import os
from datetime import datetime

import boto3
from dotenv import load_dotenv

load_dotenv()


def _get_s3_client():
    return boto3.client(
        "s3",
        aws_access_key_id=os.getenv("AWS_ACCESS_KEY_ID"),
        aws_secret_access_key=os.getenv("AWS_SECRET_ACCESS_KEY"),
        region_name=os.getenv("AWS_REGION", "us-east-1"),
    )


DOCUMENTS_BUCKET = os.getenv("AWS_S3_BUCKET_DOCUMENTS")
BACKUPS_BUCKET = os.getenv("AWS_S3_BUCKET_BACKUPS")


def upload_contract(file, transaction_id, property_address):
    """
    Upload contract PDF to S3.

    Returns: s3_key if successful, None if failed.
    """
    try:
        if not DOCUMENTS_BUCKET:
            print("S3 upload error: AWS_S3_BUCKET_DOCUMENTS is not configured")
            return None

        # Generate S3 key
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        clean_address = property_address.replace(" ", "_").replace(",", "")
        filename = f"contract_{transaction_id}_{clean_address}_{timestamp}.pdf"
        s3_key = f"contracts/{datetime.now().year}/{datetime.now().month:02d}/{filename}"

        # Upload to S3
        _get_s3_client().upload_fileobj(
            file,
            DOCUMENTS_BUCKET,
            s3_key,
            ExtraArgs={"ContentType": "application/pdf"},
        )

        print(f"Contract uploaded to S3: {s3_key}")
        return s3_key

    except Exception as exc:
        print(f"S3 upload error: {exc}")
        return None


def upload_document(file, transaction_id, document_type, filename):
    """Upload document to S3."""
    try:
        if not DOCUMENTS_BUCKET:
            print("S3 upload error: AWS_S3_BUCKET_DOCUMENTS is not configured")
            return None

        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        s3_key = (
            f"documents/{datetime.now().year}/{datetime.now().month:02d}/"
            f"{document_type}_{transaction_id}_{timestamp}_{filename}"
        )

        _get_s3_client().upload_fileobj(file, DOCUMENTS_BUCKET, s3_key)

        print(f"Document uploaded to S3: {s3_key}")
        return s3_key

    except Exception as exc:
        print(f"S3 upload error: {exc}")
        return None


def get_presigned_url(s3_key, expiration=3600):
    """
    Generate presigned URL for document download.

    Args:
        s3_key: S3 object key
        expiration: URL expiration in seconds (default 1 hour)

    Returns: Presigned URL
    """
    try:
        if not DOCUMENTS_BUCKET:
            print("Presigned URL error: AWS_S3_BUCKET_DOCUMENTS is not configured")
            return None

        url = _get_s3_client().generate_presigned_url(
            "get_object",
            Params={"Bucket": DOCUMENTS_BUCKET, "Key": s3_key},
            ExpiresIn=expiration,
        )
        return url
    except Exception as exc:
        print(f"Presigned URL error: {exc}")
        return None


def log_document_access(document_id, user_name, user_type, action, ip_address):
    """Log document access for audit trail."""
    from utils.db import execute_query

    query = """
    INSERT INTO document_access_logs (document_id, user_name, user_type, action, ip_address)
    VALUES (%s, %s, %s, %s, %s)
    """

    execute_query(query, (document_id, user_name, user_type, action, ip_address))
