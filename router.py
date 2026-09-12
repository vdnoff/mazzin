"""GET /go — the one link an ad carries, resolved to whichever funnel exists.

Owns: the vertical + language -> slug mapping, the two fallback tiers, and
the one write that records a language somebody asked for and did not get.
Nothing here renders a page, calls a model or reads a purchase: it is a
redirect, and it answers in the time a redirect should.

    /go?v=blinds&l=hu&subid=abc&utm_source=meta

  1. `blinds-hu` exists           -> 301 /blinds-hu?subid=abc&utm_source=meta
  2. only the master `blinds` does -> 301 /blinds?...     and the miss is queued
  3. neither does                  -> 301 /kitchen?...    and the miss is queued

`v` and `l` are dropped from the query string and everything else survives
it, because `subid` and the `utm_*` fields are what engine.js reads off the
URL and tracking.py stores — a router that lost them would count every
routed visit as direct.

The queue is the `gen_queue` table (schema_migrations.sql): one row per
(vertical, language), hits counted up on every miss, so the batch that
writes new languages reads it to see which ones are actually being asked
for. It is written inside a try/except and a failing write never touches the
redirect — a queue is a nice-to-have and a redirect is the click. Nothing
personal is written or logged: two short lowercase tokens and a count.

A `-test` twin is never a destination. It is a public URL one guessable
suffix away from a live funnel and it has its own gate in app.py; sending an
ad click at it would be the router opening that door from the outside.
"""
import logging
import re
from urllib.parse import parse_qsl, urlencode

from flask import Blueprint, redirect, request

import config
import database

log = logging.getLogger(__name__)

bp = Blueprint("router", __name__)

PARAM_RE = re.compile(r"^[a-z0-9_-]{1,24}$")
DEFAULT_LANG = "en"
DEFAULT_RECEIVER = "kitchen"
STATUS = 301

UPSERT_MISS_SQL = (
    "INSERT INTO gen_queue (vertical, lang, first_seen, last_seen, hits) "
    "VALUES (%s, %s, NOW(), NOW(), 1) "
    "ON DUPLICATE KEY UPDATE hits = hits + 1, last_seen = NOW()"
)


def candidate_slug(vertical, lang):
    """The slug a vertical + language pair names. English is the master."""
    return vertical if lang == DEFAULT_LANG else "%s-%s" % (vertical, lang)


def _routable(slug):
    """A funnel that exists AND is one an ad may land on."""
    return (config.valid_slug(slug) and not config.is_test_slug(slug)
            and config.funnel_exists(slug))


def resolve(vertical, lang):
    """(slug, missed): where to send the click, and whether to queue it."""
    wanted = candidate_slug(vertical, lang)
    if _routable(wanted):
        return wanted, False
    if _routable(vertical):
        return vertical, True
    return DEFAULT_RECEIVER, True


def carried_query(query_string):
    """The original query string minus `v` and `l`, order kept."""
    pairs = [(k, v) for k, v in
             parse_qsl(query_string, keep_blank_values=True)
             if k not in ("v", "l")]
    return urlencode(pairs)


def record_miss(vertical, lang):
    """Count the ask. Never raises; never breaks the redirect."""
    try:
        database.execute(UPSERT_MISS_SQL, (vertical, lang))
    except Exception as exc:
        # The type only. Nothing about the request goes in the log.
        log.warning("gen_queue write failed for %s/%s: %s", vertical, lang,
                    type(exc).__name__)


@bp.get("/go")
def go():
    vertical = (request.args.get("v") or "").strip().lower()
    lang = (request.args.get("l") or DEFAULT_LANG).strip().lower()
    if not PARAM_RE.match(vertical) or not PARAM_RE.match(lang):
        return "", 400

    slug, missed = resolve(vertical, lang)
    if missed:
        record_miss(vertical, lang)

    query = carried_query(request.query_string.decode("utf-8", "replace"))
    location = "/" + slug + ("?" + query if query else "")
    resp = redirect(location, code=STATUS)
    # A 301 is what the spec asks for and what a browser caches forever; the
    # fallback tiers are exactly the answers that change once a language
    # goes live, so the edge and the browser are told not to keep this one.
    resp.headers["Cache-Control"] = "no-store"
    return resp
