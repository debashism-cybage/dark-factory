# Pre-push hook (PowerShell version): mirrors the CI lint-and-test job.
# Install: Copy-Item scripts\pre-push.ps1 .git\hooks\pre-push.ps1

$ErrorActionPreference = "Stop"

Write-Host "=== Pre-push verification ===" -ForegroundColor Cyan
Write-Host ""

Write-Host "[1/4] Ruff check..." -ForegroundColor Yellow
ruff check shared/ agents/ workflow-starter/
if ($LASTEXITCODE -ne 0) { Write-Host "FAILED: ruff check" -ForegroundColor Red; exit 1 }

Write-Host "[2/4] Ruff format..." -ForegroundColor Yellow
ruff format --check shared/ agents/ workflow-starter/
if ($LASTEXITCODE -ne 0) { Write-Host "FAILED: ruff format" -ForegroundColor Red; exit 1 }

Write-Host "[3/4] Mypy type check..." -ForegroundColor Yellow
mypy shared/ --ignore-missing-imports
if ($LASTEXITCODE -ne 0) { Write-Host "FAILED: mypy" -ForegroundColor Red; exit 1 }

Write-Host "[4/4] Pytest..." -ForegroundColor Yellow
pytest tests/ -v --cov=shared --cov-report=term-missing
if ($LASTEXITCODE -ne 0) { Write-Host "FAILED: pytest" -ForegroundColor Red; exit 1 }

Write-Host ""
Write-Host "=== All checks passed. Pushing. ===" -ForegroundColor Green
