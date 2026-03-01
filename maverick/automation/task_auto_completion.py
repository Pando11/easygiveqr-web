#!/usr/bin/env python3
"""
Auto task completion engine.

Runs on a schedule (recommended every 15 minutes) to evaluate incomplete tasks
against completion rules and automatically close low-risk tasks when criteria
are met with high confidence.
"""

from __future__ import annotations

import json
import os
import re
import sys
from datetime import date, datetime, timedelta
from pathlib import Path

from dotenv import load_dotenv

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
load_dotenv()

from utils.db import execute_query

HIGH_STAKES_PATTERNS = (
    "verify final cd accurate",
    "final cd accurate",
    "confirm final cd",
    "verify settlement statement",
    "wire fraud",
)

DOC_TYPE_ALIASES = {
    "earnest_money_receipt": ["earnest_money_receipt", "earnest_receipt"],
    "inspection_report": ["inspection_report", "inspection"],
    "hoa_documents": ["hoa_documents", "hoa_docs", "hoa"],
    "title_commitment": ["title_commitment"],
}

DEFAULT_COMPLETION_RULES = [
    {
        "task_description_pattern": "Verify earnest money receipt",
        "completion_trigger_type": "document_uploaded",
        "completion_criteria": {"document_type": "earnest_money_receipt"},
    },
    {
        "task_description_pattern": "Confirm inspection scheduled",
        "completion_trigger_type": "vendor_response",
        "completion_criteria": {"vendor_type": "inspector", "keywords": ["scheduled", "appointment"]},
    },
    {
        "task_description_pattern": "Verify title opened",
        "completion_trigger_type": "email_received",
        "completion_criteria": {"from_party": "title", "keywords": ["file opened", "file number"]},
    },
]


def parse_json_field(raw_value, default_value):
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


def ensure_task_completion_tables():
    """Create rule + log tables and seed defaults."""
    execute_query(
        """
        CREATE TABLE IF NOT EXISTS task_completion_rules (
            id SERIAL PRIMARY KEY,
            task_description_pattern VARCHAR(500) NOT NULL,
            completion_trigger_type VARCHAR(50) NOT NULL,
            completion_criteria JSONB DEFAULT '{}'::jsonb,
            confidence_threshold INT DEFAULT 80,
            active BOOLEAN DEFAULT TRUE,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
        """
    )
    execute_query(
        """
        CREATE TABLE IF NOT EXISTS task_auto_completion_log (
            id SERIAL PRIMARY KEY,
            task_id INT REFERENCES tasks(id) ON DELETE CASCADE,
            transaction_id INT REFERENCES transactions(id) ON DELETE CASCADE,
            rule_id INT REFERENCES task_completion_rules(id) ON DELETE SET NULL,
            action VARCHAR(50) NOT NULL,
            confidence INT,
            explanation TEXT,
            snapshot JSONB DEFAULT '{}'::jsonb,
            review_required BOOLEAN DEFAULT FALSE,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            undone_by VARCHAR(100),
            undone_at TIMESTAMP
        )
        """
    )
    execute_query(
        """
        CREATE UNIQUE INDEX IF NOT EXISTS idx_task_completion_rules_unique
        ON task_completion_rules(task_description_pattern, completion_trigger_type)
        """
    )
    execute_query(
        """
        CREATE INDEX IF NOT EXISTS idx_task_auto_completion_log_task
        ON task_auto_completion_log(task_id, created_at DESC)
        """
    )
    execute_query(
        """
        CREATE INDEX IF NOT EXISTS idx_task_auto_completion_log_action
        ON task_auto_completion_log(action, created_at DESC)
        """
    )

    for rule in DEFAULT_COMPLETION_RULES:
        execute_query(
            """
            INSERT INTO task_completion_rules (
                task_description_pattern,
                completion_trigger_type,
                completion_criteria,
                confidence_threshold,
                active,
                created_at,
                updated_at
            )
            VALUES (%s, %s, %s::jsonb, 80, TRUE, CURRENT_TIMESTAMP, CURRENT_TIMESTAMP)
            ON CONFLICT (task_description_pattern, completion_trigger_type)
            DO NOTHING
            """,
            (
                rule["task_description_pattern"],
                rule["completion_trigger_type"],
                json.dumps(rule["completion_criteria"]),
            ),
        )


def fetch_task_completion_rules(active_only=True):
    """Return completion rules."""
    ensure_task_completion_tables()
    active_clause = "WHERE active = TRUE" if active_only else ""
    rows = execute_query(
        f"""
        SELECT id, task_description_pattern, completion_trigger_type, completion_criteria,
               confidence_threshold, active, created_at, updated_at
        FROM task_completion_rules
        {active_clause}
        ORDER BY id ASC
        """,
        fetch=True,
    ) or []
    for row in rows:
        row["completion_criteria"] = parse_json_field(row.get("completion_criteria"), {})
    return rows


def upsert_task_completion_rule(
    task_description_pattern,
    completion_trigger_type,
    completion_criteria,
    confidence_threshold=80,
    active=True,
):
    """Create/update one completion rule row."""
    ensure_task_completion_tables()
    pattern = (task_description_pattern or "").strip()
    trigger = (completion_trigger_type or "").strip().lower()
    if not pattern or not trigger:
        return False
    criteria = completion_criteria or {}
    try:
        threshold = max(0, min(int(confidence_threshold), 100))
    except (TypeError, ValueError):
        threshold = 80
    execute_query(
        """
        INSERT INTO task_completion_rules (
            task_description_pattern, completion_trigger_type, completion_criteria,
            confidence_threshold, active, updated_at
        )
        VALUES (%s, %s, %s::jsonb, %s, %s, CURRENT_TIMESTAMP)
        ON CONFLICT (task_description_pattern, completion_trigger_type)
        DO UPDATE SET
            completion_criteria = EXCLUDED.completion_criteria,
            confidence_threshold = EXCLUDED.confidence_threshold,
            active = EXCLUDED.active,
            updated_at = CURRENT_TIMESTAMP
        """,
        (pattern, trigger, json.dumps(criteria), threshold, bool(active)),
    )
    return True


def disable_task_completion_rule(rule_id):
    try:
        rule_id = int(rule_id)
    except (TypeError, ValueError):
        return False
    execute_query(
        """
        UPDATE task_completion_rules
        SET active = FALSE,
            updated_at = CURRENT_TIMESTAMP
        WHERE id = %s
        """,
        (rule_id,),
    )
    return True


def _rule_matches_task(pattern, task_description):
    pattern_text = (pattern or "").strip().lower()
    task_text = (task_description or "").strip().lower()
    if not pattern_text or not task_text:
        return False
    if pattern_text in task_text:
        return True
    if "%" in pattern_text or "_" in pattern_text:
        regex = re.escape(pattern_text).replace(r"\%", ".*").replace(r"\_", ".")
        return bool(re.search(regex, task_text))
    words = [word for word in re.split(r"[^a-z0-9]+", pattern_text) if len(word) > 2]
    if words and all(word in task_text for word in words):
        return True
    return False


def _is_high_stakes_task(task_description):
    text = (task_description or "").strip().lower()
    return any(pattern in text for pattern in HIGH_STAKES_PATTERNS)


def _normalize_doc_types(document_type):
    doc_type = (document_type or "").strip().lower()
    if not doc_type:
        return []
    return DOC_TYPE_ALIASES.get(doc_type, [doc_type])


def _evaluate_document_uploaded(task, criteria):
    doc_type = (criteria.get("document_type") or "").strip().lower()
    doc_types = _normalize_doc_types(doc_type)
    if not doc_types:
        return {"matched": False}

    rows = execute_query(
        """
        SELECT id, document_type, uploaded_at
        FROM documents
        WHERE transaction_id = %s
          AND LOWER(COALESCE(document_type, '')) = ANY(%s)
        ORDER BY uploaded_at DESC, id DESC
        LIMIT 1
        """,
        (task["transaction_id"], doc_types),
        fetch=True,
    ) or []
    if not rows:
        return {"matched": False}
    doc = rows[0]
    uploaded_at = doc.get("uploaded_at")
    uploaded_label = uploaded_at.strftime("%b %d, %Y %I:%M %p") if uploaded_at else "recently"
    return {
        "matched": True,
        "confidence": 95,
        "explanation": f"Document '{doc.get('document_type')}' uploaded {uploaded_label}.",
        "snapshot": {"document_id": doc.get("id"), "document_type": doc.get("document_type")},
    }


def _evaluate_vendor_response(task, criteria):
    vendor_type = (criteria.get("vendor_type") or "").strip().lower()
    if vendor_type == "survey":
        vendor_type = "surveyor"
    keywords = [(item or "").strip().lower() for item in (criteria.get("keywords") or []) if (item or "").strip()]

    rows = execute_query(
        """
        SELECT id, outreach_type, outreach_date, response_received, response_date, scheduled_date, notes
        FROM vendor_outreach_log
        WHERE transaction_id = %s
          AND LOWER(COALESCE(vendor_type, '')) = %s
          AND (
                response_received = TRUE
             OR LOWER(COALESCE(outreach_type, '')) IN ('response_received', 'scheduled')
          )
        ORDER BY COALESCE(response_date, outreach_date) DESC, id DESC
        LIMIT 5
        """,
        (task["transaction_id"], vendor_type),
        fetch=True,
    ) or []
    if not rows:
        return {"matched": False}

    row = rows[0]
    event_text = " ".join(
        [
            (row.get("outreach_type") or ""),
            (row.get("notes") or ""),
            "scheduled" if row.get("scheduled_date") else "",
        ]
    ).lower()
    keyword_hits = sum(1 for keyword in keywords if keyword in event_text)
    all_keywords_match = bool(keywords) and keyword_hits == len(keywords)

    if row.get("scheduled_date"):
        confidence = 95
    elif all_keywords_match:
        confidence = 88
    elif keyword_hits > 0 or row.get("response_received"):
        confidence = 76
    else:
        return {"matched": False}

    response_label = row.get("response_date") or row.get("outreach_date")
    response_label = response_label.strftime("%b %d, %Y %I:%M %p") if response_label else "recently"
    return {
        "matched": True,
        "confidence": confidence,
        "explanation": f"Vendor response activity detected ({vendor_type}) on {response_label}.",
        "snapshot": {"vendor_outreach_log_id": row.get("id"), "vendor_type": vendor_type, "keyword_hits": keyword_hits},
    }


def _evaluate_email_received(task, criteria):
    from_party = (criteria.get("from_party") or "").strip().lower()
    keywords = [(item or "").strip().lower() for item in (criteria.get("keywords") or []) if (item or "").strip()]
    if not from_party:
        return {"matched": False}

    rows = execute_query(
        """
        SELECT id, communication_type, contact_party, summary, outcome, created_at
        FROM communications
        WHERE transaction_id = %s
          AND LOWER(COALESCE(contact_party, '')) = %s
          AND LOWER(COALESCE(communication_type, '')) IN ('email', 'note')
        ORDER BY created_at DESC, id DESC
        LIMIT 20
        """,
        (task["transaction_id"], from_party),
        fetch=True,
    ) or []
    if not rows:
        return {"matched": False}

    text_blob = " ".join(
        [f"{row.get('summary') or ''} {row.get('outcome') or ''}" for row in rows[:6]]
    ).lower()
    if keywords:
        hits = sum(1 for keyword in keywords if keyword in text_blob)
        if hits == len(keywords):
            confidence = 90
        elif hits > 0:
            confidence = 72
        else:
            return {"matched": False}
    else:
        hits = 0
        confidence = 82

    latest = rows[0]
    created_at = latest.get("created_at")
    created_label = created_at.strftime("%b %d, %Y %I:%M %p") if created_at else "recently"
    return {
        "matched": True,
        "confidence": confidence,
        "explanation": f"{from_party.title()} email/note activity matched completion criteria ({created_label}).",
        "snapshot": {"communication_id": latest.get("id"), "from_party": from_party, "keyword_hits": hits},
    }


def _recent_log_exists(task_id, rule_id, action, window_hours=24):
    rows = execute_query(
        """
        SELECT id
        FROM task_auto_completion_log
        WHERE task_id = %s
          AND COALESCE(rule_id, 0) = COALESCE(%s, 0)
          AND action = %s
          AND created_at >= (CURRENT_TIMESTAMP - (%s || ' hours')::interval)
        LIMIT 1
        """,
        (task_id, rule_id, action, int(window_hours)),
        fetch=True,
    ) or []
    return bool(rows)


def _append_task_note(task_id, note_text):
    if not note_text:
        return
    timestamp = datetime.now().strftime("%Y-%m-%d %H:%M")
    note_entry = f"[{timestamp}] {note_text}"
    execute_query(
        """
        UPDATE tasks
        SET notes = CASE
            WHEN COALESCE(notes, '') = '' THEN %s
            ELSE notes || E'\n' || %s
        END
        WHERE id = %s
        """,
        (note_entry, note_entry, task_id),
    )


def _write_log(task, rule_id, action, confidence, explanation, snapshot=None, review_required=False):
    execute_query(
        """
        INSERT INTO task_auto_completion_log (
            task_id, transaction_id, rule_id, action, confidence, explanation, snapshot, review_required, created_at
        )
        VALUES (%s, %s, %s, %s, %s, %s, %s::jsonb, %s, CURRENT_TIMESTAMP)
        """,
        (
            task["id"],
            task["transaction_id"],
            rule_id,
            action,
            confidence,
            (explanation or "")[:1200],
            json.dumps(snapshot or {}, default=str),
            bool(review_required),
        ),
    )


def _mark_task_completed(task, rule, evaluation):
    explanation = evaluation.get("explanation") or "Completion criteria met."
    execute_query(
        """
        UPDATE tasks
        SET completed = TRUE,
            status = 'completed',
            completed_at = CURRENT_TIMESTAMP,
            completed_by = 'auto-rule-engine'
        WHERE id = %s
          AND completed = FALSE
          AND COALESCE(status, 'pending') <> 'completed'
        """,
        (task["id"],),
    )
    _append_task_note(task["id"], f"[Auto-completed] {explanation}")
    _write_log(
        task=task,
        rule_id=rule.get("id"),
        action="auto_completed",
        confidence=int(evaluation.get("confidence") or 0),
        explanation=explanation,
        snapshot=evaluation.get("snapshot") or {},
        review_required=False,
    )


def _flag_for_review(task, rule, evaluation):
    confidence = int(evaluation.get("confidence") or 0)
    explanation = evaluation.get("explanation") or "Potential completion trigger found."
    if not _recent_log_exists(task["id"], rule.get("id"), "flagged_review", window_hours=24):
        _append_task_note(
            task["id"],
            (
                "[Auto-complete review needed] "
                f"Potential trigger matched at {confidence}% confidence (<80%). "
                f"{explanation}"
            ),
        )
        _write_log(
            task=task,
            rule_id=rule.get("id"),
            action="flagged_review",
            confidence=confidence,
            explanation=explanation,
            snapshot=evaluation.get("snapshot") or {},
            review_required=True,
        )


def _evaluate_rule(task, rule):
    trigger = (rule.get("completion_trigger_type") or "").strip().lower()
    criteria = rule.get("completion_criteria") or {}
    if trigger == "document_uploaded":
        return _evaluate_document_uploaded(task, criteria)
    if trigger == "vendor_response":
        return _evaluate_vendor_response(task, criteria)
    if trigger == "email_received":
        return _evaluate_email_received(task, criteria)
    return {"matched": False}


def check_task_completion(limit=800):
    """
    Evaluate incomplete tasks against completion rules and auto-complete when safe.
    """
    ensure_task_completion_tables()
    rules = fetch_task_completion_rules(active_only=True)
    if not rules:
        return {
            "checked_tasks": 0,
            "auto_completed": 0,
            "flagged_review": 0,
            "skipped_high_stakes": 0,
        }

    tasks = execute_query(
        """
        SELECT tk.id, tk.transaction_id, tk.task_description, tk.status, tk.completed, tk.priority, tk.due_date
        FROM tasks tk
        JOIN transactions t ON t.id = tk.transaction_id
        WHERE tk.completed = FALSE
          AND COALESCE(tk.status, 'pending') <> 'completed'
          AND t.status = 'ACTIVE'
        ORDER BY tk.due_date ASC NULLS LAST, tk.id ASC
        LIMIT %s
        """,
        (int(limit),),
        fetch=True,
    ) or []

    summary = {
        "checked_tasks": len(tasks),
        "auto_completed": 0,
        "flagged_review": 0,
        "skipped_high_stakes": 0,
    }
    for task in tasks:
        description = task.get("task_description") or ""
        for rule in rules:
            if not _rule_matches_task(rule.get("task_description_pattern"), description):
                continue

            evaluation = _evaluate_rule(task, rule)
            if not evaluation.get("matched"):
                continue

            confidence = int(evaluation.get("confidence") or 0)
            threshold = int(rule.get("confidence_threshold") or 80)
            threshold = max(0, min(threshold, 100))

            if _is_high_stakes_task(description):
                if not _recent_log_exists(task["id"], rule.get("id"), "skipped_high_stakes", window_hours=24):
                    _write_log(
                        task=task,
                        rule_id=rule.get("id"),
                        action="skipped_high_stakes",
                        confidence=confidence,
                        explanation="High-stakes task is excluded from auto-completion.",
                        snapshot=evaluation.get("snapshot") or {},
                        review_required=True,
                    )
                summary["skipped_high_stakes"] += 1
                break

            if confidence < 80 or confidence < threshold:
                _flag_for_review(task, rule, evaluation)
                summary["flagged_review"] += 1
                break

            _mark_task_completed(task, rule, evaluation)
            summary["auto_completed"] += 1
            break

    return summary


def record_auto_completion_undo(task_id, undone_by="margaret"):
    """Mark latest auto-completed log entry for task as undone."""
    ensure_task_completion_tables()
    try:
        task_id = int(task_id)
    except (TypeError, ValueError):
        return False
    rows = execute_query(
        """
        WITH latest AS (
            SELECT id
            FROM task_auto_completion_log
            WHERE task_id = %s
              AND action = 'auto_completed'
              AND undone_at IS NULL
            ORDER BY id DESC
            LIMIT 1
        )
        UPDATE task_auto_completion_log l
        SET undone_by = %s,
            undone_at = CURRENT_TIMESTAMP
        FROM latest
        WHERE l.id = latest.id
        RETURNING l.id
        """,
        (task_id, (undone_by or "margaret")[:100]),
        fetch=True,
    ) or []
    if not rows:
        return False
    execute_query(
        """
        INSERT INTO task_auto_completion_log (
            task_id, transaction_id, rule_id, action, confidence, explanation, snapshot, review_required, created_at
        )
        SELECT task_id, transaction_id, rule_id, 'undone', NULL,
               %s, '{}'::jsonb, FALSE, CURRENT_TIMESTAMP
        FROM task_auto_completion_log
        WHERE id = %s
        """,
        (f"Auto-completion undone by {(undone_by or 'margaret')[:100]}", rows[0]["id"]),
    )
    return True


def fetch_task_auto_completion_metrics(weeks=8):
    """Return weekly auto-completion performance metrics."""
    ensure_task_completion_tables()
    window_start = date.today() - timedelta(days=max(int(weeks), 1) * 7)
    weekly_rows = execute_query(
        """
        SELECT
            DATE_TRUNC('week', created_at)::date AS week_start,
            COUNT(*) FILTER (WHERE action = 'auto_completed') AS auto_completed_count,
            COUNT(*) FILTER (WHERE action = 'flagged_review') AS flagged_review_count,
            COUNT(*) FILTER (WHERE action = 'auto_completed' AND undone_at IS NOT NULL) AS undone_count
        FROM task_auto_completion_log
        WHERE created_at >= %s
        GROUP BY DATE_TRUNC('week', created_at)
        ORDER BY week_start DESC
        LIMIT %s
        """,
        (window_start, int(weeks)),
        fetch=True,
    ) or []

    weekly = []
    total_auto = 0
    total_flagged = 0
    total_undone = 0
    for row in reversed(weekly_rows):
        auto_count = int(row.get("auto_completed_count") or 0)
        flagged_count = int(row.get("flagged_review_count") or 0)
        undone_count = int(row.get("undone_count") or 0)
        net_auto = max(auto_count - undone_count, 0)
        weekly.append(
            {
                "week_start": row.get("week_start"),
                "week_label": row["week_start"].strftime("%b %d") if row.get("week_start") else "",
                "auto_completed_count": auto_count,
                "flagged_review_count": flagged_count,
                "undone_count": undone_count,
                "time_saved_minutes": net_auto * 8,
            }
        )
        total_auto += auto_count
        total_flagged += flagged_count
        total_undone += undone_count

    net_total_auto = max(total_auto - total_undone, 0)
    time_saved_minutes = net_total_auto * 8
    return {
        "weekly": weekly,
        "total_auto_completed": total_auto,
        "total_flagged_review": total_flagged,
        "total_undone": total_undone,
        "time_saved_minutes": time_saved_minutes,
        "time_saved_hours": round(time_saved_minutes / 60.0, 1),
        "this_week_auto_completed": weekly[-1]["auto_completed_count"] if weekly else 0,
        "this_week_time_saved_minutes": weekly[-1]["time_saved_minutes"] if weekly else 0,
    }


def main():
    summary = check_task_completion()
    print(
        f"Task auto-completion run complete: checked={summary['checked_tasks']} "
        f"auto_completed={summary['auto_completed']} flagged_review={summary['flagged_review']} "
        f"skipped_high_stakes={summary['skipped_high_stakes']}"
    )


if __name__ == "__main__":
    main()
