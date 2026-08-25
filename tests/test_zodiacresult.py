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
import re
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

# Which archetype owns which element, so the rarity printed on the ribbon can
# be looked up against the table the config carries rather than trusted.
ARCHETYPE = {"Fire": "radiant_fire", "Earth": "grounded_earth",
             "Air": "celestial_air", "Water": "deep_water"}

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
        if path == "/api/payment-intent":
            # Enough for engine.js to get past the request. Stripe.js itself
            # cannot load here, so the attempt always ends in the redirect
            # fallback — which is the other thing worth asserting.
            return self._json({"client_secret": "pi_stub_secret_x",
                               "publishable_key": "pk_test_stub",
                               "amount_cents": 300, "currency": "usd"})
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

    print("\n--- the hero is this session's own profile ---")
    cfg = json.load(open(os.path.join(ROOT, "funnels/zodiac.json")))
    table = cfg["result_copy"]["profile"]
    names = set()
    for by_second in table["subtypes"].values():
        for by_energy in by_second.values():
            names.update(by_energy.values())
    check("the glyph is the sign that was tapped",
          page.get_attribute(".zr-glyph img", "src", timeout=5000)
          .endswith("sign_%s.webp" % SIGN.lower()),
          page.get_attribute(".zr-glyph img", "src"))
    subtype = page.inner_text(".zr-subtype")
    check("  and beside it is a name off the twenty-four", subtype in names,
          subtype)
    formula = page.inner_text(".zr-formula")
    check("  under the formula that produced it",
          formula.startswith(SIGN + " · ")
          and "-led, " in formula and " undercurrent · " in formula
          and formula.rsplit(" · ", 1)[-1] in ("Sun", "Moon"),
          formula)
    lead_el = formula.split(" · ")[1].split("-led")[0]
    second_el = formula.split("-led, ")[1].split(" undercurrent")[0]
    check("  the lead and the undercurrent are two different elements",
          lead_el != second_el
          and {lead_el, second_el} <= {"Fire", "Earth", "Air", "Water"},
          "%s / %s" % (lead_el, second_el))
    ribbon = page.inner_text(".zr-ribbon")
    rarity = int(re.search(r"1 in (\d+)", ribbon).group(1))
    check("the rarity ribbon quotes a number the config measured",
          rarity in {n for a in table["rarity"].values()
                     for s in a.values() for n in s.values()},
          ribbon)
    check("  and it is the one for this exact blend",
          rarity == table["rarity"][ARCHETYPE[lead_el]][second_el.lower()][
              formula.rsplit(" · ", 1)[-1].lower()],
          "%s says %d" % (formula, rarity))

    print("\n--- the numbers are this session's tallies ---")
    scales = page.eval_on_selector_all(".zr-scale", """ns => ns.map(n => [
        n.querySelector('.zr-scale-pole').innerText,
        n.querySelector('.zr-scale-pole.is-right').innerText,
        parseFloat(n.querySelector('.zr-scale-dot').style.left)])""")
    check("three scales, poled as the config declares them",
          [[a, b] for a, b, _ in scales]
          == [[r["left"].upper(), r["right"].upper()] for r in table["scales"]],
          str(scales))
    check("  every dot is somewhere on its own track",
          all(0 <= at <= 100 for _, _, at in scales), str(scales))
    split = page.eval_on_selector_all(".zr-split-seg", """ns => ns.map(
        n => parseFloat(n.style.width))""")
    caption = page.inner_text(".zr-split-caption")
    check("the split bar has all four elements",
          [w for w in re.findall(r"% (\w+)", caption)]
          == ["Fire", "Earth", "Air", "Water"], caption)
    check("  its shares add up to a whole profile, exactly",
          len(split) == 4 and sum(split) == 100, str(split))
    check("  and the caption is the bar in words",
          [int(n) for n in re.findall(r"(\d+)%", caption)]
          == [int(w) for w in split],
          "%s vs %s" % (caption, split))
    # Not "the widest segment is the lead": an archetype is won on three tags,
    # so a Deep Water reader can out-score air and still be Deep Water, and
    # the hero names the archetype's element rather than the tallest bar. What
    # must hold is the undercurrent — that is measured, and it is the highest
    # of the three the lead is not.
    order = ["Fire", "Earth", "Air", "Water"]
    others = [(pct, -i) for i, pct in enumerate(split)
              if order[i] != lead_el]
    check("the undercurrent is the strongest element the lead is not",
          second_el == order[-max(others)[1]],
          "%s undercurrent, split %s" % (second_el, split))
    cross = page.inner_text(".zr-crossline")
    check("the sign line is this sign against this lead",
          cross == table["sign_cross"][SIGN][lead_el.lower()], cross)

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

    print("\n--- the one strength they get for nothing ---")
    nodes = page.eval_on_selector_all(".zr-node", """ns => ns.map(n => ({
        open: n.classList.contains('is-open'),
        title: n.querySelector('.zr-node-title').innerText.trim()
    }))""")
    check("exactly one open node, and it is the free strength",
          len(nodes) == 1 and nodes[0]["open"]
          and nodes[0]["title"] == cfg["report"]["mistake_one"]["title"],
          str(nodes))
    check("  it is in a list of its own, not on a path to nowhere",
          page.locator(".zr-free .zr-node").count() == 1
          and page.locator(".zr-path").count() == 0)
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
    check("the element balance chart is gone — the hero says it now",
          page.locator(".zr-bal").count() == 0)

    print("\n--- the six questions the reading answers ---")
    bridge = page.inner_text(".zr-bridge")
    check("a bridge line in their own subtype",
          bridge.endswith(":") and subtype.replace("The ", "") in bridge,
          bridge)
    cards = page.eval_on_selector_all(".zr-card", """ns => ns.map(n => ({
        key: n.querySelector('.zr-card-key').innerText,
        line: n.querySelector('.zr-card-line').innerText.trim(),
        icon: !!n.querySelector('.zr-card-icon svg path'),
        lock: !!n.querySelector('.zr-card-lock svg path')
    }))""")
    # Every chapter, not only the ones the old path drew. `palette` carries
    # `reveal: visible` and the constellation therefore never showed it at
    # all, which meant a page selling six chapters listed five of them.
    chapters = [s for s in cfg["report"]["sections"]
                if s.get("enabled") is not False]
    check("one card per chapter, none left over",
          len(cards) == len(chapters) == len(table["cards"]), str(len(cards)))
    check("  in the order the config lists them",
          [c["key"] for c in cards]
          == ["%s:" % row["key"] for row in table["cards"]],
          str([c["key"] for c in cards]))
    for got, want in zip(cards, table["cards"]):
        check("  %-13s leads with its keyword" % want["id"],
              got["line"].startswith("%s: " % want["key"])
              and len(got["line"]) > len(want["key"]) + 12,
              got["line"])
        check("    an icon and a lock beside it",
              got["icon"] and got["lock"],
              "icon %s lock %s" % (got["icon"], got["lock"]))
    check("no token is left showing on any of them",
          not any("{" in c["line"] for c in cards),
          str([c["line"] for c in cards if "{" in c["line"]]))
    # The blind-spots card names the moon they chose, through engine.js's own
    # hook machinery — so the word in it is a card out of this run, or the
    # declared fallback if the step was somehow never reached.
    blind = [c for c in cards if c["key"] == "Blind spots:"][0]["line"]
    word = re.search(r"your (.+?) pick", blind)
    tapped_labels = {(label or "").lower() for label, _ in taken.values()}
    check("  the moon token answered out of this run",
          bool(word) and (word.group(1) in tapped_labels
                          or word.group(1) == "moon"),
          blind)
    check("  and the blueprint names the lead and the undercurrent",
          lead_el in [c for c in cards
                      if c["key"] == "Blueprint:"][0]["line"]
          and second_el in [c for c in cards
                            if c["key"] == "Blueprint:"][0]["line"],
          str([c["line"] for c in cards if c["key"] == "Blueprint:"]))
    check("no locked constellation node is left on the page",
          page.locator(".zr-node.is-locked").count() == 0)

    print("\n--- and the offer is named for what it is ---")
    check("the offer headline carries the subtype",
          subtype.replace("The ", "") in page.inner_text(".zr-offer-head")
          and "6 chapters" in page.inner_text(".zr-offer-head"),
          page.inner_text(".zr-offer-head"))

    print("\n--- no consent box, anywhere on the page ---")
    # Off for everyone rather than off outside a country list. The element
    # still exists — it is what enables the button — but nothing on screen
    # asks for it and nothing shows it.
    check("no consent control is on the page",
          page.locator("#withdrawal:visible").count() == 0
          and page.locator(".zr-offer #withdrawal").count() == 0)
    check("  and no checkbox of any kind is",
          page.locator("#result-module input[type=checkbox]").count() == 0)
    check("  yet the button is live, so it is satisfied not stranded",
          page.eval_on_selector("#withdrawal-check", "n => n.checked") is True
          and page.get_attribute(".zr-offer #pay-button",
                                 "disabled") is None)

    print("\n--- and a wallet was offered ---")
    check("the funnel asked for a payment intent",
          any(path == "/api/payment-intent" for path, _ in posted))
    check("  and the wallet's block sits in the offer card",
          page.locator(".zr-offer #xp-slot").count() == 1)
    # Stripe.js is a third-party script and does not load in here, so every
    # run ends on the redirect fallback. That the fallback still works is
    # worth as much as the wallet: it is what a blocked reader gets.
    check("  falling back to the redirect button when Stripe cannot load",
          page.get_attribute(".zr-offer #pay-button", "disabled") is None,
          "button dead after fallback")

    print("\n--- the offer is engine.js's, placed here ---")
    check("the pay button is inside it too",
          page.locator(".zr-offer #pay-button").count() == 1)
    # textContent, not innerText: the label is engine.js's own string with the
    # price folded into it, and reading it as rendered text made this check
    # race the frame the button is written on.
    label = page.eval_on_selector(".zr-offer #pay-button", "n => n.textContent")
    check("  labelled from the config",
          label == cfg["checkout"]["cta_label"].replace(
              "{price}", "$%d" % (cfg["pricing"]["amount_cents"] // 100)),
          repr(label))
    check("  and enabled, because consent is satisfied",
          page.get_attribute(".zr-offer #pay-button", "disabled") is None)
    check("the anchor names what it undercuts",
          cfg["checkout"]["commerce"]["anchor_head_accent"]
          in page.inner_text(".zr-anchor"), page.inner_text(".zr-anchor"))
    check("the trust line is built from the commerce strings",
          all(part in page.inner_text(".zr-trust")
              for part in cfg["checkout"]["commerce"]["trust"]),
          page.inner_text(".zr-trust"))

    print("\n--- and it can be read on a phone ---")
    # The token these carry measured 4.14:1 on this background, under the 4.5
    # a body size needs, and it was the colour of every teaser line.
    MINIMUM = {".zr-card-line": 14, ".zr-lead": 14, ".zr-strength-body": 15,
               ".zr-crossline": 14, ".zr-bridge": 14, ".zr-formula": 12,
               ".zr-split-caption": 11, ".zr-trust": 12}
    for selector, floor in sorted(MINIMUM.items()):
        got = page.eval_on_selector(selector, """n => {
            const c = getComputedStyle(n);
            return [parseFloat(c.fontSize),
                    parseFloat(c.lineHeight) / parseFloat(c.fontSize)];
        }""")
        check("  %-34s at %gpx" % (selector, got[0]), got[0] >= floor,
              "below %dpx" % floor)
    for selector in (".zr-card-line", ".zr-strength-body"):
        got = page.eval_on_selector(selector, """n => {
            const c = getComputedStyle(n);
            return parseFloat(c.lineHeight) / parseFloat(c.fontSize);
        }""")
        check("  %-34s breathes at %.2f" % (selector, got), got >= 1.45,
              "under 1.45")
    # A promise line that runs under its own padlock. The text rect is what
    # says so, because the element's box is full width whatever its padding.
    collisions = page.evaluate("""() => {
        const out = [];
        document.querySelectorAll('.zr-card').forEach(card => {
            const el = card.querySelector('.zr-card-line');
            const r = document.createRange();
            r.selectNodeContents(el);
            const t = r.getBoundingClientRect();
            const lock = card.querySelector('.zr-card-lock')
                             .getBoundingClientRect();
            if (t.right > lock.left) out.push(el.innerText.trim());
        });
        return out;
    }""")
    check("  no promise line runs under its padlock", not collisions,
          str(collisions))
    # The hero is a stack of measured rows; two of them overlapping is the
    # failure mode a screenshot catches and an assertion about text does not.
    overlap = page.evaluate("""() => {
        const rows = [...document.querySelectorAll(
            '.zr-hero-top, .zr-ribbon, .zr-scales, .zr-split, .zr-crossline')];
        const out = [];
        for (let i = 1; i < rows.length; i++) {
            const a = rows[i - 1].getBoundingClientRect();
            const b = rows[i].getBoundingClientRect();
            if (b.top < a.bottom) out.push(rows[i].className);
        }
        return out;
    }""")
    check("  and no two rows of the hero card overlap", not overlap,
          str(overlap))

    print("\n--- and it takes a payment ---")
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
    print("\n--- and kitchen keeps the built-in page, and its consent ---")
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
          and not page.locator(".zr-offer").count())
    check("  visible, and gating its button",
          page.locator("#commerce #withdrawal").is_visible())
    page.uncheck("#withdrawal-check")
    page.wait_for_timeout(250)
    check("    unchecking it disables the pay button",
          page.get_attribute("#pay-button", "disabled") is not None)
    page.check("#withdrawal-check")
    page.wait_for_timeout(250)
    check("    and checking it enables it again",
          page.get_attribute("#pay-button", "disabled") is None)
    check("  with no wallet, because kitchen asks for none",
          page.locator("#xp-slot").count() == 0)


def main():
    socketserver.TCPServer.allow_reuse_address = True
    httpd = socketserver.TCPServer(("127.0.0.1", PORT), Handler)
    threading.Thread(target=httpd.serve_forever, daemon=True).start()
    try:
        with sync_playwright() as pw:
            browser = pw.chromium.launch(executable_path=CHROME)
            page = browser.new_page(viewport={"width": 390, "height": 844})
            page.errors = []

            def note(text):
                # Stripe.js is a third-party script on a network this suite
                # does not have, so its load failure is a fact about the
                # sandbox rather than a fault on the page — and the redirect
                # fallback it triggers is itself asserted below. Everything
                # else counts.
                if "Failed to load resource" in text:
                    return
                page.errors.append(text)

            page.on("pageerror", lambda e: note(str(e)))
            page.on("console",
                    lambda m: note(m.text) if m.type == "error" else None)
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
