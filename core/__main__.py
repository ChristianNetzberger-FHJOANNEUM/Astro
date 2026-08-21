"""CLI: python -m core scan | python -m core summary"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parent.parent
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

from core.catalog import Catalog
from core.config import load_app_settings
from core.importer import scan_library


def _cmd_scan() -> int:
    settings = load_app_settings()
    print(f"Bibliothek: {settings.library_root}")
    print(f"Katalog:    {settings.catalog_path}")
    reports = scan_library(settings)
    for report in reports:
        print()
        print(f"Session {report.session_slug}")
        print(f"  Aufnahmen: {report.captures}  (RAW {report.raws}, JPG {report.jpgs})")
        print(f"  Bursts:    {report.bursts}   Einzelbilder: {report.singles}")
        if report.time_first:
            print(f"  Zeitraum:  {report.time_first}  ->  {report.time_last}  ({report.datetime_src})")
        for msg in report.messages:
            print(f"  {msg}")
    return 0


def _cmd_summary() -> int:
    settings = load_app_settings()
    catalog = Catalog(settings.catalog_path)
    try:
        totals = catalog.summary()
        print(
            f"Sessions {totals['sessions']}  Bursts {totals['bursts']}  Bilder {totals['images']}"
        )
        for session in catalog.list_sessions():
            print(
                f"  {session.slug}: {session.image_count} Bilder, "
                f"{session.burst_count} Gruppen ({session.kind})"
            )
    finally:
        catalog.close()
    return 0



def _cmd_workspace() -> int:
    settings = load_app_settings()
    catalog = Catalog(settings.catalog_path)
    try:
        from core.siril_workspace import create_workspace
        sessions = catalog.list_sessions()
        if not sessions:
            print("Keine Session im Katalog.")
            return 1
        session = sessions[0]
        bursts = [b for b in catalog.list_bursts(session.id) if b.kind == "burst"]
        bursts.sort(key=lambda b: b.frame_count, reverse=True)
        if not bursts:
            print("Keine Bursts.")
            return 1
        burst = bursts[0]
        frames = catalog.list_images(burst.id)
        result = create_workspace(session, burst, frames, work_subdir=settings.siril_work_subdir)
        catalog.upsert_workspace(burst.id, str(result.path), result.link_mode, result.linked)
        print(f"Burst {burst.burst_no:03d}: {result.linked} Links ({result.link_mode})")
        print(result.path)
    finally:
        catalog.close()
    return 0

def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="python -m core", description="Astro-Katalog")
    parser.add_argument("command", nargs="?", default="summary", choices=("scan", "summary", "workspace"))
    args = parser.parse_args(argv)

    if args.command == "workspace":
        return _cmd_workspace()
    if args.command == "scan":
        return _cmd_scan()
    return _cmd_summary()


if __name__ == "__main__":
    raise SystemExit(main())
