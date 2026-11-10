"""The Loan Options funnel's API: `POST /api/loans/lead`, `POST /api/loans/event`.

/loans is a comparison flow, not a swipe quiz: a visitor answers six closed
questions and is shown advertisements. This module is the whole of what the
server does about it. One route upserts the six answers into `loan_leads`,
keyed by the browser's session id, so a visitor who edits an answer
overwrites their row instead of adding one. The other writes one row into the
existing `events` table with `funnel = 'loans'`. One validated write each,
204, nothing else.

What it owns: both routes, the closed sets every answer is checked against,
and the one upsert statement. The events INSERT is tracking.py's own, reused
rather than restated, and so is the cleaning of the attribution fields.

What it never does: read. There is no SELECT here and no call that returns a
row. It never accepts free text: every answer is a member of a set this file
enumerates, an unknown key is a 400, and the only strings stored as given are
the five attribution fields, trimmed and cut to length exactly as /api/track
does it. It never touches the request's IP address or User-Agent, never takes
a name, an email, a phone number or anything else that identifies a person,
and never puts a request body in a log line: bad input is a bare 400 and a
database failure is a traceback with no payload beside it. It makes no
payment, no Stripe call and no model call, and it does not know what a lender
is.

A missing `loan_leads` table is a 500 on the lead route and nothing more: the
page is a static file, the browser ignores the failure and shows the options
anyway.
"""
import json
import logging
import re

from flask import Blueprint, request

import database
import tracking

log = logging.getLogger(__name__)

bp = Blueprint("loans", __name__)

FUNNEL = "loans"

AMOUNT_MIN = 100
AMOUNT_MAX = 5000
AMOUNT_STEP = 100

PURPOSES = frozenset(("emergency", "debt", "car", "home", "medical", "other"))
EMPLOYMENTS = frozenset(("employed", "self", "benefits", "retired"))
INCOMES = frozenset(("lt1000", "1000_2000", "2000_3000", "3000_4500",
                     "gt4500"))
CREDITS = frozenset(("excellent", "good", "fair", "building"))
# The fifty states and DC.
STATES = frozenset((
    "AL AK AZ AR CA CO CT DE DC FL GA HI ID IL IN IA KS KY LA ME MD MA MI MN "
    "MS MO MT NE NV NH NJ NM NY NC ND OH OK OR PA RI SC SD TN TX UT VT VA WA "
    "WV WI WY").split())

# Answer key in the request -> the set it must belong to.
CHOICES = (
    ("purpose", PURPOSES),
    ("employment", EMPLOYMENTS),
    ("income", INCOMES),
    ("credit", CREDITS),
    ("state", STATES),
)

ATTRIBUTION = tuple(tracking.ATTRIBUTION_FIELDS)
LEAD_KEYS = frozenset(("session_id", "amount") + tuple(k for k, _ in CHOICES)
                      + ATTRIBUTION)
EVENT_KEYS = frozenset(("session_id", "event", "step", "extra") + ATTRIBUTION)

# A subset of the names /api/track knows, so the dashboard's funnel reads
# this one without a new vocabulary. `swipe` is an answered step: 1 amount,
# 2 purpose, 3 income, 4 credit and state.
EVENTS = frozenset(("funnel_start", "swipe", "result_view", "offer_tap"))
STEP_MAX = 4
# Which sponsored element was tapped: the options card's button or one of the
# related-search rows. A short lowercase token and nothing else.
SLOT_RE = re.compile(r"[a-z0-9_-]{1,40}")

# One statement. The unique key on session_id is what turns a second submit
# into an overwrite of the first.
UPSERT_SQL = (
    "INSERT INTO loan_leads "
    "(session_id, amount_usd, purpose, employment, income_band, credit_band, "
    " state, subid, utm_source, utm_campaign, utm_content, utm_term) "
    "VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s) "
    "ON DUPLICATE KEY UPDATE "
    "amount_usd = VALUES(amount_usd), purpose = VALUES(purpose), "
    "employment = VALUES(employment), income_band = VALUES(income_band), "
    "credit_band = VALUES(credit_band), state = VALUES(state), "
    "subid = VALUES(subid), utm_source = VALUES(utm_source), "
    "utm_campaign = VALUES(utm_campaign), utm_content = VALUES(utm_content), "
    "utm_term = VALUES(utm_term)"
)


def _body(allowed):
    """The JSON object in the request, or None when it is not one this route
    takes: not an object, or carrying a key outside `allowed`."""
    body = request.get_json(silent=True, force=True)
    if not isinstance(body, dict) or not set(body) <= allowed:
        return None
    return body


def _session(body):
    value = body.get("session_id")
    # fullmatch, not match: `$` lets a trailing newline through, and this
    # value is a key.
    if isinstance(value, str) and tracking.UUID_RE.fullmatch(value):
        return value.lower()
    return None


def _attribution(body):
    """The five attribution columns, in column order, cleaned as /api/track
    cleans them."""
    return tuple(
        tracking._clean_optional(body.get(name), max_len)
        for name, max_len in tracking.ATTRIBUTION_FIELDS.items())


def _is_int(value):
    # `True` is an int in Python and 500.0 is not one in the schema.
    return type(value) is int


@bp.post("/api/loans/lead")
def lead():
    body = _body(LEAD_KEYS)
    if body is None:
        return "", 400
    session_id = _session(body)
    if session_id is None:
        return "", 400

    amount = body.get("amount")
    if (not _is_int(amount) or not AMOUNT_MIN <= amount <= AMOUNT_MAX
            or amount % AMOUNT_STEP):
        return "", 400

    answers = []
    for key, allowed in CHOICES:
        value = body.get(key)
        if not isinstance(value, str) or value not in allowed:
            return "", 400
        answers.append(value)

    try:
        database.execute(
            UPSERT_SQL,
            (session_id, amount) + tuple(answers) + _attribution(body))
    except Exception:
        # No payload: the traceback and this sentence are the whole line.
        log.exception("loan lead write failed")
        return "", 500
    return "", 204


@bp.post("/api/loans/event")
def event():
    body = _body(EVENT_KEYS)
    if body is None:
        return "", 400
    session_id = _session(body)
    if session_id is None:
        return "", 400

    name = body.get("event")
    if not isinstance(name, str) or name not in EVENTS:
        return "", 400

    step = body.get("step")
    if name == "swipe":
        if not _is_int(step) or not 1 <= step <= STEP_MAX:
            return "", 400
    elif step is not None:
        return "", 400

    extra = body.get("extra")
    extra_json = None
    if name == "offer_tap":
        # Rebuilt, not passed through: one key, one checked token.
        if not isinstance(extra, dict) or set(extra) != {"slot"}:
            return "", 400
        slot = extra["slot"]
        if not isinstance(slot, str) or not SLOT_RE.fullmatch(slot):
            return "", 400
        extra_json = json.dumps({"slot": slot}, separators=(",", ":"))
    elif extra is not None:
        return "", 400

    try:
        database.execute(
            tracking.INSERT_SQL,
            (FUNNEL, session_id, name, step) + _attribution(body)
            + (extra_json,))
    except Exception:
        log.exception("loan event write failed")
        return "", 500
    return "", 204
