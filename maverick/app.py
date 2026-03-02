import os
import re
import csv
import io
import json
import hashlib
import tempfile
from difflib import SequenceMatcher
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
from automation.morning_briefing import (
    ensure_morning_briefing_tables,
    fetch_latest_morning_briefing,
    fetch_morning_briefing_by_date,
    fetch_morning_briefing_items,
    fetch_morning_briefing_settings,
    generate_evening_recap,
    generate_morning_briefing,
    move_morning_briefing_item,
    update_morning_briefing_item,
    update_morning_briefing_settings,
)
from automation.generate_daily_plan import (
    ensure_daily_plan_tables,
    fetch_daily_plan_by_date,
    fetch_daily_plan_blocks,
    fetch_daily_plan_items,
    fetch_daily_plan_learning_metrics,
    fetch_latest_daily_plan,
    generate_daily_plan,
    reorder_daily_plan_items,
    reorganize_remaining_day,
    update_daily_plan_item,
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
from utils.automation_analytics import build_automation_analytics_snapshot
from utils.document_processing import (
    build_smart_filename,
    ensure_document_classification_corrections_table,
    extract_text_from_first_page,
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
from utils.s3 import download_file, get_presigned_url, log_document_access, upload_contract, upload_document, upload_local_file
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
BATCH_UPLOAD_MAX_FILES = 20

DATE_CASCADE_SUPPORTED_FIELDS = {
    "closing_date",
    "effective_date",
    "earnest_due_date",
    "option_period_end_date",
    "financing_approval_date",
}

DATE_CASCADE_TRANSACTION_COLUMNS = (
    "effective_date",
    "option_fee_due_date",
    "earnest_due_date",
    "seller_disclosure_due_date",
    "survey_due_date",
    "option_period_end_date",
    "hoa_docs_due_date",
    "buyer_hoa_review_end_date",
    "title_commitment_due_date",
    "financing_approval_date",
    "buyer_title_objection_end_date",
    "closing_date",
)

EFFECTIVE_DATE_CASCADE_COLUMNS = (
    "option_fee_due_date",
    "earnest_due_date",
    "seller_disclosure_due_date",
    "survey_due_date",
    "option_period_end_date",
    "hoa_docs_due_date",
    "buyer_hoa_review_end_date",
    "title_commitment_due_date",
    "financing_approval_date",
    "buyer_title_objection_end_date",
)

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

MESSAGE_TEMPLATE_SEEDS = [
    (
        "/closing",
        "Hi {{AGENT_NAME}}, closing for {{PROPERTY_ADDRESS}} is confirmed for {{CLOSING_DATE}} at {{CLOSING_TIME}} at {{TITLE_COMPANY}}. Buyer should bring photo ID and cashier's check for ${{CASH_TO_CLOSE}}. Let me know if you have questions! - Margaret",
        "closing",
    ),
    (
        "/inspection",
        "Hi {{AGENT_NAME}}, inspection is scheduled for {{PROPERTY_ADDRESS}} on {{INSPECTION_DATE}} at {{INSPECTION_TIME}}. Inspector is {{INSPECTOR_NAME}} ({{INSPECTOR_PHONE}}). Please ensure property is accessible and utilities are on. - Margaret",
        "inspection",
    ),
    (
        "/earnest",
        "Earnest money of ${{EARNEST_AMOUNT}} is due by {{EARNEST_DUE_DATE}}. Please wire to {{TITLE_COMPANY}} with reference {{TRANSACTION_ID}}. - Margaret",
        "payment",
    ),
    (
        "/option",
        "Option fee of ${{OPTION_FEE}} is due by {{OPTION_DUE_DATE}}. Please deliver to seller's agent or wire to title. - Margaret",
        "payment",
    ),
    (
        "/appraisal",
        "Appraisal is scheduled for {{APPRAISAL_DATE}}. Appraiser is {{APPRAISER_NAME}} ({{APPRAISER_PHONE}}). Property should be accessible and in showing condition. - Margaret",
        "appraisal",
    ),
    ("/survey", "Survey has been ordered for {{PROPERTY_ADDRESS}}. Expected completion by {{SURVEY_DUE_DATE}}. - Margaret", "survey"),
    (
        "/title",
        "Title file {{TRANSACTION_ID}} has been opened at {{TITLE_COMPANY}}. Contact is {{TITLE_CONTACT}} ({{TITLE_PHONE}}). - Margaret",
        "title",
    ),
    (
        "/hoa",
        "HOA documents for {{PROPERTY_ADDRESS}} are due by {{HOA_DUE_DATE}}. Please provide: declarations, bylaws, financials, and resale certificate. - Margaret",
        "hoa",
    ),
    (
        "/walkthrough",
        "Final walk-through for {{PROPERTY_ADDRESS}} is scheduled for {{WALKTHROUGH_DATE}} at {{WALKTHROUGH_TIME}}. Meet at property. - Margaret",
        "walkthrough",
    ),
    (
        "/congratulations",
        "Congratulations on your closing! Possession is at {{POSSESSION_TIME}}. Please ensure all utilities are transferred. Enjoy your new home! - Margaret",
        "closing",
    ),
    (
        "/repair",
        "Per the repair addendum, seller has agreed to: {{REPAIR_ITEMS}}. Work should be completed by {{REPAIR_COMPLETION_DATE}}. - Margaret",
        "repair",
    ),
    (
        "/extension",
        "Contract extension executed. New closing date is {{NEW_CLOSING_DATE}}. All deadlines adjusted accordingly. - Margaret",
        "extension",
    ),
    (
        "/termination",
        "This transaction has been terminated per the contract. Earnest money will be {{EARNEST_DISPOSITION}}. - Margaret",
        "termination",
    ),
    (
        "/cd",
        "Closing Disclosure is ready for review. Please review carefully and notify us of any discrepancies within 24 hours. - Margaret",
        "closing",
    ),
    (
        "/welcome",
        "Welcome to Maverick TC! I'm Margaret, your transaction coordinator for {{PROPERTY_ADDRESS}}. I'll keep everyone on track from contract to close. Looking forward to a smooth closing on {{CLOSING_DATE}}! - Margaret",
        "general",
    ),
    (
        "/paymentlink",
        "Hi {{AGENT_NAME}}, payment link for {{PROPERTY_ADDRESS}}: {{PAYMENT_LINK}}. Amount due: ${{PAYMENT_AMOUNT}} by {{PAYMENT_DUE_DATE}}. - Margaret",
        "payment",
    ),
    (
        "/wire",
        "Wire reminder for {{PROPERTY_ADDRESS}}: send funds to {{TITLE_COMPANY}} and include file {{TRANSACTION_ID}}. Confirm once sent so we can track receipt. - Margaret",
        "payment",
    ),
    (
        "/loanapproval",
        "Loan approval update for {{PROPERTY_ADDRESS}}: {{LOAN_STATUS}}. Next milestone is {{FINANCING_APPROVAL_DATE}}. Please alert us if underwriting conditions change. - Margaret",
        "payment",
    ),
    (
        "/clear2close",
        "Great news! {{PROPERTY_ADDRESS}} is clear to close. Final signing is {{CLOSING_DATE}} at {{CLOSING_TIME}}. Reach out with any final questions. - Margaret",
        "closing",
    ),
    (
        "/reminderdocs",
        "Quick doc reminder for {{PROPERTY_ADDRESS}}: {{MISSING_DOCUMENTS}}. Please upload in portal: {{PORTAL_LINK}}. - Margaret",
        "document",
    ),
    (
        "/statusweekly",
        "Weekly status for {{PROPERTY_ADDRESS}}: {{STATUS_SUMMARY}}. Next due date: {{NEXT_DEADLINE}}. - Margaret",
        "general",
    ),
    (
        "/titleupdate",
        "Title update for {{PROPERTY_ADDRESS}}: {{TITLE_STATUS}}. Contact at {{TITLE_COMPANY}} is {{TITLE_CONTACT}} ({{TITLE_PHONE}}). - Margaret",
        "title",
    ),
    (
        "/inspectionreport",
        "Inspection report received for {{PROPERTY_ADDRESS}}. Please review and send repair requests by {{REPAIR_REQUEST_DUE_DATE}}. - Margaret",
        "inspection",
    ),
    (
        "/appraisalreport",
        "Appraisal report received for {{PROPERTY_ADDRESS}} at value ${{APPRAISED_VALUE}}. Let me know if you'd like to discuss next steps. - Margaret",
        "appraisal",
    ),
    (
        "/utility",
        "Utility transfer reminder for {{PROPERTY_ADDRESS}}: set service start/end for {{CLOSING_DATE}} and keep account numbers for your records. - Margaret",
        "closing",
    ),
    (
        "/possession",
        "Possession timing for {{PROPERTY_ADDRESS}} is {{POSSESSION_TIME}} on {{CLOSING_DATE}}. Please confirm key handoff details. - Margaret",
        "closing",
    ),
    (
        "/delaynotice",
        "Update for {{PROPERTY_ADDRESS}}: we have a scheduling delay due to {{DELAY_REASON}}. Revised target date is {{NEW_CLOSING_DATE}}. - Margaret",
        "general",
    ),
    (
        "/escalate",
        "Escalation needed for {{PROPERTY_ADDRESS}}: {{ESCALATION_SUMMARY}}. Please contact me at {{MARGARET_PHONE}} when available. - Margaret",
        "general",
    ),
    (
        "/thankyouagent",
        "Thanks for partnering with Maverick TC on {{PROPERTY_ADDRESS}}. We appreciate your responsiveness and teamwork! - Margaret",
        "general",
    ),
    (
        "/reviewrequest",
        "If you have a moment, we'd love your feedback on this transaction experience: {{REVIEW_LINK}}. Thank you! - Margaret",
        "general",
    ),
]
MESSAGE_TEMPLATE_SEEDS_APPLIED = False

CLIENT_TYPES = {"buyer", "seller"}
PARTY_PORTAL_TYPES = {"buyer", "seller", "agent"}
PARTY_PORTAL_DOCUMENTS_BY_TYPE = {
    "buyer": {
        "contract",
        "inspection_report",
        "appraisal",
        "title_commitment",
        "hoa_docs",
        "survey",
        "insurance_binder",
    },
    "seller": {
        "contract",
        "seller_disclosure",
        "signed_amendment",
        "signed_addendum",
        "amendment",
        "survey",
    },
}
PORTAL_SENSITIVE_DOCUMENT_TYPES = {
    "loan_approval",
    "settlement_statement",
    "earnest_receipt",
    "option_receipt",
}
PORTAL_SECTION_NAMES = {"overview", "timeline", "documents", "action_items", "recent_activity", "upload"}

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


def ensure_message_templates_table():
    """Ensure shortcode template table exists and seed defaults."""
    global MESSAGE_TEMPLATE_SEEDS_APPLIED
    execute_query(
        """
        CREATE TABLE IF NOT EXISTS message_templates (
            id SERIAL PRIMARY KEY,
            shortcode VARCHAR(50) UNIQUE,
            template_text TEXT,
            category VARCHAR(50),
            usage_count INT DEFAULT 0,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
        """
    )
    execute_query(
        """
        CREATE INDEX IF NOT EXISTS idx_message_templates_category
        ON message_templates(category)
        """
    )
    execute_query(
        """
        CREATE INDEX IF NOT EXISTS idx_message_templates_usage
        ON message_templates(usage_count DESC)
        """
    )
    if MESSAGE_TEMPLATE_SEEDS_APPLIED:
        return
    seed_ok = True
    for shortcode, template_text, category in MESSAGE_TEMPLATE_SEEDS:
        result = execute_query(
            """
            INSERT INTO message_templates (
                shortcode, template_text, category, usage_count, created_at
            )
            VALUES (%s, %s, %s, 0, CURRENT_TIMESTAMP)
            ON CONFLICT (shortcode) DO NOTHING
            """,
            (shortcode, template_text, category),
        )
        if result is None:
            seed_ok = False
    if seed_ok:
        MESSAGE_TEMPLATE_SEEDS_APPLIED = True


def fetch_message_templates(category="", search_query="", limit=200):
    """List templates with optional category/search filters."""
    ensure_message_templates_table()
    filters = ["TRUE"]
    params = []
    if category:
        filters.append("LOWER(category) = %s")
        params.append((category or "").strip().lower())
    if search_query:
        normalized = (search_query or "").strip().lower()
        if not normalized.startswith("/"):
            normalized = f"/{normalized}"
        filters.append("(LOWER(shortcode) LIKE %s OR LOWER(template_text) LIKE %s)")
        params.extend([f"{normalized}%", f"%{normalized.lstrip('/')}%"])
    params.append(max(1, min(int(limit or 200), 500)))
    rows = execute_query(
        f"""
        SELECT id, shortcode, template_text, category, usage_count, created_at
        FROM message_templates
        WHERE {' AND '.join(filters)}
        ORDER BY usage_count DESC, shortcode ASC
        LIMIT %s
        """,
        tuple(params),
        fetch=True,
    ) or []
    for row in rows:
        text = (row.get("template_text") or "").strip()
        row["preview"] = (text[:110] + "...") if len(text) > 110 else text
        row["created_at_label"] = format_timestamp_label(row.get("created_at"))
    return rows


def get_message_template(template_id):
    """Fetch one message template by ID."""
    ensure_message_templates_table()
    rows = execute_query(
        """
        SELECT id, shortcode, template_text, category, usage_count, created_at
        FROM message_templates
        WHERE id = %s
        LIMIT 1
        """,
        (int(template_id),),
        fetch=True,
    ) or []
    return rows[0] if rows else None


def increment_message_template_usage(template_id):
    """Increment usage count for one template."""
    ensure_message_templates_table()
    execute_query(
        """
        UPDATE message_templates
        SET usage_count = COALESCE(usage_count, 0) + 1
        WHERE id = %s
        """,
        (int(template_id),),
    )


def create_message_template(shortcode, template_text, category):
    """Create one custom message template."""
    ensure_message_templates_table()
    normalized_shortcode = (shortcode or "").strip().lower()
    if normalized_shortcode and not normalized_shortcode.startswith("/"):
        normalized_shortcode = f"/{normalized_shortcode}"
    if not re.match(r"^/[a-z0-9_]{2,49}$", normalized_shortcode):
        return {"success": False, "error": "Shortcode must look like /closing_update."}
    if not (template_text or "").strip():
        return {"success": False, "error": "Template text is required."}
    normalized_category = (category or "general").strip().lower()[:50] or "general"
    rows = execute_query(
        """
        INSERT INTO message_templates (
            shortcode, template_text, category, usage_count, created_at
        )
        VALUES (%s, %s, %s, 0, CURRENT_TIMESTAMP)
        ON CONFLICT (shortcode) DO NOTHING
        RETURNING id
        """,
        (normalized_shortcode, (template_text or "").strip(), normalized_category),
        fetch=True,
    ) or []
    if not rows:
        return {"success": False, "error": "Shortcode already exists."}
    return {"success": True, "template_id": rows[0]["id"]}


def update_message_template(template_id, shortcode, template_text, category):
    """Update template row."""
    ensure_message_templates_table()
    normalized_shortcode = (shortcode or "").strip().lower()
    if normalized_shortcode and not normalized_shortcode.startswith("/"):
        normalized_shortcode = f"/{normalized_shortcode}"
    if not re.match(r"^/[a-z0-9_]{2,49}$", normalized_shortcode):
        return {"success": False, "error": "Shortcode must look like /closing_update."}
    if not (template_text or "").strip():
        return {"success": False, "error": "Template text is required."}
    normalized_category = (category or "general").strip().lower()[:50] or "general"
    rows = execute_query(
        """
        UPDATE message_templates
        SET shortcode = %s,
            template_text = %s,
            category = %s
        WHERE id = %s
        RETURNING id
        """,
        (
            normalized_shortcode,
            (template_text or "").strip(),
            normalized_category,
            int(template_id),
        ),
        fetch=True,
    ) or []
    if not rows:
        return {"success": False, "error": "Template not found or shortcode in use."}
    return {"success": True}


def delete_message_template(template_id):
    """Delete one template row when unused."""
    ensure_message_templates_table()
    template_rows = execute_query(
        """
        SELECT id, usage_count
        FROM message_templates
        WHERE id = %s
        LIMIT 1
        """,
        (int(template_id),),
        fetch=True,
    ) or []
    if not template_rows:
        return {"success": False, "error": "Template not found."}
    if int(template_rows[0].get("usage_count") or 0) > 0:
        return {"success": False, "error": "Only unused templates can be deleted."}
    rows = execute_query(
        """
        DELETE FROM message_templates
        WHERE id = %s
        RETURNING id
        """,
        (int(template_id),),
        fetch=True,
    ) or []
    if not rows:
        return {"success": False, "error": "Template not found."}
    return {"success": True}


def suggest_message_templates_from_history(limit=20):
    """Suggest templates from repeated communication phrasing."""
    rows = execute_query(
        """
        SELECT
            LOWER(REGEXP_REPLACE(TRIM(summary), '\\s+', ' ', 'g')) AS normalized_summary,
            MIN(summary) AS sample_text,
            COUNT(*) AS repeat_count
        FROM communications
        WHERE COALESCE(summary, '') <> ''
          AND LENGTH(COALESCE(summary, '')) >= 40
        GROUP BY LOWER(REGEXP_REPLACE(TRIM(summary), '\\s+', ' ', 'g'))
        HAVING COUNT(*) >= 3
        ORDER BY repeat_count DESC, MIN(created_at) DESC
        LIMIT %s
        """,
        (max(1, min(int(limit or 20), 80)),),
        fetch=True,
    ) or []
    templates = fetch_message_templates(limit=400)
    existing_phrases = {(row.get("template_text") or "").strip().lower() for row in templates}

    suggestions = []
    for row in rows:
        sample = (row.get("sample_text") or "").strip()
        if not sample or sample.lower() in existing_phrases:
            continue
        words = re.findall(r"[a-z0-9]+", sample.lower())
        words = [word for word in words if len(word) >= 3][:3]
        shortcode_base = "_".join(words) if words else "message"
        suggestion_shortcode = f"/auto_{shortcode_base}"[:50]
        suggestions.append(
            {
                "sample_text": sample,
                "repeat_count": int(row.get("repeat_count") or 0),
                "suggested_shortcode": suggestion_shortcode,
                "category": "general",
            }
        )
    return suggestions


def _transaction_optional_values(transaction_id, column_names):
    safe_columns = []
    for column_name in column_names or []:
        normalized = (column_name or "").strip().lower()
        if not normalized:
            continue
        if not re.match(r"^[a-z_][a-z0-9_]*$", normalized):
            continue
        if _transaction_column_exists(normalized):
            safe_columns.append(normalized)
    if not safe_columns:
        return {}
    query = f"""
    SELECT {", ".join(safe_columns)}
    FROM transactions
    WHERE id = %s
    LIMIT 1
    """
    rows = execute_query(query, (int(transaction_id),), fetch=True) or []
    return rows[0] if rows else {}


def _format_template_date(value, fallback="____"):
    if isinstance(value, datetime):
        return value.strftime("%B %d, %Y")
    if isinstance(value, date):
        return value.strftime("%B %d, %Y")
    return fallback


def _format_template_time(value, fallback="____"):
    if isinstance(value, datetime):
        return value.strftime("%I:%M %p").lstrip("0")
    text = (value or "").strip() if isinstance(value, str) else ""
    if re.match(r"^\d{1,2}:\d{2}$", text):
        try:
            parsed = datetime.strptime(text, "%H:%M")
            return parsed.strftime("%I:%M %p").lstrip("0")
        except ValueError:
            pass
    if text:
        return text
    return fallback


def _upcoming_vendor_appointment(transaction_id, vendor_type):
    rows = execute_query(
        """
        SELECT vo.appointment_at, vo.vendor_name, vc.phone
        FROM vendor_outreach vo
        LEFT JOIN vendor_contacts vc ON vc.id = vo.vendor_id
        WHERE vo.transaction_id = %s
          AND LOWER(COALESCE(vo.vendor_type, '')) = %s
          AND vo.appointment_at IS NOT NULL
        ORDER BY vo.appointment_at ASC, vo.id ASC
        LIMIT 1
        """,
        (int(transaction_id), (vendor_type or "").strip().lower()),
        fetch=True,
    ) or []
    return rows[0] if rows else None


def calculate_cash_to_close(transaction_row):
    """Return best-effort cash-to-close estimate for template variables."""
    optional_values = _transaction_optional_values(
        transaction_row["id"],
        ["cash_to_close", "contract_price"],
    )
    if optional_values.get("cash_to_close") not in (None, ""):
        return float(optional_values.get("cash_to_close") or 0)
    contract_price = optional_values.get("contract_price")
    if contract_price not in (None, ""):
        return round(float(contract_price) * 0.03, 2)
    return 0.0


def build_message_template_context(transaction_id):
    """Build context dictionary for template expansion."""
    transaction = get_transaction(transaction_id)
    optional_values = _transaction_optional_values(
        transaction_id,
        [
            "closing_time",
            "cash_to_close",
            "earnest_amount",
            "option_fee",
            "title_officer_name",
            "title_officer_phone",
            "walkthrough_date",
            "walkthrough_time",
            "possession_time",
            "repair_items",
            "repair_completion_date",
            "new_closing_date",
            "earnest_disposition",
            "appraised_value",
            "loan_status",
            "delay_reason",
            "escalation_summary",
            "payment_link",
            "payment_amount",
            "payment_due_date",
            "repair_request_due_date",
        ],
    )
    inspection = _upcoming_vendor_appointment(transaction_id, "inspector")
    appraisal = _upcoming_vendor_appointment(transaction_id, "appraiser")
    calendar_preferences = fetch_transaction_calendar_preferences(transaction_id) or {}
    client_portal = ensure_primary_portal_link(transaction_id)
    review_link_rows = execute_query(
        """
        SELECT access_token
        FROM agent_review_requests
        WHERE transaction_id = %s
        ORDER BY requested_at DESC, id DESC
        LIMIT 1
        """,
        (int(transaction_id),),
        fetch=True,
    ) or []
    review_link = f"{app_base_url()}/review/{review_link_rows[0]['access_token']}" if review_link_rows else ""

    missing_document_types = []
    docs_payload = _uploaded_documents_for_completion(transaction_id, transaction_row=transaction)
    for doc_type in sorted(REQUIRED_DOCUMENT_TYPES):
        if doc_type not in docs_payload["uploaded_types"]:
            missing_document_types.append(document_type_label(doc_type))

    closing_breakdown = calculate_payment_breakdown(transaction, "closing")
    cash_to_close = calculate_cash_to_close(transaction)
    context = {
        "AGENT_NAME": transaction.get("agent_name") or "Agent",
        "BUYER_NAME": transaction.get("buyer_name") or "Buyer",
        "SELLER_NAME": transaction.get("seller_name") or "Seller",
        "PROPERTY_ADDRESS": transaction.get("property_address") or "Property",
        "TRANSACTION_ID": str(transaction["id"]),
        "CLOSING_DATE": _format_template_date(transaction.get("closing_date")),
        "CLOSING_TIME": _format_template_time(
            optional_values.get("closing_time") or calendar_preferences.get("closing_time")
        ),
        "TITLE_COMPANY": transaction.get("title_company") or "title company",
        "TITLE_CONTACT": optional_values.get("title_officer_name") or transaction.get("title_company") or "Title contact",
        "TITLE_PHONE": optional_values.get("title_officer_phone") or "____",
        "CASH_TO_CLOSE": f"{cash_to_close:,.2f}" if cash_to_close > 0 else "____",
        "EARNEST_AMOUNT": (
            f"{float(optional_values.get('earnest_amount') or 0):,.2f}"
            if optional_values.get("earnest_amount") not in (None, "")
            else "____"
        ),
        "EARNEST_DUE_DATE": _format_template_date(transaction.get("earnest_due_date")),
        "OPTION_FEE": (
            f"{float(optional_values.get('option_fee') or 0):,.2f}"
            if optional_values.get("option_fee") not in (None, "")
            else "____"
        ),
        "OPTION_DUE_DATE": _format_template_date(transaction.get("option_fee_due_date")),
        "FINANCING_APPROVAL_DATE": _format_template_date(transaction.get("financing_approval_date")),
        "HOA_DUE_DATE": _format_template_date(transaction.get("hoa_docs_due_date")),
        "SURVEY_DUE_DATE": _format_template_date(transaction.get("survey_due_date")),
        "WALKTHROUGH_DATE": _format_template_date(optional_values.get("walkthrough_date")),
        "WALKTHROUGH_TIME": _format_template_time(optional_values.get("walkthrough_time")),
        "POSSESSION_TIME": _format_template_time(optional_values.get("possession_time"), fallback="at funding"),
        "REPAIR_ITEMS": optional_values.get("repair_items") or "____",
        "REPAIR_COMPLETION_DATE": _format_template_date(optional_values.get("repair_completion_date")),
        "REPAIR_REQUEST_DUE_DATE": _format_template_date(optional_values.get("repair_request_due_date")),
        "NEW_CLOSING_DATE": _format_template_date(optional_values.get("new_closing_date")),
        "EARNEST_DISPOSITION": optional_values.get("earnest_disposition") or "____",
        "APPRAISED_VALUE": (
            f"{float(optional_values.get('appraised_value') or 0):,.2f}"
            if optional_values.get("appraised_value") not in (None, "")
            else "____"
        ),
        "LOAN_STATUS": optional_values.get("loan_status") or "Pending update",
        "DELAY_REASON": optional_values.get("delay_reason") or "logistics coordination",
        "ESCALATION_SUMMARY": optional_values.get("escalation_summary") or "action required",
        "PAYMENT_LINK": optional_values.get("payment_link") or "____",
        "PAYMENT_AMOUNT": (
            f"{float(optional_values.get('payment_amount') or 0):,.2f}"
            if optional_values.get("payment_amount") not in (None, "")
            else f"{float(closing_breakdown['amount']):,.2f}"
        ),
        "PAYMENT_DUE_DATE": _format_template_date(optional_values.get("payment_due_date")),
        "STATUS_SUMMARY": f"Status is {(transaction.get('status') or 'ACTIVE').title()}",
        "NEXT_DEADLINE": "TBD",
        "MISSING_DOCUMENTS": ", ".join(missing_document_types) if missing_document_types else "None",
        "PORTAL_LINK": client_portal or "____",
        "REVIEW_LINK": review_link or "____",
        "MARGARET_PHONE": normalize_phone(os.getenv("MARGARET_PHONE") or "") or "____",
    }

    if inspection and inspection.get("appointment_at"):
        context["INSPECTION_DATE"] = _format_template_date(inspection.get("appointment_at"))
        context["INSPECTION_TIME"] = _format_template_time(inspection.get("appointment_at"))
        context["INSPECTOR_NAME"] = inspection.get("vendor_name") or "Inspector"
        context["INSPECTOR_PHONE"] = inspection.get("phone") or "____"
    else:
        context["INSPECTION_DATE"] = "____"
        context["INSPECTION_TIME"] = "____"
        context["INSPECTOR_NAME"] = "____"
        context["INSPECTOR_PHONE"] = "____"

    if appraisal and appraisal.get("appointment_at"):
        context["APPRAISAL_DATE"] = _format_template_date(appraisal.get("appointment_at"))
        context["APPRAISAL_TIME"] = _format_template_time(appraisal.get("appointment_at"))
        context["APPRAISER_NAME"] = appraisal.get("vendor_name") or "Appraiser"
        context["APPRAISER_PHONE"] = appraisal.get("phone") or "____"
    else:
        context["APPRAISAL_DATE"] = "____"
        context["APPRAISAL_TIME"] = "____"
        context["APPRAISER_NAME"] = "____"
        context["APPRAISER_PHONE"] = "____"

    next_deadline_rows = execute_query(
        """
        SELECT deadline_type, deadline_date
        FROM deadlines
        WHERE transaction_id = %s
          AND completed = FALSE
          AND deadline_date >= CURRENT_DATE
        ORDER BY deadline_date ASC, id ASC
        LIMIT 1
        """,
        (int(transaction_id),),
        fetch=True,
    ) or []
    if next_deadline_rows:
        context["NEXT_DEADLINE"] = (
            f"{(next_deadline_rows[0]['deadline_type'] or '').replace('_', ' ').title()} "
            f"({ _format_template_date(next_deadline_rows[0].get('deadline_date')) })"
        )
    return context


def expand_message_template_text(template_text, context):
    """Expand {{VARS}} using context and report missing variable names."""
    template_payload = template_text or ""
    variable_names = sorted(set(re.findall(r"\{\{([A-Z0-9_]+)\}\}", template_payload)))
    missing = [name for name in variable_names if (context.get(name) in (None, "", "____"))]
    expanded = template_payload
    for name in variable_names:
        value = context.get(name)
        expanded = expanded.replace(f"{{{{{name}}}}}", str(value if value not in (None, "") else "____"))
    expanded = re.sub(r"\{\{[A-Z0-9_]+\}\}", "____", expanded)
    return expanded, missing


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
        try:
            notify_result = notify_portal_users_milestone(
                transaction_id=transaction_id,
                milestone_key=f"inspection_complete_{date.today().isoformat()}",
                message_template="✅ Inspection complete! View report in your portal: {link}",
            )
            if notify_result.get("sent_sms") or notify_result.get("sent_email"):
                summary_bits.append(
                    "inspection_portal_notifications="
                    f"{int(notify_result.get('sent_sms') or 0)}sms/"
                    f"{int(notify_result.get('sent_email') or 0)}email"
                )
        except Exception as exc:
            print(f"Portal milestone notify error (inspection report): {exc}")

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


def ensure_party_portal_tables():
    """Ensure self-service party portal access + analytics tables exist."""
    execute_query(
        """
        CREATE TABLE IF NOT EXISTS party_portal_access (
            id SERIAL PRIMARY KEY,
            transaction_id INT REFERENCES transactions(id) ON DELETE CASCADE,
            party_type VARCHAR(20) NOT NULL,
            access_token UUID UNIQUE NOT NULL,
            email VARCHAR(255),
            is_active BOOLEAN DEFAULT TRUE,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            last_accessed_at TIMESTAMP,
            expires_at TIMESTAMP
        )
        """
    )
    execute_query(
        """
        CREATE UNIQUE INDEX IF NOT EXISTS idx_party_portal_access_txn_party
        ON party_portal_access(transaction_id, party_type)
        """
    )
    execute_query(
        """
        CREATE INDEX IF NOT EXISTS idx_party_portal_access_expiry
        ON party_portal_access(is_active, expires_at, last_accessed_at DESC)
        """
    )
    execute_query(
        """
        CREATE TABLE IF NOT EXISTS party_portal_access_log (
            id SERIAL PRIMARY KEY,
            portal_access_id INT REFERENCES party_portal_access(id) ON DELETE SET NULL,
            transaction_id INT REFERENCES transactions(id) ON DELETE CASCADE,
            party_type VARCHAR(20),
            access_token_hash VARCHAR(64),
            event_type VARCHAR(40) NOT NULL,
            section_name VARCHAR(80),
            document_id INT REFERENCES documents(id) ON DELETE SET NULL,
            success BOOLEAN DEFAULT TRUE,
            ip_address VARCHAR(64),
            user_agent VARCHAR(255),
            details JSONB DEFAULT '{}'::jsonb,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
        """
    )
    execute_query(
        """
        CREATE INDEX IF NOT EXISTS idx_party_portal_access_log_txn
        ON party_portal_access_log(transaction_id, created_at DESC, event_type)
        """
    )
    execute_query(
        """
        CREATE INDEX IF NOT EXISTS idx_party_portal_access_log_token
        ON party_portal_access_log(access_token_hash, ip_address, created_at DESC)
        """
    )
    execute_query(
        """
        CREATE TABLE IF NOT EXISTS party_portal_notifications_log (
            id SERIAL PRIMARY KEY,
            transaction_id INT REFERENCES transactions(id) ON DELETE CASCADE,
            party_type VARCHAR(20) NOT NULL,
            milestone_key VARCHAR(140) NOT NULL,
            channel VARCHAR(20) NOT NULL,
            recipient VARCHAR(255),
            sent_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            UNIQUE (transaction_id, party_type, milestone_key, channel)
        )
        """
    )
    execute_query(
        """
        CREATE INDEX IF NOT EXISTS idx_party_portal_notifications_txn
        ON party_portal_notifications_log(transaction_id, sent_at DESC)
        """
    )


def party_portal_base_url():
    """Resolve base URL used in party portal links."""
    configured = (os.getenv("CLIENT_PORTAL_BASE_URL") or os.getenv("APP_BASE_URL") or "").strip()
    if configured:
        return configured.rstrip("/")
    if has_request_context():
        return (request.url_root or "http://localhost:5000").rstrip("/")
    return "http://localhost:5000"


def build_party_portal_url(access_token):
    """Build external link for party portal token."""
    return f"{party_portal_base_url()}/portal/{access_token}"


def _portal_token_hash(access_token):
    token = (access_token or "").strip()
    return hashlib.sha256(token.encode("utf-8")).hexdigest() if token else ""


def _portal_expiration_for_transaction(transaction_id):
    """Calculate default token expiry (closing + 30 days by default)."""
    grace_days_raw = (os.getenv("PORTAL_TOKEN_GRACE_DAYS") or "30").strip()
    try:
        grace_days = max(7, min(int(grace_days_raw), 365))
    except (TypeError, ValueError):
        grace_days = 30

    rows = execute_query(
        """
        SELECT closing_date, completed_at, status
        FROM transactions
        WHERE id = %s
        LIMIT 1
        """,
        (int(transaction_id),),
        fetch=True,
    ) or []
    if not rows:
        return datetime.now() + timedelta(days=365)

    row = rows[0]
    closing_date = row.get("closing_date")
    if closing_date:
        return datetime.combine(closing_date + timedelta(days=grace_days), datetime.max.time()).replace(microsecond=0)
    completed_at = row.get("completed_at")
    if completed_at:
        return completed_at + timedelta(days=grace_days)
    return datetime.now() + timedelta(days=365)


def _fallback_client_access_email(transaction_id, party_type):
    if party_type not in {"buyer", "seller"}:
        return ""
    rows = execute_query(
        """
        SELECT email
        FROM client_access
        WHERE transaction_id = %s
          AND client_type = %s
        LIMIT 1
        """,
        (int(transaction_id), party_type),
        fetch=True,
    ) or []
    if not rows:
        return ""
    return normalize_email(rows[0].get("email") or "")


def create_portal_access(transaction_id, party_type, access_token=None, email=None):
    """Create/update one party portal token row."""
    normalized_party = (party_type or "").strip().lower()
    if normalized_party not in PARTY_PORTAL_TYPES:
        raise ValueError("Unsupported party type")
    ensure_party_portal_tables()
    token = (access_token or str(uuid4())).strip()
    safe_email = normalize_email(email or "")
    if safe_email and not is_email_valid(safe_email):
        safe_email = ""
    if not safe_email:
        safe_email = _fallback_client_access_email(transaction_id, normalized_party)
    expires_at = _portal_expiration_for_transaction(transaction_id)

    rows = execute_query(
        """
        INSERT INTO party_portal_access (
            transaction_id, party_type, access_token, email, is_active, created_at, last_accessed_at, expires_at
        )
        VALUES (%s, %s, %s::uuid, %s, TRUE, CURRENT_TIMESTAMP, NULL, %s)
        ON CONFLICT (transaction_id, party_type)
        DO UPDATE SET
            access_token = EXCLUDED.access_token,
            email = CASE
                WHEN COALESCE(EXCLUDED.email, '') <> '' THEN EXCLUDED.email
                ELSE party_portal_access.email
            END,
            is_active = TRUE,
            expires_at = EXCLUDED.expires_at
        RETURNING
            id, transaction_id, party_type, access_token::text AS access_token,
            email, is_active, created_at, last_accessed_at, expires_at
        """,
        (int(transaction_id), normalized_party, token, safe_email or None, expires_at),
        fetch=True,
    ) or []
    if not rows:
        return None
    row = rows[0]
    row["portal_url"] = build_party_portal_url(row["access_token"])
    return row


def list_party_portal_access(transaction_id):
    """List all party portal rows for one transaction."""
    ensure_party_portal_tables()
    rows = execute_query(
        """
        SELECT
            id, transaction_id, party_type, access_token::text AS access_token, email,
            is_active, created_at, last_accessed_at, expires_at
        FROM party_portal_access
        WHERE transaction_id = %s
        ORDER BY party_type ASC
        """,
        (int(transaction_id),),
        fetch=True,
    ) or []
    for row in rows:
        row["portal_url"] = build_party_portal_url(row["access_token"])
    return rows


def get_portal_access(access_token, touch=True):
    """Resolve one party portal token to transaction + party context."""
    ensure_party_portal_tables()
    token = (access_token or "").strip()
    if not token:
        return None
    rows = execute_query(
        """
        SELECT
            ppa.id, ppa.transaction_id, ppa.party_type, ppa.access_token::text AS access_token,
            ppa.email, ppa.is_active, ppa.created_at, ppa.last_accessed_at, ppa.expires_at,
            t.property_address, t.status, t.closing_date, t.completed_at,
            t.agent_name, t.agent_phone, t.agent_email,
            t.buyer_name, t.buyer_phone, t.seller_name, t.seller_phone,
            t.contract_s3_key
        FROM party_portal_access ppa
        JOIN transactions t ON t.id = ppa.transaction_id
        WHERE ppa.access_token::text = %s
        LIMIT 1
        """,
        (token,),
        fetch=True,
    ) or []
    if not rows:
        return None
    row = rows[0]
    if not row.get("is_active"):
        return None
    expires_at = row.get("expires_at")
    if expires_at and isinstance(expires_at, datetime) and expires_at < datetime.now():
        execute_query("UPDATE party_portal_access SET is_active = FALSE WHERE id = %s", (row["id"],))
        return None
    if touch:
        execute_query(
            """
            UPDATE party_portal_access
            SET last_accessed_at = CURRENT_TIMESTAMP
            WHERE id = %s
            """,
            (int(row["id"]),),
        )
        row["last_accessed_at"] = datetime.now()
    row["portal_url"] = build_party_portal_url(row["access_token"])
    return row


def log_portal_access(
    portal_access_id=None,
    transaction_id=None,
    party_type="",
    access_token="",
    event_type="view",
    section_name="",
    document_id=None,
    success=True,
    details=None,
):
    """Persist portal access/analytics events."""
    ensure_party_portal_tables()
    execute_query(
        """
        INSERT INTO party_portal_access_log (
            portal_access_id, transaction_id, party_type, access_token_hash, event_type,
            section_name, document_id, success, ip_address, user_agent, details, created_at
        )
        VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s::jsonb, CURRENT_TIMESTAMP)
        """,
        (
            int(portal_access_id) if portal_access_id else None,
            int(transaction_id) if transaction_id else None,
            (party_type or "").strip().lower() or None,
            _portal_token_hash(access_token),
            (event_type or "view").strip().lower()[:40],
            (section_name or "").strip().lower()[:80] or None,
            int(document_id) if document_id else None,
            bool(success),
            (request.remote_addr or "")[:64] if has_request_context() else "",
            (request.headers.get("User-Agent") or "")[:255] if has_request_context() else "",
            json.dumps(details or {}, default=str),
        ),
    )


def _portal_rate_limited(access_token, ip_address):
    """Simple DB-backed rate limit for portal abuse prevention."""
    ensure_party_portal_tables()
    token_hash = _portal_token_hash(access_token)
    if not token_hash:
        return False
    window_raw = (os.getenv("PORTAL_RATE_LIMIT_WINDOW_MINUTES") or "5").strip()
    max_raw = (os.getenv("PORTAL_RATE_LIMIT_MAX_REQUESTS") or "80").strip()
    try:
        window_minutes = max(1, min(int(window_raw), 60))
    except (TypeError, ValueError):
        window_minutes = 5
    try:
        max_requests = max(20, min(int(max_raw), 500))
    except (TypeError, ValueError):
        max_requests = 80
    rows = execute_query(
        """
        SELECT COUNT(*) AS total
        FROM party_portal_access_log
        WHERE access_token_hash = %s
          AND ip_address = %s
          AND created_at >= (CURRENT_TIMESTAMP - (%s || ' minutes')::interval)
          AND event_type IN ('view', 'section_view', 'document_download', 'upload')
        """,
        (token_hash, (ip_address or "")[:64], int(window_minutes)),
        fetch=True,
    ) or []
    recent_count = int((rows[0] or {}).get("total") or 0) if rows else 0
    return recent_count >= max_requests


def _portal_party_phone(transaction, party_type):
    role = (party_type or "").strip().lower()
    if role == "buyer":
        return normalize_phone(transaction.get("buyer_phone") or "")
    if role == "seller":
        return normalize_phone(transaction.get("seller_phone") or "")
    return normalize_phone(transaction.get("agent_phone") or "")


def _portal_party_email(transaction, party_type, fallback_email=""):
    role = (party_type or "").strip().lower()
    if role == "agent":
        return normalize_email((fallback_email or transaction.get("agent_email") or ""))
    return normalize_email(fallback_email or "")


def send_portal_links(transaction_id, portal_tokens):
    """Send buyer/seller/agent portal links by available channels."""
    transaction = get_transaction_or_none(transaction_id)
    if not transaction:
        return {"sent_sms": 0, "sent_email": 0}
    sent_sms = 0
    sent_email = 0
    access_map = {row["party_type"]: row for row in list_party_portal_access(transaction_id)}

    for party_type, token in (portal_tokens or {}).items():
        normalized_party = (party_type or "").strip().lower()
        if normalized_party not in PARTY_PORTAL_TYPES:
            continue
        access_row = access_map.get(normalized_party) or {}
        link_url = build_party_portal_url(token)
        recipient_phone = _portal_party_phone(transaction, normalized_party)
        recipient_email = _portal_party_email(transaction, normalized_party, access_row.get("email") or "")
        party_label = normalized_party.title()
        sms_message = f"Track your transaction in your secure portal: {link_url}"

        if recipient_phone:
            send_sms_async(recipient_phone, sms_message)
            sent_sms += 1
            execute_query(
                """
                INSERT INTO communications (transaction_id, communication_type, contact_party, contact_name, summary, outcome)
                VALUES (%s, 'text', %s, %s, %s, %s)
                """,
                (
                    int(transaction_id),
                    normalized_party,
                    party_label,
                    "Party portal link sent",
                    f"channel=sms to={recipient_phone}",
                ),
            )

        if recipient_email and is_email_valid(recipient_email):
            message_id = send_email(
                to=recipient_email,
                template="emails/client_portal_access.html",
                data={
                    "subject": f"Maverick Portal Access - {transaction.get('property_address')}",
                    "property_address": transaction.get("property_address"),
                    "client_type": party_label,
                    "portal_url": link_url,
                    "closing_date_label": (
                        transaction["closing_date"].strftime("%b %d, %Y") if transaction.get("closing_date") else "TBD"
                    ),
                },
            )
            execute_query(
                """
                INSERT INTO communications (transaction_id, communication_type, contact_party, contact_name, summary, outcome)
                VALUES (%s, 'email', %s, %s, %s, %s)
                """,
                (
                    int(transaction_id),
                    normalized_party,
                    party_label,
                    "Party portal link email sent" if message_id else "Party portal link email failed",
                    f"to={recipient_email} message_id={message_id or 'failed'}",
                ),
            )
            if message_id:
                sent_email += 1
    return {"sent_sms": sent_sms, "sent_email": sent_email}


def calculate_completion_percentage(transaction_id):
    """Calculate transaction completion percentage by deadlines completed."""
    rows = execute_query(
        """
        SELECT
            COUNT(*) AS total_count,
            COUNT(*) FILTER (WHERE completed = TRUE) AS completed_count
        FROM deadlines
        WHERE transaction_id = %s
        """,
        (int(transaction_id),),
        fetch=True,
    ) or []
    if not rows:
        return 0
    total_count = int(rows[0].get("total_count") or 0)
    completed_count = int(rows[0].get("completed_count") or 0)
    if total_count <= 0:
        return 0
    return int(round((completed_count / total_count) * 100))


def get_transaction_timeline_for_portal(transaction_id, party_type):
    """Build portal-friendly timeline rows for a transaction."""
    _ = party_type  # kept for future party-specific timeline filtering
    rows = execute_query(
        """
        SELECT id, deadline_type, deadline_date, description, completed
        FROM deadlines
        WHERE transaction_id = %s
        ORDER BY deadline_date ASC NULLS LAST, id ASC
        """,
        (int(transaction_id),),
        fetch=True,
    ) or []
    timeline = []
    today = date.today()
    for row in rows:
        due_date = row.get("deadline_date")
        if row.get("completed"):
            status = "complete"
        elif due_date and due_date <= (today + timedelta(days=2)):
            status = "in_progress"
        else:
            status = "pending"
        timeline.append(
            {
                "id": row.get("id"),
                "title": (row.get("description") or row.get("deadline_type") or "").replace("_", " ").title(),
                "date": due_date,
                "date_label": format_date_label(due_date),
                "status": status,
            }
        )
    return timeline


def _portal_document_rows(transaction):
    tx_id = int(transaction["id"])
    rows = execute_query(
        """
        SELECT DISTINCT ON (document_type)
               id, transaction_id, document_type, filename, s3_key, uploaded_at
        FROM documents
        WHERE transaction_id = %s
        ORDER BY document_type, uploaded_at DESC, id DESC
        """,
        (tx_id,),
        fetch=True,
    ) or []
    payload = list(rows)
    has_contract_doc = any((row.get("document_type") or "").lower() == "contract" for row in payload)
    if transaction.get("contract_s3_key") and not has_contract_doc:
        payload.append(
            {
                "id": 0,
                "transaction_id": tx_id,
                "document_type": "contract",
                "filename": transaction.get("contract_pdf_url") or "contract.pdf",
                "s3_key": transaction.get("contract_s3_key"),
                "uploaded_at": transaction.get("created_at"),
            }
        )
    return payload


def _party_document_whitelist(party_type, available_rows):
    role = (party_type or "").strip().lower()
    if role == "agent":
        return sorted({(row.get("document_type") or "").lower() for row in available_rows if row.get("document_type")})
    allowed = set(PARTY_PORTAL_DOCUMENTS_BY_TYPE.get(role, set()))
    return sorted([doc_type for doc_type in allowed if doc_type not in PORTAL_SENSITIVE_DOCUMENT_TYPES])


def _documents_for_portal_party(transaction, party_type, access_token):
    available_rows = _portal_document_rows(transaction)
    whitelist = _party_document_whitelist(party_type, available_rows)
    latest_by_type = {}
    for row in available_rows:
        doc_type = (row.get("document_type") or "").lower()
        if not doc_type:
            continue
        if doc_type in PORTAL_SENSITIVE_DOCUMENT_TYPES and party_type in {"buyer", "seller"}:
            continue
        latest_by_type[doc_type] = row

    documents = []
    for doc_type in whitelist:
        row = latest_by_type.get(doc_type)
        if row:
            documents.append(
                {
                    "id": int(row.get("id") or 0),
                    "document_type": doc_type,
                    "name": document_type_label(doc_type),
                    "status": "available",
                    "available": True,
                    "uploaded_at": row.get("uploaded_at"),
                    "view_url": url_for(
                        "party_portal_document",
                        document_id=int(row.get("id") or 0),
                        token=access_token,
                    ),
                }
            )
        else:
            documents.append(
                {
                    "id": None,
                    "document_type": doc_type,
                    "name": document_type_label(doc_type),
                    "status": "pending",
                    "available": False,
                    "uploaded_at": None,
                    "view_url": "",
                }
            )
    if party_type == "agent":
        documents.sort(key=lambda row: (0 if row.get("available") else 1, row.get("name") or ""))
    return documents


def get_documents_for_buyer(transaction, access_token):
    return _documents_for_portal_party(transaction, "buyer", access_token)


def get_documents_for_seller(transaction, access_token):
    return _documents_for_portal_party(transaction, "seller", access_token)


def get_all_documents(transaction, access_token):
    return _documents_for_portal_party(transaction, "agent", access_token)


def _portal_todo_payload(description, due_date=None, source="task"):
    return {
        "description": (description or "").strip(),
        "due_date": due_date,
        "due_label": format_date_label(due_date) if due_date else "",
        "source": source,
    }


def get_buyer_action_items(transaction_id):
    items = []
    task_rows = execute_query(
        """
        SELECT task_description, due_date
        FROM tasks
        WHERE transaction_id = %s
          AND completed = FALSE
          AND COALESCE(status, 'pending') <> 'completed'
          AND LOWER(COALESCE(task_description, '')) SIMILAR TO %s
        ORDER BY due_date ASC NULLS LAST, id ASC
        LIMIT 10
        """,
        (int(transaction_id), "%(buyer|inspection|insurance|loan|document|sign)%"),
        fetch=True,
    ) or []
    for row in task_rows:
        items.append(_portal_todo_payload(row.get("task_description"), row.get("due_date"), source="task"))

    request_rows = execute_query(
        """
        SELECT document_type, updated_at
        FROM document_requests
        WHERE transaction_id = %s
          AND requested_from = 'buyer'
          AND status <> 'received'
        ORDER BY updated_at DESC, id DESC
        LIMIT 8
        """,
        (int(transaction_id),),
        fetch=True,
    ) or []
    for row in request_rows:
        items.append(
            _portal_todo_payload(
                f"Upload {document_type_label(row.get('document_type'))}",
                due_date=None,
                source="document_request",
            )
        )
    return items[:12]


def get_seller_action_items(transaction_id):
    items = []
    task_rows = execute_query(
        """
        SELECT task_description, due_date
        FROM tasks
        WHERE transaction_id = %s
          AND completed = FALSE
          AND COALESCE(status, 'pending') <> 'completed'
          AND LOWER(COALESCE(task_description, '')) SIMILAR TO %s
        ORDER BY due_date ASC NULLS LAST, id ASC
        LIMIT 10
        """,
        (int(transaction_id), "%(seller|disclosure|repair|document|sign)%"),
        fetch=True,
    ) or []
    for row in task_rows:
        items.append(_portal_todo_payload(row.get("task_description"), row.get("due_date"), source="task"))

    request_rows = execute_query(
        """
        SELECT document_type, updated_at
        FROM document_requests
        WHERE transaction_id = %s
          AND requested_from = 'seller'
          AND status <> 'received'
        ORDER BY updated_at DESC, id DESC
        LIMIT 8
        """,
        (int(transaction_id),),
        fetch=True,
    ) or []
    for row in request_rows:
        items.append(
            _portal_todo_payload(
                f"Upload {document_type_label(row.get('document_type'))}",
                due_date=None,
                source="document_request",
            )
        )
    return items[:12]


def get_agent_action_items(transaction_id):
    rows = execute_query(
        """
        SELECT task_description, due_date
        FROM tasks
        WHERE transaction_id = %s
          AND completed = FALSE
          AND COALESCE(status, 'pending') <> 'completed'
        ORDER BY COALESCE(due_date, CURRENT_DATE + INTERVAL '365 days') ASC, priority DESC, id ASC
        LIMIT 15
        """,
        (int(transaction_id),),
        fetch=True,
    ) or []
    return [_portal_todo_payload(row.get("task_description"), row.get("due_date"), source="task") for row in rows]


def get_all_tasks_for_portal(transaction_id):
    rows = execute_query(
        """
        SELECT id, task_description, task_category, due_date, priority, completed
        FROM tasks
        WHERE transaction_id = %s
        ORDER BY completed ASC, COALESCE(due_date, CURRENT_DATE + INTERVAL '365 days') ASC, id ASC
        LIMIT 80
        """,
        (int(transaction_id),),
        fetch=True,
    ) or []
    for row in rows:
        row["due_label"] = format_date_label(row.get("due_date"))
        row["status"] = "complete" if row.get("completed") else "pending"
    return rows


def get_recent_activity(transaction_id, limit=5):
    rows = execute_query(
        """
        SELECT communication_type, contact_party, summary, outcome, created_at
        FROM communications
        WHERE transaction_id = %s
        ORDER BY created_at DESC, id DESC
        LIMIT %s
        """,
        (int(transaction_id), max(1, min(int(limit or 5), 20))),
        fetch=True,
    ) or []
    payload = []
    for row in rows:
        description = (row.get("summary") or "").strip()
        if row.get("outcome"):
            description = f"{description} ({row['outcome']})"
        payload.append(
            {
                "description": description[:600],
                "type": row.get("communication_type") or "update",
                "created_at": row.get("created_at"),
                "timeago": format_time_ago(row.get("created_at")),
            }
        )
    return payload


def build_portal_data(transaction, party_type, access_token):
    """
    Build a personalized portal payload for buyer/seller/agent.
    Keeps sensitive financial data out of this public-facing view.
    """
    closing_date = transaction.get("closing_date")
    days_to_closing = (closing_date - date.today()).days if closing_date else None
    data = {
        "property_address": transaction.get("property_address"),
        "closing_date": closing_date,
        "closing_date_label": format_date_label(closing_date),
        "days_to_closing": days_to_closing,
        "days_to_closing_label": (
            f"{days_to_closing} days" if isinstance(days_to_closing, int) else "Date TBD"
        ),
        "progress_percent": calculate_completion_percentage(transaction["id"]),
    }
    data["timeline"] = get_transaction_timeline_for_portal(transaction["id"], party_type)

    if party_type == "buyer":
        data["documents"] = get_documents_for_buyer(transaction, access_token)
        data["your_todo"] = get_buyer_action_items(transaction["id"])
    elif party_type == "seller":
        data["documents"] = get_documents_for_seller(transaction, access_token)
        data["your_todo"] = get_seller_action_items(transaction["id"])
    else:
        data["documents"] = get_all_documents(transaction, access_token)
        data["your_todo"] = get_agent_action_items(transaction["id"])
        data["can_upload"] = True
        data["all_tasks"] = get_all_tasks_for_portal(transaction["id"])

    data["contacts"] = {
        "coordinator": {
            "name": "Margaret",
            "phone": normalize_phone(os.getenv("MARGARET_PHONE") or ""),
            "email": normalize_email(os.getenv("MARGARET_EMAIL") or ""),
        },
        "agent": {
            "name": transaction.get("agent_name") or "Agent",
            "phone": normalize_phone(transaction.get("agent_phone") or ""),
            "email": normalize_email(transaction.get("agent_email") or ""),
        },
    }
    data["recent_updates"] = get_recent_activity(transaction["id"], limit=5)
    return data


def fetch_party_portal_analytics(transaction_id, lookback_days=90):
    """Aggregate portal analytics used for support-time and adoption tracking."""
    ensure_party_portal_tables()
    start_ts = datetime.now() - timedelta(days=max(7, min(int(lookback_days or 90), 365)))
    event_rows = execute_query(
        """
        SELECT event_type, section_name, COUNT(*) AS total
        FROM party_portal_access_log
        WHERE transaction_id = %s
          AND created_at >= %s
        GROUP BY event_type, section_name
        """,
        (int(transaction_id), start_ts),
        fetch=True,
    ) or []

    views = 0
    document_downloads = 0
    uploads = 0
    section_counts = {}
    for row in event_rows:
        event_type = (row.get("event_type") or "").strip().lower()
        count = int(row.get("total") or 0)
        if event_type == "view":
            views += count
        elif event_type == "document_download":
            document_downloads += count
        elif event_type == "upload":
            uploads += count
        elif event_type == "section_view":
            section_name = (row.get("section_name") or "other").strip().lower()
            section_counts[section_name] = section_counts.get(section_name, 0) + count

    question_rows = execute_query(
        """
        SELECT COUNT(*) AS total
        FROM communications
        WHERE transaction_id = %s
          AND communication_type = 'text'
          AND created_at >= %s
          AND (
              COALESCE(summary, '') LIKE %s
              OR COALESCE(outcome, '') LIKE %s
          )
        """,
        (int(transaction_id), start_ts, "%?%", "%?%"),
        fetch=True,
    ) or []
    text_questions = int((question_rows[0] or {}).get("total") or 0) if question_rows else 0
    estimated_support_minutes_saved = max(0, (views * 2) + (document_downloads * 3) + (uploads * 4) - (text_questions * 4))
    return {
        "views": views,
        "document_downloads": document_downloads,
        "uploads": uploads,
        "most_viewed_sections": sorted(
            [{"section": key, "count": value} for key, value in section_counts.items()],
            key=lambda item: item["count"],
            reverse=True,
        )[:5],
        "text_questions_after_portal": text_questions,
        "estimated_support_minutes_saved": estimated_support_minutes_saved,
        "estimated_support_hours_saved": round(estimated_support_minutes_saved / 60.0, 1),
    }


def _portal_notification_already_sent(transaction_id, party_type, milestone_key, channel):
    rows = execute_query(
        """
        SELECT id
        FROM party_portal_notifications_log
        WHERE transaction_id = %s
          AND party_type = %s
          AND milestone_key = %s
          AND channel = %s
        LIMIT 1
        """,
        (int(transaction_id), (party_type or "").strip().lower(), (milestone_key or "").strip(), (channel or "").strip()),
        fetch=True,
    ) or []
    return bool(rows)


def _log_portal_notification(transaction_id, party_type, milestone_key, channel, recipient):
    execute_query(
        """
        INSERT INTO party_portal_notifications_log (
            transaction_id, party_type, milestone_key, channel, recipient, sent_at
        )
        VALUES (%s, %s, %s, %s, %s, CURRENT_TIMESTAMP)
        ON CONFLICT (transaction_id, party_type, milestone_key, channel)
        DO NOTHING
        """,
        (
            int(transaction_id),
            (party_type or "").strip().lower(),
            (milestone_key or "").strip()[:140],
            (channel or "").strip()[:20],
            (recipient or "").strip()[:255] or None,
        ),
    )


def notify_portal_users_milestone(transaction_id, milestone_key, message_template):
    """Send milestone updates to all active portal users for a transaction."""
    ensure_party_portal_tables()
    transaction = get_transaction_or_none(transaction_id)
    if not transaction:
        return {"sent_sms": 0, "sent_email": 0}
    access_rows = execute_query(
        """
        SELECT id, transaction_id, party_type, access_token::text AS access_token, email, expires_at, is_active
        FROM party_portal_access
        WHERE transaction_id = %s
          AND is_active = TRUE
          AND (expires_at IS NULL OR expires_at >= CURRENT_TIMESTAMP)
        ORDER BY party_type ASC
        """,
        (int(transaction_id),),
        fetch=True,
    ) or []
    sent_sms = 0
    sent_email = 0
    for row in access_rows:
        party_type = (row.get("party_type") or "").lower()
        link = build_party_portal_url(row.get("access_token"))
        message = (message_template or "").replace("{link}", link)
        recipient_phone = _portal_party_phone(transaction, party_type)
        recipient_email = _portal_party_email(transaction, party_type, row.get("email") or "")
        party_label = party_type.title()

        if recipient_phone and not _portal_notification_already_sent(transaction_id, party_type, milestone_key, "sms"):
            send_sms_async(recipient_phone, message[:500])
            _log_portal_notification(transaction_id, party_type, milestone_key, "sms", recipient_phone)
            sent_sms += 1
            log_portal_access(
                portal_access_id=row.get("id"),
                transaction_id=transaction_id,
                party_type=party_type,
                access_token=row.get("access_token"),
                event_type="notification_sent",
                section_name=milestone_key,
                success=True,
                details={"channel": "sms"},
            )

        if recipient_email and is_email_valid(recipient_email) and not _portal_notification_already_sent(
            transaction_id, party_type, milestone_key, "email"
        ):
            message_id = send_email(
                to=recipient_email,
                template="emails/client_portal_access.html",
                data={
                    "subject": f"Maverick Portal Update - {transaction.get('property_address')}",
                    "property_address": transaction.get("property_address"),
                    "client_type": party_label,
                    "portal_url": link,
                    "closing_date_label": (
                        transaction["closing_date"].strftime("%b %d, %Y") if transaction.get("closing_date") else "TBD"
                    ),
                },
            )
            if message_id:
                _log_portal_notification(transaction_id, party_type, milestone_key, "email", recipient_email)
                sent_email += 1
                log_portal_access(
                    portal_access_id=row.get("id"),
                    transaction_id=transaction_id,
                    party_type=party_type,
                    access_token=row.get("access_token"),
                    event_type="notification_sent",
                    section_name=milestone_key,
                    success=True,
                    details={"channel": "email", "message_id": message_id},
                )
    return {"sent_sms": sent_sms, "sent_email": sent_email}


def send_walkthrough_portal_reminders(limit=50):
    """Send one-time walkthrough-tomorrow reminders to active portal users."""
    ensure_party_portal_tables()
    target_date = date.today() + timedelta(days=1)
    rows = execute_query(
        """
        SELECT DISTINCT t.id
        FROM transactions t
        JOIN tasks tk ON tk.transaction_id = t.id
        WHERE t.status = 'ACTIVE'
          AND tk.completed = FALSE
          AND COALESCE(tk.status, 'pending') <> 'completed'
          AND tk.due_date = %s
          AND LOWER(COALESCE(tk.task_description, '')) LIKE %s
        ORDER BY t.id ASC
        LIMIT %s
        """,
        (target_date, "%walk%through%", max(1, min(int(limit or 50), 200))),
        fetch=True,
    ) or []
    sent = 0
    for row in rows:
        milestone_key = f"walkthrough_tomorrow_{target_date.isoformat()}"
        result = notify_portal_users_milestone(
            transaction_id=row["id"],
            milestone_key=milestone_key,
            message_template="⏰ Reminder: Final walk-through tomorrow. Check portal for details: {link}",
        )
        sent += int(result.get("sent_sms") or 0) + int(result.get("sent_email") or 0)
    return sent


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


def ensure_batch_upload_staging_table():
    """Track temporary batch upload files before final commit."""
    execute_query(
        """
        CREATE TABLE IF NOT EXISTS batch_upload_staging (
            id SERIAL PRIMARY KEY,
            batch_token VARCHAR(64) NOT NULL,
            uploaded_by VARCHAR(100) NOT NULL,
            original_filename VARCHAR(255) NOT NULL,
            temp_path TEXT NOT NULL,
            extension VARCHAR(10),
            file_size INT DEFAULT 0,
            suggested_transaction_id INT REFERENCES transactions(id) ON DELETE SET NULL,
            suggested_document_type VARCHAR(100),
            confidence_score DECIMAL(5,2) DEFAULT 0,
            analysis_payload JSONB DEFAULT '{}'::jsonb,
            status VARCHAR(20) DEFAULT 'pending',
            error_text TEXT,
            committed_document_id INT REFERENCES documents(id) ON DELETE SET NULL,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
        """
    )
    execute_query(
        """
        CREATE INDEX IF NOT EXISTS idx_batch_upload_staging_user_status
        ON batch_upload_staging(uploaded_by, status, created_at DESC)
        """
    )
    execute_query(
        """
        CREATE INDEX IF NOT EXISTS idx_batch_upload_staging_batch
        ON batch_upload_staging(batch_token, status, created_at DESC)
        """
    )


def _cleanup_temp_file(path_value):
    temp_path = (path_value or "").strip()
    if not temp_path:
        return
    try:
        if os.path.exists(temp_path):
            os.remove(temp_path)
    except OSError:
        pass


def fetch_batch_upload_pending_count(uploaded_by):
    """Return pending staged uploads for one TC user."""
    ensure_batch_upload_staging_table()
    username = (uploaded_by or "").strip().lower()
    if not username:
        return 0
    rows = execute_query(
        """
        SELECT COUNT(*) AS pending_count
        FROM batch_upload_staging
        WHERE uploaded_by = %s
          AND status = 'pending'
        """,
        (username,),
        fetch=True,
    ) or []
    return int((rows[0] or {}).get("pending_count") or 0) if rows else 0


def cleanup_stale_batch_upload_staging(max_age_hours=16):
    """Remove stale staged files + rows to avoid temp buildup."""
    ensure_batch_upload_staging_table()
    cutoff = datetime.now() - timedelta(hours=max(1, int(max_age_hours or 16)))
    rows = execute_query(
        """
        SELECT id, temp_path
        FROM batch_upload_staging
        WHERE created_at < %s
        ORDER BY id ASC
        LIMIT 500
        """,
        (cutoff,),
        fetch=True,
    ) or []
    for row in rows:
        _cleanup_temp_file(row.get("temp_path"))
        execute_query("DELETE FROM batch_upload_staging WHERE id = %s", (row["id"],))


def clear_pending_batch_upload_staging(uploaded_by):
    """Clear pending staged files for one user before creating a new batch."""
    ensure_batch_upload_staging_table()
    username = (uploaded_by or "").strip().lower()
    if not username:
        return
    rows = execute_query(
        """
        SELECT id, temp_path
        FROM batch_upload_staging
        WHERE uploaded_by = %s
          AND status = 'pending'
        """,
        (username,),
        fetch=True,
    ) or []
    for row in rows:
        _cleanup_temp_file(row.get("temp_path"))
        execute_query("DELETE FROM batch_upload_staging WHERE id = %s", (row["id"],))


def _batch_text_similarity(first, second):
    one = re.sub(r"\s+", " ", (first or "").strip().lower())
    two = re.sub(r"\s+", " ", (second or "").strip().lower())
    if not one or not two:
        return 0.0
    return float(SequenceMatcher(None, one, two).ratio())


def _batch_name_strength(extracted_name, transaction_name):
    extracted = re.sub(r"\s+", " ", (extracted_name or "").strip().lower())
    candidate = re.sub(r"\s+", " ", (transaction_name or "").strip().lower())
    if not extracted or not candidate:
        return 0.0
    if extracted in candidate or candidate in extracted:
        return 0.95
    extracted_tokens = {token for token in re.findall(r"[a-z0-9]+", extracted) if len(token) >= 3}
    candidate_tokens = {token for token in re.findall(r"[a-z0-9]+", candidate) if len(token) >= 3}
    if not extracted_tokens or not candidate_tokens:
        return _batch_text_similarity(extracted, candidate)
    overlap = len(extracted_tokens & candidate_tokens) / max(1, len(extracted_tokens | candidate_tokens))
    return max(overlap, _batch_text_similarity(extracted, candidate))


def fetch_batch_upload_candidate_transactions(limit=400):
    """Load candidate transactions for auto-assignment + manual override options."""
    rows = execute_query(
        """
        SELECT
            id,
            property_address,
            buyer_name,
            seller_name,
            status,
            closing_date
        FROM transactions
        WHERE COALESCE(status, '') <> 'CANCELLED'
        ORDER BY
            CASE
                WHEN status = 'ACTIVE' THEN 1
                WHEN status = 'NEEDS_MARGARET_REVIEW' THEN 2
                WHEN status = 'COMPLETED' THEN 3
                ELSE 4
            END,
            COALESCE(closing_date, CURRENT_DATE + INTERVAL '365 days') ASC,
            id DESC
        LIMIT %s
        """,
        (max(10, min(int(limit or 400), 1000)),),
        fetch=True,
    ) or []
    return rows


def _extract_json_from_model_text(raw_text):
    text = (raw_text or "").strip()
    if not text:
        return None
    fenced = re.search(r"```(?:json)?\s*(\{.*?\})\s*```", text, flags=re.DOTALL)
    if fenced:
        text = fenced.group(1).strip()
    start = text.find("{")
    end = text.rfind("}")
    if start == -1 or end == -1 or end <= start:
        return None
    candidate = text[start : end + 1]
    try:
        return json.loads(candidate)
    except Exception:
        try:
            normalized = re.sub(r"'", '"', candidate)
            return json.loads(normalized)
        except Exception:
            return None


def _extract_model_text_content(response):
    fragments = []
    for item in getattr(response, "content", []) or []:
        if getattr(item, "type", "") == "text":
            fragments.append(getattr(item, "text", ""))
    return "\n".join(fragment for fragment in fragments if fragment).strip()


def _extract_currency_value(raw_text, label_patterns):
    text = re.sub(r"\s+", " ", (raw_text or ""))
    for pattern in label_patterns or []:
        match = re.search(pattern, text, flags=re.IGNORECASE)
        if not match:
            continue
        value = re.sub(r"[^0-9.\-]", "", match.group(1) or "")
        try:
            amount = float(value)
            if amount > 0:
                return round(amount, 2)
        except ValueError:
            continue
    return None


def _batch_doc_type_from_heuristics(first_page_text, filename):
    text = (first_page_text or "").lower()
    filename_text = (filename or "").lower()
    combined = f"{filename_text} {text}"
    if "inspection report" in combined or ("inspector" in combined and "defect" in combined):
        return "inspection_report", 88
    if "earnest" in combined and ("receipt" in combined or "deposit" in combined):
        return "earnest_receipt", 90
    if "option fee" in combined and ("receipt" in combined or "payment" in combined):
        return "option_receipt", 84
    if "appraisal" in combined or "appraised value" in combined:
        return "appraisal", 86
    if "survey" in combined and ("metes" in combined or "bounds" in combined or "boundary" in combined):
        return "survey", 82
    if "title commitment" in combined or ("schedule b" in combined and "title" in combined):
        return "title_commitment", 84
    if "hoa" in combined or "homeowners association" in combined:
        return "hoa_docs", 80
    if "insurance binder" in combined or "certificate of insurance" in combined:
        return "insurance_binder", 79
    if "loan approval" in combined or "commitment letter" in combined:
        return "loan_approval", 79
    if "closing disclosure" in combined or "settlement statement" in combined or "hud-1" in combined:
        return "settlement_statement", 80
    return "other", 58


def _extract_batch_identifiers(first_page_text):
    text = first_page_text or ""
    property_address = extract_pattern_value(text, PROPERTY_ADDRESS_PATTERNS, cleanup_func=cleanup_address_candidate) or ""
    buyer_name = extract_pattern_value(text, BUYER_PATTERNS, cleanup_func=cleanup_name_candidate) or ""
    seller_name = extract_pattern_value(text, SELLER_PATTERNS, cleanup_func=cleanup_name_candidate) or ""
    file_match = re.search(
        r"(?:file|escrow|order|title)\s*(?:number|no\.?|#)\s*[:#-]?\s*([A-Za-z0-9-]{4,40})",
        text,
        flags=re.IGNORECASE,
    )
    file_number = (file_match.group(1) or "").strip() if file_match else ""
    return {
        "property_address": property_address,
        "buyer_name": buyer_name,
        "seller_name": seller_name,
        "file_number": file_number,
    }


def analyze_document_with_claude(first_page_text, filename):
    """
    Identify document type and transaction identifiers.
    Uses Claude when configured, with heuristic fallback.
    """
    fallback_type, fallback_conf = _batch_doc_type_from_heuristics(first_page_text, filename)
    fallback_ids = _extract_batch_identifiers(first_page_text)
    extracted_data = {}

    if fallback_type == "earnest_receipt":
        earnest_amount = extract_earnest_amount(first_page_text, key_info_extracted={})
        if earnest_amount is not None:
            extracted_data["earnest_amount"] = earnest_amount
    if fallback_type == "appraisal":
        appraised_value = _extract_currency_value(
            first_page_text,
            [
                r"appraised\s+value[^$0-9]{0,40}\$?\s*([0-9,]+(?:\.[0-9]{1,2})?)",
                r"market\s+value[^$0-9]{0,40}\$?\s*([0-9,]+(?:\.[0-9]{1,2})?)",
            ],
        )
        if appraised_value is not None:
            extracted_data["appraisal_value"] = appraised_value

    analysis = {
        "document_type": normalize_document_type(fallback_type, fallback="other"),
        "property_address": fallback_ids.get("property_address") or "",
        "transaction_identifiers": fallback_ids,
        "extracted_data": extracted_data,
        "confidence": fallback_conf,
        "source": "heuristic",
    }

    api_key = (os.getenv("ANTHROPIC_API_KEY") or "").strip()
    if api_key and (first_page_text or "").strip():
        try:
            from anthropic import Anthropic

            prompt = (
                "Analyze this transaction document and return JSON only.\n\n"
                f"Filename: {filename or 'unknown'}\n\n"
                "First page text:\n"
                f"{(first_page_text or '')[:3000]}\n\n"
                "Return JSON with keys:\n"
                "{\n"
                '  "document_type": "inspection_report|earnest_receipt|appraisal|survey|title_commitment|hoa_docs|loan_approval|insurance_binder|settlement_statement|option_receipt|seller_disclosure|other|unknown",\n'
                '  "property_address": "string",\n'
                '  "transaction_identifiers": {\n'
                '    "property_address": "string",\n'
                '    "buyer_name": "string",\n'
                '    "seller_name": "string",\n'
                '    "file_number": "string"\n'
                "  },\n"
                '  "extracted_data": {"earnest_amount": 0, "appraisal_value": 0},\n'
                '  "confidence": 0\n'
                "}"
            )
            client = Anthropic(api_key=api_key)
            response = client.messages.create(
                model=(os.getenv("BATCH_UPLOAD_ANALYSIS_MODEL") or "claude-sonnet-4-20250514"),
                max_tokens=1200,
                temperature=0,
                messages=[{"role": "user", "content": prompt}],
            )
            payload = _extract_json_from_model_text(_extract_model_text_content(response))
            if isinstance(payload, dict):
                model_ids = payload.get("transaction_identifiers")
                if not isinstance(model_ids, dict):
                    model_ids = {}
                merged_ids = dict(fallback_ids)
                for key in ("property_address", "buyer_name", "seller_name", "file_number"):
                    value = (model_ids.get(key) or payload.get(key) or "").strip()
                    if value:
                        merged_ids[key] = value
                model_doc_type = normalize_document_type(
                    payload.get("document_type") or payload.get("type"),
                    fallback=analysis["document_type"],
                )
                confidence_value = analysis["confidence"]
                try:
                    confidence_value = max(0, min(int(payload.get("confidence")), 100))
                except (TypeError, ValueError):
                    pass
                model_extracted = payload.get("extracted_data")
                if not isinstance(model_extracted, dict):
                    model_extracted = {}
                merged_extracted = dict(analysis.get("extracted_data") or {})
                merged_extracted.update(model_extracted)
                analysis = {
                    "document_type": model_doc_type,
                    "property_address": merged_ids.get("property_address") or "",
                    "transaction_identifiers": merged_ids,
                    "extracted_data": merged_extracted,
                    "confidence": confidence_value,
                    "source": "claude",
                }
        except Exception as exc:
            log_system_error("batch_upload_analysis", f"Claude fallback used: {str(exc)[:300]}")

    return analysis


def _find_transaction_by_file_number(file_number):
    candidate = (file_number or "").strip().lower()
    if not candidate:
        return None
    for column_name in ("title_file_number", "file_number"):
        if not _transaction_column_exists(column_name):
            continue
        rows = execute_query(
            f"""
            SELECT id, property_address
            FROM transactions
            WHERE COALESCE(status, '') <> 'CANCELLED'
              AND LOWER(COALESCE({column_name}, '')) = %s
            ORDER BY id DESC
            LIMIT 1
            """,
            (candidate,),
            fetch=True,
        ) or []
        if rows:
            return rows[0]
    return None


def find_similar_transactions(identifiers, candidates, limit=5):
    """Return top likely transactions for manual review dropdown hints."""
    address_value = (identifiers.get("property_address") or "").strip()
    buyer_value = (identifiers.get("buyer_name") or "").strip()
    seller_value = (identifiers.get("seller_name") or "").strip()
    scored = []
    for row in candidates or []:
        score = 0.0
        if address_value:
            score += _batch_text_similarity(normalize_address(address_value), normalize_address(row.get("property_address"))) * 0.6
        if buyer_value:
            score += _batch_name_strength(buyer_value, row.get("buyer_name")) * 0.2
        if seller_value:
            score += _batch_name_strength(seller_value, row.get("seller_name")) * 0.2
        if score <= 0:
            continue
        scored.append(
            {
                "transaction_id": row["id"],
                "property_address": row.get("property_address") or "",
                "score": round(float(score), 3),
                "status": row.get("status") or "",
            }
        )
    scored.sort(key=lambda item: item["score"], reverse=True)
    return scored[: max(1, min(int(limit or 5), 10))]


def find_matching_transaction(analysis, candidates=None):
    """Match one analyzed document to the best transaction."""
    identifiers = analysis.get("transaction_identifiers")
    if not isinstance(identifiers, dict):
        identifiers = {}
    candidate_rows = candidates or fetch_batch_upload_candidate_transactions(limit=500)
    property_address = (identifiers.get("property_address") or analysis.get("property_address") or "").strip()
    buyer_name = (identifiers.get("buyer_name") or "").strip()
    seller_name = (identifiers.get("seller_name") or "").strip()
    file_number = (identifiers.get("file_number") or "").strip()

    if property_address:
        matched = []
        for row in candidate_rows:
            match = addresses_match(property_address, row.get("property_address"))
            if match:
                similarity = _batch_text_similarity(normalize_address(property_address), normalize_address(row.get("property_address")))
                matched.append((similarity, row))
        if matched:
            matched.sort(key=lambda item: item[0], reverse=True)
            winner = matched[0][1]
            return {
                "transaction_id": winner["id"],
                "property_address": winner.get("property_address") or "",
                "confidence": 0.95,
                "method": "property_address_match",
            }

    if file_number:
        file_match = _find_transaction_by_file_number(file_number)
        if file_match:
            return {
                "transaction_id": file_match["id"],
                "property_address": file_match.get("property_address") or "",
                "confidence": 0.9,
                "method": "file_number_match",
            }

    if buyer_name or seller_name:
        best = None
        best_score = 0.0
        for row in candidate_rows:
            buyer_score = _batch_name_strength(buyer_name, row.get("buyer_name")) if buyer_name else 0.0
            seller_score = _batch_name_strength(seller_name, row.get("seller_name")) if seller_name else 0.0
            if buyer_name and seller_name:
                score = (buyer_score * 0.5) + (seller_score * 0.5)
            elif buyer_name:
                score = buyer_score * 0.92
            else:
                score = seller_score * 0.9
            if score > best_score:
                best = row
                best_score = score
        if best and best_score >= 0.82:
            return {
                "transaction_id": best["id"],
                "property_address": best.get("property_address") or "",
                "confidence": round(max(0.85, min(best_score, 0.93)), 3),
                "method": "party_name_match",
            }

    return {
        "confidence": 0.3,
        "reason": "Could not match to active transaction",
        "possible_matches": find_similar_transactions(identifiers, candidate_rows),
    }


def _parse_batch_money(value):
    if value in (None, ""):
        return None
    cleaned = re.sub(r"[^0-9.\-]", "", str(value))
    if cleaned in {"", "-", ".", "-."}:
        return None
    try:
        amount = float(cleaned)
        if amount <= 0:
            return None
        return round(amount, 2)
    except ValueError:
        return None


def update_transaction_from_batch_extracted_data(transaction_id, document_type, extracted_data):
    """Apply extracted numeric values from batch upload documents."""
    payload = extracted_data if isinstance(extracted_data, dict) else {}
    normalized_type = normalize_document_type(document_type, fallback="other")
    applied_updates = []

    earnest_amount = _parse_batch_money(
        payload.get("earnest_amount")
        or payload.get("deposit_amount")
        or payload.get("amount")
    )
    appraisal_value = _parse_batch_money(
        payload.get("appraisal_value")
        or payload.get("appraised_value")
        or payload.get("market_value")
    )

    if earnest_amount is not None and _transaction_column_exists("earnest_amount"):
        execute_query(
            """
            UPDATE transactions
            SET earnest_amount = %s,
                updated_at = CURRENT_TIMESTAMP
            WHERE id = %s
            """,
            (earnest_amount, int(transaction_id)),
        )
        applied_updates.append("earnest_amount")

    if normalized_type == "appraisal" and appraisal_value is not None and _transaction_column_exists("appraised_value"):
        execute_query(
            """
            UPDATE transactions
            SET appraised_value = %s,
                updated_at = CURRENT_TIMESTAMP
            WHERE id = %s
            """,
            (appraisal_value, int(transaction_id)),
        )
        applied_updates.append("appraised_value")
    return applied_updates


def stage_batch_upload_record(
    batch_token,
    uploaded_by,
    original_filename,
    temp_path,
    extension,
    file_size,
    suggested_transaction_id,
    suggested_document_type,
    confidence_score,
    analysis_payload,
):
    """Persist one staged batch upload row."""
    ensure_batch_upload_staging_table()
    return execute_insert(
        """
        INSERT INTO batch_upload_staging (
            batch_token,
            uploaded_by,
            original_filename,
            temp_path,
            extension,
            file_size,
            suggested_transaction_id,
            suggested_document_type,
            confidence_score,
            analysis_payload,
            status,
            created_at
        )
        VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s::jsonb, 'pending', CURRENT_TIMESTAMP)
        RETURNING id
        """,
        (
            (batch_token or "").strip(),
            (uploaded_by or "").strip().lower()[:100],
            (original_filename or "")[:255],
            temp_path,
            (extension or "")[:10],
            int(file_size or 0),
            int(suggested_transaction_id) if suggested_transaction_id else None,
            (suggested_document_type or "other")[:100],
            float(confidence_score or 0),
            json.dumps(analysis_payload or {}, default=str),
        ),
    )


def fetch_staged_batch_upload_row(stage_id, uploaded_by):
    """Fetch one pending staged row for current user."""
    ensure_batch_upload_staging_table()
    rows = execute_query(
        """
        SELECT
            id,
            batch_token,
            uploaded_by,
            original_filename,
            temp_path,
            extension,
            file_size,
            suggested_transaction_id,
            suggested_document_type,
            confidence_score,
            analysis_payload,
            status
        FROM batch_upload_staging
        WHERE id = %s
          AND uploaded_by = %s
          AND status = 'pending'
        LIMIT 1
        """,
        (int(stage_id), (uploaded_by or "").strip().lower()),
        fetch=True,
    ) or []
    return rows[0] if rows else None


def mark_batch_upload_stage_result(stage_id, status, error_text="", committed_document_id=None):
    """Mark staged record as completed/failed."""
    ensure_batch_upload_staging_table()
    execute_query(
        """
        UPDATE batch_upload_staging
        SET status = %s,
            error_text = %s,
            committed_document_id = %s
        WHERE id = %s
        """,
        (
            (status or "failed")[:20],
            (error_text or "")[:1000] or None,
            int(committed_document_id) if committed_document_id else None,
            int(stage_id),
        ),
    )


def ensure_date_cascade_tables():
    """Store date-cascade snapshots for preview/undo workflows."""
    execute_query(
        """
        CREATE TABLE IF NOT EXISTS transaction_date_cascade_log (
            id SERIAL PRIMARY KEY,
            transaction_id INT REFERENCES transactions(id) ON DELETE CASCADE,
            date_field VARCHAR(80) NOT NULL,
            old_date DATE,
            new_date DATE,
            delta_days INT DEFAULT 0,
            cascade_options JSONB DEFAULT '{}'::jsonb,
            snapshot JSONB DEFAULT '{}'::jsonb,
            results JSONB DEFAULT '{}'::jsonb,
            initiated_by VARCHAR(100),
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            expires_at TIMESTAMP,
            undone_at TIMESTAMP,
            undo_summary JSONB DEFAULT '{}'::jsonb
        )
        """
    )
    execute_query(
        """
        CREATE INDEX IF NOT EXISTS idx_transaction_date_cascade_txn
        ON transaction_date_cascade_log(transaction_id, created_at DESC)
        """
    )
    execute_query(
        """
        CREATE INDEX IF NOT EXISTS idx_transaction_date_cascade_open
        ON transaction_date_cascade_log(transaction_id, undone_at, expires_at DESC)
        """
    )


def _to_iso_date(value):
    if isinstance(value, datetime):
        return value.date().isoformat()
    if isinstance(value, date):
        return value.isoformat()
    if isinstance(value, str):
        parsed = _parse_iso_date(value)
        return parsed.isoformat() if parsed else ""
    return ""


def _to_iso_datetime(value):
    if isinstance(value, datetime):
        return value.isoformat()
    if isinstance(value, date):
        return datetime.combine(value, time(0, 0)).isoformat()
    return ""


def _parse_iso_date(raw_value):
    value = (raw_value or "").strip() if isinstance(raw_value, str) else ""
    if not value:
        return None
    token = value[:10]
    try:
        return datetime.strptime(token, "%Y-%m-%d").date()
    except ValueError:
        return None


def _parse_iso_datetime(raw_value):
    if isinstance(raw_value, datetime):
        return raw_value
    if isinstance(raw_value, date):
        return datetime.combine(raw_value, time(0, 0))
    value = (raw_value or "").strip() if isinstance(raw_value, str) else ""
    if not value:
        return None
    try:
        return datetime.fromisoformat(value)
    except ValueError:
        parsed_date = _parse_iso_date(value)
        if parsed_date:
            return datetime.combine(parsed_date, time(0, 0))
        return None


def _shift_date_value(value, delta_days):
    if isinstance(value, datetime):
        return (value + timedelta(days=delta_days)).date()
    if isinstance(value, date):
        return value + timedelta(days=delta_days)
    return None


def _shift_datetime_value(value, delta_days):
    if isinstance(value, datetime):
        return value + timedelta(days=delta_days)
    if isinstance(value, date):
        return datetime.combine(value, time(0, 0)) + timedelta(days=delta_days)
    return None


def normalize_date_cascade_options(raw_options):
    defaults = {
        "update_deadlines": True,
        "reschedule_appointments": True,
        "update_tasks": True,
        "sync_calendar": True,
        "notify_parties": True,
    }
    if not isinstance(raw_options, dict):
        return defaults
    normalized = {}
    for key, default_value in defaults.items():
        normalized[key] = parse_bool_value(raw_options.get(key), default=default_value)
    return normalized


def _nth_weekday_of_month(year, month, weekday, occurrence):
    candidate = date(year, month, 1)
    while candidate.weekday() != weekday:
        candidate += timedelta(days=1)
    return candidate + timedelta(days=7 * (occurrence - 1))


def _last_weekday_of_month(year, month, weekday):
    if month == 12:
        candidate = date(year + 1, 1, 1) - timedelta(days=1)
    else:
        candidate = date(year, month + 1, 1) - timedelta(days=1)
    while candidate.weekday() != weekday:
        candidate -= timedelta(days=1)
    return candidate


def _observed_holiday(day):
    if day.weekday() == 5:
        return day - timedelta(days=1)
    if day.weekday() == 6:
        return day + timedelta(days=1)
    return day


def _us_holiday_set(year):
    fixed = {
        date(year, 1, 1),   # New Year
        date(year, 6, 19),  # Juneteenth
        date(year, 7, 4),   # Independence Day
        date(year, 11, 11), # Veterans Day
        date(year, 12, 25), # Christmas
    }
    observed = {_observed_holiday(day) for day in fixed}
    floating = {
        _nth_weekday_of_month(year, 1, 0, 3),   # MLK Day
        _nth_weekday_of_month(year, 2, 0, 3),   # Presidents Day
        _last_weekday_of_month(year, 5, 0),     # Memorial Day
        _nth_weekday_of_month(year, 9, 0, 1),   # Labor Day
        _nth_weekday_of_month(year, 10, 0, 2),  # Columbus Day
        _nth_weekday_of_month(year, 11, 3, 4),  # Thanksgiving
    }
    return observed | floating


def _is_weekend_or_holiday(target_date):
    if not isinstance(target_date, date):
        return False
    return target_date.weekday() >= 5 or target_date in _us_holiday_set(target_date.year)


def _next_business_day(target_date):
    if not isinstance(target_date, date):
        return None
    candidate = target_date
    for _ in range(10):
        if not _is_weekend_or_holiday(candidate):
            return candidate
        candidate += timedelta(days=1)
    return candidate


def _task_blueprint_description_set(anchor_value):
    descriptions = set()
    for item in TASK_BLUEPRINTS:
        if len(item) < 3:
            continue
        if item[2] != anchor_value:
            continue
        descriptions.add((item[0] or "").strip().lower())
    return descriptions


def _deadline_types_for_date_field(date_field):
    normalized = (date_field or "").strip().lower()
    if normalized == "closing_date":
        return {row[0] for row in DEADLINE_BLUEPRINTS if row[0] != "effective_date"}
    if normalized == "effective_date":
        return {row[0] for row in DEADLINE_BLUEPRINTS if row[0] != "closing"}
    if normalized == "earnest_due_date":
        return {"earnest_money"}
    if normalized == "option_period_end_date":
        return {"option_period_end", "buyer_hoa_review"}
    if normalized == "financing_approval_date":
        return {"financing_approval", "buyer_title_objection"}
    return set()


def _candidate_deadlines_for_cascade(transaction_id, date_field):
    deadline_types = sorted(_deadline_types_for_date_field(date_field))
    if not deadline_types:
        return []
    placeholders = ", ".join(["%s"] * len(deadline_types))
    rows = execute_query(
        f"""
        SELECT id, deadline_type, deadline_date
        FROM deadlines
        WHERE transaction_id = %s
          AND completed = FALSE
          AND deadline_date IS NOT NULL
          AND deadline_type IN ({placeholders})
        ORDER BY deadline_date ASC, id ASC
        """,
        tuple([int(transaction_id), *deadline_types]),
        fetch=True,
    ) or []
    return rows


def _candidate_tasks_for_cascade(transaction_id, date_field, old_date):
    rows = execute_query(
        """
        SELECT id, task_description, due_date
        FROM tasks
        WHERE transaction_id = %s
          AND due_date IS NOT NULL
          AND completed = FALSE
          AND COALESCE(status, 'pending') <> 'completed'
        ORDER BY due_date ASC, id ASC
        """,
        (int(transaction_id),),
        fetch=True,
    ) or []
    if not rows:
        return []

    normalized = (date_field or "").strip().lower()
    selected = []
    if normalized == "effective_date":
        effective_descriptions = _task_blueprint_description_set("effective")
        for row in rows:
            desc = (row.get("task_description") or "").strip().lower()
            if desc in effective_descriptions:
                selected.append(row)
    elif normalized == "closing_date":
        closing_descriptions = _task_blueprint_description_set("closing")
        for row in rows:
            due_date = row.get("due_date")
            desc = (row.get("task_description") or "").strip().lower()
            if desc in closing_descriptions:
                selected.append(row)
                continue
            if isinstance(due_date, date) and isinstance(old_date, date):
                if due_date >= (old_date - timedelta(days=10)):
                    selected.append(row)
    else:
        for row in rows:
            due_date = row.get("due_date")
            if isinstance(due_date, date) and isinstance(old_date, date):
                if due_date >= old_date:
                    selected.append(row)
    return selected


def _candidate_vendor_appointments_for_cascade(transaction_id, date_field, old_date):
    rows = execute_query(
        """
        SELECT id, vendor_type, appointment_at
        FROM vendor_outreach
        WHERE transaction_id = %s
          AND appointment_at IS NOT NULL
        ORDER BY appointment_at ASC, id ASC
        """,
        (int(transaction_id),),
        fetch=True,
    ) or []
    normalized = (date_field or "").strip().lower()
    if normalized != "closing_date":
        return []
    selected = []
    for row in rows:
        appointment_at = row.get("appointment_at")
        if not isinstance(appointment_at, datetime):
            continue
        if isinstance(old_date, date):
            if appointment_at.date() < (old_date - timedelta(days=7)):
                continue
        selected.append(row)
    return selected


def estimate_date_cascade_changes(transaction_id, date_field, delta_days, cascade_options, old_date, new_date):
    """Preview impacted rows and conflict warnings before apply."""
    options = normalize_date_cascade_options(cascade_options)
    transaction = get_transaction_or_none(transaction_id) or {}
    conflicts = detect_date_change_conflicts(transaction, date_field, old_date, new_date)
    deadline_rows = _candidate_deadlines_for_cascade(transaction_id, date_field) if options["update_deadlines"] else []
    task_rows = _candidate_tasks_for_cascade(transaction_id, date_field, old_date) if options["update_tasks"] else []
    appointment_rows = (
        _candidate_vendor_appointments_for_cascade(transaction_id, date_field, old_date)
        if options["reschedule_appointments"]
        else []
    )
    mapped_rows = fetch_calendar_mappings(transaction_id=transaction_id, limit=300) if options["sync_calendar"] else []
    calendar_count = 0
    if mapped_rows:
        for row in mapped_rows:
            if (row.get("status") or "").lower() == "active":
                calendar_count += 1
    return {
        "delta_days": int(delta_days),
        "deadlines_updated": len(deadline_rows),
        "tasks_updated": len(task_rows),
        "appointments_updated": len(appointment_rows),
        "calendar_events_updated": calendar_count,
        "notifications_sent": 0,
        "conflicts": conflicts,
        "requires_confirmation": bool(conflicts),
    }


def detect_date_change_conflicts(transaction, date_field, old_date, new_date):
    """Return warning/suggestion list before applying cascades."""
    conflicts = []
    normalized = (date_field or "").strip().lower()
    if not isinstance(new_date, date):
        return conflicts

    if normalized == "closing_date":
        appraisal_rows = execute_query(
            """
            SELECT appointment_at
            FROM vendor_outreach
            WHERE transaction_id = %s
              AND LOWER(COALESCE(vendor_type, '')) IN ('appraiser', 'appraisal')
              AND appointment_at IS NOT NULL
            ORDER BY appointment_at ASC
            LIMIT 1
            """,
            (transaction.get("id"),),
            fetch=True,
        ) or []
        if appraisal_rows:
            appraisal_dt = appraisal_rows[0].get("appointment_at")
            if isinstance(appraisal_dt, datetime) and new_date < appraisal_dt.date():
                conflicts.append(
                    {
                        "severity": "warning",
                        "message": (
                            f"New closing date ({new_date.strftime('%b %d')}) is before appraisal "
                            f"({appraisal_dt.strftime('%b %d')})."
                        ),
                    }
                )

        financing_date = transaction.get("financing_approval_date")
        if isinstance(financing_date, date) and new_date < financing_date:
            conflicts.append(
                {
                    "severity": "warning",
                    "message": (
                        f"New closing date ({new_date.strftime('%b %d')}) is before financing approval "
                        f"deadline ({financing_date.strftime('%b %d')})."
                    ),
                }
            )

    if new_date < date.today():
        conflicts.append(
            {
                "severity": "warning",
                "message": "Selected date is in the past.",
            }
        )

    if _is_weekend_or_holiday(new_date):
        alternative = _next_business_day(new_date)
        alt_text = alternative.strftime("%b %d, %Y") if isinstance(alternative, date) else "next business day"
        conflicts.append(
            {
                "severity": "suggestion",
                "message": f"Selected date falls on a weekend/holiday. Consider {alt_text}.",
            }
        )
    return conflicts


def _apply_transaction_date_updates(transaction_id, field_values):
    safe_updates = {}
    for key, value in (field_values or {}).items():
        if key not in DATE_CASCADE_TRANSACTION_COLUMNS:
            continue
        if isinstance(value, date):
            safe_updates[key] = value
    if not safe_updates:
        return
    set_parts = []
    params = []
    for key, value in safe_updates.items():
        set_parts.append(f"{key} = %s")
        params.append(value)
    params.append(int(transaction_id))
    execute_query(
        f"""
        UPDATE transactions
        SET {", ".join(set_parts)},
            updated_at = CURRENT_TIMESTAMP
        WHERE id = %s
        """,
        tuple(params),
    )


def _transaction_date_snapshot_map(transaction_row):
    snapshot = {}
    for column in DATE_CASCADE_TRANSACTION_COLUMNS:
        snapshot[column] = _to_iso_date(transaction_row.get(column))
    return snapshot


def cascade_date_change(
    transaction_id,
    date_field,
    delta_days,
    old_date,
    new_date,
    cascade_options,
    initiated_by="margaret",
):
    """
    Automatically adjust dependent data after a transaction date change.
    """
    options = normalize_date_cascade_options(cascade_options)
    transaction_before = get_transaction_or_none(transaction_id) or {}
    changes = {
        "deadlines_updated": 0,
        "tasks_updated": 0,
        "appointments_updated": 0,
        "calendar_events_updated": 0,
        "notifications_sent": 0,
    }
    snapshot = {
        "transaction_dates": _transaction_date_snapshot_map(transaction_before),
        "deadlines": [],
        "tasks": [],
        "appointments": [],
    }

    normalized_field = (date_field or "").strip().lower()
    if normalized_field == "effective_date" and options["update_deadlines"]:
        dependent_values = {}
        for column in EFFECTIVE_DATE_CASCADE_COLUMNS:
            old_value = transaction_before.get(column)
            shifted = _shift_date_value(old_value, delta_days)
            if shifted:
                dependent_values[column] = shifted
        if dependent_values:
            _apply_transaction_date_updates(transaction_id, dependent_values)
    elif normalized_field == "option_period_end_date" and options["update_deadlines"]:
        old_value = transaction_before.get("buyer_hoa_review_end_date")
        shifted = _shift_date_value(old_value, delta_days)
        if shifted:
            _apply_transaction_date_updates(transaction_id, {"buyer_hoa_review_end_date": shifted})
    elif normalized_field == "financing_approval_date" and options["update_deadlines"]:
        old_value = transaction_before.get("buyer_title_objection_end_date")
        shifted = _shift_date_value(old_value, delta_days)
        if shifted:
            _apply_transaction_date_updates(transaction_id, {"buyer_title_objection_end_date": shifted})

    if options["update_deadlines"]:
        deadline_rows = _candidate_deadlines_for_cascade(transaction_id, normalized_field)
        for row in deadline_rows:
            old_deadline = row.get("deadline_date")
            if not isinstance(old_deadline, date):
                continue
            new_deadline = old_deadline + timedelta(days=delta_days)
            execute_query(
                """
                UPDATE deadlines
                SET deadline_date = %s
                WHERE id = %s
                  AND transaction_id = %s
                """,
                (new_deadline, row["id"], int(transaction_id)),
            )
            snapshot["deadlines"].append(
                {
                    "id": row["id"],
                    "old_date": _to_iso_date(old_deadline),
                }
            )
            changes["deadlines_updated"] += 1

    if options["update_tasks"]:
        task_rows = _candidate_tasks_for_cascade(transaction_id, normalized_field, old_date)
        for row in task_rows:
            old_due = row.get("due_date")
            if not isinstance(old_due, date):
                continue
            new_due = old_due + timedelta(days=delta_days)
            execute_query(
                """
                UPDATE tasks
                SET due_date = %s
                WHERE id = %s
                  AND transaction_id = %s
                """,
                (new_due, row["id"], int(transaction_id)),
            )
            snapshot["tasks"].append(
                {
                    "id": row["id"],
                    "old_date": _to_iso_date(old_due),
                }
            )
            changes["tasks_updated"] += 1

    if options["reschedule_appointments"]:
        appointment_rows = _candidate_vendor_appointments_for_cascade(transaction_id, normalized_field, old_date)
        for row in appointment_rows:
            old_appt = row.get("appointment_at")
            if not isinstance(old_appt, datetime):
                continue
            new_appt = old_appt + timedelta(days=delta_days)
            execute_query(
                """
                UPDATE vendor_outreach
                SET appointment_at = %s
                WHERE id = %s
                  AND transaction_id = %s
                """,
                (new_appt, row["id"], int(transaction_id)),
            )
            snapshot["appointments"].append(
                {
                    "id": row["id"],
                    "old_at": _to_iso_datetime(old_appt),
                }
            )
            changes["appointments_updated"] += 1

    if options["sync_calendar"]:
        calendar_summary = sync_transaction_calendar_bundle(
            transaction_id=transaction_id,
            actor=(initiated_by or "margaret"),
            force_update=True,
            include_deadlines=options["update_deadlines"],
            include_closing=True,
            include_vendor_events=options["reschedule_appointments"],
        )
        changes["calendar_events_updated"] = (
            int(calendar_summary.get("deadline_synced") or 0)
            + int(calendar_summary.get("vendor_synced") or 0)
            + (1 if calendar_summary.get("closing_synced") else 0)
        )
        changes["calendar_summary"] = calendar_summary
    return {"changes": changes, "snapshot": snapshot}


def _fetch_transaction_client_emails(transaction_id):
    emails = {"buyer": "", "seller": ""}
    rows = fetch_client_access_rows(transaction_id)
    for row in rows:
        role = (row.get("client_type") or "").strip().lower()
        if role not in emails:
            continue
        email_value = normalize_email(row.get("email"))
        if email_value:
            emails[role] = email_value
    return emails


def _unique_nonempty(values):
    seen = set()
    ordered = []
    for value in values:
        token = (value or "").strip()
        if not token or token in seen:
            continue
        seen.add(token)
        ordered.append(token)
    return ordered


def notify_date_change(
    transaction_id,
    date_field,
    old_date,
    new_date,
    cascade_results,
    send_notifications=True,
    is_undo=False,
):
    """
    Notify transaction parties after a cascaded date change.
    """
    transaction = get_transaction_or_none(transaction_id)
    if not transaction:
        return {"notifications_sent": 0, "timeline_url": ""}

    timeline_result = regenerate_and_resend_timeline(
        transaction_id=transaction_id,
        reason="date_change_undo" if is_undo else "date_change_cascade",
        force=True,
        send_vendor_notifications=False,
    )
    timeline_url = timeline_result.get("timeline_url") if isinstance(timeline_result, dict) else ""
    if not send_notifications:
        return {"notifications_sent": 0, "timeline_url": timeline_url}

    date_label = (date_field or "").replace("_", " ").title()
    old_label = old_date.strftime("%b %d, %Y") if isinstance(old_date, date) else "Unknown"
    new_label = new_date.strftime("%b %d, %Y") if isinstance(new_date, date) else "Unknown"
    property_address = transaction.get("property_address") or "the transaction"

    sms_message = (
        f"Disregard previous date-change notice for {property_address}. "
        f"{date_label} is restored to {new_label}."
        if is_undo
        else (
            f"{date_label} for {property_address} moved from {old_label} to {new_label}. "
            "Updated timeline sent by email."
        )
    )
    sms_recipients = _unique_nonempty(
        [
            normalize_phone(transaction.get("agent_phone")),
            normalize_phone(transaction.get("buyer_phone")),
            normalize_phone(transaction.get("seller_phone")),
        ]
    )
    notifications_sent = 0
    for recipient in sms_recipients:
        sid = send_sms(recipient, sms_message)
        if sid:
            notifications_sent += 1

    client_emails = _fetch_transaction_client_emails(transaction_id)
    email_targets = _unique_nonempty(
        [
            normalize_email(transaction.get("agent_email")),
            normalize_email(client_emails.get("buyer")),
            normalize_email(client_emails.get("seller")),
            normalize_email(transaction.get("lender_email")),
            normalize_email(transaction.get("title_officer_email")),
        ]
    )
    attachments = []
    if timeline_url and not is_undo:
        attachments.append(
            {
                "filename": f"timeline_transaction_{transaction_id}.pdf",
                "content_type": "application/pdf",
                "url": timeline_url,
            }
        )

    for target in email_targets:
        message_id = send_email(
            to=target,
            template="emails/date_change_notification.html",
            data={
                "subject": (
                    f"Maverick TC - Disregard prior date update - {property_address}"
                    if is_undo
                    else f"Maverick TC - Date update for {property_address}"
                ),
                "transaction": transaction,
                "field_changed": date_field,
                "field_label": date_label,
                "old_date": old_date,
                "new_date": new_date,
                "old_date_label": old_label,
                "new_date_label": new_label,
                "changes": cascade_results,
                "timeline_url": timeline_url,
                "is_undo": is_undo,
            },
            attachments=attachments if attachments else None,
        )
        if message_id:
            notifications_sent += 1

    execute_query(
        """
        INSERT INTO communications (transaction_id, communication_type, contact_party, contact_name, summary, outcome)
        VALUES (%s, 'note', 'system', 'date_cascade', %s, %s)
        """,
        (
            transaction_id,
            "Date cascade notifications sent" if not is_undo else "Date cascade undo notifications sent",
            (
                f"field={date_field} old={old_label} new={new_label} "
                f"deadlines={int(cascade_results.get('deadlines_updated') or 0)} "
                f"tasks={int(cascade_results.get('tasks_updated') or 0)} "
                f"calendar={int(cascade_results.get('calendar_events_updated') or 0)} "
                f"notifications={notifications_sent} "
                f"undo={is_undo}"
            ),
        ),
    )
    return {"notifications_sent": notifications_sent, "timeline_url": timeline_url}


def record_date_cascade_log(
    transaction_id,
    date_field,
    old_date,
    new_date,
    delta_days,
    cascade_options,
    snapshot,
    results,
    initiated_by,
):
    ensure_date_cascade_tables()
    return execute_insert(
        """
        INSERT INTO transaction_date_cascade_log (
            transaction_id,
            date_field,
            old_date,
            new_date,
            delta_days,
            cascade_options,
            snapshot,
            results,
            initiated_by,
            created_at,
            expires_at
        )
        VALUES (%s, %s, %s, %s, %s, %s::jsonb, %s::jsonb, %s::jsonb, %s, CURRENT_TIMESTAMP, CURRENT_TIMESTAMP + INTERVAL '24 hours')
        RETURNING id
        """,
        (
            int(transaction_id),
            (date_field or "").strip().lower(),
            old_date if isinstance(old_date, date) else None,
            new_date if isinstance(new_date, date) else None,
            int(delta_days or 0),
            json.dumps(cascade_options or {}, default=str),
            json.dumps(snapshot or {}, default=str),
            json.dumps(results or {}, default=str),
            (initiated_by or "margaret")[:100],
        ),
    )


def fetch_recent_date_cascade_logs(transaction_id, limit=12):
    ensure_date_cascade_tables()
    rows = execute_query(
        """
        SELECT
            id,
            transaction_id,
            date_field,
            old_date,
            new_date,
            delta_days,
            cascade_options,
            results,
            initiated_by,
            created_at,
            expires_at,
            undone_at
        FROM transaction_date_cascade_log
        WHERE transaction_id = %s
        ORDER BY created_at DESC, id DESC
        LIMIT %s
        """,
        (int(transaction_id), max(1, min(int(limit or 12), 40))),
        fetch=True,
    ) or []
    for row in rows:
        row["cascade_options"] = parse_json_field(row.get("cascade_options"), {})
        row["results"] = parse_json_field(row.get("results"), {})
        row["created_at_label"] = format_timestamp_label(row.get("created_at"))
        row["expires_at_label"] = format_timestamp_label(row.get("expires_at"))
        row["undo_available"] = bool(
            row.get("undone_at") is None
            and isinstance(row.get("expires_at"), datetime)
            and row["expires_at"] >= datetime.now()
        )
        row["field_label"] = (row.get("date_field") or "").replace("_", " ").title()
        row["old_date_label"] = format_date_label(row.get("old_date"))
        row["new_date_label"] = format_date_label(row.get("new_date"))
    return rows


def fetch_date_cascade_log_for_undo(transaction_id, cascade_log_id):
    ensure_date_cascade_tables()
    rows = execute_query(
        """
        SELECT
            id,
            transaction_id,
            date_field,
            old_date,
            new_date,
            delta_days,
            cascade_options,
            snapshot,
            results,
            created_at,
            expires_at,
            undone_at
        FROM transaction_date_cascade_log
        WHERE id = %s
          AND transaction_id = %s
        LIMIT 1
        """,
        (int(cascade_log_id), int(transaction_id)),
        fetch=True,
    ) or []
    if not rows:
        return None
    row = rows[0]
    row["cascade_options"] = parse_json_field(row.get("cascade_options"), {})
    row["snapshot"] = parse_json_field(row.get("snapshot"), {})
    row["results"] = parse_json_field(row.get("results"), {})
    return row


def undo_date_cascade_change(transaction_id, cascade_log_id):
    """Revert cascaded changes from a log entry within 24 hours."""
    log_row = fetch_date_cascade_log_for_undo(transaction_id, cascade_log_id)
    if not log_row:
        return {"success": False, "error": "cascade_log_not_found"}
    if log_row.get("undone_at"):
        return {"success": False, "error": "already_undone"}
    expires_at = log_row.get("expires_at")
    if isinstance(expires_at, datetime) and expires_at < datetime.now():
        return {"success": False, "error": "undo_window_expired"}

    snapshot = log_row.get("snapshot") if isinstance(log_row.get("snapshot"), dict) else {}
    transaction_dates = snapshot.get("transaction_dates") if isinstance(snapshot.get("transaction_dates"), dict) else {}
    tx_updates = {}
    for column, raw_value in transaction_dates.items():
        if column not in DATE_CASCADE_TRANSACTION_COLUMNS:
            continue
        parsed = _parse_iso_date(raw_value)
        if parsed:
            tx_updates[column] = parsed
        else:
            # allow explicit clearing
            tx_updates[column] = None

    if tx_updates:
        set_parts = []
        params = []
        for key, value in tx_updates.items():
            set_parts.append(f"{key} = %s")
            params.append(value)
        params.append(int(transaction_id))
        execute_query(
            f"""
            UPDATE transactions
            SET {", ".join(set_parts)},
                updated_at = CURRENT_TIMESTAMP
            WHERE id = %s
            """,
            tuple(params),
        )

    for item in snapshot.get("deadlines") or []:
        row_id = parse_optional_int((item or {}).get("id"))
        parsed = _parse_iso_date((item or {}).get("old_date"))
        if not row_id:
            continue
        execute_query(
            """
            UPDATE deadlines
            SET deadline_date = %s
            WHERE id = %s
              AND transaction_id = %s
            """,
            (parsed, row_id, int(transaction_id)),
        )

    for item in snapshot.get("tasks") or []:
        row_id = parse_optional_int((item or {}).get("id"))
        parsed = _parse_iso_date((item or {}).get("old_date"))
        if not row_id:
            continue
        execute_query(
            """
            UPDATE tasks
            SET due_date = %s
            WHERE id = %s
              AND transaction_id = %s
            """,
            (parsed, row_id, int(transaction_id)),
        )

    for item in snapshot.get("appointments") or []:
        row_id = parse_optional_int((item or {}).get("id"))
        parsed = _parse_iso_datetime((item or {}).get("old_at"))
        if not row_id:
            continue
        execute_query(
            """
            UPDATE vendor_outreach
            SET appointment_at = %s
            WHERE id = %s
              AND transaction_id = %s
            """,
            (parsed, row_id, int(transaction_id)),
        )

    options = normalize_date_cascade_options(log_row.get("cascade_options"))
    calendar_summary = sync_transaction_calendar_bundle(
        transaction_id=transaction_id,
        actor=session.get("tc_username", "margaret"),
        force_update=True,
        include_deadlines=options.get("update_deadlines", True),
        include_closing=True,
        include_vendor_events=options.get("reschedule_appointments", True),
    )
    notification_result = notify_date_change(
        transaction_id=transaction_id,
        date_field=log_row.get("date_field"),
        old_date=log_row.get("new_date"),
        new_date=log_row.get("old_date"),
        cascade_results=parse_json_field(log_row.get("results"), {}),
        send_notifications=True,
        is_undo=True,
    )
    undo_summary = {
        "calendar_summary": calendar_summary,
        "notifications_sent": int(notification_result.get("notifications_sent") or 0),
        "undone_by": session.get("tc_username", "margaret"),
        "undone_at": datetime.now().isoformat(),
    }
    execute_query(
        """
        UPDATE transaction_date_cascade_log
        SET undone_at = CURRENT_TIMESTAMP,
            undo_summary = %s::jsonb
        WHERE id = %s
          AND transaction_id = %s
        """,
        (json.dumps(undo_summary, default=str), int(cascade_log_id), int(transaction_id)),
    )
    return {"success": True, "undo_summary": undo_summary}


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
    cleanup_stale_batch_upload_staging()
    try:
        send_walkthrough_portal_reminders(limit=60)
    except Exception as exc:
        print(f"Portal walkthrough reminder sweep error: {exc}")
    uploaded_by = (session.get("tc_username") or "margaret").strip().lower()
    pending_batch_upload_count = fetch_batch_upload_pending_count(uploaded_by)
    session["batch_upload_pending_count"] = pending_batch_upload_count

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
        pending_batch_upload_count=pending_batch_upload_count,
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


def _suggested_shortcode_from_text(raw_text):
    words = re.findall(r"[a-z0-9]+", (raw_text or "").lower())
    words = [word for word in words if len(word) >= 3][:3]
    base = "_".join(words) if words else "template"
    return f"/auto_{base}"[:50]


@app.route("/api/templates/search")
@login_required
def search_templates_api():
    """Search shortcode templates for text expansion autocomplete."""
    query = (request.args.get("q") or "").strip()
    if len(query) > 80:
        query = query[:80]
    templates = fetch_message_templates(search_query=query, limit=12)
    return jsonify(
        [
            {
                "id": row["id"],
                "shortcode": row["shortcode"],
                "category": row.get("category") or "general",
                "preview": row.get("preview") or "",
                "usage_count": int(row.get("usage_count") or 0),
            }
            for row in templates
        ]
    )


@app.route("/api/templates/expand", methods=["POST"])
@login_required
def expand_template():
    """
    Expand template with transaction context.
    """
    payload = request.get_json(silent=True) or {}
    if not isinstance(payload, dict):
        payload = {}
    template_id = parse_optional_int(payload.get("template_id"))
    transaction_id = parse_optional_int(payload.get("transaction_id"))
    if not template_id:
        return jsonify({"success": False, "error": "template_id is required"}), 400

    template = get_message_template(template_id)
    if not template:
        return jsonify({"success": False, "error": "Template not found"}), 404

    if not transaction_id:
        route_match = re.search(r"/tc/transaction/(\d+)", request.referrer or "")
        if route_match:
            transaction_id = int(route_match.group(1))

    context = {}
    if transaction_id:
        try:
            context = build_message_template_context(transaction_id)
        except Exception:
            context = {}
    expanded_text, unfilled_vars = expand_message_template_text(template.get("template_text"), context)
    increment_message_template_usage(template_id)
    return jsonify(
        {
            "success": True,
            "text": expanded_text,
            "unfilled_vars": unfilled_vars,
            "template": {
                "id": template["id"],
                "shortcode": template.get("shortcode"),
                "category": template.get("category"),
            },
        }
    )


@app.route("/tc/templates", methods=["GET", "POST"])
@login_required
def tc_templates():
    """Manage shortcode text-expansion templates and smart suggestions."""
    ensure_message_templates_table()
    notice = (request.args.get("notice") or "").strip()
    notice_type = (request.args.get("notice_type") or "success").strip().lower()
    if notice_type not in {"success", "warning", "error"}:
        notice_type = "success"

    if request.method == "POST":
        action = (request.form.get("action") or "").strip().lower()
        next_notice = "Template action completed."
        next_type = "success"

        if action == "create":
            result = create_message_template(
                shortcode=request.form.get("shortcode"),
                template_text=request.form.get("template_text"),
                category=request.form.get("category"),
            )
            if result.get("success"):
                next_notice = "Template created."
            else:
                next_notice = result.get("error") or "Could not create template."
                next_type = "warning"
        elif action == "update":
            template_id = parse_optional_int(request.form.get("template_id"))
            if not template_id:
                next_notice = "Template ID is required."
                next_type = "warning"
            else:
                result = update_message_template(
                    template_id=template_id,
                    shortcode=request.form.get("shortcode"),
                    template_text=request.form.get("template_text"),
                    category=request.form.get("category"),
                )
                if result.get("success"):
                    next_notice = "Template updated."
                else:
                    next_notice = result.get("error") or "Could not update template."
                    next_type = "warning"
        elif action == "delete":
            template_id = parse_optional_int(request.form.get("template_id"))
            if not template_id:
                next_notice = "Template ID is required."
                next_type = "warning"
            else:
                delete_result = delete_message_template(template_id)
                if delete_result.get("success"):
                    next_notice = "Template deleted."
                    next_type = "success"
                else:
                    next_notice = delete_result.get("error") or "Template could not be deleted."
                    next_type = "warning"
        elif action == "create_from_suggestion":
            sample_text = (request.form.get("sample_text") or "").strip()
            shortcode = (request.form.get("suggested_shortcode") or "").strip() or _suggested_shortcode_from_text(sample_text)
            category = (request.form.get("category") or "general").strip().lower()
            result = create_message_template(shortcode=shortcode, template_text=sample_text, category=category)
            if result.get("success"):
                next_notice = "Template created from suggestion."
            else:
                next_notice = result.get("error") or "Could not create template from suggestion."
                next_type = "warning"
        else:
            next_notice = "Unknown template action."
            next_type = "warning"

        return redirect(url_for("tc_templates", notice=next_notice, notice_type=next_type))

    selected_category = (request.args.get("category") or "").strip().lower()
    search_query = (request.args.get("q") or "").strip()
    templates = fetch_message_templates(category=selected_category, search_query=search_query, limit=500)
    all_templates = fetch_message_templates(limit=500)
    suggestions = suggest_message_templates_from_history(limit=20)
    categories = sorted({(row.get("category") or "general").strip().lower() for row in all_templates} | {"general"})
    return render_template(
        "tc_templates.html",
        notice=notice,
        notice_type=notice_type,
        templates=templates,
        suggestions=suggestions,
        selected_category=selected_category,
        search_query=search_query,
        categories=categories,
    )


@app.route("/tc/batch-upload", methods=["GET"])
@login_required
def tc_batch_upload():
    """Render drag/drop batch document upload workspace."""
    cleanup_stale_batch_upload_staging()
    uploaded_by = (session.get("tc_username") or "margaret").strip().lower()
    pending_count = fetch_batch_upload_pending_count(uploaded_by)
    session["batch_upload_pending_count"] = pending_count

    notice = (request.args.get("notice") or "").strip()
    notice_type = (request.args.get("notice_type") or "success").strip().lower()
    if notice_type not in {"success", "warning", "error"}:
        notice_type = "success"

    transaction_rows = fetch_batch_upload_candidate_transactions(limit=500)
    transaction_options = []
    for row in transaction_rows:
        status_value = (row.get("status") or "").strip()
        transaction_options.append(
            {
                "id": row["id"],
                "property_address": row.get("property_address") or "",
                "status": status_value,
                "label": f"#{row['id']} - {row.get('property_address') or 'Unknown address'} ({status_value or 'UNKNOWN'})",
            }
        )

    doc_type_values = [doc for doc in DOCUMENT_CLASSIFICATION_OVERRIDE_TYPES if doc != "unknown"]
    doc_type_options = [{"value": doc, "label": document_type_label(doc)} for doc in doc_type_values]
    return render_template(
        "tc_batch_upload.html",
        notice=notice,
        notice_type=notice_type,
        pending_count=pending_count,
        transaction_options=transaction_options,
        doc_type_options=doc_type_options,
    )


@app.route("/tc/batch-upload/analyze", methods=["POST"])
@login_required
def analyze_batch_upload():
    """
    Analyze multiple uploaded documents and stage assignment suggestions.
    """
    cleanup_stale_batch_upload_staging()
    uploaded_by = (session.get("tc_username") or "margaret").strip().lower()
    files = [request.files[key] for key in sorted(request.files.keys()) if request.files.get(key)]
    if not files:
        return jsonify({"success": False, "error": "No files uploaded."}), 400
    if len(files) > BATCH_UPLOAD_MAX_FILES:
        return jsonify({"success": False, "error": f"Maximum {BATCH_UPLOAD_MAX_FILES} files per batch."}), 400

    clear_pending_batch_upload_staging(uploaded_by)
    batch_token = str(uuid4())
    candidate_transactions = fetch_batch_upload_candidate_transactions(limit=600)
    results = []

    for file in files:
        safe_filename = secure_filename(file.filename or "")
        if not safe_filename:
            results.append(
                {
                    "filename": "unnamed_file",
                    "confidence": "low",
                    "reason": "Missing filename",
                }
            )
            continue

        extension = file_extension(safe_filename)
        if extension not in ALLOWED_DOCUMENT_EXTENSIONS:
            results.append(
                {
                    "filename": safe_filename,
                    "confidence": "low",
                    "reason": "Invalid file type (allowed: PDF/JPG/PNG)",
                }
            )
            continue

        file_bytes = file.read() or b""
        file_size = len(file_bytes)
        if file_size <= 0:
            results.append(
                {
                    "filename": safe_filename,
                    "confidence": "low",
                    "reason": "File is empty",
                }
            )
            continue
        if file_size > MAX_FILE_SIZE:
            results.append(
                {
                    "filename": safe_filename,
                    "confidence": "low",
                    "reason": "File exceeds 16MB upload limit",
                }
            )
            continue

        temp_path = ""
        try:
            with tempfile.NamedTemporaryFile(suffix=f".{extension}", delete=False) as tmp:
                tmp.write(file_bytes)
                temp_path = tmp.name

            first_page_text = extract_text_from_first_page(file_bytes, extension)
            analysis = analyze_document_with_claude(first_page_text, safe_filename)
            transaction_match = find_matching_transaction(analysis, candidates=candidate_transactions)
            suggested_transaction_id = parse_optional_int(transaction_match.get("transaction_id"))
            suggested_document_type = normalize_document_type(analysis.get("document_type"), fallback="other")
            match_confidence = float(transaction_match.get("confidence") or 0)
            confidence_label = "high" if suggested_transaction_id and match_confidence >= 0.85 else "low"
            analysis_payload = {
                "analysis": analysis,
                "matching": transaction_match,
                "first_page_text": (first_page_text or "")[:12000],
            }
            stage_id = stage_batch_upload_record(
                batch_token=batch_token,
                uploaded_by=uploaded_by,
                original_filename=safe_filename,
                temp_path=temp_path,
                extension=extension,
                file_size=file_size,
                suggested_transaction_id=suggested_transaction_id,
                suggested_document_type=suggested_document_type,
                confidence_score=match_confidence,
                analysis_payload=analysis_payload,
            )
            if not stage_id:
                _cleanup_temp_file(temp_path)
                results.append(
                    {
                        "filename": safe_filename,
                        "confidence": "low",
                        "reason": "Failed to stage file for upload",
                    }
                )
                continue

            if confidence_label == "high":
                results.append(
                    {
                        "stage_id": stage_id,
                        "filename": safe_filename,
                        "transaction_id": suggested_transaction_id,
                        "property_address": transaction_match.get("property_address") or "",
                        "document_type": suggested_document_type,
                        "confidence": "high",
                        "method": transaction_match.get("method") or "auto_match",
                    }
                )
            else:
                results.append(
                    {
                        "stage_id": stage_id,
                        "filename": safe_filename,
                        "transaction_id": suggested_transaction_id,
                        "document_type": suggested_document_type,
                        "confidence": "low",
                        "reason": transaction_match.get("reason") or "Needs review",
                        "suggestions": transaction_match.get("possible_matches") or [],
                    }
                )
        except Exception as exc:
            _cleanup_temp_file(temp_path)
            log_system_error("batch_upload_analyze", str(exc))
            results.append(
                {
                    "filename": safe_filename,
                    "confidence": "low",
                    "reason": "Analysis failed - please assign manually",
                }
            )

    pending_count = fetch_batch_upload_pending_count(uploaded_by)
    session["batch_upload_pending_count"] = pending_count
    session["batch_upload_batch_token"] = batch_token
    return jsonify(
        {
            "success": True,
            "results": results,
            "batch_token": batch_token,
            "pending_count": pending_count,
        }
    )


@app.route("/tc/batch-upload/commit", methods=["POST"])
@login_required
def commit_batch_upload():
    """
    Commit approved batch uploads: S3 upload + DB records + task automation.
    """
    ensure_batch_upload_staging_table()
    payload = request.get_json(silent=True) or {}
    if not isinstance(payload, dict):
        payload = {}
    uploads = payload.get("uploads")
    if not isinstance(uploads, list) or not uploads:
        return jsonify({"success": False, "error": "No uploads provided."}), 400

    uploaded_by = (session.get("tc_username") or "margaret").strip().lower()
    successful = 0
    failed = 0
    tasks_completed = 0
    touched_stage_ids = set()

    for upload in uploads[: BATCH_UPLOAD_MAX_FILES * 3]:
        if not isinstance(upload, dict):
            failed += 1
            continue

        stage_id = parse_optional_int(upload.get("stage_id"))
        if not stage_id or stage_id in touched_stage_ids:
            failed += 1
            continue
        touched_stage_ids.add(stage_id)

        stage_row = fetch_staged_batch_upload_row(stage_id, uploaded_by)
        if not stage_row:
            failed += 1
            continue

        transaction_id = parse_optional_int(upload.get("transaction_id")) or parse_optional_int(stage_row.get("suggested_transaction_id"))
        document_type = normalize_document_type(
            upload.get("document_type") or stage_row.get("suggested_document_type"),
            fallback="other",
        )

        transaction = get_transaction_or_none(transaction_id) if transaction_id else None
        if not transaction:
            mark_batch_upload_stage_result(stage_id, "failed", error_text="Transaction not found")
            failed += 1
            continue

        temp_path = (stage_row.get("temp_path") or "").strip()
        if not temp_path or not os.path.exists(temp_path):
            mark_batch_upload_stage_result(stage_id, "failed", error_text="Staged file missing")
            failed += 1
            continue

        try:
            with open(temp_path, "rb") as staged_file:
                file_bytes = staged_file.read()
            extension = (stage_row.get("extension") or file_extension(stage_row.get("original_filename") or "") or "pdf").lower()
            generated_filename = build_smart_filename(
                document_type=document_type,
                property_address=transaction.get("property_address") or "",
                extension=extension,
            )
            s3_key = upload_document(
                file=io.BytesIO(file_bytes),
                transaction_id=transaction_id,
                document_type=document_type,
                filename=generated_filename,
            )
            if not s3_key:
                raise ValueError("S3 upload failed")

            file_size = len(file_bytes or b"")
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
                    generated_filename,
                    s3_key,
                    file_size,
                    uploaded_by,
                ),
            )
            if not document_id:
                raise ValueError("Document record save failed")

            analysis_payload = stage_row.get("analysis_payload")
            if isinstance(analysis_payload, str):
                try:
                    analysis_payload = json.loads(analysis_payload)
                except Exception:
                    analysis_payload = {}
            if not isinstance(analysis_payload, dict):
                analysis_payload = {}

            analysis = analysis_payload.get("analysis")
            if not isinstance(analysis, dict):
                analysis = {}
            extracted_data = analysis.get("extracted_data")
            if not isinstance(extracted_data, dict):
                extracted_data = {}
            first_page_text = (analysis_payload.get("first_page_text") or "")[:12000]

            post_actions = apply_document_post_upload_actions(
                transaction_id=transaction_id,
                document_type=document_type,
                first_page_text=first_page_text,
                key_info_extracted=extracted_data,
                uploaded_by=uploaded_by,
            )
            tasks_completed += len(post_actions.get("completed_task_ids") or [])
            update_transaction_from_batch_extracted_data(transaction_id, document_type, extracted_data)

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
            execute_query(
                """
                INSERT INTO communications (transaction_id, communication_type, contact_party, contact_name, summary, outcome)
                VALUES (%s, 'note', 'system', 'batch_upload', %s, %s)
                """,
                (
                    transaction_id,
                    "Batch upload committed",
                    (
                        f"stage_id={stage_id} doc_id={document_id} "
                        f"type={document_type} actions={post_actions.get('summary') or 'none'}"
                    )[:1800],
                ),
            )

            log_document_access(
                document_id=document_id,
                user_name=uploaded_by,
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

            mark_batch_upload_stage_result(stage_id, "completed", committed_document_id=document_id)
            _cleanup_temp_file(temp_path)
            successful += 1
        except Exception as exc:
            mark_batch_upload_stage_result(stage_id, "failed", error_text=str(exc))
            log_system_error("batch_upload_commit", str(exc), transaction_id=transaction_id)
            failed += 1

    execute_query(
        """
        DELETE FROM batch_upload_staging
        WHERE uploaded_by = %s
          AND status IN ('completed', 'failed')
        """,
        (uploaded_by,),
    )
    pending_count = fetch_batch_upload_pending_count(uploaded_by)
    session["batch_upload_pending_count"] = pending_count
    return jsonify(
        {
            "success": True,
            "successful": successful,
            "failed": failed,
            "tasks_completed": tasks_completed,
            "pending_count": pending_count,
        }
    )


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


@app.route("/tc/analytics")
@login_required
def tc_automation_analytics():
    """Render consolidated automation analytics dashboard."""
    notice = (request.args.get("notice") or "").strip()
    notice_type = (request.args.get("notice_type") or "success").strip().lower()
    if notice_type not in {"success", "warning", "error"}:
        notice_type = "success"

    metrics = build_automation_analytics_snapshot(reference_date=date.today())
    return render_template(
        "tc_automation_analytics.html",
        notice=notice,
        notice_type=notice_type,
        metrics=metrics,
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


def _morning_briefing_notice_type(value):
    normalized = (value or "success").strip().lower()
    return normalized if normalized in {"success", "warning", "error"} else "success"


def _morning_briefing_target_date(raw_value):
    parsed = parse_optional_date(raw_value)
    return parsed or date.today()


@app.route("/tc/morning-briefing", methods=["GET", "POST"])
@login_required
def tc_morning_briefing():
    """Interactive morning briefing workspace with configurable schedule."""
    ensure_morning_briefing_tables()
    notice = (request.args.get("notice") or "").strip()
    notice_type = _morning_briefing_notice_type(request.args.get("notice_type"))
    selected_date = _morning_briefing_target_date(request.args.get("date"))

    if request.method == "POST":
        action = (request.form.get("action") or "").strip().lower()
        selected_date = _morning_briefing_target_date(request.form.get("selected_date"))
        notice = "Morning briefing updated."
        notice_type = "success"
        if action == "update_settings":
            updated_settings = update_morning_briefing_settings(
                {
                    "enabled": parse_bool_value(request.form.get("enabled"), default=False),
                    "send_time": request.form.get("send_time"),
                    "recap_enabled": parse_bool_value(request.form.get("recap_enabled"), default=False),
                    "recap_time": request.form.get("recap_time"),
                    "timezone": request.form.get("timezone"),
                    "ai_enabled": parse_bool_value(request.form.get("ai_enabled"), default=False),
                },
                updated_by=session.get("tc_username", "margaret"),
            )
            notice = (
                f"Morning briefing settings saved "
                f"({updated_settings.get('send_time')} morning / {updated_settings.get('recap_time')} recap)."
            )
        elif action == "generate_now":
            result = generate_morning_briefing(
                force=True,
                send_messages=parse_bool_value(request.form.get("send_messages"), default=False),
            )
            if result.get("success"):
                selected_date = _morning_briefing_target_date(result.get("briefing_date"))
                notice = (
                    "Morning briefing generated."
                    if not result.get("reused_existing")
                    else "Morning briefing already existed; loaded latest."
                )
            else:
                notice = f"Morning briefing was not generated: {result.get('skipped') or result.get('error') or 'unknown'}"
                notice_type = "warning"
        elif action == "send_recap_now":
            result = generate_evening_recap(
                force=True,
                send_messages=parse_bool_value(request.form.get("send_messages"), default=False),
            )
            if result.get("success"):
                notice = "2 PM recap generated and delivered."
            else:
                notice = f"Recap was not generated: {result.get('skipped') or result.get('error') or 'unknown'}"
                notice_type = "warning"
        else:
            notice = "Unknown morning briefing action."
            notice_type = "warning"

        return redirect(
            url_for(
                "tc_morning_briefing",
                date=selected_date.isoformat(),
                notice=notice,
                notice_type=notice_type,
            )
        )

    settings = fetch_morning_briefing_settings()
    briefing = fetch_morning_briefing_by_date(selected_date)
    if not briefing:
        briefing = fetch_latest_morning_briefing(days_back=21)
    items = fetch_morning_briefing_items(briefing["id"], include_completed=True) if briefing else []

    for item in items:
        transaction_id = item.get("transaction_id")
        item["transaction_url"] = url_for("tc_transaction", transaction_id=transaction_id) if transaction_id else ""
        digits = re.sub(r"\D", "", item.get("contact_phone") or "")
        item["phone_link"] = f"tel:{digits}" if digits else ""
        item["sms_link"] = f"sms:{digits}" if digits else ""
        item["email_link"] = f"mailto:{item.get('contact_email')}" if item.get("contact_email") else ""
        item["priority_label"] = (item.get("priority") or "medium").title()
        item["status_label"] = (item.get("status") or "pending").replace("_", " ").title()
        item["deferred_label"] = format_date_label(item.get("deferred_to_date"))

    item_summary = {
        "pending_count": len([item for item in items if item.get("status") == "pending"]),
        "completed_count": len([item for item in items if item.get("status") == "completed"]),
        "deferred_count": len([item for item in items if item.get("status") == "deferred"]),
    }
    email_payload = (briefing or {}).get("payload", {}).get("email_version", {}) if briefing else {}
    return render_template(
        "tc_morning_briefing.html",
        notice=notice,
        notice_type=notice_type,
        settings=settings,
        selected_date=selected_date,
        briefing=briefing,
        briefing_email=email_payload,
        items=items,
        item_summary=item_summary,
    )


@app.route("/tc/morning-briefing/item/<int:item_id>/update", methods=["POST"])
@login_required
def update_morning_briefing_item_route(item_id):
    """Update completion state, notes, or defer date for a briefing item."""
    action = (request.form.get("action") or "").strip().lower()
    notes = (request.form.get("notes") or "").strip()
    selected_date = _morning_briefing_target_date(request.form.get("selected_date"))
    deferred_to = parse_optional_date(request.form.get("deferred_to_date"))

    if action == "complete":
        status = "completed"
    elif action == "defer":
        status = "deferred"
        if deferred_to is None:
            deferred_to = date.today() + timedelta(days=1)
    elif action == "reopen":
        status = "pending"
        deferred_to = None
    else:
        status = request.form.get("status") or "pending"

    ok = update_morning_briefing_item(
        item_id=item_id,
        status=status,
        notes=notes,
        deferred_to_date=deferred_to,
    )
    notice = "Briefing item updated." if ok else "Unable to update briefing item."
    notice_type = "success" if ok else "warning"
    return redirect(
        url_for(
            "tc_morning_briefing",
            date=selected_date.isoformat(),
            notice=notice,
            notice_type=notice_type,
        )
    )


@app.route("/tc/morning-briefing/item/<int:item_id>/move", methods=["POST"])
@login_required
def move_morning_briefing_item_route(item_id):
    """Move briefing item up/down in suggested task order."""
    direction = (request.form.get("direction") or "up").strip().lower()
    selected_date = _morning_briefing_target_date(request.form.get("selected_date"))
    moved = move_morning_briefing_item(item_id=item_id, direction=direction)
    notice = "Priority order updated." if moved else "Could not reorder this item."
    notice_type = "success" if moved else "warning"
    return redirect(
        url_for(
            "tc_morning_briefing",
            date=selected_date.isoformat(),
            notice=notice,
            notice_type=notice_type,
        )
    )


def _daily_plan_notice_type(value):
    normalized = (value or "success").strip().lower()
    return normalized if normalized in {"success", "warning", "error"} else "success"


def _daily_plan_target_date(raw_value):
    parsed = parse_optional_date(raw_value)
    return parsed or date.today()


@app.route("/tc/daily-plan", methods=["GET", "POST"])
@login_required
def tc_daily_plan():
    """Interactive daily plan with time blocks, reordering, and adaptive reshuffle."""
    ensure_daily_plan_tables()
    notice = (request.args.get("notice") or "").strip()
    notice_type = _daily_plan_notice_type(request.args.get("notice_type"))
    selected_date = _daily_plan_target_date(request.args.get("date"))

    if request.method == "POST":
        action = (request.form.get("action") or "").strip().lower()
        selected_date = _daily_plan_target_date(request.form.get("selected_date"))
        notice = "Daily plan updated."
        notice_type = "success"
        if action == "generate_now":
            result = generate_daily_plan(
                force=True,
                send_messages=parse_bool_value(request.form.get("send_messages"), default=False),
                sync_calendar=parse_bool_value(request.form.get("sync_calendar"), default=True),
            )
            if result.get("success"):
                selected_date = _daily_plan_target_date(result.get("plan_date"))
                notice = "Daily plan generated."
            else:
                notice = f"Daily plan was not generated: {result.get('error') or 'unknown'}"
                notice_type = "warning"
        elif action == "reorganize_now":
            plan = fetch_daily_plan_by_date(selected_date) or fetch_latest_daily_plan(days_back=7)
            if not plan:
                notice = "No daily plan available yet."
                notice_type = "warning"
            else:
                result = reorganize_remaining_day(
                    plan_id=plan["id"],
                    reason="manual_reorganize",
                    updated_by=session.get("tc_username", "margaret"),
                )
                if result.get("success"):
                    notice = "Remaining day has been reorganized."
                else:
                    notice = f"Could not reorganize plan: {result.get('error') or 'unknown'}"
                    notice_type = "warning"
        else:
            notice = "Unknown daily plan action."
            notice_type = "warning"

        return redirect(
            url_for(
                "tc_daily_plan",
                date=selected_date.isoformat(),
                notice=notice,
                notice_type=notice_type,
            )
        )

    plan = fetch_daily_plan_by_date(selected_date)
    if not plan:
        plan = fetch_latest_daily_plan(days_back=30)
    if plan and plan.get("plan_date"):
        selected_date = plan.get("plan_date")
    blocks = fetch_daily_plan_blocks(plan["id"]) if plan else []
    items = fetch_daily_plan_items(plan["id"], include_completed=True) if plan else []

    items_by_block = {}
    for item in items:
        item["transaction_url"] = (
            url_for("tc_transaction", transaction_id=item.get("transaction_id"))
            if item.get("transaction_id")
            else ""
        )
        tier = (item.get("priority_tier") or "").strip().lower()
        item["tier_class"] = f"tier-{tier or 'routine'}"
        item["is_completed"] = item.get("status") == "completed"
        item["status_label"] = (item.get("status") or "pending").replace("_", " ").title()
        block_id = int(item.get("block_id") or 0)
        items_by_block.setdefault(block_id, []).append(item)

    tier_color_map = {
        "critical": "#ef4444",
        "high_priority": "#f97316",
        "batch_able": "#2563eb",
        "routine": "#6b7280",
        "buffer": "#7c3aed",
        "break": "#16a34a",
    }
    for block in blocks:
        block_id = int(block.get("id") or 0)
        block["tasks"] = items_by_block.get(block_id, [])
        block["start_label"] = (
            block.get("start_time").strftime("%I:%M %p").lstrip("0")
            if isinstance(block.get("start_time"), datetime)
            else ""
        )
        block["end_label"] = (
            block.get("end_time").strftime("%I:%M %p").lstrip("0")
            if isinstance(block.get("end_time"), datetime)
            else ""
        )
        block["tier_class"] = f"tier-{(block.get('tier') or 'routine').lower()}"
        block["accent_color"] = tier_color_map.get((block.get("tier") or "").lower(), "#6b7280")

    item_summary = {
        "pending_count": len([item for item in items if item.get("status") == "pending"]),
        "completed_count": len([item for item in items if item.get("status") == "completed"]),
        "deferred_count": len([item for item in items if item.get("status") == "deferred"]),
    }
    learning_metrics = fetch_daily_plan_learning_metrics(days=45)
    return render_template(
        "tc_daily_plan.html",
        notice=notice,
        notice_type=notice_type,
        selected_date=selected_date,
        plan=plan,
        blocks=blocks,
        items=items,
        item_summary=item_summary,
        learning_metrics=learning_metrics,
    )


@app.route("/tc/daily-plan/item/<int:item_id>/update", methods=["POST"])
@login_required
def update_daily_plan_item_route(item_id):
    """Update one daily-plan task status/notes with live estimated end-time refresh."""
    payload = request.get_json(silent=True) or request.form or {}
    status = (payload.get("status") or "").strip().lower() or None
    notes = (payload.get("notes") or "").strip() if payload.get("notes") is not None else None
    actual_minutes_raw = payload.get("actual_minutes")
    actual_minutes = None
    if actual_minutes_raw not in (None, ""):
        try:
            actual_minutes = max(1, int(actual_minutes_raw))
        except (TypeError, ValueError):
            actual_minutes = None
    started_now = parse_bool_value(payload.get("started_now"), default=False)
    completed_now = parse_bool_value(payload.get("completed_now"), default=False)

    updated = update_daily_plan_item(
        item_id=item_id,
        status=status,
        notes=notes,
        actual_minutes=actual_minutes,
        started_now=started_now,
        completed_now=completed_now,
        updated_by=session.get("tc_username", "margaret"),
    )
    if not updated:
        return jsonify({"success": False, "error": "item_not_found"}), 404

    remaining_rows = execute_query(
        """
        SELECT COALESCE(SUM(estimated_minutes), 0) AS remaining_minutes
        FROM daily_plan_items
        WHERE plan_id = %s
          AND status <> 'completed'
        """,
        (int(updated.get("plan_id") or 0),),
        fetch=True,
    ) or []
    remaining_minutes = int((remaining_rows[0] or {}).get("remaining_minutes") or 0) if remaining_rows else 0
    estimated_end = datetime.now() + timedelta(minutes=remaining_minutes + 30)
    return jsonify(
        {
            "success": True,
            "item": {
                "id": updated.get("id"),
                "status": updated.get("status"),
                "status_label": (updated.get("status") or "pending").replace("_", " ").title(),
                "actual_minutes": updated.get("actual_minutes"),
                "notes": updated.get("notes") or "",
            },
            "remaining_minutes": remaining_minutes,
            "estimated_end_time": estimated_end.strftime("%I:%M %p"),
        }
    )


@app.route("/tc/daily-plan/reorder", methods=["POST"])
@login_required
def reorder_daily_plan_route():
    """Persist drag-drop ordering updates for daily-plan tasks."""
    payload = request.get_json(silent=True) or {}
    plan_id = payload.get("plan_id")
    ordered_item_ids = payload.get("ordered_item_ids") or []
    try:
        plan_id = int(plan_id)
    except (TypeError, ValueError):
        return jsonify({"success": False, "error": "invalid_plan_id"}), 400

    ok = reorder_daily_plan_items(
        plan_id=plan_id,
        ordered_item_ids=ordered_item_ids,
        updated_by=session.get("tc_username", "margaret"),
    )
    if not ok:
        return jsonify({"success": False, "error": "reorder_failed"}), 400
    return jsonify({"success": True})


@app.route("/tc/daily-plan/reorganize", methods=["POST"])
@login_required
def reorganize_daily_plan_route():
    """Adaptive reshuffle for remaining day when new urgency appears."""
    payload = request.get_json(silent=True) or {}
    plan_id = payload.get("plan_id")
    reason = (payload.get("reason") or "running_behind").strip().lower()
    try:
        plan_id = int(plan_id)
    except (TypeError, ValueError):
        return jsonify({"success": False, "error": "invalid_plan_id"}), 400
    result = reorganize_remaining_day(
        plan_id=plan_id,
        reason=reason,
        updated_by=session.get("tc_username", "margaret"),
    )
    if not result.get("success"):
        return jsonify({"success": False, "error": result.get("error") or "reorganize_failed"}), 400
    return jsonify(result)


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
    party_portal_links = fetch_party_portal_link_map(transaction_id)
    party_portal_analytics = fetch_party_portal_analytics(transaction_id)

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

    ensure_date_cascade_tables()
    date_cascade_history = fetch_recent_date_cascade_logs(transaction_id, limit=12)
    date_cascade_fields = []
    for field_name in sorted(DATE_CASCADE_SUPPORTED_FIELDS):
        field_value = transaction.get(field_name)
        date_cascade_fields.append(
            {
                "field": field_name,
                "label": field_name.replace("_", " ").title(),
                "value": field_value.isoformat() if isinstance(field_value, date) else "",
            }
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
        party_portal_links=party_portal_links,
        party_portal_analytics=party_portal_analytics,
        analysis_overview={
            "total_analyzed": len(analysis_rows),
            "pending_review_count": analysis_pending_review_count,
            "action_item_count": analysis_action_item_count,
        },
        date_cascade_fields=date_cascade_fields,
        date_cascade_history=date_cascade_history,
        document_classification_types=DOCUMENT_CLASSIFICATION_OVERRIDE_TYPES,
        common_qa_categories=COMMON_QA_CATEGORY_OPTIONS,
    )


@app.route("/tc/transaction/<int:transaction_id>/update-date", methods=["POST"])
@login_required
def update_transaction_date(transaction_id):
    """
    Update a key transaction date and cascade dependent changes.
    Supports preview mode when payload includes preview_only=true.
    """
    ensure_date_cascade_tables()
    transaction = get_transaction_or_none(transaction_id)
    if not transaction:
        return jsonify({"success": False, "error": "Transaction not found"}), 404
    if (transaction.get("status") or "").upper() in {"COMPLETED", "CANCELLED"}:
        return jsonify({"success": False, "error": "Transaction cannot be modified"}), 400

    payload = request.get_json(silent=True) or {}
    if not isinstance(payload, dict):
        payload = {}

    date_field = (payload.get("field") or "").strip().lower()
    if date_field not in DATE_CASCADE_SUPPORTED_FIELDS:
        return jsonify({"success": False, "error": "Unsupported date field"}), 400

    provided_old_date = _parse_iso_date(payload.get("old_date"))
    current_old_date = transaction.get(date_field)
    old_date = provided_old_date or current_old_date
    if not isinstance(old_date, date):
        return jsonify({"success": False, "error": "Old date is required"}), 400

    new_date = _parse_iso_date(payload.get("new_date"))
    if not isinstance(new_date, date):
        return jsonify({"success": False, "error": "New date is required (YYYY-MM-DD)"}), 400

    delta_days = (new_date - old_date).days
    cascade_options = normalize_date_cascade_options(payload.get("cascade_options"))
    preview_only = parse_bool_value(payload.get("preview_only"), default=False)
    force_apply = parse_bool_value(payload.get("force"), default=False)

    stale_warning = None
    if isinstance(current_old_date, date) and current_old_date != old_date:
        stale_warning = (
            f"Current {date_field} is {current_old_date.isoformat()}, "
            f"but request expected {old_date.isoformat()}."
        )

    estimate = estimate_date_cascade_changes(
        transaction_id=transaction_id,
        date_field=date_field,
        delta_days=delta_days,
        cascade_options=cascade_options,
        old_date=old_date,
        new_date=new_date,
    )
    if stale_warning:
        estimate_conflicts = estimate.get("conflicts") if isinstance(estimate.get("conflicts"), list) else []
        estimate_conflicts.insert(0, {"severity": "warning", "message": stale_warning})
        estimate["conflicts"] = estimate_conflicts
        estimate["requires_confirmation"] = True

    if preview_only:
        return jsonify({"success": True, "preview": estimate})

    if delta_days == 0 and isinstance(current_old_date, date) and current_old_date == new_date:
        return jsonify(
            {
                "success": True,
                "changes": {
                    "deadlines_updated": 0,
                    "tasks_updated": 0,
                    "appointments_updated": 0,
                    "calendar_events_updated": 0,
                    "notifications_sent": 0,
                },
                "notifications_sent": 0,
                "delta_days": 0,
                "cascade_log_id": None,
            }
        )

    if estimate.get("requires_confirmation") and not force_apply:
        return jsonify(
            {
                "success": False,
                "error": "confirmation_required",
                "message": "Date change requires confirmation due to detected conflicts.",
                "preview": estimate,
                "requires_confirmation": True,
            }
        ), 409

    execute_query(
        f"""
        UPDATE transactions
        SET {date_field} = %s,
            updated_at = CURRENT_TIMESTAMP
        WHERE id = %s
        """,
        (new_date, int(transaction_id)),
    )

    cascade_result = cascade_date_change(
        transaction_id=transaction_id,
        date_field=date_field,
        delta_days=delta_days,
        old_date=old_date,
        new_date=new_date,
        cascade_options=cascade_options,
        initiated_by=session.get("tc_username", "margaret"),
    )
    changes = cascade_result.get("changes") if isinstance(cascade_result.get("changes"), dict) else {}
    if not changes:
        changes = {
            "deadlines_updated": 0,
            "tasks_updated": 0,
            "appointments_updated": 0,
            "calendar_events_updated": 0,
            "notifications_sent": 0,
        }

    notification_result = notify_date_change(
        transaction_id=transaction_id,
        date_field=date_field,
        old_date=old_date,
        new_date=new_date,
        cascade_results=changes,
        send_notifications=cascade_options.get("notify_parties", True),
        is_undo=False,
    )
    changes["notifications_sent"] = int(notification_result.get("notifications_sent") or 0)
    if notification_result.get("timeline_url"):
        changes["timeline_url"] = notification_result.get("timeline_url")

    cascade_log_id = record_date_cascade_log(
        transaction_id=transaction_id,
        date_field=date_field,
        old_date=old_date,
        new_date=new_date,
        delta_days=delta_days,
        cascade_options=cascade_options,
        snapshot=cascade_result.get("snapshot"),
        results=changes,
        initiated_by=session.get("tc_username", "margaret"),
    )
    execute_query(
        """
        INSERT INTO communications (transaction_id, communication_type, contact_party, contact_name, summary, outcome)
        VALUES (%s, 'note', 'system', 'date_cascade', %s, %s)
        """,
        (
            int(transaction_id),
            "Transaction date cascade applied",
            (
                f"field={date_field} old={old_date.isoformat()} new={new_date.isoformat()} delta={delta_days} "
                f"deadlines={int(changes.get('deadlines_updated') or 0)} "
                f"tasks={int(changes.get('tasks_updated') or 0)} "
                f"calendar={int(changes.get('calendar_events_updated') or 0)} "
                f"notifications={int(changes.get('notifications_sent') or 0)}"
            ),
        ),
    )
    return jsonify(
        {
            "success": True,
            "changes": changes,
            "notifications_sent": int(changes.get("notifications_sent") or 0),
            "delta_days": delta_days,
            "cascade_log_id": cascade_log_id,
        }
    )


@app.route("/tc/transaction/<int:transaction_id>/update-date/undo", methods=["POST"])
@login_required
def undo_transaction_date_change(transaction_id):
    """Undo a cascaded date change within the 24-hour window."""
    ensure_date_cascade_tables()
    transaction = get_transaction_or_none(transaction_id)
    if not transaction:
        return jsonify({"success": False, "error": "Transaction not found"}), 404

    payload = request.get_json(silent=True) or {}
    if not isinstance(payload, dict):
        payload = {}
    cascade_log_id = parse_optional_int(payload.get("cascade_log_id"))
    if not cascade_log_id:
        rows = execute_query(
            """
            SELECT id
            FROM transaction_date_cascade_log
            WHERE transaction_id = %s
              AND undone_at IS NULL
              AND expires_at >= CURRENT_TIMESTAMP
            ORDER BY created_at DESC, id DESC
            LIMIT 1
            """,
            (int(transaction_id),),
            fetch=True,
        ) or []
        if rows:
            cascade_log_id = rows[0]["id"]

    if not cascade_log_id:
        return jsonify({"success": False, "error": "No undoable date change found"}), 404

    result = undo_date_cascade_change(transaction_id=transaction_id, cascade_log_id=cascade_log_id)
    if not result.get("success"):
        error = result.get("error") or "undo_failed"
        status_code = 409 if error in {"already_undone", "undo_window_expired"} else 400
        return jsonify({"success": False, "error": error}), status_code

    execute_query(
        """
        INSERT INTO communications (transaction_id, communication_type, contact_party, contact_name, summary, outcome)
        VALUES (%s, 'note', 'system', 'date_cascade', %s, %s)
        """,
        (
            int(transaction_id),
            "Date cascade undo applied",
            f"cascade_log_id={cascade_log_id}",
        ),
    )
    return jsonify(
        {
            "success": True,
            "cascade_log_id": cascade_log_id,
            "undo_summary": result.get("undo_summary") or {},
        }
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


def fetch_party_portal_link_map(transaction_id):
    """Resolve buyer/seller/agent party portal links for transaction view."""
    link_map = {
        "buyer": {"exists": False, "link": "", "email": "", "last_accessed_label": "", "expires_at_label": ""},
        "seller": {"exists": False, "link": "", "email": "", "last_accessed_label": "", "expires_at_label": ""},
        "agent": {"exists": False, "link": "", "email": "", "last_accessed_label": "", "expires_at_label": ""},
    }
    for row in list_party_portal_access(transaction_id):
        role = (row.get("party_type") or "").strip().lower()
        if role not in link_map:
            continue
        link_map[role] = {
            "exists": bool(row.get("is_active")),
            "link": row.get("portal_url") or "",
            "email": row.get("email") or "",
            "last_accessed_label": format_timestamp_label(row.get("last_accessed_at")),
            "expires_at_label": format_timestamp_label(row.get("expires_at")),
        }
    return link_map


@app.route("/tc/transaction/<int:transaction_id>/generate-portals", methods=["POST"])
@login_required
def generate_party_portals(transaction_id):
    """
    Create unique secure access tokens for buyer, seller, and agent portals.
    """
    ensure_party_portal_tables()
    transaction = get_transaction_or_none(transaction_id)
    if not transaction:
        return jsonify({"success": False, "error": "transaction_not_found"}), 404

    payload = request.get_json(silent=True) or {}
    buyer_email = normalize_email(payload.get("buyer_email") or request.form.get("buyer_email") or "")
    seller_email = normalize_email(payload.get("seller_email") or request.form.get("seller_email") or "")
    agent_email = normalize_email(payload.get("agent_email") or request.form.get("agent_email") or transaction.get("agent_email") or "")
    if buyer_email and not is_email_valid(buyer_email):
        buyer_email = ""
    if seller_email and not is_email_valid(seller_email):
        seller_email = ""
    if agent_email and not is_email_valid(agent_email):
        agent_email = normalize_email(transaction.get("agent_email") or "")

    buyer_token = str(uuid4())
    seller_token = str(uuid4())
    agent_token = str(uuid4())

    buyer_row = create_portal_access(
        transaction_id=transaction_id,
        party_type="buyer",
        access_token=buyer_token,
        email=(buyer_email or None),
    )
    seller_row = create_portal_access(
        transaction_id=transaction_id,
        party_type="seller",
        access_token=seller_token,
        email=(seller_email or None),
    )
    agent_row = create_portal_access(
        transaction_id=transaction_id,
        party_type="agent",
        access_token=agent_token,
        email=(agent_email or None),
    )
    if not (buyer_row and seller_row and agent_row):
        return jsonify({"success": False, "error": "portal_generation_failed"}), 500

    send_summary = send_portal_links(
        transaction_id=transaction_id,
        portal_tokens={
            "buyer": buyer_token,
            "seller": seller_token,
            "agent": agent_token,
        },
    )
    portal_payload = {
        "buyer": build_party_portal_url(buyer_token),
        "seller": build_party_portal_url(seller_token),
        "agent": build_party_portal_url(agent_token),
    }
    execute_query(
        """
        INSERT INTO communications (transaction_id, communication_type, contact_party, contact_name, summary, outcome)
        VALUES (%s, 'note', 'system', %s, %s, %s)
        """,
        (
            int(transaction_id),
            session.get("tc_username", "margaret"),
            "Party portal links generated",
            (
                f"sms_sent={int(send_summary.get('sent_sms') or 0)} "
                f"email_sent={int(send_summary.get('sent_email') or 0)}"
            ),
        ),
    )
    wants_json = request.is_json or "application/json" in (request.headers.get("Accept") or "").lower()
    if wants_json:
        return jsonify(
            {
                "success": True,
                "portals": portal_payload,
                "sent_sms": int(send_summary.get("sent_sms") or 0),
                "sent_email": int(send_summary.get("sent_email") or 0),
            }
        )

    redirect_url = url_for(
        "tc_transaction",
        transaction_id=transaction_id,
        doc_notice=(
            f"Party portals generated. Sent via {int(send_summary.get('sent_sms') or 0)} SMS and "
            f"{int(send_summary.get('sent_email') or 0)} email channels."
        ),
        doc_notice_type="success",
    )
    return redirect(redirect_url)


@app.route("/portal/<access_token>")
def party_portal(access_token):
    """Display personalized self-service portal for buyer/seller/agent."""
    ensure_party_portal_tables()
    ip_address = request.remote_addr or ""
    if _portal_rate_limited(access_token, ip_address):
        log_portal_access(
            portal_access_id=None,
            transaction_id=None,
            party_type="",
            access_token=access_token,
            event_type="rate_limited",
            section_name="overview",
            success=False,
            details={"ip": ip_address},
        )
        return render_template("portal_invalid.html", reason="Too many requests. Please try again shortly."), 429

    portal_access = get_portal_access(access_token, touch=True)
    if not portal_access:
        log_portal_access(
            portal_access_id=None,
            transaction_id=None,
            party_type="",
            access_token=access_token,
            event_type="invalid_access",
            section_name="overview",
            success=False,
            details={"ip": ip_address},
        )
        return render_template("portal_invalid.html", reason="This portal link is invalid or expired."), 404

    transaction = get_transaction_or_none(portal_access["transaction_id"])
    if not transaction:
        return render_template("portal_invalid.html", reason="Transaction not found."), 404

    section = (request.args.get("section") or "overview").strip().lower()
    if section not in PORTAL_SECTION_NAMES:
        section = "overview"

    session["party_portal_token"] = portal_access["access_token"]
    session["party_portal_access_id"] = int(portal_access["id"])
    session["party_portal_transaction_id"] = int(portal_access["transaction_id"])
    session["party_portal_party_type"] = portal_access["party_type"]

    log_portal_access(
        portal_access_id=portal_access["id"],
        transaction_id=portal_access["transaction_id"],
        party_type=portal_access["party_type"],
        access_token=access_token,
        event_type="view",
        section_name=section,
        success=True,
    )
    portal_data = build_portal_data(transaction, portal_access["party_type"], access_token=access_token)
    can_upload = bool(portal_access.get("party_type") == "agent")
    return render_template(
        "party_portal.html",
        transaction=transaction,
        party_type=portal_access["party_type"],
        data=portal_data,
        can_upload=can_upload,
        access_token=access_token,
        active_section=section,
    )


@app.route("/portal/<access_token>/track-section", methods=["POST"])
def track_party_portal_section(access_token):
    """Record client-side section-view analytics for party portal."""
    ensure_party_portal_tables()
    portal_access = get_portal_access(access_token, touch=False)
    if not portal_access:
        return jsonify({"success": False, "error": "invalid_portal"}), 404
    section = (request.get_json(silent=True) or {}).get("section") or request.form.get("section") or "overview"
    section = section.strip().lower()
    if section not in PORTAL_SECTION_NAMES:
        section = "overview"
    log_portal_access(
        portal_access_id=portal_access["id"],
        transaction_id=portal_access["transaction_id"],
        party_type=portal_access["party_type"],
        access_token=access_token,
        event_type="section_view",
        section_name=section,
        success=True,
    )
    return jsonify({"success": True})


@app.route("/portal/document/<int:document_id>")
def party_portal_document(document_id):
    """Serve one allowed document from party portal token/session context."""
    ensure_party_portal_tables()
    access_token = (request.args.get("token") or session.get("party_portal_token") or "").strip()
    if not access_token:
        return "Missing portal token.", 403
    ip_address = request.remote_addr or ""
    if _portal_rate_limited(access_token, ip_address):
        return "Rate limit exceeded. Try again later.", 429
    portal_access = get_portal_access(access_token, touch=False)
    if not portal_access:
        return "Portal link is invalid or expired.", 404
    transaction = get_transaction_or_none(portal_access["transaction_id"])
    if not transaction:
        return "Transaction not found.", 404

    allowed_documents = _documents_for_portal_party(transaction, portal_access["party_type"], access_token)
    allowed_by_id = {
        int(row["id"]): row
        for row in allowed_documents
        if row.get("available") and row.get("id") is not None
    }
    if int(document_id) not in allowed_by_id:
        return "You do not have access to this document.", 403

    if int(document_id) == 0:
        if not transaction.get("contract_s3_key"):
            return "Document not available.", 404
        s3_key = transaction.get("contract_s3_key")
        download_name = "contract.pdf"
    else:
        doc_rows = execute_query(
            """
            SELECT id, transaction_id, filename, s3_key
            FROM documents
            WHERE id = %s
              AND transaction_id = %s
            LIMIT 1
            """,
            (int(document_id), int(transaction["id"])),
            fetch=True,
        ) or []
        if not doc_rows:
            return "Document not found.", 404
        s3_key = doc_rows[0].get("s3_key")
        download_name = doc_rows[0].get("filename") or f"document_{document_id}"

    url = get_presigned_url(s3_key, expiration=1800, download_filename=download_name)
    if not url:
        return "Failed to access document.", 500

    log_portal_access(
        portal_access_id=portal_access["id"],
        transaction_id=portal_access["transaction_id"],
        party_type=portal_access["party_type"],
        access_token=access_token,
        event_type="document_download",
        section_name="documents",
        document_id=document_id if document_id else None,
        success=True,
    )
    if document_id:
        log_document_access(
            document_id=int(document_id),
            user_name=f"portal_{portal_access['party_type']}",
            user_type="portal",
            action="download",
            ip_address=ip_address,
        )
    return redirect(url)


@app.route("/portal/<access_token>/upload", methods=["POST"])
def party_portal_upload(access_token):
    """Allow only agent portal users to upload files."""
    ensure_party_portal_tables()
    ip_address = request.remote_addr or ""
    if _portal_rate_limited(access_token, ip_address):
        return jsonify({"success": False, "error": "rate_limited"}), 429
    portal_access = get_portal_access(access_token, touch=False)
    if not portal_access:
        return jsonify({"success": False, "error": "invalid_portal"}), 404
    if portal_access.get("party_type") != "agent":
        return jsonify({"success": False, "error": "upload_not_allowed"}), 403
    transaction = get_transaction_or_none(portal_access["transaction_id"])
    if not transaction:
        return jsonify({"success": False, "error": "transaction_not_found"}), 404

    uploaded_files = []
    for key in request.files:
        file_items = request.files.getlist(key)
        for file_item in file_items:
            if file_item and file_item.filename:
                uploaded_files.append(file_item)
    if not uploaded_files:
        return jsonify({"success": False, "error": "no_files"}), 400
    if len(uploaded_files) > 20:
        return jsonify({"success": False, "error": "too_many_files", "max": 20}), 400

    selected_type = normalize_document_type(request.form.get("document_type"), fallback="other")
    valid_upload_types = CLIENT_UPLOAD_DOCUMENT_TYPES | REQUIRED_DOCUMENT_TYPES
    if selected_type not in valid_upload_types:
        selected_type = "other"

    successful = 0
    failed = 0
    uploaded_doc_ids = []
    for file in uploaded_files:
        safe_filename = secure_filename(file.filename or "")
        extension = file_extension(safe_filename)
        if extension not in ALLOWED_DOCUMENT_EXTENSIONS:
            failed += 1
            continue
        file_bytes = file.read()
        file_size = len(file_bytes or b"")
        if file_size <= 0 or file_size > MAX_FILE_SIZE:
            failed += 1
            continue

        processed = process_uploaded_document(
            file_bytes=file_bytes,
            transaction_id=transaction["id"],
            uploaded_by="portal_agent",
            original_filename=safe_filename,
            extension=extension,
            transaction_context=transaction,
            suggested_document_type=selected_type,
        )
        if not processed.get("success"):
            failed += 1
            continue

        final_document_type = normalize_document_type(processed.get("document_type"), fallback=selected_type)
        document_id = execute_insert(
            """
            INSERT INTO documents (
                transaction_id, document_type, filename, s3_key, file_size, uploaded_by, uploaded_at
            ) VALUES (%s, %s, %s, %s, %s, %s, CURRENT_TIMESTAMP)
            RETURNING id
            """,
            (
                int(transaction["id"]),
                final_document_type,
                processed.get("filename") or safe_filename,
                processed.get("s3_key"),
                file_size,
                "portal_agent",
            ),
        )
        if not document_id:
            failed += 1
            continue

        uploaded_doc_ids.append(document_id)
        key_info = (processed.get("analysis") or {}).get("key_info_extracted")
        apply_document_post_upload_actions(
            transaction_id=transaction["id"],
            document_type=final_document_type,
            first_page_text=processed.get("first_page_text") or "",
            key_info_extracted=(key_info if isinstance(key_info, dict) else {}),
            uploaded_by="portal_agent",
        )
        run_document_analysis_async(
            document_id=document_id,
            transaction_id=transaction["id"],
            document_type=final_document_type,
            s3_key=processed.get("s3_key"),
            extension=extension,
        )
        successful += 1

    log_portal_access(
        portal_access_id=portal_access["id"],
        transaction_id=portal_access["transaction_id"],
        party_type=portal_access["party_type"],
        access_token=access_token,
        event_type="upload",
        section_name="upload",
        success=successful > 0,
        details={"successful": successful, "failed": failed, "document_ids": uploaded_doc_ids[:20]},
    )
    return jsonify(
        {
            "success": successful > 0,
            "uploaded": successful,
            "failed": failed,
            "document_ids": uploaded_doc_ids,
        }
    )


@app.route("/tc/transaction/<int:transaction_id>/portal-analytics")
@login_required
def tc_transaction_portal_analytics(transaction_id):
    """Return portal engagement analytics for one transaction."""
    transaction = get_transaction_or_none(transaction_id)
    if not transaction:
        return jsonify({"success": False, "error": "transaction_not_found"}), 404
    return jsonify({"success": True, "analytics": fetch_party_portal_analytics(transaction_id)})


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
