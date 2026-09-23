from __future__ import annotations

from dataclasses import dataclass, field


@dataclass
class UiState:
    session_id: int | None = None
    burst_id: int | None = None
    kind_filter: str = "all"
    phase_filter: str = "all"
    group_by: str = "object"
    page: str = "catalog"
    status: str = ""
    scanning: bool = False
    nas_ok: bool | None = None
    refs: dict = field(default_factory=dict)
