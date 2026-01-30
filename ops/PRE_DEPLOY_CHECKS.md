# Pre-Deploy Checks

## Run These Commands Locally

```powershell
# PowerShell syntax (use semicolon, not &&)
cd "C:\Users\The Yoda Trader\easygiveqr-web"
git checkout main
git pull
npm ci
npm run lint
npm run typecheck
npm run build
```

## Pass Criteria

### 1. Git Checkout & Pull
- ✅ On `main` branch
- ✅ Latest code pulled

### 2. npm ci
- ✅ Clean install completes
- ✅ No dependency conflicts

### 3. npm run lint
- ✅ No lint errors
- ✅ No lint warnings that imply runtime failure

### 4. npm run typecheck
- ✅ No TypeScript errors
- ✅ All types resolve correctly

### 5. npm run build
- ✅ Build succeeds
- ✅ No build warnings that imply runtime failure
- ✅ No "edge runtime" surprises on webhook routes
  - Verify: `src/app/api/stripe-webhook/route.ts` has `export const runtime = "nodejs";`

## Common Issues

### Build Fails
- Check for missing environment variables (should fail fast in production)
- Verify all imports resolve
- Check for TypeScript errors

### Edge Runtime Warning
- Webhook routes MUST use `runtime = "nodejs"` (not edge)
- Edge runtime cannot access raw request body needed for Stripe signature verification

### Lint Errors
- Fix all errors before deploying
- Some warnings may be acceptable, but errors must be fixed

---

**Last Checked:** _[TO BE FILLED]_
