from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import yaml

REPO_ROOT = Path(__file__).resolve().parent.parent


def _load_yaml(path: Path) -> dict[str, Any]:
    if not path.is_file():
        return {}
    data = yaml.safe_load(path.read_text(encoding="utf-8"))
    return data if isinstance(data, dict) else {}


@dataclass
class MeleSettings:
    ui_port: int = 8082
    media_dir: Path = REPO_ROOT / "media"
    gps_dir: Path = REPO_ROOT / "media" / "GPS-locations"
    horizon_dir: Path = REPO_ROOT / "data" / "horizon"
    preview_width: int = 2000
    latitude_deg: float | None = None
    longitude_deg: float | None = None
    timezone: str = ""
    catalog_dir: Path = REPO_ROOT / "data" / "catalogs"


def _optional_float(value: Any) -> float | None:
    if value is None or value == "":
        return None
    return float(value)


def load_mele_settings(path: Path | None = None) -> MeleSettings:
    cfg_path = path or REPO_ROOT / "configs" / "mele.yaml"
    raw = _load_yaml(cfg_path)
    media = Path(raw.get("media_dir") or "media")
    horizon = Path(raw.get("horizon_dir") or "data/horizon")
    catalogs = Path(raw.get("catalog_dir") or "data/catalogs")
    gps_raw = raw.get("gps_dir")
    if not media.is_absolute():
        media = REPO_ROOT / media
    if gps_raw:
        gps = Path(gps_raw)
        if not gps.is_absolute():
            gps = REPO_ROOT / gps
    else:
        gps = media / "GPS-locations"
    if not horizon.is_absolute():
        horizon = REPO_ROOT / horizon
    if not catalogs.is_absolute():
        catalogs = REPO_ROOT / catalogs
    return MeleSettings(
        ui_port=int(raw.get("ui_port") or 8082),
        media_dir=media,
        gps_dir=gps,
        horizon_dir=horizon,
        preview_width=int(raw.get("preview_width") or 2000),
        latitude_deg=_optional_float(raw.get("latitude_deg")),
        longitude_deg=_optional_float(raw.get("longitude_deg")),
        timezone=str(raw.get("timezone") or "").strip(),
        catalog_dir=catalogs,
    )


def _replace_yaml_scalar(text: str, key: str, value: str) -> str:
    pattern = re.compile(rf"^({re.escape(key)}\s*:)\s*.*$", re.MULTILINE)
    if pattern.search(text):
        return pattern.sub(rf"\1 {value}", text, count=1)
    return text.rstrip() + f"\n{key}: {value}\n"


def save_site(
    latitude_deg: float,
    longitude_deg: float,
    path: Path | None = None,
) -> Path:
    """Schreibt lat/lon nach mele.yaml, laesst Kommentare stehen."""
    cfg_path = path or REPO_ROOT / "configs" / "mele.yaml"
    text = cfg_path.read_text(encoding="utf-8") if cfg_path.is_file() else ""
    text = _replace_yaml_scalar(text, "latitude_deg", f"{latitude_deg:.6f}")
    text = _replace_yaml_scalar(text, "longitude_deg", f"{longitude_deg:.6f}")
    cfg_path.parent.mkdir(parents=True, exist_ok=True)
    cfg_path.write_text(text, encoding="utf-8")
    return cfg_path
