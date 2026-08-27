"""
Run with: pytest tests/ (from /backend, with PYTHONPATH set to backend/)

Covers the security fixes made in this pass: bot-signature verification
(closes the X-User-Id spoofing hole) and date normalization (closes the
raw-Arabic-phrase-breaks-datetime-validation gap).
"""
import sys
import time
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "backend"))

from fastapi import HTTPException

from app.core import security
from app.services.date_normalizer import normalize_date_phrase


def test_valid_signature_is_accepted():
    telegram_id = "12345"
    timestamp = str(int(time.time()))
    signature = security.hmac.new(
        security.settings.bot_service_secret.encode(),
        f"{telegram_id}:{timestamp}".encode(),
        security.hashlib.sha256,
    ).hexdigest()
    # Should not raise.
    security.verify_bot_signature(telegram_id, timestamp, signature)


def test_forged_signature_is_rejected():
    telegram_id = "12345"
    timestamp = str(int(time.time()))
    with pytest.raises(HTTPException) as exc:
        security.verify_bot_signature(telegram_id, timestamp, "not-a-real-signature")
    assert exc.value.status_code == 401


def test_stale_signature_is_rejected_even_if_valid():
    telegram_id = "12345"
    old_timestamp = str(int(time.time()) - 3600)  # 1 hour old
    signature = security.hmac.new(
        security.settings.bot_service_secret.encode(),
        f"{telegram_id}:{old_timestamp}".encode(),
        security.hashlib.sha256,
    ).hexdigest()
    with pytest.raises(HTTPException) as exc:
        security.verify_bot_signature(telegram_id, old_timestamp, signature)
    assert exc.value.status_code == 401


def test_signature_for_one_user_does_not_authenticate_another():
    """The exact scenario the old X-User-Id header allowed: claiming to be
    a different user than you actually are."""
    timestamp = str(int(time.time()))
    real_signature = security.hmac.new(
        security.settings.bot_service_secret.encode(),
        f"driver-A:{timestamp}".encode(),
        security.hashlib.sha256,
    ).hexdigest()
    with pytest.raises(HTTPException):
        security.verify_bot_signature("driver-B", timestamp, real_signature)


def test_date_normalizer_handles_iso_and_arabic_and_garbage():
    assert normalize_date_phrase("2026-08-25") is not None
    assert normalize_date_phrase("الخميس") is not None
    assert normalize_date_phrase("") is None
    assert normalize_date_phrase(None) is None
    assert normalize_date_phrase("asdkjhaskjdh not a date") is None
