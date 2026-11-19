$ErrorActionPreference = 'Stop'
$projectRoot = Split-Path -Parent $PSScriptRoot
Set-Location -LiteralPath $projectRoot
$pythonExe = Join-Path $projectRoot '.venv\Scripts\python.exe'
if (-not (Test-Path -LiteralPath $pythonExe)) {
    python -m venv .venv
    if ($LASTEXITCODE -ne 0) { throw 'Impossible de créer l’environnement Python.' }
}
& $pythonExe -c "import importlib.util,sys;sys.exit(0 if all(importlib.util.find_spec(m) for m in ['fastapi','uvicorn','psycopg']) else 1)"
if ($LASTEXITCODE -ne 0) {
    & $pythonExe -m pip install -r requirements-api.lock -e '.[api,postgres]'
    if ($LASTEXITCODE -ne 0) { throw 'Installation Python interrompue.' }
}
if (-not (Test-Path -LiteralPath 'frontend\node_modules')) {
    npm --prefix frontend ci
    if ($LASTEXITCODE -ne 0) { throw 'Installation du frontend interrompue.' }
}
npm --prefix frontend run build
if ($LASTEXITCODE -ne 0) { throw 'Construction du frontend interrompue.' }
Write-Host 'Job Hunter : http://127.0.0.1:8000 — Ctrl+C pour arrêter.'
& $pythonExe -m scripts.dashboard
