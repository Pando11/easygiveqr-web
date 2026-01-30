# Final Setup Steps - Complete Now

Since you've logged in to Stripe, follow these steps:

## Step 1: Start Webhook Listener

**Open Command Prompt #1 and run:**

```cmd
cd "C:\Users\The Yoda Trader\easygiveqr-web"
stripe listen --forward-to http://localhost:3000/api/stripe-webhook
```

**You'll see output like:**
```
> Ready! Your webhook signing secret is whsec_12345...
```

**COPY THE `whsec_...` VALUE**

**Keep this window open!**

---

## Step 2: Update .env.local with Secret

**Option A: Automated (Recommended)**

After you copy the `whsec_...` secret, run this in a NEW PowerShell window:

```powershell
cd "C:\Users\The Yoda Trader\easygiveqr-web"
.\update-webhook-secret.ps1 -Secret "whsec_12345..."
```

(Replace `whsec_12345...` with your actual secret)

**Option B: Manual**

1. Open: `C:\Users\The Yoda Trader\easygiveqr-web\.env.local`
2. Add this line at the end:
   ```
   STRIPE_WEBHOOK_SECRET=whsec_12345...
   ```
3. Replace `whsec_12345...` with your actual secret
4. Save the file

---

## Step 3: Restart Next.js

**If Next.js is running, stop it (Ctrl+C), then:**

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

## Step 4: Test

**Open browser and go to:**
```
http://localhost:3000/donate?church_id=EGQR-123
```

**Complete donation:**
- Fill form
- Use test card: `4242 4242 4242 4242`
- Complete payment

---

## Step 5: Confirm Success

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

---

## Quick Commands

**Start webhook listener:**
```cmd
stripe listen --forward-to http://localhost:3000/api/stripe-webhook
```

**Update .env.local (automated):**
```powershell
.\update-webhook-secret.ps1 -Secret "whsec_..."
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

**You're almost done! Just follow Steps 1-5 above.**
