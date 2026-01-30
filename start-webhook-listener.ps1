# Start Stripe Webhook Listener and Capture Secret
# This script starts stripe listen and extracts the webhook secret

Write-Host "Starting Stripe webhook listener..." -ForegroundColor Cyan
Write-Host "Forwarding to: http://localhost:3000/api/stripe-webhook" -ForegroundColor Yellow
Write-Host ""
Write-Host "IMPORTANT: Look for the line that says:" -ForegroundColor Yellow
Write-Host "  'Ready! Your webhook signing secret is whsec_...'" -ForegroundColor Yellow
Write-Host ""
Write-Host "Copy that whsec_... value and add it to .env.local as:" -ForegroundColor Yellow
Write-Host "  STRIPE_WEBHOOK_SECRET=whsec_..." -ForegroundColor Yellow
Write-Host ""
Write-Host "Press Ctrl+C to stop" -ForegroundColor Gray
Write-Host ""

# Start stripe listen
stripe listen --forward-to http://localhost:3000/api/stripe-webhook
