#!/usr/bin/env python3
"""No frame of the built-in result before the module's page.

A funnel that names a `result_module` draws its own result page, and for a
while it drew it second: this file's layout went up the moment the analysing
screen came down, and the module's stylesheet and script only started
travelling after that. On a fast connection it was a flicker. On a slow one
the reader sat looking at a white kitchen offer card on a dark celestial
ground — the wrong product, on the screen where the price is.

The module's assets are held back here rather than the connection being
throttled: a fixed delay makes the window a known size, so a regression is a
second and a half of the wrong page rather than something that shows up only
on somebody's train journey. What is measured is every animation frame from
the first tap to the finished page, not a sample — the bug is a flash, and a
sample is exactly what a flash gets past.

The other half is that the fallback still works: with the module withheld
entirely, both pages have to draw this file's own layout rather than nothing,
which is what a half-propagated deploy looks like.

    python3 tests/test_zodiacflash.py
"""
import http.server
import json
import os
import socketserver
import sys
import threading
import time

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, REPO)

from playwright.sync_api import sync_playwright          # noqa: E402

import config                                            # noqa: E402
import database                                          # noqa: E402
import reports                                           # noqa: E402

PORT = 8843
CHROME = "/opt/pw-browsers/chromium-1194/chrome-linux/chrome"

# Long enough that a regression cannot hide inside one frame, short enough
# that the suite is not mostly sleeping.
STALL_MS = 1500

fails = []
checks = [0]


def check(label, ok, detail=""):
    checks[0] += 1
    if not ok:
        fails.append("%s %s" % (label, detail))
    print("  %-60s %s%s" % (label, "ok" if ok else "FAIL",
                            ("  " + str(detail)) if not ok else ""))


database.execute = lambda *a, **kw: None
database.query_all = lambda *a, **kw: []
reports._api = lambda: None

REPORTS = {}
# Flipped by the fallback check: the module 404s, the way a CDN with one
# stale file does.
WITHHOLD = [False]


def build(slug, style_id, sign=None):
    cfg = config.load_funnel(slug)
    choices = []
    for step in cfg["swipe"]["steps"]:
        if sign and step["id"] == "sign":
            choices.append(sign)
        else:
            choices.append(step["pairs"][0]["images"][0]["id"])
    content = reports.start_report(1, slug, style_id, {"water": 9, "moon": 6},
                                   choices=choices)
    content["version"] = "llm-2"
    return content


class Handler(http.server.SimpleHTTPRequestHandler):
    def __init__(self, *a, **kw):
        super().__init__(*a, directory=REPO, **kw)

    def log_message(self, *a):
        pass

    def do_GET(self):
        path = self.path.split("?")[0]
        if path == "/api/pixel-config":
            return self._json({})
        if path == "/api/report":
            slug = "zodiac" if "zodiac" in (self.headers.get("referer") or "") \
                else "kitchen"
            return self._json({"complete": True, "email_masked": "s***@x.com",
                               "report": REPORTS[slug]})
        if WITHHOLD[0] and path.endswith("result_zodiac.js"):
            return self.send_error(404)
        if path in ("/zodiac", "/kitchen"):
            self.path = "/static/funnel.html"
        return super().do_GET()

    def do_POST(self):
        self.rfile.read(int(self.headers.get("content-length") or 0))
        self._json({"ok": True})

    def _json(self, body):
        raw = json.dumps(body).encode()
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(raw)))
        self.end_headers()
        self.wfile.write(raw)


def url(path):
    return "http://127.0.0.1:%d%s" % (PORT, path)


# Every animation frame: what of this file's own result layout is on screen,
# and whether the module's page is up yet.
WATCH = """() => {
  window.__frames = [];
  const vis = (el) => {
    if (!el || el.hidden) return false;
    const s = getComputedStyle(el);
    const r = el.getBoundingClientRect();
    return s.display !== 'none' && s.visibility !== 'hidden'
      && parseFloat(s.opacity) > 0.01 && r.width > 0 && r.height > 0;
  };
  const id = (x) => document.getElementById(x);
  (function tick() {
    window.__frames.push({
      t: Math.round(performance.now()),
      kicker: vis(document.querySelector('.result-kicker')),
      name: vis(id('result-name')),
      report: vis(id('report')),
      commerce: vis(id('commerce')),
      cta: vis(id('cta')),
      banner: vis(document.querySelector('.value-banner')),
      module: vis(id('result-module'))});
    requestAnimationFrame(tick);
  })();
}"""


def frames(page):
    """(total frames, frames showing the built-in layout with no module)."""
    rows = page.evaluate("() => window.__frames || []")
    bad = [r for r in rows
           if (r["kicker"] or r["report"] or r["commerce"] or r["cta"]
               or r["banner"]) and not r["module"]]
    return rows, bad


def stall(page):
    """Hold the module's own files back, so the window has a known size."""
    def handler(route):
        time.sleep(STALL_MS / 1000.0)
        route.continue_()
    page.route("**/result_zodiac.*", handler)


def clear_interstitial(page):
    for _ in range(3):
        mid = page.locator("#screen-interstitial")
        if mid.count() and mid.is_visible():
            page.click("#mid-cta")
            page.wait_for_timeout(600)
        else:
            break


def walk(page, slug):
    """Open the funnel, start the recorder, and answer every step."""
    page.goto(url("/" + slug))
    page.wait_for_selector("#cards .card", timeout=25000)
    page.wait_for_timeout(400)
    page.evaluate(WATCH)
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
    page.wait_for_timeout(1200)


def free_path(browser):
    print("\n--- the free result, with the module held back ---")
    page = browser.new_page(viewport={"width": 380, "height": 844})
    stall(page)
    walk(page, "zodiac")
    rows, bad = frames(page)
    check("the whole run was recorded", len(rows) > 200, len(rows))
    check("no frame of the built-in result before the module's page",
          not bad, "%d of %d frames: %s"
          % (len(bad), len(rows), json.dumps(bad[0]) if bad else ""))
    check("  and the module's page is what drew",
          page.locator("#result-module .zr-kicker").count() == 1)
    check("  the offer is in it, not in this file's own card",
          page.locator("#result-module #pay-button").count() == 1
          and page.locator("#commerce #pay-button").count() == 0)
    page.close()


def delivered_path(browser):
    print("\n--- and the report the mail links to ---")
    page = browser.new_page(viewport={"width": 380, "height": 844})
    stall(page)
    page.goto(url("/zodiac?cs=cs_test_1"))
    page.evaluate(WATCH)
    page.wait_for_selector("#result-module .zr-kicker", timeout=40000)
    page.wait_for_timeout(800)
    rows, bad = frames(page)
    check("the whole arrival was recorded", len(rows) > 40, len(rows))
    check("no frame of the built-in report before the module's page",
          not bad, "%d of %d frames: %s"
          % (len(bad), len(rows), json.dumps(bad[0]) if bad else ""))
    check("  every node of it open",
          page.locator(".zr-node.is-open").count() == 6,
          page.locator(".zr-node.is-open").count())
    page.close()


def kitchen_path(browser):
    print("\n--- kitchen names no module, so kitchen reveals as it always did ---")
    page = browser.new_page(viewport={"width": 380, "height": 844})
    walk(page, "kitchen")
    rows, bad = frames(page)
    check("its own layout is on screen", bad, len(bad))
    check("  and no module page was ever built",
          page.locator("#result-module").count() == 0)
    page.close()


def fallback(browser):
    print("\n--- with the module withheld, both pages still draw ---")
    WITHHOLD[0] = True
    try:
        page = browser.new_page(viewport={"width": 380, "height": 844})
        walk(page, "zodiac")
        check("the free page falls back to this file's own",
              page.locator("#commerce #pay-button").count() == 1,
              page.locator("#commerce #pay-button").count())
        check("  and the module root is not left in front of it",
              page.evaluate("""() => { const m =
                  document.getElementById('result-module');
                  return !m || m.hidden; }"""))
        page.close()

        page = browser.new_page(viewport={"width": 380, "height": 844})
        page.goto(url("/zodiac?cs=cs_test_1"))
        page.wait_for_selector("#report .section", timeout=30000)
        # The count is not six: the built-in report draws its own furniture
        # alongside the sections. What has to be true is that every section
        # this reader paid for is on the page.
        titles = page.eval_on_selector_all(
            "#report .section-title", "ns => ns.map(n => n.innerText.trim())")
        want = [s["title"] for s in REPORTS["zodiac"]["sections"]]
        check("the delivered page falls back to the built-in report",
              all(t in titles for t in want), str(titles))
        page.close()
    finally:
        WITHHOLD[0] = False


def main():
    REPORTS["zodiac"] = build("zodiac", "deep_water", "sign_scorpio")
    REPORTS["kitchen"] = build("kitchen", "modern_rustic")

    socketserver.TCPServer.allow_reuse_address = True
    httpd = socketserver.TCPServer(("127.0.0.1", PORT), Handler)
    threading.Thread(target=httpd.serve_forever, daemon=True).start()
    try:
        with sync_playwright() as pw:
            browser = pw.chromium.launch(executable_path=CHROME)
            free_path(browser)
            delivered_path(browser)
            kitchen_path(browser)
            fallback(browser)
            browser.close()
    finally:
        httpd.shutdown()

    print("\n%d checks, %d failed" % (checks[0], len(fails)))
    for line in fails:
        print("  FAIL " + line)
    return 1 if fails else 0


if __name__ == "__main__":
    sys.exit(main())
