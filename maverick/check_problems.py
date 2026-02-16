#!/usr/bin/env python3
"""
Maverick TC - Problem Detection System
Runs every 6 hours to detect and flag issues.
"""

import os
import sys
from datetime import date, timedelta

from dotenv import load_dotenv

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
load_dotenv()

from utils.db import execute_query
from utils.sms import send_sms


def detect_missed_deadlines():
    """Detect missed deadlines."""
    today = date.today()
    query = """
    SELECT d.id, d.deadline_type, d.deadline_date,
           t.id as transaction_id, t.property_address, t.agent_name
    FROM deadlines d
    JOIN transactions t ON d.transaction_id = t.id
    WHERE d.deadline_date < %s
      AND d.completed = FALSE
      AND t.status = 'ACTIVE'
    ORDER BY d.deadline_date
    """

    missed = execute_query(query, (today,), fetch=True) or []
    problems = []
    for deadline in missed:
        days_overdue = (today - deadline["deadline_date"]).days
        problems.append(
            {
                "severity": "HIGH",
                "type": "MISSED_DEADLINE",
                "transaction_id": deadline["transaction_id"],
                "property": deadline["property_address"],
                "description": (
                    f"{deadline['deadline_type'].replace('_', ' ').title()} "
                    f"was {days_overdue} days ago"
                ),
                "deadline_id": deadline["id"],
            }
        )
    return problems


def detect_overdue_tasks():
    """Detect overdue tasks (>2 days)."""
    cutoff_date = date.today() - timedelta(days=2)
    query = """
    SELECT t.id, t.task_description, t.due_date,
           tr.id as transaction_id, tr.property_address
    FROM tasks t
    JOIN transactions tr ON t.transaction_id = tr.id
    WHERE t.due_date < %s
      AND t.completed = FALSE
      AND tr.status = 'ACTIVE'
    """

    overdue = execute_query(query, (cutoff_date,), fetch=True) or []
    problems = []
    for task in overdue:
        days_overdue = (date.today() - task["due_date"]).days
        problems.append(
            {
                "severity": "MEDIUM",
                "type": "OVERDUE_TASK",
                "transaction_id": task["transaction_id"],
                "property": task["property_address"],
                "description": f"Task overdue {days_overdue}d: {task['task_description']}",
                "task_id": task["id"],
            }
        )
    return problems


def detect_missing_documents():
    """Detect missing critical documents <7 days to closing."""
    target_date = date.today() + timedelta(days=7)
    query = """
    SELECT t.id, t.property_address, t.closing_date
    FROM transactions t
    WHERE t.closing_date <= %s
      AND t.closing_date >= CURRENT_DATE
      AND t.status = 'ACTIVE'
    """

    closing_soon = execute_query(query, (target_date,), fetch=True) or []
    problems = []
    required_docs = [
        "inspection_report",
        "appraisal",
        "loan_approval",
        "insurance_binder",
        "title_commitment",
    ]

    for txn in closing_soon:
        docs = execute_query(
            "SELECT document_type FROM documents WHERE transaction_id = %s",
            (txn["id"],),
            fetch=True,
        ) or []
        doc_types = [doc["document_type"] for doc in docs]
        missing = [doc for doc in required_docs if doc not in doc_types]
        if missing:
            days_until_closing = (txn["closing_date"] - date.today()).days
            problems.append(
                {
                    "severity": "HIGH" if days_until_closing < 3 else "MEDIUM",
                    "type": "MISSING_DOCUMENTS",
                    "transaction_id": txn["id"],
                    "property": txn["property_address"],
                    "description": (
                        f"Missing {len(missing)} docs, closing in {days_until_closing}d: "
                        + ", ".join(doc.replace("_", " ").title() for doc in missing)
                    ),
                    "missing_docs": missing,
                }
            )
    return problems


def detect_no_activity():
    """Detect transactions with no activity >5 days."""
    cutoff_date = date.today() - timedelta(days=5)
    query = """
    SELECT t.id, t.property_address, t.updated_at,
           (SELECT MAX(created_at) FROM communications WHERE transaction_id = t.id) as last_comm,
           (SELECT MAX(completed_at) FROM tasks WHERE transaction_id = t.id AND completed = TRUE) as last_task
    FROM transactions t
    WHERE t.status = 'ACTIVE'
      AND t.updated_at < %s
    """

    inactive = execute_query(query, (cutoff_date,), fetch=True) or []
    problems = []
    for txn in inactive:
        timestamps = [ts for ts in [txn["updated_at"], txn["last_comm"], txn["last_task"]] if ts]
        if not timestamps:
            days_inactive = 999
        else:
            last_activity = max(timestamps)
            days_inactive = (date.today() - last_activity.date()).days

        if days_inactive > 5:
            problems.append(
                {
                    "severity": "MEDIUM",
                    "type": "NO_ACTIVITY",
                    "transaction_id": txn["id"],
                    "property": txn["property_address"],
                    "description": f"No activity for {days_inactive} days",
                }
            )
    return problems


def detect_payment_issues():
    """Detect unpaid transactions."""
    query = """
    SELECT t.id, t.property_address, t.agent_name,
           t.payment_upfront_paid, t.payment_closing_paid, t.closing_date, t.created_at
    FROM transactions t
    WHERE t.status = 'ACTIVE'
      AND (t.payment_upfront_paid = FALSE OR t.payment_closing_paid = FALSE)
    """

    unpaid = execute_query(query, fetch=True) or []
    problems = []
    for txn in unpaid:
        if not txn["payment_upfront_paid"]:
            days_since_upload = (date.today() - txn["created_at"].date()).days
            if days_since_upload > 2:
                problems.append(
                    {
                        "severity": "MEDIUM",
                        "type": "PAYMENT_OVERDUE",
                        "transaction_id": txn["id"],
                        "property": txn["property_address"],
                        "description": (
                            f"Upfront payment not received ({days_since_upload}d overdue)"
                        ),
                    }
                )

        if not txn["payment_closing_paid"] and txn["closing_date"]:
            days_until_closing = (txn["closing_date"] - date.today()).days
            if days_until_closing < 3:
                problems.append(
                    {
                        "severity": "HIGH",
                        "type": "PAYMENT_OVERDUE",
                        "transaction_id": txn["id"],
                        "property": txn["property_address"],
                        "description": (
                            f"Closing payment not received, closing in {days_until_closing}d"
                        ),
                    }
                )
    return problems


def alert_margaret(problems):
    """Send problem summary to Margaret."""
    if not problems:
        print("No problems detected")
        return

    high = [item for item in problems if item["severity"] == "HIGH"]
    medium = [item for item in problems if item["severity"] == "MEDIUM"]
    message = "PROBLEMS DETECTED:\n\n"

    if high:
        message += f"HIGH ({len(high)}):\n"
        for problem in high[:3]:
            message += f"- {problem['property']}: {problem['description']}\n"
        if len(high) > 3:
            message += f"+ {len(high) - 3} more\n"
        message += "\n"

    if medium:
        message += f"MEDIUM ({len(medium)}):\n"
        for problem in medium[:3]:
            message += f"- {problem['property']}: {problem['description']}\n"
        if len(medium) > 3:
            message += f"+ {len(medium) - 3} more\n"

    message += "\nCheck dashboard for details."

    margaret_phone = os.getenv("MARGARET_PHONE")
    if margaret_phone:
        send_sms(margaret_phone, message)
        print(f"Sent problem alert to Margaret ({len(problems)} issues)")


def main():
    """Main problem detection."""
    print("\n" + "=" * 50)
    print("Maverick TC - Problem Detection")
    print(f"Running at: {date.today()}")
    print("=" * 50 + "\n")

    all_problems = []
    print("Checking for missed deadlines...")
    all_problems.extend(detect_missed_deadlines())

    print("Checking for overdue tasks...")
    all_problems.extend(detect_overdue_tasks())

    print("Checking for missing documents...")
    all_problems.extend(detect_missing_documents())

    print("Checking for inactive transactions...")
    all_problems.extend(detect_no_activity())

    print("Checking for payment issues...")
    all_problems.extend(detect_payment_issues())

    print(f"\nTotal problems found: {len(all_problems)}")
    if all_problems:
        alert_margaret(all_problems)

    print("\n" + "=" * 50)
    print("Problem detection completed")
    print("=" * 50 + "\n")


if __name__ == "__main__":
    main()
