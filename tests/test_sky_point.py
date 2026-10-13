from datetime import datetime, timezone
from pathlib import Path

from mele.mount_motion import target_block_reason
from mele.sky import az_alt_to_radec

WHEN = datetime(2026, 10, 13, 20, 0, tzinfo=timezone.utc)


def test_low_point_is_blocked_without_a_slew() -> None:
    ra, dec = az_alt_to_radec(180.0, -10.0, 48.25475, 14.36614, WHEN)
    assert target_block_reason(ra, dec, 48.25475, 14.36614, WHEN, None) == "Ziel unter Horizont"


def test_sky_point_route_only_reads() -> None:
    app = Path("app_mele/main_app.py").read_text(encoding="utf-8")
    block = app[app.index("def sky_point"):app.index("def catalog_picks_get")]
    assert "az_alt_to_radec" in block
    assert "target_block_reason" in block
    assert "slew" not in block
    page = Path("app_mele/vr.html").read_text(encoding="utf-8")
    adopt = page[page.index("async function adoptSkyPoint"):page.index("async function confirmSkyPointGoto")]
    assert "/sky/point?" in adopt
    assert "/nina/mount/slew" not in adopt
    confirm = page[page.index("async function confirmSkyPointGoto"):page.index("async function confirmQuestGoto")]
    assert "ra=" in confirm and "dec=" in confirm
    assert "target=" not in confirm
    assert "HIMMELSPUNKT" in page
    assert "GOTO PUNKT" in page
    caddy = Path(r"C:\Caddy\Caddyfile").read_text(encoding="utf-8")
    sky = caddy[caddy.index("@sky_track"):caddy.index("handle @sky_track")]
    assert "/sky/point" in sky
    control = caddy[caddy.index("@mount_control"):caddy.index("handle @mount_control")]
    assert "/sky/point" not in control
