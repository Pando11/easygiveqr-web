# Test Donation UX Upgrade
# This script tests the new donation page features

param(
    [string]$ChurchId = "EGQR-123",
    [string]$Language = "EN"
)

Write-Host "========================================" -ForegroundColor Cyan
Write-Host "Testing Donation UX Upgrade" -ForegroundColor Cyan
Write-Host "========================================" -ForegroundColor Cyan
Write-Host ""

$baseUrl = "http://localhost:3000"

Write-Host "Church ID: $ChurchId" -ForegroundColor Yellow
Write-Host "Language: $Language" -ForegroundColor Yellow
Write-Host ""

# Test 1: Fetch Church Data
Write-Host "Test 1: Fetching Church Data..." -ForegroundColor Yellow
try {
    $response = Invoke-RestMethod -Uri "$baseUrl/api/church?church_id=$([uri]::EscapeDataString($ChurchId))" -Method GET
    
    if ($response.ok) {
        Write-Host "[OK] Church data retrieved" -ForegroundColor Green
        Write-Host "  Display Name: $($response.church.display_name)" -ForegroundColor Cyan
        Write-Host "  Preferred Language: $($response.church.preferred_language)" -ForegroundColor Cyan
        Write-Host "  Status: $($response.church.status)" -ForegroundColor Cyan
        Write-Host "  Subscription Status: $($response.church.subscription_status)" -ForegroundColor Cyan
        
        # Check eligibility
        $isEligible = ($response.church.status -eq "active") `
            -and ($response.church.subscription_status -in @("active", "trialing")) `
            -and ($response.church.stripe_charges_enabled -eq $true) `
            -and ($response.church.stripe_payouts_enabled -eq $true)
        
        if ($isEligible) {
            Write-Host "  Eligibility: ELIGIBLE" -ForegroundColor Green
        } else {
            Write-Host "  Eligibility: NOT ELIGIBLE" -ForegroundColor Red
        }
    } else {
        Write-Host "[ERROR] $($response.error)" -ForegroundColor Red
        exit 1
    }
} catch {
    Write-Host "[ERROR] Failed to fetch church: $_" -ForegroundColor Red
    exit 1
}
Write-Host ""

# Test 2: Test One-time Donation with Valid Amount
Write-Host "Test 2: Testing One-time Donation ($10)..." -ForegroundColor Yellow
try {
    $body = @{
        church_id = $ChurchId
        amount_cents = 1000
        frequency = "one_time"
    } | ConvertTo-Json
    
    $response = Invoke-RestMethod -Uri "$baseUrl/api/checkout-session" -Method POST `
        -Headers @{ "Content-Type" = "application/json" } `
        -Body $body
    
    if ($response.ok) {
        Write-Host "[OK] Checkout session created" -ForegroundColor Green
        Write-Host "  URL: $($response.url)" -ForegroundColor Cyan
    } else {
        Write-Host "[ERROR] $($response.error)" -ForegroundColor Red
    }
} catch {
    $statusCode = $_.Exception.Response.StatusCode.value__
    if ($statusCode -eq 403) {
        Write-Host "[INFO] Church not eligible (403)" -ForegroundColor Yellow
    } elseif ($statusCode -eq 400) {
        Write-Host "[ERROR] Invalid request (400)" -ForegroundColor Red
        $reader = New-Object System.IO.StreamReader($_.Exception.Response.GetResponseStream())
        $responseBody = $reader.ReadToEnd()
        Write-Host "  Response: $responseBody" -ForegroundColor Red
    } else {
        Write-Host "[ERROR] Status: $statusCode" -ForegroundColor Red
    }
}
Write-Host ""

# Test 3: Test Monthly Donation
Write-Host "Test 3: Testing Monthly Donation ($25)..." -ForegroundColor Yellow
try {
    $body = @{
        church_id = $ChurchId
        amount_cents = 2500
        frequency = "monthly"
    } | ConvertTo-Json
    
    $response = Invoke-RestMethod -Uri "$baseUrl/api/checkout-session" -Method POST `
        -Headers @{ "Content-Type" = "application/json" } `
        -Body $body
    
    if ($response.ok) {
        Write-Host "[OK] Subscription checkout session created" -ForegroundColor Green
        Write-Host "  URL: $($response.url)" -ForegroundColor Cyan
    } else {
        Write-Host "[ERROR] $($response.error)" -ForegroundColor Red
    }
} catch {
    $statusCode = $_.Exception.Response.StatusCode.value__
    Write-Host "[INFO] Status: $statusCode" -ForegroundColor Yellow
    if ($statusCode -eq 400) {
        $reader = New-Object System.IO.StreamReader($_.Exception.Response.GetResponseStream())
        $responseBody = $reader.ReadToEnd()
        Write-Host "  Response: $responseBody" -ForegroundColor Gray
    }
}
Write-Host ""

# Test 4: Test Invalid Amount
Write-Host "Test 4: Testing Invalid Amount (750 cents)..." -ForegroundColor Yellow
try {
    $body = @{
        church_id = $ChurchId
        amount_cents = 750
        frequency = "one_time"
    } | ConvertTo-Json
    
    $response = Invoke-RestMethod -Uri "$baseUrl/api/checkout-session" -Method POST `
        -Headers @{ "Content-Type" = "application/json" } `
        -Body $body `
        -ErrorAction Stop
    
    Write-Host "[UNEXPECTED] Request succeeded (should have failed)" -ForegroundColor Red
} catch {
    $statusCode = $_.Exception.Response.StatusCode.value__
    if ($statusCode -eq 400) {
        Write-Host "[OK] Correctly rejected invalid amount (400)" -ForegroundColor Green
        $reader = New-Object System.IO.StreamReader($_.Exception.Response.GetResponseStream())
        $responseBody = $reader.ReadToEnd()
        Write-Host "  Response: $responseBody" -ForegroundColor Gray
    } else {
        Write-Host "[UNEXPECTED] Status: $statusCode (expected 400)" -ForegroundColor Red
    }
}
Write-Host ""

# Test 5: Test Invalid Frequency
Write-Host "Test 5: Testing Invalid Frequency..." -ForegroundColor Yellow
try {
    $body = @{
        church_id = $ChurchId
        amount_cents = 1000
        frequency = "invalid"
    } | ConvertTo-Json
    
    $response = Invoke-RestMethod -Uri "$baseUrl/api/checkout-session" -Method POST `
        -Headers @{ "Content-Type" = "application/json" } `
        -Body $body `
        -ErrorAction Stop
    
    Write-Host "[UNEXPECTED] Request succeeded (should have failed)" -ForegroundColor Red
} catch {
    $statusCode = $_.Exception.Response.StatusCode.value__
    if ($statusCode -eq 400) {
        Write-Host "[OK] Correctly rejected invalid frequency (400)" -ForegroundColor Green
    } else {
        Write-Host "[INFO] Status: $statusCode" -ForegroundColor Yellow
    }
}
Write-Host ""

Write-Host "========================================" -ForegroundColor Cyan
Write-Host "Test Summary" -ForegroundColor Cyan
Write-Host "========================================" -ForegroundColor Cyan
Write-Host ""
Write-Host "Next Steps:" -ForegroundColor Yellow
Write-Host "1. Visit donate page in browser:" -ForegroundColor White
Write-Host "   http://localhost:3000/donate?church_id=$ChurchId" -ForegroundColor Cyan
Write-Host ""
Write-Host "2. Test UI features:" -ForegroundColor White
Write-Host "   - Select different preset amounts" -ForegroundColor Gray
Write-Host "   - Toggle between one-time and monthly" -ForegroundColor Gray
Write-Host "   - Verify language matches church preference" -ForegroundColor Gray
Write-Host "   - Complete a donation" -ForegroundColor Gray
Write-Host ""
Write-Host "3. Test scenarios:" -ForegroundColor White
Write-Host "   - EN church: one-time $5" -ForegroundColor Gray
Write-Host "   - ES church: one-time $10" -ForegroundColor Gray
Write-Host "   - Monthly donation $25" -ForegroundColor Gray
Write-Host "   - Inactive church (should show unavailable message)" -ForegroundColor Gray
Write-Host ""
