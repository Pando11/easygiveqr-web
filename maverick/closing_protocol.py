#!/usr/bin/env python3
"""
Maverick closing protocol automation.

Suggested cron schedule:
  - 8:00 AM  -> morning alert to Margaret
  - 10:00 AM -> agent reminders
  - 5:00 PM  -> request closing confirmation

If run without --window, the script selects the correct action by current time.
"""

import argparse
import os
import sys
import traceback
from datetime import date, datetime, time

from dotenv import load_dotenv

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
load_dotenv()

from utils.db import execute_query
from utils.sms import send_sms

DRY_RUN = False


def log(message):
    """Timestamped logging for cron visibility."""
    print(f"[{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}] {message}")


def notify_sms(to_number, message):
    """Send SMS or print output in dry-run mode."""
    if DRY_RUN:
        log(f"[DRY-RUN] SMS to {to_number}: {message[:220]}")
        return "dry-run"
    return send_sms(to_number, message)


def fetch_todays_closings():
    """Return active transactions closing today."""
    return execute_query(
        """
        SELECT id, property_address, agent_name, agent_phone
        FROM transactions
        WHERE closing_date = %s
          AND status = 'ACTIVE'
        ORDER BY property_address ASC
        """,
        (date.today(),),
        fetch=True,
    ) or []


def morning_alert_margaret():
    """8 AM: send one summary of today's closings to Margaret."""
    closings = fetch_todays_closings()
    if not closings:
        log("No closings today for morning alert.")
        return

    margaret_phone = os.getenv("MARGARET_PHONE")
    if not margaret_phone:
        log("MARGARET_PHONE missing; cannot send morning closing summary.")
        return

    lines = [f"Closings today ({len(closings)}):"]
    for txn in closings[:8]:
        lines.append(f"- {txn['property_address']} ({txn['agent_name']})")
    if len(closings) > 8:
        lines.append(f"+ {len(closings) - 8} more in dashboard")
    lines.append("- Maverick TC")

    sid = notify_sms(margaret_phone, "\n".join(lines))
    log(f"Morning closing summary sent sid={sid}")


def send_agent_closing_reminders():
    """10 AM: remind each agent with required items."""
    closings = fetch_todays_closings()
    if not closings:
        log("No closings today for agent reminders.")
        return

    sent = 0
    for txn in closings:
        if not txn.get("agent_phone"):
            continue
        message = (
            f"Closing day reminder for {txn['property_address']}.\n"
            "Bring government ID and cashier's check or wire confirmation.\n"
            "Reply if you need anything.\n- Maverick TC"
        )
        sid = notify_sms(txn["agent_phone"], message)
        if sid:
            sent += 1

    log(f"Agent closing reminders sent: {sent}")


def evening_confirmation_requests():
    """5 PM: request closing confirmation from each agent."""
    closings = fetch_todays_closings()
    if not closings:
        log("No closings today for evening confirmation.")
        return

    sent = 0
    for txn in closings:
        if not txn.get("agent_phone"):
            continue
        message = (
            f"Did {txn['property_address']} close successfully today?\n"
            "Reply YES to confirm or call Margaret for support.\n- Maverick TC"
        )
        sid = notify_sms(txn["agent_phone"], message)
        if sid:
            sent += 1

    log(f"Evening confirmation requests sent: {sent}")


def determine_window(now_time):
    """Pick protocol window based on local time."""
    if time(8, 0) <= now_time < time(8, 30):
        return "morning"
    if time(10, 0) <= now_time < time(10, 30):
        return "agents"
    if time(17, 0) <= now_time < time(17, 30):
        return "evening"
    return "none"


def run_window(window_name):
    """Execute one protocol window."""
    if window_name == "morning":
        morning_alert_margaret()
    elif window_name == "agents":
        send_agent_closing_reminders()
    elif window_name == "evening":
        evening_confirmation_requests()
    else:
        log("No closing protocol action scheduled for this run.")


def main(window_name="auto", dry_run=False):
    """Entry point for closing protocol runner."""
    global DRY_RUN
    DRY_RUN = dry_run

    log("Starting closing protocol run")
    if DRY_RUN:
        log("Mode: DRY-RUN")

    try:
        selected_window = window_name
        if window_name == "auto":
            selected_window = determine_window(datetime.now().time())
        log(f"Selected window: {selected_window}")
        run_window(selected_window)
        log("Closing protocol run complete")
    except Exception as exc:
        log(f"ERROR: closing protocol failed: {exc}")
        traceback.print_exc()
        heidi_phone = os.getenv("HEIDI_PHONE")
        if heidi_phone:
            notify_sms(heidi_phone, f"Maverick closing protocol failed: {str(exc)[:140]}")
        raise


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Run Maverick closing-day protocol.")
    parser.add_argument(
        "--window",
        choices=["auto", "morning", "agents", "evening"],
        default="auto",
        help="Force a specific protocol window or use auto by current time.",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Print actions without sending SMS.",
    )
    args = parser.parse_args()
    main(window_name=args.window, dry_run=args.dry_run)
