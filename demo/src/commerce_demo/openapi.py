"""OpenAPI 3.1 document used by the locally hosted Swagger UI."""

from __future__ import annotations

from typing import Any


def _parameter(
    name: str,
    location: str,
    description: str,
    *,
    required: bool = False,
    schema: dict[str, Any] | None = None,
) -> dict[str, Any]:
    return {
        "name": name,
        "in": location,
        "description": description,
        "required": required,
        "schema": schema or {"type": "string"},
    }


def _operation(
    operation_id: str,
    summary: str,
    tag: str,
    *,
    request_schema: str | None = None,
    parameters: list[dict[str, Any]] | None = None,
    success_status: str = "200",
    success_description: str = "Successful response",
) -> dict[str, Any]:
    value: dict[str, Any] = {
        "operationId": operation_id,
        "summary": summary,
        "tags": [tag],
        "parameters": parameters or [],
        "responses": {
            success_status: {
                "description": success_description,
                "content": {
                    "application/json": {
                        "schema": {"type": "object", "additionalProperties": True}
                    }
                },
            },
            "4XX": {
                "description": "Validation, permission, conflict, or not-found error",
                "content": {
                    "application/json": {
                        "schema": {"$ref": "#/components/schemas/ErrorResponse"}
                    }
                },
            },
        },
    }
    if request_schema:
        value["requestBody"] = {
            "required": True,
            "content": {
                "application/json": {
                    "schema": {"$ref": f"#/components/schemas/{request_schema}"}
                }
            },
        }
    return value


def build_openapi_spec() -> dict[str, Any]:
    role = {"$ref": "#/components/parameters/RoleHeader"}
    sku = _parameter("sku", "path", "Product SKU", required=True)
    order_id = _parameter("order_id", "path", "Order identifier", required=True)
    return {
        "openapi": "3.1.0",
        "info": {
            "title": "RuntimeSpy Commerce Demo API",
            "version": "1.0.0",
            "description": (
                "A branch-rich Flask commerce API used to generate RuntimeSpy "
                "control-flow graphs. Use X-Role to exercise permission branches."
            ),
        },
        "servers": [{"url": "/", "description": "Current demo server"}],
        "tags": [
            {"name": "System"},
            {"name": "Catalog"},
            {"name": "Pricing"},
            {"name": "Inventory"},
            {"name": "Risk"},
            {"name": "Orders"},
            {"name": "Admin"},
        ],
        "paths": {
            "/health": {
                "get": _operation("getHealth", "Read service health", "System")
            },
            "/api/v1/catalog/products": {
                "get": _operation(
                    "listProducts",
                    "List and filter catalog products",
                    "Catalog",
                    parameters=[
                        _parameter("category", "query", "Exact product category"),
                        _parameter(
                            "include_inactive",
                            "query",
                            "Include discontinued products",
                            schema={"type": "boolean", "default": False},
                        ),
                        _parameter(
                            "low_stock",
                            "query",
                            "Only include products with at most five available units",
                            schema={"type": "boolean", "default": False},
                        ),
                    ],
                )
            },
            "/api/v1/catalog/products/{sku}": {
                "get": _operation(
                    "getProduct",
                    "Get product and availability details",
                    "Catalog",
                    parameters=[sku],
                )
            },
            "/api/v1/quotes": {
                "post": _operation(
                    "createQuote",
                    "Calculate discounts, shipping, tax, and total",
                    "Pricing",
                    request_schema="QuoteRequest",
                )
            },
            "/api/v1/shipping/options": {
                "post": _operation(
                    "previewShippingOptions",
                    "List delivery options available to a checkout",
                    "Pricing",
                    request_schema="QuoteRequest",
                )
            },
            "/api/v1/inventory/{sku}": {
                "get": _operation(
                    "getInventory",
                    "Read inventory for a SKU",
                    "Inventory",
                    parameters=[sku],
                )
            },
            "/api/v1/inventory/{sku}/adjust": {
                "post": _operation(
                    "adjustInventory",
                    "Adjust inventory as warehouse or admin",
                    "Inventory",
                    request_schema="InventoryAdjustmentRequest",
                    parameters=[sku, role],
                )
            },
            "/api/v1/risk/evaluate": {
                "post": _operation(
                    "evaluateRisk",
                    "Evaluate an order without creating it",
                    "Risk",
                    request_schema="RiskRequest",
                    parameters=[
                        _parameter(
                            "X-Forwarded-For",
                            "header",
                            "Client IP; use 203.0.113.66 to exercise a blocked-IP branch",
                        )
                    ],
                )
            },
            "/api/v1/orders": {
                "post": _operation(
                    "createOrder",
                    "Create an idempotent order",
                    "Orders",
                    request_schema="OrderRequest",
                    parameters=[
                        {"$ref": "#/components/parameters/IdempotencyKey"},
                        _parameter("X-Forwarded-For", "header", "Client IP for risk scoring"),
                    ],
                    success_status="201",
                    success_description="Order created",
                ),
                "get": _operation(
                    "listOrders",
                    "List and filter orders",
                    "Orders",
                    parameters=[
                        _parameter(
                            "status",
                            "query",
                            "Order status",
                            schema={"$ref": "#/components/schemas/OrderStatus"},
                        ),
                        _parameter("customer_id", "query", "Customer identifier"),
                        _parameter(
                            "minimum_total",
                            "query",
                            "Minimum order total",
                            schema={"type": "number", "minimum": 0},
                        ),
                    ],
                ),
            },
            "/api/v1/orders/{order_id}": {
                "get": _operation(
                    "getOrder",
                    "Get order details",
                    "Orders",
                    parameters=[order_id],
                )
            },
            "/api/v1/orders/{order_id}/refund-eligibility": {
                "get": _operation(
                    "getRefundEligibility",
                    "Preview refundable balance and policy eligibility",
                    "Orders",
                    parameters=[order_id],
                )
            },
            "/api/v1/orders/{order_id}/cancel": {
                "post": _operation(
                    "cancelOrder",
                    "Cancel an order with state and role checks",
                    "Orders",
                    request_schema="CancelOrderRequest",
                    parameters=[order_id, role],
                )
            },
            "/api/v1/orders/{order_id}/review": {
                "post": _operation(
                    "reviewOrder",
                    "Approve or reject a pending risk review",
                    "Risk",
                    request_schema="ReviewOrderRequest",
                    parameters=[order_id, role],
                )
            },
            "/api/v1/orders/{order_id}/ship": {
                "post": _operation(
                    "shipOrder",
                    "Ship a confirmed order",
                    "Orders",
                    request_schema="ShipOrderRequest",
                    parameters=[order_id, role],
                )
            },
            "/api/v1/orders/{order_id}/refund": {
                "post": _operation(
                    "refundOrder",
                    "Issue a partial or full refund",
                    "Orders",
                    request_schema="RefundOrderRequest",
                    parameters=[order_id, role],
                )
            },
            "/api/v1/admin/metrics": {
                "get": _operation(
                    "getMetrics",
                    "Read operational metrics",
                    "Admin",
                    parameters=[role],
                )
            },
            "/api/v1/admin/audit": {
                "get": _operation(
                    "getAuditLog",
                    "Read recent audit events",
                    "Admin",
                    parameters=[
                        role,
                        _parameter(
                            "limit",
                            "query",
                            "Maximum events",
                            schema={"type": "integer", "minimum": 1, "maximum": 200, "default": 50},
                        ),
                    ],
                )
            },
            "/api/v1/admin/maintenance": {
                "post": _operation(
                    "setMaintenance",
                    "Enable or disable maintenance mode",
                    "Admin",
                    request_schema="MaintenanceRequest",
                    parameters=[role],
                )
            },
        },
        "components": {
            "parameters": {
                "RoleHeader": _parameter(
                    "X-Role",
                    "header",
                    "Demo role: customer, support, support-lead, warehouse, "
                    "risk-analyst, finance, auditor, or admin",
                    schema={"type": "string", "default": "customer"},
                ),
                "IdempotencyKey": _parameter(
                    "Idempotency-Key",
                    "header",
                    "Reusing a key returns the original order",
                ),
            },
            "schemas": {
                "OrderStatus": {
                    "type": "string",
                    "enum": [
                        "pending_review",
                        "confirmed",
                        "packed",
                        "shipped",
                        "delivered",
                        "cancelled",
                        "refunded",
                    ],
                },
                "LineItemRequest": {
                    "type": "object",
                    "required": ["sku", "quantity"],
                    "properties": {
                        "sku": {"type": "string", "example": "HEADSET"},
                        "quantity": {"type": "integer", "minimum": 1, "maximum": 25, "example": 2},
                    },
                },
                "QuoteRequest": {
                    "type": "object",
                    "required": ["customer_id", "items"],
                    "properties": {
                        "customer_id": {"type": "string", "example": "cust-vip"},
                        "items": {
                            "type": "array",
                            "minItems": 1,
                            "items": {"$ref": "#/components/schemas/LineItemRequest"},
                        },
                        "coupon": {"type": ["string", "null"], "example": "VIP20"},
                        "shipping_method": {
                            "type": "string",
                            "enum": ["standard", "express", "same_day", "pickup"],
                            "default": "standard",
                        },
                        "destination_country": {"type": "string", "example": "US"},
                        "destination_state": {"type": "string", "example": "CA"},
                    },
                },
                "OrderRequest": {"$ref": "#/components/schemas/QuoteRequest"},
                "RiskRequest": {"$ref": "#/components/schemas/QuoteRequest"},
                "InventoryAdjustmentRequest": {
                    "type": "object",
                    "required": ["delta", "reason"],
                    "properties": {
                        "delta": {"type": "integer", "minimum": -500, "maximum": 500, "example": 10},
                        "reason": {"type": "string", "minLength": 4, "example": "warehouse delivery"},
                    },
                },
                "CancelOrderRequest": {
                    "type": "object",
                    "required": ["reason"],
                    "properties": {
                        "reason": {"type": "string", "example": "customer changed mind"},
                        "force": {"type": "boolean", "default": False},
                    },
                },
                "ReviewOrderRequest": {
                    "type": "object",
                    "required": ["decision", "note"],
                    "properties": {
                        "decision": {"type": "string", "enum": ["approve", "reject"]},
                        "note": {"type": "string", "example": "identity verified"},
                    },
                },
                "ShipOrderRequest": {
                    "type": "object",
                    "required": ["tracking_number"],
                    "properties": {
                        "tracking_number": {"type": "string", "example": "TRACK-10001"}
                    },
                },
                "RefundOrderRequest": {
                    "type": "object",
                    "required": ["amount", "reason"],
                    "properties": {
                        "amount": {"type": "number", "exclusiveMinimum": 0, "example": 20.00},
                        "reason": {"type": "string", "example": "delivery delay"},
                    },
                },
                "MaintenanceRequest": {
                    "type": "object",
                    "required": ["enabled"],
                    "properties": {"enabled": {"type": "boolean", "example": True}},
                },
                "ErrorResponse": {
                    "type": "object",
                    "required": ["error"],
                    "properties": {
                        "error": {
                            "type": "object",
                            "required": ["code", "message"],
                            "properties": {
                                "code": {"type": "string"},
                                "message": {"type": "string"},
                                "details": {"type": "object", "additionalProperties": True},
                            },
                        }
                    },
                },
            },
        },
    }
