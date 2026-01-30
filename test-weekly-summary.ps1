# Test Weekly Summary Batch Job
# This script tests the weekly summary endpoint locally

Write-Host "========================================" -ForegroundColor Cyan
Write-Host "Testing Weekly Summary Batch Job" -ForegroundColor Cyan
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

# API endpoint
$url = "http://localhost:3000/api/jobs/weekly-summary"

Write-Host "Calling: $url" -ForegroundColor Yellow
Write-Host ""

try {
    $headers = @{
        "x-cron-secret" = $cronSecret
        "Content-Type" = "application/json"
    }

    $response = Invoke-RestMethod -Uri $url -Method POST -Headers $headers

    Write-Host "Response:" -ForegroundColor Green
    Write-Host ($response | ConvertTo-Json -Depth 10) -ForegroundColor White
    Write-Host ""

    if ($response.ok) {
        Write-Host "SUCCESS!" -ForegroundColor Green
        Write-Host "Churches processed: $($response.summary.churchesProcessed)" -ForegroundColor Cyan
        Write-Host "Emails sent: $($response.summary.emailsSent)" -ForegroundColor Cyan
        Write-Host "Failures: $($response.summary.failures)" -ForegroundColor Cyan
        
        if ($response.summary.failures -gt 0 -and $response.summary.failuresList) {
            Write-Host ""
            Write-Host "Failures:" -ForegroundColor Yellow
            $response.summary.failuresList | ForEach-Object {
                Write-Host "  - $($_.church_id): $($_.error)" -ForegroundColor Red
            }
        }
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
