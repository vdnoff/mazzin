#!/usr/bin/env python3
"""What the zodiac reader actually sees: the badge, the bridges, the report.

Three things that can only be checked by rendering the page.

The badge. In badge mode the label under a card IS the answer, so the old
tap-reveal pill must not arrive on top of it when the card is chosen — which
it did, over the name, on a phone. Checked on Capricorn and Sagittarius,
because those are the two longest words in the twelve and the ones a pill
covers most.

The bridges. The quiz is light and the report is a night sky, and the two are
now joined rather than cut between: the analysing screen fades to the report's
ground, the progress bar is gold, the interstitials are dark. Every one of
those is config-gated, so kitchen is walked end to end here too and has to
come out exactly as pale as it always was.

The delivered report. The page somebody reaches from the link in their mail is
the page they paid on, with everything open — not the light kitchen layout
with the words "YOUR PERFECT STYLE IS" at the top of it, which is what it was.

    python3 tests/test_zodiacdelivered.py
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

import config                                             # noqa: E402
import database                                           # noqa: E402
import reports                                            # noqa: E402

PORT = 8841
CHROME = "/opt/pw-browsers/chromium-1194/chrome-linux/chrome"

# engine.js holds a chosen card on screen — ring, badge, then whatever else a
# funnel shows — before the set leaves.
HOLD_MS = 1650

INDIGO = "rgb(14, 20, 48)"
GOLD = "rgb(232, 200, 120)"

fails = []
checks = [0]


def check(label, ok, detail=""):
    checks[0] += 1
    if not ok:
        fails.append("%s %s" % (label, detail))
    print("  %-62s %s%s" % (label, "ok" if ok else "FAIL",
                            ("  " + str(detail)) if not ok else ""))


# --- one finished report per funnel, built offline --------------------------

database.execute = lambda *a, **kw: None
database.query_all = lambda *a, **kw: []
reports._api = lambda: None

REPORTS = {}


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
    # The stored row says "stub-2" with no model; the client only reads the
    # schema out of it, and the delivered view is the same view either way.
    content["version"] = "llm-2"
    return content


class Handler(http.server.SimpleHTTPRequestHandler):
    """static/ off disk, the two shells, and one stubbed report each."""

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


def clear_interstitial(page):
    for _ in range(3):
        mid = page.locator("#screen-interstitial")
        if mid.count() and mid.is_visible():
            page.click("#mid-cta")
            page.wait_for_timeout(600)
        else:
            break


def advance(page):
    page.locator("#cards .card").first.click()
    page.wait_for_timeout(HOLD_MS + 350)
    clear_interstitial(page)


def bg(page, selector="body"):
    return page.eval_on_selector(
        selector, "n => getComputedStyle(n).backgroundColor")


# --- a) the badge -----------------------------------------------------------

def sign_step(page):
    """Open the funnel and stop on the twelve-up."""
    page.goto(url("/zodiac"))
    page.wait_for_selector("#cards .card", timeout=20000)
    page.wait_for_timeout(400)
    advance(page)                                    # past the hook pair
    page.wait_for_function(
        "() => document.querySelectorAll('#cards .card').length === 12",
        timeout=10000)
    page.wait_for_timeout(500)
    return page.eval_on_selector_all(
        "#cards .card-name", "ns => ns.map(n => n.innerText.trim())")


def badge(page):
    print("\n--- the badge is the selected state ---")
    names = sign_step(page)
    check("the twelve signs are labelled", len(names) == 12, str(names))

    # The two longest words in the twelve: whatever a pill would cover, it
    # covers most of one of these. One run of the step each, because tapping
    # a sign is the end of the step and there is no second sign to tap.
    for want in ("Capricorn", "Sagittarius"):
        if want not in names:
            check("%s is on the grid" % want, False, str(names))
            continue
        index = names.index(want)
        measure = """(i) => {
            const card = document.querySelectorAll('#cards .card')[i];
            const name = card.querySelector('.card-name');
            const r = name.getBoundingClientRect();
            const c = card.getBoundingClientRect();
            const style = getComputedStyle(name);
            const seen = (el) => {
                if (!el) return false;
                const s = getComputedStyle(el);
                return s.display !== 'none' && s.visibility !== 'hidden'
                    && parseFloat(s.opacity) > 0.01;
            };
            return {text: name.innerText.trim(),
                    offCentre: Math.abs((r.left + r.width / 2)
                                        - (c.left + c.width / 2)),
                    bottom: Math.round(c.bottom - r.bottom),
                    inside: r.left >= c.left - 0.5 && r.right <= c.right + 0.5,
                    chosen: card.classList.contains('is-chosen'),
                    background: style.backgroundColor,
                    after: getComputedStyle(name, '::after').content,
                    pill: seen(card.querySelector('.reaction')),
                    tick: seen(card.querySelector('.check'))};
        }"""
        before = page.evaluate(measure, index)
        page.locator("#cards .card").nth(index).click()
        page.wait_for_timeout(320)
        after = page.evaluate(measure, index)

        check("%s: the cell reads as chosen" % want, after["chosen"])
        check("  no tap-reveal pill on top of it", not after["pill"])
        check("  and no separate tick either", not after["tick"])
        check("  the label still says what it said",
              after["text"] == before["text"] == want, after["text"])
        # The pill grows by a tick and the chosen card lifts, so it is the
        # anchoring that is asserted, not the pixel: still centred on its own
        # cell, still on the bottom edge of it, still inside it.
        # Measured against the cell's own centre rather than as a pixel: the
        # chosen card lifts and scales, so every absolute coordinate under it
        # moves and none of them is evidence of anything.
        check("  still centred on the cell",
              max(before["offCentre"], after["offCentre"]) <= 1.5,
              "%.2f -> %.2f" % (before["offCentre"], after["offCentre"]))
        check("  still sitting on the bottom of it",
              abs(after["bottom"] - before["bottom"]) <= 4,
              "%d -> %d" % (before["bottom"], after["bottom"]))
        check("  and has not grown out of it", after["inside"])
        check("  the badge itself carries the accent",
              after["background"] == GOLD, after["background"])
        check("  with a check integrated into it",
              "\u2713" in (after["after"] or ""), after["after"])
        if want != "Sagittarius":
            names = sign_step(page)


def kitchen_badge(page):
    print("\n--- and kitchen still reveals on tap ---")
    page.goto(url("/kitchen"))
    page.wait_for_selector("#cards .card", timeout=20000)
    page.wait_for_timeout(500)
    check("no kitchen card carries a badge",
          page.locator("#cards .card-name").count() == 0)
    page.locator("#cards .card").first.click()
    page.wait_for_timeout(420)
    shown = page.evaluate(
        """() => {
            const card = document.querySelector('#cards .card.is-chosen')
                || document.querySelector('#cards .card');
            const pill = card.querySelector('.reaction');
            if (!pill) return null;
            const s = getComputedStyle(pill);
            return {display: s.display, text: pill.innerText.trim()};
        }""")
    check("the tap-reveal pill is still drawn", bool(shown), str(shown))
    check("  and is not display:none",
          bool(shown) and shown["display"] != "none", str(shown))


# --- b) the bridges ---------------------------------------------------------

def bridges(page, slug, dark):
    print("\n--- the walk down %s ---" % slug)
    page.goto(url("/" + slug))
    page.wait_for_selector("#cards .card", timeout=20000)
    page.wait_for_timeout(400)

    theme = page.get_attribute("body", "class") or ""
    check("the funnel names its theme on the body" if dark
          else "no theme class is set", ("theme-zodiac" in theme) == dark,
          theme)

    seen_mid = False
    for _ in range(15):
        page.locator("#cards .card").first.click()
        page.wait_for_timeout(HOLD_MS + 350)
        mid = page.locator("#screen-interstitial")
        if mid.count() and mid.is_visible() and not seen_mid:
            seen_mid = True
            ground = bg(page, "#screen-interstitial")
            check("  the interstitial is on the report's ground" if dark
                  else "  the interstitial is unchanged",
                  (ground == INDIGO) == dark, ground)
            kicker = page.eval_on_selector(
                ".mid-kicker", "n => getComputedStyle(n).color")
            check("  its kicker is gold" if dark else "  its kicker is rust",
                  (kicker == GOLD) == dark, kicker)
        clear_interstitial(page)
        # The last pip that is already done — not the current one, which is
        # mid-transition and mid-pulse and reports whatever frame it is on.
        pip = page.evaluate(
            """() => {
                const done = [...document.querySelectorAll('.pip.is-done')];
                if (!done.length) return null;
                return getComputedStyle(done[done.length - 1]).backgroundColor;
            }""")
        if pip and not seen_mid:
            pass
        if page.locator("#analyzing").count() and \
                page.locator("#analyzing").is_visible():
            break
        if not page.locator("#cards .card").count():
            break
    check("  the interstitial was reached", seen_mid)

    pip = page.evaluate(
        """() => {
            const done = [...document.querySelectorAll('.pip.is-done')];
            if (!done.length) return null;
            return getComputedStyle(done[done.length - 1]).backgroundColor;
        }""")
    check("  the progress bar is gold" if dark
          else "  the progress bar is unchanged",
          (pip == GOLD) == dark, pip)

    page.wait_for_selector("#analyzing", state="visible", timeout=15000)
    early = bg(page)
    check("  the analysing screen opens on the quiz's own ground",
          early != INDIGO, early)
    duration = (config.load_funnel(slug).get("analyzing") or {}).get(
        "duration_ms") or 2500
    page.wait_for_timeout(int(duration * 0.95))
    late = bg(page)
    check("  and lands on the report's" if dark else "  and stays there",
          (late == INDIGO) == dark, "%s -> %s" % (early, late))


# --- c) the delivered report ------------------------------------------------

def delivered(page):
    print("\n--- the report the link in the mail opens ---")
    errors = []
    page.on("pageerror", lambda e: errors.append(str(e)))
    page.goto(url("/zodiac?cs=cs_test_1"))
    page.wait_for_selector("#result-module.is-delivered", timeout=25000)
    page.wait_for_timeout(900)
    check("it renders without a script error", not errors, str(errors))
    body = page.inner_text("body").upper()
    check('it never says "PERFECT STYLE"', "PERFECT STYLE" not in body)
    check("  nor anything about a kitchen", "KITCHEN" not in body)
    check("the kicker is the one the page had",
          page.inner_text(".zr-kicker") == "YOUR COSMIC PROFILE",
          page.inner_text(".zr-kicker"))
    check("the built-in report is not drawn under it",
          page.get_attribute("#report", "hidden") is not None)
    check("the ground is the night sky", bg(page) == INDIGO, bg(page))

    check("the hero names the sign", page.inner_text(".zr-sign") == "Scorpio",
          page.inner_text(".zr-sign"))
    check("  crossed with the archetype",
          page.inner_text(".zr-cross") == "× Deep Water",
          page.inner_text(".zr-cross"))
    cells = page.eval_on_selector_all(
        ".zr-el", "ns => ns.map(n => [n.innerText.trim(), n.className])")
    check("  over an element bar of four",
          [c[0] for c in cells] == ["FIRE", "EARTH", "AIR", "WATER"],
          str(cells))
    lit = [c for c in cells if "is-own" in c[1]]
    check("  with this archetype's own lit, and one only",
          len(lit) == 1 and lit[0][0] == "WATER", str(cells))

    nodes = page.eval_on_selector_all(
        ".zr-node", "ns => ns.map(n => [n.className,"
                    " n.querySelector('.zr-node-title').innerText])")
    want = [s["title"] for s in REPORTS["zodiac"]["sections"]]
    check("every section is a node on the path",
          [n[1] for n in nodes] == want, str([n[1] for n in nodes]))
    check("  and every one of them is open",
          all("is-open" in n[0] for n in nodes) and nodes,
          str([n[0] for n in nodes]))
    check("  none of them is still locked",
          page.locator(".zr-node.is-locked").count() == 0)
    check("  and none carries a teaser line",
          page.locator(".zr-teaser").count() == 0)

    check("the palette is drawn as swatches",
          page.locator(".zr-swatch").count() == 4)
    style = reports._style(config.load_funnel("zodiac"), "deep_water")
    want_colours = reports._style_colors(style)
    got = list(zip(
        page.eval_on_selector_all(".zr-swatch-name", "ns=>ns.map(n=>n.innerText)"),
        page.eval_on_selector_all(".zr-swatch-hex", "ns=>ns.map(n=>n.innerText)")))
    check("  and they are the four the free page showed",
          got == want_colours, str(got))
    check("the strengths are numbered", page.locator(".zr-item").count() == 5)
    check("the compatibility verdicts are there",
          page.locator(".zr-verdict").count() >= 3)
    check("the twelve months are all twelve",
          page.locator(".zr-month").count() == 12)
    check("no offer card is on the page", page.locator(".zr-offer").count() == 0)
    check("  and nothing asks for money",
          page.locator("#pay-button").count() == 0
          or not page.locator("#pay-button").is_visible())
    check("the footnote says where else the profile is",
          page.locator(".zr-footnote").count() == 1
          and "PDF" in page.inner_text(".zr-footnote"),
          page.locator(".zr-footnote").count()
          and page.inner_text(".zr-footnote"))


def kitchen_delivered(page):
    print("\n--- and kitchen's delivered page is its own ---")
    page.goto(url("/kitchen?cs=cs_test_1"))
    page.wait_for_selector("#report", state="visible", timeout=25000)
    page.wait_for_timeout(700)
    check("it draws the built-in report, not a module",
          page.locator("#result-module").count() == 0)
    check("  on the light ground it always had", bg(page) != INDIGO, bg(page))
    text = page.inner_text("body").upper()
    check("  and still says what it always said",
          "PERFECT STYLE" in text or "YOUR STYLE" in text, text[:120])
    check("  with nothing cosmic in it", "COSMIC" not in text)


def main():
    REPORTS["zodiac"] = build("zodiac", "deep_water", "sign_scorpio")
    REPORTS["kitchen"] = build("kitchen", "modern_rustic")

    socketserver.TCPServer.allow_reuse_address = True
    httpd = socketserver.TCPServer(("127.0.0.1", PORT), Handler)
    threading.Thread(target=httpd.serve_forever, daemon=True).start()
    try:
        with sync_playwright() as pw:
            browser = pw.chromium.launch(executable_path=CHROME)
            # 380: the narrower of the two common phone widths, and the one
            # "Sagittarius" has to fit at.
            page = browser.new_page(viewport={"width": 380, "height": 844},
                                    device_scale_factor=2)
            badge(page)
            kitchen_badge(page)
            bridges(page, "zodiac", True)
            bridges(page, "kitchen", False)
            delivered(page)
            kitchen_delivered(page)
            browser.close()
    finally:
        httpd.shutdown()

    print("\n%d checks, %d failed" % (checks[0], len(fails)))
    for line in fails:
        print("  FAIL " + line)
    return 1 if fails else 0


if __name__ == "__main__":
    sys.exit(main())
