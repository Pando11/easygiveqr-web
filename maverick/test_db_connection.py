#!/usr/bin/env python3
"""
Simple database connection test for Maverick.
"""

import os
from pathlib import Path

import psycopg2
from dotenv import load_dotenv


def main() -> None:
    """Load DATABASE_URL, test connection, and print transactions row count."""
    env_path = Path(__file__).resolve().parent / ".env"
    load_dotenv(dotenv_path=env_path)

    database_url = os.getenv("DATABASE_URL", "").strip()
    if not database_url:
        print("❌ DATABASE_URL is missing in .env")
        return

    conn = None
    cur = None
    try:
        conn = psycopg2.connect(database_url)
        cur = conn.cursor()
        cur.execute("SELECT COUNT(*) FROM transactions")
        row = cur.fetchone()
        count = row[0] if row else 0

        print("✅ Database connection successful!")
        print(f"Transactions table row count: {count}")
    except Exception as exc:
        print(f"❌ Database connection failed: {exc}")
    finally:
        if cur is not None:
            cur.close()
        if conn is not None:
            conn.close()


if __name__ == "__main__":
    main()
