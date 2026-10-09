"""S3: CAPTURE → WORK verified copy."""

from __future__ import annotations

import json
from pathlib import Path

from mele.astro_manager import create_session, list_transfer_jobs
from mele.session_transfer import (
    MANIFEST_NAME,
    push_capture_to_work,
    sha256_file,
    storage_paths_payload,
)


def _write_session_tree(root: Path) -> None:
    (root / "LIGHTS").mkdir(parents=True)
    (root / "DARKS").mkdir(parents=True)
    (root / "weather").mkdir(parents=True)
    (root / "LIGHTS" / "a.RW2").write_bytes(b"light-data-001")
    (root / "DARKS" / "d.RW2").write_bytes(b"dark-data-001")
    (root / "weather" / "weather.csv").write_text("utc,temp_c\n2026-10-08T20:00:00+00:00,10\n", encoding="utf-8")
    (root / "capture-timing.json").write_text("{}", encoding="utf-8")


def test_push_work_copy_manifest_and_siril_home(tmp_path: Path) -> None:
    db = tmp_path / "astro.sqlite"
    capture = tmp_path / "capture" / "M13" / "2026-10-08" / "s00001"
    work = tmp_path / "work"
    _write_session_tree(capture)
    session = create_session(
        catalog_key="M13",
        started_utc="2026-10-08T18:00:00+00:00",
        local_path=str(capture),
        frames_completed=1,
        db_path=db,
    )

    result = push_capture_to_work(
        session.id,
        db_path=db,
        work_transfer_root=work,
        work_local_root=tmp_path / "local_display",
        siril_home_dirname="siril_home",
        stable_window_s=0.05,
    )
    assert result.ok, result.error
    assert result.files_copied >= 4
    dest = Path(result.work_transfer_path)
    assert (dest / "LIGHTS" / "a.RW2").is_file()
    assert (dest / "siril_home").is_dir()
    assert (dest / "results").is_dir()
    assert (dest / MANIFEST_NAME).is_file()
    manifest = json.loads((dest / MANIFEST_NAME).read_text(encoding="utf-8"))
    assert manifest["schema_version"] == 1
    assert manifest["revision"] >= 1
    assert any(f["path"] == "LIGHTS/a.RW2" for f in manifest["files"])
    assert sha256_file(dest / "LIGHTS" / "a.RW2") == sha256_file(capture / "LIGHTS" / "a.RW2")
    assert "siril_home" in result.siril_home_local.replace("\\", "/")
    jobs = list_transfer_jobs(session.id, db_path=db)
    assert jobs and jobs[0].status == "completed"


def test_push_work_idempotent_preserves_siril_home(tmp_path: Path) -> None:
    db = tmp_path / "astro.sqlite"
    capture = tmp_path / "cap" / "M13" / "2026-10-08" / "s00002"
    work = tmp_path / "work"
    _write_session_tree(capture)
    session = create_session(
        catalog_key="M13",
        started_utc="2026-10-08T18:00:00+00:00",
        local_path=str(capture),
        db_path=db,
    )
    r1 = push_capture_to_work(
        session.id,
        db_path=db,
        work_transfer_root=work,
        work_local_root=tmp_path / "disp",
        stable_window_s=0.05,
    )
    assert r1.ok
    dest = Path(r1.work_transfer_path)
    marker = dest / "siril_home" / "user_process.bin"
    marker.write_bytes(b"keep-me")
    (dest / "results" / "stack.fit").write_bytes(b"result")

    r2 = push_capture_to_work(
        session.id,
        db_path=db,
        work_transfer_root=work,
        work_local_root=tmp_path / "disp",
        stable_window_s=0.05,
    )
    assert r2.ok, r2.error
    assert r2.files_copied == 0
    assert r2.files_skipped >= 4
    assert marker.read_bytes() == b"keep-me"
    assert (dest / "results" / "stack.fit").read_bytes() == b"result"


def test_push_work_conflict_on_hash_mismatch(tmp_path: Path) -> None:
    db = tmp_path / "astro.sqlite"
    capture = tmp_path / "cap" / "M13" / "2026-10-08" / "s00003"
    work = tmp_path / "work"
    _write_session_tree(capture)
    session = create_session(
        catalog_key="M13",
        started_utc="2026-10-08T18:00:00+00:00",
        local_path=str(capture),
        db_path=db,
    )
    r1 = push_capture_to_work(
        session.id,
        db_path=db,
        work_transfer_root=work,
        stable_window_s=0.05,
    )
    assert r1.ok
    dest = Path(r1.work_transfer_path)
    (dest / "LIGHTS" / "a.RW2").write_bytes(b"TAMPERED")

    r2 = push_capture_to_work(
        session.id,
        db_path=db,
        work_transfer_root=work,
        stable_window_s=0.05,
    )
    assert r2.ok is False
    assert "Konflikt" in r2.error
    jobs = list_transfer_jobs(session.id, db_path=db)
    assert any(j.status == "failed" for j in jobs)


def test_push_work_requires_config(tmp_path: Path, monkeypatch) -> None:
    db = tmp_path / "astro.sqlite"
    capture = tmp_path / "cap"
    capture.mkdir()
    (capture / "f.txt").write_text("x", encoding="utf-8")
    session = create_session(catalog_key="X", local_path=str(capture), db_path=db)

    from mele.config import MeleSettings
    import mele.session_transfer as st

    monkeypatch.setattr(
        st,
        "load_mele_settings",
        lambda: MeleSettings(work_transfer_root=None, work_local_root=None),
    )
    result = push_capture_to_work(session.id, db_path=db, stable_window_s=0.05)
    assert result.ok is False
    assert "work_transfer_root" in result.error


def test_storage_payload() -> None:
    from mele.config import MeleSettings

    payload = storage_paths_payload(
        MeleSettings(
            work_transfer_root=Path(r"\\NB\Work"),
            work_local_root=Path(r"D:\Work"),
        )
    )
    assert payload["work_configured"] is True
    assert payload["config_file"] == "configs/mele.yaml"
