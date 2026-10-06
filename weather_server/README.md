# weather_server

Eigenständige App: pollt die Ecowitt-GW1200-Live-API, speichert Samples in SQLite,
liefert REST und ein NiceGUI-Dashboard. Läuft **ohne** MeLE-App.

## Start

```bash
pip install -r requirements.txt
python -m weather_server
```

Öffnet http://127.0.0.1:8765/ (Dashboard). REST bleibt unter `/api/*`.

```bash
python -m weather_server --once          # einmaliger Abruf, kein Server
python -m weather_server --no-browser    # Server ohne Browser-Tab
python -m weather_server --api-only      # nur FastAPI, ohne NiceGUI
```

Defaults: Gateway `http://192.168.0.149`, Poll alle 30 s, Port `8765`.
Config: [`configs/weather_server.yaml`](../configs/weather_server.yaml).

## Dashboard

Zweispaltiges Layout: Messwert-Gruppen links, Verlauf rechts.
Chart-Größen und Sample-Anzahl per Checkbox/Select wählbar; Einstellungen
bleiben über `app.storage.user` sessionpersistent (Browser-Cookie).
Auto-Refresh alle 5 s.

## API

| Endpoint | Beschreibung |
|---|---|
| `GET /api/current` | letzter Sample |
| `GET /api/history?limit=100&since=…` | Historie (neueste zuerst) |
| `GET /api/status` | Collector-/DB-Status |
| `GET /healthz` | liveness |

## Datenquelle

`GET {gateway}/get_livedata_info` — metrisches JSON (`common_list` Hex-IDs, `piezoRain`, `wh25`).
Kein Login. MeLE Custom-Server-Push bleibt unberührt und wird hier nicht genutzt.

## Autostart (Windows)

Läuft **unabhängig von der MeLE-App**, sobald der MeLE-Benutzer sich anmeldet
(nach Boot / Auto-Login). Das ist kein klassischer Windows-Dienst vor der Anmeldung,
sondern ein geplanter Task „At logon“.

```powershell
powershell -ExecutionPolicy Bypass -File scripts\install-weather-server-autostart.ps1 -StartNow
```

Entfernen:

```powershell
powershell -ExecutionPolicy Bypass -File scripts\uninstall-weather-server-autostart.ps1 -StopProcess
```

Manueller Start ohne Browser: `scripts\weather-server.ps1`  
Log: `data/weather_server/autostart.log`

MeLE ist Consumer (`local_weather` in `configs/mele.yaml`).
