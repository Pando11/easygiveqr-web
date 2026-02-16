#!/usr/bin/env python3
"""
Prints a runtime briefing for Stripe minions.

Useful before enabling cron jobs in production.
"""

from __future__ import annotations

import json
import os

from dotenv import load_dotenv

load_dotenv()


def mask(value: str) -> str:
    if not value:
        return "<missing>"
    if len(value) < 10:
        return "***"
    return f"{value[:6]}...{value[-4:]}"


def main() -> None:
    payload = {
        "project": "Maverick Transaction Coordinator",
        "base_url": os.getenv("APP_BASE_URL", "http://localhost:5000"),
        "stripe": {
            "secret_key": mask(os.getenv("STRIPE_SECRET_KEY", "")),
            "publishable_key": mask(os.getenv("STRIPE_PUBLISHABLE_KEY", "")),
            "webhook_secret": mask(os.getenv("STRIPE_WEBHOOK_SECRET", "")),
        },
        "webhook_endpoint": "/stripe/webhook",
        "minions": [
            {
                "name": "payment-links",
                "command": "python run_stripe_minions.py --minion payment-links",
                "goal": "Send links for overdue upfront and near-closing payments",
            },
            {
                "name": "dunning",
                "command": "python run_stripe_minions.py --minion dunning",
                "goal": "Recover failed payments from recent Stripe intents",
            },
            {
                "name": "reconciliation",
                "command": "python run_stripe_minions.py --minion reconciliation",
                "goal": "Compare Stripe vs DB and report mismatches",
            },
        ],
    }
    print(json.dumps(payload, indent=2))


if __name__ == "__main__":
    main()
