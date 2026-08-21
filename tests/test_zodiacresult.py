#!/usr/bin/env python3
"""The zodiac result page, walked in a browser.

This page is a module engine.js loads rather than code engine.js runs, so
almost nothing about it can be checked from the config: whether the module
arrived, whether it drew the sign the session actually tapped, whether the
consent box and the pay button ended up inside its offer card and still work.

The run below taps a named sign and first-listed cards everywhere else, then
reads the finished page back and asserts it describes that run — not a run,
that one. Checkout is stubbed at the server, so the CTA takes a real trip
through engine.js's own handler without reaching Stripe.

    python3 tests/test_zodiacresult.py [Sign]
"""
import http.server
import json
import os
import socketserver
import sys
import threading

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, REPO)

from playwright.sync_api import sync_playwright           # noqa: E402

ROOT = REPO
PORT = 8813
CHROME = "/opt/pw-browsers/chromium-1194/chrome-linux/chrome"
# engine.js holds a chosen card on screen before the set leaves.
HOLD_MS = 1650

SIGN = sys.argv[1] if len(sys.argv) > 1 else "Scorpio"

fails = []
checks = [0]
posted = []


def check(label, ok, detail=""):
    checks[0] += 1
    if not ok:
        fails.append("%s %s" % (label, detail))
    print("  %-58s %s%s" % (label, "ok" if ok else "FAIL",
                            ("  " + str(detail)) if not ok else ""))


class Handler(http.server.SimpleHTTPRequestHandler):
    """static/ off disk; the funnels are the shell; the APIs are stubs."""

    def __init__(self, *a, **kw):
        super().__init__(*a, directory=ROOT, **kw)

    def log_message(self, *a):
        pass

    def do_GET(self):
        path = self.path.split("?")[0]
        if path == "/api/pixel-config":
            return self._json({})
        if path in ("/zodiac", "/kitchen"):
            self.path = "/static/funnel.html"
        return super().do_GET()

    def do_POST(self):
        length = int(self.headers.get("content-length") or 0)
        raw = self.rfile.read(length)
        path = self.path.split("?")[0]
        try:
            posted.append((path, json.loads(raw or b"{}")))
        except ValueError:
            posted.append((path, {}))
        if path == "/api/checkout":
            # Far enough for the button to have done its job, and no further.
            return self._json({"url": "http://127.0.0.1:%d/stubbed" % PORT})
        self._json({"ok": True})

    def _json(self, body):
        raw = json.dumps(body).encode()
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(raw)))
        self.end_headers()
        self.wfile.write(raw)


def clear_interstitial(page):
    """Dismiss the beat between steps, if one opened.

    It takes `is-active` off the swipe screen while it is up, so anything
    that reads "is the quiz still on screen" has to run after this, not
    before — and it does not open instantly, so a fixed wait that is a little
    too short reads as the quiz having ended.
    """
    for _ in range(4):
        mid = page.locator("#screen-interstitial.is-active")
        if not mid.count():
            page.wait_for_timeout(250)
            mid = page.locator("#screen-interstitial.is-active")
        if not mid.count():
            return
        page.click("#mid-cta")
        page.wait_for_timeout(650)


def walk(page):
    """Tap through, choosing SIGN on the sign step. Returns what was tapped."""
    taken = {}
    for _ in range(14):
        # The cards stay in the document after the last step — hidden with
        # the screen, not removed — so "are there cards" is not the question.
        # Nor is "is the swipe screen active": an interstitial takes that away
        # mid-run. The quiz is over when the result screen is up.
        if page.locator("#screen-result.is-active").count():
            break
        page.wait_for_timeout(400)
        question = page.inner_text("#swipe-caption")
        names = page.eval_on_selector_all(
            "#cards .card-name", "ns => ns.map(n => n.innerText.trim())")
        srcs = page.eval_on_selector_all(
            "#cards .card img",
            "ns => ns.map(n => n.getAttribute('src').split('/').pop())")
        index = names.index(SIGN) if SIGN in names else 0
        taken[question] = (names[index] if names else "", srcs[index])
        page.locator("#cards .card").nth(index).click()
        page.wait_for_timeout(HOLD_MS + 300)
        clear_interstitial(page)
    return taken


def run(page):
    print("\n--- the module takes the page ---")
    page.goto("http://127.0.0.1:%d/zodiac" % PORT)
    page.wait_for_selector("#cards .card", timeout=20000)
    taken = walk(page)
    page.wait_for_selector("#result-module", timeout=20000)
    page.wait_for_timeout(1200)

    check("the module rendered", page.locator("#result-module").count() == 1)
    check("  and engine.js's own result stayed out of the way",
          page.get_attribute("#report", "hidden") is not None
          and page.get_attribute("#cta", "hidden") is not None)
    check("  with no error on the console", not page.errors, str(page.errors))

    print("\n--- the hero is this session's sign ---")
    check("the glyph is the sign that was tapped",
          page.get_attribute(".zr-glyph img", "src", timeout=5000)
          .endswith("sign_%s.webp" % SIGN.lower()),
          page.get_attribute(".zr-glyph img", "src"))
    check("  named beside it", page.inner_text(".zr-sign") == SIGN,
          page.inner_text(".zr-sign"))
    check("  crossed with the archetype the run scored",
          page.inner_text(".zr-cross").startswith("× "),
          page.inner_text(".zr-cross"))

    print("\n--- the numbers are this session's tallies ---")
    bars = page.eval_on_selector_all(".zr-bal", """ns => ns.map(n => ({
        name: n.querySelector('.zr-bal-name').innerText,
        pct: parseInt(n.querySelector('.zr-bal-pct').innerText, 10),
        height: parseFloat(n.querySelector('.zr-bal-fill').style.height)
    }))""")
    check("the balance chart has all four elements",
          [b["name"] for b in bars] == ["Fire", "Earth", "Air", "Water"],
          str([b["name"] for b in bars]))
    check("  its shares add up to a whole profile",
          97 <= sum(b["pct"] for b in bars) <= 103,
          sum(b["pct"] for b in bars))
    check("  the tallest bar is the highest share",
          max(bars, key=lambda b: b["height"])["pct"]
          == max(b["pct"] for b in bars))
    sub = page.inner_text(".zr-sub")
    hero_pct = int(sub.split("%")[0])
    hero_element = sub.split("%")[1].split("·")[0].strip()
    match = [b for b in bars if b["name"] == hero_element]
    check("the hero's element is one of the four", len(match) == 1,
          hero_element)
    check("  and its percentage is that element's own",
          match and match[0]["pct"] == hero_pct,
          "%s hero %d, chart %s" % (hero_element, hero_pct,
                                    match[0]["pct"] if match else "-"))
    check("  the bar is filled to it",
          page.eval_on_selector(".zr-bar-fill", "n => n.style.width")
          == "%d%%" % hero_pct)
    check("  and the sub-line carries the blend note",
          "rare blend" in page.inner_text(".zr-sub"),
          page.inner_text(".zr-sub"))

    print("\n--- the taps strip is what they actually tapped ---")
    tapped = {src for _, src in taken.values()}
    strip = [s.split("/")[-1] for s in page.eval_on_selector_all(
        ".zr-tap img", "ns => ns.map(n => n.getAttribute('src'))")]
    check("at least four frames are shown", len(strip) >= 4, str(strip))
    check("  and every one of them was tapped in this run",
          all(src in tapped for src in strip),
          str([s for s in strip if s not in tapped]))
    labels = page.eval_on_selector_all(
        ".zr-tap-name", "ns => ns.map(n => n.innerText.trim())")
    check("  each named", all(labels) and len(labels) == len(strip),
          str(labels))

    print("\n--- the constellation path ---")
    nodes = page.eval_on_selector_all(".zr-node", """ns => ns.map(n => ({
        open: n.classList.contains('is-open'),
        title: n.querySelector('.zr-node-title').innerText.trim(),
        teaser: (n.querySelector('.zr-teaser') || {}).innerText || '',
        lock: !!n.querySelector('.zr-node-mark svg')
    }))""")
    cfg = json.load(open(os.path.join(ROOT, "funnels/zodiac.json")))
    sections = [s for s in cfg["report"]["sections"]
                if s.get("enabled") is not False]
    lockable = [s for s in sections
                if (s.get("reveal") or {}).get("mode") != "visible"]
    check("two open nodes, then one per locked section",
          [n["open"] for n in nodes]
          == [True, True] + [False] * len(lockable),
          str([n["open"] for n in nodes]))
    check("  the first is the element balance",
          nodes[0]["title"] == cfg["result_copy"]["balance_title"],
          nodes[0]["title"])
    check("  the second is the free strength",
          nodes[1]["title"] == cfg["report"]["mistake_one"]["title"],
          nodes[1]["title"])
    check("  which opens on a card from this run",
          page.locator(".zr-lead").count() == 1
          and "{" not in page.inner_text(".zr-lead"),
          page.inner_text(".zr-lead")
          if page.locator(".zr-lead").count() else "missing")
    lead_words = page.inner_text(".zr-lead").lower()
    check("    naming one they tapped",
          any((label or "").lower() in lead_words
              for label, _ in taken.values()),
          page.inner_text(".zr-lead"))
    check("  and the strength itself is there in full",
          page.locator(".zr-strength-title").count() == 1
          and len(page.inner_text(".zr-strength-body")) > 200)
    for got, want in zip(nodes[2:], lockable):
        check("  locked %-9s titled and teased" % want["id"],
              got["title"] == want["title"]
              and got["teaser"].strip() != ""
              and "{" not in got["teaser"],
              "%r / %r" % (got["title"], got["teaser"]))
        check("    with a lock on its node", got["lock"], got["lock"])

    print("\n--- the offer is engine.js's, placed here ---")
    check("the consent box is inside the offer card",
          page.locator(".zr-offer #withdrawal").count() == 1)
    check("  and it is the shell's own element, not a copy",
          page.locator("#withdrawal").count() == 1)
    check("the pay button is inside it too",
          page.locator(".zr-offer #pay-button").count() == 1)
    check("  labelled from the config",
          page.inner_text(".zr-offer #pay-button")
          == cfg["checkout"]["cta_label"].replace(
              "{price}", "$%d" % (cfg["pricing"]["amount_cents"] // 100)),
          page.inner_text(".zr-offer #pay-button"))
    check("  and enabled, because consent is satisfied",
          page.get_attribute(".zr-offer #pay-button", "disabled") is None)
    check("the anchor names what it undercuts",
          cfg["checkout"]["commerce"]["anchor_head_accent"]
          in page.inner_text(".zr-anchor"), page.inner_text(".zr-anchor"))
    check("the trust line is built from the commerce strings",
          all(part in page.inner_text(".zr-trust")
              for part in cfg["checkout"]["commerce"]["trust"]),
          page.inner_text(".zr-trust"))

    print("\n--- and it takes a payment ---")
    # Unchecking must lock the button: this is the withdrawal waiver still
    # doing its job from inside a card it did not start in.
    page.uncheck(".zr-offer #withdrawal-check")
    page.wait_for_timeout(200)
    check("unchecking consent disables the button",
          page.get_attribute(".zr-offer #pay-button", "disabled") is not None)
    page.check(".zr-offer #withdrawal-check")
    page.wait_for_timeout(200)
    before = len([p for p in posted if p[0] == "/api/checkout"])
    page.locator(".zr-offer #pay-button").click()
    page.wait_for_timeout(1500)
    taps = [body for path, body in posted
            if path == "/api/track" and body.get("event") == "pay_tap"]
    check("tapping it fires pay_tap", bool(taps), str(len(taps)))
    check("  saying which control took it",
          bool(taps) and (taps[-1].get("extra") or {}).get("method")
          == "redirect", str(taps[-1] if taps else None))
    check("  and calls the existing checkout endpoint",
          len([p for p in posted if p[0] == "/api/checkout"]) == before + 1)


def kitchen(page):
    """The other funnels must never touch any of this."""
    print("\n--- and kitchen keeps the built-in page ---")
    page.goto("http://127.0.0.1:%d/kitchen" % PORT)
    page.wait_for_selector("#cards .card", timeout=20000)
    for _ in range(16):
        if page.locator("#screen-result.is-active").count():
            break
        page.wait_for_timeout(350)
        page.locator("#cards .card").first.click()
        page.wait_for_timeout(HOLD_MS + 350)
        clear_interstitial(page)
    page.wait_for_selector("#result-body", timeout=20000)
    page.wait_for_timeout(1500)
    check("no module was loaded", page.locator("#result-module").count() == 0)
    check("  and none of its stylesheet came with it",
          page.evaluate("!!document.querySelector("
                        "'link[href*=\"result_zodiac\"]')") is False)
    check("engine.js's own result rendered",
          page.get_attribute("#report", "hidden") is None
          and page.locator("#report .section").count() > 0,
          page.locator("#report .section").count())
    check("  with its own style name and blurb on screen",
          page.inner_text("#result-name").strip() != ""
          and page.locator(".result-kicker").is_visible())
    check("  the palette section drawn by the built-in path",
          page.locator("#report .swatch-list").count() == 1)
    check("  and the consent box where it has always been",
          page.locator("#commerce #withdrawal").count() == 1
          and page.locator(".zr-offer").count() == 0)


def main():
    socketserver.TCPServer.allow_reuse_address = True
    httpd = socketserver.TCPServer(("127.0.0.1", PORT), Handler)
    threading.Thread(target=httpd.serve_forever, daemon=True).start()
    try:
        with sync_playwright() as pw:
            browser = pw.chromium.launch(executable_path=CHROME)
            page = browser.new_page(viewport={"width": 390, "height": 844})
            page.errors = []
            page.on("pageerror", lambda e: page.errors.append(str(e)))
            page.on("console", lambda m: page.errors.append(m.text)
                    if m.type == "error" else None)
            run(page)
            kitchen(page)
            browser.close()
    finally:
        httpd.shutdown()

    print("\n%d checks, %d failed" % (checks[0], len(fails)))
    for line in fails:
        print("  FAIL " + line)
    return 1 if fails else 0


if __name__ == "__main__":
    sys.exit(main())
