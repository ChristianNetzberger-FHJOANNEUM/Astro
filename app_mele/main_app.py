"""NiceGUI MeLE Astro-Computer."""

from __future__ import annotations

import asyncio
import sys
from collections.abc import Callable
from pathlib import Path
from datetime import date, datetime, timezone
from urllib.parse import urlencode

from fastapi import Query, Request
from fastapi.responses import FileResponse, HTMLResponse, JSONResponse
from nicegui import app, run, ui

from app_mele.layout import build_ui
from app_mele.state import UiState
from mele.catalog import object_track, query_overlay
from mele.observe_almanac import (
    build_almanac,
    load_almanac_prefs,
    load_lists_index,
    load_tonight,
    save_almanac_prefs,
    save_tonight,
    set_active_list,
    tonight_markers,
    upsert_list,
)
from mele.solar import (
    next_solar_transit,
    noaa_solar_noon,
    shadow_length,
    solar_diagnostics,
    solar_transit,
    solar_transits_for_year,
    transit_to_dict,
)
from mele.prefs import load_prefs, prefs_path, save_prefs
from mele.config import load_mele_settings, save_site
from mele.observe import gps_from_jpeg, list_location_jpegs, resolve_observer
from mele.shadow_calibration import (
    ShadowCalibrationError,
    calibrate_shadow,
    north_x_from_offset,
    parse_capture_time,
    store_calibration,
)
from mele.sites import load_photo_site, save_photo_site, sites_path
from mele.locations import (
    ensure_default_location,
    get_active_location,
    list_locations,
    set_active_location,
    upsert_location,
)
from mele.weather import WeatherError, load_forecast, weather_dir_for
from mele.weather_journal import (
    SOURCE_ECOWITT,
    SOURCE_GEOSPHERE,
    append_forecast,
    append_observation,
    iter_journal,
    should_skip_forecast,
)
from mele.weather_local import parse_observation_payload
from mele.astro_manager import (
    bump_session_capture,
    create_session,
    delete_profile,
    delete_session,
    ensure_manager_db,
    ensure_session_subdir,
    folder_slug,
    get_profile,
    get_session,
    list_profiles,
    list_sessions,
    object_summary,
    resolve_imaging_params,
    session_dir_slug,
    suggested_archive_session_dir,
    suggested_local_session_dir,
    update_session,
    update_session_paths,
    upsert_profile,
)
from mele.preview_service import (
    PreviewError,
    StretchParams,
    find_latest_focus,
    preview_for_session,
    roi_preview_for_session,
    session_preview_status,
    wait_and_preview,
)
from mele.network import (
    format_wifi_compact,
    format_wifi_tooltip,
    get_wifi_status,
    wifi_quality_class,
)
from mele.synscan import get_synscan_status, start_synscan
from mele.nina_launch import get_nina_app_status, start_nina_app
from mele.nina import NinaClient, validate_slew_radec_deg
from mele.nina_goto_log import save_goto_record
from mele.horizon import (
    SunExclude,
    apply_north,
    detect_horizon,
    detect_horizon_from_samples,
    detect_horizon_hybrid,
    ensure_preview,
    find_sun_excludes,
    load_panorama,
    load_profile,
    profile_belongs_to,
    store_horizon_controls,
    profile_from_manual_points,
    sample_from_preview,
    save_profile,
)
from mele.mask import (
    GROUND,
    SKY,
    crop_sky_preview,
    export_profile_views,
    export_transparent,
    load_mask_png,
    mask_from_profile,
    paint_disk,
    profile_from_alpha,
    save_mask_png,
    write_stellarium_landscape,
)

HIT_RADIUS_PREVIEW = 14.0


def _optional_float_body(value: object) -> float | None:
    if value is None or value == "":
        return None
    try:
        return float(value)  # type: ignore[arg-type]
    except (TypeError, ValueError):
        return None


def _optional_int_body(value: object) -> int | None:
    if value is None or value == "":
        return None
    try:
        return int(float(value))  # type: ignore[arg-type]
    except (TypeError, ValueError):
        return None


def _call(fn: Callable | None) -> None:
    if fn is None:
        return
    try:
        fn()
    except RuntimeError:
        return


def _ignore_win_connection_reset(loop: asyncio.AbstractEventLoop, context: dict) -> None:
    exc = context.get("exception")
    if isinstance(exc, (ConnectionResetError, ConnectionAbortedError)):
        return
    loop.default_exception_handler(context)


def _install_win_reset_handler() -> None:
    """Unterdrueckt WinError 10054/10053 in der Proactor-Loop.

    Windows ruft bei einem hart geschlossenen Browser-Socket shutdown() auf
    einem schon zurueckgesetzten Socket auf. Das ist kein Serverfehler.
    """
    if sys.platform != "win32":
        return
    policy_cls = getattr(asyncio, "WindowsProactorEventLoopPolicy", None)
    if policy_cls is None:
        return

    class _Policy(policy_cls):
        def new_event_loop(self) -> asyncio.AbstractEventLoop:
            loop = super().new_event_loop()
            loop.set_exception_handler(_ignore_win_connection_reset)
            return loop

    asyncio.set_event_loop_policy(_Policy())


def run_app(port: int | None = None) -> None:
    _install_win_reset_handler()
    settings = load_mele_settings()
    if port is None:
        port = settings.ui_port
    preview_dir = settings.horizon_dir / "previews"
    preview_dir.mkdir(parents=True, exist_ok=True)
    settings.horizon_dir.mkdir(parents=True, exist_ok=True)
    settings.gps_dir.mkdir(parents=True, exist_ok=True)
    weather_dir = weather_dir_for(settings.horizon_dir)
    weather_dir.mkdir(parents=True, exist_ok=True)
    weather_html = (Path(__file__).resolve().parent / "weather.html").read_text(encoding="utf-8")
    help_html = (Path(__file__).resolve().parent / "help.html").read_text(encoding="utf-8")
    observe_html = (Path(__file__).resolve().parent / "observe.html").read_text(encoding="utf-8")
    tools_html = (Path(__file__).resolve().parent / "tools.html").read_text(encoding="utf-8")
    app.add_static_files("/mele-media", preview_dir)
    app.add_static_files("/mele-export", settings.horizon_dir)
    app.add_static_files("/mele-source", settings.media_dir)
    app.add_static_files("/mele-static", Path(__file__).resolve().parent / "static")
    pano_html = (Path(__file__).resolve().parent / "pano.html").read_text(encoding="utf-8")
    nina = NinaClient(settings.nina_base_url)
    ensure_manager_db(settings.astro_manager_db)

    @app.get("/pano-view")
    def pano_view() -> HTMLResponse:
        return HTMLResponse(pano_html)

    @app.get("/astro/object/{catalog_key}")
    def astro_object(catalog_key: str, name: str = "") -> JSONResponse:
        """Imaging-Profile + Sessions fuer ein Katalogobjekt (z.B. M31, HIP97649)."""
        try:
            display = name.strip() or None
            summary = object_summary(catalog_key, db_path=settings.astro_manager_db)
            summary["display_name"] = display
            summary["folder_slug"] = folder_slug(catalog_key, display)
            summary["suggested_local_path"] = str(
                suggested_local_session_dir(
                    catalog_key,
                    local_root=settings.local_capture_root,
                    display_name=display,
                )
            )
            summary["suggested_archive_path"] = str(
                suggested_archive_session_dir(
                    catalog_key,
                    archive_root=settings.archive_root,
                    display_name=display,
                )
            )
            summary["local_capture_root"] = str(settings.local_capture_root)
            summary["archive_root"] = str(settings.archive_root)
            return JSONResponse(summary)
        except Exception as exc:  # noqa: BLE001
            return JSONResponse({"error": str(exc), "catalog_key": catalog_key}, status_code=500)

    @app.get("/astro/profiles")
    def astro_profiles_get(catalog_key: str = "") -> JSONResponse:
        if not catalog_key.strip():
            return JSONResponse({"error": "catalog_key fehlt"}, status_code=400)
        rows = list_profiles(catalog_key, db_path=settings.astro_manager_db)
        return JSONResponse({"catalog_key": catalog_key, "profiles": [p.to_dict() for p in rows]})

    @app.post("/astro/profiles")
    async def astro_profiles_post(request: Request) -> JSONResponse:
        try:
            body = await request.json()
        except Exception:
            return JSONResponse({"ok": False, "error": "JSON erwartet"}, status_code=400)
        if not isinstance(body, dict):
            return JSONResponse({"ok": False, "error": "JSON-Objekt erwartet"}, status_code=400)
        try:
            profile = upsert_profile(
                catalog_key=str(body.get("catalog_key") or ""),
                label=str(body.get("label") or ""),
                profile_id=int(body["id"]) if body.get("id") not in (None, "") else None,
                equipment=str(body.get("equipment") or ""),
                exposure_s=_optional_float_body(body.get("exposure_s")),
                gain=_optional_float_body(body.get("gain")),
                iso=_optional_int_body(body.get("iso")),
                offset_adu=_optional_int_body(body.get("offset_adu")),
                binning=str(body.get("binning") or "1x1"),
                filter_name=str(body.get("filter_name") or ""),
                frames=int(body.get("frames") or 1),
                notes=str(body.get("notes") or ""),
                db_path=settings.astro_manager_db,
            )
        except ValueError as exc:
            return JSONResponse({"ok": False, "error": str(exc)}, status_code=400)
        except Exception as exc:  # noqa: BLE001
            return JSONResponse({"ok": False, "error": str(exc)}, status_code=500)
        return JSONResponse({"ok": True, "profile": profile.to_dict()})

    @app.delete("/astro/profiles/{profile_id}")
    def astro_profiles_delete(profile_id: int) -> JSONResponse:
        ok = delete_profile(profile_id, db_path=settings.astro_manager_db)
        return JSONResponse({"ok": ok}, status_code=200 if ok else 404)

    @app.get("/astro/sessions")
    def astro_sessions_get(catalog_key: str = "") -> JSONResponse:
        if not catalog_key.strip():
            return JSONResponse({"error": "catalog_key fehlt"}, status_code=400)
        rows = list_sessions(catalog_key, db_path=settings.astro_manager_db)
        return JSONResponse({"catalog_key": catalog_key, "sessions": [s.to_dict() for s in rows]})

    @app.post("/astro/sessions")
    async def astro_sessions_post(request: Request) -> JSONResponse:
        try:
            body = await request.json()
        except Exception:
            return JSONResponse({"ok": False, "error": "JSON erwartet"}, status_code=400)
        if not isinstance(body, dict):
            return JSONResponse({"ok": False, "error": "JSON-Objekt erwartet"}, status_code=400)
        try:
            session = create_session(
                catalog_key=str(body.get("catalog_key") or ""),
                profile_id=_optional_int_body(body.get("profile_id")),
                started_utc=str(body.get("started_utc") or "") or None,
                frames_planned=_optional_int_body(body.get("frames_planned")),
                frames_completed=int(body.get("frames_completed") or 0),
                exposure_s=_optional_float_body(body.get("exposure_s")),
                gain=_optional_float_body(body.get("gain")),
                iso=_optional_int_body(body.get("iso")),
                offset_adu=_optional_int_body(body.get("offset_adu")),
                binning=str(body.get("binning") or ""),
                filter_name=str(body.get("filter_name") or ""),
                equipment=str(body.get("equipment") or ""),
                local_path="",
                archive_path="",
                archive_status=str(body.get("archive_status") or "local"),
                notes=str(body.get("notes") or ""),
                db_path=settings.astro_manager_db,
                apply_profile=True,
            )
            # Nach ID: kanonische Session-Ordner …/Datum/s#####/
            display = str(body.get("display_name") or "").strip() or None
            local = str(body.get("local_path") or "").strip()
            archive = str(body.get("archive_path") or "").strip()
            if local:
                local_path = str(ensure_session_subdir(local, session.id))
            else:
                local_path = str(
                    suggested_local_session_dir(
                        session.catalog_key,
                        local_root=settings.local_capture_root,
                        display_name=display,
                        session_id=session.id,
                    )
                )
            if archive:
                archive_path = str(ensure_session_subdir(archive, session.id))
            else:
                archive_path = str(
                    suggested_archive_session_dir(
                        session.catalog_key,
                        archive_root=settings.archive_root,
                        display_name=display,
                        session_id=session.id,
                    )
                )
            session = update_session_paths(
                session.id,
                local_path=local_path,
                archive_path=archive_path,
                notes=session.notes,
                db_path=settings.astro_manager_db,
            )
        except ValueError as exc:
            return JSONResponse({"ok": False, "error": str(exc)}, status_code=400)
        except Exception as exc:  # noqa: BLE001
            return JSONResponse({"ok": False, "error": str(exc)}, status_code=500)
        return JSONResponse({"ok": True, "session": session.to_dict()})

    @app.delete("/astro/sessions/{session_id}")
    def astro_sessions_delete(session_id: int) -> JSONResponse:
        ok = delete_session(session_id, db_path=settings.astro_manager_db)
        return JSONResponse({"ok": ok}, status_code=200 if ok else 404)

    @app.put("/astro/sessions/{session_id}")
    async def astro_sessions_put(session_id: int, request: Request) -> JSONResponse:
        """Session bearbeiten (Parameter vor Capture anpassen)."""
        try:
            body = await request.json()
        except Exception:
            return JSONResponse({"ok": False, "error": "JSON erwartet"}, status_code=400)
        if not isinstance(body, dict):
            return JSONResponse({"ok": False, "error": "JSON-Objekt erwartet"}, status_code=400)
        try:
            session = update_session(
                session_id,
                profile_id=_optional_int_body(body.get("profile_id")),
                frames_planned=_optional_int_body(body.get("frames_planned")),
                frames_completed=_optional_int_body(body.get("frames_completed")),
                exposure_s=_optional_float_body(body.get("exposure_s")),
                gain=_optional_float_body(body.get("gain")),
                iso=_optional_int_body(body.get("iso")),
                offset_adu=_optional_int_body(body.get("offset_adu")),
                binning=None if body.get("binning") is None else str(body.get("binning") or ""),
                filter_name=None if body.get("filter_name") is None else str(body.get("filter_name") or ""),
                equipment=None if body.get("equipment") is None else str(body.get("equipment") or ""),
                local_path=(
                    None
                    if body.get("local_path") is None
                    else str(ensure_session_subdir(str(body.get("local_path") or ""), session_id))
                ),
                archive_path=(
                    None
                    if body.get("archive_path") is None
                    else str(ensure_session_subdir(str(body.get("archive_path") or ""), session_id))
                ),
                archive_status=None if body.get("archive_status") is None else str(body.get("archive_status") or ""),
                notes=None if body.get("notes") is None else str(body.get("notes") or ""),
                db_path=settings.astro_manager_db,
            )
        except ValueError as exc:
            return JSONResponse({"ok": False, "error": str(exc)}, status_code=400)
        except Exception as exc:  # noqa: BLE001
            return JSONResponse({"ok": False, "error": str(exc)}, status_code=500)
        return JSONResponse({"ok": True, "session": session.to_dict()})

    def _stretch_params_from_body(body: dict | None) -> StretchParams:
        raw = body if isinstance(body, dict) else {}
        return StretchParams(
            mode=str(raw.get("stretch") or raw.get("mode") or "auto"),
            percentile=float(raw.get("percentile") or 99.5),
            black=_optional_float_body(raw.get("black")),
            white=_optional_float_body(raw.get("white")),
            asinh_a=float(raw.get("asinh_a") or 0.1),
        )

    def _session_preview_payload(session_id: int, result) -> dict:
        mtime = int(result.preview_path.stat().st_mtime) if result.preview_path.is_file() else 0
        kind = getattr(result, "kind", "overview") or "overview"
        if kind == "focus":
            url = f"/astro/sessions/{session_id}/preview/focus/file?v={mtime}"
        else:
            url = f"/astro/sessions/{session_id}/preview/file?v={mtime}"
        return {
            "ok": True,
            "session_id": session_id,
            "preview_url": url,
            **result.to_dict(),
        }

    @app.get("/astro/sessions/{session_id}/preview")
    async def astro_session_preview_get(
        session_id: int,
        generate: bool = Query(True),
    ) -> JSONResponse:
        """Neuestes Session-Preview (bei Bedarf aus FITS erzeugen). FITS unverändert."""
        session = get_session(session_id, db_path=settings.astro_manager_db)
        if session is None:
            return JSONResponse({"ok": False, "error": "Session unbekannt"}, status_code=404)
        local = str(session.local_path or "").strip()
        if not local:
            return JSONResponse({"ok": False, "error": "Session ohne Lokalpfad"}, status_code=400)
        status = session_preview_status(local)
        if not generate:
            return JSONResponse({"ok": True, "session_id": session_id, **status})
        try:
            result = await run.io_bound(lambda: preview_for_session(local, force=False))
        except PreviewError as exc:
            return JSONResponse(
                {"ok": False, "error": str(exc), "session_id": session_id, **status},
                status_code=404,
            )
        except Exception as exc:  # noqa: BLE001
            return JSONResponse({"ok": False, "error": str(exc)}, status_code=500)
        return JSONResponse(_session_preview_payload(session_id, result))

    @app.post("/astro/sessions/{session_id}/preview")
    async def astro_session_preview_post(session_id: int, request: Request) -> JSONResponse:
        """Preview neu stretchen (force). Body: stretch/mode, black, white, percentile."""
        session = get_session(session_id, db_path=settings.astro_manager_db)
        if session is None:
            return JSONResponse({"ok": False, "error": "Session unbekannt"}, status_code=404)
        local = str(session.local_path or "").strip()
        if not local:
            return JSONResponse({"ok": False, "error": "Session ohne Lokalpfad"}, status_code=400)
        try:
            body = await request.json()
        except Exception:
            body = {}
        if not isinstance(body, dict):
            body = {}
        params = _stretch_params_from_body(body)
        force = body.get("force", True)
        if isinstance(force, str):
            force = force.strip().lower() not in ("0", "false", "no")
        try:
            result = await run.io_bound(
                lambda: preview_for_session(local, stretch=params, force=bool(force))
            )
        except PreviewError as exc:
            return JSONResponse({"ok": False, "error": str(exc)}, status_code=404)
        except Exception as exc:  # noqa: BLE001
            return JSONResponse({"ok": False, "error": str(exc)}, status_code=500)
        return JSONResponse(_session_preview_payload(session_id, result))

    @app.get("/astro/sessions/{session_id}/preview/file", response_model=None)
    def astro_session_preview_file(session_id: int):
        """JPEG ausliefern (Cache-Bust via ?v=)."""
        session = get_session(session_id, db_path=settings.astro_manager_db)
        if session is None:
            return JSONResponse({"ok": False, "error": "Session unbekannt"}, status_code=404)
        local = str(session.local_path or "").strip()
        if not local:
            return JSONResponse({"ok": False, "error": "Session ohne Lokalpfad"}, status_code=400)
        status = session_preview_status(local)
        path = status.get("preview_path")
        if not path or not Path(path).is_file():
            return JSONResponse({"ok": False, "error": "Kein Preview"}, status_code=404)
        return FileResponse(
            path,
            media_type="image/jpeg",
            filename=Path(path).name,
        )

    @app.post("/astro/sessions/{session_id}/preview/roi")
    async def astro_session_preview_roi(session_id: int, request: Request) -> JSONResponse:
        """Fokus-ROI aus FITS (volle Auflösung im Ausschnitt, Debayer nur im Crop)."""
        session = get_session(session_id, db_path=settings.astro_manager_db)
        if session is None:
            return JSONResponse({"ok": False, "error": "Session unbekannt"}, status_code=404)
        local = str(session.local_path or "").strip()
        if not local:
            return JSONResponse({"ok": False, "error": "Session ohne Lokalpfad"}, status_code=400)
        try:
            body = await request.json()
        except Exception:
            body = {}
        if not isinstance(body, dict):
            body = {}
        params = _stretch_params_from_body(body)
        scale = float(body.get("scale") or 2.0)
        roi_w = int(body.get("width") or body.get("size") or 512)
        roi_h = int(body.get("height") or body.get("size") or roi_w)
        try:
            result = await run.io_bound(
                lambda: roi_preview_for_session(
                    local,
                    x=_optional_int_body(body.get("x")),
                    y=_optional_int_body(body.get("y")),
                    width=roi_w,
                    height=roi_h,
                    preview_x=_optional_float_body(body.get("preview_x")),
                    preview_y=_optional_float_body(body.get("preview_y")),
                    preview_w=_optional_int_body(body.get("preview_w")),
                    preview_h=_optional_int_body(body.get("preview_h")),
                    display_w=_optional_float_body(body.get("display_w")),
                    display_h=_optional_float_body(body.get("display_h")),
                    stretch=params,
                    scale=scale,
                )
            )
        except PreviewError as exc:
            return JSONResponse({"ok": False, "error": str(exc)}, status_code=404)
        except Exception as exc:  # noqa: BLE001
            return JSONResponse({"ok": False, "error": str(exc)}, status_code=500)
        return JSONResponse(_session_preview_payload(session_id, result))

    @app.get("/astro/sessions/{session_id}/preview/focus/file", response_model=None)
    def astro_session_preview_focus_file(session_id: int):
        """Letztes Fokus-ROI-JPEG ausliefern."""
        session = get_session(session_id, db_path=settings.astro_manager_db)
        if session is None:
            return JSONResponse({"ok": False, "error": "Session unbekannt"}, status_code=404)
        local = str(session.local_path or "").strip()
        if not local:
            return JSONResponse({"ok": False, "error": "Session ohne Lokalpfad"}, status_code=400)
        path = find_latest_focus(local)
        if path is None or not path.is_file():
            return JSONResponse({"ok": False, "error": "Kein Fokus-Preview"}, status_code=404)
        return FileResponse(path, media_type="image/jpeg", filename=path.name)

    @app.post("/astro/nina/capture")
    async def astro_nina_capture(request: Request) -> JSONResponse:
        """Light-Frame: Profil-Defaults, Session-Override, Ordner …/s{id}/, NINA speichern."""
        try:
            body = await request.json()
        except Exception:
            return JSONResponse({"ok": False, "error": "JSON erwartet"}, status_code=400)
        if not isinstance(body, dict):
            return JSONResponse({"ok": False, "error": "JSON-Objekt erwartet"}, status_code=400)

        catalog_key = str(body.get("catalog_key") or "").strip()
        display_name = str(body.get("display_name") or "").strip()
        profile_id = _optional_int_body(body.get("profile_id"))
        exposure_override = _optional_float_body(body.get("exposure_s"))
        gain_override = _optional_float_body(body.get("gain"))
        frames_override = _optional_int_body(body.get("frames"))
        reuse_session_id = _optional_int_body(body.get("session_id"))

        existing = None
        if reuse_session_id is not None:
            existing = get_session(reuse_session_id, db_path=settings.astro_manager_db)
            if existing is None:
                return JSONResponse(
                    {"ok": False, "error": f"Unbekannte Session: {reuse_session_id}"},
                    status_code=404,
                )
            catalog_key = catalog_key or existing.catalog_key
            if profile_id is None:
                profile_id = existing.profile_id

        profile = None
        if profile_id is not None:
            profile = get_profile(profile_id, db_path=settings.astro_manager_db)
            if profile is None:
                return JSONResponse(
                    {"ok": False, "error": f"Unbekanntes Profil: {profile_id}"},
                    status_code=404,
                )
            catalog_key = catalog_key or profile.catalog_key

        params = resolve_imaging_params(
            profile=profile,
            session=existing,
            exposure_s=exposure_override,
            gain=gain_override,
            frames=frames_override,
        )
        exposure_s = params["exposure_s"]
        gain = params["gain"]

        if not catalog_key:
            return JSONResponse({"ok": False, "error": "catalog_key fehlt"}, status_code=400)
        if exposure_s is None or exposure_s < 0:
            return JSONResponse(
                {"ok": False, "error": "Belichtung fehlt (weder Session noch Profil)"},
                status_code=400,
            )

        target = display_name or catalog_key
        # Neue Session zuerst anlegen → echte Session-ID im Ordnerpfad
        session: object | None = existing
        if existing is None:
            try:
                session = create_session(
                    catalog_key=catalog_key,
                    profile_id=profile.id if profile else profile_id,
                    frames_planned=int(params["frames"]),
                    frames_completed=0,
                    exposure_s=float(exposure_s),
                    gain=params.get("gain"),
                    iso=params.get("iso"),
                    binning=str(params.get("binning") or ""),
                    filter_name=str(params.get("filter_name") or ""),
                    equipment=str(params.get("equipment") or ""),
                    local_path="",
                    archive_path="",
                    archive_status="local",
                    notes=f"NINA capture → {target}",
                    db_path=settings.astro_manager_db,
                    apply_profile=True,
                )
            except Exception as exc:  # noqa: BLE001
                return JSONResponse({"ok": False, "error": f"Session anlegen: {exc}"}, status_code=500)

        assert session is not None
        sid = int(session.id)  # type: ignore[attr-defined]

        # Immer kanonisch: …/Target/Datum/s#####/ — alte Pfade ohne s##### nachziehen
        canonical_local = str(
            suggested_local_session_dir(
                catalog_key,
                local_root=settings.local_capture_root,
                display_name=display_name or None,
                session_id=sid,
            )
        )
        canonical_archive = str(
            suggested_archive_session_dir(
                catalog_key,
                archive_root=settings.archive_root,
                display_name=display_name or None,
                session_id=sid,
            )
        )
        body_local = str(body.get("local_path") or "").strip()
        body_archive = str(body.get("archive_path") or "").strip()
        existing_local = (existing.local_path if existing else "") or ""
        existing_archive = (existing.archive_path if existing else "") or ""
        raw_local = body_local or existing_local or canonical_local
        raw_archive = body_archive or existing_archive or canonical_archive
        local_path = str(ensure_session_subdir(raw_local, sid))
        archive_path = str(ensure_session_subdir(raw_archive, sid))

        try:
            session = update_session_paths(
                sid,
                local_path=local_path,
                archive_path=archive_path,
                db_path=settings.astro_manager_db,
            )
        except Exception as exc:  # noqa: BLE001
            return JSONResponse({"ok": False, "error": f"Session-Pfad: {exc}"}, status_code=500)

        cam = nina.get_camera_info()
        if not cam.api_online:
            return JSONResponse(
                {"ok": False, "api_online": False, "error": cam.error or "NINA offline", "camera": None},
                status_code=502,
            )
        if cam.camera is None or not cam.camera.connected:
            return JSONResponse(
                {
                    "ok": False,
                    "api_online": True,
                    "error": cam.error or "Kamera in NINA nicht verbunden",
                    "camera": None if cam.camera is None else cam.camera.to_dict(),
                },
                status_code=409,
            )

        try:
            Path(local_path).mkdir(parents=True, exist_ok=True)
        except OSError as exc:
            return JSONResponse(
                {"ok": False, "error": f"Lokalpfad nicht anlegbar: {exc}", "local_path": local_path},
                status_code=500,
            )

        dest = nina.prepare_mele_image_destination(local_path)
        if not dest["path"].ok:
            return JSONResponse(
                {
                    "ok": False,
                    "error": dest["path"].error or "NINA Image File Path fehlgeschlagen",
                    "destination": {k: v.to_dict() for k, v in dest.items()},
                    "local_path": local_path,
                },
                status_code=502,
            )
        if not dest["pattern"].ok:
            return JSONResponse(
                {
                    "ok": False,
                    "error": dest["pattern"].error or "NINA File Pattern fehlgeschlagen",
                    "destination": {k: v.to_dict() for k, v in dest.items()},
                    "local_path": local_path,
                },
                status_code=502,
            )

        snap_sync = nina.sync_snapshot_controls(exposure_s=float(exposure_s), gain=gain)
        target_for_nina = f"{target}_{session_dir_slug(sid)}"

        try:
            # Auf fertiges Frame warten — sonst liegt noch kein FITS fürs Preview vor
            result = nina.capture(
                duration_s=float(exposure_s),
                gain=gain,
                image_type="LIGHT",
                save=True,
                target_name=target_for_nina,
                wait_for_result=True,
                omit_image=True,
            )
        except Exception as exc:  # noqa: BLE001
            return JSONResponse({"ok": False, "error": str(exc)}, status_code=500)

        if result.ok:
            try:
                if existing is not None:
                    note = str(existing.notes or "")
                    n = int(existing.frames_completed or 0) + 1
                    if "Wiederholung" not in note:
                        note = (note + f" | Wiederholung ab Frame {n}").strip(" |")
                    session = bump_session_capture(
                        sid, frames_delta=1, db_path=settings.astro_manager_db
                    )
                    session = update_session_paths(
                        sid,
                        local_path=local_path,
                        archive_path=archive_path,
                        notes=note,
                        db_path=settings.astro_manager_db,
                    )
                else:
                    session = bump_session_capture(
                        sid, frames_delta=1, db_path=settings.astro_manager_db
                    )
            except Exception as exc:  # noqa: BLE001
                return JSONResponse(
                    {
                        "ok": True,
                        "capture": result.to_dict(),
                        "session": None if session is None else session.to_dict(),  # type: ignore[union-attr]
                        "warning": f"Capture ok, Session-Update fehlgeschlagen: {exc}",
                        "camera": cam.camera.to_dict(),
                        "local_path": local_path,
                    }
                )

        preview_payload: dict | None = None
        preview_error: str | None = None
        if result.ok:
            # NINA kann die Datei kurz nach waitForResult noch finalisieren
            wait_s = min(120.0, max(15.0, float(exposure_s) + 20.0))
            try:
                prev = await run.io_bound(
                    lambda: wait_and_preview(local_path, timeout_s=wait_s, force=True)
                )
                preview_payload = _session_preview_payload(sid, prev)
            except PreviewError as exc:
                preview_error = str(exc)
            except Exception as exc:  # noqa: BLE001
                preview_error = f"Preview fehlgeschlagen: {exc}"

        status = 200 if result.ok else 502
        return JSONResponse(
            {
                "ok": result.ok,
                "capture": result.to_dict(),
                "session": None if session is None else session.to_dict(),  # type: ignore[union-attr]
                "camera": cam.camera.to_dict(),
                "image_file_path": local_path,
                "session_folder": session_dir_slug(sid),
                "resolved_params": params,
                "destination": {k: v.to_dict() for k, v in dest.items()},
                "snap_sync": {k: v.to_dict() for k, v in snap_sync.items()},
                "reused_session": existing is not None,
                "preview": preview_payload,
                "preview_error": preview_error,
                "error": result.error,
                "note": (
                    f"Ordner …/{session_dir_slug(sid)}/; "
                    "Profil-Defaults mit Session-Override; "
                    "Wiederholen bleibt in derselben Session-ID."
                ),
            },
            status_code=status,
        )

    @app.get("/nina/mount")
    def nina_mount() -> JSONResponse:
        """Mount-Telemetrie via NINA Advanced API."""
        try:
            status = nina.get_mount_info()
        except Exception as exc:  # noqa: BLE001 — UI darf nie crashen
            return JSONResponse(
                {"api_online": False, "error": str(exc) or "NinaClient-Fehler", "mount": None}
            )
        return JSONResponse(status.to_dict())

    @app.get("/nina/camera")
    def nina_camera() -> JSONResponse:
        """Kamera-Status via NINA Advanced API."""
        try:
            status = nina.get_camera_info()
        except Exception as exc:  # noqa: BLE001
            return JSONResponse(
                {"api_online": False, "error": str(exc) or "NinaClient-Fehler", "camera": None}
            )
        return JSONResponse(status.to_dict())

    @app.get("/network/wifi")
    def network_wifi() -> JSONResponse:
        """Aktive WLAN-Verbindung / RSSI (Windows Native WiFi). Nie Exception an UI."""
        try:
            status = get_wifi_status()
        except Exception as exc:  # noqa: BLE001
            return JSONResponse(
                {
                    "connected": False,
                    "interface_name": None,
                    "ssid": None,
                    "bssid": None,
                    "rssi_dbm": None,
                    "rssi_source": None,
                    "signal_quality_percent": None,
                    "rx_mbps": None,
                    "tx_mbps": None,
                    "channel": None,
                    "error": str(exc) or "WLAN-Abfrage fehlgeschlagen",
                    "stale": False,
                }
            )
        return JSONResponse(status.to_dict())

    @app.post("/nina/mount/slew")
    def nina_mount_slew(ra: float | None = None, dec: float | None = None) -> JSONResponse:
        """GoTo: RA/Dec in Grad (J2000), waitForResult=false, kein center/rotate.

        Ruft NINA GET /equipment/mount/slew auf. Kein automatischer Retry.
        """
        problem = validate_slew_radec_deg(
            float("nan") if ra is None else float(ra),
            float("nan") if dec is None else float(dec),
        )
        if problem or ra is None or dec is None:
            return JSONResponse(
                {
                    "ok": False,
                    "api_online": True,
                    "message": "",
                    "error": problem or "RA/Dec fehlen.",
                    "status_code": 400,
                    "request": None,
                },
                status_code=400,
            )
        try:
            status = nina.get_mount_info()
        except Exception as exc:  # noqa: BLE001
            return JSONResponse(
                {
                    "ok": False,
                    "api_online": False,
                    "message": "",
                    "error": str(exc) or "Mount-Status nicht lesbar",
                    "status_code": None,
                    "request": None,
                },
                status_code=502,
            )
        if not status.api_online:
            return JSONResponse(
                {
                    "ok": False,
                    "api_online": False,
                    "message": "",
                    "error": status.error or "NINA Offline",
                    "status_code": None,
                    "request": None,
                },
                status_code=502,
            )
        if status.mount is None or not status.mount.connected:
            return JSONResponse(
                {
                    "ok": False,
                    "api_online": True,
                    "message": "",
                    "error": "Mount disconnected",
                    "status_code": 409,
                    "request": None,
                },
                status_code=409,
            )
        if status.mount.at_park:
            return JSONResponse(
                {
                    "ok": False,
                    "api_online": True,
                    "message": "",
                    "error": "Mount parked",
                    "status_code": 409,
                    "request": None,
                },
                status_code=409,
            )
        try:
            result = nina.slew_to_radec(float(ra), float(dec), wait_for_result=False)
        except Exception as exc:  # noqa: BLE001
            return JSONResponse(
                {
                    "ok": False,
                    "api_online": False,
                    "message": "",
                    "error": str(exc) or "Slew-Aufruf fehlgeschlagen",
                    "status_code": None,
                    "request": None,
                },
                status_code=502,
            )
        code = 200 if result.ok else (result.status_code or 502)
        if code < 400:
            code = 200 if result.ok else 502
        return JSONResponse(result.to_dict(), status_code=code if not result.ok else 200)

    @app.post("/nina/mount/slew/stop")
    def nina_mount_slew_stop() -> JSONResponse:
        """Abort: NINA GET /equipment/mount/slew/stop. Unabhaengig vom Slew-HTTP."""
        try:
            result = nina.abort_slew()
        except Exception as exc:  # noqa: BLE001
            return JSONResponse(
                {
                    "ok": False,
                    "api_online": False,
                    "message": "",
                    "error": str(exc) or "Stop fehlgeschlagen",
                    "status_code": None,
                    "request": None,
                },
                status_code=502,
            )
        return JSONResponse(result.to_dict(), status_code=200 if result.ok else (result.status_code or 502))

    @app.post("/nina/goto-log")
    async def nina_goto_log(request: Request) -> JSONResponse:
        """Phase 2b: speichert einen GoTo-Diagnosesatz (JSON + Text + JSONL)."""
        try:
            payload = await request.json()
        except Exception:
            return JSONResponse({"ok": False, "error": "JSON erwartet."}, status_code=400)
        if not isinstance(payload, dict):
            return JSONResponse({"ok": False, "error": "JSON-Objekt erwartet."}, status_code=400)
        try:
            saved = save_goto_record(settings.horizon_dir, payload)
        except Exception as exc:  # noqa: BLE001
            return JSONResponse({"ok": False, "error": str(exc) or "Log fehlgeschlagen"}, status_code=500)
        return JSONResponse(
            {
                "ok": True,
                "request_id": saved.get("request_id"),
                "metrics": saved.get("metrics"),
                "paths": saved.get("paths"),
            }
        )

    @app.get("/weather-view")
    def weather_view() -> HTMLResponse:
        return HTMLResponse(weather_html)

    @app.get("/help-view")
    def help_view() -> HTMLResponse:
        return HTMLResponse(help_html)

    @app.get("/observe-view")
    def observe_view() -> HTMLResponse:
        return HTMLResponse(observe_html)

    @app.get("/tools-view")
    def tools_view() -> HTMLResponse:
        return HTMLResponse(tools_html)

    def _solar_site_args(
        lat: float | None,
        lon: float | None,
        elevation_m: float | None,
        timezone_name: str,
    ) -> tuple[float, float, float, str] | JSONResponse:
        site_lat = lat if lat is not None else settings.latitude_deg
        site_lon = lon if lon is not None else settings.longitude_deg
        if site_lat is None or site_lon is None:
            return JSONResponse({"error": "lat/lon fehlen (Config oder Query)"}, status_code=400)
        elev = float(elevation_m if elevation_m is not None else (settings.elevation_m or 0.0))
        tz = (timezone_name or settings.timezone or "Europe/Vienna").strip() or "Europe/Vienna"
        return float(site_lat), float(site_lon), elev, tz

    @app.get("/solar/status")
    def solar_status(
        lat: float | None = None,
        lon: float | None = None,
        elevation_m: float | None = None,
        timezone_name: str = Query("", alias="timezone"),
    ) -> JSONResponse:
        resolved = _solar_site_args(lat, lon, elevation_m, timezone_name)
        if isinstance(resolved, JSONResponse):
            return resolved
        site_lat, site_lon, elev, tz = resolved
        now = datetime.now(timezone.utc)
        try:
            from zoneinfo import ZoneInfo

            local_now = now.astimezone(ZoneInfo(tz))
            today = solar_transit(local_now.date(), site_lat, site_lon, elev, tz)
            nxt = next_solar_transit(now, site_lat, site_lon, elev, tz)
            today_noaa = noaa_solar_noon(local_now.date(), site_lat, site_lon, elev, tz)
            diag = solar_diagnostics(local_now.date(), site_lat, site_lon, elev, tz)
        except Exception as exc:  # noqa: BLE001
            return JSONResponse({"error": str(exc)}, status_code=500)
        location_label = ""
        for loc in list_locations(settings.horizon_dir):
            if abs(loc.latitude_deg - site_lat) < 1e-5 and abs(loc.longitude_deg - site_lon) < 1e-5:
                location_label = loc.label
                break
        shadow = shadow_length(1.0, float(today.altitude_deg))
        return JSONResponse(
            {
                "latitude_deg": site_lat,
                "longitude_deg": site_lon,
                "elevation_m": elev,
                "timezone": tz,
                "location_label": location_label,
                "now_utc": now.isoformat().replace("+00:00", "Z"),
                "recommended_method": "astropy_hadec_zero",
                "today": transit_to_dict(today),
                "next": transit_to_dict(nxt),
                "noaa_validation": today_noaa,
                "seconds_to_next": max(0.0, (nxt.utc - now).total_seconds()),
                "shadow_length_m_for_1m_pole": None if shadow is None else round(shadow, 3),
                "diagnostics": diag,
            }
        )

    @app.get("/solar/transit")
    def solar_transit_api(
        day: str = "",
        lat: float | None = None,
        lon: float | None = None,
        elevation_m: float | None = None,
        timezone_name: str = Query("", alias="timezone"),
    ) -> JSONResponse:
        resolved = _solar_site_args(lat, lon, elevation_m, timezone_name)
        if isinstance(resolved, JSONResponse):
            return resolved
        site_lat, site_lon, elev, tz = resolved
        try:
            if day:
                stamp = date.fromisoformat(day)
            else:
                from zoneinfo import ZoneInfo

                stamp = datetime.now(timezone.utc).astimezone(ZoneInfo(tz)).date()
            payload = transit_to_dict(solar_transit(stamp, site_lat, site_lon, elev, tz))
        except Exception as exc:  # noqa: BLE001
            return JSONResponse({"error": str(exc)}, status_code=500)
        return JSONResponse(payload)

    @app.get("/solar/transits")
    def solar_transits_api(
        year: int | None = None,
        lat: float | None = None,
        lon: float | None = None,
        elevation_m: float | None = None,
        timezone_name: str = Query("", alias="timezone"),
    ) -> JSONResponse:
        resolved = _solar_site_args(lat, lon, elevation_m, timezone_name)
        if isinstance(resolved, JSONResponse):
            return resolved
        site_lat, site_lon, elev, tz = resolved
        yr = int(year or datetime.now(timezone.utc).year)
        try:
            days = [
                transit_to_dict(item)
                for item in solar_transits_for_year(yr, site_lat, site_lon, elev, tz)
            ]
        except Exception as exc:  # noqa: BLE001
            return JSONResponse({"error": str(exc)}, status_code=500)
        return JSONResponse(
            {
                "year": yr,
                "latitude_deg": site_lat,
                "longitude_deg": site_lon,
                "elevation_m": elev,
                "timezone": tz,
                "days": days,
            }
        )

    @app.get("/observe/almanac")
    def observe_almanac(
        lat: float | None = None,
        lon: float | None = None,
        when: str = "",
        stem: str = "",
        messier: int = 1,
        star_mag: float | None = 3.0,
        min_obs_min: float = 30.0,
        step_min: int = 30,
        tz_offset_min: int | None = None,
    ) -> JSONResponse:
        if lat is None or lon is None:
            return JSONResponse({"error": "lat, lon noetig"}, status_code=400)
        if when:
            stamp = datetime.fromisoformat(when.replace("Z", "+00:00"))
            if stamp.tzinfo is None:
                stamp = stamp.replace(tzinfo=timezone.utc)
        else:
            stamp = datetime.now(timezone.utc)
        profile = None
        if stem:
            json_path = settings.horizon_dir / f"{stem}.horizon.json"
            if json_path.is_file():
                profile = load_profile(json_path)
        star_limit: float | None
        if star_mag is None or star_mag < 0:
            star_limit = None
        else:
            star_limit = float(star_mag)
        try:
            payload = build_almanac(
                latitude_deg=float(lat),
                longitude_deg=float(lon),
                when=stamp,
                profile=profile,
                db_path=settings.catalog_dir / "sky.sqlite",
                messier=bool(messier),
                star_mag_max=star_limit,
                min_observable_min=float(min_obs_min or 0),
                step_min=max(15, min(int(step_min or 30), 60)),
                tz_offset_min=tz_offset_min,
            )
        except Exception as exc:  # noqa: BLE001
            return JSONResponse({"error": str(exc)}, status_code=500)
        payload["stem"] = stem
        return JSONResponse(payload)

    @app.get("/observe/prefs")
    def observe_prefs_get() -> JSONResponse:
        prefs = load_almanac_prefs(settings.horizon_dir)
        index = load_lists_index(settings.horizon_dir)
        return JSONResponse({**prefs, "lists": index.get("lists"), "active": index.get("active")})

    @app.post("/observe/prefs")
    async def observe_prefs_post(request: Request) -> JSONResponse:
        try:
            body = await request.json()
        except Exception:
            return JSONResponse({"ok": False, "error": "JSON erwartet"}, status_code=400)
        if not isinstance(body, dict):
            return JSONResponse({"ok": False, "error": "JSON-Objekt erwartet"}, status_code=400)
        try:
            prefs = save_almanac_prefs(settings.horizon_dir, body)
            index = load_lists_index(settings.horizon_dir)
        except Exception as exc:  # noqa: BLE001
            return JSONResponse({"ok": False, "error": str(exc)}, status_code=500)
        return JSONResponse({"ok": True, **prefs, "lists": index.get("lists"), "active": index.get("active")})

    @app.get("/observe/lists")
    def observe_lists_get() -> JSONResponse:
        return JSONResponse(load_lists_index(settings.horizon_dir))

    @app.post("/observe/lists")
    async def observe_lists_post(request: Request) -> JSONResponse:
        try:
            body = await request.json()
        except Exception:
            return JSONResponse({"ok": False, "error": "JSON erwartet"}, status_code=400)
        if not isinstance(body, dict):
            return JSONResponse({"ok": False, "error": "JSON-Objekt erwartet"}, status_code=400)
        list_id = str(body.get("list_id") or body.get("id") or body.get("label") or "").strip()
        label = str(body.get("label") or list_id).strip()
        if not list_id and not label:
            return JSONResponse({"ok": False, "error": "list_id oder label noetig"}, status_code=400)
        make_active = body.get("make_active", True) not in (False, 0, "0", "false", "False")
        try:
            index = upsert_list(
                settings.horizon_dir,
                list_id=list_id or label,
                label=label or list_id,
                make_active=make_active,
            )
        except Exception as exc:  # noqa: BLE001
            return JSONResponse({"ok": False, "error": str(exc)}, status_code=500)
        return JSONResponse({"ok": True, **index})

    @app.post("/observe/lists/active")
    async def observe_lists_active(request: Request) -> JSONResponse:
        try:
            body = await request.json()
        except Exception:
            return JSONResponse({"ok": False, "error": "JSON erwartet"}, status_code=400)
        if not isinstance(body, dict):
            return JSONResponse({"ok": False, "error": "JSON-Objekt erwartet"}, status_code=400)
        list_id = str(body.get("list_id") or body.get("id") or "").strip()
        if not list_id:
            return JSONResponse({"ok": False, "error": "list_id noetig"}, status_code=400)
        try:
            index = set_active_list(settings.horizon_dir, list_id)
        except ValueError as exc:
            return JSONResponse({"ok": False, "error": str(exc)}, status_code=404)
        except Exception as exc:  # noqa: BLE001
            return JSONResponse({"ok": False, "error": str(exc)}, status_code=500)
        return JSONResponse({"ok": True, **index})

    @app.get("/observe/tonight")
    def observe_tonight_get(stem: str = "", list_id: str = "") -> JSONResponse:
        return JSONResponse(load_tonight(settings.horizon_dir, stem, list_id=list_id or None))

    @app.get("/observe/tonight/markers")
    def observe_tonight_markers(
        lat: float | None = None,
        lon: float | None = None,
        when: str = "",
        stem: str = "",
        list_id: str = "",
    ) -> JSONResponse:
        if lat is None or lon is None:
            return JSONResponse({"error": "lat, lon noetig"}, status_code=400)
        if when:
            stamp = datetime.fromisoformat(when.replace("Z", "+00:00"))
            if stamp.tzinfo is None:
                stamp = stamp.replace(tzinfo=timezone.utc)
        else:
            stamp = datetime.now(timezone.utc)
        profile = None
        if stem:
            json_path = settings.horizon_dir / f"{stem}.horizon.json"
            if json_path.is_file():
                profile = load_profile(json_path)
        try:
            payload = tonight_markers(
                settings.horizon_dir,
                stem=stem,
                list_id=list_id or None,
                latitude_deg=float(lat),
                longitude_deg=float(lon),
                when=stamp,
                profile=profile,
            )
        except Exception as exc:  # noqa: BLE001
            return JSONResponse({"error": str(exc)}, status_code=500)
        return JSONResponse(payload)

    @app.post("/observe/tonight")
    async def observe_tonight_post(request: Request) -> JSONResponse:
        try:
            body = await request.json()
        except Exception:
            return JSONResponse({"ok": False, "error": "JSON erwartet"}, status_code=400)
        if not isinstance(body, dict):
            return JSONResponse({"ok": False, "error": "JSON-Objekt erwartet"}, status_code=400)
        objects = body.get("objects") if isinstance(body.get("objects"), list) else []
        stem = str(body.get("stem") or "")
        list_id = str(body.get("list_id") or "").strip() or None
        label = str(body.get("label") or "").strip()
        when_raw = body.get("when")
        stamp = None
        if when_raw:
            try:
                stamp = datetime.fromisoformat(str(when_raw).replace("Z", "+00:00"))
                if stamp.tzinfo is None:
                    stamp = stamp.replace(tzinfo=timezone.utc)
            except ValueError:
                stamp = None
        lat = body.get("lat")
        lon = body.get("lon")
        try:
            saved = save_tonight(
                settings.horizon_dir,
                objects,
                list_id=list_id,
                label=label,
                stem=stem,
                when=stamp,
                latitude_deg=float(lat) if lat is not None else None,
                longitude_deg=float(lon) if lon is not None else None,
            )
        except Exception as exc:  # noqa: BLE001
            return JSONResponse({"ok": False, "error": str(exc)}, status_code=500)
        return JSONResponse({"ok": True, **saved})

    @app.get("/weather-data")
    def weather_data(lat: float | None = None, lon: float | None = None, refresh: int = 0) -> JSONResponse:
        if lat is None or lon is None:
            return JSONResponse({"error": "lat, lon noetig"}, status_code=400)
        try:
            payload = load_forecast(lat, lon, weather_dir, refresh=bool(refresh), network=True)
        except WeatherError as exc:
            return JSONResponse({"error": str(exc)}, status_code=502)
        if (
            settings.weather_journal_enabled
            and bool(refresh)
            and not payload.get("offline")
            and not should_skip_forecast(
                weather_dir,
                latitude_deg=float(lat),
                longitude_deg=float(lon),
                interval_h=float(settings.weather_journal_interval_h or 1.0),
                source=SOURCE_GEOSPHERE,
            )
        ):
            try:
                append_forecast(
                    weather_dir,
                    payload,
                    latitude_deg=float(lat),
                    longitude_deg=float(lon),
                    label=settings.local_weather_label,
                    source=SOURCE_GEOSPHERE,
                )
            except OSError:
                pass
        return JSONResponse(payload)

    @app.get("/weather/journal")
    def weather_journal_list(kind: str = "", limit: int = 48) -> JSONResponse:
        """Kurze Liste fuer spaeteres Replay (ohne volle hours-Serien)."""
        rows = iter_journal(weather_dir, kind=kind or None)
        slim = []
        for item in rows[-max(1, min(int(limit), 500)) :]:
            forecast = item.get("forecast") or {}
            observation = item.get("observation") or {}
            slim.append(
                {
                    "logged_at": item.get("logged_at"),
                    "kind": item.get("kind"),
                    "source": item.get("source"),
                    "site": item.get("site"),
                    "hour_count": forecast.get("hour_count"),
                    "reference_time": forecast.get("reference_time"),
                    "observation_when": observation.get("when"),
                    "temp_c": observation.get("temp_c"),
                    "humidity_pct": observation.get("humidity_pct"),
                    "wind_ms": observation.get("wind_ms"),
                    "uvi": observation.get("uvi"),
                }
            )
        return JSONResponse({"count": len(slim), "entries": slim})

    def _ingest_observation(payload: dict) -> JSONResponse:
        if not settings.local_weather_enabled:
            return JSONResponse(
                {"ok": False, "error": "local_weather.enabled=false in mele.yaml"},
                status_code=403,
            )
        lat = settings.latitude_deg
        lon = settings.longitude_deg
        try:
            if payload.get("lat") is not None:
                lat = float(payload.get("lat"))
            if payload.get("lon") is not None:
                lon = float(payload.get("lon"))
        except (TypeError, ValueError):
            return JSONResponse({"ok": False, "error": "lat/lon ungueltig"}, status_code=400)
        if lat is None or lon is None:
            return JSONResponse(
                {"ok": False, "error": "Standort lat/lon in mele.yaml setzen"},
                status_code=400,
            )
        try:
            observation = parse_observation_payload(payload)
            source = SOURCE_ECOWITT
            provider = (settings.local_weather_provider or "ecowitt").strip().lower()
            if provider and provider != "ecowitt":
                source = f"{provider}.local"
            record = append_observation(
                weather_dir,
                observation,
                latitude_deg=float(lat),
                longitude_deg=float(lon),
                source=source,
                label=settings.local_weather_label,
            )
        except Exception as exc:  # noqa: BLE001
            return JSONResponse({"ok": False, "error": str(exc)}, status_code=500)
        obs = {k: v for k, v in (record.get("observation") or {}).items() if k != "raw"}
        return JSONResponse({"ok": True, "path": record.get("path"), "observation": obs})

    @app.api_route("/weather/observation", methods=["GET", "POST"])
    async def weather_observation(request: Request) -> JSONResponse:
        """Ecowitt Custom Server / generische lokale Messung -> Journal."""
        payload: dict = {}
        if request.method == "GET":
            payload = dict(request.query_params)
        else:
            content_type = (request.headers.get("content-type") or "").lower()
            try:
                if "application/json" in content_type:
                    body = await request.json()
                    if isinstance(body, dict):
                        payload = body
                else:
                    form = await request.form()
                    payload = {str(k): form.get(k) for k in form.keys()}
            except Exception:
                payload = dict(request.query_params)
        return _ingest_observation(payload)

    @app.get("/sky-overlay")
    def sky_overlay(
        when: str = "",
        lat: float | None = None,
        lon: float | None = None,
        mag: float = 5.5,
        stars: int = 1,
        const: int = 1,
        messier: int = 1,
        ngc: int = 0,
        planets: int = 1,
        dso_types: str = "",
        stem: str = "",
    ) -> JSONResponse:
        if lat is None or lon is None:
            return JSONResponse(
                {
                    "error": "Standort fehlt (EXIF oder configs/mele.yaml).",
                    "stars": [],
                    "lines": [],
                    "labels": [],
                    "dso": [],
                    "bodies": [],
                },
                status_code=400,
            )
        if when:
            stamp = datetime.fromisoformat(when.replace("Z", "+00:00"))
            if stamp.tzinfo is None:
                stamp = stamp.replace(tzinfo=timezone.utc)
        else:
            stamp = datetime.now(timezone.utc)
        profile = None
        if stem:
            json_path = settings.horizon_dir / f"{stem}.horizon.json"
            if json_path.is_file():
                profile = load_profile(json_path)
        type_list = [p.strip() for p in dso_types.replace(";", ",").split(",") if p.strip()] or None
        payload = query_overlay(
            db_path=settings.catalog_dir / "sky.sqlite",
            latitude_deg=lat,
            longitude_deg=lon,
            when=stamp,
            mag_limit=mag,
            stars=bool(stars),
            constellations=bool(const),
            messier=bool(messier),
            ngc=bool(ngc),
            planets=bool(planets),
            dso_types=type_list,
            profile=profile,
        )
        return JSONResponse(payload)

    @app.get("/sky-track")
    def sky_track(
        ra: float | None = None,
        dec: float | None = None,
        lat: float | None = None,
        lon: float | None = None,
        when: str = "",
        stem: str = "",
        tz_offset_min: int | None = None,
    ) -> JSONResponse:
        if ra is None or dec is None or lat is None or lon is None:
            return JSONResponse({"error": "ra, dec, lat, lon noetig"}, status_code=400)
        if when:
            stamp = datetime.fromisoformat(when.replace("Z", "+00:00"))
            if stamp.tzinfo is None:
                stamp = stamp.replace(tzinfo=timezone.utc)
        else:
            stamp = datetime.now(timezone.utc)
        profile = None
        if stem:
            json_path = settings.horizon_dir / f"{stem}.horizon.json"
            if json_path.is_file():
                profile = load_profile(json_path)
        return JSONResponse(
            object_track(
                ra_deg=ra,
                dec_deg=dec,
                latitude_deg=lat,
                longitude_deg=lon,
                when=stamp,
                profile=profile,
                tz_offset_min=tz_offset_min,
            )
        )

    @app.get("/ui-prefs")
    def get_ui_prefs() -> JSONResponse:
        return JSONResponse(load_prefs(prefs_path(settings.horizon_dir)))

    @app.post("/ui-prefs")
    def post_ui_prefs(
        star_scale: float | None = None,
        mag_limit: float | None = None,
        track_hours: int | None = None,
        grid: int | None = None,
        grid_step: int | None = None,
        grid_eq: int | None = None,
        grid_ecliptic: int | None = None,
        horizon_points: int | None = None,
        tonight: int | None = None,
        show_stars: int | None = None,
        show_const: int | None = None,
        show_messier: int | None = None,
        show_ngc: int | None = None,
        show_planets: int | None = None,
        dso_types: str | None = None,
    ) -> JSONResponse:
        updates = {}
        if star_scale is not None:
            updates["star_scale"] = star_scale
        if mag_limit is not None:
            updates["mag_limit"] = mag_limit
        if track_hours is not None:
            updates["track_hours"] = bool(track_hours)
        if grid is not None:
            updates["grid"] = bool(grid)
        if grid_step is not None:
            updates["grid_step"] = grid_step
        if grid_eq is not None:
            updates["grid_eq"] = bool(grid_eq)
        if grid_ecliptic is not None:
            updates["grid_ecliptic"] = bool(grid_ecliptic)
        if horizon_points is not None:
            updates["horizon_points"] = bool(horizon_points)
        if tonight is not None:
            updates["tonight"] = bool(tonight)
        if show_stars is not None:
            updates["show_stars"] = bool(show_stars)
        if show_const is not None:
            updates["show_const"] = bool(show_const)
        if show_messier is not None:
            updates["show_messier"] = bool(show_messier)
        if show_ngc is not None:
            updates["show_ngc"] = bool(show_ngc)
        if show_planets is not None:
            updates["show_planets"] = bool(show_planets)
        if dso_types is not None:
            updates["dso_types"] = [p.strip() for p in dso_types.replace(";", ",").split(",") if p.strip()]
        return JSONResponse(save_prefs(prefs_path(settings.horizon_dir), updates))

    @app.get("/site-coords")
    def get_site_coords(stem: str = "") -> JSONResponse:
        if not stem:
            return JSONResponse({"found": False, "error": "stem fehlt"}, status_code=400)
        record = load_photo_site(sites_path(settings.horizon_dir), stem)
        if record is None:
            return JSONResponse({"found": False, "stem": stem})
        return JSONResponse(
            {
                "found": True,
                "stem": record.stem,
                "latitude_deg": record.latitude_deg,
                "longitude_deg": record.longitude_deg,
                "source": record.source,
            }
        )

    @app.post("/site-coords")
    def post_site_coords(
        stem: str = "",
        lat: float | None = None,
        lon: float | None = None,
        source: str = "pano",
        filename: str = "",
    ) -> JSONResponse:
        if not stem or lat is None or lon is None:
            return JSONResponse({"error": "stem, lat, lon noetig"}, status_code=400)
        record = save_photo_site(
            sites_path(settings.horizon_dir),
            stem,
            lat,
            lon,
            source=source or "pano",
            filename=filename,
        )
        return JSONResponse(
            {
                "ok": True,
                "stem": record.stem,
                "latitude_deg": record.latitude_deg,
                "longitude_deg": record.longitude_deg,
            }
        )

    def _media_for_stem(stem: str) -> Path | None:
        if not stem or any(part in stem for part in ("/", "\\", "..")):
            return None
        if not settings.media_dir.is_dir():
            return None
        matches = [
            path
            for path in settings.media_dir.iterdir()
            if path.is_file() and path.stem == stem and path.suffix.lower() in {".jpg", ".jpeg"}
        ]
        return matches[0] if matches else None

    def _ray(payload: dict, name: str) -> tuple[float, float, float]:
        value = payload.get(name)
        if not isinstance(value, (list, tuple)) or len(value) != 3:
            raise ShadowCalibrationError(f"{name} braucht drei Koordinaten.")
        return float(value[0]), float(value[1]), float(value[2])

    @app.post("/shadow-calibration")
    async def shadow_calibration(request: Request) -> JSONResponse:
        try:
            payload = await request.json()
        except Exception:
            return JSONResponse({"error": "JSON erwartet."}, status_code=400)
        if not isinstance(payload, dict):
            return JSONResponse({"error": "JSON erwartet."}, status_code=400)
        try:
            ray1 = _ray(payload, "ray1")
            ray2 = _ray(payload, "ray2")
            when = parse_capture_time(str(payload.get("when") or ""))
            latitude = float(payload["latitude_deg"])
            longitude = float(payload["longitude_deg"])
            north_offset = float(payload.get("north_offset_deg") or 0.0)
            result = calibrate_shadow(
                ray1=ray1,
                ray2=ray2,
                when=when,
                latitude_deg=latitude,
                longitude_deg=longitude,
                north_offset_deg=north_offset,
            )
        except KeyError:
            return JSONResponse({"error": "Standort fehlt."}, status_code=400)
        except (ShadowCalibrationError, TypeError, ValueError) as exc:
            return JSONResponse({"error": str(exc) or "Kalibrierung ungueltig."}, status_code=400)

        image_width = int(float(payload.get("image_width") or 0))
        north_x = north_x_from_offset(result.north_offset_deg, image_width) if image_width > 0 else None
        body = {
            "sun_azimuth_deg": result.sun_azimuth_deg,
            "sun_altitude_deg": result.sun_altitude_deg,
            "shadow_azimuth_true_deg": result.shadow_azimuth_true_deg,
            "shadow_azimuth_measured_deg": result.shadow_azimuth_measured_deg,
            "panorama_azimuth_offset_deg": result.panorama_azimuth_offset_deg,
            "north_offset_deg": result.north_offset_deg,
            "north_x": north_x,
            "quality": result.quality,
            "warning": result.warning,
            "applied": False,
        }
        if not payload.get("apply"):
            return JSONResponse(body)

        image = _media_for_stem(str(payload.get("stem") or ""))
        if image is None:
            return JSONResponse({"error": "Panorama nicht gefunden."}, status_code=404)
        from PIL import Image

        with Image.open(image) as picture:
            width, height = picture.size
        north_x = north_x_from_offset(result.north_offset_deg, width)
        record = result.as_record(
            latitude_deg=latitude,
            longitude_deg=longitude,
            when=when,
            timezone_name=str(payload.get("timezone") or ""),
            ray1=ray1,
            ray2=ray2,
            north_x=north_x,
        )
        store_calibration(
            settings.horizon_dir,
            image,
            image_width=width,
            image_height=height,
            north_x=north_x,
            record=record,
        )
        body["north_x"] = north_x
        body["applied"] = True
        return JSONResponse(body)

    def _jpeg_size(path: Path) -> tuple[int, int]:
        from PIL import Image

        with Image.open(path) as picture:
            return picture.size

    @app.get("/horizon-controls")
    def get_horizon_controls(stem: str = "") -> JSONResponse:
        image = _media_for_stem(stem)
        if image is None:
            return JSONResponse({"error": "Panorama nicht gefunden."}, status_code=404)
        json_path = settings.horizon_dir / f"{image.stem}.horizon.json"
        if not json_path.is_file():
            width, height = _jpeg_size(image)
            return JSONResponse(
                {"stem": image.stem, "points": [], "image_width": width, "image_height": height}
            )
        profile = load_profile(json_path)
        return JSONResponse(
            {
                "stem": image.stem,
                "points": profile.control_points or [],
                "image_width": profile.image_width,
                "image_height": profile.image_height,
                "profile_points": len(profile.points),
            }
        )

    @app.post("/horizon-controls")
    async def post_horizon_controls(request: Request) -> JSONResponse:
        try:
            payload = await request.json()
        except Exception:
            return JSONResponse({"error": "JSON erwartet."}, status_code=400)
        if not isinstance(payload, dict):
            return JSONResponse({"error": "JSON erwartet."}, status_code=400)
        image = _media_for_stem(str(payload.get("stem") or ""))
        if image is None:
            return JSONResponse({"error": "Panorama nicht gefunden."}, status_code=404)
        raw_points = payload.get("points")
        if not isinstance(raw_points, list):
            return JSONResponse({"error": "Punkte fehlen."}, status_code=400)
        points: list[tuple[float, float]] = []
        for item in raw_points:
            if not isinstance(item, dict):
                return JSONResponse({"error": "Punkt ist ungueltig."}, status_code=400)
            try:
                points.append((float(item["x"]), float(item["y"])))
            except (KeyError, TypeError, ValueError):
                return JSONResponse({"error": "Punkt ist ungueltig."}, status_code=400)
        generate = bool(payload.get("generate"))
        if generate and not points:
            return JSONResponse({"error": "Mindestens einen Horizontpunkt setzen."}, status_code=400)
        width, height = _jpeg_size(image)
        try:
            north_x = float(payload.get("north_x") or 0.0)
        except (TypeError, ValueError):
            return JSONResponse({"error": "north_x ist ungueltig."}, status_code=400)
        try:
            profile = store_horizon_controls(
                settings.horizon_dir,
                image,
                points,
                image_width=width,
                image_height=height,
                north_x=north_x,
                generate=generate,
            )
        except ValueError as exc:
            return JSONResponse({"error": str(exc)}, status_code=400)
        png_url = ""
        if generate and profile.points:
            written = export_profile_views(
                image,
                profile,
                settings.horizon_dir,
                preview_width=settings.preview_width,
            )
            stamp = int(written["full"].stat().st_mtime)
            png_url = f"/mele-export/{written['full'].name}?v={stamp}"
        return JSONResponse(
            {
                "stem": image.stem,
                "saved": len(points),
                "generated": generate,
                "profile_points": len(profile.points),
                "png": png_url,
            }
        )

    def images() -> list[Path]:
        if not settings.media_dir.is_dir():
            return []
        names = []
        for path in sorted(settings.media_dir.iterdir(), key=lambda item: item.name.casefold()):
            if path.is_file() and path.suffix.lower() in {".jpg", ".jpeg"}:
                names.append(path)
        return names

    def preview_path_for(image_path: Path) -> Path:
        return preview_dir / f"{image_path.stem}.preview.jpg"

    def sky_preview_path_for(image_path: Path) -> Path:
        return preview_dir / f"{image_path.stem}.preview.sky.jpg"

    def mask_path_for(image_path: Path) -> Path:
        return settings.horizon_dir / f"{image_path.stem}.horizon.mask.png"

    def _prepare_preview(image_path: Path) -> tuple[int, int, int, int]:
        dest = preview_path_for(image_path)
        sky = sky_preview_path_for(image_path)
        last_exc: OSError | None = None
        for attempt in range(2):
            try:
                _, width, height, src_w, src_h = ensure_preview(
                    image_path, dest, settings.preview_width
                )
                crop_sky_preview(dest, sky)
                return width, height, src_w, src_h
            except OSError as exc:
                last_exc = exc
                # Abgeschnittenes/korruptes Preview löschen und einmal neu erzeugen
                for p in (dest, sky):
                    try:
                        p.unlink(missing_ok=True)
                    except OSError:
                        pass
                if attempt == 0:
                    continue
                raise
        assert last_exc is not None
        raise last_exc

    def _detect_auto(path: Path, north_x: float):
        return detect_horizon(path, north_x=north_x)

    def _detect_picker(path: Path, samples, rejects, excludes, north_x: float, hue_pad: float, sat_pad: float, val_pad: float):
        return detect_horizon_from_samples(
            path,
            samples,
            north_x=north_x,
            hue_pad=hue_pad,
            sat_pad=sat_pad,
            val_pad=val_pad,
            reject=rejects,
            excludes=excludes,
            auto_sun=not excludes,
        )

    def _detect_hybrid(
        path: Path,
        samples,
        rejects,
        excludes,
        floor_profile,
        north_x: float,
        hue_pad: float,
        sat_pad: float,
        val_pad: float,
    ):
        return detect_horizon_hybrid(
            path,
            samples,
            floor_profile,
            north_x=north_x,
            hue_pad=hue_pad,
            sat_pad=sat_pad,
            val_pad=val_pad,
            reject=rejects,
            excludes=excludes,
            auto_sun=not excludes,
        )

    def _find_sun_job(path: Path):
        rgb, src_w, src_h = load_panorama(path)
        return find_sun_excludes(rgb, src_w, src_h)

    def index() -> None:
        ensure_default_location(
            settings.horizon_dir,
            latitude_deg=settings.latitude_deg,
            longitude_deg=settings.longitude_deg,
            elevation_m=float(settings.elevation_m or 0.0),
        )
        active_loc = get_active_location(settings.horizon_dir)
        # Aktiver Listen-Standort ist Session-Default; yaml nur Fallback.
        if active_loc is not None:
            start_lat = active_loc.latitude_deg
            start_lon = active_loc.longitude_deg
            start_src = "location"
        else:
            start_lat = settings.latitude_deg
            start_lon = settings.longitude_deg
            start_src = "config" if settings.latitude_deg is not None else "none"
        state = UiState(
            latitude_deg=start_lat,
            longitude_deg=start_lon,
            site_src=start_src,
        )

        def refresh() -> None:
            _call(state.refs.get("refresh"))

        def refresh_image() -> None:
            _call(state.refs.get("refresh_image"))

        def apply_weather_summary() -> None:
            label = state.refs.get("weather_label")
            if label is None:
                return
            if state.latitude_deg is None or state.longitude_deg is None:
                try:
                    label.text = "Wetter: Standort setzen"
                except RuntimeError:
                    return
                return
            try:
                data = load_forecast(
                    state.latitude_deg,
                    state.longitude_deg,
                    weather_dir,
                    network=False,
                )
                note = " (Cache)" if data.get("stale") or data.get("offline") else ""
                label.text = f"Wetter: {data['summary']['text']}{note}"
            except WeatherError:
                label.text = "Wetter: noch kein Abruf — Seite oeffnen"
            except RuntimeError:
                return

        def refresh_meta() -> None:
            _call(state.refs.get("refresh_meta"))
            apply_weather_summary()

        def preview_url() -> str | None:
            if state.image_path is None:
                return None
            dest = (
                sky_preview_path_for(state.image_path)
                if state.above_horizon
                else preview_path_for(state.image_path)
            )
            if not dest.is_file():
                dest = preview_path_for(state.image_path)
            if not dest.is_file():
                return None
            return f"/mele-media/{dest.name}?v={state.preview_token}"

        def _active_profile():
            if profile_belongs_to(state.profile, state.image_path):
                return state.profile
            return None

        def _ensure_mask() -> None:
            if state.image_path is None or not state.preview_width:
                return
            if state.mask is not None and state.mask.shape == (state.preview_height, state.preview_width):
                return
            loaded = load_mask_png(mask_path_for(state.image_path))
            if loaded is not None:
                state.mask = loaded
                if state.mask.shape != (state.preview_height, state.preview_width):
                    from mele.mask import resize_mask

                    state.mask = resize_mask(state.mask, state.preview_width, state.preview_height)
                return
            profile = _active_profile()
            if profile is not None:
                state.mask = mask_from_profile(profile, state.preview_width, state.preview_height)
            else:
                state.mask = None

        def _persist() -> None:
            if state.image_path is None:
                return
            profile = _active_profile()
            if profile is not None:
                apply_north(profile, state.north_x)
                save_profile(profile, settings.horizon_dir)
            if state.mask is not None:
                save_mask_png(state.mask, mask_path_for(state.image_path))

        def _rebuild_manual() -> None:
            if state.image_path is None or not state.manual_points:
                if state.profile is not None and not profile_belongs_to(state.profile, state.image_path):
                    state.profile = None
                return
            state.profile = profile_from_manual_points(
                state.image_path,
                state.manual_points,
                image_width=state.source_width,
                image_height=state.source_height,
                north_x=state.north_x,
            )
            state.mask = mask_from_profile(state.profile, state.preview_width, state.preview_height)

        def _rebuild_from_mask() -> None:
            if state.image_path is None or state.mask is None:
                return
            state.profile = profile_from_alpha(
                state.image_path,
                state.mask,
                state.source_width,
                state.source_height,
                state.north_x,
            )

        async def on_select_image(name: str, *, keep_site: bool = False) -> None:
            path = settings.media_dir / name
            if not path.is_file():
                ui.notify(f"Nicht gefunden: {name}", type="warning")
                return
            keep_lat = state.latitude_deg
            keep_lon = state.longitude_deg
            keep_src = state.site_src
            state.image_path = path
            observer = resolve_observer(path, settings)
            stored = load_photo_site(sites_path(settings.horizon_dir), path.stem)
            if keep_site and keep_lat is not None and keep_lon is not None:
                state.latitude_deg = keep_lat
                state.longitude_deg = keep_lon
                state.site_src = keep_src or "location"
            elif stored is not None:
                state.latitude_deg = stored.latitude_deg
                state.longitude_deg = stored.longitude_deg
                state.site_src = stored.source or "saved"
            else:
                state.latitude_deg = observer.latitude_deg
                state.longitude_deg = observer.longitude_deg
                state.site_src = observer.site_src
            state.photo_when = observer.photo_when
            state.sky_samples.clear()
            state.reject_samples.clear()
            state.sun_excludes.clear()
            state.manual_points.clear()
            state.mask = None
            state.profile = None
            state.status = f"Lade Vorschau: {name}"
            refresh_meta()
            try:
                width, height, src_w, src_h = await run.io_bound(_prepare_preview, path)
            except OSError as exc:
                state.status = f"Vorschau fehlgeschlagen: {exc}"
                try:
                    ui.notify(str(exc), type="negative")
                except RuntimeError:
                    pass
                try:
                    refresh()
                except RuntimeError:
                    pass
                return
            state.preview_width = width
            state.preview_height = height
            state.source_width = src_w
            state.source_height = src_h
            state.preview_token += 1
            json_path = settings.horizon_dir / f"{path.stem}.horizon.json"
            if json_path.is_file():
                loaded = load_profile(json_path)
                if profile_belongs_to(loaded, path):
                    state.north_x = loaded.north_x
                    if loaded.points:
                        state.profile = loaded
                        state.status = f"{name}  |  Profil geladen"
                    else:
                        state.status = f"{name}  |  Nordkalibrierung geladen"
                else:
                    state.north_x = 0.0
                    state.status = f"{name}  |  {width} x {height} Vorschau"
            else:
                state.north_x = 0.0
                state.status = f"{name}  |  {width} x {height} Vorschau"
            _ensure_mask()
            refresh_image()
            refresh_meta()
            _call(state.refs.get("refresh_files"))

        def _queue_select_image(name: str, *, keep_site: bool = False) -> None:
            # Timer-Callback direkt awaiten (nicht create_task), sonst fehlt der NiceGUI-Slot.
            async def _run() -> None:
                await on_select_image(name, keep_site=keep_site)

            ui.timer(0.05, _run, once=True)

        def _pano_stem_for_save() -> str:
            if state.image_path is None:
                return ""
            return state.image_path.stem

        async def on_detect() -> None:
            if state.image_path is None:
                ui.notify("Zuerst ein Panorama waehlen.", type="warning")
                return
            if state.detecting:
                return
            if state.method in {"picker", "hybrid"} and not state.sky_samples:
                ui.notify("Zuerst Himmelsfarben anklicken.", type="warning")
                return
            floor_profile = None
            if state.method == "hybrid":
                if state.manual_points:
                    try:
                        _rebuild_manual()
                    except ValueError as exc:
                        ui.notify(str(exc), type="negative")
                        return
                floor_profile = _active_profile()
                if floor_profile is None or not floor_profile.points:
                    ui.notify(
                        "Hybrid braucht zuerst eine Floor-Linie (Zeichnen oder Punktwolke generieren).",
                        type="warning",
                    )
                    return
            path = state.image_path
            state.detecting = True
            state.status = f"Erkenne Horizont: {path.name}"
            refresh_meta()
            ui.notify(f"Erkennung auf {path.name}", type="info")
            try:
                if state.method == "hybrid":
                    profile, hybrid_mask = await run.io_bound(
                        _detect_hybrid,
                        path,
                        list(state.sky_samples),
                        list(state.reject_samples),
                        list(state.sun_excludes),
                        floor_profile,
                        state.north_x,
                        state.hue_pad,
                        state.sat_pad,
                        state.val_pad,
                    )
                    if state.image_path != path:
                        return
                    state.profile = profile
                    # Hybrid-Maske auf Vorschau-Groesse
                    if hybrid_mask.shape != (state.preview_height, state.preview_width):
                        from mele.mask import resize_mask

                        state.mask = resize_mask(hybrid_mask, state.preview_width, state.preview_height)
                    else:
                        state.mask = hybrid_mask
                elif state.method == "picker":
                    profile = await run.io_bound(
                        _detect_picker,
                        path,
                        list(state.sky_samples),
                        list(state.reject_samples),
                        list(state.sun_excludes),
                        state.north_x,
                        state.hue_pad,
                        state.sat_pad,
                        state.val_pad,
                    )
                    if state.image_path != path:
                        return
                    state.profile = profile
                    state.mask = mask_from_profile(profile, state.preview_width, state.preview_height)
                else:
                    profile = await run.io_bound(_detect_auto, path, state.north_x)
                    if state.image_path != path:
                        return
                    state.profile = profile
                    state.mask = mask_from_profile(profile, state.preview_width, state.preview_height)
                _persist()
                state.status = f"{path.name}: {len(profile.points)} Punkte, gespeichert"
                ui.notify(f"Horizont fuer {path.name} gespeichert.", type="positive")
            except (OSError, ValueError) as exc:
                state.status = f"Erkennung fehlgeschlagen: {exc}"
                ui.notify(str(exc), type="negative")
            finally:
                state.detecting = False
                refresh_meta()

        def on_save() -> None:
            if state.image_path is None:
                return
            if state.method == "draw" and state.manual_points:
                try:
                    _rebuild_manual()
                except ValueError as exc:
                    ui.notify(str(exc), type="negative")
                    return
            if _active_profile() is None and state.mask is None:
                ui.notify("Zuerst Horizont erkennen, zeichnen oder malen.", type="warning")
                return
            if state.mask is not None and state.method == "brush":
                _rebuild_from_mask()
            _persist()
            state.status = f"Gespeichert: {state.image_path.stem}.horizon.json"
            ui.notify(state.status, type="positive")
            refresh_meta()

        def on_export_transparent() -> None:
            if state.image_path is None:
                return
            _ensure_mask()
            if state.mask is None:
                ui.notify("Keine Maske vorhanden.", type="warning")
                return
            stem = state.image_path.stem
            png = settings.horizon_dir / f"{stem}.horizon.png"
            tif = settings.horizon_dir / f"{stem}.horizon.tif"
            export_transparent(state.image_path, state.mask, png, max_width=settings.preview_width)
            export_transparent(state.image_path, state.mask, tif, max_width=settings.preview_width)
            write_stellarium_landscape(
                settings.horizon_dir / f"{stem}.landscape",
                stem,
                png,
            )
            state.status = f"Export: {png.name}, {tif.name}, Stellarium-landscape"
            ui.notify(state.status, type="positive")
            refresh_meta()

        def on_export_fullres() -> None:
            if state.image_path is None or state.mask is None:
                ui.notify("Keine Maske vorhanden.", type="warning")
                return
            dest = settings.horizon_dir / f"{state.image_path.stem}.horizon.full.png"
            export_transparent(state.image_path, state.mask, dest, max_width=None)
            state.status = f"Vollaufloesung: {dest.name}"
            ui.notify(state.status, type="positive")
            refresh_meta()

        def on_mark_north(preview_x: float, _preview_y: float) -> None:
            if state.image_path is None or not state.preview_width:
                return
            src_w = state.source_width or state.preview_width
            state.north_x = preview_x * src_w / state.preview_width
            if _active_profile() is not None:
                apply_north(state.profile, state.north_x)
            state.status = f"{state.image_path.name}: Norden x = {state.north_x:.0f}"
            ui.notify(state.status, type="positive")
            refresh_meta()

        def on_pointer(
            preview_x: float,
            preview_y: float,
            *,
            is_click: bool,
            buttons: int,
            event_type: str = "",
        ) -> None:
            if state.image_path is None or not state.preview_width:
                return
            if event_type == "mouseup" and state.method == "brush" and state.mask is not None:
                _rebuild_from_mask()
                _persist()
                refresh_meta()
                return
            if state.click_mode == "north" or (state.method == "auto" and is_click):
                if is_click:
                    on_mark_north(preview_x, preview_y)
                return
            if state.method in {"picker", "hybrid"} and is_click:
                src_x = preview_x * state.source_width / state.preview_width
                src_y = preview_y * state.source_height / state.preview_height
                if state.picker_role == "sun":
                    src_r = state.sun_radius_preview * state.source_width / state.preview_width
                    for index, excl in enumerate(state.sun_excludes):
                        if (excl.source_x - src_x) ** 2 + (excl.source_y - src_y) ** 2 <= src_r ** 2:
                            state.sun_excludes.pop(index)
                            state.status = "Sonnen-Exclude entfernt"
                            refresh_meta()
                            return
                    state.sun_excludes.append(
                        SunExclude(
                            source_x=src_x,
                            source_y=src_y,
                            source_radius=src_r,
                            preview_x=preview_x,
                            preview_y=preview_y,
                            preview_radius=state.sun_radius_preview,
                        )
                    )
                    state.status = f"Sonne ausgenommen ({len(state.sun_excludes)})"
                    refresh_meta()
                    return
                dest = preview_path_for(state.image_path)
                try:
                    sample = sample_from_preview(dest, preview_x, preview_y)
                except OSError as exc:
                    ui.notify(str(exc), type="negative")
                    return
                sample.source_x = src_x
                sample.source_y = src_y
                if state.picker_role == "reject":
                    state.reject_samples.append(sample)
                    state.status = (
                        f"Kein Himmel {len(state.reject_samples)}: "
                        f"RGB {sample.r},{sample.g},{sample.b}"
                    )
                else:
                    state.sky_samples.append(sample)
                    state.status = (
                        f"{state.image_path.name} Probe {len(state.sky_samples)}: "
                        f"RGB {sample.r},{sample.g},{sample.b}"
                    )
                refresh_meta()
                return
            if state.method == "draw" and is_click:
                src_x = preview_x * state.source_width / state.preview_width
                src_y = preview_y * state.source_height / state.preview_height
                radius = HIT_RADIUS_PREVIEW * state.source_width / state.preview_width
                for index, (px, py) in enumerate(state.manual_points):
                    if (px - src_x) ** 2 + (py - src_y) ** 2 <= radius ** 2:
                        state.manual_points.pop(index)
                        state.profile = None
                        state.status = f"Punkt entfernt, noch {len(state.manual_points)}"
                        refresh_meta()
                        return
                state.manual_points.append((src_x, src_y))
                state.profile = None
                state.status = f"{len(state.manual_points)} Horizontpunkte"
                refresh_meta()
                return
            if state.method == "brush" and (is_click or (buttons & 1)):
                _ensure_mask()
                if state.mask is None:
                    state.mask = mask_from_profile(
                        _active_profile(), state.preview_width, state.preview_height
                    ) if _active_profile() else None
                if state.mask is None:
                    from mele.mask import empty_mask

                    state.mask = empty_mask(state.preview_height, state.preview_width, GROUND)
                value = GROUND if state.brush_erase else SKY
                paint_disk(state.mask, preview_x, preview_y, state.brush_radius, value)
                if is_click:
                    _rebuild_from_mask()
                    refresh_meta()
                else:
                    _call(state.refs.get("refresh_overlay"))

        def on_clear_samples() -> None:
            state.sky_samples.clear()
            state.status = "Himmelsproben geloescht."
            refresh_meta()

        def on_clear_rejects() -> None:
            state.reject_samples.clear()
            state.status = "Haus/Boden-Proben geloescht."
            refresh_meta()

        def on_clear_suns() -> None:
            state.sun_excludes.clear()
            state.status = "Sonnen-Excludes geloescht."
            refresh_meta()

        async def on_find_sun() -> None:
            if state.image_path is None:
                return
            try:
                found = await run.io_bound(_find_sun_job, state.image_path)
            except OSError as exc:
                ui.notify(str(exc), type="negative")
                return
            if not found:
                ui.notify("Keine Sonne gefunden.", type="warning")
                return
            pw, ph = state.preview_width, state.preview_height
            sw, sh = state.source_width, state.source_height
            state.sun_excludes.clear()
            for excl in found:
                excl.preview_x = excl.source_x * pw / sw
                excl.preview_y = excl.source_y * ph / sh
                excl.preview_radius = excl.source_radius * pw / sw
                state.sun_excludes.append(excl)
            state.status = f"Sonne automatisch: {len(state.sun_excludes)} Bereich(e)"
            refresh_meta()

        def on_undo_point() -> None:
            if state.manual_points:
                state.manual_points.pop()
            state.profile = None
            state.status = f"{len(state.manual_points)} Horizontpunkte"
            refresh_meta()

        def on_clear_points() -> None:
            state.manual_points.clear()
            state.profile = None
            state.status = "Zeichnung geloescht."
            refresh_meta()

        def on_clear_mask() -> None:
            state.mask = None
            if state.image_path is not None:
                mask_file = mask_path_for(state.image_path)
                if mask_file.is_file():
                    mask_file.unlink()
            state.status = "Pinselmaske geloescht."
            refresh_meta()

        def on_toggle_sky_view() -> None:
            state.preview_token += 1
            refresh_image()
            refresh_meta()

        def on_open_pano() -> None:
            if state.image_path is None:
                ui.notify("Zuerst ein Panorama waehlen.", type="warning")
                return
            stem = state.image_path.stem
            preview = f"/mele-media/{stem}.preview.jpg"
            full = settings.horizon_dir / f"{stem}.horizon.full.png"
            small = settings.horizon_dir / f"{stem}.horizon.png"
            png = ""
            chosen = full if full.is_file() else small
            if chosen.is_file():
                png = f"/mele-export/{chosen.name}?v={int(chosen.stat().st_mtime)}"
            original = f"/mele-source/{state.image_path.name}"
            stored = load_photo_site(sites_path(settings.horizon_dir), stem)
            if stored is not None:
                state.latitude_deg = stored.latitude_deg
                state.longitude_deg = stored.longitude_deg
                state.site_src = stored.source or "saved"
            payload = {
                "stem": stem,
                "tex": "png" if png else "preview",
                "preview": preview,
                "png": png,
                "original": original,
                "north": f"{state.north_x:.3f}",
                "srcw": str(state.source_width),
                "srch": str(state.source_height),
                "site": state.site_src,
            }
            if state.latitude_deg is not None and state.longitude_deg is not None:
                payload["lat"] = f"{state.latitude_deg:.6f}"
                payload["lon"] = f"{state.longitude_deg:.6f}"
            if state.photo_when is not None:
                payload["photo"] = state.photo_when.astimezone(timezone.utc).isoformat()
            query = urlencode(payload)
            ui.run_javascript(f"window.open('/pano-view?{query}', '_blank')")

        def on_open_weather() -> None:
            if state.latitude_deg is None or state.longitude_deg is None:
                ui.notify("Zuerst Standort setzen.", type="warning")
                return
            query = urlencode(
                {
                    "lat": f"{state.latitude_deg:.6f}",
                    "lon": f"{state.longitude_deg:.6f}",
                }
            )
            ui.run_javascript(f"window.open('/weather-view?{query}', '_blank')")

        def on_open_help() -> None:
            ui.run_javascript("window.open('/help-view', '_blank')")

        def on_open_observe() -> None:
            if state.latitude_deg is None or state.longitude_deg is None:
                ui.notify("Zuerst Standort setzen.", type="warning")
                return
            payload = {
                "lat": f"{state.latitude_deg:.6f}",
                "lon": f"{state.longitude_deg:.6f}",
            }
            if state.image_path is not None:
                payload["stem"] = state.image_path.stem
            query = urlencode(payload)
            ui.run_javascript(f"window.open('/observe-view?{query}', '_blank')")

        def on_open_tools() -> None:
            if state.latitude_deg is None or state.longitude_deg is None:
                ui.notify("Zuerst Standort im Hauptfenster setzen oder aus der Liste uebernehmen.", type="warning")
                return
            elev = float(settings.elevation_m or 0.0)
            active = get_active_location(settings.horizon_dir)
            loc_label = ""
            if active is not None:
                if (
                    abs(active.latitude_deg - state.latitude_deg) < 1e-5
                    and abs(active.longitude_deg - state.longitude_deg) < 1e-5
                ):
                    loc_label = active.label
                    elev = float(active.elevation_m or elev)
            payload: dict[str, str] = {
                "lat": f"{state.latitude_deg:.6f}",
                "lon": f"{state.longitude_deg:.6f}",
                "elev": f"{elev:.1f}",
                "tz": settings.timezone or "Europe/Vienna",
                "site_src": state.site_src or "",
            }
            if loc_label:
                payload["location"] = loc_label
            query = urlencode(payload)
            ui.run_javascript(f"window.open('/tools-view?{query}', '_blank')")

        def on_set_site(lat: float, lon: float, source: str) -> None:
            state.latitude_deg = lat
            state.longitude_deg = lon
            state.site_src = source
            if state.image_path is not None:
                save_photo_site(
                    sites_path(settings.horizon_dir),
                    state.image_path.stem,
                    lat,
                    lon,
                    source=source,
                    filename=state.image_path.name,
                )
                state.status = (
                    f"Standort {lat:.5f}, {lon:.5f} fuer {state.image_path.stem} gespeichert"
                )
            else:
                settings.latitude_deg = lat
                settings.longitude_deg = lon
                save_site(lat, lon)
                state.status = f"Standard-Standort {lat:.5f}, {lon:.5f} (mele.yaml)"
            refresh_meta()
            ui.notify(state.status, type="positive")

        def locations_list() -> list[tuple[str, str, float, float, str]]:
            return [
                (loc.id, loc.label, loc.latitude_deg, loc.longitude_deg, loc.pano_stem)
                for loc in list_locations(settings.horizon_dir)
            ]

        def active_location_id() -> str:
            active = get_active_location(settings.horizon_dir)
            return active.id if active is not None else ""

        def on_apply_location(location_id: str) -> bool:
            try:
                loc = set_active_location(settings.horizon_dir, location_id)
            except ValueError as exc:
                ui.notify(str(exc), type="warning")
                return False
            on_set_site(loc.latitude_deg, loc.longitude_deg, "location")
            state.status = f"Standort „{loc.label}“ uebernommen"
            if loc.pano_stem:
                media = _media_for_stem(loc.pano_stem)
                if media is not None:
                    _queue_select_image(media.name, keep_site=True)
                else:
                    ui.notify(
                        f"Verknuepftes Panorama „{loc.pano_stem}“ fehlt in media/.",
                        type="warning",
                    )
            return True

        def on_save_location(label: str, lat: float, lon: float) -> bool:
            stem = _pano_stem_for_save()
            loc = upsert_location(
                settings.horizon_dir,
                label=label,
                latitude_deg=lat,
                longitude_deg=lon,
                elevation_m=float(settings.elevation_m or 0.0),
                pano_stem=stem,
                make_active=True,
            )
            on_set_site(lat, lon, "location")
            note = f" + Panorama {stem}" if stem else " (kein Panorama verknuepft — zuerst Foto waehlen)"
            ui.notify(f"Standort „{loc.label}“ gespeichert{note}", type="positive")
            fill = state.refs.get("fill_location_select")
            if callable(fill):
                fill()
            return True

        def geotagged() -> list[tuple[str, float | None, float | None]]:
            return [
                (path.name, lat, lon)
                for path, lat, lon in list_location_jpegs(settings.gps_dir)
            ]

        def on_gps_upload(event) -> None:
            name = getattr(event, "name", None)
            content = getattr(event, "content", None)
            file_obj = getattr(event, "file", None)
            if name is None and file_obj is not None:
                name = getattr(file_obj, "name", None)
            if not name:
                name = "upload.jpg"
            dest = settings.gps_dir / Path(str(name)).name
            settings.gps_dir.mkdir(parents=True, exist_ok=True)
            data = b""
            if content is not None:
                data = content.read() if hasattr(content, "read") else bytes(content)
            elif file_obj is not None and hasattr(file_obj, "read"):
                data = file_obj.read()
            if not data:
                ui.notify("Upload leer.", type="warning")
                return
            dest.write_bytes(data)
            gps = gps_from_jpeg(dest)
            if gps is None:
                ui.notify(
                    f"{dest.name} gespeichert, aber ohne GPS-EXIF. "
                    "Original vom Handy mit aktivierter Ortung kopieren (nicht teilen/exportieren).",
                    type="warning",
                    timeout=8000,
                )
            else:
                on_set_site(gps[0], gps[1], "exif")
                ui.notify(f"GPS aus {dest.name}: {gps[0]:.5f}, {gps[1]:.5f}", type="positive")
            refresh_meta()

        _WIFI_COLORS = {
            "ok": "#5eead4",
            "warn": "#fbbf24",
            "bad": "#fb7185",
            "": "#e2e8f0",
        }

        async def poll_wifi_status() -> None:
            label = state.refs.get("wifi_label")
            if label is None:
                return
            try:
                status = await asyncio.to_thread(get_wifi_status)
            except Exception:  # noqa: BLE001
                return
            text = format_wifi_compact(status)
            tip = format_wifi_tooltip(status)
            color = _WIFI_COLORS.get(wifi_quality_class(status.rssi_dbm), "#e2e8f0")
            if not status.connected and not status.stale:
                color = "#fb7185"
            tip_el = state.refs.get("wifi_tooltip")
            try:
                # Client nach Tab-Close nicht mehr anfassen
                client = getattr(label, "client", None)
                if client is not None and getattr(client, "deleted", False):
                    return
                label.text = text
                label.style(f"color: {color}")
                if tip_el is not None:
                    tip_el.text = tip
                else:
                    label.props(f'title="{tip.replace(chr(34), chr(39))}"')
            except RuntimeError:
                return

        def _set_app_led(ref_key: str, *, running: bool, exe_exists: bool, tip: str) -> None:
            led = state.refs.get(ref_key)
            if led is None:
                return
            color = "#34d399" if running else "#64748b"
            if not exe_exists:
                color = "#f43f5e"
            tip_safe = (
                str(tip)
                .replace("&", "&amp;")
                .replace('"', "&quot;")
                .replace("<", "&lt;")
            )
            html = (
                f'<span title="{tip_safe}" style="display:inline-block;width:0.7em;height:0.7em;'
                f"border-radius:50%;background:{color};"
                'box-shadow:inset 0 0 0 1px rgba(15,23,42,.55);"></span>'
            )
            try:
                led.content = html
            except RuntimeError:
                return
            except AttributeError:
                try:
                    led.set_content(html)
                except Exception:  # noqa: BLE001
                    return

        async def poll_synscan_status() -> None:
            try:
                status = await asyncio.to_thread(get_synscan_status, settings.synscan_pro_exe)
            except Exception:  # noqa: BLE001
                return
            tip = "SynScan Pro laeuft" if status.running else "SynScan Pro nicht gestartet"
            if not status.exe_exists:
                tip = f"SynScanPro.exe fehlt: {status.exe_path}"
            elif status.error:
                tip = status.error
            _set_app_led(
                "synscan_led",
                running=status.running,
                exe_exists=status.exe_exists,
                tip=tip,
            )

        async def poll_nina_app_status() -> None:
            try:
                status = await asyncio.to_thread(get_nina_app_status, settings.nina_exe)
            except Exception:  # noqa: BLE001
                return
            tip = "NINA laeuft" if status.running else "NINA nicht gestartet"
            if not status.exe_exists:
                tip = f"NINA.exe fehlt: {status.exe_path}"
            elif status.error:
                tip = status.error
            _set_app_led(
                "nina_led",
                running=status.running,
                exe_exists=status.exe_exists,
                tip=tip,
            )

        def on_start_synscan() -> None:
            result = start_synscan(settings.synscan_pro_exe)
            if result.ok and result.already_running:
                ui.notify("SynScan Pro laeuft bereits.", type="info")
            elif result.ok:
                ui.notify("SynScan Pro gestartet.", type="positive")
            else:
                ui.notify(result.error or "SynScan-Start fehlgeschlagen", type="negative")
            ui.timer(0.4, poll_synscan_status, once=True)

        def on_start_nina() -> None:
            result = start_nina_app(settings.nina_exe)
            if result.ok and result.already_running:
                ui.notify("NINA laeuft bereits.", type="info")
            elif result.ok:
                ui.notify("NINA gestartet.", type="positive")
            else:
                ui.notify(result.error or "NINA-Start fehlgeschlagen", type="negative")
            ui.timer(0.4, poll_nina_app_status, once=True)

        build_ui(
            state=state,
            media_dir=settings.media_dir,
            images_fn=images,
            on_select_image=on_select_image,
            on_detect=on_detect,
            on_save=on_save,
            on_pointer=on_pointer,
            on_clear_samples=on_clear_samples,
            on_clear_rejects=on_clear_rejects,
            on_clear_suns=on_clear_suns,
            on_find_sun=on_find_sun,
            on_undo_point=on_undo_point,
            on_clear_points=on_clear_points,
            on_clear_mask=on_clear_mask,
            on_export_transparent=on_export_transparent,
            on_export_fullres=on_export_fullres,
            on_toggle_sky_view=on_toggle_sky_view,
            on_open_pano=on_open_pano,
            on_open_weather=on_open_weather,
            on_open_help=on_open_help,
            on_open_observe=on_open_observe,
            on_open_tools=on_open_tools,
            on_set_site=on_set_site,
            on_start_synscan=on_start_synscan,
            on_start_nina=on_start_nina,
            locations_fn=locations_list,
            active_location_id_fn=active_location_id,
            on_apply_location=on_apply_location,
            on_save_location=on_save_location,
            geotagged_fn=geotagged,
            on_gps_upload=on_gps_upload,
            preview_url_fn=preview_url,
        )
        apply_weather_summary()
        ui.timer(0.1, poll_wifi_status, once=True)
        ui.timer(5.0, poll_wifi_status)
        ui.timer(0.2, poll_synscan_status, once=True)
        ui.timer(3.0, poll_synscan_status)
        ui.timer(0.3, poll_nina_app_status, once=True)
        ui.timer(3.0, poll_nina_app_status)
        # Default-Standort: verknuepftes 360-Panorama beim Session-Start laden
        if active_loc is not None and active_loc.pano_stem:
            media = _media_for_stem(active_loc.pano_stem)
            if media is not None:
                _queue_select_image(media.name, keep_site=True)

    ui.run(
        root=index,
        title="MeLE Astro-Computer",
        port=port,
        host=settings.ui_host,
        show=True,
        reload=False,
    )
