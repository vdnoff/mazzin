"""The RSOC quiz engine's server half: the page route and its one event route.

An RSOC quiz is a few closed tap questions that end on a short list of
partner article links. It takes no payment, posts no answers and collects no
contact detail: the only thing the server ever hears is an event. One engine
serves every vertical. A vertical is a file, `funnels/rsoc/<slug>.json`, and
the browser renders all of it — its copy, its article keys, its rules — so a
new one is a new file and no code.

What this module owns:

  - `GET /<slug>` for every slug that has a config, answered with
    `static/rsoc.html` with the slug written into it;
  - `POST /api/rsoc/<slug>/event` — the same validation, the same `events`
    table and the same columns as `/api/loans/event`, with `funnel` set to
    the slug, so the dashboard and the console scripts read it unchanged.

How the page route stays out of everybody else's way. The swipe funnels are
served by `app.py`'s `/<slug>`, and a second variable rule of the same shape
cannot be ordered against it reliably. So each configured slug gets a static
rule of its own, added when this blueprint is built — the same kind of rule
`/loans` is, and static rules always win over `/<slug>`. A slug that names
anything the site already answers (a swipe funnel, `/loans`, a page, an API
prefix) is skipped with a warning rather than allowed to take it over. The
list is read at start-up: a new config is live after the deploy's restart.

What it never does: read the database, accept an answer, take a click
identifier (`fbclid`, `ad_id`, `asid` are never a key it accepts), log a
request body, or touch a payment.
"""
import json
import logging
import os
import re

from flask import Blueprint, Response, request

import config
import database
import tracking

log = logging.getLogger(__name__)

bp = Blueprint("rsoc", __name__)

RSOC_DIR = os.path.join(config.FUNNELS_DIR, "rsoc")
PAGE_FILE = os.path.join(config.STATIC_DIR, "rsoc.html")
SLUG_RE = re.compile(r"[a-z0-9_-]{1,32}")
# What the shell carries where the slug goes. Replaced once, by a value that
# has already matched SLUG_RE, so nothing else can be written into the page.
SLUG_MARK = "__RSOC_SLUG__"

# Paths the site already answers, whatever funnels/ holds. A config named
# after one of these is not served.
RESERVED = frozenset((
    "loans", "go", "health", "admin", "api", "static", "about", "terms",
    "privacy", "refund", "persona", "favicon.ico", "robots.txt"))

# The vocabulary /api/loans/event stores, so the dashboard counts an RSOC quiz
# the way it counts /loans: `funnel_start` is the first tap on step 1;
# `swipe` is a completed step, its 1-based number in the integer `step`
# column and nothing in `extra`; `result_view` is the result shown;
# `offer_tap` is a tap on an article row, carrying the article's key.
# Nothing else, and no answer anywhere in it.
EVENTS = frozenset(("funnel_start", "swipe", "result_view", "offer_tap"))
ATTRIBUTION = tuple(tracking.ATTRIBUTION_FIELDS)
EVENT_KEYS = frozenset(("session_id", "event", "step", "extra") + ATTRIBUTION)
TOKEN_RE = re.compile(r"[a-z0-9_-]{1,40}")

# /api/loans/event has no limit of its own and lives under the app-wide
# wall, which is sized for a photograph. An event is a few hundred bytes, so
# this route says so: anything over 4 KB is refused before it is parsed.
MAX_BODY = 4096


def load(slug):
    """The parsed config for `slug`, or None when there is no such quiz."""
    if not isinstance(slug, str) or not SLUG_RE.fullmatch(slug):
        return None
    path = os.path.join(RSOC_DIR, slug + ".json")
    try:
        with open(path, encoding="utf-8") as fh:
            cfg = json.load(fh)
    except (OSError, ValueError):
        return None
    if not isinstance(cfg, dict) or cfg.get("slug") != slug:
        return None
    return cfg


def configured_slugs():
    """Every slug with a config on disk that this module may serve."""
    try:
        names = sorted(os.listdir(RSOC_DIR))
    except OSError:
        return []
    out = []
    for name in names:
        if not name.endswith(".json"):
            continue
        slug = name[:-5]
        if not SLUG_RE.fullmatch(slug):
            continue
        if slug in RESERVED or config.funnel_exists(slug):
            log.warning("rsoc config %s names a path the site already "
                        "serves; it is not routed", slug)
            continue
        out.append(slug)
    return out


def _page(slug):
    if load(slug) is None:
        return "", 404
    with open(PAGE_FILE, encoding="utf-8") as fh:
        html = fh.read()
    resp = Response(html.replace(SLUG_MARK, slug, 1),
                    mimetype="text/html")
    resp.headers["Cache-Control"] = (
        "public, max-age=%d" % config.FUNNEL_HTML_MAX_AGE)
    return resp


for _slug in configured_slugs():
    bp.add_url_rule("/" + _slug, endpoint="page_" + _slug.replace("-", "_"),
                    view_func=(lambda s=_slug: _page(s)), methods=["GET"])


# --- the event route ---------------------------------------------------------

def _body():
    """The JSON object in the request, or None when it is not one this route
    takes: too long, not an object, or carrying a key outside EVENT_KEYS."""
    if (request.content_length or 0) > MAX_BODY:
        return None
    raw = request.get_data(cache=False)
    if len(raw) > MAX_BODY:
        return None
    try:
        body = json.loads(raw.decode("utf-8"))
    except (UnicodeDecodeError, ValueError):
        return None
    if not isinstance(body, dict) or not set(body) <= EVENT_KEYS:
        return None
    return body


def _session(body):
    value = body.get("session_id")
    if isinstance(value, str) and tracking.UUID_RE.fullmatch(value):
        return value.lower()
    return None


def _attribution(body):
    return tuple(
        tracking._clean_optional(body.get(name), max_len)
        for name, max_len in tracking.ATTRIBUTION_FIELDS.items())


@bp.post("/api/rsoc/<slug>/event")
def event(slug):
    cfg = load(slug)
    if cfg is None:
        return "", 400
    body = _body()
    if body is None:
        return "", 400
    session_id = _session(body)
    if session_id is None:
        return "", 400

    name = body.get("event")
    if not isinstance(name, str) or name not in EVENTS:
        return "", 400

    steps = [s.get("id") for s in cfg.get("steps") or []
             if isinstance(s, dict)]
    articles = cfg.get("articles") or {}
    step = body.get("step")
    extra = body.get("extra")
    extra_json = None

    if name == "swipe":
        # As loans.py writes it: a number in the column, nothing in extra.
        # The quiz's own step count is the ceiling.
        if type(step) is not int or not 1 <= step <= len(steps):
            return "", 400
        if extra is not None:
            return "", 400
    elif step is not None:
        return "", 400
    elif name == "offer_tap":
        if not isinstance(extra, dict) or set(extra) != {"slot"}:
            return "", 400
        slot = extra["slot"]
        if (not isinstance(slot, str) or not TOKEN_RE.fullmatch(slot)
                or slot not in articles):
            return "", 400
        extra_json = json.dumps({"slot": slot}, separators=(",", ":"))
    elif extra is not None:
        return "", 400

    try:
        database.execute(
            tracking.INSERT_SQL,
            (slug, session_id, name, step) + _attribution(body)
            + (extra_json,))
    except Exception:
        # No payload: the traceback and this sentence are the whole line.
        log.exception("rsoc event write failed")
        return "", 500
    return "", 204
