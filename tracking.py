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
}

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
    """The step/pair keys and image ids one funnel can produce, or None.

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

    index = {"pairs": frozenset(pairs), "images": frozenset(images)}
    _INDEX[slug] = (stamp, index)
    return index


SWIPE_EXTRA_KEYS = frozenset(("pair", "shown", "chosen"))

# How somebody arrived at the offer. A closed set, because the point of the
# field is to be grouped by — one typo in a client that ships to everybody
# would otherwise become a category nobody notices is missing.
PAYWALL_VIEW_KEYS = frozenset(("src",))
PAYWALL_VIEW_SRC = frozenset(("mid_cta", "sticky", "scroll"))


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


def _clean_extra(funnel, event, value):
    """The event payload, rebuilt from validated parts. Raises on junk.

    Four events carry one: a swipe says which pair it drew and which image was
    tapped, a paywall view says how the reader got to the offer, a pay tap says
    which of the two buttons took it, and a visualizer upload says which side
    of the money it happened on. Every string is checked against something this
    module can enumerate — ids this funnel could actually have shown, or one of
    the closed sets above — and the value stored is assembled here rather than
    passed through, so nothing reaches the events column that did not come out
    of the config or this file.

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
    if event != "swipe":
        raise ValueError("extra")
    if set(value) != SWIPE_EXTRA_KEYS:
        raise ValueError("extra")

    index = _funnel_index(funnel)
    if index is None:
        raise ValueError("extra")

    pair = value["pair"]
    if not isinstance(pair, str) or pair not in index["pairs"]:
        raise ValueError("extra")

    # Two for a pair step, four for a grid, six for the palette grid.
    # Anything else is not a step this engine can render, whatever the client
    # says it drew.
    shown = value["shown"]
    if not isinstance(shown, list) or len(shown) not in (2, 4, 6):
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

    return {"pair": pair, "shown": list(shown), "chosen": chosen}


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
