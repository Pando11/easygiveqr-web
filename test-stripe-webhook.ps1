# Test Stripe Webhook - Sends a test event to your local endpoint
# Make sure stripe listen is running first!

Write-Host "Testing Stripe webhook..." -ForegroundColor Cyan
Write-Host ""

# Trigger a test checkout.session.completed event
stripe trigger checkout.session.completed

Write-Host ""
Write-Host "Test event sent!" -ForegroundColor Green
Write-Host "Check your Next.js app console and Stripe CLI output to confirm receipt." -ForegroundColor Yellow
