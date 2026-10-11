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

$outputLog = Join-Path $AstroVrRepo "data\vr-boot\mele-app-output.log"
Initialize-AstroVrLog -Path $outputLog
$stamp = Get-Date -Format "yyyy-MM-dd HH:mm:ss"
[System.IO.File]::AppendAllText(
    $outputLog,
    "$stamp --- python stdout/stderr ---`r`n",
    (New-Object System.Text.UTF8Encoding $false)
)

Write-AstroVrLog $log "starting $AstroVrPython -m app_mele in $AstroVrRepo"
Write-AstroVrLog $log "python output: $outputLog"
Set-Location -LiteralPath $AstroVrRepo
# cmd owns the redirection. PowerShell would treat stderr as a terminating
# error under ErrorAction Stop and skip the exit-code log below.
$env:PYTHONUNBUFFERED = "1"
$env:PYTHONIOENCODING = "utf-8"
& cmd.exe /d /c "`"$AstroVrPython`" -m app_mele >> `"$outputLog`" 2>&1"
$code = $LASTEXITCODE
if ($null -eq $code) {
    $code = 1
    Write-AstroVrLog $log "app exit code missing, returning 1"
} else {
    Write-AstroVrLog $log "app exited code=$code"
}
exit $code
