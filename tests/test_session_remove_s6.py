"""S6: Sichere CAPTURE/WORK/DB-Bereinigung, nie NAS."""

from __future__ import annotations

from pathlib import Path

from mele.astro_manager import create_session, get_session, update_session_storage_fields
from mele.session_remove import RemoveError, assert_safe_deletable_session_dir, remove_session_storage
from mele.session_storage import ARCHIVE_COMPLETENESS_COMPLETE


def _tree(root: Path) -> None:
    (root / "LIGHTS").mkdir(parents=True)
    (root / "LIGHTS" / "a.RW2").write_bytes(b"data")


def test_remove_capture_requires_complete_unless_force(tmp_path: Path) -> None:
    db = tmp_path / "astro.sqlite"
    cap_root = tmp_path / "capture"
    capture = cap_root / "M13" / "2026-10-08" / "s00030"
    _tree(capture)
    session = create_session(
        catalog_key="M13",
        started_utc="2026-10-08T18:00:00+00:00",
        local_path=str(capture),
        db_path=db,
    )
    # Session-ID bestimmt slug — Pfad anpassen
    capture2 = cap_root / "M13" / "2026-10-08" / f"s{session.id:05d}"
    if capture != capture2:
        capture2.parent.mkdir(parents=True, exist_ok=True)
        if capture.exists():
            capture.rename(capture2)
        from mele.astro_manager import update_session_paths

        update_session_paths(session.id, local_path=str(capture2), db_path=db)
        capture = capture2

    r = remove_session_storage(
        session.id,
        delete_capture=True,
        db_path=db,
        local_capture_root=cap_root,
        archive_root=tmp_path / "nas",
    )
    assert r.ok is False
    assert "complete" in r.error
    assert capture.is_dir()

    r2 = remove_session_storage(
        session.id,
        delete_capture=True,
        force_capture=True,
        db_path=db,
        local_capture_root=cap_root,
        archive_root=tmp_path / "nas",
    )
    assert r2.ok, r2.error
    assert r2.deleted_capture
    assert not capture.exists()
    sess = get_session(session.id, db_path=db)
    assert sess is not None
    assert sess.local_path == ""


def test_remove_work_and_db_never_touches_archive(tmp_path: Path) -> None:
    db = tmp_path / "astro.sqlite"
    cap_root = tmp_path / "capture"
    work_root = tmp_path / "work"
    nas = tmp_path / "nas" / "Mele"
    session = create_session(
        catalog_key="M13",
        started_utc="2026-10-08T18:00:00+00:00",
        local_path="",
        db_path=db,
    )
    work = work_root / "M13" / "2026-10-08" / f"s{session.id:05d}"
    arch = nas / "M13" / "2026-10-08" / f"s{session.id:05d}"
    _tree(work)
    _tree(arch)
    (arch / "results").mkdir(parents=True)
    (arch / "results" / "final.fit").write_bytes(b"keep")
    update_session_storage_fields(
        session.id,
        work_transfer_path=str(work),
        work_local_path=str(work),
        archive_completeness=ARCHIVE_COMPLETENESS_COMPLETE,
        db_path=db,
    )
    from mele.astro_manager import update_session

    update_session(session.id, archive_path=str(arch), archive_status="archived", db_path=db)

    r = remove_session_storage(
        session.id,
        delete_work=True,
        delete_db=True,
        db_path=db,
        local_capture_root=cap_root,
        work_transfer_root=work_root,
        archive_root=nas,
    )
    assert r.ok, r.error
    assert r.deleted_work
    assert r.deleted_db
    assert not work.exists()
    assert (arch / "results" / "final.fit").read_bytes() == b"keep"
    assert get_session(session.id, db_path=db) is None


def test_guard_rejects_outside_root_and_archive(tmp_path: Path) -> None:
    allowed = tmp_path / "capture"
    other = tmp_path / "elsewhere" / "s00001"
    other.mkdir(parents=True)
    try:
        assert_safe_deletable_session_dir(
            other, allowed_root=allowed, session_id=1, label="CAPTURE"
        )
        assert False, "expected RemoveError"
    except RemoveError as exc:
        assert "Root" in str(exc) or "liegt nicht" in str(exc)

    nas = tmp_path / "nas"
    under_nas = nas / "x" / "s00001"
    under_nas.mkdir(parents=True)
    try:
        assert_safe_deletable_session_dir(
            under_nas,
            allowed_root=nas,  # would pass under root…
            session_id=1,
            label="CAPTURE",
            forbidden_roots=[nas],
        )
        assert False, "expected RemoveError"
    except RemoveError as exc:
        assert "verboten" in str(exc).lower() or "ARCHIVE" in str(exc)


def test_guard_rejects_wrong_session_slug(tmp_path: Path) -> None:
    root = tmp_path / "capture"
    path = root / "M13" / "s00099"
    path.mkdir(parents=True)
    try:
        assert_safe_deletable_session_dir(
            path, allowed_root=root, session_id=1, label="CAPTURE"
        )
        assert False, "expected RemoveError"
    except RemoveError as exc:
        assert "s00001" in str(exc)
