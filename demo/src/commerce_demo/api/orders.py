"""Order lifecycle APIs."""

from __future__ import annotations

from datetime import timedelta
from decimal import Decimal

from flask import Blueprint, jsonify, request

from ..models import OrderStatus, serialize, utc_now
from .common import client_ip, container, json_body, request_role


order_api = Blueprint("orders", __name__, url_prefix="/api/v1/orders")


@order_api.post("")
def create_order():
    payload = json_body()
    order, created = container().orders.create(
        payload,
        idempotency_key=request.headers.get("Idempotency-Key"),
        client_ip=client_ip(),
    )
    response = jsonify(serialize(order))
    response.status_code = 201 if created else 200
    response.headers["X-Idempotent-Replay"] = "false" if created else "true"
    return response


@order_api.get("")
def list_orders():
    orders = container().orders.list_orders(
        status=request.args.get("status"),
        customer_id=request.args.get("customer_id"),
        minimum_total=request.args.get("minimum_total"),
    )
    return jsonify({"items": [serialize(order) for order in orders], "count": len(orders)})


@order_api.get("/<order_id>")
def get_order(order_id: str):
    return jsonify(serialize(container().store.order(order_id)))


@order_api.get("/<order_id>/refund-eligibility")
def get_refund_eligibility(order_id: str):
    """Preview refund policy before support submits a refund transaction."""
    services = container()
    order = services.store.order(order_id)
    remaining = order.total - order.refunded_amount
    expires_at = order.created_at + timedelta(days=services.orders.refund_window_days)
    now = utc_now()
    reasons: list[str] = []

    if order.status in {OrderStatus.CANCELLED, OrderStatus.REFUNDED}:
        reasons.append("order_is_closed")
    if order.status is OrderStatus.PENDING_REVIEW:
        reasons.append("risk_review_pending")
    if now > expires_at:
        reasons.append("refund_window_expired")
    if remaining <= Decimal("0.00"):
        reasons.append("no_refundable_balance")

    return jsonify(
        {
            "order_id": order.id,
            "eligible": not reasons,
            "reasons": reasons,
            "refundable_amount": format(max(remaining, Decimal("0.00")), ".2f"),
            "finance_approval_required": remaining > Decimal("500.00"),
            "refund_window_expires_at": expires_at.isoformat(),
        }
    )


@order_api.post("/<order_id>/cancel")
def cancel_order(order_id: str):
    payload = json_body()
    order = container().orders.cancel(
        order_id,
        role=request_role(),
        reason=str(payload.get("reason", "")),
        force=payload.get("force") is True,
    )
    return jsonify(serialize(order))


@order_api.post("/<order_id>/ship")
def ship_order(order_id: str):
    payload = json_body()
    order = container().orders.ship(
        order_id,
        role=request_role(),
        tracking_number=(
            str(payload["tracking_number"]) if payload.get("tracking_number") else None
        ),
    )
    return jsonify(serialize(order))


@order_api.post("/<order_id>/review")
def review_order(order_id: str):
    payload = json_body()
    order = container().orders.review(
        order_id,
        role=request_role(),
        decision=str(payload.get("decision", "")),
        note=str(payload.get("note", "")),
    )
    return jsonify(serialize(order))


@order_api.post("/<order_id>/refund")
def refund_order(order_id: str):
    payload = json_body()
    order = container().orders.refund(
        order_id,
        role=request_role(),
        amount=payload.get("amount"),
        reason=str(payload.get("reason", "")),
    )
    return jsonify(serialize(order))
