# Smoke Test Suite

## Production Smoke Test

Run the production smoke test to verify critical endpoints are working:

```bash
node ops/smoke/smoke-prod.ts EGQR-TEST
```

**Requirements:**
- Node 18+ (for native fetch)
- Test church ID (e.g., `EGQR-TEST`)
- Production URL: `https://easygiveqr.net`

**What it checks:**
- Donation page loads (200)
- Webhook endpoint rejects GET requests (400/405)
- Health endpoint responds (if available)

## Duplicate Event Test

To test webhook idempotency:

1. **Get a webhook event ID from Stripe Dashboard:**
   - Go to Stripe Dashboard → Developers → Events
   - Find a `checkout.session.completed` event
   - Copy the event ID (e.g., `evt_...`)

2. **Replay the event:**
   ```bash
   # Using Stripe CLI (if available)
   stripe events resend evt_xxxxx
   ```

3. **Verify idempotency:**
   - Check `stripe_webhook_events` table - should show duplicate detected
   - Check `donations` table - should NOT have duplicate rows
   - Webhook should return `{ received: true, duplicate: true }`

## Manual Smoke Test Checklist

1. **Health Endpoint:**
   ```bash
   curl https://easygiveqr.net/api/health
   ```
   Expected: `{ ok: true, version: "1.0.0", env: "production" }`

2. **Smoke Test Endpoint:**
   ```bash
   curl -X POST https://easygiveqr.net/api/admin/smoke/run \
     -H "x-admin-secret: YOUR_SECRET" \
     -H "Content-Type: application/json" \
     -d '{"church_id": "EGQR-TEST"}'
   ```
   Expected: All checks PASS

3. **Donation Page:**
   ```bash
   curl https://easygiveqr.net/donate?church_id=EGQR-TEST
   ```
   Expected: 200, HTML page loads

4. **Webhook Endpoint (should reject GET):**
   ```bash
   curl https://easygiveqr.net/api/stripe-webhook
   ```
   Expected: 400 or 405 (GET not allowed)

## Troubleshooting

**Smoke test fails:**
- Check Vercel deployment status
- Verify environment variables are set
- Check Vercel logs for errors

**Webhook not receiving events:**
- Verify webhook URL in Stripe Dashboard
- Check webhook secret matches Vercel env var
- Verify webhook events are enabled in Stripe

**Donation page not loading:**
- Check church exists in Supabase
- Verify church status is `active`
- Check subscription status is `active`
- Verify Stripe Connect is complete
