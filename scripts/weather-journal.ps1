# Stündliches GeoSphere-Forecast-Journal (unabhaengig von app_mele).
# Task Scheduler: alle 1 Stunde, dieses Script starten.
# Voraussetzung: latitude_deg / longitude_deg in configs/mele.yaml.

$ErrorActionPreference = "Stop"
$Root = Split-Path -Parent $PSScriptRoot
Set-Location $Root

$Python = Join-Path $Root ".venv\Scripts\python.exe"
if (-not (Test-Path $Python)) {
    $Python = "python"
}

& $Python -m mele weather-journal @args
exit $LASTEXITCODE
