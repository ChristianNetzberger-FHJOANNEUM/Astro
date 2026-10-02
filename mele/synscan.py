"""SynScan Pro starten und Laufstatus pruefen (Skywatcher-Montierung).

Kein direkter Mount-Zugriff — nur Process-Start und Prozessabfrage unter Windows.
"""

from __future__ import annotations

import logging
import subprocess
import sys
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

DEFAULT_EXE = Path(r"C:\Astro\SW\synscanpro_windows_2611\SynScanPro\SynScanPro.exe")
PROCESS_NAME = "SynScanPro.exe"


@dataclass(frozen=True)
class SynScanStatus:
    running: bool
    exe_path: str | None = None
    exe_exists: bool = False
    error: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class SynScanStartResult:
    ok: bool
    already_running: bool = False
    pid: int | None = None
    error: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def resolve_synscan_exe(configured: str | Path | None = None) -> Path:
    if configured:
        path = Path(str(configured))
        if path.is_dir():
            path = path / PROCESS_NAME
        return path
    return DEFAULT_EXE


def is_synscan_running(*, process_name: str = PROCESS_NAME) -> bool:
    """True, wenn mindestens eine SynScanPro-Instanz laeuft. Wirft nicht."""
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


def get_synscan_status(exe: str | Path | None = None) -> SynScanStatus:
    path = resolve_synscan_exe(exe)
    try:
        running = is_synscan_running()
        return SynScanStatus(
            running=running,
            exe_path=str(path),
            exe_exists=path.is_file(),
        )
    except Exception as exc:  # noqa: BLE001
        return SynScanStatus(
            running=False,
            exe_path=str(path),
            exe_exists=path.is_file(),
            error=str(exc) or "SynScan-Status fehlgeschlagen",
        )


def start_synscan(exe: str | Path | None = None) -> SynScanStartResult:
    """Startet SynScan Pro, falls noch nicht laufend. Wirft nicht."""
    path = resolve_synscan_exe(exe)
    if not path.is_file():
        return SynScanStartResult(ok=False, error=f"SynScanPro nicht gefunden: {path}")
    if is_synscan_running():
        return SynScanStartResult(ok=True, already_running=True)
    if sys.platform != "win32":
        return SynScanStartResult(ok=False, error="SynScan Pro nur unter Windows")
    try:
        # GUI-App sichtbar starten, unabhaengig vom NiceGUI-Prozess
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
        logger.info("SynScan Pro gestartet: %s (pid=%s)", path, proc.pid)
        return SynScanStartResult(ok=True, already_running=False, pid=proc.pid)
    except Exception as exc:  # noqa: BLE001
        return SynScanStartResult(ok=False, error=str(exc) or "Start fehlgeschlagen")
