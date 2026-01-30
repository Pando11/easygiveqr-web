# Step 12: QR Code Generation per Church

## Overview

Generate and store one QR code per church that points to the donation page. QR codes are generated server-side, stored in Supabase Storage, and accessible via public URLs.

## Database Migration

### Run Migration

**In Supabase Dashboard → SQL Editor, run:**

```sql
-- File: supabase/migrations/20260127_add_qr_code_to_churches.sql
-- Adds QR code URL and updated timestamp columns
```

**OR run directly:**

```sql
-- Add qr_code_url column
DO $$
BEGIN
    IF NOT EXISTS (SELECT 1 FROM information_schema.columns WHERE table_schema = 'public' AND table_name = 'churches' AND column_name = 'qr_code_url') THEN
        ALTER TABLE public.churches ADD COLUMN qr_code_url text;
    END IF;
END $$;

-- Add qr_code_updated_at column
DO $$
BEGIN
    IF NOT EXISTS (SELECT 1 FROM information_schema.columns WHERE table_schema = 'public' AND table_name = 'churches' AND column_name = 'qr_code_updated_at') THEN
        ALTER TABLE public.churches ADD COLUMN qr_code_updated_at timestamptz;
    END IF;
END $$;
```

## Supabase Storage Setup

### Step 1: Create Storage Bucket

**In Supabase Dashboard:**

1. Go to **Storage** → **Buckets**
2. Click **"New bucket"**
3. **Bucket name:** `church-assets`
4. **Public bucket:** ✅ **Yes** (check this for public read access)
5. Click **"Create bucket"**

### Step 2: Set Bucket Policies (Optional - if public bucket is enabled, this may not be needed)

**If you need to set explicit policies, go to Storage → Policies:**

**For public read access:**

```sql
-- Allow public read access to QR codes
CREATE POLICY "Public QR code read access"
ON storage.objects FOR SELECT
USING (bucket_id = 'church-assets' AND (storage.foldername(name))[1] = 'qr');
```

**For service role write access (automatic with service role key):**

The service role key already has full access, so no additional policy needed for uploads.

### Step 3: Verify Bucket

**Test bucket access:**

```sql
-- List buckets (should see 'church-assets')
SELECT name FROM storage.buckets;
```

## Environment Variables

Add to `.env.local`:

```
NEXT_PUBLIC_SITE_URL=http://localhost:3000
```

**For production (Vercel):**
- Set `NEXT_PUBLIC_SITE_URL` to your production domain (e.g., `https://easygiveqr.com`)
- Or use `SITE_URL` as fallback

## API Routes

### 1. Generate QR Code

**POST** `/api/qr/generate`

**Request body:**
```json
{
  "church_id": "EGQR-123",
  "force": false  // optional, regenerate even if exists
}
```

**Response:**
```json
{
  "ok": true,
  "qr_code_url": "https://...supabase.co/storage/v1/object/public/church-assets/qr/EGQR-123.png",
  "donate_url": "http://localhost:3000/donate?church_id=EGQR-123"
}
```

**Behavior:**
- Generates QR code PNG (512x512px)
- Uploads to Supabase Storage at `qr/EGQR-123.png`
- Updates `churches.qr_code_url` and `qr_code_updated_at`
- Idempotent: returns existing URL if `force=false`

### 2. Get QR Code Info

**GET** `/api/qr?church_id=EGQR-123`

**Response:**
```json
{
  "ok": true,
  "church_id": "EGQR-123",
  "donate_url": "http://localhost:3000/donate?church_id=EGQR-123",
  "qr_code_url": "https://...supabase.co/storage/v1/object/public/church-assets/qr/EGQR-123.png"
}
```

## Admin Page (Optional)

**URL:** `/admin/churches/[church_id]/qr`

**Features:**
- Displays QR code image
- Shows donation URL
- "Download PNG" button
- "Regenerate QR Code" button
- Minimal styling

## Local Testing

### Step 1: Install Dependencies

```cmd
npm install qrcode
npm install --save-dev @types/qrcode
```

### Step 2: Set Up Storage Bucket

1. Create `church-assets` bucket in Supabase Dashboard
2. Set as public bucket (or configure policies)

### Step 3: Set Environment Variable

**In `.env.local`:**
```
NEXT_PUBLIC_SITE_URL=http://localhost:3000
```

### Step 4: Generate QR Code

**Using PowerShell:**

```powershell
$headers = @{ "Content-Type" = "application/json" }
$body = @{ church_id = "EGQR-123" } | ConvertTo-Json
Invoke-RestMethod -Uri "http://localhost:3000/api/qr/generate" -Method POST -Headers $headers -Body $body
```

**Expected response:**
```json
{
  "ok": true,
  "qr_code_url": "https://...supabase.co/storage/v1/object/public/church-assets/qr/EGQR-123.png",
  "donate_url": "http://localhost:3000/donate?church_id=EGQR-123"
}
```

### Step 5: Verify QR Code URL Saved

**In Supabase SQL Editor:**

```sql
SELECT church_id, qr_code_url, qr_code_updated_at
FROM public.churches
WHERE church_id = 'EGQR-123';
```

**Expected:** `qr_code_url` should contain the Supabase Storage URL

### Step 6: Open QR Code URL

**Open the `qr_code_url` in your browser:**

- Should display the QR code PNG image
- Image should be accessible publicly

### Step 7: Scan QR Code

**Using a QR code scanner app:**

1. Scan the QR code from the browser
2. Should navigate to: `http://localhost:3000/donate?church_id=EGQR-123`
3. Verify the donation page loads correctly

### Step 8: Test Admin Page (Optional)

**Open in browser:**
```
http://localhost:3000/admin/churches/EGQR-123/qr
```

**Expected:**
- QR code image displayed
- Download button works
- Regenerate button works

## Production Setup

### Environment Variables in Vercel

Set `NEXT_PUBLIC_SITE_URL` to your production domain:
```
NEXT_PUBLIC_SITE_URL=https://easygiveqr.com
```

### Storage Bucket

- Ensure `church-assets` bucket exists in production Supabase
- Ensure bucket is public or policies are configured
- QR codes will be stored at: `qr/EGQR-XXX.png`

## QR Code Details

- **Format:** PNG
- **Size:** 512x512 pixels
- **Error Correction:** Medium (M)
- **Margin:** 2 modules
- **Content:** `{SITE_URL}/donate?church_id={church_id}`
- **Storage Path:** `qr/{church_id}.png`

## Troubleshooting

### "Storage bucket 'church-assets' not found"

**Solution:**
1. Go to Supabase Dashboard → Storage
2. Create bucket named `church-assets`
3. Set as public bucket
4. Retry the generate request

### "Failed to upload QR code"

**Solution:**
- Check Supabase Storage bucket permissions
- Verify service role key has write access
- Check bucket name matches exactly: `church-assets`

### QR code URL returns 404

**Solution:**
- Verify bucket is set to public
- Check file path: `qr/EGQR-123.png`
- Verify file exists in Supabase Storage dashboard

### Wrong donation URL in QR code

**Solution:**
- Check `NEXT_PUBLIC_SITE_URL` or `SITE_URL` environment variable
- For local: `http://localhost:3000`
- For production: `https://easygiveqr.com`
- Regenerate QR code after fixing URL

### QR code doesn't scan correctly

**Solution:**
- Verify QR code contains correct URL format
- Check for URL encoding issues
- Test the donation URL directly in browser first
- Regenerate with `force: true`

## Important Notes

- **One QR per church:** Each church has exactly one QR code
- **Idempotent:** Generating twice returns existing URL (unless `force=true`)
- **Public URLs:** QR codes are publicly accessible via Supabase Storage
- **Server-side only:** QR generation happens server-side, never exposed to client
- **Deterministic paths:** QR codes stored at `qr/{church_id}.png`

## Package Installation

**Required package:**

```cmd
npm install qrcode
npm install --save-dev @types/qrcode
```

**After installation, restart Next.js dev server.**
