# Maverick Launch Checklist

## Pre-Launch
- [ ] All credentials in `.env`
- [ ] Database schema loaded in Supabase
- [ ] S3 buckets created
- [ ] Twilio verified phone numbers
- [ ] Stripe in test mode
- [ ] All routes tested
- [ ] Margaret trained on system

## Railway Deployment
- [ ] Push code to GitHub
- [ ] Connect Railway to GitHub repo
- [ ] Add all environment variables in Railway
- [ ] Deploy app
- [ ] Run schema on production database
- [ ] Configure cron jobs
- [ ] Test live URL

## Go Live
- [ ] Switch Stripe to live keys
- [ ] Update Twilio webhook URL
- [ ] Test with first beta agent
- [ ] Monitor first transaction closely
