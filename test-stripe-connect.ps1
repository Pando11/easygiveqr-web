# Test Stripe Connect Endpoints
# This script tests the Stripe Connect onboarding flow

param(
    [string]$ChurchId = "EGQR-123",
    [string]$Action = "all"
)

Write-Host "========================================" -ForegroundColor Cyan
Write-Host "Testing Stripe Connect" -ForegroundColor Cyan
Write-Host "========================================" -ForegroundColor Cyan
Write-Host ""

$baseUrl = "http://localhost:3000"
$headers = @{ "Content-Type" = "application/json" }

function Test-CreateAccount {
    Write-Host "Step 1: Creating Connected Account..." -ForegroundColor Yellow
    
    $body = @{ church_id = $ChurchId } | ConvertTo-Json
    
    try {
        $response = Invoke-RestMethod -Uri "$baseUrl/api/connect/create-account" -Method POST -Headers $headers -Body $body
        if ($response.ok) {
            Write-Host "[OK] Account created: $($response.stripe_account_id)" -ForegroundColor Green
            return $response.stripe_account_id
        } else {
            Write-Host "[ERROR] $($response.error)" -ForegroundColor Red
            return $null
        }
    } catch {
        Write-Host "[ERROR] $_" -ForegroundColor Red
        return $null
    }
}

function Test-OnboardingLink {
    param([string]$AccountId)
    
    if (-not $AccountId) {
        Write-Host "[SKIP] No account ID, skipping onboarding link" -ForegroundColor Yellow
        return
    }
    
    Write-Host ""
    Write-Host "Step 2: Generating Onboarding Link..." -ForegroundColor Yellow
    
    $body = @{
        church_id = $ChurchId
        return_url = "http://localhost:3000/onboarding/complete"
        refresh_url = "http://localhost:3000/onboarding"
    } | ConvertTo-Json
    
    try {
        $response = Invoke-RestMethod -Uri "$baseUrl/api/connect/onboarding-link" -Method POST -Headers $headers -Body $body
        if ($response.ok) {
            Write-Host "[OK] Onboarding URL generated" -ForegroundColor Green
            Write-Host "URL: $($response.url)" -ForegroundColor Cyan
            Write-Host ""
            Write-Host "Open this URL in your browser to complete onboarding:" -ForegroundColor Yellow
            Write-Host $response.url -ForegroundColor White
            return $response.url
        } else {
            Write-Host "[ERROR] $($response.error)" -ForegroundColor Red
            return $null
        }
    } catch {
        Write-Host "[ERROR] $_" -ForegroundColor Red
        return $null
    }
}

function Test-SyncStatus {
    Write-Host ""
    Write-Host "Step 3: Syncing Account Status..." -ForegroundColor Yellow
    
    $body = @{ church_id = $ChurchId } | ConvertTo-Json
    
    try {
        $response = Invoke-RestMethod -Uri "$baseUrl/api/connect/sync-status" -Method POST -Headers $headers -Body $body
        if ($response.ok) {
            Write-Host "[OK] Status synced" -ForegroundColor Green
            Write-Host "Account ID: $($response.status.stripe_account_id)" -ForegroundColor Cyan
            Write-Host "Onboarding Status: $($response.status.onboarding_status)" -ForegroundColor Cyan
            Write-Host "Charges Enabled: $($response.status.charges_enabled)" -ForegroundColor Cyan
            Write-Host "Payouts Enabled: $($response.status.payouts_enabled)" -ForegroundColor Cyan
            Write-Host "Details Submitted: $($response.status.details_submitted)" -ForegroundColor Cyan
            return $response.status
        } else {
            Write-Host "[ERROR] $($response.error)" -ForegroundColor Red
            return $null
        }
    } catch {
        Write-Host "[ERROR] $_" -ForegroundColor Red
        return $null
    }
}

function Test-WednesdayPayouts {
    Write-Host ""
    Write-Host "Step 4: Testing Wednesday Payouts Job..." -ForegroundColor Yellow
    
    $cronSecret = $env:CRON_SECRET
    if (-not $cronSecret) {
        $cronSecret = Read-Host "Enter CRON_SECRET"
    }
    
    $cronHeaders = @{
        "x-cron-secret" = $cronSecret
        "Content-Type" = "application/json"
    }
    
    try {
        $response = Invoke-RestMethod -Uri "$baseUrl/api/jobs/wednesday-payouts" -Method POST -Headers $cronHeaders
        if ($response.ok) {
            Write-Host "[OK] Payout job completed" -ForegroundColor Green
            Write-Host "Churches processed: $($response.summary.churchesProcessed)" -ForegroundColor Cyan
            Write-Host "Emails sent: $($response.summary.emailsSent)" -ForegroundColor Cyan
            Write-Host "Failures: $($response.summary.failures)" -ForegroundColor Cyan
        } else {
            Write-Host "[ERROR] $($response.error)" -ForegroundColor Red
        }
    } catch {
        Write-Host "[ERROR] $_" -ForegroundColor Red
    }
}

# Main execution
switch ($Action.ToLower()) {
    "create" {
        Test-CreateAccount
    }
    "onboarding" {
        $accountId = Test-CreateAccount
        Test-OnboardingLink -AccountId $accountId
    }
    "sync" {
        Test-SyncStatus
    }
    "payouts" {
        Test-WednesdayPayouts
    }
    default {
        $accountId = Test-CreateAccount
        $onboardingUrl = Test-OnboardingLink -AccountId $accountId
        Start-Sleep -Seconds 2
        Test-SyncStatus
        
        Write-Host ""
        Write-Host "========================================" -ForegroundColor Cyan
        Write-Host "Next Steps:" -ForegroundColor Cyan
        Write-Host "1. Complete onboarding at the URL above" -ForegroundColor White
        Write-Host "2. Run: .\test-stripe-connect.ps1 -Action sync" -ForegroundColor White
        Write-Host "3. Verify status shows complete" -ForegroundColor White
        Write-Host "========================================" -ForegroundColor Cyan
    }
}

Write-Host ""
Write-Host "Test complete!" -ForegroundColor Cyan
