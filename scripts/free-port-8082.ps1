# Prueft, ob TCP-Port 8082 belegt ist, und beendet die lauschende Instanz.
# Aufruf:  powershell -ExecutionPolicy Bypass -File scripts\free-port-8082.ps1

param(
    [int]$Port = 8082
)

$ErrorActionPreference = "Stop"

function Get-ListeningProcessIds {
    param([int]$LocalPort)

    $ids = @()
    try {
        $connections = @(Get-NetTCPConnection -LocalPort $LocalPort -State Listen -ErrorAction Stop)
        foreach ($connection in $connections) {
            if ($connection.OwningProcess -gt 4) {
                $ids += [int]$connection.OwningProcess
            }
        }
    } catch {
        # Deutsche Windows-Ausgabe von netstat nennt den Zustand ABHOEREN.
        $pattern = "^\s*TCP\s+\S+:$LocalPort\s+\S+\s+(LISTENING|ABH.REN)\s+(\d+)\s*$"
        netstat -ano -p tcp | ForEach-Object {
            if ($_ -match $pattern) {
                $procId = [int]$Matches[2]
                if ($procId -gt 4) {
                    $ids += $procId
                }
            }
        }
    }

    return @($ids | Select-Object -Unique)
}

$listeners = @(Get-ListeningProcessIds -LocalPort $Port)
if ($listeners.Count -eq 0) {
    Write-Host "Port $Port ist frei."
    exit 0
}

Write-Host "Port $Port ist belegt. Beende $($listeners.Count) Instanz(en):"
foreach ($procId in $listeners) {
    $proc = Get-CimInstance Win32_Process -Filter "ProcessId=$procId" -ErrorAction SilentlyContinue
    if ($proc) {
        Write-Host "  PID $procId  $($proc.Name)"
        if ($proc.CommandLine) {
            Write-Host "    $($proc.CommandLine)"
        }
    } else {
        Write-Host "  PID $procId"
    }

    & taskkill.exe /PID $procId /T /F
    if ($LASTEXITCODE -ne 0) {
        Write-Error "Prozess $procId konnte nicht beendet werden (Exit $LASTEXITCODE)."
        exit 1
    }
}

Start-Sleep -Milliseconds 400
$still = @(Get-ListeningProcessIds -LocalPort $Port)
if ($still.Count -gt 0) {
    Write-Error "Port $Port ist weiterhin belegt (PID: $($still -join ', '))."
    exit 1
}

Write-Host "Port $Port ist wieder frei."
exit 0
