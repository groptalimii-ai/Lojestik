from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.core.deps import get_current_user
from app.models.models import Carrier, Truck, User
from app.schemas.schemas import CarrierOut, CarrierRegister, PageParams, TruckCreate, TruckOut
from app.services.date_normalizer import normalize_date_phrase
from app.services.phone_normalizer import normalize_saudi_phone
from app.services.rate_limit import require_user_rate_limit

router = APIRouter(prefix="/carriers", tags=["carriers"])


@router.post("", response_model=CarrierOut)
async def register_carrier(
    payload: CarrierRegister,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
    _usage: dict = Depends(require_user_rate_limit("carrier")),
):
    # user_id comes from the authenticated caller, never from the body --
    # otherwise anyone could register a carrier profile under someone
    # else's user_id.
    carrier = Carrier(**payload.model_dump(), user_id=current_user.id)
    db.add(carrier)
    await db.commit()
    await db.refresh(carrier)
    return carrier


@router.get("", response_model=list[CarrierOut])
async def list_carriers(
    page: PageParams = Depends(),
    db: AsyncSession = Depends(get_db),
    _current_user: User = Depends(get_current_user),
):
    stmt = (
        select(Carrier)
        .where(Carrier.is_deleted.is_(False))
        .order_by(Carrier.created_at.desc())
        .limit(page.limit)
        .offset(page.offset)
    )
    result = await db.execute(stmt)
    return result.scalars().all()


@router.get("/by-phone/{phone}", response_model=CarrierOut)
async def get_carrier_by_phone(
    phone: str,
    db: AsyncSession = Depends(get_db),
    _current_user: User = Depends(get_current_user),
):
    # BUG FIXED: this used to compare the raw path parameter directly
    # against Carrier.phone, which is stored NORMALIZED (canonical
    # "966XXXXXXXXX" form, see CarrierRegister's validator). Any phone
    # typed in its original form ("0501234567") never matched, so this
    # endpoint 404'd for every real carrier -- silently breaking the
    # bot's entire /mytrucks flow. Normalizing here fixes it.
    normalized = normalize_saudi_phone(phone)
    result = await db.execute(
        select(Carrier).where(Carrier.phone == normalized, Carrier.is_deleted.is_(False))
    )
    carrier = result.scalars().first()
    if not carrier:
        raise HTTPException(404, "لا يوجد ناقل مسجّل بهذا الرقم")
    return carrier


@router.post("/trucks", response_model=TruckOut)
async def add_truck(
    payload: TruckCreate,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
    _usage: dict = Depends(require_user_rate_limit("carrier")),
):
    # Ownership check: the calling user must own the carrier profile they
    # are adding a truck to -- otherwise any authenticated user could add
    # trucks to any carrier_id.
    carrier = await db.get(Carrier, payload.carrier_id)
    if not carrier or carrier.is_deleted:
        raise HTTPException(404, "Carrier not found")
    if carrier.user_id != current_user.id:
        raise HTTPException(403, "لا تملك صلاحية الإضافة لهذا الناقل")

    truck_data = payload.model_dump()
    available_from_text = truck_data.pop("available_from_text", None)
    truck = Truck(**truck_data, available_from=normalize_date_phrase(available_from_text))
    db.add(truck)
    await db.commit()
    await db.refresh(truck)
    return truck


@router.get("/{carrier_id}/trucks", response_model=list[TruckOut])
async def list_carrier_trucks(
    carrier_id: str,
    page: PageParams = Depends(),
    db: AsyncSession = Depends(get_db),
    _current_user: User = Depends(get_current_user),
):
    result = await db.execute(
        select(Truck)
        .where(Truck.carrier_id == carrier_id, Truck.is_deleted.is_(False))
        .order_by(Truck.created_at.desc())
        .limit(page.limit)
        .offset(page.offset)
    )
    return result.scalars().all()
