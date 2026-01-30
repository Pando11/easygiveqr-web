# Step 17: Church Subscription Billing

## Overview

Implement monthly subscription billing for churches at $29.95/month. This is EasyGiveQR's revenue stream, separate from donation processing fees.

## Database Migration

### Run Migration

**In Supabase Dashboard → SQL Editor, run:**

```sql
-- File: supabase/migrations/20260127_add_subscription_to_churches.sql
-- Adds subscription billing fields to churches table
```

**OR run directly:**

```sql
-- See migration file for full SQL
```

**Fields Added:**
- `stripe_customer_id` - Stripe Customer ID (cus_...)
- `stripe_subscription_id` - Stripe Subscription ID (sub_...)
- `subscription_status` - Current status (active, past_due, canceled, trialing, etc.)
- `subscription_started_at` - When subscription was activated
- `subscription_canceled_at` - When subscription was canceled

## API Routes

### 1. Create Customer

**POST** `/api/billing/create-customer`

**Authentication:** Requires `x-admin-secret` header

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
  "stripe_customer_id": "cus_..."
}
```

**Behavior:**
- Creates Stripe Customer for the church
- Uses first admin email as customer email
- Stores `stripe_customer_id` in `churches` table
- Idempotent: returns existing customer if already created

### 2. Create Subscription Checkout

**POST** `/api/billing/create-subscription-checkout`

**Authentication:** Requires `x-admin-secret` header

**Request body:**
```json
{
  "church_id": "EGQR-123",
  "success_url": "https://your-domain.com/admin/billing?success=true",
  "cancel_url": "https://your-domain.com/admin/billing?canceled=true"
}
```

**Response:**
```json
{
  "ok": true,
  "url": "https://checkout.stripe.com/...",
  "session_id": "cs_..."
}
```

**Behavior:**
- Creates Stripe Checkout Session in subscription mode
- Uses $29.95/month price (creates if doesn't exist)
- Returns checkout URL for church to complete
- Requires customer to exist first

### 3. Get Church Billing Info

**GET** `/api/billing/church?church_id=EGQR-123`

**Authentication:** Requires `x-admin-secret` header

**Response:**
```json
{
  "ok": true,
  "church_id": "EGQR-123",
  "stripe_customer_id": "cus_...",
  "stripe_subscription_id": "sub_...",
  "subscription_status": "active",
  "subscription_started_at": "2026-01-27T14:00:00.000Z",
  "subscription_canceled_at": null
}
```

## Webhook Events

The webhook handler (`/api/stripe-webhook`) now processes:

### 1. `checkout.session.completed` (subscription mode)

**When:** Church completes subscription checkout

**Actions:**
- Extracts `subscription_id` and `customer_id` from session
- Updates `churches` table:
  - `stripe_subscription_id`
  - `stripe_customer_id` (if not already set)
  - `subscription_status: "active"`
  - `subscription_started_at`
  - `subscription_canceled_at: null`

### 2. `customer.subscription.updated`

**When:** Subscription status changes (e.g., payment fails, renews)

**Actions:**
- Finds church by `stripe_customer_id`
- Updates `subscription_status` to match Stripe status
- Updates `subscription_canceled_at` if canceled
- Updates `subscription_started_at` if not set and status is active

### 3. `customer.subscription.deleted`

**When:** Subscription is canceled/deleted

**Actions:**
- Finds church by `stripe_customer_id`
- Sets `subscription_status: "canceled"`
- Sets `subscription_canceled_at` timestamp

## Admin Page

### `/admin/billing`

**Features:**
- Input church ID
- "Create Customer" button
- "Create Subscription Checkout" button
- "Refresh Status" button
- Displays current subscription status:
  - Customer ID
  - Subscription ID
  - Status (with color coding)
  - Started date
  - Canceled date (if applicable)

**Authentication:** Prompts for `ADMIN_SECRET` when making API calls

## Stripe Price Setup

The code automatically creates the $29.95/month price if it doesn't exist:

- **Product:** "EasyGiveQR Monthly Subscription"
- **Price:** $29.95 USD per month
- **Recurring:** Monthly

**Manual Setup (Optional):**
1. Go to Stripe Dashboard → Products
2. Create product: "EasyGiveQR Monthly Subscription"
3. Add price: $29.95 USD, Monthly recurring
4. Note the price ID (price_...)

The code will find and use this price if it exists, or create it automatically.

## Local Testing

### Step 1: Run Migration

**In Supabase SQL Editor:**
```sql
-- Run: supabase/migrations/20260127_add_subscription_to_churches.sql
```

### Step 2: Create Customer

**Using curl:**
```bash
curl -X POST http://localhost:3000/api/billing/create-customer \
  -H "Content-Type: application/json" \
  -H "x-admin-secret: your-admin-secret" \
  -d '{"church_id": "EGQR-123"}'
```

**Expected response:**
```json
{
  "ok": true,
  "stripe_customer_id": "cus_..."
}
```

### Step 3: Verify Customer in Database

**In Supabase SQL Editor:**
```sql
SELECT 
  church_id,
  stripe_customer_id,
  stripe_subscription_id,
  subscription_status
FROM public.churches
WHERE church_id = 'EGQR-123';
```

**Expected:** `stripe_customer_id` should be set

### Step 4: Create Subscription Checkout

**Using curl:**
```bash
curl -X POST http://localhost:3000/api/billing/create-subscription-checkout \
  -H "Content-Type: application/json" \
  -H "x-admin-secret: your-admin-secret" \
  -d '{"church_id": "EGQR-123"}'
```

**Expected response:**
```json
{
  "ok": true,
  "url": "https://checkout.stripe.com/...",
  "session_id": "cs_..."
}
```

### Step 5: Complete Checkout

1. Open the `url` from Step 4 in browser
2. Use Stripe test card: `4242 4242 4242 4242`
3. Complete checkout

### Step 6: Verify Webhook Processed

**Check webhook events:**
```sql
SELECT * FROM public.stripe_webhook_events
WHERE event_type IN ('checkout.session.completed', 'customer.subscription.updated')
ORDER BY processed_at DESC
LIMIT 5;
```

### Step 7: Verify Subscription in Database

**In Supabase SQL Editor:**
```sql
SELECT 
  church_id,
  stripe_customer_id,
  stripe_subscription_id,
  subscription_status,
  subscription_started_at
FROM public.churches
WHERE church_id = 'EGQR-123';
```

**Expected:**
- `stripe_subscription_id` should be set (sub_...)
- `subscription_status` should be "active"
- `subscription_started_at` should be set

### Step 8: Test Subscription Update

**In Stripe Dashboard:**
1. Go to Customers → Find the customer
2. Go to Subscriptions
3. Cancel the subscription (or update status)

**Verify webhook processed:**
```sql
SELECT * FROM public.stripe_webhook_events
WHERE event_type = 'customer.subscription.updated'
ORDER BY processed_at DESC
LIMIT 1;
```

**Verify database updated:**
```sql
SELECT subscription_status, subscription_canceled_at
FROM public.churches
WHERE church_id = 'EGQR-123';
```

## Production Setup

### Stripe Webhook Events

**Add to Stripe Dashboard → Webhooks:**

1. Go to https://dashboard.stripe.com/webhooks
2. Edit your existing webhook endpoint
3. Add events:
   - `checkout.session.completed` (already added)
   - `customer.subscription.updated` (add this)
   - `customer.subscription.deleted` (add this)
4. Save

### Environment Variables

**Already configured:**
- `STRIPE_SECRET_KEY` - Used for creating customers and checkout sessions
- `STRIPE_WEBHOOK_SECRET` - Used for webhook signature verification

**No new environment variables required.**

## Admin Page Usage

### Access Admin Page

**URL:** `http://localhost:3000/admin/billing`

### Workflow

1. **Enter Church ID:** Type `EGQR-123` (or any church ID)

2. **Create Customer:**
   - Click "Create Customer"
   - Enter `ADMIN_SECRET` when prompted
   - Should see success message with customer ID

3. **Create Subscription Checkout:**
   - Click "Create Subscription Checkout"
   - Enter `ADMIN_SECRET` when prompted
   - Should see checkout link
   - Click link to complete subscription

4. **Refresh Status:**
   - Click "Refresh Status"
   - Enter `ADMIN_SECRET` when prompted
   - Should see current subscription status

## Subscription Status Values

- `active` - Subscription is active and paid
- `trialing` - In trial period
- `past_due` - Payment failed, retrying
- `canceled` - Subscription canceled
- `incomplete` - Initial payment failed
- `incomplete_expired` - Initial payment expired
- `unpaid` - Payment failed, subscription ended

## Important Notes

- **Separate from donations:** Subscription billing is completely separate from donation processing
- **Automatic price creation:** Code creates $29.95/month price if it doesn't exist
- **Idempotent:** Creating customer multiple times returns existing customer
- **Webhook required:** Subscription status updates come via webhooks
- **Admin-only:** All billing routes require `x-admin-secret` header

## Troubleshooting

### "Church does not have a Stripe customer"

**Solution:** Create customer first using `/api/billing/create-customer`

### Subscription status not updating

**Solution:**
- Check webhook events are being received
- Verify webhook events are added in Stripe Dashboard
- Check `stripe_webhook_events` table for errors
- Verify `STRIPE_WEBHOOK_SECRET` is correct

### Price not found

**Solution:** Code automatically creates price. If issues persist:
- Check Stripe Dashboard → Products
- Verify price exists: $29.95 USD, Monthly
- Or manually create and note the price ID

### Webhook not processing subscription events

**Solution:**
- Verify events are added to webhook endpoint in Stripe Dashboard
- Check webhook logs in Stripe Dashboard
- Verify webhook signature verification is working
- Check `stripe_webhook_events` table for processing status

## Testing Checklist

- [ ] Migration applied successfully
- [ ] Customer created for test church
- [ ] Subscription checkout session created
- [ ] Checkout completed successfully
- [ ] Webhook processed `checkout.session.completed`
- [ ] Church row updated with subscription ID and status
- [ ] Subscription status shows "active"
- [ ] Subscription update webhook processed
- [ ] Subscription cancellation webhook processed
- [ ] Admin page displays subscription status correctly
