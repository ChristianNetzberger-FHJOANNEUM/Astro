"""WLAN-Status / RSSI fuer app_mele (Windows Native WiFi via ctypes).

RSSI dBm ist die vom WLAN-Adapter/Treiber gemeldete Empfangsfeld-
bzw. Empfangssignalstaerke der aktuellen WLAN-Verbindung.
Sie ist KEINE kalibrierte HF-Leistungsmessung.

Prioritaet der RSSI-Ermittlung:
  1. WlanQueryInterface(wlan_intf_opcode_rssi)  -> rssi_source=\"native_rssi\"
  2. WLAN_BSS_ENTRY.lRssi der verbundenen BSSID -> \"bss_rssi\"
  3. WLAN_SIGNAL_QUALITY (0..100 %) geschaetzt   -> \"signal_quality_estimated\"

Microsoft-Zuordnung fuer Signal Quality (geschaetzt):
  0 % -> ca. -100 dBm, 100 % -> ca. -50 dBm
  rssi_estimated_dbm = -100 + signal_quality / 2

Keine neuen Abhaengigkeiten; Handles/Speicher immer freigeben.
"""

from __future__ import annotations

import logging
import sys
import threading
import time
from dataclasses import asdict, dataclass
from typing import Any

logger = logging.getLogger(__name__)

# Windows Native WiFi constants (wlanapi.h)
_WLAN_API_VERSION = 2
_ERROR_SUCCESS = 0
_WLAN_INTERFACE_STATE_CONNECTED = 1
_WLAN_INTF_OPCODE_CURRENT_CONNECTION = 7
_WLAN_INTF_OPCODE_CHANNEL_NUMBER = 8
# MSM-Gruppe: statistics = 0x10000100, rssi = 0x10000101 — auf Win11
# liefert 0x10000102 den LONG-RSSI (verifiziert auf MeLE / Intel AC 9560).
_WLAN_INTF_OPCODE_RSSI = 0x10000102
_DOT11_BSS_TYPE_INFRASTRUCTURE = 1
_DOT11_SSID_MAX_LENGTH = 32

_STALE_AFTER_S = 15.0


@dataclass(frozen=True)
class WifiStatus:
    """Snapshot der aktuell verbundenen WLAN-Schnittstelle."""

    connected: bool
    interface_name: str | None = None
    ssid: str | None = None
    bssid: str | None = None
    rssi_dbm: int | None = None
    rssi_source: str | None = None
    signal_quality_percent: int | None = None
    rx_mbps: float | None = None
    tx_mbps: float | None = None
    channel: int | None = None
    error: str | None = None
    stale: bool = False

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


_cache_lock = threading.Lock()
_last_good: WifiStatus | None = None
_last_good_at: float = 0.0
_last_logged_key: tuple[Any, ...] | None = None


def estimate_rssi_from_signal_quality(quality_percent: int) -> int:
    """Microsoft-Dokumentation: linear 0%≈-100 dBm … 100%≈-50 dBm."""
    q = max(0, min(100, int(quality_percent)))
    return -100 + q // 2


def format_wifi_compact(status: WifiStatus) -> str:
    """Kurzer Statuszeilentext, z.B. 'WLAN -67 dBm'."""
    if status.stale and status.rssi_dbm is None:
        return "WLAN ?"
    if not status.connected:
        if status.stale and status.rssi_dbm is not None:
            return f"WLAN {status.rssi_dbm} dBm"
        return "WLAN offline"
    if status.rssi_dbm is None:
        return "WLAN ?"
    return f"WLAN {status.rssi_dbm} dBm"


def format_wifi_tooltip(status: WifiStatus) -> str:
    """Mehrzeiliger Tooltip / Detailtext."""
    lines = ["WLAN"]
    if status.interface_name:
        lines.append(f"Adapter: {status.interface_name}")
    if status.ssid:
        lines.append(f"SSID: {status.ssid}")
    if status.bssid:
        lines.append(f"BSSID: {status.bssid}")
    if status.rssi_dbm is not None:
        if status.rssi_source == "signal_quality_estimated":
            lines.append(f"RSSI: ca. {status.rssi_dbm} dBm")
            lines.append("Quelle: aus Windows Signal Quality geschaetzt")
        else:
            lines.append(f"RSSI: {status.rssi_dbm} dBm")
            if status.rssi_source == "native_rssi":
                lines.append("Quelle: Windows WLAN driver")
            elif status.rssi_source == "bss_rssi":
                lines.append("Quelle: Windows BSS-Liste (lRssi)")
            elif status.rssi_source:
                lines.append(f"Quelle: {status.rssi_source}")
    elif not status.connected:
        lines.append("Status: offline")
    if status.signal_quality_percent is not None:
        lines.append(f"Signal Quality: {status.signal_quality_percent} %")
    if status.rx_mbps is not None:
        lines.append(f"RX-Linkrate: {status.rx_mbps:g} Mbit/s")
    if status.tx_mbps is not None:
        lines.append(f"TX-Linkrate: {status.tx_mbps:g} Mbit/s")
    if status.channel is not None:
        lines.append(f"Kanal: {status.channel}")
    if status.stale:
        lines.append("(letzte Messung, veraltet)")
    if status.error:
        lines.append(f"Hinweis: {status.error}")
    return "\n".join(lines)


def wifi_quality_class(rssi_dbm: int | None) -> str:
    """UI-Hinweis: ok / warn / bad / '' (reine Betriebsindikatoren)."""
    if rssi_dbm is None:
        return ""
    if rssi_dbm >= -60:
        return "ok"
    if rssi_dbm >= -70:
        return "ok"
    if rssi_dbm >= -80:
        return "warn"
    return "bad"


def get_wifi_status() -> WifiStatus:
    """Aktuellen WLAN-Status ermitteln. Wirft niemals eine Exception.

    Bei Abfragefehler bleibt der letzte erfolgreiche Wert bis ~15 s sichtbar
    (Feld stale=True). Danach WLAN ? bzw. offline.
    """
    global _last_good, _last_good_at, _last_logged_key

    try:
        fresh = _probe_wifi_status()
    except Exception as exc:  # noqa: BLE001 — UI darf nie crashen
        fresh = WifiStatus(connected=False, error=str(exc) or "WLAN-Abfrage fehlgeschlagen")

    now = time.monotonic()
    with _cache_lock:
        usable = fresh.connected and fresh.rssi_dbm is not None
        # Auch connected ohne RSSI (selten) als Erfolg werten, wenn SSID da
        if fresh.connected and fresh.error is None:
            usable = True
        if usable:
            _last_good = fresh
            _last_good_at = now
            _log_wifi_change(fresh)
            return fresh

        # Explizit disconnected ohne Fehler -> offline, Cache nur kurz halten
        if not fresh.connected and fresh.error is None:
            age = now - _last_good_at if _last_good is not None else _STALE_AFTER_S + 1
            if _last_good is not None and age < _STALE_AFTER_S and _last_good.connected:
                stale = WifiStatus(**{**_last_good.to_dict(), "stale": True})
                return stale
            _log_wifi_change(fresh)
            return fresh

        # Fehler: letzten guten Wert kurz behalten
        age = now - _last_good_at if _last_good is not None else _STALE_AFTER_S + 1
        if _last_good is not None and age < _STALE_AFTER_S:
            stale = WifiStatus(
                **{
                    **_last_good.to_dict(),
                    "stale": True,
                    "error": fresh.error or _last_good.error,
                }
            )
            return stale
        if _last_good is not None and age >= _STALE_AFTER_S:
            _log_wifi_change(
                WifiStatus(connected=False, error=fresh.error, rssi_dbm=None)
            )
            return WifiStatus(
                connected=False,
                error=fresh.error,
                interface_name=fresh.interface_name,
            )
        _log_wifi_change(fresh)
        return fresh


def reset_wifi_status_cache() -> None:
    """Nur fuer Tests."""
    global _last_good, _last_good_at, _last_logged_key
    with _cache_lock:
        _last_good = None
        _last_good_at = 0.0
        _last_logged_key = None


def _log_wifi_change(status: WifiStatus) -> None:
    """SSID/BSSID nur bei Zustandswechsel loggen, nicht jeden Poll."""
    global _last_logged_key
    key = (
        status.connected,
        status.ssid,
        status.bssid,
        status.error,
    )
    if key == _last_logged_key:
        return
    _last_logged_key = key
    if status.error and not status.connected:
        logger.info("WLAN: Fehler/offline (%s)", status.error)
    elif not status.connected:
        logger.info("WLAN: disconnected")
    else:
        logger.info(
            "WLAN: connected ssid=%s bssid=%s rssi=%s (%s)",
            status.ssid,
            status.bssid,
            status.rssi_dbm,
            status.rssi_source,
        )


def _probe_wifi_status() -> WifiStatus:
    if sys.platform != "win32":
        return WifiStatus(connected=False, error="WLAN-Status nur unter Windows")

    try:
        return _probe_wifi_native()
    except OSError as exc:
        return WifiStatus(connected=False, error=f"wlanapi: {exc}")
    except Exception as exc:  # noqa: BLE001
        return WifiStatus(connected=False, error=str(exc) or "Native WiFi Fehler")


def _probe_wifi_native() -> WifiStatus:
    import ctypes
    from ctypes import wintypes

    wlan = ctypes.WinDLL("wlanapi")

    class GUID(ctypes.Structure):
        _fields_ = [
            ("Data1", wintypes.DWORD),
            ("Data2", wintypes.WORD),
            ("Data3", wintypes.WORD),
            ("Data4", wintypes.BYTE * 8),
        ]

    class WLAN_INTERFACE_INFO(ctypes.Structure):
        _fields_ = [
            ("InterfaceGuid", GUID),
            ("strInterfaceDescription", ctypes.c_wchar * 256),
            ("isState", wintypes.DWORD),
        ]

    class WLAN_INTERFACE_INFO_LIST(ctypes.Structure):
        _fields_ = [
            ("dwNumberOfItems", wintypes.DWORD),
            ("dwIndex", wintypes.DWORD),
            ("InterfaceInfo", WLAN_INTERFACE_INFO * 1),
        ]

    class DOT11_SSID(ctypes.Structure):
        _fields_ = [
            ("uSSIDLength", wintypes.ULONG),
            ("ucSSID", ctypes.c_ubyte * _DOT11_SSID_MAX_LENGTH),
        ]

    class WLAN_ASSOCIATION_ATTRIBUTES(ctypes.Structure):
        _fields_ = [
            ("dot11Ssid", DOT11_SSID),
            ("dot11BssType", wintypes.DWORD),
            ("dot11Bssid", ctypes.c_ubyte * 6),
            ("dot11PhyType", wintypes.DWORD),
            ("uDot11PhyIndex", wintypes.ULONG),
            ("uWLANSignalQuality", wintypes.ULONG),
            ("ulRxRate", wintypes.ULONG),
            ("ulTxRate", wintypes.ULONG),
        ]

    class WLAN_SECURITY_ATTRIBUTES(ctypes.Structure):
        _fields_ = [
            ("bSecurityEnabled", wintypes.BOOL),
            ("bOneXEnabled", wintypes.BOOL),
            ("dot11AuthAlgorithm", wintypes.DWORD),
            ("dot11CipherAlgorithm", wintypes.DWORD),
        ]

    class WLAN_CONNECTION_ATTRIBUTES(ctypes.Structure):
        _fields_ = [
            ("isState", wintypes.DWORD),
            ("wlanConnectionMode", wintypes.DWORD),
            ("strProfileName", ctypes.c_wchar * 256),
            ("wlanAssociationAttributes", WLAN_ASSOCIATION_ATTRIBUTES),
            ("wlanSecurityAttributes", WLAN_SECURITY_ATTRIBUTES),
        ]

    class WLAN_BSS_ENTRY(ctypes.Structure):
        _fields_ = [
            ("dot11Ssid", DOT11_SSID),
            ("uPhyId", wintypes.ULONG),
            ("dot11Bssid", ctypes.c_ubyte * 6),
            ("dot11BssType", wintypes.DWORD),
            ("dot11BssPhyType", wintypes.DWORD),
            ("lRssi", ctypes.c_long),
            ("uLinkQuality", wintypes.ULONG),
            ("bInRegDomain", wintypes.BOOLEAN),
            ("usBeaconPeriod", wintypes.USHORT),
            ("ullTimestamp", ctypes.c_ulonglong),
            ("ullHostTimestamp", ctypes.c_ulonglong),
            ("usCapabilityInformation", wintypes.USHORT),
            ("ulChCenterFrequency", wintypes.ULONG),
            ("wlanRateSet", ctypes.c_ubyte * 126),  # approx; we only need lRssi
            ("ulIeOffset", wintypes.ULONG),
            ("ulIeSize", wintypes.ULONG),
        ]

    class WLAN_BSS_LIST(ctypes.Structure):
        _fields_ = [
            ("dwTotalSize", wintypes.DWORD),
            ("dwNumberOfItems", wintypes.DWORD),
            ("wlanBssEntries", WLAN_BSS_ENTRY * 1),
        ]

    handle = wintypes.HANDLE()
    negotiated = wintypes.DWORD()
    rc = wlan.WlanOpenHandle(
        _WLAN_API_VERSION, None, ctypes.byref(negotiated), ctypes.byref(handle)
    )
    if rc != _ERROR_SUCCESS:
        return WifiStatus(connected=False, error=f"WlanOpenHandle={rc}")

    try:
        plist = ctypes.POINTER(WLAN_INTERFACE_INFO_LIST)()
        rc = wlan.WlanEnumInterfaces(handle, None, ctypes.byref(plist))
        if rc != _ERROR_SUCCESS:
            return WifiStatus(connected=False, error=f"WlanEnumInterfaces={rc}")
        try:
            n = int(plist.contents.dwNumberOfItems)
            if n <= 0:
                return WifiStatus(connected=False)

            arr_t = WLAN_INTERFACE_INFO * n
            base = ctypes.addressof(plist.contents) + WLAN_INTERFACE_INFO_LIST.InterfaceInfo.offset
            infos = arr_t.from_address(base)

            connected_idx = None
            for i in range(n):
                if infos[i].isState == _WLAN_INTERFACE_STATE_CONNECTED:
                    connected_idx = i
                    break
            if connected_idx is None:
                # Kein aktives WLAN (z.B. nur Ethernet) — nicht den ersten Adapter nehmen
                return WifiStatus(
                    connected=False,
                    interface_name=infos[0].strInterfaceDescription or None,
                )

            info = infos[connected_idx]
            iface_name = info.strInterfaceDescription or None
            guid = info.InterfaceGuid

            rssi_dbm: int | None = None
            rssi_source: str | None = None
            ssid: str | None = None
            bssid: str | None = None
            quality: int | None = None
            rx_mbps: float | None = None
            tx_mbps: float | None = None
            channel: int | None = None

            # 1) Direkter Treiber-RSSI
            data = ctypes.c_void_p()
            data_size = wintypes.DWORD()
            data_type = wintypes.DWORD()
            rc = wlan.WlanQueryInterface(
                handle,
                ctypes.byref(guid),
                _WLAN_INTF_OPCODE_RSSI,
                None,
                ctypes.byref(data_size),
                ctypes.byref(data),
                ctypes.byref(data_type),
            )
            if rc == _ERROR_SUCCESS and data and data_size.value >= 4:
                rssi_dbm = int(ctypes.cast(data, ctypes.POINTER(ctypes.c_long)).contents.value)
                rssi_source = "native_rssi"
                wlan.WlanFreeMemory(data)
            elif data:
                wlan.WlanFreeMemory(data)

            # Verbindungsattribute: SSID, BSSID, Quality, Linkraten
            data = ctypes.c_void_p()
            data_size = wintypes.DWORD()
            data_type = wintypes.DWORD()
            rc = wlan.WlanQueryInterface(
                handle,
                ctypes.byref(guid),
                _WLAN_INTF_OPCODE_CURRENT_CONNECTION,
                None,
                ctypes.byref(data_size),
                ctypes.byref(data),
                ctypes.byref(data_type),
            )
            if rc == _ERROR_SUCCESS and data and data_size.value >= ctypes.sizeof(WLAN_CONNECTION_ATTRIBUTES):
                conn = ctypes.cast(data, ctypes.POINTER(WLAN_CONNECTION_ATTRIBUTES)).contents
                assoc = conn.wlanAssociationAttributes
                length = int(assoc.dot11Ssid.uSSIDLength)
                if 0 < length <= _DOT11_SSID_MAX_LENGTH:
                    ssid = bytes(assoc.dot11Ssid.ucSSID[:length]).decode("utf-8", errors="replace")
                bssid = ":".join(f"{b:02x}" for b in assoc.dot11Bssid)
                quality = int(assoc.uWLANSignalQuality)
                # ulRxRate / ulTxRate: kbit/s laut MSDN
                if assoc.ulRxRate > 0:
                    rx_mbps = round(assoc.ulRxRate / 1000.0, 1)
                if assoc.ulTxRate > 0:
                    tx_mbps = round(assoc.ulTxRate / 1000.0, 1)
                wlan.WlanFreeMemory(data)
            elif data:
                wlan.WlanFreeMemory(data)

            # Kanal
            data = ctypes.c_void_p()
            data_size = wintypes.DWORD()
            data_type = wintypes.DWORD()
            rc = wlan.WlanQueryInterface(
                handle,
                ctypes.byref(guid),
                _WLAN_INTF_OPCODE_CHANNEL_NUMBER,
                None,
                ctypes.byref(data_size),
                ctypes.byref(data),
                ctypes.byref(data_type),
            )
            if rc == _ERROR_SUCCESS and data and data_size.value >= 4:
                channel = int(ctypes.cast(data, ctypes.POINTER(wintypes.ULONG)).contents.value)
                wlan.WlanFreeMemory(data)
            elif data:
                wlan.WlanFreeMemory(data)

            # 2) BSS lRssi Fallback
            if rssi_dbm is None and bssid is not None:
                bss_rssi = _query_bss_rssi(
                    wlan,
                    handle,
                    guid,
                    bssid,
                    WLAN_BSS_LIST,
                    WLAN_BSS_ENTRY,
                    DOT11_SSID,
                )
                if bss_rssi is not None:
                    rssi_dbm = bss_rssi
                    rssi_source = "bss_rssi"

            # 3) Signal-Quality-Schaetzung
            if rssi_dbm is None and quality is not None:
                rssi_dbm = estimate_rssi_from_signal_quality(quality)
                rssi_source = "signal_quality_estimated"

            return WifiStatus(
                connected=True,
                interface_name=iface_name,
                ssid=ssid,
                bssid=bssid,
                rssi_dbm=rssi_dbm,
                rssi_source=rssi_source,
                signal_quality_percent=quality,
                rx_mbps=rx_mbps,
                tx_mbps=tx_mbps,
                channel=channel,
            )
        finally:
            wlan.WlanFreeMemory(plist)
    finally:
        wlan.WlanCloseHandle(handle, None)


def _query_bss_rssi(
    wlan: Any,
    handle: Any,
    guid: Any,
    bssid: str,
    WLAN_BSS_LIST: Any,
    WLAN_BSS_ENTRY: Any,
    DOT11_SSID: Any,
) -> int | None:
    """lRssi der verbundenen BSSID aus der BSS-Liste (Fallback)."""
    import ctypes
    from ctypes import wintypes

    target = bssid.lower().replace("-", ":")
    ssid_empty = DOT11_SSID()
    ssid_empty.uSSIDLength = 0
    pbss = ctypes.c_void_p()
    rc = wlan.WlanGetNetworkBssList(
        handle,
        ctypes.byref(guid),
        ctypes.byref(ssid_empty),
        _DOT11_BSS_TYPE_INFRASTRUCTURE,
        False,
        None,
        ctypes.byref(pbss),
    )
    if rc != _ERROR_SUCCESS or not pbss:
        return None
    try:
        # Header lesen; Eintraege sind variabel gross — wir scannen per Offset
        header = ctypes.cast(pbss, ctypes.POINTER(WLAN_BSS_LIST)).contents
        count = int(header.dwNumberOfItems)
        # MSDN: wlanBssEntries[0] ist der Start; Folgeeintraege via ulIeOffset+ulIeSize
        # Praktisch: feste Stride oft sizeof(WLAN_BSS_ENTRY) unzuverlaessig wegen IE.
        # Einfacher Ansatz: erste N Eintraege mit bekanntem Layout ab Offset lesen,
        # solange BSSID match — viele Treiber liefern verbundenen AP zuerst.
        entry_addr = ctypes.addressof(header) + WLAN_BSS_LIST.wlanBssEntries.offset
        for _ in range(count):
            entry = WLAN_BSS_ENTRY.from_address(entry_addr)
            mac = ":".join(f"{b:02x}" for b in entry.dot11Bssid)
            if mac == target:
                return int(entry.lRssi)
            # Naechster Eintrag: nach IE-Block (ulIeOffset relativ zum Eintragsbeginn)
            stride = max(int(entry.ulIeOffset) + int(entry.ulIeSize), ctypes.sizeof(WLAN_BSS_ENTRY))
            # Align auf 4
            stride = (stride + 3) & ~3
            entry_addr += stride
        return None
    finally:
        wlan.WlanFreeMemory(pbss)
