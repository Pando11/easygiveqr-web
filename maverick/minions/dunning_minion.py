#!/usr/bin/env python3
"""
Stripe Minion: Dunning + Failed Payment Recovery

Scans recent PaymentIntents for recoverable failures and sends retry links.
"""

from __future__ import annotations

import argparse
from datetime import datetime, timedelta

import stripe

from minions.common import (
    get_context,
    log_communication,
    payment_link,
    send_or_print,
    stripe_is_configured,
)
from utils.db import execute_query


RECOVERABLE_STATUSES = {"requires_payment_method", "requires_action"}


def recent_intents(lookback_days: int, limit: int) -> list:
    since = int((datetime.utcnow() - timedelta(days=lookback_days)).timestamp())
    response = stripe.PaymentIntent.list(limit=limit, created={"gte": since})
    return list(response.data)


def already_notified_recently(transaction_id: int, payment_type: str) -> bool:
    rows = execute_query(
        """
        SELECT COUNT(*) AS count
        FROM communications
        WHERE transaction_id = %s
          AND summary ILIKE %s
          AND created_at > CURRENT_TIMESTAMP - INTERVAL '24 hours'
        """,
        (transaction_id, f"%Stripe dunning minion%{payment_type}%"),
        fetch=True,
    ) or []
    if not rows:
        return False
    return int(rows[0]["count"]) > 0


def run(lookback_days: int, limit: int, dry_run: bool) -> int:
    if not stripe_is_configured():
        print("Stripe dunning minion skipped: STRIPE_SECRET_KEY is not configured.")
        return 0

    context = get_context(dry_run=dry_run)
    intents = recent_intents(lookback_days=lookback_days, limit=limit)
    sent = 0

    print(f"Fetched {len(intents)} recent PaymentIntents")
    for intent in intents:
        if intent.status not in RECOVERABLE_STATUSES:
            continue

        metadata = intent.metadata or {}
        transaction_id_raw = metadata.get("transaction_id")
        payment_type = metadata.get("payment_type", "upfront")
        if payment_type not in {"upfront", "closing"}:
            payment_type = "upfront"
        if not transaction_id_raw:
            continue

        try:
            transaction_id = int(transaction_id_raw)
        except ValueError:
            continue

        if already_notified_recently(transaction_id, payment_type):
            continue

        rows = execute_query(
            """
            SELECT id, property_address, agent_name, agent_phone, status
            FROM transactions
            WHERE id = %s
            """,
            (transaction_id,),
            fetch=True,
        ) or []
        if not rows:
            continue

        txn = rows[0]
        if txn["status"] in {"CANCELLED", "COMPLETED"}:
            continue

        amount = (intent.amount or 0) / 100.0
        retry_link = payment_link(context, transaction_id, payment_type)
        failure_reason = ""
        if getattr(intent, "last_payment_error", None):
            failure_reason = getattr(intent.last_payment_error, "message", "") or ""
        reason_line = f"Reason: {failure_reason}\n\n" if failure_reason else ""

        msg = (
            f"We could not process your {payment_type} payment (${amount:.2f}) "
            f"for {txn['property_address']}.\n\n"
            f"Retry securely: {retry_link}\n\n"
            f"{reason_line}"
            "- Maverick TC"
        )

        result = send_or_print(context, txn["agent_phone"], msg)
        if not result:
            continue

        log_communication(
            transaction_id=transaction_id,
            communication_type="text",
            contact_party="agent",
            contact_name=txn["agent_name"],
            summary=(
                f"Stripe dunning minion sent retry link for {payment_type} "
                f"(PaymentIntent {intent.id})"
            ),
            outcome=f"status={intent.status}",
            dry_run=dry_run,
        )
        sent += 1

    print(f"Dunning minion complete. Retry reminders sent: {sent}")
    return sent


def main() -> None:
    parser = argparse.ArgumentParser(description="Run Stripe dunning minion.")
    parser.add_argument("--lookback-days", type=int, default=7)
    parser.add_argument("--limit", type=int, default=200)
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()

    run(lookback_days=args.lookback_days, limit=args.limit, dry_run=args.dry_run)


if __name__ == "__main__":
    main()
