from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml

from mele.weather_safety import WeatherSafetyConfig, load_weather_safety_config

REPO_ROOT = Path(__file__).resolve().parent.parent


def _load_yaml(path: Path) -> dict[str, Any]:
    if not path.is_file():
        return {}
    data = yaml.safe_load(path.read_text(encoding="utf-8"))
    return data if isinstance(data, dict) else {}

@dataclass
class MeleSettings:
    ui_port: int = 8082
    # 0.0.0.0 = LAN-Zugriff (iPad/Heimnetz); 127.0.0.1 = nur lokal
    ui_host: str = "0.0.0.0"
    media_dir: Path = REPO_ROOT / "media"
    gps_dir: Path = REPO_ROOT / "media" / "GPS-locations"
    horizon_dir: Path = REPO_ROOT / "data" / "horizon"
    preview_width: int = 2000
    latitude_deg: float | None = None
    longitude_deg: float | None = None
    elevation_m: float = 0.0
    timezone: str = ""
    catalog_dir: Path = REPO_ROOT / "data" / "catalogs"
    # User-Imaging-DB (getrennt von sky.sqlite — Katalog-Import loescht sky.sqlite)
    astro_manager_db: Path = REPO_ROOT / "data" / "catalogs" / "astro_manager.sqlite"
    # Aufnahme lokal (SSD); Archiv spaeter NAS — nur Pfad-Config in Phase 1
    local_capture_root: Path = Path(r"C:\Astro\Capture\Mele")
    archive_root: Path = Path(r"\\NAS\Astro\Capture\Mele")
    nina_base_url: str = "http://localhost:1888/v2/api"
    nina_exe: Path = Path(
        r"C:\Program Files\N.I.N.A. - Nighttime Imaging 'N' Astronomy\NINA.exe"
    )
    synscan_pro_exe: Path = Path(
        r"C:\Astro\SW\synscanpro_windows_2611\SynScanPro\SynScanPro.exe"
    )
    weather_journal_enabled: bool = True
    weather_journal_interval_h: float = 1.0
    local_weather_enabled: bool = False
    local_weather_provider: str = "ecowitt"
    local_weather_label: str = ""
    local_weather_server_url: str = "http://127.0.0.1:8765"
    local_weather_poll_interval_s: float = 60.0
    local_weather_journal: bool = True
    weather_safety: WeatherSafetyConfig = field(default_factory=WeatherSafetyConfig)


def _optional_bool(value: Any, default: bool = False) -> bool:
    if value is None or value == "":
        return default
    if isinstance(value, bool):
        return value
    return str(value).strip().lower() in {"1", "true", "yes", "on"}


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
    manager_raw = str(raw.get("astro_manager_db") or "").strip()
    if manager_raw:
        manager_db = Path(manager_raw)
        if not manager_db.is_absolute():
            manager_db = REPO_ROOT / manager_db
    else:
        manager_db = catalogs / "astro_manager.sqlite"
    local_cap = Path(str(raw.get("local_capture_root") or r"C:\Astro\Capture\Mele").strip() or r"C:\Astro\Capture\Mele")
    archive = Path(str(raw.get("archive_root") or r"\\NAS\Astro\Capture\Mele").strip() or r"\\NAS\Astro\Capture\Mele")
    synscan_raw = str(raw.get("synscan_pro_exe") or "").strip()
    if synscan_raw:
        synscan = Path(synscan_raw)
        if synscan.is_dir():
            synscan = synscan / "SynScanPro.exe"
    else:
        synscan = MeleSettings().synscan_pro_exe
    nina_exe_raw = str(raw.get("nina_exe") or "").strip()
    if nina_exe_raw:
        nina_exe = Path(nina_exe_raw)
        if nina_exe.is_dir():
            nina_exe = nina_exe / "NINA.exe"
    else:
        nina_exe = MeleSettings().nina_exe
    local = raw.get("local_weather") if isinstance(raw.get("local_weather"), dict) else {}
    safety_raw = raw.get("weather_safety") if isinstance(raw.get("weather_safety"), dict) else {}
    if isinstance(local.get("safety"), dict):
        merged_safety = {**safety_raw, **local["safety"]}
    else:
        merged_safety = safety_raw
    weather_safety = load_weather_safety_config(merged_safety)

    return MeleSettings(
        ui_port=int(raw.get("ui_port") or 8082),
        ui_host=str(raw.get("ui_host") or "0.0.0.0").strip() or "0.0.0.0",
        media_dir=media,
        gps_dir=gps,
        horizon_dir=horizon,
        preview_width=int(raw.get("preview_width") or 2000),
        latitude_deg=_optional_float(raw.get("latitude_deg")),
        longitude_deg=_optional_float(raw.get("longitude_deg")),
        elevation_m=float(raw.get("elevation_m") or 0.0),
        timezone=str(raw.get("timezone") or "").strip(),
        catalog_dir=catalogs,
        astro_manager_db=manager_db,
        local_capture_root=local_cap,
        archive_root=archive,
        nina_base_url=str(raw.get("nina_base_url") or "http://localhost:1888/v2/api").strip().rstrip("/"),
        nina_exe=nina_exe,
        synscan_pro_exe=synscan,
        weather_journal_enabled=_optional_bool(raw.get("weather_journal_enabled"), True),
        weather_journal_interval_h=float(raw.get("weather_journal_interval_h") or 1.0),
        local_weather_enabled=_optional_bool(local.get("enabled"), False),
        local_weather_provider=str(local.get("provider") or "ecowitt").strip() or "ecowitt",
        local_weather_label=str(local.get("label") or "").strip(),
        local_weather_server_url=str(
            local.get("server_url") or local.get("weather_server_url") or "http://127.0.0.1:8765"
        ).strip().rstrip("/"),
        local_weather_poll_interval_s=float(local.get("poll_interval_s") or 60.0),
        local_weather_journal=_optional_bool(local.get("journal"), True),
        weather_safety=weather_safety,
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
