"""
Race-safe get-or-create for concurrent requests.

A plain "SELECT, if None then INSERT" pattern (used throughout this
project's intake/pricing flows for Location, Company, CarrierProfile) has
a real race window: two concurrent requests can both pass the SELECT
(finding nothing) before either commits, then both try to INSERT the
same logically-unique row. Without a DB-level unique constraint, this
silently creates duplicates -- which is exactly what would quietly break
the route-matching feature (two "Riyadh" rows means matches on "Riyadh"
routes stop finding each other). Several tables now have a unique
constraint to make the SECOND insert fail loudly instead of duplicating
-- but failing loudly (an unhandled IntegrityError -> generic 500) isn't
the right behavior either, when the actually-correct response is just
"fetch the row the other request already created."

This uses a SAVEPOINT (`begin_nested()`) so a conflict only rolls back
this ONE insert attempt, not the rest of the caller's transaction (which
may have other pending, valid changes from earlier in the same request).
"""
from typing import Callable, TypeVar

from sqlalchemy import Select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

T = TypeVar("T")


async def get_or_create(db: AsyncSession, select_stmt: Select, make_row: Callable[[], T]) -> tuple[T, bool]:
    """
    select_stmt must be a query that returns at most one row once the
    target row exists (i.e. filtered on the same column(s) the table's
    unique constraint covers) -- otherwise the retry-fetch after a
    conflict can't reliably find "the" row.

    Returns (row, created) -- created=True only when THIS call inserted
    the row, letting callers that need upsert-style "update on conflict"
    behavior (see api/intake.py's _upsert_carrier_profile) branch on it
    without a second round-trip to figure out which case happened.
    """
    result = await db.execute(select_stmt)
    existing = result.scalar_one_or_none()
    if existing is not None:
        return existing, False

    row = make_row()
    try:
        async with db.begin_nested():
            db.add(row)
            await db.flush()
        return row, True
    except IntegrityError:
        # Lost the race to a concurrent request that committed the same
        # logical row first -- fetch what they created instead of
        # erroring or silently duplicating.
        result = await db.execute(select_stmt)
        return result.scalar_one(), False
