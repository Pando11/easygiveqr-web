#!/usr/bin/env python3
"""
Stripe.dev bootstrap validator for Maverick.
"""

from __future__ import annotations

import argparse
import os
from dataclasses import dataclass

import stripe
from dotenv import load_dotenv

load_dotenv()


@dataclass
class Validation:
    name: str
    ok: bool
    details: str


def validate_key_format(name: str, value: str, prefix: str) -> Validation:
    if not value:
        return Validation(name, False, "missing")
    if value.startswith(prefix):
        return Validation(name, True, f"valid ({prefix}*)")
    return Validation(name, False, f"invalid format, expected prefix {prefix}")


def run_checks(check_api: bool) -> int:
    stripe_env = (os.getenv("STRIPE_ENV") or "dev").lower()
    secret = os.getenv("STRIPE_SECRET_KEY", "").strip()
    publishable = os.getenv("STRIPE_PUBLISHABLE_KEY", "").strip()
    webhook_secret = os.getenv("STRIPE_WEBHOOK_SECRET", "").strip()
    app_base_url = os.getenv("APP_BASE_URL", "").strip()

    checks: list[Validation] = []
    checks.append(Validation("STRIPE_ENV", stripe_env in {"dev", "test", "production"}, stripe_env))

    if stripe_env in {"dev", "test"}:
        checks.append(validate_key_format("STRIPE_SECRET_KEY", secret, "sk_test_"))
        checks.append(validate_key_format("STRIPE_PUBLISHABLE_KEY", publishable, "pk_test_"))
    else:
        checks.append(validate_key_format("STRIPE_SECRET_KEY", secret, "sk_live_"))
        checks.append(validate_key_format("STRIPE_PUBLISHABLE_KEY", publishable, "pk_live_"))

    checks.append(validate_key_format("STRIPE_WEBHOOK_SECRET", webhook_secret, "whsec_"))
    checks.append(
        Validation(
            "APP_BASE_URL",
            bool(app_base_url),
            app_base_url or "missing",
        )
    )

    if check_api and secret:
        stripe.api_key = secret
        try:
            account = stripe.Account.retrieve()
            checks.append(
                Validation(
                    "Stripe API connectivity",
                    True,
                    f"connected (account id: {account.get('id', 'unknown')})",
                )
            )
        except Exception as exc:
            checks.append(Validation("Stripe API connectivity", False, str(exc)))

    print("\nStripe.dev bootstrap validation")
    print("=" * 50)
    for item in checks:
        tag = "PASS" if item.ok else "FAIL"
        print(f"[{tag}] {item.name}: {item.details}")
    print("=" * 50)

    failed = [item for item in checks if not item.ok]
    if failed:
        print("\nAction required: fix failed checks before enabling Stripe minions.")
        return 1

    print("\nStripe.dev configuration looks good.")
    return 0


def main() -> None:
    parser = argparse.ArgumentParser(description="Validate Stripe.dev setup for Maverick.")
    parser.add_argument(
        "--check-api",
        action="store_true",
        help="Also call Stripe API to verify credentials/connectivity.",
    )
    args = parser.parse_args()
    raise SystemExit(run_checks(check_api=args.check_api))


if __name__ == "__main__":
    main()
