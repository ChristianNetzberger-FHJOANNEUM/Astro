"""Phase 2b: strukturiertes GoTo-Diagnoselog (kein Verhalten von Phase 2 aendern).

Schreibt pro Versuch eine JSON-Datei und eine Zeile in nina-goto.jsonl unter
data/horizon/nina-goto/. RA an die API bleibt in Grad (Angle.ByDegree).
"""

from __future__ import annotations

import json
import math
import os
import re
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


def goto_log_dir(horizon_dir: Path) -> Path:
    return horizon_dir / "nina-goto"


def new_request_id() -> str:
    return uuid.uuid4().hex[:12]


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


def angular_distance_deg(
    ra1_deg: float,
    dec1_deg: float,
    ra2_deg: float,
    dec2_deg: float,
) -> float:
    """Exakte sphaerische Winkeldistanz in Grad (beide RA in Grad)."""
    a1 = math.radians(ra1_deg)
    d1 = math.radians(dec1_deg)
    a2 = math.radians(ra2_deg)
    d2 = math.radians(dec2_deg)
    cos_c = math.sin(d1) * math.sin(d2) + math.cos(d1) * math.cos(d2) * math.cos(a1 - a2)
    cos_c = max(-1.0, min(1.0, cos_c))
    return math.degrees(math.acos(cos_c))


def approximate_separation_deg(
    ra_target_deg: float,
    dec_target_deg: float,
    ra_mount_hours: float,
    dec_mount_deg: float,
) -> dict[str, float]:
    """Diagnose-Kennwerte Soll/Ist (Ziel RA Grad, Mount RA Stunden)."""
    ra_mount_deg = ra_mount_hours * 15.0
    d_ra_h = (ra_mount_deg - ra_target_deg) / 15.0
    while d_ra_h > 12.0:
        d_ra_h -= 24.0
    while d_ra_h < -12.0:
        d_ra_h += 24.0
    d_dec = dec_mount_deg - dec_target_deg
    d_ra_cos = 15.0 * d_ra_h * math.cos(math.radians(dec_target_deg))
    approx = math.hypot(d_ra_cos, d_dec)
    exact = angular_distance_deg(ra_target_deg, dec_target_deg, ra_mount_deg, dec_mount_deg)
    return {
        "delta_ra_hours": d_ra_h,
        "delta_ra_cos_dec_deg": d_ra_cos,
        "delta_dec_deg": d_dec,
        "approx_sep_deg": approx,
        "sep_deg": exact,
        "ra_mount_deg": ra_mount_deg,
    }


def mount_snapshot(mount: dict[str, Any] | None) -> dict[str, Any] | None:
    if not isinstance(mount, dict):
        return None
    return {
        "connected": bool(mount.get("connected")),
        "ra_hours": _finite(mount.get("right_ascension_hours")),
        "ra_string": str(mount.get("right_ascension_string") or ""),
        "dec_deg": _finite(mount.get("declination_deg")),
        "dec_string": str(mount.get("declination_string") or ""),
        "az_deg": _finite(mount.get("azimuth_deg")),
        "alt_deg": _finite(mount.get("altitude_deg")),
        "pier": str(mount.get("side_of_pier") or ""),
        "tracking_enabled": bool(mount.get("tracking_enabled")),
        "tracking_mode": str(mount.get("tracking_mode") or ""),
        "slewing": bool(mount.get("slewing")),
        "equatorial_system": str(mount.get("equatorial_system") or ""),
        "at_park": bool(mount.get("at_park")),
    }


def _safe_stem(name: str) -> str:
    text = re.sub(r"[^\w.\-+]+", "_", (name or "object").strip(), flags=re.UNICODE)
    return (text[:48] or "object").strip("_")


def enrich_record(record: dict[str, Any]) -> dict[str, Any]:
    """Ergaenzt Kennzahlen; aendert die GoTo-Semantik nicht."""
    data = dict(record)
    data.setdefault("request_id", new_request_id())
    data.setdefault("logged_at", datetime.now(timezone.utc).isoformat())
    obj = data.get("object") if isinstance(data.get("object"), dict) else {}
    post = data.get("post_slew") if isinstance(data.get("post_slew"), dict) else None
    ra_t = _finite(obj.get("ra_deg"))
    dec_t = _finite(obj.get("dec_deg"))
    metrics: dict[str, Any] = {}
    if post and ra_t is not None and dec_t is not None:
        ra_m = _finite(post.get("ra_hours"))
        dec_m = _finite(post.get("dec_deg"))
        if ra_m is not None and dec_m is not None:
            metrics = approximate_separation_deg(ra_t, dec_t, ra_m, dec_m)
    trail = data.get("trail") if isinstance(data.get("trail"), list) else []
    pier_values = []
    for sample in trail:
        if isinstance(sample, dict) and sample.get("pier"):
            pier_values.append(str(sample["pier"]))
    pier_changes: list[str] = []
    for value in pier_values:
        if not pier_changes or pier_changes[-1] != value:
            pier_changes.append(value)
    slew = data.get("slew") if isinstance(data.get("slew"), dict) else {}
    metrics.update(
        {
            "trail_samples": len(trail),
            "pier_sequence": pier_changes,
            "duration_s": _finite(slew.get("duration_s")),
        }
    )
    data["metrics"] = metrics
    return data


def format_goto_report(record: dict[str, Any]) -> str:
    obj = record.get("object") or {}
    req = record.get("request") or {}
    pre = record.get("pre_slew") or {}
    api = record.get("api_response") or {}
    slew = record.get("slew") or {}
    post = record.get("post_slew") or {}
    metrics = record.get("metrics") or {}
    err = record.get("error") or "none"
    lines = [
        str(record.get("logged_at") or ""),
        f"request_id: {record.get('request_id')}",
        f"outcome: {record.get('outcome') or '?'}",
        "",
        "OBJECT",
        f"  name: {obj.get('name')}",
        f"  type: {obj.get('type')}",
        f"  source: {obj.get('source')}",
        f"  kind: {obj.get('kind')}",
        f"  id: {obj.get('id')}",
        f"  selected.ra_deg: {obj.get('ra_deg')}",
        f"  selected.dec_deg: {obj.get('dec_deg')}",
        f"  selected.az_deg: {obj.get('az_deg')}",
        f"  selected.alt_deg: {obj.get('alt_deg')}",
        f"  viewer_when: {obj.get('viewer_when')}",
        "",
        "REQUEST TO NINA",
        f"  endpoint: {req.get('endpoint')}",
        f"  method: {req.get('method')}",
        f"  ra_deg: {req.get('ra_deg')}   # API-Einheit Grad (nicht Stunden)",
        f"  dec_deg: {req.get('dec_deg')}",
        f"  waitForResult: {req.get('waitForResult')}",
        f"  center: {req.get('center')}",
        f"  rotate: {req.get('rotate')}",
        f"  epoch: {req.get('epoch')}",
        f"  request_id: {record.get('request_id')}",
        "",
        "PRE-SLEW MOUNT",
        f"  RA: {pre.get('ra_string')} ({pre.get('ra_hours')} h)",
        f"  Dec: {pre.get('dec_string')} ({pre.get('dec_deg')} deg)",
        f"  Az: {pre.get('az_deg')}",
        f"  Alt: {pre.get('alt_deg')}",
        f"  PierSide: {pre.get('pier')}",
        f"  Tracking: {pre.get('tracking_mode')} enabled={pre.get('tracking_enabled')}",
        f"  Slewing: {pre.get('slewing')}",
        "",
        "API RESPONSE",
        f"  HTTP: {api.get('status_code')}",
        f"  Success: {api.get('ok')}",
        f"  Message: {api.get('message')}",
        f"  Error: {api.get('error') or 'none'}",
        "",
        "SLEW",
        f"  start: {slew.get('start')}",
        f"  first Slewing=true: {slew.get('first_slewing_true')}",
        f"  end: {slew.get('end')}",
        f"  duration_s: {slew.get('duration_s')}",
        f"  samples: {metrics.get('trail_samples')}",
        f"  pier side changes: {' -> '.join(metrics.get('pier_sequence') or []) or 'n/a'}",
        "",
        "POST-SLEW MOUNT",
        f"  RA: {post.get('ra_string')} ({post.get('ra_hours')} h)",
        f"  Dec: {post.get('dec_string')} ({post.get('dec_deg')} deg)",
        f"  Az: {post.get('az_deg')}",
        f"  Alt: {post.get('alt_deg')}",
        f"  PierSide: {post.get('pier')}",
        f"  Slewing: {post.get('slewing')}",
        "",
        "METRICS",
        f"  sep_deg (spherical): {metrics.get('sep_deg')}",
        f"  approx_sep_deg: {metrics.get('approx_sep_deg')}",
        f"  delta_ra_cos_dec_deg: {metrics.get('delta_ra_cos_dec_deg')}",
        f"  delta_dec_deg: {metrics.get('delta_dec_deg')}",
        "",
        "ERROR",
        f"  {err}",
        "",
        f"TRAIL POINTS: {len(record.get('trail') or [])}",
    ]
    for index, point in enumerate(record.get("trail") or []):
        if not isinstance(point, dict):
            continue
        lines.append(
            f"  {index + 1:02d}  {point.get('kind')}  "
            f"az={point.get('az')} alt={point.get('alt')}  "
            f"ra_h={point.get('ra_hours')} dec={point.get('dec_deg')}  "
            f"pier={point.get('pier')}  t={point.get('t')}"
        )
    return "\n".join(lines) + "\n"


def save_goto_record(horizon_dir: Path, record: dict[str, Any]) -> dict[str, Any]:
    """Persistiert JSON + Text + JSONL-Zeile. Gibt Pfade im Record zurueck."""
    data = enrich_record(record)
    directory = goto_log_dir(horizon_dir)
    directory.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    name = _safe_stem(str((data.get("object") or {}).get("name") or "object"))
    outcome = _safe_stem(str(data.get("outcome") or "run"))
    stem = f"{stamp}_{outcome}_{name}_{data['request_id']}"
    json_path = directory / f"{stem}.json"
    text_path = directory / f"{stem}.txt"
    jsonl_path = directory / "nina-goto.jsonl"
    payload = json.dumps(data, indent=2, ensure_ascii=False) + "\n"
    text = format_goto_report(data)
    tmp = json_path.with_suffix(json_path.suffix + ".tmp")
    tmp.write_text(payload, encoding="utf-8")
    os.replace(tmp, json_path)
    text_path.write_text(text, encoding="utf-8")
    with jsonl_path.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(data, ensure_ascii=False) + "\n")
    data["paths"] = {
        "json": str(json_path),
        "txt": str(text_path),
        "jsonl": str(jsonl_path),
    }
    return data
