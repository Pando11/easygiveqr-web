#!/usr/bin/env python3
"""Scheduled weekly agent status updates runner."""

from __future__ import annotations

import sys
from pathlib import Path

from dotenv import load_dotenv

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
load_dotenv()

from utils.agent_status_updates import run_scheduled_agent_status_updates  # noqa: E402


def main():
    result = run_scheduled_agent_status_updates()
    if not result.get("success"):
        print(f"Agent status update run failed: {result}")
        return 1
    if result.get("skipped"):
        print(f"Agent status update run skipped: {result.get('reason', 'not_due')}")
        return 0

    print(
        "Agent status update run complete: "
        f"candidate_count={result.get('candidate_count', 0)} "
        f"sent_count={result.get('sent_count', 0)} "
        f"failed_count={result.get('failed_count', 0)} "
        f"run_id={result.get('run_id', 'n/a')}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
