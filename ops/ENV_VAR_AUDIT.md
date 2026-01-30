# Environment Variable Usage Audit

## Production-Critical Env Vars

### ✅ Verified Safe Usage

**STRIPE_SECRET_KEY:**
- ✅ Only used in server-only code paths
- ✅ All usages check for existence before use
- ✅ Never exposed to client

**STRIPE_WEBHOOK_SECRET:**
- ✅ Only used in webhook route (server-only)
- ✅ Used for signature verification
- ✅ Never exposed to client

**SUPABASE_SERVICE_ROLE_KEY:**
- ✅ Only used in `src/lib/supabaseAdmin.ts` (server-only)
- ✅ All API routes use service role correctly
- ✅ Never in client components

**SENDGRID_API_KEY:**
- ✅ Only used in `src/lib/email/sendEmail.ts` (server-only)
- ✅ Never exposed to client

**CRON_SECRET:**
- ✅ Only used in `src/lib/requireAdmin.ts` (server-only)
- ✅ Used for cron route authentication
- ✅ Never exposed to client

**ADMIN_SECRET:**
- ✅ Only used in `src/lib/requireAdmin.ts` (server-only)
- ✅ Used for admin route authentication
- ✅ Never exposed to client

**NEXT_PUBLIC_SITE_URL:**
- ✅ Used for client-side URL generation
- ✅ Safe to expose (public domain)
- ✅ All usages verified to use env var (no hardcoded URLs)

## URL Hardcoding Audit

### ✅ Fixed Localhost Fallbacks

**Files Updated:**
- ✅ `src/app/api/onboarding/create-church/route.ts` - Now uses `getSiteUrl()`
- ✅ `src/app/api/billing/create-subscription-checkout/route.ts` - Now uses `getSiteUrl()`
- ✅ `src/app/api/qr/route.ts` - Now uses `getDonationUrl()` from `siteUrl.ts`

**Remaining Localhost References (Safe):**
- `src/lib/siteUrl.ts` - Final fallback for development only (never used in production)
- `src/app/api/checkout-session/route.ts` - Fallback for request origin (development only)

### ✅ No Hardcoded Production URLs Found

All production URLs use:
- `process.env.NEXT_PUBLIC_SITE_URL`
- `process.env.SITE_URL`
- `getSiteUrl()` helper (enforces production URLs)

## Verification

Run these searches to verify:
```bash
# Should return no results (or only safe development fallbacks)
grep -r "localhost" src/ --exclude-dir=node_modules
grep -r "vercel.app" src/ --exclude-dir=node_modules
grep -r "http://" src/app/api --exclude-dir=node_modules
```

---

**Last Audited:** _[TO BE FILLED]_
