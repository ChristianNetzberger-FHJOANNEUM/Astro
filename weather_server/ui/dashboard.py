"""NiceGUI live dashboard for weather_server."""

from __future__ import annotations

from datetime import datetime
from typing import Any

from nicegui import app, ui

from weather_server.collector import WeatherCollector
from weather_server.config import WeatherServerSettings
from weather_server.storage.db import WeatherStore

_REFRESH_S = 5.0
_SAMPLE_CHOICES = [30, 60, 120, 240, 480, 960]
_DEFAULT_SERIES = ("temp_c", "dewpoint_margin_c")
_DEFAULT_SAMPLES = 120

# Plotbare Größen: storage-key → (UI-Label, Einheiten-Hinweis, Farbe)
_SERIES: dict[str, tuple[str, str, str]] = {
    "temp_c": ("Temp", "°C", "#0f766e"),
    "humidity_pct": ("Feuchte", "%", "#2563eb"),
    "dewpoint_c": ("Taupunkt", "°C", "#7c3aed"),
    "dewpoint_margin_c": ("Tau-Abstand", "K", "#ca8a04"),
    "wind_ms": ("Wind", "m/s", "#0284c7"),
    "gust_ms": ("Böe", "m/s", "#0369a1"),
    "pressure_hpa": ("Druck", "hPa", "#475569"),
    "rain_mm": ("Regen", "mm", "#0d9488"),
    "rain_rate_mm_h": ("Regenrate", "mm/h", "#14b8a6"),
    "solarradiation_wm2": ("Solar", "W/m²", "#ea580c"),
    "uvi": ("UVI", "", "#c2410c"),
}


def _fmt(value: Any, *, digits: int = 1, suffix: str = "") -> str:
    if value is None:
        return "—"
    try:
        number = float(value)
    except (TypeError, ValueError):
        return "—"
    text = f"{number:.{digits}f}"
    return f"{text}{suffix}"


def _fmt_when(value: Any) -> str:
    if not value:
        return "—"
    text = str(value)
    try:
        stamp = datetime.fromisoformat(text.replace("Z", "+00:00"))
        return stamp.astimezone().strftime("%Y-%m-%d %H:%M:%S %Z")
    except ValueError:
        return text


def _metric(title: str, *, unit: str = "", hint: str = "") -> ui.label:
    """Kompakte Karte: Name (+ Einheit) in Zeile 1, Wert in Zeile 2."""
    with ui.card().classes("ws-card"):
        head = title if not unit else f"{title} ({unit})"
        if hint:
            head = f"{head} · {hint}"
        ui.label(head).classes("ws-card-title")
        value = ui.label("—").classes("ws-card-value")
    return value


def _series_pref_key(key: str) -> str:
    return f"ws_series_{key}"


def _ensure_prefs() -> dict[str, Any]:
    """Session-/user-persistente Dashboard-Einstellungen (top-level keys)."""
    user = app.storage.user
    for key in _SERIES:
        pref_key = _series_pref_key(key)
        if pref_key not in user:
            user[pref_key] = key in _DEFAULT_SERIES

    samples = user.get("ws_chart_samples")
    if samples not in _SAMPLE_CHOICES:
        user["ws_chart_samples"] = _DEFAULT_SAMPLES

    if "ws_show_table" not in user:
        user["ws_show_table"] = True

    return user


def build_dashboard(
    settings: WeatherServerSettings,
    store: WeatherStore,
    collector: WeatherCollector,
) -> None:
    """Build the root page UI (call inside @ui.page)."""
    prefs = _ensure_prefs()

    ui.colors(primary="#1f4e5f", secondary="#334155", accent="#0e7490")
    ui.query("body").classes("bg-slate-50")

    ui.add_head_html(
        """
        <style>
          .ws-wrap { max-width: 1400px; margin: 0 auto; padding: 14px 16px 28px; }
          .ws-main {
            display: grid;
            grid-template-columns: minmax(0, 1.15fr) minmax(320px, 1fr);
            gap: 16px;
            min-height: min(72vh, 780px);
            align-items: stretch;
          }
          @media (max-width: 960px) {
            .ws-main { grid-template-columns: 1fr; min-height: 0; }
          }
          .ws-groups {
            display: grid;
            grid-template-columns: 1fr 1fr;
            gap: 12px;
            height: 100%;
          }
          @media (max-width: 640px) {
            .ws-groups { grid-template-columns: 1fr; }
          }
          .ws-group {
            border: 1px solid #e2e8f0;
            border-radius: 12px;
            background: #fff;
            padding: 10px 10px 12px;
            display: flex;
            flex-direction: column;
            min-height: 0;
          }
          .ws-group-title {
            font-size: 12px; font-weight: 700; letter-spacing: .04em;
            text-transform: uppercase; color: #64748b; margin: 0 0 8px;
          }
          .ws-grid-2 {
            display: grid;
            grid-template-columns: 1fr 1fr;
            gap: 8px;
            flex: 1;
          }
          .ws-card {
            padding: 10px 12px !important;
            box-shadow: none !important;
            border: 1px solid #e2e8f0 !important;
            border-radius: 8px !important;
            background: #f8fafc !important;
            margin: 0 !important;
          }
          .ws-card-title { font-size: 12px; color: #64748b; line-height: 1.25; margin: 0; }
          .ws-card-value {
            font-size: 1.45rem; font-weight: 650; color: #0f172a;
            line-height: 1.2; margin: 6px 0 0; word-break: break-word;
          }
          .ws-chart-panel {
            border: 1px solid #e2e8f0;
            border-radius: 12px;
            background: #fff;
            padding: 12px 12px 8px;
            display: flex;
            flex-direction: column;
            min-height: 0;
          }
          .ws-status-ok { color: #15803d; }
          .ws-status-err { color: #b91c1c; }
        </style>
        """
    )

    with ui.column().classes("ws-wrap w-full gap-0"):
        with ui.row().classes("w-full items-center justify-between"):
            with ui.column().classes("gap-0"):
                ui.label(settings.label).classes("text-h5 text-weight-bold")
                ui.label("weather_server · Ecowitt live").classes("text-caption text-grey-7")
            status_badge = ui.label("…").classes("text-subtitle2")

        meta_line = ui.label("").classes("text-caption text-grey-7 q-mb-sm")

        with ui.element("div").classes("ws-main"):
            # —— Messwerte: 2×2 Gruppen → effektiv 4 Spalten ——
            with ui.element("div").classes("ws-groups"):
                with ui.element("div").classes("ws-group"):
                    ui.label("Außen").classes("ws-group-title")
                    with ui.element("div").classes("ws-grid-2"):
                        temp_l = _metric("Temperatur", unit="°C")
                        hum_l = _metric("Feuchte", unit="%")
                        dew_l = _metric("Taupunkt", unit="°C")
                        margin_l = _metric("Tau-Abstand", unit="K", hint="T − Dew")

                with ui.element("div").classes("ws-group"):
                    ui.label("Wind").classes("ws-group-title")
                    with ui.element("div").classes("ws-grid-2"):
                        wind_l = _metric("Wind", unit="m/s")
                        gust_l = _metric("Böe", unit="m/s")
                        wind_dir_l = _metric("Richtung", unit="°")
                        press_l = _metric("Luftdruck", unit="hPa", hint="rel.")

                with ui.element("div").classes("ws-group"):
                    ui.label("Niederschlag & Sonne").classes("ws-group-title")
                    with ui.element("div").classes("ws-grid-2"):
                        rain_l = _metric("Regen heute", unit="mm")
                        rain_rate_l = _metric("Regenrate", unit="mm/h")
                        solar_l = _metric("Solar", unit="W/m²")
                        uvi_l = _metric("UV-Index")

                with ui.element("div").classes("ws-group"):
                    ui.label("Gateway innen").classes("ws-group-title")
                    with ui.element("div").classes("ws-grid-2"):
                        indoor_t_l = _metric("Temperatur", unit="°C")
                        indoor_h_l = _metric("Feuchte", unit="%")

            # —— Chart + Steuerung ——
            with ui.element("div").classes("ws-chart-panel"):
                ui.label("Verlauf").classes("text-subtitle1 text-weight-medium")
                with ui.row().classes("w-full items-center flex-wrap gap-3 q-mb-xs"):
                    ui.label("Samples").classes("text-caption text-grey-7")
                    samples_select = ui.select(
                        options=_SAMPLE_CHOICES,
                        value=int(prefs["ws_chart_samples"]),
                    ).props("dense options-dense").classes("w-28")
                    samples_select.bind_value(prefs, "ws_chart_samples")

                ui.label("Größen").classes("text-caption text-grey-7 q-mt-xs")
                series_boxes: dict[str, ui.checkbox] = {}
                with ui.row().classes("w-full flex-wrap gap-x-3 gap-y-1 q-mb-sm"):
                    for key, (label, unit, _color) in _SERIES.items():
                        text = f"{label} ({unit})" if unit else label
                        pref_key = _series_pref_key(key)
                        box = ui.checkbox(text, value=bool(prefs.get(pref_key, False)))
                        box.bind_value(prefs, pref_key)
                        series_boxes[key] = box

                chart = ui.echart(
                    {
                        "tooltip": {"trigger": "axis"},
                        "legend": {"type": "scroll", "top": 0},
                        "grid": {"left": 52, "right": 20, "top": 36, "bottom": 40},
                        "xAxis": {"type": "category", "data": [], "axisLabel": {"rotate": 40}},
                        "yAxis": {"type": "value", "scale": True},
                        "series": [],
                    }
                ).classes("w-full").style("flex:1; min-height:280px; height:100%")

        show_table = ui.checkbox("Sample-Tabelle anzeigen").bind_value(prefs, "ws_show_table")
        table_box = ui.column().classes("w-full q-mt-sm")
        with table_box:
            ui.label("Letzte Samples").classes("text-subtitle1 text-weight-medium q-mb-xs")
            columns = [
                {"name": "when", "label": "Zeit", "field": "when", "align": "left"},
                {"name": "temp_c", "label": "T °C", "field": "temp_c"},
                {"name": "humidity_pct", "label": "RH %", "field": "humidity_pct"},
                {"name": "dewpoint_c", "label": "Dew °C", "field": "dewpoint_c"},
                {"name": "dewpoint_margin_c", "label": "ΔK", "field": "dewpoint_margin_c"},
                {"name": "wind_ms", "label": "Wind", "field": "wind_ms"},
                {"name": "pressure_hpa", "label": "hPa", "field": "pressure_hpa"},
                {"name": "solarradiation_wm2", "label": "W/m²", "field": "solarradiation_wm2"},
            ]
            table = ui.table(columns=columns, rows=[], row_key="id").classes("w-full").props(
                "flat dense wrap-cells"
            )

        error_line = ui.label("").classes("text-caption q-mt-sm")

    def _active_series() -> list[str]:
        return [key for key in _SERIES if prefs.get(_series_pref_key(key))]

    def _sample_limit() -> int:
        try:
            value = int(prefs.get("ws_chart_samples") or _DEFAULT_SAMPLES)
        except (TypeError, ValueError):
            value = _DEFAULT_SAMPLES
        return value if value in _SAMPLE_CHOICES else _DEFAULT_SAMPLES

    def _sync_table_visibility() -> None:
        table_box.set_visibility(bool(prefs.get("ws_show_table", True)))

    def refresh() -> None:
        sample = store.latest()
        status = collector.status.as_dict()
        count = store.sample_count()

        if status.get("last_error") and not status.get("last_ok_at"):
            status_badge.text = "Fehler"
            status_badge.classes(replace="text-subtitle2 ws-status-err")
        elif status.get("running"):
            status_badge.text = "läuft"
            status_badge.classes(replace="text-subtitle2 ws-status-ok")
        else:
            status_badge.text = "gestoppt"
            status_badge.classes(replace="text-subtitle2 text-grey-7")

        meta_line.text = (
            f"Gateway {settings.gateway_base_url} · Poll {settings.poll_interval_s:.0f}s · "
            f"Samples {count} · zuletzt {_fmt_when(status.get('last_ok_at') or (sample or {}).get('recorded_at'))}"
        )

        if sample:
            temp_l.text = _fmt(sample.get("temp_c"), digits=1)
            hum_l.text = _fmt(sample.get("humidity_pct"), digits=0)
            dew_l.text = _fmt(sample.get("dewpoint_c"), digits=1)
            margin_l.text = _fmt(sample.get("dewpoint_margin_c"), digits=1)
            wind_l.text = _fmt(sample.get("wind_ms"), digits=1)
            gust_l.text = _fmt(sample.get("gust_ms"), digits=1)
            wind_dir_l.text = _fmt(sample.get("wind_dir_deg"), digits=0)
            press_l.text = _fmt(sample.get("pressure_hpa"), digits=1)
            rain_l.text = _fmt(sample.get("rain_mm"), digits=1)
            rain_rate_l.text = _fmt(sample.get("rain_rate_mm_h"), digits=1)
            solar_l.text = _fmt(sample.get("solarradiation_wm2"), digits=0)
            uvi_l.text = _fmt(sample.get("uvi"), digits=0)
            indoor_t_l.text = _fmt(sample.get("indoor_temp_c"), digits=1)
            indoor_h_l.text = _fmt(sample.get("indoor_humidity_pct"), digits=0)

        limit = _sample_limit()
        history = list(reversed(store.history(limit=limit)))
        times: list[str] = []
        rows: list[dict[str, Any]] = []
        for item in history:
            stamp = item.get("recorded_at") or item.get("when") or ""
            try:
                label = datetime.fromisoformat(str(stamp).replace("Z", "+00:00")).astimezone().strftime(
                    "%H:%M:%S"
                )
            except ValueError:
                label = str(stamp)[-8:]
            times.append(label)
            rows.append(
                {
                    "id": item.get("id"),
                    "when": _fmt_when(stamp),
                    "temp_c": _fmt(item.get("temp_c")),
                    "humidity_pct": _fmt(item.get("humidity_pct"), digits=0),
                    "dewpoint_c": _fmt(item.get("dewpoint_c")),
                    "dewpoint_margin_c": _fmt(item.get("dewpoint_margin_c")),
                    "wind_ms": _fmt(item.get("wind_ms")),
                    "pressure_hpa": _fmt(item.get("pressure_hpa")),
                    "solarradiation_wm2": _fmt(item.get("solarradiation_wm2"), digits=0),
                }
            )

        active = _active_series()
        series_opts: list[dict[str, Any]] = []
        legend: list[str] = []
        for key in active:
            label, unit, color = _SERIES[key]
            name = f"{label} {unit}".strip()
            legend.append(name)
            series_opts.append(
                {
                    "name": name,
                    "type": "line",
                    "showSymbol": False,
                    "data": [item.get(key) for item in history],
                    "itemStyle": {"color": color},
                    "lineStyle": {"color": color, "width": 2},
                }
            )

        chart.options["legend"]["data"] = legend
        chart.options["xAxis"]["data"] = times
        chart.options["series"] = series_opts
        chart.update()

        table.rows = list(reversed(rows))[:40]
        _sync_table_visibility()

        err = status.get("last_error")
        if err:
            error_line.text = f"Letzter Poll-Fehler: {err}"
            error_line.classes(replace="text-caption q-mt-sm ws-status-err")
        else:
            error_line.text = ""
            error_line.classes(replace="text-caption q-mt-sm")

    def _on_pref_change(_: Any = None) -> None:
        refresh()

    samples_select.on_value_change(_on_pref_change)
    show_table.on_value_change(_on_pref_change)
    for box in series_boxes.values():
        box.on_value_change(_on_pref_change)

    refresh()
    ui.timer(_REFRESH_S, refresh)
