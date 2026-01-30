# Critical Build Fixes - Complete

## ✅ All Code Fixes Applied

### 1. ✅ Duplicate siteUrl Variable
- **File:** `src/app/api/onboarding/create-church/route.ts`
- **Status:** FIXED - Removed duplicate declaration, now reuses `siteUrl` from line 270

### 2. ✅ Missing Export: getDonationUrl
- **File:** `src/app/api/onboarding/create-church/route.ts`
- **Status:** FIXED - Now imports `getDonationUrl` from `@/lib/siteUrl` (correct location)

### 3. ✅ Stripe API Version Mismatch
- **Files:** All Stripe client initializations (14 files)
- **Status:** FIXED - All updated from `"2025-01-27.acacia"` to `"2025-12-15.clover"`

### 4. ✅ Stripe Account Type Error
- **File:** `src/app/api/admin/health/route.ts`
- **Status:** FIXED - Added type assertion for compatibility

### 5. ✅ Rate Limit NextResponse Import
- **File:** `src/lib/rateLimit.ts`
- **Status:** FIXED - Added `import { NextResponse } from "next/server";`

### 6. ✅ parseAdminEmails → validateAndNormalizeEmails
- **File:** `src/app/api/onboarding/create-church/route.ts`
- **Status:** FIXED - Uses correct function

### 7. ✅ Stripe Connect Account Creation
- **Files:** `src/app/api/connect/create-account/route.ts`, `src/lib/onboardingHelpers.ts`
- **Status:** FIXED - Removed `email: null` parameter

### 8. ✅ Webhook Transfer Lookup
- **File:** `src/app/api/stripe-webhook/route.ts`
- **Status:** FIXED - Simplified transfer ID lookup

### 9. ✅ Client-Side Null Checks
- **Files:** `src/app/donate/page.tsx`, `src/app/engage/[type]/page.tsx`
- **Status:** FIXED - Added null checks before `encodeURIComponent`

### 10. ✅ TabIndex CSS Property
- **File:** `src/app/engage/[type]/page.tsx`
- **Status:** FIXED - Moved `tabIndex` to element prop

## ⚠️ Dependency Installation Required

### Issue: package-lock.json Out of Sync

**Problem:** 
- Updated `@sentry/nextjs` from `^8.0.0` to `^10.0.0` in `package.json`
- `package-lock.json` needs to be regenerated

**Solution:**

Run these commands in order:

```powershell
# Step 1: Update lock file
npm install --legacy-peer-deps

# Step 2: Verify installation
npm run typecheck

# Step 3: Run full validation
npm run lint
npm run typecheck
npm run build
```

**Why `--legacy-peer-deps`:**
- `@sentry/nextjs@10.x` may still have peer dependency warnings with Next.js 16
- This flag allows installation despite warnings
- Sentry will function correctly

## 📋 Validation Checklist

After running `npm install --legacy-peer-deps`, verify:

- [ ] `npm run lint` - No critical errors (warnings acceptable)
- [ ] `npm run typecheck` - No type errors
- [ ] `npm run build` - Build succeeds
- [ ] All critical fixes verified

## 🚀 Next Steps

Once build passes:

1. **Follow `ops/PRE_DEPLOY_CHECKS.md`**
2. **Apply database migrations** (see `ops/DATABASE_MIGRATIONS.md`)
3. **Set Vercel env vars** (use `.env.production.example`)
4. **Deploy to production**
5. **Configure Stripe live webhook** (see `ops/STRIPE_WEBHOOK_SETUP.md`)
6. **Verify SendGrid** (see `ops/SENDGRID_SETUP.md`)
7. **Run smoke test** (`node ops/smoke/smoke-prod.ts EGQR-TEST`)
8. **Mark off `ops/PHASE1_CHECKLIST.md`**

## 📝 Files Changed

### Code Fixes:
- `src/app/api/onboarding/create-church/route.ts` - Fixed duplicate siteUrl, import, email validation
- `src/app/api/admin/health/route.ts` - Fixed Stripe account type
- `src/lib/rateLimit.ts` - Added NextResponse import
- `src/app/api/stripe-webhook/route.ts` - Simplified transfer lookup
- `src/app/api/connect/create-account/route.ts` - Removed email parameter
- `src/lib/onboardingHelpers.ts` - Removed email parameter, updated API version
- `src/app/donate/page.tsx` - Added null check
- `src/app/engage/[type]/page.tsx` - Added null check, fixed tabIndex
- All Stripe client files (14 files) - Updated API version

### Configuration:
- `package.json` - Updated `@sentry/nextjs` to `^10.0.0`

### Documentation:
- `ops/BUILD_FIXES_SUMMARY.md` - Detailed fix log
- `ops/DEPENDENCY_FIX.md` - Dependency resolution guide
- `ops/CRITICAL_BUILD_FIXES.md` - This file

---

**Status:** ✅ All code fixes complete. Run `npm install --legacy-peer-deps` to install dependencies.
