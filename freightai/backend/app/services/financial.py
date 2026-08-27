"""
Financial engine. Enforces the rule: Revenue != Profit.
Also computes capital progress toward the 80,000 SAR target.
"""
from dataclasses import dataclass

from app.core.config import settings
from app.models.models import Deal


@dataclass
class DealFinancials:
    customer_price: float
    carrier_price: float
    operating_cost: float

    @property
    def gross_margin(self) -> float:
        return self.customer_price - self.carrier_price

    @property
    def margin_pct(self) -> float:
        if not self.customer_price:
            return 0.0
        return round((self.gross_margin / self.customer_price) * 100, 2)

    @property
    def net_profit(self) -> float:
        return self.gross_margin - self.operating_cost


def compute_deal_financials(customer_price: float | None, carrier_price: float | None,
                             operating_cost: float = 0.0) -> DealFinancials | None:
    if customer_price is None or carrier_price is None:
        return None
    return DealFinancials(customer_price, carrier_price, operating_cost)


def capital_progress(retained_profit: float, avg_profit_scenarios: list[float] | None = None) -> dict:
    target = settings.capital_target_sar
    avg_profit_scenarios = avg_profit_scenarios or [1000, 1500, 2000, 2500, 3000]
    remaining = max(target - retained_profit, 0)
    return {
        "starting_capital": 0,
        "current_retained_profit": retained_profit,
        "target": target,
        "progress_pct": round(min(retained_profit / target, 1) * 100, 1) if target else 0,
        "remaining_amount": remaining,
        "deals_needed_by_avg_profit": {
            f"{avg}": (int(remaining // avg) + (1 if remaining % avg else 0)) if avg else None
            for avg in avg_profit_scenarios
        },
    }


def completed_deals_retained_profit(deals: list[Deal]) -> float:
    """
    Only count profit from deals that are fully COMPLETED and paid both
    ways. As of this comment, this will ALWAYS return 0 -- no endpoint
    anywhere sets Deal.customer_paid/carrier_paid to True yet (payment
    tracking is frozen until commercial launch, see
    models.py::Deal.customer_paid's comment). This is correct, honest
    behavior for data that was never actually collected -- do not
    "fix" it by relaxing the condition or faking the flags.
    """
    total = 0.0
    for d in deals:
        if d.status.value == "COMPLETED" and d.customer_paid and d.carrier_paid:
            total += d.net_profit_estimate
    return total
