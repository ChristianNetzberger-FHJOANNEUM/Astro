from __future__ import annotations

from dataclasses import dataclass, field


@dataclass
class UiState:
    session_id: int | None = None
    burst_id: int | None = None
    kind_filter: str = "all"
    phase_filter: str = "all"
    status: str = ""
    refs: dict = field(default_factory=dict)
