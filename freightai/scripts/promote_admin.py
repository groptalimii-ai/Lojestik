"""
Promotes a user to admin by telegram_id. Run once, directly against the
database, to bootstrap the operator's own account -- there is NO API
endpoint that can do this (a self-promotion endpoint would be a privilege
escalation hole: anyone could call it to become admin).

Usage (from the backend container or any environment with DATABASE_URL set):
    python scripts/promote_admin.py <telegram_id>

The user must have already messaged the bot at least once (so /auth/telegram
has created their row) before running this.
"""
import asyncio
import sys
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "backend"))

from sqlalchemy import select

from app.core.database import AsyncSessionLocal
from app.models.models import User, UserRole
from app.services.audit import log_action


async def promote(telegram_id: str) -> None:
    async with AsyncSessionLocal() as db:
        result = await db.execute(select(User).where(User.telegram_id == telegram_id))
        user = result.scalar_one_or_none()
        if user is None:
            print(f"No user found with telegram_id={telegram_id}. "
                  "Make sure they've messaged the bot at least once first.")
            return

        if user.role == UserRole.ADMIN:
            print(f"{telegram_id} is already admin.")
            return

        user.role = UserRole.ADMIN
        # Forces every existing token for this user to be rejected on its
        # next use (see core/token_revocation.py's tokens_valid_after
        # mechanism) -- without this, a token issued before the promotion
        # (e.g. already cached client-side by a running bot process, see
        # bot/api_client.py's 1-hour cache) would keep claiming the OLD
        # role until it expired naturally, up to JWT_EXPIRE_MINUTES later.
        user.tokens_valid_after = datetime.now(timezone.utc)
        # actor_id=None -- this is run directly against the DB by whoever
        # has infrastructure access, not through the API by another user,
        # so there's no "acting user" to attribute it to. The audit entry
        # itself (this action happened, on this account, at this time) is
        # still the useful part.
        await log_action(
            db, actor_id=None, action="user_promoted_to_admin",
            entity_type="user", entity_id=user.id, details=f"telegram_id={telegram_id}",
        )
        await db.commit()
        print(f"telegram_id={telegram_id} (user_id={user.id}) is now admin.")
        print("Their next bot command will trigger a fresh login automatically.")


if __name__ == "__main__":
    if len(sys.argv) != 2:
        print("Usage: python scripts/promote_admin.py <telegram_id>")
        sys.exit(1)
    asyncio.run(promote(sys.argv[1]))
