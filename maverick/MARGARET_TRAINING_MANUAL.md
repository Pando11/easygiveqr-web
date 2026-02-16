# MAVERICK TC - MARGARET'S TRAINING MANUAL

## Table of Contents
1. System Overview
2. Daily Workflow
3. Contract Review and Approval
4. Task Management
5. Document Tracking
6. Communication Logging
7. Payment Tracking
8. Troubleshooting
9. Texas TC Best Practices
10. Quick Reference

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
3. Confirm effective date and closing date.
4. Enter required parties:
   - Buyer name
   - Seller name
   - Title company
5. Validate date logic (closing after other critical milestones).
6. Approve and activate transaction.

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

## 8. TROUBLESHOOTING

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

## 9. TEXAS TC BEST PRACTICES

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

## 10. QUICK REFERENCE

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

