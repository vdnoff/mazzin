#!/usr/bin/env python3
"""The five polish items, on the page.

Where the selection label lands on each of the three formats, what the locks
look like now, what the sticky bar does when it is tapped and which events
come out of it, and what the paid report is illustrated with.

    python3 polish2.py
"""
import json
import os
import re
import sys

# The repo root, derived from this file rather than hardcoded: a suite
# that only runs from one absolute path is a suite that stops running the
# first time the checkout moves.
REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import http.server                              # noqa: E402
import json as _json                            # noqa: E402
import socketserver                             # noqa: E402
import threading                                # noqa: E402

from playwright.sync_api import sync_playwright   # noqa: E402
from test_walk import Handler as WalkHandler, PORT, STEPS, ANCHORS, GRID  # noqa: E402


# Collected here rather than off Playwright's request event: the engine sends
# events with navigator.sendBeacon, whose Blob body the browser does not hand
# back to the harness. The server sees them all.
TRACKED = []


class Handler(WalkHandler):
    """walk.py's server, plus a checkout that actually hands back a url.

    The shortcut this file exists to check ends at Stripe, so the stub has to
    answer the way Stripe's session endpoint does — walk.py never needed to.
    """

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
        if path == "/api/track":
            raw = self.rfile.read(int(self.headers.get("content-length") or 0))
            try:
                TRACKED.append(_json.loads(raw.decode("utf-8")))
            except Exception:
                TRACKED.append({"event": "<unparseable>"})
            self.send_response(204)
            self.end_headers()
            return
        if self.path.split("?")[0] == "/api/checkout":
            self.rfile.read(int(self.headers.get("content-length") or 0))
            raw = _json.dumps(
                {"url": "http://127.0.0.1:%d/paid" % PORT}).encode()
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(raw)))
            self.end_headers()
            self.wfile.write(raw)
            return
        return super().do_POST()


def serve():
    socketserver.TCPServer.allow_reuse_address = True
    httpd = socketserver.TCPServer(("127.0.0.1", PORT), Handler)
    threading.Thread(target=httpd.serve_forever, daemon=True).start()
    return httpd

ROOT = REPO
SHOTS = os.path.dirname(os.path.abspath(__file__))
CHROME = "/opt/pw-browsers/chromium-1194/chrome-linux/chrome"
CFG = json.load(open(os.path.join(ROOT, "funnels/kitchen.json")))
VISUALS = CFG["report"]["visuals"]

fails = []
checks = [0]


def check(label, ok, detail=""):
    checks[0] += 1
    if not ok:
        fails.append("%s %s" % (label, detail))
    print("  %-60s %s%s" % (label, "ok" if ok else "FAIL",
                            ("  " + str(detail)) if not ok else ""))


def walk(page, on_step=None):
    """One full quiz, tapping a different cell each step."""
    page.wait_for_selector("#cards .card", timeout=10000)
    for index, step in enumerate(STEPS):
        cards = page.query_selector_all("#cards .card")
        pick = index % len(cards)
        cards[pick].click()
        page.wait_for_selector(".reaction.is-in", timeout=4000)
        if on_step:
            on_step(index, step, pick, len(cards))
        done = index + 1
        if done in ANCHORS and done < len(STEPS):
            page.wait_for_selector("#screen-interstitial.is-active",
                                   timeout=12000)
            page.click("#mid-cta")
        if done < len(STEPS):
            page.wait_for_function(
                "q => document.getElementById('swipe-caption')"
                ".textContent === q",
                arg=STEPS[done]["question"], timeout=15000)
    page.wait_for_selector("#result-body:not([hidden])", timeout=20000)
    page.wait_for_timeout(400)


def box(page, sel):
    return page.eval_on_selector(sel, """n => {
        const r = n.getBoundingClientRect();
        return {x: r.x, y: r.y, w: r.width, h: r.height,
                cx: r.x + r.width / 2, cy: r.y + r.height / 2};
    }""")


def main():
    httpd = serve()
    try:
        with sync_playwright() as pw:
            browser = pw.chromium.launch(executable_path=CHROME)
            page = browser.new_page(viewport={"width": 390, "height": 844},
                                    device_scale_factor=2)
            errors = []
            page.on("pageerror", lambda e: errors.append(str(e)))
            page.on("console",
                    lambda m: errors.append(m.text) if m.type == "error" else None)
            page.on("requestfailed", lambda r: errors.append(
                "requestfailed " + r.url))

            page.goto("http://127.0.0.1:%d/kitchen" % PORT)
            page.wait_for_selector("#cards .card", timeout=10000)

            print("\n--- 1. the label lands in the middle of the tapped card ---")
            seen = {}

            def look(index, step, pick, cells):
                fmt = step.get("format") or "pair"
                if fmt in seen:
                    return
                seen[fmt] = True
                card = box(page, "#cards .card.is-chosen")
                chip = box(page, ".reaction-pill")
                check("  %-5s (%d cards, cell %d) chip is inside the card"
                      % (fmt, cells, pick + 1),
                      page.eval_on_selector(
                          ".reaction", "n => n.closest('.card') !== null"))
                check("    centred on x",
                      abs(chip["cx"] - card["cx"]) < 1.5,
                      round(chip["cx"] - card["cx"], 1))
                check("    centred on y",
                      abs(chip["cy"] - card["cy"]) < 1.5,
                      round(chip["cy"] - card["cy"], 1))
                check("    and fits within it",
                      chip["w"] <= card["w"] and chip["h"] <= card["h"],
                      (round(chip["w"]), round(card["w"])))
                check("    over a wash that dims the photograph",
                      page.eval_on_selector(
                          ".reaction",
                          "n => getComputedStyle(n).backgroundColor")
                      != "rgba(0, 0, 0, 0)")
                check("    it names the choice",
                      bool(page.inner_text(".reaction-pill").strip()),
                      page.inner_text(".reaction-pill"))
                check("    only one chip on the row",
                      page.eval_on_selector_all(
                          "#cards .reaction", "n => n.length") == 1)
                check("    and none on an unchosen card",
                      page.eval_on_selector_all(
                          "#cards .card:not(.is-chosen) .reaction",
                          "n => n.length") == 0)

            walk(page, look)
            check("all three formats were exercised",
                  sorted(seen) == ["grid4", "grid6", "pair"], sorted(seen))

            print("\n--- 2. the locked-list rows carry a real padlock ---")
            rows = page.eval_on_selector_all(".also-row", """ns => ns.map(n => {
                const s = n.querySelector('.padlock');
                if (!s) return null;
                const b = s.getBoundingClientRect();
                const body = s.querySelector('.padlock-body');
                return {w: Math.round(b.width), h: Math.round(b.height),
                        sm: s.classList.contains('is-sm'),
                        parts: s.children.length,
                        fill: getComputedStyle(body).fill,
                        stroke: getComputedStyle(
                            s.querySelector('.padlock-shackle')).stroke,
                        hole: getComputedStyle(
                            s.querySelector('.padlock-hole')).display};
            })""")
            check("every row has one", all(rows) and len(rows) == 4, len(rows))
            check("it is an svg with a shackle, a body and a keyhole",
                  all(r["parts"] == 3 for r in rows))
            check("sized 14-16px", all(14 <= r["w"] <= 16 and 14 <= r["h"] <= 16
                                       for r in rows),
                  [(r["w"], r["h"]) for r in rows[:1]])
            check("drawn in the accent",
                  all(r["fill"].replace(" ", "") == "rgb(192,86,33)"
                      and r["stroke"].replace(" ", "") == "rgb(192,86,33)"
                      for r in rows), rows[0]["fill"])
            check("no keyhole at this size",
                  all(r["hole"] == "none" for r in rows))
            check("the old glyph is gone from the page",
                  page.eval_on_selector_all(".row-lock", "n => n.length") == 0)
            check("the free mistake's footer uses it too",
                  page.eval_on_selector_all(".mistake-locked .padlock.is-sm",
                                            "n => n.length") == 1)
            check("and so does the gated paint code",
                  page.eval_on_selector_all(".swatch-hex .padlock.is-sm",
                                            "n => n.length") == 3)

            print("\n--- 4. one big lock over each teaser ---")
            teasers = page.eval_on_selector_all(
                "#report .section:has(.dissolve)", "ns => ns.length")
            marks = page.eval_on_selector_all(".locked-lock", """ns => ns.map(n => {
                const b = n.getBoundingClientRect();
                const svg = n.querySelector('.padlock');
                const s = svg.getBoundingClientRect();
                const zone = n.closest('.locked-body').getBoundingClientRect();
                return {w: Math.round(b.width), lock: Math.round(s.width),
                        dx: (b.x + b.width / 2) - (zone.x + zone.width / 2),
                        dy: (b.y + b.height / 2) - (zone.y + zone.height / 2),
                        events: getComputedStyle(n).pointerEvents,
                        halo: getComputedStyle(n).boxShadow};
            })""")
            check("one per teaser and no more",
                  len(marks) == teasers == 2, (len(marks), teasers))
            check("the padlock is ~48px",
                  all(m["lock"] == 48 for m in marks),
                  [m["lock"] for m in marks])
            check("centred over the whole locked block, both axes",
                  all(abs(m["dx"]) < 1.5 and abs(m["dy"]) < 1.5 for m in marks),
                  [(round(m["dx"], 1), round(m["dy"], 1)) for m in marks])
            check("with a soft halo around it",
                  all("rgba(255, 255, 255" in m["halo"] for m in marks),
                  marks[0]["halo"][:60])
            check("it does not swallow the tap",
                  all(m["events"] == "none" for m in marks))
            check("no small lock left in the thumbnail strip",
                  page.eval_on_selector_all(".preview-strip .padlock",
                                            "n => n.length") == 0)

            before = page.evaluate("() => window.scrollY")
            page.eval_on_selector(".locked-lock", "n => n.click()")
            page.wait_for_timeout(900)
            check("tapping the lock still takes you to the offer",
                  page.eval_on_selector(
                      "#commerce",
                      """n => { const r = n.getBoundingClientRect();
                         return r.top < innerHeight && r.bottom > 0; }"""),
                  before)

            check("no page errors on the free page", not errors, errors[:3])
            browser.close()

            print("\n--- 3. the sticky bar asks for a scroll ---")
            # A page of its own. The lock tap above scrolled the offer into
            # view, which fires paywall_view for real — what the bar does to
            # that event can only be seen on a run where nobody has reached
            # the block yet.
            #
            # The bar briefly took the payment itself. That is reverted, and
            # stickyscroll.py owns the detail; what is checked here is that
            # the tap moves the reader to the block and takes no money on the
            # way.
            del TRACKED[:]
            browser = pw.chromium.launch(executable_path=CHROME)
            page = browser.new_page(viewport={"width": 390, "height": 844})
            errors = []
            page.on("pageerror", lambda e: errors.append(str(e)))
            page.on("response", lambda r: errors.append(
                "%d %s" % (r.status, r.url)) if r.status >= 400 else None)
            page.goto("http://127.0.0.1:%d/kitchen" % PORT)
            walk(page)

            page.evaluate("""() => { const r = document.querySelector(
                '#report .section'); window.scrollTo(0, r.getBoundingClientRect()
                .bottom + window.scrollY + 60); }""")
            page.wait_for_timeout(600)
            check("the bar is up", page.eval_on_selector("#sticky-cta",
                                                         "n => !n.hidden"))
            check("nobody has reached the offer yet",
                  "paywall_view" not in [e["event"] for e in TRACKED],
                  [e["event"] for e in TRACKED][-3:])
            page.click("#sticky-cta")
            page.wait_for_timeout(1600)          # let the smooth scroll land
            names = [e["event"] for e in TRACKED]
            check("it stayed on the result rather than going to Stripe",
                  "/paid" not in page.url, page.url)
            check("and put the offer on screen",
                  page.eval_on_selector(
                      "#commerce",
                      """n => { const r = n.getBoundingClientRect();
                         return r.top < innerHeight && r.bottom > 0; }"""))
            tail = [n for n in names if n in ("sticky_cta", "paywall_view",
                                              "pay_tap")]
            check("sticky_cta, then paywall_view, and no pay_tap",
                  tail == ["sticky_cta", "paywall_view"], tail)
            src = None
            for body in TRACKED:
                if body["event"] == "paywall_view":
                    src = (body.get("extra") or {}).get("src")
            check("the paywall_view is still attributed to the bar",
                  src == "sticky", src)
            check("each fired exactly once",
                  all(names.count(n) == 1 for n in
                      ("sticky_cta", "paywall_view")),
                  [(n, names.count(n)) for n in ("sticky_cta", "paywall_view")])
            check("no checkout_error", "checkout_error" not in names, names)
            check("nothing 404s or errors on the sticky run",
                  not errors, errors[:3])
            browser.close()
    finally:
        httpd.shutdown()

    print("\n%d checks, %d failed" % (checks[0], len(fails)))
    for f in fails:
        print("  FAIL " + f)
    return 1 if fails else 0


if __name__ == "__main__":
    raise SystemExit(main())
