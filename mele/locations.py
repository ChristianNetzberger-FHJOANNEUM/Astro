"""Benannte Beobachterstandorte (Garten, mobile Einsaetze).

Getrennt von sites.json (GPS pro 360-Foto-Stem).
"""

from __future__ import annotations

import json
import os
import re
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


LOCATIONS_SCHEMA = 1
DEFAULT_ID = "garten"
DEFAULT_LABEL = "Garten"


@dataclass(frozen=True)
class ObserverLocation:
    id: str
    label: str
    latitude_deg: float
    longitude_deg: float
    elevation_m: float = 0.0
    updated: str = ""


def locations_path(horizon_dir: Path) -> Path:
    return horizon_dir / "locations.json"


def _slug(value: str) -> str:
    text = str(value or "").strip().lower()
    text = re.sub(r"[^a-z0-9_\-]+", "-", text, flags=re.IGNORECASE)
    text = re.sub(r"-+", "-", text).strip("-_")
    return text or DEFAULT_ID


def _empty_payload() -> dict[str, Any]:
    return {"version": LOCATIONS_SCHEMA, "active": "", "locations": []}


def _parse_location(item: dict[str, Any]) -> ObserverLocation | None:
    try:
        lat = float(item["latitude_deg"])
        lon = float(item["longitude_deg"])
    except (KeyError, TypeError, ValueError):
        return None
    label = str(item.get("label") or item.get("name") or item.get("id") or "").strip()
    loc_id = _slug(str(item.get("id") or label))
    if not label:
        label = loc_id
    try:
        elev = float(item.get("elevation_m") or 0.0)
    except (TypeError, ValueError):
        elev = 0.0
    return ObserverLocation(
        id=loc_id,
        label=label,
        latitude_deg=lat,
        longitude_deg=lon,
        elevation_m=elev,
        updated=str(item.get("updated") or ""),
    )


def load_locations_index(horizon_dir: Path) -> dict[str, Any]:
    path = locations_path(horizon_dir)
    if not path.is_file():
        return _empty_payload()
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return _empty_payload()
    if not isinstance(raw, dict):
        return _empty_payload()
    rows = raw.get("locations") if isinstance(raw.get("locations"), list) else []
    cleaned: list[dict[str, Any]] = []
    seen: set[str] = set()
    for item in rows:
        if not isinstance(item, dict):
            continue
        loc = _parse_location(item)
        if loc is None or loc.id in seen:
            continue
        seen.add(loc.id)
        cleaned.append(
            {
                "id": loc.id,
                "label": loc.label,
                "latitude_deg": round(loc.latitude_deg, 6),
                "longitude_deg": round(loc.longitude_deg, 6),
                "elevation_m": round(loc.elevation_m, 1),
                "updated": loc.updated,
            }
        )
    active = _slug(str(raw.get("active") or "")) if raw.get("active") else ""
    if active and active not in seen:
        active = cleaned[0]["id"] if cleaned else ""
    return {"version": LOCATIONS_SCHEMA, "active": active, "locations": cleaned}


def save_locations_index(horizon_dir: Path, index: dict[str, Any]) -> dict[str, Any]:
    rows = index.get("locations") if isinstance(index.get("locations"), list) else []
    payload_rows: list[dict[str, Any]] = []
    seen: set[str] = set()
    for item in rows:
        if not isinstance(item, dict):
            continue
        loc = _parse_location(item)
        if loc is None or loc.id in seen:
            continue
        seen.add(loc.id)
        payload_rows.append(
            {
                "id": loc.id,
                "label": loc.label,
                "latitude_deg": round(loc.latitude_deg, 6),
                "longitude_deg": round(loc.longitude_deg, 6),
                "elevation_m": round(loc.elevation_m, 1),
                "updated": loc.updated or datetime.now(timezone.utc).isoformat(),
            }
        )
    active = str(index.get("active") or "")
    if active:
        active = _slug(active)
    if active and active not in seen:
        active = payload_rows[0]["id"] if payload_rows else ""
    payload = {"version": LOCATIONS_SCHEMA, "active": active, "locations": payload_rows}
    path = locations_path(horizon_dir)
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(payload, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    os.replace(tmp, path)
    return payload


def list_locations(horizon_dir: Path) -> list[ObserverLocation]:
    index = load_locations_index(horizon_dir)
    out: list[ObserverLocation] = []
    for item in index["locations"]:
        loc = _parse_location(item)
        if loc is not None:
            out.append(loc)
    return out


def get_active_location(horizon_dir: Path) -> ObserverLocation | None:
    index = load_locations_index(horizon_dir)
    active = str(index.get("active") or "")
    for item in index.get("locations") or []:
        if isinstance(item, dict) and _slug(str(item.get("id") or "")) == active:
            return _parse_location(item)
    return None


def get_location(horizon_dir: Path, location_id: str) -> ObserverLocation | None:
    want = _slug(location_id)
    for loc in list_locations(horizon_dir):
        if loc.id == want:
            return loc
    return None


def upsert_location(
    horizon_dir: Path,
    *,
    label: str,
    latitude_deg: float,
    longitude_deg: float,
    elevation_m: float = 0.0,
    location_id: str | None = None,
    make_active: bool = True,
) -> ObserverLocation:
    index = load_locations_index(horizon_dir)
    loc_id = _slug(location_id or label)
    nice = (label or loc_id).strip() or loc_id
    stamp = datetime.now(timezone.utc).isoformat()
    found = False
    for item in index["locations"]:
        if item.get("id") == loc_id:
            item["label"] = nice
            item["latitude_deg"] = round(float(latitude_deg), 6)
            item["longitude_deg"] = round(float(longitude_deg), 6)
            item["elevation_m"] = round(float(elevation_m or 0.0), 1)
            item["updated"] = stamp
            found = True
            break
    if not found:
        index["locations"].append(
            {
                "id": loc_id,
                "label": nice,
                "latitude_deg": round(float(latitude_deg), 6),
                "longitude_deg": round(float(longitude_deg), 6),
                "elevation_m": round(float(elevation_m or 0.0), 1),
                "updated": stamp,
            }
        )
    if make_active:
        index["active"] = loc_id
    save_locations_index(horizon_dir, index)
    return ObserverLocation(
        id=loc_id,
        label=nice,
        latitude_deg=float(latitude_deg),
        longitude_deg=float(longitude_deg),
        elevation_m=float(elevation_m or 0.0),
        updated=stamp,
    )


def set_active_location(horizon_dir: Path, location_id: str) -> ObserverLocation:
    loc = get_location(horizon_dir, location_id)
    if loc is None:
        raise ValueError(f"Unbekannter Standort: {location_id}")
    index = load_locations_index(horizon_dir)
    index["active"] = loc.id
    save_locations_index(horizon_dir, index)
    return loc


def ensure_default_location(
    horizon_dir: Path,
    *,
    latitude_deg: float | None,
    longitude_deg: float | None,
    elevation_m: float = 0.0,
    label: str = DEFAULT_LABEL,
) -> ObserverLocation | None:
    """Legt 'Garten' aus Config an, falls Liste leer und Koordinaten da sind."""
    existing = list_locations(horizon_dir)
    if existing:
        return get_active_location(horizon_dir) or existing[0]
    if latitude_deg is None or longitude_deg is None:
        return None
    return upsert_location(
        horizon_dir,
        label=label,
        latitude_deg=float(latitude_deg),
        longitude_deg=float(longitude_deg),
        elevation_m=float(elevation_m or 0.0),
        location_id=DEFAULT_ID,
        make_active=True,
    )
