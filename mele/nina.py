"""NINA Advanced API – Mount-Telemetrie + GoTo/Abort + Kamera-Capture (Phase 2).

Quellen (Advanced API / ninaAPI):
  GET {base}/equipment/mount/info
  GET {base}/equipment/mount/slew?ra=&dec=&waitForResult=&center=&rotate=
  GET {base}/equipment/mount/slew/stop
  GET {base}/equipment/camera/info
  GET {base}/equipment/camera/capture?duration=&gain=&imageType=&save=&targetName=&waitForResult=
  GET {base}/profile/change-value?settingpath=&newValue=

Kamera Image Options (live verifiziert an NINA 3.2 + Advanced API):
  settingpath=ImageFileSettings-FilePath  → Image File Path
  settingpath=ImageFileSettings-FilePattern → Dateiname/Unterordner-Muster

Offizielle Semantik mount/slew (Mount.cs + OpenAPI api_spec):
  - HTTP GET, Query-Parameter
  - ra, dec: Winkel in Grad (OpenAPI: \"RA angle … in degree\";
    C#: new Coordinates(Angle.ByDegree(ra), Angle.ByDegree(dec), Epoch.J2000))
  - Epoch der Eingabe: J2000 — NINA transformiert intern zum Mount-System
    (z.B. EquatorialSystem=JNOW). Keine eigene Praezession in app_mele.
  - waitForResult=false: Antwort \"Slew started\", Polling liefert Slewing.
  - center/rotate: Phase 2 immer false (kein Plate-Solve/Center).

Kamera-Capture (christian-photo/ninaAPI Changelog):
  - duration (s), gain, imageType (light/dark/…), save=true zum Speichern,
    targetName, waitForResult, stream, omitImage, onlyAwaitCaptureCompletion

Wrapper:
  {"Response": ..., "Error": "", "StatusCode": 200, "Success": true, "Type": "API"}
"""

from __future__ import annotations

import json
import math
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode
from urllib.request import Request, urlopen


DEFAULT_BASE_URL = "http://localhost:1888/v2/api"
DEFAULT_TIMEOUT_S = 1.5
COMMAND_TIMEOUT_S = 3.0


@dataclass(frozen=True)
class MountInfo:
    connected: bool
    right_ascension_hours: float | None = None
    declination_deg: float | None = None
    altitude_deg: float | None = None
    azimuth_deg: float | None = None
    side_of_pier: str = ""
    slewing: bool = False
    tracking_enabled: bool = False
    tracking_mode: str = ""
    equatorial_system: str = ""
    site_latitude: float | None = None
    site_longitude: float | None = None
    site_elevation: float | None = None
    alignment_mode: str = ""
    driver_name: str = ""
    device_id: str = ""
    right_ascension_string: str = ""
    declination_string: str = ""
    at_park: bool = False

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class NinaMountStatus:
    """Ergebnis von get_mount_info: api_online + optional Mount-Telemetrie."""

    api_online: bool
    error: str = ""
    mount: MountInfo | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "api_online": self.api_online,
            "error": self.error,
            "mount": None if self.mount is None else self.mount.to_dict(),
        }


@dataclass(frozen=True)
class NinaCommandResult:
    ok: bool
    api_online: bool
    message: str = ""
    error: str = ""
    status_code: int | None = None
    request: dict[str, Any] | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "ok": self.ok,
            "api_online": self.api_online,
            "message": self.message,
            "error": self.error,
            "status_code": self.status_code,
            "request": self.request,
        }


@dataclass(frozen=True)
class CameraInfo:
    connected: bool
    name: str = ""
    device_id: str = ""
    exposure_max: float | None = None
    exposure_min: float | None = None
    exposure_end_time: str = ""
    is_exposing: bool = False
    gain: float | None = None
    gain_min: float | None = None
    gain_max: float | None = None
    offset: float | None = None
    bin_x: int | None = None
    bin_y: int | None = None
    temperature: float | None = None
    cooler_on: bool = False
    can_set_gain: bool = False
    can_set_offset: bool = False
    can_set_temperature: bool = False
    battery: float | None = None

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class NinaCameraStatus:
    api_online: bool
    error: str = ""
    camera: CameraInfo | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "api_online": self.api_online,
            "error": self.error,
            "camera": None if self.camera is None else self.camera.to_dict(),
        }


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


def _bool(value: Any, default: bool = False) -> bool:
    if isinstance(value, bool):
        return value
    if value in (1, "1", "true", "True"):
        return True
    if value in (0, "0", "false", "False"):
        return False
    return default


def _str(value: Any) -> str:
    if value is None:
        return ""
    return str(value)


def _pier_label(raw: str) -> str:
    key = raw.strip().lower()
    if key in {"piereast", "east", "e"}:
        return "East"
    if key in {"pierwest", "west", "w"}:
        return "West"
    if not key or key in {"unknown", "pierunknown"}:
        return "Unknown"
    return raw


def validate_slew_radec_deg(ra_deg: float, dec_deg: float) -> str:
    """Leerer String = ok, sonst Fehlermeldung. RA/Dec in Grad (API-Einheit)."""
    ra = _finite(ra_deg)
    dec = _finite(dec_deg)
    if ra is None or dec is None:
        return "RA/Dec ungueltig."
    if not (-90.0 <= dec <= 90.0):
        return "Dec ausserhalb von -90…+90 Grad."
    # RA in Grad: 0…360 ueblich; API akzeptiert double ohne Wrap-Zwang
    if not (0.0 <= ra < 360.0):
        return "RA ausserhalb von 0…360 Grad."
    return ""


def parse_mount_payload(payload: Any) -> NinaMountStatus:
    """Parst die Advanced-API-Antwort. Keine Felder erfinden."""
    if not isinstance(payload, dict):
        return NinaMountStatus(api_online=False, error="Antwort ist kein JSON-Objekt.")
    if payload.get("Success") is False:
        return NinaMountStatus(
            api_online=True,
            error=_str(payload.get("Error")) or "Success=false",
            mount=None,
        )
    response = payload.get("Response")
    if not isinstance(response, dict):
        return NinaMountStatus(
            api_online=True,
            error="Response fehlt oder ist ungueltig.",
            mount=None,
        )
    pier_raw = _str(response.get("SideOfPier"))
    mount = MountInfo(
        connected=_bool(response.get("Connected"), False),
        right_ascension_hours=_finite(response.get("RightAscension")),
        declination_deg=_finite(response.get("Declination")),
        altitude_deg=_finite(response.get("Altitude")),
        azimuth_deg=_finite(response.get("Azimuth")),
        side_of_pier=_pier_label(pier_raw),
        slewing=_bool(response.get("Slewing"), False),
        tracking_enabled=_bool(response.get("TrackingEnabled"), False),
        tracking_mode=_str(response.get("TrackingMode")),
        equatorial_system=_str(response.get("EquatorialSystem")),
        site_latitude=_finite(response.get("SiteLatitude")),
        site_longitude=_finite(response.get("SiteLongitude")),
        site_elevation=_finite(response.get("SiteElevation")),
        alignment_mode=_str(response.get("AlignmentMode")),
        driver_name=_str(response.get("Name") or response.get("DisplayName")),
        device_id=_str(response.get("DeviceId")),
        right_ascension_string=_str(response.get("RightAscensionString")),
        declination_string=_str(response.get("DeclinationString")),
        at_park=_bool(response.get("AtPark"), False),
    )
    return NinaMountStatus(api_online=True, error="", mount=mount)


def parse_camera_payload(payload: Any) -> NinaCameraStatus:
    """Parst /equipment/camera/info. Unbekannte Felder werden ignoriert."""
    if not isinstance(payload, dict):
        return NinaCameraStatus(api_online=False, error="Antwort ist kein JSON-Objekt.")
    if payload.get("Success") is False:
        return NinaCameraStatus(
            api_online=True,
            error=_str(payload.get("Error")) or "Success=false",
            camera=None,
        )
    response = payload.get("Response")
    if not isinstance(response, dict):
        return NinaCameraStatus(
            api_online=True,
            error="Response fehlt oder ist ungueltig.",
            camera=None,
        )
    binning = response.get("Binning")
    bin_x = bin_y = None
    if isinstance(binning, dict):
        bx = binning.get("X", binning.get("x"))
        by = binning.get("Y", binning.get("y"))
        try:
            bin_x = int(bx) if bx is not None else None
        except (TypeError, ValueError):
            bin_x = None
        try:
            bin_y = int(by) if by is not None else None
        except (TypeError, ValueError):
            bin_y = None
    else:
        try:
            bin_x = int(response["XBinning"]) if response.get("XBinning") is not None else None
        except (TypeError, ValueError, KeyError):
            bin_x = None
        try:
            bin_y = int(response["YBinning"]) if response.get("YBinning") is not None else None
        except (TypeError, ValueError, KeyError):
            bin_y = None
    camera = CameraInfo(
        connected=_bool(response.get("Connected"), False),
        name=_str(response.get("Name") or response.get("DisplayName")),
        device_id=_str(response.get("DeviceId")),
        exposure_max=_finite(response.get("ExposureMax")),
        exposure_min=_finite(response.get("ExposureMin")),
        exposure_end_time=_str(response.get("ExposureEndTime")),
        is_exposing=_bool(response.get("IsExposing"), False),
        gain=_finite(response.get("Gain")),
        gain_min=_finite(response.get("GainMin")),
        gain_max=_finite(response.get("GainMax")),
        offset=_finite(response.get("Offset")),
        bin_x=bin_x,
        bin_y=bin_y,
        temperature=_finite(response.get("Temperature")),
        cooler_on=_bool(response.get("CoolerOn"), False),
        can_set_gain=_bool(response.get("CanSetGain"), False),
        can_set_offset=_bool(response.get("CanSetOffset"), False),
        can_set_temperature=_bool(response.get("CanSetTemperature"), False),
        battery=_finite(response.get("Battery")),
    )
    return NinaCameraStatus(api_online=True, error="", camera=camera)


def parse_command_payload(payload: Any, *, request: dict[str, Any] | None = None) -> NinaCommandResult:
    if not isinstance(payload, dict):
        return NinaCommandResult(
            ok=False,
            api_online=False,
            error="Antwort ist kein JSON-Objekt.",
            request=request,
        )
    status_code = payload.get("StatusCode")
    try:
        code = int(status_code) if status_code is not None else None
    except (TypeError, ValueError):
        code = None
    success = payload.get("Success")
    error = _str(payload.get("Error"))
    response = payload.get("Response")
    message = response if isinstance(response, str) else _str(response)
    if success is False:
        return NinaCommandResult(
            ok=False,
            api_online=True,
            message=message,
            error=error or "Success=false",
            status_code=code,
            request=request,
        )
    return NinaCommandResult(
        ok=True,
        api_online=True,
        message=message or "OK",
        error="",
        status_code=code if code is not None else 200,
        request=request,
    )


class NinaClient:
    """NINA Advanced API Client (Phase 1 Telemetrie, Phase 2 GoTo/Abort)."""

    def __init__(
        self,
        base_url: str = DEFAULT_BASE_URL,
        *,
        timeout_s: float = DEFAULT_TIMEOUT_S,
        command_timeout_s: float = COMMAND_TIMEOUT_S,
    ) -> None:
        self.base_url = base_url.rstrip("/")
        self.timeout_s = timeout_s
        self.command_timeout_s = command_timeout_s

    def _get(self, path: str, params: dict[str, Any] | None = None, *, timeout_s: float | None = None) -> tuple[int | None, Any, str]:
        """GET path. Returns (http_status, parsed_json_or_None, error)."""
        query = urlencode(params or {}, doseq=True)
        url = f"{self.base_url}{path}"
        if query:
            url = f"{url}?{query}"
        request = Request(url, headers={"Accept": "application/json", "User-Agent": "MeLE-Astro/1.0"})
        try:
            with urlopen(request, timeout=timeout_s if timeout_s is not None else self.timeout_s) as response:
                raw = response.read().decode("utf-8", errors="replace")
                status = getattr(response, "status", 200)
        except HTTPError as exc:
            body = ""
            try:
                body = exc.read().decode("utf-8", errors="replace")
            except Exception:
                pass
            if body:
                try:
                    return exc.code, json.loads(body), ""
                except json.JSONDecodeError:
                    return exc.code, None, f"HTTP {exc.code}"
            return exc.code, None, f"HTTP {exc.code}"
        except URLError as exc:
            reason = getattr(exc, "reason", exc)
            return None, None, f"NINA nicht erreichbar ({reason})"
        except TimeoutError:
            return None, None, "Timeout"
        except OSError as exc:
            return None, None, str(exc) or "Netzwerkfehler"
        try:
            return status, json.loads(raw), ""
        except json.JSONDecodeError:
            return status, None, "Ungueltiges JSON"

    def get_mount_info(self) -> NinaMountStatus:
        code, payload, err = self._get("/equipment/mount/info")
        if err and payload is None:
            return NinaMountStatus(api_online=False, error=err)
        if payload is None:
            return NinaMountStatus(api_online=False, error=err or f"HTTP {code}")
        return parse_mount_payload(payload)

    def slew_to_radec(
        self,
        ra_deg: float,
        dec_deg: float,
        *,
        wait_for_result: bool = False,
    ) -> NinaCommandResult:
        """GoTo: ra/dec in Grad, Epoch J2000 (API). Kein center/rotate."""
        problem = validate_slew_radec_deg(ra_deg, dec_deg)
        request_meta = {
            "path": "/equipment/mount/slew",
            "method": "GET",
            "ra_deg": float(ra_deg) if _finite(ra_deg) is not None else ra_deg,
            "dec_deg": float(dec_deg) if _finite(dec_deg) is not None else dec_deg,
            "waitForResult": bool(wait_for_result),
            "center": False,
            "rotate": False,
            "epoch": "J2000",
            "ra_unit": "degree",
            "dec_unit": "degree",
        }
        if problem:
            return NinaCommandResult(
                ok=False,
                api_online=True,
                error=problem,
                request=request_meta,
            )
        params = {
            "ra": f"{float(ra_deg):.10f}".rstrip("0").rstrip("."),
            "dec": f"{float(dec_deg):.10f}".rstrip("0").rstrip("."),
            "waitForResult": "true" if wait_for_result else "false",
            "center": "false",
            "rotate": "false",
        }
        request_meta["query"] = params
        code, payload, err = self._get(
            "/equipment/mount/slew",
            params,
            timeout_s=self.command_timeout_s,
        )
        if err and payload is None:
            return NinaCommandResult(
                ok=False,
                api_online=False,
                error=err,
                status_code=code,
                request=request_meta,
            )
        if payload is None:
            return NinaCommandResult(
                ok=False,
                api_online=False,
                error=err or f"HTTP {code}",
                status_code=code,
                request=request_meta,
            )
        return parse_command_payload(payload, request=request_meta)

    def abort_slew(self) -> NinaCommandResult:
        request_meta = {
            "path": "/equipment/mount/slew/stop",
            "method": "GET",
            "query": {},
        }
        code, payload, err = self._get(
            "/equipment/mount/slew/stop",
            timeout_s=self.command_timeout_s,
        )
        if err and payload is None:
            return NinaCommandResult(
                ok=False,
                api_online=False,
                error=err,
                status_code=code,
                request=request_meta,
            )
        if payload is None:
            return NinaCommandResult(
                ok=False,
                api_online=False,
                error=err or f"HTTP {code}",
                status_code=code,
                request=request_meta,
            )
        return parse_command_payload(payload, request=request_meta)

    def get_camera_info(self) -> NinaCameraStatus:
        code, payload, err = self._get("/equipment/camera/info")
        if err and payload is None:
            return NinaCameraStatus(api_online=False, error=err)
        if payload is None:
            return NinaCameraStatus(api_online=False, error=err or f"HTTP {code}")
        return parse_camera_payload(payload)

    def change_profile_setting(self, setting_path: str, new_value: str) -> NinaCommandResult:
        """NINA Profilwert setzen (z.B. ImageFileSettings-FilePath)."""
        path = str(setting_path or "").strip()
        value = str(new_value)
        request_meta = {
            "path": "/profile/change-value",
            "method": "GET",
            "settingpath": path,
            "newValue": value,
        }
        if not path:
            return NinaCommandResult(
                ok=False,
                api_online=True,
                error="settingpath fehlt",
                request=request_meta,
            )
        params = {"settingpath": path, "newValue": value}
        request_meta["query"] = params
        code, payload, err = self._get(
            "/profile/change-value",
            params,
            timeout_s=self.command_timeout_s,
        )
        if err and payload is None:
            return NinaCommandResult(
                ok=False,
                api_online=False,
                error=err,
                status_code=code,
                request=request_meta,
            )
        if payload is None:
            return NinaCommandResult(
                ok=False,
                api_online=False,
                error=err or f"HTTP {code}",
                status_code=code,
                request=request_meta,
            )
        return parse_command_payload(payload, request=request_meta)

    def set_image_file_path(self, directory: str | Path) -> NinaCommandResult:
        """Image File Path in NINA Options → Imaging setzen."""
        target = str(Path(directory))
        return self.change_profile_setting("ImageFileSettings-FilePath", target)

    def set_image_file_pattern(self, pattern: str) -> NinaCommandResult:
        """Image File Pattern setzen (unter dem FilePath)."""
        return self.change_profile_setting("ImageFileSettings-FilePattern", str(pattern))

    # MeLE-Capture: FilePath enthaelt bereits Target/Datum/Session —
    # Pattern darf Target/Datum nicht nochmals wiederholen.
    MELE_CAPTURE_FILE_PATTERN = r"$$IMAGETYPE$$\$$DATETIME$$_$$EXPOSURETIME$$s_$$FRAMENR$$"

    def prepare_mele_image_destination(self, directory: str | Path) -> dict[str, NinaCommandResult]:
        """FilePath + schlankes Pattern fuer Session-Ordner setzen."""
        return {
            "path": self.set_image_file_path(directory),
            "pattern": self.set_image_file_pattern(self.MELE_CAPTURE_FILE_PATTERN),
        }

    def sync_snapshot_controls(
        self,
        *,
        exposure_s: float | None = None,
        gain: float | None = None,
    ) -> dict[str, NinaCommandResult]:
        """Imaging-Tab Snapshot-Felder an Session/Profil angleichen (sichtbar in NINA UI)."""
        results: dict[str, NinaCommandResult] = {}
        if exposure_s is not None and _finite(exposure_s) is not None:
            results["exposure"] = self.change_profile_setting(
                "SnapShotControlSettings-ExposureDuration",
                f"{float(exposure_s):.6f}".rstrip("0").rstrip("."),
            )
        if gain is not None and _finite(gain) is not None:
            results["gain"] = self.change_profile_setting(
                "SnapShotControlSettings-Gain",
                f"{float(gain):.6f}".rstrip("0").rstrip("."),
            )
        return results

    def capture(
        self,
        *,
        duration_s: float,
        gain: float | None = None,
        image_type: str = "LIGHT",
        save: bool = True,
        target_name: str = "",
        wait_for_result: bool = False,
        omit_image: bool = True,
        only_await_capture_completion: bool = False,
        skip_auto_stretch: bool = False,
        only_save_raw: bool = False,
    ) -> NinaCommandResult:
        """Ein Frame ueber /equipment/camera/capture (kein Sequencer).

        ``only_await_capture_completion``: HTTP kehrt zurück, sobald die Kamera
        nicht mehr belichtet (IsExposing). Wirkt nur mit ``wait_for_result=False`` —
        bei ``wait_for_result=True`` wartet die API trotzdem auf den kompletten
        CaptureTask inkl. PrepareImage (Debayer/Stretch). Siehe ninaAPI Camera.cs.
        """
        duration = _finite(duration_s)
        request_meta: dict[str, Any] = {
            "path": "/equipment/camera/capture",
            "method": "GET",
            "duration_s": duration,
            "gain": gain,
            "imageType": image_type,
            "save": bool(save),
            "targetName": target_name,
            "waitForResult": bool(wait_for_result),
            "onlyAwaitCaptureCompletion": bool(only_await_capture_completion),
            "skipAutoStretch": bool(skip_auto_stretch),
            "onlySaveRaw": bool(only_save_raw),
        }
        if duration is None or duration < 0:
            return NinaCommandResult(
                ok=False,
                api_online=True,
                error="Belichtung (duration) ungueltig.",
                request=request_meta,
            )
        params: dict[str, Any] = {
            "duration": f"{float(duration):.6f}".rstrip("0").rstrip("."),
            "save": "true" if save else "false",
            "waitForResult": "true" if wait_for_result else "false",
            "omitImage": "true" if omit_image else "false",
            "imageType": str(image_type or "LIGHT").strip() or "LIGHT",
        }
        if only_await_capture_completion:
            params["onlyAwaitCaptureCompletion"] = "true"
        if skip_auto_stretch:
            params["skipAutoStretch"] = "true"
        if only_save_raw:
            params["onlySaveRaw"] = "true"
        if gain is not None and _finite(gain) is not None:
            params["gain"] = f"{float(gain):.6f}".rstrip("0").rstrip(".")
        if target_name.strip():
            params["targetName"] = target_name.strip()
        request_meta["query"] = params
        # onlyAwait hält die HTTP-Verbindung bis Belichtungsende offen —
        # command_timeout_s (3s) wäre sonst zu kurz und killt den Capture.
        timeout = self.command_timeout_s
        if wait_for_result or only_await_capture_completion:
            # Belichtung + Download (+ ggf. PrepareImage, falls IsExposing nicht greift)
            timeout = max(timeout, float(duration) + 180.0)
        request_meta["timeout_s"] = timeout
        code, payload, err = self._get(
            "/equipment/camera/capture",
            params,
            timeout_s=timeout,
        )
        if err and payload is None:
            return NinaCommandResult(
                ok=False,
                api_online=False,
                error=err,
                status_code=code,
                request=request_meta,
            )
        if payload is None:
            return NinaCommandResult(
                ok=False,
                api_online=False,
                error=err or f"HTTP {code}",
                status_code=code,
                request=request_meta,
            )
        return parse_command_payload(payload, request=request_meta)
