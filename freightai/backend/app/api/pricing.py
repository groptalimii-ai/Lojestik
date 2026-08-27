from fastapi import APIRouter, Depends
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.core.deps import get_current_user
from app.models.models import User
from app.models.pricing_schema import Location, Shipment, ShipmentStatus
from app.schemas.pricing_schemas import PricingRequestIn, PricingRequestOut
from app.services.db_utils import get_or_create
from app.services.geo import canonicalize_city_name, resolve_city_coords, resolve_distance_km
from app.services.pricing_engine import suggest_price
from app.services.rate_limit import require_user_rate_limit

router = APIRouter(prefix="/pricing", tags=["pricing"])


async def _get_or_create_location(db: AsyncSession, city_name: str) -> Location:
    # Canonicalize FIRST so spelling variants of a known city resolve to
    # the same Location row -- see geo.py's canonicalize_city_name.
    normalized = canonicalize_city_name(city_name)
    coords = await resolve_city_coords(normalized)
    location, _created = await get_or_create(
        db,
        select(Location).where(Location.city_name == normalized),
        lambda: Location(
            city_name=normalized,
            latitude=coords[0] if coords else None,
            longitude=coords[1] if coords else None,
        ),
    )
    return location


def _coords_of(location: Location) -> tuple[float, float] | None:
    if location.latitude is not None and location.longitude is not None:
        return (location.latitude, location.longitude)
    return None


@router.post("/request", response_model=PricingRequestOut)
async def create_pricing_request(
    payload: PricingRequestIn,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
    rate_limit_info: dict = Depends(require_user_rate_limit("pricing")),
):
    """
    Pipeline: JWT auth (get_current_user) -> rate limiter, keyed on the
    real user id (require_user_rate_limit) -> resolve/create locations
    (auto-geocoded for free from a static city table, see services/geo.py)
    -> persist the Shipment -> look up a statistical price suggestion
    from real historical data (services/pricing_engine.py).
    """
    origin = await _get_or_create_location(db, payload.origin_city)
    destination = await _get_or_create_location(db, payload.destination_city)

    shipment = Shipment(
        driver_user_id=current_user.id,
        origin_location_id=origin.id,
        destination_location_id=destination.id,
        truck_type=payload.truck_type,
        weight_tons=payload.weight_tons,
        requested_price=payload.requested_price,
        raw_text=payload.raw_text,
        status=ShipmentStatus.PENDING_PRICE,
    )
    db.add(shipment)
    await db.commit()
    await db.refresh(shipment)

    price_suggestion = await suggest_price(db, origin.id, destination.id)
    distance_km = await resolve_distance_km(
        origin.city_name, _coords_of(origin), destination.city_name, _coords_of(destination)
    )

    return PricingRequestOut(
        shipment_id=str(shipment.id),
        origin_city=origin.city_name,
        destination_city=destination.city_name,
        truck_type=shipment.truck_type,
        weight_tons=shipment.weight_tons,
        status=shipment.status.value,
        rate_limit_remaining=rate_limit_info["remaining"],
        distance_km=distance_km,
        suggested_price=price_suggestion.suggested_price,
        suggested_price_sample_size=price_suggestion.sample_size,
        suggested_price_source=price_suggestion.source,
        suggested_price_confidence=price_suggestion.confidence,
    )
