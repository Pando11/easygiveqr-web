# Webhook Idempotency Verification

## ✅ Verified Safe

### 1. Event ID Uniqueness
- ✅ `stripe_webhook_events.event_id` has UNIQUE constraint
- ✅ Migration: `20260127_create_stripe_webhook_events.sql`

### 2. Duplicate Detection
- ✅ Webhook checks for existing `event_id` before processing
- ✅ Code location: `src/app/api/stripe-webhook/route.ts` lines 101-112
- ✅ Returns early if duplicate found: `{ received: true, duplicate: true }`

### 3. Race Condition Handling
- ✅ Catches `23505` (unique constraint violation) on insert
- ✅ Handles race condition where two requests process same event simultaneously
- ✅ Code location: `src/app/api/stripe-webhook/route.ts` lines 124-130

### 4. Donation Idempotency
- ✅ `donations.stripe_session_id` has UNIQUE constraint
- ✅ Migration: `20260128_ensure_donations_unique_constraints.sql`
- ✅ Webhook uses `upsert` with `onConflict: "stripe_session_id"`
- ✅ Code location: `src/app/api/stripe-webhook/route.ts` lines 370-385

### 5. Webhook Signature Verification
- ✅ Uses raw body: `const rawBody = await req.text()`
- ✅ Verifies signature: `stripe.webhooks.constructEvent(rawBody, signature, webhookSecret)`
- ✅ Code location: `src/app/api/stripe-webhook/route.ts` lines 50-86

## Test Procedure

### Manual Duplicate Event Test

1. **Get a webhook event from Stripe Dashboard:**
   - Go to Stripe Dashboard → Developers → Events
   - Find a `checkout.session.completed` event
   - Copy the event ID (e.g., `evt_xxxxx`)

2. **Replay the event:**
   ```bash
   # Using Stripe CLI
   stripe events resend evt_xxxxx
   ```

3. **Verify idempotency:**
   - Check `stripe_webhook_events` table - should show duplicate detected
   - Check `donations` table - should NOT have duplicate rows
   - Webhook should return `{ received: true, duplicate: true }`

### Database Verification

Run these SQL queries to verify constraints:

```sql
-- Verify event_id unique constraint
SELECT constraint_name, constraint_type
FROM information_schema.table_constraints
WHERE table_name = 'stripe_webhook_events'
AND constraint_type = 'UNIQUE';

-- Verify stripe_session_id unique constraint
SELECT constraint_name, constraint_type
FROM information_schema.table_constraints
WHERE table_name = 'donations'
AND constraint_type = 'UNIQUE'
AND constraint_name LIKE '%stripe_session_id%';
```

Expected:
- `stripe_webhook_events.event_id` UNIQUE constraint exists
- `donations.stripe_session_id` UNIQUE constraint exists

## Code Verification Checklist

- [x] Webhook uses raw body (`req.text()`)
- [x] Signature verification with `constructEvent()`
- [x] Event logged to `stripe_webhook_events` before processing
- [x] Duplicate event detection (checks `event_id` before insert)
- [x] Race condition handling (catches unique constraint violation)
- [x] Donation insert uses `upsert` with `onConflict`
- [x] UNIQUE constraint on `donations.stripe_session_id`

---

**Status:** ✅ All idempotency measures in place
