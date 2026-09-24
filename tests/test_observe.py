from pathlib import Path

from PIL import Image

from mele.config import MeleSettings, load_mele_settings, save_site
from mele.observe import (
    dms_to_deg,
    gps_is_usable,
    iter_geotagged_jpegs,
    photo_datetime,
    resolve_observer,
)


def test_dms_and_void_gps() -> None:
    assert abs(dms_to_deg((48, 12, 0), "N") - 48.2) < 1e-6
    assert abs(dms_to_deg((16, 24, 0), "E") - 16.4) < 1e-6
    assert dms_to_deg((10, 0, 0), "W") == -10.0
    assert not gps_is_usable(0.0, 0.0, "V")
    assert not gps_is_usable(0.0, 0.0, "A")
    assert gps_is_usable(48.2, 16.4, "A")


def test_photo_datetime_from_exif(tmp_path: Path) -> None:
    path = tmp_path / "shot.jpg"
    image = Image.new("RGB", (8, 8), "navy")
    exif = image.getexif()
    exif[306] = "2026:09:23 15:14:19"
    image.save(path, format="JPEG", exif=exif)
    when = photo_datetime(path, "Europe/Vienna")
    assert when is not None
    assert when.tzinfo is not None
    local = when.astimezone()
    assert when.year == 2026
    assert when.month == 9
    assert when.day == 23
    assert local.hour in {15, 13, 14, 16, 17}


def test_resolve_observer_falls_back_to_config(tmp_path: Path) -> None:
    settings = MeleSettings(latitude_deg=48.2, longitude_deg=16.4, timezone="Europe/Vienna")
    observer = resolve_observer(None, settings)
    assert observer.latitude_deg == 48.2
    assert observer.site_src == "config"
    path = tmp_path / "empty.jpg"
    Image.new("RGB", (8, 8), "black").save(path, format="JPEG")
    observer = resolve_observer(path, settings)
    assert observer.site_src == "config"
    assert observer.photo_when is None


def test_save_site_keeps_yaml_comments(tmp_path: Path) -> None:
    cfg = tmp_path / "mele.yaml"
    cfg.write_text(
        "# Garten\nlatitude_deg:\nlongitude_deg:\ntimezone: Europe/Vienna\n",
        encoding="utf-8",
    )
    save_site(48.2082, 16.3738, cfg)
    text = cfg.read_text(encoding="utf-8")
    assert "# Garten" in text
    from mele.config import _load_yaml
    raw = _load_yaml(cfg)
    assert abs(float(raw["latitude_deg"]) - 48.2082) < 1e-6
    assert abs(float(raw["longitude_deg"]) - 16.3738) < 1e-6


def test_gps_dir_defaults_under_media(tmp_path: Path) -> None:
    cfg = tmp_path / "mele.yaml"
    cfg.write_text("media_dir: media\n", encoding="utf-8")
    from mele.config import REPO_ROOT

    settings = load_mele_settings(cfg)
    assert settings.gps_dir == REPO_ROOT / "media" / "GPS-locations"


def test_iter_geotagged_skips_huge_and_uses_gps(tmp_path: Path, monkeypatch) -> None:
    phone = tmp_path / "phone.jpg"
    huge = tmp_path / "CAM_pano.jpg"
    Image.new("RGB", (8, 8), "green").save(phone, format="JPEG")
    huge.write_bytes(b"x" * (21 * 1024 * 1024))

    def fake_gps(path: Path):
        if path.name == "phone.jpg":
            return 48.21, 16.37
        return None

    monkeypatch.setattr("mele.observe.gps_from_jpeg", fake_gps)
    found = iter_geotagged_jpegs(tmp_path)
    assert len(found) == 1
    assert found[0][0].name == "phone.jpg"
    assert abs(found[0][1] - 48.21) < 1e-6
    from mele.observe import list_location_jpegs
    listed = list_location_jpegs(tmp_path)
    assert any(item[0].name == "phone.jpg" and item[1] is not None for item in listed)
    bare = tmp_path / "no-gps.jpg"
    Image.new("RGB", (8, 8), "gray").save(bare, format="JPEG")
    listed = list_location_jpegs(tmp_path)
    empty = next(item for item in listed if item[0].name == "no-gps.jpg")
    assert empty[1] is None
