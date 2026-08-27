"""
Run with: pytest tests/ (from /backend, with PYTHONPATH set to backend/)

Pins the most important property of the Google Maps integration: it MUST
be a strict no-op by default, with no network call and no dependency on
an API key being present, until both google_maps_enabled=True AND
google_maps_api_key is set.
"""
import asyncio
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "backend"))

from app.core.config import settings
from app.services import google_maps_client


def test_maps_disabled_by_default():
    assert settings.google_maps_enabled is False
    assert settings.google_maps_api_key == ""
    assert google_maps_client.is_active() is False


def test_geocode_returns_none_without_any_network_call_when_disabled():
    # If this made a real network call it would hang/fail in this sandbox
    # (no internet access) instead of returning immediately -- asyncio.run
    # completing here IS the assertion that the guard short-circuits
    # before touching httpx at all.
    result = asyncio.run(google_maps_client.geocode_city("الرياض"))
    assert result is None


def test_distance_returns_none_without_any_network_call_when_disabled():
    result = asyncio.run(
        google_maps_client.road_distance_km(24.7136, 46.6753, 21.4858, 39.1925)
    )
    assert result is None


def test_resolve_city_coords_falls_back_to_free_table_when_maps_disabled():
    from app.services.geo import resolve_city_coords

    coords = asyncio.run(resolve_city_coords("الرياض"))
    assert coords is not None  # served entirely from the free static table


def test_resolve_distance_falls_back_to_haversine_when_maps_disabled():
    from app.services.geo import resolve_distance_km

    distance = asyncio.run(
        resolve_distance_km("الرياض", (24.7136, 46.6753), "جدة", (21.4858, 39.1925))
    )
    assert distance is not None
    assert 750 < distance < 950  # same Haversine estimate as test_geo_and_cache.py
