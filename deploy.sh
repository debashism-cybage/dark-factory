#!/bin/bash
#
# Deploy Dark Factory Lambda functions via AWS CLI.
#
# Usage:
#   ./deploy.sh                    # Deploy all
#   ./deploy.sh planning           # Deploy only planning agent
#   ./deploy.sh dashboard-api      # Deploy only dashboard API
#
# Valid targets: planning, architecture, development, validation, release,
#               workflow-starter, dashboard-api

set -e

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------
declare -A LAMBDA_MAP=(
    ["planning"]="agents/planning:planning-agent"
    ["architecture"]="agents/architecture:architecture-agent"
    ["development"]="agents/development:development-agent"
    ["validation"]="agents/validation:validation-agent"
    ["release"]="agents/release:release-agent"
    ["workflow-starter"]="workflow-starter:workflow-starter"
    ["dashboard-api"]="dashboard_api:dashboard-agent"
)

DEPLOY_DIR="./deploy"
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

# ---------------------------------------------------------------------------
# Functions
# ---------------------------------------------------------------------------

# Zip a directory's contents into a zip file, without requiring the `zip`
# CLI to be installed. Git Bash on Windows does not ship `zip` by default,
# so fall back to Python's stdlib zipfile module (Python is already a
# required dependency of this project) when `zip` isn't on PATH.
zip_directory() {
    local src_dir="$1"
    local zip_path="$2"

    if command -v zip >/dev/null 2>&1; then
        (cd "$src_dir" && zip -qr "$zip_path" .)
        return $?
    fi

    if command -v python3 >/dev/null 2>&1; then
        PY=python3
    elif command -v python >/dev/null 2>&1; then
        PY=python
    else
        echo "  ERROR: neither 'zip' nor 'python' is available to create the deployment package."
        return 1
    fi

    "$PY" -c "
import os, sys, zipfile
src_dir, zip_path = sys.argv[1], sys.argv[2]
with zipfile.ZipFile(zip_path, 'w', zipfile.ZIP_DEFLATED) as zf:
    for root, _dirs, files in os.walk(src_dir):
        for f in files:
            full_path = os.path.join(root, f)
            arcname = os.path.relpath(full_path, src_dir)
            zf.write(full_path, arcname)
" "$src_dir" "$zip_path"
}
deploy_lambda() {
    local name="$1"
    local config="${LAMBDA_MAP[$name]}"
    local source_path="${config%%:*}"
    local function_name="${config##*:}"

    echo ""
    echo "========================================"
    echo "  Deploying: $function_name"
    echo "========================================"

    local staging="$DEPLOY_DIR/$name"

    # Clean
    rm -rf "$staging"
    mkdir -p "$staging/shared"

    # Copy ALL Python files from the source folder (not just handler.py)
    cp "$SCRIPT_DIR/$source_path/"*.py "$staging/"

    # Rename handler.py to lambda_function.py (AWS Lambda default)
    if [ -f "$staging/handler.py" ]; then
        mv "$staging/handler.py" "$staging/lambda_function.py"
    fi

    # Copy shared library (including subdirectories)
    cp -r "$SCRIPT_DIR/shared/"* "$staging/shared/"

    # Verify shared exists
    if [ ! -f "$staging/shared/__init__.py" ]; then
        echo "  ERROR: shared/ library not found in package!"
        return 1
    fi

    # Zip
    local zipfile="$DEPLOY_DIR/$name.zip"
    local zipfile_abs="$(cd "$DEPLOY_DIR" && pwd)/$name.zip"
    if ! zip_directory "$staging" "$zipfile_abs"; then
        echo "  ERROR: failed to create deployment package"
        return 1
    fi

    local size=$(du -k "$zipfile" | cut -f1)
    echo "  Package size: ${size} KB"

    # Deploy
    echo "  Uploading to Lambda..."
    aws lambda update-function-code \
        --function-name "$function_name" \
        --zip-file "fileb://$zipfile" \
        --output text --query 'FunctionName' 2>&1

    if [ $? -eq 0 ]; then
        echo "  SUCCESS: $function_name updated"
    else
        echo "  FAILED: $function_name"
        return 1
    fi
}

# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------
echo ""
echo "Dark Factory - Lambda Deployment"
echo "================================"
echo ""

# Verify AWS credentials
echo "Verifying AWS credentials..."
IDENTITY=$(aws sts get-caller-identity --output json 2>&1)
if [ $? -ne 0 ]; then
    echo "ERROR: AWS credentials not configured. Run 'aws configure' or 'aws sso login'."
    exit 1
fi
echo "  $IDENTITY" | grep -o '"Account": "[^"]*"'
echo ""

# Create deploy directory
rm -rf "$DEPLOY_DIR"
mkdir -p "$DEPLOY_DIR"

# Determine which agents to deploy
if [ -z "$1" ] || [ "$1" = "all" ]; then
    AGENTS=("planning" "architecture" "development" "validation" "release" "workflow-starter" "dashboard-api")
else
    AGENTS=("$1")
fi

# Deploy
RESULTS=()
for agent in "${AGENTS[@]}"; do
    if [ -z "${LAMBDA_MAP[$agent]}" ]; then
        echo "ERROR: Unknown target '$agent'"
        echo "Valid options: planning, architecture, development, validation, release, workflow-starter, dashboard-api"
        exit 1
    fi
    if deploy_lambda "$agent"; then
        RESULTS+=("  [OK] ${LAMBDA_MAP[$agent]##*:}")
    else
        RESULTS+=("  [FAIL] ${LAMBDA_MAP[$agent]##*:}")
    fi
done

# Cleanup
rm -rf "$DEPLOY_DIR"

# Summary
echo ""
echo "========================================"
echo "  Deployment Summary"
echo "========================================"
for r in "${RESULTS[@]}"; do
    echo "$r"
done
echo ""
