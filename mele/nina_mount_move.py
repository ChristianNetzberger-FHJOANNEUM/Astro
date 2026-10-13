"""NINA Advanced API — Mount MoveAxis via WebSocket (manuelles Joggen).

Kanal: ws://{host}:{port}/v2/mount
Nachricht: {"direction":"east|west|north|south","rate": <deg/s>}

Der MeLE wiederholt die Richtung alle 0,4 s und sendet nach 1,5 s ohne neuen
Impuls selbst Rate 0. Seit Advanced API 2.2.0.0 beendet das Schließen der
WebSocket die Achse nicht. Der Stopp ist die erfolgreich übertragene Rate 0.

Ein Quest-Impuls trägt eine Aktivierungsnummer. Stopp und Totmann setzen
diese Nummer außer Kraft. Ein späterer Impuls derselben Aktivierung setzt
keine Richtung mehr. Ein Desktop-Impuls ohne Nummer bleibt der bisherige Weg.
"""

from __future__ import annotations

import json
import logging
import threading
import time
from dataclasses import asdict, dataclass
from typing import Any, Callable
from urllib.parse import urlparse

logger = logging.getLogger(__name__)

# Advanced API v2: MoveAxis-Kanal ist /v2/mount (nicht /v2/api/…).
# Verifiziert gegen laufende NINA: WS connect + {"direction","rate"} → Moving.
DEFAULT_WS_PATH = "/v2/mount"
VALID_DIRECTIONS = frozenset({"east", "west", "north", "south"})
IDLE_STOP_S = 1.5
KEEPALIVE_S = 0.4
QUEST_AXIS_RATE = 0.01
QUEST_AXIS_RATES = (0.005, 0.01, 0.02, 0.05, 0.1, 0.5)


@dataclass
class MountMoveResult:
    ok: bool
    message: str = ""
    error: str = ""
    direction: str = ""
    rate: float = 0.0
    rate0_sent: bool = False

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def quest_axis_rate(raw: Any) -> tuple[float | None, str]:
    """Quest darf nur die langsamen Pad-Stufen senden, nicht eine freie Zahl."""
    try:
        value = float(raw)
    except (TypeError, ValueError):
        return None, "Geschwindigkeit ungültig"
    for allowed in QUEST_AXIS_RATES:
        if abs(value - allowed) <= 1e-9:
            return allowed, ""
    return None, "Geschwindigkeit nicht freigegeben"


def parse_pulse_token(raw: Any) -> tuple[int | None, str]:
    """Leer heißt Desktop. Eine Quest-Aktivierung ist eine positive Ganzzahl."""
    if raw is None or raw == "":
        return None, ""
    try:
        value = int(raw)
    except (TypeError, ValueError):
        return None, "Steuerimpuls ungültig"
    if value <= 0:
        return None, "Steuerimpuls ungültig"
    return value, ""


def ws_url_from_api_base(nina_base_url: str, *, path: str = DEFAULT_WS_PATH) -> str:
    """http://host:1888/v2/api → ws://host:1888/v2/mount"""
    parsed = urlparse((nina_base_url or "").strip())
    host = parsed.hostname or "127.0.0.1"
    port = parsed.port or 1888
    scheme = "wss" if parsed.scheme == "https" else "ws"
    return f"{scheme}://{host}:{port}{path}"


class NinaMountMover:
    """Hält eine MoveAxis-WebSocket-Verbindung und sendet Keepalive-Richtungsbefehle.

    Der Totmann läuft im eigenen Thread. Er hängt nicht am HTTP-Aufruf.
    Rate 0 gilt nur als gesendet, wenn der Transport True liefert.
    """

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
        self._halt_pending = False
        self._next_halt_mono = 0.0
        self._live_token = 0
        self._retired_token = 0
        self._block_probe = lambda: ""
        self._on_halt = None
        self._transport = None

    def set_guard(
        self,
        *,
        block_probe: Callable[[], str] | None = None,
        on_halt: Callable[[MountMoveResult], None] | None = None,
        transport: Callable[[str, float], bool] | None = None,
    ) -> None:
        """``transport`` ersetzt den WebSocket nur in Tests."""
        if block_probe is not None:
            self._block_probe = block_probe
        if on_halt is not None:
            self._on_halt = on_halt
        if transport is not None:
            self._transport = transport

    def status(self) -> dict[str, Any]:
        with self._lock:
            return {
                "ws_url": self.ws_url,
                "active": bool(self._direction) and self._rate != 0,
                "direction": self._direction,
                "rate": self._rate,
                "error": self._last_error,
                "halt_pending": self._halt_pending,
                "live_token": self._live_token,
                "retired_token": self._retired_token,
            }

    def _token_blocked(self, token: int | None) -> bool:
        if token is None:
            return False
        value = int(token)
        if value <= self._retired_token:
            return True
        return bool(self._live_token) and value < self._live_token

    def pulse_rejected(self, token: int | None) -> str:
        if token is None:
            return ""
        with self._lock:
            if self._token_blocked(token):
                return "Steuerimpuls überholt"
        return ""

    def retire_pulse(self, token: int | None = None) -> None:
        """Macht eine Aktivierung ungültig, ohne selbst Rate 0 zu senden."""
        with self._lock:
            mark = self._live_token
            if token is not None:
                mark = max(mark, int(token))
            self._retired_token = max(self._retired_token, mark)

    def move(self, direction: str, rate: float, token: int | None = None, *, now: float | None = None) -> MountMoveResult:
        direction = str(direction or "").strip().lower()
        if direction not in VALID_DIRECTIONS:
            return MountMoveResult(ok=False, error=f"invalid direction: {direction}")
        try:
            rate_f = float(rate)
        except (TypeError, ValueError):
            return MountMoveResult(ok=False, error="invalid rate")
        if token is not None:
            try:
                token = int(token)
            except (TypeError, ValueError):
                return MountMoveResult(ok=False, error="Steuerimpuls ungültig")
        if rate_f == 0:
            return self.stop(token=token, now=now)
        rejected = self.pulse_rejected(token)
        if rejected:
            return MountMoveResult(ok=False, error=rejected, direction=direction)
        reason = self._probe()
        with self._lock:
            if self._token_blocked(token):
                blocked = "Steuerimpuls überholt"
            elif reason or self._halt_pending:
                blocked = reason or self._last_error or "Rate 0 nicht gesendet"
            else:
                blocked = ""
                if token is not None:
                    self._live_token = token
                self._direction = direction
                self._rate = abs(rate_f)
                self._last_cmd_mono = time.monotonic() if now is None else now
                self._last_error = ""
        if blocked:
            if reason and blocked != "Steuerimpuls überholt" and self._moving():
                halted = self.stop(now=now)
                halted.ok = False
                halted.error = reason
                return halted
            return MountMoveResult(ok=False, error=blocked, direction=direction, rate=abs(rate_f))
        reason = self._probe()
        if reason:
            halted = self.stop(now=now)
            halted.ok = False
            halted.error = reason
            return halted
        self._ensure_loop()
        ok = self._deliver(direction, abs(rate_f))
        with self._lock:
            still = self._direction == direction and self._rate == abs(rate_f)
            pending = self._halt_pending
            stale = self._token_blocked(token)
        if stale:
            if still:
                halted = self.stop(token=token, now=now)
                halted.ok = False
                halted.error = "Steuerimpuls überholt"
                return halted
            return MountMoveResult(
                ok=False,
                error="Steuerimpuls überholt",
                direction=direction,
                rate=abs(rate_f),
                rate0_sent=not pending,
            )
        if not ok:
            if still:
                with self._lock:
                    self._direction = ""
                    self._rate = 0.0
            return MountMoveResult(
                ok=False,
                error=self._last_error or "MoveAxis WebSocket fehlgeschlagen",
                direction=direction,
                rate=abs(rate_f),
                rate0_sent=not pending and not still,
            )
        if not still:
            return MountMoveResult(
                ok=False,
                error=self._last_error or "Achsbewegung gestoppt",
                direction=direction,
                rate=abs(rate_f),
                rate0_sent=not pending,
            )
        reason = self._probe()
        if reason:
            halted = self.stop(now=now)
            halted.ok = False
            halted.error = reason
            return halted
        return MountMoveResult(ok=True, message="Moving", direction=direction, rate=abs(rate_f))

    def stop(self, token: int | None = None, *, now: float | None = None) -> MountMoveResult:
        stamp = time.monotonic() if now is None else now
        with self._lock:
            if token is not None:
                token = int(token)
                if token < self._live_token:
                    self._retired_token = max(self._retired_token, token)
                    return MountMoveResult(ok=True, message="älterer Achsen-Stopp verworfen", rate0_sent=False)
            mark = self._live_token
            if token is not None:
                mark = max(mark, token)
            self._retired_token = max(self._retired_token, mark)
            direction = self._direction or "east"
            self._direction = ""
            self._rate = 0.0
            self._halt_pending = True
        sent = self._transmit_rate0()
        with self._lock:
            if sent:
                self._halt_pending = False
                self._last_error = ""
            else:
                self._halt_pending = True
                self._last_error = self._last_error or "Rate 0 nicht gesendet"
                self._next_halt_mono = stamp + KEEPALIVE_S
            error = "" if sent else self._last_error
        result = MountMoveResult(
            ok=sent,
            message="Rate 0 gesendet, Stillstand offen" if sent else "",
            error=error,
            direction=direction,
            rate=0.0,
            rate0_sent=sent,
        )
        if self._on_halt is not None:
            self._on_halt(result)
        return result

    def tick(self, now: float | None = None) -> None:
        """Ein Totmann-Schritt. Blockiert nicht auf einem laufenden HTTP-Versand."""
        stamp = time.monotonic() if now is None else now
        with self._lock:
            direction = self._direction
            rate = self._rate
            last = self._last_cmd_mono
            pending = self._halt_pending
            next_try = self._next_halt_mono
            moving = bool(direction) and rate != 0
        if moving and (self._probe() or stamp - last > IDLE_STOP_S):
            self.stop(now=stamp)
            return
        if pending:
            if stamp < next_try:
                return
            self.stop(now=stamp)
            return
        if moving:
            self._deliver(direction, rate)

    def _moving(self) -> bool:
        with self._lock:
            return bool(self._direction) and self._rate != 0

    def _probe(self) -> str:
        try:
            return str(self._block_probe() or "")
        except Exception:
            return "PHD2-Zustand nicht lesbar"

    def _ensure_loop(self) -> None:
        if self._transport is not None:
            return
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
            self.tick()
            self._stop.wait(KEEPALIVE_S)

    def _deliver(self, direction: str, rate: float) -> bool:
        if self._transport is not None:
            try:
                ok = bool(self._transport(direction, rate))
            except Exception as exc:  # noqa: BLE001
                self._last_error = str(exc)
                return False
            if not ok:
                self._last_error = self._last_error or "MoveAxis WebSocket fehlgeschlagen"
            return ok
        return self._send(direction, rate)

    def _transmit_rate0(self) -> bool:
        for direction in ("east", "west", "north", "south"):
            if not self._deliver(direction, 0.0):
                return False
        return True

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
                # NINA beantwortet den Bibliotheks-Ping nicht. Der Ping schließt
                # sonst die Leitung und die Achse bleibt stehen.
                ws = ws_sync.connect(
                    self.ws_url,
                    open_timeout=2,
                    close_timeout=1,
                    ping_interval=None,
                )
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
                # NINA beantwortet den Bibliotheks-Ping nicht. Der Ping schließt
                # sonst die Leitung und die Achse bleibt stehen.
                ws = ws_sync.connect(
                    self.ws_url,
                    open_timeout=2,
                    close_timeout=1,
                    ping_interval=None,
                )
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
