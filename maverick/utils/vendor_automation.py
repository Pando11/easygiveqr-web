import os
from datetime import date, datetime, timedelta, timezone

from utils.db import execute_insert, execute_query
from utils.email import send_email

VENDOR_TYPES = ("inspector", "appraiser", "surveyor", "title")

VENDOR_TEMPLATE_MAP = {
    "inspector": "emails/vendor_requests/inspector_request.html",
    "appraiser": "emails/vendor_requests/appraiser_request.html",
    "surveyor": "emails/vendor_requests/surveyor_request.html",
    "title": "emails/vendor_requests/title_request.html",
}

VENDOR_SUBJECT_MAP = {
    "inspector": "Inspection Needed - {property_address}",
    "appraiser": "Appraisal Needed - {property_address}",
    "surveyor": "Survey Needed - {property_address}",
    "title": "Title Coordination Needed - {property_address}",
}


def normalize_vendor_type(vendor_type):
    """Normalize vendor type labels used across legacy and new flows."""
    normalized = (vendor_type or "").strip().lower()
    aliases = {
        "survey": "surveyor",
        "survey_company": "surveyor",
        "title_company": "title",
    }
    return aliases.get(normalized, normalized)


def vendor_label(vendor_type):
    """Human-readable label from a normalized vendor type."""
    normalized = normalize_vendor_type(vendor_type)
    if normalized == "surveyor":
        return "Surveyor"
    return normalized.title() if normalized else "Vendor"


def ensure_vendor_contacts_table():
    """Create vendor_contacts and its indexes when missing."""
    execute_query(
        """
        CREATE TABLE IF NOT EXISTS vendor_contacts (
            id SERIAL PRIMARY KEY,
            vendor_type VARCHAR(50),
            company_name VARCHAR(200),
            contact_name VARCHAR(200),
            email VARCHAR(200),
            phone VARCHAR(20),
            scheduling_url TEXT,
            service_area VARCHAR(150),
            preferred BOOLEAN DEFAULT FALSE,
            active BOOLEAN DEFAULT TRUE,
            notes TEXT,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
        """
    )
    execute_query(
        """
        CREATE INDEX IF NOT EXISTS idx_vendor_contacts_type_active
        ON vendor_contacts(vendor_type, active, preferred)
        """
    )
    execute_query(
        """
        CREATE INDEX IF NOT EXISTS idx_vendor_contacts_company_name
        ON vendor_contacts(company_name)
        """
    )


def ensure_vendor_outreach_log_table():
    """Create vendor_outreach_log and indexes when missing."""
    execute_query(
        """
        CREATE TABLE IF NOT EXISTS vendor_outreach_log (
            id SERIAL PRIMARY KEY,
            transaction_id INT REFERENCES transactions(id) ON DELETE CASCADE,
            vendor_type VARCHAR(50),
            vendor_id INT REFERENCES vendor_contacts(id) ON DELETE SET NULL,
            outreach_type VARCHAR(50),
            outreach_date TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            response_received BOOLEAN DEFAULT FALSE,
            response_date TIMESTAMP,
            scheduled_date DATE,
            notes TEXT
        )
        """
    )
    execute_query(
        """
        CREATE INDEX IF NOT EXISTS idx_vendor_outreach_log_pending
        ON vendor_outreach_log(outreach_type, response_received, outreach_date)
        """
    )
    execute_query(
        """
        CREATE INDEX IF NOT EXISTS idx_vendor_outreach_log_transaction
        ON vendor_outreach_log(transaction_id, outreach_date DESC)
        """
    )


def ensure_vendor_automation_tables():
    """Ensure all vendor automation tables exist."""
    ensure_vendor_contacts_table()
    ensure_vendor_outreach_log_table()


def get_transaction_by_id(transaction_id):
    """Fetch transaction fields needed for vendor outreach."""
    rows = execute_query(
        """
        SELECT
            id,
            property_address,
            option_period_end_date,
            financing_approval_date,
            closing_date,
            buyer_name,
            agent_name,
            agent_phone,
            rush_service,
            status
        FROM transactions
        WHERE id = %s
        LIMIT 1
        """,
        (transaction_id,),
        fetch=True,
    ) or []
    return rows[0] if rows else None


def get_preferred_vendor(vendor_type, property_address=None):
    """Return best-matching active vendor for type + optional area."""
    ensure_vendor_contacts_table()
    normalized = normalize_vendor_type(vendor_type)
    rows = execute_query(
        """
        SELECT
            id,
            vendor_type,
            company_name,
            contact_name,
            email,
            phone,
            scheduling_url,
            service_area,
            preferred,
            active,
            notes,
            created_at
        FROM vendor_contacts
        WHERE active = TRUE
          AND vendor_type = %s
        ORDER BY
          CASE
            WHEN COALESCE(service_area, '') <> ''
             AND %s <> ''
             AND %s ILIKE ('%%' || service_area || '%%')
            THEN 0 ELSE 1
          END ASC,
          preferred DESC,
          created_at ASC
        LIMIT 1
        """,
        (normalized, property_address or "", property_address or ""),
        fetch=True,
    ) or []
    return rows[0] if rows else None


def preferred_vendor_date(transaction, vendor_type):
    """Calculate a preferred target date label for each vendor type."""
    normalized = normalize_vendor_type(vendor_type)
    option_end = transaction.get("option_period_end_date")
    financing = transaction.get("financing_approval_date")
    closing = transaction.get("closing_date")

    preferred_date_value = None
    if normalized == "inspector":
        if option_end:
            preferred_date_value = option_end - timedelta(days=3)
        elif closing:
            preferred_date_value = closing - timedelta(days=14)
    elif normalized == "appraiser":
        if financing:
            preferred_date_value = financing - timedelta(days=7)
        elif closing:
            preferred_date_value = closing - timedelta(days=10)
    elif normalized == "surveyor":
        if option_end:
            preferred_date_value = option_end - timedelta(days=2)
    elif normalized == "title" and closing:
        preferred_date_value = closing - timedelta(days=10)

    if preferred_date_value:
        return preferred_date_value.strftime("%b %d, %Y")
    return ""


def create_vendor_followup_task(transaction_id, vendor_type):
    """Create next-day task to verify vendor scheduling response."""
    normalized = normalize_vendor_type(vendor_type)
    label = normalized if normalized != "surveyor" else "surveyor"
    due_date = date.today() + timedelta(days=1)
    task_id = execute_insert(
        """
        INSERT INTO tasks (
            transaction_id,
            task_description,
            task_category,
            due_date,
            priority,
            status,
            completed,
            display_order,
            notes,
            created_at
        )
        VALUES (%s, %s, 'vendor_coordination', %s, 'medium', 'pending', FALSE, 47, %s, CURRENT_TIMESTAMP)
        RETURNING id
        """,
        (
            transaction_id,
            f"Follow up with {label} if no response",
            due_date,
            "Auto-created after vendor scheduling email request.",
        ),
    )
    return task_id


def log_vendor_outreach(
    transaction_id,
    vendor_type,
    vendor_id=None,
    outreach_type="email_sent",
    outreach_date=None,
    response_received=False,
    response_date=None,
    scheduled_date=None,
    notes=None,
):
    """Insert an outreach audit row and update pending sent rows on response."""
    ensure_vendor_outreach_log_table()
    normalized = normalize_vendor_type(vendor_type)
    outreach_log_id = execute_insert(
        """
        INSERT INTO vendor_outreach_log (
            transaction_id,
            vendor_type,
            vendor_id,
            outreach_type,
            outreach_date,
            response_received,
            response_date,
            scheduled_date,
            notes
        )
        VALUES (%s, %s, %s, %s, COALESCE(%s, CURRENT_TIMESTAMP), %s, %s, %s, %s)
        RETURNING id
        """,
        (
            transaction_id,
            normalized,
            vendor_id,
            outreach_type,
            outreach_date,
            bool(response_received),
            response_date,
            scheduled_date,
            notes,
        ),
    )

    if outreach_type in {"response_received", "scheduled"}:
        execute_query(
            """
            UPDATE vendor_outreach_log
            SET response_received = TRUE,
                response_date = COALESCE(%s, CURRENT_TIMESTAMP),
                scheduled_date = COALESCE(%s, scheduled_date)
            WHERE transaction_id = %s
              AND vendor_type = %s
              AND (%s IS NULL OR vendor_id = %s)
              AND outreach_type IN ('email_sent', 'follow_up_sent')
              AND response_received = FALSE
            """,
            (
                response_date,
                scheduled_date,
                transaction_id,
                normalized,
                vendor_id,
                vendor_id,
            ),
        )

    return outreach_log_id


def _vendor_request_context(transaction, vendor, vendor_type):
    property_address = transaction.get("property_address") or "Property"
    subject_template = VENDOR_SUBJECT_MAP.get(vendor_type, "Vendor Request - {property_address}")
    return {
        "subject": subject_template.format(property_address=property_address),
        "vendor_name": vendor.get("contact_name") or vendor.get("company_name") or vendor_label(vendor_type),
        "property_address": property_address,
        "transaction_id": transaction["id"],
        "preferred_date": preferred_vendor_date(transaction, vendor_type),
        "buyer_name": transaction.get("buyer_name") or "",
        "agent_name": transaction.get("agent_name") or "",
        "agent_phone": transaction.get("agent_phone") or "",
        "margaret_phone": os.getenv("MARGARET_PHONE"),
        "scheduling_url": (vendor.get("scheduling_url") or "").strip(),
        "is_rush": bool(transaction.get("rush_service")),
    }


def send_vendor_requests(transaction_id):
    """
    Auto-send scheduling requests to preferred active vendors after approval.

    Returns dict with sent_count and per-vendor results.
    """
    ensure_vendor_automation_tables()
    transaction = get_transaction_by_id(transaction_id)
    if not transaction:
        return {"success": False, "error": "transaction_not_found", "sent_count": 0, "results": []}

    vendors = {
        "inspector": get_preferred_vendor("inspector", transaction.get("property_address")),
        "appraiser": get_preferred_vendor("appraiser", transaction.get("property_address")),
        "surveyor": get_preferred_vendor("surveyor", transaction.get("property_address")),
        "title": get_preferred_vendor("title", transaction.get("property_address")),
    }

    results = []
    for vendor_type, vendor in vendors.items():
        if not vendor:
            results.append({"vendor_type": vendor_type, "sent": False, "reason": "no_active_vendor"})
            continue
        to_email = (vendor.get("email") or "").strip()
        if not to_email:
            results.append({"vendor_type": vendor_type, "sent": False, "reason": "missing_email"})
            continue

        context = _vendor_request_context(transaction, vendor, vendor_type)
        template_name = VENDOR_TEMPLATE_MAP[vendor_type]
        message_id = send_email(
            to=to_email,
            template=template_name,
            data=context,
            reply_to=os.getenv("MARGARET_EMAIL"),
        )

        outreach_type = "email_sent" if message_id else "email_failed"
        outreach_log_id = log_vendor_outreach(
            transaction_id=transaction_id,
            vendor_type=vendor_type,
            vendor_id=vendor.get("id"),
            outreach_type=outreach_type,
            response_received=False,
            notes=f"message_id={message_id or 'failed'}",
        )
        followup_task_id = create_vendor_followup_task(transaction_id, vendor_type)

        execute_query(
            """
            INSERT INTO communications (transaction_id, communication_type, contact_party, contact_name, summary, outcome)
            VALUES (%s, 'email', %s, %s, %s, %s)
            """,
            (
                transaction_id,
                vendor_type,
                context["vendor_name"],
                "Vendor request email sent" if message_id else "Vendor request email failed",
                (
                    f"to={to_email} outreach_log_id={outreach_log_id or 'n/a'} "
                    f"task_id={followup_task_id or 'n/a'} message_id={message_id or 'failed'}"
                ),
            ),
        )

        results.append(
            {
                "vendor_type": vendor_type,
                "vendor_id": vendor.get("id"),
                "vendor_email": to_email,
                "sent": bool(message_id),
                "outreach_log_id": outreach_log_id,
                "followup_task_id": followup_task_id,
                "message_id": message_id,
            }
        )

    sent_count = len([row for row in results if row.get("sent")])
    return {"success": True, "transaction_id": transaction_id, "sent_count": sent_count, "results": results}


def parse_schedule_datetime(raw_value):
    """Parse vendor scheduling webhook timestamp payloads."""
    if raw_value is None:
        return None
    if isinstance(raw_value, datetime):
        return raw_value
    if isinstance(raw_value, date):
        return datetime.combine(raw_value, datetime.min.time())
    if isinstance(raw_value, (int, float)):
        try:
            return datetime.fromtimestamp(raw_value, tz=timezone.utc).replace(tzinfo=None)
        except Exception:
            return None

    value = str(raw_value).strip()
    if not value:
        return None
    value = value.replace("Z", "+00:00")
    try:
        parsed = datetime.fromisoformat(value)
        if parsed.tzinfo:
            return parsed.astimezone(timezone.utc).replace(tzinfo=None)
        return parsed
    except ValueError:
        pass

    for fmt in ("%Y-%m-%d %H:%M:%S", "%Y-%m-%d %H:%M", "%Y-%m-%d"):
        try:
            return datetime.strptime(value, fmt)
        except ValueError:
            continue
    return None


def complete_vendor_followup_tasks(transaction_id, vendor_type):
    """Complete open follow-up tasks matching the vendor type."""
    normalized = normalize_vendor_type(vendor_type)
    pattern = f"%follow up with {normalized}%"
    rows = execute_query(
        """
        UPDATE tasks
        SET completed = TRUE,
            status = 'completed',
            completed_at = CURRENT_TIMESTAMP,
            completed_by = 'vendor_automation',
            notes = CASE
                WHEN COALESCE(notes, '') = '' THEN %s
                ELSE notes || E'\n' || %s
            END
        WHERE transaction_id = %s
          AND completed = FALSE
          AND LOWER(task_description) LIKE %s
        RETURNING id
        """,
        (
            "Auto-completed from vendor scheduling response.",
            "Auto-completed from vendor scheduling response.",
            transaction_id,
            pattern,
        ),
        fetch=True,
    ) or []
    return [row["id"] for row in rows]


def fetch_pending_vendor_responses(limit=30):
    """Return unresolved vendor outreach rows for the daily checklist."""
    ensure_vendor_automation_tables()
    rows = execute_query(
        """
        WITH latest_pending AS (
            SELECT DISTINCT ON (vol.transaction_id, vol.vendor_type, COALESCE(vol.vendor_id, 0))
                vol.id,
                vol.transaction_id,
                vol.vendor_type,
                vol.vendor_id,
                vol.outreach_type,
                vol.outreach_date,
                vol.notes,
                t.property_address,
                COALESCE(vc.company_name, '') AS company_name,
                COALESCE(vc.contact_name, '') AS contact_name,
                COALESCE(vc.email, '') AS email,
                COALESCE(vc.scheduling_url, '') AS scheduling_url
            FROM vendor_outreach_log vol
            JOIN transactions t ON t.id = vol.transaction_id
            LEFT JOIN vendor_contacts vc ON vc.id = vol.vendor_id
            WHERE t.status = 'ACTIVE'
              AND vol.outreach_type IN ('email_sent', 'follow_up_sent', 'email_failed')
              AND vol.response_received = FALSE
            ORDER BY
                vol.transaction_id,
                vol.vendor_type,
                COALESCE(vol.vendor_id, 0),
                vol.outreach_date DESC
        )
        SELECT
            id,
            transaction_id,
            vendor_type,
            vendor_id,
            outreach_type,
            outreach_date,
            notes,
            property_address,
            company_name,
            contact_name,
            email,
            scheduling_url,
            GREATEST(0, FLOOR(EXTRACT(EPOCH FROM (CURRENT_TIMESTAMP - outreach_date)) / 86400))::INT AS days_ago
        FROM latest_pending
        ORDER BY outreach_date ASC
        LIMIT %s
        """,
        (limit,),
        fetch=True,
    ) or []

    for row in rows:
        row["vendor_type_label"] = vendor_label(row.get("vendor_type"))
    return rows


def fetch_vendor_outreach_log_row(outreach_id):
    """Fetch one outreach log row with transaction + vendor context."""
    rows = execute_query(
        """
        SELECT
            vol.id,
            vol.transaction_id,
            vol.vendor_type,
            vol.vendor_id,
            vol.outreach_type,
            vol.outreach_date,
            vol.response_received,
            vol.response_date,
            vol.scheduled_date,
            vol.notes,
            t.property_address,
            t.option_period_end_date,
            t.financing_approval_date,
            t.closing_date,
            t.buyer_name,
            t.agent_name,
            t.agent_phone,
            t.rush_service,
            vc.company_name,
            vc.contact_name,
            vc.email,
            vc.scheduling_url
        FROM vendor_outreach_log vol
        JOIN transactions t ON t.id = vol.transaction_id
        LEFT JOIN vendor_contacts vc ON vc.id = vol.vendor_id
        WHERE vol.id = %s
        LIMIT 1
        """,
        (outreach_id,),
        fetch=True,
    ) or []
    return rows[0] if rows else None


def send_manual_vendor_follow_up(outreach_id, requested_by="margaret"):
    """Re-send a vendor scheduling request for one outreach log row."""
    row = fetch_vendor_outreach_log_row(outreach_id)
    if not row:
        return {"success": False, "error": "outreach_not_found"}
    to_email = (row.get("email") or "").strip()
    if not to_email:
        return {"success": False, "error": "vendor_email_missing"}

    normalized = normalize_vendor_type(row.get("vendor_type"))
    transaction = {
        "id": row["transaction_id"],
        "property_address": row.get("property_address"),
        "option_period_end_date": row.get("option_period_end_date"),
        "financing_approval_date": row.get("financing_approval_date"),
        "closing_date": row.get("closing_date"),
        "buyer_name": row.get("buyer_name"),
        "agent_name": row.get("agent_name"),
        "agent_phone": row.get("agent_phone"),
        "rush_service": row.get("rush_service"),
    }
    vendor = {
        "id": row.get("vendor_id"),
        "company_name": row.get("company_name"),
        "contact_name": row.get("contact_name"),
        "email": to_email,
        "scheduling_url": row.get("scheduling_url"),
    }

    context = _vendor_request_context(transaction, vendor, normalized)
    context["subject"] = f"Follow Up: {context['subject']}"
    message_id = send_email(
        to=to_email,
        template=VENDOR_TEMPLATE_MAP.get(normalized, VENDOR_TEMPLATE_MAP["inspector"]),
        data=context,
        reply_to=os.getenv("MARGARET_EMAIL"),
    )
    if not message_id:
        return {"success": False, "error": "email_send_failed"}

    follow_up_id = log_vendor_outreach(
        transaction_id=row["transaction_id"],
        vendor_type=normalized,
        vendor_id=row.get("vendor_id"),
        outreach_type="follow_up_sent",
        response_received=False,
        notes=f"manual_follow_up_by={requested_by} message_id={message_id}",
    )
    execute_query(
        """
        INSERT INTO communications (transaction_id, communication_type, contact_party, contact_name, summary, outcome)
        VALUES (%s, 'email', %s, %s, %s, %s)
        """,
        (
            row["transaction_id"],
            normalized,
            context["vendor_name"],
            "Vendor follow-up email sent",
            f"outreach_log_id={follow_up_id or 'n/a'} message_id={message_id}",
        ),
    )
    return {"success": True, "message_id": message_id, "outreach_log_id": follow_up_id}


def mark_vendor_outreach_scheduled(outreach_id, scheduled_datetime=None, notes=None, source="manual"):
    """Mark one outreach cycle as scheduled and close matching follow-up tasks."""
    row = fetch_vendor_outreach_log_row(outreach_id)
    if not row:
        return {"success": False, "error": "outreach_not_found"}

    parsed_dt = parse_schedule_datetime(scheduled_datetime)
    scheduled_date = parsed_dt.date() if parsed_dt else (date.today())
    notes_value = (notes or "").strip()[:1200] or None
    log_vendor_outreach(
        transaction_id=row["transaction_id"],
        vendor_type=row.get("vendor_type"),
        vendor_id=row.get("vendor_id"),
        outreach_type="scheduled",
        response_received=True,
        response_date=datetime.utcnow(),
        scheduled_date=scheduled_date,
        notes=f"{source}_scheduled {notes_value or ''}".strip(),
    )
    completed_task_ids = complete_vendor_followup_tasks(row["transaction_id"], row.get("vendor_type"))

    execute_query(
        """
        INSERT INTO communications (transaction_id, communication_type, contact_party, contact_name, summary, outcome)
        VALUES (%s, 'note', %s, %s, %s, %s)
        """,
        (
            row["transaction_id"],
            normalize_vendor_type(row.get("vendor_type")),
            row.get("contact_name") or row.get("company_name") or "Vendor",
            "Vendor marked scheduled",
            (
                f"source={source} scheduled_date={scheduled_date.isoformat()} "
                f"completed_tasks={','.join(str(task_id) for task_id in completed_task_ids) or 'none'}"
            ),
        ),
    )

    return {
        "success": True,
        "transaction_id": row["transaction_id"],
        "vendor_type": normalize_vendor_type(row.get("vendor_type")),
        "scheduled_date": scheduled_date,
        "completed_task_ids": completed_task_ids,
    }


def fetch_vendor_contacts_with_performance():
    """Return vendors with response-rate and speed metrics."""
    ensure_vendor_automation_tables()
    rows = execute_query(
        """
        SELECT
            vc.id,
            vc.vendor_type,
            vc.company_name,
            vc.contact_name,
            vc.email,
            vc.phone,
            vc.scheduling_url,
            vc.service_area,
            vc.preferred,
            vc.active,
            vc.notes,
            vc.created_at,
            COALESCE(stats.sent_count, 0) AS sent_count,
            COALESCE(stats.responded_count, 0) AS responded_count,
            COALESCE(stats.scheduled_count, 0) AS scheduled_count,
            COALESCE(stats.response_rate, 0) AS response_rate,
            COALESCE(stats.avg_response_hours, 0) AS avg_response_hours
        FROM vendor_contacts vc
        LEFT JOIN (
            SELECT
                vendor_id,
                COUNT(*) FILTER (WHERE outreach_type IN ('email_sent', 'follow_up_sent')) AS sent_count,
                COUNT(*) FILTER (
                    WHERE outreach_type IN ('email_sent', 'follow_up_sent')
                      AND response_received = TRUE
                ) AS responded_count,
                COUNT(*) FILTER (WHERE outreach_type = 'scheduled') AS scheduled_count,
                ROUND(
                    CASE
                        WHEN COUNT(*) FILTER (WHERE outreach_type IN ('email_sent', 'follow_up_sent')) = 0 THEN 0
                        ELSE (
                            COUNT(*) FILTER (
                                WHERE outreach_type IN ('email_sent', 'follow_up_sent')
                                  AND response_received = TRUE
                            )::numeric
                            / COUNT(*) FILTER (WHERE outreach_type IN ('email_sent', 'follow_up_sent'))::numeric
                        ) * 100
                    END,
                    1
                ) AS response_rate,
                ROUND(
                    AVG(EXTRACT(EPOCH FROM (response_date - outreach_date)) / 3600)
                    FILTER (
                        WHERE outreach_type IN ('email_sent', 'follow_up_sent')
                          AND response_received = TRUE
                          AND response_date IS NOT NULL
                    )::numeric,
                    1
                ) AS avg_response_hours
            FROM vendor_outreach_log
            GROUP BY vendor_id
        ) stats ON stats.vendor_id = vc.id
        ORDER BY vc.vendor_type ASC, vc.preferred DESC, vc.active DESC, vc.company_name ASC NULLS LAST, vc.id ASC
        """,
        fetch=True,
    ) or []
    return rows


def create_vendor_contact(payload):
    """Insert a vendor contact and return new id."""
    ensure_vendor_contacts_table()
    vendor_type = normalize_vendor_type(payload.get("vendor_type"))
    return execute_insert(
        """
        INSERT INTO vendor_contacts (
            vendor_type,
            company_name,
            contact_name,
            email,
            phone,
            scheduling_url,
            service_area,
            preferred,
            active,
            notes
        )
        VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
        RETURNING id
        """,
        (
            vendor_type,
            (payload.get("company_name") or "").strip() or None,
            (payload.get("contact_name") or "").strip() or None,
            (payload.get("email") or "").strip().lower() or None,
            (payload.get("phone") or "").strip() or None,
            (payload.get("scheduling_url") or "").strip() or None,
            (payload.get("service_area") or "").strip() or None,
            bool(payload.get("preferred")),
            bool(payload.get("active", True)),
            (payload.get("notes") or "").strip() or None,
        ),
    )


def update_vendor_contact(contact_id, payload):
    """Update existing vendor contact row."""
    ensure_vendor_contacts_table()
    return execute_query(
        """
        UPDATE vendor_contacts
        SET vendor_type = %s,
            company_name = %s,
            contact_name = %s,
            email = %s,
            phone = %s,
            scheduling_url = %s,
            service_area = %s,
            preferred = %s,
            active = %s,
            notes = %s
        WHERE id = %s
        """,
        (
            normalize_vendor_type(payload.get("vendor_type")),
            (payload.get("company_name") or "").strip() or None,
            (payload.get("contact_name") or "").strip() or None,
            (payload.get("email") or "").strip().lower() or None,
            (payload.get("phone") or "").strip() or None,
            (payload.get("scheduling_url") or "").strip() or None,
            (payload.get("service_area") or "").strip() or None,
            bool(payload.get("preferred")),
            bool(payload.get("active", True)),
            (payload.get("notes") or "").strip() or None,
            contact_id,
        ),
    )


def set_vendor_contact_active(contact_id, active):
    """Mark vendor active/inactive."""
    ensure_vendor_contacts_table()
    return execute_query(
        """
        UPDATE vendor_contacts
        SET active = %s
        WHERE id = %s
        """,
        (bool(active), contact_id),
    )
