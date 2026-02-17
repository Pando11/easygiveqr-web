import os
import re
from datetime import date, datetime, timedelta
from functools import wraps
from typing import Any

import stripe
from dotenv import load_dotenv
from flask import Flask, jsonify, redirect, render_template, request, session, url_for
from twilio.twiml.messaging_response import MessagingResponse
from werkzeug.security import check_password_hash
from werkzeug.utils import secure_filename

from config import Config
from utils.db import execute_insert, execute_query
from utils.payments import calculate_payment_breakdown
from utils.s3 import get_presigned_url, log_document_access, upload_contract, upload_document
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
               lender_name, title_company, payment_upfront_paid, payment_upfront_date,
               payment_closing_paid, payment_closing_date, created_at, updated_at
        FROM transactions
        WHERE id = %s
        """,
        (transaction_id,),
        fetch=True,
    ) or []
    return rows[0] if rows else None


@app.route("/")
def index():
    """Agent upload form."""
    return render_template("upload.html")


@app.route("/health")
def health():
    """Basic health check for Railway and uptime monitors."""
    return jsonify({"ok": True, "service": "maverick-tc"})


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


@app.route("/tc/checklist")
@login_required
def tc_daily_checklist():
    """Simple daily checklist page with manual reminder actions."""
    deadlines = execute_query(
        """
        SELECT d.id, d.deadline_type, d.deadline_date, d.completed,
               t.property_address, t.agent_name
        FROM deadlines d
        JOIN transactions t ON t.id = d.transaction_id
        WHERE t.status = 'ACTIVE'
          AND d.completed = FALSE
        ORDER BY d.deadline_date ASC
        LIMIT 100
        """,
        fetch=True,
    ) or []
    return render_template("tc_daily_checklist.html", deadlines=deadlines, today=date.today())


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

    transaction["has_contract_pdf"] = bool(transaction.get("contract_s3_key"))
    transaction["upload_time_ago"] = format_time_ago(transaction.get("created_at"))
    transaction["uploaded_at_label"] = (
        transaction["created_at"].strftime("%b %d, %Y %I:%M %p") if transaction.get("created_at") else "Unknown"
    )

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
    missing_document_types = sorted(REQUIRED_DOCUMENT_TYPES - uploaded_document_types)

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
        documents=documents,
        missing_document_types=missing_document_types,
        timeline=timeline,
        task_preview=task_preview,
        task_total=task_total,
        communications=communications,
        payment_context=payment_context,
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


@app.route("/tc/transaction/<int:transaction_id>/approve", methods=["POST"])
@login_required
def approve_transaction(transaction_id):
    """Approve a reviewed transaction and activate full workflow artifacts."""
    transaction = get_transaction_or_none(transaction_id)
    if not transaction:
        return "Transaction not found", 404
    if transaction.get("status") in {"COMPLETED", "CANCELLED"}:
        return "This transaction cannot be approved.", 400

    try:
        effective_date_value = parse_required_date(request.form.get("effective_date"), "Effective date")
        earnest_due_date_value = parse_required_date(request.form.get("earnest_due_date"), "Earnest money due")
        option_period_end_value = parse_required_date(request.form.get("option_period_end_date"), "Option period end")
        financing_approval_value = parse_required_date(
            request.form.get("financing_approval_date"), "Financing approval"
        )
        closing_date_value = parse_required_date(request.form.get("closing_date"), "Closing date")
    except ValueError as exc:
        return str(exc), 400

    buyer_name = request.form.get("buyer_name", "").strip()
    buyer_phone = normalize_phone(request.form.get("buyer_phone", "").strip())
    seller_name = request.form.get("seller_name", "").strip()
    seller_phone = normalize_phone(request.form.get("seller_phone", "").strip())
    lender_name = request.form.get("lender_name", "").strip()
    title_company = request.form.get("title_company", "").strip()

    if not buyer_name:
        return "Buyer name is required.", 400
    if not seller_name:
        return "Seller name is required.", 400
    if not title_company:
        return "Title company is required.", 400
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
            title_company = %s,
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
            title_company,
            transaction_id,
        ),
    )
    if not updated:
        return "Failed to activate transaction.", 500

    if not create_deadlines(transaction_id, deadline_dates):
        return "Failed to create deadlines.", 500
    if not create_tasks(transaction_id, effective_date_value, closing_date_value):
        return "Failed to create tasks.", 500

    transaction["id"] = transaction_id
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

    log_document_access(
        document_id=document_id,
        user_name=session.get("tc_username", "margaret"),
        user_type="tc",
        action="upload",
        ip_address=request.remote_addr or "",
    )
    return redirect(f"{url_for('tc_transaction', transaction_id=transaction_id)}#documents")


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
        amount_marked = calculate_payment_breakdown(transaction, "upfront")["amount"]
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
        amount_marked = calculate_payment_breakdown(transaction, "closing")["amount"]

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

        confirmation_message = f"""Contract received for {property_address}!

Margaret will review within 2 hours. You'll receive your timeline shortly.

- Maverick TC"""
        send_sms(agent_phone, confirmation_message)

        print(f"Contract uploaded: Transaction #{transaction_id} - {property_address}")
        return jsonify(
            {
                "success": True,
                "transaction_id": transaction_id,
                "message": "Contract received successfully",
            }
        )
    except Exception as exc:
        print(f"Upload error: {exc}")
        return jsonify({"success": False, "error": "Server error. Please try again."}), 500


@app.route("/pay/<int:transaction_id>/<payment_type>")
def payment_page(transaction_id, payment_type):
    """Payment page for agent."""
    if payment_type not in {"upfront", "closing"}:
        return "Invalid payment type", 400

    query = """
    SELECT property_address, agent_name, rush_service, referred_by_agent,
           payment_upfront_paid, payment_closing_paid
    FROM transactions WHERE id = %s
    """
    rows = execute_query(query, (transaction_id,), fetch=True) or []
    if not rows:
        return "Transaction not found", 404
    txn = rows[0]

    if payment_type == "upfront" and txn["payment_upfront_paid"]:
        return "This payment has already been received. Thank you!", 200
    if payment_type == "closing" and txn["payment_closing_paid"]:
        return "This payment has already been received. Thank you!", 200

    breakdown = calculate_payment_breakdown(txn, payment_type)
    payment_data = {
        "transaction_id": transaction_id,
        "property_address": txn["property_address"],
        "payment_type": payment_type,
        "original_amount": f"{breakdown['original_amount']:.2f}",
        "referral_credit": f"{breakdown['referral_credit']:.2f}",
        "amount": f"{breakdown['amount']:.2f}",
        "amount_number": round(float(breakdown["amount"]), 2),
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
    """Process Stripe payment."""
    if payment_type not in {"upfront", "closing"}:
        return jsonify({"success": False, "error": "Invalid payment type"}), 400
    if not stripe.api_key:
        return jsonify({"success": False, "error": "Stripe is not configured"}), 500

    payload = request.get_json(silent=True) or {}
    payment_method_id = payload.get("payment_method_id")
    amount_raw = payload.get("amount")

    try:
        amount = float(amount_raw)
    except (TypeError, ValueError):
        return jsonify({"success": False, "error": "Invalid payment amount"}), 400

    if not payment_method_id or amount <= 0:
        return jsonify({"success": False, "error": "Missing payment data"}), 400

    try:
        intent = stripe.PaymentIntent.create(
            amount=int(round(amount * 100)),
            currency="usd",
            payment_method=payment_method_id,
            confirm=True,
            automatic_payment_methods={"enabled": True, "allow_redirects": "never"},
            description=f"Maverick TC - Transaction #{transaction_id} - {payment_type}",
            metadata={"transaction_id": str(transaction_id), "payment_type": payment_type},
        )

        if intent.status != "succeeded":
            return jsonify({"success": False, "error": "Payment not completed"}), 400

        if payment_type == "upfront":
            update_query = """
            UPDATE transactions
            SET payment_upfront_paid = TRUE,
                payment_upfront_date = %s,
                updated_at = CURRENT_TIMESTAMP
            WHERE id = %s
            """
        else:
            update_query = """
            UPDATE transactions
            SET payment_closing_paid = TRUE,
                payment_closing_date = %s,
                updated_at = CURRENT_TIMESTAMP
            WHERE id = %s
            """
        execute_query(update_query, (datetime.now(), transaction_id))

        if payment_type == "upfront":
            agent_rows = execute_query(
                "SELECT agent_name, referred_by_agent FROM transactions WHERE id = %s",
                (transaction_id,),
                fetch=True,
            ) or []
            if agent_rows and agent_rows[0]["referred_by_agent"]:
                credit_rows = execute_query(
                    """
                    SELECT id
                    FROM referrals
                    WHERE referred_agent_name = %s
                      AND credit_used = FALSE
                    ORDER BY created_at DESC
                    LIMIT 1
                    """,
                    (agent_rows[0]["agent_name"],),
                    fetch=True,
                ) or []
                if credit_rows:
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

        phone_rows = execute_query(
            "SELECT agent_phone FROM transactions WHERE id = %s",
            (transaction_id,),
            fetch=True,
        ) or []
        if phone_rows:
            send_sms(
                phone_rows[0]["agent_phone"],
                f"Payment received (${amount:.2f}). Thank you. - Maverick TC",
            )

        return jsonify({"success": True, "payment_intent_id": intent.id})
    except stripe.error.CardError as exc:
        return jsonify({"success": False, "error": exc.user_message or "Card error"}), 400
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
    query = """
    SELECT d.deadline_type, d.deadline_date,
           t.property_address, t.agent_phone
    FROM deadlines d
    JOIN transactions t ON d.transaction_id = t.id
    WHERE d.id = %s
    """
    rows = execute_query(query, (deadline_id,), fetch=True) or []
    if not rows:
        return jsonify({"success": False, "error": "Deadline not found"}), 404

    deadline = rows[0]
    days_until = (deadline["deadline_date"] - date.today()).days
    success = send_reminder(
        to_number=deadline["agent_phone"],
        property_address=deadline["property_address"],
        deadline_type=deadline["deadline_type"].replace("_", " ").title(),
        deadline_date=deadline["deadline_date"].strftime("%m/%d/%Y"),
        days_until=days_until,
    )

    if not success:
        return jsonify({"success": False, "error": "Failed to send SMS"}), 500

    if days_until >= 10:
        sent_flag, sent_at_flag = "reminder_10d_sent", "reminder_10d_sent_at"
    elif days_until >= 7:
        sent_flag, sent_at_flag = "reminder_7d_sent", "reminder_7d_sent_at"
    elif days_until >= 3:
        sent_flag, sent_at_flag = "reminder_3d_sent", "reminder_3d_sent_at"
    else:
        sent_flag, sent_at_flag = "reminder_1d_sent", "reminder_1d_sent_at"

    execute_query(
        f"UPDATE deadlines SET {sent_flag} = TRUE, {sent_at_flag} = CURRENT_TIMESTAMP WHERE id = %s",
        (deadline_id,),
    )
    return jsonify({"success": True})


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
    return "Page not found", 404


@app.errorhandler(500)
def server_error(_exc):
    return "Server error", 500


if __name__ == "__main__":
    app.run(debug=True, host="0.0.0.0", port=5000)
