"""Stripe checkout, webhook and report delivery.

The webhook is the only writer of `purchases`. Nothing the client says about
a payment is trusted, and the client never supplies an amount — prices are
read server-side from the funnel config.

Amounts are integer cents everywhere in this module, which is what Stripe
sends and what MySQL stores. No float ever touches a money value; a Decimal
is used wherever a fractional amount is actually computed.

No email address, address or raw request body is ever written to a log line.
"""

import json
import logging
import re

import pymysql.err
import stripe
from flask import Blueprint, jsonify, request

import config
import database
import reports

log = logging.getLogger(__name__)

bp = Blueprint("payments", __name__)

stripe.api_key = config.STRIPE_SECRET_KEY

UUID_RE = re.compile(
    r"^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$",
    re.IGNORECASE,
)

# Stripe checkout session ids: cs_test_... / cs_live_...
CHECKOUT_SESSION_RE = re.compile(r"^cs_[A-Za-z0-9_]{1,250}$")

INSERT_PURCHASE_SQL = (
    "INSERT INTO purchases "
    "(funnel, session_id, stripe_event_id, payment_intent, checkout_session, "
    " amount_cents, currency, email, country, result_style, status) "
    "VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)"
)

INSERT_PURCHASE_EVENT_SQL = (
    "INSERT INTO events (funnel, session_id, event) VALUES (%s, %s, 'purchase')"
)

SELECT_PURCHASE_SQL = (
    "SELECT id, funnel, session_id, result_style, status FROM purchases "
    "WHERE checkout_session = %s LIMIT 1"
)

SELECT_REPORT_SQL = (
    "SELECT content FROM reports WHERE purchase_id = %s ORDER BY id DESC LIMIT 1"
)


def _style_ids(cfg):
    return {s.get("id") for s in cfg.get("styles", [])}


# --- POST /api/checkout ----------------------------------------------------


@bp.post("/api/checkout")
def checkout():
    body = request.get_json(silent=True, force=True)
    if not isinstance(body, dict):
        return jsonify({}), 400

    slug = body.get("funnel")
    if not config.funnel_exists(slug):
        return jsonify({}), 400

    session_id = body.get("session_id")
    if not isinstance(session_id, str) or not UUID_RE.match(session_id):
        return jsonify({}), 400

    cfg = config.load_funnel(slug)

    result_style = body.get("result_style")
    if result_style not in _style_ids(cfg):
        return jsonify({}), 400

    pricing = cfg.get("pricing") or {}
    amount_cents = pricing.get("amount_cents")
    currency = pricing.get("currency")
    if not isinstance(amount_cents, int) or amount_cents <= 0 or not currency:
        log.error("funnel %s has no usable price", slug)
        return jsonify({}), 502

    title = (cfg.get("meta") or {}).get("title") or slug
    product_name = "%s — Full Style Report" % title

    if not stripe.api_key:
        log.error("STRIPE_SECRET_KEY is not configured")
        return jsonify({}), 502

    try:
        session = stripe.checkout.Session.create(
            mode="payment",
            line_items=[
                {
                    "quantity": 1,
                    "price_data": {
                        "currency": currency,
                        "unit_amount": amount_cents,
                        "product_data": {"name": product_name},
                    },
                }
            ],
            # No payment_method_types: the account runs Managed Payments,
            # which rejects the parameter and picks the methods itself.
            # Wallets surface on their own when the device supports them.
            success_url="%s/%s?cs={CHECKOUT_SESSION_ID}" % (config.BASE_URL, slug),
            cancel_url="%s/%s?canceled=1" % (config.BASE_URL, slug),
            metadata={
                "funnel": slug,
                "session_id": session_id,
                "result_style": result_style,
            },
            customer_creation="if_required",
        )
    except Exception:
        # Stripe's message can echo request contents — log the type only.
        log.exception("stripe checkout session create failed for funnel %s", slug)
        return jsonify({}), 502

    return jsonify({"url": session.url})


# --- POST /api/stripe/webhook ----------------------------------------------


def _record_side_effects(purchase_id, slug, session_id, result_style):
    """Report stub + server-side purchase event. Never fatal to the webhook."""
    try:
        reports.generate_report(purchase_id, slug, result_style)
    except Exception:
        log.exception("report generation failed for purchase %s", purchase_id)

    try:
        database.execute(INSERT_PURCHASE_EVENT_SQL, (slug, session_id))
    except Exception:
        log.exception("purchase event insert failed for purchase %s", purchase_id)


@bp.post("/api/stripe/webhook")
def stripe_webhook():
    payload = request.get_data()
    signature = request.headers.get("Stripe-Signature", "")

    if not config.STRIPE_WEBHOOK_SECRET:
        log.error("STRIPE_WEBHOOK_SECRET is not configured")
        return jsonify({}), 400

    try:
        event = stripe.Webhook.construct_event(
            payload, signature, config.STRIPE_WEBHOOK_SECRET
        )
    except Exception as exc:
        # Signature failures are routine (probes, retries after a key rotation).
        # Log the exception class, never the payload.
        log.warning("stripe webhook rejected: %s", type(exc).__name__)
        return jsonify({}), 400

    if event.get("type") != "checkout.session.completed":
        return jsonify({"status": "ignored"}), 200

    session = (event.get("data") or {}).get("object") or {}
    metadata = session.get("metadata") or {}

    slug = metadata.get("funnel")
    session_id = metadata.get("session_id")
    result_style = metadata.get("result_style")

    if not config.funnel_exists(slug) or not (
        isinstance(session_id, str) and UUID_RE.match(session_id)
    ):
        # Sessions created outside this funnel (or by an older build) are not
        # ours to record. Acknowledge so Stripe stops retrying.
        log.warning("webhook %s has unusable metadata — skipped", event.get("id"))
        return jsonify({"status": "skipped"}), 200

    amount_cents = session.get("amount_total")
    if not isinstance(amount_cents, int):
        log.warning("webhook %s has no amount_total — skipped", event.get("id"))
        return jsonify({"status": "skipped"}), 200

    currency = (session.get("currency") or "usd")[:3]
    details = session.get("customer_details") or {}
    address = details.get("address") or {}

    payment_intent = session.get("payment_intent")
    if not isinstance(payment_intent, str):
        payment_intent = None

    try:
        purchase_id = database.execute(
            INSERT_PURCHASE_SQL,
            (
                slug,
                session_id,
                event.get("id"),
                payment_intent,
                session.get("id"),
                amount_cents,
                currency,
                details.get("email"),
                (address.get("country") or None),
                result_style,
                "paid",
            ),
        )
    except pymysql.err.IntegrityError:
        # Replay, or the same payment arriving via a second event. Both unique
        # keys are doing their job; there is nothing left to do.
        log.info("webhook %s already recorded", event.get("id"))
        return jsonify({"status": "duplicate"}), 200
    except Exception:
        log.exception("purchase insert failed for webhook %s", event.get("id"))
        return jsonify({}), 500

    log.info("purchase %s recorded for funnel %s", purchase_id, slug)
    _record_side_effects(purchase_id, slug, session_id, result_style)
    return jsonify({"status": "ok"}), 200


# --- GET /api/report -------------------------------------------------------


@bp.get("/api/report")
def report():
    cs = request.args.get("cs", "")
    if not CHECKOUT_SESSION_RE.match(cs):
        return jsonify({}), 400

    purchase = database.query_one(SELECT_PURCHASE_SQL, (cs,))
    if not purchase:
        # Webhook has not landed yet — the client keeps polling.
        return jsonify({"status": "pending"}), 202

    row = database.query_one(SELECT_REPORT_SQL, (purchase["id"],))
    if not row:
        return jsonify({"status": "pending"}), 202

    content = row["content"]
    if isinstance(content, (str, bytes)):
        content = json.loads(content)

    return jsonify({"status": "ready", "report": content}), 200
