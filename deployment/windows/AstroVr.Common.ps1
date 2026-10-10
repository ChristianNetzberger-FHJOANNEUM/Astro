# Shared paths for the Astro-VR Windows tasks.
# No secrets. Do not print pluginargs.json or cert.key.

$ErrorActionPreference = "Stop"

$AstroVrRepo = "C:\Astro\Git\Astro"
$AstroVrPython = "C:\Python\310\python.exe"
$AstroVrCaddyExe = "C:\Caddy\caddy.exe"
$AstroVrCaddyfile = "C:\Caddy\Caddyfile"
$AstroVrUser = "ASTRO\Chris"
$AstroVrDnsServer = "192.168.0.176"
$AstroVrDnsName = "vr.netzberger.at"
$AstroVrExpectedAddress = "192.168.0.176"
$AstroVrUrl = "https://vr.netzberger.at:8443/vr-view"
$AstroVrPoshAccount = "3849034426"
$AstroVrPoshServer = "https://acme-v02.api.letsencrypt.org/directory"
$AstroVrLogDir = "C:\ProgramData\AstroVR\logs"
$AstroVrTaskCaddy = "AstroVR-Caddy"
$AstroVrTaskApp = "Astro-mele_app"
$AstroVrTaskCert = "AstroVR-CertRenewal"

function Initialize-AstroVrLog {
    param([Parameter(Mandatory = $true)][string]$Path)
    $dir = Split-Path -Parent $Path
    New-Item -ItemType Directory -Force -Path $dir | Out-Null
    if ((Test-Path -LiteralPath $Path) -and ((Get-Item -LiteralPath $Path).Length -gt 5MB)) {
        $old = "$Path.old"
        if (Test-Path -LiteralPath $old) { Remove-Item -LiteralPath $old -Force }
        Move-Item -LiteralPath $Path -Destination $old
    }
}

function Write-AstroVrLog {
    param(
        [Parameter(Mandatory = $true)][string]$Path,
        [Parameter(Mandatory = $true)][string]$Message
    )
    $dir = Split-Path -Parent $Path
    New-Item -ItemType Directory -Force -Path $dir | Out-Null
    $stamp = Get-Date -Format "yyyy-MM-dd HH:mm:ss"
    Add-Content -LiteralPath $Path -Value "$stamp $Message" -Encoding UTF8
}

function Get-AstroVrListener {
    param([Parameter(Mandatory = $true)][int]$Port)
    Get-NetTCPConnection -LocalPort $Port -State Listen -ErrorAction SilentlyContinue |
        Select-Object -First 1
}

function Test-AstroVrAdministrator {
    $current = [Security.Principal.WindowsIdentity]::GetCurrent()
    $principal = New-Object Security.Principal.WindowsPrincipal($current)
    return $principal.IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)
}
