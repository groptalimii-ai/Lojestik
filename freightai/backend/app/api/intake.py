from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.core.deps import require_admin
from app.models.leads import CarrierLead, CarrierProfile, LoadLead
from app.models.models import Company, User
from app.models.pricing_schema import Location, TruckType
from app.schemas.leads_schemas import CarrierActivityOut, IntakeMessageIn, IntakeResultOut, MatchedLeadOut
from app.services.db_utils import get_or_create
from app.services.geo import canonicalize_city_name, resolve_city_coords
from app.services.lead_extraction import (
    LOW_CONFIDENCE_THRESHOLD, classify_intake_text, extract_carrier_lead, extract_load_lead,
)
from app.services.phone_normalizer import format_for_display, normalize_saudi_phone
from app.services.rate_limit import refund_user_rate_limit, require_user_rate_limit

router = APIRouter(prefix="/intake", tags=["intake"])

MAX_MATCHES_RETURNED = 5
# AI-extracted text is stored directly into ORM objects here, unlike
# LoadCreate/TruckCreate which go through Pydantic Field(max_length=...).
# Without an explicit bound, a long/malicious/hallucinated value (whether
# from prompt injection in the source message or a plain AI mistake)
# would be stored unbounded -- Location.city_name and *.contact_name have
# no DB-level length limit either. This caps it defensively before any
# of that data reaches the database.
MAX_EXTRACTED_STR_LEN = 200


def _bounded(value: str | None, max_len: int = MAX_EXTRACTED_STR_LEN) -> str | None:
    if value is None:
        return None
    trimmed = value.strip()[:max_len].strip()
    return trimmed or None


async def _get_or_create_location(db: AsyncSession, city_name: str | None) -> Location | None:
    city_name = _bounded(city_name)
    if not city_name:
        return None
    # Canonicalize FIRST so spelling variants of a known city ("الطايف" /
    # "الطائف") resolve to the same Location row -- see geo.py's
    # canonicalize_city_name docstring for why this matters for matching.
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


async def _get_or_create_company(db: AsyncSession, name: str | None, phone: str | None) -> Company | None:
    """Matches by normalized phone when we have one (the real unique
    identifier) -- otherwise by exact name, and otherwise gives up and
    lets a new row be created rather than guessing. Only the phone path
    is protected against concurrent duplicate creation (Company has a
    nullable-unique constraint on contact_phone, not on name -- see
    models.py -- since many real companies legitimately share a display
    name)."""
    name = _bounded(name)
    if not name and not phone:
        return None

    select_stmt = (
        select(Company).where(Company.contact_phone == phone)
        if phone else select(Company).where(Company.name == name)
    )
    company, _created = await get_or_create(
        db, select_stmt, lambda: Company(name=name or "غير معروف", type="shipper", contact_phone=phone)
    )
    return company


async def _upsert_carrier_profile(db: AsyncSession, phone: str | None, contact_name: str | None) -> CarrierProfile | None:
    """
    See CarrierProfile's docstring: this tracks how many times a carrier
    has been logged, not whether they're reliable. Without a phone number
    there's no stable identity to aggregate against, so we skip it rather
    than guess by name (names collide too often: multiple drivers named
    "محمد").
    """
    if not phone:
        return None
    contact_name = _bounded(contact_name)
    now = datetime.now(timezone.utc)

    profile, created = await get_or_create(
        db,
        select(CarrierProfile).where(CarrierProfile.phone == phone),
        lambda: CarrierProfile(
            phone=phone, contact_name=contact_name, total_appearances=1,
            first_seen_at=now, last_seen_at=now,
        ),
    )
    if not created:
        # A concurrent request may have just created this profile via the
        # race path in get_or_create() -- either way, "not created" means
        # a row already existed before or during this call, so this is a
        # repeat sighting and gets counted as one.
        profile.total_appearances += 1
        profile.last_seen_at = now
        if contact_name:
            profile.contact_name = contact_name  # keep the most recently stated name

    return profile


async def _find_matching_carrier_leads(db: AsyncSession, origin_id, destination_id) -> list[MatchedLeadOut]:
    if not origin_id or not destination_id:
        return []
    result = await db.execute(
        select(CarrierLead)
        .where(CarrierLead.origin_location_id == origin_id, CarrierLead.destination_location_id == destination_id)
        .order_by(CarrierLead.created_at.desc())
        .limit(MAX_MATCHES_RETURNED)
    )
    return [
        MatchedLeadOut(contact_name=c.contact_name, phone=format_for_display(c.phone))
        for c in result.scalars().all()
    ]


async def _find_matching_load_leads(db: AsyncSession, origin_id, destination_id) -> list[MatchedLeadOut]:
    if not origin_id or not destination_id:
        return []
    result = await db.execute(
        select(LoadLead)
        .where(LoadLead.origin_location_id == origin_id, LoadLead.destination_location_id == destination_id)
        .order_by(LoadLead.created_at.desc())
        .limit(MAX_MATCHES_RETURNED)
    )
    return [
        MatchedLeadOut(contact_name=l.contact_name, phone=format_for_display(l.phone))
        for l in result.scalars().all()
    ]


@router.post("/message", response_model=IntakeResultOut)
async def ingest_intake_message(
    payload: IntakeMessageIn,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_admin),
    _usage: dict = Depends(require_user_rate_limit("intake")),
):
    """
    Manual data-collection pipeline for the operator's private channel:
    classify -> extract fields via Claude -> normalize phone (the real
    identity key) -> bound/canonicalize before storage -> resolve/create
    Location(s) (+ Company for load leads, + CarrierProfile activity
    tracking for carrier leads) -> persist -> search the OPPOSITE table
    for an exact route match. Admin-only -- see bot/handlers/intake.py.
    """
    lead_type = classify_intake_text(payload.text)

    if lead_type == "load":
        try:
            data = await extract_load_lead(payload.text)
        except Exception:
            # The Depends above already counted this against today's
            # quota. If extraction genuinely failed (even after
            # ai_retry's backoff), refund it -- an outage isn't the
            # operator's fault and shouldn't cost them a slot.
            await refund_user_rate_limit(str(current_user.id), "intake")
            raise HTTPException(503, "تعذر الوصول لخدمة الاستخراج حاليًا. حاول مرة أخرى.")

        phone = normalize_saudi_phone(_bounded(data.get("phone"), 50))
        contact_name = _bounded(data.get("contact_name"))
        company = await _get_or_create_company(db, contact_name, phone)
        origin = await _get_or_create_location(db, data.get("origin"))
        destination = await _get_or_create_location(db, data.get("destination"))

        lead = LoadLead(
            company_id=company.id if company else None,
            contact_name=contact_name,
            phone=phone,
            origin_location_id=origin.id if origin else None,
            destination_location_id=destination.id if destination else None,
            weight_tons=data.get("weight_tons"),
            price=data.get("price"),
            raw_text=payload.text,
            submitted_by_user_id=current_user.id,
            needs_review=data.get("confidence", 1.0) < LOW_CONFIDENCE_THRESHOLD,
        )
        db.add(lead)
        await db.commit()
        await db.refresh(lead)

        matches = await _find_matching_carrier_leads(
            db, lead.origin_location_id, lead.destination_location_id
        )

        return IntakeResultOut(
            id=str(lead.id),
            lead_type="load",
            contact_name=lead.contact_name,
            phone=format_for_display(lead.phone),
            origin_city=origin.city_name if origin else None,
            destination_city=destination.city_name if destination else None,
            weight_tons=lead.weight_tons,
            price=lead.price,
            matches=matches,
            needs_review=lead.needs_review,
        )

    # lead_type == "carrier"
    try:
        data = await extract_carrier_lead(payload.text)
    except Exception:
        await refund_user_rate_limit(str(current_user.id), "intake")
        raise HTTPException(503, "تعذر الوصول لخدمة الاستخراج حاليًا. حاول مرة أخرى.")

    phone = normalize_saudi_phone(_bounded(data.get("phone"), 50))
    contact_name = _bounded(data.get("contact_name"))
    origin = await _get_or_create_location(db, data.get("origin"))
    destination = await _get_or_create_location(db, data.get("destination"))
    try:
        truck_type = TruckType(data.get("truck_type") or "other")
    except ValueError:
        truck_type = TruckType.OTHER

    lead = CarrierLead(
        contact_name=contact_name,
        phone=phone,
        truck_type=truck_type,
        origin_location_id=origin.id if origin else None,
        destination_location_id=destination.id if destination else None,
        raw_text=payload.text,
        submitted_by_user_id=current_user.id,
        needs_review=data.get("confidence", 1.0) < LOW_CONFIDENCE_THRESHOLD,
    )
    db.add(lead)

    profile = await _upsert_carrier_profile(db, phone, contact_name)
    await db.commit()
    await db.refresh(lead)

    matches = await _find_matching_load_leads(db, lead.origin_location_id, lead.destination_location_id)

    activity = None
    if profile:
        activity = CarrierActivityOut(
            total_appearances=profile.total_appearances,
            first_seen_at=profile.first_seen_at.date().isoformat(),
        )

    return IntakeResultOut(
        id=str(lead.id),
        lead_type="carrier",
        contact_name=lead.contact_name,
        phone=format_for_display(lead.phone),
        origin_city=origin.city_name if origin else None,
        destination_city=destination.city_name if destination else None,
        truck_type=lead.truck_type.value,
        matches=matches,
        carrier_activity=activity,
        needs_review=lead.needs_review,
    )
