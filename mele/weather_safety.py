"""Observatory weather safety — reine Entscheidungslogik (kein UI, kein HTTP).

MeLE und spaetere Clients (Imaging, Advisor, Alerts) sollen dieselbe Auswertung nutzen.
weather_server bleibt SoR; hier nur Ableitung aus current + history.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from typing import Any, Mapping, Sequence


DATA_LIVE = "LIVE"
DATA_STALE = "STALE"
DATA_OFFLINE = "OFFLINE"

SAFETY_SAFE = "SAFE"
SAFETY_CAUTION = "CAUTION"
SAFETY_UNSAFE = "UNSAFE"
SAFETY_UNKNOWN = "UNKNOWN"


@dataclass(frozen=True)
class WeatherSafetyConfig:
    live_max_age_s: float = 60.0
    stale_max_age_s: float = 180.0
    dew_caution_k: float = 3.0
    # Optional: None = Regel deaktiviert
    wind_caution_ms: float | None = None
    gust_caution_ms: float | None = None
    rain_unsafe_mmh: float = 0.01
    dew_trend_window_min: float = 45.0
    dew_trend_min_samples: int = 4
    dew_eta_threshold_k: float = 3.0
    # |trend| darunter: kein ETA (K/h)
    dew_eta_min_abs_trend_k_per_h: float = 0.25

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class WeatherSafetyResult:
    data_state: str
    safety_state: str
    reasons: list[str] = field(default_factory=list)
    sample_age_s: float | None = None
    dew_margin_k: float | None = None
    dew_trend_k_per_hour: float | None = None
    dew_eta_hours: float | None = None
    dew_risk: str | None = None  # increasing / decreasing / steady / None
    temp_c: float | None = None
    humidity_pct: float | None = None
    dewpoint_c: float | None = None
    wind_ms: float | None = None
    gust_ms: float | None = None
    wind_dir_deg: float | None = None
    rain_rate_mm_h: float | None = None
    pressure_hpa: float | None = None
    when: str | None = None
    offline_error: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def _finite(value: Any) -> float | None:
    if value is None or value == "":
        return None
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    if number != number:  # NaN
        return None
    return number


def _parse_when(value: Any) -> datetime | None:
    if value is None or value == "":
        return None
    text = str(value).replace("Z", "+00:00")
    try:
        stamp = datetime.fromisoformat(text)
    except ValueError:
        return None
    if stamp.tzinfo is None:
        stamp = stamp.replace(tzinfo=timezone.utc)
    return stamp.astimezone(timezone.utc)


def sample_age_seconds(sample: Mapping[str, Any] | None, *, now: datetime | None = None) -> float | None:
    if not sample:
        return None
    stamp = _parse_when(sample.get("recorded_at") or sample.get("when") or sample.get("station_when"))
    if stamp is None:
        return None
    ref = (now or datetime.now(timezone.utc)).astimezone(timezone.utc)
    return max(0.0, (ref - stamp).total_seconds())


def classify_data_state(
    age_s: float | None,
    *,
    cfg: WeatherSafetyConfig,
    offline: bool = False,
) -> str:
    if offline or age_s is None:
        return DATA_OFFLINE
    if age_s <= float(cfg.live_max_age_s):
        return DATA_LIVE
    if age_s <= float(cfg.stale_max_age_s):
        return DATA_STALE
    return DATA_OFFLINE


def _dew_margin(sample: Mapping[str, Any]) -> float | None:
    margin = _finite(sample.get("dewpoint_margin_c"))
    if margin is not None:
        return margin
    temp = _finite(sample.get("temp_c"))
    dew = _finite(sample.get("dewpoint_c"))
    if temp is None or dew is None:
        return None
    return temp - dew


def _linear_trend_k_per_hour(
    history: Sequence[Mapping[str, Any]],
    *,
    window_min: float,
    min_samples: int,
    now: datetime | None = None,
) -> tuple[float | None, str | None]:
    """dew_margin vs Zeit → Steigung K/h. history: beliebig sortiert."""
    ref = (now or datetime.now(timezone.utc)).astimezone(timezone.utc)
    window_s = max(60.0, float(window_min) * 60.0)
    points: list[tuple[float, float]] = []
    for item in history:
        stamp = _parse_when(item.get("recorded_at") or item.get("when") or item.get("station_when"))
        margin = _dew_margin(item)
        if stamp is None or margin is None:
            continue
        age = (ref - stamp).total_seconds()
        if age < 0 or age > window_s:
            continue
        # x in Stunden vor now (negativ = Vergangenheit)
        points.append((-age / 3600.0, margin))

    if len(points) < max(2, int(min_samples)):
        return None, None

    # Luecken: Median-Delta der Sortierung; wenn max gap >> median*8 → unsicher
    points.sort(key=lambda p: p[0])
    gaps = [points[i + 1][0] - points[i][0] for i in range(len(points) - 1)]
    if gaps:
        gaps_sorted = sorted(gaps)
        median_gap = gaps_sorted[len(gaps_sorted) // 2]
        if median_gap > 0 and max(gaps) > max(0.25, median_gap * 8):
            return None, None

    n = len(points)
    sum_x = sum(x for x, _ in points)
    sum_y = sum(y for _, y in points)
    sum_xx = sum(x * x for x, _ in points)
    sum_xy = sum(x * y for x, y in points)
    denom = n * sum_xx - sum_x * sum_x
    if abs(denom) < 1e-12:
        return None, None
    slope = (n * sum_xy - sum_x * sum_y) / denom  # K pro Stunde
    if abs(slope) < 0.05:
        risk = "steady"
    elif slope < 0:
        risk = "increasing"  # Margin sinkt → Risiko steigt
    else:
        risk = "decreasing"
    return slope, risk


def evaluate_weather_safety(
    current: Mapping[str, Any] | None,
    history: Sequence[Mapping[str, Any]] | None = None,
    *,
    cfg: WeatherSafetyConfig | None = None,
    now: datetime | None = None,
    offline: bool = False,
    offline_error: str | None = None,
) -> WeatherSafetyResult:
    """Kern-Zustandsautomat: data_state + safety_state + Begruendungen."""
    conf = cfg or WeatherSafetyConfig()
    age = None if offline else sample_age_seconds(current, now=now)
    data_state = classify_data_state(age, cfg=conf, offline=offline or current is None)

    if data_state != DATA_LIVE:
        return WeatherSafetyResult(
            data_state=data_state,
            safety_state=SAFETY_UNKNOWN,
            reasons=["weather_data_not_live"],
            sample_age_s=age,
            dew_margin_k=_dew_margin(current) if current else None,
            temp_c=_finite(current.get("temp_c")) if current else None,
            humidity_pct=_finite(current.get("humidity_pct")) if current else None,
            dewpoint_c=_finite(current.get("dewpoint_c")) if current else None,
            wind_ms=_finite(current.get("wind_ms")) if current else None,
            gust_ms=_finite(current.get("gust_ms")) if current else None,
            wind_dir_deg=_finite(current.get("wind_dir_deg")) if current else None,
            rain_rate_mm_h=_finite(current.get("rain_rate_mm_h")) if current else None,
            pressure_hpa=_finite(current.get("pressure_hpa")) if current else None,
            when=str(current.get("when") or current.get("recorded_at") or "") or None if current else None,
            offline_error=offline_error,
        )

    assert current is not None
    reasons: list[str] = []
    safety = SAFETY_SAFE

    rain = _finite(current.get("rain_rate_mm_h"))
    if rain is not None and rain > float(conf.rain_unsafe_mmh):
        safety = SAFETY_UNSAFE
        reasons.append("rain_rate_high")

    margin = _dew_margin(current)
    if margin is not None and margin < float(conf.dew_caution_k):
        if safety != SAFETY_UNSAFE:
            safety = SAFETY_CAUTION
        reasons.append("dew_margin_low")

    wind = _finite(current.get("wind_ms"))
    if conf.wind_caution_ms is not None and wind is not None and wind >= float(conf.wind_caution_ms):
        if safety != SAFETY_UNSAFE:
            safety = SAFETY_CAUTION
        reasons.append("wind_high")

    gust = _finite(current.get("gust_ms"))
    if conf.gust_caution_ms is not None and gust is not None and gust >= float(conf.gust_caution_ms):
        if safety != SAFETY_UNSAFE:
            safety = SAFETY_CAUTION
        reasons.append("gust_high")

    trend, risk = _linear_trend_k_per_hour(
        history or [],
        window_min=conf.dew_trend_window_min,
        min_samples=conf.dew_trend_min_samples,
        now=now,
    )
    eta = None
    if (
        trend is not None
        and margin is not None
        and trend < -float(conf.dew_eta_min_abs_trend_k_per_h)
        and margin > float(conf.dew_eta_threshold_k)
    ):
        # Margin sinkt Richtung Schwellwert
        eta = (margin - float(conf.dew_eta_threshold_k)) / (-trend)
        if eta < 0 or eta > 24:
            eta = None
        elif risk is None:
            risk = "increasing"

    if risk == "increasing" and "dew_trend_increasing" not in reasons:
        # Trend allein hebt nicht auf CAUTION, ausser Margin schon niedrig —
        # aber als Info-Reason behalten wenn CAUTION/UNSAFE oder Margin nahe
        if safety in (SAFETY_CAUTION, SAFETY_UNSAFE) or (
            margin is not None and margin < float(conf.dew_caution_k) * 1.5
        ):
            reasons.append("dew_trend_increasing")

    return WeatherSafetyResult(
        data_state=data_state,
        safety_state=safety,
        reasons=reasons,
        sample_age_s=age,
        dew_margin_k=margin,
        dew_trend_k_per_hour=trend,
        dew_eta_hours=eta,
        dew_risk=risk,
        temp_c=_finite(current.get("temp_c")),
        humidity_pct=_finite(current.get("humidity_pct")),
        dewpoint_c=_finite(current.get("dewpoint_c")),
        wind_ms=wind,
        gust_ms=gust,
        wind_dir_deg=_finite(current.get("wind_dir_deg")),
        rain_rate_mm_h=rain,
        pressure_hpa=_finite(current.get("pressure_hpa")),
        when=str(current.get("when") or current.get("recorded_at") or "") or None,
        offline_error=None,
    )


def load_weather_safety_config(raw: Mapping[str, Any] | None) -> WeatherSafetyConfig:
    data = raw if isinstance(raw, Mapping) else {}

    def _opt_float(key: str) -> float | None:
        if key not in data or data.get(key) in (None, ""):
            return None
        return float(data[key])

    return WeatherSafetyConfig(
        live_max_age_s=float(data.get("live_max_age_s") or 60.0),
        stale_max_age_s=float(data.get("stale_max_age_s") or 180.0),
        dew_caution_k=float(data.get("dew_caution_k") or 3.0),
        wind_caution_ms=_opt_float("wind_caution_ms"),
        gust_caution_ms=_opt_float("gust_caution_ms"),
        rain_unsafe_mmh=float(data.get("rain_unsafe_mmh") if data.get("rain_unsafe_mmh") is not None else 0.01),
        dew_trend_window_min=float(data.get("dew_trend_window_min") or 45.0),
        dew_trend_min_samples=int(data.get("dew_trend_min_samples") or 4),
        dew_eta_threshold_k=float(data.get("dew_eta_threshold_k") or 3.0),
        dew_eta_min_abs_trend_k_per_h=float(data.get("dew_eta_min_abs_trend_k_per_h") or 0.25),
    )
