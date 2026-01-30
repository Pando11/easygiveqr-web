# Test Church Subscription Billing
# This script tests the billing flow end-to-end

param(
    [string]$ChurchId = "EGQR-123",
    [string]$AdminSecret = ""
)

Write-Host "========================================" -ForegroundColor Cyan
Write-Host "Testing Church Subscription Billing" -ForegroundColor Cyan
Write-Host "========================================" -ForegroundColor Cyan
Write-Host ""

if (-not $AdminSecret) {
    $AdminSecret = Read-Host "Enter ADMIN_SECRET"
}

if (-not $AdminSecret) {
    Write-Host "[ERROR] ADMIN_SECRET is required" -ForegroundColor Red
    exit 1
}

$baseUrl = "http://localhost:3000"
$headers = @{
    "Content-Type" = "application/json"
    "x-admin-secret" = $AdminSecret
}

Write-Host "Church ID: $ChurchId" -ForegroundColor Yellow
Write-Host ""

# Step 1: Create Customer
Write-Host "Step 1: Creating Stripe Customer..." -ForegroundColor Yellow
try {
    $body = @{ church_id = $ChurchId } | ConvertTo-Json
    $response = Invoke-RestMethod -Uri "$baseUrl/api/billing/create-customer" -Method POST -Headers $headers -Body $body
    
    if ($response.ok) {
        Write-Host "[OK] Customer created: $($response.stripe_customer_id)" -ForegroundColor Green
        $customerId = $response.stripe_customer_id
    } else {
        Write-Host "[ERROR] $($response.error)" -ForegroundColor Red
        exit 1
    }
} catch {
    Write-Host "[ERROR] Failed to create customer: $_" -ForegroundColor Red
    if ($_.Exception.Response) {
        $reader = New-Object System.IO.StreamReader($_.Exception.Response.GetResponseStream())
        $responseBody = $reader.ReadToEnd()
        Write-Host "Response: $responseBody" -ForegroundColor Red
    }
    exit 1
}
Write-Host ""

# Step 2: Create Subscription Checkout
Write-Host "Step 2: Creating Subscription Checkout Session..." -ForegroundColor Yellow
try {
    $body = @{ church_id = $ChurchId } | ConvertTo-Json
    $response = Invoke-RestMethod -Uri "$baseUrl/api/billing/create-subscription-checkout" -Method POST -Headers $headers -Body $body
    
    if ($response.ok) {
        Write-Host "[OK] Checkout session created" -ForegroundColor Green
        Write-Host "Checkout URL: $($response.url)" -ForegroundColor Cyan
        Write-Host ""
        Write-Host "Next steps:" -ForegroundColor Yellow
        Write-Host "1. Open the checkout URL in your browser" -ForegroundColor White
        Write-Host "2. Use test card: 4242 4242 4242 4242" -ForegroundColor White
        Write-Host "3. Complete the checkout" -ForegroundColor White
        Write-Host "4. Wait for webhook to process (check Stripe Dashboard)" -ForegroundColor White
        Write-Host ""
        
        $checkoutUrl = $response.url
        $sessionId = $response.session_id
    } else {
        Write-Host "[ERROR] $($response.error)" -ForegroundColor Red
        exit 1
    }
} catch {
    Write-Host "[ERROR] Failed to create checkout: $_" -ForegroundColor Red
    if ($_.Exception.Response) {
        $reader = New-Object System.IO.StreamReader($_.Exception.Response.GetResponseStream())
        $responseBody = $reader.ReadToEnd()
        Write-Host "Response: $responseBody" -ForegroundColor Red
    }
    exit 1
}
Write-Host ""

# Step 3: Get Church Billing Info
Write-Host "Step 3: Fetching Church Billing Info..." -ForegroundColor Yellow
try {
    $response = Invoke-RestMethod -Uri "$baseUrl/api/billing/church?church_id=$([uri]::EscapeDataString($ChurchId))" -Method GET -Headers $headers
    
    if ($response.ok) {
        Write-Host "[OK] Church billing info retrieved" -ForegroundColor Green
        Write-Host "  Customer ID: $($response.stripe_customer_id)" -ForegroundColor Cyan
        Write-Host "  Subscription ID: $($response.stripe_subscription_id)" -ForegroundColor Cyan
        Write-Host "  Status: $($response.subscription_status)" -ForegroundColor Cyan
        if ($response.subscription_started_at) {
            Write-Host "  Started: $($response.subscription_started_at)" -ForegroundColor Cyan
        }
        if ($response.subscription_canceled_at) {
            Write-Host "  Canceled: $($response.subscription_canceled_at)" -ForegroundColor Cyan
        }
    } else {
        Write-Host "[ERROR] $($response.error)" -ForegroundColor Red
    }
} catch {
    Write-Host "[ERROR] Failed to fetch billing info: $_" -ForegroundColor Red
}
Write-Host ""

Write-Host "========================================" -ForegroundColor Cyan
Write-Host "Test Complete" -ForegroundColor Cyan
Write-Host "========================================" -ForegroundColor Cyan
Write-Host ""
Write-Host "Next Steps:" -ForegroundColor Yellow
Write-Host "1. Complete checkout at: $checkoutUrl" -ForegroundColor White
Write-Host "2. Check webhook events in Stripe Dashboard" -ForegroundColor White
Write-Host "3. Verify subscription in database:" -ForegroundColor White
Write-Host "   SELECT * FROM public.churches WHERE church_id = '$ChurchId';" -ForegroundColor Gray
Write-Host "4. Test subscription update/cancel in Stripe Dashboard" -ForegroundColor White
Write-Host ""
