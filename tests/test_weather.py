from datetime import datetime, timezone
from pathlib import Path

import pytest

from mele.weather import (
    WeatherError,
    cache_path,
    load_forecast,
    parse_nwp,
    summarize,
    wind_speed_ms,
)

FIXTURE = Path(__file__).resolve().parent / "fixtures" / "weather" / "nwp-sample.json"


def _payload() -> dict:
    import json

    return json.loads(FIXTURE.read_text(encoding="utf-8"))


def test_parse_nwp_and_wind() -> None:
    data = parse_nwp(_payload(), query_lat=48.3, query_lon=14.28)
    assert data["source"] == "nwp-v2-1h-1km"
    assert len(data["hours"]) == 4
    first = data["hours"][0]
    assert first["cloud_pct"] == 20.0
    assert first["temp_c"] == 12.0
    assert abs((first["wind_ms"] or 0) - 1.0) < 0.01
    assert data["grid_lat"] == pytest.approx(48.303)
    assert wind_speed_ms(3.0, 4.0) == 5.0


def test_summarize_next_hours() -> None:
    hours = parse_nwp(_payload(), query_lat=48.3, query_lon=14.28)["hours"]
    now = datetime(2026, 9, 24, 18, 10, tzinfo=timezone.utc)
    summary = summarize(hours, now=now, window_h=12)
    assert summary["cloud_min"] == 15.0
    assert summary["cloud_max"] == 40.0
    assert "Bewoelkung 15-40 %" in summary["text"]
    assert "wenig Wind" in summary["text"]


def test_load_forecast_uses_cache_when_fetch_fails(tmp_path: Path) -> None:
    parsed = parse_nwp(_payload(), query_lat=48.3, query_lon=14.28)
    parsed["fetched_at"] = "2026-09-24T12:00:00+00:00"
    path = cache_path(tmp_path, 48.3, 14.28)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(__import__("json").dumps(parsed), encoding="utf-8")

    def boom(_lat: float, _lon: float) -> dict:
        raise WeatherError("offline")

    now = datetime(2026, 9, 24, 18, 0, tzinfo=timezone.utc)
    data = load_forecast(48.3, 14.28, tmp_path, refresh=True, now=now, fetch_fn=boom)
    assert data["offline"] is True
    assert data["hours"]
    assert data["summary"]["cloud_max"] == 40.0


def test_load_forecast_writes_cache(tmp_path: Path) -> None:
    now = datetime(2026, 9, 24, 18, 0, tzinfo=timezone.utc)
    data = load_forecast(
        48.3,
        14.28,
        tmp_path,
        refresh=True,
        now=now,
        fetch_fn=lambda _a, _b: _payload(),
    )
    assert data["offline"] is False
    assert cache_path(tmp_path, 48.3, 14.28).is_file()
    again = load_forecast(
        48.3,
        14.28,
        tmp_path,
        refresh=False,
        now=now,
        fetch_fn=lambda _a, _b: (_ for _ in ()).throw(WeatherError("no")),
    )
    assert again["offline"] is False
    assert len(again["hours"]) == 4


def test_load_forecast_cache_only_without_file(tmp_path: Path) -> None:
    with pytest.raises(WeatherError, match="Wettercache"):
        load_forecast(48.3, 14.28, tmp_path, network=False)
