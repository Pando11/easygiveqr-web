# Deployment Guide - Vercel Production Setup

## Overview

This guide covers deploying EasyGiveQR to Vercel, configuring production webhooks, and setting up automated cron jobs.

## Prerequisites

- GitHub repository with your code
- Vercel account (free tier works)
- Stripe account (production mode)
- Supabase project
- SendGrid account

## Step 1: Connect GitHub Repository to Vercel

1. **Go to Vercel Dashboard:**
   - Visit https://vercel.com/dashboard
   - Click **"Add New..."** → **"Project"**

2. **Import Repository:**
   - Select your GitHub repository
   - Click **"Import"**

3. **Configure Project:**
   - **Framework Preset:** Next.js (auto-detected)
   - **Root Directory:** `./` (or your project root)
   - **Build Command:** `npm run build` (default)
   - **Output Directory:** `.next` (default)
   - Click **"Deploy"**

4. **Wait for Initial Deploy:**
   - Vercel will build and deploy your app
   - Note the deployment URL (e.g., `https://your-project.vercel.app`)

## Step 2: Set Environment Variables

### In Vercel Dashboard:

1. **Go to Project Settings:**
   - Click on your project
   - Go to **Settings** → **Environment Variables**

2. **Add Each Variable:**

   **Supabase:**
   ```
   SUPABASE_URL=https://your-project.supabase.co
   SUPABASE_SERVICE_ROLE_KEY=your-service-role-key
   ```

   **Stripe:**
   ```
   STRIPE_SECRET_KEY=sk_live_...
   STRIPE_PUBLISHABLE_KEY=pk_live_...
   STRIPE_WEBHOOK_SECRET=whsec_... (see Step 3)
   ```

   **SendGrid:**
   ```
   SENDGRID_API_KEY=SG....
   SENDGRID_FROM_EMAIL=noreply@yourdomain.com
   ```

   **Security:**
   ```
   ADMIN_SECRET=your-secure-random-string-here
   CRON_SECRET=your-secure-random-string-here
   ```

   **Site URL:**
   ```
   NEXT_PUBLIC_SITE_URL=https://your-domain.com
   ```
   - For production: Use your custom domain
   - For preview: Use `https://your-project.vercel.app`
   - **Important:** This must match your actual deployed domain

3. **Set for All Environments:**
   - Check **Production**, **Preview**, and **Development**
   - Click **"Save"**

4. **Redeploy:**
   - After adding environment variables, trigger a new deployment
   - Go to **Deployments** → Click **"..."** → **"Redeploy"**

## Step 3: Configure Stripe Production Webhook

### Create Webhook in Stripe Dashboard:

1. **Go to Stripe Dashboard:**
   - Visit https://dashboard.stripe.com/webhooks
   - Click **"Add endpoint"**

2. **Configure Endpoint:**
   - **Endpoint URL:** `https://your-domain.com/api/stripe-webhook`
     - Replace `your-domain.com` with your actual Vercel domain
   - **Description:** "EasyGiveQR Production Webhook"
   - Click **"Add endpoint"**

3. **Select Events:**
   - In the webhook details page, click **"Add events"**
   - Select: `checkout.session.completed`
   - Click **"Add events"**

4. **Copy Signing Secret:**
   - In the webhook details, find **"Signing secret"**
   - Click **"Reveal"** and copy the secret (starts with `whsec_`)
   - **Add to Vercel Environment Variables:**
     - Go to Vercel → Settings → Environment Variables
     - Add: `STRIPE_WEBHOOK_SECRET=whsec_...`
     - Save and redeploy

5. **Test Webhook:**
   - In Stripe Dashboard → Webhooks → Your endpoint
   - Click **"Send test webhook"**
   - Select `checkout.session.completed`
   - Click **"Send test webhook"**
   - Check Vercel function logs to verify it was received

### Test with Real Donation:

1. **Make a Test Donation:**
   - Go to `https://your-domain.com/donate?church_id=EGQR-123`
   - Complete a test donation (use Stripe test card: `4242 4242 4242 4242`)

2. **Verify Webhook:**
   - Check Stripe Dashboard → Webhooks → Your endpoint → **"Recent events"**
   - Should see `checkout.session.completed` event
   - Check Vercel function logs to confirm webhook was processed

## Step 4: Configure Vercel Cron Jobs

### Update vercel.json:

1. **Edit `vercel.json` in your repository:**
   ```json
   {
     "crons": [
       {
         "path": "/api/jobs/weekly-summary?cron=CRON_SECRET_PLACEHOLDER",
         "schedule": "0 14 * * 3"
       },
       {
         "path": "/api/jobs/wednesday-payouts?cron=CRON_SECRET_PLACEHOLDER",
         "schedule": "0 14 * * 3"
       },
       {
         "path": "/api/jobs/annual-receipts?cron=CRON_SECRET_PLACEHOLDER",
         "schedule": "0 14 15 1 *"
       }
     ]
   }
   ```

2. **Replace CRON_SECRET_PLACEHOLDER:**
   - **Option A: Use the helper script (recommended):**
     ```powershell
     .\generate-vercel-cron.ps1 -CronSecret "your-actual-cron-secret"
     ```
   - **Option B: Manual replacement:**
     - Replace `CRON_SECRET_PLACEHOLDER` with your actual `CRON_SECRET` value
     - Example: `/api/jobs/weekly-summary?cron=your-actual-cron-secret-here`
   - **Security Note:** The secret will be in `vercel.json` (which should be in your repo). Keep your repository private.

3. **Cron Schedule Explanation:**
   - `0 14 * * 3` = Every Wednesday at 14:00 UTC (09:00 America/Chicago)
   - `0 14 15 1 *` = January 15 at 14:00 UTC (09:00 America/Chicago)

4. **Commit and Push:**
   ```bash
   git add vercel.json
   git commit -m "Configure Vercel cron jobs"
   git push
   ```

5. **Verify in Vercel Dashboard:**
   - Go to **Settings** → **Cron Jobs**
   - Should see your three cron jobs listed
   - Status should be **"Active"**

### Alternative: Using Environment Variable in Cron Path

**If Vercel supports environment variable substitution in cron paths, you can use:**
```json
{
  "crons": [
    {
      "path": "/api/jobs/weekly-summary?cron=${CRON_SECRET}",
      "schedule": "0 14 * * 3"
    }
  ]
}
```

**However, Vercel Cron may not support this. If not, use the actual secret value (it's only visible in Vercel dashboard).**

## Step 5: Test Health Endpoint

### Verify Deployment:

1. **Check Health Endpoint:**
   ```bash
   curl https://your-domain.com/api/health
   ```

2. **Expected Response:**
   ```json
   {
     "ok": true,
     "env": "production",
     "timestamp": "2026-01-27T14:00:00.000Z"
   }
   ```

3. **If Missing Variables:**
   ```json
   {
     "ok": false,
     "env": "production",
     "error": "Missing required environment variables",
     "missing_vars": ["STRIPE_WEBHOOK_SECRET", ...]
   }
   ```

## Step 6: Custom Domain (Optional)

### Add Custom Domain:

1. **In Vercel Dashboard:**
   - Go to **Settings** → **Domains**
   - Click **"Add Domain"**
   - Enter your domain (e.g., `easygiveqr.com`)

2. **Configure DNS:**
   - Follow Vercel's DNS instructions
   - Add the required DNS records to your domain provider

3. **Update Environment Variable:**
   - Update `NEXT_PUBLIC_SITE_URL` to your custom domain
   - Redeploy

## Step 7: Verify Production Setup

### Checklist:

- [ ] All environment variables set in Vercel
- [ ] `NEXT_PUBLIC_SITE_URL` matches deployed domain
- [ ] Stripe webhook created and `STRIPE_WEBHOOK_SECRET` set
- [ ] Webhook tested with real donation
- [ ] Vercel cron jobs configured and active
- [ ] Health endpoint returns `{ ok: true }`
- [ ] Test donation flow end-to-end
- [ ] QR codes generate correctly
- [ ] Admin endpoints require authentication

### Test Commands:

```bash
# Health check
curl https://your-domain.com/api/health

# Test admin endpoint (should return 401)
curl -X POST https://your-domain.com/api/qr/generate \
  -H "Content-Type: application/json" \
  -d '{"church_id": "EGQR-123"}'

# Test admin endpoint with auth (should work)
curl -X POST https://your-domain.com/api/qr/generate \
  -H "Content-Type: application/json" \
  -H "x-admin-secret: your-admin-secret" \
  -d '{"church_id": "EGQR-123"}'

# Test cron endpoint manually
curl -X POST https://your-domain.com/api/jobs/weekly-summary?cron=your-cron-secret
```

## Cron Schedule Reference

### Weekly Summary (Wednesdays 09:00 CT)

**Cron:** `0 14 * * 3`
- **UTC:** 14:00 (2:00 PM)
- **America/Chicago:** 09:00 (9:00 AM) - accounts for DST
- **Frequency:** Every Wednesday

### Wednesday Payouts (Wednesdays 09:00 CT)

**Cron:** `0 14 * * 3`
- **UTC:** 14:00 (2:00 PM)
- **America/Chicago:** 09:00 (9:00 AM)
- **Frequency:** Every Wednesday

### Annual Receipts (January 15, 09:00 CT)

**Cron:** `0 14 15 1 *`
- **UTC:** 14:00 (2:00 PM) on January 15
- **America/Chicago:** 09:00 (9:00 AM) on January 15
- **Frequency:** Yearly

**Note:** Adjust UTC times if your timezone offset differs. America/Chicago is UTC-6 (CST) or UTC-5 (CDT).

**Time Conversion:**
- America/Chicago 09:00 = UTC 14:00 (during CDT, March-November)
- America/Chicago 09:00 = UTC 15:00 (during CST, November-March)
- The cron schedule `0 14 * * 3` runs at 14:00 UTC, which is approximately 09:00 CT (may vary by 1 hour due to DST)
- For exact 09:00 CT, you may need to adjust based on current DST status

## Troubleshooting

### "Missing required environment variables"

**Solution:**
- Check Vercel Dashboard → Settings → Environment Variables
- Ensure all required variables are set
- Verify they're set for the correct environment (Production/Preview)
- Redeploy after adding variables

### "Unauthorized" on Cron Jobs

**Solution:**
- Verify `CRON_SECRET` is set in Vercel environment variables
- Check that `vercel.json` cron paths include `?cron=CRON_SECRET`
- Ensure the secret in the URL matches the environment variable
- Check Vercel function logs for detailed error messages

### Webhook Not Receiving Events

**Solution:**
- Verify webhook URL is correct: `https://your-domain.com/api/stripe-webhook`
- Check `STRIPE_WEBHOOK_SECRET` is set correctly in Vercel
- Verify webhook is enabled in Stripe Dashboard
- Check Stripe Dashboard → Webhooks → Your endpoint → Recent events
- Check Vercel function logs for webhook processing errors

### Cron Jobs Not Running

**Solution:**
- Verify `vercel.json` is committed and deployed
- Check Vercel Dashboard → Settings → Cron Jobs
- Ensure cron jobs show as "Active"
- Check Vercel function logs for cron execution
- Verify cron schedule syntax is correct

### Wrong Domain in QR Codes

**Solution:**
- Verify `NEXT_PUBLIC_SITE_URL` matches your deployed domain
- Redeploy after updating the variable
- Regenerate QR codes after fixing the URL

## Security Notes

### Cron Secret in URL

**Important:** The cron secret is included in the `vercel.json` cron path as a query parameter. This means:
- ✅ The secret is only visible in Vercel dashboard (not in public URLs)
- ✅ Vercel Cron requests are internal and not exposed publicly
- ⚠️ The secret appears in `vercel.json` (which should be in your repo)
- **Recommendation:** Use a strong, unique `CRON_SECRET` and keep your repository private

### Environment Variables

- ✅ Never commit `.env.local` to git
- ✅ Use Vercel environment variables for production secrets
- ✅ Rotate secrets periodically
- ✅ Use different secrets for `ADMIN_SECRET` and `CRON_SECRET`

## Production Checklist

Before going live:

- [ ] All environment variables configured
- [ ] Stripe webhook tested with real donation
- [ ] Cron jobs scheduled and tested
- [ ] Health endpoint returns `{ ok: true }`
- [ ] Custom domain configured (if applicable)
- [ ] SSL certificate active (automatic with Vercel)
- [ ] Test donation flow end-to-end
- [ ] Verify QR codes work correctly
- [ ] Check function logs for errors
- [ ] Monitor first few cron job executions

## Monitoring

### Vercel Function Logs

1. **View Logs:**
   - Go to Vercel Dashboard → Your Project → **Functions**
   - Click on a function to see logs
   - Filter by deployment or time range

2. **Monitor:**
   - Webhook processing errors
   - Cron job execution results
   - API endpoint errors
   - Rate limiting hits

### Stripe Dashboard

- Monitor webhook delivery success rate
- Check for failed webhook deliveries
- Review payment processing

### Supabase Dashboard

- Monitor database queries
- Check for connection issues
- Review storage usage

## Production Domain Validation Checklist

After deploying to `https://easygiveqr.net`, verify the following:

### Domain & SSL
- [ ] `https://easygiveqr.net` loads correctly
- [ ] `https://www.easygiveqr.net` loads correctly (or redirects to apex)
- [ ] SSL certificate is valid (green lock icon in browser)
- [ ] No mixed content warnings

### Donation Flow
- [ ] Donate page loads: `https://easygiveqr.net/donate?church_id=EGQR-123`
- [ ] Church branding displays correctly (logo, name, colors)
- [ ] Preset amounts work ($5, $10, $25, $50)
- [ ] Frequency toggle works (if monthly enabled)
- [ ] Checkout redirects to Stripe correctly
- [ ] Success page loads: `https://easygiveqr.net/donate/success?church_id=...&session_id=...`
- [ ] Cancel page loads: `https://easygiveqr.net/donate/cancel?church_id=...`

### Webhook & Database
- [ ] Complete a test donation
- [ ] Check Stripe Dashboard → Webhooks → Recent events
- [ ] Verify `checkout.session.completed` event received with status `200`
- [ ] Check Supabase `public.donations` table - donation row created
- [ ] Verify donation appears in success page after webhook processes

### QR Codes
- [ ] QR code generation works (admin route)
- [ ] QR code URL points to `https://easygiveqr.net/donate?church_id=...`
- [ ] Scan QR code with phone camera
- [ ] QR code opens correct donation page on `https://easygiveqr.net`

### Engagement Forms
- [ ] Prayer form: `https://easygiveqr.net/engage/prayer?church_id=EGQR-123`
- [ ] Visitor form: `https://easygiveqr.net/engage/visitor?church_id=EGQR-123`
- [ ] Volunteer form: `https://easygiveqr.net/engage/volunteer?church_id=EGQR-123`
- [ ] Forms submit successfully
- [ ] Success confirmation pages display

### Environment Variables
- [ ] `SITE_URL=https://easygiveqr.net` set in Vercel
- [ ] `STRIPE_WEBHOOK_SECRET` set to production webhook secret
- [ ] `STRIPE_SECRET_KEY` set to production key (`sk_live_...`)
- [ ] All other required env vars configured

### Stripe Configuration
- [ ] Webhook endpoint: `https://easygiveqr.net/api/stripe-webhook`
- [ ] `easygiveqr.net` added to Stripe Checkout redirect domains
- [ ] Production keys in use (not test keys)
- [ ] Webhook events configured: `checkout.session.completed`, `customer.subscription.updated`, `customer.subscription.deleted`

## Support

For issues:
1. Check Vercel function logs
2. Check Stripe webhook logs
3. Verify environment variables
4. Test endpoints manually with curl
5. Review this guide's troubleshooting section
6. Review `DOMAIN_SETUP.md` for domain issues
7. Review `STRIPE_SETUP.md` for Stripe configuration issues
