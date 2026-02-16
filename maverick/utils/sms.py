import os
import re

from dotenv import load_dotenv
from twilio.rest import Client

load_dotenv()


def _normalize_phone(to_number):
    digits_only = re.sub(r"\D", "", to_number or "")
    if len(digits_only) == 10:
        return f"+1{digits_only}"
    if len(digits_only) == 11 and digits_only.startswith("1"):
        return f"+{digits_only}"
    if to_number and to_number.startswith("+"):
        return to_number
    return f"+{digits_only}" if digits_only else ""


def _get_twilio_client():
    account_sid = os.getenv("TWILIO_ACCOUNT_SID")
    auth_token = os.getenv("TWILIO_AUTH_TOKEN")
    if not account_sid or not auth_token:
        print("Twilio credentials not configured. SMS send skipped.")
        return None
    return Client(account_sid, auth_token)


def send_sms(to_number, message):
    """
    Send SMS via Twilio.

    Args:
        to_number: Phone number (format: +18065551234)
        message: Message text

    Returns:
        message_sid if successful, None if failed
    """
    try:
        from_number = os.getenv("TWILIO_PHONE_NUMBER")
        if not from_number:
            print("TWILIO_PHONE_NUMBER not configured.")
            return None

        formatted_to = _normalize_phone(to_number)
        if not formatted_to:
            print("SMS send error: invalid destination number")
            return None

        client = _get_twilio_client()
        if not client:
            return None

        twilio_message = client.messages.create(
            to=formatted_to,
            from_=from_number,
            body=message,
        )

        print(f"SMS sent to {formatted_to}: {twilio_message.sid}")
        return twilio_message.sid

    except Exception as exc:
        print(f"SMS send error: {exc}")
        return None


def send_payment_link(to_number, transaction_id, amount, payment_type="upfront"):
    """Send payment link via SMS."""
    payment_url = f"https://getmaverick.com/pay/{transaction_id}/{payment_type}"

    message = f"""Payment due: ${amount}

Pay now: {payment_url}

Or:
Venmo: {os.getenv('VENMO_HANDLE')}
PayPal: {os.getenv('PAYPAL_EMAIL')}

- Maverick TC"""

    return send_sms(to_number, message)


def send_timeline_approved(to_number, property_address, dates):
    """Send timeline approved message."""
    message = f"""Timeline approved for {property_address}!

Key dates:
- Earnest due: {dates['earnest']}
- Option ends: {dates['option_end']}
- Financing: {dates['financing']}
- Closing: {dates['closing']}

You'll get reminders 10, 7, 3, 1 days before each.

Reply CONFIRM to acknowledge.

- Maverick TC"""

    return send_sms(to_number, message)


def send_reminder(to_number, property_address, deadline_type, deadline_date, days_until):
    """Send deadline reminder."""
    days_text = "TOMORROW" if days_until == 1 else f"in {days_until} days"

    message = (
        f"Reminder: {deadline_type} for {property_address} "
        f"is due {days_text} ({deadline_date}).\n\n- Maverick TC"
    )

    return send_sms(to_number, message)
