# Removes the three Astro-VR scheduled tasks. Does not stop Caddy, python, or Technitium.
# Without -Confirm this script only prints the plan and exits.
#
#   powershell -ExecutionPolicy Bypass -File deployment\windows\Unregister-AstroVrTasks.ps1 -Confirm

param(
    [switch]$Confirm
)

$ErrorActionPreference = "Stop"
. "$PSScriptRoot\AstroVr.Common.ps1"

$names = @($AstroVrTaskCaddy, $AstroVrTaskApp, $AstroVrTaskCert)
foreach ($name in $names) {
    $existing = Get-ScheduledTask -TaskName $name -ErrorAction SilentlyContinue
    if ($existing) {
        Write-Host "would remove task $name (running processes stay)"
    } else {
        Write-Host "task $name is not registered"
    }
}

if (-not $Confirm) {
    Write-Host "Not changed. Re-run with -Confirm to unregister."
    exit 0
}

if (-not (Test-AstroVrAdministrator)) {
    throw "-Confirm needs an elevated PowerShell."
}

foreach ($name in $names) {
    $existing = Get-ScheduledTask -TaskName $name -ErrorAction SilentlyContinue
    if ($existing) {
        Unregister-ScheduledTask -TaskName $name -Confirm:$false
        Write-Host "removed $name"
    }
}

Write-Host "Processes were not stopped. The manually started Caddy and app keep serving."
