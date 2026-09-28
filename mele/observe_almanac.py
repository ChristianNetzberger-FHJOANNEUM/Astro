"""Sichtbarkeit / Almanach: Horizont ∩ Nacht, benannte Beobachtungslisten."""

from __future__ import annotations

import json
import re
import sqlite3
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from mele.catalog import (
    catalog_db_path,
    catalog_ready,
    object_track,
    visibility_summary,
)
from mele.horizon import HorizonProfile


TONIGHT_SCHEMA = 1
DEFAULT_LIST_ID = "default"
DEFAULT_LIST_LABEL = "Standard"

ALMANAC_PREF_DEFAULTS = {
    "sort_mode": "observable_h",
    "only_selected": False,
    "messier": True,
    "stars": True,
    "star_mag": 3.0,
    "min_obs_min": 30.0,
    "active_list": DEFAULT_LIST_ID,
    "time_format": "24h",
}


def _slug(value: str) -> str:
    text = str(value or "").strip().lower()
    text = re.sub(r"[^a-z0-9_\-]+", "-", text, flags=re.IGNORECASE)
    text = re.sub(r"-+", "-", text).strip("-_")
    return text or DEFAULT_LIST_ID


def lists_dir(horizon_dir: Path) -> Path:
    return horizon_dir / "observe-lists"


def lists_index_path(horizon_dir: Path) -> Path:
    return lists_dir(horizon_dir) / "index.json"


def list_file(horizon_dir: Path, list_id: str) -> Path:
    return lists_dir(horizon_dir) / f"{_slug(list_id)}.json"


def almanac_prefs_path(horizon_dir: Path) -> Path:
    return horizon_dir / "almanac-prefs.json"


def load_almanac_prefs(horizon_dir: Path) -> dict[str, Any]:
    data = dict(ALMANAC_PREF_DEFAULTS)
    path = almanac_prefs_path(horizon_dir)
    if path.is_file():
        try:
            raw = json.loads(path.read_text(encoding="utf-8"))
            if isinstance(raw, dict):
                data.update(raw)
        except (OSError, json.JSONDecodeError):
            pass
    try:
        data["star_mag"] = float(data.get("star_mag", 3.0))
    except (TypeError, ValueError):
        data["star_mag"] = 3.0
    try:
        data["min_obs_min"] = float(data.get("min_obs_min", 30.0))
    except (TypeError, ValueError):
        data["min_obs_min"] = 30.0
    data["sort_mode"] = str(data.get("sort_mode") or "observable_h")
    data["only_selected"] = bool(data.get("only_selected"))
    data["messier"] = bool(data.get("messier", True))
    data["stars"] = bool(data.get("stars", True))
    data["active_list"] = _slug(str(data.get("active_list") or DEFAULT_LIST_ID))
    fmt = str(data.get("time_format") or "24h").lower()
    data["time_format"] = "12h" if fmt in ("12h", "12", "am/pm") else "24h"
    return data


def save_almanac_prefs(horizon_dir: Path, updates: dict[str, Any] | None = None) -> dict[str, Any]:
    data = load_almanac_prefs(horizon_dir)
    if updates:
        data.update(updates)
    fmt = str(data.get("time_format") or "24h").lower()
    out = {
        "sort_mode": str(data.get("sort_mode") or "observable_h"),
        "only_selected": bool(data.get("only_selected")),
        "messier": bool(data.get("messier", True)),
        "stars": bool(data.get("stars", True)),
        "active_list": _slug(str(data.get("active_list") or DEFAULT_LIST_ID)),
        "time_format": "12h" if fmt in ("12h", "12", "am/pm") else "24h",
    }
    try:
        out["star_mag"] = float(data.get("star_mag", 3.0))
    except (TypeError, ValueError):
        out["star_mag"] = 3.0
    try:
        out["min_obs_min"] = float(data.get("min_obs_min", 30.0))
    except (TypeError, ValueError):
        out["min_obs_min"] = 30.0
    path = almanac_prefs_path(horizon_dir)
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(out, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    tmp.replace(path)
    return out


def _empty_index() -> dict[str, Any]:
    return {
        "active": DEFAULT_LIST_ID,
        "lists": [{"id": DEFAULT_LIST_ID, "label": DEFAULT_LIST_LABEL}],
    }


def _clean_objects(raw_objects: Any) -> list[dict[str, Any]]:
    if not isinstance(raw_objects, list):
        return []
    cleaned: list[dict[str, Any]] = []
    for item in raw_objects:
        if not isinstance(item, dict):
            continue
        key = str(item.get("key") or "").strip()
        if not key:
            continue
        cleaned.append(
            {
                "key": key,
                "name": str(item.get("name") or key),
                "kind": str(item.get("kind") or ""),
                "mag": item.get("mag"),
                "ra": item.get("ra"),
                "dec": item.get("dec"),
            }
        )
    return cleaned


def _write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(payload, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    tmp.replace(path)


def save_lists_index(horizon_dir: Path, index: dict[str, Any]) -> dict[str, Any]:
    lists = index.get("lists") if isinstance(index.get("lists"), list) else []
    cleaned = []
    seen: set[str] = set()
    for item in lists:
        if not isinstance(item, dict):
            continue
        list_id = _slug(str(item.get("id") or ""))
        if not list_id or list_id in seen:
            continue
        seen.add(list_id)
        cleaned.append({"id": list_id, "label": str(item.get("label") or list_id)})
    if not cleaned:
        cleaned = [{"id": DEFAULT_LIST_ID, "label": DEFAULT_LIST_LABEL}]
    active = _slug(str(index.get("active") or cleaned[0]["id"]))
    if active not in {item["id"] for item in cleaned}:
        active = cleaned[0]["id"]
    payload = {"active": active, "lists": cleaned}
    _write_json(lists_index_path(horizon_dir), payload)
    return payload


def load_lists_index(horizon_dir: Path) -> dict[str, Any]:
    ensure_observe_lists(horizon_dir)
    path = lists_index_path(horizon_dir)
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return _empty_index()
    if not isinstance(raw, dict):
        return _empty_index()
    return save_lists_index(horizon_dir, raw)


def save_tonight(
    horizon_dir: Path,
    objects: list[dict[str, Any]],
    *,
    list_id: str | None = None,
    label: str = "",
    stem: str = "",
    when: datetime | None = None,
    latitude_deg: float | None = None,
    longitude_deg: float | None = None,
) -> dict[str, Any]:
    ensure_observe_lists(horizon_dir)
    index = load_lists_index(horizon_dir)
    slug = _slug(list_id or index.get("active") or DEFAULT_LIST_ID)
    nice = (label or next((item["label"] for item in index["lists"] if item["id"] == slug), slug)).strip()
    if slug not in {item["id"] for item in index["lists"]}:
        index["lists"].append({"id": slug, "label": nice or slug})
    index["active"] = slug
    save_lists_index(horizon_dir, index)
    save_almanac_prefs(horizon_dir, {"active_list": slug})

    path = list_file(horizon_dir, slug)
    stamp = (when or datetime.now(timezone.utc)).astimezone(timezone.utc)
    cleaned = _clean_objects(objects)
    payload = {
        "schema": TONIGHT_SCHEMA,
        "list_id": slug,
        "label": nice or slug,
        "stem": stem or "",
        "when": stamp.isoformat(),
        "latitude_deg": latitude_deg,
        "longitude_deg": longitude_deg,
        "updated_at": datetime.now(timezone.utc).isoformat(),
        "objects": cleaned,
    }
    _write_json(path, payload)
    payload["path"] = str(path)
    payload["active"] = slug
    return payload


def load_tonight(
    horizon_dir: Path,
    stem: str = "",
    *,
    list_id: str | None = None,
) -> dict[str, Any]:
    """Laedt aktive oder genannte Beobachtungsliste (Objekt-IDs, nicht eingefrorene Kennzahlen)."""
    ensure_observe_lists(horizon_dir)
    index = load_lists_index(horizon_dir)
    slug = _slug(list_id or index.get("active") or DEFAULT_LIST_ID)
    path = list_file(horizon_dir, slug)
    label = next((item["label"] for item in index["lists"] if item["id"] == slug), slug)
    if not path.is_file():
        return {
            "schema": TONIGHT_SCHEMA,
            "list_id": slug,
            "label": label,
            "stem": stem or "",
            "objects": [],
            "updated_at": None,
            "path": str(path),
            "active": index.get("active"),
            "lists": index.get("lists"),
        }
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        raw = {}
    if not isinstance(raw, dict):
        raw = {}
    return {
        "schema": TONIGHT_SCHEMA,
        "list_id": slug,
        "label": str(raw.get("label") or label),
        "stem": str(raw.get("stem") or stem or ""),
        "when": raw.get("when"),
        "latitude_deg": raw.get("latitude_deg"),
        "longitude_deg": raw.get("longitude_deg"),
        "updated_at": raw.get("updated_at"),
        "objects": _clean_objects(raw.get("objects")),
        "path": str(path),
        "active": index.get("active"),
        "lists": index.get("lists"),
    }


def ensure_observe_lists(horizon_dir: Path) -> dict[str, Any]:
    """Legt observe-lists an; migriert Legacy-tonight.json einmalig."""
    root = lists_dir(horizon_dir)
    root.mkdir(parents=True, exist_ok=True)
    index_path = lists_index_path(horizon_dir)
    default_path = list_file(horizon_dir, DEFAULT_LIST_ID)
    if not index_path.is_file():
        _write_json(index_path, _empty_index())
    if not default_path.is_file():
        legacy_objects: list[dict[str, Any]] = []
        candidates = sorted(horizon_dir.glob("*.tonight.json"))
        plain = horizon_dir / "tonight.json"
        if plain.is_file():
            candidates = [plain, *candidates]
        for path in candidates:
            try:
                raw = json.loads(path.read_text(encoding="utf-8"))
            except (OSError, json.JSONDecodeError):
                continue
            if isinstance(raw, dict) and isinstance(raw.get("objects"), list) and raw["objects"]:
                legacy_objects = _clean_objects(raw["objects"])
                break
        payload = {
            "schema": TONIGHT_SCHEMA,
            "list_id": DEFAULT_LIST_ID,
            "label": DEFAULT_LIST_LABEL,
            "stem": "",
            "when": None,
            "updated_at": datetime.now(timezone.utc).isoformat(),
            "objects": legacy_objects,
        }
        _write_json(default_path, payload)
    try:
        raw = json.loads(index_path.read_text(encoding="utf-8"))
        if isinstance(raw, dict):
            return save_lists_index(horizon_dir, raw)
    except (OSError, json.JSONDecodeError):
        pass
    return save_lists_index(horizon_dir, _empty_index())


def upsert_list(
    horizon_dir: Path,
    *,
    list_id: str,
    label: str = "",
    make_active: bool = True,
) -> dict[str, Any]:
    ensure_observe_lists(horizon_dir)
    index = load_lists_index(horizon_dir)
    slug = _slug(list_id)
    nice = (label or list_id or slug).strip() or slug
    found = False
    for item in index["lists"]:
        if item["id"] == slug:
            item["label"] = nice
            found = True
            break
    if not found:
        index["lists"].append({"id": slug, "label": nice})
        if not list_file(horizon_dir, slug).is_file():
            save_tonight(horizon_dir, [], list_id=slug, label=nice)
    if make_active:
        index["active"] = slug
        save_almanac_prefs(horizon_dir, {"active_list": slug})
    return save_lists_index(horizon_dir, index)


def set_active_list(horizon_dir: Path, list_id: str) -> dict[str, Any]:
    index = load_lists_index(horizon_dir)
    slug = _slug(list_id)
    if slug not in {item["id"] for item in index["lists"]}:
        raise ValueError(f"Unbekannte Liste: {list_id}")
    index["active"] = slug
    save_lists_index(horizon_dir, index)
    save_almanac_prefs(horizon_dir, {"active_list": slug})
    return index


def list_almanac_targets(
    *,
    db_path: Path | None = None,
    messier: bool = True,
    star_mag_max: float | None = 3.0,
) -> list[dict[str, Any]]:
    """Kandidaten aus sky.sqlite (Messier + helle Sterne)."""
    path = catalog_db_path(db_path)
    if not catalog_ready(path):
        return []
    rows: list[dict[str, Any]] = []
    with sqlite3.connect(path) as conn:
        conn.row_factory = sqlite3.Row
        if messier:
            for row in conn.execute(
                "SELECT key, name, type, ra_deg, dec_deg, mag, messier FROM dso "
                "WHERE messier IS NOT NULL ORDER BY messier"
            ):
                rows.append(
                    {
                        "key": row["key"],
                        "name": row["name"] or row["key"],
                        "kind": "messier",
                        "type": row["type"],
                        "ra": float(row["ra_deg"]),
                        "dec": float(row["dec_deg"]),
                        "mag": float(row["mag"]) if row["mag"] is not None else None,
                    }
                )
        if star_mag_max is not None:
            for row in conn.execute(
                "SELECT hip, name, con, ra_deg, dec_deg, mag FROM stars "
                "WHERE mag IS NOT NULL AND mag <= ? ORDER BY mag ASC",
                (float(star_mag_max),),
            ):
                hip = int(row["hip"]) if row["hip"] is not None else None
                name = row["name"] or (f"HIP {hip}" if hip is not None else "Stern")
                key = f"HIP{hip}" if hip is not None else name
                rows.append(
                    {
                        "key": key,
                        "name": name,
                        "kind": "star",
                        "type": "star",
                        "con": row["con"],
                        "hip": hip,
                        "ra": float(row["ra_deg"]),
                        "dec": float(row["dec_deg"]),
                        "mag": float(row["mag"]) if row["mag"] is not None else None,
                    }
                )
    return rows


def build_almanac(
    *,
    latitude_deg: float,
    longitude_deg: float,
    when: datetime,
    profile: HorizonProfile | None = None,
    db_path: Path | None = None,
    messier: bool = True,
    star_mag_max: float | None = 3.0,
    min_observable_min: float = 0.0,
    step_min: int = 30,
    tz_offset_min: int | None = None,
) -> dict[str, Any]:
    """Tabelle: Sichtbarkeit je Objekt fuer die Beobachtungsnacht von `when`."""
    targets = list_almanac_targets(
        db_path=db_path,
        messier=messier,
        star_mag_max=star_mag_max,
    )
    entries: list[dict[str, Any]] = []
    for target in targets:
        track = object_track(
            ra_deg=float(target["ra"]),
            dec_deg=float(target["dec"]),
            latitude_deg=latitude_deg,
            longitude_deg=longitude_deg,
            when=when,
            profile=profile,
            step_min=step_min,
            tz_offset_min=tz_offset_min,
        )
        summary = visibility_summary(track)
        if summary["observable_min"] < float(min_observable_min):
            continue
        entries.append(
            {
                **target,
                "above_horizon_min": summary["above_horizon_min"],
                "above_horizon_h": summary["above_horizon_h"],
                "above_max_alt": summary["above_max_alt"],
                "observable_min": summary["observable_min"],
                "observable_h": summary["observable_h"],
                "observable_max_alt": summary["observable_max_alt"],
                "observable_windows": summary["observable_windows"],
            }
        )
    entries.sort(
        key=lambda row: (
            -(row.get("observable_min") or 0.0),
            -(row.get("observable_max_alt") or -99.0),
            str(row.get("name") or ""),
        )
    )
    return {
        "when": when.astimezone(timezone.utc).isoformat(),
        "latitude_deg": latitude_deg,
        "longitude_deg": longitude_deg,
        "messier": messier,
        "star_mag_max": star_mag_max,
        "min_observable_min": min_observable_min,
        "step_min": step_min,
        "tz_offset_min": tz_offset_min,
        "count": len(entries),
        "entries": entries,
    }


def tonight_markers(
    horizon_dir: Path,
    *,
    stem: str = "",
    list_id: str | None = None,
    latitude_deg: float,
    longitude_deg: float,
    when: datetime,
    profile: HorizonProfile | None = None,
) -> dict[str, Any]:
    """Listen-Objekte mit Az/h zur aktuellen Zeit (fuer 360-Highlight)."""
    from mele.sky import radec_to_az_alt

    payload = load_tonight(horizon_dir, stem, list_id=list_id)
    stamp = when.astimezone(timezone.utc)
    markers: list[dict[str, Any]] = []
    for item in payload.get("objects") or []:
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
                "key": item.get("key"),
                "id": item.get("key"),
                "name": item.get("name") or item.get("key"),
                "kind": item.get("kind") or "tonight",
                "mag": item.get("mag"),
                "ra": float(ra),
                "dec": float(dec),
                "az": round(float(az), 3),
                "alt": round(float(alt), 3),
                "above": bool(above),
            }
        )
    return {
        "stem": stem,
        "list_id": payload.get("list_id"),
        "label": payload.get("label"),
        "when": stamp.isoformat(),
        "count": len(markers),
        "markers": markers,
        "path": payload.get("path"),
    }
