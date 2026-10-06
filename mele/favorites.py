"""Viewer-Favoriten (360°-Pins) — getrennt von Observe-/Tonight-Listen.

Persistenz: ``{horizon_dir}/favorites.json``.
Nur Katalog-Keys + Anzeige-Metadaten; Az/h werden zur Laufzeit per Resolve berechnet.
"""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from mele.sky import radec_to_az_alt
from mele.horizon import HorizonProfile

FAVORITES_SCHEMA = 1


def favorites_path(horizon_dir: Path) -> Path:
    return Path(horizon_dir) / "favorites.json"


def _utc_now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def _write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(payload, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    tmp.replace(path)


def _clean_item(raw: Any) -> dict[str, Any] | None:
    if not isinstance(raw, dict):
        return None
    key = str(raw.get("key") or raw.get("id") or "").strip()
    if not key:
        return None
    item: dict[str, Any] = {
        "key": key,
        "name": str(raw.get("name") or key).strip() or key,
        "kind": str(raw.get("kind") or "").strip(),
    }
    for field in ("type", "mag_band", "con"):
        val = raw.get(field)
        if val is not None and str(val).strip():
            item[field] = str(val).strip()
    if raw.get("mag") is not None:
        try:
            item["mag"] = float(raw["mag"])
        except (TypeError, ValueError):
            pass
    if raw.get("hip") is not None:
        try:
            item["hip"] = int(raw["hip"])
        except (TypeError, ValueError):
            pass
    for field in ("ra", "dec"):
        if raw.get(field) is not None:
            try:
                item[field] = float(raw[field])
            except (TypeError, ValueError):
                pass
    added = str(raw.get("added_utc") or "").strip()
    item["added_utc"] = added or _utc_now()
    return item


def load_favorites(horizon_dir: Path) -> dict[str, Any]:
    path = favorites_path(horizon_dir)
    empty = {
        "schema": FAVORITES_SCHEMA,
        "updated_at": None,
        "objects": [],
        "path": str(path),
    }
    if not path.is_file():
        return empty
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return empty
    if not isinstance(raw, dict):
        return empty
    objects: list[dict[str, Any]] = []
    seen: set[str] = set()
    for entry in raw.get("objects") or []:
        item = _clean_item(entry)
        if item is None or item["key"] in seen:
            continue
        seen.add(item["key"])
        objects.append(item)
    objects.sort(key=lambda o: (str(o.get("name") or "").lower(), o["key"]))
    return {
        "schema": FAVORITES_SCHEMA,
        "updated_at": raw.get("updated_at"),
        "objects": objects,
        "path": str(path),
    }


def save_favorites(horizon_dir: Path, objects: list[dict[str, Any]]) -> dict[str, Any]:
    cleaned: list[dict[str, Any]] = []
    seen: set[str] = set()
    for entry in objects:
        item = _clean_item(entry)
        if item is None or item["key"] in seen:
            continue
        seen.add(item["key"])
        cleaned.append(item)
    cleaned.sort(key=lambda o: (str(o.get("name") or "").lower(), o["key"]))
    payload = {
        "schema": FAVORITES_SCHEMA,
        "updated_at": _utc_now(),
        "objects": cleaned,
    }
    path = favorites_path(horizon_dir)
    _write_json(path, payload)
    payload["path"] = str(path)
    return payload


def add_favorite(horizon_dir: Path, entry: dict[str, Any]) -> dict[str, Any]:
    data = load_favorites(horizon_dir)
    item = _clean_item(entry)
    if item is None:
        raise ValueError("Favorit braucht key")
    objects = [o for o in data["objects"] if o["key"] != item["key"]]
    # Bestehendes added_utc behalten wenn schon vorhanden
    prev = next((o for o in data["objects"] if o["key"] == item["key"]), None)
    if prev and prev.get("added_utc"):
        item["added_utc"] = prev["added_utc"]
    else:
        item["added_utc"] = _utc_now()
    objects.append(item)
    saved = save_favorites(horizon_dir, objects)
    return {"ok": True, "added": item, **saved}


def remove_favorite(horizon_dir: Path, key: str) -> dict[str, Any]:
    want = str(key or "").strip()
    if not want:
        raise ValueError("key fehlt")
    data = load_favorites(horizon_dir)
    before = len(data["objects"])
    objects = [o for o in data["objects"] if o["key"] != want]
    saved = save_favorites(horizon_dir, objects)
    return {
        "ok": True,
        "removed": want,
        "changed": len(objects) < before,
        **saved,
    }


def is_favorite(horizon_dir: Path, key: str) -> bool:
    want = str(key or "").strip()
    if not want:
        return False
    return any(o["key"] == want for o in load_favorites(horizon_dir)["objects"])


def favorite_markers(
    horizon_dir: Path,
    *,
    latitude_deg: float,
    longitude_deg: float,
    when: datetime,
    profile: HorizonProfile | None = None,
) -> dict[str, Any]:
    """Favoriten mit aktueller Az/h (fuer 360-Highlight-Layer)."""
    stamp = when.astimezone(timezone.utc)
    data = load_favorites(horizon_dir)
    markers: list[dict[str, Any]] = []
    for item in data["objects"]:
        ra = item.get("ra")
        dec = item.get("dec")
        if ra is None or dec is None:
            continue
        try:
            az, alt = radec_to_az_alt(
                float(ra),
                float(dec),
                latitude_deg,
                longitude_deg,
                stamp,
            )
        except (TypeError, ValueError):
            continue
        above = True
        if profile is not None and profile.points:
            above = float(alt) > profile.altitude_at(float(az))
        markers.append(
            {
                **item,
                "id": item["key"],
                "az": round(float(az), 3),
                "alt": round(float(alt), 3),
                "above": bool(above),
                "favorite": True,
            }
        )
    return {
        "when": stamp.isoformat(),
        "count": len(markers),
        "markers": markers,
        "path": data.get("path"),
    }
