"""MeLE-Consumer fuer den standalone weather_server (Pull /api/current)."""

from __future__ import annotations

import json
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen


SOURCE_WEATHER_SERVER = "weather_server.local"


class WeatherServerError(RuntimeError):
    """weather_server nicht erreichbar oder Antwort ungueltig."""


def fetch_current(base_url: str, *, timeout_s: float = 5.0) -> dict[str, Any]:
    """GET {base}/api/current → Sample-Dict (inkl. id)."""
    root = (base_url or "").strip().rstrip("/")
    if not root:
        raise WeatherServerError("weather_server URL fehlt")
    url = f"{root}/api/current"
    data = _get_json(url, timeout_s=timeout_s)
    sample = data.get("sample")
    if not isinstance(sample, dict):
        raise WeatherServerError("api/current: sample missing")
    return sample


def fetch_history(
    base_url: str,
    *,
    limit: int = 120,
    timeout_s: float = 8.0,
) -> list[dict[str, Any]]:
    """GET {base}/api/history → Sample-Liste (neueste zuerst)."""
    root = (base_url or "").strip().rstrip("/")
    if not root:
        raise WeatherServerError("weather_server URL fehlt")
    lim = max(1, min(int(limit), 5000))
    url = f"{root}/api/history?limit={lim}"
    data = _get_json(url, timeout_s=timeout_s)
    samples = data.get("samples")
    if not isinstance(samples, list):
        raise WeatherServerError("api/history: samples missing")
    return [item for item in samples if isinstance(item, dict)]


def _get_json(url: str, *, timeout_s: float) -> dict[str, Any]:
    request = Request(url, headers={"User-Agent": "MeLE-weather-consumer/0.1"})
    try:
        with urlopen(request, timeout=timeout_s) as response:
            body = response.read()
    except HTTPError as exc:
        raise WeatherServerError(f"HTTP {exc.code} von {url}") from exc
    except URLError as exc:
        raise WeatherServerError(f"unreachable: {url} ({exc.reason})") from exc
    except TimeoutError as exc:
        # Windows/Python: urlopen-Timeout kommt oft als bare TimeoutError, nicht URLError
        raise WeatherServerError(f"timeout: {url}") from exc
    except OSError as exc:
        raise WeatherServerError(f"unreachable: {url} ({exc})") from exc

    try:
        data = json.loads(body.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise WeatherServerError(f"invalid JSON from {url}") from exc
    if not isinstance(data, dict) or not data.get("ok"):
        err = data.get("error") if isinstance(data, dict) else "bad response"
        raise WeatherServerError(str(err))
    return data


def sample_to_observation(sample: dict[str, Any]) -> dict[str, Any]:
    """weather_server-Sample → Journal-/Anzeige-Observation (SI)."""
    return {
        "when": sample.get("when") or sample.get("recorded_at") or sample.get("station_when"),
        "temp_c": sample.get("temp_c"),
        "humidity_pct": sample.get("humidity_pct"),
        "pressure_hpa": sample.get("pressure_hpa"),
        "wind_ms": sample.get("wind_ms"),
        "wind_dir_deg": sample.get("wind_dir_deg"),
        "gust_ms": sample.get("gust_ms"),
        "rain_mm": sample.get("rain_mm"),
        "rain_rate_mm_h": sample.get("rain_rate_mm_h"),
        "uvi": sample.get("uvi"),
        "lux": sample.get("lux"),
        "solarradiation_wm2": sample.get("solarradiation_wm2"),
        "dewpoint_c": sample.get("dewpoint_c"),
        "dewpoint_margin_c": sample.get("dewpoint_margin_c"),
        "indoor_temp_c": sample.get("indoor_temp_c"),
        "indoor_humidity_pct": sample.get("indoor_humidity_pct"),
        "provider": SOURCE_WEATHER_SERVER,
        "raw": {
            "weather_server_sample_id": sample.get("id"),
            "recorded_at": sample.get("recorded_at"),
            "label": sample.get("label"),
        },
    }


def format_station_summary(observation: dict[str, Any] | None, *, label: str = "") -> str:
    """Kurze UI-Zeile, z.B. 'Garten 22.8°C Δ11.9K'."""
    if not observation:
        return ""
    parts: list[str] = []
    name = (label or "").strip()
    if name:
        parts.append(name)
    temp = observation.get("temp_c")
    if temp is not None:
        try:
            parts.append(f"{float(temp):.1f}°C")
        except (TypeError, ValueError):
            pass
    margin = observation.get("dewpoint_margin_c")
    if margin is not None:
        try:
            parts.append(f"Δ{float(margin):.1f}K")
        except (TypeError, ValueError):
            pass
    hum = observation.get("humidity_pct")
    if hum is not None and temp is None:
        try:
            parts.append(f"{float(hum):.0f}%")
        except (TypeError, ValueError):
            pass
    return " ".join(parts) if parts else "Station ok"


def sample_id(sample_or_obs: dict[str, Any] | None) -> int | None:
    if not sample_or_obs:
        return None
    raw = sample_or_obs.get("raw")
    if isinstance(raw, dict) and raw.get("weather_server_sample_id") is not None:
        try:
            return int(raw["weather_server_sample_id"])
        except (TypeError, ValueError):
            pass
    if sample_or_obs.get("id") is not None:
        try:
            return int(sample_or_obs["id"])
        except (TypeError, ValueError):
            return None
    return None
