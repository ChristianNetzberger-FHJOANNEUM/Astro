"""Background poller: GW1200 livedata → SQLite."""

from __future__ import annotations

import logging
import threading
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any

from weather_server.config import WeatherServerSettings
from weather_server.ecowitt.client import fetch_livedata
from weather_server.ecowitt.parse import parse_livedata
from weather_server.storage.db import WeatherStore

logger = logging.getLogger("weather_server.collector")


@dataclass
class CollectorStatus:
    running: bool = False
    last_ok_at: str | None = None
    last_error_at: str | None = None
    last_error: str | None = None
    last_sample_id: int | None = None
    poll_count: int = 0
    ok_count: int = 0
    error_count: int = 0
    gateway_base_url: str = ""
    poll_interval_s: float = 30.0
    extra: dict[str, Any] = field(default_factory=dict)

    def as_dict(self) -> dict[str, Any]:
        return {
            "running": self.running,
            "last_ok_at": self.last_ok_at,
            "last_error_at": self.last_error_at,
            "last_error": self.last_error,
            "last_sample_id": self.last_sample_id,
            "poll_count": self.poll_count,
            "ok_count": self.ok_count,
            "error_count": self.error_count,
            "gateway_base_url": self.gateway_base_url,
            "poll_interval_s": self.poll_interval_s,
            **self.extra,
        }


class WeatherCollector:
    """Daemon thread: poll gateway every N seconds; errors do not stop the loop."""

    def __init__(self, settings: WeatherServerSettings, store: WeatherStore) -> None:
        self.settings = settings
        self.store = store
        self.status = CollectorStatus(
            gateway_base_url=settings.gateway_base_url,
            poll_interval_s=settings.poll_interval_s,
        )
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None

    def start(self) -> None:
        if self._thread and self._thread.is_alive():
            return
        self._stop.clear()
        self.status.running = True
        self._thread = threading.Thread(
            target=self._run,
            name="weather-collector",
            daemon=True,
        )
        self._thread.start()
        logger.info(
            "Collector started → %s every %.0fs",
            self.settings.gateway_base_url,
            self.settings.poll_interval_s,
        )

    def stop(self, *, timeout_s: float = 5.0) -> None:
        self._stop.set()
        self.status.running = False
        thread = self._thread
        if thread and thread.is_alive():
            thread.join(timeout=timeout_s)
        logger.info("Collector stopped")

    def poll_once(self) -> dict[str, Any]:
        """Fetch + parse + store one sample. Raises on failure."""
        raw = fetch_livedata(
            self.settings.gateway_base_url,
            path=self.settings.livedata_path,
            timeout_s=self.settings.request_timeout_s,
        )
        observation = parse_livedata(raw)
        sample = self.store.insert_sample(observation, label=self.settings.label)
        now = datetime.now(timezone.utc).isoformat()
        self.status.last_ok_at = now
        self.status.last_error = None
        self.status.last_sample_id = int(sample["id"])
        self.status.ok_count += 1
        return sample

    def _run(self) -> None:
        # Immediate first poll, then sleep between attempts.
        while not self._stop.is_set():
            self.status.poll_count += 1
            try:
                sample = self.poll_once()
                logger.info(
                    "sample #%s temp=%s humidity=%s dew_margin=%s",
                    sample.get("id"),
                    sample.get("temp_c"),
                    sample.get("humidity_pct"),
                    sample.get("dewpoint_margin_c"),
                )
            except Exception as exc:  # noqa: BLE001 — keep loop alive
                self.status.error_count += 1
                self.status.last_error_at = datetime.now(timezone.utc).isoformat()
                self.status.last_error = str(exc)
                logger.warning("poll failed: %s", exc)

            self._stop.wait(self.settings.poll_interval_s)

        self.status.running = False
