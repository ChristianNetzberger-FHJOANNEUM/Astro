"""XR-10c Stufe B1: Achsen-Totmann ohne reale Montierung."""

from __future__ import annotations

import threading
from pathlib import Path

from mele.mount_motion import MountMotion, MountSample, phd2_blocks_axis, phd2_blocks_goto
from mele.nina_mount_move import IDLE_STOP_S, KEEPALIVE_S, NinaMountMover


class Status:
    def __init__(self, connection: str, guiding: bool = False) -> None:
        self.connection = connection
        self.guiding = guiding


def _idle(**kwargs) -> MountSample:
    base = dict(online=True, connected=True, slewing=False, parked=False, age_s=0.0)
    base.update(kwargs)
    return MountSample(**base)


def _ready() -> MountMotion:
    motion = MountMotion()
    motion.note(_idle())
    assert motion.view()["state"] == "bereit"
    return motion


def _pair(probe):
    sent: list[tuple[str, float]] = []

    def transport(direction: str, rate: float) -> bool:
        sent.append((direction, rate))
        return True

    motion = _ready()
    mover = NinaMountMover("http://127.0.0.1:1888/v2/api")
    mover.set_guard(
        block_probe=probe,
        on_halt=lambda result: motion.note_axis_stop(result.rate0_sent) if result.rate0_sent or motion.manual_axis_active() else None,
        transport=transport,
    )
    return motion, mover, sent


def test_phd2_axis_rules_are_stricter_than_goto() -> None:
    assert phd2_blocks_axis(None) == "PHD2-Zustand nicht lesbar"
    assert phd2_blocks_axis(Status("")) == "PHD2-Zustand nicht lesbar"
    assert phd2_blocks_axis(Status("OFFLINE")) == "PHD2 nicht erreichbar"
    assert phd2_blocks_axis(Status("CONNECTING")) == "PHD2 nicht erreichbar"
    assert phd2_blocks_axis(Status("GUIDING")) == "PHD2 führt"
    assert phd2_blocks_axis(Status("CONNECTED", True)) == "PHD2 führt"
    assert phd2_blocks_axis(Status("CALIBRATING")) == "PHD2 kalibriert"
    assert phd2_blocks_axis(Status("CONNECTED")) == ""
    assert phd2_blocks_goto(Status("OFFLINE")) == ""


def test_allowed_move_and_repeated_pulses_do_not_stop() -> None:
    motion, mover, sent = _pair(lambda: "")
    assert motion.reserve_move().ok
    assert mover.move("east", 0.01, now=0).ok
    assert mover.move("east", 0.01, now=1.2).ok
    mover.tick(now=2.0)
    assert all(rate > 0 for _, rate in sent)
    assert motion.view()["state"] == "faehrt"


def test_missing_pulses_send_rate0_and_leave_standstill_open() -> None:
    motion, mover, sent = _pair(lambda: "")
    assert motion.reserve_move().ok
    assert mover.move("north", 0.01, now=0).ok
    mover.tick(now=IDLE_STOP_S + 0.1)
    assert ("north", 0.0) in sent or ("east", 0.0) in sent
    assert motion.view()["state"] == "stoppt"
    assert motion.view()["detail"] == "Rate 0 gesendet, Stillstand offen"
    assert motion.view()["state"] != "bereit"


def test_guiding_calibration_and_unreadable_reject_before_motion() -> None:
    for reason in ("PHD2 führt", "PHD2 kalibriert", "PHD2-Zustand nicht lesbar", "PHD2 nicht erreichbar"):
        motion, mover, sent = _pair(lambda reason=reason: reason)
        refused = mover.move("west", 0.01, now=0)
        assert not refused.ok
        assert refused.error == reason
        assert sent == []
        assert motion.view()["state"] == "bereit"


def test_guiding_that_starts_during_a_move_sends_rate0() -> None:
    state = {"reason": ""}
    motion, mover, sent = _pair(lambda: state["reason"])
    assert motion.reserve_move().ok
    assert mover.move("east", 0.01, now=0).ok
    state["reason"] = "PHD2 führt"
    again = mover.move("east", 0.01, now=0.2)
    assert not again.ok
    assert again.rate0_sent
    assert motion.view()["detail"] == "Rate 0 gesendet, Stillstand offen"


def test_goto_while_axis_moves_is_refused_and_axis_stop_does_not_clear_goto() -> None:
    motion, mover, sent = _pair(lambda: "")
    assert motion.reserve_move().ok
    refused = motion.reserve_goto(_idle())
    assert not refused.ok
    assert refused.error == "Achsbewegung aktiv"
    motion = _ready()
    motion.reserve_goto(_idle())
    assert motion.kind_is_goto()
    before = len(sent)
    motion.finish_move(True)
    motion.note_axis_stop(False)
    assert motion.view()["state"] == "faehrt"
    assert len(sent) == before
    text = Path("app_mele/main_app.py").read_text(encoding="utf-8")
    stop = text.index("async def nina_mount_move_stop")
    body = text[stop:text.index('@app.get("/network/wifi")', stop)]
    assert "kind_is_goto" in body
    assert "/equipment/mount/slew" not in body


def test_successful_stop_is_not_standstill_and_failed_stop_is_not_ready() -> None:
    motion, mover, sent = _pair(lambda: "")
    assert motion.reserve_move().ok
    mover.move("east", 0.01, now=0)
    stopped = mover.stop(now=0.2)
    assert stopped.rate0_sent
    assert stopped.ok
    assert motion.view()["state"] == "stoppt"
    motion.note(_idle())
    assert motion.view()["state"] == "bereit"

    def fail(direction: str, rate: float) -> bool:
        sent.append((direction, rate))
        return False

    motion, mover, sent = _pair(lambda: "")
    mover.set_guard(transport=fail)
    assert motion.reserve_move().ok
    mover.move("east", 0.01, now=0)
    sent.clear()
    failed = mover.stop(now=0.2)
    assert not failed.ok
    assert not failed.rate0_sent
    assert failed.error
    assert motion.view()["state"] == "unklar"
    assert motion.view()["detail"] == "Rate 0 nicht gesendet"
    motion.note(_idle())
    motion.note(_idle())
    assert motion.view()["state"] == "unklar"


def test_websocket_loss_and_retry_without_a_burst() -> None:
    motion, mover, sent = _pair(lambda: "")
    failed_once = {"n": 0}

    def flaky(direction: str, rate: float) -> bool:
        sent.append((direction, float(rate)))
        if rate == 0 and failed_once["n"] == 0:
            failed_once["n"] = 1
            raise ConnectionError("websocket verloren")
        return True

    mover.set_guard(transport=flaky)
    assert motion.reserve_move().ok
    assert mover.move("south", 0.01, now=0).ok
    failed = mover.stop(now=1)
    assert not failed.rate0_sent
    assert "websocket verloren" in failed.error
    first = len(sent)
    mover.tick(now=1 + KEEPALIVE_S / 2)
    assert len(sent) == first
    mover.tick(now=1 + KEEPALIVE_S)
    assert any(item[0] == "east" and item[1] == 0 for item in sent[first:])
    assert motion.view()["detail"] == "Rate 0 gesendet, Stillstand offen"
    again = mover.stop(now=3)
    assert again.rate0_sent


def test_deadman_runs_while_a_move_request_is_blocked() -> None:
    motion = _ready()
    entered = threading.Event()
    release = threading.Event()
    sent: list[tuple[str, float]] = []

    def transport(direction: str, rate: float) -> bool:
        if rate > 0:
            entered.set()
            assert release.wait(timeout=2)
            return True
        sent.append((direction, rate))
        return True

    mover = NinaMountMover("http://127.0.0.1:1888/v2/api")
    mover.set_guard(
        block_probe=lambda: "",
        on_halt=lambda result: motion.note_axis_stop(result.rate0_sent),
        transport=transport,
    )
    assert motion.reserve_move().ok
    holder: dict = {}

    def run() -> None:
        holder["result"] = mover.move("east", 0.01, now=0)

    worker = threading.Thread(target=run)
    worker.start()
    assert entered.wait(timeout=2)
    mover.tick(now=IDLE_STOP_S + 1)
    release.set()
    worker.join(timeout=2)
    assert sent
    assert all(rate == 0 for _, rate in sent)
    assert motion.view()["state"] == "stoppt"
    assert not holder["result"].ok


def test_keepalive_thread_calls_tick_and_process_death_cannot_send() -> None:
    mover = NinaMountMover("http://127.0.0.1:1888/v2/api")
    called = threading.Event()

    def fake_tick(now: float | None = None) -> None:
        called.set()
        mover._stop.set()

    mover.tick = fake_tick  # type: ignore[method-assign]
    mover._keepalive_loop()
    assert called.is_set()

    motion, mover, sent = _pair(lambda: "")

    def down(direction: str, rate: float) -> bool:
        raise ConnectionError("prozess kann nicht senden")

    mover.set_guard(transport=down)
    assert motion.reserve_move().ok
    mover._direction = "east"
    mover._rate = 0.01
    mover._last_cmd_mono = 0
    mover.tick(now=IDLE_STOP_S + 1)
    assert motion.view()["detail"] == "Rate 0 nicht gesendet"
    motion.note(_idle())
    assert motion.view()["state"] == "unklar"
    assert motion.view()["state"] != "bereit"
