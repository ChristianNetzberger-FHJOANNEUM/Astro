"""GeoSphere Austria NWP-Vorhersage fuer den Beobachtungsstandort."""

from __future__ import annotations

import json
import math
import os
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Callable
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode
from urllib.request import Request, urlopen


NWP_RESOURCE = "nwp-v2-1h-1km"
NWP_URL = f"https://dataset.api.hub.geosphere.at/v1/timeseries/forecast/{NWP_RESOURCE}"
NWP_PARAMS = ("tcc", "2t", "2r", "10u", "10v", "10fg", "tp", "sy", "sund")
ATTRIBUTION = "Daten: GeoSphere Austria, CC-BY 4.0"
STALE_AFTER = timedelta(hours=3)
FETCH_TIMEOUT_S = 20
SUMMARY_HOURS = 12
# Unter dieser Geschwindigkeit keine Windrichtung (ruhig).
_WIND_CALM_MS = 0.05


class WeatherError(RuntimeError):
    """Abruf oder Parser fehlgeschlagen, kein nutzbarer Cache."""


def weather_dir_for(horizon_dir: Path) -> Path:
    return horizon_dir.parent / "weather"


def cache_path(weather_dir: Path, latitude_deg: float, longitude_deg: float) -> Path:
    return weather_dir / f"{latitude_deg:.4f}_{longitude_deg:.4f}.nwp.json"


def _parse_stamp(text: str) -> datetime:
    return datetime.fromisoformat(text.replace("Z", "+00:00")).astimezone(timezone.utc)


def _series(params: dict[str, Any], name: str) -> list[Any]:
    block = params.get(name) or {}
    data = block.get("data")
    return list(data) if isinstance(data, list) else []


def _num(value: Any) -> float | None:
    if value is None:
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def wind_speed_ms(east_ms: float | None, north_ms: float | None) -> float | None:
    if east_ms is None or north_ms is None:
        return None
    return (east_ms * east_ms + north_ms * north_ms) ** 0.5


def wind_dir_deg(east_ms: float | None, north_ms: float | None) -> float | None:
    """Meteorologische Windrichtung in Grad (woher der Wind kommt, 0=N, 90=E)."""
    if east_ms is None or north_ms is None:
        return None
    speed = wind_speed_ms(east_ms, north_ms)
    if speed is None or speed < _WIND_CALM_MS:
        return None
    # atan2(v, u) = Richtung der Stroemung; meteorologisch = Gegenrichtung vom Norden.
    degrees = (270.0 - math.degrees(math.atan2(north_ms, east_ms))) % 360.0
    return round(degrees, 1)


# 16-Punkt-Kompass (Sektoren je 22.5°, Mitte auf der Himmelsrichtung).
_COMPASS16 = (
    "N",
    "NNE",
    "NE",
    "ENE",
    "E",
    "ESE",
    "SE",
    "SSE",
    "S",
    "SSW",
    "SW",
    "WSW",
    "W",
    "WNW",
    "NW",
    "NNW",
)


def wind_compass16(degrees: float | None) -> str | None:
    """Himmelsrichtung aus meteorologischer Windrichtung (16 Sektoren)."""
    if degrees is None:
        return None
    try:
        deg = float(degrees) % 360.0
    except (TypeError, ValueError):
        return None
    return _COMPASS16[int((deg + 11.25) // 22.5) % 16]


def dewpoint_c(temp_c: float | None, humidity_pct: float | None) -> float | None:
    """Taupunkt (°C) aus Temperatur und relativer Feuchte (Magnus, Wasser)."""
    if temp_c is None or humidity_pct is None:
        return None
    try:
        t = float(temp_c)
        rh = float(humidity_pct)
    except (TypeError, ValueError):
        return None
    if rh <= 0.0:
        return None
    rh = min(100.0, rh)
    # Magnus-Tetens ueber Wasser
    a = 17.62
    b = 243.12
    gamma = (a * t) / (b + t) + math.log(rh / 100.0)
    if abs(a - gamma) < 1e-9:
        return None
    return round((b * gamma) / (a - gamma), 1)


def annotate_hours(
    hours: list[dict[str, Any]],
    *,
    latitude_deg: float,
    longitude_deg: float,
) -> list[dict[str, Any]]:
    """Ergaenzt Taupunkt, Tageslicht, Beobachtungsfenster und Mondlage pro Stunde."""
    if not hours:
        return hours
    stamps: list[datetime] = []
    for item in hours:
        try:
            stamps.append(_parse_stamp(str(item["when"])))
        except (KeyError, ValueError, TypeError):
            stamps.append(datetime.now(timezone.utc))
    try:
        from mele.catalog import daylight_phases_for_stamps

        lights = daylight_phases_for_stamps(stamps, latitude_deg, longitude_deg)
    except Exception:  # noqa: BLE001
        lights = [None] * len(hours)

    moon_up: list[bool | None] = [None] * len(hours)
    moon_phase: list[float | None] = [None] * len(hours)
    try:
        from mele.ephemeris import (
            angular_sep_deg,
            illumination_from_sep,
            moon_radec,
            sun_radec,
        )
        from mele.sky import radec_to_az_alt

        for index, stamp in enumerate(stamps):
            m_ra, m_dec = moon_radec(stamp)
            _, alt = radec_to_az_alt(m_ra, m_dec, latitude_deg, longitude_deg, stamp)
            moon_up[index] = float(alt) > 0.0
            s_ra, s_dec = sun_radec(stamp)
            moon_phase[index] = round(
                illumination_from_sep(angular_sep_deg(s_ra, s_dec, m_ra, m_dec)),
                3,
            )
    except Exception:  # noqa: BLE001
        pass

    for item, light, up, phase in zip(hours, lights, moon_up, moon_phase, strict=True):
        item["dewpoint_c"] = dewpoint_c(item.get("temp_c"), item.get("humidity_pct"))
        if light is not None:
            item["light"] = light
            # Beobachtungsfenster = astronomische Nacht nach ±1 h Daemmerung
            item["observe"] = light == "night"
        if up is not None:
            item["moon_up"] = bool(up)
        if phase is not None:
            item["moon_phase"] = phase
    return hours


def moon_phase_label(phase: float | None) -> str:
    """Beleuchtung 0–1 → kurze deutsche Bezeichnung + Prozent (ohne Zu-/Abnahme)."""
    if phase is None:
        return "Mond —"
    pct = int(round(float(phase) * 100))
    if phase < 0.03:
        name = "Neumond"
    elif phase < 0.25:
        name = "Sichel"
    elif phase < 0.45:
        name = "Halbmond"
    elif phase < 0.55:
        name = "Vollmond"
    elif phase < 0.75:
        name = "Dreiviertel"
    elif phase < 0.97:
        name = "Sichel"
    else:
        name = "Vollmond"
    return f"{name} · {pct} %"


def sky_summary(hours: list[dict[str, Any]]) -> dict[str, Any]:
    """Kompakte Sky-Infos fuer Timeline-Header."""
    observe_n = sum(1 for item in hours if item.get("observe"))
    moon_n = sum(1 for item in hours if item.get("moon_up"))
    phases = [float(item["moon_phase"]) for item in hours if item.get("moon_phase") is not None]
    mid = phases[len(phases) // 2] if phases else None
    return {
        "observe_hours": observe_n,
        "moon_up_hours": moon_n,
        "moon_phase": mid,
        "moon_label": moon_phase_label(mid),
        "observe_note": "Sonnenuntergang+1 h bis Sonnenaufgang-1 h (ohne Daemmerung)",
    }


def parse_nwp(payload: dict[str, Any], *, query_lat: float, query_lon: float) -> dict[str, Any]:
    stamps = payload.get("timestamps") or []
    features = payload.get("features") or []
    if not stamps or not features:
        raise WeatherError("GeoSphere-Antwort ohne Zeitreihe")
    feature = features[0]
    params = (feature.get("properties") or {}).get("parameters") or {}
    coords = (feature.get("geometry") or {}).get("coordinates") or [None, None]
    clouds = _series(params, "tcc")
    temps = _series(params, "2t")
    hums = _series(params, "2r")
    east = _series(params, "10u")
    north = _series(params, "10v")
    gusts = _series(params, "10fg")
    rain = _series(params, "tp")
    symbols = _series(params, "sy")
    suns = _series(params, "sund")
    hours = []
    for index, stamp in enumerate(stamps):
        u = _num(east[index] if index < len(east) else None)
        v = _num(north[index] if index < len(north) else None)
        direction = wind_dir_deg(u, v)
        temp = _num(temps[index] if index < len(temps) else None)
        humidity = _num(hums[index] if index < len(hums) else None)
        hours.append(
            {
                "when": _parse_stamp(str(stamp)).isoformat(),
                "cloud_pct": _num(clouds[index] if index < len(clouds) else None),
                "temp_c": temp,
                "humidity_pct": humidity,
                "dewpoint_c": dewpoint_c(temp, humidity),
                "wind_ms": wind_speed_ms(u, v),
                "wind_dir_deg": direction,
                "wind_compass": wind_compass16(direction),
                "gust_ms": _num(gusts[index] if index < len(gusts) else None),
                "precip_mm": _num(rain[index] if index < len(rain) else None),
                "symbol": int(symbols[index]) if index < len(symbols) and symbols[index] is not None else None,
                "sunshine_s": _num(suns[index] if index < len(suns) else None),
            }
        )
    hours = annotate_hours(hours, latitude_deg=query_lat, longitude_deg=query_lon)
    ref = payload.get("reference_time")
    return {
        "source": NWP_RESOURCE,
        "attribution": ATTRIBUTION,
        "reference_time": str(ref) if ref else None,
        "query_lat": query_lat,
        "query_lon": query_lon,
        "grid_lon": _num(coords[0]),
        "grid_lat": _num(coords[1]),
        "hours": hours,
    }


def summarize(hours: list[dict[str, Any]], *, now: datetime | None = None, window_h: int = SUMMARY_HOURS) -> dict[str, Any]:
    stamp = (now or datetime.now(timezone.utc)).astimezone(timezone.utc)
    start = stamp - timedelta(minutes=30)
    upcoming = []
    for item in hours:
        when = _parse_stamp(item["when"])
        if when >= start:
            upcoming.append(item)
        if len(upcoming) >= window_h:
            break
    clouds = [item["cloud_pct"] for item in upcoming if item.get("cloud_pct") is not None]
    winds = [item["wind_ms"] for item in upcoming if item.get("wind_ms") is not None]
    rains = [item["precip_mm"] or 0.0 for item in upcoming]
    if not upcoming or not clouds:
        text = "keine Bewoelkungsdaten"
    else:
        lo, hi = min(clouds), max(clouds)
        wind_max = max(winds) if winds else 0.0
        if wind_max < 2.0:
            wind_txt = "wenig Wind"
        elif wind_max < 5.0:
            wind_txt = "maessiger Wind"
        else:
            wind_txt = "windig"
        rain_txt = " | Regen" if any(value >= 0.2 for value in rains) else ""
        text = f"naechste {len(upcoming)} h: Bewoelkung {lo:.0f}-{hi:.0f} %, {wind_txt}{rain_txt}"
    return {
        "text": text,
        "hours": len(upcoming),
        "cloud_min": min(clouds) if clouds else None,
        "cloud_max": max(clouds) if clouds else None,
        "wind_ms_max": max(winds) if winds else None,
    }


def _read_cache(path: Path) -> dict[str, Any] | None:
    if not path.is_file():
        return None
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    return raw if isinstance(raw, dict) and isinstance(raw.get("hours"), list) else None


def _write_cache(path: Path, data: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(data, indent=2) + "\n", encoding="utf-8")
    os.replace(tmp, path)


def _is_stale(data: dict[str, Any], *, now: datetime | None = None) -> bool:
    fetched = data.get("fetched_at")
    if not fetched:
        return True
    try:
        age = (now or datetime.now(timezone.utc)) - _parse_stamp(str(fetched))
    except ValueError:
        return True
    return age > STALE_AFTER


def fetch_nwp(
    latitude_deg: float,
    longitude_deg: float,
    *,
    opener: Callable[..., Any] | None = None,
) -> dict[str, Any]:
    query = urlencode(
        {
            "lat_lon": f"{latitude_deg:.5f},{longitude_deg:.5f}",
            "parameters": ",".join(NWP_PARAMS),
            "output_format": "geojson",
        }
    )
    request = Request(f"{NWP_URL}?{query}", headers={"User-Agent": "MeLE-Astro/1.0"})
    open_fn = opener or urlopen
    try:
        with open_fn(request, timeout=FETCH_TIMEOUT_S) as response:
            payload = json.loads(response.read().decode("utf-8"))
    except HTTPError as exc:
        raise WeatherError(f"GeoSphere HTTP {exc.code}") from exc
    except (URLError, TimeoutError, json.JSONDecodeError, OSError) as exc:
        raise WeatherError(f"GeoSphere nicht erreichbar: {exc}") from exc
    if not isinstance(payload, dict):
        raise WeatherError("GeoSphere-Antwort ungueltig")
    return payload


def load_forecast(
    latitude_deg: float,
    longitude_deg: float,
    weather_dir: Path,
    *,
    refresh: bool = False,
    network: bool = True,
    now: datetime | None = None,
    fetch_fn: Callable[[float, float], dict[str, Any]] | None = None,
) -> dict[str, Any]:
    """Cache zuerst; Netz nur bei refresh, fehlendem oder veraltetem Stand."""
    path = cache_path(weather_dir, latitude_deg, longitude_deg)
    cached = _read_cache(path)
    stamp = now or datetime.now(timezone.utc)
    need_net = network and (refresh or cached is None or _is_stale(cached, now=stamp))
    if need_net:
        try:
            raw = (fetch_fn or fetch_nwp)(latitude_deg, longitude_deg)
            parsed = parse_nwp(raw, query_lat=latitude_deg, query_lon=longitude_deg)
            parsed["fetched_at"] = stamp.astimezone(timezone.utc).isoformat()
            parsed["offline"] = False
            _write_cache(path, parsed)
            cached = parsed
        except WeatherError:
            if cached is None:
                raise
            cached = dict(cached)
            cached["offline"] = True
    elif cached is None:
        raise WeatherError("Noch kein Wettercache. Einmal mit Internet aktualisieren.")
    else:
        cached = dict(cached)
        cached["offline"] = False
    cached["stale"] = _is_stale(cached, now=stamp)
    hours = list(cached.get("hours") or [])
    annotate_hours(hours, latitude_deg=latitude_deg, longitude_deg=longitude_deg)
    cached["hours"] = hours
    cached["summary"] = summarize(hours, now=stamp)
    cached["sky"] = sky_summary(hours)
    cached["attribution"] = ATTRIBUTION
    return cached
