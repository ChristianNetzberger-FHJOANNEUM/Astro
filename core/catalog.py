"""SQLite-Katalog: Pfade und Metadaten, keine Fotos."""

from __future__ import annotations

import sqlite3
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

SCHEMA = """
CREATE TABLE IF NOT EXISTS session (
    id INTEGER PRIMARY KEY,
    slug TEXT NOT NULL UNIQUE,
    title TEXT NOT NULL,
    root_path TEXT NOT NULL,
    kind TEXT NOT NULL DEFAULT 'general',
    notes TEXT NOT NULL DEFAULT ''
);

CREATE TABLE IF NOT EXISTS burst (
    id INTEGER PRIMARY KEY,
    session_id INTEGER NOT NULL REFERENCES session(id) ON DELETE CASCADE,
    burst_no INTEGER NOT NULL,
    kind TEXT NOT NULL,
    drive_guess TEXT NOT NULL DEFAULT '',
    phase TEXT NOT NULL DEFAULT '',
    start_dt TEXT,
    end_dt TEXT,
    frame_count INTEGER NOT NULL,
    c2_offset_start_s REAL,
    c2_offset_end_s REAL,
    notes TEXT NOT NULL DEFAULT '',
    UNIQUE (session_id, burst_no)
);

CREATE TABLE IF NOT EXISTS image (
    id INTEGER PRIMARY KEY,
    session_id INTEGER NOT NULL REFERENCES session(id) ON DELETE CASCADE,
    burst_id INTEGER REFERENCES burst(id) ON DELETE SET NULL,
    burst_index INTEGER,
    filepath TEXT NOT NULL UNIQUE,
    jpg_path TEXT,
    datetime TEXT,
    datetime_src TEXT NOT NULL DEFAULT '',
    exposure TEXT NOT NULL DEFAULT '',
    iso INTEGER,
    aperture TEXT NOT NULL DEFAULT '',
    focal_length REAL,
    camera TEXT NOT NULL DEFAULT '',
    lens TEXT NOT NULL DEFAULT '',
    file_number INTEGER,
    phase TEXT NOT NULL DEFAULT '',
    c2_offset_s REAL,
    rating INTEGER NOT NULL DEFAULT 0,
    notes TEXT NOT NULL DEFAULT ''
);

CREATE INDEX IF NOT EXISTS idx_image_session ON image(session_id);
CREATE INDEX IF NOT EXISTS idx_image_burst ON image(burst_id);
CREATE INDEX IF NOT EXISTS idx_burst_session ON burst(session_id);

CREATE TABLE IF NOT EXISTS siril_workspace (
    id INTEGER PRIMARY KEY,
    burst_id INTEGER NOT NULL UNIQUE REFERENCES burst(id) ON DELETE CASCADE,
    path TEXT NOT NULL,
    link_mode TEXT NOT NULL,
    frame_count INTEGER NOT NULL,
    created_at TEXT NOT NULL
);
"""


def _dt_to_iso(value: datetime | None) -> str | None:
    if value is None:
        return None
    return value.isoformat(timespec="microseconds")


def _dt_from_iso(value: str | None) -> datetime | None:
    if not value:
        return None
    return datetime.fromisoformat(value)


@dataclass
class SessionRow:
    id: int
    slug: str
    title: str
    root_path: str
    kind: str
    notes: str
    image_count: int = 0
    burst_count: int = 0


@dataclass
class BurstRow:
    id: int
    session_id: int
    burst_no: int
    kind: str
    drive_guess: str
    phase: str
    start_dt: str | None
    end_dt: str | None
    frame_count: int
    c2_offset_start_s: float | None
    c2_offset_end_s: float | None
    notes: str
    preview_jpg: str | None = None


@dataclass
class ImageRow:
    id: int
    session_id: int
    burst_id: int | None
    burst_index: int | None
    filepath: str
    jpg_path: str | None
    datetime: str | None
    datetime_src: str
    exposure: str
    iso: int | None
    aperture: str
    focal_length: float | None
    camera: str
    lens: str
    file_number: int | None
    phase: str
    c2_offset_s: float | None
    rating: int
    notes: str


class Catalog:
    def __init__(self, path: Path) -> None:
        self.path = path
        path.parent.mkdir(parents=True, exist_ok=True)
        self.conn = sqlite3.connect(path)
        self.conn.row_factory = sqlite3.Row
        self.conn.execute("PRAGMA foreign_keys = ON")
        self.conn.executescript(SCHEMA)
        self.conn.commit()

    def close(self) -> None:
        self.conn.close()

    def replace_session(
        self,
        slug: str,
        title: str,
        root_path: str,
        kind: str,
        notes: str,
        bursts: list,
    ) -> int:
        """Session upsert: image.id bleibt als stabile frame_id erhalten."""
        cur = self.conn.cursor()
        cur.execute("SELECT id FROM session WHERE slug = ?", (slug,))
        row = cur.fetchone()
        if row:
            session_id = int(row["id"])
            cur.execute(
                "UPDATE session SET title=?, root_path=?, kind=?, notes=? WHERE id=?",
                (title, root_path, kind, notes, session_id),
            )
        else:
            cur.execute(
                "INSERT INTO session (slug, title, root_path, kind, notes) VALUES (?,?,?,?,?)",
                (slug, title, root_path, kind, notes),
            )
            session_id = int(cur.lastrowid)

        from core.eclipse import capture_c2_offset, capture_phase

        seen_burst_nos: list[int] = []
        seen_paths: list[str] = []
        for burst in bursts:
            cur.execute(
                """
                INSERT INTO burst (
                    session_id, burst_no, kind, drive_guess, phase, start_dt, end_dt,
                    frame_count, c2_offset_start_s, c2_offset_end_s, notes
                ) VALUES (?,?,?,?,?,?,?,?,?,?,?)
                ON CONFLICT(session_id, burst_no) DO UPDATE SET
                    kind=excluded.kind,
                    drive_guess=excluded.drive_guess,
                    phase=excluded.phase,
                    start_dt=excluded.start_dt,
                    end_dt=excluded.end_dt,
                    frame_count=excluded.frame_count,
                    c2_offset_start_s=excluded.c2_offset_start_s,
                    c2_offset_end_s=excluded.c2_offset_end_s,
                    notes=excluded.notes
                """,
                (
                    session_id,
                    burst.burst_no,
                    burst.kind,
                    burst.drive_guess,
                    burst.phase,
                    _dt_to_iso(burst.start_dt),
                    _dt_to_iso(burst.end_dt),
                    burst.frame_count,
                    burst.contact_offset_start_s,
                    burst.contact_offset_end_s,
                    burst.notes,
                ),
            )
            cur.execute(
                "SELECT id FROM burst WHERE session_id=? AND burst_no=?",
                (session_id, burst.burst_no),
            )
            burst_id = int(cur.fetchone()["id"])
            seen_burst_nos.append(burst.burst_no)
            for index, capture in enumerate(burst.captures, start=1):
                raw = str(capture.raw_path) if capture.raw_path else str(capture.jpg_path)
                jpg = str(capture.jpg_path) if capture.jpg_path else None
                seen_paths.append(raw)
                cur.execute(
                    """
                    INSERT INTO image (
                        session_id, burst_id, burst_index, filepath, jpg_path, datetime,
                        datetime_src, exposure, iso, aperture, focal_length, camera, lens,
                        file_number, phase, c2_offset_s
                    ) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
                    ON CONFLICT(filepath) DO UPDATE SET
                        session_id=excluded.session_id,
                        burst_id=excluded.burst_id,
                        burst_index=excluded.burst_index,
                        jpg_path=excluded.jpg_path,
                        datetime=excluded.datetime,
                        datetime_src=excluded.datetime_src,
                        exposure=excluded.exposure,
                        iso=excluded.iso,
                        aperture=excluded.aperture,
                        focal_length=excluded.focal_length,
                        camera=excluded.camera,
                        lens=excluded.lens,
                        file_number=excluded.file_number,
                        phase=excluded.phase,
                        c2_offset_s=excluded.c2_offset_s
                    """,
                    (
                        session_id,
                        burst_id,
                        index,
                        raw,
                        jpg,
                        _dt_to_iso(capture.datetime),
                        capture.datetime_src,
                        capture.exposure,
                        capture.iso,
                        capture.aperture,
                        capture.focal_length_mm,
                        capture.camera,
                        capture.lens,
                        capture.file_number,
                        capture_phase(capture),
                        capture_c2_offset(capture),
                    ),
                )
        if seen_burst_nos:
            marks = ",".join("?" * len(seen_burst_nos))
            cur.execute(
                f"DELETE FROM burst WHERE session_id=? AND burst_no NOT IN ({marks})",
                [session_id, *seen_burst_nos],
            )
        else:
            cur.execute("DELETE FROM burst WHERE session_id=?", (session_id,))
        if seen_paths:
            marks = ",".join("?" * len(seen_paths))
            cur.execute(
                f"DELETE FROM image WHERE session_id=? AND filepath NOT IN ({marks})",
                [session_id, *seen_paths],
            )
        else:
            cur.execute("DELETE FROM image WHERE session_id=?", (session_id,))
        self.conn.commit()
        return session_id

    def list_sessions(self) -> list[SessionRow]:
        rows = self.conn.execute(
            """
            SELECT s.*,
                   (SELECT COUNT(*) FROM image i WHERE i.session_id = s.id) AS image_count,
                   (SELECT COUNT(*) FROM burst b WHERE b.session_id = s.id) AS burst_count
            FROM session s
            ORDER BY s.slug
            """
        ).fetchall()
        return [self._session_row(r) for r in rows]

    def get_session(self, session_id: int) -> SessionRow | None:
        row = self.conn.execute(
            """
            SELECT s.*,
                   (SELECT COUNT(*) FROM image i WHERE i.session_id = s.id) AS image_count,
                   (SELECT COUNT(*) FROM burst b WHERE b.session_id = s.id) AS burst_count
            FROM session s WHERE s.id = ?
            """,
            (session_id,),
        ).fetchone()
        return self._session_row(row) if row else None

    def list_bursts(self, session_id: int, kind: str | None = None, phase: str | None = None) -> list[BurstRow]:
        sql = """
            SELECT b.*,
                   (SELECT i.jpg_path FROM image i
                    WHERE i.burst_id = b.id AND i.jpg_path IS NOT NULL
                    ORDER BY i.burst_index LIMIT 1) AS preview_jpg
            FROM burst b
            WHERE b.session_id = ?
        """
        params: list = [session_id]
        if kind:
            sql += " AND b.kind = ?"
            params.append(kind)
        if phase:
            sql += " AND b.phase = ?"
            params.append(phase)
        sql += " ORDER BY b.burst_no"
        return [self._burst_row(r) for r in self.conn.execute(sql, params).fetchall()]

    def get_burst(self, burst_id: int) -> BurstRow | None:
        row = self.conn.execute(
            """
            SELECT b.*,
                   (SELECT i.jpg_path FROM image i
                    WHERE i.burst_id = b.id AND i.jpg_path IS NOT NULL
                    ORDER BY i.burst_index LIMIT 1) AS preview_jpg
            FROM burst b WHERE b.id = ?
            """,
            (burst_id,),
        ).fetchone()
        return self._burst_row(row) if row else None

    def list_images(self, burst_id: int) -> list[ImageRow]:
        rows = self.conn.execute(
            "SELECT * FROM image WHERE burst_id = ? ORDER BY burst_index, file_number, filepath",
            (burst_id,),
        ).fetchall()
        return [self._image_row(r) for r in rows]

    def upsert_workspace(
        self,
        burst_id: int,
        path: str,
        link_mode: str,
        frame_count: int,
    ) -> None:
        now = datetime.now().isoformat(timespec="seconds")
        self.conn.execute(
            """
            INSERT INTO siril_workspace (burst_id, path, link_mode, frame_count, created_at)
            VALUES (?,?,?,?,?)
            ON CONFLICT(burst_id) DO UPDATE SET
                path=excluded.path,
                link_mode=excluded.link_mode,
                frame_count=excluded.frame_count,
                created_at=excluded.created_at
            """,
            (burst_id, path, link_mode, frame_count, now),
        )
        self.conn.commit()

    def get_workspace_path(self, burst_id: int) -> str | None:
        row = self.conn.execute(
            "SELECT path FROM siril_workspace WHERE burst_id=?",
            (burst_id,),
        ).fetchone()
        return str(row["path"]) if row else None

    def summary(self) -> dict[str, int]:
        images = self.conn.execute("SELECT COUNT(*) AS n FROM image").fetchone()["n"]
        bursts = self.conn.execute("SELECT COUNT(*) AS n FROM burst").fetchone()["n"]
        sessions = self.conn.execute("SELECT COUNT(*) AS n FROM session").fetchone()["n"]
        return {"sessions": sessions, "bursts": bursts, "images": images}

    @staticmethod
    def _session_row(row: sqlite3.Row) -> SessionRow:
        return SessionRow(
            id=row["id"],
            slug=row["slug"],
            title=row["title"],
            root_path=row["root_path"],
            kind=row["kind"],
            notes=row["notes"],
            image_count=row["image_count"],
            burst_count=row["burst_count"],
        )

    @staticmethod
    def _burst_row(row: sqlite3.Row) -> BurstRow:
        return BurstRow(
            id=row["id"],
            session_id=row["session_id"],
            burst_no=row["burst_no"],
            kind=row["kind"],
            drive_guess=row["drive_guess"],
            phase=row["phase"],
            start_dt=row["start_dt"],
            end_dt=row["end_dt"],
            frame_count=row["frame_count"],
            c2_offset_start_s=row["c2_offset_start_s"],
            c2_offset_end_s=row["c2_offset_end_s"],
            notes=row["notes"],
            preview_jpg=row["preview_jpg"] if "preview_jpg" in row.keys() else None,
        )

    @staticmethod
    def _image_row(row: sqlite3.Row) -> ImageRow:
        return ImageRow(
            id=row["id"],
            session_id=row["session_id"],
            burst_id=row["burst_id"],
            burst_index=row["burst_index"],
            filepath=row["filepath"],
            jpg_path=row["jpg_path"],
            datetime=row["datetime"],
            datetime_src=row["datetime_src"],
            exposure=row["exposure"],
            iso=row["iso"],
            aperture=row["aperture"],
            focal_length=row["focal_length"],
            camera=row["camera"],
            lens=row["lens"],
            file_number=row["file_number"],
            phase=row["phase"],
            c2_offset_s=row["c2_offset_s"],
            rating=row["rating"],
            notes=row["notes"],
        )
