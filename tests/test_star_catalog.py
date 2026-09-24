from datetime import datetime, timezone, timedelta
from pathlib import Path

import numpy as np

from mele.catalog import (
    build_database,
    catalog_ready,
    classify_daylight,
    object_track,
    parse_constellation_fab,
    query_overlay,
)
from mele.horizon import HorizonPoint, HorizonProfile
from mele.sky import radec_to_az_alt

FIXTURES = Path(__file__).resolve().parent / "fixtures" / "catalog"
VEGA_RA = 18.61564 * 15.0
VEGA_DEC = 38.783692


def _build(tmp_path: Path) -> Path:
    db = tmp_path / "sky.sqlite"
    stats = build_database(
        db,
        hyg=FIXTURES / "hyg.csv",
        fab=FIXTURES / "constellationship.fab",
        ngc=[FIXTURES / "NGC.csv"],
    )
    assert stats["stars"] == 3
    assert stats["lines"] == 1
    assert stats["dso"] >= 2
    assert catalog_ready(db)
    return db


def test_fab_pairs() -> None:
    lines = parse_constellation_fab(FIXTURES / "constellationship.fab")
    assert lines == [("Lyr", 91262, 91971)]


def test_overlay_matches_sky_math_and_time_shift(tmp_path: Path) -> None:
    db = _build(tmp_path)
    when = datetime(2026, 9, 23, 18, 0, tzinfo=timezone.utc)
    data = query_overlay(
        db_path=db,
        latitude_deg=48.2,
        longitude_deg=16.4,
        when=when,
        mag_limit=5.5,
        stars=True,
        constellations=True,
        messier=True,
        ngc=False,
    )
    vega = next(item for item in data["stars"] if item.get("name") == "Vega")
    az, alt = radec_to_az_alt(VEGA_RA, VEGA_DEC, 48.2, 16.4, when)
    assert abs(vega["az"] - az) < 0.05
    assert abs(vega["alt"] - alt) < 0.05
    assert abs(vega["ra"] - VEGA_RA) < 0.01
    assert abs(vega["dec"] - VEGA_DEC) < 0.01
    assert vega.get("con") == "Lyr"
    assert data["lines"]
    assert data["lines"][0]["iau"] == "Lyr"
    assert any(item["id"] == "M31" for item in data["dso"])
    later = query_overlay(
        db_path=db,
        latitude_deg=48.2,
        longitude_deg=16.4,
        when=when + timedelta(hours=6),
        mag_limit=5.5,
        messier=False,
        ngc=False,
    )
    vega2 = next(item for item in later["stars"] if item.get("name") == "Vega")
    delta = (vega2["az"] - vega["az"] + 180) % 360 - 180
    assert abs(delta) > 50


def test_horizon_hides_objects_below_profile(tmp_path: Path) -> None:
    db = _build(tmp_path)
    when = datetime(2026, 9, 23, 18, 0, tzinfo=timezone.utc)
    az, alt = radec_to_az_alt(VEGA_RA, VEGA_DEC, 48.2, 16.4, when)
    wall = HorizonProfile(
        source="x.jpg",
        image_width=360,
        image_height=180,
        process_width=360,
        process_height=180,
        north_x=0.0,
        points=[
            HorizonPoint(az_deg=float(step), alt_deg=alt + 10.0, x=step, y=0)
            for step in range(0, 360, 10)
        ],
    )
    hidden = query_overlay(
        db_path=db,
        latitude_deg=48.2,
        longitude_deg=16.4,
        when=when,
        profile=wall,
        messier=False,
        ngc=False,
    )
    assert not any(item.get("name") == "Vega" for item in hidden["stars"])


def test_object_track_windows_respect_horizon() -> None:
    when = datetime(2026, 9, 23, 18, 0, tzinfo=timezone.utc)
    open_sky = object_track(
        ra_deg=VEGA_RA,
        dec_deg=VEGA_DEC,
        latitude_deg=48.2,
        longitude_deg=16.4,
        when=when,
        step_min=30,
    )
    assert len(open_sky["points"]) == 48
    assert open_sky["windows"]
    assert any(point["above"] for point in open_sky["points"])
    wall = HorizonProfile(
        source="x.jpg",
        image_width=360,
        image_height=180,
        process_width=360,
        process_height=180,
        north_x=0.0,
        points=[HorizonPoint(az_deg=float(step), alt_deg=89.0, x=step, y=0) for step in range(0, 360, 10)],
    )
    blocked = object_track(
        ra_deg=VEGA_RA,
        dec_deg=VEGA_DEC,
        latitude_deg=48.2,
        longitude_deg=16.4,
        when=when,
        profile=wall,
        step_min=30,
    )
    assert not blocked["windows"]
    assert not any(point["above"] for point in blocked["points"])


def test_classify_daylight_hour_around_rise_set() -> None:
    day = datetime(2026, 9, 23, tzinfo=timezone.utc)
    stamps = [day + timedelta(hours=hour) for hour in range(24)]
    alts = np.array([-10.0 if hour < 6 or hour >= 18 else 20.0 for hour in range(24)])
    from mele.catalog import _horizon_crossings

    rises, sets = _horizon_crossings(stamps, alts)
    phases = classify_daylight(stamps, alts, rises + sets, twilight_min=60)
    by_hour = {stamp.hour: phase for stamp, phase in zip(stamps, phases, strict=True)}
    assert by_hour[12] == "day"
    assert by_hour[21] == "night"
    assert by_hour[5] == "twilight"
    assert by_hour[6] == "twilight"
    assert by_hour[17] == "twilight"
    assert by_hour[18] == "twilight"
    assert by_hour[4] == "night"
    assert by_hour[7] == "day"


def test_object_track_marks_day_twilight_night() -> None:
    when = datetime(2026, 9, 23, 18, 0, tzinfo=timezone.utc)
    track = object_track(
        ra_deg=VEGA_RA,
        dec_deg=VEGA_DEC,
        latitude_deg=48.2,
        longitude_deg=16.4,
        when=when,
        step_min=30,
    )
    lights = {point["light"] for point in track["points"]}
    assert lights >= {"night", "twilight", "day"}
    assert track["sunrise"]
    assert track["sunset"]
    assert track["twilight_min"] == 60
    noon = next(point for point in track["points"] if point["when"].startswith("2026-09-23T12:"))
    late = next(point for point in track["points"] if point["when"].startswith("2026-09-23T21:"))
    assert noon["light"] == "day"
    assert late["light"] == "night"
    assert any(slot.get("light") == "night" for slot in track["windows"])
