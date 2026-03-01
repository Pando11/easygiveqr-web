# Maverick API Documentation

This document covers API-style routes used by mobile clients and the tokenized client portal.

## Authentication

### Mobile JWT

1. Obtain token:
   - `POST /api/mobile/login`
   - Body:
     ```json
     {
       "username": "margaret",
       "password": "your-tc-password"
     }
     ```
2. Use token:
   - Header: `Authorization: Bearer <access_token>`

## Mobile Endpoints

### Dashboard
- `GET /api/mobile/dashboard`

### Daily checklist
- `GET /api/mobile/daily-checklist`

### Task completion
- `POST /api/mobile/task/<task_id>/complete`
- Body:
  ```json
  { "completed": true }
  ```

### Call completion
- `POST /api/mobile/call/<deadline_id>/complete`
- Body:
  ```json
  { "made": true }
  ```

### Documents
- `GET /api/mobile/transaction/<transaction_id>/documents`

### Communications
- `GET /api/mobile/transaction/<transaction_id>/communications`
- `POST /api/mobile/transaction/<transaction_id>/communications`
- Body:
  ```json
  {
    "communication_type": "phone_call",
    "contact_party": "agent",
    "contact_name": "Optional Name",
    "summary": "Called to confirm timeline",
    "outcome": "Waiting on lender update",
    "follow_up_date": "2026-02-20"
  }
  ```

## Client Portal Endpoints

Client portal uses a unique token URL and does not require login credentials.

### Overview
- `GET /client/<access_token>`

### Timeline
- `GET /client/<access_token>/timeline`

### Documents + upload view
- `GET /client/<access_token>/documents`

### Upload signed document
- `POST /client/<access_token>/upload`
- Form fields:
  - `document_type`
  - `document_file` (pdf/jpg/jpeg/png)

## TC Utility Route

### Generate or re-send client portal links
- `POST /tc/transaction/<transaction_id>/generate-client-portal`

### Force timeline packet resend
- `POST /tc/transaction/<transaction_id>/resend-timeline`

### Document analysis dashboard
- `GET /tc/transaction/<transaction_id>/document-analysis`

### Mark analysis reviewed / add notes
- `POST /tc/transaction/<transaction_id>/document-analysis/<analysis_id>/review`

### Override auto-created analysis task
- `POST /tc/transaction/<transaction_id>/document-analysis/override-task`
- Form body:
  - `task_id`

## TC Extraction Verification Routes

### Save verified extraction values
- `POST /tc/transaction/<transaction_id>/verify-extraction`
- Form fields (required):
  - `verified_effective_date` (YYYY-MM-DD)
  - `verified_closing_date` (YYYY-MM-DD)
  - `verified_buyer_name`
  - `verified_seller_name`
  - `verified_property_address`

### Legacy alias (still accepted)
- `POST /tc/transaction/<transaction_id>/confirm-extraction`

## Extraction Engine Notes

Contract uploads trigger asynchronous triple-scan extraction:

1. OCR: `pdf2image` + `pytesseract`
2. Direct text: `PyPDF2`
3. Layout-aware text: `pdfplumber`

The system writes field-level confidence rows to `contract_extractions` and requires manual verification before approval.

## Automated HOA / Inspection / Appraisal Analysis

When these document types are uploaded:
- HOA: `hoa`, `hoa_documents`, `hoa_docs`
- Inspection: `inspection`, `inspection_report`
- Appraisal: `appraisal`, `appraisal_report`

Maverick:
1. Downloads the PDF from S3
2. Runs triple-scan extraction (OCR + PyPDF2 + pdfplumber)
3. Flags findings only when at least `2/3` methods agree
4. Stores analysis in `document_analysis_results`
5. Executes action items (alerts/tasks) with smart thresholds

## Vendor Outreach Response Endpoint

Vendor outreach emails include a secure response URL:

- `GET /vendor/outreach/<access_token>`  
  Shows a simple response form for vendor scheduling confirmation.

- `POST /vendor/outreach/<access_token>`  
  Accepts:
  - `response_status` (`confirmed`, `needs_call`, `unable`)
  - `appointment_at` (optional datetime-local)
  - `notes` (optional)

When submitted, Maverick:
- Logs response on `vendor_outreach`
- Creates `calendar_events` row if appointment was provided
- Marks linked coordination/follow-up task(s) complete
- Writes communication audit note

## Automated Vendor Scheduling Endpoints

### Auto-send preferred vendor requests
- Triggered in: `POST /tc/transaction/<transaction_id>/approve`
- Behavior:
  - Selects preferred active vendor contacts by type and optional service-area match
  - Sends templated emails under `templates/emails/vendor_requests/`
  - Logs outreach events to `vendor_outreach_log`
  - Creates follow-up tasks when response is pending

### Vendor scheduling webhook
- `POST /vendor-response/<transaction_id>/<vendor_type>`
- Accepts JSON payload fields:
  - `scheduled_time` or `scheduled_at` or `start_time` (ISO datetime preferred)
  - `vendor_id` (optional)
  - `notes` (optional)
- Behavior:
  - Logs `scheduled` outreach event on `vendor_outreach_log`
  - Marks pending follow-up task(s) complete for that vendor type
  - Sends SMS confirmation to Margaret

### Vendor management (TC)
- `GET|POST /tc/vendors`
- Actions via form `action`:
  - `add` (create vendor contact)
  - `update` (edit existing contact)
  - `toggle_active` (activate/deactivate vendor)

## Intelligent Deadline Nudges

### Daily nudge automation script
- `python3 automation/intelligent_nudges.py`
- Typical cron schedule: `0 7 * * *`
- Behavior:
  - scans active transactions + open deadlines
  - applies per-type timing/config from `nudge_settings`
  - sends SMS + email nudges from `templates/nudges/`
  - logs sends to `nudge_log`
  - avoids duplicate sends per `(transaction_id, deadline_id, nudge_type)`

### SMS nudge response webhook
- `POST /nudge-response`
- Twilio form fields:
  - `From`
  - `Body`
- Behavior:
  - resolves most recent unresolved `nudge_log` row for sender phone
  - positive response (`yes`, `scheduled`, `done`) -> marks responded + completes related tasks
  - help response (`help`, `call`) -> marks escalated + alerts Margaret
  - unclear response -> forwards summary to Margaret

### Nudge analytics dashboard (TC)
- `GET /tc/nudge-analytics`
- Shows:
  - nudges sent per week
  - response rate by nudge type
  - estimated time saved (resolved without escalation)
  - most effective nudge types/messages
  - agent response behavior

### Nudge settings dashboard (TC)
- `GET|POST /tc/nudge-settings`
- Actions via form `action`:
  - `update_setting` (enable toggle, lead days, template names, custom message overrides)
  - `add_whitelist` (skip nudges for specific agents)
  - `remove_whitelist` (disable whitelist entry)

## Timeline Packet Automation Notes

Timeline packet dispatch is signature-driven:
- Initial send on transaction approval
- Automatic re-send when tracked milestone signature changes (closing date, major deadlines, repair timeline additions)
- Stored in `timeline_packets` for idempotency and audit trail

## Inbound Email AI Routing Endpoints

### Inbound webhook receiver
- `POST /webhooks/inbound-email`
- Auth:
  - Optional shared secret via `INBOUND_EMAIL_WEBHOOK_SECRET`
  - Pass as header `X-Inbound-Secret` (or query/form `secret`)

Accepted payload fields (provider-dependent):
- Recipient fields: `to`, `recipient`, `delivered_to`, `envelope_to`, `envelope`
- Sender fields: `from`, `sender`
- Message fields: `subject`, `text` / `body-plain` / `stripped-text` / `body`
- Optional provider message id: `message_id`, `Message-Id`, `Message-ID`

### Save inbound routing rule (TC)
- `POST /tc/transaction/<transaction_id>/inbound-email-rule`
- Form fields:
  - `sender_role` (`lender`, `buyer`, `seller`, `agent`, `inspector`, `title_company`, etc.)
  - `always_notify_margaret` (`true`/`false`)
  - `forward_policy` (`default`, `all`, `never`)

### Override one inbound message route (TC)
- `POST /tc/transaction/<transaction_id>/inbound-email/<message_id>/override`
- Form fields:
  - `override_route` (`log_only`, `medium_awareness`, `high_action`)
  - `override_notes` (optional)
  - `clear_risk` (`true` to clear at-risk state)

## SMS Webhook Behavior (Nudge Replies)

Route:
- `POST /sms-webhook`

In addition to emergency/status handling, Maverick now supports proactive nudge replies:
- If agent replies `YES` to inspection-scheduling nudge:
  - sends inspector recommendations list
  - logs interaction
  - marks nudge responded (no Margaret escalation)
- If agent asks for help (e.g., includes `margaret`/`need help`):
  - marks nudge responded + help requested
  - escalates to Margaret checklist
  - sends Margaret alert SMS
