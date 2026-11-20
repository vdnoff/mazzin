#!/usr/bin/env python3
"""The /ai-navigator funnel's own Meta pixel.

The funnel names a pixel in its config (`pixel`: an id, the NAME of the
variable its Conversions API token is in, and the events it may send). That
pixel replaces the default one on this funnel and on no other.

The server half, with no database and no network:

  - /api/pixel-config answers this funnel's id when asked by slug, and
    answers every other funnel what it always did;
  - the Purchase goes to this pixel with this token under the payment
    intent's id; with the variable unset there is no call, no error and no
    borrowing of the default token; in test mode there is no call;
  - a kitchen purchase is the default pixel, the default token and the
    payload it has always been;
  - /api/report hands the page the three fields a browser Purchase needs,
    for a confirmed live purchase on this funnel and for nothing else.

The browser half, with Meta's script replaced by a recorder:

  - the pixel is initialised with this funnel's id and never the default;
  - PageView, then exactly one Lead, at the free result; walking the quiz
    again in the same tab adds no second Lead;
  - no ViewContent and no InitiateCheckout anywhere, an article tap and a pay
    tap included;
  - on the delivered page, one Purchase for a confirmed live purchase, with
    the amount charged and eventID = the payment intent; a reload adds none;
    a test purchase fires none.

    python3 tests/test_ainavigator_pixel.py
"""
import json
import logging
import os
import sys
import threading

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, REPO)
sys.path.insert(0, os.path.join(REPO, "tests"))

os.environ.pop("META_CAPI_TOKEN_VISYMO", None)

import config                                              # noqa: E402
import database                                            # noqa: E402

# No suite talks to a database.
database.execute = lambda *a, **kw: None
database.query_all = lambda *a, **kw: []
database.query_one = lambda *a, **kw: None

import payments                                            # noqa: E402
import reports                                             # noqa: E402
import requests                                            # noqa: E402
import test_ainavigator_rsoc as walk                       # noqa: E402
from app import app                                        # noqa: E402

from playwright.sync_api import sync_playwright            # noqa: E402

PORT = 8873
BASE = "http://127.0.0.1:%d" % PORT
CFG = walk.CFG
PIXEL = "762004311984135"
DEFAULT = "111222333444"
ENV = "META_CAPI_TOKEN_VISYMO"
FAKE = "fake-visymo-token-0001"
PI_LIVE = "pi_3LiveFixture0001"
PI_TEST = "pi_3TestFixture0002"
TAIL = "?fbclid=AbC_123-x&ad_id=111&asid=222"

fails = []
checks = [0]


def check(label, ok, detail=""):
    checks[0] += 1
    if not ok:
        fails.append("%s %s" % (label, detail))
    print("  %-66s %s%s" % (label, "ok" if ok else "FAIL",
                            ("  " + str(detail)[:400]) if not ok else ""))


# --- the server half --------------------------------------------------------

class Records(logging.Handler):
    def __init__(self):
        super().__init__(level=logging.DEBUG)
        self.lines = []

    def emit(self, record):
        self.lines.append((record.levelname, record.getMessage()))


class Reply:
    status_code = 200


def server_half():
    print("\n--- the config block ---")
    check("the funnel names its pixel, the token's variable, three events",
          CFG.get("pixel") == {"id": PIXEL, "capi_token_env": ENV,
                               "events": ["PageView", "Lead", "Purchase"]},
          CFG.get("pixel"))
    own = payments.funnel_pixel("ai-navigator")
    check("payments reads it", own == {
        "id": PIXEL, "token_env": ENV,
        "events": frozenset(("PageView", "Lead", "Purchase"))}, own)
    check("  a block with a bad id is no block",
          payments.funnel_pixel("x", {"pixel": {"id": "abc"}}) is None
          and payments.funnel_pixel("x", {"pixel": {"id": "1234"}}) is None
          and payments.funnel_pixel("x", {"pixel": "762004311984135"}) is None
          and payments.funnel_pixel("x", {}) is None)
    check("  ViewContent is dropped whatever the block lists",
          payments.funnel_pixel("x", {"pixel": {
              "id": PIXEL, "events": ["ViewContent", "Lead"]}})["events"]
          == frozenset(("Lead",)))
    check("  a variable that is not one of ours names nothing",
          payments.funnel_pixel("x", {"pixel": {
              "id": PIXEL, "capi_token_env": "STRIPE_SECRET_KEY"}})
          ["token_env"] == "")
    check("kitchen, focus and zodiac have no pixel of their own",
          [payments.funnel_pixel(s) for s in ("kitchen", "focus", "zodiac")]
          == [None, None, None])

    print("\n--- /api/pixel-config ---")
    client = app.test_client()
    config.META_PIXEL_ID = DEFAULT
    config.META_CAPI_TOKEN = "default-token"
    config.META_TEST_EVENT_CODE = ""
    bare = client.get("/api/pixel-config")
    mine = client.get("/api/pixel-config?slug=ai-navigator")
    check("asked by slug, ai-navigator is answered its own id",
          mine.get_json() == {"pixel_id": PIXEL}, mine.get_json())
    check("  with the same cache header, and no token in the answer",
          mine.headers.get("Cache-Control")
          == bare.headers.get("Cache-Control")
          and sorted(mine.get_json()) == ["pixel_id"])
    check("the bare URL is the default id, as it was",
          bare.get_json() == {"pixel_id": DEFAULT}
          and bare.headers.get("Cache-Control") == "public, max-age=%d"
          % config.PIXEL_CONFIG_MAX_AGE, bare.get_json())
    for slug in ("kitchen", "focus", "zodiac"):
        got = client.get("/api/pixel-config?slug=" + slug)
        check("  %s by slug is byte for byte the bare answer" % slug,
              got.data == bare.data
              and dict(got.headers) == dict(bare.headers), got.data)
    for bad in ("nope", "../etc", "AI-NAVIGATOR", ""):
        got = client.get("/api/pixel-config?slug=" + bad)
        check("  %r is the bare answer too" % bad, got.data == bare.data)
    config.META_PIXEL_ID = ""
    check("with no default pixel: null for kitchen, the id for ai-navigator",
          client.get("/api/pixel-config").get_json() == {"pixel_id": None}
          and client.get("/api/pixel-config?slug=kitchen").get_json()
          == {"pixel_id": None}
          and client.get("/api/pixel-config?slug=ai-navigator").get_json()
          == {"pixel_id": PIXEL})
    config.META_PIXEL_ID = DEFAULT

    print("\n--- the server's Purchase ---")
    calls = []

    def post(url, json=None, params=None, timeout=None):
        calls.append({"url": url, "json": json, "params": params,
                      "timeout": timeout})
        return Reply()

    real_post = requests.post
    real_mode = payments.effective_mode
    requests.post = post
    mode = {"ai-navigator": payments.LIVE}
    payments.effective_mode = lambda slug, cfg=None: mode.get(
        slug, payments.LIVE)
    seen = Records()
    payments.log.addHandler(seen)
    level = payments.log.level
    payments.log.setLevel(logging.DEBUG)

    def purchase(slug, intent=PI_LIVE):
        del calls[:]
        del seen.lines[:]
        return payments.send_purchase_event(
            41, slug, 600, "usd", email=" Reader@Example.com ",
            payment_intent=intent, meta_ids={"fbp": "fb.1.1.2",
                                             "fbc": "fb.1.3.4"},
            event_time=1700000000,
            session_id="0f8fad5b-d9cb-469f-a165-70867728950e",
            client_ip="203.0.113.9", client_ua="UA/1")

    def body(slug, intent=PI_LIVE):
        return {"data": [{
            "event_name": "Purchase", "event_time": 1700000000,
            "event_id": intent, "action_source": "website",
            "event_source_url": "%s/%s" % (config.BASE_URL, slug),
            "user_data": {
                "em": [payments._sha256("reader@example.com")],
                "external_id": payments._sha256(
                    "0f8fad5b-d9cb-469f-a165-70867728950e"),
                "client_ip_address": "203.0.113.9",
                "client_user_agent": "UA/1",
                "fbp": "fb.1.1.2", "fbc": "fb.1.3.4"},
            "custom_data": {"value": 6.0, "currency": "usd"}}]}

    os.environ[ENV] = FAKE
    sent = purchase("ai-navigator")
    check("with the variable set: one call, to this pixel",
          sent is True and len(calls) == 1
          and calls[0]["url"] == "https://graph.facebook.com/%s/%s/events"
          % (config.META_API_VERSION, PIXEL), calls and calls[0]["url"])
    check("  with this token and not the default one",
          calls and calls[0]["params"] == {"access_token": FAKE})
    check("  event_id is the payment intent; the payload is today's shape",
          calls and calls[0]["json"] == body("ai-navigator"),
          calls and calls[0]["json"])
    check("  the token is in no log line",
          not [l for l in seen.lines if FAKE in l[1]], seen.lines)

    config.META_TEST_EVENT_CODE = "TEST123"
    purchase("ai-navigator")
    check("  the default pixel's test event code does not ride along",
          calls and "test_event_code" not in calls[0]["json"])
    config.META_TEST_EVENT_CODE = ""

    for label, value in (("unset", None), ("empty", ""), ("blank", "  ")):
        if value is None:
            os.environ.pop(ENV, None)
        else:
            os.environ[ENV] = value
        sent = purchase("ai-navigator")
        info = [l for l in seen.lines if l[0] == "INFO" and ENV in l[1]]
        check("with the variable %s: no call, no error, one INFO line"
              % label, sent is False and calls == [] and len(info) == 1
              and not [l for l in seen.lines if l[0] in ("WARNING", "ERROR")],
              [calls, seen.lines])
        check("  and the line holds no address and no token",
              info and "@" not in info[0][1]
              and "default-token" not in info[0][1], info)

    os.environ[ENV] = FAKE
    mode["ai-navigator"] = payments.TEST
    sent = purchase("ai-navigator")
    check("in test mode: no call, even with the token set",
          sent is False and calls == [], calls)
    mode["ai-navigator"] = payments.LIVE

    sent = purchase("kitchen")
    check("a kitchen purchase: the default pixel, the default token",
          sent is True and len(calls) == 1
          and calls[0]["url"] == "https://graph.facebook.com/%s/%s/events"
          % (config.META_API_VERSION, DEFAULT)
          and calls[0]["params"] == {"access_token": "default-token"}
          and calls[0]["timeout"] == config.META_TIMEOUT_S, calls)
    check("  and the payload it has always been",
          calls and calls[0]["json"] == body("kitchen"),
          calls and calls[0]["json"])
    os.environ.pop(ENV, None)
    sent = purchase("kitchen")
    check("  whether or not the other funnel's variable is set",
          sent is True and len(calls) == 1
          and calls[0]["json"] == body("kitchen"))

    print("\n--- the pixel events' server twins ---")
    os.environ[ENV] = FAKE

    def twin(slug, name):
        del calls[:]
        return payments.send_pixel_event(
            name, "0f8fad5b-d9cb-469f-a165-70867728950e", slug,
            "1f8fad5b-d9cb-469f-a165-70867728950e", client_ip="203.0.113.9",
            client_ua="UA/1", meta_ids={"fbp": "fb.1.1.2"},
            event_time=1700000000)

    check("Lead goes to this pixel with this token",
          twin("ai-navigator", "Lead") is True and len(calls) == 1
          and PIXEL in calls[0]["url"]
          and calls[0]["params"] == {"access_token": FAKE}, calls)
    check("InitiateCheckout and AddPaymentInfo go nowhere for this funnel",
          twin("ai-navigator", "InitiateCheckout") is False and calls == []
          and twin("ai-navigator", "AddPaymentInfo") is False
          and calls == [])
    os.environ.pop(ENV, None)
    check("with the variable unset the twin is not sent, to either pixel",
          twin("ai-navigator", "Lead") is False and calls == [])
    check("kitchen's twins are the default pixel's, all four",
          all(twin("kitchen", n) is True and DEFAULT in calls[0]["url"]
              and calls[0]["params"] == {"access_token": "default-token"}
              for n in ("PageView", "Lead", "InitiateCheckout",
                        "AddPaymentInfo")))

    print("\n--- /api/report: what the browser's Purchase is built from ---")
    row = {"amount_cents": 600, "currency": "usd",
           "payment_intent": PI_LIVE, "checkout_session": None}
    bought = {"id": 41, "funnel": "ai-navigator", "session_id": "s",
              "result_style": "builder", "status": "paid",
              "email": "reader@example.com"}
    real = (payments.find_purchase, database.query_one,
            reports.delivered_content)
    payments.find_purchase = lambda token: dict(bought)

    def query_one(sql, args=None):
        if sql == payments.SELECT_REPORT_SQL:
            return {"content": {"version": "1", "sections": []}}
        if sql == payments.SELECT_PURCHASE_AMOUNT_SQL:
            return dict(row)
        raise AssertionError(sql)

    database.query_one = query_one
    reports.delivered_content = lambda content, email: {"sections": []}

    def report():
        return client.get("/api/report?cs=" + PI_LIVE).get_json()

    got = report()
    check("a confirmed live purchase: the intent, 6.00, USD",
          got.get("status") == "ready" and got.get("purchase") == {
              "event_id": PI_LIVE, "value": "6.00", "currency": "USD"}, got)
    check("  and nothing else about the buyer in that block",
          sorted(got.get("purchase") or {}) == ["currency", "event_id",
                                                "value"])
    row["amount_cents"] = 450
    check("  the value is what was charged, not the config's price",
          report().get("purchase", {}).get("value") == "4.50")
    row["amount_cents"] = 600
    mode["ai-navigator"] = payments.TEST
    check("the funnel in test mode: no purchase block",
          "purchase" not in report())
    mode["ai-navigator"] = payments.LIVE
    row["checkout_session"] = "cs_test_a1"
    check("a session Stripe marked as test: no purchase block",
          "purchase" not in report())
    row["checkout_session"] = None
    row["payment_intent"] = None
    check("no payment intent to name it by: no purchase block",
          "purchase" not in report())
    row["payment_intent"] = PI_LIVE
    bought["funnel"] = "kitchen"
    check("a kitchen purchase: no purchase block, and no extra query",
          "purchase" not in report())
    bought["funnel"] = "ai-navigator"
    payments.find_purchase = lambda token: None
    check("no purchase row yet: pending, and no purchase block",
          report() == {"status": "pending"})

    (payments.find_purchase, database.query_one,
     reports.delivered_content) = real
    requests.post = real_post
    payments.effective_mode = real_mode
    payments.log.removeHandler(seen)
    payments.log.setLevel(level)
    os.environ.pop(ENV, None)


# --- the browser half -------------------------------------------------------

# Meta's script, replaced. engine.js queues `init` and every `track` on its
# own stub and this drains them into sessionStorage, so the record survives a
# reload and the trip to the delivered page.
FBEVENTS = """
(function () {
  var f = window.fbq;
  if (!f) return;
  function keep(args) {
    var all = [];
    try { all = JSON.parse(sessionStorage.getItem('__fbq') || '[]'); }
    catch (e) {}
    all.push(args);
    sessionStorage.setItem('__fbq', JSON.stringify(all));
  }
  f.callMethod = function () { keep([].slice.call(arguments)); };
  var q = f.queue || [];
  while (q.length) f.callMethod.apply(f, q.shift());
})();
"""

state = {"report": None, "asked": []}
IMAGES = set(c["id"] for s in CFG["swipe"]["steps"]
             for p in s["pairs"] for c in p["images"])


class Handler(walk.Handler):
    def do_GET(self):
        path, _, query = self.path.partition("?")
        if path == "/api/pixel-config":
            state["asked"].append(self.path)
            if query == "slug=ai-navigator":
                return self._json({"pixel_id": PIXEL})
            return self._json({"pixel_id": DEFAULT})
        if path == "/api/report":
            if state["report"] is None:
                return self._json({"status": "pending"}, 202)
            body = {"status": "ready", "complete": True,
                    "email_masked": "r***@example.com",
                    "report": reports.delivered_content(
                        state["report"], "reader@example.com")}
            # What payments.report attaches for a confirmed live purchase,
            # and leaves off for a test one.
            if query == "cs=" + PI_LIVE:
                body["purchase"] = {"event_id": PI_LIVE, "value": "6.00",
                                    "currency": "USD"}
            return self._json(body)
        return super().do_GET()

    def do_POST(self):
        path = self.path.split("?")[0]
        if path == "/api/checkout":
            raw = self.rfile.read(int(self.headers.get("content-length")
                                      or 0))
            order = json.loads(raw)
            choices = [c for c in order.get("choices") or [] if c in IMAGES]
            state["report"] = reports.start_report(
                77, "ai-navigator", order.get("result_style"),
                order.get("tag_scores"), choices=choices)
            return self._json({"url": "%s/ai-navigator?cs=%s"
                                      % (BASE, PI_LIVE)})
        return super().do_POST()


def fbq(page):
    return page.evaluate(
        "() => JSON.parse(sessionStorage.getItem('__fbq') || '[]')")


def names(calls):
    return [c[1] for c in calls if c[0] in ("track", "trackCustom")]


def browser_half():
    server = walk.Server(("127.0.0.1", PORT), Handler)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    with sync_playwright() as pw:
        browser = pw.chromium.launch(executable_path=walk.CHROME)
        ctx = browser.new_context(viewport={"width": 390, "height": 844},
                                  is_mobile=True, has_touch=True)
        ctx.route(lambda url: not url.startswith(BASE), lambda r: r.abort())
        ctx.route("https://connect.facebook.net/en_US/fbevents.js",
                  lambda r: r.fulfill(status=200,
                                      content_type="text/javascript",
                                      body=FBEVENTS))
        page = ctx.new_page()
        errors = []
        page.on("pageerror", lambda e: errors.append(str(e)))

        print("\n--- the walk, to the free result ---")
        del walk.events[:]
        page.goto(BASE + "/ai-navigator" + TAIL)
        answered = walk.advance(page, until="time")
        page.wait_for_timeout(400)
        calls = fbq(page)
        inits = [c for c in calls if c[0] == "init"]
        check("the pixel is initialised once, with this funnel's id",
              len(inits) == 1 and inits[0][1] == PIXEL, inits)
        check("  with the session id and nothing else about the reader",
              inits and sorted(inits[0][2]) == ["external_id"], inits)
        check("  asked for by slug; the default id is never initialised",
              "/api/pixel-config?slug=ai-navigator" in state["asked"]
              and DEFAULT not in json.dumps(calls), state["asked"])
        check("PageView and nothing else while the quiz is being walked",
              names(calls) == ["PageView"], names(calls))
        answered += walk.advance(page)
        walk.wait_result(page)
        calls = fbq(page)
        check("twelve steps, to the result", len(answered) == 12,
              len(answered))
        check("exactly one Lead, at the result page",
              names(calls) == ["PageView", "Lead"], names(calls))
        lead = [c for c in calls if c[1] == "Lead"]
        check("  with no parameters and its event id",
              lead and lead[0][2] == {} and sorted(lead[0][3]) == ["eventID"],
              lead)
        views = [e for e in walk.events if e.get("event") == "result_view"]
        check("  the result_view of that moment carries the same id",
              len(views) == 1 and lead
              and views[0].get("pixel_event_id") == lead[0][3]["eventID"],
              views)
        check("  an offer card and a guides card are on that page",
              page.locator("#result-module .ai-offer").count() == 1
              and page.locator("#result-module .ai-rsoc").count() == 1)

        print("\n--- the same tab again: a reload, the quiz, the result ---")
        page.reload()
        walk.advance(page)
        walk.wait_result(page)
        calls = fbq(page)
        check("a second PageView, and no second Lead",
              names(calls) == ["PageView", "Lead", "PageView"], names(calls))
        views = [e for e in walk.events if e.get("event") == "result_view"]
        check("  the second result_view carries no pixel id to mirror",
              len(views) == 2 and "pixel_event_id" not in views[1], views)

        print("\n--- an article tap, then a pay tap ---")
        with ctx.expect_page() as popup:
            page.locator(".ai-rsoc-link").first.click()
        popup.value.close()
        page.wait_for_timeout(600)
        check("the article tap is tracked, and fires nothing on the pixel",
              [e for e in walk.events if e.get("event") == "article_tap"]
              and names(fbq(page)) == ["PageView", "Lead", "PageView"],
              names(fbq(page)))
        page.evaluate("() => document.querySelector('#pay-button')"
                      ".scrollIntoView()")
        page.wait_for_timeout(500)
        before = names(fbq(page))
        page.locator("#pay-button").click()
        page.wait_for_selector("#result-module.is-delivered .ai-node",
                               timeout=30000)
        page.wait_for_timeout(900)
        calls = fbq(page)
        check("the offer was seen and pay was tapped",
              [e for e in walk.events if e.get("event") == "pay_tap"]
              and [e for e in walk.events
                   if e.get("event") in ("paywall_view", "paywall_open")],
              [e.get("event") for e in walk.events][-8:])
        check("no pixel event before leaving for the checkout",
              before == ["PageView", "Lead", "PageView"], before)

        print("\n--- the delivered page: a confirmed live purchase ---")
        check("one Purchase, after the server's word, and one PageView",
              names(calls) == ["PageView", "Lead", "PageView", "PageView",
                               "Purchase"], names(calls))
        bought = [c for c in calls if c[1] == "Purchase"]
        check("  value 6.00, currency USD, eventID the payment intent",
              bought and bought[0][2] == {"value": 6, "currency": "USD"}
              and bought[0][3] == {"eventID": PI_LIVE}, bought)
        check("  nothing in any pixel call but ids, a value and a currency",
              "@" not in json.dumps(calls) and "example" not in
              json.dumps(calls))
        check("  no Lead on the delivered page",
              names(calls).count("Lead") == 1)
        page.reload()
        page.wait_for_selector("#result-module.is-delivered .ai-node",
                               timeout=30000)
        page.wait_for_timeout(900)
        calls = fbq(page)
        check("a reload adds a PageView and no Purchase",
              names(calls).count("Purchase") == 1
              and names(calls).count("PageView") == 4, names(calls))
        check("no ViewContent and no InitiateCheckout anywhere in the walk",
              not [n for n in names(calls)
                   if n not in ("PageView", "Lead", "Purchase")],
              names(calls))
        check("  and one init a page load, always this pixel",
              [c[1] for c in calls if c[0] == "init"] == [PIXEL] * 4,
              [c[1] for c in calls if c[0] == "init"])
        check("no script errors", not errors, errors)

        print("\n--- the same purchase link in a new tab ---")
        other = ctx.new_page()
        other.goto(BASE + "/ai-navigator?cs=" + PI_LIVE)
        other.wait_for_selector("#result-module.is-delivered .ai-node",
                                timeout=30000)
        other.wait_for_timeout(900)
        check("still no second Purchase for that payment intent",
              names(fbq(other)) == ["PageView"], names(fbq(other)))
        other.close()
        ctx.close()

        print("\n--- the delivered page: a test purchase ---")
        ctx = browser.new_context(viewport={"width": 390, "height": 844},
                                  is_mobile=True, has_touch=True)
        ctx.route(lambda url: not url.startswith(BASE), lambda r: r.abort())
        ctx.route("https://connect.facebook.net/en_US/fbevents.js",
                  lambda r: r.fulfill(status=200,
                                      content_type="text/javascript",
                                      body=FBEVENTS))
        page = ctx.new_page()
        page.goto(BASE + "/ai-navigator?cs=" + PI_TEST)
        page.wait_for_selector("#result-module.is-delivered .ai-node",
                               timeout=30000)
        page.wait_for_timeout(900)
        calls = fbq(page)
        check("the report is delivered and the pixel hears a PageView only",
              names(calls) == ["PageView"], names(calls))
        check("  on this funnel's pixel",
              [c[1] for c in calls if c[0] == "init"] == [PIXEL])
        ctx.close()
        browser.close()
    server.shutdown()


def main():
    server_half()
    browser_half()
    print("\n%d checks, %d failed" % (checks[0], len(fails)))
    for line in fails:
        print("  FAIL " + line[:420])
    return 1 if fails else 0


if __name__ == "__main__":
    sys.exit(main())
