#!/usr/bin/env python3
"""The offer was reached, and both funnels say so the same way.

`paywall_view` means the offer got in front of the reader. It is fired by an
IntersectionObserver on the block that holds the price, the consent box and
the pay button — and on a funnel that draws its own result page, that block is
not the container engine.js built. The zodiac module moves those rows into a
card of its own and hides the container it took them from, so the observer was
watching a hidden div, which never intersects anything. Two days of live ad
traffic: 42 result_view, 2 pay_tap, 0 paywall_view. Meta's InitiateCheckout
fires from the same place and was gone with it.

What is asserted here is the whole sequence rather than the one event: exactly
one `paywall_view`, carrying the same attribution kitchen's carries, arriving
before any `pay_tap` and surviving the reader scrolling away and back. Then
the same run against kitchen, whose numbers have to be identical — the fix is
in a module kitchen does not load, and this is what says so.

The pixel is a stub installed before the page's own scripts, so `Lead` and
`InitiateCheckout` are recorded rather than sent.

    python3 tests/test_zodiactracking.py
"""
import http.server
import json
import os
import socketserver
import sys
import threading

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, REPO)

from playwright.sync_api import sync_playwright          # noqa: E402

PORT = 8845
CHROME = "/opt/pw-browsers/chromium-1194/chrome-linux/chrome"

# Where each funnel's offer ends up: the module's own card on one, the
# container engine.js builds on the other. The difference is the bug.
OFFER = {"zodiac": "#result-module .zr-offer", "kitchen": "#commerce"}

fails = []
checks = [0]


def check(label, ok, detail=""):
    checks[0] += 1
    if not ok:
        fails.append("%s %s" % (label, detail))
    print("  %-60s %s%s" % (label, "ok" if ok else "FAIL",
                            ("  " + str(detail)) if not ok else ""))


events = []


class Handler(http.server.SimpleHTTPRequestHandler):
    """The funnel off disk, with the three POSTs a purchase makes recorded."""

    def __init__(self, *a, **kw):
        super().__init__(*a, directory=REPO, **kw)

    def log_message(self, *a):
        pass

    def do_GET(self):
        path = self.path.split("?")[0]
        if path == "/api/pixel-config":
            return self._json({"pixel_id": "111"})
        if path in ("/zodiac", "/kitchen"):
            self.path = "/static/funnel.html"
        return super().do_GET()

    def do_POST(self):
        raw = self.rfile.read(int(self.headers.get("content-length") or 0))
        path = self.path.split("?")[0]
        if path == "/api/track":
            try:
                events.append(json.loads(raw))
            except ValueError:
                events.append({"event": "<unparsable>"})
            return self._json({"ok": True})
        # Recorded in the same stream as the events, because where the session
        # is created relative to `pay_tap` is one of the things under test.
        if path == "/api/checkout":
            events.append({"event": "<<checkout>>"})
            return self._json({"url": "http://127.0.0.1:%d/x?cs=cs_test_1"
                                      % PORT})
        if path == "/api/payment-intent":
            events.append({"event": "<<intent>>"})
            return self._json({"client_secret": "pi_x_secret_y",
                               "publishable_key": "pk_test_x",
                               "amount_cents": 300, "currency": "usd"})
        return self._json({"ok": True})

    def _json(self, body):
        raw = json.dumps(body).encode()
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(raw)))
        self.end_headers()
        self.wfile.write(raw)


# Installed before any of the page's own scripts. engine.js's loader starts
# with `if (window.fbq) return`, so this stands in for Meta's and nothing is
# fetched or sent. Written as source rather than as a function: add_init_script
# evaluates what it is given, so an arrow expression here would be built and
# thrown away — which is exactly what happened on the first attempt, and it
# recorded nothing at all.
PIXEL = """
window.__pixel = [];
window.fbq = function () {
  var a = [].slice.call(arguments);
  if (a[0] === 'track' || a[0] === 'trackCustom') window.__pixel.push(a[1]);
};
window.fbq.queue = [];
"""


def names():
    return [e.get("event") for e in events]


def count(name):
    return names().count(name)


def clear_interstitial(page):
    for _ in range(3):
        mid = page.locator("#screen-interstitial")
        if mid.count() and mid.is_visible():
            page.click("#mid-cta")
            page.wait_for_timeout(600)
        else:
            break


def walk(page, slug):
    """Answer every step and stop on the finished result page."""
    page.add_init_script(PIXEL)
    page.goto("http://127.0.0.1:%d/%s" % (PORT, slug))
    page.wait_for_selector("#cards .card", timeout=25000)
    page.wait_for_timeout(400)
    for _ in range(16):
        try:
            page.wait_for_selector("#cards .card:not(.is-chosen)",
                                   state="visible", timeout=6000)
        except Exception:
            break
        page.wait_for_timeout(320)
        page.locator("#cards .card").first.click()
        page.wait_for_timeout(2100)
        clear_interstitial(page)
    page.wait_for_selector("#result-body", state="visible", timeout=40000)
    page.wait_for_timeout(1500)


def pixel(page):
    return page.evaluate("() => window.__pixel || []")


def issued(page, into):
    """Record the order the browser issues requests in.

    Not the order the server receives them: `track` goes out on sendBeacon and
    the checkout on fetch, and a beacon is the low-priority one — the two race
    on the wire and arrive either way round. This is the page's own order, and
    it is also collected out here rather than in the page because tapping pay
    navigates, and a navigation takes any in-page array with it.
    """
    page.on("request", lambda r: into.append(r.url))


def run(browser, slug):
    print("\n--- %s ---" % slug)
    del events[:]
    page = browser.new_page(viewport={"width": 380, "height": 844})
    requests = []
    issued(page, requests)
    walk(page, slug)

    check("the result was reached", count("result_view") == 1, names())
    check("  and Meta was told once",
          pixel(page).count("Lead") == 1, pixel(page))
    check("nothing has reached checkout yet",
          "InitiateCheckout" not in pixel(page), pixel(page))

    offer = page.locator(OFFER[slug])
    check("the offer is on the page", offer.count() == 1, offer.count())
    page.eval_on_selector(OFFER[slug], "n => n.scrollIntoView({block:'center'})")
    page.wait_for_timeout(1200)

    seen = [e for e in events if e.get("event") == "paywall_view"]
    check("reaching it fires paywall_view, exactly once",
          len(seen) == 1, "%d: %s" % (len(seen), names()))
    check("  attributed the way kitchen attributes it",
          seen and seen[0].get("extra") == {"src": "scroll"},
          seen[0].get("extra") if seen else None)
    check("  and Meta hears InitiateCheckout once",
          pixel(page).count("InitiateCheckout") == 1, pixel(page))

    # The bug in one assertion: on the module funnel the container engine.js
    # built is hidden by the time the offer is on screen, so an observer
    # watching it can never fire. The event above fired anyway.
    hidden = page.evaluate(
        "() => { const c = document.getElementById('commerce');"
        " return !!c && c.hidden; }")
    check("  fired from the block the reader can actually see",
          hidden == (slug == "zodiac"), "commerce hidden=%s" % hidden)

    page.evaluate("() => window.scrollTo(0, 0)")
    page.wait_for_timeout(500)
    page.eval_on_selector(OFFER[slug], "n => n.scrollIntoView({block:'center'})")
    page.wait_for_timeout(900)
    check("leaving and coming back does not fire it again",
          count("paywall_view") == 1, count("paywall_view"))
    check("  nor a second InitiateCheckout",
          pixel(page).count("InitiateCheckout") == 1, pixel(page))

    before = len(events)
    asked = len(requests)
    page.locator("#pay-button").click()
    page.wait_for_timeout(1800)
    tail = names()[before:]
    check("the tap is counted once", tail.count("pay_tap") == 1, tail)
    # Both requests were made; the question is which was asked for first.
    made = [c for c in requests[asked:]
            if "/api/track" in c or "/api/checkout" in c]
    check("  and it was sent before the session was asked for",
          made and "/api/track" in made[0]
          and any("/api/checkout" in c for c in made[1:]), str(made))
    order = names()
    check("  and after the offer was seen",
          order.index("paywall_view") < order.index("pay_tap"), order)
    page.close()
    return {"paywall_view": count("paywall_view"),
            "pay_tap": count("pay_tap"),
            "result_view": count("result_view")}


def main():
    socketserver.TCPServer.allow_reuse_address = True
    httpd = socketserver.TCPServer(("127.0.0.1", PORT), Handler)
    threading.Thread(target=httpd.serve_forever, daemon=True).start()
    try:
        with sync_playwright() as pw:
            browser = pw.chromium.launch(executable_path=CHROME)
            got = {slug: run(browser, slug) for slug in ("zodiac", "kitchen")}
            browser.close()
    finally:
        httpd.shutdown()

    print("\n--- and the two funnels count the same things ---")
    check("the same events, the same number of times",
          got["zodiac"] == got["kitchen"],
          "%s vs %s" % (got["zodiac"], got["kitchen"]))

    print("\n%d checks, %d failed" % (checks[0], len(fails)))
    for line in fails:
        print("  FAIL " + line)
    return 1 if fails else 0


if __name__ == "__main__":
    sys.exit(main())
