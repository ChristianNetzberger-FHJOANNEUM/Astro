"""Persönliche Objektbewertung, getrennt von Favoriten und vom Sternkatalog.

Persistenz: ``{horizon_dir}/object-picks.json``.
Schlüssel sind kanonische ``dso.key``. Eine fehlende Datei ist eine leere Auswahl.
Eine beschädigte Datei wird protokolliert und nicht überschrieben.
"""

from __future__ import annotations

import json
import logging
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

log = logging.getLogger(__name__)

PICKS_SCHEMA = 1
NOTE_MAX = 240


class PicksCorrupt(RuntimeError):
    """Die Auswahldatei ist da, aber nicht lesbar. Sie wird nicht ersetzt."""


def picks_path(horizon_dir: Path) -> Path:
    return Path(horizon_dir) / "object-picks.json"


def _utc_now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def _write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(payload, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    tmp.replace(path)


def _clean_rating(value: Any) -> int | None:
    if value is None or value == "":
        return None
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ValueError("rating muss 1 bis 5 oder leer sein")
    if isinstance(value, float) and not value.is_integer():
        raise ValueError("rating muss 1 bis 5 oder leer sein")
    rating = int(value)
    if rating < 1 or rating > 5:
        raise ValueError("rating muss 1 bis 5 oder leer sein")
    return rating


def _clean_quest(value: Any) -> bool:
    if isinstance(value, bool):
        return value
    if value in {0, 1}:
        return bool(value)
    if isinstance(value, str) and value.strip().lower() in {"0", "1", "true", "false", "ja", "nein"}:
        return value.strip().lower() in {"1", "true", "ja"}
    raise ValueError("quest muss ja oder nein sein")


def _clean_note(value: Any) -> str:
    text = str(value or "").replace("\x00", "").strip()
    if len(text) > NOTE_MAX:
        raise ValueError(f"Notiz höchstens {NOTE_MAX} Zeichen")
    return text


def _clean_stored(key: str, raw: Any) -> dict[str, Any] | None:
    if not isinstance(raw, dict):
        return None
    try:
        rating = _clean_rating(raw.get("rating"))
        quest = _clean_quest(raw.get("quest", False))
        note = _clean_note(raw.get("note"))
    except ValueError:
        log.warning("object-picks: Eintrag %s übersprungen, Werte ungültig", key)
        return None
    if rating is None and not quest and not note:
        return None
    item: dict[str, Any] = {"quest": quest, "note": note}
    if rating is not None:
        item["rating"] = rating
    return item


def load_picks(horizon_dir: Path) -> dict[str, Any]:
    path = picks_path(horizon_dir)
    empty: dict[str, Any] = {
        "schema": PICKS_SCHEMA,
        "updated_at": None,
        "objects": {},
        "path": str(path),
        "corrupt": False,
        "error": "",
    }
    if not path.is_file():
        return empty
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        log.warning("object-picks beschädigt, wird nicht überschrieben: %s (%s)", path, exc)
        empty["corrupt"] = True
        empty["error"] = "object-picks.json ist beschädigt"
        return empty
    if not isinstance(raw, dict):
        log.warning("object-picks beschädigt, wird nicht überschrieben: %s (kein Objekt)", path)
        empty["corrupt"] = True
        empty["error"] = "object-picks.json ist beschädigt"
        return empty
    objects: dict[str, dict[str, Any]] = {}
    source = raw.get("objects")
    if isinstance(source, dict):
        for key, entry in source.items():
            name = str(key or "").strip()
            item = _clean_stored(name, entry)
            if name and item is not None:
                objects[name] = item
    return {
        "schema": PICKS_SCHEMA,
        "updated_at": raw.get("updated_at"),
        "objects": objects,
        "path": str(path),
        "corrupt": False,
        "error": "",
    }


def eligible_keys(objects: dict[str, Any], ngc_min: int) -> set[str]:
    """Freigegeben und bewertet, mindestens ngc_min. Ohne Rating keine Freigabe."""
    minimum = min(5, max(1, int(ngc_min)))
    chosen: set[str] = set()
    for key, entry in objects.items():
        if not isinstance(entry, dict) or not entry.get("quest"):
            continue
        rating = entry.get("rating")
        if isinstance(rating, bool) or not isinstance(rating, int):
            continue
        if rating >= minimum:
            chosen.add(str(key))
    return chosen


def upsert_pick(
    horizon_dir: Path,
    key: str,
    *,
    rating: int | None,
    quest: bool,
    note: str,
) -> dict[str, Any]:
    loaded = load_picks(horizon_dir)
    if loaded["corrupt"]:
        raise PicksCorrupt(loaded["error"] or "object-picks.json ist beschädigt")
    name = str(key or "").strip()
    if not name:
        raise ValueError("Schlüssel fehlt")
    rating_clean = _clean_rating(rating)
    quest_clean = _clean_quest(quest)
    note_clean = _clean_note(note)
    objects: dict[str, dict[str, Any]] = dict(loaded["objects"])
    if rating_clean is None and not quest_clean and not note_clean:
        objects.pop(name, None)
        item = None
    else:
        item = {"quest": quest_clean, "note": note_clean}
        if rating_clean is not None:
            item["rating"] = rating_clean
        objects[name] = item
    payload = {
        "schema": PICKS_SCHEMA,
        "updated_at": _utc_now(),
        "objects": objects,
    }
    path = picks_path(horizon_dir)
    _write_json(path, payload)
    payload["path"] = str(path)
    payload["corrupt"] = False
    payload["error"] = ""
    payload["key"] = name
    payload["pick"] = objects.get(name)
    return payload
