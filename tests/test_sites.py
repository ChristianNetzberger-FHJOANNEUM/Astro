from pathlib import Path

from mele.sites import load_photo_site, load_sites, save_photo_site, sites_path


def test_sites_roundtrip_per_photo(tmp_path: Path) -> None:
    path = sites_path(tmp_path)
    save_photo_site(path, "CAM_0942", 48.2082, 16.3738, source="pano", filename="CAM_0942.JPG")
    save_photo_site(path, "CAM_0943", 47.0707, 15.4395, source="exif", filename="CAM_0943.JPG")
    first = load_photo_site(path, "CAM_0942")
    second = load_photo_site(path, "CAM_0943")
    assert first is not None
    assert abs(first.latitude_deg - 48.2082) < 1e-6
    assert first.source == "pano"
    assert second is not None
    assert abs(second.longitude_deg - 15.4395) < 1e-6
    assert load_photo_site(path, "unknown") is None
    assert set(load_sites(path)) == {"CAM_0942", "CAM_0943"}
    text = path.read_text(encoding="utf-8")
    assert "CAM_0942" in text
    assert "48.2082" in text


def test_sites_overwrite_keeps_other_photos(tmp_path: Path) -> None:
    path = tmp_path / "sites.json"
    save_photo_site(path, "A", 1.0, 2.0)
    save_photo_site(path, "B", 3.0, 4.0)
    save_photo_site(path, "A", 9.5, 8.5, source="saved")
    assert load_photo_site(path, "A").latitude_deg == 9.5
    assert load_photo_site(path, "B").longitude_deg == 4.0
