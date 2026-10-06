"""Anzeige-Einstellungen fuer die 360-Ansicht, sessionuebergreifend."""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any

from mele.catalog import DSO_TYPE_GROUP_KEYS, normalize_dso_type_groups


DEFAULTS = {
    "star_scale": 1.0,
    "mag_limit": 5.5,
    "track_hours": False,
    "grid": False,
    "grid_step": 10,
    "grid_eq": False,
    "grid_ecliptic": False,
    "horizon_points": True,
    "tonight": False,
    "show_favorites": False,
    "show_stars": True,
    "show_const": True,
    "show_messier": True,
    "show_ngc": False,
    "show_planets": True,
    # OpenNGC-UI-Gruppen; alle = kein Filter
    "dso_types": list(DSO_TYPE_GROUP_KEYS),
}


def prefs_path(horizon_dir: Path) -> Path:
    return horizon_dir / "ui-prefs.json"


def _as_bool(value: Any, default: bool = False) -> bool:
    if value is None:
        return default
    return value in (True, 1, "1", "true", "True")


def _normalize_dso_types(value: Any) -> list[str]:
    if value is None:
        return list(DSO_TYPE_GROUP_KEYS)
    if isinstance(value, str):
        parts = [p.strip() for p in value.replace(";", ",").split(",") if p.strip()]
    elif isinstance(value, (list, tuple, set)):
        parts = [str(p).strip() for p in value if str(p).strip()]
    else:
        parts = list(DSO_TYPE_GROUP_KEYS)
    groups = normalize_dso_type_groups(parts)
    if groups is None:
        return list(DSO_TYPE_GROUP_KEYS)
    # stabile Reihenfolge
    return [key for key in DSO_TYPE_GROUP_KEYS if key in groups]


def load_prefs(path: Path) -> dict[str, Any]:
    data = dict(DEFAULTS)
    if path.is_file():
        try:
            raw = json.loads(path.read_text(encoding="utf-8"))
            if isinstance(raw, dict):
                data.update(raw)
        except (OSError, json.JSONDecodeError):
            pass
    try:
        data["star_scale"] = max(0.4, min(4.0, float(data.get("star_scale", 1.0))))
        data["mag_limit"] = max(0.0, min(9.0, float(data.get("mag_limit", 5.5))))
        data["track_hours"] = _as_bool(data.get("track_hours"), False)
        data["grid"] = _as_bool(data.get("grid"), False)
        data["grid_eq"] = _as_bool(data.get("grid_eq"), False)
        data["grid_ecliptic"] = _as_bool(data.get("grid_ecliptic"), False)
        data["horizon_points"] = _as_bool(data.get("horizon_points"), True)
        data["tonight"] = _as_bool(data.get("tonight"), False)
        data["show_favorites"] = _as_bool(data.get("show_favorites"), False)
        data["show_stars"] = _as_bool(data.get("show_stars"), True)
        data["show_const"] = _as_bool(data.get("show_const"), True)
        data["show_messier"] = _as_bool(data.get("show_messier"), True)
        data["show_ngc"] = _as_bool(data.get("show_ngc"), False)
        data["show_planets"] = _as_bool(data.get("show_planets"), True)
        step = int(data.get("grid_step", 10))
        data["grid_step"] = 5 if step == 5 else 10
        data["dso_types"] = _normalize_dso_types(data.get("dso_types"))
    except (TypeError, ValueError):
        data = dict(DEFAULTS)
    return data


def _atomic_replace(tmp: Path, path: Path) -> None:
    """Windows-sicher: os.replace kann scheitern, wenn die Zieldatei gesperrt ist."""
    last_err: OSError | None = None
    for attempt in range(6):
        try:
            os.replace(tmp, path)
            return
        except PermissionError as exc:
            last_err = exc
            # kurz warten — Antivirus/Explorer hält die Datei oft kurz fest
            import time

            time.sleep(0.05 * (attempt + 1))
        except OSError as exc:
            last_err = exc
            break
    # Fallback: direkt überschreiben (kein atomarer Swap)
    try:
        path.write_text(tmp.read_text(encoding="utf-8"), encoding="utf-8")
        try:
            tmp.unlink(missing_ok=True)
        except OSError:
            pass
        return
    except OSError:
        if last_err is not None:
            raise last_err
        raise


def save_prefs(path: Path, updates: dict[str, Any]) -> dict[str, Any]:
    data = load_prefs(path)
    data.update(updates)
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + f".{os.getpid()}.tmp")
    tmp.write_text(json.dumps(data, indent=2) + "\n", encoding="utf-8")
    _atomic_replace(tmp, path)
    cleaned = load_prefs(path)
    if cleaned != data:
        tmp = path.with_suffix(path.suffix + f".{os.getpid()}.tmp")
        tmp.write_text(json.dumps(cleaned, indent=2) + "\n", encoding="utf-8")
        _atomic_replace(tmp, path)
    return cleaned
