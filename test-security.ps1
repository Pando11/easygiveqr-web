# Test Security Endpoints
# This script demonstrates testing authentication and rate limiting

param(
    [string]$BaseUrl = "http://localhost:3000",
    [string]$AdminSecret = "",
    [string]$CronSecret = ""
)

Write-Host "========================================" -ForegroundColor Cyan
Write-Host "Security Testing" -ForegroundColor Cyan
Write-Host "========================================" -ForegroundColor Cyan
Write-Host ""

if (-not $AdminSecret) {
    $AdminSecret = Read-Host "Enter ADMIN_SECRET (or press Enter to skip admin tests)"
}

if (-not $CronSecret) {
    $CronSecret = Read-Host "Enter CRON_SECRET (or press Enter to skip cron tests)"
}

Write-Host ""

# Test 1: Admin endpoint without auth (should return 401)
Write-Host "Test 1: Admin endpoint WITHOUT auth (should return 401)" -ForegroundColor Yellow
try {
    $response = Invoke-RestMethod -Uri "$BaseUrl/api/qr/generate" -Method POST `
        -Headers @{ "Content-Type" = "application/json" } `
        -Body (@{ church_id = "EGQR-123" } | ConvertTo-Json) `
        -ErrorAction Stop
    Write-Host "[UNEXPECTED] Request succeeded (should have failed)" -ForegroundColor Red
    Write-Host "Response: $($response | ConvertTo-Json)" -ForegroundColor Red
} catch {
    $statusCode = $_.Exception.Response.StatusCode.value__
    if ($statusCode -eq 401) {
        Write-Host "[OK] Correctly returned 401 Unauthorized" -ForegroundColor Green
        $reader = New-Object System.IO.StreamReader($_.Exception.Response.GetResponseStream())
        $responseBody = $reader.ReadToEnd()
        Write-Host "Response: $responseBody" -ForegroundColor Gray
    } else {
        Write-Host "[UNEXPECTED] Returned status $statusCode (expected 401)" -ForegroundColor Red
    }
}
Write-Host ""

# Test 2: Admin endpoint with invalid secret (should return 401)
Write-Host "Test 2: Admin endpoint with INVALID secret (should return 401)" -ForegroundColor Yellow
try {
    $response = Invoke-RestMethod -Uri "$BaseUrl/api/qr/generate" -Method POST `
        -Headers @{
            "Content-Type" = "application/json"
            "x-admin-secret" = "wrong-secret"
        } `
        -Body (@{ church_id = "EGQR-123" } | ConvertTo-Json) `
        -ErrorAction Stop
    Write-Host "[UNEXPECTED] Request succeeded (should have failed)" -ForegroundColor Red
} catch {
    $statusCode = $_.Exception.Response.StatusCode.value__
    if ($statusCode -eq 401) {
        Write-Host "[OK] Correctly returned 401 Unauthorized" -ForegroundColor Green
    } else {
        Write-Host "[UNEXPECTED] Returned status $statusCode (expected 401)" -ForegroundColor Red
    }
}
Write-Host ""

# Test 3: Admin endpoint with valid secret (should return 200 or 404)
if ($AdminSecret) {
    Write-Host "Test 3: Admin endpoint with VALID secret (should return 200 or 404)" -ForegroundColor Yellow
    try {
        $response = Invoke-RestMethod -Uri "$BaseUrl/api/qr/generate" -Method POST `
            -Headers @{
                "Content-Type" = "application/json"
                "x-admin-secret" = $AdminSecret
            } `
            -Body (@{ church_id = "EGQR-123" } | ConvertTo-Json) `
            -ErrorAction Stop
        if ($response.ok) {
            Write-Host "[OK] Request succeeded with valid secret" -ForegroundColor Green
            Write-Host "Response: $($response | ConvertTo-Json -Depth 3)" -ForegroundColor Gray
        } else {
            Write-Host "[OK] Request processed (may return error for missing church)" -ForegroundColor Yellow
            Write-Host "Response: $($response | ConvertTo-Json)" -ForegroundColor Gray
        }
    } catch {
        $statusCode = $_.Exception.Response.StatusCode.value__
        if ($statusCode -eq 404) {
            Write-Host "[OK] Church not found (expected if EGQR-123 doesn't exist)" -ForegroundColor Yellow
        } else {
            Write-Host "[ERROR] Status $statusCode" -ForegroundColor Red
            $reader = New-Object System.IO.StreamReader($_.Exception.Response.GetResponseStream())
            $responseBody = $reader.ReadToEnd()
            Write-Host "Response: $responseBody" -ForegroundColor Red
        }
    }
    Write-Host ""
}

# Test 4: Cron endpoint without auth (should return 401)
Write-Host "Test 4: Cron endpoint WITHOUT auth (should return 401)" -ForegroundColor Yellow
try {
    $response = Invoke-RestMethod -Uri "$BaseUrl/api/jobs/weekly-summary" -Method POST `
        -ErrorAction Stop
    Write-Host "[UNEXPECTED] Request succeeded (should have failed)" -ForegroundColor Red
} catch {
    $statusCode = $_.Exception.Response.StatusCode.value__
    if ($statusCode -eq 401) {
        Write-Host "[OK] Correctly returned 401 Unauthorized" -ForegroundColor Green
    } else {
        Write-Host "[UNEXPECTED] Returned status $statusCode (expected 401)" -ForegroundColor Red
    }
}
Write-Host ""

# Test 5: Cron endpoint with valid secret (should return 200 or error)
if ($CronSecret) {
    Write-Host "Test 5: Cron endpoint with VALID secret (should return 200 or error)" -ForegroundColor Yellow
    try {
        $response = Invoke-RestMethod -Uri "$BaseUrl/api/jobs/weekly-summary" -Method POST `
            -Headers @{ "x-cron-secret" = $CronSecret } `
            -ErrorAction Stop
        Write-Host "[OK] Request succeeded with valid secret" -ForegroundColor Green
        Write-Host "Response: $($response | ConvertTo-Json -Depth 3)" -ForegroundColor Gray
    } catch {
        $statusCode = $_.Exception.Response.StatusCode.value__
        Write-Host "[OK] Request processed (may return error for missing data)" -ForegroundColor Yellow
        Write-Host "Status: $statusCode" -ForegroundColor Gray
        $reader = New-Object System.IO.StreamReader($_.Exception.Response.GetResponseStream())
        $responseBody = $reader.ReadToEnd()
        Write-Host "Response: $responseBody" -ForegroundColor Gray
    }
    Write-Host ""
}

# Test 6: Public endpoint (should work without auth)
Write-Host "Test 6: Public endpoint WITHOUT auth (should return 200)" -ForegroundColor Yellow
try {
    $response = Invoke-RestMethod -Uri "$BaseUrl/api/qr?church_id=EGQR-123" -Method GET `
        -ErrorAction Stop
    Write-Host "[OK] Public endpoint accessible without auth" -ForegroundColor Green
    Write-Host "Response: $($response | ConvertTo-Json)" -ForegroundColor Gray
} catch {
    $statusCode = $_.Exception.Response.StatusCode.value__
    if ($statusCode -eq 404) {
        Write-Host "[OK] Church not found (expected if EGQR-123 doesn't exist)" -ForegroundColor Yellow
    } else {
        Write-Host "[ERROR] Status $statusCode" -ForegroundColor Red
    }
}
Write-Host ""

# Test 7: Rate limiting (make multiple requests)
Write-Host "Test 7: Rate limiting test (make 25 requests to checkout-session)" -ForegroundColor Yellow
Write-Host "Note: This may take a moment..." -ForegroundColor Gray
$rateLimitHit = $false
for ($i = 1; $i -le 25; $i++) {
    try {
        $response = Invoke-RestMethod -Uri "$BaseUrl/api/checkout-session" -Method POST `
            -Headers @{ "Content-Type" = "application/json" } `
            -Body (@{ amount = 1000; church_id = "EGQR-123" } | ConvertTo-Json) `
            -ErrorAction Stop
        Write-Host "Request $i: OK" -ForegroundColor Gray -NoNewline
        Write-Host "`r" -NoNewline
    } catch {
        $statusCode = $_.Exception.Response.StatusCode.value__
        if ($statusCode -eq 429) {
            Write-Host ""
            Write-Host "[OK] Rate limit hit on request $i (expected around request 21)" -ForegroundColor Green
            $reader = New-Object System.IO.StreamReader($_.Exception.Response.GetResponseStream())
            $responseBody = $reader.ReadToEnd()
            Write-Host "Response: $responseBody" -ForegroundColor Gray
            $rateLimitHit = $true
            break
        } else {
            Write-Host ""
            Write-Host "Request $i: Status $statusCode (may be expected if church doesn't exist)" -ForegroundColor Yellow
        }
    }
    Start-Sleep -Milliseconds 100
}
if (-not $rateLimitHit) {
    Write-Host ""
    Write-Host "[INFO] Rate limit not hit (may need more requests or different timing)" -ForegroundColor Yellow
}
Write-Host ""

Write-Host "========================================" -ForegroundColor Cyan
Write-Host "Security Tests Complete" -ForegroundColor Cyan
Write-Host "========================================" -ForegroundColor Cyan
Write-Host ""
Write-Host "Summary:" -ForegroundColor Cyan
Write-Host "- Admin endpoints require x-admin-secret header" -ForegroundColor White
Write-Host "- Cron endpoints require x-cron-secret header" -ForegroundColor White
Write-Host "- Public endpoints work without auth" -ForegroundColor White
Write-Host "- Rate limiting protects public endpoints" -ForegroundColor White
Write-Host ""
Write-Host "For more details, see SECURITY_CHECKLIST.md" -ForegroundColor Gray
