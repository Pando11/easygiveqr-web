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
- `POST /tc/transaction/<transaction_id>/regenerate-timeline` (preferred alias)

### Document analysis dashboard
- `GET /tc/transaction/<transaction_id>/document-analysis`

### Mark analysis reviewed / add notes
- `POST /tc/transaction/<transaction_id>/document-analysis/<analysis_id>/review`

### Override auto-created analysis task
- `POST /tc/transaction/<transaction_id>/document-analysis/override-task`
- Form body:
  - `task_id`

### Smart document upload processing
- Applies to:
  - `POST /tc/transaction/<transaction_id>/upload-document`
  - `POST /client/<access_token>/upload`
- Behavior before S3 save:
  - extracts first-page text
  - classifies document type via Claude + heuristic fallback
  - generates normalized filename (`<type>_<property>_<date>.pdf`)
  - uploads with smart filename
  - triggers task/deadline actions by type (e.g., earnest receipt, inspection report)

### Classification correction (TC)
- `POST /tc/document/<document_id>/classification-correction`
- Form fields:
  - `corrected_document_type` (required)
  - `correction_reason` (optional)
- Behavior:
  - updates `documents.document_type`
  - logs correction in `document_classification_corrections`
  - retriggers document analysis pipeline for corrected type

## Bulk SMS Broadcasting (TC)

### Bulk messaging workspace
- `GET|POST /tc/bulk-messages`
- Capabilities:
  - smart variable template rendering (`{{PROPERTY_ADDRESS}}`, `{{BUYER_NAME}}`, etc.)
  - audience filters (`all_active`, `closing_this_week`, `specific_status`)
  - party targeting (`buyers_only`, `sellers_only`, `agents_only`, `all_parties`)
  - preview before queueing send
  - save custom template library entries

Form `action` options:
- `preview` (build recipient/message preview only)
- `queue_send` (enqueue send job at 1 SMS/second pacing)
- `save_template` (store reusable template)

### Bulk message job progress
- `GET /tc/bulk-messages/<job_id>/progress`
- Returns JSON status:
  - `queued` / `sending` / `completed` / `failed`
  - `total_recipients`, `sent_count`, `failed_count`, `progress_pct`

## Voice Notes (Twilio Voice)

### Voice note webhook
- `POST /voice-note-webhook`
- Twilio voice-number webhook target.
- Behavior:
  - initial call returns TwiML greeting + record prompt
  - records up to 120 seconds
  - stores recording metadata in `voice_notes`
  - queues transcription + action parsing

### Transcription callbacks (same route)
- `POST /voice-note-webhook?stage=transcription`
- Used by Twilio `transcribeCallback` when `VOICE_NOTE_TRANSCRIPTION_MODE=twilio`.

### Audio playback for TC communication log
- `GET /tc/voice-note/<voice_note_id>/audio`
- Login required; streams original recording audio from Twilio for in-app playback.

### Voice note execution behavior
- Parse JSON payload fields:
  - `transaction_id`
  - `note_type`
  - `content`
  - `complete_tasks[]`
  - `create_tasks[]`
  - `confidence`
- Actions:
  - logs communication (`communication_type=voice_note`)
  - completes matching open tasks
  - creates new follow-up tasks
  - sends SMS confirmation to Margaret
- Fallback/safety:
  - unresolved transaction id -> SMS transcript to Margaret
  - confidence `< 80` -> review task created, no auto task execution

## Task Auto-Completion

### Scheduled auto-completion script
- `python3 automation/task_auto_completion.py`
- Typical cron schedule: `*/15 * * * *`
- Behavior:
  - scans incomplete active-transaction tasks
  - matches tasks to `task_completion_rules`
  - evaluates trigger evidence (`document_uploaded`, `vendor_response`, `email_received`)
  - auto-completes when confidence >= 80 and not high-stakes
  - flags review note for Margaret when confidence < 80
  - logs every action to `task_auto_completion_log`

### Manual run from TC UI
- `POST /tc/task-completion/run`
- Triggers one immediate pass and redirects to `/tc/tasks` with run summary notice.

### Undo auto-completion
- Via existing task toggle route:
  - `POST /tc/task/<task_id>/toggle` with `{ "completed": false }`
- Behavior:
  - reopens task
  - records undo event on latest auto-completion log row

## Automated Agent Status Updates

### Status update settings + preview/send UI (TC)
- `GET|POST /tc/status-updates`
- Actions via form `action`:
  - `update_settings` (enable, schedule slot, subject template, body template)
  - `preview_now` (build per-agent update preview, no email send)
  - `send_now` (manual send immediately)
  - `add_opt_out` (disable updates for specific agent)
  - `remove_opt_out` (reactivate updates for opt-out entry)

### Scheduled status update script
- `python3 automation/agent_status_updates.py`
- Recommended cron schedule: hourly (`0 * * * *`)
- Runtime behavior:
  - checks configured slot (`monday_8am` or `friday_5pm`)
  - sends once per week for that slot (dedupe guard)
  - compiles each active transaction's weekly summary for the agent only
  - logs sends to `agent_status_update_runs` + `agent_status_update_messages`

### Email content model
- Weekly summary includes:
  - tasks completed this week
  - documents uploaded this week
  - communications received this week
  - upcoming deadlines (7-day horizon)
  - incomplete agent-action tasks
  - days to closing + health label + progress bar

## Dynamic Closing Checklist Generator

### TC checklist queue + manual trigger
- `GET|POST /tc/closing-checklists`
- Form actions:
  - `refresh_due` (run the 3-day trigger immediately)
  - `auto_send_now` (process pending 24-hour auto-send items immediately)

### Transaction-level checklist generation
- `POST /tc/transaction/<transaction_id>/generate-closing-checklist`
- Behavior:
  - builds checklist from base template
  - customizes buyer cash-to-close estimate
  - adds repair/HOA/lender/special-provision sections when detected
  - creates PDF and recipient access links
  - places checklist in `pending_review` for Margaret

### Margaret review/edit/send
- `GET|POST /tc/closing-checklist/<checklist_id>`
- Form actions:
  - `add_item`
  - `remove_item`
  - `toggle_item`
  - `regenerate_pdf`
  - `approve_send`
  - `resend_now`

### Public interactive checklist (tokenized)
- `GET /closing-checklist/<access_token>`
- `POST /closing-checklist/<access_token>/item/<item_id>/toggle`
- Behavior:
  - recipients can check/uncheck items in Maverick
  - updates shared checklist state for all participants
  - tracks recipient last-viewed timestamp

### Scheduled automation script
- `python3 automation/closing_checklists.py`
- Recommended cron schedule: hourly (`0 * * * *`)
- Runtime behavior:
  - generates checklists for active transactions closing in exactly 3 days
  - auto-sends checklists when unreviewed for 24 hours (with disclaimer)
  - sends multi-format output:
    - email update + interactive checklist link
    - printable PDF link
    - SMS mini-version summary

## Smart Q&A Assistant

### Management UI (TC)
- `GET|POST /tc/common-qa`
- Form actions:
  - `add` (create manual common Q&A)
  - `update` (edit answer/category/auto-answer)
  - `toggle_auto` (enable/disable auto-answer quickly)

### Inbound email reply + learning
- `POST /tc/transaction/<transaction_id>/inbound-email/<message_id>/reply`
- Form actions:
  - `use_suggested` (send suggested answer, increment reuse)
  - `send_custom` (send edited/new answer, learn variant/new entry)

### Inbound processing integration
- `POST /webhooks/inbound-email`
- Behavior:
  - evaluates semantic match against `common_qa`
  - decision logic:
    - confidence > 95% AND `auto_answer = true` -> auto-send answer
    - confidence > 75% -> suggest to Margaret
    - otherwise no suggestion
  - logs outcomes to:
    - `inbound_email_messages` (qa match/confidence/decision metadata)
    - `common_qa_events` (audit trail + analytics)

### Agent SMS integration
- `POST /sms-webhook`
- Behavior:
  - applies same threshold logic for non-emergency/non-status messages
  - can auto-answer by SMS when high confidence + auto-answer enabled
  - sends suggestion alert to Margaret when confidence is suggest-range

## Google Calendar Integration

### Management UI (TC)
- `GET|POST /tc/calendar-sync`
- Form actions:
  - `update_settings` (enable/disable sync + per-event-type toggles)
  - `sync_active_now` (bulk re-sync all active transactions)
  - `register_channel` (store Google watch channel metadata)

### Transaction-level controls
- `POST /tc/transaction/<transaction_id>/calendar-sync`
  - `action=sync` -> sync deadlines + closing + known vendor appointments
  - `action=delete_events` -> delete mapped Google Calendar events
- `POST /tc/transaction/<transaction_id>/calendar-closing`
  - Save closing time/location/duration preferences
  - Force update closing calendar event

### Auto triggers
- Deadline creation/rebuild flow:
  - `create_deadlines(...)` calls `sync_all_deadlines(...)`
- Vendor schedule events:
  - `POST /vendor-response/<transaction_id>/<vendor_type>`
  - `POST /vendor/outreach/<access_token>`
- Closing event updates:
  - transaction approval/verification flows and closing preference saves
- Cancellation cleanup:
  - `POST /tc/transaction/<transaction_id>/cancel`

### Two-way webhook endpoint
- `GET|POST /calendar-webhook`
- Security:
  - optional `CALENDAR_WEBHOOK_SECRET` via `X-Calendar-Secret` header (or `secret` param)
- Supported payload fields:
  - `event_id` (required for update matching)
  - `calendar_id` (optional, defaults to configured calendar id)
  - `start_time` / `end_time` or Google-style `start` / `end`
- Behavior:
  - resolves event in `google_calendar_mappings`
  - applies date/time updates back to Maverick (deadlines, closing, inspection/appraisal appointments)
  - writes audit + communication log entries

### Event color coding defaults
- Deadlines: Yellow (`colorId=5`, all-day events)
- Inspections: Blue (`colorId=9`, timed)
- Closings: Red (`colorId=11`, timed)
- Appraisals: Green (`colorId=10`, timed)

## Intelligent Morning Briefing

### Interactive routes (TC)
- `GET|POST /tc/morning-briefing`
  - Form actions:
    - `update_settings` (enable/disable, set morning send time + recap send time + timezone + AI toggle)
    - `generate_now` (force-generate morning briefing; optional send toggle)
    - `send_recap_now` (force-generate 2 PM recap; optional send toggle)
- `POST /tc/morning-briefing/item/<item_id>/update`
  - Actions:
    - `complete`
    - `reopen`
    - `defer` (with optional `deferred_to_date`)
  - Supports notes updates
- `POST /tc/morning-briefing/item/<item_id>/move`
  - `direction=up|down`

### Automation script
- `python3 automation/morning_briefing.py`
  - `--mode morning` (default)
  - `--mode evening`
  - `--mode both`
  - `--force`
  - `--dry-run`

### Data sources used
- Active transactions (`transactions.status='ACTIVE'`)
- Urgent problem detector rows (`problem_detection_results.bucket='urgent'`)
- Overdue + due-today tasks
- Pending decisions (intake approvals, analysis reviews, payment confirmations)
- Critical call queue from deadline windows
- Recent good news (completions, completed tasks, positive reviews)

## Intelligent Daily Plan + Time Blocking

### Interactive route (TC)
- `GET|POST /tc/daily-plan`
  - Form actions:
    - `generate_now` (force-generate plan; optional send + calendar sync toggles)
    - `reorganize_now` (manual adaptive reshuffle)

### Item update API
- `POST /tc/daily-plan/item/<item_id>/update`
- Auth: TC login required
- JSON/form fields:
  - `status`: `pending|completed|deferred|skipped`
  - `notes` (optional)
  - `actual_minutes` (optional)
  - `started_now` (optional boolean)
  - `completed_now` (optional boolean)
- Response includes updated item status + refreshed estimated end time.

### Reorder API (drag/drop)
- `POST /tc/daily-plan/reorder`
- JSON body:
  - `plan_id`
  - `ordered_item_ids` (array of item IDs in new order)

### Adaptive reshuffle API
- `POST /tc/daily-plan/reorganize`
- JSON body:
  - `plan_id`
  - `reason` (`running_behind|urgent_item|manual_reorganize|...`)
- Behavior:
  - recategorizes remaining tasks
  - reorders pending queue by current urgency
  - updates estimated end-time projection

### Automation script
- `python3 automation/generate_daily_plan.py`
  - `--force`
  - `--dry-run`
  - `--skip-calendar`

### Google Calendar integration
- Each generated block is synced as event type: `daily_plan_block`
- Mapping `source_ref` format: `daily_plan:<plan_id>:block:<block_id>`
- Existing daily-plan block events are replaced on regeneration/re-sync.

### Data model
- `daily_plans`
  - one row/day with summary, estimated end time, delivery + sync status
- `daily_plan_blocks`
  - scheduled block rows with start/end, tier, and color
- `daily_plan_items`
  - task rows inside blocks with status, estimate, and actual timing
- `daily_plan_learning_events`
  - reorder/replan/status signals used for estimate-learning analytics

## Automation Analytics Dashboard

### Route (TC)
- `GET /tc/analytics`

### Metrics included
- Time savings (daily / weekly / monthly):
  - manual tasks avoided
  - auto-completed tasks
  - auto-sent messages
  - questions auto-answered
  - time saved
  - transactions handled, avg hours/txn, efficiency improvement
  - capacity increase, revenue enabled, ROI
- Quality:
  - auto-classification error %
  - auto-completion error %
  - missed deadlines
  - client satisfaction average
- Engagement:
  - agent questions reduced %
  - review response rate
  - referrals generated
- Feature adoption:
  - bulk SMS uses/week
  - voice notes uses/week
  - auto-complete tasks/week
  - morning briefing read/not read
  - one-click completion uses/month
- Feature time savings:
  - auto-vendor scheduling (hrs/month)
  - problem detection (hrs/month)
  - bulk messaging (hrs/month)

## Intelligent Text Expansion Templates

### Management route (TC)
- `GET|POST /tc/templates`
- Form actions:
  - `create` (shortcode, category, template_text)
  - `update` (template_id + editable fields)
  - `delete` (unused templates only)
  - `create_from_suggestion` (auto-create from repeated phrase)

### Autocomplete API
- `GET /api/templates/search?q=/clo`
- Auth: TC login required
- Response: array of matching template objects (`id`, `shortcode`, `category`, `preview`, `usage_count`)

### Expansion API
- `POST /api/templates/expand`
- Auth: TC login required
- JSON body:
  - `template_id` (required)
  - `transaction_id` (optional; inferred from referrer when possible)
- Response:
  - `text`: expanded message with resolved `{{VARIABLES}}`
  - `unfilled_vars`: variable names that remained blank (`____`)
  - `template`: selected template metadata

### Data model
- Table: `message_templates`
  - `id SERIAL PRIMARY KEY`
  - `shortcode VARCHAR(50) UNIQUE`
  - `template_text TEXT`
  - `category VARCHAR(50)`
  - `usage_count INT DEFAULT 0`
  - `created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP`
- Includes seed set of 30 common templates on first-use table initialization.

## Scenario-Based Script Library

### Suggest scripts endpoint (TC)
- `POST /tc/transaction/<transaction_id>/suggest-scripts`
- Auth: TC login required
- JSON body:
  - `situation_type` (required; e.g. `appraisal_gap`, `inspection_negotiate`, `lender_delay`)
  - optional situation context fields:
    - `appraisal_value`
    - `inspection_items_count`
    - `estimated_cost`
    - `requested_credit`
    - `extension_days`
- Response:
  - `scenarios[]`
    - `scenario_id`
    - `scenario_name`
    - `category`
    - `usage_count`
    - `success_rate`
    - `approaches[]` with personalized `messages`
  - `stats`
    - `best_line` (top-performing approach summary)
    - `scenario_stats[]`
    - `approach_stats[]`

### Track usage endpoint (TC)
- `POST /tc/transaction/<transaction_id>/track-script-usage`
- Auth: TC login required
- JSON body:
  - `scenario_id` (required)
  - `approach_name` (required)
  - `recipient_role` (optional)
  - `message_text` (optional)
  - `situation_type` (optional)
  - `context` (optional object)
- Response:
  - `usage_id`
  - `used_at`

### Record script outcome endpoint (TC)
- `POST /tc/script-usage/<usage_id>/outcome`
- Auth: TC login required
- JSON body:
  - `outcome_success` (required boolean)
  - `resolution_minutes` (optional int)
  - `outcome_notes` (optional text)
- Behavior:
  - updates usage row with resolution outcome
  - recalculates scenario success rate

### Data model
- `communication_scenarios`
  - library scenarios with trigger JSON and script approaches JSON
- `communication_script_usage`
  - scenario/approach usage telemetry + success/time-to-resolution outcomes

### Seed behavior
- `ensure_communication_scenarios_table()` seeds 50 default scenarios on first use.

## Self-Service Party Portals

### Generate portal links (TC)
- `POST /tc/transaction/<transaction_id>/generate-portals`
- Auth: TC login required
- Optional inputs:
  - `buyer_email`
  - `seller_email`
  - `agent_email`
- Output (JSON mode):
  - `success`
  - `portals.buyer|seller|agent`
  - `sent_sms`
  - `sent_email`

### Public portal route
- `GET /portal/<access_token>`
- Behavior:
  - validates token and expiration
  - logs portal view analytics
  - enforces DB-backed rate limit
  - renders role-specific portal data (timeline, docs, to-do, updates)
  - enables upload section only for `agent` party type

### Section analytics tracking
- `POST /portal/<access_token>/track-section`
- Body:
  - `section` (`overview|timeline|documents|action_items|recent_activity|upload`)
- Logs section-view telemetry per transaction/party.

### Portal document download
- `GET /portal/document/<document_id>?token=<access_token>`
- Behavior:
  - validates portal token (or session token)
  - confirms document access is allowed for party role
  - logs download event + document access
  - redirects to S3 presigned URL

### Agent upload endpoint
- `POST /portal/<access_token>/upload`
- Auth: token-based portal access (`agent` only)
- Input: multipart files (max 20; `pdf|jpg|jpeg|png`)
- Output:
  - `success`, `uploaded`, `failed`, `document_ids[]`

### Portal analytics endpoint (TC)
- `GET /tc/transaction/<transaction_id>/portal-analytics`
- Returns:
  - `views`
  - `document_downloads`
  - `uploads`
  - `most_viewed_sections`
  - `text_questions_after_portal`
  - `estimated_support_minutes_saved`
  - `estimated_support_hours_saved`

### Security model
- Tokens expire at closing + grace window (`PORTAL_TOKEN_GRACE_DAYS`, default 30)
- All access events are logged in `party_portal_access_log`
- Rate limiting uses recent access-log counts by token hash + IP
- Buyer/seller portal views exclude sensitive financial document classes

### Data model
- `party_portal_access`
  - one active token row per transaction + party (`buyer|seller|agent`)
- `party_portal_access_log`
  - event telemetry (`view`, `section_view`, `document_download`, `upload`, `notification_sent`, etc.)
- `party_portal_notifications_log`
  - dedupe guard for milestone notifications

## Batch Document Upload

### Workspace route (TC)
- `GET /tc/batch-upload`
- Renders drag/drop upload UI and manual review controls for low-confidence assignment rows.

### Analyze route (TC)
- `POST /tc/batch-upload/analyze`
- Input:
  - multipart form files (`file_0`, `file_1`, ...)
  - max 20 files per batch
  - allowed: `pdf`, `jpg`, `jpeg`, `png`
- Output JSON:
  - `results[]` with `stage_id`, `filename`, inferred `document_type`, optional `transaction_id`, confidence (`high|low`), and review hints
  - `pending_count`
- Notes:
  - stages temp files in `batch_upload_staging`
  - uses Claude (when configured) + heuristics for doc typing and transaction identifiers

### Commit route (TC)
- `POST /tc/batch-upload/commit`
- JSON body:
  - `uploads`: array of `{stage_id, transaction_id, document_type}`
- Output JSON:
  - `successful`, `failed`, `tasks_completed`, `pending_count`
- Behavior:
  - uploads each staged file to S3
  - inserts `documents` records
  - runs `apply_document_post_upload_actions` and transaction field updates from extracted values
  - updates matching `document_requests` as received
  - starts async deep document analysis

### Data model
- Table: `batch_upload_staging`
  - staged temp-path records and AI analysis payload before commit
  - cleaned automatically for stale records

## Automatic Cascade Date Updates

### Apply/preview route (TC)
- `POST /tc/transaction/<transaction_id>/update-date`
- JSON body:
  - `field`: one of `closing_date|effective_date|earnest_due_date|option_period_end_date|financing_approval_date`
  - `old_date`: `YYYY-MM-DD`
  - `new_date`: `YYYY-MM-DD`
  - `preview_only`: `true|false`
  - `force`: `true|false` (required when conflicts/warnings are present)
  - `cascade_options`:
    - `update_deadlines`
    - `reschedule_appointments`
    - `update_tasks`
    - `sync_calendar`
    - `notify_parties`
- Behavior:
  - preview mode returns estimated counts + conflicts without applying
  - apply mode updates selected transaction date, cascades dependent rows, syncs calendar, regenerates timeline, and optionally notifies parties
  - writes snapshot/results to `transaction_date_cascade_log` for undo

### Undo route (TC)
- `POST /tc/transaction/<transaction_id>/update-date/undo`
- JSON body:
  - `cascade_log_id` (optional; latest undoable cascade is used when omitted)
- Behavior:
  - allowed for 24 hours from cascade creation
  - restores transaction/deadline/task/appointment values from snapshot
  - re-syncs calendar and sends disregard notifications

### Conflict detection
- New closing date before appraisal appointment
- New closing date before financing approval date
- Weekend/holiday date warning with suggested next business day

### Data model
- Table: `transaction_date_cascade_log`
  - stores date field deltas, options, before snapshots, results, expiration, and undo summary

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

## AI Problem Detection + Health Report

### 6-hour problem detection automation
- `python3 automation/problem_detector.py`
- Typical cron schedule: `0 */6 * * *`
- Behavior:
  - scans active transactions for schedule, lender, appraisal, inspection, closing-risk, payment, and missing-document patterns
  - computes per-transaction health score (healthy/watch/urgent)
  - generates actionable recommendations (Claude when enabled, deterministic fallback when unavailable)
  - persists results for dashboard review and follow-up actions
  - sends summary SMS/email based on configured notification preference

### Health report dashboard (TC)
- `GET /tc/health-report`
- Query params:
  - `refresh=1` (optional force refresh without notifications)
- Shows:
  - healthy/watch/urgent counts
  - issues + suggested actions grouped by severity
  - one-click action execution and issue dismissal

### Accept suggestion action
- `POST /tc/suggestion/<transaction_id>/accept`
- Alias: `POST /tc/suggestion/accept`
- JSON/form body:
  - `action` (required suggestion text)
  - `transaction_id` (required for alias route only)
- Behavior:
  - executes mapped automations (call lender, send draft action, schedule conference call)
  - logs communication outcomes
  - creates a follow-up task for next-day confirmation

### Mark health issue handled
- `POST /tc/health-report/transaction/<transaction_id>/dismiss`
- JSON/form body (optional):
  - `run_id`
  - `notes`

### Problem detection settings (TC)
- `GET|POST /tc/problem-detection-settings`
- Actions via form `action`:
  - `update_settings` (sensitivity, notification mode, AI enabled, auto-execute actions)
  - `add_whitelist` (exclude transaction from analysis)
  - `remove_whitelist` (deactivate whitelist entry)
  - `run_now` (manual analysis run without notifications)

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
