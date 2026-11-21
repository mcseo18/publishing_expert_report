$ErrorActionPreference = "Stop"
$ws = Split-Path -Parent $PSScriptRoot
Set-Location $ws
Write-Host "Starting Subagent Control Tower Dashboard on http://127.0.0.1:8501 ..." -ForegroundColor Cyan
& (Join-Path $ws ".venv\Scripts\python.exe") -m uvicorn dashboard.agents_app:app --host 127.0.0.1 --port 8501
