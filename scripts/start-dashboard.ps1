# Start the Code Review dashboard: builds the frontend if needed, then serves UI + API.
#   powershell -ExecutionPolicy Bypass -File scripts\start-dashboard.ps1            # http://127.0.0.1:8000
#   powershell -ExecutionPolicy Bypass -File scripts\start-dashboard.ps1 -Port 9000 -Rebuild
param([int]$Port = 8000, [switch]$Rebuild)

$ErrorActionPreference = "Stop"
$root = Split-Path -Parent $PSScriptRoot
Set-Location $root

$python = Join-Path $root ".venv\Scripts\python.exe"
if (-not (Test-Path $python)) {
    Write-Host "Creating virtual environment and installing the project..."
    python -m venv .venv
    & $python -m pip install -e ".[dev,analysis,reports,llm,api]"
}

$dist = Join-Path $root "frontend\dist\index.html"
if ($Rebuild -or -not (Test-Path $dist)) {
    Write-Host "Building the dashboard (frontend)..."
    Push-Location (Join-Path $root "frontend")
    if (-not (Test-Path "node_modules")) { npm install --no-fund --no-audit }
    npm run build
    Pop-Location
}

& $python -m marl_agents.cli serve --port $Port
