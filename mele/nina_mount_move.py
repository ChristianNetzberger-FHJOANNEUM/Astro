"""NINA Advanced API — Mount MoveAxis via WebSocket (manuelles Joggen).

Kanal: ws://{host}:{port}/v2/mount
Nachricht: {"direction":"east|west|north|south","rate": <deg/s>}
NINA stoppt automatisch bei Client-Disconnect / fehlenden Keepalive-Messages (~2s).
"""

from __future__ import annotations

import json
import logging
import threading
import time
from dataclasses import asdict, dataclass
from typing import Any
from urllib.parse import urlparse

logger = logging.getLogger(__name__)

# Advanced API v2: MoveAxis-Kanal ist /v2/mount (nicht /v2/api/…).
# Verifiziert gegen laufende NINA: WS connect + {"direction","rate"} → Moving.
DEFAULT_WS_PATH = "/v2/mount"
VALID_DIRECTIONS = frozenset({"east", "west", "north", "south"})


@dataclass
class MountMoveResult:
    ok: bool
    message: str = ""
    error: str = ""
    direction: str = ""
    rate: float = 0.0

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def ws_url_from_api_base(nina_base_url: str, *, path: str = DEFAULT_WS_PATH) -> str:
    """http://host:1888/v2/api → ws://host:1888/v2/mount"""
    parsed = urlparse((nina_base_url or "").strip())
    host = parsed.hostname or "127.0.0.1"
    port = parsed.port or 1888
    scheme = "wss" if parsed.scheme == "https" else "ws"
    return f"{scheme}://{host}:{port}{path}"


class NinaMountMover:
    """Hält eine MoveAxis-WebSocket-Verbindung und sendet Keepalive-Richtungsbefehle."""

    def __init__(self, nina_base_url: str) -> None:
        self.ws_url = ws_url_from_api_base(nina_base_url)
        self._lock = threading.RLock()
        self._ws = None
        self._thread: threading.Thread | None = None
        self._stop = threading.Event()
        self._direction = ""
        self._rate = 0.0
        self._last_cmd_mono = 0.0
        self._last_error = ""
        self._idle_stop_s = 1.5

    def status(self) -> dict[str, Any]:
        with self._lock:
            return {
                "ws_url": self.ws_url,
                "active": bool(self._direction) and self._rate != 0,
                "direction": self._direction,
                "rate": self._rate,
                "error": self._last_error,
            }

    def move(self, direction: str, rate: float) -> MountMoveResult:
        direction = str(direction or "").strip().lower()
        if direction not in VALID_DIRECTIONS:
            return MountMoveResult(ok=False, error=f"invalid direction: {direction}")
        try:
            rate_f = float(rate)
        except (TypeError, ValueError):
            return MountMoveResult(ok=False, error="invalid rate")
        if rate_f == 0:
            return self.stop()
        with self._lock:
            self._direction = direction
            self._rate = abs(rate_f)
            self._last_cmd_mono = time.monotonic()
            self._last_error = ""
        self._ensure_loop()
        ok = self._send(direction, abs(rate_f))
        if not ok:
            return MountMoveResult(
                ok=False,
                error=self._last_error or "MoveAxis WebSocket fehlgeschlagen",
                direction=direction,
                rate=abs(rate_f),
            )
        return MountMoveResult(
            ok=True,
            message="Moving",
            direction=direction,
            rate=abs(rate_f),
        )

    def stop(self) -> MountMoveResult:
        with self._lock:
            direction = self._direction or "east"
            self._direction = ""
            self._rate = 0.0
            self._last_cmd_mono = time.monotonic()
        # Alle Achsen auf 0 tippen (NINA erwartet Richtung + rate 0)
        for d in ("east", "west", "north", "south"):
            self._send(d, 0.0)
        return MountMoveResult(ok=True, message="Stopped", direction=direction, rate=0.0)

    def _ensure_loop(self) -> None:
        with self._lock:
            if self._thread and self._thread.is_alive():
                return
            self._stop.clear()
            self._thread = threading.Thread(
                target=self._keepalive_loop,
                name="nina-mount-move",
                daemon=True,
            )
            self._thread.start()

    def _keepalive_loop(self) -> None:
        while not self._stop.is_set():
            with self._lock:
                direction = self._direction
                rate = self._rate
                last = self._last_cmd_mono
            if direction and rate:
                # Client muss periodisch senden — NINA Failsafe ~2s
                if time.monotonic() - last > self._idle_stop_s:
                    self.stop()
                else:
                    self._send(direction, rate)
            time.sleep(0.4)

    def _send(self, direction: str, rate: float) -> bool:
        try:
            import websockets.sync.client as ws_sync
        except Exception as exc:  # noqa: BLE001
            self._last_error = f"websockets missing: {exc}"
            return False
        payload = json.dumps({"direction": direction, "rate": float(rate)})
        try:
            with self._lock:
                ws = self._ws
            if ws is None:
                logger.info("NINA MoveAxis connect %s", self.ws_url)
                ws = ws_sync.connect(self.ws_url, open_timeout=2, close_timeout=1)
                with self._lock:
                    self._ws = ws
            ws.send(payload)
            logger.info("NINA MoveAxis sent %s", payload)
            return True
        except Exception as exc:  # noqa: BLE001
            logger.warning("NINA MoveAxis send failed: %s", exc)
            self._last_error = str(exc)
            with self._lock:
                old = self._ws
                self._ws = None
            if old is not None:
                try:
                    old.close()
                except Exception:  # noqa: BLE001
                    pass
            # einmal neu versuchen
            try:
                ws = ws_sync.connect(self.ws_url, open_timeout=2, close_timeout=1)
                ws.send(payload)
                with self._lock:
                    self._ws = ws
                    self._last_error = ""
                return True
            except Exception as exc2:  # noqa: BLE001
                self._last_error = str(exc2)
                return False


_MOVER: NinaMountMover | None = None
_MOVER_LOCK = threading.Lock()


def get_mount_mover(nina_base_url: str) -> NinaMountMover:
    global _MOVER
    with _MOVER_LOCK:
        if _MOVER is None or _MOVER.ws_url != ws_url_from_api_base(nina_base_url):
            _MOVER = NinaMountMover(nina_base_url)
        return _MOVER
