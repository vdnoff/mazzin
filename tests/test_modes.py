#!/usr/bin/env python3
"""Which Stripe account a funnel transacts on, end to end.

Drives the real Flask routes with a recorded `Session.create` and a real
signature on the webhook, so the assertions are against the payload the live
code builds and the verification the live code runs. Nothing reaches Stripe
and no database is touched — every write is intercepted.

    python3 modes.py
"""
import hashlib
import hmac
import json
import os
import sys
import time

# The repo root, derived from this file rather than hardcoded: a suite
# that only runs from one absolute path is a suite that stops running the
# first time the checkout moves.
REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

sys.path.insert(0, REPO)

import config          # noqa: E402
import database        # noqa: E402
import payments        # noqa: E402
import reports         # noqa: E402
import stripe          # noqa: E402
from app import app    # noqa: E402

LIVE_KEY = "sk_live_notreal_live_key"
TEST_KEY = "sk_test_notreal_test_key"
LIVE_WH = "whsec_live_notreal"
TEST_WH = "whsec_test_notreal"

fails = []
checks = [0]


def check(label, ok, detail=""):
    checks[0] += 1
    if not ok:
        fails.append("%s %s" % (label, detail))
    print("  %-60s %s%s" % (label, "ok" if ok else "FAIL",
                            ("  " + str(detail)) if not ok else ""))


class Recorder:
    """Stands in for stripe.checkout.Session.create and keeps the kwargs."""

    def __init__(self):
        self.calls = []

    def __call__(self, **kwargs):
        self.calls.append(kwargs)

        class Session:
            url = "https://checkout.stripe.test/c/pay/cs_test_123"
        return Session()


def body_for(slug):
    cfg = config.load_funnel(slug)
    return {
        "funnel": slug,
        "session_id": "11111111-2222-4333-8444-555555555555",
        "result_style": cfg["styles"][0]["id"],
        "tag_scores": {"warm": 8, "wood": 6},
        "choices": [s["pairs"][0]["images"][0]["id"]
                    for s in cfg["swipe"]["steps"]],
    }


def post_checkout(slug, live=LIVE_KEY, test=TEST_KEY):
    rec = Recorder()
    real = stripe.checkout.Session.create
    keys = (config.STRIPE_SECRET_KEY, config.STRIPE_TEST_SECRET_KEY)
    stripe.checkout.Session.create = rec
    config.STRIPE_SECRET_KEY, config.STRIPE_TEST_SECRET_KEY = live, test
    payments.config = config
    try:
        with app.test_client() as client:
            res = client.post("/api/checkout", json=body_for(slug))
    finally:
        stripe.checkout.Session.create = real
        config.STRIPE_SECRET_KEY, config.STRIPE_TEST_SECRET_KEY = keys
    return res, (rec.calls[0] if rec.calls else None)


# --- the webhook -----------------------------------------------------------

def signed_headers(payload, secret):
    """A real Stripe-Signature header, so verify_header does real work."""
    stamp = int(time.time())
    mac = hmac.new(secret.encode(), ("%d.%s" % (stamp, payload)).encode(),
                   hashlib.sha256).hexdigest()
    return {"Stripe-Signature": "t=%d,v1=%s" % (stamp, mac),
            "Content-Type": "application/json"}


def event_for(slug, livemode, session_id):
    cfg = config.load_funnel(slug)
    return {
        "id": "evt_%s_%d" % (slug.replace("-", "_"), int(time.time() * 1000)),
        "type": "checkout.session.completed",
        "created": int(time.time()),
        "livemode": livemode,
        "data": {"object": {
            "id": session_id,
            "amount_total": cfg["pricing"]["amount_cents"],
            "currency": cfg["pricing"]["currency"],
            "payment_intent": "pi_" + session_id[3:],
            "customer_details": {"email": "buyer@example.com",
                                 "address": {"country": "US"}},
            "metadata": {
                "funnel": slug,
                "session_id": "11111111-2222-4333-8444-555555555555",
                "result_style": cfg["styles"][0]["id"],
            },
        }},
    }


class Landed:
    """Everything the webhook would have written, caught instead."""

    def __init__(self):
        self.purchases = []
        self.capi = []
        self.reports = []
        self.next_id = 1000

    def install(self):
        self.real = (database.execute, payments.send_purchase_event,
                     reports.start_report)

        def execute(sql, params=None):
            if "INSERT INTO purchases" in sql:
                self.purchases.append(params)
                self.next_id += 1
                return self.next_id
            return 1

        def capi(*a, **kw):
            self.capi.append(a[1] if len(a) > 1 else None)
            return True

        def start(purchase_id, slug, style, *a, **kw):
            self.reports.append((purchase_id, slug, style))
            return {"version": "llm-2"}

        database.execute = execute
        payments.database.execute = execute
        payments.send_purchase_event = capi
        reports.start_report = start
        payments.reports.start_report = start

    def restore(self):
        database.execute, payments.send_purchase_event, \
            reports.start_report = self.real
        payments.database.execute = database.execute
        payments.reports.start_report = reports.start_report


def post_webhook(slug, livemode, session_id, secret, live=LIVE_WH,
                 test=TEST_WH):
    payload = json.dumps(event_for(slug, livemode, session_id))
    was = (config.STRIPE_WEBHOOK_SECRET, config.STRIPE_TEST_WEBHOOK_SECRET)
    config.STRIPE_WEBHOOK_SECRET, config.STRIPE_TEST_WEBHOOK_SECRET = live, test
    landed = Landed()
    landed.install()
    try:
        with app.test_client() as client:
            res = client.post("/api/stripe/webhook", data=payload,
                              headers=signed_headers(payload, secret))
    finally:
        landed.restore()
        config.STRIPE_WEBHOOK_SECRET, config.STRIPE_TEST_WEBHOOK_SECRET = was
    return res, landed


def main():
    print("\n--- which key each funnel transacts on ---")
    res, kw = post_checkout("kitchen")
    check("kitchen checks out", res.status_code == 200, res.status_code)
    check("  on the live key", kw.get("api_key") == LIVE_KEY,
          kw.get("api_key"))
    check("  at its own price",
          kw["line_items"][0]["price_data"]["unit_amount"] == 300,
          kw["line_items"][0]["price_data"]["unit_amount"])

    res, kw = post_checkout("kitchen-visualizer")
    check("kitchen-visualizer checks out", res.status_code == 200,
          res.status_code)
    check("  on the test key", kw.get("api_key") == TEST_KEY,
          kw.get("api_key"))
    check("  at 700 cents",
          kw["line_items"][0]["price_data"]["unit_amount"] == 700,
          kw["line_items"][0]["price_data"]["unit_amount"])
    check("  with its own product name",
          kw["line_items"][0]["price_data"]["product_data"]["name"]
          == "Your Kitchen Style Report + Visualization — "
             "see your kitchen transformed",
          kw["line_items"][0]["price_data"]["product_data"]["name"])
    check("  and its own success url",
          "/kitchen-visualizer?cs=" in kw["success_url"], kw["success_url"])
    check("the key is a request option, never a form field",
          "api_key" not in json.dumps(kw["line_items"]), kw["line_items"])

    print("\n--- a mode that is not configured is refused, not guessed ---")
    res, kw = post_checkout("kitchen-visualizer", test="")
    check("no test key means no checkout", res.status_code == 502,
          res.status_code)
    check("  and nothing was sent to Stripe", kw is None, kw)
    res, kw = post_checkout("kitchen", live="")
    check("the same holds for a missing live key", res.status_code == 502,
          res.status_code)
    res, kw = post_checkout("kitchen", test="")
    check("a live funnel does not care that test is unset",
          res.status_code == 200 and kw.get("api_key") == LIVE_KEY,
          res.status_code)

    print("\n--- the webhook takes either signature ---")
    res, landed = post_webhook("kitchen", True, "cs_live_abc", LIVE_WH)
    check("a live-signed event is accepted", res.status_code == 200,
          (res.status_code, res.get_json()))
    check("  the purchase is recorded", len(landed.purchases) == 1,
          landed.purchases)
    check("  the report pipeline runs", len(landed.reports) == 1,
          landed.reports)
    check("  and Meta is told", len(landed.capi) == 1, landed.capi)

    res, landed = post_webhook("kitchen-visualizer", False, "cs_test_abc",
                               TEST_WH)
    check("a test-signed event is accepted too", res.status_code == 200,
          (res.status_code, res.get_json()))
    check("  the purchase is recorded", len(landed.purchases) == 1,
          landed.purchases)
    check("  the session id keeps its cs_test_ marker",
          landed.purchases and landed.purchases[0][4] == "cs_test_abc",
          landed.purchases)
    check("  the report pipeline runs — that is the point of testing",
          len(landed.reports) == 1, landed.reports)
    check("  and Meta is NOT told", not landed.capi, landed.capi)

    print("\n--- and refuses anything signed with neither ---")
    res, landed = post_webhook("kitchen", True, "cs_live_x", "whsec_wrong")
    check("a bad signature is rejected", res.status_code == 400,
          res.status_code)
    check("  nothing was written", not landed.purchases, landed.purchases)
    res, landed = post_webhook("kitchen", True, "cs_live_y", TEST_WH, test="")
    check("an unconfigured test secret is simply not tried",
          res.status_code == 400, res.status_code)
    res, landed = post_webhook("kitchen", True, "cs_live_z", LIVE_WH, live="",
                               test="")
    check("no secrets at all is a 400, not a crash", res.status_code == 400,
          res.status_code)

    print("\n--- what keeps a live purchase out of the skip ---")
    res, landed = post_webhook("kitchen", True, "cs_live_ok", LIVE_WH)
    check("livemode true and a cs_live_ id reports to Meta",
          len(landed.capi) == 1, landed.capi)
    res, landed = post_webhook("kitchen", False, "cs_live_odd", LIVE_WH)
    check("livemode false alone is enough to skip", not landed.capi,
          landed.capi)
    res, landed = post_webhook("kitchen", True, "cs_test_odd", LIVE_WH)
    check("a cs_test_ id alone is enough to skip", not landed.capi,
          landed.capi)
    # An event with no `livemode` at all must behave exactly as it did before
    # this change: a live purchase can never be lost to a missing field.
    payload = json.dumps({k: v for k, v in
                          event_for("kitchen", True, "cs_live_old").items()
                          if k != "livemode"})
    was = (config.STRIPE_WEBHOOK_SECRET, config.STRIPE_TEST_WEBHOOK_SECRET)
    config.STRIPE_WEBHOOK_SECRET = LIVE_WH
    config.STRIPE_TEST_WEBHOOK_SECRET = TEST_WH
    landed = Landed()
    landed.install()
    try:
        with app.test_client() as client:
            res = client.post("/api/stripe/webhook", data=payload,
                              headers=signed_headers(payload, LIVE_WH))
    finally:
        landed.restore()
        config.STRIPE_WEBHOOK_SECRET, config.STRIPE_TEST_WEBHOOK_SECRET = was
    check("an event with no livemode field still reports, as it always did",
          res.status_code == 200 and len(landed.capi) == 1, landed.capi)

    print("\n--- the routes and the config copies ---")
    with app.test_client() as client:
        for slug in ("kitchen", "kitchen-visualizer"):
            check("/%s serves the funnel shell" % slug,
                  client.get("/" + slug).status_code == 200)
        check("a slug with no file is still a 404",
              client.get("/kitchen-nope").status_code == 404)
    live = json.load(open(os.path.join(REPO, "funnels/kitchen-visualizer.json")))
    served = json.load(
        open(os.path.join(REPO, "static/funnels/kitchen-visualizer.json")))
    check("funnels/ and static/funnels/ agree", live == served)
    check("the mode helpers read what the config says",
          payments._stripe_mode(live) == "test"
          and payments._stripe_mode(
              json.load(open(os.path.join(REPO, "funnels/kitchen.json"))))
          == "live"
          and payments._stripe_mode({}) == "live"
          and payments._stripe_mode(None) == "live")
    check("and an unknown mode is treated as live, never as test",
          payments._stripe_mode({"stripe_mode": "sandbox"}) == "live")

    print("\n%d checks, %d failed" % (checks[0], len(fails)))
    for f in fails:
        print("  FAIL " + f)
    return 1 if fails else 0


if __name__ == "__main__":
    raise SystemExit(main())
