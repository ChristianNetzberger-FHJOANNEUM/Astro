"""Lokale Wetterstation — Mapping fuer spaeteren Ecowitt-Custom-Server.

Ecowitt GW1200/WS90 kann per „Customized Server“ GET/POST an eine lokale URL
senden. Felder sind typischerweise imperial (tempf, windspeedmph, …).

Noch kein Dauer-Listener noetig: wenn app_mele laeuft, nimmt
POST/GET /weather/observation die Daten entgegen und schreibt ins Journal.
Ein spaeterer Standalone-Collector kann dieselbe parse_*-Funktion nutzen.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Mapping

from mele.weather_journal import SOURCE_ECOWITT


def _num(payload: Mapping[str, Any], *keys: str) -> float | None:
    for key in keys:
        if key not in payload:
            continue
        value = payload.get(key)
        if value is None or value == "":
            continue
        try:
            return float(value)
        except (TypeError, ValueError):
            continue
    return None


def _f_to_c(temp_f: float | None) -> float | None:
    if temp_f is None:
        return None
    return (temp_f - 32.0) * 5.0 / 9.0


def _mph_to_ms(mph: float | None) -> float | None:
    if mph is None:
        return None
    return mph * 0.44704


def _inhg_to_hpa(inhg: float | None) -> float | None:
    if inhg is None:
        return None
    return inhg * 33.8639


def _in_to_mm(inches: float | None) -> float | None:
    if inches is None:
        return None
    return inches * 25.4


def parse_ecowitt_payload(payload: Mapping[str, Any]) -> dict[str, Any]:
    """Mappt Ecowitt Custom-Server-Felder auf das Beobachtungs-Schema."""
    temp_c = _num(payload, "temp_c", "tempc", "outdoor_temp_c")
    if temp_c is None:
        temp_c = _f_to_c(_num(payload, "tempf", "tempF", "outdoor_temp_f"))

    humidity = _num(payload, "humidity_pct", "humidity", "outdoor_humidity")

    pressure = _num(payload, "pressure_hpa", "baromabs_hpa", "baromrel_hpa")
    if pressure is None:
        pressure = _inhg_to_hpa(_num(payload, "baromabsin", "baromrelin", "baromin"))

    wind_ms = _num(payload, "wind_ms", "windspeed_ms")
    if wind_ms is None:
        wind_ms = _mph_to_ms(_num(payload, "windspeedmph", "windspeed"))

    gust_ms = _num(payload, "gust_ms")
    if gust_ms is None:
        gust_ms = _mph_to_ms(_num(payload, "windgustmph", "gustspeedmph"))

    wind_dir = _num(payload, "wind_dir_deg", "winddir", "winddir_avg10m")

    rain_mm = _num(payload, "rain_mm")
    if rain_mm is None:
        rain_mm = _in_to_mm(_num(payload, "yearlyrainin", "totalrainin", "dailyrainin", "rainin"))

    rain_rate = _num(payload, "rain_rate_mm_h")
    if rain_rate is None:
        rain_rate = _in_to_mm(_num(payload, "rainratein", "rrain_piezo"))

    uvi = _num(payload, "uvi", "uv")
    lux = _num(payload, "lux", "solarradiation")
    # Ecowitt solarradiation oft W/m^2 — lux bleibt nur wenn explizit lux
    if "lux" not in payload and "solarradiation" in payload:
        lux = None
        # behalte W/m2 unter raw; optional solarradiation_wm2
        solar = _num(payload, "solarradiation")
    else:
        solar = _num(payload, "solarradiation_wm2")

    indoor_c = _num(payload, "indoor_temp_c", "tempinc")
    if indoor_c is None:
        indoor_c = _f_to_c(_num(payload, "tempinf", "indoortempf"))
    indoor_h = _num(payload, "indoor_humidity_pct", "humidityin", "indoorhumidity")

    dew_c = _num(payload, "dewpoint_c", "dewpointc")
    if dew_c is None:
        dew_c = _f_to_c(_num(payload, "dewpointf", "dewptf"))

    when = payload.get("when") or payload.get("dateutc")
    if when in (None, "", "now"):
        when = datetime.now(timezone.utc).isoformat()
    else:
        when = str(when)

    observation = {
        "when": when,
        "temp_c": temp_c,
        "humidity_pct": humidity,
        "pressure_hpa": pressure,
        "wind_ms": wind_ms,
        "wind_dir_deg": wind_dir,
        "gust_ms": gust_ms,
        "rain_mm": rain_mm,
        "rain_rate_mm_h": rain_rate,
        "uvi": uvi,
        "lux": lux,
        "dewpoint_c": dew_c,
        "indoor_temp_c": indoor_c,
        "indoor_humidity_pct": indoor_h,
        "solarradiation_wm2": solar,
        "raw": dict(payload),
        "provider": SOURCE_ECOWITT,
    }
    return observation


def parse_observation_payload(payload: Mapping[str, Any]) -> dict[str, Any]:
    """Generisch: bereits metrisches JSON oder Ecowitt-Felder."""
    if any(key in payload for key in ("tempf", "windspeedmph", "baromrelin", "humidityin")):
        return parse_ecowitt_payload(payload)
    # metrisches Canonical-Schema durchreichen
    out = parse_ecowitt_payload(payload)
    # wenn temp_c schon gesetzt war, raw behalten
    return out
