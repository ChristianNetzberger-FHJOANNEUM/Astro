"""Benannte Beobachterstandorte."""

from __future__ import annotations

from pathlib import Path

from mele.locations import (
    ensure_default_location,
    get_active_location,
    list_locations,
    set_active_location,
    upsert_location,
)


def test_upsert_and_active(tmp_path: Path) -> None:
    garten = upsert_location(
        tmp_path,
        label="Garten",
        latitude_deg=48.254175,
        longitude_deg=14.366140,
        elevation_m=250,
    )
    assert garten.id == "garten"
    mobile = upsert_location(
        tmp_path,
        label="Sternwarte West",
        latitude_deg=48.3,
        longitude_deg=14.2,
        make_active=True,
    )
    assert mobile.id == "sternwarte-west"
    active = get_active_location(tmp_path)
    assert active is not None
    assert active.id == "sternwarte-west"
    set_active_location(tmp_path, "garten")
    assert get_active_location(tmp_path).id == "garten"
    assert len(list_locations(tmp_path)) == 2


def test_ensure_default_from_config(tmp_path: Path) -> None:
    assert ensure_default_location(tmp_path, latitude_deg=None, longitude_deg=None) is None
    loc = ensure_default_location(
        tmp_path,
        latitude_deg=48.25,
        longitude_deg=14.36,
        elevation_m=250,
    )
    assert loc is not None
    assert loc.label == "Garten"
    # Zweiter Aufruf aendert nicht
    again = ensure_default_location(
        tmp_path,
        latitude_deg=49.0,
        longitude_deg=15.0,
    )
    assert again is not None
    assert again.latitude_deg == 48.25
