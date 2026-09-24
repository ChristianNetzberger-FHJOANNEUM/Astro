"""Sonne, Mond und Planeten: J2000-Kepler / Meeus, nur Anzeige (offline)."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from math import acos, asin, atan2, cos, degrees, hypot, radians, sin, sqrt, tan

from mele.sky import julian_date

# a, e, I, L, long_peri, long_node  und Raten / Jahrhundert (JPL 1800-2050).
_PLANETS = {
    "Merkur": (
        (0.38709927, 0.20563593, 7.00497902, 252.25032350, 77.45779628, 48.33076593),
        (0.00000037, 0.00001906, -0.00594749, 149472.67411175, 0.16047689, -0.12534081),
    ),
    "Venus": (
        (0.72333566, 0.00677672, 3.39467605, 181.97909950, 131.60246718, 76.67984255),
        (0.00000390, -0.00004107, -0.00078890, 58517.81538729, 0.00268329, -0.27769418),
    ),
    "Erde": (
        (1.00000261, 0.01671123, -0.00001531, 100.46457166, 102.93768193, 0.0),
        (0.00000562, -0.00004392, -0.01294668, 35999.37244981, 0.32327364, 0.0),
    ),
    "Mars": (
        (1.52371034, 0.09339410, 1.84969142, -4.55343205, -23.94362959, 49.55953891),
        (0.00001847, 0.00007882, -0.00813131, 19140.30268499, 0.44441088, -0.29257343),
    ),
    "Jupiter": (
        (5.20288700, 0.04838624, 1.30439695, 34.39644051, 14.72847983, 100.47390909),
        (-0.00011607, -0.00013253, -0.00183714, 3034.74612775, 0.21252668, 0.20469106),
    ),
    "Saturn": (
        (9.53667594, 0.05386179, 2.48599187, 49.95424423, 92.59887831, 113.66242448),
        (-0.00125060, -0.00050991, 0.00193609, 1222.49362201, -0.41897216, -0.28867794),
    ),
    "Uranus": (
        (19.18916464, 0.04725744, 0.77263783, 313.23810451, 170.95427630, 74.01692503),
        (-0.00196176, -0.00004397, -0.00242939, 428.48202785, 0.40805281, 0.04240589),
    ),
    "Neptun": (
        (30.06952752, 0.00859048, 1.77004347, -55.12002969, 44.96476227, 131.78422574),
        (0.00026291, 0.00005105, 0.00035372, 218.45945325, -0.32241464, -0.00508664),
    ),
}

_PLANET_MAG = {
    "Merkur": -0.4,
    "Venus": -4.0,
    "Mars": -1.0,
    "Jupiter": -2.2,
    "Saturn": 0.7,
    "Uranus": 5.7,
    "Neptun": 7.8,
}


@dataclass(frozen=True)
class SkyBody:
    key: str
    name: str
    ra_deg: float
    dec_deg: float
    mag: float
    kind: str
    phase: float | None = None
    diam_deg: float | None = None


def angular_sep_deg(ra1: float, dec1: float, ra2: float, dec2: float) -> float:
    a1, d1, a2, d2 = radians(ra1), radians(dec1), radians(ra2), radians(dec2)
    return degrees(acos(max(-1.0, min(1.0, sin(d1) * sin(d2) + cos(d1) * cos(d2) * cos(a1 - a2)))))


def illumination_from_sep(sep_deg: float) -> float:
    """Neumond 0, Vollmond 1; Elongation Sonne–Mond."""
    return 0.5 * (1.0 - cos(radians(sep_deg)))


def centuries_j2000(when: datetime) -> float:
    return (julian_date(when) - 2451545.0) / 36525.0


def obliquity_deg(t: float) -> float:
    return 23.439291 - 0.0130042 * t


def ecliptic_to_radec(lon_deg: float, lat_deg: float, t: float) -> tuple[float, float]:
    lon = radians(lon_deg)
    lat = radians(lat_deg)
    eps = radians(obliquity_deg(t))
    sin_dec = sin(lat) * cos(eps) + cos(lat) * sin(eps) * sin(lon)
    sin_dec = max(-1.0, min(1.0, sin_dec))
    dec = degrees(asin(sin_dec))
    y = sin(lon) * cos(eps) - tan(lat) * sin(eps)
    ra = degrees(atan2(y, cos(lon))) % 360.0
    return ra, dec


def _kepler_e(mean_anomaly_deg: float, ecc: float) -> float:
    mean = radians(mean_anomaly_deg)
    ecc_anom = mean
    for _ in range(10):
        delta = (ecc_anom - ecc * sin(ecc_anom) - mean) / (1.0 - ecc * cos(ecc_anom))
        ecc_anom -= delta
        if abs(delta) < 1e-10:
            break
    return ecc_anom


def _heliocentric(name: str, t: float) -> tuple[float, float, float]:
    base, rate = _PLANETS[name]
    a, ecc, incl, lon, peri, node = (base[i] + rate[i] * t for i in range(6))
    mean = (lon - peri) % 360.0
    ecc_anom = _kepler_e(mean, ecc)
    x_orb = a * (cos(ecc_anom) - ecc)
    y_orb = a * sqrt(max(0.0, 1.0 - ecc * ecc)) * sin(ecc_anom)
    arg = radians(peri - node)
    node_r = radians(node)
    incl_r = radians(incl)
    x_ecl = x_orb * (cos(arg) * cos(node_r) - sin(arg) * sin(node_r) * cos(incl_r)) + y_orb * (
        -sin(arg) * cos(node_r) - cos(arg) * sin(node_r) * cos(incl_r)
    )
    y_ecl = x_orb * (cos(arg) * sin(node_r) + sin(arg) * cos(node_r) * cos(incl_r)) + y_orb * (
        -sin(arg) * sin(node_r) + cos(arg) * cos(node_r) * cos(incl_r)
    )
    z_ecl = x_orb * (sin(arg) * sin(incl_r)) + y_orb * (cos(arg) * sin(incl_r))
    return x_ecl, y_ecl, z_ecl


def _xyz_to_radec(x: float, y: float, z: float, t: float) -> tuple[float, float]:
    lon = degrees(atan2(y, x)) % 360.0
    lat = degrees(atan2(z, hypot(x, y)))
    return ecliptic_to_radec(lon, lat, t)


def sun_radec(when: datetime) -> tuple[float, float]:
    t = centuries_j2000(when)
    xe, ye, ze = _heliocentric("Erde", t)
    return _xyz_to_radec(-xe, -ye, -ze, t)


def moon_radec(when: datetime) -> tuple[float, float]:
    """Meeus Kap. 47, grobe periodische Terme (ca. 0.3 deg)."""
    t = centuries_j2000(when)
    l0 = 218.3164477 + 481267.88123421 * t
    d = 297.8501921 + 445267.1114034 * t
    m = 357.5291092 + 35999.0502909 * t
    mp = 134.9633964 + 477198.8675055 * t
    f = 93.2720950 + 483202.0175233 * t

    def s(*terms: float) -> float:
        return sin(radians(sum(terms)))

    lon = (
        l0
        + 6.289 * s(mp)
        + 1.274 * s(2 * d - mp)
        + 0.658 * s(2 * d)
        + 0.214 * s(2 * mp)
        - 0.186 * s(m)
        - 0.114 * s(2 * f)
        + 0.059 * s(2 * d - 2 * mp)
        + 0.057 * s(2 * d - m - mp)
        + 0.053 * s(2 * d + mp)
        + 0.046 * s(2 * d - m)
        + 0.041 * s(m - mp)
        - 0.035 * s(d)
        - 0.031 * s(m + mp)
    )
    lat = (
        5.128 * s(f)
        + 0.2806 * s(mp + f)
        + 0.2777 * s(mp - f)
        + 0.1732 * s(2 * d - f)
        + 0.0554 * s(2 * d - mp + f)
        + 0.0463 * s(2 * d - mp - f)
        + 0.0326 * s(2 * d + f)
    )
    return ecliptic_to_radec(lon % 360.0, lat, t)


def _moon_mag(when: datetime) -> float:
    t = centuries_j2000(when)
    d = radians(297.8501921 + 445267.1114034 * t)
    phase = (1.0 + cos(d)) / 2.0
    return -12.7 + 2.5 * (1.0 - phase)


def solar_system_bodies(when: datetime) -> list[SkyBody]:
    t = centuries_j2000(when)
    earth = _heliocentric("Erde", t)
    bodies: list[SkyBody] = []
    sun_ra, sun_dec = sun_radec(when)
    bodies.append(SkyBody("Sun", "Sonne", sun_ra, sun_dec, -26.7, "sun", diam_deg=0.5))
    moon_ra, moon_dec = moon_radec(when)
    phase = illumination_from_sep(angular_sep_deg(sun_ra, sun_dec, moon_ra, moon_dec))
    bodies.append(
        SkyBody(
            "Moon",
            "Mond",
            moon_ra,
            moon_dec,
            _moon_mag(when),
            "moon",
            phase=phase,
            diam_deg=0.5,
        )
    )
    for name in ("Merkur", "Venus", "Mars", "Jupiter", "Saturn", "Uranus", "Neptun"):
        x, y, z = _heliocentric(name, t)
        ra, dec = _xyz_to_radec(x - earth[0], y - earth[1], z - earth[2], t)
        bodies.append(SkyBody(name, name, ra, dec, _PLANET_MAG[name], "planet"))
    return bodies
