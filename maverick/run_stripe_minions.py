#!/usr/bin/env python3
"""
Run one or more Stripe minions from a single command.

Examples:
  python run_stripe_minions.py --all --dry-run
  python run_stripe_minions.py --minion payment-links
  python run_stripe_minions.py --minion dunning --lookback-days 14
"""

from __future__ import annotations

import argparse

from minions.dunning_minion import run as run_dunning
from minions.payment_link_minion import run as run_payment_links
from minions.reconciliation_minion import run as run_reconciliation


def main() -> None:
    parser = argparse.ArgumentParser(description="Run Maverick Stripe minions.")
    parser.add_argument(
        "--minion",
        choices=["payment-links", "dunning", "reconciliation"],
        help="Run a single minion",
    )
    parser.add_argument("--all", action="store_true", help="Run all Stripe minions in sequence")
    parser.add_argument("--dry-run", action="store_true", help="No outbound SMS and no DB writes")
    parser.add_argument("--limit", type=int, default=250, help="Primary scan limit")
    parser.add_argument("--lookback-days", type=int, default=7, help="Stripe event lookback window")
    parser.add_argument("--auto-fix", action="store_true", help="Allow reconciliation DB auto-fix")
    args = parser.parse_args()

    if not args.all and not args.minion:
        parser.error("Choose --all or --minion.")

    if args.all or args.minion == "payment-links":
        print("\n[1/3] Payment Link Minion")
        run_payment_links(limit=args.limit, dry_run=args.dry_run)

    if args.all or args.minion == "dunning":
        print("\n[2/3] Dunning Minion")
        run_dunning(lookback_days=args.lookback_days, limit=max(args.limit, 150), dry_run=args.dry_run)

    if args.all or args.minion == "reconciliation":
        print("\n[3/3] Reconciliation Minion")
        run_reconciliation(
            limit=max(args.limit, 200),
            lookback_days=max(args.lookback_days, 30),
            auto_fix=args.auto_fix and not args.dry_run,
        )

    print("\nStripe minion run complete.")


if __name__ == "__main__":
    main()
