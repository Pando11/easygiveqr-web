from __future__ import annotations

import json
import os
import re
from datetime import date, datetime, timedelta
from typing import Any

from utils.db import execute_query


DEFAULT_TIMELINE_DAYS = 45
MIN_EXPECTED_PROGRESS_PCT = 15.0
DOC_PROGRESS_TYPES = {
    "contract",
    "earnest_receipt",
    "option_receipt",
    "seller_disclosure",
    "inspection_report",
    "appraisal",
    "title_commitment",
    "loan_approval",
    "insurance_binder",
    "settlement_statement",
}

HEADS_UP_PATTERN_META = {
    "behind_schedule": {
        "label": "Transaction running behind schedule",
        "description": "Expected timeline progress is materially ahead of actual progress.",
    },
    "appraisal_gap_risk": {
        "label": "Appraisal likely to come in low",
        "description": "Contract price is materially above comparable sales evidence.",
    },
    "older_home_inspection_risk": {
        "label": "Inspection likely to reveal major issues",
        "description": "Older home profile suggests elevated inspection risk.",
    },
    "lender_unresponsive": {
        "label": "Lender unresponsive",
        "description": "No lender communication activity in 5+ days.",
    },
    "repair_overload": {
        "label": "Too many repair requests likely",
        "description": "Inspection findings indicate unusually high item count.",
    },
    "closing_at_risk": {
        "label": "Closing at risk",
        "description": "Closing within 5 days without loan approval confirmation.",
    },
}


def parse_json_field(raw_value: Any, default_value: Any):
    """Safe JSON parsing helper."""
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


def _extract_amounts(text: str) -> list[float]:
    amounts = []
    for match in re.finditer(
        r"\$[\s]*([0-9]{1,3}(?:,[0-9]{3})*(?:\.[0-9]{1,2})?|[0-9]+(?:\.[0-9]{1,2})?)",
        text or "",
    ):
        numeric = match.group(1).replace(",", "")
        try:
            amounts.append(float(numeric))
        except ValueError:
            continue
    return amounts


def ensure_heads_up_tables():
    """Ensure Heads Up report storage tables exist."""
    execute_query(
        """
        CREATE TABLE IF NOT EXISTS heads_up_signals (
            id SERIAL PRIMARY KEY,
            transaction_id INT REFERENCES transactions(id) ON DELETE CASCADE,
            pattern_key VARCHAR(80) NOT NULL,
            severity VARCHAR(20) NOT NULL,
            headline TEXT NOT NULL,
            suggestion TEXT NOT NULL,
            details JSONB,
            signal_date DATE NOT NULL,
            status VARCHAR(20) DEFAULT 'open',
            modified_suggestion TEXT,
            accepted_by VARCHAR(100),
            accepted_at TIMESTAMP,
            dismissed_by VARCHAR(100),
            dismissed_at TIMESTAMP,
            dismissal_notes TEXT,
            auto_action_result TEXT,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
        """
    )
    execute_query(
        """
        CREATE UNIQUE INDEX IF NOT EXISTS idx_heads_up_signals_unique_daily
        ON heads_up_signals(transaction_id, pattern_key, signal_date)
        """
    )
    execute_query(
        """
        CREATE INDEX IF NOT EXISTS idx_heads_up_signals_date_status
        ON heads_up_signals(signal_date, status, severity)
        """
    )

    execute_query(
        """
        CREATE TABLE IF NOT EXISTS heads_up_preferences (
            id SERIAL PRIMARY KEY,
            pattern_key VARCHAR(80) UNIQUE NOT NULL,
            always_alert BOOLEAN DEFAULT TRUE,
            auto_handle BOOLEAN DEFAULT FALSE,
            updated_by VARCHAR(100),
            updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
        """
    )
    for pattern_key in HEADS_UP_PATTERN_META:
        execute_query(
            """
            INSERT INTO heads_up_preferences (pattern_key, always_alert, auto_handle, updated_by, updated_at)
            VALUES (%s, TRUE, FALSE, 'system', CURRENT_TIMESTAMP)
            ON CONFLICT (pattern_key) DO NOTHING
            """,
            (pattern_key,),
        )


def fetch_pattern_preferences() -> dict[str, dict[str, Any]]:
    """Return preferences map keyed by pattern."""
    ensure_heads_up_tables()
    rows = execute_query(
        """
        SELECT pattern_key, always_alert, auto_handle, updated_by, updated_at
        FROM heads_up_preferences
        ORDER BY pattern_key ASC
        """,
        fetch=True,
    ) or []
    result = {}
    for pattern_key in HEADS_UP_PATTERN_META:
        result[pattern_key] = {
            "always_alert": True,
            "auto_handle": False,
            "updated_by": "",
            "updated_at": None,
        }
    for row in rows:
        key = row.get("pattern_key")
        if key in result:
            result[key] = {
                "always_alert": bool(row.get("always_alert")),
                "auto_handle": bool(row.get("auto_handle")),
                "updated_by": row.get("updated_by") or "",
                "updated_at": row.get("updated_at"),
            }
    return result


def save_pattern_preference(pattern_key: str, always_alert: bool, auto_handle: bool, updated_by: str = "margaret"):
    """Upsert one Heads Up preference row."""
    ensure_heads_up_tables()
    if pattern_key not in HEADS_UP_PATTERN_META:
        return False
    execute_query(
        """
        INSERT INTO heads_up_preferences (pattern_key, always_alert, auto_handle, updated_by, updated_at)
        VALUES (%s, %s, %s, %s, CURRENT_TIMESTAMP)
        ON CONFLICT (pattern_key)
        DO UPDATE SET
            always_alert = EXCLUDED.always_alert,
            auto_handle = EXCLUDED.auto_handle,
            updated_by = EXCLUDED.updated_by,
            updated_at = CURRENT_TIMESTAMP
        """,
        (pattern_key, bool(always_alert), bool(auto_handle), (updated_by or "margaret")[:100]),
    )
    return True


def fetch_active_transactions():
    """Return active transactions for analysis."""
    return execute_query(
        """
        SELECT id, property_address, created_at, effective_date, closing_date, contract_price
        FROM transactions
        WHERE status = 'ACTIVE'
        ORDER BY created_at ASC
        """,
        fetch=True,
    ) or []


def fetch_task_stats(transaction_id: int):
    """Task completion stats for one transaction."""
    rows = execute_query(
        """
        SELECT COUNT(*) AS total_count,
               COALESCE(SUM(
                   CASE
                       WHEN completed = TRUE OR COALESCE(status, 'pending') = 'completed' THEN 1
                       ELSE 0
                   END
               ), 0) AS completed_count
        FROM tasks
        WHERE transaction_id = %s
        """,
        (transaction_id,),
        fetch=True,
    ) or []
    if not rows:
        return {"total": 0, "completed": 0, "pct": 0.0}
    total = int(rows[0].get("total_count") or 0)
    completed = int(rows[0].get("completed_count") or 0)
    pct = round((completed / total * 100.0), 1) if total > 0 else 0.0
    return {"total": total, "completed": completed, "pct": pct}


def fetch_document_types(transaction_id: int):
    """Distinct document types for one transaction."""
    rows = execute_query(
        """
        SELECT DISTINCT document_type
        FROM documents
        WHERE transaction_id = %s
        """,
        (transaction_id,),
        fetch=True,
    ) or []
    return {(row.get("document_type") or "").strip().lower() for row in rows if row.get("document_type")}


def fetch_latest_analysis(transaction_id: int, document_type: str):
    """Return latest document-analysis row for a given type."""
    rows = execute_query(
        """
        SELECT id, analysis_date, findings
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
        return None
    row = rows[0]
    row["findings"] = parse_json_field(row.get("findings"), {})
    return row


def fetch_last_lender_contact(transaction_id: int):
    """Last communication timestamp involving lender party."""
    rows = execute_query(
        """
        SELECT MAX(created_at) AS last_contact
        FROM communications
        WHERE transaction_id = %s
          AND LOWER(COALESCE(contact_party, '')) IN ('lender', 'loan_officer')
        """,
        (transaction_id,),
        fetch=True,
    ) or []
    if not rows:
        return None
    return rows[0].get("last_contact")


def loan_approval_confirmed(transaction_id: int, doc_types: set[str]):
    """Check if loan approval evidence exists."""
    if "loan_approval" in doc_types:
        return True
    rows = execute_query(
        """
        SELECT id
        FROM tasks
        WHERE transaction_id = %s
          AND LOWER(COALESCE(task_description, '')) LIKE 'get loan approval letter%%'
          AND (completed = TRUE OR COALESCE(status, 'pending') = 'completed')
        LIMIT 1
        """,
        (transaction_id,),
        fetch=True,
    ) or []
    return bool(rows)


def _headline(pattern_text: str, transaction: dict):
    return f"{transaction.get('property_address')}: {pattern_text}"


def _build_signal(
    transaction: dict,
    pattern_key: str,
    severity: str,
    headline_text: str,
    suggestion_text: str,
    details: dict[str, Any] | None = None,
):
    return {
        "transaction_id": transaction["id"],
        "property_address": transaction.get("property_address") or "Property",
        "pattern_key": pattern_key,
        "severity": severity,
        "headline": headline_text,
        "suggestion": suggestion_text,
        "details": details or {},
    }


def _evaluate_behind_schedule(transaction: dict, today: date, task_stats: dict, doc_types: set[str]):
    effective = transaction.get("effective_date")
    if not effective:
        return None
    days_since = max((today - effective).days, 0)
    closing = transaction.get("closing_date")
    if closing and closing > effective:
        timeline_days = (closing - effective).days
    else:
        timeline_days = DEFAULT_TIMELINE_DAYS
    timeline_days = max(timeline_days, 1)

    expected_progress = round(min(100.0, (days_since / timeline_days) * 100.0), 1)
    if expected_progress < MIN_EXPECTED_PROGRESS_PCT:
        return None

    doc_received = len(doc_types & DOC_PROGRESS_TYPES)
    doc_pct = round((doc_received / len(DOC_PROGRESS_TYPES)) * 100.0, 1)
    actual_progress = round((task_stats["pct"] + doc_pct) / 2.0, 1)
    if actual_progress >= expected_progress * 0.9:
        return None

    behind_days = int(round(((expected_progress - actual_progress) / 100.0) * timeline_days))
    if behind_days < 2:
        return None
    severity = "urgent" if behind_days >= 5 else "watch"
    suggestion = (
        f"This transaction is {behind_days} days behind average. "
        f"Suggest: Call lender {'today' if severity == 'urgent' else 'tomorrow'} to expedite appraisal."
    )
    return _build_signal(
        transaction,
        "behind_schedule",
        severity,
        _headline(f"{behind_days} days behind average timeline", transaction),
        suggestion,
        {
            "days_behind": behind_days,
            "expected_progress_pct": expected_progress,
            "actual_progress_pct": actual_progress,
            "task_progress_pct": task_stats["pct"],
            "document_progress_pct": doc_pct,
        },
    )


def _evaluate_appraisal_gap(transaction: dict, appraisal_analysis: dict | None):
    contract_price = transaction.get("contract_price")
    if contract_price is None:
        return None
    try:
        contract_price_value = float(contract_price)
    except (TypeError, ValueError):
        return None
    if contract_price_value <= 0:
        return None
    findings = (appraisal_analysis or {}).get("findings") or {}
    comparable_sales = findings.get("comparable_sales") or []
    comp_amounts = []
    for item in comparable_sales:
        if isinstance(item, dict):
            comp_amounts.extend(_extract_amounts(item.get("text", "")))
        elif isinstance(item, str):
            comp_amounts.extend(_extract_amounts(item))
    if len(comp_amounts) < 2:
        return None
    avg_comp = sum(comp_amounts) / len(comp_amounts)
    if contract_price_value <= avg_comp * 1.05:
        return None
    diff = contract_price_value - avg_comp
    diff_pct = (diff / avg_comp) * 100 if avg_comp > 0 else 0
    severity = "urgent" if diff_pct >= 10 else "watch"
    suggested_credit = min(10000.0, max(diff * 0.66, 5000.0))
    suggestion = (
        f"Contract price ${diff:,.0f} above recent sales. Suggest: "
        "Prepare buyer for potential appraisal gap. Draft addendum "
        f"for seller to credit ${suggested_credit:,.0f} if appraisal comes in low."
    )
    return _build_signal(
        transaction,
        "appraisal_gap_risk",
        severity,
        _headline(f"Contract price {diff_pct:.1f}% above comp average", transaction),
        suggestion,
        {
            "contract_price": contract_price_value,
            "average_comp_price": round(avg_comp, 2),
            "difference": round(diff, 2),
            "difference_percent": round(diff_pct, 1),
            "suggested_credit": round(suggested_credit, 2),
            "comp_count": len(comp_amounts),
        },
    )


def _evaluate_older_home_risk(transaction: dict, inspection_analysis: dict | None):
    findings = (inspection_analysis or {}).get("findings") or {}
    year_built = findings.get("property_year_built")
    renovated_recently = bool(findings.get("has_recent_renovation"))
    if year_built is None:
        return None
    try:
        year_built = int(year_built)
    except (TypeError, ValueError):
        return None
    if year_built >= 1980 or renovated_recently:
        return None
    suggestion = (
        "Older home - inspection may find foundation/roof issues. Suggest: "
        "Set expectations with buyer that repairs are common for homes this age. "
        "Have structural engineer on standby."
    )
    return _build_signal(
        transaction,
        "older_home_inspection_risk",
        "watch",
        _headline(f"Home built in {year_built} with no recent renovation signals", transaction),
        suggestion,
        {
            "year_built": year_built,
            "has_recent_renovation": renovated_recently,
        },
    )


def _evaluate_lender_unresponsive(transaction: dict, today: date, last_lender_contact: datetime | None):
    closing = transaction.get("closing_date")
    if last_lender_contact:
        days_silent = (today - last_lender_contact.date()).days
    else:
        reference_date = transaction.get("effective_date") or transaction.get("created_at")
        if not reference_date:
            return None
        if isinstance(reference_date, datetime):
            reference_day = reference_date.date()
        else:
            reference_day = reference_date
        days_silent = (today - reference_day).days
    if days_silent < 5:
        return None
    days_to_close = (closing - today).days if closing else None
    severity = "urgent" if days_to_close is not None and days_to_close <= 7 else "watch"
    suggestion = (
        "Lender not responding. Suggest: Email lender's manager with CC to agent. "
        "If no response in 24hrs, discuss backup lender with buyer."
    )
    return _build_signal(
        transaction,
        "lender_unresponsive",
        severity,
        _headline(f"No lender communication for {days_silent} days", transaction),
        suggestion,
        {
            "days_without_lender_communication": days_silent,
            "last_lender_contact": last_lender_contact.isoformat() if last_lender_contact else "",
            "days_to_close": days_to_close,
        },
    )


def _evaluate_repair_overload(transaction: dict, inspection_analysis: dict | None):
    findings = (inspection_analysis or {}).get("findings") or {}
    repair_items = findings.get("repair_items") or []
    repair_count = len(repair_items)
    if repair_count < 25:
        return None
    severity = "urgent" if repair_count >= 35 else "watch"
    suggestion = (
        "Inspection report extensive. Suggest: Help buyer prioritize top 5 safety/major items only. "
        "Draft reasonable repair request to avoid seller rejection."
    )
    return _build_signal(
        transaction,
        "repair_overload",
        severity,
        _headline(f"Inspection found {repair_count} repair items", transaction),
        suggestion,
        {
            "repair_item_count": repair_count,
        },
    )


def _extension_addendum_draft(transaction: dict):
    property_address = transaction.get("property_address") or "Property"
    closing_label = (
        transaction["closing_date"].strftime("%b %d, %Y")
        if isinstance(transaction.get("closing_date"), date)
        else "TBD"
    )
    return (
        "Extension Addendum Draft\n"
        f"Property: {property_address}\n"
        f"Current Closing Date: {closing_label}\n"
        "Requested Extension: 7 calendar days\n"
        "Reason: Financing approval pending with lender.\n"
        "Proposed Terms: Existing contract terms remain unchanged except closing date extension.\n"
        "Prepared by Maverick Heads Up automation."
    )


def _evaluate_closing_at_risk(transaction: dict, today: date, loan_approved: bool):
    closing = transaction.get("closing_date")
    if not closing:
        return None
    days_to_close = (closing - today).days
    if days_to_close > 5 or loan_approved:
        return None
    suggestion = (
        "URGENT: Loan approval needed ASAP. Suggest: Conference call with lender/buyer/agent today. "
        "Prepare extension addendum as backup."
    )
    return _build_signal(
        transaction,
        "closing_at_risk",
        "urgent",
        _headline(f"Closing in {days_to_close} days without loan approval", transaction),
        suggestion,
        {
            "days_to_close": days_to_close,
            "loan_approved": loan_approved,
            "extension_addendum_draft": _extension_addendum_draft(transaction),
        },
    )


def detect_heads_up_signals(today: date | None = None):
    """Detect all pattern signals across active transactions."""
    if today is None:
        today = date.today()
    signals = []
    for transaction in fetch_active_transactions():
        transaction_id = transaction["id"]
        task_stats = fetch_task_stats(transaction_id)
        doc_types = fetch_document_types(transaction_id)
        appraisal_analysis = fetch_latest_analysis(transaction_id, "appraisal")
        inspection_analysis = fetch_latest_analysis(transaction_id, "inspection")
        last_lender_contact = fetch_last_lender_contact(transaction_id)
        loan_approved = loan_approval_confirmed(transaction_id, doc_types)

        candidates = [
            _evaluate_behind_schedule(transaction, today, task_stats, doc_types),
            _evaluate_appraisal_gap(transaction, appraisal_analysis),
            _evaluate_older_home_risk(transaction, inspection_analysis),
            _evaluate_lender_unresponsive(transaction, today, last_lender_contact),
            _evaluate_repair_overload(transaction, inspection_analysis),
            _evaluate_closing_at_risk(transaction, today, loan_approved),
        ]
        for signal in candidates:
            if signal:
                signals.append(signal)
    return signals


def upsert_daily_signals(signals: list[dict], signal_date: date | None = None):
    """Persist detected signals for the given day."""
    ensure_heads_up_tables()
    if signal_date is None:
        signal_date = date.today()
    for item in signals:
        execute_query(
            """
            INSERT INTO heads_up_signals (
                transaction_id, pattern_key, severity, headline, suggestion, details, signal_date, status, updated_at
            )
            VALUES (%s, %s, %s, %s, %s, %s::jsonb, %s, 'open', CURRENT_TIMESTAMP)
            ON CONFLICT (transaction_id, pattern_key, signal_date)
            DO UPDATE SET
                severity = EXCLUDED.severity,
                headline = EXCLUDED.headline,
                suggestion = EXCLUDED.suggestion,
                details = EXCLUDED.details,
                updated_at = CURRENT_TIMESTAMP,
                status = CASE
                    WHEN heads_up_signals.status IN ('dismissed', 'accepted', 'auto_handled')
                        THEN heads_up_signals.status
                    ELSE 'open'
                END
            """,
            (
                item["transaction_id"],
                item["pattern_key"],
                item["severity"],
                item["headline"],
                item["suggestion"],
                json.dumps(item.get("details") or {}, default=str),
                signal_date,
            ),
        )


def resolve_stale_open_signals(signals: list[dict], signal_date: date | None = None):
    """Resolve open signals that are no longer detected on the same day."""
    ensure_heads_up_tables()
    if signal_date is None:
        signal_date = date.today()
    active_pairs = {(item["transaction_id"], item["pattern_key"]) for item in signals}
    rows = execute_query(
        """
        SELECT id, transaction_id, pattern_key
        FROM heads_up_signals
        WHERE signal_date = %s
          AND status = 'open'
        """,
        (signal_date,),
        fetch=True,
    ) or []
    for row in rows:
        key = (row["transaction_id"], row["pattern_key"])
        if key in active_pairs:
            continue
        execute_query(
            """
            UPDATE heads_up_signals
            SET status = 'resolved',
                updated_at = CURRENT_TIMESTAMP
            WHERE id = %s
            """,
            (row["id"],),
        )


def fetch_signal(signal_id: int):
    """Fetch one signal row with transaction details."""
    ensure_heads_up_tables()
    rows = execute_query(
        """
        SELECT hs.id, hs.transaction_id, hs.pattern_key, hs.severity, hs.headline, hs.suggestion,
               hs.details, hs.signal_date, hs.status, hs.modified_suggestion,
               hs.accepted_by, hs.accepted_at, hs.dismissed_by, hs.dismissed_at, hs.dismissal_notes,
               hs.auto_action_result, hs.updated_at, t.property_address
        FROM heads_up_signals hs
        JOIN transactions t ON t.id = hs.transaction_id
        WHERE hs.id = %s
        LIMIT 1
        """,
        (signal_id,),
        fetch=True,
    ) or []
    if not rows:
        return None
    row = rows[0]
    row["details"] = parse_json_field(row.get("details"), {})
    return row


def _create_heads_up_task(transaction_id: int, description: str, notes: str, priority: str = "high", due_days: int = 0):
    due_date = date.today() + timedelta(days=max(int(due_days), 0))
    rows = execute_query(
        """
        INSERT INTO tasks (
            transaction_id, task_description, task_category, due_date,
            priority, status, completed, display_order, notes, created_at
        )
        VALUES (%s, %s, 'coordination', %s, %s, 'pending', FALSE, 66, %s, CURRENT_TIMESTAMP)
        RETURNING id
        """,
        (
            transaction_id,
            description[:300],
            (priority or "high").lower(),
            (notes or "")[:1200],
        ),
        fetch=True,
    ) or []
    return rows[0]["id"] if rows else None


def accept_heads_up_signal(signal_id: int, acted_by: str = "margaret", suggestion_override: str = "", auto_handled: bool = False):
    """Accept one signal and create execution task."""
    signal = fetch_signal(signal_id)
    if not signal:
        return None
    if signal.get("status") in {"dismissed", "resolved"}:
        return None

    suggestion_text = (suggestion_override or "").strip() or signal.get("suggestion") or ""
    severity = (signal.get("severity") or "watch").lower()
    due_days = 0 if severity == "urgent" else 1
    task_id = _create_heads_up_task(
        transaction_id=signal["transaction_id"],
        description=f"Heads Up: {signal.get('headline')}",
        notes=suggestion_text,
        priority="high" if severity == "urgent" else "medium",
        due_days=due_days,
    )

    action_status = "auto_handled" if auto_handled else "accepted"
    execute_query(
        """
        UPDATE heads_up_signals
        SET status = %s,
            modified_suggestion = %s,
            accepted_by = %s,
            accepted_at = CURRENT_TIMESTAMP,
            auto_action_result = %s,
            updated_at = CURRENT_TIMESTAMP
        WHERE id = %s
        """,
        (
            action_status,
            suggestion_text,
            (acted_by or "margaret")[:100],
            f"task_id={task_id or 'n/a'}",
            signal_id,
        ),
    )
    execute_query(
        """
        INSERT INTO communications (transaction_id, communication_type, contact_party, contact_name, summary, outcome)
        VALUES (%s, 'note', 'system', %s, %s, %s)
        """,
        (
            signal["transaction_id"],
            (acted_by or "margaret")[:100],
            "Heads Up suggestion accepted",
            f"signal_id={signal_id} task_id={task_id or 'n/a'} auto={auto_handled}",
        ),
    )
    return task_id


def dismiss_heads_up_signal(signal_id: int, dismissed_by: str = "margaret", notes: str = ""):
    """Dismiss one signal."""
    signal = fetch_signal(signal_id)
    if not signal:
        return False
    execute_query(
        """
        UPDATE heads_up_signals
        SET status = 'dismissed',
            dismissed_by = %s,
            dismissed_at = CURRENT_TIMESTAMP,
            dismissal_notes = %s,
            updated_at = CURRENT_TIMESTAMP
        WHERE id = %s
        """,
        (
            (dismissed_by or "margaret")[:100],
            (notes or "")[:500] or None,
            signal_id,
        ),
    )
    execute_query(
        """
        INSERT INTO communications (transaction_id, communication_type, contact_party, contact_name, summary, outcome)
        VALUES (%s, 'note', 'system', %s, %s, %s)
        """,
        (
            signal["transaction_id"],
            (dismissed_by or "margaret")[:100],
            "Heads Up suggestion dismissed",
            f"signal_id={signal_id}",
        ),
    )
    return True


def _auto_handle_signals(signal_date: date, preferences: dict[str, dict[str, Any]]):
    rows = execute_query(
        """
        SELECT id, pattern_key
        FROM heads_up_signals
        WHERE signal_date = %s
          AND status = 'open'
        ORDER BY severity DESC, id ASC
        """,
        (signal_date,),
        fetch=True,
    ) or []
    handled = 0
    for row in rows:
        pref = preferences.get(row["pattern_key"], {})
        if not pref.get("auto_handle"):
            continue
        task_id = accept_heads_up_signal(
            signal_id=row["id"],
            acted_by="auto-monitor",
            suggestion_override="",
            auto_handled=True,
        )
        if task_id is not None:
            handled += 1
    return handled


def _fetch_daily_signals(signal_date: date):
    rows = execute_query(
        """
        SELECT hs.id, hs.transaction_id, hs.pattern_key, hs.severity, hs.headline, hs.suggestion,
               hs.details, hs.signal_date, hs.status, hs.modified_suggestion,
               hs.accepted_by, hs.accepted_at, hs.dismissed_by, hs.dismissed_at, hs.dismissal_notes,
               hs.auto_action_result, hs.updated_at, t.property_address
        FROM heads_up_signals hs
        JOIN transactions t ON t.id = hs.transaction_id
        WHERE hs.signal_date = %s
        ORDER BY
            CASE hs.severity WHEN 'urgent' THEN 0 WHEN 'watch' THEN 1 ELSE 2 END,
            hs.id DESC
        """,
        (signal_date,),
        fetch=True,
    ) or []
    for row in rows:
        row["details"] = parse_json_field(row.get("details"), {})
        row["signal_date_label"] = row["signal_date"].strftime("%b %d, %Y") if row.get("signal_date") else ""
        row["accepted_at_label"] = row["accepted_at"].strftime("%b %d, %Y %I:%M %p") if row.get("accepted_at") else ""
        row["dismissed_at_label"] = (
            row["dismissed_at"].strftime("%b %d, %Y %I:%M %p") if row.get("dismissed_at") else ""
        )
        row["pattern_label"] = HEADS_UP_PATTERN_META.get(row["pattern_key"], {}).get("label", row["pattern_key"])
    return rows


def build_heads_up_report(signal_date: date | None = None):
    """Build report payload grouped by health/watch/urgent."""
    ensure_heads_up_tables()
    if signal_date is None:
        signal_date = date.today()
    all_signals = _fetch_daily_signals(signal_date)

    open_signals = [row for row in all_signals if row.get("status") == "open"]
    open_urgent = [row for row in open_signals if row.get("severity") == "urgent"]
    open_watch = [row for row in open_signals if row.get("severity") == "watch"]
    accepted = [row for row in all_signals if row.get("status") in {"accepted", "auto_handled"}]
    dismissed = [row for row in all_signals if row.get("status") == "dismissed"]

    active_rows = execute_query(
        "SELECT COUNT(*) AS total FROM transactions WHERE status = 'ACTIVE'",
        fetch=True,
    ) or []
    total_active = int(active_rows[0]["total"] or 0) if active_rows else 0
    flagged_transaction_ids = {row["transaction_id"] for row in open_signals}
    healthy_count = max(total_active - len(flagged_transaction_ids), 0)

    return {
        "signal_date": signal_date,
        "signal_date_label": signal_date.strftime("%A, %B %d, %Y"),
        "summary": {
            "total_active": total_active,
            "healthy_count": healthy_count,
            "watch_count": len(open_watch),
            "urgent_count": len(open_urgent),
            "accepted_count": len(accepted),
            "dismissed_count": len(dismissed),
        },
        "open_urgent": open_urgent,
        "open_watch": open_watch,
        "accepted": accepted,
        "dismissed": dismissed,
        "all_signals": all_signals,
    }


def _build_sms_summary(report: dict, preferences: dict[str, dict[str, Any]]):
    open_urgent = [
        row for row in report["open_urgent"] if preferences.get(row["pattern_key"], {}).get("always_alert", True)
    ]
    open_watch = [
        row for row in report["open_watch"] if preferences.get(row["pattern_key"], {}).get("always_alert", True)
    ]
    if not open_urgent and not open_watch:
        return None

    lines = [
        "Heads Up Summary",
        (
            f"Healthy {report['summary']['healthy_count']} | "
            f"Watch {len(open_watch)} | Urgent {len(open_urgent)}"
        ),
    ]
    for item in open_urgent[:3]:
        lines.append(f"URGENT: {item['property_address']} - {item['headline']}")
    for item in open_watch[:3]:
        lines.append(f"WATCH: {item['property_address']} - {item['headline']}")
    lines.append("Open /tc/heads-up for full actions.")
    return "\n".join(lines)


def run_heads_up_monitor(signal_date: date | None = None, send_sms: bool = True):
    """Detect, persist, auto-handle, and summarize heads-up signals."""
    ensure_heads_up_tables()
    if signal_date is None:
        signal_date = date.today()
    detected = detect_heads_up_signals(signal_date)
    upsert_daily_signals(detected, signal_date)
    resolve_stale_open_signals(detected, signal_date)

    preferences = fetch_pattern_preferences()
    auto_handled_count = _auto_handle_signals(signal_date, preferences)
    report = build_heads_up_report(signal_date)

    sms_sid = None
    if send_sms:
        margaret_phone = (os.getenv("MARGARET_PHONE") or "").strip()
        sms_payload = _build_sms_summary(report, preferences)
        if margaret_phone and sms_payload:
            from utils.sms import send_sms

            sms_sid = send_sms(margaret_phone, sms_payload)
    return {
        "detected_count": len(detected),
        "auto_handled_count": auto_handled_count,
        "sms_sid": sms_sid,
        "report": report,
    }


def refresh_heads_up_if_stale(max_age_minutes: int = 180, send_sms: bool = False):
    """Run monitor only when no recent update exists for today's signals."""
    ensure_heads_up_tables()
    today = date.today()
    rows = execute_query(
        """
        SELECT MAX(updated_at) AS last_updated
        FROM heads_up_signals
        WHERE signal_date = %s
        """,
        (today,),
        fetch=True,
    ) or []
    last_updated = rows[0].get("last_updated") if rows else None
    if not last_updated:
        return run_heads_up_monitor(signal_date=today, send_sms=send_sms)

    age = datetime.now(last_updated.tzinfo) - last_updated if isinstance(last_updated, datetime) else timedelta.max
    if age.total_seconds() >= max_age_minutes * 60:
        return run_heads_up_monitor(signal_date=today, send_sms=send_sms)
    return None
