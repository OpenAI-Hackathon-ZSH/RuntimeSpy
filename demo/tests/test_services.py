from __future__ import annotations

from decimal import Decimal
import unittest

from commerce_demo.container import build_container
from commerce_demo.errors import DomainError
from commerce_demo.models import CustomerTier, OrderStatus
from commerce_demo.openapi import build_openapi_spec


class CommerceServiceTests(unittest.TestCase):
    def setUp(self):
        self.services = build_container(
            {
                "ALLOW_BACKORDERS": True,
                "RISK_REVIEW_THRESHOLD": 45,
                "RISK_BLOCK_THRESHOLD": 75,
                "REFUND_WINDOW_DAYS": 30,
            }
        )

    def test_vip_quote_combines_automatic_and_coupon_discounts(self):
        quote = self.services.pricing.quote(
            customer_id="cust-vip",
            items=[{"sku": "HEADSET", "quantity": 2}],
            coupon="VIP20",
            shipping_method="express",
        )
        self.assertEqual(quote.shipping_method.value, "express")
        self.assertGreater(quote.discount, Decimal("50.00"))
        self.assertGreater(quote.total, Decimal("0.00"))

    def test_openapi_document_covers_every_api_group(self):
        specification = build_openapi_spec()
        self.assertEqual(specification["openapi"], "3.1.0")
        paths = specification["paths"]
        operation_count = sum(
            method in {"get", "post", "put", "patch", "delete"}
            for operations in paths.values()
            for method in operations
        )
        self.assertEqual(operation_count, 19)
        self.assertIn("/api/v1/orders/{order_id}/refund", paths)
        self.assertIn("/api/v1/orders/{order_id}/refund-eligibility", paths)
        self.assertIn("/api/v1/shipping/options", paths)
        self.assertIn("/api/v1/admin/maintenance", paths)

    def test_inventory_transaction_rolls_back_on_failure(self):
        original = self.services.store.stock("HEADSET").available
        with self.assertRaises(RuntimeError):
            with self.services.store.transaction():
                self.services.store.stock("HEADSET").available = 0
                raise RuntimeError("simulated downstream failure")
        self.assertEqual(self.services.store.stock("HEADSET").available, original)

    def test_backorderable_inventory_can_go_negative(self):
        quote = self.services.pricing.quote(
            customer_id="cust-standard",
            items=[{"sku": "MOUSE", "quantity": 5}],
        )
        self.services.inventory.reserve(quote.lines)
        stock = self.services.store.stock("MOUSE")
        self.assertEqual(stock.available, -2)
        self.assertEqual(stock.reserved, 5)

    def test_risk_decisions_cover_approve_review_and_block(self):
        standard = self.services.store.customer("cust-standard")
        vip = self.services.store.customer("cust-vip")
        newcomer = self.services.store.customer("cust-new")
        self.assertEqual(vip.tier, CustomerTier.VIP)

        quote = self.services.pricing.quote(
            customer_id="cust-standard",
            items=[{"sku": "HEADSET", "quantity": 1}],
        )
        approved = self.services.risk.evaluate(
            customer=standard,
            lines=quote.lines,
            total=quote.total,
            shipping_method=quote.shipping_method,
            destination_country=quote.destination_country,
            destination_state=quote.destination_state,
            client_ip="127.0.0.1",
        )
        reviewed = self.services.risk.evaluate(
            customer=newcomer,
            lines=quote.lines,
            total=quote.total,
            shipping_method=quote.shipping_method,
            destination_country=quote.destination_country,
            destination_state=quote.destination_state,
            client_ip="127.0.0.1",
        )
        blocked = self.services.risk.evaluate(
            customer=newcomer,
            lines=quote.lines,
            total=quote.total,
            shipping_method=quote.shipping_method,
            destination_country=quote.destination_country,
            destination_state=quote.destination_state,
            client_ip="203.0.113.66",
        )
        self.assertEqual(approved.decision, "approve")
        self.assertEqual(reviewed.decision, "review")
        self.assertEqual(blocked.decision, "block")

    def test_order_lifecycle_and_idempotency(self):
        payload = {
            "customer_id": "cust-standard",
            "items": [{"sku": "MOUSE", "quantity": 2}],
        }
        order, created = self.services.orders.create(
            payload,
            idempotency_key="service-test-1",
            client_ip="127.0.0.1",
        )
        replay, replay_created = self.services.orders.create(
            payload,
            idempotency_key="service-test-1",
            client_ip="127.0.0.1",
        )
        self.assertTrue(created)
        self.assertFalse(replay_created)
        self.assertEqual(order.id, replay.id)

        cancelled = self.services.orders.cancel(
            order.id,
            role="support",
            reason="customer request",
        )
        self.assertEqual(cancelled.status, OrderStatus.CANCELLED)

    def test_high_risk_order_is_rejected_before_inventory_changes(self):
        original = self.services.store.stock("HEADSET").available
        with self.assertRaises(DomainError) as raised:
            self.services.orders.create(
                {
                    "customer_id": "cust-new",
                    "items": [{"sku": "HEADSET", "quantity": 1}],
                },
                idempotency_key=None,
                client_ip="203.0.113.66",
            )
        self.assertEqual(raised.exception.code, "risk_blocked")
        self.assertEqual(self.services.store.stock("HEADSET").available, original)


if __name__ == "__main__":
    unittest.main()
