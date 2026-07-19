"""Order lifecycle APIs."""

from __future__ import annotations

from flask import Blueprint, jsonify, request

from ..models import serialize
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

