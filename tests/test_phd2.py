"""Unit-Tests PHD2 Launch / Client / Image helpers."""

from __future__ import annotations

import base64
from pathlib import Path

import numpy as np
import pytest
from astropy.io import fits

from mele.phd2 import Phd2Client, _fits_path_to_jpeg, _map_connection_state, _stretch_to_jpeg
from mele.phd2_launch import resolve_phd2_exe


def test_resolve_phd2_exe_configured(tmp_path: Path) -> None:
    exe = tmp_path / "phd2.exe"
    exe.write_bytes(b"x")
    assert resolve_phd2_exe(exe) == exe
    assert resolve_phd2_exe(tmp_path).name == "phd2.exe"


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
    tel = client.telemetry()
    assert tel["count"] == 1

    # fake RPC response path
    with client._lock:
        client._pending[42] = {"event": __import__("threading").Event(), "result": None, "error": None}
    client._handle_message({"jsonrpc": "2.0", "result": "Looping", "id": 42})
    assert client._pending[42]["result"] == "Looping"
    assert client._pending[42]["event"].is_set()


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
