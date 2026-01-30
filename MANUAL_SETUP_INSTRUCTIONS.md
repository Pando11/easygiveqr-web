# Manual Stripe CLI Setup Instructions

Due to permissions, please follow these manual steps:

## STEP 1: Download and Extract Stripe CLI

1. **Open your browser** and go to:
   ```
   https://github.com/stripe/stripe-cli/releases/latest
   ```

2. **Scroll to "Assets"** section

3. **Download:** `stripe_X.X.X_windows_x86_64.zip` (where X.X.X is the version number)

4. **Extract the ZIP file:**
   - Right-click the downloaded ZIP file
   - Select "Extract All..."
   - Choose a location (we'll use `C:\stripe\`)

5. **Create the directory:**
   - Open File Explorer
   - Navigate to `C:\`
   - Right-click → New → Folder
   - Name it: `stripe`

6. **Copy stripe.exe:**
   - Open the extracted folder from step 4
   - Find `stripe.exe`
   - Copy it to `C:\stripe\`
   - (If stripe.exe is in a subfolder, copy it from there)

---

## STEP 2: Add to PATH

1. **Press `Win + X`** and select **"System"**

2. **Click "Advanced system settings"** (on the right side)

3. **Click "Environment Variables"** button (at the bottom)

4. **Under "User variables"** section:
   - Find **"Path"** in the list
   - Click **"Edit"**

5. **Click "New"** button

6. **Type:** `C:\stripe`

7. **Click "OK"** on all open windows

8. **Close and reopen Command Prompt**

---

## STEP 3: Verify Installation

**Open a NEW Command Prompt and run:**
```cmd
stripe --version
```

**You should see:** `stripe version X.X.X`

**If you see "command not found":**
- Make sure you closed and reopened Command Prompt
- Try restarting your computer
- Verify `C:\stripe\stripe.exe` exists

---

## STEP 4: Continue with Webhook Setup

Once `stripe --version` works, continue with:

**STEP 2 — Log into Stripe:**
```cmd
stripe login
```

**STEP 3 — Start webhook forwarding:**
```cmd
cd "C:\Users\The Yoda Trader\easygiveqr-web"
stripe listen --forward-to http://localhost:3000/api/stripe-webhook
```

**Copy the `whsec_...` secret from the output.**

**STEP 4 — Add to .env.local:**
- Open: `C:\Users\The Yoda Trader\easygiveqr-web\.env.local`
- Add: `STRIPE_WEBHOOK_SECRET=whsec_...`
- Save

**STEP 5 — Restart Next.js:**
```cmd
cd "C:\Users\The Yoda Trader\easygiveqr-web"
npm run dev
```

**STEP 6 — Test:**
- Go to: `http://localhost:3000/donate?church_id=EGQR-123`
- Complete donation with test card: `4242 4242 4242 4242`

**STEP 7 — Confirm:**
- Check Stripe CLI window for `--> checkout.session.completed` and `<-- [200]`
- Check Supabase for new row

---

See `COMPLETE_SETUP_STEPS.md` for full details.
