# MeLE — Session Storage: Wetter, WORK, NAS-Archiv, Remove (Agent-Spec)

Stand: 2026-10-08 (Rev. 3.1 — S0 abgeschlossen, S1 freigegeben).  
Architektur freigegeben. **S1 implementieren; S2–S6 noch nicht.**

## Verdict

Drei Speicherorte, zwei Workflows (**Sichern** vs. **Bearbeiten**), Dual-WORK-Pfade, SHA-256-Manifeste, Wetter-Zeitreihe, Lifecycle, entschärftes Remove. S0 klärt: Session-Abschluss vs. Partial-Snapshot, Manifest-Revision, Weather-API-Ist, Datenweg WORK→ARCHIVE über MeLE.

| Ort | Rolle | typisch wo |
|-----|--------|------------|
| **CAPTURE** | Aufnahme-SoT während der Nacht | MeLE lokal (`local_capture_root`) |
| **WORK** | Siril / Stacking / Ergebnisse | Notebook (UNC vom MeLE, lokal für Siril) |
| **ARCHIVE** | Langzeit-Sicherung + finale Results | NAS (`archive_root`) |

1. **Sichern:** CAPTURE → ARCHIVE (Originale früh, verifiziert).
2. **Bearbeiten:** CAPTURE → WORK; später WORK → ARCHIVE (Results + fehlende Master).

NINA schreibt nie direkt auf NAS/WORK. Transfers = Copy. Siril-Zwischenprodukte nicht archivieren. PHD2 außerhalb (Phase 1.5).

---

## Ausgangslage (Ist)

| Thema | Stand |
|--------|--------|
| Session SQLite + lokaler Ordner | `mele/astro_manager.py`, Capture unter `local_capture_root/…/s#####/` |
| Timing / Preview-Sidecars | `capture-timing.json`, `preview/` |
| Wetter GW1200 | `weather_server` SQLite SoT; MeLE Consumer `/api/current` + `/api/history` |
| `archive_path` / `archive_status` | Metadaten vorbereitet, kein Copy/Verify |
| Session löschen | nur DB, Ordner bleiben |
| WORK / Transfer-Jobs / Manifeste | fehlen |

---

## S0 — Abgeschlossen (verbindliche Entscheidungen)

### S0.0 Rahmen (unverändert)

1. Notebook-SMB: z. B. `\\NOTEBOOK\AstroWork\Mele` → `D:\Astro\Work\Mele`.
2. MeLE-Dienst-Konto: Schreibrechte auf WORK-UNC und ARCHIVE-UNC (nicht nur Explorer-User).
3. Offline → Job `failed` / retry; CAPTURE unangetastet.
4. Kein Notebook-Pull-Agent in v1 — MeLE ist Steuerinstanz und führt alle Copy-Jobs aus.

### S0.1 Session-Abschluss vs. Partial-Snapshot

**Trennung zweier Begriffe:**

| Begriff | Bedeutung |
|---------|-----------|
| Transfer-Job `completed` | Diese Dateiliste wurde verifiziert ans Ziel kopiert |
| Session **vollständig gesichert** | Session ist `CLOSED` **und** es existiert ein abgeschlossenes Voll-Manifest am Archiv, das den aktuellen Master-Stand deckt |

**Lifecycle:**

| Status | Bedeutung |
|--------|-----------|
| `OPEN` | Session angelegt |
| `CAPTURING` | Aufnahme aktiv oder Dateien können noch wachsen |
| `CLOSED` | Aufnahme beendet; NINA-Sequenz nicht mehr laufend; Dateien als final geschrieben betrachtet |

**Button „Session schließen“:**

1. NINA-Idle-Check: **nicht nur** `IsExposing=false`. Auch vorhandene MeLE-Capture-/Sequenzzustände prüfen (laufende Multi-Frame-Sequenzen, Capture-Locks, bekannte „Sequenz aktiv“-Flags). `IsExposing=false` allein bedeutet **nicht**, dass eine Sequenz beendet ist.
2. Bei laufender Belichtung/Sequenz **oder unklarem Zustand**: **Close ablehnen** (klarer UI-Hinweis) — kein reguläres `CLOSED`.
3. Nach erfolgreichem Close: `session_end_utc` setzen, Wetterexport anstoßen (best effort), Lifecycle → `CLOSED`.

*(Idle-Check-Logik gehört zu Close/S2+; S1 legt nur Lifecycle-Felder und erlaubte Statusübergänge an.)*

**Transfers während `CAPTURING`:**

- Erlaubt als **Partial Snapshot** (`job.completeness = partial`).
- Stabilitätsregel für Dateien: Größe+mtime über kurzes Fenster unverändert **oder** Session bereits `CLOSED`.
- UI/DB: **nie** „Session vollständig archiviert“ solange Lifecycle ≠ `CLOSED` oder Manifest revisionell hinter dem Master zurückliegt.

**Nachträgliche Dateien** (weitere Lights, Darks, Flats, Results):

- Erhöhen die erwartete Manifest-`revision` / setzen Archive-Vollständigkeit zurück auf `stale` / `incomplete`.
- Nächster Transfer ergänzt; entfernte bereits archivierte Dateien werden **nicht** gelöscht.
- Vollständigkeit erst wieder `complete`, wenn CLOSED + Verify gegen aktuelles Quell-Manifest ok.

### S0.2 Manifest-Versionierung & Konflikte

`session-manifest.json` (relativ zum Session-Root):

```json
{
  "schema_version": 1,
  "revision": 3,
  "session_id": "…",
  "object": "M101",
  "capture_date": "2026-10-08",
  "lifecycle_at_source": "closed",
  "completeness": "full",
  "generated_utc": "…",
  "files": [
    {"path": "LIGHTS/frame001.RW2", "size": 22700000, "sha256": "…"},
    {"path": "weather/weather.csv", "size": 12345, "sha256": "…"}
  ]
}
```

Regeln:

1. `schema_version` + `revision` (monoton steigend bei inhaltlicher Änderung der Dateiliste/Hashes).
2. Alle `path`-Einträge **relativ** zum Session-Verzeichnis.
3. Ein Transfer arbeitet auf einem **konsistenten Quell-Snapshot** (Dateiliste zu Job-Start einfrieren; neue Dateien während des Jobs → nächste Revision).
4. Späterer Transfer **darf nur ergänzen** am Ziel; bereits verifizierte Dateien mit gleichem Hash bleiben; **kein** Entfernen archivierter Results durch CAPTURE-Push.
5. Gleicher Relativpfad, anderer Hash → **Conflict** (`job.status=failed`, Log); kein silent overwrite.
6. Manifest + „archiviert/vollständig“-Flags am Ziel erst **nach** erfolgreichem Verify veröffentlichen (Write: `*.manifest.partial` → atomic rename / erst dann Status update).
7. Job-`completed` ≠ Session-`archive_completeness=complete` (letzteres nur nach S0.1).

### S0.3 Wetter-API — Ist-Befund (Code-Audit)

Vorhanden in `weather_server`:

| Endpoint | Parameter | Verhalten |
|----------|-----------|-----------|
| `GET /api/current` | — | neuestes Sample |
| `GET /api/history` | `limit` (1…5000, Default 100), `since` (ISO, optional, Filter `recorded_at >= since`) | Samples **neueste zuerst** (`ORDER BY id DESC`) |
| `GET /api/status` | — | Collector + `sample_count` |
| `GET /healthz` | — | liveness |

**Felder pro Sample** (u. a.): `recorded_at`, `station_when`, `temp_c`, `humidity_pct`, `pressure_hpa`, `pressure_abs_hpa`, `wind_ms`, `wind_dir_deg`, `gust_ms`, `rain_mm`, `rain_rate_mm_h`, Regen-Aggregate, `uvi`, `lux`, `dewpoint_c`, `dewpoint_margin_c`, Indoor-Temp/Feuchte, `solarradiation_wm2`.

**Lücken für Session-Export (S2, ohne Server-Umbau wo möglich):**

| Bedarf | Ist | S2-Entscheidung |
|--------|-----|-----------------|
| Start UTC | `since=` vorhanden | nutzen |
| Ende UTC | **kein** `until` | Client filtert `recorded_at <= session_end_utc` |
| Lange Nächte | max 5000 / Request, **neueste zuerst** | Wiederholtes `since` allein paginiert **nicht** zuverlässig ältere Daten (immer die neuesten ≤5000 ab `since`). |
| MeLE-Client | `fetch_history(limit)` **ohne** `since` | in S2 `since` ergänzen; Endzeit clientseitig filtern |
| Nachholbarer Export | — | Button/API „Wetter erneut exportieren“ auch bei `CLOSED` |
| Serverausfall | — | `export_status: unavailable\|partial`; Gaps; Capture/Close bricht nicht ab |

**S2-Wettervollständigkeit (verbindlich):** Zeitfenster nach Export prüfen. Wenn das Fenster mehr Samples braucht als die API zuverlässig liefert (Limit 5000 / fehlende ältere Seiten), Export als **`partial`** melden — **keine stillschweigend unvollständigen** CSV-Exporte. Server-Umbau (`until=`, Cursor-Pagination) optional später, nicht Blocker für S1.

### S0.4 WORK → ARCHIVE: physischer Datenweg

```
Notebook (WORK share)  ──SMB read──►  MeLE  ──SMB write──►  NAS (ARCHIVE)
     work_transfer_root                    archive_root
```

- Job `work_to_archive` läuft **auf dem MeLE**.
- Daten fließen **nicht** direkt Notebook→NAS; sie laufen Notebook → MeLE → NAS (Doppel-Hop).
- MeLE braucht **gleichzeitig**: Leserecht auf `work_transfer_root`, Schreibrecht auf `archive_root`.
- Indoor-Test: beide UNC erreichbar vom Dienst-Konto; Throughput/Timeouts dokumentieren.
- v1 akzeptiert diesen Hop; später optional direkter Notebook→NAS-Push = Out of Scope.

### S0 Indoor-Akzeptanztests (ohne Produktionsdaten)

| ID | Test |
|----|------|
| **S0-T1** | Dienst-User: Write-Probe auf `work_transfer_root` und `archive_root` (kleine Testdatei). |
| **S0-T2** | Eine Freigabe offline → Job scheitert klar; CAPTURE unverändert. |
| **S0-T3** | Close während simuliertem `IsExposing=true` → abgelehnt. |
| **S0-T4** | Partial-Job während CAPTURING setzt nie `archive_completeness=complete`. |
| **S0-T5** | Manifest revision: neue Datei → Revision++; Conflict bei Hash-Mismatch. |
| **S0-T6** | `/api/history?since=…&limit=…` liefert Samples; Client kann Endzeit filtern. |
| **S0-T7** | (Konzept) work_to_archive: Lesen UNC-WORK + Schreiben UNC-ARCHIVE in einem Prozesspfad. |

---

## Architekturregel

```
Nacht (MeLE):
  NINA → CAPTURE/{Object}/{date}/s#####/…
         OPEN → CAPTURING → CLOSED (Close nur wenn NINA idle)
         weather/ Export bei CLOSE (+ jederzeit re-export)

Sichern:
  CAPTURE ──verified copy──► ARCHIVE     [completeness: partial|complete]

Bearbeiten:
  CAPTURE ──verified copy──► WORK (UNC work_transfer_root)
                             UI: work_local_root für Siril
                             siril_home/ create-if-missing, never clear

Nach Siril:
  WORK ──MeLE liest SMB──► MeLE ──MeLE schreibt SMB──► ARCHIVE
        (results + fehlende Master; deny siril_home)
```

---

## Speicherorte & Config

```yaml
local_capture_root: C:/Astro/Capture/Mele
archive_root: //NAS/Astro/Capture/Mele
work_transfer_root: //NOTEBOOK/AstroWork/Mele
work_local_root: D:/Astro/Work/Mele
siril_home_dirname: siril_home
```

| Setting | Bedeutung |
|---------|-----------|
| `work_transfer_root` | UNC Copy-Ziel vom MeLE |
| `work_local_root` | Siril-Anzeige-Pfad auf dem Notebook |
| `siril_home_dirname` | MeLE-Konvention für Siril-Home |

Struktur: `{root}/{ObjectName}/{YYYY-MM-DD}/s#####/…`

**RAW:** `.RW2` = Master unverändert. FITS/JPEG/Preview/Results = abgeleitet.

---

## Datenmodell

### Session-Felder

| Feld | Bedeutung |
|------|-----------|
| `lifecycle_status` | `open \| capturing \| closed` |
| `session_start_utc` / `session_end_utc` | Wetter-/Korrelationsfenster |
| `work_transfer_path` / `work_local_path` | Dual-Pfad |
| `archive_completeness` | `none \| partial \| complete \| stale` |
| `manifest_revision` | letzte bekannte Quell-Revision |
| `weather_export_status` | `none \| ok \| partial \| unavailable` |
| `object_id` | Mehrnacht-Platzhalter |
| `equipment_profile_id` | optional |

### Transfer-Jobs

| Feld | Werte |
|------|--------|
| `kind` | `capture_to_archive` \| `capture_to_work` \| `work_to_archive` |
| `status` | `queued \| copying \| verifying \| completed \| failed` |
| `completeness` | `partial \| full` (bezogen auf Quell-Snapshot zum Job-Zeitpunkt) |
| `manifest_revision` | Revision dieses Snapshots |
| `progress` / `error` / `log_path` | … |

Keine parallelen Jobs Session×Ziel. `completed` erst nach Verify. Originale bei Fehler unverändert.

---

## Transferintegrität

Siehe S0.2. Kurz:

1. Keine wachsenden Dateien.
2. Keine parallelen Jobs Session×Ziel.
3. Resume erlaubt.
4. Hash-Conflict → fail, kein silent overwrite.
5. CAPTURE→ARCHIVE löscht/überschreibt keine ARCHIVE-`results/`.
6. Free-space-Check vor Start.
7. Dauerhaftes Transfer-Log.

---

## 1. Wetter pro Session

### In Scope

1. `session_start_utc` / `session_end_utc` speichern.
2. Export bei CLOSE und **jederzeit erneut** bei `CLOSED`:

```text
{session}/weather/
  weather.csv
  weather-summary.json
```

3. Quelle: `GET /api/history?since={start}&limit=…` (+ Pagination / Client-`until`-Filter laut S0.3).
4. CSV-Felder aus vorhandenen Samples (temp, humidity, dewpoint, wind, pressure, rain, …).
5. Summary: gaps, `export_status`, Zeitfenster, sample_count.
6. Re-Export: Fenster ersetzen (idempotent, keine Duplikat-Zeilen).
7. Capture/Close scheitert nicht an Wetter-Offline.

### Out of Scope

- Zweite Wetter-DB in MeLE
- weather_server-Schema-Umbau (optional `until=` später)
- Journal ersetzen / Guiding mischen

### Akzeptanz

- **W1–W4** wie zuvor, plus:
- **W5:** Re-Export nach `CLOSED` ohne Lifecycle zurückzusetzen.
- **W6:** Client filtert korrekt bis `session_end_utc` trotz fehlendem API-`until`.

---

## 2. Push WORK (CAPTURE → Notebook)

Siehe Rev. 2; plus Partial vs. Full laut S0.1.  
`siril_home/` / `results/`: create-if-missing, **never clear** on re-push.  
UI zeigt `work_local_root`-Pfad.

---

## 3. Push ARCHIVE (CAPTURE → NAS)

Verified Copy; Partial während CAPTURING möglich; `archive_completeness=complete` nur nach S0.1.  
Results am Archiv schützen.

---

## 4. Work → Archiv (schlank)

MeLE-Doppel-Hop (S0.4). Allow: fehlende Master + `results/` + weather/meta. Deny: `siril_home/`. Manifest+Verify.

---

## 5. Remove (v1)

Nur DB / CAPTURE / WORK — **kein NAS-Delete**.  
Path-Guards inkl. Junction/Symlink/UNC.  
CAPTURE-Löschung empfohlen erst nach `archive_completeness=complete`.  
DB-Pfade nicht vor physischem Delete verwerfen.

---

## 6. UI-Skizze

- Session schließen (NINA-idle-Check)
- → Work / → Archiv / Work→Archiv
- Wetter erneut exportieren
- Entfernen… (ohne NAS)
- Prefs: Dual-WORK-Pfade, archive_root
- Transfer-Job-Status + Log

---

## Implementierungsreihenfolge

| Schritt | Inhalt | Status |
|---------|--------|--------|
| **S0** | Architektur + 4 Präzisierungen + Indoor-Tests S0-T* | **abgeschlossen (Spec)** |
| **S1** | Config, Lifecycle, Transfer-Jobs, Manifest-Schema | **implementiert** (ohne Copy/Delete) |
| **S2** | Wetterexport (history+since, Re-Export) | **implementiert** |
| **S3** | CAPTURE → WORK | **implementiert** |
| **S4** | CAPTURE → ARCHIVE | **implementiert** |
| **S5** | WORK → ARCHIVE (Doppel-Hop) | **implementiert** |
| **S6** | Sichere Bereinigung CAPTURE/WORK | **implementiert** |

---

## Risiken & Mitigation

| Risiko | Mitigation |
|--------|------------|
| „Fertig“ während NINA noch schreibt | Close-Guard + Partial ≠ complete |
| Manifest drift | revision + stale completeness |
| History ohne until / Limit 5000 | Client-Filter + Pagination |
| Doppel-Hop langsam/bricht | Verify, Resume, Log; S0-T7 |
| SMB-Rechte Dienst-User | S0-T1 |
| NAS-Delete | nicht in v1 |

---

## Explizit später / nicht in v1

- NAS-Löschung, MOVE-Default, Notebook-direkter NAS-Push
- Volle Mehrnacht-Projekt-UI
- weather_server `until=` (optional)
- Auto-Archiv, Cloud, Siril-Start aus MeLE
- Guiding in Session-Ordner (Phase 1.5)
- Session als komplette Analyse-Einheit (RW2+Wetter+Guiding+Siril+Final) — Architektur vorbereitet, nicht Scope v1

---

## Agent-Arbeitsanweisung

1. S0 ist Spec-SoT — **kein Code bis S1 freigegeben**.
2. Bestehende NINA-/PHD2-/weather_server-Architektur nicht unnötig ändern.
3. S1: Datenmodell + Config gemäß diesem Doc.
4. Pro Schritt Indoor-Tests; Transfers immer Manifest+SHA-256.
5. Wetter: vorhandenen `/api/history` nutzen; Re-Export nach CLOSED.
6. `work_to_archive` = MeLE liest WORK-UNC, schreibt ARCHIVE-UNC.
