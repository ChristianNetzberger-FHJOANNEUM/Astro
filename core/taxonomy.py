"""Objekt- und Equipment-Tags fuer Sessions, ohne die NAS-Originale zu verschieben."""

from __future__ import annotations

import re
from collections import defaultdict
from dataclasses import dataclass
from pathlib import Path

from core.catalog import SessionRow

_TOKEN_SPLIT = re.compile(r"[-_\s./]+")

OBJECT_ALIASES = {
    "mond": "Mond",
    "moon": "Mond",
    "luna": "Mond",
    "sofi": "Sonne",
    "sonne": "Sonne",
    "sun": "Sonne",
    "solar": "Sonne",
    "eclipse": "Sonne",
    "jupiter": "Jupiter",
    "saturn": "Saturn",
    "mars": "Mars",
    "venus": "Venus",
    "m31": "M31",
    "andromeda": "M31",
}

EQUIPMENT_ALIASES = {
    "lumix": "Lumix",
    "s5": "Lumix",
    "s5ii": "Lumix",
    "s5iix": "Lumix",
    "newton": "Newton",
    "newt": "Newton",
    "10zoll": "Newton",
    "pst": "PST",
    "canon": "Canon",
    "asi": "ASI",
}

UNASSIGNED = "Ohne Zuordnung"


def tokens(name: str) -> list[str]:
    return [part for part in _TOKEN_SPLIT.split(name.casefold()) if part]


def infer_object(name: str) -> str:
    for token in tokens(name):
        if token in OBJECT_ALIASES:
            return OBJECT_ALIASES[token]
    return ""


def infer_equipment(name: str) -> str:
    for token in tokens(name):
        if token in EQUIPMENT_ALIASES:
            return EQUIPMENT_ALIASES[token]
    return ""


def resolve_tags(folder_name: str, object_hint: str = "", equipment_hint: str = "") -> tuple[str, str]:
    obj = object_hint.strip() or infer_object(folder_name)
    eqp = equipment_hint.strip() or infer_equipment(folder_name)
    return obj, eqp


def group_sessions(rows: list[SessionRow], key: str) -> list[tuple[str, list[SessionRow]]]:
    groups: dict[str, list[SessionRow]] = defaultdict(list)
    for row in rows:
        label = (getattr(row, key, "") or "").strip() or UNASSIGNED
        groups[label].append(row)
    return sorted(groups.items(), key=lambda item: (item[0] == UNASSIGNED, item[0].casefold()))


@dataclass
class LibraryFolder:
    name: str
    path: Path
    skipped: bool
    object: str
    equipment: str
    raw_count: int = 0
    jpg_count: int = 0
    imported: bool = False
    session_slug: str = ""
    image_count: int = 0


def _is_skipped_name(name: str, skip_names: tuple[str, ...]) -> bool:
    skip = {item.casefold() for item in skip_names}
    return name.casefold() in skip or name.startswith(".")


def _count_suffixes(folder: Path, suffixes: set[str], limit: int = 8000) -> int:
    count = 0
    for path in folder.rglob("*"):
        if path.is_file() and path.suffix.lower() in suffixes:
            count += 1
            if count >= limit:
                break
    return count


def list_library_folders(
    root: Path,
    skip_names: tuple[str, ...] = (),
    raw_suffixes: tuple[str, ...] = (),
    jpg_suffixes: tuple[str, ...] = (),
    count_files: bool = False,
) -> list[LibraryFolder]:
    if not root.is_dir():
        return []
    folders: list[LibraryFolder] = []
    raw_set = {item.lower() for item in raw_suffixes}
    jpg_set = {item.lower() for item in jpg_suffixes}
    for child in sorted(root.iterdir(), key=lambda path: path.name.casefold()):
        if not child.is_dir():
            continue
        skipped = _is_skipped_name(child.name, skip_names)
        obj, eqp = resolve_tags(child.name)
        raw_count = 0
        jpg_count = 0
        if count_files and not skipped:
            raw_count = _count_suffixes(child, raw_set) if raw_set else 0
            jpg_count = _count_suffixes(child, jpg_set) if jpg_set else 0
        folders.append(
            LibraryFolder(
                name=child.name,
                path=child,
                skipped=skipped,
                object=obj,
                equipment=eqp,
                raw_count=raw_count,
                jpg_count=jpg_count,
            )
        )
    return folders
