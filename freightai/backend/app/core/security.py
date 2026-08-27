"""
Identity primitives.

Two separate trust mechanisms, don't confuse them:

1. Bot-service HMAC  (verify_bot_signature)
   Proves a request to POST /auth/telegram genuinely came from OUR bot
   process, which is the only thing that can vouch for a Telegram user id
   (Telegram itself only guarantees `from_user.id` to the bot that received
   the update). Only the backend and the bot process know BOT_SERVICE_SECRET.
   A public client without this secret cannot mint a token for ANY
   telegram_id, which is what closes the old "X-User-Id is just a header,
   type whatever you want" hole.

2. User JWT  (create_access_token / decode_access_token)
   Issued by the backend AFTER step 1 succeeds. Short-lived, signed with
   JWT_SECRET, carries the real internal user id. Every endpoint that needs
   to know "who is calling" depends on this, never on a client-supplied id.
"""
import hashlib
import hmac
import time
import uuid
from datetime import datetime, timedelta, timezone

import jwt
from fastapi import HTTPException

from app.core.config import settings

BOT_SIGNATURE_MAX_AGE_SECONDS = 60  # replay window


def verify_bot_signature(telegram_id: str, timestamp: str, signature: str) -> None:
    """
    Raises HTTPException(401) unless `signature` is a valid HMAC-SHA256 of
    "{telegram_id}:{timestamp}" under BOT_SERVICE_SECRET, and `timestamp`
    is recent (blocks replay of a captured request).
    """
    try:
        ts = int(timestamp)
    except ValueError:
        raise HTTPException(status_code=401, detail="Invalid timestamp")

    if abs(time.time() - ts) > BOT_SIGNATURE_MAX_AGE_SECONDS:
        raise HTTPException(status_code=401, detail="Signature expired")

    message = f"{telegram_id}:{timestamp}".encode()
    expected = hmac.new(settings.bot_service_secret.encode(), message, hashlib.sha256).hexdigest()

    if not hmac.compare_digest(expected, signature):
        raise HTTPException(status_code=401, detail="Invalid signature")


def create_access_token(user_id: uuid.UUID, telegram_id: str, role: str) -> str:
    now = datetime.now(timezone.utc)
    payload = {
        "sub": str(user_id),
        "telegram_id": telegram_id,
        "role": role,
        "jti": uuid.uuid4().hex,  # unique per-token id, needed for single-session revocation
        "iat": now,
        "exp": now + timedelta(minutes=settings.jwt_expire_minutes),
    }
    return jwt.encode(payload, settings.jwt_secret, algorithm=settings.jwt_algorithm)


def decode_access_token(token: str) -> dict:
    try:
        return jwt.decode(token, settings.jwt_secret, algorithms=[settings.jwt_algorithm])
    except jwt.ExpiredSignatureError:
        raise HTTPException(status_code=401, detail="انتهت صلاحية الجلسة، أعد المصادقة")
    except jwt.InvalidTokenError:
        raise HTTPException(status_code=401, detail="رمز مصادقة غير صالح")
