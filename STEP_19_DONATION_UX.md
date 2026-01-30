# Step 19: Donation Page UX Upgrade

## Overview

Upgrade the donation page UX with preset amounts, frequency toggle, and full language support (EN/ES) while maintaining eligibility gating.

## Features

### Preset Amounts

- **$5** (500 cents)
- **$10** (1000 cents) - Default
- **$25** (2500 cents)
- **$50** (5000 cents)

Only these preset amounts are allowed. Server validates and rejects invalid amounts.

### Frequency Toggle

- **One-time:** Single payment (mode="payment")
- **Monthly:** Recurring subscription (mode="subscription")

Monthly donations create a Stripe subscription that charges monthly.

### Language Support

All donor-facing text is translated based on `church.preferred_language`:
- Page headings
- Button labels
- Error messages
- Success/cancel pages
- Frequency labels

**Languages:** English (EN) and Spanish (ES)

### Church Branding

- Church logo (if available)
- Church display name
- Donation phrase
- Primary color used for buttons and highlights

## Implementation

### Constants

**`src/lib/donationConstants.ts`**
- `DONATION_PRESETS` - Array of allowed amounts [500, 1000, 2500, 5000]
- `isValidPresetAmount()` - Validates amount is a preset
- `DonationFrequency` type - "one_time" | "monthly"

### Translations

**`src/lib/donationTranslations.ts`**
- `getDonationTranslations()` - Returns EN/ES translations object
- All donor-facing strings in both languages
- Used by donate page, success page, cancel page

### Stripe Prices

**`src/lib/stripePrices.ts`**
- `getOrCreateDonationPrice()` - Creates or retrieves Stripe price for monthly donations
- Automatically creates prices for each preset amount if they don't exist
- Prices are marked with `metadata.donation = "true"` for identification

### Donate Page

**`src/app/donate/page.tsx`** (completely rewritten)
- Preset amount buttons (2x2 grid)
- Selected amount highlighted with primary color
- Frequency toggle (one-time vs monthly)
- Church branding (logo, name, phrase, color)
- Language-aware text
- Eligibility gating (shows message if not eligible)
- Mobile-first, clean design

### Checkout API

**`src/app/api/checkout-session/route.ts`** (updated)
- Accepts `amount_cents` and `frequency` in request body
- Validates `amount_cents` is a preset (returns 400 if invalid)
- Validates `frequency` is "one_time" or "monthly"
- Creates payment checkout for one-time
- Creates subscription checkout for monthly
- Includes metadata: `church_id`, `frequency`, `amount_cents`

### Success/Cancel Pages

**`src/app/donate/success/page.tsx`** (updated)
- Fetches church to get `preferred_language`
- All text uses translations
- Maintains verified success behavior (reads from DB)

**`src/app/donate/cancel/page.tsx`** (updated)
- Fetches church to get `preferred_language`
- All text uses translations

## API Changes

### Checkout Session Request

**Before:**
```json
{
  "amount": 1000,
  "church_id": "EGQR-123"
}
```

**After:**
```json
{
  "church_id": "EGQR-123",
  "amount_cents": 1000,
  "frequency": "one_time"
}
```

**Or for monthly:**
```json
{
  "church_id": "EGQR-123",
  "amount_cents": 2500,
  "frequency": "monthly"
}
```

### Checkout Session Response

**Success:**
```json
{
  "ok": true,
  "url": "https://checkout.stripe.com/..."
}
```

**Error (Invalid Amount):**
```json
{
  "ok": false,
  "error": "invalid_amount"
}
```

**Error (Church Not Active):**
```json
{
  "ok": false,
  "error": "church_not_active"
}
```

## Testing

### Test 1: EN Church - One-time $5

**Setup:**
```sql
UPDATE public.churches
SET 
  status = 'active',
  subscription_status = 'active',
  stripe_charges_enabled = true,
  stripe_payouts_enabled = true,
  preferred_language = 'EN'
WHERE church_id = 'EGQR-123';
```

**Steps:**
1. Visit: `http://localhost:3000/donate?church_id=EGQR-123`
2. Select $5 button
3. Select "One-time"
4. Click "Donate $5"
5. Complete checkout

**Expected:**
- Page shows in English
- $5 button highlighted
- One-time selected
- Checkout completes successfully

### Test 2: ES Church - One-time $10

**Setup:**
```sql
UPDATE public.churches
SET preferred_language = 'ES'
WHERE church_id = 'EGQR-123';
```

**Steps:**
1. Visit: `http://localhost:3000/donate?church_id=EGQR-123`
2. Select $10 button
3. Select "Una vez" (One-time)
4. Click "Donar $10"
5. Complete checkout

**Expected:**
- Page shows in Spanish
- All text in Spanish
- Checkout completes successfully

### Test 3: Monthly Donation $25

**Steps:**
1. Visit: `http://localhost:3000/donate?church_id=EGQR-123`
2. Select $25 button
3. Select "Monthly" / "Mensual"
4. Click "Donate $25 / month" / "Donar $25 / mes"
5. Complete checkout

**Expected:**
- Creates Stripe subscription
- Charges monthly going forward
- Success page shows in correct language

### Test 4: Invalid Amount Rejected

**Using curl:**
```bash
curl -X POST http://localhost:3000/api/checkout-session \
  -H "Content-Type: application/json" \
  -d '{"church_id": "EGQR-123", "amount_cents": 750, "frequency": "one_time"}'
```

**Expected:**
```json
{
  "ok": false,
  "error": "invalid_amount"
}
```

**Status:** 400

### Test 5: Inactive Church Blocked

**Setup:**
```sql
UPDATE public.churches SET status = 'pending' WHERE church_id = 'EGQR-123';
```

**Steps:**
1. Visit: `http://localhost:3000/donate?church_id=EGQR-123`

**Expected:**
- Page shows "Donations Temporarily Unavailable" message
- No donation form displayed
- Message in church's preferred language

**API Test:**
```bash
curl -X POST http://localhost:3000/api/checkout-session \
  -H "Content-Type: application/json" \
  -d '{"church_id": "EGQR-123", "amount_cents": 1000, "frequency": "one_time"}'
```

**Expected:**
```json
{
  "ok": false,
  "error": "church_not_active"
}
```

**Status:** 403

## Monthly Donations with Stripe Connect

### Current Implementation

For monthly donations:
- Creates subscription on platform account
- Subscription metadata includes `church_id`, `frequency`, `amount_cents`
- **Note:** Full Connect destination charges for subscriptions require creating the subscription on the connected account, which is more complex. For v1, subscriptions are created on the platform account.

### Future Enhancement

To fully support Connect for monthly donations:
1. Create customer on connected account
2. Create subscription on connected account
3. Handle webhook events for subscription payments

For now, the subscription is created with metadata for tracking, and funds can be transferred via other means if needed.

## UI Components

### Amount Selection

- 2x2 grid of preset buttons
- Selected button highlighted with primary color
- Unselected buttons have white background with gray border
- Hover effects for better UX

### Frequency Toggle

- Toggle-style buttons
- Selected option has white background with shadow
- Unselected option is transparent
- Smooth transitions

### Donate Button

- Full width
- Uses church primary color
- Shows selected amount and frequency
- Disabled state during loading

## Language Dictionary

### English (EN)

- Page title: "Donate"
- Select amount: "Select Amount"
- Frequency: "Frequency"
- One-time: "One-time"
- Monthly: "Monthly"
- Donate button: "Donate"
- And more...

### Spanish (ES)

- Page title: "Donar"
- Select amount: "Seleccionar Cantidad"
- Frequency: "Frecuencia"
- One-time: "Una vez"
- Monthly: "Mensual"
- Donate button: "Donar"
- And more...

## Files Created

1. `src/lib/donationConstants.ts` - Preset amounts and validation
2. `src/lib/donationTranslations.ts` - EN/ES translations
3. `src/lib/stripePrices.ts` - Stripe price creation for monthly donations

## Files Updated

1. `src/app/donate/page.tsx` - Complete rewrite with new UX
2. `src/app/api/checkout-session/route.ts` - Added frequency and amount validation
3. `src/app/donate/success/page.tsx` - Added language support
4. `src/app/donate/cancel/page.tsx` - Added language support

## Important Notes

- **Preset amounts only:** Only $5, $10, $25, $50 are allowed
- **Server-side validation:** Invalid amounts return 400
- **Language support:** All text based on `church.preferred_language`
- **Monthly subscriptions:** Creates Stripe subscription (Connect integration may need enhancement)
- **Eligibility gating:** Still enforced (active + subscribed + Connect enabled)
- **Mobile-first:** Responsive design for all screen sizes

## Troubleshooting

### "invalid_amount" Error

**Cause:** Amount is not one of the presets [500, 1000, 2500, 5000]

**Solution:** Use one of the preset amounts

### Monthly Subscription Not Working

**Check:**
- Stripe price was created successfully
- Webhook is processing subscription events
- Subscription metadata includes `church_id`

### Language Not Changing

**Check:**
- `church.preferred_language` is set to "EN" or "ES"
- Page is fetching church data correctly
- Translations are being applied

### Preset Buttons Not Highlighting

**Check:**
- `selectedAmount` state is set correctly
- Primary color is valid hex color
- CSS styles are applied
