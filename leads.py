"""The email gate: `POST /api/lead`.

A funnel that carries a `lead_gate` block asks for an address where the
others ask for a price. This route is the whole of what happens when the
reader gives one: the address is validated, one row goes into `leads`, one
tracking event is written, the report is rendered and mailed, and the
browser is handed the URL of the article to open — the funnel's own
article in the reader's language, anchored to the section for their style.

The mail goes inline, on the request, because there is no runner on the
server to hand it to. It is kept fast by construction: the report is the
warmed style cache plus the stubs (never a model call — see
reports.lead_content), the PDF is the light renderer, and Resend is one
POST. A render or a send that fails is logged by type, leaves
`report_sent_at` NULL and does not touch the answer: the reader is
redirected to the article either way, and scripts/send_lead_reports.py
re-sends what is still NULL by hand. One log line carries the render+send
time in milliseconds.

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
import time

from flask import Blueprint, jsonify, request

import config
import database
import payments
import reports
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
# The receipt. Conditional, so a row the script is re-sending at the same
# moment is stamped once and a stamp never moves an earlier one.
STAMP_SQL = ("UPDATE leads SET report_sent_at = NOW() "
             "WHERE id = %s AND report_sent_at IS NULL")


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


def scores_of(row):
    """The stored tag scores back out of a row, or None."""
    raw = row.get("scores_json")
    if not raw:
        return None
    if isinstance(raw, dict):
        return raw
    try:
        data = json.loads(raw)
    except ValueError:
        return None
    return data if isinstance(data, dict) else None


def send_report_for(row, send=None):
    """Render and mail one lead's report. True when Resend took it.

    The one routine for both callers: the route, right after the row is
    written, and scripts/send_lead_reports.py for a row still NULL. `row` is
    the leads row — id, email, funnel, style_key, scores_json — and `send`
    is reports.send_lead_email unless a test hands in another. Raises
    whatever the render or the send raises; the callers decide what a
    failure costs, and here it costs the reader nothing.
    """
    send = send or reports.send_lead_email
    cfg = config.load_funnel(row["funnel"])
    gate = gate_of(cfg)
    if gate is None:
        raise ValueError("%s has no lead_gate" % row["funnel"])
    scores = scores_of(row)
    content = reports.lead_content(row["funnel"], row["style_key"], scores)
    link = article_link(gate, row["style_key"], UTM_EMAIL)
    return bool(send(row["id"], row["email"], cfg, content, scores, link))


def _deliver(row):
    """The inline send: render, mail, stamp — and never fail the request.

    Timed and logged as one line by lead id, with the outcome and the
    exception's type when there was one. Never the address: the row holds
    it, the mail carries it, the log does not.
    """
    started = time.monotonic()
    try:
        sent = send_report_for(row)
    except Exception as exc:                    # noqa: BLE001
        log.error("lead %s: report not sent (%s) after %d ms — left for "
                  "send_lead_reports.py", row["id"], type(exc).__name__,
                  int((time.monotonic() - started) * 1000))
        return False
    elapsed = int((time.monotonic() - started) * 1000)
    if not sent:
        log.warning("lead %s: report not sent after %d ms — left for "
                    "send_lead_reports.py", row["id"], elapsed)
        return False
    try:
        database.execute_rowcount(STAMP_SQL, (row["id"],))
    except Exception as exc:                    # noqa: BLE001
        log.error("lead %s: sent but not stamped (%s)", row["id"],
                  type(exc).__name__)
    log.info("lead %s: report rendered and sent in %d ms", row["id"], elapsed)
    return True


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

    scores_json = (json.dumps(scores, separators=(",", ":"), sort_keys=True)
                   if scores else None)
    event = "lead_submit"
    lead_id = None
    try:
        lead_id = database.execute(INSERT_SQL, (
            email, funnel, lang, style_key, scores_json, subid, session_id,
            opt_in))
    except Exception as exc:
        if not _is_duplicate(exc):
            # The type only. The body carries the address.
            log.error("lead insert failed for %s: %s", funnel,
                      type(exc).__name__)
            return "", 500
        event = "lead_dup"

    tracking.record_event(funnel, session_id, event, {"subid": subid})
    # The mail, for a new row only: a duplicate already had its report, and
    # is redirected exactly as the first time. Whatever happens in here, the
    # answer below is the same — the article is not held hostage to Resend.
    if event == "lead_submit":
        _deliver({"id": lead_id, "email": email, "funnel": funnel,
                  "lang": lang, "style_key": style_key,
                  "scores_json": scores_json})
    return jsonify({"redirect_url": article_link(gate, style_key)})
