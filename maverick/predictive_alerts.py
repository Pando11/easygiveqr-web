#!/usr/bin/env python3
"""
Maverick predictive progress alerts.

Schedule:
  - Railway cron daily at 6:00 AM

Responsibilities:
  - Evaluate expected progress by days since effective date
  - Compare expected progress to actual progress (tasks + documents)
  - Flag active transactions below 70% of expected progress
  - Store alert history in predictive_alerts table
  - Send a concise summary SMS to Margaret
"""

import argparse
import os
import sys
import traceback
from datetime import date, datetime

from dotenv import load_dotenv

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
load_dotenv()

from utils.db import execute_query
from utils.sms import send_sms

DRY_RUN = False

DEFAULT_TIMELINE_DAYS = 45
ALERT_THRESHOLD_RATIO = 0.70
MIN_EXPECTED_PROGRESS_PCT = 15.0
MAX_SMS_ITEMS = 5

REQUIRED_DOCUMENT_TYPES = {
    "contract",
    "earnest_receipt",
    "option_receipt",
    "seller_disclosure",
    "inspection_report",
    "appraisal",
    "title_commitment",
    "loan_approval",
    "insurance_binder",
    "settlement_statement",
}


def log(message):
    """Timestamped logger for cron output."""
    print(f"[{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}] {message}")


def notify_sms(to_number, message):
    """Send SMS or print when running in dry-run mode."""
    if DRY_RUN:
        log(f"[DRY-RUN] SMS to {to_number}: {message[:220]}")
        return "dry-run"
    return send_sms(to_number, message)


def ensure_alert_table_exists():
    """Create predictive_alerts table/indexes when missing."""
    statements = (
        """
        CREATE TABLE IF NOT EXISTS predictive_alerts (
            id SERIAL PRIMARY KEY,
            transaction_id INT REFERENCES transactions(id) ON DELETE CASCADE,
            alert_date DATE NOT NULL,
            reason TEXT NOT NULL,
            resolved_date DATE,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
        """,
        """
        CREATE UNIQUE INDEX IF NOT EXISTS idx_predictive_alerts_txn_alert_date
        ON predictive_alerts(transaction_id, alert_date)
        """,
        """
        CREATE INDEX IF NOT EXISTS idx_predictive_alerts_open
        ON predictive_alerts(transaction_id, resolved_date)
        """,
    )

    for statement in statements:
        if DRY_RUN:
            log("[DRY-RUN] Would ensure predictive_alerts table/index exists")
            continue
        if not execute_query(statement):
            raise RuntimeError("Failed to initialize predictive_alerts table/indexes")


def fetch_active_transactions():
    """Return active transactions eligible for progress analysis."""
    return execute_query(
        """
        SELECT id, property_address, effective_date, closing_date, created_at
        FROM transactions
        WHERE status = 'ACTIVE'
        ORDER BY created_at ASC
        """,
        fetch=True,
    ) or []


def calculate_expected_progress(transaction, today):
    """Expected timeline progress percentage for one transaction."""
    effective_date = transaction.get("effective_date")
    if not effective_date:
        return None

    days_since_effective = max((today - effective_date).days, 0)
    closing_date = transaction.get("closing_date")

    if closing_date and closing_date > effective_date:
        timeline_days = (closing_date - effective_date).days
    else:
        timeline_days = DEFAULT_TIMELINE_DAYS

    if timeline_days <= 0:
        timeline_days = DEFAULT_TIMELINE_DAYS

    expected_progress = min(100.0, (days_since_effective / timeline_days) * 100.0)
    return round(expected_progress, 1), days_since_effective, timeline_days


def fetch_task_progress(transaction_id):
    """Return task completion counts and percent for one transaction."""
    rows = execute_query(
        """
        SELECT COUNT(*) AS total_count,
               COALESCE(SUM(
                   CASE
                       WHEN completed = TRUE OR COALESCE(status, 'pending') = 'completed'
                       THEN 1 ELSE 0
                   END
               ), 0) AS completed_count
        FROM tasks
        WHERE transaction_id = %s
        """,
        (transaction_id,),
        fetch=True,
    ) or []

    if not rows:
        return 0, 0, 0.0

    total_count = int(rows[0]["total_count"] or 0)
    completed_count = int(rows[0]["completed_count"] or 0)
    progress_pct = (completed_count / total_count * 100.0) if total_count > 0 else 0.0
    return total_count, completed_count, round(progress_pct, 1)


def fetch_document_progress(transaction_id):
    """Return required-document completion counts and percent."""
    rows = execute_query(
        """
        SELECT DISTINCT document_type
        FROM documents
        WHERE transaction_id = %s
        """,
        (transaction_id,),
        fetch=True,
    ) or []

    existing_types = {row["document_type"] for row in rows if row.get("document_type")}
    received_required = len(existing_types & REQUIRED_DOCUMENT_TYPES)
    required_total = len(REQUIRED_DOCUMENT_TYPES)
    progress_pct = (received_required / required_total * 100.0) if required_total > 0 else 0.0
    return required_total, received_required, round(progress_pct, 1)


def evaluate_transactions():
    """Evaluate progress and return transactions that need predictive alerts."""
    today = date.today()
    transactions = fetch_active_transactions()
    flagged = []

    for transaction in transactions:
        expected_data = calculate_expected_progress(transaction, today)
        if not expected_data:
            log(f"Skipping txn#{transaction['id']} - missing effective_date")
            continue

        expected_progress, days_since_effective, timeline_days = expected_data

        # Avoid noisy alerts immediately after activation.
        if expected_progress < MIN_EXPECTED_PROGRESS_PCT:
            continue

        total_tasks, completed_tasks, task_progress = fetch_task_progress(transaction["id"])
        required_docs, received_docs, doc_progress = fetch_document_progress(transaction["id"])

        actual_progress = round((task_progress + doc_progress) / 2.0, 1)
        progress_ratio = (actual_progress / expected_progress) if expected_progress > 0 else 1.0

        if progress_ratio >= ALERT_THRESHOLD_RATIO:
            continue

        reason = (
            f"Actual {actual_progress:.1f}% is {progress_ratio * 100:.0f}% of expected "
            f"{expected_progress:.1f}% (tasks {completed_tasks}/{total_tasks}, "
            f"docs {received_docs}/{required_docs})"
        )
        flagged.append(
            {
                "transaction_id": transaction["id"],
                "property_address": transaction["property_address"],
                "expected_progress_pct": expected_progress,
                "actual_progress_pct": actual_progress,
                "progress_ratio": progress_ratio,
                "days_since_effective": days_since_effective,
                "timeline_days": timeline_days,
                "reason": reason,
            }
        )

    return flagged


def upsert_daily_alerts(flagged):
    """Insert one alert row per transaction/day when not already present."""
    today = date.today()
    for item in flagged:
        if DRY_RUN:
            log(
                f"[DRY-RUN] Would record alert txn#{item['transaction_id']} "
                f"reason={item['reason']}"
            )
            continue

        execute_query(
            """
            INSERT INTO predictive_alerts (transaction_id, alert_date, reason)
            SELECT %s, %s, %s
            WHERE NOT EXISTS (
                SELECT 1
                FROM predictive_alerts
                WHERE transaction_id = %s
                  AND alert_date = %s
            )
            """,
            (
                item["transaction_id"],
                today,
                item["reason"],
                item["transaction_id"],
                today,
            ),
        )


def resolve_cleared_alerts(flagged):
    """Resolve open alerts when a transaction recovers or leaves ACTIVE status."""
    today = date.today()
    flagged_ids = {item["transaction_id"] for item in flagged}

    if DRY_RUN:
        log("[DRY-RUN] Would resolve predictive alerts no longer matching criteria")
        return

    # Resolve alerts for transactions no longer active.
    execute_query(
        """
        UPDATE predictive_alerts pa
        SET resolved_date = %s
        FROM transactions t
        WHERE pa.transaction_id = t.id
          AND pa.resolved_date IS NULL
          AND t.status <> 'ACTIVE'
        """,
        (today,),
    )

    # Resolve alerts for active transactions no longer flagged.
    open_rows = execute_query(
        """
        SELECT DISTINCT pa.transaction_id
        FROM predictive_alerts pa
        JOIN transactions t ON t.id = pa.transaction_id
        WHERE pa.resolved_date IS NULL
          AND t.status = 'ACTIVE'
        """,
        fetch=True,
    ) or []

    for row in open_rows:
        transaction_id = row["transaction_id"]
        if transaction_id in flagged_ids:
            continue
        execute_query(
            """
            UPDATE predictive_alerts
            SET resolved_date = %s
            WHERE transaction_id = %s
              AND resolved_date IS NULL
            """,
            (today, transaction_id),
        )


def shorten_property_address(value, max_len=28):
    """Compact property address for SMS line length limits."""
    value = (value or "").strip()
    if len(value) <= max_len:
        return value
    return value[: max_len - 1] + "..."


def build_summary_message(flagged):
    """Build a concise summary text for Margaret."""
    if not flagged:
        return None

    lines = [f"Predictive alerts: {len(flagged)} at-risk transaction(s)"]
    for item in flagged[:MAX_SMS_ITEMS]:
        ratio_pct = int(round(item["progress_ratio"] * 100))
        short_address = shorten_property_address(item["property_address"])
        lines.append(
            f"- #{item['transaction_id']} {short_address}: "
            f"{item['actual_progress_pct']:.0f}% vs {item['expected_progress_pct']:.0f}% "
            f"({ratio_pct}% exp)"
        )
    if len(flagged) > MAX_SMS_ITEMS:
        lines.append(f"+ {len(flagged) - MAX_SMS_ITEMS} more in dashboard")
    lines.append("Review TC dashboard priorities today.")
    lines.append("- Maverick TC")
    return "\n".join(lines)


def send_summary_to_margaret(flagged):
    """Send one predictive-alert summary text to Margaret."""
    if not flagged:
        log("No predictive alerts detected.")
        return

    margaret_phone = os.getenv("MARGARET_PHONE")
    if not margaret_phone:
        log("MARGARET_PHONE missing; predictive summary not sent.")
        return

    message = build_summary_message(flagged)
    sid = notify_sms(margaret_phone, message)
    log(f"Predictive summary sent to Margaret sid={sid}")


def main(dry_run=False):
    """Run full predictive alert job."""
    global DRY_RUN
    DRY_RUN = dry_run

    log("Starting predictive alerts run")
    if DRY_RUN:
        log("Mode: DRY-RUN")

    try:
        ensure_alert_table_exists()
        flagged = evaluate_transactions()
        log(f"Flagged transactions: {len(flagged)}")

        for item in flagged:
            log(
                f"FLAG txn#{item['transaction_id']} {item['property_address']} - "
                f"{item['reason']}"
            )

        upsert_daily_alerts(flagged)
        resolve_cleared_alerts(flagged)
        send_summary_to_margaret(flagged)
        log("Predictive alerts run complete")
    except Exception as exc:
        log(f"ERROR: predictive alerts run failed: {exc}")
        traceback.print_exc()

        heidi_phone = os.getenv("HEIDI_PHONE")
        if heidi_phone:
            notify_sms(heidi_phone, f"Maverick predictive_alerts failed: {str(exc)[:140]}")
        raise


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Run Maverick predictive alerts.")
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Run analysis and logs without SMS sends or DB writes.",
    )
    cli_args = parser.parse_args()
    main(dry_run=cli_args.dry_run)
