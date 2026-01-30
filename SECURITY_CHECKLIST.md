# Security Checklist

## Overview

This document describes the security controls implemented for the EasyGiveQR API endpoints.

## Authentication Methods

### 1. Admin Secret (`x-admin-secret`)

**Required for:**
- `/api/onboarding/*` - Church onboarding endpoints
- `/api/connect/*` - Stripe Connect management endpoints
- `/api/qr/generate` - QR code generation endpoint

**Environment Variable:** `ADMIN_SECRET`

**Usage:**
```bash
curl -X POST http://localhost:3000/api/onboarding/create-church \
  -H "x-admin-secret: your-admin-secret-here" \
  -F "church_id=EGQR-123" \
  ...
```

### 2. Cron Secret (`x-cron-secret`)

**Required for:**
- `/api/jobs/weekly-summary` - Weekly summary email job
- `/api/jobs/annual-receipts` - Annual tax receipt job
- `/api/jobs/wednesday-payouts` - Wednesday payout reconciliation job

**Environment Variable:** `CRON_SECRET`

**Usage:**
```bash
curl -X POST http://localhost:3000/api/jobs/weekly-summary \
  -H "x-cron-secret: your-cron-secret-here"
```

## Public Endpoints

### Read-Only Endpoints (No Auth Required)

**GET `/api/qr?church_id=EGQR-123`**
- Returns QR code information
- No authentication required
- Rate limited (30 requests per minute per IP)

**GET `/api/donation?session_id=cs_xxx`**
- Returns donation information by session ID
- No authentication required
- Rate limited (30 requests per minute per IP)
- Validates `session_id` parameter

**GET `/api/stripe-webhook`**
- Health check endpoint
- Returns `{ ok: true }`
- No authentication required

**POST `/api/stripe-webhook`**
- Stripe webhook handler
- Authenticated via Stripe signature verification
- No additional header auth required

**POST `/api/checkout-session`**
- Creates Stripe Checkout Session
- No authentication required (public donation flow)
- Rate limited (20 requests per minute per IP)

## Rate Limiting

### Protected Endpoints

**`/api/checkout-session`**
- **Limit:** 20 requests per minute per IP
- **Response:** 429 Too Many Requests
- **Headers:** `Retry-After`, `X-RateLimit-*`

**`/api/donation`**
- **Limit:** 30 requests per minute per IP
- **Response:** 429 Too Many Requests
- **Headers:** `Retry-After`, `X-RateLimit-*`

**Note:** Rate limiting is in-memory and per-instance. In serverless environments (Vercel), this resets on cold starts. For production-grade rate limiting, consider a Redis-backed solution.

## Environment Variables

### Required Variables

All of these must be set in `.env.local` (local) or Vercel environment variables (production):

```bash
# Supabase
SUPABASE_URL=https://...
SUPABASE_SERVICE_ROLE_KEY=...

# Stripe
STRIPE_SECRET_KEY=sk_...
STRIPE_WEBHOOK_SECRET=whsec_...

# SendGrid
SENDGRID_API_KEY=SG....
SENDGRID_FROM_EMAIL=noreply@...

# Security
ADMIN_SECRET=your-secure-random-string-here
CRON_SECRET=your-secure-random-string-here

# Site URL
NEXT_PUBLIC_SITE_URL=http://localhost:3000  # or https://easygiveqr.com
```

### Generating Secure Secrets

**Generate random secrets:**
```bash
# Linux/Mac
openssl rand -hex 32

# PowerShell (Windows)
[Convert]::ToBase64String((1..32 | ForEach-Object { Get-Random -Minimum 0 -Maximum 256 }))
```

**Or use an online generator:**
- https://www.random.org/strings/
- Generate 32+ character random strings

## Testing Authentication

### Test Without Header (Should Return 401)

```bash
# Test admin endpoint without auth
curl -X POST http://localhost:3000/api/qr/generate \
  -H "Content-Type: application/json" \
  -d '{"church_id": "EGQR-123"}'

# Expected: {"ok":false,"error":"Unauthorized: Missing or invalid x-admin-secret header"}
```

### Test With Invalid Header (Should Return 401)

```bash
# Test with wrong secret
curl -X POST http://localhost:3000/api/qr/generate \
  -H "Content-Type: application/json" \
  -H "x-admin-secret: wrong-secret" \
  -d '{"church_id": "EGQR-123"}'

# Expected: {"ok":false,"error":"Unauthorized: Missing or invalid x-admin-secret header"}
```

### Test With Valid Header (Should Return 200)

```bash
# Test with correct secret
curl -X POST http://localhost:3000/api/qr/generate \
  -H "Content-Type: application/json" \
  -H "x-admin-secret: your-actual-admin-secret" \
  -d '{"church_id": "EGQR-123"}'

# Expected: {"ok":true,"qr_code_url":"...","donate_url":"..."}
```

### Test Cron Endpoint

```bash
# Without auth (401)
curl -X POST http://localhost:3000/api/jobs/weekly-summary

# With auth (200)
curl -X POST http://localhost:3000/api/jobs/weekly-summary \
  -H "x-cron-secret: your-actual-cron-secret"
```

## Rate Limiting Tests

### Test Rate Limit (Should Return 429)

```bash
# Make 21 requests quickly (limit is 20/min)
for i in {1..21}; do
  curl -X POST http://localhost:3000/api/checkout-session \
    -H "Content-Type: application/json" \
    -d '{"amount": 1000, "church_id": "EGQR-123"}'
done

# Expected on 21st request: {"ok":false,"error":"Rate limit exceeded...","retry_after":...}
```

## Security Best Practices

### 1. Never Expose Service Role Key

- ✅ **DO:** Use `SUPABASE_SERVICE_ROLE_KEY` only in server-side code
- ❌ **DON'T:** Expose service role key in client-side code
- ❌ **DON'T:** Log service role key values
- ❌ **DON'T:** Commit secrets to git

### 2. Use Strong Secrets

- Generate random, long secrets (32+ characters)
- Use different secrets for `ADMIN_SECRET` and `CRON_SECRET`
- Rotate secrets periodically
- Never use default or predictable values

### 3. Environment Variables

- ✅ **DO:** Store secrets in `.env.local` (local) or Vercel environment variables (production)
- ✅ **DO:** Add `.env.local` to `.gitignore`
- ❌ **DON'T:** Commit `.env.local` to version control
- ❌ **DON'T:** Share secrets in chat, email, or documentation

### 4. Vercel Cron Jobs

**When setting up Vercel Cron jobs, include the secret header:**

```json
{
  "crons": [
    {
      "path": "/api/jobs/weekly-summary",
      "schedule": "0 9 * * 3"
    }
  ]
}
```

**In Vercel Dashboard:**
1. Go to Settings → Environment Variables
2. Add `CRON_SECRET` with your secret value
3. Vercel will automatically include headers when calling cron endpoints

**For manual cron testing, use:**
```bash
curl -X POST https://your-domain.vercel.app/api/jobs/weekly-summary \
  -H "x-cron-secret: your-cron-secret"
```

### 5. Monitoring

- Monitor for 401 responses (unauthorized access attempts)
- Monitor for 429 responses (rate limit hits)
- Set up alerts for unusual patterns
- Log security events (without exposing secrets)

## Endpoint Summary

| Endpoint | Method | Auth Required | Rate Limited |
|----------|--------|--------------|--------------|
| `/api/jobs/weekly-summary` | POST | `x-cron-secret` | No |
| `/api/jobs/annual-receipts` | POST | `x-cron-secret` | No |
| `/api/jobs/wednesday-payouts` | POST | `x-cron-secret` | No |
| `/api/onboarding/create-church` | POST | `x-admin-secret` | No |
| `/api/connect/create-account` | POST | `x-admin-secret` | No |
| `/api/connect/onboarding-link` | POST | `x-admin-secret` | No |
| `/api/connect/sync-status` | POST | `x-admin-secret` | No |
| `/api/qr/generate` | POST | `x-admin-secret` | No |
| `/api/qr` | GET | None | Yes (30/min) |
| `/api/checkout-session` | POST | None | Yes (20/min) |
| `/api/donation` | GET | None | Yes (30/min) |
| `/api/stripe-webhook` | GET | None | No |
| `/api/stripe-webhook` | POST | Stripe signature | No |

## Troubleshooting

### "Unauthorized: Missing or invalid x-admin-secret header"

**Solution:**
- Check that `ADMIN_SECRET` is set in environment variables
- Verify the header name is exactly `x-admin-secret` (lowercase)
- Ensure the secret value matches exactly (no extra spaces)

### "Unauthorized: Missing or invalid x-cron-secret header"

**Solution:**
- Check that `CRON_SECRET` is set in environment variables
- Verify the header name is exactly `x-cron-secret` (lowercase)
- Ensure the secret value matches exactly

### "Rate limit exceeded"

**Solution:**
- Wait for the rate limit window to reset (check `Retry-After` header)
- Reduce request frequency
- For production, consider implementing Redis-backed rate limiting

### Environment Variable Validation Errors

**If you see errors about missing environment variables:**
- Check `.env.local` file exists
- Verify all required variables are set
- Restart Next.js dev server after adding variables
- In production, verify Vercel environment variables are set

## Additional Security Notes

- **Server-side only:** All authentication and rate limiting happens server-side
- **No client secrets:** Never expose `ADMIN_SECRET` or `CRON_SECRET` to client-side code
- **Stripe webhooks:** Authenticated via Stripe signature verification (separate from header auth)
- **Service role key:** Only used server-side, never exposed to clients
- **Rate limiting:** Best-effort in-memory (resets on serverless cold starts)

## Production Deployment

### Vercel Environment Variables

Set all required environment variables in Vercel Dashboard:
1. Go to Project → Settings → Environment Variables
2. Add each variable for Production, Preview, and Development
3. Redeploy after adding variables

### Vercel Cron Configuration

**`vercel.json`:**
```json
{
  "crons": [
    {
      "path": "/api/jobs/weekly-summary",
      "schedule": "0 9 * * 3"
    },
    {
      "path": "/api/jobs/annual-receipts",
      "schedule": "0 0 1 1 *"
    },
    {
      "path": "/api/jobs/wednesday-payouts",
      "schedule": "0 9 * * 3"
    }
  ]
}
```

Vercel will automatically include the `x-cron-secret` header when calling these endpoints, using the `CRON_SECRET` environment variable.
