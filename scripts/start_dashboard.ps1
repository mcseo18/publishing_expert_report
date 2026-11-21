$ErrorActionPreference = "Stop"
$ws = Split-Path -Parent $PSScriptRoot
$py = Join-Path $ws ".venv\Scripts\python.exe"

Write-Host "Starting SMC Report Platform Curation Dashboard..." -ForegroundColor Cyan
Write-Host "  URL          : http://127.0.0.1:8500"
Write-Host "  Data Storage : E:\SMC_Report_Platform_Data"
Write-Host "  KG Store     : C:\SMC_GRAPHRAG"

Set-Location $ws
& $py -m uvicorn dashboard.app:app --host 127.0.0.1 --port 8500
