#!/usr/bin/env python3
"""The Express Checkout Element on the paywall, and every way it declines to be.

The wallet sheet itself cannot be driven from a headless browser: Apple Pay and
Google Pay are the platform's, not the page's, and no automation opens one. So
STRIPE.JS IS STUBBED HERE — `https://js.stripe.com/v3/` is intercepted and
answered with a script of our own that implements the small surface engine.js
actually uses: `Stripe(pk)`, `.elements({clientSecret})`, `.create(...)`, an
element with `on`/`mount`, and `confirmPayment`. The stub records the
publishable key it was constructed with and the client secret it was given,
and lets the test fire the element's own events — `ready`, `click`, `cancel`,
`confirm` — at the moment it chooses.

What that stub does NOT prove: that a real Apple Pay sheet opens, or that
Stripe's element renders a button anybody would tap. What it does prove is
everything on our side of that boundary — which of the two buttons is live,
that only one ever is, that the block does not move under a thumb when the
choice is made, that the consent box gates the sheet exactly as it gates the
redirect, where the key came from, what is tracked, and that every failure ends
at the button that has always worked.

The four endings in the brief each get a run: a wallet reported available, no
wallet reported, Stripe.js refusing to load at all, and nobody answering inside
the deadline.

    python3 express.py
"""
import json
import os
import socketserver
import sys
import threading
import time

# The repo root, derived from this file rather than hardcoded: a suite
# that only runs from one absolute path is a suite that stops running the
# first time the checkout moves.
REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from playwright.sync_api import sync_playwright          # noqa: E402
from test_walk import Handler as WalkHandler, PORT, ANCHORS   # noqa: E402

ROOT = REPO
CHROME = "/opt/pw-browsers/chromium-1194/chrome-linux/chrome"

CFG = json.load(open(os.path.join(ROOT, "funnels/kitchen-visualizer.json")))
KITCHEN = json.load(open(os.path.join(ROOT, "funnels/kitchen.json")))

PK = "pk_test_HARNESS_ONLY_51abcdef"
INTENT_ID = "pi_3RharnessXYZ"
SECRET = INTENT_ID + "_secret_QQQ"

fails = []
checks = [0]


def check(label, ok, detail=""):
    checks[0] += 1
    if not ok:
        fails.append("%s %s" % (label, detail))
    print("  %-66s %s%s" % (label, "ok" if ok else "FAIL",
                            ("  " + str(detail)) if not ok else ""))


class Server:
    def __init__(self):
        self.reset()

    def reset(self):
        self.events = []          # (event, extra)
        self.intents = 0
        self.intent_bodies = []
        self.checkouts = 0
        self.checkout_bodies = []
        self.intent_answer = None  # (code, body) to force
        # Whether this reader has already handed over a kitchen. The upload
        # gate on kitchen-visualizer refuses to mount a wallet, create an
        # intent or enable the pay button until they have, so every case in
        # here that is about the Express Element starts with a photo on file.
        # The one case that is about the gate itself sets it False.
        self.has_source = True


S = Server()


def report_body():
    titles = {s["id"]: s["title"] for s in CFG["report"]["sections"]}
    data = {
        "palette": {"intro": "x", "colors": [{"name": "Oat", "hex": "#E5DAC8",
                    "role": "d", "finish": "matt", "where": "w"}],
                    "closing_rule": "r"},
        "mistakes": {"items": [{"title": "t", "body": "b" * 40, "fix": "f" * 12}]},
        "materials": {"intro": "i" * 22, "pairs": [{"combo": "c", "verdict":
                      "works", "why": "w" * 12}], "rule": "r" * 16},
        "shopping": {"items": [{"name": "n", "priority_note": "p"}], "skip": []},
        "dna": {"narrative": ["n"], "implications": ["i"]},
        "splurge": {"splurge": {"item": "i", "why": "w"},
                    "saves": [{"item": "i", "why": "w"}], "split_note": "s"},
    }
    return {"complete": True, "report": {
        "version": "llm-2", "funnel": "kitchen-visualizer",
        "style_id": "modern_rustic", "style_name": "Modern Rustic",
        "sections": [{"id": s["id"], "title": titles[s["id"]],
                      "data": data[s["id"]]}
                     for s in CFG["report"]["sections"]]}}


class Handler(WalkHandler):

    def do_GET(self):
        path = self.path.split("?")[0]
        if path == "/api/pixel-config":
            return self._json({})
        if path == "/api/report":
            return self._json(report_body())
        if path == "/api/visualizer/status":
            return self._json({"status": "uploaded" if S.has_source else "none",
                               "paid": False,
                               "generations": 0, "max_generations": 2,
                               "remaining": 2, "has_source": S.has_source})
        if path in ("/kitchen", "/kitchen-visualizer"):
            self.path = "/static/funnel.html"
        return super().do_GET()

    def do_POST(self):
        path = self.path.split("?")[0]
        raw = self.rfile.read(int(self.headers.get("content-length") or 0))
        if path == "/api/track":
            try:
                body = json.loads(raw.decode("utf-8"))
                S.events.append((body["event"], body.get("extra")))
            except Exception:
                pass
            self.send_response(204)
            self.end_headers()
            return
        if path == "/api/payment-intent":
            S.intents += 1
            try:
                S.intent_bodies.append(json.loads(raw.decode("utf-8")))
            except Exception:
                S.intent_bodies.append(None)
            if S.intent_answer is not None:
                code, body = S.intent_answer
                return self._json(body or {}, code)
            return self._json({"client_secret": SECRET, "publishable_key": PK,
                               "amount_cents": CFG["pricing"]["amount_cents"],
                               "currency": CFG["pricing"]["currency"]})
        if path == "/api/checkout":
            S.checkouts += 1
            try:
                S.checkout_bodies.append(json.loads(raw.decode("utf-8")))
            except Exception:
                S.checkout_bodies.append(None)
            return self._json({"url": "http://127.0.0.1:%d/stripe-hosted" % PORT})
        self.send_response(204)
        self.end_headers()

    def _bytes(self, raw, mime, code=200):
        self.send_response(code)
        self.send_header("Content-Type", mime)
        self.send_header("Content-Length", str(len(raw)))
        self.end_headers()
        self.wfile.write(raw)

    def _json(self, body, code=200):
        self._bytes(json.dumps(body).encode(), "application/json", code)


# --- the stub -----------------------------------------------------------------

STUB = """
window.__xp = {pk: null, secret: null, type: null, opts: null,
               mounted: false, resolved: 0, confirms: 0, args: null,
               readyFired: 0, resolveOpts: null};
window.__xpWallets = %(wallets)s;
window.__xpDelay = %(delay)d;
window.__xpAnswer = %(answer)s;
window.__xpConfirm = %(confirm)s;

window.Stripe = function (pk) {
  window.__xp.pk = pk;
  return {
    elements: function (o) {
      window.__xp.secret = o && o.clientSecret;
      return {
        create: function (type, opts) {
          window.__xp.type = type;
          window.__xp.opts = opts;
          var handlers = {};
          window.__xpFire = function (name, arg) {
            if (handlers[name]) handlers[name](arg);
          };
          return {
            on: function (n, cb) { handlers[n] = cb; },
            mount: function (node) {
              window.__xp.mounted = true;
              var btn = document.createElement('div');
              btn.id = 'xp-fake-button';
              btn.style.height = ((opts && opts.buttonHeight) || 44) + 'px';
              btn.style.background = '#101112';
              btn.style.borderRadius = '8px';
              node.appendChild(btn);
              setTimeout(function () {
                if (!window.__xpAnswer) return;
                window.__xp.readyFired++;
                if (handlers.ready) {
                  handlers.ready({availablePaymentMethods: window.__xpWallets});
                }
              }, window.__xpDelay);
            }
          };
        }
      };
    },
    confirmPayment: function (args) {
      window.__xp.confirms++;
      window.__xp.args = {return_url: args.confirmParams.return_url,
                          redirect: args.redirect,
                          hasElements: !!args.elements,
                          pmd: args.confirmParams.payment_method_data
                               || null};
      return Promise.resolve(window.__xpConfirm);
    }
  };
};
"""


def stub(wallets=None, delay=0, answer=True, confirm=None):
    return STUB % {
        "wallets": json.dumps(wallets if wallets is not None
                              else {"applePay": True, "googlePay": False}),
        "delay": delay,
        "answer": "true" if answer else "false",
        "confirm": json.dumps(confirm if confirm is not None else
                              {"paymentIntent": {"id": INTENT_ID,
                                                 "status": "succeeded"}}),
    }


def walk(page, cfg=CFG):
    steps = cfg["swipe"]["steps"]
    page.wait_for_selector("#cards .card", timeout=10000)
    for index, step in enumerate(steps):
        page.query_selector_all("#cards .card")[0].click()
        done = index + 1
        if done in ANCHORS and done < len(steps):
            page.wait_for_selector("#screen-interstitial.is-active", timeout=12000)
            page.click("#mid-cta")
        if done < len(steps):
            page.wait_for_function(
                "q => document.getElementById('swipe-caption').textContent === q",
                arg=steps[done]["question"], timeout=15000)
    page.wait_for_selector("#result-body:not([hidden])", timeout=20000)


def open_paywall(browser, script=None, block=False, slug="kitchen-visualizer",
                 cfg=CFG, photo=True):
    """A page walked to the paywall, with js.stripe.com answered by `script`.

    `photo` is whether the visualizer already has this reader's kitchen. It
    defaults to True because the wallet cannot exist without one: the upload
    gate holds the whole pay control down until a photograph has been sent, so
    a walk with no photo is a walk to a page with no Express Element on it,
    which is the subject of exactly one case below and of none of the others.
    """
    S.has_source = photo
    page = browser.new_page(viewport={"width": 390, "height": 844})
    errors = []
    page.on("pageerror", lambda e: errors.append(str(e)))
    seen = []
    page.on("request", lambda r: seen.append(r.url))

    def route(r):
        if block:
            return r.abort()
        r.fulfill(status=200, content_type="application/javascript",
                  body=script or "")
    page.route("https://js.stripe.com/**", route)
    page.goto("http://127.0.0.1:%d/%s" % (PORT, slug))
    walk(page, cfg)
    page.wait_for_selector("#commerce:not([hidden])", timeout=15000)
    # The gate coming down is what starts the wallet, and the status it turns
    # on arrives from the stub a fetch after the offer renders. Waiting for the
    # price row rather than for a timeout: it is the node the gate is keyed to.
    if photo and slug == "kitchen-visualizer":
        page.wait_for_selector(".offer-gate", state="hidden", timeout=8000)
    return page, errors, seen


def geom(page):
    """The block's height and where the row under it sits. What must not move."""
    return page.evaluate("""() => {
      var xp = document.getElementById('xp');
      var trust = document.querySelector('#commerce .trust:not(.xp-summary__trust)')
                  || document.getElementById('trust');
      var c = document.getElementById('commerce').getBoundingClientRect();
      return {
        xpH: xp ? Math.round(xp.getBoundingClientRect().height * 100) / 100 : null,
        xpTop: xp ? Math.round((xp.getBoundingClientRect().top - c.top) * 100) / 100 : null,
        trustTop: Math.round((trust.getBoundingClientRect().top - c.top) * 100) / 100,
        commerceH: Math.round(c.height * 100) / 100
      };
    }""")


def visible(page, sel):
    return page.evaluate("""s => {
      var n = document.querySelector(s);
      if (!n) return false;
      if (n.hidden) return false;
      var cs = getComputedStyle(n);
      var r = n.getBoundingClientRect();
      return cs.visibility !== 'hidden' && cs.display !== 'none'
             && r.width > 0 && r.height > 0;
    }""", sel)


def taps(kind=None):
    out = [e for e in S.events if e[0] == "pay_tap"]
    if kind is None:
        return out
    return [e for e in out if (e[1] or {}).get("method") == kind]


# --- the server side ----------------------------------------------------------

def tracking_suite():
    print("\n--- tracking.py: pay_tap carries a method, or nothing at all ---")
    sys.path.insert(0, ROOT)
    from app import app                                    # noqa: E402
    import database                                        # noqa: E402

    rows = []
    database.execute = lambda q, p=None: rows.append(p)
    client = app.test_client()
    sid = "11111111-2222-3333-4444-555555555555"

    def post(extra, event="pay_tap"):
        body = {"funnel": "kitchen-visualizer", "session_id": sid,
                "event": event}
        if extra is not _MISSING:
            body["extra"] = extra
        return client.post("/api/track", json=body)

    for value, want, label in [
        (_MISSING, 204, "an engine.js from before this shipped, sending none"),
        ({"method": "wallet"}, 204, "the wallet button"),
        ({"method": "redirect"}, 204, "the redirect button"),
        ({"method": "card"}, 400, "a method nobody defined"),
        ({"method": "WALLET"}, 400, "the right word in the wrong case"),
        ({"method": 1}, 400, "a method that is not a string"),
        ({}, 400, "an empty object"),
        ({"method": "wallet", "amount": 700}, 400, "a method plus a smuggled field"),
        ({"amount": 700}, 400, "no method at all"),
        (None, 204, "an explicit null"),
    ]:
        rows[:] = []
        r = post(value)
        check("  %-52s -> %d" % (label, want), r.status_code == want,
              r.status_code)

    rows[:] = []
    post({"method": "wallet"})
    check("  what reaches the column is rebuilt, not passed through",
          rows and rows[-1][-1] == '{"method":"wallet"}',
          rows[-1][-1] if rows else None)

    rows[:] = []
    post(_MISSING)
    check("  and an absent payload stores NULL, as it always did",
          rows and rows[-1][-1] is None, rows[-1][-1] if rows else None)

    for event in ("result_view", "sticky_cta", "checkout_error"):
        r = post({"method": "wallet"}, event)
        check("  a method on %-14s is still refused" % event,
              r.status_code == 400, r.status_code)


class _Missing:
    pass


_MISSING = _Missing()


def main():
    socketserver.TCPServer.allow_reuse_address = True
    httpd = socketserver.TCPServer(("127.0.0.1", PORT), Handler)
    threading.Thread(target=httpd.serve_forever, daemon=True).start()

    print("\n" + "=" * 78)
    print("STRIPE.JS IS STUBBED. A real wallet sheet cannot be opened headlessly;")
    print("everything below tests our side of that boundary and nothing beyond it.")
    print("=" * 78)

    try:
        with sync_playwright() as pw:
            browser = pw.chromium.launch(executable_path=CHROME)

            # --- 1. the wallet is available ---------------------------
            print("\n--- a wallet is reported: the reserved slot becomes it ---")
            S.reset()
            page, errors, seen = open_paywall(browser, stub(delay=900))

            # Caught mid-flight, while the element has not answered yet.
            page.wait_for_selector("#xp .xp__ghost", timeout=4000)
            before = geom(page)
            check("the placeholder is up before anything has answered",
                  visible(page, "#xp .xp__ghost"))
            check("  and the pay button is not, at the same moment",
                  not visible(page, "#pay-button"))
            check("  the element has already mounted and painted",
                  page.evaluate("() => window.__xp.mounted")
                  and page.query_selector("#xp-fake-button") is not None)
            check("  but it is held invisible until it has answered",
                  not visible(page, ".xp__mount")
                  and not visible(page, "#xp-fake-button"))
            check("  so it cannot be tapped before the choice is made",
                  page.evaluate("""() => getComputedStyle(
                      document.querySelector('.xp__mount')).pointerEvents
                      === 'none'"""))

            page.wait_for_function(
                "() => !document.querySelector('#xp .xp__ghost')", timeout=6000)
            after = geom(page)

            check("the wallet button is what is showing now",
                  visible(page, ".xp__mount")
                  and visible(page, "#xp-fake-button"))
            check("  and the redirect button is put away",
                  not visible(page, "#pay-button"))
            check("  never both at once",
                  visible(page, "#xp-slot") != visible(page, "#pay-button"))

            check("THE BLOCK DOES NOT MOVE: same height reserved and final",
                  before["xpH"] == after["xpH"], (before["xpH"], after["xpH"]))
            check("  the row under it is at the same y",
                  before["trustTop"] == after["trustTop"],
                  (before["trustTop"], after["trustTop"]))
            check("  and the block itself starts at the same y",
                  before["xpTop"] == after["xpTop"],
                  (before["xpTop"], after["xpTop"]))
            check("  the whole commerce block is the same height",
                  before["commerceH"] == after["commerceH"],
                  (before["commerceH"], after["commerceH"]))

            log = page.evaluate("() => window.__xp")
            check("the key came from the /api/payment-intent response",
                  log["pk"] == PK, log["pk"])
            check("  and nothing else on the page carries a key",
                  PK not in page.content()
                  and PK not in open(os.path.join(
                      ROOT, "static/funnels/kitchen-visualizer.json")).read())
            check("  the element was given that intent's client secret",
                  log["secret"] == SECRET, log["secret"])
            check("  it is an expressCheckout element", log["type"] ==
                  "expressCheckout", log["type"])
            check("exactly one intent was created", S.intents == 1, S.intents)
            check("  and the client sent no amount with it",
                  S.intent_bodies and "amount" not in S.intent_bodies[0]
                  and "amount_cents" not in S.intent_bodies[0],
                  sorted(S.intent_bodies[0]) if S.intent_bodies else None)
            check("  /api/checkout was not called on this path",
                  S.checkouts == 0, S.checkouts)
            check("stripe.js was fetched from Stripe, not from us",
                  any(u.startswith("https://js.stripe.com/v3") for u in seen),
                  [u for u in seen if "stripe" in u])
            check("no page errors", not errors, errors[:3])

            # --- what a wallet buyer is told, and where ---------------
            #
            # This used to be a summary card the wallet path grew above the
            # button: the product name and the amount, because the hosted page
            # names both and a sheet opening in place names neither. It is gone
            # on this funnel, and what replaced it is not less — it is the same
            # facts, earlier and in one place. The page names what is bought in
            # three value cards and what it costs in the price row, both of
            # them above the pay control and both of them there before Stripe
            # has answered. A card that arrives on the wallet answer says it a
            # second time and moves the button while it does.
            print("\n--- the wallet buyer reads the same block as everyone ---")
            check("no summary card on the focused page",
                  page.query_selector(".xp-summary") is None)
            check("  the price row is the price block, wallet and all",
                  visible(page, "#price"))
            money = "%.2f %s" % (CFG["pricing"]["amount_cents"] / 100.0,
                                 CFG["pricing"]["currency"].upper())
            short = "$%d" % (CFG["pricing"]["amount_cents"] // 100)
            # One price block, counted as blocks and not as occurrences of the
            # figure: the consent line names the amount inside a sentence about
            # the terms ("One-time $3 — no subscription, ever"), which is copy
            # rather than a second price to compare with the first.
            check("  and exactly one block presents it as the price",
                  page.eval_on_selector_all(
                      ".price-now", """ns => ns.filter(
                          n => n.offsetParent !== null).length""") == 1,
                  page.eval_on_selector_all(".price-now", "n => n.length"))
            check("  the figure it presents is the configured one",
                  page.inner_text("#price .price-now") == short,
                  page.inner_text("#price .price-now"))
            check("  what is bought is named above it, from commerce.value",
                  page.eval_on_selector_all(
                      ".offer-value__row", "n => n.length")
                  == len(CFG["checkout"]["commerce"]["value"]))
            check("  the value cards sit above the price, not beside the button",
                  page.evaluate("""() => {
                    var v = document.querySelector('.offer-value'),
                        p = document.getElementById('price');
                    return v.getBoundingClientRect().bottom
                           <= p.getBoundingClientRect().top + 1; }"""))
            check("  and the long form is nowhere on the page",
                  money not in page.inner_text("#result-body"), money)

            # --- consent gates the sheet ------------------------------
            print("\n--- the withdrawal consent gates the sheet, not the sheet it ---")
            check("this funnel starts the box ticked, as it configures",
                  page.is_checked("#withdrawal-check")
                  and CFG["checkout"]["consent_prechecked"] is True)
            check("  so the slot starts un-greyed",
                  not page.evaluate("""() => document.getElementById('xp-slot')
                                        .classList.contains('is-locked')"""))

            page.uncheck("#withdrawal-check")
            page.wait_for_timeout(80)
            check("clearing it greys the wallet button",
                  page.evaluate("""() => document.getElementById('xp-slot')
                                    .classList.contains('is-locked')"""))
            check("  and greys the redirect button too, as it always did",
                  page.is_disabled("#pay-button"))
            page.evaluate("""() => window.__xpFire('click', {
              resolve: function (o) { window.__xp.resolved++;
                                    window.__xp.resolveOpts = o; }})""")
            page.wait_for_timeout(150)
            log = page.evaluate("() => window.__xp")
            check("  a tap with the box clear does not open the sheet",
                  log["resolved"] == 0, log["resolved"])
            check("  the reader is told why",
                  visible(page, "#pay-error")
                  and "tick the box" in page.inner_text("#pay-error"),
                  page.inner_text("#pay-error"))
            check("  and the tap is counted anyway, as a wallet tap",
                  len(taps("wallet")) == 1, taps())

            page.check("#withdrawal-check")
            page.wait_for_timeout(80)
            check("ticking it clears the grey",
                  not page.evaluate("""() => document.getElementById('xp-slot')
                                        .classList.contains('is-locked')"""))
            check("  and takes the line away", not visible(page, "#pay-error"))
            page.evaluate("""() => window.__xpFire('click', {
              resolve: function (o) { window.__xp.resolved++;
                                    window.__xp.resolveOpts = o; }})""")
            page.wait_for_timeout(150)
            log = page.evaluate("() => window.__xp")
            check("  and now the sheet is allowed to open",
                  log["resolved"] == 1, log["resolved"])
            check("  a second wallet tap counted",
                  len(taps("wallet")) == 2, taps())
            check("  still nothing charged and nothing redirected",
                  S.checkouts == 0 and S.intents == 1)

            # --- what the sheet is asked to collect -------------------
            # A wallet does not volunteer an email. This is the option that
            # makes the sheet show the field at all, and its absence is why a
            # real purchase recorded with a NULL email and the buyer never got
            # their PDF. What the sheet then DOES with the option is Apple's,
            # and is not drivable here.
            print("\n--- the sheet is asked for an email and an address ---")
            opts = log["resolveOpts"]
            check("resolve() was handed options, not an empty object",
                  isinstance(opts, dict) and opts != {}, opts)
            check("  emailRequired, which is the whole of this fix",
                  opts.get("emailRequired") is True, opts)
            check("  billingAddressRequired, which feeds purchases.country",
                  opts.get("billingAddressRequired") is True, opts)
            check("  and nothing is asked for that nothing stores",
                  set(opts) == {"emailRequired", "billingAddressRequired"},
                  sorted(opts))

            # --- dismissal is not a failure ---------------------------
            print("\n--- a sheet dismissed is somebody thinking, not an error ---")
            url_before = page.url
            page.evaluate("() => window.__xpFire('cancel')")
            page.wait_for_timeout(200)
            check("  the page did not move", page.url == url_before)
            check("  no error copy appeared", not visible(page, "#pay-error"))
            check("  the wallet button is still the live one",
                  visible(page, "#xp-slot") and not visible(page, "#pay-button"))
            check("  the box is still ticked", page.is_checked("#withdrawal-check"))
            check("  the block still has not moved",
                  geom(page)["trustTop"] == after["trustTop"])
            page.evaluate("""() => window.__xpFire('click', {
              resolve: function (o) { window.__xp.resolved++;
                                    window.__xp.resolveOpts = o; }})""")
            page.wait_for_timeout(120)
            check("  and it can be asked for again",
                  page.evaluate("() => window.__xp.resolved") == 2)

            # --- confirmation -----------------------------------------
            print("\n--- a confirmed payment hands the token to the page ---")
            page.evaluate("""() => window.__xpFire('confirm', {
              expressPaymentType: 'apple_pay',
              billingDetails: {
                name: 'A Buyer', email: 'wallet@icloud.com', phone: '',
                address: {line1: '1 Test St', line2: null, city: 'London',
                          state: '', postal_code: 'E1 6AN', country: 'GB'}}})""")
            page.wait_for_url("**/kitchen-visualizer?cs=*", timeout=8000)
            check("it navigates to the funnel with the token",
                  page.url.endswith("/kitchen-visualizer?cs=" + INTENT_ID),
                  page.url)
            check("  the parameter is still called cs", "?cs=" in page.url)
            check("  and it is the intent id, not the client secret",
                  "_secret_" not in page.url, page.url)
            page.wait_for_selector("#screen-result.is-active", timeout=10000)
            page.wait_for_selector("#report .section", timeout=15000)
            check("  which the page accepts and polls on",
                  visible(page, "#report"))
            check("  the report came from /api/report, not from the client",
                  "Modern Rustic" in page.inner_text("body"))
            page.close()

            # --- a real failure, and what confirmPayment was asked to do ---
            # A declined confirm rather than a successful one, because a
            # success navigates and takes the stub's own log with it.
            print("\n--- a payment that really did fail ---")
            S.reset()
            page, errors, seen = open_paywall(
                browser, stub(confirm={"error": {"code": "card_declined"}}))
            page.wait_for_selector("#xp-fake-button", timeout=6000)
            page.check("#withdrawal-check")
            fail_geom = geom(page)
            page.evaluate("""() => window.__xpFire('confirm', {
              expressPaymentType: 'apple_pay',
              billingDetails: {
                name: 'A Buyer', email: 'wallet@icloud.com', phone: '',
                address: {line1: '1 Test St', line2: null, city: 'London',
                          state: '', postal_code: 'E1 6AN', country: 'GB'}}})""")
            page.wait_for_selector("#pay-button:not(.xp__off)", timeout=6000)

            log = page.evaluate("() => window.__xp")
            check("confirmPayment was handed the elements group",
                  log["args"]["hasElements"])
            check("  redirect is 'if_required', so the sheet stays in place",
                  log["args"]["redirect"] == "if_required", log["args"]["redirect"])
            check("  the return_url is the funnel with the same token",
                  log["args"]["return_url"].endswith(
                      "/kitchen-visualizer?cs=" + INTENT_ID),
                  log["args"]["return_url"])
            check("  and the secret is not in it",
                  "_secret_" not in log["args"]["return_url"])

            # The wallet's details are attached to the payment itself, so the
            # webhook reads the email off the charge — from Stripe, server
            # side — instead of from anything this page posted to our API.
            print("\n--- what the wallet said travels on the payment ---")
            pmd = log["args"]["pmd"]
            check("confirmPayment carries payment_method_data",
                  isinstance(pmd, dict) and "billing_details" in pmd, pmd)
            billing = (pmd or {}).get("billing_details") or {}
            check("  with the email the wallet gave",
                  billing.get("email") == "wallet@icloud.com", billing)
            check("  and the name", billing.get("name") == "A Buyer", billing)
            check("  and the address, country included",
                  (billing.get("address") or {}).get("country") == "GB",
                  billing.get("address"))
            check("  empty strings are dropped, not sent as blanks",
                  "phone" not in billing
                  and "state" not in (billing.get("address") or {}),
                  billing)
            check("  and nulls too",
                  "line2" not in (billing.get("address") or {}),
                  billing.get("address"))
            check("  nothing outside Stripe's own billing_details keys",
                  set(billing) <= {"name", "email", "phone", "address"}
                  and set(billing.get("address") or {}) <=
                  {"line1", "line2", "city", "state", "postal_code", "country"},
                  billing)
            check("  and our own API was never told an email",
                  all("email" not in (b or {}) for b in S.intent_bodies),
                  S.intent_bodies)
            check("a short retry line is shown",
                  visible(page, "#pay-error")
                  and "didn't go through" in page.inner_text("#pay-error"),
                  page.inner_text("#pay-error"))
            check("  the redirect button is reachable again",
                  visible(page, "#pay-button")
                  and not page.is_disabled("#pay-button"))
            check("  and the wallet is put away, so still only one",
                  not visible(page, "#xp-slot"))
            check("  the page did not move", "?cs=" not in page.url, page.url)
            check("  the block height is unchanged by the failure",
                  geom(page)["xpH"] == fail_geom["xpH"],
                  (fail_geom["xpH"], geom(page)["xpH"]))
            page.click("#pay-button")
            page.wait_for_timeout(400)
            check("  and it still reaches /api/checkout",
                  S.checkouts == 1, S.checkouts)
            check("  counted as a redirect tap",
                  len(taps("redirect")) == 1, taps())
            page.close()

            # --- the wallet still gives nothing ------------------------
            # Asking is not the same as receiving. A wallet that answers with
            # no billing details at all must still pay: the confirm goes
            # through without the field, the server records the purchase with
            # a NULL email, and only the PDF is missed. That last half is
            # asserted on the server in tests/test_payment_intent.py.
            print("\n--- a wallet that gives nothing back still pays ---")
            S.reset()
            page, errors, seen = open_paywall(
                browser, stub(confirm={"error": {"code": "card_declined"}}))
            page.wait_for_selector("#xp-fake-button", timeout=6000)
            page.check("#withdrawal-check")
            page.evaluate("() => window.__xpFire('confirm', {})")
            page.wait_for_timeout(400)
            log = page.evaluate("() => window.__xp")
            check("the payment is still confirmed", log["confirms"] == 1,
                  log["confirms"])
            check("  with no payment_method_data invented for it",
                  log["args"]["pmd"] is None, log["args"]["pmd"])
            check("  and the return_url is unchanged",
                  log["args"]["return_url"].endswith(
                      "/kitchen-visualizer?cs=" + INTENT_ID),
                  log["args"]["return_url"])
            check("no page errors", not errors, errors[:3])

            page.close()

            # --- 2. no wallet on this device --------------------------
            print("\n--- no wallet reported: today's button, unchanged ---")
            S.reset()
            page, errors, seen = open_paywall(
                browser, stub(wallets={}, delay=700))
            page.wait_for_selector("#xp .xp__ghost", timeout=4000)
            reserved = geom(page)
            check("the placeholder holds the space first",
                  visible(page, "#xp .xp__ghost")
                  and not visible(page, "#pay-button"))
            page.wait_for_selector("#pay-button:not(.xp__off)", timeout=6000)
            final = geom(page)
            check("the redirect button is what is left",
                  visible(page, "#pay-button"))
            check("  and the wallet slot is gone", not visible(page, "#xp-slot"))
            check("THE BLOCK DOES NOT MOVE: reserved -> redirect",
                  reserved["xpH"] == final["xpH"],
                  (reserved["xpH"], final["xpH"]))
            check("  the row under it is at the same y",
                  reserved["trustTop"] == final["trustTop"],
                  (reserved["trustTop"], final["trustTop"]))
            # The figure comes from `pricing`, not from a literal. It was $7
            # when this was written and it is $3 now, and a number typed in
            # here is a check that fails the next time the price moves for a
            # reason that has nothing to do with what it is testing.
            check("  it carries the config's own label",
                  page.inner_text("#pay-button") ==
                  CFG["checkout"]["cta_label"].replace(
                      "{price}", "$%d" % (CFG["pricing"]["amount_cents"] // 100)),
                  page.inner_text("#pay-button"))
            check("  live, because this funnel pre-ticks the box",
                  not page.is_disabled("#pay-button"))
            page.uncheck("#withdrawal-check")
            check("  and grey again the moment it is cleared",
                  page.is_disabled("#pay-button"))
            page.check("#withdrawal-check")
            page.click("#pay-button")
            page.wait_for_timeout(500)
            check("  and it goes to /api/checkout", S.checkouts == 1, S.checkouts)
            check("  tracked as a redirect tap",
                  len(taps("redirect")) == 1 and not taps("wallet"), taps())
            check("  the checkout body is the same one it always sent",
                  S.checkout_bodies and set(S.checkout_bodies[0]) >=
                  {"funnel", "session_id", "result_style", "tag_scores",
                   "choices"},
                  sorted(S.checkout_bodies[0]) if S.checkout_bodies else None)
            check("no page errors", not errors, errors[:3])
            page.close()

            # --- 3. stripe.js never loads -----------------------------
            print("\n--- stripe.js refuses to load at all ---")
            S.reset()
            t0 = time.time()
            page, errors, seen = open_paywall(browser, block=True)
            page.wait_for_selector("#pay-button:not(.xp__off)", timeout=8000)
            took = time.time() - t0
            check("it falls back without waiting out the deadline",
                  visible(page, "#pay-button"))
            check("  the wallet slot is not showing",
                  not visible(page, "#xp-slot"))
            check("  window.Stripe never existed",
                  page.evaluate("() => !window.Stripe"))
            page.check("#withdrawal-check")
            page.click("#pay-button")
            page.wait_for_timeout(500)
            check("  and the paywall still sells", S.checkouts == 1, S.checkouts)
            check("no page errors", not errors, errors[:3])
            page.close()

            # --- 4. nobody answers ------------------------------------
            print("\n--- the element loads and then says nothing ---")
            S.reset()
            page, errors, seen = open_paywall(browser, stub(answer=False))
            page.wait_for_selector("#xp .xp__ghost", timeout=4000)
            armed = time.time()
            held = geom(page)
            check("the placeholder holds while we wait",
                  visible(page, "#xp .xp__ghost")
                  and not visible(page, "#pay-button"))
            page.wait_for_selector("#pay-button:not(.xp__off)", timeout=9000)
            waited = time.time() - armed
            check("the deadline hands the paywall back", visible(page, "#pay-button"))
            check("  and it is a bounded wait, not an open one",
                  waited < 5.0, round(waited, 2))
            check("  the element did mount, it just never answered",
                  page.evaluate("() => window.__xp.mounted")
                  and page.evaluate("() => window.__xp.readyFired") == 0)
            check("  no wallet button is left behind",
                  not visible(page, "#xp-slot"))
            check("THE BLOCK DOES NOT MOVE: reserved -> timed out",
                  geom(page)["trustTop"] == held["trustTop"],
                  (held["trustTop"], geom(page)["trustTop"]))
            page.check("#withdrawal-check")
            page.click("#pay-button")
            page.wait_for_timeout(500)
            check("  and the paywall sells", S.checkouts == 1, S.checkouts)
            check("no page errors", not errors, errors[:3])
            page.close()

            # --- 5. the intent itself fails ---------------------------
            print("\n--- /api/payment-intent refuses ---")
            S.reset()
            S.intent_answer = (502, {})
            page, errors, seen = open_paywall(browser, stub())
            page.wait_for_selector("#pay-button:not(.xp__off)", timeout=8000)
            check("no intent, no wallet, ordinary button",
                  visible(page, "#pay-button") and not visible(page, "#xp-slot"))
            check("  and Stripe was never constructed",
                  page.evaluate("() => window.__xp.pk") is None)
            page.check("#withdrawal-check")
            page.click("#pay-button")
            page.wait_for_timeout(500)
            check("  the paywall sells", S.checkouts == 1, S.checkouts)
            S.intent_answer = None
            page.close()

            # --- 6. /kitchen is untouched -----------------------------
            print("\n--- /kitchen: the flag is absent, so none of this exists ---")
            S.reset()
            page, errors, seen = open_paywall(browser, stub(), slug="kitchen",
                                              cfg=KITCHEN)
            page.wait_for_timeout(1200)
            check("nothing was fetched from stripe.com",
                  not any("stripe.com" in u for u in seen),
                  [u for u in seen if "stripe" in u])
            check("  window.Stripe is undefined",
                  page.evaluate("() => typeof window.Stripe") == "undefined")
            check("  no express block in the document",
                  page.evaluate("() => !document.getElementById('xp')"))
            check("  no reserved slot", page.evaluate(
                "() => !document.getElementById('xp-slot')"))
            check("  no summary card", page.evaluate(
                "() => !document.querySelector('.xp-summary')"))
            check("  no payment intent was created", S.intents == 0, S.intents)
            check("  the pay button is a direct child of #commerce",
                  page.evaluate("""() => document.getElementById('pay-button')
                                    .parentNode.id === 'commerce'"""))
            check("  it is visible from the start, exactly as before",
                  visible(page, "#pay-button")
                  and not page.is_disabled("#pay-button"))
            check("  with no xp class on it",
                  page.evaluate("""() => !document.getElementById('pay-button')
                                    .className.match(/xp/)"""))

            page.uncheck("#withdrawal-check")
            check("  clearing the box still greys it",
                  page.is_disabled("#pay-button"))
            page.check("#withdrawal-check")
            check("  ticking enables it", not page.is_disabled("#pay-button"))
            page.click("#pay-button")
            page.wait_for_url("**/stripe-hosted", timeout=8000)
            check("  the full walk still ends at a redirect",
                  page.url.endswith("/stripe-hosted"), page.url)
            check("  through /api/checkout", S.checkouts == 1, S.checkouts)
            check("  with kitchen's own funnel slug",
                  S.checkout_bodies[0]["funnel"] == "kitchen",
                  S.checkout_bodies[0]["funnel"])
            check("  and the tap was tracked as a redirect",
                  len(taps("redirect")) == 1 and not taps("wallet"), taps())
            check("no page errors", not errors, errors[:3])
            page.close()

            # --- 7. a pi_ token unlocks a report ----------------------
            print("\n--- the token the wallet path produces is one the page accepts ---")
            for token, want in [(INTENT_ID, True),
                                ("cs_test_a1b2c3", True),
                                ("sk_live_nope", False),
                                ("pi_" + "x" * 300, False)]:
                p = browser.new_page(viewport={"width": 390, "height": 844})
                p.goto("http://127.0.0.1:%d/kitchen-visualizer?cs=%s"
                       % (PORT, token))
                p.wait_for_timeout(900)
                got = p.evaluate(
                    "() => document.getElementById('screen-result')"
                    ".classList.contains('is-active')")
                check("  %-24s -> %s" % (token[:24], "report" if want
                                         else "quiz"), got == want, got)
                p.close()

            browser.close()
    finally:
        httpd.shutdown()

    tracking_suite()

    print("\n%d checks, %d failed" % (checks[0], len(fails)))
    for f in fails:
        print("  FAIL " + f)
    return 1 if fails else 0


if __name__ == "__main__":
    sys.exit(main())
