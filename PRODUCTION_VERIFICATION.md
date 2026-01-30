# Production Verification Checklist

## Critical Pre-Launch Checks

### ✅ 1. Environment Variables
- [x] `src/lib/env.ts` validates all required env vars
- [x] Server fails fast in production if env vars missing
- [x] Required vars: `STRIPE_SECRET_KEY`, `STRIPE_WEBHOOK_SECRET`, `SUPABASE_URL`, `SUPABASE_SERVICE_ROLE_KEY`, `SENDGRID_API_KEY`, `SENDGRID_FROM_EMAIL`, `ADMIN_SECRET`, `CRON_SECRET`, `NEXT_PUBLIC_SITE_URL`, `NODE_ENV`
- [x] Global kill switch: `DONATIONS_PAUSED` (optional, defaults to false)

### ✅ 2. Base URL Correctness
- [x] `src/lib/siteUrl.ts` enforces production URLs
- [x] All Stripe success/cancel URLs use `NEXT_PUBLIC_SITE_URL`
- [x] All email links use production domain
- [x] QR code generation uses production domain
- [x] No hardcoded localhost in production code paths

### ✅ 3. Stripe Webhook Idempotency
- [x] Webhook uses raw body for signature verification
- [x] `stripe.webhooks.constructEvent()` with `STRIPE_WEBHOOK_SECRET`
- [x] Events logged to `stripe_webhook_events` table before processing
- [x] Duplicate event detection (checks `event_id` before insert)
- [x] Donations table has UNIQUE constraint on `stripe_session_id`
- [x] Webhook uses `upsert` with `onConflict: "stripe_session_id"`
- [x] Webhook stores Stripe IDs: `stripe_payment_intent_id`, `stripe_charge_id`, `stripe_transfer_id`

### ✅ 4. Database Constraints
- [x] `stripe_webhook_events.event_id` UNIQUE
- [x] `donations.stripe_session_id` UNIQUE (migration: `20260128_ensure_donations_unique_constraints.sql`)
- [x] `donations.church_id` FK to `churches.church_id`
- [x] `engagement_submissions.church_id` FK to `churches.church_id`
- [x] `churches.status` CHECK constraint (pending, active, paused, closed)

### ✅ 5. SendGrid Configuration
- [x] Central wrapper: `src/lib/email/sendEmail.ts`
- [x] `from` always `helping@easygiveqr.net` (enforced)
- [x] Email failures don't block donation writes
- [x] Weekly summary failures logged to `job_runs`

### ✅ 6. Cron Route Security
- [x] All cron routes use `requireCronSecret()`
- [x] Supports `x-cron-secret` header OR `?cron=...` query param
- [x] Returns 401 if wrong
- [x] Uses service role only
- [x] Writes to `job_runs` table

### ✅ 7. Admin Route Protection
- [x] All `/api/admin/*` routes use `requireAdminSecret()`
- [x] Returns 401 if `x-admin-secret` header missing/wrong

### ✅ 8. Kill Switches
- [x] Global kill switch: `DONATIONS_PAUSED` env var
- [x] Per-church pause: `churches.donations_paused` column
- [x] Checkout session checks both flags
- [x] Donate page checks both flags
- [x] Webhook checks global kill switch (logs but doesn't process)
- [x] Pause messages in EN/ES

### ✅ 9. Church Eligibility
- [x] `src/lib/churchEligibility.ts` checks:
  - Global kill switch
  - Per-church pause
  - Church status (active only)
  - Subscription status (active/trialing)
  - Stripe Connect (charges_enabled + payouts_enabled)

### ✅ 10. Vercel Configuration
- [x] `vercel.json` configured for cron jobs
- [x] Webhook route uses `runtime = "nodejs"` (not edge)
- [x] Cron jobs use query param authentication

## Post-Deploy Verification

### Stripe
- [ ] Webhook endpoint: `https://easygiveqr.net/api/stripe-webhook`
- [ ] Webhook secret configured in Stripe Dashboard
- [ ] Test webhook event received and processed
- [ ] Donation row created in Supabase

### SendGrid
- [ ] Sender verified: `helping@easygiveqr.net`
- [ ] Test email sent successfully
- [ ] Weekly summary email test sent

### Database
- [ ] All migrations applied
- [ ] Unique constraints verified
- [ ] Foreign keys verified

### Smoke Test
- [ ] `POST /api/admin/smoke/run` returns all checks PASS
- [ ] Test donation flow works
- [ ] Test engagement form works

---

**Last Verified:** _[TO BE FILLED]_
