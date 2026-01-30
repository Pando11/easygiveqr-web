# Test Annual Receipts Batch Job
# This script tests the annual receipts endpoint locally

param(
    [int]$Year = 2025,
    [string]$ChurchId = ""
)

Write-Host "========================================" -ForegroundColor Cyan
Write-Host "Testing Annual Receipts Batch Job" -ForegroundColor Cyan
Write-Host "========================================" -ForegroundColor Cyan
Write-Host ""

# Get CRON_SECRET from environment or prompt
$cronSecret = $env:CRON_SECRET
if (-not $cronSecret) {
    $cronSecret = Read-Host "Enter CRON_SECRET (or set CRON_SECRET env var)"
}

if (-not $cronSecret) {
    Write-Host "ERROR: CRON_SECRET is required" -ForegroundColor Red
    exit 1
}

# Build request body
$body = @{
    year = $Year
}

if ($ChurchId) {
    $body.church_id = $ChurchId
    Write-Host "Testing for church: $ChurchId" -ForegroundColor Yellow
} else {
    Write-Host "Testing for all churches" -ForegroundColor Yellow
}

Write-Host "Year: $Year" -ForegroundColor Yellow
Write-Host ""

# API endpoint
$url = "http://localhost:3000/api/jobs/annual-receipts"

Write-Host "Calling: $url" -ForegroundColor Yellow
Write-Host ""

try {
    $headers = @{
        "x-cron-secret" = $cronSecret
        "Content-Type" = "application/json"
    }

    $jsonBody = $body | ConvertTo-Json
    $response = Invoke-RestMethod -Uri $url -Method POST -Headers $headers -Body $jsonBody

    Write-Host "Response:" -ForegroundColor Green
    Write-Host ($response | ConvertTo-Json -Depth 10) -ForegroundColor White
    Write-Host ""

    if ($response.ok) {
        Write-Host "SUCCESS!" -ForegroundColor Green
        Write-Host "Year: $($response.summary.year)" -ForegroundColor Cyan
        Write-Host "Churches processed: $($response.summary.churchesProcessed)" -ForegroundColor Cyan
        Write-Host "Receipts sent: $($response.summary.receiptsSent)" -ForegroundColor Cyan
        Write-Host "Receipts skipped (already sent): $($response.summary.receiptsSkipped)" -ForegroundColor Cyan
        Write-Host "Failures: $($response.summary.failures)" -ForegroundColor Cyan
        
        if ($response.summary.failures -gt 0 -and $response.summary.failuresList) {
            Write-Host ""
            Write-Host "Failures:" -ForegroundColor Yellow
            $response.summary.failuresList | ForEach-Object {
                Write-Host "  - Church: $($_.church_id), Donor: $($_.donor_email)" -ForegroundColor Red
                Write-Host "    Error: $($_.error)" -ForegroundColor Red
            }
        }
        
        Write-Host ""
        Write-Host "Check your email inbox for receipt emails!" -ForegroundColor Green
    } else {
        Write-Host "ERROR: $($response.error)" -ForegroundColor Red
    }
} catch {
    Write-Host "ERROR: $_" -ForegroundColor Red
    if ($_.Exception.Response) {
        $reader = New-Object System.IO.StreamReader($_.Exception.Response.GetResponseStream())
        $responseBody = $reader.ReadToEnd()
        Write-Host "Response: $responseBody" -ForegroundColor Red
    }
}

Write-Host ""
Write-Host "Test complete!" -ForegroundColor Cyan
Write-Host ""
Write-Host "To test idempotency, run this script again with the same parameters." -ForegroundColor Yellow
Write-Host "Receipts should be skipped (not sent again)." -ForegroundColor Yellow
