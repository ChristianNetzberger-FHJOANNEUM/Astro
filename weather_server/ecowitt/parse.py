"""Parser fuer Ecowitt /get_livedata_info → SI-Beobachtungsschema."""

from __future__ import annotations

import re
from datetime import datetime, timezone
from typing import Any, Mapping

# common_list / piezoRain Hex-IDs (Ecowitt HTTP API Generic)
_ID_OUTTEMP = "0x02"
_ID_DEWPOINT = "0x03"
_ID_OUTHUMI = "0x07"
_ID_WINDDIR = "0x0a"
_ID_WINDSPEED = "0x0b"
_ID_GUSTSPEED = "0x0c"
_ID_RAINEVENT = "0x0d"
_ID_RAINRATE = "0x0e"
_ID_RAINDAY = "0x10"
_ID_RAINWEEK = "0x11"
_ID_RAINMONTH = "0x12"
_ID_RAINYEAR = "0x13"
_ID_LIGHT = "0x15"
_ID_UVI = "0x17"
_ID_DAYWINDMAX = "0x19"

_NUM_RE = re.compile(r"[-+]?\d+(?:\.\d+)?")


def _norm_id(raw: Any) -> str:
    text = str(raw or "").strip().lower()
    if text.startswith("0x"):
        try:
            return f"0x{int(text, 16):02x}"
        except ValueError:
            return text
    if text.isdigit():
        # decimal ids like "3" (feels like) stay as-is; hex-looking numerics rare
        return text
    return text


def _first_number(text: Any) -> float | None:
    if text is None:
        return None
    if isinstance(text, (int, float)):
        return float(text)
    match = _NUM_RE.search(str(text))
    if not match:
        return None
    try:
        return float(match.group(0))
    except ValueError:
        return None


def _index_by_id(items: Any) -> dict[str, Mapping[str, Any]]:
    out: dict[str, Mapping[str, Any]] = {}
    if not isinstance(items, list):
        return out
    for item in items:
        if not isinstance(item, Mapping):
            continue
        key = _norm_id(item.get("id"))
        if key:
            out[key] = item
    return out


def _val(index: Mapping[str, Mapping[str, Any]], item_id: str) -> float | None:
    entry = index.get(_norm_id(item_id))
    if not entry:
        return None
    return _first_number(entry.get("val"))


def parse_livedata(payload: Mapping[str, Any], *, when: str | None = None) -> dict[str, Any]:
    """Mappt Gateway-Livedata auf SI-Felder (wie MeLE-Observation-Schema).

    Gateway liefert bei metrischer Einstellung bereits °C / m/s / hPa / mm / W/m².
    """
    common = _index_by_id(payload.get("common_list"))
    rain = _index_by_id(payload.get("piezoRain") or payload.get("rain"))

    temp_c = _val(common, _ID_OUTTEMP)
    humidity = _val(common, _ID_OUTHUMI)
    dew_c = _val(common, _ID_DEWPOINT)
    wind_ms = _val(common, _ID_WINDSPEED)
    gust_ms = _val(common, _ID_GUSTSPEED)
    wind_dir = _val(common, _ID_WINDDIR)
    day_wind_max = _val(common, _ID_DAYWINDMAX)
    uvi = _val(common, _ID_UVI)

    # 0x15: lokal oft W/m² (nicht lux) — unit aus val/unit ableiten
    light_entry = common.get(_norm_id(_ID_LIGHT))
    solar = None
    lux = None
    if light_entry is not None:
        light_num = _first_number(light_entry.get("val"))
        unit_blob = f"{light_entry.get('val', '')} {light_entry.get('unit', '')}".lower()
        if light_num is not None:
            if "w/m" in unit_blob or "w/㎡" in unit_blob:
                solar = light_num
            elif "lux" in unit_blob:
                lux = light_num
            else:
                # metrisches GW1200: typisch W/m2 ohne "lux"
                solar = light_num

    rain_day = _val(rain, _ID_RAINDAY)
    rain_rate = _val(rain, _ID_RAINRATE)
    rain_event = _val(rain, _ID_RAINEVENT)
    rain_week = _val(rain, _ID_RAINWEEK)
    rain_month = _val(rain, _ID_RAINMONTH)
    rain_year = _val(rain, _ID_RAINYEAR)

    indoor_c = None
    indoor_h = None
    pressure = None
    pressure_abs = None
    wh25_list = payload.get("wh25")
    if isinstance(wh25_list, list) and wh25_list:
        wh25 = wh25_list[0]
        if isinstance(wh25, Mapping):
            indoor_c = _first_number(wh25.get("intemp"))
            indoor_h = _first_number(wh25.get("inhumi"))
            pressure = _first_number(wh25.get("rel"))
            pressure_abs = _first_number(wh25.get("abs"))

    margin = None
    if temp_c is not None and dew_c is not None:
        margin = round(temp_c - dew_c, 2)

    stamp = when
    if not stamp:
        stamp = datetime.now(timezone.utc).isoformat()

    return {
        "when": stamp,
        "temp_c": temp_c,
        "humidity_pct": humidity,
        "pressure_hpa": pressure,
        "pressure_abs_hpa": pressure_abs,
        "wind_ms": wind_ms,
        "wind_dir_deg": wind_dir,
        "gust_ms": gust_ms,
        "day_wind_max_ms": day_wind_max,
        "rain_mm": rain_day,
        "rain_rate_mm_h": rain_rate,
        "rain_event_mm": rain_event,
        "rain_week_mm": rain_week,
        "rain_month_mm": rain_month,
        "rain_year_mm": rain_year,
        "uvi": uvi,
        "lux": lux,
        "dewpoint_c": dew_c,
        "dewpoint_margin_c": margin,
        "indoor_temp_c": indoor_c,
        "indoor_humidity_pct": indoor_h,
        "solarradiation_wm2": solar,
        "provider": "ecowitt_livedata",
    }
