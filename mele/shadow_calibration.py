"""Sonnen-/Schattenkalibrierung des Panorama-Azimuts.

Koordinatensystem des 360-Viewers (pano.html, Y oben, Kamera im Ursprung):

    x = sin(phi) * cos(theta)
    y = cos(phi)
    z = sin(phi) * sin(theta)
    phi = 90° - Hoehe, theta = viewLon

Geografischer Azimut (Nord 0°, Ost 90°), gleicher Nullpunkt wie pixel_to_az / azAltToVec:

    az = (viewLon - north_offset) mod 360
    north_offset = 360° * north_x / Bildbreite

Eine Bildschirmgerade wird nicht verwendet. Die zwei Klicks sind Richtungen
aus der bestehenden Kameraprojektion. Die Schattenrichtung ist die Verbindung
ihrer Schnittpunkte mit der horizontalen Bodenebene unter der Kamera.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from math import atan2, cos, degrees, hypot, radians, sin, sqrt, tan
from pathlib import Path

from mele.ephemeris import sun_radec
from mele.horizon import HorizonProfile, apply_north, load_profile, save_profile
from mele.sky import radec_to_az_alt


class ShadowCalibrationError(ValueError):
    """Klicks oder Zeit reichen fuer eine Kalibrierung nicht."""


@dataclass(frozen=True)
class ShadowCalibration:
    sun_azimuth_deg: float
    sun_altitude_deg: float
    shadow_azimuth_true_deg: float
    shadow_azimuth_measured_deg: float
    panorama_azimuth_offset_deg: float
    north_offset_deg: float
    separation: float
    quality: str
    warning: str

    def as_record(
        self,
        *,
        latitude_deg: float,
        longitude_deg: float,
        when: datetime,
        timezone_name: str,
        ray1: tuple[float, float, float],
        ray2: tuple[float, float, float],
        north_x: float | None,
    ) -> dict:
        return {
            "calibration_method": "solar_shadow",
            "latitude": latitude_deg,
            "longitude": longitude_deg,
            "capture_datetime": when.isoformat(),
            "timezone": timezone_name,
            "sun_azimuth_deg": round(self.sun_azimuth_deg, 4),
            "sun_altitude_deg": round(self.sun_altitude_deg, 4),
            "shadow_azimuth_true_deg": round(self.shadow_azimuth_true_deg, 4),
            "shadow_azimuth_measured_deg": round(self.shadow_azimuth_measured_deg, 4),
            "panorama_azimuth_offset_deg": round(self.panorama_azimuth_offset_deg, 4),
            "north_offset_deg": round(self.north_offset_deg, 4),
            "north_x": None if north_x is None else round(north_x, 4),
            "p1_direction": [round(value, 6) for value in ray1],
            "p2_direction": [round(value, 6) for value in ray2],
        }


def normalize_deg(angle: float) -> float:
    return angle % 360.0


def normalize_signed(angle: float) -> float:
    """Auf [-180°, +180°) falten."""
    return (angle + 180.0) % 360.0 - 180.0


def true_shadow_azimuth(sun_azimuth_deg: float) -> float:
    return normalize_deg(sun_azimuth_deg + 180.0)


def panorama_azimuth_offset(measured_shadow_deg: float, true_shadow_deg: float) -> float:
    return normalize_signed(true_shadow_deg - measured_shadow_deg)


def corrected_north_offset(north_offset_deg: float, azimuth_offset_deg: float) -> float:
    """displayed_az = viewLon - north_offset. Ein positiver Azimut-Offset senkt north_offset."""
    return normalize_deg(north_offset_deg - azimuth_offset_deg)


def north_offset_from_x(north_x: float, image_width: int) -> float:
    if image_width <= 0:
        return 0.0
    return normalize_deg(360.0 * north_x / image_width)


def north_x_from_offset(north_offset_deg: float, image_width: int) -> float:
    if image_width <= 0:
        raise ShadowCalibrationError("Bildbreite fehlt.")
    return normalize_deg(north_offset_deg) * image_width / 360.0


def geographic_azimuth(view_lon_deg: float, north_offset_deg: float) -> float:
    return normalize_deg(view_lon_deg - north_offset_deg)


def parse_capture_time(text: str) -> datetime:
    raw = str(text or "").strip()
    if not raw:
        raise ShadowCalibrationError("Aufnahmezeit fehlt.")
    try:
        stamp = datetime.fromisoformat(raw.replace("Z", "+00:00"))
    except ValueError as exc:
        raise ShadowCalibrationError("Aufnahmezeit ist kein ISO-Zeitstempel.") from exc
    if stamp.tzinfo is None:
        raise ShadowCalibrationError("Aufnahmezeit braucht eine Zeitzone.")
    return stamp


def sun_horizontal(when: datetime, latitude_deg: float, longitude_deg: float) -> tuple[float, float]:
    if when.tzinfo is None:
        raise ShadowCalibrationError("Aufnahmezeit braucht eine Zeitzone.")
    ra, dec = sun_radec(when)
    return radec_to_az_alt(ra, dec, latitude_deg, longitude_deg, when)


def _unit(vector: tuple[float, float, float]) -> tuple[float, float, float]:
    x, y, z = vector
    length = sqrt(x * x + y * y + z * z)
    if length < 1e-12:
        raise ShadowCalibrationError("Blickrichtung ist leer.")
    return x / length, y / length, z / length


def measured_shadow_view_lon(
    ray1: tuple[float, float, float],
    ray2: tuple[float, float, float],
) -> tuple[float, float]:
    """viewLon und Bodenabstand (in Kamerahoehen) der Schattenrichtung P1 -> P2.

    Bodenebene liegt unter der Kamera (Y oben). Der gemeinsame Hoehenfaktor
    kuerzt sich; das Vorzeichen bleibt das der Richtung vom Fusspunkt nach aussen.
    """
    start = _unit(ray1)
    end = _unit(ray2)
    if start[1] >= -0.02 or end[1] >= -0.02:
        raise ShadowCalibrationError(
            "Beide Punkte muessen unter dem Horizont auf dem Boden liegen."
        )
    dx = start[0] / start[1] - end[0] / end[1]
    dz = start[2] / start[1] - end[2] / end[1]
    separation = hypot(dx, dz)
    if separation < 1e-4:
        raise ShadowCalibrationError("Die beiden Punkte liegen zu nah beieinander.")
    view_lon = degrees(atan2(dz, dx)) % 360.0
    return view_lon, separation


def quality_for(separation: float) -> tuple[str, str]:
    if separation < 0.45:
        return (
            "schlecht",
            "Die Punkte liegen nah beieinander. Weiter aussen auf dem Schatten klicken.",
        )
    if separation < 1.2:
        return (
            "mittel",
            "Groesserer Abstand zwischen den Punkten verbessert die Richtung.",
        )
    return "gut", ""


def calibrate_shadow(
    *,
    ray1: tuple[float, float, float],
    ray2: tuple[float, float, float],
    when: datetime,
    latitude_deg: float,
    longitude_deg: float,
    north_offset_deg: float,
) -> ShadowCalibration:
    sun_az, sun_alt = sun_horizontal(when, latitude_deg, longitude_deg)
    true_shadow = true_shadow_azimuth(sun_az)
    view_lon, separation = measured_shadow_view_lon(ray1, ray2)
    measured = geographic_azimuth(view_lon, north_offset_deg)
    offset = panorama_azimuth_offset(measured, true_shadow)
    quality, warning = quality_for(separation)
    return ShadowCalibration(
        sun_azimuth_deg=sun_az,
        sun_altitude_deg=sun_alt,
        shadow_azimuth_true_deg=true_shadow,
        shadow_azimuth_measured_deg=measured,
        panorama_azimuth_offset_deg=offset,
        north_offset_deg=corrected_north_offset(north_offset_deg, offset),
        separation=separation,
        quality=quality,
        warning=warning,
    )


def store_calibration(
    directory: Path,
    image_path: Path,
    *,
    image_width: int,
    image_height: int,
    north_x: float,
    record: dict,
) -> Path:
    """Schreibt den Offset in das bestehende Horizont-JSON. Das Bild bleibt unveraendert."""
    directory.mkdir(parents=True, exist_ok=True)
    json_path = directory / f"{image_path.stem}.horizon.json"
    if json_path.is_file():
        profile = load_profile(json_path)
    else:
        profile = HorizonProfile(
            source=str(image_path),
            image_width=image_width,
            image_height=image_height,
            process_width=0,
            process_height=0,
            north_x=north_x,
            created_at=datetime.now().isoformat(timespec="seconds"),
        )
    if not profile.source:
        profile.source = str(image_path)
    if image_width > 0:
        profile.image_width = image_width
    if image_height > 0:
        profile.image_height = image_height
    profile.north_x = north_x
    profile.calibration = record
    if profile.points:
        apply_north(profile, north_x)
    save_profile(profile, directory)
    return json_path


def _cross(
    left: tuple[float, float, float],
    right: tuple[float, float, float],
) -> tuple[float, float, float]:
    return (
        left[1] * right[2] - left[2] * right[1],
        left[2] * right[0] - left[0] * right[2],
        left[0] * right[1] - left[1] * right[0],
    )


def _dot(left: tuple[float, float, float], right: tuple[float, float, float]) -> float:
    return left[0] * right[0] + left[1] * right[1] + left[2] * right[2]


def _scale(vector: tuple[float, float, float], factor: float) -> tuple[float, float, float]:
    return vector[0] * factor, vector[1] * factor, vector[2] * factor


def _add(
    left: tuple[float, float, float],
    right: tuple[float, float, float],
) -> tuple[float, float, float]:
    return left[0] + right[0], left[1] + right[1], left[2] + right[2]


def viewer_look_direction(lon_deg: float, lat_deg: float) -> tuple[float, float, float]:
    """Blickrichtung von applyLook() in pano.html."""
    phi = radians(90.0 - lat_deg)
    theta = radians(lon_deg)
    return sin(phi) * cos(theta), cos(phi), sin(phi) * sin(theta)


def viewer_basis(
    lon_deg: float,
    lat_deg: float,
) -> tuple[tuple[float, float, float], tuple[float, float, float], tuple[float, float, float]]:
    """Three.js-Kamera: lookAt vom Ursprung, Y oben. Achsen X, Y, Z der Kamera."""
    look = viewer_look_direction(lon_deg, lat_deg)
    z_axis = _scale(look, -1.0)
    x_axis = _unit(_cross((0.0, 1.0, 0.0), z_axis))
    y_axis = _cross(z_axis, x_axis)
    return x_axis, y_axis, z_axis


def viewer_screen_to_world(
    ndc_x: float,
    ndc_y: float,
    *,
    lon_deg: float,
    lat_deg: float,
    fov_deg: float,
    aspect: float,
) -> tuple[float, float, float]:
    """NDC -> Weltrichtung, gleiche Perspektive wie THREE.PerspectiveCamera."""
    x_axis, y_axis, z_axis = viewer_basis(lon_deg, lat_deg)
    half = tan(radians(fov_deg) * 0.5)
    view_x = ndc_x * aspect * half
    view_y = ndc_y * half
    direction = _add(
        _add(_scale(x_axis, view_x), _scale(y_axis, view_y)),
        _scale(z_axis, -1.0),
    )
    return _unit(direction)


def viewer_world_to_ndc(
    direction: tuple[float, float, float],
    *,
    lon_deg: float,
    lat_deg: float,
    fov_deg: float,
    aspect: float,
) -> tuple[float, float]:
    x_axis, y_axis, z_axis = viewer_basis(lon_deg, lat_deg)
    vector = _unit(direction)
    view_z = _dot(vector, z_axis)
    if view_z >= -1e-8:
        raise ShadowCalibrationError("Richtung liegt hinter der Kamera.")
    half = tan(radians(fov_deg) * 0.5)
    ndc_x = (_dot(vector, x_axis) / -view_z) / (aspect * half)
    ndc_y = (_dot(vector, y_axis) / -view_z) / half
    return ndc_x, ndc_y
