from datetime import datetime, timezone
from math import isclose
from zoneinfo import ZoneInfo

import pytest

from mele.horizon import load_profile
from mele.shadow_calibration import (
    ShadowCalibrationError,
    calibrate_shadow,
    corrected_north_offset,
    geographic_azimuth,
    measured_shadow_view_lon,
    normalize_deg,
    normalize_signed,
    panorama_azimuth_offset,
    store_calibration,
    sun_horizontal,
    true_shadow_azimuth,
    viewer_look_direction,
    viewer_screen_to_world,
    viewer_world_to_ndc,
)


def test_normalize_deg_wraps() -> None:
    assert normalize_deg(0) == 0
    assert normalize_deg(360) == 0
    assert normalize_deg(-10) == 350
    assert normalize_deg(370) == 10


def test_normalize_signed_range() -> None:
    assert normalize_signed(0) == 0
    assert normalize_signed(179) == 179
    assert normalize_signed(180) == -180
    assert normalize_signed(-180) == -180
    assert normalize_signed(181) == -179
    assert isclose(normalize_signed(-356), 4)


def test_shadow_is_opposite_the_sun() -> None:
    assert true_shadow_azimuth(200) == 20
    assert true_shadow_azimuth(0) == 180
    assert true_shadow_azimuth(270) == 90


def test_offset_examples() -> None:
    assert panorama_azimuth_offset(15, 20) == 5
    assert isclose(panorama_azimuth_offset(358, 2), 4)


def test_ground_shadow_points_north_then_east() -> None:
    view_lon, separation = measured_shadow_view_lon((0.1, -1.0, 0.0), (1.0, -0.3, 0.0))
    assert view_lon == pytest.approx(0.0, abs=1e-6)
    assert separation > 1.2
    view_lon, _sep = measured_shadow_view_lon((0.0, -1.0, 0.1), (0.0, -0.3, 1.0))
    assert view_lon == pytest.approx(90.0, abs=1e-6)


def test_rays_above_horizon_are_rejected() -> None:
    with pytest.raises(ShadowCalibrationError):
        measured_shadow_view_lon((0.2, 0.1, 0.0), (0.4, -0.8, 0.0))


def test_offset_lands_measured_shadow_on_true_shadow() -> None:
    measured = 358.0
    true_shadow = 2.0
    north = 40.0
    offset = panorama_azimuth_offset(measured, true_shadow)
    view_lon = normalize_deg(measured + north)
    corrected = geographic_azimuth(view_lon, corrected_north_offset(north, offset))
    assert corrected == pytest.approx(true_shadow)


def test_vienna_local_time_is_not_treated_as_utc() -> None:
    local = datetime(2026, 9, 25, 13, 10, tzinfo=ZoneInfo("Europe/Vienna"))
    as_utc = datetime(2026, 9, 25, 13, 10, tzinfo=timezone.utc)
    local_az, _alt = sun_horizontal(local, 48.2, 16.37)
    utc_az, _utc_alt = sun_horizontal(as_utc, 48.2, 16.37)
    assert local_az != pytest.approx(utc_az, abs=1.0)


def test_calibrate_uses_existing_sun_and_reports_offset() -> None:
    when = datetime(2026, 9, 25, 11, 10, tzinfo=timezone.utc)
    sun_az, sun_alt = sun_horizontal(when, 48.2, 16.37)
    result = calibrate_shadow(
        ray1=(0.1, -1.0, 0.0),
        ray2=(1.0, -0.3, 0.0),
        when=when,
        latitude_deg=48.2,
        longitude_deg=16.37,
        north_offset_deg=0.0,
    )
    assert result.sun_azimuth_deg == pytest.approx(sun_az)
    assert result.sun_altitude_deg == pytest.approx(sun_alt)
    assert result.shadow_azimuth_true_deg == pytest.approx(true_shadow_azimuth(sun_az))
    assert result.shadow_azimuth_measured_deg == pytest.approx(0.0, abs=1e-6)
    assert result.quality == "gut"
    view_lon, _sep = measured_shadow_view_lon((0.1, -1.0, 0.0), (1.0, -0.3, 0.0))
    corrected = geographic_azimuth(view_lon, result.north_offset_deg)
    assert corrected == pytest.approx(result.shadow_azimuth_true_deg)


def test_viewer_screen_world_roundtrip() -> None:
    lon, lat, fov, aspect = 25.0, -12.0, 75.0, 16.0 / 9.0
    center = viewer_screen_to_world(0.0, 0.0, lon_deg=lon, lat_deg=lat, fov_deg=fov, aspect=aspect)
    look = viewer_look_direction(lon, lat)
    assert center == pytest.approx(look, abs=1e-9)
    ndc = (0.35, -0.2)
    direction = viewer_screen_to_world(*ndc, lon_deg=lon, lat_deg=lat, fov_deg=fov, aspect=aspect)
    back = viewer_world_to_ndc(direction, lon_deg=lon, lat_deg=lat, fov_deg=fov, aspect=aspect)
    assert back == pytest.approx(ndc, abs=1e-9)


def test_store_calibration_updates_north_without_dropping_points(tmp_path) -> None:
    image = tmp_path / "pano.jpg"
    image.write_bytes(b"")
    from mele.horizon import HorizonPoint, HorizonProfile, save_profile

    profile = HorizonProfile(
        source=str(image),
        image_width=3600,
        image_height=1800,
        process_width=360,
        process_height=180,
        north_x=0,
        points=[HorizonPoint(az_deg=0, alt_deg=0, x=0, y=900)],
    )
    save_profile(profile, tmp_path)
    record = {"calibration_method": "solar_shadow", "panorama_azimuth_offset_deg": 5}
    store_calibration(
        tmp_path,
        image,
        image_width=3600,
        image_height=1800,
        north_x=50,
        record=record,
    )
    loaded = load_profile(tmp_path / "pano.horizon.json")
    assert loaded.north_x == 50
    assert loaded.calibration["calibration_method"] == "solar_shadow"
    assert loaded.points[0].x == 0
    assert loaded.points[0].az_deg == pytest.approx((360.0 * (0 - 50) / 3600) % 360.0)
