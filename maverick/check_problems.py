#!/usr/bin/env python3
"""
Maverick problem detection automation.

Schedule:
  - Run every 6 hours on Railway cron

Checks:
  - Missed deadlines (past due + incomplete)
  - Overdue tasks (>2 days)
  - Missing critical docs (<7 days to closing)
  - Inactive transactions (>5 days no activity)
  - Unpaid transactions (upfront >2 days, closing <3 days)
"""

import argparse
import os
import sys
import traceback
from datetime import date, datetime, timedelta
from pathlib import Path

from dotenv import load_dotenv
from jinja2 import Environment, FileSystemLoader, select_autoescape

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
load_dotenv()

from utils.db import execute_query
from utils.email import send_html_email
from utils.sms import send_sms

DRY_RUN = False

REQUIRED_DOCUMENT_TYPES = {
    "contract",
    "earnest_receipt",
    "option_receipt",
    "seller_disclosure",
    "inspection_report",
    "appraisal",
    "title_commitment",
    "loan_approval",
    "insurance_binder",
    "settlement_statement",
}

DOCUMENT_REQUEST_TARGET = {
    "contract": "seller",
    "earnest_receipt": "buyer",
    "option_receipt": "buyer",
    "seller_disclosure": "seller",
    "inspection_report": "buyer",
    "appraisal": "lender",
    "title_commitment": "title",
    "loan_approval": "lender",
    "insurance_binder": "lender",
    "settlement_statement": "title",
}

TEMPLATE_ENV = Environment(
    loader=FileSystemLoader(str(Path(__file__).resolve().parent / "templates" / "emails")),
    autoescape=select_autoescape(["html", "xml"]),
)


def log(message):
    """Timestamped logger for cron output."""
    print(f"[{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}] {message}")


def notify_sms(to_number, message):
    """Send SMS or print in dry-run mode."""
    if DRY_RUN:
        log(f"[DRY-RUN] SMS to {to_number}: {message[:220]}")
        return "dry-run"
    return send_sms(to_number, message)


def ensure_document_requests_table():
    """Create document_requests table/indexes if missing."""
    statements = (
        """
        CREATE TABLE IF NOT EXISTS document_requests (
            id SERIAL PRIMARY KEY,
            transaction_id INT REFERENCES transactions(id) ON DELETE CASCADE,
            document_type VARCHAR(100) NOT NULL,
            requested_from VARCHAR(20) NOT NULL,
            email_sent_date TIMESTAMP,
            reminder_sent_date TIMESTAMP,
            received_date TIMESTAMP,
            status VARCHAR(20) DEFAULT 'pending',
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
        """,
        """
        CREATE UNIQUE INDEX IF NOT EXISTS idx_document_requests_txn_doc_type
        ON document_requests(transaction_id, document_type)
        """,
        """
        CREATE INDEX IF NOT EXISTS idx_document_requests_status
        ON document_requests(status)
        """,
    )

    for statement in statements:
        if not execute_query(statement):
            raise RuntimeError("Failed to initialize document_requests table/indexes")


def normalize_doc_label(doc_type):
    """Readable label for document types."""
    return (doc_type or "").replace("_", " ").title()


def get_request_recipient_email(transaction_row, requested_from):
    """Choose best email destination for a document request."""
    if requested_from == "lender":
        return (transaction_row.get("lender_email") or "").strip()
    if requested_from == "title":
        return (transaction_row.get("title_officer_email") or "").strip()
    # Buyer/seller emails are not collected; use listing agent email fallback.
    return (transaction_row.get("agent_email") or "").strip()


def render_email_template(template_name, context):
    """Render a Jinja HTML template by filename."""
    template = TEMPLATE_ENV.get_template(template_name)
    return template.render(**context)


def send_document_request_email(to_email, subject, html_body):
    """Send document request email with dry-run support."""
    if DRY_RUN:
        log(f"[DRY-RUN] Email to {to_email}: {subject}")
        return "dry-run"
    return send_html_email(to_email=to_email, subject=subject, html_body=html_body)


def upsert_document_request_record(transaction_id, document_type, requested_from):
    """Ensure one request row exists for transaction/document."""
    rows = execute_query(
        """
        INSERT INTO document_requests (
            transaction_id, document_type, requested_from, status, updated_at
        )
        VALUES (%s, %s, %s, 'pending', CURRENT_TIMESTAMP)
        ON CONFLICT (transaction_id, document_type)
        DO UPDATE SET
            requested_from = EXCLUDED.requested_from,
            status = CASE
                WHEN document_requests.received_date IS NOT NULL THEN 'received'
                ELSE document_requests.status
            END,
            updated_at = CURRENT_TIMESTAMP
        RETURNING id, email_sent_date, reminder_sent_date, received_date, status
        """,
        (transaction_id, document_type, requested_from),
        fetch=True,
    ) or []
    return rows[0] if rows else None


def mark_document_request_overdue(request_id):
    """Mark a request overdue if still pending and not received."""
    execute_query(
        """
        UPDATE document_requests
        SET status = 'overdue',
            updated_at = CURRENT_TIMESTAMP
        WHERE id = %s
          AND received_date IS NULL
          AND status <> 'received'
        """,
        (request_id,),
    )


def mark_document_request_email_sent(request_id, is_reminder=False):
    """Set email/reminder timestamps after successful send."""
    if is_reminder:
        execute_query(
            """
            UPDATE document_requests
            SET reminder_sent_date = COALESCE(reminder_sent_date, CURRENT_TIMESTAMP),
                status = CASE WHEN received_date IS NULL THEN 'pending' ELSE status END,
                updated_at = CURRENT_TIMESTAMP
            WHERE id = %s
            """,
            (request_id,),
        )
    else:
        execute_query(
            """
            UPDATE document_requests
            SET email_sent_date = COALESCE(email_sent_date, CURRENT_TIMESTAMP),
                status = CASE WHEN received_date IS NULL THEN 'pending' ELSE status END,
                updated_at = CURRENT_TIMESTAMP
            WHERE id = %s
            """,
            (request_id,),
        )


def maybe_send_document_request(transaction_row, document_type):
    """Create/update request row and send initial/reminder email as needed."""
    requested_from = DOCUMENT_REQUEST_TARGET.get(document_type, "buyer")
    request_row = upsert_document_request_record(
        transaction_id=transaction_row["id"],
        document_type=document_type,
        requested_from=requested_from,
    )
    if not request_row:
        return {"sent": False, "reason": "request_row_missing"}

    if request_row.get("received_date"):
        return {"sent": False, "reason": "already_received"}

    closing_date = transaction_row.get("closing_date")
    days_to_close = (closing_date - date.today()).days if closing_date else 999
    if days_to_close < 0:
        mark_document_request_overdue(request_row["id"])

    to_email = get_request_recipient_email(transaction_row, requested_from)
    if not to_email:
        log(
            f"Request not emailed (missing recipient): txn#{transaction_row['id']} "
            f"doc={document_type} requested_from={requested_from}"
        )
        return {"sent": False, "reason": "missing_recipient"}

    context = {
        "property_address": transaction_row.get("property_address"),
        "document_label": normalize_doc_label(document_type),
        "requested_from": requested_from.title(),
        "closing_date_label": closing_date.strftime("%b %d, %Y") if closing_date else "TBD",
        "days_to_close": days_to_close,
        "agent_name": transaction_row.get("agent_name") or "Agent",
    }

    should_send_initial = request_row.get("email_sent_date") is None
    should_send_reminder = (
        not should_send_initial
        and request_row.get("reminder_sent_date") is None
        and days_to_close <= 3
    )

    if not should_send_initial and not should_send_reminder:
        return {"sent": False, "reason": "already_notified"}

    if should_send_initial:
        html_body = render_email_template("document_request.html", context)
        subject = f"Document Request: {normalize_doc_label(document_type)} - {transaction_row.get('property_address')}"
        message_id = send_document_request_email(to_email, subject, html_body)
        if message_id:
            mark_document_request_email_sent(request_row["id"], is_reminder=False)
            return {"sent": True, "kind": "initial", "message_id": message_id}
        return {"sent": False, "reason": "send_failed"}

    html_body = render_email_template("document_reminder.html", context)
    subject = f"Reminder: {normalize_doc_label(document_type)} needed - {transaction_row.get('property_address')}"
    message_id = send_document_request_email(to_email, subject, html_body)
    if message_id:
        mark_document_request_email_sent(request_row["id"], is_reminder=True)
        return {"sent": True, "kind": "reminder", "message_id": message_id}
    return {"sent": False, "reason": "send_failed"}


def detect_missed_deadlines():
    """Detect incomplete deadlines where due date has passed."""
    today = date.today()
    rows = execute_query(
        """
        SELECT d.id, d.deadline_type, d.deadline_date,
               t.id AS transaction_id, t.property_address
        FROM deadlines d
        JOIN transactions t ON t.id = d.transaction_id
        WHERE d.deadline_date < %s
          AND d.completed = FALSE
          AND t.status = 'ACTIVE'
        ORDER BY d.deadline_date ASC
        """,
        (today,),
        fetch=True,
    ) or []

    problems = []
    for item in rows:
        days_overdue = (today - item["deadline_date"]).days
        problems.append(
            {
                "severity": "HIGH",
                "type": "MISSED_DEADLINE",
                "property": item["property_address"],
                "detail": (
                    f"{item['deadline_type'].replace('_', ' ').title()} "
                    f"overdue by {days_overdue}d"
                ),
            }
        )
    log(f"Missed deadlines found: {len(problems)}")
    return problems


def detect_overdue_tasks():
    """Detect incomplete tasks overdue by more than two days."""
    cutoff = date.today() - timedelta(days=2)
    rows = execute_query(
        """
        SELECT tk.id, tk.task_description, tk.due_date,
               t.property_address
        FROM tasks tk
        JOIN transactions t ON t.id = tk.transaction_id
        WHERE tk.completed = FALSE
          AND COALESCE(tk.status, 'pending') <> 'completed'
          AND tk.due_date < %s
          AND t.status = 'ACTIVE'
        ORDER BY tk.due_date ASC
        """,
        (cutoff,),
        fetch=True,
    ) or []

    problems = []
    for item in rows:
        days_overdue = (date.today() - item["due_date"]).days
        problems.append(
            {
                "severity": "MEDIUM",
                "type": "OVERDUE_TASK",
                "property": item["property_address"],
                "detail": f"Task overdue {days_overdue}d: {item['task_description']}",
            }
        )
    log(f"Overdue tasks found: {len(problems)}")
    return problems


def detect_missing_critical_documents():
    """Detect missing required docs and trigger automated requests."""
    today = date.today()
    close_cutoff = today + timedelta(days=7)
    ensure_document_requests_table()
    closings = execute_query(
        """
        SELECT id, property_address, closing_date, agent_name, agent_email,
               lender_email, title_officer_email, contract_s3_key
        FROM transactions
        WHERE status = 'ACTIVE'
          AND closing_date IS NOT NULL
          AND closing_date <= %s
        ORDER BY closing_date ASC
        """,
        (close_cutoff,),
        fetch=True,
    ) or []

    problems = []
    initial_sent = 0
    reminders_sent = 0
    for txn in closings:
        docs = execute_query(
            """
            SELECT document_type
            FROM documents
            WHERE transaction_id = %s
            """,
            (txn["id"],),
            fetch=True,
        ) or []
        existing_types = {doc["document_type"] for doc in docs}
        if txn.get("contract_s3_key"):
            existing_types.add("contract")

        missing = sorted(REQUIRED_DOCUMENT_TYPES - existing_types)
        if not missing:
            continue

        days_to_close = (txn["closing_date"] - today).days
        severity = "HIGH" if days_to_close < 3 else "MEDIUM"
        closing_label = (
            f"Closing overdue by {abs(days_to_close)}d"
            if days_to_close < 0
            else f"Closing in {days_to_close}d"
        )
        problems.append(
            {
                "severity": severity,
                "type": "MISSING_DOCUMENTS",
                "property": txn["property_address"],
                "detail": (
                    f"{closing_label}, missing: "
                    + ", ".join(item.replace("_", " ").title() for item in missing[:4])
                ),
            }
        )

        for doc_type in missing:
            result = maybe_send_document_request(txn, doc_type)
            if result.get("sent") and result.get("kind") == "initial":
                initial_sent += 1
            elif result.get("sent") and result.get("kind") == "reminder":
                reminders_sent += 1

    log(
        "Missing-document issues found: "
        f"{len(problems)} (initial emails sent={initial_sent}, reminders sent={reminders_sent})"
    )
    return problems


def detect_inactive_transactions():
    """Detect transactions with no meaningful activity in five days."""
    cutoff_date = date.today() - timedelta(days=5)
    rows = execute_query(
        """
        SELECT t.id, t.property_address, t.updated_at,
               (SELECT MAX(created_at) FROM communications c WHERE c.transaction_id = t.id) AS last_comm,
               (SELECT MAX(completed_at) FROM tasks tk WHERE tk.transaction_id = t.id AND tk.completed = TRUE)
                   AS last_task_completion
        FROM transactions t
        WHERE t.status = 'ACTIVE'
          AND t.updated_at::date <= %s
        ORDER BY t.updated_at ASC
        """,
        (cutoff_date,),
        fetch=True,
    ) or []

    problems = []
    for txn in rows:
        timestamps = [item for item in (txn["updated_at"], txn["last_comm"], txn["last_task_completion"]) if item]
        if not timestamps:
            days_inactive = 999
        else:
            days_inactive = (date.today() - max(timestamps).date()).days

        if days_inactive > 5:
            problems.append(
                {
                    "severity": "MEDIUM",
                    "type": "INACTIVE_TRANSACTION",
                    "property": txn["property_address"],
                    "detail": f"No activity for {days_inactive}d",
                }
            )
    log(f"Inactive transactions found: {len(problems)}")
    return problems


def detect_unpaid_transactions():
    """Detect unpaid upfront/closing payments needing escalation."""
    today = date.today()
    rows = execute_query(
        """
        SELECT id, property_address, created_at, closing_date,
               payment_upfront_paid, payment_closing_paid
        FROM transactions
        WHERE status = 'ACTIVE'
        """,
        fetch=True,
    ) or []

    problems = []
    for txn in rows:
        if not txn["payment_upfront_paid"]:
            days_since_created = (today - txn["created_at"].date()).days
            if days_since_created > 2:
                problems.append(
                    {
                        "severity": "MEDIUM",
                        "type": "UNPAID_UPFRONT",
                        "property": txn["property_address"],
                        "detail": f"Upfront unpaid for {days_since_created}d",
                    }
                )

        if not txn["payment_closing_paid"] and txn.get("closing_date"):
            days_to_close = (txn["closing_date"] - today).days
            if days_to_close < 3:
                problems.append(
                    {
                        "severity": "HIGH",
                        "type": "UNPAID_CLOSING",
                        "property": txn["property_address"],
                        "detail": f"Closing unpaid with closing in {days_to_close}d",
                    }
                )
    log(f"Unpaid-transaction issues found: {len(problems)}")
    return problems


def build_problem_summary(problems):
    """Build one grouped SMS summary for Margaret."""
    if not problems:
        return "No issues detected."

    high = [problem for problem in problems if problem["severity"] == "HIGH"]
    medium = [problem for problem in problems if problem["severity"] == "MEDIUM"]

    lines = [f"Problem scan: {len(problems)} issue(s)"]
    if high:
        lines.append(f"HIGH ({len(high)}):")
        for problem in high[:4]:
            lines.append(f"- {problem['property']}: {problem['detail']}")
        if len(high) > 4:
            lines.append(f"+ {len(high) - 4} more HIGH issues")
    if medium:
        lines.append(f"MEDIUM ({len(medium)}):")
        for problem in medium[:4]:
            lines.append(f"- {problem['property']}: {problem['detail']}")
        if len(medium) > 4:
            lines.append(f"+ {len(medium) - 4} more MEDIUM issues")

    lines.append("Review dashboard for full details.")
    lines.append("- Maverick TC")
    return "\n".join(lines)


def main(dry_run=False):
    """Run all problem checks and alert Margaret once."""
    global DRY_RUN
    DRY_RUN = dry_run
    log("Starting problem detection run")
    if DRY_RUN:
        log("Mode: DRY-RUN")

    try:
        detected = []
        detected.extend(detect_missed_deadlines())
        detected.extend(detect_overdue_tasks())
        detected.extend(detect_missing_critical_documents())
        detected.extend(detect_inactive_transactions())
        detected.extend(detect_unpaid_transactions())

        log(f"Total problems detected: {len(detected)}")
        for problem in detected:
            log(f"[{problem['severity']}] {problem['type']} - {problem['property']} - {problem['detail']}")

        margaret_phone = os.getenv("MARGARET_PHONE")
        if margaret_phone:
            summary = build_problem_summary(detected)
            sid = notify_sms(margaret_phone, summary)
            log(f"Problem summary sent to Margaret sid={sid}")
        else:
            log("MARGARET_PHONE missing; summary not sent.")

        log("Problem detection run complete")
    except Exception as exc:
        log(f"ERROR: problem detection failed: {exc}")
        traceback.print_exc()
        heidi_phone = os.getenv("HEIDI_PHONE")
        if heidi_phone:
            notify_sms(heidi_phone, f"Maverick check_problems failed: {str(exc)[:140]}")
        raise


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Run Maverick problem detection.")
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Run checks and log output without sending SMS.",
    )
    cli_args = parser.parse_args()
    main(dry_run=cli_args.dry_run)
