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


def _clean_extra(funnel, event, value):
    """The swipe payload, rebuilt from validated parts. Raises on junk.

    Every string is checked against ids this funnel could actually have shown,
    and the value stored is assembled here rather than passed through, so
    nothing reaches the events column that did not come out of the config.

    This used to take any JSON object up to four thousand characters and write
    it — which made the column a free write for anybody who found the endpoint,
    and truncated the overflow into JSON that would not parse back. A swipe
    with no payload is still fine: an engine.js cached from before this shipped
    sends none.
    """
    if value is None:
        return None
    if event != "swipe" or not isinstance(value, dict):
        raise ValueError("extra")
    if set(value) != SWIPE_EXTRA_KEYS:
        raise ValueError("extra")

    index = _funnel_index(funnel)
    if index is None:
        raise ValueError("extra")

    pair = value["pair"]
    if not isinstance(pair, str) or pair not in index["pairs"]:
        raise ValueError("extra")

    shown = value["shown"]
    if not isinstance(shown, list) or len(shown) != 2:
        raise ValueError("extra")
    for image_id in shown:
        if not isinstance(image_id, str) or image_id not in index["images"]:
            raise ValueError("extra")
    if shown[0] == shown[1]:
        raise ValueError("extra")

    chosen = value["chosen"]
    # Against `shown` rather than the funnel: a choice the reader could not
    # have made on the pair they were given is not a choice.
    if not isinstance(chosen, str) or chosen not in shown:
        raise ValueError("extra")

    return {"pair": pair, "shown": [shown[0], shown[1]], "chosen": chosen}


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
