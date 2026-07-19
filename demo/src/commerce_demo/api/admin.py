"""Operational and administrative APIs with role-gated branches."""

from __future__ import annotations

from decimal import Decimal

from flask import Blueprint, current_app, jsonify, request

from ..errors import PermissionDeniedError, ValidationError
from ..models import OrderStatus
from .common import container, json_body, request_role


admin_api = Blueprint("admin", __name__, url_prefix="/api/v1/admin")


def require_role(*allowed: str) -> str:
    role = request_role()
    if role not in allowed:
        raise PermissionDeniedError(f"one of these roles is required: {', '.join(allowed)}")
    return role


@admin_api.get("/metrics")
def metrics():
    require_role("admin", "support", "warehouse")
    store = container().store
    by_status = {status.value: 0 for status in OrderStatus}
    revenue = Decimal("0.00")
    for order in store.orders.values():
        by_status[order.status.value] += 1
        if order.status in {OrderStatus.CONFIRMED, OrderStatus.PACKED, OrderStatus.SHIPPED, OrderStatus.DELIVERED}:
            revenue += order.total - order.refunded_amount

    low_stock = 0
    out_of_stock = 0
    backordered = 0
    for record in store.inventory.values():
        if record.available <= 0:
            out_of_stock += 1
        elif record.available <= 5:
            low_stock += 1
        if record.available < 0:
            backordered += 1
    return jsonify(
        {
            "orders": {"total": len(store.orders), "by_status": by_status},
            "inventory": {
                "low_stock": low_stock,
                "out_of_stock": out_of_stock,
                "backordered": backordered,
            },
            "revenue": format(revenue, ".2f"),
            "audit_events": len(store.audit_log),
            "store_revision": store.revision,
        }
    )


@admin_api.get("/audit")
def audit_log():
    require_role("admin", "auditor")
    raw_limit = request.args.get("limit", "50")
    try:
        limit = int(raw_limit)
    except ValueError:
        raise ValidationError("limit must be an integer", field="limit") from None
    if not 1 <= limit <= 200:
        raise ValidationError("limit must be between 1 and 200", field="limit")
    events = container().store.audit_log[-limit:]
    return jsonify({"items": list(reversed(events)), "count": len(events)})


@admin_api.post("/maintenance")
def set_maintenance():
    require_role("admin")
    payload = json_body()
    enabled = payload.get("enabled")
    if not isinstance(enabled, bool):
        raise ValidationError("enabled must be a boolean", field="enabled")
    current_app.config["MAINTENANCE_MODE"] = enabled
    return jsonify({"maintenance_mode": enabled})

