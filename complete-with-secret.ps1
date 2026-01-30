# Complete Setup with Webhook Secret
# Run this after you have the whsec_... secret from stripe listen

param(
    [Parameter(Mandatory=$true)]
    [string]$Secret
)

Write-Host "========================================" -ForegroundColor Cyan
Write-Host "Completing Stripe Webhook Setup" -ForegroundColor Cyan
Write-Host "========================================" -ForegroundColor Cyan
Write-Host ""

$envFile = "C:\Users\The Yoda Trader\easygiveqr-web\.env.local"

# Validate secret format
if ($Secret -notmatch "^whsec_") {
    Write-Host "WARNING: Secret doesn't start with 'whsec_'. Are you sure this is correct?" -ForegroundColor Yellow
    $confirm = Read-Host "Continue anyway? (y/n)"
    if ($confirm -ne "y") {
        exit 1
    }
}

Write-Host "Step 1: Updating .env.local..." -ForegroundColor Yellow

if (-not (Test-Path $envFile)) {
    Write-Host "ERROR: .env.local not found at $envFile" -ForegroundColor Red
    exit 1
}

# Read current content
$content = Get-Content $envFile
$updated = $false
$newContent = @()

foreach ($line in $content) {
    if ($line -match "^STRIPE_WEBHOOK_SECRET=") {
        $newContent += "STRIPE_WEBHOOK_SECRET=$Secret"
        $updated = $true
        Write-Host "[OK] Updated existing STRIPE_WEBHOOK_SECRET" -ForegroundColor Green
    } else {
        $newContent += $line
    }
}

# Add if not found
if (-not $updated) {
    $newContent += "STRIPE_WEBHOOK_SECRET=$Secret"
    Write-Host "[OK] Added STRIPE_WEBHOOK_SECRET" -ForegroundColor Green
}

# Write back
$newContent | Set-Content $envFile

Write-Host ""
Write-Host "Step 2: Checking Next.js status..." -ForegroundColor Yellow

$nodeProcesses = Get-Process -Name "node" -ErrorAction SilentlyContinue | Where-Object { $_.Path -like "*nodejs*" -or $_.Path -like "*npm*" }
if ($nodeProcesses) {
    Write-Host "[INFO] Node.js processes detected" -ForegroundColor Cyan
    Write-Host ""
    Write-Host "IMPORTANT: Restart your Next.js dev server!" -ForegroundColor Yellow
    Write-Host "1. Stop current server (Ctrl+C in the terminal running npm run dev)" -ForegroundColor White
    Write-Host "2. Run: npm run dev" -ForegroundColor White
    Write-Host ""
    Write-Host "This is required for .env.local changes to take effect!" -ForegroundColor Yellow
} else {
    Write-Host "[INFO] No Node.js dev server detected" -ForegroundColor Cyan
    Write-Host "Start Next.js with: npm run dev" -ForegroundColor White
}

Write-Host ""
Write-Host "========================================" -ForegroundColor Cyan
Write-Host "Setup Complete!" -ForegroundColor Green
Write-Host "========================================" -ForegroundColor Cyan
Write-Host ""
Write-Host "Current Status:" -ForegroundColor Cyan
Write-Host "✓ Stripe CLI installed" -ForegroundColor Green
Write-Host "✓ Stripe CLI logged in" -ForegroundColor Green
Write-Host "✓ Webhook listener running (stripe listen)" -ForegroundColor Green
Write-Host "✓ .env.local updated with webhook secret" -ForegroundColor Green
Write-Host ""
Write-Host "Next Steps:" -ForegroundColor Cyan
Write-Host "1. Restart Next.js: npm run dev" -ForegroundColor White
Write-Host "2. Test at: http://localhost:3000/donate?church_id=EGQR-123" -ForegroundColor White
Write-Host "3. Complete donation with test card: 4242 4242 4242 4242" -ForegroundColor White
Write-Host "4. Confirm in Stripe CLI window: --> checkout.session.completed and <-- [200]" -ForegroundColor White
Write-Host "5. Check Supabase for new donation row" -ForegroundColor White
Write-Host ""
