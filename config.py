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

# --- Stripe (unused in Phase 1a, wired in Phase 1b) -----------------------
STRIPE_SECRET_KEY = os.getenv("STRIPE_SECRET_KEY", "")
STRIPE_WEBHOOK_SECRET = os.getenv("STRIPE_WEBHOOK_SECRET", "")
STRIPE_PUBLISHABLE_KEY = os.getenv("STRIPE_PUBLISHABLE_KEY", "")

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

# --- Email delivery -------------------------------------------------------
# An empty key is a kill switch: no PDF is built and no email is sent, and
# every other part of the purchase still works.
RESEND_API_KEY = os.getenv("RESEND_API_KEY", "")
RESEND_TIMEOUT_S = float(os.getenv("RESEND_TIMEOUT_S", "15"))
EMAIL_FROM = os.getenv("EMAIL_FROM", "Mazzin <reports@mazzin.com>")

# --- App ------------------------------------------------------------------
BASE_URL = os.getenv("BASE_URL", "https://mazzin.com")

FUNNELS_DIR = os.path.join(BASE_DIR, "funnels")
STATIC_DIR = os.path.join(BASE_DIR, "static")

SLUG_RE = re.compile(r"^[a-z0-9_-]{1,32}$")

# Cache-Control for the /<slug> HTML shell. Short for now; raised later.
FUNNEL_HTML_MAX_AGE = 300

# Facade and legal pages change rarely.
PAGE_HTML_MAX_AGE = 3600


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
