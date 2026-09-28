"""Solarer Meridiandurchgang (True North / Schattenmethode).

Solar transit is defined as the instant when the center of the Sun
crosses the observer's local meridian (local solar hour angle = 0).
For the configured northern-hemisphere site this corresponds to
solar azimuth approximately 180° and a vertical pole's shadow
pointing toward true north.

Methode (ab Korrektur):
  - Astropy get_sun (ERFA/VSOP87A built-in, offline, kein JPL-Download)
  - Beobachter: EarthLocation; Meridianbedingung via HADec-Stundenwinkel H = 0
  - Startwert: NOAA solareqns.PDF  t ≈ 720 − 4·λ − E
  - Bisektion von H auf Subsekunden
  - NOAA nur Validierung / Diagnose, nicht zweite Benutzer-Transitzeit

Referenzen:
  https://gml.noaa.gov/grad/solcalc/solareqns.PDF
  https://docs.astropy.org/en/stable/coordinates/solarsystem.html
"""

from __future__ import annotations

import calendar
import logging
from dataclasses import dataclass
from datetime import date, datetime, timedelta, timezone as dt_timezone
from functools import lru_cache
from math import cos, pi, sin, tan
from zoneinfo import ZoneInfo

import astropy.units as u
from astropy.coordinates import EarthLocation, HADec, AltAz, get_sun
from astropy.time import Time
from astropy.utils import iers

# Offline: keine IERS-Downloads im Normalbetrieb (MeLE ohne Netz).
iers.conf.auto_download = False
iers.conf.iers_degraded_accuracy = "warn"

logger = logging.getLogger(__name__)

_NOAA_HALF_WINDOW_MIN = 5.0
_BISECT_TOL_SEC = 0.25
_MAX_BISECT = 64


@dataclass(frozen=True)
class SolarTransit:
    date: date
    utc: datetime
    local: datetime
    azimuth_deg: float
    altitude_deg: float
    equation_of_time_min: float | None
    timezone: str = "Europe/Vienna"
    latitude_deg: float = 0.0
    longitude_deg: float = 0.0
    elevation_m: float = 0.0
    solver_iterations: int = 0
    method: str = "astropy_hadec_zero"

    @property
    def timezone_abbr(self) -> str:
        return self.local.tzname() or ""


def shadow_length(pole_height_m: float, solar_altitude_deg: float) -> float | None:
    """Schattenlänge eines senkrechten Stabes; None wenn Sonne nicht über dem Horizont."""
    if pole_height_m <= 0 or solar_altitude_deg <= 0:
        return None
    return float(pole_height_m) / tan(solar_altitude_deg * pi / 180.0)


def equation_of_time_minutes(when: datetime) -> float:
    """NOAA equation of time in Minuten (gml.noaa.gov/grad/solcalc/solareqns.PDF)."""
    utc = when.astimezone(dt_timezone.utc)
    doy = utc.timetuple().tm_yday
    hour = utc.hour + utc.minute / 60.0 + utc.second / 3600.0 + utc.microsecond / 3.6e9
    gamma = 2.0 * pi / 365.0 * (doy - 1 + (hour - 12.0) / 24.0)
    return 229.18 * (
        0.000075
        + 0.001868 * cos(gamma)
        - 0.032077 * sin(gamma)
        - 0.014615 * cos(2.0 * gamma)
        - 0.040849 * sin(2.0 * gamma)
    )


def _earth_location(latitude_deg: float, longitude_deg: float, elevation_m: float) -> EarthLocation:
    return EarthLocation(
        lat=float(latitude_deg) * u.deg,
        lon=float(longitude_deg) * u.deg,
        height=float(elevation_m or 0.0) * u.m,
    )


def _as_utc_datetime(when: datetime) -> datetime:
    if when.tzinfo is None:
        return when.replace(tzinfo=dt_timezone.utc)
    return when.astimezone(dt_timezone.utc)


def sun_hour_angle_deg(
    when: datetime,
    longitude_deg: float,
    *,
    latitude_deg: float = 0.0,
    elevation_m: float = 0.0,
) -> float:
    """Scheinbarer lokaler Stundenwinkel der Sonne (Astropy HADec), (−180, +180]."""
    utc = _as_utc_datetime(when)
    location = _earth_location(latitude_deg, longitude_deg, elevation_m)
    stamp = Time(utc)
    sun = get_sun(stamp)
    hadec = sun.transform_to(HADec(obstime=stamp, location=location))
    return float(hadec.ha.wrap_at(180 * u.deg).degree)


def sun_az_alt_deg(
    when: datetime,
    latitude_deg: float,
    longitude_deg: float,
    elevation_m: float = 0.0,
) -> tuple[float, float]:
    """Scheinbarer Azimut/Höhe der Sonne (Astropy AltAz, ohne Refraktion)."""
    utc = _as_utc_datetime(when)
    location = _earth_location(latitude_deg, longitude_deg, elevation_m)
    stamp = Time(utc)
    frame = AltAz(obstime=stamp, location=location, pressure=0 * u.hPa)
    altaz = get_sun(stamp).transform_to(frame)
    return float(altaz.az.degree) % 360.0, float(altaz.alt.degree)


def approximate_transit_utc(
    day: date,
    longitude_deg: float,
    *,
    timezone: str = "Europe/Vienna",
) -> tuple[datetime, float]:
    """NOAA-Näherung des Transits in UTC + Gleichung der Zeit (Minuten).

    Nur Startwert / Validierung — nicht die Benutzer-Transitdefinition.
    solar_noon_UTC_minutes ≈ 720 − 4·longitude_east − equation_of_time_min
    """
    tz = ZoneInfo(timezone)
    local_noon = datetime(day.year, day.month, day.day, 12, 0, 0, tzinfo=tz)
    seed = local_noon.astimezone(dt_timezone.utc)
    eot = equation_of_time_minutes(seed)
    utc_date = seed.date()
    base = datetime(utc_date.year, utc_date.month, utc_date.day, tzinfo=dt_timezone.utc)
    minutes = 720.0 - 4.0 * float(longitude_deg) - eot
    return base + timedelta(minutes=minutes), eot


def _bisect_hour_angle_zero(
    t_lo: datetime,
    t_hi: datetime,
    *,
    latitude_deg: float,
    longitude_deg: float,
    elevation_m: float,
) -> tuple[datetime, int]:
    def ha(stamp: datetime) -> float:
        return sun_hour_angle_deg(
            stamp,
            longitude_deg,
            latitude_deg=latitude_deg,
            elevation_m=elevation_m,
        )

    h_lo = ha(t_lo)
    h_hi = ha(t_hi)
    if h_lo > 0 and h_hi > 0:
        t_lo = t_lo - timedelta(minutes=_NOAA_HALF_WINDOW_MIN)
        h_lo = ha(t_lo)
    if h_lo < 0 and h_hi < 0:
        t_hi = t_hi + timedelta(minutes=_NOAA_HALF_WINDOW_MIN)
        h_hi = ha(t_hi)
    if h_lo * h_hi > 0:
        center = t_lo + (t_hi - t_lo) / 2
        found = False
        for step in range(-24, 25):
            a = center + timedelta(minutes=5 * step)
            b = a + timedelta(minutes=5)
            ha_a = ha(a)
            ha_b = ha(b)
            if ha_a <= 0 <= ha_b or ha_b <= 0 <= ha_a:
                t_lo, t_hi, h_lo, h_hi = a, b, ha_a, ha_b
                found = True
                break
        if not found:
            raise RuntimeError("Kein Stundenwinkel-Null Durchgang gefunden")

    if h_lo > h_hi:
        t_lo, t_hi = t_hi, t_lo
        h_lo, h_hi = h_hi, h_lo

    iterations = 0
    while iterations < _MAX_BISECT:
        iterations += 1
        mid = t_lo + (t_hi - t_lo) / 2
        if (t_hi - t_lo).total_seconds() <= _BISECT_TOL_SEC:
            return mid.astimezone(dt_timezone.utc), iterations
        h_mid = ha(mid)
        if h_mid <= 0:
            t_lo = mid
        else:
            t_hi = mid
    return (t_lo + (t_hi - t_lo) / 2).astimezone(dt_timezone.utc), iterations


def solar_transit(
    day: date,
    latitude_deg: float,
    longitude_deg: float,
    elevation_m: float = 0.0,
    timezone: str = "Europe/Vienna",
) -> SolarTransit:
    """Scheinbarer Meridiandurchgang (Astropy H = 0) für den lokalen Kalendertag `day`."""
    guess, eot = approximate_transit_utc(day, longitude_deg, timezone=timezone)
    t_lo = guess - timedelta(minutes=_NOAA_HALF_WINDOW_MIN)
    t_hi = guess + timedelta(minutes=_NOAA_HALF_WINDOW_MIN)
    utc, iterations = _bisect_hour_angle_zero(
        t_lo,
        t_hi,
        latitude_deg=latitude_deg,
        longitude_deg=longitude_deg,
        elevation_m=elevation_m,
    )
    tz = ZoneInfo(timezone)
    local = utc.astimezone(tz)
    az, alt = sun_az_alt_deg(utc, latitude_deg, longitude_deg, elevation_m)
    result = SolarTransit(
        date=day,
        utc=utc,
        local=local,
        azimuth_deg=float(az),
        altitude_deg=float(alt),
        equation_of_time_min=float(eot),
        timezone=timezone,
        latitude_deg=float(latitude_deg),
        longitude_deg=float(longitude_deg),
        elevation_m=float(elevation_m or 0.0),
        solver_iterations=iterations,
        method="astropy_hadec_zero",
    )
    if logger.isEnabledFor(logging.DEBUG):
        logger.debug(
            "solar transit: date=%s lat=%.6f lon=%.6f elev=%.1f utc=%s local=%s "
            "alt=%.3f az=%.3f eot_min=%.3f solver_iterations=%d H=%.6f method=%s",
            day.isoformat(),
            latitude_deg,
            longitude_deg,
            elevation_m,
            utc.isoformat(),
            local.isoformat(),
            alt,
            az,
            eot,
            iterations,
            sun_hour_angle_deg(
                utc, longitude_deg, latitude_deg=latitude_deg, elevation_m=elevation_m
            ),
            result.method,
        )
    return result


def solar_transits_for_year(
    year: int,
    latitude_deg: float,
    longitude_deg: float,
    elevation_m: float = 0.0,
    timezone: str = "Europe/Vienna",
) -> list[SolarTransit]:
    """Alle Transits eines Jahres (365 bzw. 366)."""
    return list(
        _solar_transits_for_year_cached(
            int(year),
            round(float(latitude_deg), 6),
            round(float(longitude_deg), 6),
            round(float(elevation_m or 0.0), 1),
            str(timezone or "Europe/Vienna"),
        )
    )


@lru_cache(maxsize=32)
def _solar_transits_for_year_cached(
    year: int,
    latitude_deg: float,
    longitude_deg: float,
    elevation_m: float,
    timezone: str,
) -> tuple[SolarTransit, ...]:
    days_in_year = 366 if calendar.isleap(year) else 365
    start = date(year, 1, 1)
    return tuple(
        solar_transit(
            start + timedelta(days=offset),
            latitude_deg,
            longitude_deg,
            elevation_m=elevation_m,
            timezone=timezone,
        )
        for offset in range(days_in_year)
    )


def next_solar_transit(
    when: datetime,
    latitude_deg: float,
    longitude_deg: float,
    elevation_m: float = 0.0,
    timezone: str = "Europe/Vienna",
) -> SolarTransit:
    """Nächster Meridiandurchgang ab `when` (timezone-aware)."""
    if when.tzinfo is None:
        when = when.replace(tzinfo=dt_timezone.utc)
    tz = ZoneInfo(timezone)
    local_now = when.astimezone(tz)
    today = solar_transit(
        local_now.date(),
        latitude_deg,
        longitude_deg,
        elevation_m=elevation_m,
        timezone=timezone,
    )
    if today.utc > when.astimezone(dt_timezone.utc):
        return today
    tomorrow = local_now.date() + timedelta(days=1)
    return solar_transit(
        tomorrow,
        latitude_deg,
        longitude_deg,
        elevation_m=elevation_m,
        timezone=timezone,
    )


def transit_to_dict(transit: SolarTransit) -> dict:
    return {
        "date": transit.date.isoformat(),
        "utc": transit.utc.astimezone(dt_timezone.utc).isoformat().replace("+00:00", "Z"),
        "local": transit.local.isoformat(),
        "timezone": transit.timezone,
        "timezone_abbr": transit.timezone_abbr,
        "azimuth_deg": round(transit.azimuth_deg, 3),
        "altitude_deg": round(transit.altitude_deg, 2),
        "equation_of_time_min": (
            None
            if transit.equation_of_time_min is None
            else round(transit.equation_of_time_min, 3)
        ),
        "shadow_azimuth_deg": 0.0,
        "latitude_deg": transit.latitude_deg,
        "longitude_deg": transit.longitude_deg,
        "elevation_m": transit.elevation_m,
        "method": transit.method,
        "solver_iterations": transit.solver_iterations,
    }


ALGORITHM_NOTES = {
    "definition": (
        "Solar transit = instant when the apparent center of the Sun crosses the observer's "
        "local meridian (local solar hour angle H = 0). Northern hemisphere: azimuth ≈ 180°, "
        "vertical pole shadow → true north (az 0°)."
    ),
    "sun_ephemeris": (
        "astropy.coordinates.get_sun — ERFA/VSOP87A built-in (GCRS), offline, no JPL file download. "
        "Includes effects consistent with Astropy coordinate transforms (e.g. aberration in GCRS)."
    ),
    "frame": (
        "EarthLocation + HADec for hour angle; AltAz (pressure=0, no refraction) for az/alt at transit."
    ),
    "solver": (
        "Initial guess: NOAA solareqns.PDF  t_noon_UTC_min ≈ 720 − 4·λ_east − E(γ). "
        "Then bisection of Astropy HA on ±5 min until <0.25 s."
    ),
    "noaa_role": (
        "NOAA solar noon is validation / start guess only — not a second user-facing transit definition."
    ),
    "references": [
        "https://gml.noaa.gov/grad/solcalc/solareqns.PDF",
        "https://docs.astropy.org/en/stable/coordinates/solarsystem.html",
    ],
}


def noaa_solar_noon(
    day: date,
    latitude_deg: float,
    longitude_deg: float,
    elevation_m: float = 0.0,
    timezone: str = "Europe/Vienna",
) -> dict:
    """NOAA solar-noon (Validierung) + Astropy Az/h zu diesem Zeitpunkt."""
    utc, eot = approximate_transit_utc(day, longitude_deg, timezone=timezone)
    tz = ZoneInfo(timezone)
    local = utc.astimezone(tz)
    az, alt = sun_az_alt_deg(utc, latitude_deg, longitude_deg, elevation_m)
    h = sun_hour_angle_deg(
        utc, longitude_deg, latitude_deg=latitude_deg, elevation_m=elevation_m
    )
    return {
        "date": day.isoformat(),
        "utc": utc.isoformat().replace("+00:00", "Z"),
        "local": local.isoformat(),
        "timezone": timezone,
        "timezone_abbr": local.tzname() or "",
        "equation_of_time_min": round(eot, 3),
        "azimuth_deg": round(az, 3),
        "altitude_deg": round(alt, 2),
        "hour_angle_deg": round(h, 6),
        "shadow_azimuth_deg": 0.0,
        "latitude_deg": float(latitude_deg),
        "longitude_deg": float(longitude_deg),
        "elevation_m": float(elevation_m or 0.0),
        "method": "noaa_solar_noon_validation",
    }


def solar_diagnostics(
    day: date,
    latitude_deg: float,
    longitude_deg: float,
    elevation_m: float = 0.0,
    timezone: str = "Europe/Vienna",
) -> dict:
    """Astropy-Transit vs. NOAA-Validierung inkl. Zwischenwerte."""
    transit = solar_transit(day, latitude_deg, longitude_deg, elevation_m, timezone)
    noaa = noaa_solar_noon(day, latitude_deg, longitude_deg, elevation_m, timezone)
    noaa_utc = datetime.fromisoformat(noaa["utc"].replace("Z", "+00:00"))
    delta_s = (transit.utc - noaa_utc).total_seconds()
    h = sun_hour_angle_deg(
        transit.utc,
        longitude_deg,
        latitude_deg=latitude_deg,
        elevation_m=elevation_m,
    )
    return {
        "algorithm": ALGORITHM_NOTES,
        "recommended_for_true_north": "astropy_hadec_zero",
        "astropy_transit": {
            **transit_to_dict(transit),
            "hour_angle_deg": round(h, 6),
        },
        "noaa_validation": noaa,
        "delta_astropy_minus_noaa_sec": round(delta_s, 3),
        "interpretation": (
            f"Astropy-Transit liegt {abs(delta_s):.1f} s "
            f"{'frueher' if delta_s < 0 else 'spaeter'} als NOAA-Solar-Noon (Validierung). "
            "Benutzer-Anzeige = Astropy; NOAA nur Diagnose."
        ),
    }
