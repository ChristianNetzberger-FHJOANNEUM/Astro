"""Wetter-Journal + Ecowitt/lokal Mapping."""

from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from mele.weather_journal import (
    SOURCE_ECOWITT,
    SOURCE_GEOSPHERE,
    append_forecast,
    append_observation,
    iter_journal,
    journal_path_for,
    last_entry,
    should_skip_forecast,
)
from mele.weather_local import parse_ecowitt_payload, parse_observation_payload

FIXTURE = Path(__file__).resolve().parent / "fixtures" / "weather" / "nwp-sample.json"


def _forecast_payload() -> dict:
    from mele.weather import parse_nwp

    return parse_nwp(
        json.loads(FIXTURE.read_text(encoding="utf-8")),
        query_lat=48.3,
        query_lon=14.28,
    )


def test_append_forecast_jsonl(tmp_path: Path) -> None:
    now = datetime(2026, 9, 26, 18, 0, tzinfo=timezone.utc)
    record = append_forecast(
        tmp_path,
        _forecast_payload(),
        latitude_deg=48.3,
        longitude_deg=14.28,
        label="Test",
        now=now,
    )
    path = Path(record["path"])
    assert path == journal_path_for(tmp_path, now)
    assert path.is_file()
    line = path.read_text(encoding="utf-8").strip()
    item = json.loads(line)
    assert item["kind"] == "forecast"
    assert item["source"] == SOURCE_GEOSPHERE
    assert item["site"]["label"] == "Test"
    assert item["forecast"]["hour_count"] == 4
    assert len(item["forecast"]["hours"]) == 4
    assert item["observation"] is None


def test_should_skip_within_interval(tmp_path: Path) -> None:
    t0 = datetime(2026, 9, 26, 18, 0, tzinfo=timezone.utc)
    append_forecast(
        tmp_path,
        _forecast_payload(),
        latitude_deg=48.3,
        longitude_deg=14.28,
        now=t0,
    )
    assert should_skip_forecast(
        tmp_path,
        latitude_deg=48.3,
        longitude_deg=14.28,
        interval_h=1.0,
        now=t0 + timedelta(minutes=30),
    )
    assert not should_skip_forecast(
        tmp_path,
        latitude_deg=48.3,
        longitude_deg=14.28,
        interval_h=1.0,
        now=t0 + timedelta(hours=1),
    )


def test_parse_ecowitt_imperial() -> None:
    # Typische Custom-Server-Felder (imperial) von GW1200+WS90
    obs = parse_ecowitt_payload(
        {
            "tempf": "68.0",
            "humidity": "55",
            "baromrelin": "29.92",
            "windspeedmph": "4.47",
            "winddir": "180",
            "windgustmph": "8.95",
            "dailyrainin": "0.1",
            "rrain_piezo": "0.04",
            "uv": "3",
            "solarradiation": "450.5",
            "tempinf": "72.5",
            "humidityin": "40",
            "dateutc": "2026-09-26T16:00:00",
        }
    )
    assert obs["temp_c"] == pytest.approx(20.0, abs=0.05)
    assert obs["humidity_pct"] == 55.0
    assert obs["pressure_hpa"] == pytest.approx(1013.25, abs=0.5)
    assert obs["wind_ms"] == pytest.approx(2.0, abs=0.02)
    assert obs["wind_dir_deg"] == 180.0
    assert obs["gust_ms"] == pytest.approx(4.0, abs=0.02)
    assert obs["rain_mm"] == pytest.approx(2.54, abs=0.01)
    assert obs["rain_rate_mm_h"] == pytest.approx(1.016, abs=0.02)
    assert obs["uvi"] == 3.0
    assert obs["lux"] is None
    assert obs["solarradiation_wm2"] == 450.5
    assert obs["indoor_temp_c"] == pytest.approx(22.5, abs=0.05)
    assert obs["indoor_humidity_pct"] == 40.0
    assert obs["provider"] == SOURCE_ECOWITT


def test_parse_metric_json() -> None:
    obs = parse_observation_payload(
        {
            "temp_c": 12.5,
            "humidity_pct": 80,
            "wind_ms": 1.2,
            "pressure_hpa": 1010,
            "uvi": 0,
            "lux": 1200,
        }
    )
    assert obs["temp_c"] == 12.5
    assert obs["lux"] == 1200.0
    assert obs["wind_ms"] == 1.2


def test_append_observation_keeps_station_fields(tmp_path: Path) -> None:
    now = datetime(2026, 9, 26, 19, 0, tzinfo=timezone.utc)
    obs = parse_ecowitt_payload(
        {
            "tempf": "50",
            "humidity": "70",
            "uv": "1",
            "solarradiation": "100",
            "windspeedmph": "2.24",
            "winddir": "90",
        }
    )
    record = append_observation(
        tmp_path,
        obs,
        latitude_deg=48.3,
        longitude_deg=14.28,
        label="Garten",
        now=now,
    )
    assert record["kind"] == "observation"
    assert record["source"] == SOURCE_ECOWITT
    stored = record["observation"]
    assert stored["temp_c"] == pytest.approx(10.0, abs=0.05)
    assert stored["solarradiation_wm2"] == 100.0
    assert stored["uvi"] == 1.0
    assert "raw" in stored

    rows = iter_journal(tmp_path, kind="observation")
    assert len(rows) == 1
    last = last_entry(
        tmp_path,
        kind="observation",
        source=SOURCE_ECOWITT,
        latitude_deg=48.3,
        longitude_deg=14.28,
    )
    assert last is not None
    assert last["site"]["label"] == "Garten"
