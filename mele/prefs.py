"""Anzeige-Einstellungen fuer die 360-Ansicht, sessionuebergreifend."""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any


DEFAULTS = {
    "star_scale": 1.0,
    "mag_limit": 5.5,
    "track_hours": False,
    "grid": False,
    "grid_step": 10,
    "grid_eq": False,
    "grid_ecliptic": False,
    "horizon_points": True,
}


def prefs_path(horizon_dir: Path) -> Path:
    return horizon_dir / "ui-prefs.json"


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
        flag = data.get("track_hours", False)
        data["track_hours"] = flag in (True, 1, "1", "true", "True")
        data["grid"] = data.get("grid", False) in (True, 1, "1", "true", "True")
        data["grid_eq"] = data.get("grid_eq", False) in (True, 1, "1", "true", "True")
        data["grid_ecliptic"] = data.get("grid_ecliptic", False) in (True, 1, "1", "true", "True")
        data["horizon_points"] = data.get("horizon_points", True) in (True, 1, "1", "true", "True")
        step = int(data.get("grid_step", 10))
        data["grid_step"] = 5 if step == 5 else 10
    except (TypeError, ValueError):
        data = dict(DEFAULTS)
    return data


def save_prefs(path: Path, updates: dict[str, Any]) -> dict[str, Any]:
    data = load_prefs(path)
    data.update(updates)
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(data, indent=2) + "\n", encoding="utf-8")
    os.replace(tmp, path)
    cleaned = load_prefs(path)
    if cleaned != data:
        tmp.write_text(json.dumps(cleaned, indent=2) + "\n", encoding="utf-8")
        os.replace(tmp, path)
    return cleaned
