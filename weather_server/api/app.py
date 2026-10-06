"""REST API factory (API-only / tests). Dashboard uses NiceGUI + register_api."""

from __future__ import annotations

from contextlib import asynccontextmanager

from fastapi import FastAPI

from weather_server.api.routes import register_api
from weather_server.collector import WeatherCollector
from weather_server.config import WeatherServerSettings, load_settings
from weather_server.storage.db import WeatherStore


def create_app(
    settings: WeatherServerSettings | None = None,
    *,
    store: WeatherStore | None = None,
    collector: WeatherCollector | None = None,
    start_collector: bool = True,
) -> FastAPI:
    cfg = settings or load_settings()
    weather_store = store or WeatherStore(cfg.db_path)
    weather_collector = collector or WeatherCollector(cfg, weather_store)

    @asynccontextmanager
    async def lifespan(_app: FastAPI):
        if start_collector:
            weather_collector.start()
        try:
            yield
        finally:
            if start_collector:
                weather_collector.stop()
            weather_store.close()

    app = FastAPI(title="Astro weather_server", version="0.1.0", lifespan=lifespan)
    register_api(app, settings=cfg, store=weather_store, collector=weather_collector)
    return app
