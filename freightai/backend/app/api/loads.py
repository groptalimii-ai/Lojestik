from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.core.database import get_db
from app.core.deps import get_current_user
from app.models.models import Load, Truck, User
from app.schemas.schemas import LoadCreate, LoadOut, MatchOut, PageParams
from app.services.matching import rank_trucks_for_load
from app.services.rate_limit import require_user_rate_limit

router = APIRouter(prefix="/loads", tags=["loads"])


@router.post("", response_model=LoadOut)
async def create_load(
    payload: LoadCreate,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
    _usage: dict = Depends(require_user_rate_limit("loads")),
):
    # shipper_id comes from the authenticated caller, never from the body.
    load = Load(**payload.model_dump(), shipper_id=current_user.id)
    db.add(load)
    await db.commit()
    await db.refresh(load)
    return load


@router.get("", response_model=list[LoadOut])
async def list_loads(
    status: str | None = None,
    page: PageParams = Depends(),
    db: AsyncSession = Depends(get_db),
    _current_user: User = Depends(get_current_user),
):
    # Previously unbounded -- fine while the table is small, a full table
    # scan returned to the client the moment it isn't. Ordered by most
    # recent first since that's what a driver/dispatcher actually wants.
    stmt = (
        select(Load)
        .where(Load.is_deleted.is_(False))
        .order_by(Load.created_at.desc())
        .limit(page.limit)
        .offset(page.offset)
    )
    if status:
        stmt = stmt.where(Load.status == status)
    result = await db.execute(stmt)
    return result.scalars().all()


@router.get("/{load_id}", response_model=LoadOut)
async def get_load(
    load_id: UUID,
    db: AsyncSession = Depends(get_db),
    _current_user: User = Depends(get_current_user),
):
    load = await db.get(Load, load_id)
    if not load:
        raise HTTPException(404, "Load not found")
    return load


@router.post("/{load_id}/matches", response_model=list[MatchOut])
async def find_matches(
    load_id: UUID,
    db: AsyncSession = Depends(get_db),
    _current_user: User = Depends(get_current_user),
):
    load = await db.get(Load, load_id)
    if not load:
        raise HTTPException(404, "Load not found")
    # BUG FIXED: matching.score_match() reads truck.carrier.rating for
    # every truck. Without eager-loading it here, that's a lazy load
    # triggered from a SYNC function under an async session -- SQLAlchemy
    # raises MissingGreenlet immediately, so this endpoint 500'd on every
    # single call once any truck existed. selectinload fixes it with one
    # extra query instead of N lazy-load attempts (which wouldn't even
    # work at all in async mode, not just be slow).
    trucks_result = await db.execute(
        select(Truck).where(Truck.is_deleted.is_(False)).options(selectinload(Truck.carrier))
    )
    trucks = trucks_result.scalars().all()
    ranked = rank_trucks_for_load(load, trucks)
    return [
        MatchOut(truck_id=t.id, score=r.score, reasons=r.reasons, is_backhaul=r.is_backhaul)
        for t, r in ranked if r.score > 0
    ]
