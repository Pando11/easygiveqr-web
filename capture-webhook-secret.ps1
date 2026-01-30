# Capture Webhook Secret from Stripe Listen Output
# This script starts stripe listen, captures the secret, and updates .env.local

param(
    [string]$WebhookSecret = ""
)

$envFile = "C:\Users\The Yoda Trader\easygiveqr-web\.env.local"

if ($WebhookSecret -eq "") {
    Write-Host "========================================" -ForegroundColor Cyan
    Write-Host "Stripe Webhook Secret Capture" -ForegroundColor Cyan
    Write-Host "========================================" -ForegroundColor Cyan
    Write-Host ""
    Write-Host "This script will:" -ForegroundColor Yellow
    Write-Host "1. Start stripe listen" -ForegroundColor White
    Write-Host "2. Capture the webhook secret (whsec_...)" -ForegroundColor White
    Write-Host "3. Update .env.local automatically" -ForegroundColor White
    Write-Host ""
    Write-Host "Press Ctrl+C to stop stripe listen after you see the secret" -ForegroundColor Yellow
    Write-Host ""
    
    # Start stripe listen and capture output
    Write-Host "Starting stripe listen..." -ForegroundColor Cyan
    Write-Host ""
    
    $process = Start-Process -FilePath "stripe" -ArgumentList "listen", "--forward-to", "http://localhost:3000/api/stripe-webhook" -NoNewWindow -PassThru -RedirectStandardOutput "$env:TEMP\stripe_output.txt" -RedirectStandardError "$env:TEMP\stripe_error.txt"
    
    Write-Host "Waiting for webhook secret..." -ForegroundColor Yellow
    Write-Host "Look for the line: 'Ready! Your webhook signing secret is whsec_...'" -ForegroundColor Yellow
    Write-Host ""
    Write-Host "Once you see the secret, press Ctrl+C, then run this script again with:" -ForegroundColor Yellow
    Write-Host "  .\capture-webhook-secret.ps1 -WebhookSecret 'whsec_...'" -ForegroundColor White
    Write-Host ""
    
    # Wait a bit and try to read output
    Start-Sleep -Seconds 3
    
    if (Test-Path "$env:TEMP\stripe_output.txt") {
        $output = Get-Content "$env:TEMP\stripe_output.txt" -ErrorAction SilentlyContinue
        $secretLine = $output | Select-String -Pattern "whsec_\w+" | Select-Object -First 1
        if ($secretLine) {
            $matches = [regex]::Matches($secretLine, "whsec_\w+")
            if ($matches.Count -gt 0) {
                $WebhookSecret = $matches[0].Value
                Write-Host "Found secret: $WebhookSecret" -ForegroundColor Green
            }
        }
    }
    
    if ($WebhookSecret -eq "") {
        Write-Host "Could not automatically capture secret." -ForegroundColor Yellow
        Write-Host "Please run stripe listen manually and copy the whsec_... value" -ForegroundColor Yellow
        Write-Host "Then run: .\capture-webhook-secret.ps1 -WebhookSecret 'whsec_...'" -ForegroundColor White
        exit 1
    }
}

# Update .env.local
Write-Host ""
Write-Host "Updating .env.local..." -ForegroundColor Cyan

if (Test-Path $envFile) {
    $content = Get-Content $envFile
    
    # Check if STRIPE_WEBHOOK_SECRET already exists
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
    Write-Host "[OK] Updated .env.local with STRIPE_WEBHOOK_SECRET" -ForegroundColor Green
} else {
    Write-Host "ERROR: .env.local not found at $envFile" -ForegroundColor Red
    exit 1
}

Write-Host ""
Write-Host "========================================" -ForegroundColor Cyan
Write-Host "Next Steps:" -ForegroundColor Cyan
Write-Host "1. Restart your Next.js dev server (npm run dev)" -ForegroundColor White
Write-Host "2. Test at: http://localhost:3000/donate?church_id=EGQR-123" -ForegroundColor White
Write-Host "========================================" -ForegroundColor Cyan
