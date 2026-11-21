@echo off
setlocal
cd /d "%~dp0"
powershell.exe -NoProfile -ExecutionPolicy Bypass -File "%~dp0scripts\launch_dashboards.ps1" -Target all
if errorlevel 1 pause
endlocal
exit /b %ERRORLEVEL%
