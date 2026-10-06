"""Session-Capture-Timing: JSON-Log unter ``{session}/capture-timing.json``."""

from __future__ import annotations

import json
import math
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


TIMING_FILENAME = "capture-timing.json"


def timing_path_for(session_dir: str | Path) -> Path:
    return Path(session_dir) / TIMING_FILENAME


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _finite(value: Any) -> float | None:
    if value is None:
        return None
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    if math.isnan(number) or math.isinf(number):
        return None
    return number


def _load(path: Path) -> dict[str, Any]:
    if not path.is_file():
        return {"version": 1, "frames": [], "summary": {}}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError):
        return {"version": 1, "frames": [], "summary": {}, "error": "corrupt"}
    if not isinstance(data, dict):
        return {"version": 1, "frames": [], "summary": {}}
    frames = data.get("frames")
    if not isinstance(frames, list):
        data["frames"] = []
    return data


def _summarize(frames: list[dict[str, Any]]) -> dict[str, Any]:
    expose: list[float] = []
    post: list[float] = []
    total: list[float] = []
    by_type: dict[str, int] = {}
    for row in frames:
        if not isinstance(row, dict):
            continue
        kind = str(row.get("image_type") or "LIGHT").upper()
        by_type[kind] = by_type.get(kind, 0) + 1
        e = _finite(row.get("expose_s"))
        p = _finite(row.get("post_s"))
        t = _finite(row.get("total_s"))
        if e is not None:
            expose.append(e)
        if p is not None:
            post.append(p)
        if t is not None:
            total.append(t)

    def _avg(vals: list[float]) -> float | None:
        return sum(vals) / len(vals) if vals else None

    def _p90(vals: list[float]) -> float | None:
        if not vals:
            return None
        ordered = sorted(vals)
        idx = min(len(ordered) - 1, max(0, int(round(0.9 * (len(ordered) - 1)))))
        return ordered[idx]

    avg_post = _avg(post)
    return {
        "frames": len(frames),
        "by_type": by_type,
        "avg_expose_s": _avg(expose),
        "avg_post_s": avg_post,
        "avg_total_s": _avg(total),
        "p90_post_s": _p90(post),
        # Empfohlener Mindest-Abstand zwischen Capture-Starts (s)
        "suggested_cadence_s": avg_post,
    }


def append_capture_timing(
    session_dir: str | Path,
    *,
    session_id: int | None = None,
    image_type: str = "LIGHT",
    exposure_planned_s: float | None = None,
    expose_s: float | None = None,
    post_s: float | None = None,
    total_s: float | None = None,
    file_name: str | None = None,
    file_path: str | None = None,
    nina_last_download_s: float | None = None,
    camera_state: str | None = None,
    ok: bool = True,
    note: str = "",
    extra: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Einen Frame-Timing-Eintrag anhängen und Summary neu berechnen."""
    root = Path(session_dir)
    root.mkdir(parents=True, exist_ok=True)
    path = timing_path_for(root)
    data = _load(path)
    if session_id is not None:
        data["session_id"] = int(session_id)
    data["version"] = 1
    data["session_dir"] = str(root)
    data["updated_utc"] = _utc_now()

    exp = _finite(expose_s)
    post = _finite(post_s)
    total = _finite(total_s)
    if total is None and exp is not None and post is not None:
        total = exp + post

    entry: dict[str, Any] = {
        "utc": _utc_now(),
        "ok": bool(ok),
        "image_type": str(image_type or "LIGHT").upper(),
        "exposure_planned_s": _finite(exposure_planned_s),
        "expose_s": exp,
        "post_s": post,
        "total_s": total,
        "file_name": file_name or None,
        "file_path": file_path or None,
        "nina_last_download_s": _finite(nina_last_download_s),
        "camera_state": camera_state or None,
        "note": note or "",
    }
    if extra:
        for key, value in extra.items():
            if key not in entry:
                entry[key] = value

    frames = list(data.get("frames") or [])
    frames.append(entry)
    data["frames"] = frames
    data["summary"] = _summarize(frames)

    tmp = path.with_suffix(".json.tmp")
    tmp.write_text(json.dumps(data, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    tmp.replace(path)
    return data


def read_capture_timing(session_dir: str | Path) -> dict[str, Any] | None:
    """Timing-Log lesen; ``None`` wenn keine Datei."""
    path = timing_path_for(session_dir)
    if not path.is_file():
        return None
    data = _load(path)
    frames = [f for f in (data.get("frames") or []) if isinstance(f, dict)]
    data["frames"] = frames
    data["summary"] = _summarize(frames)
    data["path"] = str(path)
    return data
