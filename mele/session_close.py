"""S2: Session schliessen (Idle-Guard + Lifecycle CLOSED + Wetterexport)."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from mele.astro_manager import (
    get_session,
    set_session_lifecycle,
    update_session_storage_fields,
)
from mele.session_idle import IdleCheckResult, check_session_idle
from mele.session_storage import (
    LIFECYCLE_CLOSED,
    WEATHER_EXPORT_UNAVAILABLE,
)
from mele.session_weather import (
    WeatherExportResult,
    export_session_weather_files,
    gap_threshold_from_poll_interval,
)


class SessionCloseError(RuntimeError):
    """Close abgelehnt oder Session unbekannt."""

    def __init__(self, message: str, *, idle: IdleCheckResult | None = None) -> None:
        super().__init__(message)
        self.idle = idle


@dataclass
class SessionCloseResult:
    session: dict[str, Any]
    idle: dict[str, Any]
    weather: dict[str, Any] = field(default_factory=dict)
    already_closed: bool = False

    def to_dict(self) -> dict[str, Any]:
        return {
            "session": self.session,
            "idle": self.idle,
            "weather": self.weather,
            "already_closed": self.already_closed,
        }


def _utc_now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def export_weather_for_session(
    session_id: int,
    *,
    weather_server_url: str,
    poll_interval_s: float = 60.0,
    db_path: Path | None = None,
    require_closed: bool = True,
) -> tuple[Any, WeatherExportResult]:
    """Wetter erneut exportieren. Standard: nur bei CLOSED."""
    session = get_session(session_id, db_path=db_path)
    if session is None:
        raise SessionCloseError(f"Unbekannte Session: {session_id}")
    if require_closed and session.lifecycle_status != LIFECYCLE_CLOSED:
        raise SessionCloseError(
            f"Wetterexport nur bei CLOSED (aktuell: {session.lifecycle_status})"
        )

    start = session.session_start_utc or session.started_utc
    end = session.session_end_utc or session.ended_utc or _utc_now()
    result = export_session_weather_files(
        session_id=session.id,
        session_dir=session.local_path,
        start_utc=start,
        end_utc=end,
        weather_server_url=weather_server_url,
        gap_threshold_s=gap_threshold_from_poll_interval(poll_interval_s),
    )
    updated = update_session_storage_fields(
        session.id,
        weather_export_status=result.export_status,
        db_path=db_path,
    )
    return updated, result


def close_imaging_session(
    session_id: int,
    *,
    nina_client: Any,
    me_capture_inflight: int = 0,
    weather_server_url: str = "",
    poll_interval_s: float = 60.0,
    db_path: Path | None = None,
    skip_idle_check: bool = False,
) -> SessionCloseResult:
    """Idle pruefen → CLOSED → Wetterexport (best effort, Close scheitert nicht an Wetter)."""
    session = get_session(session_id, db_path=db_path)
    if session is None:
        raise SessionCloseError(f"Unbekannte Session: {session_id}")

    if skip_idle_check:
        idle = IdleCheckResult(idle=True, reason="skip_idle_check")
    else:
        idle = check_session_idle(
            nina_client=nina_client,
            me_capture_inflight=me_capture_inflight,
        )
        if not idle.idle:
            raise SessionCloseError(idle.reason or "nicht idle", idle=idle)

    already = session.lifecycle_status == LIFECYCLE_CLOSED
    if not already:
        session = set_session_lifecycle(
            session.id,
            LIFECYCLE_CLOSED,
            session_end_utc=_utc_now(),
            db_path=db_path,
        )

    weather: dict[str, Any] = {}
    if weather_server_url.strip():
        try:
            session, export = export_weather_for_session(
                session.id,
                weather_server_url=weather_server_url,
                poll_interval_s=poll_interval_s,
                db_path=db_path,
                require_closed=True,
            )
            weather = export.to_dict()
        except Exception as exc:  # noqa: BLE001
            # Close bleibt erfolgreich; Status dokumentieren
            session = update_session_storage_fields(
                session.id,
                weather_export_status=WEATHER_EXPORT_UNAVAILABLE,
                db_path=db_path,
            )
            weather = {
                "export_status": WEATHER_EXPORT_UNAVAILABLE,
                "error": str(exc),
            }
    else:
        session = update_session_storage_fields(
            session.id,
            weather_export_status=WEATHER_EXPORT_UNAVAILABLE,
            db_path=db_path,
        )
        weather = {
            "export_status": WEATHER_EXPORT_UNAVAILABLE,
            "error": "weather_server_url fehlt",
        }

    return SessionCloseResult(
        session=session.to_dict(),
        idle=idle.to_dict(),
        weather=weather,
        already_closed=already,
    )
