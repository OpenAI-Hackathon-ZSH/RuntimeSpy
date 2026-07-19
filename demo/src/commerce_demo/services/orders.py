"""Order orchestration spanning pricing, inventory, risk, and state changes."""

from __future__ import annotations

from datetime import timedelta
from decimal import Decimal, InvalidOperation
from uuid import uuid4

from ..errors import ConflictError, DomainError, PermissionDeniedError, ValidationError
from ..models import Order, OrderStatus, ShippingMethod, serialize, utc_now
from ..store import CommerceStore
from .inventory import InventoryService
from .pricing import PricingService
from .risk import RiskService


class OrderService:
    def __init__(
        self,
        store: CommerceStore,
        pricing: PricingService,
        inventory: InventoryService,
        risk: RiskService,
        *,
        refund_window_days: int = 30,
    ):
        self.store = store
        self.pricing = pricing
        self.inventory = inventory
        self.risk = risk
        self.refund_window_days = refund_window_days

    def create(self, payload: dict[str, object], *, idempotency_key: str | None, client_ip: str) -> tuple[Order, bool]:
        if idempotency_key and idempotency_key in self.store.idempotency_keys:
            order_id = self.store.idempotency_keys[idempotency_key]
            return self.store.order(order_id), False

        customer_id = str(payload.get("customer_id", ""))
        if not customer_id:
            raise ValidationError("customer_id is required", field="customer_id")
        customer = self.store.customer(customer_id)
        quote = self.pricing.quote(
            customer_id=customer_id,
            items=payload.get("items"),
            coupon=str(payload["coupon"]) if payload.get("coupon") else None,
            shipping_method=str(payload.get("shipping_method", "standard")),
            destination_country=str(payload.get("destination_country", customer.country)),
            destination_state=str(payload.get("destination_state", customer.state)),
        )
        risk = self.risk.evaluate(
            customer=customer,
            lines=quote.lines,
            total=quote.total,
            shipping_method=quote.shipping_method,
            destination_country=quote.destination_country,
            destination_state=quote.destination_state,
            client_ip=client_ip,
        )
        if risk.decision == "block":
            raise DomainError(
                "order was rejected by risk policy",
                code="risk_blocked",
                status_code=403,
                details={"risk": serialize(risk)},
            )

        with self.store.transaction():
            self.inventory.reserve(quote.lines)
            order = Order(
                id=f"ord_{uuid4().hex[:12]}",
                customer_id=customer_id,
                lines=quote.lines,
                status=(
                    OrderStatus.PENDING_REVIEW
                    if risk.decision == "review"
                    else OrderStatus.CONFIRMED
                ),
                subtotal=quote.subtotal,
                discount=quote.discount,
                shipping=quote.shipping,
                tax=quote.tax,
                total=quote.total,
                shipping_method=quote.shipping_method,
                destination_country=quote.destination_country,
                destination_state=quote.destination_state,
                risk=risk,
                coupon=quote.coupon,
                idempotency_key=idempotency_key,
            )
            self.store.orders[order.id] = order
            if idempotency_key:
                self.store.idempotency_keys[idempotency_key] = order.id
            customer.order_count += 1
            self.store.audit_log.append(
                {"action": "order.created", "order_id": order.id, "risk": risk.decision}
            )
        return order, True

    def list_orders(self, *, status: str | None, customer_id: str | None, minimum_total: str | None) -> list[Order]:
        orders = list(self.store.orders.values())
        if status:
            try:
                wanted_status = OrderStatus(status)
            except ValueError:
                raise ValidationError("unknown order status", field="status") from None
            orders = [order for order in orders if order.status is wanted_status]
        if customer_id:
            orders = [order for order in orders if order.customer_id == customer_id]
        if minimum_total:
            try:
                threshold = Decimal(minimum_total)
            except InvalidOperation:
                raise ValidationError("minimum_total must be numeric", field="minimum_total") from None
            orders = [order for order in orders if order.total >= threshold]
        return sorted(orders, key=lambda order: order.created_at, reverse=True)

    def cancel(self, order_id: str, *, role: str, reason: str, force: bool = False) -> Order:
        order = self.store.order(order_id)
        if order.status in {OrderStatus.CANCELLED, OrderStatus.REFUNDED}:
            raise ConflictError("order is already closed", code="order_closed")
        if order.status in {OrderStatus.SHIPPED, OrderStatus.DELIVERED}:
            if not force:
                raise ConflictError("shipped orders cannot be cancelled", code="already_shipped")
            if role not in {"admin", "support-lead"}:
                raise PermissionDeniedError("forced cancellation requires support-lead access")
        elif order.status is OrderStatus.PACKED and role not in {"admin", "warehouse"}:
            raise PermissionDeniedError("packed orders require warehouse access to cancel")
        if len(reason.strip()) < 4:
            raise ValidationError("a cancellation reason is required", field="reason")

        with self.store.transaction():
            if order.status not in {OrderStatus.SHIPPED, OrderStatus.DELIVERED}:
                self.inventory.release(order.lines)
            order.status = OrderStatus.CANCELLED
            order.updated_at = utc_now()
            self.store.audit_log.append(
                {"action": "order.cancelled", "order_id": order.id, "role": role, "reason": reason}
            )
        return order

    def ship(self, order_id: str, *, role: str, tracking_number: str | None) -> Order:
        if role not in {"admin", "warehouse"}:
            raise PermissionDeniedError("shipping requires warehouse access")
        order = self.store.order(order_id)
        if order.status is OrderStatus.PENDING_REVIEW:
            raise ConflictError("order requires risk review", code="risk_review_required")
        if order.status not in {OrderStatus.CONFIRMED, OrderStatus.PACKED}:
            raise ConflictError("order cannot be shipped in its current state", code="invalid_order_state")
        if order.shipping_method is ShippingMethod.PICKUP:
            raise ConflictError("pickup orders are not shipped", code="pickup_order")
        if not tracking_number or len(tracking_number) < 6:
            raise ValidationError("a valid tracking number is required", field="tracking_number")

        with self.store.transaction():
            self.inventory.commit_shipment(order.lines)
            order.status = OrderStatus.SHIPPED
            order.tracking_number = tracking_number
            order.updated_at = utc_now()
            self.store.audit_log.append(
                {"action": "order.shipped", "order_id": order.id, "tracking": tracking_number}
            )
        return order

    def review(self, order_id: str, *, role: str, decision: str, note: str) -> Order:
        if role not in {"admin", "risk-analyst"}:
            raise PermissionDeniedError("risk review requires analyst access")
        order = self.store.order(order_id)
        if order.status is not OrderStatus.PENDING_REVIEW:
            raise ConflictError("order is not waiting for review", code="review_not_required")
        if decision not in {"approve", "reject"}:
            raise ValidationError("decision must be approve or reject", field="decision")
        if len(note.strip()) < 4:
            raise ValidationError("a review note is required", field="note")

        with self.store.transaction():
            if decision == "approve":
                order.status = OrderStatus.CONFIRMED
            else:
                self.inventory.release(order.lines)
                order.status = OrderStatus.CANCELLED
            order.updated_at = utc_now()
            self.store.audit_log.append(
                {
                    "action": f"risk.{decision}",
                    "order_id": order.id,
                    "role": role,
                    "note": note,
                }
            )
        return order

    def refund(self, order_id: str, *, role: str, amount: object, reason: str) -> Order:
        order = self.store.order(order_id)
        if order.status in {OrderStatus.CANCELLED, OrderStatus.REFUNDED}:
            raise ConflictError("order is not refundable", code="not_refundable")
        if utc_now() - order.created_at > timedelta(days=self.refund_window_days):
            raise ConflictError("refund window has expired", code="refund_expired")
        try:
            requested = Decimal(str(amount))
        except InvalidOperation:
            raise ValidationError("amount must be numeric", field="amount") from None
        if requested <= 0:
            raise ValidationError("amount must be positive", field="amount")

        refundable = order.total - order.refunded_amount
        if requested > refundable:
            raise ValidationError("amount exceeds the refundable balance", field="amount")
        if requested > Decimal("500.00") and role not in {"admin", "finance"}:
            raise PermissionDeniedError("large refunds require finance approval")
        if len(reason.strip()) < 4:
            raise ValidationError("a refund reason is required", field="reason")

        with self.store.transaction():
            order.refunded_amount += requested
            if order.refunded_amount == order.total:
                order.status = OrderStatus.REFUNDED
                if order.tracking_number is None:
                    self.inventory.release(order.lines)
            order.updated_at = utc_now()
            self.store.audit_log.append(
                {
                    "action": "order.refunded",
                    "order_id": order.id,
                    "amount": format(requested, ".2f"),
                    "role": role,
                }
            )
        return order
