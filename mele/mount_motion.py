"""Bewegungszustand für GoTo und Achsbewegung.

RA und Dec an ``/nina/mount/slew`` sind Grad. Das Katalogfeld ``ra`` ist bereits
Grad (``ra_deg``). Auf diesem Weg wird nicht mit 15 multipliziert. Die
NINA-Telemetrie ``RightAscension`` ist in Stunden und bleibt davon getrennt.

SynScan, die NINA-Oberfläche und PHD2 können die Montierung außerhalb dieser
Sperre bewegen. Unmittelbar vor einem GoTo zählt deshalb die frische Meldung.
Ein Abbruch der Quest-Verbindung stoppt einen laufenden GoTo nicht.
"""

from __future__ import annotations

import os
import sys
import threading
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

from mele.sky import radec_to_az_alt

FRESH_S = 2.0

_LABELS = {
    "unklar": "Zustand unklar",
    "bereit": "Bereit",
    "faehrt": "GoTo aktiv",
    "stoppt": "STOP läuft",
}


class InstanceBusy(RuntimeError):
    """Eine andere MeLE-App hält das Instanzschloss."""


@dataclass
class MountSample:
    online: bool
    connected: bool
    slewing: bool = False
    parked: bool = False
    age_s: float = 0.0
    error: str = ""


@dataclass
class Reserve:
    ok: bool
    generation: int = 0
    error: str = ""
    status: int = 200


@dataclass
class FollowUp:
    restop: bool
    error: str = ""
    status: int = 200


def slew_coordinates_deg(ra: float, dec: float) -> tuple[float, float]:
    """RA/Dec für den Slew. Beide Werte sind Grad und bleiben unverändert."""
    return float(ra), float(dec)


def target_block_reason(
    ra_deg: float,
    dec_deg: float,
    latitude_deg: float,
    longitude_deg: float,
    when: datetime,
    profile,
) -> str:
    """Leer, wenn das Ziel über dem geometrischen Horizont und der Gartenmaske liegt."""
    stamp = when if when.tzinfo is not None else when.replace(tzinfo=timezone.utc)
    az, alt = radec_to_az_alt(ra_deg, dec_deg, latitude_deg, longitude_deg, stamp)
    if alt <= 0.0:
        return "Ziel unter Horizont"
    points = getattr(profile, "points", None) if profile is not None else None
    if points:
        if not (alt > float(profile.altitude_at(az))):
            return "Ziel hinter dem Gartenhorizont"
    return ""


class InstanceLock:
    """Hält eine Byte-Sperre, die Windows und das Betriebssystem beim Prozessende lösen.

    Die Datei darf liegen bleiben. Blockierend ist nur die gehaltene Sperre, nicht
    das Vorhandensein der Datei.
    """

    def __init__(self, path: Path) -> None:
        self.path = Path(path)
        self._fh = None

    def acquire(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        fh = open(self.path, "a+b")
        try:
            fh.seek(0, os.SEEK_END)
            if fh.tell() < 1:
                fh.write(b"\0")
                fh.flush()
            fh.seek(0)
            if sys.platform == "win32":
                import msvcrt

                msvcrt.locking(fh.fileno(), msvcrt.LK_NBLCK, 1)
            else:
                import fcntl

                fcntl.flock(fh.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        except OSError as exc:
            fh.close()
            raise InstanceBusy("MeLE-App läuft bereits") from exc
        self._fh = fh

    def release(self) -> None:
        fh = self._fh
        self._fh = None
        if fh is None:
            return
        try:
            fh.seek(0)
            if sys.platform == "win32":
                import msvcrt

                msvcrt.locking(fh.fileno(), msvcrt.LK_UNLCK, 1)
            else:
                import fcntl

                fcntl.flock(fh.fileno(), fcntl.LOCK_UN)
        except OSError:
            pass
        finally:
            fh.close()


class MountMotion:
    """Kurzes Schloss nur für die Entscheidung. NINA-Aufrufe bleiben draußen."""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self.state = "unklar"
        self.kind = ""
        self.detail = "Start"
        self.generation = 0
        self.seen_slewing = False
        self.move_active = False
        self.axis_fault = ""
        self.start_open = False
        self.stop_open = False
        self._link_lost = False

    def view(self) -> dict[str, str]:
        with self._lock:
            return self._view()

    def note(self, sample: MountSample) -> None:
        with self._lock:
            self._apply(sample)

    def reserve_goto(self, sample: MountSample) -> Reserve:
        with self._lock:
            self._apply(sample)
            if self.state != "bereit":
                return Reserve(False, error=self._blocked_reason(), status=409)
            self.generation += 1
            generation = self.generation
            self.state = "faehrt"
            self.kind = "goto"
            self.seen_slewing = False
            self.move_active = False
            self.start_open = True
            self.detail = "GoTo aktiv"
            return Reserve(True, generation=generation)

    def complete_goto(self, generation: int, outcome: str) -> FollowUp:
        with self._lock:
            self.start_open = False
            superseded = generation != self.generation or self.state == "stoppt"
            if outcome == "ok" and not superseded:
                self.state = "faehrt"
                self.kind = "goto"
                self.detail = "GoTo aktiv"
                return FollowUp(False)
            if superseded and outcome == "ok":
                self.state = "stoppt"
                self.kind = "goto"
                self.detail = "STOP während des Starts"
                return FollowUp(True, error="STOP während des Starts", status=409)
            self.state = "unklar"
            if outcome == "unclear":
                self.detail = "GoTo-Antwort zeitlich unklar"
                return FollowUp(True, error="GoTo-Antwort zeitlich unklar", status=502)
            self.kind = ""
            self.seen_slewing = False
            self.detail = "GoTo nicht angenommen"
            return FollowUp(False, error="GoTo nicht angenommen", status=502)

    def reserve_move(self) -> Reserve:
        with self._lock:
            if self.state != "bereit" or self.move_active:
                return Reserve(False, error=self._blocked_reason(), status=409)
            self.generation += 1
            self.state = "faehrt"
            self.kind = "move"
            self.move_active = True
            self.seen_slewing = False
            self.detail = "Achsbewegung aktiv"
            return Reserve(True, generation=self.generation)

    def complete_move(self, ok: bool) -> None:
        with self._lock:
            if self.kind != "move":
                return
            if ok:
                self.detail = "Achsbewegung aktiv"
                return
            self.move_active = False
            self.axis_fault = ""
            self.kind = ""
            self.state = "unklar"
            self.detail = "Achsbewegung nicht gestartet"

    def finish_move(self, ok: bool) -> None:
        """Achsen-Stopp. Hebt einen laufenden GoTo nicht auf und blockiert nicht.

        ``ok`` heißt: Rate 0 wurde an NINA übergeben. Das ist kein Stillstand.
        Ein fehlgeschlagener Versand bleibt ein Fehler, bis ein späterer Stopp sendet.
        """
        self.note_axis_stop(ok)

    def kind_is_goto(self) -> bool:
        with self._lock:
            return self.kind == "goto"

    def manual_axis_active(self) -> bool:
        with self._lock:
            return self.kind == "move" or bool(self.axis_fault)

    def note_axis_stop(self, sent: bool) -> None:
        with self._lock:
            if self.kind == "goto":
                return
            if self.kind != "move" and not self.axis_fault:
                return
            if sent:
                self.axis_fault = ""
                self.move_active = False
                self.kind = ""
                self.state = "stoppt"
                self.stop_open = False
                self.detail = "Rate 0 gesendet, Stillstand offen"
                return
            self.axis_fault = "Rate 0 nicht gesendet"
            self.move_active = True
            self.kind = "move"
            self.state = "unklar"
            self.detail = self.axis_fault

    def begin_stop(self) -> int:
        """Immer sofort. Wartet nicht auf den GoTo-Start."""
        with self._lock:
            self.generation += 1
            generation = self.generation
            self.state = "stoppt"
            self.move_active = False
            self.start_open = False
            self.stop_open = True
            self.detail = "STOP läuft"
            return generation

    def complete_stop(self, outcome: str) -> FollowUp:
        with self._lock:
            self.stop_open = False
            if outcome == "ok":
                self.state = "stoppt"
                self.detail = "STOP gesendet, Stillstand offen"
                return FollowUp(False)
            self.state = "unklar"
            self.detail = "STOP-Antwort zeitlich unklar" if outcome == "unclear" else "STOP nicht bestätigt"
            return FollowUp(False, error=self.detail, status=502)

    def _apply(self, sample: MountSample) -> None:
        if self.axis_fault:
            self.state = "unklar"
            self.kind = "move"
            self.move_active = True
            self.detail = self.axis_fault
            return
        if sample.age_s > FRESH_S:
            if self.state == "bereit":
                self.state = "unklar"
                self.detail = "Meldung nicht mehr aktuell"
            return
        if self.stop_open:
            self.state = "stoppt"
            self.detail = "STOP läuft"
            if sample.slewing:
                self.seen_slewing = True
            return
        if not sample.online or not sample.connected:
            self._link_lost = True
            self.state = "unklar"
            if not sample.online:
                self.detail = "NINA nicht erreichbar"
            else:
                self.detail = "Montierung nicht verbunden"
            return
        if self._link_lost and not sample.slewing:
            self._become_ready()
            return
        if sample.slewing:
            self.seen_slewing = True
            if self.state == "stoppt":
                self.detail = "STOP läuft"
                return
            self.state = "faehrt"
            if self.kind == "move":
                self.detail = "Achsbewegung aktiv"
            elif self.kind == "goto":
                self.detail = "GoTo aktiv"
            else:
                self.kind = "fremd"
                self.detail = "Montierung bewegt sich"
            return
        if self.move_active:
            self.state = "faehrt"
            self.detail = "Achsbewegung aktiv"
            return
        if self.start_open or (self.kind == "goto" and not self.seen_slewing and self.state in {"faehrt", "unklar"}):
            self.state = "faehrt"
            self.detail = "GoTo gestartet, Bewegung noch nicht bestätigt"
            return
        if self.state == "faehrt" and self.seen_slewing:
            self._become_ready()
            return
        if self.state == "stoppt":
            self._become_ready()
            return
        if self.state == "unklar" and self.kind == "goto" and self.seen_slewing:
            self._become_ready()
            return
        if self.state == "unklar" and self.kind == "":
            self._become_ready()
            return
        if self.state == "bereit":
            self.detail = "Bereit"

    def _become_ready(self) -> None:
        self.state = "bereit"
        self.kind = ""
        self.seen_slewing = False
        self.move_active = False
        self.axis_fault = ""
        self.start_open = False
        self.stop_open = False
        self._link_lost = False
        self.detail = "Bereit"

    def _blocked_reason(self) -> str:
        if self.detail in {
            "NINA nicht erreichbar",
            "Montierung nicht verbunden",
            "Meldung nicht mehr aktuell",
            "GoTo-Antwort zeitlich unklar",
            "STOP läuft",
            "STOP gesendet, Stillstand offen",
            "STOP während des Starts",
            "Achsbewegung aktiv",
            "Montierung bewegt sich",
            "Rate 0 nicht gesendet",
        }:
            return self.detail
        if self.state == "faehrt":
            return "GoTo bereits aktiv"
        if self.state == "stoppt":
            return "STOP läuft"
        return "Zustand unklar"

    def _view(self) -> dict[str, str]:
        label = self.detail if self.detail in {
            "NINA nicht erreichbar",
            "Montierung nicht verbunden",
            "Bereit",
            "GoTo aktiv",
            "STOP läuft",
            "Achsbewegung aktiv",
            "Zustand unklar",
        } else _LABELS.get(self.state, "Zustand unklar")
        if self.state == "unklar" and self.detail not in {"NINA nicht erreichbar", "Montierung nicht verbunden"}:
            label = "Zustand unklar"
        if self.state == "stoppt":
            label = "STOP läuft"
        if self.state == "bereit":
            label = "Bereit"
        if self.state == "faehrt" and self.kind == "move":
            label = "Achsbewegung aktiv"
        if self.state == "faehrt" and self.kind == "goto":
            label = "GoTo aktiv"
        if self.state == "faehrt" and self.kind == "fremd":
            label = "Zustand unklar"
        return {"state": self.state, "label": label, "detail": self.detail}


def command_outcome(ok: bool, api_online: bool) -> str:
    if ok:
        return "ok"
    if not api_online:
        return "unclear"
    return "error"


def phd2_blocks_axis(status) -> str:
    """Leer, wenn eine manuelle Achse erlaubt ist.

    Unerreichbares oder unklares PHD2 sperrt. GoTo behandelt OFFLINE weiter
    als „führt nicht“.
    """
    if status is None:
        return "PHD2-Zustand nicht lesbar"
    connection = str(getattr(status, "connection", "") or "")
    if not connection:
        return "PHD2-Zustand nicht lesbar"
    if connection in {"OFFLINE", "CONNECTING"}:
        return "PHD2 nicht erreichbar"
    if connection in {"GUIDING", "LOST_STAR", "PAUSED"} or bool(getattr(status, "guiding", False)):
        return "PHD2 führt"
    if connection == "CALIBRATING":
        return "PHD2 kalibriert"
    return ""


def phd2_blocks_goto(status) -> str:
    """Leer, wenn PHD2 erkennbar nicht führt. Ausnahme: Zustand nicht lesbar."""
    if status is None:
        return "PHD2-Zustand nicht lesbar"
    connection = str(getattr(status, "connection", "") or "")
    if connection == "GUIDING" or bool(getattr(status, "guiding", False)):
        return "PHD2 führt"
    if connection == "CALIBRATING":
        return "PHD2 kalibriert"
    return ""
