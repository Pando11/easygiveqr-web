# Stripe Webhook Setup Status

## ✅ Completed Steps

1. **Stripe CLI Downloaded** ✓
   - Version: 1.34.0
   - Location: `C:\stripe\stripe.exe`

2. **Stripe CLI Extracted** ✓
   - Extracted to: `C:\stripe\`

3. **Added to PATH** ✓
   - `C:\stripe` added to user PATH

4. **Verified Installation** ✓
   - `stripe --version` works: `stripe version 1.34.0`

---

## ⚠️ Steps Requiring Your Action

### Step 5: Login to Stripe

**Run this command:**
```cmd
stripe login
```

**What will happen:**
- Browser opens automatically
- Click "Allow access" in the browser
- Command Prompt will confirm: "Done! The Stripe CLI is configured..."

**After login, continue to Step 6.**

---

### Step 6: Start Webhook Listener

**Open a NEW Command Prompt window and run:**
```cmd
cd "C:\Users\The Yoda Trader\easygiveqr-web"
stripe listen --forward-to http://localhost:3000/api/stripe-webhook
```

**You'll see output like:**
```
> Ready! Your webhook signing secret is whsec_12345...
```

**COPY THAT `whsec_...` VALUE**

**Keep this window open!**

---

### Step 7: Add Webhook Secret to .env.local

**I'll update this automatically once you provide the secret, OR you can:**

1. Open: `C:\Users\The Yoda Trader\easygiveqr-web\.env.local`
2. Add this line:
   ```
   STRIPE_WEBHOOK_SECRET=whsec_12345...
   ```
3. Replace `whsec_12345...` with the actual secret from Step 6
4. Save the file

---

### Step 8: Restart Next.js

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

### Step 9: Test the Webhook

1. **Go to:** `http://localhost:3000/donate?church_id=EGQR-123`
2. **Fill out donation form** and complete checkout
3. **Use test card:** `4242 4242 4242 4242`
4. **Complete payment**

---

### Step 10: Confirm Success

**Check 3 places:**

**A. Stripe CLI window shows:**
```
--> checkout.session.completed [evt_...]
<-- [200] http://localhost:3000/api/stripe-webhook [evt_...]
```

**B. Browser shows success page**

**C. Supabase has the row:**
```sql
SELECT * FROM public.donations ORDER BY created_at DESC LIMIT 5;
```

---

## Quick Command Reference

**Login:**
```cmd
stripe login
```

**Start webhook listener:**
```cmd
cd "C:\Users\The Yoda Trader\easygiveqr-web"
stripe listen --forward-to http://localhost:3000/api/stripe-webhook
```

**Start Next.js:**
```cmd
cd "C:\Users\The Yoda Trader\easygiveqr-web"
npm run dev
```

**Test URL:**
```
http://localhost:3000/donate?church_id=EGQR-123
```

---

**Next Action:** Run `stripe login` to continue setup.
