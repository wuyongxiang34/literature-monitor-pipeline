@echo off
setlocal
set "REPORT_PATH=%~1"
if "%REPORT_PATH%"=="" (
  powershell.exe -NoProfile -ExecutionPolicy Bypass -WindowStyle Hidden -File "%~dp0show_daily_widget.ps1"
) else (
  powershell.exe -NoProfile -ExecutionPolicy Bypass -WindowStyle Hidden -File "%~dp0show_daily_widget.ps1" -ReportPath "%REPORT_PATH%"
)
endlocal
