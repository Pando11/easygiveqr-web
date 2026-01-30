# Test Church Onboarding
# This script provides instructions for testing the onboarding flow

param(
    [string]$ChurchId = "EGQR-999"
)

Write-Host "========================================" -ForegroundColor Cyan
Write-Host "Church Onboarding Test Instructions" -ForegroundColor Cyan
Write-Host "========================================" -ForegroundColor Cyan
Write-Host ""

Write-Host "The onboarding flow requires multipart/form-data with file upload," -ForegroundColor Yellow
Write-Host "which is best tested using the admin UI page." -ForegroundColor Yellow
Write-Host ""

Write-Host "Step 1: Open Admin Page" -ForegroundColor Green
Write-Host "  URL: http://localhost:3000/admin/onboarding" -ForegroundColor White
Write-Host ""

Write-Host "Step 2: Fill Out Form" -ForegroundColor Green
Write-Host "  Church ID: $ChurchId" -ForegroundColor White
Write-Host "  Legal Name: Test Church Legal Name" -ForegroundColor White
Write-Host "  Display Name: Test Church" -ForegroundColor White
Write-Host "  EIN: 12-3456789" -ForegroundColor White
Write-Host "  Preferred Language: EN" -ForegroundColor White
Write-Host "  Primary Color: #1D4ED8" -ForegroundColor White
Write-Host "  Donation Phrase: Support our mission" -ForegroundColor White
Write-Host "  Admin Emails: admin@testchurch.com, finance@testchurch.com" -ForegroundColor White
Write-Host "  Logo: Upload any image file (PNG/JPG/SVG/WebP, max 5MB)" -ForegroundColor White
Write-Host ""

Write-Host "Step 3: Submit Form" -ForegroundColor Green
Write-Host "  Click 'Create Church & Provision Everything'" -ForegroundColor White
Write-Host ""

Write-Host "Step 4: Verify Results" -ForegroundColor Green
Write-Host "  Expected in success message:" -ForegroundColor White
Write-Host "    - Church ID: $ChurchId" -ForegroundColor Gray
Write-Host "    - Donation URL displayed" -ForegroundColor Gray
Write-Host "    - Logo URL displayed" -ForegroundColor Gray
Write-Host "    - QR code image displayed" -ForegroundColor Gray
Write-Host "    - Stripe onboarding link button" -ForegroundColor Gray
Write-Host ""

Write-Host "Step 5: Verify in Supabase" -ForegroundColor Green
Write-Host "  Run this SQL query:" -ForegroundColor White
Write-Host "    SELECT" -ForegroundColor Gray
Write-Host "      church_id," -ForegroundColor Gray
Write-Host "      legal_name," -ForegroundColor Gray
Write-Host "      display_name," -ForegroundColor Gray
Write-Host "      logo_url," -ForegroundColor Gray
Write-Host "      qr_code_url," -ForegroundColor Gray
Write-Host "      stripe_account_id," -ForegroundColor Gray
Write-Host "      stripe_onboarding_status," -ForegroundColor Gray
Write-Host "      status" -ForegroundColor Gray
Write-Host "    FROM public.churches" -ForegroundColor Gray
Write-Host "    WHERE church_id = '$ChurchId';" -ForegroundColor Gray
Write-Host ""

Write-Host "Step 6: Test URLs" -ForegroundColor Green
Write-Host "  - Open logo_url in browser (should show logo)" -ForegroundColor White
Write-Host "  - Open qr_code_url in browser (should show QR code)" -ForegroundColor White
Write-Host "  - Scan QR code (should navigate to donate page)" -ForegroundColor White
Write-Host ""

Write-Host "Step 7: Test Stripe Onboarding" -ForegroundColor Green
Write-Host "  - Click 'Complete Stripe Onboarding' button" -ForegroundColor White
Write-Host "  - Should open Stripe Connect onboarding page" -ForegroundColor White
Write-Host "  - Complete or cancel (for testing)" -ForegroundColor White
Write-Host ""

Write-Host "========================================" -ForegroundColor Cyan
Write-Host "Alternative: Test with curl" -ForegroundColor Cyan
Write-Host "========================================" -ForegroundColor Cyan
Write-Host ""
Write-Host "If you want to test the API directly with curl:" -ForegroundColor Yellow
Write-Host ""
Write-Host '  curl -X POST http://localhost:3000/api/onboarding/create-church \' -ForegroundColor White
Write-Host '    -F "church_id=EGQR-999" \' -ForegroundColor Gray
Write-Host '    -F "legal_name=Test Church Legal Name" \' -ForegroundColor Gray
Write-Host '    -F "display_name=Test Church" \' -ForegroundColor Gray
Write-Host '    -F "ein=12-3456789" \' -ForegroundColor Gray
Write-Host '    -F "preferred_language=EN" \' -ForegroundColor Gray
Write-Host '    -F "primary_color=#1D4ED8" \' -ForegroundColor Gray
Write-Host '    -F "donation_phrase=Support our mission" \' -ForegroundColor Gray
Write-Host '    -F "admin_emails=admin@testchurch.com,finance@testchurch.com" \' -ForegroundColor Gray
Write-Host '    -F "logo=@/path/to/logo.png"' -ForegroundColor Gray
Write-Host ""

Write-Host "Test complete!" -ForegroundColor Cyan
