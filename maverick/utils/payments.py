from __future__ import annotations

from typing import Any

from utils.db import execute_query


def calculate_base_amount(rush_service: bool, payment_type: str) -> float:
    """Return the base amount before referral credits."""
    if payment_type not in {"upfront", "closing"}:
        raise ValueError(f"Unsupported payment type: {payment_type}")

    if rush_service:
        return 300.0  # Rush service total is 600 split as 300 + 300
    return 200.0  # Standard service total is 400 split as 200 + 200


def get_referral_credit(agent_name: str, referred_by_agent: str | None, payment_type: str) -> float:
    """Return available referral credit amount for a given agent/payment."""
    if payment_type != "upfront":
        return 0.0
    if not referred_by_agent:
        return 0.0

    credit_rows = execute_query(
        """
        SELECT credit_amount
        FROM referrals
        WHERE referred_agent_name = %s
          AND credit_used = FALSE
        ORDER BY created_at DESC
        LIMIT 1
        """,
        (agent_name,),
        fetch=True,
    ) or []
    if not credit_rows:
        return 0.0

    return float(credit_rows[0]["credit_amount"])


def calculate_payment_breakdown(transaction: dict[str, Any], payment_type: str) -> dict[str, float]:
    """
    Calculate payment amounts for UI + minions in one place.

    Expected transaction keys:
      - rush_service (bool)
      - agent_name (str)
      - referred_by_agent (str|None)
    """
    base_amount = calculate_base_amount(bool(transaction.get("rush_service")), payment_type)
    referral_credit = get_referral_credit(
        agent_name=str(transaction.get("agent_name") or ""),
        referred_by_agent=transaction.get("referred_by_agent"),
        payment_type=payment_type,
    )
    final_amount = max(base_amount - referral_credit, 0.0)

    return {
        "original_amount": round(base_amount, 2),
        "referral_credit": round(referral_credit, 2),
        "amount": round(final_amount, 2),
    }
