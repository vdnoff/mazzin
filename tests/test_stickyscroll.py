#!/usr/bin/env python3
"""What the sticky bar does when it is tapped, now that it does not charge.

The bar briefly took the payment itself. This checks it is back to asking for
a scroll: the block arrives, no checkout call leaves the page, `pay_tap` is
still the pay button's alone, and `paywall_view` still says the bar was what
sent them. Then the pay button is pressed, to show the money path is intact
one step further down.

    python3 stickyscroll.py
"""
import json
import os
import socketserver
import sys
import threading

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from playwright.sync_api import sync_playwright   # noqa: E402
from test_walk import Handler as WalkHandler, PORT, STEPS, ANCHORS  # noqa: E402

CHROME = "/opt/pw-browsers/chromium-1194/chrome-linux/chrome"

TRACKED = []
CHECKOUTS = []
fails = []
checks = [0]


def check(label, ok, detail=""):
    checks[0] += 1
    if not ok:
        fails.append("%s %s" % (label, detail))
    print("  %-58s %s%s" % (label, "ok" if ok else "FAIL",
                            ("  " + str(detail)) if not ok else ""))


MISSING = []


class Handler(WalkHandler):
    def send_error(self, code, *a, **kw):
        MISSING.append("%s %s" % (code, self.path))
        return super().send_error(code, *a, **kw)

    def do_GET(self):
        if self.path.split("?")[0] == "/paid":
            # The empty icon href is what stops the browser asking for
            # /favicon.ico and 404ing against a page that is standing in
            # for Stripe. funnel.html declares its own icons, so the real
            # page never makes that request.
            body = (b'<!doctype html><title>stripe</title>'
                    b'<link rel="icon" href="data:,">redirected')
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
                TRACKED.append(json.loads(raw.decode("utf-8")))
            except Exception:
                TRACKED.append({"event": "<unparseable>"})
            self.send_response(204)
            self.end_headers()
            return
        if path == "/api/checkout":
            # Counted, so "no checkout fires" is about the call actually
            # leaving the page rather than about the page not having moved.
            CHECKOUTS.append(True)
            raw = json.dumps(
                {"url": "http://127.0.0.1:%d/paid" % PORT}).encode()
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(raw)))
            self.end_headers()
            self.wfile.write(raw)
            return
        self.send_response(204)
        self.end_headers()


def names():
    return [e["event"] for e in TRACKED]


def extra_of(event):
    for body in TRACKED:
        if body["event"] == event:
            return body.get("extra")
    return None


def walk(page):
    page.wait_for_selector("#cards .card", timeout=10000)
    for index, step in enumerate(STEPS):
        page.query_selector_all("#cards .card")[0].click()
        done = index + 1
        if done in ANCHORS and done < len(STEPS):
            page.wait_for_selector("#screen-interstitial.is-active",
                                   timeout=12000)
            page.click("#mid-cta")
        if done < len(STEPS):
            page.wait_for_function(
                "q => document.getElementById('swipe-caption').textContent === q",
                arg=STEPS[done]["question"], timeout=15000)
    page.wait_for_selector("#result-body:not([hidden])", timeout=20000)
    page.wait_for_timeout(500)


def main():
    socketserver.TCPServer.allow_reuse_address = True
    httpd = socketserver.TCPServer(("127.0.0.1", PORT), Handler)
    threading.Thread(target=httpd.serve_forever, daemon=True).start()
    try:
        with sync_playwright() as pw:
            browser = pw.chromium.launch(executable_path=CHROME)
            page = browser.new_page(viewport={"width": 390, "height": 844})
            errors = []
            page.on("pageerror", lambda e: errors.append(str(e)))
            page.on("console",
                    lambda m: errors.append(m.text) if m.type == "error" else None)
            page.on("response", lambda r: errors.append(
                "HTTP %d %s" % (r.status, r.url)) if r.status >= 400 else None)
            page.goto("http://127.0.0.1:%d/kitchen" % PORT)
            walk(page)

            print("\n--- the bar, armed but not yet tapped ---")
            page.evaluate("""() => { const p = document.querySelector(
                '#report .section'); window.scrollTo(0, p.getBoundingClientRect()
                .bottom + window.scrollY + 60); }""")
            page.wait_for_timeout(600)
            check("it is up", page.eval_on_selector("#sticky-cta",
                                                    "n => !n.hidden"))
            check("the offer has not been reached",
                  "paywall_view" not in names(), names())
            check("consent is pre-checked, which used to arm the shortcut",
                  page.eval_on_selector("#withdrawal-check", "n => n.checked"))
            off = page.eval_on_selector(
                "#commerce",
                "n => Math.round(n.getBoundingClientRect().top)")
            check("the block is off the bottom of the screen", off > 844, off)

            print("\n--- tapping it ---")
            page.click("#sticky-cta")
            page.wait_for_timeout(1600)          # let the smooth scroll land
            check("no checkout call left the page", not CHECKOUTS, CHECKOUTS)
            check("the page did not go to Stripe",
                  "/paid" not in page.url, page.url)
            check("the reader is still on the result",
                  page.eval_on_selector("#result-body", "n => !n.hidden"))
            check("the commerce block is on screen",
                  page.eval_on_selector(
                      "#commerce",
                      """n => { const r = n.getBoundingClientRect();
                         return r.top < innerHeight && r.bottom > 0; }"""),
                  page.eval_on_selector(
                      "#commerce",
                      "n => Math.round(n.getBoundingClientRect().top)"))
            check("the pay button is with them",
                  page.eval_on_selector(
                      "#pay-button",
                      """n => { const r = n.getBoundingClientRect();
                         return r.top < innerHeight && r.bottom > 0; }"""))
            check("the bar takes itself away at the offer",
                  page.eval_on_selector("#sticky-cta", "n => n.hidden"))

            seen = names()
            check("sticky_cta fired on the tap", "sticky_cta" in seen, seen)
            check("  exactly once", seen.count("sticky_cta") == 1, seen)
            check("paywall_view fired when the block arrived",
                  "paywall_view" in seen, seen)
            check("  and it says the bar sent them",
                  extra_of("paywall_view") == {"src": "sticky"},
                  extra_of("paywall_view"))
            check("  in that order",
                  seen.index("sticky_cta") < seen.index("paywall_view"), seen)
            check("no pay_tap — nothing was pressed that takes money",
                  "pay_tap" not in seen, seen)
            check("and no checkout_error either",
                  "checkout_error" not in seen, seen)

            print("\n--- the button they were sent to still works ---")
            page.click("#pay-button")
            page.wait_for_url("**/paid", timeout=10000)
            page.wait_for_timeout(300)
            seen = names()
            check("one checkout call, from the button", len(CHECKOUTS) == 1,
                  CHECKOUTS)
            check("pay_tap fired there", "pay_tap" in seen, seen)
            check("  exactly once", seen.count("pay_tap") == 1, seen)
            check("  after paywall_view",
                  seen.index("paywall_view") < seen.index("pay_tap"), seen)
            check("it reached Stripe", "/paid" in page.url, page.url)
            check("no page errors", not errors, errors[:3])
            check("nothing 404d", not MISSING, MISSING)
            print("    funnel: %s" % " -> ".join(
                [n for n in seen if n not in ("swipe", "interstitial")]))
            browser.close()
    finally:
        httpd.shutdown()

    print("\n%d checks, %d failed" % (checks[0], len(fails)))
    for f in fails:
        print("  FAIL " + f)
    return 1 if fails else 0


if __name__ == "__main__":
    raise SystemExit(main())
