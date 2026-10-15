"""Ein einzelnes Bild über die bestehende NINA-Capture-Funktion.

Keine Sessionanlage und keine Serienschleife. Der Capture-Auftrag ruft diese
Funktion pro Bild auf.
"""

from __future__ import annotations

import time
from pathlib import Path
from typing import Any

from mele.astro_manager import (
    FRAME_TYPE_DARK,
    FRAME_TYPE_LIGHT,
    bump_session_capture,
    ensure_capture_dir,
    ensure_session_subdir,
    get_session,
    normalize_frame_type,
    path_under_root,
    resolve_archive_session_dir,
    session_dir_slug,
    suggested_archive_session_dir,
    suggested_local_session_dir,
    update_session_paths,
)
from mele.capture_timing import append_capture_timing
from mele.nina import NinaCommandResult
from mele.preview_service import find_capture_files, wait_for_new_capture_file
from mele.session_storage import LIFECYCLE_CLOSED


def capture_one_frame(
    nina: Any,
    *,
    db_path: Path,
    local_root: Path,
    archive_root: Path,
    session_id: int,
    catalog_key: str,
    display_name: str = "",
    exposure_s: float,
    gain: float | None = None,
    image_type: str = FRAME_TYPE_LIGHT,
    local_path: str = "",
    archive_path: str = "",
    stable_s: float = 0.8,
    poll_s: float = 0.4,
    error_wait_s: float = 40.0,
) -> dict[str, Any]:
    """Ein Frame in eine bestehende Session. Legt keine Session an."""
    kind = normalize_frame_type(image_type)
    existing = get_session(int(session_id), db_path=db_path)
    if existing is None:
        return _fail(404, f"Unbekannte Session: {session_id}", code="session_missing")
    if existing.lifecycle_status == LIFECYCLE_CLOSED:
        return _fail(409, "Session ist geschlossen.", code="session_closed")
    key = str(catalog_key or existing.catalog_key).strip()
    if key and existing.catalog_key != key:
        return _fail(409, "Session gehört nicht zum Objekt.", code="session_mismatch")
    if exposure_s is None or float(exposure_s) < 0:
        return _fail(400, "Belichtung fehlt.", code="params")

    target = str(display_name or "").strip() or key
    sid = int(existing.id)
    canonical_local = str(
        suggested_local_session_dir(
            key,
            local_root=local_root,
            display_name=display_name or None,
            session_id=sid,
        )
    )
    canonical_archive = str(
        suggested_archive_session_dir(
            key,
            archive_root=archive_root,
            display_name=display_name or None,
            session_id=sid,
        )
    )
    body_local = str(local_path or "").strip()
    body_archive = str(archive_path or "").strip()
    existing_local = existing.local_path or ""
    existing_archive = existing.archive_path or ""
    raw_local = body_local or existing_local or canonical_local
    if body_archive:
        raw_archive = body_archive
    elif path_under_root(existing_archive, archive_root):
        raw_archive = existing_archive
    else:
        raw_archive = str(
            resolve_archive_session_dir(existing, archive_root=archive_root)
        )
    session_local = str(ensure_session_subdir(raw_local, sid))
    session_archive = str(ensure_session_subdir(raw_archive, sid))
    capture_local = str(ensure_capture_dir(session_local, sid, frame_type=kind))
    capture_archive = str(ensure_capture_dir(session_archive, sid, frame_type=kind))

    try:
        session = update_session_paths(
            sid,
            local_path=session_local,
            archive_path=session_archive,
            db_path=db_path,
        )
    except Exception as exc:  # noqa: BLE001
        return _fail(500, f"Session-Pfad: {exc}", code="path")

    cam = nina.get_camera_info()
    if not cam.api_online:
        return _fail(502, cam.error or "NINA offline", code="nina", api_online=False)
    if cam.camera is None or not cam.camera.connected:
        return _fail(
            409,
            cam.error or "Kamera in NINA nicht verbunden",
            code="camera",
            api_online=True,
            camera=None if cam.camera is None else cam.camera.to_dict(),
        )

    try:
        Path(capture_local).mkdir(parents=True, exist_ok=True)
    except OSError as exc:
        return _fail(500, f"Lokalpfad nicht anlegbar: {exc}", code="path", local_path=capture_local)

    dest = nina.prepare_mele_image_destination(capture_local)
    if not dest["path"].ok:
        return _fail(
            502,
            dest["path"].error or "NINA Image File Path fehlgeschlagen",
            code="nina",
            local_path=capture_local,
        )
    if not dest["pattern"].ok:
        return _fail(
            502,
            dest["pattern"].error or "NINA File Pattern fehlgeschlagen",
            code="nina",
            local_path=capture_local,
        )

    snap_sync = nina.sync_snapshot_controls(exposure_s=float(exposure_s), gain=gain)
    target_for_nina = f"{target}_{session_dir_slug(sid)}"
    files_before = {str(p) for p in find_capture_files(capture_local)}
    t0 = time.monotonic()
    t_expose_end: float | None = None
    try:
        result = nina.capture(
            duration_s=float(exposure_s),
            gain=gain,
            image_type=kind,
            save=True,
            target_name=target_for_nina,
            wait_for_result=False,
            omit_image=True,
            only_await_capture_completion=True,
            skip_auto_stretch=True,
        )
    except Exception as exc:  # noqa: BLE001
        return _fail(500, str(exc), code="nina")
    t_expose_end = time.monotonic()

    wait_s = min(180.0, max(25.0, float(exposure_s) + 120.0))
    if (not result.ok) and "timeout" not in (result.error or "").lower():
        wait_s = min(float(error_wait_s), wait_s)
    new_capture = wait_for_new_capture_file(
        capture_local,
        before=files_before,
        timeout_s=wait_s,
        min_size_bytes=1024,
        stable_s=stable_s,
        poll_s=poll_s,
    )
    t_file = time.monotonic()
    expose_s = (t_expose_end - t0) if t_expose_end is not None else None
    post_s = (t_file - t_expose_end) if t_expose_end is not None else None
    total_s = t_file - t0

    nina_dl_s = None
    camera_state = None
    try:
        cam_after = nina.get_camera_info()
        if cam_after.camera is not None:
            nina_dl_s = cam_after.camera.last_download_time_s
            camera_state = cam_after.camera.camera_state
    except Exception:  # noqa: BLE001
        pass

    timing_payload: dict | None = None
    try:
        timing_payload = append_capture_timing(
            session_local,
            session_id=sid,
            image_type=kind,
            exposure_planned_s=float(exposure_s),
            expose_s=expose_s,
            post_s=post_s,
            total_s=total_s,
            file_name=new_capture.name if new_capture else None,
            file_path=str(new_capture) if new_capture else None,
            nina_last_download_s=nina_dl_s,
            camera_state=camera_state,
            ok=bool(new_capture is not None),
            note=("" if new_capture else "no_file"),
        )
    except Exception:  # noqa: BLE001
        timing_payload = None

    if new_capture is not None:
        result = NinaCommandResult(
            ok=True,
            api_online=True,
            message=result.message or f"Capture ok ({new_capture.name})",
            error="",
            status_code=200,
            request=result.request,
        )
    elif result.ok:
        result = NinaCommandResult(
            ok=False,
            api_online=True,
            message="",
            error=(
                "Belichtung ok, aber keine neue Datei (FITS/RW2) im Zielordner. "
                f"Timeout {wait_s:.0f}s, Pfad {capture_local}"
            ),
            status_code=504,
            request=result.request,
        )

    warning = ""
    if result.ok:
        try:
            note = str(existing.notes or "")
            if kind == FRAME_TYPE_LIGHT:
                n = int(existing.lights_completed or existing.frames_completed or 0) + 1
                if "Wiederholung" not in note:
                    note = (note + f" | Wiederholung ab Frame {n}").strip(" |")
            session = bump_session_capture(
                sid,
                frames_delta=1,
                frame_type=kind,
                db_path=db_path,
            )
            session = update_session_paths(
                sid,
                local_path=session_local,
                archive_path=session_archive,
                notes=note,
                db_path=db_path,
            )
        except Exception as exc:  # noqa: BLE001
            warning = f"Capture ok, Session-Update fehlgeschlagen: {exc}"

    status = 200 if result.ok else 502
    completed = None
    planned = None
    if session is not None:
        if kind == FRAME_TYPE_DARK:
            completed = session.darks_completed
            planned = session.darks_planned
        else:
            completed = session.lights_completed
            planned = session.lights_planned
    return {
        "ok": bool(result.ok),
        "error": result.error or "",
        "warning": warning,
        "status_code": status,
        "code": "" if result.ok else "capture",
        "file_name": None if new_capture is None else new_capture.name,
        "capture_file": None if new_capture is None else str(new_capture),
        "session": session,
        "session_completed": completed,
        "session_planned": planned,
        "image_type": kind,
        "camera": None if cam.camera is None else cam.camera.to_dict(),
        "local_path": session_local,
        "capture_path": capture_local,
        "archive_capture_path": capture_archive,
        "session_folder": session_dir_slug(sid),
        "destination": {k: v.to_dict() for k, v in dest.items()},
        "snap_sync": {k: v.to_dict() for k, v in snap_sync.items()},
        "timing": None
        if timing_payload is None
        else {
            "expose_s": expose_s,
            "post_s": post_s,
            "total_s": total_s,
            "summary": timing_payload.get("summary"),
            "path": str(Path(session_local) / "capture-timing.json"),
        },
    }


def _fail(
    status: int,
    error: str,
    *,
    code: str,
    api_online: bool | None = None,
    camera: dict | None = None,
    local_path: str = "",
) -> dict[str, Any]:
    body: dict[str, Any] = {
        "ok": False,
        "error": error,
        "warning": "",
        "status_code": status,
        "code": code,
        "file_name": None,
        "capture_file": None,
        "session": None,
        "session_completed": None,
        "session_planned": None,
        "image_type": "",
        "camera": camera,
        "local_path": local_path,
        "capture_path": "",
        "archive_capture_path": "",
        "session_folder": "",
        "destination": None,
        "snap_sync": None,
        "timing": None,
    }
    if api_online is not None:
        body["api_online"] = api_online
    return body
