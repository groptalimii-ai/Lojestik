from fastapi import APIRouter, Depends
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.core.deps import require_admin
from app.models.models import Deal, DealStatus, Load, User
from app.services.financial import capital_progress, completed_deals_retained_profit

router = APIRouter(prefix="/analytics", tags=["analytics"])


@router.get("/dashboard")
async def dashboard(db: AsyncSession = Depends(get_db), _admin: User = Depends(require_admin)):
    # Revenue/margin figures are business-sensitive -- admin-only, not
    # previously gated at all.
    loads_result = await db.execute(select(Load).where(Load.is_deleted.is_(False)))
    loads = loads_result.scalars().all()

    deals_result = await db.execute(select(Deal).where(Deal.is_deleted.is_(False)))
    deals = deals_result.scalars().all()

    completed = [d for d in deals if d.status == DealStatus.COMPLETED]
    open_deals = [d for d in deals if d.status not in (DealStatus.COMPLETED, DealStatus.CANCELLED)]

    revenue = sum(d.customer_price or 0 for d in completed)
    gross_margin = sum(d.gross_margin for d in completed)
    net_profit = completed_deals_retained_profit(deals)

    return {
        "new_loads": len([l for l in loads if l.status == "NEW"]),
        "open_deals": len(open_deals),
        "completed_deals": len(completed),
        "revenue": revenue,
        "gross_margin": gross_margin,
        "net_profit_estimate": net_profit,
        "outstanding_receivables": sum(d.customer_price or 0 for d in deals if d.status == DealStatus.INVOICE_PENDING),
        "outstanding_payables": sum(d.carrier_price or 0 for d in deals if d.status == DealStatus.PAID and not d.carrier_paid),
        "capital_progress": capital_progress(net_profit),
    }
