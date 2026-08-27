from datetime import datetime, timezone

from fastapi import APIRouter, Depends
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.core.deps import get_current_user
from app.core.security import create_access_token, decode_access_token, verify_bot_signature
from app.core.token_revocation import revoke_token, seconds_until
from app.models.models import User

router = APIRouter(prefix="/auth", tags=["auth"])
_bearer = HTTPBearer(auto_error=True)


class TelegramAuthIn(BaseModel):
    telegram_id: str
    timestamp: str
    signature: str
    full_name: str | None = None  # optional, only used the first time we see this user


class TelegramAuthOut(BaseModel):
    access_token: str
    token_type: str = "bearer"
    user_id: str


class LogoutOut(BaseModel):
    revoked: bool


@router.post("/telegram", response_model=TelegramAuthOut)
async def auth_telegram(payload: TelegramAuthIn, db: AsyncSession = Depends(get_db)):
    """
    Called by the bot process (never by end users directly) once per
    Telegram session. Verifies the request was signed with
    BOT_SERVICE_SECRET, then gets-or-creates the User row for this
    telegram_id (this is the "link telegram_id to User on first
    interaction" gap, now implemented) and issues a short-lived JWT.
    """
    verify_bot_signature(payload.telegram_id, payload.timestamp, payload.signature)

    result = await db.execute(select(User).where(User.telegram_id == payload.telegram_id))
    user = result.scalar_one_or_none()

    if user is None:
        user = User(telegram_id=payload.telegram_id, full_name=payload.full_name)
        db.add(user)
        await db.commit()
        await db.refresh(user)
    elif payload.full_name and user.full_name != payload.full_name:
        user.full_name = payload.full_name
        await db.commit()

    token = create_access_token(user.id, payload.telegram_id, user.role.value)
    return TelegramAuthOut(access_token=token, user_id=str(user.id))


@router.post("/logout", response_model=LogoutOut)
async def logout(
    credentials: HTTPAuthorizationCredentials = Depends(_bearer),
    _current_user: User = Depends(get_current_user),  # also validates the token is still usable
):
    """
    Revokes THIS specific token immediately (see core/token_revocation.py)
    -- a real gap noted explicitly in earlier reviews: previously a JWT
    was valid until natural expiry no matter what, with no way to
    invalidate a single compromised or no-longer-wanted session.
    """
    payload = decode_access_token(credentials.credentials)
    jti = payload.get("jti")
    exp = payload.get("exp")
    if jti and exp:
        await revoke_token(jti, seconds_until(exp))
    return LogoutOut(revoked=bool(jti))
