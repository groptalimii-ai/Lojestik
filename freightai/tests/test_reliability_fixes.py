"""
Run with: pytest tests/ (from /backend, with PYTHONPATH set to backend/)
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "backend"))

import asyncio

import pytest

from app.api.intake import MAX_EXTRACTED_STR_LEN, _bounded
from app.services import ai_retry
from app.services.ai_retry import MAX_ATTEMPTS, call_with_retry


class _FakeTransientError(Exception):
    """
    Stands in for anthropic.APIConnectionError etc. -- avoids depending on
    guessing the exact constructor signature of the real SDK exception
    classes (which this sandbox can't verify without network access to
    install/inspect the package). The retry logic only cares whether an
    exception's TYPE is in RETRYABLE_EXCEPTIONS, not what it is, so
    monkeypatching that tuple for the duration of these tests exercises
    the real retry/backoff/give-up logic faithfully.
    """


@pytest.fixture(autouse=True)
def _patch_retryable_exceptions(monkeypatch):
    monkeypatch.setattr(ai_retry, "RETRYABLE_EXCEPTIONS", (_FakeTransientError,))
    # Don't actually sleep through the backoff delays in tests.
    monkeypatch.setattr(ai_retry.asyncio, "sleep", lambda _: asyncio.sleep(0))


def test_bounded_truncates_long_strings():
    long_name = "أ" * 500
    result = _bounded(long_name)
    assert len(result) <= MAX_EXTRACTED_STR_LEN


def test_bounded_strips_whitespace_and_handles_none():
    assert _bounded("   خالد   ") == "خالد"
    assert _bounded(None) is None
    assert _bounded("   ") is None  # whitespace-only collapses to None


def test_call_with_retry_succeeds_immediately_without_retrying():
    calls = []

    async def fn():
        calls.append(1)
        return "ok"

    result = asyncio.run(call_with_retry(fn))
    assert result == "ok"
    assert len(calls) == 1


def test_call_with_retry_retries_transient_failure_then_succeeds():
    attempts = {"count": 0}

    async def fn():
        attempts["count"] += 1
        if attempts["count"] < 2:
            raise _FakeTransientError("transient")
        return "ok"

    result = asyncio.run(call_with_retry(fn))
    assert result == "ok"
    assert attempts["count"] == 2


def test_call_with_retry_gives_up_after_max_attempts():
    attempts = {"count": 0}

    async def fn():
        attempts["count"] += 1
        raise _FakeTransientError("still failing")

    with pytest.raises(_FakeTransientError):
        asyncio.run(call_with_retry(fn))
    assert attempts["count"] == MAX_ATTEMPTS


def test_call_with_retry_does_not_retry_non_retryable_errors():
    """A genuine client error (bad request, auth failure) should fail
    immediately -- retrying it would just waste time and attempts."""
    attempts = {"count": 0}

    async def fn():
        attempts["count"] += 1
        raise ValueError("not a retryable error")

    with pytest.raises(ValueError):
        asyncio.run(call_with_retry(fn))
    assert attempts["count"] == 1

