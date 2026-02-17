#!/usr/bin/env python3
"""
Maverick reminder automation.

Schedule:
  - Railway cron daily at 8:00 AM

Responsibilities:
  - Send 10/7/3/1-day reminder texts for active deadlines
  - Alert Margaret about critical deadlines tomorrow
  - Alert Margaret about overdue deadlines
  - Alert Heidi if the job fails
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
from utils.sms import send_reminder, send_sms

DRY_RUN = False

REMINDER_STAGES = (
    {
        "days_before": 10,
        "name": "10-day",
        "where_clause": "d.reminder_10d_sent = FALSE",
        "update_query": """
            UPDATE deadlines
            SET reminder_10d_sent = TRUE,
                reminder_10d_sent_at = CURRENT_TIMESTAMP
            WHERE id = %s
        """,
    },
    {
        "days_before": 7,
        "name": "7-day",
        "where_clause": "d.reminder_7d_sent = FALSE",
        "update_query": """
            UPDATE deadlines
            SET reminder_7d_sent = TRUE,
                reminder_7d_sent_at = CURRENT_TIMESTAMP
            WHERE id = %s
        """,
    },
    {
        "days_before": 3,
        "name": "3-day",
        "where_clause": "d.reminder_3d_sent = FALSE",
        "update_query": """
            UPDATE deadlines
            SET reminder_3d_sent = TRUE,
                reminder_3d_sent_at = CURRENT_TIMESTAMP
            WHERE id = %s
        """,
    },
    {
        "days_before": 1,
        "name": "1-day",
        "where_clause": "d.reminder_1d_sent = FALSE",
        "update_query": """
            UPDATE deadlines
            SET reminder_1d_sent = TRUE,
                reminder_1d_sent_at = CURRENT_TIMESTAMP
            WHERE id = %s
        """,
    },
)


def log(message):
    """Print timestamped logs for cron visibility."""
    print(f"[{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}] {message}")


def notify_sms(to_number, message):
    """Send SMS or print in dry-run mode."""
    if DRY_RUN:
        log(f"[DRY-RUN] SMS to {to_number}: {message[:220]}")
        return "dry-run"
    return send_sms(to_number, message)


def fetch_stage_deadlines(target_date, where_clause):
    """Fetch active, incomplete deadlines for one reminder stage."""
    return execute_query(
        f"""
        SELECT d.id, d.deadline_type, d.deadline_date, d.is_critical,
               t.id AS transaction_id, t.property_address, t.agent_name, t.agent_phone
        FROM deadlines d
        JOIN transactions t ON t.id = d.transaction_id
        WHERE d.deadline_date = %s
          AND d.completed = FALSE
          AND {where_clause}
          AND t.status = 'ACTIVE'
        ORDER BY t.property_address ASC
        """,
        (target_date,),
        fetch=True,
    ) or []


def send_stage_reminders():
    """Send 10/7/3/1 day reminder messages."""
    today = date.today()
    total_sent = 0

    for stage in REMINDER_STAGES:
        target_date = today + timedelta(days=stage["days_before"])
        deadlines = fetch_stage_deadlines(target_date, stage["where_clause"])
        log(f"{stage['name']} stage: {len(deadlines)} candidate deadlines")

        for deadline in deadlines:
            if DRY_RUN:
                sid = "dry-run"
                log(
                    f"[DRY-RUN] Would send {stage['name']} reminder "
                    f"to {deadline['agent_phone']} for {deadline['property_address']}"
                )
            else:
                sid = send_reminder(
                    to_number=deadline["agent_phone"],
                    property_address=deadline["property_address"],
                    deadline_type=deadline["deadline_type"].replace("_", " ").title(),
                    deadline_date=deadline["deadline_date"].strftime("%m/%d/%Y"),
                    days_until=stage["days_before"],
                )
            if not sid:
                log(
                    f"Failed {stage['name']} reminder for "
                    f"deadline_id={deadline['id']} property={deadline['property_address']}"
                )
                continue

            if DRY_RUN:
                log(f"[DRY-RUN] Would set reminder flag for deadline_id={deadline['id']}")
            else:
                updated = execute_query(stage["update_query"], (deadline["id"],))
                if not updated:
                    log(f"Warning: failed to update reminder flags for deadline_id={deadline['id']}")
                    continue

            total_sent += 1
            log(
                f"Sent {stage['name']} reminder: "
                f"property={deadline['property_address']} type={deadline['deadline_type']} sid={sid}"
            )

    return total_sent


def send_critical_deadline_alert_to_margaret():
    """Send one summary SMS for tomorrow's critical deadlines."""
    margaret_phone = os.getenv("MARGARET_PHONE")
    if not margaret_phone:
        log("MARGARET_PHONE missing - skipping critical deadline alert.")
        return

    tomorrow = date.today() + timedelta(days=1)
    critical = execute_query(
        """
        SELECT d.id, d.deadline_type, d.deadline_date, t.property_address
        FROM deadlines d
        JOIN transactions t ON t.id = d.transaction_id
        WHERE d.deadline_date = %s
          AND d.completed = FALSE
          AND d.is_critical = TRUE
          AND t.status = 'ACTIVE'
        ORDER BY t.property_address ASC
        """,
        (tomorrow,),
        fetch=True,
    ) or []
    if not critical:
        log("No critical deadlines tomorrow.")
        return

    message_lines = [f"Critical deadlines tomorrow ({len(critical)}):"]
    for item in critical[:6]:
        deadline_label = item["deadline_type"].replace("_", " ").title()
        message_lines.append(f"- {item['property_address']}: {deadline_label}")
    if len(critical) > 6:
        message_lines.append(f"+ {len(critical) - 6} more in dashboard")
    message_lines.append("- Maverick TC")

    sid = notify_sms(margaret_phone, "\n".join(message_lines))
    log(f"Sent critical summary to Margaret sid={sid}")


def send_overdue_deadline_alert_to_margaret():
    """Send one summary SMS for overdue incomplete deadlines."""
    margaret_phone = os.getenv("MARGARET_PHONE")
    if not margaret_phone:
        log("MARGARET_PHONE missing - skipping overdue alert.")
        return

    today = date.today()
    overdue = execute_query(
        """
        SELECT d.id, d.deadline_type, d.deadline_date, t.property_address
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
    if not overdue:
        log("No overdue deadlines.")
        return

    message_lines = [f"Overdue deadlines ({len(overdue)}):"]
    for item in overdue[:6]:
        days_overdue = (today - item["deadline_date"]).days
        deadline_label = item["deadline_type"].replace("_", " ").title()
        message_lines.append(f"- {item['property_address']}: {deadline_label} ({days_overdue}d)")
    if len(overdue) > 6:
        message_lines.append(f"+ {len(overdue) - 6} more in dashboard")
    message_lines.append("- Maverick TC")

    sid = notify_sms(margaret_phone, "\n".join(message_lines))
    log(f"Sent overdue summary to Margaret sid={sid}")


def main(dry_run=False):
    """Run the full reminder job."""
    global DRY_RUN
    DRY_RUN = dry_run

    log("Starting reminder job")
    if DRY_RUN:
        log("Mode: DRY-RUN (no SMS and no DB writes)")

    try:
        reminders_sent = send_stage_reminders()
        log(f"Total reminder texts sent: {reminders_sent}")
        send_critical_deadline_alert_to_margaret()
        send_overdue_deadline_alert_to_margaret()
        log("Reminder job completed successfully")
    except Exception as exc:
        log(f"ERROR: reminder job failed: {exc}")
        traceback.print_exc()

        heidi_phone = os.getenv("HEIDI_PHONE")
        if heidi_phone:
            notify_sms(heidi_phone, f"Maverick reminder job failed: {str(exc)[:140]}")
        raise


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Run Maverick reminder automation.")
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Simulate reminder job without SMS sends or DB writes.",
    )
    cli_args = parser.parse_args()
    main(dry_run=cli_args.dry_run)
