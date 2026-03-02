from __future__ import annotations

import base64
import hashlib
import json
import os
from datetime import date, datetime, time, timedelta

from utils.db import execute_query


GOOGLE_CALENDAR_SCOPES = ["https://www.googleapis.com/auth/calendar"]
DEFAULT_CALENDAR_TIMEZONE = "America/Chicago"


def _safe_text(value, fallback=""):
    text = str(value or "").strip()
    return text if text else fallback


def _parse_bool_env(name, default=False):
    raw_value = (os.getenv(name) or "").strip().lower()
    if not raw_value:
        return bool(default)
    return raw_value in {"1", "true", "yes", "on"}


def _parse_int_env(name, default_value):
    raw_value = (os.getenv(name) or "").strip()
    if not raw_value:
        return int(default_value)
    try:
        return int(raw_value)
    except (TypeError, ValueError):
        return int(default_value)


def _normalize_datetime_value(value):
    if value is None:
        return None
    if isinstance(value, datetime):
        return value
    if isinstance(value, date):
        return datetime.combine(value, time(9, 0))
    text = _safe_text(value)
    if not text:
        return None
    text = text.replace("Z", "+00:00")
    for parser in (
        lambda payload: datetime.fromisoformat(payload),
        lambda payload: datetime.strptime(payload, "%Y-%m-%d %H:%M"),
        lambda payload: datetime.strptime(payload, "%Y-%m-%d %H:%M:%S"),
        lambda payload: datetime.strptime(payload, "%Y-%m-%d"),
    ):
        try:
            parsed = parser(text)
            if isinstance(parsed, datetime):
                return parsed
            return datetime.combine(parsed, time(9, 0))
        except Exception:
            continue
    return None


def _to_google_datetime(value):
    parsed = _normalize_datetime_value(value)
    if not parsed:
        return None
    return parsed.strftime("%Y-%m-%dT%H:%M:%S")


def _to_google_date(value):
    if isinstance(value, datetime):
        return value.date().isoformat()
    if isinstance(value, date):
        return value.isoformat()
    parsed = _normalize_datetime_value(value)
    return parsed.date().isoformat() if parsed else None


def _event_payload_hash(event_payload):
    serialized = json.dumps(event_payload or {}, sort_keys=True, default=str)
    return hashlib.sha256(serialized.encode("utf-8")).hexdigest()


def _json_dumps(payload):
    return json.dumps(payload or {}, default=str)


def _parse_json_field(raw_value, default_value):
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


def ensure_calendar_sync_tables():
    """Ensure Google Calendar sync settings, mappings, and audit tables exist."""
    execute_query(
        """
        CREATE TABLE IF NOT EXISTS calendar_sync_settings (
            id SERIAL PRIMARY KEY,
            enabled BOOLEAN DEFAULT TRUE,
            calendar_id VARCHAR(255) DEFAULT 'primary',
            timezone VARCHAR(80) DEFAULT 'America/Chicago',
            sync_deadlines BOOLEAN DEFAULT TRUE,
            sync_inspections BOOLEAN DEFAULT TRUE,
            sync_closings BOOLEAN DEFAULT TRUE,
            sync_appraisals BOOLEAN DEFAULT TRUE,
            two_way_sync_enabled BOOLEAN DEFAULT FALSE,
            auto_delete_on_cancel BOOLEAN DEFAULT TRUE,
            closing_default_time VARCHAR(5) DEFAULT '09:00',
            closing_duration_minutes INT DEFAULT 60,
            updated_by VARCHAR(100),
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
        """
    )
    execute_query(
        """
        CREATE TABLE IF NOT EXISTS transaction_calendar_preferences (
            id SERIAL PRIMARY KEY,
            transaction_id INT UNIQUE REFERENCES transactions(id) ON DELETE CASCADE,
            closing_time VARCHAR(5),
            closing_duration_minutes INT,
            closing_location TEXT,
            updated_by VARCHAR(100),
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
        """
    )
    execute_query(
        """
        CREATE TABLE IF NOT EXISTS google_calendar_mappings (
            id SERIAL PRIMARY KEY,
            transaction_id INT REFERENCES transactions(id) ON DELETE CASCADE,
            event_type VARCHAR(40) NOT NULL,
            source_ref VARCHAR(120) NOT NULL DEFAULT '',
            source_id INT DEFAULT 0,
            source_label VARCHAR(80),
            calendar_id VARCHAR(255) DEFAULT 'primary',
            google_event_id VARCHAR(255) NOT NULL,
            event_hash VARCHAR(64),
            status VARCHAR(20) DEFAULT 'active',
            metadata JSONB DEFAULT '{}'::jsonb,
            last_synced_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            UNIQUE (transaction_id, event_type, source_ref, calendar_id)
        )
        """
    )
    execute_query(
        """
        CREATE TABLE IF NOT EXISTS calendar_sync_audit_log (
            id SERIAL PRIMARY KEY,
            transaction_id INT REFERENCES transactions(id) ON DELETE CASCADE,
            mapping_id INT REFERENCES google_calendar_mappings(id) ON DELETE SET NULL,
            action VARCHAR(40) NOT NULL,
            event_type VARCHAR(40),
            success BOOLEAN DEFAULT TRUE,
            details TEXT,
            metadata JSONB DEFAULT '{}'::jsonb,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
        """
    )
    execute_query(
        """
        CREATE TABLE IF NOT EXISTS calendar_webhook_channels (
            id SERIAL PRIMARY KEY,
            channel_id VARCHAR(255) UNIQUE NOT NULL,
            resource_id VARCHAR(255),
            resource_uri TEXT,
            expiration_at TIMESTAMP,
            active BOOLEAN DEFAULT TRUE,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
        """
    )
    execute_query(
        """
        CREATE INDEX IF NOT EXISTS idx_google_calendar_mappings_txn_event
        ON google_calendar_mappings(transaction_id, event_type, status, updated_at DESC)
        """
    )
    execute_query(
        """
        CREATE UNIQUE INDEX IF NOT EXISTS idx_google_calendar_mappings_event_id
        ON google_calendar_mappings(google_event_id, calendar_id)
        """
    )
    execute_query(
        """
        CREATE INDEX IF NOT EXISTS idx_calendar_sync_audit_txn
        ON calendar_sync_audit_log(transaction_id, created_at DESC)
        """
    )
    execute_query(
        """
        CREATE INDEX IF NOT EXISTS idx_calendar_sync_audit_action
        ON calendar_sync_audit_log(action, success, created_at DESC)
        """
    )

    # Backward-compatible migrations for older DBs.
    execute_query("ALTER TABLE google_calendar_mappings ADD COLUMN IF NOT EXISTS source_ref VARCHAR(120) DEFAULT ''")
    execute_query("ALTER TABLE google_calendar_mappings ADD COLUMN IF NOT EXISTS source_id INT DEFAULT 0")
    execute_query("ALTER TABLE google_calendar_mappings ADD COLUMN IF NOT EXISTS source_label VARCHAR(80)")
    execute_query("ALTER TABLE google_calendar_mappings ADD COLUMN IF NOT EXISTS metadata JSONB DEFAULT '{}'::jsonb")
    execute_query("ALTER TABLE calendar_sync_audit_log ADD COLUMN IF NOT EXISTS metadata JSONB DEFAULT '{}'::jsonb")

    rows = execute_query("SELECT id FROM calendar_sync_settings ORDER BY id ASC LIMIT 1", fetch=True) or []
    if not rows:
        execute_query(
            """
            INSERT INTO calendar_sync_settings (
                enabled,
                calendar_id,
                timezone,
                sync_deadlines,
                sync_inspections,
                sync_closings,
                sync_appraisals,
                two_way_sync_enabled,
                auto_delete_on_cancel,
                closing_default_time,
                closing_duration_minutes,
                updated_by,
                created_at,
                updated_at
            )
            VALUES (
                %s, %s, %s, TRUE, TRUE, TRUE, TRUE, FALSE, TRUE, %s, %s, 'system', CURRENT_TIMESTAMP, CURRENT_TIMESTAMP
            )
            """,
            (
                _parse_bool_env("ENABLE_GOOGLE_CALENDAR_SYNC", default=True),
                _safe_text(os.getenv("GOOGLE_CALENDAR_ID"), "primary"),
                _safe_text(os.getenv("GOOGLE_CALENDAR_TIMEZONE"), DEFAULT_CALENDAR_TIMEZONE),
                _safe_text(os.getenv("GOOGLE_CALENDAR_CLOSING_DEFAULT_TIME"), "09:00"),
                _parse_int_env("GOOGLE_CALENDAR_CLOSING_DURATION_MINUTES", 60),
            ),
        )


def _parse_credentials_payload():
    raw_value = (os.getenv("GOOGLE_CALENDAR_CREDENTIALS") or "").strip()
    if not raw_value:
        return None
    candidates = [raw_value, raw_value.replace("\\n", "\n")]
    try:
        decoded = base64.b64decode(raw_value).decode("utf-8")
        candidates.append(decoded)
    except Exception:
        pass
    for candidate in candidates:
        try:
            payload = json.loads(candidate)
            if isinstance(payload, dict):
                return payload
        except Exception:
            continue
    return None


def _load_google_credentials():
    payload = _parse_credentials_payload()
    if not payload:
        return None, "missing_credentials"

    try:
        from google.oauth2.credentials import Credentials as UserCredentials
        from google.oauth2.service_account import Credentials as ServiceAccountCredentials
    except Exception as exc:
        return None, f"google_auth_import_error:{exc}"

    try:
        payload_type = _safe_text(payload.get("type")).lower()
        if payload_type == "service_account":
            credentials = ServiceAccountCredentials.from_service_account_info(payload, scopes=GOOGLE_CALENDAR_SCOPES)
            delegated_user = _safe_text(os.getenv("GOOGLE_CALENDAR_DELEGATED_USER"))
            if delegated_user:
                credentials = credentials.with_subject(delegated_user)
            return credentials, None

        if payload.get("refresh_token") and payload.get("client_id"):
            return UserCredentials.from_authorized_user_info(payload, scopes=GOOGLE_CALENDAR_SCOPES), None

        secret_block = payload.get("installed") or payload.get("web") or {}
        refresh_token = (
            _safe_text(os.getenv("GOOGLE_CALENDAR_REFRESH_TOKEN"))
            or _safe_text(payload.get("refresh_token"))
            or _safe_text(secret_block.get("refresh_token"))
        )
        if secret_block.get("client_id") and secret_block.get("client_secret") and refresh_token:
            auth_info = {
                "client_id": secret_block.get("client_id"),
                "client_secret": secret_block.get("client_secret"),
                "refresh_token": refresh_token,
                "token_uri": secret_block.get("token_uri") or "https://oauth2.googleapis.com/token",
            }
            return UserCredentials.from_authorized_user_info(auth_info, scopes=GOOGLE_CALENDAR_SCOPES), None
    except Exception as exc:
        return None, f"credentials_parse_error:{exc}"

    return None, "unsupported_credentials_format"


def fetch_calendar_sync_settings():
    ensure_calendar_sync_tables()
    rows = execute_query(
        """
        SELECT
            id,
            enabled,
            calendar_id,
            timezone,
            sync_deadlines,
            sync_inspections,
            sync_closings,
            sync_appraisals,
            two_way_sync_enabled,
            auto_delete_on_cancel,
            closing_default_time,
            closing_duration_minutes,
            updated_by,
            created_at,
            updated_at
        FROM calendar_sync_settings
        ORDER BY id ASC
        LIMIT 1
        """,
        fetch=True,
    ) or []
    if not rows:
        return {
            "enabled": False,
            "calendar_id": "primary",
            "timezone": DEFAULT_CALENDAR_TIMEZONE,
            "sync_deadlines": True,
            "sync_inspections": True,
            "sync_closings": True,
            "sync_appraisals": True,
            "two_way_sync_enabled": False,
            "auto_delete_on_cancel": True,
            "closing_default_time": "09:00",
            "closing_duration_minutes": 60,
        }
    row = rows[0]
    row["calendar_id"] = _safe_text(row.get("calendar_id"), "primary")
    row["timezone"] = _safe_text(row.get("timezone"), DEFAULT_CALENDAR_TIMEZONE)
    row["closing_default_time"] = _safe_text(row.get("closing_default_time"), "09:00")
    row["closing_duration_minutes"] = int(row.get("closing_duration_minutes") or 60)
    return row


def update_calendar_sync_settings(settings_payload, updated_by="margaret"):
    ensure_calendar_sync_tables()
    current = fetch_calendar_sync_settings()
    values = {
        "enabled": bool(settings_payload.get("enabled", current.get("enabled"))),
        "calendar_id": _safe_text(settings_payload.get("calendar_id"), current.get("calendar_id") or "primary"),
        "timezone": _safe_text(settings_payload.get("timezone"), current.get("timezone") or DEFAULT_CALENDAR_TIMEZONE),
        "sync_deadlines": bool(settings_payload.get("sync_deadlines", current.get("sync_deadlines"))),
        "sync_inspections": bool(settings_payload.get("sync_inspections", current.get("sync_inspections"))),
        "sync_closings": bool(settings_payload.get("sync_closings", current.get("sync_closings"))),
        "sync_appraisals": bool(settings_payload.get("sync_appraisals", current.get("sync_appraisals"))),
        "two_way_sync_enabled": bool(
            settings_payload.get("two_way_sync_enabled", current.get("two_way_sync_enabled"))
        ),
        "auto_delete_on_cancel": bool(
            settings_payload.get("auto_delete_on_cancel", current.get("auto_delete_on_cancel"))
        ),
        "closing_default_time": _safe_text(
            settings_payload.get("closing_default_time"),
            current.get("closing_default_time") or "09:00",
        ),
        "closing_duration_minutes": int(
            settings_payload.get("closing_duration_minutes", current.get("closing_duration_minutes") or 60) or 60
        ),
    }
    execute_query(
        """
        UPDATE calendar_sync_settings
        SET enabled = %s,
            calendar_id = %s,
            timezone = %s,
            sync_deadlines = %s,
            sync_inspections = %s,
            sync_closings = %s,
            sync_appraisals = %s,
            two_way_sync_enabled = %s,
            auto_delete_on_cancel = %s,
            closing_default_time = %s,
            closing_duration_minutes = %s,
            updated_by = %s,
            updated_at = CURRENT_TIMESTAMP
        WHERE id = %s
        """,
        (
            values["enabled"],
            values["calendar_id"],
            values["timezone"],
            values["sync_deadlines"],
            values["sync_inspections"],
            values["sync_closings"],
            values["sync_appraisals"],
            values["two_way_sync_enabled"],
            values["auto_delete_on_cancel"],
            values["closing_default_time"],
            max(15, min(values["closing_duration_minutes"], 240)),
            _safe_text(updated_by, "margaret"),
            current["id"],
        ),
    )
    return fetch_calendar_sync_settings()


def fetch_transaction_calendar_preferences(transaction_id):
    ensure_calendar_sync_tables()
    rows = execute_query(
        """
        SELECT
            id, transaction_id, closing_time, closing_duration_minutes, closing_location,
            updated_by, created_at, updated_at
        FROM transaction_calendar_preferences
        WHERE transaction_id = %s
        LIMIT 1
        """,
        (transaction_id,),
        fetch=True,
    ) or []
    return rows[0] if rows else None


def upsert_transaction_calendar_preferences(
    transaction_id,
    closing_time="",
    closing_duration_minutes=60,
    closing_location="",
    updated_by="margaret",
):
    ensure_calendar_sync_tables()
    safe_time = _safe_text(closing_time)
    if safe_time and len(safe_time) >= 5:
        safe_time = safe_time[:5]
    else:
        safe_time = None
    safe_duration = max(15, min(int(closing_duration_minutes or 60), 240))
    rows = execute_query(
        """
        INSERT INTO transaction_calendar_preferences (
            transaction_id, closing_time, closing_duration_minutes, closing_location, updated_by, created_at, updated_at
        )
        VALUES (%s, %s, %s, %s, %s, CURRENT_TIMESTAMP, CURRENT_TIMESTAMP)
        ON CONFLICT (transaction_id)
        DO UPDATE SET
            closing_time = EXCLUDED.closing_time,
            closing_duration_minutes = EXCLUDED.closing_duration_minutes,
            closing_location = EXCLUDED.closing_location,
            updated_by = EXCLUDED.updated_by,
            updated_at = CURRENT_TIMESTAMP
        RETURNING id, transaction_id, closing_time, closing_duration_minutes, closing_location, updated_by, created_at, updated_at
        """,
        (
            transaction_id,
            safe_time,
            safe_duration,
            _safe_text(closing_location) or None,
            _safe_text(updated_by, "margaret"),
        ),
        fetch=True,
    ) or []
    return rows[0] if rows else None


def _calendar_service(settings):
    if not settings.get("enabled"):
        return None, "calendar_sync_disabled"
    if not _parse_bool_env("ENABLE_GOOGLE_CALENDAR_SYNC", default=True):
        return None, "calendar_sync_disabled_env"

    credentials, credentials_error = _load_google_credentials()
    if not credentials:
        return None, credentials_error or "credentials_unavailable"

    try:
        from googleapiclient.discovery import build
    except Exception as exc:
        return None, f"google_api_import_error:{exc}"

    try:
        service = build("calendar", "v3", credentials=credentials, cache_discovery=False)
        return service, None
    except Exception as exc:
        return None, f"calendar_service_build_error:{exc}"


def get_calendar_service():
    """Public helper for callers needing raw Google Calendar service."""
    ensure_calendar_sync_tables()
    settings = fetch_calendar_sync_settings()
    service, service_error = _calendar_service(settings)
    if not service:
        raise RuntimeError(service_error or "calendar_service_unavailable")
    return service


def _event_sync_enabled(settings, event_type):
    normalized = _safe_text(event_type).lower()
    if normalized == "deadline":
        return bool(settings.get("sync_deadlines"))
    if normalized == "inspection":
        return bool(settings.get("sync_inspections"))
    if normalized == "closing":
        return bool(settings.get("sync_closings"))
    if normalized == "appraisal":
        return bool(settings.get("sync_appraisals"))
    return True


def _calendar_color(event_type):
    normalized = _safe_text(event_type).lower()
    if normalized == "deadline":
        return _safe_text(os.getenv("GOOGLE_CALENDAR_COLOR_DEADLINE"), "5")
    if normalized == "inspection":
        return _safe_text(os.getenv("GOOGLE_CALENDAR_COLOR_INSPECTION"), "9")
    if normalized == "closing":
        return _safe_text(os.getenv("GOOGLE_CALENDAR_COLOR_CLOSING"), "11")
    if normalized == "appraisal":
        return _safe_text(os.getenv("GOOGLE_CALENDAR_COLOR_APPRAISAL"), "10")
    if normalized == "daily_plan_block":
        return _safe_text(os.getenv("GOOGLE_CALENDAR_COLOR_DAILY_PLAN_BLOCK"), "6")
    return _safe_text(os.getenv("GOOGLE_CALENDAR_COLOR_DEFAULT"), "1")


def add_hour(iso_datetime_value):
    parsed = _normalize_datetime_value(iso_datetime_value)
    if not parsed:
        return None
    return (parsed + timedelta(hours=1)).strftime("%Y-%m-%dT%H:%M:%S")


def build_closing_description(event_data):
    return (
        f"Property: {_safe_text(event_data.get('property_address'))}\n"
        f"Buyer: {_safe_text(event_data.get('buyer_name'))}\n"
        f"Seller: {_safe_text(event_data.get('seller_name'))}\n"
        f"Agent: {_safe_text(event_data.get('agent_name'))}\n"
        f"Title: {_safe_text(event_data.get('title_company'))}\n"
        f"Lender: {_safe_text(event_data.get('lender_name'))}\n"
        f"Notes: {_safe_text(event_data.get('notes'))}"
    ).strip()


def _default_reminders(event_type):
    normalized = _safe_text(event_type).lower()
    if normalized == "inspection":
        return [{"method": "sms", "minutes": 60}, {"method": "popup", "minutes": 15}]
    if normalized == "closing":
        return [{"method": "sms", "minutes": 1440}, {"method": "sms", "minutes": 60}]
    if normalized == "appraisal":
        return [{"method": "popup", "minutes": 120}, {"method": "popup", "minutes": 30}]
    if normalized == "daily_plan_block":
        return [{"method": "popup", "minutes": 15}, {"method": "popup", "minutes": 5}]
    return [{"method": "popup", "minutes": 1440}]


def build_calendar_event_payload(event_type, transaction_id, event_data, timezone):
    normalized_type = _safe_text(event_type).lower()
    timezone_value = _safe_text(timezone, DEFAULT_CALENDAR_TIMEZONE)
    source_ref = _safe_text(event_data.get("source_ref"))
    source_id = int(event_data.get("source_id") or 0)
    summary_prefix = _safe_text(event_data.get("summary_prefix"), normalized_type.upper())
    color_id = _safe_text(event_data.get("color_id"), _calendar_color(normalized_type))
    reminders = event_data.get("reminders") or _default_reminders(normalized_type)

    if normalized_type == "deadline":
        deadline_date = _to_google_date(event_data.get("deadline_date"))
        if not deadline_date:
            raise ValueError("deadline_date is required for deadline events")
        start_date = datetime.strptime(deadline_date, "%Y-%m-%d").date()
        end_date = start_date + timedelta(days=1)
        return {
            "summary": f"{summary_prefix}: {_safe_text(event_data.get('deadline_label'))} - {_safe_text(event_data.get('property_address'))}",
            "location": _safe_text(event_data.get("property_address")),
            "description": _safe_text(event_data.get("description")),
            "start": {"date": start_date.isoformat()},
            "end": {"date": end_date.isoformat()},
            "reminders": {"useDefault": False, "overrides": reminders},
            "colorId": color_id,
            "extendedProperties": {
                "private": {
                    "transaction_id": str(transaction_id),
                    "event_type": normalized_type,
                    "source_ref": source_ref,
                    "source_id": str(source_id),
                    "deadline_type": _safe_text(event_data.get("deadline_type")),
                }
            },
        }

    if normalized_type in {"inspection", "appraisal"}:
        start_time = _to_google_datetime(event_data.get("start_time"))
        end_time = _to_google_datetime(event_data.get("end_time"))
        if not start_time:
            raise ValueError("start_time is required for timed calendar events")
        if not end_time:
            start_dt = _normalize_datetime_value(event_data.get("start_time"))
            end_time = (start_dt + timedelta(minutes=int(event_data.get("duration_minutes") or 45))).strftime(
                "%Y-%m-%dT%H:%M:%S"
            )
        contact_name = _safe_text(event_data.get("contact_name") or event_data.get("inspector_name"))
        contact_phone = _safe_text(event_data.get("contact_phone") or event_data.get("inspector_phone"))
        description = (
            f"{normalized_type.title()} contact: {contact_name} ({contact_phone})\n"
            f"Buyer: {_safe_text(event_data.get('buyer_name'))}\n"
            f"Notes: {_safe_text(event_data.get('notes'))}"
        ).strip()
        return {
            "summary": f"{summary_prefix}: {_safe_text(event_data.get('property_address'))}",
            "location": _safe_text(event_data.get("property_address")),
            "description": description,
            "start": {"dateTime": start_time, "timeZone": timezone_value},
            "end": {"dateTime": end_time, "timeZone": timezone_value},
            "reminders": {"useDefault": False, "overrides": reminders},
            "colorId": color_id,
            "extendedProperties": {
                "private": {
                    "transaction_id": str(transaction_id),
                    "event_type": normalized_type,
                    "source_ref": source_ref,
                    "source_id": str(source_id),
                }
            },
        }

    if normalized_type == "closing":
        closing_time = _to_google_datetime(event_data.get("closing_time"))
        if not closing_time:
            raise ValueError("closing_time is required for closing events")
        duration_minutes = int(event_data.get("duration_minutes") or 60)
        closing_dt = _normalize_datetime_value(event_data.get("closing_time"))
        end_dt = closing_dt + timedelta(minutes=max(30, min(duration_minutes, 240)))
        return {
            "summary": f"{summary_prefix}: {_safe_text(event_data.get('property_address'))}",
            "location": _safe_text(event_data.get("title_company_address") or event_data.get("location")),
            "description": build_closing_description(event_data),
            "start": {"dateTime": closing_time, "timeZone": timezone_value},
            "end": {"dateTime": end_dt.strftime("%Y-%m-%dT%H:%M:%S"), "timeZone": timezone_value},
            "reminders": {"useDefault": False, "overrides": reminders},
            "colorId": color_id,
            "extendedProperties": {
                "private": {
                    "transaction_id": str(transaction_id),
                    "event_type": normalized_type,
                    "source_ref": source_ref,
                    "source_id": str(source_id),
                }
            },
        }

    if normalized_type == "daily_plan_block":
        start_time = _to_google_datetime(event_data.get("start_time"))
        end_time = _to_google_datetime(event_data.get("end_time"))
        if not start_time:
            raise ValueError("start_time is required for daily_plan_block events")
        if not end_time:
            start_dt = _normalize_datetime_value(event_data.get("start_time"))
            end_dt = start_dt + timedelta(minutes=max(10, int(event_data.get("duration_minutes") or 30)))
            end_time = end_dt.strftime("%Y-%m-%dT%H:%M:%S")
        title = _safe_text(event_data.get("title")) or f"{summary_prefix}: Focus Block"
        return {
            "summary": title,
            "location": _safe_text(event_data.get("location"), "Maverick TC"),
            "description": _safe_text(event_data.get("notes") or event_data.get("description")),
            "start": {"dateTime": start_time, "timeZone": timezone_value},
            "end": {"dateTime": end_time, "timeZone": timezone_value},
            "reminders": {"useDefault": False, "overrides": reminders},
            "colorId": color_id,
            "extendedProperties": {
                "private": {
                    "transaction_id": str(transaction_id or ""),
                    "event_type": normalized_type,
                    "source_ref": source_ref,
                    "source_id": str(source_id),
                    "block_title": _safe_text(event_data.get("title")),
                }
            },
        }

    raise ValueError(f"Unsupported event_type: {event_type}")


def fetch_calendar_mapping(transaction_id, event_type, source_ref, calendar_id):
    ensure_calendar_sync_tables()
    rows = execute_query(
        """
        SELECT
            id, transaction_id, event_type, source_ref, source_id, source_label,
            calendar_id, google_event_id, event_hash, status, metadata, last_synced_at, created_at, updated_at
        FROM google_calendar_mappings
        WHERE transaction_id = %s
          AND event_type = %s
          AND source_ref = %s
          AND calendar_id = %s
        LIMIT 1
        """,
        (transaction_id, _safe_text(event_type).lower(), _safe_text(source_ref), _safe_text(calendar_id, "primary")),
        fetch=True,
    ) or []
    if not rows:
        return None
    row = rows[0]
    row["metadata"] = _parse_json_field(row.get("metadata"), {})
    return row


def fetch_calendar_mapping_by_event_id(google_event_id, calendar_id="primary"):
    ensure_calendar_sync_tables()
    rows = execute_query(
        """
        SELECT
            id, transaction_id, event_type, source_ref, source_id, source_label,
            calendar_id, google_event_id, event_hash, status, metadata, last_synced_at, created_at, updated_at
        FROM google_calendar_mappings
        WHERE google_event_id = %s
          AND calendar_id = %s
        LIMIT 1
        """,
        (_safe_text(google_event_id), _safe_text(calendar_id, "primary")),
        fetch=True,
    ) or []
    if not rows:
        return None
    row = rows[0]
    row["metadata"] = _parse_json_field(row.get("metadata"), {})
    return row


def store_calendar_event_id(
    transaction_id,
    event_type,
    google_event_id,
    source_ref="",
    source_id=0,
    source_label="",
    calendar_id="primary",
    event_hash="",
    metadata=None,
    status="active",
):
    ensure_calendar_sync_tables()
    rows = execute_query(
        """
        INSERT INTO google_calendar_mappings (
            transaction_id, event_type, source_ref, source_id, source_label,
            calendar_id, google_event_id, event_hash, status, metadata, last_synced_at, created_at, updated_at
        )
        VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s::jsonb, CURRENT_TIMESTAMP, CURRENT_TIMESTAMP, CURRENT_TIMESTAMP)
        ON CONFLICT (transaction_id, event_type, source_ref, calendar_id)
        DO UPDATE SET
            source_id = EXCLUDED.source_id,
            source_label = EXCLUDED.source_label,
            google_event_id = EXCLUDED.google_event_id,
            event_hash = EXCLUDED.event_hash,
            status = EXCLUDED.status,
            metadata = EXCLUDED.metadata,
            last_synced_at = CURRENT_TIMESTAMP,
            updated_at = CURRENT_TIMESTAMP
        RETURNING id
        """,
        (
            transaction_id,
            _safe_text(event_type).lower(),
            _safe_text(source_ref),
            int(source_id or 0),
            _safe_text(source_label),
            _safe_text(calendar_id, "primary"),
            _safe_text(google_event_id),
            _safe_text(event_hash),
            _safe_text(status, "active"),
            _json_dumps(metadata),
        ),
        fetch=True,
    ) or []
    return rows[0]["id"] if rows else None


def log_calendar_sync_event(
    action,
    transaction_id=None,
    mapping_id=None,
    event_type="",
    success=True,
    details="",
    metadata=None,
):
    ensure_calendar_sync_tables()
    execute_query(
        """
        INSERT INTO calendar_sync_audit_log (
            transaction_id, mapping_id, action, event_type, success, details, metadata, created_at
        )
        VALUES (%s, %s, %s, %s, %s, %s, %s::jsonb, CURRENT_TIMESTAMP)
        """,
        (
            transaction_id,
            mapping_id,
            _safe_text(action)[:40] or "sync",
            _safe_text(event_type).lower()[:40] or None,
            bool(success),
            _safe_text(details)[:1800] or None,
            _json_dumps(metadata),
        ),
    )


def _mark_mapping_status(mapping_id, status):
    execute_query(
        """
        UPDATE google_calendar_mappings
        SET status = %s,
            updated_at = CURRENT_TIMESTAMP
        WHERE id = %s
        """,
        (_safe_text(status, "active"), mapping_id),
    )


def sync_to_calendar(event_type, transaction_id, event_data, force_update=False):
    """
    Sync one transaction event to Google Calendar.

    Returns structured status for logs/UI flows.
    """
    ensure_calendar_sync_tables()
    settings = fetch_calendar_sync_settings()
    normalized_type = _safe_text(event_type).lower()
    if not _event_sync_enabled(settings, normalized_type):
        return {"success": False, "skipped": "event_type_disabled"}

    service, service_error = _calendar_service(settings)
    if not service:
        return {"success": False, "skipped": service_error or "service_unavailable"}

    calendar_id = _safe_text(event_data.get("calendar_id"), settings.get("calendar_id") or "primary")
    source_ref = _safe_text(event_data.get("source_ref"))
    if not source_ref:
        source_ref = f"{normalized_type}:{int(event_data.get('source_id') or 0)}"
    source_id = int(event_data.get("source_id") or 0)
    source_label = _safe_text(event_data.get("source_label"))

    try:
        payload = build_calendar_event_payload(normalized_type, transaction_id, event_data, settings.get("timezone"))
        payload_hash = _event_payload_hash(payload)
    except Exception as exc:
        log_calendar_sync_event(
            action="payload_error",
            transaction_id=transaction_id,
            event_type=normalized_type,
            success=False,
            details=str(exc),
            metadata={"source_ref": source_ref},
        )
        return {"success": False, "error": f"payload_error:{exc}"}

    mapping = fetch_calendar_mapping(transaction_id, normalized_type, source_ref, calendar_id)
    mapping_id = mapping["id"] if mapping else None
    if mapping and mapping.get("event_hash") == payload_hash and not force_update:
        log_calendar_sync_event(
            action="skip_no_change",
            transaction_id=transaction_id,
            mapping_id=mapping_id,
            event_type=normalized_type,
            success=True,
            details="No event changes detected.",
            metadata={"source_ref": source_ref},
        )
        return {
            "success": True,
            "action": "skipped",
            "reason": "no_change",
            "google_event_id": mapping.get("google_event_id"),
        }

    try:
        if mapping and mapping.get("google_event_id"):
            response = service.events().update(
                calendarId=calendar_id,
                eventId=mapping["google_event_id"],
                body=payload,
            ).execute()
            action = "updated"
        else:
            response = service.events().insert(calendarId=calendar_id, body=payload).execute()
            action = "created"

        google_event_id = _safe_text(response.get("id"))
        mapping_id = store_calendar_event_id(
            transaction_id=transaction_id,
            event_type=normalized_type,
            google_event_id=google_event_id,
            source_ref=source_ref,
            source_id=source_id,
            source_label=source_label,
            calendar_id=calendar_id,
            event_hash=payload_hash,
            metadata={
                "htmlLink": response.get("htmlLink"),
                "updated": response.get("updated"),
                "summary": payload.get("summary"),
            },
            status="active",
        )
        log_calendar_sync_event(
            action=action,
            transaction_id=transaction_id,
            mapping_id=mapping_id,
            event_type=normalized_type,
            success=True,
            details=f"Google event {action}: {google_event_id}",
            metadata={"source_ref": source_ref, "calendar_id": calendar_id},
        )
        return {
            "success": True,
            "action": action,
            "mapping_id": mapping_id,
            "google_event_id": google_event_id,
            "calendar_id": calendar_id,
            "html_link": response.get("htmlLink"),
        }
    except Exception as exc:
        log_calendar_sync_event(
            action="sync_failed",
            transaction_id=transaction_id,
            mapping_id=mapping_id,
            event_type=normalized_type,
            success=False,
            details=str(exc),
            metadata={"source_ref": source_ref, "calendar_id": calendar_id},
        )
        return {"success": False, "error": f"sync_failed:{exc}"}


def update_calendar_event(event_type, transaction_id, event_data):
    """Force-update one event even when hash matches."""
    return sync_to_calendar(event_type=event_type, transaction_id=transaction_id, event_data=event_data, force_update=True)


def _deadline_rows_for_sync(transaction_id):
    rows = execute_query(
        """
        SELECT id, deadline_type, deadline_date, description, completed
        FROM deadlines
        WHERE transaction_id = %s
        ORDER BY deadline_date ASC, id ASC
        """,
        (transaction_id,),
        fetch=True,
    ) or []
    return rows


def _transaction_row_for_sync(transaction_id):
    rows = execute_query(
        """
        SELECT id, property_address
        FROM transactions
        WHERE id = %s
        LIMIT 1
        """,
        (transaction_id,),
        fetch=True,
    ) or []
    return rows[0] if rows else None


def sync_all_deadlines(transaction_id, deadline_rows=None, transaction_row=None):
    """Sync all transaction deadlines as yellow all-day Google Calendar events."""
    ensure_calendar_sync_tables()
    transaction = transaction_row or _transaction_row_for_sync(transaction_id)
    if not transaction:
        return {"success": False, "error": "transaction_not_found"}
    rows = deadline_rows or _deadline_rows_for_sync(transaction_id)

    synced = 0
    failed = 0
    skipped = 0
    source_refs = []
    for row in rows:
        if not row.get("deadline_date"):
            continue
        source_ref = f"deadline:{_safe_text(row.get('deadline_type')).lower()}"
        source_refs.append(source_ref)
        event_data = {
            "source_ref": source_ref,
            "source_id": int(row.get("id") or 0),
            "source_label": _safe_text(row.get("deadline_type")).replace("_", " ").title(),
            "deadline_date": row.get("deadline_date"),
            "deadline_type": _safe_text(row.get("deadline_type")).lower(),
            "deadline_label": _safe_text(row.get("description")) or _safe_text(row.get("deadline_type")).replace("_", " ").title(),
            "property_address": transaction.get("property_address"),
            "summary_prefix": "DEADLINE",
            "description": (
                f"Deadline: {_safe_text(row.get('description')) or _safe_text(row.get('deadline_type')).replace('_', ' ').title()}\n"
                f"Transaction #{transaction_id}"
            ),
        }
        result = sync_to_calendar(event_type="deadline", transaction_id=transaction_id, event_data=event_data, force_update=True)
        if result.get("success"):
            synced += 1
        elif result.get("skipped"):
            skipped += 1
        else:
            failed += 1

    # Remove stale deadline events when deadline set changed.
    stale_rows = execute_query(
        """
        SELECT id, google_event_id, calendar_id, source_ref
        FROM google_calendar_mappings
        WHERE transaction_id = %s
          AND event_type = 'deadline'
          AND status = 'active'
        ORDER BY id ASC
        """,
        (transaction_id,),
        fetch=True,
    ) or []
    stale_deleted = 0
    for stale in stale_rows:
        if stale.get("source_ref") in source_refs:
            continue
        delete_result = delete_calendar_event_by_mapping(stale, reason="deadline_removed")
        if delete_result.get("success"):
            stale_deleted += 1

    return {
        "success": True,
        "synced": synced,
        "skipped": skipped,
        "failed": failed,
        "stale_deleted": stale_deleted,
    }


def delete_calendar_event_by_mapping(mapping_row, reason="manual_delete"):
    settings = fetch_calendar_sync_settings()
    service, service_error = _calendar_service(settings)
    mapping_id = mapping_row.get("id")
    google_event_id = _safe_text(mapping_row.get("google_event_id"))
    calendar_id = _safe_text(mapping_row.get("calendar_id"), settings.get("calendar_id") or "primary")
    if not google_event_id:
        return {"success": False, "error": "missing_google_event_id"}

    if service:
        try:
            service.events().delete(calendarId=calendar_id, eventId=google_event_id).execute()
        except Exception as exc:
            # Google returns 404 for already-deleted events; keep mapping cleanup.
            if "404" not in str(exc):
                log_calendar_sync_event(
                    action="delete_failed",
                    transaction_id=mapping_row.get("transaction_id"),
                    mapping_id=mapping_id,
                    event_type=mapping_row.get("event_type"),
                    success=False,
                    details=str(exc),
                    metadata={"reason": reason},
                )
                return {"success": False, "error": str(exc)}
    elif service_error:
        return {"success": False, "error": service_error}

    _mark_mapping_status(mapping_id, "deleted")
    log_calendar_sync_event(
        action="deleted",
        transaction_id=mapping_row.get("transaction_id"),
        mapping_id=mapping_id,
        event_type=mapping_row.get("event_type"),
        success=True,
        details=f"Deleted Google event {google_event_id}",
        metadata={"reason": reason},
    )
    return {"success": True}


def delete_calendar_events(transaction_id, event_type=None, reason="manual_delete"):
    """Delete all active mapped Google events for one transaction."""
    ensure_calendar_sync_tables()
    filters = ["transaction_id = %s", "status = 'active'"]
    params = [transaction_id]
    if event_type:
        filters.append("event_type = %s")
        params.append(_safe_text(event_type).lower())
    rows = execute_query(
        f"""
        SELECT id, transaction_id, event_type, source_ref, calendar_id, google_event_id
        FROM google_calendar_mappings
        WHERE {' AND '.join(filters)}
        ORDER BY id ASC
        """,
        tuple(params),
        fetch=True,
    ) or []

    deleted = 0
    failed = 0
    for row in rows:
        result = delete_calendar_event_by_mapping(row, reason=reason)
        if result.get("success"):
            deleted += 1
        else:
            failed += 1
    return {"success": True, "candidate_count": len(rows), "deleted": deleted, "failed": failed}


def fetch_calendar_mappings(transaction_id=None, limit=200):
    ensure_calendar_sync_tables()
    if transaction_id:
        rows = execute_query(
            """
            SELECT
                id, transaction_id, event_type, source_ref, source_id, source_label,
                calendar_id, google_event_id, event_hash, status, metadata, last_synced_at, created_at, updated_at
            FROM google_calendar_mappings
            WHERE transaction_id = %s
            ORDER BY updated_at DESC, id DESC
            LIMIT %s
            """,
            (transaction_id, int(limit)),
            fetch=True,
        ) or []
    else:
        rows = execute_query(
            """
            SELECT
                id, transaction_id, event_type, source_ref, source_id, source_label,
                calendar_id, google_event_id, event_hash, status, metadata, last_synced_at, created_at, updated_at
            FROM google_calendar_mappings
            ORDER BY updated_at DESC, id DESC
            LIMIT %s
            """,
            (int(limit),),
            fetch=True,
        ) or []
    for row in rows:
        row["metadata"] = _parse_json_field(row.get("metadata"), {})
    return rows


def fetch_calendar_sync_metrics(months=1):
    ensure_calendar_sync_tables()
    month_count = max(1, int(months or 1))
    start_date = date.today().replace(day=1)
    for _ in range(month_count - 1):
        start_date = (start_date.replace(day=1) - timedelta(days=1)).replace(day=1)
    rows = execute_query(
        """
        SELECT action, success, event_type, COUNT(*) AS total
        FROM calendar_sync_audit_log
        WHERE created_at >= %s
        GROUP BY action, success, event_type
        """,
        (start_date,),
        fetch=True,
    ) or []

    summary = {"created": 0, "updated": 0, "deleted": 0, "failed": 0, "webhook_updates": 0}
    event_type_counts = {}
    for row in rows:
        action = _safe_text(row.get("action")).lower()
        success = bool(row.get("success"))
        total = int(row.get("total") or 0)
        event_type = _safe_text(row.get("event_type")).lower() or "other"
        event_type_counts[event_type] = event_type_counts.get(event_type, 0) + total
        if action == "created" and success:
            summary["created"] += total
        elif action == "updated" and success:
            summary["updated"] += total
        elif action == "deleted" and success:
            summary["deleted"] += total
        elif action == "webhook_update" and success:
            summary["webhook_updates"] += total
        elif not success:
            summary["failed"] += total

    estimated_minutes_saved = (summary["created"] + summary["updated"] + summary["deleted"]) * 4
    return {
        "start_date": start_date,
        "summary": summary,
        "event_type_counts": event_type_counts,
        "estimated_minutes_saved": estimated_minutes_saved,
        "estimated_hours_saved": round(estimated_minutes_saved / 60.0, 1),
    }


def upsert_calendar_webhook_channel(channel_id, resource_id="", resource_uri="", expiration_ms=None, active=True):
    ensure_calendar_sync_tables()
    expiration_at = None
    if expiration_ms:
        try:
            expiration_at = datetime.utcfromtimestamp(int(expiration_ms) / 1000.0)
        except Exception:
            expiration_at = None
    execute_query(
        """
        INSERT INTO calendar_webhook_channels (
            channel_id, resource_id, resource_uri, expiration_at, active, created_at, updated_at
        )
        VALUES (%s, %s, %s, %s, %s, CURRENT_TIMESTAMP, CURRENT_TIMESTAMP)
        ON CONFLICT (channel_id)
        DO UPDATE SET
            resource_id = EXCLUDED.resource_id,
            resource_uri = EXCLUDED.resource_uri,
            expiration_at = EXCLUDED.expiration_at,
            active = EXCLUDED.active,
            updated_at = CURRENT_TIMESTAMP
        """,
        (
            _safe_text(channel_id),
            _safe_text(resource_id) or None,
            _safe_text(resource_uri) or None,
            expiration_at,
            bool(active),
        ),
    )

