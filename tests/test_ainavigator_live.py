#!/usr/bin/env python3
"""/ai-navigator takes real money: the payment path, end to end, on the server.

No database, no Stripe, no Meta: the purchases table is a list in this file,
the webhook is signed here with a made-up secret, and every outbound request
is recorded instead of sent.

What is held to:

  - the funnel is live and its sandbox twin is test, by payments' own
    function; each transacts on its own key set; both charge 600 usd;
  - the twin is the funnel with three fields changed, the pixel block
    included, and is on disk in both places;
  - a confirmed live payment writes `livemode = 1` on its row, sends one
    Purchase to the funnel's pixel and lets /api/report hand the page what
    the browser's Purchase is built from;
  - a test payment writes 0 and produces neither; a row that says nothing
    (NULL) produces neither;
  - the same webhook event twice is one purchase, one report, one mail, one
    Purchase;
  - on a table that does not have the column yet, the purchase is recorded
    and the report delivered all the same;
  - a funnel with no pixel block is decided as it always was.

    python3 tests/test_ainavigator_live.py
"""
import hashlib
import hmac
import json
import os
import sys
import time
import types

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, REPO)

import pymysql.err                                         # noqa: E402

import config                                              # noqa: E402
import database                                            # noqa: E402
import payments                                            # noqa: E402
import reports                                             # noqa: E402
from app import app                                        # noqa: E402

SLUG = "ai-navigator"
TWIN = "ai-navigator-test"
PIXEL = "762004311984135"
ENV = "META_CAPI_TOKEN_VISYMO"
LIVE_SECRET = "whsec_live_notreal"
TEST_SECRET = "whsec_test_notreal"
SESSION = "0f8fad5b-d9cb-469f-a165-70867728950e"
EMAIL = "reader@example.com"

fails = []
checks = [0]


def check(label, ok, detail=""):
    checks[0] += 1
    if not ok:
        fails.append("%s %s" % (label, detail))
    print("  %-66s %s%s" % (label, "ok" if ok else "FAIL",
                            ("  " + str(detail)[:400]) if not ok else ""))


class Rig:
    """The purchases table, Stripe's signature and Meta, in memory."""

    def __init__(self, column=True):
        self.column = column          # whether purchases.livemode exists
        self.rows = []                # the purchases table
        self.sql = []                 # every write, in order
        self.capi = []
        self.started = []             # reports.start_report calls
        self.mails = []
        self.logs = []

    def _execute(self, sql, params=None):
        self.sql.append(sql)
        if sql == payments.INSERT_PURCHASE_SQL:
            (funnel, session_id, event_id, intent, cs, cents, currency,
             email, country, style, status) = params
            for row in self.rows:
                if row["stripe_event_id"] == event_id or (
                        intent and row["payment_intent"] == intent):
                    raise pymysql.err.IntegrityError(1062, "Duplicate entry")
            self.rows.append({
                "id": 100 + len(self.rows), "funnel": funnel,
                "session_id": session_id, "stripe_event_id": event_id,
                "payment_intent": intent, "checkout_session": cs,
                "amount_cents": cents, "currency": currency, "email": email,
                "country": country, "result_style": style, "status": status,
                "livemode": None})
            return self.rows[-1]["id"]
        if sql == payments.MARK_LIVEMODE_SQL:
            if not self.column:
                raise pymysql.err.OperationalError(
                    1054, "Unknown column 'livemode' in 'field list'")
            for row in self.rows:
                if row["id"] == params[1]:
                    row["livemode"] = params[0]
            return 0
        return 1

    def _query_one(self, sql, params=None):
        if sql == payments.SELECT_PURCHASE_SQL:
            for row in self.rows:
                if params[0] in (row["checkout_session"],
                                 row["payment_intent"]):
                    return dict(row)
            return None
        if sql == payments.SELECT_PURCHASE_AMOUNT_SQL:
            if not self.column:
                raise pymysql.err.OperationalError(
                    1054, "Unknown column 'livemode' in 'field list'")
            for row in self.rows:
                if row["id"] == params[0]:
                    return dict(row)
            return None
        if sql == payments.SELECT_REPORT_SQL:
            if [s for s in self.started if s[0] == params[0]]:
                return {"content": {"version": "llm-2", "sections": []}}
            return None
        return None

    def _post(self, url, json=None, params=None, timeout=None):
        self.capi.append({"url": url, "params": params, "payload": json})
        return types.SimpleNamespace(status_code=200)

    def _start_report(self, purchase_id, slug, style, scores, on_final=None,
                      **kw):
        self.started.append((purchase_id, slug, style))
        if on_final:
            on_final({"version": "llm-2"})
        return {"version": "llm-2"}

    def __enter__(self):
        self.real = (database.execute, database.query_one,
                     database.query_all, reports.start_report,
                     reports.send_report_email, reports.delivered_content,
                     config.STRIPE_SECRET_KEY, config.STRIPE_TEST_SECRET_KEY,
                     config.STRIPE_WEBHOOK_SECRET,
                     config.STRIPE_TEST_WEBHOOK_SECRET, config.META_PIXEL_ID,
                     config.META_CAPI_TOKEN, config.META_TEST_EVENT_CODE,
                     payments.log, sys.modules.get("requests"),
                     os.environ.get(ENV),
                     payments._livemode_unavailable_logged)
        database.execute = self._execute
        database.query_one = self._query_one
        database.query_all = lambda *a, **kw: []
        reports.start_report = self._start_report
        reports.send_report_email = lambda *a, **kw: self.mails.append(a[0])
        reports.delivered_content = lambda content, email: {"sections": []}
        config.STRIPE_SECRET_KEY = "sk_live_notreal"
        config.STRIPE_TEST_SECRET_KEY = "sk_test_notreal"
        config.STRIPE_WEBHOOK_SECRET = LIVE_SECRET
        config.STRIPE_TEST_WEBHOOK_SECRET = TEST_SECRET
        config.META_PIXEL_ID = "111222333"
        config.META_CAPI_TOKEN = "tok_default_notreal"
        config.META_TEST_EVENT_CODE = ""
        os.environ[ENV] = "tok_visymo_notreal"
        payments._livemode_unavailable_logged = False
        stub = types.ModuleType("requests")
        stub.post = self._post
        sys.modules["requests"] = stub
        rig = self

        class Recorder:
            def _keep(self, template, *args):
                try:
                    rig.logs.append(str(template) % args if args
                                    else str(template))
                except Exception:
                    rig.logs.append("%s %s" % (template, args))
            info = warning = error = exception = debug = _keep

        payments.log = Recorder()
        return self

    def __exit__(self, *exc):
        (database.execute, database.query_one, database.query_all,
         reports.start_report, reports.send_report_email,
         reports.delivered_content, config.STRIPE_SECRET_KEY,
         config.STRIPE_TEST_SECRET_KEY, config.STRIPE_WEBHOOK_SECRET,
         config.STRIPE_TEST_WEBHOOK_SECRET, config.META_PIXEL_ID,
         config.META_CAPI_TOKEN, config.META_TEST_EVENT_CODE, payments.log,
         requests_module, token,
         payments._livemode_unavailable_logged) = self.real
        if requests_module is None:
            sys.modules.pop("requests", None)
        else:
            sys.modules["requests"] = requests_module
        if token is None:
            os.environ.pop(ENV, None)
        else:
            os.environ[ENV] = token

    def webhook(self, slug, intent, live=True, event_id=None, secret=None,
                say=True):
        """A `payment_intent.succeeded`, signed as Stripe would sign it."""
        cfg = config.load_funnel(slug)
        event = {
            "id": event_id or "evt_" + intent,
            "type": "payment_intent.succeeded",
            "created": 1700000000,
            "data": {"object": {
                "id": intent, "object": "payment_intent",
                "amount": cfg["pricing"]["amount_cents"],
                "amount_received": cfg["pricing"]["amount_cents"],
                "currency": cfg["pricing"]["currency"],
                "latest_charge": {"billing_details": {
                    "email": EMAIL, "address": {"country": "US"}}},
                "metadata": {"funnel": slug, "session_id": SESSION,
                             "result_style": cfg["styles"][0]["id"],
                             "fbp": "fb.1.1.2"},
            }},
        }
        if say:
            event["livemode"] = live
            event["data"]["object"]["livemode"] = live
        payload = json.dumps(event)
        stamp = int(time.time())
        secret = secret or (LIVE_SECRET if live else TEST_SECRET)
        mac = hmac.new(secret.encode(),
                       ("%d.%s" % (stamp, payload)).encode(),
                       hashlib.sha256).hexdigest()
        with app.test_client() as client:
            return client.post(
                "/api/stripe/webhook", data=payload,
                headers={"Stripe-Signature": "t=%d,v1=%s" % (stamp, mac),
                         "Content-Type": "application/json"})

    def report(self, token):
        with app.test_client() as client:
            got = client.get("/api/report?cs=" + token)
            return got.status_code, got.get_json()

    def row(self, intent):
        return [r for r in self.rows if r["payment_intent"] == intent][0]


requests_module = token = None       # names __exit__ unpacks into


def load(slug):
    return config.load_funnel(slug)


print("\n--- live, and a twin that is not ---")
with Rig() as rig:
    src = load(SLUG)
    twin = load(TWIN)
    check("the funnel's config asks for live, the twin's for test",
          src["stripe_mode"] == "live" and twin["stripe_mode"] == "test")
    check("payments' own function agrees: live, and test for the twin",
          payments.effective_mode(SLUG) == payments.LIVE
          and payments.effective_mode(TWIN) == payments.TEST,
          [payments.effective_mode(SLUG), payments.effective_mode(TWIN)])
    check("  so the funnel transacts on the live key and the twin on the "
          "test key",
          payments._stripe_secret(payments.effective_mode(SLUG))
          == "sk_live_notreal"
          and payments._stripe_secret(payments.effective_mode(TWIN))
          == "sk_test_notreal")
    check("the effective price is 600 usd on both, with no sale",
          payments._effective_price(src) == (600, None)
          and payments._effective_price(twin) == (600, None)
          and src["pricing"]["currency"] == "usd"
          and "sale" not in src["pricing"] and "sale" not in src,
          payments._effective_price(src))
    check("the withdrawal consent is off, as it was",
          src["checkout"].get("withdrawal_consent") is False)
    diff = sorted(k for k in set(src) | set(twin)
                  if src.get(k) != twin.get(k))
    check("the twin is the funnel with three fields changed",
          diff == ["funnel_id", "slug", "stripe_mode"]
          and twin["slug"] == TWIN
          and twin["funnel_id"] == src["funnel_id"] + "_test"
          and list(twin) == list(src), diff)
    check("  the same pixel block, so it initialises the same pixel",
          twin["pixel"] == src["pixel"]
          and payments.funnel_pixel(TWIN)["id"] == PIXEL)
    for name in (SLUG, TWIN):
        a = open(os.path.join(REPO, "funnels", name + ".json")).read()
        b = open(os.path.join(REPO, "static", "funnels",
                              name + ".json")).read()
        check("  %s is on disk twice, the same bytes" % name, a == b)
    check("no other funnel's mode moved",
          dict((n[:-5], json.load(open(os.path.join(REPO, "funnels", n)))
                .get("stripe_mode")) for n in ("focus.json", "kitchen.json",
                                               "zodiac.json", "brain.json",
                                               "persona.json"))
          == {"focus": "test", "kitchen": None, "zodiac": "live",
              "brain": "test", "persona": "test"})

print("\n--- a confirmed live payment ---")
with Rig() as rig:
    res = rig.webhook(SLUG, "pi_3Live0001")
    row = rig.row("pi_3Live0001")
    check("the webhook answers ok and writes one paid row for 600 usd",
          res.status_code == 200 and res.get_json() == {"status": "ok"}
          and len(rig.rows) == 1 and row["amount_cents"] == 600
          and row["currency"] == "usd" and row["status"] == "paid"
          and row["checkout_session"] is None, res.get_json())
    check("  the insert is the statement it always was, then the mark",
          rig.sql[0] == payments.INSERT_PURCHASE_SQL
          and rig.sql[1] == payments.MARK_LIVEMODE_SQL
          and "livemode" not in payments.INSERT_PURCHASE_SQL, rig.sql[:2])
    check("the row says livemode 1", row["livemode"] == 1, row["livemode"])
    check("one Purchase to the funnel's own pixel, with its own token",
          len(rig.capi) == 1 and PIXEL in rig.capi[0]["url"]
          and rig.capi[0]["params"] == {"access_token": "tok_visymo_notreal"},
          rig.capi)
    sent = rig.capi and rig.capi[0]["payload"]["data"][0]
    check("  event_id the payment intent, value 6.0 usd",
          sent and sent["event_name"] == "Purchase"
          and sent["event_id"] == "pi_3Live0001"
          and sent["custom_data"] == {"value": 6.0, "currency": "usd"},
          sent)
    check("one report started, one mail",
          len(rig.started) == 1 and rig.mails == [row["id"]],
          [rig.started, rig.mails])
    status, body = rig.report("pi_3Live0001")
    check("the page is handed what the browser's Purchase is built from",
          status == 200 and body.get("status") == "ready"
          and body.get("purchase") == {"event_id": "pi_3Live0001",
                                       "value": "6.00", "currency": "USD"},
          body)
    check("no address and no token in any log line",
          not [l for l in rig.logs if EMAIL in l or "notreal" in l], rig.logs)

    print("\n--- the same event again ---")
    again = rig.webhook(SLUG, "pi_3Live0001")
    check("answered duplicate, 200",
          again.status_code == 200
          and again.get_json() == {"status": "duplicate"}, again.get_json())
    check("no second row, report, mail or Purchase",
          len(rig.rows) == 1 and len(rig.started) == 1
          and len(rig.mails) == 1 and len(rig.capi) == 1,
          [len(rig.rows), len(rig.started), len(rig.mails), len(rig.capi)])
    check("  and the row is not written to a second time",
          rig.sql.count(payments.MARK_LIVEMODE_SQL) == 1
          and rig.row("pi_3Live0001")["livemode"] == 1)
    other = rig.webhook(SLUG, "pi_3Live0001", event_id="evt_second_event")
    check("the same payment under a second event id: duplicate too",
          other.get_json() == {"status": "duplicate"} and len(rig.rows) == 1
          and len(rig.capi) == 1 and len(rig.started) == 1)

print("\n--- a test payment ---")
with Rig() as rig:
    res = rig.webhook(TWIN, "pi_3Test0002", live=False)
    row = rig.row("pi_3Test0002")
    check("recorded and delivered like any purchase",
          res.get_json() == {"status": "ok"} and len(rig.started) == 1
          and row["funnel"] == TWIN and row["amount_cents"] == 600)
    check("the row says livemode 0", row["livemode"] == 0, row["livemode"])
    check("no Purchase to any pixel", rig.capi == [], rig.capi)
    status, body = rig.report("pi_3Test0002")
    check("the report is ready and carries no purchase block",
          status == 200 and body.get("status") == "ready"
          and "purchase" not in body, body)

    # A test payment on the LIVE funnel's slug: what a purchase made before
    # the switch looks like when Stripe retries it, or a mode override.
    res = rig.webhook(SLUG, "pi_3Test0003", live=False)
    row = rig.row("pi_3Test0003")
    check("a test payment on the live funnel: 0 on the row, no Purchase",
          res.get_json() == {"status": "ok"} and row["livemode"] == 0
          and rig.capi == [] and "purchase" not in rig.report(
              "pi_3Test0003")[1])

print("\n--- a row that does not say ---")
with Rig() as rig:
    rig.rows.append({
        "id": 7, "funnel": SLUG, "session_id": SESSION,
        "stripe_event_id": "evt_old", "payment_intent": "pi_3Old0004",
        "checkout_session": None, "amount_cents": 600, "currency": "usd",
        "email": EMAIL, "country": "US", "result_style": "builder",
        "status": "paid", "livemode": None})
    rig.started.append((7, SLUG, "builder"))
    status, body = rig.report("pi_3Old0004")
    check("a purchase from before the column (NULL): delivered, no Purchase",
          status == 200 and body.get("status") == "ready"
          and "purchase" not in body, body)
    rig.rows[0]["livemode"] = 0
    check("  and the same at 0", "purchase" not in rig.report(
        "pi_3Old0004")[1])
    rig.rows[0]["livemode"] = 1
    check("  and only a 1 turns it on", rig.report("pi_3Old0004")[1].get(
        "purchase", {}).get("event_id") == "pi_3Old0004")
    check("  no existing row was deleted or rewritten by any of that",
          not [s for s in rig.sql if "DELETE" in s.upper()
               or "UPDATE" in s.upper()], rig.sql)

    res = rig.webhook(SLUG, "pi_3Mute0005", say=False)
    row = rig.row("pi_3Mute0005")
    check("an event that does not say livemode: NULL on the row",
          res.get_json() == {"status": "ok"} and row["livemode"] is None
          and payments.MARK_LIVEMODE_SQL not in rig.sql)
    check("  recorded and delivered, and no Purchase for this funnel",
          len(rig.started) == 2 and rig.capi == []
          and "purchase" not in rig.report("pi_3Mute0005")[1], rig.capi)

print("\n--- before the column exists ---")
with Rig(column=False) as rig:
    res = rig.webhook(SLUG, "pi_3Live0006")
    check("the purchase is still recorded, and the webhook still says ok",
          res.status_code == 200 and res.get_json() == {"status": "ok"}
          and len(rig.rows) == 1
          and rig.row("pi_3Live0006")["status"] == "paid", res.get_json())
    check("the report is started and the mail goes out",
          len(rig.started) == 1 and len(rig.mails) == 1)
    status, body = rig.report("pi_3Live0006")
    check("the report is delivered",
          status == 200 and body.get("status") == "ready"
          and "report" in body, body)
    check("no Purchase, server or browser, until the column is there",
          rig.capi == [] and "purchase" not in body)
    check("one warning that names the migration, and nothing about the buyer",
          len([l for l in rig.logs if "schema_migrations.sql" in l]) == 1
          and not [l for l in rig.logs if EMAIL in l], rig.logs)
    rig.webhook(SLUG, "pi_3Live0007")
    check("  said once a process, not once a purchase",
          len([l for l in rig.logs if "schema_migrations.sql" in l]) == 1
          and len(rig.rows) == 2 and len(rig.started) == 2)
    again = rig.webhook(SLUG, "pi_3Live0006")
    check("a repeated event is still a duplicate",
          again.get_json() == {"status": "duplicate"} and len(rig.rows) == 2
          and len(rig.started) == 2)
    res = rig.webhook("kitchen", "pi_3Kitchen08")
    check("kitchen, column or no column: recorded, and its Purchase is sent",
          res.get_json() == {"status": "ok"} and len(rig.capi) == 1
          and "111222333" in rig.capi[0]["url"]
          and rig.capi[0]["params"] == {"access_token":
                                        "tok_default_notreal"}, rig.capi)

print("\n--- a funnel with no pixel block ---")
with Rig() as rig:
    res = rig.webhook("kitchen", "pi_3Kitchen09")
    check("a live kitchen payment: the default pixel, as ever, and a 1",
          res.get_json() == {"status": "ok"} and len(rig.capi) == 1
          and "111222333" in rig.capi[0]["url"]
          and rig.row("pi_3Kitchen09")["livemode"] == 1)
    res = rig.webhook("kitchen", "pi_3Kitchen10", say=False)
    check("  one that does not say livemode is still sent, as it always was",
          len(rig.capi) == 2 and rig.row("pi_3Kitchen10")["livemode"] is None)
    res = rig.webhook("kitchen", "pi_3Kitchen11", live=False)
    check("  a test one is not, and is marked 0",
          len(rig.capi) == 2 and rig.row("pi_3Kitchen11")["livemode"] == 0)
    check("  and /api/report never grows a purchase block for it",
          "purchase" not in rig.report("pi_3Kitchen09")[1])

print("\n--- the migration ---")
MIGRATIONS = open(os.path.join(REPO, "schema_migrations.sql")).read()
MAIN_TAIL = "  INDEX idx_loan_lead_created (created_at)\n);\n"
check("one statement, appended after everything that was there",
      MIGRATIONS.rstrip().endswith(
          "ALTER TABLE purchases ADD COLUMN livemode TINYINT(1) NULL;")
      and MIGRATIONS.count("livemode TINYINT") == 1
      and MIGRATIONS.index(MAIN_TAIL) < MIGRATIONS.index("ADD COLUMN livemode"))
check("  nullable, with no default and no backfill",
      "UPDATE purchases" not in MIGRATIONS.split("ADD COLUMN livemode")[0]
      .rsplit(MAIN_TAIL, 1)[1]
      and "DEFAULT" not in MIGRATIONS.rstrip().splitlines()[-1])
check("schema.sql is untouched by it",
      "livemode" not in open(os.path.join(REPO, "schema.sql")).read())

print("\n--- the Terms page ---")
TERMS = open(os.path.join(REPO, "static", "pages", "terms.html")).read()
flat = " ".join(TERMS.split())
check("a section for AI Navigator reports: educational, nothing promised",
      "AI Navigator reports</h2>" in TERMS
      and "educational content" in flat
      and "do not promise or guarantee any income, client, or result" in flat
      and "your own effort, your skills, and your market" in flat
      and "not financial, legal, or career advice" in flat)
check("a section for partner links: evoseekly.com, ads, its own terms",
      "Links to partner sites</h2>" in TERMS and "evoseekly.com" in flat
      and "shows advertisements" in flat
      and "We may earn money when visitors view or click those ads" in flat
      and "its own terms and privacy policy" in flat)
check("the entertainment wording for the style funnels is as it was",
      "<strong>Our quizzes and reports are provided for entertainment and "
      "self-discovery purposes only.</strong>" in flat)
check("sixteen sections, numbered in order, Contact last",
      [int(h.split(".")[0]) for h in
       __import__("re").findall(r"<h2>(\d+\. [^<]+)</h2>", TERMS)]
      == list(range(1, 17)) and "<h2>16. Contact</h2>" in TERMS)

print("\n%d checks, %d failed" % (checks[0], len(fails)))
for line in fails:
    print("  FAIL " + line[:420])
sys.exit(1 if fails else 0)
