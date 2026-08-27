"""
Google Maps Platform integration -- FROZEN until commercial launch.

This module NEVER calls Google unless BOTH settings.google_maps_enabled is
True AND settings.google_maps_api_key is set. Both default to
off/empty (see core/config.py), so importing or calling anything here in
the current deployment is a guaranteed no-op -- no network call, no risk
of billing, regardless of what's in .env.

Why it exists now instead of being written later: geo.py already has a
free Haversine/static-city path that's the DEFAULT and stays the
default. This module is a strict upgrade path for two things the free
path can't do:
  1. Real road distance (Distance Matrix API) instead of straight-line.
  2. Geocoding for ANY city (not just the ~30 in geo.py's static table).

See README "Google Maps Integration" for exactly how to turn this on.
"""
import logging

import httpx

from app.core.config import settings

logger = logging.getLogger("freightai")

GEOCODE_URL = "https://maps.googleapis.com/maps/api/geocode/json"
DISTANCE_MATRIX_URL = "https://maps.googleapis.com/maps/api/distancematrix/json"


def is_active() -> bool:
    return bool(settings.google_maps_enabled and settings.google_maps_api_key)


async def geocode_city(city_name: str) -> tuple[float, float] | None:
    """Returns (lat, lng) for any city name via Google's Geocoding API, or
    None if Maps is frozen/disabled or the lookup fails. Callers should
    treat None exactly like "not in the free static table" -- i.e. fall
    back gracefully, never error."""
    if not is_active():
        return None

    try:
        async with httpx.AsyncClient(timeout=10) as client:
            resp = await client.get(
                GEOCODE_URL,
                params={
                    "address": f"{city_name}, Saudi Arabia",
                    "key": settings.google_maps_api_key,
                },
            )
        data = resp.json()
        if data.get("status") != "OK" or not data.get("results"):
            return None
        location = data["results"][0]["geometry"]["location"]
        return (location["lat"], location["lng"])
    except Exception:
        logger.exception("Google Geocoding API call failed")
        return None


async def road_distance_km(
    origin_lat: float, origin_lng: float, dest_lat: float, dest_lng: float
) -> float | None:
    """Real road distance in km via the Distance Matrix API, or None if
    Maps is frozen/disabled or the lookup fails."""
    if not is_active():
        return None

    try:
        async with httpx.AsyncClient(timeout=10) as client:
            resp = await client.get(
                DISTANCE_MATRIX_URL,
                params={
                    "origins": f"{origin_lat},{origin_lng}",
                    "destinations": f"{dest_lat},{dest_lng}",
                    "key": settings.google_maps_api_key,
                },
            )
        data = resp.json()
        element = data["rows"][0]["elements"][0]
        if element.get("status") != "OK":
            return None
        return round(element["distance"]["value"] / 1000, 1)  # meters -> km
    except Exception:
        logger.exception("Google Distance Matrix API call failed")
        return None
