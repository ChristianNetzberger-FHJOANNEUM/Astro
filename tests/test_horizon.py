from __future__ import annotations

from pathlib import Path

import numpy as np
from PIL import Image

from mele.horizon import (
    detect_horizon,
    detect_horizon_rows,
    pixel_to_alt,
    pixel_to_az,
    sky_mask,
)


def test_equirectangular_projection() -> None:
    assert pixel_to_alt(0, 180) == 90.0
    assert pixel_to_alt(90, 180) == 0.0
    assert pixel_to_alt(180, 180) == -90.0
    assert pixel_to_az(0, 360) == 0.0
    assert pixel_to_az(90, 360) == 90.0
    assert pixel_to_az(0, 360, north_x=90) == 270.0


def test_sky_mask_blue_and_sun() -> None:
    rgb = np.zeros((4, 3, 3), dtype=np.uint8)
    rgb[0, 0] = (40, 90, 200)
    rgb[0, 1] = (255, 255, 240)
    rgb[1, 0] = (30, 140, 40)
    rgb[1, 1] = (200, 180, 150)
    mask = sky_mask(rgb)
    assert mask[0, 0]
    assert mask[0, 1]
    assert not mask[1, 0]
    assert not mask[1, 1]


def test_detect_horizon_on_synthetic_panorama(tmp_path: Path) -> None:
    width, height = 360, 180
    image = Image.new("RGB", (width, height), (40, 90, 200))
    pixels = image.load()
    house_y = 40
    ground_y = 70
    for y in range(ground_y, height):
        for x in range(width):
            pixels[x, y] = (40, 130, 40)
    for y in range(house_y, height):
        for x in range(80, 120):
            pixels[x, y] = (210, 190, 160)
    path = tmp_path / "pano.jpg"
    image.save(path)

    profile = detect_horizon(path, process_width=width, median_window=1)
    assert len(profile.points) == width
    open_sky = [p.alt_deg for p in profile.points if not (80 <= (p.x % width) < 120)]
    house = [p.alt_deg for p in profile.points if 80 <= (p.x % width) < 120]
    expected_open = pixel_to_alt(ground_y + 0.5, height)
    expected_house = pixel_to_alt(house_y + 0.5, height)
    assert abs(float(np.median(open_sky)) - expected_open) < 2.0
    assert abs(float(np.median(house)) - expected_house) < 2.0
    assert profile.is_visible(0.0, expected_open + 5)
    assert not profile.is_visible(100.0, expected_house - 5)


def test_column_transition_finds_first_obstacle() -> None:
    mask = np.ones((10, 1), dtype=bool)
    mask[4:, 0] = False
    rows = detect_horizon_rows(mask)
    assert int(rows[0]) == 4
