import os
from urllib.parse import parse_qsl, quote, urlencode, urlsplit, urlunsplit

import psycopg2
from dotenv import load_dotenv
from psycopg2.extras import RealDictCursor

load_dotenv()


def _set_query_param(url: str, key: str, value: str) -> str:
    parts = urlsplit(url)
    query_params = dict(parse_qsl(parts.query, keep_blank_values=True))
    query_params[key] = value
    new_query = urlencode(query_params)
    return urlunsplit((parts.scheme, parts.netloc, parts.path, new_query, parts.fragment))


def _redact_url(url: str) -> str:
    try:
        parts = urlsplit(url)
        if not parts.hostname:
            return "<invalid-database-url>"
        port_part = f":{parts.port}" if parts.port else ""
        path = parts.path or ""
        query = f"?{parts.query}" if parts.query else ""
        return f"{parts.scheme}://***:***@{parts.hostname}{port_part}{path}{query}"
    except Exception:
        return "<redacted-database-url>"


def _maybe_encode_password(url: str) -> str:
    """
    Return URL with password URL-encoded when needed.

    Some providers and passwords containing reserved URI characters require
    percent-encoding for reliable parsing.
    """
    parts = urlsplit(url)
    if parts.password is None or parts.hostname is None:
        return url

    encoded_password = quote(parts.password, safe="")
    username = parts.username or ""
    host = parts.hostname
    port = f":{parts.port}" if parts.port else ""
    userinfo = f"{username}:{encoded_password}" if username else encoded_password
    netloc = f"{userinfo}@{host}{port}"
    return urlunsplit((parts.scheme, netloc, parts.path, parts.query, parts.fragment))


def _candidate_database_urls(database_url: str) -> list[str]:
    """
    Build candidate connection URLs with practical fallbacks.

    Priority:
    1) As provided
    2) Password-encoded variant
    3) Explicit sslmode from env
    4) Supabase pooler fallback matrix (require, prefer, disable)
    """
    candidates: list[str] = []

    def add(url: str) -> None:
        if url and url not in candidates:
            candidates.append(url)

    add(database_url)
    add(_maybe_encode_password(database_url))

    sslmode_env = (os.getenv("DATABASE_SSLMODE") or "").strip().lower()
    if sslmode_env:
        for base in list(candidates):
            add(_set_query_param(base, "sslmode", sslmode_env))

    is_supabase_pooler = "pooler.supabase.com" in database_url
    if is_supabase_pooler:
        for mode in ("require", "prefer", "disable"):
            for base in list(candidates):
                add(_set_query_param(base, "sslmode", mode))

    return candidates


def get_db_connection():
    """Get PostgreSQL database connection."""
    database_url = os.getenv("DATABASE_URL")
    if not database_url:
        print("Database connection error: DATABASE_URL is not set")
        return None

    timeout = int((os.getenv("DATABASE_CONNECT_TIMEOUT") or "8").strip())
    errors: list[str] = []
    for candidate_url in _candidate_database_urls(database_url):
        try:
            conn = psycopg2.connect(
                candidate_url,
                cursor_factory=RealDictCursor,
                connect_timeout=timeout,
            )
            return conn
        except Exception as exc:
            errors.append(f"{_redact_url(candidate_url)} -> {exc}")

    print("Database connection error: all connection attempts failed.")
    for attempt_error in errors:
        print(f"  - {attempt_error}")
    return None


def execute_query(query, params=None, fetch=False):
    """Execute SQL query with error handling."""
    conn = get_db_connection()
    if not conn:
        return None

    cur = None
    try:
        cur = conn.cursor()
        cur.execute(query, params or ())

        if fetch:
            result = cur.fetchall()
            conn.commit()
            return result

        conn.commit()
        return True
    except Exception as exc:
        print(f"Query execution error: {exc}")
        conn.rollback()
        return None
    finally:
        if cur:
            cur.close()
        conn.close()


def execute_insert(query, params=None, return_id=True):
    """Execute INSERT and return new ID."""
    conn = get_db_connection()
    if not conn:
        return None

    cur = None
    try:
        cur = conn.cursor()
        cur.execute(query, params or ())

        if return_id:
            row = cur.fetchone()
            new_id = row["id"] if row and "id" in row else None
            conn.commit()
            return new_id

        conn.commit()
        return True
    except Exception as exc:
        print(f"Insert error: {exc}")
        conn.rollback()
        return None
    finally:
        if cur:
            cur.close()
        conn.close()


def get_active_transactions(limit=500):
    """Return active transactions with key contact/deadline fields."""
    rows = execute_query(
        """
        SELECT
            id,
            property_address,
            contract_price,
            agent_name,
            agent_phone,
            agent_email,
            buyer_name,
            buyer_phone,
            seller_name,
            seller_phone,
            lender_name,
            lender_phone,
            lender_email,
            title_company,
            title_officer_phone,
            title_officer_email,
            rush_service,
            status
        FROM transactions
        WHERE status = 'ACTIVE'
        ORDER BY COALESCE(closing_date, CURRENT_DATE + INTERVAL '365 days') ASC, id ASC
        LIMIT %s
        """,
        (int(limit),),
        fetch=True,
    ) or []
    return rows


def get_transaction_deadlines(transaction_id):
    """Return deadline rows for one transaction sorted by date."""
    rows = execute_query(
        """
        SELECT
            id,
            transaction_id,
            deadline_type,
            deadline_date,
            description,
            completed,
            is_critical,
            created_at
        FROM deadlines
        WHERE transaction_id = %s
        ORDER BY deadline_date ASC, id ASC
        """,
        (transaction_id,),
        fetch=True,
    ) or []
    return rows
