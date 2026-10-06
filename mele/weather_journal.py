"""Wetter-Journal: Forecast-Snapshots + lokale Beobachtungen (append-only).

Schema v1 — eine JSONL-Zeile pro Eintrag unter data/weather/journal/YYYY-MM/.

kind:
  forecast      GeoSphere NWP (oder spaeter andere Modelle)
  observation   lokale Station (Ecowitt WS90/GW1200, …)

Damit spaeter Replay/Verifikation: Prognose vs. Ist am Standort.
"""

from __future__ import annotations

import json
import math
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any


JOURNAL_SCHEMA = 1
SOURCE_GEOSPHERE = "geosphere.nwp-v2"
SOURCE_ECOWITT = "ecowitt.local"


def journal_root(weather_dir: Path) -> Path:
    return weather_dir / "journal"


def journal_path_for(weather_dir: Path, when: datetime | None = None) -> Path:
    stamp = (when or datetime.now(timezone.utc)).astimezone(timezone.utc)
    month_dir = journal_root(weather_dir) / stamp.strftime("%Y-%m")
    return month_dir / "weather-journal.jsonl"


def _finite(value: Any) -> float | None:
    if value is None or value == "":
        return None
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    if math.isnan(number) or math.isinf(number):
        return None
    return number


def _site(lat: float, lon: float, label: str = "") -> dict[str, Any]:
    return {
        "latitude_deg": round(float(lat), 6),
        "longitude_deg": round(float(lon), 6),
        "label": label or "",
    }


def _append_jsonl(path: Path, record: dict[str, Any]) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    line = json.dumps(record, ensure_ascii=False) + "\n"
    with path.open("a", encoding="utf-8") as handle:
        handle.write(line)
    return path


def iter_journal(
    weather_dir: Path,
    *,
    since: datetime | None = None,
    until: datetime | None = None,
    kind: str | None = None,
) -> list[dict[str, Any]]:
    """Liest Journal-Eintraege (fuer spaeteres Replay)."""
    root = journal_root(weather_dir)
    if not root.is_dir():
        return []
    rows: list[dict[str, Any]] = []
    for path in sorted(root.glob("*/weather-journal.jsonl")):
        try:
            text = path.read_text(encoding="utf-8")
        except OSError:
            continue
        for line in text.splitlines():
            line = line.strip()
            if not line:
                continue
            try:
                item = json.loads(line)
            except json.JSONDecodeError:
                continue
            if not isinstance(item, dict):
                continue
            if kind and item.get("kind") != kind:
                continue
            logged = item.get("logged_at")
            if logged and (since or until):
                try:
                    stamp = datetime.fromisoformat(str(logged).replace("Z", "+00:00"))
                except ValueError:
                    stamp = None
                if stamp is not None:
                    if since and stamp < since:
                        continue
                    if until and stamp > until:
                        continue
            rows.append(item)
    return rows


def last_entry(
    weather_dir: Path,
    *,
    kind: str,
    source: str,
    latitude_deg: float,
    longitude_deg: float,
) -> dict[str, Any] | None:
    rows = iter_journal(weather_dir, kind=kind)
    for item in reversed(rows):
        if item.get("source") != source:
            continue
        site = item.get("site") or {}
        try:
            if abs(float(site.get("latitude_deg")) - latitude_deg) > 1e-4:
                continue
            if abs(float(site.get("longitude_deg")) - longitude_deg) > 1e-4:
                continue
        except (TypeError, ValueError):
            continue
        return item
    return None


def should_skip_forecast(
    weather_dir: Path,
    *,
    latitude_deg: float,
    longitude_deg: float,
    interval_h: float,
    now: datetime | None = None,
    source: str = SOURCE_GEOSPHERE,
) -> bool:
    """True, wenn innerhalb des Intervalls schon ein Forecast geloggt wurde."""
    if interval_h <= 0:
        return False
    last = last_entry(
        weather_dir,
        kind="forecast",
        source=source,
        latitude_deg=latitude_deg,
        longitude_deg=longitude_deg,
    )
    if last is None:
        return False
    try:
        stamp = datetime.fromisoformat(str(last.get("logged_at")).replace("Z", "+00:00"))
    except (TypeError, ValueError):
        return False
    age = (now or datetime.now(timezone.utc)) - stamp.astimezone(timezone.utc)
    return age < timedelta(hours=float(interval_h) * 0.85)


def append_forecast(
    weather_dir: Path,
    forecast: dict[str, Any],
    *,
    latitude_deg: float,
    longitude_deg: float,
    label: str = "",
    source: str = SOURCE_GEOSPHERE,
    now: datetime | None = None,
) -> dict[str, Any]:
    """Haengt einen Forecast-Snapshot an (volle hours-Serie fuer spaeteres Replay)."""
    stamp = (now or datetime.now(timezone.utc)).astimezone(timezone.utc)
    hours = forecast.get("hours") if isinstance(forecast.get("hours"), list) else []
    record = {
        "schema": JOURNAL_SCHEMA,
        "kind": "forecast",
        "source": source,
        "logged_at": stamp.isoformat(),
        "site": _site(latitude_deg, longitude_deg, label),
        "forecast": {
            "reference_time": forecast.get("reference_time"),
            "fetched_at": forecast.get("fetched_at") or stamp.isoformat(),
            "offline": bool(forecast.get("offline")),
            "stale": bool(forecast.get("stale")),
            "grid_lat": forecast.get("grid_lat"),
            "grid_lon": forecast.get("grid_lon"),
            "attribution": forecast.get("attribution"),
            "hour_count": len(hours),
            "hours": hours,
        },
        "observation": None,
    }
    path = journal_path_for(weather_dir, stamp)
    _append_jsonl(path, record)
    record["path"] = str(path)
    return record


def append_observation(
    weather_dir: Path,
    observation: dict[str, Any],
    *,
    latitude_deg: float,
    longitude_deg: float,
    source: str = SOURCE_ECOWITT,
    label: str = "",
    now: datetime | None = None,
) -> dict[str, Any]:
    """Haengt eine lokale Messung an (Ecowitt / generisch)."""
    stamp = (now or datetime.now(timezone.utc)).astimezone(timezone.utc)
    when = observation.get("when") or stamp.isoformat()
    cleaned = {
        "when": when,
        "temp_c": _finite(observation.get("temp_c")),
        "humidity_pct": _finite(observation.get("humidity_pct")),
        "pressure_hpa": _finite(observation.get("pressure_hpa")),
        "wind_ms": _finite(observation.get("wind_ms")),
        "wind_dir_deg": _finite(observation.get("wind_dir_deg")),
        "gust_ms": _finite(observation.get("gust_ms")),
        "rain_mm": _finite(observation.get("rain_mm")),
        "rain_rate_mm_h": _finite(observation.get("rain_rate_mm_h")),
        "uvi": _finite(observation.get("uvi")),
        "lux": _finite(observation.get("lux")),
        "solarradiation_wm2": _finite(observation.get("solarradiation_wm2")),
        "dewpoint_c": _finite(observation.get("dewpoint_c")),
        "dewpoint_margin_c": _finite(observation.get("dewpoint_margin_c")),
        "indoor_temp_c": _finite(observation.get("indoor_temp_c")),
        "indoor_humidity_pct": _finite(observation.get("indoor_humidity_pct")),
    }
    raw = observation.get("raw")
    if isinstance(raw, dict):
        cleaned["raw"] = raw
    record = {
        "schema": JOURNAL_SCHEMA,
        "kind": "observation",
        "source": source,
        "logged_at": stamp.isoformat(),
        "site": _site(latitude_deg, longitude_deg, label),
        "forecast": None,
        "observation": cleaned,
    }
    path = journal_path_for(weather_dir, stamp)
    _append_jsonl(path, record)
    record["path"] = str(path)
    return record
