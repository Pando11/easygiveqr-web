# Test Donation Gating
# This script tests donation eligibility gating

param(
    [string]$ChurchId = "EGQR-123"
)

Write-Host "========================================" -ForegroundColor Cyan
Write-Host "Testing Donation Gating" -ForegroundColor Cyan
Write-Host "========================================" -ForegroundColor Cyan
Write-Host ""

$baseUrl = "http://localhost:3000"

Write-Host "Church ID: $ChurchId" -ForegroundColor Yellow
Write-Host ""

# Test 1: Check Church API
Write-Host "Test 1: Fetching Church Data..." -ForegroundColor Yellow
try {
    $response = Invoke-RestMethod -Uri "$baseUrl/api/church?church_id=$([uri]::EscapeDataString($ChurchId))" -Method GET
    
    if ($response.ok) {
        Write-Host "[OK] Church data retrieved" -ForegroundColor Green
        Write-Host "  Status: $($response.church.status)" -ForegroundColor Cyan
        Write-Host "  Subscription Status: $($response.church.subscription_status)" -ForegroundColor Cyan
        Write-Host "  Charges Enabled: $($response.church.stripe_charges_enabled)" -ForegroundColor Cyan
        Write-Host "  Payouts Enabled: $($response.church.stripe_payouts_enabled)" -ForegroundColor Cyan
        
        # Check eligibility
        $isEligible = ($response.church.status -eq "active") `
            -and ($response.church.subscription_status -in @("active", "trialing")) `
            -and ($response.church.stripe_charges_enabled -eq $true) `
            -and ($response.church.stripe_payouts_enabled -eq $true)
        
        if ($isEligible) {
            Write-Host "  Eligibility: ELIGIBLE" -ForegroundColor Green
        } else {
            Write-Host "  Eligibility: NOT ELIGIBLE" -ForegroundColor Red
            Write-Host "  Reasons:" -ForegroundColor Yellow
            if ($response.church.status -ne "active") {
                Write-Host "    - Status is not 'active' (current: $($response.church.status))" -ForegroundColor Gray
            }
            if ($response.church.subscription_status -notin @("active", "trialing")) {
                Write-Host "    - Subscription status is not active/trialing (current: $($response.church.subscription_status))" -ForegroundColor Gray
            }
            if (-not $response.church.stripe_charges_enabled) {
                Write-Host "    - Stripe charges not enabled" -ForegroundColor Gray
            }
            if (-not $response.church.stripe_payouts_enabled) {
                Write-Host "    - Stripe payouts not enabled" -ForegroundColor Gray
            }
        }
    } else {
        Write-Host "[ERROR] $($response.error)" -ForegroundColor Red
    }
} catch {
    Write-Host "[ERROR] Failed to fetch church: $_" -ForegroundColor Red
}
Write-Host ""

# Test 2: Test Checkout Session (should return 403 if not eligible)
Write-Host "Test 2: Testing Checkout Session API..." -ForegroundColor Yellow
try {
    $body = @{
        amount = 1000
        church_id = $ChurchId
    } | ConvertTo-Json
    
    $response = Invoke-RestMethod -Uri "$baseUrl/api/checkout-session" -Method POST `
        -Headers @{ "Content-Type" = "application/json" } `
        -Body $body `
        -ErrorAction Stop
    
    Write-Host "[OK] Checkout session created (church is eligible)" -ForegroundColor Green
    Write-Host "  URL: $($response.url)" -ForegroundColor Cyan
} catch {
    $statusCode = $_.Exception.Response.StatusCode.value__
    if ($statusCode -eq 403) {
        Write-Host "[OK] Correctly returned 403 Forbidden (church not eligible)" -ForegroundColor Green
        $reader = New-Object System.IO.StreamReader($_.Exception.Response.GetResponseStream())
        $responseBody = $reader.ReadToEnd()
        Write-Host "  Response: $responseBody" -ForegroundColor Gray
    } elseif ($statusCode -eq 404) {
        Write-Host "[INFO] Church not found (404)" -ForegroundColor Yellow
    } else {
        Write-Host "[ERROR] Unexpected status: $statusCode" -ForegroundColor Red
        $reader = New-Object System.IO.StreamReader($_.Exception.Response.GetResponseStream())
        $responseBody = $reader.ReadToEnd()
        Write-Host "  Response: $responseBody" -ForegroundColor Red
    }
}
Write-Host ""

Write-Host "========================================" -ForegroundColor Cyan
Write-Host "Test Scenarios" -ForegroundColor Cyan
Write-Host "========================================" -ForegroundColor Cyan
Write-Host ""
Write-Host "To test different scenarios, update the church in Supabase:" -ForegroundColor Yellow
Write-Host ""
Write-Host "1. Test Pending Church:" -ForegroundColor White
Write-Host "   UPDATE public.churches SET status = 'pending' WHERE church_id = '$ChurchId';" -ForegroundColor Gray
Write-Host "   Expected: Donate page shows 'Donations Temporarily Unavailable'" -ForegroundColor Gray
Write-Host ""
Write-Host "2. Test Canceled Subscription:" -ForegroundColor White
Write-Host "   UPDATE public.churches SET subscription_status = 'canceled' WHERE church_id = '$ChurchId';" -ForegroundColor Gray
Write-Host "   Expected: Donate page shows 'Donations Temporarily Unavailable'" -ForegroundColor Gray
Write-Host ""
Write-Host "3. Test Active + Paid:" -ForegroundColor White
Write-Host "   UPDATE public.churches SET" -ForegroundColor Gray
Write-Host "     status = 'active'," -ForegroundColor Gray
Write-Host "     subscription_status = 'active'," -ForegroundColor Gray
Write-Host "     stripe_charges_enabled = true," -ForegroundColor Gray
Write-Host "     stripe_payouts_enabled = true" -ForegroundColor Gray
Write-Host "   WHERE church_id = '$ChurchId';" -ForegroundColor Gray
Write-Host "   Expected: Donate page shows donation form" -ForegroundColor Gray
Write-Host ""
Write-Host "4. Test in Browser:" -ForegroundColor White
Write-Host "   Visit: http://localhost:3000/donate?church_id=$ChurchId" -ForegroundColor Cyan
Write-Host ""
