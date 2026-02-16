import os
from dataclasses import dataclass

from dotenv import load_dotenv

load_dotenv()


@dataclass(frozen=True)
class Config:
    SECRET_KEY: str = os.getenv("SECRET_KEY", "dev-secret-key-change-in-production")
    DATABASE_URL: str = os.getenv("DATABASE_URL", "")

    # Upload settings
    MAX_CONTENT_LENGTH: int = 16 * 1024 * 1024  # 16MB
    ALLOWED_EXTENSIONS: frozenset[str] = frozenset({"pdf"})

    # Twilio
    TWILIO_ACCOUNT_SID: str = os.getenv("TWILIO_ACCOUNT_SID", "")
    TWILIO_AUTH_TOKEN: str = os.getenv("TWILIO_AUTH_TOKEN", "")
    TWILIO_PHONE_NUMBER: str = os.getenv("TWILIO_PHONE_NUMBER", "")
    HEIDI_PHONE: str = os.getenv("HEIDI_PHONE", "")
    MARGARET_PHONE: str = os.getenv("MARGARET_PHONE", "")

    # AWS
    AWS_ACCESS_KEY_ID: str = os.getenv("AWS_ACCESS_KEY_ID", "")
    AWS_SECRET_ACCESS_KEY: str = os.getenv("AWS_SECRET_ACCESS_KEY", "")
    AWS_REGION: str = os.getenv("AWS_REGION", "us-east-1")
    AWS_S3_BUCKET_DOCUMENTS: str = os.getenv("AWS_S3_BUCKET_DOCUMENTS", "")
    AWS_S3_BUCKET_BACKUPS: str = os.getenv("AWS_S3_BUCKET_BACKUPS", "")

    # Payments
    STRIPE_SECRET_KEY: str = os.getenv("STRIPE_SECRET_KEY", "")
    STRIPE_PUBLISHABLE_KEY: str = os.getenv("STRIPE_PUBLISHABLE_KEY", "")
    PAYPAL_EMAIL: str = os.getenv("PAYPAL_EMAIL", "pay@getmaverick.com")
    PAYPAL_HANDLE: str = os.getenv("PAYPAL_HANDLE", "getmaverick")
    VENMO_HANDLE: str = os.getenv("VENMO_HANDLE", "@GetMaverick")

