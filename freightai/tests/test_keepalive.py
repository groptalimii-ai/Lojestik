"""
Run with: pytest tests/ (from repo root, bot/ added to sys.path here since
the rest of the suite targets backend/ only -- see other test files).
"""
import asyncio
import sys
from pathlib import Path
from unittest.mock import AsyncMock, patch

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "bot"))

from bot.keepalive import KEEPALIVE_INTERVAL_SECONDS, _ping_once

SUPABASE_PAUSE_THRESHOLD_SECONDS = 7 * 24 * 60 * 60


def test_interval_has_a_real_safety_margin_under_the_pause_threshold():
    """
    Pins the actual claim made in keepalive.py's docstring and in the
    conversation this was built from: 3 days, comfortably under
    Supabase's 7-day free-tier pause threshold -- not equal to it, not
    close enough that a single missed run risks the project pausing.
    """
    assert KEEPALIVE_INTERVAL_SECONDS < SUPABASE_PAUSE_THRESHOLD_SECONDS
    margin_days = (SUPABASE_PAUSE_THRESHOLD_SECONDS - KEEPALIVE_INTERVAL_SECONDS) / 86400
    assert margin_days >= 2  # at least 2 full days of margin


def test_ping_once_never_raises_on_network_failure():
    """A backend that's briefly unreachable must not crash the bot -- the
    whole point of a background keep-alive task is that its failure is
    invisible to the rest of the bot's operation."""
    with patch("bot.keepalive.httpx.AsyncClient") as mock_client_cls:
        mock_client_cls.return_value.__aenter__ = AsyncMock(side_effect=ConnectionError("down"))
        # Should complete without raising.
        asyncio.run(_ping_once())


def test_ping_once_handles_non_200_status_gracefully():
    class _FakeResponse:
        status_code = 500
        def json(self):
            return {}

    with patch("bot.keepalive.httpx.AsyncClient") as mock_client_cls:
        mock_client = AsyncMock()
        mock_client.get = AsyncMock(return_value=_FakeResponse())
        mock_client_cls.return_value.__aenter__ = AsyncMock(return_value=mock_client)
        # Should complete without raising even on a non-200 response.
        asyncio.run(_ping_once())
