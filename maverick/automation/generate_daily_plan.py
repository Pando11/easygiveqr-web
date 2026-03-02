#!/usr/bin/env python3
"""
Maverick intelligent daily plan generator (time blocking + prioritization).

Recommended schedule:
- Daily plan generation: 7:00 AM
"""

from __future__ import annotations

import argparse
import json
import os
import re
import sys
from collections import defaultdict
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Any

from dotenv import load_dotenv

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
load_dotenv()

from utils.calendar_sync import delete_calendar_event_by_mapping, ensure_calendar_sync_tables, sync_to_calendar  # noqa: E402
from utils.db import execute_query  # noqa: E402
from utils.email import send_email  # noqa: E402
from utils.sms import send_sms  # noqa: E402

BASELINE_TASK_TIME_ESTIMATES: list[tuple[str, str, int]] = [
    ("Review new contract", "contract_review", 20),
    ("Approve transaction", "contract_review", 15),
    ("Schedule inspection", "scheduling", 8),
    ("Schedule appraisal", "scheduling", 8),
    ("Schedule survey", "scheduling", 6),
    ("Schedule final walk-through", "scheduling", 5),
    ("Call lender", "phone_calls", 10),
    ("Call agent", "phone_calls", 8),
    ("Call buyer", "phone_calls", 12),
    ("Call seller", "phone_calls", 12),
    ("Upload document", "admin", 3),
    ("Log communication", "admin", 2),
    ("Send status update", "communication", 5),
    ("Review inspection report", "document_review", 15),
    ("Handle urgent issue", "problem_solving", 30),
    ("Coordinate repairs", "problem_solving", 20),
]

TASK_ESTIMATE_CACHE: dict[str, Any] = {
    "loaded_at": None,
    "rows": [],
}


def log(message: str) -> None:
    print(f"[daily-plan {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}] {message}")


def _safe_text(value: Any, fallback: str = "") -> str:
    text = str(value or "").strip()
    return text if text else fallback


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


def _priority_rank(priority_tier: str) -> int:
    normalized = _safe_text(priority_tier).lower()
    if normalized == "critical":
        return 5
    if normalized == "high_priority":
        return 4
    if normalized == "batch_able":
        return 3
    if normalized == "routine":
        return 2
    return 1


def _plan_base_url() -> str:
    return (os.getenv("APP_BASE_URL") or "http://localhost:5000").strip().rstrip("/")


def _iso_to_datetime(raw_value: Any) -> datetime | None:
    if isinstance(raw_value, datetime):
        return raw_value
    text = _safe_text(raw_value)
    if not text:
        return None
    text = text.replace("Z", "+00:00")
    for parser in (
        lambda payload: datetime.fromisoformat(payload),
        lambda payload: datetime.strptime(payload, "%Y-%m-%d %H:%M:%S"),
    ):
        try:
            return parser(text)
        except Exception:
            continue
    return None


def _extract_json_object(raw_text: str) -> dict[str, Any] | None:
    text = _safe_text(raw_text)
    if not text:
        return None
    fence_match = re.search(r"```(?:json)?\s*(\{.*?\})\s*```", text, flags=re.DOTALL)
    if fence_match:
        text = fence_match.group(1).strip()
    match = re.search(r"\{[\s\S]*\}", text)
    if not match:
        return None
    try:
        payload = json.loads(match.group(0))
        return payload if isinstance(payload, dict) else None
    except Exception:
        return None


def ensure_daily_schedule_management_tables() -> None:
    """Compatibility tables requested for schedule management + estimate learning."""
    execute_query(
        """
        CREATE TABLE IF NOT EXISTS daily_schedules (
            id SERIAL PRIMARY KEY,
            date DATE UNIQUE,
            generated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            total_tasks INT,
            estimated_work_hours FLOAT,
            estimated_end_time TIME,
            schedule_data JSONB,
            margaret_reviewed BOOLEAN DEFAULT FALSE,
            reviewed_at TIMESTAMP
        )
        """
    )
    execute_query(
        """
        CREATE TABLE IF NOT EXISTS task_time_estimates (
            id SERIAL PRIMARY KEY,
            task_pattern VARCHAR(200) UNIQUE,
            category VARCHAR(100),
            estimated_minutes INT,
            actual_minutes_avg INT,
            sample_count INT DEFAULT 0,
            last_updated TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
        """
    )
    execute_query(
        """
        CREATE TABLE IF NOT EXISTS task_completion_times (
            id SERIAL PRIMARY KEY,
            task_id INT REFERENCES tasks(id) ON DELETE SET NULL,
            task_description VARCHAR(500),
            task_category VARCHAR(100),
            estimated_minutes INT,
            actual_minutes INT,
            completed_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
        """
    )
    execute_query(
        """
        CREATE INDEX IF NOT EXISTS idx_daily_schedules_date
        ON daily_schedules(date DESC, generated_at DESC)
        """
    )
    execute_query(
        """
        CREATE INDEX IF NOT EXISTS idx_task_time_estimates_category
        ON task_time_estimates(category, last_updated DESC)
        """
    )
    execute_query(
        """
        CREATE INDEX IF NOT EXISTS idx_task_completion_times_category
        ON task_completion_times(task_category, completed_at DESC)
        """
    )
    for task_pattern, category, estimated_minutes in BASELINE_TASK_TIME_ESTIMATES:
        execute_query(
            """
            INSERT INTO task_time_estimates (task_pattern, category, estimated_minutes, sample_count)
            VALUES (%s, %s, %s, 0)
            ON CONFLICT (task_pattern) DO NOTHING
            """,
            (task_pattern, category, int(estimated_minutes)),
        )


def ensure_daily_plan_tables() -> None:
    execute_query(
        """
        CREATE TABLE IF NOT EXISTS daily_plans (
            id SERIAL PRIMARY KEY,
            plan_date DATE UNIQUE NOT NULL,
            generated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            status VARCHAR(20) DEFAULT 'ready',
            estimated_end_time TIMESTAMP,
            total_tasks INT DEFAULT 0,
            total_work_minutes INT DEFAULT 0,
            summary JSONB DEFAULT '{}'::jsonb,
            payload JSONB DEFAULT '{}'::jsonb,
            sent_sms BOOLEAN DEFAULT FALSE,
            sent_email BOOLEAN DEFAULT FALSE,
            sms_sid VARCHAR(120),
            email_message_id VARCHAR(255),
            send_error TEXT,
            calendar_synced BOOLEAN DEFAULT FALSE,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
        """
    )
    execute_query(
        """
        CREATE TABLE IF NOT EXISTS daily_plan_blocks (
            id SERIAL PRIMARY KEY,
            plan_id INT REFERENCES daily_plans(id) ON DELETE CASCADE,
            block_key VARCHAR(80),
            title TEXT NOT NULL,
            tier VARCHAR(30),
            color VARCHAR(20),
            focus VARCHAR(40),
            start_time TIMESTAMP,
            end_time TIMESTAMP,
            duration_minutes INT DEFAULT 0,
            display_order INT DEFAULT 999,
            source_data JSONB DEFAULT '{}'::jsonb,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
        """
    )
    execute_query(
        """
        CREATE TABLE IF NOT EXISTS daily_plan_items (
            id SERIAL PRIMARY KEY,
            plan_id INT REFERENCES daily_plans(id) ON DELETE CASCADE,
            block_id INT REFERENCES daily_plan_blocks(id) ON DELETE CASCADE,
            task_id INT REFERENCES tasks(id) ON DELETE SET NULL,
            transaction_id INT REFERENCES transactions(id) ON DELETE SET NULL,
            title TEXT NOT NULL,
            details TEXT,
            category VARCHAR(60),
            priority_tier VARCHAR(30) DEFAULT 'routine',
            estimated_minutes INT DEFAULT 10,
            actual_minutes INT,
            best_time VARCHAR(20),
            batch_key VARCHAR(120),
            status VARCHAR(20) DEFAULT 'pending',
            display_order INT DEFAULT 999,
            started_at TIMESTAMP,
            completed_at TIMESTAMP,
            deferred BOOLEAN DEFAULT FALSE,
            notes TEXT,
            source_data JSONB DEFAULT '{}'::jsonb,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
        """
    )
    execute_query(
        """
        CREATE TABLE IF NOT EXISTS daily_plan_learning_events (
            id SERIAL PRIMARY KEY,
            plan_id INT REFERENCES daily_plans(id) ON DELETE CASCADE,
            item_id INT REFERENCES daily_plan_items(id) ON DELETE SET NULL,
            event_type VARCHAR(50) NOT NULL,
            event_payload JSONB DEFAULT '{}'::jsonb,
            created_by VARCHAR(100),
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
        """
    )
    execute_query(
        """
        CREATE INDEX IF NOT EXISTS idx_daily_plans_plan_date
        ON daily_plans(plan_date DESC, generated_at DESC)
        """
    )
    execute_query(
        """
        CREATE INDEX IF NOT EXISTS idx_daily_plan_blocks_plan
        ON daily_plan_blocks(plan_id, display_order, id)
        """
    )
    execute_query(
        """
        CREATE INDEX IF NOT EXISTS idx_daily_plan_items_plan
        ON daily_plan_items(plan_id, status, display_order, id)
        """
    )
    execute_query(
        """
        CREATE INDEX IF NOT EXISTS idx_daily_plan_learning_events_plan
        ON daily_plan_learning_events(plan_id, event_type, created_at DESC)
        """
    )
    ensure_daily_schedule_management_tables()


def get_all_open_tasks(limit: int = 500) -> list[dict[str, Any]]:
    rows = execute_query(
        """
        SELECT
            tk.id,
            tk.transaction_id,
            tk.task_description,
            tk.task_category,
            tk.priority,
            tk.due_date,
            tk.notes,
            tk.display_order,
            t.property_address,
            t.status AS transaction_status,
            t.closing_date,
            t.agent_name,
            t.agent_phone
        FROM tasks tk
        JOIN transactions t ON t.id = tk.transaction_id
        WHERE COALESCE(t.status, '') IN ('ACTIVE', 'NEEDS_MARGARET_REVIEW')
          AND tk.completed = FALSE
          AND COALESCE(tk.status, 'pending') <> 'completed'
        ORDER BY tk.due_date ASC NULLS LAST, tk.display_order ASC NULLS LAST, tk.id ASC
        LIMIT %s
        """,
        (max(50, min(int(limit or 500), 1200)),),
        fetch=True,
    ) or []
    return rows


def get_closing_today() -> list[dict[str, Any]]:
    rows = execute_query(
        """
        SELECT id, property_address, agent_name, agent_phone, closing_date
        FROM transactions
        WHERE status = 'ACTIVE'
          AND closing_date = %s
        ORDER BY id ASC
        """,
        (date.today(),),
        fetch=True,
    ) or []
    return rows


def get_closing_this_week() -> list[dict[str, Any]]:
    rows = execute_query(
        """
        SELECT id, property_address, agent_name, agent_phone, closing_date
        FROM transactions
        WHERE status = 'ACTIVE'
          AND closing_date >= %s
          AND closing_date <= %s
        ORDER BY closing_date ASC, id ASC
        """,
        (date.today(), date.today() + timedelta(days=7)),
        fetch=True,
    ) or []
    return rows


def get_urgent_transactions(limit: int = 40) -> list[dict[str, Any]]:
    rows = execute_query(
        """
        WITH latest_urgent AS (
            SELECT DISTINCT ON (pdr.transaction_id)
                pdr.transaction_id,
                pdr.bucket,
                pdr.health_score,
                pdr.issues,
                pdr.created_at
            FROM problem_detection_results pdr
            JOIN transactions t ON t.id = pdr.transaction_id
            WHERE pdr.status = 'open'
              AND pdr.bucket = 'urgent'
              AND t.status = 'ACTIVE'
            ORDER BY pdr.transaction_id, pdr.created_at DESC
        )
        SELECT
            lu.transaction_id,
            lu.bucket,
            lu.health_score,
            lu.issues,
            lu.created_at,
            t.property_address,
            t.agent_name,
            t.agent_phone
        FROM latest_urgent lu
        JOIN transactions t ON t.id = lu.transaction_id
        ORDER BY lu.created_at DESC
        LIMIT %s
        """,
        (max(5, min(int(limit or 40), 120)),),
        fetch=True,
    ) or []
    for row in rows:
        row["issues"] = _parse_json_field(row.get("issues"), [])
    return rows


def get_contracts_need_review(limit: int = 40) -> list[dict[str, Any]]:
    rows = execute_query(
        """
        SELECT id, property_address, agent_name, agent_phone, created_at
        FROM transactions
        WHERE status = 'NEEDS_MARGARET_REVIEW'
        ORDER BY created_at ASC
        LIMIT %s
        """,
        (max(5, min(int(limit or 40), 120)),),
        fetch=True,
    ) or []
    return rows


def get_routine_transactions(limit: int = 120) -> list[dict[str, Any]]:
    rows = execute_query(
        """
        SELECT id, property_address, agent_name, agent_phone, closing_date
        FROM transactions
        WHERE status = 'ACTIVE'
          AND (
                closing_date IS NULL
                OR closing_date > %s
              )
        ORDER BY closing_date ASC NULLS LAST, id ASC
        LIMIT %s
        """,
        (date.today() + timedelta(days=7), max(10, min(int(limit or 120), 300))),
        fetch=True,
    ) or []
    return rows


def serialize_task(task: dict[str, Any]) -> dict[str, Any]:
    due_date = task.get("due_date")
    days_until_due = (due_date - date.today()).days if isinstance(due_date, date) else None
    return {
        "task_id": int(task.get("id") or 0),
        "transaction_id": task.get("transaction_id"),
        "property_address": _safe_text(task.get("property_address")),
        "task_description": _safe_text(task.get("task_description")),
        "task_category": _safe_text(task.get("task_category"), "general"),
        "priority": _safe_text(task.get("priority"), "medium"),
        "due_date": due_date.isoformat() if isinstance(due_date, date) else "",
        "days_until_due": days_until_due,
        "notes": _safe_text(task.get("notes")),
        "agent_phone": _safe_text(task.get("agent_phone")),
    }


def _load_task_time_estimates(force_refresh: bool = False) -> list[dict[str, Any]]:
    cached_rows = TASK_ESTIMATE_CACHE.get("rows") or []
    cached_at = TASK_ESTIMATE_CACHE.get("loaded_at")
    if (
        not force_refresh
        and cached_rows
        and isinstance(cached_at, datetime)
        and (datetime.now() - cached_at).total_seconds() < 900
    ):
        return cached_rows
    rows = execute_query(
        """
        SELECT task_pattern, category, estimated_minutes, actual_minutes_avg, sample_count
        FROM task_time_estimates
        ORDER BY sample_count DESC, last_updated DESC, id DESC
        """,
        fetch=True,
    ) or []
    TASK_ESTIMATE_CACHE["rows"] = rows
    TASK_ESTIMATE_CACHE["loaded_at"] = datetime.now()
    return rows


def _estimate_minutes_from_table(serialized_task: dict[str, Any]) -> int | None:
    description = _safe_text(serialized_task.get("task_description")).lower()
    category = _safe_text(serialized_task.get("task_category")).lower()
    if not description and not category:
        return None

    best_score = 0
    best_minutes = None
    for row in _load_task_time_estimates():
        pattern = _safe_text(row.get("task_pattern")).lower()
        row_category = _safe_text(row.get("category")).lower()
        score = 0
        if category and row_category and category == row_category:
            score += 4
        if pattern and description:
            if pattern in description:
                score += 8
            elif description in pattern:
                score += 4
            else:
                tokens = [token for token in re.split(r"[^a-z0-9]+", pattern) if len(token) >= 4]
                overlap = sum(1 for token in tokens if token in description)
                score += min(overlap, 3)

        if score <= best_score:
            continue
        raw_minutes = row.get("actual_minutes_avg")
        if raw_minutes in (None, "", 0):
            raw_minutes = row.get("estimated_minutes")
        try:
            minutes = int(raw_minutes)
        except (TypeError, ValueError):
            continue
        best_score = score
        best_minutes = minutes

    if best_score < 4 or best_minutes is None:
        return None
    return max(3, min(int(best_minutes), 120))


def _estimated_minutes_for_task(serialized_task: dict[str, Any]) -> int:
    learned_estimate = _estimate_minutes_from_table(serialized_task)
    if learned_estimate is not None:
        return learned_estimate

    category = _safe_text(serialized_task.get("task_category")).lower()
    description = _safe_text(serialized_task.get("task_description")).lower()
    base = 10
    if any(token in description for token in ("call", "phone", "text", "email", "follow up")):
        base = 8
    elif category in {"documents", "document", "review"}:
        base = 14
    elif category in {"closing", "pre_closing"}:
        base = 16
    elif category in {"coordination"}:
        base = 12
    priority = _safe_text(serialized_task.get("priority"), "medium").lower()
    if priority == "high":
        base += 4
    if priority == "low":
        base = max(5, base - 2)
    return max(5, min(base, 60))


def _best_time_for_task(serialized_task: dict[str, Any]) -> str:
    description = _safe_text(serialized_task.get("task_description")).lower()
    if any(token in description for token in ("call", "phone", "text", "follow up")):
        return "morning"
    if any(token in description for token in ("review", "documents", "upload", "checklist")):
        return "afternoon"
    return "anytime"


def _batch_key_for_task(serialized_task: dict[str, Any]) -> str:
    category = _safe_text(serialized_task.get("task_category"), "general").lower().replace(" ", "_")
    tx_id = serialized_task.get("transaction_id")
    if tx_id:
        return f"txn_{int(tx_id)}"
    return f"cat_{category}"


def _synthetic_priorities_from_transactions(transactions: dict[str, list[dict[str, Any]]]) -> list[dict[str, Any]]:
    synthetic = []
    for row in transactions.get("closing_today") or []:
        synthetic.append(
            {
                "task_id": None,
                "transaction_id": row.get("id"),
                "property_address": _safe_text(row.get("property_address")),
                "task_description": f"Closing-day coordination for {row.get('property_address')}",
                "task_category": "closing",
                "priority": "high",
                "due_date": date.today().isoformat(),
                "days_until_due": 0,
                "notes": "Confirm funds, docs, and key handoff are on track.",
                "agent_phone": _safe_text(row.get("agent_phone")),
                "source_type": "closing_today",
            }
        )
    for row in transactions.get("urgent_issues") or []:
        issue_line = ""
        if isinstance(row.get("issues"), list) and row["issues"]:
            first_issue = row["issues"][0]
            if isinstance(first_issue, dict):
                issue_line = _safe_text(first_issue.get("details"))
            else:
                issue_line = _safe_text(first_issue)
        synthetic.append(
            {
                "task_id": None,
                "transaction_id": row.get("transaction_id"),
                "property_address": _safe_text(row.get("property_address")),
                "task_description": f"Urgent issue: {row.get('property_address')}",
                "task_category": "urgent",
                "priority": "high",
                "due_date": date.today().isoformat(),
                "days_until_due": 0,
                "notes": issue_line or "Urgent issue requires immediate attention.",
                "agent_phone": _safe_text(row.get("agent_phone")),
                "source_type": "urgent_issue",
            }
        )
    for row in transactions.get("new_contracts") or []:
        synthetic.append(
            {
                "task_id": None,
                "transaction_id": row.get("id"),
                "property_address": _safe_text(row.get("property_address")),
                "task_description": f"Review new contract intake for {row.get('property_address')}",
                "task_category": "contract_review",
                "priority": "high",
                "due_date": date.today().isoformat(),
                "days_until_due": 0,
                "notes": "Needs review and activation decision.",
                "agent_phone": _safe_text(row.get("agent_phone")),
                "source_type": "new_contract",
            }
        )
    return synthetic


def _fallback_categorization(
    serialized_tasks: list[dict[str, Any]],
    transactions: dict[str, list[dict[str, Any]]],
) -> dict[str, list[dict[str, Any]]]:
    categorized = {
        "critical": [],
        "high_priority": [],
        "batch_able": [],
        "routine": [],
        "delegate_automate": [],
    }
    closing_today_ids = {int(row.get("id")) for row in transactions.get("closing_today") or [] if row.get("id")}
    urgent_ids = {
        int(row.get("transaction_id"))
        for row in transactions.get("urgent_issues") or []
        if row.get("transaction_id")
    }
    review_ids = {int(row.get("id")) for row in transactions.get("new_contracts") or [] if row.get("id")}

    for task in serialized_tasks:
        due_in = task.get("days_until_due")
        tx_id = int(task.get("transaction_id") or 0) if task.get("transaction_id") else None
        description = _safe_text(task.get("task_description")).lower()
        category = _safe_text(task.get("task_category"), "general").lower()
        source_type = _safe_text(task.get("source_type"))
        priority = _safe_text(task.get("priority"), "medium").lower()

        estimated = int(task.get("estimated_minutes") or _estimated_minutes_for_task(task))
        best_time = _safe_text(task.get("best_time"), _best_time_for_task(task))
        batch_key = _safe_text(task.get("batch_key"), _batch_key_for_task(task))
        item = {
            "task_id": task.get("task_id"),
            "transaction_id": tx_id,
            "property_address": task.get("property_address"),
            "title": task.get("task_description"),
            "details": task.get("notes") or "",
            "category": category,
            "estimated_minutes": estimated,
            "best_time": best_time,
            "batch_key": batch_key,
            "priority": priority,
            "source_type": source_type or "task",
        }

        is_critical = (
            source_type in {"closing_today", "urgent_issue"}
            or (tx_id in closing_today_ids if tx_id else False)
            or (tx_id in urgent_ids if tx_id else False)
            or (isinstance(due_in, int) and due_in <= 0)
        )
        is_high = (
            source_type == "new_contract"
            or (tx_id in review_ids if tx_id else False)
            or (isinstance(due_in, int) and due_in <= 2)
            or priority == "high"
        )
        is_batch = (
            any(token in description for token in ("call", "email", "text", "follow up", "upload", "document"))
            or category in {"documents", "communication", "coordination"}
        )
        is_delegate = any(
            token in description
            for token in (
                "archive",
                "copy data",
                "manual duplicate entry",
                "status ping",
                "resend same message",
            )
        )

        if is_critical:
            item["priority_tier"] = "critical"
            categorized["critical"].append(item)
        elif is_high:
            item["priority_tier"] = "high_priority"
            categorized["high_priority"].append(item)
        elif is_delegate:
            item["priority_tier"] = "delegate_automate"
            categorized["delegate_automate"].append(item)
        elif is_batch:
            item["priority_tier"] = "batch_able"
            categorized["batch_able"].append(item)
        else:
            item["priority_tier"] = "routine"
            categorized["routine"].append(item)
    return categorized


def _map_ai_items_to_tasks(
    ai_items: list[dict[str, Any]],
    task_lookup: dict[str, dict[str, Any]],
    fallback_tier: str,
) -> list[dict[str, Any]]:
    mapped = []
    for row in ai_items or []:
        if not isinstance(row, dict):
            continue
        key_candidates = [
            _safe_text(row.get("task_id")),
            _safe_text(row.get("id")),
            _safe_text(row.get("taskId")),
        ]
        task = None
        for key in key_candidates:
            if key and key in task_lookup:
                task = task_lookup[key]
                break
        if task is None:
            title = _safe_text(row.get("title") or row.get("task_description"))
            for candidate in task_lookup.values():
                if _safe_text(candidate.get("task_description")).lower() == title.lower():
                    task = candidate
                    break
        if task is None:
            continue

        item = {
            "task_id": task.get("task_id"),
            "transaction_id": task.get("transaction_id"),
            "property_address": task.get("property_address"),
            "title": _safe_text(task.get("task_description")),
            "details": _safe_text(task.get("notes") or row.get("details")),
            "category": _safe_text(task.get("task_category"), "general").lower(),
            "estimated_minutes": int(row.get("estimated_minutes") or _estimated_minutes_for_task(task)),
            "best_time": _safe_text(row.get("best_time"), _best_time_for_task(task)),
            "batch_key": _safe_text(row.get("batch_key"), _batch_key_for_task(task)),
            "priority": _safe_text(task.get("priority"), "medium").lower(),
            "source_type": _safe_text(task.get("source_type"), "task"),
            "priority_tier": fallback_tier,
        }
        mapped.append(item)
    return mapped


def categorize_tasks_with_ai(
    tasks: list[dict[str, Any]],
    transactions: dict[str, list[dict[str, Any]]],
) -> dict[str, list[dict[str, Any]]]:
    """
    Use Claude to intelligently categorize and prioritize tasks.
    Falls back to deterministic categorization if AI output is unavailable.
    """
    serialized_tasks = [serialize_task(task) for task in tasks]
    synthetic = _synthetic_priorities_from_transactions(transactions)
    all_tasks = serialized_tasks + synthetic
    for task in all_tasks:
        task["estimated_minutes"] = int(task.get("estimated_minutes") or _estimated_minutes_for_task(task))
        task["best_time"] = _safe_text(task.get("best_time"), _best_time_for_task(task))
        task["batch_key"] = _safe_text(task.get("batch_key"), _batch_key_for_task(task))

    fallback = _fallback_categorization(all_tasks, transactions)
    api_key = (os.getenv("ANTHROPIC_API_KEY") or "").strip()
    if not api_key:
        return fallback

    try:
        from anthropic import Anthropic
    except Exception:
        return fallback

    context = {
        "tasks": all_tasks[:350],
        "closing_today_count": len(transactions.get("closing_today") or []),
        "urgent_issues_count": len(transactions.get("urgent_issues") or []),
        "new_contracts_count": len(transactions.get("new_contracts") or []),
        "current_time": datetime.now().strftime("%I:%M %p"),
        "day_of_week": datetime.now().strftime("%A"),
    }
    prompt = f"""You are organizing tasks for Margaret, a transaction coordinator.

Current situation:
- {context['closing_today_count']} closings today
- {context['urgent_issues_count']} urgent issues
- {context['new_contracts_count']} new contracts to review
- {len(all_tasks)} total open tasks

Tasks to organize:
{json.dumps(context['tasks'], indent=2, default=str)}

Categorize tasks into these priority tiers:
1) critical
2) high_priority
3) batch_able
4) routine
5) delegate_automate

For each task return:
- task_id
- estimated_minutes
- best_time ("morning"|"afternoon"|"anytime")
- batch_key

Return ONLY valid JSON:
{{
  "critical":[{{"task_id":"...","estimated_minutes":10,"best_time":"morning","batch_key":"..."}}],
  "high_priority":[...],
  "batch_able":[...],
  "routine":[...],
  "delegate_automate":[...]
}}
"""
    try:
        client = Anthropic(api_key=api_key)
        response = client.messages.create(
            model=(os.getenv("DAILY_PLAN_MODEL") or "claude-sonnet-4-20250514").strip(),
            max_tokens=3200,
            temperature=0,
            messages=[{"role": "user", "content": prompt}],
        )
        text_parts = []
        for chunk in getattr(response, "content", []) or []:
            text = getattr(chunk, "text", "")
            if text:
                text_parts.append(text)
        parsed = _extract_json_object("\n".join(text_parts))
        if not isinstance(parsed, dict):
            return fallback

        task_lookup = {}
        for task in all_tasks:
            key = _safe_text(task.get("task_id"))
            if key:
                task_lookup[key] = task
        ai_result = {}
        for tier in ("critical", "high_priority", "batch_able", "routine", "delegate_automate"):
            tier_rows = parsed.get(tier)
            if not isinstance(tier_rows, list):
                tier_rows = []
            ai_result[tier] = _map_ai_items_to_tasks(tier_rows, task_lookup, tier)

        # Preserve any tasks AI omitted by appending fallback leftovers.
        seen_pairs = {
            (row.get("task_id"), row.get("title"))
            for tier_rows in ai_result.values()
            for row in tier_rows
        }
        for tier, rows in fallback.items():
            for row in rows:
                marker = (row.get("task_id"), row.get("title"))
                if marker in seen_pairs:
                    continue
                ai_result[tier].append(row)
                seen_pairs.add(marker)
        return ai_result
    except Exception as exc:
        log(f"AI categorization fallback: {exc}")
        return fallback


def group_similar_tasks(tasks: list[dict[str, Any]]) -> dict[str, list[dict[str, Any]]]:
    grouped: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for row in tasks or []:
        key = _safe_text(row.get("batch_key")) or _safe_text(row.get("category")) or "General"
        if key.startswith("txn_"):
            label = f"Transaction {key.replace('txn_', '#')}"
        elif key.startswith("cat_"):
            label = key.replace("cat_", "").replace("_", " ").title()
        else:
            label = key.replace("_", " ").title()
        grouped[label].append(row)
    return dict(grouped)


def create_efficient_batches(batch_tasks: list[dict[str, Any]]) -> list[dict[str, Any]]:
    grouped = group_similar_tasks(batch_tasks)
    batches = []
    for label, rows in grouped.items():
        duration = sum(int(row.get("estimated_minutes") or 10) for row in rows)
        batches.append(
            {
                "title": f"Batch: {label}",
                "duration": max(10, duration),
                "tasks": rows,
            }
        )
    batches.sort(key=lambda item: item["duration"], reverse=True)
    return batches


def _block_payload(
    start_time: datetime,
    duration_minutes: int,
    title: str,
    tasks: list[dict[str, Any]],
    color: str,
    tier: str,
    focus: str = "",
) -> dict[str, Any]:
    duration = max(0, int(duration_minutes or 0))
    return {
        "start_time": start_time,
        "end_time": start_time + timedelta(minutes=duration),
        "title": _safe_text(title, "Time Block"),
        "tasks": tasks or [],
        "color": _safe_text(color, "gray"),
        "tier": _safe_text(tier, "routine"),
        "focus": _safe_text(focus),
        "duration_minutes": duration,
    }


def create_time_blocks(categorized_tasks: dict[str, list[dict[str, Any]]]) -> dict[str, Any]:
    """
    Create optimized time blocks for the day.
    """
    schedule_blocks: list[dict[str, Any]] = []
    current_time = datetime.now().replace(hour=8, minute=0, second=0, microsecond=0)

    critical = categorized_tasks.get("critical") or []
    if critical:
        block_duration = sum(int(task.get("estimated_minutes") or 10) for task in critical)
        schedule_blocks.append(
            _block_payload(
                start_time=current_time,
                duration_minutes=block_duration,
                title=f"CRITICAL ITEMS ({len(critical)} tasks)",
                tasks=critical,
                color="red",
                tier="critical",
                focus="urgent",
            )
        )
        current_time += timedelta(minutes=block_duration)

    high_priority = categorized_tasks.get("high_priority") or []
    if high_priority:
        grouped = group_similar_tasks(high_priority)
        for group_name, group_tasks in grouped.items():
            block_duration = sum(int(task.get("estimated_minutes") or 10) for task in group_tasks)
            schedule_blocks.append(
                _block_payload(
                    start_time=current_time,
                    duration_minutes=block_duration,
                    title=f"{group_name} ({len(group_tasks)} tasks)",
                    tasks=group_tasks,
                    color="orange",
                    tier="high_priority",
                )
            )
            current_time += timedelta(minutes=block_duration)

    if 10 <= current_time.hour < 11:
        schedule_blocks.append(
            _block_payload(
                start_time=current_time,
                duration_minutes=15,
                title="BREAK",
                tasks=[],
                color="green",
                tier="break",
            )
        )
        current_time += timedelta(minutes=15)

    batch_able = categorized_tasks.get("batch_able") or []
    if batch_able:
        batches = create_efficient_batches(batch_able)
        for batch in batches:
            schedule_blocks.append(
                _block_payload(
                    start_time=current_time,
                    duration_minutes=int(batch.get("duration") or 10),
                    title=batch.get("title") or "Batch Work",
                    tasks=batch.get("tasks") or [],
                    color="blue",
                    tier="batch_able",
                )
            )
            current_time += timedelta(minutes=int(batch.get("duration") or 10))

    if current_time.hour < 12:
        current_time = current_time.replace(hour=12, minute=0)
    schedule_blocks.append(
        _block_payload(
            start_time=current_time,
            duration_minutes=60,
            title="LUNCH",
            tasks=[],
            color="green",
            tier="break",
        )
    )
    current_time += timedelta(hours=1)

    routine = categorized_tasks.get("routine") or []
    if routine:
        routine_minutes = sum(int(task.get("estimated_minutes") or 10) for task in routine)
        block_duration = min(routine_minutes, 120)
        limited_tasks = []
        spent = 0
        for task in routine:
            task_minutes = int(task.get("estimated_minutes") or 10)
            if spent + task_minutes > block_duration and limited_tasks:
                break
            limited_tasks.append(task)
            spent += task_minutes
        schedule_blocks.append(
            _block_payload(
                start_time=current_time,
                duration_minutes=block_duration,
                title=f"ROUTINE TASKS ({len(limited_tasks)} tasks)",
                tasks=limited_tasks,
                color="gray",
                tier="routine",
            )
        )
        current_time += timedelta(minutes=block_duration)

    schedule_blocks.append(
        _block_payload(
            start_time=current_time,
            duration_minutes=30,
            title="BUFFER TIME",
            tasks=[],
            color="purple",
            tier="buffer",
            focus="slack",
        )
    )
    estimated_end = current_time + timedelta(minutes=30)
    start_anchor = schedule_blocks[0]["start_time"] if schedule_blocks else datetime.now().replace(hour=8, minute=0, second=0)
    total_tasks = (
        len(categorized_tasks.get("critical") or [])
        + len(categorized_tasks.get("high_priority") or [])
        + len(categorized_tasks.get("batch_able") or [])
        + len(categorized_tasks.get("routine") or [])
        + len(categorized_tasks.get("delegate_automate") or [])
    )
    return {
        "blocks": schedule_blocks,
        "estimated_end_time": estimated_end,
        "total_tasks": total_tasks,
        "total_work_hours": round((estimated_end - start_anchor).seconds / 3600.0, 2),
        "delegate_suggestions": categorized_tasks.get("delegate_automate", []),
        "categorized_tasks": categorized_tasks,
    }


def _hydrate_plan_row(row: dict[str, Any] | None) -> dict[str, Any] | None:
    if not row:
        return None
    hydrated = dict(row)
    hydrated["summary"] = _parse_json_field(row.get("summary"), {})
    hydrated["payload"] = _parse_json_field(row.get("payload"), {})
    return hydrated


def fetch_daily_plan_by_date(plan_date: date | str) -> dict[str, Any] | None:
    ensure_daily_plan_tables()
    target = plan_date.isoformat() if isinstance(plan_date, date) else _safe_text(plan_date)
    rows = execute_query(
        """
        SELECT *
        FROM daily_plans
        WHERE plan_date = %s
        LIMIT 1
        """,
        (target,),
        fetch=True,
    ) or []
    return _hydrate_plan_row(rows[0] if rows else None)


def fetch_latest_daily_plan(days_back: int = 21) -> dict[str, Any] | None:
    ensure_daily_plan_tables()
    start_date = date.today() - timedelta(days=max(1, int(days_back or 21)))
    rows = execute_query(
        """
        SELECT *
        FROM daily_plans
        WHERE plan_date >= %s
        ORDER BY plan_date DESC, generated_at DESC, id DESC
        LIMIT 1
        """,
        (start_date,),
        fetch=True,
    ) or []
    return _hydrate_plan_row(rows[0] if rows else None)


def fetch_daily_plan_blocks(plan_id: int) -> list[dict[str, Any]]:
    ensure_daily_plan_tables()
    rows = execute_query(
        """
        SELECT
            id, plan_id, block_key, title, tier, color, focus,
            start_time, end_time, duration_minutes, display_order, source_data, created_at, updated_at
        FROM daily_plan_blocks
        WHERE plan_id = %s
        ORDER BY display_order ASC, id ASC
        """,
        (int(plan_id),),
        fetch=True,
    ) or []
    for row in rows:
        row["source_data"] = _parse_json_field(row.get("source_data"), {})
    return rows


def fetch_daily_plan_items(plan_id: int, include_completed: bool = True) -> list[dict[str, Any]]:
    ensure_daily_plan_tables()
    filters = ["plan_id = %s"]
    params = [int(plan_id)]
    if not include_completed:
        filters.append("status <> 'completed'")
    rows = execute_query(
        f"""
        SELECT
            id, plan_id, block_id, task_id, transaction_id, title, details, category, priority_tier,
            estimated_minutes, actual_minutes, best_time, batch_key, status, display_order,
            started_at, completed_at, deferred, notes, source_data, created_at, updated_at
        FROM daily_plan_items
        WHERE {' AND '.join(filters)}
        ORDER BY display_order ASC, id ASC
        """,
        tuple(params),
        fetch=True,
    ) or []
    for row in rows:
        row["source_data"] = _parse_json_field(row.get("source_data"), {})
    return rows


def _upsert_plan_row(
    plan_date: date,
    schedule: dict[str, Any],
    transactions: dict[str, list[dict[str, Any]]],
) -> dict[str, Any]:
    summary = {
        "closing_today_count": len(transactions.get("closing_today") or []),
        "closing_this_week_count": len(transactions.get("closing_this_week") or []),
        "urgent_issues_count": len(transactions.get("urgent_issues") or []),
        "new_contracts_count": len(transactions.get("new_contracts") or []),
        "routine_count": len(transactions.get("routine") or []),
        "delegate_suggestions_count": len(schedule.get("delegate_suggestions") or []),
    }
    rows = execute_query(
        """
        INSERT INTO daily_plans (
            plan_date,
            generated_at,
            status,
            estimated_end_time,
            total_tasks,
            total_work_minutes,
            summary,
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
            %s::jsonb,
            %s::jsonb,
            CURRENT_TIMESTAMP
        )
        ON CONFLICT (plan_date)
        DO UPDATE SET
            generated_at = CURRENT_TIMESTAMP,
            status = 'ready',
            estimated_end_time = EXCLUDED.estimated_end_time,
            total_tasks = EXCLUDED.total_tasks,
            total_work_minutes = EXCLUDED.total_work_minutes,
            summary = EXCLUDED.summary,
            payload = EXCLUDED.payload,
            updated_at = CURRENT_TIMESTAMP
        RETURNING *
        """,
        (
            plan_date,
            schedule.get("estimated_end_time"),
            int(schedule.get("total_tasks") or 0),
            int(round(float(schedule.get("total_work_hours") or 0) * 60)),
            _json_dumps(summary),
            _json_dumps(
                {
                    "blocks": [
                        {
                            "title": block.get("title"),
                            "tier": block.get("tier"),
                            "color": block.get("color"),
                            "start_time": block.get("start_time"),
                            "end_time": block.get("end_time"),
                            "duration_minutes": block.get("duration_minutes"),
                            "task_count": len(block.get("tasks") or []),
                        }
                        for block in (schedule.get("blocks") or [])
                    ],
                    "delegate_suggestions": schedule.get("delegate_suggestions") or [],
                }
            ),
        ),
        fetch=True,
    ) or []
    if not rows:
        raise RuntimeError("Failed to save daily plan row.")
    return _hydrate_plan_row(rows[0]) or {}


def _upsert_daily_schedule_row(plan_date: date, schedule: dict[str, Any]) -> None:
    """Persist schedule JSON into requested daily_schedules compatibility table."""
    ensure_daily_schedule_management_tables()
    estimated_end_time = schedule.get("estimated_end_time")
    estimated_end_clock = estimated_end_time.time() if isinstance(estimated_end_time, datetime) else None
    payload = dict(schedule or {})
    payload["date"] = plan_date.isoformat()
    execute_query(
        """
        INSERT INTO daily_schedules (
            date,
            generated_at,
            total_tasks,
            estimated_work_hours,
            estimated_end_time,
            schedule_data
        )
        VALUES (
            %s,
            CURRENT_TIMESTAMP,
            %s,
            %s,
            %s,
            %s::jsonb
        )
        ON CONFLICT (date)
        DO UPDATE SET
            generated_at = CURRENT_TIMESTAMP,
            total_tasks = EXCLUDED.total_tasks,
            estimated_work_hours = EXCLUDED.estimated_work_hours,
            estimated_end_time = EXCLUDED.estimated_end_time,
            schedule_data = EXCLUDED.schedule_data
        """,
        (
            plan_date,
            int(schedule.get("total_tasks") or 0),
            float(schedule.get("total_work_hours") or 0.0),
            estimated_end_clock,
            _json_dumps(payload),
        ),
    )


def save_daily_schedule(schedule: dict[str, Any], plan_date: date | None = None) -> bool:
    """Public helper to save schedule snapshots (requested interface)."""
    target_date = plan_date or date.today()
    _upsert_daily_schedule_row(target_date, schedule or {})
    return True


def _replace_plan_blocks(plan_id: int, schedule: dict[str, Any]) -> None:
    execute_query("DELETE FROM daily_plan_items WHERE plan_id = %s", (int(plan_id),))
    execute_query("DELETE FROM daily_plan_blocks WHERE plan_id = %s", (int(plan_id),))

    global_item_order = 1
    for block_index, block in enumerate(schedule.get("blocks") or [], start=1):
        block_rows = execute_query(
            """
            INSERT INTO daily_plan_blocks (
                plan_id, block_key, title, tier, color, focus,
                start_time, end_time, duration_minutes, display_order, source_data, created_at, updated_at
            )
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s::jsonb, CURRENT_TIMESTAMP, CURRENT_TIMESTAMP)
            RETURNING id
            """,
            (
                int(plan_id),
                f"{_safe_text(block.get('tier'), 'block')}_{block_index}",
                _safe_text(block.get("title"), "Time Block"),
                _safe_text(block.get("tier"), "routine"),
                _safe_text(block.get("color"), "gray"),
                _safe_text(block.get("focus")),
                block.get("start_time"),
                block.get("end_time"),
                int(block.get("duration_minutes") or 0),
                block_index,
                _json_dumps(
                    {
                        "task_count": len(block.get("tasks") or []),
                    }
                ),
            ),
            fetch=True,
        )
        block_id = int((block_rows[0] or {}).get("id") or 0) if block_rows else 0
        if not block_id:
            continue

        for task in block.get("tasks") or []:
            execute_query(
                """
                INSERT INTO daily_plan_items (
                    plan_id, block_id, task_id, transaction_id, title, details, category, priority_tier,
                    estimated_minutes, actual_minutes, best_time, batch_key, status, display_order,
                    source_data, created_at, updated_at
                )
                VALUES (
                    %s, %s, %s, %s, %s, %s, %s, %s,
                    %s, NULL, %s, %s, 'pending', %s,
                    %s::jsonb, CURRENT_TIMESTAMP, CURRENT_TIMESTAMP
                )
                """,
                (
                    int(plan_id),
                    int(block_id),
                    int(task.get("task_id")) if task.get("task_id") else None,
                    int(task.get("transaction_id")) if task.get("transaction_id") else None,
                    _safe_text(task.get("title"), "Task")[:600],
                    _safe_text(task.get("details"))[:2000] or None,
                    _safe_text(task.get("category"), "general")[:60],
                    _safe_text(task.get("priority_tier"), block.get("tier") or "routine")[:30],
                    int(task.get("estimated_minutes") or 10),
                    _safe_text(task.get("best_time"), "anytime")[:20],
                    _safe_text(task.get("batch_key"))[:120] or None,
                    global_item_order,
                    _json_dumps(task),
                ),
            )
            global_item_order += 1


def _delete_existing_calendar_blocks(plan_id: int) -> dict[str, int]:
    ensure_calendar_sync_tables()
    rows = execute_query(
        """
        SELECT id, transaction_id, event_type, source_ref, calendar_id, google_event_id
        FROM google_calendar_mappings
        WHERE event_type = 'daily_plan_block'
          AND source_ref LIKE %s
          AND status = 'active'
        ORDER BY id ASC
        """,
        (f"daily_plan:{int(plan_id)}:%",),
        fetch=True,
    ) or []
    deleted = 0
    failed = 0
    for row in rows:
        result = delete_calendar_event_by_mapping(row, reason="daily_plan_regenerate")
        if result.get("success"):
            deleted += 1
        else:
            failed += 1
    return {"deleted": deleted, "failed": failed}


def sync_daily_plan_to_calendar(plan_id: int) -> dict[str, Any]:
    ensure_daily_plan_tables()
    ensure_calendar_sync_tables()
    cleanup = _delete_existing_calendar_blocks(plan_id)
    blocks = fetch_daily_plan_blocks(plan_id)
    block_items = fetch_daily_plan_items(plan_id, include_completed=True)
    items_by_block: dict[int, list[dict[str, Any]]] = defaultdict(list)
    for item in block_items:
        items_by_block[int(item.get("block_id") or 0)].append(item)

    synced = 0
    failed = 0
    for block in blocks:
        start_time = block.get("start_time")
        end_time = block.get("end_time")
        if not isinstance(start_time, datetime) or not isinstance(end_time, datetime):
            continue
        tier = _safe_text(block.get("tier"), "routine")
        color = {
            "critical": "11",
            "high_priority": "6",
            "batch_able": "9",
            "routine": "8",
            "buffer": "3",
            "break": "2",
        }.get(tier, "6")
        items = items_by_block.get(int(block["id"]), [])
        addresses = []
        for item in items:
            address = _safe_text(item.get("source_data", {}).get("property_address") if isinstance(item.get("source_data"), dict) else "")
            if address:
                addresses.append(address)
        summary_suffix = f"({len(items)} tasks)" if items else "(no tasks)"
        description = "\n".join(
            [f"- {_safe_text(item.get('title'))} [{int(item.get('estimated_minutes') or 0)}m]" for item in items[:15]]
        ) or "No tasks assigned."
        source_ref = f"daily_plan:{int(plan_id)}:block:{int(block['id'])}"
        primary_tx_id = next((item.get("transaction_id") for item in items if item.get("transaction_id")), None)
        event_data = {
            "summary_prefix": "DAILY PLAN",
            "property_address": ", ".join(sorted(set(addresses))[:2]) or "Margaret Focus Block",
            "start_time": start_time,
            "end_time": end_time,
            "duration_minutes": int(block.get("duration_minutes") or 0),
            "notes": description[:3000],
            "source_ref": source_ref,
            "source_id": int(block["id"]),
            "source_label": _safe_text(block.get("title")),
            "color_id": color,
            "title": f"{_safe_text(block.get('title'))} {summary_suffix}",
        }
        result = sync_to_calendar(
            event_type="daily_plan_block",
            transaction_id=primary_tx_id,
            event_data=event_data,
            force_update=True,
        )
        if result.get("success"):
            synced += 1
        elif not result.get("skipped"):
            failed += 1

    execute_query(
        """
        UPDATE daily_plans
        SET calendar_synced = %s,
            updated_at = CURRENT_TIMESTAMP
        WHERE id = %s
        """,
        (failed == 0 and synced > 0, int(plan_id)),
    )
    return {
        "success": failed == 0,
        "synced": synced,
        "failed": failed,
        "deleted_previous": cleanup.get("deleted", 0),
        "delete_failed": cleanup.get("failed", 0),
    }


def _format_time_label(value: datetime | None) -> str:
    if not isinstance(value, datetime):
        return ""
    return value.strftime("%I:%M %p").lstrip("0")


def send_daily_plan(schedule: dict[str, Any], plan_date: date | None = None) -> dict[str, Any]:
    """
    Send optimized schedule to Margaret via email and SMS.
    """
    target_date = plan_date or date.today()
    margaret_phone = _normalize_phone(os.getenv("MARGARET_PHONE") or "")
    margaret_email = _normalize_email(os.getenv("MARGARET_EMAIL") or "")
    blocks = schedule.get("blocks") or []
    non_empty_blocks = [block for block in blocks if (block.get("tasks") or [])]
    sms_summary = (
        "📅 TODAY'S PLAN\n\n"
        f"{len(blocks)} time blocks\n"
        f"End time: {_format_time_label(schedule.get('estimated_end_time'))}\n\n"
        "Next 3 priorities:\n"
    )
    for block in non_empty_blocks[:3]:
        sms_summary += (
            f"\n{_format_time_label(block.get('start_time'))} - "
            f"{_safe_text(block.get('title'))}"
        )
    sms_summary += f"\n\nFull plan: {_plan_base_url()}/tc/daily-plan?date={target_date.isoformat()}"
    sms_summary = sms_summary[:500]

    sms_sid = None
    email_message_id = None
    send_error = ""
    try:
        if margaret_phone:
            sms_sid = send_sms(margaret_phone, sms_summary)
    except Exception as exc:
        send_error = f"sms_error:{exc}"

    try:
        if margaret_email:
            email_message_id = send_email(
                to=margaret_email,
                template="emails/daily_plan.html",
                data={
                    "subject": f"Daily Plan - {target_date.strftime('%A, %B %d, %Y')}",
                    "schedule": schedule,
                    "date": target_date.strftime("%A, %B %d, %Y"),
                    "plan_url": f"{_plan_base_url()}/tc/daily-plan?date={target_date.isoformat()}",
                },
            )
    except Exception as exc:
        send_error = f"{send_error}; email_error:{exc}".strip("; ")

    return {
        "sms_sent": bool(sms_sid),
        "email_sent": bool(email_message_id),
        "sms_sid": sms_sid,
        "email_message_id": email_message_id,
        "send_error": send_error,
        "sms_preview": sms_summary,
    }


def generate_daily_plan(force: bool = False, send_messages: bool = True, sync_calendar: bool = True) -> dict[str, Any]:
    """
    Create optimized daily schedule for Margaret.
    Run at 7:00 AM before morning briefing.
    """
    ensure_daily_plan_tables()
    target_date = date.today()
    existing = fetch_daily_plan_by_date(target_date)
    if existing and not force:
        return {"success": True, "reused_existing": True, "plan_id": existing["id"], "plan_date": target_date.isoformat()}

    tasks = get_all_open_tasks()
    transactions = {
        "closing_today": get_closing_today(),
        "closing_this_week": get_closing_this_week(),
        "urgent_issues": get_urgent_transactions(),
        "new_contracts": get_contracts_need_review(),
        "routine": get_routine_transactions(),
    }
    categorized = categorize_tasks_with_ai(tasks, transactions)
    schedule = create_time_blocks(categorized)
    plan_row = _upsert_plan_row(target_date, schedule, transactions)
    _replace_plan_blocks(plan_row["id"], schedule)
    save_daily_schedule(schedule, plan_date=target_date)

    calendar_summary = {"success": False, "synced": 0, "failed": 0}
    if sync_calendar:
        calendar_summary = sync_daily_plan_to_calendar(plan_row["id"])

    delivery = {"sms_sent": False, "email_sent": False}
    if send_messages:
        delivery = send_daily_plan(schedule, plan_date=target_date)
        execute_query(
            """
            UPDATE daily_plans
            SET sent_sms = %s,
                sent_email = %s,
                sms_sid = %s,
                email_message_id = %s,
                send_error = %s,
                updated_at = CURRENT_TIMESTAMP
            WHERE id = %s
            """,
            (
                bool(delivery.get("sms_sent")),
                bool(delivery.get("email_sent")),
                delivery.get("sms_sid"),
                delivery.get("email_message_id"),
                _safe_text(delivery.get("send_error")) or None,
                int(plan_row["id"]),
            ),
        )

    return {
        "success": True,
        "plan_id": plan_row["id"],
        "plan_date": target_date.isoformat(),
        "summary": {
            "total_tasks": schedule.get("total_tasks"),
            "total_work_hours": schedule.get("total_work_hours"),
            "estimated_end_time": _format_time_label(schedule.get("estimated_end_time")),
            "delegate_suggestions": len(schedule.get("delegate_suggestions") or []),
        },
        "delivery": delivery,
        "calendar": calendar_summary,
    }


def _record_learning_event(plan_id: int, item_id: int | None, event_type: str, event_payload: dict[str, Any], created_by: str):
    execute_query(
        """
        INSERT INTO daily_plan_learning_events (
            plan_id, item_id, event_type, event_payload, created_by, created_at
        )
        VALUES (%s, %s, %s, %s::jsonb, %s, CURRENT_TIMESTAMP)
        """,
        (
            int(plan_id),
            int(item_id) if item_id else None,
            _safe_text(event_type)[:50] or "event",
            _json_dumps(event_payload or {}),
            _safe_text(created_by, "margaret")[:100],
        ),
    )


def _record_task_completion_time(item: dict[str, Any], actual_minutes: int | None) -> None:
    ensure_daily_schedule_management_tables()
    estimated = int(item.get("estimated_minutes") or 0)
    measured = int(actual_minutes or 0)
    if measured <= 0:
        measured = estimated
    if measured <= 0:
        return
    execute_query(
        """
        INSERT INTO task_completion_times (
            task_id,
            task_description,
            task_category,
            estimated_minutes,
            actual_minutes,
            completed_at
        )
        VALUES (%s, %s, %s, %s, %s, CURRENT_TIMESTAMP)
        """,
        (
            int(item.get("task_id")) if item.get("task_id") else None,
            _safe_text(item.get("title"), "Task")[:500],
            _safe_text(item.get("category"), "general")[:100],
            estimated if estimated > 0 else None,
            measured,
        ),
    )


def update_daily_plan_item(
    item_id: int,
    status: str | None = None,
    notes: str | None = None,
    actual_minutes: int | None = None,
    started_now: bool = False,
    completed_now: bool = False,
    updated_by: str = "margaret",
) -> dict[str, Any] | None:
    ensure_daily_plan_tables()
    rows = execute_query(
        """
        SELECT *
        FROM daily_plan_items
        WHERE id = %s
        LIMIT 1
        """,
        (int(item_id),),
        fetch=True,
    ) or []
    if not rows:
        return None
    item = rows[0]
    was_completed = _safe_text(item.get("status")).lower() == "completed"
    next_status = _safe_text(status, item.get("status") or "pending").lower()
    if next_status not in {"pending", "completed", "deferred", "skipped"}:
        next_status = "pending"

    start_value = datetime.now() if started_now and not item.get("started_at") else item.get("started_at")
    completed_value = datetime.now() if (completed_now or next_status == "completed") else None
    next_actual = actual_minutes
    if next_actual is None and completed_value and start_value:
        duration_min = int(max(1, (completed_value - start_value).total_seconds() // 60))
        next_actual = duration_min

    execute_query(
        """
        UPDATE daily_plan_items
        SET status = %s,
            notes = %s,
            actual_minutes = %s,
            started_at = %s,
            completed_at = %s,
            updated_at = CURRENT_TIMESTAMP
        WHERE id = %s
        """,
        (
            next_status,
            _safe_text(notes, item.get("notes") or "") or None,
            int(next_actual) if next_actual not in (None, "") else item.get("actual_minutes"),
            start_value,
            completed_value,
            int(item_id),
        ),
    )
    _record_learning_event(
        plan_id=int(item.get("plan_id")),
        item_id=int(item_id),
        event_type="status_change",
        event_payload={
            "from": item.get("status"),
            "to": next_status,
            "estimated_minutes": int(item.get("estimated_minutes") or 0),
            "actual_minutes": int(next_actual or item.get("actual_minutes") or 0) if (next_actual or item.get("actual_minutes")) else None,
        },
        created_by=updated_by,
    )
    just_completed = next_status == "completed" and not was_completed
    if just_completed:
        measured = int(next_actual or item.get("actual_minutes") or 0)
        _record_task_completion_time(item, measured)

    refreshed = execute_query(
        """
        SELECT *
        FROM daily_plan_items
        WHERE id = %s
        LIMIT 1
        """,
        (int(item_id),),
        fetch=True,
    ) or []
    if not refreshed:
        return None
    row = refreshed[0]
    row["source_data"] = _parse_json_field(row.get("source_data"), {})
    return row


def reorder_daily_plan_items(plan_id: int, ordered_item_ids: list[int], updated_by: str = "margaret") -> bool:
    ensure_daily_plan_tables()
    cleaned = []
    seen = set()
    for raw_id in ordered_item_ids or []:
        try:
            value = int(raw_id)
        except (TypeError, ValueError):
            continue
        if value in seen:
            continue
        seen.add(value)
        cleaned.append(value)
    if not cleaned:
        return False

    rows = execute_query(
        """
        SELECT id
        FROM daily_plan_items
        WHERE plan_id = %s
        """,
        (int(plan_id),),
        fetch=True,
    ) or []
    valid_ids = {int(row["id"]) for row in rows}
    order_map = [item_id for item_id in cleaned if item_id in valid_ids]
    if not order_map:
        return False

    for display_order, item_id in enumerate(order_map, start=1):
        execute_query(
            """
            UPDATE daily_plan_items
            SET display_order = %s,
                updated_at = CURRENT_TIMESTAMP
            WHERE id = %s
              AND plan_id = %s
            """,
            (display_order, int(item_id), int(plan_id)),
        )
    _record_learning_event(
        plan_id=int(plan_id),
        item_id=None,
        event_type="reorder",
        event_payload={"item_count": len(order_map)},
        created_by=updated_by,
    )
    return True


def _build_task_from_item(item: dict[str, Any]) -> dict[str, Any]:
    source_data = _parse_json_field(item.get("source_data"), {})
    derived_task_id = int(item.get("task_id") or item.get("id") or 0)
    return {
        "id": derived_task_id,
        "task_id": derived_task_id,
        "transaction_id": item.get("transaction_id"),
        "property_address": source_data.get("property_address") or "",
        "task_description": item.get("title"),
        "task_category": item.get("category"),
        "priority": "high" if _safe_text(item.get("priority_tier")) in {"critical", "high_priority"} else "medium",
        "due_date": "",
        "days_until_due": None,
        "notes": item.get("details") or "",
        "estimated_minutes": item.get("estimated_minutes"),
        "best_time": item.get("best_time"),
        "batch_key": item.get("batch_key"),
        "source_type": "plan_item",
    }


def reorganize_remaining_day(plan_id: int, reason: str = "running_behind", updated_by: str = "margaret") -> dict[str, Any]:
    ensure_daily_plan_tables()
    plan_rows = execute_query(
        """
        SELECT *
        FROM daily_plans
        WHERE id = %s
        LIMIT 1
        """,
        (int(plan_id),),
        fetch=True,
    ) or []
    if not plan_rows:
        return {"success": False, "error": "plan_not_found"}

    remaining = execute_query(
        """
        SELECT *
        FROM daily_plan_items
        WHERE plan_id = %s
          AND status <> 'completed'
        ORDER BY display_order ASC, id ASC
        """,
        (int(plan_id),),
        fetch=True,
    ) or []
    if not remaining:
        return {"success": True, "reordered": 0}

    task_like = [_build_task_from_item(item) for item in remaining]
    transactions = {
        "closing_today": get_closing_today(),
        "closing_this_week": get_closing_this_week(),
        "urgent_issues": get_urgent_transactions(),
        "new_contracts": get_contracts_need_review(),
        "routine": get_routine_transactions(),
    }
    categorized = categorize_tasks_with_ai(task_like, transactions)
    reordered = (
        categorized.get("critical", [])
        + categorized.get("high_priority", [])
        + categorized.get("batch_able", [])
        + categorized.get("routine", [])
        + categorized.get("delegate_automate", [])
    )

    index = 1
    used_ids: set[int] = set()
    for task in reordered:
        matching = next(
            (
                row for row in remaining
                if int(row.get("id") or 0) not in used_ids
                and (
                    (
                        task.get("task_id")
                        and (
                            task.get("task_id") == row.get("task_id")
                            or task.get("task_id") == row.get("id")
                        )
                    )
                    or (_safe_text(task.get("title")).lower() == _safe_text(row.get("title")).lower())
                )
            ),
            None,
        )
        if not matching:
            continue
        execute_query(
            """
            UPDATE daily_plan_items
            SET display_order = %s,
                priority_tier = %s,
                best_time = %s,
                batch_key = %s,
                updated_at = CURRENT_TIMESTAMP
            WHERE id = %s
              AND plan_id = %s
            """,
            (
                index,
                _safe_text(task.get("priority_tier"), matching.get("priority_tier"))[:30],
                _safe_text(task.get("best_time"), matching.get("best_time"))[:20],
                _safe_text(task.get("batch_key"), matching.get("batch_key"))[:120] or None,
                int(matching["id"]),
                int(plan_id),
            ),
        )
        used_ids.add(int(matching["id"]))
        index += 1

    # Keep unmatched rows at the end to preserve visibility while avoiding duplicate orders.
    for row in remaining:
        row_id = int(row.get("id") or 0)
        if not row_id or row_id in used_ids:
            continue
        execute_query(
            """
            UPDATE daily_plan_items
            SET display_order = %s,
                updated_at = CURRENT_TIMESTAMP
            WHERE id = %s
              AND plan_id = %s
            """,
            (index, row_id, int(plan_id)),
        )
        index += 1

    _record_learning_event(
        plan_id=int(plan_id),
        item_id=None,
        event_type="replan",
        event_payload={"reason": _safe_text(reason), "remaining_count": len(remaining)},
        created_by=updated_by,
    )
    remaining_minutes = sum(int(item.get("estimated_minutes") or 0) for item in remaining)
    estimated_end = datetime.now() + timedelta(minutes=remaining_minutes + 30)
    execute_query(
        """
        UPDATE daily_plans
        SET estimated_end_time = %s,
            updated_at = CURRENT_TIMESTAMP
        WHERE id = %s
        """,
        (estimated_end, int(plan_id)),
    )
    return {
        "success": True,
        "reordered": index - 1,
        "estimated_end_time": estimated_end.isoformat(),
        "remaining_minutes": remaining_minutes,
    }


def fetch_daily_plan_learning_metrics(days: int = 30) -> dict[str, Any]:
    ensure_daily_plan_tables()
    start_date = datetime.now() - timedelta(days=max(1, int(days or 30)))
    estimate_rows = execute_query(
        """
        SELECT category, estimated_minutes, actual_minutes
        FROM daily_plan_items
        WHERE completed_at IS NOT NULL
          AND actual_minutes IS NOT NULL
          AND completed_at >= %s
        """,
        (start_date,),
        fetch=True,
    ) or []
    reorder_rows = execute_query(
        """
        SELECT COUNT(*) AS total
        FROM daily_plan_learning_events
        WHERE event_type = 'reorder'
          AND created_at >= %s
        """,
        (start_date,),
        fetch=True,
    ) or []
    replan_rows = execute_query(
        """
        SELECT COUNT(*) AS total
        FROM daily_plan_learning_events
        WHERE event_type = 'replan'
          AND created_at >= %s
        """,
        (start_date,),
        fetch=True,
    ) or []

    total_estimate = 0
    total_actual = 0
    category_buckets: dict[str, dict[str, int]] = defaultdict(lambda: {"estimated": 0, "actual": 0, "count": 0})
    for row in estimate_rows:
        estimated = int(row.get("estimated_minutes") or 0)
        actual = int(row.get("actual_minutes") or 0)
        category = _safe_text(row.get("category"), "general").lower()
        total_estimate += estimated
        total_actual += actual
        category_buckets[category]["estimated"] += estimated
        category_buckets[category]["actual"] += actual
        category_buckets[category]["count"] += 1

    accuracy_pct = 0.0
    if total_estimate > 0 and total_actual > 0:
        diff = abs(total_actual - total_estimate)
        accuracy_pct = max(0.0, 100.0 - ((diff / max(total_estimate, 1)) * 100.0))

    slow_categories = []
    for category, values in category_buckets.items():
        estimated = values["estimated"]
        actual = values["actual"]
        if estimated <= 0 or values["count"] <= 0:
            continue
        ratio = actual / max(estimated, 1)
        if ratio > 1.2:
            slow_categories.append(
                {
                    "category": category,
                    "ratio": round(ratio, 2),
                    "avg_extra_minutes": int((actual - estimated) / max(values["count"], 1)),
                }
            )
    slow_categories.sort(key=lambda item: item["ratio"], reverse=True)

    return {
        "completed_samples": len(estimate_rows),
        "estimate_accuracy_pct": round(accuracy_pct, 1),
        "reorder_events": int((reorder_rows[0] or {}).get("total") or 0) if reorder_rows else 0,
        "replan_events": int((replan_rows[0] or {}).get("total") or 0) if replan_rows else 0,
        "slow_categories": slow_categories[:5],
    }


def update_task_estimates(days_window: int = 30, buffer_ratio: float = 1.1) -> dict[str, Any]:
    """
    Refresh task time estimates from measured completion durations.
    Intended for weekly cron execution.
    """
    ensure_daily_schedule_management_tables()
    safe_days = max(7, min(int(days_window or 30), 120))
    safe_ratio = max(1.0, min(float(buffer_ratio or 1.1), 1.5))
    rows = execute_query(
        """
        SELECT
            task_category,
            AVG(actual_minutes)::float AS avg_actual,
            COUNT(*)::int AS sample_count
        FROM task_completion_times
        WHERE completed_at >= CURRENT_TIMESTAMP - (%s * INTERVAL '1 day')
          AND actual_minutes IS NOT NULL
          AND actual_minutes > 0
        GROUP BY task_category
        ORDER BY sample_count DESC, task_category ASC
        """,
        (safe_days,),
        fetch=True,
    ) or []

    updated_categories = 0
    inserted_categories = 0
    for row in rows:
        category = _safe_text(row.get("task_category"), "general")[:100]
        avg_actual = int(round(float(row.get("avg_actual") or 0)))
        sample_count = max(1, int(row.get("sample_count") or 1))
        if avg_actual <= 0:
            continue
        buffered_estimate = max(2, int(round(avg_actual * safe_ratio)))
        existing = execute_query(
            """
            SELECT id
            FROM task_time_estimates
            WHERE category = %s
            LIMIT 1
            """,
            (category,),
            fetch=True,
        ) or []
        if existing:
            execute_query(
                """
                UPDATE task_time_estimates
                SET actual_minutes_avg = %s,
                    estimated_minutes = %s,
                    sample_count = sample_count + %s,
                    last_updated = CURRENT_TIMESTAMP
                WHERE category = %s
                """,
                (avg_actual, buffered_estimate, sample_count, category),
            )
            updated_categories += 1
        else:
            execute_query(
                """
                INSERT INTO task_time_estimates (
                    task_pattern,
                    category,
                    estimated_minutes,
                    actual_minutes_avg,
                    sample_count,
                    last_updated
                )
                VALUES (%s, %s, %s, %s, %s, CURRENT_TIMESTAMP)
                ON CONFLICT (task_pattern) DO NOTHING
                """,
                (f"Auto-learned {category}", category, buffered_estimate, avg_actual, sample_count),
            )
            inserted_categories += 1

    _load_task_time_estimates(force_refresh=True)
    return {
        "success": True,
        "days_window": safe_days,
        "rows_considered": len(rows),
        "updated_categories": updated_categories,
        "inserted_categories": inserted_categories,
    }


def _cli() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Generate daily plan for Margaret.")
    parser.add_argument("--force", action="store_true", help="Force regenerate today's plan.")
    parser.add_argument("--dry-run", action="store_true", help="Generate plan without sending SMS/email.")
    parser.add_argument(
        "--update-estimates",
        action="store_true",
        help="Refresh learned task time estimates from recent completion data.",
    )
    parser.add_argument(
        "--estimate-days",
        type=int,
        default=30,
        help="Lookback window (days) for estimate learning updates.",
    )
    parser.add_argument(
        "--estimates-only",
        action="store_true",
        help="Only refresh estimates and skip daily plan generation.",
    )
    parser.add_argument(
        "--skip-calendar",
        action="store_true",
        help="Skip Google Calendar block sync.",
    )
    return parser.parse_args()


def main() -> None:
    args = _cli()
    log(
        "Starting daily plan generation "
        f"(force={args.force}, dry_run={args.dry_run}, skip_calendar={args.skip_calendar}, "
        f"update_estimates={args.update_estimates}, estimates_only={args.estimates_only})"
    )
    if args.update_estimates:
        learning_summary = update_task_estimates(days_window=args.estimate_days)
        log(f"Estimate learning summary: {json.dumps(learning_summary, default=str)}")
        if args.estimates_only:
            return
    result = generate_daily_plan(
        force=args.force,
        send_messages=not args.dry_run,
        sync_calendar=not args.skip_calendar,
    )
    log(f"Daily plan result: {json.dumps(result, default=str)[:2400]}")


if __name__ == "__main__":
    main()
