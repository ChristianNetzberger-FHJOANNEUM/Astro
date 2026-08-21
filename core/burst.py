"""Burst-Erkennung anhand Aufnahmezeit und Kameradateinummer.

Siril gruppiert Sequenzen nach Ordner/Dateiname, nicht nach 'Burst 17 um C2'.
Deshalb liegt die semantische Gruppierung hier — Originale werden nicht umbenannt.
"""

from __future__ import annotations

from datetime import datetime

from core.config import BurstSettings
from core.models import Burst, Capture


def guess_drive(frame_count: int, duration_s: float) -> str:
    if frame_count < 2:
        return "single"
    if duration_s <= 1e-6:
        return "SH30"
    fps = (frame_count - 1) / duration_s
    if fps >= 20:
        return "SH30"
    if fps >= 8:
        return "H"
    if fps >= 4:
        return "M"
    if fps >= 1.5:
        return "L"
    return "burst"


def _gap_s(prev: Capture, cur: Capture) -> float:
    if prev.datetime is None or cur.datetime is None:
        return 0.0
    return (cur.datetime - prev.datetime).total_seconds()


def _consecutive_numbers(prev: Capture, cur: Capture) -> bool:
    if prev.file_number is None or cur.file_number is None:
        return False
    delta = cur.file_number - prev.file_number
    return 1 <= delta <= 2


def _same_burst(prev: Capture, cur: Capture, settings: BurstSettings) -> bool:
    gap = _gap_s(prev, cur)
    if gap <= settings.same_burst_gap_s:
        return True
    if gap > settings.new_burst_gap_s:
        return False
    return _consecutive_numbers(prev, cur)


def detect_bursts(
    captures: list[Capture],
    settings: BurstSettings | None = None,
) -> list[Burst]:
    """Sortiert Aufnahmen und bildet Bursts / Einzelbilder."""
    settings = settings or BurstSettings()
    if not captures:
        return []

    ordered = sorted(
        captures,
        key=lambda c: (
            c.datetime or datetime.min,
            c.file_number if c.file_number is not None else 0,
            str(c.primary_path),
        ),
    )

    groups: list[list[Capture]] = [[ordered[0]]]
    for prev, cur in zip(ordered, ordered[1:]):
        if _same_burst(prev, cur, settings):
            groups[-1].append(cur)
        else:
            groups.append([cur])

    bursts: list[Burst] = []
    for index, group in enumerate(groups, start=1):
        start = group[0].datetime
        end = group[-1].datetime
        duration = 0.0
        if start is not None and end is not None:
            duration = (end - start).total_seconds()
        kind = "burst" if len(group) >= settings.min_burst_frames else "single"
        bursts.append(
            Burst(
                burst_no=index,
                captures=group,
                kind=kind,
                drive_guess=guess_drive(len(group), duration),
            )
        )
    return bursts
