# Registers three scheduled tasks. Does not start them and does not stop running processes.
# Without -Confirm this script only prints the plan and exits.
#
#   powershell -ExecutionPolicy Bypass -File deployment\windows\Register-AstroVrTasks.ps1
#   powershell -ExecutionPolicy Bypass -File deployment\windows\Register-AstroVrTasks.ps1 -Confirm

param(
    [switch]$Confirm
)

$ErrorActionPreference = "Stop"
. "$PSScriptRoot\AstroVr.Common.ps1"

$caddyLauncher = Join-Path $PSScriptRoot "Start-AstroVrCaddy.ps1"
$appLauncher = Join-Path $PSScriptRoot "Start-AstroVrMeleApp.ps1"
$certLauncher = Join-Path $PSScriptRoot "Invoke-AstroVrCertRenewal.ps1"

foreach ($path in @($caddyLauncher, $appLauncher, $certLauncher, $AstroVrCaddyExe, $AstroVrCaddyfile, $AstroVrPython)) {
    if (-not (Test-Path -LiteralPath $path)) {
        throw "missing $path"
    }
}

$ps = "powershell.exe"
$hidden = "-NoProfile -ExecutionPolicy Bypass -WindowStyle Hidden -File"

$caddyAction = New-ScheduledTaskAction -Execute $ps -Argument "$hidden `"$caddyLauncher`"" -WorkingDirectory "C:\Caddy"
$caddyTrigger = New-ScheduledTaskTrigger -AtStartup
$caddyTrigger.Delay = "PT45S"
$caddySettings = New-ScheduledTaskSettingsSet `
    -AllowStartIfOnBatteries `
    -DontStopIfGoingOnBatteries `
    -StartWhenAvailable `
    -RestartCount 5 `
    -RestartInterval (New-TimeSpan -Minutes 1) `
    -ExecutionTimeLimit ([TimeSpan]::Zero) `
    -MultipleInstances IgnoreNew
$caddyPrincipal = New-ScheduledTaskPrincipal -UserId "SYSTEM" -LogonType ServiceAccount -RunLevel Highest

$appAction = New-ScheduledTaskAction -Execute $ps -Argument "$hidden `"$appLauncher`"" -WorkingDirectory $AstroVrRepo
$appTrigger = New-ScheduledTaskTrigger -AtLogOn -User $AstroVrUser
$appTrigger.Delay = "PT30S"
$appSettings = New-ScheduledTaskSettingsSet `
    -AllowStartIfOnBatteries `
    -DontStopIfGoingOnBatteries `
    -StartWhenAvailable `
    -ExecutionTimeLimit ([TimeSpan]::Zero) `
    -MultipleInstances IgnoreNew
$appPrincipal = New-ScheduledTaskPrincipal -UserId $AstroVrUser -LogonType Interactive -RunLevel Limited

$certAction = New-ScheduledTaskAction -Execute $ps -Argument "$hidden `"$certLauncher`"" -WorkingDirectory $AstroVrRepo
$certTrigger = New-ScheduledTaskTrigger -Daily -At "09:15"
$certSettings = New-ScheduledTaskSettingsSet `
    -AllowStartIfOnBatteries `
    -DontStopIfGoingOnBatteries `
    -StartWhenAvailable `
    -ExecutionTimeLimit (New-TimeSpan -Minutes 30) `
    -MultipleInstances IgnoreNew
$certPrincipal = New-ScheduledTaskPrincipal -UserId $AstroVrUser -LogonType Interactive -RunLevel Limited

Write-Host "Plan, not yet applied:"
Write-Host ""
Write-Host "$AstroVrTaskCaddy"
Write-Host "  account:  SYSTEM, at startup, whether anyone is logged on"
Write-Host "  delay:    45 seconds"
Write-Host "  retry:    task restarts 5 times, 1 minute apart, if the launcher exits non-zero"
Write-Host "  command:  $ps $hidden `"$caddyLauncher`""
Write-Host "  note:     launcher validates the Caddyfile, retries 5 x 20s, and exits 0 when TCP 8443 is already taken"
Write-Host ""
Write-Host "$AstroVrTaskApp"
Write-Host "  account:  $AstroVrUser, interactive, at logon only"
Write-Host "  delay:    30 seconds, then the launcher waits up to 3 minutes for Python and the repo"
Write-Host "  retry:    none after the process has exited. No night-time watchdog."
Write-Host "  command:  $AstroVrPython -m app_mele"
Write-Host "  workdir:  $AstroVrRepo"
Write-Host "  note:     exits 0 when TCP 8082 is already taken. Does not start NINA, SynScan, or PHD2."
Write-Host "  limit:    the Quest URL works after this logon, not at the Windows boot screen"
Write-Host ""
Write-Host "$AstroVrTaskCert"
Write-Host "  account:  $AstroVrUser, interactive, daily 09:15, run when available"
Write-Host "  command:  $ps $hidden `"$certLauncher`""
Write-Host "  note:     reuses Posh-ACME account $AstroVrPoshAccount and the saved deSEC plugin"
Write-Host "            skips until RenewAfter; never passes -Force or plugin args"
Write-Host "            reloads Caddy only after fullchain.cer changes"
Write-Host ""
Write-Host "Running Caddy and python processes are not stopped."
Write-Host "Technitium, DNS zones, firewall, router, and the Quest are not changed."

if (-not $Confirm) {
    Write-Host ""
    Write-Host "Not registered. Review this plan, then re-run with -Confirm from an elevated PowerShell."
    exit 0
}

if (-not (Test-AstroVrAdministrator)) {
    throw "-Confirm needs an elevated PowerShell so the SYSTEM startup task can be registered."
}

$items = @(
    @{ Name = $AstroVrTaskCaddy; Action = $caddyAction; Trigger = $caddyTrigger; Settings = $caddySettings; Principal = $caddyPrincipal; Description = "Astro VR: Caddy HTTPS :8443 at startup. Keeps an existing listener." },
    @{ Name = $AstroVrTaskApp; Action = $appAction; Trigger = $appTrigger; Settings = $appSettings; Principal = $appPrincipal; Description = "Astro VR: mele_app at logon of ASTRO\Chris. One instance on port 8082." },
    @{ Name = $AstroVrTaskCert; Action = $certAction; Trigger = $certTrigger; Settings = $certSettings; Principal = $certPrincipal; Description = "Astro VR: daily Posh-ACME renewal check for vr.netzberger.at. No forced issuance." }
)

foreach ($item in $items) {
    $existing = Get-ScheduledTask -TaskName $item.Name -ErrorAction SilentlyContinue
    if ($existing) {
        Write-Host "Replacing task definition only: $($item.Name). Process not stopped."
    } else {
        Write-Host "Creating task: $($item.Name). Not started."
    }
    Register-ScheduledTask `
        -TaskName $item.Name `
        -Action $item.Action `
        -Trigger $item.Trigger `
        -Settings $item.Settings `
        -Principal $item.Principal `
        -Description $item.Description `
        -Force | Out-Null
}

Write-Host ""
Write-Host "Registered. Not started. Next check: deployment\windows\Get-AstroVrStatus.ps1"
Write-Host "A reboot test waits for a separate approval."
