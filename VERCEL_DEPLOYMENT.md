# Vercel Deployment Guide

## Overview

Complete guide for deploying EasyGiveQR to Vercel with all required environment variables, cron jobs, and production configuration.

## Prerequisites

- GitHub repository with your code
- Vercel account (free tier works)
- Stripe account (production mode)
- Supabase project
- SendGrid account
- Domain `easygiveqr.net` (optional, but recommended)

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
   STRIPE_SECRET_KEY=sk_live_... (production key)
   STRIPE_PUBLISHABLE_KEY=pk_live_... (production key)
   STRIPE_WEBHOOK_SECRET=whsec_... (production webhook secret)
   ```

   **SendGrid:**
   ```
   SENDGRID_API_KEY=SG....
   SENDGRID_FROM_EMAIL=helping@easygiveqr.net
   SENDGRID_REPLY_TO_EMAIL=helping@easygiveqr.net
   ```

   **Site URL:**
   ```
   SITE_URL=https://easygiveqr.net
   NEXT_PUBLIC_SITE_URL=https://easygiveqr.net
   ```

   **Security:**
   ```
   ADMIN_SECRET=your-strong-admin-secret-here
   CRON_SECRET=your-strong-cron-secret-here
   ```

   **Optional (Development Only):**
   ```
   ALLOW_DONATIONS_WHEN_INACTIVE=false
   ```

3. **Set Environment Scope:**
   - For each variable, select:
     - **Production**
     - **Preview** (optional, for PR previews)
     - **Development** (optional, for local dev)

4. **Save:**
   - Click **"Save"** after adding each variable

## Step 3: Configure Custom Domain (Optional)

If you have `easygiveqr.net`:

1. **Follow `DOMAIN_SETUP.md`** for detailed instructions
2. **Quick Steps:**
   - Go to **Settings** → **Domains**
   - Add `easygiveqr.net` and `www.easygiveqr.net`
   - Configure DNS records at your registrar
   - Wait for SSL certificate (automatic)

## Step 4: Configure Cron Jobs

### Update vercel.json

1. **Edit `vercel.json`** in your repository:

```json
{
  "crons": [
    {
      "path": "/api/jobs/weekly-summary?cron=YOUR_CRON_SECRET",
      "schedule": "0 14 * * 3"
    },
    {
      "path": "/api/jobs/wednesday-payouts?cron=YOUR_CRON_SECRET",
      "schedule": "0 14 * * 3"
    },
    {
      "path": "/api/jobs/annual-receipts?cron=YOUR_CRON_SECRET",
      "schedule": "0 14 15 1 *"
    }
  ]
}
```

2. **Replace `YOUR_CRON_SECRET`:**
   - Replace with your actual `CRON_SECRET` value
   - **Important:** This file is in your repository, so use a strong secret
   - Alternatively, use a placeholder and document that it must be replaced

3. **Commit and Push:**
   - Commit `vercel.json` to your repository
   - Push to trigger a new deployment

### Cron Schedule Explanation

**Weekly Summary (Wednesday 9:00 AM America/Chicago):**
- Schedule: `0 14 * * 3` (Wednesday 14:00 UTC = 9:00 AM CDT / 8:00 AM CST)
- Runs every Wednesday

**Wednesday Payouts (Wednesday 9:00 AM America/Chicago):**
- Schedule: `0 14 * * 3` (Wednesday 14:00 UTC = 9:00 AM CDT / 8:00 AM CST)
- Runs every Wednesday

**Annual Receipts (January 15, 9:00 AM America/Chicago):**
- Schedule: `0 14 15 1 *` (January 15, 14:00 UTC = 9:00 AM CDT / 8:00 AM CST)
- Runs once per year on January 15

**Note:** UTC times account for daylight saving time. Adjust if needed.

### Verify Cron Jobs

1. **Go to Vercel Dashboard:**
   - Project → **Settings** → **Cron Jobs**
   - Should see your cron jobs listed

2. **Check Status:**
   - Each cron should show "Active"
   - Next run time should be displayed

3. **Monitor Executions:**
   - Go to **Deployments** tab
   - Filter by cron job executions
   - Check logs for any errors

## Step 5: Configure Stripe Webhook

1. **Follow `STRIPE_PRODUCTION_WEBHOOK.md`** for detailed instructions

2. **Quick Steps:**
   - Go to Stripe Dashboard → **Developers** → **Webhooks**
   - Add endpoint: `https://easygiveqr.net/api/stripe-webhook`
   - Select events: `checkout.session.completed`, `customer.subscription.updated`, `customer.subscription.deleted`
   - Copy signing secret
   - Add to Vercel as `STRIPE_WEBHOOK_SECRET`

## Step 6: Verify Deployment

### Health Check

1. **Visit Health Endpoint:**
   ```
   https://easygiveqr.net/api/health
   ```

2. **Expected Response:**
   ```json
   {
     "ok": true,
     "env": "production",
     "timestamp": "2026-01-27T..."
   }
   ```

3. **If Missing Variables:**
   ```json
   {
     "ok": false,
     "env": "production",
     "error": "Missing required environment variables",
     "missing_vars": ["STRIPE_SECRET_KEY", ...]
   }
   ```

### Test Donation Flow

1. **Visit Donate Page:**
   ```
   https://easygiveqr.net/donate?church_id=EGQR-123
   ```

2. **Complete Test Donation:**
   - Use Stripe test card: `4242 4242 4242 4242`
   - Verify redirects to success page
   - Check donation appears in database

3. **Verify Webhook:**
   - Check Stripe Dashboard → Webhooks → Recent events
   - Should see `checkout.session.completed` with status `200`
   - Use `/api/admin/webhook-smoke` to verify

### Test Admin Endpoints

1. **Webhook Smoke Test:**
   ```bash
   curl -X GET https://easygiveqr.net/api/admin/webhook-smoke \
     -H "x-admin-secret: YOUR_ADMIN_SECRET"
   ```

2. **Email Test:**
   ```bash
   curl -X POST https://easygiveqr.net/api/admin/email-test \
     -H "Content-Type: application/json" \
     -H "x-admin-secret: YOUR_ADMIN_SECRET" \
     -d '{"to_email": "your-email@example.com", "template": "weekly", "language": "EN"}'
   ```

## Step 7: Monitor and Maintain

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

## Environment Variables Reference

### Required Variables

| Variable | Description | Example |
|----------|-------------|---------|
| `SUPABASE_URL` | Supabase project URL | `https://xxx.supabase.co` |
| `SUPABASE_SERVICE_ROLE_KEY` | Supabase service role key | `sb_secret_...` |
| `STRIPE_SECRET_KEY` | Stripe secret key (production) | `sk_live_...` |
| `STRIPE_PUBLISHABLE_KEY` | Stripe publishable key (production) | `pk_live_...` |
| `STRIPE_WEBHOOK_SECRET` | Stripe webhook signing secret | `whsec_...` |
| `SENDGRID_API_KEY` | SendGrid API key | `SG....` |
| `SENDGRID_FROM_EMAIL` | Email sender address | `helping@easygiveqr.net` |
| `SENDGRID_REPLY_TO_EMAIL` | Reply-to address | `helping@easygiveqr.net` |
| `SITE_URL` | Production site URL | `https://easygiveqr.net` |
| `NEXT_PUBLIC_SITE_URL` | Public site URL | `https://easygiveqr.net` |
| `ADMIN_SECRET` | Admin API secret | `your-secret` |
| `CRON_SECRET` | Cron job secret | `your-secret` |

### Optional Variables

| Variable | Description | Default |
|----------|-------------|---------|
| `ALLOW_DONATIONS_WHEN_INACTIVE` | Allow donations when church inactive (dev only) | `false` |

## Troubleshooting

### Build Fails

**Check:**
- All required environment variables are set
- Build logs for specific errors
- Node.js version compatibility
- Package dependencies

### Cron Jobs Not Running

**Check:**
- `vercel.json` is committed to repository
- Cron schedule is correct (UTC time)
- `CRON_SECRET` matches in `vercel.json` and environment variables
- Cron jobs show as "Active" in Vercel Dashboard

### Webhook Not Working

**Check:**
- Webhook URL is correct: `https://easygiveqr.net/api/stripe-webhook`
- `STRIPE_WEBHOOK_SECRET` matches Stripe Dashboard
- Webhook events are selected in Stripe
- Check Vercel function logs for errors

### Environment Variables Not Loading

**Check:**
- Variables are set for correct environment (Production/Preview/Development)
- App has been redeployed after adding variables
- Variable names are correct (case-sensitive)
- No typos in variable values

## Security Checklist

- [ ] All secrets are strong and unique
- [ ] `ADMIN_SECRET` and `CRON_SECRET` are different
- [ ] `CRON_SECRET` in `vercel.json` matches environment variable
- [ ] Repository is private (if `vercel.json` contains secrets)
- [ ] Production keys are used (not test keys)
- [ ] Webhook secret is production secret (not test)
- [ ] Environment variables are set for Production scope only (where appropriate)

## Next Steps

After deployment:
1. Complete domain setup (if using custom domain)
2. Configure Stripe webhook
3. Test all critical paths
4. Monitor first cron job executions
5. Set up monitoring/alerts (optional)

## Support

For issues:
1. Check Vercel function logs
2. Check Stripe webhook logs
3. Verify environment variables
4. Test endpoints manually with curl
5. Review troubleshooting sections in other guides
