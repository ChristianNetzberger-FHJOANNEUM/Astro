"""Kamera, Kamerakonfiguration und Aufnahmerezept.

Eine Quelle je Angabe. Die Bildanzahl gehört zur Session oder zum Auftrag,
nicht zum Rezept. Fähigkeiten beschreiben, was ein Gerät kann. Der verbundene
Zustand kommt von NINA und wird hier nicht nachgebaut.
"""

from __future__ import annotations

import sqlite3
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

LUMIX_NAME = "Lumix S5IIX"
LUMIX_MATCH = "Lumix S5IIX,DC-S5M2X,DC-S5M2,Lumix"
LUMIX_CONFIG_LABEL = "ISO 640"
LUMIX_ISO = 640
LUMIX_BINNING = "1x1"

RECIPES: tuple[tuple[str, float], ...] = (
    ("Kurz – 2 s", 2.0),
    ("Mittel – 5 s", 5.0),
    ("Mittel – 6 s", 6.0),
    ("Standard – 10 s", 10.0),
    ("Lang – 20 s", 20.0),
)

CAMERA_SCHEMA = """
CREATE TABLE IF NOT EXISTS cameras (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT NOT NULL UNIQUE,
    driver_hint TEXT NOT NULL DEFAULT '',
    match_names TEXT NOT NULL DEFAULT '',
    capture_kind TEXT NOT NULL DEFAULT 'still',
    cap_iso INTEGER NOT NULL DEFAULT 0,
    cap_gain INTEGER NOT NULL DEFAULT 0,
    cap_offset INTEGER NOT NULL DEFAULT 0,
    cap_binning INTEGER NOT NULL DEFAULT 0,
    cap_roi INTEGER NOT NULL DEFAULT 0,
    cap_cooling INTEGER NOT NULL DEFAULT 0,
    cap_video INTEGER NOT NULL DEFAULT 0,
    iso_from_nina_gains INTEGER NOT NULL DEFAULT 0,
    created_utc TEXT NOT NULL,
    updated_utc TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS camera_configs (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    camera_id INTEGER NOT NULL,
    label TEXT NOT NULL,
    iso INTEGER,
    gain REAL,
    offset_adu INTEGER,
    binning TEXT NOT NULL DEFAULT '1x1',
    roi TEXT NOT NULL DEFAULT '',
    cooling_c REAL,
    readout_mode TEXT NOT NULL DEFAULT '',
    created_utc TEXT NOT NULL,
    updated_utc TEXT NOT NULL,
    FOREIGN KEY(camera_id) REFERENCES cameras(id)
);
CREATE TABLE IF NOT EXISTS capture_recipes (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT NOT NULL UNIQUE,
    exposure_s REAL NOT NULL,
    image_type TEXT NOT NULL DEFAULT 'LIGHT',
    capture_kind TEXT NOT NULL DEFAULT 'still',
    created_utc TEXT NOT NULL,
    updated_utc TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_camera_configs_camera ON camera_configs(camera_id);
"""

SESSION_CAMERA_COLUMNS = (
    ("camera_id", "ALTER TABLE sessions ADD COLUMN camera_id INTEGER"),
    ("camera_config_id", "ALTER TABLE sessions ADD COLUMN camera_config_id INTEGER"),
    ("recipe_id", "ALTER TABLE sessions ADD COLUMN recipe_id INTEGER"),
)


@dataclass(frozen=True)
class Camera:
    id: int
    name: str
    driver_hint: str = ""
    match_names: str = ""
    capture_kind: str = "still"
    cap_iso: bool = False
    cap_gain: bool = False
    cap_offset: bool = False
    cap_binning: bool = False
    cap_roi: bool = False
    cap_cooling: bool = False
    cap_video: bool = False
    iso_from_nina_gains: bool = False

    def capabilities(self) -> dict[str, bool]:
        return {
            "iso": self.cap_iso,
            "gain": self.cap_gain,
            "offset": self.cap_offset,
            "binning": self.cap_binning,
            "roi": self.cap_roi,
            "cooling": self.cap_cooling,
            "video": self.cap_video,
            "still": self.capture_kind == "still",
        }

    def to_dict(self) -> dict[str, Any]:
        body = asdict(self)
        body["capabilities"] = self.capabilities()
        return body


@dataclass(frozen=True)
class CameraConfig:
    id: int
    camera_id: int
    label: str
    iso: int | None = None
    gain: float | None = None
    offset_adu: int | None = None
    binning: str = "1x1"
    roi: str = ""
    cooling_c: float | None = None
    readout_mode: str = ""

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class CaptureRecipe:
    id: int
    name: str
    exposure_s: float
    image_type: str = "LIGHT"
    capture_kind: str = "still"

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class SetupChoice:
    ok: bool
    code: str = ""
    error: str = ""
    status: int = 200
    camera: Camera | None = None
    config: CameraConfig | None = None
    recipe: CaptureRecipe | None = None
    choices: dict[str, Any] | None = None


def _utc_now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def _flag(value: object) -> bool:
    return bool(int(value or 0))


def migrate_camera_model(conn: sqlite3.Connection) -> None:
    conn.executescript(CAMERA_SCHEMA)
    cols = {str(row[1]) for row in conn.execute("PRAGMA table_info(sessions)").fetchall()}
    for name, sql in SESSION_CAMERA_COLUMNS:
        if name not in cols:
            conn.execute(sql)
    _seed_lumix(conn)


def _seed_lumix(conn: sqlite3.Connection) -> None:
    now = _utc_now()
    row = conn.execute("SELECT id FROM cameras WHERE name=?", (LUMIX_NAME,)).fetchone()
    if row is None:
        cur = conn.execute(
            """
            INSERT INTO cameras (
              name, driver_hint, match_names, capture_kind,
              cap_iso, cap_gain, cap_offset, cap_binning, cap_roi, cap_cooling, cap_video,
              iso_from_nina_gains, created_utc, updated_utc
            ) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)
            """,
            (
                LUMIX_NAME,
                "DC-S5M2X",
                LUMIX_MATCH,
                "still",
                1,
                0,
                0,
                1,
                0,
                0,
                0,
                1,
                now,
                now,
            ),
        )
        camera_id = int(cur.lastrowid)
    else:
        camera_id = int(row[0])
    config = conn.execute(
        "SELECT id FROM camera_configs WHERE camera_id=? AND label=?",
        (camera_id, LUMIX_CONFIG_LABEL),
    ).fetchone()
    if config is None:
        conn.execute(
            """
            INSERT INTO camera_configs (
              camera_id, label, iso, gain, offset_adu, binning, roi, readout_mode,
              created_utc, updated_utc
            ) VALUES (?,?,?,?,?,?,?,?,?,?)
            """,
            (camera_id, LUMIX_CONFIG_LABEL, LUMIX_ISO, None, None, LUMIX_BINNING, "", "", now, now),
        )
    for name, exposure_s in RECIPES:
        found = conn.execute("SELECT id FROM capture_recipes WHERE name=?", (name,)).fetchone()
        if found is None:
            conn.execute(
                """
                INSERT INTO capture_recipes (
                  name, exposure_s, image_type, capture_kind, created_utc, updated_utc
                ) VALUES (?,?,?,?,?,?)
                """,
                (name, float(exposure_s), "LIGHT", "still", now, now),
            )


def _open(db_path: Path | None) -> sqlite3.Connection:
    from mele.astro_manager import ensure_manager_db

    path = ensure_manager_db(db_path)
    conn = sqlite3.connect(path)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    return conn


def _camera_from_row(row: sqlite3.Row) -> Camera:
    return Camera(
        id=int(row["id"]),
        name=str(row["name"]),
        driver_hint=str(row["driver_hint"] or ""),
        match_names=str(row["match_names"] or ""),
        capture_kind=str(row["capture_kind"] or "still"),
        cap_iso=_flag(row["cap_iso"]),
        cap_gain=_flag(row["cap_gain"]),
        cap_offset=_flag(row["cap_offset"]),
        cap_binning=_flag(row["cap_binning"]),
        cap_roi=_flag(row["cap_roi"]),
        cap_cooling=_flag(row["cap_cooling"]),
        cap_video=_flag(row["cap_video"]),
        iso_from_nina_gains=_flag(row["iso_from_nina_gains"]),
    )


def _config_from_row(row: sqlite3.Row) -> CameraConfig:
    return CameraConfig(
        id=int(row["id"]),
        camera_id=int(row["camera_id"]),
        label=str(row["label"]),
        iso=None if row["iso"] is None else int(row["iso"]),
        gain=None if row["gain"] is None else float(row["gain"]),
        offset_adu=None if row["offset_adu"] is None else int(row["offset_adu"]),
        binning=str(row["binning"] or "1x1"),
        roi=str(row["roi"] or ""),
        cooling_c=None if row["cooling_c"] is None else float(row["cooling_c"]),
        readout_mode=str(row["readout_mode"] or ""),
    )


def _recipe_from_row(row: sqlite3.Row) -> CaptureRecipe:
    return CaptureRecipe(
        id=int(row["id"]),
        name=str(row["name"]),
        exposure_s=float(row["exposure_s"]),
        image_type=str(row["image_type"] or "LIGHT"),
        capture_kind=str(row["capture_kind"] or "still"),
    )


def list_cameras(*, db_path: Path | None = None) -> list[Camera]:
    with _open(db_path) as conn:
        rows = conn.execute("SELECT * FROM cameras ORDER BY name COLLATE NOCASE").fetchall()
    return [_camera_from_row(row) for row in rows]


def get_camera(camera_id: int, *, db_path: Path | None = None) -> Camera | None:
    with _open(db_path) as conn:
        row = conn.execute("SELECT * FROM cameras WHERE id=?", (int(camera_id),)).fetchone()
    return None if row is None else _camera_from_row(row)


def list_configs(camera_id: int | None = None, *, db_path: Path | None = None) -> list[CameraConfig]:
    with _open(db_path) as conn:
        if camera_id is None:
            rows = conn.execute("SELECT * FROM camera_configs ORDER BY label COLLATE NOCASE").fetchall()
        else:
            rows = conn.execute(
                "SELECT * FROM camera_configs WHERE camera_id=? ORDER BY label COLLATE NOCASE",
                (int(camera_id),),
            ).fetchall()
    return [_config_from_row(row) for row in rows]


def get_config(config_id: int, *, db_path: Path | None = None) -> CameraConfig | None:
    with _open(db_path) as conn:
        row = conn.execute("SELECT * FROM camera_configs WHERE id=?", (int(config_id),)).fetchone()
    return None if row is None else _config_from_row(row)


def list_recipes(*, db_path: Path | None = None) -> list[CaptureRecipe]:
    with _open(db_path) as conn:
        rows = conn.execute("SELECT * FROM capture_recipes ORDER BY exposure_s, name").fetchall()
    return [_recipe_from_row(row) for row in rows]


def get_recipe(recipe_id: int, *, db_path: Path | None = None) -> CaptureRecipe | None:
    with _open(db_path) as conn:
        row = conn.execute("SELECT * FROM capture_recipes WHERE id=?", (int(recipe_id),)).fetchone()
    return None if row is None else _recipe_from_row(row)


def imaging_model(*, db_path: Path | None = None) -> dict[str, Any]:
    cameras = list_cameras(db_path=db_path)
    return {
        "ok": True,
        "cameras": [camera.to_dict() for camera in cameras],
        "configs": [config.to_dict() for config in list_configs(db_path=db_path)],
        "recipes": [recipe.to_dict() for recipe in list_recipes(db_path=db_path)],
    }


def nina_name_matches(match_names: str, connected_name: str) -> bool:
    name = str(connected_name or "").casefold().strip()
    if not name:
        return False
    tokens = [part.casefold().strip() for part in str(match_names or "").split(",") if part.strip()]
    return any(token == name or token in name or name in token for token in tokens)


def connected_camera_name(camera_payload: dict[str, Any] | None) -> str:
    raw = camera_payload if isinstance(camera_payload, dict) else {}
    camera = raw.get("camera") if isinstance(raw.get("camera"), dict) else {}
    return str(camera.get("name") or "")


def connected_camera_online(camera_payload: dict[str, Any] | None) -> bool:
    raw = camera_payload if isinstance(camera_payload, dict) else {}
    camera = raw.get("camera") if isinstance(raw.get("camera"), dict) else {}
    return bool(raw.get("api_online")) and bool(camera.get("connected"))


def iso_from_gains_enabled(camera: Camera | None, camera_payload: dict[str, Any] | None) -> bool:
    """Nur die Lumix legt ihre ISO-Stufen in der NINA-Gain-Liste ab."""
    if camera is None or not camera.iso_from_nina_gains or not camera.cap_iso:
        return False
    if not connected_camera_online(camera_payload):
        return False
    return nina_name_matches(camera.match_names, connected_camera_name(camera_payload))


def camera_connection_problem(
    camera: Camera | None,
    camera_payload: dict[str, Any] | None,
) -> tuple[str, str] | None:
    """None, wenn keine Session-Kamera gesetzt ist oder das verbundene Gerät passt."""
    if camera is None:
        return None
    if camera_payload is None or not connected_camera_online(camera_payload):
        return "camera_offline", "Die gewählte Kamera ist in NINA nicht verbunden."
    if not nina_name_matches(camera.match_names, connected_camera_name(camera_payload)):
        return "camera_mismatch", "Die verbundene NINA-Kamera passt nicht zur Session."
    return None


def resolve_setup(
    *,
    camera_id: int | None,
    config_id: int | None,
    recipe_id: int | None,
    db_path: Path | None = None,
) -> SetupChoice:
    cameras = list_cameras(db_path=db_path)
    configs = list_configs(db_path=db_path)
    recipes = list_recipes(db_path=db_path)
    catalog = {
        "cameras": [camera.to_dict() for camera in cameras],
        "configs": [config.to_dict() for config in configs],
        "recipes": [recipe.to_dict() for recipe in recipes],
    }
    if camera_id is None:
        if len(cameras) != 1:
            return SetupChoice(False, "camera_required", "Kamera wählen.", 409, choices=catalog)
        camera = cameras[0]
    else:
        camera = next((item for item in cameras if item.id == int(camera_id)), None)
        if camera is None:
            return SetupChoice(False, "camera_missing", "Unbekannte Kamera.", 404, choices=catalog)
    own_configs = [item for item in configs if item.camera_id == camera.id]
    if config_id is None:
        if len(own_configs) != 1:
            return SetupChoice(False, "config_required", "Kamerakonfiguration wählen.", 409, choices=catalog)
        config = own_configs[0]
    else:
        config = next((item for item in own_configs if item.id == int(config_id)), None)
        if config is None:
            return SetupChoice(False, "config_mismatch", "Konfiguration gehört nicht zur Kamera.", 409, choices=catalog)
    if recipe_id is None:
        if len(recipes) != 1:
            return SetupChoice(False, "recipe_required", "Aufnahmerezept wählen.", 409, choices=catalog)
        recipe = recipes[0]
    else:
        recipe = next((item for item in recipes if item.id == int(recipe_id)), None)
        if recipe is None:
            return SetupChoice(False, "recipe_missing", "Unbekanntes Aufnahmerezept.", 404, choices=catalog)
    return SetupChoice(True, camera=camera, config=config, recipe=recipe)


def clear_test_capture_data(*, db_path: Path | None = None) -> dict[str, Any]:
    """Entfernt Test-Sessions, ihre Auftragszeilen und objektgebundene Profile.

    Dateien auf der Platte bleiben. Andere Tabellen bleiben.
    """
    with _open(db_path) as conn:
        sessions = [dict(row) for row in conn.execute(
            "SELECT id, catalog_key, local_path, archive_path FROM sessions ORDER BY id"
        ).fetchall()]
        profiles = [dict(row) for row in conn.execute(
            "SELECT id, catalog_key, label FROM imaging_profiles ORDER BY id"
        ).fetchall()]
        image_count = int(conn.execute("SELECT COUNT(*) FROM images").fetchone()[0])
        job_count = int(conn.execute("SELECT COUNT(*) FROM transfer_jobs").fetchone()[0])
        tables = [
            str(row[0])
            for row in conn.execute(
                "SELECT name FROM sqlite_master WHERE type='table' ORDER BY name"
            ).fetchall()
        ]
        conn.execute("DELETE FROM transfer_jobs")
        conn.execute("DELETE FROM images")
        conn.execute("DELETE FROM sessions")
        conn.execute("DELETE FROM imaging_profiles")
        conn.commit()
        remaining = {
            "sessions": int(conn.execute("SELECT COUNT(*) FROM sessions").fetchone()[0]),
            "images": int(conn.execute("SELECT COUNT(*) FROM images").fetchone()[0]),
            "transfer_jobs": int(conn.execute("SELECT COUNT(*) FROM transfer_jobs").fetchone()[0]),
            "imaging_profiles": int(conn.execute("SELECT COUNT(*) FROM imaging_profiles").fetchone()[0]),
            "cameras": int(conn.execute("SELECT COUNT(*) FROM cameras").fetchone()[0]),
            "camera_configs": int(conn.execute("SELECT COUNT(*) FROM camera_configs").fetchone()[0]),
            "capture_recipes": int(conn.execute("SELECT COUNT(*) FROM capture_recipes").fetchone()[0]),
        }
    return {
        "tables": tables,
        "deleted_sessions": len(sessions),
        "deleted_images": image_count,
        "deleted_transfer_jobs": job_count,
        "deleted_profiles": len(profiles),
        "session_paths": [
            {"id": int(row["id"]), "catalog_key": row["catalog_key"], "local_path": row["local_path"]}
            for row in sessions
        ],
        "profiles": [
            {"id": int(row["id"]), "catalog_key": row["catalog_key"], "label": row["label"]}
            for row in profiles
        ],
        "remaining": remaining,
    }
