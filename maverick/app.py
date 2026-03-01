import os
import re
import csv
import io
import json
import hashlib
import tempfile
from datetime import date, datetime, time, timedelta
from functools import wraps
from threading import Thread
from typing import Any
from urllib.parse import urlencode
from uuid import uuid4

import jwt
import stripe
from dotenv import load_dotenv
from flask import Flask, Response, g, has_request_context, jsonify, redirect, render_template, request, session, url_for
from reportlab.lib import colors
from reportlab.lib.pagesizes import letter
from reportlab.lib.styles import getSampleStyleSheet
from reportlab.platypus import Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle
from twilio.twiml.messaging_response import MessagingResponse
from twilio.twiml.voice_response import VoiceResponse
from werkzeug.security import check_password_hash
from werkzeug.utils import secure_filename

from automation.task_auto_completion import (
    check_task_completion,
    ensure_task_completion_tables,
    fetch_task_auto_completion_metrics,
    record_auto_completion_undo,
)
from automation.problem_detector import (
    analyze_transaction_health,
    deactivate_problem_detection_whitelist,
    ensure_problem_detection_tables,
    execute_suggestion_action,
    fetch_latest_health_report,
    fetch_problem_detection_settings,
    fetch_problem_detection_whitelist,
    mark_problem_result_handled,
    run_problem_detection_if_stale,
    update_problem_detection_settings,
    upsert_problem_detection_whitelist,
)
from config import Config
from utils.bulk_messaging import (
    SMART_TEMPLATE_VARIABLES,
    build_bulk_message_preview,
    ensure_bulk_messaging_tables,
    fetch_bulk_message_history,
    fetch_bulk_message_progress,
    fetch_bulk_message_status_options,
    fetch_bulk_message_templates,
    queue_bulk_message_job,
    save_bulk_message_template,
)
from utils.closing_checklist import (
    add_closing_checklist_item,
    approve_and_send_closing_checklist,
    auto_send_unreviewed_closing_checklists,
    ensure_closing_checklist_tables,
    fetch_closing_checklist,
    fetch_closing_checklist_by_access_token,
    fetch_closing_checklist_by_transaction,
    fetch_closing_checklist_items,
    fetch_closing_checklist_recipients,
    fetch_closing_checklists_for_tc,
    generate_closing_checklist,
    generate_due_closing_checklists,
    mark_closing_checklist_recipient_viewed,
    regenerate_closing_checklist_pdf,
    remove_closing_checklist_item,
    send_closing_checklist,
    toggle_closing_checklist_item,
)
from utils.calendar_sync import (
    delete_calendar_events,
    fetch_calendar_mapping_by_event_id,
    fetch_calendar_mappings,
    fetch_calendar_sync_metrics,
    fetch_calendar_sync_settings,
    log_calendar_sync_event,
    sync_all_deadlines,
    sync_to_calendar,
    update_calendar_event,
    upsert_calendar_webhook_channel,
    upsert_transaction_calendar_preferences,
    fetch_transaction_calendar_preferences,
    update_calendar_sync_settings,
    ensure_calendar_sync_tables,
)
from utils.common_qa import (
    AUTO_ANSWER_CONFIDENCE_THRESHOLD,
    COMMON_QA_CATEGORY_OPTIONS,
    SUGGEST_CONFIDENCE_THRESHOLD,
    answer_similarity,
    build_agent_faq_draft,
    create_common_qa_entry,
    ensure_common_qa_tables,
    evaluate_common_qa_decision,
    fetch_common_qa_analytics,
    fetch_common_qa_rows,
    increment_common_qa_reuse,
    infer_common_qa_category,
    log_common_qa_event,
    normalize_common_qa_category,
    update_common_qa_entry,
)
from utils.db import execute_insert, execute_query
from utils.email import send_email, send_html_email
from utils.payments import calculate_payment_breakdown
from utils.contract_extraction import (
    compare_extractions,
    extract_via_anthropic,
    extract_via_ocr,
    extract_via_pdfplumber,
    extract_via_pypdf,
)
from utils.document_analysis import analyze_appraisal, analyze_hoa_documents, analyze_inspection_report
from utils.agent_status_updates import (
    AGENT_STATUS_TEMPLATE_TOKENS,
    SCHEDULE_SLOT_OPTIONS,
    add_agent_status_opt_out,
    build_agent_status_update_payloads,
    deactivate_agent_status_opt_out,
    dispatch_agent_status_updates,
    ensure_agent_status_update_tables,
    fetch_agent_status_opt_outs,
    fetch_agent_status_update_metrics,
    fetch_agent_status_update_runs,
    fetch_agent_status_update_settings,
    update_agent_status_update_settings,
)
from utils.document_processing import (
    ensure_document_classification_corrections_table,
    extract_earnest_amount,
    normalize_document_type,
    process_uploaded_document,
)
from utils.heads_up import (
    HEADS_UP_PATTERN_META,
    accept_heads_up_signal,
    build_heads_up_report,
    dismiss_heads_up_signal,
    fetch_pattern_preferences,
    refresh_heads_up_if_stale,
    run_heads_up_monitor,
    save_pattern_preference,
)
from utils.inbound_email import (
    classify_inbound_email,
    extract_email_address,
    parse_transaction_alias,
    split_recipient_addresses,
)
from utils.s3 import download_file, get_presigned_url, log_document_access, upload_contract, upload_local_file
from utils.sms import send_payment_link, send_reminder, send_sms, send_timeline_approved
from utils.timeline_generator import (
    generate_transaction_timeline_pdf,
    generate_transaction_timeline_pdf_bytes,
    upload_transaction_timeline_pdf,
)
from utils.timeline_pdf import build_timeline_pdf
from utils.voice_notes import (
    ensure_voice_note_tables,
    fetch_voice_note_audio_payload,
    handle_twilio_transcription_callback,
    queue_voice_note_processing,
    register_voice_note_capture,
)
from utils.vendor_automation import (
    VENDOR_TYPES,
    complete_vendor_followup_tasks,
    create_vendor_contact,
    ensure_vendor_automation_tables,
    fetch_pending_vendor_responses,
    fetch_vendor_contacts_with_performance,
    log_vendor_outreach,
    mark_vendor_outreach_scheduled,
    normalize_vendor_type,
    parse_schedule_datetime,
    send_manual_vendor_follow_up,
    send_vendor_requests,
    set_vendor_contact_active,
    update_vendor_contact,
)

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

CRITICAL_COMPLETION_DOCUMENT_TYPES = {
    "contract",
    "title_commitment",
    "loan_approval",
    "insurance_binder",
    "settlement_statement",
}

POSITIVE_REVIEW_THRESHOLD = 4

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

DOCUMENT_CLASSIFICATION_OVERRIDE_TYPES = sorted(
    {
        "earnest_receipt",
        "option_receipt",
        "seller_disclosure",
        "survey",
        "hoa_docs",
        "title_commitment",
        "inspection_report",
        "appraisal",
        "loan_approval",
        "insurance_binder",
        "settlement_statement",
        "signed_amendment",
        "signed_disclosure",
        "signed_addendum",
        "other",
        "unknown",
    }
)

HOA_ANALYSIS_DOCUMENT_TYPES = {"hoa", "hoa_documents", "hoa_docs"}
INSPECTION_ANALYSIS_DOCUMENT_TYPES = {"inspection", "inspection_report"}
APPRAISAL_ANALYSIS_DOCUMENT_TYPES = {"appraisal", "appraisal_report"}

TIMELINE_VENDOR_TYPES = ("inspector", "appraiser", "survey", "title")
TIMELINE_MAJOR_DEADLINE_TYPES = {"option_fee", "earnest_money", "option_period_end", "financing_approval", "closing"}
INBOUND_MAILBOX_ROLES = ("buyer", "seller", "lender")
INBOUND_SENDER_ROLES = (
    "agent",
    "buyer",
    "seller",
    "lender",
    "title_company",
    "inspector",
    "appraiser",
    "survey",
    "external",
)

INTELLIGENT_NUDGE_DEFAULTS = {
    "inspection_not_scheduled": {
        "label": "Inspection not scheduled",
        "lead_days": 5,
        "sms_template": "inspection_reminder.txt",
        "email_template": "inspection_reminder.html",
        "include_preferred_vendors": True,
    },
    "earnest_not_received": {
        "label": "Earnest not received",
        "lead_days": 2,
        "sms_template": "earnest_reminder.txt",
        "email_template": "earnest_reminder.html",
        "include_preferred_vendors": False,
    },
    "appraisal_not_ordered": {
        "label": "Appraisal not ordered",
        "lead_days": 7,
        "sms_template": "appraisal_reminder.txt",
        "email_template": "appraisal_reminder.html",
        "include_preferred_vendors": False,
    },
    "hoa_docs_not_received": {
        "label": "HOA docs not received",
        "lead_days": 5,
        "sms_template": "hoa_reminder.txt",
        "email_template": "hoa_reminder.html",
        "include_preferred_vendors": False,
    },
    "survey_not_ordered": {
        "label": "Survey not ordered",
        "lead_days": 5,
        "sms_template": "survey_reminder.txt",
        "email_template": "survey_reminder.html",
        "include_preferred_vendors": False,
    },
    "title_not_received": {
        "label": "Title commitment not received",
        "lead_days": 7,
        "sms_template": "title_reminder.txt",
        "email_template": "title_reminder.html",
        "include_preferred_vendors": False,
    },
}

INTELLIGENT_NUDGE_TASK_HINTS = {
    "inspection_not_scheduled": ("schedule home inspection", "follow up on inspection not scheduled"),
    "earnest_not_received": ("verify earnest money receipt", "follow up on earnest not received"),
    "appraisal_not_ordered": ("verify appraisal completed", "follow up on appraisal not ordered"),
    "hoa_docs_not_received": ("get hoa documents", "follow up on hoa docs not received"),
    "survey_not_ordered": ("get survey", "follow up on survey not ordered"),
    "title_not_received": ("get title commitment", "follow up on title not received"),
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
    "%Y-%m-%d",
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

CONTRACT_EXTRACTION_FIELDS = (
    ("effective_date", "Effective Date", "date"),
    ("closing_date", "Closing Date", "date"),
    ("buyer_name", "Buyer Name(s)", "text"),
    ("seller_name", "Seller Name(s)", "text"),
    ("property_address", "Property Address", "textarea"),
)


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
    """Download contract, run triple extraction, and persist confidence results."""
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

        method1_data = extract_via_ocr(temp_path)
        method2_data = extract_via_pypdf(temp_path)
        method3_data = extract_via_pdfplumber(temp_path)
        comparison = compare_extractions(method1_data, method2_data, method3_data)
        save_contract_extraction_results(transaction_id, comparison)

        preferred_effective = parse_contract_date((comparison.get("effective_date") or {}).get("value"))
        preferred_closing = parse_contract_date((comparison.get("closing_date") or {}).get("value"))
        preferred_buyer = normalize_extraction_value("buyer_name", (comparison.get("buyer_name") or {}).get("value"))
        preferred_seller = normalize_extraction_value("seller_name", (comparison.get("seller_name") or {}).get("value"))
        preferred_property = normalize_extraction_value(
            "property_address",
            (comparison.get("property_address") or {}).get("value"),
        )

        extracted_fields = {
            "effective_date": preferred_effective,
            "closing_date": preferred_closing,
            "buyer_names": preferred_buyer,
            "seller_names": preferred_seller,
            "property_address": preferred_property,
        }
        raw_text = (
            (method1_data.get("_raw_text") or "")
            or (method2_data.get("_raw_text") or "")
            or (method3_data.get("_raw_text") or "")
        )
        anthropic_api_key = (os.getenv("ANTHROPIC_API_KEY") or "").strip()
        if anthropic_api_key and raw_text:
            claude_result = extract_via_anthropic(raw_text, anthropic_api_key)
            claude_raw = (claude_result.get("raw_response") or "").strip()
            if claude_raw:
                raw_text = f"{raw_text}\n\n--- OPTIONAL CLAUDE PARSE ---\n{claude_raw[:1200]}"
        extraction_errors = [method1_data.get("_error"), method2_data.get("_error"), method3_data.get("_error")]
        extraction_errors = [error for error in extraction_errors if error]
        has_any_value = any((comparison.get(field_name) or {}).get("value") for field_name, _, _ in CONTRACT_EXTRACTION_FIELDS)
        save_extracted_contract_data(
            transaction_id=transaction_id,
            submitted_property_address=submitted_property_address,
            extracted_fields=extracted_fields,
            status="success" if has_any_value else "failed",
            error_message=(" | ".join(extraction_errors)[:500] if extraction_errors and not has_any_value else None),
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


def ensure_contract_extractions_table():
    """Ensure triple-scan contract extraction table exists."""
    execute_query(
        """
        CREATE TABLE IF NOT EXISTS contract_extractions (
            id SERIAL PRIMARY KEY,
            transaction_id INT REFERENCES transactions(id) ON DELETE CASCADE,
            field_name VARCHAR(50) NOT NULL,
            extracted_value TEXT,
            confidence VARCHAR(10),
            agreement VARCHAR(10),
            method1_value TEXT,
            method2_value TEXT,
            method3_value TEXT,
            manually_verified BOOLEAN DEFAULT FALSE,
            verified_value TEXT,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
        """
    )
    execute_query(
        """
        CREATE UNIQUE INDEX IF NOT EXISTS idx_contract_extractions_txn_field
        ON contract_extractions(transaction_id, field_name)
        """
    )


def extraction_field_meta_map():
    """Return field metadata keyed by extraction field name."""
    return {field_name: {"label": label, "input_type": input_type} for field_name, label, input_type in CONTRACT_EXTRACTION_FIELDS}


def normalize_extraction_value(field_name, raw_value):
    """Normalize extracted/verified values for DB and form handling."""
    if raw_value is None:
        return ""
    if isinstance(raw_value, date):
        return raw_value.isoformat()

    value = str(raw_value).strip()
    if not value:
        return ""

    if field_name in {"effective_date", "closing_date"}:
        parsed = parse_contract_date(value)
        return parsed.isoformat() if parsed else value
    return value


def save_contract_extraction_results(transaction_id, extraction_results):
    """Persist triple-scan extraction outcomes into contract_extractions."""
    ensure_contract_extractions_table()
    for field_name, _, _ in CONTRACT_EXTRACTION_FIELDS:
        field_result = extraction_results.get(field_name) or {}
        extracted_value = normalize_extraction_value(field_name, field_result.get("value"))
        confidence = (field_result.get("confidence") or "low").strip().lower()
        if confidence not in {"high", "low"}:
            confidence = "low"
        agreement = (field_result.get("agreement") or "0/3").strip()
        method1_value = normalize_extraction_value(field_name, field_result.get("method1_value"))
        method2_value = normalize_extraction_value(field_name, field_result.get("method2_value"))
        method3_value = normalize_extraction_value(field_name, field_result.get("method3_value"))

        execute_query(
            """
            INSERT INTO contract_extractions (
                transaction_id,
                field_name,
                extracted_value,
                confidence,
                agreement,
                method1_value,
                method2_value,
                method3_value,
                manually_verified,
                verified_value
            )
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s, FALSE, NULL)
            ON CONFLICT (transaction_id, field_name)
            DO UPDATE SET
                extracted_value = EXCLUDED.extracted_value,
                confidence = EXCLUDED.confidence,
                agreement = EXCLUDED.agreement,
                method1_value = EXCLUDED.method1_value,
                method2_value = EXCLUDED.method2_value,
                method3_value = EXCLUDED.method3_value,
                manually_verified = FALSE,
                verified_value = NULL
            """,
            (
                transaction_id,
                field_name,
                extracted_value or None,
                confidence,
                agreement,
                method1_value or None,
                method2_value or None,
                method3_value or None,
            ),
        )


def get_contract_extraction_rows(transaction_id):
    """Fetch contract_extractions rows for one transaction."""
    ensure_contract_extractions_table()
    return execute_query(
        """
        SELECT id, transaction_id, field_name, extracted_value, confidence, agreement,
               method1_value, method2_value, method3_value,
               manually_verified, verified_value, created_at
        FROM contract_extractions
        WHERE transaction_id = %s
        ORDER BY field_name ASC
        """,
        (transaction_id,),
        fetch=True,
    ) or []


def _fallback_extraction_value(field_name, extracted_data, transaction):
    """Fallback value source when contract_extractions row is unavailable."""
    if field_name == "effective_date":
        return extracted_data.get("confirmed_effective_date") or extracted_data.get("extracted_effective_date")
    if field_name == "closing_date":
        return extracted_data.get("confirmed_closing_date") or extracted_data.get("extracted_closing_date")
    if field_name == "buyer_name":
        return extracted_data.get("confirmed_buyer_names") or extracted_data.get("extracted_buyer_names")
    if field_name == "seller_name":
        return extracted_data.get("confirmed_seller_names") or extracted_data.get("extracted_seller_names")
    if field_name == "property_address":
        return (
            extracted_data.get("confirmed_property_address")
            or extracted_data.get("extracted_property_address")
            or extracted_data.get("submitted_property_address")
            or transaction.get("property_address")
        )
    return ""


def build_contract_extraction_review(transaction_id, extracted_data, transaction):
    """Build review payload for extraction confidence + verification UI."""
    field_meta = extraction_field_meta_map()
    row_lookup = {row.get("field_name"): row for row in get_contract_extraction_rows(transaction_id)}
    fields = []
    required_count = len(CONTRACT_EXTRACTION_FIELDS)
    verified_count = 0

    for field_name, _, _ in CONTRACT_EXTRACTION_FIELDS:
        row = row_lookup.get(field_name, {})
        suggested_value = normalize_extraction_value(field_name, row.get("extracted_value"))
        if not suggested_value:
            suggested_value = normalize_extraction_value(
                field_name,
                _fallback_extraction_value(field_name, extracted_data or {}, transaction),
            )

        verified_value = normalize_extraction_value(field_name, row.get("verified_value"))
        input_value = verified_value or suggested_value
        confidence = (row.get("confidence") or "low").strip().lower()
        if confidence not in {"high", "low"}:
            confidence = "low"
        agreement = (row.get("agreement") or "0/3").strip()
        method_values = [
            normalize_extraction_value(field_name, row.get("method1_value")),
            normalize_extraction_value(field_name, row.get("method2_value")),
            normalize_extraction_value(field_name, row.get("method3_value")),
        ]
        method_options = []
        for candidate in method_values:
            if candidate and candidate not in method_options:
                method_options.append(candidate)
        if suggested_value and suggested_value not in method_options:
            method_options.insert(0, suggested_value)

        manually_verified = bool(row.get("manually_verified")) and bool(verified_value)
        if manually_verified:
            verified_count += 1

        fields.append(
            {
                "field_name": field_name,
                "field_label": field_meta[field_name]["label"],
                "input_type": field_meta[field_name]["input_type"],
                "confidence": confidence,
                "agreement": agreement,
                "method1_value": method_values[0],
                "method2_value": method_values[1],
                "method3_value": method_values[2],
                "method_options": method_options,
                "suggested_value": suggested_value,
                "input_value": input_value,
                "manual_required": agreement in {"0/3", "1/3"} or not suggested_value,
                "is_high_confidence": confidence == "high" and agreement == "3/3" and bool(suggested_value),
                "manually_verified": manually_verified,
            }
        )

    return {
        "fields": fields,
        "all_verified": verified_count == required_count and required_count > 0,
        "verified_count": verified_count,
        "required_count": required_count,
    }


def get_verified_contract_extraction_values(transaction_id):
    """Return verified extraction values required for approval, if complete."""
    field_meta = extraction_field_meta_map()
    rows = get_contract_extraction_rows(transaction_id)
    row_lookup = {row.get("field_name"): row for row in rows}
    missing_fields = []
    values = {}

    for field_name, _, _ in CONTRACT_EXTRACTION_FIELDS:
        row = row_lookup.get(field_name)
        if not row or not row.get("manually_verified") or not (row.get("verified_value") or "").strip():
            missing_fields.append(field_meta[field_name]["label"])
            continue
        values[field_name] = normalize_extraction_value(field_name, row.get("verified_value"))

    if missing_fields:
        return None, missing_fields

    effective_date_value = parse_contract_date(values.get("effective_date"))
    closing_date_value = parse_contract_date(values.get("closing_date"))
    if not effective_date_value or not closing_date_value:
        return None, ["Effective Date", "Closing Date"]
    if closing_date_value < effective_date_value:
        return None, ["Closing Date cannot be before Effective Date"]

    return (
        {
            "effective_date": effective_date_value,
            "closing_date": closing_date_value,
            "buyer_name": values.get("buyer_name", "").strip(),
            "seller_name": values.get("seller_name", "").strip(),
            "property_address": values.get("property_address", "").strip(),
        },
        [],
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


@app.template_filter("format_issue_type")
def format_issue_type(issue_type):
    """Format machine issue keys into readable labels."""
    key = (issue_type or "").strip().replace("_", " ")
    return key.title() if key else "Issue"


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


def ensure_document_analysis_results_table():
    """Ensure document analysis storage exists."""
    execute_query(
        """
        CREATE TABLE IF NOT EXISTS document_analysis_results (
            id SERIAL PRIMARY KEY,
            document_id INT REFERENCES documents(id) ON DELETE CASCADE,
            transaction_id INT REFERENCES transactions(id) ON DELETE CASCADE,
            document_type VARCHAR(50),
            analysis_date TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            findings JSONB,
            action_items JSONB,
            margaret_reviewed BOOLEAN DEFAULT FALSE,
            reviewed_at TIMESTAMP,
            notes TEXT
        )
        """
    )
    execute_query(
        """
        CREATE INDEX IF NOT EXISTS idx_document_analysis_transaction
        ON document_analysis_results(transaction_id, analysis_date DESC)
        """
    )
    execute_query(
        """
        CREATE INDEX IF NOT EXISTS idx_document_analysis_document
        ON document_analysis_results(document_id)
        """
    )


def parse_json_field(raw_value, default_value):
    """Return parsed JSON field with fallback."""
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


def calculate_due_date(due_days):
    """Calculate a due date offset from today."""
    try:
        days = int(due_days)
    except (TypeError, ValueError):
        days = 7
    if days < 0:
        days = 0
    return date.today() + timedelta(days=days)


def create_analysis_task(transaction_id, description, priority="medium", due_days=7):
    """Create task from automated document analysis action item."""
    due_date = calculate_due_date(due_days)
    rows = execute_query(
        """
        INSERT INTO tasks (
            transaction_id, task_description, task_category, due_date,
            priority, status, completed, display_order, notes, created_at
        )
        VALUES (%s, %s, 'document_analysis', %s, %s, 'pending', FALSE, 999, %s, CURRENT_TIMESTAMP)
        RETURNING id
        """,
        (
            transaction_id,
            description,
            (priority or "medium").lower(),
            due_date,
            "Auto-created from document analysis",
        ),
        fetch=True,
    ) or []
    return rows[0]["id"] if rows else None


def save_analysis_results(document_id, transaction_id, document_type, findings, action_items):
    """Insert one analysis result row."""
    ensure_document_analysis_results_table()
    rows = execute_query(
        """
        INSERT INTO document_analysis_results (
            document_id, transaction_id, document_type, findings, action_items
        ) VALUES (%s, %s, %s, %s::jsonb, %s::jsonb)
        RETURNING id, analysis_date
        """,
        (
            document_id,
            transaction_id,
            document_type,
            json.dumps(findings or {}, default=str),
            json.dumps(action_items or [], default=str),
        ),
        fetch=True,
    ) or []
    return rows[0] if rows else None


def update_analysis_action_items(analysis_id, action_items):
    """Update action_items payload for analysis row."""
    ensure_document_analysis_results_table()
    execute_query(
        """
        UPDATE document_analysis_results
        SET action_items = %s::jsonb
        WHERE id = %s
        """,
        (json.dumps(action_items or [], default=str), analysis_id),
    )


def get_document_analysis_rows(transaction_id):
    """Return analysis rows for one transaction."""
    ensure_document_analysis_results_table()
    rows = execute_query(
        """
        SELECT
            dar.id,
            dar.document_id,
            dar.transaction_id,
            dar.document_type,
            dar.analysis_date,
            dar.findings,
            dar.action_items,
            dar.margaret_reviewed,
            dar.reviewed_at,
            dar.notes,
            d.filename,
            d.document_type AS uploaded_document_type,
            d.uploaded_at
        FROM document_analysis_results dar
        LEFT JOIN documents d ON d.id = dar.document_id
        WHERE dar.transaction_id = %s
        ORDER BY dar.analysis_date DESC, dar.id DESC
        """,
        (transaction_id,),
        fetch=True,
    ) or []

    for row in rows:
        row["findings"] = parse_json_field(row.get("findings"), {})
        row["action_items"] = parse_json_field(row.get("action_items"), [])
        row["analysis_date_label"] = format_timestamp_label(row.get("analysis_date"))
        row["reviewed_at_label"] = format_timestamp_label(row.get("reviewed_at"))
        row["uploaded_at_label"] = format_timestamp_label(row.get("uploaded_at"))
        row["document_label"] = document_type_label(row.get("document_type"))
    return rows


def execute_document_analysis_actions(transaction_id, analysis_type, action_items):
    """Execute alerts/tasks generated by analysis with smart notification thresholds."""
    executed_actions = []
    margaret_phone = normalize_phone(os.getenv("MARGARET_PHONE") or "")

    for action in action_items or []:
        action_type = (action.get("type") or "").strip().lower()
        executed_action = dict(action)
        executed_action["executed_at"] = datetime.utcnow().isoformat() + "Z"

        if action_type == "create_task":
            task_id = create_analysis_task(
                transaction_id=transaction_id,
                description=(action.get("task") or "Review document analysis finding").strip(),
                priority=(action.get("priority") or "medium"),
                due_days=action.get("due_days", 7),
            )
            executed_action["task_id"] = task_id
            executed_action["status"] = "created" if task_id else "failed"
            execute_query(
                """
                INSERT INTO communications (transaction_id, communication_type, contact_party, contact_name, summary, outcome)
                VALUES (%s, 'note', 'system', 'document_analysis', %s, %s)
                """,
                (
                    transaction_id,
                    f"Document analysis task action ({analysis_type})",
                    f"task={action.get('task')} task_id={task_id or 'failed'}",
                ),
            )
            executed_actions.append(executed_action)
            continue

        if action_type == "alert_margaret":
            message = (action.get("message") or "Document analysis alert").strip()
            immediate = bool(action.get("immediate"))
            sms_sid = None

            if immediate and margaret_phone:
                prefix = "🏢" if analysis_type == "hoa" else "🔍"
                sms_sid = send_sms(margaret_phone, f"{prefix} {message} - Transaction #{transaction_id}")
                executed_action["sms_sid"] = sms_sid or "failed"
                executed_action["status"] = "sms_sent" if sms_sid else "sms_failed"
            else:
                task_id = create_analysis_task(
                    transaction_id=transaction_id,
                    description=f"Review analysis alert: {message}",
                    priority=action.get("priority", "medium"),
                    due_days=0,
                )
                executed_action["task_id"] = task_id
                executed_action["status"] = "added_to_daily_checklist" if task_id else "failed"
            execute_query(
                """
                INSERT INTO communications (transaction_id, communication_type, contact_party, contact_name, summary, outcome)
                VALUES (%s, 'text', 'system', 'margaret', %s, %s)
                """,
                (
                    transaction_id,
                    f"Document analysis alert ({analysis_type})",
                    f"message={message} immediate={immediate} sms_sid={sms_sid or 'n/a'} task_id={executed_action.get('task_id') or 'n/a'}",
                ),
            )
            executed_actions.append(executed_action)
            continue

        executed_action["status"] = "ignored"
        executed_actions.append(executed_action)

    return executed_actions


def get_transaction_contract_price(transaction_id):
    """Fetch optional transaction contract_price when column exists."""
    has_column_rows = execute_query(
        """
        SELECT 1
        FROM information_schema.columns
        WHERE table_name = 'transactions'
          AND column_name = 'contract_price'
        LIMIT 1
        """,
        fetch=True,
    ) or []
    if not has_column_rows:
        return None

    value_rows = execute_query(
        """
        SELECT contract_price
        FROM transactions
        WHERE id = %s
        LIMIT 1
        """,
        (transaction_id,),
        fetch=True,
    ) or []
    if not value_rows:
        return None
    value = value_rows[0].get("contract_price")
    try:
        return float(value) if value is not None else None
    except (TypeError, ValueError):
        return None


def run_document_analysis(document_id, transaction_id, document_type, s3_key, extension):
    """Analyze HOA/inspection docs and persist findings."""
    normalized_type = (document_type or "").strip().lower()
    analysis_type = None
    if normalized_type in HOA_ANALYSIS_DOCUMENT_TYPES:
        analysis_type = "hoa"
    elif normalized_type in INSPECTION_ANALYSIS_DOCUMENT_TYPES:
        analysis_type = "inspection"
    elif normalized_type in APPRAISAL_ANALYSIS_DOCUMENT_TYPES:
        analysis_type = "appraisal"
    if not analysis_type:
        return

    if (extension or "").lower() != "pdf":
        findings = {
            "error": "Automated analysis currently supports PDF uploads only.",
            "confidence_summary": {"high": 0, "medium": 0, "low": 0},
            "action_items": [],
        }
        save_analysis_results(document_id, transaction_id, analysis_type, findings, [])
        return

    temp_path = None
    try:
        with tempfile.NamedTemporaryFile(suffix=".pdf", delete=False) as tmp_file:
            temp_path = tmp_file.name

        if not download_file(s3_key, temp_path):
            findings = {
                "error": "Could not download document from S3 for analysis.",
                "confidence_summary": {"high": 0, "medium": 0, "low": 0},
                "action_items": [],
            }
            save_analysis_results(document_id, transaction_id, analysis_type, findings, [])
            return

        if analysis_type == "hoa":
            findings = analyze_hoa_documents(temp_path)
        elif analysis_type == "inspection":
            findings = analyze_inspection_report(temp_path)
        else:
            findings = analyze_appraisal(
                temp_path,
                contract_price=get_transaction_contract_price(transaction_id),
            )
        action_items = findings.get("action_items") or []
        saved_row = save_analysis_results(
            document_id=document_id,
            transaction_id=transaction_id,
            document_type=analysis_type,
            findings=findings,
            action_items=action_items,
        )
        if not saved_row:
            return

        execute_query(
            """
            INSERT INTO communications (transaction_id, communication_type, contact_party, contact_name, summary, outcome)
            VALUES (%s, 'note', 'system', 'document_analysis', %s, %s)
            """,
            (
                transaction_id,
                f"Document analyzed ({analysis_type})",
                f"document_id={document_id} analysis_id={saved_row['id']} action_items={len(action_items)}",
            ),
        )

        executed_actions = execute_document_analysis_actions(transaction_id, analysis_type, action_items)
        update_analysis_action_items(saved_row["id"], executed_actions)
        if analysis_type in {"inspection", "appraisal"}:
            has_repair_related_task = any(
                (action.get("type") or "").strip().lower() == "create_task"
                and "repair" in ((action.get("task") or "").lower())
                for action in action_items
            )
            if has_repair_related_task:
                maybe_dispatch_timeline_update_for_repairs(transaction_id)
    except Exception as exc:
        print(f"Document analysis error (txn#{transaction_id}, doc#{document_id}): {exc}")
        findings = {
            "error": str(exc),
            "confidence_summary": {"high": 0, "medium": 0, "low": 0},
            "action_items": [],
        }
        save_analysis_results(document_id, transaction_id, analysis_type or normalized_type or "unknown", findings, [])
    finally:
        if temp_path and os.path.exists(temp_path):
            try:
                os.remove(temp_path)
            except OSError:
                pass


def run_document_analysis_async(document_id, transaction_id, document_type, s3_key, extension):
    """Dispatch document analysis in a background thread."""

    def _run():
        try:
            run_document_analysis(document_id, transaction_id, document_type, s3_key, extension)
        except Exception as exc:
            print(f"Async document analysis error (txn#{transaction_id}, doc#{document_id}): {exc}")

    Thread(target=_run, daemon=True).start()


def _transaction_column_exists(column_name):
    """Return whether a transactions column exists."""
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


def complete_tasks_for_document_event(transaction_id, description_fragments, note_line, completed_by="document-smart-processor"):
    """Complete pending tasks that match one or more description fragments."""
    completed_ids = []
    for fragment in description_fragments or []:
        snippet = (fragment or "").strip().lower()
        if len(snippet) < 3:
            continue
        rows = execute_query(
            """
            SELECT id
            FROM tasks
            WHERE transaction_id = %s
              AND completed = FALSE
              AND COALESCE(status, 'pending') <> 'completed'
              AND LOWER(COALESCE(task_description, '')) LIKE %s
            ORDER BY due_date ASC NULLS LAST, id ASC
            LIMIT 1
            """,
            (transaction_id, f"%{snippet}%"),
            fetch=True,
        ) or []
        if not rows:
            continue
        task_id = rows[0]["id"]
        if task_id in completed_ids:
            continue
        execute_query(
            """
            UPDATE tasks
            SET completed = TRUE,
                status = 'completed',
                completed_at = CURRENT_TIMESTAMP,
                completed_by = %s
            WHERE id = %s
            """,
            ((completed_by or "document-smart-processor")[:100], task_id),
        )
        append_task_note(task_id, note_line)
        completed_ids.append(task_id)
    return completed_ids


def apply_document_post_upload_actions(
    transaction_id,
    document_type,
    first_page_text,
    key_info_extracted,
    uploaded_by="margaret",
):
    """Apply smart action hooks based on detected document type."""
    normalized_type = normalize_document_type(document_type, fallback="other")
    actor = (uploaded_by or "margaret")[:100]
    summary_bits = []
    completed_task_ids = []

    if normalized_type == "inspection_report":
        completed_task_ids = complete_tasks_for_document_event(
            transaction_id=transaction_id,
            description_fragments=["get inspection report", "upload inspection report"],
            note_line="Auto-completed from smart document processing: inspection report uploaded.",
            completed_by=actor,
        )
        summary_bits.append(f"inspection_tasks_completed={len(completed_task_ids)}")

    elif normalized_type == "earnest_receipt":
        amount = extract_earnest_amount(first_page_text, key_info_extracted=key_info_extracted)
        completed_task_ids = complete_tasks_for_document_event(
            transaction_id=transaction_id,
            description_fragments=["verify earnest money receipt", "earnest money receipt"],
            note_line="Auto-completed from smart document processing: earnest receipt uploaded.",
            completed_by=actor,
        )
        execute_query(
            """
            UPDATE deadlines
            SET completed = TRUE,
                completed_at = COALESCE(completed_at, CURRENT_TIMESTAMP)
            WHERE transaction_id = %s
              AND deadline_type = 'earnest_money'
              AND completed = FALSE
            """,
            (transaction_id,),
        )
        if amount is not None and _transaction_column_exists("earnest_amount"):
            execute_query(
                """
                UPDATE transactions
                SET earnest_amount = %s,
                    updated_at = CURRENT_TIMESTAMP
                WHERE id = %s
                """,
                (amount, transaction_id),
            )
        if _transaction_column_exists("earnest_received"):
            execute_query(
                """
                UPDATE transactions
                SET earnest_received = TRUE,
                    updated_at = CURRENT_TIMESTAMP
                WHERE id = %s
                """,
                (transaction_id,),
            )
        if amount is not None:
            summary_bits.append(f"earnest_amount={amount:.2f}")
        summary_bits.append(f"earnest_tasks_completed={len(completed_task_ids)}")

    elif normalized_type == "title_commitment":
        completed_task_ids = complete_tasks_for_document_event(
            transaction_id=transaction_id,
            description_fragments=["get title commitment", "verify title opened"],
            note_line="Auto-completed from smart document processing: title commitment uploaded.",
            completed_by=actor,
        )
        summary_bits.append(f"title_tasks_completed={len(completed_task_ids)}")

    elif normalized_type == "survey":
        completed_task_ids = complete_tasks_for_document_event(
            transaction_id=transaction_id,
            description_fragments=["get survey", "request survey from seller"],
            note_line="Auto-completed from smart document processing: survey uploaded.",
            completed_by=actor,
        )
        summary_bits.append(f"survey_tasks_completed={len(completed_task_ids)}")

    elif normalized_type == "hoa_docs":
        completed_task_ids = complete_tasks_for_document_event(
            transaction_id=transaction_id,
            description_fragments=["get hoa documents", "order hoa documents if applicable"],
            note_line="Auto-completed from smart document processing: HOA docs uploaded.",
            completed_by=actor,
        )
        summary_bits.append(f"hoa_tasks_completed={len(completed_task_ids)}")

    elif normalized_type == "appraisal":
        completed_task_ids = complete_tasks_for_document_event(
            transaction_id=transaction_id,
            description_fragments=["verify appraisal completed"],
            note_line="Auto-completed from smart document processing: appraisal uploaded.",
            completed_by=actor,
        )
        summary_bits.append(f"appraisal_tasks_completed={len(completed_task_ids)}")

    elif normalized_type == "loan_approval":
        completed_task_ids = complete_tasks_for_document_event(
            transaction_id=transaction_id,
            description_fragments=["get loan approval letter"],
            note_line="Auto-completed from smart document processing: loan approval uploaded.",
            completed_by=actor,
        )
        summary_bits.append(f"loan_tasks_completed={len(completed_task_ids)}")

    elif normalized_type == "insurance_binder":
        completed_task_ids = complete_tasks_for_document_event(
            transaction_id=transaction_id,
            description_fragments=["verify insurance binder received by lender"],
            note_line="Auto-completed from smart document processing: insurance binder uploaded.",
            completed_by=actor,
        )
        summary_bits.append(f"insurance_tasks_completed={len(completed_task_ids)}")

    elif normalized_type == "settlement_statement":
        completed_task_ids = complete_tasks_for_document_event(
            transaction_id=transaction_id,
            description_fragments=["get final settlement statement"],
            note_line="Auto-completed from smart document processing: settlement statement uploaded.",
            completed_by=actor,
        )
        summary_bits.append(f"settlement_tasks_completed={len(completed_task_ids)}")

    return {
        "document_type": normalized_type,
        "completed_task_ids": completed_task_ids,
        "summary": " ".join(summary_bits).strip(),
    }


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


def ensure_timeline_packets_table():
    """Store latest generated timeline packet metadata/signature per transaction."""
    execute_query(
        """
        CREATE TABLE IF NOT EXISTS timeline_packets (
            id SERIAL PRIMARY KEY,
            transaction_id INT UNIQUE REFERENCES transactions(id) ON DELETE CASCADE,
            timeline_s3_key VARCHAR(500),
            timeline_filename VARCHAR(255),
            timeline_signature VARCHAR(128),
            timeline_snapshot JSONB,
            sent_recipients JSONB,
            last_trigger VARCHAR(64),
            generated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            last_sent_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
        """
    )
    execute_query(
        """
        CREATE UNIQUE INDEX IF NOT EXISTS idx_timeline_packets_transaction
        ON timeline_packets(transaction_id)
        """
    )


def ensure_vendor_outreach_table():
    """Track outbound vendor scheduling requests and response status."""
    execute_query(
        """
        CREATE TABLE IF NOT EXISTS vendor_outreach (
            id SERIAL PRIMARY KEY,
            transaction_id INT REFERENCES transactions(id) ON DELETE CASCADE,
            vendor_type VARCHAR(30) NOT NULL,
            vendor_name VARCHAR(255),
            vendor_email VARCHAR(255) NOT NULL,
            outreach_token UUID UNIQUE NOT NULL,
            sent_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            responded_at TIMESTAMP,
            response_status VARCHAR(30),
            appointment_at TIMESTAMP,
            appointment_notes TEXT,
            related_task_id INT REFERENCES tasks(id) ON DELETE SET NULL,
            followup_task_id INT REFERENCES tasks(id) ON DELETE SET NULL,
            last_message_id VARCHAR(255),
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
        """
    )
    execute_query(
        """
        CREATE INDEX IF NOT EXISTS idx_vendor_outreach_transaction
        ON vendor_outreach(transaction_id, vendor_type, sent_at DESC)
        """
    )
    execute_query(
        """
        CREATE UNIQUE INDEX IF NOT EXISTS idx_vendor_outreach_token
        ON vendor_outreach(outreach_token)
        """
    )


def ensure_calendar_events_table():
    """Store vendor-confirmed appointments created from outreach links."""
    execute_query(
        """
        CREATE TABLE IF NOT EXISTS calendar_events (
            id SERIAL PRIMARY KEY,
            transaction_id INT REFERENCES transactions(id) ON DELETE CASCADE,
            vendor_outreach_id INT REFERENCES vendor_outreach(id) ON DELETE SET NULL,
            event_type VARCHAR(50),
            title VARCHAR(255) NOT NULL,
            starts_at TIMESTAMP,
            ends_at TIMESTAMP,
            details TEXT,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
        """
    )
    execute_query(
        """
        CREATE INDEX IF NOT EXISTS idx_calendar_events_transaction
        ON calendar_events(transaction_id, starts_at DESC)
        """
    )


def ensure_timeline_automation_tables():
    """Ensure timeline packet and vendor outreach tables exist."""
    ensure_timeline_packets_table()
    ensure_vendor_outreach_table()
    ensure_calendar_events_table()
    ensure_calendar_sync_tables()
    ensure_vendor_automation_tables()


def log_system_error(component, error_text, transaction_id=None):
    """Persist operational errors for later review without breaking UX flows."""
    safe_component = (component or "system").strip()[:80] or "system"
    safe_error = (error_text or "unknown error").strip()[:1800]
    print(f"[{safe_component}] {safe_error}")
    if transaction_id:
        execute_query(
            """
            INSERT INTO communications (transaction_id, communication_type, contact_party, contact_name, summary, outcome)
            VALUES (%s, 'note', 'system', %s, 'Automation warning', %s)
            """,
            (transaction_id, safe_component, safe_error),
        )


def voice_note_webhook_secret_valid():
    """Validate optional shared secret for Twilio voice webhook requests."""
    configured_secret = (os.getenv("VOICE_NOTE_WEBHOOK_SECRET") or "").strip()
    if not configured_secret:
        return True
    provided = (
        request.headers.get("X-Voice-Secret")
        or request.headers.get("X-Webhook-Secret")
        or request.args.get("secret")
        or request.form.get("secret")
        or ""
    ).strip()
    return provided == configured_secret


def build_voice_note_webhook_url(stage=None):
    """Build absolute callback URLs for Twilio voice note actions."""
    params = {}
    if stage:
        params["stage"] = stage
    configured_secret = (os.getenv("VOICE_NOTE_WEBHOOK_SECRET") or "").strip()
    if configured_secret:
        params["secret"] = configured_secret
    base_url = url_for("voice_note_webhook", _external=True)
    if not params:
        return base_url
    return f"{base_url}?{urlencode(params)}"


def inbound_email_domain():
    """Resolve domain used for transaction inbound mailbox aliases."""
    configured = (os.getenv("INBOUND_EMAIL_DOMAIN") or "getmaverick.com").strip().lower()
    return configured.lstrip("@")


def transaction_inbound_aliases(transaction_id):
    """Build unique buyer/seller/lender mailbox addresses for one transaction."""
    safe_id = int(transaction_id)
    domain = inbound_email_domain()
    return {
        role: f"transaction-{safe_id}-{role}@{domain}"
        for role in INBOUND_MAILBOX_ROLES
    }


def ensure_inbound_email_messages_table():
    """Store inbound message analysis/routing decisions per transaction."""
    execute_query(
        """
        CREATE TABLE IF NOT EXISTS inbound_email_messages (
            id SERIAL PRIMARY KEY,
            transaction_id INT REFERENCES transactions(id) ON DELETE CASCADE,
            mailbox_role VARCHAR(20) NOT NULL,
            mailbox_address VARCHAR(255) NOT NULL,
            sender_email VARCHAR(255) NOT NULL,
            sender_role VARCHAR(50) NOT NULL,
            subject TEXT,
            body_text TEXT,
            urgency VARCHAR(20),
            category VARCHAR(50),
            action_required BOOLEAN DEFAULT FALSE,
            sensitive_content BOOLEAN DEFAULT FALSE,
            at_risk BOOLEAN DEFAULT FALSE,
            recommended_route VARCHAR(30),
            applied_route VARCHAR(30),
            forwarded_to JSONB,
            sms_sent BOOLEAN DEFAULT FALSE,
            task_id INT REFERENCES tasks(id) ON DELETE SET NULL,
            status_notes TEXT,
            provider_message_id VARCHAR(255),
            provider_payload JSONB,
            qa_match_id INT REFERENCES common_qa(id) ON DELETE SET NULL,
            qa_similarity DECIMAL(6,4),
            qa_confidence DECIMAL(5,2),
            qa_decision VARCHAR(30),
            qa_answer_text TEXT,
            qa_used BOOLEAN DEFAULT FALSE,
            qa_used_at TIMESTAMP,
            qa_variant_created BOOLEAN DEFAULT FALSE,
            reply_message_id VARCHAR(255),
            replied_at TIMESTAMP,
            override_route VARCHAR(30),
            override_notes TEXT,
            override_by VARCHAR(100),
            override_at TIMESTAMP,
            received_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
        """
    )
    # Backfill new Q&A columns for already-provisioned databases.
    execute_query("ALTER TABLE inbound_email_messages ADD COLUMN IF NOT EXISTS qa_match_id INT REFERENCES common_qa(id) ON DELETE SET NULL")
    execute_query("ALTER TABLE inbound_email_messages ADD COLUMN IF NOT EXISTS qa_similarity DECIMAL(6,4)")
    execute_query("ALTER TABLE inbound_email_messages ADD COLUMN IF NOT EXISTS qa_confidence DECIMAL(5,2)")
    execute_query("ALTER TABLE inbound_email_messages ADD COLUMN IF NOT EXISTS qa_decision VARCHAR(30)")
    execute_query("ALTER TABLE inbound_email_messages ADD COLUMN IF NOT EXISTS qa_answer_text TEXT")
    execute_query("ALTER TABLE inbound_email_messages ADD COLUMN IF NOT EXISTS qa_used BOOLEAN DEFAULT FALSE")
    execute_query("ALTER TABLE inbound_email_messages ADD COLUMN IF NOT EXISTS qa_used_at TIMESTAMP")
    execute_query("ALTER TABLE inbound_email_messages ADD COLUMN IF NOT EXISTS qa_variant_created BOOLEAN DEFAULT FALSE")
    execute_query("ALTER TABLE inbound_email_messages ADD COLUMN IF NOT EXISTS reply_message_id VARCHAR(255)")
    execute_query("ALTER TABLE inbound_email_messages ADD COLUMN IF NOT EXISTS replied_at TIMESTAMP")
    execute_query(
        """
        CREATE INDEX IF NOT EXISTS idx_inbound_email_messages_transaction
        ON inbound_email_messages(transaction_id, received_at DESC)
        """
    )
    execute_query(
        """
        CREATE INDEX IF NOT EXISTS idx_inbound_email_messages_qa
        ON inbound_email_messages(qa_decision, qa_match_id, received_at DESC)
        """
    )


def ensure_inbound_email_rules_table():
    """Store per-transaction sender-role routing preferences."""
    execute_query(
        """
        CREATE TABLE IF NOT EXISTS inbound_email_rules (
            id SERIAL PRIMARY KEY,
            transaction_id INT REFERENCES transactions(id) ON DELETE CASCADE,
            sender_role VARCHAR(50) NOT NULL,
            always_notify_margaret BOOLEAN DEFAULT FALSE,
            forward_policy VARCHAR(20) DEFAULT 'default',
            updated_by VARCHAR(100),
            updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
        """
    )
    execute_query(
        """
        CREATE UNIQUE INDEX IF NOT EXISTS idx_inbound_email_rules_txn_role
        ON inbound_email_rules(transaction_id, sender_role)
        """
    )


def ensure_transaction_risk_flags_table():
    """Track transaction-level risk signals from sensitive communications."""
    execute_query(
        """
        CREATE TABLE IF NOT EXISTS transaction_risk_flags (
            id SERIAL PRIMARY KEY,
            transaction_id INT UNIQUE REFERENCES transactions(id) ON DELETE CASCADE,
            is_at_risk BOOLEAN DEFAULT TRUE,
            reason TEXT,
            latest_message_id INT REFERENCES inbound_email_messages(id) ON DELETE SET NULL,
            flagged_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            resolved_at TIMESTAMP,
            updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
        """
    )
    execute_query(
        """
        CREATE UNIQUE INDEX IF NOT EXISTS idx_transaction_risk_flags_txn
        ON transaction_risk_flags(transaction_id)
        """
    )


def ensure_inbound_email_tables():
    """Ensure inbound email ingestion/routing tables exist."""
    ensure_common_qa_tables()
    ensure_inbound_email_messages_table()
    ensure_inbound_email_rules_table()
    ensure_transaction_risk_flags_table()


def ensure_deadline_nudges_table():
    """Store proactive deadline nudges and response/escalation state."""
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
    execute_query(
        """
        CREATE UNIQUE INDEX IF NOT EXISTS idx_deadline_nudges_unique_cycle
        ON deadline_nudges(transaction_id, nudge_key, due_date, target_party)
        """
    )


def ensure_nudge_log_table():
    """Store intelligent nudge sends and response/escalation status."""
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
    """Persist Margaret's configurable nudge settings."""
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
    for nudge_type, defaults in INTELLIGENT_NUDGE_DEFAULTS.items():
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
                bool(defaults.get("include_preferred_vendors")),
            ),
        )


def ensure_nudge_agent_whitelist_table():
    """Store agent no-nudge whitelist entries."""
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


def ensure_intelligent_nudge_tables():
    """Ensure all intelligent nudge tables exist."""
    ensure_nudge_log_table()
    ensure_nudge_settings_table()
    ensure_nudge_agent_whitelist_table()


def nudge_type_label(nudge_type):
    """Return display label for nudge type key."""
    defaults = INTELLIGENT_NUDGE_DEFAULTS.get((nudge_type or "").strip(), {})
    return defaults.get("label") or (nudge_type or "").replace("_", " ").title()


def fetch_nudge_settings_rows():
    """Return nudge settings rows merged with defaults for UI."""
    ensure_nudge_settings_table()
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
            preferred_vendor_ids,
            updated_by,
            updated_at
        FROM nudge_settings
        ORDER BY nudge_type ASC
        """,
        fetch=True,
    ) or []
    by_type = {row["nudge_type"]: row for row in rows if row.get("nudge_type")}
    merged = []
    for nudge_type, defaults in INTELLIGENT_NUDGE_DEFAULTS.items():
        row = by_type.get(nudge_type, {})
        preferred_vendor_ids = row.get("preferred_vendor_ids") or []
        if isinstance(preferred_vendor_ids, str):
            preferred_vendor_ids = []
        merged.append(
            {
                "nudge_type": nudge_type,
                "label": defaults.get("label") or nudge_type.replace("_", " ").title(),
                "enabled": bool(row.get("enabled", True)),
                "lead_days": int(row.get("lead_days") or defaults["lead_days"]),
                "sms_template": (row.get("sms_template") or defaults["sms_template"]).strip(),
                "email_template": (row.get("email_template") or defaults["email_template"]).strip(),
                "custom_sms_message": (row.get("custom_sms_message") or "").strip(),
                "custom_email_message": (row.get("custom_email_message") or "").strip(),
                "include_preferred_vendors": bool(
                    row.get("include_preferred_vendors", defaults.get("include_preferred_vendors", False))
                ),
                "preferred_vendor_ids": preferred_vendor_ids if isinstance(preferred_vendor_ids, list) else [],
                "updated_by": row.get("updated_by") or "",
                "updated_at_label": format_timestamp_label(row.get("updated_at")),
            }
        )
    return merged


def fetch_nudge_settings_map():
    """Return compact nudge settings map keyed by nudge type."""
    settings_map = {}
    for row in fetch_nudge_settings_rows():
        settings_map[row["nudge_type"]] = row
    return settings_map


def upsert_nudge_setting(
    nudge_type,
    enabled=True,
    lead_days=5,
    sms_template="",
    email_template="",
    custom_sms_message="",
    custom_email_message="",
    include_preferred_vendors=False,
    preferred_vendor_ids=None,
    updated_by="margaret",
):
    """Create/update one nudge setting row."""
    if (nudge_type or "").strip() not in INTELLIGENT_NUDGE_DEFAULTS:
        return False
    safe_lead_days = max(1, min(21, int(lead_days or 5)))
    safe_vendor_ids = []
    for raw_value in preferred_vendor_ids or []:
        parsed_value = parse_optional_int(raw_value)
        if parsed_value is not None and parsed_value not in safe_vendor_ids:
            safe_vendor_ids.append(parsed_value)
    execute_query(
        """
        INSERT INTO nudge_settings (
            nudge_type, enabled, lead_days, sms_template, email_template,
            custom_sms_message, custom_email_message, include_preferred_vendors,
            preferred_vendor_ids, updated_by, updated_at
        )
        VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s::jsonb, %s, CURRENT_TIMESTAMP)
        ON CONFLICT (nudge_type)
        DO UPDATE SET
            enabled = EXCLUDED.enabled,
            lead_days = EXCLUDED.lead_days,
            sms_template = EXCLUDED.sms_template,
            email_template = EXCLUDED.email_template,
            custom_sms_message = EXCLUDED.custom_sms_message,
            custom_email_message = EXCLUDED.custom_email_message,
            include_preferred_vendors = EXCLUDED.include_preferred_vendors,
            preferred_vendor_ids = EXCLUDED.preferred_vendor_ids,
            updated_by = EXCLUDED.updated_by,
            updated_at = CURRENT_TIMESTAMP
        """,
        (
            nudge_type,
            bool(enabled),
            safe_lead_days,
            (sms_template or "").strip()[:200],
            (email_template or "").strip()[:200],
            (custom_sms_message or "").strip()[:2500] or None,
            (custom_email_message or "").strip()[:5000] or None,
            bool(include_preferred_vendors),
            json.dumps(safe_vendor_ids),
            (updated_by or "margaret")[:100],
        ),
    )
    return True


def fetch_nudge_whitelist_rows():
    """Return active whitelist rows for nudge settings UI."""
    ensure_nudge_agent_whitelist_table()
    return execute_query(
        """
        SELECT id, agent_name, agent_phone, agent_email, notes, active, created_at
        FROM nudge_agent_whitelist
        WHERE active = TRUE
        ORDER BY created_at DESC, id DESC
        """,
        fetch=True,
    ) or []


def upsert_nudge_whitelist_row(agent_name="", agent_phone="", agent_email="", notes="", updated_by="margaret"):
    """Add/update one whitelist row by phone/email."""
    ensure_nudge_agent_whitelist_table()
    normalized_phone = normalize_phone(agent_phone or "")
    normalized_email = normalize_email(agent_email or "")
    if not normalized_phone and not normalized_email:
        return False
    if normalized_phone:
        execute_query(
            """
            INSERT INTO nudge_agent_whitelist (
                agent_name, agent_phone, agent_email, notes, active, created_at, updated_at
            )
            VALUES (%s, %s, %s, %s, TRUE, CURRENT_TIMESTAMP, CURRENT_TIMESTAMP)
            ON CONFLICT (agent_phone)
            DO UPDATE SET
                agent_name = EXCLUDED.agent_name,
                agent_email = COALESCE(EXCLUDED.agent_email, nudge_agent_whitelist.agent_email),
                notes = EXCLUDED.notes,
                active = TRUE,
                updated_at = CURRENT_TIMESTAMP
            """,
            (
                (agent_name or "").strip()[:200] or None,
                normalized_phone,
                normalized_email or None,
                f"{(notes or '').strip()[:800]} (updated_by={updated_by})"[:900] or None,
            ),
        )
    if normalized_email:
        execute_query(
            """
            INSERT INTO nudge_agent_whitelist (
                agent_name, agent_phone, agent_email, notes, active, created_at, updated_at
            )
            VALUES (%s, %s, %s, %s, TRUE, CURRENT_TIMESTAMP, CURRENT_TIMESTAMP)
            ON CONFLICT (agent_email)
            DO UPDATE SET
                agent_name = EXCLUDED.agent_name,
                agent_phone = COALESCE(EXCLUDED.agent_phone, nudge_agent_whitelist.agent_phone),
                notes = EXCLUDED.notes,
                active = TRUE,
                updated_at = CURRENT_TIMESTAMP
            """,
            (
                (agent_name or "").strip()[:200] or None,
                normalized_phone or None,
                normalized_email or None,
                f"{(notes or '').strip()[:800]} (updated_by={updated_by})"[:900] or None,
            ),
        )
    return True


def delete_nudge_whitelist_row(whitelist_id):
    """Deactivate one whitelist row."""
    ensure_nudge_agent_whitelist_table()
    execute_query(
        """
        UPDATE nudge_agent_whitelist
        SET active = FALSE,
            updated_at = CURRENT_TIMESTAMP
        WHERE id = %s
        """,
        (whitelist_id,),
    )


def get_recent_nudge_by_phone(phone_number):
    """Fetch most recent unresolved nudge row for inbound phone."""
    ensure_nudge_log_table()
    last10 = phone_last10(phone_number)
    if not last10:
        return None
    rows = execute_query(
        """
        SELECT
            nl.id,
            nl.transaction_id,
            nl.deadline_id,
            nl.nudge_type,
            nl.sent_to,
            nl.sent_at,
            nl.response_received,
            nl.escalated_to_margaret,
            t.property_address,
            t.agent_name,
            t.agent_phone
        FROM nudge_log nl
        JOIN transactions t ON t.id = nl.transaction_id
        WHERE nl.response_received = FALSE
          AND nl.sent_at >= (CURRENT_TIMESTAMP - INTERVAL '10 days')
          AND (
                RIGHT(REGEXP_REPLACE(COALESCE(nl.sent_to, ''), '[^0-9]', '', 'g'), 10) = %s
             OR RIGHT(REGEXP_REPLACE(COALESCE(t.agent_phone, ''), '[^0-9]', '', 'g'), 10) = %s
          )
        ORDER BY nl.sent_at DESC
        LIMIT 1
        """,
        (last10, last10),
        fetch=True,
    ) or []
    return rows[0] if rows else None


def mark_nudge_log_responded(nudge_log_id):
    """Mark nudge response received."""
    execute_query(
        """
        UPDATE nudge_log
        SET response_received = TRUE,
            response_date = COALESCE(response_date, CURRENT_TIMESTAMP)
        WHERE id = %s
        """,
        (nudge_log_id,),
    )


def mark_nudge_log_escalated(nudge_log_id):
    """Mark nudge as escalated to Margaret."""
    execute_query(
        """
        UPDATE nudge_log
        SET escalated_to_margaret = TRUE
        WHERE id = %s
        """,
        (nudge_log_id,),
    )


def complete_task_for_nudge(transaction_id, nudge_type):
    """Complete matching task(s) once a positive nudge response is received."""
    hints = INTELLIGENT_NUDGE_TASK_HINTS.get((nudge_type or "").strip(), ())
    if not hints:
        return []
    completed_ids = []
    for hint in hints:
        rows = execute_query(
            """
            UPDATE tasks
            SET completed = TRUE,
                status = 'completed',
                completed_at = CURRENT_TIMESTAMP,
                completed_by = 'nudge_response',
                notes = CASE
                    WHEN COALESCE(notes, '') = '' THEN %s
                    ELSE notes || E'\n' || %s
                END
            WHERE transaction_id = %s
              AND completed = FALSE
              AND LOWER(COALESCE(task_description, '')) LIKE %s
            RETURNING id
            """,
            (
                "Auto-completed after positive nudge response.",
                "Auto-completed after positive nudge response.",
                transaction_id,
                f"%{hint.lower()}%",
            ),
            fetch=True,
        ) or []
        for row in rows:
            if row["id"] not in completed_ids:
                completed_ids.append(row["id"])
    return completed_ids


def phone_last10(value):
    """Return last 10 numeric digits from a phone-like value."""
    digits = re.sub(r"\D", "", value or "")
    if len(digits) < 10:
        return ""
    return digits[-10:]


def fetch_open_agent_nudge_by_phone(phone_number):
    """Fetch latest pending agent nudge by sender phone."""
    ensure_deadline_nudges_table()
    last10 = phone_last10(phone_number)
    if not last10:
        return None
    rows = execute_query(
        """
        SELECT dn.id, dn.transaction_id, dn.deadline_id, dn.task_id, dn.nudge_key,
               dn.deadline_type, dn.due_date, dn.target_party, dn.target_email, dn.target_phone,
               dn.message_text, dn.first_nudge_sent_at, dn.second_nudge_sent_at,
               dn.requested_margaret_help, dn.escalated_at, dn.status_notes,
               t.property_address, t.agent_name
        FROM deadline_nudges dn
        JOIN transactions t ON t.id = dn.transaction_id
        WHERE dn.target_party = 'agent'
          AND dn.response_received_at IS NULL
          AND dn.status = 'pending'
          AND RIGHT(REGEXP_REPLACE(COALESCE(dn.target_phone, t.agent_phone, ''), '[^0-9]', '', 'g'), 10) = %s
        ORDER BY COALESCE(dn.second_nudge_sent_at, dn.first_nudge_sent_at, dn.created_at) DESC
        LIMIT 1
        """,
        (last10,),
        fetch=True,
    ) or []
    return rows[0] if rows else None


def mark_deadline_nudge_response(nudge_id, response_text, response_channel="sms", requested_help=False):
    """Mark one proactive nudge as responded."""
    execute_query(
        """
        UPDATE deadline_nudges
        SET response_received_at = COALESCE(response_received_at, CURRENT_TIMESTAMP),
            response_channel = %s,
            response_text = %s,
            requested_margaret_help = requested_margaret_help OR %s,
            status = CASE
                WHEN status = 'escalated' THEN status
                ELSE 'responded'
            END,
            updated_at = CURRENT_TIMESTAMP
        WHERE id = %s
        """,
        (
            (response_channel or "sms")[:20],
            (response_text or "")[:1000] or None,
            bool(requested_help),
            nudge_id,
        ),
    )


def create_deadline_nudge_followup_task(transaction_id, description, notes=""):
    """Create one high-priority coordination task for Margaret follow-up."""
    safe_description = (description or "Follow up on deadline nudge").strip()[:280]
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

    rows = execute_query(
        """
        INSERT INTO tasks (
            transaction_id, task_description, task_category, due_date,
            priority, status, completed, display_order, notes, created_at
        )
        VALUES (%s, %s, 'coordination', %s, 'high', 'pending', FALSE, 64, %s, CURRENT_TIMESTAMP)
        RETURNING id
        """,
        (
            transaction_id,
            safe_description,
            date.today(),
            (notes or "Auto-created from proactive deadline nudge response."),
        ),
        fetch=True,
    ) or []
    return rows[0]["id"] if rows else None


def deadline_nudge_escalation_summary(nudge_row):
    """Default escalation summary by nudge key."""
    summary_map = {
        "option_period_inspection": "Follow up on inspection scheduling",
        "earnest_money_receipt": "Follow up on earnest money receipt",
        "appraisal_order": "Follow up with lender on appraisal order",
        "hoa_docs_request": "Follow up on HOA documents from seller",
        "repair_addendum": "Follow up on repair addendum submission",
    }
    key = (nudge_row.get("nudge_key") or "").strip().lower()
    if key in summary_map:
        return summary_map[key]
    deadline_label = (nudge_row.get("deadline_type") or "").replace("_", " ").title()
    return f"Follow up on {deadline_label or 'deadline'} progress"


def escalate_deadline_nudge_to_margaret(nudge_row, reason, notify_sms=False):
    """Escalate nudge to Margaret by creating checklist task + optional SMS."""
    if not nudge_row:
        return None
    if nudge_row.get("escalated_at") and nudge_row.get("escalation_task_id"):
        return nudge_row.get("escalation_task_id")

    transaction_id = nudge_row["transaction_id"]
    summary = deadline_nudge_escalation_summary(nudge_row)
    notes = f"{summary}. Reason: {(reason or 'Escalation requested')[:300]}"
    task_id = create_deadline_nudge_followup_task(
        transaction_id=transaction_id,
        description=summary,
        notes=notes,
    )
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
        (task_id, notes[:400], nudge_row["id"]),
    )
    execute_query(
        """
        INSERT INTO communications (transaction_id, communication_type, contact_party, contact_name, summary, outcome)
        VALUES (%s, 'note', 'system', 'deadline_nudge', %s, %s)
        """,
        (
            transaction_id,
            "Deadline nudge escalated to Margaret",
            f"nudge_id={nudge_row['id']} reason={reason} task_id={task_id or 'n/a'}",
        ),
    )
    if notify_sms:
        margaret_phone = normalize_phone(os.getenv("MARGARET_PHONE") or "")
        if margaret_phone:
            send_sms_async(
                margaret_phone,
                (
                    f"⚠️ Escalation requested for {nudge_row.get('property_address')}: "
                    f"{summary}. Reason: {reason}"
                )[:300],
            )
    return task_id


def build_inspector_recommendations_message():
    """Return inspector recommendation SMS payload after agent replies YES."""
    raw_value = (os.getenv("INSPECTOR_RECOMMENDATIONS") or "").strip()
    recommendations = []
    if raw_value:
        for chunk in raw_value.split(";"):
            item = chunk.strip()
            if item:
                recommendations.append(item)
    if not recommendations:
        recommendations = [
            "Lone Star Inspection Group | (214) 555-0130 | scheduling@lonestarinspect.com",
            "North Texas Home Inspectors | (817) 555-0194 | team@nthi.com",
            "Metro Property Inspection | (972) 555-0177 | appointments@metroinspect.com",
        ]
    lines = ["Great — here are inspector recommendations:"]
    for idx, item in enumerate(recommendations[:3], start=1):
        lines.append(f"{idx}) {item}")
    lines.append("Reply HELP if you want Margaret to coordinate introductions. - Maverick TC")
    return "\n".join(lines)


def fetch_inbound_email_rule(transaction_id, sender_role):
    """Fetch one sender-role rule row with defaults."""
    ensure_inbound_email_rules_table()
    normalized_role = (sender_role or "external").strip().lower()
    rows = execute_query(
        """
        SELECT id, transaction_id, sender_role, always_notify_margaret, forward_policy, updated_by, updated_at
        FROM inbound_email_rules
        WHERE transaction_id = %s
          AND sender_role = %s
        LIMIT 1
        """,
        (transaction_id, normalized_role),
        fetch=True,
    ) or []
    if rows:
        return rows[0]
    return {
        "sender_role": normalized_role,
        "always_notify_margaret": False,
        "forward_policy": "default",
    }


def fetch_inbound_email_rules_map(transaction_id):
    """Return routing-rule map for UI controls."""
    ensure_inbound_email_rules_table()
    rows = execute_query(
        """
        SELECT sender_role, always_notify_margaret, forward_policy
        FROM inbound_email_rules
        WHERE transaction_id = %s
        """,
        (transaction_id,),
        fetch=True,
    ) or []
    result = {
        role: {
            "always_notify_margaret": False,
            "forward_policy": "default",
        }
        for role in INBOUND_SENDER_ROLES
    }
    for row in rows:
        role = (row.get("sender_role") or "").strip().lower()
        if role in result:
            result[role] = {
                "always_notify_margaret": bool(row.get("always_notify_margaret")),
                "forward_policy": (row.get("forward_policy") or "default").strip().lower(),
            }
    return result


def upsert_inbound_email_rule(transaction_id, sender_role, always_notify_margaret=False, forward_policy="default"):
    """Create/update one sender-role routing rule."""
    ensure_inbound_email_rules_table()
    normalized_role = (sender_role or "").strip().lower()
    if normalized_role not in INBOUND_SENDER_ROLES:
        return False
    normalized_policy = (forward_policy or "default").strip().lower()
    if normalized_policy not in {"default", "all", "never"}:
        normalized_policy = "default"
    execute_query(
        """
        INSERT INTO inbound_email_rules (
            transaction_id, sender_role, always_notify_margaret, forward_policy, updated_by, updated_at
        )
        VALUES (%s, %s, %s, %s, %s, CURRENT_TIMESTAMP)
        ON CONFLICT (transaction_id, sender_role)
        DO UPDATE SET
            always_notify_margaret = EXCLUDED.always_notify_margaret,
            forward_policy = EXCLUDED.forward_policy,
            updated_by = EXCLUDED.updated_by,
            updated_at = CURRENT_TIMESTAMP
        """,
        (
            transaction_id,
            normalized_role,
            bool(always_notify_margaret),
            normalized_policy,
            session.get("tc_username", "margaret") if has_request_context() else "system",
        ),
    )
    return True


def fetch_transaction_risk_state(transaction_id):
    """Return current risk-flag state for transaction detail UI."""
    ensure_transaction_risk_flags_table()
    rows = execute_query(
        """
        SELECT id, transaction_id, is_at_risk, reason, latest_message_id, flagged_at, resolved_at, updated_at
        FROM transaction_risk_flags
        WHERE transaction_id = %s
        LIMIT 1
        """,
        (transaction_id,),
        fetch=True,
    ) or []
    if not rows:
        return {
            "is_at_risk": False,
            "reason": "",
            "flagged_at_label": "",
            "resolved_at_label": "",
        }
    row = rows[0]
    return {
        "is_at_risk": bool(row.get("is_at_risk")),
        "reason": row.get("reason") or "",
        "flagged_at_label": format_timestamp_label(row.get("flagged_at")),
        "resolved_at_label": format_timestamp_label(row.get("resolved_at")),
        "latest_message_id": row.get("latest_message_id"),
    }


def set_transaction_risk_state(transaction_id, is_at_risk, reason, latest_message_id=None):
    """Upsert risk state, including resolve timestamps when cleared."""
    ensure_transaction_risk_flags_table()
    execute_query(
        """
        INSERT INTO transaction_risk_flags (
            transaction_id, is_at_risk, reason, latest_message_id, flagged_at, resolved_at, updated_at
        )
        VALUES (
            %s, %s, %s, %s,
            CASE WHEN %s THEN CURRENT_TIMESTAMP ELSE NULL END,
            CASE WHEN %s THEN NULL ELSE CURRENT_TIMESTAMP END,
            CURRENT_TIMESTAMP
        )
        ON CONFLICT (transaction_id)
        DO UPDATE SET
            is_at_risk = EXCLUDED.is_at_risk,
            reason = EXCLUDED.reason,
            latest_message_id = COALESCE(EXCLUDED.latest_message_id, transaction_risk_flags.latest_message_id),
            flagged_at = CASE
                WHEN EXCLUDED.is_at_risk THEN COALESCE(transaction_risk_flags.flagged_at, CURRENT_TIMESTAMP)
                ELSE transaction_risk_flags.flagged_at
            END,
            resolved_at = CASE
                WHEN EXCLUDED.is_at_risk THEN NULL
                ELSE CURRENT_TIMESTAMP
            END,
            updated_at = CURRENT_TIMESTAMP
        """,
        (
            transaction_id,
            bool(is_at_risk),
            (reason or "").strip() or None,
            latest_message_id,
            bool(is_at_risk),
            bool(is_at_risk),
        ),
    )


def fetch_inbound_email_messages(transaction_id, limit=20):
    """Load recent inbound-email timeline rows for transaction detail view."""
    ensure_inbound_email_messages_table()
    rows = execute_query(
        """
        SELECT
            id,
            mailbox_role,
            mailbox_address,
            sender_email,
            sender_role,
            subject,
            body_text,
            urgency,
            category,
            action_required,
            sensitive_content,
            at_risk,
            recommended_route,
            applied_route,
            forwarded_to,
            sms_sent,
            task_id,
            status_notes,
            qa_match_id,
            qa_similarity,
            qa_confidence,
            qa_decision,
            qa_answer_text,
            qa_used,
            qa_used_at,
            qa_variant_created,
            reply_message_id,
            replied_at,
            override_route,
            override_notes,
            override_by,
            override_at,
            received_at
        FROM inbound_email_messages
        WHERE transaction_id = %s
        ORDER BY received_at DESC, id DESC
        LIMIT %s
        """,
        (transaction_id, limit),
        fetch=True,
    ) or []
    for row in rows:
        row["forwarded_to"] = parse_json_field(row.get("forwarded_to"), [])
        row["received_at_label"] = format_timestamp_label(row.get("received_at"))
        row["override_at_label"] = format_timestamp_label(row.get("override_at"))
        row["sender_role_label"] = (row.get("sender_role") or "").replace("_", " ").title()
        row["mailbox_role_label"] = (row.get("mailbox_role") or "").replace("_", " ").title()
        row["urgency_label"] = (row.get("urgency") or "low").title()
        row["category_label"] = (row.get("category") or "general").replace("_", " ").title()
        row["qa_decision_label"] = (row.get("qa_decision") or "none").replace("_", " ").title()
        row["qa_used_at_label"] = format_timestamp_label(row.get("qa_used_at"))
        row["replied_at_label"] = format_timestamp_label(row.get("replied_at"))
        row["qa_confidence_pct"] = float(row.get("qa_confidence") or 0.0)
        row["qa_similarity"] = float(row.get("qa_similarity") or 0.0)
    return rows


def fetch_inbound_email_message(transaction_id, message_id):
    """Fetch one inbound email row for override actions."""
    ensure_inbound_email_messages_table()
    rows = execute_query(
        """
        SELECT
            id,
            transaction_id,
            mailbox_role,
            mailbox_address,
            sender_email,
            sender_role,
            subject,
            body_text,
            urgency,
            category,
            action_required,
            sensitive_content,
            at_risk,
            recommended_route,
            applied_route,
            forwarded_to,
            sms_sent,
            task_id,
            status_notes,
            qa_match_id,
            qa_similarity,
            qa_confidence,
            qa_decision,
            qa_answer_text,
            qa_used,
            qa_used_at,
            qa_variant_created,
            reply_message_id,
            replied_at
        FROM inbound_email_messages
        WHERE transaction_id = %s
          AND id = %s
        LIMIT 1
        """,
        (transaction_id, message_id),
        fetch=True,
    ) or []
    if not rows:
        return None
    row = rows[0]
    row["forwarded_to"] = parse_json_field(row.get("forwarded_to"), [])
    row["qa_confidence_pct"] = float(row.get("qa_confidence") or 0.0)
    row["qa_similarity"] = float(row.get("qa_similarity") or 0.0)
    return row


def infer_inbound_sender_role(sender_email, transaction):
    """Infer sender role based on known transaction addresses and email patterns."""
    normalized_sender = normalize_email(sender_email)
    if not normalized_sender:
        return "external"

    if normalized_sender == normalize_email(transaction.get("agent_email")):
        return "agent"
    if normalized_sender == normalize_email(transaction.get("lender_email")):
        return "lender"
    if normalized_sender == normalize_email(transaction.get("title_officer_email")):
        return "title_company"

    client_email_map = fetch_client_email_map(transaction["id"])
    if normalized_sender == normalize_email(client_email_map.get("buyer")):
        return "buyer"
    if normalized_sender == normalize_email(client_email_map.get("seller")):
        return "seller"

    lower_sender = normalized_sender.lower()
    if "inspect" in lower_sender:
        return "inspector"
    if "apprais" in lower_sender:
        return "appraiser"
    if "survey" in lower_sender:
        return "survey"
    return "external"


def inbound_forward_email_map(transaction):
    """Resolve forwarding email addresses for known transaction parties."""
    client_email_map = fetch_client_email_map(transaction["id"])
    return {
        "buyer": normalize_email(client_email_map.get("buyer")),
        "seller": normalize_email(client_email_map.get("seller")),
        "agent": normalize_email(transaction.get("agent_email")),
        "lender": normalize_email(transaction.get("lender_email")),
        "title_company": normalize_email(transaction.get("title_officer_email")),
    }


def inbound_forward_roles_for_category(category):
    """Default relevant-party routing map for medium-priority updates."""
    normalized_category = (category or "general").strip().lower()
    if normalized_category == "inspection":
        return {"agent", "buyer", "seller"}
    if normalized_category == "appraisal":
        return {"agent", "lender", "buyer"}
    if normalized_category == "repairs":
        return {"agent", "buyer", "seller"}
    if normalized_category == "closing":
        return {"agent", "lender", "title_company", "buyer", "seller"}
    return {"agent"}


def resolve_inbound_route(analysis, rule_row):
    """Resolve route + Margaret notification intent from analysis + overrides."""
    urgency = (analysis.get("urgency") or "low").strip().lower()
    action_required = bool(analysis.get("action_required"))
    route = "log_only"
    if urgency == "high" and action_required:
        route = "high_action"
    elif urgency in {"medium", "high"} or action_required:
        route = "medium_awareness"

    normalized_policy = (rule_row.get("forward_policy") or "default").strip().lower()
    if normalized_policy == "never":
        route = "log_only"
    elif normalized_policy == "all" and route == "log_only":
        route = "medium_awareness"

    notify_margaret = bool(rule_row.get("always_notify_margaret")) or route == "high_action"
    if analysis.get("at_risk"):
        notify_margaret = True
    return route, notify_margaret


def build_inbound_forward_roles(route, category, sender_role, sensitive_content=False):
    """Determine recipient roles for forwarding decisions."""
    sender = (sender_role or "external").strip().lower()
    if route == "high_action":
        roles = {"buyer", "seller", "agent", "lender", "title_company"}
    elif route == "medium_awareness":
        roles = set(inbound_forward_roles_for_category(category))
    else:
        roles = set()

    if sender in roles:
        roles.discard(sender)
    if sender == "title":
        roles.discard("title_company")
    if sender == "title_company":
        roles.discard("title_company")
    if sensitive_content and sender == "buyer":
        roles.discard("seller")
    return sorted(roles)


def append_task_note(task_id, note_line):
    """Append one timestamped note line to an existing task."""
    if not task_id:
        return
    note_text = (note_line or "").strip()
    if not note_text:
        return
    stamped = f"[{datetime.now().strftime('%Y-%m-%d %H:%M')}] {note_text}"
    execute_query(
        """
        UPDATE tasks
        SET notes = CASE
            WHEN COALESCE(notes, '') = '' THEN %s
            ELSE notes || E'\n' || %s
        END
        WHERE id = %s
        """,
        (stamped, stamped, task_id),
    )


def update_appraisal_task_from_email(transaction_id, subject, body_text):
    """Mark appraisal verification task as in-progress when lender reports ordering."""
    rows = execute_query(
        """
        SELECT id
        FROM tasks
        WHERE transaction_id = %s
          AND LOWER(task_description) LIKE 'verify appraisal completed%%'
        ORDER BY id DESC
        LIMIT 1
        """,
        (transaction_id,),
        fetch=True,
    ) or []
    if not rows:
        return None
    task_id = rows[0]["id"]
    execute_query(
        """
        UPDATE tasks
        SET status = CASE
                WHEN completed = TRUE THEN status
                ELSE 'in_progress'
            END
        WHERE id = %s
        """,
        (task_id,),
    )
    append_task_note(
        task_id,
        f"Lender inbound update: {(subject or 'Appraisal update')[:160]} | {(body_text or '')[:220]}",
    )
    return task_id


def create_inbound_coordination_task(transaction_id, description, priority="medium", due_days=1, body_excerpt=""):
    """Create one coordination task from inbound routing actions."""
    due_days_int = 0
    try:
        due_days_int = int(due_days)
    except (TypeError, ValueError):
        due_days_int = 1
    due_days_int = max(due_days_int, 0)
    due_date = date.today() + timedelta(days=due_days_int)
    rows = execute_query(
        """
        INSERT INTO tasks (
            transaction_id, task_description, task_category, due_date,
            priority, status, completed, display_order, notes, created_at
        )
        VALUES (%s, %s, 'coordination', %s, %s, 'pending', FALSE, 62, %s, CURRENT_TIMESTAMP)
        RETURNING id
        """,
        (
            transaction_id,
            description[:300],
            (priority or "medium").lower(),
            f"Auto-created from inbound email routing.\n{(body_excerpt or '')[:420]}",
        ),
        fetch=True,
    ) or []
    return rows[0]["id"] if rows else None


def apply_inbound_task_effects(transaction_id, analysis, route, subject, body_text):
    """Apply task updates/creations for inbound message processing."""
    hint = (analysis.get("status_update_hint") or "").strip().lower()
    if hint == "appraisal_ordered":
        updated_task_id = update_appraisal_task_from_email(transaction_id, subject, body_text)
        return updated_task_id

    if route == "log_only":
        return None

    recommended_task = (analysis.get("recommended_task") or "").strip()
    if recommended_task:
        description = recommended_task
    else:
        category_label = (analysis.get("category") or "general").replace("_", " ").title()
        description = f"Review inbound {category_label} update: {(subject or 'No subject')[:120]}"

    priority = "high" if route == "high_action" else "medium"
    due_days = 0 if route == "high_action" else 1
    return create_inbound_coordination_task(
        transaction_id=transaction_id,
        description=description,
        priority=priority,
        due_days=due_days,
        body_excerpt=body_text,
    )


def inbound_email_excerpt(text, max_chars=800):
    """Normalize and trim inbound body text for storage/display."""
    cleaned = re.sub(r"\s+", " ", (text or "")).strip()
    if len(cleaned) <= max_chars:
        return cleaned
    return f"{cleaned[:max_chars].rstrip()}..."


def build_inbound_question_text(subject, body_text):
    """Canonicalized question text used for semantic Q&A matching."""
    subject_clean = re.sub(r"\s+", " ", str(subject or "").strip())
    body_clean = inbound_email_excerpt(body_text, max_chars=1400)
    if subject_clean and body_clean:
        return f"{subject_clean}\n{body_clean}"
    return subject_clean or body_clean


def send_common_qa_reply_email(transaction, to_email, original_subject, answer_text, auto_sent=False):
    """Send one common-Q&A reply email to inbound sender."""
    recipient = normalize_email(to_email)
    if not recipient or not is_email_valid(recipient):
        return None
    safe_subject = (original_subject or "Question").strip() or "Question"
    reply_subject = f"Re: {safe_subject}"
    html_body = render_template(
        "emails/common_qa_reply.html",
        property_address=transaction.get("property_address"),
        answer_text=re.sub(r"\s+", " ", str(answer_text or "").strip()),
        auto_sent=bool(auto_sent),
    )
    return send_html_email(to_email=recipient, subject=reply_subject, html_body=html_body)


def evaluate_inbound_common_qa(subject, body_text, asked_by_party):
    """Evaluate Q&A decision for one inbound question payload."""
    question_text = build_inbound_question_text(subject, body_text)
    category_hint = infer_common_qa_category(question_text)
    decision = evaluate_common_qa_decision(
        question_text=question_text,
        asked_by_party=asked_by_party,
        category_hint=category_hint,
    )
    return {
        "question_text": question_text,
        "category_hint": category_hint,
        "decision": decision.get("decision") or "none",
        "confidence": float(decision.get("confidence") or 0.0),
        "similarity": float(decision.get("similarity") or 0.0),
        "match": decision.get("match"),
    }


def send_inbound_forward_notifications(transaction, sender_email, sender_role, subject, body_text, analysis, recipient_roles):
    """Forward inbound email updates to selected parties and log outcomes."""
    email_map = inbound_forward_email_map(transaction)
    forwarded = []
    for role in recipient_roles:
        recipient_email = normalize_email(email_map.get(role))
        if not recipient_email or not is_email_valid(recipient_email):
            continue
        context = {
            "transaction_id": transaction["id"],
            "property_address": transaction.get("property_address"),
            "sender_email": sender_email,
            "sender_role_label": (sender_role or "external").replace("_", " ").title(),
            "subject": subject or "(No subject)",
            "body_excerpt": inbound_email_excerpt(body_text, max_chars=1000),
            "urgency": (analysis.get("urgency") or "low").title(),
            "category": (analysis.get("category") or "general").replace("_", " ").title(),
            "action_required": bool(analysis.get("action_required")),
        }
        html_body = render_template("emails/inbound_email_forward.html", data=context)
        message_id = send_html_email(
            to_email=recipient_email,
            subject=f"Maverick Inbound Update - {transaction.get('property_address')}",
            html_body=html_body,
        )
        execute_query(
            """
            INSERT INTO communications (transaction_id, communication_type, contact_party, contact_name, summary, outcome)
            VALUES (%s, 'email', %s, %s, %s, %s)
            """,
            (
                transaction["id"],
                role,
                role.replace("_", " ").title(),
                "Inbound email forwarded" if message_id else "Inbound email forward failed",
                f"to={recipient_email} sender={sender_email} message_id={message_id or 'failed'}",
            ),
        )
        if message_id:
            forwarded.append(
                {
                    "role": role,
                    "email": recipient_email,
                    "message_id": message_id,
                }
            )
    return forwarded


def process_inbound_email_message(
    transaction,
    mailbox_role,
    mailbox_address,
    sender_email,
    sender_role,
    subject,
    body_text,
    provider_message_id="",
    provider_payload=None,
):
    """Classify, route, log, and persist one inbound email event."""
    ensure_inbound_email_tables()
    analysis = classify_inbound_email(subject, body_text, sender_role=sender_role)
    rule = fetch_inbound_email_rule(transaction["id"], sender_role)
    route, notify_margaret = resolve_inbound_route(analysis, rule)
    qa_eval = evaluate_inbound_common_qa(
        subject=subject,
        body_text=body_text,
        asked_by_party=sender_role,
    )
    qa_match = qa_eval.get("match") or {}
    qa_match_id = qa_match.get("id")
    qa_similarity = float(qa_eval.get("similarity") or 0.0) if qa_match else None
    qa_confidence = float(qa_eval.get("confidence") or 0.0) if qa_match else None
    qa_decision = qa_eval.get("decision") or "none"
    qa_answer_text = (qa_match.get("answer_text") or "").strip() if qa_match else ""
    qa_used = False
    qa_variant_created = False
    reply_message_id = None
    replied_at = None

    if qa_match:
        log_common_qa_event(
            event_type="question_matched",
            common_qa_id=qa_match_id,
            transaction_id=transaction["id"],
            channel="email",
            asked_by_party=sender_role,
            question_text=qa_eval.get("question_text"),
            answer_text=qa_answer_text,
            similarity_score=qa_similarity,
            confidence_score=qa_confidence,
            auto_answer=(qa_decision == "auto_answer"),
        )
    else:
        log_common_qa_event(
            event_type="question_no_match",
            common_qa_id=None,
            transaction_id=transaction["id"],
            channel="email",
            asked_by_party=sender_role,
            question_text=qa_eval.get("question_text"),
            answer_text="",
            similarity_score=0,
            confidence_score=0,
            auto_answer=False,
        )

    if qa_decision == "auto_answer" and qa_answer_text and qa_match_id:
        reply_message_id = send_common_qa_reply_email(
            transaction=transaction,
            to_email=sender_email,
            original_subject=subject,
            answer_text=qa_answer_text,
            auto_sent=True,
        )
        if reply_message_id:
            replied_at = datetime.now()
            qa_used = True
            increment_common_qa_reuse(qa_match_id, increment_by=1)
            log_common_qa_event(
                event_type="auto_answer_sent",
                common_qa_id=qa_match_id,
                transaction_id=transaction["id"],
                channel="email",
                asked_by_party=sender_role,
                question_text=qa_eval.get("question_text"),
                answer_text=qa_answer_text,
                similarity_score=qa_similarity,
                confidence_score=qa_confidence,
                auto_answer=True,
            )
            execute_query(
                """
                INSERT INTO communications (transaction_id, communication_type, contact_party, contact_name, summary, outcome)
                VALUES (%s, 'email', %s, %s, %s, %s)
                """,
                (
                    transaction["id"],
                    sender_role,
                    sender_email,
                    "Auto-answer sent from common Q&A",
                    (
                        f"qa_id={qa_match_id} confidence={qa_confidence or 0:.2f}% "
                        f"message_id={reply_message_id}"
                    ),
                ),
            )
        else:
            # Delivery failed; downgrade to suggestion so Margaret can intervene.
            qa_decision = "suggest"
            notify_margaret = True

    if qa_decision == "suggest":
        notify_margaret = True

    recipient_roles = build_inbound_forward_roles(
        route=route,
        category=analysis.get("category"),
        sender_role=sender_role,
        sensitive_content=bool(analysis.get("sensitive_content")),
    )

    task_id = apply_inbound_task_effects(
        transaction_id=transaction["id"],
        analysis=analysis,
        route=route,
        subject=subject,
        body_text=body_text,
    )
    forwarded_to = send_inbound_forward_notifications(
        transaction=transaction,
        sender_email=sender_email,
        sender_role=sender_role,
        subject=subject,
        body_text=body_text,
        analysis=analysis,
        recipient_roles=recipient_roles,
    )
    sms_sent = False
    if notify_margaret:
        margaret_phone = normalize_phone(os.getenv("MARGARET_PHONE") or "")
        if margaret_phone:
            alert_message = (
                analysis.get("margaret_alert")
                or f"⚠️ {analysis.get('urgency', 'medium').title()} inbound email - {transaction.get('property_address')}"
            )
            if qa_decision == "suggest" and qa_answer_text and qa_confidence:
                alert_message = (
                    f"Q&A suggestion ({qa_confidence:.0f}%) ready for "
                    f"{transaction.get('property_address')}. Review inbound email in Maverick."
                )
            send_sms_async(margaret_phone, alert_message)
            sms_sent = True

    message_id = execute_insert(
        """
        INSERT INTO inbound_email_messages (
            transaction_id,
            mailbox_role,
            mailbox_address,
            sender_email,
            sender_role,
            subject,
            body_text,
            urgency,
            category,
            action_required,
            sensitive_content,
            at_risk,
            recommended_route,
            applied_route,
            forwarded_to,
            sms_sent,
            task_id,
            status_notes,
            provider_message_id,
            provider_payload,
            qa_match_id,
            qa_similarity,
            qa_confidence,
            qa_decision,
            qa_answer_text,
            qa_used,
            qa_used_at,
            qa_variant_created,
            reply_message_id,
            replied_at,
            received_at,
            updated_at
        )
        VALUES (
            %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s,
            %s, %s, %s::jsonb, %s, %s, %s, %s, %s::jsonb,
            %s, %s, %s, %s, %s, %s, %s, %s, %s, %s,
            CURRENT_TIMESTAMP, CURRENT_TIMESTAMP
        )
        RETURNING id
        """,
        (
            transaction["id"],
            mailbox_role,
            mailbox_address,
            sender_email,
            sender_role,
            (subject or "").strip() or "(No subject)",
            body_text or "",
            analysis.get("urgency") or "low",
            analysis.get("category") or "general",
            bool(analysis.get("action_required")),
            bool(analysis.get("sensitive_content")),
            bool(analysis.get("at_risk")),
            route,
            route,
            json.dumps(forwarded_to or [], default=str),
            sms_sent,
            task_id,
            (
                f"rule_notify={bool(rule.get('always_notify_margaret'))} "
                f"forward_policy={rule.get('forward_policy', 'default')} "
                f"qa_decision={qa_decision}"
            ),
            (provider_message_id or "").strip()[:255] or None,
            json.dumps(provider_payload or {}, default=str),
            qa_match_id,
            qa_similarity,
            qa_confidence,
            qa_decision,
            qa_answer_text or None,
            qa_used,
            (datetime.now() if qa_used else None),
            qa_variant_created,
            reply_message_id,
            replied_at,
        ),
    )

    if qa_match and qa_decision == "suggest":
        log_common_qa_event(
            event_type="suggested_answer_available",
            common_qa_id=qa_match_id,
            transaction_id=transaction["id"],
            channel="email",
            asked_by_party=sender_role,
            question_text=qa_eval.get("question_text"),
            answer_text=qa_answer_text,
            similarity_score=qa_similarity,
            confidence_score=qa_confidence,
            auto_answer=False,
        )

    execute_query(
        """
        INSERT INTO communications (transaction_id, communication_type, contact_party, contact_name, summary, outcome)
        VALUES (%s, 'email', %s, %s, %s, %s)
        """,
        (
            transaction["id"],
            sender_role,
            sender_email,
            f"Inbound email: {(subject or '(No subject)')[:160]}",
            (
                f"mailbox={mailbox_role} urgency={analysis.get('urgency')} "
                f"category={analysis.get('category')} route={route} "
                f"forwarded={len(forwarded_to)} sms_sent={sms_sent} task_id={task_id or 'n/a'} "
                f"qa_decision={qa_decision} qa_confidence={qa_confidence or 0:.2f}"
            ),
        ),
    )

    if analysis.get("at_risk"):
        set_transaction_risk_state(
            transaction_id=transaction["id"],
            is_at_risk=True,
            reason=analysis.get("margaret_alert") or "Sensitive inbound concern detected",
            latest_message_id=message_id,
        )

    return {
        "message_id": message_id,
        "analysis": analysis,
        "route": route,
        "forwarded_to": forwarded_to,
        "sms_sent": sms_sent,
        "task_id": task_id,
        "qa_decision": qa_decision,
        "qa_confidence": qa_confidence,
        "qa_match_id": qa_match_id,
        "qa_used": qa_used,
    }


def parse_vendor_datetime(raw_value):
    """Parse vendor appointment datetime from form input."""
    value = (raw_value or "").strip()
    if not value:
        return None
    for fmt in ("%Y-%m-%dT%H:%M", "%Y-%m-%d %H:%M", "%Y-%m-%dT%H:%M:%S"):
        try:
            return datetime.strptime(value, fmt)
        except ValueError:
            continue
    return None


def fetch_vendor_outreach_by_token(access_token):
    """Resolve vendor outreach row + transaction context by secure token."""
    ensure_vendor_outreach_table()
    rows = execute_query(
        """
        SELECT
            vo.id,
            vo.transaction_id,
            vo.vendor_type,
            vo.vendor_name,
            vo.vendor_email,
            vo.outreach_token::text AS outreach_token,
            vo.sent_at,
            vo.responded_at,
            vo.response_status,
            vo.appointment_at,
            vo.appointment_notes,
            vo.related_task_id,
            vo.followup_task_id,
            t.property_address,
            t.agent_name,
            t.rush_service
        FROM vendor_outreach vo
        JOIN transactions t ON t.id = vo.transaction_id
        WHERE vo.outreach_token::text = %s
        LIMIT 1
        """,
        ((access_token or "").strip(),),
        fetch=True,
    ) or []
    return rows[0] if rows else None


def complete_vendor_response_tasks(task_ids, appointment_at, notes):
    """Mark linked vendor coordination tasks complete after confirmation."""
    cleaned_ids = []
    for value in task_ids or []:
        try:
            task_id = int(value or 0)
        except (TypeError, ValueError):
            task_id = 0
        if task_id > 0 and task_id not in cleaned_ids:
            cleaned_ids.append(task_id)
    if not cleaned_ids:
        return []

    event_note = (
        f"Vendor confirmed appointment for {appointment_at.strftime('%b %d, %Y %I:%M %p')}"
        if isinstance(appointment_at, datetime)
        else "Vendor confirmed response via secure link."
    )
    if notes:
        event_note = f"{event_note} Notes: {notes}"
    updated_rows = []
    for task_id in cleaned_ids:
        rows = execute_query(
            """
            UPDATE tasks
            SET completed = TRUE,
                status = 'completed',
                completed_at = CURRENT_TIMESTAMP,
                completed_by = 'vendor-link',
                notes = CASE
                    WHEN COALESCE(notes, '') = '' THEN %s
                    ELSE notes || E'\n' || %s
                END
            WHERE id = %s
            RETURNING id
            """,
            (event_note, event_note, task_id),
            fetch=True,
        ) or []
        if rows:
            updated_rows.append(rows[0]["id"])
    return updated_rows


def fetch_timeline_transaction(transaction_id):
    """Fetch transaction fields required for timeline packet generation."""
    rows = execute_query(
        """
        SELECT
            id, status, rush_service, property_address,
            effective_date, closing_date,
            option_fee_due_date, earnest_due_date, seller_disclosure_due_date, survey_due_date,
            option_period_end_date, hoa_docs_due_date, buyer_hoa_review_end_date, title_commitment_due_date,
            financing_approval_date, buyer_title_objection_end_date,
            buyer_name, buyer_phone, seller_name, seller_phone,
            agent_name, agent_phone, agent_email,
            lender_name, lender_email, lender_phone,
            title_company, title_officer_name, title_officer_email, title_officer_phone,
            updated_at
        FROM transactions
        WHERE id = %s
        LIMIT 1
        """,
        (transaction_id,),
        fetch=True,
    ) or []
    return rows[0] if rows else None


def fetch_timeline_deadlines(transaction_id):
    """Return ordered deadline rows for timeline rendering."""
    return execute_query(
        """
        SELECT id, deadline_type, deadline_date, description, completed
        FROM deadlines
        WHERE transaction_id = %s
        ORDER BY deadline_date ASC, id ASC
        """,
        (transaction_id,),
        fetch=True,
    ) or []


def fetch_repair_timeline_tasks(transaction_id):
    """Return repair-related timeline tasks used for update signatures."""
    return execute_query(
        """
        SELECT id, task_description, due_date, completed, status
        FROM tasks
        WHERE transaction_id = %s
          AND (
                LOWER(task_description) LIKE '%%repair%%'
             OR LOWER(task_description) LIKE '%%appraisal%%shortfall%%'
          )
        ORDER BY due_date ASC NULLS LAST, id ASC
        """,
        (transaction_id,),
        fetch=True,
    ) or []


def build_timeline_snapshot(transaction, deadline_rows, repair_tasks):
    """Create deterministic snapshot payload used to detect major schedule changes."""
    major_deadline_map = {}
    deadline_map = {}
    for row in deadline_rows:
        deadline_type = (row.get("deadline_type") or "").strip().lower()
        deadline_value = row.get("deadline_date")
        iso_value = deadline_value.isoformat() if deadline_value else ""
        deadline_map[deadline_type] = iso_value
        if deadline_type in TIMELINE_MAJOR_DEADLINE_TYPES:
            major_deadline_map[deadline_type] = iso_value

    snapshot = {
        "effective_date": (
            transaction.get("effective_date").isoformat() if isinstance(transaction.get("effective_date"), date) else ""
        ),
        "closing_date": (
            transaction.get("closing_date").isoformat() if isinstance(transaction.get("closing_date"), date) else ""
        ),
        "major_deadlines": major_deadline_map,
        "all_deadlines": deadline_map,
        "repair_task_count": len(repair_tasks),
        "repair_task_descriptions": [row.get("task_description") or "" for row in repair_tasks],
    }
    return snapshot


def timeline_signature(snapshot):
    """Hash timeline snapshot so we only re-send when meaningful values change."""
    payload = json.dumps(snapshot, sort_keys=True, default=str)
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def infer_timeline_trigger(previous_snapshot, current_snapshot, requested_reason):
    """Classify why a timeline was re-sent for logging and subject lines."""
    if not previous_snapshot:
        return requested_reason or "approved"
    if (previous_snapshot.get("closing_date") or "") != (current_snapshot.get("closing_date") or ""):
        return "closing_date_changed"

    prev_major = previous_snapshot.get("major_deadlines") or {}
    curr_major = current_snapshot.get("major_deadlines") or {}
    for deadline_type in TIMELINE_MAJOR_DEADLINE_TYPES:
        if (prev_major.get(deadline_type) or "") != (curr_major.get(deadline_type) or ""):
            return "major_deadline_shift"

    prev_repairs = int(previous_snapshot.get("repair_task_count") or 0)
    curr_repairs = int(current_snapshot.get("repair_task_count") or 0)
    if curr_repairs > prev_repairs:
        return "repair_timeline_added"
    return requested_reason or "timeline_updated"


def fetch_timeline_packet_row(transaction_id):
    """Return current timeline packet metadata row."""
    ensure_timeline_packets_table()
    rows = execute_query(
        """
        SELECT id, transaction_id, timeline_s3_key, timeline_filename, timeline_signature,
               timeline_snapshot, sent_recipients, last_trigger, generated_at, last_sent_at, updated_at
        FROM timeline_packets
        WHERE transaction_id = %s
        LIMIT 1
        """,
        (transaction_id,),
        fetch=True,
    ) or []
    if not rows:
        return None
    row = rows[0]
    row["timeline_snapshot"] = parse_json_field(row.get("timeline_snapshot"), {})
    row["sent_recipients"] = parse_json_field(row.get("sent_recipients"), [])
    return row


def upsert_timeline_packet_row(transaction_id, s3_key, filename, signature, snapshot, sent_recipients, trigger_reason):
    """Persist latest timeline packet metadata for change detection and audit."""
    ensure_timeline_packets_table()
    execute_query(
        """
        INSERT INTO timeline_packets (
            transaction_id,
            timeline_s3_key,
            timeline_filename,
            timeline_signature,
            timeline_snapshot,
            sent_recipients,
            last_trigger,
            generated_at,
            last_sent_at,
            updated_at
        )
        VALUES (%s, %s, %s, %s, %s::jsonb, %s::jsonb, %s, CURRENT_TIMESTAMP, CURRENT_TIMESTAMP, CURRENT_TIMESTAMP)
        ON CONFLICT (transaction_id)
        DO UPDATE SET
            timeline_s3_key = EXCLUDED.timeline_s3_key,
            timeline_filename = EXCLUDED.timeline_filename,
            timeline_signature = EXCLUDED.timeline_signature,
            timeline_snapshot = EXCLUDED.timeline_snapshot,
            sent_recipients = EXCLUDED.sent_recipients,
            last_trigger = EXCLUDED.last_trigger,
            generated_at = CURRENT_TIMESTAMP,
            last_sent_at = CURRENT_TIMESTAMP,
            updated_at = CURRENT_TIMESTAMP
        """,
        (
            transaction_id,
            s3_key,
            filename,
            signature,
            json.dumps(snapshot or {}, default=str),
            json.dumps(sent_recipients or [], default=str),
            trigger_reason,
        ),
    )


def fetch_client_email_map(transaction_id):
    """Resolve buyer/seller emails from client access table."""
    email_map = {"buyer": "", "seller": ""}
    for access_row in fetch_client_access_rows(transaction_id):
        role = (access_row.get("client_type") or "").strip().lower()
        if role in email_map:
            email_map[role] = normalize_email(access_row.get("email"))
    return email_map


def fetch_client_portal_link_map(transaction_id):
    """Resolve buyer/seller client portal links by transaction role."""
    link_map = {"buyer": "", "seller": ""}
    for access_row in fetch_client_access_rows(transaction_id):
        role = (access_row.get("client_type") or "").strip().lower()
        access_token = (access_row.get("access_token") or "").strip()
        if role in link_map and access_token:
            link_map[role] = client_portal_link_for_token(access_token)
    return link_map


def ensure_primary_portal_link(transaction_id):
    """Return a stable portal upload link for timeline packet content."""
    buyer_access = upsert_client_access(transaction_id, "buyer", None)
    if buyer_access and buyer_access.get("access_token"):
        return client_portal_link_for_token(buyer_access["access_token"])
    seller_access = upsert_client_access(transaction_id, "seller", None)
    if seller_access and seller_access.get("access_token"):
        return client_portal_link_for_token(seller_access["access_token"])
    return ""


def _contact_line(name_value, email_value="", phone_value=""):
    """Format compact contact lines for PDF/email content."""
    parts = [piece for piece in [name_value, email_value, phone_value] if (piece or "").strip()]
    return " | ".join(parts) if parts else "N/A"


def timeline_service_level_label(transaction):
    """Readable service-level indicator shown in timeline packet."""
    return "Rush (priority handling)" if transaction.get("rush_service") else "Standard"


def build_timeline_pdf_payload(transaction, deadline_rows, portal_link, trigger_reason, buyer_email="", seller_email=""):
    """Build context payload consumed by the timeline PDF renderer."""
    payment_document_points = [
        "Earnest and option receipts should be uploaded as soon as funded.",
        "Loan approval and insurance binder should be finalized before closing week.",
        "Final settlement statement is reviewed immediately after closing.",
    ]
    inspection_appraisal_points = [
        "Inspection is typically coordinated during the first week after effective date.",
        "Appraisal timing depends on lender ordering and access readiness.",
        "If repair negotiations or appraisal shortfalls occur, Maverick issues update tasks immediately.",
    ]
    weekly_expectations = [
        "Week 1: Contract activation, earnest/option receipts, and initial coordination.",
        "Week 2: Inspection, disclosures, and survey/title milestones.",
        "Week 3+: Financing approval, pre-closing confirmations, and final logistics.",
        "Closing Week: Final walk-through, wire verification, and closing document readiness.",
    ]
    moving_checklist = [
        "Confirm utility transfer date at least 3 business days before closing.",
        "Schedule movers and packing support once closing risk is low.",
        "Set up USPS address forwarding and update key accounts.",
        "Prepare closing-day IDs, wire confirmations, and occupancy plans.",
    ]
    contacts = {
        "buyer": _contact_line(transaction.get("buyer_name"), buyer_email, transaction.get("buyer_phone")),
        "seller": _contact_line(transaction.get("seller_name"), seller_email, transaction.get("seller_phone")),
        "agent": _contact_line(transaction.get("agent_name"), transaction.get("agent_email"), transaction.get("agent_phone")),
        "lender": _contact_line(transaction.get("lender_name"), transaction.get("lender_email"), transaction.get("lender_phone")),
        "title": _contact_line(
            transaction.get("title_company") or transaction.get("title_officer_name"),
            transaction.get("title_officer_email"),
            transaction.get("title_officer_phone"),
        ),
        "margaret": _contact_line(
            "Margaret - Maverick TC",
            normalize_email(os.getenv("MARGARET_EMAIL")),
            normalize_phone(os.getenv("MARGARET_PHONE")),
        ),
    }
    return {
        "transaction_id": transaction["id"],
        "property_address": transaction.get("property_address"),
        "effective_date": transaction.get("effective_date"),
        "closing_date": transaction.get("closing_date"),
        "service_level": timeline_service_level_label(transaction),
        "generated_at": datetime.now(),
        "trigger_reason": trigger_reason,
        "deadlines": deadline_rows,
        "contacts": contacts,
        "upload_portal_link": portal_link,
        "weekly_expectations": weekly_expectations,
        "payment_document_points": payment_document_points,
        "inspection_appraisal_points": inspection_appraisal_points,
        "moving_checklist": moving_checklist,
    }


def generate_timeline_pdf_artifact(transaction, deadline_rows, trigger_reason, buyer_email="", seller_email=""):
    """Create timeline PDF, upload to S3, and track as a document row."""
    portal_link = ensure_primary_portal_link(transaction["id"])
    payload = build_timeline_pdf_payload(
        transaction=transaction,
        deadline_rows=deadline_rows,
        portal_link=portal_link,
        trigger_reason=trigger_reason,
        buyer_email=buyer_email,
        seller_email=seller_email,
    )
    temp_pdf_path = None
    try:
        with tempfile.NamedTemporaryFile(suffix=".pdf", delete=False) as tmp_file:
            temp_pdf_path = tmp_file.name
        build_timeline_pdf(temp_pdf_path, payload)
        pdf_bytes = b""
        with open(temp_pdf_path, "rb") as pdf_handle:
            pdf_bytes = pdf_handle.read()

        filename = f"timeline_packet_txn_{transaction['id']}_{datetime.now().strftime('%Y%m%d_%H%M')}.pdf"
        s3_key = upload_local_file(
            local_path=temp_pdf_path,
            transaction_id=transaction["id"],
            document_type="timeline_packet",
            filename=filename,
            content_type="application/pdf",
        )
        if not s3_key:
            return {"success": False, "error": "upload_failed"}

        document_id = execute_insert(
            """
            INSERT INTO documents (
                transaction_id, document_type, filename, s3_key, file_size, uploaded_by, uploaded_at
            ) VALUES (%s, 'timeline_packet', %s, %s, %s, %s, CURRENT_TIMESTAMP)
            RETURNING id
            """,
            (transaction["id"], filename, s3_key, len(pdf_bytes), "system_timeline"),
        )
        return {
            "success": True,
            "s3_key": s3_key,
            "filename": filename,
            "document_id": document_id,
            "pdf_bytes": pdf_bytes,
            "timeline_url": get_presigned_url(s3_key, expiration=60 * 60 * 24 * 7),
            "portal_link": portal_link,
            "payload": payload,
        }
    finally:
        if temp_pdf_path and os.path.exists(temp_pdf_path):
            try:
                os.remove(temp_pdf_path)
            except OSError:
                pass


def timeline_recipient_focus_points(role):
    """Audience-specific focus bullets for timeline emails."""
    role = (role or "").strip().lower()
    if role == "buyer":
        return [
            "Review option and inspection windows early to preserve negotiation flexibility.",
            "Confirm wiring and insurance details before closing week.",
            "Use your upload portal link to submit signed documents quickly.",
        ]
    if role == "seller":
        return [
            "Stay ahead of disclosure, survey, and repair-related requests.",
            "Coordinate showing/access windows for inspection and appraisal teams.",
            "Use the upload portal for signed amendments and supporting documents.",
        ]
    if role == "lender":
        return [
            "Financing-approval and closing milestones are highlighted in the attached packet.",
            "Notify Maverick immediately if underwriting timelines shift.",
            "Reply with any document gaps so Margaret can coordinate same-day.",
        ]
    if role == "title":
        return [
            "Title commitment and closing milestones are included in the packet.",
            "Please confirm file-open status and any curative items early.",
            "Reply if closing schedule windows need to be adjusted.",
        ]
    if role == "agent":
        return [
            "This packet includes all milestone deadlines and weekly client expectations.",
            "Use it to answer buyer/seller timing questions without manual timeline builds.",
            "Reply to this thread if contract terms or dates change.",
        ]
    return [
        "See attached timeline for complete milestone details.",
        "Reply with any schedule changes so Maverick can re-issue updates.",
    ]


def build_timeline_email_recipients(transaction, buyer_email="", seller_email=""):
    """Build email recipient list for timeline distribution."""
    email_map = fetch_client_email_map(transaction["id"])
    resolved_buyer_email = normalize_email(buyer_email) or email_map.get("buyer") or ""
    resolved_seller_email = normalize_email(seller_email) or email_map.get("seller") or ""

    return [
        {
            "role": "buyer",
            "name": transaction.get("buyer_name") or "Buyer",
            "email": resolved_buyer_email,
        },
        {
            "role": "seller",
            "name": transaction.get("seller_name") or "Seller",
            "email": resolved_seller_email,
        },
        {
            "role": "agent",
            "name": transaction.get("agent_name") or "Agent",
            "email": normalize_email(transaction.get("agent_email")),
        },
        {
            "role": "lender",
            "name": transaction.get("lender_name") or "Lender",
            "email": normalize_email(transaction.get("lender_email")),
        },
        {
            "role": "title",
            "name": transaction.get("title_company") or "Title Company",
            "email": normalize_email(transaction.get("title_officer_email")),
        },
    ]


def format_timeline_recipients_label(sent_recipients):
    """Format timeline recipient roles for transaction detail display."""
    preferred_order = ["buyer", "seller", "agent", "lender", "title"]
    preferred_labels = {
        "buyer": "Buyer",
        "seller": "Seller",
        "agent": "Agent",
        "lender": "Lender",
        "title": "Title",
    }

    if not isinstance(sent_recipients, list):
        return ", ".join(preferred_labels[role] for role in preferred_order)

    role_set = set()
    extra_labels = []
    for row in sent_recipients:
        role = (row.get("role") if isinstance(row, dict) else "").strip().lower()
        if not role:
            continue
        if role in preferred_labels:
            role_set.add(role)
        elif role not in extra_labels:
            extra_labels.append(role.replace("_", " ").title())

    ordered = [preferred_labels[role] for role in preferred_order if role in role_set]
    if not ordered and not extra_labels:
        return ", ".join(preferred_labels[role] for role in preferred_order)
    return ", ".join(ordered + extra_labels)


def send_timeline_packet_emails(transaction, timeline_artifact, trigger_reason, buyer_email="", seller_email=""):
    """Distribute timeline PDF to buyer/seller/agent/lender/title audiences."""
    property_address = transaction.get("property_address") or "your transaction"
    recipients = build_timeline_email_recipients(transaction, buyer_email=buyer_email, seller_email=seller_email)
    portal_links = fetch_client_portal_link_map(transaction["id"])
    sent_recipients = []

    is_update = trigger_reason not in {"approved", "manual_refresh"}
    subject_prefix = "Updated transaction timeline" if is_update else "Your transaction timeline"
    margaret_phone = normalize_phone(os.getenv("MARGARET_PHONE")) or ""
    margaret_email = normalize_email(os.getenv("MARGARET_EMAIL")) or ""
    timeline_attachment = [
        {
            "filename": timeline_artifact.get("filename") or "timeline_packet.pdf",
            "content_type": "application/pdf",
            "data": timeline_artifact.get("pdf_bytes"),
        }
    ]

    for recipient in recipients:
        role = recipient["role"]
        to_email = normalize_email(recipient.get("email"))
        contact_name = recipient.get("name") or role.title()
        if not to_email or not is_email_valid(to_email):
            execute_query(
                """
                INSERT INTO communications (transaction_id, communication_type, contact_party, contact_name, summary, outcome)
                VALUES (%s, 'email', %s, %s, %s, %s)
                """,
                (
                    transaction["id"],
                    role,
                    contact_name,
                    "Timeline packet email skipped (missing recipient email)",
                    f"trigger={trigger_reason}",
                ),
            )
            continue

        if role == "buyer":
            buyer_context = {
                "subject": f"Maverick TC - {subject_prefix.title()} - {property_address}",
                "buyer_name": contact_name,
                "property_address": property_address,
                "closing_date": transaction.get("closing_date"),
                "option_fee_due_date": transaction.get("option_fee_due_date"),
                "earnest_due_date": transaction.get("earnest_due_date"),
                "margaret_phone": margaret_phone or "our support line",
                "client_portal_url": portal_links.get("buyer") or timeline_artifact.get("portal_link") or "",
                "timeline_url": timeline_artifact.get("timeline_url") or "",
            }
            message_id = send_email(
                to=to_email,
                template="emails/timeline_buyer.html",
                data=buyer_context,
                reply_to=margaret_email or None,
                attachments=timeline_attachment,
            )
        else:
            template_context = {
                "recipient_name": contact_name,
                "recipient_role": role.title(),
                "property_address": property_address,
                "transaction_id": transaction["id"],
                "effective_date": format_date_label(transaction.get("effective_date")),
                "closing_date": format_date_label(transaction.get("closing_date")),
                "message_line": (
                    f"{subject_prefix} for {property_address} is ready! "
                    "This shows all important dates and deadlines. We'll send reminders as dates approach. "
                    "Questions? Reply to this email or call Margaret at "
                    f"{margaret_phone or 'our support line'}."
                ),
                "timeline_url": timeline_artifact.get("timeline_url"),
                "portal_link": timeline_artifact.get("timeline_url") or timeline_artifact.get("portal_link"),
                "focus_points": timeline_recipient_focus_points(role),
                "trigger_reason": trigger_reason.replace("_", " ").title(),
                "margaret_phone": margaret_phone,
                "margaret_email": margaret_email,
            }
            if has_request_context():
                html_body = render_template("emails/timeline_packet_notification.html", data=template_context)
            else:
                with app.app_context():
                    html_body = render_template("emails/timeline_packet_notification.html", data=template_context)

            message_id = send_html_email(
                to_email=to_email,
                subject=f"Maverick TC - {subject_prefix.title()} - {property_address}",
                html_body=html_body,
                attachments=timeline_attachment,
                reply_to=margaret_email or None,
            )
        execute_query(
            """
            INSERT INTO communications (transaction_id, communication_type, contact_party, contact_name, summary, outcome)
            VALUES (%s, 'email', %s, %s, %s, %s)
            """,
            (
                transaction["id"],
                role,
                contact_name,
                "Timeline packet email sent" if message_id else "Timeline packet email failed",
                f"to={to_email} trigger={trigger_reason} message_id={message_id or 'failed'}",
            ),
        )
        if message_id:
            sent_recipients.append({"role": role, "email": to_email, "name": contact_name, "message_id": message_id})

    return sent_recipients


def send_timeline_to_all_parties(
    transaction,
    timeline_url,
    trigger_reason="timeline_updated",
    buyer_email="",
    seller_email="",
    pdf_bytes=None,
    filename="timeline_packet.pdf",
):
    """Fallback timeline distribution flow used when packet dispatch fails."""
    recipients = build_timeline_email_recipients(transaction, buyer_email=buyer_email, seller_email=seller_email)
    portal_links = fetch_client_portal_link_map(transaction["id"])
    property_address = transaction.get("property_address") or "your transaction"
    margaret_phone = normalize_phone(os.getenv("MARGARET_PHONE")) or ""
    margaret_email = normalize_email(os.getenv("MARGARET_EMAIL")) or ""

    attachments = []
    if pdf_bytes:
        attachments = [{"filename": filename, "content_type": "application/pdf", "data": pdf_bytes}]
    elif timeline_url:
        attachments = [{"filename": filename, "content_type": "application/pdf", "url": timeline_url}]

    sent_recipients = []
    for recipient in recipients:
        role = recipient["role"]
        to_email = normalize_email(recipient.get("email"))
        contact_name = recipient.get("name") or role.title()
        if not to_email or not is_email_valid(to_email):
            continue

        if role == "buyer":
            buyer_context = {
                "subject": f"Maverick TC - Your transaction timeline - {property_address}",
                "buyer_name": contact_name,
                "property_address": property_address,
                "closing_date": transaction.get("closing_date"),
                "option_fee_due_date": transaction.get("option_fee_due_date"),
                "earnest_due_date": transaction.get("earnest_due_date"),
                "margaret_phone": margaret_phone or "our support line",
                "client_portal_url": portal_links.get("buyer") or timeline_url or "",
                "timeline_url": timeline_url or "",
            }
            message_id = send_email(
                to=to_email,
                template="emails/timeline_buyer.html",
                data=buyer_context,
                reply_to=margaret_email or None,
                attachments=attachments,
            )
        else:
            template_context = {
                "recipient_name": contact_name,
                "recipient_role": role.title(),
                "property_address": property_address,
                "transaction_id": transaction["id"],
                "effective_date": format_date_label(transaction.get("effective_date")),
                "closing_date": format_date_label(transaction.get("closing_date")),
                "message_line": (
                    f"Updated transaction timeline for {property_address} is ready. "
                    "Reply to this message if dates changed or support is needed."
                ),
                "timeline_url": timeline_url,
                "portal_link": timeline_url,
                "focus_points": timeline_recipient_focus_points(role),
                "trigger_reason": (trigger_reason or "timeline_updated").replace("_", " ").title(),
                "margaret_phone": margaret_phone,
                "margaret_email": margaret_email,
            }
            if has_request_context():
                html_body = render_template("emails/timeline_packet_notification.html", data=template_context)
            else:
                with app.app_context():
                    html_body = render_template("emails/timeline_packet_notification.html", data=template_context)

            message_id = send_html_email(
                to_email=to_email,
                subject=f"Maverick TC - Updated transaction timeline - {property_address}",
                html_body=html_body,
                attachments=attachments,
                reply_to=margaret_email or None,
            )

        execute_query(
            """
            INSERT INTO communications (transaction_id, communication_type, contact_party, contact_name, summary, outcome)
            VALUES (%s, 'email', %s, %s, %s, %s)
            """,
            (
                transaction["id"],
                role,
                contact_name,
                "Timeline fallback email sent" if message_id else "Timeline fallback email failed",
                f"to={to_email} trigger={trigger_reason} message_id={message_id or 'failed'}",
            ),
        )
        if message_id:
            sent_recipients.append({"role": role, "email": to_email, "name": contact_name, "message_id": message_id})
    return sent_recipients


def log_timeline_sent(transaction_id, timeline_s3_key, sent_recipients=None, trigger_reason="timeline_updated"):
    """Persist timeline packet metadata + communication log for generated timeline."""
    transaction = fetch_timeline_transaction(transaction_id)
    if not transaction:
        return False
    deadline_rows = fetch_timeline_deadlines(transaction_id)
    repair_tasks = fetch_repair_timeline_tasks(transaction_id)
    snapshot = build_timeline_snapshot(transaction, deadline_rows, repair_tasks)
    signature = timeline_signature(snapshot)
    filename = (timeline_s3_key or "").rsplit("/", 1)[-1] or f"timeline_{transaction_id}.pdf"

    upsert_timeline_packet_row(
        transaction_id=transaction_id,
        s3_key=timeline_s3_key,
        filename=filename,
        signature=signature,
        snapshot=snapshot,
        sent_recipients=sent_recipients or [],
        trigger_reason=trigger_reason,
    )
    execute_query(
        """
        INSERT INTO communications (transaction_id, communication_type, contact_party, contact_name, summary, outcome)
        VALUES (%s, 'note', 'system', 'timeline', %s, %s)
        """,
        (
            transaction_id,
            "Timeline generated and sent",
            f"trigger={trigger_reason} s3_key={timeline_s3_key} recipients={len(sent_recipients or [])}",
        ),
    )
    return True


def regenerate_and_resend_timeline(
    transaction_id,
    reason,
    force=False,
    buyer_email="",
    seller_email="",
    send_vendor_notifications=False,
):
    """
    Regenerate + resend transaction timeline.

    Primary path uses the existing timeline packet dispatcher.
    Fallback path uses utils.timeline_generator when packet dispatch fails.
    """
    trigger_reason = ((reason or "timeline_updated").strip().lower() or "timeline_updated").replace(" ", "_")
    dispatch_result = dispatch_timeline_packet(
        transaction_id=transaction_id,
        trigger_reason=trigger_reason,
        force=bool(force),
        buyer_email=buyer_email,
        seller_email=seller_email,
        send_vendor_requests=bool(send_vendor_notifications),
    )
    if dispatch_result.get("success"):
        return dispatch_result

    try:
        payload = generate_transaction_timeline_pdf_bytes(transaction_id)
        try:
            timeline_s3_key = upload_transaction_timeline_pdf(
                transaction_id=transaction_id,
                pdf_bytes=payload["pdf_bytes"],
                filename=payload["filename"],
            )
        except Exception:
            # Keep an explicit fallback path through the standalone generator.
            timeline_s3_key = generate_transaction_timeline_pdf(transaction_id)
        timeline_url = get_presigned_url(timeline_s3_key, expiration=60 * 60 * 24 * 7)
        transaction = fetch_timeline_transaction(transaction_id)
        if not transaction:
            return {
                "success": False,
                "error": "transaction_not_found",
                "primary_error": dispatch_result.get("error") or "dispatch_failed",
            }
        sent_recipients = send_timeline_to_all_parties(
            transaction=transaction,
            timeline_url=timeline_url,
            trigger_reason=trigger_reason,
            buyer_email=buyer_email,
            seller_email=seller_email,
            pdf_bytes=payload["pdf_bytes"],
            filename=payload["filename"],
        )
        log_timeline_sent(
            transaction_id=transaction_id,
            timeline_s3_key=timeline_s3_key,
            sent_recipients=sent_recipients,
            trigger_reason=trigger_reason,
        )
        return {
            "success": True,
            "fallback": True,
            "timeline_s3_key": timeline_s3_key,
            "timeline_url": timeline_url,
            "sent_recipients": sent_recipients,
            "trigger_reason": trigger_reason,
        }
    except Exception as fallback_exc:
        return {
            "success": False,
            "error": dispatch_result.get("error") or "timeline_regeneration_failed",
            "primary_error": dispatch_result.get("error") or "dispatch_failed",
            "fallback_error": str(fallback_exc),
        }


def create_vendor_coordination_task(transaction_id, vendor_type, property_address, rush_service=False):
    """Create vendor response confirmation task for outreach workflows."""
    task_descriptions = {
        "inspector": "Confirm inspection appointment with vendor",
        "appraiser": "Confirm appraiser access appointment with vendor",
        "survey": "Confirm survey scheduling with vendor",
        "title": "Confirm title file opened and closing appointment",
    }
    description = task_descriptions.get(vendor_type, "Confirm vendor scheduling update")
    due_days = 1 if rush_service else 2
    due_date = date.today() + timedelta(days=due_days)
    rows = execute_query(
        """
        INSERT INTO tasks (
            transaction_id, task_description, task_category, due_date,
            priority, status, completed, display_order, notes, created_at
        )
        VALUES (%s, %s, 'coordination', %s, %s, 'pending', FALSE, 45, %s, CURRENT_TIMESTAMP)
        RETURNING id
        """,
        (
            transaction_id,
            description,
            due_date,
            "high",
            f"Auto-created vendor outreach task for {vendor_type} on {property_address}",
        ),
        fetch=True,
    ) or []
    return rows[0]["id"] if rows else None


def build_vendor_catalog(transaction):
    """Build vendor outreach recipient entries from env + transaction metadata."""
    catalog = []
    vendor_rows = [
        {
            "vendor_type": "inspector",
            "vendor_name": (os.getenv("INSPECTOR_NAME") or "Inspection Team").strip(),
            "vendor_email": normalize_email(os.getenv("INSPECTOR_EMAIL")),
            "template_name": "emails/vendor_inspector_request.html",
            "calendly_url": (os.getenv("INSPECTOR_CALENDLY_URL") or "").strip(),
        },
        {
            "vendor_type": "appraiser",
            "vendor_name": (os.getenv("APPRAISER_NAME") or "Appraisal Team").strip(),
            "vendor_email": normalize_email(os.getenv("APPRAISER_EMAIL")),
            "template_name": "emails/vendor_appraiser_request.html",
            "calendly_url": (os.getenv("APPRAISER_CALENDLY_URL") or "").strip(),
        },
        {
            "vendor_type": "survey",
            "vendor_name": (os.getenv("SURVEY_COMPANY_NAME") or "Survey Team").strip(),
            "vendor_email": normalize_email(os.getenv("SURVEY_COMPANY_EMAIL")),
            "template_name": "emails/vendor_survey_request.html",
            "calendly_url": (os.getenv("SURVEY_CALENDLY_URL") or "").strip(),
        },
        {
            "vendor_type": "title",
            "vendor_name": (transaction.get("title_company") or os.getenv("TITLE_COORDINATION_NAME") or "Title Team").strip(),
            "vendor_email": (
                normalize_email(transaction.get("title_officer_email"))
                or normalize_email(os.getenv("TITLE_COORDINATION_EMAIL"))
            ),
            "template_name": "emails/vendor_title_file_notice.html",
            "calendly_url": (os.getenv("TITLE_CALENDLY_URL") or "").strip(),
        },
    ]
    for item in vendor_rows:
        if item["vendor_email"] and is_email_valid(item["vendor_email"]):
            catalog.append(item)
    return catalog


def create_vendor_outreach_record(transaction_id, vendor_type, vendor_name, vendor_email, related_task_id=None):
    """Insert one vendor outreach row and return the generated token."""
    ensure_vendor_outreach_table()
    rows = execute_query(
        """
        INSERT INTO vendor_outreach (
            transaction_id, vendor_type, vendor_name, vendor_email, outreach_token,
            related_task_id, sent_at, created_at, updated_at
        )
        VALUES (%s, %s, %s, %s, %s::uuid, %s, CURRENT_TIMESTAMP, CURRENT_TIMESTAMP, CURRENT_TIMESTAMP)
        RETURNING id, outreach_token::text AS outreach_token
        """,
        (transaction_id, vendor_type, vendor_name, vendor_email, str(uuid4()), related_task_id),
        fetch=True,
    ) or []
    return rows[0] if rows else None


def build_vendor_links(vendor_row, transaction):
    """Build scheduling and response links for vendor emails."""
    confirm_link = f"{app_base_url()}/vendor/outreach/{vendor_row['outreach_token']}"
    calendly_url = (vendor_row.get("calendly_url") or "").strip()
    if not calendly_url:
        return {"confirm_link": confirm_link, "scheduling_link": confirm_link}

    query = urlencode(
        {
            "a1": transaction.get("property_address") or "",
            "a2": f"TX-{transaction['id']}",
            "a3": "Rush" if transaction.get("rush_service") else "Standard",
            "a4": confirm_link,
        }
    )
    separator = "&" if "?" in calendly_url else "?"
    return {"confirm_link": confirm_link, "scheduling_link": f"{calendly_url}{separator}{query}"}


def send_vendor_outreach(transaction, timeline_artifact, trigger_reason):
    """Send scheduling request emails to inspector/appraiser/survey/title vendors."""
    catalog = build_vendor_catalog(transaction)
    if not catalog:
        return []

    sent = []
    for vendor in catalog:
        existing_rows = execute_query(
            """
            SELECT id
            FROM vendor_outreach
            WHERE transaction_id = %s
              AND vendor_type = %s
            ORDER BY sent_at DESC
            LIMIT 1
            """,
            (transaction["id"], vendor["vendor_type"]),
            fetch=True,
        ) or []
        if existing_rows and trigger_reason == "approved":
            continue

        related_task_id = create_vendor_coordination_task(
            transaction_id=transaction["id"],
            vendor_type=vendor["vendor_type"],
            property_address=transaction.get("property_address") or "this property",
            rush_service=bool(transaction.get("rush_service")),
        )
        outreach_row = create_vendor_outreach_record(
            transaction_id=transaction["id"],
            vendor_type=vendor["vendor_type"],
            vendor_name=vendor["vendor_name"],
            vendor_email=vendor["vendor_email"],
            related_task_id=related_task_id,
        )
        if not outreach_row:
            continue

        merged_vendor = dict(vendor)
        merged_vendor.update(outreach_row)
        links = build_vendor_links(merged_vendor, transaction)
        context = {
            "vendor_name": vendor["vendor_name"],
            "property_address": transaction.get("property_address"),
            "transaction_id": transaction["id"],
            "urgency_label": "RUSH - response requested within 24 hours"
            if transaction.get("rush_service")
            else "Standard - response requested within 24 hours",
            "scheduling_link": links["scheduling_link"],
            "confirm_link": links["confirm_link"],
            "timeline_url": timeline_artifact.get("timeline_url"),
            "portal_link": timeline_artifact.get("portal_link"),
            "margaret_email": normalize_email(os.getenv("MARGARET_EMAIL")),
            "margaret_phone": normalize_phone(os.getenv("MARGARET_PHONE")),
            "trigger_reason": trigger_reason.replace("_", " ").title(),
        }
        if has_request_context():
            html_body = render_template(vendor["template_name"], data=context)
        else:
            with app.app_context():
                html_body = render_template(vendor["template_name"], data=context)

        message_id = send_html_email(
            to_email=vendor["vendor_email"],
            subject=f"Maverick TC - {vendor['vendor_type'].title()} Coordination - {transaction.get('property_address')}",
            html_body=html_body,
        )
        execute_query(
            """
            UPDATE vendor_outreach
            SET last_message_id = %s,
                updated_at = CURRENT_TIMESTAMP
            WHERE id = %s
            """,
            (message_id or "failed", outreach_row["id"]),
        )
        execute_query(
            """
            INSERT INTO communications (transaction_id, communication_type, contact_party, contact_name, summary, outcome)
            VALUES (%s, 'email', %s, %s, %s, %s)
            """,
            (
                transaction["id"],
                vendor["vendor_type"],
                vendor["vendor_name"],
                "Vendor outreach email sent" if message_id else "Vendor outreach email failed",
                f"to={vendor['vendor_email']} message_id={message_id or 'failed'}",
            ),
        )
        if message_id:
            sent.append(
                {
                    "vendor_type": vendor["vendor_type"],
                    "vendor_email": vendor["vendor_email"],
                    "message_id": message_id,
                    "outreach_id": outreach_row["id"],
                }
            )
    return sent


def dispatch_timeline_packet(
    transaction_id,
    trigger_reason="timeline_updated",
    force=False,
    buyer_email="",
    seller_email="",
    send_vendor_requests=False,
):
    """Generate/send timeline packet and optionally vendor outreach notifications."""
    ensure_timeline_automation_tables()
    transaction = fetch_timeline_transaction(transaction_id)
    if not transaction:
        return {"success": False, "error": "transaction_not_found"}

    status = (transaction.get("status") or "").upper()
    if status not in {"ACTIVE", "COMPLETED"}:
        return {"success": False, "error": "transaction_not_active"}

    deadline_rows = fetch_timeline_deadlines(transaction_id)
    repair_tasks = fetch_repair_timeline_tasks(transaction_id)
    snapshot = build_timeline_snapshot(transaction, deadline_rows, repair_tasks)
    signature = timeline_signature(snapshot)
    current_packet = fetch_timeline_packet_row(transaction_id)
    previous_snapshot = (current_packet or {}).get("timeline_snapshot") or {}
    resolved_trigger = infer_timeline_trigger(previous_snapshot, snapshot, trigger_reason)

    if current_packet and current_packet.get("timeline_signature") == signature and not force:
        return {
            "success": True,
            "skipped": True,
            "reason": "no_changes",
            "trigger_reason": resolved_trigger,
            "timeline_s3_key": current_packet.get("timeline_s3_key"),
        }

    timeline_artifact = generate_timeline_pdf_artifact(
        transaction=transaction,
        deadline_rows=deadline_rows,
        trigger_reason=resolved_trigger,
        buyer_email=buyer_email,
        seller_email=seller_email,
    )
    if not timeline_artifact.get("success"):
        execute_query(
            """
            INSERT INTO communications (transaction_id, communication_type, contact_party, contact_name, summary, outcome)
            VALUES (%s, 'note', 'system', 'timeline', %s, %s)
            """,
            (
                transaction_id,
                "Timeline packet generation failed",
                f"reason={timeline_artifact.get('error')}",
            ),
        )
        return {"success": False, "error": timeline_artifact.get("error")}

    sent_recipients = send_timeline_packet_emails(
        transaction=transaction,
        timeline_artifact=timeline_artifact,
        trigger_reason=resolved_trigger,
        buyer_email=buyer_email,
        seller_email=seller_email,
    )
    vendor_results = []
    if send_vendor_requests:
        vendor_results = send_vendor_outreach(transaction, timeline_artifact, resolved_trigger)

    upsert_timeline_packet_row(
        transaction_id=transaction_id,
        s3_key=timeline_artifact.get("s3_key"),
        filename=timeline_artifact.get("filename"),
        signature=signature,
        snapshot=snapshot,
        sent_recipients=sent_recipients,
        trigger_reason=resolved_trigger,
    )

    execute_query(
        """
        INSERT INTO communications (transaction_id, communication_type, contact_party, contact_name, summary, outcome)
        VALUES (%s, 'note', 'system', 'timeline', %s, %s)
        """,
        (
            transaction_id,
            "Timeline packet generated and distributed",
            (
                f"trigger={resolved_trigger} recipients={len(sent_recipients)} "
                f"vendors_notified={len(vendor_results)} s3_key={timeline_artifact.get('s3_key')}"
            ),
        ),
    )
    return {
        "success": True,
        "skipped": False,
        "trigger_reason": resolved_trigger,
        "timeline_s3_key": timeline_artifact.get("s3_key"),
        "timeline_url": timeline_artifact.get("timeline_url"),
        "recipients_sent": sent_recipients,
        "vendors_sent": vendor_results,
    }


def ensure_vendor_followup_tasks():
    """Create 24h no-response follow-up tasks for vendor outreach records."""
    ensure_vendor_outreach_table()
    rows = execute_query(
        """
        SELECT vo.id, vo.transaction_id, vo.vendor_type, vo.vendor_name, vo.followup_task_id,
               t.property_address
        FROM vendor_outreach vo
        JOIN transactions t ON t.id = vo.transaction_id
        WHERE vo.responded_at IS NULL
          AND vo.followup_task_id IS NULL
          AND vo.sent_at <= (CURRENT_TIMESTAMP - INTERVAL '24 hours')
          AND t.status = 'ACTIVE'
        ORDER BY vo.sent_at ASC
        """,
        fetch=True,
    ) or []
    created_count = 0
    for row in rows:
        task_rows = execute_query(
            """
            INSERT INTO tasks (
                transaction_id, task_description, task_category, due_date,
                priority, status, completed, display_order, notes, created_at
            )
            VALUES (%s, %s, 'coordination', %s, 'high', 'pending', FALSE, 46, %s, CURRENT_TIMESTAMP)
            RETURNING id
            """,
            (
                row["transaction_id"],
                f"Follow up with {row.get('vendor_name') or row.get('vendor_type')} for appointment confirmation",
                date.today(),
                f"No vendor response within 24h for {row.get('property_address')}",
            ),
            fetch=True,
        ) or []
        if not task_rows:
            continue
        followup_task_id = task_rows[0]["id"]
        execute_query(
            """
            UPDATE vendor_outreach
            SET followup_task_id = %s,
                updated_at = CURRENT_TIMESTAMP
            WHERE id = %s
            """,
            (followup_task_id, row["id"]),
        )
        execute_query(
            """
            INSERT INTO communications (transaction_id, communication_type, contact_party, contact_name, summary, outcome)
            VALUES (%s, 'note', 'system', 'vendor_outreach', %s, %s)
            """,
            (
                row["transaction_id"],
                "Vendor follow-up task auto-created",
                f"vendor_type={row.get('vendor_type')} task_id={followup_task_id}",
            ),
        )
        created_count += 1
    return created_count


def auto_dispatch_timeline_updates(limit=40):
    """Auto-resend timeline packets when date/repair signatures shift."""
    ensure_timeline_packets_table()
    rows = execute_query(
        """
        SELECT t.id
        FROM transactions t
        JOIN timeline_packets tp ON tp.transaction_id = t.id
        WHERE t.status = 'ACTIVE'
        ORDER BY t.updated_at DESC
        LIMIT %s
        """,
        (limit,),
        fetch=True,
    ) or []
    sent_updates = 0
    for row in rows:
        result = regenerate_and_resend_timeline(
            transaction_id=row["id"],
            reason="timeline_updated",
            force=False,
            send_vendor_notifications=False,
        )
        if result.get("success") and not result.get("skipped"):
            sent_updates += 1
    return sent_updates


def maybe_dispatch_timeline_update_for_repairs(transaction_id):
    """Trigger non-blocking timeline update when repair timeline tasks are added."""
    try:
        regenerate_and_resend_timeline(
            transaction_id=transaction_id,
            reason="repair_timeline_added",
            force=False,
            send_vendor_notifications=False,
        )
    except Exception as exc:
        print(f"Repair timeline dispatch error (txn#{transaction_id}): {exc}")


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


def closing_checklist_status_label(status_value):
    """Readable status text for closing checklist rows."""
    status_text = (status_value or "").strip().replace("_", " ")
    return status_text.title() if status_text else "Pending Review"


def build_closing_checklist_sections(item_rows):
    """Group checklist items into ordered section blocks for templates."""
    grouped = {}
    section_order = []
    for item in item_rows or []:
        section = (item.get("section_title") or "General").strip()
        if section not in grouped:
            grouped[section] = []
            section_order.append(section)
        grouped[section].append(item)

    blocks = []
    for section in section_order:
        blocks.append(
            {
                "section_title": section,
                "items": grouped[section],
            }
        )
    return blocks


def closing_checklist_public_url(access_token):
    """Build external URL for public checklist recipient link."""
    if not access_token:
        return ""
    base_url = (os.getenv("APP_BASE_URL") or "").strip().rstrip("/")
    if base_url:
        return f"{base_url}/closing-checklist/{access_token}"
    if has_request_context():
        return url_for("public_closing_checklist", access_token=access_token, _external=True)
    return f"/closing-checklist/{access_token}"


def common_qa_variant_similarity_threshold():
    """Return minimum similarity to treat edited answer as same variant."""
    raw_value = (os.getenv("COMMON_QA_VARIANT_SIMILARITY_THRESHOLD") or "").strip()
    if not raw_value:
        return 0.82
    try:
        parsed = float(raw_value)
    except (TypeError, ValueError):
        return 0.82
    return max(0.3, min(parsed, 0.99))


def parse_optional_hhmm(raw_value):
    """Parse optional HH:MM value."""
    value = (raw_value or "").strip()
    if not value:
        return None
    try:
        parsed = datetime.strptime(value, "%H:%M")
        return parsed.strftime("%H:%M")
    except ValueError:
        return None


def combine_date_and_hhmm(target_date, hhmm_value, fallback_hhmm="09:00"):
    """Combine date with HH:MM string into datetime."""
    if not target_date:
        return None
    chosen_hhmm = parse_optional_hhmm(hhmm_value) or parse_optional_hhmm(fallback_hhmm) or "09:00"
    hour, minute = chosen_hhmm.split(":")
    return datetime.combine(target_date, time(int(hour), int(minute)))


def calendar_sync_event_type_for_vendor(vendor_type):
    normalized = normalize_vendor_type(vendor_type)
    if normalized == "inspector":
        return "inspection"
    if normalized == "appraiser":
        return "appraisal"
    return ""


def sync_vendor_appointment_to_calendar(
    transaction_id,
    vendor_type,
    appointment_at,
    vendor_name="",
    vendor_phone="",
    source_ref="",
    source_id=0,
    notes="",
):
    """Sync inspector/appraiser appointment to Google Calendar."""
    event_type = calendar_sync_event_type_for_vendor(vendor_type)
    if not event_type or not appointment_at:
        return {"success": False, "skipped": "unsupported_vendor_or_missing_time"}

    transaction = get_transaction_or_none(transaction_id)
    if not transaction:
        return {"success": False, "error": "transaction_not_found"}

    source_ref_value = source_ref or f"vendor:{normalize_vendor_type(vendor_type)}:{int(source_id or 0)}"
    event_data = {
        "property_address": transaction.get("property_address"),
        "buyer_name": transaction.get("buyer_name"),
        "contact_name": vendor_name or normalize_vendor_type(vendor_type).title(),
        "contact_phone": vendor_phone or "",
        "start_time": appointment_at,
        "end_time": appointment_at + timedelta(minutes=45),
        "duration_minutes": 45,
        "notes": notes,
        "source_ref": source_ref_value,
        "source_id": int(source_id or 0),
        "source_label": normalize_vendor_type(vendor_type).title(),
        "summary_prefix": event_type.upper(),
    }
    result = sync_to_calendar(event_type=event_type, transaction_id=transaction_id, event_data=event_data)
    if result.get("success"):
        execute_query(
            """
            INSERT INTO communications (transaction_id, communication_type, contact_party, contact_name, summary, outcome)
            VALUES (%s, 'note', %s, 'calendar_sync', %s, %s)
            """,
            (
                transaction_id,
                normalize_vendor_type(vendor_type),
                "Google Calendar synced for vendor appointment",
                (
                    f"event_type={event_type} appointment_at={appointment_at.isoformat()} "
                    f"google_event_id={result.get('google_event_id') or 'n/a'}"
                ),
            ),
        )
    return result


def _sync_closing_event_for_transaction(transaction_id, transaction_row=None, force_update=False):
    """Sync one closing event for transaction if closing date is available."""
    transaction = transaction_row or get_transaction_or_none(transaction_id)
    if not transaction or not transaction.get("closing_date"):
        return {"success": False, "skipped": "closing_date_missing"}

    settings = fetch_calendar_sync_settings()
    preferences = fetch_transaction_calendar_preferences(transaction_id) or {}
    closing_dt = combine_date_and_hhmm(
        transaction.get("closing_date"),
        preferences.get("closing_time"),
        fallback_hhmm=settings.get("closing_default_time") or "09:00",
    )
    duration_minutes = int(
        preferences.get("closing_duration_minutes")
        or settings.get("closing_duration_minutes")
        or 60
    )
    location = (
        (preferences.get("closing_location") or "").strip()
        or (transaction.get("title_company") or "").strip()
        or (transaction.get("property_address") or "").strip()
    )
    event_data = {
        "property_address": transaction.get("property_address"),
        "title_company_address": location,
        "title_company": transaction.get("title_company"),
        "buyer_name": transaction.get("buyer_name"),
        "seller_name": transaction.get("seller_name"),
        "agent_name": transaction.get("agent_name"),
        "lender_name": transaction.get("lender_name"),
        "closing_time": closing_dt,
        "duration_minutes": duration_minutes,
        "source_ref": "closing",
        "source_id": 0,
        "source_label": "Closing",
        "summary_prefix": "CLOSING",
    }
    if force_update:
        return update_calendar_event(event_type="closing", transaction_id=transaction_id, event_data=event_data)
    return sync_to_calendar(event_type="closing", transaction_id=transaction_id, event_data=event_data)


def sync_transaction_calendar_bundle(
    transaction_id,
    actor="system",
    force_update=False,
    include_deadlines=True,
    include_closing=True,
    include_vendor_events=True,
):
    """Sync deadlines, closing event, and known appointments for one transaction."""
    ensure_calendar_sync_tables()
    transaction = get_transaction_or_none(transaction_id)
    if not transaction:
        return {"success": False, "error": "transaction_not_found"}

    summary = {
        "success": True,
        "deadline_synced": 0,
        "deadline_skipped": 0,
        "deadline_failed": 0,
        "deadline_deleted": 0,
        "closing_synced": False,
        "closing_skipped": False,
        "closing_failed": False,
        "vendor_synced": 0,
        "vendor_failed": 0,
    }

    if include_deadlines:
        deadline_rows = execute_query(
            """
            SELECT id, deadline_type, deadline_date, description, completed
            FROM deadlines
            WHERE transaction_id = %s
            ORDER BY deadline_date ASC, id ASC
            """,
            (transaction_id,),
            fetch=True,
        ) or []
        deadline_result = sync_all_deadlines(
            transaction_id=transaction_id,
            deadline_rows=deadline_rows,
            transaction_row=transaction,
        )
        summary["deadline_synced"] = int(deadline_result.get("synced") or 0)
        summary["deadline_skipped"] = int(deadline_result.get("skipped") or 0)
        summary["deadline_failed"] = int(deadline_result.get("failed") or 0)
        summary["deadline_deleted"] = int(deadline_result.get("stale_deleted") or 0)

    if include_closing:
        closing_result = _sync_closing_event_for_transaction(
            transaction_id=transaction_id,
            transaction_row=transaction,
            force_update=force_update,
        )
        summary["closing_synced"] = bool(closing_result.get("success"))
        summary["closing_skipped"] = bool(closing_result.get("skipped"))
        summary["closing_failed"] = (not bool(closing_result.get("success"))) and not bool(
            closing_result.get("skipped")
        )

    if include_vendor_events:
        appointments = execute_query(
            """
            SELECT id, vendor_type, vendor_name, appointment_at, appointment_notes
            FROM vendor_outreach
            WHERE transaction_id = %s
              AND appointment_at IS NOT NULL
              AND COALESCE(response_status, '') <> 'unable'
            ORDER BY appointment_at ASC, id ASC
            """,
            (transaction_id,),
            fetch=True,
        ) or []
        for appointment in appointments:
            vendor_result = sync_vendor_appointment_to_calendar(
                transaction_id=transaction_id,
                vendor_type=appointment.get("vendor_type"),
                appointment_at=appointment.get("appointment_at"),
                vendor_name=appointment.get("vendor_name") or "",
                source_ref=f"vendor_outreach:{appointment['id']}",
                source_id=appointment.get("id") or 0,
                notes=appointment.get("appointment_notes") or "",
            )
            if vendor_result.get("success"):
                summary["vendor_synced"] += 1
            elif not vendor_result.get("skipped"):
                summary["vendor_failed"] += 1

    execute_query(
        """
        INSERT INTO communications (transaction_id, communication_type, contact_party, contact_name, summary, outcome)
        VALUES (%s, 'note', 'system', 'calendar_sync', %s, %s)
        """,
        (
            transaction_id,
            "Google Calendar sync bundle executed",
            (
                f"actor={actor} deadlines={summary['deadline_synced']}/{summary['deadline_failed']} "
                f"deadline_skipped={summary['deadline_skipped']} "
                f"deadline_deleted={summary['deadline_deleted']} "
                f"closing_synced={summary['closing_synced']} closing_skipped={summary['closing_skipped']} "
                f"vendor_synced={summary['vendor_synced']} "
                f"vendor_failed={summary['vendor_failed']}"
            ),
        ),
    )
    return summary


def apply_calendar_webhook_update(payload):
    """Apply two-way sync payload from Google Calendar webhook bridge."""
    ensure_calendar_sync_tables()
    event_id = (
        (payload or {}).get("event_id")
        or (payload or {}).get("id")
        or ((payload or {}).get("event") or {}).get("id")
        or ""
    )
    event_id = (event_id or "").strip()
    if not event_id:
        return {"success": False, "error": "missing_event_id"}

    calendar_id = (
        (payload or {}).get("calendar_id")
        or (payload or {}).get("calendarId")
        or os.getenv("GOOGLE_CALENDAR_ID")
        or "primary"
    )
    mapping = fetch_calendar_mapping_by_event_id(event_id, calendar_id=calendar_id)
    if not mapping:
        return {"success": False, "error": "mapping_not_found"}

    def _parse_calendar_webhook_datetime(raw_value):
        if not raw_value:
            return None
        text = str(raw_value).strip().replace("Z", "+00:00")
        if not text:
            return None
        try:
            parsed_value = datetime.fromisoformat(text)
        except ValueError:
            try:
                parsed_value = datetime.strptime(text, "%Y-%m-%d")
            except ValueError:
                return None
        if parsed_value.tzinfo:
            return parsed_value.astimezone().replace(tzinfo=None)
        return parsed_value

    start_input = (
        (payload or {}).get("start_time")
        or ((payload or {}).get("start") or {}).get("dateTime")
        or ((payload or {}).get("start") or {}).get("date")
    )
    end_input = (
        (payload or {}).get("end_time")
        or ((payload or {}).get("end") or {}).get("dateTime")
        or ((payload or {}).get("end") or {}).get("date")
    )
    start_dt = _parse_calendar_webhook_datetime(start_input)
    end_dt = _parse_calendar_webhook_datetime(end_input)

    transaction_id = mapping.get("transaction_id")
    event_type = (mapping.get("event_type") or "").lower()
    source_ref = (mapping.get("source_ref") or "").lower()

    if event_type == "deadline" and start_dt:
        deadline_type = source_ref.split("deadline:", 1)[1] if source_ref.startswith("deadline:") else ""
        if deadline_type:
            execute_query(
                """
                UPDATE deadlines
                SET deadline_date = %s
                WHERE transaction_id = %s
                  AND deadline_type = %s
                """,
                (start_dt.date(), transaction_id, deadline_type),
            )
    elif event_type == "closing" and start_dt:
        execute_query(
            """
            UPDATE transactions
            SET closing_date = %s,
                updated_at = CURRENT_TIMESTAMP
            WHERE id = %s
            """,
            (start_dt.date(), transaction_id),
        )
        execute_query(
            """
            UPDATE deadlines
            SET deadline_date = %s
            WHERE transaction_id = %s
              AND deadline_type = 'closing'
            """,
            (start_dt.date(), transaction_id),
        )
        upsert_transaction_calendar_preferences(
            transaction_id=transaction_id,
            closing_time=start_dt.strftime("%H:%M"),
            closing_duration_minutes=60 if not end_dt else max(30, int((end_dt - start_dt).total_seconds() / 60)),
            closing_location=(payload or {}).get("location") or "",
            updated_by="calendar_webhook",
        )
    elif event_type in {"inspection", "appraisal"} and start_dt:
        vendor_id = mapping.get("source_id") or 0
        if vendor_id:
            execute_query(
                """
                UPDATE vendor_outreach
                SET appointment_at = %s,
                    updated_at = CURRENT_TIMESTAMP
                WHERE id = %s
                """,
                (start_dt, vendor_id),
            )
            execute_query(
                """
                UPDATE calendar_events
                SET starts_at = %s,
                    ends_at = %s
                WHERE vendor_outreach_id = %s
                """,
                (start_dt, end_dt or (start_dt + timedelta(minutes=45)), vendor_id),
            )

    log_calendar_sync_event(
        action="webhook_update",
        transaction_id=transaction_id,
        mapping_id=mapping.get("id"),
        event_type=event_type,
        success=True,
        details="Two-way calendar webhook update applied",
        metadata={"event_id": event_id, "source_ref": source_ref},
    )
    execute_query(
        """
        INSERT INTO communications (transaction_id, communication_type, contact_party, contact_name, summary, outcome)
        VALUES (%s, 'note', 'system', 'calendar_webhook', %s, %s)
        """,
        (
            transaction_id,
            "Calendar webhook update applied",
            (
                f"event_type={event_type} event_id={event_id} "
                f"start={start_dt.isoformat() if start_dt else 'n/a'}"
            ),
        ),
    )
    return {"success": True, "transaction_id": transaction_id, "event_type": event_type}


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
    inserted = bool(execute_query(insert_query, tuple(params)))
    if not inserted:
        return False

    # Best-effort Google Calendar sync should never block deadline creation.
    try:
        sync_all_deadlines(transaction_id)
    except Exception as exc:
        log_system_error("calendar_sync", f"Deadline sync failed: {exc}", transaction_id)
    return True


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


def get_transaction(transaction_id):
    """Fetch one transaction or raise a ValueError."""
    transaction = get_transaction_or_none(transaction_id)
    if not transaction:
        raise ValueError("Transaction not found")
    return transaction


def ensure_completion_workflow_schema():
    """Ensure completion-workflow transaction columns exist."""
    execute_query("ALTER TABLE transactions ADD COLUMN IF NOT EXISTS completed_at TIMESTAMP")
    execute_query("ALTER TABLE transactions ADD COLUMN IF NOT EXISTS completion_archive_s3_key VARCHAR(500)")
    execute_query("ALTER TABLE transactions ADD COLUMN IF NOT EXISTS completion_summary_s3_key VARCHAR(500)")


def ensure_review_system_tables():
    """Ensure review request, review submission, and website review tables exist."""
    execute_query(
        """
        CREATE TABLE IF NOT EXISTS agent_review_requests (
            id SERIAL PRIMARY KEY,
            transaction_id INT REFERENCES transactions(id) ON DELETE CASCADE,
            agent_email VARCHAR(255) NOT NULL,
            access_token UUID UNIQUE NOT NULL,
            status VARCHAR(20) DEFAULT 'pending',
            requested_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            completed_at TIMESTAMP
        )
        """
    )
    execute_query(
        """
        CREATE INDEX IF NOT EXISTS idx_agent_review_requests_txn
        ON agent_review_requests(transaction_id, requested_at DESC)
        """
    )
    execute_query(
        """
        CREATE TABLE IF NOT EXISTS agent_reviews (
            id SERIAL PRIMARY KEY,
            request_id INT REFERENCES agent_review_requests(id) ON DELETE SET NULL,
            transaction_id INT REFERENCES transactions(id) ON DELETE CASCADE,
            agent_email VARCHAR(255),
            rating INT NOT NULL CHECK (rating >= 1 AND rating <= 5),
            feedback TEXT NOT NULL,
            auto_posted BOOLEAN DEFAULT FALSE,
            posted_at TIMESTAMP,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
        """
    )
    execute_query(
        """
        CREATE INDEX IF NOT EXISTS idx_agent_reviews_txn
        ON agent_reviews(transaction_id, created_at DESC)
        """
    )
    execute_query(
        """
        CREATE TABLE IF NOT EXISTS website_reviews (
            id SERIAL PRIMARY KEY,
            source_review_id INT UNIQUE REFERENCES agent_reviews(id) ON DELETE CASCADE,
            transaction_id INT REFERENCES transactions(id) ON DELETE CASCADE,
            display_name VARCHAR(255),
            quote_text TEXT NOT NULL,
            rating INT NOT NULL,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
        """
    )
    execute_query(
        """
        CREATE INDEX IF NOT EXISTS idx_website_reviews_created
        ON website_reviews(created_at DESC)
        """
    )


def update_transaction(transaction_id, **fields):
    """Update whitelisted transaction columns and updated_at timestamp."""
    ensure_completion_workflow_schema()
    allowed_fields = {
        "status",
        "completed_at",
        "completion_archive_s3_key",
        "completion_summary_s3_key",
        "review_requested",
        "review_requested_date",
    }
    safe_fields = {key: value for key, value in fields.items() if key in allowed_fields}
    if not safe_fields:
        return False

    set_parts = []
    params: list[Any] = []
    for key, value in safe_fields.items():
        set_parts.append(f"{key} = %s")
        params.append(value)
    set_parts.append("updated_at = CURRENT_TIMESTAMP")
    params.append(transaction_id)
    query = f"""
    UPDATE transactions
    SET {", ".join(set_parts)}
    WHERE id = %s
    """
    return bool(execute_query(query, tuple(params)))


def _uploaded_documents_for_completion(transaction_id, transaction_row=None):
    """Return uploaded document rows and lookup maps for completion checks."""
    transaction = transaction_row or get_transaction_or_none(transaction_id) or {}
    rows = execute_query(
        """
        SELECT id, document_type, filename, s3_key, status, uploaded_at
        FROM documents
        WHERE transaction_id = %s
        ORDER BY uploaded_at DESC, id DESC
        """,
        (transaction_id,),
        fetch=True,
    ) or []
    by_type = {}
    uploaded_types = set()
    for row in rows:
        doc_type = (row.get("document_type") or "").strip().lower()
        if not doc_type:
            continue
        uploaded_types.add(doc_type)
        if doc_type not in by_type:
            by_type[doc_type] = row

    if transaction.get("contract_s3_key"):
        uploaded_types.add("contract")
        by_type.setdefault(
            "contract",
            {
                "id": 0,
                "document_type": "contract",
                "filename": transaction.get("contract_pdf_url") or "contract.pdf",
                "s3_key": transaction.get("contract_s3_key"),
                "status": "received",
                "uploaded_at": transaction.get("created_at"),
            },
        )
    return {"rows": rows, "by_type": by_type, "uploaded_types": uploaded_types}


def run_completion_safety_checks(transaction_id, transaction_row=None):
    """Validate safety checks and return warning/error payload."""
    transaction = transaction_row or get_transaction_or_none(transaction_id)
    if not transaction:
        return {
            "ok": False,
            "issues": [{"code": "transaction_not_found", "severity": "error", "message": "Transaction not found."}],
            "missing_documents": [],
            "major_incomplete_tasks": [],
        }

    issues = []
    if not transaction.get("payment_closing_paid"):
        issues.append(
            {
                "code": "closing_payment_missing",
                "severity": "error",
                "message": "Closing payment has not been marked as received.",
            }
        )

    docs_payload = _uploaded_documents_for_completion(transaction_id, transaction_row=transaction)
    missing_documents = sorted(CRITICAL_COMPLETION_DOCUMENT_TYPES - docs_payload["uploaded_types"])
    if missing_documents:
        issues.append(
            {
                "code": "critical_docs_missing",
                "severity": "error",
                "message": "Critical closing documents are missing.",
                "missing_documents": missing_documents,
            }
        )

    major_incomplete_tasks = execute_query(
        """
        SELECT id, task_description, task_category, priority, due_date
        FROM tasks
        WHERE transaction_id = %s
          AND completed = FALSE
          AND (
                LOWER(COALESCE(priority, 'medium')) = 'high'
                OR LOWER(COALESCE(task_category, '')) IN ('closing', 'post_closing')
              )
        ORDER BY due_date ASC NULLS LAST, id ASC
        LIMIT 25
        """,
        (transaction_id,),
        fetch=True,
    ) or []
    if major_incomplete_tasks:
        issues.append(
            {
                "code": "major_tasks_incomplete",
                "severity": "warning",
                "message": f"{len(major_incomplete_tasks)} major task(s) remain incomplete.",
                "task_ids": [row["id"] for row in major_incomplete_tasks],
            }
        )

    has_errors = any(issue.get("severity") == "error" for issue in issues)
    return {
        "ok": not issues,
        "has_errors": has_errors,
        "issues": issues,
        "missing_documents": missing_documents,
        "major_incomplete_tasks": major_incomplete_tasks,
    }


def complete_all_deadlines(transaction_id):
    """Mark all open deadlines complete for a transaction."""
    rows = execute_query(
        """
        UPDATE deadlines
        SET completed = TRUE,
            completed_at = COALESCE(completed_at, CURRENT_TIMESTAMP)
        WHERE transaction_id = %s
          AND completed = FALSE
        RETURNING id
        """,
        (transaction_id,),
        fetch=True,
    ) or []
    return [row["id"] for row in rows]


def complete_all_tasks(transaction_id):
    """Mark all open tasks complete for a transaction."""
    rows = execute_query(
        """
        UPDATE tasks
        SET completed = TRUE,
            status = 'completed',
            completed_at = COALESCE(completed_at, CURRENT_TIMESTAMP),
            completed_by = COALESCE(NULLIF(completed_by, ''), 'completion_workflow')
        WHERE transaction_id = %s
          AND completed = FALSE
        RETURNING id
        """,
        (transaction_id,),
        fetch=True,
    ) or []
    return [row["id"] for row in rows]


def archive_all_documents(transaction_id):
    """Archive all transaction documents and upload an archive manifest."""
    ensure_completion_workflow_schema()
    transaction = get_transaction(transaction_id)
    docs_payload = _uploaded_documents_for_completion(transaction_id, transaction_row=transaction)
    document_rows = docs_payload["rows"]

    execute_query(
        """
        UPDATE documents
        SET status = 'archived'
        WHERE transaction_id = %s
          AND COALESCE(status, 'received') <> 'archived'
        """,
        (transaction_id,),
    )

    manifest_payload = {
        "transaction_id": transaction_id,
        "property_address": transaction.get("property_address"),
        "archived_at": datetime.now().isoformat(),
        "contract_s3_key": transaction.get("contract_s3_key"),
        "documents": [
            {
                "id": row.get("id"),
                "document_type": row.get("document_type"),
                "filename": row.get("filename"),
                "s3_key": row.get("s3_key"),
                "status": row.get("status"),
                "uploaded_at": row.get("uploaded_at"),
            }
            for row in document_rows
        ],
    }

    archive_key = None
    temp_path = None
    try:
        filename = f"archive_manifest_txn_{transaction_id}_{datetime.now().strftime('%Y%m%d_%H%M%S')}.json"
        with tempfile.NamedTemporaryFile(suffix=".json", delete=False, mode="w", encoding="utf-8") as tmp:
            temp_path = tmp.name
            json.dump(manifest_payload, tmp, indent=2, default=str)
        archive_key = upload_local_file(
            local_path=temp_path,
            transaction_id=transaction_id,
            document_type="archive_manifest",
            filename=filename,
            content_type="application/json",
        )
    finally:
        if temp_path and os.path.exists(temp_path):
            try:
                os.remove(temp_path)
            except OSError:
                pass

    if archive_key:
        update_transaction(transaction_id, completion_archive_s3_key=archive_key)
    return archive_key


def count_completions_this_month():
    """Return number of completed transactions in the current month."""
    month_start = date.today().replace(day=1)
    rows = execute_query(
        """
        SELECT COUNT(*) AS total
        FROM transactions
        WHERE status = 'COMPLETED'
          AND COALESCE(completed_at, updated_at, created_at) >= %s
        """,
        (month_start,),
        fetch=True,
    ) or []
    return int(rows[0]["total"]) if rows else 0


def _completion_date_label(value):
    if isinstance(value, datetime):
        return value.strftime("%b %d, %Y %I:%M %p")
    if isinstance(value, date):
        return value.strftime("%b %d, %Y")
    return str(value or "N/A")


def generate_completion_summary(transaction_id):
    """Generate and upload transaction completion summary PDF."""
    ensure_completion_workflow_schema()
    ensure_commission_tracking_table()
    transaction = get_transaction(transaction_id)
    upsert_commission_tracking(transaction_id)

    deadline_rows = execute_query(
        """
        SELECT deadline_type, deadline_date, completed
        FROM deadlines
        WHERE transaction_id = %s
        ORDER BY deadline_date ASC, id ASC
        """,
        (transaction_id,),
        fetch=True,
    ) or []
    docs_payload = _uploaded_documents_for_completion(transaction_id, transaction_row=transaction)
    comm_rows = execute_query(
        """
        SELECT communication_type, contact_party, summary, created_at
        FROM communications
        WHERE transaction_id = %s
        ORDER BY created_at DESC, id DESC
        LIMIT 14
        """,
        (transaction_id,),
        fetch=True,
    ) or []
    comm_type_counts = execute_query(
        """
        SELECT communication_type, COUNT(*) AS total
        FROM communications
        WHERE transaction_id = %s
        GROUP BY communication_type
        ORDER BY total DESC, communication_type ASC
        """,
        (transaction_id,),
        fetch=True,
    ) or []
    commission_rows = execute_query(
        """
        SELECT upfront_fee, closing_fee, referral_credit_given, total_revenue,
               upfront_paid_date, closing_paid_date
        FROM commission_tracking
        WHERE transaction_id = %s
        LIMIT 1
        """,
        (transaction_id,),
        fetch=True,
    ) or []
    commission_row = commission_rows[0] if commission_rows else {}

    upfront_breakdown = calculate_payment_breakdown(transaction, "upfront")
    closing_breakdown = calculate_payment_breakdown(transaction, "closing")
    outstanding_amount = 0.0
    if not transaction.get("payment_upfront_paid"):
        outstanding_amount += float(upfront_breakdown["amount"])
    if not transaction.get("payment_closing_paid"):
        outstanding_amount += float(closing_breakdown["amount"])

    total_deadlines = len(deadline_rows)
    met_deadlines = len([row for row in deadline_rows if row.get("completed")])

    deadline_table_rows = [["Milestone", "Date", "Met"]]
    for row in deadline_rows:
        deadline_table_rows.append(
            [
                (row.get("deadline_type") or "").replace("_", " ").title(),
                _completion_date_label(row.get("deadline_date")),
                "Yes" if row.get("completed") else "No",
            ]
        )
    if len(deadline_table_rows) == 1:
        deadline_table_rows.append(["No deadlines", "N/A", "N/A"])

    docs_table_rows = [["Document", "Received", "Latest File"]]
    for doc_type in sorted(REQUIRED_DOCUMENT_TYPES):
        latest_row = docs_payload["by_type"].get(doc_type) or {}
        docs_table_rows.append(
            [
                document_type_label(doc_type),
                "Yes" if doc_type in docs_payload["uploaded_types"] else "No",
                latest_row.get("filename") or "-",
            ]
        )

    comm_type_table_rows = [["Type", "Count"]]
    for row in comm_type_counts:
        comm_type_table_rows.append(
            [
                (row.get("communication_type") or "").replace("_", " ").title(),
                str(int(row.get("total") or 0)),
            ]
        )
    if len(comm_type_table_rows) == 1:
        comm_type_table_rows.append(["No communications", "0"])

    recent_comm_table_rows = [["When", "Type", "Summary"]]
    for row in comm_rows:
        recent_comm_table_rows.append(
            [
                _completion_date_label(row.get("created_at")),
                (row.get("communication_type") or "").replace("_", " ").title(),
                (row.get("summary") or "").strip()[:90] or "-",
            ]
        )
    if len(recent_comm_table_rows) == 1:
        recent_comm_table_rows.append(["N/A", "N/A", "No communications logged."])

    settlement_table_rows = [
        ["Line Item", "Amount", "Status"],
        [
            "Upfront Payment",
            f"${float(upfront_breakdown['amount']):,.2f}",
            "Paid" if transaction.get("payment_upfront_paid") else "Pending",
        ],
        [
            "Closing Payment",
            f"${float(closing_breakdown['amount']):,.2f}",
            "Paid" if transaction.get("payment_closing_paid") else "Pending",
        ],
        ["Outstanding Balance", f"${float(outstanding_amount):,.2f}", "Cleared" if outstanding_amount == 0 else "Open"],
    ]

    commission_table_rows = [
        ["Metric", "Value"],
        ["Upfront Fee", f"${float(commission_row.get('upfront_fee') or 0):,.2f}"],
        ["Closing Fee", f"${float(commission_row.get('closing_fee') or 0):,.2f}"],
        ["Referral Credit", f"${float(commission_row.get('referral_credit_given') or 0):,.2f}"],
        ["Total Revenue", f"${float(commission_row.get('total_revenue') or 0):,.2f}"],
    ]

    temp_path = None
    pdf_bytes = b""
    filename = f"completion_summary_txn_{transaction_id}_{datetime.now().strftime('%Y%m%d_%H%M')}.pdf"
    try:
        with tempfile.NamedTemporaryFile(suffix=".pdf", delete=False) as tmp:
            temp_path = tmp.name

        doc = SimpleDocTemplate(temp_path, pagesize=letter, leftMargin=36, rightMargin=36, topMargin=36, bottomMargin=36)
        styles = getSampleStyleSheet()
        story = []
        story.append(Paragraph("Transaction Completion Summary", styles["Title"]))
        story.append(
            Paragraph(
                f"Transaction #{transaction_id} | {(transaction.get('property_address') or 'Unknown property')}",
                styles["Heading3"],
            )
        )
        story.append(Spacer(1, 8))
        story.append(
            Paragraph(
                (
                    f"Completed at: {_completion_date_label(datetime.now())}<br/>"
                    f"Agent: {transaction.get('agent_name') or 'N/A'} | "
                    f"Buyer: {transaction.get('buyer_name') or 'N/A'} | "
                    f"Seller: {transaction.get('seller_name') or 'N/A'}"
                ),
                styles["BodyText"],
            )
        )
        story.append(Spacer(1, 10))

        def _styled_table(rows, col_widths):
            table = Table(rows, colWidths=col_widths, repeatRows=1)
            table.setStyle(
                TableStyle(
                    [
                        ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#1d4ed8")),
                        ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
                        ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
                        ("FONTNAME", (0, 1), (-1, -1), "Helvetica"),
                        ("FONTSIZE", (0, 0), (-1, -1), 8.6),
                        ("GRID", (0, 0), (-1, -1), 0.25, colors.HexColor("#cbd5e1")),
                        ("ROWBACKGROUNDS", (0, 1), (-1, -1), [colors.white, colors.HexColor("#f8fafc")]),
                        ("LEFTPADDING", (0, 0), (-1, -1), 6),
                        ("RIGHTPADDING", (0, 0), (-1, -1), 6),
                        ("TOPPADDING", (0, 0), (-1, -1), 4),
                        ("BOTTOMPADDING", (0, 0), (-1, -1), 4),
                    ]
                )
            )
            return table

        story.append(Paragraph("Final Timeline", styles["Heading2"]))
        story.append(_styled_table(deadline_table_rows, [250, 160, 90]))
        story.append(Spacer(1, 10))

        story.append(Paragraph("Deadlines Met", styles["Heading2"]))
        story.append(Paragraph(f"{met_deadlines}/{total_deadlines} deadlines marked complete.", styles["BodyText"]))
        story.append(Spacer(1, 8))

        story.append(Paragraph("Documents Checklist", styles["Heading2"]))
        story.append(_styled_table(docs_table_rows, [170, 80, 250]))
        story.append(Spacer(1, 10))

        story.append(Paragraph("Communications Summary", styles["Heading2"]))
        story.append(_styled_table(comm_type_table_rows, [280, 220]))
        story.append(Spacer(1, 6))
        story.append(_styled_table(recent_comm_table_rows, [130, 90, 280]))
        story.append(Spacer(1, 10))

        story.append(Paragraph("Final Settlement Amounts", styles["Heading2"]))
        story.append(_styled_table(settlement_table_rows, [220, 140, 140]))
        story.append(Spacer(1, 10))

        story.append(Paragraph("Commission Breakdown", styles["Heading2"]))
        story.append(_styled_table(commission_table_rows, [250, 250]))
        doc.build(story)

        with open(temp_path, "rb") as pdf_file:
            pdf_bytes = pdf_file.read()
    finally:
        if temp_path and os.path.exists(temp_path):
            try:
                os.remove(temp_path)
            except OSError:
                pass

    temp_upload_path = None
    s3_key = None
    try:
        with tempfile.NamedTemporaryFile(suffix=".pdf", delete=False) as tmp_upload:
            temp_upload_path = tmp_upload.name
            tmp_upload.write(pdf_bytes)
        s3_key = upload_local_file(
            local_path=temp_upload_path,
            transaction_id=transaction_id,
            document_type="completion_summary",
            filename=filename,
            content_type="application/pdf",
        )
    finally:
        if temp_upload_path and os.path.exists(temp_upload_path):
            try:
                os.remove(temp_upload_path)
            except OSError:
                pass

    if not s3_key:
        raise RuntimeError("Failed to upload completion summary PDF")

    document_id = execute_insert(
        """
        INSERT INTO documents (
            transaction_id, document_type, filename, s3_key, file_size, uploaded_by, uploaded_at
        ) VALUES (%s, %s, %s, %s, %s, %s, CURRENT_TIMESTAMP)
        RETURNING id
        """,
        (transaction_id, "completion_summary", filename, s3_key, len(pdf_bytes), "completion_workflow"),
    )
    update_transaction(transaction_id, completion_summary_s3_key=s3_key)
    return {
        "s3_key": s3_key,
        "filename": filename,
        "document_id": document_id,
        "pdf_bytes": pdf_bytes,
        "summary_url": get_presigned_url(s3_key, expiration=60 * 60 * 24 * 7),
    }


def send_congratulations_emails(transaction):
    """Send buyer, seller, and agent completion emails."""
    transaction_id = int(transaction["id"])
    email_map = fetch_client_email_map(transaction_id)
    portal_links = fetch_client_portal_link_map(transaction_id)
    default_portal_link = ensure_primary_portal_link(transaction_id)
    survey_url = (os.getenv("POST_CLOSE_SURVEY_URL") or "").strip() or f"{app_base_url()}/tc"
    referral_url = (os.getenv("REFERRAL_PROGRAM_URL") or "").strip() or "https://www.getmaverick.com"

    def _log_email_result(contact_party, contact_name, summary, outcome):
        execute_query(
            """
            INSERT INTO communications (transaction_id, communication_type, contact_party, contact_name, summary, outcome)
            VALUES (%s, 'email', %s, %s, %s, %s)
            """,
            (transaction_id, contact_party, contact_name, summary, outcome),
        )

    results = {"sent": 0, "failed": 0, "skipped": 0}

    buyer_email = normalize_email(email_map.get("buyer"))
    if buyer_email and is_email_valid(buyer_email):
        buyer_context = {
            "subject": f"Congratulations on your closing - {transaction.get('property_address')}",
            "buyer_name": transaction.get("buyer_name") or "Buyer",
            "property_address": transaction.get("property_address"),
            "move_in_tip_1": "Create a first-week move-in checklist before closing day.",
            "move_in_tip_2": "Store settlement documents in your portal for quick access.",
            "utility_reminder": "Set utility transfers to begin on your closing date.",
            "final_docs_link": portal_links.get("buyer") or default_portal_link,
            "survey_link": survey_url,
        }
        message_id = send_email(
            to=buyer_email,
            template="emails/transaction_complete_buyer.html",
            data=buyer_context,
        )
        _log_email_result(
            "buyer",
            transaction.get("buyer_name") or "Buyer",
            "Buyer congratulations email sent" if message_id else "Buyer congratulations email failed",
            f"to={buyer_email} message_id={message_id or 'failed'}",
        )
        if message_id:
            results["sent"] += 1
        else:
            results["failed"] += 1
    else:
        results["skipped"] += 1

    seller_email = normalize_email(email_map.get("seller"))
    if seller_email and is_email_valid(seller_email):
        seller_context = {
            "subject": f"Thank you for trusting Maverick TC - {transaction.get('property_address')}",
            "seller_name": transaction.get("seller_name") or "Seller",
            "property_address": transaction.get("property_address"),
            "final_docs_link": portal_links.get("seller") or default_portal_link,
            "referral_link": referral_url,
        }
        message_id = send_email(
            to=seller_email,
            template="emails/transaction_complete_seller.html",
            data=seller_context,
        )
        _log_email_result(
            "seller",
            transaction.get("seller_name") or "Seller",
            "Seller thank-you email sent" if message_id else "Seller thank-you email failed",
            f"to={seller_email} message_id={message_id or 'failed'}",
        )
        if message_id:
            results["sent"] += 1
        else:
            results["failed"] += 1
    else:
        results["skipped"] += 1

    agent_email = normalize_email(transaction.get("agent_email"))
    if agent_email and is_email_valid(agent_email):
        agent_context = {
            "subject": f"Transaction complete - {transaction.get('property_address')}",
            "agent_name": transaction.get("agent_name") or "Agent",
            "property_address": transaction.get("property_address"),
            "referral_link": referral_url,
        }
        message_id = send_email(
            to=agent_email,
            template="emails/transaction_complete_agent.html",
            data=agent_context,
        )
        _log_email_result(
            "agent",
            transaction.get("agent_name") or "Agent",
            "Agent completion email sent" if message_id else "Agent completion email failed",
            f"to={agent_email} message_id={message_id or 'failed'}",
        )
        if message_id:
            results["sent"] += 1
        else:
            results["failed"] += 1
    else:
        results["skipped"] += 1

    return results


def send_review_request(agent_email, transaction_id):
    """Create review request token and email the review link to agent."""
    ensure_review_system_tables()
    safe_email = normalize_email(agent_email)
    if not safe_email or not is_email_valid(safe_email):
        return {"success": False, "skipped": "missing_agent_email"}

    existing_rows = execute_query(
        """
        SELECT id, access_token
        FROM agent_review_requests
        WHERE transaction_id = %s
          AND LOWER(agent_email) = LOWER(%s)
          AND status = 'pending'
        ORDER BY requested_at DESC, id DESC
        LIMIT 1
        """,
        (transaction_id, safe_email),
        fetch=True,
    ) or []
    if existing_rows:
        request_id = existing_rows[0]["id"]
        access_token = str(existing_rows[0]["access_token"])
    else:
        access_token = str(uuid4())
        request_id = execute_insert(
            """
            INSERT INTO agent_review_requests (
                transaction_id, agent_email, access_token, status, requested_at
            ) VALUES (%s, %s, %s, 'pending', CURRENT_TIMESTAMP)
            RETURNING id
            """,
            (transaction_id, safe_email, access_token),
        )

    review_link = f"{app_base_url()}/review/{access_token}"
    transaction = get_transaction_or_none(transaction_id) or {}
    message_id = send_email(
        to=safe_email,
        template="emails/review_request_agent.html",
        data={
            "subject": f"Quick favor: review your Maverick TC experience ({transaction.get('property_address')})",
            "agent_name": transaction.get("agent_name") or "Agent",
            "property_address": transaction.get("property_address") or "your transaction",
            "review_link": review_link,
        },
    )
    update_transaction(
        transaction_id,
        review_requested=True,
        review_requested_date=datetime.now(),
    )
    execute_query(
        """
        INSERT INTO communications (transaction_id, communication_type, contact_party, contact_name, summary, outcome)
        VALUES (%s, 'email', 'agent', %s, %s, %s)
        """,
        (
            transaction_id,
            transaction.get("agent_name") or "Agent",
            "Review request email sent" if message_id else "Review request email failed",
            f"to={safe_email} request_id={request_id or 'n/a'} message_id={message_id or 'failed'}",
        ),
    )
    return {
        "success": bool(message_id),
        "request_id": request_id,
        "review_link": review_link,
        "message_id": message_id,
    }


def auto_post_positive_review(review_id):
    """Auto-post positive agent reviews to website_reviews."""
    ensure_review_system_tables()
    rows = execute_query(
        """
        SELECT ar.id, ar.transaction_id, ar.rating, ar.feedback, ar.agent_email,
               t.agent_name, t.property_address
        FROM agent_reviews ar
        LEFT JOIN transactions t ON t.id = ar.transaction_id
        WHERE ar.id = %s
        LIMIT 1
        """,
        (review_id,),
        fetch=True,
    ) or []
    if not rows:
        return {"success": False, "error": "review_not_found"}
    row = rows[0]
    if int(row.get("rating") or 0) < POSITIVE_REVIEW_THRESHOLD:
        return {"success": False, "skipped": "rating_not_positive"}

    display_name = row.get("agent_name") or row.get("agent_email") or "Maverick Agent"
    execute_query(
        """
        INSERT INTO website_reviews (
            source_review_id, transaction_id, display_name, quote_text, rating, created_at
        )
        VALUES (%s, %s, %s, %s, %s, CURRENT_TIMESTAMP)
        ON CONFLICT (source_review_id)
        DO UPDATE SET
            quote_text = EXCLUDED.quote_text,
            rating = EXCLUDED.rating
        """,
        (
            review_id,
            row.get("transaction_id"),
            display_name,
            (row.get("feedback") or "").strip(),
            int(row.get("rating") or 0),
        ),
    )
    execute_query(
        """
        UPDATE agent_reviews
        SET auto_posted = TRUE,
            posted_at = CURRENT_TIMESTAMP
        WHERE id = %s
        """,
        (review_id,),
    )
    execute_query(
        """
        INSERT INTO communications (transaction_id, communication_type, contact_party, contact_name, summary, outcome)
        VALUES (%s, 'note', 'system', 'reviews', %s, %s)
        """,
        (
            row.get("transaction_id"),
            "Positive review auto-posted to website",
            f"review_id={review_id} rating={int(row.get('rating') or 0)}",
        ),
    )
    return {"success": True}


def alert_margaret_negative_review(transaction_id, rating, feedback):
    """Notify Margaret when a low review is submitted."""
    margaret_phone = normalize_phone(os.getenv("MARGARET_PHONE") or "")
    margaret_email = normalize_email(os.getenv("MARGARET_EMAIL") or "")
    message_body = (
        f"Negative review alert: Transaction #{transaction_id} "
        f"received {int(rating)}/5. Feedback: {(feedback or '')[:180]}"
    )
    sms_sid = None
    if margaret_phone:
        sms_sid = send_sms(margaret_phone, message_body[:320])
    email_message_id = None
    if margaret_email and is_email_valid(margaret_email):
        email_html = (
            "<p><strong>Negative review alert</strong></p>"
            f"<p>Transaction #{transaction_id} received <strong>{int(rating)}/5</strong>.</p>"
            f"<p>Feedback:</p><blockquote>{(feedback or '').strip()}</blockquote>"
        )
        email_message_id = send_html_email(
            to_email=margaret_email,
            subject=f"Negative review alert - Transaction #{transaction_id}",
            html_body=email_html,
        )
    execute_query(
        """
        INSERT INTO communications (transaction_id, communication_type, contact_party, contact_name, summary, outcome)
        VALUES (%s, 'note', 'system', 'reviews', %s, %s)
        """,
        (
            transaction_id,
            "Negative review alert sent to Margaret",
            f"sms_sid={sms_sid or 'none'} email_message_id={email_message_id or 'none'}",
        ),
    )


def process_referral_credit(transaction_id):
    """Process referral credit bookkeeping for completed transaction."""
    transaction = get_transaction_or_none(transaction_id)
    if not transaction:
        return {"success": False, "error": "transaction_not_found"}
    maybe_create_referral(transaction)
    used_credit = False
    if transaction.get("payment_upfront_paid") and transaction.get("agent_name"):
        mark_referral_credit_used_if_needed(transaction_id, transaction.get("agent_name"))
        used_credit = True
    return {
        "success": True,
        "had_referral": bool((transaction.get("referred_by_agent") or "").strip()),
        "credit_marked_used": used_credit,
    }


def finalize_commission_record(transaction_id):
    """Finalize commission row after completion."""
    ensure_commission_tracking_table()
    success = bool(upsert_commission_tracking(transaction_id))
    rows = execute_query(
        """
        SELECT upfront_fee, closing_fee, referral_credit_given, total_revenue
        FROM commission_tracking
        WHERE transaction_id = %s
        LIMIT 1
        """,
        (transaction_id,),
        fetch=True,
    ) or []
    return {"success": success, "commission_row": rows[0] if rows else {}}


def execute_transaction_completion_workflow(transaction_id, force_complete=False, initiated_by="margaret"):
    """Run full one-click completion workflow."""
    ensure_completion_workflow_schema()
    ensure_review_system_tables()
    transaction = get_transaction(transaction_id)
    status = (transaction.get("status") or "").strip().upper()
    if status in {"COMPLETED", "CANCELLED"}:
        return {"success": False, "error": "invalid_status", "message": "Transaction is already closed."}

    safety = run_completion_safety_checks(transaction_id, transaction_row=transaction)
    if safety.get("issues") and not force_complete:
        return {
            "success": False,
            "requires_confirmation": True,
            "message": "Safety checks found issues. Confirmation required.",
            "issues": safety.get("issues"),
        }

    if safety.get("issues") and force_complete:
        execute_query(
            """
            INSERT INTO communications (transaction_id, communication_type, contact_party, contact_name, summary, outcome)
            VALUES (%s, 'note', 'system', 'completion_workflow', %s, %s)
            """,
            (
                transaction_id,
                "Completion workflow override confirmed",
                json.dumps(safety.get("issues"), default=str)[:1800],
            ),
        )

    update_transaction(transaction_id, status="COMPLETED", completed_at=datetime.now())
    completed_deadline_ids = complete_all_deadlines(transaction_id)
    completed_task_ids = complete_all_tasks(transaction_id)
    archive_s3_key = archive_all_documents(transaction_id)
    summary_pdf = generate_completion_summary(transaction_id)

    margaret_email = normalize_email(os.getenv("MARGARET_EMAIL") or "")
    margaret_message_id = None
    if margaret_email and is_email_valid(margaret_email):
        margaret_message_id = send_email(
            to=margaret_email,
            template="emails/transaction_complete_margaret.html",
            data={
                "subject": f"Transaction completed: {transaction.get('property_address')}",
                "transaction": transaction,
                "summary_pdf": summary_pdf,
                "archive_s3_key": archive_s3_key,
            },
            attachments=[
                {
                    "filename": summary_pdf.get("filename") or "completion_summary.pdf",
                    "content_type": "application/pdf",
                    "data": summary_pdf.get("pdf_bytes"),
                }
            ],
        )
    execute_query(
        """
        INSERT INTO communications (transaction_id, communication_type, contact_party, contact_name, summary, outcome)
        VALUES (%s, 'email', 'system', 'margaret', %s, %s)
        """,
        (
            transaction_id,
            "Margaret completion summary email sent" if margaret_message_id else "Margaret completion email failed/skipped",
            f"to={margaret_email or 'n/a'} message_id={margaret_message_id or 'none'}",
        ),
    )

    congratulation_result = send_congratulations_emails(transaction)
    review_result = send_review_request(transaction.get("agent_email"), transaction_id)
    referral_result = process_referral_credit(transaction_id)
    commission_result = finalize_commission_record(transaction_id)

    completion_count = count_completions_this_month()
    margaret_phone = normalize_phone(os.getenv("MARGARET_PHONE") or "")
    celebration_sid = None
    if margaret_phone:
        celebration_sid = send_sms(
            margaret_phone,
            (
                f"Transaction #{transaction_id} ({transaction.get('property_address')}) completed. "
                f"That's #{completion_count} this month. Great work!"
            ),
        )

    execute_query(
        """
        INSERT INTO communications (transaction_id, communication_type, contact_party, contact_name, summary, outcome)
        VALUES (%s, 'note', 'system', 'completion_workflow', %s, %s)
        """,
        (
            transaction_id,
            "One-click completion workflow executed",
            (
                f"by={initiated_by} completed_deadlines={len(completed_deadline_ids)} "
                f"completed_tasks={len(completed_task_ids)} archive_key={archive_s3_key or 'none'} "
                f"summary_key={summary_pdf.get('s3_key') or 'none'} "
                f"review_request={'sent' if review_result.get('success') else 'failed/skipped'} "
                f"celebration_sid={celebration_sid or 'none'}"
            ),
        ),
    )

    return {
        "success": True,
        "message": "Transaction completed successfully",
        "actions_completed": 15,
        "archive_s3_key": archive_s3_key,
        "summary_pdf": {
            "s3_key": summary_pdf.get("s3_key"),
            "summary_url": summary_pdf.get("summary_url"),
            "filename": summary_pdf.get("filename"),
        },
        "completed_deadline_count": len(completed_deadline_ids),
        "completed_task_count": len(completed_task_ids),
        "email_summary": congratulation_result,
        "review_request": review_result,
        "referral": referral_result,
        "commission": commission_result,
        "safety_issues": safety.get("issues") if safety.get("issues") else [],
    }


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


def parse_inbound_recipients_from_payload(payload):
    """Extract potential recipient addresses from provider payload formats."""
    recipients = []
    for key in ("to", "recipient", "delivered_to", "envelope_to", "X-Envelope-To"):
        recipients.extend(split_recipient_addresses(payload.get(key)))

    envelope_raw = payload.get("envelope")
    if envelope_raw:
        try:
            envelope_json = json.loads(envelope_raw) if isinstance(envelope_raw, str) else envelope_raw
            if isinstance(envelope_json, dict):
                recipients.extend(split_recipient_addresses(envelope_json.get("to")))
        except Exception:
            pass

    unique = []
    for email in recipients:
        if email not in unique:
            unique.append(email)
    return unique


def parse_inbound_sender_from_payload(payload):
    """Extract sender email from common inbound provider fields."""
    for key in ("from", "sender", "sender_email", "From"):
        sender = extract_email_address(payload.get(key))
        if sender:
            return sender
    return ""


@app.route("/webhooks/inbound-email", methods=["POST"])
def inbound_email_webhook():
    """Receive inbound transaction mailbox emails and apply AI routing."""
    ensure_inbound_email_tables()
    configured_secret = (os.getenv("INBOUND_EMAIL_WEBHOOK_SECRET") or "").strip()
    if configured_secret:
        provided_secret = (
            request.headers.get("X-Inbound-Secret")
            or request.headers.get("X-Webhook-Secret")
            or request.args.get("secret")
            or request.form.get("secret")
            or ""
        ).strip()
        if provided_secret != configured_secret:
            return jsonify({"success": False, "error": "Unauthorized"}), 403

    payload = request.get_json(silent=True)
    if not isinstance(payload, dict):
        payload = dict(request.form or {})

    recipient_addresses = parse_inbound_recipients_from_payload(payload)
    alias_match = None
    for recipient in recipient_addresses:
        parsed = parse_transaction_alias(recipient, inbound_email_domain())
        if parsed:
            alias_match = parsed
            break

    if not alias_match:
        return jsonify({"success": True, "ignored": "recipient_not_mapped"}), 200

    transaction = fetch_timeline_transaction(alias_match["transaction_id"])
    if not transaction:
        return jsonify({"success": False, "error": "Transaction not found"}), 404

    sender_email = parse_inbound_sender_from_payload(payload)
    sender_role = infer_inbound_sender_role(sender_email, transaction)
    if sender_role == "external" and alias_match["mailbox_role"] in INBOUND_MAILBOX_ROLES:
        sender_role = alias_match["mailbox_role"]
    subject = (payload.get("subject") or payload.get("Subject") or "").strip()
    body_text = (
        payload.get("text")
        or payload.get("body-plain")
        or payload.get("stripped-text")
        or payload.get("body")
        or payload.get("TextBody")
        or ""
    )
    body_text = str(body_text or "").strip()
    if not body_text:
        body_text = str(payload.get("html") or payload.get("stripped-html") or "")[:2000]
    provider_message_id = (
        payload.get("message_id")
        or payload.get("Message-Id")
        or payload.get("Message-ID")
        or payload.get("message-id")
        or ""
    )

    result = process_inbound_email_message(
        transaction=transaction,
        mailbox_role=alias_match["mailbox_role"],
        mailbox_address=alias_match["mailbox_address"],
        sender_email=sender_email or "unknown-sender",
        sender_role=sender_role,
        subject=subject or "(No subject)",
        body_text=body_text,
        provider_message_id=str(provider_message_id or "")[:255],
        provider_payload=payload,
    )
    return jsonify(
        {
            "success": True,
            "transaction_id": transaction["id"],
            "mailbox_role": alias_match["mailbox_role"],
            "route": result.get("route"),
            "urgency": result.get("analysis", {}).get("urgency"),
            "category": result.get("analysis", {}).get("category"),
            "message_id": result.get("message_id"),
        }
    )


@app.route("/calendar-webhook", methods=["GET", "POST"])
def calendar_webhook():
    """
    Receive Google Calendar two-way sync notifications.

    Supports:
    - Google channel ping headers (X-Goog-*)
    - JSON payload bridge with event_id/start/end fields
    """
    ensure_calendar_sync_tables()
    configured_secret = (os.getenv("CALENDAR_WEBHOOK_SECRET") or "").strip()
    if configured_secret:
        provided_secret = (
            request.headers.get("X-Calendar-Secret")
            or request.headers.get("X-Webhook-Secret")
            or request.args.get("secret")
            or request.form.get("secret")
            or ""
        ).strip()
        if provided_secret != configured_secret:
            log_calendar_sync_event(
                action="webhook_unauthorized",
                success=False,
                details="Calendar webhook secret mismatch.",
            )
            return jsonify({"success": False, "error": "Unauthorized"}), 403

    channel_id = (request.headers.get("X-Goog-Channel-ID") or "").strip()
    resource_id = (request.headers.get("X-Goog-Resource-ID") or "").strip()
    resource_uri = (request.headers.get("X-Goog-Resource-URI") or "").strip()
    expiration_ms = (request.headers.get("X-Goog-Channel-Expiration-Millis") or "").strip()
    resource_state = (request.headers.get("X-Goog-Resource-State") or "").strip().lower()
    if channel_id:
        upsert_calendar_webhook_channel(
            channel_id=channel_id,
            resource_id=resource_id,
            resource_uri=resource_uri,
            expiration_ms=expiration_ms or None,
            active=(resource_state != "sync" and resource_state != "not_exists"),
        )

    if request.method == "GET":
        return jsonify({"success": True, "message": "calendar webhook endpoint ready"}), 200

    settings = fetch_calendar_sync_settings()
    payload = request.get_json(silent=True)
    if not isinstance(payload, dict):
        payload = dict(request.form or {})

    if not settings.get("two_way_sync_enabled"):
        log_calendar_sync_event(
            action="webhook_ignored",
            event_type="calendar",
            success=True,
            details="Two-way sync disabled; payload ignored.",
            metadata={"channel_id": channel_id, "resource_state": resource_state},
        )
        return jsonify({"success": True, "ignored": "two_way_sync_disabled"}), 202

    if not payload:
        log_calendar_sync_event(
            action="webhook_ping",
            event_type="calendar",
            success=True,
            details="Webhook ping received with no body payload.",
            metadata={"channel_id": channel_id, "resource_state": resource_state},
        )
        return "", 204

    result = apply_calendar_webhook_update(payload)
    if not result.get("success"):
        log_calendar_sync_event(
            action="webhook_apply_failed",
            event_type="calendar",
            success=False,
            details=result.get("error") or "Unknown webhook apply failure.",
            metadata={"payload": payload},
        )
        return jsonify({"success": False, "error": result.get("error") or "webhook_apply_failed"}), 400

    return jsonify({"success": True, "result": result}), 200


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
        ensure_vendor_followup_tasks()
        auto_dispatch_timeline_updates(limit=40)
        refresh_heads_up_if_stale(max_age_minutes=180, send_sms=False)
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
        existing_rows = execute_query(
            """
            SELECT id, completed, completed_by
            FROM tasks
            WHERE id = %s
            LIMIT 1
            """,
            (task_id,),
            fetch=True,
        ) or []
        if not existing_rows:
            return jsonify({"success": False, "error": "Task not found"}), 404
        existing_task = existing_rows[0]
        was_auto_completed = (
            bool(existing_task.get("completed"))
            and (existing_task.get("completed_by") or "").strip().lower() == "auto-rule-engine"
        )
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

        undo_logged = False
        if not completed and was_auto_completed:
            undo_logged = record_auto_completion_undo(task_id, undone_by=getattr(g, "mobile_username", "mobile-user"))

        task_row = rows[0]
        return jsonify(
            {
                "success": True,
                "task_id": task_row["id"],
                "transaction_id": task_row.get("transaction_id"),
                "completed": bool(task_row.get("completed")),
                "status": task_row.get("status"),
                "completed_at": json_date_value(task_row.get("completed_at")),
                "undo_logged": undo_logged,
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
    notice = (request.args.get("notice") or "").strip()
    notice_type = (request.args.get("notice_type") or "success").strip().lower()
    if notice_type not in {"success", "warning", "error"}:
        notice_type = "success"

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

    heads_up_report = {
        "summary": {
            "healthy_count": 0,
            "watch_count": 0,
            "urgent_count": 0,
            "total_active": len(active_transactions),
            "accepted_count": 0,
            "dismissed_count": 0,
        },
        "open_watch": [],
        "open_urgent": [],
    }
    try:
        refresh_heads_up_if_stale(max_age_minutes=180, send_sms=False)
        heads_up_report = build_heads_up_report()
    except Exception as exc:
        print(f"Heads Up refresh error: {exc}")

    tc_name = (session.get("tc_username") or "margaret").capitalize()
    current_date_label = datetime.now().strftime("%A, %B %d, %Y")
    return render_template(
        "tc_dashboard.html",
        tc_name=tc_name,
        current_date_label=current_date_label,
        notice=notice,
        notice_type=notice_type,
        needs_review=needs_review,
        active_transactions=active_transactions,
        completed_transactions=completed_transactions,
        heads_up_summary=heads_up_report["summary"],
        heads_up_watch=heads_up_report["open_watch"][:3],
        heads_up_urgent=heads_up_report["open_urgent"][:3],
    )


@app.route("/tc/heads-up")
@login_required
def tc_heads_up():
    """Render daily Heads Up report with actionable suggestions."""
    notice = (request.args.get("notice") or "").strip()
    notice_type = (request.args.get("notice_type") or "success").strip().lower()
    if notice_type not in {"success", "warning", "error"}:
        notice_type = "success"

    refresh_heads_up_if_stale(max_age_minutes=120, send_sms=False)
    report = build_heads_up_report()
    preferences = fetch_pattern_preferences()
    pattern_rows = []
    for pattern_key, meta in HEADS_UP_PATTERN_META.items():
        pref = preferences.get(pattern_key, {"always_alert": True, "auto_handle": False})
        pattern_rows.append(
            {
                "pattern_key": pattern_key,
                "label": meta.get("label") or pattern_key,
                "description": meta.get("description") or "",
                "always_alert": bool(pref.get("always_alert")),
                "auto_handle": bool(pref.get("auto_handle")),
            }
        )

    return render_template(
        "tc_heads_up.html",
        notice=notice,
        notice_type=notice_type,
        report=report,
        pattern_rows=pattern_rows,
    )


@app.route("/tc/heads-up/refresh", methods=["POST"])
@login_required
def refresh_tc_heads_up():
    """Force-refresh Heads Up monitor from TC UI."""
    run_heads_up_monitor(send_sms=False)
    redirect_url = url_for(
        "tc_heads_up",
        notice="Heads Up report refreshed.",
        notice_type="success",
    )
    return redirect(redirect_url)


@app.route("/tc/heads-up/signal/<int:signal_id>/accept", methods=["POST"])
@login_required
def accept_tc_heads_up_signal(signal_id):
    """Accept one Heads Up suggestion (with optional edits)."""
    suggestion_override = (request.form.get("suggestion") or "").strip()
    task_id = accept_heads_up_signal(
        signal_id=signal_id,
        acted_by=session.get("tc_username", "margaret"),
        suggestion_override=suggestion_override,
        auto_handled=False,
    )
    if task_id is None:
        redirect_url = url_for(
            "tc_heads_up",
            notice="Could not accept this suggestion (already dismissed/resolved or unavailable).",
            notice_type="warning",
        )
        return redirect(redirect_url)

    redirect_url = url_for(
        "tc_heads_up",
        notice=f"Suggestion accepted. Task #{task_id} created.",
        notice_type="success",
    )
    return redirect(redirect_url)


@app.route("/tc/heads-up/signal/<int:signal_id>/dismiss", methods=["POST"])
@login_required
def dismiss_tc_heads_up_signal(signal_id):
    """Dismiss one Heads Up suggestion."""
    notes = (request.form.get("dismissal_notes") or "").strip()
    success = dismiss_heads_up_signal(
        signal_id=signal_id,
        dismissed_by=session.get("tc_username", "margaret"),
        notes=notes,
    )
    redirect_url = url_for(
        "tc_heads_up",
        notice=("Suggestion dismissed." if success else "Suggestion could not be dismissed."),
        notice_type=("success" if success else "warning"),
    )
    return redirect(redirect_url)


@app.route("/tc/heads-up/preferences", methods=["POST"])
@login_required
def save_tc_heads_up_preferences():
    """Save Heads Up preference toggles."""
    pattern_key = (request.form.get("pattern_key") or "").strip()
    always_alert = parse_bool_value(request.form.get("always_alert"), default=False)
    auto_handle = parse_bool_value(request.form.get("auto_handle"), default=False)
    ok = save_pattern_preference(
        pattern_key=pattern_key,
        always_alert=always_alert,
        auto_handle=auto_handle,
        updated_by=session.get("tc_username", "margaret"),
    )
    redirect_url = url_for(
        "tc_heads_up",
        notice=(
            "Heads Up preference saved."
            if ok
            else "Invalid pattern key. Preference not saved."
        ),
        notice_type=("success" if ok else "error"),
    )
    return redirect(redirect_url)


@app.route("/tc/health-report")
@login_required
def tc_health_report():
    """Render AI-powered transaction health report for Margaret."""
    ensure_problem_detection_tables()
    notice = (request.args.get("notice") or "").strip()
    notice_type = (request.args.get("notice_type") or "success").strip().lower()
    if notice_type not in {"success", "warning", "error"}:
        notice_type = "success"

    refresh_flag = (request.args.get("refresh") or "").strip().lower() in {"1", "true", "yes"}
    if refresh_flag:
        analyze_transaction_health(send_notifications=False)
        if not notice:
            notice = "Health report refreshed."
            notice_type = "success"
    else:
        try:
            run_problem_detection_if_stale(max_age_minutes=360, send_notifications=False)
        except Exception as exc:
            log_system_error("problem_detector", str(exc))

    report = fetch_latest_health_report(include_handled=False)
    if not report.get("run_id"):
        analyze_transaction_health(send_notifications=False)
        report = fetch_latest_health_report(include_handled=False)

    generated_at = report.get("generated_at")
    generated_at_ago = format_time_ago(generated_at) if generated_at else ""
    return render_template(
        "tc_health_report.html",
        notice=notice,
        notice_type=notice_type,
        report=report,
        healthy_count=report.get("healthy_count", 0),
        watch_count=report.get("watch_count", 0),
        urgent_count=report.get("urgent_count", 0),
        healthy_items=report.get("healthy_items") or [],
        watch_items=report.get("watch_items") or [],
        urgent_items=report.get("urgent_items") or [],
        generated_at_label=report.get("generated_at_label") or "",
        generated_at_ago=generated_at_ago,
    )


@app.route("/tc/suggestion/<int:transaction_id>/accept", methods=["POST"])
@login_required
def accept_suggestion(transaction_id):
    """
    Execute suggested action automatically from the health dashboard.
    """
    payload = request.get_json(silent=True) or request.form
    suggestion_action = (payload.get("action") or "").strip()
    if not suggestion_action:
        return jsonify({"success": False, "error": "missing_action"}), 400

    result = execute_suggestion_action(
        transaction_id=transaction_id,
        suggestion_action=suggestion_action,
        actor=session.get("tc_username", "margaret"),
    )
    if not result.get("success"):
        return jsonify(result), 400
    return jsonify(result), 200


@app.route("/tc/suggestion/accept", methods=["POST"])
@login_required
def accept_suggestion_alias():
    """Alias route: accept suggestion using JSON body transaction_id."""
    payload = request.get_json(silent=True) or request.form
    transaction_id = parse_optional_int(payload.get("transaction_id"))
    if not transaction_id:
        return jsonify({"success": False, "error": "missing_transaction_id"}), 400
    suggestion_action = (payload.get("action") or "").strip()
    if not suggestion_action:
        return jsonify({"success": False, "error": "missing_action"}), 400

    result = execute_suggestion_action(
        transaction_id=transaction_id,
        suggestion_action=suggestion_action,
        actor=session.get("tc_username", "margaret"),
    )
    if not result.get("success"):
        return jsonify(result), 400
    return jsonify(result), 200


@app.route("/tc/health-report/transaction/<int:transaction_id>/dismiss", methods=["POST"])
@login_required
def dismiss_health_report_transaction(transaction_id):
    """Mark current report issues for one transaction as handled."""
    payload = request.get_json(silent=True) or request.form
    run_id = parse_optional_int(payload.get("run_id"))
    ok = mark_problem_result_handled(
        transaction_id=transaction_id,
        run_id=run_id,
        handled_by=session.get("tc_username", "margaret"),
        notes=(payload.get("notes") or "").strip(),
    )
    if not ok:
        return jsonify({"success": False, "error": "not_found"}), 404
    return jsonify({"success": True}), 200


@app.route("/tc/problem-detection-settings", methods=["GET", "POST"])
@login_required
def tc_problem_detection_settings():
    """Configure sensitivity, notifications, auto-actions, and whitelist."""
    ensure_problem_detection_tables()
    notice = (request.args.get("notice") or "").strip()
    notice_type = (request.args.get("notice_type") or "success").strip().lower()
    if notice_type not in {"success", "warning", "error"}:
        notice_type = "success"

    if request.method == "POST":
        action = (request.form.get("action") or "").strip().lower()
        next_notice = "Problem detection settings updated."
        next_type = "success"

        if action == "update_settings":
            update_problem_detection_settings(
                sensitivity_level=request.form.get("sensitivity_level"),
                notification_mode=request.form.get("notification_mode"),
                ai_enabled=parse_bool_value(request.form.get("ai_enabled"), default=False),
                auto_execute_actions=request.form.getlist("auto_execute_actions"),
                updated_by=session.get("tc_username", "margaret"),
            )
        elif action == "add_whitelist":
            transaction_id = parse_optional_int(request.form.get("transaction_id"))
            if transaction_id:
                upsert_problem_detection_whitelist(
                    transaction_id=transaction_id,
                    reason=request.form.get("reason") or "",
                    active=True,
                )
                next_notice = "Transaction added to problem-detection whitelist."
            else:
                next_notice = "Select a transaction to whitelist."
                next_type = "warning"
        elif action == "remove_whitelist":
            whitelist_id = parse_optional_int(request.form.get("whitelist_id"))
            if whitelist_id:
                deactivate_problem_detection_whitelist(whitelist_id)
                next_notice = "Whitelist entry removed."
            else:
                next_notice = "Invalid whitelist row."
                next_type = "warning"
        elif action == "run_now":
            analyze_transaction_health(send_notifications=False)
            next_notice = "Problem detector run completed."
        else:
            next_notice = "Unknown settings action."
            next_type = "warning"

        return redirect(url_for("tc_problem_detection_settings", notice=next_notice, notice_type=next_type))

    settings = fetch_problem_detection_settings()
    whitelist_rows = fetch_problem_detection_whitelist(active_only=False)
    active_transactions = execute_query(
        """
        SELECT id, property_address, closing_date
        FROM transactions
        WHERE status = 'ACTIVE'
        ORDER BY COALESCE(closing_date, CURRENT_DATE + INTERVAL '365 days') ASC, id ASC
        """,
        fetch=True,
    ) or []
    transaction_lookup = {row["id"]: row for row in active_transactions}
    for row in whitelist_rows:
        transaction = transaction_lookup.get(row.get("transaction_id"))
        if transaction:
            row["property_address"] = transaction.get("property_address") or f"Transaction #{row.get('transaction_id')}"
            row["closing_label"] = (
                transaction["closing_date"].strftime("%b %d, %Y") if transaction.get("closing_date") else "TBD"
            )
        else:
            row["property_address"] = f"Transaction #{row.get('transaction_id')}"
            row["closing_label"] = "Unknown"

    return render_template(
        "tc_problem_detection_settings.html",
        notice=notice,
        notice_type=notice_type,
        settings=settings,
        whitelist_rows=whitelist_rows,
        active_transactions=active_transactions,
    )


@app.route("/tc/bulk-messages", methods=["GET", "POST"])
@login_required
def tc_bulk_messages():
    """Bulk SMS broadcasting workspace with preview + queued sending."""
    ensure_bulk_messaging_tables()
    notice = (request.args.get("notice") or "").strip()
    notice_type = (request.args.get("notice_type") or "success").strip().lower()
    if notice_type not in {"success", "warning", "error"}:
        notice_type = "success"

    templates = fetch_bulk_message_templates()
    template_lookup = {str(item["id"]): item for item in templates}
    status_options = fetch_bulk_message_status_options()
    if "ACTIVE" not in status_options:
        status_options = ["ACTIVE", *status_options]
    history_rows = fetch_bulk_message_history(limit=10)

    form_state = {
        "filter_scope": "all_active",
        "filter_status": "ACTIVE",
        "party_type": "all_parties",
        "template_id": "",
        "template_name": "",
        "template_body": "",
    }
    preview_data = None

    job_id = parse_optional_int(request.args.get("job_id"))
    if request.method == "POST":
        action = (request.form.get("action") or "").strip().lower()
        form_state["filter_scope"] = (request.form.get("filter_scope") or "all_active").strip().lower()
        form_state["filter_status"] = (request.form.get("filter_status") or "ACTIVE").strip().upper()
        form_state["party_type"] = (request.form.get("party_type") or "all_parties").strip().lower()
        form_state["template_id"] = (request.form.get("template_id") or "").strip()
        form_state["template_name"] = (request.form.get("template_name") or "").strip()

        template_body_input = (request.form.get("template_body") or "").strip()
        if not template_body_input and form_state["template_id"] in template_lookup:
            template_body_input = (template_lookup[form_state["template_id"]].get("template_body") or "").strip()
            if not form_state["template_name"]:
                form_state["template_name"] = template_lookup[form_state["template_id"]].get("template_name") or ""
        form_state["template_body"] = template_body_input

        if action == "save_template":
            template_name = (request.form.get("new_template_name") or "").strip()
            result = save_bulk_message_template(
                template_name=template_name,
                template_body=template_body_input,
                created_by=session.get("tc_username", "margaret"),
            )
            redirect_url = url_for(
                "tc_bulk_messages",
                notice=("Template saved." if result.get("success") else result.get("error", "Template save failed.")),
                notice_type=("success" if result.get("success") else "warning"),
            )
            return redirect(redirect_url)

        if action in {"preview", "queue_send"}:
            if not template_body_input:
                notice = "Template body is required."
                notice_type = "warning"
            else:
                preview_data = build_bulk_message_preview(
                    template_body=template_body_input,
                    filter_scope=form_state["filter_scope"],
                    filter_status=form_state["filter_status"],
                    party_type=form_state["party_type"],
                    max_preview_rows=120,
                )
                if action == "queue_send":
                    queue_result = queue_bulk_message_job(
                        template_used=form_state["template_name"] or "Custom Template",
                        template_body=template_body_input,
                        filter_scope=form_state["filter_scope"],
                        filter_status=form_state["filter_status"],
                        party_type=form_state["party_type"],
                        created_by=session.get("tc_username", "margaret"),
                    )
                    if not queue_result.get("success"):
                        notice = queue_result.get("error", "Unable to queue bulk message send.")
                        notice_type = "warning"
                    else:
                        redirect_url = url_for(
                            "tc_bulk_messages",
                            job_id=queue_result["job_id"],
                            notice=(
                                "Bulk broadcast queued. Messages send at 1 per second. "
                                "Keep this page open to track progress."
                            ),
                            notice_type="success",
                        )
                        return redirect(redirect_url)

    if form_state["template_id"] in template_lookup and not form_state["template_body"]:
        selected = template_lookup[form_state["template_id"]]
        form_state["template_name"] = selected.get("template_name") or form_state["template_name"]
        form_state["template_body"] = selected.get("template_body") or ""

    job_progress = fetch_bulk_message_progress(job_id) if job_id else None
    return render_template(
        "tc_bulk_messages.html",
        notice=notice,
        notice_type=notice_type,
        templates=templates,
        smart_variables=SMART_TEMPLATE_VARIABLES,
        status_options=status_options,
        form_state=form_state,
        preview_data=preview_data,
        job_id=job_id,
        job_progress=job_progress,
        history_rows=history_rows,
    )


@app.route("/tc/bulk-messages/<int:job_id>/progress")
@login_required
def tc_bulk_messages_progress(job_id):
    """Return JSON progress for a queued bulk SMS job."""
    progress = fetch_bulk_message_progress(job_id)
    if not progress:
        return jsonify({"success": False, "error": "Job not found"}), 404
    return jsonify({"success": True, "job": progress})


@app.route("/tc/status-updates", methods=["GET", "POST"])
@login_required
def tc_status_updates():
    """Configure, preview, and send weekly automated agent status updates."""
    ensure_agent_status_update_tables()
    notice = (request.args.get("notice") or "").strip()
    notice_type = (request.args.get("notice_type") or "success").strip().lower()
    if notice_type not in {"success", "warning", "error"}:
        notice_type = "success"

    settings = fetch_agent_status_update_settings()
    form_state = {
        "enabled": bool(settings.get("enabled")),
        "schedule_slot": settings.get("schedule_slot") or "monday_8am",
        "subject_template": settings.get("subject_template") or "",
        "body_template": settings.get("body_template") or "",
    }
    preview_payloads = []

    if request.method == "POST":
        action = (request.form.get("action") or "").strip().lower()
        form_state["enabled"] = parse_bool_value(request.form.get("enabled"), default=False)
        form_state["schedule_slot"] = (request.form.get("schedule_slot") or form_state["schedule_slot"]).strip().lower()
        form_state["subject_template"] = (request.form.get("subject_template") or "").strip() or settings.get("subject_template")
        form_state["body_template"] = (request.form.get("body_template") or "").strip() or settings.get("body_template")

        if action == "update_settings":
            update_agent_status_update_settings(
                enabled=form_state["enabled"],
                schedule_slot=form_state["schedule_slot"],
                subject_template=form_state["subject_template"],
                body_template=form_state["body_template"],
                updated_by=session.get("tc_username", "margaret"),
            )
            redirect_url = url_for(
                "tc_status_updates",
                notice="Status update settings saved.",
                notice_type="success",
            )
            return redirect(redirect_url)

        if action == "add_opt_out":
            result = add_agent_status_opt_out(
                agent_name=request.form.get("agent_name") or "",
                agent_email=request.form.get("agent_email") or "",
                agent_phone=request.form.get("agent_phone") or "",
                reason=request.form.get("reason") or "",
                active=True,
            )
            redirect_url = url_for(
                "tc_status_updates",
                notice=("Agent opt-out saved." if result.get("success") else result.get("error", "Could not add opt-out.")),
                notice_type=("success" if result.get("success") else "warning"),
            )
            return redirect(redirect_url)

        if action == "remove_opt_out":
            opt_out_id = parse_optional_int(request.form.get("opt_out_id"))
            if opt_out_id:
                deactivate_agent_status_opt_out(opt_out_id)
                next_notice = "Agent opt-out removed."
                next_type = "success"
            else:
                next_notice = "Invalid opt-out row."
                next_type = "warning"
            return redirect(url_for("tc_status_updates", notice=next_notice, notice_type=next_type))

        if action == "send_now":
            result = dispatch_agent_status_updates(
                preview_only=False,
                run_kind="manual",
                triggered_by=session.get("tc_username", "margaret"),
                template_overrides={
                    "subject_template": form_state["subject_template"],
                    "body_template": form_state["body_template"],
                },
                force_send=True,
            )
            if not result.get("success"):
                next_notice = result.get("error") or "Failed to run status updates."
                next_type = "error"
            elif result.get("skipped"):
                next_notice = f"Status update send skipped: {result.get('reason', 'n/a')}."
                next_type = "warning"
            else:
                next_notice = (
                    f"Status updates sent. Candidates: {result.get('candidate_count', 0)} | "
                    f"Sent: {result.get('sent_count', 0)} | Failed: {result.get('failed_count', 0)}"
                )
                next_type = "success" if result.get("failed_count", 0) == 0 else "warning"
            return redirect(url_for("tc_status_updates", notice=next_notice, notice_type=next_type))

        if action == "preview_now":
            preview_result = dispatch_agent_status_updates(
                preview_only=True,
                run_kind="manual",
                triggered_by=session.get("tc_username", "margaret"),
                template_overrides={
                    "subject_template": form_state["subject_template"],
                    "body_template": form_state["body_template"],
                },
                force_send=True,
            )
            if not preview_result.get("success"):
                notice = preview_result.get("error") or "Could not generate preview."
                notice_type = "error"
            else:
                preview_payloads = (preview_result.get("payloads") or [])[:24]
                notice = (
                    f"Preview generated for {preview_result.get('candidate_count', len(preview_payloads))} "
                    "agent status updates."
                )
                notice_type = "success"
        else:
            if action not in {"update_settings", "add_opt_out", "remove_opt_out", "send_now"}:
                notice = "Unknown status update action."
                notice_type = "warning"

    opt_out_rows = fetch_agent_status_opt_outs(active_only=False)
    recent_runs = fetch_agent_status_update_runs(limit=20)
    metrics = fetch_agent_status_update_metrics(weeks=8)
    return render_template(
        "tc_status_updates.html",
        notice=notice,
        notice_type=notice_type,
        form_state=form_state,
        schedule_slot_options=SCHEDULE_SLOT_OPTIONS,
        template_tokens=AGENT_STATUS_TEMPLATE_TOKENS,
        opt_out_rows=opt_out_rows,
        preview_payloads=preview_payloads,
        metrics=metrics,
        recent_runs=recent_runs,
    )


@app.route("/tc/common-qa", methods=["GET", "POST"])
@login_required
def tc_common_qa():
    """Manage reusable Smart Q&A responses and analytics."""
    ensure_common_qa_tables()
    notice = (request.args.get("notice") or "").strip()
    notice_type = (request.args.get("notice_type") or "success").strip().lower()
    if notice_type not in {"success", "warning", "error"}:
        notice_type = "success"

    if request.method == "POST":
        action = (request.form.get("action") or "").strip().lower()
        next_notice = "Q&A settings updated."
        next_type = "success"

        if action == "add":
            question_text = (request.form.get("question_text") or "").strip()
            answer_text = (request.form.get("answer_text") or "").strip()
            asked_by_party = (request.form.get("asked_by_party") or "agent").strip().lower()
            category = normalize_common_qa_category(
                request.form.get("category"),
                fallback=infer_common_qa_category(question_text),
            )
            transaction_id = parse_optional_int(request.form.get("transaction_id"))
            created = create_common_qa_entry(
                question_text=question_text,
                answer_text=answer_text,
                transaction_id=transaction_id,
                asked_by_party=asked_by_party,
                category=category,
                force_new=True,
            )
            if created:
                log_common_qa_event(
                    event_type="manual_qa_added",
                    common_qa_id=created["id"],
                    transaction_id=transaction_id,
                    channel="tc_ui",
                    asked_by_party=asked_by_party,
                    question_text=question_text,
                    answer_text=answer_text,
                    auto_answer=False,
                )
                next_notice = "Common Q&A entry added."
            else:
                next_notice = "Could not add common Q&A entry."
                next_type = "error"

        elif action == "update":
            qa_id = parse_optional_int(request.form.get("qa_id"))
            answer_text = (request.form.get("answer_text") or "").strip()
            category = normalize_common_qa_category(request.form.get("category"), fallback="general")
            auto_answer = parse_bool_value(request.form.get("auto_answer"), default=False)
            if not qa_id or not answer_text:
                next_notice = "Question ID and answer are required."
                next_type = "warning"
            else:
                updated = update_common_qa_entry(
                    common_qa_id=qa_id,
                    answer_text=answer_text,
                    category=category,
                    auto_answer=auto_answer,
                )
                if updated:
                    log_common_qa_event(
                        event_type="manual_qa_updated",
                        common_qa_id=qa_id,
                        transaction_id=updated.get("transaction_id"),
                        channel="tc_ui",
                        asked_by_party=updated.get("asked_by_party"),
                        question_text=updated.get("question_text"),
                        answer_text=answer_text,
                        auto_answer=bool(auto_answer),
                    )
                    next_notice = "Common Q&A entry updated."
                else:
                    next_notice = "Could not update common Q&A entry."
                    next_type = "error"

        elif action == "toggle_auto":
            qa_id = parse_optional_int(request.form.get("qa_id"))
            auto_answer = parse_bool_value(request.form.get("auto_answer"), default=False)
            if not qa_id:
                next_notice = "Invalid Q&A row."
                next_type = "warning"
            else:
                updated = update_common_qa_entry(common_qa_id=qa_id, auto_answer=auto_answer)
                if updated:
                    log_common_qa_event(
                        event_type="manual_auto_toggle",
                        common_qa_id=qa_id,
                        transaction_id=updated.get("transaction_id"),
                        channel="tc_ui",
                        asked_by_party=updated.get("asked_by_party"),
                        question_text=updated.get("question_text"),
                        answer_text=updated.get("answer_text"),
                        auto_answer=bool(auto_answer),
                    )
                    next_notice = "Auto-answer setting updated."
                else:
                    next_notice = "Could not update auto-answer setting."
                    next_type = "error"
        else:
            next_notice = "Unknown common Q&A action."
            next_type = "warning"

        return redirect(url_for("tc_common_qa", notice=next_notice, notice_type=next_type))

    selected_category = normalize_common_qa_category(request.args.get("category"), fallback="")
    search_text = (request.args.get("q") or "").strip()
    qa_rows = fetch_common_qa_rows(
        limit=400,
        category=(selected_category if selected_category else None),
        search_text=search_text,
    )
    for row in qa_rows:
        row["auto_enabled_label"] = "Enabled" if row.get("auto_answer") else "Disabled"
        row["updated_at_label"] = format_timestamp_label(row.get("updated_at"))
        row["last_used_label"] = format_timestamp_label(row.get("last_used_at"))

    analytics = fetch_common_qa_analytics()
    faq_draft = build_agent_faq_draft(limit=18)
    return render_template(
        "tc_common_qa.html",
        notice=notice,
        notice_type=notice_type,
        qa_rows=qa_rows,
        category_options=COMMON_QA_CATEGORY_OPTIONS,
        selected_category=selected_category,
        search_text=search_text,
        analytics=analytics,
        faq_draft=faq_draft,
        auto_threshold_pct=AUTO_ANSWER_CONFIDENCE_THRESHOLD,
        suggest_threshold_pct=SUGGEST_CONFIDENCE_THRESHOLD,
    )


@app.route("/tc/calendar-sync", methods=["GET", "POST"])
@login_required
def tc_calendar_sync():
    """Manage Google Calendar sync settings, metrics, and manual runs."""
    ensure_calendar_sync_tables()
    notice = (request.args.get("notice") or "").strip()
    notice_type = (request.args.get("notice_type") or "success").strip().lower()
    if notice_type not in {"success", "warning", "error"}:
        notice_type = "success"

    if request.method == "POST":
        action = (request.form.get("action") or "").strip().lower()
        if action == "update_settings":
            updated = update_calendar_sync_settings(
                {
                    "enabled": parse_bool_value(request.form.get("enabled"), default=False),
                    "calendar_id": request.form.get("calendar_id"),
                    "timezone": request.form.get("timezone"),
                    "sync_deadlines": parse_bool_value(request.form.get("sync_deadlines"), default=False),
                    "sync_inspections": parse_bool_value(request.form.get("sync_inspections"), default=False),
                    "sync_closings": parse_bool_value(request.form.get("sync_closings"), default=False),
                    "sync_appraisals": parse_bool_value(request.form.get("sync_appraisals"), default=False),
                    "two_way_sync_enabled": parse_bool_value(request.form.get("two_way_sync_enabled"), default=False),
                    "auto_delete_on_cancel": parse_bool_value(request.form.get("auto_delete_on_cancel"), default=True),
                    "closing_default_time": request.form.get("closing_default_time"),
                    "closing_duration_minutes": parse_optional_int(request.form.get("closing_duration_minutes")) or 60,
                },
                updated_by=session.get("tc_username", "margaret"),
            )
            next_notice = (
                f"Calendar sync settings saved (calendar={updated.get('calendar_id')} timezone={updated.get('timezone')})."
            )
            return redirect(url_for("tc_calendar_sync", notice=next_notice, notice_type="success"))

        if action == "sync_active_now":
            rows = execute_query(
                """
                SELECT id
                FROM transactions
                WHERE status = 'ACTIVE'
                ORDER BY COALESCE(closing_date, CURRENT_DATE + INTERVAL '365 days') ASC, id ASC
                LIMIT 250
                """,
                fetch=True,
            ) or []
            synced_txn = 0
            failed_txn = 0
            for row in rows:
                result = sync_transaction_calendar_bundle(
                    transaction_id=row["id"],
                    actor=session.get("tc_username", "margaret"),
                    force_update=True,
                    include_deadlines=True,
                    include_closing=True,
                    include_vendor_events=True,
                )
                if result.get("success"):
                    synced_txn += 1
                else:
                    failed_txn += 1
            next_notice = (
                f"Calendar sync run complete. Active transactions synced: {synced_txn}; failed: {failed_txn}."
            )
            next_type = "success" if failed_txn == 0 else "warning"
            return redirect(url_for("tc_calendar_sync", notice=next_notice, notice_type=next_type))

        if action == "register_channel":
            channel_id = (request.form.get("channel_id") or "").strip()
            resource_id = (request.form.get("resource_id") or "").strip()
            resource_uri = (request.form.get("resource_uri") or "").strip()
            expiration_ms = request.form.get("expiration_ms")
            if not channel_id:
                return redirect(
                    url_for(
                        "tc_calendar_sync",
                        notice="Channel ID is required.",
                        notice_type="warning",
                    )
                )
            upsert_calendar_webhook_channel(
                channel_id=channel_id,
                resource_id=resource_id,
                resource_uri=resource_uri,
                expiration_ms=expiration_ms,
                active=True,
            )
            return redirect(
                url_for(
                    "tc_calendar_sync",
                    notice="Webhook channel metadata stored.",
                    notice_type="success",
                )
            )

        return redirect(url_for("tc_calendar_sync", notice="Unknown calendar action.", notice_type="warning"))

    settings = fetch_calendar_sync_settings()
    metrics = fetch_calendar_sync_metrics(months=3)
    recent_audit = execute_query(
        """
        SELECT
            l.id, l.transaction_id, l.action, l.event_type, l.success, l.details, l.created_at,
            t.property_address
        FROM calendar_sync_audit_log l
        LEFT JOIN transactions t ON t.id = l.transaction_id
        ORDER BY l.created_at DESC, l.id DESC
        LIMIT 60
        """,
        fetch=True,
    ) or []
    for row in recent_audit:
        row["created_at_label"] = format_timestamp_label(row.get("created_at"))
        row["status_label"] = "Success" if row.get("success") else "Failed"
        row["event_type_label"] = (row.get("event_type") or "general").replace("_", " ").title()
        row["action_label"] = (row.get("action") or "sync").replace("_", " ").title()

    recent_channels = execute_query(
        """
        SELECT id, channel_id, resource_id, resource_uri, expiration_at, active, updated_at
        FROM calendar_webhook_channels
        ORDER BY updated_at DESC, id DESC
        LIMIT 30
        """,
        fetch=True,
    ) or []
    for row in recent_channels:
        row["expiration_label"] = format_timestamp_label(row.get("expiration_at"))
        row["updated_label"] = format_timestamp_label(row.get("updated_at"))

    return render_template(
        "tc_calendar_sync.html",
        notice=notice,
        notice_type=notice_type,
        settings=settings,
        metrics=metrics,
        recent_audit=recent_audit,
        recent_channels=recent_channels,
    )


@app.route("/tc/transaction/<int:transaction_id>/calendar-sync", methods=["POST"])
@login_required
def sync_transaction_calendar_now(transaction_id):
    """Manual override to sync or clear transaction calendar events."""
    transaction = get_transaction_or_none(transaction_id)
    if not transaction:
        return "Transaction not found", 404

    action = (request.form.get("action") or "sync").strip().lower()
    if action == "delete_events":
        deleted = delete_calendar_events(transaction_id=transaction_id, reason="manual_override")
        notice = (
            f"Calendar cleanup complete. Removed: {deleted.get('deleted', 0)}; "
            f"failed: {deleted.get('failed', 0)}."
        )
        notice_type = "success" if deleted.get("failed", 0) == 0 else "warning"
    else:
        result = sync_transaction_calendar_bundle(
            transaction_id=transaction_id,
            actor=session.get("tc_username", "margaret"),
            force_update=True,
            include_deadlines=True,
            include_closing=True,
            include_vendor_events=True,
        )
        notice = (
            "Calendar sync complete. "
            f"Deadlines: {result.get('deadline_synced', 0)} synced / {result.get('deadline_skipped', 0)} skipped / {result.get('deadline_failed', 0)} failed; "
            f"Closing synced: {'yes' if result.get('closing_synced') else 'no'}; "
            f"Vendor events: {result.get('vendor_synced', 0)} synced / {result.get('vendor_failed', 0)} failed."
        )
        notice_type = (
            "success"
            if (
                result.get("deadline_failed", 0) == 0
                and result.get("vendor_failed", 0) == 0
                and not result.get("closing_failed")
            )
            else "warning"
        )

    redirect_url = url_for(
        "tc_transaction",
        transaction_id=transaction_id,
        doc_notice=notice,
        doc_notice_type=notice_type,
    )
    return redirect(f"{redirect_url}#calendar-sync")


@app.route("/tc/transaction/<int:transaction_id>/calendar-closing", methods=["POST"])
@login_required
def save_transaction_calendar_closing(transaction_id):
    """Save closing calendar preferences and force-sync closing event."""
    transaction = get_transaction_or_none(transaction_id)
    if not transaction:
        return "Transaction not found", 404
    if not transaction.get("closing_date"):
        redirect_url = url_for(
            "tc_transaction",
            transaction_id=transaction_id,
            doc_notice="Set closing date before saving calendar closing time.",
            doc_notice_type="warning",
        )
        return redirect(f"{redirect_url}#calendar-sync")

    closing_time = parse_optional_hhmm(request.form.get("closing_time")) or ""
    closing_location = (request.form.get("closing_location") or "").strip()
    duration = parse_optional_int(request.form.get("closing_duration_minutes")) or 60
    upsert_transaction_calendar_preferences(
        transaction_id=transaction_id,
        closing_time=closing_time,
        closing_duration_minutes=duration,
        closing_location=closing_location,
        updated_by=session.get("tc_username", "margaret"),
    )
    result = _sync_closing_event_for_transaction(
        transaction_id=transaction_id,
        transaction_row=transaction,
        force_update=True,
    )
    notice = (
        "Closing calendar preferences saved and synced."
        if result.get("success")
        else f"Preferences saved, but closing sync failed: {result.get('error') or result.get('skipped') or 'unknown'}"
    )
    notice_type = "success" if result.get("success") else "warning"
    redirect_url = url_for(
        "tc_transaction",
        transaction_id=transaction_id,
        doc_notice=notice,
        doc_notice_type=notice_type,
    )
    return redirect(f"{redirect_url}#calendar-sync")


@app.route("/tc/closing-checklists", methods=["GET", "POST"])
@login_required
def tc_closing_checklists():
    """Queue, review, and auto-send dynamic closing checklists."""
    ensure_closing_checklist_tables()
    notice = (request.args.get("notice") or "").strip()
    notice_type = (request.args.get("notice_type") or "success").strip().lower()
    if notice_type not in {"success", "warning", "error"}:
        notice_type = "success"

    if request.method == "POST":
        action = (request.form.get("action") or "").strip().lower()
        if action == "refresh_due":
            summary = generate_due_closing_checklists(days_before=3)
            notice = (
                "Closing checklist trigger completed: "
                f"candidates={summary.get('candidate_count', 0)} "
                f"generated={summary.get('generated', 0)} "
                f"skipped_existing={summary.get('skipped_existing', 0)} "
                f"failed={summary.get('failed', 0)}"
            )
            notice_type = "success" if summary.get("failed", 0) == 0 else "warning"
        elif action == "auto_send_now":
            summary = auto_send_unreviewed_closing_checklists()
            notice = (
                "Auto-send run completed: "
                f"candidates={summary.get('candidate_count', 0)} "
                f"auto_sent={summary.get('auto_sent', 0)} "
                f"failed={summary.get('failed', 0)}"
            )
            notice_type = "success" if summary.get("failed", 0) == 0 else "warning"
        else:
            notice = "Unknown closing checklist action."
            notice_type = "warning"
        return redirect(url_for("tc_closing_checklists", notice=notice, notice_type=notice_type))

    checklists = fetch_closing_checklists_for_tc(limit=120)
    for row in checklists:
        row["status_label"] = closing_checklist_status_label(row.get("status"))
        row["closing_date_label"] = format_date_label(row.get("closing_date"))
        row["generated_at_label"] = format_timestamp_label(row.get("generated_at"))
        row["auto_send_after_label"] = format_timestamp_label(row.get("auto_send_after"))
        row["item_count"] = int((row.get("summary") or {}).get("item_count") or 0)

    return render_template(
        "tc_closing_checklists.html",
        notice=notice,
        notice_type=notice_type,
        checklists=checklists,
    )


@app.route("/tc/transaction/<int:transaction_id>/generate-closing-checklist", methods=["POST"])
@login_required
def generate_transaction_closing_checklist(transaction_id):
    """Generate one dynamic closing checklist for a transaction."""
    ensure_closing_checklist_tables()
    result = generate_closing_checklist(
        transaction_id=transaction_id,
        trigger_source="manual_tc_action",
    )
    if not result.get("success"):
        return redirect(
            url_for(
                "tc_transaction",
                transaction_id=transaction_id,
                doc_notice=f"Could not generate closing checklist: {result.get('error', 'unknown error')}",
                doc_notice_type="error",
            )
        )
    checklist_id = result["checklist"]["id"]
    return redirect(
        url_for(
            "tc_closing_checklist_detail",
            checklist_id=checklist_id,
            notice="Dynamic closing checklist generated.",
            notice_type="success",
        )
    )


@app.route("/tc/closing-checklist/<int:checklist_id>", methods=["GET", "POST"])
@login_required
def tc_closing_checklist_detail(checklist_id):
    """Review and edit dynamic closing checklist before party distribution."""
    ensure_closing_checklist_tables()
    checklist = fetch_closing_checklist(checklist_id)
    if not checklist:
        return "Closing checklist not found.", 404

    if request.method == "POST":
        action = (request.form.get("action") or "").strip().lower()
        notice = "Checklist updated."
        notice_type = "success"

        if action == "add_item":
            section_title = (request.form.get("section_title") or "CUSTOM ITEMS").strip()
            item_text = (request.form.get("item_text") or "").strip()
            if not item_text:
                notice = "Item text is required."
                notice_type = "warning"
            else:
                add_closing_checklist_item(checklist_id, section_title=section_title, item_text=item_text, source_type="margaret")
                regenerate_closing_checklist_pdf(checklist_id)
                notice = "Checklist item added."
        elif action == "remove_item":
            item_id = parse_optional_int(request.form.get("item_id"))
            if not item_id:
                notice = "Invalid checklist item."
                notice_type = "warning"
            else:
                remove_closing_checklist_item(checklist_id, item_id=item_id)
                regenerate_closing_checklist_pdf(checklist_id)
                notice = "Checklist item removed."
        elif action == "toggle_item":
            item_id = parse_optional_int(request.form.get("item_id"))
            completed = parse_bool_value(request.form.get("completed"), default=False)
            if not item_id:
                notice = "Invalid checklist item."
                notice_type = "warning"
            else:
                toggle_closing_checklist_item(
                    checklist_id=checklist_id,
                    item_id=item_id,
                    completed=completed,
                    actor_role="tc",
                    actor_name=session.get("tc_username", "margaret"),
                )
                regenerate_closing_checklist_pdf(checklist_id)
                notice = "Checklist item status updated."
        elif action == "regenerate_pdf":
            result = regenerate_closing_checklist_pdf(checklist_id)
            notice = "Checklist PDF regenerated." if result else "Unable to regenerate checklist PDF."
            notice_type = "success" if result else "warning"
        elif action == "approve_send":
            result = approve_and_send_closing_checklist(
                checklist_id=checklist_id,
                approved_by=session.get("tc_username", "margaret"),
            )
            if result.get("success"):
                delivery = result.get("delivery") or {}
                notice = (
                    "Checklist approved and sent. "
                    f"Emails: {delivery.get('sent_email_count', 0)} | SMS: {delivery.get('sent_sms_count', 0)}"
                )
                notice_type = "success"
            else:
                notice = f"Could not send checklist: {result.get('error', 'unknown error')}"
                notice_type = "error"
        elif action == "resend_now":
            result = send_closing_checklist(
                checklist_id=checklist_id,
                actor=session.get("tc_username", "margaret"),
                auto=False,
            )
            if result.get("success"):
                delivery = result.get("delivery") or {}
                notice = (
                    "Checklist resent. "
                    f"Emails: {delivery.get('sent_email_count', 0)} | SMS: {delivery.get('sent_sms_count', 0)}"
                )
                notice_type = "success"
            else:
                notice = f"Could not resend checklist: {result.get('error', 'unknown error')}"
                notice_type = "error"
        else:
            notice = "Unknown checklist action."
            notice_type = "warning"

        return redirect(
            url_for(
                "tc_closing_checklist_detail",
                checklist_id=checklist_id,
                notice=notice,
                notice_type=notice_type,
            )
        )

    checklist = fetch_closing_checklist(checklist_id)
    transaction = get_transaction_or_none(checklist["transaction_id"])
    if not transaction:
        return "Transaction not found.", 404
    items = fetch_closing_checklist_items(checklist_id)
    recipients = fetch_closing_checklist_recipients(checklist_id)
    for recipient in recipients:
        recipient["checklist_url"] = closing_checklist_public_url(recipient.get("access_token"))
        recipient["party_role_label"] = (recipient.get("party_role") or "party").replace("_", " ").title()

    checklist_pdf_url = ""
    if checklist.get("pdf_s3_key"):
        checklist_pdf_url = get_presigned_url(checklist["pdf_s3_key"], expiration=60 * 60 * 24 * 7) or ""

    for item in items:
        item["source_label"] = (item.get("source_type") or "base").replace("_", " ").title()
        item["completed_label"] = "Completed" if item.get("completed") else "Open"
        item["completed_at_label"] = format_timestamp_label(item.get("completed_at"))

    notice = (request.args.get("notice") or "").strip()
    notice_type = (request.args.get("notice_type") or "success").strip().lower()
    if notice_type not in {"success", "warning", "error"}:
        notice_type = "success"

    return render_template(
        "tc_closing_checklist_detail.html",
        notice=notice,
        notice_type=notice_type,
        checklist=checklist,
        checklist_status_label=closing_checklist_status_label(checklist.get("status")),
        checklist_pdf_url=checklist_pdf_url,
        checklist_sections=build_closing_checklist_sections(items),
        recipients=recipients,
        transaction=transaction,
    )


@app.route("/closing-checklist/<access_token>")
def public_closing_checklist(access_token):
    """Public interactive checklist view for recipients."""
    ensure_closing_checklist_tables()
    payload = fetch_closing_checklist_by_access_token(access_token)
    if not payload:
        return "Checklist link is invalid or expired.", 404
    mark_closing_checklist_recipient_viewed(payload["recipient_id"])

    items = fetch_closing_checklist_items(payload["checklist_id"])
    for item in items:
        item["completed_label"] = "Completed" if item.get("completed") else "Open"

    checklist_pdf_url = ""
    if payload.get("pdf_s3_key"):
        checklist_pdf_url = get_presigned_url(payload["pdf_s3_key"], expiration=60 * 60 * 24 * 7) or ""

    return render_template(
        "closing_checklist_party.html",
        checklist=payload,
        checklist_status_label=closing_checklist_status_label(payload.get("status")),
        checklist_sections=build_closing_checklist_sections(items),
        checklist_pdf_url=checklist_pdf_url,
    )


@app.route("/closing-checklist/<access_token>/item/<int:item_id>/toggle", methods=["POST"])
def toggle_public_closing_checklist_item(access_token, item_id):
    """Toggle one checklist item from the public recipient checklist page."""
    ensure_closing_checklist_tables()
    payload = fetch_closing_checklist_by_access_token(access_token)
    if not payload:
        return jsonify({"success": False, "error": "Invalid checklist link"}), 404

    request_json = request.get_json(silent=True) or {}
    if request_json:
        completed = parse_bool_value(request_json.get("completed"), default=False)
    else:
        completed = parse_bool_value(request.form.get("completed"), default=False)

    toggle_closing_checklist_item(
        checklist_id=payload["checklist_id"],
        item_id=item_id,
        completed=completed,
        actor_role=payload.get("party_role") or "party",
        actor_name=payload.get("recipient_name") or "Checklist Party",
    )
    return jsonify({"success": True, "completed": completed})


@app.route("/tc/task-completion/run", methods=["POST"])
@login_required
def run_task_completion_now():
    """Manually run task auto-completion checks from TC UI."""
    summary = check_task_completion()
    redirect_url = url_for(
        "tc_tasks",
        notice=(
            "Task auto-completion run complete: "
            f"checked={summary['checked_tasks']} "
            f"auto-completed={summary['auto_completed']} "
            f"review-flags={summary['flagged_review']}"
        ),
        notice_type="success",
    )
    return redirect(redirect_url)


@app.route("/tc/vendors", methods=["GET", "POST"])
@login_required
def tc_vendors():
    """Manage vendor directory, preferences, and performance metrics."""
    ensure_vendor_automation_tables()
    notice = (request.args.get("notice") or "").strip()
    notice_type = (request.args.get("notice_type") or "success").strip().lower()
    if notice_type not in {"success", "warning", "error"}:
        notice_type = "success"

    if request.method == "POST":
        action = (request.form.get("action") or "").strip().lower()
        redirect_notice = ""
        redirect_type = "success"

        try:
            if action == "add":
                payload = {
                    "vendor_type": normalize_vendor_type(request.form.get("vendor_type")),
                    "company_name": request.form.get("company_name"),
                    "contact_name": request.form.get("contact_name"),
                    "email": request.form.get("email"),
                    "phone": request.form.get("phone"),
                    "scheduling_url": request.form.get("scheduling_url"),
                    "service_area": request.form.get("service_area"),
                    "preferred": parse_bool_value(request.form.get("preferred"), default=False),
                    "active": parse_bool_value(request.form.get("active"), default=True),
                    "notes": request.form.get("notes"),
                }
                if payload["vendor_type"] not in VENDOR_TYPES:
                    redirect_notice = "Invalid vendor type."
                    redirect_type = "error"
                else:
                    vendor_id = create_vendor_contact(payload)
                    if vendor_id:
                        redirect_notice = "Vendor contact added."
                    else:
                        redirect_notice = "Could not add vendor contact."
                        redirect_type = "error"

            elif action == "update":
                vendor_id = parse_optional_int(request.form.get("vendor_id"))
                if not vendor_id:
                    redirect_notice = "Vendor ID missing."
                    redirect_type = "error"
                else:
                    payload = {
                        "vendor_type": normalize_vendor_type(request.form.get("vendor_type")),
                        "company_name": request.form.get("company_name"),
                        "contact_name": request.form.get("contact_name"),
                        "email": request.form.get("email"),
                        "phone": request.form.get("phone"),
                        "scheduling_url": request.form.get("scheduling_url"),
                        "service_area": request.form.get("service_area"),
                        "preferred": parse_bool_value(request.form.get("preferred"), default=False),
                        "active": parse_bool_value(request.form.get("active"), default=False),
                        "notes": request.form.get("notes"),
                    }
                    if payload["vendor_type"] not in VENDOR_TYPES:
                        redirect_notice = "Invalid vendor type."
                        redirect_type = "error"
                    else:
                        ok = update_vendor_contact(vendor_id, payload)
                        redirect_notice = "Vendor contact updated." if ok else "Could not update vendor contact."
                        if not ok:
                            redirect_type = "error"

            elif action == "toggle_active":
                vendor_id = parse_optional_int(request.form.get("vendor_id"))
                active = parse_bool_value(request.form.get("active"), default=False)
                if not vendor_id:
                    redirect_notice = "Vendor ID missing."
                    redirect_type = "error"
                else:
                    ok = set_vendor_contact_active(vendor_id, active)
                    redirect_notice = (
                        "Vendor marked active." if (ok and active) else
                        ("Vendor marked inactive." if ok else "Could not update vendor status.")
                    )
                    if not ok:
                        redirect_type = "error"
            else:
                redirect_notice = "Unknown vendor action."
                redirect_type = "warning"

        except Exception as exc:
            log_system_error("vendor_management", str(exc))
            redirect_notice = f"Vendor update failed: {str(exc)[:200]}"
            redirect_type = "error"

        return redirect(url_for("tc_vendors", notice=redirect_notice, notice_type=redirect_type))

    vendors = fetch_vendor_contacts_with_performance()
    grouped_vendors = {vendor_type: [] for vendor_type in VENDOR_TYPES}
    for row in vendors:
        vendor_type = normalize_vendor_type(row.get("vendor_type"))
        if vendor_type not in grouped_vendors:
            grouped_vendors[vendor_type] = []
        grouped_vendors[vendor_type].append(row)

    return render_template(
        "tc_vendors.html",
        notice=notice,
        notice_type=notice_type,
        grouped_vendors=grouped_vendors,
        vendor_types=VENDOR_TYPES,
    )


@app.route("/tc/vendor-outreach/<int:outreach_id>/follow-up", methods=["POST"])
@login_required
def follow_up_vendor_outreach(outreach_id):
    """Send manual follow-up email for one pending vendor outreach."""
    result = send_manual_vendor_follow_up(
        outreach_id=outreach_id,
        requested_by=session.get("tc_username", "margaret"),
    )
    notice = "Follow-up email sent."
    notice_type = "success"
    if not result.get("success"):
        notice = f"Could not send follow-up: {result.get('error', 'unknown error')}"
        notice_type = "warning"
    return redirect(url_for("tc_daily_checklist", notice=notice, notice_type=notice_type))


@app.route("/tc/vendor-outreach/<int:outreach_id>/mark-scheduled", methods=["POST"])
@login_required
def mark_vendor_outreach_scheduled_route(outreach_id):
    """Manually mark one pending vendor outreach as scheduled."""
    scheduled_input = (request.form.get("scheduled_date") or "").strip()
    notes = (request.form.get("notes") or "").strip()
    result = mark_vendor_outreach_scheduled(
        outreach_id=outreach_id,
        scheduled_datetime=scheduled_input or None,
        notes=notes,
        source="manual_checklist",
    )
    notice = "Vendor marked as scheduled."
    notice_type = "success"
    if not result.get("success"):
        notice = f"Could not mark scheduled: {result.get('error', 'unknown error')}"
        notice_type = "warning"
    else:
        scheduled_at = parse_schedule_datetime(scheduled_input)
        if scheduled_at:
            if len(scheduled_input) <= 10:
                scheduled_at = scheduled_at.replace(hour=9, minute=0, second=0, microsecond=0)
            calendar_sync_result = sync_vendor_appointment_to_calendar(
                transaction_id=result.get("transaction_id"),
                vendor_type=result.get("vendor_type"),
                appointment_at=scheduled_at,
                source_ref=f"vendor_outreach:{outreach_id}",
                source_id=outreach_id,
                notes=notes,
            )
            if not calendar_sync_result.get("success"):
                sync_reason = (
                    calendar_sync_result.get("error")
                    or calendar_sync_result.get("skipped")
                    or "unknown"
                )
                notice = f"Vendor marked scheduled, but calendar sync was skipped/failed: {sync_reason}"
                notice_type = "warning"
    return redirect(url_for("tc_daily_checklist", notice=notice, notice_type=notice_type))


@app.route("/tc/nudge-analytics")
@login_required
def tc_nudge_analytics():
    """Show intelligent nudge performance and response analytics."""
    ensure_intelligent_nudge_tables()
    notice = (request.args.get("notice") or "").strip()
    notice_type = (request.args.get("notice_type") or "success").strip().lower()
    if notice_type not in {"success", "warning", "error"}:
        notice_type = "success"

    weekly_counts = execute_query(
        """
        SELECT DATE_TRUNC('week', sent_at)::date AS week_start, COUNT(*) AS total_sent
        FROM nudge_log
        WHERE sent_at >= (CURRENT_DATE - INTERVAL '90 days')
        GROUP BY DATE_TRUNC('week', sent_at)
        ORDER BY week_start DESC
        LIMIT 14
        """,
        fetch=True,
    ) or []
    weekly_counts = list(reversed(weekly_counts))
    for row in weekly_counts:
        row["week_label"] = row["week_start"].strftime("%b %d") if row.get("week_start") else ""

    response_by_type = execute_query(
        """
        SELECT
            nudge_type,
            COUNT(*) AS total_sent,
            COUNT(*) FILTER (WHERE response_received = TRUE) AS responses,
            COUNT(*) FILTER (WHERE escalated_to_margaret = TRUE) AS escalations,
            ROUND(
                CASE WHEN COUNT(*) = 0 THEN 0
                     ELSE (COUNT(*) FILTER (WHERE response_received = TRUE)::numeric / COUNT(*)::numeric) * 100
                END,
                1
            ) AS response_rate
        FROM nudge_log
        GROUP BY nudge_type
        ORDER BY total_sent DESC, response_rate DESC
        """,
        fetch=True,
    ) or []
    for row in response_by_type:
        row["label"] = nudge_type_label(row.get("nudge_type"))
        row["follow_up_needed"] = int(row.get("total_sent") or 0) - int(row.get("responses") or 0)

    time_saved_row = execute_query(
        """
        SELECT
            COUNT(*) FILTER (
                WHERE response_received = TRUE
                  AND escalated_to_margaret = FALSE
            ) AS resolved_without_escalation,
            COUNT(*) AS total_nudges
        FROM nudge_log
        """,
        fetch=True,
    ) or []
    time_saved = time_saved_row[0] if time_saved_row else {"resolved_without_escalation": 0, "total_nudges": 0}
    resolved_without_escalation = int(time_saved.get("resolved_without_escalation") or 0)
    estimated_minutes_saved = resolved_without_escalation * 12

    agent_rows = execute_query(
        """
        SELECT
            COALESCE(t.agent_name, 'Unknown Agent') AS agent_name,
            COALESCE(t.agent_phone, '') AS agent_phone,
            COUNT(*) AS nudges_sent,
            COUNT(*) FILTER (WHERE nl.response_received = TRUE) AS responses,
            COUNT(*) FILTER (WHERE nl.escalated_to_margaret = TRUE) AS escalations,
            ROUND(
                CASE WHEN COUNT(*) = 0 THEN 0
                     ELSE (COUNT(*) FILTER (WHERE nl.response_received = TRUE)::numeric / COUNT(*)::numeric) * 100
                END,
                1
            ) AS response_rate
        FROM nudge_log nl
        JOIN transactions t ON t.id = nl.transaction_id
        GROUP BY t.agent_name, t.agent_phone
        ORDER BY response_rate DESC, nudges_sent DESC
        LIMIT 40
        """,
        fetch=True,
    ) or []
    for row in agent_rows:
        row["needs_follow_up"] = int(row.get("nudges_sent") or 0) - int(row.get("responses") or 0)

    most_effective_messages = sorted(
        [row for row in response_by_type if int(row.get("total_sent") or 0) > 0],
        key=lambda row: (float(row.get("response_rate") or 0), int(row.get("total_sent") or 0)),
        reverse=True,
    )[:5]

    return render_template(
        "tc_nudge_analytics.html",
        notice=notice,
        notice_type=notice_type,
        weekly_counts=weekly_counts,
        response_by_type=response_by_type,
        most_effective_messages=most_effective_messages,
        agent_rows=agent_rows,
        resolved_without_escalation=resolved_without_escalation,
        estimated_minutes_saved=estimated_minutes_saved,
        total_nudges=int(time_saved.get("total_nudges") or 0),
    )


@app.route("/tc/nudge-settings", methods=["GET", "POST"])
@login_required
def tc_nudge_settings():
    """Configure intelligent nudge timing, templates, vendors, and whitelist."""
    ensure_intelligent_nudge_tables()
    ensure_vendor_automation_tables()

    notice = (request.args.get("notice") or "").strip()
    notice_type = (request.args.get("notice_type") or "success").strip().lower()
    if notice_type not in {"success", "warning", "error"}:
        notice_type = "success"

    if request.method == "POST":
        action = (request.form.get("action") or "").strip().lower()
        next_notice = "Settings saved."
        next_type = "success"

        if action == "update_setting":
            nudge_type = (request.form.get("nudge_type") or "").strip()
            lead_days = parse_optional_int(request.form.get("lead_days")) or INTELLIGENT_NUDGE_DEFAULTS.get(
                nudge_type, {}
            ).get("lead_days", 5)
            enabled = parse_bool_value(request.form.get("enabled"), default=False)
            include_preferred_vendors = parse_bool_value(request.form.get("include_preferred_vendors"), default=False)
            preferred_vendor_ids = request.form.getlist("preferred_vendor_ids")
            ok = upsert_nudge_setting(
                nudge_type=nudge_type,
                enabled=enabled,
                lead_days=lead_days,
                sms_template=request.form.get("sms_template") or "",
                email_template=request.form.get("email_template") or "",
                custom_sms_message=request.form.get("custom_sms_message") or "",
                custom_email_message=request.form.get("custom_email_message") or "",
                include_preferred_vendors=include_preferred_vendors,
                preferred_vendor_ids=preferred_vendor_ids,
                updated_by=session.get("tc_username", "margaret"),
            )
            if not ok:
                next_notice = "Invalid nudge type. Setting not saved."
                next_type = "error"

        elif action == "add_whitelist":
            ok = upsert_nudge_whitelist_row(
                agent_name=request.form.get("agent_name") or "",
                agent_phone=request.form.get("agent_phone") or "",
                agent_email=request.form.get("agent_email") or "",
                notes=request.form.get("notes") or "",
                updated_by=session.get("tc_username", "margaret"),
            )
            if ok:
                next_notice = "Agent added to no-nudge whitelist."
            else:
                next_notice = "Whitelist entry needs a phone or email."
                next_type = "warning"

        elif action == "remove_whitelist":
            whitelist_id = parse_optional_int(request.form.get("whitelist_id"))
            if whitelist_id is not None:
                delete_nudge_whitelist_row(whitelist_id)
                next_notice = "Whitelist entry removed."
            else:
                next_notice = "Invalid whitelist row."
                next_type = "error"
        else:
            next_notice = "Unknown settings action."
            next_type = "warning"

        return redirect(url_for("tc_nudge_settings", notice=next_notice, notice_type=next_type))

    settings_rows = fetch_nudge_settings_rows()
    whitelist_rows = fetch_nudge_whitelist_rows()
    inspector_vendors = execute_query(
        """
        SELECT id, company_name, contact_name, phone, preferred
        FROM vendor_contacts
        WHERE vendor_type = 'inspector'
          AND active = TRUE
        ORDER BY preferred DESC, company_name ASC NULLS LAST, id ASC
        """,
        fetch=True,
    ) or []

    return render_template(
        "tc_nudge_settings.html",
        notice=notice,
        notice_type=notice_type,
        settings_rows=settings_rows,
        whitelist_rows=whitelist_rows,
        inspector_vendors=inspector_vendors,
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
    notice = (request.args.get("notice") or "").strip()
    notice_type = (request.args.get("notice_type") or "success").strip().lower()
    if notice_type not in {"success", "warning", "error"}:
        notice_type = "success"

    try:
        ensure_task_completion_tables()
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
                   tk.completed, tk.status, tk.completed_at, tk.completed_by,
                   t.id AS transaction_id, t.property_address
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
            task["auto_completed"] = (task.get("completed_by") or "").strip().lower() == "auto-rule-engine"

        auto_metrics = fetch_task_auto_completion_metrics(weeks=8)

        return render_template(
            "tc_tasks.html",
            notice=notice,
            notice_type=notice_type,
            selected_filter=selected_filter,
            transaction_filter=transaction_filter,
            overdue_tasks=overdue_tasks,
            due_today_tasks=due_today_tasks,
            upcoming_tasks=upcoming_tasks,
            completed_tasks=completed_tasks,
            auto_metrics=auto_metrics,
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
        existing_rows = execute_query(
            """
            SELECT id, completed, completed_by
            FROM tasks
            WHERE id = %s
            LIMIT 1
            """,
            (task_id,),
            fetch=True,
        ) or []
        if not existing_rows:
            return jsonify({"success": False, "error": "Task not found"}), 404
        existing_task = existing_rows[0]
        was_auto_completed = (
            bool(existing_task.get("completed"))
            and (existing_task.get("completed_by") or "").strip().lower() == "auto-rule-engine"
        )
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
            return jsonify({"success": False, "error": "Unable to update task"}), 500

        undo_logged = False
        if not completed and was_auto_completed:
            undo_logged = record_auto_completion_undo(task_id, undone_by=session.get("tc_username", "margaret"))
            if undo_logged:
                note_text = (
                    "[Auto-completion undone] Margaret reopened this task for manual verification."
                )
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

        return jsonify(
            {
                "success": True,
                "task_id": task_id,
                "completed": bool(rows[0]["completed"]),
                "status": rows[0]["status"],
                "undo_logged": undo_logged,
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
        notice = (request.args.get("notice") or "").strip()
        notice_type = (request.args.get("notice_type") or "success").strip().lower()
        if notice_type not in {"success", "warning", "error"}:
            notice_type = "success"

        ensure_vendor_followup_tasks()
        ensure_vendor_automation_tables()
        auto_dispatch_timeline_updates(limit=40)
        refresh_heads_up_if_stale(max_age_minutes=180, send_sms=False)
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

        pending_vendor_responses = fetch_pending_vendor_responses(limit=40)
        summary = {
            "total_items": (
                len(overdue_tasks)
                + len(due_today_tasks)
                + len(calls_to_make)
                + len(reminders_to_send)
                + len(pending_vendor_responses)
            ),
            "overdue_count": len(overdue_tasks),
            "due_today_count": len(due_today_tasks),
            "calls_count": len(calls_to_make),
            "vendor_response_count": len(pending_vendor_responses),
        }

        return render_template(
            "tc_daily_checklist.html",
            current_date_label=today.strftime("%A, %B %d, %Y"),
            notice=notice,
            notice_type=notice_type,
            summary=summary,
            calls_to_make=calls_to_make,
            overdue_tasks=overdue_tasks,
            due_today_tasks=due_today_tasks,
            reminders_to_send=reminders_to_send,
            pending_vendor_responses=pending_vendor_responses,
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

    extracted_data = get_extracted_contract_data_or_none(transaction_id) or {}
    extraction_review = build_contract_extraction_review(transaction_id, extracted_data, transaction)
    verified_values_by_field = {
        field["field_name"]: field["input_value"]
        for field in extraction_review["fields"]
        if field.get("manually_verified") and field.get("input_value")
    }

    prefill_effective = parse_contract_date(verified_values_by_field.get("effective_date")) or extraction_prefill_value(
        extracted_data,
        "confirmed_effective_date",
        "extracted_effective_date",
    )
    prefill_closing = parse_contract_date(verified_values_by_field.get("closing_date")) or extraction_prefill_value(
        extracted_data,
        "confirmed_closing_date",
        "extracted_closing_date",
    )
    prefill_buyer = verified_values_by_field.get("buyer_name") or extraction_prefill_value(
        extracted_data,
        "confirmed_buyer_names",
        "extracted_buyer_names",
        "",
    )
    prefill_seller = verified_values_by_field.get("seller_name") or extraction_prefill_value(
        extracted_data,
        "confirmed_seller_names",
        "extracted_seller_names",
        "",
    )
    prefill_property = verified_values_by_field.get("property_address") or extraction_prefill_value(
        extracted_data,
        "confirmed_property_address",
        "extracted_property_address",
        transaction.get("property_address") or "",
    )

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
        "confirmed": extraction_review["all_verified"],
        "confirmed_at_label": (
            extracted_data["confirmed_at"].strftime("%b %d, %Y %I:%M %p")
            if extracted_data.get("confirmed_at")
            else ""
        ),
        "confirmed_by": extracted_data.get("confirmed_by") or "",
        "raw_text_excerpt": extracted_data.get("raw_text_excerpt") or "",
        "agent_property_address": extracted_data.get("submitted_property_address")
        or transaction.get("property_address")
        or "",
        "property_address_match": extracted_data.get("property_address_match"),
        "effective_date_input": (prefill_effective.isoformat() if prefill_effective else ""),
        "closing_date_input": (prefill_closing.isoformat() if prefill_closing else ""),
        "buyer_names_input": prefill_buyer,
        "seller_names_input": prefill_seller,
        "property_address_input": prefill_property,
    }
    email_status = get_email_notification_status(
        transaction_id=transaction_id,
        lender_email=normalize_email(transaction.get("lender_email")),
        title_email=normalize_email(transaction.get("title_officer_email")),
    )

    ensure_document_classification_corrections_table()
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

    correction_rows = execute_query(
        """
        SELECT DISTINCT ON (document_id)
               id, document_id, original_document_type, corrected_document_type,
               correction_reason, corrected_by, created_at
        FROM document_classification_corrections
        WHERE transaction_id = %s
        ORDER BY document_id, created_at DESC, id DESC
        """,
        (transaction_id,),
        fetch=True,
    ) or []
    correction_by_document = {row["document_id"]: row for row in correction_rows}
    for document in documents:
        correction = correction_by_document.get(document["id"])
        document["classification_correction"] = correction
        document["was_reclassified"] = bool(correction)
        document["original_document_type"] = correction.get("original_document_type") if correction else None
        document["correction_note"] = correction.get("correction_reason") if correction else ""

    analysis_rows = get_document_analysis_rows(transaction_id)
    analysis_by_document = {}
    analysis_pending_review_count = 0
    analysis_action_item_count = 0
    for row in analysis_rows:
        row["action_count"] = len(row.get("action_items") or [])
        analysis_action_item_count += row["action_count"]
        if not row.get("margaret_reviewed"):
            analysis_pending_review_count += 1
        document_id = row.get("document_id")
        if document_id and document_id not in analysis_by_document:
            analysis_by_document[document_id] = row

    for document in documents:
        linked_analysis = analysis_by_document.get(document["id"])
        document["analysis_available"] = bool(linked_analysis)
        document["analysis_reviewed"] = bool(linked_analysis and linked_analysis.get("margaret_reviewed"))
        document["analysis_status_label"] = (
            "Reviewed"
            if document["analysis_reviewed"]
            else ("Needs review" if linked_analysis else "Not analyzed")
        )
        document["analysis_action_count"] = linked_analysis.get("action_count", 0) if linked_analysis else 0

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

    timeline_packet = fetch_timeline_packet_row(transaction_id) or {}
    timeline_pdf_url = ""
    if timeline_packet.get("timeline_s3_key"):
        timeline_pdf_url = get_presigned_url(timeline_packet["timeline_s3_key"], expiration=60 * 60 * 24 * 7) or ""
    timeline_last_sent = timeline_packet.get("last_sent_at")
    timeline_last_sent_label = format_timestamp_label(timeline_last_sent)
    timeline_last_sent_ago = format_time_ago(timeline_last_sent) if timeline_last_sent else ""
    timeline_recipients_label = format_timeline_recipients_label(timeline_packet.get("sent_recipients"))

    ensure_closing_checklist_tables()
    closing_checklist = fetch_closing_checklist_by_transaction(transaction_id) or {}
    closing_checklist_pdf_url = ""
    if closing_checklist.get("pdf_s3_key"):
        closing_checklist_pdf_url = get_presigned_url(closing_checklist["pdf_s3_key"], expiration=60 * 60 * 24 * 7) or ""
    if closing_checklist:
        closing_checklist["status_label"] = closing_checklist_status_label(closing_checklist.get("status"))
        closing_checklist["generated_at_label"] = format_timestamp_label(closing_checklist.get("generated_at"))
        closing_checklist["auto_send_after_label"] = format_timestamp_label(closing_checklist.get("auto_send_after"))
        closing_checklist["summary"] = closing_checklist.get("summary") or {}

    ensure_calendar_sync_tables()
    calendar_sync_settings = fetch_calendar_sync_settings()
    calendar_preferences = fetch_transaction_calendar_preferences(transaction_id) or {}
    calendar_mappings = fetch_calendar_mappings(transaction_id=transaction_id, limit=80)
    for mapping in calendar_mappings:
        mapping["event_type_label"] = (mapping.get("event_type") or "event").replace("_", " ").title()
        mapping["status_label"] = (mapping.get("status") or "active").replace("_", " ").title()
        mapping["updated_at_label"] = format_timestamp_label(mapping.get("updated_at"))
        mapping["source_label"] = (
            mapping.get("source_label")
            or (mapping.get("source_ref") or "").replace("deadline:", "").replace("_", " ").title()
        )
    default_closing_time = (
        parse_optional_hhmm(calendar_preferences.get("closing_time"))
        or parse_optional_hhmm(calendar_sync_settings.get("closing_default_time"))
        or "09:00"
    )
    calendar_preferences["closing_time_input"] = default_closing_time
    calendar_preferences["closing_duration_minutes"] = int(
        calendar_preferences.get("closing_duration_minutes")
        or calendar_sync_settings.get("closing_duration_minutes")
        or 60
    )
    calendar_preferences["closing_location"] = (
        calendar_preferences.get("closing_location")
        or transaction.get("title_company")
        or ""
    )

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

    ensure_inbound_email_tables()
    inbound_aliases = transaction_inbound_aliases(transaction_id)
    inbound_rules = fetch_inbound_email_rules_map(transaction_id)
    inbound_messages = fetch_inbound_email_messages(transaction_id, limit=20)
    risk_state = fetch_transaction_risk_state(transaction_id)

    ensure_voice_note_tables()
    communications = execute_query(
        """
        SELECT c.id, c.communication_type, c.contact_party, c.contact_name, c.summary, c.outcome, c.created_at,
               vn.id AS voice_note_id,
               vn.recording_sid AS voice_recording_sid,
               vn.note_type AS voice_note_type,
               vn.transcription_text AS voice_note_transcription,
               vn.confidence_score AS voice_confidence_score,
               vn.status AS voice_note_status,
               vn.review_required AS voice_review_required,
               vn.actions_taken AS voice_actions_taken
        FROM communications c
        LEFT JOIN voice_notes vn ON vn.communication_id = c.id
        WHERE c.transaction_id = %s
        ORDER BY c.created_at DESC
        """,
        (transaction_id,),
        fetch=True,
    ) or []
    for entry in communications:
        entry["created_at_label"] = entry["created_at"].strftime("%b %d, %Y %I:%M %p") if entry.get("created_at") else ""
        entry["type_label"] = (entry.get("communication_type") or "").replace("_", " ").title()
        entry["party_label"] = (entry.get("contact_party") or "").replace("_", " ").title()
        entry["is_voice_note"] = bool(entry.get("voice_note_id"))
        entry["voice_note_type_label"] = (entry.get("voice_note_type") or "general_update").replace("_", " ").title()
        entry["voice_note_transcription"] = (entry.get("voice_note_transcription") or "").strip()
        entry["voice_note_status_label"] = (entry.get("voice_note_status") or "").replace("_", " ").title()
        entry["voice_confidence_score"] = int(entry.get("voice_confidence_score") or 0)
        entry["voice_actions_taken"] = parse_json_field(entry.get("voice_actions_taken"), {})

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
        timeline_pdf_url=timeline_pdf_url,
        timeline_last_sent_label=timeline_last_sent_label,
        timeline_last_sent_ago=timeline_last_sent_ago,
        timeline_recipients_label=timeline_recipients_label,
        closing_checklist=closing_checklist,
        closing_checklist_pdf_url=closing_checklist_pdf_url,
        calendar_sync_settings=calendar_sync_settings,
        calendar_preferences=calendar_preferences,
        calendar_mappings=calendar_mappings,
        task_preview=task_preview,
        task_total=task_total,
        communications=communications,
        inbound_aliases=inbound_aliases,
        inbound_rules=inbound_rules,
        inbound_messages=inbound_messages,
        risk_state=risk_state,
        payment_context=payment_context,
        extracted_data=extracted_context,
        extraction_review=extraction_review,
        email_status=email_status,
        client_portal_links=client_portal_links,
        analysis_overview={
            "total_analyzed": len(analysis_rows),
            "pending_review_count": analysis_pending_review_count,
            "action_item_count": analysis_action_item_count,
        },
        document_classification_types=DOCUMENT_CLASSIFICATION_OVERRIDE_TYPES,
        common_qa_categories=COMMON_QA_CATEGORY_OPTIONS,
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


def _verified_field_value_from_form(form_payload, field_name):
    """Read verify-extraction values with backward-compatible fallback keys."""
    legacy_key_map = {
        "effective_date": "extracted_effective_date",
        "closing_date": "extracted_closing_date",
        "buyer_name": "extracted_buyer_names",
        "seller_name": "extracted_seller_names",
        "property_address": "extracted_property_address",
    }
    preferred_key = f"verified_{field_name}"
    return (form_payload.get(preferred_key) or form_payload.get(legacy_key_map[field_name]) or "").strip()


def _persist_verified_contract_extractions(transaction, transaction_id):
    """Persist Margaret-verified extraction values and sync legacy table."""
    transaction_id = int(transaction_id)
    extracted_data = get_extracted_contract_data_or_none(transaction_id) or {}
    existing_rows = get_contract_extraction_rows(transaction_id)
    existing_by_field = {row.get("field_name"): row for row in existing_rows}
    field_meta = extraction_field_meta_map()

    parsed_dates = {}
    verified_values = {}
    for field_name, _, _ in CONTRACT_EXTRACTION_FIELDS:
        raw_value = _verified_field_value_from_form(request.form, field_name)
        if not raw_value:
            raise ValueError(f"{field_meta[field_name]['label']} is required.")

        if field_name in {"effective_date", "closing_date"}:
            parsed_date = parse_required_date(raw_value, field_meta[field_name]["label"])
            parsed_dates[field_name] = parsed_date
            verified_values[field_name] = parsed_date.isoformat()
        else:
            verified_values[field_name] = raw_value

    if parsed_dates["closing_date"] < parsed_dates["effective_date"]:
        raise ValueError("Closing date cannot be before effective date.")

    ensure_contract_extractions_table()
    for field_name, _, _ in CONTRACT_EXTRACTION_FIELDS:
        existing_row = existing_by_field.get(field_name, {})
        extracted_value = normalize_extraction_value(
            field_name,
            existing_row.get("extracted_value") or verified_values[field_name],
        )
        confidence = (existing_row.get("confidence") or "low").strip().lower()
        if confidence not in {"high", "low"}:
            confidence = "low"
        agreement = (existing_row.get("agreement") or ("3/3" if confidence == "high" else "2/3")).strip()

        execute_query(
            """
            INSERT INTO contract_extractions (
                transaction_id,
                field_name,
                extracted_value,
                confidence,
                agreement,
                method1_value,
                method2_value,
                method3_value,
                manually_verified,
                verified_value
            )
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s, TRUE, %s)
            ON CONFLICT (transaction_id, field_name)
            DO UPDATE SET
                extracted_value = EXCLUDED.extracted_value,
                confidence = EXCLUDED.confidence,
                agreement = EXCLUDED.agreement,
                method1_value = EXCLUDED.method1_value,
                method2_value = EXCLUDED.method2_value,
                method3_value = EXCLUDED.method3_value,
                manually_verified = TRUE,
                verified_value = EXCLUDED.verified_value
            """,
            (
                transaction_id,
                field_name,
                extracted_value or None,
                confidence,
                agreement or "0/3",
                existing_row.get("method1_value"),
                existing_row.get("method2_value"),
                existing_row.get("method3_value"),
                verified_values[field_name],
            ),
        )

    submitted_property_address = extracted_data.get("submitted_property_address") or transaction.get("property_address") or ""
    property_match = addresses_match(verified_values["property_address"], submitted_property_address)
    if property_match is None and submitted_property_address:
        property_match = False

    ensure_extracted_contract_data_table()
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
            extracted_data.get("extracted_effective_date") or parsed_dates["effective_date"],
            extracted_data.get("extracted_closing_date") or parsed_dates["closing_date"],
            extracted_data.get("extracted_buyer_names") or verified_values["buyer_name"],
            extracted_data.get("extracted_seller_names") or verified_values["seller_name"],
            extracted_data.get("extracted_property_address") or verified_values["property_address"],
            property_match,
            extracted_data.get("raw_text_excerpt"),
            "success" if extracted_data.get("extraction_status") == "success" else "manual",
            parsed_dates["effective_date"],
            parsed_dates["closing_date"],
            verified_values["buyer_name"],
            verified_values["seller_name"],
            verified_values["property_address"],
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
            property_address = %s,
            updated_at = CURRENT_TIMESTAMP
        WHERE id = %s
        """,
        (
            parsed_dates["effective_date"],
            parsed_dates["closing_date"],
            verified_values["buyer_name"],
            verified_values["seller_name"],
            verified_values["property_address"],
            transaction_id,
        ),
    )

    if (transaction.get("status") or "").upper() == "ACTIVE":
        try:
            _sync_closing_event_for_transaction(
                transaction_id=transaction_id,
                transaction_row={
                    **transaction,
                    "closing_date": parsed_dates["closing_date"],
                    "buyer_name": verified_values["buyer_name"],
                    "seller_name": verified_values["seller_name"],
                    "property_address": verified_values["property_address"],
                },
                force_update=True,
            )
        except Exception as exc:
            log_system_error("calendar_sync", f"Closing event update failed after extraction verify: {exc}", transaction_id)


@app.route("/tc/transaction/<int:transaction_id>/verify-extraction", methods=["POST"])
@login_required
def verify_extraction(transaction_id):
    """Persist Margaret's verified extraction values from triple-scan review."""
    transaction = get_transaction_or_none(transaction_id)
    if not transaction:
        return "Transaction not found", 404
    if transaction.get("status") in {"COMPLETED", "CANCELLED"}:
        return "This transaction cannot be modified.", 400

    try:
        _persist_verified_contract_extractions(transaction, transaction_id)
    except ValueError as exc:
        return str(exc), 400
    except Exception as exc:
        print(f"Verify extraction error (txn#{transaction_id}): {exc}")
        return "Unable to save verified extraction values right now.", 500

    redirect_url = url_for(
        "tc_transaction",
        transaction_id=transaction_id,
        doc_notice="Extraction fields verified successfully.",
        doc_notice_type="success",
    )
    return redirect(f"{redirect_url}#review-details")


@app.route("/tc/transaction/<int:transaction_id>/confirm-extraction", methods=["POST"])
@login_required
def confirm_extraction(transaction_id):
    """Backward-compatible alias for extraction verification."""
    return verify_extraction(transaction_id)


@app.route("/tc/transaction/<int:transaction_id>/approve", methods=["POST"])
@login_required
def approve_transaction(transaction_id):
    """Approve a reviewed transaction and activate full workflow artifacts."""
    transaction = get_transaction_or_none(transaction_id)
    if not transaction:
        return "Transaction not found", 404
    if transaction.get("status") in {"COMPLETED", "CANCELLED"}:
        return "This transaction cannot be approved.", 400

    verified_extraction, missing_fields = get_verified_contract_extraction_values(transaction_id)
    if not verified_extraction:
        if missing_fields:
            missing_text = ", ".join(missing_fields)
            return f"Please verify extraction fields before approval: {missing_text}.", 400
        return "Please verify extraction fields before approval.", 400

    effective_date_value = verified_extraction["effective_date"]
    closing_date_value = verified_extraction["closing_date"]
    buyer_name = verified_extraction["buyer_name"]
    seller_name = verified_extraction["seller_name"]
    verified_property_address = verified_extraction["property_address"] or transaction.get("property_address")

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
        SET property_address = %s,
            effective_date = %s,
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
            verified_property_address,
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

    calendar_summary = sync_transaction_calendar_bundle(
        transaction_id=transaction_id,
        actor=session.get("tc_username", "margaret"),
        force_update=True,
        include_deadlines=False,
        include_closing=True,
        include_vendor_events=False,
    )

    transaction["id"] = transaction_id
    transaction["property_address"] = verified_property_address
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

    timeline_result = regenerate_and_resend_timeline(
        transaction_id=transaction_id,
        reason="approved",
        force=True,
        buyer_email=buyer_email or "",
        seller_email=seller_email or "",
        send_vendor_notifications=False,
    )
    if not timeline_result.get("success"):
        execute_query(
            """
            INSERT INTO communications (transaction_id, communication_type, contact_party, contact_name, summary, outcome)
            VALUES (%s, 'note', 'system', 'timeline', %s, %s)
            """,
            (
                transaction_id,
                "Timeline packet dispatch failed on approval",
                (
                    f"error={timeline_result.get('error', 'unknown')} "
                    f"primary_error={timeline_result.get('primary_error', 'n/a')} "
                    f"fallback_error={timeline_result.get('fallback_error', 'n/a')}"
                ),
            ),
        )

    timeline_warning = ""
    if not timeline_result.get("success"):
        timeline_warning = " Timeline generation failed; please regenerate from transaction details."

    dashboard_notice = "Transaction approved."
    dashboard_notice_type = "success"
    calendar_warning = ""
    if calendar_summary.get("closing_failed"):
        calendar_warning = " Calendar sync failed for the closing event."
    try:
        vendor_result = send_vendor_requests(transaction_id)
        sent_count = vendor_result.get("sent_count", 0)
        if sent_count > 0:
            dashboard_notice = "✅ Transaction approved and vendor requests sent!"
            dashboard_notice_type = "success"
        else:
            dashboard_notice = "⚠️ Transaction approved, but no active vendors were available to email."
            dashboard_notice_type = "warning"
        execute_query(
            """
            INSERT INTO communications (transaction_id, communication_type, contact_party, contact_name, summary, outcome)
            VALUES (%s, 'note', 'system', 'vendor_automation', %s, %s)
            """,
            (
                transaction_id,
                "Vendor scheduling automation run after approval",
                f"sent_count={sent_count}",
            ),
        )
    except Exception as exc:
        dashboard_notice = f"⚠️ Transaction approved, but vendor emails failed: {str(exc)[:200]}"
        dashboard_notice_type = "warning"
        log_system_error("vendor_automation", str(exc), transaction_id)

    if timeline_warning:
        dashboard_notice = f"{dashboard_notice}{timeline_warning}"
        if dashboard_notice_type == "success":
            dashboard_notice_type = "warning"
    if calendar_warning:
        dashboard_notice = f"{dashboard_notice}{calendar_warning}"
        if dashboard_notice_type == "success":
            dashboard_notice_type = "warning"

    return redirect(url_for("tc_dashboard", notice=dashboard_notice, notice_type=dashboard_notice_type))


@app.route("/tc/transaction/<int:transaction_id>/upload-document", methods=["POST"])
@login_required
def upload_transaction_document(transaction_id):
    """Upload a transaction document to S3 and track it in DB."""
    transaction = get_transaction_or_none(transaction_id)
    if not transaction:
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

    file_bytes = file.read()
    file_size = len(file_bytes or b"")
    if file_size > MAX_FILE_SIZE:
        return "File exceeds 16MB upload limit.", 400

    selected_document_type = normalize_document_type(request.form.get("document_type"), fallback="other")
    uploaded_by = session.get("tc_username", "margaret")
    processed = process_uploaded_document(
        file_bytes=file_bytes,
        transaction_id=transaction_id,
        uploaded_by=uploaded_by,
        original_filename=safe_filename,
        extension=extension,
        transaction_context=transaction,
        suggested_document_type=selected_document_type,
    )
    if not processed.get("success"):
        return "Failed to upload document.", 500
    document_type = normalize_document_type(processed.get("document_type"), fallback=selected_document_type or "other")
    predicted_type = normalize_document_type(processed.get("predicted_type"), fallback="unknown")
    document_filename = processed.get("filename") or safe_filename
    s3_key = processed.get("s3_key")
    classification = processed.get("analysis") or {}
    first_page_text = processed.get("first_page_text") or ""

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
            document_filename,
            s3_key,
            file_size,
            uploaded_by,
        ),
    )
    if not document_id:
        return "Failed to save document record.", 500

    key_info = classification.get("key_info_extracted")
    post_actions = apply_document_post_upload_actions(
        transaction_id=transaction_id,
        document_type=document_type,
        first_page_text=first_page_text,
        key_info_extracted=(key_info if isinstance(key_info, dict) else {}),
        uploaded_by=uploaded_by,
    )

    execute_query(
        """
        INSERT INTO communications (transaction_id, communication_type, contact_party, contact_name, summary, outcome)
        VALUES (%s, 'note', 'system', 'document_processor', %s, %s)
        """,
        (
            transaction_id,
            "Smart document classification completed",
            (
                f"doc_id={document_id} selected_type={selected_document_type} "
                f"predicted_type={predicted_type} final_type={document_type} "
                f"confidence={int(classification.get('confidence') or 0)} "
                f"source={(classification.get('source') or 'heuristic')} "
                f"actions={post_actions.get('summary') or 'none'}"
            )[:1800],
        ),
    )

    if predicted_type != "unknown" and predicted_type != document_type:
        execute_query(
            """
            INSERT INTO document_classification_corrections (
                document_id, transaction_id, original_document_type, corrected_document_type,
                first_page_signature, first_page_excerpt, correction_reason, corrected_by
            )
            VALUES (%s, %s, %s, %s, md5(%s), %s, %s, %s)
            """,
            (
                document_id,
                transaction_id,
                predicted_type,
                document_type,
                first_page_text[:3000],
                first_page_text[:600],
                "Auto fallback from unknown prediction to selected upload type",
                "system",
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
        (transaction_id, document_type),
    )

    log_document_access(
        document_id=document_id,
        user_name=session.get("tc_username", "margaret"),
        user_type="tc",
        action="upload",
        ip_address=request.remote_addr or "",
    )

    run_document_analysis_async(
        document_id=document_id,
        transaction_id=transaction_id,
        document_type=document_type,
        s3_key=s3_key,
        extension=extension,
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

    file_bytes = file.read()
    file_size = len(file_bytes or b"")
    if file_size > MAX_FILE_SIZE:
        redirect_url = url_for(
            "client_portal_documents",
            access_token=access_token,
            notice="File exceeds 16MB upload limit.",
            notice_type="error",
        )
        return redirect(redirect_url)

    document_type = normalize_document_type(request.form.get("document_type"), fallback="other")
    valid_upload_types = CLIENT_UPLOAD_DOCUMENT_TYPES | REQUIRED_DOCUMENT_TYPES
    if document_type not in valid_upload_types:
        document_type = "other"

    uploaded_by = f"client_{access_row.get('client_type')}"
    processed = process_uploaded_document(
        file_bytes=file_bytes,
        transaction_id=transaction["id"],
        uploaded_by=uploaded_by,
        original_filename=safe_filename,
        extension=extension,
        transaction_context=transaction,
        suggested_document_type=document_type,
    )
    if not processed.get("success"):
        redirect_url = url_for(
            "client_portal_documents",
            access_token=access_token,
            notice="Upload failed. Please try again.",
            notice_type="error",
        )
        return redirect(redirect_url)
    final_document_type = normalize_document_type(processed.get("document_type"), fallback=document_type or "other")
    predicted_type = normalize_document_type(processed.get("predicted_type"), fallback="unknown")
    s3_key = processed.get("s3_key")
    filename_for_storage = processed.get("filename") or safe_filename
    classification = processed.get("analysis") or {}
    first_page_text = processed.get("first_page_text") or ""

    document_id = execute_insert(
        """
        INSERT INTO documents (
            transaction_id, document_type, filename, s3_key, file_size, uploaded_by, uploaded_at
        ) VALUES (%s, %s, %s, %s, %s, %s, CURRENT_TIMESTAMP)
        RETURNING id
        """,
        (
            transaction["id"],
            final_document_type,
            filename_for_storage,
            s3_key,
            file_size,
            uploaded_by,
        ),
    )
    if document_id:
        key_info = classification.get("key_info_extracted")
        post_actions = apply_document_post_upload_actions(
            transaction_id=transaction["id"],
            document_type=final_document_type,
            first_page_text=first_page_text,
            key_info_extracted=(key_info if isinstance(key_info, dict) else {}),
            uploaded_by=uploaded_by,
        )
        execute_query(
            """
            INSERT INTO communications (transaction_id, communication_type, contact_party, contact_name, summary, outcome)
            VALUES (%s, 'note', 'system', 'document_processor', %s, %s)
            """,
            (
                transaction["id"],
                "Smart document classification completed (client upload)",
                (
                    f"doc_id={document_id} selected_type={document_type} "
                    f"predicted_type={predicted_type} final_type={final_document_type} "
                    f"confidence={int(classification.get('confidence') or 0)} "
                    f"source={(classification.get('source') or 'heuristic')} "
                    f"actions={post_actions.get('summary') or 'none'}"
                )[:1800],
            ),
        )

        if predicted_type != "unknown" and predicted_type != final_document_type:
            execute_query(
                """
                INSERT INTO document_classification_corrections (
                    document_id, transaction_id, original_document_type, corrected_document_type,
                    first_page_signature, first_page_excerpt, correction_reason, corrected_by
                )
                VALUES (%s, %s, %s, %s, md5(%s), %s, %s, %s)
                """,
                (
                    document_id,
                    transaction["id"],
                    predicted_type,
                    final_document_type,
                    first_page_text[:3000],
                    first_page_text[:600],
                    "Auto fallback from unknown prediction to selected upload type",
                    "system",
                ),
            )

        run_document_analysis_async(
            document_id=document_id,
            transaction_id=transaction["id"],
            document_type=final_document_type,
            s3_key=s3_key,
            extension=extension,
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
        (transaction["id"], final_document_type),
    )

    mark_client_accessed(access_row["id"])

    redirect_url = url_for(
        "client_portal_documents",
        access_token=access_token,
        notice=f"Uploaded {document_type_label(final_document_type)} successfully.",
        notice_type="success",
    )
    return redirect(redirect_url)


@app.route("/vendor-response/<int:transaction_id>/<vendor_type>", methods=["POST"])
def vendor_response_webhook(transaction_id, vendor_type):
    """
    Receive scheduling webhook callbacks from vendor booking tools.
    """
    ensure_vendor_automation_tables()
    normalized_vendor_type = normalize_vendor_type(vendor_type)
    if normalized_vendor_type not in VENDOR_TYPES:
        return jsonify({"success": False, "error": "invalid_vendor_type"}), 400
    if not get_transaction_or_none(transaction_id):
        return jsonify({"success": False, "error": "transaction_not_found"}), 404

    payload = request.get_json(silent=True) or {}
    scheduled_input = (
        payload.get("scheduled_time")
        or payload.get("scheduled_at")
        or payload.get("start_time")
        or payload.get("event_start")
    )
    if not scheduled_input and isinstance(payload.get("event"), dict):
        scheduled_input = payload["event"].get("start_time")
    scheduled_at = parse_schedule_datetime(scheduled_input)
    scheduled_date = scheduled_at.date() if scheduled_at else date.today()
    vendor_id = parse_optional_int(payload.get("vendor_id"))
    notes = (
        payload.get("notes")
        or payload.get("message")
        or payload.get("event_type")
        or "Scheduling webhook received"
    )
    notes = str(notes).strip()[:1200]

    log_vendor_outreach(
        transaction_id=transaction_id,
        vendor_type=normalized_vendor_type,
        vendor_id=vendor_id,
        outreach_type="scheduled",
        response_received=True,
        response_date=datetime.utcnow(),
        scheduled_date=scheduled_date,
        notes=notes,
    )
    completed_task_ids = complete_vendor_followup_tasks(transaction_id, normalized_vendor_type)
    vendor_display = "Surveyor" if normalized_vendor_type == "surveyor" else normalized_vendor_type.title()
    calendar_sync_result = {"success": False, "skipped": "not_timed"}
    if scheduled_at:
        calendar_sync_result = sync_vendor_appointment_to_calendar(
            transaction_id=transaction_id,
            vendor_type=normalized_vendor_type,
            appointment_at=scheduled_at,
            vendor_name=vendor_display,
            source_ref=f"vendor_webhook:{normalized_vendor_type}:{transaction_id}",
            source_id=vendor_id or 0,
            notes=notes,
        )

    execute_query(
        """
        INSERT INTO communications (transaction_id, communication_type, contact_party, contact_name, summary, outcome)
        VALUES (%s, 'note', %s, 'vendor_webhook', %s, %s)
        """,
        (
            transaction_id,
            normalized_vendor_type,
            "Vendor scheduling webhook received",
            (
                f"scheduled_date={scheduled_date.isoformat()} "
                f"completed_tasks={','.join(str(task_id) for task_id in completed_task_ids) or 'none'} "
                f"calendar_sync={calendar_sync_result.get('action') or calendar_sync_result.get('error') or calendar_sync_result.get('skipped') or 'n/a'}"
            ),
        ),
    )

    margaret_phone = os.getenv("MARGARET_PHONE")
    if margaret_phone:
        schedule_label = scheduled_date.strftime("%b %d")
        send_sms(
            margaret_phone,
            (
                f"✅ {vendor_display} scheduled for {schedule_label} "
                f"- Transaction #{transaction_id}"
            ),
        )

    return jsonify(
        {
            "success": True,
            "transaction_id": transaction_id,
            "vendor_type": normalized_vendor_type,
            "scheduled_date": scheduled_date.isoformat(),
            "completed_task_ids": completed_task_ids,
        }
    ), 200


@app.route("/vendor/outreach/<access_token>", methods=["GET", "POST"])
def vendor_outreach_response(access_token):
    """Public response endpoint for vendor confirmation links."""
    ensure_timeline_automation_tables()
    outreach = fetch_vendor_outreach_by_token(access_token)
    if not outreach:
        return "This vendor response link is invalid or expired.", 404

    if request.method == "GET":
        return render_template(
            "vendor_outreach_response.html",
            outreach=outreach,
            submitted=False,
            success=False,
            appointment_label="",
        )

    response_status = (request.form.get("response_status") or "confirmed").strip().lower()
    if response_status not in {"confirmed", "needs_call", "unable"}:
        response_status = "confirmed"
    appointment_at = parse_vendor_datetime(request.form.get("appointment_at"))
    notes = (request.form.get("notes") or "").strip()[:1200]

    execute_query(
        """
        UPDATE vendor_outreach
        SET responded_at = CURRENT_TIMESTAMP,
            response_status = %s,
            appointment_at = %s,
            appointment_notes = %s,
            updated_at = CURRENT_TIMESTAMP
        WHERE id = %s
        """,
        (response_status, appointment_at, notes or None, outreach["id"]),
    )

    calendar_event_id = None
    calendar_sync_result = {"success": False, "skipped": "not_timed"}
    if appointment_at:
        calendar_event_id = execute_insert(
            """
            INSERT INTO calendar_events (
                transaction_id, vendor_outreach_id, event_type, title, starts_at, ends_at, details, created_at
            )
            VALUES (%s, %s, 'vendor_appointment', %s, %s, %s, %s, CURRENT_TIMESTAMP)
            RETURNING id
            """,
            (
                outreach["transaction_id"],
                outreach["id"],
                f"{(outreach.get('vendor_type') or 'vendor').title()} appointment - {outreach.get('property_address')}",
                appointment_at,
                appointment_at + timedelta(minutes=45),
                notes or "Appointment confirmed by vendor via secure link.",
            ),
        )
        calendar_sync_result = sync_vendor_appointment_to_calendar(
            transaction_id=outreach["transaction_id"],
            vendor_type=outreach.get("vendor_type"),
            appointment_at=appointment_at,
            vendor_name=outreach.get("vendor_name") or "",
            source_ref=f"vendor_outreach:{outreach['id']}",
            source_id=outreach.get("id") or 0,
            notes=notes,
        )

    completed_task_ids = complete_vendor_response_tasks(
        [outreach.get("related_task_id"), outreach.get("followup_task_id")],
        appointment_at=appointment_at,
        notes=notes,
    )
    execute_query(
        """
        INSERT INTO communications (transaction_id, communication_type, contact_party, contact_name, summary, outcome)
        VALUES (%s, 'note', %s, %s, %s, %s)
        """,
        (
            outreach["transaction_id"],
            outreach.get("vendor_type") or "vendor",
            outreach.get("vendor_name") or "Vendor",
            "Vendor responded via secure outreach link",
            (
                f"status={response_status} appointment={appointment_at.isoformat() if appointment_at else 'none'} "
                f"calendar_event_id={calendar_event_id or 'n/a'} "
                f"google_calendar={calendar_sync_result.get('action') or calendar_sync_result.get('error') or calendar_sync_result.get('skipped') or 'n/a'} "
                f"completed_tasks={','.join(str(task_id) for task_id in completed_task_ids) or 'none'}"
            ),
        ),
    )

    refreshed = fetch_vendor_outreach_by_token(access_token) or outreach
    appointment_label = appointment_at.strftime("%b %d, %Y %I:%M %p") if appointment_at else ""
    return render_template(
        "vendor_outreach_response.html",
        outreach=refreshed,
        submitted=True,
        success=True,
        appointment_label=appointment_label,
    )


def _handle_regenerate_timeline_request(transaction_id):
    """Shared redirect flow for manual timeline regeneration endpoints."""
    transaction = get_transaction_or_none(transaction_id)
    if not transaction:
        return "Transaction not found", 404
    if (transaction.get("status") or "").upper() not in {"ACTIVE", "COMPLETED"}:
        return "Timeline regeneration is only available for active/completed transactions.", 400

    result = regenerate_and_resend_timeline(
        transaction_id=transaction_id,
        reason="manual_refresh",
        force=True,
        send_vendor_notifications=False,
    )
    if not result.get("success"):
        redirect_url = url_for(
            "tc_transaction",
            transaction_id=transaction_id,
            doc_notice="Timeline regeneration failed. Please retry.",
            doc_notice_type="error",
        )
        return redirect(redirect_url)

    redirect_url = url_for(
        "tc_transaction",
        transaction_id=transaction_id,
        doc_notice="Timeline regenerated and re-sent successfully.",
        doc_notice_type="success",
    )
    return redirect(f"{redirect_url}#timeline-pdf")


@app.route("/tc/transaction/<int:transaction_id>/resend-timeline", methods=["POST"])
@login_required
def resend_timeline_packet(transaction_id):
    """Backward-compatible route for manual timeline resend."""
    return _handle_regenerate_timeline_request(transaction_id)


@app.route("/tc/transaction/<int:transaction_id>/regenerate-timeline", methods=["POST"])
@login_required
def regenerate_transaction_timeline(transaction_id):
    """Allow TC to manually regenerate + resend timeline packet."""
    return _handle_regenerate_timeline_request(transaction_id)


@app.route("/tc/transaction/<int:transaction_id>/document-analysis")
@login_required
def tc_document_analysis(transaction_id):
    """Show document analysis dashboard for one transaction."""
    transaction = get_transaction_or_none(transaction_id)
    if not transaction:
        return "Transaction not found", 404

    analysis_rows = get_document_analysis_rows(transaction_id)
    hoa_summary = next((row for row in analysis_rows if row.get("document_type") == "hoa"), None)
    inspection_summary = next((row for row in analysis_rows if row.get("document_type") == "inspection"), None)
    appraisal_summary = next((row for row in analysis_rows if row.get("document_type") == "appraisal"), None)

    return render_template(
        "tc_document_analysis.html",
        transaction=transaction,
        analysis_rows=analysis_rows,
        hoa_summary=hoa_summary,
        inspection_summary=inspection_summary,
        appraisal_summary=appraisal_summary,
    )


@app.route("/tc/transaction/<int:transaction_id>/document-analysis/<int:analysis_id>/review", methods=["POST"])
@login_required
def mark_document_analysis_reviewed(transaction_id, analysis_id):
    """Allow Margaret to mark an analysis row as reviewed and save notes."""
    if not get_transaction_or_none(transaction_id):
        return "Transaction not found", 404

    notes = (request.form.get("notes") or "").strip()
    reviewed = parse_bool_value(request.form.get("reviewed"), default=True)
    execute_query(
        """
        UPDATE document_analysis_results
        SET margaret_reviewed = %s,
            reviewed_at = CASE WHEN %s THEN CURRENT_TIMESTAMP ELSE NULL END,
            notes = %s
        WHERE id = %s
          AND transaction_id = %s
        """,
        (reviewed, reviewed, notes or None, analysis_id, transaction_id),
    )

    execute_query(
        """
        INSERT INTO communications (transaction_id, communication_type, contact_party, contact_name, summary, outcome)
        VALUES (%s, 'note', 'system', %s, %s, %s)
        """,
        (
            transaction_id,
            session.get("tc_username", "margaret"),
            "Document analysis review updated",
            f"analysis_id={analysis_id} reviewed={reviewed}",
        ),
    )

    return redirect(url_for("tc_document_analysis", transaction_id=transaction_id))


@app.route("/tc/transaction/<int:transaction_id>/document-analysis/override-task", methods=["POST"])
@login_required
def override_document_analysis_task(transaction_id):
    """Mark an auto-created analysis task as not applicable."""
    if not get_transaction_or_none(transaction_id):
        return "Transaction not found", 404

    try:
        task_id = int(request.form.get("task_id") or "0")
    except ValueError:
        return redirect(url_for("tc_document_analysis", transaction_id=transaction_id))
    if task_id <= 0:
        return redirect(url_for("tc_document_analysis", transaction_id=transaction_id))

    execute_query(
        """
        UPDATE tasks
        SET completed = TRUE,
            status = 'not_applicable',
            completed_at = CURRENT_TIMESTAMP,
            completed_by = %s,
            notes = CASE
                WHEN COALESCE(notes, '') = '' THEN %s
                ELSE notes || E'\n' || %s
            END
        WHERE id = %s
          AND transaction_id = %s
        """,
        (
            session.get("tc_username", "margaret"),
            "[Override] Marked not applicable from document analysis dashboard.",
            "[Override] Marked not applicable from document analysis dashboard.",
            task_id,
            transaction_id,
        ),
    )

    execute_query(
        """
        INSERT INTO communications (transaction_id, communication_type, contact_party, contact_name, summary, outcome)
        VALUES (%s, 'note', 'system', %s, %s, %s)
        """,
        (
            transaction_id,
            session.get("tc_username", "margaret"),
            "Document analysis task overridden",
            f"task_id={task_id} marked_not_applicable=true",
        ),
    )

    return redirect(url_for("tc_document_analysis", transaction_id=transaction_id))


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


@app.route("/tc/document/<int:document_id>/classification-correction", methods=["POST"])
@login_required
def correct_document_classification(document_id):
    """Allow Margaret to correct smart document classification labels."""
    ensure_document_classification_corrections_table()
    corrected_type = normalize_document_type(request.form.get("corrected_document_type"), fallback="unknown")
    if corrected_type not in DOCUMENT_CLASSIFICATION_OVERRIDE_TYPES:
        return "Invalid document type override.", 400

    correction_reason = (request.form.get("correction_reason") or "").strip()
    correction_reason = correction_reason[:800] if correction_reason else ""

    rows = execute_query(
        """
        SELECT id, transaction_id, document_type, filename, s3_key
        FROM documents
        WHERE id = %s
        LIMIT 1
        """,
        (document_id,),
        fetch=True,
    ) or []
    if not rows:
        return "Document not found.", 404

    document = rows[0]
    transaction_id = document["transaction_id"]
    original_type = normalize_document_type(document.get("document_type"), fallback="other")
    if original_type == corrected_type:
        redirect_url = url_for(
            "tc_transaction",
            transaction_id=transaction_id,
            doc_notice="Document type is already set to that value.",
            doc_notice_type="warning",
        )
        return redirect(f"{redirect_url}#documents")

    execute_query(
        """
        UPDATE documents
        SET document_type = %s
        WHERE id = %s
        """,
        (corrected_type, document_id),
    )
    execute_query(
        """
        INSERT INTO document_classification_corrections (
            document_id, transaction_id, original_document_type, corrected_document_type,
            first_page_signature, first_page_excerpt, correction_reason, corrected_by
        )
        VALUES (%s, %s, %s, %s, md5(%s), %s, %s, %s)
        """,
        (
            document_id,
            transaction_id,
            original_type,
            corrected_type,
            f"{document.get('filename') or ''}|{document.get('s3_key') or ''}",
            (document.get("filename") or "")[:500],
            correction_reason or "Manual classification correction by Margaret",
            session.get("tc_username", "margaret"),
        ),
    )

    action_result = apply_document_post_upload_actions(
        transaction_id=transaction_id,
        document_type=corrected_type,
        first_page_text="",
        key_info_extracted={},
        uploaded_by=session.get("tc_username", "margaret"),
    )
    execute_query(
        """
        INSERT INTO communications (transaction_id, communication_type, contact_party, contact_name, summary, outcome)
        VALUES (%s, 'note', 'system', %s, %s, %s)
        """,
        (
            transaction_id,
            session.get("tc_username", "margaret"),
            "Document classification corrected",
            (
                f"document_id={document_id} original_type={original_type} corrected_type={corrected_type} "
                f"reason={(correction_reason or 'n/a')[:280]} "
                f"actions={action_result.get('summary') or 'none'}"
            )[:1800],
        ),
    )

    extension = file_extension(document.get("filename") or "")
    if document.get("s3_key"):
        run_document_analysis_async(
            document_id=document_id,
            transaction_id=transaction_id,
            document_type=corrected_type,
            s3_key=document["s3_key"],
            extension=extension,
        )

    redirect_url = url_for(
        "tc_transaction",
        transaction_id=transaction_id,
        doc_notice=(
            f"Document type corrected to {document_type_label(corrected_type)}."
        ),
        doc_notice_type="success",
    )
    return redirect(f"{redirect_url}#documents")


@app.route("/tc/voice-note/<int:voice_note_id>/audio")
@login_required
def tc_voice_note_audio(voice_note_id):
    """Stream original Twilio voice-note audio for playback in communication log."""
    ensure_voice_note_tables()
    payload = fetch_voice_note_audio_payload(voice_note_id)
    if not payload.get("success"):
        return payload.get("error") or "Voice note audio unavailable.", 404
    return Response(
        payload["data"],
        mimetype=payload.get("content_type") or "audio/mpeg",
        headers={
            "Content-Disposition": f'inline; filename="{payload.get("filename") or f"voice-note-{voice_note_id}.mp3"}"',
            "Cache-Control": "private, max-age=600",
        },
    )


@app.route("/tc/transaction/<int:transaction_id>/inbound-email-rule", methods=["POST"])
@login_required
def save_inbound_email_rule(transaction_id):
    """Save Margaret routing preference for inbound sender role."""
    if not get_transaction_or_none(transaction_id):
        return "Transaction not found", 404

    sender_role = (request.form.get("sender_role") or "").strip().lower()
    if sender_role not in INBOUND_SENDER_ROLES:
        redirect_url = url_for(
            "tc_transaction",
            transaction_id=transaction_id,
            doc_notice="Invalid sender role for inbound rule.",
            doc_notice_type="error",
        )
        return redirect(f"{redirect_url}#communications")

    always_notify = parse_bool_value(request.form.get("always_notify_margaret"), default=False)
    forward_policy = (request.form.get("forward_policy") or "default").strip().lower()
    upsert_inbound_email_rule(
        transaction_id=transaction_id,
        sender_role=sender_role,
        always_notify_margaret=always_notify,
        forward_policy=forward_policy,
    )
    redirect_url = url_for(
        "tc_transaction",
        transaction_id=transaction_id,
        doc_notice=f"Inbound rule saved for {sender_role.replace('_', ' ').title()}.",
        doc_notice_type="success",
    )
    return redirect(f"{redirect_url}#communications")


@app.route("/tc/transaction/<int:transaction_id>/inbound-email/<int:message_id>/reply", methods=["POST"])
@login_required
def reply_inbound_email_with_qa(transaction_id, message_id):
    """Send Margaret-approved answer and update Smart Q&A learning state."""
    ensure_common_qa_tables()
    transaction = fetch_timeline_transaction(transaction_id)
    if not transaction:
        return "Transaction not found", 404
    inbound_row = fetch_inbound_email_message(transaction_id, message_id)
    if not inbound_row:
        return "Inbound message not found", 404

    sender_email = normalize_email(inbound_row.get("sender_email"))
    if not sender_email or not is_email_valid(sender_email):
        redirect_url = url_for(
            "tc_transaction",
            transaction_id=transaction_id,
            doc_notice="Inbound sender email is invalid; cannot send reply.",
            doc_notice_type="error",
        )
        return redirect(f"{redirect_url}#communications")

    action = (request.form.get("action") or "").strip().lower()
    question_text = build_inbound_question_text(inbound_row.get("subject"), inbound_row.get("body_text"))
    category = normalize_common_qa_category(
        request.form.get("qa_category"),
        fallback=infer_common_qa_category(question_text),
    )
    current_qa_id = inbound_row.get("qa_match_id")
    existing_suggested_answer = (inbound_row.get("qa_answer_text") or "").strip()

    answer_text = ""
    event_type = "manual_answer_recorded"
    qa_variant_created = False
    qa_used_id = current_qa_id

    if action == "use_suggested":
        answer_text = existing_suggested_answer
        if not answer_text:
            redirect_url = url_for(
                "tc_transaction",
                transaction_id=transaction_id,
                doc_notice="No suggested answer is available for this message.",
                doc_notice_type="warning",
            )
            return redirect(f"{redirect_url}#communications")
        if qa_used_id:
            increment_common_qa_reuse(qa_used_id, increment_by=1)
        event_type = "suggested_answer_used"
    elif action == "send_custom":
        answer_text = (request.form.get("answer_text") or "").strip()
        if not answer_text:
            redirect_url = url_for(
                "tc_transaction",
                transaction_id=transaction_id,
                doc_notice="Answer text is required.",
                doc_notice_type="warning",
            )
            return redirect(f"{redirect_url}#communications")

        if qa_used_id and existing_suggested_answer:
            similarity = answer_similarity(existing_suggested_answer, answer_text)
            if similarity < common_qa_variant_similarity_threshold():
                variant_row = create_common_qa_entry(
                    question_text=question_text,
                    answer_text=answer_text,
                    transaction_id=transaction_id,
                    asked_by_party=inbound_row.get("sender_role") or "agent",
                    category=category,
                    force_new=True,
                )
                if variant_row:
                    qa_used_id = variant_row["id"]
                qa_variant_created = True
                event_type = "suggested_answer_variant_created"
            else:
                update_common_qa_entry(
                    common_qa_id=qa_used_id,
                    answer_text=answer_text,
                    category=category,
                )
                increment_common_qa_reuse(qa_used_id, increment_by=1)
                event_type = "suggested_answer_used"
        else:
            created = create_common_qa_entry(
                question_text=question_text,
                answer_text=answer_text,
                transaction_id=transaction_id,
                asked_by_party=inbound_row.get("sender_role") or "agent",
                category=category,
                force_new=True,
            )
            if created:
                qa_used_id = created["id"]
            event_type = "manual_answer_recorded"
    else:
        redirect_url = url_for(
            "tc_transaction",
            transaction_id=transaction_id,
            doc_notice="Unknown reply action.",
            doc_notice_type="warning",
        )
        return redirect(f"{redirect_url}#communications")

    reply_message_id = send_common_qa_reply_email(
        transaction=transaction,
        to_email=sender_email,
        original_subject=inbound_row.get("subject"),
        answer_text=answer_text,
        auto_sent=False,
    )
    if not reply_message_id:
        redirect_url = url_for(
            "tc_transaction",
            transaction_id=transaction_id,
            doc_notice="Could not send reply email.",
            doc_notice_type="error",
        )
        return redirect(f"{redirect_url}#communications")

    execute_query(
        """
        UPDATE inbound_email_messages
        SET qa_match_id = COALESCE(%s, qa_match_id),
            qa_answer_text = %s,
            qa_used = TRUE,
            qa_used_at = CURRENT_TIMESTAMP,
            qa_variant_created = qa_variant_created OR %s,
            reply_message_id = %s,
            replied_at = CURRENT_TIMESTAMP,
            updated_at = CURRENT_TIMESTAMP
        WHERE transaction_id = %s
          AND id = %s
        """,
        (
            qa_used_id,
            answer_text,
            qa_variant_created,
            reply_message_id,
            transaction_id,
            message_id,
        ),
    )

    log_common_qa_event(
        event_type=event_type,
        common_qa_id=qa_used_id,
        transaction_id=transaction_id,
        channel="email",
        asked_by_party=inbound_row.get("sender_role") or "agent",
        question_text=question_text,
        answer_text=answer_text,
        similarity_score=inbound_row.get("qa_similarity"),
        confidence_score=inbound_row.get("qa_confidence"),
        auto_answer=False,
    )
    execute_query(
        """
        INSERT INTO communications (transaction_id, communication_type, contact_party, contact_name, summary, outcome)
        VALUES (%s, 'email', %s, %s, %s, %s)
        """,
        (
            transaction_id,
            inbound_row.get("sender_role") or "external",
            sender_email,
            "Margaret replied to inbound email",
            (
                f"message_id={message_id} qa_id={qa_used_id or 'n/a'} "
                f"variant_created={qa_variant_created} reply_message_id={reply_message_id}"
            ),
        ),
    )

    redirect_url = url_for(
        "tc_transaction",
        transaction_id=transaction_id,
        doc_notice="Inbound reply sent and Q&A learning updated.",
        doc_notice_type="success",
    )
    return redirect(f"{redirect_url}#communications")


@app.route("/tc/transaction/<int:transaction_id>/inbound-email/<int:message_id>/override", methods=["POST"])
@login_required
def override_inbound_email_routing(transaction_id, message_id):
    """Allow Margaret to override one inbound-email routing decision."""
    transaction = fetch_timeline_transaction(transaction_id)
    if not transaction:
        return "Transaction not found", 404
    inbound_row = fetch_inbound_email_message(transaction_id, message_id)
    if not inbound_row:
        return "Inbound message not found", 404

    override_route = (request.form.get("override_route") or "").strip().lower()
    if override_route not in {"log_only", "medium_awareness", "high_action"}:
        redirect_url = url_for(
            "tc_transaction",
            transaction_id=transaction_id,
            doc_notice="Invalid override route selected.",
            doc_notice_type="error",
        )
        return redirect(f"{redirect_url}#communications")

    override_notes = (request.form.get("override_notes") or "").strip()
    clear_risk = parse_bool_value(request.form.get("clear_risk"), default=False)

    analysis = {
        "urgency": inbound_row.get("urgency") or "low",
        "category": inbound_row.get("category") or "general",
        "action_required": bool(inbound_row.get("action_required")),
        "sensitive_content": bool(inbound_row.get("sensitive_content")),
        "recommended_task": "",
    }
    forward_roles = build_inbound_forward_roles(
        route=override_route,
        category=analysis.get("category"),
        sender_role=inbound_row.get("sender_role"),
        sensitive_content=bool(analysis.get("sensitive_content")),
    )
    forwarded = send_inbound_forward_notifications(
        transaction=transaction,
        sender_email=inbound_row.get("sender_email") or "unknown-sender",
        sender_role=inbound_row.get("sender_role") or "external",
        subject=inbound_row.get("subject") or "(No subject)",
        body_text=inbound_row.get("body_text") or "",
        analysis=analysis,
        recipient_roles=forward_roles,
    )
    sms_sent = bool(inbound_row.get("sms_sent"))
    if override_route == "high_action":
        margaret_phone = normalize_phone(os.getenv("MARGARET_PHONE") or "")
        if margaret_phone:
            send_sms_async(
                margaret_phone,
                f"🚨 Manual override: urgent inbound email on {transaction.get('property_address')}",
            )
            sms_sent = True

    task_id = inbound_row.get("task_id")
    if not task_id and override_route in {"medium_awareness", "high_action"}:
        task_id = apply_inbound_task_effects(
            transaction_id=transaction_id,
            analysis=analysis,
            route=override_route,
            subject=inbound_row.get("subject") or "(No subject)",
            body_text=inbound_row.get("body_text") or "",
        )

    combined_forwarded = list(inbound_row.get("forwarded_to") or [])
    for item in forwarded:
        if item not in combined_forwarded:
            combined_forwarded.append(item)

    execute_query(
        """
        UPDATE inbound_email_messages
        SET applied_route = %s,
            forwarded_to = %s::jsonb,
            sms_sent = %s,
            task_id = COALESCE(%s, task_id),
            override_route = %s,
            override_notes = %s,
            override_by = %s,
            override_at = CURRENT_TIMESTAMP,
            updated_at = CURRENT_TIMESTAMP
        WHERE id = %s
          AND transaction_id = %s
        """,
        (
            override_route,
            json.dumps(combined_forwarded, default=str),
            sms_sent,
            task_id,
            override_route,
            override_notes or None,
            session.get("tc_username", "margaret"),
            message_id,
            transaction_id,
        ),
    )

    if clear_risk:
        set_transaction_risk_state(
            transaction_id=transaction_id,
            is_at_risk=False,
            reason="Risk cleared by Margaret override.",
            latest_message_id=message_id,
        )

    execute_query(
        """
        INSERT INTO communications (transaction_id, communication_type, contact_party, contact_name, summary, outcome)
        VALUES (%s, 'note', 'system', %s, %s, %s)
        """,
        (
            transaction_id,
            session.get("tc_username", "margaret"),
            "Inbound routing overridden",
            (
                f"message_id={message_id} route={override_route} "
                f"forwarded_now={len(forwarded)} clear_risk={clear_risk}"
            ),
        ),
    )
    redirect_url = url_for(
        "tc_transaction",
        transaction_id=transaction_id,
        doc_notice="Inbound routing override saved.",
        doc_notice_type="success",
    )
    return redirect(f"{redirect_url}#communications")


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


@app.route("/review/<access_token>", methods=["GET", "POST"])
def submit_agent_review(access_token):
    """Public review form for agent completion feedback."""
    ensure_review_system_tables()
    rows = execute_query(
        """
        SELECT rr.id, rr.transaction_id, rr.agent_email, rr.status, rr.requested_at, rr.completed_at,
               t.property_address, t.agent_name
        FROM agent_review_requests rr
        JOIN transactions t ON t.id = rr.transaction_id
        WHERE rr.access_token = %s
        LIMIT 1
        """,
        (access_token,),
        fetch=True,
    ) or []
    if not rows:
        return "Invalid or expired review link.", 404

    review_request = rows[0]
    if request.method == "GET":
        return render_template(
            "review_form.html",
            review_request=review_request,
            submitted=(review_request.get("status") == "completed"),
            error="",
        )

    if review_request.get("status") == "completed":
        return render_template("review_form.html", review_request=review_request, submitted=True, error="")

    rating = parse_optional_int(request.form.get("rating"))
    feedback = (request.form.get("feedback") or "").strip()
    if not rating or rating < 1 or rating > 5:
        return render_template(
            "review_form.html",
            review_request=review_request,
            submitted=False,
            error="Please select a rating from 1 to 5.",
        )
    if not feedback:
        return render_template(
            "review_form.html",
            review_request=review_request,
            submitted=False,
            error="Please include a few words of feedback.",
        )

    review_id = execute_insert(
        """
        INSERT INTO agent_reviews (
            request_id, transaction_id, agent_email, rating, feedback, created_at
        ) VALUES (%s, %s, %s, %s, %s, CURRENT_TIMESTAMP)
        RETURNING id
        """,
        (
            review_request["id"],
            review_request["transaction_id"],
            review_request.get("agent_email"),
            int(rating),
            feedback,
        ),
    )
    execute_query(
        """
        UPDATE agent_review_requests
        SET status = 'completed',
            completed_at = CURRENT_TIMESTAMP
        WHERE id = %s
        """,
        (review_request["id"],),
    )
    execute_query(
        """
        INSERT INTO communications (transaction_id, communication_type, contact_party, contact_name, summary, outcome)
        VALUES (%s, 'note', 'agent', %s, %s, %s)
        """,
        (
            review_request["transaction_id"],
            review_request.get("agent_name") or "Agent",
            "Agent review submitted",
            f"review_id={review_id or 'n/a'} rating={int(rating)}",
        ),
    )

    if int(rating) >= POSITIVE_REVIEW_THRESHOLD:
        auto_post_positive_review(review_id)
    else:
        alert_margaret_negative_review(
            transaction_id=review_request["transaction_id"],
            rating=int(rating),
            feedback=feedback,
        )

    return render_template("review_form.html", review_request=review_request, submitted=True, error="")


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


def _completion_force_flag():
    payload = request.get_json(silent=True)
    if isinstance(payload, dict) and "force_complete" in payload:
        return parse_bool_value(payload.get("force_complete"), default=False)
    return parse_bool_value(request.form.get("force_complete"), default=False)


@app.route("/tc/transaction/<int:transaction_id>/complete", methods=["POST"])
@login_required
def complete_transaction(transaction_id):
    """
    Execute full transaction completion sequence.
    """
    try:
        result = execute_transaction_completion_workflow(
            transaction_id=transaction_id,
            force_complete=_completion_force_flag(),
            initiated_by=session.get("tc_username", "margaret"),
        )
        if result.get("success"):
            return jsonify(
                {
                    "success": True,
                    "message": "Transaction completed successfully",
                    "actions_completed": 15,
                    "result": result,
                }
            )

        status_code = 409 if result.get("requires_confirmation") else 400
        return (
            jsonify(
                {
                    "success": False,
                    "error": result.get("error") or "completion_failed",
                    "message": result.get("message") or "Some completion steps failed - please review",
                    "requires_confirmation": bool(result.get("requires_confirmation")),
                    "issues": result.get("issues") or [],
                }
            ),
            status_code,
        )
    except ValueError as exc:
        return jsonify({"success": False, "error": str(exc), "message": "Transaction not found"}), 404
    except Exception as exc:
        return (
            jsonify(
                {
                    "success": False,
                    "error": str(exc),
                    "message": "Some completion steps failed - please review",
                }
            ),
            500,
        )


@app.route("/tc/transaction/<int:transaction_id>/mark-complete", methods=["GET", "POST"])
@login_required
def mark_transaction_complete(transaction_id):
    """Legacy completion confirmation route backed by one-click workflow."""
    transaction = get_transaction_or_none(transaction_id)
    if not transaction:
        return "Transaction not found", 404

    if request.method == "GET":
        safety_warning = (request.args.get("safety_warning") or "").strip()
        warning_block = (
            f"<div class='warning'><strong>Safety checks detected:</strong><br>{safety_warning}</div>"
            if safety_warning
            else ""
        )
        force_input = "<input type='hidden' name='force_complete' value='1'>" if safety_warning else ""
        return f"""
        <html>
        <head>
            <title>Mark Complete</title>
            <style>
                body {{ font-family: sans-serif; padding: 40px; max-width: 700px; margin: 0 auto; background:#f8fafc; }}
                .card {{ background: white; padding: 30px; border-radius: 8px; box-shadow: 0 2px 8px rgba(0,0,0,0.1); }}
                h2 {{ color: #1e3a8a; margin-bottom: 20px; }}
                .checklist {{ background: #f9fafb; padding: 20px; border-radius: 6px; margin: 20px 0; }}
                .checklist-item {{ padding: 10px 0; border-bottom: 1px solid #e5e7eb; }}
                .btn {{ padding: 12px 24px; background: #10b981; color: white; border: none; border-radius: 6px; cursor: pointer; font-size: 16px; margin-right: 10px; text-decoration: none; display: inline-block; }}
                .btn-secondary {{ background: #6b7280; }}
                .warning {{ background:#fff7ed; border:1px solid #fdba74; color:#9a3412; padding:12px; border-radius:6px; margin:12px 0; }}
            </style>
        </head>
        <body>
            <div class="card">
                <h2>Mark Transaction Complete</h2>
                <p><strong>Property:</strong> {transaction.get('property_address') or 'N/A'}</p>
                <p><strong>Agent:</strong> {transaction.get('agent_name') or 'N/A'}</p>
                {warning_block}
                <div class="checklist">
                    <h3>Pre-Completion Checklist:</h3>
                    <div class="checklist-item">Closing occurred successfully</div>
                    <div class="checklist-item">All critical documents are uploaded</div>
                    <div class="checklist-item">Final settlement statement uploaded</div>
                    <div class="checklist-item">Commission tracking is current</div>
                    <div class="checklist-item">Closing payment received</div>
                </div>
                <form method="POST">
                    {force_input}
                    <button type="submit" class="btn">Mark Complete</button>
                    <a href="/tc/transaction/{transaction_id}" class="btn btn-secondary">Cancel</a>
                </form>
            </div>
        </body>
        </html>
        """

    force_complete = parse_bool_value(request.form.get("force_complete"), default=False)
    result = execute_transaction_completion_workflow(
        transaction_id=transaction_id,
        force_complete=force_complete,
        initiated_by=session.get("tc_username", "margaret"),
    )
    if result.get("success"):
        return redirect(
            url_for(
                "tc_dashboard",
                notice="Transaction completed successfully.",
                notice_type="success",
            )
        )
    if result.get("requires_confirmation"):
        issue_text = "<br>".join(issue.get("message") or "Issue detected" for issue in (result.get("issues") or []))
        return redirect(
            url_for(
                "mark_transaction_complete",
                transaction_id=transaction_id,
                safety_warning=issue_text,
            )
        )
    return redirect(
        url_for(
            "tc_transaction",
            transaction_id=transaction_id,
            doc_notice=result.get("message") or "Could not complete transaction.",
            doc_notice_type="warning",
        )
    )


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
    settings = fetch_calendar_sync_settings()
    if settings.get("auto_delete_on_cancel"):
        calendar_cleanup = delete_calendar_events(
            transaction_id=transaction_id,
            reason="transaction_cancelled",
        )
    else:
        calendar_cleanup = {"candidate_count": 0, "deleted": 0, "failed": 0}
    execute_query(
        """
        INSERT INTO communications (transaction_id, communication_type, contact_party, contact_name, summary, outcome)
        VALUES (%s, 'note', 'system', 'calendar_sync', %s, %s)
        """,
        (
            transaction_id,
            "Calendar events cleanup on cancellation",
            (
                f"candidate={calendar_cleanup.get('candidate_count', 0)} "
                f"deleted={calendar_cleanup.get('deleted', 0)} "
                f"failed={calendar_cleanup.get('failed', 0)}"
            ),
        ),
    )
    return redirect(url_for("tc_dashboard"))


@app.route("/nudge-response", methods=["POST"])
def handle_nudge_response():
    """
    Handle SMS replies to intelligent nudges via Twilio webhook.
    """
    ensure_intelligent_nudge_tables()
    from_phone = normalize_phone(request.form.get("From", ""))
    message_body_raw = (request.form.get("Body") or "").strip()
    message_body = message_body_raw.lower()
    margaret_phone = normalize_phone(os.getenv("MARGARET_PHONE") or "")

    recent_nudge = get_recent_nudge_by_phone(from_phone)
    if not recent_nudge:
        if margaret_phone:
            send_sms(margaret_phone, f"Unknown SMS from {from_phone or 'unknown'}: {message_body_raw[:220]}")
        return "", 200

    nudge_type = recent_nudge.get("nudge_type") or "deadline_item"
    label = nudge_type_label(nudge_type).lower()
    positive_keywords = ("yes", "scheduled", "done", "complete", "completed")
    help_keywords = ("help", "call", "need help", "margaret")

    if any(keyword in message_body for keyword in positive_keywords):
        mark_nudge_log_responded(recent_nudge["id"])
        completed_task_ids = complete_task_for_nudge(recent_nudge["transaction_id"], nudge_type)
        if from_phone:
            send_sms(from_phone, "Great! I've updated the transaction. Thanks!")
        if margaret_phone:
            send_sms(
                margaret_phone,
                (
                    f"{nudge_type_label(nudge_type)} completed for "
                    f"Transaction #{recent_nudge['transaction_id']}"
                ),
            )
        execute_query(
            """
            INSERT INTO communications (transaction_id, communication_type, contact_party, contact_name, summary, outcome)
            VALUES (%s, 'text', 'agent', %s, %s, %s)
            """,
            (
                recent_nudge["transaction_id"],
                recent_nudge.get("agent_name") or "Agent",
                "Positive intelligent nudge response received",
                (
                    f"nudge_log_id={recent_nudge['id']} completed_tasks="
                    f"{','.join(str(task_id) for task_id in completed_task_ids) or 'none'}"
                ),
            ),
        )
        return "", 200

    if any(keyword in message_body for keyword in help_keywords):
        mark_nudge_log_escalated(recent_nudge["id"])
        followup_task_id = create_deadline_nudge_followup_task(
            recent_nudge["transaction_id"],
            f"Follow up on {label}",
            notes=f"Agent requested help via /nudge-response ({from_phone})",
        )
        execute_query(
            """
            INSERT INTO communications (transaction_id, communication_type, contact_party, contact_name, summary, outcome)
            VALUES (%s, 'text', 'agent', %s, %s, %s)
            """,
            (
                recent_nudge["transaction_id"],
                recent_nudge.get("agent_name") or "Agent",
                "Intelligent nudge escalated to Margaret",
                f"nudge_log_id={recent_nudge['id']} task_id={followup_task_id or 'n/a'}",
            ),
        )
        if margaret_phone:
            send_sms(
                margaret_phone,
                (
                    f"Agent needs help with {label} - "
                    f"Transaction #{recent_nudge['transaction_id']} - {from_phone or 'unknown'}"
                ),
            )
        if from_phone:
            send_sms(from_phone, "I've notified Margaret. She will call you shortly. - Maverick TC")
        return "", 200

    if margaret_phone:
        send_sms(
            margaret_phone,
            (
                f"Unclear nudge response from {from_phone or 'unknown'}: "
                f"'{message_body_raw[:180]}' - Transaction #{recent_nudge['transaction_id']}"
            ),
        )
    return "", 200


@app.route("/voice-note-webhook", methods=["POST"])
def voice_note_webhook():
    """
    Twilio voice-note intake endpoint.
    - Initial call: returns greeting + recording instructions.
    - Recording action callback: stores capture and queues transcription parse.
    - Transcription callback (?stage=transcription): stores transcript and processes actions.
    """
    if not voice_note_webhook_secret_valid():
        return "Unauthorized", 403

    ensure_voice_note_tables()
    callback_stage = (request.args.get("stage") or "").strip().lower()
    if callback_stage == "transcription":
        recording_sid = (request.form.get("RecordingSid") or "").strip()
        transcription_text = (request.form.get("TranscriptionText") or "").strip()
        transcription_status = (request.form.get("TranscriptionStatus") or "completed").strip()
        handle_twilio_transcription_callback(
            recording_sid=recording_sid,
            transcription_text=transcription_text,
            transcription_status=transcription_status,
        )
        return "", 204

    recording_url = (request.form.get("RecordingUrl") or "").strip()
    if recording_url:
        transcription_text = (request.form.get("TranscriptionText") or "").strip()
        transcription_source = "twilio" if transcription_text else None
        voice_row = register_voice_note_capture(
            call_sid=request.form.get("CallSid"),
            recording_sid=request.form.get("RecordingSid"),
            recording_url=recording_url,
            from_phone=request.form.get("From"),
            recording_duration_seconds=request.form.get("RecordingDuration"),
            transcription_text=transcription_text,
            transcription_source=transcription_source or "",
        )
        voice_note_id = voice_row["id"] if voice_row else None
        mode = (os.getenv("VOICE_NOTE_TRANSCRIPTION_MODE") or "twilio").strip().lower()
        if voice_note_id and (transcription_text or mode == "claude"):
            queue_voice_note_processing(
                voice_note_id=voice_note_id,
                transcription_text=transcription_text or None,
                transcription_source=transcription_source or ("claude" if mode == "claude" else None),
            )

        response = VoiceResponse()
        response.say("Thanks. Your voice note is saved. Maverick will text confirmation shortly.")
        response.hangup()
        return Response(str(response), mimetype="text/xml")

    mode = (os.getenv("VOICE_NOTE_TRANSCRIPTION_MODE") or "twilio").strip().lower()
    response = VoiceResponse()
    response.say("Maverick voice notes. Say transaction number, then your note. Beep.")
    record_kwargs = {
        "action": build_voice_note_webhook_url(),
        "method": "POST",
        "play_beep": True,
        "max_length": 120,
        "timeout": 4,
        "trim": "trim-silence",
    }
    if mode == "twilio":
        record_kwargs["transcribe"] = True
        record_kwargs["transcribe_callback"] = build_voice_note_webhook_url(stage="transcription")
    response.record(**record_kwargs)
    response.say("No recording was received. Goodbye.")
    response.hangup()
    return Response(str(response), mimetype="text/xml")


@app.route("/sms-webhook", methods=["POST"])
def sms_webhook():
    """Handle incoming SMS from agents."""
    incoming_msg_raw = request.form.get("Body", "").strip()
    incoming_msg = incoming_msg_raw.lower()
    from_number = normalize_phone(request.form.get("From", ""))
    response = MessagingResponse()

    emergency_keywords = {"emergency", "urgent", "asap", "help now"}
    status_keywords = {"status", "closing", "when", "deadline", "update"}
    affirmative_keywords = {"yes", "yes please", "y", "yep", "yeah", "affirmative"}
    margaret_help_keywords = {"margaret", "please call", "need help", "call me", "need support", "help"}

    ensure_deadline_nudges_table()
    pending_nudge = fetch_open_agent_nudge_by_phone(from_number)
    if pending_nudge:
        if any(keyword in incoming_msg for keyword in margaret_help_keywords):
            mark_deadline_nudge_response(
                nudge_id=pending_nudge["id"],
                response_text=incoming_msg_raw,
                response_channel="sms",
                requested_help=True,
            )
            escalate_deadline_nudge_to_margaret(
                pending_nudge,
                reason="Party explicitly requested Margaret help via SMS.",
                notify_sms=True,
            )
            response.message("Margaret has been notified and will follow up with you shortly. - Maverick TC")
            return str(response)

        if incoming_msg in affirmative_keywords and pending_nudge.get("nudge_key") == "option_period_inspection":
            mark_deadline_nudge_response(
                nudge_id=pending_nudge["id"],
                response_text=incoming_msg_raw,
                response_channel="sms",
                requested_help=False,
            )
            execute_query(
                """
                INSERT INTO communications (transaction_id, communication_type, contact_party, contact_name, summary, outcome)
                VALUES (%s, 'text', 'agent', %s, %s, %s)
                """,
                (
                    pending_nudge["transaction_id"],
                    pending_nudge.get("agent_name") or "Agent",
                    "Agent replied YES to inspection scheduling nudge",
                    f"nudge_id={pending_nudge['id']}",
                ),
            )
            response.message(build_inspector_recommendations_message())
            return str(response)

        if incoming_msg and not any(keyword in incoming_msg for keyword in emergency_keywords.union(status_keywords)):
            mark_deadline_nudge_response(
                nudge_id=pending_nudge["id"],
                response_text=incoming_msg_raw,
                response_channel="sms",
                requested_help=False,
            )
            execute_query(
                """
                INSERT INTO communications (transaction_id, communication_type, contact_party, contact_name, summary, outcome)
                VALUES (%s, 'text', 'agent', %s, %s, %s)
                """,
                (
                    pending_nudge["transaction_id"],
                    pending_nudge.get("agent_name") or "Agent",
                    "Agent replied to proactive deadline nudge",
                    f"nudge_id={pending_nudge['id']} message={incoming_msg_raw[:180]}",
                ),
            )
            response.message("Thanks for the update — we logged your response and will keep the timeline on track.")
            return str(response)

    if any(word in incoming_msg for word in emergency_keywords):
        heidi_phone = os.getenv("HEIDI_PHONE")
        margaret_phone = os.getenv("MARGARET_PHONE")
        if heidi_phone:
            send_sms(heidi_phone, f"EMERGENCY from {from_number}: {incoming_msg}")
        if margaret_phone:
            send_sms(margaret_phone, f"EMERGENCY from {from_number}: {incoming_msg}")
        response.message("Emergency alert sent to Heidi and Margaret. They will call you ASAP.")
        return str(response)

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

    qa_decision = evaluate_common_qa_decision(
        question_text=incoming_msg_raw,
        asked_by_party="agent",
        category_hint=infer_common_qa_category(incoming_msg_raw),
    )
    qa_match = qa_decision.get("match") or {}
    sms_txn_rows = execute_query(
        """
        SELECT id, property_address
        FROM transactions
        WHERE RIGHT(REGEXP_REPLACE(agent_phone, '[^0-9]', '', 'g'), 10) = %s
          AND status IN ('NEEDS_MARGARET_REVIEW', 'ACTIVE')
        ORDER BY created_at DESC
        LIMIT 1
        """,
        (re.sub(r"\D", "", from_number)[-10:],),
        fetch=True,
    ) or []
    sms_transaction = sms_txn_rows[0] if sms_txn_rows else None
    if qa_decision.get("decision") == "auto_answer" and qa_match.get("id") and qa_match.get("answer_text"):
        answer_text = (qa_match.get("answer_text") or "").strip()
        if "- maverick tc" not in answer_text.lower():
            answer_text = f"{answer_text}\n- Maverick TC"
        increment_common_qa_reuse(qa_match["id"], increment_by=1)
        log_common_qa_event(
            event_type="auto_answer_sent",
            common_qa_id=qa_match["id"],
            transaction_id=(sms_transaction or {}).get("id"),
            channel="sms",
            asked_by_party="agent",
            question_text=incoming_msg_raw,
            answer_text=answer_text,
            similarity_score=qa_decision.get("similarity"),
            confidence_score=qa_decision.get("confidence"),
            auto_answer=True,
        )
        if sms_transaction:
            execute_query(
                """
                INSERT INTO communications (transaction_id, communication_type, contact_party, contact_name, summary, outcome)
                VALUES (%s, 'text', 'agent', %s, %s, %s)
                """,
                (
                    sms_transaction["id"],
                    from_number or "Agent",
                    "Smart Q&A auto-answer sent (SMS)",
                    (
                        f"qa_id={qa_match['id']} confidence={float(qa_decision.get('confidence') or 0):.2f} "
                        f"question={(incoming_msg_raw or '')[:140]}"
                    ),
                ),
            )
        response.message(answer_text[:1500])
        return str(response)

    if qa_decision.get("decision") == "suggest" and qa_match.get("id"):
        margaret_phone = normalize_phone(os.getenv("MARGARET_PHONE") or "")
        if margaret_phone:
            property_label = (sms_transaction or {}).get("property_address") or "unknown property"
            send_sms(
                margaret_phone,
                (
                    f"Q&A suggestion ({float(qa_decision.get('confidence') or 0):.0f}%) "
                    f"for {property_label} from {from_number or 'unknown'}: "
                    f"\"{(incoming_msg_raw or '')[:110]}\". Review in Maverick. - Maverick TC"
                )[:320],
            )
        log_common_qa_event(
            event_type="suggested_answer_available",
            common_qa_id=qa_match["id"],
            transaction_id=(sms_transaction or {}).get("id"),
            channel="sms",
            asked_by_party="agent",
            question_text=incoming_msg_raw,
            answer_text=qa_match.get("answer_text"),
            similarity_score=qa_decision.get("similarity"),
            confidence_score=qa_decision.get("confidence"),
            auto_answer=False,
        )
        if sms_transaction:
            execute_query(
                """
                INSERT INTO communications (transaction_id, communication_type, contact_party, contact_name, summary, outcome)
                VALUES (%s, 'text', 'agent', %s, %s, %s)
                """,
                (
                    sms_transaction["id"],
                    from_number or "Agent",
                    "Smart Q&A suggestion flagged for Margaret (SMS)",
                    (
                        f"qa_id={qa_match['id']} confidence={float(qa_decision.get('confidence') or 0):.2f} "
                        f"question={(incoming_msg_raw or '')[:140]}"
                    ),
                ),
            )
        response.message("Thanks for your question. Margaret will follow up shortly. - Maverick TC")
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
