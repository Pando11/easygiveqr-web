import os
import re
from datetime import date, datetime
from functools import wraps

import stripe
from dotenv import load_dotenv
from flask import Flask, jsonify, redirect, render_template, request, session, url_for
from twilio.twiml.messaging_response import MessagingResponse
from werkzeug.security import check_password_hash
from werkzeug.utils import secure_filename

from config import Config
from utils.db import execute_insert, execute_query
from utils.payments import calculate_payment_breakdown
from utils.s3 import upload_contract
from utils.sms import send_reminder, send_sms

load_dotenv()
stripe.api_key = os.getenv("STRIPE_SECRET_KEY")

app = Flask(__name__)
app.config.from_object(Config())
app.secret_key = app.config["SECRET_KEY"]
app.config["MAX_CONTENT_LENGTH"] = app.config.get("MAX_CONTENT_LENGTH", 16 * 1024 * 1024)

ALLOWED_EXTENSIONS = set(app.config.get("ALLOWED_EXTENSIONS", {"pdf"}))
MAX_FILE_SIZE = app.config["MAX_CONTENT_LENGTH"]


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
        if not session.get("tc_authenticated"):
            return redirect(url_for("tc_login"))
        return view_func(*args, **kwargs)

    return wrapped


@app.route("/")
def index():
    """Agent upload form."""
    return render_template("upload.html")


@app.route("/health")
def health():
    """Basic health check for Railway and uptime monitors."""
    return jsonify({"ok": True, "service": "maverick-tc"})


@app.route("/tc/login", methods=["GET", "POST"])
def tc_login():
    """Simple TC login page."""
    if session.get("tc_authenticated"):
        return redirect(url_for("tc_dashboard"))

    error = None
    if request.method == "POST":
        username = request.form.get("username", "").strip()
        password = request.form.get("password", "")
        expected_username = os.getenv("TC_USERNAME", "margaret")

        if username == expected_username and _verify_tc_password(password):
            session["tc_authenticated"] = True
            session["tc_username"] = username
            return redirect(url_for("tc_dashboard"))
        error = "Invalid username or password."

    return f"""
    <html>
      <head>
        <title>Maverick TC Login</title>
        <style>
          body {{ font-family: Arial, sans-serif; background: #f5f5f5; padding: 40px; }}
          .card {{ max-width: 420px; margin: 0 auto; background: #fff; padding: 24px;
                   border-radius: 8px; box-shadow: 0 2px 10px rgba(0,0,0,0.1); }}
          input {{ width: 100%; padding: 10px; margin: 8px 0 14px; border: 1px solid #ccc; border-radius: 6px; }}
          button {{ width: 100%; padding: 12px; border: none; border-radius: 6px;
                    background: #10b981; color: #fff; cursor: pointer; }}
          .error {{ color: #b91c1c; margin-bottom: 12px; }}
        </style>
      </head>
      <body>
        <div class="card">
          <h2>Margaret Dashboard Login</h2>
          <p>Use your TC credentials to continue.</p>
          {"<p class='error'>" + error + "</p>" if error else ""}
          <form method="post">
            <label>Username</label>
            <input name="username" required />
            <label>Password</label>
            <input name="password" type="password" required />
            <button type="submit">Sign in</button>
          </form>
        </div>
      </body>
    </html>
    """


@app.route("/tc/logout")
def tc_logout():
    session.clear()
    return redirect(url_for("tc_login"))


@app.route("/tc")
@login_required
def tc_dashboard():
    """Minimal transaction list dashboard."""
    rows = execute_query(
        """
        SELECT id, property_address, agent_name, status, closing_date,
               payment_upfront_paid, payment_closing_paid
        FROM transactions
        ORDER BY created_at DESC
        LIMIT 100
        """,
        fetch=True,
    ) or []

    list_items = []
    for txn in rows:
        closing = txn["closing_date"].strftime("%Y-%m-%d") if txn["closing_date"] else "TBD"
        list_items.append(
            f"""
            <tr>
              <td>{txn['id']}</td>
              <td>{txn['property_address']}</td>
              <td>{txn['agent_name']}</td>
              <td>{txn['status']}</td>
              <td>{closing}</td>
              <td>{"YES" if txn['payment_upfront_paid'] else "NO"}</td>
              <td>{"YES" if txn['payment_closing_paid'] else "NO"}</td>
              <td><a href="/tc/transaction/{txn['id']}">Open</a></td>
            </tr>
            """
        )

    table_rows = "".join(list_items) or "<tr><td colspan='8'>No transactions yet.</td></tr>"
    return f"""
    <html>
      <head>
        <title>Maverick TC Dashboard</title>
        <style>
          body {{ font-family: Arial, sans-serif; margin: 24px; }}
          table {{ border-collapse: collapse; width: 100%; }}
          th, td {{ border: 1px solid #ddd; padding: 8px; text-align: left; }}
          th {{ background: #f5f5f5; }}
          .nav {{ margin-bottom: 20px; }}
        </style>
      </head>
      <body>
        <div class="nav">
          <strong>Maverick TC Dashboard</strong> |
          <a href="/tc/checklist">Daily checklist</a> |
          <a href="/tc/logout">Logout</a>
        </div>
        <table>
          <thead>
            <tr>
              <th>ID</th><th>Property</th><th>Agent</th><th>Status</th><th>Closing</th>
              <th>Upfront Paid</th><th>Closing Paid</th><th>Actions</th>
            </tr>
          </thead>
          <tbody>{table_rows}</tbody>
        </table>
      </body>
    </html>
    """


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
    txn_rows = execute_query(
        """
        SELECT id, property_address, agent_name, agent_phone, status, closing_date,
               payment_upfront_paid, payment_closing_paid
        FROM transactions
        WHERE id = %s
        """,
        (transaction_id,),
        fetch=True,
    ) or []
    if not txn_rows:
        return "Transaction not found", 404

    txn = txn_rows[0]
    closing = txn["closing_date"].strftime("%Y-%m-%d") if txn["closing_date"] else "TBD"
    return f"""
    <html>
      <head><title>Transaction {txn['id']}</title></head>
      <body style="font-family: Arial, sans-serif; margin: 24px;">
        <a href="/tc">Back to dashboard</a>
        <h2>{txn['property_address']}</h2>
        <p><strong>Agent:</strong> {txn['agent_name']} ({txn['agent_phone']})</p>
        <p><strong>Status:</strong> {txn['status']}</p>
        <p><strong>Closing date:</strong> {closing}</p>
        <p><strong>Upfront paid:</strong> {"YES" if txn['payment_upfront_paid'] else "NO"}</p>
        <p><strong>Closing paid:</strong> {"YES" if txn['payment_closing_paid'] else "NO"}</p>
        <p>
          <a href="/pay/{txn['id']}/upfront">Upfront payment page</a> |
          <a href="/pay/{txn['id']}/closing">Closing payment page</a>
        </p>
        <p><a href="/tc/transaction/{txn['id']}/mark-complete">Mark complete</a></p>
      </body>
    </html>
    """


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
