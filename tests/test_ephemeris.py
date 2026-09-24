from datetime import datetime, timedelta, timezone
from math import acos, cos, degrees, radians, sin

from mele.ephemeris import (
    illumination_from_sep,
    moon_radec,
    solar_system_bodies,
    sun_radec,
)


def _sep(ra1: float, dec1: float, ra2: float, dec2: float) -> float:
    a1, d1, a2, d2 = (radians(ra1), radians(dec1), radians(ra2), radians(dec2))
    return degrees(acos(max(-1.0, min(1.0, sin(d1) * sin(d2) + cos(d1) * cos(d2) * cos(a1 - a2)))))


def test_sun_near_2026_autumnal_equinox() -> None:
    when = datetime(2026, 9, 23, 0, 5, tzinfo=timezone.utc)
    ra, dec = sun_radec(when)
    assert abs((ra - 180.0 + 180) % 360 - 180) < 1.2
    assert abs(dec) < 0.6


def test_moon_moves_about_a_dozen_degrees_per_day() -> None:
    a = datetime(2026, 9, 23, 0, 0, tzinfo=timezone.utc)
    b = a + timedelta(days=1)
    ra0, dec0 = moon_radec(a)
    ra1, dec1 = moon_radec(b)
    assert 10.0 < _sep(ra0, dec0, ra1, dec1) < 16.0


def test_moon_phase_from_elongation() -> None:
    assert illumination_from_sep(0.0) < 0.02
    assert illumination_from_sep(180.0) > 0.98
    assert abs(illumination_from_sep(90.0) - 0.5) < 0.02
    when = datetime(2026, 9, 23, 18, 0, tzinfo=timezone.utc)
    moon = next(item for item in solar_system_bodies(when) if item.key == "Moon")
    assert moon.diam_deg == 0.5
    assert 0.0 <= (moon.phase or 0) <= 1.0


def test_venus_stays_near_the_sun() -> None:
    when = datetime(2026, 9, 23, 18, 0, tzinfo=timezone.utc)
    bodies = {item.key: item for item in solar_system_bodies(when)}
    assert _sep(bodies["Sun"].ra_deg, bodies["Sun"].dec_deg, bodies["Venus"].ra_deg, bodies["Venus"].dec_deg) < 48.0
    assert "Mond" in {item.name for item in bodies.values()}
    assert "Jupiter" in bodies


def test_overlay_includes_moon_and_planets(tmp_path) -> None:
    from mele.catalog import query_overlay
    from mele.horizon import HorizonPoint, HorizonProfile

    when = datetime(2026, 9, 23, 22, 0, tzinfo=timezone.utc)
    open_sky = HorizonProfile(
        source="open",
        image_width=360,
        image_height=180,
        process_width=360,
        process_height=180,
        north_x=0.0,
        points=[
            HorizonPoint(az_deg=float(step), alt_deg=-90.0, x=step, y=0)
            for step in range(0, 360, 10)
        ],
    )
    data = query_overlay(
        db_path=tmp_path / "missing.sqlite",
        latitude_deg=48.2,
        longitude_deg=16.4,
        when=when,
        stars=False,
        constellations=False,
        messier=False,
        ngc=False,
        planets=True,
        profile=open_sky,
    )
    names = {item["name"] for item in data["bodies"]}
    assert "Mond" in names
    assert "Venus" in names
    assert "Sonne" in names
    moon = next(item for item in data["bodies"] if item["kind"] == "moon")
    assert moon["diam_deg"] == 0.5
    assert "sun_az" in moon
    assert 0.0 <= moon["phase"] <= 1.0
    off = query_overlay(
        db_path=tmp_path / "missing.sqlite",
        latitude_deg=48.2,
        longitude_deg=16.4,
        when=when,
        stars=False,
        constellations=False,
        messier=False,
        planets=False,
    )
    assert off["bodies"] == []
    assert "error" in off
