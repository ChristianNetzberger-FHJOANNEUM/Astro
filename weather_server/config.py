"""Konfiguration fuer weather_server (eigenstaendig, kein mele-Import)."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

import yaml

REPO_ROOT = Path(__file__).resolve().parent.parent
DEFAULT_CONFIG_PATH = REPO_ROOT / "configs" / "weather_server.yaml"


def _load_yaml(path: Path) -> dict[str, Any]:
    if not path.is_file():
        return {}
    data = yaml.safe_load(path.read_text(encoding="utf-8"))
    return data if isinstance(data, dict) else {}


@dataclass(frozen=True)
class WeatherServerSettings:
    gateway_base_url: str = "http://192.168.0.149"
    livedata_path: str = "/get_livedata_info"
    poll_interval_s: float = 30.0
    request_timeout_s: float = 10.0
    api_host: str = "0.0.0.0"
    api_port: int = 8765
    db_path: Path = REPO_ROOT / "data" / "weather_server" / "weather.sqlite"
    label: str = "GW1200"
    open_browser: bool = True


def load_settings(path: Path | None = None) -> WeatherServerSettings:
    cfg_path = path or DEFAULT_CONFIG_PATH
    raw = _load_yaml(cfg_path)

    db_raw = raw.get("db_path")
    if db_raw:
        db_path = Path(str(db_raw))
        if not db_path.is_absolute():
            db_path = REPO_ROOT / db_path
    else:
        db_path = REPO_ROOT / "data" / "weather_server" / "weather.sqlite"

    return WeatherServerSettings(
        gateway_base_url=str(raw.get("gateway_base_url") or "http://192.168.0.149").rstrip("/"),
        livedata_path=str(raw.get("livedata_path") or "/get_livedata_info"),
        poll_interval_s=float(raw.get("poll_interval_s") or 30.0),
        request_timeout_s=float(raw.get("request_timeout_s") or 10.0),
        api_host=str(raw.get("api_host") or "0.0.0.0"),
        api_port=int(raw.get("api_port") or 8765),
        db_path=db_path,
        label=str(raw.get("label") or "GW1200").strip() or "GW1200",
        open_browser=bool(raw["open_browser"]) if "open_browser" in raw else True,
    )
