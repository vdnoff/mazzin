"""Event tracking API.

One endpoint, one INSERT, no reads. This is on the hot path of every swipe,
so it stays boring and fast.

Nothing user-supplied is ever written to the error log — bad input gets a
bare 400 and a counter-style log line at most.
"""

import json
import logging
import os
import re

from flask import Blueprint, request

import config
import database

log = logging.getLogger(__name__)

bp = Blueprint("tracking", __name__)

# In funnel order. `mid_cta` and `sticky_cta` are the two prompts on the
# single-page result that ask for a scroll rather than a payment; `paywall_view`
# is the offer actually reaching the reader and carries which of them sent them
# there. `paywall_open` belongs to the two-screen flow behind the config flag
# and stays allowed for as long as that flag can be turned off. `pay_tap` is the
# tap that starts paying — one name covered both it and opening the paywall
# until the split, which made the gap between wanting to know the price and
# being willing to pay it unmeasurable. `checkout_error` is the client saying
# its own checkout call failed; it carries no detail, and being client-asserted
# it is a signal to look at the server logs rather than a count to trust alone.
#
# `purchase` is deliberately absent: it is written server-side by the Stripe
# webhook in Phase 1b and must never be client-assertable.
ALLOWED_EVENTS = {
    "funnel_start",
    # The tap on an intro card's own button. `funnel_start` is the page
    # arriving; this is somebody deciding to begin, and the gap between the
    # two is the only measurement of a screen whose whole job is to be got
    # past. It carries no payload — `_clean_extra` refuses an `extra` on
    # anything but the six that have one — and only a funnel declaring an
    # `intro` block can emit it at all.
    "intro_start",
    "swipe",
    "interstitial",
    "result_view",
    "mid_cta",
    "sticky_cta",
    "paywall_view",
    "paywall_open",
    "pay_tap",
    "checkout_error",
    # After the money, not before it. These four are the visualizer's funnel
    # inside the funnel — a photo chosen, a transformation asked for, and
    # which way it ended — and they are the only events here that describe
    # something happening on a page somebody has already paid for.
    #
    # They carry no payload at all: `_clean_extra` rejects an `extra` on
    # anything but a swipe and a paywall view, so a filename or an image
    # dimension cannot ride along on one even if a future client tried to
    # send it. What a photograph was called is the reader's business.
    "viz_upload",
    "viz_generate",
    "viz_ready",
    "viz_failed",
    # The locked panel reaching the reader's screen: their own kitchen beside
    # the transformation they have not bought. It is the visualizer's
    # `paywall_view` — the moment the offer is actually made — and without it
    # the upload-to-purchase rate has no denominator.
    "viz_teaser_view",
    # The bottom of the offer, before a photograph exists: the price is on
    # screen but the pay control is not, and what stands in its place is a
    # button asking for the kitchen first. `viz_gate_view` is that state
    # reaching the reader, once per session rather than once per scroll past
    # it; `viz_gate_tap` is them accepting it and going back up for the photo.
    #
    # Without the pair there is no denominator for the upload: a reader who
    # reached the offer and never uploaded is indistinguishable from one who
    # never got that far, and those are opposite problems.
    "viz_gate_view",
    "viz_gate_tap",
    # Which pay control the reader was actually shown, once per session, at the
    # moment it appears. `pay_tap` already says which button took a payment —
    # but only for somebody who tapped one, and the question that costs money
    # is about the people who did not.
    #
    # Twelve sessions uploaded a photo, reached the offer, spent two to eight
    # minutes on it and produced one tap and no purchase. Whether they were
    # looking at an Apple Pay button or a trip to a hosted page is the first
    # thing you would want to know, and nothing recorded it.
    "pay_ready",
    # The reader handing the result to somebody else. It is the only event
    # here that describes a person leaving with something rather than moving
    # through the funnel, and it is the front of a loop the funnel otherwise
    # has no measurement of: what comes back arrives as `subid=share-<id>` on
    # an ordinary `funnel_start`, through the attribution columns that already
    # exist, so this event and that one are the two ends of the same number.
    "share_tap",
    # Which arm of a paywall test this session was shown, written once when
    # the offer is drawn. It is the only row that says so: the events after
    # it carry no variant of their own and do not need to, because they carry
    # the session id and this one does too. Splitting conversion by variant is
    # a join, which is what keeps a new arm a config edit instead of a
    # migration.
    "paywall_variant",
}

# How many cells one swipe step can have drawn. This is engine.js's GRID_SIZE
# plus the pair, and it is a closed set for the same reason the event names
# are: the number is the client's word about our own layout, and a swipe
# claiming a size no format produces is not a swipe this funnel served.
SHOWN_SIZES = frozenset((2, 4, 6, 12))

# `viz_upload` happens on both sides of the money now, and the two are
# different events wearing one name: one is somebody still deciding, the other
# is somebody who has already paid. A closed set of two, for the same reason
# `paywall_view` has one — a field whose whole purpose is to be grouped by
# cannot afford a typo in a client that ships to everybody.
VIZ_UPLOAD_PHASE = frozenset(("pre", "post"))

# How the browser got the photograph into the request: a memory-safe
# `createImageBitmap` resize, an ordinary canvas draw, or the raw file exactly
# as the camera wrote it. Most of the traffic here is Android inside an in-app
# WebView, where the first two are the ones that fail, and this field is the
# only way to see which one a real device actually took.
VIZ_UPLOAD_PATH = frozenset(("bitmap", "canvas", "raw"))

# Which button was pressed. `redirect` is the trip to Stripe's hosted page that
# every funnel has always had; `wallet` is a sheet opening over the paywall
# itself. They are the same intention through very different amounts of
# friction, and without this field the difference between them is invisible in
# a table that has one row per tap.
#
# A closed set, for the reason every closed set here is one: this is a field
# whose whole purpose is to be grouped by, and a typo in a client that ships to
# everybody would become a category nobody notices is missing.
PAY_TAP_METHOD = frozenset(("wallet", "redirect"))

# Which control was on screen, as opposed to which one was pressed. The same
# two words as `pay_tap.method` and deliberately the same two: the pair is only
# useful read together, as a rate — of the people shown a wallet, how many
# tapped it — and two vocabularies for one thing would make that a join with a
# CASE in it.
#
# It is a separate set rather than a reuse of PAY_TAP_METHOD because the two
# answer different questions and will not necessarily move together: a future
# third control would be showable before it is tappable.
PAY_READY_CONTROL = frozenset(("wallet", "redirect"))


def _clean_pay_ready(value):
    """`{"control": ...}` from a closed set, and nothing else.

    Required, unlike `pay_tap`'s method: this event did not exist before the
    payload did, so there is no cached engine.js that sends one without it.
    """
    if set(value) != {"control"}:
        raise ValueError("extra")
    control = value["control"]
    if not isinstance(control, str) or control not in PAY_READY_CONTROL:
        raise ValueError("extra")
    return {"control": control}


def _clean_pay_tap(value):
    """`{"method": ...}` from a closed set, and nothing else.

    Optional in the sense that matters: `pay_tap` with no payload at all is
    still accepted, because engine.js sits behind a CDN and the version that
    sent none will be served for a while yet. What is not accepted is a
    `pay_tap` carrying anything other than exactly this.
    """
    if set(value) != {"method"}:
        raise ValueError("extra")
    method = value["method"]
    if not isinstance(method, str) or method not in PAY_TAP_METHOD:
        raise ValueError("extra")
    return {"method": method}


def _clean_viz_upload(value):
    """`{"phase": ..., "path": ...}`, both from closed sets. Raises otherwise.

    Rebuilt rather than passed through, like every other payload here. Nothing
    about the photograph is carried — not its name, not its size, not its
    dimensions — and this shape is what makes that structural rather than a
    convention somebody has to remember.

    `path` is optional: an engine.js cached from before it shipped sends a
    payload with only `phase` in it, and the CDN will be serving one of those
    for a while after this deploys.
    """
    keys = set(value)
    if not keys or not keys.issubset({"phase", "path"}) or "phase" not in keys:
        raise ValueError("extra")

    phase = value["phase"]
    if not isinstance(phase, str) or phase not in VIZ_UPLOAD_PHASE:
        raise ValueError("extra")
    out = {"phase": phase}

    if "path" in keys:
        path = value["path"]
        if not isinstance(path, str) or path not in VIZ_UPLOAD_PATH:
            raise ValueError("extra")
        out["path"] = path
    return out

# --- what they were using ---------------------------------------------------

# Two words about the device, derived here from the User-Agent header and
# written onto the session's `funnel_start` row.
#
# Server-side and not client-reported, for two reasons. A client-sent field is
# one more untrusted string to validate, and it is trivially spoofable — and
# this one is going to be used to decide where to spend, so a value anybody can
# set is a number nobody can act on. The header is already in the request.
#
# The raw User-Agent is NOT stored, here or anywhere. It carries the OS build,
# the browser build and often the exact handset model, which together identify
# a returning visitor far more precisely than anything else this app keeps —
# and none of that is needed to answer "did the wallet show up on Instagram's
# browser". What is stored is two enum values out of the sets below and
# nothing else: no version, no device model, no screen size, no IP, no
# Accept-Language.
#
# A UA that matches nothing lands on `other` rather than being dropped. A
# growing `other` bucket is a prompt to come and look; a missing row is not.
UA_PLATFORM = frozenset(("ios", "android", "desktop", "other"))
UA_BROWSER = frozenset(("facebook", "instagram", "safari", "chrome",
                        "firefox", "edge", "samsung", "webview", "other"))

# Only the head of the header is read. A User-Agent is conventionally under
# 256 characters and these tokens all appear early; a request arriving with
# sixteen kilobytes of it should not turn into sixteen kilobytes of scanning
# on the hottest path on the site.
UA_SCAN_CHARS = 512

# Order is the whole correctness of this. The Instagram in-app browser's UA
# contains both "Safari" and "Chrome", and the Facebook one on Android does
# too — so testing for Safari or Chrome first files every in-app session as an
# ordinary browser, which is precisely the distinction this exists to draw.
# In-app first, then the vendors that also claim to be Chrome, then Chrome,
# then Safari last as the residue.
_BROWSER_TOKENS = (
    ("facebook", ("fban/", "fbav/", "fb_iab", "fbios", "fbsv/")),
    ("instagram", ("instagram",)),
    ("samsung", ("samsungbrowser",)),
    ("edge", ("edg/", "edgios", "edga/")),
    ("firefox", ("firefox/", "fxios")),
    ("webview", ("; wv)", "; wv;")),
    ("chrome", ("crios", "chrome/", "chromium")),
    ("safari", ("safari/",)),
)

_PLATFORM_TOKENS = (
    ("ios", ("iphone", "ipad", "ipod", "fbios", "crios", "fxios", "edgios")),
    ("android", ("android",)),
    ("desktop", ("windows", "macintosh", "cros", "x11", "linux")),
)


def _device(user_agent):
    """`{"platform": ..., "browser": ...}` for one request.

    Pure string work on a header that is already in memory: no I/O, no regex
    backtracking, no allocation beyond one lowercased slice. It runs once per
    session, on `funnel_start`, and adds nothing that can block or fail — a
    header that is missing, empty or unrecognisable produces `other`/`other`
    rather than an exception, because a device we cannot name is not a reason
    to lose the event.
    """
    low = (user_agent or "")[:UA_SCAN_CHARS].lower()

    platform = "other"
    for name, tokens in _PLATFORM_TOKENS:
        if any(token in low for token in tokens):
            # Android before desktop: an Android UA says "Linux" too.
            platform = name
            break

    browser = "other"
    for name, tokens in _BROWSER_TOKENS:
        if any(token in low for token in tokens):
            browser = name
            break

    return {"platform": platform, "browser": browser}


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


# --- the swipe payload ------------------------------------------------------

# What a step is allowed to have shown. A step carrying a bare `images` list
# is its own single pair, which is the pre-3d shape and still valid — the
# funnel JSON and engine.js sit behind a CDN and can be a version apart for a
# while after a deploy.
def _pairs_of(step):
    pairs = step.get("pairs")
    if isinstance(pairs, list) and pairs:
        return [p for p in pairs if isinstance(p, dict)]
    images = step.get("images")
    if isinstance(images, list) and images:
        return [{"id": "p1", "images": images}]
    return []


_INDEX = {}     # slug -> (mtime, {"pairs": frozenset, "images": frozenset})


def _funnel_index(slug):
    """The step/pair keys, image ids and share cards one funnel can produce.

    None when the slug names no config. Everything in here is something the
    client is allowed to claim it drew or handed over, so it is exactly what
    the config says and nothing derived.

    Held rather than re-read. This runs once per swipe, and a file read plus a
    JSON parse to check three short strings would be by far the slowest thing
    on the path. The config's mtime is the cache key, so `deploy.sh` rewriting
    it is picked up by the next event without a restart, and a stat is all the
    steady state costs.
    """
    path = os.path.join(config.FUNNELS_DIR, slug + ".json")
    try:
        stamp = os.path.getmtime(path)
    except OSError:
        return None

    hit = _INDEX.get(slug)
    if hit is not None and hit[0] == stamp:
        return hit[1]

    try:
        cfg = config.load_funnel(slug)
    except (KeyError, ValueError, OSError):
        return None

    pairs, images = set(), set()
    for step in ((cfg.get("swipe") or {}).get("steps") or []):
        if not isinstance(step, dict):
            continue
        step_id = step.get("id")
        for pair in _pairs_of(step):
            pair_id = pair.get("id")
            if isinstance(step_id, str) and isinstance(pair_id, str):
                pairs.add(step_id + ":" + pair_id)
            for item in (pair.get("images") or []):
                if isinstance(item, dict) and isinstance(item.get("id"), str):
                    images.add(item["id"])

    shares = set()
    for card in (cfg.get("share_cards") or []):
        if isinstance(card, dict) and isinstance(card.get("id"), str):
            shares.add(card["id"])

    # Every variant the config declares, enabled or not. A disabled variant
    # is still a legal thing for an event to name: a session assigned to it
    # before it was turned off can have its arm reported on the same page
    # load that the flag flipped under, and dropping that row would be
    # dropping the truth about a reader who really was shown it.
    variants = set()
    for variant in (cfg.get("paywall_variants") or []):
        if isinstance(variant, dict) and isinstance(variant.get("id"), str):
            variants.add(variant["id"])

    index = {"pairs": frozenset(pairs), "images": frozenset(images),
             "shares": frozenset(shares), "variants": frozenset(variants)}
    _INDEX[slug] = (stamp, index)
    return index


SWIPE_EXTRA_KEYS = frozenset(("pair", "shown", "chosen"))

# What a swipe MAY also carry. Optional rather than required, because a client
# cached from before they existed sends neither and is not wrong — and because
# the two of them are a funnel-level opt-in: engine.js writes them only where
# the config names `track_timing`, so every other funnel goes on sending the
# three above and nothing else.
#
# Optional is not lax. A key not on this list still refuses the whole event, a
# value of the wrong type still refuses it, and what is stored is rebuilt here
# rather than passed through — exactly as the three required ones are.
#
# `elapsed_ms` is how long the question was on screen before the tap, in whole
# milliseconds. The ceiling mirrors ELAPSED_MAX_MS in engine.js, which is where
# the clamp actually happens; this is the second one, because the client's is a
# courtesy and this is the boundary. A minute is already a phone that was put
# down rather than a decision being made.
#
# `timed_out` says the step answered itself. It is true or it is absent: a
# client sending `false` is sending the default, and the column is easier to
# read when the rows that carry it are the rows it happened on. `False` is
# accepted rather than refused, because refusing it would break a client that
# was being tidy, and it is simply not stored.
ELAPSED_MAX_MS = 60000
SWIPE_EXTRA_OPTIONAL = frozenset(("elapsed_ms", "timed_out"))

# What a share tap says: which card was handed over. One key, and its value is
# checked against the share cards the config declares rather than against a
# list kept here — the same rule every other id on this path follows, and the
# reason a funnel that declares none can produce no valid share tap at all.
SHARE_EXTRA_KEYS = frozenset(("persona",))

# How somebody arrived at the offer. A closed set, because the point of the
# field is to be grouped by — one typo in a client that ships to everybody
# would otherwise become a category nobody notices is missing.
PAYWALL_VIEW_KEYS = frozenset(("src",))

# What a paywall variant says: which arm of the test this session was shown.
# One key, one row per session, and every later event on that session — the
# paywall view, the pay tap, and the purchase the webhook writes — already
# carries the same `session_id`. That is why this can be one small event
# rather than a column added to all of them.
VARIANT_EXTRA_KEYS = frozenset(("variant",))
# `teaser_cta` is the button under the visualizer's two panels — their kitchen
# beside their kitchen behind a lock. It gets a word of its own rather than
# borrowing `mid_cta`: the two sit on different funnels, in front of different
# arguments, and the question the button was put back to answer is how many
# readers the panels send down to the offer. Folded into another bucket, that
# number cannot be read out again.
PAYWALL_VIEW_SRC = frozenset(("mid_cta", "sticky", "scroll", "teaser_cta"))


def _clean_paywall_view(value):
    """`{"src": ...}` and nothing else. Raises on anything it is not.

    Rebuilt rather than passed through, like the swipe payload above it: what
    reaches the column is a string this module chose from a set it owns.
    """
    if set(value) != PAYWALL_VIEW_KEYS:
        raise ValueError("extra")
    src = value["src"]
    if not isinstance(src, str) or src not in PAYWALL_VIEW_SRC:
        raise ValueError("extra")
    return {"src": src}


def _clean_share_tap(funnel, value):
    """`{"persona": "<share card id>"}`, checked against the config.

    The id is not parsed and not pattern-matched: it either is one of the
    share cards this funnel declares or it is not. That keeps the funnel's own
    vocabulary out of this module — a second funnel wanting the same event
    declares its own cards and needs nothing here — and it keeps the column a
    closed set, which is the only reason it is worth grouping by.
    """
    if set(value) != SHARE_EXTRA_KEYS:
        raise ValueError("extra")
    index = _funnel_index(funnel)
    if index is None:
        raise ValueError("extra")
    persona = value["persona"]
    if not isinstance(persona, str) or persona not in index["shares"]:
        raise ValueError("extra")
    return {"persona": persona}


def _clean_paywall_variant(funnel, value):
    """`{"variant": "<variant id>"}`, checked against the config.

    The same rule as a share tap: the id either is one of the variants this
    funnel declares or it is not, and nothing here knows what any of them are
    called. A funnel that declares no variants can produce no valid event of
    this kind, which is what makes the column a closed set worth grouping by
    — and grouping by it is the whole reason the event exists.
    """
    if set(value) != VARIANT_EXTRA_KEYS:
        raise ValueError("extra")
    index = _funnel_index(funnel)
    if index is None:
        raise ValueError("extra")
    variant = value["variant"]
    if not isinstance(variant, str) or variant not in index["variants"]:
        raise ValueError("extra")
    return {"variant": variant}


def _clean_extra(funnel, event, value):
    """The event payload, rebuilt from validated parts. Raises on junk.

    Six events carry one: a swipe says which pair it drew and which image was
    tapped, a paywall view says how the reader got to the offer, a pay tap says
    which of the two buttons took it, a visualizer upload says which side of
    the money it happened on, a share tap says which card was handed over, and
    a paywall variant says which arm of the offer test was drawn. Every string is checked against something this module can
    enumerate — ids this funnel could actually have shown, or one of the
    closed sets above — and the value stored is assembled here rather than
    passed through, so nothing reaches the events column that did not come
    out of the config or this file.

    This used to take any JSON object up to four thousand characters and write
    it — which made the column a free write for anybody who found the endpoint,
    and truncated the overflow into JSON that would not parse back. An event
    with no payload is still fine: an engine.js cached from before either of
    these shipped sends none.
    """
    if value is None:
        return None
    if not isinstance(value, dict):
        raise ValueError("extra")
    if event == "paywall_view":
        return _clean_paywall_view(value)
    if event == "viz_upload":
        return _clean_viz_upload(value)
    if event == "pay_tap":
        return _clean_pay_tap(value)
    if event == "pay_ready":
        return _clean_pay_ready(value)
    if event == "share_tap":
        return _clean_share_tap(funnel, value)
    if event == "paywall_variant":
        return _clean_paywall_variant(funnel, value)
    if event != "swipe":
        raise ValueError("extra")
    keys = set(value)
    if not SWIPE_EXTRA_KEYS <= keys:
        raise ValueError("extra")
    if keys - SWIPE_EXTRA_KEYS - SWIPE_EXTRA_OPTIONAL:
        raise ValueError("extra")

    index = _funnel_index(funnel)
    if index is None:
        raise ValueError("extra")

    pair = value["pair"]
    if not isinstance(pair, str) or pair not in index["pairs"]:
        raise ValueError("extra")

    # Two for a pair step, four for a grid, six for a palette grid, twelve for
    # a whole zodiac at once. The set mirrors GRID_SIZE in engine.js, which is
    # the only thing that decides how many cells a step can draw — anything
    # else is not a step this engine can render, whatever the client says it
    # drew.
    shown = value["shown"]
    if not isinstance(shown, list) or len(shown) not in SHOWN_SIZES:
        raise ValueError("extra")
    for image_id in shown:
        if not isinstance(image_id, str) or image_id not in index["images"]:
            raise ValueError("extra")
    if len(set(shown)) != len(shown):
        raise ValueError("extra")

    chosen = value["chosen"]
    # Against `shown` rather than the funnel: a choice the reader could not
    # have made on the pair they were given is not a choice.
    if not isinstance(chosen, str) or chosen not in shown:
        raise ValueError("extra")

    out = {"pair": pair, "shown": list(shown), "chosen": chosen}

    # The two the timing funnels add. Checked the same way everything above is
    # — the type first, then the range — and rebuilt into the answer rather
    # than copied out of the request.
    if "elapsed_ms" in value:
        elapsed = value["elapsed_ms"]
        # `bool` is an `int` in Python and `True` would store as 1ms, which is
        # a reaction nobody has ever had.
        if not isinstance(elapsed, int) or isinstance(elapsed, bool):
            raise ValueError("extra")
        if elapsed < 0 or elapsed > ELAPSED_MAX_MS:
            raise ValueError("extra")
        out["elapsed_ms"] = elapsed
    if "timed_out" in value:
        if not isinstance(value["timed_out"], bool):
            raise ValueError("extra")
        if value["timed_out"]:
            out["timed_out"] = True
    return out


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

    try:
        extra = _clean_extra(funnel, event, body.get("extra"))
    except ValueError:
        return "", 400

    # After validation, never before. `_clean_extra` still refuses any `extra`
    # a client sends on `funnel_start`, so this is the only way these two words
    # can get onto the row — a request cannot supply them, and cannot overwrite
    # them by supplying its own. That is the whole reason it is derived here
    # from a header rather than accepted as a field.
    #
    # Once a session, on the first event of it, because the device does not
    # change halfway through a quiz and paying for it on all twenty rows would
    # be twenty copies of the same two words.
    if event == "funnel_start":
        extra = _device(request.headers.get("User-Agent"))
    # No cap needed any more: what comes back is three ids out of the funnel's
    # own config, so its length is bounded by the config rather than by the
    # request.
    extra_json = (json.dumps(extra, separators=(",", ":"))
                  if extra is not None else None)

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
