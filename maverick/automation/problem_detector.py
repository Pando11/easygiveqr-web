#!/usr/bin/env python3
"""
AI-powered problem detection and solution recommendation system.

Run every 6 hours to detect transaction risk patterns, recommend actions,
and deliver a health summary to Margaret.
"""

from __future__ import annotations

import json
import os
import re
import sys
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Any

from anthropic import Anthropic
from dotenv import load_dotenv
from twilio.rest import Client

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
load_dotenv()

from utils.db import execute_query, get_active_transactions
from utils.email import send_email, send_html_email
from utils.sms import send_sms

DEFAULT_SETTINGS = {
    "sensitivity_level": "standard",
    "notification_mode": "urgent_only",
    "ai_enabled": True,
    "auto_execute_actions": [],
}

SENSITIVITY_THRESHOLDS = {
    "relaxed": {"healthy_min": 78, "watch_min": 55},
    "standard": {"healthy_min": 80, "watch_min": 60},
    "aggressive": {"healthy_min": 85, "watch_min": 68},
}

KNOWN_AUTO_ACTIONS = {
    "call_lender",
    "send_draft_extension",
    "schedule_conference_call",
}

REQUIRED_PROGRESS_DOC_TYPES = (
    "earnest_receipt",
    "option_receipt",
    "seller_disclosure",
    "inspection_report",
    "appraisal",
    "title_commitment",
    "loan_approval",
)


def parse_json_field(raw_value: Any, default_value: Any):
    """Safe JSON parser for DB JSON/text fields."""
    if raw_value is None:
        return default_value
    if isinstance(raw_value, (dict, list)):
        return raw_value
    if isinstance(raw_value, str):
        try:
            return json.loads(raw_value)
        except Exception:
            return default_value
    return default_value


def normalize_phone(value):
    """Normalize phone numbers to Twilio-friendly format when possible."""
    digits = re.sub(r"\D", "", value or "")
    if len(digits) == 10:
        return f"+1{digits}"
    if len(digits) == 11 and digits.startswith("1"):
        return f"+{digits}"
    if value and str(value).startswith("+"):
        return str(value).strip()
    return f"+{digits}" if digits else ""


def normalize_email(value):
    """Normalize email strings."""
    return (value or "").strip().lower()


def now_utc():
    return datetime.utcnow()


def ensure_problem_detection_tables():
    """Create persistence tables for problem detection runs and settings."""
    execute_query(
        """
        CREATE TABLE IF NOT EXISTS problem_detection_settings (
            id SERIAL PRIMARY KEY,
            sensitivity_level VARCHAR(20) DEFAULT 'standard',
            notification_mode VARCHAR(20) DEFAULT 'urgent_only',
            ai_enabled BOOLEAN DEFAULT TRUE,
            auto_execute_actions JSONB DEFAULT '[]'::jsonb,
            updated_by VARCHAR(100),
            updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
        """
    )
    execute_query(
        """
        CREATE TABLE IF NOT EXISTS problem_detection_whitelist (
            id SERIAL PRIMARY KEY,
            transaction_id INT UNIQUE REFERENCES transactions(id) ON DELETE CASCADE,
            reason TEXT,
            active BOOLEAN DEFAULT TRUE,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
        """
    )
    execute_query(
        """
        CREATE TABLE IF NOT EXISTS problem_detection_runs (
            id SERIAL PRIMARY KEY,
            started_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            completed_at TIMESTAMP,
            sensitivity_level VARCHAR(20),
            notification_mode VARCHAR(20),
            ai_enabled BOOLEAN DEFAULT TRUE,
            auto_execute_actions JSONB DEFAULT '[]'::jsonb,
            healthy_count INT DEFAULT 0,
            watch_count INT DEFAULT 0,
            urgent_count INT DEFAULT 0,
            sms_sid VARCHAR(120),
            email_message_id VARCHAR(255),
            notes TEXT
        )
        """
    )
    execute_query(
        """
        CREATE TABLE IF NOT EXISTS problem_detection_results (
            id SERIAL PRIMARY KEY,
            run_id INT REFERENCES problem_detection_runs(id) ON DELETE CASCADE,
            transaction_id INT REFERENCES transactions(id) ON DELETE CASCADE,
            health_score INT NOT NULL,
            bucket VARCHAR(20) NOT NULL,
            issues JSONB DEFAULT '[]'::jsonb,
            suggestions JSONB DEFAULT '[]'::jsonb,
            auto_actions JSONB DEFAULT '[]'::jsonb,
            status VARCHAR(20) DEFAULT 'open',
            handled_by VARCHAR(100),
            handled_at TIMESTAMP,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
        """
    )
    execute_query(
        """
        CREATE UNIQUE INDEX IF NOT EXISTS idx_problem_detection_results_run_txn
        ON problem_detection_results(run_id, transaction_id)
        """
    )
    execute_query(
        """
        CREATE INDEX IF NOT EXISTS idx_problem_detection_results_bucket_status
        ON problem_detection_results(bucket, status, created_at DESC)
        """
    )
    execute_query(
        """
        CREATE INDEX IF NOT EXISTS idx_problem_detection_whitelist_active
        ON problem_detection_whitelist(active, transaction_id)
        """
    )
    execute_query(
        """
        CREATE INDEX IF NOT EXISTS idx_problem_detection_runs_completed
        ON problem_detection_runs(completed_at DESC)
        """
    )

    rows = execute_query(
        """
        SELECT id
        FROM problem_detection_settings
        ORDER BY id ASC
        LIMIT 1
        """,
        fetch=True,
    ) or []
    if not rows:
        execute_query(
            """
            INSERT INTO problem_detection_settings (
                sensitivity_level, notification_mode, ai_enabled, auto_execute_actions, updated_by, updated_at
            )
            VALUES ('standard', 'urgent_only', TRUE, '[]'::jsonb, 'system', CURRENT_TIMESTAMP)
            """
        )


def fetch_problem_detection_settings():
    """Return merged settings map for problem detection behavior."""
    ensure_problem_detection_tables()
    rows = execute_query(
        """
        SELECT id, sensitivity_level, notification_mode, ai_enabled, auto_execute_actions, updated_by, updated_at
        FROM problem_detection_settings
        ORDER BY id ASC
        LIMIT 1
        """,
        fetch=True,
    ) or []
    if not rows:
        return dict(DEFAULT_SETTINGS)
    row = rows[0]
    sensitivity = (row.get("sensitivity_level") or "standard").strip().lower()
    if sensitivity not in SENSITIVITY_THRESHOLDS:
        sensitivity = "standard"
    notification_mode = (row.get("notification_mode") or "urgent_only").strip().lower()
    if notification_mode not in {"urgent_only", "all", "none"}:
        notification_mode = "urgent_only"

    auto_execute_actions = row.get("auto_execute_actions") or []
    if isinstance(auto_execute_actions, str):
        auto_execute_actions = []
    filtered_actions = [
        action for action in auto_execute_actions if isinstance(action, str) and action in KNOWN_AUTO_ACTIONS
    ]
    return {
        "id": row.get("id"),
        "sensitivity_level": sensitivity,
        "notification_mode": notification_mode,
        "ai_enabled": bool(row.get("ai_enabled", True)),
        "auto_execute_actions": filtered_actions,
        "updated_by": row.get("updated_by") or "",
        "updated_at": row.get("updated_at"),
    }


def update_problem_detection_settings(
    sensitivity_level,
    notification_mode,
    ai_enabled=True,
    auto_execute_actions=None,
    updated_by="margaret",
):
    """Save top-level problem detection settings."""
    ensure_problem_detection_tables()
    sensitivity = (sensitivity_level or "standard").strip().lower()
    if sensitivity not in SENSITIVITY_THRESHOLDS:
        sensitivity = "standard"
    mode = (notification_mode or "urgent_only").strip().lower()
    if mode not in {"urgent_only", "all", "none"}:
        mode = "urgent_only"

    actions = []
    for raw in auto_execute_actions or []:
        if not isinstance(raw, str):
            continue
        action = raw.strip()
        if action in KNOWN_AUTO_ACTIONS and action not in actions:
            actions.append(action)

    rows = execute_query(
        """
        SELECT id
        FROM problem_detection_settings
        ORDER BY id ASC
        LIMIT 1
        """,
        fetch=True,
    ) or []
    if rows:
        execute_query(
            """
            UPDATE problem_detection_settings
            SET sensitivity_level = %s,
                notification_mode = %s,
                ai_enabled = %s,
                auto_execute_actions = %s::jsonb,
                updated_by = %s,
                updated_at = CURRENT_TIMESTAMP
            WHERE id = %s
            """,
            (sensitivity, mode, bool(ai_enabled), json.dumps(actions), (updated_by or "margaret")[:100], rows[0]["id"]),
        )
    else:
        execute_query(
            """
            INSERT INTO problem_detection_settings (
                sensitivity_level, notification_mode, ai_enabled, auto_execute_actions, updated_by, updated_at
            )
            VALUES (%s, %s, %s, %s::jsonb, %s, CURRENT_TIMESTAMP)
            """,
            (sensitivity, mode, bool(ai_enabled), json.dumps(actions), (updated_by or "margaret")[:100]),
        )
    return True


def fetch_problem_detection_whitelist(active_only=False):
    """Return whitelist rows, optionally only active entries."""
    ensure_problem_detection_tables()
    clause = "WHERE active = TRUE" if active_only else ""
    return execute_query(
        f"""
        SELECT id, transaction_id, reason, active, created_at, updated_at
        FROM problem_detection_whitelist
        {clause}
        ORDER BY active DESC, updated_at DESC, id DESC
        """,
        fetch=True,
    ) or []


def upsert_problem_detection_whitelist(transaction_id, reason="", active=True):
    """Add/update one transaction whitelist entry."""
    ensure_problem_detection_tables()
    try:
        transaction_id = int(transaction_id)
    except (TypeError, ValueError):
        return False
    if transaction_id <= 0:
        return False

    execute_query(
        """
        INSERT INTO problem_detection_whitelist (transaction_id, reason, active, updated_at)
        VALUES (%s, %s, %s, CURRENT_TIMESTAMP)
        ON CONFLICT (transaction_id)
        DO UPDATE SET
            reason = EXCLUDED.reason,
            active = EXCLUDED.active,
            updated_at = CURRENT_TIMESTAMP
        """,
        (transaction_id, (reason or "")[:500] or None, bool(active)),
    )
    return True


def deactivate_problem_detection_whitelist(whitelist_id):
    """Mark one whitelist row inactive."""
    try:
        whitelist_id = int(whitelist_id)
    except (TypeError, ValueError):
        return False
    execute_query(
        """
        UPDATE problem_detection_whitelist
        SET active = FALSE,
            updated_at = CURRENT_TIMESTAMP
        WHERE id = %s
        """,
        (whitelist_id,),
    )
    return True


def calculate_expected_progress(days_since_effective, days_to_closing):
    """Estimate expected progress percentage for the transaction timeline."""
    days_since_effective = max(int(days_since_effective or 0), 0)
    if days_to_closing is None:
        total_days = max(days_since_effective, 30)
    else:
        total_days = max(days_since_effective + max(int(days_to_closing), 0), 1)
    return round(min((days_since_effective / total_days) * 100.0, 100.0), 1)


def _task_progress_pct(transaction_id):
    rows = execute_query(
        """
        SELECT
            COUNT(*) AS total_count,
            COALESCE(
                SUM(CASE WHEN completed = TRUE OR COALESCE(status, 'pending') = 'completed' THEN 1 ELSE 0 END),
                0
            ) AS completed_count
        FROM tasks
        WHERE transaction_id = %s
        """,
        (transaction_id,),
        fetch=True,
    ) or []
    if not rows:
        return 0.0
    total = int(rows[0].get("total_count") or 0)
    completed = int(rows[0].get("completed_count") or 0)
    if total <= 0:
        return 0.0
    return round((completed / total) * 100.0, 1)


def _deadline_progress_pct(transaction_id):
    rows = execute_query(
        """
        SELECT
            COUNT(*) AS total_count,
            COALESCE(SUM(CASE WHEN completed = TRUE THEN 1 ELSE 0 END), 0) AS completed_count
        FROM deadlines
        WHERE transaction_id = %s
        """,
        (transaction_id,),
        fetch=True,
    ) or []
    if not rows:
        return 0.0
    total = int(rows[0].get("total_count") or 0)
    completed = int(rows[0].get("completed_count") or 0)
    if total <= 0:
        return 0.0
    return round((completed / total) * 100.0, 1)


def _document_progress_pct(transaction_id):
    rows = execute_query(
        """
        SELECT DISTINCT LOWER(COALESCE(document_type, '')) AS document_type
        FROM documents
        WHERE transaction_id = %s
        """,
        (transaction_id,),
        fetch=True,
    ) or []
    types = {(row.get("document_type") or "").strip().lower() for row in rows}
    matched = len(types & set(REQUIRED_PROGRESS_DOC_TYPES))
    if not REQUIRED_PROGRESS_DOC_TYPES:
        return 0.0
    return round((matched / len(REQUIRED_PROGRESS_DOC_TYPES)) * 100.0, 1)


def calculate_actual_progress(transaction):
    """Estimate actual progress using tasks, deadlines, and document milestones."""
    transaction_id = int(transaction["id"])
    task_pct = _task_progress_pct(transaction_id)
    deadline_pct = _deadline_progress_pct(transaction_id)
    doc_pct = _document_progress_pct(transaction_id)
    weighted = (task_pct * 0.5) + (deadline_pct * 0.25) + (doc_pct * 0.25)
    return round(weighted, 1)


def get_communications_from_party(transaction_id, party, limit=5):
    """Fetch recent communications for a transaction + party."""
    return execute_query(
        """
        SELECT id, communication_type, contact_party, contact_name, summary, outcome, created_at
        FROM communications
        WHERE transaction_id = %s
          AND LOWER(COALESCE(contact_party, '')) = %s
        ORDER BY created_at DESC
        LIMIT %s
        """,
        (transaction_id, (party or "").strip().lower(), int(limit)),
        fetch=True,
    ) or []


def _collect_amounts(text):
    amounts = []
    for match in re.finditer(r"\$[\s]*([0-9]{1,3}(?:,[0-9]{3})*(?:\.[0-9]{1,2})?|[0-9]+(?:\.[0-9]{1,2})?)", text or ""):
        value = match.group(1).replace(",", "")
        try:
            amounts.append(float(value))
        except ValueError:
            continue
    return amounts


def _fetch_latest_analysis_findings(transaction_id, document_type):
    rows = execute_query(
        """
        SELECT id, findings, analysis_date
        FROM document_analysis_results
        WHERE transaction_id = %s
          AND document_type = %s
        ORDER BY analysis_date DESC, id DESC
        LIMIT 1
        """,
        (transaction_id, (document_type or "").strip().lower()),
        fetch=True,
    ) or []
    if not rows:
        return {}
    return parse_json_field(rows[0].get("findings"), {})


def get_recent_comparable_sales(transaction):
    """
    Derive comparable sales prices from latest appraisal analysis findings.
    """
    transaction_id = int(transaction["id"])
    findings = _fetch_latest_analysis_findings(transaction_id, "appraisal")
    if not findings:
        findings = _fetch_latest_analysis_findings(transaction_id, "appraisal_report")

    comparable_sales = findings.get("comparable_sales") or []
    comps = []
    for item in comparable_sales:
        if isinstance(item, dict):
            text = item.get("text") or ""
        else:
            text = str(item or "")
        for price in _collect_amounts(text):
            if price > 0:
                comps.append({"price": float(price), "source": "appraisal_analysis"})

    # Fallback: inspect free-form comparable section if present.
    if not comps:
        extra = findings.get("comps_text") or findings.get("summary") or ""
        for price in _collect_amounts(extra):
            if price > 0:
                comps.append({"price": float(price), "source": "appraisal_summary"})
    return comps[:10]


def get_document_by_type(transaction_id, document_type):
    """Return latest document row by one or many type aliases."""
    if isinstance(document_type, (list, tuple, set)):
        doc_types = [str(item).strip().lower() for item in document_type if str(item).strip()]
    else:
        aliases = {
            "inspection": ["inspection", "inspection_report"],
            "hoa_documents": ["hoa_documents", "hoa_docs", "hoa"],
            "survey": ["survey", "survey_report"],
            "title_commitment": ["title_commitment"],
        }
        raw = str(document_type).strip().lower()
        doc_types = aliases.get(raw, [raw])
    if not doc_types:
        return None
    rows = execute_query(
        """
        SELECT id, document_type, filename, s3_key, uploaded_at
        FROM documents
        WHERE transaction_id = %s
          AND LOWER(COALESCE(document_type, '')) = ANY(%s)
        ORDER BY uploaded_at DESC, id DESC
        LIMIT 1
        """,
        (transaction_id, doc_types),
        fetch=True,
    ) or []
    return rows[0] if rows else None


def _inspection_risk_snapshot(transaction_id):
    """Return derived repair-count/major-defect risk values from inspection analysis."""
    findings = _fetch_latest_analysis_findings(transaction_id, "inspection")
    if not findings:
        findings = _fetch_latest_analysis_findings(transaction_id, "inspection_report")

    repair_items = findings.get("repair_items") or []
    major_defects = findings.get("major_defects") or []
    year_built = findings.get("property_year_built")
    has_recent_renovation = bool(findings.get("has_recent_renovation"))

    if isinstance(repair_items, dict):
        repair_items = list(repair_items.values())
    if isinstance(major_defects, dict):
        major_defects = list(major_defects.values())
    try:
        if year_built is not None:
            year_built = int(year_built)
    except (TypeError, ValueError):
        year_built = None

    return {
        "repair_items_count": len(repair_items) if isinstance(repair_items, list) else 0,
        "major_defects": major_defects if isinstance(major_defects, list) else [],
        "year_built": year_built,
        "has_recent_renovation": has_recent_renovation,
    }


def check_task_completed(transaction_id, description_fragment):
    """True when a matching task has been completed."""
    rows = execute_query(
        """
        SELECT id
        FROM tasks
        WHERE transaction_id = %s
          AND LOWER(COALESCE(task_description, '')) LIKE %s
          AND (completed = TRUE OR COALESCE(status, 'pending') = 'completed')
        LIMIT 1
        """,
        (transaction_id, f"%{(description_fragment or '').strip().lower()}%"),
        fetch=True,
    ) or []
    return bool(rows)


def check_loan_approval_status(transaction):
    """Determine if loan approval has been confirmed."""
    transaction_id = int(transaction["id"])
    return bool(get_document_by_type(transaction_id, ("loan_approval",))) or check_task_completed(
        transaction_id, "loan approval"
    )


def check_title_status(transaction):
    """Determine if title is clear enough for closing path."""
    transaction_id = int(transaction["id"])
    if not get_document_by_type(transaction_id, ("title_commitment",)):
        return False

    unresolved_title_tasks = execute_query(
        """
        SELECT id
        FROM tasks
        WHERE transaction_id = %s
          AND LOWER(COALESCE(task_description, '')) LIKE '%title%'
          AND completed = FALSE
          AND COALESCE(status, 'pending') <> 'completed'
        LIMIT 1
        """,
        (transaction_id,),
        fetch=True,
    ) or []
    return not unresolved_title_tasks


def calculate_transaction_health(transaction, sensitivity_level="standard"):
    """
    Calculate health score 0-100 and identify issues.
    """
    sensitivity_level = (sensitivity_level or "standard").strip().lower()
    if sensitivity_level not in SENSITIVITY_THRESHOLDS:
        sensitivity_level = "standard"

    health_score = 100
    issues = []
    today = date.today()
    transaction_id = int(transaction["id"])
    closing_date = transaction.get("closing_date")
    effective_date = transaction.get("effective_date")

    days_to_closing = (closing_date - today).days if closing_date else None
    days_since_effective = (today - effective_date).days if effective_date else 0

    expected_progress = calculate_expected_progress(days_since_effective, days_to_closing)
    actual_progress = calculate_actual_progress(transaction)
    behind_gap = expected_progress - actual_progress
    behind_threshold = 18 if sensitivity_level == "relaxed" else (12 if sensitivity_level == "aggressive" else 15)
    if behind_gap >= behind_threshold:
        penalty = 24 if behind_gap >= 25 else 18
        health_score -= penalty
        issues.append(
            {
                "type": "behind_schedule",
                "severity": "high" if penalty >= 20 else "medium",
                "details": f"Transaction {behind_gap:.0f}% behind expected progress",
                "expected": expected_progress,
                "actual": actual_progress,
            }
        )

    lender_communications = get_communications_from_party(transaction_id, "lender")
    if lender_communications:
        last_contact = lender_communications[0].get("created_at")
        days_since_lender_contact = (now_utc() - last_contact).days if isinstance(last_contact, datetime) else 0
        if days_since_lender_contact > 5 and (days_to_closing is not None and days_to_closing < 20):
            health_score -= 15
            issues.append(
                {
                    "type": "lender_unresponsive",
                    "severity": "high" if days_since_lender_contact >= 9 else "medium",
                    "details": f"No lender contact in {days_since_lender_contact} days",
                    "days_silent": days_since_lender_contact,
                }
            )

    contract_price = transaction.get("contract_price")
    try:
        contract_price = float(contract_price) if contract_price not in (None, "") else None
    except (TypeError, ValueError):
        contract_price = None
    if contract_price and contract_price > 0:
        recent_comps = get_recent_comparable_sales(transaction)
        if recent_comps:
            avg_comp_price = sum(item["price"] for item in recent_comps) / len(recent_comps)
            if avg_comp_price > 0 and contract_price > avg_comp_price * 1.05:
                health_score -= 15
                variance = contract_price - avg_comp_price
                issues.append(
                    {
                        "type": "appraisal_risk",
                        "severity": "medium",
                        "details": f"Contract price ${variance:,.0f} above recent comps",
                        "variance": round(variance, 2),
                        "variance_percent": round((variance / avg_comp_price) * 100.0, 1),
                    }
                )

    inspection_snapshot = _inspection_risk_snapshot(transaction_id)
    if inspection_snapshot["repair_items_count"] > 20:
        health_score -= 10
        issues.append(
            {
                "type": "excessive_repairs",
                "severity": "medium",
                "details": f"{inspection_snapshot['repair_items_count']} repair items found",
                "repair_count": inspection_snapshot["repair_items_count"],
                "major_items": inspection_snapshot.get("major_defects", [])[:5],
            }
        )

    year_built = inspection_snapshot.get("year_built")
    if year_built and year_built < 1980 and not inspection_snapshot.get("has_recent_renovation"):
        health_score -= 10
        issues.append(
            {
                "type": "inspection_major_issue_risk",
                "severity": "medium",
                "details": f"Older home profile (built {year_built}) suggests elevated inspection risk",
                "year_built": year_built,
            }
        )

    if days_to_closing is not None and days_to_closing <= 5:
        loan_approved = check_loan_approval_status(transaction)
        title_clear = check_title_status(transaction)
        final_walkthrough = check_task_completed(transaction_id, "final walk")

        if not loan_approved:
            health_score -= 30
            issues.append(
                {
                    "type": "closing_at_risk_loan",
                    "severity": "critical",
                    "details": f"Loan not approved with {days_to_closing} days to closing",
                    "days_to_closing": days_to_closing,
                }
            )

        if not title_clear:
            health_score -= 25
            issues.append(
                {
                    "type": "closing_at_risk_title",
                    "severity": "critical",
                    "details": "Title issues unresolved",
                    "days_to_closing": days_to_closing,
                }
            )
        if not final_walkthrough:
            health_score -= 5
            issues.append(
                {
                    "type": "closing_prep_gap",
                    "severity": "medium",
                    "details": "Final walk-through not confirmed",
                    "days_to_closing": days_to_closing,
                }
            )

    upfront_paid = bool(transaction.get("payment_upfront_paid"))
    closing_paid = bool(transaction.get("payment_closing_paid"))
    if not upfront_paid and days_since_effective > 2:
        health_score -= 10
        issues.append(
            {
                "type": "payment_overdue",
                "severity": "low",
                "details": "Upfront payment not received",
                "payment_type": "upfront",
            }
        )
    if not closing_paid and (days_to_closing is not None and days_to_closing < 3):
        health_score -= 15
        issues.append(
            {
                "type": "payment_overdue",
                "severity": "high",
                "details": "Closing payment not received",
                "payment_type": "closing",
            }
        )

    if days_to_closing is not None and days_to_closing < 7:
        required_docs = ["title_commitment", "hoa_documents", "survey"]
        for doc_type in required_docs:
            if not get_document_by_type(transaction_id, doc_type):
                health_score -= 10
                issues.append(
                    {
                        "type": "missing_document",
                        "severity": "high",
                        "details": f"{doc_type.replace('_', ' ').title()} not received",
                        "document_type": doc_type,
                        "days_to_closing": days_to_closing,
                    }
                )

    return max(0, int(round(health_score))), issues


def _fallback_suggestions(issues, transaction):
    """Return deterministic suggestions when AI is unavailable."""
    tx_id = transaction.get("id")
    days_to_closing = ""
    if transaction.get("closing_date"):
        days_to_closing = f"{(transaction['closing_date'] - date.today()).days} days to close"

    suggestion_pool = []
    issue_types = {(item.get("type") or "").strip().lower() for item in issues}
    if "behind_schedule" in issue_types:
        suggestion_pool.append(
            {
                "action": f"Call lender today for transaction #{tx_id} and confirm appraisal + underwriting status.",
                "why": "The file is behind expected timeline progress and lender momentum usually unblocks critical steps.",
                "priority": "high",
            }
        )
    if "appraisal_risk" in issue_types:
        suggestion_pool.append(
            {
                "action": "Send draft appraisal-gap addendum to agent for review.",
                "why": "Comp variance indicates higher low-appraisal probability; drafting now reduces renegotiation delay.",
                "priority": "high",
            }
        )
    if {"closing_at_risk_loan", "closing_at_risk_title"} & issue_types:
        suggestion_pool.append(
            {
                "action": f"Schedule conference call with lender, agent, and buyer today ({days_to_closing}).",
                "why": "A live alignment call is the fastest path to remove closing blockers before deadline.",
                "priority": "high",
            }
        )
    if "lender_unresponsive" in issue_types:
        suggestion_pool.append(
            {
                "action": "Email lender manager with agent CC and request status response within 24 hours.",
                "why": "Escalation creates accountability and gives the agent documented update timing.",
                "priority": "medium",
            }
        )
    if "excessive_repairs" in issue_types:
        suggestion_pool.append(
            {
                "action": "Help buyer prioritize top 5 safety/major repair requests before addendum drafting.",
                "why": "Focused request sets usually get better seller response than a long repair list.",
                "priority": "medium",
            }
        )
    if not suggestion_pool:
        suggestion_pool.append(
            {
                "action": f"Review transaction #{tx_id} timeline and call agent for same-day status alignment.",
                "why": "Direct coordination quickly clarifies blockers and protects milestone deadlines.",
                "priority": "medium",
            }
        )
    return suggestion_pool[:3]


def parse_suggestions(suggestions_text):
    """Parse Claude response into structured action/why/priority rows."""
    if not suggestions_text:
        return []

    structured = []
    pattern = re.compile(
        r"\*\*Action\*\*:\s*(.+?)\s*\n\s*\*\*Why\*\*:\s*(.+?)\s*\n\s*\*\*Priority\*\*:\s*(high|medium|low)",
        re.IGNORECASE | re.DOTALL,
    )
    for match in pattern.finditer(suggestions_text):
        action = re.sub(r"\s+", " ", (match.group(1) or "").strip())
        why = re.sub(r"\s+", " ", (match.group(2) or "").strip())
        priority = (match.group(3) or "medium").strip().lower()
        if action and why:
            structured.append({"action": action, "why": why, "priority": priority})

    if structured:
        return structured[:3]

    numbered_pattern = re.compile(r"^\s*\d+[\).\s-]+(.+)$", re.MULTILINE)
    lines = [re.sub(r"\s+", " ", line.strip()) for line in numbered_pattern.findall(suggestions_text) if line.strip()]
    for line in lines[:3]:
        structured.append({"action": line, "why": "Recommended by AI risk analysis.", "priority": "medium"})
    return structured


def generate_suggestions(issues, transaction, ai_enabled=True):
    """
    Use Claude AI to generate specific, actionable suggestions.
    Falls back to deterministic guidance if API is unavailable.
    """
    if not issues:
        return []

    if not ai_enabled:
        return _fallback_suggestions(issues, transaction)

    api_key = (os.getenv("ANTHROPIC_API_KEY") or "").strip()
    if not api_key:
        return _fallback_suggestions(issues, transaction)

    days_to_closing = None
    if transaction.get("closing_date"):
        days_to_closing = (transaction["closing_date"] - date.today()).days
    days_since_effective = None
    if transaction.get("effective_date"):
        days_since_effective = (date.today() - transaction["effective_date"]).days

    context = f"""
Transaction Details:
- Property: {transaction.get("property_address") or "Property"}
- Transaction ID: {transaction.get("id")}
- Days to closing: {days_to_closing if days_to_closing is not None else "unknown"}
- Days since effective: {days_since_effective if days_since_effective is not None else "unknown"}

Issues Detected:
"""
    for issue in issues:
        context += f"\n- {issue.get('type')}: {issue.get('details')}"

    prompt = f"""{context}

You are an expert Texas real estate transaction coordinator. Based on these issues,
provide 2-3 specific, actionable suggestions that Margaret should take TODAY.

Format each suggestion exactly as:
1. **Action**: [specific action to take]
   **Why**: [brief reason]
   **Priority**: [high/medium/low]

Be specific with names, dates, and next steps. Focus on preventing problems, not just reacting.
"""

    try:
        client = Anthropic(api_key=api_key)
        response = client.messages.create(
            model="claude-sonnet-4-20250514",
            max_tokens=1200,
            messages=[{"role": "user", "content": prompt}],
        )
        content_blocks = response.content or []
        ai_text = ""
        if content_blocks and hasattr(content_blocks[0], "text"):
            ai_text = content_blocks[0].text or ""
        parsed = parse_suggestions(ai_text)
        return parsed if parsed else _fallback_suggestions(issues, transaction)
    except Exception as exc:
        print(f"AI suggestion error for transaction #{transaction.get('id')}: {exc}")
        return _fallback_suggestions(issues, transaction)


def _create_problem_run(settings):
    rows = execute_query(
        """
        INSERT INTO problem_detection_runs (
            started_at, sensitivity_level, notification_mode, ai_enabled, auto_execute_actions
        )
        VALUES (CURRENT_TIMESTAMP, %s, %s, %s, %s::jsonb)
        RETURNING id
        """,
        (
            settings.get("sensitivity_level"),
            settings.get("notification_mode"),
            bool(settings.get("ai_enabled", True)),
            json.dumps(settings.get("auto_execute_actions") or []),
        ),
        fetch=True,
    ) or []
    return rows[0]["id"] if rows else None


def _classify_bucket(health_score, sensitivity_level):
    thresholds = SENSITIVITY_THRESHOLDS.get(sensitivity_level, SENSITIVITY_THRESHOLDS["standard"])
    if health_score >= thresholds["healthy_min"]:
        return "healthy"
    if health_score >= thresholds["watch_min"]:
        return "watch"
    return "urgent"


def get_transaction_context(transaction_id):
    """Fetch transaction details used by action executors and draft sends."""
    rows = execute_query(
        """
        SELECT
            id,
            property_address,
            agent_name,
            agent_phone,
            agent_email,
            buyer_name,
            buyer_phone,
            seller_name,
            seller_phone,
            lender_name,
            lender_phone,
            lender_email,
            title_company,
            title_officer_email,
            closing_date
        FROM transactions
        WHERE id = %s
        LIMIT 1
        """,
        (transaction_id,),
        fetch=True,
    ) or []
    return rows[0] if rows else None


def get_transaction_lender(transaction_id):
    """Return lender contact details for one transaction."""
    transaction = get_transaction_context(transaction_id)
    if not transaction:
        return {}
    return {
        "name": transaction.get("lender_name") or "Lender",
        "phone": transaction.get("lender_phone") or "",
        "email": transaction.get("lender_email") or "",
    }


def initiate_call(from_phone, to_phone):
    """
    Initiate a Twilio outbound call if voice integration is configured.
    Returns call SID or None.
    """
    account_sid = (os.getenv("TWILIO_ACCOUNT_SID") or "").strip()
    auth_token = (os.getenv("TWILIO_AUTH_TOKEN") or "").strip()
    from_number = normalize_phone(from_phone or os.getenv("TWILIO_PHONE_NUMBER") or "")
    to_number = normalize_phone(to_phone)
    if not account_sid or not auth_token or not from_number or not to_number:
        return None
    try:
        client = Client(account_sid, auth_token)
        voice_url = (os.getenv("TWILIO_VOICE_URL") or "http://demo.twilio.com/docs/voice.xml").strip()
        call = client.calls.create(
            to=to_number,
            from_=from_number,
            url=voice_url,
        )
        return call.sid
    except Exception as exc:
        print(f"Twilio voice call initiation failed: {exc}")
        return None


def log_communication(transaction_id, contact_party, communication_type, summary, outcome):
    """Write a communication log row."""
    execute_query(
        """
        INSERT INTO communications (
            transaction_id, communication_type, contact_party, contact_name, summary, outcome
        )
        VALUES (%s, %s, %s, %s, %s, %s)
        """,
        (
            transaction_id,
            (communication_type or "note")[:50],
            (contact_party or "system")[:50],
            "problem_detector",
            (summary or "")[:400],
            (outcome or "")[:1800],
        ),
    )


def create_task(transaction_id, description, priority="high", due_date=None):
    """Create follow-up task row and return ID."""
    if due_date is None:
        due_date = date.today() + timedelta(days=1)
    rows = execute_query(
        """
        INSERT INTO tasks (
            transaction_id, task_description, task_category, due_date,
            priority, status, completed, display_order, notes, created_at
        )
        VALUES (%s, %s, 'coordination', %s, %s, 'pending', FALSE, 68, %s, CURRENT_TIMESTAMP)
        RETURNING id
        """,
        (
            transaction_id,
            (description or "Follow up task")[:280],
            due_date,
            (priority or "high").lower(),
            "Auto-created by problem detector suggestion flow.",
        ),
        fetch=True,
    ) or []
    return rows[0]["id"] if rows else None


def _ensure_calendar_events_table():
    execute_query(
        """
        CREATE TABLE IF NOT EXISTS calendar_events (
            id SERIAL PRIMARY KEY,
            transaction_id INT REFERENCES transactions(id) ON DELETE CASCADE,
            vendor_outreach_id INT REFERENCES vendor_outreach(id) ON DELETE SET NULL,
            event_type VARCHAR(50),
            title VARCHAR(255) NOT NULL,
            starts_at TIMESTAMP,
            ends_at TIMESTAMP,
            details TEXT,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
        """
    )


def send_suggested_draft(transaction_id, suggestion_action):
    """Send a pre-drafted action email for extension/escalation workflows."""
    transaction = get_transaction_context(transaction_id)
    if not transaction:
        return None
    target_email = (
        normalize_email(transaction.get("agent_email"))
        or normalize_email(transaction.get("lender_email"))
        or normalize_email(transaction.get("title_officer_email"))
    )
    if not target_email:
        return None

    subject = f"Maverick Draft Action - {transaction.get('property_address') or f'Transaction #{transaction_id}'}"
    closing_label = (
        transaction["closing_date"].strftime("%b %d, %Y")
        if isinstance(transaction.get("closing_date"), date)
        else "TBD"
    )
    html_body = f"""
    <p>Hi Team,</p>
    <p>Maverick generated the following draft action for transaction <strong>#{transaction_id}</strong>:</p>
    <blockquote style="border-left:3px solid #cbd5e1; padding-left:10px; color:#334155;">
        {suggestion_action}
    </blockquote>
    <p><strong>Property:</strong> {transaction.get("property_address") or "Property"}</p>
    <p><strong>Current Closing Date:</strong> {closing_label}</p>
    <p>Please review and reply if edits are needed before we send externally.</p>
    <p>Thanks,<br>Maverick TC</p>
    """
    return send_html_email(
        to_email=target_email,
        subject=subject,
        html_body=html_body,
        reply_to=normalize_email(os.getenv("MARGARET_EMAIL")) or None,
    )


def create_conference_call(transaction_id):
    """Create conference-call coordination event + notifications."""
    transaction = get_transaction_context(transaction_id)
    if not transaction:
        return {"event_id": None, "emails_sent": 0}

    _ensure_calendar_events_table()
    start_at = datetime.now() + timedelta(hours=2)
    end_at = start_at + timedelta(minutes=30)
    rows = execute_query(
        """
        INSERT INTO calendar_events (
            transaction_id, vendor_outreach_id, event_type, title, starts_at, ends_at, details, created_at
        )
        VALUES (%s, NULL, 'conference_call', %s, %s, %s, %s, CURRENT_TIMESTAMP)
        RETURNING id
        """,
        (
            transaction_id,
            f"Conference call - {transaction.get('property_address') or f'Transaction #{transaction_id}'}",
            start_at,
            end_at,
            "Auto-created from accepted problem-detector suggestion.",
        ),
        fetch=True,
    ) or []
    event_id = rows[0]["id"] if rows else None

    recipients = [
        normalize_email(transaction.get("agent_email")),
        normalize_email(transaction.get("lender_email")),
        normalize_email(transaction.get("title_officer_email")),
    ]
    recipients = [email for email in recipients if email]
    sent_count = 0
    for to_email in recipients:
        message_id = send_html_email(
            to_email=to_email,
            subject=f"Conference Call Requested - Transaction #{transaction_id}",
            html_body=(
                "<p>Maverick requested a conference call for this transaction.</p>"
                f"<p><strong>Property:</strong> {transaction.get('property_address') or 'Property'}</p>"
                f"<p><strong>Proposed start:</strong> {start_at.strftime('%b %d, %Y %I:%M %p')}</p>"
            ),
            reply_to=normalize_email(os.getenv("MARGARET_EMAIL")) or None,
        )
        if message_id:
            sent_count += 1

    return {"event_id": event_id, "emails_sent": sent_count}


def execute_suggestion_action(transaction_id, suggestion_action, actor="margaret"):
    """
    Execute suggested action automatically when accepted by Margaret.
    """
    action_text = (suggestion_action or "").strip()
    if not action_text:
        return {"success": False, "error": "missing_action"}

    normalized = action_text.lower()
    action_result = {"success": True, "action": action_text, "steps": []}
    lender = get_transaction_lender(transaction_id)

    if "call lender" in normalized:
        call_sid = initiate_call(os.getenv("MARGARET_PHONE"), lender.get("phone"))
        if call_sid:
            action_result["steps"].append({"type": "call", "status": "initiated", "sid": call_sid})
            log_communication(
                transaction_id,
                "lender",
                "phone_call",
                "Automated call initiated from suggestion acceptance",
                f"action={action_text} sid={call_sid}",
            )
        else:
            task_id = create_task(
                transaction_id,
                f"Call lender now: {lender.get('name') or 'Lender'} ({lender.get('phone') or 'phone missing'})",
                priority="high",
                due_date=date.today(),
            )
            action_result["steps"].append({"type": "call", "status": "queued_manual", "task_id": task_id})

    elif "send draft" in normalized or "draft addendum" in normalized or "extension addendum" in normalized:
        message_id = send_suggested_draft(transaction_id, action_text)
        action_result["steps"].append(
            {"type": "draft_send", "status": ("sent" if message_id else "failed"), "message_id": message_id}
        )
        log_communication(
            transaction_id,
            "agent",
            "email",
            "Suggested draft send attempted",
            f"action={action_text} message_id={message_id or 'failed'}",
        )

    elif "schedule conference call" in normalized or "conference call" in normalized:
        result = create_conference_call(transaction_id)
        action_result["steps"].append(
            {
                "type": "conference_call",
                "status": "scheduled" if result.get("event_id") else "queued",
                "event_id": result.get("event_id"),
                "emails_sent": result.get("emails_sent", 0),
            }
        )
        log_communication(
            transaction_id,
            "system",
            "note",
            "Conference call action executed",
            f"action={action_text} event_id={result.get('event_id') or 'n/a'}",
        )

    else:
        action_result["steps"].append({"type": "generic", "status": "logged"})
        log_communication(
            transaction_id,
            "system",
            "note",
            "Suggestion action accepted",
            f"action={action_text}",
        )

    followup_task_id = create_task(
        transaction_id=transaction_id,
        description=f"Follow up on: {action_text}",
        priority="high",
        due_date=date.today() + timedelta(days=1),
    )
    action_result["followup_task_id"] = followup_task_id
    action_result["accepted_by"] = (actor or "margaret")[:100]
    return action_result


def _suggestion_matches_auto_action(action_text, auto_action_key):
    text = (action_text or "").lower()
    if auto_action_key == "call_lender":
        return "call lender" in text
    if auto_action_key == "send_draft_extension":
        return "send draft" in text or "draft addendum" in text or "extension addendum" in text
    if auto_action_key == "schedule_conference_call":
        return "conference call" in text
    return False


def _maybe_auto_execute_suggestions(transaction_id, suggestions, settings):
    auto_actions = settings.get("auto_execute_actions") or []
    if not auto_actions:
        return []
    executed = []
    for suggestion in suggestions:
        action_text = suggestion.get("action") if isinstance(suggestion, dict) else ""
        if not action_text:
            continue
        matched = [key for key in auto_actions if _suggestion_matches_auto_action(action_text, key)]
        if not matched:
            continue
        result = execute_suggestion_action(
            transaction_id=transaction_id,
            suggestion_action=action_text,
            actor="auto-problem-detector",
        )
        result["matched_auto_actions"] = matched
        executed.append(result)
    return executed


def _persist_results(run_id, problems):
    if not run_id:
        return
    for bucket in ("healthy", "watch", "urgent"):
        for item in problems[bucket]:
            transaction = item.get("transaction") or {}
            transaction_id = transaction.get("id")
            if not transaction_id:
                continue
            execute_query(
                """
                INSERT INTO problem_detection_results (
                    run_id, transaction_id, health_score, bucket, issues, suggestions, auto_actions, status
                )
                VALUES (%s, %s, %s, %s, %s::jsonb, %s::jsonb, %s::jsonb, 'open')
                ON CONFLICT (run_id, transaction_id)
                DO UPDATE SET
                    health_score = EXCLUDED.health_score,
                    bucket = EXCLUDED.bucket,
                    issues = EXCLUDED.issues,
                    suggestions = EXCLUDED.suggestions,
                    auto_actions = EXCLUDED.auto_actions,
                    status = 'open'
                """,
                (
                    run_id,
                    transaction_id,
                    int(item.get("health_score") or 0),
                    bucket,
                    json.dumps(item.get("issues") or [], default=str),
                    json.dumps(item.get("suggestions") or [], default=str),
                    json.dumps(item.get("auto_actions") or [], default=str),
                ),
            )


def _finalize_run(run_id, problems, sms_sid=None, email_message_id=None, notes=""):
    if not run_id:
        return
    execute_query(
        """
        UPDATE problem_detection_runs
        SET completed_at = CURRENT_TIMESTAMP,
            healthy_count = %s,
            watch_count = %s,
            urgent_count = %s,
            sms_sid = %s,
            email_message_id = %s,
            notes = %s
        WHERE id = %s
        """,
        (
            len(problems.get("healthy") or []),
            len(problems.get("watch") or []),
            len(problems.get("urgent") or []),
            sms_sid,
            email_message_id,
            (notes or "")[:1200] or None,
            run_id,
        ),
    )


def analyze_transaction_health(send_notifications=True):
    """
    Analyze all active transactions for potential problems.
    Run every 6 hours.
    """
    ensure_problem_detection_tables()
    settings = fetch_problem_detection_settings()
    sensitivity_level = settings.get("sensitivity_level", "standard")
    ai_enabled = bool(settings.get("ai_enabled", True))

    whitelist_rows = fetch_problem_detection_whitelist(active_only=True)
    whitelisted_txn_ids = {int(row["transaction_id"]) for row in whitelist_rows if row.get("transaction_id")}

    transactions = get_active_transactions()
    run_id = _create_problem_run(settings)
    problems = {"healthy": [], "watch": [], "urgent": []}

    for transaction in transactions:
        transaction_id = int(transaction["id"])
        if transaction_id in whitelisted_txn_ids:
            problems["healthy"].append(
                {
                    "transaction": transaction,
                    "health_score": 100,
                    "issues": [],
                    "suggestions": [],
                    "auto_actions": [],
                    "note": "whitelisted",
                }
            )
            continue

        health_score, issues = calculate_transaction_health(transaction, sensitivity_level=sensitivity_level)
        bucket = _classify_bucket(health_score, sensitivity_level)

        item = {
            "transaction": transaction,
            "health_score": health_score,
            "issues": issues,
            "suggestions": [],
            "auto_actions": [],
        }
        if bucket != "healthy":
            suggestions = generate_suggestions(issues, transaction, ai_enabled=ai_enabled)
            item["suggestions"] = suggestions
            item["auto_actions"] = _maybe_auto_execute_suggestions(transaction_id, suggestions, settings)
        problems[bucket].append(item)

    _persist_results(run_id, problems)

    sms_sid = None
    email_message_id = None
    if send_notifications:
        summary_outcome = send_health_summary(problems, settings=settings)
        sms_sid = summary_outcome.get("sms_sid")
        email_message_id = summary_outcome.get("email_message_id")
    _finalize_run(run_id, problems, sms_sid=sms_sid, email_message_id=email_message_id)

    return {
        "run_id": run_id,
        "settings": settings,
        "healthy_count": len(problems["healthy"]),
        "watch_count": len(problems["watch"]),
        "urgent_count": len(problems["urgent"]),
        "problems": problems,
    }


def send_health_summary(problems, settings=None):
    """
    Send daily health summary to Margaret.
    """
    settings = settings or fetch_problem_detection_settings()
    mode = settings.get("notification_mode", "urgent_only")
    if mode not in {"urgent_only", "all", "none"}:
        mode = "urgent_only"

    healthy_count = len(problems.get("healthy") or [])
    watch_count = len(problems.get("watch") or [])
    urgent_count = len(problems.get("urgent") or [])

    sms_sid = None
    if mode != "none" and (mode == "all" or urgent_count > 0):
        sms_summary = (
            "Daily Transaction Health\n\n"
            f"Healthy: {healthy_count}\n"
            f"Watch: {watch_count}\n"
            f"Urgent: {urgent_count}\n"
        )
        for item in (problems.get("urgent") or [])[:3]:
            tx = item.get("transaction") or {}
            first_issue = (item.get("issues") or [{}])[0]
            sms_summary += (
                f"\nURGENT: {tx.get('property_address') or f'Transaction #{tx.get('id')}' }\n"
                f"  {first_issue.get('details') or 'Immediate review needed.'}\n"
            )
        if watch_count > 0:
            sms_summary += f"\n{watch_count} watch transactions need attention."
        app_base = (os.getenv("APP_BASE_URL") or "").strip().rstrip("/")
        if app_base:
            sms_summary += f"\n\nView full report: {app_base}/tc/health-report"

        margaret_phone = normalize_phone(os.getenv("MARGARET_PHONE"))
        if margaret_phone:
            sms_sid = send_sms(margaret_phone, sms_summary[:1500])

    email_message_id = None
    margaret_email = normalize_email(os.getenv("MARGARET_EMAIL"))
    if margaret_email and mode != "none":
        email_message_id = send_email(
            to=margaret_email,
            template="emails/health_summary.html",
            data={
                "subject": f"Maverick Health Summary - {datetime.now().strftime('%B %d, %Y')}",
                "healthy_count": healthy_count,
                "watch_count": watch_count,
                "urgent_count": urgent_count,
                "watch_items": problems.get("watch") or [],
                "urgent_items": problems.get("urgent") or [],
                "date": datetime.now().strftime("%B %d, %Y"),
                "app_base_url": (os.getenv("APP_BASE_URL") or "").strip().rstrip("/"),
            },
            reply_to=margaret_email,
        )
    return {"sms_sid": sms_sid, "email_message_id": email_message_id}


def fetch_latest_health_report(include_handled=False):
    """Return latest persisted health report payload for UI rendering."""
    ensure_problem_detection_tables()
    runs = execute_query(
        """
        SELECT id, started_at, completed_at, healthy_count, watch_count, urgent_count,
               sensitivity_level, notification_mode, ai_enabled, auto_execute_actions
        FROM problem_detection_runs
        ORDER BY COALESCE(completed_at, started_at) DESC, id DESC
        LIMIT 1
        """,
        fetch=True,
    ) or []
    if not runs:
        return {
            "generated_at": None,
            "generated_at_label": "",
            "healthy_count": 0,
            "watch_count": 0,
            "urgent_count": 0,
            "healthy_items": [],
            "watch_items": [],
            "urgent_items": [],
            "run_id": None,
            "settings": fetch_problem_detection_settings(),
        }

    run = runs[0]
    where_handled = "" if include_handled else "AND COALESCE(r.status, 'open') = 'open'"
    rows = execute_query(
        f"""
        SELECT
            r.id,
            r.transaction_id,
            r.health_score,
            r.bucket,
            r.issues,
            r.suggestions,
            r.auto_actions,
            r.status,
            r.handled_by,
            r.handled_at,
            t.property_address,
            t.agent_name,
            t.agent_phone,
            t.lender_name,
            t.lender_email,
            t.closing_date
        FROM problem_detection_results r
        JOIN transactions t ON t.id = r.transaction_id
        WHERE r.run_id = %s
        {where_handled}
        ORDER BY
            CASE r.bucket WHEN 'urgent' THEN 0 WHEN 'watch' THEN 1 ELSE 2 END,
            r.health_score ASC,
            r.id DESC
        """,
        (run["id"],),
        fetch=True,
    ) or []

    grouped = {"healthy": [], "watch": [], "urgent": []}
    for row in rows:
        issues = parse_json_field(row.get("issues"), [])
        suggestions = parse_json_field(row.get("suggestions"), [])
        auto_actions = parse_json_field(row.get("auto_actions"), [])
        transaction = {
            "id": row.get("transaction_id"),
            "property_address": row.get("property_address"),
            "agent_name": row.get("agent_name"),
            "agent_phone": row.get("agent_phone"),
            "lender_name": row.get("lender_name"),
            "lender_email": row.get("lender_email"),
            "closing_date": row.get("closing_date"),
        }
        bucket = (row.get("bucket") or "watch").strip().lower()
        if bucket not in grouped:
            bucket = "watch"
        grouped[bucket].append(
            {
                "id": row.get("id"),
                "transaction": transaction,
                "health_score": int(row.get("health_score") or 0),
                "issues": issues if isinstance(issues, list) else [],
                "suggestions": suggestions if isinstance(suggestions, list) else [],
                "auto_actions": auto_actions if isinstance(auto_actions, list) else [],
                "status": row.get("status") or "open",
            }
        )

    generated_at = run.get("completed_at") or run.get("started_at")
    return {
        "run_id": run.get("id"),
        "generated_at": generated_at,
        "generated_at_label": generated_at.strftime("%b %d, %Y %I:%M %p") if generated_at else "",
        "healthy_count": len(grouped["healthy"]),
        "watch_count": len(grouped["watch"]),
        "urgent_count": len(grouped["urgent"]),
        "healthy_items": grouped["healthy"],
        "watch_items": grouped["watch"],
        "urgent_items": grouped["urgent"],
        "settings": {
            "sensitivity_level": (run.get("sensitivity_level") or "standard"),
            "notification_mode": (run.get("notification_mode") or "urgent_only"),
            "ai_enabled": bool(run.get("ai_enabled", True)),
            "auto_execute_actions": parse_json_field(run.get("auto_execute_actions"), []),
        },
    }


def mark_problem_result_handled(transaction_id, run_id=None, handled_by="margaret", notes=""):
    """Mark latest open result for transaction as handled for current report cycle."""
    ensure_problem_detection_tables()
    params = [transaction_id]
    run_filter = ""
    if run_id:
        run_filter = "AND run_id = %s"
        params.append(run_id)

    rows = execute_query(
        f"""
        SELECT id
        FROM problem_detection_results
        WHERE transaction_id = %s
          {run_filter}
          AND COALESCE(status, 'open') = 'open'
        ORDER BY id DESC
        """,
        tuple(params),
        fetch=True,
    ) or []
    if not rows:
        return False
    ids = [row["id"] for row in rows]
    execute_query(
        """
        UPDATE problem_detection_results
        SET status = 'handled',
            handled_by = %s,
            handled_at = CURRENT_TIMESTAMP
        WHERE id = ANY(%s)
        """,
        ((handled_by or "margaret")[:100], ids),
    )
    log_communication(
        transaction_id,
        "system",
        "note",
        "Problem detector issue marked handled",
        f"result_ids={','.join(str(item) for item in ids)} notes={notes[:200]}",
    )
    return True


def run_problem_detection_if_stale(max_age_minutes=360, send_notifications=False):
    """Run analysis only if last completed run is older than threshold."""
    ensure_problem_detection_tables()
    rows = execute_query(
        """
        SELECT completed_at
        FROM problem_detection_runs
        WHERE completed_at IS NOT NULL
        ORDER BY completed_at DESC
        LIMIT 1
        """,
        fetch=True,
    ) or []
    if not rows:
        return analyze_transaction_health(send_notifications=send_notifications)
    completed_at = rows[0].get("completed_at")
    if not isinstance(completed_at, datetime):
        return analyze_transaction_health(send_notifications=send_notifications)
    age = now_utc() - completed_at
    if age.total_seconds() >= int(max_age_minutes) * 60:
        return analyze_transaction_health(send_notifications=send_notifications)
    return None


def main():
    """Cron entrypoint."""
    print(f"[{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}] Starting problem detector run")
    result = analyze_transaction_health(send_notifications=True)
    print(
        f"[{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}] Problem detector complete: "
        f"healthy={result['healthy_count']} watch={result['watch_count']} urgent={result['urgent_count']}"
    )


if __name__ == "__main__":
    main()
