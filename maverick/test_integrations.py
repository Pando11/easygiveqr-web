#!/usr/bin/env python3
"""
Maverick integration connectivity tests for:
1) AWS S3
2) Twilio SMS
3) Stripe API
"""

from __future__ import annotations

import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Tuple

import boto3
import stripe
from botocore.exceptions import BotoCoreError, ClientError
from dotenv import load_dotenv
from twilio.base.exceptions import TwilioRestException
from twilio.rest import Client


def load_environment() -> None:
    """Load variables from local .env file."""
    env_path = Path(__file__).resolve().parent / ".env"
    load_dotenv(dotenv_path=env_path)


def _missing_env(*keys: str) -> list[str]:
    """Return a list of missing env variable names."""
    return [key for key in keys if not os.getenv(key)]


def test_s3_connection() -> Tuple[bool, str]:
    """
    Test AWS S3 by uploading a test object and generating a presigned URL.

    Returns:
        (success, message)
    """
    required = (
        "AWS_ACCESS_KEY_ID",
        "AWS_SECRET_ACCESS_KEY",
        "AWS_S3_BUCKET_DOCUMENTS",
        "AWS_REGION",
    )
    missing = _missing_env(*required)
    if missing:
        return False, f"Missing env vars: {', '.join(missing)}"

    bucket = os.getenv("AWS_S3_BUCKET_DOCUMENTS", "")
    region = os.getenv("AWS_REGION")
    key = f"integration-tests/test_{datetime.now(timezone.utc).strftime('%Y%m%d_%H%M%S')}.txt"
    body = b"Maverick integration test file."

    s3_client = boto3.client(
        "s3",
        aws_access_key_id=os.getenv("AWS_ACCESS_KEY_ID"),
        aws_secret_access_key=os.getenv("AWS_SECRET_ACCESS_KEY"),
        region_name=region,
    )

    uploaded = False
    try:
        s3_client.put_object(Bucket=bucket, Key=key, Body=body, ContentType="text/plain")
        uploaded = True

        presigned_url = s3_client.generate_presigned_url(
            "get_object",
            Params={"Bucket": bucket, "Key": key},
            ExpiresIn=300,
        )

        return True, f"Upload + presigned URL successful (key={key}, url_generated=yes)"
    except (ClientError, BotoCoreError) as exc:
        return False, f"S3 error: {exc}"
    finally:
        if uploaded:
            try:
                s3_client.delete_object(Bucket=bucket, Key=key)
            except Exception:
                # Cleanup failure should not mask test result.
                pass


def test_twilio_sms() -> Tuple[bool, str]:
    """
    Test Twilio SMS by sending a message to HEIDI_PHONE.

    Returns:
        (success, message)
    """
    required = ("TWILIO_ACCOUNT_SID", "TWILIO_AUTH_TOKEN", "TWILIO_PHONE_NUMBER", "HEIDI_PHONE")
    missing = _missing_env(*required)
    if missing:
        return False, f"Missing env vars: {', '.join(missing)}"

    client = Client(os.getenv("TWILIO_ACCOUNT_SID"), os.getenv("TWILIO_AUTH_TOKEN"))
    to_number = os.getenv("HEIDI_PHONE", "")
    from_number = os.getenv("TWILIO_PHONE_NUMBER", "")

    try:
        message = client.messages.create(
            to=to_number,
            from_=from_number,
            body="Maverick TC integration test - SMS working!",
        )
        return True, f"SMS sent successfully (sid={message.sid})"
    except TwilioRestException as exc:
        return False, f"Twilio error: {exc}"
    except Exception as exc:
        return False, f"Unexpected Twilio error: {exc}"


def test_stripe_api() -> Tuple[bool, str]:
    """
    Test Stripe API by creating a test customer.

    Returns:
        (success, message)
    """
    secret_key = os.getenv("STRIPE_SECRET_KEY", "").strip()
    if not secret_key:
        return False, "Missing env var: STRIPE_SECRET_KEY"
    if not secret_key.startswith("sk_test_"):
        return False, "Expected test key format sk_test_* for STRIPE_SECRET_KEY"

    stripe.api_key = secret_key
    email = f"integration-test-{int(datetime.now(timezone.utc).timestamp())}@maverick.local"
    try:
        customer = stripe.Customer.create(
            name="Maverick Integration Test",
            email=email,
            description="Temporary customer created by test_integrations.py",
        )
        customer_id = customer.get("id", "unknown")
        return True, f"Stripe customer created successfully (id={customer_id})"
    except stripe.error.StripeError as exc:
        return False, f"Stripe error: {exc.user_message or str(exc)}"
    except Exception as exc:
        return False, f"Unexpected Stripe error: {exc}"


def main() -> None:
    """Run all integration checks and print a clear summary."""
    load_environment()
    print("Running Maverick integration tests...\n")

    tests = (
        ("AWS S3 Connection", test_s3_connection),
        ("Twilio SMS", test_twilio_sms),
        ("Stripe API", test_stripe_api),
    )

    results: list[Tuple[str, bool, str]] = []
    for label, func in tests:
        try:
            success, details = func()
            results.append((label, success, details))
        except Exception as exc:
            # Ensure one failed test never stops the rest.
            results.append((label, False, f"Unhandled error: {exc}"))

    for label, success, details in results:
        prefix = "✅" if success else "❌"
        print(f"{prefix} {label}: {details}")

    passed_count = sum(1 for _, success, _ in results if success)
    print(f"\nSummary: {passed_count}/{len(results)} integrations passed.")


if __name__ == "__main__":
    main()
