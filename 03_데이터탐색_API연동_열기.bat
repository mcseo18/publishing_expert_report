@echo off
cd /d "%~dp0"
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0scripts\launch_dashboards.ps1" -Target explorer
if errorlevel 1 pause
