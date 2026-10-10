# Starts one mele_app in the interactive session.
# If TCP 8082 is already open, the existing process is left alone.
# Waits briefly for Python and the repo, then stays attached to that one process.
# No restart loop: a later crash stays down until the next logon. NINA, SynScan and PHD2 are not started.

$ErrorActionPreference = "Stop"
. "$PSScriptRoot\AstroVr.Common.ps1"

$log = Join-Path $AstroVrRepo "data\vr-boot\mele-app.log"
Initialize-AstroVrLog -Path $log

$module = Join-Path $AstroVrRepo "app_mele\__main__.py"
$deadline = (Get-Date).AddMinutes(3)
$ready = $false
while ((Get-Date) -lt $deadline) {
    if ((Test-Path -LiteralPath $AstroVrPython) -and (Test-Path -LiteralPath $module)) {
        $ready = $true
        break
    }
    Write-AstroVrLog $log "waiting for python or repo"
    Start-Sleep -Seconds 10
}
if (-not $ready) {
    Write-AstroVrLog $log "python or repo still missing: $AstroVrPython / $module"
    exit 1
}

if (Get-AstroVrListener -Port 8082) {
    Write-AstroVrLog $log "TCP 8082 already listening. Existing process kept. No second app."
    exit 0
}

Write-AstroVrLog $log "starting $AstroVrPython -m app_mele in $AstroVrRepo"
Set-Location -LiteralPath $AstroVrRepo
& $AstroVrPython -m app_mele
$code = $LASTEXITCODE
Write-AstroVrLog $log "app exited code=$code"
exit $code
