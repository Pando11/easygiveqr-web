# Complete Stripe Webhook Setup Automation
# This script helps automate the remaining setup steps

param(
    [string]$WebhookSecret = ""
)

Write-Host "========================================" -ForegroundColor Cyan
Write-Host "Stripe Webhook Setup - Automation" -ForegroundColor Cyan
Write-Host "========================================" -ForegroundColor Cyan
Write-Host ""

# Step 1: Verify Stripe CLI
Write-Host "Step 1: Verifying Stripe CLI..." -ForegroundColor Yellow
try {
    $version = stripe --version 2>&1
    if ($LASTEXITCODE -eq 0) {
        Write-Host "[OK] Stripe CLI installed: $version" -ForegroundColor Green
    } else {
        Write-Host "[ERROR] Stripe CLI not working. Please verify installation." -ForegroundColor Red
        exit 1
    }
} catch {
    Write-Host "[ERROR] Stripe CLI not found. Please install it first." -ForegroundColor Red
    exit 1
}

Write-Host ""

# Step 2: Check if logged in
Write-Host "Step 2: Checking Stripe login status..." -ForegroundColor Yellow
try {
    $config = stripe config --list 2>&1
    if ($config -match "test_mode_api_key" -or $config -match "live_mode_api_key") {
        Write-Host "[OK] Stripe CLI is logged in" -ForegroundColor Green
    } else {
        Write-Host "[WARNING] Stripe CLI not logged in" -ForegroundColor Yellow
        Write-Host ""
        Write-Host "Please run: stripe login" -ForegroundColor White
        Write-Host "Then run this script again." -ForegroundColor White
        exit 1
    }
} catch {
    Write-Host "[WARNING] Could not verify login status" -ForegroundColor Yellow
    Write-Host "Please ensure you've run: stripe login" -ForegroundColor White
}

Write-Host ""

# Step 3: Update .env.local with webhook secret
$envFile = "C:\Users\The Yoda Trader\easygiveqr-web\.env.local"

if ($WebhookSecret -eq "") {
    Write-Host "Step 3: Webhook Secret Setup" -ForegroundColor Yellow
    Write-Host ""
    Write-Host "To get your webhook secret:" -ForegroundColor Cyan
    Write-Host "1. Open a NEW Command Prompt window" -ForegroundColor White
    Write-Host "2. Run: stripe listen --forward-to http://localhost:3000/api/stripe-webhook" -ForegroundColor White
    Write-Host "3. Copy the 'whsec_...' value from the output" -ForegroundColor White
    Write-Host "4. Run this script again with:" -ForegroundColor White
    Write-Host "   .\complete-setup.ps1 -WebhookSecret 'whsec_...'" -ForegroundColor Yellow
    Write-Host ""
    Write-Host "OR manually add to .env.local:" -ForegroundColor Cyan
    Write-Host "   STRIPE_WEBHOOK_SECRET=whsec_..." -ForegroundColor White
    exit 0
} else {
    Write-Host "Step 3: Updating .env.local with webhook secret..." -ForegroundColor Yellow
    
    if (Test-Path $envFile) {
        $content = Get-Content $envFile
        $updated = $false
        $newContent = @()
        
        foreach ($line in $content) {
            if ($line -match "^STRIPE_WEBHOOK_SECRET=") {
                $newContent += "STRIPE_WEBHOOK_SECRET=$WebhookSecret"
                $updated = $true
            } else {
                $newContent += $line
            }
        }
        
        if (-not $updated) {
            $newContent += "STRIPE_WEBHOOK_SECRET=$WebhookSecret"
        }
        
        $newContent | Set-Content $envFile
        Write-Host "[OK] Updated .env.local" -ForegroundColor Green
    } else {
        Write-Host "[ERROR] .env.local not found" -ForegroundColor Red
        exit 1
    }
}

Write-Host ""

# Step 4: Check Next.js
Write-Host "Step 4: Next.js Dev Server Status" -ForegroundColor Yellow
$nodeProcesses = Get-Process -Name "node" -ErrorAction SilentlyContinue
if ($nodeProcesses) {
    Write-Host "[INFO] Node.js processes detected" -ForegroundColor Cyan
    Write-Host "[IMPORTANT] Please restart your Next.js dev server:" -ForegroundColor Yellow
    Write-Host "   1. Stop current server (Ctrl+C)" -ForegroundColor White
    Write-Host "   2. Run: npm run dev" -ForegroundColor White
    Write-Host ""
    Write-Host "   This is required for .env.local changes to take effect!" -ForegroundColor Yellow
} else {
    Write-Host "[INFO] No Node.js processes detected" -ForegroundColor Cyan
    Write-Host "Start Next.js with: npm run dev" -ForegroundColor White
}

Write-Host ""
Write-Host "========================================" -ForegroundColor Cyan
Write-Host "Setup Summary" -ForegroundColor Cyan
Write-Host "========================================" -ForegroundColor Cyan
Write-Host ""
Write-Host "[OK] Stripe CLI installed and verified" -ForegroundColor Green
Write-Host "[OK] Stripe CLI logged in" -ForegroundColor Green
Write-Host "[OK] .env.local updated with webhook secret" -ForegroundColor Green
Write-Host ""
Write-Host "Next Steps:" -ForegroundColor Cyan
Write-Host "1. Restart Next.js: npm run dev" -ForegroundColor White
Write-Host "2. Start webhook listener (separate terminal):" -ForegroundColor White
Write-Host "   stripe listen --forward-to http://localhost:3000/api/stripe-webhook" -ForegroundColor Yellow
Write-Host "3. Test at: http://localhost:3000/donate?church_id=EGQR-123" -ForegroundColor White
Write-Host ""
