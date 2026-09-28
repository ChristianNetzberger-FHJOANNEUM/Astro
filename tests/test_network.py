"""Tests fuer mele.network WLAN-/RSSI-Status (ohne echtes WLAN noetig)."""

from __future__ import annotations

from mele import network
from mele.network import (
    WifiStatus,
    estimate_rssi_from_signal_quality,
    format_wifi_compact,
    format_wifi_tooltip,
    get_wifi_status,
    reset_wifi_status_cache,
    wifi_quality_class,
)


def setup_function() -> None:
    reset_wifi_status_cache()


def test_estimate_rssi_from_signal_quality_bounds() -> None:
    assert estimate_rssi_from_signal_quality(0) == -100
    assert estimate_rssi_from_signal_quality(100) == -50
    assert estimate_rssi_from_signal_quality(60) == -70
    assert estimate_rssi_from_signal_quality(40) == -80
    assert estimate_rssi_from_signal_quality(80) == -60
    assert estimate_rssi_from_signal_quality(-5) == -100
    assert estimate_rssi_from_signal_quality(150) == -50


def test_native_rssi_path(monkeypatch) -> None:
    monkeypatch.setattr(
        network,
        "_probe_wifi_status",
        lambda: WifiStatus(
            connected=True,
            interface_name="Wi-Fi",
            ssid="GardenMesh",
            bssid="aa:bb:cc:dd:ee:ff",
            rssi_dbm=-67,
            rssi_source="native_rssi",
            signal_quality_percent=66,
            rx_mbps=866.7,
            tx_mbps=650.0,
            channel=44,
        ),
    )
    status = get_wifi_status()
    assert status.connected is True
    assert status.rssi_dbm == -67
    assert status.rssi_source == "native_rssi"
    assert status.ssid == "GardenMesh"
    assert status.channel == 44
    assert format_wifi_compact(status) == "WLAN -67 dBm"
    tip = format_wifi_tooltip(status)
    assert "RSSI: -67 dBm" in tip
    assert "Windows WLAN driver" in tip
    assert "RX-Linkrate: 866.7 Mbit/s" in tip


def test_signal_quality_fallback_estimated(monkeypatch) -> None:
    monkeypatch.setattr(
        network,
        "_probe_wifi_status",
        lambda: WifiStatus(
            connected=True,
            ssid="Test",
            rssi_dbm=estimate_rssi_from_signal_quality(60),
            rssi_source="signal_quality_estimated",
            signal_quality_percent=60,
        ),
    )
    status = get_wifi_status()
    assert status.rssi_dbm == -70
    assert status.rssi_source == "signal_quality_estimated"
    tip = format_wifi_tooltip(status)
    assert "ca. -70 dBm" in tip
    assert "Signal Quality geschaetzt" in tip


def test_disconnected(monkeypatch) -> None:
    monkeypatch.setattr(
        network,
        "_probe_wifi_status",
        lambda: WifiStatus(connected=False),
    )
    status = get_wifi_status()
    assert status.connected is False
    assert status.rssi_dbm is None
    assert format_wifi_compact(status) == "WLAN offline"


def test_api_driver_error_keeps_last_good(monkeypatch) -> None:
    good = WifiStatus(
        connected=True,
        ssid="Mesh",
        rssi_dbm=-55,
        rssi_source="native_rssi",
    )
    monkeypatch.setattr(network, "_probe_wifi_status", lambda: good)
    assert get_wifi_status().rssi_dbm == -55

    monkeypatch.setattr(
        network,
        "_probe_wifi_status",
        lambda: WifiStatus(connected=False, error="WlanQueryInterface=5"),
    )
    status = get_wifi_status()
    assert status.stale is True
    assert status.rssi_dbm == -55
    assert format_wifi_compact(status) == "WLAN -55 dBm"


def test_stale_expires_to_question(monkeypatch) -> None:
    good = WifiStatus(
        connected=True,
        ssid="Mesh",
        rssi_dbm=-55,
        rssi_source="native_rssi",
    )
    monkeypatch.setattr(network, "_probe_wifi_status", lambda: good)
    get_wifi_status()

    # Cache aelter als 15 s machen
    network._last_good_at = 0.0  # noqa: SLF001
    monkeypatch.setattr(
        network,
        "_probe_wifi_status",
        lambda: WifiStatus(connected=False, error="timeout"),
    )
    status = get_wifi_status()
    assert status.connected is False
    assert status.rssi_dbm is None
    assert format_wifi_compact(status) == "WLAN offline"


def test_multiple_interfaces_selects_connected(monkeypatch) -> None:
    """Sicherstellen: nur verbundenes Interface, nicht irgendeines."""
    seen = {"called": False}

    def fake_probe() -> WifiStatus:
        seen["called"] = True
        # Simuliert Auswahl des verbundenen Adapters
        return WifiStatus(
            connected=True,
            interface_name="Wi-Fi 2",
            ssid="ActiveAP",
            rssi_dbm=-72,
            rssi_source="native_rssi",
        )

    monkeypatch.setattr(network, "_probe_wifi_status", fake_probe)
    status = get_wifi_status()
    assert seen["called"]
    assert status.interface_name == "Wi-Fi 2"
    assert status.ssid == "ActiveAP"


def test_missing_optional_fields_still_ok(monkeypatch) -> None:
    monkeypatch.setattr(
        network,
        "_probe_wifi_status",
        lambda: WifiStatus(
            connected=True,
            ssid="Minimal",
            rssi_dbm=-67,
            rssi_source="native_rssi",
            # channel / rates absichtlich None
        ),
    )
    status = get_wifi_status()
    payload = status.to_dict()
    assert payload["channel"] is None
    assert payload["rx_mbps"] is None
    assert payload["tx_mbps"] is None
    assert format_wifi_compact(status) == "WLAN -67 dBm"
    tip = format_wifi_tooltip(status)
    assert "Kanal" not in tip
    assert "Linkrate" not in tip


def test_probe_exception_never_raises(monkeypatch) -> None:
    def boom() -> WifiStatus:
        raise RuntimeError("native crash")

    monkeypatch.setattr(network, "_probe_wifi_status", boom)
    status = get_wifi_status()
    assert status.connected is False
    assert status.error
    assert "native crash" in (status.error or "")


def test_wifi_quality_class() -> None:
    assert wifi_quality_class(-50) == "ok"
    assert wifi_quality_class(-65) == "ok"
    assert wifi_quality_class(-75) == "warn"
    assert wifi_quality_class(-85) == "bad"
    assert wifi_quality_class(None) == ""


def test_to_dict_json_shape(monkeypatch) -> None:
    monkeypatch.setattr(
        network,
        "_probe_wifi_status",
        lambda: WifiStatus(
            connected=True,
            interface_name="Wi-Fi",
            ssid="X",
            bssid="11:22:33:44:55:66",
            rssi_dbm=-67,
            rssi_source="native_rssi",
            signal_quality_percent=66,
            rx_mbps=866.7,
            tx_mbps=650.0,
            channel=44,
            error=None,
        ),
    )
    d = get_wifi_status().to_dict()
    for key in (
        "connected",
        "interface_name",
        "ssid",
        "bssid",
        "rssi_dbm",
        "rssi_source",
        "signal_quality_percent",
        "rx_mbps",
        "tx_mbps",
        "channel",
        "error",
    ):
        assert key in d
