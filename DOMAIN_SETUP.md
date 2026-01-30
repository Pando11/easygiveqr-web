# Domain Setup Guide - easygiveqr.net

## Overview

This guide covers connecting the `easygiveqr.net` domain (and `www.easygiveqr.net`) to your Vercel deployment.

## Prerequisites

- Vercel project deployed and working
- Domain registered at your registrar (e.g., Namecheap, GoDaddy, Google Domains)
- Access to domain DNS settings

## Step 1: Add Domain in Vercel

1. **Go to Vercel Dashboard:**
   - Visit https://vercel.com/dashboard
   - Click on your project

2. **Navigate to Settings:**
   - Click **Settings** tab
   - Click **Domains** in the left sidebar

3. **Add Domain:**
   - Enter `easygiveqr.net` in the domain field
   - Click **Add**
   - Vercel will show you the DNS records needed

4. **Add www Subdomain:**
   - Enter `www.easygiveqr.net` in the domain field
   - Click **Add**

## Step 2: Configure DNS Records

### At Your Domain Registrar:

You need to add DNS records to point your domain to Vercel. The exact method depends on your registrar.

#### Option A: Apex Domain (easygiveqr.net) - Using A Records

Vercel will provide you with IP addresses. Add A records:

```
Type: A
Name: @ (or leave blank, or use "easygiveqr.net")
Value: [IP address from Vercel]
TTL: 3600 (or Auto)
```

**Note:** Vercel may recommend using their nameservers instead (see Option B below).

#### Option B: Using Vercel Nameservers (Recommended)

1. **Get Nameservers from Vercel:**
   - In Vercel Domains settings, Vercel will show you nameservers
   - Example: `ns1.vercel-dns.com`, `ns2.vercel-dns.com`

2. **Update Nameservers at Registrar:**
   - Go to your domain registrar's DNS/Nameserver settings
   - Replace existing nameservers with Vercel's nameservers
   - Save changes

3. **Wait for Propagation:**
   - DNS changes can take 24-48 hours to propagate
   - Usually works within a few hours

#### Option C: CNAME for www (Always Required)

For `www.easygiveqr.net`, add a CNAME record:

```
Type: CNAME
Name: www
Value: cname.vercel-dns.com (or value provided by Vercel)
TTL: 3600 (or Auto)
```

## Step 3: Verify SSL/HTTPS

1. **Wait for DNS Propagation:**
   - Check DNS propagation: https://www.whatsmydns.net
   - Enter `easygiveqr.net` and verify it points to Vercel

2. **Vercel Auto-SSL:**
   - Vercel automatically provisions SSL certificates via Let's Encrypt
   - This happens automatically once DNS is configured correctly
   - Usually takes 5-10 minutes after DNS is live

3. **Verify HTTPS:**
   - Visit `https://easygiveqr.net`
   - Visit `https://www.easygiveqr.net`
   - Both should load with a valid SSL certificate (green lock icon)

## Step 4: Set Environment Variable

1. **In Vercel Dashboard:**
   - Go to **Settings** → **Environment Variables**

2. **Add/Update:**
   ```
   SITE_URL=https://easygiveqr.net
   ```
   Or:
   ```
   NEXT_PUBLIC_SITE_URL=https://easygiveqr.net
   ```

3. **Redeploy:**
   - After adding the environment variable, trigger a new deployment
   - Go to **Deployments** tab → Click **Redeploy** on latest deployment

## Step 5: Verify Both Domains Work

1. **Test Apex Domain:**
   - Visit: `https://easygiveqr.net`
   - Should load your Next.js app

2. **Test www Subdomain:**
   - Visit: `https://www.easygiveqr.net`
   - Should load your Next.js app (Vercel redirects www to apex or vice versa)

3. **Test Donate Page:**
   - Visit: `https://easygiveqr.net/donate?church_id=EGQR-123`
   - Should load the donation page

## Common Issues

### Domain Not Resolving

**Symptoms:** Domain shows "Not Found" or doesn't load

**Solutions:**
- Wait longer for DNS propagation (can take up to 48 hours)
- Verify DNS records are correct at your registrar
- Check Vercel Domains page for any errors
- Use `dig easygiveqr.net` or `nslookup easygiveqr.net` to verify DNS

### SSL Certificate Not Issued

**Symptoms:** HTTPS shows "Not Secure" or certificate error

**Solutions:**
- Ensure DNS is fully propagated
- Wait 10-15 minutes after DNS is live
- Check Vercel Domains page for SSL status
- Try forcing a redeploy in Vercel

### www Redirect Not Working

**Symptoms:** www subdomain doesn't redirect to apex (or vice versa)

**Solutions:**
- Verify CNAME record for www is correct
- Check Vercel Domains settings for redirect configuration
- Vercel should handle this automatically, but you can configure it in project settings

## DNS Record Examples

### Namecheap

1. Go to **Domain List** → Click **Manage** next to `easygiveqr.net`
2. Go to **Advanced DNS** tab
3. Add records:
   - **A Record:** Host `@`, Value `[Vercel IP]`, TTL `Automatic`
   - **CNAME Record:** Host `www`, Value `cname.vercel-dns.com`, TTL `Automatic`

### GoDaddy

1. Go to **My Products** → Click **DNS** next to `easygiveqr.net`
2. Add records:
   - **A Record:** Type `A`, Name `@`, Value `[Vercel IP]`, TTL `600`
   - **CNAME Record:** Type `CNAME`, Name `www`, Value `cname.vercel-dns.com`, TTL `600`

### Google Domains

1. Go to **DNS** settings
2. Add records:
   - **A Record:** Name `@`, IPv4 address `[Vercel IP]`, TTL `3600`
   - **CNAME Record:** Name `www`, Domain name `cname.vercel-dns.com`, TTL `3600`

## Verification Checklist

- [ ] Domain added in Vercel Dashboard
- [ ] DNS records configured at registrar
- [ ] DNS propagated (checked via whatsmydns.net)
- [ ] SSL certificate issued (green lock in browser)
- [ ] `https://easygiveqr.net` loads correctly
- [ ] `https://www.easygiveqr.net` loads correctly
- [ ] `SITE_URL` environment variable set in Vercel
- [ ] App redeployed after setting environment variable
- [ ] Donate page works: `https://easygiveqr.net/donate?church_id=EGQR-123`

## Next Steps

After domain setup is complete:
1. Update Stripe webhook URL (see `STRIPE_SETUP.md`)
2. Regenerate QR codes for all churches (they will now point to `https://easygiveqr.net`)
3. Test full donation flow on production domain
4. Verify webhook receives events from Stripe
