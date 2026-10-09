# MeLE Phase 1.5 — PHD2 Guiding Dry-Run / Telemetrie (Agent-Spec)

Stand: 2026-10-07. Aufbauend auf Phase 1 (Indoor OK) und Architektur-Review;
zur schrittweisen Implementierung durch Cursor-Agent. **Noch kein Phase 2.**

## Verdict

Die externe Phase-1.5-Spec ist **architektonisch passend** für die Schlechtwetterphase:
Telemetrie, Event-Log, Graph, Calibration-/Equipment-Anzeige und Replay —
**ohne** Guiding-Automatisierung und ohne feste „gute“ RMS-Grenzen.

Korrekturen (verbindlich):

1. **Einheiten:** `GuideStep.RADistanceRaw` / `DECDistanceRaw` sind **Pixel**, nicht Bogensekunden.
   Arcsec erst nach zentraler Umrechnung mit `get_pixel_scale`. Ohne gültigen Scale: Pixel anzeigen und klar kennzeichnen (`px`), nie stille Fehl-Einheit `″`.
2. **Bestehenden Telemetrie-Puffer erweitern** (`Phd2Client._steps` / `TELEMETRY_SECONDS`) — keinen parallelen zweiten Puffer oder Service.
3. **Event-Log edge-triggered:** nur bei echten Zustandswechseln / PHD2-Events; kein Polling-Spam.
4. **Calibration nur über PHD2-API** (`get_calibrated`, `get_calibration_data`, …). Kein Log-Parser, keine GUI-Automation. Status zunächst `AVAILABLE` / `NONE` (nicht `VALID`/`QUESTIONABLE`).
5. **Equipment-Profiles in MeLE** = Zuordnung zu PHD2-Profilen, **keine** eigene Kalibrierungsmatrix. Getrennt von Imaging-Profiles (`astro_manager`).
6. **Image scale:** Primär `get_pixel_scale`; MeLE-Formel `206.265 * µm / mm` nur als Anzeige aus Konfig, wenn PHD2 nichts liefert.
7. **Session:** nur vorbereiten (Felder/Ordnerkonzept); keine volle Session-Pipeline in 1.5.
8. **Replay (optional):** eigener Provider, klar getrennt vom echten `Phd2Client`; erzeugt nie Kamera-/Mount-Kommandos.

Zusätzliche Agent-Regeln:

- Bestehende Implementierungen wiederverwenden; keine parallelen Services/Datenpuffer.
- Pixel→Arcsec **zentral** (eine Hilfsfunktion) + Unit-Tests.
- Bei Guiding-Events unterscheiden: **PHD2-Ereignis** vs. **abgeleiteter Zustand** (z. B. `STAR_RECOVERED`).
- Phase-1-Funktionen (Fullframe, Star-Crop, Exposure, LOOP/AUTO STAR/GUIDE/PAUSE/STOP, Pad, Lock-Burn-in) dürfen nicht regressieren.
- Pro Implementierungsabschnitt konkrete Indoor-Akzeptanztests (unten).
- **MeLE-App nicht vom Agenten dauerhaft laufen lassen** — User startet selbst; Agent nur gezielt zum Testen, danach wieder stoppen wenn angefordert.

---

## Ausgangslage (Ist nach Phase 1)

| Bereich | Pfade / Stand |
|--------|----------------|
| Launch | `mele/phd2_launch.py`, Config `phd2_*` |
| Client | `mele/phd2.py` — Singleton, Events, RPC, `GuideStepSample`-Puffer (~300 s), RMS in **Pixeln** |
| Bild | Fullframe `save_image`→FITS→JPEG (+ Lock-Burn-in aus `PHDLOCKX/Y`); Star `get_star_image` |
| UI | `/guiding-view` → `app_mele/guiding.html` — Full links, Star+Pad+Telemetrie rechts |
| Pad | NINA `ws://…/v2/mount`; gesperrt bei `GUIDING`/`CALIBRATING` |
| Multi-Client | Exposure/State via Status-Poll aus PHD2 (SoT) |
| Tests | `tests/test_phd2.py` |
| Indoor-Bericht | `wiki/knowledge/phd2-guiding-phase1-indoor-report.md` |

Bekannter UI-Bug (in 1.5 beheben): Telemetrie beschriftet RA/DEC-Fehler und RMS mit `″`, obwohl Rohwerte Pixel sind.

---

## Architekturregel (unverhandelbar, unverändert)

```
ASI120MC-S --USB--> PHD2 --Event Server--> MeLE Phd2Client --> /guiding-view
                 |
                 +-- PulseGuide --> ASCOM Mount --> Montierung

Manuelles Pad:
Browser --> MeLE --> NINA MoveAxis (/v2/mount) --> ASCOM Mount
```

- MeLE öffnet ASI120 nie direkt.
- Ein zentraler `Phd2Client`; Browser nur MeLE-REST.
- Keine zweite Guiding-Engine, kein ST4 aus MeLE, kein PHD2-GUI-Scraping.

---

## UI-Freeze (Layout)

Bestehendes Dual-Panel **beibehalten**:

**Links:** Fullframe, Fit/1:1/Zoom, Full-Update-Intervall, Exposure, LOOP, AUTO STAR, GUIDE, PAUSE, STOP.

**Rechts:** Star-Crop, SNR/HFD, Mount-Pad, Telemetrie, **neu:** Graph + Event-Log + kompaktes Calibration/Equipment.

Fullframe und Star-Crop bleiben gleichzeitig sichtbar. PHD2 bleibt SoT für Exposure und State.

---

## Scope Phase 1.5

### In Scope

1. Pixel↔Arcsec zentral + korrekte Telemetrie-Anzeige
2. Erweiterte Live-Telemetrie (Pulse-Richtungen, Dauer, Lost-Star-Info, …) im **bestehenden** Puffer
3. Guiding-Graph (RA/DEC Error vs. Zeit, letzte 5–10 min)
4. Edge-triggered Event-Log (PHD2 + abgeleitete Zustände)
5. Calibration-/Equipment-Panel (API-only)
6. MeLE Equipment-Configuration → PHD2-Profil-Zuordnung (Persistenz)
7. Session-Vorbereitung (Konzept/Felder; optionale Log-Referenz)
8. Optional: Telemetry Replay/Test Provider
9. Indoor-Akzeptanztests A–I + Abschnitt-Tests pro Abschnitt

### Explizit Out of Scope (Phase 2+ — zurückgestellt)

- automatische Guiding-Parameteroptimierung / Auto-Kalibrierung / Neukalibrierung
- automatische Lost-Star-Recovery außerhalb PHD2
- Meridian-Flip, „guiding stable“, Imaging-Start aufgrund RMS
- feste RMS-Grenzen / „gut/schlecht“-Bewertung
- ST4, Direkt-ASI120, eigene Guiding-Algorithmen
- automatische Mount-Recovery bei PulseGuide-Fehlern

---

## Priorisierte Implementierungsabschnitte

Reihenfolge fest. Jeder Abschnitt endet mit Unit-Tests + Indoor-Check; Freigabe vor dem nächsten.

### Abschnitt A — Einheiten & Telemetrie-Kern

**Ziel:** Anzeige und API ehrlich; zentrale Umrechnung.

- Hilfsfunktion z. B. `pixels_to_arcsec(px, scale)` / `arcsec_to_pixels`; `scale` aus `get_pixel_scale` (cache bei Connect/`ConfigurationChange`).
- `GuideStepSample` erweitern (nicht doppelter Puffer): u. a. `ra_direction`, `dec_direction`, ggf. `guide_time_s` (`GuideStep.Time`), `error_code`.
- `/phd2/telemetry` liefert Rohwerte in px **und** (wenn Scale gültig) Arcsec + RMS in beiden Einheiten klar benannt (`ra_rms_px`, `ra_rms_arcsec`, …).
- UI: bei gültigem Scale `″`, sonst `px` (nie gemischt ohne Label).
- Unit-Tests: Scale 3.09 → bekannte px→″; Scale `None`/0/NaN → keine Arcsec-Felder bzw. `null`, UI-Label `px`.

**Indoor A1:** Mit laufendem PHD2/`GuideStep` (oder Mock): Telemetrie zeigt korrekte Einheit; Multi-Client gleich.

### Abschnitt B — Event-Log

**Ziel:** Chronik ohne Flut.

- Ringpuffer/Liste serverseitig im `Phd2Client` (oder eng gekoppelt), REST z. B. `GET /phd2/events?limit=…`.
- Eintrag nur bei Transition / Event — nicht bei jedem Status-Poll.
- Felder: `utc`, `kind`, `source` (`phd2`|`derived`), `message`, optionale Payload.
- Mindestens mappen/ableiten:

| kind | Quelle |
|------|--------|
| `CONNECTED` / `LOOPING` / `GUIDING` / `PAUSED` / `CALIBRATING` / `GUIDING_STOPPED` | PHD2 `AppState` / Start*/Stop*-Events |
| `STAR_SELECTED` | `StarSelected` |
| `CALIBRATION_COMPLETE` / `CALIBRATION_FAILED` | entsprechende PHD2-Events |
| `STAR_LOST` | `StarLost` (+ last SNR wenn bekannt) |
| `STAR_RECOVERED` | **derived** (Lost → wieder GuideStep/Star ohne Lost) + `outage_s` |
| `MOUNT_ERROR` | `Alert` / erkennbare Mount-/PulseGuide-Texte — nur loggen |
| SNR-Sprung (optional) | derived, gedrosselt (Schwelle + Min-Intervall), nicht jedes Frame |

**Indoor B1:** Zustandswechsel erzeugen genau einen sinnvollen Eintrag; Polling allein erzeugt keine Events.  
**Indoor B2:** `STAR_LOST` → `STAR_RECOVERED` mit Dauer.

### Abschnitt C — Guiding-Graph

**Ziel:** Platzhalter ersetzen; nur Anzeige.

- Daten aus bestehendem Step-Puffer (5–10 min).
- X = Zeit, Y = Error (″ wenn Scale, sonst px — Achsenbeschriftung!).
- Serien: RA, DEC (optional Total später).
- Keine Bewertung, keine Schwellenlinien als „gut/schlecht“.
- Update ohne Full-Page-Reload (Poll/Telemetry-Tick).

**Indoor C1:** Zeitreihe läuft kontinuierlich; Reload nicht nötig.  
**Indoor C2:** Einheit der Y-Achse stimmt mit Telemetrie überein.

### Abschnitt D — Calibration- & Equipment-Anzeige

**Ziel:** Kompaktes Panel, API-only.

- RPC: `get_calibrated`, `get_calibration_data` (Mount), `get_profile` / `get_profiles`, `get_current_equipment`, `get_pixel_scale`.
- Anzeige: Profilname, Camera/Mount-Namen, Scale, Calibration `AVAILABLE`/`NONE`, Winkel/Rates/Parity soweit geliefert; fehlendes = `—`.
- Kein zweiter Parser; keine automatische Qualitätsbewertung.

**Indoor D1:** Mit/ohne Kalibrierung korrekte `AVAILABLE`/`NONE`.  
**Indoor D2:** Fehlende Felder zeigen `—`, kein Crash.

### Abschnitt E — MeLE Equipment-Configuration

**Ziel:** Persistente Zuordnung Montierung/Setup → PHD2-Profil.

Konzept (JSON unter `data/…`, analog anderer Prefs — kein Imaging-DB-Zwang):

```text
id, name, mount_id, imaging_optics_id, guiding_camera_id,
guiding_scope_id, guiding_focal_length_mm, phd2_profile_name | phd2_profile_id
```

- MeLE speichert **keine** Kalibrierungsmatrix.
- `set_profile` nur wenn PHD2 Equipment disconnected; sonst Zuordnung speichern, Wechsel manuell in PHD2 (dokumentieren).
- Image-scale-Hinweis aus MeLE-Konfig optional parallel zu PHD2-Scale.

**Indoor E1:** Mehrere Configs speichern/laden; Zuordnung zu PHD2-Profilname sichtbar.  
**Indoor E2:** Kein erzwungener Profilwechsel bei connected Equipment.

### Abschnitt F — Lost-Star- & Mount-Error-Darstellung

**Ziel:** Erkennen, anzeigen, protokollieren — keine Recovery.

- UI-Badge/Zeile: `STAR LOST`, Dauer, last SNR.
- Bei Recovery: outage-Dauer.
- Mount-/PulseGuide-Fehler als Events (siehe B); Pad-Sperren unverändert.

**Indoor F1:** Lost/Recovered in UI + Log.  
**Indoor F2:** Keine automatische `find_star`/Pad-Bewegung/Neukalibrierung durch MeLE.

### Abschnitt G — Session-Vorbereitung (leicht)

**Ziel:** Spätere Korrelation vorbereiten, nicht fertig orchestrieren.

- Spezifizieren/ggf. minimale Felder: `equipment_profile_id`, `phd2_profile`, Guiding-Zeitfenster, Pfade für telemetry/events (noch nicht zwingend schreiben).
- PHD2-Guide-Logs nicht verändern; optional später Referenzpfad.
- Zielstruktur dokumentieren (`Session/guiding/{telemetry,events,…}`) — Implementierung der Ordneranlage darf stub bleiben.

**Indoor G1:** Keine Regression der Imaging-Sessions; Guiding bleibt unabhängig nutzbar.

### Abschnitt H — Replay-Provider (optional)

**Ziel:** UI/Graph/Log indoor ohne Montierung.

- Interface kompatibel zu Status/Telemetry/Events-Reads.
- Klar getrennt; Feature-Flag/Config.
- **Niemals** `loop`/`guide`/Pad/MoveAxis/save_image an echte Hardware während Replay.
- Synthetische Sequenz: LOOPING → STAR_SELECTED → CALIBRATING → GUIDING → Samples → STAR_LOST → STAR_RECOVERED → STOPPED.

**Indoor H1:** Replay füllt UI/Graph/Log.  
**Indoor H2:** Während Replay keine realen Mount-/Kamera-Side-Effects (Netzwerk/WS prüfen).

---

## Gesamte Akzeptanztests Phase 1.5 (Regression + Querschnitt)

| ID | Test | Erwartung |
|----|------|-----------|
| **A** | Multi-Client | Exposure/State in Client A → Client B via Poll |
| **B** | Telemetry | RA/DEC erscheinen in UI + Puffer; Einheiten korrekt |
| **C** | Graph | kontinuierlich ohne Reload |
| **D** | Events | ein Eintrag pro sinnvollem Wechsel; keine Poll-Flut |
| **E** | Star Lost | LOST→RECOVERED mit Dauer |
| **F** | Equipment | Configs speicherbar, PHD2-Profil zugeordnet |
| **G** | Safety | Pad gesperrt bei GUIDING/CALIBRATING |
| **H** | Replay | falls gebaut: keine realen Kommandos |
| **I** | Regression | Fullframe, Star-Crop, Exposure, LOOP, AUTO STAR, GUIDE, PAUSE, STOP, Lock-Box im JPEG |

---

## Explizit keine RMS-Schwellen

Keine festen „guten“ RMS-Grenzen in Code oder UI-Ampeln. Schwellen erst nach realem Outdoor-Lauf mit **sauberer** NEQ6-Kalibrierung und 20–30 min Guiding ableiten (zusammen mit Wetterdaten).

---

## Abschluss Phase 1.5 / Übergang Outdoor

Nach Implementierung **keine Phase 2 beginnen**.

Nächster klarer Abend (manuell):

1. Montierung zugänglich aufbauen.
2. Kalibrierregion nahe Äquator/Meridian.
3. PHD2 sauber kalibrieren und Review in PHD2.
4. 20–30 min Guiding aufzeichnen.
5. MeLE-Telemetrie/Events + PHD2-Log-Referenz + Wetter sichern.
6. Erst dann Phase-2-Automatisierung und Schwellen entwerfen.

---

## Agent-Arbeitsanweisung (kurz)

1. **Zuerst nur diese Spec** — Implementierung erst nach expliziter Freigabe Abschnitt für Abschnitt.
2. Bestehende `Phd2Client`-Puffer/REST erweitern; nichts Parallel erfinden.
3. Pixel→Arcsec zentral + Tests; fehlender Scale → `px`.
4. Events: `source=phd2` vs `source=derived` kennzeichnen.
5. Phase-1-Regression (I) nach jedem Abschnitt grün halten.
6. MeLE nicht dauerhaft im Hintergrund lassen, wenn der User selbst starten will.
7. Phase 2 nicht anfassen.
