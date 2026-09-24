"""GPS pro 360-Foto: eine gemeinsame sites.json."""

from __future__ import annotations

import json
import os
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


@dataclass(frozen=True)
class PhotoSite:
    stem: str
    latitude_deg: float
    longitude_deg: float
    source: str = "saved"
    updated: str = ""
    filename: str = ""


def sites_path(horizon_dir: Path) -> Path:
    return horizon_dir / "sites.json"


def load_sites(path: Path) -> dict[str, PhotoSite]:
    if not path.is_file():
        return {}
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    rows = raw.get("sites", raw) if isinstance(raw, dict) else {}
    if not isinstance(rows, dict):
        return {}
    found: dict[str, PhotoSite] = {}
    for stem, item in rows.items():
        if not isinstance(item, dict):
            continue
        try:
            lat = float(item["latitude_deg"])
            lon = float(item["longitude_deg"])
        except (KeyError, TypeError, ValueError):
            continue
        found[str(stem)] = PhotoSite(
            stem=str(stem),
            latitude_deg=lat,
            longitude_deg=lon,
            source=str(item.get("source") or "saved"),
            updated=str(item.get("updated") or ""),
            filename=str(item.get("file") or ""),
        )
    return found


def load_photo_site(path: Path, stem: str) -> PhotoSite | None:
    return load_sites(path).get(stem)


def save_photo_site(
    path: Path,
    stem: str,
    latitude_deg: float,
    longitude_deg: float,
    *,
    source: str = "saved",
    filename: str = "",
) -> PhotoSite:
    sites = load_sites(path)
    record = PhotoSite(
        stem=stem,
        latitude_deg=float(latitude_deg),
        longitude_deg=float(longitude_deg),
        source=source,
        updated=datetime.now(timezone.utc).isoformat(),
        filename=filename,
    )
    sites[stem] = record
    payload: dict[str, Any] = {
        "version": 1,
        "sites": {
            key: {
                "latitude_deg": round(site.latitude_deg, 6),
                "longitude_deg": round(site.longitude_deg, 6),
                "source": site.source,
                "updated": site.updated,
                "file": site.filename,
            }
            for key, site in sorted(sites.items())
        },
    }
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(payload, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    os.replace(tmp, path)
    return record
