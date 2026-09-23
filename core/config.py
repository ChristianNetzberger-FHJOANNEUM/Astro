from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml

REPO_ROOT = Path(__file__).resolve().parent.parent


def _load_yaml(path: Path) -> dict[str, Any]:
    if not path.is_file():
        return {}
    data = yaml.safe_load(path.read_text(encoding="utf-8"))
    return data if isinstance(data, dict) else {}


@dataclass
class BurstSettings:
    same_burst_gap_s: float = 0.2
    new_burst_gap_s: float = 1.0
    min_burst_frames: int = 2


@dataclass
class AppSettings:
    library_root: Path = Path("N:/Astro")
    catalog_path: Path = REPO_ROOT / "data" / "astro.sqlite"
    ui_port: int = 8081
    skip_dir_names: tuple[str, ...] = (
        "Siril",
        "siril_work",
        "results",
        "resolve",
        "excluded",
        "Inventory",
        ".git",
    )
    original_raw_suffixes: tuple[str, ...] = (
        ".rw2",
        ".cr2",
        ".cr3",
        ".nef",
        ".arw",
        ".dng",
        ".raf",
    )
    original_jpg_suffixes: tuple[str, ...] = (".jpg", ".jpeg")
    burst: BurstSettings = field(default_factory=BurstSettings)
    siril_work_subdir: str = "siril_work"


@dataclass
class EclipseContacts:
    C1: str | None = None
    C2: str | None = None
    C3: str | None = None
    C4: str | None = None


@dataclass
class SessionConfig:
    slug: str
    title: str = ""
    kind: str = "general"
    timezone: str = "Europe/Madrid"
    location: str = ""
    originals_subdir: str = ""
    camera_clock_offset_s: float = 0.0
    contacts: EclipseContacts = field(default_factory=EclipseContacts)
    notes: str = ""
    object: str = ""
    equipment: str = ""


def load_app_settings(path: Path | None = None) -> AppSettings:
    cfg_path = path or REPO_ROOT / "configs" / "app.yaml"
    raw = _load_yaml(cfg_path)
    burst_raw = raw.get("burst") or {}
    catalog = raw.get("catalog_path") or "data/astro.sqlite"
    catalog_path = Path(catalog)
    if not catalog_path.is_absolute():
        catalog_path = REPO_ROOT / catalog_path
    suffixes_raw = raw.get("original_raw_suffixes") or []
    suffixes_jpg = raw.get("original_jpg_suffixes") or []
    skip = raw.get("skip_dir_names") or list(AppSettings.skip_dir_names)
    return AppSettings(
        library_root=Path(raw.get("library_root") or "N:/Astro"),
        catalog_path=catalog_path,
        ui_port=int(raw.get("ui_port") or 8081),
        skip_dir_names=tuple(str(x) for x in skip),
        original_raw_suffixes=tuple(str(x).lower() for x in suffixes_raw)
        if suffixes_raw
        else AppSettings.original_raw_suffixes,
        original_jpg_suffixes=tuple(str(x).lower() for x in suffixes_jpg)
        if suffixes_jpg
        else AppSettings.original_jpg_suffixes,
        burst=BurstSettings(
            same_burst_gap_s=float(burst_raw.get("same_burst_gap_s", 0.2)),
            new_burst_gap_s=float(burst_raw.get("new_burst_gap_s", 1.0)),
            min_burst_frames=int(burst_raw.get("min_burst_frames", 2)),
        ),
        siril_work_subdir=str(raw.get("siril_work_subdir") or "siril_work"),
    )


def _catalog_path_for_yaml(path: Path) -> str:
    try:
        return path.relative_to(REPO_ROOT).as_posix()
    except ValueError:
        return path.as_posix()


def save_app_settings(settings: AppSettings, path: Path | None = None) -> Path:
    cfg_path = path or REPO_ROOT / "configs" / "app.yaml"
    payload = {
        "library_root": settings.library_root.as_posix(),
        "catalog_path": _catalog_path_for_yaml(settings.catalog_path),
        "ui_port": settings.ui_port,
        "skip_dir_names": list(settings.skip_dir_names),
        "burst": {
            "same_burst_gap_s": settings.burst.same_burst_gap_s,
            "new_burst_gap_s": settings.burst.new_burst_gap_s,
            "min_burst_frames": settings.burst.min_burst_frames,
        },
        "original_raw_suffixes": list(settings.original_raw_suffixes),
        "original_jpg_suffixes": list(settings.original_jpg_suffixes),
        "siril_work_subdir": settings.siril_work_subdir,
    }
    cfg_path.parent.mkdir(parents=True, exist_ok=True)
    cfg_path.write_text(
        yaml.safe_dump(payload, allow_unicode=True, sort_keys=False),
        encoding="utf-8",
    )
    return cfg_path


def _parse_session(slug: str, raw: dict[str, Any]) -> SessionConfig:
    contacts_raw = raw.get("contacts") or {}
    return SessionConfig(
        slug=str(raw.get("slug") or slug),
        title=str(raw.get("title") or slug),
        kind=str(raw.get("kind") or "general"),
        timezone=str(raw.get("timezone") or "Europe/Madrid"),
        location=str(raw.get("location") or ""),
        originals_subdir=str(raw.get("originals_subdir") or ""),
        camera_clock_offset_s=float(raw.get("camera_clock_offset_s") or 0),
        contacts=EclipseContacts(
            C1=contacts_raw.get("C1"),
            C2=contacts_raw.get("C2"),
            C3=contacts_raw.get("C3"),
            C4=contacts_raw.get("C4"),
        ),
        notes=str(raw.get("notes") or ""),
        object=str(raw.get("object") or ""),
        equipment=str(raw.get("equipment") or ""),
    )


def load_session_configs(directory: Path | None = None) -> dict[str, SessionConfig]:
    folder = directory or REPO_ROOT / "configs" / "sessions"
    result: dict[str, SessionConfig] = {}
    if not folder.is_dir():
        return result
    for path in sorted(folder.glob("*.yaml")):
        raw = _load_yaml(path)
        if not raw:
            continue
        cfg = _parse_session(path.stem, raw)
        result[cfg.slug.casefold()] = cfg
        result[path.stem.casefold()] = cfg
    return result


def session_config_for(folder_name: str, configs: dict[str, SessionConfig] | None = None) -> SessionConfig | None:
    mapping = configs if configs is not None else load_session_configs()
    return mapping.get(folder_name.casefold())
