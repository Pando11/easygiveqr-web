# Exact Setup Steps - Follow These Instructions

## STEP 1: Install Stripe CLI

1. **Go to:**
   ```
   https://github.com/stripe/stripe-cli/releases/latest
   ```

2. **Download:**
   ```
   stripe_X.X.X_windows_x86_64.zip
   ```
   (X.X.X is the version number)

3. **Unzip it:**
   - Right-click the ZIP file
   - Select "Extract All..."
   - Extract to a temporary location

4. **Create directory:**
   - Open File Explorer
   - Go to `C:\`
   - Create new folder: `stripe`
   - Full path: `C:\stripe\`

5. **Copy stripe.exe:**
   - From the extracted folder, find `stripe.exe`
   - Copy it to `C:\stripe\`
   - You should have: `C:\stripe\stripe.exe`

6. **Add to PATH:**
   - Press `Win + X` → System
   - Advanced system settings → Environment Variables
   - Under "User variables", find "Path" → Edit
   - Click "New"
   - Type: `C:\stripe`
   - Click "OK" on all windows

7. **Open a NEW Command Prompt**

8. **Verify:**
   ```cmd
   stripe --version
   ```

9. **If that command works, continue to Step 2.**

---

## STEP 2: Log into Stripe (local machine)

```cmd
stripe login
```

**What happens:**
- Browser opens automatically
- Click "Allow"
- Command Prompt confirms login

✅ **This step does not affect live/test mode — it only authorizes the CLI.**

---

## STEP 3: Start webhook forwarding (this is the key step)

**Open Command Prompt #1 and run:**

```cmd
cd "C:\Users\The Yoda Trader\easygiveqr-web"
stripe listen --forward-to http://localhost:3000/api/stripe-webhook
```

**You should see output like:**
```
Ready! Your webhook signing secret is whsec_12345...
```

**COPY THAT `whsec_...` VALUE**

**Keep this window open!**

---

## STEP 4: Add the webhook secret to .env.local

**Open:**
```
C:\Users\The Yoda Trader\easygiveqr-web\.env.local
```

**Add one new line:**
```
STRIPE_WEBHOOK_SECRET=whsec_12345...
```

**Replace `whsec_12345...` with the actual secret from Step 3.**

**Save the file.**

---

## STEP 5: Restart Next.js (required)

**Close your dev server** (if running) with `Ctrl+C`

**Then restart:**

```cmd
cd "C:\Users\The Yoda Trader\easygiveqr-web"
npm run dev
```

**This is mandatory. Env vars do not hot-reload.**

**Wait for:**
```
✓ Ready in X.Xs
○ Local: http://localhost:3000
```

---

## STEP 6: Trigger a real event

**Go to:**
```
http://localhost:3000/donate?church_id=EGQR-123
```

**Donate:**
- Enter an amount (e.g., 1000 cents = $10.00)
- Click submit/checkout

**Complete checkout:**
- Use test card: `4242 4242 4242 4242`
- Expiry: Any future date (e.g., 12/34)
- CVC: Any 3 digits (e.g., 123)
- ZIP: Any 5 digits (e.g., 12345)
- Click "Pay"

---

## STEP 7: Confirm success (3 places)

### A. Stripe CLI window shows:

**In Command Prompt #1 (where `stripe listen` is running):**

```
--> checkout.session.completed [evt_1ABC...]
<-- [200] http://localhost:3000/api/stripe-webhook [evt_1ABC...]
```

**What this means:**
- `-->` = Event received from Stripe
- `<-- [200]` = Successfully forwarded (200 = HTTP success)

### B. Browser success page loads normally

**You should see your success page at:**
```
http://localhost:3000/donate/success?church_id=EGQR-123&session_id=cs_test_...
```

### C. Supabase shows the row

**In Supabase Dashboard → SQL Editor, run:**

```sql
SELECT *
FROM public.donations
ORDER BY created_at DESC
LIMIT 5;
```

**You should see:**

- `stripe_session_id` = `cs_test_...` or `cs_live_...`
- `amount_cents` = the amount you paid (e.g., 1000)
- `currency` = `usd`
- `status` = `succeeded`
- `church_id` = `EGQR-123`

---

## Troubleshooting

### "stripe: command not found"
- Close and reopen Command Prompt
- Restart computer if needed
- Verify: `C:\stripe\stripe.exe` exists
- Check PATH: `echo %PATH%` should include `C:\stripe`

### "Connection refused"
- Next.js app is not running
- Start it: `npm run dev`

### "Webhook signature verification failed"
- Get new secret from `stripe listen` output
- Update `.env.local`
- **Restart Next.js dev server**

### No events showing
- Make sure `stripe listen` is running
- Make sure Next.js app is running
- Make sure you completed the payment

---

## Quick Command Reference

**Command Prompt #1 - Webhook Listener:**
```cmd
cd "C:\Users\The Yoda Trader\easygiveqr-web"
stripe listen --forward-to http://localhost:3000/api/stripe-webhook
```

**Command Prompt #2 - Next.js Dev Server:**
```cmd
cd "C:\Users\The Yoda Trader\easygiveqr-web"
npm run dev
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

**Follow these steps in order. You're all set!** 🎉
