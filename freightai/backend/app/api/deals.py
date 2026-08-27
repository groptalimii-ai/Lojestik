from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.core.deps import get_current_user
from app.models.models import Carrier, Deal, DealStatus, Load, Truck, User
from app.schemas.schemas import DealCreate, DealOut, DealStatusUpdate, PageParams
from app.services.audit import log_action
from app.services.deal_lifecycle import InvalidTransitionError, validate_transition
from app.services.rate_limit import require_user_rate_limit

router = APIRouter(prefix="/deals", tags=["deals"])

# NOTE: this router previously had NO auth and NO rate limiting on any
# route -- create_deal and update_deal_status were reachable by anyone,
# and update_deal_status trusted a client-supplied `is_admin: bool` in the
# request body to decide whether to allow admin-only transitions. Both are
# fixed below: every mutating route now requires an authenticated user,
# and admin authority is read from `current_user.role`, which the caller
# cannot set.


@router.post("", response_model=DealOut)
async def create_deal(
    payload: DealCreate,
    db: AsyncSession = Depends(get_db),
    _current_user: User = Depends(get_current_user),
    _usage: dict = Depends(require_user_rate_limit("deals")),
):
    # BUG FIXED: previously created a Deal from any load_id/truck_id/
    # carrier_id without checking they exist -- either a raw
    # IntegrityError leaked out (now caught by the global handler as a
    # generic 500, still bad UX) or, in a misconfigured DB without FK
    # enforcement, silently created a dangling reference. Explicit checks
    # give a clear 404 instead.
    if await db.get(Load, payload.load_id) is None:
        raise HTTPException(404, "Load not found")
    if payload.truck_id is not None and await db.get(Truck, payload.truck_id) is None:
        raise HTTPException(404, "Truck not found")
    if payload.carrier_id is not None and await db.get(Carrier, payload.carrier_id) is None:
        raise HTTPException(404, "Carrier not found")

    deal = Deal(**payload.model_dump())
    db.add(deal)
    await db.commit()
    await db.refresh(deal)
    return deal


@router.get("")
async def list_deals(
    page: PageParams = Depends(),
    db: AsyncSession = Depends(get_db),
    _current_user: User = Depends(get_current_user),
):
    stmt = (
        select(Deal)
        .where(Deal.is_deleted.is_(False))
        .order_by(Deal.created_at.desc())
        .limit(page.limit)
        .offset(page.offset)
    )
    result = await db.execute(stmt)
    deals = result.scalars().all()
    return [
        {
            "id": d.id, "status": d.status, "customer_price": d.customer_price,
            "carrier_price": d.carrier_price, "gross_margin": d.gross_margin,
            "margin_pct": d.margin_pct, "net_profit_estimate": d.net_profit_estimate,
        }
        for d in deals
    ]


@router.patch("/{deal_id}/status")
async def update_deal_status(
    deal_id: UUID,
    payload: DealStatusUpdate,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    deal = await db.get(Deal, deal_id)
    if not deal:
        raise HTTPException(404, "Deal not found")
    try:
        target = DealStatus(payload.target_status)
        # is_admin now comes from the authenticated user's role, not the
        # request body.
        validate_transition(deal.status, target, is_admin=(current_user.role.value == "admin"))
    except (ValueError, InvalidTransitionError) as e:
        raise HTTPException(400, str(e))

    deal.status = target
    # BUG FIXED: this used to unconditionally set
    # `approved_by_admin_id = current_user.id if admin else None` on
    # EVERY transition -- meaning any later transition made by a
    # non-admin (e.g. DISPUTED -> NEGOTIATING, which doesn't require
    # admin approval) would silently WIPE OUT a prior admin's approval
    # recorded on an earlier transition, destroying the audit trail. Now
    # it only ever sets the field when an admin is the one acting, and
    # never clears a value that's already there.
    if current_user.role.value == "admin":
        deal.approved_by_admin_id = current_user.id
        await log_action(
            db, current_user.id, "deal_status_admin_approved",
            entity_type="deal", entity_id=deal.id,
            details=f"{payload.target_status}",
        )

    await db.commit()
    return {"id": deal.id, "status": deal.status}
