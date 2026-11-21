param(
    [ValidateSet("all", "agents", "main", "explorer", "stop")]
    [string]$Target = "all",
    [switch]$NoBrowser
)

$ErrorActionPreference = "Stop"
$ws = Split-Path -Parent $PSScriptRoot
$py = Join-Path $ws ".venv\Scripts\python.exe"
$logDir = "E:\SMC_Report_Platform_Data\logs"
if (-not (Test-Path $logDir)) { New-Item -ItemType Directory -Path $logDir -Force | Out-Null }

function Get-ListeningPid([int]$Port) {
    $conns = Get-NetTCPConnection -LocalPort $Port -State Listen -ErrorAction SilentlyContinue
    if ($conns) { return ($conns | Select-Object -First 1 -ExpandProperty OwningProcess) }
    return $null
}

if ($Target -eq "stop") {
    foreach ($p in @(8500, 8501)) {
        $procId = Get-ListeningPid $p
        if ($procId) {
            Write-Host "[STOP] Port $p (PID $procId) stopping..." -ForegroundColor Yellow
            Stop-Process -Id $procId -Force -ErrorAction SilentlyContinue
        } else {
            Write-Host "[STOP] Port $p is already stopped." -ForegroundColor DarkGray
        }
    }
    exit 0
}

if (-not (Test-Path $py)) {
    Write-Host "[ERROR] Python venv not found: $py" -ForegroundColor Red
    exit 1
}

function Ensure-Server([int]$Port, [string]$AppModule, [string]$Label) {
    $existing = Get-ListeningPid $Port
    if ($existing) {
        Write-Host "[OK] $Label (http://127.0.0.1:$Port) already running (PID $existing)." -ForegroundColor Green
        return
    }
    Write-Host "[START] Starting $Label on http://127.0.0.1:$Port ..." -ForegroundColor Cyan
    $outLog = Join-Path $logDir "dashboard_${Port}.out.log"
    $errLog = Join-Path $logDir "dashboard_${Port}.err.log"
    Start-Process -FilePath $py `
        -ArgumentList @("-m", "uvicorn", $AppModule, "--host", "127.0.0.1", "--port", "$Port") `
        -WorkingDirectory $ws `
        -WindowStyle Minimized `
        -RedirectStandardOutput $outLog `
        -RedirectStandardError $errLog | Out-Null

    $ready = $false
    for ($i = 0; $i -lt 38; $i++) {
        Start-Sleep -Milliseconds 400
        try {
            $resp = Invoke-WebRequest -Uri "http://127.0.0.1:$Port/" -UseBasicParsing -TimeoutSec 2
            if ($resp.StatusCode -eq 200) {
                $ready = $true
                break
            }
        } catch {}
    }
    if ($ready) {
        Write-Host "[READY] $Label is online at http://127.0.0.1:$Port" -ForegroundColor Green
    } else {
        Write-Host "[WARN] $Label did not respond within 15s. Check log: $errLog" -ForegroundColor Yellow
    }
}

$urls = @()
if ($Target -eq "all" -or $Target -eq "agents") {
    Ensure-Server -Port 8501 -AppModule "dashboard.agents_app:app" -Label "Unified Textbook Publishing Dashboard"
    $urls += "http://127.0.0.1:8501"
}
if ($Target -eq "explorer") {
    Ensure-Server -Port 8501 -AppModule "dashboard.agents_app:app" -Label "Unified Textbook Publishing Dashboard (Explorer Tab)"
    $urls += "http://127.0.0.1:8501/#explorer"
}
if ($Target -eq "main") {
    Ensure-Server -Port 8500 -AppModule "dashboard.app:app" -Label "Legacy Data Curation Server (8500)"
    $urls += "http://127.0.0.1:8500"
}

if (-not $NoBrowser) {
    foreach ($u in $urls) {
        Start-Process $u
    }
}
exit 0
