[CmdletBinding()]
param(
    [string]$ReportPath = "",
    [string]$Profile = "",
    [int]$Width = 520,
    [int]$Height = 720
)

$ErrorActionPreference = "Stop"
$ProjectRoot = Split-Path -Parent $PSScriptRoot
$Python = Join-Path $ProjectRoot ".venv\Scripts\python.exe"
$Config = Join-Path $ProjectRoot "config\settings.yaml"

if (-not (Test-Path -LiteralPath $Python)) {
    throw "Virtual environment not found. Run .\scripts\setup.ps1 first."
}

$RenderArguments = @(
    "-m", "literature_pipeline.desktop_widget",
    "--config", $Config
)
if (-not [string]::IsNullOrWhiteSpace($Profile)) {
    $RenderArguments += @("--profile", $Profile)
}
if (-not [string]::IsNullOrWhiteSpace($ReportPath)) {
    $ResolvedReport = (Resolve-Path -LiteralPath $ReportPath).Path
    if ([IO.Path]::GetExtension($ResolvedReport) -ne ".md") {
        throw "Only .md report files are supported: $ResolvedReport"
    }
    $RenderArguments += @("--report", $ResolvedReport)
}

Set-Location $ProjectRoot
$WidgetPath = (& $Python @RenderArguments | Select-Object -Last 1).Trim()
if ($LASTEXITCODE -ne 0 -or [string]::IsNullOrWhiteSpace($WidgetPath) -or -not (Test-Path -LiteralPath $WidgetPath)) {
    throw "Desktop widget rendering failed."
}
$WidgetProfile = Join-Path (Split-Path -Parent $WidgetPath) "edge_profile"

$EdgeCandidates = @(
    "C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe",
    "C:\Program Files\Microsoft\Edge\Application\msedge.exe"
)
$Edge = $EdgeCandidates | Where-Object { Test-Path -LiteralPath $_ } | Select-Object -First 1
if (-not $Edge) {
    throw "Microsoft Edge was not found."
}

Add-Type -AssemblyName System.Windows.Forms
$Area = [System.Windows.Forms.Screen]::PrimaryScreen.WorkingArea
$Width = [Math]::Max(420, [Math]::Min($Width, $Area.Width - 48))
$Height = [Math]::Max(560, [Math]::Min($Height, $Area.Height - 48))
$X = $Area.Right - $Width - 20
$Y = $Area.Bottom - $Height - 20
$WidgetUrl = ([Uri]$WidgetPath).AbsoluteUri

$EdgeArguments = @(
    ('--app="{0}"' -f $WidgetUrl),
    ('--user-data-dir="{0}"' -f $WidgetProfile),
    ('--window-size={0},{1}' -f $Width, $Height),
    ('--window-position={0},{1}' -f $X, $Y),
    "--no-first-run",
    "--no-default-browser-check",
    "--disable-features=msEdgeFirstRunExperience"
)

Start-Process -FilePath $Edge -ArgumentList $EdgeArguments
