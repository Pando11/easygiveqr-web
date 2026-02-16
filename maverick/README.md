# Maverick Transaction Coordinator

Maverick is a Flask application for transaction coordination workflows:
- Agent contract upload
- S3 document storage
- PostgreSQL transaction tracking
- SMS notifications and auto-responses
- Stripe payment processing
- Cron-driven reminders and problem detection

## Current deliverables in this scaffold

- Project structure and deployment files (`Procfile`, `runtime.txt`)
- Upload form UI (`templates/upload.html`)
- Upload API endpoint (`POST /upload`)
- Twilio SMS webhook (`POST /sms-webhook`)
- Stripe payment page and processing endpoints (`/pay/...`)
- Stripe webhook endpoint (`POST /stripe/webhook`)
- TC login/dashboard stubs (`/tc/login`, `/tc`)
- Reminder automation script (`send_reminders.py`)
- Closing protocol script (`closing_protocol.py`)
- Problem detection script (`check_problems.py`)
- Stripe minion scripts (`minions/`)
- Stripe minion orchestrator (`run_stripe_minions.py`)
- SQL schema (`schema.sql`)
- Helper utilities for database, Twilio, and S3 (`utils/`)
- Backup script (`backup_db.sh`)
- Margaret training manual (`MARGARET_TRAINING_MANUAL.md`)

## Local setup

1. Create and activate a virtual environment:
   ```bash
   python3 -m venv venv
   source venv/bin/activate
   ```
2. Install dependencies:
   ```bash
   pip install -r requirements.txt
   ```
3. Configure environment:
   ```bash
   cp .env.example .env
   ```
4. Update `.env` with Railway, Twilio, AWS, and Stripe values.
5. Run app:
   ```bash
   python app.py
   ```
6. Open:
   - Upload UI: <http://localhost:5000>
   - Health check: <http://localhost:5000/health>
   - TC login: <http://localhost:5000/tc/login>

## Required environment variables

```env
DATABASE_URL=postgresql://user:pass@host:port/dbname
TWILIO_ACCOUNT_SID=
TWILIO_AUTH_TOKEN=
TWILIO_PHONE_NUMBER=
AWS_ACCESS_KEY_ID=
AWS_SECRET_ACCESS_KEY=
AWS_S3_BUCKET_DOCUMENTS=maverick-documents
AWS_S3_BUCKET_BACKUPS=maverick-backups
AWS_REGION=us-east-1
STRIPE_SECRET_KEY=
STRIPE_PUBLISHABLE_KEY=
STRIPE_WEBHOOK_SECRET=
STRIPE_ENV=dev
APP_BASE_URL=http://localhost:5000
SECRET_KEY=generate-random-secret-key
TC_USERNAME=margaret
TC_PASSWORD=secure-hashed-password
PAYPAL_EMAIL=pay@getmaverick.com
PAYPAL_HANDLE=getmaverick
VENMO_HANDLE=@GetMaverick
HEIDI_PHONE=
MARGARET_PHONE=
```

## Deploy to Railway

1. Provision PostgreSQL in Railway.
2. Run `schema.sql` in the PostgreSQL query editor.
3. Deploy this directory from GitHub.
4. Add environment variables from `.env`.
5. Configure Twilio webhook to:
   ```
   https://<your-railway-domain>/sms-webhook
   ```
6. Configure Stripe webhook to:
   ```
   https://<your-railway-domain>/stripe/webhook
   ```

## Suggested cron jobs (Railway)

- Daily reminders (8am): `0 8 * * *` -> `python send_reminders.py`
- Closing protocol morning (8am): `0 8 * * *` -> `python closing_protocol.py`
- Closing protocol midday (10am): `0 10 * * *` -> `python closing_protocol.py`
- Closing protocol evening (5pm): `0 17 * * *` -> `python closing_protocol.py`
- Problem detection (every 6h): `0 */6 * * *` -> `python check_problems.py`
- Stripe minions (recommended):
  - payment links: `0 */12 * * *` -> `python run_stripe_minions.py --minion payment-links`
  - dunning: `0 */6 * * *` -> `python run_stripe_minions.py --minion dunning`
  - reconciliation: `30 6 * * *` -> `python run_stripe_minions.py --minion reconciliation`

## Stripe minions

Instruction pack:
- `STRIPE_MINIONS_INSTRUCTIONS.md`
- `minions/stripe_minions_context.example.json`
- `STRIPE_DEV_SETUP.md`
- `AGENT_EXECUTION_PLAYBOOK.md`

Run all minions in dry-run mode:

```bash
python run_stripe_minions.py --all --dry-run
```

Print the Stripe minion briefing payload:

```bash
python minions/briefing.py
```

Validate Stripe.dev configuration:

```bash
python stripe_dev_bootstrap.py --check-api
```

One-shot Stripe.dev bring-up (from repo root):

```bash
make stripe-dev-up
```

## Week 7 launch testing (one command)

Run the launch smoke harness:

```bash
python run_launch_checks.py
```

It validates:
- Core Flask routes (`/health`, `/`, `/upload`, `/pay/...`)
- Stripe and database env key readiness
- `send_reminders.py --dry-run`
- `check_problems.py --dry-run`
- `run_stripe_minions.py --all --dry-run`

Exit code is non-zero if any check fails.

## Notes

- The `uploads/` folder is ignored and reserved for temporary local storage.
- The backup script expects `pg_dump` and `aws` CLI binaries in the runtime image.
