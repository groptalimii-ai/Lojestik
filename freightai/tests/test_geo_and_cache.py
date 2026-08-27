"""
Run with: pytest tests/ (from /backend, with PYTHONPATH set to backend/)
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "backend"))

from app.services.ai_cache import _cache_key
from app.services.geo import estimate_distance_km, haversine_km, lookup_coords


def test_known_cities_resolve_coords():
    assert lookup_coords("الرياض") is not None
    assert lookup_coords("jeddah") is not None


def test_unknown_city_returns_none():
    assert lookup_coords("مدينة غير موجودة أبدًا") is None
    assert lookup_coords(None) is None


def test_riyadh_jeddah_distance_is_roughly_correct():
    # Known great-circle distance Riyadh<->Jeddah is ~850km. Wide tolerance
    # on purpose -- this pins "roughly right", not exact city-center precision.
    d = estimate_distance_km("الرياض", "جدة")
    assert d is not None
    assert 750 < d < 950


def test_distance_is_none_when_a_city_is_unknown():
    assert estimate_distance_km("الرياض", "مدينة غير موجودة") is None


def test_spelling_variants_of_a_known_city_canonicalize_to_the_same_name():
    """
    Pins the actual bug found in review: "الطايف" (colloquial spelling,
    used in a real example message) and "الطائف" (standard spelling) are
    both recognized by CITY_COORDS as the same city, but without
    canonicalization they'd create two separate Location rows and the
    intake route-matching feature would silently miss a real match.
    """
    from app.services.geo import canonicalize_city_name

    assert canonicalize_city_name("الطايف") == canonicalize_city_name("الطائف")
    assert canonicalize_city_name("مكه") == canonicalize_city_name("مكة")
    assert canonicalize_city_name("mecca") == canonicalize_city_name("makkah")


def test_canonicalize_unknown_city_returns_stripped_input_unchanged():
    from app.services.geo import canonicalize_city_name

    assert canonicalize_city_name("  مدينة غير معروفة  ") == "مدينة غير معروفة"
    assert canonicalize_city_name(None) is None


def test_haversine_zero_distance_for_same_point():
    assert haversine_km(24.7136, 46.6753, 24.7136, 46.6753) == 0.0


def test_cache_key_is_stable_and_whitespace_insensitive():
    k1 = _cache_key("load", "خالد حمولة 29 طن من الرياض لجدة")
    k2 = _cache_key("load", "خالد   حمولة 29 طن من الرياض لجدة")  # extra spaces
    assert k1 == k2


def test_cache_key_differs_by_namespace():
    k1 = _cache_key("load", "same text")
    k2 = _cache_key("carrier", "same text")
    assert k1 != k2
