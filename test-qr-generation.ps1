# Test QR Code Generation
# This script tests the QR code generation endpoint

param(
    [string]$ChurchId = "EGQR-123",
    [switch]$Force = $false
)

Write-Host "========================================" -ForegroundColor Cyan
Write-Host "Testing QR Code Generation" -ForegroundColor Cyan
Write-Host "========================================" -ForegroundColor Cyan
Write-Host ""

$baseUrl = "http://localhost:3000"
$headers = @{ "Content-Type" = "application/json" }

Write-Host "Church ID: $ChurchId" -ForegroundColor Yellow
Write-Host "Force regenerate: $Force" -ForegroundColor Yellow
Write-Host ""

# Step 1: Generate QR Code
Write-Host "Step 1: Generating QR Code..." -ForegroundColor Yellow

$body = @{
    church_id = $ChurchId
    force = $Force.IsPresent
} | ConvertTo-Json

try {
    $response = Invoke-RestMethod -Uri "$baseUrl/api/qr/generate" -Method POST -Headers $headers -Body $body
    
    if ($response.ok) {
        Write-Host "[OK] QR code generated successfully!" -ForegroundColor Green
        Write-Host ""
        Write-Host "QR Code URL:" -ForegroundColor Cyan
        Write-Host $response.qr_code_url -ForegroundColor White
        Write-Host ""
        Write-Host "Donation URL:" -ForegroundColor Cyan
        Write-Host $response.donate_url -ForegroundColor White
        Write-Host ""
        
        # Step 2: Verify in database
        Write-Host "Step 2: Verify in Supabase..." -ForegroundColor Yellow
        Write-Host "Run this SQL query:" -ForegroundColor White
        Write-Host "  SELECT church_id, qr_code_url, qr_code_updated_at" -ForegroundColor Gray
        Write-Host "  FROM public.churches" -ForegroundColor Gray
        Write-Host "  WHERE church_id = '$ChurchId';" -ForegroundColor Gray
        Write-Host ""
        
        # Step 3: Test GET endpoint
        Write-Host "Step 3: Testing GET endpoint..." -ForegroundColor Yellow
        try {
            $getResponse = Invoke-RestMethod -Uri "$baseUrl/api/qr?church_id=$([uri]::EscapeDataString($ChurchId))" -Method GET
            if ($getResponse.ok) {
                Write-Host "[OK] GET endpoint works" -ForegroundColor Green
                Write-Host "  Church ID: $($getResponse.church_id)" -ForegroundColor Cyan
                Write-Host "  Donate URL: $($getResponse.donate_url)" -ForegroundColor Cyan
                Write-Host "  QR Code URL: $($getResponse.qr_code_url)" -ForegroundColor Cyan
            }
        } catch {
            Write-Host "[ERROR] GET endpoint failed: $_" -ForegroundColor Red
        }
        
        Write-Host ""
        Write-Host "========================================" -ForegroundColor Cyan
        Write-Host "Next Steps:" -ForegroundColor Cyan
        Write-Host "1. Open QR code URL in browser to view image" -ForegroundColor White
        Write-Host "2. Scan QR code with phone camera" -ForegroundColor White
        Write-Host "3. Verify it navigates to: $($response.donate_url)" -ForegroundColor White
        Write-Host "========================================" -ForegroundColor Cyan
        
    } else {
        Write-Host "[ERROR] $($response.error)" -ForegroundColor Red
    }
} catch {
    Write-Host "[ERROR] $_" -ForegroundColor Red
    if ($_.Exception.Response) {
        $reader = New-Object System.IO.StreamReader($_.Exception.Response.GetResponseStream())
        $responseBody = $reader.ReadToEnd()
        Write-Host "Response: $responseBody" -ForegroundColor Red
    }
}

Write-Host ""
Write-Host "Test complete!" -ForegroundColor Cyan
