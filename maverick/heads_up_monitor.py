#!/usr/bin/env python3
"""
Maverick Heads Up monitor.

Schedule:
  - Railway cron daily (recommended 6:15 AM)

Responsibilities:
  - Detect watch/urgent pattern signals
  - Persist today's signal set
  - Apply auto-handle preferences
  - Send summary SMS to Margaret (preference-aware)
"""

import argparse
import os
import sys
import traceback
from datetime import datetime

from dotenv import load_dotenv

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
load_dotenv()

from utils.heads_up import run_heads_up_monitor


def log(message):
    """Timestamped logger for cron output."""
    print(f"[{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}] {message}")


def main(send_sms=True):
    log("Starting Heads Up monitor run")
    try:
        result = run_heads_up_monitor(send_sms=send_sms)
        report = result["report"]
        summary = report["summary"]
        log(
            "Heads Up summary: "
            f"healthy={summary['healthy_count']} "
            f"watch={summary['watch_count']} "
            f"urgent={summary['urgent_count']} "
            f"auto_handled={result['auto_handled_count']}"
        )
        if result.get("sms_sid"):
            log(f"Heads Up SMS sent sid={result['sms_sid']}")
        else:
            log("Heads Up SMS not sent (no alert-eligible signals or phone missing).")
        log("Heads Up monitor completed successfully")
    except Exception as exc:
        log(f"ERROR: Heads Up monitor failed: {exc}")
        traceback.print_exc()
        raise


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Run Maverick Heads Up monitor.")
    parser.add_argument(
        "--no-sms",
        action="store_true",
        help="Run detection/persistence without sending summary SMS.",
    )
    args = parser.parse_args()
    main(send_sms=not args.no_sms)
