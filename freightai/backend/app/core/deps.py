import uuid
from datetime import datetime, timezone

from fastapi import Depends, HTTPException
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.core.security import decode_access_token
from app.core.token_revocation import is_token_revoked
from app.models.models import User

_bearer = HTTPBearer(auto_error=True)


async def get_current_user(
    credentials: HTTPAuthorizationCredentials = Depends(_bearer),
    db: AsyncSession = Depends(get_db),
) -> User:
    """
    The single source of truth for "who is calling this endpoint".
    Every mutating endpoint should depend on this instead of trusting a
    client-supplied id in a header or in the request body.
    """
    payload = decode_access_token(credentials.credentials)
    try:
        user_id = uuid.UUID(payload["sub"])
    except (KeyError, ValueError):
        raise HTTPException(status_code=401, detail="رمز مصادقة غير صالح")

    # Revocation check 1: this specific token was explicitly logged out.
    if await is_token_revoked(payload.get("jti")):
        raise HTTPException(status_code=401, detail="تم تسجيل الخروج من هذه الجلسة، أعد المصادقة")

    user = await db.get(User, user_id)
    if user is None or user.is_deleted:
        raise HTTPException(status_code=401, detail="المستخدم غير موجود")

    # Revocation check 2: ALL of this user's tokens were invalidated
    # (e.g. a role change via scripts/promote_admin.py) after this
    # specific token was issued.
    if user.tokens_valid_after is not None:
        issued_at = payload.get("iat")
        issued_at_dt = (
            datetime.fromtimestamp(issued_at, tz=timezone.utc) if issued_at is not None else None
        )
        valid_after = user.tokens_valid_after
        if valid_after.tzinfo is None:
            valid_after = valid_after.replace(tzinfo=timezone.utc)
        if issued_at_dt is None or issued_at_dt < valid_after:
            raise HTTPException(status_code=401, detail="انتهت صلاحية الجلسة (تغيّرت الصلاحيات)، أعد المصادقة")

    return user


async def require_admin(user: User = Depends(get_current_user)) -> User:
    if user.role.value != "admin":
        raise HTTPException(status_code=403, detail="هذا الإجراء يتطلب صلاحية Admin")
    return user
