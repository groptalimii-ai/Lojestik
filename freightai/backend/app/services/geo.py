"""
Free, offline distance estimation for major Saudi/Gulf logistics hubs --
no paid geocoding/maps API. A static coordinate table covers the cities
that actually matter for inter-city road freight on this platform;
anything not in the table just skips the distance estimate rather than
guessing or calling a paid API.

This is what actually populates `locations.latitude/longitude` and
`trip_records.distance_km` (both were designed into the schema for future
ML use but had no data source -- this is that data source, at zero cost).

Straight-line (great-circle) distance, not road distance. For inter-city
Saudi highway routes between major hubs this is a reasonable proxy --
noticeably wrong for anywhere with major detours (e.g. coastal vs.
mountain routes), which is a known limitation, not a hidden one.
"""
import math

# lat, lng in decimal degrees, city centers. Includes common Arabic and
# English spellings/transliterations as separate keys (simplest robust
# approach at this scale -- a proper transliteration-matching layer is
# not worth building until real coverage gaps show up in production data).
CITY_COORDS: dict[str, tuple[float, float]] = {
    "الرياض": (24.7136, 46.6753), "riyadh": (24.7136, 46.6753),
    "جدة": (21.4858, 39.1925), "jeddah": (21.4858, 39.1925), "jedda": (21.4858, 39.1925),
    "الدمام": (26.4207, 50.0888), "dammam": (26.4207, 50.0888),
    "مكة": (21.3891, 39.8579), "مكه": (21.3891, 39.8579), "mecca": (21.3891, 39.8579), "makkah": (21.3891, 39.8579),
    "المدينة": (24.5247, 39.5692), "المدينه": (24.5247, 39.5692), "madinah": (24.5247, 39.5692), "medina": (24.5247, 39.5692),
    "الطائف": (21.2703, 40.4158), "الطايف": (21.2703, 40.4158), "taif": (21.2703, 40.4158),
    "تبوك": (28.3838, 36.5550), "tabuk": (28.3838, 36.5550),
    "أبها": (18.2164, 42.5053), "ابها": (18.2164, 42.5053), "abha": (18.2164, 42.5053),
    "عسير": (18.2164, 42.5053), "aseer": (18.2164, 42.5053),  # region -> capital used as anchor
    "الخبر": (26.2172, 50.1971), "khobar": (26.2172, 50.1971),
    "الأحساء": (25.3833, 49.5833), "الاحساء": (25.3833, 49.5833), "hofuf": (25.3833, 49.5833), "ahsa": (25.3833, 49.5833),
    "جازان": (16.8892, 42.5611), "جيزان": (16.8892, 42.5611), "jazan": (16.8892, 42.5611), "gizan": (16.8892, 42.5611),
    "نجران": (17.4924, 44.1277), "najran": (17.4924, 44.1277),
    "حائل": (27.5114, 41.6900), "hail": (27.5114, 41.6900), "hayil": (27.5114, 41.6900),
    "القصيم": (26.3260, 43.9750), "بريدة": (26.3260, 43.9750), "buraydah": (26.3260, 43.9750), "qassim": (26.3260, 43.9750),
    "عرعر": (30.9753, 41.0381), "arar": (30.9753, 41.0381),
    "الجوف": (29.7860, 39.8579), "jouf": (29.7860, 39.8579), "sakaka": (29.9697, 40.2064), "سكاكا": (29.9697, 40.2064),
    "ينبع": (24.0895, 38.0618), "yanbu": (24.0895, 38.0618),
    "الجبيل": (27.0046, 49.6607), "jubail": (27.0046, 49.6607),
    "الباحة": (20.0129, 41.4677), "الباحه": (20.0129, 41.4677), "baha": (20.0129, 41.4677),
    "دبي": (25.2048, 55.2708), "dubai": (25.2048, 55.2708),
    "الدوحة": (25.2854, 51.5310), "doha": (25.2854, 51.5310),
    "الكويت": (29.3759, 47.9774), "kuwait": (29.3759, 47.9774),
    "المنامة": (26.2285, 50.5860), "manama": (26.2285, 50.5860),
}


def lookup_coords(city_name: str | None) -> tuple[float, float] | None:
    if not city_name:
        return None
    stripped = city_name.strip()
    return CITY_COORDS.get(stripped) or CITY_COORDS.get(stripped.lower())


def _build_canonical_city_map() -> dict[str, str]:
    """
    Groups every alias sharing the same coordinates and maps each one to
    a single canonical spelling (the first key written for that
    coordinate pair in CITY_COORDS above -- e.g. "مكة" over "مكه"/
    "mecca"/"makkah"). Without this, "الطايف" and "الطائف" -- both valid,
    both already recognized by CITY_COORDS as the same city -- would
    silently create TWO separate Location rows, and the route-matching
    feature (intake.py's _find_matching_*_leads) would miss a real match
    just because two messages spelled the same city differently. This is
    not a hypothetical: "الطايف" is a spelling that has actually shown up
    in real intake messages.
    """
    seen_coords: dict[tuple[float, float], str] = {}
    canonical: dict[str, str] = {}
    for key, coords in CITY_COORDS.items():
        if coords not in seen_coords:
            seen_coords[coords] = key
        canonical[key] = seen_coords[coords]
    return canonical


_CANONICAL_CITY_NAMES = _build_canonical_city_map()


def canonicalize_city_name(city_name: str | None) -> str | None:
    """Returns the canonical spelling for a known city so spelling
    variants resolve to the SAME Location row, or the original
    (whitespace-trimmed) input unchanged if it's not a recognized city at
    all. Always call this before creating/looking up a Location."""
    if not city_name:
        return None
    stripped = city_name.strip()
    return _CANONICAL_CITY_NAMES.get(stripped) or _CANONICAL_CITY_NAMES.get(stripped.lower()) or stripped


def haversine_km(lat1: float, lng1: float, lat2: float, lng2: float) -> float:
    earth_radius_km = 6371.0
    phi1, phi2 = math.radians(lat1), math.radians(lat2)
    dphi = math.radians(lat2 - lat1)
    dlambda = math.radians(lng2 - lng1)
    a = math.sin(dphi / 2) ** 2 + math.cos(phi1) * math.cos(phi2) * math.sin(dlambda / 2) ** 2
    return round(earth_radius_km * 2 * math.atan2(math.sqrt(a), math.sqrt(1 - a)), 1)


def estimate_distance_km(origin_city: str | None, destination_city: str | None) -> float | None:
    origin = lookup_coords(origin_city)
    destination = lookup_coords(destination_city)
    if not origin or not destination:
        return None
    return haversine_km(*origin, *destination)


# --- Optional Google Maps upgrade path (frozen until commercial launch) --
# See google_maps_client.py's docstring: these are no-ops unless
# settings.google_maps_enabled is explicitly True. Import is deliberately
# placed here (not at module top) so this file has zero dependency on
# google_maps_client existing/working when Maps stays off -- geo.py must
# keep functioning as the sole distance source if that file is ever
# removed or fails to import for any reason.
from app.services.google_maps_client import geocode_city as _google_geocode_city  # noqa: E402
from app.services.google_maps_client import is_active as google_maps_is_active  # noqa: E402
from app.services.google_maps_client import road_distance_km as _google_road_distance_km  # noqa: E402


async def resolve_city_coords(city_name: str | None) -> tuple[float, float] | None:
    """
    Free static table first (instant, zero network calls, works for the
    ~30 major hubs this platform actually routes between) -- only falls
    through to Google Maps (if enabled) for a city NOT in that table.
    This keeps Maps calls to the rare miss even after commercial launch,
    not the common case.
    """
    coords = lookup_coords(city_name)
    if coords or not city_name:
        return coords
    return await _google_geocode_city(city_name)


async def resolve_distance_km(
    origin_city: str | None,
    origin_coords: tuple[float, float] | None,
    destination_city: str | None,
    destination_coords: tuple[float, float] | None,
) -> float | None:
    """
    Road distance via Google Maps when enabled and both coordinates are
    already known (best accuracy) -- otherwise falls back to the free
    straight-line Haversine estimate. Same return shape either way, so
    callers never need to know which source answered.
    """
    if google_maps_is_active() and origin_coords and destination_coords:
        road_km = await _google_road_distance_km(*origin_coords, *destination_coords)
        if road_km is not None:
            return road_km
    return estimate_distance_km(origin_city, destination_city)
