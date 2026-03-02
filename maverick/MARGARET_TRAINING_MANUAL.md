# MAVERICK TC - MARGARET'S TRAINING MANUAL

## Table of Contents
1. System Overview
2. Daily Workflow
3. Contract Review and Approval
4. Task Management
5. Document Tracking
6. Communication Logging
7. Payment Tracking
8. Client Portal Management
9. Troubleshooting
10. Texas TC Best Practices
11. Quick Reference

---

## 1. SYSTEM OVERVIEW

### What is Maverick?
Maverick is your transaction coordination platform. It handles:
- Automatic deadline tracking (12 Texas deadlines)
- Automated reminders to agents (10d, 7d, 3d, 1d)
- Task management (30+ tasks per transaction)
- Document storage (AWS S3)
- Communication logging
- Payment processing and tracking
- Problem detection alerts

### Your Role
You remain the human coordinator. Maverick is your assistant.

You handle:
- Contract review and verification
- Phone calls and relationship management
- Coordination between parties
- Problem-solving and judgment calls
- Quality control

Maverick handles:
- Deadline calculations
- Reminder sending
- Document storage
- Task organization
- Problem flagging

---

## 2. DAILY WORKFLOW

### Morning Routine (8:00 AM)

1. Login at `/tc`
2. Review:
   - Overdue items
   - Due today
   - Calls to make
3. Prioritize:
   - Overdue first
   - Critical deadline calls
   - Due-today tasks
   - Reminder sends

### Throughout the Day

- Check dashboard every 2-3 hours
- Review new uploads
- Handle problem alerts
- Respond to agent questions
- Log all substantial communications

### End-of-Day Review (5:00 PM)

- All overdue items handled?
- Tomorrow's priorities identified?
- Communications logged?
- Escalations captured?

---

## 3. CONTRACT REVIEW AND APPROVAL

### Trigger
When a new contract arrives:
- Dashboard shows `NEEDS_MARGARET_REVIEW`
- Agent has already received upload confirmation

### Review Process

1. Open transaction and review uploaded PDF.
2. Verify all pages and signatures.
3. Review **AI Contract Extraction (Triple-Scan Verification)**:
   - High confidence (`3/3`) can usually be accepted quickly.
   - Low confidence (`2/3` or `1/3`) requires closer review.
   - No agreement (`0/3`) requires manual entry.
4. Use **Accept High-Confidence Values** as a quick start.
5. For low-confidence fields:
   - Compare Method 1 (OCR), Method 2 (PyPDF2), Method 3 (pdfplumber)
   - Choose best value or type manually
6. Click **Save Verified Extraction**.
7. Enter required parties/contact details:
   - Buyer name
   - Seller name
   - Title company
8. Validate date logic (closing after other critical milestones).
9. Approve and activate transaction.

### Approval Gate

The **Approve & Activate Transaction** button stays disabled until all required extraction fields are verified.

### Automatic Timeline Packet + Distribution (After Approval)

Immediately after you approve a transaction, Maverick now handles timeline distribution automatically:

1. Generates a professional PDF timeline packet with:
   - All contract deadlines
   - Visual timeline/gantt-style chart
   - Weekly expectations
   - Payment/document milestones
   - Inspection/appraisal windows
   - Moving checklist
   - Party contact info + Margaret contact info
   - Client upload portal link
2. Emails the packet to:
   - Buyer
   - Seller
   - Agent
   - Lender
   - Title company
3. Uses update-aware messaging if dates/timeline shift later.

### Timeline Re-Send

If needed, use **Re-send Timeline Packet** from the transaction Actions card.

### If Contract Has Errors

- Do not approve yet.
- Contact agent immediately.
- Resolve issue.
- Re-check and approve.

Common issues:
- Missing signatures
- Missing addenda
- Unclear effective date
- Conflicting dates

---

## 4. TASK MANAGEMENT

### Task Categories

- contract_setup
- coordination
- documents
- pre_closing
- closing
- post_closing

### Completion Rules

- Mark done as soon as completed.
- Add notes for context and auditability.
- If not applicable, mark complete and add "N/A" note.

### Daily Task Hygiene

- Clear overdue tasks first.
- Move due-today tasks before noon.
- Capture blockers in notes and communication log.

### Vendor Follow-Up Tasks (Auto-Created)

When vendor outreach is sent (inspector/appraiser/survey/title), Maverick tracks responses.
If no response is received within 24 hours, a follow-up task is auto-added to your checklist.

- Treat these as high-priority coordination tasks.
- Update/complete once vendor confirms scheduling.

### Proactive Deadline Nudges (Auto)

Maverick now checks key timeline milestones daily for missing progress and sends gentle nudges automatically.

Examples:
- Option period in 5 days + no inspection scheduled -> agent nudge (SMS/email)
- Earnest due in 2 days + no receipt -> buyer reminder email
- Appraisal due in 7 days + not ordered -> lender reminder email
- HOA docs due in 5 days + not received -> seller reminder email
- Repair addendum due in 3 days + missing -> agent reminder email

Escalation rules:
- Maverick escalates to your checklist only when:
  1. no response after 2 nudges **and** deadline is within 48 hours, or
  2. a party explicitly asks for your help

### Agent Reply Flow: "YES" for Inspector Help

For inspection scheduling nudges, if an agent replies `YES`:
- Maverick sends inspector recommendations by SMS
- Logs interaction automatically
- No manual Margaret action is required unless agent requests help

---

## 5. DOCUMENT TRACKING

### Common Required Documents

1. Earnest money receipt
2. Option fee receipt
3. Seller disclosure
4. Inspection report
5. Appraisal
6. Title commitment
7. Survey (if applicable)
8. HOA documents (if applicable)
9. Loan approval letter
10. Insurance binder
11. Final settlement statement
12. Amendments

### Upload Process

1. Open transaction.
2. Upload document.
3. Assign document type.
4. Confirm in list and verify accessibility.

### Manual "Send request now" Button

If a required document is missing:

1. Open the transaction.
2. Go to **Documents**.
3. Click **Send request now** next to the missing document.
4. Confirm the status banner at the top.
5. Verify request timestamps in the **Document Requests** box.

### AI Document Analysis (HOA + Inspection + Appraisal)

When HOA, inspection, or appraisal PDFs are uploaded, Maverick auto-analyzes them and creates action items.

1. Open transaction and review **Document Analysis** status.
2. Click **View Full Analysis Dashboard**.
3. Review:
   - HOA dues / special assessments / violations
   - Inspection major defects / repair count / safety issues / estimated cost
   - Appraisal value vs contract price variance
4. Check confidence indicators:
   - High (3/3), Medium (2/3), Low (1/3)
5. Confirm auto-created tasks make sense.
6. If needed, use **Override Task (Mark N/A)**.
7. Add notes and click **Mark as Reviewed**.

### Repair Timeline Update Trigger

If inspection/appraisal findings generate repair-related tasks, Maverick can issue updated timeline packets to keep parties aligned on new timeline risk.

### Smart Alert Rules

- HOA special assessment over $3,000 -> immediate SMS alert
- Inspection safety issues -> immediate SMS alert
- Estimated repairs over $10,000 -> immediate SMS alert
- Appraisal below contract value -> immediate SMS alert + critical task
- Lower-severity alerts -> auto-added to daily checklist tasks

### Access and Retention

- Documents are stored in S3.
- Access is auditable through `document_access_logs`.
- Do not delete records/documents unless policy explicitly allows.

---

## 6. COMMUNICATION LOGGING

### What to Log

Log:
- Phone calls with agent/lender/title/buyer/seller
- Material email updates
- Meaningful text exchanges

Do not log:
- Trivial acknowledgements
- Automated system messages

### Automated Communication Notes You Will See

You will now see system-created entries for:
- Timeline packet generated/sent
- Vendor outreach email sent/failed
- Vendor secure-link response received
- Auto follow-up task creation after 24h no response
- Inbound mailbox routing decisions (urgency/category/forwarding/SMS alerts)
- Post-close review follow-up scheduled (default: 7 days after completion)
- Agent review submitted (includes rating)
- Negative review alert sent to Margaret
- Referral offer link clicked
- Referral conversion tracked

### Post-Close Review + Referral Workflow (New)

Maverick now runs a post-close follow-up automatically:

1. When a transaction is marked `COMPLETED`, Maverick schedules a review follow-up.
2. At **7 days after close** (default), Maverick sends the agent:
   - "How did we do?" request
   - direct Google review link
   - referral offer: "Refer another agent, they get $50 off, you get $50 credit"
3. Referral link clicks are tracked automatically.
4. New referred uploads are tracked as referral conversions.

Tracking fields are stored in `review_requests`, including:
- `sent_at`
- `review_received`
- `star_rating`
- `referral_sent`
- `referral_clicks`
- `referrals_converted`

### Low-Rating Escalation Rule (New)

If an agent submits a review with **3 stars or less**, Maverick immediately notifies Margaret so a response can be made quickly.

Notification channels:
- SMS to `MARGARET_PHONE` (if configured)
- Email to `MARGARET_EMAIL` (if configured)

### Bad Review Response SOP

When a <=3-star alert arrives:

1. Open the transaction communication timeline immediately.
2. Review feedback text and recent communication history.
3. Respond to the agent the same day (call first, then email/text recap).
4. Log the outreach and outcome in Communication Log.
5. If resolved, add a final note summarizing root cause + fix.

### Inbound Mailbox Workflow (New)

Each transaction now has unique inbound addresses:
- `transaction-<id>-buyer@getmaverick.com`
- `transaction-<id>-seller@getmaverick.com`
- `transaction-<id>-lender@getmaverick.com`

When an inbound message is received, Maverick:
1. Logs it to communication timeline
2. Classifies urgency/category/action needed
3. Auto-routes:
   - Low informational -> log only
   - Medium awareness -> forwards to relevant parties + timeline task
   - High action required -> SMS alert to Margaret + broad forwarding

Sensitive handling:
- Buyer concern/cold-feet messages are flagged **At Risk** and not auto-forwarded to seller.

Override controls:
- In transaction -> Communication Log -> Inbound Email Timeline -> Override Routing
- Use this to force log-only, relevant-forward, or high-action behavior
- Optional checkbox clears At-Risk flag after resolution

Rule setting:
- Inbound Routing Rules supports preferences like:
  - "Always notify Margaret for lender emails"

### Smart Q&A Assistant (New)

Maverick now learns from your inbound email/SMS answers and can suggest or auto-send approved responses.

Decision thresholds:
- Confidence > 95% and auto-answer enabled -> Maverick auto-sends a professional answer
- Confidence > 75% -> Maverick suggests an answer for your review
- Confidence <= 75% -> normal manual response workflow

How to use it in a transaction:
1. Open transaction -> **Communication Log** -> **Inbound Email Timeline**
2. If a suggestion appears:
   - Click **Use Suggested Answer** to send immediately, OR
   - Click **Edit / Send Reply** to customize before sending
3. If no suggestion appears:
   - Use **Reply and Save to Smart Q&A**
4. Every send is logged for audit trail automatically.

Learning behavior:
- Using suggested answers increments reuse count.
- At 5 reuses (default), Maverick enables auto-answer for that Q&A.
- Significant edits create a new answer variant.
- New manual replies are stored as future common Q&A candidates.

Global management:
- Open **/tc/common-qa** from dashboard.
- You can:
  - view all reusable Q&A entries
  - edit answers/categories
  - enable/disable auto-answer per question
  - add manual Q&A entries
  - review time-saved metrics and FAQ draft suggestions

### Google Calendar Sync (New)

Maverick can now keep your Google Calendar updated for core transaction events.

Where to manage:
- Global settings + audit metrics: **/tc/calendar-sync**
- Per transaction controls: transaction detail -> **Google Calendar Sync** card

What auto-syncs:
- **Deadlines** as yellow all-day events
- **Inspection appointments** as blue timed events
- **Appraisal appointments** as green timed events
- **Closing appointment** as red timed event

How to use:
1. Open **/tc/calendar-sync**
2. Enable sync and confirm calendar ID/timezone
3. Save settings
4. On a transaction page, click **Sync Calendar Now** to force refresh
5. Set closing time/location in the same card when needed

Two-way sync option:
- If enabled in settings, Maverick accepts updates from `/calendar-webhook`.
- If an event time is changed in Google Calendar (through your webhook bridge), Maverick updates the corresponding deadline/closing/vendor appointment record and logs it automatically.

Override options:
- You can delete synced events for any transaction with **Delete Synced Events**.
- You can disable specific sync categories (deadlines/inspections/appraisals/closings) globally.

### Logging Best Practice

For each log entry, capture:
- Communication type
- Contact party and name
- Summary (specific, concise)
- Outcome
- Follow-up date if needed

---

## 7. PAYMENT TRACKING

### Payment Structure

- Upfront payment
- Closing payment

Agents may pay by:
- Stripe card flow
- Venmo
- PayPal

### Operational Rules

- Stripe payments auto-update database.
- Venmo/PayPal payments require manual verification and marking.
- Escalate overdue payments based on policy thresholds.

### Referral Credits

- Upfront payment may apply referral credit.
- Credit should be marked used once consumed.

---

## 8. CLIENT PORTAL MANAGEMENT

### What Clients Can Do

Buyer and seller portal links let clients:
- View transaction progress
- See deadline timeline
- View document checklist
- Upload signed documents directly

### Your Responsibilities

1. During review/approval, capture optional buyer/seller email in the form.
2. After activation, use **Generate Client Portal Link** on the transaction page.
3. Confirm links appear in the Actions card.
4. Re-send links if clients report they cannot find the message.

### Vendor Coordination Workflow (New)

After approval, Maverick sends outreach emails to configured vendors:
- Inspector
- Appraiser
- Survey team
- Title coordinator

Each outreach includes:
- Scheduling link (e.g., Calendly if configured)
- Secure confirmation link
- Direct reply path to Margaret (email/phone)

When vendor confirms via link:
- Related coordination task is auto-marked complete
- Appointment can be captured as a calendar event
- Communication log is updated automatically

### Best Practices

- Always verify buyer/seller phone numbers are correct before approving.
- Encourage clients to upload signed items in portal rather than texting photos.
- If a client upload appears missing, refresh the Documents section and check timestamps.

---

## 9. TROUBLESHOOTING

### SMS Not Sending

1. Verify phone format.
2. Check Twilio credentials and balance.
3. Confirm Twilio number and webhook config.

### PDF / S3 Issues

1. Verify bucket variables.
2. Confirm IAM permissions.
3. Check object exists and key path is valid.

### Payment Failures

1. Verify Stripe keys and mode (test/live).
2. Check PaymentIntent status and errors.
3. Confirm amount and route parameters.

### System Performance

1. Refresh browser session.
2. Validate Railway service health.
3. Check database connectivity and logs.

---

## 10. TEXAS TC BEST PRACTICES

### Critical Deadlines to Protect

1. Option fee and earnest money deadlines
2. Option period end
3. Financing approval
4. Closing day readiness

### Escalate to Heidi Immediately If

- Major contract issue post-approval
- Significant client complaint or cancellation threat
- System outage affecting active closings
- Payment dispute with legal/financial risk
- Missed critical deadline at high risk of fallout

### Capacity Guidance

- 10 transactions/month: sustainable
- 15 transactions/month: high pace
- 20+ transactions/month: likely needs support

If overloaded:
- escalate early
- re-prioritize critical paths
- pause low-priority work

---

## 11. QUICK REFERENCE

### Login
- URL: `/tc/login`
- Username: `TC_USERNAME` from environment
- Password: `TC_PASSWORD` from environment

### Daily Checklist
1. Review dashboard
2. Resolve overdue items
3. Make required calls
4. Log communications
5. Confirm tomorrow's risk items

### Review Alert Quick Actions
1. If rating alert is <=3 stars: respond same day.
2. Confirm communication log includes:
   - "Agent review submitted"
   - "Negative review alert sent to Margaret"
3. Add follow-up note with resolution status.

### Emergency Protocol

If system down:
1. Notify Heidi immediately.
2. Continue with manual checklist.
3. Backfill notes when system is back.

If agent emergency:
1. Respond immediately.
2. Log event in system.
3. Escalate to Heidi for major risk.

---

## Appendix A: Suggested Call Scripts

### Lender status call
"Hi, this is Margaret with Maverick TC. I am coordinating [property address]. Are we on track for financing approval by [date]?"

### Title company call
"Hi, this is Margaret with Maverick TC regarding [property address]. What is the status of [title commitment/survey] and expected delivery date?"

### Agent check-in
"Hi [agent name], quick check on [property address]: [specific item]. Do you have an update?"

---

## Appendix B: Common Status Values

Transactions:
- `NEEDS_MARGARET_REVIEW`
- `ACTIVE`
- `COMPLETED`
- `CANCELLED`

Tasks:
- `pending`
- `in_progress`
- `completed`
- `not_applicable`

Documents:
- `received`
- `sent_to_parties`
- `archived`

---

## Appendix C: Launch-Day Readiness

Before launch, confirm:
- Stripe test payments succeed end-to-end.
- S3 uploads and downloads work.
- Reminder job runs manually and by cron.
- Problem detection sends alerts.
- Backup job writes to S3 and sends notification.
- Margaret can login and complete the full workflow.

