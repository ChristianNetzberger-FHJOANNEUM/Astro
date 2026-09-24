from __future__ import annotations

from datetime import datetime, timezone

from mele.sky import (
    az_alt_to_radec,
    format_dec,
    format_pointer,
    format_ra,
    preview_to_horizontal,
    radec_to_az_alt,
)


def test_preview_to_horizontal_matches_equirectangular() -> None:
    az, alt = preview_to_horizontal(0, 0, 360, 180, 360, 180, north_x=0)
    assert abs(az - 0.0) < 1e-6
    assert abs(alt - 90.0) < 1e-6
    az, alt = preview_to_horizontal(90, 90, 360, 180, 360, 180, north_x=0)
    assert abs(az - 90.0) < 1e-6
    assert abs(alt - 0.0) < 1e-6
    az, alt = preview_to_horizontal(90, 90, 360, 180, 360, 180, north_x=90)
    assert abs(az - 0.0) < 1e-6


def test_zenith_declination_equals_latitude() -> None:
    when = datetime(2026, 9, 23, 12, 0, tzinfo=timezone.utc)
    _ra, dec = az_alt_to_radec(120.0, 90.0, 48.2, 16.4, when)
    assert abs(dec - 48.2) < 0.05


def test_north_celestial_pole_at_az_zero_alt_latitude() -> None:
    when = datetime(2026, 9, 23, 12, 0, tzinfo=timezone.utc)
    _ra, dec = az_alt_to_radec(0.0, 48.2, 48.2, 16.4, when)
    assert abs(dec - 90.0) < 0.15


def test_format_ra_dec_and_pointer_without_site() -> None:
    assert format_ra(0.0).startswith("00h")
    assert format_dec(48.2).startswith("+48°")
    text = format_pointer(10.0, 5.0, latitude_deg=None, longitude_deg=None)
    assert "Az" in text
    assert "Standort" in text
    filled = format_pointer(
        10.0,
        5.0,
        latitude_deg=48.2,
        longitude_deg=16.4,
        when=datetime(2026, 9, 23, 12, 0, tzinfo=timezone.utc),
        horizon_alt=2.0,
    )
    assert "RA" in filled
    assert "frei" in filled


def test_radec_many_matches_scalar() -> None:
    from mele.sky import radec_to_az_alt_many
    import numpy as np

    when = datetime(2026, 9, 23, 18, 0, tzinfo=timezone.utc)
    ras = np.array([279.2346, 10.0, 180.0])
    decs = np.array([38.7837, 45.0, -20.0])
    az, alt = radec_to_az_alt_many(ras, decs, 48.2, 16.4, when)
    for index in range(3):
        az0, alt0 = radec_to_az_alt(float(ras[index]), float(decs[index]), 48.2, 16.4, when)
        assert abs((az[index] - az0 + 180) % 360 - 180) < 0.05
        assert abs(alt[index] - alt0) < 0.05


def test_radec_roundtrip_near_horizon() -> None:
    when = datetime(2026, 9, 23, 12, 0, tzinfo=timezone.utc)
    az0, alt0 = 140.0, 25.0
    ra, dec = az_alt_to_radec(az0, alt0, 48.2, 16.4, when)
    az1, alt1 = radec_to_az_alt(ra, dec, 48.2, 16.4, when)
    assert abs((az1 - az0 + 180) % 360 - 180) < 0.2
    assert abs(alt1 - alt0) < 0.2
