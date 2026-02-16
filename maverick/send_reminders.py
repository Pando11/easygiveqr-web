#!/usr/bin/env python3
"""
Maverick TC - Automated Reminder System
Runs daily at 8am via Railway cron
Sends 4-stage reminders: 10d, 7d, 3d, 1d before each deadline.
"""

import os
import sys
import traceback
from datetime import date, timedelta

from dotenv import load_dotenv

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
load_dotenv()

from utils.db import execute_query
from utils.sms import send_reminder, send_sms


def send_deadline_reminders():
    """Send reminders for upcoming deadlines."""
    today = date.today()

    reminder_stages = [
        (10, "reminder_10d_sent", "reminder_10d_sent_at"),
        (7, "reminder_7d_sent", "reminder_7d_sent_at"),
        (3, "reminder_3d_sent", "reminder_3d_sent_at"),
        (1, "reminder_1d_sent", "reminder_1d_sent_at"),
    ]

    reminders_sent = 0

    for days_before, sent_flag, sent_at_flag in reminder_stages:
        target_date = today + timedelta(days=days_before)
        query = f"""
        SELECT d.id, d.deadline_type, d.deadline_date, d.description,
               t.id as transaction_id, t.property_address, t.agent_name, t.agent_phone
        FROM deadlines d
        JOIN transactions t ON d.transaction_id = t.id
        WHERE d.deadline_date = %s
          AND d.completed = FALSE
          AND d.{sent_flag} = FALSE
          AND t.status = 'ACTIVE'
        """

        deadlines = execute_query(query, (target_date,), fetch=True) or []
        print(f"Found {len(deadlines)} deadlines for {days_before}-day reminders")

        for deadline in deadlines:
            success = send_reminder(
                to_number=deadline["agent_phone"],
                property_address=deadline["property_address"],
                deadline_type=deadline["deadline_type"].replace("_", " ").title(),
                deadline_date=deadline["deadline_date"].strftime("%m/%d/%Y"),
                days_until=days_before,
            )

            if success:
                update_query = f"""
                UPDATE deadlines
                SET {sent_flag} = TRUE, {sent_at_flag} = CURRENT_TIMESTAMP
                WHERE id = %s
                """
                execute_query(update_query, (deadline["id"],))
                reminders_sent += 1
                print(
                    f"Sent {days_before}d reminder for "
                    f"{deadline['property_address']} - {deadline['deadline_type']}"
                )
            else:
                print(f"Failed to send reminder for deadline {deadline['id']}")

    return reminders_sent


def send_critical_deadline_alerts():
    """Send alerts to Margaret for critical deadlines within 24 hours."""
    tomorrow = date.today() + timedelta(days=1)
    query = """
    SELECT d.id, d.deadline_type, d.deadline_date,
           t.property_address, t.agent_name, t.agent_phone
    FROM deadlines d
    JOIN transactions t ON d.transaction_id = t.id
    WHERE d.deadline_date = %s
      AND d.is_critical = TRUE
      AND d.completed = FALSE
      AND d.margaret_called_agent = FALSE
      AND t.status = 'ACTIVE'
    """

    critical_deadlines = execute_query(query, (tomorrow,), fetch=True) or []
    if not critical_deadlines:
        return

    message = f"CRITICAL DEADLINES TOMORROW ({len(critical_deadlines)}):\n\n"
    for deadline in critical_deadlines[:5]:
        deadline_type = deadline["deadline_type"].replace("_", " ").title()
        message += f"- {deadline['property_address']}: {deadline_type}\n"
    if len(critical_deadlines) > 5:
        message += f"\n+ {len(critical_deadlines) - 5} more. Check dashboard."
    message += "\nCall agents today to confirm."

    margaret_phone = os.getenv("MARGARET_PHONE")
    if margaret_phone:
        send_sms(margaret_phone, message)
        print(
            f"Sent critical deadline alert to Margaret "
            f"({len(critical_deadlines)} deadlines)"
        )


def check_overdue_deadlines():
    """Check for overdue deadlines and alert Margaret."""
    today = date.today()
    query = """
    SELECT d.id, d.deadline_type, d.deadline_date,
           t.id as transaction_id, t.property_address, t.agent_name
    FROM deadlines d
    JOIN transactions t ON d.transaction_id = t.id
    WHERE d.deadline_date < %s
      AND d.completed = FALSE
      AND t.status = 'ACTIVE'
    """

    overdue = execute_query(query, (today,), fetch=True) or []
    if not overdue:
        return

    message = f"OVERDUE DEADLINES ({len(overdue)}):\n\n"
    for deadline in overdue[:5]:
        days_overdue = (today - deadline["deadline_date"]).days
        deadline_type = deadline["deadline_type"].replace("_", " ").title()
        message += (
            f"- {deadline['property_address']}: {deadline_type} "
            f"({days_overdue}d overdue)\n"
        )
    if len(overdue) > 5:
        message += f"\n+ {len(overdue) - 5} more overdue items."

    margaret_phone = os.getenv("MARGARET_PHONE")
    if margaret_phone:
        send_sms(margaret_phone, message)
        print(f"Sent overdue alert to Margaret ({len(overdue)} deadlines)")


def main():
    """Main reminder job."""
    print("\n" + "=" * 50)
    print("Maverick TC - Daily Reminders")
    print(f"Running at: {date.today()}")
    print("=" * 50 + "\n")

    try:
        reminders_sent = send_deadline_reminders()
        print(f"\nTotal reminders sent to agents: {reminders_sent}")
        send_critical_deadline_alerts()
        check_overdue_deadlines()

        print("\n" + "=" * 50)
        print("Reminder job completed successfully")
        print("=" * 50 + "\n")
    except Exception as exc:
        print(f"\nERROR in reminder job: {exc}")
        traceback.print_exc()
        heidi_phone = os.getenv("HEIDI_PHONE")
        if heidi_phone:
            send_sms(heidi_phone, f"Maverick reminder job failed: {str(exc)[:100]}")


if __name__ == "__main__":
    main()
