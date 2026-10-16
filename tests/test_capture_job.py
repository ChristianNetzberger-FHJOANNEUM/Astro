"""Capture-Auftrag im MeLE-Prozess. Keine reale Kamera."""

from __future__ import annotations

import sqlite3
import threading
import time
from pathlib import Path

from fastapi import FastAPI
from fastapi.testclient import TestClient

from mele.astro_manager import create_session, ensure_manager_db, get_session
from mele.capture_frame import capture_one_frame
from mele.capture_job import (
    STATE_COMPLETED,
    STATE_FAILED,
    STATE_IDLE,
    STATE_RUNNING,
    STATE_STOP_REQUESTED,
    STATE_STOPPED,
    CaptureFrameResult,
    CaptureJobService,
    confirmed_iso_steps,
    install_capture_routes,
    select_iso_step,
)
from mele.nina import CameraInfo, NinaCameraStatus, NinaCommandResult


def _db(tmp_path: Path) -> Path:
    path = tmp_path / "astro_manager.sqlite"
    ensure_manager_db(path)
    return path


def _session(db: Path, *, key: str = "M31", frames: int = 5, exposure: float = 30.0, done: int = 0) -> int:
    row = create_session(
        catalog_key=key,
        lights_planned=frames,
        lights_completed=done,
        exposure_s=exposure,
        gain=200.0,
        iso=640,
        db_path=db,
        apply_profile=False,
    )
    return int(row.id)


def _close(db: Path, session_id: int) -> None:
    conn = sqlite3.connect(db)
    conn.execute(
        "UPDATE sessions SET lifecycle_status='closed' WHERE id=?",
        (int(session_id),),
    )
    conn.commit()
    conn.close()


def _service(db: Path, capture) -> CaptureJobService:
    return CaptureJobService(db_path=db, capture_one=capture)


def _wait(pred, timeout: float = 5.0) -> None:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if pred():
            return
        time.sleep(0.01)
    raise AssertionError("Zustand nicht erreicht")


def test_single_frame_and_series_count_saved_files_once(tmp_path: Path) -> None:
    db = _db(tmp_path)
    sid = _session(db, frames=3)
    calls = {"n": 0}

    def capture(snapshot):
        calls["n"] += 1
        assert snapshot.exposure_s == 30.0
        assert snapshot.gain == 200.0
        assert snapshot.iso == 640
        assert snapshot.planned == 3
        return CaptureFrameResult(
            ok=True,
            file_name=f"frame_{calls['n']}.rw2",
            session_completed=calls["n"],
            session_planned=3,
        )

    service = _service(db, capture)
    status, body = service.start_from_body({"catalog_key": "M31", "session_id": sid})
    assert status == 200
    assert body["job"]["planned"] == 3
    _wait(lambda: service.status_body()["state"] == STATE_COMPLETED)
    job = service.status_body()["job"]
    assert job["saved"] == 3
    assert job["failed_frames"] == 0
    assert job["current_file"] == "frame_3.rw2"
    assert calls["n"] == 3
    assert get_session(sid, db_path=db) is not None


def test_double_start_is_rejected_and_stop_finishes_the_current_frame(tmp_path: Path) -> None:
    db = _db(tmp_path)
    sid = _session(db, frames=4)
    entered = threading.Event()
    release = threading.Event()
    calls = {"n": 0}

    def capture(snapshot):
        calls["n"] += 1
        entered.set()
        assert release.wait(timeout=5)
        release.clear()
        entered.clear()
        return CaptureFrameResult(ok=True, file_name=f"f{calls['n']}.rw2", session_completed=calls["n"])

    service = _service(db, capture)
    status, first = service.start_from_body({"catalog_key": "M31", "session_id": sid, "frames": 4})
    assert status == 200
    assert entered.wait(timeout=5)
    again, busy = service.start_from_body({"catalog_key": "M31", "session_id": sid, "frames": 4})
    assert again == 409
    assert busy["code"] == "busy"
    assert service.inflight_count() == 1
    stop_status, stopped = service.stop()
    assert stop_status == 200
    assert stopped["state"] == STATE_STOP_REQUESTED
    release.set()
    _wait(lambda: service.status_body()["state"] == STATE_STOPPED)
    job = service.status_body()["job"]
    assert job["saved"] == 1
    assert calls["n"] == 1
    assert job["state"] == STATE_STOPPED
    assert service.inflight_count() == 0


def test_another_session_does_not_replace_the_running_job(tmp_path: Path) -> None:
    db = _db(tmp_path)
    running_id = _session(db, frames=2)
    other_id = _session(db, frames=2)
    entered = threading.Event()
    release = threading.Event()

    def capture(_snapshot):
        entered.set()
        assert release.wait(timeout=5)
        return CaptureFrameResult(ok=True, file_name="a.rw2", session_completed=1)

    service = _service(db, capture)
    status, _started = service.start_from_body(
        {"catalog_key": "M31", "session_id": running_id, "frames": 1, "exposure_s": 1}
    )
    assert status == 200
    assert entered.wait(timeout=5)
    again, busy = service.start_from_body(
        {"catalog_key": "M31", "session_id": other_id, "frames": 1, "exposure_s": 1}
    )
    assert again == 409
    assert busy["code"] == "busy"
    assert service.status_body()["job"]["session_id"] == running_id
    release.set()
    _wait(lambda: service.status_body()["state"] == STATE_COMPLETED)
    assert service.status_body()["job"]["session_id"] == running_id


def test_status_survives_the_caller_and_two_readers_see_one_job(tmp_path: Path) -> None:
    db = _db(tmp_path)
    sid = _session(db)
    entered = threading.Event()
    release = threading.Event()

    def capture(snapshot):
        entered.set()
        assert release.wait(timeout=5)
        return CaptureFrameResult(ok=True, file_name="only.rw2", session_completed=1)

    service = _service(db, capture)
    status, started = service.start_from_body({"catalog_key": "M31", "session_id": sid, "frames": 1})
    assert status == 200
    job_id = started["job"]["job_id"]
    assert entered.wait(timeout=5)
    # Der startende Aufruf ist vorbei. Zwei Beobachter lesen denselben Auftrag.
    seen = []

    def read() -> None:
        body = service.status_body()
        seen.append((body["job"]["job_id"], body["state"], body["process_epoch"]))

    threads = [threading.Thread(target=read), threading.Thread(target=read)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join(timeout=5)
    assert len(seen) == 2
    assert seen[0][0] == seen[1][0] == job_id
    assert seen[0][1] == seen[1][1] == STATE_RUNNING
    assert seen[0][2] == seen[1][2] == service.epoch
    release.set()
    _wait(lambda: service.status_body()["state"] == STATE_COMPLETED)
    done = service.status_body()
    assert done["job"]["saved"] == 1
    assert done["job"]["current_file"] == "only.rw2"
    assert done["resumable"] is False


def test_restart_does_not_present_the_old_job_as_continued(tmp_path: Path) -> None:
    db = _db(tmp_path)
    sid = _session(db, frames=2, done=1)

    def capture(snapshot):
        return CaptureFrameResult(ok=True, file_name="a.rw2", session_completed=2)

    first = _service(db, capture)
    status, _body = first.start_from_body({"catalog_key": "M31", "session_id": sid, "frames": 1})
    assert status == 200
    _wait(lambda: first.status_body()["state"] == STATE_COMPLETED)
    restarted = _service(db, capture)
    body = restarted.status_body()
    assert body["state"] == STATE_IDLE
    assert body["job"] is None
    assert body["resumable"] is False
    assert body["process_epoch"] != first.epoch


def test_nina_failure_stops_the_series_without_counting_the_frame(tmp_path: Path) -> None:
    db = _db(tmp_path)
    sid = _session(db, frames=3)
    calls = {"n": 0}

    def capture(snapshot):
        calls["n"] += 1
        if calls["n"] == 1:
            return CaptureFrameResult(ok=True, file_name="ok.rw2", session_completed=1)
        return CaptureFrameResult(ok=False, error="NINA offline")

    service = _service(db, capture)
    service.start_from_body({"catalog_key": "M31", "session_id": sid, "frames": 3})
    _wait(lambda: service.status_body()["state"] == STATE_FAILED)
    job = service.status_body()["job"]
    assert job["saved"] == 1
    assert job["failed_frames"] == 1
    assert job["error"] == "NINA offline"
    assert calls["n"] == 2


def test_missing_closed_and_ambiguous_sessions_do_not_create_one(tmp_path: Path) -> None:
    db = _db(tmp_path)
    closed_id = _session(db, key="M42")
    _close(db, closed_id)
    before = _count(db)

    service = _service(db, lambda snapshot: CaptureFrameResult(ok=True))
    status, body = service.start_from_body({"catalog_key": "M31"})
    assert status == 409
    assert body["code"] == "session_missing"
    assert _count(db) == before

    status, body = service.start_from_body({"catalog_key": "M42", "session_id": closed_id})
    assert status == 409
    assert body["code"] == "session_closed"

    status, body = service.start_from_body({"catalog_key": "M31", "session_id": 99999})
    assert status == 404
    assert body["code"] == "session_missing"

    one = _session(db, key="M51")
    status, body = service.start_from_body({"catalog_key": "NGC1", "session_id": one})
    assert status == 409
    assert body["code"] == "session_mismatch"

    _session(db, key="M31")
    _session(db, key="M31")
    status, body = service.start_from_body({"catalog_key": "M31"})
    assert status == 409
    assert body["code"] == "session_ambiguous"
    assert len(body["sessions"]) == 2
    assert _count(db) == before + 3


def test_unique_open_session_is_adopted_and_params_stay_frozen(tmp_path: Path) -> None:
    db = _db(tmp_path)
    sid = _session(db, frames=2, exposure=10.0)
    seen: list[float] = []
    entered = threading.Event()
    release = threading.Event()

    def capture(snapshot):
        seen.append(snapshot.exposure_s)
        entered.set()
        assert release.wait(timeout=5)
        return CaptureFrameResult(ok=True, file_name="frozen.rw2", session_completed=1)

    service = _service(db, capture)
    status, body = service.start_from_body({"catalog_key": "M31", "exposure_s": 12.5, "frames": 1})
    assert status == 200
    assert body["job"]["session_id"] == sid
    assert body["job"]["exposure_s"] == 12.5
    assert entered.wait(timeout=5)
    conn = sqlite3.connect(db)
    conn.execute("UPDATE sessions SET exposure_s=99 WHERE id=?", (sid,))
    conn.commit()
    conn.close()
    release.set()
    _wait(lambda: service.status_body()["state"] == STATE_COMPLETED)
    assert seen == [12.5]
    assert service.status_body()["job"]["exposure_s"] == 12.5


def test_closed_session_between_frames_fails_without_another_capture(tmp_path: Path) -> None:
    db = _db(tmp_path)
    sid = _session(db, frames=3)
    calls = {"n": 0}

    def capture(snapshot):
        calls["n"] += 1
        _close(db, sid)
        return CaptureFrameResult(ok=True, file_name="last.rw2", session_completed=1)

    service = _service(db, capture)
    service.start_from_body({"catalog_key": "M31", "session_id": sid, "frames": 3})
    _wait(lambda: service.status_body()["state"] == STATE_FAILED)
    job = service.status_body()["job"]
    assert calls["n"] == 1
    assert job["saved"] == 1
    assert "nicht mehr offen" in job["error"]


def test_two_direct_captures_cannot_overlap(tmp_path: Path) -> None:
    db = _db(tmp_path)
    service = _service(db, lambda snapshot: CaptureFrameResult(ok=True))
    assert service.try_begin_direct() is True
    assert service.try_begin_direct() is False
    service.end_direct()
    assert service.try_begin_direct() is True
    service.end_direct()


def test_direct_capture_and_job_cannot_overlap(tmp_path: Path) -> None:
    db = _db(tmp_path)
    sid = _session(db)
    entered = threading.Event()
    release = threading.Event()

    def capture(snapshot):
        entered.set()
        assert release.wait(timeout=5)
        return CaptureFrameResult(ok=True, file_name="a.rw2")

    service = _service(db, capture)
    assert service.try_begin_direct()
    status, body = service.start_from_body({"catalog_key": "M31", "session_id": sid, "frames": 1})
    assert status == 409
    assert body["code"] == "busy"
    service.end_direct()
    service.start_from_body({"catalog_key": "M31", "session_id": sid, "frames": 1})
    assert entered.wait(timeout=5)
    assert service.try_begin_direct() is False
    release.set()
    _wait(lambda: service.status_body()["state"] == STATE_COMPLETED)


def test_http_start_stop_and_status(tmp_path: Path) -> None:
    db = _db(tmp_path)
    sid = _session(db, frames=2)
    entered = threading.Event()
    release = threading.Event()

    def capture(snapshot):
        entered.set()
        assert release.wait(timeout=5)
        return CaptureFrameResult(ok=True, file_name="http.rw2", session_completed=1)

    service = _service(db, capture)
    app = FastAPI()
    install_capture_routes(app, service)
    with TestClient(app) as client:
        started = client.post(
            "/astro/capture/start",
            json={"catalog_key": "M31", "session_id": sid, "frames": 2},
        )
        assert started.status_code == 200
        assert started.json()["job"]["saved"] == 0
        assert entered.wait(timeout=5)
        second = client.post(
            "/astro/capture/start",
            json={"catalog_key": "M31", "session_id": sid, "frames": 2},
        )
        assert second.status_code == 409
        watching = client.get("/astro/capture/status")
        assert watching.status_code == 200
        assert watching.json()["job"]["job_id"] == started.json()["job"]["job_id"]
        stopped = client.post("/astro/capture/stop")
        assert stopped.status_code == 200
        assert stopped.json()["state"] == STATE_STOP_REQUESTED
        release.set()
        deadline = time.monotonic() + 5
        final = None
        while time.monotonic() < deadline:
            final = client.get("/astro/capture/status").json()
            if final["state"] == STATE_STOPPED:
                break
            time.sleep(0.01)
        assert final is not None
        assert final["state"] == STATE_STOPPED
        assert final["job"]["saved"] == 1
        idle_stop = client.post("/astro/capture/stop")
        assert idle_stop.status_code == 409


def test_capture_one_frame_saves_once_and_counts_once(tmp_path: Path) -> None:
    db = _db(tmp_path)
    sid = _session(db, frames=2, done=0)
    nina = _FakeNina()
    common = dict(
        db_path=db,
        local_root=tmp_path / "local",
        archive_root=tmp_path / "archive",
        session_id=sid,
        catalog_key="M31",
        exposure_s=1.0,
        gain=200.0,
        image_type="LIGHT",
        stable_s=0.0,
        poll_s=0.01,
        error_wait_s=0.05,
    )
    first = capture_one_frame(nina, **common)
    second = capture_one_frame(nina, **common)
    assert first["ok"] is True
    assert second["ok"] is True
    assert first["file_name"] != second["file_name"]
    session = get_session(sid, db_path=db)
    assert session is not None
    assert session.lights_completed == 2
    assert len(nina.capture_calls) == 2

    nina.fail = True
    failed = capture_one_frame(nina, **common)
    assert failed["ok"] is False
    assert get_session(sid, db_path=db).lights_completed == 2
    assert "NINA" in failed["error"] or failed["error"]


def test_desktop_pages_use_the_job_and_not_a_browser_loop() -> None:
    imaging = Path("app_mele/imaging.html").read_text(encoding="utf-8")
    pano = Path("app_mele/pano.html").read_text(encoding="utf-8")
    for text in (imaging, pano):
        assert "/astro/capture/start" in text
        assert "/astro/capture/stop" in text
        assert "/astro/capture/status" in text
        assert "/astro/nina/capture" not in text
        assert "for (let i = 0; i < total" not in text
    app = Path("app_mele/main_app.py").read_text(encoding="utf-8")
    assert "install_capture_routes" in app
    assert "capture_one_frame" in app


def _count(db: Path) -> int:
    conn = sqlite3.connect(db)
    n = int(conn.execute("SELECT COUNT(*) FROM sessions").fetchone()[0])
    conn.close()
    return n


class _FakeNina:
    def __init__(self) -> None:
        self.fail = False
        self.directory: Path | None = None
        self.capture_calls: list[dict] = []

    def get_camera_info(self) -> NinaCameraStatus:
        return NinaCameraStatus(
            api_online=True,
            camera=CameraInfo(connected=True, name="fake"),
        )

    def prepare_mele_image_destination(self, directory) -> dict:
        self.directory = Path(directory)
        self.directory.mkdir(parents=True, exist_ok=True)
        ok = NinaCommandResult(ok=True, api_online=True)
        return {"path": ok, "pattern": ok}

    def sync_snapshot_controls(self, **kwargs) -> dict:
        return {}

    def capture(self, **kwargs) -> NinaCommandResult:
        self.capture_calls.append(kwargs)
        if self.fail:
            return NinaCommandResult(ok=False, api_online=True, error="NINA capture fehlgeschlagen")
        assert self.directory is not None
        path = self.directory / f"frame_{len(self.capture_calls)}.rw2"
        path.write_bytes(b"x" * 2048)
        return NinaCommandResult(ok=True, api_online=True, message="ok")


_LUMIX_GAINS = [100, 125, 160, 200, 250, 400, 800, 1600, 3200]


def test_dark_frames_keep_the_requested_type(tmp_path: Path) -> None:
    db = _db(tmp_path)
    sid = _session(db, frames=2, exposure=1.0)
    seen: dict[str, object] = {}

    def capture(snapshot):
        seen["image_type"] = snapshot.image_type
        seen["planned"] = snapshot.planned
        return CaptureFrameResult(ok=True, file_name="dark.rw2", session_completed=1)

    status, _body = _service(db, capture).start_from_body(
        {"catalog_key": "M31", "session_id": sid, "frames": 2, "exposure_s": 1, "image_type": "DARK"}
    )
    assert status == 200
    _wait(lambda: seen.get("image_type") == "DARK")
    assert seen["image_type"] == "DARK"
    assert seen["planned"] == 2


def test_iso_steps_come_only_from_the_camera_gain_list(tmp_path: Path) -> None:
    db = _db(tmp_path)
    sid = _session(db)
    _bind_lumix(db, sid)
    service = _service(db, lambda _snapshot: CaptureFrameResult(ok=True))
    lumix = {
        "api_online": True,
        "camera": {
            "connected": True,
            "name": "DC-S5M2X",
            "gains": list(_LUMIX_GAINS),
            "gain_min": 100,
            "gain_max": 51200,
        },
    }
    listed = service.context("M31", lumix)
    assert listed["iso_steps"] == _LUMIX_GAINS
    assert listed["iso_adjustable"] is True
    assert listed["capabilities"]["iso"] is True
    assert listed["capabilities"]["cooling"] is False
    other = {
        "api_online": True,
        "camera": {"connected": True, "name": "ASI585MC", "gains": list(_LUMIX_GAINS)},
    }
    foreign = service.context("M31", other)
    assert foreign["iso_steps"] == [640]
    assert foreign["iso_adjustable"] is False
    bounds_only = service.context(
        "M31",
        {"api_online": True, "camera": {"connected": True, "name": "DC-S5M2X", "gain_min": 100, "gain_max": 51200, "gains": []}},
    )
    assert bounds_only["iso_steps"] == [640]
    assert bounds_only["iso_adjustable"] is False
    assert confirmed_iso_steps({"camera": {"gain_min": 100, "gain_max": 51200}}) == []


def test_iso_step_stays_inside_the_list() -> None:
    steps = [100, 200, 400, 800]
    assert select_iso_step(steps, 200, 1) == 400
    assert select_iso_step(steps, 200, -1) == 100
    assert select_iso_step(steps, 100, -1) == 100
    assert select_iso_step(steps, 800, 1) == 800
    assert select_iso_step(steps, 150, 1) == 200
    assert select_iso_step(steps, 150, -1) == 100
    assert select_iso_step(steps, None, 1) == 100
    assert 300 not in steps
    assert select_iso_step([], 640, 1) == 640


def _bind_lumix(db: Path, session_id: int) -> None:
    from mele.camera_model import list_cameras

    camera = list_cameras(db_path=db)[0]
    conn = sqlite3.connect(db)
    conn.execute("UPDATE sessions SET camera_id=? WHERE id=?", (camera.id, int(session_id)))
    conn.commit()
    conn.close()


def test_selected_iso_replaces_a_different_gain_on_the_nina_call(tmp_path: Path) -> None:
    db = _db(tmp_path)
    sid = _session(db, frames=1, exposure=1.0)
    _bind_lumix(db, sid)
    seen: dict[str, object] = {}

    def capture(snapshot):
        seen["gain"] = snapshot.gain
        seen["iso"] = snapshot.iso
        return CaptureFrameResult(ok=True, file_name="iso.rw2", session_completed=1)

    service = _service(db, capture)
    camera = {"api_online": True, "camera": {"connected": True, "name": "DC-S5M2X", "gains": list(_LUMIX_GAINS)}}
    status, _body = service.start_from_body(
        {
            "catalog_key": "M31",
            "session_id": sid,
            "frames": 1,
            "exposure_s": 1,
            "iso": 800,
            "gain": 200,
        },
        camera_payload=camera,
    )
    assert status == 200
    _wait(lambda: service.status_body()["state"] == STATE_COMPLETED)
    assert seen["iso"] == 800
    assert seen["gain"] == 800.0

    kept = _session(db, frames=1, exposure=1.0)
    _bind_lumix(db, kept)
    held: dict[str, object] = {}

    def keep(snapshot):
        held["gain"] = snapshot.gain
        held["iso"] = snapshot.iso
        return CaptureFrameResult(ok=True, file_name="kept.rw2", session_completed=1)

    other = _service(db, keep)
    status, _body = other.start_from_body(
        {
            "catalog_key": "M31",
            "session_id": kept,
            "frames": 1,
            "exposure_s": 1,
            "iso": 150,
            "gain": 200,
        },
        camera_payload=camera,
    )
    assert status == 200
    _wait(lambda: other.status_body()["state"] == STATE_COMPLETED)
    assert held["iso"] == 150
    assert held["gain"] == 200.0

    nina = _FakeNina()
    synced: list[dict] = []
    nina.sync_snapshot_controls = lambda **kwargs: synced.append(kwargs) or {}  # type: ignore[method-assign]
    saved = capture_one_frame(
        nina,
        db_path=db,
        local_root=tmp_path / "local-iso",
        archive_root=tmp_path / "archive-iso",
        session_id=sid,
        catalog_key="M31",
        exposure_s=1.0,
        gain=800.0,
        image_type="LIGHT",
        stable_s=0.0,
        poll_s=0.01,
        error_wait_s=0.05,
    )
    assert saved["ok"] is True
    assert nina.capture_calls[-1]["gain"] == 800.0
    assert synced[-1]["gain"] == 800.0
    assert "iso" not in nina.capture_calls[-1]


def test_probe_light_is_only_signalled_for_a_single_light(tmp_path: Path) -> None:
    db = _db(tmp_path)
    seen: list[tuple[int, str]] = []

    def capture(snapshot):
        return CaptureFrameResult(ok=True, file_name="frame.rw2", session_completed=1)

    def on_probe(snapshot, file_name):
        seen.append((int(snapshot.planned), file_name))

    series_service = CaptureJobService(db_path=db, capture_one=capture, on_probe_light=on_probe)
    series = _session(db, frames=3)
    status, _body = series_service.start_from_body(
        {"catalog_key": "M31", "session_id": series, "frames": 3, "image_type": "LIGHT"}
    )
    assert status == 200
    _wait(lambda: series_service.status_body()["state"] == STATE_COMPLETED)
    assert seen == []

    dark_service = CaptureJobService(db_path=db, capture_one=capture, on_probe_light=on_probe)
    single = _session(db, key="M42", frames=1)
    status, _body = dark_service.start_from_body(
        {"catalog_key": "M42", "session_id": single, "frames": 1, "image_type": "DARK"}
    )
    assert status == 200
    _wait(lambda: dark_service.status_body()["state"] == STATE_COMPLETED)
    assert seen == []

    light_service = CaptureJobService(db_path=db, capture_one=capture, on_probe_light=on_probe)
    light = _session(db, key="M51", frames=1)
    status, _body = light_service.start_from_body(
        {"catalog_key": "M51", "session_id": light, "frames": 1, "exposure_s": 12.0, "image_type": "LIGHT"}
    )
    assert status == 200
    _wait(lambda: len(seen) == 1)
    assert seen == [(1, "frame.rw2")]
    assert light_service.status_body()["state"] == STATE_COMPLETED


def test_probe_light_error_does_not_fail_the_capture(tmp_path: Path) -> None:
    db = _db(tmp_path)
    sid = _session(db, frames=1)

    def capture(snapshot):
        return CaptureFrameResult(ok=True, file_name="frame.rw2")

    def on_probe(snapshot, file_name):
        raise RuntimeError("Statistik fehlgeschlagen")

    service = CaptureJobService(db_path=db, capture_one=capture, on_probe_light=on_probe)
    status, _body = service.start_from_body(
        {"catalog_key": "M31", "session_id": sid, "frames": 1, "image_type": "LIGHT"}
    )
    assert status == 200
    _wait(lambda: service.status_body()["state"] == STATE_COMPLETED)
    assert service.status_body()["job"]["saved"] == 1
