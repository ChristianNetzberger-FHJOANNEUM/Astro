from __future__ import annotations

from datetime import datetime, timedelta
from pathlib import Path

from core.burst import detect_bursts, guess_drive
from core.config import BurstSettings
from core.models import Capture


def _cap(num: int, dt: datetime, stem: str | None = None) -> Capture:
    name = stem or f"P{num}"
    return Capture(
        raw_path=Path(f"{name}.RW2"),
        jpg_path=None,
        datetime=dt,
        file_number=num,
        stem=name,
    )


def test_same_second_sh30_is_one_burst() -> None:
    t0 = datetime(2026, 8, 12, 20, 28, 10)
    frames = [_cap(1000 + i, t0) for i in range(30)]
    bursts = detect_bursts(frames)
    assert len(bursts) == 1
    assert bursts[0].kind == "burst"
    assert bursts[0].frame_count == 30
    assert bursts[0].drive_guess == "SH30"


def test_sh30_spanning_seconds_stays_together() -> None:
    t0 = datetime(2026, 8, 12, 20, 28, 10)
    frames = []
    for i in range(84):
        dt = t0 + timedelta(seconds=i // 30)
        frames.append(_cap(2000 + i, dt))
    bursts = detect_bursts(frames)
    assert len(bursts) == 1
    assert bursts[0].frame_count == 84
    assert bursts[0].drive_guess == "SH30"


def test_gap_over_one_second_starts_new_burst() -> None:
    t0 = datetime(2026, 8, 12, 20, 28, 10)
    frames = [
        _cap(1, t0),
        _cap(2, t0 + timedelta(milliseconds=33)),
        _cap(3, t0 + timedelta(seconds=3)),
        _cap(4, t0 + timedelta(seconds=3, milliseconds=33)),
    ]
    bursts = detect_bursts(frames)
    assert len(bursts) == 2
    assert bursts[0].frame_count == 2
    assert bursts[1].frame_count == 2
    assert bursts[0].burst_no == 1
    assert bursts[1].burst_no == 2


def test_singles_far_apart() -> None:
    t0 = datetime(2026, 8, 12, 19, 40, 0)
    frames = [_cap(10 + i, t0 + timedelta(seconds=i * 5)) for i in range(3)]
    bursts = detect_bursts(frames)
    assert len(bursts) == 3
    assert all(b.kind == "single" for b in bursts)


def test_lumix_folder_jump_same_timestamp_same_burst() -> None:
    t0 = datetime(2026, 8, 12, 20, 28, 12)
    frames = [
        _cap(1046770, t0, "P1046770"),
        _cap(1056771, t0, "P1056771"),
        _cap(1056772, t0, "P1056772"),
    ]
    bursts = detect_bursts(frames)
    assert len(bursts) == 1
    assert bursts[0].frame_count == 3


def test_ambiguous_gap_uses_file_numbers() -> None:
    t0 = datetime(2026, 8, 12, 20, 28, 10)
    settings = BurstSettings(same_burst_gap_s=0.2, new_burst_gap_s=1.0)
    together = [
        _cap(50, t0),
        _cap(51, t0 + timedelta(milliseconds=800)),
    ]
    split = [
        _cap(50, t0),
        _cap(90, t0 + timedelta(milliseconds=800)),
    ]
    assert len(detect_bursts(together, settings)) == 1
    assert len(detect_bursts(split, settings)) == 2


def test_guess_drive_fps_buckets() -> None:
    assert guess_drive(1, 0) == "single"
    assert guess_drive(30, 0) == "SH30"
    assert guess_drive(10, 1.0) == "H"
    assert guess_drive(6, 1.0) == "M"
