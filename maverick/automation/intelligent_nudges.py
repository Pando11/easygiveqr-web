#!/usr/bin/env python3
"""
Maverick intelligent nudge automation.

Run daily (recommended at 7:00 AM) to send proactive deadline nudges before
Margaret starts her workday.
"""

import os
import re
import sys
from datetime import date, datetime, timedelta
from pathlib import Path

from dotenv import load_dotenv
from jinja2 import Environment, FileSystemLoader, TemplateNotFound, select_autoescape

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
load_dotenv()

from utils.db import execute_query, get_active_transactions, get_transaction_deadlines  # noqa: E402
from utils.email import send_email  # noqa: E402
from utils.sms import send_sms  # noqa: E402

AGENT_OWNED_NUDGE_TYPES = {
    "inspection_not_scheduled",
    "earnest_not_received",
    "survey_not_ordered",
}

NUDGE_DEFAULTS = {
    "inspection_not_scheduled": {
        "label": "Inspection not scheduled",
        "lead_days": 5,
        "sms_template": "inspection_reminder.txt",
        "email_template": "inspection_reminder.html",
        "subject": "Inspection Reminder - {property_address}",
        "include_preferred_vendors": True,
    },
    "earnest_not_received": {
        "label": "Earnest not received",
        "lead_days": 2,
        "sms_template": "earnest_reminder.txt",
        "email_template": "earnest_reminder.html",
        "subject": "Earnest Money Reminder - {property_address}",
        "include_preferred_vendors": False,
    },
    "appraisal_not_ordered": {
        "label": "Appraisal not ordered",
        "lead_days": 7,
        "sms_template": "appraisal_reminder.txt",
        "email_template": "appraisal_reminder.html",
        "subject": "Appraisal Status Reminder - {property_address}",
        "include_preferred_vendors": False,
    },
    "hoa_docs_not_received": {
        "label": "HOA docs not received",
        "lead_days": 5,
        "sms_template": "hoa_reminder.txt",
        "email_template": "hoa_reminder.html",
        "subject": "HOA Documents Reminder - {property_address}",
        "include_preferred_vendors": False,
    },
    "survey_not_ordered": {
        "label": "Survey not ordered",
        "lead_days": 5,
        "sms_template": "survey_reminder.txt",
        "email_template": "survey_reminder.html",
        "subject": "Survey Reminder - {property_address}",
        "include_preferred_vendors": False,
    },
    "title_not_received": {
        "label": "Title commitment not received",
        "lead_days": 7,
        "sms_template": "title_reminder.txt",
        "email_template": "title_reminder.html",
        "subject": "Title Commitment Reminder - {property_address}",
        "include_preferred_vendors": False,
    },
}


def log(message):
    """Print timestamped script logs."""
    print(f"[{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}] {message}")


def normalize_phone(value):
    """Return normalized E.164-like phone string when possible."""
    digits = re.sub(r"\D", "", value or "")
    if len(digits) == 10:
        return f"+1{digits}"
    if len(digits) == 11 and digits.startswith("1"):
        return f"+{digits}"
    if value and str(value).startswith("+"):
        return str(value).strip()
    return f"+{digits}" if digits else ""


def phone_last10(value):
    """Return last 10 phone digits."""
    digits = re.sub(r"\D", "", value or "")
    if len(digits) < 10:
        return ""
    return digits[-10:]


def normalize_email(value):
    """Return normalized lowercase email."""
    return (value or "").strip().lower()


def format_date(value):
    """Template date formatter."""
    if hasattr(value, "strftime"):
        return value.strftime("%b %d, %Y")
    return str(value or "")


def format_currency(value):
    """Template currency formatter."""
    try:
        amount = float(value or 0)
    except (TypeError, ValueError):
        amount = 0.0
    return f"${amount:,.2f}"


def template_environment():
    """Build Jinja environment for nudge templates."""
    templates_root = Path(__file__).resolve().parents[1] / "templates"
    env = Environment(
        loader=FileSystemLoader(str(templates_root)),
        autoescape=select_autoescape(["html", "xml"]),
        trim_blocks=True,
        lstrip_blocks=True,
    )
    env.filters["format_date"] = format_date
    env.filters["currency"] = format_currency
    return env


def ensure_nudge_log_table():
    """Create nudge_log table and indexes."""
    execute_query(
        """
        CREATE TABLE IF NOT EXISTS nudge_log (
            id SERIAL PRIMARY KEY,
            transaction_id INT REFERENCES transactions(id) ON DELETE CASCADE,
            deadline_id INT REFERENCES deadlines(id) ON DELETE CASCADE,
            nudge_type VARCHAR(100) NOT NULL,
            sent_to VARCHAR(200),
            sent_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            response_received BOOLEAN DEFAULT FALSE,
            response_date TIMESTAMP,
            escalated_to_margaret BOOLEAN DEFAULT FALSE
        )
        """
    )
    execute_query(
        """
        CREATE UNIQUE INDEX IF NOT EXISTS idx_nudge_log_unique_deadline_type
        ON nudge_log(transaction_id, deadline_id, nudge_type)
        """
    )
    execute_query(
        """
        CREATE INDEX IF NOT EXISTS idx_nudge_log_sent_to
        ON nudge_log(sent_to, sent_at DESC)
        """
    )
    execute_query(
        """
        CREATE INDEX IF NOT EXISTS idx_nudge_log_response
        ON nudge_log(nudge_type, response_received, sent_at DESC)
        """
    )


def ensure_nudge_settings_table():
    """Create nudge settings table and seed defaults."""
    execute_query(
        """
        CREATE TABLE IF NOT EXISTS nudge_settings (
            id SERIAL PRIMARY KEY,
            nudge_type VARCHAR(100) UNIQUE NOT NULL,
            enabled BOOLEAN DEFAULT TRUE,
            lead_days INT NOT NULL DEFAULT 5,
            sms_template VARCHAR(200),
            email_template VARCHAR(200),
            custom_sms_message TEXT,
            custom_email_message TEXT,
            include_preferred_vendors BOOLEAN DEFAULT TRUE,
            preferred_vendor_ids JSONB DEFAULT '[]'::jsonb,
            updated_by VARCHAR(100),
            updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
        """
    )
    execute_query(
        """
        CREATE UNIQUE INDEX IF NOT EXISTS idx_nudge_settings_type
        ON nudge_settings(nudge_type)
        """
    )
    for nudge_type, defaults in NUDGE_DEFAULTS.items():
        execute_query(
            """
            INSERT INTO nudge_settings (
                nudge_type, enabled, lead_days, sms_template, email_template,
                include_preferred_vendors, preferred_vendor_ids, updated_by, updated_at
            )
            VALUES (%s, TRUE, %s, %s, %s, %s, '[]'::jsonb, 'system', CURRENT_TIMESTAMP)
            ON CONFLICT (nudge_type) DO NOTHING
            """,
            (
                nudge_type,
                defaults["lead_days"],
                defaults["sms_template"],
                defaults["email_template"],
                defaults.get("include_preferred_vendors", False),
            ),
        )


def ensure_nudge_agent_whitelist_table():
    """Create whitelist table for high-discipline agents."""
    execute_query(
        """
        CREATE TABLE IF NOT EXISTS nudge_agent_whitelist (
            id SERIAL PRIMARY KEY,
            agent_name VARCHAR(200),
            agent_phone VARCHAR(25),
            agent_email VARCHAR(200),
            notes TEXT,
            active BOOLEAN DEFAULT TRUE,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
        """
    )
    execute_query(
        """
        CREATE UNIQUE INDEX IF NOT EXISTS idx_nudge_agent_whitelist_phone
        ON nudge_agent_whitelist(agent_phone)
        """
    )
    execute_query(
        """
        CREATE UNIQUE INDEX IF NOT EXISTS idx_nudge_agent_whitelist_email
        ON nudge_agent_whitelist(agent_email)
        """
    )


def ensure_nudge_automation_tables():
    """Ensure nudge automation persistence exists."""
    ensure_nudge_log_table()
    ensure_nudge_settings_table()
    ensure_nudge_agent_whitelist_table()


def fetch_nudge_settings():
    """Return settings keyed by nudge type merged with defaults."""
    rows = execute_query(
        """
        SELECT
            nudge_type,
            enabled,
            lead_days,
            sms_template,
            email_template,
            custom_sms_message,
            custom_email_message,
            include_preferred_vendors,
            preferred_vendor_ids
        FROM nudge_settings
        """,
        fetch=True,
    ) or []
    settings = {}
    for nudge_type, defaults in NUDGE_DEFAULTS.items():
        settings[nudge_type] = {
            "enabled": True,
            "lead_days": defaults["lead_days"],
            "sms_template": defaults["sms_template"],
            "email_template": defaults["email_template"],
            "custom_sms_message": "",
            "custom_email_message": "",
            "include_preferred_vendors": defaults.get("include_preferred_vendors", False),
            "preferred_vendor_ids": [],
        }
    for row in rows:
        nudge_type = (row.get("nudge_type") or "").strip()
        if nudge_type not in settings:
            continue
        preferred_vendor_ids = row.get("preferred_vendor_ids") or []
        if isinstance(preferred_vendor_ids, str):
            preferred_vendor_ids = []
        settings[nudge_type].update(
            {
                "enabled": bool(row.get("enabled")),
                "lead_days": int(row.get("lead_days") or settings[nudge_type]["lead_days"]),
                "sms_template": (row.get("sms_template") or settings[nudge_type]["sms_template"]).strip(),
                "email_template": (row.get("email_template") or settings[nudge_type]["email_template"]).strip(),
                "custom_sms_message": (row.get("custom_sms_message") or "").strip(),
                "custom_email_message": (row.get("custom_email_message") or "").strip(),
                "include_preferred_vendors": bool(row.get("include_preferred_vendors")),
                "preferred_vendor_ids": preferred_vendor_ids if isinstance(preferred_vendor_ids, list) else [],
            }
        )
    return settings


def fetch_whitelist_rows():
    """Return active nudge whitelist rows."""
    return execute_query(
        """
        SELECT id, agent_name, agent_phone, agent_email
        FROM nudge_agent_whitelist
        WHERE active = TRUE
        """,
        fetch=True,
    ) or []


def transaction_agent_is_whitelisted(transaction, whitelist_rows):
    """True when transaction agent is in no-nudge whitelist."""
    agent_last10 = phone_last10(transaction.get("agent_phone"))
    agent_email = normalize_email(transaction.get("agent_email"))
    for row in whitelist_rows:
        if agent_last10 and phone_last10(row.get("agent_phone")) == agent_last10:
            return True
        if agent_email and normalize_email(row.get("agent_email")) == agent_email:
            return True
    return False


def get_task_by_description(transaction_id, description):
    """Find one task by partial description."""
    rows = execute_query(
        """
        SELECT id, task_description, completed, status, completed_by, due_date
        FROM tasks
        WHERE transaction_id = %s
          AND LOWER(COALESCE(task_description, '')) LIKE %s
        ORDER BY id DESC
        LIMIT 1
        """,
        (transaction_id, f"%{(description or '').strip().lower()}%"),
        fetch=True,
    ) or []
    return rows[0] if rows else None


def get_document_by_type(transaction_id, document_type):
    """Find one document by type or type tuple."""
    if isinstance(document_type, (list, tuple, set)):
        doc_types = tuple(str(item).strip().lower() for item in document_type if str(item).strip())
        if not doc_types:
            return None
        rows = execute_query(
            """
            SELECT id, document_type, uploaded_at
            FROM documents
            WHERE transaction_id = %s
              AND document_type = ANY(%s)
            ORDER BY uploaded_at DESC, id DESC
            LIMIT 1
            """,
            (transaction_id, list(doc_types)),
            fetch=True,
        ) or []
        return rows[0] if rows else None

    rows = execute_query(
        """
        SELECT id, document_type, uploaded_at
        FROM documents
        WHERE transaction_id = %s
          AND document_type = %s
        ORDER BY uploaded_at DESC, id DESC
        LIMIT 1
        """,
        (transaction_id, str(document_type).strip().lower()),
        fetch=True,
    ) or []
    return rows[0] if rows else None


def get_client_email(transaction_id, client_type):
    """Get latest buyer/seller portal email for transaction."""
    rows = execute_query(
        """
        SELECT email
        FROM client_access
        WHERE transaction_id = %s
          AND client_type = %s
          AND COALESCE(email, '') <> ''
        ORDER BY created_date DESC NULLS LAST, id DESC
        LIMIT 1
        """,
        (transaction_id, (client_type or "").strip().lower()),
        fetch=True,
    ) or []
    return normalize_email(rows[0].get("email")) if rows else ""


def calculate_earnest_amount(transaction):
    """Estimate earnest amount as 1% contract price when available."""
    contract_price = transaction.get("contract_price")
    if contract_price in (None, ""):
        return 0.0
    try:
        return float(contract_price) * 0.01
    except (TypeError, ValueError):
        return 0.0


def get_preferred_inspectors(setting):
    """Build inspector recommendation list from selected/preferred vendors."""
    include_preferred = bool(setting.get("include_preferred_vendors"))
    selected_ids = []
    for raw_id in setting.get("preferred_vendor_ids") or []:
        try:
            selected_ids.append(int(raw_id))
        except (TypeError, ValueError):
            continue

    rows = []
    if include_preferred and selected_ids:
        rows = execute_query(
            """
            SELECT id, company_name, contact_name, phone, email
            FROM vendor_contacts
            WHERE vendor_type = 'inspector'
              AND active = TRUE
              AND id = ANY(%s)
            ORDER BY preferred DESC, company_name ASC NULLS LAST, id ASC
            LIMIT 5
            """,
            (selected_ids,),
            fetch=True,
        ) or []
    elif include_preferred:
        rows = execute_query(
            """
            SELECT id, company_name, contact_name, phone, email
            FROM vendor_contacts
            WHERE vendor_type = 'inspector'
              AND active = TRUE
              AND preferred = TRUE
            ORDER BY company_name ASC NULLS LAST, id ASC
            LIMIT 5
            """,
            fetch=True,
        ) or []

    recommendations = []
    for row in rows:
        recommendations.append(
            {
                "name": row.get("contact_name") or row.get("company_name") or "Inspector",
                "phone": row.get("phone") or "Phone unavailable",
                "email": row.get("email") or "",
            }
        )
    if recommendations:
        return recommendations

    # Fallback to env-configured recommendations.
    raw_value = (os.getenv("INSPECTOR_RECOMMENDATIONS") or "").strip()
    if raw_value:
        for chunk in raw_value.split(";"):
            item = chunk.strip()
            if not item:
                continue
            parts = [piece.strip() for piece in item.split("|")]
            recommendations.append(
                {
                    "name": parts[0] if len(parts) > 0 else "Inspector",
                    "phone": parts[1] if len(parts) > 1 else "Phone unavailable",
                    "email": parts[2] if len(parts) > 2 else "",
                }
            )
    if recommendations:
        return recommendations[:5]
    return [
        {"name": "Lone Star Inspection Group", "phone": "(214) 555-0130", "email": ""},
        {"name": "North Texas Home Inspectors", "phone": "(817) 555-0194", "email": ""},
    ]


def recent_manual_followup_exists(transaction_id, nudge_type):
    """Skip new nudge if Margaret has already completed a matching follow-up task."""
    search_phrase = f"follow up on {nudge_type.replace('_', ' ')}"
    rows = execute_query(
        """
        SELECT id
        FROM tasks
        WHERE transaction_id = %s
          AND completed = TRUE
          AND LOWER(COALESCE(task_description, '')) LIKE %s
          AND completed_at >= (CURRENT_TIMESTAMP - INTERVAL '21 days')
        LIMIT 1
        """,
        (transaction_id, f"%{search_phrase}%"),
        fetch=True,
    ) or []
    return bool(rows)


def nudge_already_logged(transaction_id, deadline_id, nudge_type):
    """Prevent duplicate nudge sends for the same cycle."""
    rows = execute_query(
        """
        SELECT id, response_received, escalated_to_margaret
        FROM nudge_log
        WHERE transaction_id = %s
          AND deadline_id = %s
          AND nudge_type = %s
        LIMIT 1
        """,
        (transaction_id, deadline_id, nudge_type),
        fetch=True,
    ) or []
    if rows:
        return True
    if recent_manual_followup_exists(transaction_id, nudge_type):
        return True
    return False


def check_nudge_criteria(deadline, days_until, transaction, settings):
    """
    Determine if nudge is needed based on deadline type and missing progress.
    """
    deadline_type = (deadline.get("deadline_type") or "").strip().lower()
    transaction_id = transaction["id"]

    if deadline_type == "option_period_end":
        setting = settings["inspection_not_scheduled"]
        if not setting["enabled"] or days_until != setting["lead_days"]:
            return (False, None)
        inspection_task = get_task_by_description(transaction_id, "Schedule home inspection")
        inspection_doc = get_document_by_type(transaction_id, ("inspection_report", "inspection"))
        if (not inspection_task or not inspection_task.get("completed")) and not inspection_doc:
            return (True, "inspection_not_scheduled")

    elif deadline_type in {"earnest_money", "earnest_due_date"}:
        setting = settings["earnest_not_received"]
        if not setting["enabled"] or days_until != setting["lead_days"]:
            return (False, None)
        earnest_doc = get_document_by_type(transaction_id, ("earnest_receipt", "earnest_money_receipt"))
        if not earnest_doc:
            return (True, "earnest_not_received")

    elif deadline_type in {"financing_approval", "financing_approval_date"}:
        setting = settings["appraisal_not_ordered"]
        if not setting["enabled"] or days_until != setting["lead_days"]:
            return (False, None)
        appraisal_task = get_task_by_description(transaction_id, "Verify appraisal completed")
        appraisal_doc = get_document_by_type(transaction_id, ("appraisal", "appraisal_report"))
        if (not appraisal_task or not appraisal_task.get("completed")) and not appraisal_doc:
            return (True, "appraisal_not_ordered")

    elif deadline_type in {"hoa_docs", "hoa_docs_due_date"}:
        setting = settings["hoa_docs_not_received"]
        if not setting["enabled"] or days_until != setting["lead_days"]:
            return (False, None)
        hoa_docs = get_document_by_type(transaction_id, ("hoa", "hoa_documents", "hoa_docs"))
        if not hoa_docs:
            return (True, "hoa_docs_not_received")

    elif deadline_type in {"survey", "survey_due_date"}:
        setting = settings["survey_not_ordered"]
        if not setting["enabled"] or days_until != setting["lead_days"]:
            return (False, None)
        survey_task = get_task_by_description(transaction_id, "Get survey")
        survey_doc = get_document_by_type(transaction_id, ("survey", "survey_report"))
        if (not survey_task or not survey_task.get("completed")) and not survey_doc:
            return (True, "survey_not_ordered")

    elif deadline_type in {"title_commitment", "title_commitment_due_date"}:
        setting = settings["title_not_received"]
        if not setting["enabled"] or days_until != setting["lead_days"]:
            return (False, None)
        title_doc = get_document_by_type(transaction_id, ("title_commitment",))
        if not title_doc:
            return (True, "title_not_received")

    return (False, None)


def render_nudge_template(template_name, context):
    """Render template from templates/nudges and return plain text string."""
    env = template_environment()
    try:
        template = env.get_template(f"nudges/{template_name}")
    except TemplateNotFound:
        return ""
    return template.render(**context).strip()


def create_followup_task(transaction_id, description, due_date):
    """Create one open follow-up task for unresolved nudge."""
    existing = execute_query(
        """
        SELECT id
        FROM tasks
        WHERE transaction_id = %s
          AND LOWER(COALESCE(task_description, '')) = LOWER(%s)
          AND completed = FALSE
          AND COALESCE(status, 'pending') <> 'completed'
        LIMIT 1
        """,
        (transaction_id, description),
        fetch=True,
    ) or []
    if existing:
        return existing[0]["id"]

    rows = execute_query(
        """
        INSERT INTO tasks (
            transaction_id, task_description, task_category, due_date, priority,
            status, completed, display_order, notes, created_at
        )
        VALUES (%s, %s, 'coordination', %s, 'medium', 'pending', FALSE, 66, %s, CURRENT_TIMESTAMP)
        RETURNING id
        """,
        (
            transaction_id,
            description[:280],
            due_date,
            "Auto-created from intelligent nudge automation.",
        ),
        fetch=True,
    ) or []
    return rows[0]["id"] if rows else None


def log_nudge_sent(transaction_id, deadline_id, nudge_type, sent_to):
    """Record nudge send in nudge_log, deduping same deadline/type."""
    execute_query(
        """
        INSERT INTO nudge_log (
            transaction_id, deadline_id, nudge_type, sent_to, sent_at,
            response_received, escalated_to_margaret
        )
        VALUES (%s, %s, %s, %s, CURRENT_TIMESTAMP, FALSE, FALSE)
        ON CONFLICT (transaction_id, deadline_id, nudge_type)
        DO NOTHING
        """,
        (transaction_id, deadline_id, nudge_type, sent_to[:200] if sent_to else None),
    )


def send_deadline_nudge(transaction, deadline, nudge_type, days_until, settings):
    """
    Send appropriate nudge based on nudge type/settings.
    """
    setting = settings.get(nudge_type, {})
    defaults = NUDGE_DEFAULTS[nudge_type]
    transaction_id = transaction["id"]
    deadline_id = deadline["id"]

    if nudge_already_logged(transaction_id, deadline_id, nudge_type):
        return False

    seller_email = get_client_email(transaction_id, "seller")
    lender_email = normalize_email(transaction.get("lender_email"))
    agent_email = normalize_email(transaction.get("agent_email"))
    title_email = normalize_email(transaction.get("title_officer_email"))

    recipient_phone = ""
    recipient_email = ""
    if nudge_type == "inspection_not_scheduled":
        recipient_phone = normalize_phone(transaction.get("agent_phone"))
        recipient_email = agent_email
    elif nudge_type == "earnest_not_received":
        recipient_phone = normalize_phone(transaction.get("agent_phone"))
        recipient_email = agent_email
    elif nudge_type == "appraisal_not_ordered":
        recipient_phone = normalize_phone(transaction.get("lender_phone") or transaction.get("agent_phone"))
        recipient_email = lender_email or agent_email
    elif nudge_type == "hoa_docs_not_received":
        recipient_phone = normalize_phone(transaction.get("seller_phone"))
        recipient_email = seller_email or agent_email
    elif nudge_type == "survey_not_ordered":
        recipient_phone = normalize_phone(transaction.get("agent_phone"))
        recipient_email = agent_email
    elif nudge_type == "title_not_received":
        recipient_phone = normalize_phone(transaction.get("title_officer_phone") or transaction.get("agent_phone"))
        recipient_email = title_email or agent_email

    context = {
        "agent_name": transaction.get("agent_name") or "Agent",
        "buyer_name": transaction.get("buyer_name") or "Buyer",
        "lender_name": transaction.get("lender_name") or "Lender",
        "property_address": transaction.get("property_address") or "Property",
        "due_date": deadline.get("deadline_date"),
        "days_remaining": days_until,
        "option_period_end": deadline.get("deadline_date"),
        "financing_deadline": deadline.get("deadline_date"),
        "earnest_amount": calculate_earnest_amount(transaction),
        "margaret_phone": normalize_phone(os.getenv("MARGARET_PHONE") or ""),
        "inspector_recommendations": get_preferred_inspectors(setting),
        "seller_agent_name": transaction.get("agent_name") or "Listing Agent",
    }
    context["subject"] = defaults["subject"].format(property_address=context["property_address"])

    sms_template = (setting.get("sms_template") or defaults["sms_template"]).strip()
    email_template = (setting.get("email_template") or defaults["email_template"]).strip()
    custom_sms = (setting.get("custom_sms_message") or "").strip()
    custom_email = (setting.get("custom_email_message") or "").strip()

    if custom_sms:
        sms_message = template_environment().from_string(custom_sms).render(**context).strip()
    else:
        sms_message = render_nudge_template(sms_template, context)

    sms_sid = None
    if recipient_phone and sms_message:
        sms_sid = send_sms(recipient_phone, sms_message)

    email_result = None
    if recipient_email:
        email_context = dict(context)
        if custom_email:
            email_context["custom_email_message"] = template_environment().from_string(custom_email).render(
                **context
            )
        email_result = send_email(
            to=recipient_email,
            template=f"nudges/{email_template}",
            data=email_context,
            reply_to=os.getenv("MARGARET_EMAIL"),
        )

    if not sms_sid and not email_result:
        return False

    sent_to_parts = []
    if recipient_phone and sms_sid:
        sent_to_parts.append(recipient_phone)
    if recipient_email and email_result:
        sent_to_parts.append(recipient_email)
    sent_to = " | ".join(sent_to_parts) if sent_to_parts else (recipient_phone or recipient_email)
    log_nudge_sent(transaction_id, deadline_id, nudge_type, sent_to)

    create_followup_task(
        transaction_id=transaction_id,
        description=f"Follow up on {nudge_type.replace('_', ' ')}",
        due_date=date.today() + timedelta(days=1),
    )

    execute_query(
        """
        INSERT INTO communications (transaction_id, communication_type, contact_party, contact_name, summary, outcome)
        VALUES (%s, %s, %s, %s, %s, %s)
        """,
        (
            transaction_id,
            "text" if sms_sid else "email",
            "agent",
            transaction.get("agent_name") or "Agent",
            f"Intelligent nudge sent ({nudge_type})",
            f"sms_sid={sms_sid or 'n/a'} email_id={email_result or 'n/a'}",
        ),
    )
    return True


def check_and_send_nudges():
    """
    Check all active transactions and send proactive nudges.
    """
    ensure_nudge_automation_tables()
    settings = fetch_nudge_settings()
    whitelist_rows = fetch_whitelist_rows()
    transactions = get_active_transactions()

    total_sent = 0
    for transaction in transactions:
        deadlines = get_transaction_deadlines(transaction["id"])
        agent_whitelisted = transaction_agent_is_whitelisted(transaction, whitelist_rows)

        for deadline in deadlines:
            if deadline.get("completed"):
                continue
            if not deadline.get("deadline_date"):
                continue

            days_until = (deadline["deadline_date"] - date.today()).days
            if days_until < 0:
                continue

            nudge_needed, nudge_type = check_nudge_criteria(
                deadline=deadline,
                days_until=days_until,
                transaction=transaction,
                settings=settings,
            )
            if not nudge_needed:
                continue

            if agent_whitelisted and nudge_type in AGENT_OWNED_NUDGE_TYPES:
                continue
            if nudge_already_logged(transaction["id"], deadline["id"], nudge_type):
                continue

            if send_deadline_nudge(transaction, deadline, nudge_type, days_until, settings):
                total_sent += 1

    return total_sent


def main():
    """CLI entrypoint for cron jobs."""
    log("Starting intelligent nudge automation run")
    sent_count = check_and_send_nudges()
    log(f"Intelligent nudge run complete. Nudges sent: {sent_count}")


if __name__ == "__main__":
    main()
