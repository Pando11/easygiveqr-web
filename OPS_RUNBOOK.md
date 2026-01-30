# Operations Runbook

## Overview

This runbook provides operational guidance for monitoring, troubleshooting, and maintaining EasyGiveQR in production.

## Monitoring & Observability

### Error Tracking

**Sentry Dashboard:**
- URL: https://sentry.io/organizations/[your-org]/projects/easygiveqr/
- **What to monitor:**
  - Error rate trends
  - New error types
  - Error frequency by route
  - Performance issues

**Key Routes Monitored:**
- `/api/stripe-webhook` - Payment processing
- `/api/checkout-session` - Donation checkout
- `/api/jobs/*` - Batch jobs (weekly-summary, annual-receipts, wednesday-payouts)
- `/api/onboarding/*` - Church onboarding

**Alert Thresholds:**
- **Stop the Line:** Error rate > 10% for any route
- **Warning:** Error rate > 5% for any route
- **Critical:** Zero donations processed in 1 hour (during business hours)

### Email Alerts

**Alert Email:** helping@easygiveqr.net

**Alert Types:**
- `webhook_failure` - Stripe webhook processing failures
- `job_failure` - Batch job execution failures
- `checkout_failure` - Checkout session creation failures
- `email_failure` - Email delivery failures
- `database_error` - Database connection/query errors

**Throttling:**
- Alerts are throttled to **at most once per hour per failure type**
- Check Sentry for detailed error logs

### Health Checks

**Health Endpoint:**
```
GET /api/health
```

**Expected Response:**
```json
{
  "ok": true,
  "env": "production",
  "timestamp": "2026-01-27T12:00:00Z"
}
```

**What to Check:**
- All required environment variables are set
- Database connectivity
- Stripe API connectivity
- SendGrid API connectivity

## Critical Failure Scenarios

### 1. Stripe Webhook Failures

**Symptoms:**
- Donations not appearing in database
- Webhook events not being processed
- Alert email: "Stripe Webhook Failures"

**Stop the Line Threshold:**
- **> 5 webhook failures in 1 hour** = Stop the line
- **Zero donations processed in 1 hour** (during business hours) = Stop the line

**Troubleshooting:**
1. Check Sentry for error details
2. Verify `STRIPE_WEBHOOK_SECRET` is correct
3. Check Stripe Dashboard → Webhooks → Events
4. Verify database connectivity
5. Check `stripe_webhook_events` table for recent errors

**Resolution:**
- Fix webhook secret if incorrect
- Restart application if database connection issue
- Manually retry failed webhook events from Stripe Dashboard

### 2. Zero Donations

**Symptoms:**
- No donations processed in last hour
- Donation page not working
- Checkout sessions failing

**Stop the Line Threshold:**
- **Zero donations in 1 hour** (during business hours) = Stop the line

**Troubleshooting:**
1. Check `/api/health` endpoint
2. Verify Stripe API keys are valid
3. Check Sentry for checkout-session errors
4. Test donation flow manually
5. Check church eligibility (subscription status, Stripe Connect)

**Resolution:**
- Fix Stripe API keys if invalid
- Fix church eligibility issues
- Restart application if needed

### 3. Email Delivery Failures

**Symptoms:**
- Weekly summaries not sent
- Annual receipts not sent
- Engagement notifications not sent
- Alert email: "Email Delivery Failures"

**Stop the Line Threshold:**
- **> 50% email failure rate** = Stop the line
- **Zero emails sent in 24 hours** (for scheduled jobs) = Stop the line

**Troubleshooting:**
1. Check SendGrid API key
2. Verify `SENDGRID_FROM_EMAIL` is correct
3. Check SendGrid Dashboard → Activity
4. Verify email addresses are valid
5. Check rate limits

**Resolution:**
- Fix SendGrid API key if invalid
- Verify sender email is verified in SendGrid
- Check SendGrid account limits

### 4. Database Errors

**Symptoms:**
- API routes returning 500 errors
- Database queries failing
- Alert email: "Database Error"

**Stop the Line Threshold:**
- **Any database connection error** = Stop the line
- **> 10% database query failures** = Stop the line

**Troubleshooting:**
1. Check Supabase Dashboard → Database
2. Verify `SUPABASE_URL` and `SUPABASE_SERVICE_ROLE_KEY`
3. Check database connection pool limits
4. Review slow queries
5. Check for database migrations pending

**Resolution:**
- Fix Supabase credentials if invalid
- Scale database if connection pool exhausted
- Apply pending migrations if needed

### 5. Batch Job Failures

**Symptoms:**
- Weekly summaries not sent
- Annual receipts not sent
- Payout notifications not sent
- Alert email: "Batch Job Failure"

**Stop the Line Threshold:**
- **Any job failure** = Investigate immediately
- **> 2 consecutive job failures** = Stop the line

**Troubleshooting:**
1. Check Sentry for job error details
2. Check `job_runs` table for recent failures
3. Verify cron job is scheduled correctly
4. Check job-specific dependencies (email, database, Stripe)

**Resolution:**
- Fix underlying issue (email, database, etc.)
- Manually trigger job if needed
- Verify cron schedule in Vercel Dashboard

## Daily Operations

### Morning Checklist

1. **Check Sentry Dashboard:**
   - Review overnight errors
   - Check error trends
   - Verify no critical issues

2. **Check Email Alerts:**
   - Review any alert emails received
   - Investigate any critical alerts

3. **Check Health Endpoint:**
   - Verify `/api/health` returns `ok: true`
   - Check all environment variables are set

4. **Check Donation Activity:**
   - Verify donations are being processed
   - Check for any anomalies

### Weekly Checklist

1. **Review Error Trends:**
   - Check Sentry for error patterns
   - Identify recurring issues
   - Plan fixes for non-critical issues

2. **Review Job Runs:**
   - Check `job_runs` table for successful executions
   - Verify weekly summaries sent
   - Verify annual receipts sent (if applicable)

3. **Review Database:**
   - Check database size
   - Review slow queries
   - Check for pending migrations

4. **Review Stripe:**
   - Check Stripe Dashboard for issues
   - Verify webhook events are processing
   - Review payment processing

## Emergency Contacts

- **Technical Issues:** helping@easygiveqr.net
- **Stripe Support:** https://support.stripe.com
- **Supabase Support:** https://supabase.com/support
- **SendGrid Support:** https://support.sendgrid.com

## Environment Variables

**Required for Production:**
- `SUPABASE_URL`
- `SUPABASE_SERVICE_ROLE_KEY`
- `STRIPE_SECRET_KEY`
- `STRIPE_WEBHOOK_SECRET`
- `SENDGRID_API_KEY`
- `SENDGRID_FROM_EMAIL`
- `SITE_URL` or `NEXT_PUBLIC_SITE_URL`
- `ADMIN_SECRET`
- `CRON_SECRET`
- `SENTRY_DSN` (optional but recommended)

## Deployment

**Vercel Deployment:**
1. Push to main branch
2. Vercel automatically deploys
3. Verify deployment in Vercel Dashboard
4. Check `/api/health` endpoint
5. Monitor Sentry for errors

**Database Migrations:**
1. Apply migrations via Supabase Dashboard
2. Verify migrations applied successfully
3. Test affected functionality
4. Monitor for errors

## Troubleshooting Commands

**Check webhook events:**
```sql
SELECT * FROM stripe_webhook_events 
ORDER BY processed_at DESC 
LIMIT 10;
```

**Check job runs:**
```sql
SELECT * FROM job_runs 
ORDER BY started_at DESC 
LIMIT 10;
```

**Check recent donations:**
```sql
SELECT * FROM donations 
ORDER BY created_at DESC 
LIMIT 10;
```

**Check church eligibility:**
```sql
SELECT church_id, status, subscription_status, 
       stripe_charges_enabled, stripe_payouts_enabled 
FROM churches 
WHERE status != 'active' OR subscription_status != 'active';
```

## Performance Monitoring

**Key Metrics:**
- API response times (target: < 500ms)
- Database query times (target: < 100ms)
- Email delivery times (target: < 5s)
- Webhook processing times (target: < 2s)

**Tools:**
- Sentry Performance Monitoring
- Vercel Analytics
- Supabase Dashboard → Database → Performance

## Security

**Security Checklist:**
- [ ] All secrets are in environment variables (never in code)
- [ ] Admin endpoints are protected by `x-admin-secret`
- [ ] Cron jobs are protected by `x-cron-secret` or `?cron=...`
- [ ] Rate limiting is enabled on public endpoints
- [ ] PII is not logged or sent to Sentry
- [ ] Database RLS is configured (if applicable)

## Backup & Recovery

**Database Backups:**
- Supabase automatically backs up daily
- Manual backups available in Supabase Dashboard

**Recovery Procedures:**
1. Identify issue
2. Check backups
3. Restore from backup if needed
4. Verify data integrity
5. Monitor for errors

---

**Last Updated:** January 2026
