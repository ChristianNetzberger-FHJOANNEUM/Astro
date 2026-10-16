"""Ein Capture-Auftrag im MeLE-Prozess.

Desktop und Quest starten, beobachten und stoppen denselben Auftrag.
Die Serie überlebt das Schließen des Browsers. Ein Prozessneustart setzt
den Auftrag auf idle und setzt ihn nicht als erfolgreich fort.
"""

from __future__ import annotations

import threading
import uuid
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable

from fastapi import FastAPI, Request
from fastapi.responses import FileResponse, JSONResponse, Response

from mele.astro_manager import (
    FRAME_TYPE_DARK,
    FRAME_TYPE_LIGHT,
    get_profile,
    get_session,
    list_profiles,
    list_sessions,
    normalize_frame_type,
)
from mele.session_storage import LIFECYCLE_CLOSED

STATE_IDLE = "idle"
STATE_RUNNING = "running"
STATE_STOP_REQUESTED = "stop_requested"
STATE_COMPLETED = "completed"
STATE_STOPPED = "stopped"
STATE_FAILED = "failed"
ACTIVE_STATES = frozenset({STATE_RUNNING, STATE_STOP_REQUESTED})
TERMINAL_STATES = frozenset({STATE_COMPLETED, STATE_STOPPED, STATE_FAILED})
# Bedienstufen der Quest, keine Behauptung über die Kamera. Grenzen der Kamera filtern sie.
EXPOSURE_STEPS_S = (0.5, 1.0, 2.0, 4.0, 5.0, 8.0, 10.0, 15.0, 20.0, 30.0, 45.0, 60.0, 90.0, 120.0, 180.0, 300.0)
FRAME_MIN = 1
FRAME_MAX = 999


@dataclass
class CaptureSnapshot:
    job_id: int
    catalog_key: str
    session_id: int
    display_name: str
    image_type: str
    exposure_s: float
    gain: float | None
    iso: int | None
    planned: int
    local_path: str
    archive_path: str
    session_completed: int
    session_planned: int | None


@dataclass
class CaptureFrameResult:
    ok: bool
    error: str = ""
    file_name: str | None = None
    session_completed: int | None = None
    session_planned: int | None = None


CaptureFn = Callable[[CaptureSnapshot], CaptureFrameResult]
ProbeLightFn = Callable[[CaptureSnapshot, str], None]


@dataclass
class _Job:
    snapshot: CaptureSnapshot
    state: str = STATE_RUNNING
    saved: int = 0
    failed_frames: int = 0
    current_file: str | None = None
    error: str = ""
    session_completed: int = 0
    session_planned: int | None = None

    def public(self, *, epoch: str) -> dict[str, Any]:
        snap = self.snapshot
        return {
            "job_id": snap.job_id,
            "state": self.state,
            "process_epoch": epoch,
            "resumable": False,
            "catalog_key": snap.catalog_key,
            "session_id": snap.session_id,
            "display_name": snap.display_name,
            "image_type": snap.image_type,
            "exposure_s": snap.exposure_s,
            "gain": snap.gain,
            "iso": snap.iso,
            "planned": snap.planned,
            "saved": self.saved,
            "failed_frames": self.failed_frames,
            "current_file": self.current_file,
            "error": self.error,
            "session_completed": self.session_completed,
            "session_planned": self.session_planned,
        }


@dataclass
class _Choice:
    ok: bool
    status: int = 200
    error: str = ""
    code: str = ""
    session: Any = None
    candidates: list[dict[str, Any]] = field(default_factory=list)


def choose_open_session(
    *,
    catalog_key: str,
    session_id: int | None,
    db_path: Path,
) -> _Choice:
    """Genau eine offene Session, oder die ausdrücklich genannte.

    Geschlossene Sessions zählen nicht. Mehrere offene Sessions werden nicht
    stillschweigend aufgelöst. Es wird keine Session angelegt.
    """
    key = str(catalog_key or "").strip()
    if session_id is not None:
        session = get_session(int(session_id), db_path=db_path)
        if session is None:
            return _Choice(False, 404, f"Unbekannte Session: {session_id}", "session_missing")
        if key and session.catalog_key != key:
            return _Choice(False, 409, "Session gehört nicht zum Objekt.", "session_mismatch")
        if session.lifecycle_status == LIFECYCLE_CLOSED:
            return _Choice(False, 409, "Session ist geschlossen.", "session_closed")
        return _Choice(True, session=session)

    if not key:
        return _Choice(False, 400, "Objekt fehlt.", "params")
    rows = [
        row
        for row in list_sessions(key, db_path=db_path)
        if row.lifecycle_status != LIFECYCLE_CLOSED
    ]
    if not rows:
        return _Choice(
            False,
            409,
            "Keine offene Session für dieses Objekt. Am Desktop anlegen, hier wird keine erzeugt.",
            "session_missing",
        )
    if len(rows) > 1:
        return _Choice(
            False,
            409,
            "Mehrere offene Sessions. Auswahl am Desktop, die Quest wählt nicht selbst.",
            "session_ambiguous",
            candidates=[_session_brief(row) for row in rows],
        )
    return _Choice(True, session=rows[0])


def _session_brief(session: Any) -> dict[str, Any]:
    return {
        "id": int(session.id),
        "catalog_key": session.catalog_key,
        "lifecycle_status": session.lifecycle_status,
        "started_utc": session.started_utc,
        "lights_planned": session.lights_planned,
        "lights_completed": session.lights_completed,
        "darks_planned": session.darks_planned,
        "darks_completed": session.darks_completed,
    }


class CaptureJobService:
    def __init__(
        self,
        *,
        db_path: Path,
        capture_one: CaptureFn,
        epoch: str | None = None,
        on_probe_light: ProbeLightFn | None = None,
    ) -> None:
        self.db_path = db_path
        self._capture_one = capture_one
        self._on_probe_light = on_probe_light
        self.epoch = epoch or uuid.uuid4().hex
        self._lock = threading.Lock()
        self._stop = threading.Event()
        self._job: _Job | None = None
        self._next_id = 1
        self._direct = 0
        self._thread: threading.Thread | None = None

    def inflight_count(self) -> int:
        with self._lock:
            active = 1 if (self._job is not None and self._job.state in ACTIVE_STATES) else 0
            return active + self._direct

    def try_begin_direct(self) -> bool:
        """Einzelbild der bisherigen Route. False, solange irgendeine Aufnahme läuft."""
        with self._lock:
            if self._direct > 0:
                return False
            if self._job is not None and self._job.state in ACTIVE_STATES:
                return False
            if self._thread is not None and self._thread.is_alive():
                return False
            self._direct += 1
            return True

    def end_direct(self) -> None:
        with self._lock:
            self._direct = max(0, self._direct - 1)

    def status_body(self) -> dict[str, Any]:
        with self._lock:
            job = None if self._job is None else self._job.public(epoch=self.epoch)
            state = STATE_IDLE if job is None else str(job["state"])
        return {
            "ok": True,
            "state": state,
            "process_epoch": self.epoch,
            "resumable": False,
            "job": job,
        }

    def context(self, catalog_key: str, camera_payload: dict[str, Any] | None) -> dict[str, Any]:
        """Quest-Anzeige. Ein laufender Auftrag verdrängt den Entwurf."""
        status = self.status_body()
        job = status.get("job")
        locked = bool(job and job.get("state") in ACTIVE_STATES)
        camera = _camera_brief(camera_payload)
        body: dict[str, Any] = {
            "ok": True,
            "process_epoch": status["process_epoch"],
            "resumable": False,
            "camera": camera,
            "job": job,
            "locked": locked,
            "exposure_steps_s": exposure_steps(camera.get("exposure_min"), camera.get("exposure_max")),
            "iso_steps": [],
            "iso_adjustable": False,
            "frame_min": FRAME_MIN,
            "frame_max": FRAME_MAX,
        }
        if locked and isinstance(job, dict):
            session = get_session(int(job["session_id"]), db_path=self.db_path)
            body.update(
                session=None if session is None else _session_brief(session),
                session_code="job",
                session_message="Laufender Auftrag.",
                sessions=[],
                profile=None,
                profile_code="job",
                profile_message="Parameter kommen vom laufenden Auftrag.",
            )
            _apply_iso_offer(
                body,
                camera_payload,
                job.get("iso"),
                enabled=_iso_enabled(session, camera_payload, self.db_path),
            )
            _attach_camera_view(body, session, camera_payload, self.db_path)
            return body
        key = str(catalog_key or "").strip()
        if not key:
            body.update(
                session=None,
                session_code="no_object",
                session_message="Objekt auf der Quest wählen.",
                sessions=[],
                profile=None,
                profile_code="no_object",
                profile_message="Objekt auf der Quest wählen.",
            )
            _apply_iso_offer(body, camera_payload, None, enabled=False)
            _attach_camera_view(body, None, camera_payload, self.db_path)
            return body
        choice = choose_open_session(catalog_key=key, session_id=None, db_path=self.db_path)
        profile, profile_code, profile_message = _profile_choice(
            key,
            None if choice.session is None else choice.session.profile_id,
            self.db_path,
        )
        body.update(
            session=None if choice.session is None else _session_brief(choice.session),
            session_code=choice.code or "ok",
            session_message="" if choice.ok else choice.error,
            sessions=choice.candidates,
            profile=None if profile is None else _profile_brief(profile),
            profile_code=profile_code,
            profile_message=profile_message,
        )
        fallback_iso = None
        if choice.session is not None and choice.session.iso is not None:
            fallback_iso = choice.session.iso
        elif profile is not None and profile.iso is not None:
            fallback_iso = profile.iso
        enabled = _iso_enabled(choice.session, camera_payload, self.db_path)
        _apply_iso_offer(body, camera_payload, fallback_iso, enabled=enabled)
        _attach_camera_view(body, choice.session, camera_payload, self.db_path)
        if profile is None and choice.session is not None and choice.session.recipe_id is not None:
            from mele.camera_model import get_recipe

            recipe = get_recipe(int(choice.session.recipe_id), db_path=self.db_path)
            if recipe is not None:
                profile = _RecipeView(
                    recipe.id,
                    recipe.name,
                    choice.session.exposure_s,
                    choice.session.gain,
                    choice.session.iso,
                )
                profile_code = "recipe"
                profile_message = "Rezept der Session. Die Bildanzahl bleibt am Auftrag."
                body["profile"] = _profile_brief(profile)
                body["profile_code"] = profile_code
                body["profile_message"] = profile_message
        return body

    def start_from_body(
        self,
        body: dict[str, Any],
        camera_payload: dict[str, Any] | None = None,
    ) -> tuple[int, dict[str, Any]]:
        catalog_key = str(body.get("catalog_key") or "").strip()
        session_id = _opt_int(body.get("session_id"))
        choice = choose_open_session(
            catalog_key=catalog_key,
            session_id=session_id,
            db_path=self.db_path,
        )
        if not choice.ok or choice.session is None:
            return choice.status, _error_body(choice.error, choice.code, choice.candidates)

        session = choice.session
        key = catalog_key or session.catalog_key
        image_type = normalize_frame_type(
            str(body.get("image_type") or body.get("frame_type") or FRAME_TYPE_LIGHT)
        )
        exposure = _opt_float(body.get("exposure_s"))
        if exposure is None:
            exposure = session.exposure_s
        if exposure is None or float(exposure) < 0:
            return 400, _error_body("Belichtung fehlt.", "params")
        gain = _opt_float(body.get("gain"))
        if gain is None:
            gain = session.gain
        iso = _opt_int(body.get("iso"))
        if iso is None:
            iso = session.iso
        from mele.camera_model import camera_connection_problem, get_camera, iso_from_gains_enabled

        camera_row = None
        if session.camera_id is not None:
            camera_row = get_camera(int(session.camera_id), db_path=self.db_path)
        if camera_payload is not None:
            problem = camera_connection_problem(camera_row, camera_payload)
            if problem is not None:
                return 409, _error_body(problem[1], problem[0])
        gain, iso = bind_nina_gain(
            gain=gain,
            iso=iso,
            camera_payload=camera_payload,
            iso_from_gains=iso_from_gains_enabled(camera_row, camera_payload),
        )

        if "frames" in body and body.get("frames") not in (None, ""):
            frames = _opt_int(body.get("frames"))
            if frames is None:
                return 400, _error_body("Bildanzahl ungültig.", "params")
        else:
            frames = None
        if image_type == FRAME_TYPE_DARK:
            done = int(session.darks_completed or 0)
            plan = session.darks_planned
        else:
            done = int(session.lights_completed or session.frames_completed or 0)
            plan = session.lights_planned if session.lights_planned is not None else session.frames_planned
        if frames is None:
            if plan is None:
                return 400, _error_body("Bildanzahl fehlt.", "params")
            frames = max(0, int(plan) - done)
            if frames < 1:
                return 409, _error_body("Nichts mehr zu capturen.", "nothing_to_capture")
        if frames < 1:
            return 400, _error_body("Bildanzahl muss mindestens 1 sein.", "params")

        display_name = str(body.get("display_name") or "").strip()
        local_path = str(body.get("local_path") or "").strip() or (session.local_path or "")
        archive_path = str(body.get("archive_path") or "").strip() or (session.archive_path or "")
        session_planned = None if plan is None else int(plan)

        with self._lock:
            if self._direct > 0 or (self._job is not None and self._job.state in ACTIVE_STATES):
                return 409, _error_body("Es läuft bereits ein Aufnahmeauftrag.", "busy", job=self._public_unlocked())
            if self._thread is not None and self._thread.is_alive():
                return 409, _error_body("Es läuft bereits ein Aufnahmeauftrag.", "busy", job=self._public_unlocked())
            snap = CaptureSnapshot(
                job_id=self._next_id,
                catalog_key=key,
                session_id=int(session.id),
                display_name=display_name,
                image_type=image_type,
                exposure_s=float(exposure),
                gain=None if gain is None else float(gain),
                iso=None if iso is None else int(iso),
                planned=int(frames),
                local_path=local_path,
                archive_path=archive_path,
                session_completed=done,
                session_planned=session_planned,
            )
            self._next_id += 1
            self._stop.clear()
            self._job = _Job(
                snapshot=snap,
                state=STATE_RUNNING,
                session_completed=done,
                session_planned=session_planned,
            )
            worker = threading.Thread(
                target=self._run,
                args=(snap.job_id,),
                name=f"capture-job-{snap.job_id}",
                daemon=True,
            )
            self._thread = worker
            worker.start()
            payload = self.status_body_unlocked()
        return 200, payload

    def stop(self) -> tuple[int, dict[str, Any]]:
        with self._lock:
            job = self._job
            if job is None or job.state not in ACTIVE_STATES:
                return 409, _error_body("Kein laufender Aufnahmeauftrag.", "idle", job=self._public_unlocked())
            if job.state != STATE_STOP_REQUESTED:
                job.state = STATE_STOP_REQUESTED
            self._stop.set()
            payload = self.status_body_unlocked()
        return 200, payload

    def _run(self, job_id: int) -> None:
        try:
            while True:
                with self._lock:
                    job = self._job
                    if job is None or job.snapshot.job_id != job_id:
                        return
                    if job.saved >= job.snapshot.planned:
                        job.state = STATE_COMPLETED
                        job.error = ""
                        return
                    if self._stop.is_set() or job.state == STATE_STOP_REQUESTED:
                        job.state = STATE_STOPPED
                        return
                    job.state = STATE_RUNNING
                    snap = job.snapshot
                fresh = get_session(snap.session_id, db_path=self.db_path)
                if (
                    fresh is None
                    or fresh.lifecycle_status == LIFECYCLE_CLOSED
                    or fresh.catalog_key != snap.catalog_key
                ):
                    self._fail(job_id, "Session ist nicht mehr offen.")
                    return
                try:
                    result = self._capture_one(snap)
                except Exception as exc:  # noqa: BLE001
                    self._fail(job_id, str(exc) or "Aufnahme fehlgeschlagen")
                    return
                probe: tuple[CaptureSnapshot, str] | None = None
                with self._lock:
                    job = self._job
                    if job is None or job.snapshot.job_id != job_id:
                        return
                    if result.ok:
                        job.saved += 1
                        job.current_file = result.file_name
                        job.error = ""
                        if result.session_completed is not None:
                            job.session_completed = int(result.session_completed)
                        if result.session_planned is not None:
                            job.session_planned = int(result.session_planned)
                        snap = job.snapshot
                        if (
                            self._on_probe_light is not None
                            and snap.planned == 1
                            and snap.image_type == FRAME_TYPE_LIGHT
                            and job.saved >= snap.planned
                            and result.file_name
                        ):
                            probe = (snap, str(result.file_name))
                    else:
                        job.failed_frames += 1
                        job.state = STATE_FAILED
                        job.error = result.error or "Aufnahme fehlgeschlagen"
                        return
                if probe is not None:
                    self._fire_probe(probe[0], probe[1])
        finally:
            with self._lock:
                job = self._job
                if job is not None and job.snapshot.job_id == job_id and job.state in ACTIVE_STATES:
                    job.state = STATE_FAILED
                    if not job.error:
                        job.error = "Auftrag unerwartet beendet."

    def _fire_probe(self, snapshot: CaptureSnapshot, file_name: str) -> None:
        """Eigenes Thread. Der Aufnahmeauftrag wartet nicht auf JPEG oder Histogramm."""
        callback = self._on_probe_light
        if callback is None:
            return

        def run() -> None:
            try:
                callback(snapshot, file_name)
            except Exception:  # noqa: BLE001
                return

        threading.Thread(target=run, name="probe-light", daemon=True).start()

    def _fail(self, job_id: int, error: str) -> None:
        with self._lock:
            job = self._job
            if job is None or job.snapshot.job_id != job_id:
                return
            job.state = STATE_FAILED
            job.error = error

    def _public_unlocked(self) -> dict[str, Any] | None:
        return None if self._job is None else self._job.public(epoch=self.epoch)

    def status_body_unlocked(self) -> dict[str, Any]:
        job = self._public_unlocked()
        state = STATE_IDLE if job is None else str(job["state"])
        return {
            "ok": True,
            "state": state,
            "process_epoch": self.epoch,
            "resumable": False,
            "job": job,
        }


def install_capture_routes(
    app: FastAPI,
    service: CaptureJobService,
    *,
    gate: Callable[[Request], JSONResponse | None] | None = None,
    camera_info: Callable[[], dict[str, Any]] | None = None,
    close_session: Callable[[int], tuple[int, dict[str, Any]]] | None = None,
    guide_image: Callable[[], tuple[bytes, dict[str, Any]]] | None = None,
    guide_star: Callable[[], tuple[bytes, dict[str, Any]]] | None = None,
) -> None:
    def _guard(request: Request) -> JSONResponse | None:
        if gate is None:
            return None
        return gate(request)

    @app.get("/astro/capture/context")
    def capture_context(catalog_key: str = "") -> JSONResponse:
        if camera_info is None:
            payload: dict[str, Any] = {"api_online": False, "error": "Kamera nicht abgefragt", "camera": None}
        else:
            try:
                payload = camera_info()
            except Exception as exc:  # noqa: BLE001
                payload = {"api_online": False, "error": str(exc), "camera": None}
        return JSONResponse(service.context(catalog_key, payload))

    @app.post("/astro/capture/start")
    async def capture_start(request: Request) -> JSONResponse:
        denied = _guard(request)
        if denied is not None:
            return denied
        try:
            body = await request.json()
        except Exception:
            return JSONResponse({"ok": False, "error": "JSON erwartet", "code": "json"}, status_code=400)
        if not isinstance(body, dict):
            return JSONResponse(
                {"ok": False, "error": "JSON-Objekt erwartet", "code": "json"},
                status_code=400,
            )
        camera_payload = None
        if camera_info is not None:
            try:
                camera_payload = camera_info()
            except Exception:  # noqa: BLE001
                camera_payload = None
        status, payload = service.start_from_body(body, camera_payload=camera_payload)
        return JSONResponse(payload, status_code=status)

    @app.post("/astro/capture/session-close")
    async def capture_session_close(request: Request) -> JSONResponse:
        """Quest: Session schließen. Der bestehende Close schreibt das Wetter mit."""
        denied = _guard(request)
        if denied is not None:
            return denied
        if close_session is None:
            return JSONResponse({"ok": False, "error": "Schließen nicht verbunden"}, status_code=404)
        try:
            body = await request.json()
        except Exception:
            return JSONResponse({"ok": False, "error": "JSON erwartet", "code": "json"}, status_code=400)
        if not isinstance(body, dict):
            return JSONResponse({"ok": False, "error": "JSON-Objekt erwartet", "code": "json"}, status_code=400)
        try:
            session_id = int(body.get("session_id"))
        except (TypeError, ValueError):
            return JSONResponse({"ok": False, "error": "Session fehlt.", "code": "params"}, status_code=400)
        status, payload = close_session(session_id)
        return JSONResponse(payload, status_code=status)

    @app.post("/astro/capture/stop")
    def capture_stop(request: Request) -> JSONResponse:
        denied = _guard(request)
        if denied is not None:
            return denied
        status, payload = service.stop()
        return JSONResponse(payload, status_code=status)

    @app.get("/astro/capture/status")
    def capture_status() -> JSONResponse:
        return JSONResponse(service.status_body())

    @app.get("/astro/capture/preview")
    def capture_preview(session_id: int = 0, source: str = "light_preview") -> JSONResponse:
        from mele.frame_analysis import (
            SOURCE_GUIDE_PREVIEW,
            SOURCE_GUIDE_STAR,
            read_guide_preview,
            read_light_preview,
        )

        wanted = str(source or "").strip()
        if wanted == SOURCE_GUIDE_PREVIEW:
            status, payload = read_guide_preview(guide_image, source=SOURCE_GUIDE_PREVIEW)
            return JSONResponse(payload, status_code=status)
        if wanted == SOURCE_GUIDE_STAR:
            status, payload = read_guide_preview(guide_star, source=SOURCE_GUIDE_STAR)
            return JSONResponse(payload, status_code=status)
        status, payload = read_light_preview(session_id, db_path=service.db_path, source=source)
        if isinstance(payload, dict):
            payload["sources"] = ["light_preview", SOURCE_GUIDE_PREVIEW]
        return JSONResponse(payload, status_code=status)

    @app.get("/astro/capture/preview/file", response_model=None)
    def capture_preview_file(session_id: int = 0, source: str = "light_preview"):
        from mele.frame_analysis import (
            SOURCE_GUIDE_PREVIEW,
            SOURCE_GUIDE_STAR,
            guide_status_text,
            light_preview_file,
        )

        wanted = str(source or "").strip()
        if wanted in {SOURCE_GUIDE_PREVIEW, SOURCE_GUIDE_STAR}:
            fetch = guide_image if wanted == SOURCE_GUIDE_PREVIEW else guide_star
            star = wanted == SOURCE_GUIDE_STAR
            if fetch is None:
                return JSONResponse(
                    {"ok": False, "error": "Quelle noch nicht vorhanden", "source": wanted},
                    status_code=404,
                )
            try:
                jpeg, _meta = fetch()
            except Exception as exc:  # noqa: BLE001
                return JSONResponse(
                    {"ok": False, "error": guide_status_text(str(exc), star=star), "source": wanted},
                    status_code=404,
                )
            if not jpeg:
                missing = "Kein Leitstern" if star else "Kein Guiding-Bild"
                return JSONResponse(
                    {"ok": False, "error": missing, "source": wanted},
                    status_code=404,
                )
            return Response(content=jpeg, media_type="image/jpeg", headers={"Cache-Control": "no-store"})
        status, payload = light_preview_file(session_id, db_path=service.db_path)
        if status != 200 or not isinstance(payload, Path):
            body = payload if isinstance(payload, dict) else {"ok": False, "error": "Preview fehlt"}
            return JSONResponse(body, status_code=status)
        return FileResponse(payload, media_type="image/jpeg", filename=payload.name)


def confirmed_iso_steps(
    camera_payload: dict[str, Any] | None,
    *,
    enabled: bool = False,
) -> list[int]:
    """ISO-Stufen nur aus der Gain-Liste, und nur wenn die Kamera das so meldet.

    Der Lumix-Treiber legt die ISO-Werte der S5IIX in NINA unter ``Gains`` ab.
    Das gilt nicht für eine andere Kamera. GainMin und GainMax ergeben keine Stufen.
    """
    if not enabled:
        return []
    raw = camera_payload if isinstance(camera_payload, dict) else {}
    camera = raw.get("camera") if isinstance(raw.get("camera"), dict) else {}
    gains = camera.get("gains")
    if not isinstance(gains, (list, tuple)) or len(gains) < 2:
        return []
    steps: list[int] = []
    seen: set[int] = set()
    for item in gains:
        if isinstance(item, bool):
            continue
        try:
            number = float(item)
        except (TypeError, ValueError):
            continue
        if not number.is_integer() or number <= 0:
            continue
        step = int(number)
        if step in seen:
            continue
        seen.add(step)
        steps.append(step)
    steps.sort()
    return steps if len(steps) >= 2 else []


def iso_offer(
    camera_payload: dict[str, Any] | None,
    fallback_iso: Any,
    *,
    enabled: bool = False,
) -> tuple[list[int], bool]:
    """Bestätigte Stufen, sonst nur der gespeicherte ISO-Wert, dann nicht veränderbar."""
    steps = confirmed_iso_steps(camera_payload, enabled=enabled)
    if steps:
        return steps, True
    try:
        value = int(fallback_iso)
    except (TypeError, ValueError):
        return [], False
    if value > 0:
        return [value], False
    return [], False


def select_iso_step(steps: list[int], current: Any, direction: int) -> int | None:
    """Nächste Stufe der Liste. Kein Zwischenwert, kein Verlassen der Grenzen."""
    list_ = []
    for item in steps:
        try:
            number = int(item)
        except (TypeError, ValueError):
            continue
        if number > 0:
            list_.append(number)
    if not list_:
        try:
            return int(current)
        except (TypeError, ValueError):
            return None
    try:
        value = int(current)
    except (TypeError, ValueError):
        return list_[-1] if direction < 0 else list_[0]
    if direction > 0:
        for step in list_:
            if step > value:
                return step
        return list_[-1]
    for step in reversed(list_):
        if step < value:
            return step
    return list_[0]


def bind_nina_gain(
    *,
    gain: float | None,
    iso: int | None,
    camera_payload: dict[str, Any] | None,
    iso_from_gains: bool = False,
) -> tuple[float | None, int | None]:
    """ISO der Lumix geht als NINA-Gain an die Aufnahme.

    Steht der gewählte ISO-Wert in der Gain-Liste der Kamera, ersetzt er einen
    davon abweichenden gespeicherten Gain. Ohne diese Liste bleibt die bisherige
    Regel: ein gesetzter Gain hat Vorrang, fehlt er, wird die ISO-Zahl als Gain
    geschickt. Die Zahl bei NINA ist noch kein Beleg für die Empfindlichkeit der Datei.
    Eine andere Kamera benutzt diese Gain-Liste nicht als ISO.
    """
    steps = confirmed_iso_steps(camera_payload, enabled=iso_from_gains)
    if iso is not None and int(iso) in steps:
        return float(int(iso)), int(iso)
    if gain is None and iso is not None:
        return float(iso), int(iso)
    stored_iso = None if iso is None else int(iso)
    return (None if gain is None else float(gain)), stored_iso


def _apply_iso_offer(
    body: dict[str, Any],
    camera_payload: dict[str, Any] | None,
    fallback_iso: Any,
    *,
    enabled: bool = False,
) -> None:
    steps, adjustable = iso_offer(camera_payload, fallback_iso, enabled=enabled)
    body["iso_steps"] = steps
    body["iso_adjustable"] = adjustable


def exposure_steps(exposure_min: Any, exposure_max: Any) -> list[float]:
    """Bedienstufen. Nur bei gemeldeten Kamera-Grenzen wird die Liste beschnitten."""
    try:
        lo = float(exposure_min) if exposure_min is not None else 0.0
        hi = float(exposure_max) if exposure_max is not None else 0.0
    except (TypeError, ValueError):
        lo, hi = 0.0, 0.0
    if hi > lo > 0:
        return [step for step in EXPOSURE_STEPS_S if lo <= step <= hi]
    return list(EXPOSURE_STEPS_S)


class _RecipeView:
    def __init__(
        self,
        recipe_id: int,
        label: str,
        exposure_s: float | None,
        gain: float | None,
        iso: int | None,
    ) -> None:
        self.id = recipe_id
        self.label = label
        self.exposure_s = exposure_s
        self.gain = gain
        self.iso = iso
        self.frames = None


def _iso_enabled(session: Any, camera_payload: dict[str, Any] | None, db_path: Path) -> bool:
    from mele.camera_model import get_camera, iso_from_gains_enabled

    if session is None or getattr(session, "camera_id", None) is None:
        return False
    camera = get_camera(int(session.camera_id), db_path=db_path)
    return iso_from_gains_enabled(camera, camera_payload)


def _attach_camera_view(
    body: dict[str, Any],
    session: Any,
    camera_payload: dict[str, Any] | None,
    db_path: Path,
) -> None:
    from mele.camera_model import get_camera

    camera = None
    if session is not None and getattr(session, "camera_id", None) is not None:
        camera = get_camera(int(session.camera_id), db_path=db_path)
    if camera is None:
        body["capabilities"] = {
            "iso": False,
            "gain": False,
            "offset": False,
            "binning": False,
            "roi": False,
            "cooling": False,
            "video": False,
            "still": False,
        }
    else:
        body["capabilities"] = camera.capabilities()
    brief = body.get("camera") if isinstance(body.get("camera"), dict) else {}
    body["camera_state"] = {
        "connected": bool(brief.get("connected")),
        "name": str(brief.get("name") or ""),
    }
    del camera_payload


def _camera_brief(payload: dict[str, Any] | None) -> dict[str, Any]:
    raw = payload if isinstance(payload, dict) else {}
    camera = raw.get("camera") if isinstance(raw.get("camera"), dict) else {}
    return {
        "api_online": bool(raw.get("api_online")),
        "connected": bool(camera.get("connected")),
        "name": str(camera.get("name") or ""),
        "exposure_min": camera.get("exposure_min"),
        "exposure_max": camera.get("exposure_max"),
        "error": str(raw.get("error") or ""),
    }


def _profile_brief(profile: Any) -> dict[str, Any]:
    return {
        "id": int(profile.id),
        "label": profile.label,
        "exposure_s": profile.exposure_s,
        "gain": profile.gain,
        "iso": profile.iso,
        "frames": profile.frames,
    }


def _profile_choice(
    catalog_key: str,
    profile_id: int | None,
    db_path: Path,
) -> tuple[Any, str, str]:
    if profile_id is not None:
        profile = get_profile(int(profile_id), db_path=db_path)
        if profile is not None:
            return profile, "ok", ""
    rows = list_profiles(catalog_key, db_path=db_path)
    if len(rows) == 1:
        return rows[0], "ok", ""
    if len(rows) > 1:
        return None, "ambiguous", "Mehrere Profile. Auswahl am Desktop."
    return None, "missing", "Kein Profil für dieses Objekt."


def _error_body(
    error: str,
    code: str,
    candidates: list[dict[str, Any]] | None = None,
    *,
    job: dict[str, Any] | None = None,
) -> dict[str, Any]:
    body: dict[str, Any] = {"ok": False, "error": error, "code": code}
    if candidates:
        body["sessions"] = candidates
    if job is not None:
        body["job"] = job
    return body


def _opt_int(value: object) -> int | None:
    if value is None or value == "":
        return None
    try:
        return int(value)  # type: ignore[arg-type]
    except (TypeError, ValueError):
        return None


def _opt_float(value: object) -> float | None:
    if value is None or value == "":
        return None
    try:
        return float(value)  # type: ignore[arg-type]
    except (TypeError, ValueError):
        return None
