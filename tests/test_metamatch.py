#!/usr/bin/env python3
"""What reaches Meta, and what must never.

Server-side Purchase events were matching at 5.9 out of 10 because a hashed
iCloud relay address matches nobody. The fix is a set of identifiers, and
every one of them crosses two boundaries on its way out — the browser to the
checkout route, and the checkout route to a webhook that fires minutes later
from somebody else's request. This walks a stubbed checkout into a stubbed
webhook and reads the payload that comes out the other end.

Half of this suite is about absence. The payload is allowed identifiers and a
price; it is not allowed a raw email address and it is not allowed one word
about the quiz. A sign, a purpose, a subtype or a list of choices in an ad
platform's payload would be an inference about somebody made from a thing
they thought was a game — and it would be there for as long as the platform
keeps it. So the assertions are written the strict way round: not "the
expected keys are present" but "nothing outside the allowed set is, anywhere
in the tree, at any depth".

No database, no Stripe, no network, no Meta. Every one of the four is stubbed
and every payload is caught rather than sent.

    python3 tests/test_metamatch.py
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

import config          # noqa: E402
import database        # noqa: E402
import payments        # noqa: E402
import reports         # noqa: E402
import stripe          # noqa: E402
from app import app    # noqa: E402

SESSION = "11111111-2222-4333-8444-555555555555"
EMAIL = "Buyer@icloud.com"
IP = "203.0.113.9"
UA = "Mozilla/5.0 (iPhone; CPU iPhone OS 17_5 like Mac OS X) Safari/605.1"
FBP = "fb.1.1750000000000.1234567890"
FBC = "fb.1.1750000000000.IwAR0abcDEF"
FBCLID = "IwAR0zzzTOP"
WEBHOOK_SECRET = "whsec_notreal_live"

fails = []
checks = [0]


def check(label, ok, detail=""):
    checks[0] += 1
    if not ok:
        fails.append("%s %s" % (label, detail))
    print("  %-66s %s%s" % (label, "ok" if ok else "FAIL",
                            ("  " + str(detail)) if not ok else ""))


def sha(value):
    return hashlib.sha256(value.strip().lower().encode("utf-8")).hexdigest()


def walk(node, path=""):
    """Every (path, leaf) in a nested structure, so a claim about the payload
    can be made about the whole of it rather than about the keys somebody
    remembered to look at."""
    if isinstance(node, dict):
        for key, value in node.items():
            for row in walk(value, "%s.%s" % (path, key)):
                yield row
    elif isinstance(node, (list, tuple)):
        for n, value in enumerate(node):
            for row in walk(value, "%s[%d]" % (path, n)):
                yield row
    else:
        yield path, node


# --- the harness ------------------------------------------------------------

class Rig:
    """A checkout and a webhook with nothing real behind either."""

    def __init__(self):
        self.stripe_kwargs = None
        self.context = {}          # session_id -> (ip, ua)
        self.capi = []             # the payloads that would have gone to Meta
        self.events = []           # everything written to the events table
        self.logs = []

    # -- stubs
    def _session_create(self, **kwargs):
        self.stripe_kwargs = kwargs

        class Session:
            url = "https://checkout.stripe.test/c/pay/cs_live_x"
            id = "cs_live_x"
        return Session()

    def _execute(self, sql, params=None):
        if "checkout_context" in sql:
            self.context[params[0]] = (params[1], params[2])
            return 1
        if "INSERT INTO events" in sql:
            self.events.append((sql, params))
            return 1
        if "INSERT INTO purchases" in sql:
            return 4242
        return 1

    def _query_one(self, sql, params=None):
        if "checkout_context" in sql:
            got = self.context.get(params[0])
            if not got:
                return None
            return {"client_ip": got[0], "client_ua": got[1]}
        return None

    def _post(self, url, json=None, params=None, timeout=None):
        self.capi.append({"url": url, "params": params, "payload": json})

        class Response:
            status_code = 200
        return Response()

    def install(self):
        self.real = (
            stripe.checkout.Session.create, database.execute,
            database.query_one, reports.start_report,
            config.STRIPE_SECRET_KEY, config.STRIPE_TEST_SECRET_KEY,
            config.STRIPE_WEBHOOK_SECRET, config.STRIPE_TEST_WEBHOOK_SECRET,
            config.META_PIXEL_ID, config.META_CAPI_TOKEN,
            config.META_TEST_EVENT_CODE, payments.log,
        )
        stripe.checkout.Session.create = self._session_create
        database.execute = self._execute
        database.query_one = self._query_one
        payments.database.execute = self._execute
        payments.database.query_one = self._query_one
        reports.start_report = lambda *a, **kw: {"version": "llm-2"}
        payments.reports.start_report = reports.start_report
        config.STRIPE_SECRET_KEY = "sk_live_notreal"
        config.STRIPE_TEST_SECRET_KEY = "sk_test_notreal"
        config.STRIPE_WEBHOOK_SECRET = WEBHOOK_SECRET
        config.STRIPE_TEST_WEBHOOK_SECRET = ""
        config.META_PIXEL_ID = "111222333"
        config.META_CAPI_TOKEN = "tok_notreal"
        config.META_TEST_EVENT_CODE = ""

        # `requests` is imported inside the sender, so the module is what has
        # to be replaced rather than an attribute on payments.
        import types
        stub = types.ModuleType("requests")
        stub.post = self._post
        self.real_requests = sys.modules.get("requests")
        sys.modules["requests"] = stub

        rig = self

        class Recorder:
            """Every log line the payment path writes, so "the address is
            never logged" is a claim about output rather than about care."""

            def _keep(self, template, *args):
                try:
                    rig.logs.append(str(template) % args if args
                                    else str(template))
                except Exception:
                    rig.logs.append("%s %s" % (template, args))

            info = warning = error = exception = debug = _keep

        payments.log = Recorder()

    def restore(self):
        (stripe.checkout.Session.create, database.execute,
         database.query_one, reports.start_report,
         config.STRIPE_SECRET_KEY, config.STRIPE_TEST_SECRET_KEY,
         config.STRIPE_WEBHOOK_SECRET, config.STRIPE_TEST_WEBHOOK_SECRET,
         config.META_PIXEL_ID, config.META_CAPI_TOKEN,
         config.META_TEST_EVENT_CODE, payments.log) = self.real
        payments.database.execute = database.execute
        payments.database.query_one = database.query_one
        payments.reports.start_report = reports.start_report
        if self.real_requests is None:
            sys.modules.pop("requests", None)
        else:
            sys.modules["requests"] = self.real_requests

    # -- the two halves of a purchase
    def checkout(self, slug, cookies=None, headers=None, session_id=SESSION):
        cfg = config.load_funnel(slug)
        body = {
            "funnel": slug,
            "session_id": session_id,
            "result_style": cfg["styles"][0]["id"],
            "tag_scores": {"fire": 8, "sun": 6},
            "choices": [s["pairs"][0]["images"][0]["id"]
                        for s in cfg["swipe"]["steps"]],
        }
        with app.test_client() as client:
            for name, value in (cookies or {}).items():
                client.set_cookie(name, value, domain="localhost")
            return client.post("/api/checkout", json=body,
                               headers=headers or {})

    def webhook(self, slug, session_id=SESSION, email=EMAIL, metadata=None):
        cfg = config.load_funnel(slug)
        meta = dict(self.stripe_kwargs["metadata"]) if self.stripe_kwargs \
            else {}
        meta.update(metadata or {})
        event = {
            "id": "evt_%d" % int(time.time() * 1000000),
            "type": "checkout.session.completed",
            "created": int(time.time()),
            "livemode": True,
            "data": {"object": {
                "id": "cs_live_x",
                "amount_total": cfg["pricing"]["amount_cents"],
                "currency": cfg["pricing"]["currency"],
                "payment_intent": "pi_live_abc123",
                "customer_details": {"email": email,
                                     "address": {"country": "US"}},
                "metadata": meta,
            }},
        }
        payload = json.dumps(event)
        stamp = int(time.time())
        mac = hmac.new(WEBHOOK_SECRET.encode(),
                       ("%d.%s" % (stamp, payload)).encode(),
                       hashlib.sha256).hexdigest()
        with app.test_client() as client:
            return client.post(
                "/api/stripe/webhook", data=payload,
                headers={"Stripe-Signature": "t=%d,v1=%s" % (stamp, mac),
                         "Content-Type": "application/json"})

    def user_data(self):
        return self.capi[-1]["payload"]["data"][0]["user_data"]

    def event(self):
        return self.capi[-1]["payload"]["data"][0]


def run(rig, slug, cookies, headers, **kw):
    """One purchase, end to end, returning the Meta event it produced."""
    rig.capi = []
    res = rig.checkout(slug, cookies=cookies, headers=headers,
                       **{k: v for k, v in kw.items() if k == "session_id"})
    hook = rig.webhook(slug, **{k: v for k, v in kw.items()
                                if k in ("session_id", "email")})
    return res, hook


# --- a) the identifiers that arrive ----------------------------------------

rig = Rig()
rig.install()
try:
    print("\n--- a purchase, checkout through webhook ---")
    res, hook = run(rig, "zodiac",
                    cookies={"_fbp": FBP, "_fbc": FBC},
                    headers={"User-Agent": UA, "CF-Connecting-IP": IP})
    check("checkout answered", res.status_code == 200, res.status_code)
    check("  and the webhook after it", hook.status_code == 200,
          hook.status_code)
    check("one Meta event was sent", len(rig.capi) == 1, len(rig.capi))
    ud = rig.user_data()
    event = rig.event()

    check("it carries the hashed email", ud.get("em") == [sha(EMAIL)],
          str(ud.get("em")))
    check("  and external_id, hashed the same way",
          ud.get("external_id") == sha(SESSION), ud.get("external_id"))
    check("    which is the session id the funnel has used all along",
          ud["external_id"] == hashlib.sha256(
              SESSION.encode()).hexdigest(), ud["external_id"])
    check("  the browser cookie", ud.get("fbp") == FBP, ud.get("fbp"))
    check("  the click id", ud.get("fbc") == FBC, ud.get("fbc"))
    check("  where the buyer was", ud.get("client_ip_address") == IP,
          ud.get("client_ip_address"))
    check("  and what they were on", ud.get("client_user_agent") == UA,
          ud.get("client_user_agent"))
    check("the event id is the payment intent, so a replay collapses",
          event.get("event_id") == "pi_live_abc123", event.get("event_id"))
    check("  the value is the price, in units",
          event["custom_data"] == {"value": 3.0, "currency": "usd"},
          str(event["custom_data"]))
    check("  and it is a website conversion",
          event.get("action_source") == "website"
          and event.get("event_name") == "Purchase")

    # --- b) what must never be there ---------------------------------------

    print("\n--- and nothing it is not allowed ---")
    flat = list(walk(rig.capi[-1]["payload"]))
    blob = json.dumps(rig.capi[-1]["payload"])
    check("the raw email address is nowhere in it",
          "icloud" not in blob.lower() and EMAIL not in blob
          and EMAIL.lower() not in blob.lower())
    check("  nor its local part on its own",
          not re.search(r"\bBuyer\b", blob, re.I), blob[:80])
    # Everything the quiz produced, by the names it produces them under and by
    # the values this run actually chose.
    cfg = config.load_funnel("zodiac")
    QUIZ_KEYS = ("sign", "purpose", "subtype", "choices", "tag_scores",
                 "result_style", "style", "funnel", "elements", "season")
    named = [path for path, _v in flat
             if any(part in QUIZ_KEYS
                    for part in path.strip(".").split("."))]
    check("no quiz key appears anywhere in the tree", not named, str(named))
    values = {str(v) for _p, v in flat}
    quiz_values = {cfg["styles"][0]["id"], "sign_leo", "fire", "sun"}
    quiz_values |= {s["pairs"][0]["images"][0]["id"]
                    for s in cfg["swipe"]["steps"]}
    check("  nor any value the quiz produced",
          not (values & quiz_values), str(sorted(values & quiz_values)))
    check("  the only fields sent are identifiers and a price",
          set(ud) <= {"em", "external_id", "fbp", "fbc",
                      "client_ip_address", "client_user_agent"},
          str(sorted(ud)))
    check("  and the event carries no custom data but value and currency",
          set(event["custom_data"]) == {"value", "currency"},
          str(sorted(event["custom_data"])))
    # The report needs the quiz; Meta does not. Both are true at once, and
    # this is the line between them.
    check("the quiz still reaches Stripe, which is what builds the report",
          "tag_scores" in rig.stripe_kwargs["metadata"]
          and "choices" in rig.stripe_kwargs["metadata"])

    print("\n--- the address and the device are used, not kept ---")
    check("neither is written to the events table",
          not [1 for sql, params in rig.events
               if IP in str(params) or UA in str(params)],
          str(rig.events[:1]))
    # Read off the statement rather than off this flow, which writes no
    # events at all — a check that passes because nothing happened is not a
    # check. tracking.py keeps two enum words about the device and says the
    # raw User-Agent and the IP are stored nowhere; this is that sentence,
    # asserted.
    import tracking                                        # noqa: E402
    columns = tracking.INSERT_SQL.lower()
    check("  and the events statement has no column for either",
          "client_ip" not in columns and "user_agent" not in columns
          and " ip" not in columns and " ua" not in columns,
          columns)
    check("  which is the rule tracking.py states in as many words",
          "The raw User-Agent is NOT stored, here or anywhere"
          in open(os.path.join(REPO, "tracking.py"),
                  encoding="utf-8").read())
    check("  nor to any log line",
          not [line for line in rig.logs if IP in line or UA in line],
          str([line for line in rig.logs if IP in line or UA in line]))
    check("  and the log said something, so that is not a vacuous pass",
          len(rig.logs) > 0, len(rig.logs))
    check("they are held only in the context row, keyed on the session",
          rig.context.get(SESSION) == (IP, UA), str(rig.context))
    check("  which nothing else in the payload path reads",
          "checkout_context" not in json.dumps(rig.stripe_kwargs["metadata"]))

    # --- c) the shapes a real visitor actually arrives in -------------------

    print("\n--- a click with no cookie yet ---")
    rig.context.clear()
    res, hook = run(rig, "zodiac", cookies={},
                    headers={"User-Agent": UA, "CF-Connecting-IP": IP,
                             "Referer": "https://mazzin.com/zodiac"
                                        "?fbclid=" + FBCLID})
    ud = rig.user_data()
    check("fbc is built from the click id", bool(ud.get("fbc")),
          str(ud.get("fbc")))
    check("  in Meta's own format",
          re.match(r"^fb\.1\.\d{13}\.%s$" % re.escape(FBCLID),
                   ud.get("fbc") or ""), ud.get("fbc"))
    check("  stamped when the click was seen, not when the webhook fired",
          abs(int((ud["fbc"].split(".")[2])) / 1000.0 - time.time()) < 120,
          ud.get("fbc"))
    check("  and it survives the trip through Stripe metadata",
          payments.META_ID_RE.match(ud["fbc"]) is not None)
    check("the rest of the identifiers are still there",
          ud.get("external_id") == sha(SESSION)
          and ud.get("client_ip_address") == IP
          and ud.get("em") == [sha(EMAIL)])
    check("  and no fbp, because there was no cookie to read",
          "fbp" not in ud, str(sorted(ud)))

    print("\n--- and a visitor with no Meta identifiers at all ---")
    rig.context.clear()
    res, hook = run(rig, "zodiac", cookies={},
                    headers={"User-Agent": UA, "CF-Connecting-IP": IP})
    check("the purchase still reaches Meta", len(rig.capi) == 1,
          len(rig.capi))
    ud = rig.user_data()
    check("  on what it does have", set(ud) == {"em", "external_id",
                                                "client_ip_address",
                                                "client_user_agent"},
          str(sorted(ud)))
    check("  which is more than it used to have, and enough to match on",
          ud.get("external_id") == sha(SESSION))

    print("\n--- where the address comes from ---")
    # Cloudflare sits in front, so its header wins; the left-most hop of
    # X-Forwarded-For is next; and a header that is not an address is not
    # believed at all, because these are strings anybody can set.
    for label, headers, want in (
            ("Cloudflare's header wins",
             {"CF-Connecting-IP": IP,
              "X-Forwarded-For": "198.51.100.7, 10.0.0.1"}, IP),
            ("the first hop of X-Forwarded-For, without it",
             {"X-Forwarded-For": "198.51.100.7, 10.0.0.1"}, "198.51.100.7"),
            ("an IPv6 address survives",
             {"CF-Connecting-IP": "2001:db8::42"}, "2001:db8::42"),
            # Not None: the socket is the last resort and it is a real
            # address. What matters is that neither unparseable header was
            # believed — they are strings anybody can set, on their way to a
            # third party.
            ("a header that is not an address falls through to the socket",
             {"CF-Connecting-IP": "not-an-ip",
              "X-Forwarded-For": "also-not"}, "127.0.0.1")):
        rig.context.clear()
        run(rig, "zodiac", cookies={}, headers=dict(headers,
                                                    **{"User-Agent": UA}))
        got = rig.user_data().get("client_ip_address")
        check("  %s" % label, got == want, "%r, want %r" % (got, want))

    print("\n--- a User-Agent longer than anything real ---")
    rig.context.clear()
    run(rig, "zodiac", cookies={},
        headers={"User-Agent": "M" * 5000, "CF-Connecting-IP": IP})
    sent_ua = rig.user_data().get("client_user_agent") or ""
    check("is truncated here rather than by the column",
          len(sent_ua) == payments.UA_MAX, len(sent_ua))

    # --- d) the other product gets the same plumbing ------------------------

    print("\n--- kitchen gets the same enrichment ---")
    rig.context.clear()
    res, hook = run(rig, "kitchen",
                    cookies={"_fbp": FBP, "_fbc": FBC},
                    headers={"User-Agent": UA, "CF-Connecting-IP": IP})
    check("its checkout answers as it always did", res.status_code == 200,
          res.status_code)
    ud = rig.user_data()
    check("  and its Purchase carries the same six fields",
          set(ud) == {"em", "external_id", "fbp", "fbc",
                      "client_ip_address", "client_user_agent"},
          str(sorted(ud)))
    check("  with no kitchen quiz content on it",
          not (({str(v) for _p, v in walk(rig.capi[-1]["payload"])})
               & {"modern_rustic", "warm", "wood"}))
    check("  and its product name is untouched by any of this",
          rig.stripe_kwargs["line_items"][0]["price_data"]["product_data"]
          ["name"] == (config.load_funnel("kitchen")["checkout"]
                       ["product_name"]),
          rig.stripe_kwargs["line_items"][0]["price_data"]["product_data"]
          ["name"][:50])

    print("\n--- an older purchase, from before the table existed ---")
    rig.context.clear()          # nothing was ever captured for this session
    rig.capi = []
    rig.webhook("zodiac")
    ud = rig.user_data()
    check("still sends what it can", len(rig.capi) == 1, len(rig.capi))
    check("  with no address and no device",
          "client_ip_address" not in ud and "client_user_agent" not in ud,
          str(sorted(ud)))
    check("  and external_id regardless, because it rides in metadata",
          ud.get("external_id") == sha(SESSION))
finally:
    rig.restore()

# --- e) the browser end of the same identifier ------------------------------

print("\n--- and the pixel declares it too ---")
engine = open(os.path.join(REPO, "static/js/engine.js"),
              encoding="utf-8").read()
init = re.search(r'window\.fbq\("init"[^\n]*\n', engine)
check("fbq init carries advanced matching", bool(init),
      engine[engine.find('window.fbq("init"'):][:80])
check("  and the one field on it is external_id",
      init and "external_id: sessionId" in init.group(0), init and
      init.group(0).strip())
check("  guarded, so a page with no session id declares nothing",
      init and "sessionId ?" in init.group(0), init and init.group(0).strip())
check("no other advanced-matching field is declared",
      not re.search(r'fbq\("init"[^)]*\b(em|ph|fn|ln|ct|st|zp|db|ge)\s*:',
                    engine),
      "an identifier other than external_id is declared at init")
check("the value is the same session id the events carry",
      "body = { funnel: slug, session_id: sessionId" in engine)
check("  and it is set before the pixel starts",
      engine.index("sessionId = getSessionId();")
      < engine.index("startPixel();"))

print("\n%d checks, %d failed" % (checks[0], len(fails)))
for line in fails:
    print("  FAIL " + line)
sys.exit(1 if fails else 0)
