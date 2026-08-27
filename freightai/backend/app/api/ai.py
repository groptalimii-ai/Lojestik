from fastapi import APIRouter, Depends, HTTPException

from app.core.deps import get_current_user
from app.models.models import User
from app.schemas.schemas import ExtractRequest, ExtractResponse
from app.services.extraction import extract_load_from_text
from app.services.rate_limit import refund_user_rate_limit, require_user_rate_limit

router = APIRouter(prefix="/ai", tags=["ai"])


@router.post("/extract-load", response_model=ExtractResponse)
async def extract_load(
    payload: ExtractRequest,
    current_user: User = Depends(get_current_user),
    _usage: dict = Depends(require_user_rate_limit("ai_extract")),
):
    try:
        data = await extract_load_from_text(payload.text)
    except Exception:
        # The Depends above already counted this request against today's
        # quota before we got here. If the AI call itself genuinely fails
        # (even after ai_retry's backoff attempts), the caller got zero
        # value for that -- refund it rather than silently eating into
        # their daily budget for an outage that wasn't their fault.
        await refund_user_rate_limit(str(current_user.id), "ai_extract")
        raise HTTPException(503, "تعذر الوصول لخدمة الاستخراج حاليًا. حاول مرة أخرى.")

    return ExtractResponse(**{k: v for k, v in data.items() if k in ExtractResponse.model_fields})
