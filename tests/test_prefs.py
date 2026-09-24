from pathlib import Path

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
    })
    assert saved["star_scale"] == 4.0
    assert saved["mag_limit"] == 0.0
    assert saved["track_hours"] is True
    assert saved["grid"] is True
    assert saved["grid_eq"] is True
    assert saved["grid_ecliptic"] is True
    assert saved["grid_step"] == 10
    assert save_prefs(path, {"grid_step": 5})["grid_step"] == 5
    again = load_prefs(path)
    assert again["star_scale"] == 4.0
    assert again["mag_limit"] == 0.0
    assert again["grid_step"] == 5


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
    assert data["grid_step"] == 10
