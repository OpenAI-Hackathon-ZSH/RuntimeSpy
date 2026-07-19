from __future__ import annotations

import unittest

from commerce_demo import create_app


class CommerceApiTests(unittest.TestCase):
    def setUp(self):
        self.app = create_app({"TESTING": True})
        self.client = self.app.test_client()

    def test_catalog_and_vip_quote(self):
        catalog = self.client.get("/api/v1/catalog/products")
        self.assertEqual(catalog.status_code, 200)
        self.assertEqual(catalog.get_json()["count"], 5)

        quote = self.client.post(
            "/api/v1/quotes",
            json={
                "customer_id": "cust-vip",
                "items": [{"sku": "HEADSET", "quantity": 2}],
                "coupon": "VIP20",
                "shipping_method": "express",
            },
        )
        self.assertEqual(quote.status_code, 200)
        self.assertEqual(quote.get_json()["shipping_method"], "express")
        self.assertGreater(float(quote.get_json()["discount"]), 0)

    def test_swagger_and_openapi_are_available(self):
        specification = self.client.get("/openapi.json")
        self.assertEqual(specification.status_code, 200)
        self.assertEqual(specification.get_json()["openapi"], "3.1.0")
        self.assertIn("/api/v1/orders", specification.get_json()["paths"])

        swagger = self.client.get("/docs/")
        self.assertEqual(swagger.status_code, 200)
        self.assertIn("Swagger UI", swagger.get_data(as_text=True))

    def test_order_idempotency_and_cancellation(self):
        payload = {
            "customer_id": "cust-standard",
            "items": [{"sku": "MOUSE", "quantity": 2}],
            "shipping_method": "standard",
        }
        headers = {"Idempotency-Key": "test-order-1"}
        first = self.client.post("/api/v1/orders", json=payload, headers=headers)
        replay = self.client.post("/api/v1/orders", json=payload, headers=headers)
        self.assertEqual(first.status_code, 201)
        self.assertEqual(replay.status_code, 200)
        self.assertEqual(first.get_json()["id"], replay.get_json()["id"])
        self.assertEqual(replay.headers["X-Idempotent-Replay"], "true")

        cancelled = self.client.post(
            f"/api/v1/orders/{first.get_json()['id']}/cancel",
            json={"reason": "duplicate purchase"},
            headers={"X-Role": "support"},
        )
        self.assertEqual(cancelled.status_code, 200)
        self.assertEqual(cancelled.get_json()["status"], "cancelled")

    def test_high_risk_order_is_blocked(self):
        response = self.client.post(
            "/api/v1/orders",
            json={
                "customer_id": "cust-new",
                "items": [{"sku": "HEADSET", "quantity": 1}],
            },
            headers={"X-Forwarded-For": "203.0.113.66"},
        )
        self.assertEqual(response.status_code, 403)
        self.assertEqual(response.get_json()["error"]["code"], "risk_blocked")

    def test_review_then_ship_order(self):
        created = self.client.post(
            "/api/v1/orders",
            json={
                "customer_id": "cust-new",
                "items": [{"sku": "HEADSET", "quantity": 1}],
            },
        )
        self.assertEqual(created.status_code, 201)
        self.assertEqual(created.get_json()["status"], "pending_review")
        order_id = created.get_json()["id"]

        reviewed = self.client.post(
            f"/api/v1/orders/{order_id}/review",
            json={"decision": "approve", "note": "identity verified"},
            headers={"X-Role": "risk-analyst"},
        )
        self.assertEqual(reviewed.get_json()["status"], "confirmed")

        shipped = self.client.post(
            f"/api/v1/orders/{order_id}/ship",
            json={"tracking_number": "TRACK-10001"},
            headers={"X-Role": "warehouse"},
        )
        self.assertEqual(shipped.status_code, 200)
        self.assertEqual(shipped.get_json()["status"], "shipped")

    def test_inventory_adjustment_requires_role(self):
        denied = self.client.post(
            "/api/v1/inventory/MOUSE/adjust",
            json={"delta": 5, "reason": "new delivery"},
        )
        self.assertEqual(denied.status_code, 403)

        allowed = self.client.post(
            "/api/v1/inventory/MOUSE/adjust",
            json={"delta": 5, "reason": "new delivery"},
            headers={"X-Role": "warehouse"},
        )
        self.assertEqual(allowed.status_code, 200)
        self.assertEqual(allowed.get_json()["available"], 8)

    def test_large_refund_requires_finance(self):
        created = self.client.post(
            "/api/v1/orders",
            json={
                "customer_id": "cust-vip",
                "items": [{"sku": "LAPTOP-PRO", "quantity": 1}],
            },
        )
        order_id = created.get_json()["id"]
        denied = self.client.post(
            f"/api/v1/orders/{order_id}/refund",
            json={"amount": "600.00", "reason": "damaged device"},
            headers={"X-Role": "support"},
        )
        self.assertEqual(denied.status_code, 403)

        approved = self.client.post(
            f"/api/v1/orders/{order_id}/refund",
            json={"amount": "600.00", "reason": "damaged device"},
            headers={"X-Role": "finance"},
        )
        self.assertEqual(approved.status_code, 200)
        self.assertEqual(approved.get_json()["refunded_amount"], "600.00")

    def test_maintenance_mode_blocks_non_admin_traffic(self):
        enabled = self.client.post(
            "/api/v1/admin/maintenance",
            json={"enabled": True},
            headers={"X-Role": "admin"},
        )
        self.assertEqual(enabled.status_code, 200)
        self.assertEqual(self.client.get("/api/v1/catalog/products").status_code, 503)
        self.assertEqual(self.client.get("/health").get_json()["status"], "maintenance")

        disabled = self.client.post(
            "/api/v1/admin/maintenance",
            json={"enabled": False},
            headers={"X-Role": "admin"},
        )
        self.assertEqual(disabled.status_code, 200)


if __name__ == "__main__":
    unittest.main()
