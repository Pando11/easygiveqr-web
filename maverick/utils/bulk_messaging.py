from __future__ import annotations

import json
import re
import threading
import time
from datetime import date, datetime, timedelta

from utils.db import execute_query
from utils.sms import send_sms

SMART_TEMPLATE_VARIABLES = [
    "PROPERTY_ADDRESS",
    "BUYER_NAME",
    "SELLER_NAME",
    "CLOSING_DATE",
    "CLOSING_TIME",
    "TITLE_COMPANY",
    "NEXT_DEADLINE",
    "DAYS_TO_CLOSING",
]

SYSTEM_BULK_TEMPLATES = [
    {
        "name": "Closing tomorrow reminder",
        "body": (
            "Hi {{BUYER_NAME}}, quick reminder that {{PROPERTY_ADDRESS}} is scheduled to close "
            "on {{CLOSING_DATE}} at {{CLOSING_TIME}}. Please confirm any final questions with "
            "your agent and title company ({{TITLE_COMPANY}}). - Maverick TC"
        ),
    },
    {
        "name": "Final walk-through confirmation",
        "body": (
            "Hi {{BUYER_NAME}}, this is your final walk-through check for {{PROPERTY_ADDRESS}}. "
            "Closing is in {{DAYS_TO_CLOSING}} day(s). Reply CONFIRMED once completed. - Maverick TC"
        ),
    },
    {
        "name": "Document request",
        "body": (
            "Hi {{SELLER_NAME}}, we still need a required document for {{PROPERTY_ADDRESS}}. "
            "Next deadline: {{NEXT_DEADLINE}}. Please upload/send today to keep closing on track. - Maverick TC"
        ),
    },
]

_RUNNING_JOB_IDS = set()
_JOB_LOCK = threading.Lock()


def ensure_bulk_messaging_tables():
    """Create bulk SMS tables and seed system templates."""
    execute_query(
        """
        CREATE TABLE IF NOT EXISTS bulk_messages_log (
            id SERIAL PRIMARY KEY,
            template_used VARCHAR(255),
            message_template TEXT,
            filter_scope VARCHAR(50),
            filter_status VARCHAR(50),
            party_type VARCHAR(30),
            transactions_affected INT DEFAULT 0,
            total_recipients INT DEFAULT 0,
            sent_count INT DEFAULT 0,
            failed_count INT DEFAULT 0,
            status VARCHAR(20) DEFAULT 'queued',
            created_by VARCHAR(100),
            summary JSONB DEFAULT '{}'::jsonb,
            sent_at TIMESTAMP,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            started_at TIMESTAMP,
            completed_at TIMESTAMP
        )
        """
    )
    execute_query(
        """
        CREATE TABLE IF NOT EXISTS bulk_message_recipients (
            id SERIAL PRIMARY KEY,
            bulk_message_id INT REFERENCES bulk_messages_log(id) ON DELETE CASCADE,
            transaction_id INT REFERENCES transactions(id) ON DELETE CASCADE,
            party_type VARCHAR(20),
            recipient_name VARCHAR(200),
            recipient_phone VARCHAR(25),
            rendered_message TEXT,
            status VARCHAR(20) DEFAULT 'pending',
            provider_message_sid VARCHAR(120),
            error_text TEXT,
            attempted_at TIMESTAMP,
            sent_at TIMESTAMP,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
        """
    )
    execute_query(
        """
        CREATE TABLE IF NOT EXISTS bulk_message_templates (
            id SERIAL PRIMARY KEY,
            template_name VARCHAR(120) UNIQUE NOT NULL,
            template_body TEXT NOT NULL,
            is_system BOOLEAN DEFAULT FALSE,
            active BOOLEAN DEFAULT TRUE,
            created_by VARCHAR(100),
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
        """
    )
    execute_query(
        """
        CREATE INDEX IF NOT EXISTS idx_bulk_messages_log_status
        ON bulk_messages_log(status, created_at DESC)
        """
    )
    execute_query(
        """
        CREATE INDEX IF NOT EXISTS idx_bulk_messages_log_sent_at
        ON bulk_messages_log(sent_at DESC)
        """
    )
    execute_query(
        """
        CREATE INDEX IF NOT EXISTS idx_bulk_message_recipients_bulk
        ON bulk_message_recipients(bulk_message_id, status, id)
        """
    )

    for template in SYSTEM_BULK_TEMPLATES:
        execute_query(
            """
            INSERT INTO bulk_message_templates (
                template_name, template_body, is_system, active, created_by, updated_at
            )
            VALUES (%s, %s, TRUE, TRUE, 'system', CURRENT_TIMESTAMP)
            ON CONFLICT (template_name)
            DO UPDATE SET
                template_body = EXCLUDED.template_body,
                is_system = TRUE,
                active = TRUE,
                updated_at = CURRENT_TIMESTAMP
            """,
            (template["name"], template["body"]),
        )


def normalize_phone(value):
    """Normalize values for SMS dispatch."""
    digits = re.sub(r"\D", "", value or "")
    if len(digits) == 10:
        return f"+1{digits}"
    if len(digits) == 11 and digits.startswith("1"):
        return f"+{digits}"
    if value and str(value).startswith("+"):
        return str(value).strip()
    return f"+{digits}" if digits else ""


def fetch_bulk_message_templates():
    """Return active templates for bulk messaging UI."""
    ensure_bulk_messaging_tables()
    return execute_query(
        """
        SELECT id, template_name, template_body, is_system, active, created_by, created_at, updated_at
        FROM bulk_message_templates
        WHERE active = TRUE
        ORDER BY is_system DESC, template_name ASC
        """,
        fetch=True,
    ) or []


def save_bulk_message_template(template_name, template_body, created_by="margaret"):
    """Save a custom reusable bulk SMS template."""
    ensure_bulk_messaging_tables()
    name = (template_name or "").strip()
    body = (template_body or "").strip()
    if not name or not body:
        return {"success": False, "error": "Template name and body are required."}
    if len(name) > 120:
        return {"success": False, "error": "Template name is too long (max 120 chars)."}
    if len(body) > 2000:
        return {"success": False, "error": "Template body is too long (max 2000 chars)."}

    existing = execute_query(
        """
        SELECT id, is_system
        FROM bulk_message_templates
        WHERE LOWER(template_name) = LOWER(%s)
        LIMIT 1
        """,
        (name,),
        fetch=True,
    ) or []
    if existing and existing[0].get("is_system"):
        return {"success": False, "error": "Cannot overwrite a built-in template name."}

    execute_query(
        """
        INSERT INTO bulk_message_templates (
            template_name, template_body, is_system, active, created_by, updated_at
        )
        VALUES (%s, %s, FALSE, TRUE, %s, CURRENT_TIMESTAMP)
        ON CONFLICT (template_name)
        DO UPDATE SET
            template_body = EXCLUDED.template_body,
            active = TRUE,
            created_by = EXCLUDED.created_by,
            updated_at = CURRENT_TIMESTAMP
        """,
        (name, body, (created_by or "margaret")[:100]),
    )
    return {"success": True}


def _deadline_label(deadline_type, deadline_date):
    if not deadline_type or not deadline_date:
        return "No upcoming deadline"
    pretty = str(deadline_type).replace("_", " ").title()
    return f"{pretty} ({deadline_date.strftime('%b %d')})"


def _render_message_template(template_body, variables):
    body = template_body or ""

    def repl(match):
        key = (match.group(1) or "").strip().upper()
        return str(variables.get(key, ""))

    return re.sub(r"\{\{\s*([A-Za-z0-9_]+)\s*\}\}", repl, body)


def _fetch_transactions_for_filter(filter_scope, filter_status):
    scope = (filter_scope or "all_active").strip().lower()
    status_value = (filter_status or "").strip().upper()
    today = date.today()
    week_end = today + timedelta(days=7)

    where_clauses = []
    params = []
    if scope == "closing_this_week":
        where_clauses.append("t.status = 'ACTIVE'")
        where_clauses.append("t.closing_date IS NOT NULL")
        where_clauses.append("t.closing_date >= %s")
        where_clauses.append("t.closing_date <= %s")
        params.extend([today, week_end])
    elif scope == "specific_status" and status_value:
        where_clauses.append("t.status = %s")
        params.append(status_value)
    else:
        where_clauses.append("t.status = 'ACTIVE'")

    where_sql = " AND ".join(where_clauses) if where_clauses else "TRUE"
    return execute_query(
        f"""
        SELECT
            t.id,
            t.status,
            t.property_address,
            t.buyer_name,
            t.buyer_phone,
            t.seller_name,
            t.seller_phone,
            t.agent_name,
            t.agent_phone,
            t.closing_date,
            t.title_company,
            nd.deadline_type AS next_deadline_type,
            nd.deadline_date AS next_deadline_date
        FROM transactions t
        LEFT JOIN LATERAL (
            SELECT d.deadline_type, d.deadline_date
            FROM deadlines d
            WHERE d.transaction_id = t.id
              AND d.completed = FALSE
              AND d.deadline_date >= CURRENT_DATE
            ORDER BY d.deadline_date ASC, d.id ASC
            LIMIT 1
        ) nd ON TRUE
        WHERE {where_sql}
        ORDER BY COALESCE(t.closing_date, CURRENT_DATE + INTERVAL '365 days') ASC, t.id ASC
        """,
        tuple(params),
        fetch=True,
    ) or []


def _recipient_targets(transaction, party_type):
    mode = (party_type or "all_parties").strip().lower()
    all_targets = []
    buyer_phone = normalize_phone(transaction.get("buyer_phone"))
    seller_phone = normalize_phone(transaction.get("seller_phone"))
    agent_phone = normalize_phone(transaction.get("agent_phone"))

    if buyer_phone:
        all_targets.append(
            {
                "party_type": "buyer",
                "recipient_name": transaction.get("buyer_name") or "Buyer",
                "recipient_phone": buyer_phone,
            }
        )
    if seller_phone:
        all_targets.append(
            {
                "party_type": "seller",
                "recipient_name": transaction.get("seller_name") or "Seller",
                "recipient_phone": seller_phone,
            }
        )
    if agent_phone:
        all_targets.append(
            {
                "party_type": "agent",
                "recipient_name": transaction.get("agent_name") or "Agent",
                "recipient_phone": agent_phone,
            }
        )

    if mode == "buyers_only":
        return [target for target in all_targets if target["party_type"] == "buyer"]
    if mode == "sellers_only":
        return [target for target in all_targets if target["party_type"] == "seller"]
    if mode == "agents_only":
        return [target for target in all_targets if target["party_type"] == "agent"]
    return all_targets


def build_bulk_message_preview(
    template_body,
    filter_scope="all_active",
    filter_status="",
    party_type="all_parties",
    max_preview_rows=120,
):
    """Build a personalized preview list for selected transaction/party filters."""
    transactions = _fetch_transactions_for_filter(filter_scope, filter_status)
    today = date.today()
    sendable_rows = []
    preview_rows = []
    tx_ids = set()

    for transaction in transactions:
        closing_date = transaction.get("closing_date")
        days_to_closing = (closing_date - today).days if closing_date else ""
        variables = {
            "PROPERTY_ADDRESS": transaction.get("property_address") or "",
            "BUYER_NAME": transaction.get("buyer_name") or "Buyer",
            "SELLER_NAME": transaction.get("seller_name") or "Seller",
            "CLOSING_DATE": closing_date.strftime("%b %d, %Y") if closing_date else "TBD",
            "CLOSING_TIME": (transaction.get("closing_time") or "") if transaction.get("closing_time") else "TBD",
            "TITLE_COMPANY": transaction.get("title_company") or "Title Company",
            "NEXT_DEADLINE": _deadline_label(transaction.get("next_deadline_type"), transaction.get("next_deadline_date")),
            "DAYS_TO_CLOSING": str(days_to_closing) if days_to_closing != "" else "unknown",
        }
        rendered_message = _render_message_template(template_body, variables)

        for recipient in _recipient_targets(transaction, party_type):
            row = {
                "transaction_id": transaction["id"],
                "property_address": transaction.get("property_address") or "",
                "status": transaction.get("status") or "",
                "party_type": recipient["party_type"],
                "recipient_name": recipient["recipient_name"],
                "recipient_phone": recipient["recipient_phone"],
                "rendered_message": rendered_message.strip(),
            }
            sendable_rows.append(row)
            tx_ids.add(transaction["id"])
            if len(preview_rows) < max_preview_rows:
                preview_rows.append(row)

    return {
        "transactions_total": len(transactions),
        "transactions_affected": len(tx_ids),
        "total_recipients": len(sendable_rows),
        "preview_rows": preview_rows,
        "all_rows": sendable_rows,
        "preview_truncated": len(sendable_rows) > len(preview_rows),
    }


def _start_bulk_message_worker(job_id):
    with _JOB_LOCK:
        if job_id in _RUNNING_JOB_IDS:
            return False
        _RUNNING_JOB_IDS.add(job_id)

    thread = threading.Thread(target=_process_bulk_message_worker, args=(job_id,), daemon=True)
    thread.start()
    return True


def queue_bulk_message_job(
    template_used,
    template_body,
    filter_scope,
    filter_status,
    party_type,
    created_by="margaret",
):
    """Queue one bulk SMS send job and start background worker."""
    ensure_bulk_messaging_tables()
    preview = build_bulk_message_preview(
        template_body=template_body,
        filter_scope=filter_scope,
        filter_status=filter_status,
        party_type=party_type,
        max_preview_rows=120,
    )
    recipients = preview["all_rows"]
    if not recipients:
        return {"success": False, "error": "No recipients match current filters."}

    rows = execute_query(
        """
        INSERT INTO bulk_messages_log (
            template_used,
            message_template,
            filter_scope,
            filter_status,
            party_type,
            transactions_affected,
            total_recipients,
            sent_count,
            failed_count,
            status,
            created_by,
            summary,
            created_at
        )
        VALUES (%s, %s, %s, %s, %s, %s, %s, 0, 0, 'queued', %s, %s::jsonb, CURRENT_TIMESTAMP)
        RETURNING id
        """,
        (
            (template_used or "Custom Template")[:255],
            (template_body or "")[:2000],
            (filter_scope or "all_active")[:50],
            (filter_status or "")[:50],
            (party_type or "all_parties")[:30],
            preview["transactions_affected"],
            preview["total_recipients"],
            (created_by or "margaret")[:100],
            json.dumps(
                {
                    "transactions_total": preview["transactions_total"],
                    "preview_truncated": preview["preview_truncated"],
                }
            ),
        ),
        fetch=True,
    ) or []
    if not rows:
        return {"success": False, "error": "Unable to create message job."}
    job_id = rows[0]["id"]

    for row in recipients:
        execute_query(
            """
            INSERT INTO bulk_message_recipients (
                bulk_message_id,
                transaction_id,
                party_type,
                recipient_name,
                recipient_phone,
                rendered_message,
                status,
                created_at
            )
            VALUES (%s, %s, %s, %s, %s, %s, 'pending', CURRENT_TIMESTAMP)
            """,
            (
                job_id,
                row["transaction_id"],
                row["party_type"],
                row["recipient_name"][:200],
                row["recipient_phone"][:25],
                row["rendered_message"][:2000],
            ),
        )

    _start_bulk_message_worker(job_id)
    return {"success": True, "job_id": job_id, "preview": preview}


def _process_bulk_message_worker(job_id):
    try:
        execute_query(
            """
            UPDATE bulk_messages_log
            SET status = 'sending',
                started_at = CURRENT_TIMESTAMP
            WHERE id = %s
            """,
            (job_id,),
        )

        recipients = execute_query(
            """
            SELECT id, recipient_phone, rendered_message
            FROM bulk_message_recipients
            WHERE bulk_message_id = %s
              AND status = 'pending'
            ORDER BY id ASC
            """,
            (job_id,),
            fetch=True,
        ) or []

        for recipient in recipients:
            recipient_id = recipient["id"]
            to_phone = recipient.get("recipient_phone")
            message_body = recipient.get("rendered_message") or ""
            sid = send_sms(to_phone, message_body)
            if sid:
                execute_query(
                    """
                    UPDATE bulk_message_recipients
                    SET status = 'sent',
                        provider_message_sid = %s,
                        attempted_at = CURRENT_TIMESTAMP,
                        sent_at = CURRENT_TIMESTAMP
                    WHERE id = %s
                    """,
                    (sid, recipient_id),
                )
                execute_query(
                    """
                    UPDATE bulk_messages_log
                    SET sent_count = COALESCE(sent_count, 0) + 1
                    WHERE id = %s
                    """,
                    (job_id,),
                )
            else:
                execute_query(
                    """
                    UPDATE bulk_message_recipients
                    SET status = 'failed',
                        error_text = %s,
                        attempted_at = CURRENT_TIMESTAMP
                    WHERE id = %s
                    """,
                    ("SMS send failed", recipient_id),
                )
                execute_query(
                    """
                    UPDATE bulk_messages_log
                    SET failed_count = COALESCE(failed_count, 0) + 1
                    WHERE id = %s
                    """,
                    (job_id,),
                )
            # Carrier-safe pacing: 1 message per second.
            time.sleep(1.0)

        execute_query(
            """
            UPDATE bulk_messages_log
            SET status = 'completed',
                completed_at = CURRENT_TIMESTAMP,
                sent_at = CURRENT_TIMESTAMP
            WHERE id = %s
            """,
            (job_id,),
        )
    except Exception as exc:
        execute_query(
            """
            UPDATE bulk_messages_log
            SET status = 'failed',
                completed_at = CURRENT_TIMESTAMP,
                summary = COALESCE(summary, '{}'::jsonb) || %s::jsonb
            WHERE id = %s
            """,
            (json.dumps({"worker_error": str(exc)[:500]}), job_id),
        )
    finally:
        with _JOB_LOCK:
            if job_id in _RUNNING_JOB_IDS:
                _RUNNING_JOB_IDS.remove(job_id)


def fetch_bulk_message_progress(job_id):
    """Return progress details for one bulk message job."""
    ensure_bulk_messaging_tables()
    rows = execute_query(
        """
        SELECT id, template_used, transactions_affected, total_recipients, sent_count, failed_count,
               status, created_at, started_at, completed_at, sent_at
        FROM bulk_messages_log
        WHERE id = %s
        LIMIT 1
        """,
        (job_id,),
        fetch=True,
    ) or []
    if not rows:
        return None
    row = rows[0]
    total = int(row.get("total_recipients") or 0)
    sent = int(row.get("sent_count") or 0)
    failed = int(row.get("failed_count") or 0)
    processed = sent + failed
    pending = max(total - processed, 0)
    progress_pct = round((processed / total) * 100.0, 1) if total > 0 else 0.0
    return {
        "id": row["id"],
        "template_used": row.get("template_used") or "",
        "transactions_affected": int(row.get("transactions_affected") or 0),
        "total_recipients": total,
        "sent_count": sent,
        "failed_count": failed,
        "pending_count": pending,
        "processed_count": processed,
        "progress_pct": progress_pct,
        "status": row.get("status") or "queued",
        "created_at": row.get("created_at"),
        "started_at": row.get("started_at"),
        "completed_at": row.get("completed_at"),
        "sent_at": row.get("sent_at"),
    }


def fetch_bulk_message_history(limit=12):
    """Return recent bulk message jobs for dashboard summary."""
    ensure_bulk_messaging_tables()
    return execute_query(
        """
        SELECT id, template_used, transactions_affected, total_recipients, sent_count, failed_count,
               status, created_by, created_at, sent_at, completed_at
        FROM bulk_messages_log
        ORDER BY id DESC
        LIMIT %s
        """,
        (int(limit),),
        fetch=True,
    ) or []


def fetch_bulk_message_status_options():
    """Return status choices used in filter UI."""
    rows = execute_query(
        """
        SELECT DISTINCT status
        FROM transactions
        WHERE COALESCE(status, '') <> ''
        ORDER BY status ASC
        """,
        fetch=True,
    ) or []
    return [row["status"] for row in rows if row.get("status")]
