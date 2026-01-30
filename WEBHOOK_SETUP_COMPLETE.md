# ✅ Stripe Webhook Setup - Complete Instructions

## Files Created

1. **`start-stripe-webhooks.ps1`** - PowerShell script to start webhook forwarding
2. **`start-stripe-webhooks.bat`** - Batch file alternative (double-click to run)
3. **`test-stripe-webhook.ps1`** - Script to send test events
4. **`QUICK_START.txt`** - Quick reference card

## Setup Steps

### 1. Install Stripe CLI (if not done)
```powershell
# See: C:\Users\The Yoda Trader\INSTALL_STRIPE_CLI_NOW.md
```

### 2. Login to Stripe
```powershell
stripe login
```

### 3. Start Webhook Forwarding

**In Terminal 1:**
```powershell
cd "C:\Users\The Yoda Trader\easygiveqr-web"
.\start-stripe-webhooks.ps1
```

**You'll see output like:**
```
> Ready! Your webhook signing secret is whsec_xxxxxxxxxxxxx
```

### 4. Add Webhook Secret to .env.local

**Copy the `whsec_xxxxx` secret** from step 3, then add this line to `.env.local`:

```
STRIPE_WEBHOOK_SECRET=whsec_xxxxxxxxxxxxx
```

**Your `.env.local` should now have:**
```
SUPABASE_URL=...
SUPABASE_SERVICE_ROLE_KEY=...
STRIPE_PUBLISHABLE_KEY=...
STRIPE_SECRET_KEY=...
STRIPE_WEBHOOK_SECRET=whsec_xxxxxxxxxxxxx  ← ADD THIS
```

### 5. Start Your Next.js App

**In Terminal 2:**
```powershell
cd "C:\Users\The Yoda Trader\easygiveqr-web"
npm run dev
```

### 6. Test Webhook

**In Terminal 3:**
```powershell
cd "C:\Users\The Yoda Trader\easygiveqr-web"
.\test-stripe-webhook.ps1
```

---

## How to Confirm Events Are Received

### ✅ Check Stripe CLI Output (Terminal 1)

You should see:
```
--> checkout.session.completed [evt_1ABC...]
<-- [200] http://localhost:3000/api/stripe-webhook [evt_1ABC...]
```

- `-->` = Event received from Stripe
- `<-- [200]` = Successfully forwarded to your app (200 = success)

### ✅ Check Next.js Console (Terminal 2)

Look for any console.log output or errors in your Next.js app.

### ✅ Check Database

Check your Supabase `donations` table - a new record should appear for successful `checkout.session.completed` events.

### ✅ Check Browser DevTools

1. Open `http://localhost:3000` in your browser
2. Press F12 to open DevTools
3. Go to Network tab
4. Filter by "stripe-webhook"
5. Trigger a test event and watch for the request

---

## Common Commands

**Start webhook forwarding:**
```powershell
stripe listen --forward-to http://localhost:3000/api/stripe-webhook
```

**Send test event:**
```powershell
stripe trigger checkout.session.completed
```

**View recent events:**
```powershell
stripe events list
```

**View specific event:**
```powershell
stripe events retrieve evt_xxxxx
```

---

## Troubleshooting

### "stripe: command not found"
- Stripe CLI not installed or not in PATH
- Restart terminal/computer after installation

### "Connection refused"
- Next.js app not running
- Start with: `npm run dev`

### "Webhook signature verification failed"
- `STRIPE_WEBHOOK_SECRET` in `.env.local` doesn't match
- Get new secret from `stripe listen` output
- Restart Next.js app after updating `.env.local`

### No events showing
- Make sure `stripe listen` is running
- Make sure Next.js app is running
- Try: `stripe trigger checkout.session.completed`

---

## What Your Webhook Handler Does

Your `src/app/api/stripe-webhook/route.ts`:
- ✅ Verifies webhook signature
- ✅ Handles `checkout.session.completed` events
- ✅ Creates donation record in Supabase
- ✅ Returns 200 for other events (acknowledged but ignored)

---

## Quick Test Workflow

1. **Terminal 1:** `.\start-stripe-webhooks.ps1`
2. **Terminal 2:** `npm run dev`
3. **Terminal 3:** `.\test-stripe-webhook.ps1`
4. **Check Terminal 1** for `-->` and `<-- [200]` messages
5. **Check Terminal 2** for any app logs
6. **Check Supabase** for new donation record

---

**That's it! Your webhooks are now forwarding to your local app.** 🎉
