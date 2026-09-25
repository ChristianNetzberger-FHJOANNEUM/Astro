"""Himmels-Alpha: Vorschau bearbeiten, auf Vollaufloesung zurueckrechnen."""

from __future__ import annotations

import base64
from io import BytesIO
from pathlib import Path

import numpy as np
from PIL import Image

from mele.horizon import (
    HorizonProfile,
    alt_to_pixel,
    pixel_to_az,
    profile_from_mask,
)

Image.MAX_IMAGE_PIXELS = None

GROUND = 255
SKY = 0


def empty_mask(height: int, width: int, fill: int = GROUND) -> np.ndarray:
    return np.full((height, width), fill, dtype=np.uint8)


def mask_from_profile(profile: HorizonProfile, width: int, height: int) -> np.ndarray:
    mask = np.zeros((height, width), dtype=np.uint8)
    src_w = profile.image_width or width
    for x in range(width):
        az = pixel_to_az(x + 0.5, width, profile.north_x * width / src_w if src_w else 0.0)
        y = int(round(alt_to_pixel(profile.altitude_at(az), height)))
        y = max(0, min(height, y))
        mask[y:, x] = GROUND
    return mask


def paint_disk(mask: np.ndarray, x: float, y: float, radius: float, value: int) -> None:
    height, width = mask.shape
    if radius <= 0 or width <= 0 or height <= 0:
        return
    xi, yi = int(round(x)), int(round(y))
    rad = max(1, int(round(radius)))
    x0, x1 = max(0, xi - rad), min(width, xi + rad + 1)
    y0, y1 = max(0, yi - rad), min(height, yi + rad + 1)
    yy, xx = np.ogrid[y0:y1, x0:x1]
    disk = (xx - x) ** 2 + (yy - y) ** 2 <= radius ** 2
    mask[y0:y1, x0:x1][disk] = value


def resize_mask(mask: np.ndarray, width: int, height: int) -> np.ndarray:
    if mask.shape[1] == width and mask.shape[0] == height:
        return mask
    image = Image.fromarray(mask, mode="L")
    return np.asarray(image.resize((width, height), Image.Resampling.NEAREST), dtype=np.uint8)


def profile_from_alpha(
    path: Path,
    mask: np.ndarray,
    src_w: int,
    src_h: int,
    north_x: float,
) -> HorizonProfile:
    sky = mask == SKY
    return profile_from_mask(path, sky, src_w, src_h, north_x, median_window=5)


def save_mask_png(mask: np.ndarray, dest: Path) -> Path:
    dest.parent.mkdir(parents=True, exist_ok=True)
    Image.fromarray(mask, mode="L").save(dest)
    return dest


def load_mask_png(path: Path) -> np.ndarray | None:
    if not path.is_file():
        return None
    return np.asarray(Image.open(path).convert("L"), dtype=np.uint8)


def compose_rgba(rgb: np.ndarray, mask: np.ndarray) -> Image.Image:
    if mask.shape[:2] != rgb.shape[:2]:
        mask = resize_mask(mask, rgb.shape[1], rgb.shape[0])
    rgba = np.dstack([rgb, mask])
    return Image.fromarray(rgba, mode="RGBA")


def export_transparent(
    photo: Path,
    mask: np.ndarray,
    dest: Path,
    *,
    max_width: int | None = None,
) -> Path:
    image = Image.open(photo).convert("RGB")
    if max_width and image.size[0] > max_width:
        height = max(1, round(image.size[1] * max_width / image.size[0]))
        image = image.resize((max_width, height), Image.Resampling.BILINEAR)
    rgb = np.asarray(image, dtype=np.uint8)
    fitted = resize_mask(mask, rgb.shape[1], rgb.shape[0])
    dest.parent.mkdir(parents=True, exist_ok=True)
    compose_rgba(rgb, fitted).save(dest)
    return dest


def export_profile_views(
    photo: Path,
    profile: HorizonProfile,
    directory: Path,
    *,
    preview_width: int,
) -> dict[str, Path]:
    """Ersetzt Maske und transparente PNGs durch die Linie aus dem Profil."""
    src_w = profile.image_width or preview_width
    src_h = profile.image_height or max(1, preview_width // 2)
    prev_w = max(1, min(int(preview_width), int(src_w)))
    prev_h = max(1, round(src_h * prev_w / src_w))
    mask = mask_from_profile(profile, prev_w, prev_h)
    stem = photo.stem
    directory.mkdir(parents=True, exist_ok=True)
    mask_path = directory / f"{stem}.horizon.mask.png"
    png = directory / f"{stem}.horizon.png"
    full = directory / f"{stem}.horizon.full.png"
    save_mask_png(mask, mask_path)
    export_transparent(photo, mask, png, max_width=preview_width)
    export_transparent(photo, mask, full, max_width=None)
    write_stellarium_landscape(directory / f"{stem}.landscape", stem, png)
    return {"mask": mask_path, "png": png, "full": full}


def write_stellarium_landscape(
    dest_dir: Path,
    name: str,
    rgba_png: Path,
) -> Path:
    dest_dir.mkdir(parents=True, exist_ok=True)
    target = dest_dir / f"{name}.png"
    if Path(rgba_png).resolve() != target.resolve():
        Image.open(rgba_png).save(target)
    ini = dest_dir / "landscape.ini"
    ini.write_text(
        "\n".join(
            [
                "[landscape]",
                f"name = {name}",
                "type = spherical",
                f"maptex = {target.name}",
                "author = MeLE Astro-Computer",
                "description = Gartenhorizont, Himmel transparent",
                "",
            ]
        ),
        encoding="utf-8",
    )
    return ini


def mask_tint_data_uri(mask: np.ndarray, height: int | None = None) -> str:
    view = mask if height is None else mask[:height]
    rgba = np.zeros((view.shape[0], view.shape[1], 4), dtype=np.uint8)
    rgba[view == SKY] = (56, 189, 248, 72)
    buffer = BytesIO()
    Image.fromarray(rgba, mode="RGBA").save(buffer, format="PNG")
    encoded = base64.b64encode(buffer.getvalue()).decode("ascii")
    return f"data:image/png;base64,{encoded}"


def crop_sky_preview(full_preview: Path, dest: Path) -> tuple[Path, int, int]:
    image = Image.open(full_preview).convert("RGB")
    width, height = image.size
    sky_h = max(1, height // 2)
    image.crop((0, 0, width, sky_h)).save(dest, quality=85)
    return dest, width, sky_h
