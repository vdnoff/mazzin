#!/usr/bin/env python3
"""Drive the real engine through a whole run, in a real browser.

Serves static/ the way the CDN does, hands back static/funnel.html for the
slug route the way Flask does, stubs the two API calls the quiz makes, and
then taps through all thirteen steps checking what the screen actually says
at each one. Screenshots the hook step, the elements section and the home
page on the way past.

    python3 walk.py [left|right]     which card to tap (default alternating)
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
SHOTS = os.path.dirname(os.path.abspath(__file__))
PORT = 8731

fails = []


def check(label, ok, detail=""):
    if not ok:
        fails.append("%s %s" % (label, detail))
    print("  %-56s %s%s" % (label, "ok" if ok else "FAIL",
                            ("  " + str(detail)) if not ok else ""))


class Handler(http.server.SimpleHTTPRequestHandler):
    """static/ straight off disk; /kitchen is the funnel shell; APIs stubbed."""

    def __init__(self, *a, **kw):
        super().__init__(*a, directory=ROOT, **kw)

    def log_message(self, *a):
        pass

    def do_GET(self):
        path = self.path.split("?")[0]
        if path == "/api/pixel-config":
            return self._json({})
        if path == "/":
            self.path = "/static/pages/home.html"
            return super().do_GET()
        if path in ("/kitchen",):
            self.path = "/static/funnel.html"
            return super().do_GET()
        return super().do_GET()

    def do_POST(self):
        length = int(self.headers.get("content-length") or 0)
        self.rfile.read(length)
        self._json({"ok": True})

    def _json(self, body):
        raw = json.dumps(body).encode()
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(raw)))
        self.end_headers()
        self.wfile.write(raw)


def serve():
    socketserver.TCPServer.allow_reuse_address = True
    httpd = socketserver.TCPServer(("127.0.0.1", PORT), Handler)
    threading.Thread(target=httpd.serve_forever, daemon=True).start()
    return httpd


cfg = json.load(open(os.path.join(ROOT, "funnels/kitchen.json")))
WORKING = cfg.get("interstitial_working") or []
STEPS = cfg["swipe"]["steps"]
TOTAL = cfg["swipe"]["pairs_count"]
ANCHORS = {i["after_step"]: i for i in cfg["interstitials"]}
GRID = {"grid4": 4, "grid6": 6}


def run(side="alt"):
    httpd = serve()
    seen_interstitials = []
    try:
        with sync_playwright() as pw:
            browser = pw.chromium.launch(
                executable_path="/opt/pw-browsers/chromium-1194/chrome-linux/chrome")
            page = browser.new_page(viewport={"width": 390, "height": 844},
                                    device_scale_factor=2)
            errors = []
            page.on("pageerror", lambda e: errors.append(str(e)))
            page.on("console", lambda m: errors.append(m.text)
                    if m.type == "error" else None)

            page.goto("http://127.0.0.1:%d/kitchen" % PORT)
            page.wait_for_selector("#cards .card", timeout=10000)

            for index, step in enumerate(STEPS):
                want = GRID.get(step.get("format"), 2)
                cards = page.query_selector_all("#cards .card")
                label = page.inner_text("#progress-label")
                question = page.inner_text("#swipe-caption")
                check("step %2d/%d  %-11s  %d cards, '%s'"
                      % (index + 1, TOTAL, step["id"], want, label),
                      len(cards) == want
                      and label == "%d of %d" % (index + 1, TOTAL)
                      and question == step["question"],
                      "cards=%d label=%r q=%r" % (len(cards), label, question))

                if index == 0:
                    check("  header leads with the saving",
                          page.inner_text("#swipe-subtext")
                          == "$4,000+ saved on your renovation",
                          page.inner_text("#swipe-subtext"))
                    check("  the caps kicker is gone",
                          page.query_selector("#swipe-headline") is None)
                    check("  the saving is in the accent",
                          page.inner_text(".subtext .money") == "$4,000+",
                          page.inner_text(".subtext .money"))
                    money = page.eval_on_selector(
                        ".subtext",
                        "n => { const s = getComputedStyle(n);"
                        " return [parseFloat(s.fontSize), s.fontFamily,"
                        " getComputedStyle(n.querySelector('.money')).color]; }")
                    check("  money line is 17-18px brand face",
                          17 <= money[0] <= 18 and "Fraunces" in money[1], money)
                    check("  accent is the terracotta",
                          money[2].replace(" ", "") == "rgb(192,86,33)", money[2])
                    srcs = [i.get_attribute("src") for i in
                            page.query_selector_all("#cards .card img")]
                    check("  hook shows hk1a and hk1b",
                          sorted(os.path.basename(s) for s in srcs)
                          == ["hk1a.webp", "hk1b.webp"], srcs)
                    page.screenshot(path=os.path.join(SHOTS, "shot-hook.png"))

                pick = 0 if side == "left" else (
                    len(cards) - 1 if side == "right" else index % len(cards))
                cards[pick].click()

                completed = index + 1
                # The engine advances the counter on the tap and the cards a
                # beat later, so waiting on the label would read the next step
                # while the last one is still on screen. Wait on the question.
                if completed in ANCHORS and completed < TOTAL:
                    page.wait_for_selector("#screen-interstitial.is-active",
                                           timeout=12000)
                    mid = page.inner_text("#mid-progress-label")
                    seen_interstitials.append(completed)
                    first = page.inner_text(".mid-working-text")
                    check("    working row shows a line and a spinner",
                          bool(first) and page.query_selector(".mid-spinner")
                          is not None, first)
                    check("    working line is config copy",
                          first in WORKING, first)
                    page.wait_for_timeout(2300)
                    later = page.inner_text(".mid-working-text")
                    check("    working line rotates within ~2s",
                          later != first and later in WORKING,
                          "%r -> %r" % (first, later))
                    check("  interstitial after step %d  (%s)"
                          % (completed, page.inner_text("#mid-kicker")),
                          mid == "%d of %d" % (min(completed + 1, TOTAL), TOTAL),
                          mid)
                    page.click("#mid-cta")

                if completed < TOTAL:
                    page.wait_for_function(
                        "q => document.getElementById('screen-swipe')"
                        ".classList.contains('is-active') &&"
                        " document.getElementById('swipe-caption')"
                        ".textContent === q",
                        arg=STEPS[completed]["question"],
                        timeout=12000)

            # --- result -------------------------------------------------
            page.wait_for_selector("#result-body:not([hidden])", timeout=15000)
            page.wait_for_selector(".section-elements", timeout=8000)

            check("interstitials fired at 4/7/10",
                  seen_interstitials == [4, 7, 10], seen_interstitials)

            name = page.inner_text("#result-name")
            check("a style was named", bool(name.strip()), name)

            sections = page.eval_on_selector_all(
                "#report .section",
                "ns => ns.map(n => n.querySelector('.section-title')"
                ".textContent)")
            # Free first, then the seam, then what is being sold. The four
            # sections that used to have a blurred block each are one card at
            # the bottom now.
            check("the free run is palette, mistake #1, elements",
                  sections[:3] == ["Your Color Palette", "Mistake #1 of 5",
                                   "Your Style Elements"], sections)
            check("then the two teasers worth keeping",
                  sections[3:5] == ["The 5 Mistakes People With Your Style Make",
                                    "Get the Look: Your Shopping List"], sections)
            check("then everything else, in one card",
                  sections[5:] == ["Also in your report"], sections)

            chips = page.eval_on_selector_all(
                ".element-chip",
                "ns => ns.map(n => ({label: n.querySelector('.element-label')"
                ".textContent, img: n.querySelector('img').getAttribute('src')}))")
            check("six element chips", len(chips) == 6, len(chips))
            check("every chip has a label and a thumb",
                  all(c["label"] and c["img"] for c in chips), chips)
            known = {e["label"] for e in cfg["style_elements"]["items"]}
            check("chip labels come from the config",
                  {c["label"] for c in chips} <= known,
                  {c["label"] for c in chips} - known)
            check("chips are unique", len({c["label"] for c in chips}) == 6)
            teaser = page.inner_text(".mistakes-teaser")
            check("mistakes teaser counts from the free one",
                  teaser.startswith("You've seen mistake #1")
                  and "other four" in teaser and "$4,000+" in teaser, teaser)
            check("teaser names the winning style",
                  name in teaser, "%r / %r" % (name, teaser))
            check("teaser sits inside the report, under the offer card",
                  page.evaluate(
                      """() => { const t = document.querySelector('.mistakes-teaser'),
                           m = document.getElementById('mid-offer');
                         return document.getElementById('report').contains(t)
                           && !!m
                           && (m.compareDocumentPosition(t)
                               & Node.DOCUMENT_POSITION_FOLLOWING) > 0; }"""))
            check("elements subline present",
                  page.inner_text(".elements-sub").startswith(
                      "Recognized from your choices"),
                  page.inner_text(".elements-sub"))

            # Two columns, and the thumbs are square.
            box = page.eval_on_selector_all(
                ".element-chip",
                "ns => ns.map(n => n.getBoundingClientRect().top)")
            check("chips are laid out two to a row",
                  len(set(round(t) for t in box)) == 3, sorted(set(box)))
            thumb = page.eval_on_selector(
                ".element-thumb img",
                "n => { const r = n.getBoundingClientRect();"
                " return [r.width, r.height]; }")
            check("thumbs are square", abs(thumb[0] - thumb[1]) < 0.5, thumb)

            check("no horizontal overflow on the result",
                  page.evaluate("document.documentElement.scrollWidth <= 390"),
                  page.evaluate("document.documentElement.scrollWidth"))

            page.locator(".section-elements").scroll_into_view_if_needed()
            page.screenshot(path=os.path.join(SHOTS, "shot-elements.png"))
            page.screenshot(path=os.path.join(SHOTS, "shot-result-full.png"),
                            full_page=True)

            # Tapping a free section still takes you toward the offer, which
            # is now further down this same page rather than a screen away.
            page.click(".section-elements")
            page.wait_for_timeout(800)
            check("tapping a free section scrolls toward the offer",
                  page.evaluate(
                      "() => document.getElementById('commerce')"
                      ".getBoundingClientRect().top < window.innerHeight * 2"),
                  page.evaluate(
                      "() => Math.round(document.getElementById('commerce')"
                      ".getBoundingClientRect().top)"))

            # --- the offer, on the same page ----------------------------
            page.evaluate("() => document.getElementById('commerce')"
                          ".scrollIntoView()")
            page.wait_for_timeout(500)
            heroes = page.eval_on_selector_all(
                ".manifest-row.is-hero",
                "ns => ns.map(n => n.querySelector('.manifest-text').textContent)")
            check("exactly one manifest row is promoted", len(heroes) == 1, heroes)
            check("the promoted row is the mistakes row",
                  heroes and "mistakes" in heroes[0].lower(), heroes)
            style = page.eval_on_selector(
                ".manifest-row.is-hero",
                "n => { const s = getComputedStyle(n),"
                " t = getComputedStyle(n.querySelector('.manifest-text'));"
                " return [s.borderLeftWidth, s.borderLeftColor, t.fontWeight]; }")
            check("promoted row has an accent left border and bold text",
                  style[0] == "3px"
                  and style[1].replace(" ", "") == "rgb(192,86,33)"
                  and int(style[2]) >= 600, style)
            check("the pay button is on the result page",
                  page.evaluate(
                      "() => document.getElementById('commerce')"
                      ".contains(document.getElementById('pay-button'))"))

            check("no page errors", not errors, errors[:4])

            # --- home ---------------------------------------------------
            home = browser.new_page(viewport={"width": 1280, "height": 900},
                                    device_scale_factor=2)
            home.goto("http://127.0.0.1:%d/" % PORT)
            home.wait_for_selector(".hero-preview")
            # The hero teaser is the funnel being advertised, which is the
            # zodiac one now. The saving line went with the kitchen — it is a
            # claim about a renovation and it belongs on the card that sells
            # one, not over a question about the sky.
            check("home preview asks the hook question",
                  home.inner_text(".mini-question")
                  == "Which sky calls to you?",
                  home.inner_text(".mini-question"))
            check("home preview hides the step count, like the quiz",
                  home.query_selector(".mini-count") is None)
            check("home preview makes no claim over the question",
                  home.query_selector(".mini-sub") is None)
            check("the saving moved to the card that sells a renovation",
                  "$4,000+" in home.inner_text(".card.is-live:nth-child(2)"),
                  home.inner_text(".card.is-live:nth-child(2)"))
            check("home preview draws 12 pips",
                  home.eval_on_selector_all(".mini-pips i", "n => n.length") == 12)
            check("home preview shows the hook images",
                  sorted(os.path.basename(s) for s in home.eval_on_selector_all(
                      ".mini-card img", "ns => ns.map(n => n.getAttribute('src'))"))
                  == ["zk1a.webp", "zk1b.webp"])
            check("  and both of them lead into that funnel",
                  home.eval_on_selector_all(
                      ".mini-card", "ns => ns.map(n => n.getAttribute('href'))")
                  == ["/zodiac", "/zodiac"])
            home.screenshot(path=os.path.join(SHOTS, "shot-home.png"))
            browser.close()
    finally:
        httpd.shutdown()

    print("\n%d failed" % len(fails))
    for f in fails:
        print("  FAIL " + f)
    return 1 if fails else 0


if __name__ == "__main__":
    raise SystemExit(run(sys.argv[1] if len(sys.argv) > 1 else "alt"))
