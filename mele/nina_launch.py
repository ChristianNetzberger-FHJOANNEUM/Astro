"""NINA-Desktop-App starten und Laufstatus pruefen.

Getrennt von mele.nina (REST-Client zur Advanced API).
"""

from __future__ import annotations

import logging
import subprocess
import sys
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

DEFAULT_EXE = Path(r"C:\Program Files\N.I.N.A. - Nighttime Imaging 'N' Astronomy\NINA.exe")
PROCESS_NAME = "NINA.exe"


@dataclass(frozen=True)
class NinaAppStatus:
    running: bool
    exe_path: str | None = None
    exe_exists: bool = False
    error: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class NinaAppStartResult:
    ok: bool
    already_running: bool = False
    pid: int | None = None
    error: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def resolve_nina_exe(configured: str | Path | None = None) -> Path:
    if configured:
        path = Path(str(configured))
        if path.is_dir():
            path = path / PROCESS_NAME
        return path
    return DEFAULT_EXE


def is_nina_running(*, process_name: str = PROCESS_NAME) -> bool:
    """True, wenn mindestens eine NINA.exe-Instanz laeuft. Wirft nicht."""
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


def get_nina_app_status(exe: str | Path | None = None) -> NinaAppStatus:
    path = resolve_nina_exe(exe)
    try:
        return NinaAppStatus(
            running=is_nina_running(),
            exe_path=str(path),
            exe_exists=path.is_file(),
        )
    except Exception as exc:  # noqa: BLE001
        return NinaAppStatus(
            running=False,
            exe_path=str(path),
            exe_exists=path.is_file(),
            error=str(exc) or "NINA-Status fehlgeschlagen",
        )


def start_nina_app(exe: str | Path | None = None) -> NinaAppStartResult:
    """Startet die NINA-Desktop-App, falls noch nicht laufend. Wirft nicht."""
    path = resolve_nina_exe(exe)
    if not path.is_file():
        return NinaAppStartResult(ok=False, error=f"NINA.exe nicht gefunden: {path}")
    if is_nina_running():
        return NinaAppStartResult(ok=True, already_running=True)
    if sys.platform != "win32":
        return NinaAppStartResult(ok=False, error="NINA-Start nur unter Windows")
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
        logger.info("NINA gestartet: %s (pid=%s)", path, proc.pid)
        return NinaAppStartResult(ok=True, already_running=False, pid=proc.pid)
    except Exception as exc:  # noqa: BLE001
        return NinaAppStartResult(ok=False, error=str(exc) or "Start fehlgeschlagen")
