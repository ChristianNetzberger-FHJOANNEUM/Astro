from __future__ import annotations

from pathlib import Path

import numpy as np
from PIL import Image

from mele.horizon import (
    HorizonPoint,
    HorizonProfile,
    SunExclude,
    apply_north,
    apply_sun_excludes,
    detect_horizon,
    detect_horizon_from_samples,
    detect_horizon_rows,
    find_sun_excludes,
    keep_sky_connected_to_top,
    load_profile,
    overlay_svg,
    pixel_to_alt,
    pixel_to_az,
    profile_from_manual_points,
    rgb_to_hsv,
    save_profile,
    sky_mask,
    sky_mask_from_samples,
    sky_obstruction,
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


def test_sky_mask_rejects_sunlit_grass() -> None:
    rgb = np.zeros((1, 3, 3), dtype=np.uint8)
    rgb[0, 0] = (180, 210, 90)
    rgb[0, 1] = (210, 230, 110)
    rgb[0, 2] = (230, 240, 140)
    mask = sky_mask(rgb)
    assert not mask.any()


def test_overlay_svg_grid_has_const_alt_and_az() -> None:
    svg = overlay_svg(
        None,
        preview_width=360,
        preview_height=180,
        north_x=0,
        source_width=360,
        source_height=180,
        show_grid=True,
        grid_step=10,
    )
    assert svg.count("<line") >= 20
    assert "N</text>" in svg
    assert "O</text>" in svg
    assert "0°" in svg


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


def test_apply_north_and_roundtrip(tmp_path: Path) -> None:
    width, height = 360, 180
    image = Image.new('RGB', (width, height), (40, 90, 200))
    for y in range(90, height):
        for x in range(width):
            image.putpixel((x, y), (40, 130, 40))
    path = tmp_path / 'pano.jpg'
    image.save(path)
    profile = detect_horizon(path, north_x=0, process_width=width, median_window=1)
    apply_north(profile, 90)
    assert profile.north_x == 90
    written = save_profile(profile, tmp_path)
    loaded = load_profile(written['json'])
    assert loaded.north_x == 90
    assert abs(loaded.altitude_at(90) - profile.altitude_at(90)) < 0.2


def test_sun_island_is_ignored() -> None:
    mask = np.ones((20, 3), dtype=bool)
    mask[2:5, 1] = False
    mask[14:, :] = False
    rows = detect_horizon_rows(mask)
    assert int(rows[1]) == 14
    assert int(rows[0]) == 14


def test_false_sky_near_nadir_does_not_pull_horizon() -> None:
    mask = np.ones((20, 1), dtype=bool)
    mask[8:, 0] = False
    mask[18, 0] = True
    rows = detect_horizon_rows(mask)
    assert int(rows[0]) == 8


def test_rgb_to_hsv_primaries() -> None:
    rgb = np.array([[[255, 0, 0], [0, 255, 0], [0, 0, 255]]], dtype=np.uint8)
    hue, sat, val = rgb_to_hsv(rgb)
    assert abs(float(hue[0, 0]) - 0.0) < 1.0
    assert abs(float(hue[0, 1]) - 120.0) < 1.0
    assert abs(float(hue[0, 2]) - 240.0) < 1.0
    assert np.all(sat > 0.99)
    assert np.all(val > 0.99)


def test_picker_does_not_treat_white_house_as_sky() -> None:
    rgb = np.zeros((1, 2, 3), dtype=np.uint8)
    rgb[0, 0] = (50, 110, 210)
    rgb[0, 1] = (240, 232, 220)
    mask = sky_mask_from_samples(rgb, [(50, 110, 210)], include_sun=False)
    assert mask[0, 0]
    assert not mask[0, 1]


def test_keep_sky_connected_to_top_drops_house_wall() -> None:
    sky = np.zeros((8, 6), dtype=bool)
    sky[:3, :] = True
    sky[5:, 1:3] = True
    kept = keep_sky_connected_to_top(sky)
    assert kept[0, 0]
    assert kept[2, 2]
    assert not kept[5, 1]


def test_sun_exclude_is_not_an_obstacle() -> None:
    mask = np.ones((40, 20), dtype=bool)
    mask[5:20, 8:12] = False
    mask[28:, :] = False
    rows = detect_horizon_rows(mask)
    assert int(rows[10]) == 5
    filled = apply_sun_excludes(
        mask, [SunExclude(source_x=10, source_y=12, source_radius=9)], 20, 40
    )
    rows2 = detect_horizon_rows(filled)
    assert int(rows2[10]) == 28


def test_find_sun_in_upper_white_disk() -> None:
    rgb = np.zeros((40, 40, 3), dtype=np.uint8)
    rgb[:, :] = (40, 90, 200)
    rgb[6:12, 18:24] = (255, 255, 250)
    found = find_sun_excludes(rgb, 40, 40)
    assert found
    assert 16 < found[0].source_x < 26
    assert found[0].source_y < 20


def test_sky_mask_from_samples_keeps_blue_rejects_grass() -> None:
    rgb = np.zeros((2, 2, 3), dtype=np.uint8)
    rgb[0, 0] = (50, 110, 210)
    rgb[0, 1] = (170, 210, 250)
    rgb[1, 0] = (40, 160, 50)
    rgb[1, 1] = (210, 190, 160)
    mask = sky_mask_from_samples(
        rgb, [(50, 110, 210), (170, 210, 250)], hue_pad=18, sat_pad=0.25, val_pad=0.25, include_sun=False
    )
    assert mask[0, 0]
    assert mask[0, 1]
    assert not mask[1, 0]
    assert not mask[1, 1]


def test_picker_horizon_on_synthetic_panorama(tmp_path: Path) -> None:
    width, height = 360, 180
    image = Image.new("RGB", (width, height), (40, 90, 200))
    for y in range(70, height):
        for x in range(width):
            image.putpixel((x, y), (40, 130, 40))
    path = tmp_path / "pano.jpg"
    image.save(path)
    profile = detect_horizon_from_samples(
        path, [(40, 90, 200)], north_x=0, process_width=width, median_window=1
    )
    expected = pixel_to_alt(70.5, height)
    assert abs(float(np.median([p.alt_deg for p in profile.points])) - expected) < 2.0


def test_manual_points_interpolate_and_wrap() -> None:
    profile = profile_from_manual_points(
        "manual",
        [(10, 40), (200, 80), (350, 40)],
        image_width=360,
        image_height=180,
        north_x=0,
        process_width=360,
    )
    assert len(profile.points) == 360
    mid = next(p for p in profile.points if 198 <= p.x <= 202)
    assert abs(mid.y - 80) < 3
    left = next(p for p in profile.points if p.x <= 12)
    assert abs(left.y - 40) < 3


def test_overlay_marks_samples_and_handles() -> None:
    svg = overlay_svg(
        None,
        200,
        100,
        sample_marks=[(20.0, 30.0)],
        handle_marks=[(80.0, 50.0)],
    )
    assert "circle" in svg
    assert "20.0" in svg
    assert "80.0" in svg


def _flat_profile(alt_deg: float) -> HorizonProfile:
    points = [
        HorizonPoint(az_deg=float(az), alt_deg=alt_deg, x=az, y=90)
        for az in range(0, 360, 10)
    ]
    return HorizonProfile(
        source="flat",
        image_width=360,
        image_height=180,
        process_width=36,
        process_height=18,
        north_x=0,
        points=points,
    )


def test_sky_obstruction_solid_angle() -> None:
    blocked, free = sky_obstruction(_flat_profile(0.0))
    assert blocked < 0.5
    assert free > 99.5
    blocked, free = sky_obstruction(_flat_profile(30.0))
    assert abs(blocked - 50.0) < 0.6
    assert abs(free - 50.0) < 0.6
    blocked, _free = sky_obstruction(_flat_profile(90.0))
    assert blocked > 99.5
