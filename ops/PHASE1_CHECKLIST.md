# Phase 1 Launch Checklist

**Authoritative order (A→F):** See **`ops/PHASE1_LAUNCH_RUNBOOK.md`** for the exact launch sequence. Do not assume migrations are applied—confirm UNIQUE constraints in Supabase PROD.

## Pre-Deploy (Local)

- [ ] `git checkout main && git pull` - Latest code
- [ ] **Install dependencies:** `npm install --legacy-peer-deps` (updates lock file)
  - **Note:** `--legacy-peer-deps` needed due to Sentry/Next.js 16 compatibility
  - See `ops/CRITICAL_BUILD_FIXES.md` for details
- [ ] `npm run lint` - No lint errors (warnings acceptable)
- [ ] `npm run typecheck` - No type errors
- [ ] `npm run build` - Build succeeds (no runtime warnings)
- [ ] `npm test` - Tests pass (if available)
- [ ] Verify webhook route uses `runtime = "nodejs"` (not edge)

## Database Migrations (CRITICAL - DO NOT SKIP)

- [ ] Migration applied: `20260128_ensure_donations_unique_constraints.sql`
  - [ ] `donations.stripe_session_id` UNIQUE constraint exists
  - [ ] `donations.church_id` FOREIGN KEY constraint exists
- [ ] Migration applied: `20260127_create_stripe_webhook_events.sql` (or equivalent)
  - [ ] `stripe_webhook_events.event_id` UNIQUE constraint exists
- [ ] **Proof:** Run SQL query to verify constraints:
  ```sql
  SELECT constraint_name, constraint_type
  FROM information_schema.table_constraints
  WHERE table_name IN ('donations', 'stripe_webhook_events')
  AND constraint_type = 'UNIQUE';
  ```
- [ ] **Why this matters:** Code idempotency is not enough. Webhooks get retried. Without DB uniqueness you will eventually duplicate donations.

## Vercel Environment Variables (Production)

**Use `.env.production.example` as reference**

### Absolutely Required:
- [ ] `NEXT_PUBLIC_SITE_URL=https://easygiveqr.net` (NOT localhost, NOT vercel.app)
- [ ] `STRIPE_SECRET_KEY` = **LIVE** key (starts with `sk_live_`)
- [ ] `STRIPE_WEBHOOK_SECRET` = **LIVE** webhook signing secret (starts with `whsec_`)
- [ ] `SUPABASE_URL` = Production Supabase project URL
- [ ] `SUPABASE_SERVICE_ROLE_KEY` = Production service role key
- [ ] `SENDGRID_API_KEY` = Production SendGrid API key
- [ ] `CRON_SECRET` = Strong random secret
- [ ] `ADMIN_SECRET` = Strong random secret (or `X_ADMIN_SECRET`)
- [ ] `DONATIONS_PAUSED=false` (or unset) - Kill switch OFF

### Common Gotchas:
- [ ] ⚠️ **NOT using test Stripe keys** (verify `sk_live_` not `sk_test_`)
- [ ] ⚠️ **Webhook secret from LIVE endpoint** (not test endpoint)

### Pass Criteria:
- [ ] All vars set in Vercel → **Production Environment** (not Preview)
- [ ] **Redeploy after setting them** (Vercel won't apply them to existing build)

## Deploy to Production

- [ ] Deploy `main` branch to Vercel
- [ ] Confirm `easygiveqr.net` domain is bound to production deployment
- [ ] Git commit hash deployed: `________________`
- [ ] Vercel deployment URL: `________________`
- [ ] Deployment timestamp: `________________`

### Pass Criteria:
- [ ] `https://easygiveqr.net/donate?church_id=EGQR-TEST` loads (200 OK)

## Post-Deploy Verification

### Stripe LIVE Webhook Destination (CRITICAL)

**In Stripe Dashboard (LIVE mode, not test):**

- [ ] Add endpoint: `https://easygiveqr.net/api/stripe-webhook`
- [ ] Select required events (minimum):
  - [ ] `checkout.session.completed`
  - [ ] `payment_intent.succeeded` (if used)
  - [ ] `customer.subscription.*` (if using subscriptions)
- [ ] Copy webhook signing secret (starts with `whsec_`)
- [ ] Set `STRIPE_WEBHOOK_SECRET` in Vercel (LIVE secret, not test)
- [ ] Test webhook event sent from Stripe Dashboard (LIVE mode)
- [ ] Stripe Dashboard shows **200 OK** deliveries
- [ ] Webhook event received and logged in `stripe_webhook_events` table
- [ ] Donation row created in `donations` table (if applicable)

### Pass Criteria:
- [ ] Stripe Dashboard shows webhook endpoint with **200 OK** status
- [ ] `stripe_webhook_events` table has new row for test event
- [ ] Screenshot: Stripe webhook delivery = 200 ✅

### SendGrid Sender Verification

- [ ] Domain verified for `easygiveqr.net` (if required)
- [ ] Sender verified: `helping@easygiveqr.net`
- [ ] Test email sent in production (use `/api/admin/email-test`)
- [ ] Email delivered (not spam)
- [ ] Correct EN/ES template used
- [ ] Sender is exactly `helping@easygiveqr.net` (not from different domain)

### Pass Criteria:
- [ ] SendGrid Dashboard shows verified sender/domain
- [ ] Test email delivered successfully
- [ ] Screenshot: SendGrid delivered event ✅

### Cron Jobs
- [ ] Cron jobs configured in Vercel Dashboard
- [ ] `CRON_SECRET` set in Vercel env vars
- [ ] Cron schedule verified:
  - Weekly summary: Wednesday 8:00 AM CT (0 14 * * 3 UTC)
  - Wednesday payouts: Wednesday 8:00 AM CT (0 14 * * 3 UTC)
  - Annual receipts: January 15, 8:00 AM CT (0 14 15 1 * UTC)

### Pilot Church
- [ ] Test church created: `EGQR-TEST` (or actual pilot church ID)
- [ ] Stripe Connect onboarding completed
- [ ] Subscription active
- [ ] Status set to `active`
- [ ] Donations not paused
- [ ] QR code generated
- [ ] Smoke test passed: `node ops/smoke/smoke-prod.ts EGQR-TEST`

### End-to-End Test
- [ ] Donation page loads: `https://easygiveqr.net/donate?church_id=EGQR-TEST`
- [ ] Test donation ($5 one-time) completed
- [ ] Stripe Checkout session created successfully
- [ ] Payment processed in Stripe
- [ ] Webhook received and processed
- [ ] Donation row created in Supabase
- [ ] Success page shows "Donation Verified"

### Smoke Test (Production)

- [ ] Run: `node ops/smoke/smoke-prod.ts EGQR-TEST`
- [ ] All checks pass:
  - [ ] Health endpoint: `GET /api/health` returns `{ ok: true, version: "1.0.0" }`
  - [ ] Donation page: `GET /donate?church_id=EGQR-TEST` returns 200
  - [ ] Webhook endpoint: `GET /api/stripe-webhook` rejects GET with 400/405 (expected)
  - [ ] Church API: `GET /api/church?church_id=EGQR-TEST` returns 200
- [ ] Admin smoke test: `POST /api/admin/smoke/run` returns all checks PASS
- [ ] No console errors in browser
- [ ] No server errors in Vercel logs

### Pass Criteria:
- [ ] All smoke test checks pass ✅
- [ ] Health endpoint accessible (critical for ops visibility)

## Proof Documentation (What "Ready" Actually Means)

Capture evidence of successful setup:

- [ ] **Git commit hash deployed:** `________________`
- [ ] **Vercel deployment URL:** `________________`
- [ ] **Deployment timestamp:** `________________`
- [ ] **Screenshot:** Stripe webhook delivery = 200 OK
- [ ] **Screenshot/Query:** Database uniqueness constraints exist
  ```sql
  -- Proof query
  SELECT constraint_name, constraint_type
  FROM information_schema.table_constraints
  WHERE table_name IN ('donations', 'stripe_webhook_events')
  AND constraint_type = 'UNIQUE';
  ```
- [ ] **Screenshot:** SendGrid delivered event
- [ ] **Screenshot:** Health endpoint response (`/api/health`)
- [ ] **Screenshot:** Smoke test results (all PASS)

## Known Issues

_[TO BE FILLED]_

---

**Launch Date/Time (Central):** _[TO BE FILLED]_

**Deployed By:** _[TO BE FILLED]_

**Stripe Account (Last 4):** _[TO BE FILLED]_

**Supabase Project:** _[TO BE FILLED]_

**SendGrid Domain:** _[TO BE FILLED]_
