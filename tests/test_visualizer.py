#!/usr/bin/env python3
"""The second funnel, in a browser, from first tap to delivered report.

/kitchen-visualizer is walked end to end: the quiz, the free result with its
$7 offer and its promo line, a checkout that comes back with a Stripe url, and
the return from Stripe with ?cs=cs_test_… that polls out a finished report.
Then /kitchen is walked the same way to show the live funnel did not move.

    python3 visualizer.py
"""
import json
import os
import socketserver
import sys
import threading

# The repo root, derived from this file rather than hardcoded: a suite
# that only runs from one absolute path is a suite that stops running the
# first time the checkout moves.
REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from playwright.sync_api import sync_playwright   # noqa: E402
from test_walk import Handler as WalkHandler, PORT, ANCHORS   # noqa: E402

ROOT = REPO
SHOTS = os.path.dirname(os.path.abspath(__file__))
CHROME = "/opt/pw-browsers/chromium-1194/chrome-linux/chrome"

CFG = {slug: json.load(open(os.path.join(ROOT, "funnels/%s.json" % slug)))
       for slug in ("kitchen", "kitchen-visualizer")}

CHECKOUTS = []
fails = []
checks = [0]


def check(label, ok, detail=""):
    checks[0] += 1
    if not ok:
        fails.append("%s %s" % (label, detail))
    print("  %-60s %s%s" % (label, "ok" if ok else "FAIL",
                            ("  " + str(detail)) if not ok else ""))


def report_for(slug):
    """A finished report, the shape /api/report serves after the webhook."""
    cfg = CFG[slug]
    titles = {s["id"]: s["title"] for s in cfg["report"]["sections"]}
    data = {
        "palette": {"intro": "Three colours carry this room.",
                    "colors": [{"name": "Oat Linen", "hex": "#E5DAC8",
                                "role": "dominant", "finish": "matt",
                                "where": "the cream you kept choosing"}],
                    "closing_rule": "Sixty oat, thirty oak, ten clay."},
        "mistakes": {"items": [{"title": "Matching every wood tone",
                                "body": "Three identical oaks read as laminate.",
                                "fix": "Age one piece past the rest."}]},
        "materials": {"intro": "Aged brass against smoked oak.",
                      "pairs": [{"combo": "Oak + marble", "verdict": "works",
                                 "why": "One cold thing in a warm room."}],
                      "rule": "One warm metal, one cold stone."},
        "shopping": {"items": [{"name": "The table",
                                "priority_note": "Buy it first."}], "skip": []},
        "dna": {"narrative": ["Your picks lean warm."],
                "implications": ["Buy the timber first."]},
        "splurge": {"splurge": {"item": "The joinery",
                                "why": "It is the thing you touch."},
                    "saves": [{"item": "Appliances", "why": "They all cook."}],
                    "split_note": "Spend up, save down."},
    }
    return {
        "complete": True,
        "email_masked": "s***@example.com",
        "report": {
            "version": "llm-2", "funnel": slug,
            "style_id": cfg["styles"][0]["id"],
            "style_name": cfg["styles"][0]["name"],
            "visuals": {"moodboard": "mp5", "materials": ["c4b", "b8a"]},
            "sections": [{"id": sid, "title": titles[sid], "data": data[sid]}
                         for sid in [s["id"] for s in cfg["report"]["sections"]]],
        },
    }


class Handler(WalkHandler):
    """Serves both funnels, a checkout that answers, and a paid report."""

    def do_GET(self):
        path = self.path.split("?")[0]
        if path == "/api/pixel-config":
            return self._json({})
        if path == "/api/visualizer/status":
            # This suite is about the funnel, not the feature — it stands in
            # for a server that has the endpoint and nothing uploaded yet.
            return self._json({"status": "none", "generations": 0,
                               "max_generations": 2, "remaining": 2,
                               "has_source": False})
        if path == "/api/report":
            # Which funnel this reader bought is not in the query — the real
            # endpoint reads it off the purchase row. The last checkout is the
            # one being returned from.
            slug = CHECKOUTS[-1]["funnel"] if CHECKOUTS else "kitchen"
            return self._json(report_for(slug))
        if path in ("/kitchen", "/kitchen-visualizer"):
            self.path = "/static/funnel.html"
        return super().do_GET()

    def do_POST(self):
        path = self.path.split("?")[0]
        raw = self.rfile.read(int(self.headers.get("content-length") or 0))
        if path == "/api/checkout":
            body = json.loads(raw.decode("utf-8"))
            CHECKOUTS.append(body)
            # A test-mode session id, which is what a `stripe_mode: test`
            # funnel really comes back with.
            return self._json({
                "url": "http://127.0.0.1:%d/%s?cs=cs_test_walk%d"
                       % (PORT, body["funnel"], len(CHECKOUTS))})
        self.send_response(204)
        self.end_headers()

    def _json(self, body):
        raw = json.dumps(body).encode()
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(raw)))
        self.end_headers()
        self.wfile.write(raw)


def walk(page, slug):
    steps = CFG[slug]["swipe"]["steps"]
    page.wait_for_selector("#cards .card", timeout=10000)
    for index, step in enumerate(steps):
        page.query_selector_all("#cards .card")[0].click()
        done = index + 1
        if done in ANCHORS and done < len(steps):
            page.wait_for_selector("#screen-interstitial.is-active",
                                   timeout=12000)
            page.click("#mid-cta")
        if done < len(steps):
            page.wait_for_function(
                "q => document.getElementById('swipe-caption').textContent === q",
                arg=steps[done]["question"], timeout=15000)
    page.wait_for_selector("#result-body:not([hidden])", timeout=20000)
    page.wait_for_timeout(500)


# This box has no route to js.stripe.com, and the kitchen-visualizer paywall now
# asks for one. Answered here with an empty script: window.Stripe stays
# undefined, engine.js takes its no-wallet fallback, and the run is not polluted
# by a tunnel error that says nothing about what is under test. express.py is
# where that path is actually exercised.
def no_stripe(page):
    page.route("https://js.stripe.com/**",
               lambda r: r.fulfill(status=200,
                                   content_type="application/javascript",
                                   body=""))
    return page


def main():
    socketserver.TCPServer.allow_reuse_address = True
    httpd = socketserver.TCPServer(("127.0.0.1", PORT), Handler)
    threading.Thread(target=httpd.serve_forever, daemon=True).start()
    try:
        with sync_playwright() as pw:
            browser = pw.chromium.launch(executable_path=CHROME)

            # --- the new funnel ---------------------------------------
            print("\n--- /kitchen-visualizer, first tap to delivered report ---")
            page = browser.new_page(viewport={"width": 390, "height": 844},
                                    device_scale_factor=2)
            no_stripe(page)
            errors = []
            page.on("pageerror", lambda e: errors.append(str(e)))
            page.on("console",
                    lambda m: errors.append(m.text) if m.type == "error" else None)
            page.on("response", lambda r: errors.append(
                "%d %s" % (r.status, r.url)) if r.status >= 400 else None)

            page.goto("http://127.0.0.1:%d/kitchen-visualizer" % PORT)
            walk(page, "kitchen-visualizer")

            vis = CFG["kitchen-visualizer"]
            check("it names a style", bool(page.inner_text("#result-name")))
            check("the promo line sits under the elements strip",
                  page.eval_on_selector(
                      ".section-elements .elements-promo",
                      "n => n.textContent") == vis["style_elements"]["promo"],
                  page.eval_on_selector_all(".elements-promo",
                                            "ns => ns.map(n => n.textContent)"))
            check("  and it is the last thing in that section",
                  page.eval_on_selector(
                      ".section-elements",
                      "n => n.lastElementChild.className") == "elements-promo")
            check("the headline is priced at $7",
                  page.inner_text(".commerce .anchor-head")
                  == "A $7 decision that saves you $4,000+",
                  page.inner_text(".commerce .anchor-head"))
            check("  with the saving still in the accent",
                  page.inner_text(".commerce .anchor-head .money") == "$4,000+")
            check("the price row says 7.00 USD",
                  page.inner_text("#price")
                  == "7.00 USD · one-time · no subscription",
                  page.inner_text("#price"))
            check("the button asks for $7",
                  page.inner_text("#pay-button") == "Get my report for $7",
                  page.inner_text("#pay-button"))
            check("the consent line is priced from config too",
                  "One-time $7" in page.inner_text("#withdrawal-text"),
                  page.inner_text("#withdrawal-text"))
            rows = page.eval_on_selector_all(
                ".commerce .manifest-row",
                """ns => ns.map(n => ({text: n.querySelector('.manifest-text')
                     .textContent, hero: n.classList.contains('is-hero')}))""")
            check("seven manifest rows", len(rows) == 7, len(rows))
            check("  the visualization is first",
                  rows[0]["text"] == vis["checkout"]["manifest"][0],
                  rows[0]["text"])
            check("  and it is the one wearing the accent",
                  rows[0]["hero"] and sum(r["hero"] for r in rows) == 1,
                  [r["hero"] for r in rows])
            page.screenshot(path=os.path.join(SHOTS, "shot-visualizer.png"),
                            full_page=True)

            print("\n--- paying, on the test key ---")
            page.click("#pay-button")
            page.wait_for_url("**/kitchen-visualizer?cs=*", timeout=10000)
            check("checkout was asked for this funnel",
                  CHECKOUTS and CHECKOUTS[-1]["funnel"] == "kitchen-visualizer",
                  CHECKOUTS[-1]["funnel"] if CHECKOUTS else None)
            check("  and it carried the whole run",
                  len(CHECKOUTS[-1].get("choices") or []) == 13
                  and bool(CHECKOUTS[-1].get("tag_scores")),
                  len(CHECKOUTS[-1].get("choices") or []))
            check("Stripe sent them back with a cs_test_ session",
                  "cs=cs_test_" in page.url, page.url)

            page.wait_for_selector("#result-body:not([hidden])", timeout=20000)
            page.wait_for_selector(".report-unlocked .section", timeout=20000)
            page.wait_for_timeout(1200)
            titles = page.eval_on_selector_all(
                "#report .section",
                "ns => ns.map(n => n.querySelector('.section-title').textContent)")
            want = [s["title"] for s in vis["report"]["sections"]]
            check("the report is delivered, in config order",
                  [t for t in titles if t in want] == want, titles)
            check("  with the elements strip in it",
                  "Your Style Elements" in titles, titles)
            check("  the palette carries real codes now",
                  "#E5DAC8" in page.inner_text("#report"))
            check("  and nothing is left locked",
                  page.eval_on_selector_all(".dissolve", "n => n.length") == 0
                  and page.eval_on_selector_all(".locked-lock",
                                                "n => n.length") == 0)
            check("the offer is gone from a paid page",
                  page.eval_on_selector("#commerce", "n => n.hidden"))
            check("no page errors on the whole run", not errors, errors[:3])
            page.screenshot(path=os.path.join(SHOTS, "shot-visualizer-paid.png"),
                            full_page=True)
            page.close()

            # --- the live funnel, unmoved -----------------------------
            print("\n--- /kitchen, unchanged ---")
            page = browser.new_page(viewport={"width": 390, "height": 844})
            no_stripe(page)
            errors = []
            page.on("pageerror", lambda e: errors.append(str(e)))
            page.on("response", lambda r: errors.append(
                "%d %s" % (r.status, r.url)) if r.status >= 400 else None)
            page.goto("http://127.0.0.1:%d/kitchen" % PORT)
            walk(page, "kitchen")
            kit = CFG["kitchen"]
            check("still priced at $3",
                  page.inner_text(".commerce .anchor-head")
                  == "A $3 decision that saves you $4,000+",
                  page.inner_text(".commerce .anchor-head"))
            check("  and the price row agrees",
                  page.inner_text("#price")
                  == "3.00 USD · one-time · no subscription",
                  page.inner_text("#price"))
            rows = page.eval_on_selector_all(
                ".commerce .manifest-row",
                """ns => ns.map(n => ({text: n.querySelector('.manifest-text')
                     .textContent, hero: n.classList.contains('is-hero')}))""")
            check("six manifest rows, as before", len(rows) == 6, len(rows))
            check("  and the mistakes row keeps the accent",
                  rows[1]["hero"] and sum(r["hero"] for r in rows) == 1,
                  [(r["hero"], r["text"][:24]) for r in rows])
            check("no promo line on this funnel",
                  page.eval_on_selector_all(".elements-promo",
                                            "n => n.length") == 0)
            check("no page errors", not errors, errors[:3])
            browser.close()
    finally:
        httpd.shutdown()

    print("\n%d checks, %d failed" % (checks[0], len(fails)))
    for f in fails:
        print("  FAIL " + f)
    return 1 if fails else 0


if __name__ == "__main__":
    raise SystemExit(main())
