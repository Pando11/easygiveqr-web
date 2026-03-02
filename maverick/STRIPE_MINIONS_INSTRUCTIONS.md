# Stripe Minions - Operator Instructions

This document is the instruction pack for Maverick's Stripe minions.

## Objective

Stripe minions automate payment operations while keeping Margaret in control.

Primary goals:
- Recover failed/overdue payments quickly
- Keep Stripe and database payment states in sync
- Reduce manual reminder work
- Keep an auditable communication trail

## Minions and responsibilities

### 1) Payment Link Minion
**Script:** `minions/payment_link_minion.py`  
**Purpose:** Send proactive payment links for:
- overdue upfront payments
- unpaid closing payments within 3 days of closing

**Data inputs:**
- `transactions` table
- payment amounts from shared `utils/payments.py`

**Side effects:**
- Sends SMS to agents
- Writes communication log entries

---

### 2) Dunning Minion
**Script:** `minions/dunning_minion.py`  
**Purpose:** Recover failed card payments by scanning recent Stripe PaymentIntents.

**Data inputs:**
- Stripe PaymentIntents (recent)
- transaction metadata (`transaction_id`, `payment_type`)
- `transactions` and `communications` tables

**Side effects:**
- Sends retry SMS links
- Writes communication log entries

---

### 3) Reconciliation Minion
**Script:** `minions/reconciliation_minion.py`  
**Purpose:** Compare Stripe succeeded payment intents with DB paid flags.

**Data inputs:**
- Stripe PaymentIntents
- `transactions` table

**Side effects:**
- Reporting only by default
- Optional DB fixes with `--auto-fix`

---

### 4) Stripe Webhook Minion (HTTP route)
**Route:** `POST /stripe/webhook` in `app.py`  
**Purpose:** Real-time payment state sync from Stripe events.

**Handled events:**
- `payment_intent.succeeded`
- `payment_intent.payment_failed`

**Side effects:**
- Updates payment flags in `transactions`
- Sends retry SMS for failed intents
- Writes communication log entries

---

## Runtime commands

### Run all minions safely (dry-run)
```bash
python run_stripe_minions.py --all --dry-run
```

### Print current minion briefing payload
```bash
python minions/briefing.py
```

### Run one minion
```bash
python run_stripe_minions.py --minion payment-links --dry-run
python run_stripe_minions.py --minion dunning --lookback-days 14 --dry-run
python run_stripe_minions.py --minion reconciliation --lookback-days 60
```

### Reconciliation with DB fixes
```bash
python run_stripe_minions.py --minion reconciliation --auto-fix
```

## Required environment variables

- `STRIPE_ENV` (`dev` for stripe.dev / test mode, `production` for live mode)
- `STRIPE_SECRET_KEY`
- `STRIPE_PUBLISHABLE_KEY`
- `STRIPE_WEBHOOK_SECRET`
- `APP_BASE_URL` (example: `https://maverick-production.up.railway.app`)
- `DATABASE_URL`
- `TWILIO_ACCOUNT_SID`
- `TWILIO_AUTH_TOKEN`
- `TWILIO_PHONE_NUMBER`

## Stripe dashboard configuration

Create webhook endpoint:
- URL: `https://<your-domain>/stripe/webhook`
- Events:
  - `payment_intent.succeeded`
  - `payment_intent.payment_failed`

## Stripe.dev quick bootstrap

1. Set `STRIPE_ENV=dev`
2. Use `sk_test_...` and `pk_test_...` keys
3. Start Stripe CLI forwarding:
   - `stripe listen --forward-to http://localhost:5000/stripe/webhook`
4. Validate:
   - `python stripe_dev_bootstrap.py --check-api`

## Safety rules

1. Run with `--dry-run` before enabling schedules.
2. Do **not** use `--auto-fix` until reconciliation output is reviewed.
3. Keep payment metadata on intents:
   - `transaction_id`
   - `payment_type`
4. Never delete payment-related communication logs.

## Suggested schedules (after dry-run validation)

- Payment link minion: every 12 hours
- Dunning minion: every 6 hours
- Reconciliation minion: daily at 6:30am (without auto-fix initially)

## Escalation triggers

Escalate to Heidi if:
- 3+ dunning failures for same transaction in 24h
- reconciliation finds >10 mismatches
- webhook 4xx/5xx spikes

