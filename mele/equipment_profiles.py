"""MeLE Equipment-Configurations → PHD2-Profil-Zuordnung.

Persistenz: ``{horizon_dir}/equipment-profiles.json``.
Keine eigene Kalibrierungsmatrix — nur Mapping und optionale Optik-Metadaten.
"""

from __future__ import annotations

import json
import re
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

SCHEMA = 1

# arcsec/pixel ≈ 206.265 * pixel_size_um / focal_length_mm
ARCSEC_FACTOR = 206.265


def equipment_profiles_path(horizon_dir: Path) -> Path:
    return Path(horizon_dir) / "equipment-profiles.json"


def _utc_now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def _write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(payload, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    tmp.replace(path)


def _finite_positive(value: Any) -> float | None:
    if value is None or value == "":
        return None
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    if number != number or number <= 0:  # NaN or non-positive
        return None
    return number


def image_scale_arcsec_px(
    *,
    pixel_size_um: Any,
    focal_length_mm: Any,
) -> float | None:
    """MeLE-Hinweismaßstab (nicht PHD2 get_pixel_scale)."""
    px = _finite_positive(pixel_size_um)
    fl = _finite_positive(focal_length_mm)
    if px is None or fl is None:
        return None
    return ARCSEC_FACTOR * px / fl


def _slugify(name: str) -> str:
    base = re.sub(r"[^a-zA-Z0-9]+", "-", (name or "").strip().lower()).strip("-")
    return (base or "profile")[:48]


def _clean_profile(raw: Any, *, require_id: bool = False) -> dict[str, Any] | None:
    if not isinstance(raw, dict):
        return None
    name = str(raw.get("name") or "").strip()
    pid = str(raw.get("id") or "").strip()
    if require_id and not pid:
        return None
    if not pid:
        pid = _slugify(name) + "-" + uuid.uuid4().hex[:6]
    if not name:
        name = pid
    phd2_id = raw.get("phd2_profile_id")
    try:
        phd2_profile_id = int(phd2_id) if phd2_id is not None and str(phd2_id).strip() != "" else None
    except (TypeError, ValueError):
        phd2_profile_id = None
    fl = _finite_positive(raw.get("guiding_focal_length_mm"))
    pix = _finite_positive(raw.get("guiding_pixel_size_um"))
    item: dict[str, Any] = {
        "id": pid,
        "name": name,
        "mount_id": str(raw.get("mount_id") or "").strip(),
        "imaging_optics_id": str(raw.get("imaging_optics_id") or "").strip(),
        "guiding_camera_id": str(raw.get("guiding_camera_id") or "").strip(),
        "guiding_scope_id": str(raw.get("guiding_scope_id") or "").strip(),
        "guiding_focal_length_mm": fl,
        "guiding_pixel_size_um": pix,
        "phd2_profile_name": str(raw.get("phd2_profile_name") or "").strip(),
        "phd2_profile_id": phd2_profile_id,
        "mele_image_scale_arcsec_px": image_scale_arcsec_px(
            pixel_size_um=pix,
            focal_length_mm=fl,
        ),
    }
    return item


def empty_store(path: Path) -> dict[str, Any]:
    return {
        "schema": SCHEMA,
        "updated_at": None,
        "active_id": None,
        "profiles": [],
        "path": str(path),
    }


def load_equipment_profiles(horizon_dir: Path) -> dict[str, Any]:
    path = equipment_profiles_path(horizon_dir)
    empty = empty_store(path)
    if not path.is_file():
        return empty
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return empty
    if not isinstance(raw, dict):
        return empty
    profiles: list[dict[str, Any]] = []
    seen: set[str] = set()
    for entry in raw.get("profiles") or []:
        item = _clean_profile(entry, require_id=True)
        if item is None or item["id"] in seen:
            continue
        seen.add(item["id"])
        profiles.append(item)
    profiles.sort(key=lambda p: (str(p.get("name") or "").lower(), p["id"]))
    active_id = str(raw.get("active_id") or "").strip() or None
    if active_id and active_id not in seen:
        active_id = None
    return {
        "schema": SCHEMA,
        "updated_at": raw.get("updated_at"),
        "active_id": active_id,
        "profiles": profiles,
        "path": str(path),
    }


def save_equipment_profiles(
    horizon_dir: Path,
    *,
    profiles: list[dict[str, Any]],
    active_id: str | None,
) -> dict[str, Any]:
    path = equipment_profiles_path(horizon_dir)
    cleaned: list[dict[str, Any]] = []
    seen: set[str] = set()
    for entry in profiles:
        item = _clean_profile(entry, require_id=True)
        if item is None or item["id"] in seen:
            continue
        seen.add(item["id"])
        cleaned.append(item)
    cleaned.sort(key=lambda p: (str(p.get("name") or "").lower(), p["id"]))
    aid = str(active_id or "").strip() or None
    if aid and aid not in seen:
        aid = None
    payload = {
        "schema": SCHEMA,
        "updated_at": _utc_now(),
        "active_id": aid,
        "profiles": cleaned,
    }
    _write_json(path, payload)
    return load_equipment_profiles(horizon_dir)


def upsert_equipment_profile(horizon_dir: Path, raw: dict[str, Any]) -> dict[str, Any]:
    data = load_equipment_profiles(horizon_dir)
    item = _clean_profile(raw, require_id=bool(str(raw.get("id") or "").strip()))
    if item is None:
        return {"ok": False, "error": "ungültiges Profil", **data}
    profiles = [p for p in data["profiles"] if p["id"] != item["id"]]
    profiles.append(item)
    saved = save_equipment_profiles(
        horizon_dir,
        profiles=profiles,
        active_id=data.get("active_id"),
    )
    return {"ok": True, "profile": item, **saved}


def delete_equipment_profile(horizon_dir: Path, profile_id: str) -> dict[str, Any]:
    data = load_equipment_profiles(horizon_dir)
    pid = str(profile_id or "").strip()
    profiles = [p for p in data["profiles"] if p["id"] != pid]
    active = data.get("active_id")
    if active == pid:
        active = None
    saved = save_equipment_profiles(horizon_dir, profiles=profiles, active_id=active)
    return {"ok": True, "deleted": pid, **saved}


def set_active_equipment_profile(horizon_dir: Path, profile_id: str) -> dict[str, Any]:
    data = load_equipment_profiles(horizon_dir)
    pid = str(profile_id or "").strip()
    match = next((p for p in data["profiles"] if p["id"] == pid), None)
    if match is None:
        return {"ok": False, "error": f"Profil nicht gefunden: {pid}", **data}
    saved = save_equipment_profiles(
        horizon_dir,
        profiles=data["profiles"],
        active_id=pid,
    )
    return {"ok": True, "active": match, **saved}


def get_active_equipment_profile(horizon_dir: Path) -> dict[str, Any] | None:
    data = load_equipment_profiles(horizon_dir)
    aid = data.get("active_id")
    if not aid:
        return None
    return next((p for p in data["profiles"] if p["id"] == aid), None)
