from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path


@dataclass
class Capture:
    """Eine logische Aufnahme (RAW + optionales JPG), Originale unveraendert."""

    raw_path: Path | None
    jpg_path: Path | None
    datetime: datetime | None
    datetime_src: str = ""
    exposure: str = ""
    iso: int | None = None
    aperture: str = ""
    focal_length_mm: float | None = None
    camera: str = ""
    lens: str = ""
    file_number: int | None = None
    stem: str = ""
    phase: str = ""
    c2_offset_s: float | None = None

    @property
    def preview_path(self) -> Path | None:
        return self.jpg_path or self.raw_path

    @property
    def primary_path(self) -> Path:
        if self.raw_path is not None:
            return self.raw_path
        if self.jpg_path is not None:
            return self.jpg_path
        raise ValueError("Capture ohne Datei")


@dataclass
class Burst:
    """Gruppe aufeinanderfolgender Aufnahmen (Burst oder Einzelbild)."""

    burst_no: int
    captures: list[Capture] = field(default_factory=list)
    kind: str = "burst"  # burst | single
    drive_guess: str = ""
    phase: str = ""
    contact_offset_start_s: float | None = None
    contact_offset_end_s: float | None = None
    notes: str = ""

    @property
    def frame_count(self) -> int:
        return len(self.captures)

    @property
    def start_dt(self) -> datetime | None:
        dts = [c.datetime for c in self.captures if c.datetime is not None]
        return min(dts) if dts else None

    @property
    def end_dt(self) -> datetime | None:
        dts = [c.datetime for c in self.captures if c.datetime is not None]
        return max(dts) if dts else None


@dataclass
class SessionInfo:
    slug: str
    title: str
    root_path: Path
    kind: str = "general"
    originals_subdir: str = ""
    notes: str = ""
