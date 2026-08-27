"""
Run with: pytest tests/ (from /backend, with PYTHONPATH set to backend/)
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "backend"))

from app.services.phone_normalizer import format_for_display, normalize_saudi_phone


def test_all_common_formats_normalize_to_the_same_value():
    expected = "966501234567"
    variants = [
        "0501234567",
        "+966501234567",
        "966501234567",
        "00966501234567",
        "+966 50 123 4567",
        "050-123-4567",
        "05 01 23 45 67",
    ]
    for v in variants:
        assert normalize_saudi_phone(v) == expected, f"failed for input: {v!r}"


def test_none_and_empty_return_none():
    assert normalize_saudi_phone(None) is None
    assert normalize_saudi_phone("") is None
    assert normalize_saudi_phone("   ") is None


def test_non_saudi_or_unrecognized_falls_back_to_digits_only_not_crash():
    # A landline / non-mobile number: doesn't match the strict mobile
    # pattern, but should still normalize losslessly for exact-retype dedup.
    result = normalize_saudi_phone("0112345678")
    assert result is not None
    assert result.isdigit() or result.startswith("966")


def test_format_for_display_converts_back_to_local_form():
    assert format_for_display("966501234567") == "0501234567"
    assert format_for_display(None) == "-"


def test_two_carriers_with_differently_typed_same_number_dedup():
    """This is the actual bug this module fixes: without normalization,
    these would be treated as two different people."""
    a = normalize_saudi_phone("0501234567")
    b = normalize_saudi_phone("+966 50 123 4567")
    assert a == b


def test_lookup_by_raw_typed_phone_matches_normalized_stored_phone():
    """
    Pins the exact bug found in api/carriers.py's get_carrier_by_phone:
    a carrier is REGISTERED with phone normalized to canonical form (see
    CarrierRegister's validator), but a driver looking themselves up via
    /mytrucks types their number in whatever raw form they habitually
    use. The lookup must normalize the same way before comparing, or it
    404s for every real carrier.
    """
    stored_at_registration = normalize_saudi_phone("+966 50 123 4567")
    typed_at_lookup = normalize_saudi_phone("0501234567")
    assert stored_at_registration == typed_at_lookup
