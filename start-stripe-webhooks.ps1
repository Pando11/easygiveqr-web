# Start Stripe Webhook Forwarding
# This forwards Stripe webhooks to your local Next.js app

Write-Host "Starting Stripe webhook forwarding..." -ForegroundColor Cyan
Write-Host "Forwarding to: http://localhost:3000/api/stripe-webhook" -ForegroundColor Yellow
Write-Host ""
Write-Host "IMPORTANT: Make sure your Next.js app is running on http://localhost:3000" -ForegroundColor Yellow
Write-Host ""
Write-Host "Press Ctrl+C to stop" -ForegroundColor Gray
Write-Host ""

# Start Stripe webhook listener
stripe listen --forward-to http://localhost:3000/api/stripe-webhook
