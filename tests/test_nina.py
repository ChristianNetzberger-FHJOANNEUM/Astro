"""Tests fuer NINA Advanced API Mount-Telemetrie + GoTo/Abort."""

from __future__ import annotations

import json
from pathlib import Path
from urllib.error import URLError

import pytest

from mele.nina import (
    NinaClient,
    parse_command_payload,
    parse_mount_payload,
    validate_slew_radec_deg,
)


FIXTURE = Path(__file__).parent / "fixtures" / "nina" / "mount-info-connected.json"


class _FakeResponse:
    def __init__(self, payload: dict, status: int = 200) -> None:
        self._raw = json.dumps(payload).encode("utf-8")
        self.status = status

    def read(self) -> bytes:
        return self._raw

    def __enter__(self) -> "_FakeResponse":
        return self

    def __exit__(self, *_args) -> None:
        return None


def test_parse_live_connected_fixture() -> None:
    payload = json.loads(FIXTURE.read_text(encoding="utf-8"))
    status = parse_mount_payload(payload)
    assert status.api_online is True
    assert status.error == ""
    assert status.mount is not None
    mount = status.mount
    assert mount.connected is True
    assert mount.right_ascension_hours == pytest.approx(16.8137956172)
    assert mount.declination_deg == pytest.approx(36.4076706144)
    assert mount.altitude_deg == pytest.approx(24.233759356)
    assert mount.azimuth_deg == pytest.approx(298.276234533)
    assert mount.side_of_pier == "East"
    assert mount.slewing is False
    assert mount.tracking_enabled is True
    assert mount.tracking_mode == "Sidereal"
    assert mount.equatorial_system == "JNOW"
    assert mount.driver_name == "SynScan App Driver"
    assert mount.device_id == "ASCOM.SynScanMobile.Telescope"
    assert mount.right_ascension_string == "16:48:50"
    assert "36" in mount.declination_string
    assert mount.at_park is False


def test_parse_success_false() -> None:
    status = parse_mount_payload(
        {"Response": None, "Error": "Mount offline", "StatusCode": 500, "Success": False, "Type": "API"}
    )
    assert status.api_online is True
    assert status.mount is None
    assert "Mount offline" in status.error


def test_parse_disconnected_mount() -> None:
    status = parse_mount_payload(
        {
            "Response": {"Connected": False, "Name": "SynScan App Driver"},
            "Error": "",
            "StatusCode": 200,
            "Success": True,
            "Type": "API",
        }
    )
    assert status.api_online is True
    assert status.mount is not None
    assert status.mount.connected is False
    assert status.mount.driver_name == "SynScan App Driver"


def test_parse_nan_and_unknown_pier() -> None:
    status = parse_mount_payload(
        {
            "Response": {
                "Connected": True,
                "RightAscension": "NaN",
                "Declination": float("nan"),
                "Altitude": 10,
                "Azimuth": 20,
                "SideOfPier": "pierUnknown",
            },
            "Success": True,
        }
    )
    assert status.mount is not None
    assert status.mount.right_ascension_hours is None
    assert status.mount.declination_deg is None
    assert status.mount.altitude_deg == 10
    assert status.mount.side_of_pier == "Unknown"


def test_client_offline(monkeypatch: pytest.MonkeyPatch) -> None:
    def boom(*_args, **_kwargs):
        raise URLError("refused")

    monkeypatch.setattr("mele.nina.urlopen", boom)
    status = NinaClient("http://localhost:9/v2/api", timeout_s=0.2).get_mount_info()
    assert status.api_online is False
    assert status.mount is None
    assert "nicht erreichbar" in status.error


def test_client_live_readonly_if_available() -> None:
    status = NinaClient(timeout_s=2.0).get_mount_info()
    if not status.api_online:
        pytest.skip(f"NINA offline: {status.error}")
    assert status.mount is not None
    assert isinstance(status.mount.connected, bool)


def test_validate_slew_radec() -> None:
    assert validate_slew_radec_deg(252.2, 36.4) == ""
    assert validate_slew_radec_deg(400, 10) != ""
    assert validate_slew_radec_deg(10, 95) != ""
    assert validate_slew_radec_deg(float("nan"), 10) != ""


def test_slew_builds_official_query_degrees_j2000(monkeypatch: pytest.MonkeyPatch) -> None:
    captured: dict[str, str] = {}

    def fake_urlopen(request, timeout=None):
        captured["url"] = request.full_url
        captured["timeout"] = str(timeout)
        return _FakeResponse(
            {"Response": "Slew started", "Error": "", "StatusCode": 200, "Success": True, "Type": "API"}
        )

    monkeypatch.setattr("mele.nina.urlopen", fake_urlopen)
    # RA in Grad wie selected.ra — KEINE Stunden-Umrechnung (Angle.ByDegree in Mount.cs)
    result = NinaClient("http://localhost:1888/v2/api").slew_to_radec(
        252.206934258, 36.4076706144, wait_for_result=False
    )
    assert result.ok is True
    assert result.message == "Slew started"
    assert "/equipment/mount/slew?" in captured["url"]
    assert "ra=252.206934258" in captured["url"]
    assert "dec=36.4076706144" in captured["url"]
    assert "waitForResult=false" in captured["url"]
    assert "center=false" in captured["url"]
    assert "rotate=false" in captured["url"]
    assert result.request is not None
    assert result.request["epoch"] == "J2000"
    assert result.request["ra_unit"] == "degree"


def test_slew_rejects_bad_coords_without_http(monkeypatch: pytest.MonkeyPatch) -> None:
    def boom(*_args, **_kwargs):
        raise AssertionError("kein HTTP bei ungueltigen Koordinaten")

    monkeypatch.setattr("mele.nina.urlopen", boom)
    result = NinaClient().slew_to_radec(10, 120)
    assert result.ok is False
    assert "Dec" in result.error


def test_abort_slew_route(monkeypatch: pytest.MonkeyPatch) -> None:
    captured: dict[str, str] = {}

    def fake_urlopen(request, timeout=None):
        captured["url"] = request.full_url
        return _FakeResponse(
            {"Response": "Stopped slew", "Error": "", "StatusCode": 200, "Success": True, "Type": "API"}
        )

    monkeypatch.setattr("mele.nina.urlopen", fake_urlopen)
    result = NinaClient().abort_slew()
    assert result.ok is True
    assert captured["url"].endswith("/equipment/mount/slew/stop")
    assert result.message == "Stopped slew"


def test_parse_command_mount_not_connected() -> None:
    result = parse_command_payload(
        {"Response": None, "Error": "Mount not connected", "StatusCode": 409, "Success": False, "Type": "API"}
    )
    assert result.ok is False
    assert result.status_code == 409
    assert "not connected" in result.error


def test_parse_camera_connected() -> None:
    from mele.nina import parse_camera_payload

    status = parse_camera_payload(
        {
            "Response": {
                "Connected": True,
                "Name": "ASI585MC Pro",
                "DeviceId": "ASCOM.ASICamera2.Camera",
                "Gain": 100,
                "GainMin": 0,
                "GainMax": 510,
                "IsExposing": False,
                "CameraState": "Idle",
                "LastDownloadTime": 2.45,
                "Temperature": -5.2,
                "CoolerOn": True,
                "CanSetGain": True,
                "XBinning": 1,
                "YBinning": 1,
            },
            "Success": True,
            "StatusCode": 200,
        }
    )
    assert status.api_online is True
    assert status.camera is not None
    assert status.camera.connected is True
    assert status.camera.name == "ASI585MC Pro"
    assert status.camera.gain == 100
    assert status.camera.bin_x == 1
    assert status.camera.cooler_on is True
    assert status.camera.camera_state == "Idle"
    assert status.camera.last_download_time_s == 2.45


def test_capture_builds_query(monkeypatch: pytest.MonkeyPatch) -> None:
    calls: list[tuple[str, dict | None, float | None]] = []

    def fake_get(self, path, params=None, *, timeout_s=None):  # noqa: ANN001
        del self
        calls.append((path, params, timeout_s))
        return 200, {"Success": True, "Response": "Capture finished", "StatusCode": 200, "Error": ""}, ""

    monkeypatch.setattr(NinaClient, "_get", fake_get)
    result = NinaClient().capture(
        duration_s=5.0,
        gain=2.0,
        target_name="Altair",
        save=True,
        wait_for_result=False,
        only_await_capture_completion=True,
        skip_auto_stretch=True,
    )
    assert result.ok is True
    assert calls[0][0] == "/equipment/camera/capture"
    assert calls[0][1]["duration"] == "5"
    assert calls[0][1]["gain"] == "2"
    assert calls[0][1]["targetName"] == "Altair"
    assert calls[0][1]["save"] == "true"
    assert calls[0][1]["waitForResult"] == "false"
    assert calls[0][1]["onlyAwaitCaptureCompletion"] == "true"
    assert calls[0][1]["skipAutoStretch"] == "true"
    # onlyAwait hält HTTP offen → Timeout muss Belichtung überstehen (nicht 3s Default)
    assert calls[0][2] is not None and calls[0][2] >= 5.0 + 180.0


def test_set_image_file_path(monkeypatch: pytest.MonkeyPatch) -> None:
    calls: list[tuple[str, dict | None]] = []

    def fake_get(self, path, params=None, *, timeout_s=None):  # noqa: ANN001
        del self, timeout_s
        calls.append((path, params))
        return 200, {"Success": True, "Response": "Updated setting", "StatusCode": 200, "Error": ""}, ""

    monkeypatch.setattr(NinaClient, "_get", fake_get)
    result = NinaClient().set_image_file_path(r"C:\Astro\Capture\Mele\Altair\2026-10-02")
    assert result.ok is True
    assert calls[0][0] == "/profile/change-value"
    assert calls[0][1]["settingpath"] == "ImageFileSettings-FilePath"
    assert calls[0][1]["newValue"] == r"C:\Astro\Capture\Mele\Altair\2026-10-02"


def test_sync_snapshot_controls(monkeypatch: pytest.MonkeyPatch) -> None:
    calls: list[tuple[str, dict | None]] = []

    def fake_get(self, path, params=None, *, timeout_s=None):  # noqa: ANN001
        del self, timeout_s
        calls.append((path, params))
        return 200, {"Success": True, "Response": "Updated setting", "StatusCode": 200, "Error": ""}, ""

    monkeypatch.setattr(NinaClient, "_get", fake_get)
    results = NinaClient().sync_snapshot_controls(exposure_s=6.0, gain=2.0)
    assert results["exposure"].ok is True
    assert results["gain"].ok is True
    assert calls[0][1]["settingpath"] == "SnapShotControlSettings-ExposureDuration"
    assert calls[0][1]["newValue"] == "6"
    assert calls[1][1]["settingpath"] == "SnapShotControlSettings-Gain"
    assert calls[1][1]["newValue"] == "2"


def test_prepare_mele_image_destination(monkeypatch: pytest.MonkeyPatch) -> None:
    calls: list[tuple[str, dict | None]] = []

    def fake_get(self, path, params=None, *, timeout_s=None):  # noqa: ANN001
        del self, timeout_s
        calls.append((path, params))
        return 200, {"Success": True, "Response": "Updated setting", "StatusCode": 200, "Error": ""}, ""

    monkeypatch.setattr(NinaClient, "_get", fake_get)
    dest = NinaClient().prepare_mele_image_destination(r"C:\Astro\Capture\Mele\Altair\2026-10-02\s00042")
    assert dest["path"].ok and dest["pattern"].ok
    assert calls[0][1]["settingpath"] == "ImageFileSettings-FilePath"
    assert calls[1][1]["settingpath"] == "ImageFileSettings-FilePattern"
    assert "TARGETNAME" not in calls[1][1]["newValue"]
    assert "DATEMINUS12" not in calls[1][1]["newValue"]
    # FilePath ist bereits …/LIGHTS — kein $$IMAGETYPE$$-Unterordner (sonst LIGHTS/LIGHT/)
    assert "IMAGETYPE" not in calls[1][1]["newValue"]
    assert "DATETIME" in calls[1][1]["newValue"]
    assert "FRAMENR" in calls[1][1]["newValue"]
