# Stripe Production Webhook Setup

## Overview

Configure Stripe webhook endpoint for production at `https://easygiveqr.net/api/stripe-webhook`. This replaces local testing with Stripe CLI.

## Prerequisites

- Stripe account in **Production mode** (not test mode)
- Domain `https://easygiveqr.net` deployed and accessible
- SSL certificate active (HTTPS working)

## Step 1: Access Stripe Dashboard

1. **Go to Stripe Dashboard:**
   - Visit https://dashboard.stripe.com
   - **Important:** Ensure you're in **"Live mode"** (toggle in top right)

2. **Navigate to Webhooks:**
   - Click **"Developers"** in the left sidebar
   - Click **"Webhooks"** (or **"Event Destinations"** in newer Stripe UI)

## Step 2: Add Webhook Endpoint

### Option A: Using "Webhooks" (Classic UI)

1. **Click "Add endpoint"** (or "Add webhook endpoint")

2. **Enter Endpoint URL:**
   ```
   https://easygiveqr.net/api/stripe-webhook
   ```

3. **Select Events to Listen To:**
   - Click **"Select events"** or **"Add events"**
   - Check the following events:
     - `checkout.session.completed` (for donations and subscriptions)
     - `customer.subscription.updated` (for subscription changes)
     - `customer.subscription.deleted` (for subscription cancellations)
   - Click **"Add events"** or **"Save"**

4. **Save Endpoint:**
   - Click **"Add endpoint"** or **"Save"**

### Option B: Using "Event Destinations" (New UI)

1. **Click "Add destination"**

2. **Select "Webhook endpoint"**

3. **Enter Endpoint URL:**
   ```
   https://easygiveqr.net/api/stripe-webhook
   ```

4. **Select Events:**
   - `checkout.session.completed`
   - `customer.subscription.updated`
   - `customer.subscription.deleted`

5. **Save Destination**

## Step 3: Copy Signing Secret

1. **After creating the endpoint:**
   - Stripe will display a **"Signing secret"**
   - It starts with `whsec_...`
   - **Copy this value immediately** - you'll only see it once

2. **If you missed it:**
   - Click on the webhook endpoint
   - Click **"Reveal"** next to "Signing secret"
   - Copy the value

## Step 4: Set Environment Variable in Vercel

1. **Go to Vercel Dashboard:**
   - Project → **Settings** → **Environment Variables**

2. **Add/Update:**
   ```
   STRIPE_WEBHOOK_SECRET=whsec_... (your production webhook secret)
   ```

3. **Important:** 
   - This is different from your local/test webhook secret
   - Make sure you're using the **production** secret (from Live mode)

4. **Redeploy:**
   - After adding the environment variable, trigger a new deployment
   - Go to **Deployments** tab → Click **Redeploy** on latest deployment

## Step 5: Test Webhook

1. **Make a Test Donation:**
   - Visit: `https://easygiveqr.net/donate?church_id=EGQR-123`
   - Complete a test donation (use Stripe test card: `4242 4242 4242 4242`)

2. **Check Webhook Logs:**
   - Go to Stripe Dashboard → **Developers** → **Webhooks**
   - Click on your webhook endpoint
   - View **"Recent events"** or **"Event logs"** tab
   - You should see `checkout.session.completed` event
   - Status should be `200` (success)

3. **Verify in Database:**
   - Check `public.donations` table in Supabase
   - Should see the new donation row

4. **Check Webhook Health:**
   - Use admin endpoint: `GET /api/admin/webhook-smoke` (with `x-admin-secret`)
   - Should show recent webhook activity

## Step 6: Monitor Webhook Health

### Using Admin Endpoint

**GET /api/admin/webhook-smoke**

Protected by `x-admin-secret` header.

**Response:**
```json
{
  "ok": true,
  "lastWebhookAt": "2026-01-27T...",
  "count24h": 15,
  "count1h": 2
}
```

### Using Stripe Dashboard

1. **Go to Webhooks:**
   - Stripe Dashboard → **Developers** → **Webhooks**

2. **Click on your endpoint**

3. **View Metrics:**
   - Success rate
   - Recent events
   - Error logs

4. **Check Event Details:**
   - Click on any event to see:
     - Request payload
     - Response status
     - Response body
     - Retry attempts (if failed)

## Event Types

### checkout.session.completed

**When:** Payment or subscription checkout completes

**Handled for:**
- One-time donations (`mode="payment"`)
- Monthly donations (`mode="subscription"`)

**Actions:**
- Creates donation record in `public.donations`
- Updates church subscription status (if subscription)

### customer.subscription.updated

**When:** Subscription status changes (active, past_due, canceled, etc.)

**Actions:**
- Updates `public.churches.subscription_status`
- Updates `subscription_canceled_at` if canceled

### customer.subscription.deleted

**When:** Subscription is canceled/deleted

**Actions:**
- Sets `subscription_status="canceled"` in `public.churches`
- Sets `subscription_canceled_at` timestamp

## Troubleshooting

### Webhook Not Receiving Events

**Symptoms:** Events show in Stripe but not reaching your endpoint

**Solutions:**
- Verify webhook URL is correct: `https://easygiveqr.net/api/stripe-webhook`
- Check Vercel deployment logs for errors
- Verify `STRIPE_WEBHOOK_SECRET` matches the signing secret in Stripe
- Check Stripe webhook logs for error messages
- Ensure endpoint returns `200` status code
- Verify domain SSL certificate is valid

### Signature Verification Failed

**Symptoms:** Webhook returns `400 Invalid signature`

**Solutions:**
- Verify `STRIPE_WEBHOOK_SECRET` is set correctly in Vercel
- Ensure you're using the **production** webhook secret (not test)
- Check that the secret matches what's shown in Stripe Dashboard
- Redeploy after setting the environment variable

### Events Not Processing

**Symptoms:** Events received but donations not created

**Solutions:**
- Check Vercel function logs for processing errors
- Verify `stripe_webhook_events` table exists and is accessible
- Check `public.donations` table for constraint violations
- Verify `church_id` is present in checkout session metadata
- Use `/api/admin/webhook-health` to see recent errors

### Duplicate Events

**Symptoms:** Same event processed multiple times

**Solutions:**
- Webhook route uses `stripe_webhook_events` table for idempotency
- Events are logged with `event_id` (unique)
- Duplicate events are ignored if already processed
- Check `stripe_webhook_events` table for duplicate `event_id` entries

## Verification Checklist

- [ ] Webhook endpoint created in Stripe Dashboard (Live mode)
- [ ] Endpoint URL: `https://easygiveqr.net/api/stripe-webhook`
- [ ] Events selected: `checkout.session.completed`, `customer.subscription.updated`, `customer.subscription.deleted`
- [ ] Signing secret copied (`whsec_...`)
- [ ] `STRIPE_WEBHOOK_SECRET` set in Vercel environment variables
- [ ] App redeployed after setting environment variable
- [ ] Test donation completed successfully
- [ ] Webhook event received in Stripe Dashboard (status 200)
- [ ] Donation row created in Supabase `public.donations`
- [ ] `/api/admin/webhook-smoke` shows recent activity
- [ ] No signature verification errors in logs

## Important Notes

- **Production vs Test:** Use different webhook secrets for production and test
- **Event Idempotency:** Webhook route logs all events to `stripe_webhook_events` table
- **Error Handling:** Failed events are logged with error messages
- **Monitoring:** Use `/api/admin/webhook-smoke` and Stripe Dashboard to monitor health
- **Retries:** Stripe automatically retries failed webhook deliveries

## Next Steps

After webhook is configured:
1. Test with a real donation
2. Monitor webhook health using admin endpoints
3. Set up Stripe email notifications for webhook failures (optional)
4. Review webhook logs regularly for any issues
