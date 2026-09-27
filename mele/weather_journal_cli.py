"""Einmal GeoSphere-Forecast holen und ins Wetter-Journal schreiben.

Aufruf (Task Scheduler, stündlich):
  powershell -ExecutionPolicy Bypass -File scripts\\weather-journal.ps1

Oder:
  .venv\\Scripts\\python.exe -m mele weather-journal
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parent.parent
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

from mele.config import load_mele_settings
from mele.weather import WeatherError, load_forecast, weather_dir_for
from mele.weather_journal import (
    SOURCE_GEOSPHERE,
    append_forecast,
    should_skip_forecast,
)


def run_weather_journal(
    *,
    latitude_deg: float | None = None,
    longitude_deg: float | None = None,
    force: bool = False,
    label: str = "",
) -> int:
    settings = load_mele_settings()
    if not settings.weather_journal_enabled and not force:
        print("weather_journal_enabled=false — Abbruch (mit --force erzwingen).")
        return 0
    lat = latitude_deg if latitude_deg is not None else settings.latitude_deg
    lon = longitude_deg if longitude_deg is not None else settings.longitude_deg
    if lat is None or lon is None:
        print("latitude_deg/longitude_deg in configs/mele.yaml setzen oder --lat/--lon.", file=sys.stderr)
        return 2
    weather_dir = weather_dir_for(settings.horizon_dir)
    weather_dir.mkdir(parents=True, exist_ok=True)
    interval = float(settings.weather_journal_interval_h or 1.0)
    if not force and should_skip_forecast(
        weather_dir,
        latitude_deg=float(lat),
        longitude_deg=float(lon),
        interval_h=interval,
        source=SOURCE_GEOSPHERE,
    ):
        print(f"Skip: letzter Forecast juenger als {interval} h.")
        return 0
    try:
        forecast = load_forecast(
            float(lat),
            float(lon),
            weather_dir,
            refresh=True,
            network=True,
        )
    except WeatherError as exc:
        print(f"Forecast fehlgeschlagen: {exc}", file=sys.stderr)
        return 1
    record = append_forecast(
        weather_dir,
        forecast,
        latitude_deg=float(lat),
        longitude_deg=float(lon),
        label=label or settings.local_weather_label,
        source=SOURCE_GEOSPHERE,
    )
    hours = (record.get("forecast") or {}).get("hour_count")
    print(f"Journal: {record.get('path')}")
    print(f"Source:  {SOURCE_GEOSPHERE}  hours={hours}  offline={forecast.get('offline')}")
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="GeoSphere-Forecast ins Wetter-Journal schreiben")
    parser.add_argument("--lat", type=float, default=None)
    parser.add_argument("--lon", type=float, default=None)
    parser.add_argument("--force", action="store_true", help="Intervall-Skip ignorieren")
    parser.add_argument("--label", default="", help="Standort-Label im Journal")
    args = parser.parse_args(argv)
    return run_weather_journal(
        latitude_deg=args.lat,
        longitude_deg=args.lon,
        force=args.force,
        label=args.label,
    )


if __name__ == "__main__":
    raise SystemExit(main())
