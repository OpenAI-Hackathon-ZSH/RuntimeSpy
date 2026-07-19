"""Pricing rules with customer, coupon, shipping, and tax branches."""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal, ROUND_HALF_UP
from typing import Any

from ..errors import ConflictError, ValidationError
from ..models import Customer, CustomerTier, OrderLine, ShippingMethod, json_value
from ..store import CommerceStore


CENT = Decimal("0.01")


def money(value: Decimal) -> Decimal:
    return value.quantize(CENT, rounding=ROUND_HALF_UP)


@dataclass(slots=True)
class Quote:
    lines: list[OrderLine]
    subtotal: Decimal
    discount: Decimal
    shipping: Decimal
    tax: Decimal
    total: Decimal
    shipping_method: ShippingMethod
    destination_country: str
    destination_state: str
    coupon: str | None

    def as_dict(self) -> dict[str, Any]:
        return json_value(
            {
                "lines": [
                    {
                        "sku": line.sku,
                        "quantity": line.quantity,
                        "unit_price": line.unit_price,
                        "discount": line.discount,
                        "total": line.total,
                    }
                    for line in self.lines
                ],
                "subtotal": self.subtotal,
                "discount": self.discount,
                "shipping": self.shipping,
                "tax": self.tax,
                "total": self.total,
                "shipping_method": self.shipping_method,
                "destination_country": self.destination_country,
                "destination_state": self.destination_state,
                "coupon": self.coupon,
            }
        )


class PricingService:
    def __init__(self, store: CommerceStore):
        self.store = store

    def quote(
        self,
        *,
        customer_id: str,
        items: Any,
        coupon: str | None = None,
        shipping_method: str = "standard",
        destination_country: str | None = None,
        destination_state: str | None = None,
    ) -> Quote:
        customer = self.store.customer(customer_id)
        if not customer.active:
            raise ConflictError("inactive customers cannot place orders", code="inactive_customer")
        if not isinstance(items, list) or not items:
            raise ValidationError("items must be a non-empty array", field="items")

        try:
            method = ShippingMethod(shipping_method)
        except ValueError:
            raise ValidationError("unknown shipping method", field="shipping_method") from None

        country = (destination_country or customer.country).upper()
        state = (destination_state or customer.state).upper()
        lines = self._price_lines(customer, items)
        subtotal = money(sum((line.unit_price * line.quantity for line in lines), Decimal("0")))
        automatic_discount = money(sum((line.discount for line in lines), Decimal("0")))
        shipping = self._shipping(lines, method, country, state)
        coupon_discount, free_shipping = self._coupon_discount(
            coupon,
            customer=customer,
            subtotal=subtotal,
            automatic_discount=automatic_discount,
        )
        if free_shipping:
            shipping = Decimal("0.00")
        discount = money(automatic_discount + coupon_discount)
        taxable = max(subtotal - discount, Decimal("0.00"))
        tax = self._tax(taxable, shipping, country, state)
        total = money(taxable + shipping + tax)
        return Quote(
            lines=lines,
            subtotal=subtotal,
            discount=discount,
            shipping=shipping,
            tax=tax,
            total=total,
            shipping_method=method,
            destination_country=country,
            destination_state=state,
            coupon=coupon.upper() if coupon else None,
        )

    def _price_lines(self, customer: Customer, items: list[Any]) -> list[OrderLine]:
        lines: list[OrderLine] = []
        seen: set[str] = set()
        for index, raw in enumerate(items):
            if not isinstance(raw, dict):
                raise ValidationError(f"item {index} must be an object", field="items")
            sku = str(raw.get("sku", "")).upper()
            quantity = raw.get("quantity", 1)
            if not sku:
                raise ValidationError(f"item {index} is missing sku", field="items")
            if sku in seen:
                raise ValidationError(f"duplicate sku {sku}", field="items")
            if isinstance(quantity, bool) or not isinstance(quantity, int) or quantity < 1:
                raise ValidationError("quantity must be a positive integer", field="quantity")
            if quantity > 25:
                raise ValidationError("quantity cannot exceed 25", field="quantity")

            product = self.store.product(sku)
            if not product.active:
                raise ConflictError(f"product {sku} is not available", code="inactive_product")
            line_discount = self._line_discount(customer, product.category, product.price, quantity)
            lines.append(OrderLine(sku, quantity, product.price, line_discount))
            seen.add(sku)
        return lines

    @staticmethod
    def _line_discount(
        customer: Customer,
        category: str,
        unit_price: Decimal,
        quantity: int,
    ) -> Decimal:
        match customer.tier:
            case CustomerTier.VIP:
                tier_rate = Decimal("0.08")
            case CustomerTier.PLUS:
                tier_rate = Decimal("0.04")
            case _:
                tier_rate = Decimal("0.00")

        quantity_rate = Decimal("0.00")
        if quantity >= 10:
            quantity_rate = Decimal("0.07")
        elif quantity >= 5:
            quantity_rate = Decimal("0.03")

        category_rate = Decimal("0.05") if category == "digital" else Decimal("0.00")
        rate = min(tier_rate + quantity_rate + category_rate, Decimal("0.20"))
        return money(unit_price * quantity * rate)

    def _shipping(
        self,
        lines: list[OrderLine],
        method: ShippingMethod,
        country: str,
        state: str,
    ) -> Decimal:
        products = [self.store.product(line.sku) for line in lines]
        if all(product.digital for product in products) or method is ShippingMethod.PICKUP:
            return Decimal("0.00")
        if country != "US" and any(product.hazardous for product in products):
            raise ConflictError(
                "hazardous products cannot be shipped internationally",
                code="shipping_restricted",
            )

        total_weight = sum(
            product.weight_grams * line.quantity
            for product, line in zip(products, lines, strict=True)
        )
        weight_surcharge = Decimal(total_weight // 1000) * Decimal("1.50")
        match method:
            case ShippingMethod.STANDARD:
                base = Decimal("7.99")
            case ShippingMethod.EXPRESS:
                base = Decimal("18.00")
                weight_surcharge *= 2
            case ShippingMethod.SAME_DAY:
                if country != "US" or state not in {"CA", "NY"}:
                    raise ConflictError("same-day delivery is unavailable", code="same_day_unavailable")
                base = Decimal("29.00")
                weight_surcharge *= 3
            case _:
                base = Decimal("0.00")
        return money(base + weight_surcharge)

    @staticmethod
    def _coupon_discount(
        coupon: str | None,
        *,
        customer: Customer,
        subtotal: Decimal,
        automatic_discount: Decimal,
    ) -> tuple[Decimal, bool]:
        if not coupon:
            return Decimal("0.00"), False

        normalized = coupon.upper()
        match normalized:
            case "SAVE10":
                discount = min(subtotal * Decimal("0.10"), Decimal("50.00"))
                return money(discount), False
            case "VIP20":
                if customer.tier is not CustomerTier.VIP:
                    raise ConflictError("VIP20 requires a VIP account", code="coupon_not_eligible")
                if automatic_discount >= subtotal * Decimal("0.10"):
                    return money(subtotal * Decimal("0.10")), False
                return money(subtotal * Decimal("0.20")), False
            case "FREESHIP":
                if subtotal < Decimal("50.00"):
                    raise ConflictError("FREESHIP requires a $50 subtotal", code="coupon_minimum")
                return Decimal("0.00"), True
            case "EXPIRED":
                raise ConflictError("coupon has expired", code="coupon_expired")
            case _:
                raise ValidationError("unknown coupon code", field="coupon")

    @staticmethod
    def _tax(
        taxable: Decimal,
        shipping: Decimal,
        country: str,
        state: str,
    ) -> Decimal:
        if country != "US":
            return Decimal("0.00")
        rates = {
            "CA": Decimal("0.0825"),
            "NY": Decimal("0.08875"),
            "TX": Decimal("0.0625"),
        }
        rate = rates.get(state, Decimal("0.0500"))
        shipping_taxable = state in {"NY", "TX"}
        base = taxable + shipping if shipping_taxable else taxable
        return money(base * rate)

