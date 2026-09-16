[CmdletBinding()]
param([string]$Profile = "")

$ErrorActionPreference = "Stop"
$ProjectRoot = Split-Path -Parent $PSScriptRoot
$Python = Join-Path $ProjectRoot ".venv\Scripts\python.exe"

if (-not (Test-Path -LiteralPath $Python)) {
    throw "Virtual environment not found. Run .\scripts\setup.ps1 first."
}

Set-Location $ProjectRoot
$Arguments = @((Join-Path $ProjectRoot "run.py"), "--config", (Join-Path $ProjectRoot "config\settings.yaml"))
if (-not [string]::IsNullOrWhiteSpace($Profile)) { $Arguments += @("--profile", $Profile) }
$Arguments += "export"
& $Python @Arguments
exit $LASTEXITCODE
