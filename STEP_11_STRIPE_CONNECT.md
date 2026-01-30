# Step 11: Stripe Connect Onboarding & Wednesday Payouts

## Overview

Stripe Connect platform model implementation. Churches onboard to receive direct payouts. EasyGiveQR never touches funds; Stripe handles everything. Payouts happen automatically every Wednesday via Stripe's schedule.

## Database Migration

### Run Migration

**In Supabase Dashboard → SQL Editor, run:**

```sql
-- File: supabase/migrations/20260127_add_stripe_connect_to_churches.sql
-- Adds Stripe Connect account fields to churches table
```

**OR run directly:**

```sql
-- Add stripe_account_id
DO $$
BEGIN
    IF NOT EXISTS (SELECT 1 FROM information_schema.columns WHERE table_schema = 'public' AND table_name = 'churches' AND column_name = 'stripe_account_id') THEN
        ALTER TABLE public.churches ADD COLUMN stripe_account_id text;
    END IF;
END $$;

-- Add stripe_onboarding_status
DO $$
BEGIN
    IF NOT EXISTS (SELECT 1 FROM information_schema.columns WHERE table_schema = 'public' AND table_name = 'churches' AND column_name = 'stripe_onboarding_status') THEN
        ALTER TABLE public.churches ADD COLUMN stripe_onboarding_status text DEFAULT 'not_started';
    END IF;
END $$;

-- Add stripe_charges_enabled
DO $$
BEGIN
    IF NOT EXISTS (SELECT 1 FROM information_schema.columns WHERE table_schema = 'public' AND table_name = 'churches' AND column_name = 'stripe_charges_enabled') THEN
        ALTER TABLE public.churches ADD COLUMN stripe_charges_enabled boolean DEFAULT false;
    END IF;
END $$;

-- Add stripe_payouts_enabled
DO $$
BEGIN
    IF NOT EXISTS (SELECT 1 FROM information_schema.columns WHERE table_schema = 'public' AND table_name = 'churches' AND column_name = 'stripe_payouts_enabled') THEN
        ALTER TABLE public.churches ADD COLUMN stripe_payouts_enabled boolean DEFAULT false;
    END IF;
END $$;

-- Add stripe_details_submitted
DO $$
BEGIN
    IF NOT EXISTS (SELECT 1 FROM information_schema.columns WHERE table_schema = 'public' AND table_name = 'churches' AND column_name = 'stripe_details_submitted') THEN
        ALTER TABLE public.churches ADD COLUMN stripe_details_submitted boolean DEFAULT false;
    END IF;
END $$;

-- Create index
CREATE INDEX IF NOT EXISTS idx_churches_stripe_account_id ON public.churches(stripe_account_id);
```

## API Routes

### 1. Create Connected Account

**POST** `/api/connect/create-account`

**Request body:**
```json
{
  "church_id": "EGQR-123"
}
```

**Response:**
```json
{
  "ok": true,
  "stripe_account_id": "acct_xxxxxxxxxxxxx"
}
```

**Behavior:**
- If church already has `stripe_account_id`, returns existing account
- Otherwise, creates new Stripe Express account
- Updates church record with account ID
- Sets onboarding status to "not_started"

### 2. Generate Onboarding Link

**POST** `/api/connect/onboarding-link`

**Request body:**
```json
{
  "church_id": "EGQR-123",
  "return_url": "https://example.com/onboarding/complete",
  "refresh_url": "https://example.com/onboarding"
}
```

**Response:**
```json
{
  "ok": true,
  "url": "https://connect.stripe.com/setup/..."
}
```

**Behavior:**
- Requires church to have `stripe_account_id` (create account first)
- Creates Stripe account link for onboarding
- Updates onboarding status to "pending"
- Returns URL for church to complete onboarding

### 3. Sync Account Status

**POST** `/api/connect/sync-status`

**Request body:**
```json
{
  "church_id": "EGQR-123"
}
```

**Response:**
```json
{
  "ok": true,
  "status": {
    "stripe_account_id": "acct_...",
    "onboarding_status": "complete",
    "charges_enabled": true,
    "payouts_enabled": true,
    "details_submitted": true
  }
}
```

**Behavior:**
- Retrieves account from Stripe
- Updates church record with current status
- Determines onboarding status based on account capabilities

### 4. Wednesday Payouts Job

**POST** `/api/jobs/wednesday-payouts`

**Headers:**
- `x-cron-secret`: Must match `CRON_SECRET`

**Response:**
```json
{
  "ok": true,
  "summary": {
    "churchesProcessed": 5,
    "emailsSent": 10,
    "failures": 0
  }
}
```

**Behavior:**
- For each church with Stripe account:
  - Calculates weekly total (last Wednesday to this Wednesday)
  - Determines payout status:
    - If onboarding incomplete: "Payouts not enabled—complete Stripe onboarding"
    - If enabled: "Payout scheduled for Wednesday via Stripe Connect (automatic)"
  - Sends deposit status email to admin_emails
- For v1: Email-only reconciliation (relies on Stripe's automatic payouts)

## Checkout Session Update

**`/api/checkout-session`** has been updated to use Stripe Connect:

- Fetches church's `stripe_account_id`
- Validates account is fully activated (`charges_enabled` and `payouts_enabled`)
- Uses **destination charges**:
  - `payment_intent_data.transfer_data.destination` = connected account
  - `application_fee_amount` = 0 (no platform fee)
  - Funds go directly to church's connected account
  - Churches pay Stripe processing fees directly
  - EasyGiveQR never touches funds

## Environment Variables

Ensure these are set in `.env.local`:

```
CRON_SECRET=your-secret-key-here
STRIPE_SECRET_KEY=sk_live_... (platform account key)
SENDGRID_API_KEY=SG.xxxxxxxxxxxxx
SENDGRID_FROM_EMAIL=noreply@yourdomain.com
```

## Local Testing

### Step 1: Create Connected Account

```powershell
$headers = @{ "Content-Type" = "application/json" }
$body = @{ church_id = "EGQR-123" } | ConvertTo-Json
Invoke-RestMethod -Uri "http://localhost:3000/api/connect/create-account" -Method POST -Headers $headers -Body $body
```

**Expected:** `{ "ok": true, "stripe_account_id": "acct_..." }`

### Step 2: Generate Onboarding Link

```powershell
$body = @{
    church_id = "EGQR-123"
    return_url = "http://localhost:3000/onboarding/complete"
    refresh_url = "http://localhost:3000/onboarding"
} | ConvertTo-Json

Invoke-RestMethod -Uri "http://localhost:3000/api/connect/onboarding-link" -Method POST -Headers $headers -Body $body
```

**Expected:** `{ "ok": true, "url": "https://connect.stripe.com/..." }`

### Step 3: Complete Onboarding

1. Open the URL from Step 2 in browser
2. Complete Stripe Connect onboarding flow
3. Fill out required information (business details, bank account, etc.)
4. Submit

### Step 4: Sync Status

```powershell
$body = @{ church_id = "EGQR-123" } | ConvertTo-Json
Invoke-RestMethod -Uri "http://localhost:3000/api/connect/sync-status" -Method POST -Headers $headers -Body $body
```

**Expected:** Status should show `onboarding_status: "complete"`, `charges_enabled: true`, `payouts_enabled: true`

### Step 5: Verify Church Row Updated

**In Supabase SQL Editor:**

```sql
SELECT 
  church_id,
  stripe_account_id,
  stripe_onboarding_status,
  stripe_charges_enabled,
  stripe_payouts_enabled,
  stripe_details_submitted
FROM public.churches
WHERE church_id = 'EGQR-123';
```

**Expected:** All Stripe fields should be populated/updated

### Step 6: Test Checkout with Connect

```powershell
$body = @{
    amount = 1000
    church_id = "EGQR-123"
} | ConvertTo-Json

Invoke-RestMethod -Uri "http://localhost:3000/api/checkout-session" -Method POST -Headers $headers -Body $body
```

**Expected:** Checkout session created successfully

**Verify in Stripe Dashboard:**
- Payment should show in connected account (not platform account)
- Transfer should be to the connected account

### Step 7: Test Wednesday Payouts Job

```powershell
$headers = @{
    "x-cron-secret" = "your-secret-key-here"
    "Content-Type" = "application/json"
}

Invoke-RestMethod -Uri "http://localhost:3000/api/jobs/wednesday-payouts" -Method POST -Headers $headers
```

**Expected:** Emails sent to church admins with deposit status

## Production Usage

### Vercel Cron Setup

**In `vercel.json`:**

```json
{
  "crons": [
    {
      "path": "/api/jobs/weekly-summary",
      "schedule": "0 8 * * 3"
    },
    {
      "path": "/api/jobs/wednesday-payouts",
      "schedule": "0 9 * * 3"
    },
    {
      "path": "/api/jobs/annual-receipts",
      "schedule": "0 9 1 2 *"
    }
  ]
}
```

**Schedule:** `0 9 * * 3` = Every Wednesday at 9:00 AM UTC

### Stripe Connect Configuration

**Important Notes:**

1. **Platform Model:** EasyGiveQR is the platform, churches are connected accounts
2. **Destination Charges:** Payments go directly to connected accounts
3. **Application Fee:** Set to 0% (revenue is subscription-only)
4. **Processing Fees:** Churches pay Stripe fees directly
5. **Automatic Payouts:** Stripe handles Wednesday payouts automatically for connected accounts
6. **No Manual Payouts:** For v1, rely on Stripe's automatic schedule (no manual payout creation needed)

## Troubleshooting

### "Church has not completed Stripe Connect onboarding"

- Create account: `POST /api/connect/create-account`
- Generate onboarding link: `POST /api/connect/onboarding-link`
- Complete onboarding in Stripe
- Sync status: `POST /api/connect/sync-status`

### "Church Stripe account is not fully activated"

- Check onboarding status: `POST /api/connect/sync-status`
- Ensure `charges_enabled` and `payouts_enabled` are both `true`
- Complete any remaining onboarding steps in Stripe

### Checkout fails with Connect error

- Verify church has `stripe_account_id`
- Verify account is fully activated
- Check Stripe Dashboard for account status

### Payouts not working

- Verify `stripe_payouts_enabled = true`
- Check Stripe Dashboard → Connected Accounts → Payouts
- Stripe handles automatic payouts per connected account schedule
- No manual payout creation needed for v1

## Important Notes

- **No Platform Fees:** `application_fee_amount = 0` (revenue is subscription-only)
- **Churches Pay Fees:** Processing fees are handled by Stripe and paid by churches
- **Automatic Payouts:** Stripe's automatic payout schedule handles Wednesday payouts
- **No Manual Payouts:** For v1, we only send reconciliation emails, not create payouts
- **Metadata Preserved:** `metadata.church_id` still included for reconciliation
