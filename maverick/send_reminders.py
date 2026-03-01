#!/usr/bin/env python3
"""
Maverick reminder automation.

Schedule:
  - Railway cron daily at 8:00 AM

Responsibilities:
  - Send 10/7/3/1-day reminder texts for active deadlines
  - Alert Margaret about critical deadlines tomorrow
  - Alert Margaret about overdue deadlines
  - Alert Heidi if the job fails
"""

import argparse
import os
import re
import sys
import traceback
from datetime import date, datetime, timedelta

from dotenv import load_dotenv

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
load_dotenv()

from utils.db import execute_query
from utils.email import send_html_email
from utils.sms import send_reminder, send_sms

DRY_RUN = False

REMINDER_STAGES = (
    {
        "days_before": 10,
        "name": "10-day",
        "where_clause": "d.reminder_10d_sent = FALSE",
        "update_query": """
            UPDATE deadlines
            SET reminder_10d_sent = TRUE,
                reminder_10d_sent_at = CURRENT_TIMESTAMP
            WHERE id = %s
        """,
    },
    {
        "days_before": 7,
        "name": "7-day",
        "where_clause": "d.reminder_7d_sent = FALSE",
        "update_query": """
            UPDATE deadlines
            SET reminder_7d_sent = TRUE,
                reminder_7d_sent_at = CURRENT_TIMESTAMP
            WHERE id = %s
        """,
    },
    {
        "days_before": 3,
        "name": "3-day",
        "where_clause": "d.reminder_3d_sent = FALSE",
        "update_query": """
            UPDATE deadlines
            SET reminder_3d_sent = TRUE,
                reminder_3d_sent_at = CURRENT_TIMESTAMP
            WHERE id = %s
        """,
    },
    {
        "days_before": 1,
        "name": "1-day",
        "where_clause": "d.reminder_1d_sent = FALSE",
        "update_query": """
            UPDATE deadlines
            SET reminder_1d_sent = TRUE,
                reminder_1d_sent_at = CURRENT_TIMESTAMP
            WHERE id = %s
        """,
    },
)

NUDGE_SECOND_SEND_DELAY_HOURS = 24


def _normalize_email(value):
    return (value or "").strip().lower()


def _is_email_valid(value):
    if not value:
        return False
    return bool(re.match(r"^[^\s@]+@[^\s@]+\.[^\s@]+$", value))


def _phone_last10(value):
    digits = re.sub(r"\D", "", value or "")
    if len(digits) < 10:
        return ""
    return digits[-10:]


def ensure_client_access_table():
    """Ensure client_access exists for buyer/seller email lookup."""
    execute_query(
        """
        CREATE TABLE IF NOT EXISTS client_access (
            id SERIAL PRIMARY KEY,
            transaction_id INT REFERENCES transactions(id) ON DELETE CASCADE,
            client_type VARCHAR(20) NOT NULL,
            access_token UUID UNIQUE NOT NULL,
            email VARCHAR(255),
            created_date TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            last_accessed TIMESTAMP
        )
        """
    )
    execute_query(
        """
        CREATE UNIQUE INDEX IF NOT EXISTS idx_client_access_transaction_type
        ON client_access(transaction_id, client_type)
        """
    )
    execute_query(
        """
        CREATE UNIQUE INDEX IF NOT EXISTS idx_client_access_token
        ON client_access(access_token)
        """
    )


def ensure_deadline_nudges_table():
    """Create proactive deadline nudge tracking table/indexes."""
    execute_query(
        """
        CREATE TABLE IF NOT EXISTS deadline_nudges (
            id SERIAL PRIMARY KEY,
            transaction_id INT REFERENCES transactions(id) ON DELETE CASCADE,
            deadline_id INT REFERENCES deadlines(id) ON DELETE CASCADE,
            task_id INT REFERENCES tasks(id) ON DELETE SET NULL,
            nudge_key VARCHAR(80) NOT NULL,
            deadline_type VARCHAR(80),
            due_date DATE,
            target_party VARCHAR(30) NOT NULL,
            target_email VARCHAR(255),
            target_phone VARCHAR(25),
            message_text TEXT,
            first_nudge_sent_at TIMESTAMP,
            second_nudge_sent_at TIMESTAMP,
            response_received_at TIMESTAMP,
            response_channel VARCHAR(20),
            response_text TEXT,
            requested_margaret_help BOOLEAN DEFAULT FALSE,
            escalated_at TIMESTAMP,
            escalation_task_id INT REFERENCES tasks(id) ON DELETE SET NULL,
            status VARCHAR(20) DEFAULT 'pending',
            status_notes TEXT,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
        """
    )
    execute_query(
        """
        CREATE UNIQUE INDEX IF NOT EXISTS idx_deadline_nudges_unique_cycle
        ON deadline_nudges(transaction_id, nudge_key, due_date, target_party)
        """
    )
    execute_query(
        """
        CREATE INDEX IF NOT EXISTS idx_deadline_nudges_transaction
        ON deadline_nudges(transaction_id, due_date DESC)
        """
    )
    execute_query(
        """
        CREATE INDEX IF NOT EXISTS idx_deadline_nudges_phone
        ON deadline_nudges(target_phone, status, response_received_at)
        """
    )


def notify_email(to_email, subject, html_body):
    """Send email or print in dry-run mode."""
    if DRY_RUN:
        log(f"[DRY-RUN] Email to {to_email}: {subject}")
        return "dry-run"
    return send_html_email(to_email=to_email, subject=subject, html_body=html_body)


def log_communication(transaction_id, communication_type, contact_party, contact_name, summary, outcome):
    """Persist communication timeline records for nudges and escalations."""
    if DRY_RUN:
        log(
            f"[DRY-RUN] communication txn#{transaction_id}: "
            f"{communication_type}/{contact_party} {summary} | {outcome}"
        )
        return
    execute_query(
        """
        INSERT INTO communications (
            transaction_id, communication_type, contact_party, contact_name, summary, outcome, logged_by
        ) VALUES (%s, %s, %s, %s, %s, %s, %s)
        """,
        (
            transaction_id,
            communication_type,
            contact_party,
            contact_name,
            summary,
            outcome,
            "nudge_engine",
        ),
    )


def get_existing_nudge(transaction_id, nudge_key, due_date, target_party):
    """Fetch existing nudge cycle row for one transaction/key/date/party."""
    rows = execute_query(
        """
        SELECT id, first_nudge_sent_at, second_nudge_sent_at, response_received_at,
               requested_margaret_help, escalated_at, escalation_task_id, status
        FROM deadline_nudges
        WHERE transaction_id = %s
          AND nudge_key = %s
          AND due_date = %s
          AND target_party = %s
        ORDER BY id DESC
        LIMIT 1
        """,
        (transaction_id, nudge_key, due_date, target_party),
        fetch=True,
    ) or []
    return rows[0] if rows else None


def insert_first_nudge(candidate, message_text, status_notes):
    """Insert first nudge row after successful delivery."""
    if DRY_RUN:
        log(
            f"[DRY-RUN] insert first nudge txn#{candidate['transaction_id']} "
            f"key={candidate['nudge_key']}"
        )
        return
    execute_query(
        """
        INSERT INTO deadline_nudges (
            transaction_id, deadline_id, task_id, nudge_key, deadline_type, due_date,
            target_party, target_email, target_phone, message_text, first_nudge_sent_at,
            status, status_notes, created_at, updated_at
        )
        VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, CURRENT_TIMESTAMP, 'pending', %s, CURRENT_TIMESTAMP, CURRENT_TIMESTAMP)
        ON CONFLICT (transaction_id, nudge_key, due_date, target_party)
        DO UPDATE SET
            message_text = EXCLUDED.message_text,
            target_email = COALESCE(EXCLUDED.target_email, deadline_nudges.target_email),
            target_phone = COALESCE(EXCLUDED.target_phone, deadline_nudges.target_phone),
            first_nudge_sent_at = COALESCE(deadline_nudges.first_nudge_sent_at, CURRENT_TIMESTAMP),
            status_notes = COALESCE(EXCLUDED.status_notes, deadline_nudges.status_notes),
            updated_at = CURRENT_TIMESTAMP
        """,
        (
            candidate["transaction_id"],
            candidate.get("deadline_id"),
            candidate.get("task_id"),
            candidate["nudge_key"],
            candidate.get("deadline_type"),
            candidate["due_date"],
            candidate["target_party"],
            candidate.get("target_email"),
            candidate.get("target_phone"),
            message_text,
            status_notes,
        ),
    )


def mark_second_nudge(nudge_id, message_text, status_notes):
    """Mark second nudge send timestamp."""
    if DRY_RUN:
        log(f"[DRY-RUN] mark second nudge id={nudge_id}")
        return
    execute_query(
        """
        UPDATE deadline_nudges
        SET second_nudge_sent_at = CURRENT_TIMESTAMP,
            message_text = %s,
            status_notes = %s,
            status = 'pending',
            updated_at = CURRENT_TIMESTAMP
        WHERE id = %s
        """,
        (message_text, status_notes, nudge_id),
    )


def create_margaret_followup_task(transaction_id, description, notes):
    """Create/return one open follow-up task for Margaret checklist."""
    safe_description = (description or "Follow up on pending deadline item").strip()[:280]
    existing_rows = execute_query(
        """
        SELECT id
        FROM tasks
        WHERE transaction_id = %s
          AND LOWER(task_description) = LOWER(%s)
          AND completed = FALSE
          AND COALESCE(status, 'pending') <> 'completed'
        LIMIT 1
        """,
        (transaction_id, safe_description),
        fetch=True,
    ) or []
    if existing_rows:
        return existing_rows[0]["id"]

    if DRY_RUN:
        log(f"[DRY-RUN] create checklist task txn#{transaction_id}: {safe_description}")
        return None

    rows = execute_query(
        """
        INSERT INTO tasks (
            transaction_id, task_description, task_category, due_date,
            priority, status, completed, display_order, notes, created_at
        )
        VALUES (%s, %s, 'coordination', %s, 'high', 'pending', FALSE, 65, %s, CURRENT_TIMESTAMP)
        RETURNING id
        """,
        (transaction_id, safe_description, date.today(), (notes or "")[:900]),
        fetch=True,
    ) or []
    return rows[0]["id"] if rows else None


def escalate_nudge_to_margaret(nudge_row, candidate, reason):
    """Escalate unresolved nudge to Margaret checklist (and optional SMS)."""
    if not nudge_row or nudge_row.get("escalated_at"):
        return nudge_row.get("escalation_task_id") if nudge_row else None

    description = candidate.get("escalation_task") or "Follow up on pending deadline item"
    notes = (
        f"Escalated from proactive nudge engine.\n"
        f"Nudge key: {candidate['nudge_key']}\n"
        f"Reason: {reason}\n"
        f"Property: {candidate.get('property_address')}\n"
    )
    task_id = create_margaret_followup_task(candidate["transaction_id"], description, notes)

    if not DRY_RUN:
        execute_query(
            """
            UPDATE deadline_nudges
            SET escalated_at = CURRENT_TIMESTAMP,
                escalation_task_id = %s,
                status = 'escalated',
                status_notes = %s,
                updated_at = CURRENT_TIMESTAMP
            WHERE id = %s
            """,
            (task_id, reason[:380], nudge_row["id"]),
        )

    log_communication(
        transaction_id=candidate["transaction_id"],
        communication_type="note",
        contact_party="system",
        contact_name="nudge_engine",
        summary=f"Nudge escalated to Margaret ({candidate['nudge_key']})",
        outcome=f"reason={reason} task_id={task_id or 'n/a'}",
    )
    return task_id


def build_nudge_email_html(candidate, message_text, stage_label):
    """Simple HTML body used for nudge emails."""
    due_label = candidate["due_date"].strftime("%b %d, %Y")
    return (
        "<html><body style='font-family:Arial,sans-serif;color:#0f172a;'>"
        "<h3 style='margin-bottom:8px;'>Maverick TC Reminder</h3>"
        f"<p>{message_text}</p>"
        f"<p><strong>Property:</strong> {candidate.get('property_address') or 'N/A'}</p>"
        f"<p><strong>Due Date:</strong> {due_label}</p>"
        f"<p><strong>Nudge Stage:</strong> {stage_label}</p>"
        "<p style='color:#475569;'>Reply to this message if you need support.</p>"
        "</body></html>"
    )


def send_candidate_nudge(candidate, stage):
    """Send one candidate nudge (email/SMS) and return delivery summary."""
    due_label = candidate["due_date"].strftime("%m/%d/%Y")
    stage_text = "first" if stage == "first" else "second"
    message_text = candidate["sms_message"].format(date=due_label)
    email_text = candidate["email_message"].format(date=due_label)
    email_subject = candidate["email_subject"].format(date=due_label)

    sms_result = None
    if candidate.get("send_sms") and candidate.get("target_phone"):
        sms_result = notify_sms(candidate["target_phone"], message_text)

    email_result = None
    if candidate.get("target_email") and _is_email_valid(candidate["target_email"]):
        html_body = build_nudge_email_html(candidate, email_text, stage_text)
        email_result = notify_email(candidate["target_email"], email_subject, html_body)

    delivered = bool(sms_result or email_result)
    if not delivered:
        return {
            "delivered": False,
            "message_text": message_text,
            "status_notes": "delivery_failed",
            "sms_result": sms_result,
            "email_result": email_result,
        }

    outcome = (
        f"stage={stage_text} sms_sid={sms_result or 'n/a'} "
        f"email_id={email_result or 'n/a'} target={candidate.get('target_party')}"
    )
    log_communication(
        transaction_id=candidate["transaction_id"],
        communication_type="email" if email_result else "text",
        contact_party=candidate.get("target_party") or "agent",
        contact_name=candidate.get("target_name") or (candidate.get("target_party") or "party").title(),
        summary=f"Proactive nudge sent ({candidate['nudge_key']})",
        outcome=outcome,
    )
    return {
        "delivered": True,
        "message_text": message_text,
        "status_notes": outcome[:350],
        "sms_result": sms_result,
        "email_result": email_result,
    }


def should_send_second_nudge(existing_row):
    """Determine if second nudge is due."""
    if not existing_row:
        return False
    if existing_row.get("second_nudge_sent_at"):
        return False
    sent_at = existing_row.get("first_nudge_sent_at")
    if not sent_at:
        return True
    return datetime.now() - sent_at >= timedelta(hours=NUDGE_SECOND_SEND_DELAY_HOURS)


def find_option_period_inspection_candidates(today):
    """Option period in 5 days and no inspection scheduling progress."""
    target_date = today + timedelta(days=5)
    rows = execute_query(
        """
        SELECT d.id AS deadline_id, d.deadline_type, d.deadline_date,
               t.id AS transaction_id, t.property_address, t.agent_name, t.agent_phone, t.agent_email,
               EXISTS (
                   SELECT 1 FROM tasks tk
                   WHERE tk.transaction_id = t.id
                     AND (
                         LOWER(COALESCE(tk.task_description, '')) LIKE 'schedule home inspection%%'
                         OR LOWER(COALESCE(tk.task_description, '')) LIKE 'get inspection report%%'
                     )
                     AND (
                         tk.completed = TRUE
                         OR COALESCE(tk.status, 'pending') IN ('in_progress', 'completed')
                     )
               ) AS inspection_progress,
               EXISTS (
                   SELECT 1 FROM documents doc
                   WHERE doc.transaction_id = t.id
                     AND doc.document_type IN ('inspection', 'inspection_report')
               ) AS inspection_doc
        FROM deadlines d
        JOIN transactions t ON t.id = d.transaction_id
        WHERE d.deadline_type = 'option_period_end'
          AND d.deadline_date = %s
          AND d.completed = FALSE
          AND t.status = 'ACTIVE'
        ORDER BY t.property_address ASC
        """,
        (target_date,),
        fetch=True,
    ) or []

    candidates = []
    for row in rows:
        if row.get("inspection_progress") or row.get("inspection_doc"):
            continue
        candidates.append(
            {
                "transaction_id": row["transaction_id"],
                "deadline_id": row["deadline_id"],
                "task_id": None,
                "deadline_type": row["deadline_type"],
                "due_date": row["deadline_date"],
                "nudge_key": "option_period_inspection",
                "property_address": row.get("property_address"),
                "target_party": "agent",
                "target_name": row.get("agent_name") or "Agent",
                "target_email": _normalize_email(row.get("agent_email")),
                "target_phone": row.get("agent_phone") or "",
                "send_sms": True,
                "email_subject": "Inspection scheduling reminder - {date}",
                "email_message": (
                    "Hi! Quick reminder: inspection should be scheduled before {date} to stay within the option period. "
                    "Need help finding an inspector? Reply YES and Maverick will send recommendations."
                ),
                "sms_message": (
                    "Hi! Quick reminder - inspection should be scheduled before {date} to stay within option period. "
                    "Need help finding an inspector? Reply YES and I'll send recommendations. - Maverick TC"
                ),
                "escalation_task": "Follow up on inspection scheduling",
            }
        )
    return candidates


def find_earnest_money_candidates(today):
    """Earnest money due in 2 days and receipt not uploaded."""
    target_date = today + timedelta(days=2)
    rows = execute_query(
        """
        SELECT d.id AS deadline_id, d.deadline_type, d.deadline_date,
               t.id AS transaction_id, t.property_address, t.agent_name, t.agent_email,
               buyer_ca.email AS buyer_email,
               EXISTS (
                   SELECT 1 FROM documents doc
                   WHERE doc.transaction_id = t.id
                     AND doc.document_type = 'earnest_receipt'
               ) AS has_earnest_receipt
        FROM deadlines d
        JOIN transactions t ON t.id = d.transaction_id
        LEFT JOIN LATERAL (
            SELECT email
            FROM client_access ca
            WHERE ca.transaction_id = t.id
              AND ca.client_type = 'buyer'
            ORDER BY ca.created_date DESC NULLS LAST, ca.id DESC
            LIMIT 1
        ) buyer_ca ON TRUE
        WHERE d.deadline_type = 'earnest_money'
          AND d.deadline_date = %s
          AND d.completed = FALSE
          AND t.status = 'ACTIVE'
        ORDER BY t.property_address ASC
        """,
        (target_date,),
        fetch=True,
    ) or []

    candidates = []
    for row in rows:
        if row.get("has_earnest_receipt"):
            continue
        target_email = _normalize_email(row.get("buyer_email")) or _normalize_email(row.get("agent_email"))
        candidates.append(
            {
                "transaction_id": row["transaction_id"],
                "deadline_id": row["deadline_id"],
                "task_id": None,
                "deadline_type": row["deadline_type"],
                "due_date": row["deadline_date"],
                "nudge_key": "earnest_money_receipt",
                "property_address": row.get("property_address"),
                "target_party": "buyer",
                "target_name": "Buyer",
                "target_email": target_email,
                "target_phone": "",
                "send_sms": False,
                "email_subject": "Friendly reminder - earnest money due by {date}",
                "email_message": (
                    "Friendly reminder: earnest money is due by {date}. "
                    "Please confirm once submitted so we can keep the timeline on track."
                ),
                "sms_message": "Friendly reminder - earnest money due by {date}. - Maverick TC",
                "escalation_task": "Follow up on earnest money receipt",
            }
        )
    return candidates


def find_appraisal_order_candidates(today):
    """Appraisal due in 7 days and order progress not detected."""
    target_date = today + timedelta(days=7)
    rows = execute_query(
        """
        SELECT tk.id AS task_id, tk.task_description, tk.due_date,
               t.id AS transaction_id, t.property_address, t.lender_name, t.lender_email, t.agent_email
        FROM tasks tk
        JOIN transactions t ON t.id = tk.transaction_id
        WHERE LOWER(COALESCE(tk.task_description, '')) LIKE 'verify appraisal completed%%'
          AND tk.due_date = %s
          AND tk.completed = FALSE
          AND COALESCE(tk.status, 'pending') = 'pending'
          AND t.status = 'ACTIVE'
        ORDER BY t.property_address ASC
        """,
        (target_date,),
        fetch=True,
    ) or []

    candidates = []
    for row in rows:
        target_email = _normalize_email(row.get("lender_email")) or _normalize_email(row.get("agent_email"))
        candidates.append(
            {
                "transaction_id": row["transaction_id"],
                "deadline_id": None,
                "task_id": row["task_id"],
                "deadline_type": "appraisal_order",
                "due_date": row["due_date"],
                "nudge_key": "appraisal_order",
                "property_address": row.get("property_address"),
                "target_party": "lender",
                "target_name": row.get("lender_name") or "Lender",
                "target_email": target_email,
                "target_phone": "",
                "send_sms": False,
                "email_subject": "Please confirm appraisal has been ordered ({date})",
                "email_message": (
                    "Please confirm appraisal has been ordered. Target due date is {date}. "
                    "Reply with current status and expected inspection window."
                ),
                "sms_message": "Please confirm appraisal has been ordered by {date}. - Maverick TC",
                "escalation_task": "Follow up with lender on appraisal order",
            }
        )
    return candidates


def find_hoa_docs_candidates(today):
    """HOA docs due in 5 days and docs still missing."""
    target_date = today + timedelta(days=5)
    rows = execute_query(
        """
        SELECT d.id AS deadline_id, d.deadline_type, d.deadline_date,
               t.id AS transaction_id, t.property_address, t.agent_email,
               seller_ca.email AS seller_email,
               EXISTS (
                   SELECT 1 FROM documents doc
                   WHERE doc.transaction_id = t.id
                     AND doc.document_type IN ('hoa', 'hoa_docs', 'hoa_documents')
               ) AS has_hoa_docs
        FROM deadlines d
        JOIN transactions t ON t.id = d.transaction_id
        LEFT JOIN LATERAL (
            SELECT email
            FROM client_access ca
            WHERE ca.transaction_id = t.id
              AND ca.client_type = 'seller'
            ORDER BY ca.created_date DESC NULLS LAST, ca.id DESC
            LIMIT 1
        ) seller_ca ON TRUE
        WHERE d.deadline_type = 'hoa_docs'
          AND d.deadline_date = %s
          AND d.completed = FALSE
          AND t.status = 'ACTIVE'
        ORDER BY t.property_address ASC
        """,
        (target_date,),
        fetch=True,
    ) or []

    candidates = []
    for row in rows:
        if row.get("has_hoa_docs"):
            continue
        target_email = _normalize_email(row.get("seller_email")) or _normalize_email(row.get("agent_email"))
        candidates.append(
            {
                "transaction_id": row["transaction_id"],
                "deadline_id": row["deadline_id"],
                "task_id": None,
                "deadline_type": row["deadline_type"],
                "due_date": row["deadline_date"],
                "nudge_key": "hoa_docs_request",
                "property_address": row.get("property_address"),
                "target_party": "seller",
                "target_name": "Seller",
                "target_email": target_email,
                "target_phone": "",
                "send_sms": False,
                "email_subject": "HOA documents requested by {date}",
                "email_message": (
                    "Please provide HOA documents by {date} to keep closing on schedule. "
                    "Reply if you need help obtaining them."
                ),
                "sms_message": "Please provide HOA documents by {date}. - Maverick TC",
                "escalation_task": "Follow up on HOA documents from seller",
            }
        )
    return candidates


def find_repair_addendum_candidates(today):
    """Repair addendum due in 3 days and not submitted yet."""
    target_date = today + timedelta(days=3)
    rows = execute_query(
        """
        SELECT DISTINCT ON (t.id)
               tk.id AS task_id,
               tk.task_description,
               tk.due_date,
               t.id AS transaction_id,
               t.property_address,
               t.agent_name,
               t.agent_email
        FROM tasks tk
        JOIN transactions t ON t.id = tk.transaction_id
        WHERE tk.due_date = %s
          AND tk.completed = FALSE
          AND COALESCE(tk.status, 'pending') <> 'completed'
          AND LOWER(COALESCE(tk.task_description, '')) LIKE '%%repair%%'
          AND t.status = 'ACTIVE'
          AND NOT EXISTS (
              SELECT 1 FROM documents doc
              WHERE doc.transaction_id = t.id
                AND doc.document_type IN ('signed_addendum', 'signed_amendment', 'repair_addendum')
          )
        ORDER BY t.id, tk.due_date ASC, tk.id ASC
        """,
        (target_date,),
        fetch=True,
    ) or []

    candidates = []
    for row in rows:
        candidates.append(
            {
                "transaction_id": row["transaction_id"],
                "deadline_id": None,
                "task_id": row["task_id"],
                "deadline_type": "repair_addendum",
                "due_date": row["due_date"],
                "nudge_key": "repair_addendum",
                "property_address": row.get("property_address"),
                "target_party": "agent",
                "target_name": row.get("agent_name") or "Agent",
                "target_email": _normalize_email(row.get("agent_email")),
                "target_phone": "",
                "send_sms": False,
                "email_subject": "Inspection repairs should be submitted by {date}",
                "email_message": (
                    "Inspection repairs should be submitted by {date}. "
                    "Please share repair addendum status so we stay on timeline."
                ),
                "sms_message": "Inspection repairs should be submitted by {date}. - Maverick TC",
                "escalation_task": "Follow up on repair addendum submission",
            }
        )
    return candidates


def proactive_nudge_candidates(today):
    """Aggregate all proactive nudge candidates."""
    candidates = []
    candidates.extend(find_option_period_inspection_candidates(today))
    candidates.extend(find_earnest_money_candidates(today))
    candidates.extend(find_appraisal_order_candidates(today))
    candidates.extend(find_hoa_docs_candidates(today))
    candidates.extend(find_repair_addendum_candidates(today))
    return candidates


def run_proactive_deadline_nudges():
    """Run proactive nudge workflow and escalation rules."""
    ensure_client_access_table()
    ensure_deadline_nudges_table()

    today = date.today()
    candidates = proactive_nudge_candidates(today)
    log(f"Proactive nudge candidates: {len(candidates)}")

    first_sent = 0
    second_sent = 0
    escalated = 0

    for candidate in candidates:
        if not candidate.get("target_email") and not candidate.get("target_phone"):
            log(
                f"Skipping nudge {candidate['nudge_key']} txn#{candidate['transaction_id']} "
                "(no contact channel)"
            )
            continue

        existing = get_existing_nudge(
            transaction_id=candidate["transaction_id"],
            nudge_key=candidate["nudge_key"],
            due_date=candidate["due_date"],
            target_party=candidate["target_party"],
        )

        if existing and existing.get("response_received_at"):
            continue

        stage = None
        if not existing:
            stage = "first"
        elif should_send_second_nudge(existing):
            stage = "second"

        if stage:
            delivery = send_candidate_nudge(candidate, stage=stage)
            if delivery.get("delivered"):
                if stage == "first":
                    insert_first_nudge(
                        candidate=candidate,
                        message_text=delivery["message_text"],
                        status_notes=delivery["status_notes"],
                    )
                    first_sent += 1
                else:
                    mark_second_nudge(
                        nudge_id=existing["id"],
                        message_text=delivery["message_text"],
                        status_notes=delivery["status_notes"],
                    )
                    second_sent += 1
            else:
                log(
                    f"Nudge delivery failed: key={candidate['nudge_key']} "
                    f"txn#{candidate['transaction_id']}"
                )

        existing = get_existing_nudge(
            transaction_id=candidate["transaction_id"],
            nudge_key=candidate["nudge_key"],
            due_date=candidate["due_date"],
            target_party=candidate["target_party"],
        )
        if not existing:
            continue
        due_within_48h = candidate["due_date"] <= today + timedelta(days=2)
        needs_escalation = (
            existing.get("response_received_at") is None
            and existing.get("escalated_at") is None
            and (
                bool(existing.get("requested_margaret_help"))
                or (bool(existing.get("second_nudge_sent_at")) and due_within_48h)
            )
        )
        if not needs_escalation:
            continue

        reason = (
            "Party explicitly requested Margaret help."
            if existing.get("requested_margaret_help")
            else "No response after 2 nudges and deadline is within 48 hours."
        )
        task_id = escalate_nudge_to_margaret(existing, candidate, reason)
        if task_id or DRY_RUN:
            escalated += 1

    log(
        "Proactive nudge summary: "
        f"first_sent={first_sent}, second_sent={second_sent}, escalated={escalated}"
    )
    return {
        "first_sent": first_sent,
        "second_sent": second_sent,
        "escalated": escalated,
        "candidate_count": len(candidates),
    }


def log(message):
    """Print timestamped logs for cron visibility."""
    print(f"[{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}] {message}")


def notify_sms(to_number, message):
    """Send SMS or print in dry-run mode."""
    if DRY_RUN:
        log(f"[DRY-RUN] SMS to {to_number}: {message[:220]}")
        return "dry-run"
    return send_sms(to_number, message)


def fetch_stage_deadlines(target_date, where_clause):
    """Fetch active, incomplete deadlines for one reminder stage."""
    return execute_query(
        f"""
        SELECT d.id, d.deadline_type, d.deadline_date, d.is_critical,
               t.id AS transaction_id, t.property_address, t.agent_name, t.agent_phone
        FROM deadlines d
        JOIN transactions t ON t.id = d.transaction_id
        WHERE d.deadline_date = %s
          AND d.completed = FALSE
          AND {where_clause}
          AND t.status = 'ACTIVE'
        ORDER BY t.property_address ASC
        """,
        (target_date,),
        fetch=True,
    ) or []


def send_stage_reminders():
    """Send 10/7/3/1 day reminder messages."""
    today = date.today()
    total_sent = 0

    for stage in REMINDER_STAGES:
        target_date = today + timedelta(days=stage["days_before"])
        deadlines = fetch_stage_deadlines(target_date, stage["where_clause"])
        log(f"{stage['name']} stage: {len(deadlines)} candidate deadlines")

        for deadline in deadlines:
            if DRY_RUN:
                sid = "dry-run"
                log(
                    f"[DRY-RUN] Would send {stage['name']} reminder "
                    f"to {deadline['agent_phone']} for {deadline['property_address']}"
                )
            else:
                sid = send_reminder(
                    to_number=deadline["agent_phone"],
                    property_address=deadline["property_address"],
                    deadline_type=deadline["deadline_type"].replace("_", " ").title(),
                    deadline_date=deadline["deadline_date"].strftime("%m/%d/%Y"),
                    days_until=stage["days_before"],
                )
            if not sid:
                log(
                    f"Failed {stage['name']} reminder for "
                    f"deadline_id={deadline['id']} property={deadline['property_address']}"
                )
                continue

            if DRY_RUN:
                log(f"[DRY-RUN] Would set reminder flag for deadline_id={deadline['id']}")
            else:
                updated = execute_query(stage["update_query"], (deadline["id"],))
                if not updated:
                    log(f"Warning: failed to update reminder flags for deadline_id={deadline['id']}")
                    continue

            total_sent += 1
            log(
                f"Sent {stage['name']} reminder: "
                f"property={deadline['property_address']} type={deadline['deadline_type']} sid={sid}"
            )

    return total_sent


def send_critical_deadline_alert_to_margaret():
    """Send one summary SMS for tomorrow's critical deadlines."""
    margaret_phone = os.getenv("MARGARET_PHONE")
    if not margaret_phone:
        log("MARGARET_PHONE missing - skipping critical deadline alert.")
        return

    tomorrow = date.today() + timedelta(days=1)
    critical = execute_query(
        """
        SELECT d.id, d.deadline_type, d.deadline_date, t.property_address
        FROM deadlines d
        JOIN transactions t ON t.id = d.transaction_id
        WHERE d.deadline_date = %s
          AND d.completed = FALSE
          AND d.is_critical = TRUE
          AND t.status = 'ACTIVE'
        ORDER BY t.property_address ASC
        """,
        (tomorrow,),
        fetch=True,
    ) or []
    if not critical:
        log("No critical deadlines tomorrow.")
        return

    message_lines = [f"Critical deadlines tomorrow ({len(critical)}):"]
    for item in critical[:6]:
        deadline_label = item["deadline_type"].replace("_", " ").title()
        message_lines.append(f"- {item['property_address']}: {deadline_label}")
    if len(critical) > 6:
        message_lines.append(f"+ {len(critical) - 6} more in dashboard")
    message_lines.append("- Maverick TC")

    sid = notify_sms(margaret_phone, "\n".join(message_lines))
    log(f"Sent critical summary to Margaret sid={sid}")


def send_overdue_deadline_alert_to_margaret():
    """Send one summary SMS for overdue incomplete deadlines."""
    margaret_phone = os.getenv("MARGARET_PHONE")
    if not margaret_phone:
        log("MARGARET_PHONE missing - skipping overdue alert.")
        return

    today = date.today()
    overdue = execute_query(
        """
        SELECT d.id, d.deadline_type, d.deadline_date, t.property_address
        FROM deadlines d
        JOIN transactions t ON t.id = d.transaction_id
        WHERE d.deadline_date < %s
          AND d.completed = FALSE
          AND t.status = 'ACTIVE'
        ORDER BY d.deadline_date ASC
        """,
        (today,),
        fetch=True,
    ) or []
    if not overdue:
        log("No overdue deadlines.")
        return

    message_lines = [f"Overdue deadlines ({len(overdue)}):"]
    for item in overdue[:6]:
        days_overdue = (today - item["deadline_date"]).days
        deadline_label = item["deadline_type"].replace("_", " ").title()
        message_lines.append(f"- {item['property_address']}: {deadline_label} ({days_overdue}d)")
    if len(overdue) > 6:
        message_lines.append(f"+ {len(overdue) - 6} more in dashboard")
    message_lines.append("- Maverick TC")

    sid = notify_sms(margaret_phone, "\n".join(message_lines))
    log(f"Sent overdue summary to Margaret sid={sid}")


def main(dry_run=False):
    """Run the full reminder job."""
    global DRY_RUN
    DRY_RUN = dry_run

    log("Starting reminder job")
    if DRY_RUN:
        log("Mode: DRY-RUN (no SMS and no DB writes)")

    try:
        reminders_sent = send_stage_reminders()
        log(f"Total reminder texts sent: {reminders_sent}")
        nudge_summary = run_proactive_deadline_nudges()
        log(
            "Proactive nudges completed: "
            f"{nudge_summary['first_sent']} first, "
            f"{nudge_summary['second_sent']} second, "
            f"{nudge_summary['escalated']} escalated"
        )
        send_critical_deadline_alert_to_margaret()
        send_overdue_deadline_alert_to_margaret()
        log("Reminder job completed successfully")
    except Exception as exc:
        log(f"ERROR: reminder job failed: {exc}")
        traceback.print_exc()

        heidi_phone = os.getenv("HEIDI_PHONE")
        if heidi_phone:
            notify_sms(heidi_phone, f"Maverick reminder job failed: {str(exc)[:140]}")
        raise


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Run Maverick reminder automation.")
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Simulate reminder job without SMS sends or DB writes.",
    )
    cli_args = parser.parse_args()
    main(dry_run=cli_args.dry_run)
