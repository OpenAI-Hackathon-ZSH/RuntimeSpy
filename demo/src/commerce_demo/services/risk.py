"""Explainable order-risk scoring with deliberately varied branches."""

from __future__ import annotations

from decimal import Decimal

from ..models import Customer, OrderLine, RiskResult, ShippingMethod
from ..store import CommerceStore


class RiskService:
    def __init__(self, store: CommerceStore, *, review_threshold: int = 45, block_threshold: int = 75):
        self.store = store
        self.review_threshold = review_threshold
        self.block_threshold = block_threshold

    def evaluate(
        self,
        *,
        customer: Customer,
        lines: list[OrderLine],
        total: Decimal,
        shipping_method: ShippingMethod,
        destination_country: str,
        destination_state: str,
        client_ip: str,
    ) -> RiskResult:
        score = 0
        reasons: list[str] = []

        if customer.account_age_days < 3:
            score += 25
            reasons.append("new_account")
        elif customer.account_age_days < 30:
            score += 10
            reasons.append("young_account")

        if customer.email.endswith(("temporary-mail.example", "mail-drop.example")):
            score += 30
            reasons.append("disposable_email")
        if customer.chargeback_count >= 2:
            score += 35
            reasons.append("chargeback_history")
        elif customer.chargeback_count == 1:
            score += 15
            reasons.append("prior_chargeback")

        if total >= Decimal("3000.00"):
            score += 35
            reasons.append("very_high_value")
        elif total >= Decimal("1000.00"):
            score += 18
            reasons.append("high_value")

        total_units = sum(line.quantity for line in lines)
        if total_units >= 20:
            score += 15
            reasons.append("bulk_quantity")
        if destination_country != customer.country:
            score += 18
            reasons.append("country_mismatch")
        elif destination_state != customer.state:
            score += 5
            reasons.append("state_mismatch")
        if shipping_method is ShippingMethod.SAME_DAY and total > Decimal("500.00"):
            score += 10
            reasons.append("urgent_high_value")
        if client_ip.startswith(("10.", "127.", "192.168.")):
            score = max(score - 5, 0)
            reasons.append("trusted_network")
        elif client_ip in {"203.0.113.66", "198.51.100.9"}:
            score += 40
            reasons.append("blocked_ip")

        if score >= self.block_threshold:
            decision = "block"
        elif score >= self.review_threshold:
            decision = "review"
        else:
            decision = "approve"
        return RiskResult(score=min(score, 100), decision=decision, reasons=reasons)

