"""Event tracking API.

One endpoint, one INSERT, no reads. This is on the hot path of every swipe,
so it stays boring and fast.

Nothing user-supplied is ever written to the error log — bad input gets a
bare 400 and a counter-style log line at most.
"""

import json
import logging
import re

from flask import Blueprint, request

import config
import database

log = logging.getLogger(__name__)

bp = Blueprint("tracking", __name__)

# `purchase` is deliberately absent: it is written server-side by the Stripe
# webhook in Phase 1b and must never be client-assertable.
ALLOWED_EVENTS = {
    "funnel_start",
    "swipe",
    "result_view",
    "paywall_view",
    "pay_tap",
}

UUID_RE = re.compile(
    r"^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$",
    re.IGNORECASE,
)

# Column name -> max length, for the optional attribution fields.
ATTRIBUTION_FIELDS = {
    "subid": 128,
    "utm_source": 64,
    "utm_campaign": 128,
    "utm_content": 128,
    "utm_term": 128,
}

INSERT_SQL = (
    "INSERT INTO events "
    "(funnel, session_id, event, step, subid, utm_source, utm_campaign, "
    " utm_content, utm_term, extra) "
    "VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s)"
)


def _clean_optional(value, max_len):
    """Coerce an optional short string field, or None if unusable."""
    if value is None:
        return None
    if not isinstance(value, str):
        return None
    value = value.strip()
    if not value:
        return None
    return value[:max_len]


def _clean_step(value):
    """Return an int step in 1..20, or None. Raises ValueError if invalid."""
    if value is None:
        return None
    if isinstance(value, bool) or not isinstance(value, int):
        raise ValueError("step")
    if not 1 <= value <= 20:
        raise ValueError("step")
    return value


@bp.post("/api/track")
def track():
    body = request.get_json(silent=True, force=True)
    if not isinstance(body, dict):
        return "", 400

    funnel = body.get("funnel")
    if not config.funnel_exists(funnel):
        return "", 400

    session_id = body.get("session_id")
    if not isinstance(session_id, str) or not UUID_RE.match(session_id):
        return "", 400

    event = body.get("event")
    if event not in ALLOWED_EVENTS:
        return "", 400

    try:
        step = _clean_step(body.get("step"))
    except ValueError:
        return "", 400

    extra = body.get("extra")
    if extra is None:
        extra_json = None
    elif isinstance(extra, (dict, list)):
        extra_json = json.dumps(extra, separators=(",", ":"))[:4000]
    else:
        return "", 400

    attribution = {
        name: _clean_optional(body.get(name), max_len)
        for name, max_len in ATTRIBUTION_FIELDS.items()
    }

    try:
        database.execute(
            INSERT_SQL,
            (
                funnel,
                session_id,
                event,
                step,
                attribution["subid"],
                attribution["utm_source"],
                attribution["utm_campaign"],
                attribution["utm_content"],
                attribution["utm_term"],
                extra_json,
            ),
        )
    except Exception:
        # No payload, no session id, no IP — just the fact that it failed.
        log.exception("track insert failed")
        return "", 500

    return "", 204
