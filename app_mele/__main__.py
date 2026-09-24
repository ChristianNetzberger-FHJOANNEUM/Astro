"""Einstieg: python -m app_mele (aus Repo-Root, venv aktiv)."""

from __future__ import annotations

import sys
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parent.parent
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

from app_mele.main_app import run_app

if __name__ in {"__main__", "__mp_main__"}:
    run_app()
