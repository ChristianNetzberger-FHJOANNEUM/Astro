"""Tests fuer MeLE weather_server Consumer."""

from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import patch

import pytest

from mele.weather_journal import append_observation, iter_journal
from mele.weather_server_client import (
    SOURCE_WEATHER_SERVER,
    format_station_summary,
    sample_id,
    sample_to_observation,
)


def test_sample_to_observation_and_summary() -> None:
    sample = {
        "id": 42,
        "when": "2026-10-05T12:00:00+00:00",
        "recorded_at": "2026-10-05T12:00:00+00:00",
        "temp_c": 22.8,
        "humidity_pct": 47.0,
        "dewpoint_c": 10.9,
        "dewpoint_margin_c": 11.9,
        "wind_ms": 0.5,
        "label": "GW1200",
    }
    obs = sample_to_observation(sample)
    assert obs["temp_c"] == 22.8
    assert obs["dewpoint_margin_c"] == 11.9
    assert obs["provider"] == SOURCE_WEATHER_SERVER
    assert sample_id(obs) == 42
    assert sample_id(sample) == 42
    text = format_station_summary(obs, label="Garten")
    assert "Garten" in text
    assert "22.8°C" in text
    assert "Δ11.9K" in text


def test_journal_keeps_margin(tmp_path: Path) -> None:
    obs = sample_to_observation(
        {
            "id": 7,
            "temp_c": 10.0,
            "dewpoint_c": 2.0,
            "dewpoint_margin_c": 8.0,
            "humidity_pct": 55,
        }
    )
    record = append_observation(
        tmp_path,
        obs,
        latitude_deg=48.25,
        longitude_deg=14.36,
        source=SOURCE_WEATHER_SERVER,
        label="Garten",
    )
    assert record["source"] == SOURCE_WEATHER_SERVER
    assert record["observation"]["dewpoint_margin_c"] == 8.0
    assert record["observation"]["raw"]["weather_server_sample_id"] == 7
    rows = iter_journal(tmp_path, kind="observation")
    assert len(rows) == 1


def test_fetch_current_parses_ok() -> None:
    from mele.weather_server_client import fetch_current

    payload = {
        "ok": True,
        "sample": {"id": 1, "temp_c": 20.0, "dewpoint_margin_c": 9.0},
    }
    fake_body = json.dumps(payload).encode("utf-8")

    class _Resp:
        def read(self) -> bytes:
            return fake_body

        def __enter__(self):
            return self

        def __exit__(self, *args):
            return False

    with patch("mele.weather_server_client.urlopen", return_value=_Resp()):
        sample = fetch_current("http://127.0.0.1:8765")
    assert sample["id"] == 1
    assert sample["temp_c"] == 20.0


def test_fetch_current_wraps_timeout_error() -> None:
    from mele.weather_server_client import WeatherServerError, fetch_current

    with patch("mele.weather_server_client.urlopen", side_effect=TimeoutError("timed out")):
        with pytest.raises(WeatherServerError, match="timeout"):
            fetch_current("http://127.0.0.1:8765", timeout_s=1.0)
