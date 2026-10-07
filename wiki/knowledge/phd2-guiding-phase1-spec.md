# MeLE Phase 1 — PHD2 / ASI120 Guiding (Agent-Spec)

Stand: 2026-10-07. Architektur-Review gegen bestehende MeLE-App; zur Implementierung durch Cursor-Agent.

## Verdict

Die externe Spec ist **architektonisch korrekt und wünschenswert**, mit diesen Korrekturen:

1. **PHD2 bleibt Kamera-Owner** — MeLE öffnet ASI120 nie direkt (kein ZWO-SDK/ASCOM Camera/OpenCV).
2. **Livebild**: PHD2-Event-Server liefert **kein volles FOV-Stream**. `get_star_image` = Crop um Guide-Star (nur wenn Star gewählt). Vollframe: `save_image` → temporäre FITS, MeLE liest/konvertiert zu JPEG. Abstraktion `GuideImageProvider` bleibt Pflicht.
3. **Mount-Pad**: MeLE hat heute nur GoTo/Stop via NINA REST. Manuelles Joggen über **NINA Advanced API MoveAxis-WebSocket** `ws://…/v2/mount` (eingebauter Failsafe ~2 s). Nicht ST4/ASI120, nicht zweite Mount-Architektur.
4. **Route**: wie bestehende Pages → `/guiding-view` + `app_mele/guiding.html` (nicht nur `/guiding`).
5. **Process-Start**: Spiegel von `mele/nina_launch.py` / `mele/synscan.py` → `mele/phd2_launch.py` + `phd2_exe` in `configs/mele.yaml`.
6. **Ein** serverseitiger `Phd2Client` (TCP :4400); Browser pollen MeLE-REST, keine parallelen PHD2-Verbindungen pro Tab.

Keine Nebenwirkungen auf NINA-Capture/Lumix, wenn ASI120 ausschließlich in PHD2 bleibt und Mount-Pad nur über NINA MoveAxis geht.

---

## Ausgangslage (Ist)

Bereits vorhanden:

| Bereich | Pfade / Muster |
|--------|----------------|
| NINA starten | `mele/nina_launch.py`, Toolbar in `app_mele/layout.py`, Handler in `app_mele/main_app.py` |
| SynScan starten | `mele/synscan.py` (nur Process, kein Mount-IO) |
| NINA REST | `mele/nina.py` — camera/capture, mount info/slew/stop |
| Browser-Pages | Static HTML → `@app.get("/…-view")` → `window.open` (pano, imaging, weather, …) |
| Mount GoTo | `POST /nina/mount/slew`, Stop `POST /nina/mount/slew/stop`; UI in `pano.html` |
| Mount Jog | **fehlt** in MeLE; NINA API hat `MountAxisMoveSocket` (MoveAxis + Auto-Stop) |

Nicht vorhanden: PHD2-Code, Guiding-Page, Pulse/Jog in MeLE.

PHD2 2.6.x Event Server (JSON-RPC 2.0, typisch `localhost:4400`): dokumentiert u. a. `loop`, `stop_capture`, `set_exposure`, `get_exposure`, `find_star`, `guide`, `set_paused`, `get_star_image`, `save_image`, Events `GuideStep`, `AppState`, `StarLost`, …

---

## Architekturregel (unverhandelbar)

```
ASI120MC-S --USB--> PHD2 --Event Server--> MeLE Phd2Client --> /guiding-view
                 |
                 +-- PulseGuide --> ASCOM SynScan App Driver --> Montierung

Manuelles Pad (MeLE):
Browser --> MeLE --> NINA MoveAxis WebSocket --> ASCOM Mount --> Montierung
```

- MeLE **nie** parallel ASI120 öffnen.
- PHD2 Guiding-Engine; MeLE = Orchestrator + UI.
- Kein Screenshot/Screen-Scraping von PHD2.

---

## Phase-1 Scope

### In Scope

1. `phd2_exe` Config + `mele/phd2_launch.py` (find / is_running / start / status; stop vorsichtig, optional via RPC `shutdown`)
2. Hauptfenster: PHD2-LED + Start + „Open Guiding“ (wie NINA/SynScan)
3. `mele/phd2.py`: `Phd2Client` (TCP reconnect, State-Machine, Commands, Telemetrie-Puffer)
4. `GuideImageProvider`: Star-Crop und/oder Fullframe via `save_image`→JPEG; klare Caps, wenn FOV-Stream fehlt
5. Page `/guiding-view` + `guiding.html`: großes Bild, Exposure, LOOP/AUTO STAR/GUIDE/PAUSE/STOP, Telemetrie
6. Mount-Pad RA±/DEC±/STOP über **neuen** MeLE-Proxy auf NINA MoveAxis (Failsafe); bei PHD2-State `Guiding` deaktiviert
7. Unit-Tests (Mocks); Indoor-Tests A–H aus Spec

### Out of Scope (Phase 1)

Automatisches Starten mit NINA, Auto-Guide nach GoTo, Dither-Orchestrierung, Meridian-Flip, eigene Centroid/Kalibrier-Algorithmen, Direktzugriff auf ZWO.

---

## Implementierungsplan (Reihenfolge)

### Schritt 0 — Analyse (kein Code)

1. `nina_launch` / `synscan` / Toolbar-Polling spiegeln.
2. PHD2 EventMonitoring Wiki: Bildpfade (`get_star_image` vs `save_image`) verifizieren (kurz gegen laufendes PHD2 testen, wenn möglich).
3. NINA MoveAxis-WebSocket-URL/Path aus Advanced API / Fixture `tests/fixtures/nina/Mount.cs` klären.
4. Kurzer Plan im Chat; dann Code.

### Schritt 1 — Process Service

Datei: `mele/phd2_launch.py` (analog `nina_launch.py`).

- Config: `phd2_exe` in `mele/config.py` + `configs/mele.yaml`
- Standardpfade prüfen (Program Files / User Install), sonst Config
- `PROCESS_NAME` typisch `phd2.exe`
- `start`: `Popen` DETACHED wie NINA; wenn schon running → ok
- Status: `{ installed, running, exe_path, error }`
- Kein harter Kill als Default; optional RPC `shutdown` später

### Schritt 2 — Phd2Client (Server-Singleton)

Datei: `mele/phd2.py`

- Eine Verbindung `host`/`port` aus Config (`phd2_host`, `phd2_port`, Default `127.0.0.1:4400`)
- Thread oder asyncio-Task: lesen Events, JSON-RPC Requests mit id
- State: `OFFLINE | CONNECTING | CONNECTED | LOOPING | CALIBRATING | GUIDING | PAUSED | LOST_STAR | ERROR`
- Aus Events mappen (`AppState`, `LoopingExposures`, `GuideStep`, `StarLost`, `Paused`, …)
- Commands (dokumentierte Namen): `loop`, `stop_capture`, `set_exposure`, `get_exposure`, `get_exposure_durations`, `find_star`, `guide` (+ settle), `set_paused`, `get_app_state`, `get_connected`, `get_current_equipment`, `get_star_image`, `save_image`
- Telemetrie-Ringpuffer (~5 min `GuideStep`)
- Exceptions nur loggen; MeLE-App darf nicht crashen
- **Wichtig:** Client lebt in MeLE-Prozess; alle Browser teilen denselben Client

REST-Fassade in `main_app.py` (Beispiele):

- `GET /phd2/app` — Process-Status (launch)
- `POST /phd2/app/start`
- `GET /phd2/status` — API-State + equipment + last errors
- `POST /phd2/loop` | `/stop` | `/guide` | `/pause` | `/find-star`
- `POST /phd2/exposure` body `{ "exposure_ms": … }`
- `GET /phd2/telemetry` — recent GuideSteps + summary RMS
- `GET /phd2/image` — JPEG vom `GuideImageProvider` (`?kind=star|full`)

### Schritt 3 — GuideImageProvider

- `star`: `get_star_image(size)` → 16-bit → Stretch → JPEG (nur mit Star)
- `full`: `save_image` → FITS lesen (astropy) → Stretch → JPEG → Temp-Datei löschen; Rate limit (z. B. ≤1 Hz), Looping voraussetzen
- Wenn Fullframe unzuverlässig: UI zeigt Star-Crop + Hinweis; kein Screenshot-Fallback

### Schritt 4 — UI Page

- `app_mele/guiding.html` — Stil wie `imaging.html` (dunkles Tablet-Layout)
- Route `@app.get("/guiding-view")` in `run_app()`
- Toolbar: PHD2 Status-LED, Start, „Guiding“ öffnet `window.open('/guiding-view')`
- Layout: Statusleiste | großes Bild | Exposure-Select | Pad | Action-Buttons | Telemetrie-Panel | Platzhalter Graph (Datenmodell ok, Graph optional)

Pad:

- pointerdown → MoveAxis start (Richtung + Rate)
- pointerup / leave / cancel / visibilitychange → stop (Rate 0)
- MeLE-seitiger Timeout falls Browser stirbt (zusätzlich zu NINA ~2 s Failsafe)
- Disabled wenn PHD2 State Guiding/Calibrating

### Schritt 5 — Mount MoveAxis Proxy

Neu in `mele/nina.py` / Routes:

- WebSocket-Client zu NINA MountAxisMove (Path laut API; Fixture: `MountAxisMoveSocket`)
- MeLE-HTTP: `POST /nina/mount/move` `{ direction: east|west|north|south, rate: float }` und `POST /nina/mount/move/stop`
- Keine zweite SynScan-Steuerung

### Schritt 6 — Tests

- Unit: launch path resolution; Phd2Client parse events/RPC (Mocks); image provider mit Fake-FITS/base64
- Keine Regression: bestehende `tests/test_nina.py`, SynScan-Launch
- Manuell Indoor (CCTV-Linse): Tests A–H aus Original-Spec

---

## Nebenwirkungen / Risiken

| Risiko | Mitigation |
|--------|------------|
| ASI120 in NINA + PHD2 | Ops-Hinweis; MeLE öffnet Kamera nicht |
| Viele Browser-Tabs → viele PHD2-Sockets | Ein Server-Client |
| `get_star_image` ohne Star | UI: „Star wählen / AUTO STAR“; Fullframe-Pfad |
| `save_image` Disk-IO | Rate-Limit, Cleanup |
| Pad während Guiding | Buttons disabled |
| Endlose MoveAxis | NINA Failsafe + MeLE stop on pointerup + Timeout |
| PHD2 Stop killt Session | Prefer RPC stop_capture; process kill nur bewusst |

---

## Spätere Phasen (nur vorbereiten, nicht bauen)

GoTo → Center → PHD2 Loop → find_star → guide/settle → NINA Capture → dither — Sequenz in Spec behalten, Code erst nach stabilem Phase-1.

---

## Agent-Arbeitsanweisung (kurz)

1. Bestehende Launch-/Page-Muster lesen, nicht neu erfinden.
2. Zuerst PHD2 Bild-API klären (`get_star_image` / `save_image`), dann `GuideImageProvider`.
3. Kein Direktzugriff auf ASI120.
4. Mount-Pad nur über NINA MoveAxis-Proxy.
5. Keine Automatik-Orchestrierung in Phase 1.
6. Bestehende NINA/SynScan/Imaging-Pfade nicht regressieren; Tests grün halten.
