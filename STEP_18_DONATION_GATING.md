# Step 18: Donation Access Gating

## Overview

Gate donations based on church activation status and subscription status. Only churches that are active, have an active/trialing subscription, and have completed Stripe Connect onboarding can accept donations.

## Eligibility Criteria

A church is eligible to accept donations if **ALL** of the following are true:

1. **Church Status:** `status = 'active'`
2. **Subscription Status:** `subscription_status IN ('active', 'trialing')`
3. **Stripe Connect:** `stripe_charges_enabled = true` AND `stripe_payouts_enabled = true`

If any condition fails, donations are blocked.

## Implementation

### Server-Side Enforcement

**`src/app/api/checkout-session/route.ts`** (updated)
- Fetches church with eligibility fields
- Calls `isChurchEligibleForDonations()` helper
- Returns `403 { ok: false, error: "church_not_active" }` if not eligible
- **Cannot be bypassed by client**

### Client-Side UI Gating

**`src/app/donate/page.tsx`** (updated)
- Fetches church data from `/api/church`
- Checks eligibility client-side
- Shows friendly message if not eligible (EN/ES based on `preferred_language`)
- **Does not show donation form** if not eligible

### Helper Functions

**`src/lib/churchEligibility.ts`**
- `isChurchEligibleForDonations()` - Server-side eligibility check
- `getEligibilityReason()` - Returns reason for ineligibility
- Supports admin override flag (local dev only)

**`src/lib/donationMessages.ts`**
- `getDonationUnavailableMessage()` - EN/ES messages for unavailable donations
- `getChurchNotFoundMessage()` - EN/ES messages for church not found

### API Route Updates

**`src/app/api/church/route.ts`** (updated)
- Now returns eligibility fields: `status`, `subscription_status`, `stripe_charges_enabled`, `stripe_payouts_enabled`
- Used by donate page to check eligibility

## Admin Override (Local Dev Only)

**Environment Variable:** `ALLOW_DONATIONS_WHEN_INACTIVE=true`

**Safety:**
- Only works when `NODE_ENV !== "production"`
- Cannot be enabled in production
- Useful for local testing

**Usage:**
```bash
# In .env.local (local dev only)
ALLOW_DONATIONS_WHEN_INACTIVE=true
NODE_ENV=development
```

**Note:** This bypasses eligibility checks for testing. **Never set in production.**

## User Experience

### Eligible Church

**URL:** `/donate?church_id=EGQR-123` (where church is active, subscribed, and Connect-enabled)

**Shows:**
- Church logo (if available)
- Church display name
- Donation phrase
- "Donate $10" button
- Full donation form

### Ineligible Church

**URL:** `/donate?church_id=EGQR-123` (where church is pending/canceled/subscription inactive)

**Shows:**
- Friendly message: "Donations Temporarily Unavailable"
- Explanation in church's preferred language (EN/ES)
- Church name (if available)
- **No donation form**

### Church Not Found

**URL:** `/donate?church_id=INVALID`

**Shows:**
- "Church Not Found" message
- Instructions to check the link

## Testing

### Test 1: Active Church with Active Subscription

**Setup:**
```sql
UPDATE public.churches
SET 
  status = 'active',
  subscription_status = 'active',
  stripe_charges_enabled = true,
  stripe_payouts_enabled = true
WHERE church_id = 'EGQR-123';
```

**Expected:**
- Donate page shows donation form
- Checkout session can be created
- Donation completes successfully

### Test 2: Pending Church

**Setup:**
```sql
UPDATE public.churches
SET status = 'pending'
WHERE church_id = 'EGQR-123';
```

**Expected:**
- Donate page shows "Donations Temporarily Unavailable"
- Checkout session returns `403 { ok: false, error: "church_not_active" }`

### Test 3: Canceled Subscription

**Setup:**
```sql
UPDATE public.churches
SET 
  status = 'active',
  subscription_status = 'canceled',
  stripe_charges_enabled = true,
  stripe_payouts_enabled = true
WHERE church_id = 'EGQR-123';
```

**Expected:**
- Donate page shows "Donations Temporarily Unavailable"
- Checkout session returns `403 { ok: false, error: "church_not_active" }`

### Test 4: Incomplete Stripe Connect

**Setup:**
```sql
UPDATE public.churches
SET 
  status = 'active',
  subscription_status = 'active',
  stripe_charges_enabled = false,
  stripe_payouts_enabled = true
WHERE church_id = 'EGQR-123';
```

**Expected:**
- Donate page shows "Donations Temporarily Unavailable"
- Checkout session returns `403 { ok: false, error: "church_not_active" }`

### Test 5: Admin Override (Local Dev)

**Setup:**
```bash
# In .env.local
ALLOW_DONATIONS_WHEN_INACTIVE=true
NODE_ENV=development
```

**Then test with pending church:**
```sql
UPDATE public.churches
SET status = 'pending'
WHERE church_id = 'EGQR-123';
```

**Expected:**
- Donate page shows donation form (override active)
- Checkout session succeeds (override active)
- **Only works in development, not production**

## Error Responses

### Checkout Session API

**403 Forbidden (Not Eligible):**
```json
{
  "ok": false,
  "error": "church_not_active"
}
```

**404 Not Found:**
```json
{
  "ok": false,
  "error": "Church not found"
}
```

## Security Notes

### Server-Side Enforcement

- **Critical:** Eligibility is checked server-side in `/api/checkout-session`
- Client-side UI gating is for UX only
- Server-side check cannot be bypassed
- Returns `403` if not eligible

### Admin Override Safety

- Only works when `NODE_ENV !== "production"`
- Explicitly checked in code
- Documented as local dev only
- Should never be set in production environment variables

## Local Testing

### Step 1: Test Eligible Church

```bash
# Ensure church is eligible
# Then visit:
http://localhost:3000/donate?church_id=EGQR-123

# Expected: Donation form visible
```

### Step 2: Test Ineligible Church (Pending Status)

```sql
-- Make church pending
UPDATE public.churches SET status = 'pending' WHERE church_id = 'EGQR-123';
```

```bash
# Visit:
http://localhost:3000/donate?church_id=EGQR-123

# Expected: "Donations Temporarily Unavailable" message
```

### Step 3: Test Server-Side Enforcement

```bash
# Try to create checkout session for ineligible church
curl -X POST http://localhost:3000/api/checkout-session \
  -H "Content-Type: application/json" \
  -d '{"amount": 1000, "church_id": "EGQR-123"}'

# Expected: {"ok":false,"error":"church_not_active"} with 403 status
```

### Step 4: Test Admin Override

```bash
# Add to .env.local
ALLOW_DONATIONS_WHEN_INACTIVE=true
NODE_ENV=development

# Restart dev server
npm run dev

# Test with pending church
# Expected: Donation form visible (override active)
```

## Production Behavior

### Eligible Church Flow

1. User visits `/donate?church_id=EGQR-123`
2. Page fetches church data
3. Eligibility check passes
4. Donation form displayed
5. User clicks "Donate"
6. Checkout session created (server validates eligibility again)
7. User completes payment
8. Webhook processes donation

### Ineligible Church Flow

1. User visits `/donate?church_id=EGQR-123`
2. Page fetches church data
3. Eligibility check fails
4. Friendly message displayed (no form)
5. If user somehow bypasses UI and calls API directly:
   - Server returns `403 { ok: false, error: "church_not_active" }`
   - Donation cannot proceed

## Important Notes

- **Dual enforcement:** Both client-side (UX) and server-side (security)
- **Language support:** Messages in EN/ES based on church `preferred_language`
- **Mobile-first:** Clean, responsive design
- **No bypass:** Server-side check prevents client manipulation
- **Admin override:** Local dev only, cannot be enabled in production

## Troubleshooting

### "Donations Temporarily Unavailable" for Active Church

**Check:**
1. Church `status` = 'active'?
2. `subscription_status` = 'active' or 'trialing'?
3. `stripe_charges_enabled` = true?
4. `stripe_payouts_enabled` = true?

**Query:**
```sql
SELECT 
  church_id,
  status,
  subscription_status,
  stripe_charges_enabled,
  stripe_payouts_enabled
FROM public.churches
WHERE church_id = 'EGQR-123';
```

### Checkout Returns 403

**Solution:**
- Verify all eligibility criteria are met
- Check server logs for specific reason
- Ensure church has completed Stripe Connect onboarding
- Ensure subscription is active or trialing

### Admin Override Not Working

**Check:**
- `ALLOW_DONATIONS_WHEN_INACTIVE=true` in `.env.local`
- `NODE_ENV=development` (not "production")
- Restarted dev server after adding env var
