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
    (cd "$staging" && zip -qr "../$name.zip" .)

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
