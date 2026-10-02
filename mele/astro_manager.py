"""Astro-Manager: Imaging-Profile, Sessions, Images (Phase 1).

Stammdaten (RA/Dec/Typ) bleiben in sky.sqlite / Tabelle dso.
User-Daten liegen bewusst in einer eigenen Datei astro_manager.sqlite,
weil `python -m mele.catalog import` sky.sqlite neu aufbaut und loescht.

Verknuepfung: catalog_key Soft-Link zur Objekt-Identitaet
(z.B. \"M31\", \"NGC224\", \"HIP21421\", \"planet:Jupiter\") — kein FK auf sky.sqlite.
Speicherpfade: local_path / archive_path / archive_status vorbereitet,
aber noch ohne NAS-Copy (spaetere Phase).
"""

from __future__ import annotations

import os
import sqlite3
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from mele.config import REPO_ROOT, load_mele_settings

SCHEMA_VERSION = 1

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
"""

ARCHIVE_STATUSES = frozenset({"local", "pending", "archived", "missing"})


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
    frames_planned: int | None = None
    frames_completed: int = 0
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
    return ImagingSession(
        id=int(row["id"]),
        catalog_key=str(row["catalog_key"]),
        profile_id=None if row["profile_id"] is None else int(row["profile_id"]),
        started_utc=str(row["started_utc"] or ""),
        ended_utc=None if row["ended_utc"] is None else str(row["ended_utc"]),
        frames_planned=None if row["frames_planned"] is None else int(row["frames_planned"]),
        frames_completed=int(row["frames_completed"] or 0),
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
    completed = max(0, int(frames_completed or 0))
    planned = None if frames_planned is None else max(0, int(frames_planned))

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
        if planned is None:
            planned = profile.frames

    binning = str(binning or "1x1")

    integration = None
    if exposure_s is not None and completed > 0:
        integration = float(exposure_s) * completed
    with _connect(db_path) as conn:
        if profile_id is not None:
            exists = conn.execute(
                "SELECT id FROM imaging_profiles WHERE id=?",
                (int(profile_id),),
            ).fetchone()
            if exists is None:
                raise ValueError(f"Unbekanntes Profil: {profile_id}")
        cur = conn.execute(
            """
            INSERT INTO sessions (
              catalog_key, profile_id, started_utc, ended_utc, frames_planned,
              frames_completed, exposure_s, gain, iso, offset_adu, binning,
              filter_name, equipment, integration_s, local_path, archive_path,
              archive_status, notes, created_utc, updated_utc
            ) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
            """,
            (
                key,
                None if profile_id is None else int(profile_id),
                started,
                None,
                planned,
                completed,
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

        pid = row["profile_id"] if profile_id is None else profile_id
        if pid is not None:
            exists = conn.execute(
                "SELECT id FROM imaging_profiles WHERE id=?",
                (int(pid),),
            ).fetchone()
            if exists is None:
                raise ValueError(f"Unbekanntes Profil: {pid}")

        planned = _pick(frames_planned, row["frames_planned"])
        if planned is not None:
            planned = max(0, int(planned))
        completed = int(row["frames_completed"] or 0)
        if frames_completed is not None:
            completed = max(0, int(frames_completed))
        exp = _pick(exposure_s, row["exposure_s"])
        if exp is not None:
            exp = float(exp)
        g = _pick(gain, row["gain"] if "gain" in row.keys() else None)
        if g is not None:
            g = float(g)
        iso_v = _pick(iso, row["iso"] if "iso" in row.keys() else None)
        if iso_v is not None:
            iso_v = int(iso_v)
        off = _pick(offset_adu, row["offset_adu"] if "offset_adu" in row.keys() else None)
        if off is not None:
            off = int(off)
        binn = str(_pick(binning, row["binning"] if "binning" in row.keys() else "1x1") or "1x1")
        filt = str(_pick(filter_name, row["filter_name"] if "filter_name" in row.keys() else "") or "")
        equip = str(_pick(equipment, row["equipment"] if "equipment" in row.keys() else "") or "")
        local = str(_pick(local_path, row["local_path"]) or "")
        arch = str(_pick(archive_path, row["archive_path"]) or "")
        status = str(_pick(archive_status, row["archive_status"]) or "local").lower()
        if status not in ARCHIVE_STATUSES:
            status = "local"
        note = str(_pick(notes, row["notes"]) or "")
        integration = None if exp is None else float(exp) * completed

        conn.execute(
            """
            UPDATE sessions SET
              profile_id=?, frames_planned=?, frames_completed=?, exposure_s=?,
              gain=?, iso=?, offset_adu=?, binning=?, filter_name=?, equipment=?,
              integration_s=?, local_path=?, archive_path=?, archive_status=?,
              notes=?, updated_utc=?
            WHERE id=?
            """,
            (
                None if pid is None else int(pid),
                planned,
                completed,
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
    db_path: Path | None = None,
) -> ImagingSession:
    """Ein weiteres Frame an bestehende Session anrechnen."""
    delta = max(1, int(frames_delta))
    now = _utc_now()
    with _connect(db_path) as conn:
        row = conn.execute("SELECT * FROM sessions WHERE id=?", (int(session_id),)).fetchone()
        if row is None:
            raise ValueError(f"Unbekannte Session: {session_id}")
        completed = int(row["frames_completed"] or 0) + delta
        planned = row["frames_planned"]
        if planned is not None:
            planned = max(int(planned), completed)
        exposure = None if row["exposure_s"] is None else float(row["exposure_s"])
        integration = None if exposure is None else exposure * completed
        conn.execute(
            """
            UPDATE sessions SET
              frames_completed=?, frames_planned=?, integration_s=?, updated_utc=?
            WHERE id=?
            """,
            (completed, planned, integration, now, int(session_id)),
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


def ensure_session_subdir(path: str | Path, session_id: int) -> Path:
    """Haengt s##### an, falls der Pfad noch keine Session-Ebene hat."""
    p = Path(str(path or "").strip())
    slug = session_dir_slug(session_id)
    if p.name.lower() == slug.lower():
        return p
    if any(part.lower() == slug.lower() for part in p.parts):
        return p
    return p / slug


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
    if fr is None and session is not None and session.frames_planned is not None:
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
