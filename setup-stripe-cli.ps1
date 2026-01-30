# Stripe CLI Setup Script for Windows
# This script downloads, extracts, and configures Stripe CLI

Write-Host "========================================" -ForegroundColor Cyan
Write-Host "Stripe CLI Setup Script" -ForegroundColor Cyan
Write-Host "========================================" -ForegroundColor Cyan
Write-Host ""

# Step 1: Create C:\stripe directory
Write-Host "Step 1: Creating C:\stripe directory..." -ForegroundColor Yellow
$stripeDir = "C:\stripe"
if (-not (Test-Path $stripeDir)) {
    New-Item -ItemType Directory -Path $stripeDir -Force | Out-Null
    Write-Host "[OK] Created: $stripeDir" -ForegroundColor Green
} else {
    Write-Host "[OK] Directory already exists: $stripeDir" -ForegroundColor Green
}

# Step 2: Download Stripe CLI
Write-Host ""
Write-Host "Step 2: Downloading Stripe CLI..." -ForegroundColor Yellow

try {
    [Net.ServicePointManager]::SecurityProtocol = [Net.SecurityProtocolType]::Tls12
    $releaseInfo = Invoke-RestMethod -Uri "https://api.github.com/repos/stripe/stripe-cli/releases/latest" -Headers @{"Accept"="application/vnd.github.v3+json"}
    $zipAsset = $releaseInfo.assets | Where-Object { $_.name -like "*windows*.zip" }
    
    if (-not $zipAsset) {
        Write-Host "ERROR: Could not find Windows ZIP file in release." -ForegroundColor Red
        Write-Host "Please download manually from: https://github.com/stripe/stripe-cli/releases/latest" -ForegroundColor Yellow
        exit 1
    }
    
    $downloadUrl = $zipAsset.browser_download_url
    $fileName = $zipAsset.name
    $downloadPath = Join-Path $env:TEMP $fileName
    
    Write-Host "Downloading: $fileName" -ForegroundColor Gray
    Invoke-WebRequest -Uri $downloadUrl -OutFile $downloadPath -UseBasicParsing
    Write-Host "[OK] Download complete" -ForegroundColor Green
    
} catch {
    Write-Host "ERROR: Download failed: $_" -ForegroundColor Red
    Write-Host "Please download manually from: https://github.com/stripe/stripe-cli/releases/latest" -ForegroundColor Yellow
    exit 1
}

# Step 3: Extract ZIP
Write-Host ""
Write-Host "Step 3: Extracting ZIP file..." -ForegroundColor Yellow
try {
    Expand-Archive -Path $downloadPath -DestinationPath $stripeDir -Force
    Write-Host "[OK] Extraction complete" -ForegroundColor Green
    
    # Find stripe.exe
    $stripeExe = Get-ChildItem -Path $stripeDir -Recurse -Filter "stripe.exe" | Select-Object -First 1
    
    if ($stripeExe) {
        # Move stripe.exe to C:\stripe\ if it's in a subdirectory
        if ($stripeExe.DirectoryName -ne $stripeDir) {
            Write-Host "Moving stripe.exe to C:\stripe\" -ForegroundColor Yellow
            Move-Item -Path $stripeExe.FullName -Destination (Join-Path $stripeDir "stripe.exe") -Force
            Write-Host "[OK] Moved stripe.exe to C:\stripe\" -ForegroundColor Green
        }
    } else {
        Write-Host "WARNING: Could not find stripe.exe in extracted files" -ForegroundColor Yellow
    }
    
} catch {
    Write-Host "ERROR: Extraction failed: $_" -ForegroundColor Red
    exit 1
}

# Step 4: Add to PATH
Write-Host ""
Write-Host "Step 4: Adding C:\stripe to PATH..." -ForegroundColor Yellow

$currentPath = [Environment]::GetEnvironmentVariable("Path", "User")
if ($currentPath -notlike "*$stripeDir*") {
    [Environment]::SetEnvironmentVariable("Path", "$currentPath;$stripeDir", "User")
    $env:Path += ";$stripeDir"
    Write-Host "[OK] Added C:\stripe to PATH" -ForegroundColor Green
    Write-Host ""
    Write-Host "IMPORTANT: Close and reopen Command Prompt for PATH changes to take effect!" -ForegroundColor Yellow
} else {
    Write-Host "[OK] C:\stripe is already in PATH" -ForegroundColor Green
}

# Step 5: Verify installation
Write-Host ""
Write-Host "Step 5: Verifying installation..." -ForegroundColor Yellow

# Refresh PATH in current session
$env:Path = [System.Environment]::GetEnvironmentVariable("Path", "Machine") + ";" + [System.Environment]::GetEnvironmentVariable("Path", "User")

Start-Sleep -Seconds 1

try {
    $version = & "$stripeDir\stripe.exe" --version 2>&1
    if ($LASTEXITCODE -eq 0) {
        Write-Host "[OK] Stripe CLI is working!" -ForegroundColor Green
        Write-Host "Version: $version" -ForegroundColor Green
    } else {
        Write-Host "WARNING: stripe.exe found but command returned error" -ForegroundColor Yellow
        Write-Host "Please close and reopen Command Prompt, then run: stripe --version" -ForegroundColor Yellow
    }
} catch {
    Write-Host "WARNING: Could not verify automatically" -ForegroundColor Yellow
    Write-Host "Please close and reopen Command Prompt, then run: stripe --version" -ForegroundColor Yellow
}

Write-Host ""
Write-Host "========================================" -ForegroundColor Cyan
Write-Host "Setup Complete!" -ForegroundColor Green
Write-Host "========================================" -ForegroundColor Cyan
Write-Host ""
Write-Host "Next steps:" -ForegroundColor Cyan
Write-Host "1. Close and reopen Command Prompt" -ForegroundColor White
Write-Host "2. Run: stripe --version (to verify)" -ForegroundColor White
Write-Host "3. Run: stripe login" -ForegroundColor White
Write-Host "4. Run: stripe listen --forward-to http://localhost:3000/api/stripe-webhook" -ForegroundColor White
Write-Host ""
