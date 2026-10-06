"""Tests fuer weather_server Livedata-Parser + SQLite-Store."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from weather_server.ecowitt.parse import parse_livedata
from weather_server.storage.db import WeatherStore

FIXTURE = Path(__file__).resolve().parent / "fixtures" / "weather" / "gw1200_livedata_metric.json"


def test_parse_livedata_metric_fixture() -> None:
    payload = json.loads(FIXTURE.read_text(encoding="utf-8"))
    obs = parse_livedata(payload, when="2026-10-05T10:00:00+00:00")
    assert obs["temp_c"] == pytest.approx(20.7)
    assert obs["humidity_pct"] == pytest.approx(53.0)
    assert obs["dewpoint_c"] == pytest.approx(10.8)
    assert obs["dewpoint_margin_c"] == pytest.approx(9.9)
    assert obs["wind_ms"] == pytest.approx(0.6)
    assert obs["gust_ms"] == pytest.approx(1.5)
    assert obs["day_wind_max_ms"] == pytest.approx(2.0)
    assert obs["wind_dir_deg"] == pytest.approx(144.0)
    assert obs["solarradiation_wm2"] == pytest.approx(648.46)
    assert obs["lux"] is None
    assert obs["uvi"] == pytest.approx(6.0)
    assert obs["rain_mm"] == pytest.approx(0.0)
    assert obs["rain_rate_mm_h"] == pytest.approx(0.0)
    assert obs["pressure_hpa"] == pytest.approx(996.1)
    assert obs["pressure_abs_hpa"] == pytest.approx(996.0)
    assert obs["indoor_temp_c"] == pytest.approx(34.5)
    assert obs["indoor_humidity_pct"] == pytest.approx(24.0)
    assert obs["provider"] == "ecowitt_livedata"
    assert obs["when"] == "2026-10-05T10:00:00+00:00"


def test_store_latest_and_history(tmp_path: Path) -> None:
    payload = json.loads(FIXTURE.read_text(encoding="utf-8"))
    obs = parse_livedata(payload)
    store = WeatherStore(tmp_path / "weather.sqlite")
    first = store.insert_sample(obs, label="GW1200")
    second = store.insert_sample({**obs, "temp_c": 21.0}, label="GW1200")
    latest = store.latest()
    assert latest is not None
    assert latest["id"] == second["id"]
    assert latest["temp_c"] == pytest.approx(21.0)
    assert latest["dewpoint_margin_c"] == pytest.approx(obs["dewpoint_margin_c"])
    hist = store.history(limit=10)
    assert len(hist) == 2
    assert hist[0]["id"] == second["id"]
    assert hist[1]["id"] == first["id"]
    assert store.sample_count() == 2
    store.close()
