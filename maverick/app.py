import os
import re

from dotenv import load_dotenv
from flask import Flask, jsonify, render_template, request
from twilio.twiml.messaging_response import MessagingResponse
from werkzeug.utils import secure_filename

from config import Config
from utils.db import execute_insert, execute_query
from utils.s3 import upload_contract
from utils.sms import send_sms

load_dotenv()

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


@app.route("/")
def index():
    """Agent upload form."""
    return render_template("upload.html")


@app.route("/health")
def health():
    """Basic health check for Railway and uptime monitors."""
    return jsonify({"ok": True, "service": "maverick-tc"})


@app.route("/upload", methods=["POST"])
def upload_contract_route():
    """Handle contract upload from agent."""
    try:
        # Validate form data
        agent_name = request.form.get("agent_name", "").strip()
        agent_phone = normalize_phone(request.form.get("agent_phone", "").strip())
        agent_email = request.form.get("agent_email", "").strip()
        property_address = request.form.get("property_address", "").strip()
        rush_service = request.form.get("rush_service") == "on"
        referral_source = request.form.get("referral_source", "").strip()
        referred_by = (
            request.form.get("referred_by", "").strip() if referral_source == "referral" else None
        )

        # Validate required fields
        if not all([agent_name, agent_phone, agent_email, property_address, referral_source]):
            return jsonify({"success": False, "error": "All required fields must be provided"}), 400

        if referral_source == "referral" and not referred_by:
            return jsonify({"success": False, "error": "Referral agent name is required"}), 400

        # Validate file upload
        if "contract_pdf" not in request.files:
            return jsonify({"success": False, "error": "No file uploaded"}), 400

        file = request.files["contract_pdf"]
        if not file or file.filename == "":
            return jsonify({"success": False, "error": "No file selected"}), 400

        if not allowed_file(file.filename):
            return jsonify({"success": False, "error": "Only PDF files allowed"}), 400

        # Check file size
        file.seek(0, os.SEEK_END)
        file_size = file.tell()
        if file_size > MAX_FILE_SIZE:
            return jsonify({"success": False, "error": "File too large (max 16MB)"}), 400
        file.seek(0)

        # Insert transaction into database
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

        # Upload contract to S3
        safe_filename = secure_filename(file.filename)
        if not safe_filename.lower().endswith(".pdf"):
            safe_filename = f"{safe_filename}.pdf"

        s3_key = upload_contract(file, transaction_id, property_address)
        if not s3_key:
            execute_query("UPDATE transactions SET status = 'CANCELLED' WHERE id = %s", (transaction_id,))
            return jsonify({"success": False, "error": "File upload failed"}), 500

        # Update transaction with S3 key and basic PDF URL marker
        update_query = """
        UPDATE transactions
        SET contract_s3_key = %s,
            contract_pdf_url = %s,
            updated_at = CURRENT_TIMESTAMP
        WHERE id = %s
        """
        execute_query(update_query, (s3_key, safe_filename, transaction_id))

        # Send confirmation SMS to agent (best-effort)
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


@app.route("/sms-webhook", methods=["POST"])
def sms_webhook():
    """Handle incoming SMS from agents."""
    incoming_msg = request.form.get("Body", "").strip().lower()
    from_number = normalize_phone(request.form.get("From", ""))

    response = MessagingResponse()

    # Emergency alert flow
    emergency_keywords = {"emergency", "urgent", "asap", "help now"}
    if any(word in incoming_msg for word in emergency_keywords):
        heidi_phone = os.getenv("HEIDI_PHONE")
        margaret_phone = os.getenv("MARGARET_PHONE")
        if heidi_phone:
            send_sms(heidi_phone, f"EMERGENCY from {from_number}: {incoming_msg}")
        if margaret_phone:
            send_sms(margaret_phone, f"EMERGENCY from {from_number}: {incoming_msg}")

        response.message("Emergency alert sent to Heidi and Margaret. They'll call you ASAP.")
        return str(response)

    # Status update flow
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
        transactions = execute_query(query, (last_10,), fetch=True)

        if transactions:
            txn = transactions[0]
            if txn["status"] == "NEEDS_MARGARET_REVIEW":
                response.message(
                    f"{txn['property_address']}: Under review. Margaret will call you today."
                )
            else:
                closing_date = txn["closing_date"].strftime("%Y-%m-%d") if txn["closing_date"] else "TBD"
                response.message(
                    f"{txn['property_address']}: Closes {closing_date}. "
                    "Margaret will send a detailed update tomorrow morning."
                )
        else:
            response.message(
                "No active transactions found. Margaret will call you tomorrow morning to help."
            )

        return str(response)

    response.message(
        "Got your message! Margaret will call you during business hours "
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
