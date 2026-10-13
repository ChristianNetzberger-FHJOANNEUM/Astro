"""Rechte-Joystick-Regel für die manuelle Quest-Achse.

Dieselbe Entscheidung steht in ``app_mele/vr.html``. Bei ``xr-standard`` sind
``axes[0]`` und ``axes[1]`` das Touchpad, ``axes[2]`` und ``axes[3]`` der
Stick. Die Quest hat kein Touchpad, die ersten beiden Achsen bleiben 0.
Stick nach oben meldet negatives Y. Norden ist oben, deshalb wird Y umgekehrt.
"""

from __future__ import annotations

DEADZONE = 0.2
TOUCH_PROFILES = (
    "oculus-touch",
    "meta-quest-touch-plus",
    "generic-thumbstick",
    "generic-trigger",
)


def right_stick_usable(
    handedness: str,
    mapping: str,
    profiles: list[str] | tuple[str, ...],
    axis_count: int,
) -> bool:
    if handedness != "right":
        return False
    if mapping != "xr-standard":
        return False
    if axis_count < 2:
        return False
    names = tuple(profiles or ())
    if names and not any(name in TOUCH_PROFILES for name in names):
        return False
    return True


def thumbstick_xy(mapping: str, axes: list[float] | tuple[float, ...]) -> tuple[float, float] | None:
    """Liefert X nach rechts und Y nach oben. Unbekanntes Mapping ergibt nichts."""
    if mapping != "xr-standard":
        return None
    try:
        values = [float(item) for item in axes]
    except (TypeError, ValueError):
        return None
    if any(item != item for item in values):
        return None
    if len(values) >= 4:
        return values[2], -values[3]
    if len(values) >= 2:
        return values[0], values[1]
    return None


def stick_direction(x: float, y: float, deadzone: float = DEADZONE) -> str:
    try:
        x_f = float(x)
        y_f = float(y)
    except (TypeError, ValueError):
        return ""
    if x_f != x_f or y_f != y_f:
        return ""
    ax = abs(x_f)
    ay = abs(y_f)
    if ax < deadzone and ay < deadzone:
        return ""
    if ax >= ay:
        return "east" if x_f > 0 else "west"
    return "north" if y_f > 0 else "south"
