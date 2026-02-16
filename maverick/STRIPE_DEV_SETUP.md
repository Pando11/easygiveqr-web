# Stripe.dev Setup for Maverick

Use this when you want Maverick running against Stripe test/developer mode.

## 1) Create/access your Stripe developer account

1. Go to `https://stripe.dev` (or Stripe Dashboard directly).
2. Sign in / create account.
3. Ensure you are in **Test mode**.

## 2) Get API keys

1. Dashboard -> Developers -> API keys
2. Copy:
   - Publishable key (`pk_test_...`)
   - Secret key (`sk_test_...`)
3. Set in `.env`:

```env
STRIPE_ENV=dev
STRIPE_SECRET_KEY=sk_test_...
STRIPE_PUBLISHABLE_KEY=pk_test_...
```

## 3) Set webhook secret

For local development with Stripe CLI:

```bash
stripe login
stripe listen --forward-to http://localhost:5000/stripe/webhook
```

Stripe CLI prints:
- `Ready! Your webhook signing secret is whsec_...`

Add to `.env`:

```env
STRIPE_WEBHOOK_SECRET=whsec_...
APP_BASE_URL=http://localhost:5000
```

## 4) Verify Stripe.dev readiness

Run:

```bash
python stripe_dev_bootstrap.py --check-api
```

This validates:
- key formats
- webhook secret presence
- optional API connectivity to Stripe

## 5) Verify app + minions

Run launch checks:

```bash
python run_launch_checks.py
```

Run minions dry-run:

```bash
python run_stripe_minions.py --all --dry-run
```

## 6) Trigger Stripe test events

```bash
stripe trigger payment_intent.succeeded
stripe trigger payment_intent.payment_failed
```

Then verify:
- `/stripe/webhook` handles events
- transaction payment flags update
- communication log entries appear
- dunning/payment-link minions behave as expected

