# Database Migrations Guide

## Overview

This directory contains SQL migration files that define all database schema changes for EasyGiveQR. All schema changes **must** be captured in migration files to ensure consistency across environments.

## Directory Structure

```
supabase/
  migrations/
    20260127_create_job_runs.sql
    20260127_add_stripe_connect_to_churches.sql
    ...
```

## Naming Conventions

Migration files use the format: `YYYYMMDD_description.sql`

Examples:
- `20260127_create_job_runs.sql`
- `20260127_add_monthly_enabled_to_churches.sql`
- `20260127_add_donor_fields_to_donations.sql`

**Rules:**
- Use date prefix (YYYYMMDD) for chronological ordering
- Use descriptive names (what the migration does)
- Use lowercase with underscores
- Never use spaces or special characters

## Migration Guidelines

### ✅ DO:

1. **Always use `IF NOT EXISTS` or `DO $$` blocks** to make migrations idempotent
   ```sql
   ALTER TABLE public.churches
   ADD COLUMN IF NOT EXISTS monthly_enabled boolean NOT NULL DEFAULT false;
   ```

2. **Add comments** for documentation
   ```sql
   COMMENT ON COLUMN public.churches.monthly_enabled IS 'Whether monthly recurring donations are enabled';
   ```

3. **Create indexes** for performance-critical columns
   ```sql
   CREATE INDEX IF NOT EXISTS idx_churches_monthly_enabled ON public.churches(monthly_enabled);
   ```

4. **Use transactions** for multi-step changes (when needed)
   ```sql
   BEGIN;
   -- multiple statements
   COMMIT;
   ```

5. **Test migrations** on a copy of production data before applying

### ❌ DON'T:

1. **Never edit old migrations** - Create a new migration instead
2. **Never drop columns without a deprecation period** - Mark as deprecated first
3. **Never use `DROP TABLE` or `DROP COLUMN`** without careful consideration
4. **Never hardcode IDs** - Use references or lookups
5. **Never commit migrations that haven't been tested**

## Applying Migrations

### Local Development

**Using Supabase CLI:**
```bash
# Apply all pending migrations
supabase db reset

# Or apply specific migration
supabase migration up
```

**Using psql directly:**
```bash
# Connect to local database
psql -h localhost -U postgres -d postgres

# Apply a migration
\i supabase/migrations/20260127_create_job_runs.sql
```

**Using Supabase Dashboard:**
1. Go to SQL Editor
2. Copy migration SQL
3. Paste and run

### Production (Supabase Dashboard)

1. **Backup first** (always!)
   - Go to Database → Backups
   - Create a manual backup before applying migrations

2. **Apply migration:**
   - Go to SQL Editor
   - Copy migration SQL
   - Paste and run
   - Verify no errors

3. **Verify migration:**
   - Check that columns/tables exist
   - Run a test query
   - Monitor for errors

### Staging/Test Environment

Always test migrations on staging first:
1. Apply migration to staging
2. Run test suite
3. Verify application works
4. Then apply to production

## Rollback Strategy

**Important:** We do NOT have automatic rollback migrations. Rollbacks must be done manually if needed.

### Manual Rollback Steps:

1. **Identify what needs to be rolled back:**
   - Review the migration file
   - Understand what it changed

2. **Create a rollback script** (temporary, not committed):
   ```sql
   -- Rollback: Remove monthly_enabled column
   ALTER TABLE public.churches
   DROP COLUMN IF EXISTS monthly_enabled;
   ```

3. **Test rollback on staging first**

4. **Apply rollback to production** (if needed)

5. **Document the rollback** in a ticket/issue

### When to Rollback:

- Migration causes data corruption
- Migration breaks critical functionality
- Migration has security issues
- Migration causes performance degradation

## Migration Checklist

Before committing a migration:

- [ ] Migration is idempotent (can run multiple times safely)
- [ ] Migration includes comments/documentation
- [ ] Migration creates necessary indexes
- [ ] Migration tested on local database
- [ ] Migration tested on staging (if available)
- [ ] Migration does not drop data
- [ ] Migration follows naming conventions
- [ ] Migration reviewed by another developer (if possible)

## Current Schema Overview

### Core Tables:

- **`churches`** - Church information, Stripe Connect accounts, subscriptions
- **`donations`** - Donation records with donor information
- **`engagement_submissions`** - Prayer requests, visitor cards, volunteer interest
- **`job_runs`** - Batch job execution history
- **`stripe_webhook_events`** - Stripe webhook event tracking
- **`annual_receipts_sent`** - Annual receipt sending history

### Key Columns:

**churches:**
- `church_id` (text, PK)
- `display_name`, `legal_name`
- `admin_emails` (text[])
- `monthly_enabled` (boolean)
- `stripe_account_id`, `stripe_customer_id`, `stripe_subscription_id`
- `subscription_status`, `subscription_started_at`, `subscription_canceled_at`
- `qr_code_url`, `logo_url`
- `status`, `preferred_language`, `primary_color`

**donations:**
- `id` (uuid, PK)
- `church_id` (text, FK)
- `stripe_session_id` (text, UNIQUE)
- `amount_cents`, `currency`, `status`
- `donor_email`, `donor_name`, `donor_address` (jsonb)
- `created_at` (timestamptz)

## Troubleshooting

### Migration Fails with "already exists" Error

This usually means the migration was partially applied. Check what exists:
```sql
SELECT column_name 
FROM information_schema.columns 
WHERE table_name = 'churches' 
AND column_name = 'monthly_enabled';
```

If the column exists, the migration is already applied. Skip it or mark as applied.

### Migration Fails with Foreign Key Error

Check for existing data that violates constraints:
```sql
SELECT * FROM donations 
WHERE church_id NOT IN (SELECT church_id FROM churches);
```

Fix the data, then re-run the migration.

### Migration Takes Too Long

Large migrations can lock tables. Consider:
- Running during low-traffic periods
- Breaking into smaller migrations
- Using `CONCURRENTLY` for index creation (PostgreSQL 12+)

## Resources

- [Supabase Migrations Docs](https://supabase.com/docs/guides/cli/local-development#database-migrations)
- [PostgreSQL ALTER TABLE](https://www.postgresql.org/docs/current/sql-altertable.html)
- [PostgreSQL Indexes](https://www.postgresql.org/docs/current/indexes.html)

## Questions?

Contact: helping@easygiveqr.net
