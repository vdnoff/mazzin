#!/usr/bin/env python3
"""How zodiac30's screens behave in a browser: the beats, and the deal.

The config suite can say the funnel asks for a thing. Only a page can say
what the thing is.

The self-advancing interstitial: that the button is gone, that the screen
leaves on its own inside the beat it named, that a tap gets there first, and
that nothing advances twice when both happen.

The pinned first slot: that Love actually arrives top-left on the seeking
step, run after run, while the other three cards keep moving. Config order
decided nothing before this — every card on the step was shuffled, so
whichever id was authored first reached that slot about one run in four, and
the only way to tell the difference is to load the page repeatedly.

The other half of both is what did not change. zodiac and kitchen carry
neither flag, so their interstitials still draw the button and still wait to
be pressed, and every step of theirs still deals shuffled — claims about the
engine's default path, asserted here rather than assumed from the diff.

    python3 tests/test_zodiac30flow.py
"""
import http.server
import json
import os
import socketserver
import sys
import threading

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, REPO)

from playwright.sync_api import Error as PageError        # noqa: E402
from playwright.sync_api import sync_playwright           # noqa: E402

ROOT = REPO
PORT = 8851
CHROME = "/opt/pw-browsers/chromium-1194/chrome-linux/chrome"

# engine.js holds a chosen card on screen — ring, badge, then the reaction
# chip — before the set leaves. Nothing about the next screen may be asserted
# until that has run.
HOLD_MS = 1650
SETTLE_MS = 420

fails = []
checks = [0]


def check(label, ok, detail=""):
    checks[0] += 1
    if not ok:
        fails.append("%s %s" % (label, detail))
    print("  %-58s %s%s" % (label, "ok" if ok else "FAIL",
                            ("  " + str(detail)) if not ok else ""))


class Handler(http.server.SimpleHTTPRequestHandler):
    """static/ off disk, the slugs are the shell, the APIs are stubbed."""

    def __init__(self, *a, **kw):
        super().__init__(*a, directory=ROOT, **kw)

    def log_message(self, *a):
        pass

    def do_GET(self):
        path = self.path.split("?")[0]
        if path == "/api/pixel-config":
            return self._json({})
        if path in ("/zodiac", "/zodiac30", "/kitchen"):
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


def start(page, slug):
    page.goto("http://127.0.0.1:%d/%s" % (PORT, slug))
    page.wait_for_selector("#cards .card", timeout=20000)
    page.wait_for_timeout(400)


def tap_card(page):
    """Tap the first card, wait out the hold, stop at whatever is next.

    A run that has no card to tap has already left the quiz — which is a
    failed expectation somewhere above, not a reason to stop the suite and
    print a driver traceback in place of the checks still to come.
    """
    cards = page.locator("#cards .card")
    if not cards.count():
        return False
    try:
        cards.first.click(timeout=4000)
    except PageError:
        return False
    page.wait_for_timeout(HOLD_MS + SETTLE_MS)
    return True


def mid_visible(page):
    return page.locator("#screen-interstitial.is-active").count() == 1


def gone(page, ms):
    """True once the interstitial has left, within `ms`. Never raises.

    A regression here is a screen that sits there, and a bare
    `wait_for_selector` turns that into a traceback halfway down the run
    instead of a named failure with the rest of the suite still to come.
    """
    for _ in range(int(ms / 50) + 1):
        if not mid_visible(page):
            return True
        page.wait_for_timeout(50)
    return not mid_visible(page)


def klass(page, selector):
    """The class list of a node, or "" when the node is not there.

    Read through the locator rather than `page.get_attribute`, which waits
    thirty seconds for a node that a regression has removed and turns a
    failing check into a hung suite.
    """
    node = page.locator(selector)
    if not node.count():
        return ""
    return node.first.get_attribute("class") or ""


def to_interstitial(page, limit=6):
    """Tap through steps until an interstitial is on screen. True if one is."""
    for _ in range(limit):
        if not tap_card(page):
            return False
        if mid_visible(page):
            return True
    return False


def step_of(page):
    return page.evaluate(
        "() => document.querySelectorAll('#mid-pips .pip.is-done').length")


def run(page):
    print("\n--- zodiac30: the first beat arrives without a button ---")
    start(page, "zodiac30")
    check("an interstitial is reached", to_interstitial(page))
    check("  it is the one after the sign step", step_of(page) == 2,
          step_of(page))
    check("  the screen carries the mode's class",
          "is-auto" in klass(page, "#screen-interstitial"),
          klass(page, "#screen-interstitial"))
    check("  and its entrance class, so the beats played",
          "is-enter" in klass(page, "#screen-interstitial"))
    check("there is no Continue button on it",
          not page.locator("#mid-cta").is_visible())
    check("  the node is hidden rather than emptied, so nothing is tappable",
          page.evaluate("() => document.getElementById('mid-cta').hidden")
          is True)
    check("the kicker and the line are both filled",
          bool(page.text_content("#mid-kicker").strip())
          and bool(page.text_content("#mid-line").strip()),
          "%r / %r" % (page.text_content("#mid-kicker"),
                       page.text_content("#mid-line")))
    check("  and this one drops its sub, as the config says",
          page.evaluate("() => document.getElementById('mid-sub').hidden")
          is True)
    check("the accent is on screen",
          page.locator("#mid-accent").count() == 1
          and page.locator("#mid-accent").is_visible())
    check("  a spark on a confirm beat, not a rule",
          "is-spark" in klass(page, "#mid-accent"),
          klass(page, "#mid-accent"))
    check("  and the working spinner stays out of the way",
          page.locator("#mid-working").count() == 0
          or not page.locator("#mid-working").is_visible())

    print("\n--- it leaves on its own ---")
    # Its own beat is 2000ms and the default this replaces is 4000ms, so the
    # window between them is what says the entry's own timing is the one
    # running: still there at 1.2s, gone by 2.6s.
    page.wait_for_timeout(1200)
    check("still on screen a second in", mid_visible(page))
    check("gone by its own beat, with no tap and no button", gone(page, 1400))
    check("  and the quiz is what came back",
          page.locator("#cards .card").count() >= 2)

    print("\n--- and a tap gets there first ---")
    check("the next interstitial is reached", to_interstitial(page))
    before = step_of(page)
    # Three taps in the same breath, which is what an impatient thumb does to
    # a screen with nothing on it to press. Dispatched rather than driven,
    # because the second and third land on a screen already on its way out
    # and a driver would wait for it to be clickable again. One dismissal,
    # not three.
    page.evaluate("""() => {
        const s = document.getElementById('screen-interstitial');
        for (let i = 0; i < 3; i++) s.click();
    }""")
    check("a tap anywhere on it advances immediately", gone(page, 1200),
          "was after step %s" % before)
    check("  and a flurry of them still only advances once",
          step_of(page) == before, "%s vs %s" % (step_of(page), before))
    # The dismiss it outran is still pending. Whether it is cancelled or
    # merely refused on arrival is asserted against the source in
    # test_zodiac30_check; what a page can say is that nothing moves when it
    # comes due.
    cards = page.locator("#cards .card").count()
    page.wait_for_timeout(2600)
    check("  and nothing moves when that beat would have ended",
          not mid_visible(page)
          and page.locator("#cards .card").count() == cards
          and step_of(page) == before,
          "%s cards, mid=%s, step %s"
          % (page.locator("#cards .card").count(), mid_visible(page),
             step_of(page)))
    # The step after a skipped beat is the next one, not the one after it.
    tap_card(page)
    check("  the next tap moves the walk on by exactly one",
          step_of(page) == before + 1,
          "%s vs %s" % (step_of(page), before + 1))

    print("\n--- the almost beats draw a rule to how far along they are ---")
    # Anchors 8 and 15 are the `almost` templates. Walk to the next one and
    # read the accent off the page rather than off the config.
    found = None
    for _ in range(8):
        if not to_interstitial(page, limit=4):
            break
        if "is-bar" in klass(page, "#mid-accent"):
            found = step_of(page)
            break
        page.click("#screen-interstitial")
        gone(page, 1500)
    check("an almost beat draws a bar", found is not None, str(found))
    READ = """() => {
        const f = document.querySelector('#mid-accent .mid-accent-fill');
        if (!f) return null;
        const cs = getComputedStyle(f);
        const m = cs.transform;
        return {
            scale: (m && m !== 'none')
                ? parseFloat(m.replace(/matrix\\(|\\)/g, '').split(',')[0])
                : null,
            property: cs.transitionProperty,
            duration: parseFloat(cs.transitionDuration),
            delay: parseFloat(cs.transitionDelay)};
    }"""
    fill = page.locator("#mid-accent .mid-accent-fill")
    if found is not None and fill.count():
        want = found / 18.0
        opening = page.evaluate(READ)
        # It has to draw rather than arrive drawn, and it has to draw by
        # transform: a width animation on this screen is layout work in the
        # middle of a beat that runs while the next pair is still decoding.
        check("  the rule is transitioned, not simply set",
              opening["property"] == "transform" and opening["duration"] > 0
              and opening["delay"] > 0, str(opening))
        check("  and it is still short of its mark when the screen opens",
              opening["scale"] is not None and opening["scale"] < want - 0.01,
              "%s vs %.3f" % (opening["scale"], want))
        page.wait_for_timeout(1400)
        drawn = page.evaluate(READ)
        check("  it ends scaled to how far through the walk they are",
              drawn["scale"] is not None and abs(drawn["scale"] - want) < 0.02,
              "%s vs %.3f after step %s" % (drawn["scale"], want, found))
        shown = page.text_content("#mid-line") or ""
        check("  and the sentence above it says the same number",
              "%d%%" % round(want * 100) in shown, shown)

    print("\n--- zodiac keeps its button, and keeps waiting ---")
    start(page, "zodiac")
    check("an interstitial is reached", to_interstitial(page))
    check("  it draws the Continue button",
          page.locator("#mid-cta").is_visible()
          and bool((page.text_content("#mid-cta") or "").strip()),
          page.text_content("#mid-cta"))
    check("  the mode's class is nowhere on it",
          "is-auto" not in klass(page, "#screen-interstitial"),
          klass(page, "#screen-interstitial"))
    check("  and it draws no accent",
          page.locator("#mid-accent").count() == 0
          or not page.locator("#mid-accent").is_visible())
    check("  its working row is the one it always had",
          page.locator("#mid-working").is_visible())
    # The default dismiss is four seconds. Two and a half in it must still be
    # standing, and a tap on the background must not have moved it.
    page.mouse.click(190, 300)
    page.wait_for_timeout(2500)
    check("a tap beside the button does nothing, as before", mid_visible(page))
    page.click("#mid-cta")
    check("  and the button is what dismisses it", gone(page, 2000))

    print("\n--- the seeking step opens on Love, every run ---")
    # Nothing here can be read off one page. The claim is about what a
    # shuffle does across runs, so the funnel is walked to the seeking step
    # from a fresh load each time and the deal is recorded.
    RUNS = 8
    IDS = """() => [...document.querySelectorAll('#cards .card img')]
        .map(n => n.getAttribute('src').split('/').pop())
        .map(n => n.replace('.webp', ''))"""
    seeking, signs = [], []
    for _ in range(RUNS):
        start(page, "zodiac30")
        tap_card(page)                       # 1 hook -> 2 sign
        signs.append(page.evaluate(IDS))
        tap_card(page)                       # 2 sign -> the beat after it
        gone(page, 2600)                     # which leaves on its own
        page.wait_for_timeout(SETTLE_MS)
        seeking.append(page.evaluate(IDS))
    check("every run reached the seeking step",
          all(len(d) == 4 and all(i.startswith("sk3") for i in d)
              for d in seeking), str(seeking[:2]))
    check("  Love is top-left on all %d of them" % RUNS,
          all(d and d[0] == "sk3a" for d in seeking),
          str([d[0] for d in seeking if d]))
    # The other side of the flag, and the reason it is not `shuffle: false`:
    # the three cards that carry no order of their own still have none.
    tails = {tuple(d[1:]) for d in seeking if len(d) == 4}
    check("  and the other three are still dealt in no fixed order",
          len(tails) > 1, str(sorted(tails)))
    check("  none of them ever taking the first slot",
          not [d for d in seeking if d and d[0] != "sk3a"],
          str([d for d in seeking if d and d[0] != "sk3a"]))
    check("  the same four cards every time, only reordered",
          len({tuple(sorted(d)) for d in seeking}) == 1,
          str(sorted({tuple(sorted(d)) for d in seeking})))
    # The step that already pinned every slot is untouched by the new flag.
    ZODIAC = ["aries", "taurus", "gemini", "cancer", "leo", "virgo", "libra",
              "scorpio", "sagittarius", "capricorn", "aquarius", "pisces"]
    want = ["sign_" + name for name in ZODIAC]
    check("the sign step still deals Aries to Pisces, unshuffled",
          all(d == want for d in signs),
          str([d for d in signs if d != want][:1]))

    print("\n--- and every other step still shuffles ---")
    # One step pinned is one step. The proof that the rest were left alone is
    # that a step with neither flag still moves its first card around, which
    # is what the hook step is read for here: it is the same two cards on
    # every load and the only thing that can differ is the order.
    hooks = set()
    for _ in range(RUNS):
        start(page, "zodiac30")
        hooks.add(tuple(page.evaluate(IDS)))
    check("the hook step deals its pair both ways round", len(hooks) == 2,
          str(sorted(hooks)))

    print("\n--- kitchen is untouched ---")
    start(page, "kitchen")
    check("an interstitial is reached", to_interstitial(page, limit=8))
    check("  it draws the Continue button",
          page.locator("#mid-cta").is_visible())
    check("  with no mode class and no accent",
          "is-auto" not in klass(page, "#screen-interstitial")
          and page.locator("#mid-accent").count() == 0)
    page.wait_for_timeout(2500)
    check("  and it is still there without a press", mid_visible(page))


def main():
    socketserver.TCPServer.allow_reuse_address = True
    httpd = socketserver.TCPServer(("127.0.0.1", PORT), Handler)
    threading.Thread(target=httpd.serve_forever, daemon=True).start()
    try:
        with sync_playwright() as pw:
            browser = pw.chromium.launch(executable_path=CHROME)
            page = browser.new_page(viewport={"width": 390, "height": 844})
            run(page)
            browser.close()
    finally:
        httpd.shutdown()

    print("\n%d checks, %d failed" % (checks[0], len(fails)))
    for line in fails:
        print("  FAIL " + line)
    return 1 if fails else 0


if __name__ == "__main__":
    sys.exit(main())
