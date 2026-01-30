# Test Engagement Tools
# This script tests the engagement forms feature

param(
    [string]$ChurchId = "EGQR-123",
    [string]$AdminSecret = ""
)

Write-Host "========================================" -ForegroundColor Cyan
Write-Host "Testing Engagement Tools" -ForegroundColor Cyan
Write-Host "========================================" -ForegroundColor Cyan
Write-Host ""

$baseUrl = "http://localhost:3000"

Write-Host "Church ID: $ChurchId" -ForegroundColor Yellow
Write-Host ""

if ([string]::IsNullOrEmpty($AdminSecret)) {
    Write-Host "WARNING: Admin secret not provided. Admin route tests will be skipped." -ForegroundColor Yellow
    Write-Host "Usage: .\test-engagement.ps1 -ChurchId EGQR-123 -AdminSecret YOUR_SECRET" -ForegroundColor Gray
    Write-Host ""
}

# Test 1: Submit Prayer Request
Write-Host "Test 1: Submitting Prayer Request..." -ForegroundColor Yellow
try {
    $body = @{
        church_id = $ChurchId
        type = "prayer"
        name = "Test User"
        email = "test@example.com"
        message = "Please pray for my family during this difficult time."
    } | ConvertTo-Json
    
    $response = Invoke-RestMethod -Uri "$baseUrl/api/engagement/submit" -Method POST `
        -Headers @{ "Content-Type" = "application/json" } `
        -Body $body
    
    if ($response.ok) {
        Write-Host "[OK] Prayer request submitted" -ForegroundColor Green
        Write-Host "  Submission ID: $($response.id)" -ForegroundColor Cyan
        $prayerId = $response.id
    } else {
        Write-Host "[ERROR] $($response.error)" -ForegroundColor Red
    }
} catch {
    $statusCode = $_.Exception.Response.StatusCode.value__
    Write-Host "[ERROR] Status: $statusCode" -ForegroundColor Red
    $reader = New-Object System.IO.StreamReader($_.Exception.Response.GetResponseStream())
    $responseBody = $reader.ReadToEnd()
    Write-Host "  Response: $responseBody" -ForegroundColor Red
}
Write-Host ""

# Test 2: Submit Visitor Connect
Write-Host "Test 2: Submitting Visitor Connect..." -ForegroundColor Yellow
try {
    $body = @{
        church_id = $ChurchId
        type = "visitor"
        name = "Jane Visitor"
        email = "jane@example.com"
        phone = "+1234567890"
        message = "First time visitor, would love to learn more."
    } | ConvertTo-Json
    
    $response = Invoke-RestMethod -Uri "$baseUrl/api/engagement/submit" -Method POST `
        -Headers @{ "Content-Type" = "application/json" } `
        -Body $body
    
    if ($response.ok) {
        Write-Host "[OK] Visitor connect submitted" -ForegroundColor Green
        Write-Host "  Submission ID: $($response.id)" -ForegroundColor Cyan
        $visitorId = $response.id
    } else {
        Write-Host "[ERROR] $($response.error)" -ForegroundColor Red
    }
} catch {
    $statusCode = $_.Exception.Response.StatusCode.value__
    Write-Host "[ERROR] Status: $statusCode" -ForegroundColor Red
}
Write-Host ""

# Test 3: Submit Volunteer Interest
Write-Host "Test 3: Submitting Volunteer Interest..." -ForegroundColor Yellow
try {
    $body = @{
        church_id = $ChurchId
        type = "volunteer"
        name = "Bob Volunteer"
        email = "bob@example.com"
        message = "Interested in music ministry and children's programs."
    } | ConvertTo-Json
    
    $response = Invoke-RestMethod -Uri "$baseUrl/api/engagement/submit" -Method POST `
        -Headers @{ "Content-Type" = "application/json" } `
        -Body $body
    
    if ($response.ok) {
        Write-Host "[OK] Volunteer interest submitted" -ForegroundColor Green
        Write-Host "  Submission ID: $($response.id)" -ForegroundColor Cyan
        $volunteerId = $response.id
    } else {
        Write-Host "[ERROR] $($response.error)" -ForegroundColor Red
    }
} catch {
    $statusCode = $_.Exception.Response.StatusCode.value__
    Write-Host "[ERROR] Status: $statusCode" -ForegroundColor Red
}
Write-Host ""

# Test 4: Validation - Prayer without message
Write-Host "Test 4: Testing Validation (Prayer without message)..." -ForegroundColor Yellow
try {
    $body = @{
        church_id = $ChurchId
        type = "prayer"
        name = "Test User"
    } | ConvertTo-Json
    
    $response = Invoke-RestMethod -Uri "$baseUrl/api/engagement/submit" -Method POST `
        -Headers @{ "Content-Type" = "application/json" } `
        -Body $body `
        -ErrorAction Stop
    
    Write-Host "[UNEXPECTED] Request succeeded (should have failed)" -ForegroundColor Red
} catch {
    $statusCode = $_.Exception.Response.StatusCode.value__
    if ($statusCode -eq 400) {
        Write-Host "[OK] Correctly rejected missing message (400)" -ForegroundColor Green
        $reader = New-Object System.IO.StreamReader($_.Exception.Response.GetResponseStream())
        $responseBody = $reader.ReadToEnd()
        Write-Host "  Response: $responseBody" -ForegroundColor Gray
    } else {
        Write-Host "[UNEXPECTED] Status: $statusCode (expected 400)" -ForegroundColor Red
    }
}
Write-Host ""

# Test 5: Validation - Visitor without name
Write-Host "Test 5: Testing Validation (Visitor without name)..." -ForegroundColor Yellow
try {
    $body = @{
        church_id = $ChurchId
        type = "visitor"
        email = "test@example.com"
    } | ConvertTo-Json
    
    $response = Invoke-RestMethod -Uri "$baseUrl/api/engagement/submit" -Method POST `
        -Headers @{ "Content-Type" = "application/json" } `
        -Body $body `
        -ErrorAction Stop
    
    Write-Host "[UNEXPECTED] Request succeeded (should have failed)" -ForegroundColor Red
} catch {
    $statusCode = $_.Exception.Response.StatusCode.value__
    if ($statusCode -eq 400) {
        Write-Host "[OK] Correctly rejected missing name (400)" -ForegroundColor Green
    } else {
        Write-Host "[INFO] Status: $statusCode" -ForegroundColor Yellow
    }
}
Write-Host ""

# Test 6: Admin List (if admin secret provided)
if (-not [string]::IsNullOrEmpty($AdminSecret)) {
    Write-Host "Test 6: Admin List Submissions..." -ForegroundColor Yellow
    try {
        $response = Invoke-RestMethod -Uri "$baseUrl/api/admin/engagement?church_id=$([uri]::EscapeDataString($ChurchId))&status=open" -Method GET `
            -Headers @{ "x-admin-secret" = $AdminSecret }
        
        if ($response.ok) {
            Write-Host "[OK] Retrieved submissions" -ForegroundColor Green
            Write-Host "  Count: $($response.count)" -ForegroundColor Cyan
            if ($response.submissions.Count -gt 0) {
                Write-Host "  Latest: $($response.submissions[0].type) - $($response.submissions[0].name)" -ForegroundColor Cyan
                $latestId = $response.submissions[0].id
            }
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
    
    # Test 7: Admin Mark Complete (if we have an ID)
    if ($latestId) {
        Write-Host "Test 7: Admin Mark Complete..." -ForegroundColor Yellow
        try {
            $body = @{
                id = $latestId
            } | ConvertTo-Json
            
            $response = Invoke-RestMethod -Uri "$baseUrl/api/admin/engagement/complete" -Method PATCH `
                -Headers @{
                    "Content-Type" = "application/json"
                    "x-admin-secret" = $AdminSecret
                } `
                -Body $body
            
            if ($response.ok) {
                Write-Host "[OK] Submission marked as completed" -ForegroundColor Green
                Write-Host "  Status: $($response.submission.status)" -ForegroundColor Cyan
                Write-Host "  Completed At: $($response.submission.completed_at)" -ForegroundColor Cyan
            } else {
                Write-Host "[ERROR] $($response.error)" -ForegroundColor Red
            }
        } catch {
            $statusCode = $_.Exception.Response.StatusCode.value__
            Write-Host "[ERROR] Status: $statusCode" -ForegroundColor Red
        }
        Write-Host ""
    }
} else {
    Write-Host "Test 6-7: Skipped (admin secret not provided)" -ForegroundColor Yellow
    Write-Host ""
}

Write-Host "========================================" -ForegroundColor Cyan
Write-Host "Test Summary" -ForegroundColor Cyan
Write-Host "========================================" -ForegroundColor Cyan
Write-Host ""
Write-Host "Next Steps:" -ForegroundColor Yellow
Write-Host "1. Visit form pages in browser:" -ForegroundColor White
Write-Host "   http://localhost:3000/engage/prayer?church_id=$ChurchId" -ForegroundColor Cyan
Write-Host "   http://localhost:3000/engage/visitor?church_id=$ChurchId" -ForegroundColor Cyan
Write-Host "   http://localhost:3000/engage/volunteer?church_id=$ChurchId" -ForegroundColor Cyan
Write-Host ""
Write-Host "2. Verify in Supabase:" -ForegroundColor White
Write-Host "   SELECT * FROM public.engagement_submissions WHERE church_id = '$ChurchId' ORDER BY created_at DESC;" -ForegroundColor Gray
Write-Host ""
Write-Host "3. Test scenarios:" -ForegroundColor White
Write-Host "   - Submit prayer request (message required)" -ForegroundColor Gray
Write-Host "   - Submit visitor connect (name required)" -ForegroundColor Gray
Write-Host "   - Submit volunteer interest (name required)" -ForegroundColor Gray
Write-Host "   - Verify email notifications sent (if SendGrid configured)" -ForegroundColor Gray
Write-Host "   - List submissions via admin API" -ForegroundColor Gray
Write-Host "   - Mark submission as completed" -ForegroundColor Gray
Write-Host ""
