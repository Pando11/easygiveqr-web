#!/usr/bin/env python3
"""
Stripe Minion: Payment Link Sender

Purpose:
- Send payment links for overdue upfront payments
- Send payment links for near-closing unpaid closing payments
"""

from __future__ import annotations

import argparse
from datetime import date

from minions.common import get_context, log_communication, payment_link, send_or_print
from utils.db import execute_query
from utils.payments import calculate_payment_breakdown


def fetch_candidates(limit: int) -> list[dict]:
    return execute_query(
        """
        SELECT id, property_address, agent_name, agent_phone,
               rush_service, referred_by_agent,
               payment_upfront_paid, payment_closing_paid,
               closing_date, created_at, status
        FROM transactions
        WHERE status = 'ACTIVE'
        ORDER BY created_at DESC
        LIMIT %s
        """,
        (limit,),
        fetch=True,
    ) or []


def needs_upfront_reminder(txn: dict) -> bool:
    if txn["payment_upfront_paid"]:
        return False
    created = txn["created_at"].date() if txn["created_at"] else date.today()
    return (date.today() - created).days >= 1


def needs_closing_reminder(txn: dict) -> bool:
    if txn["payment_closing_paid"]:
        return False
    if not txn["closing_date"]:
        return False
    days_until_closing = (txn["closing_date"] - date.today()).days
    return days_until_closing <= 3


def send_payment_link_for_type(txn: dict, payment_type: str, dry_run: bool) -> bool:
    context = get_context(dry_run=dry_run)
    breakdown = calculate_payment_breakdown(txn, payment_type)
    url = payment_link(context, txn["id"], payment_type)
    amount = breakdown["amount"]

    message = (
        f"Maverick payment reminder: ${amount:.2f} is due for {txn['property_address']}.\n\n"
        f"Pay securely: {url}\n\n"
        "If already paid via Venmo/PayPal, reply to confirm.\n- Maverick TC"
    )
    result = send_or_print(context, txn["agent_phone"], message)
    if not result:
        return False

    log_communication(
        transaction_id=txn["id"],
        communication_type="text",
        contact_party="agent",
        contact_name=txn["agent_name"],
        summary=f"Stripe minion sent {payment_type} payment link (${amount:.2f})",
        outcome=f"Link: {url}",
        dry_run=dry_run,
    )
    return True


def run(limit: int, dry_run: bool) -> int:
    sent = 0
    candidates = fetch_candidates(limit)
    print(f"Evaluating {len(candidates)} transactions for payment links")

    for txn in candidates:
        if needs_upfront_reminder(txn):
            if send_payment_link_for_type(txn, "upfront", dry_run=dry_run):
                sent += 1

        if needs_closing_reminder(txn):
            if send_payment_link_for_type(txn, "closing", dry_run=dry_run):
                sent += 1

    print(f"Payment Link Minion complete. Messages sent: {sent}")
    return sent


def main() -> None:
    parser = argparse.ArgumentParser(description="Run Stripe payment link minion.")
    parser.add_argument("--limit", type=int, default=250, help="Max transactions to evaluate")
    parser.add_argument("--dry-run", action="store_true", help="Print actions without sending SMS")
    args = parser.parse_args()

    run(limit=args.limit, dry_run=args.dry_run)


if __name__ == "__main__":
    main()
