"""
Writes to `audit_logs`. Previously this table existed in the schema but
nothing in the codebase ever wrote to it -- meaning any question like
"who approved this deal" or "who promoted this account to admin" had no
answer beyond scrolling through application logs by hand.

Scope, deliberately narrow: this logs sensitive/privileged actions
(admin approvals, role changes), not every request -- that's what
logging_config.py's request logging is for. Audit log entries are for
"what did a privileged actor DO", not "what HTTP calls happened".

Failure to write an audit entry NEVER blocks the action it's logging --
see log_action()'s try/except. An audit trail that could break the
feature it's auditing would be worse than no audit trail.
"""
import logging
import uuid

from sqlalchemy.ext.asyncio import AsyncSession

from app.models.models import AuditLog

logger = logging.getLogger("freightai")


async def log_action(
    db: AsyncSession,
    actor_id: uuid.UUID | None,
    action: str,
    entity_type: str | None = None,
    entity_id: uuid.UUID | None = None,
    details: str | None = None,
) -> None:
    """
    Adds an AuditLog row to the CURRENT session without committing --
    callers should call this right before their own db.commit() so the
    audit entry lands in the same transaction as the action it describes
    (both succeed together, or both roll back together).
    """
    try:
        db.add(AuditLog(
            actor_id=actor_id, action=action, entity_type=entity_type,
            entity_id=entity_id, details=details,
        ))
    except Exception:
        # Never let a logging failure break the actual operation.
        logger.exception("Failed to queue audit log entry for action=%s", action)
