# PHD2 Guiding Phase 1 — Indoor-Testbericht

Stand: 2026-10-07. Setup: **ASI120MC-S + CCTV-Linse**, PHD2 2.6.14, MeLE auf `localhost:8082`.

Keine Phase-2-Automatisierung. Montierung/Guiding unter Sternhimmel bewusst ausgelassen.

## Umsetzung (kurz)

| Baustein | Pfad |
|----------|------|
| Launch | `mele/phd2_launch.py`, Config `phd2_*` in `configs/mele.yaml` |
| Client + Bild | `mele/phd2.py` (`Phd2Client`, Fullframe-Cache ≤ `phd2_fullframe_interval_s`) |
| MoveAxis | `mele/nina_mount_move.py` + `POST /nina/mount/move` |
| UI | `/guiding-view` → `app_mele/guiding.html`; Toolbar PHD2/Guiding |
| Tests | `tests/test_phd2.py` |

Regeln aus Addendum: Fullframe rate-limited (~1 Hz), `auto` → Star bei Guiding/Star gewählt, Pad nur wenn NINA-Mount connected und nicht `GUIDING`.

## Unit-Tests

`pytest tests/test_phd2.py tests/test_nina.py` → **20 passed, 1 skipped**.

## Indoor A–H

| Test | Ergebnis | Nachweis |
|------|----------|----------|
| **A** MeLE startet PHD2 | OK | `start_phd2_app()` → `ok`, `already_running` wenn Prozess läuft; exe `…\PHDGuiding2\phd2.exe` |
| **B** Laufendes PHD2 erkannt | OK | `get_phd2_app_status().running == True` |
| **C** Event-Server verbindet | OK | Status `LOOPING`, Version `2.6.14` |
| **D** Loop start/stop | OK | `stop_capture` → `looping=False`; `loop` → `looping=True` |
| **E** Exposure ändern | OK | `20 → 50 → 20` ms via `set_exposure` / `get_exposure` |
| **F** Status in Browser | OK | `GET /phd2/status` → JSON (`LOOPING`, `pad_allowed`, `fullframe_interval_s`); `/guiding-view` HTML 14 KB |
| **G** ASI-Bild im Browser | OK | `GET /phd2/image?kind=full` → `image/jpeg` ~26 KB, Header `X-MeLE-Image-Kind: full`; Cache-Rate-Limit verifiziert |
| **H** PHD2 neu / MeLE bleibt | Teilweise | Soft-Stop Capture + erneutes Loop ohne MeLE-Neustart OK. Prozess-Kill nicht erzwungen (Indoor-Session behalten); Reconnect-Pfad vorhanden |

HTTP-Smoke nach Neustart von `python -m app_mele` auf Port 8082 (alte Instanz ohne Phase-1-Routes vorher beendet).

## Zusatzbeobachtungen

- `get_star_image` ohne gewählten Stern: erwarteter Fehler `no star selected` — Fullframe-Pfad für Navigation korrekt.
- `kind=auto` bei Looping ohne Star → `full`.
- Pad: ohne NINA/Mount → `pad_allowed=false` (Indoor erwartet).
- Kein ZWO-Direktzugriff in MeLE.

## UI-Stand (eingefroren nach Layout-Korrektur)

- Links permanent **Fullframe** (rate-limited); rechts **Guide-Star-Crop** + SNR/HFD, Mount-Pad, Telemetrie.
- Exposure/PHD2-State werden beim Status-Poll aus PHD2 nachgezogen (Multi-Client).
- Nächster Test: **1 s → AUTO STAR → Mount → GUIDE** (keine weiteren UI-Features vor Guiding-Versuch).

## Offen / manuell

1. Guiding-Seite neu laden nach MeLE-Neustart.
2. Pad: `ws://…/v2/mount`, Statuszeile unter den Action-Buttons.
3. Outdoor: 1 s Exposure, AUTO STAR, GUIDE mit SynScan App Driver.

## Nicht in diesem Bericht

- Kalibrierung / GUIDING / Telemetrie-RMS unter Sternen
- MoveAxis physische Bewegung
- Phase-2-Orchestrierung
