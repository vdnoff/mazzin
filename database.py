"""Thin MySQL helpers. No ORM, no pooling.

Driver is PyMySQL. Connect-per-request is fine for Phase 1 traffic.
Autocommit is OFF — callers commit explicitly so a failed multi-statement
write leaves nothing half-applied.
"""

import pymysql
import pymysql.cursors

import config


def get_db():
    """Open a new MySQL connection with autocommit disabled."""
    return pymysql.connect(
        host=config.DB_HOST,
        user=config.DB_USER,
        password=config.DB_PASSWORD,
        database=config.DB_NAME,
        charset="utf8mb4",
        autocommit=False,
        cursorclass=pymysql.cursors.DictCursor,
    )


def execute(query, params=None):
    """Run a write statement and commit. Returns lastrowid."""
    conn = get_db()
    try:
        with conn.cursor() as cur:
            cur.execute(query, params or ())
            conn.commit()
            return cur.lastrowid
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


def query_all(query, params=None):
    """Run a SELECT and return all rows as dicts."""
    conn = get_db()
    try:
        with conn.cursor() as cur:
            cur.execute(query, params or ())
            return cur.fetchall()
    finally:
        conn.close()


def query_one(query, params=None):
    """Run a SELECT and return the first row as a dict, or None."""
    conn = get_db()
    try:
        with conn.cursor() as cur:
            cur.execute(query, params or ())
            return cur.fetchone()
    finally:
        conn.close()
