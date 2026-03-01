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
- Client portal links for buyer/seller timeline + document upload
- Triple-scan AI contract extraction with confidence verification (OCR + PyPDF2 + pdfplumber)
- Automated HOA/Inspection document analysis with action-item automation
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
CLIENT_PORTAL_BASE_URL=https://maverick.com

TC_USERNAME=margaret
TC_PASSWORD=secure-hashed-password
MOBILE_JWT_EXP_HOURS=12

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
ANTHROPIC_API_KEY=

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
- Client portal: `http://localhost:5000/client/<access_token>`

## Mobile API (JWT)

Mobile clients authenticate with TC credentials and receive a bearer token.

1. Login:
   - `POST /api/mobile/login`
   - Body: `{"username":"margaret","password":"..."}`
   - Response includes `access_token`
2. Use token:
   - Header: `Authorization: Bearer <access_token>`
3. Key MVP endpoints:
   - `GET /api/mobile/dashboard`
   - `GET /api/mobile/daily-checklist`
   - `POST /api/mobile/task/<task_id>/complete`
   - `GET /api/mobile/transaction/<transaction_id>/documents`
   - `POST /api/mobile/call/<deadline_id>/complete`
   - `GET /api/mobile/transaction/<transaction_id>/communications`
   - `POST /api/mobile/transaction/<transaction_id>/communications`

## Client Portal Routes

These routes power buyer/seller client access using secure UUID tokens:

- `GET /client/<access_token>` (portal overview)
- `GET /client/<access_token>/timeline` (timeline)
- `GET /client/<access_token>/documents` (documents + upload UI)
- `POST /client/<access_token>/upload` (signed document upload)

TC actions:
- `POST /tc/transaction/<transaction_id>/generate-client-portal`
- `GET /tc/transaction/<transaction_id>/document-analysis`

## Contract Extraction Verification

Maverick runs three extraction methods on uploaded contracts and compares agreement:

- Method 1: OCR (Tesseract via `pdf2image` + `pytesseract`)
- Method 2: Direct text (`PyPDF2`)
- Method 3: Layout-aware text (`pdfplumber`)

Verification workflow routes:
- `POST /tc/transaction/<transaction_id>/verify-extraction` (save Margaret verified values)

Approval gating:
- Transaction approval requires all required extraction fields to be verified.

## Automated HOA / Inspection Analysis

Uploaded HOA and inspection documents are analyzed with triple-scan text extraction.

Dashboard route:
- `GET /tc/transaction/<transaction_id>/document-analysis`

Review/action routes:
- `POST /tc/transaction/<transaction_id>/document-analysis/<analysis_id>/review`
- `POST /tc/transaction/<transaction_id>/document-analysis/override-task`

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
- `CLIENT_PORTAL_USER_GUIDE.md`
- `API_DOCUMENTATION.md`
- `EXTRACTION_VERIFICATION_GUIDE.md`
- `DOCUMENT_ANALYSIS_USER_GUIDE.md`
- `STRIPE_MINIONS_INSTRUCTIONS.md`
- `STRIPE_DEV_SETUP.md`
- `LAUNCH_CHECKLIST.md`
