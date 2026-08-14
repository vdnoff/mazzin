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


def execute_rowcount(query, params=None):
    """Run a write statement and commit. Returns how many rows it changed.

    The same call as `execute`, answering the other question. `execute` returns
    a lastrowid, which an UPDATE does not have — so a conditional UPDATE used
    as a claim ("take this slot only if it is still free") has no way to say
    whether it took it. That answer is the whole point of writing the condition
    into the statement instead of reading, deciding and then writing, so it
    needs a caller that can hear it.
    """
    conn = get_db()
    try:
        with conn.cursor() as cur:
            count = cur.execute(query, params or ())
            conn.commit()
            return count
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
