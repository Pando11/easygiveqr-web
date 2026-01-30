# Database Migrations (CRITICAL - DO NOT SKIP)

## Why This Matters

**Code idempotency is not enough. Webhooks get retried. Without DB uniqueness you will eventually duplicate donations.**

## Required Constraints (Minimum)

### 1. `donations.stripe_session_id` UNIQUE
- **Migration:** `supabase/migrations/20260128_ensure_donations_unique_constraints.sql`
- **Why:** Prevents duplicate donation rows when webhook events are retried
- **Critical:** This is the primary idempotency mechanism

### 2. `stripe_webhook_events.event_id` UNIQUE
- **Migration:** `supabase/migrations/20260127_create_stripe_webhook_events.sql` (or equivalent)
- **Why:** Prevents duplicate webhook event processing
- **Critical:** Ensures each Stripe event is processed exactly once

### 3. Optional: `donations.payment_intent_id` UNIQUE
- **Why:** Additional safety if you store payment intent IDs
- **Status:** Check your schema - may already exist

## Verification Steps

### Step 1: Apply Migrations in Production Supabase

1. Go to Supabase Dashboard → SQL Editor
2. Run each migration file in order:
   - `20260127_create_stripe_webhook_events.sql` (if not already applied)
   - `20260128_ensure_donations_unique_constraints.sql`
3. Verify no errors

### Step 2: Verify Constraints Exist

Run this SQL query in Supabase SQL Editor:

```sql
SELECT 
  tc.table_name,
  tc.constraint_name,
  tc.constraint_type,
  kcu.column_name
FROM information_schema.table_constraints tc
JOIN information_schema.key_column_usage kcu
  ON tc.constraint_name = kcu.constraint_name
WHERE tc.table_name IN ('donations', 'stripe_webhook_events')
  AND tc.constraint_type = 'UNIQUE'
ORDER BY tc.table_name, tc.constraint_name;
```

**Expected Results:**
- `donations.stripe_session_id` - UNIQUE constraint exists
- `stripe_webhook_events.event_id` - UNIQUE constraint exists

### Step 3: Test Idempotency (Optional but Recommended)

1. Get a webhook event ID from Stripe Dashboard
2. Replay the event (using Stripe CLI or Dashboard)
3. Verify:
   - `stripe_webhook_events` table shows duplicate detected
   - `donations` table does NOT have duplicate rows
   - Webhook returns `{ received: true, duplicate: true }`

## Pass Criteria

- [ ] Migration `20260128_ensure_donations_unique_constraints.sql` applied
- [ ] Migration `20260127_create_stripe_webhook_events.sql` applied (or equivalent)
- [ ] SQL query confirms `donations.stripe_session_id` UNIQUE constraint exists
- [ ] SQL query confirms `stripe_webhook_events.event_id` UNIQUE constraint exists
- [ ] Screenshot/query evidence saved in runbook

## Failure Consequences

**If you skip this step:**
- Webhook retries will create duplicate donation rows
- Financial reporting will be incorrect
- Reconciliation will be impossible
- You will have to manually clean up duplicates

**This is not optional. It's the difference between a production-ready system and a gambling system.**

---

**Last Verified:** _[TO BE FILLED]_

**Migration Applied By:** _[TO BE FILLED]_
