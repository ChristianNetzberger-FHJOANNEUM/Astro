from __future__ import annotations

from pathlib import Path

import numpy as np
from PIL import Image

from mele.horizon import SkySample, detect_horizon_from_samples, profile_belongs_to
from mele.mask import (
    GROUND,
    SKY,
    compose_rgba,
    crop_sky_preview,
    empty_mask,
    export_transparent,
    paint_disk,
    save_mask_png,
    write_stellarium_landscape,
)


def test_profile_belongs_to_uses_stem() -> None:
    from mele.horizon import HorizonProfile

    profile = HorizonProfile(
        source="C:/media/CAM_A.JPG",
        image_width=10,
        image_height=5,
        process_width=10,
        process_height=5,
        north_x=0,
    )
    assert profile_belongs_to(profile, Path("CAM_A.JPG"))
    assert not profile_belongs_to(profile, Path("CAM_B.JPG"))
    assert not profile_belongs_to(None, Path("CAM_A.JPG"))


def test_paint_disk_sets_sky_pixels() -> None:
    mask = empty_mask(40, 40, GROUND)
    paint_disk(mask, 20, 20, 5, SKY)
    assert mask[20, 20] == SKY
    assert mask[0, 0] == GROUND


def test_export_transparent_has_alpha(tmp_path: Path) -> None:
    photo = tmp_path / "pano.jpg"
    Image.new("RGB", (80, 40), (40, 90, 200)).save(photo)
    mask = empty_mask(20, 40, GROUND)
    mask[:8] = SKY
    dest = tmp_path / "out.png"
    export_transparent(photo, mask, dest, max_width=80)
    image = Image.open(dest)
    assert image.mode == "RGBA"
    alpha = np.asarray(image)[:, :, 3]
    assert int(alpha[0, 0]) == SKY
    assert int(alpha[-1, 0]) == GROUND


def test_crop_sky_preview_is_upper_half(tmp_path: Path) -> None:
    full = tmp_path / "full.jpg"
    Image.new("RGB", (100, 80), (10, 20, 30)).save(full)
    dest = tmp_path / "sky.jpg"
    _, width, height = crop_sky_preview(full, dest)
    assert width == 100
    assert height == 40
    assert Image.open(dest).size == (100, 40)


def test_stellarium_landscape_writes_ini(tmp_path: Path) -> None:
    png = tmp_path / "map.png"
    Image.new("RGBA", (16, 8), (0, 0, 0, 255)).save(png)
    dest = tmp_path / "land"
    ini = write_stellarium_landscape(dest, "garden", png)
    text = ini.read_text(encoding="utf-8")
    assert "type = spherical" in text
    assert (dest / "garden.png").is_file()


def test_picker_resamples_from_source_coords(tmp_path: Path) -> None:
    width, height = 120, 60
    image = Image.new("RGB", (width, height), (40, 90, 200))
    for y in range(30, height):
        for x in range(width):
            image.putpixel((x, y), (40, 130, 40))
    path = tmp_path / "CAM_PICK.JPG"
    image.save(path)
    sample = SkySample(preview_x=10, preview_y=5, r=0, g=0, b=0, source_x=10, source_y=5)
    profile = detect_horizon_from_samples(
        path, [sample], process_width=width, median_window=1, hue_pad=20, sat_pad=0.3, val_pad=0.3
    )
    assert profile_belongs_to(profile, path)
    assert abs(float(np.median([p.alt_deg for p in profile.points])) - 0.0) < 8.0


def test_save_mask_roundtrip(tmp_path: Path) -> None:
    mask = empty_mask(10, 12, GROUND)
    mask[2, 3] = SKY
    dest = tmp_path / "m.png"
    save_mask_png(mask, dest)
    loaded = np.asarray(Image.open(dest).convert("L"))
    assert loaded[2, 3] == SKY
    rgb = np.zeros((10, 12, 3), dtype=np.uint8)
    rgba = np.asarray(compose_rgba(rgb, mask))
    assert rgba[2, 3, 3] == SKY
