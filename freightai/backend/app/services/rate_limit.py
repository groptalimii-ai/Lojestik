"""
Daily per-account rate limiting.

CHANGED: previously keyed off the client-supplied `X-User-Id` header, which
any caller could set to any value (see README "Known Gaps" -- this was the
actual bypass). Now it depends on `get_current_user`, so the identity used
as the Redis key is the `sub` claim of a JWT the caller cannot forge
without BOT_SERVICE_SECRET. The Redis mechanics (INCR + midnight-UTC TTL)
are unchanged.
"""
from datetime import datetime, timedelta, timezone

from fastapi import Depends, HTTPException

from app.core.config import settings
from app.core.deps import get_current_user
from app.core.redis_client import get_redis
from app.models.models import User

SCOPE_LIMITS = {
    "ai_extract": settings.rate_limit_ai_extract_per_day,
    "loads": settings.rate_limit_loads_per_day,
    "carrier": settings.rate_limit_carrier_actions_per_day,
    "deals": settings.rate_limit_default_per_day,
    "pricing": settings.rate_limit_pricing_per_day,
    "intake": settings.rate_limit_intake_per_day,
    "default": settings.rate_limit_default_per_day,
}


def _seconds_until_midnight_utc() -> int:
    now = datetime.now(timezone.utc)
    midnight = (now + timedelta(days=1)).replace(hour=0, minute=0, second=0, microsecond=0)
    return max(int((midnight - now).total_seconds()), 1)


async def check_and_increment(user_id: str, scope: str = "default") -> dict:
    limit = SCOPE_LIMITS.get(scope, settings.rate_limit_default_per_day)
    today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    key = f"ratelimit:{scope}:{user_id}:{today}"

    r = get_redis()
    current = await r.incr(key)
    if current == 1:
        await r.expire(key, _seconds_until_midnight_utc())

    if current > limit:
        raise HTTPException(
            status_code=429,
            detail=f"تم تجاوز الحد اليومي المسموح ({limit} طلب/يوم) لهذه الخدمة. حاول مرة أخرى غدًا.",
        )

    return {"scope": scope, "used": current, "limit": limit, "remaining": max(limit - current, 0)}


def require_user_rate_limit(scope: str):
    """
    FastAPI dependency factory. Usage:
        Depends(require_user_rate_limit("ai_extract"))
    Identity comes from the authenticated User (via get_current_user),
    never from a client-controlled header.
    """
    async def dependency(user: User = Depends(get_current_user)) -> dict:
        return await check_and_increment(str(user.id), scope)

    return dependency


async def refund_user_rate_limit(user_id: str, scope: str) -> None:
    """
    Decrements today's usage counter by 1. Used when a request was
    already counted against the daily quota (the Depends ran and
    incremented it) but genuinely failed to deliver any value -- e.g. the
    AI call itself errored out even after retries. Without this, a
    transient Anthropic outage would silently eat into your daily budget
    for zero benefit. Best-effort: if the key already rolled over to a
    new day or anything goes wrong, this does nothing rather than risk
    corrupting the counter.
    """
    today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    key = f"ratelimit:{scope}:{user_id}:{today}"
    try:
        r = get_redis()
        current = await r.get(key)
        if current is not None and int(current) > 0:
            await r.decr(key)
    except Exception:
        pass
