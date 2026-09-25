"""Tests fuer Phase-2b GoTo-Diagnoselog."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from mele.nina_goto_log import (
    angular_distance_deg,
    approximate_separation_deg,
    enrich_record,
    save_goto_record,
)


def test_angular_distance_same_point() -> None:
    assert angular_distance_deg(100.0, 20.0, 100.0, 20.0) == pytest.approx(0.0, abs=1e-9)


def test_angular_distance_orthogonal_ish() -> None:
    # 1 deg Dec-Differenz
    assert angular_distance_deg(0.0, 0.0, 0.0, 1.0) == pytest.approx(1.0, abs=1e-6)


def test_approximate_separation_small_offset() -> None:
    # Ziel RA 165 deg = 11 h, Mount 11.01 h, Dec gleich
    metrics = approximate_separation_deg(165.0, 40.0, 11.01, 40.0)
    assert metrics["sep_deg"] == pytest.approx(metrics["approx_sep_deg"], abs=0.02)
    assert metrics["sep_deg"] < 0.2


def test_save_goto_record_writes_files(tmp_path: Path) -> None:
    record = {
        "outcome": "completed",
        "object": {
            "name": "Mirfak",
            "type": "star",
            "source": "catalog.stars",
            "kind": "star",
            "ra_deg": 51.0807,
            "dec_deg": 49.8612,
            "az_deg": 10.0,
            "alt_deg": 40.0,
            "viewer_when": "2026-09-26T00:00:00",
        },
        "request": {
            "endpoint": "/equipment/mount/slew",
            "method": "GET",
            "ra_deg": 51.0807,
            "dec_deg": 49.8612,
            "waitForResult": False,
            "center": False,
            "rotate": False,
            "epoch": "J2000",
        },
        "pre_slew": {"ra_hours": 3.2, "dec_deg": 40.0, "az_deg": 1.0, "alt_deg": 20.0, "pier": "East"},
        "api_response": {"status_code": 200, "ok": True, "message": "Slew started", "error": ""},
        "slew": {
            "start": "2026-09-26T00:00:00Z",
            "first_slewing_true": "2026-09-26T00:00:01Z",
            "end": "2026-09-26T00:00:08Z",
            "duration_s": 8.0,
        },
        "post_slew": {
            "ra_hours": 3.4054,
            "dec_deg": 49.85,
            "az_deg": 12.0,
            "alt_deg": 41.0,
            "pier": "West",
            "slewing": False,
        },
        "trail": [
            {"kind": "pre", "az": 1.0, "alt": 20.0, "ra_hours": 3.2, "dec_deg": 40.0, "pier": "East"},
            {"kind": "sample", "az": 5.0, "alt": 30.0, "ra_hours": 3.3, "dec_deg": 45.0, "pier": "East"},
            {"kind": "end", "az": 12.0, "alt": 41.0, "ra_hours": 3.4054, "dec_deg": 49.85, "pier": "West"},
        ],
        "error": "none",
    }
    saved = save_goto_record(tmp_path, record)
    assert saved["metrics"]["sep_deg"] is not None
    assert saved["metrics"]["trail_samples"] == 3
    assert saved["metrics"]["pier_sequence"] == ["East", "West"]
    paths = saved["paths"]
    assert Path(paths["json"]).is_file()
    assert Path(paths["txt"]).is_file()
    assert Path(paths["jsonl"]).is_file()
    text = Path(paths["txt"]).read_text(encoding="utf-8")
    assert "Mirfak" in text
    assert "ra_deg:" in text
    assert "nicht Stunden" in text or "Grad" in text
    line = Path(paths["jsonl"]).read_text(encoding="utf-8").strip().splitlines()[-1]
    loaded = json.loads(line)
    assert loaded["object"]["name"] == "Mirfak"


def test_enrich_without_post_slew() -> None:
    data = enrich_record({"object": {"name": "M37", "ra_deg": 1, "dec_deg": 2}, "trail": []})
    assert data["request_id"]
    assert data["metrics"]["trail_samples"] == 0
