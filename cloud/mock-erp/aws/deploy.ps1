param(
    [string]$StackName = "fresh-food-mock-erp",
    [string]$Region = "ap-northeast-2"
)

$ErrorActionPreference = "Stop"
$awsDirectory = Split-Path -Parent $MyInvocation.MyCommand.Path

if (-not (Get-Command aws -ErrorAction SilentlyContinue)) {
    throw "AWS CLI v2 is required. Install it and run 'aws configure' first."
}
if (-not (Get-Command sam -ErrorAction SilentlyContinue)) {
    throw "AWS SAM CLI is required."
}

$identity = aws sts get-caller-identity --region $Region | ConvertFrom-Json
Write-Host "AWS account: $($identity.Account)"
Write-Host "Caller ARN: $($identity.Arn)"
Write-Host "Region: $Region"
Write-Warning "This deployment creates a billable RDS PostgreSQL instance."

$confirmation = Read-Host "Type DEPLOY to continue"
if ($confirmation -cne "DEPLOY") {
    throw "Deployment cancelled."
}

$dbPasswordSecure = Read-Host "RDS master password (12+ characters)" -AsSecureString
$erpTokenSecure = Read-Host "ERP shared token (24+ characters)" -AsSecureString
$dbPassword = [System.Net.NetworkCredential]::new("", $dbPasswordSecure).Password
$erpToken = [System.Net.NetworkCredential]::new("", $erpTokenSecure).Password

if ($dbPassword.Length -lt 12) {
    throw "RDS password must contain at least 12 characters."
}
if ($erpToken.Length -lt 24) {
    throw "ERP shared token must contain at least 24 characters."
}

Push-Location $awsDirectory
try {
    sam build
    sam deploy `
        --stack-name $StackName `
        --region $Region `
        --resolve-s3 `
        --capabilities CAPABILITY_IAM `
        --parameter-overrides `
            "DbMasterPassword=$dbPassword" `
            "ErpSharedToken=$erpToken" `
        --no-fail-on-empty-changeset

    $syncUrl = aws cloudformation describe-stacks `
        --stack-name $StackName `
        --region $Region `
        --query "Stacks[0].Outputs[?OutputKey=='SyncUrl'].OutputValue" `
        --output text

    Write-Host ""
    Write-Host "Deployment completed."
    Write-Host "Set these values in the PowerShell window that runs the Mock ERP:"
    Write-Host "`$env:AWS_SYNC_URL='$syncUrl'"
    Write-Host "`$env:ERP_SHARED_TOKEN='<the shared token entered above>'"
} finally {
    $dbPassword = $null
    $erpToken = $null
    Pop-Location
}
