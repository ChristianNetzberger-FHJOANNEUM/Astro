"""PHD2 Event-Server Client (JSON-RPC 2.0) + Guide-Image-Provider.

PHD2 besitzt die ASI120 exklusiv. MeLE spricht nur den Event-Server
(typisch localhost:4400) an — kein ZWO-/ASCOM-Kamerazugriff.
"""

from __future__ import annotations

import base64
import json
import logging
import math
import socket
import threading
import time
from collections import deque
from dataclasses import asdict, dataclass, field
from io import BytesIO
from pathlib import Path
from typing import Any

import numpy as np
from PIL import Image

logger = logging.getLogger(__name__)

DEFAULT_HOST = "127.0.0.1"
DEFAULT_PORT = 4400
TELEMETRY_SECONDS = 300.0
DEFAULT_FULLFRAME_MIN_INTERVAL_S = 1.0
DEFAULT_SETTLE = {"pixels": 2.0, "time": 10, "timeout": 60}


class Phd2Error(RuntimeError):
    """PHD2 nicht erreichbar oder RPC-Fehler."""


@dataclass
class GuideStepSample:
    utc: float
    frame: int | None = None
    dx: float | None = None
    dy: float | None = None
    ra_distance: float | None = None
    dec_distance: float | None = None
    ra_duration: float | None = None
    dec_duration: float | None = None
    star_mass: float | None = None
    snr: float | None = None
    hfd: float | None = None
    avg_dist: float | None = None

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class Phd2Status:
    connection: str = "OFFLINE"  # OFFLINE|CONNECTING|CONNECTED|…
    app_state: str = ""
    equipment_connected: bool | None = None
    camera_name: str = ""
    mount_name: str = ""
    exposure_ms: int | None = None
    last_error: str = ""
    phd_version: str = ""
    guiding: bool = False
    looping: bool = False
    paused: bool = False
    lost_star: bool = False
    star_selected: bool = False
    last_step: dict[str, Any] | None = None
    # Leitstern-Lock in Sensorpixeln (Fullframe); für Overlay
    lock_x: float | None = None
    lock_y: float | None = None
    frame_width: int | None = None
    frame_height: int | None = None
    lock_box_px: int = 21  # Anzeige-Quadrat (≈ PHD2 Search-Box)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def _finite(value: Any) -> float | None:
    if value is None:
        return None
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    if math.isnan(number) or math.isinf(number):
        return None
    return number


def _map_connection_state(
    *,
    online: bool,
    app_state: str,
    lost_star: bool,
    paused: bool,
) -> str:
    if not online:
        return "OFFLINE"
    state = (app_state or "").strip()
    if paused or state == "Paused":
        return "PAUSED"
    # LostLock / StarLost nur als Primärstatus während Guiding — beim reinen
    # Looping (Setup/Fokus) bleibt LOOPING, Telemetrie zeigt lost_star.
    if state == "LostLock" or (lost_star and state == "Guiding"):
        return "LOST_STAR"
    if state == "Guiding":
        return "GUIDING"
    if state == "Calibrating":
        return "CALIBRATING"
    if state == "Looping":
        return "LOOPING"
    if lost_star and state not in ("Looping", "Stopped", "Selected", ""):
        return "LOST_STAR"
    if state in ("Stopped", "Selected", ""):
        return "CONNECTED"
    return "CONNECTED"


class Phd2Client:
    """Ein TCP-Client zum PHD2 Event-Server (prozessweit teilen)."""

    def __init__(
        self,
        host: str = DEFAULT_HOST,
        port: int = DEFAULT_PORT,
        *,
        reconnect_s: float = 2.0,
    ) -> None:
        self.host = str(host or DEFAULT_HOST).strip() or DEFAULT_HOST
        self.port = int(port or DEFAULT_PORT)
        self.reconnect_s = max(0.5, float(reconnect_s))
        self._lock = threading.RLock()
        self._sock: socket.socket | None = None
        self._reader: threading.Thread | None = None
        self._stop = threading.Event()
        self._started = False
        self._rpc_id = 1
        self._pending: dict[int, dict[str, Any]] = {}
        self._buf = b""
        self._status = Phd2Status()
        self._steps: deque[GuideStepSample] = deque()
        self._fullframe_cache: tuple[float, bytes] | None = None
        self._fullframe_min_interval_s = DEFAULT_FULLFRAME_MIN_INTERVAL_S
        self._last_fullframe_mono = 0.0

    # --- lifecycle ---------------------------------------------------------

    def start(self) -> None:
        with self._lock:
            if self._started:
                return
            self._started = True
            self._stop.clear()
            self._reader = threading.Thread(
                target=self._reader_loop,
                name="phd2-event-reader",
                daemon=True,
            )
            self._reader.start()

    def stop(self) -> None:
        self._stop.set()
        with self._lock:
            sock = self._sock
            self._sock = None
            self._started = False
        if sock is not None:
            try:
                sock.close()
            except OSError:
                pass

    def ensure_started(self) -> None:
        if not self._started:
            self.start()

    # --- status / telemetry ------------------------------------------------

    def get_status(self) -> Phd2Status:
        with self._lock:
            st = Phd2Status(**asdict(self._status))
        return st

    def telemetry(self, *, limit: int = 120) -> dict[str, Any]:
        with self._lock:
            steps = list(self._steps)[-max(1, int(limit)) :]
        ra = [s.ra_distance for s in steps if s.ra_distance is not None]
        dec = [s.dec_distance for s in steps if s.dec_distance is not None]
        tot = []
        for s in steps:
            if s.ra_distance is None or s.dec_distance is None:
                continue
            tot.append(math.hypot(s.ra_distance, s.dec_distance))

        def _rms(vals: list[float]) -> float | None:
            if not vals:
                return None
            return math.sqrt(sum(v * v for v in vals) / len(vals))

        return {
            "steps": [s.to_dict() for s in steps],
            "count": len(steps),
            "ra_rms": _rms(ra),
            "dec_rms": _rms(dec),
            "total_rms": _rms(tot),
            "window_s": TELEMETRY_SECONDS,
        }

    def set_fullframe_min_interval(self, seconds: float) -> None:
        self._fullframe_min_interval_s = max(0.2, float(seconds))

    # --- RPC commands ------------------------------------------------------

    def call(self, method: str, params: Any = None, *, timeout_s: float = 8.0) -> Any:
        self.ensure_started()
        deadline = time.monotonic() + max(0.5, float(timeout_s))
        with self._lock:
            rpc_id = self._rpc_id
            self._rpc_id += 1
            payload: dict[str, Any] = {"method": method, "id": rpc_id}
            if params is not None:
                payload["params"] = params
            self._pending[rpc_id] = {"event": threading.Event(), "result": None, "error": None}
            line = (json.dumps(payload, separators=(",", ":")) + "\r\n").encode("utf-8")
            sock = self._sock
        if sock is None:
            with self._lock:
                self._pending.pop(rpc_id, None)
            raise Phd2Error("PHD2 offline")
        try:
            sock.sendall(line)
        except OSError as exc:
            with self._lock:
                self._pending.pop(rpc_id, None)
                self._status.last_error = str(exc)
            raise Phd2Error(f"PHD2 send failed: {exc}") from exc

        event = self._pending[rpc_id]["event"]
        while time.monotonic() < deadline:
            if event.wait(timeout=0.2):
                break
        with self._lock:
            entry = self._pending.pop(rpc_id, None)
        if entry is None or not entry["event"].is_set():
            raise Phd2Error(f"PHD2 timeout: {method}")
        if entry["error"] is not None:
            raise Phd2Error(str(entry["error"]))
        return entry["result"]

    def loop(self) -> Any:
        return self.call("loop")

    def stop_capture(self) -> Any:
        return self.call("stop_capture")

    def set_exposure(self, exposure_ms: int) -> Any:
        ms = int(exposure_ms)
        result = self.call("set_exposure", [ms])
        with self._lock:
            self._status.exposure_ms = ms
        return result

    def get_exposure(self) -> int | None:
        result = self.call("get_exposure")
        try:
            return int(result)
        except (TypeError, ValueError):
            return None

    def get_exposure_durations(self) -> list[int]:
        result = self.call("get_exposure_durations")
        if not isinstance(result, list):
            return []
        out: list[int] = []
        for item in result:
            try:
                out.append(int(item))
            except (TypeError, ValueError):
                continue
        return out

    def find_star(self) -> Any:
        result = self.call("find_star", timeout_s=20.0)
        # Erfolg: typisch [x, y] Lock-Position
        if isinstance(result, (list, tuple)) and len(result) >= 2:
            x = _finite(result[0])
            y = _finite(result[1])
            if x is not None and y is not None:
                self._set_lock_position(x, y)
        return result

    def guide(self, *, recalibrate: bool = False, settle: dict[str, Any] | None = None) -> Any:
        params: list[Any] = [settle or dict(DEFAULT_SETTLE)]
        if recalibrate:
            params.append(True)
        return self.call("guide", params, timeout_s=30.0)

    def set_paused(self, paused: bool, *, full: bool = False) -> Any:
        params: list[Any] = [bool(paused)]
        if paused and full:
            params.append("full")
        return self.call("set_paused", params)

    def get_star_image(self, size: int = 64) -> dict[str, Any]:
        return self.call("get_star_image", [max(15, int(size))], timeout_s=10.0)

    def get_lock_position(self) -> tuple[float, float] | None:
        result = self.call("get_lock_position", timeout_s=4.0)
        if isinstance(result, (list, tuple)) and len(result) >= 2:
            x = _finite(result[0])
            y = _finite(result[1])
            if x is not None and y is not None:
                return x, y
        return None

    def get_camera_frame_size(self) -> tuple[int, int] | None:
        result = self.call("get_camera_frame_size", timeout_s=4.0)
        if isinstance(result, (list, tuple)) and len(result) >= 2:
            try:
                return int(result[0]), int(result[1])
            except (TypeError, ValueError):
                return None
        return None

    def save_image(self) -> str:
        result = self.call("save_image", timeout_s=15.0)
        if isinstance(result, dict) and result.get("filename"):
            return str(result["filename"])
        raise Phd2Error("save_image: filename missing")

    def _set_lock_position(self, x: float | None, y: float | None) -> None:
        with self._lock:
            self._status.lock_x = x
            self._status.lock_y = y
            if x is not None and y is not None:
                self._status.star_selected = True

    def refresh_equipment(self) -> None:
        try:
            connected = self.call("get_connected", timeout_s=4.0)
            equip = self.call("get_current_equipment", timeout_s=4.0)
            exposure = self.call("get_exposure", timeout_s=4.0)
        except Phd2Error as exc:
            with self._lock:
                self._status.last_error = str(exc)
            return
        with self._lock:
            self._status.equipment_connected = bool(connected)
            if isinstance(equip, dict):
                cam = equip.get("camera") if isinstance(equip.get("camera"), dict) else {}
                mnt = equip.get("mount") if isinstance(equip.get("mount"), dict) else {}
                self._status.camera_name = str(cam.get("name") or "")
                self._status.mount_name = str(mnt.get("name") or "")
            try:
                self._status.exposure_ms = int(exposure)
            except (TypeError, ValueError):
                pass
        try:
            size = self.get_camera_frame_size()
            if size is not None:
                with self._lock:
                    self._status.frame_width = size[0]
                    self._status.frame_height = size[1]
        except Phd2Error:
            pass
        try:
            lock = self.get_lock_position()
            if lock is not None:
                self._set_lock_position(lock[0], lock[1])
            else:
                self._set_lock_position(None, None)
        except Phd2Error:
            # kein Stern / nicht verfügbar
            with self._lock:
                if not self._status.star_selected:
                    self._status.lock_x = None
                    self._status.lock_y = None

    # --- image provider ----------------------------------------------------

    def guide_image_jpeg(
        self,
        *,
        kind: str = "auto",
        fullframe_min_interval_s: float | None = None,
        star_size: int = 96,
        max_width: int = 1280,
    ) -> tuple[bytes, dict[str, Any]]:
        """JPEG-Bytes + Meta. kind: auto|star|full."""
        status = self.get_status()
        requested = (kind or "auto").strip().lower()
        mode = requested
        if mode == "auto":
            # Setup/Navigation: Fullframe. Star-Crop nur bei aktivem Guiding
            # mit gültigem Stern (nicht bei LOST_STAR / bloßem star_selected).
            if status.guiding and status.star_selected and not status.lost_star:
                mode = "star"
            else:
                mode = "full"
        if mode == "star":
            try:
                return self._star_jpeg(star_size=star_size), {
                    "kind": "star",
                    "connection": status.connection,
                }
            except Phd2Error:
                if requested == "star":
                    raise
                mode = "full"
        if fullframe_min_interval_s is not None:
            self.set_fullframe_min_interval(fullframe_min_interval_s)
        return self._fullframe_jpeg(max_width=max_width), {
            "kind": "full",
            "connection": status.connection,
            "min_interval_s": self._fullframe_min_interval_s,
        }

    def _star_jpeg(self, *, star_size: int) -> bytes:
        data = self.get_star_image(star_size)
        width = int(data.get("width") or 0)
        height = int(data.get("height") or 0)
        pixels_b64 = data.get("pixels")
        if width <= 0 or height <= 0 or not pixels_b64:
            raise Phd2Error("get_star_image: incomplete")
        raw = base64.b64decode(pixels_b64)
        arr = np.frombuffer(raw, dtype="<u2").reshape((height, width)).astype(np.float32)
        return _stretch_to_jpeg(arr, max_width=max(width, 256))

    def _fullframe_jpeg(self, *, max_width: int) -> bytes:
        now = time.monotonic()
        with self._lock:
            cached = self._fullframe_cache
            min_iv = self._fullframe_min_interval_s
            last = self._last_fullframe_mono
        if cached is not None and (now - last) < min_iv:
            return cached[1]
        with self._lock:
            fallback_lock = (
                (self._status.lock_x, self._status.lock_y)
                if self._status.lock_x is not None and self._status.lock_y is not None
                else None
            )
            lock_box_px = int(self._status.lock_box_px or 21)
        path = Path(self.save_image())
        try:
            jpeg = _fits_path_to_jpeg(
                path,
                max_width=max_width,
                lock=fallback_lock,
                lock_box_px=lock_box_px,
            )
        finally:
            try:
                path.unlink(missing_ok=True)
            except OSError:
                pass
        with self._lock:
            self._fullframe_cache = (now, jpeg)
            self._last_fullframe_mono = now
        return jpeg

    # --- reader thread -----------------------------------------------------

    def _reader_loop(self) -> None:
        while not self._stop.is_set():
            try:
                self._connect_once()
                self._read_forever()
            except Exception as exc:  # noqa: BLE001
                logger.debug("PHD2 reader: %s", exc)
                with self._lock:
                    self._status.connection = "OFFLINE"
                    self._status.last_error = str(exc)
                    sock = self._sock
                    self._sock = None
                if sock is not None:
                    try:
                        sock.close()
                    except OSError:
                        pass
                self._stop.wait(self.reconnect_s)

    def _connect_once(self) -> None:
        with self._lock:
            self._status.connection = "CONNECTING"
            self._buf = b""
        sock = socket.create_connection((self.host, self.port), timeout=4.0)
        sock.settimeout(1.0)
        with self._lock:
            self._sock = sock
            self._status.connection = "CONNECTED"
            self._status.last_error = ""
        logger.info("PHD2 connected %s:%s", self.host, self.port)

    def _read_forever(self) -> None:
        assert self._sock is not None
        while not self._stop.is_set():
            try:
                chunk = self._sock.recv(65536)
            except socket.timeout:
                continue
            except OSError:
                raise
            if not chunk:
                raise Phd2Error("PHD2 connection closed")
            with self._lock:
                self._buf += chunk
                while True:
                    nl = self._buf.find(b"\n")
                    if nl < 0:
                        break
                    line = self._buf[:nl].strip()
                    self._buf = self._buf[nl + 1 :]
                    if not line:
                        continue
                    try:
                        msg = json.loads(line.decode("utf-8", errors="replace"))
                    except json.JSONDecodeError:
                        continue
                    self._handle_message(msg)

    def _handle_message(self, msg: dict[str, Any]) -> None:
        if "id" in msg and ("result" in msg or "error" in msg):
            rpc_id = msg.get("id")
            try:
                key = int(rpc_id)
            except (TypeError, ValueError):
                return
            entry = self._pending.get(key)
            if entry is None:
                return
            if msg.get("error") is not None:
                err = msg["error"]
                entry["error"] = err.get("message") if isinstance(err, dict) else str(err)
            else:
                entry["result"] = msg.get("result")
            entry["event"].set()
            return

        event = str(msg.get("Event") or "")
        if event == "Version":
            self._status.phd_version = str(msg.get("PHDVersion") or "")
            return
        if event == "AppState":
            state = str(msg.get("State") or "")
            self._apply_app_state(state)
            return
        if event == "LoopingExposures":
            self._status.looping = True
            self._status.guiding = False
            if not self._status.app_state:
                self._status.app_state = "Looping"
            self._refresh_connection_label()
            return
        if event == "LoopingExposuresStopped":
            self._status.looping = False
            self._refresh_connection_label()
            return
        if event == "StartCalibration":
            self._status.app_state = "Calibrating"
            self._refresh_connection_label()
            return
        if event == "StartGuiding":
            self._status.guiding = True
            self._status.looping = True
            self._status.lost_star = False
            self._status.app_state = "Guiding"
            self._refresh_connection_label()
            return
        if event == "GuideStep":
            self._ingest_guide_step(msg)
            self._status.guiding = True
            self._status.looping = True
            self._status.lost_star = False
            self._status.star_selected = True
            self._status.app_state = "Guiding"
            self._refresh_connection_label()
            return
        if event == "Paused":
            self._status.paused = True
            self._status.app_state = "Paused"
            self._refresh_connection_label()
            return
        if event == "Resumed":
            self._status.paused = False
            self._refresh_connection_label()
            return
        if event == "StarLost":
            self._status.lost_star = True
            # Beim reinen Looping kein „Guiding“-Lock — AppState beibehalten.
            self._refresh_connection_label()
            return
        if event == "StarSelected":
            self._status.star_selected = True
            self._status.lost_star = False
            x = _finite(msg.get("X"))
            y = _finite(msg.get("Y"))
            if x is not None and y is not None:
                self._status.lock_x = x
                self._status.lock_y = y
            return
        if event == "LockPositionSet":
            x = _finite(msg.get("X"))
            y = _finite(msg.get("Y"))
            if x is not None and y is not None:
                self._status.lock_x = x
                self._status.lock_y = y
                self._status.star_selected = True
                self._status.lost_star = False
            return
        if event == "GuidingStopped":
            self._status.guiding = False
            self._refresh_connection_label()
            return
        if event == "Alert":
            self._status.last_error = str(msg.get("Msg") or "PHD2 alert")

    def _apply_app_state(self, state: str) -> None:
        self._status.app_state = state
        self._status.guiding = state == "Guiding"
        self._status.looping = state in ("Looping", "Guiding", "Calibrating")
        self._status.paused = state == "Paused"
        self._status.lost_star = state == "LostLock"
        self._refresh_connection_label()

    def _refresh_connection_label(self) -> None:
        online = self._sock is not None
        self._status.connection = _map_connection_state(
            online=online,
            app_state=self._status.app_state,
            lost_star=self._status.lost_star,
            paused=self._status.paused,
        )

    def _ingest_guide_step(self, msg: dict[str, Any]) -> None:
        sample = GuideStepSample(
            utc=time.time(),
            frame=int(msg["Frame"]) if msg.get("Frame") is not None else None,
            dx=_finite(msg.get("dx") if "dx" in msg else msg.get("DX")),
            dy=_finite(msg.get("dy") if "dy" in msg else msg.get("DY")),
            ra_distance=_finite(msg.get("RADistanceRaw") or msg.get("RADistanceGuide")),
            dec_distance=_finite(msg.get("DECDistanceRaw") or msg.get("DecDistanceRaw")),
            ra_duration=_finite(msg.get("RADuration")),
            dec_duration=_finite(msg.get("DECDuration") or msg.get("DecDuration")),
            star_mass=_finite(msg.get("StarMass")),
            snr=_finite(msg.get("SNR")),
            hfd=_finite(msg.get("HFD")),
            avg_dist=_finite(msg.get("AvgDist")),
        )
        self._steps.append(sample)
        cutoff = time.time() - TELEMETRY_SECONDS
        while self._steps and self._steps[0].utc < cutoff:
            self._steps.popleft()
        self._status.last_step = sample.to_dict()


_CLIENT: Phd2Client | None = None
_CLIENT_LOCK = threading.Lock()


def get_shared_phd2_client(
    *,
    host: str = DEFAULT_HOST,
    port: int = DEFAULT_PORT,
) -> Phd2Client:
    global _CLIENT
    with _CLIENT_LOCK:
        if _CLIENT is None:
            _CLIENT = Phd2Client(host=host, port=port)
            _CLIENT.start()
        return _CLIENT


def _draw_lock_box(
    image: Image.Image,
    *,
    lock_x: float,
    lock_y: float,
    lock_box_px: int,
    scale: float = 1.0,
) -> Image.Image:
    """Zeichnet Lock-Quadrat + Kreuz in Bildpixeln (nach optionalem Resize)."""
    from PIL import ImageDraw

    rgb = image.convert("RGB")
    side = max(8.0, float(lock_box_px) * scale)
    half = side / 2.0
    x = float(lock_x) * scale
    y = float(lock_y) * scale
    draw = ImageDraw.Draw(rgb)
    color = (34, 197, 94)  # #22c55e
    draw.rectangle(
        [x - half, y - half, x + half, y + half],
        outline=color,
        width=max(1, int(round(2 * max(scale, 1.0)))),
    )
    arm = max(3.0, side * 0.35)
    stroke = max(1, int(round(1.5 * max(scale, 1.0))))
    draw.line([x - arm, y, x + arm, y], fill=color, width=stroke)
    draw.line([x, y - arm, x, y + arm], fill=color, width=stroke)
    return rgb


def _stretch_to_jpeg(
    arr: np.ndarray,
    *,
    max_width: int = 1280,
    lock: tuple[float, float] | None = None,
    lock_box_px: int = 21,
) -> bytes:
    finite = arr[np.isfinite(arr)]
    if finite.size == 0:
        raise Phd2Error("empty image")
    lo = float(np.percentile(finite, 1.0))
    hi = float(np.percentile(finite, 99.5))
    if hi <= lo:
        hi = lo + 1.0
    scaled = np.clip((arr - lo) / (hi - lo), 0.0, 1.0)
    # soft asinh-like boost without astropy dependency here
    scaled = np.log1p(scaled * 9.0) / math.log1p(9.0)
    u8 = (scaled * 255.0).astype(np.uint8)
    image: Image.Image = Image.fromarray(u8, mode="L")
    scale = 1.0
    if max_width and image.width > max_width:
        scale = max_width / float(image.width)
        image = image.resize((max_width, max(1, int(image.height * scale))), Image.Resampling.BILINEAR)
    if lock is not None:
        image = _draw_lock_box(
            image,
            lock_x=lock[0],
            lock_y=lock[1],
            lock_box_px=lock_box_px,
            scale=scale,
        )
    buf = BytesIO()
    image.save(buf, format="JPEG", quality=85)
    return buf.getvalue()


def _fits_path_to_jpeg(
    path: Path,
    *,
    max_width: int = 1280,
    lock: tuple[float, float] | None = None,
    lock_box_px: int = 21,
) -> bytes:
    from astropy.io import fits

    with fits.open(path, memmap=False, mode="readonly") as hdul:
        data = hdul[0].data
        hdr = hdul[0].header
        if data is None and len(hdul) > 1:
            data = hdul[1].data
            hdr = hdul[1].header
    if data is None:
        raise Phd2Error(f"no image data in {path}")
    arr = np.asarray(data, dtype=np.float32)
    if arr.ndim == 3:
        arr = np.mean(arr, axis=0 if arr.shape[0] in (3, 4) else -1)
    # PHD2 schreibt Lock in denselben Sensorpixeln wie das FITS — bevorzugt Header
    hx = _finite(hdr.get("PHDLOCKX"))
    hy = _finite(hdr.get("PHDLOCKY"))
    if hx is not None and hy is not None:
        lock = (hx, hy)
    return _stretch_to_jpeg(arr, max_width=max_width, lock=lock, lock_box_px=lock_box_px)
