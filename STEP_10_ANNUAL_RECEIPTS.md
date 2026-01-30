# Step 10: Annual Tax Receipt Batch Job

## Overview

Automated annual tax receipt emails sent to donors once per year. The batch job processes all churches (or a specific church for testing) and sends receipt emails to donors who made donations in the specified tax year.

## Database Migrations

### Run Migrations

**In Supabase Dashboard → SQL Editor, run both migration files:**

1. **Add donor fields to donations table:**
   - File: `supabase/migrations/20260127_add_donor_fields_to_donations.sql`
   - Adds: `donor_email`, `donor_name`, `donor_address` columns
   - Creates index on `donor_email`

2. **Create annual_receipts_sent table:**
   - File: `supabase/migrations/20260127_create_annual_receipts_sent.sql`
   - Creates table with unique constraint on `(year, church_id, donor_email)`
   - Ensures idempotency (no duplicate receipts)

**OR run both in sequence:**

```sql
-- Migration 1: Add donor fields
DO $$
BEGIN
    IF NOT EXISTS (SELECT 1 FROM information_schema.columns WHERE table_schema = 'public' AND table_name = 'donations' AND column_name = 'donor_email') THEN
        ALTER TABLE public.donations ADD COLUMN donor_email text;
        ALTER TABLE public.donations ADD COLUMN donor_name text;
        ALTER TABLE public.donations ADD COLUMN donor_address jsonb;
        CREATE INDEX idx_donations_donor_email ON public.donations(donor_email);
    END IF;
END $$;

-- Migration 2: Create receipts tracking table
CREATE TABLE IF NOT EXISTS public.annual_receipts_sent (
    id uuid DEFAULT gen_random_uuid() PRIMARY KEY,
    year integer NOT NULL,
    church_id text NOT NULL,
    donor_email text NOT NULL,
    sent_at timestamptz DEFAULT now() NOT NULL,
    created_at timestamptz DEFAULT now() NOT NULL,
    CONSTRAINT annual_receipts_sent_unique UNIQUE (year, church_id, donor_email)
);
CREATE INDEX IF NOT EXISTS idx_annual_receipts_sent_year_church ON public.annual_receipts_sent(year, church_id);
CREATE INDEX IF NOT EXISTS idx_annual_receipts_sent_donor_email ON public.annual_receipts_sent(donor_email);
```

## Webhook Update

The webhook handler (`src/app/api/stripe-webhook/route.ts`) has been updated to capture:
- `session.customer_details.email` → `donor_email`
- `session.customer_details.name` → `donor_name`
- `session.customer_details.address` → `donor_address` (as JSON)

**Note:** Donor information is only captured for new donations. Existing donations will not have donor information until new donations are processed.

## Environment Variables

Ensure these are set in `.env.local`:

```
CRON_SECRET=your-secret-key-here
SENDGRID_API_KEY=SG.xxxxxxxxxxxxx
SENDGRID_FROM_EMAIL=noreply@yourdomain.com
```

## API Endpoint

**POST** `/api/jobs/annual-receipts`

**Headers:**
- `x-cron-secret`: Must match `CRON_SECRET` environment variable
- `Content-Type`: `application/json`

**Request Body:**
```json
{
  "year": 2025,
  "church_id": "EGQR-123"  // optional, for testing single church
}
```

**Response:**
```json
{
  "ok": true,
  "summary": {
    "year": 2025,
    "churchesProcessed": 3,
    "receiptsSent": 15,
    "receiptsSkipped": 2,
    "failures": 0,
    "failuresList": []
  }
}
```

## Local Testing

### 1. Set Up Test Data

**Ensure test church has EIN:**

```sql
UPDATE public.churches
SET ein = '12-3456789'
WHERE church_id = 'EGQR-123';
```

**Create test donations with donor emails:**

```sql
-- Insert test donations for 2025
INSERT INTO public.donations (church_id, stripe_session_id, amount_cents, currency, status, donor_email, donor_name, created_at)
VALUES 
  ('EGQR-123', 'cs_test_receipt_1', 1000, 'usd', 'succeeded', 'donor1@example.com', 'John Doe', '2025-01-15 10:00:00'),
  ('EGQR-123', 'cs_test_receipt_2', 2500, 'usd', 'succeeded', 'donor1@example.com', 'John Doe', '2025-06-20 14:30:00'),
  ('EGQR-123', 'cs_test_receipt_3', 5000, 'usd', 'succeeded', 'donor2@example.com', 'Jane Smith', '2025-11-10 09:15:00');
```

**Note:** Replace `donor1@example.com` and `donor2@example.com` with your actual test email addresses.

### 2. Test the Endpoint

**Using PowerShell:**

```powershell
$headers = @{
    "x-cron-secret" = "your-secret-key-here"
    "Content-Type" = "application/json"
}

$body = @{
    year = 2025
    church_id = "EGQR-123"
} | ConvertTo-Json

Invoke-RestMethod -Uri "http://localhost:3000/api/jobs/annual-receipts" -Method POST -Headers $headers -Body $body
```

**Using curl (Command Prompt):**

```cmd
curl -X POST http://localhost:3000/api/jobs/annual-receipts ^
  -H "x-cron-secret: your-secret-key-here" ^
  -H "Content-Type: application/json" ^
  -d "{\"year\": 2025, \"church_id\": \"EGQR-123\"}"
```

**Using the test script:**

```powershell
.\test-annual-receipts.ps1
```

### 3. Verify Results

- Check your email inbox for receipt emails
- Check the API response for `receiptsSent`, `receiptsSkipped`, and `failures`
- Verify in database:

```sql
SELECT * FROM public.annual_receipts_sent 
WHERE year = 2025 AND church_id = 'EGQR-123';
```

### 4. Test Idempotency

**Run the same request again:**

```powershell
# Same command as above
```

**Expected result:**
- `receiptsSent`: 0 (or same as before)
- `receiptsSkipped`: Should equal the number of receipts already sent
- No duplicate emails should be sent

## Production Usage

### Vercel Cron Setup

**In `vercel.json` (add to existing crons array):**

```json
{
  "crons": [
    {
      "path": "/api/jobs/weekly-summary",
      "schedule": "0 8 * * 3"
    },
    {
      "path": "/api/jobs/annual-receipts",
      "schedule": "0 9 1 2 *"
    }
  ]
}
```

**Schedule explanation:**
- `0 9 1 2 *` = February 1st at 9:00 AM UTC
- This runs once per year to send receipts for the previous tax year
- Adjust date/time as needed

**Manual trigger (for testing in production):**

You can also trigger manually via API call with the cron secret.

### Annual Receipt Process

**Typical workflow:**

1. **Early February:** Run batch job for previous year (e.g., 2025 receipts in Feb 2026)
2. **Request body:**
   ```json
   {
     "year": 2025
   }
   ```
3. **Job processes:**
   - All active churches (or specific church if `church_id` provided)
   - All unique donor emails that donated in the year
   - Sums total donations per donor per church
   - Sends one receipt email per donor per church
   - Tracks sent receipts to prevent duplicates

## Email Content

Each receipt email includes:
- **Total annual donations** (sum of all succeeded donations in the year)
- **Church legal name**
- **EIN** (Employer Identification Number)
- **Tax year**
- **Required IRS language** (501(c)(3) notice)
- **Statement about no goods/services provided**
- Language: EN or ES based on `churches.preferred_language`

## Troubleshooting

### "Unauthorized" Error

- Check that `x-cron-secret` header matches `CRON_SECRET` env var
- Verify `CRON_SECRET` is set in `.env.local`

### "SENDGRID_API_KEY not configured"

- Add `SENDGRID_API_KEY` to `.env.local`
- Get API key from SendGrid dashboard

### "SENDGRID_FROM_EMAIL not configured"

- Add `SENDGRID_FROM_EMAIL` to `.env.local`
- Must be a verified sender in SendGrid

### No Receipts Sent

- Check that donations have `donor_email` populated
- Verify donations have `status = 'succeeded'`
- Check that donations are in the specified year
- Review API response for `failuresList`

### Receipts Already Sent (Idempotency)

- Check `annual_receipts_sent` table:
  ```sql
  SELECT * FROM public.annual_receipts_sent 
  WHERE year = 2025 AND church_id = 'EGQR-123';
  ```
- If receipt was already sent, it will be skipped (idempotent)

### Missing Donor Information

- Donor information is captured from Stripe `customer_details`
- Only new donations (after webhook update) will have donor info
- Existing donations may need to be updated manually or re-processed

## Important Notes

- **No PDFs:** Receipts are email-only
- **No donor portal:** Donors receive emails, no login required
- **No dashboard:** This is a batch job only
- **Idempotent:** Running the same job twice won't send duplicate emails
- **One receipt per donor per church per year:** Multiple donations are summed into one receipt

## TODO

- [ ] Consider adding donor address to receipt (currently captured but not displayed)
- [ ] Add option to resend specific receipts
- [ ] Add receipt download/view capability (future enhancement)
