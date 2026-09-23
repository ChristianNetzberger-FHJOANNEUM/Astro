from __future__ import annotations

from pathlib import Path

from core.catalog import SessionRow
from core.config import load_app_settings, save_app_settings
from core.importer import discover_sessions
from core.taxonomy import group_sessions, infer_equipment, infer_object, list_library_folders, resolve_tags


def test_infer_tags_from_folder_name() -> None:
    assert infer_object("Mond-Lumix") == "Mond"
    assert infer_equipment("Mond-Lumix") == "Lumix"
    assert infer_object("Sofi-26") == "Sonne"
    assert resolve_tags("Newton-Jupiter", "Jupiter", "") == ("Jupiter", "Newton")


def test_discover_skips_inventory_and_tags_sessions(tmp_path: Path) -> None:
    (tmp_path / "Mond-Lumix").mkdir()
    (tmp_path / "Sofi-26").mkdir()
    (tmp_path / "Inventory").mkdir()
    (tmp_path / "siril_work").mkdir()
    sessions = discover_sessions(tmp_path, ("Inventory", "siril_work"))
    slugs = {session.slug for session in sessions}
    assert slugs == {"Mond-Lumix", "Sofi-26"}
    by_slug = {session.slug: session for session in sessions}
    assert by_slug["Mond-Lumix"].object == "Mond"
    assert by_slug["Mond-Lumix"].equipment == "Lumix"
    assert by_slug["Sofi-26"].object == "Sonne"


def test_group_sessions_by_object() -> None:
    rows = [
        SessionRow(1, "Mond-Lumix", "Mond Lumix", "x", "general", "", "Mond", "Lumix"),
        SessionRow(2, "Sofi-26", "Sofi", "y", "eclipse", "", "Sonne", "Lumix"),
        SessionRow(3, "misc", "Misc", "z", "general", "", "", ""),
    ]
    groups = dict(group_sessions(rows, "object"))
    assert set(groups) == {"Mond", "Sonne", "Ohne Zuordnung"}
    equipment = dict(group_sessions(rows, "equipment"))
    assert len(equipment["Lumix"]) == 2


def test_list_library_folders_marks_skipped(tmp_path: Path) -> None:
    (tmp_path / "Mond-Lumix").mkdir()
    (tmp_path / "Inventory").mkdir()
    folders = list_library_folders(tmp_path, ("Inventory",))
    by_name = {folder.name: folder for folder in folders}
    assert by_name["Inventory"].skipped
    assert not by_name["Mond-Lumix"].skipped
    assert by_name["Mond-Lumix"].object == "Mond"


def test_save_app_settings_roundtrip(tmp_path: Path) -> None:
    settings = load_app_settings()
    settings.library_root = tmp_path / "AstroRoot"
    target = tmp_path / "app.yaml"
    save_app_settings(settings, target)
    loaded = load_app_settings(target)
    assert loaded.library_root == settings.library_root
