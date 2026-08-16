"""Stripe checkout, webhook and report delivery.

The webhook is the only writer of `purchases`. Nothing the client says about
a payment is trusted, and the client never supplies an amount — prices are
read server-side from the funnel config.

Amounts are integer cents everywhere in this module, which is what Stripe
sends and what MySQL stores. No float ever touches a money value; a Decimal
is used wherever a fractional amount is actually computed.

No email address, address or raw request body is ever written to a log line.
"""

import decimal
import hashlib
import json
import logging
import re
import time

import pymysql.err
import stripe
from flask import Blueprint, jsonify, request

import config
import database
import reports

log = logging.getLogger(__name__)

bp = Blueprint("payments", __name__)

# The default for anything that does not name a key. Every call below names
# one: `stripe.api_key` is module state, and mutating it per request would race
# across the threads Flask serves concurrent requests on — two funnels in two
# modes would take each other's key. The SDK pulls `api_key` out of the call's
# kwargs as a request option, so passing it is both explicit and thread-safe.
stripe.api_key = config.STRIPE_SECRET_KEY

# Which key set a funnel transacts on. `live` is the default and the only mode
# a funnel gets by saying nothing, so an older config — or one cached a version
# back in the CDN — is a live funnel, which is what it has always been.
LIVE, TEST = "live", "test"


def _stripe_mode(cfg):
    return TEST if (cfg or {}).get("stripe_mode") == TEST else LIVE


def _stripe_secret(mode):
    """The secret key for a mode, or "" when that mode is not configured."""
    return (config.STRIPE_TEST_SECRET_KEY if mode == TEST
            else config.STRIPE_SECRET_KEY)


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
    "SELECT id, funnel, session_id, result_style, status, email FROM purchases "
    "WHERE checkout_session = %s LIMIT 1"
)

SELECT_REPORT_SQL = (
    "SELECT content FROM reports WHERE purchase_id = %s ORDER BY id DESC LIMIT 1"
)


def _style_ids(cfg):
    return {s.get("id") for s in cfg.get("styles", [])}


def _step_images(cfg):
    """Every image any step can show, across all of its pairs.

    A step owns several pairs from 3d on, and the reader is given exactly one
    of them — but which one is decided in the browser, so every variant is a
    legitimate answer and all of them have to validate. A step still carrying a
    bare `images` list is read as its own single pair, so a funnel that has not
    been converted keeps working rather than silently rejecting every payload
    it is sent.
    """
    for step in ((cfg.get("swipe") or {}).get("steps") or []):
        if not isinstance(step, dict):
            continue
        pairs = step.get("pairs")
        if not (isinstance(pairs, list) and pairs):
            pairs = [{"images": step.get("images") or []}]
        for pair in pairs:
            if not isinstance(pair, dict):
                continue
            for item in (pair.get("images") or []):
                if isinstance(item, dict):
                    yield item


def _gallery_tags(cfg):
    """Every tag the quiz can actually award. The client cannot invent one.

    The steps are the whole source: a tag the reader had no way to tap is not a
    tag they scored. `gallery` is the pre-3a shape and is still read, so a
    funnel that has not been converted keeps validating instead of silently
    rejecting every score it is sent.
    """
    swipe = cfg.get("swipe") or {}
    tags = set()
    for item in _step_images(cfg):
        tags.update(item.get("tags") or [])
    for item in (swipe.get("gallery") or []):
        tags.update(item.get("tags") or [])
    return tags


# Stripe metadata values are strings capped at 500 characters.
METADATA_VALUE_MAX = 500
TAG_SCORE_MAX = 30
# One tap per step, with headroom for a funnel that grows a few. This is a
# ceiling on absurdity, not a step count: the real per-funnel limit is the
# step list itself, checked above it. It was 12 while the quiz was 12 steps,
# which meant the thirteenth step would have failed every list at exactly the
# length the quiz now produces — and the failure is silent, so the reports
# would simply have stopped being personalised. Held at the same 20 the
# tracking step ceiling uses; twenty ids and their separators are around a
# hundred characters, well inside the metadata value limit.
CHOICES_MAX = 20


def _clean_tag_scores(cfg, raw):
    """The client's tag scores, or None if they are not usable.

    Scores only steer report copy, so a bad shape is dropped rather than
    failing the checkout — an older client that sends nothing at all is the
    same case as one that sends nonsense.
    """
    if not isinstance(raw, dict) or not raw:
        return None

    known = _gallery_tags(cfg)
    clean = {}
    for tag, score in raw.items():
        if tag not in known:
            return None
        # bool is an int subclass; it is not a score.
        if isinstance(score, bool) or not isinstance(score, (int, float)):
            return None
        # Halves and negatives, since 4B: an inverse step scores a rejection
        # at -0.5, so a tag nobody chose and somebody rejected finishes below
        # zero. Requiring a non-negative int here would have rejected every
        # payload the moment that step shipped, and rejection is silent — the
        # report would simply have stopped being personalised.
        if score != score or score in (float("inf"), float("-inf")):
            return None
        if not -TAG_SCORE_MAX <= score <= TAG_SCORE_MAX:
            return None
        clean[tag] = score
    return clean or None


def _tag_scores_metadata(scores):
    """Compact JSON for Stripe metadata, or None if it will not fit."""
    if not scores:
        return None
    packed = json.dumps(scores, separators=(",", ":"), sort_keys=True)
    if len(packed) > METADATA_VALUE_MAX:
        log.warning("tag_scores too large for metadata (%d chars) — dropped",
                    len(packed))
        return None
    return packed


def _step_image_ids(cfg):
    """Every image id the quiz can hand back, across every pair of every step."""
    return [item["id"] for item in _step_images(cfg)
            if isinstance(item.get("id"), str)]


def _clean_choices(cfg, raw):
    """The tapped image ids, or None if the list is not usable.

    Same posture as the tag scores: this only steers report copy, so anything
    the client sends that does not describe a real run through this funnel is
    dropped rather than failing the checkout. A client that sends nothing is
    the same case as one that sends nonsense.
    """
    if not isinstance(raw, list) or not raw:
        return None
    steps = (cfg.get("swipe") or {}).get("steps") or []
    limit = max(len(steps), int((cfg.get("swipe") or {}).get("pairs_count") or 0))
    if limit and len(raw) > limit:
        return None
    if len(raw) > CHOICES_MAX:
        return None

    known = set(_step_image_ids(cfg))
    for image_id in raw:
        if not isinstance(image_id, str) or image_id not in known:
            return None
    # One tap per step: a repeated id is a replayed or hand-made list.
    if len(set(raw)) != len(raw):
        return None
    return list(raw)


def _choices_metadata(choices):
    """The sequence as one short string, or None if it will not fit.

    Comma-joined rather than JSON: the ids are the funnel's own and carry no
    punctuation, so this is half the characters of a JSON array and leaves
    room under Stripe's 500-character value limit.
    """
    if not choices:
        return None
    packed = ",".join(choices)
    if len(packed) > METADATA_VALUE_MAX:
        log.warning("choices too large for metadata (%d chars) — dropped",
                    len(packed))
        return None
    return packed


def _read_choices(cfg, packed):
    """The sequence back out of Stripe metadata, re-validated.

    Metadata round-trips through Stripe, so this is still client-originated
    data by the time it comes back and is checked again from scratch.
    """
    if not isinstance(packed, str) or not packed:
        return None
    return _clean_choices(cfg, packed.split(","))


# --- Meta click identifiers ------------------------------------------------

# Meta's own formats: `fb.1.<ms>.<random>` for the browser cookie and the
# click id, and an fbclid is a URL parameter somebody else generated. None of
# them are ours to interpret — they are opaque strings we carry from the tap
# to the Purchase event so the two can be joined. The caps are Stripe's
# metadata limit and a sanity bound; anything longer is not a click id.
META_ID_MAX = 255
META_ID_RE = re.compile(r"^[A-Za-z0-9._-]{1,%d}$" % META_ID_MAX)
META_ID_KEYS = ("fbp", "fbc", "fbclid")


def _clean_meta_ids(raw):
    """The click identifiers worth forwarding, or {}.

    Same posture as the tag scores: these only improve ad attribution, so a
    bad one is dropped and the purchase carries on. A missing identifier costs
    a slightly worse match rate; a failed checkout costs the sale.
    """
    if not isinstance(raw, dict):
        return {}
    out = {}
    for key in META_ID_KEYS:
        value = raw.get(key)
        if isinstance(value, str) and META_ID_RE.match(value):
            out[key] = value
    return out


def _metadata(slug, session_id, result_style, tag_scores, choices=None,
              meta_ids=None):
    """Checkout session metadata. Absent keys are absent, never empty strings."""
    data = {
        "funnel": slug,
        "session_id": session_id,
        "result_style": result_style,
    }
    if tag_scores:
        data["tag_scores"] = tag_scores
    if choices:
        data["choices"] = choices
    for key, value in (meta_ids or {}).items():
        data[key] = value
    return data


# --- Meta Conversions API --------------------------------------------------

# The browser never fires Purchase. An ad blocker, a closed tab or a back
# button all lose it, and a browser that does fire it plus a server that also
# does produces two. One sender, server-side, after the row exists.


def _sha256(value):
    """Meta's normalisation for an email: trimmed, lower-cased, then hashed."""
    return hashlib.sha256(value.strip().lower().encode("utf-8")).hexdigest()


def _capi_url():
    return "https://graph.facebook.com/%s/%s/events" % (
        config.META_API_VERSION, config.META_PIXEL_ID)


def send_purchase_event(purchase_id, slug, amount_cents, currency,
                        email=None, payment_intent=None, meta_ids=None,
                        event_time=None):
    """Tell Meta a purchase happened. Returns True if it was accepted.

    Best effort by construction: every failure path returns False and the
    webhook still answers 200. Stripe retries a non-200, and a retry would
    replay a purchase we have already recorded — an advertising event is not
    worth that.

    `event_id` is the payment intent, which is what makes this safe to send
    more than once: Meta deduplicates on it, so a replayed webhook or a future
    browser-side Purchase collapses into one conversion rather than inflating
    the number the ad spend is judged against.
    """
    if not (config.META_PIXEL_ID and config.META_CAPI_TOKEN):
        return False

    try:
        import requests
    except ImportError:
        log.error("requests not installed — Meta purchase events are skipped")
        return False

    ids = meta_ids or {}
    user_data = {}
    if email:
        # The only personal datum that leaves here, and it leaves hashed.
        user_data["em"] = [_sha256(email)]
    if ids.get("fbp"):
        user_data["fbp"] = ids["fbp"]
    # fbc is the joinable click id. Meta will take a raw fbclid wrapped in its
    # own format, so a visitor who arrived with one but has no cookie yet is
    # still attributable.
    if ids.get("fbc"):
        user_data["fbc"] = ids["fbc"]
    elif ids.get("fbclid") and event_time:
        user_data["fbc"] = "fb.1.%d.%s" % (event_time * 1000, ids["fbclid"])

    if not user_data:
        # Nothing to match on. Meta rejects the event anyway, so do not spend
        # a request finding that out.
        log.info("purchase %s has no Meta identifiers — event not sent",
                 purchase_id)
        return False

    payload = {
        "data": [{
            "event_name": "Purchase",
            "event_time": event_time or int(time.time()),
            "event_id": payment_intent or ("purchase-%s" % purchase_id),
            "action_source": "website",
            "event_source_url": "%s/%s" % (config.BASE_URL, slug),
            "user_data": user_data,
            "custom_data": {
                # Cents to units, through Decimal — this is a money value and
                # the rule here is that money never touches a float.
                "value": float(decimal.Decimal(amount_cents)
                               / decimal.Decimal(100)),
                "currency": (currency or "usd").lower(),
            },
        }],
    }
    if config.META_TEST_EVENT_CODE:
        payload["test_event_code"] = config.META_TEST_EVENT_CODE

    try:
        response = requests.post(
            _capi_url(),
            json=payload,
            params={"access_token": config.META_CAPI_TOKEN},
            timeout=config.META_TIMEOUT_S,
        )
    except Exception as exc:
        # Class only. The payload holds a hashed email and click ids, and none
        # of it belongs in a log line.
        log.warning("Meta purchase event failed for purchase %s: %s",
                    purchase_id, type(exc).__name__)
        return False

    if response.status_code >= 300:
        log.warning("Meta purchase event rejected for purchase %s: HTTP %s",
                    purchase_id, response.status_code)
        return False

    log.info("Meta purchase event sent for purchase %s", purchase_id)
    return True


# --- GET /api/pixel-config -------------------------------------------------


@bp.get("/api/pixel-config")
def pixel_config():
    """The pixel id, or null. One field, no secrets.

    The id lives here rather than in the HTML because static/ is served by the
    CDN and shared by every funnel and every brand that will ever run on this
    shell. A pixel compiled into those files would follow the next one onto
    its own domain.

    The token is never exposed: it is a server credential and the browser has
    no use for it.
    """
    response = jsonify({"pixel_id": config.META_PIXEL_ID or None})
    response.headers["Cache-Control"] = (
        "public, max-age=%d" % config.PIXEL_CONFIG_MAX_AGE)
    return response


# --- POST /api/checkout ----------------------------------------------------

# Stripe caps the product name it will render; past this it truncates, and a
# name that ends mid-word on the payment page looks like a broken store.
PRODUCT_NAME_MAX = 250


def _text(value, limit=PRODUCT_NAME_MAX):
    """A usable one-line string from config, or None."""
    if not isinstance(value, str):
        return None
    value = value.strip()
    return value[:limit] or None


def _product_images(checkout_cfg):
    """The single product image, absolute, or an empty list.

    Stripe fetches this itself from the public internet, so a relative path is
    useless to it — the config stores the path and this joins it to BASE_URL,
    which is where the success and cancel URLs already come from. Doing it that
    way rather than writing the domain in here means a staging deploy shows its
    own image instead of production's, and there is one place the hostname is
    configured rather than two.

    Anything that is not a path or an http(s) URL is dropped: Stripe rejects
    the whole session over a bad image, and losing a picture is better than
    losing the sale.
    """
    raw = _text(checkout_cfg.get("product_image"), limit=500)
    if not raw:
        return []
    if raw.startswith("http://") or raw.startswith("https://"):
        return [raw]
    if not raw.startswith("/"):
        return []
    base = (config.BASE_URL or "").rstrip("/")
    if not (base.startswith("http://") or base.startswith("https://")):
        return []
    return [base + raw]


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

    # Steer the report copy only — never the price, never whether we fulfil.
    tag_scores = _tag_scores_metadata(_clean_tag_scores(cfg, body.get("tag_scores")))
    choices = _choices_metadata(_clean_choices(cfg, body.get("choices")))
    # Carried through Stripe so the server-side Purchase can be joined to the
    # click that produced it. Never used to decide anything on this path.
    meta_ids = _clean_meta_ids(body)

    # What Stripe shows on its own payment page and on the receipt. It is the
    # last piece of copy somebody reads before paying and the only one we do
    # not draw ourselves, so it comes out of the funnel config with the rest of
    # the funnel's words. The old derived name stays as the fallback: a funnel
    # without the key, or an older config still in the CDN, gets exactly what
    # it got before.
    checkout_cfg = cfg.get("checkout") or {}
    title = (cfg.get("meta") or {}).get("title") or slug
    product_name = (_text(checkout_cfg.get("product_name"))
                    or "%s — Full Style Report" % title)
    product_data = {"name": product_name}
    images = _product_images(checkout_cfg)
    if images:
        product_data["images"] = images

    # Which key set this funnel transacts on, and a refusal rather than a
    # fallback when it asks for one that is not configured. Quietly billing a
    # test funnel against the live key would be the single worst outcome here,
    # so the missing-key branch stops instead of guessing.
    mode = _stripe_mode(cfg)
    secret = _stripe_secret(mode)
    if not secret:
        log.error(
            "funnel %s wants stripe_mode=%s but %s is not configured — "
            "refusing checkout", slug, mode,
            "STRIPE_TEST_SECRET_KEY" if mode == TEST else "STRIPE_SECRET_KEY")
        return jsonify({}), 502

    try:
        session = stripe.checkout.Session.create(
            # Extracted by the SDK as a request option, never sent as a form
            # field. Passed rather than assigned so two funnels in two modes
            # cannot take each other's key off the module.
            api_key=secret,
            mode="payment",
            line_items=[
                {
                    "quantity": 1,
                    "price_data": {
                        "currency": currency,
                        "unit_amount": amount_cents,
                        "product_data": product_data,
                    },
                }
            ],
            # Managed Payments is on by default for the account but wants a
            # product tax code we do not have — the tax model is a Phase 2
            # decision — so it is switched off per session. No
            # payment_method_types either: Stripe still picks the methods, and
            # wallets surface on their own when the device supports them.
            managed_payments={"enabled": False},
            success_url="%s/%s?cs={CHECKOUT_SESSION_ID}" % (config.BASE_URL, slug),
            cancel_url="%s/%s?canceled=1" % (config.BASE_URL, slug),
            metadata=_metadata(slug, session_id, result_style, tag_scores,
                               choices, meta_ids),
            customer_creation="if_required",
        )
    except Exception:
        # Stripe's message can echo request contents — log the type only.
        log.exception("stripe checkout session create failed for funnel %s", slug)
        return jsonify({}), 502

    return jsonify({"url": session.url})


# --- POST /api/stripe/webhook ----------------------------------------------


def _read_tag_scores(cfg, packed):
    """Tag scores back out of Stripe metadata. Anything odd becomes None.

    Metadata is round-tripped through Stripe, so it is re-validated here rather
    than trusted: this is still client-originated data, and a webhook is not a
    place to discover that.
    """
    if not isinstance(packed, str) or not packed:
        return None
    try:
        raw = json.loads(packed)
    except ValueError:
        return None
    return _clean_tag_scores(cfg, raw)


def _claim_visualizer_photo(purchase_id, slug, session_id):
    """Hand this purchase the photo its session uploaded before paying.

    On a funnel that takes the photograph before the money, the file is
    already on disk under the quiz session by the time this runs. Moving it
    here is what makes the paid page open on a picture the reader has already
    chosen rather than on a picker asking them to choose it again.

    Imported inside the function rather than at module scope: visualizer.py
    imports this module for the checkout-session pattern, so a top-level
    import in the other direction would be a cycle.

    Never raises. A photo that does not move leaves the purchase exactly where
    it would have been without this — the paid page's own upload still works,
    which is the flow that shipped before any of this.
    """
    try:
        import visualizer
        cfg = config.load_funnel(slug)
        visualizer.claim_pending(purchase_id, session_id, cfg)
    except Exception:
        log.exception("visualizer photo claim failed for purchase %s",
                      purchase_id)


def _record_side_effects(purchase_id, slug, session_id, result_style, tag_scores,
                         email=None, checkout_session=None, choices=None):
    """Report + emailed PDF + server-side purchase event.

    `start_report` persists an empty report row and returns; every model call
    happens on a background thread that fills the row in as sections land. So
    this webhook's response time no longer depends on generation at all — the
    only thing between the purchase landing and the 200 is two inserts.

    The email hangs off the report's `on_final` hook rather than anything here,
    because that fires once at completion, after any late call has had its
    chance to upgrade the row. The PDF therefore carries the finished report.
    """

    def deliver(content):
        reports.send_report_email(purchase_id, email, content, checkout_session)

    # Before the report, because it is a file rename and a single INSERT while
    # the report is a background thread and a fleet of model calls. The paid
    # page polls both; this one should already be true when the first poll
    # lands.
    _claim_visualizer_photo(purchase_id, slug, session_id)

    try:
        reports.start_report(
            purchase_id, slug, result_style, tag_scores,
            on_final=deliver if email else None, choices=choices,
        )
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

    # One endpoint, two Stripe accounts' worth of signatures: the live one and,
    # where it is configured, the test one a `stripe_mode: test` funnel
    # transacts on. Live is tried first because it is the one that carries
    # money and the one almost every event comes from; a test secret that is
    # not set simply is not tried.
    secrets = [(LIVE, config.STRIPE_WEBHOOK_SECRET),
               (TEST, config.STRIPE_TEST_WEBHOOK_SECRET)]
    secrets = [(mode, key) for mode, key in secrets if key]
    if not secrets:
        log.error("STRIPE_WEBHOOK_SECRET is not configured")
        return jsonify({}), 400

    # Verify the signature with the SDK, then parse the payload ourselves.
    # stripe.Webhook.construct_event returns an Event object whose shape has
    # changed across SDK majors — it stopped being a dict in 15.x, so `.get()`
    # on it raises. A plain dict keeps this handler independent of that.
    #
    # verify_header interpolates the payload into the signed string with %s, so
    # bytes would hash as their repr. Decode first, exactly as construct_event
    # does internally.
    raw = payload.decode("utf-8") if isinstance(payload, bytes) else payload
    signed = None
    last = None
    for mode, secret in secrets:
        try:
            stripe.WebhookSignature.verify_header(
                raw, signature, secret, stripe.Webhook.DEFAULT_TOLERANCE)
            signed = mode
            break
        except Exception as exc:
            last = exc
    if signed is None:
        # Signature failures are routine (probes, retries after a key rotation).
        # Log the exception class, never the payload.
        log.warning("stripe webhook rejected: %s", type(last).__name__)
        return jsonify({}), 400

    try:
        event = json.loads(raw)
        if not isinstance(event, dict):
            raise ValueError("event is not an object")
    except Exception as exc:
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

    # After the row, never before, and never in a way that can change the
    # answer. A conversion Meta missed is a reporting gap; a webhook that
    # returns non-200 is a retry against a purchase already written.
    #
    # Nothing from a test payment reaches Meta. A 4242 card walking the funnel
    # is not a conversion, and one in the pixel would be optimised against and
    # counted in the number the ad spend is judged on. Two independent markers
    # have to agree it is real: Stripe's own `livemode`, and the session id,
    # which carries cs_test_ on a test session. Absence is not evidence — an
    # event with no `livemode` at all behaves exactly as it did before this,
    # so a live purchase can never be dropped by a missing field.
    live_purchase = (event.get("livemode") is not False
                     and not str(session.get("id") or "").startswith("cs_test_"))
    if not live_purchase:
        # Names the payment, not the signature: an event can be signed with the
        # live secret and still be a test payment, and a line claiming
        # otherwise is the one you would read while wondering where a
        # conversion went.
        log.info("purchase %s is not a live payment (signature: %s) — Meta "
                 "purchase event skipped", purchase_id, signed)
    else:
        try:
            send_purchase_event(
                purchase_id, slug, amount_cents, currency,
                email=details.get("email"), payment_intent=payment_intent,
                meta_ids=_clean_meta_ids(metadata),
                event_time=int(event.get("created") or time.time()),
            )
        except Exception as exc:
            log.warning("Meta purchase event raised for purchase %s: %s",
                        purchase_id, type(exc).__name__)

    cfg = config.load_funnel(slug)
    tag_scores = _read_tag_scores(cfg, metadata.get("tag_scores"))
    choices = _read_choices(cfg, metadata.get("choices"))
    _record_side_effects(
        purchase_id, slug, session_id, result_style, tag_scores,
        email=details.get("email"), checkout_session=session.get("id"),
        choices=choices,
    )
    return jsonify({"status": "ok"}), 200


# --- GET /api/report -------------------------------------------------------


def _mask_email(address):
    """`j***@gmail.com`, or None when there is nothing safe to show.

    Enough for someone to recognise which inbox to check and not enough to be
    worth harvesting. The full address never leaves the database.
    """
    if not isinstance(address, str) or address.count("@") != 1:
        return None
    local, _, domain = address.partition("@")
    if not local or not domain:
        return None
    return "%s***@%s" % (local[0], domain)


@bp.get("/api/report")
def report():
    cs = request.args.get("cs", "")
    if not CHECKOUT_SESSION_RE.match(cs):
        return jsonify({}), 400

    purchase = database.query_one(SELECT_PURCHASE_SQL, (cs,))
    if not purchase:
        # Webhook has not landed yet — the client keeps polling.
        return jsonify({"status": "pending"}), 202

    body = {"status": "pending"}
    masked = _mask_email(purchase.get("email"))
    if masked:
        body["email_masked"] = masked

    row = database.query_one(SELECT_REPORT_SQL, (purchase["id"],))
    if not row:
        # The webhook has not written the row yet. Everything after this point
        # is a 200 with however much of the report exists.
        return jsonify(body), 202

    content = row["content"]
    if isinstance(content, (str, bytes)):
        content = json.loads(content)

    body["status"] = "ready"
    body["complete"] = not str((content or {}).get("version") or "").endswith(
        reports.PARTIAL_SUFFIX)
    body["report"] = content
    return jsonify(body), 200
