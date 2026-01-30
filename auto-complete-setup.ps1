# Auto-Complete Stripe Webhook Setup
# This script captures the webhook secret and updates .env.local

Write-Host "========================================" -ForegroundColor Cyan
Write-Host "Auto-Complete Stripe Webhook Setup" -ForegroundColor Cyan
Write-Host "========================================" -ForegroundColor Cyan
Write-Host ""

# Step 1: Verify Stripe CLI
Write-Host "Step 1: Verifying Stripe CLI..." -ForegroundColor Yellow
try {
    $version = & "C:\stripe\stripe.exe" --version 2>&1
    if ($LASTEXITCODE -eq 0) {
        Write-Host "[OK] Stripe CLI: $version" -ForegroundColor Green
    } else {
        Write-Host "[ERROR] Stripe CLI not working" -ForegroundColor Red
        exit 1
    }
} catch {
    Write-Host "[ERROR] Stripe CLI not found" -ForegroundColor Red
    exit 1
}

Write-Host ""

# Step 2: Start webhook listener and capture secret
Write-Host "Step 2: Starting webhook listener to capture secret..." -ForegroundColor Yellow
Write-Host "This may take a few seconds..." -ForegroundColor Gray
Write-Host ""

$envFile = "C:\Users\The Yoda Trader\easygiveqr-web\.env.local"

# Create a temporary script to run stripe listen and capture output
$tempScript = @"
`$process = Start-Process -FilePath "C:\stripe\stripe.exe" -ArgumentList "listen", "--forward-to", "http://localhost:3000/api/stripe-webhook" -NoNewWindow -PassThru -RedirectStandardOutput "$env:TEMP\stripe_webhook_output.txt" -RedirectStandardError "$env:TEMP\stripe_webhook_error.txt"
Start-Sleep -Seconds 5
if (Test-Path "$env:TEMP\stripe_webhook_output.txt") {
    `$content = Get-Content "$env:TEMP\stripe_webhook_output.txt" -ErrorAction SilentlyContinue
    `$secretLine = `$content | Select-String -Pattern "whsec_\w+" | Select-Object -First 1
    if (`$secretLine) {
        `$matches = [regex]::Matches(`$secretLine, "whsec_\w+")
        if (`$matches.Count -gt 0) {
            `$matches[0].Value
        }
    }
}
Stop-Process -Id `$process.Id -Force -ErrorAction SilentlyContinue
"@

$tempScriptPath = "$env:TEMP\capture_secret.ps1"
$tempScript | Set-Content $tempScriptPath

try {
    $webhookSecret = & powershell -ExecutionPolicy Bypass -File $tempScriptPath
    
    if ($webhookSecret -and $webhookSecret -match "whsec_\w+") {
        Write-Host "[OK] Captured webhook secret: $webhookSecret" -ForegroundColor Green
        Write-Host ""
        
        # Step 3: Update .env.local
        Write-Host "Step 3: Updating .env.local..." -ForegroundColor Yellow
        
        if (Test-Path $envFile) {
            $content = Get-Content $envFile
            $updated = $false
            $newContent = @()
            
            foreach ($line in $content) {
                if ($line -match "^STRIPE_WEBHOOK_SECRET=") {
                    $newContent += "STRIPE_WEBHOOK_SECRET=$webhookSecret"
                    $updated = $true
                } else {
                    $newContent += $line
                }
            }
            
            if (-not $updated) {
                $newContent += "STRIPE_WEBHOOK_SECRET=$webhookSecret"
            }
            
            $newContent | Set-Content $envFile
            Write-Host "[OK] Updated .env.local with webhook secret" -ForegroundColor Green
        } else {
            Write-Host "[ERROR] .env.local not found" -ForegroundColor Red
            exit 1
        }
        
        Write-Host ""
        Write-Host "========================================" -ForegroundColor Cyan
        Write-Host "Setup Complete!" -ForegroundColor Green
        Write-Host "========================================" -ForegroundColor Cyan
        Write-Host ""
        Write-Host "Next steps:" -ForegroundColor Cyan
        Write-Host "1. Start webhook listener (new terminal):" -ForegroundColor White
        Write-Host "   stripe listen --forward-to http://localhost:3000/api/stripe-webhook" -ForegroundColor Yellow
        Write-Host ""
        Write-Host "2. Restart Next.js (if running):" -ForegroundColor White
        Write-Host "   npm run dev" -ForegroundColor Yellow
        Write-Host ""
        Write-Host "3. Test at:" -ForegroundColor White
        Write-Host "   http://localhost:3000/donate?church_id=EGQR-123" -ForegroundColor Yellow
        Write-Host ""
        
    } else {
        Write-Host "[WARNING] Could not automatically capture webhook secret" -ForegroundColor Yellow
        Write-Host ""
        Write-Host "Please run manually:" -ForegroundColor Cyan
        Write-Host "1. stripe listen --forward-to http://localhost:3000/api/stripe-webhook" -ForegroundColor White
        Write-Host "2. Copy the whsec_... value" -ForegroundColor White
        Write-Host "3. Run: .\update-webhook-secret.ps1 -Secret 'whsec_...'" -ForegroundColor White
        Write-Host ""
    }
} catch {
    Write-Host "[ERROR] Failed to capture secret: $_" -ForegroundColor Red
    Write-Host ""
    Write-Host "Please run manually:" -ForegroundColor Cyan
    Write-Host "1. stripe listen --forward-to http://localhost:3000/api/stripe-webhook" -ForegroundColor White
    Write-Host "2. Copy the whsec_... value" -ForegroundColor White
    Write-Host "3. Run: .\update-webhook-secret.ps1 -Secret 'whsec_...'" -ForegroundColor White
}

# Cleanup
Remove-Item $tempScriptPath -ErrorAction SilentlyContinue
