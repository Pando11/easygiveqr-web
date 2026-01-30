# Test Monthly Enabled Flag
# This script tests the monthly_enabled feature

param(
    [string]$ChurchId = "EGQR-123",
    [string]$AdminSecret = ""
)

Write-Host "========================================" -ForegroundColor Cyan
Write-Host "Testing Monthly Enabled Flag" -ForegroundColor Cyan
Write-Host "========================================" -ForegroundColor Cyan
Write-Host ""

$baseUrl = "http://localhost:3000"

Write-Host "Church ID: $ChurchId" -ForegroundColor Yellow
Write-Host ""

if ([string]::IsNullOrEmpty($AdminSecret)) {
    Write-Host "WARNING: Admin secret not provided. Admin route tests will be skipped." -ForegroundColor Yellow
    Write-Host "Usage: .\test-monthly-enabled.ps1 -ChurchId EGQR-123 -AdminSecret YOUR_SECRET" -ForegroundColor Gray
    Write-Host ""
}

# Test 1: Fetch Church Data (Check monthly_enabled)
Write-Host "Test 1: Fetching Church Data..." -ForegroundColor Yellow
try {
    $response = Invoke-RestMethod -Uri "$baseUrl/api/church?church_id=$([uri]::EscapeDataString($ChurchId))" -Method GET
    
    if ($response.ok) {
        Write-Host "[OK] Church data retrieved" -ForegroundColor Green
        Write-Host "  Display Name: $($response.church.display_name)" -ForegroundColor Cyan
        Write-Host "  Monthly Enabled: $($response.church.monthly_enabled)" -ForegroundColor Cyan
        
        $monthlyEnabled = $response.church.monthly_enabled
    } else {
        Write-Host "[ERROR] $($response.error)" -ForegroundColor Red
        exit 1
    }
} catch {
    Write-Host "[ERROR] Failed to fetch church: $_" -ForegroundColor Red
    exit 1
}
Write-Host ""

# Test 2: Test One-time Donation (Should Always Work)
Write-Host "Test 2: Testing One-time Donation..." -ForegroundColor Yellow
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
        Write-Host "[OK] One-time checkout session created" -ForegroundColor Green
        Write-Host "  URL: $($response.url)" -ForegroundColor Cyan
    } else {
        Write-Host "[ERROR] $($response.error)" -ForegroundColor Red
    }
} catch {
    $statusCode = $_.Exception.Response.StatusCode.value__
    if ($statusCode -eq 403) {
        Write-Host "[INFO] Church not eligible (403)" -ForegroundColor Yellow
    } else {
        Write-Host "[ERROR] Status: $statusCode" -ForegroundColor Red
    }
}
Write-Host ""

# Test 3: Test Monthly Donation (Based on Flag)
Write-Host "Test 3: Testing Monthly Donation..." -ForegroundColor Yellow
try {
    $body = @{
        church_id = $ChurchId
        amount_cents = 2500
        frequency = "monthly"
    } | ConvertTo-Json
    
    $response = Invoke-RestMethod -Uri "$baseUrl/api/checkout-session" -Method POST `
        -Headers @{ "Content-Type" = "application/json" } `
        -Body $body `
        -ErrorAction Stop
    
    if ($response.ok) {
        if ($monthlyEnabled) {
            Write-Host "[OK] Monthly checkout session created (expected)" -ForegroundColor Green
            Write-Host "  URL: $($response.url)" -ForegroundColor Cyan
        } else {
            Write-Host "[UNEXPECTED] Monthly checkout created but monthly_enabled=false" -ForegroundColor Red
        }
    } else {
        Write-Host "[ERROR] $($response.error)" -ForegroundColor Red
    }
} catch {
    $statusCode = $_.Exception.Response.StatusCode.value__
    if ($statusCode -eq 403) {
        $reader = New-Object System.IO.StreamReader($_.Exception.Response.GetResponseStream())
        $responseBody = $reader.ReadToEnd()
        $errorObj = $responseBody | ConvertFrom-Json
        
        if ($errorObj.error -eq "monthly_not_enabled") {
            if ($monthlyEnabled) {
                Write-Host "[UNEXPECTED] Monthly rejected but monthly_enabled=true" -ForegroundColor Red
            } else {
                Write-Host "[OK] Monthly correctly rejected (monthly_not_enabled)" -ForegroundColor Green
            }
        } elseif ($errorObj.error -eq "church_not_active") {
            Write-Host "[INFO] Church not eligible (403)" -ForegroundColor Yellow
        } else {
            Write-Host "[INFO] Rejected with: $($errorObj.error)" -ForegroundColor Yellow
        }
    } else {
        Write-Host "[INFO] Status: $statusCode" -ForegroundColor Yellow
    }
}
Write-Host ""

# Test 4: Admin Route - Enable Monthly (if admin secret provided)
if (-not [string]::IsNullOrEmpty($AdminSecret)) {
    Write-Host "Test 4: Admin Route - Enable Monthly..." -ForegroundColor Yellow
    try {
        $body = @{
            church_id = $ChurchId
            monthly_enabled = $true
        } | ConvertTo-Json
        
        $response = Invoke-RestMethod -Uri "$baseUrl/api/admin/churches/monthly" -Method PATCH `
            -Headers @{
                "Content-Type" = "application/json"
                "x-admin-secret" = $AdminSecret
            } `
            -Body $body
        
        if ($response.ok) {
            Write-Host "[OK] Monthly enabled successfully" -ForegroundColor Green
            Write-Host "  Church ID: $($response.church_id)" -ForegroundColor Cyan
            Write-Host "  Monthly Enabled: $($response.monthly_enabled)" -ForegroundColor Cyan
        } else {
            Write-Host "[ERROR] $($response.error)" -ForegroundColor Red
        }
    } catch {
        $statusCode = $_.Exception.Response.StatusCode.value__
        if ($statusCode -eq 401) {
            Write-Host "[ERROR] Unauthorized - check admin secret" -ForegroundColor Red
        } else {
            Write-Host "[ERROR] Status: $statusCode" -ForegroundColor Red
        }
    }
    Write-Host ""
    
    # Test 5: Admin Route - Disable Monthly
    Write-Host "Test 5: Admin Route - Disable Monthly..." -ForegroundColor Yellow
    try {
        $body = @{
            church_id = $ChurchId
            monthly_enabled = $false
        } | ConvertTo-Json
        
        $response = Invoke-RestMethod -Uri "$baseUrl/api/admin/churches/monthly" -Method PATCH `
            -Headers @{
                "Content-Type" = "application/json"
                "x-admin-secret" = $AdminSecret
            } `
            -Body $body
        
        if ($response.ok) {
            Write-Host "[OK] Monthly disabled successfully" -ForegroundColor Green
            Write-Host "  Church ID: $($response.church_id)" -ForegroundColor Cyan
            Write-Host "  Monthly Enabled: $($response.monthly_enabled)" -ForegroundColor Cyan
        } else {
            Write-Host "[ERROR] $($response.error)" -ForegroundColor Red
        }
    } catch {
        $statusCode = $_.Exception.Response.StatusCode.value__
        Write-Host "[ERROR] Status: $statusCode" -ForegroundColor Red
    }
    Write-Host ""
} else {
    Write-Host "Test 4-5: Skipped (admin secret not provided)" -ForegroundColor Yellow
    Write-Host ""
}

Write-Host "========================================" -ForegroundColor Cyan
Write-Host "Test Summary" -ForegroundColor Cyan
Write-Host "========================================" -ForegroundColor Cyan
Write-Host ""
Write-Host "Next Steps:" -ForegroundColor Yellow
Write-Host "1. Visit donate page in browser:" -ForegroundColor White
Write-Host "   http://localhost:3000/donate?church_id=$ChurchId" -ForegroundColor Cyan
Write-Host ""
Write-Host "2. Verify UI behavior:" -ForegroundColor White
if ($monthlyEnabled) {
    Write-Host "   - Frequency toggle should be VISIBLE" -ForegroundColor Green
    Write-Host "   - Both 'One-time' and 'Monthly' options available" -ForegroundColor Green
} else {
    Write-Host "   - Frequency toggle should be HIDDEN" -ForegroundColor Yellow
    Write-Host "   - Only one-time donation available" -ForegroundColor Yellow
}
Write-Host ""
Write-Host "3. Test scenarios:" -ForegroundColor White
Write-Host "   - monthly_enabled=false: No toggle, API rejects monthly" -ForegroundColor Gray
Write-Host "   - monthly_enabled=true: Toggle visible, API accepts monthly" -ForegroundColor Gray
Write-Host "   - Use admin route to toggle the flag" -ForegroundColor Gray
Write-Host ""
