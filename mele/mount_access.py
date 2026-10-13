"""Zugriff auf Montierungsbefehle.

Die lesenden Quest-Routen bleiben offen. GoTo, STOP und Achsbewegung brauchen
eine Berechtigung, die auch bei einem direkten Aufruf von Port 8082 gilt.

Der Browser auf dem MeLE selbst bleibt die Desktop-Bedienung. Daran erkennt
ihn die Verbindung: sie kommt von einer Adresse dieses Rechners und nicht über
Caddy. Caddy setzt dafür ``X-Astro-Edge: caddy``. Ein Gerät im Netz kann seine
Absenderadresse nicht zu einer lokalen Adresse machen.

Die Quest koppelt sich mit einem festen Code. Den gibt nur der lokale Desktop
aus, und er steht nicht in ``vr.html``. Er wechselt nicht und läuft nicht ab.
Danach trägt die Sitzung ein HttpOnly-Cookie und ein CSRF-Token.
"""

from __future__ import annotations

import secrets
import socket
import threading
from pathlib import Path

COOKIE = "astro_mount"
EDGE_HEADER = "x-astro-edge"
EDGE_VALUE = "caddy"
CSRF_HEADER = "x-astro-csrf"
SESSION_TTL_S = 12 * 3600.0


def normalize_ip(peer: str) -> str:
    text = str(peer or "").strip().lower()
    if text.startswith("::ffff:"):
        text = text[7:]
    if text == "localhost":
        return "127.0.0.1"
    return text


def machine_addresses() -> set[str]:
    """Adressen dieses Rechners. Eine Gegenstelle mit genau diesen Adressen ist lokal."""
    found = {"127.0.0.1", "::1"}
    try:
        for info in socket.getaddrinfo(socket.gethostname(), None):
            found.add(normalize_ip(info[4][0]))
    except OSError:
        pass
    try:
        probe = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        try:
            probe.connect(("192.168.0.1", 9))
            found.add(normalize_ip(probe.getsockname()[0]))
        finally:
            probe.close()
    except OSError:
        pass
    return {item for item in found if item}


def is_local_desktop(peer: str, via_edge: bool, local_ips: set[str]) -> bool:
    if via_edge:
        return False
    return normalize_ip(peer) in {normalize_ip(item) for item in local_ips}


def _same(left: str, right: str) -> bool:
    if not left or not right or len(left) != len(right):
        return False
    return secrets.compare_digest(left, right)


class MountAccess:
    def __init__(self, code_path: Path | None = None) -> None:
        self._lock = threading.Lock()
        self._code_path = code_path
        self._code = self._load_or_create()
        self._sessions: dict[str, tuple[str, float]] = {}

    def _load_or_create(self) -> str:
        path = self._code_path
        if path is not None:
            try:
                text = path.read_text(encoding="utf-8").strip()
            except OSError:
                text = ""
            if len(text) == 6 and text.isdigit():
                return text
        code = f"{secrets.randbelow(1_000_000):06d}"
        if path is not None:
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(code + "\n", encoding="utf-8")
        return code

    def issue_code(self, now: float | None = None) -> str:
        """Derselbe Code bei jedem Aufruf. ``now`` bleibt unbenutzt."""
        del now
        with self._lock:
            return self._code

    def pair(self, code: str, now: float) -> tuple[str, str, float] | None:
        offered = str(code or "").strip()
        with self._lock:
            if not _same(offered, self._code):
                return None
            token = secrets.token_urlsafe(32)
            csrf = secrets.token_urlsafe(32)
            self._sessions[token] = (csrf, now + SESSION_TTL_S)
            return token, csrf, SESSION_TTL_S

    def csrf_for(self, token: str, now: float) -> str:
        with self._lock:
            self._drop_expired(now)
            row = self._sessions.get(token)
            if row is None:
                return ""
            return row[0]

    def expires_in(self, token: str, now: float) -> float:
        with self._lock:
            self._drop_expired(now)
            row = self._sessions.get(token)
            if row is None:
                return 0.0
            return max(0.0, row[1] - now)

    def _drop_expired(self, now: float) -> None:
        stale = [token for token, (_, expires) in self._sessions.items() if now >= expires]
        for token in stale:
            del self._sessions[token]


def authorization(
    access: MountAccess,
    *,
    peer: str,
    via_edge: bool,
    local_ips: set[str],
    cookie: str,
    csrf: str,
    now: float,
) -> str:
    """``desktop`` oder ``session``. Leer heißt abgelehnt."""
    if is_local_desktop(peer, via_edge, local_ips):
        return "desktop"
    expected = access.csrf_for(cookie, now)
    if expected and _same(str(csrf or ""), expected):
        return "session"
    return ""
