"""S2: Wetterexport, Idle-Check, Session-Close."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from pathlib import Path
from types import SimpleNamespace

import pytest

from mele.astro_manager import create_session, get_session, set_session_lifecycle
from mele.session_close import (
    SessionCloseError,
    close_imaging_session,
    export_weather_for_session,
)
from mele.session_idle import check_session_idle
from mele.session_storage import LIFECYCLE_CLOSED, LIFECYCLE_OPEN
from mele.session_weather import (
    assess_export_status,
    detect_gaps,
    export_session_weather_files,
    filter_samples_window,
    parse_iso_utc,
)
from mele.weather_server_client import WeatherServerError


def _sample(offset_s: float, *, sid: int = 1, start: datetime | None = None) -> dict:
    base = start or datetime(2026, 10, 8, 20, 0, 0, tzinfo=timezone.utc)
    when = base + timedelta(seconds=offset_s)
    return {
        "id": sid,
        "recorded_at": when.isoformat(),
        "temp_c": 10.0 + offset_s / 1000.0,
        "humidity_pct": 70.0,
        "dewpoint_c": 5.0,
        "wind_ms": 1.0,
        "pressure_hpa": 1013.0,
    }


def test_filter_and_gaps() -> None:
    start = datetime(2026, 10, 8, 20, 0, 0, tzinfo=timezone.utc)
    end = start + timedelta(minutes=10)
    samples = [
        _sample(0, sid=1, start=start),
        _sample(30, sid=2, start=start),
        _sample(400, sid=3, start=start),  # grosse Luecke
        _sample(9000, sid=4, start=start),  # ausserhalb Fenster
    ]
    filtered = filter_samples_window(samples, start=start, end=end)
    assert [s["id"] for s in filtered] == [1, 2, 3]
    gaps = detect_gaps(filtered, gap_threshold_s=120, window_start=start, window_end=end)
    kinds = {g["kind"] for g in gaps}
    assert "between" in kinds


def test_assess_truncated_partial() -> None:
    start = datetime(2026, 10, 8, 20, 0, 0, tzinfo=timezone.utc)
    filtered = [_sample(60, start=start)]
    status, truncated = assess_export_status(
        api_sample_count=5000,
        history_limit=5000,
        gaps=[],
        window_start=start,
        filtered_samples=filtered,
    )
    assert status == "partial"
    assert truncated is True


def test_export_writes_csv_and_summary(tmp_path: Path) -> None:
    start = datetime(2026, 10, 8, 20, 0, 0, tzinfo=timezone.utc)
    end = start + timedelta(hours=1)
    session_dir = tmp_path / "M101" / "2026-10-08" / "s00001"
    session_dir.mkdir(parents=True)

    def fake_fetch(url: str, *, limit: int = 120, since: str | None = None, timeout_s: float = 8.0):
        assert since is not None
        assert "2026-10-08" in since
        # neueste zuerst wie API
        return [
            _sample(120, sid=2, start=start),
            _sample(0, sid=1, start=start),
            _sample(99999, sid=99, start=start),  # nach end → raus
        ]

    result = export_session_weather_files(
        session_id=1,
        session_dir=session_dir,
        start_utc=start.isoformat(),
        end_utc=end.isoformat(),
        weather_server_url="http://127.0.0.1:8765",
        gap_threshold_s=120,
        fetch_history_fn=fake_fetch,
    )
    assert result.export_status == "ok"
    assert result.sample_count == 2
    assert Path(result.csv_path).is_file()
    assert Path(result.summary_path).is_file()
    csv_text = Path(result.csv_path).read_text(encoding="utf-8")
    assert "temp_c" in csv_text
    assert csv_text.count("\n") >= 3  # header + 2

    # Re-Export idempotent (ersetzt)
    again = export_session_weather_files(
        session_id=1,
        session_dir=session_dir,
        start_utc=start.isoformat(),
        end_utc=end.isoformat(),
        weather_server_url="http://127.0.0.1:8765",
        fetch_history_fn=fake_fetch,
    )
    assert again.export_status == "ok"
    assert again.sample_count == 2


def test_export_unavailable_on_server_error(tmp_path: Path) -> None:
    session_dir = tmp_path / "s1"
    session_dir.mkdir()

    def boom(*args, **kwargs):
        raise WeatherServerError("unreachable")

    result = export_session_weather_files(
        session_id=1,
        session_dir=session_dir,
        start_utc="2026-10-08T20:00:00+00:00",
        end_utc="2026-10-08T21:00:00+00:00",
        weather_server_url="http://127.0.0.1:8765",
        fetch_history_fn=boom,
    )
    assert result.export_status == "unavailable"
    assert "unreachable" in result.error
    assert Path(result.summary_path).is_file()


def test_export_partial_when_limit_hit(tmp_path: Path) -> None:
    start = datetime(2026, 10, 8, 18, 0, 0, tzinfo=timezone.utc)
    end = start + timedelta(hours=6)
    session_dir = tmp_path / "s2"
    session_dir.mkdir()

    def fake_fetch(*args, **kwargs):
        # 5000 Samples, aeltestes deutlich nach Session-Start
        out = []
        for i in range(5000):
            out.append(_sample(3600 + i, sid=i, start=start))
        return out

    result = export_session_weather_files(
        session_id=2,
        session_dir=session_dir,
        start_utc=start.isoformat(),
        end_utc=end.isoformat(),
        weather_server_url="http://x",
        history_limit=5000,
        fetch_history_fn=fake_fetch,
    )
    assert result.export_status == "partial"
    assert result.truncated is True


def test_idle_check_me_capture_and_exposing() -> None:
    idle = check_session_idle(nina_client=object(), me_capture_inflight=1)
    assert idle.idle is False
    assert "MeLE-Capture" in idle.reason

    class FakeNina:
        def get_camera_info(self):
            return SimpleNamespace(
                api_online=True,
                error="",
                camera=SimpleNamespace(is_exposing=True, camera_state="Idle"),
            )

    busy = check_session_idle(nina_client=FakeNina(), me_capture_inflight=0)
    assert busy.idle is False
    assert "IsExposing" in busy.reason

    class FakeDownload:
        def get_camera_info(self):
            return SimpleNamespace(
                api_online=True,
                error="",
                camera=SimpleNamespace(is_exposing=False, camera_state="Download"),
            )

    dl = check_session_idle(nina_client=FakeDownload(), me_capture_inflight=0)
    assert dl.idle is False
    assert "Download" in dl.reason

    class FakeIdle:
        def get_camera_info(self):
            return SimpleNamespace(
                api_online=True,
                error="",
                camera=SimpleNamespace(is_exposing=False, camera_state="Idle"),
            )

    ok = check_session_idle(nina_client=FakeIdle(), me_capture_inflight=0)
    assert ok.idle is True

    class Offline:
        def get_camera_info(self):
            return SimpleNamespace(api_online=False, error="down", camera=None)

    unclear = check_session_idle(nina_client=Offline(), me_capture_inflight=0)
    assert unclear.idle is False
    assert "unklar" in unclear.reason.lower() or "nicht erreichbar" in unclear.reason.lower()


def test_close_and_reexport(tmp_path: Path) -> None:
    db = tmp_path / "astro.sqlite"
    session_dir = tmp_path / "cap" / "M31" / "2026-10-08" / "s00001"
    session_dir.mkdir(parents=True)
    session = create_session(
        catalog_key="M31",
        frames_completed=2,
        local_path=str(session_dir),
        db_path=db,
    )
    assert session.lifecycle_status != LIFECYCLE_CLOSED

    class FakeNina:
        def get_camera_info(self):
            return SimpleNamespace(
                api_online=True,
                error="",
                camera=SimpleNamespace(is_exposing=False, camera_state="Idle"),
            )

    start = parse_iso_utc(session.session_start_utc) or datetime.now(timezone.utc)

    def fake_fetch(*args, **kwargs):
        return [_sample(0, sid=1, start=start), _sample(30, sid=2, start=start)]

    # Patch export path via monkeypatch of fetch inside close by providing url
    # and patching fetch_history used by export_session_weather_files — inject via
    # temporary monkeypatch on module.
    import mele.session_weather as sw

    original = sw.fetch_history
    sw.fetch_history = fake_fetch  # type: ignore[assignment]
    try:
        closed = close_imaging_session(
            session.id,
            nina_client=FakeNina(),
            me_capture_inflight=0,
            weather_server_url="http://127.0.0.1:8765",
            poll_interval_s=20.0,
            db_path=db,
        )
    finally:
        sw.fetch_history = original

    assert closed.session["lifecycle_status"] == LIFECYCLE_CLOSED
    assert closed.weather["export_status"] in ("ok", "partial")
    assert (session_dir / "weather" / "weather.csv").is_file()

    # Close waehrend MeLE-Capture → 409-aequivalent
    open_sess = create_session(catalog_key="M42", local_path=str(session_dir), db_path=db)
    with pytest.raises(SessionCloseError, match="MeLE-Capture"):
        close_imaging_session(
            open_sess.id,
            nina_client=FakeNina(),
            me_capture_inflight=2,
            weather_server_url="http://127.0.0.1:8765",
            db_path=db,
        )
    assert get_session(open_sess.id, db_path=db).lifecycle_status == LIFECYCLE_OPEN

    # Re-Export nur CLOSED
    with pytest.raises(SessionCloseError, match="CLOSED"):
        export_weather_for_session(
            open_sess.id,
            weather_server_url="http://127.0.0.1:8765",
            db_path=db,
            require_closed=True,
        )

    set_session_lifecycle(open_sess.id, LIFECYCLE_CLOSED, db_path=db)
    sw.fetch_history = fake_fetch  # type: ignore[assignment]
    try:
        sess2, exp = export_weather_for_session(
            open_sess.id,
            weather_server_url="http://127.0.0.1:8765",
            db_path=db,
        )
    finally:
        sw.fetch_history = original
    assert sess2.weather_export_status == exp.export_status
    assert sess2.lifecycle_status == LIFECYCLE_CLOSED


def test_fetch_history_passes_since(monkeypatch: pytest.MonkeyPatch) -> None:
    from mele.weather_server_client import fetch_history
    import json

    captured: dict = {}

    class _Resp:
        def read(self) -> bytes:
            return json.dumps({"ok": True, "samples": [{"id": 1}]}).encode()

        def __enter__(self):
            return self

        def __exit__(self, *args):
            return False

    def fake_urlopen(req, timeout=None):
        captured["url"] = req.full_url
        return _Resp()

    monkeypatch.setattr("mele.weather_server_client.urlopen", fake_urlopen)
    rows = fetch_history(
        "http://127.0.0.1:8765",
        limit=50,
        since="2026-10-08T20:00:00+00:00",
    )
    assert len(rows) == 1
    assert "since=2026-10-08" in captured["url"]
    assert "limit=50" in captured["url"]
