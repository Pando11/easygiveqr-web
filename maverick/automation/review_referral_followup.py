#!/usr/bin/env python3
"""Scheduled runner for post-close review + referral follow-up emails."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

try:
    from dotenv import load_dotenv
except Exception:  # pragma: no cover - fallback for minimal runtime environments
    def load_dotenv(*_args, **_kwargs):
        return False

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
load_dotenv()

from app import run_post_close_review_referral_automation  # noqa: E402


def parse_args():
    parser = argparse.ArgumentParser(description="Send review/referral follow-ups for completed transactions.")
    parser.add_argument(
        "--days-after-close",
        type=int,
        default=7,
        help="Minimum days since completion before sending (default: 7).",
    )
    parser.add_argument(
        "--limit",
        type=int,
        default=200,
        help="Maximum completed transactions to evaluate in one run (default: 200).",
    )
    return parser.parse_args()


def main():
    args = parse_args()
    result = run_post_close_review_referral_automation(
        days_after_close=args.days_after_close,
        limit=args.limit,
    )
    if not result.get("success"):
        print(f"Review/referral follow-up failed: {result}")
        return 1
    print(
        "Review/referral follow-up complete: "
        f"days_after_close={result.get('days_after_close')} "
        f"evaluated={result.get('evaluated', 0)} "
        f"sent={result.get('sent', 0)} "
        f"failed={result.get('failed', 0)} "
        f"skipped_already_sent={result.get('skipped_already_sent', 0)} "
        f"skipped_already_reviewed={result.get('skipped_already_reviewed', 0)}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
