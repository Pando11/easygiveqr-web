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
- Twilio voice-note capture with transcription, auto task actions, and communication-log playback
- Smart document classification + renaming before S3 save, with Margaret correction learning loop
- Automated weekly agent status updates (preview/edit/send controls, schedule choice, opt-out list)
- Dynamic closing checklist generator (3-day trigger, Margaret review, 24-hour auto-send fallback, PDF + interactive + SMS)
- Smart Q&A assistant with semantic matching, Margaret approval workflow, and auto-answer learning
- Google Calendar sync for deadlines/inspections/appraisals/closings with color coding, manual overrides, and webhook updates
- Automation scripts for reminders, closing protocol, problem detection, task auto-completion, closing checklists, and nightly backups

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
TWILIO_VOICE_NOTE_NUMBER=
VOICE_NOTE_TRANSCRIPTION_MODE=twilio
VOICE_NOTE_CLAUDE_MODEL=claude-sonnet-4-20250514
VOICE_NOTE_WEBHOOK_SECRET=
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
DOCUMENT_CLASSIFIER_MODEL=claude-sonnet-4-20250514

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
COMMON_QA_EMBEDDING_DIMENSIONS=128
COMMON_QA_SIMILARITY_THRESHOLD=0.85
COMMON_QA_SUGGEST_CONFIDENCE=75
COMMON_QA_AUTO_CONFIDENCE=95
COMMON_QA_AUTO_ENABLE_REUSE_COUNT=5
COMMON_QA_VARIANT_SIMILARITY_THRESHOLD=0.82

ENABLE_GOOGLE_CALENDAR_SYNC=true
GOOGLE_CALENDAR_CREDENTIALS=
GOOGLE_CALENDAR_ID=primary
GOOGLE_CALENDAR_TIMEZONE=America/Chicago
GOOGLE_CALENDAR_DELEGATED_USER=
GOOGLE_CALENDAR_REFRESH_TOKEN=
GOOGLE_CALENDAR_CLOSING_DEFAULT_TIME=09:00
GOOGLE_CALENDAR_CLOSING_DURATION_MINUTES=60
GOOGLE_CALENDAR_COLOR_DEADLINE=5
GOOGLE_CALENDAR_COLOR_INSPECTION=9
GOOGLE_CALENDAR_COLOR_CLOSING=11
GOOGLE_CALENDAR_COLOR_APPRAISAL=10
CALENDAR_WEBHOOK_SECRET=
MORNING_BRIEFING_SEND_TIME=07:30
EVENING_RECAP_SEND_TIME=14:00
MORNING_BRIEFING_TIMEZONE=America/Chicago
MORNING_BRIEFING_MODEL=claude-sonnet-4-20250514
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

## Smart Document Processing

On document upload, Maverick now:

1. extracts first-page text
2. classifies document type using Claude (with heuristic fallback)
3. renames file using a standard pattern before S3 upload
4. auto-executes document-specific actions (task completion, earnest receipt updates, analysis triggers)

Margaret override route:
- `POST /tc/document/<document_id>/classification-correction`

Corrections are stored in `document_classification_corrections` and used to improve future type mapping.

## Automated Agent Status Updates

Maverick can send weekly progress emails to agents for each active transaction:

- TC control route: `GET|POST /tc/status-updates`
- Scheduler script: `python3 automation/agent_status_updates.py`
- Schedule options:
  - Monday at 8:00 AM
  - Friday at 5:00 PM
- Features:
  - preview before send
  - editable subject/body templates with smart tokens
  - per-agent opt-out list
  - manual "send now" trigger
  - call/text reduction tracking (estimated "questions answered" metric)

## Dynamic Closing Checklists

Maverick can generate a transaction-specific closing checklist exactly 3 days before closing:

- TC queue route: `GET|POST /tc/closing-checklists`
- Transaction trigger route: `POST /tc/transaction/<transaction_id>/generate-closing-checklist`
- Review/edit/send route: `GET|POST /tc/closing-checklist/<checklist_id>`
- Public interactive route: `GET /closing-checklist/<access_token>`
- Scheduler script: `python3 automation/closing_checklists.py` (hourly recommended)

Generation behavior:
- starts from a base checklist template
- customizes buyer cash-to-close estimate
- adds repair verification section when repair addendum content is detected
- adds HOA special-assessment item when analysis indicates one
- appends lender-specific requirement section
- appends contract special-provision checklist items when extracted

Distribution behavior:
- Margaret can add/remove/toggle items before approval
- approved checklist sends to parties in multi-format:
  - printable PDF link
  - interactive checklist link in Maverick (checkboxes shared across parties)
  - SMS mini-version summary
- if not reviewed within 24 hours, it auto-sends with a disclaimer

## Smart Q&A Assistant

Maverick can detect repeated inbound questions and suggest or auto-send approved answers:

- TC management route: `GET|POST /tc/common-qa`
- Inbound email reply route: `POST /tc/transaction/<transaction_id>/inbound-email/<message_id>/reply`
- Inbound intake integration:
  - `POST /webhooks/inbound-email`
  - `POST /sms-webhook` (agent SMS question flow)

Decision model:
- semantic match against `common_qa` using cosine similarity
- if confidence > 95% and auto-answer enabled: auto-send answer
- if confidence > 75%: suggest answer to Margaret
- otherwise: regular manual response flow

Learning model:
- suggested answer used -> `times_reused` increments
- at reuse threshold (`COMMON_QA_AUTO_ENABLE_REUSE_COUNT`, default 5), auto-answer is enabled
- major Margaret edits create a new variant entry
- new manual replies are saved as future common Q&A candidates

Analytics:
- monthly time saved estimate (hours)
- most common question list
- FAQ draft suggestion block for agent-facing documentation

## Google Calendar Integration

Maverick can sync key transaction events directly to Margaret's Google Calendar:

- Management route: `GET|POST /tc/calendar-sync`
- Transaction sync route: `POST /tc/transaction/<transaction_id>/calendar-sync`
- Transaction closing preferences route: `POST /tc/transaction/<transaction_id>/calendar-closing`
- Two-way webhook route: `GET|POST /calendar-webhook`

OAuth setup:
1. In Google Cloud Console, enable **Google Calendar API**.
2. Create OAuth or service-account credentials with calendar write access.
3. Put the credentials JSON into Railway env var `GOOGLE_CALENDAR_CREDENTIALS`.
4. Set `GOOGLE_CALENDAR_ID` (`primary` or a shared calendar ID).
5. (Optional) Configure `CALENDAR_WEBHOOK_SECRET` for webhook validation.

Auto-sync triggers:
- deadline creation/recreation -> all deadline events are synced as yellow all-day events
- vendor inspection/appraisal scheduling -> timed blue/green events
- closing date/time changes -> timed red closing event update
- transaction cancellation -> synced events are deleted (when enabled)

Color coding defaults:
- Deadlines: yellow (`colorId=5`)
- Inspections: blue (`colorId=9`)
- Closings: red (`colorId=11`)
- Appraisals: green (`colorId=10`)

Two-way behavior:
- when enabled, webhook payload updates can push event-time changes from Google Calendar back into Maverick deadlines, vendor appointment records, and closing timing preferences.

## Intelligent Morning Briefing + 2 PM Recap

Maverick now supports an AI-powered briefing workflow tailored to Margaret:

- Interactive route: `GET|POST /tc/morning-briefing`
- Item update route: `POST /tc/morning-briefing/item/<item_id>/update`
- Reorder route: `POST /tc/morning-briefing/item/<item_id>/move`
- Automation script: `python3 automation/morning_briefing.py`
  - Morning mode: `--mode morning`
  - Evening recap mode: `--mode evening`
  - Both: `--mode both`
  - Preview without send: `--dry-run`

Morning briefing behavior:
- gathers active transactions, urgent problem-detector items, calls, overdue/due-today tasks, pending decisions, and good-news wins
- learns Margaret's prioritization patterns from prior interactive completion/defer behavior
- generates:
  - SMS summary (urgent + actionable)
  - detailed email briefing (priority order, pattern highlights, batching suggestions, time estimate)
- stores an interactive item list where Margaret can:
  - check off completed items
  - reorder priorities
  - add notes
  - defer tasks to tomorrow
  - use one-click call/text/email links

2 PM recap behavior:
- summarizes what was completed vs. still pending
- highlights rollover items for tomorrow
- includes completion celebrations
- sends via SMS + email

## Automation Analytics Dashboard

- Route: `GET /tc/analytics`
- Consolidates:
  - time-savings metrics (daily/weekly/monthly)
  - quality metrics (classification/completion accuracy, missed deadlines, satisfaction)
  - engagement metrics (question reduction, review response rate, referrals)
  - feature adoption + time-saved-by-feature rankings

## Intelligent Text Expansion Templates

Margaret can now use shortcode-triggered text expansion from any standard text input/textarea across TC pages.

- Management route: `GET|POST /tc/templates`
- API search route: `GET /api/templates/search?q=/clo`
- API expansion route: `POST /api/templates/expand`
- Backing table: `message_templates`
  - columns: `shortcode`, `template_text`, `category`, `usage_count`, `created_at`
  - seeded with 30 common templates (closing, inspection, payment, docs, etc.)

Highlights:
- slash autocomplete dropdown appears while typing (desktop + mobile/touch)
- selecting a template expands variables using live transaction context
- tracks per-template usage counts
- supports custom create/edit workflows
- smart suggestions identify repeated phrases from communication history

## Batch Document Upload + Auto Assignment

Margaret can now upload many docs in one pass for AI-assisted assignment:

- Workspace route: `GET /tc/batch-upload`
- Analyze route: `POST /tc/batch-upload/analyze`
- Commit route: `POST /tc/batch-upload/commit`

Behavior:
- drag/drop up to 20 files (`pdf`, `jpg`, `jpeg`, `png`)
- each file is analyzed for likely document type + transaction match
- high-confidence matches are prefilled, low-confidence rows require manual review
- one-click commit uploads all approved docs, runs post-upload task automation, and launches async document analysis
- dashboard shows pending staged count and supports shortcut `Ctrl+U`

## Automatic Cascade Date Updates + Undo

Margaret can now update key transaction dates with a confirmation preview and controlled cascade behavior.

- API route: `POST /tc/transaction/<transaction_id>/update-date`
  - preview mode: `preview_only=true` to estimate updates/conflicts before apply
- Undo route: `POST /tc/transaction/<transaction_id>/update-date/undo`
- UI location: transaction detail page (`#date-cascade`)

Capabilities:
- conflict detection before apply:
  - closing date before appraisal appointment
  - closing date before financing approval date
  - weekend/holiday warnings with next-business-day suggestion
- partial cascades via checkboxes:
  - update deadlines
  - reschedule appointments
  - update tasks
  - sync Google Calendar
  - notify parties
- automatic timeline regeneration on date update
- 24-hour undo window with reverse notifications ("disregard previous message")

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

## Twilio Voice Notes

Margaret can call a dedicated voice-note number and dictate updates:

- Twilio webhook route: `POST /voice-note-webhook`
- Flow:
  1. greeting + beep prompt
  2. record up to 2 minutes
  3. transcription (`VOICE_NOTE_TRANSCRIPTION_MODE=twilio|claude`)
  4. parse transaction + actions
  5. auto log communication + optional task create/complete
  6. SMS confirmation to Margaret
- Safety:
  - if transaction ID cannot be parsed, transcript is texted to Margaret
  - if confidence `< 80%`, note is flagged for Margaret review before task automation

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
- `automation/agent_status_updates.py`
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
