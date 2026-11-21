$ErrorActionPreference = "Stop"
$ws = Split-Path -Parent $PSScriptRoot
$venvLightrag = Join-Path $ws ".venv\Scripts\lightrag-server.exe"
$envFile = Join-Path $ws ".env"

if (-not (Test-Path $venvLightrag)) {
    Write-Error "lightrag-server.exe not found at $venvLightrag. Run pip install -r requirements.txt in .venv first."
}

# Load .env into current process environment
if (Test-Path $envFile) {
    Get-Content $envFile | ForEach-Object {
        $line = $_.Trim()
        if ($line -and -not $line.StartsWith("#") -and $line.Contains("=")) {
            $parts = $line.Split("=", 2)
            [System.Environment]::SetEnvironmentVariable($parts[0].Trim(), $parts[1].Trim(), "Process")
        }
    }
}

$workingDir = if ($env:LIGHTRAG_WORKING_DIR) { $env:LIGHTRAG_WORKING_DIR } else { "C:\SMC_GRAPHRAG\lightrag_store" }
$workspace  = if ($env:WORKSPACE) { $env:WORKSPACE } else { "smc_default" }
$port       = if ($env:PORT) { $env:PORT } else { "9621" }

$numCtx     = if ($env:OLLAMA_LLM_NUM_CTX) { $env:OLLAMA_LLM_NUM_CTX } else { "32768" }

New-Item -ItemType Directory -Force -Path $workingDir | Out-Null

Write-Host "Starting LightRAG Server..." -ForegroundColor Cyan
Write-Host "  WORKING_DIR : $workingDir"
Write-Host "  WORKSPACE   : $workspace"
Write-Host "  WEBUI       : http://127.0.0.1:$port/webui"
Write-Host "  OLLAMA LLM  : $env:LLM_MODEL ($env:LLM_BINDING_HOST, num_ctx=$numCtx)"
Write-Host "  EMBEDDING   : $env:EMBEDDING_MODEL"

& $venvLightrag `
    --working-dir $workingDir `
    --workspace $workspace `
    --host 127.0.0.1 `
    --port $port `
    --llm-binding ollama `
    --embedding-binding ollama `
    --ollama-llm-num_ctx $numCtx
