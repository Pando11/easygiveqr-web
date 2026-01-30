# Step 13: Church Onboarding API + Admin Page

## Overview

A complete onboarding flow for adding a church and automatically provisioning everything needed for launch:
- Logo upload to Supabase Storage
- QR code generation
- Stripe Connect account creation
- Stripe onboarding link generation

## API Route

### POST `/api/onboarding/create-church`

**Content-Type:** `multipart/form-data`

**Required Fields:**
- `church_id` (string): Format `EGQR-XXX` (e.g., `EGQR-123`)
- `legal_name` (string): Legal name of the church
- `display_name` (string): Display name for public-facing pages
- `ein` (string): Employer Identification Number
- `preferred_language` (string): `EN` or `ES`
- `primary_color` (string): Hex color `#RRGGBB` (e.g., `#1D4ED8`)
- `donation_phrase` (string): Phrase shown on donation page
- `admin_emails` (string): Comma-separated email addresses
- `logo` (file): Image file (PNG, JPG, SVG, WebP, max 5MB)

**Response (Success):**
```json
{
  "ok": true,
  "church_id": "EGQR-123",
  "donate_url": "http://localhost:3000/donate?church_id=EGQR-123",
  "logo_url": "https://...supabase.co/storage/v1/object/public/church-assets/logos/EGQR-123.png",
  "qr_code_url": "https://...supabase.co/storage/v1/object/public/church-assets/qr/EGQR-123.png",
  "stripe_account_id": "acct_...",
  "onboarding_link": "https://connect.stripe.com/..."
}
```

**Response (Error):**
```json
{
  "ok": false,
  "error": "Error message"
}
```

**What It Does:**
1. Validates all required fields and formats
2. Uploads logo to Supabase Storage at `logos/{church_id}.{ext}`
3. Creates Stripe Connect Express account
4. Generates QR code and uploads to storage
5. Inserts church record into `public.churches` with:
   - All provided fields
   - `logo_url` from storage
   - `qr_code_url` from storage
   - `stripe_account_id` from Stripe
   - `stripe_onboarding_status: "not_started"`
   - `status: "pending"`
6. Generates Stripe Connect onboarding link
7. Returns all URLs and IDs

## Admin Page

### `/admin/onboarding`

**Features:**
- Form with all required fields
- File upload for logo
- Real-time validation
- Success display with:
  - Church ID
  - Donation URL
  - Logo URL
  - QR code preview
  - Stripe onboarding link button

**No authentication required** (for local dev only)

## Environment Variables

**Required in `.env.local`:**
```
NEXT_PUBLIC_SITE_URL=http://localhost:3000
STRIPE_SECRET_KEY=sk_...
SUPABASE_URL=https://...
SUPABASE_SERVICE_ROLE_KEY=...
```

**For production:**
```
NEXT_PUBLIC_SITE_URL=https://easygiveqr.com
```

## Storage Bucket

**Required bucket:** `church-assets` (from Step 12)

**Paths:**
- Logos: `logos/{church_id}.{ext}`
- QR codes: `qr/{church_id}.png`

**Ensure bucket is public** for direct URL access.

## Validation Rules

### Church ID
- Format: `EGQR-XXX` where `XXX` is alphanumeric
- Must be unique (checked against database)

### Primary Color
- Format: `#RRGGBB` (6 hex digits)
- Example: `#1D4ED8`

### Preferred Language
- Must be `EN` or `ES` (case-insensitive)

### Admin Emails
- Comma-separated list
- Each email validated for format
- At least one valid email required

### Logo
- Must be an image file
- Accepted types: PNG, JPG, SVG, WebP
- Maximum size: 5MB
- File extension determined from filename or content type

## Local Testing

### Step 1: Ensure Storage Bucket Exists

**In Supabase Dashboard:**
1. Go to Storage → Buckets
2. Verify `church-assets` bucket exists
3. Ensure it's set to public

### Step 2: Set Environment Variables

**In `.env.local`:**
```
NEXT_PUBLIC_SITE_URL=http://localhost:3000
```

### Step 3: Start Dev Server

```cmd
npm run dev
```

### Step 4: Open Admin Page

**In browser:**
```
http://localhost:3000/admin/onboarding
```

### Step 5: Fill Out Form

**Test data:**
- Church ID: `EGQR-999`
- Legal Name: `Test Church Legal Name`
- Display Name: `Test Church`
- EIN: `12-3456789`
- Preferred Language: `EN`
- Primary Color: `#1D4ED8`
- Donation Phrase: `Support our mission`
- Admin Emails: `admin@testchurch.com, finance@testchurch.com`
- Logo: Upload any image file (PNG/JPG/SVG/WebP)

### Step 6: Submit Form

Click "Create Church & Provision Everything"

**Expected:**
- Success message displayed
- Church ID shown
- Donation URL shown
- Logo URL shown
- QR code image displayed
- Stripe onboarding link button shown

### Step 7: Verify in Database

**In Supabase SQL Editor:**
```sql
SELECT 
  church_id,
  legal_name,
  display_name,
  logo_url,
  qr_code_url,
  stripe_account_id,
  stripe_onboarding_status,
  status
FROM public.churches
WHERE church_id = 'EGQR-999';
```

**Expected:**
- All fields populated
- `logo_url` contains Supabase Storage URL
- `qr_code_url` contains Supabase Storage URL
- `stripe_account_id` starts with `acct_`
- `stripe_onboarding_status` is `not_started` or `pending`
- `status` is `pending`

### Step 8: Verify Logo URL

**Open `logo_url` in browser:**
- Should display the uploaded logo image

### Step 9: Verify QR Code URL

**Open `qr_code_url` in browser:**
- Should display QR code PNG image

### Step 10: Scan QR Code

**Using QR scanner app:**
1. Scan the QR code
2. Should navigate to: `http://localhost:3000/donate?church_id=EGQR-999`
3. Verify donation page loads with church data

### Step 11: Test Stripe Onboarding Link

**Click "Complete Stripe Onboarding" button:**
- Should open Stripe Connect onboarding page
- Complete or cancel (for testing)
- After completion, use `/api/connect/sync-status` to update status

## API Testing (Alternative to UI)

### Using PowerShell:

```powershell
$formData = @{
    church_id = "EGQR-999"
    legal_name = "Test Church Legal Name"
    display_name = "Test Church"
    ein = "12-3456789"
    preferred_language = "EN"
    primary_color = "#1D4ED8"
    donation_phrase = "Support our mission"
    admin_emails = "admin@testchurch.com,finance@testchurch.com"
}

# Note: File upload requires multipart/form-data
# Use curl or Postman for full testing, or use the admin UI
```

**For full API testing with file upload, use:**
- Postman
- curl
- Or the provided admin UI page

## Error Handling

### Common Errors:

**"Church with this church_id already exists"**
- Solution: Use a different `church_id` or delete existing church

**"Invalid church_id format. Must be EGQR-XXX"**
- Solution: Use format `EGQR-123` (alphanumeric after `EGQR-`)

**"Logo file too large. Maximum size is 5MB"**
- Solution: Compress or resize logo image

**"Storage bucket 'church-assets' not found"**
- Solution: Create bucket in Supabase Dashboard

**"Failed to create Stripe account"**
- Solution: Check `STRIPE_SECRET_KEY` is set correctly

**"No valid admin emails provided"**
- Solution: Provide at least one valid email address

## Production Setup

### Environment Variables in Vercel

Set:
```
NEXT_PUBLIC_SITE_URL=https://easygiveqr.com
STRIPE_SECRET_KEY=sk_live_...
SUPABASE_URL=https://...
SUPABASE_SERVICE_ROLE_KEY=...
```

### Storage Bucket

- Ensure `church-assets` bucket exists in production Supabase
- Ensure bucket is public
- Logos stored at: `logos/{church_id}.{ext}`
- QR codes stored at: `qr/{church_id}.png`

### Onboarding Flow

1. Admin fills out form at `/admin/onboarding`
2. Church created with `status: "pending"`
3. Admin completes Stripe onboarding
4. Use `/api/connect/sync-status` to update status
5. Change `status` to `"active"` when ready to launch

## Important Notes

- **One-time setup:** Each church is created once
- **Automatic provisioning:** QR code and Stripe account created automatically
- **Pending status:** Churches start as `pending` until activated
- **Stripe onboarding:** Must be completed before church can receive payments
- **No authentication:** Admin page has no auth (local dev only; add auth for production)
- **File upload:** Uses native FormData API (no external libraries needed)

## Files Created

1. `src/lib/onboardingHelpers.ts` - Helper functions for QR, Stripe, logo upload
2. `src/app/api/onboarding/create-church/route.ts` - Main onboarding API route
3. `src/app/admin/onboarding/page.tsx` - Admin UI page

## Dependencies

**Already installed (from previous steps):**
- `qrcode` - QR code generation
- `stripe` - Stripe Connect
- `@supabase/supabase-js` - Supabase client

**No new dependencies required.**
