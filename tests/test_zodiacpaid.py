#!/usr/bin/env python3
"""The paid zodiac report, drawn in a browser.

The whole of the zodiac report design rests on one claim: that naming its
sections after kitchen's ids is what makes them draw. Neither renderer sniffs
the shape of a section — `SECTION_BODY[sec.id]` in engine.js and
`PDF_BODY[id]` in reports.py both switch on the id, and an id they do not
carry falls through to a bare paragraph. That failure is silent and it looks
like a styling problem, so it is worth a browser rather than an assertion
about a dict.

The zodiac funnel now draws its delivered report through its own result
module, so this file serves that module as a 404 and tests what engine.js
falls back to when the CDN does not hand it over. That fallback is the reason
the ids were chosen the way they were, and it is the path a reader lands on
when a deploy is half-propagated — which is exactly when nobody is watching.
The module's own delivered view is tested in test_zodiacdelivered.py.

The report served here is a real one: reports.start_report with generation
switched off, which is the documented no-key path, so what the page is handed
is the same object a purchase would store. No database, no Stripe, no model.

    python3 tests/test_zodiacpaid.py
"""
import http.server
import json
import os
import socketserver
import sys
import threading

# The repo root, derived from this file rather than hardcoded: a suite that
# only runs from one absolute path is a suite that stops running the first
# time the checkout moves.
REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, REPO)

from playwright.sync_api import sync_playwright          # noqa: E402

import config                                            # noqa: E402
import database                                          # noqa: E402
import reports                                           # noqa: E402

ROOT = REPO
PORT = 8801
CHROME = "/opt/pw-browsers/chromium-1194/chrome-linux/chrome"

fails = []
checks = [0]


def check(label, ok, detail=""):
    checks[0] += 1
    if not ok:
        fails.append("%s %s" % (label, detail))
    print("  %-60s %s%s" % (label, "ok" if ok else "FAIL",
                            ("  " + str(detail)) if not ok else ""))


def build():
    """The report a Leo who bought Radiant Fire would have stored."""
    database.execute = lambda *a, **k: None
    database.query_all = lambda *a, **k: []
    reports._api = lambda: None                 # no key: the stub path
    cfg = config.load_funnel("zodiac")
    choices = []
    for step in cfg["swipe"]["steps"]:
        if step["id"] == "season":
            choices.append("se2b")              # summer
        elif step["id"] == "sign":
            choices.append("sign_leo")
        else:
            choices.append(step["pairs"][0]["images"][0]["id"])
    content = reports.start_report(1, "zodiac", "radiant_fire",
                                   {"fire": 9, "sun": 7, "bold": 6},
                                   choices=choices)
    # The page only draws typed sections for a finished report.
    content["version"] = "llm-2"
    return content


CONTENT = build()
MODULE = config.load_funnel("zodiac")["result_module"]


class Handler(http.server.SimpleHTTPRequestHandler):
    """static/ off disk, /zodiac is the shell, /api/report is the report."""

    def __init__(self, *a, **kw):
        super().__init__(*a, directory=ROOT, **kw)

    def log_message(self, *a):
        pass

    def do_GET(self):
        path = self.path.split("?")[0]
        if path == "/api/pixel-config":
            return self._json({})
        if path == "/api/report":
            return self._json({"complete": True,
                               "email_masked": "s***@example.com",
                               "report": CONTENT})
        if path == "/zodiac":
            self.path = "/static/funnel.html"
        # The one asset this suite withholds: with no module to hand over,
        # engine.js draws the report itself, which is what is under test.
        if path == MODULE:
            self.send_error(404)
            return
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


# Each section's title, and a node only that section's own builder makes.
# `.section-body` is no use as a tell: dnaBody uses that class for a narrative
# paragraph as well as buildSection using it for the prose fallback.
MARKERS = [
    ("Your Power Palette & Talismans", ".swatch-list", 4, ".swatch-row"),
    ("5 Hidden Strengths & Blind Spots", ".mistake-list", 5, ".mistake"),
    ("Your Cosmic Blueprint", ".implications", 3, ".implications li"),
    ("Love & Compatibility", ".verdict-list", 4, ".verdict"),
    ("Career & Money Path", ".splurge-card", 3, ".save-item"),
    ("Your 12-Month Energy Map", ".buy-list", 12, ".buy-name"),
]

MONTHS = ["January", "February", "March", "April", "May", "June", "July",
          "August", "September", "October", "November", "December"]


def main():
    socketserver.TCPServer.allow_reuse_address = True
    httpd = socketserver.TCPServer(("127.0.0.1", PORT), Handler)
    threading.Thread(target=httpd.serve_forever, daemon=True).start()
    try:
        with sync_playwright() as pw:
            browser = pw.chromium.launch(executable_path=CHROME)
            page = browser.new_page(viewport={"width": 390, "height": 844})
            page.goto("http://127.0.0.1:%d/zodiac?cs=cs_test_123" % PORT)
            page.wait_for_selector("#report .section", timeout=20000)
            check("the module was withheld, so the fallback drew",
                  page.locator("#result-module").count() == 0
                  or page.get_attribute("#result-module", "hidden")
                  is not None)
            page.wait_for_timeout(600)
            run(page)
            browser.close()
    finally:
        httpd.shutdown()

    print("\n%d checks, %d failed" % (checks[0], len(fails)))
    for line in fails:
        print("  FAIL " + line)
    return 1 if fails else 0


def run(page):
    print("\n--- every section draws its own shape ---")
    titles = page.eval_on_selector_all(
        "#report .section-title", "ns => ns.map(n => n.innerText.trim())")
    for title, marker, count, row in MARKERS:
        check("%-34s is on the page" % title, title in titles, str(titles))
        drew = page.evaluate(
            """([t, m]) => {
                 var secs = document.querySelectorAll('#report .section');
                 for (var i = 0; i < secs.length; i++) {
                   var h = secs[i].querySelector('.section-title');
                   if (h && h.innerText.trim() === t) {
                     return !!secs[i].querySelector(m);
                   }
                 }
                 return null;
               }""", [title, marker])
        check("  drew %-14s rather than a paragraph" % marker, drew is True,
              drew)
        check("  with %d %s" % (count, row),
              page.locator("#report " + row).count() == count,
              page.locator("#report " + row).count())

    print("\n--- the year map ---")
    months = page.eval_on_selector_all(
        "#report .buy-name", "ns => ns.map(n => n.innerText.trim())")
    check("all twelve months, in calendar order", months == MONTHS,
          str(months))
    notes = page.eval_on_selector_all(
        "#report .buy-note", "ns => ns.map(n => n.innerText.trim())")
    check("  two are marked strongest",
          sum(n.startswith("Strongest month:") for n in notes) == 2)
    check("  one is marked quiet",
          sum(n.startswith("Quiet month:") for n in notes) == 1)
    # engine.js labels the skip block "Skip" and strikes the name through.
    # That is right for a kitchen worth not buying and wrong for a quiet month
    # in somebody's year, which is why all twelve are items.
    check("  no month is struck out under a Skip label",
          page.locator("#report .skip-block").count() == 0,
          page.locator("#report .skip-block").count())

    print("\n--- what a zodiac buyer must never be shown ---")
    body = page.inner_text("#report")
    hit = reports._banned_hit(body, reports.ZODIAC_BANNED)
    check("the delivered page says nothing banned", hit is None, hit)
    for word in ("kitchen", "worktop", "cabinet", "splashback", "renovation"):
        check("  says nothing about a %s" % word, word not in body.lower())
    # engine.js hardcodes SAMPLE_SRC to one image of the kitchen report, so
    # zodiac's config carries no sample_link and the button must not appear.
    check("no sample link, because the only sample is kitchen's",
          page.locator("#sample-link").count() == 0)


if __name__ == "__main__":
    sys.exit(main())
