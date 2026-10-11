# Starts the existing Caddy once, unless TCP 8443 is already taken.
# Does not edit the Caddyfile, does not stop a running Caddy, does not touch DNS or firewall.
# A startup task should call this. The task delay covers a slow network; this script retries validate.
# Caddy logs to stderr. PowerShell "Stop" plus *>> turns that into a terminating error and
# exits before caddy-task.log is written. cmd.exe captures both streams instead.

$ErrorActionPreference = "Stop"
$CaddyTaskLog = "C:\ProgramData\AstroVR\logs\caddy-task.log"

function Write-CaddyTaskLine {
    param(
        [Parameter(Mandatory = $true)][string]$Path,
        [Parameter(Mandatory = $true)][string]$Message
    )
    $dir = Split-Path -Parent $Path
    if (-not (Test-Path -LiteralPath $dir)) {
        [System.IO.Directory]::CreateDirectory($dir) | Out-Null
    }
    $stamp = Get-Date -Format "yyyy-MM-dd HH:mm:ss"
    $text = $Message -replace "`r`n", "`n" -replace "`n", "`r`n  "
    [System.IO.File]::AppendAllText($Path, "$stamp $text`r`n", (New-Object System.Text.UTF8Encoding $false))
}

function Write-CaddyFailure {
    param($ErrorRecord)
    Write-CaddyTaskLine $CaddyTaskLog ("ERROR " + $ErrorRecord.Exception.ToString())
    Write-CaddyTaskLine $CaddyTaskLog ("POSITION " + [string]$ErrorRecord.InvocationInfo.PositionMessage)
    Write-CaddyTaskLine $CaddyTaskLog ("STACK " + [string]$ErrorRecord.ScriptStackTrace)
}

try {
    . "$PSScriptRoot\AstroVr.Common.ps1"
    $log = Join-Path $AstroVrLogDir "caddy-task.log"
    $stdoutLog = Join-Path $AstroVrLogDir "caddy-stdout.log"
    Initialize-AstroVrLog -Path $log
    Initialize-AstroVrLog -Path $stdoutLog
    $user = [Security.Principal.WindowsIdentity]::GetCurrent().Name
    Write-AstroVrLog $log "launcher started user=$user pid=$PID"

    function Get-CaddyPortOwner {
        $listener = Get-AstroVrListener -Port 8443
        if (-not $listener) { return $null }
        $proc = Get-Process -Id $listener.OwningProcess -ErrorAction SilentlyContinue
        [PSCustomObject]@{
            Pid  = $listener.OwningProcess
            Name = $(if ($proc) { $proc.ProcessName } else { "unknown" })
        }
    }

    function Test-ExpectedCaddy {
        param($Owner)
        return ($Owner -and $Owner.Name -eq "caddy")
    }

    function Invoke-AstroVrCaddy {
        param([Parameter(Mandatory = $true)][string]$Arguments)
        $stamp = Get-Date -Format "yyyy-MM-dd HH:mm:ss"
        [System.IO.File]::AppendAllText(
            $stdoutLog,
            "$stamp --- caddy $Arguments ---`r`n",
            (New-Object System.Text.UTF8Encoding $false)
        )
        & cmd.exe /d /c "`"$AstroVrCaddyExe`" $Arguments >> `"$stdoutLog`" 2>&1"
        $exitCode = $LASTEXITCODE
        if ($null -eq $exitCode) { return 1 }
        return $exitCode
    }

    $owner = Get-CaddyPortOwner
    if (Test-ExpectedCaddy $owner) {
        Write-AstroVrLog $log "TCP 8443 already listening (caddy pid $($owner.Pid)). Existing process kept. No second Caddy."
        exit 0
    }
    if ($owner) {
        Write-AstroVrLog $log "TCP 8443 already listening ($($owner.Name) pid $($owner.Pid)). Not the expected caddy process. No second Caddy started."
        exit 0
    }

    $attempts = 5
    $pauseSec = 20
    for ($i = 1; $i -le $attempts; $i++) {
        $owner = Get-CaddyPortOwner
        if (Test-ExpectedCaddy $owner) {
            Write-AstroVrLog $log "TCP 8443 became busy (caddy pid $($owner.Pid)). Existing process kept."
            exit 0
        }
        if ($owner) {
            Write-AstroVrLog $log "TCP 8443 busy ($($owner.Name) pid $($owner.Pid)). No second Caddy started."
            exit 0
        }
        if (-not (Test-Path -LiteralPath $AstroVrCaddyExe)) {
            Write-AstroVrLog $log "missing $AstroVrCaddyExe (attempt $i/$attempts)"
            if ($i -lt $attempts) { Start-Sleep -Seconds $pauseSec }
            continue
        }
        $validateCode = Invoke-AstroVrCaddy "validate --config `"$AstroVrCaddyfile`" --adapter caddyfile"
        if ($validateCode -ne 0) {
            Write-AstroVrLog $log "caddy validate failed (attempt $i/$attempts, exit $validateCode)"
            if ($i -lt $attempts) { Start-Sleep -Seconds $pauseSec }
            continue
        }
        $owner = Get-CaddyPortOwner
        if (Test-ExpectedCaddy $owner) {
            Write-AstroVrLog $log "TCP 8443 busy after validate (caddy pid $($owner.Pid)). Existing process kept."
            exit 0
        }
        if ($owner) {
            Write-AstroVrLog $log "TCP 8443 busy after validate ($($owner.Name) pid $($owner.Pid)). No second Caddy started."
            exit 0
        }
        Write-AstroVrLog $log "starting caddy (attempt $i/$attempts)"
        $runCode = Invoke-AstroVrCaddy "run --config `"$AstroVrCaddyfile`" --adapter caddyfile"
        Write-AstroVrLog $log "caddy exited code=$runCode"
        if ($i -lt $attempts) { Start-Sleep -Seconds $pauseSec }
    }

    Write-AstroVrLog $log "caddy did not stay up after $attempts attempts"
    exit 1
} catch {
    Write-CaddyFailure $_
    exit 1
}
