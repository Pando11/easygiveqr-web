# Dependency Fix Instructions

## Issue: Sentry Peer Dependency Conflict

**Problem:**
- `@sentry/nextjs@8.55.0` requires Next.js `^13.2.0 || ^14.0 || ^15.0.0-rc.0`
- Project uses Next.js `16.1.4`
- This causes `npm ci` to fail

## Solutions

### Option 1: Use Legacy Peer Deps (Recommended for Launch)

Run:
```powershell
npm ci --legacy-peer-deps
```

This allows npm to install despite peer dependency warnings. Sentry will still work, but you may see warnings.

### Option 2: Update Sentry (If Available)

Check for a newer version of `@sentry/nextjs` that supports Next.js 16:
```powershell
npm view @sentry/nextjs versions --json
```

If a compatible version exists, update `package.json`:
```json
"@sentry/nextjs": "^9.0.0"  // or whatever version supports Next.js 16
```

### Option 3: Make Sentry Optional (Temporary)

If Sentry is not critical for launch, you can:
1. Remove `@sentry/nextjs` from dependencies
2. Update `src/lib/sentry.ts` to gracefully handle missing package
3. Add Sentry back after launch when compatible version is available

## Recommended Action

For production launch, use **Option 1** (`--legacy-peer-deps`). This is safe because:
- Sentry is already implemented with graceful degradation
- The package will still function correctly
- You can update to a compatible version later

## After Fix

Run validation loop:
```powershell
npm ci --legacy-peer-deps
npm run lint
npm run typecheck
npm run build
```

---

**Note:** This is a known issue with Sentry's peer dependency range. The package will work fine with Next.js 16 despite the warning.
