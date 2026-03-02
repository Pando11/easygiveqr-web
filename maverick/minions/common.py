from __future__ import annotations

import os
from dataclasses import dataclass
from datetime import datetime

import stripe
from dotenv import load_dotenv

from utils.db import execute_query
from utils.sms import send_sms

load_dotenv()

stripe.api_key = os.getenv("STRIPE_SECRET_KEY")


@dataclass(frozen=True)
class MinionContext:
    base_url: str
    dry_run: bool


def get_context(dry_run: bool = False) -> MinionContext:
    base_url = (os.getenv("APP_BASE_URL") or "http://localhost:5000").rstrip("/")
    return MinionContext(base_url=base_url, dry_run=dry_run)


def payment_link(context: MinionContext, transaction_id: int, payment_type: str) -> str:
    return f"{context.base_url}/pay/{transaction_id}/{payment_type}"


def send_or_print(context: MinionContext, to_number: str, body: str) -> str | None:
    """Send SMS in normal mode; print in dry-run mode."""
    if context.dry_run:
        print(f"[DRY-RUN] SMS to {to_number}: {body[:220]}")
        return "dry-run"
    return send_sms(to_number, body)


def log_communication(
    transaction_id: int,
    communication_type: str,
    contact_party: str,
    contact_name: str,
    summary: str,
    outcome: str | None = None,
    dry_run: bool = False,
) -> None:
    if dry_run:
        print(
            "[DRY-RUN] Log communication:",
            transaction_id,
            communication_type,
            contact_party,
            summary[:120],
        )
        return

    execute_query(
        """
        INSERT INTO communications (
            transaction_id, communication_type, contact_party, contact_name, summary, outcome, created_at
        )
        VALUES (%s, %s, %s, %s, %s, %s, %s)
        """,
        (
            transaction_id,
            communication_type,
            contact_party,
            contact_name,
            summary,
            outcome,
            datetime.utcnow(),
        ),
    )


def stripe_is_configured() -> bool:
    return bool(stripe.api_key)

