@echo off
echo Starting Stripe webhook forwarding...
echo Forwarding to: http://localhost:3000/api/stripe-webhook
echo.
echo IMPORTANT: Make sure your Next.js app is running on http://localhost:3000
echo.
echo Press Ctrl+C to stop
echo.

stripe listen --forward-to http://localhost:3000/api/stripe-webhook
