#!/usr/bin/env python3
"""
Automated closing checklist generation/distribution runner.

Suggested Railway cron:
  - Every hour: 0 * * * *
"""

import argparse
import os
import sys
import traceback
from datetime import datetime

from dotenv import load_dotenv

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
load_dotenv()

from utils.closing_checklist import run_closing_checklist_automation
from utils.sms import send_sms


def log(message):
    print(f"[{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}] {message}")


def main(days_before=3):
    log("Starting closing checklist automation run")
    try:
        summary = run_closing_checklist_automation(days_before=days_before)
        generation = summary.get("due_generation") or {}
        auto_send = summary.get("auto_send") or {}
        log(
            "Closing checklist summary: "
            f"target_date={generation.get('target_date')} "
            f"candidates={generation.get('candidate_count', 0)} "
            f"generated={generation.get('generated', 0)} "
            f"skipped_existing={generation.get('skipped_existing', 0)} "
            f"failed={generation.get('failed', 0)} "
            f"auto_candidates={auto_send.get('candidate_count', 0)} "
            f"auto_sent={auto_send.get('auto_sent', 0)} "
            f"auto_failed={auto_send.get('failed', 0)}"
        )
        log("Closing checklist automation run complete")
    except Exception as exc:
        log(f"ERROR: closing checklist automation failed: {exc}")
        traceback.print_exc()
        heidi_phone = os.getenv("HEIDI_PHONE")
        if heidi_phone:
            try:
                send_sms(heidi_phone, f"Maverick closing checklist automation failed: {str(exc)[:140]}")
            except Exception:
                pass
        raise


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Run dynamic closing checklist automation.")
    parser.add_argument(
        "--days-before",
        default=3,
        type=int,
        help="Days before closing date to generate checklist (default: 3).",
    )
    args = parser.parse_args()
    main(days_before=args.days_before)

