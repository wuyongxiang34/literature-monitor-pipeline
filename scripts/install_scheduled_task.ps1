[CmdletBinding()]
param(
    [string]$Profile = "",
    [string]$TaskName = "",
    [string]$DailyAt = "08:00"
)

$ErrorActionPreference = "Stop"
$ProjectRoot = Split-Path -Parent $PSScriptRoot
$RunScript = Join-Path $PSScriptRoot "run_daily.ps1"
$Python = Join-Path $ProjectRoot ".venv\Scripts\python.exe"
$Config = Join-Path $ProjectRoot "config\settings.yaml"

if (-not (Test-Path -LiteralPath $RunScript)) {
    throw "Daily runner not found: $RunScript"
}

if ([string]::IsNullOrWhiteSpace($Profile)) {
    $Profile = (& $Python (Join-Path $ProjectRoot "run.py") --config $Config profiles resolve).Trim()
    if ($LASTEXITCODE -ne 0 -or [string]::IsNullOrWhiteSpace($Profile)) {
        throw "No active research profile. Run python run.py configure-search first."
    }
}
if ([string]::IsNullOrWhiteSpace($TaskName)) {
    $TaskName = "Literature Monitor - $Profile"
}

$At = [DateTime]::ParseExact($DailyAt, "HH:mm", [Globalization.CultureInfo]::InvariantCulture)
$ActionArguments = '-NoProfile -ExecutionPolicy Bypass -File "{0}" -Profile "{1}"' -f $RunScript, $Profile
$Action = New-ScheduledTaskAction `
    -Execute "powershell.exe" `
    -Argument $ActionArguments `
    -WorkingDirectory $ProjectRoot
$Trigger = New-ScheduledTaskTrigger -Daily -At $At
$Principal = New-ScheduledTaskPrincipal `
    -UserId ([System.Security.Principal.WindowsIdentity]::GetCurrent().Name) `
    -LogonType Interactive `
    -RunLevel Limited
$Settings = New-ScheduledTaskSettingsSet `
    -StartWhenAvailable `
    -AllowStartIfOnBatteries `
    -DontStopIfGoingOnBatteries `
    -MultipleInstances IgnoreNew `
    -ExecutionTimeLimit (New-TimeSpan -Hours 2)

Register-ScheduledTask `
    -TaskName $TaskName `
    -Action $Action `
    -Trigger $Trigger `
    -Principal $Principal `
    -Settings $Settings `
    -Description "Daily literature search, SQLite update, and Excel export for profile $Profile (v0.1.0)." `
    -Force | Out-Null

$Task = Get-ScheduledTask -TaskName $TaskName
Write-Host "Scheduled task installed: $($Task.TaskName)"
Write-Host "State: $($Task.State)"
Write-Host "Daily time: $DailyAt (Windows local timezone; keep it aligned with config/settings.yaml)."
Write-Host "Research profile: $Profile"
