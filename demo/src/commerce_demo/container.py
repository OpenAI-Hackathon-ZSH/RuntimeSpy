"""Dependency container created once per Flask application instance."""

from __future__ import annotations

from dataclasses import dataclass

from .services import InventoryService, OrderService, PricingService, RiskService
from .store import CommerceStore


@dataclass(slots=True)
class CommerceContainer:
    store: CommerceStore
    pricing: PricingService
    inventory: InventoryService
    risk: RiskService
    orders: OrderService


def build_container(config: dict[str, object]) -> CommerceContainer:
    store = CommerceStore()
    store.seed()
    pricing = PricingService(store)
    inventory = InventoryService(
        store,
        allow_backorders=bool(config.get("ALLOW_BACKORDERS", True)),
    )
    risk = RiskService(
        store,
        review_threshold=int(config.get("RISK_REVIEW_THRESHOLD", 45)),
        block_threshold=int(config.get("RISK_BLOCK_THRESHOLD", 75)),
    )
    orders = OrderService(
        store,
        pricing,
        inventory,
        risk,
        refund_window_days=int(config.get("REFUND_WINDOW_DAYS", 30)),
    )
    return CommerceContainer(store, pricing, inventory, risk, orders)

