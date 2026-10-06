"""CLI: python -m weather_server"""

from __future__ import annotations

import argparse
import json
import logging
import sys
from dataclasses import replace
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parent.parent
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Astro weather_server (Ecowitt Pull → SQLite → REST + Dashboard)"
    )
    parser.add_argument(
        "--config",
        type=Path,
        default=None,
        help="Pfad zu configs/weather_server.yaml",
    )
    parser.add_argument("--host", default=None, help="API/UI bind host (override)")
    parser.add_argument("--port", type=int, default=None, help="API/UI bind port (override)")
    parser.add_argument(
        "--once",
        action="store_true",
        help="Einmal poll + print JSON, dann exit (ohne API/UI)",
    )
    parser.add_argument(
        "--api-only",
        action="store_true",
        help="Nur FastAPI/REST ohne NiceGUI-Dashboard",
    )
    parser.add_argument(
        "--no-browser",
        action="store_true",
        help="Browser nicht automatisch oeffnen",
    )
    parser.add_argument("-v", "--verbose", action="store_true")
    args = parser.parse_args(argv)

    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )

    from weather_server.collector import WeatherCollector
    from weather_server.config import load_settings
    from weather_server.storage.db import WeatherStore

    settings = load_settings(args.config)
    if args.host:
        settings = replace(settings, api_host=args.host)
    if args.port is not None:
        settings = replace(settings, api_port=args.port)
    if args.no_browser:
        settings = replace(settings, open_browser=False)

    store = WeatherStore(settings.db_path)
    collector = WeatherCollector(settings, store)

    if args.once:
        try:
            sample = collector.poll_once()
        except Exception as exc:  # noqa: BLE001
            print(f"poll failed: {exc}", file=sys.stderr)
            store.close()
            return 1
        print(json.dumps(sample, indent=2, ensure_ascii=False))
        store.close()
        return 0

    if args.api_only:
        import uvicorn

        from weather_server.api.app import create_app

        app = create_app(settings, store=store, collector=collector, start_collector=True)
        uvicorn.run(app, host=settings.api_host, port=settings.api_port, log_level="info")
        return 0

    from nicegui import app, ui

    from weather_server.api.routes import register_api
    from weather_server.ui.dashboard import build_dashboard

    register_api(app, settings=settings, store=store, collector=collector)

    @app.on_startup
    def _start_collector() -> None:
        collector.start()

    @app.on_shutdown
    def _stop_collector() -> None:
        collector.stop()
        store.close()

    @ui.page("/")
    def index() -> None:
        build_dashboard(settings, store, collector)

    ui.run(
        title=f"Weather · {settings.label}",
        host=settings.api_host,
        port=settings.api_port,
        show=settings.open_browser,
        reload=False,
        favicon="⛅",
        # nötig für app.storage.user (Chart-/UI-Prefs sessionpersistent)
        storage_secret="astro-weather-server-ui",
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
