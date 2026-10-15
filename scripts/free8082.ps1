# Gibt TCP 8082 frei, falls darauf noch etwas lauscht.
# Aufruf: powershell -ExecutionPolicy Bypass -File scripts\free8082.ps1
# Beendet den lauschenden Prozess und, falls es die MeLE-App ist, den Starter darueber.
# Andere Ports, insbesondere 8097 und 8443, bleiben unberuehrt.

$ErrorActionPreference = "Stop"
$Port = 8082

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

function Get-ProcessRow {
    param([int]$ProcessId)
    Get-CimInstance Win32_Process -Filter "ProcessId=$ProcessId" -ErrorAction SilentlyContinue
}

function Test-MeleAppProcess {
    param($Row)
    if (-not $Row) { return $false }
    $cmd = [string]$Row.CommandLine
    return ($cmd -match '-m app_mele' -or $cmd -match 'Start-AstroVrMeleApp\.ps1')
}

function Stop-ProcessTree {
    param([int]$ProcessId)
    & taskkill.exe /PID $ProcessId /T /F | Out-Host
    return ($LASTEXITCODE -eq 0)
}

$listeners = @(Get-ListeningProcessIds -LocalPort $Port)
if ($listeners.Count -eq 0) {
    Write-Host "Port $Port ist frei."
    exit 0
}

Write-Host "Port $Port ist belegt. Beende $($listeners.Count) Instanz(en):"
foreach ($procId in $listeners) {
    $proc = Get-ProcessRow -ProcessId $procId
    if ($proc) {
        Write-Host "  PID $procId  $($proc.Name)"
        if ($proc.CommandLine) {
            Write-Host "    $($proc.CommandLine)"
        }
    } else {
        Write-Host "  PID $procId"
    }

    $roots = New-Object System.Collections.Generic.List[int]
    $seen = @{}
    $current = $procId
    for ($step = 0; $step -lt 12 -and $current -gt 4; $step++) {
        if ($seen.ContainsKey($current)) { break }
        $seen[$current] = $true
        $row = Get-ProcessRow -ProcessId $current
        if (-not $row) { break }
        $followParent = ($current -eq $procId) -or (Test-MeleAppProcess -Row $row)
        if (-not $followParent) { break }
        $roots.Insert(0, $current)
        $parentId = [int]$row.ParentProcessId
        $parent = Get-ProcessRow -ProcessId $parentId
        if (-not (Test-MeleAppProcess -Row $parent)) { break }
        $current = $parentId
    }
    if ($roots.Count -eq 0) {
        $roots.Add($procId)
    }

    foreach ($rootId in $roots) {
        $alive = Get-Process -Id $rootId -ErrorAction SilentlyContinue
        if (-not $alive) { continue }
        if (-not (Stop-ProcessTree -ProcessId $rootId)) {
            Write-Error "Prozess $rootId konnte nicht beendet werden."
            exit 1
        }
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
