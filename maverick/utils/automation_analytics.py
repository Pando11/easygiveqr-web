from __future__ import annotations

import os
from datetime import date, datetime, timedelta
from typing import Any

from utils.db import execute_query


TIME_PER_AUTO_COMPLETED_TASK_MIN = float((os.getenv("ANALYTICS_TIME_PER_AUTO_TASK_MIN") or "8").strip() or 8)
TIME_PER_AUTO_MESSAGE_MIN = float((os.getenv("ANALYTICS_TIME_PER_AUTO_MESSAGE_MIN") or "3").strip() or 3)
TIME_PER_AUTO_ANSWER_MIN = float((os.getenv("ANALYTICS_TIME_PER_AUTO_ANSWER_MIN") or "5").strip() or 5)
TIME_PER_VENDOR_SCHEDULING_MIN = float((os.getenv("ANALYTICS_TIME_PER_VENDOR_SCHEDULING_MIN") or "15").strip() or 15)
TIME_PER_PROBLEM_DETECTION_MIN = float((os.getenv("ANALYTICS_TIME_PER_PROBLEM_DETECTION_MIN") or "8").strip() or 8)
TIME_PER_BULK_MESSAGE_MIN = float((os.getenv("ANALYTICS_TIME_PER_BULK_MESSAGE_MIN") or "1.5").strip() or 1.5)

BASELINE_HOURS_PER_TRANSACTION = float((os.getenv("ANALYTICS_BASELINE_HOURS_PER_TXN") or "6.0").strip() or 6.0)
MARGARET_HOURLY_RATE = float((os.getenv("ANALYTICS_MARGARET_HOURLY_RATE") or "45").strip() or 45)


def _safe_float(value: Any, default: float = 0.0) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return float(default)


def _safe_int(value: Any, default: int = 0) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return int(default)


def _format_hours_minutes(minutes_value: float) -> str:
    total_minutes = max(0, int(round(minutes_value or 0)))
    hours = total_minutes // 60
    minutes = total_minutes % 60
    return f"{hours}h {minutes}m"


def _month_start(target_date: date) -> date:
    return target_date.replace(day=1)


def _next_month_start(target_date: date) -> date:
    if target_date.month == 12:
        return date(target_date.year + 1, 1, 1)
    return date(target_date.year, target_date.month + 1, 1)


def _week_start(target_date: date) -> date:
    return target_date - timedelta(days=target_date.weekday())


def _scalar(query: str, params: tuple[Any, ...] = (), default: Any = 0) -> Any:
    rows = execute_query(query, params, fetch=True) or []
    if not rows:
        return default
    row = rows[0]
    if not isinstance(row, dict) or not row:
        return default
    value = next(iter(row.values()))
    return value if value is not None else default


def _table_exists(table_name: str) -> bool:
    value = _scalar(
        "SELECT to_regclass(%s) AS table_ref",
        (f"public.{table_name}",),
        default=None,
    )
    return bool(value)


def _count_rows(table_name: str, where_clause: str = "TRUE", params: tuple[Any, ...] = ()) -> int:
    if not _table_exists(table_name):
        return 0
    query = f"SELECT COUNT(*) AS total FROM {table_name} WHERE {where_clause}"
    return _safe_int(_scalar(query, params, default=0))


def _count_distinct(table_name: str, distinct_col: str, where_clause: str = "TRUE", params: tuple[Any, ...] = ()) -> int:
    if not _table_exists(table_name):
        return 0
    query = f"SELECT COUNT(DISTINCT {distinct_col}) AS total FROM {table_name} WHERE {where_clause}"
    return _safe_int(_scalar(query, params, default=0))


def _count_auto_completed_tasks(start_dt: datetime, end_dt: datetime) -> int:
    return _count_rows(
        "tasks",
        "completed_by = 'auto-rule-engine' AND completed_at >= %s AND completed_at < %s",
        (start_dt, end_dt),
    )


def _count_auto_sent_messages(start_dt: datetime, end_dt: datetime) -> int:
    total = 0
    total += _count_rows("nudge_log", "sent_at >= %s AND sent_at < %s", (start_dt, end_dt))
    total += _count_rows(
        "bulk_message_recipients",
        "status = 'sent' AND COALESCE(sent_at, attempted_at, created_at) >= %s AND COALESCE(sent_at, attempted_at, created_at) < %s",
        (start_dt, end_dt),
    )
    total += _count_rows(
        "agent_status_update_messages",
        "status = 'sent' AND COALESCE(sent_at, created_at) >= %s AND COALESCE(sent_at, created_at) < %s",
        (start_dt, end_dt),
    )
    return total


def _count_auto_answered_questions(start_dt: datetime, end_dt: datetime) -> int:
    return _count_rows(
        "common_qa_events",
        "event_type = 'auto_answer_sent' AND created_at >= %s AND created_at < %s",
        (start_dt, end_dt),
    )


def _count_vendor_scheduling_events(start_dt: datetime, end_dt: datetime) -> int:
    return _count_rows(
        "vendor_outreach_log",
        "outreach_type = 'scheduled' AND outreach_date >= %s AND outreach_date < %s",
        (start_dt, end_dt),
    )


def _count_problem_detection_events(start_dt: datetime, end_dt: datetime) -> int:
    return _count_rows(
        "problem_detection_results",
        "bucket IN ('urgent', 'watch') AND created_at >= %s AND created_at < %s",
        (start_dt, end_dt),
    )


def _count_bulk_message_recipients_sent(start_dt: datetime, end_dt: datetime) -> int:
    return _count_rows(
        "bulk_message_recipients",
        "status = 'sent' AND COALESCE(sent_at, attempted_at, created_at) >= %s AND COALESCE(sent_at, attempted_at, created_at) < %s",
        (start_dt, end_dt),
    )


def _count_transactions_handled(start_dt: datetime, end_dt: datetime) -> int:
    value = _count_distinct(
        "communications",
        "transaction_id",
        "transaction_id IS NOT NULL AND created_at >= %s AND created_at < %s",
        (start_dt, end_dt),
    )
    if value > 0:
        return value
    return _count_distinct(
        "transactions",
        "id",
        "updated_at >= %s AND updated_at < %s",
        (start_dt, end_dt),
    )


def _sum_revenue_enabled(month_label: str) -> float:
    if not _table_exists("commission_tracking"):
        return 0.0
    value = _scalar(
        """
        SELECT COALESCE(SUM(ct.total_revenue), 0) AS total
        FROM commission_tracking ct
        JOIN transactions t ON t.id = ct.transaction_id
        WHERE ct.month = %s
          AND t.status = 'COMPLETED'
        """,
        (month_label,),
        default=0,
    )
    return _safe_float(value, default=0.0)


def _core_counts(start_dt: datetime, end_dt: datetime) -> dict[str, Any]:
    auto_completed = _count_auto_completed_tasks(start_dt, end_dt)
    auto_messages = _count_auto_sent_messages(start_dt, end_dt)
    auto_answers = _count_auto_answered_questions(start_dt, end_dt)
    manual_tasks_avoided = auto_completed + auto_messages + auto_answers
    core_time_saved_minutes = (
        auto_completed * TIME_PER_AUTO_COMPLETED_TASK_MIN
        + auto_messages * TIME_PER_AUTO_MESSAGE_MIN
        + auto_answers * TIME_PER_AUTO_ANSWER_MIN
    )
    return {
        "manual_tasks_avoided": manual_tasks_avoided,
        "auto_completed_tasks": auto_completed,
        "auto_sent_messages": auto_messages,
        "questions_auto_answered": auto_answers,
        "core_time_saved_minutes": round(core_time_saved_minutes, 1),
    }


def _auto_classification_error_pct(month_start_dt: datetime, month_end_dt: datetime) -> float:
    total_docs = _count_rows(
        "documents",
        "uploaded_at >= %s AND uploaded_at < %s",
        (month_start_dt, month_end_dt),
    )
    if total_docs <= 0:
        return 0.0
    error_docs = _count_distinct(
        "document_classification_corrections",
        "document_id",
        "created_at >= %s AND created_at < %s AND document_id IS NOT NULL",
        (month_start_dt, month_end_dt),
    )
    return round((error_docs / total_docs) * 100.0, 2)


def _auto_completion_error_pct(month_start_dt: datetime, month_end_dt: datetime) -> float:
    auto_completed = _count_rows(
        "task_auto_completion_log",
        "action = 'auto_completed' AND created_at >= %s AND created_at < %s",
        (month_start_dt, month_end_dt),
    )
    if auto_completed <= 0:
        return 0.0
    undone = _count_rows(
        "task_auto_completion_log",
        "action = 'auto_completed' AND undone_at IS NOT NULL AND created_at >= %s AND created_at < %s",
        (month_start_dt, month_end_dt),
    )
    return round((undone / auto_completed) * 100.0, 2)


def _missed_deadlines_count() -> int:
    if not _table_exists("deadlines") or not _table_exists("transactions"):
        return 0
    value = _scalar(
        """
        SELECT COUNT(*) AS total
        FROM deadlines d
        JOIN transactions t ON t.id = d.transaction_id
        WHERE t.status = 'ACTIVE'
          AND d.completed = FALSE
          AND d.deadline_date < CURRENT_DATE
        """,
        default=0,
    )
    return _safe_int(value)


def _client_satisfaction_score() -> dict[str, Any]:
    if not _table_exists("agent_reviews"):
        return {"avg_rating": 0.0, "review_count": 0}
    avg_rating = _safe_float(_scalar("SELECT COALESCE(AVG(rating), 0) AS avg_rating FROM agent_reviews", default=0), 0.0)
    review_count = _safe_int(_scalar("SELECT COUNT(*) AS total FROM agent_reviews", default=0), 0)
    return {"avg_rating": round(avg_rating, 2), "review_count": review_count}


def _agent_questions_reduced_pct(reference_date: date) -> float:
    if not _table_exists("common_qa_events"):
        return 0.0
    current_start = datetime.combine(reference_date - timedelta(days=30), datetime.min.time())
    previous_start = datetime.combine(reference_date - timedelta(days=60), datetime.min.time())
    rows = execute_query(
        """
        SELECT
            COUNT(*) FILTER (
                WHERE created_at >= %s
                  AND created_at < %s
                  AND asked_by_party = 'agent'
            ) AS previous_count,
            COUNT(*) FILTER (
                WHERE created_at >= %s
                  AND asked_by_party = 'agent'
            ) AS current_count
        FROM common_qa_events
        """,
        (previous_start, current_start, current_start),
        fetch=True,
    ) or []
    if not rows:
        return 0.0
    previous_count = _safe_int(rows[0].get("previous_count"), 0)
    current_count = _safe_int(rows[0].get("current_count"), 0)
    if previous_count <= 0:
        return 0.0
    return round(((previous_count - current_count) / previous_count) * 100.0, 1)


def _agent_review_response_rate(month_start_dt: datetime, month_end_dt: datetime) -> float:
    if not _table_exists("agent_review_requests"):
        return 0.0
    rows = execute_query(
        """
        SELECT
            COUNT(*) AS total_count,
            COUNT(*) FILTER (WHERE status = 'completed') AS completed_count
        FROM agent_review_requests
        WHERE requested_at >= %s
          AND requested_at < %s
        """,
        (month_start_dt, month_end_dt),
        fetch=True,
    ) or []
    if not rows:
        return 0.0
    total_count = _safe_int(rows[0].get("total_count"), 0)
    completed_count = _safe_int(rows[0].get("completed_count"), 0)
    if total_count <= 0:
        return 0.0
    return round((completed_count / total_count) * 100.0, 1)


def _morning_briefing_read_status() -> str:
    if not _table_exists("morning_briefings"):
        return "Not generated"
    latest_rows = execute_query(
        """
        SELECT id, briefing_date, generated_at, sent_sms, sent_email
        FROM morning_briefings
        ORDER BY briefing_date DESC, generated_at DESC, id DESC
        LIMIT 1
        """,
        fetch=True,
    ) or []
    if not latest_rows:
        return "Not generated"
    latest = latest_rows[0]
    if not _table_exists("morning_briefing_items"):
        return "Generated"
    interaction_count = _count_rows(
        "morning_briefing_items",
        "briefing_id = %s AND (status <> 'pending' OR COALESCE(notes, '') <> '' OR updated_at > created_at)",
        (latest["id"],),
    )
    return "Read" if interaction_count > 0 else "Not read"


def build_automation_analytics_snapshot(reference_date: date | None = None) -> dict[str, Any]:
    """Build consolidated automation/efficiency analytics payload."""
    today = reference_date or date.today()
    day_start = datetime.combine(today, datetime.min.time())
    day_end = day_start + timedelta(days=1)

    week_start_date = _week_start(today)
    week_start_dt = datetime.combine(week_start_date, datetime.min.time())
    week_end_dt = week_start_dt + timedelta(days=7)

    month_start_date = _month_start(today)
    next_month_date = _next_month_start(today)
    month_start_dt = datetime.combine(month_start_date, datetime.min.time())
    month_end_dt = datetime.combine(next_month_date, datetime.min.time())
    month_label = month_start_date.strftime("%Y-%m")

    daily_core = _core_counts(day_start, day_end)
    weekly_core = _core_counts(week_start_dt, week_end_dt)
    monthly_core = _core_counts(month_start_dt, month_end_dt)

    weekly_vendor_count = _count_vendor_scheduling_events(week_start_dt, week_end_dt)
    weekly_problem_count = _count_problem_detection_events(week_start_dt, week_end_dt)
    weekly_total_saved_minutes = (
        weekly_core["core_time_saved_minutes"]
        + (weekly_vendor_count * TIME_PER_VENDOR_SCHEDULING_MIN)
        + (weekly_problem_count * TIME_PER_PROBLEM_DETECTION_MIN)
    )

    monthly_vendor_count = _count_vendor_scheduling_events(month_start_dt, month_end_dt)
    monthly_problem_count = _count_problem_detection_events(month_start_dt, month_end_dt)
    monthly_total_saved_minutes = (
        monthly_core["core_time_saved_minutes"]
        + (monthly_vendor_count * TIME_PER_VENDOR_SCHEDULING_MIN)
        + (monthly_problem_count * TIME_PER_PROBLEM_DETECTION_MIN)
    )

    transactions_handled_week = _count_transactions_handled(week_start_dt, week_end_dt)
    weekly_saved_hours = round(weekly_total_saved_minutes / 60.0, 2)
    if transactions_handled_week > 0:
        average_hours_per_txn = max(
            0.5,
            BASELINE_HOURS_PER_TRANSACTION - (weekly_saved_hours / transactions_handled_week),
        )
    else:
        average_hours_per_txn = 0.0
    efficiency_improvement_pct = (
        round(((BASELINE_HOURS_PER_TRANSACTION - average_hours_per_txn) / BASELINE_HOURS_PER_TRANSACTION) * 100.0, 1)
        if BASELINE_HOURS_PER_TRANSACTION > 0 and transactions_handled_week > 0
        else 0.0
    )

    transactions_handled_month = _count_transactions_handled(month_start_dt, month_end_dt)
    monthly_saved_hours = round(monthly_total_saved_minutes / 60.0, 2)
    capacity_increase = (
        int(round(monthly_saved_hours / BASELINE_HOURS_PER_TRANSACTION))
        if BASELINE_HOURS_PER_TRANSACTION > 0
        else 0
    )
    margaret_hours_worked = max(0.0, (transactions_handled_month * BASELINE_HOURS_PER_TRANSACTION) - monthly_saved_hours)
    revenue_enabled = _sum_revenue_enabled(month_label)
    labor_cost = margaret_hours_worked * MARGARET_HOURLY_RATE
    roi_pct = round(((revenue_enabled - labor_cost) / labor_cost) * 100.0, 1) if labor_cost > 0 else 0.0

    quality = {
        "auto_classification_errors_pct": _auto_classification_error_pct(month_start_dt, month_end_dt),
        "auto_completion_errors_pct": _auto_completion_error_pct(month_start_dt, month_end_dt),
        "missed_deadlines": _missed_deadlines_count(),
    }
    quality.update(_client_satisfaction_score())

    engagement = {
        "agent_questions_reduced_pct": _agent_questions_reduced_pct(today),
        "agent_review_responses_pct": _agent_review_response_rate(month_start_dt, month_end_dt),
        "referrals_generated": _count_rows(
            "referrals",
            "created_at >= %s AND created_at < %s",
            (month_start_dt, month_end_dt),
        ),
    }

    feature_adoption = {
        "bulk_sms_uses_week": _count_rows(
            "bulk_messages_log",
            "created_at >= %s AND created_at < %s",
            (week_start_dt, week_end_dt),
        ),
        "voice_notes_uses_week": _count_rows(
            "voice_notes",
            "created_at >= %s AND created_at < %s",
            (week_start_dt, week_end_dt),
        ),
        "auto_complete_tasks_week": weekly_core["auto_completed_tasks"],
        "morning_briefing_read_status": _morning_briefing_read_status(),
        "transaction_completion_uses_month": _count_rows(
            "communications",
            "created_at >= %s AND created_at < %s AND summary = %s",
            (month_start_dt, month_end_dt, "One-click completion workflow executed"),
        ),
    }

    feature_time_savings = {
        "auto_vendor_scheduling_hours_month": round(
            (monthly_vendor_count * TIME_PER_VENDOR_SCHEDULING_MIN) / 60.0,
            1,
        ),
        "problem_detection_hours_month": round(
            (monthly_problem_count * TIME_PER_PROBLEM_DETECTION_MIN) / 60.0,
            1,
        ),
        "bulk_messaging_hours_month": round(
            (_count_bulk_message_recipients_sent(month_start_dt, month_end_dt) * TIME_PER_BULK_MESSAGE_MIN) / 60.0,
            1,
        ),
    }

    return {
        "generated_at": datetime.now(),
        "period": {
            "today": today,
            "week_start": week_start_date,
            "month_start": month_start_date,
        },
        "time_savings": {
            "daily": {
                **daily_core,
                "time_saved_minutes": daily_core["core_time_saved_minutes"],
                "time_saved_label": _format_hours_minutes(daily_core["core_time_saved_minutes"]),
            },
            "weekly": {
                "transactions_handled": transactions_handled_week,
                "average_hours_per_transaction": round(average_hours_per_txn, 1),
                "total_time_saved_hours": round(weekly_saved_hours, 1),
                "efficiency_improvement_pct": efficiency_improvement_pct,
            },
            "monthly": {
                "capacity_increase_transactions": capacity_increase,
                "margaret_hours_worked": round(margaret_hours_worked, 1),
                "revenue_enabled": round(revenue_enabled, 2),
                "roi_pct": roi_pct,
            },
        },
        "quality": quality,
        "engagement": engagement,
        "feature_adoption": feature_adoption,
        "feature_time_savings": feature_time_savings,
        "baseline": {
            "baseline_hours_per_transaction": BASELINE_HOURS_PER_TRANSACTION,
            "margaret_hourly_rate": MARGARET_HOURLY_RATE,
        },
    }
