# Read-only status. Does not start, stop, or register anything.

$ErrorActionPreference = "Continue"
. "$PSScriptRoot\AstroVr.Common.ps1"

function Write-Check {
    param([string]$Name, [bool]$Ok, [string]$Detail)
    $flag = if ($Ok) { "OK  " } else { "FAIL" }
    Write-Host "$flag  $Name  $Detail"
}

function Write-Note {
    param([string]$Name, [string]$Detail)
    Write-Host "NOTE  $Name  $Detail"
}

$dns = Get-Service -Name DnsService -ErrorAction SilentlyContinue
Write-Check "Technitium service" ($dns -and $dns.Status -eq "Running" -and $dns.StartType -eq "Automatic") "$(if ($dns) { "$($dns.Status) / $($dns.StartType)" } else { 'DnsService missing' })"

$answer = $null
try {
    $answer = Resolve-DnsName -Name $AstroVrDnsName -Server $AstroVrDnsServer -Type A -ErrorAction Stop |
        Where-Object { $_.Type -eq "A" } |
        Select-Object -First 1
} catch {
    Write-Check "DNS $AstroVrDnsName" $false $_.Exception.Message
}
if ($answer) {
    Write-Check "DNS $AstroVrDnsName" ($answer.IPAddress -eq $AstroVrExpectedAddress) "$($answer.IPAddress) via $AstroVrDnsServer"
}

try {
    $public = @(Resolve-DnsName -Name $AstroVrDnsName -Type A -ErrorAction Stop)
    $publicText = ($public | ForEach-Object { "$($_.Type)=$($_.Name) $($_.IPAddress)$($_.NameHost)" }) -join "; "
    Write-Note "system resolver" "$publicText (Quest uses Technitium, not this answer)"
} catch {
    Write-Note "system resolver" $_.Exception.Message
}

foreach ($port in 53, 8082, 8443) {
    $listener = Get-AstroVrListener -Port $port
    Write-Check "TCP $port" ([bool]$listener) $(if ($listener) { "pid $($listener.OwningProcess)" } else { "not listening" })
}

$cer = Join-Path $env:LOCALAPPDATA "Posh-ACME\LE_PROD\$AstroVrPoshAccount\$AstroVrDnsName\fullchain.cer"
if (Test-Path -LiteralPath $cer) {
    $fileCert = New-Object System.Security.Cryptography.X509Certificates.X509Certificate2 $cer
    $days = [int]($fileCert.NotAfter - (Get-Date)).TotalDays
    Write-Check "certificate file" ($fileCert.NotAfter -gt (Get-Date).AddDays(14)) "$($fileCert.Subject) until $($fileCert.NotAfter.ToString('u')) ($days days)"
} else {
    Write-Check "certificate file" $false "missing $cer"
    $fileCert = $null
}

$curl = Join-Path $env:SystemRoot "System32\curl.exe"
if (-not (Test-Path -LiteralPath $curl)) {
    Write-Check "HTTPS GET" $false "curl.exe missing"
} else {
    $httpCode = & $curl --resolve "${AstroVrDnsName}:8443:${AstroVrExpectedAddress}" --max-time 15 -sS -o NUL -w "%{http_code}" $AstroVrUrl
    Write-Check "HTTPS GET" ($LASTEXITCODE -eq 0 -and $httpCode -eq "200") "$AstroVrUrl via $AstroVrExpectedAddress -> $httpCode"
}

if ($fileCert) {
    $tcp = $null
    $ssl = $null
    try {
        $tcp = New-Object System.Net.Sockets.TcpClient
        $wait = $tcp.BeginConnect($AstroVrExpectedAddress, 8443, $null, $null)
        if (-not $wait.AsyncWaitHandle.WaitOne(8000, $false)) {
            throw "timeout connecting to ${AstroVrExpectedAddress}:8443"
        }
        $tcp.EndConnect($wait)
        $ssl = New-Object System.Net.Security.SslStream($tcp.GetStream(), $false, { param($sender, $certificate, $chain, $errors) return $true })
        $ssl.AuthenticateAsClient($AstroVrDnsName)
        $live = New-Object System.Security.Cryptography.X509Certificates.X509Certificate2($ssl.RemoteCertificate)
        $same = $live.Thumbprint -eq $fileCert.Thumbprint
        Write-Check "live certificate" $same "live $($live.NotAfter.ToString('u')) file $($fileCert.NotAfter.ToString('u'))"
    } catch {
        Write-Check "live certificate" $false $_.Exception.Message
    } finally {
        if ($ssl) { $ssl.Dispose() }
        if ($tcp) { $tcp.Dispose() }
    }
}

foreach ($name in @($AstroVrTaskCaddy, $AstroVrTaskApp, $AstroVrTaskCert)) {
    $task = Get-ScheduledTask -TaskName $name -ErrorAction SilentlyContinue
    if (-not $task) {
        Write-Note "task $name" "not registered"
        continue
    }
    $info = Get-ScheduledTaskInfo -TaskName $name
    Write-Check "task $name" $true "$($task.State) last=$($info.LastTaskResult)"
}

Write-Host ""
Write-Host "Logs: $AstroVrLogDir and $AstroVrRepo\data\vr-boot"
Write-Host "This script does not start or stop processes."
