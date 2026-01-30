# Stripe LIVE Webhook Setup (CRITICAL)

## Why This Matters

**This is the most common production failure point. Setting up the webhook incorrectly will cause all donations to fail silently.**

## Step-by-Step Setup

### 1. Switch to LIVE Mode

1. Go to Stripe Dashboard
2. **Toggle to LIVE mode** (not test mode)
3. Verify you see "LIVE" badge in top right

### 2. Create Webhook Endpoint

1. Go to: **Developers → Webhooks**
2. Click **"Add endpoint"**
3. Enter endpoint URL: `https://easygiveqr.net/api/stripe-webhook`
4. Click **"Add endpoint"**

### 3. Select Required Events

**Minimum required events:**
- ✅ `checkout.session.completed` (critical for one-time donations)
- ✅ `payment_intent.succeeded` (if used)
- ✅ `customer.subscription.created` (if using subscriptions)
- ✅ `customer.subscription.updated` (if using subscriptions)
- ✅ `customer.subscription.deleted` (if using subscriptions)

**Click "Add events"**

### 4. Copy Webhook Signing Secret

1. After creating endpoint, click on it
2. Find **"Signing secret"** section
3. Click **"Reveal"** or **"Click to reveal"**
4. Copy the secret (starts with `whsec_`)
5. **⚠️ CRITICAL:** This is the LIVE secret, not test secret

### 5. Set Environment Variable in Vercel

1. Go to Vercel Dashboard → Your Project → Settings → Environment Variables
2. Add/Update: `STRIPE_WEBHOOK_SECRET`
3. Paste the LIVE webhook secret (starts with `whsec_`)
4. **Select "Production" environment** (not Preview)
5. Click "Save"

### 6. Redeploy

**⚠️ IMPORTANT:** Vercel won't apply new env vars to existing builds. You must redeploy.

1. Go to Vercel Dashboard → Deployments
2. Click "Redeploy" on latest deployment
3. Or push a new commit to trigger deployment

### 7. Test Webhook

1. In Stripe Dashboard → Webhooks → Your endpoint
2. Click **"Send test webhook"**
3. Select event: `checkout.session.completed`
4. Click **"Send test webhook"**
5. Verify:
   - Status shows **200 OK** ✅
   - Response time is reasonable (< 2 seconds)
   - No error messages

### 8. Verify in Database

1. Go to Supabase Dashboard → Table Editor
2. Open `stripe_webhook_events` table
3. Verify new row exists for test event:
   - `event_id` matches Stripe event ID
   - `status` = "success"
   - `processed_at` is recent

## Common Gotchas

### ❌ Using Test Mode Secret in Production
- **Symptom:** Webhook signature verification fails
- **Fix:** Use LIVE mode secret, not test mode secret
- **Verify:** Secret starts with `whsec_` and matches LIVE endpoint

### ❌ Wrong Endpoint URL
- **Symptom:** Webhook never receives events
- **Fix:** Verify URL is exactly `https://easygiveqr.net/api/stripe-webhook`
- **Check:** No trailing slash, correct domain

### ❌ Missing Events
- **Symptom:** Some donations don't get processed
- **Fix:** Add all required events (see Step 3)
- **Verify:** Check Stripe Dashboard → Webhooks → Your endpoint → Events

### ❌ Not Redeploying After Setting Env Var
- **Symptom:** Webhook still uses old secret
- **Fix:** Redeploy after setting `STRIPE_WEBHOOK_SECRET`
- **Verify:** Check Vercel logs show new deployment

## Pass Criteria

- [ ] Webhook endpoint created in Stripe LIVE mode
- [ ] Endpoint URL: `https://easygiveqr.net/api/stripe-webhook`
- [ ] Required events selected (see Step 3)
- [ ] LIVE webhook secret copied (starts with `whsec_`)
- [ ] `STRIPE_WEBHOOK_SECRET` set in Vercel Production environment
- [ ] Vercel redeployed after setting env var
- [ ] Test webhook sent from Stripe Dashboard
- [ ] Stripe Dashboard shows **200 OK** status
- [ ] `stripe_webhook_events` table has new row
- [ ] Screenshot: Stripe webhook delivery = 200 ✅

## Verification Query

After sending test webhook, verify in Supabase:

```sql
SELECT 
  event_id,
  event_type,
  status,
  processed_at,
  error_message
FROM stripe_webhook_events
ORDER BY processed_at DESC
LIMIT 5;
```

Expected: Recent row with `status = 'success'` and `event_type = 'checkout.session.completed'`

---

**Last Verified:** _[TO BE FILLED]_

**Webhook Secret Set By:** _[TO BE FILLED]_
