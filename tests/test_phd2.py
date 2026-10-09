"""Unit-Tests PHD2 Launch / Client / Image helpers."""

from __future__ import annotations

import base64
from pathlib import Path

import numpy as np
import pytest
from astropy.io import fits

from mele.phd2 import (
    TELEMETRY_SECONDS,
    Phd2Client,
    _fits_path_to_jpeg,
    _map_connection_state,
    _stretch_to_jpeg,
    arcsec_to_pixels,
    enrich_guide_step_dict,
    is_mount_alert_message,
    normalize_pixel_scale,
    pixels_to_arcsec,
)
from mele.phd2_launch import resolve_phd2_exe


def test_resolve_phd2_exe_configured(tmp_path: Path) -> None:
    exe = tmp_path / "phd2.exe"
    exe.write_bytes(b"x")
    assert resolve_phd2_exe(exe) == exe
    assert resolve_phd2_exe(tmp_path).name == "phd2.exe"


def test_telemetry_window_covers_graph() -> None:
    # Phase 1.5 Graph: 5–10 min Puffer
    assert 300.0 <= TELEMETRY_SECONDS <= 600.0


def test_pixel_scale_conversion() -> None:
    assert normalize_pixel_scale(3.09) == pytest.approx(3.09)
    assert normalize_pixel_scale(0) is None
    assert normalize_pixel_scale(-1) is None
    assert normalize_pixel_scale(float("nan")) is None
    assert normalize_pixel_scale(None) is None
    assert pixels_to_arcsec(0.4, 3.09) == pytest.approx(1.236)
    assert pixels_to_arcsec(0.4, None) is None
    assert pixels_to_arcsec(None, 3.09) is None
    assert arcsec_to_pixels(1.236, 3.09) == pytest.approx(0.4)
    assert arcsec_to_pixels(1.0, 0) is None


def test_enrich_guide_step_dict_units() -> None:
    step = {"ra_distance": 0.5, "dec_distance": -0.25, "avg_dist": 0.6}
    with_scale = enrich_guide_step_dict(step, 3.09)
    assert with_scale["display_unit"] == "arcsec"
    assert with_scale["ra_distance_px"] == pytest.approx(0.5)
    assert with_scale["ra_distance_arcsec"] == pytest.approx(1.545)
    assert with_scale["dec_distance_arcsec"] == pytest.approx(-0.7725)
    no_scale = enrich_guide_step_dict(step, None)
    assert no_scale["display_unit"] == "px"
    assert no_scale["ra_distance_arcsec"] is None


def test_telemetry_reports_px_and_arcsec() -> None:
    client = Phd2Client(host="127.0.0.1", port=9)
    client._sock = object()  # type: ignore[assignment]
    client._pixel_scale_stale = False
    client._status.pixel_scale_arcsec_px = 3.09
    client._handle_message(
        {
            "Event": "GuideStep",
            "Frame": 1,
            "Time": 12.5,
            "RADistanceRaw": 0.4,
            "DECDistanceRaw": -0.2,
            "RADuration": 250,
            "RADirection": "West",
            "DECDuration": 120,
            "DECDirection": "North",
            "SNR": 40.0,
            "HFD": 2.5,
        }
    )
    tel = client.telemetry()
    assert tel["display_unit"] == "arcsec"
    assert tel["ra_rms_px"] == pytest.approx(0.4)
    assert tel["ra_rms_arcsec"] == pytest.approx(1.236)
    assert tel["last"]["ra_direction"] == "West"
    assert tel["last"]["guide_time_s"] == pytest.approx(12.5)
    assert tel["last"]["ra_distance_arcsec"] == pytest.approx(1.236)

    client._status.pixel_scale_arcsec_px = None
    tel_px = client.telemetry()
    assert tel_px["display_unit"] == "px"
    assert tel_px["ra_rms_arcsec"] is None
    assert tel_px["last"]["display_unit"] == "px"


def test_map_connection_state() -> None:
    assert _map_connection_state(online=False, app_state="Guiding", lost_star=False, paused=False) == "OFFLINE"
    assert _map_connection_state(online=True, app_state="Guiding", lost_star=False, paused=False) == "GUIDING"
    assert _map_connection_state(online=True, app_state="Looping", lost_star=False, paused=False) == "LOOPING"
    assert _map_connection_state(online=True, app_state="Paused", lost_star=False, paused=True) == "PAUSED"
    assert _map_connection_state(online=True, app_state="Guiding", lost_star=True, paused=False) == "LOST_STAR"
    # StarLost während Setup-Looping → weiter LOOPING (nicht Primärstatus LOST_STAR)
    assert _map_connection_state(online=True, app_state="Looping", lost_star=True, paused=False) == "LOOPING"


def test_stretch_and_fits_jpeg(tmp_path: Path) -> None:
    arr = np.linspace(0, 1000, 64 * 48, dtype=np.float32).reshape(48, 64)
    jpeg = _stretch_to_jpeg(arr, max_width=32)
    assert jpeg[:2] == b"\xff\xd8"
    path = tmp_path / "g.fits"
    fits.PrimaryHDU(data=arr).writeto(path)
    jpeg2 = _fits_path_to_jpeg(path, max_width=40)
    assert jpeg2[:2] == b"\xff\xd8"


def test_fits_jpeg_burns_phd_lock_header(tmp_path: Path) -> None:
    from PIL import Image
    import io

    arr = np.zeros((96, 128), dtype=np.float32)
    arr[30, 50] = 5000.0
    path = tmp_path / "lock.fits"
    hdu = fits.PrimaryHDU(data=arr)
    hdu.header["PHDLOCKX"] = 50.0
    hdu.header["PHDLOCKY"] = 30.0
    hdu.writeto(path)
    jpeg = _fits_path_to_jpeg(path, max_width=128, lock_box_px=11)
    im = Image.open(io.BytesIO(jpeg)).convert("RGB")
    px = im.getpixel((50, 30))
    # Lock-Stroke ist grün auf dem Zentrums-Kreuz
    assert px[1] > px[0] and px[1] > px[2]


def test_client_handles_events_and_rpc(monkeypatch: pytest.MonkeyPatch) -> None:
    client = Phd2Client(host="127.0.0.1", port=9)
    # inject as if connected
    client._status.connection = "CONNECTED"
    client._sock = object()  # type: ignore[assignment]
    client._handle_message({"Event": "AppState", "State": "Looping"})
    assert client.get_status().connection == "LOOPING"
    client._handle_message(
        {
            "Event": "GuideStep",
            "Frame": 3,
            "SNR": 12.5,
            "HFD": 2.2,
            "RADistanceRaw": 0.4,
            "DECDistanceRaw": -0.2,
        }
    )
    st = client.get_status()
    assert st.connection == "GUIDING"
    assert st.last_step is not None
    client._pixel_scale_stale = False
    tel = client.telemetry()
    assert tel["count"] == 1
    assert tel["display_unit"] == "px"

    # fake RPC response path
    with client._lock:
        client._pending[42] = {"event": __import__("threading").Event(), "result": None, "error": None}
    client._handle_message({"jsonrpc": "2.0", "result": "Looping", "id": 42})
    assert client._pending[42]["result"] == "Looping"
    assert client._pending[42]["event"].is_set()


def test_events_edge_triggered_no_poll_spam() -> None:
    client = Phd2Client(host="127.0.0.1", port=9)
    client._sock = object()  # type: ignore[assignment]
    client._handle_message({"Event": "AppState", "State": "Looping"})
    client._handle_message({"Event": "LoopingExposures", "Frame": 1})
    # zweites Looping ohne Zustandswechsel → kein zusätzliches LOOPING
    before = len(client.events()["events"])
    client._handle_message({"Event": "LoopingExposures", "Frame": 2})
    after = client.events()["events"]
    assert len(after) == before
    kinds = [e["kind"] for e in after]
    assert kinds.count("LOOPING") == 1


def test_star_lost_recovered_with_outage() -> None:
    client = Phd2Client(host="127.0.0.1", port=9)
    client._sock = object()  # type: ignore[assignment]
    client._pixel_scale_stale = False
    client._handle_message({"Event": "AppState", "State": "Guiding"})
    client._handle_message(
        {"Event": "GuideStep", "Frame": 1, "SNR": 50.0, "RADistanceRaw": 0.1, "DECDistanceRaw": 0.1}
    )
    client._handle_message({"Event": "StarLost"})
    client._star_lost_utc = __import__("time").time() - 4.2
    client._handle_message(
        {"Event": "GuideStep", "Frame": 2, "SNR": 48.0, "RADistanceRaw": 0.1, "DECDistanceRaw": 0.1}
    )
    kinds = [e["kind"] for e in client.events()["events"]]
    assert "STAR_LOST" in kinds
    assert "STAR_RECOVERED" in kinds
    recovered = [e for e in client.events()["events"] if e["kind"] == "STAR_RECOVERED"][-1]
    assert recovered["source"] == "derived"
    assert recovered["payload"]["outage_s"] == pytest.approx(4.2, abs=0.5)


def test_mount_alert_classified() -> None:
    assert is_mount_alert_message("PulseGuide command failed")
    assert not is_mount_alert_message("Calibration was too far from equator")
    client = Phd2Client(host="127.0.0.1", port=9)
    client._sock = object()  # type: ignore[assignment]
    client._handle_message({"Event": "Alert", "Msg": "PulseGuide command failed"})
    client._handle_message({"Event": "Alert", "Msg": "Calibration was too far from equator"})
    kinds = [e["kind"] for e in client.events()["events"]]
    assert "MOUNT_ERROR" in kinds
    assert "ALERT" in kinds


def test_calibration_available_from_api(monkeypatch: pytest.MonkeyPatch) -> None:
    client = Phd2Client(host="127.0.0.1", port=9)
    client._sock = object()  # type: ignore[assignment]

    def fake_call(method, params=None, *, timeout_s=8.0):  # noqa: ANN001, ARG001
        if method == "get_calibrated":
            return True
        if method == "get_calibration_data":
            return {
                "calibrated": True,
                "xAngle": -167.1,
                "xRate": 39.124,
                "xParity": "-",
                "yAngle": 106.1,
                "yRate": 39.33,
                "yParity": "+",
            }
        if method == "get_profile":
            return {"id": 2, "name": "NEQ6 + Guide250"}
        raise AssertionError(method)

    monkeypatch.setattr(client, "call", fake_call)
    client.refresh_calibration_and_profile()
    st = client.get_status()
    assert st.calibration_state == "AVAILABLE"
    assert st.phd2_profile_name == "NEQ6 + Guide250"
    assert st.phd2_profile_id == 2
    assert st.cal_x_angle == pytest.approx(-167.1)
    assert st.cal_y_parity == "+"


def test_calibration_none_when_uncalibrated(monkeypatch: pytest.MonkeyPatch) -> None:
    client = Phd2Client(host="127.0.0.1", port=9)
    client._sock = object()  # type: ignore[assignment]

    def fake_call(method, params=None, *, timeout_s=8.0):  # noqa: ANN001, ARG001
        if method == "get_calibrated":
            return False
        if method == "get_calibration_data":
            return {"calibrated": False}
        if method == "get_profile":
            return {"id": 1, "name": "temp"}
        raise AssertionError(method)

    monkeypatch.setattr(client, "call", fake_call)
    client.refresh_calibration_and_profile()
    st = client.get_status()
    assert st.calibration_state == "NONE"
    assert st.cal_x_angle is None
    assert st.cal_x_parity == ""


def test_star_selected_sets_lock_position() -> None:
    client = Phd2Client(host="127.0.0.1", port=9)
    client._sock = object()  # type: ignore[assignment]
    client._handle_message({"Event": "StarSelected", "X": 100.5, "Y": 200.25})
    st = client.get_status()
    assert st.star_selected is True
    assert st.lock_x == pytest.approx(100.5)
    assert st.lock_y == pytest.approx(200.25)


def test_auto_image_prefers_full_when_lost_star(monkeypatch: pytest.MonkeyPatch) -> None:
    client = Phd2Client()
    client._status.guiding = False
    client._status.looping = True
    client._status.star_selected = True
    client._status.lost_star = True
    client._status.connection = "LOOPING"
    client._status.app_state = "Looping"
    calls: list[str] = []

    def fake_full(*, max_width: int) -> bytes:  # noqa: ARG001
        calls.append("full")
        return b"\xff\xd8full"

    def fake_star(*, star_size: int) -> bytes:  # noqa: ARG001
        calls.append("star")
        return b"\xff\xd8star"

    monkeypatch.setattr(client, "_fullframe_jpeg", fake_full)
    monkeypatch.setattr(client, "_star_jpeg", fake_star)
    jpeg, meta = client.guide_image_jpeg(kind="auto")
    assert jpeg.endswith(b"full")
    assert meta["kind"] == "full"
    assert calls == ["full"]


def test_star_image_decode_roundtrip(monkeypatch: pytest.MonkeyPatch) -> None:
    client = Phd2Client()
    h, w = 16, 16
    raw = np.full((h, w), 1000, dtype="<u2")
    raw[8, 8] = 5000
    b64 = base64.b64encode(raw.tobytes()).decode("ascii")

    def fake_call(method, params=None, *, timeout_s=8.0):  # noqa: ANN001
        assert method == "get_star_image"
        return {"width": w, "height": h, "pixels": b64, "frame": 1}

    monkeypatch.setattr(client, "call", fake_call)
    jpeg = client._star_jpeg(star_size=16)
    assert jpeg[:2] == b"\xff\xd8"
