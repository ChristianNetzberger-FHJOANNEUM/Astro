from __future__ import annotations

from datetime import datetime
from zoneinfo import ZoneInfo

from core.config import EclipseContacts, SessionConfig
from core.eclipse import classify_phase, format_c2_offset


def _session() -> SessionConfig:
    return SessionConfig(
        slug="Sofi-26",
        kind="eclipse",
        timezone="Europe/Madrid",
        contacts=EclipseContacts(
            C1="2026-08-12T19:33:00",
            C2="2026-08-12T20:28:13",
            C3="2026-08-12T20:30:00",
            C4="2026-08-12T21:21:00",
        ),
    )


def test_phases_around_contacts() -> None:
    tz = ZoneInfo("Europe/Madrid")
    session = _session()
    cases = [
        (datetime(2026, 8, 12, 19, 10, tzinfo=tz), "pre"),
        (datetime(2026, 8, 12, 20, 0, tzinfo=tz), "partial_ingress"),
        (datetime(2026, 8, 12, 20, 28, 13, tzinfo=tz), "c2_window"),
        (datetime(2026, 8, 12, 20, 29, 10, tzinfo=tz), "totality"),
        (datetime(2026, 8, 12, 20, 30, 3, tzinfo=tz), "c3_window"),
        (datetime(2026, 8, 12, 20, 45, tzinfo=tz), "partial_egress"),
        (datetime(2026, 8, 12, 21, 30, tzinfo=tz), "post"),
    ]
    for dt, expected in cases:
        phase, offset = classify_phase(dt, session)
        assert phase == expected, (dt, phase, expected)
        assert offset is not None


def test_c2_offset_sign() -> None:
    tz = ZoneInfo("Europe/Madrid")
    session = _session()
    before = datetime(2026, 8, 12, 20, 28, 10, tzinfo=tz)
    after = datetime(2026, 8, 12, 20, 28, 16, tzinfo=tz)
    _, off_before = classify_phase(before, session)
    _, off_after = classify_phase(after, session)
    assert off_before is not None and off_before < 0
    assert off_after is not None and off_after > 0
    assert "C2 -" in format_c2_offset(off_before)
    assert "C2 +" in format_c2_offset(off_after)


def test_camera_clock_offset_shifts_phase() -> None:
    tz = ZoneInfo("Europe/Madrid")
    session = _session()
    session.camera_clock_offset_s = -5 * 3600
    camera_dt = datetime(2026, 8, 13, 1, 28, 13, tzinfo=tz)
    phase, offset = classify_phase(camera_dt, session)
    assert phase == "c2_window"
    assert offset is not None
    assert abs(offset) < 1
