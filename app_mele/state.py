from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path

import numpy as np

from mele.horizon import HorizonProfile, SkySample, SunExclude


@dataclass
class UiState:
    image_path: Path | None = None
    profile: HorizonProfile | None = None
    preview_width: int = 0
    preview_height: int = 0
    source_width: int = 0
    source_height: int = 0
    north_x: float = 0.0
    status: str = ""
    detecting: bool = False
    show_grid: bool = False
    grid_step: int = 10
    latitude_deg: float | None = None
    longitude_deg: float | None = None
    site_src: str = "none"
    photo_when: datetime | None = None
    method: str = "auto"
    click_mode: str = "tool"
    sky_samples: list[SkySample] = field(default_factory=list)
    reject_samples: list[SkySample] = field(default_factory=list)
    sun_excludes: list[SunExclude] = field(default_factory=list)
    picker_role: str = "sky"
    sun_radius_preview: float = 28.0
    manual_points: list[tuple[float, float]] = field(default_factory=list)
    hue_pad: float = 18.0
    sat_pad: float = 0.22
    val_pad: float = 0.22
    above_horizon: bool = True
    brush_radius: float = 18.0
    brush_erase: bool = False
    mask: np.ndarray | None = None
    preview_token: int = 0
    refs: dict = field(default_factory=dict)
