"""Configuration + funnel config loading.

Owns: environment variables, paths, funnel JSON reads.
Nothing here talks to the database or to Stripe.
"""

import json
import os
import re

from dotenv import load_dotenv

BASE_DIR = os.path.dirname(os.path.abspath(__file__))

load_dotenv(os.path.join(BASE_DIR, ".env"))

# --- Database -------------------------------------------------------------
DB_HOST = os.getenv("DB_HOST", "")
DB_USER = os.getenv("DB_USER", "")
DB_PASSWORD = os.getenv("DB_PASSWORD", "")
DB_NAME = os.getenv("DB_NAME", "")

# --- Stripe ---------------------------------------------------------------
STRIPE_SECRET_KEY = os.getenv("STRIPE_SECRET_KEY", "")
STRIPE_WEBHOOK_SECRET = os.getenv("STRIPE_WEBHOOK_SECRET", "")
STRIPE_PUBLISHABLE_KEY = os.getenv("STRIPE_PUBLISHABLE_KEY", "")

# A second key set, for funnels marked `"stripe_mode": "test"` in their config.
# The point is to be able to walk a whole funnel — quiz, checkout, webhook,
# report, email — with a 4242 card, on the live site, without a real charge and
# without the money paths diverging from the ones customers use.
#
# Entirely optional. Absent, the feature is simply unavailable: a funnel asking
# for test mode is refused at checkout with a log line saying why, and every
# live funnel behaves exactly as it did. Nothing here is ever fatal at import,
# because a server that will not boot is a worse outcome than a funnel that
# will not sell.
STRIPE_TEST_SECRET_KEY = os.getenv("STRIPE_TEST_SECRET_KEY", "")
STRIPE_TEST_WEBHOOK_SECRET = os.getenv("STRIPE_TEST_WEBHOOK_SECRET", "")
# Read for symmetry and unused, exactly like its live counterpart: checkout is
# a redirect to Stripe-hosted Checkout, so no publishable key ever reaches the
# browser. Here so that a mode is one complete key set rather than two.
STRIPE_TEST_PUBLISHABLE_KEY = os.getenv("STRIPE_TEST_PUBLISHABLE_KEY", "")

# --- Report generation ----------------------------------------------------
# An empty key is a kill switch, not an error: reports fall back to the stub
# templates and the purchase still delivers.
ANTHROPIC_API_KEY = os.getenv("ANTHROPIC_API_KEY", "")
ANTHROPIC_MODEL = os.getenv("ANTHROPIC_MODEL", "claude-sonnet-4-6")

# Per-call HTTP timeout, and the wall-clock budget for the whole of report
# generation. The budget is the smaller of the two on purpose: the webhook has
# to answer Stripe long before a single slow call would give up, so generation
# is abandoned at the budget and the stub is stored instead.
ANTHROPIC_TIMEOUT_S = float(os.getenv("ANTHROPIC_TIMEOUT_S", "30"))
REPORT_BUDGET_S = float(os.getenv("REPORT_BUDGET_S", "20"))

# How many model calls may be in flight at once. Four was timing three sections
# out at a time in production: the host's egress proxy does not sustain that
# many long-lived HTTPS connections in parallel, and the failure mode is a
# timeout rather than a rejection, so it costs the whole budget before it shows.
# Two is what it carries reliably.
LLM_MAX_CONCURRENCY = int(os.getenv("LLM_MAX_CONCURRENCY", "2"))

# A call still running when the budget expires is no longer waited on, but it
# is no longer thrown away either: it finishes in the background and upgrades
# the stored report. This is the ceiling on that background wait.
REPORT_UPGRADE_MAX_S = float(os.getenv("REPORT_UPGRADE_MAX_S", "60"))

# --- Visualizer (photo -> restyled render) --------------------------------
# The same kill-switch shape as every other integration here: an empty key
# means the feature reports itself unavailable and nothing else changes. A
# funnel without a `visualizer` block never reaches any of this.
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY", "")
OPENAI_API_BASE = os.getenv("OPENAI_API_BASE", "https://api.openai.com/v1")
OPENAI_IMAGE_MODEL = os.getenv("OPENAI_IMAGE_MODEL", "gpt-image-1")

# An image edit is the one thing here that costs real money per use, so both
# levers are environment variables rather than constants. At 1024x1024 the
# quality tiers run roughly $0.01 / $0.04 / $0.17 per image; `medium` twice is
# under a dollar on a hundred purchases and is the balance this ships with.
OPENAI_IMAGE_SIZE = os.getenv("OPENAI_IMAGE_SIZE", "1024x1024")
OPENAI_IMAGE_QUALITY = os.getenv("OPENAI_IMAGE_QUALITY", "medium")

# Image edits are slow — a minute is normal, two is not unusual. This runs on
# a background thread, so nothing is waiting on it but the poller.
OPENAI_TIMEOUT_S = float(os.getenv("OPENAI_TIMEOUT_S", "180"))

# Uploaded photographs and their renders. Deliberately not under static/: these
# are pictures of somebody's home, and everything in static/ is world-readable
# and CDN-cached. They are served by a route that checks the purchase token
# instead. Outside the repo tree by default so a deploy never walks over them.
VISUALIZER_DIR = os.getenv(
    "VISUALIZER_DIR", os.path.join(BASE_DIR, "data", "visualizer"))

# Eight megabytes was set from what a phone camera sent when this was written,
# and a 48-megapixel Pro sensor writes past it routinely — which is how a
# ceiling meant for crafted files ended up refusing ordinary photographs.
#
# The browser downscales before it uploads, so almost nothing should ever come
# near this: what arrives is a 2048px JPEG of a few hundred kilobytes. This is
# the ceiling for the raw fallback — an in-app WebView with no working canvas,
# or a file it could not decode — where the original is sent exactly as the
# camera wrote it. Twenty-five is chosen for that path rather than for the
# common one, because the common one does not use it.
VISUALIZER_MAX_BYTES = int(os.getenv("VISUALIZER_MAX_BYTES",
                                     str(25 * 1024 * 1024)))

# The longest side we keep. The model reads a 1024px square; 1536 leaves room
# for the before/after to stay crisp on a 3x phone screen without storing a
# 12-megapixel original of someone's kitchen indefinitely.
VISUALIZER_MAX_EDGE = int(os.getenv("VISUALIZER_MAX_EDGE", "1536"))
VISUALIZER_JPEG_QUALITY = int(os.getenv("VISUALIZER_JPEG_QUALITY", "88"))

# A decode ceiling, still well under Pillow's own bomb guard.
#
# "No phone photograph is 40 megapixels" was true when it was written and is
# not any more: a 48MP Pro sensor produces 8064x6048, which is 48.8 million —
# so the guard against crafted files was rejecting the exact device this
# feature was being used on. Eighty admits a 48 and a 64 with room over.
#
# The cost of the ceiling is memory: Pillow holds the decoded image as three
# bytes a pixel, so eighty megapixels is about 240MB in a worker for as long as
# the re-encode takes. That is survivable and it is why this is not simply set
# to Pillow's own limit. The browser downscales before uploading, so almost
# nothing reaches this at all — it is the fallback path's wall.
VISUALIZER_MAX_PIXELS = int(os.getenv("VISUALIZER_MAX_PIXELS", str(80_000_000)))

# Attempts, not generations. A generation is a credit the buyer paid for and
# is only spent when an image actually comes back; an attempt is any claim on
# the worker, and this is the ceiling that stops a purchase whose generation
# fails forever from retrying forever.
VISUALIZER_MAX_ATTEMPTS = int(os.getenv("VISUALIZER_MAX_ATTEMPTS", "6"))

# A photograph uploaded before the purchase that would give it a home. Most
# never get one — the upload moves ahead of the payment on purpose, so the
# common case is a picture of a kitchen belonging to somebody who did not buy.
# Two days is long enough to come back to the tab tomorrow evening and short
# enough that a stranger's home is not on a disk next week.
VISUALIZER_PENDING_MAX_AGE_S = float(
    os.getenv("VISUALIZER_PENDING_MAX_AGE_S", str(48 * 3600)))

# The sweep walks every pending directory, so it runs on a timer rather than on
# every upload. Cron may also call scripts/cleanup_pending.py; both are safe and
# neither is required for the other to work.
VISUALIZER_PURGE_EVERY_S = float(
    os.getenv("VISUALIZER_PURGE_EVERY_S", str(600)))

# How long a row may sit in `generating` before another attempt may claim it.
# Nothing releases the claim if a worker is killed mid-call, so the lock has to
# be able to expire on its own.
VISUALIZER_STALE_S = float(os.getenv("VISUALIZER_STALE_S", "300"))

# --- Email delivery -------------------------------------------------------
# An empty key is a kill switch: no PDF is built and no email is sent, and
# every other part of the purchase still works.
RESEND_API_KEY = os.getenv("RESEND_API_KEY", "")
RESEND_TIMEOUT_S = float(os.getenv("RESEND_TIMEOUT_S", "15"))
EMAIL_FROM = os.getenv("EMAIL_FROM", "Mazzin <reports@mazzin.com>")

# --- Meta advertising measurement -----------------------------------------
# Two switches, and either being empty turns its own half off without
# touching the other. No pixel id: the browser loads nothing from Meta and
# /api/pixel-config answers null. No token: the server sends no Purchase.
# A funnel with neither behaves exactly as it did before any of this existed.
#
# The id is deliberately not baked into the static HTML. Those files are
# cached by the CDN and shared across every funnel, so a pixel compiled into
# them would follow a second brand onto a second domain.
META_PIXEL_ID = os.getenv("META_PIXEL_ID", "")
META_CAPI_TOKEN = os.getenv("META_CAPI_TOKEN", "")
META_API_VERSION = os.getenv("META_API_VERSION", "v21.0")
META_TIMEOUT_S = float(os.getenv("META_TIMEOUT_S", "10"))
# Meta's own test hook: set it and events land in Events Manager's test tab
# instead of in reporting. Absent in production, which is the point.
META_TEST_EVENT_CODE = os.getenv("META_TEST_EVENT_CODE", "")

# --- App ------------------------------------------------------------------
BASE_URL = os.getenv("BASE_URL", "https://mazzin.com")

FUNNELS_DIR = os.path.join(BASE_DIR, "funnels")
STATIC_DIR = os.path.join(BASE_DIR, "static")

SLUG_RE = re.compile(r"^[a-z0-9_-]{1,32}$")

# Cache-Control for the /<slug> HTML shell. Short for now; raised later.
FUNNEL_HTML_MAX_AGE = 300

# Facade and legal pages change rarely.
PAGE_HTML_MAX_AGE = 3600

# The pixel id changes about never, and the endpoint is on the critical
# path of every page load. Cache it hard.
PIXEL_CONFIG_MAX_AGE = int(os.getenv("PIXEL_CONFIG_MAX_AGE", "86400"))


def valid_slug(slug):
    """True if `slug` is safe to use as a filename component."""
    return isinstance(slug, str) and SLUG_RE.match(slug) is not None


def funnel_exists(slug):
    """True if funnels/<slug>.json exists. Validates the slug first."""
    if not valid_slug(slug):
        return False
    return os.path.isfile(os.path.join(FUNNELS_DIR, slug + ".json"))


def load_funnel(slug):
    """Return the parsed funnel config for `slug`.

    Raises KeyError if the slug is invalid or the config file is missing.
    """
    if not valid_slug(slug):
        raise KeyError(slug)
    path = os.path.join(FUNNELS_DIR, slug + ".json")
    if not os.path.isfile(path):
        raise KeyError(slug)
    with open(path, "r", encoding="utf-8") as fh:
        return json.load(fh)
