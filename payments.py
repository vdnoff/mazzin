"""Stripe checkout, webhook and report delivery.

The webhook is the only writer of `purchases`. Nothing the client says about
a payment is trusted, and the client never supplies an amount — prices are
read server-side from the funnel config.

Two routes start a payment and neither one completes it. `/api/checkout`
creates a hosted Checkout Session and redirects; `/api/payment-intent` creates
a PaymentIntent for a payment confirmed in the page. They validate through the
same function and price from the same config, so there is one answer to what
something costs rather than two that agree today. The redirect is the default
and the one carrying money; the intent path has no caller yet.

Both arrive back here as a webhook, as `checkout.session.completed` or
`payment_intent.succeeded`, and are read into one shape before anything is
written — so there is one INSERT, one set of side effects, and one place where
a purchase becomes real. `uq_payment_intent` is what makes a payment that
somehow produced both events yield one row and not two.

Amounts are integer cents everywhere in this module, which is what Stripe
sends and what MySQL stores. No float ever touches a money value; a Decimal
is used wherever a fractional amount is actually computed.

No email address, address or raw request body is ever written to a log line.
"""

import decimal
import hashlib
import ipaddress
import json
import logging
import re
import time
import urllib.parse

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


def _stripe_publishable(mode):
    """The publishable key for a mode, or "" when that mode is not configured.

    The only key that is ever allowed out of this process. It goes to the
    browser so Stripe.js can confirm a PaymentIntent there, which is the whole
    reason it exists — it identifies the account and authorises nothing.
    """
    return (config.STRIPE_TEST_PUBLISHABLE_KEY if mode == TEST
            else config.STRIPE_PUBLISHABLE_KEY)


UUID_RE = re.compile(
    r"^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$",
    re.IGNORECASE,
)

# Stripe checkout session ids: cs_test_... / cs_live_...
CHECKOUT_SESSION_RE = re.compile(r"^cs_[A-Za-z0-9_]{1,250}$")

# What a reader's result link can carry. `cs_` is what every link in the wild
# already holds and is unchanged; `pi_` is what a purchase confirmed in the
# page has instead, because it never had a checkout session at all.
#
# Both are Stripe-generated identifiers of the same shape and the same
# unguessability, and both are already known to the browser that made the
# payment — the redirect puts the `cs_` in the URL bar, and the client secret
# contains the `pi_`. So this widens what the token may look like without
# widening what a stranger can reach.
RESULT_TOKEN_RE = re.compile(r"^(?:cs|pi)_[A-Za-z0-9_]{1,250}$")

INSERT_PURCHASE_SQL = (
    "INSERT INTO purchases "
    "(funnel, session_id, stripe_event_id, payment_intent, checkout_session, "
    " amount_cents, currency, email, country, result_style, status) "
    "VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)"
)

INSERT_PURCHASE_EVENT_SQL = (
    "INSERT INTO events (funnel, session_id, event) VALUES (%s, %s, 'purchase')"
)

# One purchase, found by whichever identifier its payment produced. A hosted
# checkout has a `cs_` and no `pi_` in the link; an in-page confirmation has a
# `pi_` and no checkout session at all. The token is matched against both
# columns rather than parsed and routed, because a prefix is a weaker thing to
# depend on than an index — and both columns are indexed, so this is two key
# lookups either way.
#
# Passing the same value twice is deliberate and safe: a `cs_` can never equal
# a payment intent id and a `pi_` can never equal a checkout session id, so
# exactly one side can match.
SELECT_PURCHASE_SQL = (
    "SELECT id, funnel, session_id, result_style, status, email FROM purchases "
    "WHERE checkout_session = %s OR payment_intent = %s LIMIT 1"
)

SELECT_REPORT_SQL = (
    "SELECT content FROM reports WHERE purchase_id = %s ORDER BY id DESC LIMIT 1"
)


def find_purchase(token):
    """The purchase a result token names, or None. Raises on a database error.

    The one place a browser-supplied token becomes a purchase. It was two
    identical SELECTs in two modules, which is exactly the arrangement that
    would have left the visualizer unable to find an in-page purchase while
    the report could — so it is one function now and both callers import it.

    Validating the token is the caller's job, because what they do about a
    malformed one differs: the report answers 400 and the visualizer answers
    the same refusal it gives an unknown session.
    """
    return database.query_one(SELECT_PURCHASE_SQL, (token, token))


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
    """Metadata for whichever object starts the payment. Absent keys are
    absent, never empty strings.

    One builder for the Checkout Session and the PaymentIntent alike, because
    the webhook reads them back through one code path and a difference here
    would surface there as a purchase that could not be recorded."""
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


# --- what the browser knew, held until the webhook -------------------------
#
# The server-side Purchase fires from Stripe's request rather than the
# buyer's, so by then the buyer's IP and User-Agent are gone — and those are
# two of the identifiers Meta matches a conversion on. They are captured when
# the browser asks for a checkout session, held in `checkout_context`, and
# read once when the webhook lands.
#
# Not in Stripe metadata, where the click ids ride: Stripe documents metadata
# as the wrong place for personal data, an IP address is personal data, and
# metadata is permanent and dashboard-visible where this row has a retention
# window and a sweeper. Not in `events` either — tracking.py keeps two enum
# words about the device and says the raw User-Agent and the IP are stored
# nowhere, and that rule is about a history kept forever and read by people.
# This row lives for minutes, is read once by a machine, and is deleted.
#
# Everything in here is best effort. A failed capture costs a slightly worse
# match rate on one conversion; a failed checkout costs the sale.

CONTEXT_UPSERT_SQL = (
    "INSERT INTO checkout_context (session_id, client_ip, client_ua) "
    "VALUES (%s, %s, %s) "
    "ON DUPLICATE KEY UPDATE client_ip = VALUES(client_ip), "
    "client_ua = VALUES(client_ua), created_at = CURRENT_TIMESTAMP"
)

CONTEXT_SELECT_SQL = (
    "SELECT client_ip, client_ua FROM checkout_context "
    "WHERE session_id = %s LIMIT 1"
)

# A User-Agent is conventionally under 256 characters. The column is 400 and
# this is the same number, so a header arriving with sixteen kilobytes of it
# is truncated here rather than by MySQL.
UA_MAX = 400


def _client_ua():
    """The buyer's User-Agent header, trimmed to what the column holds."""
    value = request.headers.get("User-Agent") or ""
    value = value.strip()[:UA_MAX]
    return value or None


def _client_ip():
    """The buyer's address, or None.

    Cloudflare sits in front of this app, so `remote_addr` is Cloudflare. The
    header it sets is read first, then the left-most hop of X-Forwarded-For,
    then the socket as the last resort. Every candidate is parsed as an
    address before it is believed: these are client-settable headers, and an
    unparsed one would be a string of somebody else's choosing on its way to
    a third party.
    """
    candidates = [request.headers.get("CF-Connecting-IP")]
    forwarded = request.headers.get("X-Forwarded-For") or ""
    if forwarded:
        candidates.append(forwarded.split(",")[0])
    candidates.append(request.remote_addr)
    for value in candidates:
        if not value:
            continue
        try:
            return str(ipaddress.ip_address(value.strip()))
        except ValueError:
            continue
    return None


def _merged_meta_ids(from_page, from_request):
    """The click ids to carry, the page's first, and an fbc if we can build one.

    `fbc` is what Meta actually joins a conversion to a click on, so a visitor
    who arrived with an `fbclid` and no cookie yet is given one in Meta's own
    format rather than left unattributable. `fbclid` travels too: the send
    side still knows how to wrap one, and an older row that never got here
    should keep working.
    """
    out = dict(from_request or {})
    out.update(from_page or {})
    if not out.get("fbc"):
        built = _fbc_from_click(out.get("fbclid"))
        if built:
            out["fbc"] = built
    return out


def _cookie_meta_ids():
    """The click identifiers the request itself carries.

    fbevents.js writes `_fbp` and `_fbc` as first-party cookies, so they
    arrive on this request whether or not the page managed to read them — an
    extension that blocks `document.cookie` reads, or an engine.js cached from
    before that code shipped, both still send them here.
    """
    out = {}
    for key, name in (("fbp", "_fbp"), ("fbc", "_fbc")):
        value = request.cookies.get(name)
        if isinstance(value, str) and META_ID_RE.match(value):
            out[key] = value
    # And the click id off the landing URL, where the browser came straight
    # from an ad and the cookie has not been written yet.
    referrer = request.referrer or ""
    if "fbclid=" in referrer:
        try:
            hit = urllib.parse.parse_qs(
                urllib.parse.urlparse(referrer).query).get("fbclid")
        except ValueError:
            hit = None
        if hit and META_ID_RE.match(hit[0]):
            out["fbclid"] = hit[0]
    return out


def _fbc_from_click(fbclid, now=None):
    """Meta's own format for a click id that has no cookie behind it yet.

    `fb.1.<milliseconds>.<fbclid>`: the subdomain index Meta uses for a
    first-party cookie, then when the click was seen, then the id itself.
    Built here rather than at send time because "when it was seen" is now —
    the webhook fires minutes later and would stamp the payment's time onto a
    click that happened before the funnel was walked.
    """
    if not fbclid:
        return None
    return "fb.1.%d.%s" % (int((now or time.time()) * 1000), fbclid)


def _save_context(session_id, client_ip, client_ua):
    """Hold the buyer's IP and User-Agent for the webhook. Never raises."""
    if not session_id or not (client_ip or client_ua):
        return False
    try:
        database.execute(CONTEXT_UPSERT_SQL,
                         (session_id, client_ip, client_ua))
        return True
    except Exception as exc:
        # Class only, and never the values: this is the one place in the app
        # that holds an address and a full User-Agent, and a log line is
        # exactly the durable, human-read place they must not reach.
        log.warning("checkout context not saved for session: %s",
                    type(exc).__name__)
        return False


def _read_context(session_id):
    """(ip, user agent) for a session, or (None, None). Never raises."""
    if not session_id:
        return None, None
    try:
        row = database.query_one(CONTEXT_SELECT_SQL, (session_id,))
    except Exception as exc:
        log.warning("checkout context not read: %s", type(exc).__name__)
        return None, None
    if not row:
        return None, None
    return (row.get("client_ip") or None), (row.get("client_ua") or None)


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
                        event_time=None, session_id=None,
                        client_ip=None, client_ua=None):
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
        # Hashed, always. Meta never sees an address in the clear.
        user_data["em"] = [_sha256(email)]
    # The identifier that does not depend on the buyer's inbox. An iCloud
    # relay address, a wallet's own address, a typo — every one of them is an
    # email Meta cannot join to a person, and each of those purchases was
    # matching on nothing else. This is the session id the funnel has used
    # since the first tap: the browser declares it to the pixel at init, so
    # the Lead and InitiateCheckout it fires carry the same value, and the
    # Purchase joins to them on it.
    #
    # Hashed with the same normalisation as the email, which is not a
    # preference — fbevents.js normalises and SHA-256s advanced-matching
    # values in the browser, so anything else here would hash to a different
    # string and match nothing.
    if session_id:
        user_data["external_id"] = _sha256(session_id)
    # Where the buyer actually was, captured when they asked for a checkout
    # session because this code runs on Stripe's request and not theirs.
    # Neither is hashed: Meta's spec takes both in the clear and hashing
    # either one makes it unusable.
    if client_ip:
        user_data["client_ip_address"] = client_ip
    if client_ua:
        user_data["client_user_agent"] = client_ua
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
        # a request finding that out. In practice unreachable now that the
        # session id is always there, and kept because "always" is a claim
        # about a caller rather than about this function.
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


class OrderError(Exception):
    """A request that will not become a payment, with the status to answer."""

    def __init__(self, status):
        Exception.__init__(self, status)
        self.status = status


def _validated_order(body):
    """Everything a payment needs, taken from a request and re-derived here.

    Two routes now start a payment — the hosted Checkout redirect and the
    PaymentIntent the Express Checkout Element confirms — and they have to
    agree on every one of these answers. Not "should agree": a second copy of
    this that drifted would be a second opinion about what something costs.

    The one rule that matters is unchanged and is the reason this reads the
    config rather than the body: **the price comes from the funnel, never from
    the client.** The body supplies which funnel, which session and which
    style; the amount is looked up. Everything else it sends steers report
    copy or ad attribution and can be dropped without affecting the sale.

    Raises OrderError with the status to answer. A 400 is the caller's fault
    and says nothing about why; a 502 is ours and is logged.
    """
    if not isinstance(body, dict):
        raise OrderError(400)

    slug = body.get("funnel")
    if not config.funnel_exists(slug):
        raise OrderError(400)

    session_id = body.get("session_id")
    if not isinstance(session_id, str) or not UUID_RE.match(session_id):
        raise OrderError(400)

    cfg = config.load_funnel(slug)

    result_style = body.get("result_style")
    if result_style not in _style_ids(cfg):
        raise OrderError(400)

    pricing = cfg.get("pricing") or {}
    amount_cents = pricing.get("amount_cents")
    currency = pricing.get("currency")
    if not isinstance(amount_cents, int) or amount_cents <= 0 or not currency:
        log.error("funnel %s has no usable price", slug)
        raise OrderError(502)

    # Which key set this funnel transacts on, and a refusal rather than a
    # fallback when it asks for one that is not configured. Quietly billing a
    # test funnel against the live key would be the single worst outcome here,
    # so the missing-key branch stops instead of guessing.
    mode = _stripe_mode(cfg)
    secret = _stripe_secret(mode)
    if not secret:
        log.error(
            "funnel %s wants stripe_mode=%s but %s is not configured — "
            "refusing payment", slug, mode,
            "STRIPE_TEST_SECRET_KEY" if mode == TEST else "STRIPE_SECRET_KEY")
        raise OrderError(502)

    return {
        "slug": slug,
        "cfg": cfg,
        "session_id": session_id,
        "result_style": result_style,
        "amount_cents": amount_cents,
        "currency": currency,
        # Steer the report copy only — never the price, never whether we
        # fulfil.
        "tag_scores": _tag_scores_metadata(
            _clean_tag_scores(cfg, body.get("tag_scores"))),
        "choices": _choices_metadata(
            _clean_choices(cfg, body.get("choices"))),
        # Carried through Stripe so the server-side Purchase can be joined to
        # the click that produced it. Never used to decide anything.
        #
        # Two sources, the page's reading of its own cookies and the request's
        # own. The page's wins where it has one — it read `location.search`
        # for the click id, which this side only sees through a referrer — and
        # the request fills the gaps, which is what a blocked `document.cookie`
        # or an engine.js cached from before that code shipped leaves behind.
        # Where nothing has a joinable click id but a raw one arrived, it is
        # wrapped into Meta's format here, while "when the click was seen" is
        # still now rather than whenever the webhook happens to land.
        "meta_ids": _merged_meta_ids(_clean_meta_ids(body),
                                     _cookie_meta_ids()),
        # Held for the webhook, which fires from Stripe's request and so has
        # neither of these. Read once, then swept.
        "client_ip": _client_ip(),
        "client_ua": _client_ua(),
        "mode": mode,
        "secret": secret,
    }


@bp.post("/api/checkout")
def checkout():
    try:
        order = _validated_order(request.get_json(silent=True, force=True))
    except OrderError as exc:
        return jsonify({}), exc.status

    slug = order["slug"]
    cfg = order["cfg"]
    session_id = order["session_id"]
    result_style = order["result_style"]
    amount_cents = order["amount_cents"]
    currency = order["currency"]
    tag_scores = order["tag_scores"]
    choices = order["choices"]
    meta_ids = order["meta_ids"]
    mode = order["mode"]
    secret = order["secret"]

    # Before the session, so a Stripe call that succeeds cannot leave the
    # webhook with nothing to match on. It answers False rather than raising,
    # so a table that is not there yet costs match quality and not a sale.
    _save_context(session_id, order["client_ip"], order["client_ua"])

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


# --- POST /api/payment-intent ----------------------------------------------


@bp.post("/api/payment-intent")
def payment_intent():
    """A PaymentIntent for a payment confirmed in the page rather than on
    Stripe's.

    The same order as `/api/checkout`, priced the same way from the same
    config by the same function — the two differ only in what Stripe object
    they create and therefore in where the card details are typed. The hosted
    redirect remains the default and is untouched; nothing calls this yet.

    What comes back is a client secret and the *publishable* key. Neither is a
    credential: the client secret authorises confirming this one payment for
    this one amount, and the amount was fixed here, from the funnel, before
    the browser ever saw it. The client still cannot say what anything costs,
    and this route still does not confirm anything — only the webhook does.
    """
    try:
        order = _validated_order(request.get_json(silent=True, force=True))
    except OrderError as exc:
        return jsonify({}), exc.status

    slug = order["slug"]
    mode = order["mode"]

    # A payment nobody can confirm is worse than no payment: the charge would
    # be created and then stranded. Refused for the same reason and in the
    # same shape as a missing secret.
    publishable = _stripe_publishable(mode)
    if not publishable:
        log.error(
            "funnel %s wants stripe_mode=%s but %s is not configured — "
            "refusing payment intent", slug, mode,
            "STRIPE_TEST_PUBLISHABLE_KEY" if mode == TEST
            else "STRIPE_PUBLISHABLE_KEY")
        return jsonify({}), 502

    # The wallet path reaches the same webhook, so it holds the same context.
    _save_context(order["session_id"], order["client_ip"], order["client_ua"])

    try:
        intent = stripe.PaymentIntent.create(
            # Extracted by the SDK as a request option, never sent as a form
            # field. Passed rather than assigned so two funnels in two modes
            # cannot take each other's key off the module.
            api_key=order["secret"],
            amount=order["amount_cents"],
            currency=order["currency"],
            # Stripe decides which methods to offer from the account's
            # settings and the device, which is what makes the wallets appear
            # without this route naming any of them.
            automatic_payment_methods={"enabled": True},
            # The same metadata the checkout session carries, from the same
            # builder — the webhook reads one shape whichever object produced
            # the payment.
            metadata=_metadata(slug, order["session_id"],
                               order["result_style"], order["tag_scores"],
                               order["choices"], order["meta_ids"]),
        )
    except Exception:
        # Stripe's message can echo request contents — log the type only.
        log.exception("stripe payment intent create failed for funnel %s", slug)
        return jsonify({}), 502

    return jsonify({
        "client_secret": intent.client_secret,
        "publishable_key": publishable,
        "amount_cents": order["amount_cents"],
        "currency": order["currency"],
    })


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


# Both ways a payment reaches us. The hosted redirect is the one carrying
# money today; the intent is what an in-page confirmation produces. Anything
# else is acknowledged and ignored.
PAID_EVENTS = frozenset(("checkout.session.completed",
                         "payment_intent.succeeded"))


def _from_checkout_session(session):
    """The paid facts, off a Checkout Session. None when it has no amount."""
    amount_cents = session.get("amount_total")
    if not isinstance(amount_cents, int):
        return None
    payment_intent = session.get("payment_intent")
    return {
        "amount_cents": amount_cents,
        "currency": (session.get("currency") or "usd")[:3],
        "details": session.get("customer_details") or {},
        "payment_intent": (payment_intent
                           if isinstance(payment_intent, str) else None),
        "checkout_session": session.get("id"),
    }


def _as_plain_dict(obj):
    """A Stripe SDK object as a plain dict, all the way down. `{}` on anything
    else.

    The one boundary between the SDK's object model and this module, which
    reads dicts and nothing else. Two ways of getting it wrong were both live
    here at once and both crashed the webhook:

    - `.get()` does not exist on a `StripeObject` in SDK 15.x. It is no longer
      a dict subclass, so `.get` is not a method but a field lookup on an
      object that has no such field, and it raises AttributeError.
    - `dict(obj)` does not work either. There is no `keys()` for the mapping
      protocol to find, so it falls back to iterating the object as a sequence
      of pairs and raises `KeyError: 0`. Swapping `.get(k)` for `[k]` alone
      would have moved the crash one line, not removed it.

    `to_dict()` is the SDK's own answer and it recurses by default, so nested
    objects — `billing_details`, the `address` inside it — come back as plain
    dicts too and one conversion is genuinely enough. Everything below this
    function uses ordinary dict access.
    """
    if isinstance(obj, dict):
        return obj
    to_dict = getattr(obj, "to_dict", None)
    if not callable(to_dict):
        return {}
    value = to_dict()
    return value if isinstance(value, dict) else {}


def _billing_details(intent, cfg):
    """Who paid, off the charge behind an intent. `{}` when it cannot be read.

    A PaymentIntent does not carry an email of its own — it is on the charge,
    which the event may or may not expand. Recent API versions send
    `latest_charge` as a bare id, older ones inline `charges.data[0]`, and both
    are handled here rather than assumed.

    Failing to find it is not a failure of the payment. A purchase with no
    email is already an ordinary case on the existing path: the row is written,
    the report is generated, and only the email delivery is skipped. A missing
    address is a delivery gap; a 500 here is a paid reader watching a spinner
    that will never finish, because the purchase was never recorded at all.

    `intent` arrives from `json.loads` of the webhook body, so it and anything
    reached through it are already plain dicts. The single object in this
    function that is not is the one fetched from the API below.
    """
    charge = intent.get("latest_charge")
    if isinstance(charge, dict):
        return charge.get("billing_details") or {}

    inline = ((intent.get("charges") or {}).get("data") or [])
    if inline and isinstance(inline[0], dict):
        return inline[0].get("billing_details") or {}

    if not isinstance(charge, str) or not charge:
        return {}

    # Only reached when the event carried an id rather than the object. The
    # mode's own key, for the same reason every other call names one.
    secret = _stripe_secret(_stripe_mode(cfg))
    if not secret:
        return {}
    try:
        fetched = stripe.Charge.retrieve(charge, api_key=secret)
        # Converted inside the try on purpose: a `to_dict` that failed would
        # otherwise escape as a 500 and cost the purchase, which is exactly
        # what this whole path is written to avoid.
        charge_data = _as_plain_dict(fetched)
    except Exception as exc:
        # An address we could not fetch costs an email. It does not cost the
        # purchase, so this is a warning and the flow continues.
        log.warning("could not retrieve charge for a payment intent: %s",
                    type(exc).__name__)
        return {}
    return charge_data.get("billing_details") or {}


def _from_payment_intent(intent, cfg):
    """The paid facts, off a PaymentIntent. None when nothing was received.

    `amount_received` and not `amount`: the first is what was actually taken,
    the second is what was asked for. On a succeeded intent they agree, and on
    anything else the difference is the whole point.
    """
    amount_cents = intent.get("amount_received")
    if not isinstance(amount_cents, int) or amount_cents <= 0:
        return None

    billing = _billing_details(intent, cfg)
    return {
        "amount_cents": amount_cents,
        "currency": (intent.get("currency") or "usd")[:3],
        # Reshaped to the customer_details keys the rest of this handler reads,
        # so one insert serves both paths.
        "details": {"email": billing.get("email"),
                    "address": billing.get("address") or {}},
        "payment_intent": intent.get("id"),
        # There was no checkout session. This is the column the migration
        # exists to allow NULL in.
        "checkout_session": None,
    }


def _is_live_payment(event, checkout_session):
    """Whether Meta should hear about this. Absence is never evidence.

    `livemode` is the authority and the only marker the intent path has — a
    `pi_` id looks identical in both modes, so there is nothing else to read
    and nothing worth inventing. On the checkout path the session id carries a
    `cs_test_` prefix as a second, independent marker, and it is still used
    there.

    An event with no `livemode` at all behaves exactly as it did before any of
    this, so a live purchase can never be lost to a missing field.
    """
    if event.get("livemode") is False:
        return False
    return not str(checkout_session or "").startswith("cs_test_")


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

    kind = event.get("type")
    if kind not in PAID_EVENTS:
        return jsonify({"status": "ignored"}), 200

    obj = (event.get("data") or {}).get("object") or {}
    metadata = obj.get("metadata") or {}

    slug = metadata.get("funnel")
    session_id = metadata.get("session_id")
    result_style = metadata.get("result_style")

    if not config.funnel_exists(slug) or not (
        isinstance(session_id, str) and UUID_RE.match(session_id)
    ):
        # Payments created outside this funnel (or by an older build) are not
        # ours to record. Acknowledge so Stripe stops retrying.
        log.warning("webhook %s has unusable metadata — skipped", event.get("id"))
        return jsonify({"status": "skipped"}), 200

    # The two objects that mean "this was paid for" describe the same facts
    # under different names, so they are read into one shape here and
    # everything below this line is written once.
    if kind == "payment_intent.succeeded":
        paid = _from_payment_intent(obj, config.load_funnel(slug))
    else:
        paid = _from_checkout_session(obj)

    if paid is None:
        log.warning("webhook %s has no usable amount — skipped",
                    event.get("id"))
        return jsonify({"status": "skipped"}), 200

    amount_cents = paid["amount_cents"]
    currency = paid["currency"]
    details = paid["details"]
    address = details.get("address") or {}
    payment_intent = paid["payment_intent"]
    checkout_session = paid["checkout_session"]

    try:
        purchase_id = database.execute(
            INSERT_PURCHASE_SQL,
            (
                slug,
                session_id,
                event.get("id"),
                payment_intent,
                checkout_session,
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
    live_purchase = _is_live_payment(event, checkout_session)
    if not live_purchase:
        # Names the payment, not the signature: an event can be signed with the
        # live secret and still be a test payment, and a line claiming
        # otherwise is the one you would read while wondering where a
        # conversion went.
        log.info("purchase %s is not a live payment (signature: %s) — Meta "
                 "purchase event skipped", purchase_id, signed)
    else:
        try:
            # What the browser knew, read back once. A session that never
            # got a row — an older payment, a table not yet applied — sends
            # exactly what it sent before.
            context_ip, context_ua = _read_context(session_id)
            send_purchase_event(
                purchase_id, slug, amount_cents, currency,
                email=details.get("email"), payment_intent=payment_intent,
                meta_ids=_clean_meta_ids(metadata),
                event_time=int(event.get("created") or time.time()),
                session_id=session_id,
                client_ip=context_ip, client_ua=context_ua,
            )
        except Exception as exc:
            log.warning("Meta purchase event raised for purchase %s: %s",
                        purchase_id, type(exc).__name__)

    cfg = config.load_funnel(slug)
    tag_scores = _read_tag_scores(cfg, metadata.get("tag_scores"))
    choices = _read_choices(cfg, metadata.get("choices"))
    _record_side_effects(
        purchase_id, slug, session_id, result_style, tag_scores,
        email=details.get("email"), checkout_session=checkout_session,
        choices=choices,
    )
    return jsonify({"status": "ok"}), 200


# --- GET /api/report -------------------------------------------------------


def _mask_email(address):
    """`j***@gmail.com`, or None when there is nothing safe to show.

    Enough for someone to recognise which inbox to check while they are still
    waiting, and not enough to be worth harvesting. This is what every state
    of this route except one shows.

    The exception is the finished report, which carries the full address so
    the page can confirm where the PDF went. That is a deliberate widening and
    it is bounded: the request has already proved it holds this purchase's
    token, the address is the requester's own, and it is attached to the
    response rather than to anything stored or logged.
    """
    if not isinstance(address, str) or address.count("@") != 1:
        return None
    local, _, domain = address.partition("@")
    if not local or not domain:
        return None
    return "%s***@%s" % (local[0], domain)


@bp.get("/api/report")
def report():
    # Still `cs`, and still every `cs_` link that has ever been emailed. The
    # parameter name is the shape in the wild and is not worth changing to
    # match what a token can now also be.
    cs = request.args.get("cs", "")
    if not RESULT_TOKEN_RE.match(cs):
        return jsonify({}), 400

    purchase = find_purchase(cs)
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
    # The finished report, and the address its PDF went to. Attached to this
    # response only — never to the stored row, which is what the PDF and the
    # mail are built from — and only once there is a report to deliver, so the
    # pending poll keeps showing the masked form it always did.
    body["report"] = reports.delivered_content(content, purchase.get("email"))
    return jsonify(body), 200
