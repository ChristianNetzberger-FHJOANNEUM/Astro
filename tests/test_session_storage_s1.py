"""S1 Session Storage: Config, Migration, Lifecycle, Manifest, WORK-Pfade, Transfer-Jobs."""

from __future__ import annotations

import sqlite3
from datetime import datetime
from pathlib import Path

import pytest
import yaml

from mele.astro_manager import (
    SCHEMA_VERSION,
    create_session,
    create_transfer_job,
    ensure_manager_db,
    get_session,
    get_transfer_job,
    list_transfer_jobs,
    set_session_lifecycle,
    update_session_storage_fields,
    update_transfer_job_status,
)
from mele.config import load_mele_settings
from mele.session_storage import (
    ARCHIVE_COMPLETENESS_COMPLETE,
    ARCHIVE_COMPLETENESS_STALE,
    LIFECYCLE_CAPTURING,
    LIFECYCLE_CLOSED,
    LIFECYCLE_OPEN,
    LifecycleError,
    ManifestError,
    can_transition_lifecycle,
    empty_manifest,
    find_manifest_conflicts,
    map_work_paths,
    mark_archive_stale_after_new_files,
    merge_manifest_files,
    session_relative_under_root,
    siril_home_dir,
    suggested_work_local_session_dir,
    suggested_work_transfer_session_dir,
    validate_manifest,
)


def test_config_loads_work_paths(tmp_path: Path) -> None:
    cfg = tmp_path / "mele.yaml"
    cfg.write_text(
        yaml.safe_dump(
            {
                "local_capture_root": r"C:\Astro\Capture\Mele",
                "archive_root": r"\\NAS\Astro\Capture\Mele",
                "work_transfer_root": r"\\NOTEBOOK\AstroWork\Mele",
                "work_local_root": r"D:\Astro\Work\Mele",
                "siril_home_dirname": "siril_home",
            }
        ),
        encoding="utf-8",
    )
    settings = load_mele_settings(cfg)
    assert settings.work_transfer_root == Path(r"\\NOTEBOOK\AstroWork\Mele")
    assert settings.work_local_root == Path(r"D:\Astro\Work\Mele")
    assert settings.siril_home_dirname == "siril_home"


def test_config_empty_work_paths_are_none(tmp_path: Path) -> None:
    cfg = tmp_path / "mele.yaml"
    cfg.write_text(
        yaml.safe_dump(
            {
                "work_transfer_root": "",
                "work_local_root": "",
            }
        ),
        encoding="utf-8",
    )
    settings = load_mele_settings(cfg)
    assert settings.work_transfer_root is None
    assert settings.work_local_root is None


def test_work_path_mapping() -> None:
    rel = session_relative_under_root(
        "M101",
        when=datetime(2026, 10, 8, 22, 0, 0),
        display_name="M101",
        session_id=7,
    )
    assert rel == Path("M101") / "2026-10-08" / "s00007"
    transfer, local = map_work_paths(
        rel,
        work_transfer_root=Path(r"\\NOTEBOOK\AstroWork\Mele"),
        work_local_root=Path(r"D:\Astro\Work\Mele"),
    )
    assert transfer == Path(r"\\NOTEBOOK\AstroWork\Mele") / rel
    assert local == Path(r"D:\Astro\Work\Mele") / rel
    assert siril_home_dir(local) == local / "siril_home"

    assert suggested_work_transfer_session_dir(
        "M101",
        when=datetime(2026, 10, 8),
        work_transfer_root=Path(r"\\NB\Work"),
        session_id=1,
    ) == Path(r"\\NB\Work") / "M101" / "2026-10-08" / "s00001"
    assert suggested_work_local_session_dir(
        "M101",
        when=datetime(2026, 10, 8),
        work_local_root=Path(r"D:\Astro\Work\Mele"),
        session_id=1,
    ) == Path(r"D:\Astro\Work\Mele") / "M101" / "2026-10-08" / "s00001"


def test_work_paths_none_roots() -> None:
    transfer, local = map_work_paths(
        "M101/2026-10-08/s00001",
        work_transfer_root=None,
        work_local_root=None,
    )
    assert transfer is None
    assert local is None
    assert suggested_work_transfer_session_dir(
        "M101",
        work_transfer_root=Path(r"\\X\Y"),
        session_id=2,
    ) == Path(r"\\X\Y") / session_relative_under_root("M101", session_id=2)


def test_lifecycle_transitions() -> None:
    assert can_transition_lifecycle(LIFECYCLE_OPEN, LIFECYCLE_CAPTURING)
    assert can_transition_lifecycle(LIFECYCLE_CAPTURING, LIFECYCLE_CLOSED)
    assert can_transition_lifecycle(LIFECYCLE_OPEN, LIFECYCLE_CLOSED)
    assert can_transition_lifecycle(LIFECYCLE_CLOSED, LIFECYCLE_CLOSED)
    assert not can_transition_lifecycle(LIFECYCLE_CLOSED, LIFECYCLE_OPEN)
    assert not can_transition_lifecycle(LIFECYCLE_CLOSED, LIFECYCLE_CAPTURING)
    assert mark_archive_stale_after_new_files(ARCHIVE_COMPLETENESS_COMPLETE) == ARCHIVE_COMPLETENESS_STALE


def test_lifecycle_db_transitions(tmp_path: Path) -> None:
    db = tmp_path / "astro_manager.sqlite"
    session = create_session(catalog_key="M31", frames_completed=0, db_path=db)
    assert session.lifecycle_status == LIFECYCLE_OPEN
    assert session.session_start_utc
    assert session.object_id == "M31"
    assert session.archive_completeness == "none"

    capturing = set_session_lifecycle(session.id, LIFECYCLE_CAPTURING, db_path=db)
    assert capturing.lifecycle_status == LIFECYCLE_CAPTURING

    closed = set_session_lifecycle(session.id, LIFECYCLE_CLOSED, db_path=db)
    assert closed.lifecycle_status == LIFECYCLE_CLOSED
    assert closed.session_end_utc

    with pytest.raises(LifecycleError):
        set_session_lifecycle(session.id, LIFECYCLE_OPEN, db_path=db)


def test_manifest_schema_and_revision() -> None:
    m = empty_manifest(session_id=42, object_name="M101", capture_date="2026-10-08")
    assert m["schema_version"] == 1
    assert m["revision"] == 0
    validated = validate_manifest(m)
    assert validated["files"] == []

    merged = merge_manifest_files(
        validated,
        [{"path": "LIGHTS/a.RW2", "size": 100, "sha256": "a" * 64}],
        generated_utc="2026-10-08T20:00:00+00:00",
    )
    assert merged["revision"] == 1
    assert len(merged["files"]) == 1

    # gleiche Datei erneut → keine neue Revision
    again = merge_manifest_files(
        merged,
        [{"path": "LIGHTS/a.RW2", "size": 100, "sha256": "a" * 64}],
    )
    assert again["revision"] == 1

    # neue Datei → Revision++
    more = merge_manifest_files(
        again,
        [{"path": "DARKS/d.RW2", "size": 50, "sha256": "b" * 64}],
    )
    assert more["revision"] == 2

    conflicts = find_manifest_conflicts(
        more["files"],
        [{"path": "LIGHTS/a.RW2", "size": 100, "sha256": "c" * 64}],
    )
    assert len(conflicts) == 1
    with pytest.raises(ManifestError):
        merge_manifest_files(
            more,
            [{"path": "LIGHTS/a.RW2", "size": 100, "sha256": "c" * 64}],
        )


def test_manifest_rejects_bad_paths() -> None:
    m = empty_manifest(session_id=1)
    with pytest.raises(ManifestError):
        validate_manifest({**m, "files": [{"path": "../etc/passwd", "size": 1, "sha256": "a" * 64}]})
    with pytest.raises(ManifestError):
        validate_manifest({**m, "schema_version": 99, "files": []})


def test_transfer_jobs_crud(tmp_path: Path) -> None:
    db = tmp_path / "astro_manager.sqlite"
    session = create_session(catalog_key="M42", db_path=db)
    job = create_transfer_job(
        session_id=session.id,
        kind="capture_to_work",
        source_root=r"C:\Astro\Capture\Mele\M42",
        dest_root=r"\\NOTEBOOK\AstroWork\Mele\M42",
        completeness="partial",
        db_path=db,
    )
    assert job.status == "queued"
    assert job.job_id
    assert get_transfer_job(job.job_id, db_path=db) is not None

    with pytest.raises(ValueError, match="Aktiver Transfer"):
        create_transfer_job(session_id=session.id, kind="capture_to_work", db_path=db)

    running = update_transfer_job_status(job.job_id, status="copying", progress_files=2, db_path=db)
    assert running.status == "copying"
    assert running.started_utc
    assert running.progress_files == 2

    done = update_transfer_job_status(job.job_id, status="completed", db_path=db)
    assert done.status == "completed"
    assert done.finished_utc

    # nach completed darf neuer Job gleichen Kinds entstehen
    job2 = create_transfer_job(session_id=session.id, kind="capture_to_work", db_path=db)
    assert job2.job_id != job.job_id
    assert len(list_transfer_jobs(session.id, db_path=db)) == 2


def test_storage_fields_update(tmp_path: Path) -> None:
    db = tmp_path / "astro_manager.sqlite"
    session = create_session(catalog_key="M33", db_path=db)
    updated = update_session_storage_fields(
        session.id,
        work_transfer_path=r"\\NB\Work\M33\s00001",
        work_local_path=r"D:\Work\M33\s00001",
        archive_completeness="partial",
        manifest_revision=3,
        weather_export_status="unavailable",
        db_path=db,
    )
    assert updated.work_transfer_path.endswith("s00001")
    assert updated.work_local_path.startswith("D:")
    assert updated.archive_completeness == "partial"
    assert updated.manifest_revision == 3
    assert updated.weather_export_status == "unavailable"


def test_migrate_v2_sessions_to_storage_v3(tmp_path: Path) -> None:
    """Bestehende Sessions behalten Daten; Lifecycle wird abgeleitet."""
    db = tmp_path / "legacy_v2.sqlite"
    with sqlite3.connect(db) as conn:
        conn.executescript(
            """
            CREATE TABLE meta (key TEXT PRIMARY KEY, value TEXT NOT NULL);
            CREATE TABLE imaging_profiles (
              id INTEGER PRIMARY KEY AUTOINCREMENT,
              catalog_key TEXT NOT NULL,
              label TEXT NOT NULL,
              equipment TEXT NOT NULL DEFAULT '',
              exposure_s REAL, gain REAL, iso INTEGER, offset_adu INTEGER,
              binning TEXT NOT NULL DEFAULT '1x1',
              filter_name TEXT NOT NULL DEFAULT '',
              frames INTEGER NOT NULL DEFAULT 1,
              notes TEXT NOT NULL DEFAULT '',
              created_utc TEXT NOT NULL, updated_utc TEXT NOT NULL
            );
            CREATE TABLE sessions (
              id INTEGER PRIMARY KEY AUTOINCREMENT,
              catalog_key TEXT NOT NULL,
              profile_id INTEGER,
              started_utc TEXT NOT NULL,
              ended_utc TEXT,
              frames_planned INTEGER,
              frames_completed INTEGER NOT NULL DEFAULT 0,
              lights_planned INTEGER,
              lights_completed INTEGER NOT NULL DEFAULT 0,
              darks_planned INTEGER,
              darks_completed INTEGER NOT NULL DEFAULT 0,
              exposure_s REAL,
              gain REAL, iso INTEGER, offset_adu INTEGER,
              binning TEXT NOT NULL DEFAULT '1x1',
              filter_name TEXT NOT NULL DEFAULT '',
              equipment TEXT NOT NULL DEFAULT '',
              integration_s REAL,
              local_path TEXT NOT NULL DEFAULT '',
              archive_path TEXT NOT NULL DEFAULT '',
              archive_status TEXT NOT NULL DEFAULT 'local',
              notes TEXT NOT NULL DEFAULT '',
              created_utc TEXT NOT NULL,
              updated_utc TEXT NOT NULL
            );
            INSERT INTO meta(key, value) VALUES ('schema_version', '2');
            INSERT INTO meta(key, value) VALUES ('lights_darks_backfill', '1');
            INSERT INTO sessions (
              catalog_key, profile_id, started_utc, ended_utc,
              frames_planned, frames_completed, lights_planned, lights_completed,
              darks_planned, darks_completed, exposure_s, integration_s,
              local_path, archive_path, archive_status, notes, created_utc, updated_utc
            ) VALUES
            ('M31', NULL, '2026-01-01T20:00:00+00:00', '2026-01-02T02:00:00+00:00',
             50, 40, 50, 40, NULL, 0, 10.0, 400.0,
             'C:/Astro/Capture/Mele/M31/2026-01-01/s00001', '', 'local', 'keep-me',
             '2026-01-01T20:00:00+00:00', '2026-01-02T02:00:00+00:00'),
            ('M42', NULL, '2026-02-01T20:00:00+00:00', NULL,
             10, 3, 10, 3, NULL, 0, 30.0, 90.0,
             '', '', 'local', '',
             '2026-02-01T20:00:00+00:00', '2026-02-01T21:00:00+00:00'),
            ('M33', NULL, '2026-03-01T20:00:00+00:00', NULL,
             5, 0, 5, 0, NULL, 0, 60.0, NULL,
             '', '', 'pending', 'open-one',
             '2026-03-01T20:00:00+00:00', '2026-03-01T20:00:00+00:00');
            """
        )
        conn.commit()

    ensure_manager_db(db)

    closed = get_session(1, db_path=db)
    capturing = get_session(2, db_path=db)
    opened = get_session(3, db_path=db)
    assert closed is not None and capturing is not None and opened is not None

    assert closed.local_path.endswith("s00001")
    assert closed.notes == "keep-me"
    assert closed.lights_completed == 40
    assert closed.lifecycle_status == LIFECYCLE_CLOSED
    assert closed.session_end_utc == "2026-01-02T02:00:00+00:00"
    assert closed.object_id == "M31"

    assert capturing.lifecycle_status == LIFECYCLE_CAPTURING
    assert capturing.lights_completed == 3

    assert opened.lifecycle_status == LIFECYCLE_OPEN
    assert opened.archive_status == "pending"

    with sqlite3.connect(db) as conn:
        ver = conn.execute("SELECT value FROM meta WHERE key='schema_version'").fetchone()
        tables = {
            r[0]
            for r in conn.execute(
                "SELECT name FROM sqlite_master WHERE type='table'"
            ).fetchall()
        }
    assert int(ver[0]) == SCHEMA_VERSION
    assert "transfer_jobs" in tables
