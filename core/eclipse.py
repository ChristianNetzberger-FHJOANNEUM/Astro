"""Eclipse-Phasen relativ zu C1/C2/C3/C4.

Kontaktzeiten kommen aus der Session-Config, nicht aus Siril.
Kamerauhr-Offset wird vor der Klassifikation addiert.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo

from core.config import SessionConfig
from core.models import Burst, Capture

PHASE_LABELS = {
    "pre": "Vor C1",
    "partial_ingress": "Partial (C1-C2)",
    "c2_window": "C2",
    "totality": "Totality",
    "c3_window": "C3",
    "partial_egress": "Partial (C3-C4)",
    "post": "Nach C4",
    "": "",
}


def parse_contact(value: str | None, tz_name: str) -> datetime | None:
    if not value:
        return None
    text = value.strip()
    if not text:
        return None
    tz = ZoneInfo(tz_name)
    if text.endswith("Z"):
        dt = datetime.fromisoformat(text.replace("Z", "+00:00"))
        return dt.astimezone(tz)
    dt = datetime.fromisoformat(text)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=tz)
    return dt.astimezone(tz)


def apply_clock_offset(dt: datetime, offset_s: float) -> datetime:
    if not offset_s:
        return dt
    return dt + timedelta(seconds=offset_s)


def ensure_aware(dt: datetime, tz_name: str) -> datetime:
    if dt.tzinfo is not None:
        return dt
    return dt.replace(tzinfo=ZoneInfo(tz_name))


def classify_phase(
    photo_dt: datetime,
    session: SessionConfig,
    c2_window_s: float = 8.0,
) -> tuple[str, float | None]:
    """Gibt (phase, offset_zu_C2_in_sekunden) zurueck."""
    tz = session.timezone
    t = apply_clock_offset(ensure_aware(photo_dt, tz), session.camera_clock_offset_s)
    contacts = {
        name: parse_contact(getattr(session.contacts, name), tz)
        for name in ("C1", "C2", "C3", "C4")
    }
    c2 = contacts["C2"]
    c2_offset = (t - c2).total_seconds() if c2 is not None else None

    c1, c3, c4 = contacts["C1"], contacts["C3"], contacts["C4"]
    if c1 and t < c1:
        return "pre", c2_offset
    if c2 and abs((t - c2).total_seconds()) <= c2_window_s:
        return "c2_window", c2_offset
    if c2 and c3 and c2 <= t <= c3:
        return "totality", c2_offset
    if c3 and abs((t - c3).total_seconds()) <= c2_window_s:
        return "c3_window", c2_offset
    if c1 and c2 and c1 <= t < c2:
        return "partial_ingress", c2_offset
    if c3 and c4 and c3 < t <= c4:
        return "partial_egress", c2_offset
    if c4 and t > c4:
        return "post", c2_offset
    return "", c2_offset


def annotate_bursts(bursts: list[Burst], session: SessionConfig | None) -> None:
    if session is None or session.kind != "eclipse":
        return
    for burst in bursts:
        offsets: list[float] = []
        phases: list[str] = []
        for capture in burst.captures:
            if capture.datetime is None:
                continue
            phase, offset = classify_phase(capture.datetime, session)
            capture.phase = phase
            capture.c2_offset_s = offset
            phases.append(phase)
            if offset is not None:
                offsets.append(offset)
        burst.phase = _dominant_phase(phases)
        burst.contact_offset_start_s = min(offsets) if offsets else None
        burst.contact_offset_end_s = max(offsets) if offsets else None


def capture_phase(capture: Capture) -> str:
    return capture.phase


def capture_c2_offset(capture: Capture) -> float | None:
    return capture.c2_offset_s


def format_c2_offset(seconds: float | None) -> str:
    if seconds is None:
        return ""
    sign = "+" if seconds >= 0 else "-"
    abs_s = abs(seconds)
    return f"C2 {sign}{abs_s:.1f} s"


def _dominant_phase(phases: list[str]) -> str:
    if not phases:
        return ""
    priority = (
        "c2_window",
        "c3_window",
        "totality",
        "partial_ingress",
        "partial_egress",
        "pre",
        "post",
    )
    unique = set(phases)
    for name in priority:
        if name in unique:
            return name
    return phases[0]


UTC = timezone.utc
