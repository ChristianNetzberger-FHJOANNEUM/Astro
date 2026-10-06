"""Tests fuer WeatherSafetyEvaluator (Zustandsautomat)."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

from mele.weather_safety import (
    DATA_LIVE,
    DATA_OFFLINE,
    DATA_STALE,
    SAFETY_CAUTION,
    SAFETY_SAFE,
    SAFETY_UNKNOWN,
    SAFETY_UNSAFE,
    WeatherSafetyConfig,
    evaluate_weather_safety,
)


def _sample(
    *,
    age_s: float,
    temp_c: float = 12.0,
    dewpoint_c: float = 8.0,
    humidity_pct: float = 70.0,
    wind_ms: float = 1.0,
    gust_ms: float = 1.5,
    wind_dir_deg: float = 257.0,
    rain_rate_mm_h: float = 0.0,
    pressure_hpa: float = 1000.0,
    now: datetime | None = None,
) -> dict:
    ref = now or datetime(2026, 10, 5, 12, 0, tzinfo=timezone.utc)
    when = (ref - timedelta(seconds=age_s)).isoformat()
    return {
        "id": 1,
        "when": when,
        "recorded_at": when,
        "temp_c": temp_c,
        "dewpoint_c": dewpoint_c,
        "dewpoint_margin_c": temp_c - dewpoint_c,
        "humidity_pct": humidity_pct,
        "wind_ms": wind_ms,
        "gust_ms": gust_ms,
        "wind_dir_deg": wind_dir_deg,
        "rain_rate_mm_h": rain_rate_mm_h,
        "pressure_hpa": pressure_hpa,
    }


def test_live_safe() -> None:
    now = datetime(2026, 10, 5, 12, 0, tzinfo=timezone.utc)
    result = evaluate_weather_safety(
        _sample(age_s=8, temp_c=20, dewpoint_c=8, now=now),
        cfg=WeatherSafetyConfig(),
        now=now,
    )
    assert result.data_state == DATA_LIVE
    assert result.safety_state == SAFETY_SAFE
    assert result.dew_margin_k == 12.0
    assert abs((result.sample_age_s or 0) - 8) < 0.5


def test_stale_forces_unknown() -> None:
    now = datetime(2026, 10, 5, 12, 0, tzinfo=timezone.utc)
    # Frisch genug fuer Werte, aber STALE → keine SAFE-Aussage
    result = evaluate_weather_safety(
        _sample(age_s=90, temp_c=20, dewpoint_c=8, rain_rate_mm_h=5.0, now=now),
        cfg=WeatherSafetyConfig(live_max_age_s=60, stale_max_age_s=180),
        now=now,
    )
    assert result.data_state == DATA_STALE
    assert result.safety_state == SAFETY_UNKNOWN
    assert "weather_data_not_live" in result.reasons


def test_offline() -> None:
    result = evaluate_weather_safety(None, offline=True, offline_error="unreachable")
    assert result.data_state == DATA_OFFLINE
    assert result.safety_state == SAFETY_UNKNOWN


def test_offline_by_age() -> None:
    now = datetime(2026, 10, 5, 12, 0, tzinfo=timezone.utc)
    result = evaluate_weather_safety(
        _sample(age_s=400, now=now),
        cfg=WeatherSafetyConfig(live_max_age_s=60, stale_max_age_s=180),
        now=now,
    )
    assert result.data_state == DATA_OFFLINE
    assert result.safety_state == SAFETY_UNKNOWN


def test_rain_unsafe() -> None:
    now = datetime(2026, 10, 5, 12, 0, tzinfo=timezone.utc)
    result = evaluate_weather_safety(
        _sample(age_s=5, rain_rate_mm_h=0.5, now=now),
        cfg=WeatherSafetyConfig(rain_unsafe_mmh=0.01),
        now=now,
    )
    assert result.data_state == DATA_LIVE
    assert result.safety_state == SAFETY_UNSAFE
    assert "rain_rate_high" in result.reasons


def test_dew_caution() -> None:
    now = datetime(2026, 10, 5, 12, 0, tzinfo=timezone.utc)
    result = evaluate_weather_safety(
        _sample(age_s=5, temp_c=12.0, dewpoint_c=10.0, now=now),
        cfg=WeatherSafetyConfig(dew_caution_k=3.0),
        now=now,
    )
    assert result.safety_state == SAFETY_CAUTION
    assert "dew_margin_low" in result.reasons
    assert result.dew_margin_k == 2.0


def test_dew_trend_and_eta() -> None:
    now = datetime(2026, 10, 5, 12, 0, tzinfo=timezone.utc)
    history = []
    # Margin 6.0 → 4.5 über 40 min (~ -2.25 K/h)
    for minutes, margin in [(40, 6.0), (30, 5.6), (20, 5.2), (10, 4.8), (0, 4.5)]:
        stamp = now - timedelta(minutes=minutes)
        history.append(
            {
                "recorded_at": stamp.isoformat(),
                "temp_c": 12.0,
                "dewpoint_c": 12.0 - margin,
                "dewpoint_margin_c": margin,
            }
        )
    current = _sample(age_s=5, temp_c=12.0, dewpoint_c=7.5, now=now)
    current["dewpoint_margin_c"] = 4.5
    result = evaluate_weather_safety(
        current,
        history,
        cfg=WeatherSafetyConfig(
            dew_caution_k=3.0,
            dew_eta_threshold_k=3.0,
            dew_trend_window_min=45,
            dew_trend_min_samples=4,
            dew_eta_min_abs_trend_k_per_h=0.25,
        ),
        now=now,
    )
    assert result.data_state == DATA_LIVE
    assert result.dew_trend_k_per_hour is not None
    assert result.dew_trend_k_per_hour < -0.5
    assert result.dew_risk == "increasing"
    assert result.dew_eta_hours is not None
    assert 0.5 < result.dew_eta_hours < 3.0


def test_optional_wind_caution() -> None:
    now = datetime(2026, 10, 5, 12, 0, tzinfo=timezone.utc)
    result = evaluate_weather_safety(
        _sample(age_s=5, wind_ms=6.0, gust_ms=9.0, temp_c=20, dewpoint_c=5, now=now),
        cfg=WeatherSafetyConfig(wind_caution_ms=5.0, gust_caution_ms=8.0),
        now=now,
    )
    assert result.safety_state == SAFETY_CAUTION
    assert "wind_high" in result.reasons
    assert "gust_high" in result.reasons
