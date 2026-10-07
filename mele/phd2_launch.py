"""PHD2-Desktop-App starten und Laufstatus pruefen.

Getrennt von mele.phd2 (Event-Server / JSON-RPC Client).
"""

from __future__ import annotations

import logging
import subprocess
import sys
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

DEFAULT_EXE = Path(r"C:\Program Files (x86)\PHDGuiding2\phd2.exe")
PROCESS_NAME = "phd2.exe"
CANDIDATE_EXES = (
    DEFAULT_EXE,
    Path(r"C:\Program Files\PHDGuiding2\phd2.exe"),
    Path.home() / "AppData" / "Local" / "Programs" / "PHDGuiding2" / "phd2.exe",
)


@dataclass(frozen=True)
class Phd2AppStatus:
    running: bool
    exe_path: str | None = None
    exe_exists: bool = False
    error: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class Phd2AppStartResult:
    ok: bool
    already_running: bool = False
    pid: int | None = None
    error: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def resolve_phd2_exe(configured: str | Path | None = None) -> Path:
    if configured:
        path = Path(str(configured))
        if path.is_dir():
            path = path / PROCESS_NAME
        return path
    for candidate in CANDIDATE_EXES:
        if candidate.is_file():
            return candidate
    return DEFAULT_EXE


def is_phd2_running(*, process_name: str = PROCESS_NAME) -> bool:
    """True, wenn mindestens eine phd2.exe-Instanz laeuft. Wirft nicht."""
    if sys.platform != "win32":
        return False
    try:
        creationflags = getattr(subprocess, "CREATE_NO_WINDOW", 0)
        completed = subprocess.run(
            ["tasklist", "/FI", f"IMAGENAME eq {process_name}", "/FO", "CSV", "/NH"],
            capture_output=True,
            text=True,
            timeout=5,
            creationflags=creationflags,
            check=False,
        )
        out = (completed.stdout or "") + (completed.stderr or "")
        return process_name.lower() in out.lower()
    except Exception:  # noqa: BLE001
        return False


def get_phd2_app_status(exe: str | Path | None = None) -> Phd2AppStatus:
    path = resolve_phd2_exe(exe)
    try:
        return Phd2AppStatus(
            running=is_phd2_running(),
            exe_path=str(path),
            exe_exists=path.is_file(),
        )
    except Exception as exc:  # noqa: BLE001
        return Phd2AppStatus(
            running=False,
            exe_path=str(path),
            exe_exists=path.is_file(),
            error=str(exc) or "PHD2-Status fehlgeschlagen",
        )


def start_phd2_app(exe: str | Path | None = None) -> Phd2AppStartResult:
    """Startet PHD2, falls noch nicht laufend. Wirft nicht."""
    path = resolve_phd2_exe(exe)
    if not path.is_file():
        return Phd2AppStartResult(ok=False, error=f"phd2.exe nicht gefunden: {path}")
    if is_phd2_running():
        return Phd2AppStartResult(ok=True, already_running=True)
    if sys.platform != "win32":
        return Phd2AppStartResult(ok=False, error="PHD2-Start nur unter Windows")
    try:
        flags = 0
        flags |= getattr(subprocess, "DETACHED_PROCESS", 0)
        flags |= getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0)
        proc = subprocess.Popen(  # noqa: S603 — konfigurierter lokaler Pfad
            [str(path)],
            cwd=str(path.parent),
            close_fds=True,
            creationflags=flags,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            stdin=subprocess.DEVNULL,
        )
        logger.info("PHD2 gestartet: %s (pid=%s)", path, proc.pid)
        return Phd2AppStartResult(ok=True, already_running=False, pid=proc.pid)
    except Exception as exc:  # noqa: BLE001
        return Phd2AppStartResult(ok=False, error=str(exc) or "Start fehlgeschlagen")
