"""
Exact-text Redis cache for AI extraction calls.

Honest about what this is: an exact-match cache keyed on a hash of the
normalized input text -- NOT semantic/fuzzy matching (that would need
embeddings, which is a real infrastructure cost, and overkill at this
data volume). It's still a genuine, zero-cost win in THIS workflow
specifically: an operator re-pasting a driver's forwarded message, or a
driver re-sending an unedited message after a network hiccup, produces
byte-identical text extremely often. Catching that with a hash lookup
costs nothing extra and skips a paid Anthropic call entirely.

Not a cache for anything else -- no fuzzy similarity, no "did the user
mean the same thing with different words" cleverness. Overselling this as
smarter than it is would just cause confusing bugs later.
"""
import hashlib
import json

from app.core.redis_client import get_redis

CACHE_TTL_SECONDS = 60 * 60 * 24 * 7  # 7 days -- long enough to catch re-sends/retries


def _cache_key(namespace: str, text: str) -> str:
    normalized = " ".join(text.strip().split())  # collapse whitespace differences only
    digest = hashlib.sha256(normalized.encode()).hexdigest()[:24]
    return f"aicache:{namespace}:{digest}"


async def get_cached_extraction(namespace: str, text: str) -> dict | None:
    r = get_redis()
    raw = await r.get(_cache_key(namespace, text))
    return json.loads(raw) if raw else None


async def set_cached_extraction(namespace: str, text: str, value: dict) -> None:
    r = get_redis()
    await r.set(_cache_key(namespace, text), json.dumps(value), ex=CACHE_TTL_SECONDS)
