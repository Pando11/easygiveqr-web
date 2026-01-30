# Step 7B: Stripe Webhook Testing Guide

This guide provides exact commands for Windows to test the Stripe webhook integration.

## Prerequisites

- Stripe CLI installed and in PATH
- Next.js app running on `http://localhost:3000`
- Environment variables configured in `.env.local`:
  - `STRIPE_SECRET_KEY`
  - `STRIPE_WEBHOOK_SECRET`
  - `SUPABASE_URL`
  - `SUPABASE_SERVICE_ROLE_KEY`

## Step 1: Login to Stripe CLI

**Open Command Prompt or PowerShell and run:**

```cmd
stripe login
```

**What happens:**
- Browser opens automatically
- Click "Allow access" in the browser
- Terminal confirms: "Done! The Stripe CLI is configured for [your account]"

✅ This step does not affect live/test mode — it only authorizes the CLI.

---

## Step 2: Start Webhook Forwarding

**Open Command Prompt #1 (keep this window open) and run:**

```cmd
cd "C:\Users\The Yoda Trader\easygiveqr-web"
stripe listen --forward-to http://localhost:3000/api/stripe-webhook
```

**You should see output like:**

```
> Ready! Your webhook signing secret is whsec_12345...
```

**IMPORTANT:**
- **Keep this window open** — this is your webhook listener
- **Copy the `whsec_...` value** — you'll need it for `.env.local`
- If you restart this command, you'll get a new secret — update `.env.local` accordingly

---

## Step 3: Configure Webhook Secret

**Add to `.env.local`:**

```
STRIPE_WEBHOOK_SECRET=whsec_12345...
```

(Replace `whsec_12345...` with the actual secret from Step 2)

**Restart Next.js dev server** after updating `.env.local` (env vars don't hot-reload).

---

## Step 4: Start Next.js Dev Server

**Open Command Prompt #2 and run:**

```cmd
cd "C:\Users\The Yoda Trader\easygiveqr-web"
npm run dev
```

**Wait for:**

```
✓ Ready in X.Xs
○ Local: http://localhost:3000
```

---

## Step 5: Trigger a checkout.session.completed Event

### Option A: Complete a Real Donation (Recommended)

**Open your browser and go to:**

```
http://localhost:3000/donate?church_id=EGQR-123
```

**Complete the donation:**

1. Fill out the donation form (enter an amount in cents, e.g., 1000 = $10.00)
2. Click submit/checkout
3. In Stripe Checkout, use test card:
   - Card number: `4242 4242 4242 4242`
   - Expiry: Any future date (e.g., 12/34)
   - CVC: Any 3 digits (e.g., 123)
   - ZIP: Any 5 digits (e.g., 12345)
4. Click "Pay"
5. You'll be redirected to the success page

### Option B: Use Stripe CLI Test Event

**In a new Command Prompt, run:**

```cmd
stripe trigger checkout.session.completed
```

**Note:** This creates a test event but may not have the `church_id` in metadata, so it may return 400.

---

## Step 6: Confirm Success

### A. Check Stripe CLI Output (Command Prompt #1)

**You should see:**

```
--> checkout.session.completed [evt_1ABC...]
<-- [200] http://localhost:3000/api/stripe-webhook [evt_1ABC...]
```

**What this means:**
- `-->` = Event received from Stripe
- `<-- [200]` = Successfully forwarded to your app (200 = HTTP success)
- If you see `[400]` or `[500]`, check your Next.js console for errors

### B. Check Next.js Console (Command Prompt #2)

**You should see logs like:**

```
[Stripe Webhook] Received event: checkout.session.completed (evt_1ABC...)
[Stripe Webhook] Successfully processed donation: cs_test_... for church EGQR-123, amount: 1000 usd
```

**If you see errors, they'll be logged here (without exposing secrets).**

### C. Check Supabase Database

**In Supabase Dashboard → SQL Editor, run:**

```sql
SELECT *
FROM public.donations
ORDER BY created_at DESC
LIMIT 5;
```

**You should see a new row with:**

- `stripe_session_id` = `cs_test_...` or `cs_live_...`
- `church_id` = `EGQR-123` (or the church_id you used)
- `amount_cents` = the amount you paid (e.g., 1000)
- `currency` = `usd`
- `status` = `succeeded`

---

## Troubleshooting

### Problem: "stripe: command not found"

**Solution:**
1. Close and reopen Command Prompt
2. If still not working, restart computer
3. Verify: `C:\stripe\stripe.exe` exists
4. Check PATH: `echo %PATH%` should include `C:\stripe`

### Problem: "Connection refused" in stripe listen

**Solution:**
- Your Next.js app is not running
- Start it with: `npm run dev` in Command Prompt #2
- Make sure it's running on `http://localhost:3000`

### Problem: "Webhook signature verification failed"

**Solution:**
1. Get the current webhook secret from `stripe listen` output
2. Update `STRIPE_WEBHOOK_SECRET` in `.env.local`
3. **Restart your Next.js dev server** (stop with Ctrl+C, then `npm run dev` again)

### Problem: "[400] Missing required field: church_id"

**Solution:**
- The checkout session doesn't have `church_id` in metadata or `client_reference_id`
- Make sure your checkout session creation includes:
  ```typescript
  metadata: { church_id: "EGQR-123" }
  ```
  OR
  ```typescript
  client_reference_id: "EGQR-123"
  ```

### Problem: Event received but no database row

**Check:**
1. Next.js console for errors
2. Supabase connection (verify `SUPABASE_URL` and `SUPABASE_SERVICE_ROLE_KEY`)
3. Database permissions (service role should have insert/update permissions)
4. Table schema matches (columns: `church_id`, `stripe_session_id`, `amount_cents`, `currency`, `status`)

---

## Quick Command Reference

**Login to Stripe:**
```cmd
stripe login
```

**Start webhook listener:**
```cmd
stripe listen --forward-to http://localhost:3000/api/stripe-webhook
```

**Start Next.js:**
```cmd
npm run dev
```

**Trigger test event:**
```cmd
stripe trigger checkout.session.completed
```

**Test URL:**
```
http://localhost:3000/donate?church_id=EGQR-123
```

**SQL Query:**
```sql
SELECT * FROM public.donations ORDER BY created_at DESC LIMIT 5;
```

---

## Success Checklist

- [ ] Stripe CLI installed and working
- [ ] `stripe login` completed
- [ ] `stripe listen` running and showing webhook secret
- [ ] `STRIPE_WEBHOOK_SECRET` added to `.env.local`
- [ ] Next.js dev server running on `http://localhost:3000`
- [ ] Created checkout session from donate page
- [ ] Completed payment with test card
- [ ] Stripe CLI shows `--> checkout.session.completed` and `<-- [200]`
- [ ] Next.js console shows success log
- [ ] Row exists in Supabase `donations` table

---

**You're all set! Your webhooks are now forwarding to your local app.** 🎉
