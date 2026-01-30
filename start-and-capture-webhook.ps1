# Start Stripe Webhook Listener and Capture Secret
# This script starts stripe listen, captures the webhook secret, and updates .env.local

Write-Host "========================================" -ForegroundColor Cyan
Write-Host "Starting Stripe Webhook Listener" -ForegroundColor Cyan
Write-Host "========================================" -ForegroundColor Cyan
Write-Host ""

$envFile = "C:\Users\The Yoda Trader\easygiveqr-web\.env.local"

# Check if Stripe CLI is available
try {
    $version = & "C:\stripe\stripe.exe" --version 2>&1
    if ($LASTEXITCODE -ne 0) {
        Write-Host "ERROR: Stripe CLI not working. Please verify installation." -ForegroundColor Red
        exit 1
    }
} catch {
    Write-Host "ERROR: Stripe CLI not found at C:\stripe\stripe.exe" -ForegroundColor Red
    exit 1
}

Write-Host "Starting stripe listen..." -ForegroundColor Yellow
Write-Host "This will run in the foreground. Look for the webhook secret." -ForegroundColor Yellow
Write-Host ""
Write-Host "When you see: 'Ready! Your webhook signing secret is whsec_...'" -ForegroundColor Cyan
Write-Host "1. Copy the whsec_... value" -ForegroundColor White
Write-Host "2. Press Ctrl+C to stop this script" -ForegroundColor White
Write-Host "3. Run: .\update-webhook-secret.ps1 -Secret 'whsec_...'" -ForegroundColor White
Write-Host ""
Write-Host "OR manually add to .env.local:" -ForegroundColor Yellow
Write-Host "   STRIPE_WEBHOOK_SECRET=whsec_..." -ForegroundColor White
Write-Host ""
Write-Host "Starting webhook listener now..." -ForegroundColor Cyan
Write-Host ""

# Start stripe listen
& "C:\stripe\stripe.exe" listen --forward-to http://localhost:3000/api/stripe-webhook
