"""S2: Idle-Pruefung vor Session-CLOSE (NINA + MeLE-Capture).

IsExposing=false allein reicht nicht. Unklarer Zustand → Close verweigern.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Protocol

# Kamera-Zustaende, die auf laufende Aufnahme/Download hindeuten (ASCOM-/NINA-aehnlich)
_BUSY_CAMERA_STATES = frozenset(
    {
        "exposing",
        "exposure",
        "download",
        "downloading",
        "waitingforsave",
        "waiting_for_save",
        "reading",
        "busy",
    }
)


class SupportsCameraInfo(Protocol):
    def get_camera_info(self) -> Any: ...


@dataclass(frozen=True)
class IdleCheckResult:
    idle: bool
    reason: str = ""
    me_capture_inflight: int = 0
    nina_api_online: bool | None = None
    is_exposing: bool | None = None
    camera_state: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "idle": self.idle,
            "reason": self.reason,
            "me_capture_inflight": self.me_capture_inflight,
            "nina_api_online": self.nina_api_online,
            "is_exposing": self.is_exposing,
            "camera_state": self.camera_state,
        }


def check_session_idle(
    *,
    nina_client: SupportsCameraInfo | None,
    me_capture_inflight: int = 0,
) -> IdleCheckResult:
    """True nur wenn sicher kein Capture laeuft. Unklar → idle=False."""
    inflight = max(0, int(me_capture_inflight or 0))
    if inflight > 0:
        return IdleCheckResult(
            idle=False,
            reason=f"MeLE-Capture laeuft ({inflight})",
            me_capture_inflight=inflight,
        )

    if nina_client is None:
        return IdleCheckResult(
            idle=False,
            reason="NINA-Client fehlt — Zustand unklar",
            me_capture_inflight=0,
        )

    try:
        status = nina_client.get_camera_info()
    except Exception as exc:  # noqa: BLE001
        return IdleCheckResult(
            idle=False,
            reason=f"NINA Kamera-Status nicht lesbar: {exc}",
            me_capture_inflight=0,
            nina_api_online=False,
        )

    api_online = bool(getattr(status, "api_online", False))
    if not api_online:
        err = str(getattr(status, "error", "") or "API offline")
        return IdleCheckResult(
            idle=False,
            reason=f"NINA API nicht erreichbar ({err}) — Zustand unklar",
            me_capture_inflight=0,
            nina_api_online=False,
        )

    camera = getattr(status, "camera", None)
    if camera is None:
        return IdleCheckResult(
            idle=False,
            reason="Kamerastatus unklar (kein camera-Objekt)",
            me_capture_inflight=0,
            nina_api_online=True,
        )

    is_exposing = bool(getattr(camera, "is_exposing", False))
    cam_state = str(getattr(camera, "camera_state", "") or "").strip()
    state_norm = cam_state.lower().replace(" ", "")

    if is_exposing:
        return IdleCheckResult(
            idle=False,
            reason="NINA belichtet (IsExposing=true)",
            me_capture_inflight=0,
            nina_api_online=True,
            is_exposing=True,
            camera_state=cam_state,
        )

    if state_norm in _BUSY_CAMERA_STATES:
        return IdleCheckResult(
            idle=False,
            reason=f"NINA CameraState={cam_state!r} — Sequenz/Download aktiv",
            me_capture_inflight=0,
            nina_api_online=True,
            is_exposing=False,
            camera_state=cam_state,
        )

    return IdleCheckResult(
        idle=True,
        reason="",
        me_capture_inflight=0,
        nina_api_online=True,
        is_exposing=False,
        camera_state=cam_state,
    )
