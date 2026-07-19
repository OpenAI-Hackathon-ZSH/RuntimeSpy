"""Domain models for the branch-rich commerce demo."""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from decimal import Decimal
from enum import StrEnum
from typing import Any


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


class CustomerTier(StrEnum):
    STANDARD = "standard"
    PLUS = "plus"
    VIP = "vip"


class OrderStatus(StrEnum):
    PENDING_REVIEW = "pending_review"
    CONFIRMED = "confirmed"
    PACKED = "packed"
    SHIPPED = "shipped"
    DELIVERED = "delivered"
    CANCELLED = "cancelled"
    REFUNDED = "refunded"


class ShippingMethod(StrEnum):
    STANDARD = "standard"
    EXPRESS = "express"
    SAME_DAY = "same_day"
    PICKUP = "pickup"


@dataclass(slots=True)
class Product:
    sku: str
    name: str
    category: str
    price: Decimal
    weight_grams: int
    active: bool = True
    digital: bool = False
    hazardous: bool = False


@dataclass(slots=True)
class Customer:
    id: str
    email: str
    tier: CustomerTier = CustomerTier.STANDARD
    country: str = "US"
    state: str = "CA"
    active: bool = True
    account_age_days: int = 365
    order_count: int = 0
    chargeback_count: int = 0


@dataclass(slots=True)
class InventoryRecord:
    sku: str
    available: int
    reserved: int = 0
    backorderable: bool = False


@dataclass(slots=True)
class OrderLine:
    sku: str
    quantity: int
    unit_price: Decimal
    discount: Decimal = Decimal("0.00")

    @property
    def total(self) -> Decimal:
        return (self.unit_price * self.quantity) - self.discount


@dataclass(slots=True)
class RiskResult:
    score: int
    decision: str
    reasons: list[str]


@dataclass(slots=True)
class Order:
    id: str
    customer_id: str
    lines: list[OrderLine]
    status: OrderStatus
    subtotal: Decimal
    discount: Decimal
    shipping: Decimal
    tax: Decimal
    total: Decimal
    shipping_method: ShippingMethod
    destination_country: str
    destination_state: str
    risk: RiskResult
    coupon: str | None = None
    idempotency_key: str | None = None
    created_at: datetime = field(default_factory=utc_now)
    updated_at: datetime = field(default_factory=utc_now)
    refunded_amount: Decimal = Decimal("0.00")
    tracking_number: str | None = None


def json_value(value: Any) -> Any:
    if isinstance(value, Decimal):
        return format(value, ".2f")
    if isinstance(value, datetime):
        return value.isoformat()
    if isinstance(value, StrEnum):
        return value.value
    if isinstance(value, list):
        return [json_value(item) for item in value]
    if isinstance(value, dict):
        return {key: json_value(item) for key, item in value.items()}
    return value


def serialize(value: Any) -> dict[str, Any]:
    return json_value(asdict(value))

