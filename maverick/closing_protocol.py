#!/usr/bin/env python3
"""
Maverick TC - Closing Day Protocol
Runs multiple times on closing day to ensure smooth closing.
"""

import os
import sys
from datetime import date, datetime, time

from dotenv import load_dotenv

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
load_dotenv()

from utils.db import execute_query
from utils.sms import send_sms


def morning_closing_alerts():
    """8am: Alert Margaret of today's closings."""
    today = date.today()
    query = """
    SELECT t.id, t.property_address, t.agent_name, t.agent_phone, t.closing_date
    FROM transactions t
    WHERE t.closing_date = %s
      AND t.status = 'ACTIVE'
    ORDER BY t.property_address
    """

    closings_today = execute_query(query, (today,), fetch=True) or []
    if not closings_today:
        print("No closings today")
        return

    message = f"CLOSINGS TODAY ({len(closings_today)}):\n\n"
    for txn in closings_today:
        message += f"- {txn['property_address']}\n  Agent: {txn['agent_name']}\n\n"
    message += "Stay available for any last-minute issues."

    margaret_phone = os.getenv("MARGARET_PHONE")
    if margaret_phone:
        send_sms(margaret_phone, message)
        print(f"Sent morning closing alert to Margaret ({len(closings_today)} closings)")


def send_agent_closing_reminders():
    """10am: Remind agents about today's closings."""
    today = date.today()
    query = """
    SELECT t.id, t.property_address, t.agent_name, t.agent_phone
    FROM transactions t
    WHERE t.closing_date = %s
      AND t.status = 'ACTIVE'
    """

    closings_today = execute_query(query, (today,), fetch=True) or []
    for txn in closings_today:
        message = f"""Your closing for {txn['property_address']} is today.

Bring:
- Government ID
- Cashier's check or wire confirmation

Questions? Reply to this text.

- Maverick TC"""
        send_sms(txn["agent_phone"], message)
        print(f"Sent closing reminder to {txn['agent_name']}")


def evening_confirmation_requests():
    """5pm: Request confirmation that closings occurred."""
    today = date.today()
    query = """
    SELECT t.id, t.property_address, t.agent_name, t.agent_phone
    FROM transactions t
    WHERE t.closing_date = %s
      AND t.status = 'ACTIVE'
    """

    closings_today = execute_query(query, (today,), fetch=True) or []
    for txn in closings_today:
        message = f"""Did {txn['property_address']} close successfully today?

Reply YES to confirm or call Margaret if there are issues.

- Maverick TC"""
        send_sms(txn["agent_phone"], message)
        print(f"Sent confirmation request to {txn['agent_name']}")


def main():
    """Run appropriate closing protocol based on current time."""
    now = datetime.now()
    current_time = now.time()
    print(f"\nClosing Protocol - {now.strftime('%Y-%m-%d %H:%M')}")

    if time(8, 0) <= current_time < time(8, 30):
        print("Running: Morning closing alerts")
        morning_closing_alerts()
    elif time(10, 0) <= current_time < time(10, 30):
        print("Running: Agent closing reminders")
        send_agent_closing_reminders()
    elif time(17, 0) <= current_time < time(17, 30):
        print("Running: Evening confirmation requests")
        evening_confirmation_requests()
    else:
        print(f"No protocol scheduled for {current_time}")


if __name__ == "__main__":
    main()
