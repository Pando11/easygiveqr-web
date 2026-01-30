# SendGrid Sender Verification

## Why This Matters

**Unverified senders get marked as spam. Your emails won't reach churches.**

## Step-by-Step Setup

### 1. Domain Verification (Recommended)

1. Go to SendGrid Dashboard → Settings → Sender Authentication
2. Click **"Authenticate Your Domain"**
3. Follow instructions to add DNS records:
   - Add CNAME records to your DNS provider
   - Wait for verification (can take up to 48 hours)
4. Verify domain shows as **"Verified"**

### 2. Single Sender Verification (Alternative)

If domain verification is not possible:

1. Go to SendGrid Dashboard → Settings → Sender Authentication
2. Click **"Verify a Single Sender"**
3. Enter:
   - **From Email:** `helping@easygiveqr.net`
   - **From Name:** `EasyGiveQR`
   - **Reply To:** `helping@easygiveqr.net`
4. Click **"Create"**
5. Check email inbox for verification link
6. Click verification link in email
7. Verify sender shows as **"Verified"**

### 3. Test Email in Production

1. Use admin endpoint to send test email:
   ```bash
   curl -X POST https://easygiveqr.net/api/admin/email-test \
     -H "x-admin-secret: YOUR_SECRET" \
     -H "Content-Type: application/json" \
     -d '{"to": "your-email@example.com", "language": "EN"}'
   ```

2. Or use SendGrid Dashboard → Email API → Send Test Email

### 4. Verify Email Delivery

1. Check recipient inbox (not spam folder)
2. Verify:
   - ✅ Email delivered (not bounced)
   - ✅ Sender is exactly `helping@easygiveqr.net`
   - ✅ Correct EN/ES template used
   - ✅ Links work correctly

### 5. Check SendGrid Activity

1. Go to SendGrid Dashboard → Activity
2. Verify:
   - ✅ Email shows as **"Delivered"** (not "Bounced" or "Blocked")
   - ✅ No spam reports
   - ✅ Open rate is reasonable (if tracked)

## Common Issues

### ❌ Email Goes to Spam
- **Cause:** Sender not verified or domain not authenticated
- **Fix:** Complete domain verification or single sender verification
- **Verify:** Check SendGrid Dashboard → Activity → Filter by "Delivered"

### ❌ Email Bounces
- **Cause:** Invalid recipient email or sender not verified
- **Fix:** Verify sender, check recipient email format
- **Verify:** Check SendGrid Dashboard → Activity → Filter by "Bounced"

### ❌ Wrong Sender Address
- **Cause:** `SENDGRID_FROM_EMAIL` not set correctly
- **Fix:** Set `SENDGRID_FROM_EMAIL=helping@easygiveqr.net` in Vercel
- **Verify:** Check email headers show correct sender

## Pass Criteria

- [ ] Domain verified OR single sender verified
- [ ] Sender: `helping@easygiveqr.net` shows as **"Verified"**
- [ ] Test email sent in production
- [ ] Email delivered (not spam, not bounced)
- [ ] Sender is exactly `helping@easygiveqr.net`
- [ ] Correct EN/ES template used
- [ ] Screenshot: SendGrid delivered event ✅

## Verification Checklist

- [ ] SendGrid Dashboard → Sender Authentication → Verified senders includes `helping@easygiveqr.net`
- [ ] SendGrid Dashboard → Activity → Recent email shows **"Delivered"**
- [ ] Test email received in inbox (not spam)
- [ ] Email headers show `From: helping@easygiveqr.net`

---

**Last Verified:** _[TO BE FILLED]_

**Sender Verified By:** _[TO BE FILLED]_
