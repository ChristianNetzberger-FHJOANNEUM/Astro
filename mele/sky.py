"""Horizontal (Az/h) <-> aequatorial (RA/Dec), Stellarium-Konvention."""

from __future__ import annotations

from datetime import datetime, timezone
from math import asin, atan2, cos, degrees, radians, sin

import numpy as np

from mele.horizon import pixel_to_alt, pixel_to_az


def preview_to_horizontal(
    preview_x: float,
    preview_y: float,
    preview_width: int,
    preview_height: int,
    source_width: int,
    source_height: int,
    north_x: float,
) -> tuple[float, float]:
    if preview_width <= 0 or preview_height <= 0:
        return 0.0, 0.0
    src_w = source_width or preview_width
    src_h = source_height or preview_height
    src_x = preview_x * src_w / preview_width
    src_y = preview_y * src_h / preview_height
    return pixel_to_az(src_x, src_w, north_x), pixel_to_alt(src_y, src_h)


def julian_date(when: datetime) -> float:
    utc = when.astimezone(timezone.utc)
    year, month, day = utc.year, utc.month, utc.day
    frac = (
        utc.hour
        + utc.minute / 60.0
        + utc.second / 3600.0
        + utc.microsecond / 3.6e9
    ) / 24.0
    if month <= 2:
        year -= 1
        month += 12
    century = year // 100
    b = 2 - century + century // 4
    return int(365.25 * (year + 4716)) + int(30.6001 * (month + 1)) + day + b - 1524.5 + frac


def gmst_degrees(when: datetime) -> float:
    """Mittlere Greenwich-Sternzeit in Grad (Meeus, ausreichend fuer Anzeige)."""
    jd = julian_date(when)
    t = (jd - 2451545.0) / 36525.0
    gmst = (
        280.46061837
        + 360.98564736629 * (jd - 2451545.0)
        + 0.000387933 * t * t
        - t * t * t / 38710000.0
    )
    return gmst % 360.0


def lst_degrees(when: datetime, longitude_east_deg: float) -> float:
    return (gmst_degrees(when) + longitude_east_deg) % 360.0


def az_alt_to_radec(
    az_deg: float,
    alt_deg: float,
    latitude_deg: float,
    longitude_deg: float,
    when: datetime,
) -> tuple[float, float]:
    """Azimut von Norden nach Osten, Hoehe in Grad -> (RA_deg, Dec_deg)."""
    az = radians(az_deg % 360.0)
    alt = radians(alt_deg)
    lat = radians(latitude_deg)
    sin_dec = sin(lat) * sin(alt) + cos(lat) * cos(alt) * cos(az)
    sin_dec = max(-1.0, min(1.0, sin_dec))
    dec = asin(sin_dec)
    cos_dec = cos(dec)
    if abs(cos_dec) < 1e-12 or abs(cos(lat)) < 1e-12:
        ha = 0.0
    else:
        sin_ha = -sin(az) * cos(alt) / cos_dec
        cos_ha = (sin(alt) - sin(lat) * sin_dec) / (cos(lat) * cos_dec)
        ha = atan2(sin_ha, cos_ha)
    ra = (lst_degrees(when, longitude_deg) - degrees(ha)) % 360.0
    return ra, degrees(dec)


def radec_to_az_alt(
    ra_deg: float,
    dec_deg: float,
    latitude_deg: float,
    longitude_deg: float,
    when: datetime,
) -> tuple[float, float]:
    """RA/Dec in Grad -> Azimut von Norden nach Osten, Hoehe."""
    ha = radians((lst_degrees(when, longitude_deg) - ra_deg) % 360.0)
    dec = radians(dec_deg)
    lat = radians(latitude_deg)
    sin_alt = sin(lat) * sin(dec) + cos(lat) * cos(dec) * cos(ha)
    sin_alt = max(-1.0, min(1.0, sin_alt))
    alt = asin(sin_alt)
    cos_alt = cos(alt)
    if abs(cos_alt) < 1e-12 or abs(cos(lat)) < 1e-12:
        az = 0.0
    else:
        sin_az = -sin(ha) * cos(dec) / cos_alt
        cos_az = (sin(dec) - sin(lat) * sin_alt) / (cos(lat) * cos_alt)
        az = atan2(sin_az, cos_az)
    return degrees(az) % 360.0, degrees(alt)


def radec_to_az_alt_many(
    ra_deg: np.ndarray,
    dec_deg: np.ndarray,
    latitude_deg: float,
    longitude_deg: float,
    when: datetime,
) -> tuple[np.ndarray, np.ndarray]:
    """Vektorisierte RA/Dec -> Az/h, gleiche Konvention wie radec_to_az_alt."""
    ra = np.asarray(ra_deg, dtype=np.float64)
    dec = np.asarray(dec_deg, dtype=np.float64)
    lst = lst_degrees(when, longitude_deg)
    ha = np.radians((lst - ra) % 360.0)
    dec_r = np.radians(dec)
    lat = radians(latitude_deg)
    sin_alt = np.sin(lat) * np.sin(dec_r) + np.cos(lat) * np.cos(dec_r) * np.cos(ha)
    sin_alt = np.clip(sin_alt, -1.0, 1.0)
    alt = np.arcsin(sin_alt)
    cos_alt = np.cos(alt)
    safe = (np.abs(cos_alt) >= 1e-12) & (abs(cos(lat)) >= 1e-12)
    sin_az = np.zeros_like(alt)
    cos_az = np.ones_like(alt)
    sin_az[safe] = -np.sin(ha[safe]) * np.cos(dec_r[safe]) / cos_alt[safe]
    cos_az[safe] = (np.sin(dec_r[safe]) - np.sin(lat) * sin_alt[safe]) / (
        np.cos(lat) * cos_alt[safe]
    )
    az = np.degrees(np.arctan2(sin_az, cos_az)) % 360.0
    return az, np.degrees(alt)


def format_ra(ra_deg: float) -> str:
    hours = (ra_deg % 360.0) / 15.0
    h = int(hours)
    minutes = (hours - h) * 60.0
    m = int(minutes)
    s = (minutes - m) * 60.0
    return f"{h:02d}h {m:02d}m {s:05.2f}s"


def format_dec(dec_deg: float) -> str:
    sign = "+" if dec_deg >= 0 else "-"
    value = abs(dec_deg)
    d = int(value)
    minutes = (value - d) * 60.0
    m = int(minutes)
    s = (minutes - m) * 60.0
    return f"{sign}{d:02d}° {m:02d}' {s:04.1f}\""


def format_latitude(lat_deg: float) -> str:
    """Geographische Breite als Grad/Minuten/Sekunden mit N/S."""
    hemi = "N" if lat_deg >= 0 else "S"
    return f"{_format_dms_abs(lat_deg)} {hemi}"


def format_longitude(lon_deg: float) -> str:
    """Geographische Laenge als Grad/Minuten/Sekunden mit E/W."""
    hemi = "E" if lon_deg >= 0 else "W"
    return f"{_format_dms_abs(lon_deg)} {hemi}"


def _format_dms_abs(deg: float) -> str:
    value = abs(float(deg))
    d = int(value)
    minutes = (value - d) * 60.0
    m = int(minutes)
    s = (minutes - m) * 60.0
    if s >= 59.95:
        s = 0.0
        m += 1
    if m >= 60:
        m = 0
        d += 1
    return f"{d:02d}° {m:02d}' {s:04.1f}\""


def format_angle(deg: float) -> str:
    sign = "-" if deg < 0 else ""
    value = abs(deg)
    d = int(value)
    minutes = (value - d) * 60.0
    m = int(minutes)
    s = (minutes - m) * 60.0
    return f"{sign}{d:03d}° {m:02d}' {s:04.1f}\""


def format_pointer(
    az_deg: float,
    alt_deg: float,
    *,
    latitude_deg: float | None,
    longitude_deg: float | None,
    when: datetime | None = None,
    horizon_alt: float | None = None,
    include_site: bool = True,
) -> str:
    lines = [
        f"Az  {format_angle(az_deg)}     h  {format_angle(alt_deg)}",
    ]
    now = when or datetime.now(timezone.utc)
    if latitude_deg is None or longitude_deg is None:
        lines.append("RA/Dec: Standort in configs/mele.yaml setzen")
        if include_site:
            lines.append("(latitude_deg, longitude_deg; Ost positiv)")
    else:
        ra, dec = az_alt_to_radec(az_deg, alt_deg, latitude_deg, longitude_deg, now)
        lines.append(f"RA  {format_ra(ra)}     Dec {format_dec(dec)}")
        if include_site:
            hemi_ns = "N" if latitude_deg >= 0 else "S"
            hemi_ew = "E" if longitude_deg >= 0 else "W"
            lines.append(
                f"Standort  {abs(latitude_deg):.4f}° {hemi_ns}, "
                f"{abs(longitude_deg):.4f}° {hemi_ew}"
            )
    if include_site:
        lines.append(now.astimezone(timezone.utc).strftime("Epoche  %Y-%m-%d  %H:%M:%S UTC"))
    if horizon_alt is not None:
        free = alt_deg > horizon_alt
        lines.append(
            f"Horizont hier  {horizon_alt:+.2f}°   "
            f"{'frei' if free else 'verdeckt'}"
        )
    return "\n".join(lines)
