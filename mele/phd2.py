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
TELEMETRY_SECONDS = 600.0  # 10 min für Guiding-Graph (Phase 1.5)
EVENT_LOG_MAX = 500
SNR_DROP_RATIO = 0.45
SNR_DROP_MIN_INTERVAL_S = 15.0
CALIBRATION_REFRESH_INTERVAL_S = 2.5
DEFAULT_FULLFRAME_MIN_INTERVAL_S = 1.0
DEFAULT_SETTLE = {"pixels": 2.0, "time": 10, "timeout": 60}
_MOUNT_ALERT_HINTS = (
    "pulseguide",
    "pulse guide",
    "mount not",
    "mount error",
    "insufficient correction",
    "ascom",
    "guide output",
)


class Phd2Error(RuntimeError):
    """PHD2 nicht erreichbar oder RPC-Fehler."""


@dataclass
class Phd2LogEvent:
    """Edge-triggered Guiding-Event (kein Polling-Spam)."""

    utc: float
    kind: str
    source: str  # phd2 | derived
    message: str
    payload: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "utc": self.utc,
            "kind": self.kind,
            "source": self.source,
            "message": self.message,
            "payload": dict(self.payload),
        }


def is_mount_alert_message(text: str) -> bool:
    lowered = (text or "").lower()
    return any(hint in lowered for hint in _MOUNT_ALERT_HINTS)


@dataclass
class GuideStepSample:
    """Ein GuideStep. Distanzen sind immer Sensor-/Mount-Pixel (PHD2 Raw)."""

    utc: float
    frame: int | None = None
    dx: float | None = None
    dy: float | None = None
    ra_distance: float | None = None  # px (RADistanceRaw)
    dec_distance: float | None = None  # px
    ra_duration: float | None = None  # ms
    dec_duration: float | None = None  # ms
    ra_direction: str = ""
    dec_direction: str = ""
    guide_time_s: float | None = None  # Sekunden seit Guiding-Start (PHD2 Time)
    error_code: int | None = None
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
    # Guider image scale ["/px] aus get_pixel_scale; None = unbekannt/ungültig
    pixel_scale_arcsec_px: float | None = None
    # PHD2 Equipment Profile + Calibration (API-only, kein Review-Parser)
    phd2_profile_id: int | None = None
    phd2_profile_name: str = ""
    calibration_state: str = "NONE"  # AVAILABLE | NONE
    cal_x_angle: float | None = None
    cal_y_angle: float | None = None
    cal_x_rate: float | None = None
    cal_y_rate: float | None = None
    cal_x_parity: str = ""
    cal_y_parity: str = ""

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


def normalize_pixel_scale(value: Any) -> float | None:
    """Gültiger PHD2-Maßstab in arcsec/pixel, sonst None."""
    scale = _finite(value)
    if scale is None or scale <= 0.0:
        return None
    return scale


def pixels_to_arcsec(pixels: Any, scale_arcsec_per_px: Any) -> float | None:
    """Pixel → Bogensekunden; None wenn Scale oder Wert ungültig."""
    scale = normalize_pixel_scale(scale_arcsec_per_px)
    px = _finite(pixels)
    if scale is None or px is None:
        return None
    return px * scale


def arcsec_to_pixels(arcsec: Any, scale_arcsec_per_px: Any) -> float | None:
    """Bogensekunden → Pixel; None wenn Scale oder Wert ungültig."""
    scale = normalize_pixel_scale(scale_arcsec_per_px)
    value = _finite(arcsec)
    if scale is None or value is None:
        return None
    return value / scale


def enrich_guide_step_dict(step: dict[str, Any], scale_arcsec_per_px: Any) -> dict[str, Any]:
    """Roh-Sample-Dict um *_px / *_arcsec und Anzeige-Einheit ergänzen."""
    out = dict(step)
    scale = normalize_pixel_scale(scale_arcsec_per_px)
    ra_px = _finite(out.get("ra_distance"))
    dec_px = _finite(out.get("dec_distance"))
    out["ra_distance_px"] = ra_px
    out["dec_distance_px"] = dec_px
    out["ra_distance_arcsec"] = pixels_to_arcsec(ra_px, scale)
    out["dec_distance_arcsec"] = pixels_to_arcsec(dec_px, scale)
    avg_px = _finite(out.get("avg_dist"))
    out["avg_dist_px"] = avg_px
    out["avg_dist_arcsec"] = pixels_to_arcsec(avg_px, scale)
    out["display_unit"] = "arcsec" if scale is not None else "px"
    out["pixel_scale_arcsec_px"] = scale
    return out


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
        self._events: deque[Phd2LogEvent] = deque(maxlen=EVENT_LOG_MAX)
        self._fullframe_cache: tuple[float, bytes] | None = None
        self._fullframe_min_interval_s = DEFAULT_FULLFRAME_MIN_INTERVAL_S
        self._last_fullframe_mono = 0.0
        self._pixel_scale_stale = True
        self._last_logged_connection = ""
        self._star_lost_utc: float | None = None
        self._last_snr_for_drop: float | None = None
        self._last_snr_drop_utc: float = 0.0
        self._last_cal_refresh_mono = 0.0

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
        if st.last_step is not None:
            st.last_step = enrich_guide_step_dict(st.last_step, st.pixel_scale_arcsec_px)
        return st

    def telemetry(self, *, limit: int = 120) -> dict[str, Any]:
        self._ensure_pixel_scale()
        with self._lock:
            steps = list(self._steps)[-max(1, int(limit)) :]
            scale = self._status.pixel_scale_arcsec_px
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

        ra_rms_px = _rms(ra)
        dec_rms_px = _rms(dec)
        total_rms_px = _rms(tot)
        enriched = [enrich_guide_step_dict(s.to_dict(), scale) for s in steps]
        last = enriched[-1] if enriched else None
        return {
            "steps": enriched,
            "last": last,
            "count": len(steps),
            "pixel_scale_arcsec_px": scale,
            "display_unit": "arcsec" if scale is not None else "px",
            "ra_rms_px": ra_rms_px,
            "dec_rms_px": dec_rms_px,
            "total_rms_px": total_rms_px,
            "ra_rms_arcsec": pixels_to_arcsec(ra_rms_px, scale),
            "dec_rms_arcsec": pixels_to_arcsec(dec_rms_px, scale),
            "total_rms_arcsec": pixels_to_arcsec(total_rms_px, scale),
            # Abwärtskompatibel: bisher fälschlich als ″ gelesen — jetzt explizit px
            "ra_rms": ra_rms_px,
            "dec_rms": dec_rms_px,
            "total_rms": total_rms_px,
            "window_s": TELEMETRY_SECONDS,
        }

    def set_fullframe_min_interval(self, seconds: float) -> None:
        self._fullframe_min_interval_s = max(0.2, float(seconds))

    def events(self, *, limit: int = 100) -> dict[str, Any]:
        """Letzte Event-Log-Einträge (neueste zuletzt)."""
        n = max(1, min(int(limit), EVENT_LOG_MAX))
        with self._lock:
            items = list(self._events)[-n:]
        return {
            "events": [e.to_dict() for e in items],
            "count": len(items),
            "max": EVENT_LOG_MAX,
        }

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

    def get_pixel_scale(self) -> float | None:
        result = self.call("get_pixel_scale", timeout_s=4.0)
        return normalize_pixel_scale(result)

    def get_profiles(self) -> list[dict[str, Any]]:
        result = self.call("get_profiles", timeout_s=4.0)
        if not isinstance(result, list):
            return []
        out: list[dict[str, Any]] = []
        for item in result:
            if isinstance(item, dict) and item.get("name") is not None:
                out.append({"id": item.get("id"), "name": str(item.get("name") or "")})
        return out

    def try_set_profile(self, profile_id: int) -> dict[str, Any]:
        """PHD2 set_profile nur wenn Equipment disconnected (E2).

        Returns:
            applied: True wenn PHD2-Profil gewechselt wurde.
            Bei connected Equipment: ok=True, applied=False (MeLE-Zuordnung darf trotzdem bleiben).
        """
        try:
            connected = bool(self.call("get_connected", timeout_s=4.0))
        except Phd2Error as exc:
            return {
                "ok": False,
                "applied": False,
                "error": str(exc),
                "reason": "phd2_unreachable",
            }
        if connected:
            return {
                "ok": True,
                "applied": False,
                "error": "",
                "reason": "equipment_connected",
                "message": "PHD2-Equipment verbunden — Profil in PHD2 manuell wechseln",
            }
        try:
            self.call("set_profile", [int(profile_id)], timeout_s=10.0)
        except Phd2Error as exc:
            return {
                "ok": False,
                "applied": False,
                "error": str(exc),
                "reason": "set_profile_failed",
            }
        with self._lock:
            self._last_cal_refresh_mono = 0.0
            self._pixel_scale_stale = True
        return {
            "ok": True,
            "applied": True,
            "error": "",
            "reason": "applied",
            "message": "PHD2-Profil gesetzt",
        }

    def refresh_pixel_scale(self) -> float | None:
        """Aktualisiert den gecachten Maßstab (nicht aus Event-Handler mit Lock aufrufen)."""
        try:
            scale = self.get_pixel_scale()
        except Phd2Error:
            with self._lock:
                # Offline: erneut versuchen; bei Connect-Fehler Scale leeren
                if self._sock is None:
                    self._pixel_scale_stale = True
                else:
                    self._status.pixel_scale_arcsec_px = None
                    self._pixel_scale_stale = False
            return None
        with self._lock:
            self._status.pixel_scale_arcsec_px = scale
            self._pixel_scale_stale = False
        return scale

    def _ensure_pixel_scale(self) -> None:
        with self._lock:
            stale = self._pixel_scale_stale
        if stale:
            self.refresh_pixel_scale()

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
        self._ensure_pixel_scale()
        now = time.monotonic()
        if (now - self._last_cal_refresh_mono) >= CALIBRATION_REFRESH_INTERVAL_S:
            self._last_cal_refresh_mono = now
            self.refresh_calibration_and_profile()

    def refresh_calibration_and_profile(self) -> None:
        """Lädt Profil + Calibration über PHD2-API (kein Log-/GUI-Parser)."""
        calibrated: bool | None
        try:
            calibrated = bool(self.call("get_calibrated", timeout_s=4.0))
        except Phd2Error:
            calibrated = None

        data: Any = None
        try:
            data = self.call("get_calibration_data", ["Mount"], timeout_s=4.0)
        except Phd2Error:
            try:
                data = self.call("get_calibration_data", timeout_s=4.0)
            except Phd2Error:
                data = None

        profile: Any = None
        try:
            profile = self.call("get_profile", timeout_s=4.0)
        except Phd2Error:
            profile = None

        with self._lock:
            if isinstance(profile, dict):
                self._status.phd2_profile_name = str(profile.get("name") or "")
                try:
                    self._status.phd2_profile_id = int(profile["id"])
                except (TypeError, ValueError, KeyError):
                    self._status.phd2_profile_id = None

            data_calibrated = bool(isinstance(data, dict) and data.get("calibrated"))
            if calibrated is True or data_calibrated:
                self._status.calibration_state = "AVAILABLE"
            else:
                self._status.calibration_state = "NONE"

            if isinstance(data, dict):
                self._status.cal_x_angle = _finite(data.get("xAngle"))
                self._status.cal_y_angle = _finite(data.get("yAngle"))
                self._status.cal_x_rate = _finite(data.get("xRate"))
                self._status.cal_y_rate = _finite(data.get("yRate"))
                self._status.cal_x_parity = str(data.get("xParity") or "").strip()
                self._status.cal_y_parity = str(data.get("yParity") or "").strip()
            elif calibrated is False:
                self._status.cal_x_angle = None
                self._status.cal_y_angle = None
                self._status.cal_x_rate = None
                self._status.cal_y_rate = None
                self._status.cal_x_parity = ""
                self._status.cal_y_parity = ""

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
                    prev = self._status.connection
                    self._status.connection = "OFFLINE"
                    self._status.last_error = str(exc)
                    sock = self._sock
                    self._sock = None
                    if prev and prev != "OFFLINE":
                        self._emit_event("OFFLINE", "derived", f"PHD2 offline: {exc}")
                        self._last_logged_connection = "OFFLINE"
                if sock is not None:
                    try:
                        sock.close()
                    except OSError:
                        pass
                self._stop.wait(self.reconnect_s)

    def _connect_once(self) -> None:
        with self._lock:
            self._status.connection = "CONNECTING"
            self._pixel_scale_stale = True
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
        if event == "CalibrationComplete":
            mount = str(msg.get("Mount") or "")
            self._emit_event(
                "CALIBRATION_COMPLETE",
                "phd2",
                "Calibration complete" + (f" ({mount})" if mount else ""),
                mount=mount or None,
            )
            self._last_cal_refresh_mono = 0.0
            return
        if event == "CalibrationFailed":
            reason = str(msg.get("Reason") or msg.get("Msg") or "calibration failed")
            self._emit_event("CALIBRATION_FAILED", "phd2", reason, reason=reason)
            self._status.last_error = reason
            self._last_cal_refresh_mono = 0.0
            return
        if event == "StartGuiding":
            self._clear_lost_star(source_hint="StartGuiding")
            self._status.guiding = True
            self._status.looping = True
            self._status.star_selected = True
            self._status.app_state = "Guiding"
            self._refresh_connection_label()
            return
        if event == "GuideStep":
            was_lost = self._status.lost_star
            self._ingest_guide_step(msg)
            if was_lost:
                self._clear_lost_star(source_hint="GuideStep")
            self._status.guiding = True
            self._status.looping = True
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
            if not self._status.lost_star:
                last_snr = None
                if self._status.last_step:
                    last_snr = _finite(self._status.last_step.get("snr"))
                self._star_lost_utc = time.time()
                self._emit_event(
                    "STAR_LOST",
                    "phd2",
                    "Star lost" + (f" (last SNR {last_snr:.1f})" if last_snr is not None else ""),
                    last_snr=last_snr,
                )
            self._status.lost_star = True
            # Beim reinen Looping kein „Guiding“-Lock — AppState beibehalten.
            self._refresh_connection_label()
            return
        if event == "StarSelected":
            self._clear_lost_star(source_hint="StarSelected")
            self._status.star_selected = True
            x = _finite(msg.get("X"))
            y = _finite(msg.get("Y"))
            if x is not None and y is not None:
                self._status.lock_x = x
                self._status.lock_y = y
            self._emit_event(
                "STAR_SELECTED",
                "phd2",
                "Star selected" + (f" ({x:.1f},{y:.1f})" if x is not None and y is not None else ""),
                x=x,
                y=y,
            )
            self._refresh_connection_label()
            return
        if event == "LockPositionSet":
            self._clear_lost_star(source_hint="LockPositionSet")
            x = _finite(msg.get("X"))
            y = _finite(msg.get("Y"))
            if x is not None and y is not None:
                self._status.lock_x = x
                self._status.lock_y = y
                self._status.star_selected = True
            self._refresh_connection_label()
            return
        if event == "GuidingStopped":
            self._status.guiding = False
            self._emit_event("GUIDING_STOPPED", "phd2", "Guiding stopped")
            self._refresh_connection_label()
            return
        if event == "ConfigurationChange":
            # RPC nicht unter Event-Lock — Flag für nächsten refresh/telemetry
            self._pixel_scale_stale = True
            self._last_cal_refresh_mono = 0.0
            return
        if event == "Alert":
            text = str(msg.get("Msg") or "PHD2 alert")
            self._status.last_error = text
            if is_mount_alert_message(text):
                self._emit_event("MOUNT_ERROR", "phd2", text, alert=text)
            else:
                self._emit_event("ALERT", "phd2", text, alert=text)

    def _emit_event(
        self,
        kind: str,
        source: str,
        message: str,
        **payload: Any,
    ) -> None:
        """Muss unter self._lock aufgerufen werden (Event-Handler)."""
        clean = {k: v for k, v in payload.items() if v is not None}
        self._events.append(
            Phd2LogEvent(
                utc=time.time(),
                kind=str(kind),
                source=str(source),
                message=str(message),
                payload=clean,
            )
        )

    def _clear_lost_star(self, *, source_hint: str) -> bool:
        """Lost→ok; bei Transition STAR_RECOVERED (derived). True wenn recovered."""
        if not self._status.lost_star:
            return False
        now = time.time()
        outage = None
        if self._star_lost_utc is not None:
            outage = max(0.0, now - self._star_lost_utc)
        self._status.lost_star = False
        self._star_lost_utc = None
        self._emit_event(
            "STAR_RECOVERED",
            "derived",
            f"Star recovered" + (f" (outage {outage:.1f}s)" if outage is not None else ""),
            outage_s=outage,
            via=source_hint,
        )
        return True

    def _apply_app_state(self, state: str) -> None:
        self._status.app_state = state
        self._status.guiding = state == "Guiding"
        self._status.looping = state in ("Looping", "Guiding", "Calibrating")
        self._status.paused = state == "Paused"
        if state == "LostLock":
            if not self._status.lost_star:
                last_snr = None
                if self._status.last_step:
                    last_snr = _finite(self._status.last_step.get("snr"))
                self._star_lost_utc = time.time()
                self._emit_event(
                    "STAR_LOST",
                    "phd2",
                    "Star lost (AppState LostLock)",
                    last_snr=last_snr,
                )
            self._status.lost_star = True
        self._refresh_connection_label()

    def _refresh_connection_label(self) -> None:
        online = self._sock is not None
        prev = self._status.connection
        new = _map_connection_state(
            online=online,
            app_state=self._status.app_state,
            lost_star=self._status.lost_star,
            paused=self._status.paused,
        )
        self._status.connection = new
        if new == prev:
            return
        # LOST_STAR: Detail-Event STAR_LOST kommt aus StarLost/AppState — hier kein zweites
        if new == "LOST_STAR":
            self._last_logged_connection = new
            return
        if new == self._last_logged_connection:
            return
        self._last_logged_connection = new
        self._emit_event(new, "derived", new.replace("_", " "))

    def _ingest_guide_step(self, msg: dict[str, Any]) -> None:
        ra_px = _finite(msg.get("RADistanceRaw"))
        if ra_px is None:
            ra_px = _finite(msg.get("RADistanceGuide"))
        dec_px = _finite(msg.get("DECDistanceRaw"))
        if dec_px is None:
            dec_px = _finite(msg.get("DecDistanceRaw"))
        if dec_px is None:
            dec_px = _finite(msg.get("DECDistanceGuide"))
        err_raw = msg.get("ErrorCode")
        try:
            error_code = int(err_raw) if err_raw is not None else None
        except (TypeError, ValueError):
            error_code = None
        snr = _finite(msg.get("SNR"))
        sample = GuideStepSample(
            utc=time.time(),
            frame=int(msg["Frame"]) if msg.get("Frame") is not None else None,
            dx=_finite(msg.get("dx") if "dx" in msg else msg.get("DX")),
            dy=_finite(msg.get("dy") if "dy" in msg else msg.get("DY")),
            ra_distance=ra_px,
            dec_distance=dec_px,
            ra_duration=_finite(msg.get("RADuration")),
            dec_duration=_finite(msg.get("DECDuration") or msg.get("DecDuration")),
            ra_direction=str(msg.get("RADirection") or "").strip(),
            dec_direction=str(msg.get("DECDirection") or msg.get("DecDirection") or "").strip(),
            guide_time_s=_finite(msg.get("Time")),
            error_code=error_code,
            star_mass=_finite(msg.get("StarMass")),
            snr=snr,
            hfd=_finite(msg.get("HFD")),
            avg_dist=_finite(msg.get("AvgDist")),
        )
        self._steps.append(sample)
        cutoff = time.time() - TELEMETRY_SECONDS
        while self._steps and self._steps[0].utc < cutoff:
            self._steps.popleft()
        self._status.last_step = sample.to_dict()
        self._maybe_log_snr_drop(snr)

    def _maybe_log_snr_drop(self, snr: float | None) -> None:
        if snr is None:
            return
        prev = self._last_snr_for_drop
        self._last_snr_for_drop = snr
        if prev is None or prev <= 0:
            return
        now = time.time()
        if now - self._last_snr_drop_utc < SNR_DROP_MIN_INTERVAL_S:
            return
        if snr > prev * SNR_DROP_RATIO:
            return
        # Deutlicher Abfall (z. B. 72 → 31)
        self._last_snr_drop_utc = now
        self._emit_event(
            "SNR_DROP",
            "derived",
            f"SNR {prev:.1f} → {snr:.1f}",
            snr_from=prev,
            snr_to=snr,
        )


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
