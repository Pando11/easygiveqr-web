# Maverick Transaction Coordinator

Maverick is a Flask-based transaction coordination platform for Texas real estate teams. It combines contract intake, deadline/task workflows, secure document handling, payment collection, and automated operational reminders.

## Project overview

Core capabilities:
- Agent contract upload and intake
- TC dashboard and transaction detail workspace
- Deadline and task management
- Document storage with AWS S3 + access logs
- Stripe card payments plus Venmo/PayPal fallback links
- Twilio SMS reminders, updates, and escalation alerts
- Automation scripts for reminders, closing protocol, problem detection, and nightly backups

## Local setup instructions

1. From this folder (`maverick/`), create and activate a virtual environment:
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
4. Fill in all required values in `.env`.
5. Run database schema (`schema.sql`) against your Postgres database.

## Environment variables

```env
DATABASE_URL=postgresql://user:pass@host:port/dbname
DATABASE_SSLMODE=
DATABASE_CONNECT_TIMEOUT=8

SECRET_KEY=generate-random-secret-key
APP_BASE_URL=http://localhost:5000

TC_USERNAME=margaret
TC_PASSWORD=secure-hashed-password

TWILIO_ACCOUNT_SID=
TWILIO_AUTH_TOKEN=
TWILIO_PHONE_NUMBER=
HEIDI_PHONE=
MARGARET_PHONE=

AWS_ACCESS_KEY_ID=
AWS_SECRET_ACCESS_KEY=
AWS_REGION=us-east-2
AWS_S3_BUCKET_DOCUMENTS=maverick-documents
AWS_S3_BUCKET_BACKUPS=maverick-backups

STRIPE_ENV=dev
STRIPE_SECRET_KEY=
STRIPE_PUBLISHABLE_KEY=
STRIPE_WEBHOOK_SECRET=

VENMO_HANDLE=@GetMaverick
PAYPAL_EMAIL=pay@getmaverick.com
PAYPAL_HANDLE=getmaverick
```

## Run locally

```bash
python app.py
```

Useful endpoints:
- Agent upload: `http://localhost:5000/`
- TC login: `http://localhost:5000/tc`
- Health check: `http://localhost:5000/health`

## Deploy to Railway

This repository is configured to run Maverick from repo root using:
- `Procfile`: `web: gunicorn app:app --chdir maverick`
- `runtime.txt`: `python-3.11.7`

Deployment steps:
1. Push code to GitHub.
2. Create a Railway project and connect the repository.
3. Add all environment variables listed in `.env.example`.
4. Provision PostgreSQL and run `maverick/schema.sql`.
5. Deploy and verify:
   - `/health` returns `{"status":"ok", ...}`
   - upload + TC login flows work
6. Configure webhooks:
   - Twilio -> `https://<your-domain>/sms-webhook`
   - Stripe -> `https://<your-domain>/stripe/webhook`

## Cron job setup (Railway)

See `RAILWAY_CRONS.md` for copy/paste schedules and commands for:
- `send_reminders.py`
- `closing_protocol.py`
- `check_problems.py`
- `backup_db.sh`

## Additional operational docs

- `MARGARET_TRAINING_MANUAL.md`
- `STRIPE_MINIONS_INSTRUCTIONS.md`
- `STRIPE_DEV_SETUP.md`
- `LAUNCH_CHECKLIST.md`
