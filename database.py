"""Thin MySQL helpers. No ORM, no pooling.

Connect-per-request is fine for Phase 1 traffic. Autocommit is OFF —
callers commit explicitly so a failed multi-statement write leaves nothing
half-applied.
"""

import mysql.connector

import config


def get_db():
    """Open a new MySQL connection with autocommit disabled."""
    return mysql.connector.connect(
        host=config.DB_HOST,
        user=config.DB_USER,
        password=config.DB_PASSWORD,
        database=config.DB_NAME,
        autocommit=False,
        charset="utf8mb4",
        use_unicode=True,
    )


def execute(query, params=None):
    """Run a write statement and commit. Returns lastrowid."""
    conn = get_db()
    try:
        cur = conn.cursor()
        try:
            cur.execute(query, params or ())
            conn.commit()
            return cur.lastrowid
        finally:
            cur.close()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


def query_all(query, params=None):
    """Run a SELECT and return all rows as dicts."""
    conn = get_db()
    try:
        cur = conn.cursor(dictionary=True)
        try:
            cur.execute(query, params or ())
            return cur.fetchall()
        finally:
            cur.close()
    finally:
        conn.close()


def query_one(query, params=None):
    """Run a SELECT and return the first row as a dict, or None."""
    conn = get_db()
    try:
        cur = conn.cursor(dictionary=True)
        try:
            cur.execute(query, params or ())
            row = cur.fetchone()
            cur.fetchall()  # drain so the connection closes cleanly
            return row
        finally:
            cur.close()
    finally:
        conn.close()
