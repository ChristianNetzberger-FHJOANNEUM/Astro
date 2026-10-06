# Registriert weather_server als Windows Geplanter Task (Autostart bei Benutzeranmeldung).
# Laeuft nach Boot, sobald die MeLE-Benutzer-Session startet (nicht abhaengig von app_mele).
#
#   powershell -ExecutionPolicy Bypass -File scripts\install-weather-server-autostart.ps1
#   powershell -ExecutionPolicy Bypass -File scripts\install-weather-server-autostart.ps1 -StartNow

param(
    [switch]$StartNow
)

$ErrorActionPreference = "Stop"
$Root = Split-Path -Parent $PSScriptRoot
$Launcher = Join-Path $PSScriptRoot "weather-server.ps1"
$TaskName = "Astro-weather_server"

if (-not (Test-Path $Launcher)) {
    throw "Launcher fehlt: $Launcher"
}

$arg = "-NoProfile -ExecutionPolicy Bypass -WindowStyle Hidden -File `"$Launcher`""
$action = New-ScheduledTaskAction -Execute "powershell.exe" -Argument $arg -WorkingDirectory $Root
$trigger = New-ScheduledTaskTrigger -AtLogOn -User $env:USERNAME
$settings = New-ScheduledTaskSettingsSet `
    -AllowStartIfOnBatteries `
    -DontStopIfGoingOnBatteries `
    -StartWhenAvailable `
    -RestartCount 5 `
    -RestartInterval (New-TimeSpan -Minutes 1) `
    -ExecutionTimeLimit ([TimeSpan]::Zero) `
    -MultipleInstances IgnoreNew

$principal = New-ScheduledTaskPrincipal -UserId $env:USERNAME -LogonType Interactive -RunLevel Limited
$description = "Astro weather_server: Ecowitt Pull → SQLite → REST/Dashboard (:8765). Start bei Anmeldung."

Register-ScheduledTask `
    -TaskName $TaskName `
    -Action $action `
    -Trigger $trigger `
    -Settings $settings `
    -Principal $principal `
    -Description $description `
    -Force | Out-Null

Write-Host "Task registriert: $TaskName"
Write-Host "  Trigger: bei Anmeldung von $env:USERNAME"
Write-Host "  Launcher: $Launcher"
Write-Host "  Dashboard/API: http://127.0.0.1:8765/"
Write-Host "  Log: $Root\data\weather_server\autostart.log"

if ($StartNow) {
    Start-ScheduledTask -TaskName $TaskName
    Start-Sleep -Seconds 2
    $info = Get-ScheduledTaskInfo -TaskName $TaskName
    Write-Host "Task gestartet (LastTaskResult=$($info.LastTaskResult))."
}

Write-Host ""
Write-Host "Entfernen: powershell -ExecutionPolicy Bypass -File scripts\uninstall-weather-server-autostart.ps1"
