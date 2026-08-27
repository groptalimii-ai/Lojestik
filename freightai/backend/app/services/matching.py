"""
Deterministic matching engine. Produces a 0-100 score plus human-readable
reasons. This is intentionally rule-based (not AI) so pricing/matching stays
auditable and predictable, per project requirements.
"""
from dataclasses import dataclass, field
from datetime import datetime

from app.models.models import Load, Truck

WEIGHTS = {
    "origin": 25,
    "trailer": 15,
    "weight": 15,
    "availability": 15,
    "destination_or_backhaul": 15,
    "reliability": 10,
    "price": 5,
}


@dataclass
class MatchResult:
    score: float
    reasons: list[str] = field(default_factory=list)
    is_backhaul: bool = False


def _normalize(s: str | None) -> str:
    return (s or "").strip().lower()


def score_match(load: Load, truck: Truck) -> MatchResult:
    total = 0.0
    reasons: list[str] = []

    # Origin compatibility
    if _normalize(load.origin) == _normalize(truck.current_location):
        total += WEIGHTS["origin"]
        reasons.append("✓ الموقع مطابق تمامًا")
    elif truck.current_location and load.origin and _normalize(truck.current_location) in _normalize(load.origin):
        total += WEIGHTS["origin"] * 0.6
        reasons.append("~ الموقع قريب")

    # Trailer compatibility
    if load.trailer_type and truck.trailer_type and _normalize(load.trailer_type) == _normalize(truck.trailer_type):
        total += WEIGHTS["trailer"]
        reasons.append("✓ نوع المقطورة مناسب")
    elif not load.trailer_type:
        total += WEIGHTS["trailer"] * 0.5
        reasons.append("~ نوع المقطورة غير محدد بالحمولة")

    # Weight compatibility
    if load.weight_tons and truck.max_weight_tons:
        if truck.max_weight_tons >= load.weight_tons:
            total += WEIGHTS["weight"]
            reasons.append("✓ الوزن مناسب")
        else:
            reasons.append("✗ الشاحنة لا تتحمل الوزن المطلوب")

    # Availability / date
    if load.loading_date and truck.available_from:
        if truck.available_from.date() <= load.loading_date.date():
            total += WEIGHTS["availability"]
            reasons.append("✓ متاح في الموعد")
        else:
            reasons.append("✗ غير متاح بالتاريخ المطلوب")
    else:
        total += WEIGHTS["availability"] * 0.4

    # Destination match / backhaul opportunity
    is_backhaul = False
    if truck.routes and load.destination and _normalize(load.destination) in _normalize(truck.routes):
        total += WEIGHTS["destination_or_backhaul"]
        reasons.append("✓ الخط ضمن مسارات الناقل")
    if truck.has_return_load:
        is_backhaul = True
        reasons.append("↩ فرصة حمولة عودة")

    # Reliability
    reasons.append(f"تقييم الناقل: {getattr(truck.carrier, 'rating', 0) or 0}/5")
    total += WEIGHTS["reliability"] * min((getattr(truck.carrier, "rating", 0) or 0) / 5, 1)

    # Price sanity (only if both present)
    if truck.approximate_price and load.target_price:
        if truck.approximate_price <= load.target_price:
            total += WEIGHTS["price"]
            reasons.append("✓ السعر ضمن الميزانية المستهدفة")

    return MatchResult(score=round(min(total, 100), 1), reasons=reasons, is_backhaul=is_backhaul)


def rank_trucks_for_load(load: Load, trucks: list[Truck]) -> list[tuple[Truck, MatchResult]]:
    results = [(t, score_match(load, t)) for t in trucks]
    results.sort(key=lambda pair: pair[1].score, reverse=True)
    return results
