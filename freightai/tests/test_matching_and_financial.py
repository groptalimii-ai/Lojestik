"""
Run with: pytest tests/ (from /backend, with PYTHONPATH set to backend/)
"""
import sys
from datetime import datetime, timezone
from pathlib import Path
from types import SimpleNamespace

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "backend"))

from app.services.financial import capital_progress, compute_deal_financials
from app.services.matching import score_match


def _truck(**kwargs):
    defaults = dict(
        current_location="Dammam", trailer_type="curtain", max_weight_tons=30,
        available_from=datetime(2026, 8, 20, tzinfo=timezone.utc), routes="Amman,Riyadh",
        has_return_load=False, approximate_price=9000,
        carrier=SimpleNamespace(rating=4.5),
    )
    defaults.update(kwargs)
    return SimpleNamespace(**defaults)


def _load(**kwargs):
    defaults = dict(
        origin="Dammam", destination="Amman", cargo_type="plastic", weight_tons=22,
        trailer_type="curtain", loading_date=datetime(2026, 8, 20, tzinfo=timezone.utc),
        target_price=10000,
    )
    defaults.update(kwargs)
    return SimpleNamespace(**defaults)


def test_perfect_match_scores_high():
    result = score_match(_load(), _truck())
    assert result.score >= 80


def test_weight_incompatible_lowers_score():
    result = score_match(_load(weight_tons=40), _truck(max_weight_tons=20))
    assert any("لا يتحمل" in r for r in result.reasons)


def test_backhaul_flagged():
    result = score_match(_load(), _truck(has_return_load=True))
    assert result.is_backhaul is True


def test_deal_financials_margin():
    fin = compute_deal_financials(customer_price=12000, carrier_price=9000, operating_cost=500)
    assert fin.gross_margin == 3000
    assert fin.margin_pct == 25.0
    assert fin.net_profit == 2500


def test_deal_financials_missing_prices_returns_none():
    assert compute_deal_financials(None, 9000) is None


def test_capital_progress_deals_needed():
    progress = capital_progress(retained_profit=17500)
    assert progress["target"] == 80000
    assert progress["deals_needed_by_avg_profit"]["2000"] == 32  # (80000-17500)/2000 = 31.25 -> 32
