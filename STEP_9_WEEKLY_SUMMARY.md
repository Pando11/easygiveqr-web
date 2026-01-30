# Step 9: Weekly Summary Email Batch Job

## Overview

Automated weekly email summaries for churches, sent every Wednesday. The batch job processes all active churches and sends summary emails to their administrators.

## Database Migration

### Run Migration

**In Supabase Dashboard → SQL Editor, run:**

```sql
-- Add admin_emails column if it doesn't exist
DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1 
        FROM information_schema.columns 
        WHERE table_schema = 'public' 
        AND table_name = 'churches' 
        AND column_name = 'admin_emails'
    ) THEN
        ALTER TABLE public.churches
        ADD COLUMN admin_emails text[] NOT NULL DEFAULT '{}';
        
        COMMENT ON COLUMN public.churches.admin_emails IS 'Array of email addresses for church administrators who receive weekly summary emails';
    END IF;
END $$;
```

**OR use the migration file:**

The migration file is located at: `supabase/migrations/20260127_add_admin_emails_to_churches.sql`

### Update Church Admin Emails

**To add admin emails to a church:**

```sql
UPDATE public.churches
SET admin_emails = ARRAY['admin1@example.com', 'admin2@example.com']
WHERE church_id = 'EGQR-123';
```

## Environment Variables

Add to `.env.local`:

```
CRON_SECRET=your-secret-key-here
SENDGRID_API_KEY=SG.xxxxxxxxxxxxx
SENDGRID_FROM_EMAIL=noreply@yourdomain.com
```

## API Endpoint

**POST** `/api/jobs/weekly-summary`

**Headers:**
- `x-cron-secret`: Must match `CRON_SECRET` environment variable

**Response:**
```json
{
  "ok": true,
  "summary": {
    "churchesProcessed": 5,
    "emailsSent": 10,
    "failures": 0,
    "failuresList": []
  }
}
```

## Local Testing

### 1. Set Up Test Data

**Add admin emails to a test church:**

```sql
UPDATE public.churches
SET admin_emails = ARRAY['your-email@example.com']
WHERE church_id = 'EGQR-123';
```

**Create test donations (optional):**

```sql
-- Insert test donations for the current week
INSERT INTO public.donations (church_id, stripe_session_id, amount_cents, currency, status, created_at)
VALUES 
  ('EGQR-123', 'cs_test_1', 1000, 'usd', 'succeeded', NOW() - INTERVAL '2 days'),
  ('EGQR-123', 'cs_test_2', 2500, 'usd', 'succeeded', NOW() - INTERVAL '1 day');
```

### 2. Test the Endpoint

**Using curl (Windows PowerShell):**

```powershell
$headers = @{
    "x-cron-secret" = "your-secret-key-here"
    "Content-Type" = "application/json"
}

Invoke-RestMethod -Uri "http://localhost:3000/api/jobs/weekly-summary" -Method POST -Headers $headers
```

**Using curl (Command Prompt):**

```cmd
curl -X POST http://localhost:3000/api/jobs/weekly-summary ^
  -H "x-cron-secret: your-secret-key-here" ^
  -H "Content-Type: application/json"
```

**Using Postman or similar:**
- Method: POST
- URL: `http://localhost:3000/api/jobs/weekly-summary`
- Headers:
  - `x-cron-secret`: `your-secret-key-here`
- Body: (empty)

### 3. Verify Results

- Check your email inbox for the summary email
- Check the API response for `churchesProcessed`, `emailsSent`, and `failures`

## Vercel Cron Setup

**In `vercel.json` (create if it doesn't exist):**

```json
{
  "crons": [
    {
      "path": "/api/jobs/weekly-summary",
      "schedule": "0 8 * * 3"
    }
  ]
}
```

**Schedule explanation:**
- `0 8 * * 3` = Every Wednesday at 8:00 AM UTC
- Adjust time as needed (account for America/Chicago timezone)

**Environment variables in Vercel:**
- Add `CRON_SECRET` to Vercel environment variables
- Add `SENDGRID_API_KEY` to Vercel environment variables
- Add `SENDGRID_FROM_EMAIL` to Vercel environment variables
- Add `SUPABASE_URL` to Vercel environment variables
- Add `SUPABASE_SERVICE_ROLE_KEY` to Vercel environment variables

**Note:** The cron job will automatically call the endpoint with the `x-cron-secret` header. You need to set `CRON_SECRET` in Vercel to match.

## Weekly Summary Details

### Date Range Calculation

- **Week Start:** Last Wednesday 00:00:00 (America/Chicago)
- **Week End:** This Wednesday 00:00:00 (America/Chicago)
- **Month Start:** First day of current month 00:00:00 (America/Chicago)

### Email Content

Each email includes:
- **This Week's Total:** Sum of all donations in the week
- **Breakdown:** One-time vs monthly (monthly currently shows $0.00, TODO)
- **Month-to-Date Total:** Sum from first of month
- **Week-over-Week Comparison:** Previous week total and percentage change
- **Processing & Deposit:** Fees message and deposit status

### Language Support

- English (EN) - default
- Spanish (ES) - based on `churches.preferred_language`

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

### No Emails Sent

- Check that churches have `admin_emails` array populated
- Verify SendGrid API key is valid
- Check SendGrid activity logs
- Review API response for `failuresList`

### Wrong Date Range

- Verify timezone handling (America/Chicago)
- Check that donations have correct `created_at` timestamps

## TODO

- [ ] Track one-time vs monthly donations (currently all shown as one-time)
- [ ] Add detailed processing fees breakdown
- [ ] Add more email template customization options
