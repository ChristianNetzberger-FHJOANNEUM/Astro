"""XR-10c Stufe B2: Quest-Achse ohne reale Montierung."""

from __future__ import annotations

import threading
from pathlib import Path

from mele.axis_stick import DEADZONE, right_stick_usable, stick_direction, thumbstick_xy
from mele.mount_motion import MountMotion, MountSample
from mele.nina_mount_move import IDLE_STOP_S, QUEST_AXIS_RATE, QUEST_AXIS_RATES, NinaMountMover, parse_pulse_token, quest_axis_rate


def _ready() -> MountMotion:
    motion = MountMotion()
    motion.note(MountSample(online=True, connected=True, slewing=False, parked=False, age_s=0.0))
    assert motion.view()["state"] == "bereit"
    return motion


def _pair():
    sent: list[tuple[str, float]] = []

    def transport(direction: str, rate: float) -> bool:
        sent.append((direction, rate))
        return True

    motion = _ready()
    mover = NinaMountMover("http://127.0.0.1:1888/v2/api")
    mover.set_guard(
        block_probe=lambda: "",
        on_halt=lambda result: motion.note_axis_stop(result.rate0_sent) if result.rate0_sent or motion.manual_axis_active() else None,
        transport=transport,
    )
    return motion, mover, sent


def test_right_xr_standard_stick_and_existing_profiles() -> None:
    profiles = ["meta-quest-touch-plus", "oculus-touch", "generic-trigger", "generic-thumbstick"]
    assert right_stick_usable("right", "xr-standard", profiles, 4)
    assert right_stick_usable("right", "xr-standard", [], 2)
    assert not right_stick_usable("left", "xr-standard", profiles, 4)
    assert not right_stick_usable("right", "", profiles, 4)
    assert not right_stick_usable("right", "xr-standard", ["unknown-device"], 4)
    assert not right_stick_usable("right", "xr-standard", profiles, 1)


def test_quest_thumbstick_is_axes_two_and_three_not_the_touchpad() -> None:
    assert thumbstick_xy("", (0.0, 0.0, 0.9, 0.0)) is None
    assert thumbstick_xy("xr-standard", (0.9, -0.9, 0.0, 0.0)) == (0.0, -0.0)
    assert thumbstick_xy("xr-standard", (0.0, 0.0, 0.8, 0.0)) == (0.8, -0.0)
    assert thumbstick_xy("xr-standard", (0.0, 0.0, -0.8, 0.0)) == (-0.8, -0.0)
    up = thumbstick_xy("xr-standard", (0.0, 0.0, 0.0, -0.8))
    down = thumbstick_xy("xr-standard", (0.0, 0.0, 0.1, 0.9))
    assert up is not None and stick_direction(*up) == "north"
    assert down is not None and stick_direction(*down) == "south"
    assert stick_direction(*thumbstick_xy("xr-standard", (0.0, 0.0, 0.9, -0.2))) == "east"
    assert stick_direction(*thumbstick_xy("xr-standard", (0.0, 0.0, -0.9, 0.2))) == "west"


def test_deadzone_neutral_and_both_directions() -> None:
    assert stick_direction(0.0, 0.0) == ""
    assert stick_direction(DEADZONE - 0.01, 0.0) == ""
    assert stick_direction(0.0, -(DEADZONE - 0.01)) == ""
    assert stick_direction(0.8, 0.1) == "east"
    assert stick_direction(-0.8, 0.1) == "west"
    assert stick_direction(0.1, 0.8) == "north"
    assert stick_direction(0.1, -0.8) == "south"
    assert stick_direction(0.9, 0.4) == "east"
    assert stick_direction(0.3, -0.9) == "south"
    assert stick_direction(float("nan"), 1.0) == ""


def test_same_token_cannot_restart_after_stop_and_a_newer_token_can() -> None:
    motion, mover, sent = _pair()
    assert motion.reserve_move().ok
    assert mover.move("east", QUEST_AXIS_RATE, token=4, now=0).ok
    assert mover.move("east", 5.0, token=4, now=0.4).ok
    stopped = mover.stop(token=4, now=0.5)
    assert stopped.rate0_sent
    assert motion.view()["state"] == "stoppt"
    late = mover.move("west", QUEST_AXIS_RATE, token=4, now=2)
    assert not late.ok
    assert late.error == "Steuerimpuls überholt"
    assert all(rate == 0 or direction == "east" for direction, rate in sent)
    assert mover.status()["direction"] == ""
    motion.note(MountSample(online=True, connected=True, slewing=False, age_s=0.0))
    assert motion.view()["state"] == "bereit"
    assert motion.reserve_move().ok
    assert mover.move("north", QUEST_AXIS_RATE, token=5, now=3).ok
    assert ("north", QUEST_AXIS_RATE) in sent


def test_older_stop_does_not_clear_a_newer_activation() -> None:
    _motion, mover, sent = _pair()
    assert mover.move("east", QUEST_AXIS_RATE, token=2, now=0).ok
    discarded = mover.stop(token=1, now=0.2)
    assert discarded.message == "älterer Achsen-Stopp verworfen"
    assert mover.status()["direction"] == "east"
    assert not any(rate == 0 for _, rate in sent)
    late = mover.move("west", QUEST_AXIS_RATE, token=1, now=0.4)
    assert not late.ok
    assert mover.status()["direction"] == "east"


def test_desktop_without_token_still_moves_after_a_quest_stop() -> None:
    _motion, mover, sent = _pair()
    assert mover.move("south", 0.01, token=3, now=0).ok
    assert mover.stop(token=3, now=0.2).rate0_sent
    assert mover.move("south", 0.02, now=1).ok
    assert ("south", 0.02) in sent


def test_missing_pulses_and_blocked_request_do_not_resume_the_old_token() -> None:
    motion, mover, sent = _pair()
    assert motion.reserve_move().ok
    assert mover.move("north", QUEST_AXIS_RATE, token=7, now=0).ok
    mover.tick(now=IDLE_STOP_S + 0.1)
    assert motion.view()["state"] == "stoppt"
    assert mover.move("north", QUEST_AXIS_RATE, token=7, now=3).error == "Steuerimpuls überholt"

    entered = threading.Event()
    release = threading.Event()
    held: list[tuple[str, float]] = []

    def transport(direction: str, rate: float) -> bool:
        if rate > 0:
            entered.set()
            assert release.wait(timeout=2)
            return True
        held.append((direction, rate))
        return True

    motion = _ready()
    mover = NinaMountMover("http://127.0.0.1:1888/v2/api")
    mover.set_guard(
        block_probe=lambda: "",
        on_halt=lambda result: motion.note_axis_stop(result.rate0_sent),
        transport=transport,
    )
    box: dict = {}

    def run() -> None:
        box["result"] = mover.move("east", QUEST_AXIS_RATE, token=8, now=0)

    worker = threading.Thread(target=run)
    worker.start()
    assert entered.wait(timeout=2)
    mover.stop(token=8, now=0.2)
    release.set()
    worker.join(timeout=2)
    assert not box["result"].ok
    assert held
    assert mover.move("east", QUEST_AXIS_RATE, token=8, now=1).error == "Steuerimpuls überholt"


def test_invalid_token_and_quest_rate_constant() -> None:
    assert parse_pulse_token(None) == (None, "")
    assert parse_pulse_token("") == (None, "")
    assert parse_pulse_token("4") == (4, "")
    value, error = parse_pulse_token("nein")
    assert value is None and error
    assert QUEST_AXIS_RATE == 0.01
    assert quest_axis_rate(0.5) == (0.5, "")
    assert quest_axis_rate("0.02") == (0.02, "")
    assert quest_axis_rate(9)[0] is None
    assert quest_axis_rate("schnell")[0] is None
    assert QUEST_AXIS_RATES[-1] == 0.5


def test_vr_binding_keeps_select_and_uses_the_right_stick() -> None:
    text = Path("app_mele/vr.html").read_text(encoding="utf-8")
    assert 'dashboard: "select"' in text
    assert "selectstart" in text
    assert "selectend" in text
    assert "function questStickDirection" in text
    assert "function rightAxisGamepad" in text
    assert 'handedness !== "right"' in text
    assert 'mapping !== "xr-standard"' in text
    assert "pad.axes[2]" in text
    assert "pad.axes[3]" in text
    assert "const AXIS_DEADZONE = 0.2" in text
    assert "const AXIS_RATES = [0.005, 0.01, 0.02, 0.05, 0.1, 0.5]" in text
    assert "quest-axis-rate" in text
    assert "const AXIS_PULSE_MS = 400" in text
    assert "oculus-touch" in text
    assert "meta-quest-touch-plus" in text
    assert text.count("gamepad") >= 1
    stick = text[text.index("function questStickDirection"):text.index("function axisDirectionLabel")]
    assert '"east"' in stick and '"west"' in stick and '"north"' in stick and '"south"' in stick
    assert 'fetch("/nina/mount/slew/stop"' in text
    assert 'fetch("/nina/mount/move/stop"' in text
    assert 'fetch("/nina/mount/move"' in text
    assert "X-Astro-Csrf" in text[text.index("async function requestAxisStop"):text.index("async function sendAxisPulse")]
    assert "new WebSocket" not in text
    assert "MANUELLE ACHSE" in text
    assert "STOP ACHSE" in text
    poll = text[text.index("function pollAxisStick"):text.index("async function requestMountStop")]
    held = poll[poll.index('motionDetail === "Rate 0 nicht gesendet"'):poll.index("if (!direction)")]
    assert "slewing" not in held
    assert "requestAxisStop(token, true)" in held
    assert "quest-axis" in text
    assert "function requestMountStop" in text


def test_move_routes_keep_the_gate_and_caddy_opens_only_those_paths() -> None:
    app = Path("app_mele/main_app.py").read_text(encoding="utf-8")
    move = app[app.index("async def nina_mount_move"):app.index("async def nina_mount_move_stop")]
    stop = app[app.index("async def nina_mount_move_stop"):app.index('@app.get("/network/wifi")')]
    assert "_mount_gate" in move and "_mount_gate" in stop
    assert "pulse_rejected" in move
    assert "retire_pulse" in move
    assert "kind_is_goto" in move and "kind_is_goto" in stop
    assert "/equipment/mount/slew" not in stop
    assert "quest_axis_rate" in move
    assert "if motion.manual_axis_active():" in move
    mover = Path("mele/nina_mount_move.py").read_text(encoding="utf-8")
    assert mover.count("ping_interval=None") == 2
    caddy = Path(r"C:\Caddy\Caddyfile").read_text(encoding="utf-8")
    block = caddy[caddy.index("@mount_control"):caddy.index("handle @mount_control")]
    assert "/nina/mount/move/stop" in block
    assert "/nina/mount/move " in block or "/nina/mount/move/" in block or block.count("/nina/mount/move") >= 1
    assert "/nina/mount/slew/stop" in block
    assert "/mount-session/pair" in block
    assert "path /nina " not in caddy
    assert "path /nina*" not in caddy
    assert "/nina/mount/move/status" not in block
