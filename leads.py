"""The email gate: `POST /api/lead`.

A funnel that carries a `lead_gate` block asks for an address where the
others ask for a price. This route is the whole of what happens when the
reader gives one: the address is validated, one row goes into `leads`, one
tracking event is written, and the browser is handed the URL of the article
to open — the funnel's own article in the reader's language, anchored to
the section for their style. The report itself is not built here: that is
a PDF render and a mail call, and scripts/send_lead_reports.py does both
off the request, from the row this route wrote.

Idempotent on (email, funnel). A second submit of the same address hits the
unique key, is answered exactly as the first — same redirect, 200 — and
sends nothing more; it is counted as `lead_dup` so the two can be told
apart in the events table.

No PII in logs: the address is never in a log line, a warning or an
exception message this module writes. A bad request is a bare 400.
"""
import json
import logging
import re

from flask import Blueprint, jsonify, request

import config
import database
import payments
import tracking

log = logging.getLogger(__name__)

bp = Blueprint("leads", __name__)

EMAIL_MAX = 320
# The shape of an address and nothing cleverer: something, an @, a domain
# with a dot in it, no whitespace. Deliverability is Resend's problem.
EMAIL_RE = re.compile(r"^[^\s@]+@[^\s@]+\.[^\s@]{2,}$")
UTM_REDIRECT = "utm_source=mazzin&utm_medium=redirect&utm_campaign=%s"
UTM_EMAIL = "utm_source=mazzin&utm_medium=email&utm_campaign=%s"
# MySQL's duplicate-key error, which is the one failure here that is not one.
ER_DUP_ENTRY = 1062

INSERT_SQL = (
    "INSERT INTO leads (email, funnel, lang, style_key, scores_json, subid, "
    "session_id, marketing_opt_in) VALUES (%s, %s, %s, %s, %s, %s, %s, %s)"
)


def clean_email(value):
    """The address, lower-cased and trimmed, or None when it is not one."""
    if not isinstance(value, str):
        return None
    value = value.strip()
    if not value or len(value) > EMAIL_MAX or not EMAIL_RE.match(value):
        return None
    return value.lower()


def gate_of(cfg):
    """The funnel's `lead_gate` block, or None when it sells for money."""
    block = (cfg or {}).get("lead_gate")
    return block if isinstance(block, dict) and block.get("article_url") \
        else None


def article_link(gate, style_key, medium=UTM_REDIRECT):
    """The article for this style: the funnel's URL, the UTM triplet, the
    style's anchor.

    The canonical `?p=` form already carries a query string, so the UTM
    parameters are joined with `&`; a URL without one gets a `?`. The anchor
    goes last, after the query, which is what a 301 to the pretty URL
    preserves.
    """
    url = str(gate.get("article_url") or "")
    campaign = str(gate.get("utm_campaign") or "")
    joiner = "&" if "?" in url else "?"
    link = url + joiner + medium % campaign
    anchor = (gate.get("anchors") or {}).get(style_key) or ""
    if anchor:
        link += anchor if anchor.startswith("#") else "#" + anchor
    return link


def _is_duplicate(exc):
    args = getattr(exc, "args", ())
    return bool(args) and args[0] == ER_DUP_ENTRY


@bp.post("/api/lead")
def lead():
    body = request.get_json(silent=True, force=True)
    if not isinstance(body, dict):
        return "", 400

    funnel = body.get("funnel")
    if not config.funnel_exists(funnel):
        return "", 400
    cfg = config.load_funnel(funnel)
    gate = gate_of(cfg)
    if gate is None:
        # A funnel that sells for money has no gate to submit to.
        return "", 404

    email = clean_email(body.get("email"))
    if email is None:
        return "", 400

    style_key = body.get("style_key")
    known = [s.get("id") for s in (cfg.get("styles") or [])]
    if not isinstance(style_key, str) or style_key not in known:
        return "", 400

    # The language is the funnel's, not the client's: a generated funnel
    # declares its locale and the master is English. The client's word is
    # only taken when the config has none.
    lang = cfg.get("locale") or body.get("lang") or "en"
    if not isinstance(lang, str) or not re.match(r"^[a-z]{2,8}$", lang):
        lang = "en"

    scores = payments._clean_tag_scores(cfg, body.get("scores"))
    session_id = body.get("session_id")
    if not isinstance(session_id, str) or not tracking.UUID_RE.match(session_id):
        session_id = None
    subid = tracking._clean_optional(body.get("subid"),
                                     tracking.ATTRIBUTION_FIELDS["subid"])
    opt_in = 1 if body.get("marketing_opt_in") is True else 0

    event = "lead_submit"
    try:
        database.execute(INSERT_SQL, (
            email, funnel, lang, style_key,
            json.dumps(scores, separators=(",", ":"), sort_keys=True)
            if scores else None,
            subid, session_id, opt_in))
    except Exception as exc:
        if not _is_duplicate(exc):
            # The type only. The body carries the address.
            log.error("lead insert failed for %s: %s", funnel,
                      type(exc).__name__)
            return "", 500
        event = "lead_dup"

    tracking.record_event(funnel, session_id, event, {"subid": subid})
    return jsonify({"redirect_url": article_link(gate, style_key)})
