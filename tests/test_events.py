#!/usr/bin/env python3
"""Watch which tracking events actually fire, and when.

Serves the funnel, records every /api/track body in order, and drives three
runs of the checkout tail:

  ok      /api/checkout returns a url  -> pay_tap, then the redirect
  http    /api/checkout returns 500    -> pay_tap, then checkout_error
  dead    /api/checkout never connects -> pay_tap, then checkout_error

`python3 events.py [ok|http|dead|all]`   (default all)
"""
import http.server
import json
import os
import socketserver
import sys
import threading
# The repo root, derived from this file rather than hardcoded: a suite
# that only runs from one absolute path is a suite that stops running the
# first time the checkout moves.
REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


from playwright.sync_api import sync_playwright

ROOT = REPO
PORT = 8741

cfg = json.load(open(os.path.join(ROOT, "funnels/kitchen.json")))
STEPS = cfg["swipe"]["steps"]
ANCHORS = {i["after_step"] for i in cfg["interstitials"]}
GRID = {"grid4": 4, "grid6": 6}

events = []          # every /api/track body, in arrival order
checkout_mode = ["ok"]
fails = []


def check(label, ok, detail=""):
    if not ok:
        fails.append("%s %s" % (label, detail))
    print("    %-52s %s%s" % (label, "ok" if ok else "FAIL",
                              ("  " + str(detail)) if not ok else ""))


def names():
    return [e.get("event") for e in events]


class Handler(http.server.SimpleHTTPRequestHandler):
    def __init__(self, *a, **kw):
        super().__init__(*a, directory=ROOT, **kw)

    def log_message(self, *a):
        pass

    def do_GET(self):
        path = self.path.split("?")[0]
        if path == "/api/pixel-config":
            return self._json({})
        # This suite is about the two-screen checkout's events — the result CTA
        # that opens the paywall, then the pay button, then the error path. That
        # flow now lives behind `single_page: false`, so the flag is turned off
        # here rather than the assertions being rewritten around a screen they
        # were never about. single.py owns the single-page event map.
        if path == "/static/funnels/kitchen.json":
            two_screen = json.loads(json.dumps(cfg))
            two_screen["checkout"]["single_page"] = False
            two_screen["checkout"].pop("commerce", None)
            return self._json(two_screen)
        if path == "/kitchen":
            self.path = "/static/funnel.html"
        if path == "/paid":                      # where a real redirect lands
            body = b"<!doctype html><title>stripe</title>redirected"
            self.send_response(200)
            self.send_header("Content-Type", "text/html")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)
            return
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
            if checkout_mode[0] == "http":
                self.send_response(500)
                self.end_headers()
                return
            return self._json({"url": "http://127.0.0.1:%d/paid" % PORT})
        self._json({"ok": True})

    def _json(self, body):
        raw = json.dumps(body).encode()
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(raw)))
        self.end_headers()
        self.wfile.write(raw)


def to_paywall(page):
    """Tap through the quiz, open the paywall, tick the consent box."""
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


def run(mode):
    print("\n=== checkout %s ===" % mode)
    checkout_mode[0] = mode
    del events[:]

    with sync_playwright() as pw:
        b = pw.chromium.launch(
            executable_path="/opt/pw-browsers/chromium-1194/chrome-linux/chrome")
        page = b.new_page(viewport={"width": 390, "height": 844})
        errs = []
        page.on("pageerror", lambda e: errs.append(str(e)))
        if mode == "dead":
            # Nothing answers the checkout call at all: the fetch rejects
            # rather than resolving with a bad status.
            page.route("**/api/checkout", lambda route: route.abort())
        page.goto("http://127.0.0.1:%d/kitchen" % PORT)

        to_paywall(page)
        page.wait_for_timeout(300)
        before = names()
        check("result screen has not claimed a pay_tap",
              "pay_tap" not in before, before)
        check("result_view fired", "result_view" in before, before)

        # --- the result CTA: opens the paywall, nothing more ---------------
        page.click("#cta")
        page.wait_for_selector("#screen-paywall.is-active", timeout=5000)
        page.wait_for_timeout(500)
        after_open = names()
        check("paywall_open fired on the result CTA",
              "paywall_open" in after_open, after_open)
        check("still no pay_tap from merely opening the paywall",
              "pay_tap" not in after_open, after_open)
        check("paywall_open lands after result_view",
              after_open.index("result_view") < after_open.index("paywall_open"),
              after_open)

        # --- the pay button: the real attempt ------------------------------
        page.check("#withdrawal-check")
        page.click("#pay-button")

        if mode == "ok":
            page.wait_for_url("**/paid", timeout=10000)
            page.wait_for_timeout(400)
            final = names()
            check("pay_tap fired on the pay button", "pay_tap" in final, final)
            check("no checkout_error on a good checkout",
                  "checkout_error" not in final, final)
            check("the redirect happened", "/paid" in page.url, page.url)
        else:
            page.wait_for_selector("#pay-error:not([hidden])", timeout=10000)
            page.wait_for_timeout(500)
            final = names()
            check("pay_tap fired on the pay button", "pay_tap" in final, final)
            check("checkout_error fired on the failure",
                  "checkout_error" in final, final)
            check("pay_tap comes before checkout_error",
                  "pay_tap" in final and "checkout_error" in final
                  and final.index("pay_tap") < final.index("checkout_error"),
                  final)
            err = [e for e in events if e.get("event") == "checkout_error"][0]
            check("checkout_error carries no details payload",
                  "extra" not in err and "step" not in err,
                  json.dumps(err))
            check("the reader is told", bool(page.inner_text("#pay-error")),
                  page.inner_text("#pay-error"))
            check("the button is usable again",
                  page.eval_on_selector("#pay-button", "n => !n.disabled"))

        check("no page errors", not errs, errs[:3])
        print("    sequence: %s" % " -> ".join(names()[-6:]))
        b.close()


def main():
    which = sys.argv[1] if len(sys.argv) > 1 else "all"
    socketserver.TCPServer.allow_reuse_address = True
    httpd = socketserver.TCPServer(("127.0.0.1", PORT), Handler)
    threading.Thread(target=httpd.serve_forever, daemon=True).start()
    try:
        for mode in (["ok", "http", "dead"] if which == "all" else [which]):
            run(mode)
    finally:
        httpd.shutdown()
    print("\n%d failed" % len(fails))
    for f in fails:
        print("  FAIL " + f)
    return 1 if fails else 0


if __name__ == "__main__":
    raise SystemExit(main())
