"""
Retry wrapper for Anthropic API calls. Previously a single network blip,
a transient Anthropic-side rate limit, or a brief 5xx would fail the
whole extraction immediately -- no automatic retry existed anywhere in
the project. Transient failures now get retried with exponential
backoff; genuine client errors (bad API key, malformed request) are
deliberately NOT retried since retrying won't fix them -- it would just
burn the attempt budget and make the user wait longer for the same
failure.
"""
import asyncio
import logging
from typing import Awaitable, Callable, TypeVar

import anthropic

logger = logging.getLogger("freightai")

T = TypeVar("T")

RETRYABLE_EXCEPTIONS = (
    anthropic.APIConnectionError,
    anthropic.APITimeoutError,
    anthropic.RateLimitError,
    anthropic.InternalServerError,
)

MAX_ATTEMPTS = 3
BASE_DELAY_SECONDS = 1.0


async def call_with_retry(fn: Callable[[], Awaitable[T]]) -> T:
    """Usage: await call_with_retry(lambda: client.messages.create(...))"""
    last_exc: Exception | None = None
    for attempt in range(1, MAX_ATTEMPTS + 1):
        try:
            return await fn()
        except RETRYABLE_EXCEPTIONS as e:
            last_exc = e
            if attempt == MAX_ATTEMPTS:
                break
            delay = BASE_DELAY_SECONDS * (2 ** (attempt - 1))
            logger.warning(
                "Anthropic API call failed (attempt %d/%d): %s -- retrying in %.1fs",
                attempt, MAX_ATTEMPTS, e, delay,
            )
            await asyncio.sleep(delay)
    raise last_exc
