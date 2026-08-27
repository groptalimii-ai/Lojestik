"""
Statistical price suggestion -- deliberately NOT a trained ML model.

At this data volume (early pilot), a trained model would overfit noise
and produce false confidence dressed up as precision. A median over
comparable historical prices, with the sample size shown honestly, is
both more honest and more immediately useful. This is meant to be
upgraded to the trained model `trip_records` was designed for (see
pricing_schema.py's docstring) once there's enough completed-deal volume
to justify it -- the same underlying signal (route + price) feeds both;
only the estimator changes when that day comes.

Two data sources, checked in order of reliability:
1. TripRecord.final_accepted_price -- actually-closed deals. Best signal,
   currently empty until a deal-completion flow exists (Phase 2/3 item).
2. LoadLead.price -- asking prices shippers stated during manual intake
   (see /intake). Noisier (an ask, not a confirmed deal) but it's the
   data that actually exists today, and a median over even a handful of
   comparable asks is a genuinely useful anchor for a driver asking
   "is 3000 SAR fair for Riyadh -> Jeddah?"
"""
import uuid
from dataclasses import dataclass
from statistics import median

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.leads import LoadLead
from app.models.pricing_schema import TripRecord

MIN_SAMPLES_FOR_MEDIUM_CONFIDENCE = 3


@dataclass
class PriceSuggestion:
    suggested_price: float | None
    sample_size: int
    source: str  # "closed_deals" | "manual_asks" | "none"
    confidence: str  # "low" | "medium" | "none"


async def suggest_price(
    db: AsyncSession, origin_location_id: uuid.UUID, destination_location_id: uuid.UUID
) -> PriceSuggestion:
    result = await db.execute(
        select(TripRecord.final_accepted_price).where(
            TripRecord.origin_location_id == origin_location_id,
            TripRecord.destination_location_id == destination_location_id,
            TripRecord.used_for_training.is_(True),
        )
    )
    prices = [p for (p,) in result.all() if p is not None]
    if prices:
        return PriceSuggestion(
            suggested_price=round(median(prices)),
            sample_size=len(prices),
            source="closed_deals",
            confidence="medium" if len(prices) >= MIN_SAMPLES_FOR_MEDIUM_CONFIDENCE else "low",
        )

    result = await db.execute(
        select(LoadLead.price).where(
            LoadLead.origin_location_id == origin_location_id,
            LoadLead.destination_location_id == destination_location_id,
            LoadLead.price.is_not(None),
        )
    )
    prices = [p for (p,) in result.all() if p is not None]
    if prices:
        return PriceSuggestion(
            suggested_price=round(median(prices)),
            sample_size=len(prices),
            source="manual_asks",
            confidence="low",
        )

    return PriceSuggestion(suggested_price=None, sample_size=0, source="none", confidence="none")
