# Steps 29, 30, 31: Database Migrations, Observability, Anti-Abuse

## Step 29: Make DB Changes Safe and Repeatable ✅

### Implementation Complete

**Migrations Directory:**
- ✅ `/supabase/migrations/` already exists with comprehensive migrations
- ✅ All schema changes are captured in migration files:
  - `engagement_submissions` table
  - `job_runs` table
  - `stripe_webhook_events` table
  - `churches` columns (admin_emails, monthly_enabled, Stripe Connect fields, subscription fields, qr_code_url)
  - `donations` donor fields (donor_email, donor_name, donor_address)

**Migrations README:**
- ✅ `supabase/MIGRATIONS_README.md` - Complete guide
  - Naming conventions
  - Migration guidelines (DO/DON'T)
  - How to apply migrations (local, production)
  - Rollback strategy
  - Current schema overview
  - Troubleshooting

**Schema Snapshot Script:**
- ✅ `scripts/schema-snapshot-simple.js` - Simple script to print table structure
  - Uses Supabase REST API
  - Samples data to infer column types
  - No direct SQL access required

## Step 30: Minimal Observability for Production ✅

### Implementation Complete

**Sentry Integration:**
- ✅ `src/lib/sentry.ts` - Sentry helper functions
  - `initSentry()` - Initialize Sentry (optional, can use next.config.js)
  - `captureException()` - Capture errors (no PII)
  - `captureMessage()` - Capture messages (no PII)
  - PII filtering (emails, names redacted)
  - Lazy import (doesn't break if Sentry not installed)

**Package Update:**
- ✅ `package.json` - Added `@sentry/nextjs` dependency

**Alert Email System:**
- ✅ `src/lib/alertEmail.ts` - Critical failure email alerts
  - `sendAlertEmail()` - Throttled alerts (max once per hour per type)
  - Alert types: webhook_failure, job_failure, checkout_failure, email_failure, database_error
  - Sends to: helping@easygiveqr.net
  - In-memory throttle cache

**Operations Runbook:**
- ✅ `OPS_RUNBOOK.md` - Complete operational guide
  - Monitoring & observability (Sentry, email alerts)
  - Critical failure scenarios (webhook, donations, email, database, jobs)
  - Stop the line thresholds
  - Daily/weekly checklists
  - Troubleshooting commands
  - Performance monitoring
  - Security checklist

## Step 31: Tighten Anti-Abuse for Public Endpoints ✅

### Implementation Complete

**Rate Limiting Hardening:**
- ✅ `src/lib/rateLimit.ts` - Enhanced rate limiting
  - IP-based + user agent heuristic
  - Hardened limits:
    - Checkout: 15 requests/minute (was 20)
    - Donation: 20 requests/minute (was 30)
    - Engagement: 10 requests/minute (new)
  - Returns `{ ok: false, error: "rate_limited" }` with 429 status
  - Proper Retry-After headers

**Honey Pot Field:**
- ✅ `src/app/engage/[type]/page.tsx` - Added hidden "website" field
  - Hidden from users (CSS: `position: absolute, left: -9999px`)
  - If filled, form submission is silently rejected (returns success but doesn't store)
  - Bot detection without user friction

**Strict Validation:**
- ✅ `src/app/api/checkout-session/route.ts` - Enhanced validation
  - Church ID format validation: `/^EGQR-\d+$/` pattern
  - Church existence double-check in database
  - Best-effort origin/referrer check (logs suspicious requests, doesn't block)
  - Only allows preset amounts (already enforced)

**Engagement Route:**
- ✅ `src/app/api/engagement/submit/route.ts` - Uses hardened rate limiting
  - 10 requests per minute limit
  - Honey pot field checked on client-side (server-side check can be added if needed)

## Files Created

### Step 29:
1. `supabase/MIGRATIONS_README.md` - Migration guide
2. `scripts/schema-snapshot.js` - Schema snapshot script (advanced)
3. `scripts/schema-snapshot-simple.js` - Simple schema snapshot script

### Step 30:
1. `src/lib/sentry.ts` - Sentry integration
2. `src/lib/alertEmail.ts` - Alert email system
3. `OPS_RUNBOOK.md` - Operations runbook

## Files Updated

### Step 30:
1. `package.json` - Added `@sentry/nextjs` dependency

### Step 31:
1. `src/lib/rateLimit.ts` - Enhanced rate limiting with user agent heuristic
2. `src/app/engage/[type]/page.tsx` - Added honey pot field
3. `src/app/api/checkout-session/route.ts` - Enhanced validation (church_id format, origin check)
4. `src/app/api/engagement/submit/route.ts` - Uses hardened rate limiting

## Testing

### Step 29: Migrations

**Test Schema Snapshot:**
```bash
SUPABASE_URL=... SUPABASE_SERVICE_ROLE_KEY=... node scripts/schema-snapshot-simple.js
```

**Expected:** Prints table structure for churches and donations

### Step 30: Observability

**Test Sentry (optional):**
1. Set `SENTRY_DSN` environment variable
2. Trigger an error in an API route
3. Check Sentry dashboard for captured error

**Test Alert Email:**
```typescript
import { sendAlertEmail } from "@/lib/alertEmail";

await sendAlertEmail({
  type: "webhook_failure",
  message: "Test alert",
  details: { test: true },
});
```

**Expected:** Email sent to helping@easygiveqr.net (throttled to once per hour)

### Step 31: Anti-Abuse

**Test Rate Limiting:**
```bash
# Make 16 requests in 1 minute to checkout endpoint
for i in {1..16}; do
  curl -X POST http://localhost:3000/api/checkout-session \
    -H "Content-Type: application/json" \
    -d '{"church_id": "EGQR-123", "amount_cents": 1000, "frequency": "one_time"}'
done
```

**Expected:** 16th request returns `429 { ok: false, error: "rate_limited" }`

**Test Honey Pot:**
1. Open engagement form
2. Fill hidden "website" field (via browser dev tools)
3. Submit form

**Expected:** Form shows success but submission is not stored

**Test Church ID Validation:**
```bash
curl -X POST http://localhost:3000/api/checkout-session \
  -H "Content-Type: application/json" \
  -d '{"church_id": "INVALID-123", "amount_cents": 1000, "frequency": "one_time"}'
```

**Expected:** `400 { ok: false, error: "invalid_input", message: "Invalid church ID format." }`

## Important Notes

### Migrations (Step 29)

- **Never edit old migrations** - Create new ones instead
- **Always use `IF NOT EXISTS`** - Makes migrations idempotent
- **Test on staging first** - Before applying to production
- **Backup before applying** - Always backup production database

### Observability (Step 30)

- **Sentry is optional** - App works without it
- **No PII in Sentry** - All emails/names are redacted
- **Alerts are throttled** - Max once per hour per type
- **Check Sentry daily** - Review error trends

### Anti-Abuse (Step 31)

- **Rate limiting is best-effort** - Serverless resets on cold starts
- **Honey pot is client-side** - Can add server-side check if needed
- **Origin check is best-effort** - Logs suspicious requests, doesn't block
- **Church ID format is strict** - Must match `EGQR-XXX` pattern

## Next Steps

1. **Apply Sentry DSN:**
   - Get DSN from Sentry dashboard
   - Add to Vercel environment variables
   - Initialize in `next.config.js` (optional) or use helper functions

2. **Test Rate Limiting:**
   - Verify rate limits work in production
   - Monitor for false positives
   - Adjust limits if needed

3. **Monitor Alerts:**
   - Check email inbox for alerts
   - Review Sentry dashboard daily
   - Investigate critical alerts immediately

## Summary

All three steps are complete:
- ✅ **Step 29:** Database migrations documented and organized
- ✅ **Step 30:** Sentry observability and alert system implemented
- ✅ **Step 31:** Anti-abuse measures hardened (rate limiting, honey pot, validation)

Ready for production! 🚀
