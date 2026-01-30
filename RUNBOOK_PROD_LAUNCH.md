# Production Launch Runbook

## Launch Information

**Launch Date/Time (Central):** _[TO BE FILLED]_

**Git Commit Hash:** _[TO BE FILLED]_

**Vercel Project Name:** _[TO BE FILLED]_

**Stripe Account (Last 4):** _[TO BE FILLED]_

**Supabase Project Ref:** _[TO BE FILLED]_

**SendGrid Domain:** _[TO BE FILLED]_

**Admin Secret Holder:** _[TO BE FILLED]_

**Cron Secret Holder:** _[TO BE FILLED]_

---

## Pre-Launch Checklist

### 0. Runbook Created ✅
- [x] RUNBOOK_PROD_LAUNCH.md created

### 1. Pull Latest + Lock Dependencies
- [ ] `git checkout main`
- [ ] `git pull`
- [ ] `npm ci`
- [ ] `npm run lint` - Status: ___
- [ ] `npm run typecheck` - Status: ___
- [ ] `npm run test` - Status: ___
- [ ] No "TODO: remove before prod" warnings

### 2. Environment Variable Schema ✅
- [x] Single source of truth: `src/lib/env.ts`
- [x] Runtime validation (throws on missing vars)
- [x] Server vs client vars separated (validates only server-side)
- [x] Required server envs validated:
  - [x] `STRIPE_SECRET_KEY`
  - [x] `STRIPE_WEBHOOK_SECRET`
  - [x] `SUPABASE_URL`
  - [x] `SUPABASE_SERVICE_ROLE_KEY`
  - [x] `SENDGRID_API_KEY`
  - [x] `CRON_SECRET`
  - [x] `ADMIN_SECRET`
  - [x] `DONATIONS_PAUSED` (optional, defaults to false)
  - [x] `NODE_ENV`
- [x] Required public envs:
  - [x] `NEXT_PUBLIC_SITE_URL` = `https://easygiveqr.net`
- [x] Server crashes on boot if required envs missing (production only)
- [ ] `npm run dev` fails fast if env missing - Tested: ___

### 3. Production Domain + App URL Correctness ✅
- [x] No hardcoded preview URLs
- [x] No accidental localhost in prod paths (enforced by `getSiteUrl()`)
- [x] All absolute URLs use `NEXT_PUBLIC_SITE_URL` or `SITE_URL`
- [x] Stripe success/cancel URLs use production domain
- [x] Email links use production domain
- [x] Webhook callbacks use production domain

**Files Checked:**
- [x] `src/lib/siteUrl.ts` - Enforces production URLs, throws if missing
- [x] `src/app/api/checkout-session/route.ts` - Uses `getSiteUrl()`
- [x] `src/lib/onboardingHelpers.ts` - Uses `getDonationUrl()` from `siteUrl.ts`
- [x] `src/app/api/qr/generate/route.ts` - Uses `getDonationUrl()`

### 4. Stripe Live Mode Checks ✅
- [x] Checkout session creation uses `STRIPE_SECRET_KEY`
- [x] One-time donations: `mode: "payment"`
- [x] Monthly donations: `mode: "subscription"`
- [x] Success/cancel URLs use `NEXT_PUBLIC_SITE_URL` (via `getSiteUrl()`)
- [x] Webhook handler uses raw body (`req.text()`)
- [x] Webhook signature verification with `STRIPE_WEBHOOK_SECRET`
- [x] Webhook events logged to `stripe_webhook_events` table (before processing)
- [x] Idempotency: duplicate events don't create duplicate donations
  - [x] Checks `event_id` before insert
  - [x] Uses `upsert` with `onConflict: "stripe_session_id"`
  - [x] UNIQUE constraint on `donations.stripe_session_id`

**Files Checked:**
- [x] `src/app/api/checkout-session/route.ts` - ✅ Verified
- [x] `src/app/api/stripe-webhook/route.ts` - ✅ Verified

### 5. Supabase Production Safety ✅
- [x] `SUPABASE_SERVICE_ROLE_KEY` only in server-only code
- [x] No service role key in client components
- [x] Public donation pages don't allow direct writes (donations only created via webhook)
- [x] All donation writes come from webhook with service role

**Files Checked:**
- [x] `src/lib/supabaseAdmin.ts` - ✅ Server-only, uses service role
- [x] `src/app/donate/page.tsx` - ✅ Client component, uses public API routes only

### 6. Database Constraints ✅
- [x] `stripe_webhook_events.event_id` UNIQUE constraint exists
- [x] `donations.stripe_session_id` UNIQUE constraint exists (migration: `20260128_ensure_donations_unique_constraints.sql`)
- [x] `donations.church_id` FK to `churches.church_id` (migration: `20260128_ensure_donations_unique_constraints.sql`)
- [x] `engagement_submissions.church_id` FK to `churches.church_id`
- [x] `churches.status` CHECK constraint (pending, active, paused, closed)

**Migrations Checked:**
- [x] `20260127_create_stripe_webhook_events.sql` - ✅ `event_id` UNIQUE
- [x] `20260128_ensure_donations_unique_constraints.sql` - ✅ `stripe_session_id` UNIQUE + FK
- [x] `20260128_add_status_constraint_to_churches.sql` - ✅ Status CHECK constraint

### 7. SendGrid Production Setup ✅
- [x] Central email wrapper: `src/lib/email/sendEmail.ts`
- [x] `from` always `helping@easygiveqr.net` (enforced, throws if missing)
- [x] No dynamic reply-from-church-domain behavior
- [x] Templates are static EN/ES
- [x] Email failures don't block donation writes (webhook continues)
- [x] Weekly summary failures logged to `job_runs`

**Files Checked:**
- [x] `src/lib/email/sendEmail.ts` - ✅ Enforces sender, multi-recipient support
- [x] `src/app/api/jobs/weekly-summary/route.ts` - ✅ Logs to job_runs
- [x] `src/app/api/stripe-webhook/route.ts` - ✅ Email failures don't block

### 8. Cron Routes: Locked + Safe ✅
- [x] Each cron route checks `x-cron-secret` header OR `?cron=...` query param
- [x] Returns 401 if wrong
- [x] Uses service role only
- [x] Writes to `job_runs` table

**Files Checked:**
- [x] `src/app/api/jobs/weekly-summary/route.ts` - ✅ Uses `requireCronSecret()`
- [x] `src/app/api/jobs/wednesday-payouts/route.ts` - ✅ Uses `requireCronSecret()`
- [x] `src/app/api/jobs/annual-receipts/route.ts` - ✅ Uses `requireCronSecret()`
- [x] `src/lib/requireAdmin.ts` - ✅ Supports header + query param

### 9. Admin Routes Protection ✅
- [x] Every admin endpoint requires `x-admin-secret` header
- [x] No admin UI routes exposed without protection
- [x] Unauthenticated calls get blocked (401)

**Files Checked:**
- [x] All `/api/admin/*` routes - ✅ Use `requireAdminSecret()`
- [x] `src/lib/requireAdmin.ts` - ✅ Validates header

### 10. Global Kill Switch + Per-Church Pause ✅
- [x] Global kill switch: `DONATIONS_PAUSED` env var
- [x] Blocks checkout creation (returns 503)
- [x] Blocks webhook processing (logs but doesn't create donation)
- [x] Per-church pause: `churches.donations_paused` column (migration: `20260128_add_donations_paused_to_churches.sql`)
- [x] Donation page checks both flags
- [x] Returns clean "Donations currently paused" message (EN/ES)

**Files Checked:**
- [x] `src/app/api/checkout-session/route.ts` - ✅ Checks global kill switch + per-church pause
- [x] `src/app/donate/page.tsx` - ✅ Checks per-church pause, shows pause message
- [x] `src/lib/churchEligibility.ts` - ✅ Checks both flags
- [x] `src/app/api/stripe-webhook/route.ts` - ✅ Checks global kill switch

### 11. Vercel Production Settings ✅
- [x] `vercel.json` doesn't block raw webhook body (no body parsing config)
- [x] Webhook runs on Node runtime (not edge) - `export const runtime = "nodejs"`
- [x] Cron jobs configured in `vercel.json`

**Files Checked:**
- [x] `vercel.json` - ✅ Cron jobs configured with query param auth
- [x] `src/app/api/stripe-webhook/route.ts` - ✅ `runtime = "nodejs"`

### 12. Production Smoke Tests

#### 12.1 Local "Prod-Like" Run
- [ ] `npm run build` - Status: ___
- [ ] `npm run start` - Status: ___
- [ ] Checkout session creation returns 200 for valid church

#### 12.2 After Production Deploy
- [ ] Test: `https://easygiveqr.net/donate?church_id=EGQR-TEST`
- [ ] Choose preset amount
- [ ] If kill switch OFF and church active, proceeds
- [ ] No console errors
- [ ] Language matches church preference

---

## Post-Launch Verification

### Stripe Webhook
- [ ] Screenshot: Stripe webhook event received in Stripe dashboard
- [ ] Screenshot: Supabase `stripe_webhook_events` row created
- [ ] Screenshot: Supabase `donations` row created

### SendGrid
- [ ] Screenshot: SendGrid "delivered" logs for weekly summary test
- [ ] Test email sent successfully

### Database
- [ ] All migrations applied
- [ ] Constraints verified
- [ ] Test donation recorded correctly

---

## Known Issues + Mitigation

_[TO BE FILLED]_

---

## Execution Order

1. ✅ Create RUNBOOK_PROD_LAUNCH.md
2. ✅ Create ops/ folder structure
3. ✅ Create smoke test script
4. ✅ Create .env.production.example
5. ✅ Create admin health endpoint
6. ✅ Fix localhost fallbacks
7. [ ] Run tests/lint/typecheck
8. [ ] Verify env schema + fail-fast
9. [ ] Verify base URL correctness (✅ Done)
10. [ ] Verify Stripe checkout + webhook strictness (✅ Done)
11. [ ] Verify DB constraints/migrations (✅ Done)
12. [ ] Verify SendGrid wrapper + sender lock (✅ Done)
13. [ ] Verify cron auth + job_runs logging (✅ Done)
14. [ ] Verify admin secret enforcement (✅ Done)
15. [ ] Verify kill switch + per-church pause (✅ Done)
16. [ ] Build/start smoke test
17. [ ] Push → Vercel deploy → prod smoke
18. [ ] Fill runbook with proof

---

## Notes

- **Brutal Note:** If you skip DB uniqueness constraints or webhook strict verification, you're not "launching," you're gambling. Those two prevent silent financial/reporting disasters.

---

**Last Updated:** _[TO BE FILLED]_
