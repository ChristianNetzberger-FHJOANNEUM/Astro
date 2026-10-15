"""Rohdatenstatistik und Session-Vorschau. Keine reale RW2 und keine Kamera."""

from __future__ import annotations

from pathlib import Path

import numpy as np
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from mele.astro_manager import create_session, ensure_manager_db, update_session_paths
from mele.capture_job import CaptureFrameResult, CaptureJobService, install_capture_routes
from mele.frame_analysis import (
    ensure_session_preview,
    light_preview_file,
    read_light_preview,
    statistics_from_linear,
)
from mele.preview_service import PreviewResult, preview_path_for


def test_statistics_use_the_file_black_and_white_levels() -> None:
    values = np.array([100, 100, 100, 100, 100, 100, 100, 100, 5000, 16383], dtype=np.float32)
    stats = statistics_from_linear(values, black_level=512, white_level=16383)
    assert stats["black_level"] == 512
    assert stats["white_level"] == 16383
    assert stats["background_median"] == 100
    assert stats["background_noise"] == 0
    assert stats["max_raw"] == 16383
    assert stats["saturated_fraction"] == pytest.approx(0.1)
    assert stats["percentile_99_9"] == pytest.approx(16280.55, abs=0.1)
    assert len(stats["histogram_bins"]) == 64
    assert sum(stats["histogram_bins"]) == 10


def test_preview_keeps_the_raw_and_pairs_jpeg_with_stats(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    session_dir = tmp_path / "sess"
    raw = session_dir / "LIGHTS" / "frame_10s_0001.RW2"
    raw.parent.mkdir(parents=True)
    raw.write_bytes(b"raw-bytes")
    calls = {"preview": 0}

    def fake_preview(source, session_dir=None, color=True):
        calls["preview"] += 1
        dest = preview_path_for(Path(source), session_dir, color=color)
        dest.parent.mkdir(parents=True, exist_ok=True)
        dest.write_bytes(b"jpeg")
        return PreviewResult(
            preview_path=dest,
            source_path=Path(source),
            width=4,
            height=4,
            stretch={"mode": "auto"},
            created=True,
            color=True,
        )

    def fake_raw(path):
        values = np.full((4, 4), 800, dtype=np.float32)
        values[0, 0] = 16383
        return values, {"BLACK": 512.0, "WHITE": 16383}

    monkeypatch.setattr("mele.frame_analysis.generate_preview", fake_preview)
    monkeypatch.setattr("mele.frame_analysis.load_cfa_raw", fake_raw)

    record = ensure_session_preview(session_dir, session_id=7, exposure_s=10, iso=640, file_name=raw.name)
    assert record is not None
    assert record["image_id"] == raw.name
    assert record["source"] == "light_preview"
    assert record["session_id"] == 7
    assert record["analysis"]["black_level"] == 512
    assert record["analysis"]["white_level"] == 16383
    assert record["analysis"]["background_median"] == 800
    assert record["stretch"]["mode"] == "auto"
    assert raw.read_bytes() == b"raw-bytes"

    again = ensure_session_preview(session_dir, session_id=7, file_name=raw.name)
    assert again is not None
    assert again["image_id"] == raw.name
    assert calls["preview"] == 1


def test_preview_route_reads_without_starting_analysis(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    db = tmp_path / "astro_manager.sqlite"
    ensure_manager_db(db)
    session = create_session(catalog_key="M31", lights_planned=1, exposure_s=10, iso=640, db_path=db, apply_profile=False)
    session_dir = tmp_path / "sess"
    raw = session_dir / "LIGHTS" / "frame_30s_0001.RW2"
    raw.parent.mkdir(parents=True)
    raw.write_bytes(b"raw-bytes")
    update_session_paths(int(session.id), local_path=str(session_dir), db_path=db)
    calls = {"preview": 0}

    def fake_preview(source, session_dir=None, color=True):
        calls["preview"] += 1
        dest = preview_path_for(Path(source), session_dir, color=color)
        dest.parent.mkdir(parents=True, exist_ok=True)
        dest.write_bytes(b"jpeg-30")
        return PreviewResult(
            preview_path=dest,
            source_path=Path(source),
            width=2,
            height=2,
            stretch={"mode": "auto"},
            created=True,
            color=True,
        )

    def fake_raw(path):
        values = np.full((4, 4), 900, dtype=np.float32)
        return values, {"BLACK": 500.0, "WHITE": 16000}

    monkeypatch.setattr("mele.frame_analysis.generate_preview", fake_preview)
    monkeypatch.setattr("mele.frame_analysis.load_cfa_raw", fake_raw)

    app = FastAPI()
    install_capture_routes(app, CaptureJobService(db_path=db, capture_one=lambda _snapshot: CaptureFrameResult(ok=True)))
    client = TestClient(app)
    waiting = client.get(f"/astro/capture/preview?session_id={session.id}")
    assert waiting.status_code == 404
    assert waiting.json()["pending"] is True
    assert calls["preview"] == 0

    later = client.get(f"/astro/capture/preview?session_id={session.id}&source=phd2_fullframe")
    assert later.status_code == 404
    assert later.json()["error"] == "Quelle noch nicht vorhanden"

    record = ensure_session_preview(
        session_dir,
        session_id=int(session.id),
        exposure_s=30,
        iso=640,
        file_name=raw.name,
    )
    assert record is not None
    ready = client.get(f"/astro/capture/preview?session_id={session.id}")
    body = ready.json()
    assert ready.status_code == 200
    assert body["image_id"] == raw.name
    assert body["source"] == "light_preview"
    assert body["analysis"]["background_median"] == 900
    assert body["analysis"]["white_level"] == 16000
    image = client.get(body["preview_url"])
    assert image.status_code == 200
    assert image.content == b"jpeg-30"
    status, path = light_preview_file(int(session.id), db_path=db)
    assert status == 200
    assert Path(path).read_bytes() == b"jpeg-30"
    assert calls["preview"] == 1
