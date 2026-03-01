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
- Automated HOA/Inspection/Appraisal document analysis with action-item automation
- Auto-generated timeline PDF packet (with milestone chart) + multi-party email distribution
- Vendor outreach automation (inspector/appraiser/survey/title) with secure confirmation links
- Transaction-specific inbound email aliases with AI urgency/category routing
- Proactive deadline nudges with two-step escalation and SMS YES inspector recommendations
- Intelligent nudge automation with configurable timing/templates + response analytics
- AI-powered problem detection with health scoring, recommendations, and one-click action execution
- Bulk SMS broadcasting with smart variables, preview, filtering, and paced queue sends
- Rule-based auto-task completion with confidence safeguards, undo tracking, and weekly time-saved metrics
- Automation scripts for reminders, closing protocol, problem detection, task auto-completion, and nightly backups

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
TWILIO_VOICE_URL=http://demo.twilio.com/docs/voice.xml
HEIDI_PHONE=
MARGARET_PHONE=
MARGARET_EMAIL=margaret@getmaverick.com
INBOUND_EMAIL_DOMAIN=getmaverick.com
INBOUND_EMAIL_WEBHOOK_SECRET=

AWS_ACCESS_KEY_ID=
AWS_SECRET_ACCESS_KEY=
AWS_REGION=us-east-2
AWS_S3_BUCKET_DOCUMENTS=maverick-documents
AWS_S3_BUCKET_BACKUPS=maverick-backups

INSPECTOR_NAME=Inspection Team
INSPECTOR_EMAIL=
INSPECTOR_CALENDLY_URL=
INSPECTOR_RECOMMENDATIONS=Inspector One | (214) 555-0101 | one@example.com; Inspector Two | (817) 555-0102 | two@example.com
APPRAISER_NAME=Appraisal Team
APPRAISER_EMAIL=
APPRAISER_CALENDLY_URL=
SURVEY_COMPANY_NAME=Survey Team
SURVEY_COMPANY_EMAIL=
SURVEY_CALENDLY_URL=
TITLE_COORDINATION_NAME=Title Team
TITLE_COORDINATION_EMAIL=
TITLE_CALENDLY_URL=

STRIPE_ENV=dev
STRIPE_SECRET_KEY=
STRIPE_PUBLISHABLE_KEY=
STRIPE_WEBHOOK_SECRET=
ANTHROPIC_API_KEY=

VENMO_HANDLE=@GetMaverick
PAYPAL_EMAIL=pay@getmaverick.com
PAYPAL_HANDLE=getmaverick
SMTP_HOST=smtp.gmail.com
SMTP_PORT=587
SMTP_USER=notifications@getmaverick.com
SMTP_USERNAME=
SMTP_PASSWORD=your_app_password
SMTP_FROM_EMAIL=
SMTP_FROM_NAME=Maverick TC
ENABLE_LEGACY_DEADLINE_NUDGES=false
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

## Automated HOA / Inspection / Appraisal Analysis

Uploaded HOA, inspection, and appraisal documents are analyzed with triple-scan text extraction.

Dashboard route:
- `GET /tc/transaction/<transaction_id>/document-analysis`

Review/action routes:
- `POST /tc/transaction/<transaction_id>/document-analysis/<analysis_id>/review`
- `POST /tc/transaction/<transaction_id>/document-analysis/override-task`

## Timeline Packet + Vendor Outreach Automation

After Margaret approves and activates a transaction, Maverick:

1. Generates a professional timeline PDF packet (all deadlines, weekly expectations, key contacts, moving checklist)
2. Uploads/stores the packet in S3 and transaction documents
3. Emails packet updates to buyer, seller, agent, lender, and title contacts
4. Sends vendor outreach emails to inspector/appraiser/survey/title with scheduling + secure confirmation links
5. Auto-creates follow-up tasks if vendors do not respond within 24 hours

Relevant routes:
- `POST /tc/transaction/<transaction_id>/resend-timeline`
- `GET|POST /vendor/outreach/<access_token>`
- `POST /vendor-response/<transaction_id>/<vendor_type>` (vendor scheduling webhook)
- `GET|POST /tc/vendors` (vendor directory + performance management)

## AI Problem Detection + Health Report

Maverick runs an AI-backed risk scan every 6 hours to detect transactions that are:
- behind schedule
- at appraisal risk
- inspection-risk prone
- lender-stalled
- closing at risk
- payment/document constrained

Routes:
- `GET /tc/health-report`
- `POST /tc/suggestion/<transaction_id>/accept`
- `GET|POST /tc/problem-detection-settings`

## Bulk SMS Broadcasting

Margaret can send announcements/reminders at scale without copy/paste:

- Route: `GET|POST /tc/bulk-messages`
- Features:
  - built-in + custom template library
  - smart variables (`{{PROPERTY_ADDRESS}}`, `{{BUYER_NAME}}`, `{{CLOSING_DATE}}`, etc.)
  - filtering by active scope/closing this week/specific status
  - targeting by party type (buyer/seller/agent/all)
  - preview before send
  - queued processing at 1 SMS/sec with progress reporting

## Auto Task Completion Engine

Maverick can auto-complete low-risk checklist items based on evidence rules:

- Rule table: `task_completion_rules`
- Run log: `task_auto_completion_log`
- Trigger types:
  - `document_uploaded`
  - `vendor_response`
  - `email_received`
- Safety controls:
  - never auto-completes high-stakes tasks (e.g., final CD verification)
  - confidence below 80% is flagged for Margaret review, not completed
  - Margaret can undo auto-completed tasks from the existing task toggle

Manual + scheduled runs:
- Manual route: `POST /tc/task-completion/run`
- Cron script: `python3 automation/task_auto_completion.py` (every 15 minutes recommended)

## Inbound Email AI Routing

Each transaction exposes unique mailbox aliases:
- `transaction-<id>-buyer@<INBOUND_EMAIL_DOMAIN>`
- `transaction-<id>-seller@<INBOUND_EMAIL_DOMAIN>`
- `transaction-<id>-lender@<INBOUND_EMAIL_DOMAIN>`

Inbound webhook route:
- `POST /webhooks/inbound-email`

Behavior:
- Logs inbound email to transaction communication timeline
- Classifies urgency/category/action-required
- Routes by severity (log-only, relevant forward, or high-action alert)
- Supports sensitive handling (e.g., buyer concerns not forwarded to seller)
- Supports per-transaction routing rules (e.g., always notify Margaret for lender emails)

## Intelligent Nudge Automation

Maverick includes a dedicated proactive nudge engine:

- Script: `automation/intelligent_nudges.py`
- Suggested cron: daily at 7:00 AM
- Nudge logs: `nudge_log`
- Settings + whitelist:
  - `GET|POST /tc/nudge-settings`
  - `GET /tc/nudge-analytics`
- Twilio response route:
  - `POST /nudge-response`

Duplicate prevention:
- no duplicate send for the same `(transaction, deadline, nudge_type)`
- skipped when response already received
- skipped when a matching Margaret follow-up task has already been completed

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
   - Intelligent nudge replies (optional dedicated endpoint) -> `https://<your-domain>/nudge-response`
   - Stripe -> `https://<your-domain>/stripe/webhook`

## Cron job setup (Railway)

See `RAILWAY_CRONS.md` for copy/paste schedules and commands for:
- `send_reminders.py`
- `closing_protocol.py`
- `automation/problem_detector.py`
- `automation/task_auto_completion.py`
- `backup_db.sh`

`send_reminders.py` now also runs the proactive deadline nudge engine:
- Sends first/second nudges when progress is missing
- Escalates to Margaret checklist only when:
  - no response after 2 nudges and deadline within 48h, or
  - a party explicitly asks for Margaret help
- Supports agent SMS `YES` response flow for inspector recommendations

## Additional operational docs

- `MARGARET_TRAINING_MANUAL.md`
- `CLIENT_PORTAL_USER_GUIDE.md`
- `API_DOCUMENTATION.md`
- `EXTRACTION_VERIFICATION_GUIDE.md`
- `DOCUMENT_ANALYSIS_USER_GUIDE.md`
- `STRIPE_MINIONS_INSTRUCTIONS.md`
- `STRIPE_DEV_SETUP.md`
- `LAUNCH_CHECKLIST.md`
