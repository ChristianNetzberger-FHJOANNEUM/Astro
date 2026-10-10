# MeLE-PC Autostart (Windows)

> Quelle: Chat mit Cursor, 2026-10-05 · Thema: weather_server Autostart, NINA/SynScan/MeLE nach Stromausfall
> Beschluss 2026-10-09, noch nicht implementiert: [MeLE Autostart und Entwicklungsbetrieb](mele-autostart-dev-prod-spec.md)

Dieses Kapitel beschreibt, **welche Prozesse heute** auf dem MeLE-PC automatisch starten, was bei einem **12‑V-/Netzausfall** passiert, und wie man beim **Weiterentwickeln mit Cursor** laufende Instanzen sauber stoppt. Die beschlossene Soll-Architektur (Bootstrap, DEV/PROD) steht in der verlinkten Spec.

App-Bedienung (Buttons NINA/SynScan in der UI) bleibt unter **Hilfe**. Hier geht es um den PC-Betrieb.

## Kurzantwort

| Komponente | Autostart sinnvoll? | Stand |
|---|---|---|
| `weather_server` | Ja — Logger soll dauerhaft laufen | **eingebaut** (Task Scheduler) — einziger Astro-Task |
| Technitium DNS | Ja — Namensauflösung für die Quest | Windows-Dienst, automatisch. Details: [Astro-VR Dauerbetrieb](astro-vr-dauerbetrieb.md) |
| Caddy (HTTPS 8443) | Ja — Quest-URL nach Reboot | Skript `AstroVR-Caddy`, noch nicht registriert. [Dauerbetrieb](astro-vr-dauerbetrieb.md) |
| MeLE-App (`app_mele`) | Optional — UI nach Login | Skript `Astro-mele_app` bei Anmeldung, noch nicht registriert |
| NINA / SynScan Pro | Vorsichtig — brauchen USB/ASCOM/Montierung | Nicht empfohlen als blinder Boot-Start; besser manuell oder verzögert |

Details zu Port **8765**, manuellem Start/Stop, SQLite-Pfad und Client-Zugriff: [weather_server](weather-server.md).

MeLE leitet daraus **Live Conditions / Safety** ab (`mele/weather_safety.py`): Zustände `LIVE|STALE|OFFLINE` und `SAFE|CAUTION|UNSAFE|UNKNOWN`. Config: `weather_safety` in `configs/mele.yaml`. Panel in der Haupt-UI. Kein direkter SQLite-Zugriff.

**Boot ≠ MeLE-App:** Ein Autostart-Task startet mit der **Windows-Benutzeranmeldung** (nach Boot bzw. Auto-Login). Die MeLE-App muss dafür **nicht** laufen. Umgekehrt startet die MeLE-App **nicht** automatisch NINA/SynScan beim Boot — nur per UI-Button (oder eigener Task).

## weather_server (implementiert)

Eigenständiger Prozess: Ecowitt Pull → SQLite → REST + Dashboard auf Port **8765**.

### Installieren / sofort starten

Vorher manuell gestarteten `weather_server` beenden (Terminal Ctrl+C), sonst erkennt der Launcher „läuft bereits“ und der Task beendet sich sofort.

```powershell
# Task registrieren und optional sofort starten
powershell -ExecutionPolicy Bypass -File scripts\install-weather-server-autostart.ps1 -StartNow
```

Nur registrieren (Start beim nächsten Login):

```powershell
powershell -ExecutionPolicy Bypass -File scripts\install-weather-server-autostart.ps1
```

### Entfernen

```powershell
powershell -ExecutionPolicy Bypass -File scripts\uninstall-weather-server-autostart.ps1 -StopProcess
```

Ohne `-StopProcess` bleibt ein schon laufender Prozess bestehen; nur der geplante Task wird gelöscht.

### Technik

| Punkt | Wert |
|---|---|
| Task-Name | `Astro-weather_server` |
| Trigger | Bei Anmeldung von `$env:USERNAME` |
| Launcher | `scripts/weather-server.ps1` |
| Flags | `--no-browser` (kein Dashboard-Tab im Hintergrund) |
| Log | `data/weather_server/autostart.log` |
| API/UI | http://127.0.0.1:8765/ |

Doppelstart-Schutz: Launcher prüft, ob schon ein `python … weather_server` läuft.

## NINA und SynScan Pro — kann man das analog machen?

**Ja technisch** (ebenfalls geplanter Task „At logon“ mit Pfad aus `configs/mele.yaml`: `nina_exe`, `synscan_pro_exe`). Die MeLE-App startet sie heute nur auf Knopfdruck (`mele.nina_launch` / `mele.synscan`) und prüft „schon laufend“.

**Aber:** Nach einem Kaltstart brauchen Kamera, Montierung und USB oft **einige Sekunden bis Minuten**. Ein sofortiger Autostart von NINA kann zu fehlenden Geräten oder ASCOM-Fehlern führen. Sinnvoller:

1. Windows + Netzwerk stehen (Auto-Login).
2. `weather_server` startet (bereits so).
3. Optional MeLE-App (UI).
4. NINA / SynScan **manuell** oder mit **Verzögerung** (z. B. Task „1–2 min nach Anmeldung“) und nur wenn die Hardware bereit ist.

Empfehlung: NINA/SynScan **nicht** blind parallel zu weather_server auf „sofort bei Login“ setzen, solange der 12‑V-/USB-Stack nicht stabil hochgefahren ist.

## MeLE-App selbst als Autostart?

Möglich analog zu weather_server, z. B. Task:

```text
.venv\Scripts\python.exe -m app_mele
```

Dann wäre die UI nach Login unter http://127.0.0.1:8082/ erreichbar (Port aus `configs/mele.yaml`: `ui_port`).

**Entwicklungskonflikt:** Wenn die App immer per Task läuft, blockiert Port 8082 den manuellen Start aus Cursor. Deshalb:

- Autostart nur auf dem **Beobachtungs-/Produktions-Login**, oder
- Task vor dem Entwickeln deaktivieren/stoppen (siehe unten).

Ein Install-Skript für die App gibt es noch nicht. Der Beschluss dafür (Task `Astro-mele_app`, Marker `--no-show`, Umschaltung DEV/PROD) steht in [MeLE Autostart und Entwicklungsbetrieb](mele-autostart-dev-prod-spec.md). Diesen Task erst nach Freigabe anlegen.

## 12‑V-Ausfall — starten alle Tools wieder von selbst?

| Was passiert | Wirkung |
|---|---|
| PC war aus / Neustart nach Stromwiederkehr | Windows bootet → Benutzeranmeldung (Auto-Login vorausgesetzt) → **At-logon-Tasks** starten erneut |
| Nur 12 V an Montierung/Kamera weg, PC blieb an | Windows-Tasks starten **nicht** neu; NINA/SynScan bleiben im alten Zustand und müssen manuell oder per MeLE-Button neu verbunden/gestartet werden |
| PC aus, kein Auto-Login | Tasks starten erst nach manueller Anmeldung |

**Fazit:** Mit Auto-Login + registriertem weather_server-Task kommt der Logger nach einem kompletten PC-Neustart wieder. NINA/SynScan/MeLE nur, wenn dafür ebenfalls Tasks existieren — und Hardware-Bereitschaft ist dann trotzdem zu prüfen. Ein reiner 12‑V-Drop am Scope ohne PC-Reboot reaktiviert nichts automatisch.

## Beim Entwickeln mit Cursor: laufende Instanz stoppen

### MeLE-App (Port 8082)

Im Terminal der laufenden App: **Ctrl+C**.

Oder Port freigeben (beendet den Listener inkl. Kindprozesse):

```powershell
powershell -ExecutionPolicy Bypass -File scripts\free-port-8082.ps1
```

Danach wieder manuell:

```powershell
.venv\Scripts\Activate
python -m app_mele
```

### weather_server (Port 8765)

- Manuell gestartet: Ctrl+C im Terminal.
- Per Autostart-Task: Task beenden und optional Prozess killen:

```powershell
Stop-ScheduledTask -TaskName Astro-weather_server
powershell -ExecutionPolicy Bypass -File scripts\uninstall-weather-server-autostart.ps1 -StopProcess
# oder Task behalten, nur Prozess:
Get-CimInstance Win32_Process -Filter "Name='python.exe'" |
  Where-Object { $_.CommandLine -match 'weather_server' } |
  ForEach-Object { Stop-Process -Id $_.ProcessId -Force }
```

Nach dem Entwickeln Autostart wieder setzen:

```powershell
powershell -ExecutionPolicy Bypass -File scripts\install-weather-server-autostart.ps1 -StartNow
```

### NINA / SynScan

Über die MeLE-Buttons starten (starten nicht doppelt, wenn schon laufend). Beenden über die jeweilige App oder Task-Manager — nicht über MeLE.

## Checkliste Beobachtungsabend (Empfehlung)

1. PC an, Windows + Auto-Login  
2. `weather_server` läuft (Task) → http://127.0.0.1:8765/ kurz prüfen  
3. MeLE starten (manuell oder später Autostart) → Station erscheint in der Wetterzeile  
4. 12 V / USB / Montierung bereit  
5. SynScan Pro, dann NINA (MeLE-Buttons)  
6. Imaging wie gewohnt  

## Verwandte Dateien

- `scripts/weather-server.ps1`
- `scripts/install-weather-server-autostart.ps1`
- `scripts/uninstall-weather-server-autostart.ps1`
- `scripts/free-port-8082.ps1`
- `configs/weather_server.yaml`
- `configs/mele.yaml` → `local_weather`, `nina_exe`, `synscan_pro_exe`
- `weather_server/README.md`
