#!/usr/bin/env python3
"""The PaymentIntent path: creation, the webhook that confirms it, and dedup.

The money path, which is why this one is in the repo. It needs no database,
no network and no browser — a Flask test client, a fake database that enforces
the same unique keys MySQL does, and fakes for the two Stripe calls it makes.

    python3 tests/test_payment_intent.py

Exits non-zero if anything fails.

What matters here: that an intent prices exactly as the redirect does, that
the webhook can record a purchase with no checkout session at all, that a
payment which somehow produced both events yields ONE row, and that a wallet
payment survives the shape Stripe actually hands back.

Two checks are worth reading before the rest.

The dedup is not asserted by inspection: the fake database enforces
`uq_payment_intent` the way MySQL does, so the second insert raises
IntegrityError and the handler's existing branch has to be the thing that
catches it.

And `FakeStripeObject` is asserted against the real `stripe.StripeObject`
rather than trusted. A fake that returned a plain dict here is why a webhook
that 500'd on every Apple Pay payment shipped under a green suite: production
gets an object that is not a dict, whose `.get` raises AttributeError and
which `dict()` cannot convert. If the SDK's behaviour moves again, those
checks fail rather than this file quietly going back to testing a shape
nothing ever sees.
"""
import hashlib
import hmac
import json
import logging
import os
import sys
import time

# The repo root, from this file rather than from a hardcoded path: this
# has to import the real payments.py on a developer box and on the
# server, and those are not at the same absolute path.
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import config          # noqa: E402
import database        # noqa: E402
import payments        # noqa: E402
import reports         # noqa: E402
import stripe          # noqa: E402
from app import app    # noqa: E402

LIVE_KEY, TEST_KEY = "sk_live_notreal", "sk_test_notreal"
LIVE_PUB, TEST_PUB = "pk_live_notreal", "pk_test_notreal"
LIVE_WH, TEST_WH = "whsec_live_notreal", "whsec_test_notreal"

SESSION = "11111111-2222-4333-8444-555555555555"

fails = []
checks = [0]


def check(label, ok, detail=""):
    checks[0] += 1
    if not ok:
        fails.append("%s %s" % (label, detail))
    print("  %-64s %s%s" % (label, "ok" if ok else "FAIL",
                            ("  " + str(detail)) if not ok else ""))


class Recorder:
    """Stands in for a Stripe create call and keeps the kwargs."""

    def __init__(self, result):
        self.calls = []
        self.result = result

    def __call__(self, **kwargs):
        self.calls.append(kwargs)
        return self.result


class Intent(dict):
    """A PaymentIntent object: attribute access, like the SDK's."""

    def __getattr__(self, name):
        try:
            return self[name]
        except KeyError:
            raise AttributeError(name)


def body_for(slug, **over):
    cfg = config.load_funnel(slug)
    out = {
        "funnel": slug,
        "session_id": SESSION,
        "result_style": cfg["styles"][0]["id"],
        "tag_scores": {"warm": 8, "wood": 6},
        "choices": [s["pairs"][0]["images"][0]["id"]
                    for s in cfg["swipe"]["steps"]],
    }
    out.update(over)
    return out


def post_intent(slug, live=LIVE_KEY, test=TEST_KEY, live_pub=LIVE_PUB,
                test_pub=TEST_PUB, body=None, **over):
    rec = Recorder(Intent(id="pi_created", client_secret="pi_created_secret_x"))
    real = stripe.PaymentIntent.create
    was = (config.STRIPE_SECRET_KEY, config.STRIPE_TEST_SECRET_KEY,
           config.STRIPE_PUBLISHABLE_KEY, config.STRIPE_TEST_PUBLISHABLE_KEY)
    stripe.PaymentIntent.create = rec
    (config.STRIPE_SECRET_KEY, config.STRIPE_TEST_SECRET_KEY,
     config.STRIPE_PUBLISHABLE_KEY,
     config.STRIPE_TEST_PUBLISHABLE_KEY) = live, test, live_pub, test_pub
    try:
        with app.test_client() as client:
            res = client.post("/api/payment-intent",
                              json=(body_for(slug, **over) if body is None
                                    else body))
    finally:
        stripe.PaymentIntent.create = real
        (config.STRIPE_SECRET_KEY, config.STRIPE_TEST_SECRET_KEY,
         config.STRIPE_PUBLISHABLE_KEY,
         config.STRIPE_TEST_PUBLISHABLE_KEY) = was
    return res, (rec.calls[0] if rec.calls else None)


# --- the webhook -----------------------------------------------------------

def signed_headers(payload, secret):
    stamp = int(time.time())
    mac = hmac.new(secret.encode(), ("%d.%s" % (stamp, payload)).encode(),
                   hashlib.sha256).hexdigest()
    return {"Stripe-Signature": "t=%d,v1=%s" % (stamp, mac),
            "Content-Type": "application/json"}


def pi_event(slug, livemode=True, pi="pi_abc", amount=None, charge=None,
             event_id=None, received=True):
    cfg = config.load_funnel(slug)
    # `is None` and not `or`: zero is a value this fixture has to be able to
    # produce, and `amount or default` would quietly turn it into the price.
    if amount is None:
        amount = cfg["pricing"]["amount_cents"]
    obj = {
        "id": pi,
        "object": "payment_intent",
        "amount": amount,
        "currency": cfg["pricing"]["currency"],
        "metadata": {"funnel": slug, "session_id": SESSION,
                     "result_style": cfg["styles"][0]["id"]},
    }
    if received:
        obj["amount_received"] = amount
    if charge is not None:
        obj["latest_charge"] = charge
    return {
        "id": event_id or ("evt_pi_%d" % int(time.time() * 1000000)),
        "type": "payment_intent.succeeded",
        "created": int(time.time()),
        "livemode": livemode,
        "data": {"object": obj},
    }


def cs_event(slug, livemode=True, cs="cs_live_abc", pi="pi_abc",
             event_id=None):
    cfg = config.load_funnel(slug)
    return {
        "id": event_id or ("evt_cs_%d" % int(time.time() * 1000000)),
        "type": "checkout.session.completed",
        "created": int(time.time()),
        "livemode": livemode,
        "data": {"object": {
            "id": cs,
            "amount_total": cfg["pricing"]["amount_cents"],
            "currency": cfg["pricing"]["currency"],
            "payment_intent": pi,
            "customer_details": {"email": "buyer@example.com",
                                 "address": {"country": "US"}},
            "metadata": {"funnel": slug, "session_id": SESSION,
                         "result_style": cfg["styles"][0]["id"]},
        }},
    }


class Landed:
    """A database that enforces the unique keys the real one enforces."""

    def __init__(self, db_raises=False):
        self.purchases = []
        self.capi = []
        self.reports = []
        # Who actually got a PDF. `_record_side_effects` only arms the delivery
        # hook when there is an email, so this stays empty on every no-email
        # path — which is the difference between a delivery gap and a lost sale
        # and is worth asserting rather than inferring.
        self.emailed = []
        self.next_id = 2000
        self.by_pi = {}
        self.by_event = {}
        self.db_raises = db_raises

    def install(self):
        import pymysql.err
        self.real = (database.execute, payments.send_purchase_event,
                     reports.start_report, payments._claim_visualizer_photo,
                     reports.send_report_email)

        def execute(sql, params=None):
            if "INSERT INTO purchases" in sql:
                if self.db_raises:
                    raise RuntimeError("database is down")
                event_id, pi = params[2], params[3]
                # uq_stripe_event and uq_payment_intent. MySQL allows many
                # NULLs in a unique column, so only non-NULL values collide —
                # which is exactly the behaviour the dedup relies on.
                if event_id is not None and event_id in self.by_event:
                    raise pymysql.err.IntegrityError(1062, "dup event")
                if pi is not None and pi in self.by_pi:
                    raise pymysql.err.IntegrityError(1062, "dup pi")
                self.next_id += 1
                self.by_event[event_id] = self.next_id
                if pi is not None:
                    self.by_pi[pi] = self.next_id
                self.purchases.append(params)
                return self.next_id
            return 1

        def capi(*a, **kw):
            self.capi.append(kw.get("email"))
            return True

        def send_email(purchase_id, email, content, checkout_session):
            self.emailed.append((purchase_id, email))
            return True

        def start(purchase_id, slug, style, *a, **kw):
            self.reports.append((purchase_id, slug, style))
            content = {"version": "llm-2"}
            # The real one fires this once the report finishes. Fired here so
            # the suite sees whether an email would actually go out, rather
            # than only whether a hook was passed.
            final = kw.get("on_final")
            if final:
                final(content)
            return content

        database.execute = execute
        payments.database.execute = execute
        payments.send_purchase_event = capi
        reports.start_report = start
        payments.reports.start_report = start
        reports.send_report_email = send_email
        payments.reports.send_report_email = send_email
        payments._claim_visualizer_photo = lambda *a: None

    def restore(self):
        (database.execute, payments.send_purchase_event, reports.start_report,
         payments._claim_visualizer_photo,
         reports.send_report_email) = self.real
        payments.database.execute = database.execute
        payments.reports.start_report = reports.start_report
        payments.reports.send_report_email = reports.send_report_email


# --- what stripe.Charge.retrieve actually hands back -------------------------

# The fake that let a live 500 through 1609 passing checks returned a plain
# dict here. Stripe returns a StripeObject, and in SDK 15.x that is NOT a dict:
# it is a plain object with `__getitem__` and `__getattr__`, so `.get()` raises
# AttributeError and `dict()` on it raises KeyError: 0. A stub that is a dict
# tests the one shape production never sees.
#
# This is that object's semantics, written out rather than imported, so the
# suite states what it is depending on instead of inheriting it. It is checked
# against the real `stripe.StripeObject` below — if the SDK's behaviour ever
# moves, that check fails rather than this fake quietly drifting back into
# being wrong in a new way.
class FakeStripeObject:
    """Item access and attribute access. No `.get`, not a dict, `to_dict()`
    recurses — exactly `stripe._stripe_object.StripeObject` in 15.x."""

    def __init__(self, data):
        self._data = data

    def __getitem__(self, key):
        value = self._data[key]
        return FakeStripeObject(value) if isinstance(value, dict) else value

    def __getattr__(self, name):
        if name.startswith("_"):
            raise AttributeError(name)
        try:
            return self[name]
        except KeyError:
            raise AttributeError(name)

    def to_dict(self, recursive=True):
        if not recursive:
            return dict(self._data)
        return {k: (FakeStripeObject(v).to_dict() if isinstance(v, dict) else v)
                for k, v in self._data.items()}


class _NoDetails:
    """A charge that came back carrying no `billing_details` at all."""


class Raises:
    """A retrieve that fails the way a network or an API error does."""


_NO_DETAILS = _NoDetails()


def charge_object(email, country="GB"):
    """A charge as the SDK hands it over, with or without billing details."""
    data = {"id": "ch_fake", "object": "charge"}
    if email is not _NO_DETAILS:
        data["billing_details"] = {"email": email,
                                   "address": {"country": country}}
    return FakeStripeObject(data)


def post_hook(events, secret=LIVE_WH, landed=None, charge_email=None,
              db_raises=False):
    """Post one or more events through the real route, sharing a database.

    `charge_email` is what the fetched charge carries. `_NO_DETAILS` gives a
    charge with no `billing_details` key at all; `Raises` makes the retrieve
    itself blow up. `db_raises` makes the purchase insert fail, which must
    still be a 500 — Stripe's retry is the recovery.
    """
    was = (config.STRIPE_WEBHOOK_SECRET, config.STRIPE_TEST_WEBHOOK_SECRET,
           config.STRIPE_SECRET_KEY)
    config.STRIPE_WEBHOOK_SECRET = LIVE_WH
    config.STRIPE_TEST_WEBHOOK_SECRET = TEST_WH
    config.STRIPE_SECRET_KEY = LIVE_KEY
    landed = landed or Landed(db_raises=db_raises)
    landed.install()

    real_charge = stripe.Charge.retrieve
    fetched = []

    def retrieve(cid, **kw):
        fetched.append((cid, kw.get("api_key")))
        if charge_email is Raises:
            raise RuntimeError("no route to stripe")
        return charge_object(charge_email)

    stripe.Charge.retrieve = retrieve
    out = []
    try:
        with app.test_client() as client:
            for event in events:
                payload = json.dumps(event)
                out.append(client.post("/api/stripe/webhook", data=payload,
                                       headers=signed_headers(payload, secret)))
    finally:
        landed.restore()
        stripe.Charge.retrieve = real_charge
        (config.STRIPE_WEBHOOK_SECRET, config.STRIPE_TEST_WEBHOOK_SECRET,
         config.STRIPE_SECRET_KEY) = was
    return out, landed, fetched


def main():
    print("\n--- the intent is priced from the funnel, never from the body ---")
    res, kw = post_intent("kitchen")
    check("the route answers 200", res.status_code == 200,
          (res.status_code, res.get_json()))
    body = res.get_json()
    check("  and returns a client secret",
          body.get("client_secret") == "pi_created_secret_x", body)
    check("  the publishable key, not the secret",
          body.get("publishable_key") == LIVE_PUB
          and LIVE_KEY not in json.dumps(body), body)
    check("  the amount and currency it was created for",
          body.get("amount_cents") == 300 and body.get("currency") == "usd",
          body)
    check("Stripe was asked for exactly that amount",
          kw["amount"] == 300 and kw["currency"] == "usd",
          (kw.get("amount"), kw.get("currency")))
    check("  on the live key, passed per call",
          kw.get("api_key") == LIVE_KEY, kw.get("api_key"))
    check("  with automatic payment methods, so wallets surface on their own",
          kw.get("automatic_payment_methods") == {"enabled": True},
          kw.get("automatic_payment_methods"))
    check("  carrying the same metadata the checkout session carries",
          kw["metadata"]["funnel"] == "kitchen"
          and kw["metadata"]["session_id"] == SESSION
          and "tag_scores" in kw["metadata"]
          and "choices" in kw["metadata"], kw.get("metadata"))

    # The client cannot say what anything costs — the body's amount is ignored
    # because there is nowhere for it to enter.
    res, kw = post_intent("kitchen", body=dict(body_for("kitchen"),
                                               amount_cents=1, amount=1,
                                               price=1))
    check("an amount in the body changes nothing",
          res.status_code == 200 and kw["amount"] == 300, kw.get("amount"))

    print("\n--- the visualizer funnel, on its own key set ---")
    res, kw = post_intent("kitchen-visualizer")
    check("it transacts on the test key",
          kw.get("api_key") == TEST_KEY, kw.get("api_key"))
    check("  at its own price", kw["amount"] == 700, kw.get("amount"))
    check("  and hands back the test publishable key",
          res.get_json()["publishable_key"] == TEST_PUB, res.get_json())

    print("\n--- and refuses rather than guesses ---")
    res, kw = post_intent("kitchen-visualizer", test="")
    check("no test secret means no intent", res.status_code == 502,
          res.status_code)
    check("  and nothing was sent to Stripe", kw is None, kw)
    res, kw = post_intent("kitchen-visualizer", test_pub="")
    check("no test publishable key means no intent either — a payment "
          "nobody can confirm is worse than none", res.status_code == 502,
          res.status_code)
    check("  and again nothing was sent", kw is None, kw)

    print("\n--- the same validation as the redirect, not a second copy ---")
    for label, over in (("a style that is not in the config",
                         {"result_style": "not-a-style"}),
                        ("a session id that is not a UUID",
                         {"session_id": "nope"}),
                        ("a funnel that does not exist",
                         {"funnel": "no-such-funnel"})):
        res, kw = post_intent("kitchen", **over)
        check("%s is a 400" % label, res.status_code == 400,
              res.status_code)
        check("  with nothing sent to Stripe", kw is None, kw)
    res, _ = post_intent("kitchen", body="not a dict")
    check("a body that is not an object is a 400", res.status_code == 400,
          res.status_code)

    # --- the boundary the old fake got wrong ------------------------------
    #
    # Everything below depends on FakeStripeObject behaving like the real one,
    # so that is asserted against the SDK rather than assumed. A stub that is
    # secretly a dict is how a webhook that 500s on every wallet payment went
    # out under a green suite.
    print("\n--- the fake charge object matches the real StripeObject ---")
    real = stripe.StripeObject.construct_from(
        {"id": "ch_r", "billing_details": {"email": "r@x.com",
                                           "address": {"country": "US"}}},
        "sk_test")
    fake = charge_object("r@x.com", country="US")

    for label, obj in (("stripe.StripeObject", real), ("our fake", fake)):
        check("%-20s is not a dict" % label, not isinstance(obj, dict))
        check("  %-18s has no .get" % label, not hasattr(obj, "get"))
        try:
            obj.get("billing_details")
            got = "no error"
        except AttributeError:
            got = "AttributeError"
        except Exception as exc:
            got = type(exc).__name__
        check("  %-18s .get raises AttributeError" % label,
              got == "AttributeError", got)
        try:
            dict(obj)
            conv = "no error"
        except Exception as exc:
            conv = type(exc).__name__
        check("  %-18s dict() raises, so [] alone is not the fix" % label,
              conv != "no error", conv)
        check("  %-18s item access works" % label,
              obj["billing_details"]["email"] == "r@x.com")
        plain = obj.to_dict()
        check("  %-18s to_dict() gives a plain dict" % label,
              isinstance(plain, dict) and not hasattr(plain, "to_dict"))
        check("  %-18s to_dict() recurses, so one conversion is enough" % label,
              type(plain["billing_details"]) is dict
              and type(plain["billing_details"]["address"]) is dict,
              type(plain["billing_details"]).__name__)
        # getattr rather than a direct call: run against a payments.py that has
        # no such helper this must FAIL, not abort the suite before the
        # behavioural scenarios below get their turn.
        plainly = getattr(payments, "_as_plain_dict", None)
        check("  %-18s survives _as_plain_dict" % label,
              plainly is not None
              and plainly(obj)["billing_details"]["address"]
              .get("country") == "US",
              "no _as_plain_dict" if plainly is None else "")

    print("\n--- the webhook records a purchase with no checkout session ---")
    out, landed, fetched = post_hook([pi_event("kitchen", charge="ch_1")],
                                     charge_email="buyer@example.com")
    check("it is accepted", out[0].status_code == 200,
          (out[0].status_code, out[0].get_json()))
    check("  one purchase written", len(landed.purchases) == 1,
          landed.purchases)
    row = landed.purchases[0]
    check("  with the payment intent as its identifier",
          row[3] == "pi_abc", row[3])
    check("  and NULL where the checkout session would be",
          row[4] is None, row[4])
    check("  the amount taken, from amount_received",
          row[5] == 300, row[5])
    check("  the email off the charge", row[7] == "buyer@example.com", row[7])
    check("  and the country off its billing address", row[8] == "GB", row[8])
    check("the charge was retrieved with the mode's key",
          fetched and fetched[0][1] == LIVE_KEY, fetched)
    check("the report pipeline runs", len(landed.reports) == 1, landed.reports)

    print("\n--- a real Apple Pay payment, end to end ---")
    # The exact shape of the live 500: payment_intent.succeeded carrying a
    # bare latest_charge id, so the charge is fetched, so a StripeObject is
    # what the handler has to read. Pre-fix this was an AttributeError inside
    # the route, a 500 out, no purchase row, and a paid reader watching a
    # spinner forever.
    out, landed, fetched = post_hook([pi_event("kitchen", pi="pi_wallet",
                                               charge="ch_wallet")],
                                     charge_email="wallet@icloud.com")
    check("the webhook answers 200, not 500", out[0].status_code == 200,
          (out[0].status_code, out[0].get_json()))
    check("  a purchase is recorded", len(landed.purchases) == 1,
          landed.purchases)
    check("  WITH the wallet email off the StripeObject",
          landed.purchases[0][7] == "wallet@icloud.com", landed.purchases[0][7])
    check("  and the country out of the nested address",
          landed.purchases[0][8] == "GB", landed.purchases[0][8])
    check("  the report runs and the email is armed",
          len(landed.reports) == 1, landed.reports)
    check("  Stripe was asked for the charge once, on the mode's key",
          len(fetched) == 1 and fetched[0] == ("ch_wallet", LIVE_KEY), fetched)

    print("\n--- a charge with no billing details at all ---")
    out, landed, _ = post_hook([pi_event("kitchen", pi="pi_nodet",
                                         charge="ch_nodet")],
                               charge_email=_NO_DETAILS)
    check("still a 200", out[0].status_code == 200, out[0].status_code)
    check("  the purchase is recorded", len(landed.purchases) == 1,
          landed.purchases)
    check("  email NULL", landed.purchases[0][7] is None,
          landed.purchases[0][7])
    check("  country NULL too", landed.purchases[0][8] is None,
          landed.purchases[0][8])
    check("  the report is still generated", len(landed.reports) == 1,
          landed.reports)
    check("  and no email was sent — only delivery is skipped",
          landed.emailed == [], landed.emailed)

    print("\n--- the charge retrieve itself blows up ---")
    out, landed, fetched = post_hook([pi_event("kitchen", pi="pi_boom",
                                               charge="ch_boom")],
                                     charge_email=Raises)
    check("a failed fetch does not cost the purchase",
          out[0].status_code == 200 and len(landed.purchases) == 1,
          (out[0].status_code, landed.purchases))
    check("  email NULL", landed.purchases[0][7] is None,
          landed.purchases[0][7])
    check("  the report is still generated", len(landed.reports) == 1,
          landed.reports)
    check("  no email sent", landed.emailed == [], landed.emailed)
    check("  and it really did try", len(fetched) == 1, fetched)

    print("\n--- a payment with an explicitly empty email ---")
    out, landed, _ = post_hook([pi_event("kitchen", charge="ch_2")],
                               charge_email=None)
    check("it is recorded", len(landed.purchases) == 1, landed.purchases)
    check("  with no email", landed.purchases[0][7] is None,
          landed.purchases[0][7])
    check("  and the report is still generated — only delivery is skipped",
          len(landed.reports) == 1, landed.reports)
    check("  no email sent", landed.emailed == [], landed.emailed)

    print("\n--- an unexpected failure is still a 500, so Stripe retries ---")
    # The route logs this one with log.exception, by design — it is a real
    # failure and the traceback belongs in the server log. Silenced only here,
    # so the sweep's "did anything crash" heuristic is not reading our own
    # deliberate breakage as a broken suite.
    quiet = logging.getLogger("payments")
    was_level = quiet.level
    quiet.setLevel(logging.CRITICAL)
    try:
        out, landed, _ = post_hook([pi_event("kitchen", pi="pi_dbdown",
                                             charge=None)], db_raises=True)
    finally:
        quiet.setLevel(was_level)
    check("the insert failing is a 500, not a swallowed 200",
          out[0].status_code == 500, out[0].status_code)
    check("  and nothing was recorded", not landed.purchases, landed.purchases)

    print("\n--- the charge inline, and the charge absent ---")
    inline = pi_event("kitchen", charge=None)
    inline["data"]["object"]["latest_charge"] = {
        "billing_details": {"email": "inline@example.com",
                            "address": {"country": "FR"}}}
    out, landed, fetched = post_hook([inline])
    check("an expanded charge is read without a second call",
          landed.purchases[0][7] == "inline@example.com" and not fetched,
          (landed.purchases[0][7], fetched))
    out, landed, fetched = post_hook([pi_event("kitchen", charge=None)])
    check("no charge at all is still a purchase",
          len(landed.purchases) == 1 and landed.purchases[0][7] is None,
          landed.purchases)

    print("\n--- an intent that received nothing is not a purchase ---")
    out, landed, _ = post_hook([pi_event("kitchen", received=False)])
    check("it is skipped, not recorded",
          out[0].get_json().get("status") == "skipped"
          and not landed.purchases, (out[0].get_json(), landed.purchases))
    out, landed, _ = post_hook([pi_event("kitchen", amount=0)])
    check("a zero amount_received is skipped too",
          not landed.purchases, landed.purchases)

    print("\n--- ONE payment, BOTH events, ONE row ---")
    # This is the guarantee the unique key on payment_intent exists for. Both
    # orders are tried, because Stripe does not promise which arrives first.
    for order, names in (((cs_event("kitchen", cs="cs_live_z", pi="pi_both"),
                           pi_event("kitchen", pi="pi_both", charge=None)),
                          "checkout first, then intent"),
                         ((pi_event("kitchen", pi="pi_both2", charge=None),
                           cs_event("kitchen", cs="cs_live_y", pi="pi_both2")),
                          "intent first, then checkout")):
        out, landed, _ = post_hook(list(order))
        check("%s: both answered 200" % names,
              [r.status_code for r in out] == [200, 200],
              [r.status_code for r in out])
        check("  the second is reported as a duplicate",
              out[1].get_json().get("status") == "duplicate",
              out[1].get_json())
        check("  and exactly ONE purchase row exists",
              len(landed.purchases) == 1, len(landed.purchases))
        check("  with one report generated, not two",
              len(landed.reports) == 1, landed.reports)

    print("\n--- Meta hears only about live payments ---")
    out, landed, _ = post_hook([pi_event("kitchen", livemode=True,
                                         charge="ch_l")],
                               charge_email="buyer@example.com")
    check("a live intent is reported", len(landed.capi) == 1, landed.capi)
    out, landed, _ = post_hook([pi_event("kitchen", livemode=False,
                                         charge="ch_t")],
                               charge_email="buyer@example.com")
    check("livemode false is skipped — the only marker this path has",
          not landed.capi, landed.capi)
    # There is no cs_test_ to read on this path, and a pi_ id looks identical
    # in both modes. An event with no livemode must behave as it always did.
    no_flag = pi_event("kitchen", charge=None)
    no_flag.pop("livemode")
    out, landed, _ = post_hook([no_flag])
    check("an event with no livemode still reports, as it always did",
          len(landed.capi) == 1, landed.capi)
    check("  and nothing invents a test marker from the pi_ prefix",
          payments._is_live_payment({"livemode": True}, None) is True)

    print("\n--- the redirect path is exactly as it was ---")
    out, landed, fetched = post_hook([cs_event("kitchen")])
    check("a checkout.session.completed still records", out[0].status_code
          == 200 and len(landed.purchases) == 1, landed.purchases)
    row = landed.purchases[0]
    check("  keeping its checkout session", row[4] == "cs_live_abc", row[4])
    check("  and its payment intent", row[3] == "pi_abc", row[3])
    check("  amount from amount_total", row[5] == 300, row[5])
    check("  email from customer_details",
          row[7] == "buyer@example.com", row[7])
    check("  and it still reports to Meta", len(landed.capi) == 1, landed.capi)
    # The hosted session arrives fully inline in the webhook body, so nothing
    # on this path ever touches a StripeObject. That is why it kept working
    # while every wallet payment 500'd, and it is worth pinning: the fix must
    # not have reached across into it.
    check("  it never fetched a charge — the session is already inline",
          not fetched, fetched)
    check("  and the email really is delivered on this path",
          [e[1] for e in landed.emailed] == ["buyer@example.com"],
          landed.emailed)
    out, landed, _ = post_hook([cs_event("kitchen", cs="cs_test_x")])
    check("a cs_test_ session is still kept out of Meta", not landed.capi,
          landed.capi)

    print("\n--- an event we do not handle is still ignored ---")
    other = pi_event("kitchen")
    other["type"] = "payment_intent.payment_failed"
    out, landed, _ = post_hook([other])
    check("it is acknowledged and nothing is written",
          out[0].get_json().get("status") == "ignored"
          and not landed.purchases, out[0].get_json())

    print("\n--- one lookup, both token shapes ---")
    seen = []

    def query_one(sql, params=None):
        seen.append((sql, params))
        return {"id": 7, "funnel": "kitchen", "status": "paid"}

    real = database.query_one
    database.query_one = query_one
    payments.database.query_one = query_one
    try:
        payments.find_purchase("cs_live_abc")
        payments.find_purchase("pi_abc")
    finally:
        database.query_one = real
        payments.database.query_one = real
    check("both columns are searched", all(
        "checkout_session = %s OR payment_intent = %s" in s for s, _ in seen),
        seen and seen[0][0])
    check("  with the token passed to both sides",
          [p for _, p in seen] == [("cs_live_abc", "cs_live_abc"),
                                   ("pi_abc", "pi_abc")],
          [p for _, p in seen])
    check("a cs_ token is still a valid result token",
          bool(payments.RESULT_TOKEN_RE.match("cs_live_abcDEF123")))
    check("  and a pi_ token is one now too",
          bool(payments.RESULT_TOKEN_RE.match("pi_3abcDEF123")))
    check("  while junk is not",
          not payments.RESULT_TOKEN_RE.match("../../etc/passwd")
          and not payments.RESULT_TOKEN_RE.match("ch_abc")
          and not payments.RESULT_TOKEN_RE.match(""))
    import visualizer
    check("the visualizer resolves purchases through the same function",
          visualizer.find_purchase is payments.find_purchase)
    check("  and no longer keeps a SELECT of its own",
          not hasattr(visualizer, "SELECT_PURCHASE_SQL"))

    print("\n%d checks, %d failed" % (checks[0], len(fails)))
    for f in fails:
        print("  FAIL " + f)
    return 1 if fails else 0


if __name__ == "__main__":
    raise SystemExit(main())
