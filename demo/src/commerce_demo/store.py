"""Thread-safe in-memory store with rollback-capable transactions."""

from __future__ import annotations

from contextlib import contextmanager
from copy import deepcopy
from decimal import Decimal
from threading import RLock
from typing import Iterator

from .errors import NotFoundError
from .models import Customer, CustomerTier, InventoryRecord, Order, Product


class CommerceStore:
    def __init__(self):
        self.products: dict[str, Product] = {}
        self.customers: dict[str, Customer] = {}
        self.inventory: dict[str, InventoryRecord] = {}
        self.orders: dict[str, Order] = {}
        self.idempotency_keys: dict[str, str] = {}
        self.audit_log: list[dict[str, object]] = []
        self.revision = 0
        self._lock = RLock()

    @contextmanager
    def transaction(self) -> Iterator["CommerceStore"]:
        with self._lock:
            snapshot = (
                deepcopy(self.inventory),
                deepcopy(self.orders),
                dict(self.idempotency_keys),
                list(self.audit_log),
                self.revision,
            )
            try:
                yield self
            except Exception:
                (
                    self.inventory,
                    self.orders,
                    self.idempotency_keys,
                    self.audit_log,
                    self.revision,
                ) = snapshot
                raise
            else:
                self.revision += 1

    def product(self, sku: str) -> Product:
        try:
            return self.products[sku]
        except KeyError:
            raise NotFoundError("product", sku) from None

    def customer(self, customer_id: str) -> Customer:
        try:
            return self.customers[customer_id]
        except KeyError:
            raise NotFoundError("customer", customer_id) from None

    def stock(self, sku: str) -> InventoryRecord:
        try:
            return self.inventory[sku]
        except KeyError:
            raise NotFoundError("inventory", sku) from None

    def order(self, order_id: str) -> Order:
        try:
            return self.orders[order_id]
        except KeyError:
            raise NotFoundError("order", order_id) from None

    def seed(self) -> None:
        products = [
            Product("LAPTOP-PRO", "Orbit Pro Laptop", "computers", Decimal("1499.00"), 1800),
            Product("HEADSET", "Nebula Headset", "audio", Decimal("129.00"), 340),
            Product("MOUSE", "Pulse Mouse", "accessories", Decimal("59.00"), 110),
            Product("BATTERY", "Travel Battery", "power", Decimal("89.00"), 420, hazardous=True),
            Product("COURSE-PY", "Python Video Course", "digital", Decimal("79.00"), 0, digital=True),
            Product("LEGACY-DOCK", "Legacy Dock", "accessories", Decimal("39.00"), 250, active=False),
        ]
        for product in products:
            self.products[product.sku] = product

        self.inventory.update(
            {
                "LAPTOP-PRO": InventoryRecord("LAPTOP-PRO", 8),
                "HEADSET": InventoryRecord("HEADSET", 30),
                "MOUSE": InventoryRecord("MOUSE", 3, backorderable=True),
                "BATTERY": InventoryRecord("BATTERY", 12),
                "COURSE-PY": InventoryRecord("COURSE-PY", 999_999),
                "LEGACY-DOCK": InventoryRecord("LEGACY-DOCK", 0),
            }
        )
        self.customers.update(
            {
                "cust-standard": Customer("cust-standard", "alex@example.com"),
                "cust-plus": Customer(
                    "cust-plus",
                    "maya@example.com",
                    tier=CustomerTier.PLUS,
                    state="NY",
                    order_count=12,
                ),
                "cust-vip": Customer(
                    "cust-vip",
                    "lee@example.com",
                    tier=CustomerTier.VIP,
                    account_age_days=900,
                    order_count=44,
                ),
                "cust-new": Customer(
                    "cust-new",
                    "new-user@temporary-mail.example",
                    account_age_days=1,
                    order_count=0,
                ),
                "cust-disabled": Customer(
                    "cust-disabled",
                    "disabled@example.com",
                    active=False,
                ),
            }
        )

