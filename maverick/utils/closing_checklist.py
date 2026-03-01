from __future__ import annotations

import json
import os
import re
import tempfile
from collections import defaultdict
from datetime import date, datetime, timedelta
from uuid import uuid4

from PyPDF2 import PdfReader
from reportlab.lib import colors
from reportlab.lib.pagesizes import letter
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import inch
from reportlab.platypus import Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle

from utils.db import execute_query
from utils.email import send_email
from utils.s3 import download_file, get_presigned_url, upload_local_file
from utils.sms import send_sms


BASE_CHECKLIST_TEMPLATE = [
    {
        "section": "CLOSING DAY LOGISTICS",
        "items": [
            "Confirm closing time and location with all parties.",
            "Verify buyer government-issued ID is ready.",
            "Verify buyer cashier check amount: {buyer_cash_to_close}.",
            "Confirm wire instructions were validated.",
            "Confirm keys and access devices transfer plan.",
        ],
    },
    {
        "section": "FUNDING AND DOCUMENTS",
        "items": [
            "Confirm final Closing Disclosure (CD) is delivered and acknowledged.",
            "Confirm lender clear-to-close status.",
            "Confirm title company has final funding package.",
            "Confirm settlement statement is available.",
        ],
    },
    {
        "section": "FINAL VERIFICATION",
        "items": [
            "Confirm final walk-through completion.",
            "Confirm negotiated credits or concessions are reflected.",
            "Confirm post-closing document delivery expectations.",
        ],
    },
]

DEFAULT_LENDER_REQUIREMENTS = {
    "generic": [
        "Confirm final underwriting conditions are cleared.",
        "Confirm CD acknowledgment timing requirements are satisfied.",
        "Confirm wire instructions and funding cutoff time.",
    ],
    "rocket": [
        "Confirm borrower portal final disclosures are signed.",
        "Confirm title package upload acknowledgment from Rocket.",
        "Confirm same-day funding cutoff and wire release contact.",
    ],
    "wells": [
        "Confirm Wells final approval status code in lender system.",
        "Confirm CD delivery timing and compliance window.",
        "Confirm title has final signed lender package.",
    ],
    "chase": [
        "Confirm Chase funding authorization number.",
        "Confirm all required borrower signatures are complete.",
        "Confirm title disbursement instructions are acknowledged.",
    ],
}

REPAIR_DOC_TYPES = {"repair_addendum", "signed_addendum", "signed_amendment"}
REPAIR_KEYWORDS = ("repair", "replace", "fix", "correct", "remedy", "patch", "seal")
SPECIAL_PROVISION_STOP_HEADERS = (
    "broker information",
    "addenda",
    "notices",
    "execution",
    "acceptance",
    "property condition",
    "financing",
)


def _normalize_email(value):
    return (value or "").strip().lower()


def _normalize_phone(value):
    digits = re.sub(r"\D", "", value or "")
    if len(digits) == 10:
        return f"+1{digits}"
    if len(digits) == 11 and digits.startswith("1"):
        return f"+{digits}"
    if (value or "").strip().startswith("+"):
        return (value or "").strip()
    return f"+{digits}" if digits else ""


def _safe_text(value, fallback="N/A"):
    text = str(value or "").strip()
    return text if text else fallback


def _format_date(value):
    if isinstance(value, datetime):
        value = value.date()
    if isinstance(value, date):
        return value.strftime("%b %d, %Y")
    return "TBD"


def _parse_json_field(raw_value, default):
    if raw_value is None:
        return default
    if isinstance(raw_value, (dict, list)):
        return raw_value
    if isinstance(raw_value, str):
        try:
            return json.loads(raw_value)
        except Exception:
            return default
    return default


def _transaction_column_exists(column_name):
    rows = execute_query(
        """
        SELECT 1
        FROM information_schema.columns
        WHERE table_name = 'transactions'
          AND column_name = %s
        LIMIT 1
        """,
        ((column_name or "").strip().lower(),),
        fetch=True,
    ) or []
    return bool(rows)


def ensure_closing_checklist_tables():
    """Create checklist core tables for generation, review, and sharing."""
    execute_query(
        """
        CREATE TABLE IF NOT EXISTS closing_checklists (
            id SERIAL PRIMARY KEY,
            transaction_id INT UNIQUE REFERENCES transactions(id) ON DELETE CASCADE,
            status VARCHAR(30) DEFAULT 'pending_review',
            trigger_date DATE,
            auto_send_after TIMESTAMP,
            generated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            reviewed_by VARCHAR(100),
            reviewed_at TIMESTAMP,
            approved_by VARCHAR(100),
            approved_at TIMESTAMP,
            sent_at TIMESTAMP,
            sent_disclaimer BOOLEAN DEFAULT FALSE,
            pdf_s3_key VARCHAR(500),
            pdf_filename VARCHAR(255),
            summary JSONB DEFAULT '{}'::jsonb,
            notes TEXT,
            updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
        """
    )
    execute_query(
        """
        CREATE TABLE IF NOT EXISTS closing_checklist_items (
            id SERIAL PRIMARY KEY,
            checklist_id INT REFERENCES closing_checklists(id) ON DELETE CASCADE,
            section_title VARCHAR(200),
            item_text TEXT NOT NULL,
            source_type VARCHAR(40) DEFAULT 'base',
            required BOOLEAN DEFAULT TRUE,
            sort_order INT DEFAULT 0,
            completed BOOLEAN DEFAULT FALSE,
            completed_by_role VARCHAR(40),
            completed_by_name VARCHAR(120),
            completed_at TIMESTAMP,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
        """
    )
    execute_query(
        """
        CREATE TABLE IF NOT EXISTS closing_checklist_recipients (
            id SERIAL PRIMARY KEY,
            checklist_id INT REFERENCES closing_checklists(id) ON DELETE CASCADE,
            party_role VARCHAR(30) NOT NULL,
            recipient_name VARCHAR(255),
            recipient_email VARCHAR(255),
            recipient_phone VARCHAR(25),
            access_token UUID UNIQUE NOT NULL,
            email_sent_at TIMESTAMP,
            sms_sent_at TIMESTAMP,
            last_viewed_at TIMESTAMP,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
        """
    )
    execute_query(
        """
        CREATE TABLE IF NOT EXISTS closing_lender_requirements (
            id SERIAL PRIMARY KEY,
            lender_name VARCHAR(255) UNIQUE NOT NULL,
            requirements JSONB DEFAULT '[]'::jsonb,
            active BOOLEAN DEFAULT TRUE,
            updated_by VARCHAR(100),
            updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
        """
    )
    execute_query(
        """
        CREATE INDEX IF NOT EXISTS idx_closing_checklists_status
        ON closing_checklists(status, auto_send_after, generated_at DESC)
        """
    )
    execute_query(
        """
        CREATE INDEX IF NOT EXISTS idx_closing_checklist_items_checklist
        ON closing_checklist_items(checklist_id, section_title, sort_order, id)
        """
    )
    execute_query(
        """
        CREATE INDEX IF NOT EXISTS idx_closing_checklist_recipients_checklist
        ON closing_checklist_recipients(checklist_id, party_role, recipient_email)
        """
    )
    execute_query(
        """
        CREATE INDEX IF NOT EXISTS idx_closing_lender_requirements_active
        ON closing_lender_requirements(active, lender_name)
        """
    )


def _fetch_transaction(transaction_id):
    rows = execute_query(
        """
        SELECT
            id, property_address, status, contract_price, contract_s3_key,
            effective_date, closing_date,
            buyer_name, buyer_phone, seller_name, seller_phone,
            agent_name, agent_phone, agent_email,
            lender_name, lender_phone, lender_email,
            title_company, title_officer_name, title_officer_phone, title_officer_email
        FROM transactions
        WHERE id = %s
        LIMIT 1
        """,
        (transaction_id,),
        fetch=True,
    ) or []
    return rows[0] if rows else None


def _fetch_client_email(transaction_id, client_type):
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
        (transaction_id, client_type),
        fetch=True,
    ) or []
    return _normalize_email(rows[0].get("email")) if rows else ""


def _extract_amounts(text):
    amounts = []
    for match in re.finditer(r"\$?\s*([0-9]{1,3}(?:,[0-9]{3})*(?:\.[0-9]{1,2})|[0-9]+(?:\.[0-9]{1,2})?)", text or ""):
        raw = match.group(1).replace(",", "")
        try:
            value = float(raw)
        except ValueError:
            continue
        if value > 0:
            amounts.append(value)
    return amounts


def _read_pdf_text_from_s3(s3_key, max_pages=12):
    if not s3_key:
        return ""
    temp_path = None
    try:
        with tempfile.NamedTemporaryFile(suffix=".pdf", delete=False) as tmp:
            temp_path = tmp.name
        if not download_file(s3_key, temp_path):
            return ""

        reader = PdfReader(temp_path)
        chunks = []
        for page in reader.pages[:max_pages]:
            chunks.append(page.extract_text() or "")
        return "\n".join(chunks).strip()
    except Exception:
        return ""
    finally:
        if temp_path and os.path.exists(temp_path):
            try:
                os.remove(temp_path)
            except OSError:
                pass


def calculate_buyer_cash_to_close(transaction):
    """Estimate buyer cash to close using available contract + earnest signals."""
    contract_price = transaction.get("contract_price")
    if contract_price is None:
        return "TBD (waiting on final CD)"
    try:
        contract_price_value = float(contract_price)
    except (TypeError, ValueError):
        return "TBD (waiting on final CD)"

    earnest_amount = 0.0
    if _transaction_column_exists("earnest_amount"):
        rows = execute_query(
            "SELECT earnest_amount FROM transactions WHERE id = %s LIMIT 1",
            (transaction["id"],),
            fetch=True,
        ) or []
        if rows:
            try:
                earnest_amount = float(rows[0].get("earnest_amount") or 0.0)
            except (TypeError, ValueError):
                earnest_amount = 0.0

    estimated_closing_costs = contract_price_value * 0.02
    estimated_cash = max(estimated_closing_costs - earnest_amount, 0.0)
    return f"${estimated_cash:,.2f} (estimated)"


def _find_repair_addendum_document(transaction_id):
    rows = execute_query(
        """
        SELECT id, document_type, filename, s3_key, uploaded_at
        FROM documents
        WHERE transaction_id = %s
          AND (
                LOWER(COALESCE(document_type, '')) = ANY(%s)
             OR LOWER(COALESCE(filename, '')) LIKE '%repair%'
          )
        ORDER BY uploaded_at DESC NULLS LAST, id DESC
        LIMIT 1
        """,
        (transaction_id, list(REPAIR_DOC_TYPES)),
        fetch=True,
    ) or []
    return rows[0] if rows else None


def extract_repair_items(repair_document_row):
    """Extract repair items from a repair addendum PDF."""
    if not repair_document_row:
        return []
    text = _read_pdf_text_from_s3(repair_document_row.get("s3_key"), max_pages=8)
    if not text:
        return []

    lines = [re.sub(r"\s+", " ", line or "").strip() for line in text.splitlines()]
    lines = [line for line in lines if len(line) >= 8]
    items = []

    bullet_pattern = re.compile(r"^(?:\d+[\).\-\s]+|[-*]\s+)(.+)$")
    for line in lines:
        bullet_match = bullet_pattern.match(line)
        candidate = bullet_match.group(1).strip() if bullet_match else line
        lower = candidate.lower()
        if any(keyword in lower for keyword in REPAIR_KEYWORDS):
            if candidate not in items:
                items.append(candidate[:260])

    if not items:
        sentences = re.split(r"[.;]\s+", re.sub(r"\s+", " ", text))
        for sentence in sentences:
            clean = sentence.strip()
            if len(clean) < 15:
                continue
            lower = clean.lower()
            if any(keyword in lower for keyword in REPAIR_KEYWORDS):
                if clean not in items:
                    items.append(clean[:260])
            if len(items) >= 10:
                break
    return items[:12]


def get_hoa_analysis(transaction_id):
    rows = execute_query(
        """
        SELECT findings
        FROM document_analysis_results
        WHERE transaction_id = %s
          AND document_type = 'hoa'
        ORDER BY analysis_date DESC, id DESC
        LIMIT 1
        """,
        (transaction_id,),
        fetch=True,
    ) or []
    if not rows:
        return {}
    findings = _parse_json_field(rows[0].get("findings"), {})
    special_assessments = findings.get("special_assessments") or []
    special_amount = None
    for item in special_assessments:
        text = item.get("text") if isinstance(item, dict) else str(item)
        for amount in _extract_amounts(text or ""):
            if special_amount is None or amount > special_amount:
                special_amount = amount
    if special_amount is None:
        outstanding = findings.get("outstanding_fees")
        if isinstance(outstanding, dict):
            for amount in _extract_amounts(outstanding.get("text") or ""):
                if special_amount is None or amount > special_amount:
                    special_amount = amount
    return {
        "special_assessment": special_amount,
        "findings": findings,
    }


def get_lender_requirements(lender_name):
    normalized_name = (lender_name or "").strip()
    if not normalized_name:
        return DEFAULT_LENDER_REQUIREMENTS["generic"]

    rows = execute_query(
        """
        SELECT requirements
        FROM closing_lender_requirements
        WHERE active = TRUE
          AND LOWER(lender_name) = LOWER(%s)
        LIMIT 1
        """,
        (normalized_name,),
        fetch=True,
    ) or []
    if rows:
        reqs = _parse_json_field(rows[0].get("requirements"), [])
        if isinstance(reqs, list) and reqs:
            return [str(item).strip()[:260] for item in reqs if str(item).strip()]

    lowered = normalized_name.lower()
    if "rocket" in lowered:
        return DEFAULT_LENDER_REQUIREMENTS["rocket"]
    if "wells" in lowered:
        return DEFAULT_LENDER_REQUIREMENTS["wells"]
    if "chase" in lowered:
        return DEFAULT_LENDER_REQUIREMENTS["chase"]
    return DEFAULT_LENDER_REQUIREMENTS["generic"]


def extract_special_provisions(contract_s3_key):
    """Extract likely special-provisions bullet list from contract text."""
    text = _read_pdf_text_from_s3(contract_s3_key, max_pages=16)
    if not text:
        return []

    normalized = re.sub(r"\r", "\n", text)
    lower = normalized.lower()
    start_idx = lower.find("special provisions")
    if start_idx == -1:
        return []

    candidate = normalized[start_idx : start_idx + 5000]
    lower_candidate = candidate.lower()
    end_idx = len(candidate)
    for header in SPECIAL_PROVISION_STOP_HEADERS:
        found = lower_candidate.find(header)
        if found > 80:
            end_idx = min(end_idx, found)
    section_text = candidate[:end_idx]

    lines = [re.sub(r"\s+", " ", line or "").strip() for line in section_text.splitlines()]
    lines = [line for line in lines if len(line) > 12 and "special provisions" not in line.lower()]
    items = []
    for line in lines:
        if re.match(r"^\d+[\).\-\s]+", line) or line.startswith("-"):
            clean = re.sub(r"^\d+[\).\-\s]+", "", line).lstrip("- ").strip()
            if clean and clean not in items:
                items.append(clean[:260])
        elif any(word in line.lower() for word in ("buyer", "seller", "closing", "repair", "credit", "allowance")):
            if line not in items:
                items.append(line[:260])
        if len(items) >= 10:
            break
    return items[:10]


def _load_base_checklist_items(transaction):
    buyer_cash = calculate_buyer_cash_to_close(transaction)
    items = []
    order = 10
    for section in BASE_CHECKLIST_TEMPLATE:
        section_name = section["section"]
        for template_item in section["items"]:
            item_text = template_item.format(buyer_cash_to_close=buyer_cash)
            items.append(
                {
                    "section_title": section_name,
                    "item_text": item_text,
                    "source_type": "base",
                    "required": True,
                    "sort_order": order,
                }
            )
            order += 10
    return items


def _append_section_items(checklist_items, section_title, section_items, source_type, start_order):
    order = start_order
    for raw_item in section_items or []:
        text = (raw_item or "").strip()
        if not text:
            continue
        checklist_items.append(
            {
                "section_title": section_title,
                "item_text": text[:320],
                "source_type": source_type,
                "required": True,
                "sort_order": order,
            }
        )
        order += 10
    return order


def _build_recipient_rows(transaction_id, transaction):
    recipients = []

    def maybe_add(role, name, email="", phone=""):
        normalized_email = _normalize_email(email)
        normalized_phone = _normalize_phone(phone)
        if not normalized_email and not normalized_phone:
            return
        recipients.append(
            {
                "party_role": role,
                "recipient_name": (name or role.title())[:255],
                "recipient_email": normalized_email[:255] if normalized_email else None,
                "recipient_phone": normalized_phone[:25] if normalized_phone else None,
            }
        )

    maybe_add(
        "agent",
        transaction.get("agent_name") or "Agent",
        email=transaction.get("agent_email"),
        phone=transaction.get("agent_phone"),
    )
    maybe_add(
        "buyer",
        transaction.get("buyer_name") or "Buyer",
        email=_fetch_client_email(transaction_id, "buyer"),
        phone=transaction.get("buyer_phone"),
    )
    maybe_add(
        "seller",
        transaction.get("seller_name") or "Seller",
        email=_fetch_client_email(transaction_id, "seller"),
        phone=transaction.get("seller_phone"),
    )
    maybe_add(
        "lender",
        transaction.get("lender_name") or "Lender",
        email=transaction.get("lender_email"),
        phone=transaction.get("lender_phone"),
    )
    maybe_add(
        "title_company",
        transaction.get("title_company") or transaction.get("title_officer_name") or "Title Company",
        email=transaction.get("title_officer_email"),
        phone=transaction.get("title_officer_phone"),
    )

    deduped = []
    seen = set()
    for row in recipients:
        key = (
            row["party_role"],
            row.get("recipient_email") or "",
            row.get("recipient_phone") or "",
        )
        if key in seen:
            continue
        seen.add(key)
        deduped.append(row)
    return deduped


def _upsert_checklist_header(transaction_id, trigger_date, summary, status="pending_review"):
    rows = execute_query(
        """
        INSERT INTO closing_checklists (
            transaction_id, status, trigger_date, auto_send_after,
            generated_at, summary, updated_at
        )
        VALUES (%s, %s, %s, CURRENT_TIMESTAMP + INTERVAL '24 hours', CURRENT_TIMESTAMP, %s::jsonb, CURRENT_TIMESTAMP)
        ON CONFLICT (transaction_id)
        DO UPDATE SET
            status = EXCLUDED.status,
            trigger_date = EXCLUDED.trigger_date,
            auto_send_after = CURRENT_TIMESTAMP + INTERVAL '24 hours',
            generated_at = CURRENT_TIMESTAMP,
            reviewed_by = NULL,
            reviewed_at = NULL,
            approved_by = NULL,
            approved_at = NULL,
            sent_at = NULL,
            sent_disclaimer = FALSE,
            summary = EXCLUDED.summary,
            updated_at = CURRENT_TIMESTAMP
        RETURNING id, transaction_id, status, generated_at, auto_send_after, summary
        """,
        (transaction_id, status, trigger_date, json.dumps(summary or {}, default=str)),
        fetch=True,
    ) or []
    return rows[0] if rows else None


def _replace_checklist_items(checklist_id, items):
    execute_query("DELETE FROM closing_checklist_items WHERE checklist_id = %s", (checklist_id,))
    for item in items:
        execute_query(
            """
            INSERT INTO closing_checklist_items (
                checklist_id, section_title, item_text, source_type, required, sort_order,
                completed, created_at, updated_at
            )
            VALUES (%s, %s, %s, %s, %s, %s, FALSE, CURRENT_TIMESTAMP, CURRENT_TIMESTAMP)
            """,
            (
                checklist_id,
                (item.get("section_title") or "GENERAL").strip()[:200],
                (item.get("item_text") or "").strip()[:500],
                (item.get("source_type") or "base")[:40],
                bool(item.get("required", True)),
                int(item.get("sort_order") or 0),
            ),
        )


def _replace_checklist_recipients(checklist_id, recipients):
    execute_query("DELETE FROM closing_checklist_recipients WHERE checklist_id = %s", (checklist_id,))
    for row in recipients:
        execute_query(
            """
            INSERT INTO closing_checklist_recipients (
                checklist_id, party_role, recipient_name, recipient_email, recipient_phone,
                access_token, created_at, updated_at
            )
            VALUES (%s, %s, %s, %s, %s, %s, CURRENT_TIMESTAMP, CURRENT_TIMESTAMP)
            """,
            (
                checklist_id,
                (row.get("party_role") or "party")[:30],
                (row.get("recipient_name") or "Party")[:255],
                row.get("recipient_email"),
                row.get("recipient_phone"),
                str(uuid4()),
            ),
        )


def fetch_closing_checklist_by_transaction(transaction_id):
    rows = execute_query(
        """
        SELECT id, transaction_id, status, trigger_date, auto_send_after,
               generated_at, reviewed_by, reviewed_at, approved_by, approved_at, sent_at,
               sent_disclaimer, pdf_s3_key, pdf_filename, summary, notes, updated_at
        FROM closing_checklists
        WHERE transaction_id = %s
        LIMIT 1
        """,
        (transaction_id,),
        fetch=True,
    ) or []
    if not rows:
        return None
    row = rows[0]
    row["summary"] = _parse_json_field(row.get("summary"), {})
    return row


def fetch_closing_checklist(checklist_id):
    rows = execute_query(
        """
        SELECT id, transaction_id, status, trigger_date, auto_send_after,
               generated_at, reviewed_by, reviewed_at, approved_by, approved_at, sent_at,
               sent_disclaimer, pdf_s3_key, pdf_filename, summary, notes, updated_at
        FROM closing_checklists
        WHERE id = %s
        LIMIT 1
        """,
        (checklist_id,),
        fetch=True,
    ) or []
    if not rows:
        return None
    row = rows[0]
    row["summary"] = _parse_json_field(row.get("summary"), {})
    return row


def fetch_closing_checklist_items(checklist_id):
    rows = execute_query(
        """
        SELECT id, checklist_id, section_title, item_text, source_type, required, sort_order,
               completed, completed_by_role, completed_by_name, completed_at, created_at, updated_at
        FROM closing_checklist_items
        WHERE checklist_id = %s
        ORDER BY section_title ASC, sort_order ASC, id ASC
        """,
        (checklist_id,),
        fetch=True,
    ) or []
    return rows


def fetch_closing_checklist_recipients(checklist_id):
    rows = execute_query(
        """
        SELECT id, checklist_id, party_role, recipient_name, recipient_email, recipient_phone,
               access_token, email_sent_at, sms_sent_at, last_viewed_at, created_at, updated_at
        FROM closing_checklist_recipients
        WHERE checklist_id = %s
        ORDER BY id ASC
        """,
        (checklist_id,),
        fetch=True,
    ) or []
    return rows


def _build_items_grouped_for_render(items):
    grouped = defaultdict(list)
    for item in items:
        grouped[item.get("section_title") or "GENERAL"].append(item)
    ordered = []
    for section in sorted(grouped.keys()):
        ordered.append({"section_title": section, "items": grouped[section]})
    return ordered


def _generate_checklist_pdf(checklist_id, transaction, checklist_row, items):
    if not items:
        return None

    filename = f"closing_checklist_txn_{transaction['id']}_{datetime.now().strftime('%Y%m%d_%H%M')}.pdf"
    temp_path = None
    try:
        with tempfile.NamedTemporaryFile(suffix=".pdf", delete=False) as tmp_file:
            temp_path = tmp_file.name

        doc = SimpleDocTemplate(
            temp_path,
            pagesize=letter,
            leftMargin=36,
            rightMargin=36,
            topMargin=36,
            bottomMargin=36,
            title=f"Closing Checklist #{transaction['id']}",
        )
        styles = getSampleStyleSheet()
        title_style = ParagraphStyle(
            "ChecklistTitle",
            parent=styles["Heading1"],
            fontSize=22,
            textColor=colors.HexColor("#1e3a8a"),
            spaceAfter=16,
        )
        section_style = ParagraphStyle(
            "ChecklistSection",
            parent=styles["Heading3"],
            textColor=colors.HexColor("#0f172a"),
            spaceBefore=12,
            spaceAfter=6,
        )
        body_style = ParagraphStyle(
            "ChecklistBody",
            parent=styles["BodyText"],
            fontSize=10,
            leading=13,
            spaceAfter=4,
        )

        elements = []
        elements.append(Paragraph("Dynamic Closing Checklist", title_style))
        elements.append(Paragraph(_safe_text(transaction.get("property_address")), styles["Heading2"]))
        elements.append(Spacer(1, 0.1 * inch))
        summary_table = Table(
            [
                ["Transaction #", str(transaction["id"])],
                ["Closing Date", _format_date(transaction.get("closing_date"))],
                ["Status", _safe_text(checklist_row.get("status")).replace("_", " ").title()],
                ["Generated", _format_date(checklist_row.get("generated_at"))],
            ],
            colWidths=[1.6 * inch, 4.8 * inch],
        )
        summary_table.setStyle(
            TableStyle(
                [
                    ("BACKGROUND", (0, 0), (0, -1), colors.HexColor("#eff6ff")),
                    ("GRID", (0, 0), (-1, -1), 0.4, colors.HexColor("#93c5fd")),
                    ("FONTSIZE", (0, 0), (-1, -1), 9),
                    ("BOTTOMPADDING", (0, 0), (-1, -1), 8),
                ]
            )
        )
        elements.append(summary_table)
        elements.append(Spacer(1, 0.14 * inch))

        grouped = _build_items_grouped_for_render(items)
        for block in grouped:
            elements.append(Paragraph(block["section_title"], section_style))
            for item in block["items"]:
                marker = "[x]" if item.get("completed") else "[ ]"
                text = f"{marker} {item.get('item_text') or ''}"
                elements.append(Paragraph(text, body_style))
            elements.append(Spacer(1, 0.05 * inch))

        doc.build(elements)
        s3_key = upload_local_file(
            local_path=temp_path,
            transaction_id=transaction["id"],
            document_type="closing_checklist",
            filename=filename,
            content_type="application/pdf",
        )
        return {"s3_key": s3_key, "filename": filename}
    finally:
        if temp_path and os.path.exists(temp_path):
            try:
                os.remove(temp_path)
            except OSError:
                pass


def regenerate_closing_checklist_pdf(checklist_id):
    checklist = fetch_closing_checklist(checklist_id)
    if not checklist:
        return None
    transaction = _fetch_transaction(checklist["transaction_id"])
    if not transaction:
        return None
    items = fetch_closing_checklist_items(checklist_id)
    pdf_result = _generate_checklist_pdf(checklist_id, transaction, checklist, items)
    if not pdf_result or not pdf_result.get("s3_key"):
        return None
    execute_query(
        """
        UPDATE closing_checklists
        SET pdf_s3_key = %s,
            pdf_filename = %s,
            updated_at = CURRENT_TIMESTAMP
        WHERE id = %s
        """,
        (pdf_result["s3_key"], pdf_result["filename"], checklist_id),
    )
    return pdf_result


def generate_closing_checklist(transaction_id, trigger_source="3_day"):
    """
    Generate and persist a dynamic closing checklist for one transaction.
    """
    ensure_closing_checklist_tables()
    transaction = _fetch_transaction(transaction_id)
    if not transaction:
        return {"success": False, "error": "transaction_not_found"}
    if (transaction.get("status") or "").strip().upper() != "ACTIVE":
        return {"success": False, "error": "transaction_not_active"}

    checklist_items = _load_base_checklist_items(transaction)
    next_order = max((item["sort_order"] for item in checklist_items), default=0) + 20

    repair_doc = _find_repair_addendum_document(transaction_id)
    repair_items = extract_repair_items(repair_doc) if repair_doc else []
    if repair_items:
        next_order = _append_section_items(
            checklist_items,
            section_title="VERIFY REPAIRS COMPLETED",
            section_items=repair_items,
            source_type="repair_addendum",
            start_order=next_order,
        )
        next_order += 20

    hoa_analysis = get_hoa_analysis(transaction_id)
    special_assessment = hoa_analysis.get("special_assessment")
    if special_assessment:
        next_order = _append_section_items(
            checklist_items,
            section_title="HOA ITEMS",
            section_items=[f"Verify seller pays ${float(special_assessment):,.2f} HOA assessment."],
            source_type="hoa",
            start_order=next_order,
        )
        next_order += 20

    lender_requirements = get_lender_requirements(transaction.get("lender_name"))
    if lender_requirements:
        next_order = _append_section_items(
            checklist_items,
            section_title="LENDER REQUIREMENTS",
            section_items=lender_requirements,
            source_type="lender",
            start_order=next_order,
        )
        next_order += 20

    special_provisions = extract_special_provisions(transaction.get("contract_s3_key"))
    if special_provisions:
        _append_section_items(
            checklist_items,
            section_title="CUSTOM ITEMS",
            section_items=special_provisions,
            source_type="special_provision",
            start_order=next_order,
        )

    urgent_count = len(
        [item for item in checklist_items if "verify" in (item.get("item_text") or "").lower() or "confirm" in (item.get("item_text") or "").lower()]
    )
    summary = {
        "item_count": len(checklist_items),
        "section_count": len({item.get("section_title") for item in checklist_items}),
        "urgent_item_count": urgent_count,
        "trigger_source": trigger_source,
        "repair_item_count": len(repair_items),
        "has_special_assessment": bool(special_assessment),
    }
    checklist_row = _upsert_checklist_header(
        transaction_id=transaction_id,
        trigger_date=transaction.get("closing_date"),
        summary=summary,
        status="pending_review",
    )
    if not checklist_row:
        return {"success": False, "error": "checklist_upsert_failed"}
    checklist_id = checklist_row["id"]

    _replace_checklist_items(checklist_id, checklist_items)
    recipients = _build_recipient_rows(transaction_id, transaction)
    _replace_checklist_recipients(checklist_id, recipients)

    pdf_result = regenerate_closing_checklist_pdf(checklist_id)
    checklist = fetch_closing_checklist(checklist_id)
    items = fetch_closing_checklist_items(checklist_id)
    recipient_rows = fetch_closing_checklist_recipients(checklist_id)

    execute_query(
        """
        INSERT INTO communications (transaction_id, communication_type, contact_party, contact_name, summary, outcome)
        VALUES (%s, 'note', 'system', 'closing_checklist', %s, %s)
        """,
        (
            transaction_id,
            "Dynamic closing checklist generated",
            (
                f"checklist_id={checklist_id} items={len(items)} recipients={len(recipient_rows)} "
                f"pdf={'yes' if pdf_result else 'no'} trigger={trigger_source}"
            ),
        ),
    )

    return {
        "success": True,
        "checklist": checklist,
        "items": items,
        "recipients": recipient_rows,
    }


def fetch_closing_checklists_for_tc(limit=80):
    ensure_closing_checklist_tables()
    rows = execute_query(
        """
        SELECT c.id, c.transaction_id, c.status, c.trigger_date, c.generated_at,
               c.auto_send_after, c.reviewed_by, c.reviewed_at, c.approved_by, c.approved_at,
               c.sent_at, c.sent_disclaimer, c.summary,
               t.property_address, t.closing_date, t.agent_name, t.status AS transaction_status
        FROM closing_checklists c
        JOIN transactions t ON t.id = c.transaction_id
        ORDER BY
            CASE
                WHEN c.status = 'pending_review' THEN 0
                WHEN c.status = 'approved' THEN 1
                WHEN c.status = 'sent' THEN 2
                WHEN c.status = 'auto_sent' THEN 3
                ELSE 4
            END,
            COALESCE(t.closing_date, CURRENT_DATE + INTERVAL '365 days') ASC,
            c.generated_at DESC
        LIMIT %s
        """,
        (int(limit),),
        fetch=True,
    ) or []
    for row in rows:
        row["summary"] = _parse_json_field(row.get("summary"), {})
    return rows


def add_closing_checklist_item(checklist_id, section_title, item_text, source_type="margaret", required=True):
    rows = execute_query(
        """
        SELECT COALESCE(MAX(sort_order), 0) + 10 AS next_order
        FROM closing_checklist_items
        WHERE checklist_id = %s
        """,
        (checklist_id,),
        fetch=True,
    ) or []
    next_order = int(rows[0]["next_order"]) if rows else 10
    execute_query(
        """
        INSERT INTO closing_checklist_items (
            checklist_id, section_title, item_text, source_type, required, sort_order,
            completed, created_at, updated_at
        )
        VALUES (%s, %s, %s, %s, %s, %s, FALSE, CURRENT_TIMESTAMP, CURRENT_TIMESTAMP)
        """,
        (
            checklist_id,
            (section_title or "CUSTOM").strip()[:200],
            (item_text or "").strip()[:500],
            (source_type or "margaret")[:40],
            bool(required),
            next_order,
        ),
    )
    execute_query(
        """
        UPDATE closing_checklists
        SET updated_at = CURRENT_TIMESTAMP
        WHERE id = %s
        """,
        (checklist_id,),
    )
    return True


def remove_closing_checklist_item(checklist_id, item_id):
    execute_query(
        """
        DELETE FROM closing_checklist_items
        WHERE checklist_id = %s
          AND id = %s
        """,
        (checklist_id, item_id),
    )
    execute_query(
        "UPDATE closing_checklists SET updated_at = CURRENT_TIMESTAMP WHERE id = %s",
        (checklist_id,),
    )
    return True


def toggle_closing_checklist_item(checklist_id, item_id, completed, actor_role="party", actor_name=""):
    execute_query(
        """
        UPDATE closing_checklist_items
        SET completed = %s,
            completed_by_role = CASE WHEN %s THEN %s ELSE NULL END,
            completed_by_name = CASE WHEN %s THEN %s ELSE NULL END,
            completed_at = CASE WHEN %s THEN CURRENT_TIMESTAMP ELSE NULL END,
            updated_at = CURRENT_TIMESTAMP
        WHERE checklist_id = %s
          AND id = %s
        """,
        (
            bool(completed),
            bool(completed),
            (actor_role or "party")[:40],
            bool(completed),
            (actor_name or "")[:120] or None,
            bool(completed),
            checklist_id,
            item_id,
        ),
    )
    execute_query(
        "UPDATE closing_checklists SET updated_at = CURRENT_TIMESTAMP WHERE id = %s",
        (checklist_id,),
    )
    return True


def _party_label(role):
    return (role or "party").replace("_", " ").title()


def _public_checklist_url(access_token):
    base_url = (os.getenv("APP_BASE_URL") or "").strip().rstrip("/")
    if not base_url:
        return ""
    return f"{base_url}/closing-checklist/{access_token}"


def _mini_sms_text(transaction, urgent_items, checklist_url, auto_disclaimer=False):
    property_address = transaction.get("property_address") or f"Transaction #{transaction['id']}"
    urgent_snippet = urgent_items[0] if urgent_items else "Review final closing logistics."
    disclaimer = " Auto-sent pending final review." if auto_disclaimer else ""
    parts = [
        f"Closing checklist for {property_address}.{disclaimer}",
        f"Top priority: {urgent_snippet}",
    ]
    if checklist_url:
        parts.append(f"Checklist: {checklist_url}")
    parts.append("- Maverick TC")
    return " ".join(parts)[:1400]


def _send_checklist_notifications(checklist, transaction, items, recipients, auto_disclaimer=False):
    urgent_items = []
    for item in items:
        text = (item.get("item_text") or "").strip()
        if any(keyword in text.lower() for keyword in ("verify", "confirm", "fund", "wire", "cd")):
            urgent_items.append(text)
    urgent_items = urgent_items[:4]

    sent_email_count = 0
    sent_sms_count = 0
    failed_email_count = 0

    for recipient in recipients:
        party_role = recipient.get("party_role") or "party"
        checklist_url = _public_checklist_url(recipient.get("access_token"))
        pdf_url = get_presigned_url(checklist.get("pdf_s3_key"), expiration=60 * 60 * 24 * 7) if checklist.get("pdf_s3_key") else ""
        context = {
            "subject": f"Dynamic Closing Checklist - {transaction.get('property_address')}",
            "recipient_name": recipient.get("recipient_name") or _party_label(party_role),
            "party_role_label": _party_label(party_role),
            "property_address": transaction.get("property_address"),
            "closing_date_label": _format_date(transaction.get("closing_date")),
            "auto_disclaimer": auto_disclaimer,
            "urgent_items": urgent_items,
            "checklist_url": checklist_url,
            "pdf_url": pdf_url,
            "item_count": len(items),
            "summary": checklist.get("summary") or {},
        }

        email = _normalize_email(recipient.get("recipient_email"))
        if email:
            message_id = send_email(
                to=email,
                template="emails/closing_checklist_update.html",
                data=context,
            )
            if message_id:
                sent_email_count += 1
                execute_query(
                    """
                    UPDATE closing_checklist_recipients
                    SET email_sent_at = CURRENT_TIMESTAMP,
                        updated_at = CURRENT_TIMESTAMP
                    WHERE id = %s
                    """,
                    (recipient["id"],),
                )
                execute_query(
                    """
                    INSERT INTO communications (
                        transaction_id, communication_type, contact_party, contact_name, summary, outcome
                    )
                    VALUES (%s, 'email', %s, %s, %s, %s)
                    """,
                    (
                        transaction["id"],
                        party_role,
                        recipient.get("recipient_name") or _party_label(party_role),
                        "Dynamic closing checklist sent",
                        f"checklist_id={checklist['id']} to={email} message_id={message_id}",
                    ),
                )
            else:
                failed_email_count += 1

        phone = _normalize_phone(recipient.get("recipient_phone"))
        if phone:
            sms_text = _mini_sms_text(transaction, urgent_items, checklist_url, auto_disclaimer=auto_disclaimer)
            sid = send_sms(phone, sms_text)
            if sid:
                sent_sms_count += 1
                execute_query(
                    """
                    UPDATE closing_checklist_recipients
                    SET sms_sent_at = CURRENT_TIMESTAMP,
                        updated_at = CURRENT_TIMESTAMP
                    WHERE id = %s
                    """,
                    (recipient["id"],),
                )
                execute_query(
                    """
                    INSERT INTO communications (
                        transaction_id, communication_type, contact_party, contact_name, summary, outcome
                    )
                    VALUES (%s, 'text', %s, %s, %s, %s)
                    """,
                    (
                        transaction["id"],
                        party_role,
                        recipient.get("recipient_name") or _party_label(party_role),
                        "Closing checklist SMS summary sent",
                        f"checklist_id={checklist['id']} to={phone} sid={sid}",
                    ),
                )

    return {
        "sent_email_count": sent_email_count,
        "sent_sms_count": sent_sms_count,
        "failed_email_count": failed_email_count,
    }


def send_closing_checklist(checklist_id, actor="margaret", auto=False):
    ensure_closing_checklist_tables()
    checklist = fetch_closing_checklist(checklist_id)
    if not checklist:
        return {"success": False, "error": "checklist_not_found"}
    transaction = _fetch_transaction(checklist["transaction_id"])
    if not transaction:
        return {"success": False, "error": "transaction_not_found"}

    items = fetch_closing_checklist_items(checklist_id)
    if not items:
        return {"success": False, "error": "no_items"}
    if not checklist.get("pdf_s3_key"):
        regenerate_closing_checklist_pdf(checklist_id)
        checklist = fetch_closing_checklist(checklist_id) or checklist

    recipients = fetch_closing_checklist_recipients(checklist_id)
    if not recipients:
        return {"success": False, "error": "no_recipients"}

    delivery = _send_checklist_notifications(
        checklist=checklist,
        transaction=transaction,
        items=items,
        recipients=recipients,
        auto_disclaimer=bool(auto),
    )
    next_status = "auto_sent" if auto else "sent"
    execute_query(
        """
        UPDATE closing_checklists
        SET status = %s,
            approved_by = CASE WHEN %s THEN approved_by ELSE %s END,
            approved_at = CASE WHEN %s THEN approved_at ELSE CURRENT_TIMESTAMP END,
            sent_at = CURRENT_TIMESTAMP,
            sent_disclaimer = %s,
            updated_at = CURRENT_TIMESTAMP
        WHERE id = %s
        """,
        (
            next_status,
            bool(auto),
            (actor or "margaret")[:100],
            bool(auto),
            bool(auto),
            checklist_id,
        ),
    )
    execute_query(
        """
        INSERT INTO communications (
            transaction_id, communication_type, contact_party, contact_name, summary, outcome
        )
        VALUES (%s, 'note', 'system', %s, %s, %s)
        """,
        (
            transaction["id"],
            (actor or "system")[:100],
            "Dynamic closing checklist distributed",
            (
                f"checklist_id={checklist_id} auto={auto} "
                f"emails={delivery['sent_email_count']} sms={delivery['sent_sms_count']} "
                f"email_failures={delivery['failed_email_count']}"
            ),
        ),
    )
    return {"success": True, "delivery": delivery, "status": next_status}


def approve_and_send_closing_checklist(checklist_id, approved_by="margaret"):
    checklist = fetch_closing_checklist(checklist_id)
    if not checklist:
        return {"success": False, "error": "checklist_not_found"}
    execute_query(
        """
        UPDATE closing_checklists
        SET status = 'approved',
            reviewed_by = %s,
            reviewed_at = CURRENT_TIMESTAMP,
            approved_by = %s,
            approved_at = CURRENT_TIMESTAMP,
            updated_at = CURRENT_TIMESTAMP
        WHERE id = %s
        """,
        ((approved_by or "margaret")[:100], (approved_by or "margaret")[:100], checklist_id),
    )
    return send_closing_checklist(checklist_id, actor=approved_by, auto=False)


def auto_send_unreviewed_closing_checklists():
    ensure_closing_checklist_tables()
    rows = execute_query(
        """
        SELECT id
        FROM closing_checklists
        WHERE status = 'pending_review'
          AND sent_at IS NULL
          AND auto_send_after <= CURRENT_TIMESTAMP
        ORDER BY auto_send_after ASC, id ASC
        LIMIT 120
        """,
        fetch=True,
    ) or []
    sent = 0
    failed = 0
    for row in rows:
        result = send_closing_checklist(row["id"], actor="system_auto", auto=True)
        if result.get("success"):
            sent += 1
        else:
            failed += 1
    return {"candidate_count": len(rows), "auto_sent": sent, "failed": failed}


def generate_due_closing_checklists(days_before=3):
    ensure_closing_checklist_tables()
    target_date = date.today() + timedelta(days=int(days_before or 3))
    transactions = execute_query(
        """
        SELECT id
        FROM transactions
        WHERE status = 'ACTIVE'
          AND closing_date = %s
        ORDER BY id ASC
        """,
        (target_date,),
        fetch=True,
    ) or []
    generated = 0
    failed = 0
    skipped_existing = 0
    checklist_ids = []
    for row in transactions:
        existing = fetch_closing_checklist_by_transaction(row["id"])
        if existing:
            existing_trigger = existing.get("trigger_date")
            if existing_trigger == target_date:
                # Keep first generated version stable so 24h auto-send clock is not reset hourly.
                skipped_existing += 1
                continue
        result = generate_closing_checklist(row["id"], trigger_source=f"{days_before}_day_trigger")
        if result.get("success"):
            generated += 1
            checklist_ids.append(result["checklist"]["id"])
        else:
            failed += 1
    return {
        "target_date": target_date,
        "candidate_count": len(transactions),
        "generated": generated,
        "skipped_existing": skipped_existing,
        "failed": failed,
        "checklist_ids": checklist_ids,
    }


def run_closing_checklist_automation(days_before=3):
    """Cron-friendly orchestration for 3-day trigger + 24h auto-send."""
    due_result = generate_due_closing_checklists(days_before=days_before)
    auto_send_result = auto_send_unreviewed_closing_checklists()
    return {
        "due_generation": due_result,
        "auto_send": auto_send_result,
    }


def fetch_closing_checklist_by_access_token(access_token):
    ensure_closing_checklist_tables()
    rows = execute_query(
        """
        SELECT r.id AS recipient_id, r.checklist_id, r.party_role, r.recipient_name, r.recipient_email, r.recipient_phone,
               r.access_token, r.email_sent_at, r.sms_sent_at, r.last_viewed_at,
               c.transaction_id, c.status, c.trigger_date, c.generated_at, c.reviewed_at, c.sent_at, c.sent_disclaimer,
               c.pdf_s3_key, c.summary,
               t.property_address, t.closing_date
        FROM closing_checklist_recipients r
        JOIN closing_checklists c ON c.id = r.checklist_id
        JOIN transactions t ON t.id = c.transaction_id
        WHERE r.access_token = %s::uuid
        LIMIT 1
        """,
        (str(access_token),),
        fetch=True,
    ) or []
    if not rows:
        return None
    row = rows[0]
    row["summary"] = _parse_json_field(row.get("summary"), {})
    return row


def mark_closing_checklist_recipient_viewed(recipient_id):
    execute_query(
        """
        UPDATE closing_checklist_recipients
        SET last_viewed_at = CURRENT_TIMESTAMP,
            updated_at = CURRENT_TIMESTAMP
        WHERE id = %s
        """,
        (recipient_id,),
    )

