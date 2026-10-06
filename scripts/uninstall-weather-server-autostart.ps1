# Entfernt den Geplanten Task Astro-weather_server.
#
#   powershell -ExecutionPolicy Bypass -File scripts\uninstall-weather-server-autostart.ps1
#   powershell -ExecutionPolicy Bypass -File scripts\uninstall-weather-server-autostart.ps1 -StopProcess

param(
    [switch]$StopProcess
)

$ErrorActionPreference = "Stop"
$TaskName = "Astro-weather_server"

$existing = Get-ScheduledTask -TaskName $TaskName -ErrorAction SilentlyContinue
if ($existing) {
    Unregister-ScheduledTask -TaskName $TaskName -Confirm:$false
    Write-Host "Task entfernt: $TaskName"
} else {
    Write-Host "Kein Task namens $TaskName gefunden."
}

if ($StopProcess) {
    Get-CimInstance Win32_Process -Filter "Name = 'python.exe'" -ErrorAction SilentlyContinue |
        Where-Object { $_.CommandLine -and ($_.CommandLine -match 'weather_server') } |
        ForEach-Object {
            Stop-Process -Id $_.ProcessId -Force -ErrorAction SilentlyContinue
            Write-Host "Prozess beendet: PID $($_.ProcessId)"
        }
}
