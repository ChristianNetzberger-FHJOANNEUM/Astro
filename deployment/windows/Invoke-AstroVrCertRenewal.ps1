# Daily check for the existing Posh-ACME order of vr.netzberger.at.
# Does not pass plugin args, does not use -Force, does not request a new name.
# Reloads Caddy only when fullchain.cer actually changes.
# -CheckOnly reads the order and does not call Submit-Renewal.

param(
    [switch]$CheckOnly
)

$ErrorActionPreference = "Stop"
. "$PSScriptRoot\AstroVr.Common.ps1"

$log = Join-Path $AstroVrRepo "data\vr-boot\cert-renew.log"
Initialize-AstroVrLog -Path $log

function Write-RenewLog {
    param([string]$Message)
    Write-AstroVrLog $log $Message
    Write-Host $Message
}

Import-Module Posh-ACME -ErrorAction Stop
Set-PAServer -DirectoryUrl $AstroVrPoshServer
Set-PAAccount -ID $AstroVrPoshAccount | Out-Null

$order = Get-PAOrder -MainDomain $AstroVrDnsName
if (-not $order) {
    Write-RenewLog "no Posh-ACME order for $AstroVrDnsName under account $AstroVrPoshAccount. Not creating one."
    exit 1
}

$renewAfter = [datetimeoffset]::Parse([string]$order.RenewAfter)
Write-RenewLog "order status=$($order.status) RenewAfter=$($order.RenewAfter) CertExpires=$($order.CertExpires)"

if ([datetimeoffset]::UtcNow -lt $renewAfter) {
    Write-RenewLog "not due. No renewal, Caddy not reloaded."
    exit 0
}

if ($CheckOnly) {
    Write-RenewLog "due, but -CheckOnly set. No renewal."
    exit 0
}

$cer = Join-Path $env:LOCALAPPDATA "Posh-ACME\LE_PROD\$AstroVrPoshAccount\$AstroVrDnsName\fullchain.cer"
if (-not (Test-Path -LiteralPath $cer)) {
    Write-RenewLog "fullchain missing: $cer"
    exit 1
}

$before = (Get-FileHash -Algorithm SHA256 -LiteralPath $cer).Hash
try {
    $renewed = @(Submit-Renewal -MainDomain $AstroVrDnsName)
} catch {
    Write-RenewLog "Submit-Renewal failed. Existing files kept. Caddy not reloaded. $($_.Exception.Message)"
    exit 1
}

$after = (Get-FileHash -Algorithm SHA256 -LiteralPath $cer).Hash
if ($before -eq $after) {
    Write-RenewLog "fullchain unchanged (returned $($renewed.Count) object(s)). Caddy not reloaded."
    exit 0
}

$leaf = New-Object System.Security.Cryptography.X509Certificates.X509Certificate2 $cer
Write-RenewLog "fullchain replaced. NotAfter=$($leaf.NotAfter.ToString('u'))"

& $AstroVrCaddyExe reload --config $AstroVrCaddyfile --adapter caddyfile
if ($LASTEXITCODE -ne 0) {
    Write-RenewLog "caddy reload failed (exit $LASTEXITCODE). New files stay on disk. Running Caddy keeps its loaded certificate until a later reload."
    exit 1
}

Write-RenewLog "caddy reload ok"
exit 0
