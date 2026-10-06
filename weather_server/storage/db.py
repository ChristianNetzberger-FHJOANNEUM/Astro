"""SQLite persistence for weather_server samples."""

from __future__ import annotations

import json
import sqlite3
import threading
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


_SCHEMA = """
CREATE TABLE IF NOT EXISTS weather_samples (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    recorded_at TEXT NOT NULL,
    station_when TEXT,
    label TEXT,
    temp_c REAL,
    humidity_pct REAL,
    pressure_hpa REAL,
    pressure_abs_hpa REAL,
    wind_ms REAL,
    wind_dir_deg REAL,
    gust_ms REAL,
    day_wind_max_ms REAL,
    rain_mm REAL,
    rain_rate_mm_h REAL,
    rain_event_mm REAL,
    rain_week_mm REAL,
    rain_month_mm REAL,
    rain_year_mm REAL,
    uvi REAL,
    lux REAL,
    dewpoint_c REAL,
    dewpoint_margin_c REAL,
    indoor_temp_c REAL,
    indoor_humidity_pct REAL,
    solarradiation_wm2 REAL,
    provider TEXT,
    payload_json TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_weather_samples_recorded_at
    ON weather_samples (recorded_at DESC);
"""

_SAMPLE_COLUMNS = (
    "id",
    "recorded_at",
    "station_when",
    "label",
    "temp_c",
    "humidity_pct",
    "pressure_hpa",
    "pressure_abs_hpa",
    "wind_ms",
    "wind_dir_deg",
    "gust_ms",
    "day_wind_max_ms",
    "rain_mm",
    "rain_rate_mm_h",
    "rain_event_mm",
    "rain_week_mm",
    "rain_month_mm",
    "rain_year_mm",
    "uvi",
    "lux",
    "dewpoint_c",
    "dewpoint_margin_c",
    "indoor_temp_c",
    "indoor_humidity_pct",
    "solarradiation_wm2",
    "provider",
)


def _utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _row_to_dict(row: sqlite3.Row) -> dict[str, Any]:
    data = {key: row[key] for key in _SAMPLE_COLUMNS if key in row.keys()}
    data["when"] = data.get("station_when") or data.get("recorded_at")
    return data


class WeatherStore:
    """Thread-safe SQLite store."""

    def __init__(self, db_path: Path) -> None:
        self.db_path = Path(db_path)
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._lock = threading.Lock()
        self._conn = sqlite3.connect(str(self.db_path), check_same_thread=False)
        self._conn.row_factory = sqlite3.Row
        with self._lock:
            self._conn.executescript(_SCHEMA)
            self._conn.commit()

    def close(self) -> None:
        with self._lock:
            self._conn.close()

    def insert_sample(self, observation: dict[str, Any], *, label: str = "") -> dict[str, Any]:
        recorded_at = _utc_now_iso()
        station_when = str(observation.get("when") or recorded_at)
        payload_json = json.dumps(observation, ensure_ascii=False)
        values = (
            recorded_at,
            station_when,
            label or None,
            observation.get("temp_c"),
            observation.get("humidity_pct"),
            observation.get("pressure_hpa"),
            observation.get("pressure_abs_hpa"),
            observation.get("wind_ms"),
            observation.get("wind_dir_deg"),
            observation.get("gust_ms"),
            observation.get("day_wind_max_ms"),
            observation.get("rain_mm"),
            observation.get("rain_rate_mm_h"),
            observation.get("rain_event_mm"),
            observation.get("rain_week_mm"),
            observation.get("rain_month_mm"),
            observation.get("rain_year_mm"),
            observation.get("uvi"),
            observation.get("lux"),
            observation.get("dewpoint_c"),
            observation.get("dewpoint_margin_c"),
            observation.get("indoor_temp_c"),
            observation.get("indoor_humidity_pct"),
            observation.get("solarradiation_wm2"),
            observation.get("provider"),
            payload_json,
        )
        with self._lock:
            cur = self._conn.execute(
                """
                INSERT INTO weather_samples (
                    recorded_at, station_when, label,
                    temp_c, humidity_pct, pressure_hpa, pressure_abs_hpa,
                    wind_ms, wind_dir_deg, gust_ms, day_wind_max_ms,
                    rain_mm, rain_rate_mm_h, rain_event_mm,
                    rain_week_mm, rain_month_mm, rain_year_mm,
                    uvi, lux, dewpoint_c, dewpoint_margin_c,
                    indoor_temp_c, indoor_humidity_pct, solarradiation_wm2,
                    provider, payload_json
                ) VALUES (
                    ?, ?, ?,
                    ?, ?, ?, ?,
                    ?, ?, ?, ?,
                    ?, ?, ?,
                    ?, ?, ?,
                    ?, ?, ?, ?,
                    ?, ?, ?,
                    ?, ?
                )
                """,
                values,
            )
            sample_id = int(cur.lastrowid)
            self._conn.commit()
            row = self._conn.execute(
                f"SELECT {', '.join(_SAMPLE_COLUMNS)} FROM weather_samples WHERE id = ?",
                (sample_id,),
            ).fetchone()
        assert row is not None
        return _row_to_dict(row)

    def latest(self) -> dict[str, Any] | None:
        with self._lock:
            row = self._conn.execute(
                f"""
                SELECT {', '.join(_SAMPLE_COLUMNS)}
                FROM weather_samples
                ORDER BY id DESC
                LIMIT 1
                """
            ).fetchone()
        return _row_to_dict(row) if row else None

    def history(self, *, limit: int = 100, since: str | None = None) -> list[dict[str, Any]]:
        limit = max(1, min(int(limit), 5000))
        sql = f"SELECT {', '.join(_SAMPLE_COLUMNS)} FROM weather_samples"
        params: list[Any] = []
        if since:
            sql += " WHERE recorded_at >= ?"
            params.append(since)
        sql += " ORDER BY id DESC LIMIT ?"
        params.append(limit)
        with self._lock:
            rows = self._conn.execute(sql, params).fetchall()
        return [_row_to_dict(row) for row in rows]

    def sample_count(self) -> int:
        with self._lock:
            row = self._conn.execute("SELECT COUNT(*) AS n FROM weather_samples").fetchone()
        return int(row["n"]) if row else 0
