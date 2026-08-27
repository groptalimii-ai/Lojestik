"""
Run with: pytest tests/ (from /backend, with PYTHONPATH set to backend/)

Only covers the pure-logic piece (seconds_until) without a real Redis --
revoke_token()/is_token_revoked() need an actual Redis connection to
exercise meaningfully and aren't covered here; verify those against a
running Redis (docker compose up) before relying on them.
"""
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "backend"))

from app.core.token_revocation import seconds_until


def test_seconds_until_future_timestamp_is_positive():
    future = int(time.time()) + 3600
    result = seconds_until(future)
    assert 3590 <= result <= 3600


def test_seconds_until_past_timestamp_floors_at_zero():
    past = int(time.time()) - 3600
    assert seconds_until(past) == 0


def test_seconds_until_now_is_near_zero():
    now = int(time.time())
    assert 0 <= seconds_until(now) <= 1
