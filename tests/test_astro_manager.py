from datetime import datetime
from pathlib import Path

from mele.astro_manager import (
    create_session,
    delete_profile,
    delete_session,
    ensure_manager_db,
    folder_slug,
    list_profiles,
    list_sessions,
    object_summary,
    session_dir_slug,
    suggested_local_session_dir,
    upsert_profile,
)


def test_schema_and_profile_session_crud(tmp_path: Path) -> None:
    db = tmp_path / "astro_manager.sqlite"
    ensure_manager_db(db)

    profile = upsert_profile(
        catalog_key="M31",
        label="S5IIX 60s",
        equipment="Lumix S5IIX",
        exposure_s=60.0,
        iso=800,
        frames=100,
        db_path=db,
    )
    assert profile.id > 0
    assert profile.catalog_key == "M31"
    assert profile.exposure_s == 60.0

    updated = upsert_profile(
        catalog_key="M31",
        label="S5IIX 60s HDR",
        profile_id=profile.id,
        equipment="Lumix S5IIX",
        exposure_s=60.0,
        iso=1600,
        frames=120,
        filter_name="UV/IR",
        db_path=db,
    )
    assert updated.id == profile.id
    assert updated.label == "S5IIX 60s HDR"
    assert updated.iso == 1600
    assert updated.filter_name == "UV/IR"

    rows = list_profiles("M31", db_path=db)
    assert len(rows) == 1
    assert rows[0].label == "S5IIX 60s HDR"

    session = create_session(
        catalog_key="M31",
        profile_id=profile.id,
        started_utc="2026-10-02T20:00:00+00:00",
        frames_planned=120,
        frames_completed=96,
        exposure_s=60.0,
        local_path=r"C:\Astro\Capture\Mele\M31\2026-10-02",
        archive_path=r"\\NAS\Astro\M31\2026-10-02",
        archive_status="local",
        notes="erste Session",
        db_path=db,
    )
    assert session.id > 0
    assert session.frames_completed == 96
    assert session.lights_completed == 96
    assert session.lights_planned == 120
    assert session.darks_completed == 0
    assert session.integration_s == 96 * 60.0
    assert session.archive_status == "local"
    assert session.local_path.endswith("2026-10-02")

    sessions = list_sessions("M31", db_path=db)
    assert len(sessions) == 1

    summary = object_summary("M31", db_path=db)
    assert summary["catalog_key"] == "M31"
    assert summary["profile_count"] == 1
    assert summary["session_count"] == 1
    assert summary["total_integration_s"] == 5760.0
    assert summary["profiles"][0]["label"] == "S5IIX 60s HDR"
    assert summary["sessions"][0]["archive_status"] == "local"

    assert delete_session(session.id, db_path=db) is True
    assert list_sessions("M31", db_path=db) == []
    assert delete_profile(profile.id, db_path=db) is True
    assert list_profiles("M31", db_path=db) == []


def test_soft_link_is_catalog_key_only(tmp_path: Path) -> None:
    """Keine zweite Objektwelt — nur catalog_key, kein RA/Dec in Manager-DB."""
    db = tmp_path / "astro_manager.sqlite"
    ensure_manager_db(db)
    upsert_profile(catalog_key="NGC224", label="default", db_path=db)
    create_session(catalog_key="NGC224", frames_completed=10, exposure_s=30.0, db_path=db)
    summary = object_summary("NGC224", db_path=db)
    assert "ra" not in summary
    assert "dec" not in summary
    assert summary["total_integration_s"] == 300.0

    star = upsert_profile(
        catalog_key="HIP21421",
        label="ASI585 Aldebaran",
        equipment="ZWO ASI585MC Pro",
        exposure_s=3.0,
        gain=100,
        db_path=db,
    )
    assert star.catalog_key == "HIP21421"
    assert object_summary("HIP21421", db_path=db)["profile_count"] == 1


def test_create_session_snapshots_profile(tmp_path: Path) -> None:
    db = tmp_path / "astro_manager.sqlite"
    profile = upsert_profile(
        catalog_key="M31",
        label="Lumix-5s",
        equipment="Lumix S5IIX",
        exposure_s=5.0,
        gain=2.0,
        iso=640,
        frames=12,
        binning="1x1",
        db_path=db,
    )
    session = create_session(
        catalog_key="M31",
        profile_id=profile.id,
        db_path=db,
        apply_profile=True,
    )
    assert session.exposure_s == 5.0
    assert session.gain == 2.0
    assert session.iso == 640
    assert session.equipment == "Lumix S5IIX"
    assert session.frames_planned == 12
    assert session.lights_planned == 12


def test_bump_session_capture(tmp_path: Path) -> None:
    from mele.astro_manager import FRAME_TYPE_DARK, bump_session_capture, update_session

    db = tmp_path / "astro_manager.sqlite"
    session = create_session(
        catalog_key="M31",
        frames_planned=10,
        frames_completed=1,
        exposure_s=60.0,
        db_path=db,
    )
    again = bump_session_capture(session.id, frames_delta=1, db_path=db)
    assert again.frames_completed == 2
    assert again.lights_completed == 2
    assert again.integration_s == 120.0
    assert again.frames_planned == 10
    assert again.lights_planned == 10

    edited = update_session(session.id, exposure_s=5.0, gain=2.0, notes="prep", db_path=db)
    assert edited.exposure_s == 5.0
    assert edited.gain == 2.0
    assert edited.notes == "prep"
    assert edited.frames_completed == 2
    assert edited.lights_completed == 2


def test_lights_darks_session_and_paths(tmp_path: Path) -> None:
    from mele.astro_manager import (
        FRAME_TYPE_DARK,
        bump_session_capture,
        ensure_capture_dir,
        frame_type_subdir,
        normalize_frame_type,
        update_session,
    )

    db = tmp_path / "astro_manager.sqlite"
    session = create_session(
        catalog_key="M33",
        lights_planned=20,
        lights_completed=0,
        darks_planned=10,
        darks_completed=0,
        exposure_s=30.0,
        db_path=db,
    )
    assert session.lights_planned == 20
    assert session.frames_planned == 20
    assert session.darks_planned == 10
    assert session.darks_completed == 0

    lit = bump_session_capture(session.id, frames_delta=3, db_path=db)
    assert lit.lights_completed == 3
    assert lit.frames_completed == 3
    assert lit.darks_completed == 0
    assert lit.integration_s == 90.0

    dark = bump_session_capture(
        session.id, frames_delta=2, frame_type=FRAME_TYPE_DARK, db_path=db
    )
    assert dark.lights_completed == 3
    assert dark.darks_completed == 2
    assert dark.integration_s == 90.0  # nur Lights

    edited = update_session(
        session.id,
        lights_planned=25,
        darks_planned=15,
        darks_completed=5,
        db_path=db,
    )
    assert edited.lights_planned == 25
    assert edited.frames_planned == 25
    assert edited.darks_planned == 15
    assert edited.darks_completed == 5

    assert normalize_frame_type("dark") == "DARK"
    assert normalize_frame_type("LIGHTS") == "LIGHT"
    assert frame_type_subdir("DARK") == "DARKS"
    assert frame_type_subdir("LIGHT") == "LIGHTS"

    root = tmp_path / "Altair" / "2026-10-05" / "s00007"
    lights = ensure_capture_dir(root.parent, 7, frame_type="LIGHT")
    darks = ensure_capture_dir(root, 7, frame_type="DARK")
    assert lights == root / "LIGHTS"
    assert darks == root / "DARKS"
    # Bereits LIGHTS → Session-Root ableiten
    again = ensure_capture_dir(lights, 7, frame_type="DARK")
    assert again == root / "DARKS"


def test_migrate_frames_to_lights(tmp_path: Path) -> None:
    """Alte sessions mit frames_* bekommen lights_* per Migration."""
    import sqlite3

    from mele.astro_manager import SCHEMA_VERSION, get_session

    db = tmp_path / "legacy.sqlite"
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
            INSERT INTO meta(key, value) VALUES ('schema_version', '1');
            INSERT INTO sessions (
              catalog_key, profile_id, started_utc, frames_planned, frames_completed,
              exposure_s, integration_s, local_path, archive_path, archive_status,
              notes, created_utc, updated_utc
            ) VALUES (
              'M31', NULL, '2026-01-01T00:00:00+00:00', 50, 40,
              10.0, 400.0, '', '', 'local', '', '2026-01-01T00:00:00+00:00',
              '2026-01-01T00:00:00+00:00'
            );
            """
        )
        conn.commit()

    ensure_manager_db(db)
    session = get_session(1, db_path=db)
    assert session is not None
    assert session.lights_planned == 50
    assert session.lights_completed == 40
    assert session.frames_planned == 50
    assert session.frames_completed == 40
    assert session.darks_planned is None
    assert session.darks_completed == 0
    with sqlite3.connect(db) as conn:
        ver = conn.execute(
            "SELECT value FROM meta WHERE key='schema_version'"
        ).fetchone()
    assert ver is not None
    assert int(ver[0]) == SCHEMA_VERSION


def test_archive_status_fallback_and_paths(tmp_path: Path) -> None:
    db = tmp_path / "astro_manager.sqlite"
    session = create_session(
        catalog_key="M42",
        frames_completed=0,
        archive_status="bogus",
        db_path=db,
    )
    assert session.archive_status == "local"
    assert session.integration_s is None

    when = datetime(2026, 10, 2, 22, 0, 0)
    path = suggested_local_session_dir(
        "HIP97649",
        when=when,
        local_root=tmp_path / "AstroCapture",
        display_name="Altair",
        session_id=42,
    )
    assert path == tmp_path / "AstroCapture" / "Altair" / "2026-10-02" / "s00042"
    assert not path.exists()

    hip_only = suggested_local_session_dir(
        "HIP97649",
        when=when,
        local_root=tmp_path / "AstroCapture",
    )
    assert hip_only == tmp_path / "AstroCapture" / "HIP97649" / "2026-10-02"
    assert folder_slug("HIP97649", "Altair") == "Altair"
    assert folder_slug("planet:Jupiter", None) == "Jupiter"
    assert folder_slug("M31", "Andromeda") == "Andromeda"
    assert session_dir_slug(7) == "s00007"
    from mele.astro_manager import ensure_session_subdir

    assert ensure_session_subdir(r"C:\Astro\Capture\Mele\Altair\2026-10-02", 14) == Path(
        r"C:\Astro\Capture\Mele\Altair\2026-10-02\s00014"
    )
    assert ensure_session_subdir(r"C:\Astro\Capture\Mele\Altair\2026-10-02\s00014", 14) == Path(
        r"C:\Astro\Capture\Mele\Altair\2026-10-02\s00014"
    )


def test_resolve_imaging_params_override(tmp_path: Path) -> None:
    from mele.astro_manager import resolve_imaging_params

    db = tmp_path / "astro_manager.sqlite"
    profile = upsert_profile(
        catalog_key="M31",
        label="default",
        exposure_s=60.0,
        gain=100,
        frames=50,
        db_path=db,
    )
    session = create_session(
        catalog_key="M31",
        profile_id=profile.id,
        exposure_s=None,
        frames_planned=None,
        db_path=db,
    )
    base = resolve_imaging_params(profile=profile, session=session)
    assert base["exposure_s"] == 60.0
    assert base["gain"] == 100
    assert base["frames"] == 50

    overridden = resolve_imaging_params(
        profile=profile,
        session=session,
        exposure_s=6.0,
        frames=10,
    )
    assert overridden["exposure_s"] == 6.0
    assert overridden["frames"] == 10
    assert overridden["gain"] == 100
