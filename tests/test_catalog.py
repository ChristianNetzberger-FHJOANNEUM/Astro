from __future__ import annotations

from datetime import datetime
from pathlib import Path

from core.burst import detect_bursts
from core.catalog import Catalog
from core.models import Capture


def test_replace_session_roundtrip(tmp_path: Path) -> None:
    catalog = Catalog(tmp_path / "test.sqlite")
    t0 = datetime(2026, 8, 12, 20, 28, 10)
    captures = [
        Capture(
            raw_path=tmp_path / f"P{i}.RW2",
            jpg_path=tmp_path / f"P{i}.JPG",
            datetime=t0,
            file_number=i,
            stem=f"P{i}",
            exposure="1/2000",
            iso=100,
        )
        for i in range(3)
    ]
    bursts = detect_bursts(captures)
    session_id = catalog.replace_session(
        slug="Sofi-26",
        title="Test",
        root_path=str(tmp_path),
        kind="eclipse",
        notes="",
        bursts=bursts,
    )
    sessions = catalog.list_sessions()
    assert len(sessions) == 1
    assert sessions[0].id == session_id
    assert sessions[0].image_count == 3
    listed = catalog.list_bursts(session_id)
    assert len(listed) == 1
    images = catalog.list_images(listed[0].id)
    assert len(images) == 3
    assert images[0].exposure == "1/2000"
    catalog.close()
