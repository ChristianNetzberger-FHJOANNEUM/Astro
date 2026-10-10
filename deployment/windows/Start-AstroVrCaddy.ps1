# Starts the existing Caddy once, unless TCP 8443 is already taken.
# Does not edit the Caddyfile, does not stop a running Caddy, does not touch DNS or firewall.
# A startup task should call this. The task delay covers a slow network; this script retries validate.

$ErrorActionPreference = "Stop"
. "$PSScriptRoot\AstroVr.Common.ps1"

$log = Join-Path $AstroVrLogDir "caddy-task.log"
$stdoutLog = Join-Path $AstroVrLogDir "caddy-stdout.log"
Initialize-AstroVrLog -Path $log
Initialize-AstroVrLog -Path $stdoutLog

if (Get-AstroVrListener -Port 8443) {
    Write-AstroVrLog $log "TCP 8443 already listening. Existing process kept. No second Caddy."
    exit 0
}

$attempts = 5
$pauseSec = 20
for ($i = 1; $i -le $attempts; $i++) {
    if (Get-AstroVrListener -Port 8443) {
        Write-AstroVrLog $log "TCP 8443 became busy. Existing process kept."
        exit 0
    }
    if (-not (Test-Path -LiteralPath $AstroVrCaddyExe)) {
        Write-AstroVrLog $log "missing $AstroVrCaddyExe (attempt $i/$attempts)"
        if ($i -lt $attempts) { Start-Sleep -Seconds $pauseSec }
        continue
    }
    & $AstroVrCaddyExe validate --config $AstroVrCaddyfile --adapter caddyfile *>> $stdoutLog
    if ($LASTEXITCODE -ne 0) {
        Write-AstroVrLog $log "caddy validate failed (attempt $i/$attempts, exit $LASTEXITCODE)"
        if ($i -lt $attempts) { Start-Sleep -Seconds $pauseSec }
        continue
    }
    if (Get-AstroVrListener -Port 8443) {
        Write-AstroVrLog $log "TCP 8443 busy after validate. Existing process kept."
        exit 0
    }
    Write-AstroVrLog $log "starting caddy (attempt $i/$attempts)"
    & $AstroVrCaddyExe run --config $AstroVrCaddyfile --adapter caddyfile *>> $stdoutLog
    $code = $LASTEXITCODE
    Write-AstroVrLog $log "caddy exited code=$code"
    if ($i -lt $attempts) { Start-Sleep -Seconds $pauseSec }
}

Write-AstroVrLog $log "caddy did not stay up after $attempts attempts"
exit 1
