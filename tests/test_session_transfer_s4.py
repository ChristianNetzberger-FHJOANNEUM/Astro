"""S4: CAPTURE → ARCHIVE verified copy, Results-Schutz."""

from __future__ import annotations

import json
from pathlib import Path

from mele.astro_manager import create_session, get_session, list_transfer_jobs
from mele.session_transfer import MANIFEST_NAME, push_capture_to_archive, sha256_file


def _write_capture(root: Path) -> None:
    (root / "LIGHTS").mkdir(parents=True)
    (root / "DARKS").mkdir(parents=True)
    (root / "weather").mkdir(parents=True)
    (root / "LIGHTS" / "a.RW2").write_bytes(b"light-arch-001")
    (root / "DARKS" / "d.RW2").write_bytes(b"dark-arch-001")
    (root / "weather" / "weather.csv").write_text("utc,temp_c\nx,1\n", encoding="utf-8")
    # CAPTURE sollte keine results haben — falls doch, S4 darf sie nicht aufs Archiv spiegeln
    (root / "results").mkdir(parents=True)
    (root / "results" / "should_not_copy.fit").write_bytes(b"nope")


def test_push_archive_copy_and_status(tmp_path: Path) -> None:
    db = tmp_path / "astro.sqlite"
    capture = tmp_path / "cap" / "M13" / "2026-10-08" / "s00010"
    archive = tmp_path / "nas"
    _write_capture(capture)
    session = create_session(
        catalog_key="M13",
        started_utc="2026-10-08T18:00:00+00:00",
        local_path=str(capture),
        frames_completed=1,
        db_path=db,
    )
    # CLOSED → archive_completeness=complete
    from mele.astro_manager import set_session_lifecycle
    from mele.session_storage import LIFECYCLE_CLOSED

    set_session_lifecycle(session.id, LIFECYCLE_CLOSED, db_path=db)

    result = push_capture_to_archive(
        session.id,
        db_path=db,
        archive_root=archive,
        stable_window_s=0.05,
    )
    assert result.ok, result.error
    dest = Path(result.archive_path)
    assert (dest / "LIGHTS" / "a.RW2").is_file()
    assert (dest / "weather" / "weather.csv").is_file()
    assert not (dest / "results" / "should_not_copy.fit").exists()
    assert (dest / MANIFEST_NAME).is_file()
    assert result.archive_completeness == "complete"
    sess = get_session(session.id, db_path=db)
    assert sess is not None
    assert sess.archive_status == "archived"
    assert sess.archive_path == str(dest)
    assert sha256_file(dest / "LIGHTS" / "a.RW2") == sha256_file(capture / "LIGHTS" / "a.RW2")
    jobs = list_transfer_jobs(session.id, db_path=db)
    assert any(j.kind == "capture_to_archive" and j.status == "completed" for j in jobs)


def test_push_archive_preserves_existing_results(tmp_path: Path) -> None:
    db = tmp_path / "astro.sqlite"
    capture = tmp_path / "cap" / "M13" / "2026-10-08" / "s00011"
    archive = tmp_path / "nas"
    _write_capture(capture)
    session = create_session(
        catalog_key="M13",
        started_utc="2026-10-08T18:00:00+00:00",
        local_path=str(capture),
        db_path=db,
    )
    r1 = push_capture_to_archive(
        session.id, db_path=db, archive_root=archive, stable_window_s=0.05
    )
    assert r1.ok
    dest = Path(r1.archive_path)
    kept = dest / "results" / "final_stack.fit"
    kept.parent.mkdir(parents=True, exist_ok=True)
    kept.write_bytes(b"precious-result")

    r2 = push_capture_to_archive(
        session.id, db_path=db, archive_root=archive, stable_window_s=0.05
    )
    assert r2.ok, r2.error
    assert r2.files_copied == 0
    assert kept.read_bytes() == b"precious-result"
    # Manifest darf results-Eintrag behalten wenn wir ihn manuell ergänzen — Datei jedenfalls unangetastet
    assert kept.is_file()


def test_push_archive_conflict(tmp_path: Path) -> None:
    db = tmp_path / "astro.sqlite"
    capture = tmp_path / "cap" / "M13" / "2026-10-08" / "s00012"
    archive = tmp_path / "nas"
    _write_capture(capture)
    session = create_session(
        catalog_key="M13",
        started_utc="2026-10-08T18:00:00+00:00",
        local_path=str(capture),
        db_path=db,
    )
    r1 = push_capture_to_archive(
        session.id, db_path=db, archive_root=archive, stable_window_s=0.05
    )
    assert r1.ok
    dest = Path(r1.archive_path)
    (dest / "LIGHTS" / "a.RW2").write_bytes(b"TAMPER")
    r2 = push_capture_to_archive(
        session.id, db_path=db, archive_root=archive, stable_window_s=0.05
    )
    assert r2.ok is False
    assert "Konflikt" in r2.error
