import os

import psycopg2
from dotenv import load_dotenv
from psycopg2.extras import RealDictCursor

load_dotenv()


def get_db_connection():
    """Get PostgreSQL database connection."""
    database_url = os.getenv("DATABASE_URL")
    if not database_url:
        print("Database connection error: DATABASE_URL is not set")
        return None

    try:
        conn = psycopg2.connect(database_url, cursor_factory=RealDictCursor)
        return conn
    except Exception as exc:
        print(f"Database connection error: {exc}")
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
