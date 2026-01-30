# Quick Complete Setup

Since `stripe listen` is running, follow these steps:

## Step 1: Get the Webhook Secret

**Look at your `stripe listen` window.** You should see a line like:
```
> Ready! Your webhook signing secret is whsec_12345...
```

**Copy the entire `whsec_...` value** (everything after "whsec_")

---

## Step 2: Update .env.local

**Run this command** (replace `whsec_...` with your actual secret):

```powershell
cd "C:\Users\The Yoda Trader\easygiveqr-web"
.\complete-with-secret.ps1 -Secret "whsec_12345..."
```

**OR manually:**
1. Open `.env.local`
2. Add: `STRIPE_WEBHOOK_SECRET=whsec_12345...`
3. Save

---

## Step 3: Restart Next.js

**If Next.js is running:**
1. Stop it (Ctrl+C)
2. Restart: `npm run dev`

**If Next.js is NOT running:**
```cmd
npm run dev
```

---

## Step 4: Test

**Go to:**
```
http://localhost:3000/donate?church_id=EGQR-123
```

**Complete donation with test card:** `4242 4242 4242 4242`

---

## Step 5: Confirm

**Check Stripe CLI window:**
- Should show: `--> checkout.session.completed`
- Should show: `<-- [200]`

**Check Supabase:**
```sql
SELECT * FROM public.donations ORDER BY created_at DESC LIMIT 5;
```

---

**That's it! You're done!** 🎉
