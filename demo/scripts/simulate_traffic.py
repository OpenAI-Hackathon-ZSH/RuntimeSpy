"""Exercise common and exceptional API paths, then write RuntimeSpy's graph."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import runtimespy


PROJECT_ROOT = Path(__file__).resolve().parents[1]
session = runtimespy.init(project_root=PROJECT_ROOT, context="simulated-api-traffic")

from commerce_demo import create_app  # noqa: E402


app = create_app({"TESTING": True})
client = app.test_client()


def call(
    method: str,
    path: str,
    *,
    json: dict[str, Any] | None = None,
    headers: dict[str, str] | None = None,
):
    response = client.open(path, method=method, json=json, headers=headers or {})
    body = response.get_json(silent=True)
    code = body.get("error", {}).get("code") if isinstance(body, dict) else None
    suffix = f" error={code}" if code else ""
    print(f"{method:>4} {path:<46} -> {response.status_code}{suffix}")
    return response


def main() -> None:
    call("GET", "/health")
    call("GET", "/api/v1/catalog/products")
    call("GET", "/api/v1/catalog/products?category=audio")
    call("GET", "/api/v1/catalog/products?low_stock=true")
    call("GET", "/api/v1/catalog/products/COURSE-PY")
    call("GET", "/api/v1/catalog/products/LEGACY-DOCK")

    call(
        "POST",
        "/api/v1/quotes",
        json={
            "customer_id": "cust-vip",
            "items": [{"sku": "HEADSET", "quantity": 2}, {"sku": "COURSE-PY", "quantity": 1}],
            "coupon": "VIP20",
            "shipping_method": "express",
        },
    )
    call(
        "POST",
        "/api/v1/quotes",
        json={
            "customer_id": "cust-standard",
            "items": [{"sku": "MOUSE", "quantity": 1}],
            "coupon": "EXPIRED",
        },
    )

    normal_payload = {
        "customer_id": "cust-standard",
        "items": [{"sku": "HEADSET", "quantity": 1}, {"sku": "MOUSE", "quantity": 2}],
        "coupon": "SAVE10",
        "shipping_method": "standard",
    }
    created = call(
        "POST",
        "/api/v1/orders",
        json=normal_payload,
        headers={"Idempotency-Key": "traffic-normal-1"},
    )
    normal_order_id = created.get_json()["id"]
    call(
        "POST",
        "/api/v1/orders",
        json=normal_payload,
        headers={"Idempotency-Key": "traffic-normal-1"},
    )
    call("GET", f"/api/v1/orders/{normal_order_id}")
    call("GET", "/api/v1/orders?status=confirmed&minimum_total=50")

    review_payload = {
        "customer_id": "cust-new",
        "items": [{"sku": "HEADSET", "quantity": 1}],
        "shipping_method": "standard",
    }
    review_response = call("POST", "/api/v1/orders", json=review_payload)
    review_order_id = review_response.get_json()["id"]
    call(
        "POST",
        f"/api/v1/orders/{review_order_id}/review",
        json={"decision": "approve", "note": "identity verified"},
        headers={"X-Role": "risk-analyst"},
    )
    call(
        "POST",
        f"/api/v1/orders/{review_order_id}/ship",
        json={"tracking_number": "TRACK-10001"},
        headers={"X-Role": "warehouse"},
    )
    call(
        "POST",
        f"/api/v1/orders/{review_order_id}/refund",
        json={"amount": "20.00", "reason": "delivery delay"},
        headers={"X-Role": "support"},
    )

    call(
        "POST",
        "/api/v1/orders",
        json=review_payload,
        headers={"X-Forwarded-For": "203.0.113.66"},
    )
    call(
        "POST",
        f"/api/v1/orders/{normal_order_id}/cancel",
        json={"reason": "customer changed mind"},
        headers={"X-Role": "support"},
    )

    call("GET", "/api/v1/inventory/MOUSE")
    call(
        "POST",
        "/api/v1/inventory/MOUSE/adjust",
        json={"delta": 10, "reason": "warehouse delivery"},
    )
    call(
        "POST",
        "/api/v1/inventory/MOUSE/adjust",
        json={"delta": 10, "reason": "warehouse delivery"},
        headers={"X-Role": "warehouse"},
    )
    call("GET", "/api/v1/admin/metrics", headers={"X-Role": "support"})
    call("GET", "/api/v1/admin/audit?limit=10", headers={"X-Role": "auditor"})

    call(
        "POST",
        "/api/v1/admin/maintenance",
        json={"enabled": True},
        headers={"X-Role": "admin"},
    )
    call("GET", "/api/v1/catalog/products")
    call("GET", "/health")
    call(
        "POST",
        "/api/v1/admin/maintenance",
        json={"enabled": False},
        headers={"X-Role": "admin"},
    )

    session.stop()
    print(f"\nRuntimeSpy graph written to {session.export_path}")


if __name__ == "__main__":
    main()

