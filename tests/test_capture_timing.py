"""Tests für Session capture-timing.json."""

from __future__ import annotations

from pathlib import Path

from mele.capture_timing import append_capture_timing, read_capture_timing, timing_path_for


def test_append_and_summarize(tmp_path: Path) -> None:
    session = tmp_path / "s00048"
    append_capture_timing(
        session,
        session_id=48,
        image_type="LIGHT",
        exposure_planned_s=4.0,
        expose_s=4.1,
        post_s=35.0,
        file_name="a.rw2",
    )
    append_capture_timing(
        session,
        session_id=48,
        image_type="DARK",
        exposure_planned_s=4.0,
        expose_s=4.0,
        post_s=40.0,
        file_name="b.rw2",
    )
    path = timing_path_for(session)
    assert path.is_file()
    data = read_capture_timing(session)
    assert data is not None
    assert len(data["frames"]) == 2
    assert data["summary"]["frames"] == 2
    assert data["summary"]["by_type"]["LIGHT"] == 1
    assert data["summary"]["by_type"]["DARK"] == 1
    assert abs(data["summary"]["avg_post_s"] - 37.5) < 1e-6
    assert data["summary"]["suggested_cadence_s"] == data["summary"]["avg_post_s"]


def test_read_missing(tmp_path: Path) -> None:
    assert read_capture_timing(tmp_path / "missing") is None
