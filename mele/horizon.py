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
class SkySample:
    preview_x: float
    preview_y: float
    r: int
    g: int
    b: int
    source_x: float = -1.0
    source_y: float = -1.0


@dataclass
class SunExclude:
    source_x: float
    source_y: float
    source_radius: float
    preview_x: float = 0.0
    preview_y: float = 0.0
    preview_radius: float = 24.0


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
    calibration: dict | None = None
    control_points: list[dict[str, float]] | None = None

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
    """Himmel: Blaukanal oder die helle Sonnenscheibe, nicht sonnenbeschienenes Gras."""
    red = rgb[:, :, 0].astype(np.int16)
    green = rgb[:, :, 1].astype(np.int16)
    blue = rgb[:, :, 2].astype(np.int16)
    is_blue = (blue > red + 8) & (blue > green + 2) & (blue > 70)
    is_sun = (red > 230) & (green > 230) & (blue > 200)
    return is_blue | is_sun


def rgb_to_hsv(rgb: np.ndarray) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    """RGB 0..255 -> Hue 0..360, Sat 0..1, Val 0..1."""
    red = rgb[..., 0].astype(np.float64) / 255.0
    green = rgb[..., 1].astype(np.float64) / 255.0
    blue = rgb[..., 2].astype(np.float64) / 255.0
    maxc = np.maximum(np.maximum(red, green), blue)
    minc = np.minimum(np.minimum(red, green), blue)
    delta = maxc - minc
    value = maxc
    sat = np.divide(delta, maxc, out=np.zeros_like(maxc), where=maxc > 1e-12)
    hue = np.zeros_like(maxc)
    usable = delta > 1e-12
    eq_r = usable & (maxc == red)
    eq_g = usable & (maxc == green) & ~eq_r
    eq_b = usable & (maxc == blue) & ~eq_r & ~eq_g
    hue[eq_r] = ((green[eq_r] - blue[eq_r]) / delta[eq_r]) % 6.0
    hue[eq_g] = (blue[eq_g] - red[eq_g]) / delta[eq_g] + 2.0
    hue[eq_b] = (red[eq_b] - green[eq_b]) / delta[eq_b] + 4.0
    return (hue * 60.0) % 360.0, sat, value


def _hue_near(hue: np.ndarray, center: float, pad: float) -> np.ndarray:
    delta = np.abs(hue - center) % 360.0
    return np.minimum(delta, 360.0 - delta) <= pad


def sample_from_preview(path: Path, x: float, y: float, radius: int = 2) -> SkySample:
    rgb = np.asarray(Image.open(path).convert("RGB"), dtype=np.uint8)
    red, green, blue = sample_color_patch(rgb, x, y, radius)
    return SkySample(preview_x=x, preview_y=y, r=red, g=green, b=blue)


def sample_color_patch(rgb: np.ndarray, x: float, y: float, radius: int = 2) -> tuple[int, int, int]:
    height, width, _ = rgb.shape
    xi = int(round(x))
    yi = int(round(y))
    x0, x1 = max(0, xi - radius), min(width, xi + radius + 1)
    y0, y1 = max(0, yi - radius), min(height, yi + radius + 1)
    if x1 <= x0 or y1 <= y0:
        return 0, 0, 0
    med = np.median(rgb[y0:y1, x0:x1].reshape(-1, 3), axis=0)
    return int(med[0]), int(med[1]), int(med[2])


def sky_mask_from_samples(
    rgb: np.ndarray,
    samples: list[SkySample] | list[tuple[int, int, int]],
    *,
    hue_pad: float = 14.0,
    sat_pad: float = 0.18,
    val_pad: float = 0.18,
    include_sun: bool = False,
    reject: list[SkySample] | list[tuple[int, int, int]] | None = None,
) -> np.ndarray:
    """Himmelsmaske wie ein Qualifier. Weiss/Sonne gehoert nicht in diese Box."""
    if not samples:
        return np.zeros(rgb.shape[:2], dtype=bool)
    hue, sat, val = rgb_to_hsv(rgb)
    mask = np.zeros(rgb.shape[:2], dtype=bool)
    for sample in samples:
        if isinstance(sample, SkySample):
            color = np.array([[[sample.r, sample.g, sample.b]]], dtype=np.uint8)
        else:
            color = np.array([[[sample[0], sample[1], sample[2]]]], dtype=np.uint8)
        sh, ss, sv = rgb_to_hsv(color)
        mask |= (
            _hue_near(hue, float(sh[0, 0]), hue_pad)
            & (np.abs(sat - float(ss[0, 0])) <= sat_pad)
            & (np.abs(val - float(sv[0, 0])) <= val_pad)
        )
    if include_sun:
        red = rgb[:, :, 0]
        green = rgb[:, :, 1]
        blue = rgb[:, :, 2]
        mask |= (red > 230) & (green > 230) & (blue > 200)
    for sample in reject or []:
        if isinstance(sample, SkySample):
            color = np.array([[[sample.r, sample.g, sample.b]]], dtype=np.uint8)
        else:
            color = np.array([[[sample[0], sample[1], sample[2]]]], dtype=np.uint8)
        sh, ss, sv = rgb_to_hsv(color)
        near = (
            _hue_near(hue, float(sh[0, 0]), max(8.0, hue_pad * 0.7))
            & (np.abs(sat - float(ss[0, 0])) <= sat_pad)
            & (np.abs(val - float(sv[0, 0])) <= val_pad)
        )
        mask &= ~near
    return mask


def keep_sky_connected_to_top(sky: np.ndarray) -> np.ndarray:
    """Nur die Himmelsschicht, die mit der obersten Bildzeile zusammenhaengt (360-Wrap)."""
    height, width = sky.shape
    if height == 0 or width == 0:
        return sky
    keep = np.zeros_like(sky, dtype=bool)
    keep[0] = sky[0]
    for y in range(1, height):
        keep[y] = _fill_sky_row(sky[y], keep[y - 1])
    return keep


def _fill_sky_row(sky_row: np.ndarray, from_above: np.ndarray) -> np.ndarray:
    width = int(sky_row.size)
    out = np.zeros(width, dtype=bool)
    index = 0
    while index < width:
        if not sky_row[index]:
            index += 1
            continue
        start = index
        while index < width and sky_row[index]:
            index += 1
        if from_above[start:index].any():
            out[start:index] = True
    if sky_row[0] and sky_row[-1] and (out[0] or out[-1]):
        pos = 0
        while pos < width and sky_row[pos]:
            out[pos] = True
            pos += 1
        pos = width - 1
        while pos >= 0 and sky_row[pos]:
            out[pos] = True
            pos -= 1
    return out


def apply_sun_excludes(
    mask: np.ndarray,
    excludes: list[SunExclude],
    src_w: int,
    src_h: int,
) -> np.ndarray:
    """Sonnen-Kreise werden Himmel (kein Hindernis), unabhaengig von der Farbe."""
    if not excludes:
        return mask
    height, width = mask.shape
    out = mask.copy()
    yy, xx = np.ogrid[:height, :width]
    for excl in excludes:
        cx = excl.source_x * width / src_w
        cy = excl.source_y * height / src_h
        radius = max(2.0, excl.source_radius * width / src_w)
        dx = np.minimum(np.abs(xx - cx), width - np.abs(xx - cx))
        out[(dx * dx + (yy - cy) * (yy - cy)) <= radius * radius] = True
    return out


def find_sun_excludes(rgb: np.ndarray, src_w: int, src_h: int) -> list[SunExclude]:
    """Hellste kompakte Flecken in der oberen Haelfte, nicht die Hauswand."""
    height, width, _ = rgb.shape
    red = rgb[:, :, 0]
    green = rgb[:, :, 1]
    blue = rgb[:, :, 2]
    bright = (red >= 245) & (green >= 245) & (blue >= 228)
    bright[int(height * 0.46) :, :] = False
    if not bright.any():
        bright = (red >= 236) & (green >= 236) & (blue >= 215)
        bright[int(height * 0.46) :, :] = False
    if not bright.any():
        return []
    rows, cols = np.where(bright)
    cx = float(np.median(cols))
    cy = float(np.median(rows))
    dist = np.sqrt((cols - cx) ** 2 + (rows - cy) ** 2)
    radius = max(10.0, float(np.percentile(dist, 92)) * 1.55)
    return [
        SunExclude(
            source_x=cx * src_w / width,
            source_y=cy * src_h / height,
            source_radius=radius * src_w / width,
        )
    ]


def _column_transition(sky_column: np.ndarray) -> int:
    """Erste Hinderniskante von oben; kleine schwebende Inseln (Sonne) werden uebersprungen.

    Nicht bottom-up: einzelne falsch-blaue Pixel am Nadir wuerden sonst
    die Linie an den unteren Bildrand ziehen.
    """
    height = int(sky_column.size)
    if height == 0:
        return 0
    y = 0
    while y < height and not sky_column[y]:
        y += 1
    if y >= height:
        return 0
    max_island = max(8, height // 30)
    sky_limit = height // 2
    while y < height:
        if sky_column[y]:
            y += 1
            continue
        end = y
        while end < height and not sky_column[end]:
            end += 1
        if end >= height:
            return y
        if (end - y) <= max_island and y < sky_limit:
            y = end
            continue
        return y
    return height - 1


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


def profile_from_mask(
    path: Path,
    mask: np.ndarray,
    src_w: int,
    src_h: int,
    north_x: float,
    median_window: int = MEDIAN_WINDOW,
) -> HorizonProfile:
    height, width = mask.shape
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


def refine_sky_mask(
    mask: np.ndarray,
    rgb: np.ndarray,
    src_w: int,
    src_h: int,
    excludes: list[SunExclude] | None = None,
    *,
    auto_sun: bool = True,
) -> np.ndarray:
    cleaned = keep_sky_connected_to_top(mask)
    found = list(excludes or [])
    if auto_sun and not found:
        found.extend(find_sun_excludes(rgb, src_w, src_h))
    return apply_sun_excludes(cleaned, found, src_w, src_h)


def detect_horizon(
    path: Path,
    *,
    north_x: float = 0.0,
    process_width: int = DEFAULT_PROCESS_WIDTH,
    median_window: int = MEDIAN_WINDOW,
    excludes: list[SunExclude] | None = None,
) -> HorizonProfile:
    rgb, src_w, src_h = load_panorama(path, process_width)
    red = rgb[:, :, 0]
    green = rgb[:, :, 1]
    blue = rgb[:, :, 2]
    is_blue = (blue > red + 8) & (blue > green + 2) & (blue > 70)
    mask = refine_sky_mask(is_blue, rgb, src_w, src_h, excludes, auto_sun=True)
    return profile_from_mask(path, mask, src_w, src_h, north_x, median_window)


def profile_belongs_to(profile: HorizonProfile | None, image_path: Path | None) -> bool:
    if profile is None or image_path is None:
        return False
    source = Path(profile.source)
    return source.stem == image_path.stem or source.name == image_path.name


def _sample_colors(
    rgb: np.ndarray,
    samples: list[SkySample] | list[tuple[int, int, int]],
    src_w: int,
    src_h: int,
) -> list[tuple[int, int, int]]:
    height, width, _ = rgb.shape
    colors: list[tuple[int, int, int]] = []
    for sample in samples:
        if isinstance(sample, SkySample) and sample.source_x >= 0 and sample.source_y >= 0:
            px = sample.source_x * width / src_w
            py = sample.source_y * height / src_h
            colors.append(sample_color_patch(rgb, px, py))
        elif isinstance(sample, SkySample):
            colors.append((sample.r, sample.g, sample.b))
        else:
            colors.append((sample[0], sample[1], sample[2]))
    return colors


def detect_horizon_from_samples(
    path: Path,
    samples: list[SkySample] | list[tuple[int, int, int]],
    *,
    north_x: float = 0.0,
    process_width: int = DEFAULT_PROCESS_WIDTH,
    median_window: int = MEDIAN_WINDOW,
    hue_pad: float = 14.0,
    sat_pad: float = 0.18,
    val_pad: float = 0.18,
    reject: list[SkySample] | list[tuple[int, int, int]] | None = None,
    excludes: list[SunExclude] | None = None,
    auto_sun: bool = True,
) -> HorizonProfile:
    rgb, src_w, src_h = load_panorama(path, process_width)
    colors = _sample_colors(rgb, samples, src_w, src_h)
    reject_colors = _sample_colors(rgb, reject or [], src_w, src_h)
    mask = sky_mask_from_samples(
        rgb,
        colors,
        hue_pad=hue_pad,
        sat_pad=sat_pad,
        val_pad=val_pad,
        include_sun=False,
        reject=reject_colors,
    )
    mask = refine_sky_mask(mask, rgb, src_w, src_h, excludes, auto_sun=auto_sun)
    return profile_from_mask(path, mask, src_w, src_h, north_x, median_window)


def floor_sky_mask(profile: HorizonProfile, width: int, height: int) -> np.ndarray:
    """True = Himmel oberhalb der Floor-Kurve (Punktwolke / Zeichnung)."""
    sky = np.ones((height, width), dtype=bool)
    src_w = profile.image_width or width
    north = profile.north_x * width / src_w if src_w else profile.north_x
    for x in range(width):
        az = pixel_to_az(x + 0.5, width, north)
        y = int(round(alt_to_pixel(profile.altitude_at(az), height)))
        y = max(0, min(height, y))
        sky[y:, x] = False
    return sky


def merge_sky_with_floor(color_sky: np.ndarray, floor_profile: HorizonProfile) -> np.ndarray:
    """Hybrid: Floor erzwingt Himmel darueber; Farbe fuellt zusaetzlich darunter (Blau)."""
    if color_sky.dtype != np.bool_ and color_sky.dtype != bool:
        color_sky = color_sky.astype(bool)
    height, width = color_sky.shape
    return floor_sky_mask(floor_profile, width, height) | color_sky


def detect_horizon_hybrid(
    path: Path,
    samples: list[SkySample] | list[tuple[int, int, int]],
    floor_profile: HorizonProfile,
    *,
    north_x: float | None = None,
    process_width: int = DEFAULT_PROCESS_WIDTH,
    median_window: int = MEDIAN_WINDOW,
    hue_pad: float = 14.0,
    sat_pad: float = 0.18,
    val_pad: float = 0.18,
    reject: list[SkySample] | list[tuple[int, int, int]] | None = None,
    excludes: list[SunExclude] | None = None,
    auto_sun: bool = True,
) -> tuple[HorizonProfile, np.ndarray]:
    """Punktwolken-Floor + Farbpicker.

    Returns:
        profile: Silhouette aus der gemergten Maske
        mask_u8: 0=Himmel, 255=Boden (2D, nicht nur aus der Kurve neu gebaut)
    """
    rgb, src_w, src_h = load_panorama(path, process_width)
    height, width = rgb.shape[:2]
    colors = _sample_colors(rgb, samples, src_w, src_h)
    reject_colors = _sample_colors(rgb, reject or [], src_w, src_h)
    color_sky = sky_mask_from_samples(
        rgb,
        colors,
        hue_pad=hue_pad,
        sat_pad=sat_pad,
        val_pad=val_pad,
        include_sun=False,
        reject=reject_colors,
    )
    color_sky = refine_sky_mask(color_sky, rgb, src_w, src_h, excludes, auto_sun=auto_sun)
    # Floor auf Process-Aufloesung bringen (Altitude-Interpolation unabhaengig von process_width)
    floor = HorizonProfile(
        source=floor_profile.source,
        image_width=src_w,
        image_height=src_h,
        process_width=width,
        process_height=height,
        north_x=north_x if north_x is not None else floor_profile.north_x,
        created_at=floor_profile.created_at,
        points=list(floor_profile.points),
        calibration=floor_profile.calibration,
        control_points=floor_profile.control_points,
    )
    hybrid = merge_sky_with_floor(color_sky, floor)
    north = floor.north_x
    profile = profile_from_mask(path, hybrid, src_w, src_h, north, median_window)
    if floor.control_points is not None:
        profile.control_points = list(floor.control_points)
    mask_u8 = np.where(hybrid, 0, 255).astype(np.uint8)
    return profile, mask_u8


def profile_from_manual_points(
    path: Path | str,
    points_xy: list[tuple[float, float]],
    *,
    image_width: int,
    image_height: int,
    north_x: float = 0.0,
    process_width: int = DEFAULT_PROCESS_WIDTH,
) -> HorizonProfile:
    """Zirkulaer interpolierte Horizontlinie aus gesetzten Stuetzpunkten (Originalpixel)."""
    if image_width <= 0 or image_height <= 0:
        raise ValueError("Bildgroesse fehlt.")
    if not points_xy:
        raise ValueError("Mindestens einen Horizontpunkt setzen.")
    xs = np.array([float(x) for x, _y in points_xy], dtype=np.float64)
    ys = np.array([float(y) for _x, y in points_xy], dtype=np.float64)
    order = np.argsort(xs)
    xs, ys = xs[order], ys[order]
    width = min(int(process_width), int(image_width))
    height = max(1, round(image_height * width / image_width))
    if xs.size == 1:
        py = np.full(width, ys[0], dtype=np.float64)
    else:
        wrap_x = np.concatenate([xs - image_width, xs, xs + image_width])
        wrap_y = np.concatenate([ys, ys, ys])
        src_x = (np.arange(width) + 0.5) * image_width / width
        py = np.interp(src_x, wrap_x, wrap_y)
    py = np.clip(py, 0, image_height - 1)
    scale_x = image_width / width
    points = [
        HorizonPoint(
            az_deg=round(pixel_to_az((x + 0.5) * scale_x, image_width, north_x), 4),
            alt_deg=round(pixel_to_alt(float(py[x]), image_height), 4),
            x=int(round((x + 0.5) * scale_x)),
            y=int(round(float(py[x]))),
        )
        for x in range(width)
    ]
    return HorizonProfile(
        source=str(path),
        image_width=image_width,
        image_height=image_height,
        process_width=width,
        process_height=height,
        north_x=north_x,
        created_at=datetime.now().isoformat(timespec="seconds"),
        points=points,
    )


def save_profile(profile: HorizonProfile, directory: Path) -> dict[str, Path]:
    directory.mkdir(parents=True, exist_ok=True)
    stem = Path(profile.source).stem
    json_path = directory / f"{stem}.horizon.json"
    csv_path = directory / f"{stem}.horizon.csv"
    previous: dict = {}
    if json_path.is_file() and (profile.calibration is None or profile.control_points is None):
        try:
            loaded = json.loads(json_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            loaded = {}
        if isinstance(loaded, dict):
            previous = loaded
    calibration = profile.calibration
    if calibration is None and isinstance(previous.get("calibration"), dict):
        calibration = previous["calibration"]
    control_points = profile.control_points
    if control_points is None and isinstance(previous.get("control_points"), list):
        control_points = previous["control_points"]
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
    if calibration is not None:
        payload["calibration"] = calibration
    if control_points is not None:
        payload["control_points"] = control_points
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


def apply_north(profile: HorizonProfile, north_x: float) -> HorizonProfile:
    profile.north_x = float(north_x)
    width = profile.image_width
    for point in profile.points:
        point.az_deg = round(pixel_to_az(point.x, width, profile.north_x), 4)
    return profile


def _control_points(raw: object) -> list[dict[str, float]] | None:
    if not isinstance(raw, list):
        return None
    points: list[dict[str, float]] = []
    for item in raw:
        if not isinstance(item, dict):
            continue
        try:
            points.append({"x": float(item["x"]), "y": float(item["y"])})
        except (KeyError, TypeError, ValueError):
            continue
    return points


def store_horizon_controls(
    directory: Path,
    image_path: Path,
    points_xy: list[tuple[float, float]],
    *,
    image_width: int,
    image_height: int,
    north_x: float,
    generate: bool,
) -> HorizonProfile:
    """Speichert die Stuetzpunkte. generate baut daraus das dichte Horizontprofil."""
    json_path = directory / f"{image_path.stem}.horizon.json"
    existing = load_profile(json_path) if json_path.is_file() else None
    controls = [{"x": round(float(x), 2), "y": round(float(y), 2)} for x, y in points_xy]
    width = image_width or (existing.image_width if existing else 0)
    height = image_height or (existing.image_height if existing else 0)
    used_north = float(north_x)
    if generate:
        profile = profile_from_manual_points(
            image_path,
            [(item["x"], item["y"]) for item in controls],
            image_width=width,
            image_height=height,
            north_x=used_north,
        )
        if existing is not None and existing.calibration is not None:
            profile.calibration = existing.calibration
    elif existing is not None:
        profile = existing
        profile.north_x = used_north
        if width > 0:
            profile.image_width = width
        if height > 0:
            profile.image_height = height
    else:
        profile = HorizonProfile(
            source=str(image_path),
            image_width=width,
            image_height=height,
            process_width=0,
            process_height=0,
            north_x=used_north,
            created_at=datetime.now().isoformat(timespec="seconds"),
        )
    profile.control_points = controls
    if not profile.source:
        profile.source = str(image_path)
    save_profile(profile, directory)
    return profile


def load_profile(path: Path) -> HorizonProfile:
    raw = json.loads(path.read_text(encoding="utf-8"))
    points = [HorizonPoint(**item) for item in raw.get("points") or []]
    return HorizonProfile(
        source=str(raw.get("source") or ""),
        image_width=int(raw.get("image_width") or 0),
        image_height=int(raw.get("image_height") or 0),
        process_width=int(raw.get("process_width") or 0),
        process_height=int(raw.get("process_height") or 0),
        north_x=float(raw.get("north_x") or 0),
        projection=str(raw.get("projection") or "equirectangular"),
        created_at=str(raw.get("created_at") or ""),
        points=points,
        calibration=raw.get("calibration") if isinstance(raw.get("calibration"), dict) else None,
        control_points=_control_points(raw.get("control_points")),
    )


def ensure_preview(path: Path, dest: Path, preview_width: int = 2000) -> tuple[Path, int, int, int, int]:
    dest.parent.mkdir(parents=True, exist_ok=True)
    image = Image.open(path).convert("RGB")
    src_w, src_h = image.size
    if preview_width < src_w:
        preview_height = max(1, round(src_h * preview_width / src_w))
        image = image.resize((preview_width, preview_height), Image.Resampling.BILINEAR)
    else:
        preview_width, preview_height = src_w, src_h
    # Atomar schreiben — verhindert abgeschnittene .preview.jpg nach Abbruch
    tmp = dest.with_suffix(dest.suffix + ".tmp")
    image.save(tmp, format="JPEG", quality=85)
    tmp.replace(dest)
    return dest, preview_width, preview_height, src_w, src_h


def overlay_svg(
    profile: HorizonProfile | None,
    preview_width: int,
    preview_height: int,
    north_x: float = 0.0,
    source_width: int = 0,
    source_height: int = 0,
    show_grid: bool = False,
    grid_step: int = 10,
    sample_marks: list[tuple[float, float]] | None = None,
    handle_marks: list[tuple[float, float]] | None = None,
    mask_uri: str = "",
    sun_marks: list[tuple[float, float, float]] | None = None,
    reject_marks: list[tuple[float, float]] | None = None,
) -> str:
    parts: list[str] = ['<g pointer-events="none">']
    src_w = source_width or preview_width
    src_h = source_height or preview_height
    if mask_uri and preview_width and preview_height:
        parts.append(
            f'<image href="{mask_uri}" x="0" y="0" width="{preview_width}" '
            f'height="{preview_height}" preserveAspectRatio="none" />'
        )
    if show_grid and preview_width and preview_height:
        parts.extend(
            _sky_grid_svg(preview_width, preview_height, north_x, src_w, grid_step)
        )
    else:
        mid_y = preview_height / 2
        parts.append(
            f'<line x1="0" y1="{mid_y:.1f}" x2="{preview_width}" y2="{mid_y:.1f}" '
            f'stroke="#3b82f6" stroke-width="1" stroke-dasharray="6 6" />'
        )
    if profile is not None and profile.points and src_w and src_h:
        step = max(1, len(profile.points) // 1200)
        sampled = profile.points[::step]
        jump = preview_height * 0.18
        segment: list[str] = []
        prev_y: float | None = None
        for point in sampled:
            x = point.x * preview_width / src_w
            y = point.y * preview_height / src_h
            if prev_y is not None and abs(y - prev_y) > jump and len(segment) >= 2:
                parts.append(
                    f'<polyline points="{" ".join(segment)}" fill="none" stroke="#dc2626" '
                    f'stroke-width="3" stroke-linejoin="round" />'
                )
                segment = []
            segment.append(f"{x:.1f},{y:.1f}")
            prev_y = y
        if len(segment) >= 2:
            parts.append(
                f'<polyline points="{" ".join(segment)}" fill="none" stroke="#dc2626" '
                f'stroke-width="3" stroke-linejoin="round" />'
            )
    if preview_width and src_w:
        nx = max(0.0, min(float(preview_width), north_x * preview_width / src_w))
        parts.append(
            f'<line x1="{nx:.1f}" y1="0" x2="{nx:.1f}" y2="{preview_height}" '
            f'stroke="#22c55e" stroke-width="2" />'
        )
        label_x = min(preview_width - 24, nx + 8)
        parts.append(
            f'<text x="{label_x:.1f}" y="22" fill="#22c55e" font-size="18" font-weight="700">N</text>'
        )
    for index, (mx, my) in enumerate(sample_marks or [], start=1):
        parts.append(
            f'<circle cx="{mx:.1f}" cy="{my:.1f}" r="7" fill="#38bdf8" '
            f'stroke="#0f172a" stroke-width="1.5" />'
        )
        parts.append(
            f'<text x="{mx + 9:.1f}" y="{my - 8:.1f}" fill="#38bdf8" '
            f'font-size="12" font-weight="700">{index}</text>'
        )
    for mx, my in handle_marks or []:
        parts.append(
            f'<circle cx="{mx:.1f}" cy="{my:.1f}" r="6" fill="#facc15" '
            f'stroke="#422006" stroke-width="1.5" />'
        )
    for mx, my, radius in sun_marks or []:
        parts.append(
            f'<circle cx="{mx:.1f}" cy="{my:.1f}" r="{max(8.0, radius):.1f}" '
            f'fill="none" stroke="#f97316" stroke-width="2.5" stroke-dasharray="5 4" />'
        )
        parts.append(
            f'<text x="{mx + radius:.1f}" y="{my - 8:.1f}" fill="#f97316" '
            f'font-size="12" font-weight="700">Sonne</text>'
        )
    for mx, my in reject_marks or []:
        parts.append(
            f'<circle cx="{mx:.1f}" cy="{my:.1f}" r="7" fill="#fb7185" '
            f'stroke="#881337" stroke-width="1.5" />'
        )
    parts.append("</g>")
    return "\n".join(parts)


def _sky_grid_svg(
    preview_width: int,
    preview_height: int,
    north_x: float,
    source_width: int,
    grid_step: int,
) -> list[str]:
    step = 5 if int(grid_step) <= 5 else 10
    parts: list[str] = []
    alt = -90.0 + step
    while alt < 90.0 - 1e-6:
        y = alt_to_pixel(alt, preview_height)
        if 0 <= y <= preview_height:
            is_zero = abs(alt) < 1e-6
            color = "#3b82f6" if is_zero else "#94a3b8"
            width = "1.2" if is_zero else "0.55"
            dash = ' stroke-dasharray="6 6"' if is_zero else ""
            parts.append(
                f'<line x1="0" y1="{y:.1f}" x2="{preview_width}" y2="{y:.1f}" '
                f'stroke="{color}" stroke-width="{width}"{dash} />'
            )
            if abs(alt % 10) < 1e-6:
                ty = max(12.0, y - 3)
                parts.append(
                    f'<text x="6" y="{ty:.1f}" fill="#e2e8f0" font-size="11">{alt:.0f}°</text>'
                )
        alt += step
    az = 0.0
    cardinals = {0: "N", 90: "O", 180: "S", 270: "W"}
    while az < 360.0 - 1e-6:
        x = ((north_x + az / 360.0 * source_width) % source_width) * preview_width / source_width
        az_i = int(round(az)) % 360
        label = cardinals.get(az_i)
        is_north = az_i == 0
        if not is_north:
            width = "1.1" if label else "0.55"
            parts.append(
                f'<line x1="{x:.1f}" y1="0" x2="{x:.1f}" y2="{preview_height}" '
                f'stroke="#94a3b8" stroke-width="{width}" />'
            )
        if label:
            tx = min(preview_width - 14, x + 4)
            parts.append(
                f'<text x="{tx:.1f}" y="{preview_height - 8:.1f}" fill="#e2e8f0" '
                f'font-size="12">{label}</text>'
            )
        elif az_i % 30 == 0:
            tx = min(preview_width - 28, x + 3)
            parts.append(
                f'<text x="{tx:.1f}" y="16" fill="#cbd5e1" font-size="10">{az_i}°</text>'
            )
        az += step
    return parts


def sample_profile(profile: HorizonProfile, step_deg: float = 10.0) -> list[tuple[float, float]]:
    rows: list[tuple[float, float]] = []
    az = 0.0
    while az < 360.0 - 1e-6:
        rows.append((az, round(profile.altitude_at(az), 2)))
        az += step_deg
    return rows


def sky_obstruction(profile: HorizonProfile, step_deg: float = 1.0) -> tuple[float, float]:
    """Verdeckter / freier Anteil der oberen Hemisphaere in Prozent (Raumwinkel).

    dΩ = cos(h) dh dAz. Gesamter Himmel ueber dem geometrischen Horizont: 2π sr.
    Bei konstantem h gilt: verdeckt = sin(max(h, 0)).
    """
    if profile is None or not profile.points:
        return 0.0, 100.0
    weights: list[float] = []
    az = 0.0
    while az < 360.0 - 1e-9:
        height = max(0.0, min(90.0, profile.altitude_at(az)))
        weights.append(float(np.sin(np.deg2rad(height))))
        az += step_deg
    blocked = float(np.mean(np.array(weights, dtype=np.float64)))
    blocked = max(0.0, min(1.0, blocked))
    return blocked * 100.0, (1.0 - blocked) * 100.0

