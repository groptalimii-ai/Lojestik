"""
Turns a free-text date phrase (Arabic or English, absolute or relative --
"2026-08-25", "الخميس", "يوم الأحد الجاي", "next Thursday") into a real
datetime.

Previously this problem was solved twice, inconsistently, and neither
solve was complete:
- extraction.py asked the Anthropic model to resolve dates itself, with no
  guaranteed format -- if it returned "الخميس" unparsed, LoadCreate's
  `loading_date: datetime` field would fail Pydantic validation.
- The bot's truck-adding flow (bot/handlers/truck.py) collected the same
  kind of phrase for `available_from` and then explicitly did NOT send it
  to the backend at all, because there was nowhere to parse it.

Both now call this single function, so a route only has to pick a
reasonable default (currently: prefer the nearest FUTURE occurrence of a
weekday, e.g. "الخميس" said on a Friday means next week's Thursday).
"""
from datetime import datetime

import dateparser

_SETTINGS = {
    "PREFER_DATES_FROM": "future",
    "TIMEZONE": "Asia/Riyadh",
    "RETURN_AS_TIMEZONE_AWARE": True,
    "RELATIVE_BASE": None,  # dateparser fills this with "now" per call
}


def normalize_date_phrase(text: str | None) -> datetime | None:
    """
    Returns a timezone-aware datetime, or None if `text` is empty or
    unparseable. Never raises -- an unparseable date should degrade to
    "we don't know", not a 500 error on a load/truck submission.
    """
    if not text or not text.strip():
        return None

    parsed = dateparser.parse(text.strip(), languages=["ar", "en"], settings=_SETTINGS)
    return parsed
