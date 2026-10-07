"""weather_server (python -m weather_server) starten und Laufstatus pruefen.

Analog zu nina_launch / phd2_launch — eigener Prozess auf Port 8765.
"""

from __future__ import annotations

import logging
import socket
import subprocess
import sys
import urllib.error
import urllib.request
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

logger = logging.getLogger(__name__)

REPO_ROOT = Path(__file__).resolve().parent.parent
DEFAULT_SERVER_URL = "http://127.0.0.1:8765"


@dataclass(frozen=True)
class WeatherServerAppStatus:
    running: bool
    reachable: bool = False
    server_url: str = DEFAULT_SERVER_URL
    python_path: str | None = None
    python_exists: bool = False
    error: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class WeatherServerStartResult:
    ok: bool
    already_running: bool = False
    pid: int | None = None
    error: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def resolve_python(repo_root: Path | None = None) -> Path:
    root = repo_root or REPO_ROOT
    venv = root / ".venv" / "Scripts" / "python.exe"
    if venv.is_file():
        return venv
    return Path(sys.executable)


def _port_from_url(server_url: str) -> int:
    parsed = urlparse((server_url or DEFAULT_SERVER_URL).strip() or DEFAULT_SERVER_URL)
    if parsed.port:
        return int(parsed.port)
    return 443 if (parsed.scheme or "").lower() == "https" else 80


def _host_from_url(server_url: str) -> str:
    parsed = urlparse((server_url or DEFAULT_SERVER_URL).strip() or DEFAULT_SERVER_URL)
    return (parsed.hostname or "127.0.0.1").strip() or "127.0.0.1"


def is_weather_server_process_running() -> bool:
    """True, wenn `python -m weather_server` laeuft (strikter CommandLine-Match)."""
    if sys.platform != "win32":
        return False
    try:
        creationflags = getattr(subprocess, "CREATE_NO_WINDOW", 0)
        # wmic: kein PowerShell, dessen eigene CommandLine sonst falsch matchen koennte
        completed = subprocess.run(
            [
                "wmic",
                "process",
                "where",
                "name='python.exe'",
                "get",
                "CommandLine",
                "/FORMAT:LIST",
            ],
            capture_output=True,
            text=True,
            timeout=8,
            creationflags=creationflags,
            check=False,
        )
        text = (completed.stdout or "") + "\n" + (completed.stderr or "")
        for line in text.splitlines():
            low = line.lower().replace('"', "")
            if "-m weather_server" in low:
                return True
        return False
    except Exception:  # noqa: BLE001
        return False


def is_port_open(host: str, port: int, *, timeout_s: float = 0.4) -> bool:
    try:
        with socket.create_connection((host, port), timeout=timeout_s):
            return True
    except OSError:
        return False


def is_weather_server_reachable(server_url: str = DEFAULT_SERVER_URL, *, timeout_s: float = 1.5) -> bool:
    base = (server_url or DEFAULT_SERVER_URL).rstrip("/")
    url = f"{base}/api/current"
    try:
        req = urllib.request.Request(url, method="GET")
        with urllib.request.urlopen(req, timeout=timeout_s) as resp:  # noqa: S310
            return 200 <= int(getattr(resp, "status", 200) or 200) < 500
    except (urllib.error.URLError, urllib.error.HTTPError, TimeoutError, OSError):
        # Port offen reicht als „laeuft“ (API kann kurz busy sein)
        return is_port_open(_host_from_url(base), _port_from_url(base))


def get_weather_server_app_status(
    server_url: str = DEFAULT_SERVER_URL,
    *,
    repo_root: Path | None = None,
) -> WeatherServerAppStatus:
    python = resolve_python(repo_root)
    url = (server_url or DEFAULT_SERVER_URL).strip() or DEFAULT_SERVER_URL
    try:
        proc = is_weather_server_process_running()
        reachable = is_weather_server_reachable(url)
        return WeatherServerAppStatus(
            running=proc or reachable,
            reachable=reachable,
            server_url=url,
            python_path=str(python),
            python_exists=python.is_file(),
        )
    except Exception as exc:  # noqa: BLE001
        return WeatherServerAppStatus(
            running=False,
            reachable=False,
            server_url=url,
            python_path=str(python),
            python_exists=python.is_file(),
            error=str(exc) or "weather_server-Status fehlgeschlagen",
        )


def start_weather_server_app(
    server_url: str = DEFAULT_SERVER_URL,
    *,
    repo_root: Path | None = None,
    no_browser: bool = True,
) -> WeatherServerStartResult:
    """Startet `python -m weather_server --no-browser`, falls noch nicht laufend."""
    root = (repo_root or REPO_ROOT).resolve()
    python = resolve_python(root)
    if not python.is_file():
        return WeatherServerStartResult(ok=False, error=f"Python nicht gefunden: {python}")

    status = get_weather_server_app_status(server_url, repo_root=root)
    if status.reachable:
        return WeatherServerStartResult(ok=True, already_running=True)
    if status.running and not status.reachable:
        return WeatherServerStartResult(
            ok=False,
            already_running=True,
            error=(
                "weather_server-Prozess laeuft, API aber nicht erreichbar. "
                "Alten Prozess beenden (Task/Terminal) und erneut starten."
            ),
        )

    if sys.platform != "win32":
        return WeatherServerStartResult(ok=False, error="weather_server-Start nur unter Windows")

    cmd = [str(python), "-m", "weather_server"]
    if no_browser:
        cmd.append("--no-browser")
    try:
        flags = 0
        flags |= getattr(subprocess, "DETACHED_PROCESS", 0)
        flags |= getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0)
        flags |= getattr(subprocess, "CREATE_NO_WINDOW", 0)
        proc = subprocess.Popen(  # noqa: S603
            cmd,
            cwd=str(root),
            close_fds=True,
            creationflags=flags,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            stdin=subprocess.DEVNULL,
        )
        logger.info("weather_server gestartet: %s (pid=%s)", " ".join(cmd), proc.pid)
        return WeatherServerStartResult(ok=True, already_running=False, pid=proc.pid)
    except Exception as exc:  # noqa: BLE001
        return WeatherServerStartResult(ok=False, error=str(exc) or "Start fehlgeschlagen")
