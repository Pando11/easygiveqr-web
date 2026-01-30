# Stripe Webhook Setup Guide

## Quick Start

### 1. Install Stripe CLI (if not already installed)
See: `C:\Users\The Yoda Trader\INSTALL_STRIPE_CLI_NOW.md`

### 2. Login to Stripe
```powershell
stripe login
```
This opens a browser to authenticate. Follow the prompts.

### 3. Start Webhook Forwarding

**Option A: Use the script**
```powershell
.\start-stripe-webhooks.ps1
```

**Option B: Manual command**
```powershell
stripe listen --forward-to http://localhost:3000/api/stripe-webhook
```

### 4. Get Your Webhook Signing Secret

When you run `stripe listen`, you'll see output like:
```
> Ready! Your webhook signing secret is whsec_xxxxxxxxxxxxx
```

**Copy this secret** - you'll need it for your `.env.local` file.

### 5. Add to Environment Variables

Add this to your `.env.local` file in the `easygiveqr-web` folder:
```
STRIPE_WEBHOOK_SECRET=whsec_xxxxxxxxxxxxx
```

**Important:** The webhook secret changes each time you restart `stripe listen`. Make sure to update your `.env.local` if you restart.

### 6. Start Your Next.js App

In a separate terminal:
```powershell
cd easygiveqr-web
npm run dev
```

Your app should be running on `http://localhost:3000`

---

## Testing Webhooks

### Test 1: Send a Test Event

**While `stripe listen` is running**, open a new terminal and run:
```powershell
.\test-stripe-webhook.ps1
```

Or manually:
```powershell
stripe trigger checkout.session.completed
```

### Test 2: Confirm Events Are Received

**Check these places:**

1. **Stripe CLI Output** - You should see:
   ```
   --> checkout.session.completed [evt_xxxxx]
   <-- [200] http://localhost:3000/api/stripe-webhook [evt_xxxxx]
   ```

2. **Next.js Console** - Check your terminal where `npm run dev` is running for any logs

3. **Browser DevTools** - Open Network tab and look for requests to `/api/stripe-webhook`

4. **Database** - Check your Supabase `donations` table for new entries

---

## Troubleshooting

### Problem: "stripe: command not found"
- Stripe CLI is not installed or not in PATH
- Close and reopen your terminal
- If still not working, restart your computer

### Problem: "Connection refused" or "ECONNREFUSED"
- Your Next.js app is not running
- Start it with: `npm run dev` in the `easygiveqr-web` folder
- Make sure it's running on `http://localhost:3000`

### Problem: "Webhook signature verification failed"
- Your `STRIPE_WEBHOOK_SECRET` in `.env.local` doesn't match
- Get the new secret from `stripe listen` output (starts with `whsec_`)
- Update `.env.local` and restart your Next.js app

### Problem: No events showing up
- Make sure `stripe listen` is running
- Make sure your Next.js app is running
- Try sending a test event: `stripe trigger checkout.session.completed`

---

## Quick Reference

**Start webhook forwarding:**
```powershell
stripe listen --forward-to http://localhost:3000/api/stripe-webhook
```

**Send test event:**
```powershell
stripe trigger checkout.session.completed
```

**View webhook events:**
```powershell
stripe events list
```

**View specific event:**
```powershell
stripe events retrieve evt_xxxxx
```

---

## What Events Are Handled

Your webhook handler (`route.ts`) currently handles:
- `checkout.session.completed` - Creates donation record in Supabase

All other events are acknowledged but ignored.
