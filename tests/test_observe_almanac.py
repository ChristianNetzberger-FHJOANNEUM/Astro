"""Almanach / Sichtbarkeits-Kennzahlen."""

from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path

from mele.catalog import object_track, visibility_summary
from mele.observe_almanac import (
    load_almanac_prefs,
    load_tonight,
    save_almanac_prefs,
    save_tonight,
    set_active_list,
    upsert_list,
)

VEGA_RA = 18.61564 * 15.0
VEGA_DEC = 38.783692


def test_visibility_summary_separates_night() -> None:
    when = datetime(2026, 9, 23, 18, 0, tzinfo=timezone.utc)
    track = object_track(
        ra_deg=VEGA_RA,
        dec_deg=VEGA_DEC,
        latitude_deg=48.2,
        longitude_deg=16.4,
        when=when,
        step_min=30,
    )
    assert "summary" in track
    summary = track["summary"]
    assert summary["observable_min"] <= summary["above_horizon_min"] + 1e-6
    assert summary["observable_h"] == round(summary["observable_min"] / 60.0, 2)
    # Vega im Herbst: nachts ueber Horizont
    assert summary["observable_min"] > 0
    assert all(slot["light"] == "night" for slot in summary["observable_windows"])


def test_visibility_summary_helper_matches_track() -> None:
    track = {
        "windows": [
            {
                "start": "2026-09-23T19:00:00+00:00",
                "end": "2026-09-23T21:00:00+00:00",
                "max_alt": 40.0,
                "light": "night",
            },
            {
                "start": "2026-09-23T12:00:00+00:00",
                "end": "2026-09-23T13:00:00+00:00",
                "max_alt": 50.0,
                "light": "day",
            },
        ],
        "twilight_min": 60,
    }
    summary = visibility_summary(track)
    assert summary["observable_min"] == 120.0
    assert summary["above_horizon_min"] == 180.0
    assert summary["observable_max_alt"] == 40.0
    assert summary["above_max_alt"] == 50.0


def test_tonight_roundtrip(tmp_path: Path) -> None:
    saved = save_tonight(
        tmp_path,
        [{"key": "M31", "name": "Andromeda", "kind": "messier", "mag": 3.4, "ra": 10.0, "dec": 41.0}],
        stem="pano1",
        latitude_deg=48.2,
        longitude_deg=14.3,
    )
    assert Path(saved["path"]).is_file()
    loaded = load_tonight(tmp_path, "pano1")
    assert len(loaded["objects"]) == 1
    assert loaded["objects"][0]["key"] == "M31"
    assert loaded["list_id"] == "default"


def test_named_lists_and_prefs(tmp_path: Path) -> None:
    upsert_list(tmp_path, list_id="apo", label="APO", make_active=True)
    save_tonight(
        tmp_path,
        [{"key": "M42", "name": "Orion", "kind": "messier", "mag": 4.0, "ra": 83.0, "dec": -5.0}],
        list_id="apo",
        label="APO",
    )
    upsert_list(tmp_path, list_id="newton-10", label='Newton 10"', make_active=False)
    save_tonight(
        tmp_path,
        [{"key": "M31", "name": "Andromeda", "kind": "messier", "mag": 3.4, "ra": 10.0, "dec": 41.0}],
        list_id="newton-10",
        label='Newton 10"',
    )
    apo = load_tonight(tmp_path, list_id="apo")
    newton = load_tonight(tmp_path, list_id="newton-10")
    assert apo["objects"][0]["key"] == "M42"
    assert newton["objects"][0]["key"] == "M31"
    set_active_list(tmp_path, "newton-10")
    active = load_tonight(tmp_path)
    assert active["list_id"] == "newton-10"
    prefs = save_almanac_prefs(
        tmp_path,
        {"sort_mode": "mag", "only_selected": True, "active_list": "newton-10"},
    )
    assert prefs["sort_mode"] == "mag"
    assert prefs["only_selected"] is True
    loaded_prefs = load_almanac_prefs(tmp_path)
    assert loaded_prefs["active_list"] == "newton-10"


def test_legacy_tonight_migration(tmp_path: Path) -> None:
    legacy = tmp_path / "pano.tonight.json"
    legacy.write_text(
        '{"objects":[{"key":"M13","name":"Herkules","kind":"messier","mag":5.8,"ra":250.0,"dec":36.0}]}',
        encoding="utf-8",
    )
    loaded = load_tonight(tmp_path)
    assert loaded["objects"][0]["key"] == "M13"
    assert (tmp_path / "observe-lists" / "default.json").is_file()


def test_tonight_markers_az_alt(tmp_path: Path) -> None:
    save_tonight(
        tmp_path,
        [
            {
                "key": "Vega",
                "name": "Vega",
                "kind": "star",
                "mag": 0.0,
                "ra": VEGA_RA,
                "dec": VEGA_DEC,
            }
        ],
        stem="test",
    )
    from mele.observe_almanac import tonight_markers

    when = datetime(2026, 9, 23, 21, 0, tzinfo=timezone.utc)
    data = tonight_markers(
        tmp_path,
        stem="test",
        latitude_deg=48.2,
        longitude_deg=16.4,
        when=when,
    )
    assert data["count"] == 1
    assert data["markers"][0]["name"] == "Vega"
    assert "az" in data["markers"][0]
    assert "alt" in data["markers"][0]


def test_observing_night_keeps_evening_morning_together() -> None:
    """Abend und Morgen einer Nacht als ein Fenster (nicht an Mitternacht getrennt)."""
    from mele.catalog import observing_night_start_utc

    when = datetime(2026, 9, 27, 15, 40, tzinfo=timezone.utc)  # ~17:40 CEST
    start = observing_night_start_utc(when, longitude_deg=16.4, tz_offset_min=120)
    assert start == datetime(2026, 9, 27, 10, 0, tzinfo=timezone.utc)
    track = object_track(
        ra_deg=323.36,
        dec_deg=-0.82,  # M2 ungefaehr
        latitude_deg=48.2,
        longitude_deg=16.4,
        when=when,
        step_min=30,
        tz_offset_min=120,
    )
    night = [slot for slot in track["windows"] if slot.get("light") == "night"]
    assert len(night) == 1
    start_h = datetime.fromisoformat(night[0]["start"].replace("Z", "+00:00"))
    end_h = datetime.fromisoformat(night[0]["end"].replace("Z", "+00:00"))
    # Fenster ueberschreitet lokale Mitternacht (UTC 22:00 = CEST 00:00)
    assert start_h < datetime(2026, 9, 27, 22, 0, tzinfo=timezone.utc) < end_h
    assert (end_h - start_h).total_seconds() > 5 * 3600
