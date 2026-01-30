# Phase 1 Launch Runbook (Authoritative Order)

**Launch discipline:** Follow A→F in order. No `npm audit fix --force`, no feature tweaks, no refactors.

---

## A) Apply Supabase migrations (PROD)

**Do not assume migrations exist—confirm in PROD schema.**

### 1. Run migrations in Supabase PROD

- Open **Supabase Dashboard** → your **production** project → **SQL Editor**.
- Run these migrations in order (if not already applied):
  - `supabase/migrations/20260127_create_stripe_webhook_events.sql`
  - `supabase/migrations/20260128_ensure_donations_unique_constraints.sql`

### 2. Verify constraints in PROD

Run this in **Supabase PROD** → SQL Editor:

```sql
SELECT constraint_name, constraint_type, table_name
FROM information_schema.table_constraints
WHERE table_name IN ('donations', 'stripe_webhook_events')
AND constraint_type = 'UNIQUE';
```

**Required result:**

- `donations`: **`donations_stripe_session_id_key`** (or equivalent) on column **`stripe_session_id`** → UNIQUE.
- `stripe_webhook_events`: **`stripe_webhook_events_event_id_key`** (or equivalent) on column **`event_id`** → UNIQUE.

If either UNIQUE is missing, apply/fix the migration in PROD before proceeding.

**Pass:** Both tables have the UNIQUE constraints above. Screenshot or copy the query result.

---

## B) Set Vercel Production env vars

**Reference:** `.env.production.example`

**Scope:** Vercel → Project → **Settings** → **Environment Variables** → **Production** (not Preview).

### Critical (must set)

| Variable | Value | Notes |
|----------|--------|--------|
| `NEXT_PUBLIC_SITE_URL` | `https://easygiveqr.net` | NOT localhost, NOT vercel.app. (If app uses `NEXT_PUBLIC_APP_URL`, set that too to same value.) |
| `SITE_URL` | `https://easygiveqr.net` | |
| `STRIPE_SECRET_KEY` | **LIVE** key | Must start with `sk_live_` (not `sk_test_`) |
| `STRIPE_WEBHOOK_SECRET` | **LIVE** webhook signing secret | From Stripe LIVE webhook endpoint (step D). Set after creating endpoint; starts with `whsec_` |
| `SUPABASE_URL` | Production Supabase project URL | |
| `SUPABASE_SERVICE_ROLE_KEY` | Production Supabase service role key | |
| `SENDGRID_API_KEY` | Production SendGrid API key | |
| `SENDGRID_FROM_EMAIL` | `helping@easygiveqr.net` | |
| `SENDGRID_REPLY_TO_EMAIL` | `helping@easygiveqr.net` | |
| `ADMIN_SECRET` | Strong random secret | (or `X_ADMIN_SECRET` if app expects that) |
| `CRON_SECRET` | Strong random secret | |
| `DONATIONS_PAUSED` | `false` or leave unset | Kill switch **OFF** |

Optional but recommended: `STRIPE_PUBLISHABLE_KEY` (LIVE), `NODE_ENV=production`, `SENTRY_DSN`, `ALLOW_DONATIONS_WHEN_INACTIVE=false`.

### After setting env vars

- **Redeploy.** Vercel does not apply new env vars to existing deployments.
- Confirm all above are set for **Production** environment.

**Pass:** All critical vars set; redeploy triggered.

---

## C) Deploy to production

- Deploy the **main** branch (e.g. Vercel → Deployments → deploy latest from `main`, or push to `main` to trigger deploy).
- Confirm **easygiveqr.net** is bound to this deployment (Vercel → Domains).

**Pass check:**

- Open: **https://easygiveqr.net/donate?church_id=EGQR-TEST**
- Must load with **200 OK** (donation page renders).

**Pass:** Donate URL loads. Note deployment URL and timestamp if needed.

---

## D) Configure Stripe LIVE webhook destination

**Stripe Dashboard:** Switch to **LIVE** mode (not Test).

1. **Developers** → **Webhooks** → **Add endpoint**.
2. **Endpoint URL:** `https://easygiveqr.net/api/stripe-webhook`
3. **Events to send:** at minimum **`checkout.session.completed`**.
4. Create endpoint; copy the **Signing secret** (`whsec_...`).
5. In **Vercel** → Production env vars, set **`STRIPE_WEBHOOK_SECRET`** to this LIVE secret (overwrite if it was placeholder).
6. **Redeploy** so the new secret is used.
7. In Stripe, use **Send test webhook** (or trigger a real test) and confirm:
   - Stripe shows **200 OK** for the delivery.
   - In Supabase PROD, table **`stripe_webhook_events`** has a new row for the event.

**Pass:** Stripe shows 200 OK; row(s) appear in `stripe_webhook_events`.

---

## E) Verify SendGrid

- **Sender:** `helping@easygiveqr.net` (verified in SendGrid).
- **Domain:** `easygiveqr.net` verified if required by SendGrid.
- **Test:** Send a real email in production (e.g. use `/api/admin/email-test` or your normal flow).
- **Confirm:** Email delivered to inbox (not spam), sender shows as `helping@easygiveqr.net`.

**Pass:** SendGrid sender/domain verified; test email delivered.

---

## F) Run production smoke test

From project root (Node 18+):

```bash
node ops/smoke/smoke-prod.ts EGQR-TEST
```

**Expected:** All checks pass (health, donate page, webhook rejects GET, church API). Exit code 0.

If any check fails, fix the failing item (env, deployment, or PROD data) and re-run. Do not change smoke script behavior for launch.

**Pass:** `All smoke checks passed`; exit code 0.

---

## After A–F pass

- Commit and push any runbook/checklist updates if desired.
- Proceed to Phase 1 steps (pilot church, cron, E2E donation test) per `ops/PHASE1_CHECKLIST.md`.

---

## DO NOT (launch discipline)

- `npm audit fix --force`
- Feature tweaks
- Refactors
- “Just one more improvement”

You are in launch discipline mode.
