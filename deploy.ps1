<#
.SYNOPSIS
    Deploy Dark Factory Lambda functions via AWS CLI.

.DESCRIPTION
    Packages each agent handler with the shared/ library and deploys
    to AWS Lambda using update-function-code.

.PARAMETER Agent
    Deploy a specific agent. Options: all, planning, architecture, development,
    validation, release, workflow-starter.
    Default: all

.EXAMPLE
    .\deploy.ps1                    # Deploy all
    .\deploy.ps1 -Agent planning    # Deploy only planning agent
#>

param(
    [ValidateSet("all", "planning", "architecture", "development", "validation", "release", "workflow-starter")]
    [string]$Agent = "all"
)

$ErrorActionPreference = "Stop"

# ---------------------------------------------------------------------------
# Configuration: Map local folders to AWS Lambda function names
# ---------------------------------------------------------------------------
$LambdaMap = @{
    "planning"         = @{ Source = "agents\planning";      FunctionName = "planning-agent" }
    "architecture"     = @{ Source = "agents\architecture";  FunctionName = "architecture-agent" }
    "development"      = @{ Source = "agents\development";   FunctionName = "development-agent" }
    "validation"       = @{ Source = "agents\validation";    FunctionName = "validation-agent" }
    "release"          = @{ Source = "agents\release";       FunctionName = "release-agent" }
    "workflow-starter" = @{ Source = "workflow-starter";      FunctionName = "workflow-starter" }
}

$DeployDir = Join-Path $PSScriptRoot "deploy"
$SharedDir = Join-Path $PSScriptRoot "shared"
$ProjectRoot = $PSScriptRoot

if (-not $ProjectRoot) {
    $ProjectRoot = (Get-Location).Path
    $DeployDir = Join-Path $ProjectRoot "deploy"
    $SharedDir = Join-Path $ProjectRoot "shared"
}

# ---------------------------------------------------------------------------
# Functions
# ---------------------------------------------------------------------------

function Deploy-Lambda {
    param(
        [string]$Name,
        [string]$SourcePath,
        [string]$FunctionName
    )

    Write-Host ""
    Write-Host "========================================" -ForegroundColor Cyan
    Write-Host "  Deploying: $FunctionName" -ForegroundColor Cyan
    Write-Host "========================================" -ForegroundColor Cyan

    $stagingDir = Join-Path $DeployDir $Name
    $zipFile = Join-Path $DeployDir "$Name.zip"

    # Clean previous
    if (Test-Path $stagingDir) { Remove-Item -Recurse -Force $stagingDir }
    if (Test-Path $zipFile) { Remove-Item -Force $zipFile }

    # Create staging directory
    New-Item -ItemType Directory -Path $stagingDir -Force | Out-Null

    # Copy handler(s)
    $handlerSource = Join-Path $ProjectRoot $SourcePath
    Get-ChildItem -Path $handlerSource -Filter "*.py" | ForEach-Object {
        Copy-Item $_.FullName $stagingDir
    }

    # Rename handler.py to lambda_function.py (AWS Lambda default)
    $handlerFile = Join-Path $stagingDir "handler.py"
    $lambdaFile = Join-Path $stagingDir "lambda_function.py"
    if (Test-Path $handlerFile) {
        # Read content and replace the handler reference
        $content = Get-Content $handlerFile -Raw
        Move-Item $handlerFile $lambdaFile
    }

    # Copy shared library
    $sharedDest = Join-Path $stagingDir "shared"
    Copy-Item -Recurse -Force $SharedDir $sharedDest

    # Verify shared was copied
    if (-not (Test-Path (Join-Path $sharedDest "__init__.py"))) {
        Write-Host "  ERROR: shared/ library not found in package!" -ForegroundColor Red
        return $false
    }

    # Create zip
    Compress-Archive -Path "$stagingDir\*" -DestinationPath $zipFile -Force

    $zipSize = [math]::Round((Get-Item $zipFile).Length / 1KB, 1)
    Write-Host "  Package size: ${zipSize} KB" -ForegroundColor Gray

    # Deploy to AWS
    Write-Host "  Uploading to Lambda..." -ForegroundColor Yellow
    aws lambda update-function-code `
        --function-name $FunctionName `
        --zip-file "fileb://$zipFile" `
        --output text --query 'FunctionName' 2>&1

    if ($LASTEXITCODE -eq 0) {
        Write-Host "  SUCCESS: $FunctionName updated" -ForegroundColor Green
    } else {
        Write-Host "  FAILED: $FunctionName" -ForegroundColor Red
        return $false
    }

    return $true
}

# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

Write-Host ""
Write-Host "Dark Factory - Lambda Deployment" -ForegroundColor White
Write-Host "================================" -ForegroundColor White
Write-Host ""

# Verify AWS credentials
Write-Host "Verifying AWS credentials..." -ForegroundColor Gray
$identity = aws sts get-caller-identity --output json 2>&1 | ConvertFrom-Json
if (-not $identity.Account) {
    Write-Host "ERROR: AWS credentials not configured. Run 'aws configure' or 'aws sso login'." -ForegroundColor Red
    exit 1
}
Write-Host "  Account: $($identity.Account)" -ForegroundColor Gray
Write-Host "  Identity: $($identity.Arn)" -ForegroundColor Gray

# Create deploy directory
if (-not (Test-Path $DeployDir)) {
    New-Item -ItemType Directory -Path $DeployDir -Force | Out-Null
}

# Determine which agents to deploy
if ($Agent -eq "all") {
    $toDeploy = $LambdaMap.Keys
} else {
    $toDeploy = @($Agent)
}

$results = @()

foreach ($name in $toDeploy) {
    $config = $LambdaMap[$name]
    $success = Deploy-Lambda -Name $name -SourcePath $config.Source -FunctionName $config.FunctionName
    $results += @{ Name = $config.FunctionName; Success = $success }
}

# Cleanup
if (Test-Path $DeployDir) {
    Remove-Item -Recurse -Force $DeployDir
}

# Summary
Write-Host ""
Write-Host "========================================" -ForegroundColor White
Write-Host "  Deployment Summary" -ForegroundColor White
Write-Host "========================================" -ForegroundColor White

foreach ($r in $results) {
    $icon = if ($r.Success) { "[OK]" } else { "[FAIL]" }
    $color = if ($r.Success) { "Green" } else { "Red" }
    Write-Host "  $icon $($r.Name)" -ForegroundColor $color
}

Write-Host ""
