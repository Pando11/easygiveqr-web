# Stripe Setup Guide - easygiveqr.net

## Overview

This guide covers configuring Stripe for production use with `https://easygiveqr.net`.

## Prerequisites

- Stripe account in **Production mode** (not test mode)
- Domain `easygiveqr.net` connected to Vercel (see `DOMAIN_SETUP.md`)
- SSL certificate active (HTTPS working)

## Step 1: Configure Webhook Endpoint

### In Stripe Dashboard:

1. **Go to Webhooks:**
   - Visit https://dashboard.stripe.com/webhooks
   - Click **"Add endpoint"** (or edit existing endpoint)

2. **Set Endpoint URL:**
   ```
   https://easygiveqr.net/api/stripe-webhook
   ```

3. **Select Events to Listen To:**
   - `checkout.session.completed` (for donations and subscriptions)
   - `customer.subscription.updated` (for subscription changes)
   - `customer.subscription.deleted` (for subscription cancellations)

4. **Save Endpoint:**
   - Click **"Add endpoint"** or **"Save"**

5. **Copy Signing Secret:**
   - After creating the endpoint, Stripe will show a **"Signing secret"**
   - It starts with `whsec_...`
   - **Copy this value** - you'll need it for Vercel environment variables

## Step 2: Set Environment Variable in Vercel

1. **Go to Vercel Dashboard:**
   - Project → **Settings** → **Environment Variables**

2. **Add/Update:**
   ```
   STRIPE_WEBHOOK_SECRET=whsec_... (your production webhook secret)
   ```

3. **Redeploy:**
   - Trigger a new deployment to apply the change

## Step 3: Configure Allowed Domains (Stripe Checkout)

### In Stripe Dashboard:

1. **Go to Settings:**
   - Visit https://dashboard.stripe.com/settings/checkout

2. **Check Redirect Domains:**
   - Under **"Redirect domains"**, ensure `easygiveqr.net` is listed
   - If not, add it:
     - Click **"Add domain"**
     - Enter `easygiveqr.net`
     - Click **"Add"**

3. **Also Add www (if needed):**
   - Add `www.easygiveqr.net` if you want to support www subdomain

**Note:** Stripe automatically allows common domains, but it's good to explicitly add your domain.

## Step 4: Apple Pay Domain Verification (Optional)

If you want to enable Apple Pay:

1. **Go to Apple Pay Settings:**
   - Visit https://dashboard.stripe.com/settings/payment_methods
   - Find **Apple Pay** section

2. **Add Domain:**
   - Click **"Add domain"**
   - Enter `easygiveqr.net`
   - Follow Stripe's instructions to verify domain ownership
   - Usually involves adding a file to your domain's `.well-known` directory

3. **Verify:**
   - Stripe will verify the domain
   - Once verified, Apple Pay will be available in Checkout

## Step 5: Google Pay (Automatic)

Google Pay is automatically enabled for verified domains. No additional setup required if your domain is properly configured.

## Step 6: Venmo Availability

Venmo is available in Stripe Checkout for:
- US-based customers
- When using US payment methods
- Automatically enabled if your Stripe account supports it

No additional configuration needed.

## Step 7: Test Webhook

1. **Make a Test Donation:**
   - Visit: `https://easygiveqr.net/donate?church_id=EGQR-123`
   - Complete a test donation (use Stripe test card: `4242 4242 4242 4242`)

2. **Check Webhook Logs:**
   - Go to Stripe Dashboard → **Webhooks**
   - Click on your webhook endpoint
   - View **"Recent events"** tab
   - You should see `checkout.session.completed` event with status `200`

3. **Verify in Database:**
   - Check `public.donations` table in Supabase
   - Should see the new donation row

## Step 8: Production Keys

Ensure you're using **Production** keys (not test keys):

### In Vercel Environment Variables:

```
STRIPE_SECRET_KEY=sk_live_... (production secret key)
STRIPE_PUBLISHABLE_KEY=pk_live_... (production publishable key)
STRIPE_WEBHOOK_SECRET=whsec_... (production webhook secret)
```

### Get Production Keys:

1. **Go to Stripe Dashboard:**
   - Visit https://dashboard.stripe.com/apikeys

2. **Toggle to "Live mode"** (top right)

3. **Copy Keys:**
   - **Secret key:** Starts with `sk_live_...`
   - **Publishable key:** Starts with `pk_live_...`

## Verification Checklist

- [ ] Webhook endpoint created: `https://easygiveqr.net/api/stripe-webhook`
- [ ] Webhook signing secret copied and added to Vercel env vars
- [ ] Events selected: `checkout.session.completed`, `customer.subscription.updated`, `customer.subscription.deleted`
- [ ] `easygiveqr.net` added to Stripe Checkout redirect domains
- [ ] Production Stripe keys set in Vercel (not test keys)
- [ ] Test donation completed successfully
- [ ] Webhook event received in Stripe Dashboard (status 200)
- [ ] Donation row created in Supabase database
- [ ] Apple Pay domain verified (if using Apple Pay)
- [ ] Google Pay working (automatic)

## Troubleshooting

### Webhook Not Receiving Events

**Symptoms:** Events show in Stripe but not reaching your endpoint

**Solutions:**
- Verify webhook URL is correct: `https://easygiveqr.net/api/stripe-webhook`
- Check Vercel deployment logs for errors
- Verify `STRIPE_WEBHOOK_SECRET` matches the signing secret in Stripe
- Check Stripe webhook logs for error messages
- Ensure endpoint returns `200` status code

### Checkout Redirect Fails

**Symptoms:** After payment, redirect to success page fails

**Solutions:**
- Verify `easygiveqr.net` is in Stripe Checkout redirect domains
- Check `SITE_URL` environment variable is set to `https://easygiveqr.net`
- Verify success/cancel URLs in checkout session creation use `https://easygiveqr.net`

### Apple Pay Not Showing

**Symptoms:** Apple Pay option not available in Checkout

**Solutions:**
- Verify domain is added and verified in Stripe Apple Pay settings
- Ensure domain verification file is accessible at `https://easygiveqr.net/.well-known/apple-developer-merchantid-domain-association`
- Check that you're testing on an Apple device with Apple Pay enabled

## Important Notes

- **Never use test keys in production:** Always use `sk_live_...` and `pk_live_...`
- **Webhook secret is different for test vs production:** Make sure you're using the production webhook secret
- **Domain must be HTTPS:** Stripe requires HTTPS for webhooks and Checkout redirects
- **Both apex and www:** Consider adding both `easygiveqr.net` and `www.easygiveqr.net` to redirect domains if you support both

## Next Steps

After Stripe is configured:
1. Test full donation flow end-to-end
2. Test subscription checkout flow
3. Verify webhook events are being processed correctly
4. Monitor Stripe Dashboard for any errors
5. Set up Stripe email notifications for failed payments (optional)
