# Remaining Steps to Complete Setup

## ✅ Already Completed

1. ✅ Stripe CLI downloaded and extracted to `C:\stripe\`
2. ✅ Stripe CLI added to PATH
3. ✅ Stripe CLI verified: `stripe --version` works
4. ✅ Webhook route code updated: `src/app/api/stripe-webhook/route.ts`

---

## ⚠️ Steps You Need to Complete

### Step 1: Login to Stripe CLI

**Open Command Prompt or PowerShell and run:**

```cmd
stripe login
```

**OR if that doesn't work:**

```cmd
C:\stripe\stripe.exe login
```

**What happens:**
- Browser opens automatically
- Click "Allow access"
- Terminal confirms: "Done! The Stripe CLI is configured..."

**Status:** ⏳ **PENDING** - Requires your action

---

### Step 2: Start Webhook Listener

**Open a NEW Command Prompt window (keep it open) and run:**

```cmd
cd "C:\Users\The Yoda Trader\easygiveqr-web"
stripe listen --forward-to http://localhost:3000/api/stripe-webhook
```

**You'll see output like:**
```
> Ready! Your webhook signing secret is whsec_12345...
```

**IMPORTANT:** 
- **Keep this window open**
- **COPY THE `whsec_...` VALUE** - you'll need it in the next step

**Status:** ⏳ **PENDING** - Requires your action

---

### Step 3: Add Webhook Secret to .env.local

**Option A: Automated (Recommended)**

After you get the `whsec_...` secret from Step 2, run:

```powershell
cd "C:\Users\The Yoda Trader\easygiveqr-web"
.\complete-setup.ps1 -WebhookSecret "whsec_12345..."
```

(Replace `whsec_12345...` with your actual secret)

**Option B: Manual**

1. Open: `C:\Users\The Yoda Trader\easygiveqr-web\.env.local`
2. Add this line at the end:
   ```
   STRIPE_WEBHOOK_SECRET=whsec_12345...
   ```
3. Replace `whsec_12345...` with the actual secret from Step 2
4. Save the file

**Current .env.local status:** ❌ **MISSING** `STRIPE_WEBHOOK_SECRET`

---

### Step 4: Restart Next.js Dev Server

**If Next.js is currently running:**
1. Stop it with `Ctrl+C`
2. Restart with:

```cmd
cd "C:\Users\The Yoda Trader\easygiveqr-web"
npm run dev
```

**If Next.js is NOT running:**
```cmd
cd "C:\Users\The Yoda Trader\easygiveqr-web"
npm run dev
```

**Wait for:**
```
✓ Ready in X.Xs
○ Local: http://localhost:3000
```

**Status:** ⏳ **PENDING** - Requires your action

---

### Step 5: Test the Webhook

**Open your browser and go to:**
```
http://localhost:3000/donate?church_id=EGQR-123
```

**Complete the donation:**
1. Fill out the donation form
2. Click submit/checkout
3. Use test card: `4242 4242 4242 4242`
4. Any future expiry date (e.g., 12/34)
5. Any CVC (e.g., 123)
6. Any ZIP (e.g., 12345)
7. Click "Pay"

**Status:** ⏳ **PENDING** - Requires your action

---

### Step 6: Confirm Success (3 Places)

**A. Check Stripe CLI Window**

In the Command Prompt where `stripe listen` is running, you should see:
```
--> checkout.session.completed [evt_1ABC...]
<-- [200] http://localhost:3000/api/stripe-webhook [evt_1ABC...]
```

✅ `-->` = Event received from Stripe  
✅ `<-- [200]` = Successfully forwarded (200 = HTTP success)

**B. Check Browser**

You should see the success page at:
```
http://localhost:3000/donate/success?church_id=EGQR-123&session_id=cs_test_...
```

**C. Check Supabase**

In Supabase Dashboard → SQL Editor, run:

```sql
SELECT * 
FROM public.donations 
ORDER BY created_at DESC 
LIMIT 5;
```

You should see a new row with:
- `stripe_session_id` = `cs_test_...` or `cs_live_...`
- `amount_cents` = the amount you paid
- `currency` = `usd`
- `status` = `succeeded`
- `church_id` = `EGQR-123`

**Status:** ⏳ **PENDING** - Requires your action

---

## Quick Summary

**What's Done:**
- ✅ Stripe CLI installed
- ✅ Webhook route code ready

**What You Need to Do:**
1. ⏳ Run `stripe login`
2. ⏳ Run `stripe listen --forward-to http://localhost:3000/api/stripe-webhook`
3. ⏳ Copy the `whsec_...` secret
4. ⏳ Add `STRIPE_WEBHOOK_SECRET=whsec_...` to `.env.local`
5. ⏳ Restart Next.js: `npm run dev`
6. ⏳ Test at: `http://localhost:3000/donate?church_id=EGQR-123`
7. ⏳ Confirm in Stripe CLI, browser, and Supabase

---

## Quick Command Reference

**Login:**
```cmd
stripe login
```

**Start webhook listener (Window 1):**
```cmd
cd "C:\Users\The Yoda Trader\easygiveqr-web"
stripe listen --forward-to http://localhost:3000/api/stripe-webhook
```

**Start Next.js (Window 2):**
```cmd
cd "C:\Users\The Yoda Trader\easygiveqr-web"
npm run dev
```

**Update .env.local (automated):**
```powershell
.\complete-setup.ps1 -WebhookSecret "whsec_..."
```

**Test URL:**
```
http://localhost:3000/donate?church_id=EGQR-123
```

---

**Next Action:** Start with Step 1 - Run `stripe login` in your terminal!
