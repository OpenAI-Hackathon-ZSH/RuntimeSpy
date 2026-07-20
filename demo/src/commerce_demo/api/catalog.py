"""Catalog, quote, inventory, and standalone risk APIs."""

from __future__ import annotations

from flask import Blueprint, jsonify, request

from ..errors import ConflictError
from ..models import ShippingMethod, serialize
from .common import client_ip, container, json_body, request_role


catalog_api = Blueprint("catalog", __name__, url_prefix="/api/v1")


@catalog_api.get("/catalog/products")
def list_products():
    services = container()
    category = request.args.get("category")
    include_inactive = request.args.get("include_inactive") == "true"
    only_low_stock = request.args.get("low_stock") == "true"
    values: list[dict[str, object]] = []
    for product in services.store.products.values():
        if not include_inactive and not product.active:
            continue
        if category and product.category != category:
            continue
        stock = services.store.stock(product.sku)
        if only_low_stock and stock.available > 5:
            continue
        value = serialize(product)
        value["inventory"] = {
            "available": stock.available,
            "reserved": stock.reserved,
            "backorderable": stock.backorderable,
        }
        values.append(value)
    return jsonify({"items": values, "count": len(values)})


@catalog_api.get("/catalog/products/<sku>")
def get_product(sku: str):
    services = container()
    product = services.store.product(sku.upper())
    stock = services.store.stock(product.sku)
    value = serialize(product)
    value["inventory"] = serialize(stock)
    if not product.active:
        value["availability"] = "discontinued"
    elif product.digital:
        value["availability"] = "instant"
    elif stock.available > 0:
        value["availability"] = "in_stock"
    elif stock.backorderable:
        value["availability"] = "backorder"
    else:
        value["availability"] = "out_of_stock"
    return jsonify(value)


@catalog_api.post("/quotes")
def create_quote():
    payload = json_body()
    quote = container().pricing.quote(
        customer_id=str(payload.get("customer_id", "")),
        items=payload.get("items"),
        coupon=str(payload["coupon"]) if payload.get("coupon") else None,
        shipping_method=str(payload.get("shipping_method", "standard")),
        destination_country=(
            str(payload["destination_country"])
            if payload.get("destination_country")
            else None
        ),
        destination_state=(
            str(payload["destination_state"])
            if payload.get("destination_state")
            else None
        ),
    )
    return jsonify(quote.as_dict())


@catalog_api.post("/shipping/options")
def preview_shipping_options():
    """Return the delivery choices a checkout can present before payment."""
    payload = json_body()
    services = container()
    customer_id = str(payload.get("customer_id", ""))
    customer = services.store.customer(customer_id)
    country = str(payload.get("destination_country", customer.country)).upper()
    state = str(payload.get("destination_state", customer.state)).upper()
    items = payload.get("items")
    options: list[dict[str, object]] = []

    for method, label, eta_days in (
        (ShippingMethod.STANDARD, "Standard delivery", 5),
        (ShippingMethod.EXPRESS, "Express delivery", 2),
        (ShippingMethod.SAME_DAY, "Same-day delivery", 0),
        (ShippingMethod.PICKUP, "Store pickup", 0),
    ):
        try:
            quote = services.pricing.quote(
                customer_id=customer_id,
                items=items,
                shipping_method=method.value,
                destination_country=country,
                destination_state=state,
            )
        except ConflictError:
            continue
        if all(services.store.product(line.sku).digital for line in quote.lines):
            if method is not ShippingMethod.STANDARD:
                continue
            label = "Instant digital delivery"
            eta_days = 0
        options.append(
            {
                "method": method.value,
                "label": label,
                "shipping": format(quote.shipping, ".2f"),
                "estimated_delivery_days": eta_days,
                "available": True,
            }
        )

    return jsonify(
        {
            "destination": {"country": country, "state": state},
            "items_count": len(items) if isinstance(items, list) else 0,
            "options": options,
        }
    )


@catalog_api.get("/inventory/<sku>")
def get_inventory(sku: str):
    record = container().store.stock(sku.upper())
    return jsonify(serialize(record))


@catalog_api.post("/inventory/<sku>/adjust")
def adjust_inventory(sku: str):
    payload = json_body()
    value = container().inventory.adjust(
        sku.upper(),
        payload.get("delta"),
        role=request_role(),
        reason=str(payload.get("reason", "")),
    )
    return jsonify(value)


@catalog_api.post("/risk/evaluate")
def evaluate_risk():
    payload = json_body()
    services = container()
    customer_id = str(payload.get("customer_id", ""))
    customer = services.store.customer(customer_id)
    quote = services.pricing.quote(
        customer_id=customer_id,
        items=payload.get("items"),
        shipping_method=str(payload.get("shipping_method", "standard")),
        destination_country=str(payload.get("destination_country", customer.country)),
        destination_state=str(payload.get("destination_state", customer.state)),
    )
    result = services.risk.evaluate(
        customer=customer,
        lines=quote.lines,
        total=quote.total,
        shipping_method=quote.shipping_method,
        destination_country=quote.destination_country,
        destination_state=quote.destination_state,
        client_ip=client_ip(),
    )
    return jsonify(serialize(result))
