"""Send branch-rich HTTP traffic to a running commerce demo server."""

from __future__ import annotations

import argparse
from dataclasses import dataclass
import json
import time
from typing import Any
from urllib.error import HTTPError
from urllib.request import Request, urlopen


@dataclass(slots=True)
class HttpResult:
    status_code: int
    body: Any
    headers: dict[str, str]


@dataclass(slots=True)
class PacedCaller:
    """Send requests one at a time with a fixed pause between them."""

    interval_seconds: float
    sent_requests: int = 0

    def __post_init__(self) -> None:
        if self.interval_seconds < 0:
            raise ValueError("request interval cannot be negative")

    def __call__(
        self,
        base_url: str,
        method: str,
        path: str,
        *,
        payload: dict[str, Any] | None = None,
        headers: dict[str, str] | None = None,
    ) -> HttpResult:
        if self.sent_requests:
            time.sleep(self.interval_seconds)
        result = call(
            base_url,
            method,
            path,
            payload=payload,
            headers=headers,
        )
        self.sent_requests += 1
        return result


def call(
    base_url: str,
    method: str,
    path: str,
    *,
    payload: dict[str, Any] | None = None,
    headers: dict[str, str] | None = None,
) -> HttpResult:
    request_headers = dict(headers or {})
    data = None
    if payload is not None:
        data = json.dumps(payload).encode("utf-8")
        request_headers["Content-Type"] = "application/json"
    request = Request(
        f"{base_url.rstrip('/')}{path}",
        data=data,
        headers=request_headers,
        method=method,
    )
    try:
        with urlopen(request, timeout=10) as response:
            status_code = response.status
            raw = response.read()
            response_headers = dict(response.headers.items())
    except HTTPError as error:
        status_code = error.code
        raw = error.read()
        response_headers = dict(error.headers.items())

    body = json.loads(raw) if raw else None
    code = body.get("error", {}).get("code") if isinstance(body, dict) else None
    suffix = f" error={code}" if code else ""
    print(f"{method:>4} {path:<46} -> {status_code}{suffix}")
    return HttpResult(status_code, body, response_headers)


def run_scenario(base_url: str, *, interval_seconds: float = 2.0) -> None:
    call = PacedCaller(interval_seconds)
    scenario_id = str(time.time_ns())

    call(base_url, "GET", "/health")
    call(base_url, "GET", "/openapi.json")
    call(base_url, "GET", "/api/v1/catalog/products")
    call(base_url, "GET", "/api/v1/catalog/products?category=audio")
    call(base_url, "GET", "/api/v1/catalog/products?low_stock=true")
    call(base_url, "GET", "/api/v1/catalog/products?include_inactive=true")
    call(base_url, "GET", "/api/v1/catalog/products/COURSE-PY")
    call(base_url, "GET", "/api/v1/catalog/products/LEGACY-DOCK")
    call(base_url, "GET", "/api/v1/catalog/products/LAPTOP-PRO")
    call(base_url, "GET", "/api/v1/catalog/products/MOUSE")
    call(base_url, "GET", "/api/v1/catalog/products/BATTERY")
    call(base_url, "GET", "/api/v1/catalog/products/UNKNOWN-SKU")

    call(
        base_url,
        "POST",
        "/api/v1/quotes",
        payload={
            "customer_id": "cust-vip",
            "items": [
                {"sku": "HEADSET", "quantity": 2},
                {"sku": "COURSE-PY", "quantity": 1},
            ],
            "coupon": "VIP20",
            "shipping_method": "express",
        },
    )
    call(
        base_url,
        "POST",
        "/api/v1/quotes",
        payload={
            "customer_id": "cust-standard",
            "items": [{"sku": "MOUSE", "quantity": 1}],
            "coupon": "EXPIRED",
        },
    )
    call(
        base_url,
        "POST",
        "/api/v1/quotes",
        payload={"customer_id": "cust-disabled", "items": [{"sku": "MOUSE"}]},
    )
    call(
        base_url,
        "POST",
        "/api/v1/quotes",
        payload={
            "customer_id": "cust-standard",
            "items": [{"sku": "HEADSET"}],
            "shipping_method": "teleport",
        },
    )
    call(
        base_url,
        "POST",
        "/api/v1/quotes",
        payload={"customer_id": "cust-standard", "items": []},
    )
    call(
        base_url,
        "POST",
        "/api/v1/quotes",
        payload={
            "customer_id": "cust-standard",
            "items": [{"sku": "MOUSE"}, {"sku": "MOUSE"}],
        },
    )
    call(
        base_url,
        "POST",
        "/api/v1/quotes",
        payload={
            "customer_id": "cust-standard",
            "items": [{"sku": "HEADSET", "quantity": 26}],
        },
    )
    call(
        base_url,
        "POST",
        "/api/v1/quotes",
        payload={
            "customer_id": "cust-standard",
            "items": [{"sku": "LEGACY-DOCK"}],
        },
    )
    call(
        base_url,
        "POST",
        "/api/v1/quotes",
        payload={
            "customer_id": "cust-standard",
            "items": [{"sku": "BATTERY"}],
            "destination_country": "CA",
        },
    )
    call(
        base_url,
        "POST",
        "/api/v1/quotes",
        payload={
            "customer_id": "cust-standard",
            "items": [{"sku": "HEADSET"}],
            "coupon": "FREESHIP",
        },
    )
    call(
        base_url,
        "POST",
        "/api/v1/quotes",
        payload={
            "customer_id": "cust-standard",
            "items": [{"sku": "MOUSE"}],
            "coupon": "NOT-A-COUPON",
        },
    )
    call(
        base_url,
        "POST",
        "/api/v1/quotes",
        payload={
            "customer_id": "cust-plus",
            "items": [{"sku": "MOUSE", "quantity": 5}],
            "destination_state": "NY",
        },
    )
    call(
        base_url,
        "POST",
        "/api/v1/quotes",
        payload={
            "customer_id": "cust-standard",
            "items": [{"sku": "COURSE-PY"}],
            "shipping_method": "same_day",
        },
    )

    call(
        base_url,
        "POST",
        "/api/v1/risk/evaluate",
        payload={
            "customer_id": "cust-plus",
            "items": [{"sku": "LAPTOP-PRO"}],
            "shipping_method": "same_day",
            "destination_state": "NY",
        },
        headers={"X-Forwarded-For": "198.51.100.9"},
    )

    normal_payload = {
        "customer_id": "cust-standard",
        "items": [
            {"sku": "HEADSET", "quantity": 1},
            {"sku": "MOUSE", "quantity": 2},
        ],
        "coupon": "SAVE10",
        "shipping_method": "standard",
    }
    created = call(
        base_url,
        "POST",
        "/api/v1/orders",
        payload=normal_payload,
        headers={"Idempotency-Key": "traffic-normal-1"},
    )
    normal_order_id = created.body["id"]
    call(
        base_url,
        "POST",
        "/api/v1/orders",
        payload=normal_payload,
        headers={"Idempotency-Key": "traffic-normal-1"},
    )
    call(base_url, "GET", f"/api/v1/orders/{normal_order_id}")
    call(base_url, "GET", "/api/v1/orders?status=confirmed&minimum_total=50")
    call(base_url, "GET", "/api/v1/orders?status=unknown")
    call(base_url, "GET", "/api/v1/orders?minimum_total=not-a-number")
    call(base_url, "GET", "/api/v1/orders/ord_missing")

    review_payload = {
        "customer_id": "cust-new",
        "items": [{"sku": "HEADSET", "quantity": 1}],
        "shipping_method": "standard",
    }
    review_response = call(
        base_url,
        "POST",
        "/api/v1/orders",
        payload=review_payload,
    )
    review_order_id = review_response.body["id"]
    call(
        base_url,
        "POST",
        f"/api/v1/orders/{review_order_id}/review",
        payload={"decision": "approve", "note": "identity verified"},
        headers={"X-Role": "risk-analyst"},
    )
    call(
        base_url,
        "POST",
        f"/api/v1/orders/{review_order_id}/ship",
        payload={"tracking_number": "TRACK-10001"},
        headers={"X-Role": "warehouse"},
    )
    call(
        base_url,
        "POST",
        f"/api/v1/orders/{review_order_id}/refund",
        payload={"amount": "20.00", "reason": "delivery delay"},
        headers={"X-Role": "support"},
    )

    shipped_response = call(
        base_url,
        "POST",
        "/api/v1/orders",
        payload={
            "customer_id": "cust-plus",
            "items": [{"sku": "HEADSET", "quantity": 1}],
            "shipping_method": "express",
        },
        headers={"Idempotency-Key": f"traffic-shipped-{scenario_id}"},
    )
    shipped_order_id = shipped_response.body["id"]
    call(
        base_url,
        "POST",
        f"/api/v1/orders/{shipped_order_id}/ship",
        payload={"tracking_number": "TRACK-20001"},
    )
    call(
        base_url,
        "POST",
        f"/api/v1/orders/{shipped_order_id}/ship",
        payload={"tracking_number": "TRACK-20001"},
        headers={"X-Role": "warehouse"},
    )
    call(
        base_url,
        "POST",
        f"/api/v1/orders/{shipped_order_id}/cancel",
        payload={"reason": "requested after shipment"},
        headers={"X-Role": "support"},
    )
    call(
        base_url,
        "POST",
        f"/api/v1/orders/{shipped_order_id}/cancel",
        payload={"reason": "requested after shipment", "force": True},
        headers={"X-Role": "support"},
    )
    call(
        base_url,
        "POST",
        f"/api/v1/orders/{shipped_order_id}/cancel",
        payload={"reason": "requested after shipment", "force": True},
        headers={"X-Role": "support-lead"},
    )

    rejected_response = call(
        base_url,
        "POST",
        "/api/v1/orders",
        payload=review_payload,
        headers={"Idempotency-Key": f"traffic-reject-{scenario_id}"},
    )
    rejected_order_id = rejected_response.body["id"]
    call(
        base_url,
        "POST",
        f"/api/v1/orders/{rejected_order_id}/review",
        payload={"decision": "approve", "note": "identity verified"},
    )
    call(
        base_url,
        "POST",
        f"/api/v1/orders/{rejected_order_id}/review",
        payload={"decision": "wait", "note": "identity verified"},
        headers={"X-Role": "risk-analyst"},
    )
    call(
        base_url,
        "POST",
        f"/api/v1/orders/{rejected_order_id}/review",
        payload={"decision": "reject", "note": "identity could not be verified"},
        headers={"X-Role": "risk-analyst"},
    )

    large_refund_response = call(
        base_url,
        "POST",
        "/api/v1/orders",
        payload={
            "customer_id": "cust-vip",
            "items": [{"sku": "LAPTOP-PRO"}],
            "shipping_method": "standard",
        },
        headers={"Idempotency-Key": f"traffic-refund-{scenario_id}"},
    )
    large_refund_order_id = large_refund_response.body["id"]
    call(
        base_url,
        "POST",
        f"/api/v1/orders/{large_refund_order_id}/refund",
        payload={"amount": "not-a-number", "reason": "testing validation"},
        headers={"X-Role": "support"},
    )
    call(
        base_url,
        "POST",
        f"/api/v1/orders/{large_refund_order_id}/refund",
        payload={"amount": "600.00", "reason": "testing authorization"},
        headers={"X-Role": "support"},
    )
    call(
        base_url,
        "POST",
        f"/api/v1/orders/{large_refund_order_id}/refund",
        payload={"amount": "600.00", "reason": "finance approved return"},
        headers={"X-Role": "finance"},
    )
    call(
        base_url,
        "POST",
        f"/api/v1/orders/{large_refund_order_id}/refund",
        payload={"amount": "9999.00", "reason": "testing refund limit"},
        headers={"X-Role": "finance"},
    )

    call(
        base_url,
        "POST",
        "/api/v1/orders",
        payload=review_payload,
        headers={"X-Forwarded-For": "203.0.113.66"},
    )
    call(
        base_url,
        "POST",
        f"/api/v1/orders/{normal_order_id}/cancel",
        payload={"reason": "customer changed mind"},
        headers={"X-Role": "support"},
    )

    call(base_url, "GET", "/api/v1/inventory/MOUSE")
    call(
        base_url,
        "POST",
        "/api/v1/inventory/MOUSE/adjust",
        payload={"delta": 10, "reason": "warehouse delivery"},
    )
    call(
        base_url,
        "POST",
        "/api/v1/inventory/MOUSE/adjust",
        payload={"delta": 10, "reason": "warehouse delivery"},
        headers={"X-Role": "warehouse"},
    )
    call(
        base_url,
        "POST",
        "/api/v1/inventory/MOUSE/adjust",
        payload={"delta": 0, "reason": "invalid adjustment"},
        headers={"X-Role": "warehouse"},
    )
    call(
        base_url,
        "POST",
        "/api/v1/inventory/MOUSE/adjust",
        payload={"delta": -500, "reason": "negative inventory"},
        headers={"X-Role": "warehouse"},
    )
    call(
        base_url,
        "POST",
        "/api/v1/inventory/UNKNOWN-SKU/adjust",
        payload={"delta": 1, "reason": "missing inventory"},
        headers={"X-Role": "warehouse"},
    )
    call(base_url, "GET", "/api/v1/admin/metrics")
    call(base_url, "GET", "/api/v1/admin/metrics", headers={"X-Role": "support"})
    call(base_url, "GET", "/api/v1/admin/audit?limit=invalid", headers={"X-Role": "auditor"})
    call(base_url, "GET", "/api/v1/admin/audit?limit=0", headers={"X-Role": "auditor"})
    call(base_url, "GET", "/api/v1/admin/audit?limit=10", headers={"X-Role": "auditor"})

    call(
        base_url,
        "POST",
        "/api/v1/admin/maintenance",
        payload={"enabled": "yes"},
        headers={"X-Role": "admin"},
    )

    call(
        base_url,
        "POST",
        "/api/v1/admin/maintenance",
        payload={"enabled": True},
        headers={"X-Role": "admin"},
    )
    call(base_url, "GET", "/api/v1/catalog/products")
    call(base_url, "GET", "/health")
    call(
        base_url,
        "POST",
        "/api/v1/admin/maintenance",
        payload={"enabled": False},
        headers={"X-Role": "admin"},
    )


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--base-url", default="http://34.239.92.98/")
    parser.add_argument(
        "--interval",
        type=float,
        default=2.0,
        help="seconds between requests (default: 2.0; use 0 for no delay)",
    )
    args = parser.parse_args()
    if args.interval < 0:
        parser.error("--interval cannot be negative")
    run_scenario(args.base_url, interval_seconds=args.interval)
    print("\nTraffic complete. Stop the server to write its final RuntimeSpy JSON.")


if __name__ == "__main__":
    main()
