# MeLE Autostart und Entwicklungsbetrieb (Spec)

> Quelle: Chat mit Cursor, 2026-10-09 · Thema: schlanker Bootstrap, DEV/PROD auf Port 8082
> Stand: **beschlossen, noch nicht implementiert.** Den Windows-Task erst nach ausdrücklicher Freigabe registrieren. Zuerst Phase A, danach Phase B. Feldnetz und Quest hängen nicht daran.

Ist-Betrieb (nur `weather_server` startet automatisch): [MeLE-PC Autostart](mele-pc-autostart.md), [weather_server](weather-server.md).

## Ziel

Nach dem Einschalten des MeLE ist die Oberfläche am iPad erreichbar, ohne die Programme von Hand zu öffnen. Die Weiterentwicklung in Cursor auf demselben Port bleibt möglich. Dafür gibt es einen kurzen Bootstrap, keine zweite Steuerungsanwendung.

Beobachtung (Alignment, GoTo, Guiding, Aufnahmeserien) bleibt manuell über die bestehende Oberfläche.

## Ist und Soll

| Thema | Heute | Diese Spec |
|---|---|---|
| `weather_server` | Task `Astro-weather_server`, Port 8765 | bleibt eigener Task, Bootstrap startet ihn nicht |
| MeLE-App | nur manuell, `python -m app_mele`, Port 8082 | Task `Astro-mele_app` bei Anmeldung (Phase A) |
| NINA, SynScan, PHD2 | Buttons in der App, Starter in `mele/` | Phase B: dieselben Starter, einmalig, ohne Gerätebefehle |
| Windows-Benutzer | `Chris` | vorerst `Chris`; Autologin erst Phase D |
| Tailscale | Dienst automatisch plus Tray beim Login | optional, keine Startvoraussetzung |

## Verbindliche Architektur

- App: `python -m app_mele`, Port **8082**, Host aus `configs/mele.yaml` (`ui_host`, heute `0.0.0.0`). Port 8080 gilt nicht. Port 8081 ist `app_astro`.
- Windows-Aufgabenplanung, Trigger Anmeldung von `Chris`, interaktiv, keine Administratorrechte.
- Bootstrap startet die App losgelöst und beendet sich. Er bleibt kein Elternprozess. Ein Absturz der App beendet keine anderen Programme.
- Der Bootstrap hat keine Geräte- oder Verbindungslogik. Er startet, prüft die HTTP-Antwort und schreibt das Protokoll. Zustände liest nur die App.
- Starter wiederverwenden: `mele/nina_launch.py`, `mele/synscan.py`, `mele/phd2_launch.py`. Keine zweiten `Popen`-Pfade, keine neuen Geräteclients.
- Kein permanenter Watchdog und kein `RestartCount` für die App oder die GUI-Programme.
- Keine automatischen Geräteaktionen: keine Belichtung, kein Guiding, kein Alignment, kein GoTo.
- Start hängt nicht an NAS, FH-Notebook, Internet oder Tailscale.
- Aufnahmeverzeichnis bleibt `C:/Astro/Capture/Mele`.

Reihenfolge ab Phase B: App zuerst, danach SynScan, NINA und PHD2 ohne Warteschleife aufeinander. USB und 12 V dürfen Minuten brauchen. Die Oberfläche zeigt in der Zeit den Wartestatus.

## Zustände

Die App ist die einzige Anzeige. Der Bootstrap interpretiert keine Geräte.

| Komponente | Prozess läuft | Bereit | Eingeschränkt |
|---|---|---|---|
| MeLE-App | HTTP-Antwort auf Port 8082 | Seite erreichbar | — |
| SynScan Pro | `SynScanPro.exe` | Prozess läuft | kein eigener Verbindungsstatus; Montierung kommt über NINA |
| NINA | `NINA.exe` | API `localhost:1888` | API da, Kamera oder Montierung nicht verbunden |
| PHD2 | `phd2.exe` | Event-Server Port 4400 | Server da, keine Guidekamera |
| weather_server | eigener Task | `http://127.0.0.1:8765/` | Station alt oder offline |
| Tailscale | Dienst | nur Fernzugriff und WORK | fürs iPad im Feld egal |

„Prozess läuft“ ist nicht „aufnahmebereit“. Aufnahmebereit ist NINA erst, wenn Prozess, API und die benötigten Geräte verbunden sind. Ein laufender SynScan-Prozess ist keine bestätigte Montierungsverbindung.

## Bootstrap (Phase A)

Task-Name: `Astro-mele_app`.

Launcher `scripts/mele-app.ps1`:

1. Keine zweite Instanz, wenn die Kommandozeile bereits `-m app_mele` enthält oder Port 8082 antwortet.
2. Start: `.venv\Scripts\python.exe -m app_mele --no-show`, losgelöst.
3. Höchstens etwa 45 Sekunden auf HTTP-Antwort von `http://127.0.0.1:8082/` warten. Ein belegter Port allein ist kein Erfolg.
4. Startzeit, PID und Fehler nach `data/mele/autostart.log`. Bei Ausbleiben der Antwort nur protokollieren, nicht erneut starten.

`--no-show` unterdrückt das Browserfenster (`ui.run` hat heute `show=True`) und ist der Produktiv-Marker in der Kommandozeile. Der Produktiv-Start übergibt nie `--reload`.

`ui.run` bleibt voreingestellt `reload=False`. Das steht nicht in `configs/mele.yaml` und wird dort nicht ergänzt. Wer beim Entwickeln Reload will, startet `python -m app_mele --reload`. Ohne dieses Argument verhält sich die App wie heute. `--reload` und `--no-show` sind unabhängig. Der Task kombiniert sie nicht.

## DEV und PROD

Nur eine App-Instanz zur Zeit, derselbe Port 8082. Umschalten macht der Benutzer, nicht Cursor beim Öffnen.

| Modus | Autostart-Task | Prozess |
|---|---|---|
| PROD | aktiv | `python -m app_mele --no-show` (ohne `--reload`) |
| DEV | deaktiviert | `python -m app_mele` aus Cursor; Reload nur mit zusätzlichem `--reload` |

- `scripts/astro-dev.ps1`: Task deaktivieren und nur Prozesse beenden, deren Kommandozeile `-m app_mele` und `--no-show` enthält.
- `scripts/astro-prod.ps1`: Entwicklungsinstanz auf Port 8082 beenden, Task aktivieren, produktive App starten.
- Ohne `-Confirm` nur anzeigen, nichts ändern.
- Nicht beenden: NINA, SynScan Pro, PHD2, `weather_server`. Kein pauschales Beenden aller `python.exe`.
- `scripts/free-port-8082.ps1` bleibt für die Entwicklung und wird von den Umschaltskripten nicht verwendet, weil es jeden Hörer auf dem Port beendet.

Beide Modi nutzen dieselben Dateien: `data/catalogs/astro_manager.sqlite`, `data/catalogs/sky.sqlite`, `C:/Astro/Capture/Mele`. Keine zweite Datenbank und keine parallelen DEV/PROD-Instanzen, solange Schreibzugriffe auf SQLite, Sessions und Hardware nicht getrennt sind.

## Umschaltung und laufende Geräte

Vor dem Beenden der App:

1. NINA-API über die vorhandene Idle-Prüfung (`mele/session_idle.py`) lesen. Belichtung oder Download: abbrechen.
2. `GET /astro/busy` der laufenden App lesen. Die Zählung laufender MeLE-Aufnahmen liegt nur im Arbeitsspeicher und ist sonst von außen nicht sichtbar.
3. Ist die NINA-API nicht erreichbar, abbrechen und das melden. Weiter nur mit zusätzlichem `-Force`.

PHD2-Guiding und eine NINA-Aufnahme laufen in den jeweiligen Programmen weiter. Beendet wird nur die Weboberfläche. `-Force` beendet trotzdem keine anderen Programme.

## Phasen

| Phase | Inhalt | Abnahme |
|---|---|---|
| A | App-Task, Log, HTTP-Prüfung, `--no-show`, `astro-dev.ps1`, `astro-prod.ps1`, `GET /astro/busy`. Noch kein GUI-Autostart | App nach Anmeldung erreichbar; Cursor-Start auf 8082 bleibt möglich |
| B | SynScan, NINA, PHD2 über vorhandene Starter, einmalig, begrenzte Wiederholung nur in der Bootphase | zehn Kaltstarts ohne Programme von Hand zu öffnen |
| C | bestehende LEDs und Startknöpfe schärfen: Prozess, API, Gerät. Letzte Bootstrap-Fehler anzeigen | fehlende Geräte am iPad erkennbar |
| D | Autologin, Astro-WLAN, Energie, Updates, Start ohne Internet | MeLE ein, iPad verbunden, Oberfläche da |

Phase D ändert keine Windows-Systemeinstellung ohne ausdrückliche Freigabe. Autologin erst nach bestandenen Kaltstarts von A und B.

## Phase A — Dateien

Neu, Install-Skript erst nach Freigabe ausführen:

- `scripts/mele-app.ps1`
- `scripts/install-mele-app-autostart.ps1`
- `scripts/uninstall-mele-app-autostart.ps1`
- `scripts/astro-dev.ps1`
- `scripts/astro-prod.ps1`

Ändern:

- `app_mele/__main__.py` und `run_app` in `app_mele/main_app.py` für `--no-show` und optionales `--reload` (Voreinstellung bleibt aus)
- `GET /astro/busy` in `app_mele/main_app.py`

Unverändert: NINA-/SynScan-/PHD2-Starter, weather_server-Task, `configs/mele.yaml`, SQLite-Dateien.

## Phase A — Tests

1. Task von Hand starten: `http://127.0.0.1:8082/` antwortet, Log enthält PID, auf dem MeLE öffnet sich kein Browser.
2. Zweiter Start erzeugt keine zweite Instanz.
3. `astro-dev.ps1` ohne `-Confirm` ändert nichts. Mit `-Confirm` endet nur die Produktiv-Instanz, der Task ist aus, Port 8082 ist frei. weather_server und laufende GUIs bleiben.
4. `python -m app_mele` aus Cursor belegt 8082. Ein erneuter Task-Start legt keine zweite Instanz an.
5. `astro-prod.ps1 -Confirm` beendet die Entwicklungsinstanz und bringt die produktive App zurück.
6. Während einer NINA-Belichtung verweigert die Umschaltung ohne `-Force`.
7. Abmelden und anmelden: die produktive App kommt über den Task.

## Feldnetz und Quest

Reiserouter, Astro-WLAN, S22-Gateway und Meta Quest 3: [MeLE Feldnetz, Reiserouter und Quest 3](mele-feldnetz-quest-spec.md). Keine Abhängigkeit dieser Autostart-Spec. Fürs Feld reicht, dass das iPad den MeLE auf Port 8082 im lokalen WLAN erreicht. Tailscale bleibt optional.

## Verwandte Dateien

- [MeLE-PC Autostart](mele-pc-autostart.md) — was heute installiert ist
- [weather_server](weather-server.md)
- `configs/mele.yaml` — `ui_port`, `ui_host`, EXE-Pfade, `local_capture_root`
- `scripts/install-weather-server-autostart.ps1` — Muster für den späteren App-Task
- `scripts/free-port-8082.ps1` — nur manuell in der Entwicklung
- `mele/session_idle.py`
