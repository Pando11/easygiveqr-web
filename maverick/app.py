import os
import re
import csv
import io
import tempfile
from datetime import date, datetime, timedelta
from functools import wraps
from threading import Thread
from typing import Any
from uuid import uuid4

import jwt
import stripe
from dotenv import load_dotenv
from flask import Flask, Response, g, has_request_context, jsonify, redirect, render_template, request, session, url_for
from twilio.twiml.messaging_response import MessagingResponse
from werkzeug.security import check_password_hash
from werkzeug.utils import secure_filename

from config import Config
from utils.db import execute_insert, execute_query
from utils.email import send_html_email
from utils.payments import calculate_payment_breakdown
from utils.s3 import download_file, get_presigned_url, log_document_access, upload_contract, upload_document
from utils.sms import send_payment_link, send_reminder, send_sms, send_timeline_approved

load_dotenv()
stripe.api_key = os.getenv("STRIPE_SECRET_KEY")
stripe_env = (os.getenv("STRIPE_ENV") or "dev").lower()

if stripe_env in {"dev", "test"} and stripe.api_key and stripe.api_key.startswith("sk_live_"):
    print("WARNING: STRIPE_ENV is dev/test but STRIPE_SECRET_KEY looks like a live key.")
if stripe_env == "production" and stripe.api_key and stripe.api_key.startswith("sk_test_"):
    print("WARNING: STRIPE_ENV is production but STRIPE_SECRET_KEY looks like a test key.")

app = Flask(__name__)
app.config.from_object(Config())
app.secret_key = app.config["SECRET_KEY"]
app.config["MAX_CONTENT_LENGTH"] = app.config.get("MAX_CONTENT_LENGTH", 16 * 1024 * 1024)
app.config["SESSION_COOKIE_HTTPONLY"] = True
app.config["SESSION_COOKIE_SAMESITE"] = "Lax"
app.permanent_session_lifetime = timedelta(days=14)

ALLOWED_EXTENSIONS = set(app.config.get("ALLOWED_EXTENSIONS", {"pdf"}))
MAX_FILE_SIZE = app.config["MAX_CONTENT_LENGTH"]
ALLOWED_DOCUMENT_EXTENSIONS = {"pdf", "jpg", "jpeg", "png"}

REQUIRED_DOCUMENT_TYPES = {
    "contract",
    "earnest_receipt",
    "option_receipt",
    "seller_disclosure",
    "inspection_report",
    "appraisal",
    "title_commitment",
    "loan_approval",
    "insurance_binder",
    "settlement_statement",
}

CLIENT_TYPES = {"buyer", "seller"}

CLIENT_UPLOAD_DOCUMENT_TYPES = {
    "signed_amendment",
    "signed_disclosure",
    "signed_addendum",
    "insurance_binder",
    "loan_approval",
    "settlement_statement",
    "other",
}

DOCUMENT_REQUEST_TARGET = {
    "contract": "seller",
    "earnest_receipt": "buyer",
    "option_receipt": "buyer",
    "seller_disclosure": "seller",
    "inspection_report": "buyer",
    "appraisal": "lender",
    "title_commitment": "title",
    "loan_approval": "lender",
    "insurance_binder": "lender",
    "settlement_statement": "title",
}

DEADLINE_BLUEPRINTS = (
    ("effective_date", "Contract effective date", False),
    ("option_fee", "Option fee due", True),
    ("earnest_money", "Earnest money due", True),
    ("seller_disclosure", "Seller disclosure due", False),
    ("survey", "Survey due", False),
    ("option_period_end", "Option period end", True),
    ("hoa_docs", "HOA documents due", False),
    ("buyer_hoa_review", "Buyer HOA review end", False),
    ("title_commitment", "Title commitment due", False),
    ("financing_approval", "Financing approval", True),
    ("buyer_title_objection", "Buyer title objection end", False),
    ("closing", "Closing date", True),
)

TASK_BLUEPRINTS = (
    ("Review contract for completeness", "contract_setup", "effective", 0, "high"),
    ("Verify earnest money receipt", "contract_setup", "effective", 1, "high"),
    ("Verify option fee receipt", "contract_setup", "effective", 1, "high"),
    ("Send introduction email to all parties", "contract_setup", "effective", 2, "medium"),
    ("Call lender to confirm pre-approval", "coordination", "effective", 3, "high"),
    ("Schedule home inspection", "coordination", "effective", 4, "high"),
    ("Order HOA documents if applicable", "coordination", "effective", 5, "medium"),
    ("Request survey from seller", "coordination", "effective", 6, "medium"),
    ("Coordinate appraiser property access", "coordination", "effective", 7, "medium"),
    ("Follow up on seller disclosure", "coordination", "effective", 9, "medium"),
    ("Get inspection report", "documents", "effective", 8, "high"),
    ("Get survey", "documents", "effective", 10, "medium"),
    ("Get HOA documents", "documents", "effective", 11, "medium"),
    ("Verify appraisal completed", "documents", "effective", 14, "medium"),
    ("Get title commitment", "documents", "effective", 18, "medium"),
    ("Get loan approval letter", "documents", "effective", 20, "high"),
    ("Verify all repairs completed", "pre_closing", "effective", 21, "high"),
    ("Get repair receipts", "pre_closing", "effective", 22, "medium"),
    ("Order home warranty if in contract", "pre_closing", "effective", 23, "low"),
    ("Verify insurance binder received by lender", "pre_closing", "effective", 24, "high"),
    ("Get final CD from lender", "pre_closing", "effective", 26, "high"),
    ("Send utilities transfer reminder", "pre_closing", "effective", 27, "low"),
    ("Coordinate final walk-through", "closing", "closing", -2, "high"),
    ("Confirm closing time with all parties", "closing", "closing", -1, "high"),
    ("Verify wire instructions sent to buyer", "closing", "closing", -1, "high"),
    ("Confirm keys available", "closing", "closing", 0, "medium"),
    ("Verify all closing documents ready", "closing", "closing", 0, "high"),
    ("Get final settlement statement", "post_closing", "closing", 1, "high"),
    ("Verify commission disbursed", "post_closing", "closing", 2, "high"),
    ("Archive all documents", "post_closing", "closing", 3, "medium"),
)

LENDER_DEADLINE_TYPES = {"financing_approval"}
TITLE_DEADLINE_TYPES = {"title_commitment", "buyer_title_objection", "closing"}

DATE_CAPTURE_PATTERN = (
    r"(\d{1,2}[/-]\d{1,2}[/-]\d{2,4}|"
    r"[A-Za-z]{3,9}\s+\d{1,2},?\s+\d{2,4})"
)
EFFECTIVE_DATE_PATTERNS = (
    rf"effective\s+date\s*[:\-]?\s*{DATE_CAPTURE_PATTERN}",
    rf"date\s+of\s+effective\s*[:\-]?\s*{DATE_CAPTURE_PATTERN}",
)
CLOSING_DATE_PATTERNS = (
    rf"closing\s+date\s*[:\-]?\s*{DATE_CAPTURE_PATTERN}",
    rf"date\s+of\s+closing\s*[:\-]?\s*{DATE_CAPTURE_PATTERN}",
)
BUYER_PATTERNS = (
    r"buyer(?:\(s\))?\s*[:\-]\s*([A-Za-z0-9 ,.&'/-]{3,160})",
    r"buyer(?:\(s\))?\s+name\s*[:\-]\s*([A-Za-z0-9 ,.&'/-]{3,160})",
)
SELLER_PATTERNS = (
    r"seller(?:\(s\))?\s*[:\-]\s*([A-Za-z0-9 ,.&'/-]{3,160})",
    r"seller(?:\(s\))?\s+name\s*[:\-]\s*([A-Za-z0-9 ,.&'/-]{3,160})",
)
PROPERTY_ADDRESS_PATTERNS = (
    r"property\s+address\s*[:\-]\s*([^\n]{8,220})",
    r"address\s+of\s+property\s*[:\-]\s*([^\n]{8,220})",
)
DATE_PARSE_FORMATS = (
    "%m/%d/%Y",
    "%m-%d-%Y",
    "%m/%d/%y",
    "%m-%d-%y",
    "%B %d, %Y",
    "%b %d, %Y",
    "%B %d %Y",
    "%b %d %Y",
)
EMAIL_PATTERN = re.compile(r"^[^\s@]+@[^\s@]+\.[^\s@]+$")


def normalize_address(value):
    """Normalize address strings for lightweight equality checks."""
    value = (value or "").lower()
    value = value.replace("street", "st").replace("avenue", "ave").replace("road", "rd")
    value = value.replace("drive", "dr").replace("lane", "ln").replace("court", "ct")
    return re.sub(r"[^a-z0-9]", "", value)


def addresses_match(first, second):
    """Return True/False for likely address match, or None when unavailable."""
    if not first or not second:
        return None
    normalized_first = normalize_address(first)
    normalized_second = normalize_address(second)
    if not normalized_first or not normalized_second:
        return None
    return normalized_first in normalized_second or normalized_second in normalized_first


def cleanup_name_candidate(raw_value):
    """Sanitize extracted buyer/seller text to remove trailing noise."""
    value = (raw_value or "").strip(" ,.;:-")
    value = re.sub(r"\s{2,}", " ", value)
    value = re.split(r"\s+(?:phone|email|address|date)\s*[:\-]", value, maxsplit=1, flags=re.IGNORECASE)[0]
    return value[:180].strip(" ,.;:-")


def cleanup_address_candidate(raw_value):
    """Sanitize extracted address candidate text."""
    value = (raw_value or "").strip(" ,.;:-")
    value = re.sub(r"\s{2,}", " ", value)
    value = re.split(r"\s+(?:county|lot|block)\b", value, maxsplit=1, flags=re.IGNORECASE)[0]
    return value[:240].strip(" ,.;:-")


def parse_contract_date(raw_value):
    """Parse a date string from OCR text using common contract formats."""
    value = (raw_value or "").strip()
    if not value:
        return None

    value = re.sub(r"(\d)(st|nd|rd|th)\b", r"\1", value, flags=re.IGNORECASE)
    value = re.sub(r"\s+", " ", value).strip()

    for fmt in DATE_PARSE_FORMATS:
        try:
            return datetime.strptime(value, fmt).date()
        except ValueError:
            continue
    return None


def extract_pattern_value(text, patterns, cleanup_func=None):
    """Search OCR text with regex patterns and return first cleaned match."""
    for pattern in patterns:
        match = re.search(pattern, text, flags=re.IGNORECASE)
        if not match:
            continue
        value = (match.group(1) or "").strip()
        if cleanup_func:
            value = cleanup_func(value)
        if value:
            return value
    return ""


def extract_contract_fields_from_text(text):
    """Extract key contract fields from OCR text."""
    lower_text = text.lower()

    extracted_effective = None
    for pattern in EFFECTIVE_DATE_PATTERNS:
        match = re.search(pattern, lower_text, flags=re.IGNORECASE)
        if not match:
            continue
        extracted_effective = parse_contract_date(match.group(1))
        if extracted_effective:
            break

    extracted_closing = None
    for pattern in CLOSING_DATE_PATTERNS:
        match = re.search(pattern, lower_text, flags=re.IGNORECASE)
        if not match:
            continue
        extracted_closing = parse_contract_date(match.group(1))
        if extracted_closing:
            break

    buyer_names = extract_pattern_value(text, BUYER_PATTERNS, cleanup_func=cleanup_name_candidate)
    seller_names = extract_pattern_value(text, SELLER_PATTERNS, cleanup_func=cleanup_name_candidate)
    property_address = extract_pattern_value(
        text,
        PROPERTY_ADDRESS_PATTERNS,
        cleanup_func=cleanup_address_candidate,
    )

    return {
        "effective_date": extracted_effective,
        "closing_date": extracted_closing,
        "buyer_names": buyer_names,
        "seller_names": seller_names,
        "property_address": property_address,
    }


def extract_text_from_contract_pdf(pdf_path, max_pages=3):
    """Run OCR over first N pages of a contract PDF."""
    from pdf2image import convert_from_path
    import pytesseract

    images = convert_from_path(pdf_path, first_page=1, last_page=max_pages)
    page_text = []
    for page_index, image in enumerate(images, start=1):
        text = pytesseract.image_to_string(image) or ""
        page_text.append(f"\n--- PAGE {page_index} ---\n{text}")
    return "\n".join(page_text).strip()


def save_extracted_contract_data(
    transaction_id,
    submitted_property_address,
    extracted_fields=None,
    status="success",
    error_message=None,
    raw_text_excerpt="",
):
    """Insert/update extracted OCR payload for a transaction."""
    ensure_extracted_contract_data_table()
    extracted_fields = extracted_fields or {}
    extracted_property = extracted_fields.get("property_address") or ""
    property_match = addresses_match(extracted_property, submitted_property_address)
    if extracted_property and submitted_property_address and property_match is None:
        property_match = False

    execute_query(
        """
        INSERT INTO extracted_contract_data (
            transaction_id,
            submitted_property_address,
            extracted_effective_date,
            extracted_closing_date,
            extracted_buyer_names,
            extracted_seller_names,
            extracted_property_address,
            property_address_match,
            raw_text_excerpt,
            extraction_status,
            extraction_error,
            confirmed,
            confirmed_effective_date,
            confirmed_closing_date,
            confirmed_buyer_names,
            confirmed_seller_names,
            confirmed_property_address,
            confirmed_at,
            confirmed_by,
            updated_at
        ) VALUES (
            %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s,
            FALSE, NULL, NULL, NULL, NULL, NULL, NULL, NULL, CURRENT_TIMESTAMP
        )
        ON CONFLICT (transaction_id)
        DO UPDATE SET
            submitted_property_address = EXCLUDED.submitted_property_address,
            extracted_effective_date = EXCLUDED.extracted_effective_date,
            extracted_closing_date = EXCLUDED.extracted_closing_date,
            extracted_buyer_names = EXCLUDED.extracted_buyer_names,
            extracted_seller_names = EXCLUDED.extracted_seller_names,
            extracted_property_address = EXCLUDED.extracted_property_address,
            property_address_match = EXCLUDED.property_address_match,
            raw_text_excerpt = EXCLUDED.raw_text_excerpt,
            extraction_status = EXCLUDED.extraction_status,
            extraction_error = EXCLUDED.extraction_error,
            confirmed = FALSE,
            confirmed_effective_date = NULL,
            confirmed_closing_date = NULL,
            confirmed_buyer_names = NULL,
            confirmed_seller_names = NULL,
            confirmed_property_address = NULL,
            confirmed_at = NULL,
            confirmed_by = NULL,
            updated_at = CURRENT_TIMESTAMP
        """,
        (
            transaction_id,
            submitted_property_address or "",
            extracted_fields.get("effective_date"),
            extracted_fields.get("closing_date"),
            extracted_fields.get("buyer_names") or None,
            extracted_fields.get("seller_names") or None,
            extracted_property or None,
            property_match,
            (raw_text_excerpt or "")[:4000] or None,
            status,
            (error_message or "")[:500] or None,
        ),
    )


def run_contract_extraction(transaction_id, s3_key, submitted_property_address):
    """Download uploaded contract from S3, OCR it, and persist extraction output."""
    temp_path = None
    try:
        with tempfile.NamedTemporaryFile(suffix=".pdf", delete=False) as tmp_file:
            temp_path = tmp_file.name

        if not download_file(s3_key, temp_path):
            save_extracted_contract_data(
                transaction_id=transaction_id,
                submitted_property_address=submitted_property_address,
                status="failed",
                error_message="Could not download PDF from S3 for OCR.",
            )
            return

        raw_text = extract_text_from_contract_pdf(temp_path, max_pages=3)
        extracted_fields = extract_contract_fields_from_text(raw_text)
        save_extracted_contract_data(
            transaction_id=transaction_id,
            submitted_property_address=submitted_property_address,
            extracted_fields=extracted_fields,
            status="success",
            error_message=None,
            raw_text_excerpt=raw_text,
        )
    except Exception as exc:
        save_extracted_contract_data(
            transaction_id=transaction_id,
            submitted_property_address=submitted_property_address,
            status="failed",
            error_message=str(exc),
        )
        print(f"Contract OCR extraction error (txn#{transaction_id}): {exc}")
    finally:
        if temp_path and os.path.exists(temp_path):
            try:
                os.remove(temp_path)
            except OSError:
                pass


def run_contract_extraction_async(transaction_id, s3_key, submitted_property_address):
    """Run OCR extraction in a background thread."""

    def _extract():
        try:
            run_contract_extraction(transaction_id, s3_key, submitted_property_address)
        except Exception as exc:
            print(f"Async extraction error (txn#{transaction_id}): {exc}")

    Thread(
        target=_extract,
        daemon=True,
    ).start()


def ensure_extracted_contract_data_table():
    """Ensure extracted_contract_data table exists for OCR workflow."""
    execute_query(
        """
        CREATE TABLE IF NOT EXISTS extracted_contract_data (
            id SERIAL PRIMARY KEY,
            transaction_id INT UNIQUE REFERENCES transactions(id) ON DELETE CASCADE,
            submitted_property_address TEXT,
            extracted_effective_date DATE,
            extracted_closing_date DATE,
            extracted_buyer_names TEXT,
            extracted_seller_names TEXT,
            extracted_property_address TEXT,
            property_address_match BOOLEAN,
            raw_text_excerpt TEXT,
            extraction_status VARCHAR(32) DEFAULT 'pending',
            extraction_error TEXT,
            confirmed BOOLEAN DEFAULT FALSE,
            confirmed_effective_date DATE,
            confirmed_closing_date DATE,
            confirmed_buyer_names TEXT,
            confirmed_seller_names TEXT,
            confirmed_property_address TEXT,
            confirmed_at TIMESTAMP,
            confirmed_by VARCHAR(100),
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
        """
    )
    execute_query(
        """
        CREATE UNIQUE INDEX IF NOT EXISTS idx_extracted_contract_data_transaction
        ON extracted_contract_data(transaction_id)
        """
    )


def normalize_phone(phone_number):
    """Normalize input to E.164-ish +1 format for US numbers."""
    digits = re.sub(r"\D", "", phone_number or "")
    if len(digits) == 10:
        return f"+1{digits}"
    if len(digits) == 11 and digits.startswith("1"):
        return f"+{digits}"
    if phone_number and phone_number.startswith("+"):
        return phone_number
    return f"+{digits}" if digits else ""


def normalize_email(raw_value):
    """Normalize email value for storage and delivery."""
    return (raw_value or "").strip().lower()


def is_email_valid(raw_value):
    """Basic email format validation for notification recipients."""
    email_value = normalize_email(raw_value)
    if not email_value:
        return False
    return bool(EMAIL_PATTERN.match(email_value))


def format_timestamp_label(value):
    """Return timestamp labels for status cards."""
    if not value:
        return ""
    return value.strftime("%b %d, %Y %I:%M %p")


def get_email_notification_status(transaction_id, lender_email, title_email):
    """Build lender/title email status indicators from communications log."""
    rows = execute_query(
        """
        SELECT
            MAX(CASE WHEN summary = 'Lender notification email sent' THEN created_at END) AS lender_sent_at,
            MAX(CASE WHEN summary = 'Title notification email sent' THEN created_at END) AS title_sent_at,
            MAX(CASE WHEN summary = 'Lender notification email failed' THEN created_at END) AS lender_failed_at,
            MAX(CASE WHEN summary = 'Title notification email failed' THEN created_at END) AS title_failed_at
        FROM communications
        WHERE transaction_id = %s
          AND communication_type = 'email'
        """,
        (transaction_id,),
        fetch=True,
    ) or []
    row = rows[0] if rows else {}

    def status_for(recipient_email, sent_at, failed_at):
        if not recipient_email:
            return {
                "state": "missing",
                "label": "No email on file",
                "sent_at_label": "",
            }
        if sent_at:
            return {
                "state": "sent",
                "label": f"Sent {format_timestamp_label(sent_at)}",
                "sent_at_label": format_timestamp_label(sent_at),
            }
        if failed_at:
            return {
                "state": "failed",
                "label": "Failed to send (see communications log)",
                "sent_at_label": "",
            }
        return {
            "state": "pending",
            "label": "Pending send",
            "sent_at_label": "",
        }

    return {
        "lender": status_for(lender_email, row.get("lender_sent_at"), row.get("lender_failed_at")),
        "title": status_for(title_email, row.get("title_sent_at"), row.get("title_failed_at")),
    }


def commission_base_fee(rush_service):
    """Return standard/rush per-phase fee."""
    return 300.0 if rush_service else 200.0


def normalize_referral_credit(value):
    """Clamp referral credit to expected reporting values (0 or 50)."""
    try:
        numeric = float(value or 0)
    except (TypeError, ValueError):
        return 0.0
    return 50.0 if numeric > 0 else 0.0


def ensure_commission_tracking_table():
    """Ensure commission tracking schema exists for revenue reporting."""
    execute_query(
        """
        CREATE TABLE IF NOT EXISTS commission_tracking (
            id SERIAL PRIMARY KEY,
            transaction_id INT UNIQUE REFERENCES transactions(id) ON DELETE CASCADE,
            upfront_fee DECIMAL(10,2) NOT NULL,
            closing_fee DECIMAL(10,2) NOT NULL,
            referral_credit_given DECIMAL(10,2) NOT NULL DEFAULT 0,
            total_revenue DECIMAL(10,2) NOT NULL,
            upfront_paid_date TIMESTAMP,
            closing_paid_date TIMESTAMP,
            month VARCHAR(7) NOT NULL,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
        """
    )
    execute_query(
        """
        CREATE UNIQUE INDEX IF NOT EXISTS idx_commission_tracking_transaction
        ON commission_tracking(transaction_id)
        """
    )
    execute_query(
        """
        CREATE INDEX IF NOT EXISTS idx_commission_tracking_month
        ON commission_tracking(month)
        """
    )


def ensure_document_requests_table():
    """Ensure document request tracking table exists."""
    execute_query(
        """
        CREATE TABLE IF NOT EXISTS document_requests (
            id SERIAL PRIMARY KEY,
            transaction_id INT REFERENCES transactions(id) ON DELETE CASCADE,
            document_type VARCHAR(100) NOT NULL,
            requested_from VARCHAR(20) NOT NULL,
            email_sent_date TIMESTAMP,
            reminder_sent_date TIMESTAMP,
            received_date TIMESTAMP,
            status VARCHAR(20) DEFAULT 'pending',
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
        """
    )
    execute_query(
        """
        CREATE UNIQUE INDEX IF NOT EXISTS idx_document_requests_txn_doc_type
        ON document_requests(transaction_id, document_type)
        """
    )
    execute_query(
        """
        CREATE INDEX IF NOT EXISTS idx_document_requests_status
        ON document_requests(status)
        """
    )


def ensure_client_access_table():
    """Ensure client portal access table exists."""
    execute_query(
        """
        CREATE TABLE IF NOT EXISTS client_access (
            id SERIAL PRIMARY KEY,
            transaction_id INT REFERENCES transactions(id) ON DELETE CASCADE,
            client_type VARCHAR(20) NOT NULL,
            access_token VARCHAR(64) NOT NULL,
            email VARCHAR(255),
            created_date TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            last_accessed TIMESTAMP
        )
        """
    )
    execute_query(
        """
        CREATE UNIQUE INDEX IF NOT EXISTS idx_client_access_token
        ON client_access(access_token)
        """
    )
    execute_query(
        """
        CREATE UNIQUE INDEX IF NOT EXISTS idx_client_access_txn_client_type
        ON client_access(transaction_id, client_type)
        """
    )


def app_base_url():
    """Resolve public app base URL for link generation."""
    configured = (os.getenv("APP_BASE_URL") or "").strip().rstrip("/")
    if configured:
        return configured
    if has_request_context():
        return (request.url_root or "http://localhost:5000").rstrip("/")
    return "http://localhost:5000"


def build_client_portal_url(access_token):
    """Build a full client portal URL for an access token."""
    return f"{app_base_url()}/client/{access_token}"


def upsert_client_access(transaction_id, client_type, email=None):
    """Create/get one portal token row per transaction/client type."""
    normalized_type = (client_type or "").strip().lower()
    if normalized_type not in CLIENT_TYPES:
        return None

    ensure_client_access_table()
    email_value = normalize_email(email)
    if email_value and not is_email_valid(email_value):
        email_value = ""

    rows = execute_query(
        """
        INSERT INTO client_access (
            transaction_id, client_type, access_token, email, created_date
        )
        VALUES (%s, %s, %s, %s, CURRENT_TIMESTAMP)
        ON CONFLICT (transaction_id, client_type)
        DO UPDATE SET
            email = COALESCE(NULLIF(EXCLUDED.email, ''), client_access.email)
        RETURNING id, transaction_id, client_type, access_token, email, created_date, last_accessed
        """,
        (transaction_id, normalized_type, str(uuid4()), email_value),
        fetch=True,
    ) or []
    if not rows:
        return None

    access_row = rows[0]
    access_row["portal_url"] = build_client_portal_url(access_row["access_token"])
    access_row["client_type_label"] = access_row["client_type"].title()
    access_row["created_date_label"] = format_timestamp_label(access_row.get("created_date"))
    access_row["last_accessed_label"] = format_timestamp_label(access_row.get("last_accessed"))
    return access_row


def ensure_client_access_links(transaction_id, buyer_email=None, seller_email=None):
    """Ensure buyer/seller portal links exist and return both rows."""
    links = []
    buyer_row = upsert_client_access(transaction_id, "buyer", buyer_email)
    seller_row = upsert_client_access(transaction_id, "seller", seller_email)
    if buyer_row:
        links.append(buyer_row)
    if seller_row:
        links.append(seller_row)
    return links


def list_client_access_links(transaction_id):
    """Return portal link rows for transaction detail view."""
    ensure_client_access_table()
    rows = execute_query(
        """
        SELECT client_type, access_token, email, created_date, last_accessed
        FROM client_access
        WHERE transaction_id = %s
        ORDER BY client_type ASC
        """,
        (transaction_id,),
        fetch=True,
    ) or []
    for row in rows:
        row["client_type_label"] = (row.get("client_type") or "").title()
        row["portal_url"] = build_client_portal_url(row["access_token"])
        row["created_date_label"] = format_timestamp_label(row.get("created_date"))
        row["last_accessed_label"] = format_timestamp_label(row.get("last_accessed"))
    return rows


def get_client_access_by_token(access_token, touch=True):
    """Resolve client portal token to transaction + client context."""
    ensure_client_access_table()
    rows = execute_query(
        """
        SELECT ca.transaction_id, ca.client_type, ca.access_token, ca.email,
               ca.created_date, ca.last_accessed,
               t.id AS tx_id, t.property_address, t.status, t.effective_date, t.closing_date,
               t.buyer_name, t.buyer_phone, t.seller_name, t.seller_phone,
               t.agent_name, t.agent_email, t.contract_s3_key
        FROM client_access ca
        JOIN transactions t ON t.id = ca.transaction_id
        WHERE ca.access_token = %s
        LIMIT 1
        """,
        (access_token,),
        fetch=True,
    ) or []
    if not rows:
        return None

    access_row = rows[0]
    if touch:
        execute_query(
            """
            UPDATE client_access
            SET last_accessed = CURRENT_TIMESTAMP
            WHERE access_token = %s
            """,
            (access_token,),
        )
        access_row["last_accessed"] = datetime.now()

    access_row["portal_url"] = build_client_portal_url(access_row["access_token"])
    return access_row


def notify_client_portal_links(transaction_id, transaction, access_rows):
    """Send client portal links by SMS/email for available contacts."""
    sent_sms = 0
    sent_email = 0
    for access in access_rows:
        client_type = (access.get("client_type") or "").strip().lower()
        if client_type not in CLIENT_TYPES:
            continue

        client_name = (transaction.get(f"{client_type}_name") or client_type.title()).strip()
        client_phone = normalize_phone(transaction.get(f"{client_type}_phone") or "")
        client_email = normalize_email(access.get("email"))
        portal_url = build_client_portal_url(access["access_token"])
        message = f"Track your transaction: {portal_url}"

        if client_phone:
            send_sms_async(client_phone, message)
            sent_sms += 1
            execute_query(
                """
                INSERT INTO communications (transaction_id, communication_type, contact_party, contact_name, summary, outcome)
                VALUES (%s, 'text', %s, %s, %s, %s)
                """,
                (
                    transaction_id,
                    client_type,
                    client_name,
                    "Client portal link sent",
                    f"to={client_phone} channel=sms",
                ),
            )

        if client_email and is_email_valid(client_email):
            email_subject = f"Maverick Client Portal - {transaction.get('property_address')}"
            html_body = (
                "<p>Hello,</p>"
                f"<p>Your Maverick client portal is ready for <strong>{transaction.get('property_address')}</strong>.</p>"
                f"<p><a href=\"{portal_url}\">Track your transaction: {portal_url}</a></p>"
                "<p>Use this portal to view timeline progress and upload signed documents.</p>"
                "<p>- Maverick TC</p>"
            )
            message_id = send_html_email(
                to_email=client_email,
                subject=email_subject,
                html_body=html_body,
            )
            execute_query(
                """
                INSERT INTO communications (transaction_id, communication_type, contact_party, contact_name, summary, outcome)
                VALUES (%s, 'email', %s, %s, %s, %s)
                """,
                (
                    transaction_id,
                    client_type,
                    client_name,
                    "Client portal link email sent" if message_id else "Client portal link email failed",
                    f"to={client_email} message_id={message_id or 'failed'}",
                ),
            )
            if message_id:
                sent_email += 1

    return {"sent_sms": sent_sms, "sent_email": sent_email}


def document_request_status_label(status_value):
    """Readable status text for document request cards."""
    normalized = (status_value or "").strip().lower()
    if normalized == "received":
        return "Received"
    if normalized == "overdue":
        return "Overdue"
    return "Pending"


def document_type_label(document_type):
    """Readable label for a document type value."""
    return (document_type or "").replace("_", " ").title()


def document_request_target(document_type):
    """Map document type to requested party."""
    return DOCUMENT_REQUEST_TARGET.get(document_type, "buyer")


def document_request_recipient_email(transaction_row, requested_from):
    """Pick the best recipient email by request target."""
    if requested_from == "lender":
        return normalize_email(transaction_row.get("lender_email"))
    if requested_from == "title":
        return normalize_email(transaction_row.get("title_officer_email"))
    return normalize_email(transaction_row.get("agent_email"))


def transaction_has_document(transaction_row, transaction_id, document_type):
    """Return whether a specific document already exists for transaction."""
    if document_type == "contract":
        return bool(transaction_row.get("contract_s3_key"))
    rows = execute_query(
        """
        SELECT id
        FROM documents
        WHERE transaction_id = %s
          AND document_type = %s
        LIMIT 1
        """,
        (transaction_id, document_type),
        fetch=True,
    ) or []
    return bool(rows)


def upsert_document_request_record(transaction_id, document_type, requested_from):
    """Create/update one request row per transaction/document."""
    ensure_document_requests_table()
    rows = execute_query(
        """
        INSERT INTO document_requests (
            transaction_id, document_type, requested_from, status, updated_at
        )
        VALUES (%s, %s, %s, 'pending', CURRENT_TIMESTAMP)
        ON CONFLICT (transaction_id, document_type)
        DO UPDATE SET
            requested_from = EXCLUDED.requested_from,
            status = CASE
                WHEN document_requests.received_date IS NOT NULL THEN 'received'
                ELSE document_requests.status
            END,
            updated_at = CURRENT_TIMESTAMP
        RETURNING id, email_sent_date, reminder_sent_date, received_date, status
        """,
        (transaction_id, document_type, requested_from),
        fetch=True,
    ) or []
    return rows[0] if rows else None


def mark_document_request_email_sent(request_id, is_reminder=False):
    """Update request timestamps after manual email delivery."""
    if is_reminder:
        execute_query(
            """
            UPDATE document_requests
            SET reminder_sent_date = CURRENT_TIMESTAMP,
                status = CASE
                    WHEN received_date IS NOT NULL THEN 'received'
                    WHEN status = 'overdue' THEN 'overdue'
                    ELSE 'pending'
                END,
                updated_at = CURRENT_TIMESTAMP
            WHERE id = %s
            """,
            (request_id,),
        )
    else:
        execute_query(
            """
            UPDATE document_requests
            SET email_sent_date = CASE
                    WHEN email_sent_date IS NULL THEN CURRENT_TIMESTAMP
                    ELSE email_sent_date
                END,
                status = CASE
                    WHEN received_date IS NOT NULL THEN 'received'
                    WHEN status = 'overdue' THEN 'overdue'
                    ELSE 'pending'
                END,
                updated_at = CURRENT_TIMESTAMP
            WHERE id = %s
            """,
            (request_id,),
        )


def send_manual_document_request(transaction_row, document_type):
    """Send an initial request or reminder email for one missing document."""
    requested_from = document_request_target(document_type)
    recipient_email = document_request_recipient_email(transaction_row, requested_from)
    if not recipient_email:
        return {"success": False, "reason": "missing_recipient", "requested_from": requested_from}

    request_row = upsert_document_request_record(transaction_row["id"], document_type, requested_from)
    if not request_row:
        return {"success": False, "reason": "request_row_missing", "requested_from": requested_from}
    if request_row.get("received_date"):
        return {"success": False, "reason": "already_received", "requested_from": requested_from}

    closing_date = transaction_row.get("closing_date")
    days_to_close = (closing_date - date.today()).days if closing_date else None
    template_name = "document_request.html" if not request_row.get("email_sent_date") else "document_reminder.html"
    request_kind = "initial" if template_name == "document_request.html" else "reminder"
    subject = (
        f"Document Request: {document_type_label(document_type)} - {transaction_row.get('property_address')}"
        if request_kind == "initial"
        else f"Reminder: {document_type_label(document_type)} needed - {transaction_row.get('property_address')}"
    )
    html_body = render_template(
        f"emails/{template_name}",
        property_address=transaction_row.get("property_address"),
        document_label=document_type_label(document_type),
        requested_from=requested_from.title(),
        closing_date_label=closing_date.strftime("%b %d, %Y") if closing_date else "TBD",
        days_to_close=days_to_close if days_to_close is not None else "N/A",
        agent_name=transaction_row.get("agent_name") or "Agent",
    )
    message_id = send_html_email(to_email=recipient_email, subject=subject, html_body=html_body)
    if not message_id:
        return {"success": False, "reason": "send_failed", "requested_from": requested_from}

    mark_document_request_email_sent(request_row["id"], is_reminder=request_kind == "reminder")
    return {
        "success": True,
        "kind": request_kind,
        "requested_from": requested_from,
        "recipient_email": recipient_email,
        "message_id": message_id,
    }


def ensure_client_access_table():
    """Ensure client portal access table exists."""
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


def client_portal_base_url():
    """Resolve base URL used in client portal links."""
    configured = (os.getenv("CLIENT_PORTAL_BASE_URL") or os.getenv("APP_BASE_URL") or "").strip()
    if configured:
        return configured.rstrip("/")
    if has_request_context():
        return request.url_root.rstrip("/")
    return "https://maverick.com"


def client_portal_link_for_token(access_token):
    """Build external link for a client access token."""
    return f"{client_portal_base_url()}/client/{access_token}"


def upsert_client_access(transaction_id, client_type, email=None):
    """Create/update one client portal token per role."""
    if client_type not in CLIENT_TYPES:
        raise ValueError("Unsupported client type")

    ensure_client_access_table()
    safe_email = normalize_email(email)
    generated_token = str(uuid4())
    rows = execute_query(
        """
        INSERT INTO client_access (
            transaction_id, client_type, access_token, email, created_date
        )
        VALUES (%s, %s, %s::uuid, %s, CURRENT_TIMESTAMP)
        ON CONFLICT (transaction_id, client_type)
        DO UPDATE SET
            email = CASE
                WHEN COALESCE(EXCLUDED.email, '') <> '' THEN EXCLUDED.email
                ELSE client_access.email
            END
        RETURNING
            id,
            transaction_id,
            client_type,
            access_token::text AS access_token,
            email,
            created_date,
            last_accessed
        """,
        (transaction_id, client_type, generated_token, safe_email or None),
        fetch=True,
    ) or []
    return rows[0] if rows else None


def fetch_client_access_rows(transaction_id):
    """Fetch all client access rows for one transaction."""
    ensure_client_access_table()
    return execute_query(
        """
        SELECT
            id,
            transaction_id,
            client_type,
            access_token::text AS access_token,
            email,
            created_date,
            last_accessed
        FROM client_access
        WHERE transaction_id = %s
        ORDER BY client_type ASC
        """,
        (transaction_id,),
        fetch=True,
    ) or []


def fetch_client_access_by_token(access_token):
    """Resolve one client access row using an access token."""
    ensure_client_access_table()
    rows = execute_query(
        """
        SELECT
            id,
            transaction_id,
            client_type,
            access_token::text AS access_token,
            email,
            created_date,
            last_accessed
        FROM client_access
        WHERE access_token::text = %s
        LIMIT 1
        """,
        ((access_token or "").strip(),),
        fetch=True,
    ) or []
    return rows[0] if rows else None


def mark_client_accessed(access_id):
    """Stamp latest client portal visit/upload time."""
    execute_query(
        """
        UPDATE client_access
        SET last_accessed = CURRENT_TIMESTAMP
        WHERE id = %s
        """,
        (access_id,),
    )


def deliver_client_portal_link(transaction, client_type, link_url, phone_number="", email_address=""):
    """Send portal link via SMS/email and log outcomes."""
    sent_count = 0
    msg = f"Track your transaction: {link_url}"
    party_label = client_type.title()

    normalized_phone = normalize_phone(phone_number or "")
    if normalized_phone:
        send_sms_async(normalized_phone, msg)
        execute_query(
            """
            INSERT INTO communications (transaction_id, communication_type, contact_party, contact_name, summary, outcome)
            VALUES (%s, 'text', %s, %s, %s, %s)
            """,
            (
                transaction["id"],
                client_type,
                party_label,
                f"Client portal link sent by SMS to {party_label}",
                f"phone={normalized_phone}",
            ),
        )
        sent_count += 1

    safe_email = normalize_email(email_address)
    if safe_email and is_email_valid(safe_email):
        html_body = render_template(
            "emails/client_portal_access.html",
            property_address=transaction.get("property_address"),
            client_type=party_label,
            portal_url=link_url,
            closing_date_label=(
                transaction["closing_date"].strftime("%b %d, %Y") if transaction.get("closing_date") else "TBD"
            ),
        )
        message_id = send_html_email(
            to_email=safe_email,
            subject=f"Maverick Client Portal - {transaction.get('property_address')}",
            html_body=html_body,
        )
        execute_query(
            """
            INSERT INTO communications (transaction_id, communication_type, contact_party, contact_name, summary, outcome)
            VALUES (%s, 'email', %s, %s, %s, %s)
            """,
            (
                transaction["id"],
                client_type,
                party_label,
                (
                    f"Client portal link emailed to {party_label}"
                    if message_id
                    else f"Client portal email failed for {party_label}"
                ),
                f"to={safe_email} message_id={message_id or 'failed'}",
            ),
        )
        if message_id:
            sent_count += 1

    return sent_count


def provision_client_portal_access(transaction, buyer_email=None, seller_email=None):
    """Create portal links and send them to buyer/seller contacts."""
    buyer_access = upsert_client_access(transaction["id"], "buyer", buyer_email)
    seller_access = upsert_client_access(transaction["id"], "seller", seller_email)
    if not buyer_access or not seller_access:
        return {
            "success": False,
            "reason": "access_generation_failed",
            "sent_count": 0,
            "links": {},
        }

    buyer_link = client_portal_link_for_token(buyer_access["access_token"])
    seller_link = client_portal_link_for_token(seller_access["access_token"])

    sent_count = 0
    sent_count += deliver_client_portal_link(
        transaction,
        "buyer",
        buyer_link,
        phone_number=transaction.get("buyer_phone"),
        email_address=buyer_access.get("email"),
    )
    sent_count += deliver_client_portal_link(
        transaction,
        "seller",
        seller_link,
        phone_number=transaction.get("seller_phone"),
        email_address=seller_access.get("email"),
    )

    return {
        "success": True,
        "sent_count": sent_count,
        "links": {
            "buyer": buyer_link,
            "seller": seller_link,
        },
        "emails": {
            "buyer": buyer_access.get("email") or "",
            "seller": seller_access.get("email") or "",
        },
    }


def build_client_portal_context(access_token):
    """Build context payload for client portal template rendering."""
    access_row = fetch_client_access_by_token(access_token)
    if not access_row:
        return None

    transaction = get_transaction_or_none(access_row["transaction_id"])
    if not transaction:
        return None

    mark_client_accessed(access_row["id"])

    timeline_rows = execute_query(
        """
        SELECT id, deadline_type, deadline_date, completed
        FROM deadlines
        WHERE transaction_id = %s
        ORDER BY deadline_date ASC, id ASC
        """,
        (transaction["id"],),
        fetch=True,
    ) or []
    completed_count = 0
    for row in timeline_rows:
        row["deadline_label"] = format_date_label(row.get("deadline_date"))
        row["name_label"] = (row.get("deadline_type") or "").replace("_", " ").title()
        row["is_completed"] = bool(row.get("completed"))
        row["is_overdue"] = bool(row.get("deadline_date")) and row["deadline_date"] < date.today() and not row["is_completed"]
        if row["is_completed"]:
            completed_count += 1

    total_count = len(timeline_rows)
    progress_percent = 0
    if total_count > 0:
        progress_percent = int(round((completed_count / total_count) * 100))
    elif (transaction.get("status") or "").upper() == "COMPLETED":
        progress_percent = 100

    documents = execute_query(
        """
        SELECT id, document_type, filename, uploaded_at, s3_key
        FROM documents
        WHERE transaction_id = %s
        ORDER BY uploaded_at DESC, id DESC
        """,
        (transaction["id"],),
        fetch=True,
    ) or []

    if transaction.get("contract_s3_key"):
        documents.insert(
            0,
            {
                "id": 0,
                "document_type": "contract",
                "filename": transaction.get("contract_pdf_url") or "contract.pdf",
                "uploaded_at": transaction.get("created_at"),
                "s3_key": transaction.get("contract_s3_key"),
            },
        )

    uploaded_types = set()
    for doc in documents:
        doc["uploaded_at_label"] = format_timestamp_label(doc.get("uploaded_at"))
        doc["document_label"] = document_type_label(doc.get("document_type"))
        doc["view_url"] = get_presigned_url(doc["s3_key"], expiration=1800) if doc.get("s3_key") else None
        uploaded_types.add((doc.get("document_type") or "").lower())

    checklist = []
    for doc_type in sorted(REQUIRED_DOCUMENT_TYPES):
        checklist.append(
            {
                "document_type": doc_type,
                "document_label": document_type_label(doc_type),
                "received": doc_type in uploaded_types,
            }
        )

    return {
        "access": access_row,
        "transaction": transaction,
        "timeline": timeline_rows,
        "documents": documents,
        "checklist": checklist,
        "progress_percent": progress_percent,
        "completed_deadlines": completed_count,
        "total_deadlines": total_count,
    }


def upsert_commission_tracking(transaction_id, referral_credit_override=None):
    """Create/update commission tracking row from current transaction state."""
    ensure_commission_tracking_table()
    rows = execute_query(
        """
        SELECT id, rush_service, created_at, payment_upfront_date, payment_closing_date
        FROM transactions
        WHERE id = %s
        LIMIT 1
        """,
        (transaction_id,),
        fetch=True,
    ) or []
    if not rows:
        return False

    transaction = rows[0]
    existing_rows = execute_query(
        "SELECT referral_credit_given FROM commission_tracking WHERE transaction_id = %s",
        (transaction_id,),
        fetch=True,
    ) or []
    existing_credit = existing_rows[0]["referral_credit_given"] if existing_rows else 0

    if referral_credit_override is None:
        referral_credit_given = normalize_referral_credit(existing_credit)
    else:
        referral_credit_given = normalize_referral_credit(referral_credit_override)

    upfront_fee = commission_base_fee(bool(transaction.get("rush_service")))
    closing_fee = commission_base_fee(bool(transaction.get("rush_service")))
    total_revenue = round(upfront_fee + closing_fee - referral_credit_given, 2)
    created_at_value = transaction.get("created_at") or datetime.now()
    month_label = created_at_value.strftime("%Y-%m")

    return bool(
        execute_query(
            """
            INSERT INTO commission_tracking (
                transaction_id,
                upfront_fee,
                closing_fee,
                referral_credit_given,
                total_revenue,
                upfront_paid_date,
                closing_paid_date,
                month,
                updated_at
            ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, CURRENT_TIMESTAMP)
            ON CONFLICT (transaction_id)
            DO UPDATE SET
                upfront_fee = EXCLUDED.upfront_fee,
                closing_fee = EXCLUDED.closing_fee,
                referral_credit_given = EXCLUDED.referral_credit_given,
                total_revenue = EXCLUDED.total_revenue,
                upfront_paid_date = EXCLUDED.upfront_paid_date,
                closing_paid_date = EXCLUDED.closing_paid_date,
                month = EXCLUDED.month,
                updated_at = CURRENT_TIMESTAMP
            """,
            (
                transaction_id,
                round(upfront_fee, 2),
                round(closing_fee, 2),
                round(referral_credit_given, 2),
                total_revenue,
                transaction.get("payment_upfront_date"),
                transaction.get("payment_closing_date"),
                month_label,
            ),
        )
    )


def parse_revenue_filters():
    """Parse month/quarter/year filter selections from request args."""
    today = date.today()
    selected_period = (request.args.get("period") or "month").strip().lower()
    if selected_period not in {"month", "quarter", "year"}:
        selected_period = "month"

    month_value = (request.args.get("month") or today.strftime("%Y-%m")).strip()
    if not re.match(r"^\d{4}-\d{2}$", month_value):
        month_value = today.strftime("%Y-%m")

    default_quarter = f"{today.year}-Q{((today.month - 1) // 3) + 1}"
    quarter_value = (request.args.get("quarter") or default_quarter).strip().upper()
    quarter_match = re.match(r"^(\d{4})-Q([1-4])$", quarter_value)
    if not quarter_match:
        quarter_value = default_quarter
        quarter_match = re.match(r"^(\d{4})-Q([1-4])$", quarter_value)

    year_value_raw = (request.args.get("year") or str(today.year)).strip()
    year_value = int(year_value_raw) if re.match(r"^\d{4}$", year_value_raw) else today.year

    if selected_period == "month":
        months = [month_value]
        label = month_value
    elif selected_period == "quarter":
        quarter_year = int(quarter_match.group(1))
        quarter_num = int(quarter_match.group(2))
        start_month = (quarter_num - 1) * 3 + 1
        months = [f"{quarter_year}-{month:02d}" for month in range(start_month, start_month + 3)]
        label = f"{quarter_year} Q{quarter_num}"
    else:
        months = [f"{year_value}-{month:02d}" for month in range(1, 13)]
        label = str(year_value)

    return {
        "period": selected_period,
        "month": month_value,
        "quarter": quarter_value,
        "year": str(year_value),
        "months": months,
        "label": label,
    }


def fetch_commission_rows(months):
    """Fetch commission rows for selected month labels."""
    if not months:
        return []
    placeholders = ", ".join(["%s"] * len(months))
    query = f"""
        SELECT
            ct.transaction_id, ct.month, ct.upfront_fee, ct.closing_fee, ct.referral_credit_given,
            ct.total_revenue, ct.upfront_paid_date, ct.closing_paid_date,
            t.property_address, t.agent_name, t.status
        FROM commission_tracking ct
        JOIN transactions t ON t.id = ct.transaction_id
        WHERE ct.month IN ({placeholders})
          AND t.status <> 'CANCELLED'
        ORDER BY ct.month ASC, ct.transaction_id ASC
    """
    return execute_query(query, tuple(months), fetch=True) or []


def build_revenue_summary(rows, selected_months):
    """Build totals and chart payloads for revenue dashboard."""
    month_buckets = {
        month: {"revenue": 0.0, "pending": 0.0, "referrals": 0.0}
        for month in selected_months
    }

    total_revenue = 0.0
    total_pending = 0.0
    total_referrals = 0.0
    paid_upfront_count = 0
    paid_closing_count = 0
    pending_upfront_count = 0
    pending_closing_count = 0

    formatted_rows = []
    for row in rows:
        upfront_fee = float(row.get("upfront_fee") or 0)
        closing_fee = float(row.get("closing_fee") or 0)
        referral_credit = float(row.get("referral_credit_given") or 0)
        total_value = float(row.get("total_revenue") or 0)
        upfront_due = max(upfront_fee - referral_credit, 0.0)
        closing_due = closing_fee
        upfront_paid = bool(row.get("upfront_paid_date"))
        closing_paid = bool(row.get("closing_paid_date"))
        pending_value = (0.0 if upfront_paid else upfront_due) + (0.0 if closing_paid else closing_due)

        month_key = row.get("month")
        if month_key not in month_buckets:
            month_buckets[month_key] = {"revenue": 0.0, "pending": 0.0, "referrals": 0.0}
        month_buckets[month_key]["revenue"] += total_value
        month_buckets[month_key]["pending"] += pending_value
        month_buckets[month_key]["referrals"] += referral_credit

        total_revenue += total_value
        total_pending += pending_value
        total_referrals += referral_credit
        if upfront_paid:
            paid_upfront_count += 1
        else:
            pending_upfront_count += 1
        if closing_paid:
            paid_closing_count += 1
        else:
            pending_closing_count += 1

        formatted_rows.append(
            {
                "transaction_id": row.get("transaction_id"),
                "month": month_key,
                "property_address": row.get("property_address"),
                "agent_name": row.get("agent_name"),
                "status": row.get("status"),
                "upfront_fee": round(upfront_fee, 2),
                "closing_fee": round(closing_fee, 2),
                "referral_credit_given": round(referral_credit, 2),
                "total_revenue": round(total_value, 2),
                "pending_amount": round(pending_value, 2),
                "upfront_paid_date": row.get("upfront_paid_date"),
                "closing_paid_date": row.get("closing_paid_date"),
            }
        )

    month_labels = list(month_buckets.keys())
    chart_payload = {
        "kpi": {
            "labels": ["Total Revenue", "Payments Pending", "Referral Credits"],
            "series": [
                {
                    "name": "Current Selection",
                    "color": "#1d4ed8",
                    "values": [
                        round(total_revenue, 2),
                        round(total_pending, 2),
                        round(total_referrals, 2),
                    ],
                }
            ],
        },
        "monthly": {
            "labels": month_labels,
            "series": [
                {
                    "name": "Revenue",
                    "color": "#10b981",
                    "values": [round(month_buckets[label]["revenue"], 2) for label in month_labels],
                },
                {
                    "name": "Pending",
                    "color": "#f59e0b",
                    "values": [round(month_buckets[label]["pending"], 2) for label in month_labels],
                },
                {
                    "name": "Referral Credits",
                    "color": "#ef4444",
                    "values": [round(month_buckets[label]["referrals"], 2) for label in month_labels],
                },
            ],
        },
    }

    return {
        "rows": formatted_rows,
        "totals": {
            "total_revenue": round(total_revenue, 2),
            "payments_pending": round(total_pending, 2),
            "referral_credits": round(total_referrals, 2),
            "transaction_count": len(rows),
            "paid_upfront_count": paid_upfront_count,
            "pending_upfront_count": pending_upfront_count,
            "paid_closing_count": paid_closing_count,
            "pending_closing_count": pending_closing_count,
        },
        "chart_payload": chart_payload,
    }


def send_sms_async(to_number, message):
    """Dispatch SMS in a background thread so request responses stay fast."""

    def _send():
        try:
            send_sms(to_number, message)
        except Exception as exc:
            print(f"Async SMS send error: {exc}")

    Thread(target=_send, daemon=True).start()


def allowed_file(filename):
    return "." in filename and filename.rsplit(".", 1)[1].lower() in ALLOWED_EXTENSIONS


def _verify_tc_password(provided_password):
    expected_password = os.getenv("TC_PASSWORD", "")
    if not expected_password:
        return False

    # Allow either plain text or hashed password in env for flexible rollout.
    if expected_password.startswith(("pbkdf2:", "scrypt:")):
        try:
            return check_password_hash(expected_password, provided_password)
        except Exception:
            return False

    return provided_password == expected_password


def login_required(view_func):
    """Minimal session-based auth gate for TC routes."""

    @wraps(view_func)
    def wrapped(*args, **kwargs):
        if not session.get("tc_logged_in"):
            return redirect(url_for("tc_entry"))
        return view_func(*args, **kwargs)

    return wrapped


MOBILE_JWT_ALGORITHM = "HS256"


def parse_mobile_token_hours():
    """Return access-token lifetime in hours for mobile clients."""
    raw_value = (os.getenv("MOBILE_JWT_EXP_HOURS") or "").strip()
    if not raw_value:
        return 12
    try:
        parsed = int(raw_value)
        if parsed <= 0:
            return 12
        return min(parsed, 72)
    except (TypeError, ValueError):
        return 12


def issue_mobile_access_token(username: str):
    """Create a signed JWT bearer token for mobile API usage."""
    issued_at = datetime.utcnow()
    expires_at = issued_at + timedelta(hours=parse_mobile_token_hours())
    payload = {
        "sub": username,
        "scope": "mobile",
        "iat": issued_at,
        "exp": expires_at,
    }
    token = jwt.encode(payload, app.config["SECRET_KEY"], algorithm=MOBILE_JWT_ALGORITHM)
    if isinstance(token, bytes):
        token = token.decode("utf-8")
    return token, expires_at


def mobile_jwt_required(view_func):
    """Protect JSON API routes with bearer token auth."""

    @wraps(view_func)
    def wrapped(*args, **kwargs):
        auth_header = (request.headers.get("Authorization") or "").strip()
        if not auth_header.lower().startswith("bearer "):
            return jsonify({"success": False, "error": "Missing bearer token"}), 401
        token = auth_header.split(" ", 1)[1].strip()
        if not token:
            return jsonify({"success": False, "error": "Missing bearer token"}), 401

        try:
            payload = jwt.decode(token, app.config["SECRET_KEY"], algorithms=[MOBILE_JWT_ALGORITHM])
        except jwt.ExpiredSignatureError:
            return jsonify({"success": False, "error": "Token expired"}), 401
        except jwt.InvalidTokenError:
            return jsonify({"success": False, "error": "Invalid token"}), 401

        g.mobile_username = payload.get("sub") or "mobile-user"
        return view_func(*args, **kwargs)

    return wrapped


def json_date_value(value):
    """Serialize date and datetime values to ISO8601 strings."""
    if isinstance(value, datetime):
        return value.isoformat()
    if isinstance(value, date):
        return value.isoformat()
    return None


def format_time_ago(value):
    """Return a short relative time label for dashboard cards."""
    if not value:
        return "Unknown"

    if isinstance(value, date) and not isinstance(value, datetime):
        value = datetime.combine(value, datetime.min.time())
    if not isinstance(value, datetime):
        return "Unknown"

    now = datetime.now(value.tzinfo) if value.tzinfo else datetime.now()
    delta = now - value

    total_seconds = max(int(delta.total_seconds()), 0)
    if total_seconds < 60:
        return "just now"

    minutes = total_seconds // 60
    if minutes < 60:
        return f"{minutes}m ago"

    hours = minutes // 60
    if hours < 24:
        return f"{hours}h ago"

    days_count = hours // 24
    if days_count < 30:
        return f"{days_count}d ago"

    months = days_count // 30
    return f"{months}mo ago"


def calculate_days_until_closing(closing_date):
    """Return days remaining until closing date."""
    if not closing_date:
        return None
    return (closing_date - date.today()).days


def format_next_deadline(deadline_type, deadline_date):
    """Return formatted next-deadline label for the dashboard."""
    if not deadline_type or not deadline_date:
        return "No upcoming deadline"
    pretty_type = deadline_type.replace("_", " ").title()
    return f"{pretty_type} ({deadline_date.strftime('%b %d')})"


def payment_status_text(upfront_paid, closing_paid):
    """Return compact payment status label."""
    if upfront_paid and closing_paid:
        return "Paid in full"
    if upfront_paid and not closing_paid:
        return "Upfront paid"
    if not upfront_paid and closing_paid:
        return "Closing paid only"
    return "Unpaid"


def format_date_label(value):
    """Return a user-friendly date label."""
    if not value:
        return "Not set"
    return value.strftime("%b %d, %Y")


def parse_required_date(raw_value: str, field_label: str):
    """Parse required YYYY-MM-DD date fields from forms."""
    value = (raw_value or "").strip()
    if not value:
        raise ValueError(f"{field_label} is required.")
    try:
        return datetime.strptime(value, "%Y-%m-%d").date()
    except ValueError as exc:
        raise ValueError(f"{field_label} must be a valid date.") from exc


def parse_optional_date(raw_value: str | None):
    """Parse optional YYYY-MM-DD date values."""
    value = (raw_value or "").strip()
    if not value:
        return None
    try:
        return datetime.strptime(value, "%Y-%m-%d").date()
    except ValueError:
        return None


def parse_bool_value(raw_value, default=False):
    """Convert mixed boolean form/JSON input to bool."""
    if raw_value is None:
        return default
    if isinstance(raw_value, bool):
        return raw_value
    return str(raw_value).strip().lower() in {"1", "true", "yes", "on"}


def parse_optional_int(raw_value):
    """Convert optional input to int or None."""
    if raw_value in (None, ""):
        return None
    try:
        return int(raw_value)
    except (TypeError, ValueError):
        return None


def file_extension(filename):
    """Return lower-cased extension for a filename."""
    if not filename or "." not in filename:
        return ""
    return filename.rsplit(".", 1)[1].lower()


def document_due_status(target_date, is_complete):
    """Return status class for tasks/deadlines."""
    if is_complete:
        return "complete"
    if not target_date:
        return "pending"
    if target_date < date.today():
        return "overdue"
    if target_date == date.today():
        return "today"
    return "pending"


def deadline_contact_party(deadline_type):
    """Infer the best call contact type for a deadline."""
    if deadline_type in LENDER_DEADLINE_TYPES:
        return "lender"
    if deadline_type in TITLE_DEADLINE_TYPES:
        return "title"
    return "agent"


def build_call_script(contact_party, deadline_label, property_address):
    """Return guided call script text for daily checklist."""
    if contact_party == "lender":
        return f"Hi, checking on loan status for {property_address}. Any update on {deadline_label}?"
    if contact_party == "title":
        return f"Checking status of {deadline_label} for {property_address}. Anything needed from us today?"
    return f"Checking on {deadline_label} for {property_address}. Do you need help completing this item?"


def build_deadline_dates(
    effective_date_value,
    earnest_due_date_value,
    option_period_end_value,
    financing_approval_value,
    closing_date_value,
):
    """Build all deadline dates from approval inputs."""
    return {
        "effective_date": effective_date_value,
        "option_fee": effective_date_value + timedelta(days=3),
        "earnest_money": earnest_due_date_value,
        "seller_disclosure": effective_date_value + timedelta(days=7),
        "survey": effective_date_value + timedelta(days=10),
        "option_period_end": option_period_end_value,
        "hoa_docs": effective_date_value + timedelta(days=10),
        "buyer_hoa_review": option_period_end_value + timedelta(days=2),
        "title_commitment": effective_date_value + timedelta(days=20),
        "financing_approval": financing_approval_value,
        "buyer_title_objection": financing_approval_value + timedelta(days=2),
        "closing": closing_date_value,
    }


def create_deadlines(transaction_id, deadline_dates):
    """Create or replace deadlines for a transaction."""
    execute_query("DELETE FROM deadlines WHERE transaction_id = %s", (transaction_id,))

    values_sql = []
    params: list[Any] = []
    for deadline_type, description, is_critical in DEADLINE_BLUEPRINTS:
        deadline_date = deadline_dates.get(deadline_type)
        if not deadline_date:
            continue
        values_sql.append("(%s, %s, %s, %s, %s)")
        params.extend([transaction_id, deadline_type, deadline_date, description, is_critical])

    if not values_sql:
        return True

    insert_query = f"""
    INSERT INTO deadlines (
        transaction_id, deadline_type, deadline_date, description, is_critical
    ) VALUES {", ".join(values_sql)}
    """
    return bool(execute_query(insert_query, tuple(params)))


def create_tasks(transaction_id, effective_date_value, closing_date_value):
    """Create or replace the 30-task checklist for a transaction."""
    execute_query("DELETE FROM tasks WHERE transaction_id = %s", (transaction_id,))

    values_sql = []
    params: list[Any] = []
    for order, (description, category, anchor, offset_days, priority) in enumerate(TASK_BLUEPRINTS, start=1):
        anchor_date = effective_date_value if anchor == "effective" else closing_date_value
        due_date = anchor_date + timedelta(days=offset_days)
        values_sql.append("(%s, %s, %s, %s, %s, %s)")
        params.extend([transaction_id, description, category, due_date, priority, order])

    insert_query = f"""
    INSERT INTO tasks (
        transaction_id, task_description, task_category, due_date, priority, display_order
    ) VALUES {", ".join(values_sql)}
    """
    return bool(execute_query(insert_query, tuple(params)))


def maybe_create_referral(transaction):
    """Create referral credit tracking for referred transactions."""
    referred_by_agent = (transaction.get("referred_by_agent") or "").strip()
    if not referred_by_agent:
        return

    exists = execute_query(
        "SELECT id FROM referrals WHERE referred_transaction_id = %s LIMIT 1",
        (transaction["id"],),
        fetch=True,
    ) or []
    if exists:
        return

    referrer_phone_rows = execute_query(
        """
        SELECT agent_phone
        FROM transactions
        WHERE LOWER(agent_name) = LOWER(%s)
          AND agent_phone IS NOT NULL
          AND agent_phone <> ''
        ORDER BY created_at DESC
        LIMIT 1
        """,
        (referred_by_agent,),
        fetch=True,
    ) or []
    referrer_phone = referrer_phone_rows[0]["agent_phone"] if referrer_phone_rows else None

    execute_query(
        """
        INSERT INTO referrals (
            referrer_agent_name,
            referrer_agent_phone,
            referred_agent_name,
            referred_transaction_id,
            credit_amount
        ) VALUES (%s, %s, %s, %s, %s)
        """,
        (
            referred_by_agent,
            referrer_phone,
            transaction.get("agent_name"),
            transaction["id"],
            50.00,
        ),
    )


def mark_referral_credit_used_if_needed(transaction_id, agent_name):
    """Mark the newest unused referral credit as used on upfront payment."""
    credit_rows = execute_query(
        """
        SELECT id
        FROM referrals
        WHERE referred_agent_name = %s
          AND credit_used = FALSE
        ORDER BY created_at DESC
        LIMIT 1
        """,
        (agent_name,),
        fetch=True,
    ) or []
    if not credit_rows:
        return

    execute_query(
        """
        UPDATE referrals
        SET credit_used = TRUE,
            credit_used_on_transaction_id = %s,
            credit_used_date = %s
        WHERE id = %s
        """,
        (transaction_id, datetime.now(), credit_rows[0]["id"]),
    )


def get_transaction_or_none(transaction_id):
    """Fetch one transaction for TC routes."""
    rows = execute_query(
        """
        SELECT id, agent_name, agent_phone, agent_email, property_address,
               contract_pdf_url, contract_s3_key, status, rush_service, referred_by_agent,
               effective_date, option_fee_due_date, earnest_due_date, seller_disclosure_due_date,
               survey_due_date, option_period_end_date, hoa_docs_due_date, buyer_hoa_review_end_date,
               title_commitment_due_date, financing_approval_date, buyer_title_objection_end_date,
               closing_date, buyer_name, buyer_phone, seller_name, seller_phone,
               lender_name, lender_email, title_company, title_officer_email,
               payment_upfront_paid, payment_upfront_date,
               payment_closing_paid, payment_closing_date, created_at, updated_at
        FROM transactions
        WHERE id = %s
        """,
        (transaction_id,),
        fetch=True,
    ) or []
    return rows[0] if rows else None


def get_extracted_contract_data_or_none(transaction_id):
    """Fetch OCR extraction payload for one transaction."""
    ensure_extracted_contract_data_table()
    rows = execute_query(
        """
        SELECT transaction_id, submitted_property_address,
               extracted_effective_date, extracted_closing_date,
               extracted_buyer_names, extracted_seller_names, extracted_property_address,
               property_address_match, raw_text_excerpt,
               extraction_status, extraction_error,
               confirmed, confirmed_effective_date, confirmed_closing_date,
               confirmed_buyer_names, confirmed_seller_names, confirmed_property_address,
               confirmed_at, confirmed_by, created_at, updated_at
        FROM extracted_contract_data
        WHERE transaction_id = %s
        LIMIT 1
        """,
        (transaction_id,),
        fetch=True,
    ) or []
    return rows[0] if rows else None


def extraction_status_label(status_value):
    """Return display-friendly status text for extraction records."""
    status = (status_value or "").strip().lower()
    if status == "success":
        return "Extracted"
    if status == "failed":
        return "Extraction failed"
    if status == "manual":
        return "Manual entry"
    if status == "pending":
        return "Pending extraction"
    return "Pending extraction"


def extraction_prefill_value(extracted, confirmed_key, extracted_key, fallback=""):
    """Choose confirmed value first, then extracted value, then fallback."""
    if not extracted:
        return fallback
    if extracted.get("confirmed") and extracted.get(confirmed_key) not in (None, ""):
        return extracted.get(confirmed_key)
    if extracted.get(extracted_key) not in (None, ""):
        return extracted.get(extracted_key)
    return fallback


@app.route("/")
def index():
    """Agent upload form."""
    return render_template("upload.html")


@app.route("/health")
def health():
    """Basic health check for Railway and uptime monitors."""
    return jsonify({"status": "ok", "timestamp": datetime.utcnow().isoformat() + "Z"})


@app.route("/tc", methods=["GET"])
def tc_entry():
    """Margaret login page."""
    if session.get("tc_logged_in"):
        return redirect(url_for("tc_dashboard"))
    return render_template("login.html", error=None, username="", remember_me=False)


@app.route("/tc/login", methods=["GET", "POST"])
def tc_login():
    """Handle Margaret login submission."""
    if request.method == "GET":
        return redirect(url_for("tc_entry"))

    if session.get("tc_logged_in"):
        return redirect(url_for("tc_dashboard"))

    username = request.form.get("username", "").strip()
    password = request.form.get("password", "")
    remember_me = request.form.get("remember_me") == "on"
    expected_username = os.getenv("TC_USERNAME", "margaret")

    if username == expected_username and _verify_tc_password(password):
        session.clear()
        session["tc_logged_in"] = True
        session["tc_username"] = username
        session.permanent = remember_me
        return redirect(url_for("tc_dashboard"))

    return (
        render_template(
            "login.html",
            error="Invalid username or password.",
            username=username,
            remember_me=remember_me,
        ),
        401,
    )


@app.route("/tc/logout")
def tc_logout():
    """Clear session and return to login page."""
    session.clear()
    return redirect(url_for("tc_entry"))


@app.route("/api/mobile/login", methods=["POST"])
def mobile_login():
    """Issue JWT access token for the mobile app."""
    payload = request.get_json(silent=True) or {}
    if not isinstance(payload, dict):
        payload = {}
    username = (payload.get("username") or "").strip()
    password = payload.get("password") or ""
    expected_username = os.getenv("TC_USERNAME", "margaret")

    if username != expected_username or not _verify_tc_password(password):
        return jsonify({"success": False, "error": "Invalid username or password"}), 401

    token, expires_at = issue_mobile_access_token(username)
    return jsonify(
        {
            "success": True,
            "access_token": token,
            "token_type": "Bearer",
            "expires_at": expires_at.isoformat() + "Z",
            "username": username,
        }
    )


@app.route("/api/mobile/dashboard", methods=["GET"])
@mobile_jwt_required
def mobile_dashboard():
    """JSON dashboard payload for mobile."""
    needs_review_rows = execute_query(
        """
        SELECT id, property_address, agent_name, agent_phone, created_at,
               rush_service, referred_by_agent
        FROM transactions
        WHERE status = %s
        ORDER BY created_at ASC
        LIMIT %s
        """,
        ("NEEDS_MARGARET_REVIEW", 30),
        fetch=True,
    ) or []

    active_rows = execute_query(
        """
        SELECT t.id, t.property_address, t.agent_name, t.agent_phone, t.closing_date,
               t.payment_upfront_paid, t.payment_closing_paid,
               nd.deadline_type AS next_deadline_type,
               nd.deadline_date AS next_deadline_date
        FROM transactions t
        LEFT JOIN LATERAL (
            SELECT d.deadline_type, d.deadline_date
            FROM deadlines d
            WHERE d.transaction_id = t.id
              AND d.completed = FALSE
              AND d.deadline_date >= CURRENT_DATE
            ORDER BY d.deadline_date ASC
            LIMIT 1
        ) nd ON TRUE
        WHERE t.status = %s
        ORDER BY COALESCE(t.closing_date, nd.deadline_date) ASC NULLS LAST, t.created_at DESC
        LIMIT %s
        """,
        ("ACTIVE", 80),
        fetch=True,
    ) or []

    needs_review = []
    for row in needs_review_rows:
        needs_review.append(
            {
                "id": row["id"],
                "property_address": row.get("property_address") or "",
                "agent_name": row.get("agent_name") or "",
                "agent_phone": row.get("agent_phone") or "",
                "created_at": json_date_value(row.get("created_at")),
                "time_ago_uploaded": format_time_ago(row.get("created_at")),
                "rush_service": bool(row.get("rush_service")),
                "referred_by_agent": bool(row.get("referred_by_agent")),
            }
        )

    active_transactions = []
    for row in active_rows:
        days_until = calculate_days_until_closing(row.get("closing_date"))
        if days_until is None:
            days_until_label = "No closing date"
        elif days_until < 0:
            days_until_label = f"{abs(days_until)} days overdue"
        elif days_until == 0:
            days_until_label = "Closing today"
        elif days_until == 1:
            days_until_label = "1 day until closing"
        else:
            days_until_label = f"{days_until} days until closing"

        active_transactions.append(
            {
                "id": row["id"],
                "property_address": row.get("property_address") or "",
                "agent_name": row.get("agent_name") or "",
                "agent_phone": row.get("agent_phone") or "",
                "closing_date": json_date_value(row.get("closing_date")),
                "days_until_closing": days_until,
                "days_until_label": days_until_label,
                "next_deadline_type": row.get("next_deadline_type"),
                "next_deadline_date": json_date_value(row.get("next_deadline_date")),
                "next_deadline_label": format_next_deadline(
                    row.get("next_deadline_type"),
                    row.get("next_deadline_date"),
                ),
                "payment_summary": payment_status_text(
                    bool(row.get("payment_upfront_paid")),
                    bool(row.get("payment_closing_paid")),
                ),
            }
        )

    return jsonify(
        {
            "success": True,
            "summary": {
                "needs_review_count": len(needs_review),
                "active_count": len(active_transactions),
            },
            "needs_review": needs_review,
            "active_transactions": active_transactions,
        }
    )


@app.route("/api/mobile/daily-checklist", methods=["GET"])
@mobile_jwt_required
def mobile_daily_checklist():
    """Return today's checklist as JSON for mobile."""
    try:
        today = date.today()
        call_window_start = today - timedelta(days=1)
        call_window_end = today + timedelta(days=3)

        calls_to_make = execute_query(
            """
            SELECT d.id, d.deadline_type, d.deadline_date, d.margaret_called_agent,
                   t.id AS transaction_id, t.property_address, t.agent_phone,
                   t.lender_phone, t.title_officer_phone
            FROM deadlines d
            JOIN transactions t ON t.id = d.transaction_id
            WHERE t.status = 'ACTIVE'
              AND d.completed = FALSE
              AND d.is_critical = TRUE
              AND d.deadline_date >= %s
              AND d.deadline_date <= %s
            ORDER BY d.deadline_date ASC
            """,
            (call_window_start, call_window_end),
            fetch=True,
        ) or []

        call_payload = []
        for call_item in calls_to_make:
            contact_type = deadline_contact_party(call_item.get("deadline_type"))
            deadline_label = (call_item.get("deadline_type") or "").replace("_", " ").title()
            if contact_type == "lender":
                contact_phone = call_item.get("lender_phone") or call_item.get("agent_phone")
            elif contact_type == "title":
                contact_phone = call_item.get("title_officer_phone") or call_item.get("agent_phone")
            else:
                contact_phone = call_item.get("agent_phone")

            digits_only_phone = re.sub(r"\D", "", contact_phone or "")
            phone_link = f"tel:{digits_only_phone}" if digits_only_phone else None
            days_away = (call_item["deadline_date"] - today).days if call_item.get("deadline_date") else None

            call_payload.append(
                {
                    "deadline_id": call_item["id"],
                    "transaction_id": call_item.get("transaction_id"),
                    "property_address": call_item.get("property_address") or "",
                    "contact_type": contact_type,
                    "contact_phone": contact_phone or "",
                    "phone_link": phone_link,
                    "deadline_type": call_item.get("deadline_type"),
                    "deadline_label": deadline_label,
                    "deadline_date": json_date_value(call_item.get("deadline_date")),
                    "days_away": days_away,
                    "days_label": "Today" if days_away == 0 else (f"{days_away}d" if days_away is not None else ""),
                    "made": bool(call_item.get("margaret_called_agent")),
                    "call_script": build_call_script(
                        contact_type,
                        deadline_label,
                        call_item.get("property_address") or "this property",
                    ),
                }
            )

        overdue_tasks_rows = execute_query(
            """
            SELECT tk.id, tk.task_description, tk.notes, tk.due_date,
                   t.id AS transaction_id, t.property_address
            FROM tasks tk
            JOIN transactions t ON t.id = tk.transaction_id
            WHERE t.status = 'ACTIVE'
              AND tk.completed = FALSE
              AND COALESCE(tk.status, 'pending') <> 'completed'
              AND tk.due_date < %s
            ORDER BY tk.due_date ASC, tk.display_order ASC NULLS LAST
            """,
            (today,),
            fetch=True,
        ) or []
        due_today_rows = execute_query(
            """
            SELECT tk.id, tk.task_description, tk.notes, tk.due_date,
                   t.id AS transaction_id, t.property_address
            FROM tasks tk
            JOIN transactions t ON t.id = tk.transaction_id
            WHERE t.status = 'ACTIVE'
              AND tk.completed = FALSE
              AND COALESCE(tk.status, 'pending') <> 'completed'
              AND tk.due_date = %s
            ORDER BY tk.display_order ASC NULLS LAST, tk.id ASC
            """,
            (today,),
            fetch=True,
        ) or []

        def _task_payload(task, include_days_overdue=False):
            result = {
                "task_id": task["id"],
                "transaction_id": task.get("transaction_id"),
                "property_address": task.get("property_address") or "",
                "task_description": task.get("task_description") or "",
                "notes": task.get("notes") or "",
                "due_date": json_date_value(task.get("due_date")),
                "due_label": format_date_label(task.get("due_date")),
                "completed": False,
            }
            if include_days_overdue:
                result["days_overdue"] = (today - task["due_date"]).days if task.get("due_date") else 0
            return result

        overdue_tasks = [_task_payload(task, include_days_overdue=True) for task in overdue_tasks_rows]
        due_today_tasks = [_task_payload(task, include_days_overdue=False) for task in due_today_rows]

        reminders_to_send_rows = execute_query(
            """
            SELECT d.id, d.deadline_type, d.deadline_date,
                   t.id AS transaction_id, t.property_address, t.agent_phone
            FROM deadlines d
            JOIN transactions t ON t.id = d.transaction_id
            WHERE t.status = 'ACTIVE'
              AND d.completed = FALSE
              AND (
                    (d.deadline_date = %s AND d.reminder_1d_sent = FALSE)
                 OR (d.deadline_date = %s AND d.reminder_3d_sent = FALSE)
                 OR (d.deadline_date = %s AND d.reminder_7d_sent = FALSE)
                 OR (d.deadline_date = %s AND d.reminder_10d_sent = FALSE)
              )
            ORDER BY d.deadline_date ASC
            """,
            (
                today + timedelta(days=1),
                today + timedelta(days=3),
                today + timedelta(days=7),
                today + timedelta(days=10),
            ),
            fetch=True,
        ) or []

        reminder_payload = []
        for row in reminders_to_send_rows:
            days_until = (row["deadline_date"] - today).days if row.get("deadline_date") else None
            reminder_payload.append(
                {
                    "deadline_id": row["id"],
                    "transaction_id": row.get("transaction_id"),
                    "property_address": row.get("property_address") or "",
                    "agent_phone": row.get("agent_phone") or "",
                    "deadline_type": row.get("deadline_type"),
                    "deadline_label": (row.get("deadline_type") or "").replace("_", " ").title(),
                    "deadline_date": json_date_value(row.get("deadline_date")),
                    "days_until": days_until,
                }
            )

        summary = {
            "total_items": len(overdue_tasks) + len(due_today_tasks) + len(call_payload) + len(reminder_payload),
            "overdue_count": len(overdue_tasks),
            "due_today_count": len(due_today_tasks),
            "calls_count": len(call_payload),
            "reminders_count": len(reminder_payload),
        }

        return jsonify(
            {
                "success": True,
                "current_date_label": today.strftime("%A, %B %d, %Y"),
                "summary": summary,
                "calls_to_make": call_payload,
                "overdue_tasks": overdue_tasks,
                "due_today_tasks": due_today_tasks,
                "reminders_to_send": reminder_payload,
            }
        )
    except Exception as exc:
        print(f"Mobile checklist error: {exc}")
        return jsonify({"success": False, "error": "Unable to load checklist"}), 500


@app.route("/api/mobile/task/<int:task_id>/complete", methods=["POST"])
@mobile_jwt_required
def mobile_complete_task(task_id):
    """Mark one task complete/incomplete from mobile."""
    try:
        payload = request.get_json(silent=True) or {}
        if not isinstance(payload, dict):
            payload = {}
        completed = parse_bool_value(payload.get("completed"), default=True)
        completed_by = getattr(g, "mobile_username", "mobile-user") if completed else None
        status_value = "completed" if completed else "pending"

        rows = execute_query(
            """
            UPDATE tasks
            SET completed = %s,
                status = %s,
                completed_at = CASE WHEN %s THEN CURRENT_TIMESTAMP ELSE NULL END,
                completed_by = %s
            WHERE id = %s
            RETURNING id, transaction_id, completed, status, completed_at
            """,
            (completed, status_value, completed, completed_by, task_id),
            fetch=True,
        ) or []
        if not rows:
            return jsonify({"success": False, "error": "Task not found"}), 404

        task_row = rows[0]
        return jsonify(
            {
                "success": True,
                "task_id": task_row["id"],
                "transaction_id": task_row.get("transaction_id"),
                "completed": bool(task_row.get("completed")),
                "status": task_row.get("status"),
                "completed_at": json_date_value(task_row.get("completed_at")),
            }
        )
    except Exception as exc:
        print(f"Mobile task completion error: {exc}")
        return jsonify({"success": False, "error": "Unable to update task"}), 500


@app.route("/api/mobile/transaction/<int:transaction_id>/documents", methods=["GET"])
@mobile_jwt_required
def mobile_transaction_documents(transaction_id):
    """Return transaction documents and secure URLs for mobile viewing."""
    transaction_rows = execute_query(
        "SELECT id, property_address, status FROM transactions WHERE id = %s",
        (transaction_id,),
        fetch=True,
    ) or []
    if not transaction_rows:
        return jsonify({"success": False, "error": "Transaction not found"}), 404
    transaction = transaction_rows[0]

    document_rows = execute_query(
        """
        SELECT id, document_type, filename, status, uploaded_at, s3_key
        FROM documents
        WHERE transaction_id = %s
        ORDER BY uploaded_at DESC, id DESC
        """,
        (transaction_id,),
        fetch=True,
    ) or []

    documents = []
    uploaded_document_types = set()
    for row in document_rows:
        uploaded_document_types.add((row.get("document_type") or "").lower())
        view_url = get_presigned_url(row["s3_key"], expiration=1800)
        download_url = get_presigned_url(
            row["s3_key"],
            expiration=1800,
            download_filename=row.get("filename") or f"document_{row['id']}",
        )
        documents.append(
            {
                "id": row["id"],
                "document_type": row.get("document_type") or "",
                "document_type_label": (row.get("document_type") or "").replace("_", " ").title(),
                "filename": row.get("filename") or "",
                "status": row.get("status") or "received",
                "uploaded_at": json_date_value(row.get("uploaded_at")),
                "view_url": view_url,
                "download_url": download_url,
            }
        )

    missing_required = sorted(REQUIRED_DOCUMENT_TYPES - uploaded_document_types)
    return jsonify(
        {
            "success": True,
            "transaction": {
                "id": transaction["id"],
                "property_address": transaction.get("property_address") or "",
                "status": transaction.get("status") or "",
            },
            "documents": documents,
            "missing_required_documents": missing_required,
        }
    )


@app.route("/api/mobile/call/<int:deadline_id>/complete", methods=["POST"])
@mobile_jwt_required
def mobile_complete_call(deadline_id):
    """Mark a call action complete/incomplete from mobile."""
    try:
        payload = request.get_json(silent=True) or {}
        if not isinstance(payload, dict):
            payload = {}
        call_made = parse_bool_value(payload.get("made"), default=True)
        rows = execute_query(
            """
            UPDATE deadlines
            SET margaret_called_agent = %s,
                margaret_call_date = CASE WHEN %s THEN CURRENT_TIMESTAMP ELSE NULL END
            WHERE id = %s
            RETURNING id, transaction_id, margaret_called_agent, margaret_call_date
            """,
            (call_made, call_made, deadline_id),
            fetch=True,
        ) or []
        if not rows:
            return jsonify({"success": False, "error": "Deadline not found"}), 404
        row = rows[0]
        return jsonify(
            {
                "success": True,
                "deadline_id": row["id"],
                "transaction_id": row.get("transaction_id"),
                "made": bool(row.get("margaret_called_agent")),
                "call_date": json_date_value(row.get("margaret_call_date")),
            }
        )
    except Exception as exc:
        print(f"Mobile call completion error: {exc}")
        return jsonify({"success": False, "error": "Unable to update call status"}), 500


@app.route("/api/mobile/transaction/<int:transaction_id>/communications", methods=["GET"])
@mobile_jwt_required
def mobile_list_communications(transaction_id):
    """List communications for a transaction in descending order."""
    if not get_transaction_or_none(transaction_id):
        return jsonify({"success": False, "error": "Transaction not found"}), 404

    rows = execute_query(
        """
        SELECT id, communication_type, contact_party, contact_name,
               summary, outcome, follow_up_needed, follow_up_date,
               logged_by, created_at
        FROM communications
        WHERE transaction_id = %s
        ORDER BY created_at DESC
        LIMIT 100
        """,
        (transaction_id,),
        fetch=True,
    ) or []

    communications = [
        {
            "id": row["id"],
            "communication_type": row.get("communication_type") or "",
            "contact_party": row.get("contact_party") or "",
            "contact_name": row.get("contact_name") or "",
            "summary": row.get("summary") or "",
            "outcome": row.get("outcome") or "",
            "follow_up_needed": bool(row.get("follow_up_needed")),
            "follow_up_date": json_date_value(row.get("follow_up_date")),
            "logged_by": row.get("logged_by") or "",
            "created_at": json_date_value(row.get("created_at")),
        }
        for row in rows
    ]
    return jsonify({"success": True, "communications": communications})


@app.route("/api/mobile/transaction/<int:transaction_id>/communications", methods=["POST"])
@mobile_jwt_required
def mobile_log_communication(transaction_id):
    """Insert a communication log entry from the mobile app."""
    if not get_transaction_or_none(transaction_id):
        return jsonify({"success": False, "error": "Transaction not found"}), 404

    payload = request.get_json(silent=True) or {}
    if not isinstance(payload, dict):
        payload = {}
    communication_type = (payload.get("communication_type") or "").strip().lower()
    contact_party = (payload.get("contact_party") or "").strip().lower()
    contact_name = (payload.get("contact_name") or "").strip()
    summary = (payload.get("summary") or "").strip()
    outcome = (payload.get("outcome") or "").strip()
    follow_up_date = parse_optional_date(payload.get("follow_up_date"))
    follow_up_needed = bool(follow_up_date)

    if not communication_type:
        return jsonify({"success": False, "error": "Communication type is required"}), 400
    if not contact_party:
        return jsonify({"success": False, "error": "Contact party is required"}), 400
    if not summary:
        return jsonify({"success": False, "error": "Summary is required"}), 400

    rows = execute_query(
        """
        INSERT INTO communications (
            transaction_id, communication_type, contact_party, contact_name,
            summary, outcome, follow_up_needed, follow_up_date, logged_by
        ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)
        RETURNING id, created_at
        """,
        (
            transaction_id,
            communication_type,
            contact_party,
            contact_name or None,
            summary,
            outcome or None,
            follow_up_needed,
            follow_up_date,
            getattr(g, "mobile_username", "mobile-user"),
        ),
        fetch=True,
    ) or []
    if not rows:
        return jsonify({"success": False, "error": "Unable to log communication"}), 500

    return jsonify(
        {
            "success": True,
            "communication_id": rows[0]["id"],
            "transaction_id": transaction_id,
            "created_at": json_date_value(rows[0].get("created_at")),
        }
    )


@app.route("/tc/dashboard")
@login_required
def tc_dashboard():
    """Render Margaret's main dashboard with status-grouped transactions."""
    needs_review = execute_query(
        """
        SELECT id, property_address, agent_name, agent_phone, created_at,
               rush_service, referred_by_agent
        FROM transactions
        WHERE status = %s
        ORDER BY created_at ASC
        LIMIT %s
        """,
        ("NEEDS_MARGARET_REVIEW", 50),
        fetch=True,
    ) or []

    active_transactions = execute_query(
        """
        SELECT t.id, t.property_address, t.agent_name, t.agent_phone, t.closing_date,
               t.payment_upfront_paid, t.payment_closing_paid,
               nd.deadline_type AS next_deadline_type,
               nd.deadline_date AS next_deadline_date
        FROM transactions t
        LEFT JOIN LATERAL (
            SELECT d.deadline_type, d.deadline_date
            FROM deadlines d
            WHERE d.transaction_id = t.id
              AND d.completed = FALSE
              AND d.deadline_date >= CURRENT_DATE
            ORDER BY d.deadline_date ASC
            LIMIT 1
        ) nd ON TRUE
        WHERE t.status = %s
        ORDER BY COALESCE(t.closing_date, nd.deadline_date) ASC NULLS LAST, t.created_at DESC
        LIMIT %s
        """,
        ("ACTIVE", 100),
        fetch=True,
    ) or []

    completed_transactions = execute_query(
        """
        SELECT id, property_address, agent_name, closing_date, updated_at,
               payment_upfront_paid, payment_closing_paid
        FROM transactions
        WHERE status = %s
        ORDER BY COALESCE(closing_date, updated_at::date) DESC
        LIMIT %s
        """,
        ("COMPLETED", 10),
        fetch=True,
    ) or []

    for transaction in needs_review:
        transaction["time_ago_uploaded"] = format_time_ago(transaction.get("created_at"))
        transaction["has_rush"] = bool(transaction.get("rush_service"))
        transaction["has_referral"] = bool(transaction.get("referred_by_agent"))

    for transaction in active_transactions:
        days_until = calculate_days_until_closing(transaction.get("closing_date"))
        transaction["days_until_closing"] = days_until
        if days_until is None:
            transaction["days_until_label"] = "No closing date"
        elif days_until < 0:
            transaction["days_until_label"] = f"{abs(days_until)} days overdue"
        elif days_until == 0:
            transaction["days_until_label"] = "Closing today"
        elif days_until == 1:
            transaction["days_until_label"] = "1 day until closing"
        else:
            transaction["days_until_label"] = f"{days_until} days until closing"

        transaction["next_deadline_label"] = format_next_deadline(
            transaction.get("next_deadline_type"),
            transaction.get("next_deadline_date"),
        )
        transaction["payment_summary"] = payment_status_text(
            bool(transaction.get("payment_upfront_paid")),
            bool(transaction.get("payment_closing_paid")),
        )

    for transaction in completed_transactions:
        closed_on = transaction.get("closing_date")
        if not closed_on and transaction.get("updated_at"):
            closed_on = transaction["updated_at"].date()

        transaction["closed_date_label"] = closed_on.strftime("%b %d, %Y") if closed_on else "Unknown"
        transaction["payment_summary"] = payment_status_text(
            bool(transaction.get("payment_upfront_paid")),
            bool(transaction.get("payment_closing_paid")),
        )

    tc_name = (session.get("tc_username") or "margaret").capitalize()
    current_date_label = datetime.now().strftime("%A, %B %d, %Y")
    return render_template(
        "tc_dashboard.html",
        tc_name=tc_name,
        current_date_label=current_date_label,
        needs_review=needs_review,
        active_transactions=active_transactions,
        completed_transactions=completed_transactions,
    )


@app.route("/tc/revenue")
@login_required
def tc_revenue():
    """Render commission/revenue dashboard with month/quarter/year filters."""
    ensure_commission_tracking_table()
    filters = parse_revenue_filters()
    rows = fetch_commission_rows(filters["months"])
    revenue_summary = build_revenue_summary(rows, filters["months"])
    export_url = url_for(
        "export_revenue_csv",
        period=filters["period"],
        month=filters["month"],
        quarter=filters["quarter"],
        year=filters["year"],
    )

    return render_template(
        "tc_revenue.html",
        filters=filters,
        totals=revenue_summary["totals"],
        rows=revenue_summary["rows"],
        chart_payload=revenue_summary["chart_payload"],
        export_url=export_url,
    )


@app.route("/tc/revenue/export")
@login_required
def export_revenue_csv():
    """Export filtered revenue rows as CSV."""
    ensure_commission_tracking_table()
    filters = parse_revenue_filters()
    rows = fetch_commission_rows(filters["months"])
    revenue_summary = build_revenue_summary(rows, filters["months"])

    output = io.StringIO()
    writer = csv.writer(output)
    writer.writerow(
        [
            "period",
            "month",
            "transaction_id",
            "property_address",
            "agent_name",
            "status",
            "upfront_fee",
            "closing_fee",
            "referral_credit_given",
            "total_revenue",
            "pending_amount",
            "upfront_paid_date",
            "closing_paid_date",
        ]
    )
    for row in revenue_summary["rows"]:
        writer.writerow(
            [
                filters["label"],
                row["month"],
                row["transaction_id"],
                row["property_address"],
                row["agent_name"],
                row["status"],
                f"{row['upfront_fee']:.2f}",
                f"{row['closing_fee']:.2f}",
                f"{row['referral_credit_given']:.2f}",
                f"{row['total_revenue']:.2f}",
                f"{row['pending_amount']:.2f}",
                row["upfront_paid_date"].isoformat() if row.get("upfront_paid_date") else "",
                row["closing_paid_date"].isoformat() if row.get("closing_paid_date") else "",
            ]
        )

    filename = f"maverick_revenue_{filters['period']}_{filters['label'].replace(' ', '_')}.csv"
    csv_payload = output.getvalue()
    output.close()
    return Response(
        csv_payload,
        mimetype="text/csv",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


@app.route("/tc/tasks")
@login_required
def tc_tasks():
    """Render the full task management workspace."""
    selected_filter = (request.args.get("filter") or "all").strip().lower()
    if selected_filter not in {"all", "pending", "overdue", "completed"}:
        selected_filter = "all"
    transaction_filter = parse_optional_int(request.args.get("transaction_id"))

    try:
        today = date.today()
        upcoming_horizon = today + timedelta(days=7)
        transaction_clause = " AND t.id = %s" if transaction_filter is not None else ""

        overdue_params = [today]
        if transaction_filter is not None:
            overdue_params.append(transaction_filter)
        overdue_tasks = execute_query(
            f"""
            SELECT tk.id, tk.task_description, tk.task_category, tk.notes, tk.due_date,
                   tk.completed, tk.status, t.id AS transaction_id, t.property_address
            FROM tasks tk
            JOIN transactions t ON t.id = tk.transaction_id
            WHERE tk.completed = FALSE
              AND COALESCE(tk.status, 'pending') <> 'completed'
              AND tk.due_date IS NOT NULL
              AND tk.due_date < %s
              AND t.status = 'ACTIVE'
              {transaction_clause}
            ORDER BY tk.due_date ASC, tk.display_order ASC NULLS LAST
            """,
            tuple(overdue_params),
            fetch=True,
        ) or []

        due_today_params = [today]
        if transaction_filter is not None:
            due_today_params.append(transaction_filter)
        due_today_tasks = execute_query(
            f"""
            SELECT tk.id, tk.task_description, tk.task_category, tk.notes, tk.due_date,
                   tk.completed, tk.status, t.id AS transaction_id, t.property_address
            FROM tasks tk
            JOIN transactions t ON t.id = tk.transaction_id
            WHERE tk.completed = FALSE
              AND COALESCE(tk.status, 'pending') <> 'completed'
              AND tk.due_date = %s
              AND t.status = 'ACTIVE'
              {transaction_clause}
            ORDER BY tk.display_order ASC NULLS LAST, tk.id ASC
            """,
            tuple(due_today_params),
            fetch=True,
        ) or []

        upcoming_params = [today, upcoming_horizon]
        if transaction_filter is not None:
            upcoming_params.append(transaction_filter)
        upcoming_tasks = execute_query(
            f"""
            SELECT tk.id, tk.task_description, tk.task_category, tk.notes, tk.due_date,
                   tk.completed, tk.status, t.id AS transaction_id, t.property_address
            FROM tasks tk
            JOIN transactions t ON t.id = tk.transaction_id
            WHERE tk.completed = FALSE
              AND COALESCE(tk.status, 'pending') <> 'completed'
              AND tk.due_date > %s
              AND tk.due_date <= %s
              AND t.status = 'ACTIVE'
              {transaction_clause}
            ORDER BY tk.due_date ASC, tk.display_order ASC NULLS LAST
            """,
            tuple(upcoming_params),
            fetch=True,
        ) or []

        completed_params: list[Any] = []
        if transaction_filter is not None:
            completed_params.append(transaction_filter)
        completed_tasks = execute_query(
            f"""
            SELECT tk.id, tk.task_description, tk.task_category, tk.notes, tk.due_date,
                   tk.completed, tk.status, tk.completed_at, t.id AS transaction_id, t.property_address
            FROM tasks tk
            JOIN transactions t ON t.id = tk.transaction_id
            WHERE (tk.completed = TRUE OR tk.status = 'completed')
              {transaction_clause}
            ORDER BY COALESCE(tk.completed_at, tk.due_date) DESC NULLS LAST
            LIMIT 60
            """,
            tuple(completed_params),
            fetch=True,
        ) or []

        for task in overdue_tasks:
            task["days_overdue"] = (today - task["due_date"]).days if task.get("due_date") else 0
            task["due_label"] = format_date_label(task.get("due_date"))

        for task in due_today_tasks:
            task["due_label"] = format_date_label(task.get("due_date"))

        for task in upcoming_tasks:
            task["days_until"] = (task["due_date"] - today).days if task.get("due_date") else None
            task["due_label"] = format_date_label(task.get("due_date"))

        for task in completed_tasks:
            completed_at = task.get("completed_at")
            task["completed_at_label"] = completed_at.strftime("%b %d, %Y %I:%M %p") if completed_at else ""
            task["due_label"] = format_date_label(task.get("due_date"))

        return render_template(
            "tc_tasks.html",
            selected_filter=selected_filter,
            transaction_filter=transaction_filter,
            overdue_tasks=overdue_tasks,
            due_today_tasks=due_today_tasks,
            upcoming_tasks=upcoming_tasks,
            completed_tasks=completed_tasks,
        )
    except Exception as exc:
        print(f"Task view error: {exc}")
        return "Unable to load tasks right now.", 500


@app.route("/tc/task/<int:task_id>/toggle", methods=["POST"])
@login_required
def toggle_task(task_id):
    """Toggle task completion state."""
    try:
        payload = request.get_json(silent=True) or request.form
        completed = parse_bool_value(payload.get("completed"), default=False)
        completed_by = session.get("tc_username", "margaret") if completed else None
        status_value = "completed" if completed else "pending"

        rows = execute_query(
            """
            UPDATE tasks
            SET completed = %s,
                status = %s,
                completed_at = CASE WHEN %s THEN CURRENT_TIMESTAMP ELSE NULL END,
                completed_by = %s
            WHERE id = %s
            RETURNING id, transaction_id, completed, status
            """,
            (completed, status_value, completed, completed_by, task_id),
            fetch=True,
        ) or []
        if not rows:
            return jsonify({"success": False, "error": "Task not found"}), 404

        return jsonify(
            {
                "success": True,
                "task_id": task_id,
                "completed": bool(rows[0]["completed"]),
                "status": rows[0]["status"],
            }
        )
    except Exception as exc:
        print(f"Task toggle error: {exc}")
        return jsonify({"success": False, "error": "Unable to update task"}), 500


@app.route("/tc/task/<int:task_id>/note", methods=["POST"])
@login_required
def add_task_note(task_id):
    """Append a note to an existing task."""
    try:
        payload = request.get_json(silent=True) or request.form
        note_text = (payload.get("note") or "").strip()
        if not note_text:
            return jsonify({"success": False, "error": "Note cannot be empty"}), 400
        if len(note_text) > 1200:
            return jsonify({"success": False, "error": "Note is too long"}), 400

        timestamp = datetime.now().strftime("%Y-%m-%d %H:%M")
        note_entry = f"[{timestamp}] {note_text}"
        rows = execute_query(
            """
            UPDATE tasks
            SET notes = CASE
                WHEN COALESCE(notes, '') = '' THEN %s
                ELSE notes || E'\n' || %s
            END
            WHERE id = %s
            RETURNING id, notes
            """,
            (note_entry, note_entry, task_id),
            fetch=True,
        ) or []
        if not rows:
            return jsonify({"success": False, "error": "Task not found"}), 404

        return jsonify({"success": True, "task_id": task_id, "notes": rows[0]["notes"]})
    except Exception as exc:
        print(f"Task note error: {exc}")
        return jsonify({"success": False, "error": "Unable to save note"}), 500


@app.route("/tc/call/<int:deadline_id>/toggle", methods=["POST"])
@login_required
def toggle_call_made(deadline_id):
    """Mark whether Margaret completed a required call."""
    try:
        payload = request.get_json(silent=True) or request.form
        call_made = parse_bool_value(payload.get("made"), default=True)
        rows = execute_query(
            """
            UPDATE deadlines
            SET margaret_called_agent = %s,
                margaret_call_date = CASE WHEN %s THEN CURRENT_TIMESTAMP ELSE NULL END
            WHERE id = %s
            RETURNING id, margaret_called_agent
            """,
            (call_made, call_made, deadline_id),
            fetch=True,
        ) or []
        if not rows:
            return jsonify({"success": False, "error": "Deadline not found"}), 404
        return jsonify({"success": True, "deadline_id": deadline_id, "made": bool(rows[0]["margaret_called_agent"])})
    except Exception as exc:
        print(f"Call toggle error: {exc}")
        return jsonify({"success": False, "error": "Unable to update call status"}), 500


@app.route("/tc/daily-checklist")
@app.route("/tc/checklist")
@login_required
def tc_daily_checklist():
    """Render an auto-generated checklist for today's critical work."""
    try:
        today = date.today()
        call_window_start = today - timedelta(days=1)
        call_window_end = today + timedelta(days=3)

        calls_to_make = execute_query(
            """
            SELECT d.id, d.deadline_type, d.deadline_date, d.margaret_called_agent,
                   t.id AS transaction_id, t.property_address, t.agent_phone,
                   t.lender_phone, t.title_officer_phone
            FROM deadlines d
            JOIN transactions t ON t.id = d.transaction_id
            WHERE t.status = 'ACTIVE'
              AND d.completed = FALSE
              AND d.is_critical = TRUE
              AND d.deadline_date >= %s
              AND d.deadline_date <= %s
            ORDER BY d.deadline_date ASC
            """,
            (call_window_start, call_window_end),
            fetch=True,
        ) or []

        for call_item in calls_to_make:
            contact_type = deadline_contact_party(call_item.get("deadline_type"))
            deadline_label = (call_item.get("deadline_type") or "").replace("_", " ").title()
            if contact_type == "lender":
                contact_phone = call_item.get("lender_phone") or call_item.get("agent_phone")
            elif contact_type == "title":
                contact_phone = call_item.get("title_officer_phone") or call_item.get("agent_phone")
            else:
                contact_phone = call_item.get("agent_phone")

            days_away = (call_item["deadline_date"] - today).days if call_item.get("deadline_date") else None
            call_item["days_away"] = days_away
            call_item["days_label"] = "Today" if days_away == 0 else f"{days_away}d"
            call_item["deadline_label"] = deadline_label
            call_item["contact_type"] = contact_type
            call_item["contact_phone"] = contact_phone
            call_item["call_script"] = build_call_script(
                contact_type,
                deadline_label,
                call_item.get("property_address") or "this property",
            )

        overdue_tasks = execute_query(
            """
            SELECT tk.id, tk.task_description, tk.notes, tk.due_date,
                   t.id AS transaction_id, t.property_address
            FROM tasks tk
            JOIN transactions t ON t.id = tk.transaction_id
            WHERE t.status = 'ACTIVE'
              AND tk.completed = FALSE
              AND COALESCE(tk.status, 'pending') <> 'completed'
              AND tk.due_date < %s
            ORDER BY tk.due_date ASC, tk.display_order ASC NULLS LAST
            """,
            (today,),
            fetch=True,
        ) or []
        for task in overdue_tasks:
            task["days_overdue"] = (today - task["due_date"]).days if task.get("due_date") else 0

        due_today_tasks = execute_query(
            """
            SELECT tk.id, tk.task_description, tk.notes, tk.due_date,
                   t.id AS transaction_id, t.property_address
            FROM tasks tk
            JOIN transactions t ON t.id = tk.transaction_id
            WHERE t.status = 'ACTIVE'
              AND tk.completed = FALSE
              AND COALESCE(tk.status, 'pending') <> 'completed'
              AND tk.due_date = %s
            ORDER BY tk.display_order ASC NULLS LAST, tk.id ASC
            """,
            (today,),
            fetch=True,
        ) or []

        reminders_to_send = execute_query(
            """
            SELECT d.id, d.deadline_type, d.deadline_date,
                   t.id AS transaction_id, t.property_address, t.agent_phone
            FROM deadlines d
            JOIN transactions t ON t.id = d.transaction_id
            WHERE t.status = 'ACTIVE'
              AND d.completed = FALSE
              AND (
                    (d.deadline_date = %s AND d.reminder_1d_sent = FALSE)
                 OR (d.deadline_date = %s AND d.reminder_3d_sent = FALSE)
                 OR (d.deadline_date = %s AND d.reminder_7d_sent = FALSE)
                 OR (d.deadline_date = %s AND d.reminder_10d_sent = FALSE)
              )
            ORDER BY d.deadline_date ASC
            """,
            (
                today + timedelta(days=1),
                today + timedelta(days=3),
                today + timedelta(days=7),
                today + timedelta(days=10),
            ),
            fetch=True,
        ) or []
        for deadline in reminders_to_send:
            deadline["days_until"] = (deadline["deadline_date"] - today).days if deadline.get("deadline_date") else None
            deadline["deadline_label"] = (deadline.get("deadline_type") or "").replace("_", " ").title()

        summary = {
            "total_items": len(overdue_tasks) + len(due_today_tasks) + len(calls_to_make) + len(reminders_to_send),
            "overdue_count": len(overdue_tasks),
            "due_today_count": len(due_today_tasks),
            "calls_count": len(calls_to_make),
        }

        return render_template(
            "tc_daily_checklist.html",
            current_date_label=today.strftime("%A, %B %d, %Y"),
            summary=summary,
            calls_to_make=calls_to_make,
            overdue_tasks=overdue_tasks,
            due_today_tasks=due_today_tasks,
            reminders_to_send=reminders_to_send,
        )
    except Exception as exc:
        print(f"Daily checklist error: {exc}")
        return "Unable to load daily checklist right now.", 500


@app.route("/tc/transaction/<int:transaction_id>")
@login_required
def tc_transaction(transaction_id):
    transaction = get_transaction_or_none(transaction_id)
    if not transaction:
        return "Transaction not found", 404

    status = (transaction.get("status") or "").upper()
    mode = "review" if status == "NEEDS_MARGARET_REVIEW" else "active"
    if status == "COMPLETED":
        mode = "completed"
    if status == "CANCELLED":
        mode = "completed"
    doc_notice = (request.args.get("doc_notice") or "").strip()
    doc_notice_type = (request.args.get("doc_notice_type") or "success").strip().lower()
    if doc_notice_type not in {"success", "warning", "error"}:
        doc_notice_type = "success"

    client_portal_links = {
        "buyer": {"exists": False, "link": "", "email": "", "last_accessed_label": ""},
        "seller": {"exists": False, "link": "", "email": "", "last_accessed_label": ""},
    }
    for access_row in fetch_client_access_rows(transaction_id):
        role = (access_row.get("client_type") or "").lower()
        if role not in client_portal_links:
            continue
        client_portal_links[role] = {
            "exists": True,
            "link": client_portal_link_for_token(access_row.get("access_token")),
            "email": access_row.get("email") or "",
            "last_accessed_label": format_timestamp_label(access_row.get("last_accessed")),
        }

    transaction["has_contract_pdf"] = bool(transaction.get("contract_s3_key"))
    transaction["upload_time_ago"] = format_time_ago(transaction.get("created_at"))
    transaction["uploaded_at_label"] = (
        transaction["created_at"].strftime("%b %d, %Y %I:%M %p") if transaction.get("created_at") else "Unknown"
    )

    extracted_data = get_extracted_contract_data_or_none(transaction_id)
    prefill_effective = extraction_prefill_value(extracted_data, "confirmed_effective_date", "extracted_effective_date")
    prefill_closing = extraction_prefill_value(extracted_data, "confirmed_closing_date", "extracted_closing_date")
    prefill_buyer = extraction_prefill_value(extracted_data, "confirmed_buyer_names", "extracted_buyer_names", "")
    prefill_seller = extraction_prefill_value(extracted_data, "confirmed_seller_names", "extracted_seller_names", "")

    if prefill_effective and not transaction.get("effective_date"):
        transaction["effective_date"] = prefill_effective
    if prefill_closing and not transaction.get("closing_date"):
        transaction["closing_date"] = prefill_closing
    if prefill_buyer and not transaction.get("buyer_name"):
        transaction["buyer_name"] = prefill_buyer
    if prefill_seller and not transaction.get("seller_name"):
        transaction["seller_name"] = prefill_seller

    date_fields = (
        "effective_date",
        "earnest_due_date",
        "option_period_end_date",
        "financing_approval_date",
        "closing_date",
    )
    for field_name in date_fields:
        value = transaction.get(field_name)
        transaction[f"{field_name}_input"] = value.isoformat() if value else ""

    extracted_context = {
        "exists": bool(extracted_data),
        "status": extracted_data.get("extraction_status") if extracted_data else "pending",
        "status_label": extraction_status_label(extracted_data.get("extraction_status") if extracted_data else "pending"),
        "error": extracted_data.get("extraction_error") if extracted_data else None,
        "confirmed": bool(extracted_data.get("confirmed")) if extracted_data else False,
        "confirmed_at_label": (
            extracted_data["confirmed_at"].strftime("%b %d, %Y %I:%M %p")
            if extracted_data and extracted_data.get("confirmed_at")
            else ""
        ),
        "confirmed_by": extracted_data.get("confirmed_by") if extracted_data else "",
        "raw_text_excerpt": extracted_data.get("raw_text_excerpt") if extracted_data else "",
        "agent_property_address": (extracted_data.get("submitted_property_address") if extracted_data else None)
        or transaction.get("property_address")
        or "",
        "property_address_match": extracted_data.get("property_address_match") if extracted_data else None,
        "effective_date_input": (prefill_effective.isoformat() if prefill_effective else ""),
        "closing_date_input": (prefill_closing.isoformat() if prefill_closing else ""),
        "buyer_names_input": prefill_buyer,
        "seller_names_input": prefill_seller,
        "property_address_input": extraction_prefill_value(
            extracted_data,
            "confirmed_property_address",
            "extracted_property_address",
            transaction.get("property_address") or "",
        ),
    }
    email_status = get_email_notification_status(
        transaction_id=transaction_id,
        lender_email=normalize_email(transaction.get("lender_email")),
        title_email=normalize_email(transaction.get("title_officer_email")),
    )

    documents = execute_query(
        """
        SELECT id, document_type, filename, file_size, uploaded_by, uploaded_at
        FROM documents
        WHERE transaction_id = %s
        ORDER BY uploaded_at DESC
        """,
        (transaction_id,),
        fetch=True,
    ) or []
    for document in documents:
        document["uploaded_at_label"] = (
            document["uploaded_at"].strftime("%b %d, %Y %I:%M %p") if document.get("uploaded_at") else "Unknown"
        )

    uploaded_document_types = {doc["document_type"] for doc in documents}
    if transaction.get("contract_s3_key"):
        uploaded_document_types.add("contract")
    missing_document_types = sorted(REQUIRED_DOCUMENT_TYPES - uploaded_document_types)
    missing_document_items = []
    for doc_type in missing_document_types:
        requested_from = document_request_target(doc_type)
        missing_document_items.append(
            {
                "document_type": doc_type,
                "document_label": document_type_label(doc_type),
                "requested_from": requested_from,
                "requested_from_label": requested_from.title(),
            }
        )

    ensure_document_requests_table()
    document_requests = execute_query(
        """
        SELECT id, document_type, requested_from, email_sent_date, reminder_sent_date, received_date, status, updated_at
        FROM document_requests
        WHERE transaction_id = %s
        ORDER BY
            CASE status
                WHEN 'overdue' THEN 0
                WHEN 'pending' THEN 1
                WHEN 'received' THEN 2
                ELSE 3
            END,
            document_type ASC
        """,
        (transaction_id,),
        fetch=True,
    ) or []
    for req in document_requests:
        req["status_label"] = document_request_status_label(req.get("status"))
        req["document_label"] = document_type_label(req.get("document_type"))
        req["requested_from_label"] = (req.get("requested_from") or "").replace("_", " ").title()
        req["email_sent_label"] = format_timestamp_label(req.get("email_sent_date"))
        req["reminder_sent_label"] = format_timestamp_label(req.get("reminder_sent_date"))
        req["received_label"] = format_timestamp_label(req.get("received_date"))

    timeline = execute_query(
        """
        SELECT id, deadline_type, deadline_date, completed
        FROM deadlines
        WHERE transaction_id = %s
        ORDER BY deadline_date ASC, id ASC
        """,
        (transaction_id,),
        fetch=True,
    ) or []
    for deadline in timeline:
        deadline["status_class"] = document_due_status(deadline.get("deadline_date"), bool(deadline.get("completed")))
        deadline["deadline_label"] = format_date_label(deadline.get("deadline_date"))
        deadline["name_label"] = (deadline.get("deadline_type") or "").replace("_", " ").title()

    task_preview = []
    task_total = 0
    if status == "ACTIVE":
        task_preview = execute_query(
            """
            SELECT id, task_description, task_category, due_date, completed, status, priority
            FROM tasks
            WHERE transaction_id = %s
            ORDER BY completed ASC, due_date ASC NULLS LAST, display_order ASC NULLS LAST
            LIMIT 10
            """,
            (transaction_id,),
            fetch=True,
        ) or []
        task_count_rows = execute_query(
            "SELECT COUNT(*) AS total FROM tasks WHERE transaction_id = %s",
            (transaction_id,),
            fetch=True,
        ) or []
        task_total = int(task_count_rows[0]["total"]) if task_count_rows else len(task_preview)

        for task in task_preview:
            is_complete = bool(task.get("completed")) or task.get("status") == "completed"
            task["status_class"] = document_due_status(task.get("due_date"), is_complete)
            task["due_label"] = format_date_label(task.get("due_date"))
            task["category_label"] = (task.get("task_category") or "").replace("_", " ").title()

    communication_limit = 100 if mode == "completed" else 5
    communications = execute_query(
        """
        SELECT id, communication_type, contact_party, contact_name, summary, outcome, created_at
        FROM communications
        WHERE transaction_id = %s
        ORDER BY created_at DESC
        LIMIT %s
        """,
        (transaction_id, communication_limit),
        fetch=True,
    ) or []
    for entry in communications:
        entry["created_at_label"] = entry["created_at"].strftime("%b %d, %Y %I:%M %p") if entry.get("created_at") else ""
        entry["type_label"] = (entry.get("communication_type") or "").replace("_", " ").title()
        entry["party_label"] = (entry.get("contact_party") or "").replace("_", " ").title()

    upfront_breakdown = calculate_payment_breakdown(transaction, "upfront")
    closing_breakdown = calculate_payment_breakdown(transaction, "closing")
    outstanding_amount = 0.0
    if not transaction.get("payment_upfront_paid"):
        outstanding_amount += float(upfront_breakdown["amount"])
    if not transaction.get("payment_closing_paid"):
        outstanding_amount += float(closing_breakdown["amount"])

    payment_context = {
        "upfront_amount": float(upfront_breakdown["amount"]),
        "closing_amount": float(closing_breakdown["amount"]),
        "outstanding_amount": round(outstanding_amount, 2),
    }

    return render_template(
        "tc_transaction_detail.html",
        transaction=transaction,
        mode=mode,
        status=status,
        doc_notice=doc_notice,
        doc_notice_type=doc_notice_type,
        documents=documents,
        missing_document_types=missing_document_types,
        missing_document_items=missing_document_items,
        document_requests=document_requests,
        timeline=timeline,
        task_preview=task_preview,
        task_total=task_total,
        communications=communications,
        payment_context=payment_context,
        extracted_data=extracted_context,
        email_status=email_status,
        client_portal_links=client_portal_links,
    )


@app.route("/tc/view-pdf/<int:transaction_id>")
@login_required
def view_transaction_pdf(transaction_id):
    """View the contract PDF in-browser via a presigned URL."""
    rows = execute_query(
        "SELECT contract_s3_key FROM transactions WHERE id = %s",
        (transaction_id,),
        fetch=True,
    ) or []
    if not rows or not rows[0]["contract_s3_key"]:
        return "Contract PDF not found", 404

    url = get_presigned_url(rows[0]["contract_s3_key"], expiration=1800)
    if not url:
        return "Unable to generate secure PDF link", 500
    return redirect(url)


@app.route("/tc/download-pdf/<int:transaction_id>")
@login_required
def download_transaction_pdf(transaction_id):
    """Download the contract PDF via a presigned URL."""
    rows = execute_query(
        "SELECT contract_s3_key, contract_pdf_url FROM transactions WHERE id = %s",
        (transaction_id,),
        fetch=True,
    ) or []
    if not rows or not rows[0]["contract_s3_key"]:
        return "Contract PDF not found", 404

    filename = rows[0]["contract_pdf_url"] or f"contract_{transaction_id}.pdf"
    url = get_presigned_url(
        rows[0]["contract_s3_key"],
        expiration=1800,
        download_filename=filename,
    )
    if not url:
        return "Unable to generate secure download link", 500
    return redirect(url)


@app.route("/tc/transaction/<int:transaction_id>/confirm-extraction", methods=["POST"])
@login_required
def confirm_extraction(transaction_id):
    """Confirm (and optionally edit) OCR extracted contract fields."""
    transaction = get_transaction_or_none(transaction_id)
    if not transaction:
        return "Transaction not found", 404
    if transaction.get("status") in {"COMPLETED", "CANCELLED"}:
        return "This transaction cannot be modified.", 400

    try:
        confirmed_effective = parse_required_date(
            request.form.get("extracted_effective_date"),
            "Effective date",
        )
        confirmed_closing = parse_required_date(
            request.form.get("extracted_closing_date"),
            "Closing date",
        )
    except ValueError as exc:
        return str(exc), 400

    confirmed_buyer = (request.form.get("extracted_buyer_names") or "").strip()
    confirmed_seller = (request.form.get("extracted_seller_names") or "").strip()
    confirmed_property = (request.form.get("extracted_property_address") or "").strip()

    if not confirmed_buyer:
        return "Buyer name(s) are required for extraction confirmation.", 400
    if not confirmed_seller:
        return "Seller name(s) are required for extraction confirmation.", 400
    if not confirmed_property:
        return "Property address is required for extraction confirmation.", 400
    if confirmed_closing < confirmed_effective:
        return "Closing date cannot be before effective date.", 400

    existing = get_extracted_contract_data_or_none(transaction_id) or {}
    extraction_status = "success" if existing.get("extraction_status") == "success" else "manual"
    submitted_property_address = existing.get("submitted_property_address") or transaction.get("property_address") or ""
    property_match = addresses_match(confirmed_property, submitted_property_address)
    if property_match is None and submitted_property_address:
        property_match = False

    execute_query(
        """
        INSERT INTO extracted_contract_data (
            transaction_id,
            submitted_property_address,
            extracted_effective_date,
            extracted_closing_date,
            extracted_buyer_names,
            extracted_seller_names,
            extracted_property_address,
            property_address_match,
            raw_text_excerpt,
            extraction_status,
            extraction_error,
            confirmed,
            confirmed_effective_date,
            confirmed_closing_date,
            confirmed_buyer_names,
            confirmed_seller_names,
            confirmed_property_address,
            confirmed_at,
            confirmed_by,
            updated_at
        ) VALUES (
            %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, NULL,
            TRUE, %s, %s, %s, %s, %s, CURRENT_TIMESTAMP, %s, CURRENT_TIMESTAMP
        )
        ON CONFLICT (transaction_id)
        DO UPDATE SET
            submitted_property_address = EXCLUDED.submitted_property_address,
            extracted_effective_date = EXCLUDED.extracted_effective_date,
            extracted_closing_date = EXCLUDED.extracted_closing_date,
            extracted_buyer_names = EXCLUDED.extracted_buyer_names,
            extracted_seller_names = EXCLUDED.extracted_seller_names,
            extracted_property_address = EXCLUDED.extracted_property_address,
            property_address_match = EXCLUDED.property_address_match,
            raw_text_excerpt = EXCLUDED.raw_text_excerpt,
            extraction_status = EXCLUDED.extraction_status,
            extraction_error = NULL,
            confirmed = TRUE,
            confirmed_effective_date = EXCLUDED.confirmed_effective_date,
            confirmed_closing_date = EXCLUDED.confirmed_closing_date,
            confirmed_buyer_names = EXCLUDED.confirmed_buyer_names,
            confirmed_seller_names = EXCLUDED.confirmed_seller_names,
            confirmed_property_address = EXCLUDED.confirmed_property_address,
            confirmed_at = CURRENT_TIMESTAMP,
            confirmed_by = EXCLUDED.confirmed_by,
            updated_at = CURRENT_TIMESTAMP
        """,
        (
            transaction_id,
            submitted_property_address,
            existing.get("extracted_effective_date") or confirmed_effective,
            existing.get("extracted_closing_date") or confirmed_closing,
            existing.get("extracted_buyer_names") or confirmed_buyer,
            existing.get("extracted_seller_names") or confirmed_seller,
            existing.get("extracted_property_address") or confirmed_property,
            property_match,
            existing.get("raw_text_excerpt"),
            extraction_status,
            confirmed_effective,
            confirmed_closing,
            confirmed_buyer,
            confirmed_seller,
            confirmed_property,
            session.get("tc_username", "margaret"),
        ),
    )

    execute_query(
        """
        UPDATE transactions
        SET effective_date = %s,
            closing_date = %s,
            buyer_name = %s,
            seller_name = %s,
            updated_at = CURRENT_TIMESTAMP
        WHERE id = %s
        """,
        (confirmed_effective, confirmed_closing, confirmed_buyer, confirmed_seller, transaction_id),
    )

    return redirect(f"{url_for('tc_transaction', transaction_id=transaction_id)}#review-details")


@app.route("/tc/transaction/<int:transaction_id>/approve", methods=["POST"])
@login_required
def approve_transaction(transaction_id):
    """Approve a reviewed transaction and activate full workflow artifacts."""
    transaction = get_transaction_or_none(transaction_id)
    if not transaction:
        return "Transaction not found", 404
    if transaction.get("status") in {"COMPLETED", "CANCELLED"}:
        return "This transaction cannot be approved.", 400

    extraction = get_extracted_contract_data_or_none(transaction_id)
    if not extraction or not extraction.get("confirmed"):
        return "Please confirm extracted contract data before activating this transaction.", 400

    effective_date_value = extraction.get("confirmed_effective_date")
    closing_date_value = extraction.get("confirmed_closing_date")
    buyer_name = (extraction.get("confirmed_buyer_names") or "").strip()
    seller_name = (extraction.get("confirmed_seller_names") or "").strip()

    if not effective_date_value or not closing_date_value:
        return "Confirmed extraction must include effective and closing dates.", 400
    if not buyer_name:
        return "Confirmed extraction must include buyer name(s).", 400
    if not seller_name:
        return "Confirmed extraction must include seller name(s).", 400

    try:
        earnest_due_date_value = parse_required_date(request.form.get("earnest_due_date"), "Earnest money due")
        option_period_end_value = parse_required_date(request.form.get("option_period_end_date"), "Option period end")
        financing_approval_value = parse_required_date(
            request.form.get("financing_approval_date"), "Financing approval"
        )
    except ValueError as exc:
        return str(exc), 400

    buyer_phone = normalize_phone(request.form.get("buyer_phone", "").strip())
    seller_phone = normalize_phone(request.form.get("seller_phone", "").strip())
    buyer_email = normalize_email(request.form.get("buyer_email"))
    seller_email = normalize_email(request.form.get("seller_email"))
    lender_name = request.form.get("lender_name", "").strip()
    lender_email = normalize_email(request.form.get("lender_email"))
    title_company = request.form.get("title_company", "").strip()
    title_company_email = normalize_email(request.form.get("title_company_email"))

    if not title_company:
        return "Title company is required.", 400
    if lender_email and not is_email_valid(lender_email):
        return "Lender email must be a valid address.", 400
    if title_company_email and not is_email_valid(title_company_email):
        return "Title company email must be a valid address.", 400
    if buyer_email and not is_email_valid(buyer_email):
        return "Buyer email must be a valid address.", 400
    if seller_email and not is_email_valid(seller_email):
        return "Seller email must be a valid address.", 400
    if closing_date_value < effective_date_value:
        return "Closing date cannot be before effective date.", 400

    deadline_dates = build_deadline_dates(
        effective_date_value=effective_date_value,
        earnest_due_date_value=earnest_due_date_value,
        option_period_end_value=option_period_end_value,
        financing_approval_value=financing_approval_value,
        closing_date_value=closing_date_value,
    )

    updated = execute_query(
        """
        UPDATE transactions
        SET effective_date = %s,
            option_fee_due_date = %s,
            earnest_due_date = %s,
            seller_disclosure_due_date = %s,
            survey_due_date = %s,
            option_period_end_date = %s,
            hoa_docs_due_date = %s,
            buyer_hoa_review_end_date = %s,
            title_commitment_due_date = %s,
            financing_approval_date = %s,
            buyer_title_objection_end_date = %s,
            closing_date = %s,
            buyer_name = %s,
            buyer_phone = %s,
            seller_name = %s,
            seller_phone = %s,
            lender_name = %s,
            lender_email = %s,
            title_company = %s,
            title_officer_email = %s,
            status = 'ACTIVE',
            updated_at = CURRENT_TIMESTAMP
        WHERE id = %s
        """,
        (
            effective_date_value,
            deadline_dates["option_fee"],
            earnest_due_date_value,
            deadline_dates["seller_disclosure"],
            deadline_dates["survey"],
            option_period_end_value,
            deadline_dates["hoa_docs"],
            deadline_dates["buyer_hoa_review"],
            deadline_dates["title_commitment"],
            financing_approval_value,
            deadline_dates["buyer_title_objection"],
            closing_date_value,
            buyer_name,
            buyer_phone,
            seller_name,
            seller_phone,
            lender_name,
            lender_email or None,
            title_company,
            title_company_email or None,
            transaction_id,
        ),
    )
    if not updated:
        return "Failed to activate transaction.", 500

    upsert_commission_tracking(transaction_id)

    if not create_deadlines(transaction_id, deadline_dates):
        return "Failed to create deadlines.", 500
    if not create_tasks(transaction_id, effective_date_value, closing_date_value):
        return "Failed to create tasks.", 500

    transaction["id"] = transaction_id
    transaction["buyer_phone"] = buyer_phone
    transaction["seller_phone"] = seller_phone
    maybe_create_referral(transaction)

    timeline_dates = {
        "earnest": earnest_due_date_value.strftime("%m/%d/%Y"),
        "option_end": option_period_end_value.strftime("%m/%d/%Y"),
        "financing": financing_approval_value.strftime("%m/%d/%Y"),
        "closing": closing_date_value.strftime("%m/%d/%Y"),
    }
    timeline_sid = send_timeline_approved(
        transaction.get("agent_phone"),
        transaction.get("property_address"),
        timeline_dates,
    )
    execute_query(
        """
        INSERT INTO communications (transaction_id, communication_type, contact_party, contact_name, summary, outcome)
        VALUES (%s, 'text', 'agent', 'system', %s, %s)
        """,
        (
            transaction_id,
            "Timeline approved and sent to agent",
            f"message_sid={timeline_sid or 'failed'}",
        ),
    )

    email_context = {
        "transaction_id": transaction_id,
        "property_address": transaction.get("property_address"),
        "agent_name": transaction.get("agent_name"),
        "buyer_name": buyer_name,
        "seller_name": seller_name,
        "lender_name": lender_name or "Lender",
        "title_company": title_company,
        "effective_date": effective_date_value.strftime("%b %d, %Y"),
        "earnest_due_date": earnest_due_date_value.strftime("%b %d, %Y"),
        "option_period_end_date": option_period_end_value.strftime("%b %d, %Y"),
        "financing_approval_date": financing_approval_value.strftime("%b %d, %Y"),
        "closing_date": closing_date_value.strftime("%b %d, %Y"),
    }
    if lender_email:
        lender_html = render_template("emails/lender_notification.html", data=email_context)
        lender_message_id = send_html_email(
            to_email=lender_email,
            subject=f"Maverick TC - Lender Coordination - {transaction.get('property_address')}",
            html_body=lender_html,
        )
        execute_query(
            """
            INSERT INTO communications (transaction_id, communication_type, contact_party, contact_name, summary, outcome)
            VALUES (%s, 'email', 'lender', %s, %s, %s)
            """,
            (
                transaction_id,
                lender_name or "Lender",
                "Lender notification email sent" if lender_message_id else "Lender notification email failed",
                f"to={lender_email} message_id={lender_message_id or 'failed'}",
            ),
        )

    if title_company_email:
        title_html = render_template("emails/title_notification.html", data=email_context)
        title_message_id = send_html_email(
            to_email=title_company_email,
            subject=f"Maverick TC - Title Coordination - {transaction.get('property_address')}",
            html_body=title_html,
        )
        execute_query(
            """
            INSERT INTO communications (transaction_id, communication_type, contact_party, contact_name, summary, outcome)
            VALUES (%s, 'email', 'title_company', %s, %s, %s)
            """,
            (
                transaction_id,
                title_company,
                "Title notification email sent" if title_message_id else "Title notification email failed",
                f"to={title_company_email} message_id={title_message_id or 'failed'}",
            ),
        )

    if not transaction.get("payment_upfront_paid"):
        upfront_breakdown = calculate_payment_breakdown(transaction, "upfront")
        payment_sid = send_payment_link(
            transaction.get("agent_phone"),
            transaction_id,
            round(float(upfront_breakdown["amount"]), 2),
            "upfront",
        )
        execute_query(
            """
            INSERT INTO communications (transaction_id, communication_type, contact_party, contact_name, summary, outcome)
            VALUES (%s, 'text', 'agent', 'system', %s, %s)
            """,
            (
                transaction_id,
                "Upfront payment link sent",
                f"message_sid={payment_sid or 'failed'} amount={upfront_breakdown['amount']}",
            ),
        )

    provision_client_portal_access(
        transaction,
        buyer_email=buyer_email or None,
        seller_email=seller_email or None,
    )

    return redirect(url_for("tc_dashboard"))


@app.route("/tc/transaction/<int:transaction_id>/upload-document", methods=["POST"])
@login_required
def upload_transaction_document(transaction_id):
    """Upload a transaction document to S3 and track it in DB."""
    if not get_transaction_or_none(transaction_id):
        return "Transaction not found", 404

    if "document_file" not in request.files:
        return "No file uploaded.", 400
    file = request.files["document_file"]
    if not file or not file.filename:
        return "Please select a document file.", 400

    safe_filename = secure_filename(file.filename)
    extension = file_extension(safe_filename)
    if extension not in ALLOWED_DOCUMENT_EXTENSIONS:
        return "Invalid file type. Allowed: PDF, JPG, JPEG, PNG.", 400

    file.seek(0, os.SEEK_END)
    file_size = file.tell()
    if file_size > MAX_FILE_SIZE:
        return "File exceeds 16MB upload limit.", 400
    file.seek(0)

    document_type = (request.form.get("document_type") or "other").strip().lower()
    if not document_type:
        document_type = "other"

    s3_key = upload_document(file, transaction_id, document_type, safe_filename)
    if not s3_key:
        return "Failed to upload document.", 500

    document_id = execute_insert(
        """
        INSERT INTO documents (
            transaction_id, document_type, filename, s3_key, file_size, uploaded_by, uploaded_at
        ) VALUES (%s, %s, %s, %s, %s, %s, CURRENT_TIMESTAMP)
        RETURNING id
        """,
        (
            transaction_id,
            document_type,
            safe_filename,
            s3_key,
            file_size,
            session.get("tc_username", "margaret"),
        ),
    )
    if not document_id:
        return "Failed to save document record.", 500

    ensure_document_requests_table()
    execute_query(
        """
        UPDATE document_requests
        SET received_date = COALESCE(received_date, CURRENT_TIMESTAMP),
            status = 'received',
            updated_at = CURRENT_TIMESTAMP
        WHERE transaction_id = %s
          AND document_type = %s
          AND status <> 'received'
        """,
        (transaction_id, document_type),
    )

    log_document_access(
        document_id=document_id,
        user_name=session.get("tc_username", "margaret"),
        user_type="tc",
        action="upload",
        ip_address=request.remote_addr or "",
    )
    return redirect(f"{url_for('tc_transaction', transaction_id=transaction_id)}#documents")


@app.route("/tc/transaction/<int:transaction_id>/request-document", methods=["POST"])
@login_required
def send_document_request_now(transaction_id):
    """Allow TC to manually trigger a request email for a missing document."""
    transaction = get_transaction_or_none(transaction_id)
    if not transaction:
        return "Transaction not found", 404

    document_type = (request.form.get("document_type") or "").strip().lower()
    if document_type not in REQUIRED_DOCUMENT_TYPES:
        redirect_url = url_for(
            "tc_transaction",
            transaction_id=transaction_id,
            doc_notice="Invalid document type selected.",
            doc_notice_type="error",
        )
        return redirect(f"{redirect_url}#documents")

    if transaction_has_document(transaction, transaction_id, document_type):
        redirect_url = url_for(
            "tc_transaction",
            transaction_id=transaction_id,
            doc_notice=f"{document_type_label(document_type)} is already on file.",
            doc_notice_type="warning",
        )
        return redirect(f"{redirect_url}#documents")

    result = send_manual_document_request(transaction, document_type)
    if result.get("success"):
        action_label = "Request" if result.get("kind") == "initial" else "Reminder"
        redirect_url = url_for(
            "tc_transaction",
            transaction_id=transaction_id,
            doc_notice=(
                f"{action_label} sent for {document_type_label(document_type)} "
                f"to {result.get('requested_from', 'party').title()}."
            ),
            doc_notice_type="success",
        )
        return redirect(f"{redirect_url}#documents")

    failure_reason = result.get("reason")
    if failure_reason == "missing_recipient":
        notice = (
            f"Cannot send {document_type_label(document_type)} request: "
            f"{result.get('requested_from', 'recipient').title()} email is missing."
        )
        notice_type = "warning"
    elif failure_reason == "already_received":
        notice = f"{document_type_label(document_type)} is already marked as received."
        notice_type = "warning"
    else:
        notice = f"Email send failed for {document_type_label(document_type)}. Please try again."
        notice_type = "error"

    redirect_url = url_for(
        "tc_transaction",
        transaction_id=transaction_id,
        doc_notice=notice,
        doc_notice_type=notice_type,
    )
    return redirect(f"{redirect_url}#documents")


@app.route("/tc/transaction/<int:transaction_id>/generate-client-portal", methods=["POST"])
@login_required
def generate_client_portal_link(transaction_id):
    """Generate/send buyer and seller client portal links from TC view."""
    transaction = get_transaction_or_none(transaction_id)
    if not transaction:
        return "Transaction not found", 404

    buyer_email = normalize_email(request.form.get("buyer_email"))
    seller_email = normalize_email(request.form.get("seller_email"))
    if buyer_email and not is_email_valid(buyer_email):
        buyer_email = ""
    if seller_email and not is_email_valid(seller_email):
        seller_email = ""

    result = provision_client_portal_access(transaction, buyer_email=buyer_email, seller_email=seller_email)
    if not result.get("success"):
        redirect_url = url_for(
            "tc_transaction",
            transaction_id=transaction_id,
            doc_notice="Unable to generate client portal links right now.",
            doc_notice_type="error",
        )
        return redirect(redirect_url)

    redirect_url = url_for(
        "tc_transaction",
        transaction_id=transaction_id,
        doc_notice=f"Client portal links generated. Sent via {result.get('sent_count', 0)} channel(s).",
        doc_notice_type="success",
    )
    return redirect(redirect_url)


def _render_client_portal_page(access_token, active_tab):
    """Render client portal with a selected tab."""
    portal_context = build_client_portal_context(access_token)
    if not portal_context:
        return "Client portal link is invalid or expired.", 404

    notice = (request.args.get("notice") or "").strip()
    notice_type = (request.args.get("notice_type") or "success").strip().lower()
    if notice_type not in {"success", "warning", "error"}:
        notice_type = "success"

    return render_template(
        "client_portal.html",
        active_tab=active_tab,
        portal_notice=notice,
        portal_notice_type=notice_type,
        **portal_context,
    )


@app.route("/client/<access_token>")
def client_portal_home(access_token):
    """Client portal landing page."""
    return _render_client_portal_page(access_token, active_tab="overview")


@app.route("/client/<access_token>/timeline")
def client_portal_timeline(access_token):
    """Client portal timeline view."""
    return _render_client_portal_page(access_token, active_tab="timeline")


@app.route("/client/<access_token>/documents")
def client_portal_documents(access_token):
    """Client portal documents + upload view."""
    return _render_client_portal_page(access_token, active_tab="documents")


@app.route("/client/<access_token>/upload", methods=["POST"])
def client_portal_upload(access_token):
    """Upload signed client documents into the transaction record."""
    access_row = fetch_client_access_by_token(access_token)
    if not access_row:
        return "Client portal link is invalid or expired.", 404

    transaction = get_transaction_or_none(access_row["transaction_id"])
    if not transaction:
        return "Transaction not found.", 404

    if "document_file" not in request.files:
        redirect_url = url_for(
            "client_portal_documents",
            access_token=access_token,
            notice="Please choose a file before uploading.",
            notice_type="warning",
        )
        return redirect(redirect_url)

    file = request.files["document_file"]
    if not file or not file.filename:
        redirect_url = url_for(
            "client_portal_documents",
            access_token=access_token,
            notice="Please choose a file before uploading.",
            notice_type="warning",
        )
        return redirect(redirect_url)

    safe_filename = secure_filename(file.filename)
    extension = file_extension(safe_filename)
    if extension not in ALLOWED_DOCUMENT_EXTENSIONS:
        redirect_url = url_for(
            "client_portal_documents",
            access_token=access_token,
            notice="Invalid file type. Please upload PDF, JPG, JPEG, or PNG.",
            notice_type="error",
        )
        return redirect(redirect_url)

    file.seek(0, os.SEEK_END)
    file_size = file.tell()
    if file_size > MAX_FILE_SIZE:
        redirect_url = url_for(
            "client_portal_documents",
            access_token=access_token,
            notice="File exceeds 16MB upload limit.",
            notice_type="error",
        )
        return redirect(redirect_url)
    file.seek(0)

    document_type = (request.form.get("document_type") or "other").strip().lower()
    valid_upload_types = CLIENT_UPLOAD_DOCUMENT_TYPES | REQUIRED_DOCUMENT_TYPES
    if document_type not in valid_upload_types:
        document_type = "other"

    s3_key = upload_document(file, transaction["id"], document_type, safe_filename)
    if not s3_key:
        redirect_url = url_for(
            "client_portal_documents",
            access_token=access_token,
            notice="Upload failed. Please try again.",
            notice_type="error",
        )
        return redirect(redirect_url)

    execute_insert(
        """
        INSERT INTO documents (
            transaction_id, document_type, filename, s3_key, file_size, uploaded_by, uploaded_at
        ) VALUES (%s, %s, %s, %s, %s, %s, CURRENT_TIMESTAMP)
        RETURNING id
        """,
        (
            transaction["id"],
            document_type,
            safe_filename,
            s3_key,
            file_size,
            f"client_{access_row.get('client_type')}",
        ),
    )

    ensure_document_requests_table()
    execute_query(
        """
        UPDATE document_requests
        SET received_date = COALESCE(received_date, CURRENT_TIMESTAMP),
            status = 'received',
            updated_at = CURRENT_TIMESTAMP
        WHERE transaction_id = %s
          AND document_type = %s
          AND status <> 'received'
        """,
        (transaction["id"], document_type),
    )

    mark_client_accessed(access_row["id"])

    redirect_url = url_for(
        "client_portal_documents",
        access_token=access_token,
        notice=f"Uploaded {document_type_label(document_type)} successfully.",
        notice_type="success",
    )
    return redirect(redirect_url)


@app.route("/tc/document/<int:document_id>/view")
@login_required
def view_document(document_id):
    """View a transaction document using a presigned URL."""
    rows = execute_query(
        "SELECT id, transaction_id, s3_key, filename FROM documents WHERE id = %s",
        (document_id,),
        fetch=True,
    ) or []
    if not rows:
        return "Document not found", 404

    document = rows[0]
    url = get_presigned_url(document["s3_key"], expiration=1800)
    if not url:
        return "Failed to create secure document URL", 500

    log_document_access(
        document_id=document_id,
        user_name=session.get("tc_username", "margaret"),
        user_type="tc",
        action="view",
        ip_address=request.remote_addr or "",
    )
    return redirect(url)


@app.route("/tc/document/<int:document_id>/download")
@login_required
def download_document(document_id):
    """Download a transaction document using a presigned URL."""
    rows = execute_query(
        "SELECT id, transaction_id, s3_key, filename FROM documents WHERE id = %s",
        (document_id,),
        fetch=True,
    ) or []
    if not rows:
        return "Document not found", 404

    document = rows[0]
    url = get_presigned_url(
        document["s3_key"],
        expiration=1800,
        download_filename=document.get("filename") or f"document_{document_id}",
    )
    if not url:
        return "Failed to create secure document URL", 500

    log_document_access(
        document_id=document_id,
        user_name=session.get("tc_username", "margaret"),
        user_type="tc",
        action="download",
        ip_address=request.remote_addr or "",
    )
    return redirect(url)


@app.route("/tc/transaction/<int:transaction_id>/log-communication", methods=["POST"])
@login_required
def log_transaction_communication(transaction_id):
    """Log call/email/text communication for a transaction."""
    if not get_transaction_or_none(transaction_id):
        return "Transaction not found", 404

    communication_type = (request.form.get("communication_type") or "").strip().lower()
    contact_party = (request.form.get("contact_party") or "").strip().lower()
    contact_name = request.form.get("contact_name", "").strip()
    summary = request.form.get("summary", "").strip()
    outcome = request.form.get("outcome", "").strip()
    follow_up_date = parse_optional_date(request.form.get("follow_up_date"))
    follow_up_needed = bool(follow_up_date)

    if not communication_type:
        return "Communication type is required.", 400
    if not contact_party:
        return "Contact party is required.", 400
    if not summary:
        return "Summary is required.", 400

    execute_query(
        """
        INSERT INTO communications (
            transaction_id, communication_type, contact_party, contact_name,
            summary, outcome, follow_up_needed, follow_up_date, logged_by
        ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)
        """,
        (
            transaction_id,
            communication_type,
            contact_party,
            contact_name or None,
            summary,
            outcome or None,
            follow_up_needed,
            follow_up_date,
            session.get("tc_username", "margaret"),
        ),
    )
    return redirect(f"{url_for('tc_transaction', transaction_id=transaction_id)}#communications")


@app.route("/tc/transaction/<int:transaction_id>/mark-payment", methods=["POST"])
@login_required
def mark_transaction_payment(transaction_id):
    """Mark payment as received manually from TC dashboard."""
    transaction = get_transaction_or_none(transaction_id)
    if not transaction:
        return "Transaction not found", 404

    payment_type = (request.form.get("payment_type") or "").strip().lower()
    if payment_type not in {"upfront", "closing"}:
        return "Invalid payment type.", 400

    if payment_type == "upfront":
        upfront_breakdown = calculate_payment_breakdown(transaction, "upfront")
        referral_credit_used = float(upfront_breakdown.get("referral_credit", 0) or 0)
        amount_marked = float(upfront_breakdown["amount"])
        execute_query(
            """
            UPDATE transactions
            SET payment_upfront_paid = TRUE,
                payment_upfront_date = COALESCE(payment_upfront_date, CURRENT_TIMESTAMP),
                updated_at = CURRENT_TIMESTAMP
            WHERE id = %s
            """,
            (transaction_id,),
        )
        mark_referral_credit_used_if_needed(transaction_id, transaction.get("agent_name"))
        upsert_commission_tracking(transaction_id, referral_credit_override=referral_credit_used)
    else:
        amount_marked = calculate_payment_breakdown(transaction, "closing")["amount"]
        execute_query(
            """
            UPDATE transactions
            SET payment_closing_paid = TRUE,
                payment_closing_date = COALESCE(payment_closing_date, CURRENT_TIMESTAMP),
                updated_at = CURRENT_TIMESTAMP
            WHERE id = %s
            """,
            (transaction_id,),
        )
        upsert_commission_tracking(transaction_id)

    send_sms(
        transaction.get("agent_phone"),
        f"Payment marked received (${float(amount_marked):.2f}) for {payment_type}. - Maverick TC",
    )
    execute_query(
        """
        INSERT INTO communications (transaction_id, communication_type, contact_party, contact_name, summary, outcome)
        VALUES (%s, 'text', 'agent', 'system', %s, %s)
        """,
        (
            transaction_id,
            f"{payment_type.title()} payment marked paid manually",
            f"amount={float(amount_marked):.2f}",
        ),
    )
    return redirect(f"{url_for('tc_transaction', transaction_id=transaction_id)}#payments")


@app.route("/tc/transaction/<int:transaction_id>/send-referrer-thanks", methods=["POST"])
@login_required
def send_referrer_thanks(transaction_id):
    """Send referral thank-you SMS to the referring agent."""
    transaction = get_transaction_or_none(transaction_id)
    if not transaction:
        return "Transaction not found", 404

    referrer_name = (transaction.get("referred_by_agent") or "").strip()
    if not referrer_name:
        return "No referral is associated with this transaction.", 400

    referral_rows = execute_query(
        """
        SELECT referrer_agent_phone
        FROM referrals
        WHERE referred_transaction_id = %s
        ORDER BY created_at DESC
        LIMIT 1
        """,
        (transaction_id,),
        fetch=True,
    ) or []
    referrer_phone = referral_rows[0]["referrer_agent_phone"] if referral_rows else None

    if not referrer_phone:
        fallback_rows = execute_query(
            """
            SELECT agent_phone
            FROM transactions
            WHERE LOWER(agent_name) = LOWER(%s)
            ORDER BY created_at DESC
            LIMIT 1
            """,
            (referrer_name,),
            fetch=True,
        ) or []
        referrer_phone = fallback_rows[0]["agent_phone"] if fallback_rows else None

    if not referrer_phone:
        return "Could not find referrer phone number.", 400

    sid = send_sms(
        referrer_phone,
        (
            f"Thanks for referring {transaction.get('agent_name')} to Maverick TC. "
            "We appreciate your trust and partnership. - Maverick TC"
        ),
    )
    execute_query(
        """
        INSERT INTO communications (transaction_id, communication_type, contact_party, contact_name, summary, outcome)
        VALUES (%s, 'text', 'agent', %s, %s, %s)
        """,
        (
            transaction_id,
            referrer_name,
            "Referral thank-you text sent to referrer",
            f"message_sid={sid or 'failed'}",
        ),
    )
    return redirect(f"{url_for('tc_transaction', transaction_id=transaction_id)}#review-details")


@app.route("/upload", methods=["POST"])
def upload_contract_route():
    """Handle contract upload from agent."""
    try:
        agent_name = request.form.get("agent_name", "").strip()
        agent_phone = normalize_phone(request.form.get("agent_phone", "").strip())
        agent_email = request.form.get("agent_email", "").strip()
        property_address = request.form.get("property_address", "").strip()
        rush_service = request.form.get("rush_service") == "on"
        referral_source = request.form.get("referral_source", "").strip()
        referred_by = request.form.get("referred_by", "").strip() if referral_source == "referral" else None

        if not all([agent_name, agent_phone, agent_email, property_address, referral_source]):
            return jsonify({"success": False, "error": "All required fields must be provided"}), 400
        if referral_source == "referral" and not referred_by:
            return jsonify({"success": False, "error": "Referral agent name is required"}), 400

        if "contract_pdf" not in request.files:
            return jsonify({"success": False, "error": "No file uploaded"}), 400

        file = request.files["contract_pdf"]
        if not file or file.filename == "":
            return jsonify({"success": False, "error": "No file selected"}), 400
        if not allowed_file(file.filename):
            return jsonify({"success": False, "error": "Only PDF files allowed"}), 400

        file.seek(0, os.SEEK_END)
        file_size = file.tell()
        if file_size > MAX_FILE_SIZE:
            return jsonify({"success": False, "error": "File too large (max 16MB)"}), 400
        file.seek(0)

        insert_query = """
        INSERT INTO transactions (
            agent_name, agent_phone, agent_email, property_address,
            rush_service, referred_by_agent, status, created_at, updated_at
        ) VALUES (%s, %s, %s, %s, %s, %s, 'NEEDS_MARGARET_REVIEW', CURRENT_TIMESTAMP, CURRENT_TIMESTAMP)
        RETURNING id
        """
        transaction_id = execute_insert(
            insert_query,
            (agent_name, agent_phone, agent_email, property_address, rush_service, referred_by),
        )
        if not transaction_id:
            return jsonify({"success": False, "error": "Database error"}), 500

        safe_filename = secure_filename(file.filename)
        if not safe_filename.lower().endswith(".pdf"):
            safe_filename = f"{safe_filename}.pdf"

        s3_key = upload_contract(file, transaction_id, property_address)
        if not s3_key:
            execute_query("UPDATE transactions SET status = 'CANCELLED' WHERE id = %s", (transaction_id,))
            return jsonify({"success": False, "error": "File upload failed"}), 500

        update_query = """
        UPDATE transactions
        SET contract_s3_key = %s,
            contract_pdf_url = %s,
            updated_at = CURRENT_TIMESTAMP
        WHERE id = %s
        """
        execute_query(update_query, (s3_key, safe_filename, transaction_id))
        ensure_document_requests_table()
        execute_query(
            """
            UPDATE document_requests
            SET received_date = COALESCE(received_date, CURRENT_TIMESTAMP),
                status = 'received',
                updated_at = CURRENT_TIMESTAMP
            WHERE transaction_id = %s
              AND document_type = 'contract'
              AND status <> 'received'
            """,
            (transaction_id,),
        )
        upsert_commission_tracking(transaction_id, referral_credit_override=0)
        run_contract_extraction_async(transaction_id, s3_key, property_address)

        confirmation_message = f"""Contract received for {property_address}!

Margaret will review within 2 hours. You'll receive your timeline shortly.

- Maverick TC"""
        send_sms_async(agent_phone, confirmation_message)

        confirmation_code = f"MAV-{int(transaction_id):06d}"
        print(f"Contract uploaded: Transaction #{transaction_id} - {property_address}")
        return jsonify(
            {
                "success": True,
                "transaction_id": transaction_id,
                "confirmation_code": confirmation_code,
                "message": "Contract received successfully",
            }
        )
    except Exception as exc:
        print(f"Upload error: {exc}")
        return jsonify({"success": False, "error": "Server error. Please try again."}), 500


@app.route("/pay/<int:transaction_id>/<payment_type>")
def payment_page(transaction_id, payment_type):
    """Render secure agent payment page."""
    if payment_type not in {"upfront", "closing"}:
        return "Invalid payment type", 400

    rows = execute_query(
        """
        SELECT id, property_address, agent_name, agent_phone, rush_service, referred_by_agent, status,
               payment_upfront_paid, payment_closing_paid
        FROM transactions
        WHERE id = %s
        """,
        (transaction_id,),
        fetch=True,
    ) or []
    if not rows:
        return "Transaction not found", 404

    transaction = rows[0]
    if transaction.get("status") == "CANCELLED":
        return "This transaction has been cancelled.", 400

    if payment_type == "upfront" and transaction["payment_upfront_paid"]:
        return (
            "<h2>Payment already received</h2>"
            "<p>Thank you! Your upfront payment has already been recorded.</p>",
            200,
        )
    if payment_type == "closing" and transaction["payment_closing_paid"]:
        return (
            "<h2>Payment already received</h2>"
            "<p>Thank you! Your closing payment has already been recorded.</p>",
            200,
        )

    breakdown = calculate_payment_breakdown(transaction, payment_type)
    payment_type_label = "Upfront" if payment_type == "upfront" else "Closing"
    payment_data = {
        "transaction_id": transaction_id,
        "property_address": transaction["property_address"],
        "payment_type": payment_type,
        "payment_type_label": payment_type_label,
        "original_amount": f"{breakdown['original_amount']:.2f}",
        "referral_credit": f"{breakdown['referral_credit']:.2f}",
        "amount": f"{breakdown['amount']:.2f}",
        "amount_number": round(float(breakdown["amount"]), 2),
        "has_referral_credit": float(breakdown["referral_credit"]) > 0,
    }

    venmo_handle = os.getenv("VENMO_HANDLE", "GetMaverick").lstrip("@")
    paypal_email = os.getenv("PAYPAL_EMAIL", "pay@getmaverick.com")
    paypal_handle = os.getenv("PAYPAL_HANDLE", paypal_email.split("@")[0])

    return render_template(
        "payment.html",
        payment=payment_data,
        stripe_publishable_key=os.getenv("STRIPE_PUBLISHABLE_KEY", ""),
        venmo_handle=venmo_handle,
        paypal_handle=paypal_handle,
    )


@app.route("/pay/<int:transaction_id>/<payment_type>/process", methods=["POST"])
def process_payment(transaction_id, payment_type):
    """Process a card payment through Stripe."""
    if payment_type not in {"upfront", "closing"}:
        return jsonify({"success": False, "error": "Invalid payment type"}), 400
    if not stripe.api_key:
        return jsonify({"success": False, "error": "Stripe is not configured"}), 500

    transaction_rows = execute_query(
        """
        SELECT id, property_address, agent_name, agent_phone, rush_service, referred_by_agent, status,
               payment_upfront_paid, payment_closing_paid
        FROM transactions
        WHERE id = %s
        """,
        (transaction_id,),
        fetch=True,
    ) or []
    if not transaction_rows:
        return jsonify({"success": False, "error": "Transaction not found"}), 404

    transaction = transaction_rows[0]
    if transaction.get("status") == "CANCELLED":
        return jsonify({"success": False, "error": "This transaction has been cancelled"}), 400
    if payment_type == "upfront" and transaction.get("payment_upfront_paid"):
        return jsonify({"success": False, "error": "Upfront payment is already recorded"}), 409
    if payment_type == "closing" and transaction.get("payment_closing_paid"):
        return jsonify({"success": False, "error": "Closing payment is already recorded"}), 409

    payload = request.get_json(silent=True) or {}
    payment_method_id = payload.get("payment_method_id")
    amount_raw = payload.get("amount")

    try:
        amount = float(amount_raw)
    except (TypeError, ValueError):
        return jsonify({"success": False, "error": "Invalid payment amount"}), 400

    if not payment_method_id or amount <= 0:
        return jsonify({"success": False, "error": "Missing payment data"}), 400

    breakdown = calculate_payment_breakdown(transaction, payment_type)
    expected_amount = round(float(breakdown["amount"]), 2)
    if abs(amount - expected_amount) > 0.01:
        return jsonify({"success": False, "error": "Payment amount mismatch. Refresh and try again."}), 400

    try:
        intent = stripe.PaymentIntent.create(
            amount=int(round(expected_amount * 100)),
            currency="usd",
            payment_method=payment_method_id,
            confirm=True,
            automatic_payment_methods={"enabled": True, "allow_redirects": "never"},
            description=f"Maverick TC - Transaction #{transaction_id} - {payment_type}",
            metadata={
                "transaction_id": str(transaction_id),
                "payment_type": payment_type,
                "property_address": transaction.get("property_address", ""),
            },
        )

        if intent.status != "succeeded":
            return jsonify({"success": False, "error": "Payment not completed"}), 400

        if payment_type == "upfront":
            updated = execute_query(
                """
                UPDATE transactions
                SET payment_upfront_paid = TRUE,
                    payment_upfront_date = COALESCE(payment_upfront_date, CURRENT_TIMESTAMP),
                    updated_at = CURRENT_TIMESTAMP
                WHERE id = %s
                """,
                (transaction_id,),
            )
            if not updated:
                return jsonify({"success": False, "error": "Failed to record payment"}), 500
            mark_referral_credit_used_if_needed(transaction_id, transaction.get("agent_name"))
            upsert_commission_tracking(
                transaction_id,
                referral_credit_override=float(breakdown.get("referral_credit", 0) or 0),
            )
        else:
            updated = execute_query(
                """
                UPDATE transactions
                SET payment_closing_paid = TRUE,
                    payment_closing_date = COALESCE(payment_closing_date, CURRENT_TIMESTAMP),
                    updated_at = CURRENT_TIMESTAMP
                WHERE id = %s
                """,
                (transaction_id,),
            )
            if not updated:
                return jsonify({"success": False, "error": "Failed to record payment"}), 500
            upsert_commission_tracking(transaction_id)

        if transaction.get("agent_phone"):
            send_sms(
                transaction["agent_phone"],
                (
                    f"Payment received (${expected_amount:.2f}) for {payment_type}. "
                    "Thank you. - Maverick TC"
                ),
            )

        execute_query(
            """
            INSERT INTO communications (transaction_id, communication_type, contact_party, contact_name, summary, outcome)
            VALUES (%s, 'text', 'agent', 'system', %s, %s)
            """,
            (
                transaction_id,
                f"Payment processed via Stripe ({payment_type})",
                f"intent={intent.id} amount={expected_amount:.2f}",
            ),
        )

        return jsonify({"success": True, "payment_intent_id": intent.id})
    except stripe.error.CardError as exc:
        return jsonify({"success": False, "error": exc.user_message or "Card was declined"}), 400
    except stripe.error.StripeError as exc:
        return jsonify({"success": False, "error": exc.user_message or "Payment processing error"}), 400
    except Exception as exc:
        print(f"Payment error: {exc}")
        return jsonify({"success": False, "error": "Payment processing error"}), 500


@app.route("/stripe/webhook", methods=["POST"])
def stripe_webhook():
    """Handle Stripe webhook events for payment state sync."""
    webhook_secret = os.getenv("STRIPE_WEBHOOK_SECRET", "").strip()
    if not webhook_secret:
        return jsonify({"received": False, "error": "Webhook secret not configured"}), 500

    payload = request.get_data(as_text=False)
    signature = request.headers.get("Stripe-Signature", "")

    try:
        event = stripe.Webhook.construct_event(payload, signature, webhook_secret)
    except ValueError:
        return jsonify({"received": False, "error": "Invalid payload"}), 400
    except stripe.error.SignatureVerificationError:
        return jsonify({"received": False, "error": "Invalid signature"}), 400

    event_type = event.get("type")
    data_object = (event.get("data") or {}).get("object") or {}
    metadata = data_object.get("metadata") or {}
    transaction_id_raw = metadata.get("transaction_id")
    payment_type = metadata.get("payment_type", "upfront")
    if payment_type not in {"upfront", "closing"}:
        payment_type = "upfront"

    transaction_id = None
    if transaction_id_raw:
        try:
            transaction_id = int(transaction_id_raw)
        except ValueError:
            transaction_id = None

    if event_type == "payment_intent.succeeded" and transaction_id:
        if payment_type == "upfront":
            execute_query(
                """
                UPDATE transactions
                SET payment_upfront_paid = TRUE,
                    payment_upfront_date = COALESCE(payment_upfront_date, CURRENT_TIMESTAMP),
                    updated_at = CURRENT_TIMESTAMP
                WHERE id = %s
                """,
                (transaction_id,),
            )
            rows = execute_query(
                """
                SELECT id, agent_name, rush_service, referred_by_agent
                FROM transactions
                WHERE id = %s
                """,
                (transaction_id,),
                fetch=True,
            ) or []
            if rows:
                referral_credit = calculate_payment_breakdown(rows[0], "upfront").get("referral_credit", 0)
                mark_referral_credit_used_if_needed(transaction_id, rows[0].get("agent_name"))
                if float(referral_credit or 0) > 0:
                    upsert_commission_tracking(transaction_id, referral_credit_override=referral_credit)
                else:
                    upsert_commission_tracking(transaction_id)
        else:
            execute_query(
                """
                UPDATE transactions
                SET payment_closing_paid = TRUE,
                    payment_closing_date = COALESCE(payment_closing_date, CURRENT_TIMESTAMP),
                    updated_at = CURRENT_TIMESTAMP
                WHERE id = %s
                """,
                (transaction_id,),
            )
            upsert_commission_tracking(transaction_id)

        execute_query(
            """
            INSERT INTO communications (transaction_id, communication_type, contact_party, contact_name, summary, outcome)
            VALUES (%s, 'text', 'agent', 'system',
                    %s, %s)
            """,
            (
                transaction_id,
                f"Stripe webhook confirmed {payment_type} payment",
                f"event={event_type} intent={data_object.get('id', 'unknown')}",
            ),
        )

    if event_type == "payment_intent.payment_failed" and transaction_id:
        rows = execute_query(
            """
            SELECT id, property_address, agent_phone, status
            FROM transactions
            WHERE id = %s
            """,
            (transaction_id,),
            fetch=True,
        ) or []

        if rows and rows[0]["status"] not in {"CANCELLED", "COMPLETED"}:
            base_url = (os.getenv("APP_BASE_URL") or "http://localhost:5000").rstrip("/")
            retry_link = f"{base_url}/pay/{transaction_id}/{payment_type}"
            send_sms(
                rows[0]["agent_phone"],
                (
                    f"We could not process your {payment_type} payment for "
                    f"{rows[0]['property_address']}.\nRetry securely: {retry_link}\n- Maverick TC"
                ),
            )

        execute_query(
            """
            INSERT INTO communications (transaction_id, communication_type, contact_party, contact_name, summary, outcome)
            VALUES (%s, 'text', 'agent', 'system',
                    %s, %s)
            """,
            (
                transaction_id,
                f"Stripe webhook reported failed {payment_type} payment",
                f"event={event_type} intent={data_object.get('id', 'unknown')}",
            ),
        )

    return jsonify({"received": True})


@app.route("/tc/reminder/<int:deadline_id>/send", methods=["POST"])
@login_required
def send_reminder_now(deadline_id):
    """Manually send reminder for a deadline."""
    try:
        rows = execute_query(
            """
            SELECT d.deadline_type, d.deadline_date, t.property_address, t.agent_phone
            FROM deadlines d
            JOIN transactions t ON d.transaction_id = t.id
            WHERE d.id = %s
            """,
            (deadline_id,),
            fetch=True,
        ) or []
        if not rows:
            return jsonify({"success": False, "error": "Deadline not found"}), 404

        deadline = rows[0]
        if not deadline.get("deadline_date"):
            return jsonify({"success": False, "error": "Deadline date is missing"}), 400

        days_until = (deadline["deadline_date"] - date.today()).days
        sent_sid = send_reminder(
            to_number=deadline["agent_phone"],
            property_address=deadline["property_address"],
            deadline_type=deadline["deadline_type"].replace("_", " ").title(),
            deadline_date=deadline["deadline_date"].strftime("%m/%d/%Y"),
            days_until=days_until,
        )
        if not sent_sid:
            return jsonify({"success": False, "error": "Failed to send SMS"}), 500

        if days_until >= 10:
            update_query = """
            UPDATE deadlines
            SET reminder_10d_sent = TRUE,
                reminder_10d_sent_at = CURRENT_TIMESTAMP
            WHERE id = %s
            """
        elif days_until >= 7:
            update_query = """
            UPDATE deadlines
            SET reminder_7d_sent = TRUE,
                reminder_7d_sent_at = CURRENT_TIMESTAMP
            WHERE id = %s
            """
        elif days_until >= 3:
            update_query = """
            UPDATE deadlines
            SET reminder_3d_sent = TRUE,
                reminder_3d_sent_at = CURRENT_TIMESTAMP
            WHERE id = %s
            """
        else:
            update_query = """
            UPDATE deadlines
            SET reminder_1d_sent = TRUE,
                reminder_1d_sent_at = CURRENT_TIMESTAMP
            WHERE id = %s
            """

        updated = execute_query(update_query, (deadline_id,))
        if not updated:
            return jsonify({"success": False, "error": "Failed to update reminder log"}), 500

        return jsonify({"success": True, "message_sid": sent_sid})
    except Exception as exc:
        print(f"Reminder send error: {exc}")
        return jsonify({"success": False, "error": "Unable to send reminder right now"}), 500


@app.route("/tc/transaction/<int:transaction_id>/mark-complete", methods=["GET", "POST"])
@login_required
def mark_transaction_complete(transaction_id):
    """Mark transaction as completed."""
    if request.method == "GET":
        rows = execute_query(
            "SELECT property_address, agent_name, agent_phone FROM transactions WHERE id = %s",
            (transaction_id,),
            fetch=True,
        ) or []
        if not rows:
            return "Transaction not found", 404

        txn = rows[0]
        return f"""
        <html>
        <head>
            <title>Mark Complete</title>
            <style>
                body {{ font-family: sans-serif; padding: 40px; max-width: 600px; margin: 0 auto; }}
                .card {{ background: white; padding: 30px; border-radius: 8px; box-shadow: 0 2px 8px rgba(0,0,0,0.1); }}
                h2 {{ color: #1e3a8a; margin-bottom: 20px; }}
                .checklist {{ background: #f9fafb; padding: 20px; border-radius: 6px; margin: 20px 0; }}
                .checklist-item {{ padding: 10px 0; border-bottom: 1px solid #e5e7eb; }}
                .btn {{ padding: 12px 24px; background: #10b981; color: white; border: none; border-radius: 6px; cursor: pointer; font-size: 16px; margin-right: 10px; text-decoration: none; display: inline-block; }}
                .btn-secondary {{ background: #6b7280; }}
            </style>
        </head>
        <body>
            <div class="card">
                <h2>Mark Transaction Complete</h2>
                <p><strong>Property:</strong> {txn['property_address']}</p>
                <p><strong>Agent:</strong> {txn['agent_name']}</p>
                <div class="checklist">
                    <h3>Pre-Completion Checklist:</h3>
                    <div class="checklist-item">Closing occurred successfully</div>
                    <div class="checklist-item">All documents received</div>
                    <div class="checklist-item">Final settlement statement uploaded</div>
                    <div class="checklist-item">Commission disbursed</div>
                    <div class="checklist-item">Closing payment received</div>
                </div>
                <form method="POST">
                    <button type="submit" class="btn">Mark Complete</button>
                    <a href="/tc/transaction/{transaction_id}" class="btn btn-secondary">Cancel</a>
                </form>
            </div>
        </body>
        </html>
        """

    execute_query(
        """
        UPDATE transactions
        SET status = 'COMPLETED',
            updated_at = CURRENT_TIMESTAMP
        WHERE id = %s
        """,
        (transaction_id,),
    )

    rows = execute_query(
        "SELECT property_address, agent_name, agent_phone FROM transactions WHERE id = %s",
        (transaction_id,),
        fetch=True,
    ) or []
    if rows:
        txn = rows[0]
        congrats_message = f"""Congratulations on closing {txn['property_address']}!

Thank you for using Maverick TC. We would love your feedback.

Refer a friend and you both get $50 off.

- Heidi and Margaret"""
        send_sms(txn["agent_phone"], congrats_message)

    execute_query(
        """
        UPDATE transactions
        SET review_requested = TRUE,
            review_requested_date = %s,
            updated_at = CURRENT_TIMESTAMP
        WHERE id = %s
        """,
        (datetime.now(), transaction_id),
    )

    return redirect(url_for("tc_dashboard"))


@app.route("/tc/transaction/<int:transaction_id>/cancel", methods=["POST"])
@login_required
def cancel_transaction(transaction_id):
    """Cancel transaction."""
    execute_query(
        """
        UPDATE transactions
        SET status = 'CANCELLED',
            updated_at = CURRENT_TIMESTAMP
        WHERE id = %s
        """,
        (transaction_id,),
    )
    return redirect(url_for("tc_dashboard"))


@app.route("/sms-webhook", methods=["POST"])
def sms_webhook():
    """Handle incoming SMS from agents."""
    incoming_msg = request.form.get("Body", "").strip().lower()
    from_number = normalize_phone(request.form.get("From", ""))
    response = MessagingResponse()

    emergency_keywords = {"emergency", "urgent", "asap", "help now"}
    if any(word in incoming_msg for word in emergency_keywords):
        heidi_phone = os.getenv("HEIDI_PHONE")
        margaret_phone = os.getenv("MARGARET_PHONE")
        if heidi_phone:
            send_sms(heidi_phone, f"EMERGENCY from {from_number}: {incoming_msg}")
        if margaret_phone:
            send_sms(margaret_phone, f"EMERGENCY from {from_number}: {incoming_msg}")
        response.message("Emergency alert sent to Heidi and Margaret. They will call you ASAP.")
        return str(response)

    status_keywords = {"status", "closing", "when", "deadline", "update"}
    if any(word in incoming_msg for word in status_keywords):
        last_10 = re.sub(r"\D", "", from_number)[-10:]
        query = """
        SELECT id, property_address, closing_date, status
        FROM transactions
        WHERE RIGHT(REGEXP_REPLACE(agent_phone, '[^0-9]', '', 'g'), 10) = %s
          AND status IN ('NEEDS_MARGARET_REVIEW', 'ACTIVE')
        ORDER BY created_at DESC
        LIMIT 1
        """
        transactions = execute_query(query, (last_10,), fetch=True) or []

        if transactions:
            txn = transactions[0]
            if txn["status"] == "NEEDS_MARGARET_REVIEW":
                response.message(f"{txn['property_address']}: Under review. Margaret will call you today.")
            else:
                closing_date = txn["closing_date"].strftime("%Y-%m-%d") if txn["closing_date"] else "TBD"
                response.message(
                    f"{txn['property_address']}: Closes {closing_date}. "
                    "Margaret will send a detailed update tomorrow morning."
                )
        else:
            response.message("No active transactions found. Margaret will call you tomorrow morning to help.")
        return str(response)

    response.message(
        "Got your message. Margaret will call you during business hours "
        "(8am-5pm Mon-Fri). For emergencies, text EMERGENCY."
    )
    return str(response)


@app.errorhandler(404)
def not_found(_exc):
    return (
        render_template(
            "error_page.html",
            status_code=404,
            title="Page Not Found",
            message="The page you requested does not exist.",
        ),
        404,
    )


@app.errorhandler(500)
def server_error(_exc):
    return (
        render_template(
            "error_page.html",
            status_code=500,
            title="Server Error",
            message="Something went wrong. Please try again in a moment.",
        ),
        500,
    )


if __name__ == "__main__":
    app.run(debug=True, host="0.0.0.0", port=5000)
