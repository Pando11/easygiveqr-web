from __future__ import annotations

import re
from datetime import date, datetime, time, timedelta

from utils.db import execute_query
from utils.email import send_email

DEFAULT_SUBJECT_TEMPLATE = "Weekly status update: {{PROPERTY_ADDRESS}} ({{DAYS_TO_CLOSING}} days to closing)"
DEFAULT_BODY_TEMPLATE = (
    "Hi {{AGENT_NAME}},\n"
    "Here is your status update for {{PROPERTY_ADDRESS}}.\n"
    "Health: {{HEALTH_STATUS}}\n"
    "Days to closing: {{DAYS_TO_CLOSING}}\n"
    "Progress to closing: {{PROGRESS_PCT}}%\n"
    "Urgent items: {{URGENT_ITEMS}}\n"
    "Agent action items: {{AGENT_ACTION_ITEMS}}\n"
    "Reply to this email if you want Margaret to prioritize anything today."
)

SCHEDULE_SLOT_OPTIONS = [
    ("monday_8am", "Monday at 8:00 AM"),
    ("friday_5pm", "Friday at 5:00 PM"),
]

AGENT_STATUS_TEMPLATE_TOKENS = [
    "AGENT_NAME",
    "PROPERTY_ADDRESS",
    "DAYS_TO_CLOSING",
    "HEALTH_STATUS",
    "PROGRESS_PCT",
    "URGENT_ITEMS",
    "AGENT_ACTION_ITEMS",
]

def _normalize_email(raw_value):
    value = (raw_value or "").strip().lower()
    return value


def _normalize_phone(raw_value):
    digits = re.sub(r"\D", "", raw_value or "")
    if len(digits) == 10:
        return f"+1{digits}"
    if len(digits) == 11 and digits.startswith("1"):
        return f"+{digits}"
    if (raw_value or "").strip().startswith("+"):
        return (raw_value or "").strip()
    return f"+{digits}" if digits else ""


def _format_date(value):
    if hasattr(value, "strftime"):
        return value.strftime("%b %d, %Y")
    return "TBD"


def _format_datetime(value):
    if hasattr(value, "strftime"):
        return value.strftime("%b %d, %Y %I:%M %p")
    return ""


def _week_bounds(reference_dt=None):
    current_date = reference_dt.date() if isinstance(reference_dt, datetime) else (reference_dt or date.today())
    week_start = current_date - timedelta(days=current_date.weekday())
    week_end = week_start + timedelta(days=7)
    return week_start, week_end


def _to_dt_day_start(day_value):
    return datetime.combine(day_value, time.min)


def _to_dt_day_end(day_value):
    return datetime.combine(day_value, time.max)


def _render_token_template(template_text, token_map):
    base = template_text or ""

    def repl(match):
        token_key = (match.group(1) or "").strip().upper()
        return str(token_map.get(token_key, ""))

    return re.sub(r"\{\{\s*([A-Za-z0-9_]+)\s*\}\}", repl, base)


def _schedule_slot_label(slot):
    for key, label in SCHEDULE_SLOT_OPTIONS:
        if key == slot:
            return label
    return "Monday at 8:00 AM"


def _schedule_week_key(schedule_slot, reference_dt=None):
    base_date = reference_dt.date() if isinstance(reference_dt, datetime) else (reference_dt or date.today())
    iso_year, iso_week, _ = base_date.isocalendar()
    return f"{iso_year}-W{iso_week:02d}-{schedule_slot}"


def _is_schedule_due(now_dt, schedule_slot):
    slot = (schedule_slot or "monday_8am").strip().lower()
    if slot == "friday_5pm":
        return now_dt.weekday() == 4 and now_dt.hour == 17
    return now_dt.weekday() == 0 and now_dt.hour == 8


def ensure_agent_status_update_tables():
    """Create status-update settings, opt-outs, and send logs."""
    execute_query(
        """
        CREATE TABLE IF NOT EXISTS agent_status_update_settings (
            id SERIAL PRIMARY KEY,
            enabled BOOLEAN DEFAULT TRUE,
            schedule_slot VARCHAR(30) DEFAULT 'monday_8am',
            subject_template TEXT,
            body_template TEXT,
            updated_by VARCHAR(100),
            updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
        """
    )
    execute_query(
        """
        CREATE TABLE IF NOT EXISTS agent_status_update_opt_out (
            id SERIAL PRIMARY KEY,
            agent_name VARCHAR(255),
            agent_email VARCHAR(255),
            agent_phone VARCHAR(25),
            reason TEXT,
            active BOOLEAN DEFAULT TRUE,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
        """
    )
    execute_query(
        """
        CREATE TABLE IF NOT EXISTS agent_status_update_runs (
            id SERIAL PRIMARY KEY,
            run_kind VARCHAR(30) DEFAULT 'manual',
            preview_only BOOLEAN DEFAULT FALSE,
            triggered_by VARCHAR(100),
            schedule_slot VARCHAR(30),
            schedule_week_key VARCHAR(40),
            started_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            completed_at TIMESTAMP,
            status VARCHAR(20) DEFAULT 'running',
            candidate_count INT DEFAULT 0,
            sent_count INT DEFAULT 0,
            failed_count INT DEFAULT 0,
            questions_this_week INT DEFAULT 0,
            questions_previous_week INT DEFAULT 0,
            question_reduction_estimate INT DEFAULT 0,
            notes TEXT
        )
        """
    )
    execute_query(
        """
        CREATE TABLE IF NOT EXISTS agent_status_update_messages (
            id SERIAL PRIMARY KEY,
            run_id INT REFERENCES agent_status_update_runs(id) ON DELETE CASCADE,
            transaction_id INT REFERENCES transactions(id) ON DELETE CASCADE,
            agent_name VARCHAR(255),
            agent_email VARCHAR(255),
            property_address VARCHAR(255),
            health_status VARCHAR(20),
            progress_pct INT DEFAULT 0,
            days_to_closing INT,
            urgent_item_count INT DEFAULT 0,
            tasks_completed_week INT DEFAULT 0,
            documents_uploaded_week INT DEFAULT 0,
            communications_week INT DEFAULT 0,
            upcoming_deadlines_count INT DEFAULT 0,
            agent_action_items_count INT DEFAULT 0,
            subject VARCHAR(255),
            rendered_body TEXT,
            status VARCHAR(20) DEFAULT 'preview',
            failure_reason TEXT,
            sent_at TIMESTAMP,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
        """
    )
    execute_query(
        """
        CREATE INDEX IF NOT EXISTS idx_agent_status_update_opt_out_active
        ON agent_status_update_opt_out(active, agent_email, agent_name)
        """
    )
    execute_query(
        """
        CREATE INDEX IF NOT EXISTS idx_agent_status_update_runs_started
        ON agent_status_update_runs(started_at DESC, status)
        """
    )
    execute_query(
        """
        CREATE INDEX IF NOT EXISTS idx_agent_status_update_runs_week_key
        ON agent_status_update_runs(schedule_week_key, run_kind, preview_only)
        """
    )
    execute_query(
        """
        CREATE INDEX IF NOT EXISTS idx_agent_status_update_messages_run
        ON agent_status_update_messages(run_id, status, sent_at DESC)
        """
    )
    execute_query(
        """
        CREATE INDEX IF NOT EXISTS idx_agent_status_update_messages_sent
        ON agent_status_update_messages(sent_at DESC, status)
        """
    )

    existing = execute_query("SELECT id FROM agent_status_update_settings LIMIT 1", fetch=True) or []
    if not existing:
        execute_query(
            """
            INSERT INTO agent_status_update_settings (
                enabled, schedule_slot, subject_template, body_template, updated_by, updated_at
            )
            VALUES (TRUE, 'monday_8am', %s, %s, 'system', CURRENT_TIMESTAMP)
            """,
            (DEFAULT_SUBJECT_TEMPLATE, DEFAULT_BODY_TEMPLATE),
        )


def fetch_agent_status_update_settings():
    ensure_agent_status_update_tables()
    rows = execute_query(
        """
        SELECT id, enabled, schedule_slot, subject_template, body_template, updated_by, updated_at
        FROM agent_status_update_settings
        ORDER BY id ASC
        LIMIT 1
        """,
        fetch=True,
    ) or []
    if rows:
        row = rows[0]
    else:
        row = {
            "enabled": True,
            "schedule_slot": "monday_8am",
            "subject_template": DEFAULT_SUBJECT_TEMPLATE,
            "body_template": DEFAULT_BODY_TEMPLATE,
            "updated_by": "system",
            "updated_at": None,
        }
    row["schedule_slot"] = (row.get("schedule_slot") or "monday_8am").strip().lower()
    if row["schedule_slot"] not in {option[0] for option in SCHEDULE_SLOT_OPTIONS}:
        row["schedule_slot"] = "monday_8am"
    row["subject_template"] = (row.get("subject_template") or DEFAULT_SUBJECT_TEMPLATE).strip()
    row["body_template"] = (row.get("body_template") or DEFAULT_BODY_TEMPLATE).strip()
    row["schedule_label"] = _schedule_slot_label(row["schedule_slot"])
    row["updated_at_label"] = _format_datetime(row.get("updated_at"))
    return row


def update_agent_status_update_settings(
    *,
    enabled=True,
    schedule_slot="monday_8am",
    subject_template="",
    body_template="",
    updated_by="margaret",
):
    ensure_agent_status_update_tables()
    normalized_slot = (schedule_slot or "monday_8am").strip().lower()
    if normalized_slot not in {option[0] for option in SCHEDULE_SLOT_OPTIONS}:
        normalized_slot = "monday_8am"

    clean_subject = (subject_template or "").strip() or DEFAULT_SUBJECT_TEMPLATE
    clean_body = (body_template or "").strip() or DEFAULT_BODY_TEMPLATE
    execute_query(
        """
        UPDATE agent_status_update_settings
        SET enabled = %s,
            schedule_slot = %s,
            subject_template = %s,
            body_template = %s,
            updated_by = %s,
            updated_at = CURRENT_TIMESTAMP
        WHERE id = (
            SELECT id FROM agent_status_update_settings ORDER BY id ASC LIMIT 1
        )
        """,
        (bool(enabled), normalized_slot, clean_subject, clean_body, (updated_by or "margaret")[:100]),
    )
    return True


def fetch_agent_status_opt_outs(active_only=False):
    ensure_agent_status_update_tables()
    clause = "WHERE active = TRUE" if active_only else ""
    rows = execute_query(
        f"""
        SELECT id, agent_name, agent_email, agent_phone, reason, active, created_at, updated_at
        FROM agent_status_update_opt_out
        {clause}
        ORDER BY active DESC, created_at DESC, id DESC
        """,
        fetch=True,
    ) or []
    for row in rows:
        row["created_at_label"] = _format_datetime(row.get("created_at"))
    return rows


def add_agent_status_opt_out(agent_name="", agent_email="", agent_phone="", reason="", active=True):
    ensure_agent_status_update_tables()
    email_value = _normalize_email(agent_email)
    name_value = (agent_name or "").strip()
    phone_value = _normalize_phone(agent_phone)
    if not email_value and not name_value and not phone_value:
        return {"success": False, "error": "Provide at least one identifier (name, email, or phone)."}

    rows = execute_query(
        """
        INSERT INTO agent_status_update_opt_out (
            agent_name, agent_email, agent_phone, reason, active, created_at, updated_at
        )
        VALUES (%s, %s, %s, %s, %s, CURRENT_TIMESTAMP, CURRENT_TIMESTAMP)
        RETURNING id
        """,
        (
            name_value[:255] or None,
            email_value[:255] or None,
            phone_value[:25] or None,
            (reason or "").strip()[:800] or None,
            bool(active),
        ),
        fetch=True,
    ) or []
    return {"success": bool(rows), "id": (rows[0]["id"] if rows else None)}


def deactivate_agent_status_opt_out(opt_out_id):
    try:
        row_id = int(opt_out_id)
    except (TypeError, ValueError):
        return False
    execute_query(
        """
        UPDATE agent_status_update_opt_out
        SET active = FALSE,
            updated_at = CURRENT_TIMESTAMP
        WHERE id = %s
        """,
        (row_id,),
    )
    return True


def _fetch_active_transactions():
    rows = execute_query(
        """
        SELECT id, property_address, agent_name, agent_email, agent_phone, closing_date
        FROM transactions
        WHERE status = 'ACTIVE'
          AND COALESCE(agent_email, '') <> ''
        ORDER BY COALESCE(closing_date, CURRENT_DATE + INTERVAL '365 days') ASC, id ASC
        """,
        fetch=True,
    ) or []
    return rows


def _fetch_opt_out_lookup():
    rows = fetch_agent_status_opt_outs(active_only=True)
    emails = {_normalize_email(row.get("agent_email")) for row in rows if _normalize_email(row.get("agent_email"))}
    names = {(row.get("agent_name") or "").strip().lower() for row in rows if (row.get("agent_name") or "").strip()}
    phones = {_normalize_phone(row.get("agent_phone")) for row in rows if _normalize_phone(row.get("agent_phone"))}
    return {"emails": emails, "names": names, "phones": phones}


def _is_opted_out(transaction_row, opt_out_lookup):
    email = _normalize_email(transaction_row.get("agent_email"))
    name = (transaction_row.get("agent_name") or "").strip().lower()
    phone = _normalize_phone(transaction_row.get("agent_phone"))
    if email and email in opt_out_lookup["emails"]:
        return True
    if name and name in opt_out_lookup["names"]:
        return True
    if phone and phone in opt_out_lookup["phones"]:
        return True
    return False


def _status_check_count(start_dt, end_dt):
    rows = execute_query(
        """
        SELECT COUNT(*) AS total
        FROM communications
        WHERE created_at >= %s
          AND created_at < %s
          AND LOWER(COALESCE(contact_party, '')) = 'agent'
          AND (
                LOWER(COALESCE(summary, '')) LIKE '%status%'
             OR LOWER(COALESCE(summary, '')) LIKE '%update%'
             OR LOWER(COALESCE(summary, '')) LIKE '%closing%'
             OR LOWER(COALESCE(summary, '')) LIKE '%deadline%'
             OR LOWER(COALESCE(summary, '')) LIKE '%progress%'
             OR LOWER(COALESCE(outcome, '')) LIKE '%status%'
             OR LOWER(COALESCE(outcome, '')) LIKE '%update%'
             OR LOWER(COALESCE(outcome, '')) LIKE '%closing%'
             OR LOWER(COALESCE(outcome, '')) LIKE '%deadline%'
             OR LOWER(COALESCE(outcome, '')) LIKE '%progress%'
          )
          AND LOWER(COALESCE(summary, '')) NOT LIKE 'weekly transaction status update sent%%'
        """,
        (start_dt, end_dt),
        fetch=True,
    ) or []
    return int(rows[0]["total"]) if rows else 0


def _fetch_question_reduction_metrics(reference_dt=None):
    week_start, week_end = _week_bounds(reference_dt)
    previous_start = week_start - timedelta(days=7)
    current_count = _status_check_count(_to_dt_day_start(week_start), _to_dt_day_start(week_end))
    previous_count = _status_check_count(_to_dt_day_start(previous_start), _to_dt_day_start(week_start))
    reduction_count = max(previous_count - current_count, 0)
    reduction_pct = round((reduction_count / previous_count) * 100.0, 1) if previous_count > 0 else 0.0
    return {
        "week_start": week_start,
        "week_end": week_end,
        "current_count": current_count,
        "previous_count": previous_count,
        "reduction_count": reduction_count,
        "reduction_pct": reduction_pct,
        "answered_questions_estimate": reduction_count,
    }


def _fetch_counts(transaction_id, week_start, week_end, reference_date, horizon_date):
    rows = execute_query(
        """
        SELECT
            (
                SELECT COUNT(*)
                FROM tasks tk
                WHERE tk.transaction_id = %s
                  AND (tk.completed = TRUE OR tk.status = 'completed')
                  AND tk.completed_at >= %s
                  AND tk.completed_at < %s
            ) AS tasks_completed_week,
            (
                SELECT COUNT(*)
                FROM documents d
                WHERE d.transaction_id = %s
                  AND d.uploaded_at >= %s
                  AND d.uploaded_at < %s
            ) AS documents_uploaded_week,
            (
                SELECT COUNT(*)
                FROM communications c
                WHERE c.transaction_id = %s
                  AND c.created_at >= %s
                  AND c.created_at < %s
                  AND LOWER(COALESCE(c.contact_party, '')) <> 'system'
                  AND LOWER(COALESCE(c.summary, '')) NOT LIKE 'weekly transaction status update sent%%'
            ) AS communications_week,
            (
                SELECT COUNT(*)
                FROM deadlines d2
                WHERE d2.transaction_id = %s
                  AND d2.completed = FALSE
                  AND d2.deadline_date >= %s
                  AND d2.deadline_date <= %s
            ) AS upcoming_deadlines_count,
            (
                SELECT COUNT(*)
                FROM tasks ta
                WHERE ta.transaction_id = %s
                  AND ta.completed = FALSE
                  AND COALESCE(ta.status, 'pending') <> 'completed'
                  AND LOWER(COALESCE(ta.assigned_to, '')) LIKE '%%agent%%'
            ) AS agent_assigned_open_count
        """,
        (
            transaction_id,
            _to_dt_day_start(week_start),
            _to_dt_day_start(week_end),
            transaction_id,
            _to_dt_day_start(week_start),
            _to_dt_day_start(week_end),
            transaction_id,
            _to_dt_day_start(week_start),
            _to_dt_day_start(week_end),
            transaction_id,
            reference_date,
            horizon_date,
            transaction_id,
        ),
        fetch=True,
    ) or []
    return rows[0] if rows else {
        "tasks_completed_week": 0,
        "documents_uploaded_week": 0,
        "communications_week": 0,
        "upcoming_deadlines_count": 0,
        "agent_assigned_open_count": 0,
    }


def _fetch_task_progress(transaction_id):
    rows = execute_query(
        """
        SELECT
            COUNT(*) AS total_count,
            COUNT(*) FILTER (WHERE completed = TRUE OR status = 'completed') AS completed_count
        FROM tasks
        WHERE transaction_id = %s
        """,
        (transaction_id,),
        fetch=True,
    ) or []
    if not rows:
        return {"total_count": 0, "completed_count": 0, "progress_pct": 0}
    total_count = int(rows[0].get("total_count") or 0)
    completed_count = int(rows[0].get("completed_count") or 0)
    progress_pct = round((completed_count / total_count) * 100.0) if total_count > 0 else 0
    return {"total_count": total_count, "completed_count": completed_count, "progress_pct": int(progress_pct)}


def _fetch_recent_completed_tasks(transaction_id, week_start, week_end):
    rows = execute_query(
        """
        SELECT task_description, completed_at
        FROM tasks
        WHERE transaction_id = %s
          AND (completed = TRUE OR status = 'completed')
          AND completed_at >= %s
          AND completed_at < %s
        ORDER BY completed_at DESC, id DESC
        LIMIT 5
        """,
        (transaction_id, _to_dt_day_start(week_start), _to_dt_day_start(week_end)),
        fetch=True,
    ) or []
    return [f"{row.get('task_description')}" for row in rows if row.get("task_description")]


def _fetch_uploaded_documents(transaction_id, week_start, week_end):
    rows = execute_query(
        """
        SELECT document_type, filename, uploaded_at
        FROM documents
        WHERE transaction_id = %s
          AND uploaded_at >= %s
          AND uploaded_at < %s
        ORDER BY uploaded_at DESC, id DESC
        LIMIT 5
        """,
        (transaction_id, _to_dt_day_start(week_start), _to_dt_day_start(week_end)),
        fetch=True,
    ) or []
    items = []
    for row in rows:
        label = (row.get("document_type") or "document").replace("_", " ").title()
        filename = row.get("filename") or ""
        if filename:
            items.append(f"{label}: {filename}")
        else:
            items.append(label)
    return items


def _fetch_recent_communications(transaction_id, week_start, week_end):
    rows = execute_query(
        """
        SELECT summary, contact_party, created_at
        FROM communications
        WHERE transaction_id = %s
          AND created_at >= %s
          AND created_at < %s
          AND LOWER(COALESCE(contact_party, '')) <> 'system'
          AND LOWER(COALESCE(summary, '')) NOT LIKE 'weekly transaction status update sent%%'
        ORDER BY created_at DESC, id DESC
        LIMIT 4
        """,
        (transaction_id, _to_dt_day_start(week_start), _to_dt_day_start(week_end)),
        fetch=True,
    ) or []
    items = []
    for row in rows:
        party = (row.get("contact_party") or "party").replace("_", " ").title()
        summary = (row.get("summary") or "").strip()
        if summary:
            items.append(f"{party}: {summary[:180]}")
    return items


def _fetch_in_progress_tasks(transaction_id):
    rows = execute_query(
        """
        SELECT task_description, due_date, priority
        FROM tasks
        WHERE transaction_id = %s
          AND completed = FALSE
          AND status = 'in_progress'
        ORDER BY due_date ASC NULLS LAST, id ASC
        LIMIT 5
        """,
        (transaction_id,),
        fetch=True,
    ) or []
    items = []
    for row in rows:
        due = _format_date(row.get("due_date"))
        items.append(f"{row.get('task_description') or 'Task'} (due {due})")
    return items


def _fetch_upcoming_deadlines(transaction_id, reference_date, horizon_date):
    rows = execute_query(
        """
        SELECT deadline_type, deadline_date
        FROM deadlines
        WHERE transaction_id = %s
          AND completed = FALSE
          AND deadline_date >= %s
          AND deadline_date <= %s
        ORDER BY deadline_date ASC, id ASC
        LIMIT 7
        """,
        (transaction_id, reference_date, horizon_date),
        fetch=True,
    ) or []
    items = []
    for row in rows:
        deadline_date = row.get("deadline_date")
        days_until = (deadline_date - reference_date).days if deadline_date else None
        label = (row.get("deadline_type") or "").replace("_", " ").title()
        if days_until is None:
            items.append(f"{label}: TBD")
        elif days_until == 0:
            items.append(f"{label}: Today")
        elif days_until == 1:
            items.append(f"{label}: Tomorrow")
        else:
            items.append(f"{label}: {_format_date(deadline_date)} ({days_until} days)")
    return items


def _fetch_agent_action_items(transaction_id, reference_date, horizon_date):
    rows = execute_query(
        """
        SELECT task_description, due_date, priority
        FROM tasks
        WHERE transaction_id = %s
          AND completed = FALSE
          AND COALESCE(status, 'pending') <> 'completed'
          AND (
                LOWER(COALESCE(assigned_to, '')) LIKE '%%agent%%'
             OR LOWER(COALESCE(task_description, '')) LIKE '%%schedule%%'
             OR LOWER(COALESCE(task_description, '')) LIKE '%%provide%%'
             OR LOWER(COALESCE(task_description, '')) LIKE '%%confirm%%'
             OR LOWER(COALESCE(task_description, '')) LIKE '%%submit%%'
             OR LOWER(COALESCE(task_description, '')) LIKE '%%review%%'
             OR LOWER(COALESCE(task_description, '')) LIKE '%%send%%'
             OR LOWER(COALESCE(task_description, '')) LIKE '%%request%%'
             OR LOWER(COALESCE(task_description, '')) LIKE '%%order%%'
          )
          AND (due_date IS NULL OR due_date <= %s)
        ORDER BY
            CASE WHEN due_date < %s THEN 0 ELSE 1 END,
            due_date ASC NULLS LAST,
            id ASC
        LIMIT 8
        """,
        (transaction_id, horizon_date, reference_date),
        fetch=True,
    ) or []
    items = []
    for row in rows:
        description = (row.get("task_description") or "Task").strip()
        due_date = row.get("due_date")
        if due_date:
            if due_date < reference_date:
                due_label = "overdue"
            else:
                days = (due_date - reference_date).days
                due_label = "today" if days == 0 else (f"in {days} day{'s' if days != 1 else ''}")
            items.append(f"{description} ({due_label})")
        else:
            items.append(description)
    return items


def _fetch_urgent_items(transaction_id, reference_date):
    deadline_rows = execute_query(
        """
        SELECT deadline_type, deadline_date
        FROM deadlines
        WHERE transaction_id = %s
          AND completed = FALSE
          AND deadline_date < %s
        ORDER BY deadline_date ASC, id ASC
        LIMIT 4
        """,
        (transaction_id, reference_date),
        fetch=True,
    ) or []
    task_rows = execute_query(
        """
        SELECT task_description, due_date, priority
        FROM tasks
        WHERE transaction_id = %s
          AND completed = FALSE
          AND COALESCE(status, 'pending') <> 'completed'
          AND LOWER(COALESCE(priority, '')) = 'high'
          AND due_date IS NOT NULL
          AND due_date <= %s
        ORDER BY due_date ASC, id ASC
        LIMIT 5
        """,
        (transaction_id, reference_date + timedelta(days=2)),
        fetch=True,
    ) or []

    urgent = []
    for row in deadline_rows:
        label = (row.get("deadline_type") or "").replace("_", " ").title()
        urgent.append(f"{label} is overdue ({_format_date(row.get('deadline_date'))})")
    for row in task_rows:
        due_date = row.get("due_date")
        if due_date and due_date < reference_date:
            due_label = "overdue"
        else:
            due_label = "due soon"
        urgent.append(f"{row.get('task_description') or 'High-priority task'} ({due_label})")
    unique = []
    for item in urgent:
        if item not in unique:
            unique.append(item)
    return unique[:6]


def _derive_health_status(days_to_closing, urgent_items, upcoming_deadlines, agent_actions):
    if days_to_closing is not None and days_to_closing < 0:
        return "urgent"
    if urgent_items:
        return "urgent"
    if (days_to_closing is not None and days_to_closing <= 5 and agent_actions) or upcoming_deadlines:
        return "watch"
    return "healthy"


def _build_transaction_payload(transaction_row, settings, template_overrides=None, reference_dt=None):
    reference_date = reference_dt.date() if isinstance(reference_dt, datetime) else (reference_dt or date.today())
    week_start, week_end = _week_bounds(reference_date)
    horizon_date = reference_date + timedelta(days=7)
    transaction_id = transaction_row["id"]

    counts = _fetch_counts(transaction_id, week_start, week_end, reference_date, horizon_date)
    progress = _fetch_task_progress(transaction_id)
    completed_tasks = _fetch_recent_completed_tasks(transaction_id, week_start, week_end)
    uploaded_docs = _fetch_uploaded_documents(transaction_id, week_start, week_end)
    communications = _fetch_recent_communications(transaction_id, week_start, week_end)
    in_progress = _fetch_in_progress_tasks(transaction_id)
    upcoming_deadlines = _fetch_upcoming_deadlines(transaction_id, reference_date, horizon_date)
    agent_actions = _fetch_agent_action_items(transaction_id, reference_date, horizon_date)
    urgent_items = _fetch_urgent_items(transaction_id, reference_date)

    closing_date = transaction_row.get("closing_date")
    days_to_closing = (closing_date - reference_date).days if closing_date else None
    days_to_closing_label = (
        "TBD"
        if days_to_closing is None
        else ("Closing today" if days_to_closing == 0 else f"{days_to_closing} day{'s' if days_to_closing != 1 else ''}")
    )
    health_status = _derive_health_status(days_to_closing, urgent_items, upcoming_deadlines, agent_actions)
    health_label = health_status.title()

    token_map = {
        "AGENT_NAME": transaction_row.get("agent_name") or "Agent",
        "PROPERTY_ADDRESS": transaction_row.get("property_address") or f"Transaction #{transaction_id}",
        "DAYS_TO_CLOSING": "TBD" if days_to_closing is None else str(days_to_closing),
        "HEALTH_STATUS": health_label,
        "PROGRESS_PCT": str(progress["progress_pct"]),
        "URGENT_ITEMS": "; ".join(urgent_items) if urgent_items else "None",
        "AGENT_ACTION_ITEMS": "; ".join(agent_actions[:4]) if agent_actions else "None",
    }

    subject_template = (
        (template_overrides or {}).get("subject_template")
        or settings.get("subject_template")
        or DEFAULT_SUBJECT_TEMPLATE
    )
    body_template = (
        (template_overrides or {}).get("body_template")
        or settings.get("body_template")
        or DEFAULT_BODY_TEMPLATE
    )
    rendered_subject = _render_token_template(subject_template, token_map).strip()[:255]
    rendered_body = _render_token_template(body_template, token_map).strip()
    custom_message_lines = [line.strip() for line in rendered_body.splitlines() if line.strip()]

    metrics_summary = {
        "tasks_completed_week": int(counts.get("tasks_completed_week") or 0),
        "documents_uploaded_week": int(counts.get("documents_uploaded_week") or 0),
        "communications_week": int(counts.get("communications_week") or 0),
        "upcoming_deadlines_count": int(counts.get("upcoming_deadlines_count") or 0),
        "agent_assigned_open_count": int(counts.get("agent_assigned_open_count") or 0),
    }

    email_context = {
        "subject": rendered_subject,
        "agent_name": token_map["AGENT_NAME"],
        "property_address": token_map["PROPERTY_ADDRESS"],
        "transaction_id": transaction_id,
        "closing_date_label": _format_date(closing_date),
        "days_to_closing": days_to_closing,
        "days_to_closing_label": days_to_closing_label,
        "health_status": health_status,
        "health_label": health_label,
        "progress_pct": int(progress["progress_pct"]),
        "tasks_completed_week_count": metrics_summary["tasks_completed_week"],
        "documents_uploaded_week_count": metrics_summary["documents_uploaded_week"],
        "communications_week_count": metrics_summary["communications_week"],
        "upcoming_deadlines_count": metrics_summary["upcoming_deadlines_count"],
        "agent_assigned_open_count": metrics_summary["agent_assigned_open_count"],
        "completed_tasks": completed_tasks,
        "uploaded_documents": uploaded_docs,
        "communications_this_week": communications,
        "in_progress_items": in_progress,
        "due_this_week_items": upcoming_deadlines,
        "agent_action_items": agent_actions,
        "urgent_items": urgent_items,
        "custom_message_lines": custom_message_lines,
        "week_start_label": _format_date(week_start),
        "week_end_label": _format_date(week_end - timedelta(days=1)),
    }

    return {
        "transaction_id": transaction_id,
        "property_address": token_map["PROPERTY_ADDRESS"],
        "agent_name": token_map["AGENT_NAME"],
        "agent_email": _normalize_email(transaction_row.get("agent_email")),
        "health_status": health_status,
        "progress_pct": int(progress["progress_pct"]),
        "days_to_closing": days_to_closing,
        "days_to_closing_label": days_to_closing_label,
        "urgent_items": urgent_items,
        "in_progress_items": in_progress,
        "due_this_week_items": upcoming_deadlines,
        "agent_action_items": agent_actions,
        "metrics_summary": metrics_summary,
        "subject": rendered_subject,
        "rendered_body": rendered_body,
        "email_context": email_context,
    }


def build_agent_status_update_payloads(settings=None, template_overrides=None, reference_dt=None, limit=None):
    ensure_agent_status_update_tables()
    settings_row = settings or fetch_agent_status_update_settings()
    transactions = _fetch_active_transactions()
    opt_out = _fetch_opt_out_lookup()
    payloads = []

    for transaction in transactions:
        if _is_opted_out(transaction, opt_out):
            continue
        if not _normalize_email(transaction.get("agent_email")):
            continue
        payloads.append(
            _build_transaction_payload(
                transaction_row=transaction,
                settings=settings_row,
                template_overrides=template_overrides,
                reference_dt=reference_dt,
            )
        )
        if limit and len(payloads) >= int(limit):
            break
    return payloads


def _create_status_update_run(
    run_kind,
    preview_only,
    triggered_by,
    schedule_slot,
    schedule_week_key,
    candidate_count,
    notes="",
):
    rows = execute_query(
        """
        INSERT INTO agent_status_update_runs (
            run_kind, preview_only, triggered_by, schedule_slot, schedule_week_key,
            candidate_count, status, notes, started_at
        )
        VALUES (%s, %s, %s, %s, %s, %s, 'running', %s, CURRENT_TIMESTAMP)
        RETURNING id
        """,
        (
            (run_kind or "manual")[:30],
            bool(preview_only),
            (triggered_by or "margaret")[:100],
            (schedule_slot or "")[:30] or None,
            (schedule_week_key or "")[:40] or None,
            int(candidate_count or 0),
            (notes or "")[:1000] or None,
        ),
        fetch=True,
    ) or []
    return rows[0]["id"] if rows else None


def _record_status_update_message(run_id, payload, status, failure_reason=None, sent_at=None):
    execute_query(
        """
        INSERT INTO agent_status_update_messages (
            run_id, transaction_id, agent_name, agent_email, property_address,
            health_status, progress_pct, days_to_closing, urgent_item_count,
            tasks_completed_week, documents_uploaded_week, communications_week,
            upcoming_deadlines_count, agent_action_items_count, subject, rendered_body,
            status, failure_reason, sent_at, created_at
        )
        VALUES (
            %s, %s, %s, %s, %s,
            %s, %s, %s, %s,
            %s, %s, %s,
            %s, %s, %s, %s,
            %s, %s, %s, CURRENT_TIMESTAMP
        )
        """,
        (
            run_id,
            payload["transaction_id"],
            (payload.get("agent_name") or "")[:255],
            (payload.get("agent_email") or "")[:255],
            (payload.get("property_address") or "")[:255],
            (payload.get("health_status") or "")[:20],
            int(payload.get("progress_pct") or 0),
            payload.get("days_to_closing"),
            len(payload.get("urgent_items") or []),
            int(payload.get("metrics_summary", {}).get("tasks_completed_week") or 0),
            int(payload.get("metrics_summary", {}).get("documents_uploaded_week") or 0),
            int(payload.get("metrics_summary", {}).get("communications_week") or 0),
            int(payload.get("metrics_summary", {}).get("upcoming_deadlines_count") or 0),
            len(payload.get("agent_action_items") or []),
            (payload.get("subject") or "")[:255],
            (payload.get("rendered_body") or "")[:8000],
            (status or "preview")[:20],
            (failure_reason or "")[:1000] if failure_reason else None,
            sent_at,
        ),
    )


def _finalize_status_update_run(run_id, sent_count, failed_count, status, notes, question_metrics):
    execute_query(
        """
        UPDATE agent_status_update_runs
        SET sent_count = %s,
            failed_count = %s,
            status = %s,
            notes = %s,
            questions_this_week = %s,
            questions_previous_week = %s,
            question_reduction_estimate = %s,
            completed_at = CURRENT_TIMESTAMP
        WHERE id = %s
        """,
        (
            int(sent_count or 0),
            int(failed_count or 0),
            (status or "completed")[:20],
            (notes or "")[:1000] if notes else None,
            int(question_metrics.get("current_count") or 0),
            int(question_metrics.get("previous_count") or 0),
            int(question_metrics.get("answered_questions_estimate") or 0),
            run_id,
        ),
    )


def _has_scheduled_run_for_week(schedule_week_key):
    rows = execute_query(
        """
        SELECT id
        FROM agent_status_update_runs
        WHERE run_kind = 'scheduled'
          AND preview_only = FALSE
          AND COALESCE(schedule_week_key, '') = %s
          AND status = 'completed'
        ORDER BY id DESC
        LIMIT 1
        """,
        (schedule_week_key,),
        fetch=True,
    ) or []
    return bool(rows)


def dispatch_agent_status_updates(
    *,
    preview_only=False,
    run_kind="manual",
    triggered_by="margaret",
    template_overrides=None,
    reference_dt=None,
    force_send=False,
):
    """
    Build and optionally send weekly agent status updates.
    """
    ensure_agent_status_update_tables()
    settings = fetch_agent_status_update_settings()
    run_kind_value = (run_kind or "manual").strip().lower()
    preview_mode = bool(preview_only)
    slot = settings.get("schedule_slot") or "monday_8am"
    week_key = _schedule_week_key(slot, reference_dt)

    if run_kind_value == "scheduled" and not settings.get("enabled"):
        return {
            "success": True,
            "skipped": True,
            "reason": "disabled",
            "sent_count": 0,
            "failed_count": 0,
            "payloads": [],
        }

    if run_kind_value == "scheduled" and not preview_mode and not force_send and _has_scheduled_run_for_week(week_key):
        return {
            "success": True,
            "skipped": True,
            "reason": "already_sent_this_week",
            "sent_count": 0,
            "failed_count": 0,
            "payloads": [],
        }

    payloads = build_agent_status_update_payloads(
        settings=settings,
        template_overrides=template_overrides,
        reference_dt=reference_dt,
    )
    run_id = _create_status_update_run(
        run_kind=run_kind_value,
        preview_only=preview_mode,
        triggered_by=triggered_by,
        schedule_slot=slot if run_kind_value == "scheduled" else None,
        schedule_week_key=week_key if run_kind_value == "scheduled" else None,
        candidate_count=len(payloads),
        notes=("Preview only" if preview_mode else ""),
    )
    if not run_id:
        return {"success": False, "error": "Failed to create status update run."}

    sent_count = 0
    failed_count = 0
    status_value = "completed"
    notes = ""

    for payload in payloads:
        if preview_mode:
            _record_status_update_message(run_id, payload, status="preview")
            continue

        message_id = send_email(
            to=payload["agent_email"],
            template="emails/agent_status_update.html",
            data=payload["email_context"],
        )
        if message_id:
            sent_count += 1
            _record_status_update_message(
                run_id,
                payload,
                status="sent",
                sent_at=datetime.now(),
            )
            execute_query(
                """
                INSERT INTO communications (
                    transaction_id, communication_type, contact_party, contact_name, summary, outcome
                )
                VALUES (%s, 'email', 'agent', %s, %s, %s)
                """,
                (
                    payload["transaction_id"],
                    payload.get("agent_name") or "Agent",
                    "Weekly transaction status update sent",
                    (
                        f"to={payload.get('agent_email')} "
                        f"health={payload.get('health_status')} "
                        f"progress={payload.get('progress_pct')}%"
                    ),
                ),
            )
            continue

        failed_count += 1
        _record_status_update_message(
            run_id,
            payload,
            status="failed",
            failure_reason="Email send failed",
        )

    if not preview_mode and failed_count > 0 and sent_count == 0:
        status_value = "failed"
        notes = "All status updates failed to send."
    elif preview_mode:
        notes = "Preview generated."
    elif failed_count > 0:
        notes = "Partial success."
    else:
        notes = "Status updates sent."

    question_metrics = _fetch_question_reduction_metrics(reference_dt=reference_dt)
    _finalize_status_update_run(
        run_id=run_id,
        sent_count=sent_count,
        failed_count=failed_count,
        status=status_value,
        notes=notes,
        question_metrics=question_metrics,
    )
    return {
        "success": True,
        "run_id": run_id,
        "preview_only": preview_mode,
        "sent_count": sent_count,
        "failed_count": failed_count,
        "candidate_count": len(payloads),
        "payloads": payloads,
        "question_metrics": question_metrics,
    }


def run_scheduled_agent_status_updates(reference_dt=None):
    """Run scheduled weekly status update send if current hour matches configured slot."""
    ensure_agent_status_update_tables()
    now_dt = reference_dt if isinstance(reference_dt, datetime) else datetime.now()
    settings = fetch_agent_status_update_settings()
    schedule_slot = settings.get("schedule_slot") or "monday_8am"

    if not settings.get("enabled"):
        return {"success": True, "skipped": True, "reason": "disabled"}
    if not _is_schedule_due(now_dt, schedule_slot):
        return {"success": True, "skipped": True, "reason": "not_due"}

    return dispatch_agent_status_updates(
        preview_only=False,
        run_kind="scheduled",
        triggered_by="cron",
        reference_dt=now_dt,
        force_send=False,
    )


def fetch_agent_status_update_runs(limit=20):
    ensure_agent_status_update_tables()
    rows = execute_query(
        """
        SELECT id, run_kind, preview_only, triggered_by, schedule_slot, schedule_week_key,
               started_at, completed_at, status, candidate_count, sent_count, failed_count,
               questions_this_week, questions_previous_week, question_reduction_estimate, notes
        FROM agent_status_update_runs
        ORDER BY id DESC
        LIMIT %s
        """,
        (int(limit),),
        fetch=True,
    ) or []
    for row in rows:
        row["started_at_label"] = _format_datetime(row.get("started_at"))
        row["completed_at_label"] = _format_datetime(row.get("completed_at"))
        row["schedule_label"] = _schedule_slot_label(row.get("schedule_slot"))
    return rows


def fetch_agent_status_update_metrics(weeks=8, reference_dt=None):
    ensure_agent_status_update_tables()
    question_metrics = _fetch_question_reduction_metrics(reference_dt=reference_dt)
    week_start, week_end = _week_bounds(reference_dt)

    sent_rows = execute_query(
        """
        SELECT COUNT(*) AS sent_count
        FROM agent_status_update_messages
        WHERE status = 'sent'
          AND sent_at >= %s
          AND sent_at < %s
        """,
        (_to_dt_day_start(week_start), _to_dt_day_start(week_end)),
        fetch=True,
    ) or []
    this_week_sent = int(sent_rows[0]["sent_count"]) if sent_rows else 0

    start_window = week_start - timedelta(days=max(int(weeks), 1) * 7)
    run_rows = execute_query(
        """
        SELECT DATE_TRUNC('week', started_at)::date AS week_start,
               SUM(candidate_count) AS candidate_count,
               SUM(sent_count) AS sent_count,
               SUM(failed_count) AS failed_count,
               COUNT(*) AS run_count
        FROM agent_status_update_runs
        WHERE started_at >= %s
          AND preview_only = FALSE
        GROUP BY DATE_TRUNC('week', started_at)
        ORDER BY week_start DESC
        LIMIT %s
        """,
        (_to_dt_day_start(start_window), int(weeks)),
        fetch=True,
    ) or []

    weekly = []
    for row in reversed(run_rows):
        week_item_start = row.get("week_start")
        if not week_item_start:
            continue
        next_week_start = week_item_start + timedelta(days=7)
        status_checks = _status_check_count(_to_dt_day_start(week_item_start), _to_dt_day_start(next_week_start))
        weekly.append(
            {
                "week_start": week_item_start,
                "week_label": week_item_start.strftime("%b %d"),
                "run_count": int(row.get("run_count") or 0),
                "candidate_count": int(row.get("candidate_count") or 0),
                "sent_count": int(row.get("sent_count") or 0),
                "failed_count": int(row.get("failed_count") or 0),
                "status_checks": status_checks,
            }
        )

    return {
        "this_week_sent": this_week_sent,
        "this_week_status_checks": question_metrics["current_count"],
        "previous_week_status_checks": question_metrics["previous_count"],
        "reduction_count": question_metrics["reduction_count"],
        "reduction_pct": question_metrics["reduction_pct"],
        "answered_questions_estimate": question_metrics["answered_questions_estimate"],
        "weekly": weekly,
    }
