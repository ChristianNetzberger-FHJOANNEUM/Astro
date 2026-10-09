"""Astro-Manager: Imaging-Profile, Sessions, Images (Phase 1).

Stammdaten (RA/Dec/Typ) bleiben in sky.sqlite / Tabelle dso.
User-Daten liegen bewusst in einer eigenen Datei astro_manager.sqlite,
weil `python -m mele.catalog import` sky.sqlite neu aufbaut und loescht.

Verknuepfung: catalog_key Soft-Link zur Objekt-Identitaet
(z.B. \"M31\", \"NGC224\", \"HIP21421\", \"planet:Jupiter\") — kein FK auf sky.sqlite.
Speicherpfade: local_path / archive_path / archive_status vorbereitet.
S1 (Session Storage): Lifecycle, WORK-Pfade, Transfer-Jobs, Manifest-Revision —
noch ohne produktive Copy/Delete/Archiv-Aktionen (S3–S6).
"""

from __future__ import annotations

import os
import sqlite3
import uuid
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from mele.config import REPO_ROOT, load_mele_settings
from mele.session_storage import (
    ARCHIVE_COMPLETENESS,
    ARCHIVE_COMPLETENESS_NONE,
    JOB_COMPLETENESS,
    JOB_COMPLETENESS_PARTIAL,
    LIFECYCLE_CAPTURING,
    LIFECYCLE_CLOSED,
    LIFECYCLE_OPEN,
    LIFECYCLE_STATUSES,
    TRANSFER_KINDS,
    TRANSFER_QUEUED,
    TRANSFER_STATUSES,
    WEATHER_EXPORT_NONE,
    WEATHER_EXPORT_STATUSES,
    assert_lifecycle_transition,
    normalize_archive_completeness,
    normalize_lifecycle,
    normalize_weather_export_status,
)

SCHEMA_VERSION = 3

MANAGER_SCHEMA = """
CREATE TABLE IF NOT EXISTS meta (
    key TEXT PRIMARY KEY,
    value TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS imaging_profiles (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    catalog_key TEXT NOT NULL,
    label TEXT NOT NULL,
    equipment TEXT NOT NULL DEFAULT '',
    exposure_s REAL,
    gain REAL,
    iso INTEGER,
    offset_adu INTEGER,
    binning TEXT NOT NULL DEFAULT '1x1',
    filter_name TEXT NOT NULL DEFAULT '',
    frames INTEGER NOT NULL DEFAULT 1,
    notes TEXT NOT NULL DEFAULT '',
    created_utc TEXT NOT NULL,
    updated_utc TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_profiles_key ON imaging_profiles(catalog_key);

CREATE TABLE IF NOT EXISTS sessions (
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
    gain REAL,
    iso INTEGER,
    offset_adu INTEGER,
    binning TEXT NOT NULL DEFAULT '1x1',
    filter_name TEXT NOT NULL DEFAULT '',
    equipment TEXT NOT NULL DEFAULT '',
    integration_s REAL,
    local_path TEXT NOT NULL DEFAULT '',
    archive_path TEXT NOT NULL DEFAULT '',
    archive_status TEXT NOT NULL DEFAULT 'local',
    notes TEXT NOT NULL DEFAULT '',
    created_utc TEXT NOT NULL,
    updated_utc TEXT NOT NULL,
    lifecycle_status TEXT NOT NULL DEFAULT 'open',
    session_start_utc TEXT NOT NULL DEFAULT '',
    session_end_utc TEXT,
    work_transfer_path TEXT NOT NULL DEFAULT '',
    work_local_path TEXT NOT NULL DEFAULT '',
    archive_completeness TEXT NOT NULL DEFAULT 'none',
    manifest_revision INTEGER NOT NULL DEFAULT 0,
    weather_export_status TEXT NOT NULL DEFAULT 'none',
    object_id TEXT NOT NULL DEFAULT '',
    equipment_profile_id TEXT NOT NULL DEFAULT '',
    FOREIGN KEY(profile_id) REFERENCES imaging_profiles(id) ON DELETE SET NULL
);
CREATE INDEX IF NOT EXISTS idx_sessions_key ON sessions(catalog_key);
CREATE INDEX IF NOT EXISTS idx_sessions_started ON sessions(started_utc);

CREATE TABLE IF NOT EXISTS images (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    session_id INTEGER NOT NULL,
    catalog_key TEXT NOT NULL,
    filename TEXT NOT NULL,
    local_path TEXT NOT NULL DEFAULT '',
    archive_path TEXT NOT NULL DEFAULT '',
    archive_status TEXT NOT NULL DEFAULT 'local',
    exposure_s REAL,
    captured_utc TEXT,
    image_type TEXT NOT NULL DEFAULT 'LIGHT',
    created_utc TEXT NOT NULL,
    FOREIGN KEY(session_id) REFERENCES sessions(id) ON DELETE CASCADE
);
CREATE INDEX IF NOT EXISTS idx_images_session ON images(session_id);
CREATE INDEX IF NOT EXISTS idx_images_key ON images(catalog_key);

CREATE TABLE IF NOT EXISTS transfer_jobs (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    job_id TEXT NOT NULL UNIQUE,
    session_id INTEGER NOT NULL,
    kind TEXT NOT NULL,
    source_root TEXT NOT NULL DEFAULT '',
    dest_root TEXT NOT NULL DEFAULT '',
    status TEXT NOT NULL DEFAULT 'queued',
    completeness TEXT NOT NULL DEFAULT 'partial',
    manifest_revision INTEGER NOT NULL DEFAULT 0,
    progress_files INTEGER NOT NULL DEFAULT 0,
    progress_bytes INTEGER NOT NULL DEFAULT 0,
    error TEXT NOT NULL DEFAULT '',
    manifest_path TEXT NOT NULL DEFAULT '',
    log_path TEXT NOT NULL DEFAULT '',
    started_utc TEXT,
    finished_utc TEXT,
    created_utc TEXT NOT NULL,
    updated_utc TEXT NOT NULL,
    FOREIGN KEY(session_id) REFERENCES sessions(id) ON DELETE CASCADE
);
CREATE INDEX IF NOT EXISTS idx_transfer_jobs_session ON transfer_jobs(session_id);
CREATE INDEX IF NOT EXISTS idx_transfer_jobs_status ON transfer_jobs(status);
"""

ARCHIVE_STATUSES = frozenset({"local", "pending", "archived", "missing"})
FRAME_TYPE_LIGHT = "LIGHT"
FRAME_TYPE_DARK = "DARK"


@dataclass(frozen=True)
class ImagingProfile:
    id: int
    catalog_key: str
    label: str
    equipment: str = ""
    exposure_s: float | None = None
    gain: float | None = None
    iso: int | None = None
    offset_adu: int | None = None
    binning: str = "1x1"
    filter_name: str = ""
    frames: int = 1
    notes: str = ""
    created_utc: str = ""
    updated_utc: str = ""

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class ImagingSession:
    id: int
    catalog_key: str
    profile_id: int | None = None
    started_utc: str = ""
    ended_utc: str | None = None
    frames_planned: int | None = None  # Alias: Lights (Kompatibilitaet)
    frames_completed: int = 0  # Alias: Lights
    lights_planned: int | None = None
    lights_completed: int = 0
    darks_planned: int | None = None
    darks_completed: int = 0
    exposure_s: float | None = None
    gain: float | None = None
    iso: int | None = None
    offset_adu: int | None = None
    binning: str = "1x1"
    filter_name: str = ""
    equipment: str = ""
    integration_s: float | None = None
    local_path: str = ""
    archive_path: str = ""
    archive_status: str = "local"
    notes: str = ""
    created_utc: str = ""
    updated_utc: str = ""
    # S1 Session Storage
    lifecycle_status: str = LIFECYCLE_OPEN
    session_start_utc: str = ""
    session_end_utc: str | None = None
    work_transfer_path: str = ""
    work_local_path: str = ""
    archive_completeness: str = ARCHIVE_COMPLETENESS_NONE
    manifest_revision: int = 0
    weather_export_status: str = WEATHER_EXPORT_NONE
    object_id: str = ""
    equipment_profile_id: str = ""

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class TransferJob:
    id: int
    job_id: str
    session_id: int
    kind: str
    source_root: str = ""
    dest_root: str = ""
    status: str = TRANSFER_QUEUED
    completeness: str = JOB_COMPLETENESS_PARTIAL
    manifest_revision: int = 0
    progress_files: int = 0
    progress_bytes: int = 0
    error: str = ""
    manifest_path: str = ""
    log_path: str = ""
    started_utc: str | None = None
    finished_utc: str | None = None
    created_utc: str = ""
    updated_utc: str = ""

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def default_manager_db_path() -> Path:
    return load_mele_settings().catalog_dir / "astro_manager.sqlite"


def manager_db_path(explicit: Path | None = None) -> Path:
    if explicit is not None:
        return explicit
    settings = load_mele_settings()
    configured = getattr(settings, "astro_manager_db", None)
    if configured:
        path = Path(configured)
        if not path.is_absolute():
            path = REPO_ROOT / path
        return path
    return default_manager_db_path()


def _utc_now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def ensure_manager_db(db_path: Path | None = None) -> Path:
    path = manager_db_path(db_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    with sqlite3.connect(path) as conn:
        conn.executescript(MANAGER_SCHEMA)
        row = conn.execute("SELECT value FROM meta WHERE key='schema_version'").fetchone()
        if row is None:
            conn.execute(
                "INSERT INTO meta(key, value) VALUES ('schema_version', ?)",
                (str(SCHEMA_VERSION),),
            )
        _migrate_sessions_snapshot_columns(conn)
        _migrate_sessions_light_dark_columns(conn)
        _migrate_sessions_storage_v3(conn)
        conn.commit()
    return path


def _migrate_sessions_snapshot_columns(conn: sqlite3.Connection) -> None:
    """Profil-Snapshot-Felder an bestehende sessions-Tabellen anfuegen."""
    cols = {str(r[1]) for r in conn.execute("PRAGMA table_info(sessions)").fetchall()}
    alterations = [
        ("gain", "ALTER TABLE sessions ADD COLUMN gain REAL"),
        ("iso", "ALTER TABLE sessions ADD COLUMN iso INTEGER"),
        ("offset_adu", "ALTER TABLE sessions ADD COLUMN offset_adu INTEGER"),
        ("binning", "ALTER TABLE sessions ADD COLUMN binning TEXT NOT NULL DEFAULT '1x1'"),
        ("filter_name", "ALTER TABLE sessions ADD COLUMN filter_name TEXT NOT NULL DEFAULT ''"),
        ("equipment", "ALTER TABLE sessions ADD COLUMN equipment TEXT NOT NULL DEFAULT ''"),
    ]
    for name, sql in alterations:
        if name not in cols:
            conn.execute(sql)


def _migrate_sessions_light_dark_columns(conn: sqlite3.Connection) -> None:
    """Lights/Darks-Zaehler; bestehende frames_* → lights_* uebernehmen."""
    cols = {str(r[1]) for r in conn.execute("PRAGMA table_info(sessions)").fetchall()}
    alterations = [
        ("lights_planned", "ALTER TABLE sessions ADD COLUMN lights_planned INTEGER"),
        ("lights_completed", "ALTER TABLE sessions ADD COLUMN lights_completed INTEGER NOT NULL DEFAULT 0"),
        ("darks_planned", "ALTER TABLE sessions ADD COLUMN darks_planned INTEGER"),
        ("darks_completed", "ALTER TABLE sessions ADD COLUMN darks_completed INTEGER NOT NULL DEFAULT 0"),
    ]
    added = False
    for name, sql in alterations:
        if name not in cols:
            conn.execute(sql)
            added = True
    migrated = conn.execute(
        "SELECT value FROM meta WHERE key='lights_darks_backfill'"
    ).fetchone()
    if migrated is None or added:
        conn.execute(
            """
            UPDATE sessions SET
              lights_planned = COALESCE(lights_planned, frames_planned),
              lights_completed = CASE
                WHEN COALESCE(lights_completed, 0) > 0 THEN lights_completed
                ELSE COALESCE(frames_completed, 0)
              END,
              darks_planned = COALESCE(darks_planned, NULL),
              darks_completed = COALESCE(darks_completed, 0)
            """
        )
        conn.execute(
            "INSERT OR REPLACE INTO meta(key, value) VALUES ('lights_darks_backfill', '1')"
        )
        conn.execute(
            "INSERT OR REPLACE INTO meta(key, value) VALUES ('schema_version', ?)",
            (str(SCHEMA_VERSION),),
        )


def _migrate_sessions_storage_v3(conn: sqlite3.Connection) -> None:
    """S1: Lifecycle, WORK-Pfade, Archiv-Vollstaendigkeit, Transfer-Jobs."""
    cols = {str(r[1]) for r in conn.execute("PRAGMA table_info(sessions)").fetchall()}
    alterations = [
        ("lifecycle_status", "ALTER TABLE sessions ADD COLUMN lifecycle_status TEXT NOT NULL DEFAULT 'open'"),
        ("session_start_utc", "ALTER TABLE sessions ADD COLUMN session_start_utc TEXT NOT NULL DEFAULT ''"),
        ("session_end_utc", "ALTER TABLE sessions ADD COLUMN session_end_utc TEXT"),
        ("work_transfer_path", "ALTER TABLE sessions ADD COLUMN work_transfer_path TEXT NOT NULL DEFAULT ''"),
        ("work_local_path", "ALTER TABLE sessions ADD COLUMN work_local_path TEXT NOT NULL DEFAULT ''"),
        ("archive_completeness", "ALTER TABLE sessions ADD COLUMN archive_completeness TEXT NOT NULL DEFAULT 'none'"),
        ("manifest_revision", "ALTER TABLE sessions ADD COLUMN manifest_revision INTEGER NOT NULL DEFAULT 0"),
        ("weather_export_status", "ALTER TABLE sessions ADD COLUMN weather_export_status TEXT NOT NULL DEFAULT 'none'"),
        ("object_id", "ALTER TABLE sessions ADD COLUMN object_id TEXT NOT NULL DEFAULT ''"),
        ("equipment_profile_id", "ALTER TABLE sessions ADD COLUMN equipment_profile_id TEXT NOT NULL DEFAULT ''"),
    ]
    for name, sql in alterations:
        if name not in cols:
            conn.execute(sql)

    # transfer_jobs via MANAGER_SCHEMA CREATE IF NOT EXISTS
    conn.executescript(
        """
        CREATE TABLE IF NOT EXISTS transfer_jobs (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            job_id TEXT NOT NULL UNIQUE,
            session_id INTEGER NOT NULL,
            kind TEXT NOT NULL,
            source_root TEXT NOT NULL DEFAULT '',
            dest_root TEXT NOT NULL DEFAULT '',
            status TEXT NOT NULL DEFAULT 'queued',
            completeness TEXT NOT NULL DEFAULT 'partial',
            manifest_revision INTEGER NOT NULL DEFAULT 0,
            progress_files INTEGER NOT NULL DEFAULT 0,
            progress_bytes INTEGER NOT NULL DEFAULT 0,
            error TEXT NOT NULL DEFAULT '',
            manifest_path TEXT NOT NULL DEFAULT '',
            log_path TEXT NOT NULL DEFAULT '',
            started_utc TEXT,
            finished_utc TEXT,
            created_utc TEXT NOT NULL,
            updated_utc TEXT NOT NULL,
            FOREIGN KEY(session_id) REFERENCES sessions(id) ON DELETE CASCADE
        );
        CREATE INDEX IF NOT EXISTS idx_transfer_jobs_session ON transfer_jobs(session_id);
        CREATE INDEX IF NOT EXISTS idx_transfer_jobs_status ON transfer_jobs(status);
        CREATE INDEX IF NOT EXISTS idx_sessions_lifecycle ON sessions(lifecycle_status);
        """
    )

    backfill = conn.execute(
        "SELECT value FROM meta WHERE key='storage_v3_backfill'"
    ).fetchone()
    if backfill is None:
        # sqlite3.Row ohne row_factory: Tupel-Indizes — explizit benannte SELECT-Aliase
        conn.row_factory = sqlite3.Row
        rows = conn.execute(
            """
            SELECT id, catalog_key, started_utc, ended_utc,
                   frames_completed, lights_completed
            FROM sessions
            """
        ).fetchall()
        for row in rows:
            ended = row["ended_utc"]
            lights_c = int(row["lights_completed"] or 0) if row["lights_completed"] is not None else int(
                row["frames_completed"] or 0
            )
            if ended:
                life = LIFECYCLE_CLOSED
            elif lights_c > 0:
                life = LIFECYCLE_CAPTURING
            else:
                life = LIFECYCLE_OPEN
            start = str(row["started_utc"] or "")
            end = str(ended) if ended else None
            conn.execute(
                """
                UPDATE sessions SET
                  lifecycle_status=?,
                  session_start_utc=CASE WHEN COALESCE(session_start_utc,'')='' THEN ? ELSE session_start_utc END,
                  session_end_utc=COALESCE(session_end_utc, ?),
                  object_id=CASE WHEN COALESCE(object_id,'')='' THEN catalog_key ELSE object_id END
                WHERE id=?
                """,
                (life, start, end, int(row["id"])),
            )
        conn.execute(
            "INSERT OR REPLACE INTO meta(key, value) VALUES ('storage_v3_backfill', '1')"
        )
    conn.execute(
        "INSERT OR REPLACE INTO meta(key, value) VALUES ('schema_version', ?)",
        (str(SCHEMA_VERSION),),
    )


def _connect(db_path: Path | None = None) -> sqlite3.Connection:
    path = ensure_manager_db(db_path)
    conn = sqlite3.connect(path)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    return conn


def _profile_from_row(row: sqlite3.Row) -> ImagingProfile:
    return ImagingProfile(
        id=int(row["id"]),
        catalog_key=str(row["catalog_key"]),
        label=str(row["label"]),
        equipment=str(row["equipment"] or ""),
        exposure_s=None if row["exposure_s"] is None else float(row["exposure_s"]),
        gain=None if row["gain"] is None else float(row["gain"]),
        iso=None if row["iso"] is None else int(row["iso"]),
        offset_adu=None if row["offset_adu"] is None else int(row["offset_adu"]),
        binning=str(row["binning"] or "1x1"),
        filter_name=str(row["filter_name"] or ""),
        frames=int(row["frames"] or 1),
        notes=str(row["notes"] or ""),
        created_utc=str(row["created_utc"] or ""),
        updated_utc=str(row["updated_utc"] or ""),
    )


def _session_from_row(row: sqlite3.Row) -> ImagingSession:
    keys = set(row.keys())

    def _opt_int(name: str) -> int | None:
        if name not in keys or row[name] is None:
            return None
        return int(row[name])

    def _int0(name: str) -> int:
        if name not in keys or row[name] is None:
            return 0
        return int(row[name] or 0)

    lights_planned = _opt_int("lights_planned")
    if lights_planned is None:
        lights_planned = _opt_int("frames_planned")
    lights_completed = _int0("lights_completed")
    if "lights_completed" not in keys:
        lights_completed = _int0("frames_completed")
    elif lights_completed == 0 and _int0("frames_completed") > 0 and lights_planned is None:
        # Sehr alte Zeile ohne Backfill
        lights_completed = _int0("frames_completed")

    darks_planned = _opt_int("darks_planned")
    darks_completed = _int0("darks_completed")

    return ImagingSession(
        id=int(row["id"]),
        catalog_key=str(row["catalog_key"]),
        profile_id=None if row["profile_id"] is None else int(row["profile_id"]),
        started_utc=str(row["started_utc"] or ""),
        ended_utc=None if row["ended_utc"] is None else str(row["ended_utc"]),
        frames_planned=lights_planned,
        frames_completed=lights_completed,
        lights_planned=lights_planned,
        lights_completed=lights_completed,
        darks_planned=darks_planned,
        darks_completed=darks_completed,
        exposure_s=None if row["exposure_s"] is None else float(row["exposure_s"]),
        gain=None if "gain" not in keys or row["gain"] is None else float(row["gain"]),
        iso=None if "iso" not in keys or row["iso"] is None else int(row["iso"]),
        offset_adu=None if "offset_adu" not in keys or row["offset_adu"] is None else int(row["offset_adu"]),
        binning=str(row["binning"] if "binning" in keys and row["binning"] is not None else "1x1"),
        filter_name=str(row["filter_name"] if "filter_name" in keys and row["filter_name"] else ""),
        equipment=str(row["equipment"] if "equipment" in keys and row["equipment"] else ""),
        integration_s=None if row["integration_s"] is None else float(row["integration_s"]),
        local_path=str(row["local_path"] or ""),
        archive_path=str(row["archive_path"] or ""),
        archive_status=str(row["archive_status"] or "local"),
        notes=str(row["notes"] or ""),
        created_utc=str(row["created_utc"] or ""),
        updated_utc=str(row["updated_utc"] or ""),
        lifecycle_status=normalize_lifecycle(
            str(row["lifecycle_status"]) if "lifecycle_status" in keys and row["lifecycle_status"] else LIFECYCLE_OPEN
        ),
        session_start_utc=str(
            row["session_start_utc"]
            if "session_start_utc" in keys and row["session_start_utc"]
            else (row["started_utc"] or "")
        ),
        session_end_utc=(
            None
            if "session_end_utc" not in keys or row["session_end_utc"] is None
            else str(row["session_end_utc"])
        ),
        work_transfer_path=str(
            row["work_transfer_path"] if "work_transfer_path" in keys and row["work_transfer_path"] else ""
        ),
        work_local_path=str(
            row["work_local_path"] if "work_local_path" in keys and row["work_local_path"] else ""
        ),
        archive_completeness=normalize_archive_completeness(
            str(row["archive_completeness"])
            if "archive_completeness" in keys and row["archive_completeness"]
            else ARCHIVE_COMPLETENESS_NONE
        ),
        manifest_revision=int(row["manifest_revision"] or 0) if "manifest_revision" in keys else 0,
        weather_export_status=normalize_weather_export_status(
            str(row["weather_export_status"])
            if "weather_export_status" in keys and row["weather_export_status"]
            else WEATHER_EXPORT_NONE
        ),
        object_id=str(
            row["object_id"]
            if "object_id" in keys and row["object_id"]
            else row["catalog_key"]
        ),
        equipment_profile_id=str(
            row["equipment_profile_id"]
            if "equipment_profile_id" in keys and row["equipment_profile_id"]
            else ""
        ),
    )


def list_profiles(catalog_key: str, *, db_path: Path | None = None) -> list[ImagingProfile]:
    key = str(catalog_key or "").strip()
    if not key:
        return []
    with _connect(db_path) as conn:
        rows = conn.execute(
            "SELECT * FROM imaging_profiles WHERE catalog_key=? ORDER BY label COLLATE NOCASE",
            (key,),
        ).fetchall()
    return [_profile_from_row(r) for r in rows]


def get_profile(profile_id: int, *, db_path: Path | None = None) -> ImagingProfile | None:
    with _connect(db_path) as conn:
        row = conn.execute(
            "SELECT * FROM imaging_profiles WHERE id=?",
            (int(profile_id),),
        ).fetchone()
    return None if row is None else _profile_from_row(row)


def upsert_profile(
    *,
    catalog_key: str,
    label: str,
    profile_id: int | None = None,
    equipment: str = "",
    exposure_s: float | None = None,
    gain: float | None = None,
    iso: int | None = None,
    offset_adu: int | None = None,
    binning: str = "1x1",
    filter_name: str = "",
    frames: int = 1,
    notes: str = "",
    db_path: Path | None = None,
) -> ImagingProfile:
    key = str(catalog_key or "").strip()
    nice = str(label or "").strip()
    if not key:
        raise ValueError("catalog_key fehlt")
    if not nice:
        raise ValueError("label fehlt")
    now = _utc_now()
    frames_i = max(1, int(frames or 1))
    with _connect(db_path) as conn:
        if profile_id is not None:
            existing = conn.execute(
                "SELECT id FROM imaging_profiles WHERE id=?",
                (int(profile_id),),
            ).fetchone()
            if existing is None:
                raise ValueError(f"Unbekanntes Profil: {profile_id}")
            conn.execute(
                """
                UPDATE imaging_profiles SET
                  catalog_key=?, label=?, equipment=?, exposure_s=?, gain=?, iso=?,
                  offset_adu=?, binning=?, filter_name=?, frames=?, notes=?, updated_utc=?
                WHERE id=?
                """,
                (
                    key,
                    nice,
                    str(equipment or ""),
                    exposure_s,
                    gain,
                    iso,
                    offset_adu,
                    str(binning or "1x1"),
                    str(filter_name or ""),
                    frames_i,
                    str(notes or ""),
                    now,
                    int(profile_id),
                ),
            )
            pid = int(profile_id)
        else:
            cur = conn.execute(
                """
                INSERT INTO imaging_profiles (
                  catalog_key, label, equipment, exposure_s, gain, iso, offset_adu,
                  binning, filter_name, frames, notes, created_utc, updated_utc
                ) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)
                """,
                (
                    key,
                    nice,
                    str(equipment or ""),
                    exposure_s,
                    gain,
                    iso,
                    offset_adu,
                    str(binning or "1x1"),
                    str(filter_name or ""),
                    frames_i,
                    str(notes or ""),
                    now,
                    now,
                ),
            )
            pid = int(cur.lastrowid)
        conn.commit()
    profile = get_profile(pid, db_path=db_path)
    assert profile is not None
    return profile


def delete_profile(profile_id: int, *, db_path: Path | None = None) -> bool:
    with _connect(db_path) as conn:
        cur = conn.execute("DELETE FROM imaging_profiles WHERE id=?", (int(profile_id),))
        conn.commit()
        return cur.rowcount > 0


def list_sessions(catalog_key: str, *, db_path: Path | None = None) -> list[ImagingSession]:
    key = str(catalog_key or "").strip()
    if not key:
        return []
    with _connect(db_path) as conn:
        rows = conn.execute(
            "SELECT * FROM sessions WHERE catalog_key=? ORDER BY started_utc DESC, id DESC",
            (key,),
        ).fetchall()
    return [_session_from_row(r) for r in rows]


def create_session(
    *,
    catalog_key: str,
    profile_id: int | None = None,
    started_utc: str | None = None,
    frames_planned: int | None = None,
    frames_completed: int = 0,
    lights_planned: int | None = None,
    lights_completed: int | None = None,
    darks_planned: int | None = None,
    darks_completed: int = 0,
    exposure_s: float | None = None,
    gain: float | None = None,
    iso: int | None = None,
    offset_adu: int | None = None,
    binning: str = "",
    filter_name: str = "",
    equipment: str = "",
    local_path: str = "",
    archive_path: str = "",
    archive_status: str = "local",
    notes: str = "",
    db_path: Path | None = None,
    apply_profile: bool = True,
) -> ImagingSession:
    key = str(catalog_key or "").strip()
    if not key:
        raise ValueError("catalog_key fehlt")
    status = str(archive_status or "local").strip().lower()
    if status not in ARCHIVE_STATUSES:
        status = "local"
    now = _utc_now()
    started = (started_utc or now).strip() or now

    lights_p = lights_planned if lights_planned is not None else frames_planned
    lights_c = lights_completed if lights_completed is not None else frames_completed
    lights_c = max(0, int(lights_c or 0))
    lights_p = None if lights_p is None else max(0, int(lights_p))
    darks_p = None if darks_planned is None else max(0, int(darks_planned))
    darks_c = max(0, int(darks_completed or 0))

    # Bei neuer Session: fehlende Felder aus Profil uebernehmen (Snapshot)
    if apply_profile and profile_id is not None:
        profile = get_profile(int(profile_id), db_path=db_path)
        if profile is None:
            raise ValueError(f"Unbekanntes Profil: {profile_id}")
        if exposure_s is None:
            exposure_s = profile.exposure_s
        if gain is None:
            gain = profile.gain
        if iso is None:
            iso = profile.iso
        if offset_adu is None:
            offset_adu = profile.offset_adu
        if not str(binning or "").strip():
            binning = profile.binning or "1x1"
        if not str(filter_name or "").strip():
            filter_name = profile.filter_name
        if not str(equipment or "").strip():
            equipment = profile.equipment
        if lights_p is None:
            lights_p = profile.frames

    binning = str(binning or "1x1")

    integration = None
    if exposure_s is not None and lights_c > 0:
        integration = float(exposure_s) * lights_c
    with _connect(db_path) as conn:
        if profile_id is not None:
            exists = conn.execute(
                "SELECT id FROM imaging_profiles WHERE id=?",
                (int(profile_id),),
            ).fetchone()
            if exists is None:
                raise ValueError(f"Unbekanntes Profil: {profile_id}")
        life = LIFECYCLE_CAPTURING if lights_c > 0 else LIFECYCLE_OPEN
        cur = conn.execute(
            """
            INSERT INTO sessions (
              catalog_key, profile_id, started_utc, ended_utc,
              frames_planned, frames_completed,
              lights_planned, lights_completed, darks_planned, darks_completed,
              exposure_s, gain, iso, offset_adu, binning,
              filter_name, equipment, integration_s, local_path, archive_path,
              archive_status, notes, created_utc, updated_utc,
              lifecycle_status, session_start_utc, session_end_utc,
              work_transfer_path, work_local_path, archive_completeness,
              manifest_revision, weather_export_status, object_id, equipment_profile_id
            ) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
            """,
            (
                key,
                None if profile_id is None else int(profile_id),
                started,
                None,
                lights_p,
                lights_c,
                lights_p,
                lights_c,
                darks_p,
                darks_c,
                exposure_s,
                gain,
                iso,
                offset_adu,
                str(binning or "1x1"),
                str(filter_name or ""),
                str(equipment or ""),
                integration,
                str(local_path or ""),
                str(archive_path or ""),
                status,
                str(notes or ""),
                now,
                now,
                life,
                started,
                None,
                "",
                "",
                ARCHIVE_COMPLETENESS_NONE,
                0,
                WEATHER_EXPORT_NONE,
                key,
                "",
            ),
        )
        sid = int(cur.lastrowid)
        conn.commit()
        row = conn.execute("SELECT * FROM sessions WHERE id=?", (sid,)).fetchone()
    assert row is not None
    return _session_from_row(row)


def get_session(session_id: int, *, db_path: Path | None = None) -> ImagingSession | None:
    with _connect(db_path) as conn:
        row = conn.execute(
            "SELECT * FROM sessions WHERE id=?",
            (int(session_id),),
        ).fetchone()
    return None if row is None else _session_from_row(row)


def update_session(
    session_id: int,
    *,
    profile_id: int | None = None,
    frames_planned: int | None = None,
    frames_completed: int | None = None,
    lights_planned: int | None = None,
    lights_completed: int | None = None,
    darks_planned: int | None = None,
    darks_completed: int | None = None,
    exposure_s: float | None = None,
    gain: float | None = None,
    iso: int | None = None,
    offset_adu: int | None = None,
    binning: str | None = None,
    filter_name: str | None = None,
    equipment: str | None = None,
    local_path: str | None = None,
    archive_path: str | None = None,
    archive_status: str | None = None,
    notes: str | None = None,
    db_path: Path | None = None,
) -> ImagingSession:
    """Session-Parameter aktualisieren (Vorbereitung / Feintuning vor Capture)."""
    now = _utc_now()
    with _connect(db_path) as conn:
        row = conn.execute("SELECT * FROM sessions WHERE id=?", (int(session_id),)).fetchone()
        if row is None:
            raise ValueError(f"Unbekannte Session: {session_id}")

        def _pick(new: object, old: object) -> object:
            return old if new is None else new

        keys = set(row.keys())
        pid = row["profile_id"] if profile_id is None else profile_id
        if pid is not None:
            exists = conn.execute(
                "SELECT id FROM imaging_profiles WHERE id=?",
                (int(pid),),
            ).fetchone()
            if exists is None:
                raise ValueError(f"Unbekanntes Profil: {pid}")

        # Lights: neues Feld > frames_* Alias > DB
        lights_p_in = lights_planned if lights_planned is not None else frames_planned
        lights_c_in = lights_completed if lights_completed is not None else frames_completed
        old_lights_p = row["lights_planned"] if "lights_planned" in keys else row["frames_planned"]
        old_lights_c = (
            int(row["lights_completed"] or 0)
            if "lights_completed" in keys
            else int(row["frames_completed"] or 0)
        )
        lights_p = _pick(lights_p_in, old_lights_p)
        if lights_p is not None:
            lights_p = max(0, int(lights_p))
        lights_c = old_lights_c if lights_c_in is None else max(0, int(lights_c_in))

        old_darks_p = row["darks_planned"] if "darks_planned" in keys else None
        old_darks_c = int(row["darks_completed"] or 0) if "darks_completed" in keys else 0
        darks_p = _pick(darks_planned, old_darks_p)
        if darks_p is not None:
            darks_p = max(0, int(darks_p))
        darks_c = old_darks_c if darks_completed is None else max(0, int(darks_completed))

        exp = _pick(exposure_s, row["exposure_s"])
        if exp is not None:
            exp = float(exp)
        g = _pick(gain, row["gain"] if "gain" in keys else None)
        if g is not None:
            g = float(g)
        iso_v = _pick(iso, row["iso"] if "iso" in keys else None)
        if iso_v is not None:
            iso_v = int(iso_v)
        off = _pick(offset_adu, row["offset_adu"] if "offset_adu" in keys else None)
        if off is not None:
            off = int(off)
        binn = str(_pick(binning, row["binning"] if "binning" in keys else "1x1") or "1x1")
        filt = str(_pick(filter_name, row["filter_name"] if "filter_name" in keys else "") or "")
        equip = str(_pick(equipment, row["equipment"] if "equipment" in keys else "") or "")
        local = str(_pick(local_path, row["local_path"]) or "")
        arch = str(_pick(archive_path, row["archive_path"]) or "")
        status = str(_pick(archive_status, row["archive_status"]) or "local").lower()
        if status not in ARCHIVE_STATUSES:
            status = "local"
        note = str(_pick(notes, row["notes"]) or "")
        integration = None if exp is None else float(exp) * lights_c

        conn.execute(
            """
            UPDATE sessions SET
              profile_id=?,
              frames_planned=?, frames_completed=?,
              lights_planned=?, lights_completed=?,
              darks_planned=?, darks_completed=?,
              exposure_s=?,
              gain=?, iso=?, offset_adu=?, binning=?, filter_name=?, equipment=?,
              integration_s=?, local_path=?, archive_path=?, archive_status=?,
              notes=?, updated_utc=?
            WHERE id=?
            """,
            (
                None if pid is None else int(pid),
                lights_p,
                lights_c,
                lights_p,
                lights_c,
                darks_p,
                darks_c,
                exp,
                g,
                iso_v,
                off,
                binn,
                filt,
                equip,
                integration,
                local,
                arch,
                status,
                note,
                now,
                int(session_id),
            ),
        )
        conn.commit()
        updated = conn.execute("SELECT * FROM sessions WHERE id=?", (int(session_id),)).fetchone()
    assert updated is not None
    return _session_from_row(updated)


def bump_session_capture(
    session_id: int,
    *,
    frames_delta: int = 1,
    frame_type: str = FRAME_TYPE_LIGHT,
    db_path: Path | None = None,
) -> ImagingSession:
    """Ein weiteres Frame (LIGHT oder DARK) an bestehende Session anrechnen."""
    delta = max(1, int(frames_delta))
    kind = normalize_frame_type(frame_type)
    now = _utc_now()
    with _connect(db_path) as conn:
        row = conn.execute("SELECT * FROM sessions WHERE id=?", (int(session_id),)).fetchone()
        if row is None:
            raise ValueError(f"Unbekannte Session: {session_id}")
        keys = set(row.keys())

        lights_c = (
            int(row["lights_completed"] or 0)
            if "lights_completed" in keys
            else int(row["frames_completed"] or 0)
        )
        lights_p = row["lights_planned"] if "lights_planned" in keys else row["frames_planned"]
        darks_c = int(row["darks_completed"] or 0) if "darks_completed" in keys else 0
        darks_p = row["darks_planned"] if "darks_planned" in keys else None

        if kind == FRAME_TYPE_DARK:
            darks_c = darks_c + delta
            if darks_p is not None:
                darks_p = max(int(darks_p), darks_c)
        else:
            lights_c = lights_c + delta
            if lights_p is not None:
                lights_p = max(int(lights_p), lights_c)

        exposure = None if row["exposure_s"] is None else float(row["exposure_s"])
        integration = None if exposure is None else exposure * lights_c
        life = (
            str(row["lifecycle_status"])
            if "lifecycle_status" in keys and row["lifecycle_status"]
            else LIFECYCLE_OPEN
        )
        if normalize_lifecycle(life) == LIFECYCLE_OPEN:
            life = LIFECYCLE_CAPTURING
        conn.execute(
            """
            UPDATE sessions SET
              frames_completed=?, frames_planned=?,
              lights_completed=?, lights_planned=?,
              darks_completed=?, darks_planned=?,
              integration_s=?, lifecycle_status=?, updated_utc=?
            WHERE id=?
            """,
            (
                lights_c,
                lights_p,
                lights_c,
                lights_p,
                darks_c,
                darks_p,
                integration,
                normalize_lifecycle(life),
                now,
                int(session_id),
            ),
        )
        conn.commit()
        updated = conn.execute("SELECT * FROM sessions WHERE id=?", (int(session_id),)).fetchone()
    assert updated is not None
    return _session_from_row(updated)


def delete_session(session_id: int, *, db_path: Path | None = None) -> bool:
    with _connect(db_path) as conn:
        cur = conn.execute("DELETE FROM sessions WHERE id=?", (int(session_id),))
        conn.commit()
        return cur.rowcount > 0


def object_summary(catalog_key: str, *, db_path: Path | None = None) -> dict[str, Any]:
    """Profile + Sessions + Integrationssumme fuer ein Katalogobjekt."""
    key = str(catalog_key or "").strip()
    profiles = list_profiles(key, db_path=db_path)
    sessions = list_sessions(key, db_path=db_path)
    total_integration_s = 0.0
    for session in sessions:
        if session.integration_s is not None:
            total_integration_s += float(session.integration_s)
        elif session.exposure_s is not None and session.frames_completed:
            total_integration_s += float(session.exposure_s) * int(session.frames_completed)
    return {
        "catalog_key": key,
        "profiles": [p.to_dict() for p in profiles],
        "sessions": [s.to_dict() for s in sessions],
        "total_integration_s": round(total_integration_s, 1),
        "session_count": len(sessions),
        "profile_count": len(profiles),
    }


def session_dir_slug(session_id: int) -> str:
    """Unterordner pro Session, z.B. s00042 — fuer Stacking/Nachvollziehbarkeit."""
    return f"s{int(session_id):05d}"


def normalize_frame_type(frame_type: str | None) -> str:
    """NINA image_type: LIGHT | DARK (spaeter FLAT/BIAS)."""
    raw = str(frame_type or FRAME_TYPE_LIGHT).strip().upper()
    if raw in ("DARK", "DARKS"):
        return FRAME_TYPE_DARK
    return FRAME_TYPE_LIGHT


def frame_type_subdir(frame_type: str | None) -> str:
    """Unterordner unter s#####/: LIGHTS oder DARKS."""
    return "DARKS" if normalize_frame_type(frame_type) == FRAME_TYPE_DARK else "LIGHTS"


def ensure_session_subdir(path: str | Path, session_id: int) -> Path:
    """Haengt s##### an, falls der Pfad noch keine Session-Ebene hat."""
    p = Path(str(path or "").strip())
    slug = session_dir_slug(session_id)
    if p.name.lower() == slug.lower():
        return p
    if any(part.lower() == slug.lower() for part in p.parts):
        return p
    return p / slug


def ensure_capture_dir(
    path: str | Path,
    session_id: int,
    *,
    frame_type: str = FRAME_TYPE_LIGHT,
) -> Path:
    """Session-Root …/s#####/ plus Frame-Typ-Unterordner LIGHTS|DARKS."""
    session_root = ensure_session_subdir(path, session_id)
    # Wenn Aufrufer schon …/LIGHTS oder …/DARKS uebergibt: Session-Root ableiten
    name = session_root.name.upper()
    if name in ("LIGHTS", "DARKS", "FLATS", "BIAS"):
        session_root = session_root.parent
        session_root = ensure_session_subdir(session_root, session_id)
    return session_root / frame_type_subdir(frame_type)


def resolve_imaging_params(
    *,
    profile: ImagingProfile | None = None,
    session: ImagingSession | None = None,
    exposure_s: float | None = None,
    gain: float | None = None,
    iso: int | None = None,
    frames: int | None = None,
) -> dict[str, Any]:
    """Explicit > Session-Snapshot > Profil. Session speichert Profilkopie bei Anlage."""
    exp = exposure_s
    if exp is None and session is not None:
        exp = session.exposure_s
    if exp is None and profile is not None:
        exp = profile.exposure_s

    g = gain
    if g is None and session is not None:
        g = session.gain
    if g is None and profile is not None:
        g = profile.gain
    if g is None and session is not None and session.iso is not None:
        g = float(session.iso)
    if g is None and profile is not None and profile.iso is not None:
        g = float(profile.iso)
    if g is None and iso is not None:
        g = float(iso)

    fr = frames
    if fr is None and session is not None:
        if session.lights_planned is not None:
            fr = session.lights_planned
        elif session.frames_planned is not None:
            fr = session.frames_planned
    if fr is None and profile is not None:
        fr = profile.frames
    if fr is None:
        fr = 1

    return {
        "exposure_s": exp,
        "gain": g,
        "frames": max(1, int(fr)),
        "profile_id": (
            session.profile_id if session is not None and session.profile_id is not None
            else (None if profile is None else profile.id)
        ),
        "equipment": (
            (session.equipment if session and session.equipment else "")
            or ("" if profile is None else profile.equipment)
        ),
        "binning": (
            (session.binning if session and session.binning else "")
            or ("" if profile is None else profile.binning)
            or "1x1"
        ),
        "filter_name": (
            (session.filter_name if session and session.filter_name else "")
            or ("" if profile is None else profile.filter_name)
        ),
        "iso": (
            session.iso if session is not None and session.iso is not None
            else (None if profile is None else profile.iso)
        ),
    }


def folder_slug(catalog_key: str, display_name: str | None = None) -> str:
    """Ordnername: Anzeigename wenn vorhanden (Altair), sonst catalog_key (HIP…/M31)."""
    key = (catalog_key or "").strip() or "object"
    name = (display_name or "").strip()
    raw = name if name else key
    if ":" in raw:
        prefix, rest = raw.split(":", 1)
        if prefix.lower() in {"planet", "moon", "sun", "star"}:
            raw = (rest or key).strip()
    safe = "".join(ch if ch.isalnum() or ch in "-_" else "_" for ch in raw)
    return safe.strip("_") or "object"


def suggested_local_session_dir(
    catalog_key: str,
    *,
    when: datetime | None = None,
    local_root: Path | None = None,
    display_name: str | None = None,
    session_id: int | None = None,
) -> Path:
    """{root}/{Name}/{YYYY-MM-DD}/[s00042]/ — Session-ID-Ebene optional."""
    settings = load_mele_settings()
    root = local_root or Path(
        getattr(settings, "local_capture_root", None) or r"C:\Astro\Capture\Mele"
    )
    stamp = when or datetime.now().astimezone()
    path = root / folder_slug(catalog_key, display_name) / stamp.strftime("%Y-%m-%d")
    if session_id is not None:
        path = path / session_dir_slug(session_id)
    return path


def suggested_archive_session_dir(
    catalog_key: str,
    *,
    when: datetime | None = None,
    archive_root: Path | None = None,
    display_name: str | None = None,
    session_id: int | None = None,
) -> Path:
    settings = load_mele_settings()
    root = archive_root or Path(
        getattr(settings, "archive_root", None) or r"\\NAS\Astro\Capture\Mele"
    )
    stamp = when or datetime.now().astimezone()
    path = root / folder_slug(catalog_key, display_name) / stamp.strftime("%Y-%m-%d")
    if session_id is not None:
        path = path / session_dir_slug(session_id)
    return path


def _norm_fs_path(path: Path | str) -> str:
    """Vergleichbare UNC/Pfad-Form (ohne trailing separator)."""
    text = str(path or "").replace("/", "\\").strip()
    while text.endswith("\\") and text not in ("\\", "\\\\"):
        text = text[:-1]
    return text.lower()


def path_under_root(path: Path | str, root: Path | str) -> bool:
    """True wenn path gleich root oder darunter liegt (UNC-tauglich)."""
    a = _norm_fs_path(path)
    b = _norm_fs_path(root)
    if not a or not b:
        return False
    return a == b or a.startswith(b + "\\")


def resolve_archive_session_dir(
    session: ImagingSession,
    *,
    archive_root: Path | None = None,
    when: datetime | None = None,
    display_name: str | None = None,
) -> Path:
    """Kanonischer ARCHIVE-Pfad unter aktuellem archive_root.

    Alte DB-Werte unter veraltetem Root (z.B. \\\\NAS\\\\…) werden ignoriert.
    """
    settings = load_mele_settings()
    root = Path(archive_root if archive_root is not None else settings.archive_root)
    stamp = when
    if stamp is None:
        try:
            if session.started_utc:
                stamp = datetime.fromisoformat(str(session.started_utc).replace("Z", "+00:00"))
        except ValueError:
            stamp = None
    canonical = suggested_archive_session_dir(
        session.catalog_key,
        when=stamp,
        archive_root=root,
        display_name=display_name,
        session_id=session.id,
    )
    existing = str(getattr(session, "archive_path", "") or "").strip()
    if existing and path_under_root(existing, root):
        return ensure_session_subdir(existing, session.id)
    return canonical


def update_session_paths(
    session_id: int,
    *,
    local_path: str = "",
    archive_path: str = "",
    notes: str | None = None,
    db_path: Path | None = None,
) -> ImagingSession:
    now = _utc_now()
    with _connect(db_path) as conn:
        row = conn.execute("SELECT * FROM sessions WHERE id=?", (int(session_id),)).fetchone()
        if row is None:
            raise ValueError(f"Unbekannte Session: {session_id}")
        note_val = str(row["notes"] or "") if notes is None else str(notes)
        conn.execute(
            """
            UPDATE sessions SET local_path=?, archive_path=?, notes=?, updated_utc=?
            WHERE id=?
            """,
            (str(local_path or ""), str(archive_path or ""), note_val, now, int(session_id)),
        )
        conn.commit()
        updated = conn.execute("SELECT * FROM sessions WHERE id=?", (int(session_id),)).fetchone()
    assert updated is not None
    return _session_from_row(updated)


def set_session_lifecycle(
    session_id: int,
    target: str,
    *,
    session_end_utc: str | None = None,
    db_path: Path | None = None,
) -> ImagingSession:
    """Lifecycle setzen (S1). NINA-Idle-Check gehoert zur spaeteren Close-UI — hier nur State-Machine."""
    tgt = normalize_lifecycle(target)
    if tgt not in LIFECYCLE_STATUSES:
        raise ValueError(f"Ungueltiger lifecycle_status: {target}")
    now = _utc_now()
    with _connect(db_path) as conn:
        row = conn.execute("SELECT * FROM sessions WHERE id=?", (int(session_id),)).fetchone()
        if row is None:
            raise ValueError(f"Unbekannte Session: {session_id}")
        keys = set(row.keys())
        current = normalize_lifecycle(
            str(row["lifecycle_status"]) if "lifecycle_status" in keys and row["lifecycle_status"] else LIFECYCLE_OPEN
        )
        assert_lifecycle_transition(current, tgt)
        end_val = row["session_end_utc"] if "session_end_utc" in keys else None
        if tgt == LIFECYCLE_CLOSED:
            end_val = session_end_utc or end_val or row["ended_utc"] or now
            conn.execute(
                """
                UPDATE sessions SET
                  lifecycle_status=?, session_end_utc=?, ended_utc=COALESCE(ended_utc, ?),
                  updated_utc=?
                WHERE id=?
                """,
                (tgt, end_val, end_val, now, int(session_id)),
            )
        else:
            conn.execute(
                """
                UPDATE sessions SET lifecycle_status=?, updated_utc=?
                WHERE id=?
                """,
                (tgt, now, int(session_id)),
            )
        conn.commit()
        updated = conn.execute("SELECT * FROM sessions WHERE id=?", (int(session_id),)).fetchone()
    assert updated is not None
    return _session_from_row(updated)


def update_session_storage_fields(
    session_id: int,
    *,
    work_transfer_path: str | None = None,
    work_local_path: str | None = None,
    archive_completeness: str | None = None,
    manifest_revision: int | None = None,
    weather_export_status: str | None = None,
    object_id: str | None = None,
    equipment_profile_id: str | None = None,
    db_path: Path | None = None,
) -> ImagingSession:
    """S1-Metadaten ohne Copy/Delete. None = Feld unveraendert."""
    now = _utc_now()
    with _connect(db_path) as conn:
        row = conn.execute("SELECT * FROM sessions WHERE id=?", (int(session_id),)).fetchone()
        if row is None:
            raise ValueError(f"Unbekannte Session: {session_id}")
        keys = set(row.keys())

        def _keep(name: str, default: str = "") -> str:
            return str(row[name] if name in keys and row[name] is not None else default)

        w_xfer = _keep("work_transfer_path") if work_transfer_path is None else str(work_transfer_path)
        w_local = _keep("work_local_path") if work_local_path is None else str(work_local_path)
        a_comp = (
            normalize_archive_completeness(_keep("archive_completeness", ARCHIVE_COMPLETENESS_NONE))
            if archive_completeness is None
            else normalize_archive_completeness(archive_completeness)
        )
        if a_comp not in ARCHIVE_COMPLETENESS:
            a_comp = ARCHIVE_COMPLETENESS_NONE
        rev = (
            int(row["manifest_revision"] or 0)
            if manifest_revision is None and "manifest_revision" in keys
            else (0 if manifest_revision is None else max(0, int(manifest_revision)))
        )
        w_exp = (
            normalize_weather_export_status(_keep("weather_export_status", WEATHER_EXPORT_NONE))
            if weather_export_status is None
            else normalize_weather_export_status(weather_export_status)
        )
        if w_exp not in WEATHER_EXPORT_STATUSES:
            w_exp = WEATHER_EXPORT_NONE
        obj = _keep("object_id", str(row["catalog_key"])) if object_id is None else str(object_id)
        equip = _keep("equipment_profile_id") if equipment_profile_id is None else str(equipment_profile_id)
        conn.execute(
            """
            UPDATE sessions SET
              work_transfer_path=?, work_local_path=?,
              archive_completeness=?, manifest_revision=?,
              weather_export_status=?, object_id=?, equipment_profile_id=?,
              updated_utc=?
            WHERE id=?
            """,
            (w_xfer, w_local, a_comp, rev, w_exp, obj, equip, now, int(session_id)),
        )
        conn.commit()
        updated = conn.execute("SELECT * FROM sessions WHERE id=?", (int(session_id),)).fetchone()
    assert updated is not None
    return _session_from_row(updated)


def _transfer_job_from_row(row: sqlite3.Row) -> TransferJob:
    return TransferJob(
        id=int(row["id"]),
        job_id=str(row["job_id"]),
        session_id=int(row["session_id"]),
        kind=str(row["kind"]),
        source_root=str(row["source_root"] or ""),
        dest_root=str(row["dest_root"] or ""),
        status=str(row["status"] or TRANSFER_QUEUED),
        completeness=str(row["completeness"] or JOB_COMPLETENESS_PARTIAL),
        manifest_revision=int(row["manifest_revision"] or 0),
        progress_files=int(row["progress_files"] or 0),
        progress_bytes=int(row["progress_bytes"] or 0),
        error=str(row["error"] or ""),
        manifest_path=str(row["manifest_path"] or ""),
        log_path=str(row["log_path"] or ""),
        started_utc=None if row["started_utc"] is None else str(row["started_utc"]),
        finished_utc=None if row["finished_utc"] is None else str(row["finished_utc"]),
        created_utc=str(row["created_utc"] or ""),
        updated_utc=str(row["updated_utc"] or ""),
    )


def create_transfer_job(
    *,
    session_id: int,
    kind: str,
    source_root: str = "",
    dest_root: str = "",
    completeness: str = JOB_COMPLETENESS_PARTIAL,
    manifest_revision: int = 0,
    job_id: str | None = None,
    db_path: Path | None = None,
) -> TransferJob:
    """Persistenter Transfer-Job anlegen — ohne Dateien zu kopieren (S1)."""
    kind_n = str(kind or "").strip()
    if kind_n not in TRANSFER_KINDS:
        raise ValueError(f"Ungueltiger Transfer-Kind: {kind}")
    comp = completeness if completeness in JOB_COMPLETENESS else JOB_COMPLETENESS_PARTIAL
    jid = (job_id or "").strip() or str(uuid.uuid4())
    now = _utc_now()
    with _connect(db_path) as conn:
        session = conn.execute("SELECT id FROM sessions WHERE id=?", (int(session_id),)).fetchone()
        if session is None:
            raise ValueError(f"Unbekannte Session: {session_id}")
        active = conn.execute(
            """
            SELECT id FROM transfer_jobs
            WHERE session_id=? AND kind=? AND status IN ('queued','copying','verifying')
            LIMIT 1
            """,
            (int(session_id), kind_n),
        ).fetchone()
        if active is not None:
            raise ValueError(
                f"Aktiver Transfer-Job existiert bereits fuer Session {session_id} / {kind_n}"
            )
        cur = conn.execute(
            """
            INSERT INTO transfer_jobs (
              job_id, session_id, kind, source_root, dest_root, status, completeness,
              manifest_revision, progress_files, progress_bytes, error,
              manifest_path, log_path, started_utc, finished_utc, created_utc, updated_utc
            ) VALUES (?,?,?,?,?,?,?,?,0,0,'','','',NULL,NULL,?,?)
            """,
            (
                jid,
                int(session_id),
                kind_n,
                str(source_root or ""),
                str(dest_root or ""),
                TRANSFER_QUEUED,
                comp,
                max(0, int(manifest_revision)),
                now,
                now,
            ),
        )
        rid = int(cur.lastrowid)
        conn.commit()
        row = conn.execute("SELECT * FROM transfer_jobs WHERE id=?", (rid,)).fetchone()
    assert row is not None
    return _transfer_job_from_row(row)


def get_transfer_job(job_id: str, *, db_path: Path | None = None) -> TransferJob | None:
    with _connect(db_path) as conn:
        row = conn.execute(
            "SELECT * FROM transfer_jobs WHERE job_id=?",
            (str(job_id),),
        ).fetchone()
    return None if row is None else _transfer_job_from_row(row)


def list_transfer_jobs(
    session_id: int,
    *,
    db_path: Path | None = None,
) -> list[TransferJob]:
    with _connect(db_path) as conn:
        rows = conn.execute(
            """
            SELECT * FROM transfer_jobs
            WHERE session_id=?
            ORDER BY id DESC
            """,
            (int(session_id),),
        ).fetchall()
    return [_transfer_job_from_row(r) for r in rows]


def update_transfer_job_status(
    job_id: str,
    *,
    status: str,
    error: str | None = None,
    progress_files: int | None = None,
    progress_bytes: int | None = None,
    manifest_path: str | None = None,
    log_path: str | None = None,
    db_path: Path | None = None,
) -> TransferJob:
    status_n = str(status or "").strip().lower()
    if status_n not in TRANSFER_STATUSES:
        raise ValueError(f"Ungueltiger Transfer-Status: {status}")
    now = _utc_now()
    with _connect(db_path) as conn:
        row = conn.execute(
            "SELECT * FROM transfer_jobs WHERE job_id=?",
            (str(job_id),),
        ).fetchone()
        if row is None:
            raise ValueError(f"Unbekannter Transfer-Job: {job_id}")
        started = row["started_utc"]
        finished = row["finished_utc"]
        if status_n in ("copying", "verifying") and not started:
            started = now
        if status_n in ("completed", "failed"):
            finished = now
        conn.execute(
            """
            UPDATE transfer_jobs SET
              status=?,
              error=?,
              progress_files=?,
              progress_bytes=?,
              manifest_path=?,
              log_path=?,
              started_utc=?,
              finished_utc=?,
              updated_utc=?
            WHERE job_id=?
            """,
            (
                status_n,
                str(row["error"] or "") if error is None else str(error),
                int(row["progress_files"] or 0) if progress_files is None else max(0, int(progress_files)),
                int(row["progress_bytes"] or 0) if progress_bytes is None else max(0, int(progress_bytes)),
                str(row["manifest_path"] or "") if manifest_path is None else str(manifest_path),
                str(row["log_path"] or "") if log_path is None else str(log_path),
                started,
                finished,
                now,
                str(job_id),
            ),
        )
        conn.commit()
        updated = conn.execute(
            "SELECT * FROM transfer_jobs WHERE job_id=?",
            (str(job_id),),
        ).fetchone()
    assert updated is not None
    return _transfer_job_from_row(updated)
