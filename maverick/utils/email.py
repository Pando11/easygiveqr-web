import os
import re
import smtplib
from email.message import EmailMessage

from dotenv import load_dotenv

load_dotenv()


def _html_to_text(html_body):
    """Convert simple HTML email body to a plain-text fallback."""
    if not html_body:
        return ""
    stripped = re.sub(r"<\s*br\s*/?\s*>", "\n", html_body, flags=re.IGNORECASE)
    stripped = re.sub(r"</p\s*>", "\n\n", stripped, flags=re.IGNORECASE)
    stripped = re.sub(r"<[^>]+>", "", stripped)
    return re.sub(r"\n{3,}", "\n\n", stripped).strip()


def send_html_email(to_email, subject, html_body, text_body=None):
    """
    Send HTML email using SMTP settings from environment variables.

    Required env vars:
      - SMTP_HOST
      - SMTP_PORT (defaults to 587)
      - SMTP_FROM_EMAIL (or SMTP_USERNAME fallback)

    Optional env vars:
      - SMTP_USERNAME
      - SMTP_PASSWORD
      - SMTP_USE_TLS (default true)
      - SMTP_USE_SSL (default false)
      - SMTP_FROM_NAME

    Returns:
      - message-id string if sent
      - None on failure/missing config
    """
    smtp_host = (os.getenv("SMTP_HOST") or "").strip()
    smtp_port = int((os.getenv("SMTP_PORT") or "587").strip())
    smtp_username = (os.getenv("SMTP_USERNAME") or "").strip()
    smtp_password = (os.getenv("SMTP_PASSWORD") or "").strip()
    smtp_from_email = (os.getenv("SMTP_FROM_EMAIL") or smtp_username).strip()
    smtp_from_name = (os.getenv("SMTP_FROM_NAME") or "Maverick TC").strip()
    use_tls = (os.getenv("SMTP_USE_TLS") or "true").strip().lower() in {"1", "true", "yes", "on"}
    use_ssl = (os.getenv("SMTP_USE_SSL") or "false").strip().lower() in {"1", "true", "yes", "on"}

    if not smtp_host:
        print("Email send skipped: SMTP_HOST is not configured.")
        return None
    if not smtp_from_email:
        print("Email send skipped: SMTP_FROM_EMAIL/SMTP_USERNAME is not configured.")
        return None
    if not to_email:
        print("Email send skipped: recipient address missing.")
        return None

    message = EmailMessage()
    message["Subject"] = subject
    message["From"] = f"{smtp_from_name} <{smtp_from_email}>"
    message["To"] = to_email
    message.set_content((text_body or _html_to_text(html_body) or "Maverick TC notification").strip())
    if html_body:
        message.add_alternative(html_body, subtype="html")

    try:
        smtp_client_class = smtplib.SMTP_SSL if use_ssl else smtplib.SMTP
        with smtp_client_class(smtp_host, smtp_port, timeout=25) as server:
            if not use_ssl and use_tls:
                server.starttls()
            if smtp_username and smtp_password:
                server.login(smtp_username, smtp_password)
            server.send_message(message)
        return message.get("Message-ID")
    except Exception as exc:
        print(f"Email send error to {to_email}: {exc}")
        return None
