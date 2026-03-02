#!/usr/bin/env python3
"""
Stripe Minion: Payment Reconciliation

Compares Stripe succeeded intents against transaction payment flags.
Optionally auto-fixes DB flags when Stripe shows successful payment.
"""

from __future__ import annotations

import argparse
from datetime import datetime, timedelta

import stripe

from minions.common import stripe_is_configured
from utils.db import execute_query


def fetch_transactions(limit: int) -> list[dict]:
    return execute_query(
        """
        SELECT id, property_address, status,
               payment_upfront_paid, payment_closing_paid
        FROM transactions
        WHERE status IN ('ACTIVE', 'COMPLETED')
        ORDER BY created_at DESC
        LIMIT %s
        """,
        (limit,),
        fetch=True,
    ) or []


def fetch_succeeded_intents(lookback_days: int, limit: int) -> list:
    since = int((datetime.utcnow() - timedelta(days=lookback_days)).timestamp())
    intent_list = stripe.PaymentIntent.list(limit=min(limit, 100), created={"gte": since})
    intents = []
    for intent in intent_list.auto_paging_iter():
        intents.append(intent)
        if len(intents) >= limit:
            break
    return intents


def build_intent_index(intents: list) -> dict[int, dict[str, list[str] | bool]]:
    index: dict[int, dict[str, list[str] | bool]] = {}
    for intent in intents:
        if intent.status != "succeeded":
            continue
        metadata = intent.metadata or {}
        transaction_id_raw = metadata.get("transaction_id")
        payment_type = metadata.get("payment_type", "upfront")
        if payment_type not in {"upfront", "closing"}:
            continue
        if not transaction_id_raw:
            continue

        try:
            transaction_id = int(transaction_id_raw)
        except ValueError:
            continue

        current = index.setdefault(
            transaction_id,
            {"upfront": False, "closing": False, "intent_ids": []},
        )
        current[payment_type] = True
        current["intent_ids"].append(intent.id)
    return index


def apply_fix(transaction_id: int, payment_type: str) -> None:
    if payment_type == "upfront":
        execute_query(
            """
            UPDATE transactions
            SET payment_upfront_paid = TRUE,
                payment_upfront_date = COALESCE(payment_upfront_date, CURRENT_TIMESTAMP),
                updated_at = CURRENT_TIMESTAMP
            WHERE id = %s
            """,
            (transaction_id,),
        )
    else:
        execute_query(
            """
            UPDATE transactions
            SET payment_closing_paid = TRUE,
                payment_closing_date = COALESCE(payment_closing_date, CURRENT_TIMESTAMP),
                updated_at = CURRENT_TIMESTAMP
            WHERE id = %s
            """,
            (transaction_id,),
        )


def run(limit: int, lookback_days: int, auto_fix: bool) -> int:
    if not stripe_is_configured():
        print("Reconciliation minion skipped: STRIPE_SECRET_KEY is not configured.")
        return 0

    transactions = fetch_transactions(limit=limit)
    intents = fetch_succeeded_intents(lookback_days=lookback_days, limit=max(limit * 4, 300))
    index = build_intent_index(intents)

    mismatches = []
    fixes_applied = 0

    for txn in transactions:
        stripe_info = index.get(txn["id"], {"upfront": False, "closing": False, "intent_ids": []})
        checks = [
            ("upfront", bool(txn["payment_upfront_paid"]), bool(stripe_info["upfront"])),
            ("closing", bool(txn["payment_closing_paid"]), bool(stripe_info["closing"])),
        ]

        for payment_type, db_paid, stripe_paid in checks:
            if db_paid == stripe_paid:
                continue

            mismatch = {
                "transaction_id": txn["id"],
                "property_address": txn["property_address"],
                "payment_type": payment_type,
                "db_paid": db_paid,
                "stripe_paid": stripe_paid,
            }
            mismatches.append(mismatch)

            if auto_fix and stripe_paid and not db_paid:
                apply_fix(txn["id"], payment_type)
                fixes_applied += 1

    print("\nStripe Reconciliation Report")
    print("=" * 60)
    print(f"Transactions scanned: {len(transactions)}")
    print(f"Succeeded intents scanned: {len(intents)}")
    print(f"Mismatches found: {len(mismatches)}")
    if auto_fix:
        print(f"Auto-fixes applied: {fixes_applied}")
    print("-" * 60)

    for item in mismatches[:50]:
        print(
            f"txn={item['transaction_id']} {item['property_address']} | "
            f"{item['payment_type']} | db={item['db_paid']} stripe={item['stripe_paid']}"
        )
    if len(mismatches) > 50:
        print(f"... {len(mismatches) - 50} more mismatches not shown")
    print("=" * 60 + "\n")

    return len(mismatches)


def main() -> None:
    parser = argparse.ArgumentParser(description="Run Stripe reconciliation minion.")
    parser.add_argument("--limit", type=int, default=300, help="Transactions to inspect")
    parser.add_argument("--lookback-days", type=int, default=60)
    parser.add_argument("--auto-fix", action="store_true", help="Apply DB fixes where safe")
    args = parser.parse_args()

    run(limit=args.limit, lookback_days=args.lookback_days, auto_fix=args.auto_fix)


if __name__ == "__main__":
    main()
