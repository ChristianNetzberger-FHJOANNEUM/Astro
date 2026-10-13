"""Zugriffsschutz für GoTo und STOP. Keine reale Montierung."""

from __future__ import annotations

import threading
from pathlib import Path

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse
from fastapi.testclient import TestClient

from mele.mount_access import (
    CSRF_HEADER,
    SESSION_TTL_S,
    MountAccess,
    authorization,
    is_local_desktop,
)
from mele.mount_motion import MountMotion, MountSample

LOCAL = {"127.0.0.1", "::1", "192.168.0.176"}


def test_remote_without_session_is_refused() -> None:
    access = MountAccess()
    assert authorization(access, peer="192.168.0.50", via_edge=False, local_ips=LOCAL, cookie="", csrf="", now=10) == ""


def test_local_desktop_is_allowed_and_edge_is_not() -> None:
    access = MountAccess()
    assert is_local_desktop("127.0.0.1", False, LOCAL)
    assert is_local_desktop("::ffff:192.168.0.176", False, LOCAL)
    assert authorization(access, peer="127.0.0.1", via_edge=False, local_ips=LOCAL, cookie="", csrf="", now=10) == "desktop"
    assert authorization(access, peer="192.168.0.176", via_edge=False, local_ips=LOCAL, cookie="", csrf="", now=10) == "desktop"
    assert authorization(access, peer="127.0.0.1", via_edge=True, local_ips=LOCAL, cookie="", csrf="", now=10) == ""


def test_pair_session_csrf_and_expiry() -> None:
    access = MountAccess()
    code = access.issue_code(50)
    assert len(code) == 6 and code.isdigit()
    assert access.issue_code(10_000) == code
    assert access.pair("000000", 70) is None
    paired = access.pair(code, 80)
    assert paired is not None
    token, csrf, life = paired
    assert life == SESSION_TTL_S
    again = access.pair(code, 90)
    assert again is not None
    assert again[0] != token
    assert authorization(access, peer="192.168.0.50", via_edge=True, local_ips=LOCAL, cookie=token, csrf=csrf, now=100) == "session"
    assert authorization(access, peer="192.168.0.50", via_edge=True, local_ips=LOCAL, cookie=token, csrf="falsch-falsch-falsch", now=100) == ""
    assert authorization(access, peer="192.168.0.50", via_edge=False, local_ips=LOCAL, cookie=token, csrf="", now=100) == ""
    assert authorization(access, peer="10.0.0.8", via_edge=False, local_ips=LOCAL, cookie=token, csrf=csrf, now=100 + SESSION_TTL_S) == ""


def test_wrong_code_does_not_replace_it() -> None:
    access = MountAccess()
    code = access.issue_code(1)
    for _ in range(20):
        assert access.pair("999999", 2) is None
    assert access.issue_code(3) == code
    assert access.pair(code, 4) is not None


def test_code_persists_across_processes(tmp_path: Path) -> None:
    path = tmp_path / "mount-pair-code.txt"
    code = MountAccess(path).issue_code(1)
    assert MountAccess(path).issue_code(999_999) == code
    assert path.read_text(encoding="utf-8").strip() == code
    assert MountAccess(path).pair(code, 1 + 10 * SESSION_TTL_S) is not None


def test_http_remote_slew_and_stop_do_not_move_state() -> None:
    access = MountAccess()
    motion = MountMotion()
    motion.note(MountSample(online=True, connected=True))
    app = FastAPI()

    def allowed(request: Request) -> bool:
        return authorization(
            access,
            peer=request.client.host if request.client else "",
            via_edge=request.headers.get("x-astro-edge") == "caddy",
            local_ips={"127.0.0.1"},
            cookie=request.cookies.get("astro_mount", ""),
            csrf=request.headers.get(CSRF_HEADER, ""),
            now=100.0,
        ) != ""

    @app.post("/nina/mount/slew")
    def slew(request: Request) -> JSONResponse:
        if not allowed(request):
            return JSONResponse({"ok": False, "error": "Keine Montierungsberechtigung"}, status_code=401)
        reserved = motion.reserve_goto(MountSample(online=True, connected=True))
        return JSONResponse({"ok": reserved.ok}, status_code=200 if reserved.ok else 409)

    @app.post("/nina/mount/slew/stop")
    def stop(request: Request) -> JSONResponse:
        if not allowed(request):
            return JSONResponse({"ok": False, "error": "Keine Montierungsberechtigung"}, status_code=401)
        motion.begin_stop()
        return JSONResponse({"ok": True, "settled": False})

    with TestClient(app, client=("127.0.0.1", 50000)) as client:
        denied = client.post("/nina/mount/slew", headers={"X-Astro-Edge": "caddy"})
        assert denied.status_code == 401
        assert motion.view()["state"] == "bereit"
        stopped = client.post("/nina/mount/slew/stop", headers={"X-Astro-Edge": "caddy"})
        assert stopped.status_code == 401
        assert motion.view()["state"] == "bereit"
        desktop = client.post("/nina/mount/slew")
        assert desktop.status_code == 200
        blocked = client.post("/nina/mount/slew")
        assert blocked.status_code == 409
        halt = client.post("/nina/mount/slew/stop")
        assert halt.status_code == 200
        assert halt.json()["settled"] is False
        assert motion.view()["state"] == "stoppt"


def test_stop_during_open_start_is_not_blocked_for_a_session() -> None:
    access = MountAccess()
    code = access.issue_code(1)
    paired = access.pair(code, 2)
    assert paired is not None
    token, csrf, _ = paired
    motion = MountMotion()
    motion.note(MountSample(online=True, connected=True))
    entered = threading.Event()
    release = threading.Event()
    app = FastAPI()

    def allowed(request: Request) -> bool:
        return authorization(
            access,
            peer="10.1.1.8",
            via_edge=True,
            local_ips=LOCAL,
            cookie=request.cookies.get("astro_mount", ""),
            csrf=request.headers.get(CSRF_HEADER, ""),
            now=10.0,
        ) == "session"

    @app.post("/nina/mount/slew")
    def slew(request: Request) -> JSONResponse:
        if not allowed(request):
            return JSONResponse({"ok": False}, status_code=401)
        reserved = motion.reserve_goto(MountSample(online=True, connected=True))
        if not reserved.ok:
            return JSONResponse({"ok": False, "error": reserved.error}, status_code=409)
        entered.set()
        assert release.wait(timeout=5)
        follow = motion.complete_goto(reserved.generation, "ok")
        if follow.restop:
            motion.complete_stop("ok")
            return JSONResponse({"ok": False, "error": follow.error}, status_code=409)
        return JSONResponse({"ok": True})

    @app.post("/nina/mount/slew/stop")
    def stop(request: Request) -> JSONResponse:
        if not allowed(request):
            return JSONResponse({"ok": False}, status_code=401)
        motion.begin_stop()
        release.set()
        motion.complete_stop("ok")
        return JSONResponse({"ok": True, "settled": False, "motion": motion.view()})

    headers = {"X-Astro-Csrf": csrf}
    with TestClient(app) as client:
        client.cookies.set("astro_mount", token)
        first: dict = {}

        def run_first() -> None:
            response = client.post("/nina/mount/slew", headers=headers)
            first["status"] = response.status_code
            first["body"] = response.json()

        worker = threading.Thread(target=run_first)
        worker.start()
        assert entered.wait(timeout=5)
        second = client.post("/nina/mount/slew", headers=headers)
        halted = client.post("/nina/mount/slew/stop", headers=headers)
        worker.join(timeout=5)
    assert second.status_code == 409
    assert halted.status_code == 200
    assert halted.json()["settled"] is False
    assert first["status"] == 409
    assert motion.view()["state"] == "stoppt"


def test_dropped_cookie_does_not_stop_or_ready() -> None:
    access = MountAccess()
    code = access.issue_code(1)
    token, csrf, _ = access.pair(code, 2)  # type: ignore[misc]
    motion = MountMotion()
    motion.note(MountSample(online=True, connected=True))
    reserved = motion.reserve_goto(MountSample(online=True, connected=True))
    motion.complete_goto(reserved.generation, "ok")
    motion.note(MountSample(online=True, connected=True, slewing=True))
    assert motion.view()["state"] == "faehrt"
    assert authorization(access, peer="10.0.0.4", via_edge=True, local_ips=LOCAL, cookie="", csrf=csrf, now=5) == ""
    assert motion.view()["state"] == "faehrt"
    assert authorization(access, peer="10.0.0.4", via_edge=True, local_ips=LOCAL, cookie=token, csrf=csrf, now=5) == "session"


def test_quest_page_keeps_confirm_off_the_slew_request() -> None:
    text = Path("app_mele/vr.html").read_text(encoding="utf-8")
    show = text.index("function showQuestGoto")
    confirm = text.index("function confirmQuestGoto")
    assert "/nina/mount/slew" not in text[show:confirm]
    assert "/nina/mount/slew?" in text[confirm:confirm + 1800]
    assert "Keine feste Kopplung" not in text
    assert "astro_mount" not in text
