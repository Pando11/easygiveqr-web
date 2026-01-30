# Step 20: Per-Church Monthly Donations Flag

## Overview

Add a per-church flag (`monthly_enabled`) to enable/disable monthly recurring donations. When disabled, the monthly option is hidden from the donate page and the API rejects monthly donation requests.

## Database Changes

### Migration

**`supabase/migrations/20260127_add_monthly_enabled_to_churches.sql`**

Adds `monthly_enabled boolean NOT NULL DEFAULT false` to `public.churches`.

```sql
ALTER TABLE public.churches
ADD COLUMN IF NOT EXISTS monthly_enabled boolean NOT NULL DEFAULT false;
```

**Default:** `false` (monthly disabled by default)

## Implementation

### 1. Donate Page (`src/app/donate/page.tsx`)

**Changes:**
- Fetches `monthly_enabled` from church data
- Hides frequency toggle entirely if `monthly_enabled = false`
- Automatically resets frequency to "one_time" if monthly is disabled
- Default frequency remains "one_time"

**Behavior:**
- If `monthly_enabled = false`: Only one-time donations available (no toggle shown)
- If `monthly_enabled = true`: Full toggle with one-time and monthly options

### 2. Checkout API (`src/app/api/checkout-session/route.ts`)

**Changes:**
- Fetches `monthly_enabled` when validating church
- Enforces server-side: If `frequency="monthly"` and `monthly_enabled=false`, returns `403 { ok: false, error: "monthly_not_enabled" }`

**Security:**
- Client-side hiding is for UX only
- Server-side enforcement prevents bypassing the UI

### 3. Church API (`src/app/api/church/route.ts`)

**Changes:**
- Includes `monthly_enabled` in select query
- Donate page can access the flag

### 4. Onboarding (`src/app/api/onboarding/create-church/route.ts`)

**Changes:**
- Accepts optional `monthly_enabled` field in form data
- Parses as boolean (defaults to `false` if not provided)
- Stores in church row on creation

**Form Field:**
- `monthly_enabled`: "true" or "false" (string, optional)
- Defaults to `false` if missing

### 5. Admin Route (`src/app/api/admin/churches/monthly/route.ts`)

**New Route:** `PATCH /api/admin/churches/monthly`

**Request:**
```json
{
  "church_id": "EGQR-123",
  "monthly_enabled": true
}
```

**Response:**
```json
{
  "ok": true,
  "church_id": "EGQR-123",
  "monthly_enabled": true
}
```

**Protection:**
- Requires `x-admin-secret` header
- Returns `401` if missing/invalid

**Validation:**
- `church_id` required
- `monthly_enabled` must be boolean
- Returns `404` if church not found

## Testing

### Test 1: Monthly Disabled (Default)

**Setup:**
```sql
UPDATE public.churches
SET monthly_enabled = false
WHERE church_id = 'EGQR-123';
```

**Steps:**
1. Visit: `http://localhost:3000/donate?church_id=EGQR-123`
2. Observe UI

**Expected:**
- No frequency toggle visible
- Only one-time donation available
- Donate button shows: "Donate $10" (no "/ month")

**API Test:**
```bash
curl -X POST http://localhost:3000/api/checkout-session \
  -H "Content-Type: application/json" \
  -d '{"church_id": "EGQR-123", "amount_cents": 1000, "frequency": "monthly"}'
```

**Expected:**
```json
{
  "ok": false,
  "error": "monthly_not_enabled"
}
```

**Status:** 403

### Test 2: Monthly Enabled

**Setup:**
```sql
UPDATE public.churches
SET monthly_enabled = true
WHERE church_id = 'EGQR-123';
```

**Steps:**
1. Visit: `http://localhost:3000/donate?church_id=EGQR-123`
2. Observe UI

**Expected:**
- Frequency toggle visible
- Both "One-time" and "Monthly" options available
- Can select monthly and complete checkout

**API Test:**
```bash
curl -X POST http://localhost:3000/api/checkout-session \
  -H "Content-Type: application/json" \
  -d '{"church_id": "EGQR-123", "amount_cents": 1000, "frequency": "monthly"}'
```

**Expected:**
```json
{
  "ok": true,
  "url": "https://checkout.stripe.com/..."
}
```

**Status:** 200

### Test 3: Admin Update Route

**Enable Monthly:**
```bash
curl -X PATCH http://localhost:3000/api/admin/churches/monthly \
  -H "Content-Type: application/json" \
  -H "x-admin-secret: YOUR_ADMIN_SECRET" \
  -d '{"church_id": "EGQR-123", "monthly_enabled": true}'
```

**Expected:**
```json
{
  "ok": true,
  "church_id": "EGQR-123",
  "monthly_enabled": true
}
```

**Disable Monthly:**
```bash
curl -X PATCH http://localhost:3000/api/admin/churches/monthly \
  -H "Content-Type: application/json" \
  -H "x-admin-secret: YOUR_ADMIN_SECRET" \
  -d '{"church_id": "EGQR-123", "monthly_enabled": false}'
```

**Expected:**
```json
{
  "ok": true,
  "church_id": "EGQR-123",
  "monthly_enabled": false
}
```

### Test 4: Onboarding with Monthly Enabled

**Form Data:**
```
church_id: EGQR-999
legal_name: Test Church
display_name: Test Church
ein: 12-3456789
preferred_language: EN
primary_color: #1D4ED8
donation_phrase: Support our mission
admin_emails: admin@example.com
monthly_enabled: true
logo: [file]
```

**Expected:**
- Church created with `monthly_enabled = true`
- Donate page shows monthly toggle

### Test 5: Onboarding without Monthly (Default)

**Form Data:**
```
... (same as above, but omit monthly_enabled)
```

**Expected:**
- Church created with `monthly_enabled = false` (default)
- Donate page hides monthly toggle

## API Reference

### PATCH /api/admin/churches/monthly

**Purpose:** Update `monthly_enabled` flag for a church

**Authentication:** `x-admin-secret` header required

**Request Body:**
```json
{
  "church_id": "EGQR-123",
  "monthly_enabled": true
}
```

**Success Response (200):**
```json
{
  "ok": true,
  "church_id": "EGQR-123",
  "monthly_enabled": true
}
```

**Error Responses:**

**400 Bad Request:**
```json
{
  "ok": false,
  "error": "Missing required field: church_id"
}
```

```json
{
  "ok": false,
  "error": "Missing or invalid field: monthly_enabled (must be boolean)"
}
```

**401 Unauthorized:**
```json
{
  "ok": false,
  "error": "Unauthorized: Missing or invalid admin secret"
}
```

**404 Not Found:**
```json
{
  "ok": false,
  "error": "Church not found"
}
```

## Files Created

1. `supabase/migrations/20260127_add_monthly_enabled_to_churches.sql` - Database migration
2. `src/app/api/admin/churches/monthly/route.ts` - Admin update route

## Files Updated

1. `src/app/donate/page.tsx` - Hide monthly toggle when disabled, reset frequency
2. `src/app/api/checkout-session/route.ts` - Server-side enforcement
3. `src/app/api/church/route.ts` - Include `monthly_enabled` in response
4. `src/app/api/onboarding/create-church/route.ts` - Accept and store `monthly_enabled`

## Important Notes

- **Default:** `monthly_enabled = false` (monthly disabled by default)
- **Server-side enforcement:** API rejects monthly donations if disabled (prevents UI bypass)
- **Client-side UX:** Toggle hidden when disabled (cleaner UI)
- **Automatic reset:** If monthly is disabled and user had selected monthly, frequency resets to one-time
- **Onboarding:** Optional field, defaults to `false` if not provided

## Migration Instructions

1. Apply the SQL migration to your Supabase database:
   ```sql
   -- Run the migration file
   ALTER TABLE public.churches
   ADD COLUMN IF NOT EXISTS monthly_enabled boolean NOT NULL DEFAULT false;
   ```

2. Verify the column was added:
   ```sql
   SELECT church_id, monthly_enabled FROM public.churches LIMIT 5;
   ```

3. All existing churches will have `monthly_enabled = false` by default.

## Troubleshooting

### Monthly Toggle Not Hiding

**Check:**
- `monthly_enabled` is `false` in database
- `/api/church` returns `monthly_enabled` field
- Donate page is fetching church data correctly

### API Still Accepts Monthly When Disabled

**Check:**
- Checkout API is fetching `monthly_enabled` field
- Server-side validation is running before checkout creation
- Error response is `403` with `"monthly_not_enabled"`

### Admin Route Returns 401

**Check:**
- `x-admin-secret` header is present
- Header value matches `ADMIN_SECRET` environment variable
- Route is using `requireAdminSecret()` correctly
