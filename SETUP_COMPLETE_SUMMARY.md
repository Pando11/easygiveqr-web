# Setup Complete - Summary

## ✅ Completed Automatically

1. **Stripe CLI Downloaded** ✓
   - Downloaded: `stripe_1.34.0_windows_x86_64.zip`
   - Version: 1.34.0

2. **Stripe CLI Extracted** ✓
   - Location: `C:\stripe\stripe.exe`

3. **Added to PATH** ✓
   - `C:\stripe` added to user PATH environment variable

4. **Verified Installation** ✓
   - `stripe --version` works: `stripe version 1.34.0`

---

## ⚠️ Manual Steps Required

### Step 1: Login to Stripe

**Run:**
```cmd
stripe login
```

**Action:**
- Browser opens automatically
- Click "Allow access"
- Command Prompt confirms login

---

### Step 2: Start Webhook Listener

**Open Command Prompt #1:**
```cmd
cd "C:\Users\The Yoda Trader\easygiveqr-web"
stripe listen --forward-to http://localhost:3000/api/stripe-webhook
```

**You'll see:**
```
> Ready! Your webhook signing secret is whsec_12345...
```

**COPY THE `whsec_...` VALUE**

**Keep this window open!**

---

### Step 3: Add Webhook Secret to .env.local

**Option A: Automated (Recommended)**

Run this script with your webhook secret:
```powershell
cd "C:\Users\The Yoda Trader\easygiveqr-web"
.\complete-setup.ps1 -WebhookSecret "whsec_12345..."
```

**Option B: Manual**

1. Open: `C:\Users\The Yoda Trader\easygiveqr-web\.env.local`
2. Add line: `STRIPE_WEBHOOK_SECRET=whsec_12345...`
3. Save file

---

### Step 4: Restart Next.js

**If running, stop it (Ctrl+C), then:**
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

### Step 5: Test

**Go to:**
```
http://localhost:3000/donate?church_id=EGQR-123
```

**Complete donation:**
- Fill form
- Use test card: `4242 4242 4242 4242`
- Complete payment

---

### Step 6: Confirm Success

**Check 3 places:**

**A. Stripe CLI (Command Prompt #1):**
```
--> checkout.session.completed [evt_...]
<-- [200] http://localhost:3000/api/stripe-webhook [evt_...]
```

**B. Browser:** Success page loads

**C. Supabase SQL:**
```sql
SELECT * FROM public.donations ORDER BY created_at DESC LIMIT 5;
```

Should show new row with:
- `stripe_session_id`
- `amount_cents`
- `currency = usd`
- `status = succeeded`
- `church_id = EGQR-123`

---

## Quick Commands

**Login:**
```cmd
stripe login
```

**Start webhook listener:**
```cmd
stripe listen --forward-to http://localhost:3000/api/stripe-webhook
```

**Update .env.local (automated):**
```powershell
.\complete-setup.ps1 -WebhookSecret "whsec_..."
```

**Start Next.js:**
```cmd
npm run dev
```

**Test URL:**
```
http://localhost:3000/donate?church_id=EGQR-123
```

---

## Files Created

- `complete-setup.ps1` - Automation script
- `capture-webhook-secret.ps1` - Webhook secret helper
- `start-webhook-listener.ps1` - Webhook listener starter
- `SETUP_STATUS.md` - Detailed status
- `SETUP_COMPLETE_SUMMARY.md` - This file

---

**Next Action:** Run `stripe login` to continue!
