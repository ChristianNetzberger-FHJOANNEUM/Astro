"""Register REST routes on a FastAPI / NiceGUI app."""

from __future__ import annotations

from typing import Any

from fastapi import Query, Request
from fastapi.responses import JSONResponse

from weather_server.collector import WeatherCollector
from weather_server.config import WeatherServerSettings
from weather_server.storage.db import WeatherStore


def register_api(
    app: Any,
    *,
    settings: WeatherServerSettings,
    store: WeatherStore,
    collector: WeatherCollector,
) -> None:
    """Attach /api/* and /healthz to ``app`` (FastAPI or NiceGUI app)."""
    app.state.settings = settings
    app.state.store = store
    app.state.collector = collector

    @app.get("/api/current")
    def api_current(request: Request) -> JSONResponse:
        sample = request.app.state.store.latest()
        if sample is None:
            return JSONResponse({"ok": False, "error": "no samples yet"}, status_code=404)
        return JSONResponse({"ok": True, "sample": sample})

    @app.get("/api/history")
    def api_history(
        request: Request,
        limit: int = Query(100, ge=1, le=5000),
        since: str | None = Query(None, description="ISO timestamp lower bound on recorded_at"),
    ) -> dict[str, Any]:
        samples = request.app.state.store.history(limit=limit, since=since)
        return {"ok": True, "count": len(samples), "samples": samples}

    @app.get("/api/status")
    def api_status(request: Request) -> dict[str, Any]:
        weather_store: WeatherStore = request.app.state.store
        weather_collector: WeatherCollector = request.app.state.collector
        cfg: WeatherServerSettings = request.app.state.settings
        status = weather_collector.status.as_dict()
        status.update(
            {
                "ok": True,
                "label": cfg.label,
                "db_path": str(cfg.db_path),
                "sample_count": weather_store.sample_count(),
                "api_host": cfg.api_host,
                "api_port": cfg.api_port,
            }
        )
        return status

    @app.get("/healthz")
    def healthz() -> dict[str, str]:
        return {"status": "ok"}
