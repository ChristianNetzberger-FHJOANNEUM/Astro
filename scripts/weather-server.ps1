# Startet weather_server im Vordergrund (fuer Task Scheduler / manuell).
# Ohne Browser-Tab — geeignet fuer Autostart im Hintergrund.
#
# Installation Autostart:
#   powershell -ExecutionPolicy Bypass -File scripts\install-weather-server-autostart.ps1

$ErrorActionPreference = "Stop"
$Root = Split-Path -Parent $PSScriptRoot
Set-Location $Root

$Python = Join-Path $Root ".venv\Scripts\python.exe"
if (-not (Test-Path $Python)) {
    $Python = "python"
}

# Doppelstart vermeiden (z.B. manueller Start + Task)
$running = Get-CimInstance Win32_Process -Filter "Name = 'python.exe'" -ErrorAction SilentlyContinue |
    Where-Object { $_.CommandLine -and ($_.CommandLine -match 'weather_server') }
if ($running) {
    Write-Host "weather_server laeuft bereits (PID $($running[0].ProcessId))."
    exit 0
}

$logDir = Join-Path $Root "data\weather_server"
New-Item -ItemType Directory -Force -Path $logDir | Out-Null
$logFile = Join-Path $logDir "autostart.log"
$stamp = Get-Date -Format "yyyy-MM-dd HH:mm:ss"
Add-Content -Path $logFile -Value "$stamp starting weather_server ($Python)"

& $Python -m weather_server --no-browser @args
$code = $LASTEXITCODE
$stamp = Get-Date -Format "yyyy-MM-dd HH:mm:ss"
Add-Content -Path $logFile -Value "$stamp exited code=$code"
exit $code
