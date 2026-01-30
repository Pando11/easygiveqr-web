# Steps 22 & 23: Production Domain & Email Standardization

## Step 22: Production Domain Readiness

### Overview

Configure production domain `https://easygiveqr.net` for Vercel deployment and ensure all URLs use the correct domain in production.

### Implementation

#### 1. Site URL Helper

**`src/lib/siteUrl.ts`**

Centralized helper for getting site URL:
- **Production:** MUST use `SITE_URL` or `NEXT_PUBLIC_SITE_URL` (throws error if missing)
- **Development:** Allows fallback to request origin or localhost
- Prevents accidental localhost URLs in production

**Functions:**
- `getSiteUrl(requestOrigin?)` - Get base site URL
- `getDonationUrl(churchId, requestOrigin?)` - Get full donation URL

#### 2. Updated Checkout Session

**`src/app/api/checkout-session/route.ts`**

- Uses `getSiteUrl()` to build success/cancel URLs
- Ensures production always uses `https://easygiveqr.net`
- Throws clear error if `SITE_URL` missing in production

#### 3. Updated QR Generation

**`src/lib/onboardingHelpers.ts`** and **`src/app/api/qr/generate/route.ts`**

- Uses `getDonationUrl()` from `siteUrl.ts`
- Throws error if `SITE_URL` missing in production
- QR codes always point to correct production domain

### Documentation

**`DOMAIN_SETUP.md`**
- Step-by-step guide to connect `easygiveqr.net` to Vercel
- DNS configuration instructions
- SSL/HTTPS verification
- Common issues and solutions

**`STRIPE_SETUP.md`**
- Stripe webhook configuration for `https://easygiveqr.net/api/stripe-webhook`
- Checkout redirect domain settings
- Apple Pay / Google Pay domain verification
- Production keys setup

**`DEPLOYMENT_GUIDE.md`** (updated)
- Added production domain validation checklist
- Tests for donate page, checkout, webhooks, QR codes

## Step 23: Email Standardization

### Overview

Centralize all email sending, enforce correct sender (`helping@easygiveqr.net`), and consolidate templates.

### Implementation

#### 1. Centralized Email Sender

**`src/lib/email/sendEmail.ts`**

- Wraps SendGrid API
- Enforces `SENDGRID_FROM_EMAIL` (required, throws error if missing)
- Supports optional `SENDGRID_REPLY_TO_EMAIL`
- Does not log secrets or full recipient lists
- Returns `{ success, error? }` result

**Usage:**
```typescript
import { sendEmail } from "@/lib/email/sendEmail";

const result = await sendEmail({
  to: "recipient@example.com",
  subject: "Subject",
  html: "<p>HTML content</p>",
  text: "Plain text content",
  replyTo: "optional-reply@example.com",
});
```

#### 2. Template Consolidation

**`src/lib/email/templates.ts`**

Re-exports all email template functions:
- `weeklySummaryEN()` / `weeklySummaryES()`
- `annualReceiptEN()` / `annualReceiptES()`
- `generateEngagementEmailSubject/Html/Text()`

#### 3. Updated Email Sending Code

**Files Updated:**
- `src/app/api/jobs/weekly-summary/route.ts` - Uses centralized `sendEmail()`
- `src/app/api/jobs/annual-receipts/route.ts` - Uses centralized `sendEmail()`
- `src/app/api/engagement/submit/route.ts` - Uses centralized `sendEmail()`

All removed duplicate `sendEmail()` functions and now use the centralized module.

#### 4. Email Test Endpoint

**`src/app/api/admin/email-test/route.ts`**

**POST /api/admin/email-test**

Protected by `x-admin-secret` header.

**Request:**
```json
{
  "to_email": "test@example.com",
  "template": "weekly" | "annual" | "engagement",
  "language": "EN" | "ES"
}
```

**Response:**
```json
{
  "ok": true,
  "message": "Test email sent to test@example.com",
  "template": "weekly",
  "language": "EN"
}
```

Sends a sample email using the specified template and language.

#### 5. Environment Variables

**`.env.example`** (created/updated)

Includes:
```
SENDGRID_FROM_EMAIL=helping@easygiveqr.net
SENDGRID_REPLY_TO_EMAIL=helping@easygiveqr.net
```

**Important:** Sender email is `helping@easygiveqr.net` (NOT `help@easygiveqr.net`)

## Files Created

### Step 22:
1. `src/lib/siteUrl.ts` - Site URL helper
2. `DOMAIN_SETUP.md` - Domain configuration guide
3. `STRIPE_SETUP.md` - Stripe production setup guide

### Step 23:
1. `src/lib/email/sendEmail.ts` - Centralized email sender
2. `src/lib/email/templates.ts` - Template consolidation
3. `src/app/api/admin/email-test/route.ts` - Email test endpoint
4. `.env.example` - Environment variable template

## Files Updated

### Step 22:
1. `src/app/api/checkout-session/route.ts` - Uses `getSiteUrl()`
2. `src/lib/onboardingHelpers.ts` - Uses `getDonationUrl()` from `siteUrl.ts`
3. `src/app/api/qr/generate/route.ts` - Uses `getDonationUrl()` from `siteUrl.ts`
4. `DEPLOYMENT_GUIDE.md` - Added validation checklist

### Step 23:
1. `src/app/api/jobs/weekly-summary/route.ts` - Uses centralized `sendEmail()`
2. `src/app/api/jobs/annual-receipts/route.ts` - Uses centralized `sendEmail()`
3. `src/app/api/engagement/submit/route.ts` - Uses centralized `sendEmail()`

## Testing

### Step 22: Domain Setup

1. **Follow `DOMAIN_SETUP.md`** to connect domain to Vercel
2. **Set environment variable:**
   ```
   SITE_URL=https://easygiveqr.net
   ```
3. **Verify:**
   - `https://easygiveqr.net` loads
   - `https://easygiveqr.net/donate?church_id=EGQR-123` works
   - Checkout success URL uses `https://easygiveqr.net`
   - QR codes point to `https://easygiveqr.net`

### Step 23: Email Standardization

1. **Set environment variables:**
   ```
   SENDGRID_FROM_EMAIL=helping@easygiveqr.net
   SENDGRID_REPLY_TO_EMAIL=helping@easygiveqr.net
   ```

2. **Test email sending:**
   ```bash
   curl -X POST http://localhost:3000/api/admin/email-test \
     -H "Content-Type: application/json" \
     -H "x-admin-secret: YOUR_SECRET" \
     -d '{"to_email": "your-email@example.com", "template": "weekly", "language": "EN"}'
   ```

3. **Verify:**
   - Email received
   - From address is `helping@easygiveqr.net`
   - Reply-to is `helping@easygiveqr.net`
   - Content matches template

4. **Test all templates:**
   - `weekly` (EN/ES)
   - `annual` (EN/ES)
   - `engagement` (EN/ES)

## Important Notes

### Domain (Step 22)

- **Production requires `SITE_URL`:** Code throws error if missing in production
- **Development fallback:** Uses request origin or localhost in development
- **QR codes:** Always use `getDonationUrl()` helper
- **Checkout URLs:** Always use `getSiteUrl()` helper

### Email (Step 23)

- **Sender is `helping@easygiveqr.net`:** NOT `help@easygiveqr.net`
- **Centralized sending:** All email code uses `src/lib/email/sendEmail.ts`
- **Template consolidation:** All templates exported from `src/lib/email/templates.ts`
- **Test endpoint:** Use `/api/admin/email-test` to verify SendGrid config

## Troubleshooting

### Domain Issues

**Problem:** URLs still use localhost in production

**Solution:**
- Verify `SITE_URL=https://easygiveqr.net` is set in Vercel
- Redeploy after setting environment variable
- Check code is using `getSiteUrl()` helper

**Problem:** QR codes point to wrong domain

**Solution:**
- Regenerate QR codes after setting `SITE_URL`
- Verify `getDonationUrl()` is being used
- Check production environment variable is set

### Email Issues

**Problem:** `SENDGRID_FROM_EMAIL must be set` error

**Solution:**
- Set `SENDGRID_FROM_EMAIL=helping@easygiveqr.net` in environment variables
- Verify email address is verified in SendGrid
- Redeploy after setting environment variable

**Problem:** Emails not sending

**Solution:**
- Verify `SENDGRID_API_KEY` is set
- Check SendGrid dashboard for errors
- Use `/api/admin/email-test` endpoint to test
- Check server logs for SendGrid API errors

## Next Steps

1. **Domain Setup:**
   - Follow `DOMAIN_SETUP.md` to connect domain
   - Set `SITE_URL` in Vercel
   - Test all URLs use correct domain

2. **Email Setup:**
   - Set `SENDGRID_FROM_EMAIL` and `SENDGRID_REPLY_TO_EMAIL` in Vercel
   - Verify sender email in SendGrid
   - Test email sending with test endpoint
   - Verify all email types work

3. **Production Validation:**
   - Complete validation checklist in `DEPLOYMENT_GUIDE.md`
   - Test donation flow end-to-end
   - Verify webhook receives events
   - Test QR code scanning
