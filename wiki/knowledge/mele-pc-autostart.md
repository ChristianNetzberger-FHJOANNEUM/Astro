# MeLE-PC Autostart (Windows)

> Quelle: Chat mit Cursor, 2026-10-05 · Thema: weather_server Autostart, NINA/SynScan/MeLE nach Stromausfall
> Beschluss 2026-10-09, noch nicht implementiert: [MeLE Autostart und Entwicklungsbetrieb](mele-autostart-dev-prod-spec.md)

Dieses Kapitel beschreibt, **welche Prozesse heute** auf dem MeLE-PC automatisch starten, was bei einem **12‑V-/Netzausfall** passiert, und wie man beim **Weiterentwickeln mit Cursor** laufende Instanzen sauber stoppt. Die beschlossene Soll-Architektur (Bootstrap, DEV/PROD) steht in der verlinkten Spec.

App-Bedienung (Buttons NINA/SynScan in der UI) bleibt unter **Hilfe**. Hier geht es um den PC-Betrieb.

## Kurzantwort

| Komponente | Autostart sinnvoll? | Stand |
|---|---|---|
| `weather_server` | Ja — Logger soll dauerhaft laufen | **eingebaut** (Task `Astro-weather_server`) |
| Technitium DNS | Ja — Namensauflösung für die Quest | Windows-Dienst, automatisch. Details: [Astro-VR Dauerbetrieb](astro-vr-dauerbetrieb.md) |
| Caddy (HTTPS 8443) | Ja — Quest-URL nach Reboot | Skript `AstroVR-Caddy`. [Dauerbetrieb](astro-vr-dauerbetrieb.md) |
| MeLE-App (`app_mele`) | Ja — Oberfläche nach der Anmeldung | **eingebaut**, Task `Astro-mele_app` bei Anmeldung von Chris |
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

## MeLE-App als Autostart

Aufgabe `Astro-mele_app`, ausgelöst bei der Anmeldung von Chris, 30 Sekunden Verzögerung. Sie startet `deployment/windows/Start-AstroVrMeleApp.ps1`. Der Starter ruft

```text
C:\Astro\Git\Astro\.venv\Scripts\python.exe -m app_mele
```

im Arbeitsverzeichnis `C:\Astro\Git\Astro` auf. Der System-Python `C:\Python\310\python.exe` hat kein NiceGUI und wird dafür nicht verwendet. Ist Port 8082 schon belegt, startet er keine zweite Instanz.

Die Aufgabe hat kein `RestartOnFailure`. Endet der Python-Prozess, bleibt Port 8082 bis zur nächsten Anmeldung frei. Das Schließen des Browserfensters beendet das Backend nicht.

NINA, SynScan und PHD2 startet diese Aufgabe nicht. Laufen sie, wurden sie über die Knöpfe in der App losgelöst gestartet (`DETACHED_PROCESS`) und überleben das Beenden der App. `weather_server` ist ein eigener Task.

`--no-show`, `astro-dev.ps1` und `astro-prod.ps1` sind weiterhin nur beschlossen, nicht gebaut: [MeLE Autostart und Entwicklungsbetrieb](mele-autostart-dev-prod-spec.md).

In der Toolbar steht **Beenden**. Der Knopf öffnet eine Bestätigung und ruft dann nur `app.shutdown()` für diesen Python-Prozess auf. NINA, SynScan, PHD2 und `weather_server` bleiben. Die nächste Anmeldung startet die App wieder. Port 8082 ist im Hausnetz offen, deshalb kann auch das iPad den Knopf erreichen. Zum Entwickeln über einen Neustart hinweg die Aufgabe zusätzlich aussetzen, siehe unten.

## 12‑V-Ausfall — starten alle Tools wieder von selbst?

| Was passiert | Wirkung |
|---|---|
| PC war aus / Neustart nach Stromwiederkehr | Windows bootet → Benutzeranmeldung (Auto-Login vorausgesetzt) → **At-logon-Tasks** starten erneut |
| Nur 12 V an Montierung/Kamera weg, PC blieb an | Windows-Tasks starten **nicht** neu; NINA/SynScan bleiben im alten Zustand und müssen manuell oder per MeLE-Button neu verbunden/gestartet werden |
| PC aus, kein Auto-Login | Tasks starten erst nach manueller Anmeldung |

**Fazit:** Mit Auto-Login kommen `weather_server` und die MeLE-App nach einem kompletten PC-Neustart wieder, sobald Chris angemeldet ist. NINA und SynScan starten dadurch nicht. Ein reiner 12‑V-Drop am Scope ohne PC-Reboot reaktiviert nichts automatisch.

## Beim Entwickeln mit Cursor: laufende Instanz stoppen

### MeLE-App (Port 8082)

Nur Prozesse, deren Kommandozeile `-m app_mele` enthält. NINA, SynScan, PHD2 und `weather_server` bleiben laufen. Port 8082 ist danach frei, bis sich Chris neu anmeldet.

```powershell
Get-CimInstance Win32_Process -Filter "Name = 'python.exe'" |
  Where-Object { $_.CommandLine -match '-m app_mele' } |
  ForEach-Object { Stop-Process -Id $_.ProcessId -Force }
```

Soll die App auch nach der nächsten Anmeldung aus bleiben:

```powershell
Disable-ScheduledTask -TaskName "Astro-mele_app"
```

Automatischen Start wieder einschalten:

```powershell
Enable-ScheduledTask -TaskName "Astro-mele_app"
```

`Enable-ScheduledTask` startet die laufende Sitzung nicht nach. Dafür die Aufgabe einmal ausführen oder sich neu anmelden.

`scripts\free-port-8082.ps1` beendet jeden Hörer auf Port 8082 mit `taskkill /T /F`, ohne die Kommandozeile zu prüfen. Für das gezielte Beenden der App ist der Befehl oben der richtige. Die geplante DEV/PROD-Umschaltung soll `free-port-8082.ps1` nicht aufrufen.

Danach aus Cursor, im Repo:

```powershell
.venv\Scripts\python.exe -m app_mele
```

Lief die App in einem sichtbaren Terminal: dort **Ctrl+C**. Das trifft die Autostart-Instanz nicht, die hat kein Fenster.

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
3. MeLE-App kommt mit der Anmeldung (Task `Astro-mele_app`) → Station erscheint in der Wetterzeile  
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
