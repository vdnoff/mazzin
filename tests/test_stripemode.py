#!/usr/bin/env python3
"""Which Stripe account a funnel transacts on, once an override can say.

A funnel's mode used to be a line in a config file. It is now that line unless
a row in `funnel_mode_overrides` disagrees, and the whole of this suite is
about the two rules that make that safe to operate:

  **One answer.** `payments.effective_mode()` is the only thing that decides,
  and every path that starts or finishes a payment asks it. A funnel that were
  live at checkout and test at the webhook would take a real card and then fail
  to record the sale — so the suite greps for a second path as well as testing
  the first.

  **No memory past the request.** A toggle has to be true for the very next
  checkout. An owner who flips a funnel to test and reaches for a 4242 card
  must not be charged for real because a worker was still holding the old
  answer. So the memo is per request, and this proves it both ways: two calls
  inside one request hit the database once, and two requests either side of a
  toggle disagree.

Also here: that the table not existing is survivable (it degrades to the
config, which is exactly today's behaviour), that the admin page's red banner
fires on the pairing it is meant to, and that the four funnels in production
resolve exactly as they did before any of this when nobody has toggled
anything.

No MySQL, no Stripe, no network. Every write is intercepted, `Session.create`
is recorded rather than called, and the webhook signatures are real ones made
here.

    python3 tests/test_stripemode.py
"""
import hashlib
import hmac
import json
import os
import re
import sys
import time

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, REPO)

import admin           # noqa: E402
import config          # noqa: E402
import database        # noqa: E402
import payments        # noqa: E402
import stripe          # noqa: E402
from app import app    # noqa: E402

LIVE_KEY = "sk_live_notreal"
TEST_KEY = "sk_test_notreal"
LIVE_PUB = "pk_live_notreal"
TEST_PUB = "pk_test_notreal"
LIVE_WH = "whsec_live_notreal"
TEST_WH = "whsec_test_notreal"
SESSION = "11111111-2222-4333-8444-555555555555"

fails = []
checks = [0]


def check(label, ok, detail=""):
    checks[0] += 1
    if not ok:
        fails.append("%s %s" % (label, detail))
    print("  %-64s %s%s" % (label, "ok" if ok else "FAIL",
                            ("  " + str(detail)) if not ok else ""))


def eq(label, got, want):
    check(label, got == want, "got %r want %r" % (got, want))


# --- the table, and its absence ---------------------------------------------

class Table:
    """`funnel_mode_overrides`, as a dict, with a switch to make it vanish.

    `present = False` raises the way PyMySQL raises for a table that is not
    there, which is the state every server is in between a deploy and somebody
    running the migration. That is not a hypothetical: the migration is applied
    by hand.
    """

    def __init__(self):
        self.rows = {}
        self.present = True
        self.reads = 0
        self.writes = []

    def _guard(self):
        if not self.present:
            raise RuntimeError("Table 'mazzin.funnel_mode_overrides' "
                               "doesn't exist")

    def query_one(self, sql, params=None):
        if "funnel_mode_overrides" not in sql:
            return None
        self._guard()
        self.reads += 1
        return self.rows.get(params[0])

    def query_all(self, sql, params=None):
        if "funnel_mode_overrides" in sql:
            self._guard()
            self.reads += 1
            return list(self.rows.values())
        if "FROM events" in sql:
            return traffic_rows(params)
        return []

    def execute(self, sql, params=None):
        self.writes.append(sql)
        if "funnel_mode_overrides" not in sql:
            return 1
        self._guard()
        if sql.strip().upper().startswith("INSERT"):
            self.rows[params[0]] = {"funnel": params[0], "mode": params[1],
                                    "changed_at": None,
                                    "changed_by": params[2]}
        else:
            self.rows.pop(params[0], None)
        return 1

    def set(self, funnel, mode):
        self.rows[funnel] = {"funnel": funnel, "mode": mode,
                             "changed_at": None, "changed_by": "test"}

    def clear(self):
        self.rows.clear()


# How many sessions started each funnel in the banner's window. Read by the
# stubbed events query, set per test.
STARTS = {}


def traffic_rows(params):
    slug = params[0] if params else None
    count = STARTS.get(slug, 0)
    return [{"event": "funnel_start", "sessions": count}] if count else []


table = Table()
database.query_one = table.query_one
database.query_all = table.query_all
database.execute = table.execute
database.execute_rowcount = lambda *a, **k: 1

for _name, _value in (("STRIPE_SECRET_KEY", LIVE_KEY),
                      ("STRIPE_TEST_SECRET_KEY", TEST_KEY),
                      ("STRIPE_PUBLISHABLE_KEY", LIVE_PUB),
                      ("STRIPE_TEST_PUBLISHABLE_KEY", TEST_PUB),
                      ("STRIPE_WEBHOOK_SECRET", LIVE_WH),
                      ("STRIPE_TEST_WEBHOOK_SECRET", TEST_WH)):
    setattr(config, _name, _value)


def resolved(slug):
    """`effective_mode` inside a request, which is where it really runs."""
    with app.test_request_context("/"):
        return payments.effective_mode(slug)


# --- 1. precedence ----------------------------------------------------------

print("\n--- what the config says, with nobody overriding ---")
table.clear()
# The four funnels in production, resolving exactly as they did before this
# feature existed. persona is the one whose config asks for test mode; the
# other three are live by saying nothing or by saying so.
for slug, expected in (("kitchen", "live"), ("zodiac", "live"),
                       ("zodiac-ro", "live"), ("persona", "test")):
    eq("%s resolves to its config's mode" % slug, resolved(slug), expected)
    eq("...and its config alone says the same",
       payments._stripe_mode(config.load_funnel(slug)), expected)

print("\n--- an override beats the config ---")
table.set("kitchen", "test")
eq("a test override flips a live funnel", resolved("kitchen"), "test")
table.set("persona", "live")
eq("a live override flips a test funnel", resolved("persona"), "live")
eq("a funnel with no row is untouched by another's", resolved("zodiac"),
   "live")
table.clear()
eq("clearing the row hands it back to the config",
   resolved("kitchen"), "live")
eq("...and the other one too", resolved("persona"), "test")

print("\n--- a junk row is not an override ---")
table.rows["kitchen"] = {"funnel": "kitchen", "mode": "sandbox",
                         "changed_at": None, "changed_by": "test"}
eq("a mode this code does not know is ignored, not obeyed",
   resolved("kitchen"), "live")
table.clear()

print("\n--- without the table at all ---")
table.present = False
payments._override_unavailable[0] = False
for slug, expected in (("kitchen", "live"), ("persona", "test")):
    eq("%s still resolves off its config" % slug, resolved(slug), expected)
check("and the process said so once", payments._override_unavailable[0])
eq("nothing raised out of the resolution path",
   resolved("zodiac"), "live")
table.present = True

print("\n--- one path, not two ---")
source = open(os.path.join(REPO, "payments.py"), encoding="utf-8").read()
callers = [line.strip() for line in source.splitlines()
           if "_stripe_mode(" in line and not line.strip().startswith("def ")]
eq("_stripe_mode is called from exactly one place", len(callers), 1)
check("...and that place is effective_mode",
      callers[0] == "return _stripe_mode(cfg)", callers[0])
check("nothing else in the tree reads stripe_mode to decide a mode",
      not re.search(r'\.get\("stripe_mode"\)',
                    source[source.index("def effective_mode"):]))
check("the token scheme is gone from the tree",
      not any("ADMIN_TOKEN" in open(os.path.join(REPO, name),
                                    encoding="utf-8").read()
              for name in ("config.py", "admin.py", "app.py", "payments.py")))


# --- 2. the memo lives and dies with the request ----------------------------

print("\n--- caching ---")
table.clear()
table.set("kitchen", "test")
table.reads = 0
with app.test_request_context("/"):
    first = payments.effective_mode("kitchen")
    second = payments.effective_mode("kitchen")
eq("two calls in one request agree", (first, second), ("test", "test"))
eq("and cost one read", table.reads, 1)

table.reads = 0
resolved("kitchen")
resolved("kitchen")
eq("two separate requests each read again", table.reads, 2)

# The one that matters: a write inside a request must be visible to the rest
# of that request, or the audit line reports a transition that did not happen.
with app.test_request_context("/"):
    before = payments.effective_mode("kitchen")
    payments.clear_override("kitchen")
    after = payments.effective_mode("kitchen")
eq("a write is visible to the request that made it",
   (before, after), ("test", "live"))

print("\n--- a toggle is true for the very next checkout ---")


class Recorder:
    def __init__(self):
        self.calls = []

    def __call__(self, **kwargs):
        self.calls.append(kwargs)

        class Session:
            url = "https://checkout.stripe.test/c/pay/cs_test_1"
            id = "cs_test_1"
        return Session()


def body_for(slug):
    cfg = config.load_funnel(slug)
    return {
        "funnel": slug,
        "session_id": SESSION,
        "result_style": cfg["styles"][0]["id"],
        "tag_scores": {"warm": 8, "wood": 6},
        "choices": [s["pairs"][0]["images"][0]["id"]
                    for s in cfg["swipe"]["steps"]],
    }


def checkout(slug):
    """Drive the real /api/checkout and hand back the kwargs Stripe got."""
    rec = Recorder()
    real = stripe.checkout.Session.create
    stripe.checkout.Session.create = rec
    try:
        with app.test_client() as client:
            response = client.post("/api/checkout", json=body_for(slug))
    finally:
        stripe.checkout.Session.create = real
    return response, (rec.calls[0] if rec.calls else None)


table.clear()
response, call = checkout("kitchen")
eq("a live funnel checks out", response.status_code, 200)
eq("on the live key", (call or {}).get("api_key"), LIVE_KEY)

table.set("kitchen", "test")
response, call = checkout("kitchen")
eq("the very next checkout after the toggle", response.status_code, 200)
eq("is on the test key", (call or {}).get("api_key"), TEST_KEY)

table.set("kitchen", "live")
response, call = checkout("kitchen")
eq("and back again with no restart in between",
   (call or {}).get("api_key"), LIVE_KEY)

table.set("persona", "live")
response, call = checkout("persona")
eq("an override can put a test-config funnel onto the live key",
   (call or {}).get("api_key"), LIVE_KEY)
table.clear()

print("\n--- a mode with no key refuses rather than falls back ---")
held = config.STRIPE_TEST_SECRET_KEY
config.STRIPE_TEST_SECRET_KEY = ""
table.set("kitchen", "test")
response, call = checkout("kitchen")
eq("checkout is refused", response.status_code, 502)
eq("and nothing was sent to Stripe", call, None)
config.STRIPE_TEST_SECRET_KEY = held
table.clear()


# --- 3. the webhook ---------------------------------------------------------

print("\n--- the webhook follows the effective mode ---")


def signed(payload, secret):
    stamp = int(time.time())
    mac = hmac.new(secret.encode(),
                   ("%d.%s" % (stamp, payload)).encode(),
                   hashlib.sha256).hexdigest()
    return {"Stripe-Signature": "t=%d,v1=%s" % (stamp, mac)}


class ChargeSpy:
    """Stands in for stripe.Charge.retrieve and keeps the key it was given."""

    def __init__(self):
        self.keys = []

    def __call__(self, charge_id, api_key=None, **kwargs):
        self.keys.append(api_key)

        class Charge:
            @staticmethod
            def to_dict():
                return {"billing_details": {"email": None, "address": {}}}
        return Charge()


def webhook_intent(slug, secret):
    """A payment_intent.succeeded whose charge is a bare id, so the handler
    has to go and fetch it — which is the call that names a key."""
    event = {
        "id": "evt_1",
        "type": "payment_intent.succeeded",
        "livemode": False,
        "data": {"object": {
            "id": "pi_1",
            "amount_received": 300,
            "currency": "usd",
            "latest_charge": "ch_1",
            "metadata": {"funnel": slug, "session_id": SESSION,
                         "result_style": "modern_rustic"},
        }},
    }
    payload = json.dumps(event)
    spy = ChargeSpy()
    real_retrieve = stripe.Charge.retrieve
    real_execute = database.execute
    stripe.Charge.retrieve = spy
    # The purchase insert is not what this is about; let it succeed silently.
    database.execute = lambda sql, params=None: (
        table.execute(sql, params) if "funnel_mode_overrides" in sql else 1)
    try:
        with app.test_client() as client:
            response = client.post("/api/stripe/webhook", data=payload,
                                   headers=signed(payload, secret),
                                   content_type="application/json")
    finally:
        stripe.Charge.retrieve = real_retrieve
        database.execute = real_execute
    return response, spy


table.clear()
response, spy = webhook_intent("kitchen", LIVE_WH)
eq("a live funnel's webhook is accepted", response.status_code, 200)
eq("and the charge is fetched on the live key", spy.keys, [LIVE_KEY])

table.set("kitchen", "test")
response, spy = webhook_intent("kitchen", TEST_WH)
eq("an overridden funnel's webhook is accepted too",
   response.status_code, 200)
eq("and the charge is fetched on the test key", spy.keys, [TEST_KEY])

# Both signing secrets stay in play regardless, and they have to: which funnel
# an event belongs to is inside the payload, and the payload cannot be read
# before the signature is verified. So an event signed live for a funnel that
# is now in test is still accepted — it is a real payment made before the
# toggle — and the charge lookup follows the funnel, not the signature.
response, spy = webhook_intent("kitchen", LIVE_WH)
eq("an event signed with the other secret is still accepted",
   response.status_code, 200)
eq("and the lookup still follows the funnel's mode", spy.keys, [TEST_KEY])
table.clear()


# --- 4. the admin page's rails ----------------------------------------------

print("\n--- red banner: test mode plus live traffic ---")
import datetime            # noqa: E402

now = datetime.datetime.now()
table.clear()
STARTS.clear()

STARTS["kitchen"] = 143
rows = {row["slug"]: row for row in admin._mode_rows(now)}
eq("a live funnel with traffic is not an alarm",
   rows["kitchen"]["danger"], False)

table.set("kitchen", "test")
rows = {row["slug"]: row for row in admin._mode_rows(now)}
check("a funnel in test mode with traffic is", rows["kitchen"]["danger"],
      rows["kitchen"])
eq("and the count is carried so the banner can say it",
   rows["kitchen"]["recent_starts"], 143)
eq("the row still shows what the config says underneath",
   rows["kitchen"]["config_mode"], "live")
eq("and marks itself overridden", rows["kitchen"]["overridden"], True)

STARTS["kitchen"] = 0
rows = {row["slug"]: row for row in admin._mode_rows(now)}
eq("test mode with nobody arriving is not an alarm",
   rows["kitchen"]["danger"], False)

# persona's config asks for test mode, so it needs no override to be dangerous
# — which is the point of measuring the effective mode rather than the row.
table.clear()
STARTS["persona"] = 12
rows = {row["slug"]: row for row in admin._mode_rows(now)}
check("a funnel whose *config* is test raises it too, with no row at all",
      rows["persona"]["danger"] and not rows["persona"]["overridden"],
      rows["persona"])
STARTS.clear()

print("\n--- the live-key trio ---")
eq("with every key set, nothing is missing", admin._missing_keys("live"), [])
held = config.STRIPE_WEBHOOK_SECRET
config.STRIPE_WEBHOOK_SECRET = ""
eq("a missing webhook secret is caught", admin._missing_keys("live"),
   ["STRIPE_WEBHOOK_SECRET"])
config.STRIPE_WEBHOOK_SECRET = held
held = config.STRIPE_PUBLISHABLE_KEY
config.STRIPE_PUBLISHABLE_KEY = ""
eq("so is a missing publishable key", admin._missing_keys("live"),
   ["STRIPE_PUBLISHABLE_KEY"])
config.STRIPE_PUBLISHABLE_KEY = held
eq("and the test trio is checked the same way",
   admin._missing_keys("test"), [])
held = config.STRIPE_TEST_SECRET_KEY
config.STRIPE_TEST_SECRET_KEY = ""
eq("a half-configured test mode is refusable too",
   admin._missing_keys("test"), ["STRIPE_TEST_SECRET_KEY"])
config.STRIPE_TEST_SECRET_KEY = held


print()
print("%d checks, %d failed" % (checks[0], len(fails)))
for line in fails:
    print("  FAIL %s" % line)
sys.exit(1 if fails else 0)
