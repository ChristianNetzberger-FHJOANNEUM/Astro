"""S5: WORK → ARCHIVE (Doppel-Hop), results ja, siril_home nie."""

from __future__ import annotations

from pathlib import Path

from mele.astro_manager import (
    create_session,
    get_session,
    list_transfer_jobs,
    set_session_lifecycle,
)
from mele.session_storage import LIFECYCLE_CLOSED
from mele.session_transfer import (
    MANIFEST_NAME,
    push_capture_to_archive,
    push_capture_to_work,
    push_work_to_archive,
    sha256_file,
)


def _seed_capture(root: Path) -> None:
    (root / "LIGHTS").mkdir(parents=True)
    (root / "DARKS").mkdir(parents=True)
    (root / "weather").mkdir(parents=True)
    (root / "LIGHTS" / "a.RW2").write_bytes(b"light-w2a-001")
    (root / "DARKS" / "d.RW2").write_bytes(b"dark-w2a-001")
    (root / "weather" / "weather.csv").write_text("utc,temp_c\nx,1\n", encoding="utf-8")
    (root / "capture-timing.json").write_text("{}", encoding="utf-8")


def test_work_to_archive_copies_results_skips_siril(tmp_path: Path) -> None:
    db = tmp_path / "astro.sqlite"
    capture = tmp_path / "cap" / "M13" / "2026-10-08" / "s00020"
    work = tmp_path / "work"
    archive = tmp_path / "nas"
    _seed_capture(capture)
    session = create_session(
        catalog_key="M13",
        started_utc="2026-10-08T18:00:00+00:00",
        local_path=str(capture),
        frames_completed=1,
        db_path=db,
    )
    set_session_lifecycle(session.id, LIFECYCLE_CLOSED, db_path=db)

    r_work = push_capture_to_work(
        session.id,
        db_path=db,
        work_transfer_root=work,
        work_local_root=tmp_path / "disp",
        stable_window_s=0.05,
    )
    assert r_work.ok, r_work.error
    work_dir = Path(r_work.work_transfer_path)
    # Siril-Zwischenprodukt + finales Result
    (work_dir / "siril_home" / "tmp.fit").write_bytes(b"scratch")
    (work_dir / "results" / "final_stack.fit").write_bytes(b"final-stack-bytes")

    # Optional: CAPTURE→ARCHIVE zuerst (ohne results)
    r_arch = push_capture_to_archive(
        session.id,
        db_path=db,
        archive_root=archive,
        stable_window_s=0.05,
    )
    assert r_arch.ok, r_arch.error
    dest = Path(r_arch.archive_path)
    assert not (dest / "results" / "final_stack.fit").exists()

    r5 = push_work_to_archive(
        session.id,
        db_path=db,
        archive_root=archive,
        stable_window_s=0.05,
    )
    assert r5.ok, r5.error
    assert (dest / "results" / "final_stack.fit").read_bytes() == b"final-stack-bytes"
    assert not (dest / "siril_home" / "tmp.fit").exists()
    assert (dest / MANIFEST_NAME).is_file()
    assert r5.archive_completeness == "complete"
    # Master bereits von S4 → skipped
    assert r5.files_skipped >= 1
    assert sha256_file(dest / "LIGHTS" / "a.RW2") == sha256_file(capture / "LIGHTS" / "a.RW2")
    sess = get_session(session.id, db_path=db)
    assert sess is not None
    assert sess.archive_status == "archived"
    jobs = list_transfer_jobs(session.id, db_path=db)
    assert any(j.kind == "work_to_archive" and j.status == "completed" for j in jobs)


def test_work_to_archive_idempotent_results(tmp_path: Path) -> None:
    db = tmp_path / "astro.sqlite"
    capture = tmp_path / "cap" / "M13" / "2026-10-08" / "s00021"
    work = tmp_path / "work"
    archive = tmp_path / "nas"
    _seed_capture(capture)
    session = create_session(
        catalog_key="M13",
        started_utc="2026-10-08T18:00:00+00:00",
        local_path=str(capture),
        db_path=db,
    )
    r_work = push_capture_to_work(
        session.id,
        db_path=db,
        work_transfer_root=work,
        stable_window_s=0.05,
    )
    assert r_work.ok
    work_dir = Path(r_work.work_transfer_path)
    kept = work_dir / "results" / "stack.fit"
    kept.parent.mkdir(parents=True, exist_ok=True)
    kept.write_bytes(b"precious")

    r1 = push_work_to_archive(
        session.id, db_path=db, archive_root=archive, stable_window_s=0.05
    )
    assert r1.ok, r1.error
    dest = Path(r1.archive_path)
    assert (dest / "results" / "stack.fit").read_bytes() == b"precious"

    r2 = push_work_to_archive(
        session.id, db_path=db, archive_root=archive, stable_window_s=0.05
    )
    assert r2.ok, r2.error
    assert r2.files_copied == 0
    assert (dest / "results" / "stack.fit").read_bytes() == b"precious"


def test_work_to_archive_ignores_stale_nas_archive_path(tmp_path: Path) -> None:
    """Alte \\NAS\\…-Pfade in der DB dürfen nicht Ziel sein — aktueller archive_root gilt."""
    db = tmp_path / "astro.sqlite"
    capture = tmp_path / "cap" / "M57" / "2026-10-06" / "s00047"
    work = tmp_path / "work"
    archive = tmp_path / "nas_media" / "Astro" / "Mele"
    _seed_capture(capture)
    session = create_session(
        catalog_key="M57",
        started_utc="2026-10-06T18:00:00+00:00",
        local_path=str(capture),
        archive_path=r"\\NAS\Astro\Capture\Mele\M57_Ring_Nebula\2026-10-06\s00047",
        db_path=db,
    )
    r_work = push_capture_to_work(
        session.id,
        db_path=db,
        work_transfer_root=work,
        stable_window_s=0.05,
    )
    assert r_work.ok, r_work.error
    work_dir = Path(r_work.work_transfer_path)
    (work_dir / "results" / "stack.fit").parent.mkdir(parents=True, exist_ok=True)
    (work_dir / "results" / "stack.fit").write_bytes(b"ok")

    r5 = push_work_to_archive(
        session.id, db_path=db, archive_root=archive, stable_window_s=0.05
    )
    assert r5.ok, r5.error
    dest = Path(r5.archive_path)
    dest_n = str(dest).replace("/", "\\").lower()
    assert dest_n.startswith(str(archive).replace("/", "\\").lower())
    assert "\\nas\\" not in dest_n
    assert (dest / "results" / "stack.fit").is_file()
    sess = get_session(session.id, db_path=db)
    assert sess is not None
    assert "\\nas\\" not in sess.archive_path.replace("/", "\\").lower()


def test_work_to_archive_requires_work_path(tmp_path: Path) -> None:
    db = tmp_path / "astro.sqlite"
    capture = tmp_path / "cap" / "M13" / "2026-10-08" / "s00022"
    _seed_capture(capture)
    session = create_session(
        catalog_key="M13",
        started_utc="2026-10-08T18:00:00+00:00",
        local_path=str(capture),
        db_path=db,
    )
    r = push_work_to_archive(
        session.id, db_path=db, archive_root=tmp_path / "nas", stable_window_s=0.05
    )
    assert r.ok is False
    assert "WORK" in r.error


def test_work_to_archive_fills_missing_masters(tmp_path: Path) -> None:
    """Ohne vorheriges S4: fehlende Master kommen von WORK."""
    db = tmp_path / "astro.sqlite"
    capture = tmp_path / "cap" / "M13" / "2026-10-08" / "s00023"
    work = tmp_path / "work"
    archive = tmp_path / "nas"
    _seed_capture(capture)
    session = create_session(
        catalog_key="M13",
        started_utc="2026-10-08T18:00:00+00:00",
        local_path=str(capture),
        db_path=db,
    )
    r_work = push_capture_to_work(
        session.id,
        db_path=db,
        work_transfer_root=work,
        stable_window_s=0.05,
    )
    assert r_work.ok
    work_dir = Path(r_work.work_transfer_path)
    (work_dir / "results" / "out.fit").parent.mkdir(parents=True, exist_ok=True)
    (work_dir / "results" / "out.fit").write_bytes(b"out")

    r5 = push_work_to_archive(
        session.id, db_path=db, archive_root=archive, stable_window_s=0.05
    )
    assert r5.ok, r5.error
    dest = Path(r5.archive_path)
    assert (dest / "LIGHTS" / "a.RW2").is_file()
    assert (dest / "results" / "out.fit").is_file()
    # work_transfer_path bleibt gesetzt
    sess = get_session(session.id, db_path=db)
    assert sess is not None
    assert sess.work_transfer_path
