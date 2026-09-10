#!/usr/bin/env python3
"""One id, both sides, in a real browser.

The unit suite (test_capimirror.py) reads the wiring off engine.js and
drives the server with hand-made bodies. This drives the page: a stub fbq
records every event with the eventID it was given, the stub server records
every /api/track body, and the two are laid side by side — PageView beside
funnel_start, Lead beside result_view, InitiateCheckout beside paywall_open,
AddPaymentInfo beside pay_tap. Same id, or the twin the server sends would be
a second event rather than a copy.

The two-screen checkout, as test_events.py drives it: the result CTA opens
the paywall, the pay button starts paying. The single-page layout carries
the same id on paywall_view instead, which the unit suite covers.

    python3 tests/test_capiwire.py
"""
import http.server
import json
import os
import re
import socketserver
import sys
import threading

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, REPO)

from playwright.sync_api import sync_playwright           # noqa: E402

ROOT = REPO
PORT = 8747
CHROME = "/opt/pw-browsers/chromium-1194/chrome-linux/chrome"
cfg = json.load(open(os.path.join(ROOT, "funnels/kitchen.json")))
STEPS = cfg["swipe"]["steps"]
ANCHORS = {i["after_step"] for i in cfg["interstitials"]}
UUID_RE = re.compile(r"^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-"
                     r"[0-9a-f]{12}$", re.I)

events = []
fails = []
checks = [0]


def check(label, ok, detail=""):
    checks[0] += 1
    if not ok:
        fails.append("%s %s" % (label, detail))
    print("  %-62s %s%s" % (label, "ok" if ok else "FAIL",
                            ("  " + str(detail)) if not ok else ""))


class Handler(http.server.SimpleHTTPRequestHandler):
    def __init__(self, *a, **kw):
        super().__init__(*a, directory=ROOT, **kw)

    def log_message(self, *a):
        pass

    def do_GET(self):
        path = self.path.split("?")[0]
        if path == "/api/pixel-config":
            return self._json({"pixel_id": "111"})
        if path == "/static/funnels/kitchen.json":
            two_screen = json.loads(json.dumps(cfg))
            two_screen["checkout"]["single_page"] = False
            two_screen["checkout"].pop("commerce", None)
            return self._json(two_screen)
        if path == "/kitchen":
            self.path = "/static/funnel.html"
        return super().do_GET()

    def do_POST(self):
        path = self.path.split("?")[0]
        raw = self.rfile.read(int(self.headers.get("content-length") or 0))
        if path == "/api/track":
            try:
                events.append(json.loads(raw.decode("utf-8")))
            except Exception:
                events.append({"event": "<unparseable>"})
            self.send_response(204)
            self.end_headers()
            return
        if path == "/api/checkout":
            # A failed checkout keeps the reader on the page, which is where
            # the record has to be read from.
            self.send_response(500)
            self.end_headers()
            return
        self._json({"ok": True})

    def _json(self, body):
        raw = json.dumps(body).encode()
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(raw)))
        self.end_headers()
        self.wfile.write(raw)


# Installed before the page's own scripts: engine.js's loader starts with
# `if (window.fbq) return`, so this stands in for Meta's. It keeps the name
# and the eventID of every track call — the fourth argument, which is where
# fbq takes it.
PIXEL = """
window.__pixel = [];
window.fbq = function () {
  var a = [].slice.call(arguments);
  if (a[0] === 'track' || a[0] === 'trackCustom') {
    window.__pixel.push([a[1], (a[3] && a[3].eventID) || null]);
  }
};
window.fbq.queue = [];
"""


def to_paywall(page):
    page.wait_for_selector("#cards .card", timeout=10000)
    for i, step in enumerate(STEPS):
        page.query_selector_all("#cards .card")[0].click()
        done = i + 1
        if done in ANCHORS and done < len(STEPS):
            page.wait_for_selector("#screen-interstitial.is-active",
                                   timeout=12000)
            page.click("#mid-cta")
        if done < len(STEPS):
            page.wait_for_function(
                "q => document.getElementById('swipe-caption').textContent === q",
                arg=STEPS[done]["question"], timeout=12000)
    page.wait_for_selector("#result-body:not([hidden])", timeout=15000)
    page.wait_for_timeout(400)


def fired(page):
    return page.evaluate("() => window.__pixel || []")


def tracked(event):
    return [e for e in events if e.get("event") == event]


def pair(label, pixel_name, track_event, page):
    """The pixel's id for `pixel_name` beside the tracking id on `track_event`."""
    px = [i for n, i in fired(page) if n == pixel_name]
    tr = [e.get("pixel_event_id") for e in tracked(track_event)]
    check("%s: %s fired once, with a well-formed eventID"
          % (label, pixel_name),
          len(px) == 1 and px[0] and UUID_RE.match(px[0]), str(px))
    check("  %s carried exactly one pixel id, the same one" % track_event,
          [i for i in tr if i] == px, "%s vs %s" % (tr, px))
    carrier = [e for e in tracked(track_event) if e.get("pixel_event_id")]
    check("  with the session id and the click cookies beside it",
          carrier and UUID_RE.match(carrier[0].get("session_id") or "")
          and carrier[0].get("fbp") == FBP,
          str(carrier[:1]))
    return px[0] if px else None


FBP = "fb.1.1700000000000.42"

socketserver.TCPServer.allow_reuse_address = True
httpd = socketserver.TCPServer(("127.0.0.1", PORT), Handler)
threading.Thread(target=httpd.serve_forever, daemon=True).start()

try:
    with sync_playwright() as pw:
        browser = pw.chromium.launch(executable_path=CHROME)
        context = browser.new_context(viewport={"width": 390, "height": 844})
        context.add_cookies([{"name": "_fbp", "value": FBP,
                              "domain": "127.0.0.1", "path": "/"}])
        page = context.new_page()
        page.add_init_script(PIXEL)
        errs = []
        page.on("pageerror", lambda e: errs.append(str(e)))

        print("\n--- the page arriving ---")
        page.goto("http://127.0.0.1:%d/kitchen" % PORT)
        page.wait_for_selector("#cards .card", timeout=10000)
        page.wait_for_timeout(600)
        pv = pair("load", "PageView", "funnel_start", page)
        check("  and PageView is the first thing the pixel fired",
              fired(page) and fired(page)[0][0] == "PageView")

        print("\n--- the result ---")
        to_paywall(page)
        lead = pair("result", "Lead", "result_view", page)
        check("  no swipe carried a pixel id",
              not any(e.get("pixel_event_id") for e in tracked("swipe")))

        print("\n--- the paywall and the pay tap ---")
        page.click("#cta")
        page.wait_for_selector("#screen-paywall.is-active", timeout=5000)
        page.wait_for_timeout(500)
        ic = pair("open", "InitiateCheckout", "paywall_open", page)
        page.check("#withdrawal-check")
        page.click("#pay-button")
        page.wait_for_selector("#pay-error:not([hidden])", timeout=10000)
        page.wait_for_timeout(500)
        api = pair("pay", "AddPaymentInfo", "pay_tap", page)
        check("four events, four different ids",
              len({pv, lead, ic, api}) == 4 and None not in {pv, lead, ic, api})

        print("\n--- a second tap, and a reload ---")
        page.click("#pay-button")
        page.wait_for_timeout(800)
        check("a second pay tap is tracked again but fires no second pixel "
              "and carries no id",
              len(tracked("pay_tap")) == 2
              and [n for n, _ in fired(page)].count("AddPaymentInfo") == 1
              and not tracked("pay_tap")[1].get("pixel_event_id"))
        stored = page.evaluate(
            "() => JSON.parse(sessionStorage.getItem('mazzin_evid') || '{}')")
        check("the three conversion ids are kept for the session, PageView's "
              "is not",
              stored.get("Lead") == lead
              and stored.get("InitiateCheckout") == ic
              and stored.get("AddPaymentInfo") == api
              and "PageView" not in stored, str(stored))
        events.clear()
        page.reload()
        page.wait_for_selector("#cards .card", timeout=10000)
        page.wait_for_timeout(600)
        pv2 = [i for n, i in fired(page) if n == "PageView"]
        check("a reload fires PageView under a new id, on both sides again",
              len(pv2) == 1 and pv2[0] != pv
              and [e.get("pixel_event_id") for e in tracked("funnel_start")]
              == pv2, str((pv, pv2)))
        check("  and would fire Lead under the id it already has",
              page.evaluate(
                  "() => JSON.parse(sessionStorage.getItem('mazzin_evid'))"
                  ".Lead") == lead)
        check("no page errors", not errs, errs[:3])
        browser.close()
finally:
    httpd.shutdown()

print("\n%d checks, %d failed" % (checks[0], len(fails)))
for f in fails:
    print("  FAIL " + f)
sys.exit(1 if fails else 0)
