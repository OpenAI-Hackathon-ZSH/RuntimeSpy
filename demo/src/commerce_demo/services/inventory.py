"""Inventory reservation, release, and administrative adjustment rules."""

from __future__ import annotations

from ..errors import ConflictError, PermissionDeniedError, ValidationError
from ..models import OrderLine
from ..store import CommerceStore


class InventoryService:
    def __init__(self, store: CommerceStore, *, allow_backorders: bool = True):
        self.store = store
        self.allow_backorders = allow_backorders

    def reserve(self, lines: list[OrderLine]) -> None:
        for line in lines:
            product = self.store.product(line.sku)
            if product.digital:
                continue
            record = self.store.stock(line.sku)
            if record.available >= line.quantity:
                record.available -= line.quantity
                record.reserved += line.quantity
            elif self.allow_backorders and record.backorderable:
                record.reserved += line.quantity
                record.available -= line.quantity
            else:
                raise ConflictError(
                    f"insufficient inventory for {line.sku}",
                    code="insufficient_inventory",
                )

    def release(self, lines: list[OrderLine]) -> None:
        for line in lines:
            product = self.store.product(line.sku)
            if product.digital:
                continue
            record = self.store.stock(line.sku)
            released = min(record.reserved, line.quantity)
            record.reserved -= released
            record.available += released

    def commit_shipment(self, lines: list[OrderLine]) -> None:
        for line in lines:
            product = self.store.product(line.sku)
            if product.digital:
                continue
            record = self.store.stock(line.sku)
            if record.reserved < line.quantity:
                raise ConflictError(
                    f"inventory reservation for {line.sku} is incomplete",
                    code="reservation_incomplete",
                )
            record.reserved -= line.quantity

    def adjust(self, sku: str, delta: object, *, role: str, reason: str) -> dict[str, object]:
        if role not in {"admin", "warehouse"}:
            raise PermissionDeniedError("inventory adjustment requires warehouse access")
        if isinstance(delta, bool) or not isinstance(delta, int) or delta == 0:
            raise ValidationError("delta must be a non-zero integer", field="delta")
        if abs(delta) > 500:
            raise ValidationError("a single adjustment cannot exceed 500", field="delta")
        if len(reason.strip()) < 4:
            raise ValidationError("an adjustment reason is required", field="reason")

        with self.store.transaction():
            record = self.store.stock(sku)
            if record.available + delta < 0:
                raise ConflictError("adjustment would make stock negative", code="negative_inventory")
            record.available += delta
            self.store.audit_log.append(
                {
                    "action": "inventory.adjust",
                    "sku": sku,
                    "delta": delta,
                    "reason": reason,
                    "role": role,
                }
            )
            return {
                "sku": sku,
                "available": record.available,
                "reserved": record.reserved,
                "revision": self.store.revision + 1,
            }

