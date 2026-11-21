@echo off
setlocal
cd /d "%~dp0\.."
powershell.exe -NoProfile -ExecutionPolicy Bypass -File "%~dp0launch_dashboards.ps1" -Target main
if errorlevel 1 pause
endlocal
exit /b %ERRORLEVEL%
