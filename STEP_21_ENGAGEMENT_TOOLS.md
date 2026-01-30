# Step 21: Engagement Tools v1 (Simple Forms)

## Overview

Add three simple engagement forms for each church:
- Prayer request form
- Visitor connect card
- Volunteer interest form

Forms are simple, logged to database, with optional email notifications. No CRM behavior or marketing automation.

## Database Changes

### Migration

**`supabase/migrations/20260127_create_engagement_submissions.sql`**

Creates unified `public.engagement_submissions` table:

```sql
CREATE TABLE public.engagement_submissions (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  church_id text NOT NULL REFERENCES public.churches(church_id),
  type text NOT NULL CHECK (type IN ('prayer', 'visitor', 'volunteer')),
  name text,
  email text,
  phone text,
  message text,
  meta jsonb,
  status text NOT NULL DEFAULT 'open' CHECK (status IN ('open', 'completed')),
  created_at timestamptz NOT NULL DEFAULT now(),
  completed_at timestamptz
);
```

**Indexes:**
- `church_id`
- `type`
- `status`
- `created_at` (DESC)

## Implementation

### 1. Public Pages

**`src/app/engage/[type]/page.tsx`**

Dynamic route handling all three form types:
- `/engage/prayer?church_id=EGQR-123`
- `/engage/visitor?church_id=EGQR-123`
- `/engage/volunteer?church_id=EGQR-123`

**Features:**
- Loads church branding (logo, name, primary color)
- Form fields vary by type:
  - **Prayer:** Message required, name/email/phone optional
  - **Visitor:** Name required, email/phone/message optional
  - **Volunteer:** Name required, email/phone/message optional
- EN/ES text based on `church.preferred_language`
- Shows "Submitted" confirmation page after success
- Clean, mobile-first design

### 2. Submit API

**`src/app/api/engagement/submit/route.ts`**

**POST /api/engagement/submit**

**Request Body:**
```json
{
  "church_id": "EGQR-123",
  "type": "prayer" | "visitor" | "volunteer",
  "name": "John Doe" (optional for prayer, required for visitor/volunteer),
  "email": "john@example.com" (optional),
  "phone": "+1234567890" (optional),
  "message": "Prayer request text" (required for prayer, optional for others),
  "meta": {} (optional, JSON object)
}
```

**Validation:**
- `church_id` required
- `type` must be `prayer`, `visitor`, or `volunteer`
- Prayer: `message` required
- Visitor/Volunteer: `name` required
- Email format validation if provided

**Response:**
```json
{
  "ok": true,
  "id": "uuid-of-submission"
}
```

**Email Notification:**
- If SendGrid configured and church has `admin_emails`:
  - Sends email to all admin emails
  - Subject: "New {Prayer Request|Visitor|Volunteer} — {Church Name}"
  - Body includes all submitted fields
  - EN/ES based on `church.preferred_language`
  - Email failure does NOT block submission (logged only)

### 3. Admin Routes

**GET /api/admin/engagement**

**Query Parameters:**
- `church_id` (required)
- `type` (optional): `prayer`, `visitor`, or `volunteer`
- `status` (optional): `open` or `completed`

**Response:**
```json
{
  "ok": true,
  "submissions": [...],
  "count": 10
}
```

Returns last 100 submissions, newest first.

**Protected by:** `x-admin-secret` header

**PATCH /api/admin/engagement/complete**

**Request Body:**
```json
{
  "id": "uuid-of-submission"
}
```

**Response:**
```json
{
  "ok": true,
  "submission": {
    "id": "...",
    "status": "completed",
    "completed_at": "2026-01-27T..."
  }
}
```

Sets `status='completed'` and `completed_at=now()`.

**Protected by:** `x-admin-secret` header

### 4. Translations

**`src/lib/engagementTranslations.ts`**

EN/ES translations for all form text:
- Form titles and subtitles
- Field labels
- Submit buttons
- Success messages
- Error messages

### 5. Email Templates

**`src/lib/engagementEmailTemplates.ts`**

Functions to generate email content:
- `generateEngagementEmailSubject()` - Email subject line
- `generateEngagementEmailHtml()` - HTML email body
- `generateEngagementEmailText()` - Plain text email body

All support EN/ES based on church language.

## Testing

### Test 1: Submit Prayer Request

**Steps:**
1. Visit: `http://localhost:3000/engage/prayer?church_id=EGQR-123`
2. Fill form:
   - Message: "Please pray for my family"
   - Name: "John Doe" (optional)
   - Email: "john@example.com" (optional)
3. Submit

**Expected:**
- Success confirmation page
- Row in `engagement_submissions` table:
  - `type = 'prayer'`
  - `status = 'open'`
  - `message` populated
- Email sent to church admin emails (if SendGrid configured)

**Verify in Supabase:**
```sql
SELECT * FROM public.engagement_submissions 
WHERE church_id = 'EGQR-123' AND type = 'prayer'
ORDER BY created_at DESC LIMIT 1;
```

### Test 2: Submit Visitor Connect

**Steps:**
1. Visit: `http://localhost:3000/engage/visitor?church_id=EGQR-123`
2. Fill form:
   - Name: "Jane Smith" (required)
   - Email: "jane@example.com" (optional)
   - Phone: "+1234567890" (optional)
   - Message: "First time visitor" (optional)
3. Submit

**Expected:**
- Success confirmation
- Row with `type = 'visitor'`, `name` populated
- Email notification sent

### Test 3: Submit Volunteer Interest

**Steps:**
1. Visit: `http://localhost:3000/engage/volunteer?church_id=EGQR-123`
2. Fill form:
   - Name: "Bob Johnson" (required)
   - Email: "bob@example.com" (optional)
   - Message: "Interested in music ministry" (optional)
3. Submit

**Expected:**
- Success confirmation
- Row with `type = 'volunteer'`, `name` populated
- Email notification sent

### Test 4: Admin List Submissions

**Using curl:**
```bash
curl -X GET "http://localhost:3000/api/admin/engagement?church_id=EGQR-123&status=open" \
  -H "x-admin-secret: YOUR_ADMIN_SECRET"
```

**Expected:**
```json
{
  "ok": true,
  "submissions": [
    {
      "id": "...",
      "church_id": "EGQR-123",
      "type": "prayer",
      "name": "John Doe",
      "email": "john@example.com",
      "message": "Please pray for my family",
      "status": "open",
      "created_at": "2026-01-27T..."
    }
  ],
  "count": 1
}
```

### Test 5: Admin Mark Complete

**Using curl:**
```bash
curl -X PATCH http://localhost:3000/api/admin/engagement/complete \
  -H "Content-Type: application/json" \
  -H "x-admin-secret: YOUR_ADMIN_SECRET" \
  -d '{"id": "uuid-from-test-4"}'
```

**Expected:**
```json
{
  "ok": true,
  "submission": {
    "id": "...",
    "status": "completed",
    "completed_at": "2026-01-27T..."
  }
}
```

**Verify in Supabase:**
```sql
SELECT id, status, completed_at 
FROM public.engagement_submissions 
WHERE id = 'uuid-from-test-4';
```

Should show `status = 'completed'` and `completed_at` populated.

### Test 6: Validation Errors

**Missing Required Fields:**

Prayer without message:
```bash
curl -X POST http://localhost:3000/api/engagement/submit \
  -H "Content-Type: application/json" \
  -d '{"church_id": "EGQR-123", "type": "prayer"}'
```

**Expected:** `400 { ok: false, error: "Message is required for prayer requests" }`

Visitor without name:
```bash
curl -X POST http://localhost:3000/api/engagement/submit \
  -H "Content-Type: application/json" \
  -d '{"church_id": "EGQR-123", "type": "visitor"}'
```

**Expected:** `400 { ok: false, error: "Name is required for visitor and volunteer submissions" }`

### Test 7: Language Support

**EN Church:**
1. Set `preferred_language = 'EN'` in database
2. Visit form page
3. Expected: All text in English

**ES Church:**
1. Set `preferred_language = 'ES'` in database
2. Visit form page
3. Expected: All text in Spanish

## API Reference

### POST /api/engagement/submit

**Public endpoint** (no authentication required)

**Request:**
```json
{
  "church_id": "EGQR-123",
  "type": "prayer",
  "name": "John Doe",
  "email": "john@example.com",
  "phone": "+1234567890",
  "message": "Prayer request text",
  "meta": {}
}
```

**Success (200):**
```json
{
  "ok": true,
  "id": "uuid"
}
```

**Error (400):**
```json
{
  "ok": false,
  "error": "Message is required for prayer requests"
}
```

### GET /api/admin/engagement

**Protected by:** `x-admin-secret` header

**Query Parameters:**
- `church_id` (required)
- `type` (optional): `prayer`, `visitor`, `volunteer`
- `status` (optional): `open`, `completed`

**Success (200):**
```json
{
  "ok": true,
  "submissions": [...],
  "count": 10
}
```

### PATCH /api/admin/engagement/complete

**Protected by:** `x-admin-secret` header

**Request:**
```json
{
  "id": "uuid"
}
```

**Success (200):**
```json
{
  "ok": true,
  "submission": {
    "id": "uuid",
    "status": "completed",
    "completed_at": "2026-01-27T..."
  }
}
```

## Files Created

1. `supabase/migrations/20260127_create_engagement_submissions.sql` - Database migration
2. `src/lib/engagementTranslations.ts` - EN/ES translations
3. `src/lib/engagementEmailTemplates.ts` - Email template generators
4. `src/app/engage/[type]/page.tsx` - Dynamic form page
5. `src/app/api/engagement/submit/route.ts` - Submit API
6. `src/app/api/admin/engagement/route.ts` - Admin list API
7. `src/app/api/admin/engagement/complete/route.ts` - Admin complete API

## Important Notes

- **Simple forms only:** No CRM behavior, no marketing automation
- **Optional fields:** Email and phone are optional for all forms
- **Required fields:**
  - Prayer: `message` required
  - Visitor/Volunteer: `name` required
- **Status tracking:** `open` (default) or `completed`
- **Email notifications:** Optional, sent to `church.admin_emails` if SendGrid configured
- **Email failures:** Do not block submission (logged only)
- **Language support:** All text in EN/ES based on `church.preferred_language`
- **No dashboard UI:** Admin operations via API only

## Troubleshooting

### Form Not Loading

**Check:**
- `church_id` is in URL query parameter
- Church exists in database
- Type is one of: `prayer`, `visitor`, `volunteer`

### Submission Fails

**Check:**
- Required fields are filled (message for prayer, name for visitor/volunteer)
- Email format is valid if provided
- Church exists in database
- API route is accessible

### Email Not Sending

**Check:**
- `SENDGRID_API_KEY` and `SENDGRID_FROM_EMAIL` are set
- Church has `admin_emails` array populated
- Check server logs for email errors (submission should still succeed)

### Admin Routes Return 401

**Check:**
- `x-admin-secret` header is present
- Header value matches `ADMIN_SECRET` environment variable
