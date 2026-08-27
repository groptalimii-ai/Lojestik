"""
JWT revocation via Redis.

Two complementary mechanisms, don't confuse them:

1. Per-token blacklist (jti) -- revoke_token()/is_token_revoked().
   For explicit logout of ONE session. The blacklist entry's TTL is set
   to exactly the token's remaining lifetime, so it never needs manual
   cleanup and never grows unbounded -- once the token would have
   expired naturally anyway, the blacklist entry vanishes with it.

2. Per-user invalidation cutoff (User.tokens_valid_after) -- checked in
   core/deps.py, set via revoke_all_user_tokens() below. For "invalidate
   EVERY existing token for this user right now" -- used automatically by
   scripts/promote_admin.py, so a role change takes effect immediately
   instead of waiting up to JWT_EXPIRE_MINUTES (or the bot's separate
   client-side token cache TTL) for the old token to expire on its own.
   Without this, promoting yourself to admin while your bot process still
   holds a cached pre-promotion token would silently keep failing
   require_admin checks until that cache expired.
"""
from datetime import datetime, timezone

from app.core.redis_client import get_redis


def _blacklist_key(jti: str) -> str:
    return f"jwt:revoked:{jti}"


async def revoke_token(jti: str, seconds_until_expiry: int) -> None:
    if not jti or seconds_until_expiry <= 0:
        return  # nothing to do -- already expired naturally
    r = get_redis()
    await r.set(_blacklist_key(jti), "1", ex=seconds_until_expiry)


async def is_token_revoked(jti: str | None) -> bool:
    if not jti:
        # A token minted before this feature existed has no jti. Treat
        # it as not-individually-revoked (the per-user cutoff below still
        # applies to it via `iat`) rather than rejecting every old token
        # outright the moment this code ships.
        return False
    r = get_redis()
    return bool(await r.get(_blacklist_key(jti)))


def seconds_until(expiry_timestamp: int) -> int:
    """expiry_timestamp is a JWT `exp` claim (Unix seconds, UTC)."""
    now = int(datetime.now(timezone.utc).timestamp())
    return max(expiry_timestamp - now, 0)
