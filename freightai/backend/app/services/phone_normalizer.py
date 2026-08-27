"""
Normalizes Saudi mobile numbers to one canonical form, so "0501234567",
"+966 50 123 4567", "00966501234567", and "966-50-123-4567" are all
recognized as the SAME number for dedup/matching purposes.

Without this, every get-or-create-by-phone in the project (Company
lookup, carrier identity, future matching) silently creates a duplicate
row for every different way the same human types their own number --
which defeats the entire point of using phone as the unique key.

Scope: validated strictly for Saudi mobiles (05X.../9665X..., 9 digits
after the country code, starting with 5). Anything else is returned as
digits-only -- still deduplicated among identical retypes of the same
non-Saudi number, just without the format validation.
"""
import re

SAUDI_MOBILE_LOCAL_PATTERN = re.compile(r"^5\d{8}$")  # 9 digits, starts with 5


def normalize_saudi_phone(raw: str | None) -> str | None:
    """Returns a canonical "966XXXXXXXXX" string for a recognizable Saudi
    mobile, a digits-only fallback for anything else, or None if there
    were no digits at all."""
    if not raw:
        return None

    digits = re.sub(r"\D", "", raw)
    if not digits:
        return None

    local = digits
    if local.startswith("00966"):
        local = local[5:]
    elif local.startswith("966"):
        local = local[3:]
    elif local.startswith("0"):
        local = local[1:]

    if SAUDI_MOBILE_LOCAL_PATTERN.match(local):
        return f"966{local}"

    return digits  # unrecognized format -- dedup-only fallback, not validated


def format_for_display(normalized: str | None) -> str:
    if not normalized:
        return "-"
    if normalized.startswith("966") and len(normalized) == 12:
        return f"0{normalized[3:]}"
    return normalized
