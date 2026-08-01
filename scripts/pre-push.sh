#!/bin/bash
# Pre-push hook: mirrors the CI lint-and-test job.
# Install: cp scripts/pre-push.sh .git/hooks/pre-push && chmod +x .git/hooks/pre-push

set -e

# Add Python user scripts to PATH (where ruff, mypy, pytest are installed)
export PATH="$APPDATA/Python/Python314/Scripts:$PATH"
export PATH="/c/Python314/Scripts:$PATH"
export PATH="/c/Python314:$PATH"

echo "=== Pre-push verification ==="
echo ""

echo "[1/4] Ruff check..."
ruff check shared/ agents/ workflow-starter/

echo "[2/4] Ruff format..."
ruff format --check shared/ agents/ workflow-starter/

echo "[3/4] Mypy type check..."
mypy shared/ --ignore-missing-imports

echo "[4/4] Pytest..."
pytest tests/ -v --cov=shared --cov-report=term-missing

echo ""
echo "=== All checks passed. Pushing. ==="
