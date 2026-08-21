from __future__ import annotations

from datetime import datetime
from pathlib import Path

from core.burst import detect_bursts
from core.catalog import Catalog
from core.models import Capture
from core.siril_workspace import create_workspace, workspace_path


def _captures(folder: Path, n: int = 3) -> list[Capture]:
    t0 = datetime(2026, 8, 12, 20, 28, 10)
    caps = []
    for i in range(n):
        raw = folder / f"P{i}.RW2"
        raw.write_bytes(b"raw")
        jpg = folder / f"P{i}.JPG"
        jpg.write_bytes(b"jpg")
        caps.append(
            Capture(
                raw_path=raw,
                jpg_path=jpg,
                datetime=t0,
                file_number=i,
                stem=f"P{i}",
                exposure="1/640",
                iso=400,
                camera="DC-S5M2X",
            )
        )
    return caps


def test_workspace_hardlinks_and_metadata(tmp_path: Path) -> None:
    originals = tmp_path / "Sofi-26" / "Lumix" / "Camera"
    originals.mkdir(parents=True)
    catalog = Catalog(tmp_path / "test.sqlite")
    bursts = detect_bursts(_captures(originals))
    session_id = catalog.replace_session(
        slug="Sofi-26",
        title="Sonnenfinsternis",
        root_path=str(tmp_path / "Sofi-26"),
        kind="eclipse",
        notes="",
        bursts=bursts,
    )
    session = catalog.get_session(session_id)
    burst = catalog.list_bursts(session_id)[0]
    frames = catalog.list_images(burst.id)
    result = create_workspace(session, burst, frames)
    assert result.linked == 3
    assert result.path == workspace_path(tmp_path / "Sofi-26", burst.burst_no)
    assert (result.path / "P0.RW2").is_file()
    assert (result.path / "metadata.json").is_file()
    text = (result.path / "metadata.json").read_text(encoding="utf-8")
    assert '"frame_id"' in text
    assert '"burst": 1' in text
    catalog.close()


def test_rescan_keeps_frame_id(tmp_path: Path) -> None:
    originals = tmp_path / "cam"
    originals.mkdir()
    catalog = Catalog(tmp_path / "ids.sqlite")
    bursts = detect_bursts(_captures(originals, 2))
    sid = catalog.replace_session("s", "t", str(tmp_path), "general", "", bursts)
    first_ids = [img.id for img in catalog.list_images(catalog.list_bursts(sid)[0].id)]
    sid2 = catalog.replace_session("s", "t", str(tmp_path), "general", "", bursts)
    assert sid == sid2
    second_ids = [img.id for img in catalog.list_images(catalog.list_bursts(sid)[0].id)]
    assert first_ids == second_ids
    catalog.close()
