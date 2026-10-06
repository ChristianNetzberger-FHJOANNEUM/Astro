from datetime import datetime, timezone
from pathlib import Path

from mele.favorites import (
    add_favorite,
    favorite_markers,
    is_favorite,
    load_favorites,
    remove_favorite,
    save_favorites,
)


def test_favorites_add_remove_roundtrip(tmp_path: Path) -> None:
    horizon = tmp_path / "horizon"
    horizon.mkdir()
    empty = load_favorites(horizon)
    assert empty["objects"] == []

    added = add_favorite(
        horizon,
        {
            "key": "NGC6960",
            "name": "NGC6960 Veil Nebula",
            "kind": "ngc",
            "type": "SNR",
            "ra": 313.0,
            "dec": 30.7,
            "mag": 7.0,
        },
    )
    assert added["ok"] is True
    assert len(added["objects"]) == 1
    assert added["objects"][0]["key"] == "NGC6960"
    assert is_favorite(horizon, "NGC6960")

    # Upsert behält Key, aktualisiert Name
    again = add_favorite(
        horizon,
        {"key": "NGC6960", "name": "Veil West", "kind": "ngc", "ra": 313.0, "dec": 30.7},
    )
    assert len(again["objects"]) == 1
    assert again["objects"][0]["name"] == "Veil West"

    add_favorite(horizon, {"key": "M31", "name": "Andromeda", "kind": "messier", "ra": 10.0, "dec": 41.0})
    data = load_favorites(horizon)
    assert {o["key"] for o in data["objects"]} == {"M31", "NGC6960"}

    removed = remove_favorite(horizon, "NGC6960")
    assert removed["changed"] is True
    assert not is_favorite(horizon, "NGC6960")
    assert is_favorite(horizon, "M31")


def test_favorite_markers_az_alt(tmp_path: Path) -> None:
    horizon = tmp_path / "horizon"
    horizon.mkdir()
    save_favorites(
        horizon,
        [
            {
                "key": "HIP97649",
                "name": "Altair",
                "kind": "star",
                "hip": 97649,
                "ra": 19.84639 * 15.0,
                "dec": 8.868322,
            }
        ],
    )
    when = datetime(2026, 9, 23, 22, 0, tzinfo=timezone.utc)
    payload = favorite_markers(
        horizon,
        latitude_deg=48.2,
        longitude_deg=16.4,
        when=when,
    )
    assert payload["count"] == 1
    marker = payload["markers"][0]
    assert marker["key"] == "HIP97649"
    assert "az" in marker and "alt" in marker
    assert marker["favorite"] is True


def test_favorites_rejects_empty_key(tmp_path: Path) -> None:
    horizon = tmp_path / "horizon"
    horizon.mkdir()
    try:
        add_favorite(horizon, {"name": "x"})
        assert False, "expected ValueError"
    except ValueError:
        pass
