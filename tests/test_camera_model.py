"""Kameramodell v1.16. Keine reale Kamera."""

from __future__ import annotations

import time
from pathlib import Path

from mele.astro_manager import create_session, ensure_manager_db, get_session
from mele.camera_model import (
    RECIPES,
    clear_test_capture_data,
    list_cameras,
    list_configs,
    list_recipes,
)
from mele.capture_job import STATE_COMPLETED, CaptureFrameResult, CaptureJobService


def _db(tmp_path: Path) -> Path:
    path = tmp_path / "astro_manager.sqlite"
    ensure_manager_db(path)
    return path


def test_seed_is_idempotent_and_recipes_have_one_exposure(tmp_path: Path) -> None:
    db = _db(tmp_path)
    ensure_manager_db(db)
    cameras = list_cameras(db_path=db)
    assert [camera.name for camera in cameras] == ["Lumix S5IIX"]
    assert cameras[0].cap_iso is True
    assert cameras[0].cap_cooling is False
    assert cameras[0].cap_video is False
    assert cameras[0].iso_from_nina_gains is True
    configs = list_configs(cameras[0].id, db_path=db)
    assert len(configs) == 1
    assert configs[0].iso == 640
    assert configs[0].binning == "1x1"
    recipes = list_recipes(db_path=db)
    assert [(recipe.name, recipe.exposure_s) for recipe in recipes] == list(RECIPES)
    assert all(not hasattr(recipe, "frames") or "frames" not in recipe.to_dict() for recipe in recipes)


def test_probe_exposure_does_not_change_the_session(tmp_path: Path) -> None:
    db = _db(tmp_path)
    camera = list_cameras(db_path=db)[0]
    config = list_configs(camera.id, db_path=db)[0]
    recipe = next(item for item in list_recipes(db_path=db) if item.exposure_s == 20.0)
    session = create_session(
        catalog_key="M31",
        camera_id=camera.id,
        camera_config_id=config.id,
        recipe_id=recipe.id,
        lights_planned=4,
        db_path=db,
        apply_profile=False,
    )
    assert session.exposure_s == 20.0
    assert session.lights_planned == 4

    def capture(snapshot):
        assert snapshot.exposure_s == 10.0
        assert snapshot.planned == 1
        return CaptureFrameResult(ok=True, file_name="probe.rw2", session_completed=1)

    service = CaptureJobService(db_path=db, capture_one=capture)
    status, body = service.start_from_body(
        {
            "catalog_key": "M31",
            "session_id": session.id,
            "frames": 1,
            "exposure_s": 10,
            "iso": 640,
        },
        camera_payload={
            "api_online": True,
            "camera": {"connected": True, "name": "DC-S5M2X", "gains": [100, 640]},
        },
    )
    assert status == 200
    deadline = time.monotonic() + 5
    while time.monotonic() < deadline and service.status_body()["state"] != STATE_COMPLETED:
        time.sleep(0.01)
    assert service.status_body()["state"] == STATE_COMPLETED
    assert body["job"]["exposure_s"] == 10.0
    kept = get_session(session.id, db_path=db)
    assert kept is not None
    assert kept.exposure_s == 20.0
    assert kept.recipe_id == recipe.id


def test_other_camera_is_rejected(tmp_path: Path) -> None:
    db = _db(tmp_path)
    camera = list_cameras(db_path=db)[0]
    session = create_session(
        catalog_key="M31",
        camera_id=camera.id,
        exposure_s=2,
        db_path=db,
        apply_profile=False,
    )
    service = CaptureJobService(
        db_path=db,
        capture_one=lambda _snapshot: CaptureFrameResult(ok=True, file_name="x.rw2"),
    )
    status, body = service.start_from_body(
        {"catalog_key": "M31", "session_id": session.id, "frames": 1, "exposure_s": 2},
        camera_payload={"api_online": True, "camera": {"connected": True, "name": "ASI585MC"}},
    )
    assert status == 409
    assert body["code"] == "camera_mismatch"


def test_clear_removes_sessions_and_keeps_the_camera(tmp_path: Path) -> None:
    db = _db(tmp_path)
    create_session(catalog_key="M31", exposure_s=2, db_path=db, apply_profile=False)
    report = clear_test_capture_data(db_path=db)
    assert report["deleted_sessions"] == 1
    assert report["remaining"]["sessions"] == 0
    assert report["remaining"]["cameras"] == 1
    assert report["remaining"]["capture_recipes"] == 5
