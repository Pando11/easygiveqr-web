#!/usr/bin/env python3
"""
Simple database connection test for Maverick.
"""

import os
from pathlib import Path
from urllib.parse import parse_qsl, quote, urlencode, urlsplit, urlunsplit

import psycopg2
from dotenv import load_dotenv


def _set_query_param(url: str, key: str, value: str) -> str:
    parts = urlsplit(url)
    query_params = dict(parse_qsl(parts.query, keep_blank_values=True))
    query_params[key] = value
    new_query = urlencode(query_params)
    return urlunsplit((parts.scheme, parts.netloc, parts.path, new_query, parts.fragment))


def _maybe_encode_password(url: str) -> str:
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


def _candidate_urls(database_url: str) -> list[str]:
    urls: list[str] = []

    def add(url: str) -> None:
        if url and url not in urls:
            urls.append(url)

    add(database_url)
    add(_maybe_encode_password(database_url))

    sslmode_env = (os.getenv("DATABASE_SSLMODE") or "").strip().lower()
    if sslmode_env:
        for base in list(urls):
            add(_set_query_param(base, "sslmode", sslmode_env))

    if "pooler.supabase.com" in database_url:
        for mode in ("require", "prefer", "disable"):
            for base in list(urls):
                add(_set_query_param(base, "sslmode", mode))

    return urls


def main() -> None:
    """Load DATABASE_URL, test connection, and print transactions row count."""
    env_path = Path(__file__).resolve().parent / ".env"
    load_dotenv(dotenv_path=env_path)

    database_url = os.getenv("DATABASE_URL", "").strip()
    if not database_url:
        print("❌ DATABASE_URL is missing in .env")
        return

    timeout = int((os.getenv("DATABASE_CONNECT_TIMEOUT") or "8").strip())
    errors: list[str] = []
    for candidate_url in _candidate_urls(database_url):
        conn = None
        cur = None
        try:
            conn = psycopg2.connect(candidate_url, connect_timeout=timeout)
            cur = conn.cursor()
            cur.execute("SELECT COUNT(*) FROM transactions")
            row = cur.fetchone()
            count = row[0] if row else 0

            print("✅ Database connection successful!")
            print(f"Transactions table row count: {count}")
            return
        except Exception as exc:
            errors.append(str(exc))
        finally:
            if cur is not None:
                cur.close()
            if conn is not None:
                conn.close()

    print("❌ Database connection failed:")
    for idx, error in enumerate(errors, start=1):
        print(f"  {idx}. {error}")


if __name__ == "__main__":
    main()
