"""NiceGUI MeLE Astro-Computer."""

from __future__ import annotations

import asyncio
import sys
from collections.abc import Callable
from pathlib import Path
from datetime import datetime, timezone
from urllib.parse import urlencode

from fastapi import Request
from fastapi.responses import HTMLResponse, JSONResponse
from nicegui import app, run, ui

from app_mele.layout import build_ui
from app_mele.state import UiState
from mele.catalog import object_track, query_overlay
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
from mele.nina import NinaClient, validate_slew_radec_deg
from mele.nina_goto_log import save_goto_record
from mele.horizon import (
    SunExclude,
    apply_north,
    detect_horizon,
    detect_horizon_from_samples,
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
    app.add_static_files("/mele-media", preview_dir)
    app.add_static_files("/mele-export", settings.horizon_dir)
    app.add_static_files("/mele-source", settings.media_dir)
    app.add_static_files("/mele-static", Path(__file__).resolve().parent / "static")
    pano_html = (Path(__file__).resolve().parent / "pano.html").read_text(encoding="utf-8")
    nina = NinaClient(settings.nina_base_url)

    @app.get("/pano-view")
    def pano_view() -> HTMLResponse:
        return HTMLResponse(pano_html)

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
        _, width, height, src_w, src_h = ensure_preview(
            image_path, preview_path_for(image_path), settings.preview_width
        )
        crop_sky_preview(preview_path_for(image_path), sky_preview_path_for(image_path))
        return width, height, src_w, src_h

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

    def _find_sun_job(path: Path):
        rgb, src_w, src_h = load_panorama(path)
        return find_sun_excludes(rgb, src_w, src_h)

    def index() -> None:
        state = UiState(
            latitude_deg=settings.latitude_deg,
            longitude_deg=settings.longitude_deg,
            site_src="config" if settings.latitude_deg is not None else "none",
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

        async def on_select_image(name: str) -> None:
            path = settings.media_dir / name
            if not path.is_file():
                ui.notify(f"Nicht gefunden: {name}", type="warning")
                return
            state.image_path = path
            observer = resolve_observer(path, settings)
            stored = load_photo_site(sites_path(settings.horizon_dir), path.stem)
            if stored is not None:
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
                ui.notify(str(exc), type="negative")
                refresh()
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
            ui.timer(0.05, lambda: _call(state.refs.get("refresh_files")), once=True)

        async def on_detect() -> None:
            if state.image_path is None:
                ui.notify("Zuerst ein Panorama waehlen.", type="warning")
                return
            if state.detecting:
                return
            if state.method == "picker" and not state.sky_samples:
                ui.notify("Zuerst Himmelsfarben anklicken.", type="warning")
                return
            path = state.image_path
            state.detecting = True
            state.status = f"Erkenne Horizont: {path.name}"
            refresh_meta()
            ui.notify(f"Erkennung auf {path.name}", type="info")
            try:
                if state.method == "picker":
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
            if state.method == "picker" and is_click:
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
            on_set_site=on_set_site,
            geotagged_fn=geotagged,
            on_gps_upload=on_gps_upload,
            preview_url_fn=preview_url,
        )
        apply_weather_summary()

    ui.run(
        root=index,
        title="MeLE Astro-Computer",
        port=port,
        host="127.0.0.1",
        show=True,
        reload=False,
    )
