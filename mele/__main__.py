"""CLI: python -m mele horizon <panorama.jpg>"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parent.parent
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

from mele.horizon import DEFAULT_PROCESS_WIDTH, detect_horizon, render_overlay, save_profile


def _cmd_horizon(args: argparse.Namespace) -> int:
    path = Path(args.image)
    if not path.is_file():
        print(f"Bild nicht gefunden: {path}", file=sys.stderr)
        return 1
    out_dir = Path(args.out) if args.out else _REPO_ROOT / "data" / "horizon"
    profile = detect_horizon(
        path,
        north_x=args.north_x,
        process_width=args.width,
        median_window=args.median,
    )
    written = save_profile(profile, out_dir)
    overlay = render_overlay(path, profile, out_dir / f"{path.stem}.horizon.jpg")
    alts = [p.alt_deg for p in profile.points]
    print(f"Quelle:     {path}")
    print(f"Aufloesung: {profile.image_width} x {profile.image_height}")
    print(f"Punkte:     {len(profile.points)}")
    print(f"h(Az):      {min(alts):.1f} ... {max(alts):.1f} deg")
    print(f"JSON:       {written['json']}")
    print(f"CSV:        {written['csv']}")
    print(f"Overlay:    {overlay}")
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="python -m mele", description="MeLE Astro-Computer")
    sub = parser.add_subparsers(dest="command", required=True)
    horizon = sub.add_parser("horizon", help="sichtbaren Horizont aus 360-Panorama berechnen")
    horizon.add_argument("image", help="equirektangulares Panorama (JPG)")
    horizon.add_argument("--out", help="Ausgabeordner (default: data/horizon)")
    horizon.add_argument("--north-x", type=float, default=0.0, help="x-Pixel fuer Norden im Original")
    horizon.add_argument("--width", type=int, default=DEFAULT_PROCESS_WIDTH, help="Arbeitsspalten")
    horizon.add_argument("--median", type=int, default=9, help="Medianfenster in Spalten")
    catalog = sub.add_parser("catalog", help="Sternkatalog importieren oder anzeigen")
    catalog.add_argument("action", choices=["import", "info"])
    catalog.add_argument("--src", help="bereits heruntergeladene Katalogdateien")
    catalog.add_argument("--no-download", action="store_true")
    weather_journal = sub.add_parser(
        "weather-journal",
        help="GeoSphere-Forecast holen und ins Journal schreiben (Task Scheduler)",
    )
    weather_journal.add_argument("--lat", type=float, default=None)
    weather_journal.add_argument("--lon", type=float, default=None)
    weather_journal.add_argument("--force", action="store_true")
    weather_journal.add_argument("--label", default="")
    args = parser.parse_args(argv)
    if args.command == "horizon":
        return _cmd_horizon(args)
    if args.command == "catalog":
        from mele.catalog import main as catalog_main
        extra = [args.action]
        if args.src:
            extra.extend(["--src", args.src])
        if args.no_download:
            extra.append("--no-download")
        return catalog_main(extra)
    if args.command == "weather-journal":
        from mele.weather_journal_cli import run_weather_journal
        return run_weather_journal(
            latitude_deg=args.lat,
            longitude_deg=args.lon,
            force=args.force,
            label=args.label,
        )
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
