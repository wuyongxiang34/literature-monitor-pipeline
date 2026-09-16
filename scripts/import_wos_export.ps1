[CmdletBinding()]
param(
    [Parameter(Mandatory = $true)]
    [string]$Path,
    [string]$Profile = "",
    [switch]$RunAfterImport
)

$ErrorActionPreference = "Stop"
$ProjectRoot = Split-Path -Parent $PSScriptRoot
$Source = (Resolve-Path -LiteralPath $Path).Path
$Python = Join-Path $ProjectRoot ".venv\Scripts\python.exe"
$Config = Join-Path $ProjectRoot "config\settings.yaml"
$Allowed = @(".xlsx", ".xls", ".csv", ".txt")
$Extension = [IO.Path]::GetExtension($Source).ToLowerInvariant()

if ($Allowed -notcontains $Extension) {
    throw "Unsupported WoS export format: $Extension. Use Excel, CSV, or Plain Text."
}

if ([string]::IsNullOrWhiteSpace($Profile)) {
    $Profile = (& $Python (Join-Path $ProjectRoot "run.py") --config $Config profiles resolve).Trim()
}
$Inbox = (& $Python (Join-Path $ProjectRoot "run.py") --config $Config profiles path $Profile wos-inbox).Trim()
if ($LASTEXITCODE -ne 0 -or [string]::IsNullOrWhiteSpace($Inbox)) {
    throw "Unable to resolve the WoS inbox for profile $Profile."
}
New-Item -ItemType Directory -Force -Path $Inbox | Out-Null
$Destination = Join-Path $Inbox ([IO.Path]::GetFileName($Source))
if (Test-Path -LiteralPath $Destination) {
    $Timestamp = Get-Date -Format "yyyyMMdd_HHmmss"
    $BaseName = [IO.Path]::GetFileNameWithoutExtension($Source)
    $Destination = Join-Path $Inbox ($BaseName + "_" + $Timestamp + $Extension)
}

Copy-Item -LiteralPath $Source -Destination $Destination
Write-Host "Imported to inbox: $Destination"

if ($RunAfterImport) {
    & (Join-Path $PSScriptRoot "run_daily.ps1") -Profile $Profile -NoDelivery
    exit $LASTEXITCODE
}

Write-Host "Run .\scripts\run_daily.ps1 -NoDelivery to process the export."
