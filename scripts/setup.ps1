[CmdletBinding()]
param()

$ErrorActionPreference = "Stop"
$ProjectRoot = Split-Path -Parent $PSScriptRoot
$VenvPython = Join-Path $ProjectRoot ".venv\Scripts\python.exe"
$env:PIP_CACHE_DIR = Join-Path $ProjectRoot ".pip-cache"

Set-Location $ProjectRoot

if (-not (Test-Path -LiteralPath $VenvPython)) {
    py -3 -m venv (Join-Path $ProjectRoot ".venv")
    if ($LASTEXITCODE -ne 0) {
        throw "Failed to create the Python virtual environment."
    }
}

& $VenvPython -m pip install --upgrade pip
if ($LASTEXITCODE -ne 0) {
    throw "Failed to upgrade pip."
}
& $VenvPython -m pip install -r (Join-Path $ProjectRoot "requirements.txt")
if ($LASTEXITCODE -ne 0) {
    throw "Failed to install Python dependencies."
}

$EnvFile = Join-Path $ProjectRoot ".env"
if (-not (Test-Path -LiteralPath $EnvFile)) {
    Copy-Item -LiteralPath (Join-Path $ProjectRoot ".env.example") -Destination $EnvFile
}

& $VenvPython (Join-Path $ProjectRoot "run.py") --config (Join-Path $ProjectRoot "config\settings.yaml") validate
if ($LASTEXITCODE -ne 0) {
    throw "Configuration validation failed."
}

Write-Host ""
Write-Host "Literature Monitor v0.1.0 environment is ready. Next:"
Write-Host "  1. Create a research profile:"
Write-Host "     .\.venv\Scripts\python.exe run.py configure-search"
Write-Host "  2. Add required API keys to .env."
Write-Host "  3. Run: .\scripts\run_daily.ps1 -Profile <profile_id> -NoDelivery"
