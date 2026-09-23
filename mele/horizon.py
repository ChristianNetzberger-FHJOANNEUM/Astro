"""Equirektangulares 360x180-Panorama -> sichtbarer Horizont h(Az)."""

from __future__ import annotations

import csv
import json
from dataclasses import asdict, dataclass, field
from datetime import datetime
from pathlib import Path

import numpy as np
from PIL import Image, ImageDraw

Image.MAX_IMAGE_PIXELS = None

DEFAULT_PROCESS_WIDTH = 3600
MEDIAN_WINDOW = 9


@dataclass
class HorizonPoint:
    az_deg: float
    alt_deg: float
    x: int
    y: int


@dataclass
class HorizonProfile:
    source: str
    image_width: int
    image_height: int
    process_width: int
    process_height: int
    north_x: float
    projection: str = "equirectangular"
    created_at: str = ""
    points: list[HorizonPoint] = field(default_factory=list)

    def altitude_at(self, az_deg: float) -> float:
        if not self.points:
            return 0.0
        azimuths = np.array([p.az_deg for p in self.points], dtype=np.float64)
        alts = np.array([p.alt_deg for p in self.points], dtype=np.float64)
        order = np.argsort(azimuths)
        azimuths = azimuths[order]
        alts = alts[order]
        az = az_deg % 360.0
        wrap_az = np.concatenate([azimuths - 360.0, azimuths, azimuths + 360.0])
        wrap_alt = np.concatenate([alts, alts, alts])
        return float(np.interp(az, wrap_az, wrap_alt))

    def is_visible(self, az_deg: float, alt_deg: float) -> bool:
        return alt_deg > self.altitude_at(az_deg)


def pixel_to_alt(y: float, height: int) -> float:
    if height <= 1:
        return 0.0
    return 90.0 - 180.0 * y / height


def pixel_to_az(x: float, width: int, north_x: float = 0.0) -> float:
    if width <= 0:
        return 0.0
    return (360.0 * (x - north_x) / width) % 360.0


def alt_to_pixel(alt_deg: float, height: int) -> float:
    return (90.0 - alt_deg) * height / 180.0


def load_panorama(path: Path, process_width: int = DEFAULT_PROCESS_WIDTH) -> tuple[np.ndarray, int, int]:
    image = Image.open(path).convert("RGB")
    src_w, src_h = image.size
    if src_w <= 0 or src_h <= 0:
        raise ValueError(f"Leeres Bild: {path}")
    if process_width < src_w:
        process_height = max(1, round(src_h * process_width / src_w))
        image = image.resize((process_width, process_height), Image.Resampling.BILINEAR)
    rgb = np.asarray(image, dtype=np.uint8)
    return rgb, src_w, src_h


def sky_mask(rgb: np.ndarray) -> np.ndarray:
    """Himmel: blau oder sehr hell (Sonne / Ueberstrahlung)."""
    red = rgb[:, :, 0].astype(np.int16)
    green = rgb[:, :, 1].astype(np.int16)
    blue = rgb[:, :, 2].astype(np.int16)
    is_blue = (blue > red + 8) & (blue > green + 2) & (blue > 70)
    is_sun = (red > 230) & (green > 230) & (blue > 200)
    return is_blue | is_sun


def _column_transition(sky_column: np.ndarray) -> int:
    sky_rows = np.flatnonzero(sky_column)
    if sky_rows.size == 0:
        return 0
    start = int(sky_rows[0])
    blocked = np.flatnonzero(~sky_column[start:])
    if blocked.size == 0:
        return sky_column.size - 1
    return start + int(blocked[0])


def detect_horizon_rows(mask: np.ndarray) -> np.ndarray:
    height, width = mask.shape
    rows = np.empty(width, dtype=np.int32)
    for x in range(width):
        rows[x] = _column_transition(mask[:, x])
    return np.clip(rows, 0, height - 1)


def circular_median(values: np.ndarray, window: int = MEDIAN_WINDOW) -> np.ndarray:
    if window <= 1 or values.size == 0:
        return values.astype(np.float64)
    radius = window // 2
    padded = np.concatenate([values[-radius:], values, values[:radius]])
    smoothed = np.empty(values.size, dtype=np.float64)
    for i in range(values.size):
        smoothed[i] = float(np.median(padded[i : i + window]))
    return smoothed


def detect_horizon(
    path: Path,
    *,
    north_x: float = 0.0,
    process_width: int = DEFAULT_PROCESS_WIDTH,
    median_window: int = MEDIAN_WINDOW,
) -> HorizonProfile:
    rgb, src_w, src_h = load_panorama(path, process_width)
    height, width, _ = rgb.shape
    mask = sky_mask(rgb)
    rows = detect_horizon_rows(mask)
    rows = np.rint(circular_median(rows.astype(np.float64), median_window)).astype(np.int32)
    rows = np.clip(rows, 0, height - 1)
    scale_x = src_w / width
    scale_y = src_h / height
    north = north_x
    points = [
        HorizonPoint(
            az_deg=round(pixel_to_az(x + 0.5, width, north / scale_x if scale_x else north), 4),
            alt_deg=round(pixel_to_alt(float(rows[x]) + 0.5, height), 4),
            x=int(round((x + 0.5) * scale_x)),
            y=int(round((float(rows[x]) + 0.5) * scale_y)),
        )
        for x in range(width)
    ]
    return HorizonProfile(
        source=str(path),
        image_width=src_w,
        image_height=src_h,
        process_width=width,
        process_height=height,
        north_x=north,
        created_at=datetime.now().isoformat(timespec="seconds"),
        points=points,
    )


def save_profile(profile: HorizonProfile, directory: Path) -> dict[str, Path]:
    directory.mkdir(parents=True, exist_ok=True)
    stem = Path(profile.source).stem
    json_path = directory / f"{stem}.horizon.json"
    csv_path = directory / f"{stem}.horizon.csv"
    payload = {
        "source": profile.source,
        "image_width": profile.image_width,
        "image_height": profile.image_height,
        "process_width": profile.process_width,
        "process_height": profile.process_height,
        "north_x": profile.north_x,
        "projection": profile.projection,
        "created_at": profile.created_at,
        "points": [asdict(point) for point in profile.points],
    }
    json_path.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    with csv_path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.writer(handle)
        writer.writerow(["az_deg", "alt_deg", "x", "y"])
        for point in profile.points:
            writer.writerow([point.az_deg, point.alt_deg, point.x, point.y])
    return {"json": json_path, "csv": csv_path}


def render_overlay(path: Path, profile: HorizonProfile, dest: Path, preview_width: int = 2000) -> Path:
    image = Image.open(path).convert("RGB")
    src_w, src_h = image.size
    if preview_width < src_w:
        preview_height = max(1, round(src_h * preview_width / src_w))
        image = image.resize((preview_width, preview_height), Image.Resampling.BILINEAR)
    else:
        preview_width, preview_height = src_w, src_h
    draw = ImageDraw.Draw(image)
    xs = [p.x * preview_width / src_w for p in profile.points]
    ys = [p.y * preview_height / src_h for p in profile.points]
    if len(xs) >= 2:
        draw.line(list(zip(xs, ys)), fill=(220, 40, 40), width=3)
    mid_y = preview_height / 2
    draw.line([(0, mid_y), (preview_width, mid_y)], fill=(40, 80, 220), width=1)
    dest.parent.mkdir(parents=True, exist_ok=True)
    image.save(dest, quality=88)
    return dest
