"""NAS scannen, Metadaten lesen, Bursts bilden - Originale unveraendert lassen."""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

from core.burst import detect_bursts
from core.catalog import Catalog
from core.config import AppSettings, SessionConfig, load_app_settings, load_session_configs, session_config_for
from core.eclipse import annotate_bursts
from core.exif import build_capture
from core.models import Capture, SessionInfo
from core.taxonomy import resolve_tags


@dataclass
class ScanReport:
    session_slug: str
    captures: int
    bursts: int
    singles: int
    raws: int
    jpgs: int
    time_first: str = ""
    time_last: str = ""
    datetime_src: str = ""
    messages: list[str] = field(default_factory=list)


def discover_sessions(
    library_root: Path,
    skip_names: tuple[str, ...] = (),
    configs: dict[str, SessionConfig] | None = None,
) -> list[SessionInfo]:
    if not library_root.is_dir():
        return []
    skip = {name.casefold() for name in skip_names}
    configs = configs if configs is not None else load_session_configs()
    sessions: list[SessionInfo] = []
    for child in sorted(library_root.iterdir(), key=lambda path: path.name.casefold()):
        if not child.is_dir() or child.name.startswith(".") or child.name.casefold() in skip:
            continue
        cfg = session_config_for(child.name, configs)
        obj, eqp = resolve_tags(
            child.name,
            cfg.object if cfg else "",
            cfg.equipment if cfg else "",
        )
        sessions.append(
            SessionInfo(
                slug=cfg.slug if cfg else child.name,
                title=(cfg.title if cfg else child.name),
                root_path=child,
                kind=cfg.kind if cfg else "general",
                originals_subdir=cfg.originals_subdir if cfg else "",
                notes=cfg.notes if cfg else "",
                object=obj,
                equipment=eqp,
            )
        )
    return sessions


def _is_skipped(path: Path, root: Path, skip_names: tuple[str, ...]) -> bool:
    try:
        relative = path.relative_to(root)
    except ValueError:
        return True
    skip = {name.casefold() for name in skip_names}
    return any(part.casefold() in skip for part in relative.parts)


def collect_captures(
    session_root: Path,
    settings: AppSettings,
    originals_subdir: str = "",
) -> list[Capture]:
    search_root = session_root / originals_subdir if originals_subdir else session_root
    if not search_root.is_dir():
        search_root = session_root

    raw_suffixes = set(settings.original_raw_suffixes)
    jpg_suffixes = set(settings.original_jpg_suffixes)
    by_stem: dict[str, dict[str, Path]] = {}

    for path in search_root.rglob("*"):
        if not path.is_file():
            continue
        if _is_skipped(path, session_root, settings.skip_dir_names):
            continue
        suffix = path.suffix.lower()
        stem_key = path.stem.casefold()
        slot = by_stem.setdefault(stem_key, {})
        if suffix in raw_suffixes:
            slot["raw"] = path
        elif suffix in jpg_suffixes:
            slot["jpg"] = path

    captures: list[Capture] = []
    for files in by_stem.values():
        raw = files.get("raw")
        jpg = files.get("jpg")
        if raw is None and jpg is None:
            continue
        captures.append(build_capture(raw, jpg))
    return captures


def scan_session(
    session: SessionInfo,
    catalog: Catalog,
    settings: AppSettings,
    session_cfg: SessionConfig | None,
) -> ScanReport:
    captures = collect_captures(session.root_path, settings, session.originals_subdir)
    bursts = detect_bursts(captures, settings.burst)
    annotate_bursts(bursts, session_cfg)
    catalog.replace_session(
        slug=session.slug,
        title=session.title,
        root_path=str(session.root_path),
        kind=session.kind,
        notes=session.notes,
        bursts=bursts,
        object=session.object,
        equipment=session.equipment,
    )
    dts = [c.datetime for c in captures if c.datetime is not None]
    srcs = {c.datetime_src for c in captures if c.datetime_src}
    return ScanReport(
        session_slug=session.slug,
        captures=len(captures),
        bursts=sum(1 for b in bursts if b.kind == "burst"),
        singles=sum(1 for b in bursts if b.kind == "single"),
        raws=sum(1 for c in captures if c.raw_path is not None),
        jpgs=sum(1 for c in captures if c.jpg_path is not None),
        time_first=min(dts).isoformat(sep=" ", timespec="seconds") if dts else "",
        time_last=max(dts).isoformat(sep=" ", timespec="seconds") if dts else "",
        datetime_src=",".join(sorted(srcs)),
    )


def scan_library(
    settings: AppSettings | None = None,
    catalog: Catalog | None = None,
    slugs: list[str] | None = None,
) -> list[ScanReport]:
    settings = settings or load_app_settings()
    own_catalog = catalog is None
    catalog = catalog or Catalog(settings.catalog_path)
    configs = load_session_configs()
    reports: list[ScanReport] = []
    try:
        sessions = discover_sessions(settings.library_root, settings.skip_dir_names, configs)
        if slugs:
            wanted = {item.casefold() for item in slugs}
            sessions = [
                session
                for session in sessions
                if session.slug.casefold() in wanted or session.root_path.name.casefold() in wanted
            ]
        if not sessions:
            reports.append(
                ScanReport(
                    session_slug="-",
                    captures=0,
                    bursts=0,
                    singles=0,
                    raws=0,
                    jpgs=0,
                    messages=[f"Bibliothek nicht gefunden oder leer: {settings.library_root}"],
                )
            )
            return reports
        for session in sessions:
            cfg = session_config_for(session.root_path.name, configs)
            reports.append(scan_session(session, catalog, settings, cfg))
        return reports
    finally:
        if own_catalog:
            catalog.close()
