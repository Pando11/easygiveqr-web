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

from dotenv import load_dotenv

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
load_dotenv()

from utils.db import execute_query
from utils.sms import send_sms

DRY_RUN = False

CRITICAL_DOC_TYPES = {
    "inspection_report",
    "appraisal",
    "loan_approval",
    "insurance_binder",
    "title_commitment",
}


def log(message):
    """Timestamped logger for cron output."""
    print(f"[{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}] {message}")


def notify_sms(to_number, message):
    """Send SMS or print in dry-run mode."""
    if DRY_RUN:
        log(f"[DRY-RUN] SMS to {to_number}: {message[:220]}")
        return "dry-run"
    return send_sms(to_number, message)


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
    """Detect missing critical docs for closings within seven days."""
    today = date.today()
    close_cutoff = today + timedelta(days=7)
    closings = execute_query(
        """
        SELECT id, property_address, closing_date
        FROM transactions
        WHERE status = 'ACTIVE'
          AND closing_date IS NOT NULL
          AND closing_date >= %s
          AND closing_date <= %s
        ORDER BY closing_date ASC
        """,
        (today, close_cutoff),
        fetch=True,
    ) or []

    problems = []
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
        missing = sorted(CRITICAL_DOC_TYPES - existing_types)
        if not missing:
            continue

        days_to_close = (txn["closing_date"] - today).days
        severity = "HIGH" if days_to_close < 3 else "MEDIUM"
        problems.append(
            {
                "severity": severity,
                "type": "MISSING_DOCUMENTS",
                "property": txn["property_address"],
                "detail": (
                    f"Closing in {days_to_close}d, missing: "
                    + ", ".join(item.replace("_", " ").title() for item in missing[:4])
                ),
            }
        )
    log(f"Missing-document issues found: {len(problems)}")
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
