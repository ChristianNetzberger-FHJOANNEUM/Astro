# MeLE Feldnetz, Reiserouter und Quest 3 (Spec)

> Quelle: Chat mit Cursor, 2026-10-09 · Thema: mobiles Astro-Netz ohne Standort-WLAN
> Stand: Architekturentscheidung. Router noch nicht beschafft, Quest noch nicht angebunden, App-Autostart noch nicht gebaut.
> Kein Implementierungsauftrag. Keine Router- oder Windows-Änderung ohne gesonderte Freigabe.

Statusworte: `IMPLEMENTIERT` (im Code), `GEPLANT` (beschlossen, nicht gebaut), `OPTIONAL`, `OFFEN` (noch zu prüfen).

Autostart und DEV/PROD stehen in [MeLE Autostart und Entwicklungsbetrieb](mele-autostart-dev-prod-spec.md). Capture, WORK und ARCHIVE in [Session Storage](mele-session-storage-weather-archive-spec.md). Was heute von selbst startet: [MeLE-PC Autostart](mele-pc-autostart.md).

## Ziel

Das System soll an einem Beobachtungsort ohne fremdes WLAN und ohne Internet laufen.

Zielablauf, noch nicht der Ist-Zustand:

1. Ausrüstung aufbauen.
2. MeLE und Reiserouter einschalten.
3. Windows startet die vorgesehenen Programme (`GEPLANT`, siehe Autostart-Spec; heute startet nur der weather_server).
4. iPad ins Astro-WLAN.
5. Bestehende Oberfläche im Browser: `http://<mele>:8082/`.
6. Montierung, Kamera und Guider initialisieren.
7. Alignment, GoTo, Guiding und Capture über diese Oberfläche.

Die Meta Quest 3 ist ein zusätzlicher Client derselben App, keine zweite Steuerung. Das Samsung Galaxy S22 ist ein optionales Mobilfunk-Gateway. Alle wesentlichen Astro-Funktionen müssen ohne Internet gehen.

## Abgleich mit dem Ist-Stand

Zwei Formulierungen aus der Planung gelten so nicht:

1. Die Voreinstellung bleibt `reload=False`. Reload ist kein Produktivverhalten und keine YAML-Option, sondern nur das Startargument `--reload`. Maßgeblich bleibt die Autostart-Spec.
2. Ein GeoSphere-Abruf bei fehlendem Netz ist bereits gebaut. `mele/weather.py` liest den Cache, setzt `fetched_at`, `offline` und `stale` (älter als 3 Stunden). Fehlt jeder Cache, gibt es noch keine Prognose.

Weitere Korrekturen gegenüber dem Planungstext:

- Die Beispieladressen `192.168.50.0/24` sind das **Feldnetz**. Das Hausnetz bleibt getrennt: NAS `archive_root` ist `//192.168.0.100/Media/Astro/Mele`, WORK läuft über Tailscale `//100.97.226.18/Astro/Work/Mele` (`configs/mele.yaml`). Diese Einträge nicht auf die Router-IP umschreiben. Beim Wechsel Haus/Feld wird `configs/mele.yaml` nicht von Hand umgeschrieben. Die App bindet auf `0.0.0.0:8082` und ist in dem LAN erreichbar, in dem der MeLE gerade steckt. WORK und ARCHIVE bleiben die Haus-Pfade und dürfen unerreichbar sein.
- „Windows startet automatisch NINA, SynScan und PHD2“ ist Phase B der Autostart-Spec, nicht der heutige Boot.
- iPad und weitere Browser können die NiceGUI-App schon gleichzeitig öffnen. Eine Sperre gegen widersprüchliche Gerätebefehle gibt es nicht. Langfristig koordiniert das Backend nur kritische Aktionen (GoTo, Guiding-Start, Capture-Steuerung). Wetter, Kamerabilder und Objektinfos bleiben für alle Clients gleichzeitig lesbar. Das ist `OFFEN` und kommt nicht vor dem Quest-Browsertest.

## Komponenten und Status

| Thema | Status | Wo es liegt |
|---|---|---|
| MeLE-App, Port 8082, `ui_host: 0.0.0.0` | `IMPLEMENTIERT` | `configs/mele.yaml`, `app_mele` |
| NINA-API `http://localhost:1888/v2/api` | `IMPLEMENTIERT` | `mele/nina.py`, Starter `mele/nina_launch.py` |
| PHD2 Event-Server Port 4400 | `IMPLEMENTIERT` | `mele/phd2.py`, Starter `mele/phd2_launch.py` |
| SynScan Pro, nur Prozessstart | `IMPLEMENTIERT` | `mele/synscan.py` |
| weather_server Port 8765, eigener Task | `IMPLEMENTIERT` | `Astro-weather_server`, Ecowitt/GW1200 |
| GeoSphere Austria NWP v2, Cache, Offline-Flag | `IMPLEMENTIERT` | `mele/weather.py`, Wetterfenster |
| Lokale Station, Safety `LIVE/STALE/OFFLINE` | `IMPLEMENTIERT` | `mele/weather_safety.py`, Pull von Port 8765 |
| Capture lokal `C:/Astro/Capture/Mele` | `IMPLEMENTIERT` | `local_capture_root` |
| WORK- und ARCHIVE-Pfade konfiguriert | `IMPLEMENTIERT` als Pfade | Transferablauf: Session-Storage-Spec |
| Tailscale-Dienst automatisch | `IMPLEMENTIERT` | optional fürs Feld |
| Schlanker Bootstrap, DEV/PROD | `GEPLANT` | Autostart-Spec, Task noch nicht angelegt |
| GL.iNet GL-MT3000 Beryl AX | `AUSGEWÄHLT`, Kauf und Inbetriebnahme `OFFEN` | diese Seite |
| Feld-WLAN, DHCP, SSIDs | `GEPLANT` | diese Seite |
| S22 als Internet-Gateway | `OPTIONAL` / `GEPLANT` | diese Seite |
| Quest 3 | `GEPLANT` | diese Seite |
| HTTPS / WebXR Port 8443 | `GEPLANT`, nicht vorhanden | diese Seite |
| Mehrclient: Lesen gemeinsam, kritische Befehle später koordiniert | `OFFEN` | diese Seite |

Gerätenamen aus der Planung (MeLE Quieter 4C, AZ-GTi, NEQ5/NEQ6, Quest 3, Galaxy S22) sind hier Architekturrollen, keine Inventar-Einträge. Das Inventar bleibt `wiki/inventar/hardware.md`.

## ADR-NET-001 — Beryl AX als mobiler Router

`AUSGEWÄHLT / KAUF GEPLANT`. Preis bei der Auswahl am 2026-10-09: ca. 102,85 €. Bestellung und Firmwarestand sind `OFFEN`.

GL.iNet GL-MT3000 (Beryl AX): Wi-Fi 6, Dualband, 2,4 GHz bis 574 Mbit/s und 5 GHz bis 2402 Mbit/s (theoretisch), WAN 2,5-Gbit/s-Ethernet, LAN 1-Gbit/s-Ethernet, USB 3.0 Typ A, Versorgung USB-C 5 V / 3 A, Firmware auf OpenWrt-Basis. Uplink über Ethernet, WLAN-Repeater oder USB-Tethering. Kein zweiter Internetrouter. Wi-Fi 7 und 6 GHz sind nicht erforderlich.

Begründung: beide Bänder gleichzeitig, 2,4 GHz für ältere Adapter, 5 GHz für iPad und Quest, Ethernet zum MeLE, Betrieb ohne Internet, S22 als optionales Gateway, kompakt.

## ADR-NET-002 — Wer hängt woran

`GEPLANT`. Ein LAN für Ethernet und beide WLAN-Bänder. Keine Client-Isolation zwischen WLAN und Ethernet.

```text
Mobilfunk (nur wenn S22 als Gateway an ist)
        |
   Galaxy S22
        |  USB-Tethering oder WLAN-Hotspot
        v
   Beryl AX  192.168.50.1  (Vorschlag)
     |            |              |
  Ethernet      2,4 GHz         5 GHz
     |            |              |
    MeLE       AZ-GTi         iPad
  .50.10                    Quest 3
```

| Gerät | Verbindung | Rolle |
|---|---|---|
| MeLE | Ethernet, LAN-Port des Routers | Astro-Computer, App Port 8082 |
| AZ-GTi | 2,4-GHz-WLAN, Station-Modus | Montierung |
| NEQ5 / NEQ6 | USB/seriell oder eigener WLAN-Adapter | kein eingebautes WLAN; Adapter `OFFEN` |
| iPad | 5 GHz bevorzugt | Hauptbedienung |
| Quest 3 | 5 GHz | zusätzliches Frontend |
| Galaxy S22 | USB-Tethering oder Hotspot zum Router | optionales Gateway, nicht zwingend Client im Astro-WLAN |

Das MeLE-WLAN wird im Feld nicht gebraucht und kann aus bleiben (`OPTIONAL`, nicht voreingestellt).

Beispiel, erst bei der Einrichtung festzulegen:

| Parameter | Vorschlag |
|---|---|
| Router | 192.168.50.1 |
| MeLE | 192.168.50.10, DHCP-Reservierung |
| Subnetz | 192.168.50.0/24 |
| WLAN 2,4 GHz | ASTRO-24 |
| WLAN 5 GHz | ASTRO-5G |
| Oberfläche | http://192.168.50.10:8082/ |

2,4 GHz: WPA2-Personal/AES, kein WPA3-Zwang. Bei Verbindungsproblemen Kanäle 1, 6 oder 11. AZ-GTi-Station-Modus nach Stromausfall prüfen.

5 GHz: fester Kanal, wenn der Automatikwechsel stört. Fürs Feld möglichst kein DFS-Kanal. Stabilität und Latenz vor maximaler Kanalbreite.

## ADR-NET-003 — S22 als optionales Gateway

`OPTIONAL`. Internet ist keine Startbedingung. Fällt Mobilfunk, Tethering oder das S22 aus, bleiben App, NINA, SynScan, PHD2, GoTo, Guiding, Capture und der lokale weather_server auf ihren Adressen. GeoSphere zeigt den Cache mit `offline` bzw. `stale`. Die Feld-IPs ändern sich dadurch nicht.

Variante A, WLAN-Hotspot des S22 als Repeater-Uplink des Beryl: ohne Kabel, genug für GeoSphere. Zusätzliches Funkfeld, bei VR-Last ungünstiger.

Variante B, USB-Tethering an den USB-3.0-Port des Routers: kein WLAN-Uplink, für Quest-Last vorgezogen. Ob das S22 dabei geladen wird, ist `OFFEN`.

Das Gateway startet keine RAW-Transfers. WORK und ARCHIVE bleiben die bestehenden Pfade und sind für App-Start und Capture nicht nötig.

## ADR-NET-004 — Offline

`IMPLEMENTIERT` für den heutigen Funktionskern, `GEPLANT` für das Feldnetz drumherum.

Ohne Internet müssen Bedienung, NINA, SynScan, PHD2, lokale Aufnahme und lokale Wetterstation gehen. GeoSphere ist Komfort und degradiert auf den Cache (`mele/weather.py`). Der weather_server bleibt der eigene Task auf Port 8765; kein zweiter GeoSphere- oder Ecowitt-Client im Bootstrap.

```text
Ecowitt / GW1200 --> weather_server :8765 --> mele_app
GeoSphere NWP ----> Cache data/weather/ ----> mele_app
                         ^
                    nur bei Netz: S22 --> Beryl --> MeLE
```

## ADR-VR-001 — Quest als weiterer Browser-Client

`GEPLANT`. Keine eigene NINA-, SynScan- oder PHD2-Instanz. Alle Befehle laufen über die MeLE-App.

Phase Q1: Quest-Browser öffnet `http://<mele-ip>:8082/`. Bestehende Oberfläche, nur Anzeige und Bedienprobe. Kein Umbau der Steuerung.

Phase Q2, immersiver 360°-Viewer: WebXR über vorhandene Panorama-/Horizontdaten, Katalog, RA/Dec, Azimut/Höhe und Sichtfeld. GoTo-Schnittstellen zunächst nur lesend. In `app_mele/layout.py` steht dazu nur der Hinweis auf eine spätere Quest-Skybox; eine WebXR-Ansicht gibt es nicht.

Die Quest liefert die Kopfpose relativ zu ihrem XR-Raum, nicht als astronomisches Azimut. Eine Nordkalibrierung ist `OFFEN` und vor Q2 zu definieren.

Phase Q3, `OPTIONAL`: Objekt wählen, Infos, GoTo nur nach ausdrücklicher Bestätigung, Gesichtsfeld, Kameravorschau, Aufnahmestatus und Wetter im Raum. Weiterhin keine Geräteclients in der Quest.

## ADR-VR-002 — WebXR getrennt von der heutigen App

`GEPLANT`. Die normale Oberfläche bleibt HTTP auf Port 8082. Immersives WebXR braucht in der Regel einen sicheren Ursprung. Vorgeschlagene spätere Adresse, nicht implementiert: `https://<mele-host>:8443/vr/`.

Ein selbstsigniertes Zertifikat ohne Vertrauen auf der Quest reicht nicht. Ein lokaler Reverse-Proxy ist eine mögliche Lösung. Die NiceGUI-App wird nicht wegen WebXR umgebaut. Zertifikatsweg ist `OFFEN`.

Mehrere Bediengeräte (iPad, PC, später Quest) dürfen gleichzeitig lesen: Wetter, Kamerabilder, Objektinfos. Kritische Aktionen — GoTo, Guiding-Start, Capture-Steuerung — bekommen später eine zentrale Koordination im bestehenden Backend (`OFFEN`). Nicht jede Funktion wird gesperrt. Q1 bleibt die bestehende Oberfläche im Quest-Browser, ohne diese Koordination.

## ADR-BOOT-001 und ADR-DEV-001

Nicht hier wiederholen. Verbindlich: [MeLE Autostart und Entwicklungsbetrieb](mele-autostart-dev-prod-spec.md).

Kurz: Bootstrap bei interaktiver Anmeldung von `Chris`, App zuerst auf 8082, danach die vorhandenen Starter, kein Watchdog, keine eigene Zustandslogik, weather_server bleibt draußen, keine automatische Belichtung, kein Guiding, kein Alignment, kein GoTo. DEV und PROD teilen sich Port 8082 nacheinander. Produktiv ohne `--reload`. Keine zweite Instanz.

## Reihenfolge

1. Autostart Phase A, einschließlich DEV/PROD-Umschaltung.
2. Phase B: SynScan, NINA, PHD2 über die vorhandenen Starter.
3. Feldnetz, sobald der Beryl AX da ist. Unabhängig von Phase A und B. Kein Umschreiben von `configs/mele.yaml`.
4. Quest 3 zuerst als normaler Browser auf Port 8082. WebXR erst danach.
5. Mehrclient-Koordination für GoTo, Guiding-Start und Capture, bevor eine Quest diese Aktionen auslöst.

GeoSphere bleibt wie implementiert. Kein weiterer Entwicklungsauftrag dafür.

## Offene Prüfungen

- Beryl AX beschaffen, Firmwarestand notieren, beide SSIDs, Ethernet zum MeLE, DHCP-Reservierung.
- AZ-GTi im Station-Modus, auch nach Stromverlust. SynScan-Pro über die Grenze Ethernet zu 2,4 GHz.
- NEQ5/NEQ6 je nach Adapter.
- S22: Hotspot-Uplink, USB-Tethering, Verhalten bei Mobilfunkverlust, keine IP-Änderung.
- Quest-Browser gegen Port 8082. Danach erst HTTPS/WebXR und Nordkalibrierung.
- Mehrclient-Befehle absichern, bevor Q3 etwas auslöst.
- Autostart und DEV/PROD nach der Autostart-Spec. Kaltstarts ohne Internet.

## Verwandte Dateien

- [MeLE Autostart und Entwicklungsbetrieb](mele-autostart-dev-prod-spec.md)
- [MeLE-PC Autostart](mele-pc-autostart.md)
- [weather_server](weather-server.md)
- [Session Storage](mele-session-storage-weather-archive-spec.md)
- `configs/mele.yaml` — Port 8082, Capture, WORK, ARCHIVE
- `mele/weather.py` — GeoSphere-Cache
- `mele/weather_safety.py` — lokale Station
