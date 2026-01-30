# Validation Commands

## After Installing Dependencies

Run these commands in order to validate the build:

```powershell
# 1. Install dependencies (updates package-lock.json)
npm install --legacy-peer-deps

# 2. Lint check
npm run lint

# 3. Type check
npm run typecheck

# 4. Build
npm run build
```

## Expected Results

### ✅ Success Criteria:
- `npm run lint` - May show warnings (acceptable), but no errors
- `npm run typecheck` - **Zero errors** (critical)
- `npm run build` - Build completes successfully

### ❌ If Build Fails:

1. **Type errors:** Check `ops/CRITICAL_BUILD_FIXES.md` - all fixes should be applied
2. **Module not found:** Run `npm install --legacy-peer-deps` again
3. **Sentry errors:** Check `ops/DEPENDENCY_FIX.md` for alternatives

## After Validation Passes

Proceed with:
1. Database migrations (see `ops/DATABASE_MIGRATIONS.md`)
2. Vercel env vars setup
3. Production deployment
4. Smoke testing

---

**Last Updated:** 2026-01-28
