# weather_server (Port, Start/Stop, DB, Clients)

> Quelle: Chat mit Cursor, 2026-10-05 · Stand: nur `weather_server` hat Autostart
> Geplanter App-Autostart (noch nicht gebaut, startet diesen Dienst nicht): [MeLE Autostart und Entwicklungsbetrieb](mele-autostart-dev-prod-spec.md)

## Was startet automatisch?

**Zurzeit nur `weather_server`.**  
NINA, SynScan Pro und die MeLE-App (`app_mele`) starten **nicht** automatisch. Siehe auch [MeLE-PC Autostart](mele-pc-autostart.md).

## Port & Adressen

| Was | Wert |
|---|---|
| HTTP-Port | **8765** |
| Bind | `0.0.0.0` (LAN erreichbar) |
| Lokal | http://127.0.0.1:8765/ (NiceGUI-Dashboard) |
| Config | `configs/weather_server.yaml` → `api_port: 8765` |

### REST (für Clients)

| Endpoint | Bedeutung |
|---|---|
| `GET /api/current` | letzter Sample |
| `GET /api/history?limit=100` | Historie (neueste zuerst) |
| `GET /api/status` | Collector-/DB-Status |
| `GET /healthz` | liveness |

## Manuell starten

Im Repo-Root (mit venv):

```powershell
.venv\Scripts\Activate
python -m weather_server
```

Ohne Browser-Tab (wie Autostart):

```powershell
python -m weather_server --no-browser
```

Oder über den Launcher:

```powershell
powershell -ExecutionPolicy Bypass -File scripts\weather-server.ps1
```

Einmaliger Abruf ohne Dauerprozess:

```powershell
python -m weather_server --once
```

## Stoppen (zum Weiterentwickeln)

**Manuell gestartet:** im Terminal **Ctrl+C**.

**Per Autostart-Task laufend:**

```powershell
Stop-ScheduledTask -TaskName Astro-weather_server

Get-CimInstance Win32_Process -Filter "Name='python.exe'" |
  Where-Object { $_.CommandLine -match 'weather_server' } |
  ForEach-Object { Stop-Process -Id $_.ProcessId -Force }
```

Task deinstallieren und Prozess beenden:

```powershell
powershell -ExecutionPolicy Bypass -File scripts\uninstall-weather-server-autostart.ps1 -StopProcess
```

Danach Port 8765 frei — erneut manuell mit `python -m weather_server` starten.

Autostart wieder aktivieren:

```powershell
powershell -ExecutionPolicy Bypass -File scripts\install-weather-server-autostart.ps1 -StartNow
```

## Datenbank — wo liegt sie?

| | |
|---|---|
| Relativer Pfad (Config) | `data/weather_server/weather.sqlite` |
| Absolut (dieses Repo) | `C:\Astro\Git\Astro\data\weather_server\weather.sqlite` |
| Config-Key | `configs/weather_server.yaml` → `db_path` |

Der Ordner `data/` ist gitignored; die SQLite-Datei bleibt lokal auf dem MeLE-PC.

Tabelle (Kern): `weather_samples` — u. a. `recorded_at`, `temp_c`, `humidity_pct`, `dewpoint_c`, `dewpoint_margin_c`, Wind, Druck, Regen, Solar, `payload_json`.

Autostart-Log daneben: `data/weather_server/autostart.log`.

## Wie greift ein Client (z. B. MeLE) zu?

**Nicht** direkt auf die SQLite-Datei zugreifen.  
`weather_server` ist die Source of Truth; Clients holen Daten per **HTTP**.

### MeLE-App (eingebaut)

- Config: `configs/mele.yaml` → `local_weather.server_url: http://127.0.0.1:8765`
- Pull: `GET http://127.0.0.1:8765/api/current` (Modul `mele/weather_server_client.py`)
- Anzeige: Wetterzeile + Block „Lokale Station“ auf der Wetter-Seite
- Optional Journal: MeLE schreibt Beobachtungen nach `data/weather/journal/…` (eigenes JSONL, **nicht** dieselbe SQLite)
- Proxy in MeLE: `GET /weather/station` (leitet auf weather_server weiter)

Beispiel roh:

```powershell
Invoke-RestMethod http://127.0.0.1:8765/api/current
Invoke-RestMethod "http://127.0.0.1:8765/api/history?limit=20"
Invoke-RestMethod http://127.0.0.1:8765/api/status
```

Antwort `/api/current` (vereinfacht): `{ "ok": true, "sample": { "id": …, "temp_c": …, "dewpoint_margin_c": … } }`.

### Andere Clients

Jeder Prozess im LAN kann dieselbe REST-API nutzen (`http://<mele-pc>:8765/api/…`). SQLite-Pfad nur für Betrieb/Backup des Servers, nicht für App-Logik.

## Verwandte Dateien

- `weather_server/` — App
- `configs/weather_server.yaml`
- `configs/mele.yaml` → `local_weather`
- `mele/weather_server_client.py`
- `scripts/weather-server.ps1`, `install-weather-server-autostart.ps1`, `uninstall-weather-server-autostart.ps1`
- `weather_server/README.md`
