"""
Prevents Supabase's free-tier project pause (triggered after 7 days with
NO database activity) without paying for a paid plan you don't otherwise
need at this data volume. Runs as a background task inside the bot
process, which is already alive continuously -- no separate cron job, no
exposed port, no GitHub Actions workflow, no additional infrastructure.

Deliberately hits /health/db (a real `SELECT 1` against Postgres), not
/health (process-alive only, touches nothing) -- an app-level health
check that never touches the DB would NOT prevent the pause, since
Supabase's inactivity clock tracks database activity specifically.

Interval is 3 days, not 7 -- a comfortable safety margin against the bot
process itself being restarted/redeployed/briefly down near the 7-day
mark, which would otherwise risk missing the window entirely.
"""
import asyncio
import logging

import httpx

from bot.config import BACKEND_URL

logger = logging.getLogger("freightai.bot")

KEEPALIVE_INTERVAL_SECONDS = 3 * 24 * 60 * 60  # 3 days -- safety margin under Supabase's 7-day pause threshold


async def _ping_once() -> None:
    try:
        async with httpx.AsyncClient(timeout=10) as client:
            r = await client.get(f"{BACKEND_URL}/health/db")
        if r.status_code == 200:
            logger.info("Keep-alive ping succeeded: %s", r.json())
        else:
            logger.warning("Keep-alive ping got unexpected status %d", r.status_code)
    except Exception:
        # Never let a failed ping crash the bot -- worst case, this
        # specific attempt is silently skipped and the next one (3 days
        # later) tries again. A backend that's briefly down doesn't mean
        # give up on the whole mechanism.
        logger.exception("Keep-alive ping failed")


async def keepalive_loop() -> None:
    """Runs forever -- start with asyncio.create_task(keepalive_loop())
    before dp.start_polling(), never awaited directly."""
    while True:
        await _ping_once()
        await asyncio.sleep(KEEPALIVE_INTERVAL_SECONDS)
