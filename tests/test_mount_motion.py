"""XR-10b Stufe B: Bewegungszustand, STOP-Rennen, Koordinaten, Instanzschloss.

Keine echte Montierung. Die Prüfungen laufen gegen MountMotion und ein
Windows-Dateischloss in einem Unterprozess.
"""

from __future__ import annotations

import os
import subprocess
import sys
import textwrap
import threading
from datetime import datetime, timezone
from pathlib import Path

import pytest

from mele.horizon import HorizonPoint, HorizonProfile
from mele.mount_motion import (
    FRESH_S,
    InstanceBusy,
    InstanceLock,
    MountMotion,
    MountSample,
    command_outcome,
    phd2_blocks_goto,
    slew_coordinates_deg,
    target_block_reason,
)
from mele.nina import validate_slew_radec_deg

ROOT = Path(__file__).resolve().parents[1]
LAT = 48.254750
LON = 14.366140
WHEN = datetime(2026, 10, 12, 20, 0, tzinfo=timezone.utc)


def idle(**kwargs) -> MountSample:
    data = dict(online=True, connected=True, slewing=False, parked=False, age_s=0.0)
    data.update(kwargs)
    return MountSample(**data)


def _ready() -> MountMotion:
    motion = MountMotion()
    motion.note(idle())
    assert motion.view()["state"] == "bereit"
    return motion


def test_start_is_unklar_and_stale_sample_does_not_ready() -> None:
    motion = MountMotion()
    assert motion.view()["state"] == "unklar"
    assert motion.view()["label"] == "Zustand unklar"
    motion.note(idle(age_s=FRESH_S + 0.1))
    assert motion.view()["state"] == "unklar"
    motion.note(idle())
    assert motion.view()["state"] == "bereit"
    motion.note(idle(age_s=FRESH_S + 1))
    assert motion.view()["state"] == "unklar"
    assert motion.view()["detail"] == "Meldung nicht mehr aktuell"


def test_offline_and_disconnected_are_distinct() -> None:
    motion = _ready()
    motion.note(MountSample(online=False, connected=False, error="Timeout"))
    view = motion.view()
    assert view["state"] == "unklar"
    assert view["label"] == "NINA nicht erreichbar"
    motion.note(idle(connected=False))
    view = motion.view()
    assert view["label"] == "Montierung nicht verbunden"
    assert view["state"] != "bereit"


def test_concurrent_goto_only_one_accepted() -> None:
    motion = _ready()
    barrier = threading.Barrier(8)
    results: list = []

    def attempt() -> None:
        barrier.wait()
        results.append(motion.reserve_goto(idle()))

    threads = [threading.Thread(target=attempt) for _ in range(8)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()
    accepted = [item for item in results if item.ok]
    rejected = [item for item in results if not item.ok]
    assert len(accepted) == 1
    assert len(rejected) == 7
    assert {item.status for item in rejected} == {409}
    assert {item.error for item in rejected} == {"GoTo bereits aktiv"}
    assert motion.view()["state"] == "faehrt"
    assert motion.view()["label"] == "GoTo aktiv"


def test_second_client_uses_same_lock() -> None:
    motion = _ready()
    desktop = motion.reserve_goto(idle())
    quest = motion.reserve_goto(idle())
    assert desktop.ok
    assert not quest.ok
    assert quest.status == 409
    assert quest.error == "GoTo bereits aktiv"


def test_goto_rejected_while_slewing_or_moving() -> None:
    motion = MountMotion()
    motion.note(idle(slewing=True))
    refused = motion.reserve_goto(idle(slewing=True))
    assert not refused.ok
    assert refused.status == 409
    assert motion.view()["state"] == "faehrt"
    assert refused.error == "Montierung bewegt sich"

    moving = _ready()
    assert moving.reserve_move().ok
    during_move = moving.reserve_goto(idle())
    assert not during_move.ok
    assert during_move.error == "Achsbewegung aktiv"
    assert moving.view()["label"] == "Achsbewegung aktiv"


def test_phd2_guiding_blocks_and_offline_does_not() -> None:
    class Status:
        def __init__(self, connection: str, guiding: bool) -> None:
            self.connection = connection
            self.guiding = guiding

    assert phd2_blocks_goto(Status("GUIDING", True)) == "PHD2 führt"
    assert phd2_blocks_goto(Status("CONNECTED", True)) == "PHD2 führt"
    assert phd2_blocks_goto(Status("CALIBRATING", False)) == "PHD2 kalibriert"
    assert phd2_blocks_goto(Status("OFFLINE", False)) == ""
    assert phd2_blocks_goto(Status("CONNECTED", False)) == ""
    assert phd2_blocks_goto(None) == "PHD2-Zustand nicht lesbar"


def test_stop_during_slew_stays_unsettled_until_idle_telemetry() -> None:
    motion = _ready()
    assert motion.reserve_goto(idle()).ok
    motion.note(idle(slewing=True))
    assert motion.view()["label"] == "GoTo aktiv"
    motion.begin_stop()
    assert motion.view()["state"] == "stoppt"
    assert motion.view()["label"] == "STOP läuft"
    motion.note(idle(slewing=True))
    assert motion.view()["state"] == "stoppt"
    follow = motion.complete_stop("ok")
    assert follow.error == ""
    assert motion.view()["state"] == "stoppt"
    assert motion.view()["detail"] == "STOP gesendet, Stillstand offen"
    motion.note(idle(slewing=True))
    assert motion.view()["state"] == "stoppt"
    motion.note(idle())
    assert motion.view()["state"] == "bereit"


def test_late_goto_ack_after_stop_requests_restop_and_does_not_ready() -> None:
    motion = _ready()
    reserved = motion.reserve_goto(idle())
    motion.begin_stop()
    motion.note(idle())
    assert motion.view()["state"] == "stoppt"
    follow = motion.complete_goto(reserved.generation, "ok")
    assert follow.restop
    assert follow.status == 409
    assert follow.error == "STOP während des Starts"
    assert motion.view()["state"] == "stoppt"
    motion.note(idle())
    assert motion.view()["state"] != "bereit"
    motion.complete_stop("ok")
    assert motion.view()["state"] == "stoppt"
    motion.note(idle())
    assert motion.view()["state"] == "bereit"


def test_stop_timeout_does_not_report_success() -> None:
    motion = _ready()
    motion.reserve_goto(idle())
    motion.begin_stop()
    follow = motion.complete_stop("unclear")
    assert follow.status == 502
    assert motion.view()["state"] == "unklar"
    assert motion.view()["state"] != "bereit"
    assert "unklar" in motion.view()["detail"].lower() or motion.view()["label"] == "Zustand unklar"
    motion.note(idle())
    assert motion.view()["state"] != "bereit"


def test_goto_timeout_does_not_become_ready() -> None:
    motion = _ready()
    reserved = motion.reserve_goto(idle())
    follow = motion.complete_goto(reserved.generation, "unclear")
    assert follow.restop
    assert follow.status == 502
    assert motion.view()["state"] == "unklar"
    motion.note(idle())
    assert motion.view()["state"] != "bereit"
    assert motion.view()["detail"] == "GoTo gestartet, Bewegung noch nicht bestätigt"


def test_explicit_goto_error_can_recover_from_fresh_idle() -> None:
    motion = _ready()
    reserved = motion.reserve_goto(idle())
    follow = motion.complete_goto(reserved.generation, "error")
    assert not follow.restop
    assert motion.view()["state"] == "unklar"
    motion.note(idle())
    assert motion.view()["state"] == "bereit"


def test_connection_loss_during_goto_does_not_ready() -> None:
    motion = _ready()
    reserved = motion.reserve_goto(idle())
    motion.note(idle(slewing=True))
    motion.note(MountSample(online=False, connected=False, error="Timeout"))
    assert motion.view()["state"] == "unklar"
    assert motion.view()["label"] == "NINA nicht erreichbar"
    motion.complete_goto(reserved.generation, "ok")
    assert motion.view()["state"] != "bereit"
    motion.note(idle())
    assert motion.view()["state"] == "bereit"


def test_restart_begins_unklar_until_fresh_idle() -> None:
    first = _ready()
    first.reserve_goto(idle())
    restarted = MountMotion()
    assert restarted.view()["state"] == "unklar"
    refused = restarted.reserve_goto(idle(slewing=False, age_s=5))
    assert not refused.ok
    restarted.note(idle())
    assert restarted.view()["state"] == "bereit"


def test_unseen_goto_ignores_early_idle_sample() -> None:
    motion = _ready()
    reserved = motion.reserve_goto(idle())
    motion.note(idle())
    assert motion.view()["state"] == "faehrt"
    assert motion.view()["detail"] == "GoTo gestartet, Bewegung noch nicht bestätigt"
    motion.complete_goto(reserved.generation, "ok")
    motion.note(idle())
    assert motion.view()["state"] == "faehrt"
    motion.note(idle(slewing=True))
    motion.note(idle())
    assert motion.view()["state"] == "bereit"


def test_coordinates_are_degrees_without_hour_conversion() -> None:
    assert slew_coordinates_deg(37.95, 89.26) == (37.95, 89.26)
    assert slew_coordinates_deg(15.0, 10.0) != (15.0 * 15.0, 10.0)
    assert validate_slew_radec_deg(180.0, 45.0) == ""
    assert validate_slew_radec_deg(15.0, 40.0) == ""
    assert validate_slew_radec_deg(400.0, 0.0) != ""
    assert validate_slew_radec_deg(10.0, 95.0) != ""
    assert validate_slew_radec_deg(float("nan"), 0.0) != ""
    assert command_outcome(True, True) == "ok"
    assert command_outcome(False, False) == "unclear"
    assert command_outcome(False, True) == "error"


def test_horizon_and_garden_mask() -> None:
    assert target_block_reason(0.0, -80.0, LAT, LON, WHEN, None) == "Ziel unter Horizont"
    assert target_block_reason(37.95, 89.26, LAT, LON, WHEN, None) == ""
    mask = HorizonProfile(
        source="test",
        image_width=1,
        image_height=1,
        process_width=1,
        process_height=1,
        north_x=0.0,
        points=[HorizonPoint(0.0, 80.0, 0, 0), HorizonPoint(180.0, 80.0, 0, 0)],
    )
    assert target_block_reason(37.95, 89.26, LAT, LON, WHEN, mask) == "Ziel hinter dem Gartenhorizont"
    low_mask = HorizonProfile(
        source="test",
        image_width=1,
        image_height=1,
        process_width=1,
        process_height=1,
        north_x=0.0,
        points=[HorizonPoint(0.0, 5.0, 0, 0), HorizonPoint(180.0, 5.0, 0, 0)],
    )
    assert target_block_reason(37.95, 89.26, LAT, LON, WHEN, low_mask) == ""


def test_move_stop_does_not_clear_goto() -> None:
    motion = _ready()
    motion.reserve_goto(idle())
    motion.finish_move(True)
    assert motion.view()["state"] == "faehrt"
    motion.begin_stop()
    assert motion.view()["state"] == "stoppt"


def test_instance_lock_blocks_second_holder_and_releases(tmp_path: Path) -> None:
    path = tmp_path / "mele-app.lock"
    first = InstanceLock(path)
    first.acquire()
    second = InstanceLock(path)
    with pytest.raises(InstanceBusy):
        second.acquire()
    first.release()
    first.release()
    third = InstanceLock(path)
    third.acquire()
    third.release()
    assert path.is_file()


def _python() -> str:
    return sys.executable


def _run_lock_child(tmp_path: Path, mode: str) -> subprocess.Popen:
    path = tmp_path / "mele-app.lock"
    script = tmp_path / "hold_lock.py"
    script.write_text(
        textwrap.dedent(
            """
            import os
            import sys
            from pathlib import Path
            from mele.mount_motion import InstanceLock

            lock = InstanceLock(Path(sys.argv[1]))
            lock.acquire()
            sys.stdout.write("HOLD\\n")
            sys.stdout.flush()
            if sys.argv[2] == "crash":
                os._exit(7)
            sys.stdin.readline()
            lock.release()
            """
        ).lstrip(),
        encoding="utf-8",
    )
    env = os.environ.copy()
    env["PYTHONPATH"] = str(ROOT) + os.pathsep + env.get("PYTHONPATH", "")
    return subprocess.Popen(
        [_python(), str(script), str(path), mode],
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        env=env,
        text=True,
    )


def _wait_hold(proc: subprocess.Popen) -> None:
    assert proc.stdout is not None
    line = proc.stdout.readline()
    assert line.strip() == "HOLD", proc.stderr.read() if proc.stderr is not None else line


def test_second_process_cannot_lock_and_crash_releases(tmp_path: Path) -> None:
    path = tmp_path / "mele-app.lock"
    holder = _run_lock_child(tmp_path, "hold")
    try:
        _wait_hold(holder)
        with pytest.raises(InstanceBusy):
            InstanceLock(path).acquire()
    finally:
        if holder.stdin is not None:
            holder.stdin.write("\n")
            holder.stdin.flush()
        holder.wait(timeout=10)
    again = InstanceLock(path)
    again.acquire()
    again.release()

    crashed = _run_lock_child(tmp_path, "crash")
    _wait_hold(crashed)
    code = crashed.wait(timeout=10)
    assert code == 7
    after = InstanceLock(path)
    after.acquire()
    after.release()


def test_parallel_http_accepts_one_goto_and_does_not_block_stop() -> None:
    """Zwei API-GoTo und ein STOP gegen eine Mock-NINA. Keine reale Montierung."""
    from fastapi import FastAPI
    from fastapi.responses import JSONResponse
    from fastapi.testclient import TestClient

    motion = _ready()
    entered = threading.Event()
    release = threading.Event()
    calls = {"slew": 0, "stop": 0}
    call_lock = threading.Lock()

    class Nina:
        def slew(self) -> str:
            with call_lock:
                calls["slew"] += 1
            entered.set()
            assert release.wait(timeout=5)
            return "ok"

        def stop(self) -> None:
            with call_lock:
                calls["stop"] += 1
            release.set()

    nina = Nina()
    app = FastAPI()

    @app.post("/nina/mount/slew")
    def slew() -> JSONResponse:
        reserved = motion.reserve_goto(idle())
        if not reserved.ok:
            return JSONResponse({"ok": False, "error": reserved.error}, status_code=reserved.status)
        outcome = nina.slew()
        follow = motion.complete_goto(reserved.generation, outcome)
        if follow.restop:
            nina.stop()
            motion.complete_stop("ok")
            return JSONResponse({"ok": False, "error": follow.error}, status_code=follow.status)
        return JSONResponse({"ok": True, "error": ""})

    @app.post("/nina/mount/slew/stop")
    def stop() -> JSONResponse:
        motion.begin_stop()
        nina.stop()
        follow = motion.complete_stop("ok")
        body = {"ok": follow.error == "", "error": follow.error, "settled": False, "motion": motion.view()}
        return JSONResponse(body, status_code=200 if follow.error == "" else follow.status)

    first: dict = {}

    with TestClient(app) as client:
        def run_first() -> None:
            response = client.post("/nina/mount/slew")
            first["status"] = response.status_code
            first["body"] = response.json()

        worker = threading.Thread(target=run_first)
        worker.start()
        assert entered.wait(timeout=5)
        second = client.post("/nina/mount/slew")
        stopped = client.post("/nina/mount/slew/stop")
        worker.join(timeout=5)
    assert not worker.is_alive()
    assert calls["slew"] == 1
    assert second.status_code == 409
    assert second.json()["error"] == "GoTo bereits aktiv"
    assert stopped.status_code == 200
    assert stopped.json()["settled"] is False
    assert stopped.json()["motion"]["state"] == "stoppt"
    assert first["status"] == 409
    assert first["body"]["error"] == "STOP während des Starts"
    assert calls["stop"] >= 1
