"""Quest-Kameratafel: Kontext, Sperre, Caddy. Keine reale Kamera."""

from __future__ import annotations

from pathlib import Path

import pytest
from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse
from fastapi.testclient import TestClient

from mele.astro_manager import (
    SessionCreateError,
    create_object_session,
    create_session,
    ensure_manager_db,
    upsert_profile,
)
from mele.capture_job import (
    STATE_RUNNING,
    CaptureFrameResult,
    CaptureJobService,
    exposure_steps,
    install_capture_routes,
)


def _db(tmp_path: Path) -> Path:
    path = tmp_path / "astro_manager.sqlite"
    ensure_manager_db(path)
    return path


def _service(db: Path) -> CaptureJobService:
    return CaptureJobService(db_path=db, capture_one=lambda snapshot: CaptureFrameResult(ok=True, file_name="a.rw2"))


def test_exposure_steps_follow_camera_bounds() -> None:
    assert 0.5 in exposure_steps(0, 0)
    bounded = exposure_steps(2, 30)
    assert 0.5 not in bounded
    assert 2.0 in bounded
    assert 30.0 in bounded
    assert 45.0 not in bounded


def test_context_adopts_one_session_and_does_not_invent_iso(tmp_path: Path) -> None:
    db = _db(tmp_path)
    profile = upsert_profile(
        catalog_key="M31",
        label="Test",
        exposure_s=30,
        gain=200,
        iso=640,
        frames=12,
        db_path=db,
    )
    session = create_session(
        catalog_key="M31",
        profile_id=profile.id,
        lights_planned=12,
        exposure_s=20,
        gain=200,
        iso=640,
        db_path=db,
    )
    service = _service(db)
    body = service.context("M31", {"api_online": True, "camera": {"connected": True, "exposure_min": 1, "exposure_max": 60}})
    assert body["session_code"] == "ok"
    assert body["session"]["id"] == session.id
    assert body["session"]["darks_completed"] == 0
    assert "darks_planned" in body["session"]
    assert body["profile"]["id"] == profile.id
    assert body["profile"]["exposure_s"] == 30
    assert body["iso_steps"] == [640]
    assert body["iso_adjustable"] is False
    assert body["locked"] is False
    assert 1.0 in body["exposure_steps_s"]
    assert 90.0 not in body["exposure_steps_s"]


def test_ambiguous_session_is_not_chosen(tmp_path: Path) -> None:
    db = _db(tmp_path)
    create_session(catalog_key="M31", lights_planned=2, exposure_s=10, db_path=db)
    create_session(catalog_key="M31", lights_planned=3, exposure_s=10, db_path=db)
    body = _service(db).context("M31", {"api_online": True, "camera": {"connected": False}})
    assert body["session_code"] == "session_ambiguous"
    assert body["session"] is None
    assert len(body["sessions"]) == 2


def test_running_job_is_the_displayed_source(tmp_path: Path) -> None:
    import threading

    db = _db(tmp_path)
    session = create_session(catalog_key="M31", lights_planned=4, exposure_s=15, iso=200, db_path=db)
    entered = threading.Event()
    release = threading.Event()

    def blocking(snapshot):
        entered.set()
        assert release.wait(timeout=5)
        return CaptureFrameResult(ok=True, file_name="job.rw2", session_completed=1)

    service = CaptureJobService(db_path=db, capture_one=blocking)
    status, _body = service.start_from_body({"catalog_key": "M31", "session_id": session.id, "frames": 2, "exposure_s": 15})
    assert status == 200
    assert entered.wait(timeout=5)
    view = service.context("M42", {"api_online": True, "camera": {"connected": True, "name": "Lumix"}})
    assert view["locked"] is True
    assert view["session_code"] == "job"
    assert view["job"]["state"] == STATE_RUNNING
    assert view["job"]["catalog_key"] == "M31"
    assert view["job"]["exposure_s"] == 15
    assert view["profile"] is None
    release.set()


def test_quest_write_requires_the_mount_gate(tmp_path: Path) -> None:
    db = _db(tmp_path)
    session = create_session(catalog_key="M31", lights_planned=1, exposure_s=1, db_path=db)
    service = _service(db)
    app = FastAPI()

    def gate(request: Request):
        if request.headers.get("x-astro-csrf") == "ok":
            return None
        return JSONResponse({"ok": False, "error": "Keine Montierungsberechtigung"}, status_code=401)

    install_capture_routes(app, service, gate=gate, camera_info=lambda: {"api_online": True, "camera": {"connected": False}})
    with TestClient(app) as client:
        assert client.get("/astro/capture/context").status_code == 200
        assert client.get("/astro/capture/status").json()["state"] == "idle"
        denied = client.post("/astro/capture/start", json={"catalog_key": "M31", "session_id": session.id, "frames": 1})
        assert denied.status_code == 401
        stopped = client.post("/astro/capture/stop")
        assert stopped.status_code == 401
        closed = client.post("/astro/capture/session-close", json={"session_id": session.id})
        assert closed.status_code == 401


def test_session_close_route_returns_the_weather_result(tmp_path: Path) -> None:
    db = _db(tmp_path)
    service = _service(db)
    app = FastAPI()
    seen: dict[str, int] = {}

    def close_session(session_id: int) -> tuple[int, dict]:
        seen["id"] = session_id
        return 200, {
            "ok": True,
            "session": {"id": session_id, "lifecycle_status": "closed"},
            "weather": {"export_status": "ok", "sample_count": 4},
        }

    install_capture_routes(
        app,
        service,
        camera_info=lambda: {"api_online": True, "camera": {"connected": False}},
        close_session=close_session,
    )
    with TestClient(app) as client:
        response = client.post("/astro/capture/session-close", json={"session_id": 12})
    assert response.status_code == 200
    body = response.json()
    assert seen["id"] == 12
    assert body["weather"]["export_status"] == "ok"
    assert body["session"]["lifecycle_status"] == "closed"


def test_vr_camera_panel_reuses_the_job_and_leaves_the_mount_bindings() -> None:
    page = Path("app_mele/vr.html").read_text(encoding="utf-8")
    assert 'makeTextButton("KAMERA"' in page
    assert "/astro/capture/context" in page
    assert "catalogQueryOf(selectedItem)" in page
    assert "encodeURIComponent(selectedKey)" not in page
    assert "/astro/sessions" in page
    assert "session-pick" in page
    assert "Session erstellt" in page
    assert "＋ NEUE SESSION" in page
    assert "/astro/capture/start" in page
    assert "/astro/capture/stop" in page
    assert "cam-start" in page
    assert "slider" not in page.lower()
    assert "ISO fest vom Profil." in page
    assert "iso_adjustable" in page
    assert "cameraDraft.gain = cameraDraft.iso" in page
    assert 'makeTextButton("LIGHTS"' in page
    assert 'makeTextButton("DARKS"' in page
    assert 'makeTextButton("TUBUS ABGEDECKT"' in page
    assert "selectFrameType" in page
    assert "cameraDraft.dark_frames" in page
    assert "savedSessionRow" in page
    assert "showSessionView" in page
    assert 'makeTextButton("MONITOR", "session-monitor"' in page
    assert 'panelMode === "session-view"' in page
    closed = page[page.index('hit.userData.action === "session-pick"'):page.index('hit.userData.action === "session-profile"')]
    assert "showSessionView" in closed
    assert "showCamera" not in closed.split("return;")[0]
    assert "/astro/capture/session-close" in page
    assert "closeCameraSession" in page
    assert "HIMMELSPUNKT" in page
    assert "quest-stop" in page
    assert "controlRoles" in page
    caddy = Path(r"C:\Caddy\Caddyfile").read_text(encoding="utf-8")
    read = caddy[caddy.index("@camera_read"):caddy.index("handle @camera_read")]
    assert "/astro/capture/status" in read and "/astro/capture/context" in read
    assert "/astro/capture/preview" in read and "/astro/capture/preview/file" in read
    control = caddy[caddy.index("@camera_control"):caddy.index("handle @camera_control")]
    assert "/astro/capture/start" in control and "/astro/capture/stop" in control
    assert "/astro/capture/session-close" in control
    assert "/nina/" not in control
    assert "path /astro " not in caddy
    assert "path /nina " not in caddy
    session_read = caddy[caddy.index("@session_read"):caddy.index("handle @session_read")]
    assert "/astro/sessions" in session_read
    assert "/astro/imaging-model" in session_read
    session_handle = caddy[caddy.index("handle @session_control"):caddy.index("handle @session_control") + 280]
    assert "X-Astro-Edge" in session_handle
    phd2_read = caddy[caddy.index("@phd2_read"):caddy.index("handle @phd2_read")]
    assert "/phd2/status" in phd2_read and "/phd2/exposures" in phd2_read
    phd2_control = caddy[caddy.index("@phd2_control"):caddy.index("handle @phd2_control")]
    assert "/phd2/loop" in phd2_control and "/phd2/guide" in phd2_control and "/phd2/stop" in phd2_control
    assert "/phd2/image" not in phd2_control
    assert 'makeTextButton("GUIDING", "guide-open"' in page
    assert 'makeTextButton("NEU", "guide-recal"' in page
    assert "panelMode === \"guide\"" in page
    assert "alert_msg" in page
    guide_start = page[page.index('action === "guide-start"'):page.index('action === "guide-pause"')]
    assert "recalibrate: false" in guide_start
    assert "selectedItem" not in guide_start
    guide_recal = page[page.index('action === "guide-recal"'):page.index('action === "guide-pause"')]
    assert "recalibrate: true" in guide_recal
    assert "selectedItem" not in guide_recal
    leave = page[page.index("function leaveGuide"):page.index("function showCamera")]
    assert "/phd2/stop" not in leave
    assert "fetch(" not in leave


def test_dashboard_closes_only_through_its_own_button() -> None:
    page = Path("app_mele/vr.html").read_text(encoding="utf-8")
    buttons = page[page.index("const pointerButtons"):page.index("let overlayStateText")]
    assert "dragHandle," in buttons
    assert "closeButton," in buttons
    assert 'makeTextButton("SCHLIESSEN", "close-panel", 0.22, 0.205, 0.22, 0.046)' in page
    assert 'makeTextButton("ZIEHEN", "drag", -0.10, 0.205, 0.40, 0.046)' in page
    assert "dragHandle.visible = true" in page
    assert "closeButton.visible = true" in page
    hide = page[page.index("function hideDashboard"):page.index("function placeDashboard")]
    assert "dashboard.visible = false" in hide
    assert "showHome" not in hide
    assert "resetObjectPanel" not in hide
    assert "fetch(" not in hide
    select = page[page.index("function onSelect"):page.index("function hideDashboard")]
    assert 'hit.userData.action === "close-panel"' in select
    assert "if (dashboard.visible) return;" in select
    assert "resetObjectPanel()" not in select
    assert "showObjectDetail(aimedObject)" in select
    place = page[page.index("function placeDashboard"):page.index("function mountClock")]
    assert "resetObjectPanel()" in place
    drag = page[page.index("function onDragStart"):page.index("function moveDraggedDashboard")]
    assert "intersectObjects([closeButton, dragHandle], false)" in drag
    assert "top.object === dragHandle" in drag
    assert "monitor-hide" in page
    assert 'makeTextButton("MONITOR", "cam-monitor"' in page
    assert "light_preview" in page
    assert "/astro/capture/preview" in page
    hide_monitor = page[page.index("function hideMonitor"):page.index("function placeMonitor")]
    assert "monitor.visible = false" in hide_monitor
    assert "fetch(" not in hide_monitor
    assert "/astro/capture/session-close" not in hide_monitor


def test_quest_session_create_copies_recipe_without_frame_count(tmp_path: Path) -> None:
    from mele.camera_model import list_cameras, list_configs, list_recipes

    db = _db(tmp_path)
    local = tmp_path / "local"
    archive = tmp_path / "archive"
    with pytest.raises(SessionCreateError) as missing:
        create_object_session(
            catalog_key="M31",
            display_name="Andromeda",
            db_path=db,
            local_root=local,
            archive_root=archive,
        )
    assert missing.value.code == "recipe_required"
    camera = list_cameras(db_path=db)[0]
    config = list_configs(camera.id, db_path=db)[0]
    recipe = next(item for item in list_recipes(db_path=db) if item.name == "Kurz – 2 s")
    session = create_object_session(
        catalog_key="M31",
        display_name="Andromeda",
        camera_id=camera.id,
        camera_config_id=config.id,
        recipe_id=recipe.id,
        db_path=db,
        local_root=local,
        archive_root=archive,
    )
    assert session.catalog_key == "M31"
    assert session.profile_id is None
    assert session.camera_id == camera.id
    assert session.recipe_id == recipe.id
    assert session.exposure_s == 2.0
    assert session.iso == 640
    assert session.lights_planned is None
    assert session.equipment == "Lumix S5IIX"
    assert session.local_path.startswith(str(local))
    assert f"s{session.id:05d}" in session.local_path.replace("\\", "/")
    assert session.archive_path.startswith(str(archive))
    with pytest.raises(SessionCreateError) as unknown:
        create_object_session(
            catalog_key="M31",
            recipe_id=9999,
            db_path=db,
            local_root=local,
            archive_root=archive,
        )
    assert unknown.value.code == "recipe_missing"
