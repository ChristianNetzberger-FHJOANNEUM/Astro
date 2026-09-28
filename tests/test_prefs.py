from pathlib import Path

from mele.catalog import DSO_TYPE_GROUP_KEYS
from mele.prefs import DEFAULTS, load_prefs, prefs_path, save_prefs


def test_prefs_defaults_and_clamp(tmp_path: Path) -> None:
    path = prefs_path(tmp_path)
    assert load_prefs(path) == DEFAULTS
    saved = save_prefs(path, {
        "star_scale": 9.0,
        "mag_limit": -2,
        "track_hours": True,
        "grid": True,
        "grid_step": 7,
        "grid_eq": True,
        "grid_ecliptic": 1,
        "horizon_points": False,
        "show_ngc": True,
        "show_messier": 0,
        "dso_types": ["galaxy", "globular"],
    })
    assert saved["star_scale"] == 4.0
    assert saved["mag_limit"] == 0.0
    assert saved["track_hours"] is True
    assert saved["grid"] is True
    assert saved["grid_eq"] is True
    assert saved["grid_ecliptic"] is True
    assert saved["horizon_points"] is False
    assert saved["grid_step"] == 10
    assert saved["show_ngc"] is True
    assert saved["show_messier"] is False
    assert saved["dso_types"] == ["galaxy", "globular"]
    assert save_prefs(path, {"grid_step": 5})["grid_step"] == 5
    again = load_prefs(path)
    assert again["star_scale"] == 4.0
    assert again["mag_limit"] == 0.0
    assert again["grid_step"] == 5
    assert again["horizon_points"] is False
    assert again["dso_types"] == ["galaxy", "globular"]


def test_prefs_keep_unknown_and_partial(tmp_path: Path) -> None:
    path = tmp_path / "ui-prefs.json"
    path.write_text('{"star_scale": 1.5, "theme": "dark"}\n', encoding="utf-8")
    data = load_prefs(path)
    assert data["star_scale"] == 1.5
    assert data["mag_limit"] == DEFAULTS["mag_limit"]
    assert data["theme"] == "dark"
    assert data["track_hours"] is False
    assert data["grid"] is False
    assert data["grid_eq"] is False
    assert data["grid_ecliptic"] is False
    assert data["horizon_points"] is True
    assert data["grid_step"] == 10
    assert data["show_stars"] is True
    assert data["dso_types"] == list(DSO_TYPE_GROUP_KEYS)


def test_prefs_dso_types_csv_string(tmp_path: Path) -> None:
    path = prefs_path(tmp_path)
    saved = save_prefs(path, {"dso_types": "open,planetary,bogus"})
    assert saved["dso_types"] == ["open", "planetary"]
