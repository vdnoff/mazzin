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

# --- App ------------------------------------------------------------------
BASE_URL = os.getenv("BASE_URL", "https://mazzin.com")

FUNNELS_DIR = os.path.join(BASE_DIR, "funnels")
STATIC_DIR = os.path.join(BASE_DIR, "static")

SLUG_RE = re.compile(r"^[a-z0-9_-]{1,32}$")

# Cache-Control for the /<slug> HTML shell. Short for now; raised later.
FUNNEL_HTML_MAX_AGE = 300


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
