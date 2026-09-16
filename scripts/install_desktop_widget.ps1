[CmdletBinding()]
param(
    [string]$Profile = "",
    [string]$TaskName = "",
    [switch]$NoLaunch
)

$ErrorActionPreference = "Stop"
$ProjectRoot = Split-Path -Parent $PSScriptRoot
$ShowScript = Join-Path $PSScriptRoot "show_daily_widget.ps1"
$OpenScript = Join-Path $PSScriptRoot "open_daily_report.cmd"
$Python = Join-Path $ProjectRoot ".venv\Scripts\python.exe"
$Config = Join-Path $ProjectRoot "config\settings.yaml"

if (-not (Test-Path -LiteralPath $ShowScript)) {
    throw "Widget launcher not found: $ShowScript"
}

if ([string]::IsNullOrWhiteSpace($Profile)) {
    $Profile = (& $Python (Join-Path $ProjectRoot "run.py") --config $Config profiles resolve).Trim()
    if ($LASTEXITCODE -ne 0 -or [string]::IsNullOrWhiteSpace($Profile)) {
        throw "No active research profile. Run python run.py configure-search first."
    }
}
if ([string]::IsNullOrWhiteSpace($TaskName)) {
    $TaskName = "Literature Widget - $Profile"
}

$CurrentUser = [System.Security.Principal.WindowsIdentity]::GetCurrent().Name
$ActionArguments = '-NoProfile -ExecutionPolicy Bypass -WindowStyle Hidden -File "{0}" -Profile "{1}"' -f $ShowScript, $Profile
$Action = New-ScheduledTaskAction `
    -Execute "powershell.exe" `
    -Argument $ActionArguments `
    -WorkingDirectory $ProjectRoot
$Trigger = New-ScheduledTaskTrigger -AtLogOn -User $CurrentUser
$Principal = New-ScheduledTaskPrincipal `
    -UserId $CurrentUser `
    -LogonType Interactive `
    -RunLevel Limited
$Settings = New-ScheduledTaskSettingsSet `
    -AllowStartIfOnBatteries `
    -DontStopIfGoingOnBatteries `
    -MultipleInstances IgnoreNew `
    -ExecutionTimeLimit (New-TimeSpan -Minutes 10)

Register-ScheduledTask `
    -TaskName $TaskName `
    -Action $Action `
    -Trigger $Trigger `
    -Principal $Principal `
    -Settings $Settings `
    -Description "Open the latest literature report for profile $Profile as a desktop card." `
    -Force | Out-Null

$Desktop = [Environment]::GetFolderPath("Desktop")
$ShortcutPath = Join-Path $Desktop "Daily Literature.lnk"
$Shell = New-Object -ComObject WScript.Shell
$Shortcut = $Shell.CreateShortcut($ShortcutPath)
$Shortcut.TargetPath = $OpenScript
$Shortcut.WorkingDirectory = $ProjectRoot
$Edge = "C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe"
if (Test-Path -LiteralPath $Edge) {
    $Shortcut.IconLocation = "$Edge,0"
}
$Shortcut.Description = "Open the latest literature report, or drag a Daily_Report.md file here."
$Shortcut.Save()

Write-Host "Desktop widget startup task installed: $TaskName"
Write-Host "Desktop shortcut created: $ShortcutPath"
if (-not $NoLaunch) {
    & $ShowScript -Profile $Profile
}
