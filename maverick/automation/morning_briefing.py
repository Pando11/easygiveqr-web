#!/usr/bin/env python3
"""
Maverick intelligent morning briefing automation.

Recommended Railway schedules:
- Morning briefing: daily at 7:30 AM
- Evening recap: daily at 2:00 PM
"""

from __future__ import annotations

import argparse
import json
import os
import re
import sys
from collections import Counter
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Any

from dotenv import load_dotenv

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
load_dotenv()

from utils.db import execute_query, get_active_transactions  # noqa: E402
from utils.email import send_email  # noqa: E402
from utils.sms import send_sms  # noqa: E402

DEFAULT_BRIEFING_SEND_TIME = "07:30"
DEFAULT_RECAP_SEND_TIME = "14:00"
DEFAULT_TIMEZONE = "America/Chicago"


def log(message: str) -> None:
    """Print timestamped logs for cron output."""
    print(f"[{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}] {message}")


def _safe_text(value: Any, fallback: str = "") -> str:
    text = str(value or "").strip()
    return text if text else fallback


def _normalize_email(value: Any) -> str:
    return _safe_text(value).lower()


def _normalize_phone(value: Any) -> str:
    digits = re.sub(r"\D", "", str(value or ""))
    if len(digits) == 10:
        return f"+1{digits}"
    if len(digits) == 11 and digits.startswith("1"):
        return f"+{digits}"
    if str(value or "").startswith("+"):
        return str(value).strip()
    return f"+{digits}" if digits else ""


def _json_dumps(payload: Any) -> str:
    return json.dumps(payload or {}, default=str)


def _parse_json_field(raw_value: Any, default_value: Any):
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


def _priority_rank(priority: str) -> int:
    normalized = _safe_text(priority).lower()
    if normalized == "high":
        return 3
    if normalized == "low":
        return 1
    return 2


def _minutes_label(total_minutes: int) -> str:
    hours = max(0, int(total_minutes or 0)) // 60
    minutes = max(0, int(total_minutes or 0)) % 60
    if hours and minutes:
        return f"{hours}h {minutes}m"
    if hours:
        return f"{hours}h"
    return f"{minutes}m"


def _app_base_url() -> str:
    return (os.getenv("APP_BASE_URL") or "http://localhost:5000").strip().rstrip("/")


def ensure_morning_briefing_tables() -> None:
    """Ensure morning briefing settings, briefing runs, and interactive items tables."""
    execute_query(
        """
        CREATE TABLE IF NOT EXISTS morning_briefing_settings (
            id SERIAL PRIMARY KEY,
            enabled BOOLEAN DEFAULT TRUE,
            send_time VARCHAR(5) DEFAULT '07:30',
            recap_enabled BOOLEAN DEFAULT TRUE,
            recap_time VARCHAR(5) DEFAULT '14:00',
            timezone VARCHAR(80) DEFAULT 'America/Chicago',
            ai_enabled BOOLEAN DEFAULT TRUE,
            updated_by VARCHAR(100),
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
        """
    )
    execute_query(
        """
        CREATE TABLE IF NOT EXISTS morning_briefings (
            id SERIAL PRIMARY KEY,
            briefing_date DATE UNIQUE NOT NULL,
            generated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            status VARCHAR(20) DEFAULT 'ready',
            total_transactions INT DEFAULT 0,
            closing_today_count INT DEFAULT 0,
            closing_week_count INT DEFAULT 0,
            urgent_count INT DEFAULT 0,
            estimated_day_minutes INT DEFAULT 0,
            sms_version TEXT,
            email_subject VARCHAR(255),
            email_opening TEXT,
            payload JSONB DEFAULT '{}'::jsonb,
            sent_sms BOOLEAN DEFAULT FALSE,
            sent_email BOOLEAN DEFAULT FALSE,
            sms_sid VARCHAR(120),
            email_message_id VARCHAR(255),
            send_error TEXT,
            recap_generated_at TIMESTAMP,
            recap_payload JSONB DEFAULT '{}'::jsonb,
            recap_sms TEXT,
            recap_sent_sms BOOLEAN DEFAULT FALSE,
            recap_sent_email BOOLEAN DEFAULT FALSE,
            recap_sms_sid VARCHAR(120),
            recap_email_message_id VARCHAR(255),
            recap_send_error TEXT,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
        """
    )
    execute_query(
        """
        CREATE TABLE IF NOT EXISTS morning_briefing_items (
            id SERIAL PRIMARY KEY,
            briefing_id INT REFERENCES morning_briefings(id) ON DELETE CASCADE,
            transaction_id INT REFERENCES transactions(id) ON DELETE SET NULL,
            item_type VARCHAR(50) NOT NULL,
            category VARCHAR(50),
            priority VARCHAR(20) DEFAULT 'medium',
            title TEXT NOT NULL,
            details TEXT,
            contact_phone VARCHAR(25),
            contact_email VARCHAR(255),
            status VARCHAR(20) DEFAULT 'pending',
            display_order INT DEFAULT 999,
            estimated_minutes INT DEFAULT 10,
            deferred_to_date DATE,
            notes TEXT,
            source_data JSONB DEFAULT '{}'::jsonb,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            completed_at TIMESTAMP
        )
        """
    )
    execute_query(
        """
        CREATE INDEX IF NOT EXISTS idx_morning_briefing_items_briefing
        ON morning_briefing_items(briefing_id, display_order, id)
        """
    )
    execute_query(
        """
        CREATE INDEX IF NOT EXISTS idx_morning_briefing_items_status
        ON morning_briefing_items(status, deferred_to_date, updated_at DESC)
        """
    )
    execute_query(
        """
        CREATE INDEX IF NOT EXISTS idx_morning_briefings_date
        ON morning_briefings(briefing_date DESC, generated_at DESC)
        """
    )

    rows = execute_query("SELECT id FROM morning_briefing_settings ORDER BY id ASC LIMIT 1", fetch=True) or []
    if not rows:
        execute_query(
            """
            INSERT INTO morning_briefing_settings (
                enabled, send_time, recap_enabled, recap_time, timezone, ai_enabled, updated_by, created_at, updated_at
            ) VALUES (%s, %s, %s, %s, %s, %s, 'system', CURRENT_TIMESTAMP, CURRENT_TIMESTAMP)
            """,
            (
                True,
                (os.getenv("MORNING_BRIEFING_SEND_TIME") or DEFAULT_BRIEFING_SEND_TIME).strip()[:5],
                True,
                (os.getenv("EVENING_RECAP_SEND_TIME") or DEFAULT_RECAP_SEND_TIME).strip()[:5],
                (os.getenv("MORNING_BRIEFING_TIMEZONE") or DEFAULT_TIMEZONE).strip(),
                True,
            ),
        )


def fetch_morning_briefing_settings() -> dict[str, Any]:
    ensure_morning_briefing_tables()
    rows = execute_query(
        """
        SELECT id, enabled, send_time, recap_enabled, recap_time, timezone, ai_enabled, updated_by, created_at, updated_at
        FROM morning_briefing_settings
        ORDER BY id ASC
        LIMIT 1
        """,
        fetch=True,
    ) or []
    if not rows:
        return {
            "id": 0,
            "enabled": True,
            "send_time": DEFAULT_BRIEFING_SEND_TIME,
            "recap_enabled": True,
            "recap_time": DEFAULT_RECAP_SEND_TIME,
            "timezone": DEFAULT_TIMEZONE,
            "ai_enabled": True,
        }
    row = rows[0]
    row["send_time"] = _safe_text(row.get("send_time"), DEFAULT_BRIEFING_SEND_TIME)[:5]
    row["recap_time"] = _safe_text(row.get("recap_time"), DEFAULT_RECAP_SEND_TIME)[:5]
    row["timezone"] = _safe_text(row.get("timezone"), DEFAULT_TIMEZONE)
    return row


def update_morning_briefing_settings(settings_payload: dict[str, Any], updated_by: str = "margaret") -> dict[str, Any]:
    ensure_morning_briefing_tables()
    current = fetch_morning_briefing_settings()
    values = {
        "enabled": bool(settings_payload.get("enabled", current.get("enabled"))),
        "send_time": _safe_text(settings_payload.get("send_time"), current.get("send_time") or DEFAULT_BRIEFING_SEND_TIME)[:5],
        "recap_enabled": bool(settings_payload.get("recap_enabled", current.get("recap_enabled"))),
        "recap_time": _safe_text(settings_payload.get("recap_time"), current.get("recap_time") or DEFAULT_RECAP_SEND_TIME)[:5],
        "timezone": _safe_text(settings_payload.get("timezone"), current.get("timezone") or DEFAULT_TIMEZONE),
        "ai_enabled": bool(settings_payload.get("ai_enabled", current.get("ai_enabled"))),
    }
    execute_query(
        """
        UPDATE morning_briefing_settings
        SET enabled = %s,
            send_time = %s,
            recap_enabled = %s,
            recap_time = %s,
            timezone = %s,
            ai_enabled = %s,
            updated_by = %s,
            updated_at = CURRENT_TIMESTAMP
        WHERE id = %s
        """,
        (
            values["enabled"],
            values["send_time"],
            values["recap_enabled"],
            values["recap_time"],
            values["timezone"],
            values["ai_enabled"],
            _safe_text(updated_by, "margaret"),
            current["id"],
        ),
    )
    return fetch_morning_briefing_settings()


def _hydrate_briefing_row(row: dict[str, Any] | None) -> dict[str, Any] | None:
    if not row:
        return None
    hydrated = dict(row)
    hydrated["payload"] = _parse_json_field(row.get("payload"), {})
    hydrated["recap_payload"] = _parse_json_field(row.get("recap_payload"), {})
    return hydrated


def fetch_morning_briefing_by_date(briefing_date: date | str) -> dict[str, Any] | None:
    ensure_morning_briefing_tables()
    target = briefing_date.isoformat() if isinstance(briefing_date, date) else _safe_text(briefing_date)
    rows = execute_query(
        """
        SELECT *
        FROM morning_briefings
        WHERE briefing_date = %s
        LIMIT 1
        """,
        (target,),
        fetch=True,
    ) or []
    return _hydrate_briefing_row(rows[0] if rows else None)


def fetch_latest_morning_briefing(days_back: int = 14) -> dict[str, Any] | None:
    ensure_morning_briefing_tables()
    start_date = date.today() - timedelta(days=max(1, int(days_back or 14)))
    rows = execute_query(
        """
        SELECT *
        FROM morning_briefings
        WHERE briefing_date >= %s
        ORDER BY briefing_date DESC, generated_at DESC, id DESC
        LIMIT 1
        """,
        (start_date,),
        fetch=True,
    ) or []
    return _hydrate_briefing_row(rows[0] if rows else None)


def fetch_morning_briefing_items(briefing_id: int, include_completed: bool = True) -> list[dict[str, Any]]:
    ensure_morning_briefing_tables()
    filters = ["briefing_id = %s"]
    params: list[Any] = [int(briefing_id)]
    if not include_completed:
        filters.append("status <> 'completed'")
    rows = execute_query(
        f"""
        SELECT id, briefing_id, transaction_id, item_type, category, priority, title, details,
               contact_phone, contact_email, status, display_order, estimated_minutes,
               deferred_to_date, notes, source_data, created_at, updated_at, completed_at
        FROM morning_briefing_items
        WHERE {' AND '.join(filters)}
        ORDER BY display_order ASC, id ASC
        """,
        tuple(params),
        fetch=True,
    ) or []
    for row in rows:
        row["source_data"] = _parse_json_field(row.get("source_data"), {})
    return rows


def update_morning_briefing_item(
    item_id: int,
    status: str | None = None,
    notes: str | None = None,
    deferred_to_date: date | None = None,
) -> bool:
    ensure_morning_briefing_tables()
    existing_rows = execute_query(
        """
        SELECT id, status, notes, deferred_to_date
        FROM morning_briefing_items
        WHERE id = %s
        LIMIT 1
        """,
        (int(item_id),),
        fetch=True,
    ) or []
    if not existing_rows:
        return False
    existing = existing_rows[0]
    next_status = _safe_text(status, existing.get("status") or "pending").lower()
    if next_status not in {"pending", "completed", "deferred"}:
        next_status = existing.get("status") or "pending"

    effective_notes = notes if notes is not None else existing.get("notes")
    execute_query(
        """
        UPDATE morning_briefing_items
        SET status = %s,
            notes = %s,
            deferred_to_date = %s,
            completed_at = CASE WHEN %s = 'completed' THEN CURRENT_TIMESTAMP ELSE NULL END,
            updated_at = CURRENT_TIMESTAMP
        WHERE id = %s
        """,
        (
            next_status,
            (_safe_text(effective_notes) or None),
            deferred_to_date,
            next_status,
            int(item_id),
        ),
    )
    return True


def move_morning_briefing_item(item_id: int, direction: str) -> bool:
    """Move one interactive briefing item up/down in priority order."""
    ensure_morning_briefing_tables()
    item_rows = execute_query(
        """
        SELECT id, briefing_id, display_order
        FROM morning_briefing_items
        WHERE id = %s
        LIMIT 1
        """,
        (int(item_id),),
        fetch=True,
    ) or []
    if not item_rows:
        return False
    item = item_rows[0]
    comparator = "<" if _safe_text(direction).lower() == "up" else ">"
    sort_order = "DESC" if comparator == "<" else "ASC"
    neighbor_rows = execute_query(
        f"""
        SELECT id, display_order
        FROM morning_briefing_items
        WHERE briefing_id = %s
          AND display_order {comparator} %s
        ORDER BY display_order {sort_order}, id {sort_order}
        LIMIT 1
        """,
        (item["briefing_id"], item["display_order"]),
        fetch=True,
    ) or []
    if not neighbor_rows:
        return False
    neighbor = neighbor_rows[0]
    execute_query(
        """
        UPDATE morning_briefing_items
        SET display_order = CASE
                WHEN id = %s THEN %s
                WHEN id = %s THEN %s
                ELSE display_order
            END,
            updated_at = CURRENT_TIMESTAMP
        WHERE id IN (%s, %s)
        """,
        (
            item["id"],
            neighbor["display_order"],
            neighbor["id"],
            item["display_order"],
            item["id"],
            neighbor["id"],
        ),
    )
    return True


def days_until_closing(transaction: dict[str, Any]) -> int | None:
    closing_date = transaction.get("closing_date")
    if not closing_date:
        return None
    try:
        return int((closing_date - date.today()).days)
    except Exception:
        return None


def _issue_first_line(issues_value: Any) -> str:
    issues = _parse_json_field(issues_value, [])
    if isinstance(issues, list) and issues:
        first = issues[0]
        if isinstance(first, dict):
            issue_type = _safe_text(first.get("type"), "issue").replace("_", " ")
            details = _safe_text(first.get("details"))
            return f"{issue_type.title()}: {details}" if details else issue_type.title()
        return _safe_text(first)
    return ""


def get_urgent_problems(limit: int = 20) -> list[dict[str, Any]]:
    rows = execute_query(
        """
        WITH latest_urgent AS (
            SELECT DISTINCT ON (pdr.transaction_id)
                pdr.id,
                pdr.transaction_id,
                pdr.health_score,
                pdr.bucket,
                pdr.issues,
                pdr.created_at,
                t.property_address,
                t.agent_name,
                t.agent_phone,
                t.lender_name,
                t.lender_phone
            FROM problem_detection_results pdr
            JOIN transactions t ON t.id = pdr.transaction_id
            WHERE pdr.status = 'open'
              AND pdr.bucket = 'urgent'
              AND t.status = 'ACTIVE'
            ORDER BY pdr.transaction_id, pdr.created_at DESC, pdr.id DESC
        )
        SELECT *
        FROM latest_urgent
        ORDER BY created_at DESC, id DESC
        LIMIT %s
        """,
        (int(limit),),
        fetch=True,
    ) or []
    for row in rows:
        row["issues"] = _parse_json_field(row.get("issues"), [])
        row["summary_line"] = _issue_first_line(row.get("issues"))
    return rows


def get_overdue_tasks(limit: int = 60) -> list[dict[str, Any]]:
    rows = execute_query(
        """
        SELECT tk.id, tk.transaction_id, tk.task_description, tk.task_category, tk.priority, tk.due_date,
               tk.notes, t.property_address, t.agent_name, t.agent_phone
        FROM tasks tk
        JOIN transactions t ON t.id = tk.transaction_id
        WHERE t.status = 'ACTIVE'
          AND tk.completed = FALSE
          AND COALESCE(tk.status, 'pending') <> 'completed'
          AND tk.due_date < %s
        ORDER BY tk.due_date ASC, tk.display_order ASC NULLS LAST, tk.id ASC
        LIMIT %s
        """,
        (date.today(), int(limit)),
        fetch=True,
    ) or []
    for row in rows:
        row["days_overdue"] = (date.today() - row["due_date"]).days if row.get("due_date") else 0
    return rows


def get_due_today_tasks(limit: int = 60) -> list[dict[str, Any]]:
    rows = execute_query(
        """
        SELECT tk.id, tk.transaction_id, tk.task_description, tk.task_category, tk.priority, tk.due_date,
               tk.notes, t.property_address, t.agent_name, t.agent_phone
        FROM tasks tk
        JOIN transactions t ON t.id = tk.transaction_id
        WHERE t.status = 'ACTIVE'
          AND tk.completed = FALSE
          AND COALESCE(tk.status, 'pending') <> 'completed'
          AND tk.due_date = %s
        ORDER BY tk.display_order ASC NULLS LAST, tk.id ASC
        LIMIT %s
        """,
        (date.today(), int(limit)),
        fetch=True,
    ) or []
    return rows


def get_pending_decisions(limit: int = 40) -> list[dict[str, Any]]:
    pending: list[dict[str, Any]] = []

    review_rows = execute_query(
        """
        SELECT id AS transaction_id, property_address, agent_name, agent_phone, created_at
        FROM transactions
        WHERE status = 'NEEDS_MARGARET_REVIEW'
        ORDER BY created_at ASC
        LIMIT %s
        """,
        (max(5, int(limit // 2)),),
        fetch=True,
    ) or []
    for row in review_rows:
        pending.append(
            {
                "decision_type": "approval",
                "priority": "high",
                "transaction_id": row["transaction_id"],
                "property_address": row.get("property_address"),
                "title": "Approve intake and activate transaction",
                "details": f"Pending Margaret review for {row.get('agent_name') or 'agent'}.",
                "contact_phone": row.get("agent_phone"),
            }
        )

    analysis_rows = execute_query(
        """
        SELECT dar.id, dar.transaction_id, dar.document_type, dar.analysis_date,
               t.property_address, t.agent_name, t.agent_phone
        FROM document_analysis_results dar
        JOIN transactions t ON t.id = dar.transaction_id
        WHERE t.status = 'ACTIVE'
          AND COALESCE(dar.margaret_reviewed, FALSE) = FALSE
        ORDER BY dar.analysis_date DESC, dar.id DESC
        LIMIT %s
        """,
        (max(5, int(limit // 2)),),
        fetch=True,
    ) or []
    for row in analysis_rows:
        pending.append(
            {
                "decision_type": "document_review",
                "priority": "medium",
                "transaction_id": row.get("transaction_id"),
                "property_address": row.get("property_address"),
                "title": f"Review {(_safe_text(row.get('document_type')) or 'document').replace('_', ' ')} findings",
                "details": "Document analysis has action items pending Margaret review.",
                "contact_phone": row.get("agent_phone"),
            }
        )

    payment_rows = execute_query(
        """
        SELECT id AS transaction_id, property_address, agent_phone, closing_date
        FROM transactions
        WHERE status = 'ACTIVE'
          AND payment_closing_paid = FALSE
          AND closing_date IS NOT NULL
          AND closing_date <= %s
        ORDER BY closing_date ASC, id ASC
        LIMIT %s
        """,
        (date.today() + timedelta(days=3), max(5, int(limit // 3))),
        fetch=True,
    ) or []
    for row in payment_rows:
        pending.append(
            {
                "decision_type": "payment_confirmation",
                "priority": "high",
                "transaction_id": row.get("transaction_id"),
                "property_address": row.get("property_address"),
                "title": "Confirm closing payment before closing date",
                "details": f"Closing is near ({row.get('closing_date')}). Payment not marked paid.",
                "contact_phone": row.get("agent_phone"),
            }
        )
    return pending[: max(1, int(limit))]


def get_calls_needed_today(limit: int = 40) -> list[dict[str, Any]]:
    today = date.today()
    call_window_start = today - timedelta(days=1)
    call_window_end = today + timedelta(days=3)
    rows = execute_query(
        """
        SELECT d.id AS deadline_id, d.deadline_type, d.deadline_date, d.margaret_called_agent,
               t.id AS transaction_id, t.property_address, t.agent_phone,
               t.lender_phone, t.title_officer_phone
        FROM deadlines d
        JOIN transactions t ON t.id = d.transaction_id
        WHERE t.status = 'ACTIVE'
          AND d.completed = FALSE
          AND d.is_critical = TRUE
          AND d.deadline_date >= %s
          AND d.deadline_date <= %s
        ORDER BY d.deadline_date ASC, d.id ASC
        LIMIT %s
        """,
        (call_window_start, call_window_end, int(limit)),
        fetch=True,
    ) or []
    payload = []
    for row in rows:
        deadline_type = _safe_text(row.get("deadline_type")).lower()
        if deadline_type in {"financing_approval", "earnest_money"}:
            contact_type = "lender"
            contact_phone = row.get("lender_phone") or row.get("agent_phone")
        elif deadline_type in {"title_commitment", "closing"}:
            contact_type = "title"
            contact_phone = row.get("title_officer_phone") or row.get("agent_phone")
        else:
            contact_type = "agent"
            contact_phone = row.get("agent_phone")
        payload.append(
            {
                "deadline_id": row.get("deadline_id"),
                "transaction_id": row.get("transaction_id"),
                "property_address": row.get("property_address"),
                "deadline_type": row.get("deadline_type"),
                "deadline_date": row.get("deadline_date"),
                "contact_type": contact_type,
                "contact_phone": contact_phone,
                "made": bool(row.get("margaret_called_agent")),
            }
        )
    return payload


def get_recent_good_news(limit: int = 12) -> list[dict[str, Any]]:
    good_news: list[dict[str, Any]] = []

    completed_txn_rows = execute_query(
        """
        SELECT id, property_address, completed_at
        FROM transactions
        WHERE status = 'COMPLETED'
          AND COALESCE(completed_at, updated_at, created_at) >= (CURRENT_TIMESTAMP - INTERVAL '7 days')
        ORDER BY COALESCE(completed_at, updated_at, created_at) DESC
        LIMIT %s
        """,
        (max(1, int(limit // 2)),),
        fetch=True,
    ) or []
    for row in completed_txn_rows:
        good_news.append(
            {
                "type": "completion",
                "label": f"Completed: {row.get('property_address')}",
                "created_at": row.get("completed_at"),
            }
        )

    completed_tasks = execute_query(
        """
        SELECT tk.id, tk.task_description, tk.completed_at, t.property_address
        FROM tasks tk
        JOIN transactions t ON t.id = tk.transaction_id
        WHERE tk.completed = TRUE
          AND tk.completed_at >= (CURRENT_TIMESTAMP - INTERVAL '24 hours')
        ORDER BY tk.completed_at DESC
        LIMIT %s
        """,
        (max(1, int(limit // 2)),),
        fetch=True,
    ) or []
    for row in completed_tasks:
        good_news.append(
            {
                "type": "task",
                "label": f"Task done ({row.get('property_address')}): {row.get('task_description')}",
                "created_at": row.get("completed_at"),
            }
        )

    positive_reviews = execute_query(
        """
        SELECT ar.rating, ar.created_at, t.property_address
        FROM agent_reviews ar
        JOIN transactions t ON t.id = ar.transaction_id
        WHERE ar.rating >= 4
          AND ar.created_at >= (CURRENT_TIMESTAMP - INTERVAL '14 days')
        ORDER BY ar.created_at DESC
        LIMIT 5
        """,
        fetch=True,
    ) or []
    for row in positive_reviews:
        good_news.append(
            {
                "type": "review",
                "label": f"New {int(row.get('rating') or 0)}-star review ({row.get('property_address')})",
                "created_at": row.get("created_at"),
            }
        )
    return good_news[:limit]


def load_priority_learning(window_days: int = 45) -> dict[str, float]:
    """Learn preferred categories from completed/deferred briefing interactions."""
    ensure_morning_briefing_tables()
    rows = execute_query(
        """
        SELECT category,
               COUNT(*) FILTER (WHERE status = 'completed') AS completed_count,
               COUNT(*) FILTER (WHERE status = 'deferred') AS deferred_count,
               AVG(display_order) FILTER (WHERE status = 'completed') AS avg_completion_order
        FROM morning_briefing_items
        WHERE created_at >= (CURRENT_TIMESTAMP - (%s || ' days')::interval)
        GROUP BY category
        """,
        (int(window_days),),
        fetch=True,
    ) or []

    weights: dict[str, float] = {}
    for row in rows:
        category = _safe_text(row.get("category"), "general").lower()
        completed = float(row.get("completed_count") or 0)
        deferred = float(row.get("deferred_count") or 0)
        avg_order = float(row.get("avg_completion_order") or 12)
        score = (completed * 0.6) - (deferred * 0.35) + max(0.0, (14.0 - avg_order) * 0.08)
        weights[category] = round(score, 3)
    return weights


def _estimate_item_minutes(item_type: str, priority: str) -> int:
    base = {
        "urgent_problem": 14,
        "call": 8,
        "overdue_task": 12,
        "due_today": 10,
        "decision": 9,
    }.get(_safe_text(item_type).lower(), 8)
    if _safe_text(priority).lower() == "high":
        return base + 4
    if _safe_text(priority).lower() == "low":
        return max(4, base - 2)
    return base


def combine_priorities(
    overdue_tasks: list[dict[str, Any]],
    due_today_tasks: list[dict[str, Any]],
    pending_decisions: list[dict[str, Any]],
    calls_needed: list[dict[str, Any]],
    urgent_items: list[dict[str, Any]],
    learning_weights: dict[str, float] | None = None,
) -> list[dict[str, Any]]:
    """Combine priorities from multiple sources into one ordered action queue."""
    learning_weights = learning_weights or {}
    prioritized = []

    for row in urgent_items:
        category = "urgent_problem"
        prioritized.append(
            {
                "item_type": "urgent_problem",
                "category": category,
                "priority": "high",
                "transaction_id": row.get("transaction_id"),
                "property_address": row.get("property_address"),
                "title": f"Urgent problem: {row.get('property_address')}",
                "details": row.get("summary_line") or "Urgent risk requires immediate action.",
                "contact_phone": row.get("lender_phone") or row.get("agent_phone"),
                "contact_email": "",
                "estimated_minutes": _estimate_item_minutes("urgent_problem", "high"),
            }
        )

    for row in overdue_tasks:
        days_overdue = int(row.get("days_overdue") or 0)
        priority = "high" if days_overdue >= 3 else "medium"
        category = _safe_text(row.get("task_category"), "task").lower() or "task"
        prioritized.append(
            {
                "item_type": "overdue_task",
                "category": category,
                "priority": priority,
                "transaction_id": row.get("transaction_id"),
                "property_address": row.get("property_address"),
                "title": f"Overdue task ({days_overdue}d): {row.get('task_description')}",
                "details": _safe_text(row.get("notes")) or "Task is overdue and needs completion today.",
                "contact_phone": row.get("agent_phone"),
                "contact_email": "",
                "estimated_minutes": _estimate_item_minutes("overdue_task", priority),
            }
        )

    for row in due_today_tasks:
        category = _safe_text(row.get("task_category"), "task").lower() or "task"
        priority = "high" if _safe_text(row.get("priority"), "medium").lower() == "high" else "medium"
        prioritized.append(
            {
                "item_type": "due_today",
                "category": category,
                "priority": priority,
                "transaction_id": row.get("transaction_id"),
                "property_address": row.get("property_address"),
                "title": f"Due today: {row.get('task_description')}",
                "details": _safe_text(row.get("notes")) or "Complete this task today.",
                "contact_phone": row.get("agent_phone"),
                "contact_email": "",
                "estimated_minutes": _estimate_item_minutes("due_today", priority),
            }
        )

    for row in pending_decisions:
        category = _safe_text(row.get("decision_type"), "decision").lower()
        priority = _safe_text(row.get("priority"), "medium").lower()
        prioritized.append(
            {
                "item_type": "decision",
                "category": category,
                "priority": priority,
                "transaction_id": row.get("transaction_id"),
                "property_address": row.get("property_address"),
                "title": row.get("title") or "Pending decision",
                "details": row.get("details") or "Decision pending",
                "contact_phone": row.get("contact_phone"),
                "contact_email": row.get("contact_email"),
                "estimated_minutes": _estimate_item_minutes("decision", priority),
            }
        )

    for row in calls_needed:
        deadline_label = (_safe_text(row.get("deadline_type")) or "deadline").replace("_", " ").title()
        days_away = (row["deadline_date"] - date.today()).days if row.get("deadline_date") else None
        priority = "high" if days_away is not None and days_away <= 1 else "medium"
        prioritized.append(
            {
                "item_type": "call",
                "category": _safe_text(row.get("contact_type"), "calls").lower(),
                "priority": priority,
                "transaction_id": row.get("transaction_id"),
                "property_address": row.get("property_address"),
                "title": f"Call {row.get('contact_type')} re: {deadline_label}",
                "details": f"Critical milestone check for {row.get('property_address')}.",
                "contact_phone": row.get("contact_phone"),
                "contact_email": "",
                "estimated_minutes": _estimate_item_minutes("call", priority),
            }
        )

    for row in prioritized:
        category = _safe_text(row.get("category"), "general").lower()
        learning_boost = float(learning_weights.get(category, 0))
        row["priority_score"] = (_priority_rank(row.get("priority")) * 100) + learning_boost

    prioritized.sort(
        key=lambda item: (
            float(item.get("priority_score") or 0),
            int(item.get("estimated_minutes") or 0),
        ),
        reverse=True,
    )
    for idx, row in enumerate(prioritized, start=1):
        row["display_order"] = idx
    return prioritized


def _detect_pattern_highlights(transactions: list[dict[str, Any]], priorities: list[dict[str, Any]]) -> list[str]:
    highlights = []
    lender_counts = Counter(
        _safe_text(tx.get("lender_name"))
        for tx in transactions
        if _safe_text(tx.get("lender_name"))
    )
    repeated_lenders = [(name, count) for name, count in lender_counts.items() if count >= 3]
    repeated_lenders.sort(key=lambda item: item[1], reverse=True)
    if repeated_lenders:
        lender_name, lender_count = repeated_lenders[0]
        highlights.append(f"{lender_count} active transactions are waiting on lender updates from {lender_name}.")

    category_counts = Counter(_safe_text(item.get("category"), "general") for item in priorities)
    for category, count in category_counts.most_common(2):
        if count >= 3:
            highlights.append(f"{count} priorities are in the '{category.replace('_', ' ')}' category.")
    return highlights[:4]


def _suggest_batching(priorities: list[dict[str, Any]]) -> list[str]:
    suggestions = []
    call_items = [item for item in priorities if item.get("item_type") == "call"]
    if len(call_items) >= 3:
        suggestions.append("Batch all call tasks into one call sprint to reduce context switching.")

    transaction_counts = Counter(item.get("transaction_id") for item in priorities if item.get("transaction_id"))
    busy_transactions = [txn_id for txn_id, count in transaction_counts.items() if count >= 2]
    if busy_transactions:
        suggestions.append(
            "Handle multi-item transactions together to close loops faster "
            f"(IDs: {', '.join(str(txn_id) for txn_id in busy_transactions[:5])})."
        )

    urgent_then_calls = any(item.get("item_type") == "urgent_problem" for item in priorities) and bool(call_items)
    if urgent_then_calls:
        suggestions.append("Resolve urgent blockers first, then batch outbound calls.")
    return suggestions[:4]


def _build_fallback_briefing(data: dict[str, Any]) -> dict[str, Any]:
    priorities = data.get("priorities") or []
    top_items = priorities[:6]
    estimated_day_minutes = int(data.get("estimated_day_minutes") or 0)
    heavy_load = (
        int(data.get("urgent_count") or 0) >= 3
        or int(data.get("overdue_count") or 0) >= 7
        or len(priorities) >= 15
    )
    tone_line = (
        "Big day ahead, but you've handled tougher boards. Focus on top blockers first."
        if heavy_load
        else "Solid board today. You can finish strong and still protect focus time."
    )

    brief_url = f"{_app_base_url()}/tc/morning-briefing?date={date.today().isoformat()}"
    sms_items = []
    for item in top_items[:3]:
        title = _safe_text(item.get("title"))[:68]
        phone = _safe_text(item.get("contact_phone"))
        phone_suffix = f" ({phone})" if phone else ""
        sms_items.append(f"• {title}{phone_suffix}")
    sms_header = (
        f"🌅 {date.today().strftime('%a')} brief: "
        f"🚨{int(data.get('urgent_count') or 0)} "
        f"⏰{int(data.get('overdue_count') or 0)} "
        f"📞{int(data.get('calls_count') or 0)}"
    )
    sms_text = f"{sms_header}\n" + "\n".join(sms_items) + f"\nFull brief: {brief_url}"
    sms_text = sms_text[:500]

    recommended_order = []
    for idx, item in enumerate(top_items, start=1):
        recommended_order.append(
            {
                "step": idx,
                "title": item.get("title"),
                "transaction_id": item.get("transaction_id"),
                "estimated_minutes": int(item.get("estimated_minutes") or 0),
            }
        )

    return {
        "sms_version": sms_text,
        "email_version": {
            "subject": f"Morning Briefing - {date.today().strftime('%A, %b %d')}",
            "opening": tone_line,
            "workload_tone": "Heavy load" if heavy_load else "Balanced load",
            "total_transactions": int(data.get("total_transactions") or 0),
            "closing_today_count": int(data.get("closing_today_count") or 0),
            "closing_week_count": int(data.get("closing_week_count") or 0),
            "urgent_count": int(data.get("urgent_count") or 0),
            "overdue_count": int(data.get("overdue_count") or 0),
            "due_today_count": int(data.get("due_today_count") or 0),
            "calls_count": int(data.get("calls_count") or 0),
            "estimated_day_minutes": estimated_day_minutes,
            "estimated_day_label": _minutes_label(estimated_day_minutes),
            "pattern_highlights": data.get("pattern_highlights") or [],
            "batching_suggestions": data.get("batching_suggestions") or [],
            "recommended_order": recommended_order,
            "priority_items": top_items,
            "calls_needed": (data.get("calls_needed") or [])[:10],
            "good_news": data.get("good_news") or [],
            "brief_url": brief_url,
        },
    }


def _extract_json_object(raw_text: str) -> dict[str, Any] | None:
    text = _safe_text(raw_text)
    if not text:
        return None
    match = re.search(r"\{[\s\S]*\}", text)
    if not match:
        return None
    try:
        payload = json.loads(match.group(0))
        return payload if isinstance(payload, dict) else None
    except Exception:
        return None


def parse_briefing_response(raw_response: str) -> dict[str, Any]:
    """Parse Claude response and return dict when possible."""
    parsed = _extract_json_object(raw_response)
    return parsed or {}


def generate_briefing_with_ai(data: dict[str, Any]) -> dict[str, Any]:
    """
    Use Claude to create natural, prioritized morning briefing.
    Falls back to deterministic output if AI is unavailable.
    """
    fallback = _build_fallback_briefing(data)
    if not bool(data.get("ai_enabled", True)):
        return fallback

    api_key = (os.getenv("ANTHROPIC_API_KEY") or "").strip()
    if not api_key:
        return fallback

    try:
        from anthropic import Anthropic
    except Exception:
        return fallback

    compact_payload = {
        "active_transactions": int(data.get("total_transactions") or 0),
        "closing_today_count": int(data.get("closing_today_count") or 0),
        "closing_week_count": int(data.get("closing_week_count") or 0),
        "urgent_items": data.get("urgent_items") or [],
        "priority_items": (data.get("priorities") or [])[:16],
        "calls_needed": (data.get("calls_needed") or [])[:12],
        "good_news": (data.get("good_news") or [])[:10],
        "learning_profile": data.get("learning_profile") or {},
        "pattern_highlights": data.get("pattern_highlights") or [],
        "batching_suggestions": data.get("batching_suggestions") or [],
        "estimated_day_minutes": int(data.get("estimated_day_minutes") or 0),
    }

    prompt = f"""
Create a morning briefing for Margaret, a Texas real estate transaction coordinator.

Use this data:
{json.dumps(compact_payload, indent=2, default=str)}

Instructions:
- Learn from "learning_profile" and prioritize similar categories earlier.
- Adapt tone: encouraging if workload is heavy, celebratory if light.
- Highlight patterns (shared lender bottlenecks, repeated categories).
- Suggest batching opportunities.
- Include estimated time needed for the day.

Return ONLY valid JSON with this shape:
{{
  "sms_version": "max 500 chars",
  "email_version": {{
    "subject": "...",
    "opening": "...",
    "workload_tone": "...",
    "recommended_order": [{{"step":1,"title":"...","transaction_id":123,"estimated_minutes":12}}],
    "pattern_highlights": ["..."],
    "batching_suggestions": ["..."],
    "estimated_day_label": "xh ym",
    "priority_items": [{{"title":"...","details":"...","transaction_id":123,"priority":"high","estimated_minutes":12}}],
    "calls_needed": [{{"property_address":"...","contact_type":"...","contact_phone":"..."}}],
    "good_news": [{{"label":"..."}}]
  }}
}}
"""
    try:
        model = (os.getenv("MORNING_BRIEFING_MODEL") or "claude-sonnet-4-20250514").strip()
        client = Anthropic(api_key=api_key)
        response = client.messages.create(
            model=model,
            max_tokens=2500,
            messages=[{"role": "user", "content": prompt}],
        )
        text_parts = []
        for block in (response.content or []):
            text = getattr(block, "text", "")
            if text:
                text_parts.append(text)
        parsed = parse_briefing_response("\n".join(text_parts))
        if not parsed:
            return fallback
        sms_version = _safe_text(parsed.get("sms_version"), fallback["sms_version"])[:500]
        email_version = parsed.get("email_version") if isinstance(parsed.get("email_version"), dict) else {}
        merged_email = dict(fallback["email_version"])
        merged_email.update({key: value for key, value in email_version.items() if value not in (None, "")})
        if "estimated_day_label" not in merged_email:
            merged_email["estimated_day_label"] = _minutes_label(int(data.get("estimated_day_minutes") or 0))
        return {"sms_version": sms_version, "email_version": merged_email}
    except Exception as exc:
        log(f"AI morning briefing fallback triggered: {exc}")
        return fallback


def _upsert_briefing_row(briefing_date: date, data: dict[str, Any], briefing: dict[str, Any]) -> dict[str, Any]:
    ensure_morning_briefing_tables()
    email_version = briefing.get("email_version") or {}
    rows = execute_query(
        """
        INSERT INTO morning_briefings (
            briefing_date,
            generated_at,
            status,
            total_transactions,
            closing_today_count,
            closing_week_count,
            urgent_count,
            estimated_day_minutes,
            sms_version,
            email_subject,
            email_opening,
            payload,
            updated_at
        )
        VALUES (
            %s,
            CURRENT_TIMESTAMP,
            'ready',
            %s,
            %s,
            %s,
            %s,
            %s,
            %s,
            %s,
            %s,
            %s::jsonb,
            CURRENT_TIMESTAMP
        )
        ON CONFLICT (briefing_date)
        DO UPDATE SET
            generated_at = CURRENT_TIMESTAMP,
            status = 'ready',
            total_transactions = EXCLUDED.total_transactions,
            closing_today_count = EXCLUDED.closing_today_count,
            closing_week_count = EXCLUDED.closing_week_count,
            urgent_count = EXCLUDED.urgent_count,
            estimated_day_minutes = EXCLUDED.estimated_day_minutes,
            sms_version = EXCLUDED.sms_version,
            email_subject = EXCLUDED.email_subject,
            email_opening = EXCLUDED.email_opening,
            payload = EXCLUDED.payload,
            updated_at = CURRENT_TIMESTAMP
        RETURNING *
        """,
        (
            briefing_date,
            int(data.get("total_transactions") or 0),
            int(data.get("closing_today_count") or 0),
            int(data.get("closing_week_count") or 0),
            int(data.get("urgent_count") or 0),
            int(data.get("estimated_day_minutes") or 0),
            _safe_text(briefing.get("sms_version"))[:500],
            _safe_text(email_version.get("subject"))[:255] or f"Morning Briefing - {briefing_date.isoformat()}",
            _safe_text(email_version.get("opening"))[:1800],
            _json_dumps(briefing),
        ),
        fetch=True,
    ) or []
    if not rows:
        raise RuntimeError("Failed to store morning briefing.")
    return _hydrate_briefing_row(rows[0]) or {}


def _replace_briefing_items(briefing_id: int, priorities: list[dict[str, Any]]) -> None:
    execute_query("DELETE FROM morning_briefing_items WHERE briefing_id = %s", (int(briefing_id),))
    for idx, item in enumerate(priorities, start=1):
        execute_query(
            """
            INSERT INTO morning_briefing_items (
                briefing_id,
                transaction_id,
                item_type,
                category,
                priority,
                title,
                details,
                contact_phone,
                contact_email,
                status,
                display_order,
                estimated_minutes,
                source_data,
                created_at,
                updated_at
            )
            VALUES (
                %s, %s, %s, %s, %s, %s, %s, %s, %s,
                'pending', %s, %s, %s::jsonb, CURRENT_TIMESTAMP, CURRENT_TIMESTAMP
            )
            """,
            (
                int(briefing_id),
                item.get("transaction_id"),
                _safe_text(item.get("item_type"), "task")[:50],
                _safe_text(item.get("category"), "general")[:50],
                _safe_text(item.get("priority"), "medium")[:20],
                _safe_text(item.get("title"), "Priority item")[:600],
                _safe_text(item.get("details"))[:2000] or None,
                _normalize_phone(item.get("contact_phone")) or None,
                _normalize_email(item.get("contact_email")) or None,
                int(item.get("display_order") or idx),
                int(item.get("estimated_minutes") or 8),
                _json_dumps(item),
            ),
        )


def _send_morning_messages(briefing_row: dict[str, Any], briefing_payload: dict[str, Any]) -> dict[str, Any]:
    sms_sid = None
    email_message_id = None
    send_error = ""
    margaret_phone = _normalize_phone(os.getenv("MARGARET_PHONE") or "")
    margaret_email = _normalize_email(os.getenv("MARGARET_EMAIL") or "")
    sms_version = _safe_text(briefing_payload.get("sms_version"))[:500]
    email_version = briefing_payload.get("email_version") if isinstance(briefing_payload.get("email_version"), dict) else {}

    try:
        if margaret_phone and sms_version:
            sms_sid = send_sms(margaret_phone, sms_version)
    except Exception as exc:
        send_error = f"sms_error:{exc}"

    try:
        if margaret_email:
            email_context = dict(email_version)
            email_context.setdefault("subject", _safe_text(email_version.get("subject")) or "Morning Briefing")
            email_context.setdefault("briefing_date", briefing_row.get("briefing_date"))
            email_context.setdefault("brief_url", f"{_app_base_url()}/tc/morning-briefing?date={briefing_row.get('briefing_date')}")
            email_message_id = send_email(
                to=margaret_email,
                template="emails/morning_briefing.html",
                data=email_context,
            )
    except Exception as exc:
        send_error = f"{send_error}; email_error:{exc}".strip("; ")

    execute_query(
        """
        UPDATE morning_briefings
        SET sent_sms = %s,
            sent_email = %s,
            sms_sid = %s,
            email_message_id = %s,
            send_error = %s,
            updated_at = CURRENT_TIMESTAMP
        WHERE id = %s
        """,
        (
            bool(sms_sid),
            bool(email_message_id),
            sms_sid,
            email_message_id,
            send_error or None,
            briefing_row["id"],
        ),
    )
    return {
        "sms_sent": bool(sms_sid),
        "email_sent": bool(email_message_id),
        "sms_sid": sms_sid,
        "email_message_id": email_message_id,
        "send_error": send_error,
    }


def _build_input_dataset(settings: dict[str, Any]) -> dict[str, Any]:
    transactions = get_active_transactions(limit=700) or []
    closing_today = [tx for tx in transactions if tx.get("closing_date") == date.today()]
    closing_this_week = [
        tx for tx in transactions if days_until_closing(tx) is not None and (days_until_closing(tx) or 999) <= 7
    ]
    urgent_items = get_urgent_problems()
    overdue_tasks = get_overdue_tasks()
    due_today_tasks = get_due_today_tasks()
    pending_decisions = get_pending_decisions()
    calls_needed = get_calls_needed_today()
    good_news = get_recent_good_news()
    learning_profile = load_priority_learning()
    priorities = combine_priorities(
        overdue_tasks=overdue_tasks,
        due_today_tasks=due_today_tasks,
        pending_decisions=pending_decisions,
        calls_needed=calls_needed,
        urgent_items=urgent_items,
        learning_weights=learning_profile,
    )
    estimated_day_minutes = sum(int(item.get("estimated_minutes") or 0) for item in priorities[:18])
    pattern_highlights = _detect_pattern_highlights(transactions, priorities)
    batching_suggestions = _suggest_batching(priorities)
    return {
        "settings": settings,
        "transactions": transactions,
        "closing_today": closing_today,
        "closing_this_week": closing_this_week,
        "urgent_items": urgent_items,
        "overdue_tasks": overdue_tasks,
        "due_today_tasks": due_today_tasks,
        "pending_decisions": pending_decisions,
        "calls_needed": calls_needed,
        "good_news": good_news,
        "learning_profile": learning_profile,
        "priorities": priorities,
        "pattern_highlights": pattern_highlights,
        "batching_suggestions": batching_suggestions,
        "estimated_day_minutes": estimated_day_minutes,
        "total_transactions": len(transactions),
        "closing_today_count": len(closing_today),
        "closing_week_count": len(closing_this_week),
        "urgent_count": len(urgent_items),
        "overdue_count": len(overdue_tasks),
        "due_today_count": len(due_today_tasks),
        "calls_count": len(calls_needed),
        "ai_enabled": bool(settings.get("ai_enabled")),
    }


def generate_morning_briefing(force: bool = False, send_messages: bool = True) -> dict[str, Any]:
    """
    Create AI-powered morning briefing for Margaret.
    """
    ensure_morning_briefing_tables()
    settings = fetch_morning_briefing_settings()
    if not settings.get("enabled"):
        return {"success": False, "skipped": "disabled_in_settings"}

    today = date.today()
    existing = fetch_morning_briefing_by_date(today)
    if existing and not force:
        return {"success": True, "reused_existing": True, "briefing_id": existing["id"], "briefing": existing}

    data = _build_input_dataset(settings)
    briefing = generate_briefing_with_ai(data)
    briefing_row = _upsert_briefing_row(today, data, briefing)
    _replace_briefing_items(briefing_row["id"], data.get("priorities") or [])

    delivery = {"sms_sent": False, "email_sent": False}
    if send_messages:
        delivery = _send_morning_messages(briefing_row, briefing)

    return {
        "success": True,
        "briefing_id": briefing_row["id"],
        "briefing_date": today.isoformat(),
        "summary": {
            "total_transactions": data["total_transactions"],
            "closing_today_count": data["closing_today_count"],
            "closing_week_count": data["closing_week_count"],
            "urgent_count": data["urgent_count"],
            "estimated_day_minutes": data["estimated_day_minutes"],
        },
        "delivery": delivery,
        "briefing": briefing,
    }


def _build_evening_recap_payload(briefing_row: dict[str, Any], item_rows: list[dict[str, Any]]) -> dict[str, Any]:
    completed_items = [row for row in item_rows if _safe_text(row.get("status")).lower() == "completed"]
    deferred_items = [row for row in item_rows if _safe_text(row.get("status")).lower() == "deferred"]
    pending_items = [row for row in item_rows if _safe_text(row.get("status")).lower() == "pending"]

    completions_today = execute_query(
        """
        SELECT id, property_address
        FROM transactions
        WHERE status = 'COMPLETED'
          AND COALESCE(completed_at, updated_at, created_at) >= %s
        ORDER BY COALESCE(completed_at, updated_at, created_at) DESC, id DESC
        LIMIT 12
        """,
        (date.today(),),
        fetch=True,
    ) or []

    celebration_lines = []
    if completions_today:
        celebration_lines.append(
            f"{len(completions_today)} transaction(s) completed today: "
            + ", ".join(_safe_text(row.get("property_address"), f"#{row.get('id')}") for row in completions_today[:4])
        )
    if completed_items:
        celebration_lines.append(f"{len(completed_items)} priority briefing items checked off.")
    if not celebration_lines:
        celebration_lines.append("No major completions logged yet, but tomorrow starts with a clean action plan.")

    tomorrow = date.today() + timedelta(days=1)
    rollover_preview = [row for row in (pending_items + deferred_items) if row.get("status") != "completed"][:10]
    rollover_lines = []
    for row in rollover_preview:
        rollover_lines.append(
            {
                "title": row.get("title"),
                "transaction_id": row.get("transaction_id"),
                "deferred_to": row.get("deferred_to_date") or tomorrow,
                "priority": row.get("priority"),
            }
        )

    sms_lines = [
        f"🌆 2PM recap: ✅{len(completed_items)} done, ⏳{len(pending_items)} pending, ↪️{len(deferred_items)} deferred.",
    ]
    if celebration_lines:
        sms_lines.append(celebration_lines[0])
    sms_lines.append(f"Tomorrow queue: {len(rollover_preview)} items. Full: {_app_base_url()}/tc/morning-briefing")
    sms_text = " ".join(sms_lines)[:500]

    return {
        "subject": f"2PM Recap - {date.today().strftime('%A, %b %d')}",
        "briefing_date": briefing_row.get("briefing_date"),
        "completed_count": len(completed_items),
        "pending_count": len(pending_items),
        "deferred_count": len(deferred_items),
        "celebration_lines": celebration_lines,
        "rollover_lines": rollover_lines,
        "completed_items": completed_items[:12],
        "sms_version": sms_text,
        "brief_url": f"{_app_base_url()}/tc/morning-briefing?date={briefing_row.get('briefing_date')}",
    }


def generate_evening_recap(force: bool = False, send_messages: bool = True) -> dict[str, Any]:
    """Generate and send 2PM recap of progress and rollover items."""
    ensure_morning_briefing_tables()
    settings = fetch_morning_briefing_settings()
    if not settings.get("recap_enabled"):
        return {"success": False, "skipped": "recap_disabled_in_settings"}

    briefing = fetch_morning_briefing_by_date(date.today()) or fetch_latest_morning_briefing(days_back=3)
    if not briefing:
        return {"success": False, "skipped": "no_briefing_found"}
    if briefing.get("recap_generated_at") and not force:
        return {"success": True, "reused_existing": True, "briefing_id": briefing["id"], "briefing": briefing}

    items = fetch_morning_briefing_items(briefing["id"], include_completed=True)
    recap_payload = _build_evening_recap_payload(briefing, items)
    recap_sms = _safe_text(recap_payload.get("sms_version"))[:500]

    sms_sid = None
    email_message_id = None
    send_error = ""
    margaret_phone = _normalize_phone(os.getenv("MARGARET_PHONE") or "")
    margaret_email = _normalize_email(os.getenv("MARGARET_EMAIL") or "")

    if send_messages:
        try:
            if margaret_phone and recap_sms:
                sms_sid = send_sms(margaret_phone, recap_sms)
        except Exception as exc:
            send_error = f"sms_error:{exc}"
        try:
            if margaret_email:
                email_message_id = send_email(
                    to=margaret_email,
                    template="emails/evening_recap.html",
                    data=recap_payload,
                )
        except Exception as exc:
            send_error = f"{send_error}; email_error:{exc}".strip("; ")

    execute_query(
        """
        UPDATE morning_briefings
        SET recap_generated_at = CURRENT_TIMESTAMP,
            recap_payload = %s::jsonb,
            recap_sms = %s,
            recap_sent_sms = %s,
            recap_sent_email = %s,
            recap_sms_sid = %s,
            recap_email_message_id = %s,
            recap_send_error = %s,
            updated_at = CURRENT_TIMESTAMP
        WHERE id = %s
        """,
        (
            _json_dumps(recap_payload),
            recap_sms,
            bool(sms_sid),
            bool(email_message_id),
            sms_sid,
            email_message_id,
            send_error or None,
            briefing["id"],
        ),
    )
    return {
        "success": True,
        "briefing_id": briefing["id"],
        "delivery": {
            "sms_sent": bool(sms_sid),
            "email_sent": bool(email_message_id),
            "send_error": send_error,
        },
        "recap": recap_payload,
    }


def _cli() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run Maverick morning briefing automation.")
    parser.add_argument(
        "--mode",
        choices=["morning", "evening", "both"],
        default="morning",
        help="Which workflow to run.",
    )
    parser.add_argument("--force", action="store_true", help="Force regenerate even if already generated today.")
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Generate payloads but skip SMS/email delivery.",
    )
    return parser.parse_args()


def main() -> None:
    args = _cli()
    log(f"Morning briefing automation started (mode={args.mode}, force={args.force}, dry_run={args.dry_run})")
    send_messages = not args.dry_run

    if args.mode in {"morning", "both"}:
        morning_result = generate_morning_briefing(force=args.force, send_messages=send_messages)
        log(f"Morning result: {json.dumps(morning_result, default=str)[:2000]}")

    if args.mode in {"evening", "both"}:
        evening_result = generate_evening_recap(force=args.force, send_messages=send_messages)
        log(f"Evening result: {json.dumps(evening_result, default=str)[:2000]}")


if __name__ == "__main__":
    main()
