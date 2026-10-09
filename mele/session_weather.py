"""S2: Session-Wetterexport aus weather_server (Zeitreihe → CSV + Summary).

Kein zweites dauerhaftes Wetter-DB. Server bleibt SoT; Export ist Snapshot.
Bei History-Limit (max 5000, neueste zuerst) → partial, nie still unvollstaendig.
"""

from __future__ import annotations

import csv
import json
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable

from mele.session_storage import (
    LIFECYCLE_CLOSED,
    WEATHER_EXPORT_NONE,
    WEATHER_EXPORT_OK,
    WEATHER_EXPORT_PARTIAL,
    WEATHER_EXPORT_UNAVAILABLE,
)
from mele.weather_server_client import WeatherServerError, fetch_history

HISTORY_LIMIT_MAX = 5000

CSV_FIELDS = (
    "utc",
    "recorded_at",
    "station_when",
    "temp_c",
    "humidity_pct",
    "dewpoint_c",
    "dewpoint_margin_c",
    "pressure_hpa",
    "pressure_abs_hpa",
    "wind_ms",
    "wind_dir_deg",
    "gust_ms",
    "rain_mm",
    "rain_rate_mm_h",
    "uvi",
    "lux",
    "solarradiation_wm2",
    "indoor_temp_c",
    "indoor_humidity_pct",
    "sample_id",
    "label",
)


@dataclass
class WeatherExportResult:
    export_status: str
    sample_count: int = 0
    csv_path: str = ""
    summary_path: str = ""
    gaps: list[dict[str, Any]] = field(default_factory=list)
    truncated: bool = False
    error: str = ""
    window_start_utc: str = ""
    window_end_utc: str = ""
    summary: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "export_status": self.export_status,
            "sample_count": self.sample_count,
            "csv_path": self.csv_path,
            "summary_path": self.summary_path,
            "gaps": list(self.gaps),
            "truncated": self.truncated,
            "error": self.error,
            "window_start_utc": self.window_start_utc,
            "window_end_utc": self.window_end_utc,
            "summary": dict(self.summary),
        }


def parse_iso_utc(value: str | None) -> datetime | None:
    raw = str(value or "").strip()
    if not raw:
        return None
    try:
        if raw.endswith("Z"):
            raw = raw[:-1] + "+00:00"
        dt = datetime.fromisoformat(raw)
    except ValueError:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def _sample_recorded_at(sample: dict[str, Any]) -> datetime | None:
    return parse_iso_utc(
        str(sample.get("recorded_at") or sample.get("when") or sample.get("station_when") or "")
    )


def filter_samples_window(
    samples: list[dict[str, Any]],
    *,
    start: datetime,
    end: datetime,
) -> list[dict[str, Any]]:
    """Samples im geschlossenen Intervall [start, end], aufsteigend nach Zeit."""
    kept: list[tuple[datetime, dict[str, Any]]] = []
    for sample in samples:
        when = _sample_recorded_at(sample)
        if when is None:
            continue
        if when < start or when > end:
            continue
        kept.append((when, sample))
    kept.sort(key=lambda item: item[0])
    return [sample for _, sample in kept]


def detect_gaps(
    samples_asc: list[dict[str, Any]],
    *,
    gap_threshold_s: float,
    window_start: datetime,
    window_end: datetime,
) -> list[dict[str, Any]]:
    """Luecken zwischen aufeinanderfolgenden Samples und am Fensterrand."""
    threshold = max(1.0, float(gap_threshold_s))
    gaps: list[dict[str, Any]] = []
    times = [_sample_recorded_at(s) for s in samples_asc]
    times = [t for t in times if t is not None]
    if not times:
        duration = (window_end - window_start).total_seconds()
        if duration > threshold:
            gaps.append(
                {
                    "start_utc": window_start.isoformat(),
                    "end_utc": window_end.isoformat(),
                    "duration_s": round(duration, 1),
                    "kind": "empty_window",
                }
            )
        return gaps

    lead = (times[0] - window_start).total_seconds()
    if lead > threshold:
        gaps.append(
            {
                "start_utc": window_start.isoformat(),
                "end_utc": times[0].isoformat(),
                "duration_s": round(lead, 1),
                "kind": "leading",
            }
        )
    for prev, nxt in zip(times, times[1:]):
        dt = (nxt - prev).total_seconds()
        if dt > threshold:
            gaps.append(
                {
                    "start_utc": prev.isoformat(),
                    "end_utc": nxt.isoformat(),
                    "duration_s": round(dt, 1),
                    "kind": "between",
                }
            )
    trail = (window_end - times[-1]).total_seconds()
    if trail > threshold:
        gaps.append(
            {
                "start_utc": times[-1].isoformat(),
                "end_utc": window_end.isoformat(),
                "duration_s": round(trail, 1),
                "kind": "trailing",
            }
        )
    return gaps


def assess_export_status(
    *,
    api_sample_count: int,
    history_limit: int,
    gaps: list[dict[str, Any]],
    window_start: datetime,
    filtered_samples: list[dict[str, Any]],
) -> tuple[str, bool]:
    """ok | partial. truncated=True wenn API-Limit aeltere Daten abschneiden kann."""
    limit = max(1, int(history_limit))
    truncated = api_sample_count >= limit
    if truncated:
        # Neueste-zuerst + Limit: aeltere Samples im Fenster koennen fehlen
        oldest = _sample_recorded_at(filtered_samples[0]) if filtered_samples else None
        if oldest is None or oldest > window_start:
            return WEATHER_EXPORT_PARTIAL, True
        return WEATHER_EXPORT_PARTIAL, True
    # Grosse Luecken dokumentieren, Status bleibt ok wenn Fenster voll abgedeckt wurde
    return WEATHER_EXPORT_OK, False


def _numeric_stats(samples: list[dict[str, Any]], key: str) -> dict[str, float] | None:
    values: list[float] = []
    for sample in samples:
        raw = sample.get(key)
        if raw is None:
            continue
        try:
            values.append(float(raw))
        except (TypeError, ValueError):
            continue
    if not values:
        return None
    return {
        "min": round(min(values), 3),
        "max": round(max(values), 3),
        "mean": round(sum(values) / len(values), 3),
    }


def build_summary(
    *,
    session_id: int,
    window_start: datetime,
    window_end: datetime,
    samples: list[dict[str, Any]],
    gaps: list[dict[str, Any]],
    export_status: str,
    truncated: bool,
    error: str = "",
    history_limit: int = HISTORY_LIMIT_MAX,
) -> dict[str, Any]:
    return {
        "session_id": session_id,
        "export_status": export_status,
        "truncated": truncated,
        "error": error,
        "window_start_utc": window_start.isoformat(),
        "window_end_utc": window_end.isoformat(),
        "sample_count": len(samples),
        "history_limit": history_limit,
        "gaps": gaps,
        "stats": {
            key: stats
            for key in ("temp_c", "humidity_pct", "dewpoint_c", "dewpoint_margin_c", "wind_ms", "pressure_hpa")
            if (stats := _numeric_stats(samples, key)) is not None
        },
        "generated_utc": datetime.now(timezone.utc).replace(microsecond=0).isoformat(),
    }


def samples_to_csv_rows(samples: list[dict[str, Any]]) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for sample in samples:
        when = _sample_recorded_at(sample)
        row = {key: "" for key in CSV_FIELDS}
        row["utc"] = when.isoformat() if when else ""
        row["recorded_at"] = str(sample.get("recorded_at") or "")
        row["station_when"] = str(sample.get("station_when") or "")
        for key in CSV_FIELDS:
            if key in ("utc", "recorded_at", "station_when", "sample_id", "label"):
                continue
            val = sample.get(key)
            row[key] = "" if val is None else val
        sid = sample.get("id")
        row["sample_id"] = "" if sid is None else sid
        row["label"] = str(sample.get("label") or "")
        rows.append(row)
    return rows


def write_weather_files(
    session_dir: Path,
    *,
    rows: list[dict[str, Any]],
    summary: dict[str, Any],
) -> tuple[Path, Path]:
    weather_dir = Path(session_dir) / "weather"
    weather_dir.mkdir(parents=True, exist_ok=True)
    csv_path = weather_dir / "weather.csv"
    summary_path = weather_dir / "weather-summary.json"
    with csv_path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(CSV_FIELDS))
        writer.writeheader()
        for row in rows:
            writer.writerow(row)
    summary_path.write_text(
        json.dumps(summary, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    return csv_path, summary_path


def export_session_weather_files(
    *,
    session_id: int,
    session_dir: Path | str,
    start_utc: str,
    end_utc: str,
    weather_server_url: str,
    gap_threshold_s: float = 120.0,
    history_limit: int = HISTORY_LIMIT_MAX,
    fetch_history_fn: Callable[..., list[dict[str, Any]]] | None = None,
) -> WeatherExportResult:
    """Zeitreihe exportieren. Idempotent: CSV/Summary werden ersetzt."""
    start = parse_iso_utc(start_utc)
    end = parse_iso_utc(end_utc)
    if start is None or end is None:
        return WeatherExportResult(
            export_status=WEATHER_EXPORT_UNAVAILABLE,
            error="session_start_utc/session_end_utc ungueltig",
            window_start_utc=str(start_utc or ""),
            window_end_utc=str(end_utc or ""),
        )
    if end < start:
        end = start

    root = Path(str(session_dir or "").strip())
    if not str(session_dir or "").strip():
        return WeatherExportResult(
            export_status=WEATHER_EXPORT_UNAVAILABLE,
            error="local_path fehlt — kein Session-Ordner fuer weather/",
            window_start_utc=start.isoformat(),
            window_end_utc=end.isoformat(),
        )

    limit = max(1, min(int(history_limit), HISTORY_LIMIT_MAX))
    fetcher = fetch_history_fn or fetch_history
    try:
        api_samples = fetcher(
            weather_server_url,
            limit=limit,
            since=start.isoformat(),
            timeout_s=20.0,
        )
    except WeatherServerError as exc:
        summary = build_summary(
            session_id=session_id,
            window_start=start,
            window_end=end,
            samples=[],
            gaps=[],
            export_status=WEATHER_EXPORT_UNAVAILABLE,
            truncated=False,
            error=str(exc),
            history_limit=limit,
        )
        try:
            csv_path, summary_path = write_weather_files(root, rows=[], summary=summary)
            return WeatherExportResult(
                export_status=WEATHER_EXPORT_UNAVAILABLE,
                sample_count=0,
                csv_path=str(csv_path),
                summary_path=str(summary_path),
                error=str(exc),
                window_start_utc=start.isoformat(),
                window_end_utc=end.isoformat(),
                summary=summary,
            )
        except OSError as write_exc:
            return WeatherExportResult(
                export_status=WEATHER_EXPORT_UNAVAILABLE,
                error=f"{exc}; write failed: {write_exc}",
                window_start_utc=start.isoformat(),
                window_end_utc=end.isoformat(),
                summary=summary,
            )

    filtered = filter_samples_window(api_samples, start=start, end=end)
    gaps = detect_gaps(
        filtered,
        gap_threshold_s=gap_threshold_s,
        window_start=start,
        window_end=end,
    )
    status, truncated = assess_export_status(
        api_sample_count=len(api_samples),
        history_limit=limit,
        gaps=gaps,
        window_start=start,
        filtered_samples=filtered,
    )
    summary = build_summary(
        session_id=session_id,
        window_start=start,
        window_end=end,
        samples=filtered,
        gaps=gaps,
        export_status=status,
        truncated=truncated,
        history_limit=limit,
    )
    rows = samples_to_csv_rows(filtered)
    try:
        csv_path, summary_path = write_weather_files(root, rows=rows, summary=summary)
    except OSError as exc:
        return WeatherExportResult(
            export_status=WEATHER_EXPORT_UNAVAILABLE,
            error=f"Schreiben fehlgeschlagen: {exc}",
            sample_count=len(filtered),
            truncated=truncated,
            gaps=gaps,
            window_start_utc=start.isoformat(),
            window_end_utc=end.isoformat(),
            summary=summary,
        )
    return WeatherExportResult(
        export_status=status,
        sample_count=len(filtered),
        csv_path=str(csv_path),
        summary_path=str(summary_path),
        gaps=gaps,
        truncated=truncated,
        window_start_utc=start.isoformat(),
        window_end_utc=end.isoformat(),
        summary=summary,
    )


def gap_threshold_from_poll_interval(poll_interval_s: float) -> float:
    poll = max(1.0, float(poll_interval_s or 60.0))
    return max(120.0, poll * 2.5)
