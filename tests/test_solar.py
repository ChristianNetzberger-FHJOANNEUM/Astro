"""Solarer Meridiandurchgang / True North (Astropy)."""

from __future__ import annotations

from datetime import date, datetime, timedelta, timezone
from math import fabs
from zoneinfo import ZoneInfo

import astropy
from mele.solar import (
    approximate_transit_utc,
    equation_of_time_minutes,
    next_solar_transit,
    shadow_length,
    solar_diagnostics,
    solar_transit,
    solar_transits_for_year,
    sun_hour_angle_deg,
)

# Referenzstandort (Garten / Spec)
REF_LAT = 48.254175
REF_LON = 14.366140  # Ost positiv
REF_ELEV = 250.0
REF_TZ = "Europe/Vienna"


def test_solar_transit_timezone_aware() -> None:
    result = solar_transit(date(2026, 9, 27), REF_LAT, REF_LON, REF_ELEV, REF_TZ)
    assert result.utc.tzinfo is not None
    assert result.local.tzinfo is not None
    assert result.utc.utcoffset() == timedelta(0)
    assert result.local.tzinfo == ZoneInfo(REF_TZ)
    assert result.method == "astropy_hadec_zero"


def test_longitude_east_positive_shifts_noon_earlier_utc() -> None:
    """Ost-Länge: Transit früher in UTC als bei westlicherer Länge."""
    east = solar_transit(date(2026, 6, 21), REF_LAT, 14.0, timezone=REF_TZ)
    west = solar_transit(date(2026, 6, 21), REF_LAT, 10.0, timezone=REF_TZ)
    assert east.utc < west.utc


def test_year_lengths() -> None:
    assert len(solar_transits_for_year(2026, REF_LAT, REF_LON, REF_ELEV, REF_TZ)) == 365
    assert len(solar_transits_for_year(2028, REF_LAT, REF_LON, REF_ELEV, REF_TZ)) == 366


def test_europe_vienna_dst_offsets() -> None:
    jan = solar_transit(date(2026, 1, 15), REF_LAT, REF_LON, REF_ELEV, REF_TZ)
    jul = solar_transit(date(2026, 7, 15), REF_LAT, REF_LON, REF_ELEV, REF_TZ)
    assert jan.local.utcoffset() == timedelta(hours=1)
    assert jul.local.utcoffset() == timedelta(hours=2)
    assert jan.timezone_abbr in {"CET", "MEZ"}
    assert jul.timezone_abbr in {"CEST", "MESZ"}


def test_hour_angle_near_zero_at_transit() -> None:
    result = solar_transit(date(2026, 9, 27), REF_LAT, REF_LON, REF_ELEV, REF_TZ)
    h = sun_hour_angle_deg(
        result.utc, REF_LON, latitude_deg=REF_LAT, elevation_m=REF_ELEV
    )
    assert fabs(h) < 0.001


def test_azimuth_near_south_at_transit() -> None:
    result = solar_transit(date(2026, 9, 27), REF_LAT, REF_LON, REF_ELEV, REF_TZ)
    assert abs((result.azimuth_deg - 180.0 + 180.0) % 360.0 - 180.0) < 0.05
    assert result.altitude_deg > 20.0


def test_reference_2026_09_27_astropy_near_noaa() -> None:
    """2026-09-27 Referenzstandort: Astropy vs NOAA nur gering, nicht ~78 s."""
    day = date(2026, 9, 27)
    result = solar_transit(day, REF_LAT, REF_LON, REF_ELEV, REF_TZ)
    noaa_utc, eot = approximate_transit_utc(day, REF_LON, timezone=REF_TZ)
    delta_sec = abs((result.utc - noaa_utc).total_seconds())
    assert delta_sec < 30.0
    assert fabs(
        sun_hour_angle_deg(result.utc, REF_LON, latitude_deg=REF_LAT, elevation_m=REF_ELEV)
    ) < 0.001
    assert result.local.utcoffset() == timedelta(hours=2)
    assert result.equation_of_time_min is not None
    assert abs(result.equation_of_time_min - eot) < 1e-6
    assert 9 <= result.utc.hour <= 12


def test_year_values_monotonic_and_local_matches_utc() -> None:
    rows = solar_transits_for_year(2026, REF_LAT, REF_LON, REF_ELEV, REF_TZ)
    for prev, cur in zip(rows, rows[1:]):
        assert cur.utc > prev.utc
        assert cur.local.astimezone(timezone.utc) == cur.utc
        assert cur.date == cur.local.date()


def test_dst_transition_days_vienna_2026() -> None:
    before = solar_transit(date(2026, 3, 28), REF_LAT, REF_LON, REF_ELEV, REF_TZ)
    after = solar_transit(date(2026, 3, 30), REF_LAT, REF_LON, REF_ELEV, REF_TZ)
    assert before.local.utcoffset() == timedelta(hours=1)
    assert after.local.utcoffset() == timedelta(hours=2)
    assert abs((after.utc - before.utc).total_seconds() - 2 * 86400) < 30 * 60

    oct_sum = solar_transit(date(2026, 10, 24), REF_LAT, REF_LON, REF_ELEV, REF_TZ)
    oct_win = solar_transit(date(2026, 10, 26), REF_LAT, REF_LON, REF_ELEV, REF_TZ)
    assert oct_sum.local.utcoffset() == timedelta(hours=2)
    assert oct_win.local.utcoffset() == timedelta(hours=1)


def test_next_transit_and_shadow_length() -> None:
    day = date(2026, 9, 27)
    transit = solar_transit(day, REF_LAT, REF_LON, REF_ELEV, REF_TZ)
    before = transit.utc - timedelta(hours=1)
    nxt = next_solar_transit(before, REF_LAT, REF_LON, REF_ELEV, REF_TZ)
    assert nxt.date == day
    after = transit.utc + timedelta(minutes=1)
    nxt2 = next_solar_transit(after, REF_LAT, REF_LON, REF_ELEV, REF_TZ)
    assert nxt2.date == date(2026, 9, 28)
    length = shadow_length(1.0, transit.altitude_deg)
    assert length is not None and length > 0
    assert shadow_length(1.0, -1.0) is None


def test_equation_of_time_noaa_range() -> None:
    stamp = datetime(2026, 9, 27, 12, 0, tzinfo=timezone.utc)
    eot = equation_of_time_minutes(stamp)
    assert -20.0 < eot < 20.0


def test_diagnostics_astropy_vs_noaa() -> None:
    diag = solar_diagnostics(date(2026, 9, 27), REF_LAT, REF_LON, REF_ELEV, REF_TZ)
    assert diag["recommended_for_true_north"] == "astropy_hadec_zero"
    assert "algorithm" in diag
    assert abs(diag["astropy_transit"]["hour_angle_deg"]) < 0.001
    assert abs(diag["delta_astropy_minus_noaa_sec"]) < 30.0
    assert astropy.__version__


def test_legacy_kepler_time_not_user_facing() -> None:
    """Alte Eigenephemeride ~12:52:10 darf nicht die Benutzer-Transitzeit sein."""
    result = solar_transit(date(2026, 9, 27), REF_LAT, REF_LON, REF_ELEV, REF_TZ)
    legacy_wrong = datetime(2026, 9, 27, 12, 52, 10, tzinfo=ZoneInfo(REF_TZ))
    assert abs((result.local - legacy_wrong).total_seconds()) > 45.0
    noaa_utc, _ = approximate_transit_utc(date(2026, 9, 27), REF_LON, timezone=REF_TZ)
    assert abs((result.utc - noaa_utc).total_seconds()) < 30.0
