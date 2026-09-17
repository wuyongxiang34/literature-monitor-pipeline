[CmdletBinding()]
param(
    [ValidateSet("3.11", "3.12", "3.13", "3.14")]
    [string]$PythonVersion,
    [switch]$RecreateVenv,
    [switch]$WithPlaywright
)

$ErrorActionPreference = "Stop"
$ProjectRoot = Split-Path -Parent $PSScriptRoot
$VenvDirectory = Join-Path $ProjectRoot ".venv"
$VenvPython = Join-Path $VenvDirectory "Scripts\python.exe"
$env:PIP_CACHE_DIR = Join-Path $ProjectRoot ".pip-cache"

Set-Location $ProjectRoot

function Get-PythonInfo {
    param(
        [Parameter(Mandatory = $true)][string]$Command,
        [string[]]$PrefixArguments = @()
    )

    try {
        $Json = & $Command @PrefixArguments -c "import json,platform,sys; print(json.dumps({'version': f'{sys.version_info.major}.{sys.version_info.minor}.{sys.version_info.micro}', 'short': f'{sys.version_info.major}.{sys.version_info.minor}', 'executable': sys.executable, 'bits': platform.architecture()[0]}))" 2>$null
        if ($LASTEXITCODE -ne 0 -or [string]::IsNullOrWhiteSpace($Json)) {
            return $null
        }
        return $Json | ConvertFrom-Json
    }
    catch {
        return $null
    }
}

function Test-SupportedPython {
    param($Info)
    return $null -ne $Info -and $Info.short -in @("3.11", "3.12", "3.13", "3.14")
}

function Resolve-PythonCommand {
    param([string]$RequestedVersion)

    $Launcher = Get-Command py -ErrorAction SilentlyContinue
    $PathPython = Get-Command python -ErrorAction SilentlyContinue
    $Versions = if ([string]::IsNullOrWhiteSpace($RequestedVersion)) {
        @("3.14", "3.13", "3.12", "3.11")
    }
    else {
        @($RequestedVersion)
    }

    if ($null -ne $Launcher) {
        foreach ($Version in $Versions) {
            $Info = Get-PythonInfo -Command $Launcher.Source -PrefixArguments @("-$Version")
            if (Test-SupportedPython $Info -and $Info.short -eq $Version) {
                return [pscustomobject]@{
                    Command = $Launcher.Source
                    PrefixArguments = @("-$Version")
                    Info = $Info
                }
            }
        }
    }

    if ($null -ne $PathPython) {
        $Info = Get-PythonInfo -Command $PathPython.Source
        if (Test-SupportedPython $Info -and (
            [string]::IsNullOrWhiteSpace($RequestedVersion) -or $Info.short -eq $RequestedVersion
        )) {
            return [pscustomobject]@{
                Command = $PathPython.Source
                PrefixArguments = @()
                Info = $Info
            }
        }
    }

    $Wanted = if ([string]::IsNullOrWhiteSpace($RequestedVersion)) { "3.11-3.14" } else { $RequestedVersion }
    throw (
        "No supported Python interpreter was found (required: $Wanted).`n" +
        "Install 64-bit Python from https://www.python.org/downloads/windows/ and reopen PowerShell."
    )
}

function Invoke-PipInstall {
    param(
        [Parameter(Mandatory = $true)][string[]]$Arguments,
        [Parameter(Mandatory = $true)][string]$Description,
        [Parameter(Mandatory = $true)]$PythonInfo
    )

    & $VenvPython -m pip install @Arguments
    if ($LASTEXITCODE -ne 0) {
        throw (
            "$Description failed.`n" +
            "Python: $($PythonInfo.version) ($($PythonInfo.bits))`n" +
            "Interpreter: $($PythonInfo.executable)`n" +
            "The installer only accepts prebuilt wheels, so Microsoft C++ Build Tools are not required. " +
            "Check the network connection and use a supported Python version (3.11-3.14)."
        )
    }
}

$ExistingInfo = $null
if (Test-Path -LiteralPath $VenvDirectory) {
    if (Test-Path -LiteralPath $VenvPython) {
        $ExistingInfo = Get-PythonInfo -Command $VenvPython
    }
    $VersionMismatch = (
        -not [string]::IsNullOrWhiteSpace($PythonVersion) -and
        ($null -eq $ExistingInfo -or $ExistingInfo.short -ne $PythonVersion)
    )
    $NeedsRecreate = -not (Test-SupportedPython $ExistingInfo) -or $VersionMismatch

    if ($NeedsRecreate -and -not $RecreateVenv) {
        $Detected = if ($null -eq $ExistingInfo) { "unusable" } else { $ExistingInfo.version }
        $Suggested = if ([string]::IsNullOrWhiteSpace($PythonVersion)) { "3.12" } else { $PythonVersion }
        throw (
            "The existing .venv uses unsupported or mismatched Python ($Detected).`n" +
            "Run: .\scripts\setup.ps1 -PythonVersion $Suggested -RecreateVenv"
        )
    }

    if ($NeedsRecreate) {
        $Stamp = Get-Date -Format "yyyyMMdd_HHmmss"
        $Backup = Join-Path $ProjectRoot ".venv_backup_$($Stamp)_$PID"
        Move-Item -LiteralPath $VenvDirectory -Destination $Backup
        Write-Host "Previous virtual environment was preserved at: $Backup"
        $ExistingInfo = $null
    }
}

if (-not (Test-Path -LiteralPath $VenvPython)) {
    $Candidate = Resolve-PythonCommand -RequestedVersion $PythonVersion
    Write-Host "Creating .venv with Python $($Candidate.Info.version): $($Candidate.Info.executable)"
    & $Candidate.Command @($Candidate.PrefixArguments) -m venv $VenvDirectory
    if ($LASTEXITCODE -ne 0) {
        throw "Failed to create the Python virtual environment."
    }
}

$PythonInfo = Get-PythonInfo -Command $VenvPython
if (-not (Test-SupportedPython $PythonInfo)) {
    throw "The virtual environment is not using supported Python 3.11-3.14."
}

Invoke-PipInstall -Description "pip bootstrap" -PythonInfo $PythonInfo -Arguments @(
    "--upgrade", "pip", "setuptools", "wheel", "--only-binary=:all:"
)
Invoke-PipInstall -Description "Core dependency installation" -PythonInfo $PythonInfo -Arguments @(
    "-r", (Join-Path $ProjectRoot "requirements.txt"), "--only-binary=:all:"
)

if ($WithPlaywright) {
    Invoke-PipInstall -Description "Optional Playwright installation" -PythonInfo $PythonInfo -Arguments @(
        "-r", (Join-Path $ProjectRoot "requirements-playwright.txt"), "--only-binary=:all:"
    )
}

$EnvFile = Join-Path $ProjectRoot ".env"
if (-not (Test-Path -LiteralPath $EnvFile)) {
    Copy-Item -LiteralPath (Join-Path $ProjectRoot ".env.example") -Destination $EnvFile
}

& $VenvPython (Join-Path $ProjectRoot "run.py") --config (Join-Path $ProjectRoot "config\settings.yaml") validate
if ($LASTEXITCODE -ne 0) {
    throw "Configuration validation failed."
}
& $VenvPython (Join-Path $ProjectRoot "run.py") --config (Join-Path $ProjectRoot "config\settings.yaml") doctor
if ($LASTEXITCODE -ne 0) {
    throw "Environment diagnostics failed."
}

Write-Host ""
$ProjectVersion = (& $VenvPython -c "from literature_pipeline import __version__; print(__version__)").Trim()
Write-Host "Literature Monitor v$ProjectVersion environment is ready."
Write-Host "Python $($PythonInfo.version) ($($PythonInfo.bits)): $($PythonInfo.executable)"
if (-not $WithPlaywright) {
    Write-Host "Playwright was not installed (optional). Use -WithPlaywright only for experimental WoS browser mode."
}
Write-Host "Next:"
Write-Host "  1. Create a research profile:"
Write-Host "     .\.venv\Scripts\python.exe run.py configure-search"
Write-Host "  2. Add required API keys to .env."
Write-Host "  3. Run: .\scripts\run_daily.ps1 -Profile <profile_id> -NoDelivery"
