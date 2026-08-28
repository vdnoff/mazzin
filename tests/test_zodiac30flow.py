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
import re
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
    """static/ off disk, the slugs are the shell, the APIs are stubbed.

    `strip_purpose` serves zodiac30's config with its purpose block taken out,
    which is the only way to see what a funnel that never declared one does
    without editing a file in the repo to find out. It is the same code path
    zodiac v1 and both kitchens take every time.
    """

    strip_purpose = False
    # Served without the `personal` blocks, which is how a run reaches the
    # base lines without having to engineer a tie on every axis at once.
    strip_personal = False
    # Served without `echo_steps`, which is the only way left to see an auto
    # interstitial that has no row on it — every one of this funnel's does
    # now, and the spark yields wherever a row does. The engine still draws
    # it for an auto beat without one, so that is where it is tested.
    strip_echo = False
    # Served without the hook slot {sign} resolves through, which is the only
    # way to see a personalised line whose own token cannot be answered. The
    # engine falls back to the base line rather than printing a hole or
    # taking the screen down.
    strip_sign_slot = False

    def __init__(self, *a, **kw):
        super().__init__(*a, directory=ROOT, **kw)

    def log_message(self, *a):
        pass

    def do_GET(self):
        path = self.path.split("?")[0]
        if path == "/api/pixel-config":
            return self._json({})
        if path == "/static/funnels/zodiac30.json" and (
                Handler.strip_purpose or Handler.strip_personal
                or Handler.strip_echo or Handler.strip_sign_slot):
            with open(os.path.join(ROOT, "static/funnels/zodiac30.json"),
                      encoding="utf-8") as fh:
                cfg = json.load(fh)
            if Handler.strip_purpose:
                cfg["result_copy"].pop("purpose_map", None)
            if Handler.strip_personal:
                for entry in cfg.get("interstitials") or []:
                    entry.pop("personal", None)
            if Handler.strip_echo:
                cfg.pop("analyzing_echo", None)
                for entry in cfg.get("interstitials") or []:
                    entry.pop("echo_steps", None)
            if Handler.strip_sign_slot:
                (cfg.get("report") or {}).get("hook_slots", {}).pop("sign",
                                                                    None)
            return self._json(cfg)
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


RESULT = """() => {
  const off = document.querySelector('.zr-offer');
  if (!off) return null;
  return {
    sub: (off.querySelector('.zr-offer-sub') || {}).textContent || "",
    head: (off.querySelector('.zr-offer-head') || {}).textContent || "",
    subtype: (document.querySelector('.zr-subtype') || {}).textContent || "",
    open: [...document.querySelectorAll('.zr-node.is-open')].map(
      n => (n.querySelector('.zr-node-title') || {}).textContent),
    cards: [...document.querySelectorAll('.zr-card')].map(n => ({
      key: (n.querySelector('.zr-card-key') || {}).textContent,
      line: (n.querySelector('.zr-card-line') || {}).textContent.trim(),
      lead: n.classList.contains('is-lead'),
      edge: getComputedStyle(n).borderTopColor}))};
}"""

# The six question cards, in the order the config lists them. Anything else on
# screen is a reorder, which is the whole subject below.
CANON = ["Love:", "Blind spots:", "Your year:", "Money:", "Power colors:",
         "Blueprint:"]
DEFAULT_SUB = "Your complete profile — once, forever."
# The two edges a card can wear. The chapter they came for steps up exactly
# one, on the card that is already first.
LINE = "rgba(232, 200, 120, 0.22)"
LEAD_LINE = "rgba(232, 200, 120, 0.55)"


def to_result(page, slug, seeking=None):
    """Walk a whole funnel to its result page, or None if it never arrives.

    `seeking` names a card to tap when the step offering it comes up; every
    other step takes whatever is in the first slot.
    """
    page.goto("http://127.0.0.1:%d/%s" % (PORT, slug))
    page.wait_for_selector("#cards .card", timeout=20000)
    page.wait_for_timeout(300)
    for _ in range(40):
        module = page.locator("#result-module")
        if module.count() and not module.is_hidden():
            break
        cards = page.locator("#cards .card")
        if not cards.count():
            page.wait_for_timeout(300)
            continue
        target = cards.first
        if seeking:
            named = page.locator("#cards .card", has_text=seeking)
            if named.count():
                target = named.first
        try:
            target.click(timeout=4000)
        except PageError:
            # A card that would not take a tap is usually one caught mid-exit,
            # not a dead run. Give the step a beat and look again; the loop
            # bound is what stops a genuinely stuck funnel here.
            page.wait_for_timeout(400)
            continue
        page.wait_for_timeout(HOLD_MS + SETTLE_MS)
        for _ in range(200):
            if not mid_visible(page):
                break
            page.wait_for_timeout(20)
        page.wait_for_timeout(180)
    page.wait_for_timeout(3200)
    return page.evaluate(RESULT)


BEAT = """() => {
  const s = document.getElementById('screen-interstitial');
  if (!s || !s.classList.contains('is-active')) return null;
  const a = document.getElementById('mid-accent');
  const sub = document.getElementById('mid-sub');
  return {
    line: (document.getElementById('mid-line') || {}).textContent || "",
    sub: sub && !sub.hidden ? sub.textContent : "",
    echo: [...document.querySelectorAll('#mid-echo .mid-echo-cell img')]
      .map(n => n.getAttribute('src').split('/').pop().replace('.webp', '')),
    delays: [...document.querySelectorAll('#mid-echo .mid-echo-cell')]
      .map(n => n.style.animationDelay),
    accent: a && !a.hidden ? a.className : ""};
}"""


def plan(slug, prefer=(), overrides=None):
    """One image id per step: the card carrying most of `prefer`, or the first.

    Computed here rather than chosen in the browser because the tags are the
    config's and the page does not carry them. `overrides` pins named steps.
    """
    cfg = json.load(open(os.path.join(ROOT, "funnels/%s.json" % slug),
                        encoding="utf-8"))
    want = set(prefer)
    out = []
    for step in cfg["swipe"]["steps"]:
        images = [i for p in step["pairs"] for i in p["images"]]
        pick = (overrides or {}).get(step["id"])
        if not pick:
            best = max(images, key=lambda i: len(set(i["tags"]) & want))
            pick = best["id"] if set(best["tags"]) & want else images[0]["id"]
        out.append(pick)
    return out


def element_tie(slug, upto=9):
    """One image id per step through `upto` that leaves no element ahead.

    Built rather than pinned, because the interesting state is a property of
    the tallies and a hand-written list of card ids stops being that the first
    time a card is retagged. Depth-first over each step's own cards, taking
    the first assignment whose top element is shared — which is exactly what
    `soleLeaderOf` refuses to name.
    """
    cfg = json.load(open(os.path.join(ROOT, "funnels/%s.json" % slug),
                         encoding="utf-8"))
    steps = cfg["swipe"]["steps"][:upto]
    ELEMENTS = ("fire", "earth", "air", "water")

    def walk(n, scores, taken):
        if n == len(steps):
            top = max(scores.values())
            level = [t for t in ELEMENTS if scores[t] == top]
            return (list(taken), dict(scores)) if len(level) > 1 else None
        step = steps[n]
        weight = -0.5 if step.get("scoring") == "inverse" else 1
        for item in [i for p in step["pairs"] for i in p["images"]]:
            hit = [t for t in item.get("tags") or [] if t in ELEMENTS]
            for tag in hit:
                scores[tag] += weight
            found = walk(n + 1, scores, taken + [item["id"]])
            for tag in hit:
                scores[tag] -= weight
            if found:
                return found
        return None

    found = walk(0, dict((t, 0) for t in ELEMENTS), [])
    if not found:
        return None, None
    ids, scores = found
    # The rest of the walk is whatever the plan would have taken; only the
    # steps before the beat decide what it says.
    rest = plan(slug)[upto:]
    return ids + rest, scores


def walk_beats(page, slug, ids, stop_after=None):
    """Walk a funnel tapping named cards, reading every interstitial on the way.

    Returns (beats, tapped). `stop_after` leaves the walk once that step's
    beat has been read, for the runs that only care about an early one.
    """
    page.goto("http://127.0.0.1:%d/%s" % (PORT, slug))
    page.wait_for_selector("#cards .card", timeout=20000)
    page.wait_for_timeout(300)
    beats, tapped = [], []
    for index in range(len(ids)):
        cards = page.locator("#cards .card")
        if not cards.count():
            break
        target = page.locator("#cards .card img[src$='%s.webp']" % ids[index])
        node = target.first.locator("xpath=..") if target.count() \
            else cards.first
        try:
            node.click(timeout=4000)
        except PageError:
            page.wait_for_timeout(400)
            continue
        tapped.append(ids[index] if target.count() else None)
        page.wait_for_timeout(HOLD_MS + SETTLE_MS)
        if mid_visible(page):
            # Late enough that every thumbnail has had its delay, early
            # enough that the shortest beat is still up.
            page.wait_for_timeout(1300)
            got = page.evaluate(BEAT)
            if got:
                got["after"] = index + 1
                beats.append(got)
            for _ in range(300):
                if not mid_visible(page):
                    break
                page.wait_for_timeout(20)
        page.wait_for_timeout(140)
        if stop_after and index + 1 >= stop_after:
            break
    return beats, tapped


def beat(beats, after):
    for row in beats:
        if row["after"] == after:
            return row
    return None


# The browser, so the sale section can open a page per clock. An init script
# cannot be taken off a page once it is on, and engine.js reads the clock as
# it renders, so each side of the boundary needs a page of its own.
BROWSER = [None]


def fresh(iso):
    page = BROWSER[0].new_page(viewport={"width": 390, "height": 844})
    page.add_init_script(clock(iso))
    return page


def clock(iso):
    """A page whose Date is pinned, so both sides of the sale are reachable.

    An init script rather than an evaluate: engine.js reads the clock while it
    renders, so the stub has to be in place before the first line of it runs.
    """
    return ("(() => { const AT = Date.parse(%r); const Real = Date;"
            " class Stub extends Real {"
            "   constructor(...a) { super(...(a.length ? a : [AT])); }"
            "   static now() { return AT; } }"
            " window.Date = Stub; })();" % iso)


OFFER = """() => {
  const o = document.querySelector('.zr-offer');
  if (!o) return null;
  const t = s => { const n = o.querySelector(s);
                   return n ? n.textContent : null; };
  return {
    now: t('.zr-price-now'), was: t('.zr-price-was'), sale: t('.zr-sale'),
    note: t('.zr-price-note'), anchor: t('.zr-anchor'),
    sub: t('.zr-offer-sub'),
    badges: [...o.querySelectorAll('.zr-badge')].map(n => n.textContent),
    button: (document.getElementById('pay-button') || {}).textContent,
    strike: (() => { const n = o.querySelector('.zr-price-was');
      return n ? getComputedStyle(n).textDecorationLine : null; })(),
    label: (() => { const n = o.querySelector('.zr-price-was');
      return n ? n.getAttribute('aria-label') : null; })(),
    residue: o.textContent.toLowerCase()};
}"""


def offer_at(slug, iso):
    """Walk a funnel to its offer card on a page whose clock says `iso`."""
    page = fresh(iso)
    try:
        return _offer_walk(page, slug)
    finally:
        page.close()


def _offer_walk(page, slug):
    page.goto("http://127.0.0.1:%d/%s" % (PORT, slug))
    page.wait_for_selector("#cards .card", timeout=20000)
    page.wait_for_timeout(300)
    for _ in range(40):
        module = page.locator("#result-module")
        if module.count() and not module.is_hidden():
            break
        cards = page.locator("#cards .card")
        if not cards.count():
            page.wait_for_timeout(300)
            continue
        try:
            cards.first.click(timeout=4000)
        except PageError:
            page.wait_for_timeout(400)
            continue
        page.wait_for_timeout(HOLD_MS + SETTLE_MS)
        for _ in range(300):
            if not mid_visible(page):
                break
            page.wait_for_timeout(20)
        page.wait_for_timeout(150)
    page.wait_for_timeout(3200)
    return page.evaluate(OFFER)


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


# Where the copy sits and how it is set. Both are facts about a layout
# engine rather than about a stylesheet, which is why they are read here: the
# block was measured at 50.5% of the viewport before this mode was centred
# horizontally, so a rule that claimed to fix the vertical would have been
# fixing something that was not broken.
BLOCK = """() => {
  const parts = [...document.querySelectorAll(
      '#mid-kicker, #mid-line, #mid-sub, #mid-accent, #mid-echo')]
    .filter(n => !n.hidden && n.getBoundingClientRect().height > 0)
    .map(n => n.getBoundingClientRect());
  if (!parts.length) return null;
  const top = Math.min(...parts.map(r => r.top));
  const bottom = Math.max(...parts.map(r => r.bottom));
  const line = document.querySelector('#mid-line');
  return {centre: ((top + bottom) / 2) / window.innerHeight * 100,
          align: getComputedStyle(line).textAlign,
          box: [Math.round(top), Math.round(bottom)]};
}"""

# The spark's animations as the browser holds them, not as the sheet declares
# them. `iterations: Infinity` is the whole claim — a loop that was written as
# one long run would read the same in the CSS and stop on screen.
ACCENT = """() => {
  const f = document.querySelector('#mid-accent .mid-accent-fill');
  if (!f) return null;
  const cs = getComputedStyle(f);
  return {names: cs.animationName, glow: cs.boxShadow,
          animations: [...f.getAnimations()].map(a => {
            const t = a.effect.getTiming();
            return {name: a.animationName,
                    iterations: t.iterations === Infinity ? "infinite"
                                                          : t.iterations,
                    direction: t.direction, duration: t.duration};
          })};
}"""


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
    check("  it is the one that closes the first act", step_of(page) == 4,
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
    check("  and this one carries its sub, as the config says",
          page.evaluate("() => document.getElementById('mid-sub').hidden")
          is False
          and bool(page.text_content("#mid-sub").strip()),
          page.text_content("#mid-sub"))
    check("the frames it closed on are what is on screen",
          page.locator("#mid-echo .mid-echo-cell").count() == 4,
          str(page.locator("#mid-echo .mid-echo-cell").count()))
    check("  and the spark yields to them, rather than pulsing beside them",
          page.locator("#mid-accent").count() == 0
          or not page.locator("#mid-accent").is_visible(),
          klass(page, "#mid-accent"))

    print("\n--- the block is placed, not parked in a corner ---")
    block = page.evaluate(BLOCK)
    check("the copy is centred across the column",
          block["align"] == "center", block["align"])
    check("  and sits on the middle of the viewport",
          abs(block["centre"] - 50) <= 2, "%.1f%%" % block["centre"])
    check("  the row centred with it",
          abs(page.evaluate("""() => {
              const a = document.getElementById('mid-echo')
                  .getBoundingClientRect();
              return (a.left + a.right) / 2 - window.innerWidth / 2;
          }""")) < 1)

    print("\n--- and the spark keeps breathing, where a beat has no row ---")
    # Every beat on this funnel hands frames back now, and the spark yields
    # wherever a row does. It is still what an auto interstitial without one
    # draws, so it is tested against a config served without `echo_steps` —
    # the same engine path, the same CSS, one key fewer.
    Handler.strip_echo = True
    try:
        start(page, "zodiac30")
        check("a beat with no row is reached", to_interstitial(page))
        check("  and it draws the spark instead",
              "is-spark" in klass(page, "#mid-accent"),
              klass(page, "#mid-accent"))
        check("  with no row beside it",
              page.locator("#mid-echo .mid-echo-cell").count() == 0)
        check("  centred like the copy above it",
              abs(page.evaluate("""() => {
                  const a = document.getElementById('mid-accent')
                      .getBoundingClientRect();
                  return (a.left + a.right) / 2 - window.innerWidth / 2;
              }""")) < 1)
        spark_probe(page)
    finally:
        Handler.strip_echo = False
    rest_of_run(page)


def spark_probe(page):
    accent = page.evaluate(ACCENT)
    names = [a["name"] for a in accent["animations"]]
    check("two animations on it, the pulse and the breath",
          names == ["mid-spark", "mid-breathe"], str(names))
    breath = [a for a in accent["animations"]
              if a["name"] == "mid-breathe"]
    check("  the breath never ends",
          breath and breath[0]["iterations"] == "infinite", str(breath))
    check("  and turns round rather than restarting",
          breath and breath[0]["direction"] == "alternate", str(breath))
    check("  on a slow cycle, not a flicker",
          breath and 1500 <= breath[0]["duration"] <= 2200, str(breath))
    check("  and the pulse hands over where it ends, not by restarting",
          [a["duration"] for a in accent["animations"]] == [820, 1800],
          str([a["duration"] for a in accent["animations"]]))
    check("  and the working spinner stays out of the way",
          page.locator("#mid-working").count() == 0
          or not page.locator("#mid-working").is_visible())
    # The breath, watched rather than read off the sheet. On its own beat,
    # entered deliberately: the pulse hands over at 1240ms and the beat ends
    # at 2000ms, so there is exactly one window to sample and the checks
    # above have already spent an unknown amount of this one.
    #
    # A fresh run rather than the next beat along, because the next one is an
    # `almost` and draws the rule instead — and a rule does not breathe, which
    # is the thing being sampled.
    start(page, "zodiac30")
    check("another beat with no row is reached", to_interstitial(page))
    page.wait_for_timeout(1300)
    lit = []
    for _ in range(3):
        lit.append(page.evaluate(
            "() => +getComputedStyle(document.querySelector("
            "'#mid-accent .mid-accent-fill')).opacity"))
        page.wait_for_timeout(150)
    check("  it is still moving after its pulse has finished",
          len(set(round(v, 2) for v in lit)) > 1,
          str([round(v, 3) for v in lit]))
    check("  and stays lit while it moves, rather than blinking out",
          all(v > 0.4 for v in lit), str([round(v, 3) for v in lit]))


def rest_of_run(page):
    print("\n--- it leaves on its own ---")
    # Back on the real config, so the beat under test is the one that ships.
    start(page, "zodiac30")
    check("a beat is reached", to_interstitial(page))
    # 2000ms base plus one stagger per thumbnail is 3680ms on a beat closing
    # four steps, against the 4000ms a button screen takes. The window between
    # the two is what says the entry's own timing is the one running: there at
    # 1.2s, gone by 3.9s.
    page.wait_for_timeout(1200)
    check("still on screen a second in", mid_visible(page))
    check("gone by its own beat, with no tap and no button", gone(page, 2800))
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
    # Anchors 9 and 18 are the `almost` templates. Walk to the next one and
    # read the accent off the page rather than off the config.
    # Walked to rather than scanned for. The accent node is hidden rather
    # than reclassed on a beat that yields to its row, so a stale `is-bar`
    # left on a hidden node is not a reading of what is on screen.
    found = None
    for _ in range(8):
        if not to_interstitial(page, limit=6):
            break
        visible = (page.locator("#mid-accent").count()
                   and page.locator("#mid-accent").is_visible())
        if visible and "is-bar" in klass(page, "#mid-accent"):
            found = step_of(page)
            break
        page.click("#screen-interstitial")
        gone(page, 2200)
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
        # The base line of an `almost` beat carries {pct}; a run that resolved
        # a personal line for that beat is reading a sentence written for what
        # it said instead, and that one is not about the percentage. Either
        # way the sentence has to be one this entry could put on screen.
        entry = next(e for e in json.load(
            open(os.path.join(ROOT, "funnels/zodiac30.json"),
                 encoding="utf-8"))["interstitials"]
            if e["after_step"] == found)
        can_show = [entry["line"]] + [
            row.get("line") for row
            in ((entry.get("personal") or {}).get("lines") or {}).values()]
        if "%" in shown:
            check("  and the sentence above it says the same number",
                  "%d%%" % round(want * 100) in shown, shown)
        else:
            check("  and the sentence above it is one this beat can show",
                  shown in can_show, "%r not in %s" % (shown, can_show))
        # Progress, not decoration: the rule is a reading of how far along
        # they are, so it draws once and holds. What stops the held state
        # reading as a dead screen is a glow that is painted rather than
        # animated.
        accent = page.evaluate(ACCENT)
        check("  the rule runs no animation of its own",
              accent["names"] == "none" and not accent["animations"],
              str(accent["names"]))
        check("  it does not breathe — that is the spark's job",
              "mid-breathe" not in accent["names"], accent["names"])
        check("  and it carries a glow instead",
              accent["glow"] and accent["glow"] != "none", accent["glow"])
        bar = page.evaluate(BLOCK)
        check("  the almost block is centred too",
              bar["align"] == "center" and abs(bar["centre"] - 50) <= 2,
              "%s / %.1f%%" % (bar["align"], bar["centre"]))

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
    # Verbatim against its own config, not merely "not zodiac30's". This is
    # the funnel that is live, and it shares every line of this file.
    v1cfg = json.load(open(os.path.join(ROOT, "funnels/zodiac.json"),
                           encoding="utf-8"))
    v1first = v1cfg["interstitials"][0]
    check("  its line is the one its config carries, word for word",
          (page.text_content("#mid-line") or "") == v1first["line"],
          "%r vs %r" % (page.text_content("#mid-line"), v1first["line"]))
    check("    and its sub",
          (page.text_content("#mid-sub") or "") == v1first["sub"],
          "%r vs %r" % (page.text_content("#mid-sub"), v1first["sub"]))
    check("  it hands back no frames",
          page.locator("#mid-echo").count() == 0
          or not page.locator("#mid-echo").is_visible())
    # The centring is the auto mode's, and only the auto mode's. This screen
    # has a control under its copy, which is where ranged-left type belongs,
    # and its block was measured at 45.5% of the viewport before any of this.
    v1 = page.evaluate(BLOCK)
    check("  its copy is still ranged left", v1["align"] == "start",
          v1["align"])
    check("  and sits where it always sat, not on the middle",
          abs(v1["centre"] - 45.5) <= 1.5, "%.1f%%" % v1["centre"])
    check("  with no accent of any kind to glow or breathe",
          page.locator("#mid-accent").count() == 0)
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

    print("\n--- the paywall answers what they said they came for ---")
    # Four runs, one per answer to the seeking step. Each has to promote its
    # own section to the head of what is still locked, keep the rest in report
    # order, and say its own line under the anchor.
    WANT = [("Love", "Love:", "Your compatibility read is inside."),
            ("Career & money", "Money:", "Your money months are inside."),
            ("Inner peace", "Blind spots:",
             "Your calm has a pattern. It's inside."),
            ("The road ahead", "Your year:",
             "Your year, mapped window by window — inside.")]
    for tapped, lead, sub in WANT:
        got = to_result(page, "zodiac30", tapped)
        check("tapping %-14s reaches the result" % tapped, got is not None)
        if not got:
            continue
        keys = [n["key"] for n in got["cards"]]
        check("  %-14s is the first card they meet" % lead,
              keys and keys[0] == lead, str(keys))
        check("    and the other five keep config order",
              keys[1:] == [k for k in CANON if k != lead], str(keys[1:]))
        check("    the offer says their line, not the default one",
              got["sub"] == sub, got["sub"])
        check("    its card is the one marked as led",
              [n["key"] for n in got["cards"] if n["lead"]] == [lead],
              str([n["key"] for n in got["cards"] if n["lead"]]))
        check("    and it is the only one wearing the brighter edge",
              got["cards"][0]["edge"] == LEAD_LINE
              and all(n["edge"] == LINE for n in got["cards"][1:]),
              str([n["edge"] for n in got["cards"]]))
        check("    the free strength above it is untouched",
              got["open"] == ["Hidden Strength #1 of 5"], str(got["open"]))
        check("    and the offer is headed with their subtype",
              got["subtype"].replace("The ", "") in got["head"]
              and "6 chapters" in got["head"],
              "%s / %s" % (got["subtype"], got["head"]))
        # The one card whose copy changes as well as its place. Read off the
        # run the loop already made rather than walking the funnel again for
        # it: eighteen steps is forty seconds of suite.
        if tapped == "Love":
            check("    and says the reading they came for, in those words",
                  "came for" in got["cards"][0]["line"],
                  got["cards"][0]["line"])

    print("\n--- a funnel with no purpose block does none of it ---")
    # Served without the block rather than with an unknown tag: this is the
    # path zodiac v1 and both kitchens take, exercised against the funnel that
    # otherwise would personalise, so nothing but the block is different.
    Handler.strip_purpose = True
    try:
        bare = to_result(page, "zodiac30", "Love")
    finally:
        Handler.strip_purpose = False
    check("it still reaches the result", bare is not None)
    if bare:
        check("  the cards are in config order",
              [n["key"] for n in bare["cards"]] == CANON,
              str([n["key"] for n in bare["cards"]]))
        check("  the offer says the default line",
              bare["sub"] == DEFAULT_SUB, bare["sub"])
        check("  and nothing is marked as led",
              not [n for n in bare["cards"] if n["lead"]],
              str([n["key"] for n in bare["cards"] if n["lead"]]))
        check("  every card at the edge it always had",
              all(n["edge"] == LINE for n in bare["cards"]),
              str([n["edge"] for n in bare["cards"]]))
        check("  and the Love card promises what it promises everyone",
              "came for" not in bare["cards"][0]["line"],
              bare["cards"][0]["line"])

    print("\n--- and zodiac v1 renders the page it always did ---")
    # Asserted here rather than inferred from the block being absent: this is
    # the funnel that is live, and the module it loads is the same file.
    v1 = to_result(page, "zodiac")
    check("it reaches its result", v1 is not None)
    if v1:
        check("  its cards are in config order",
              [n["key"] for n in v1["cards"]] == CANON,
              str([n["key"] for n in v1["cards"]]))
        check("  its offer says the default line", v1["sub"] == DEFAULT_SUB,
              v1["sub"])
        check("  nothing on it is marked as led",
              not [n for n in v1["cards"] if n["lead"]],
              str([n["key"] for n in v1["cards"] if n["lead"]]))
        check("  and every card wears the ordinary edge",
              all(n["edge"] == LINE for n in v1["cards"]),
              str([(n["key"], n["edge"]) for n in v1["cards"]]))
        check("  yet it is named and measured like its twin",
              v1["subtype"].startswith("The ")
              and v1["subtype"].replace("The ", "") in v1["head"],
              "%s / %s" % (v1["subtype"], v1["head"]))

    print("\n--- the echo: their own frames, handed back ---")
    # A fire-leaning walk, which also carries the whole run to the analysing
    # screen. The taps are named here rather than chosen in the browser, so
    # every thumbnail can be checked against a card this session actually
    # tapped rather than against the config's idea of one.
    fire = plan("zodiac30", ("fire",))
    beats, tapped = walk_beats(page, "zodiac30", fire)
    check("every beat was reached", len(beats) == 4, str(len(beats)))
    check("  and every tap landed on the card it was aimed at",
          None not in tapped and len(tapped) == 18, str(tapped))
    ECHOED = {4: 4, 9: 5, 14: 5, 18: 4}
    for row in beats:
        after = row["after"]
        want = tapped[after - ECHOED[after]:after]
        check("  after %-2d hands back the frames it closed on" % after,
              row["echo"] == want, "%s vs %s" % (row["echo"], want))
        check("    one at a time, %d of them" % ECHOED[after],
              row["delays"] == ["%dms" % (i * 420)
                                for i in range(ECHOED[after])],
              str(row["delays"]))
    check("no beat shows a frame from an act it did not close",
          not [r for r in beats
               if set(r["echo"]) - set(tapped[:r["after"]])])
    # The spark is decoration and yields; the rule is progress and does not.
    check("the almost beats keep their rule",
          all(beat(beats, a) and "is-bar" in beat(beats, a)["accent"]
              for a in (9, 18)),
          str([(a, beat(beats, a)["accent"]) for a in (9, 18)]))
    check("  and the confirm beats show no spark beside the row",
          not [a for a in (4, 14)
               if beat(beats, a) and beat(beats, a)["accent"]],
          str([(a, beat(beats, a)["accent"]) for a in (4, 14)]))

    print("\n--- and the beat outlasts its own last frame ---")
    # The first beat closes four steps, so its last thumbnail starts at
    # 1260ms. The screen has to still be there then, and gone by the 3680ms
    # it asked for.
    page.goto("http://127.0.0.1:%d/zodiac30" % PORT)
    page.wait_for_selector("#cards .card", timeout=20000)
    page.wait_for_timeout(300)
    for _ in range(4):
        page.locator("#cards .card").first.click()
        page.wait_for_timeout(HOLD_MS + SETTLE_MS)
    check("the first beat is up", mid_visible(page))
    cells = page.locator("#mid-echo .mid-echo-cell").count()
    check("  with its row on it", cells == 4, str(cells))
    # Four thumbnails, so the last starts at 1260ms and the screen holds
    # 2000 + 4 x 420 = 3680ms.
    page.wait_for_timeout(1400)
    check("  still up once the last thumbnail has arrived",
          mid_visible(page))
    check("  and gone by the beat it asked for", gone(page, 2600))
    # A tap still gets there first, row or no row.
    for _ in range(5):
        page.locator("#cards .card").first.click()
        page.wait_for_timeout(HOLD_MS + SETTLE_MS)
    check("the next beat is up", mid_visible(page))
    page.evaluate("() => document.getElementById('screen-interstitial')"
                  ".click()")
    check("  and a tap skips it, thumbnails and all", gone(page, 900))

    print("\n--- the analysing screen shows the whole run ---")
    grid = walk_beats(page, "zodiac30", fire)[1]
    seen = 0
    for _ in range(60):
        seen = max(seen, page.locator("#analyzing-grid .analyzing-cell")
                   .count())
        if page.locator("#result-module").count() \
                and not page.locator("#result-module").is_hidden():
            break
        page.wait_for_timeout(100)
    check("it draws every choice of the run", seen == 18, str(seen))
    check("  which is one cell per tap", seen == len(grid), str(len(grid)))
    check("  and the result waited for it",
          page.locator("#result-module").count() == 1)

    print("\n--- the line says what the run said ---")
    # Their sign and their reason, in one sentence, four steps in. {sign} is
    # the new token: it resolves through the slot the funnel already declares
    # for the result page, and it is the reader's own label rather than a
    # lowercased fragment because it opens the sentence.
    love = plan("zodiac30", ("fire",),
                {"seeking": "sk3a", "sign": "sign_leo"})
    said = beat(walk_beats(page, "zodiac30", love, stop_after=4)[0], 4)
    check("a Leo who came for love is told so after four",
          said and said["line"] == "A Leo looking for love.",
          said and said["line"])
    check("  with the sub written for it",
          said and said["sub"] == "That narrows it fast.",
          said and said["sub"])
    nine = beat(beats, 9)
    check("a fire run is told fire is winning after nine",
          nine and nine["line"] == "Fire keeps winning.",
          nine and nine["line"])
    check("  and what that would mean if it holds",
          nine and nine["sub"] == "If it holds, your reading changes.",
          nine and nine["sub"])
    # The step-keyed block: one question, answered back in its own words,
    # rather than a running total.
    # One card in the browser, because what is being proved here is that a
    # step-keyed block resolves to the card that was tapped at all. That every
    # one of the four has a line, and that the four are the only cards on that
    # step, is a property of the config and is checked there.
    heart = plan("zodiac30", ("fire",), {"decision": "dc14a"})
    got = beat(walk_beats(page, "zodiac30", heart, stop_after=14)[0], 14)
    check("  a heart-first run is told so after fourteen",
          got and got["line"] == "You choose with your heart first."
          and got["sub"] == "Few admit that.",
          str(got and (got["line"], got["sub"])))

    print("\n--- and says nothing it cannot stand behind ---")
    # A run with no element ahead of the others by step nine. `leaderOf` would
    # break that tie by array order and name one; `soleLeaderOf` does not, and
    # the base line is what a run that has not said it yet gets.
    tie_ids, tallies = element_tie("zodiac30")
    check("a level run can be built out of this funnel's own cards",
          tie_ids is not None,
          str(tallies))
    if tie_ids:
        tied = beat(walk_beats(page, "zodiac30", tie_ids,
                               stop_after=9)[0], 9)
        check("  and it gets the line the entry was written with",
              tied and tied["line"] == "Profile 50% calibrated.",
              tied and tied["line"])
        check("  its row and rule unaffected by that",
              tied and len(tied["echo"]) == 5 and "is-bar" in tied["accent"],
              str(tied and (tied["echo"], tied["accent"])))
    # The second way a personalised line is refused: its own token cannot be
    # answered. The engine falls back to the entry it was written to replace
    # rather than printing a hole or dropping the screen.
    Handler.strip_sign_slot = True
    try:
        unsigned = beat(walk_beats(page, "zodiac30", love,
                                   stop_after=4)[0], 4)
    finally:
        Handler.strip_sign_slot = False
    check("a run whose {sign} cannot be answered falls back to the base line",
          unsigned and unsigned["line"] == "Two personal signals in."
          and unsigned["sub"] == "Your profile is narrowing.",
          str(unsigned and (unsigned["line"], unsigned["sub"])))
    check("  with no brace left showing on it",
          unsigned and "{" not in unsigned["line"] + unsigned["sub"],
          str(unsigned))
    check("  and the screen still drawn rather than skipped",
          unsigned and len(unsigned["echo"]) == 4, str(unsigned))
    # The third way: a config that never offered an alternative, which is
    # every funnel but this one.
    Handler.strip_personal = True
    try:
        bare = walk_beats(page, "zodiac30", fire, stop_after=9)[0]
    finally:
        Handler.strip_personal = False
    check("a config with no personal block renders its own lines",
          [b["line"] for b in bare] == ["Two personal signals in.",
                                        "Profile 50% calibrated."],
          str([b["line"] for b in bare]))
    check("  and still hands the frames back",
          [len(b["echo"]) for b in bare] == [4, 5],
          str([b["echo"] for b in bare]))

    print("\n--- the summer sale, on both sides of the last second ---")
    # The offer's own instant: 23:59:59 in UTC-12 is 11:59:59Z on the 1st, and
    # that second is already outside it. One page a second before, one on it.
    DURING = "2026-09-01T11:59:58Z"
    AFTER = "2026-09-01T11:59:59Z"
    sale = json.load(open(os.path.join(ROOT, "funnels/zodiac30.json"),
                          encoding="utf-8"))["sale"]
    live = offer_at("zodiac30", DURING)
    check("the card is reached with the sale running", live is not None)
    if live:
        check("  two dollars is the hero", live["now"] == "$2", live["now"])
        check("  three is beside it", live["was"] == "$3", live["was"])
        check("    and it is the price this funnel actually charges",
              live["was"] == "$%d" % (sale["regular_price_cents"] // 100)
              == "$3", live["was"])
        check("    struck through, not merely small",
              live["strike"] == "line-through", live["strike"])
        check("    and said, for a reader who cannot see a line",
              live["label"] == "Regular price $3", live["label"])
        check("  one line names the offer and the day it stops",
              live["sale"] == "Summer Sale · ends Aug 31", live["sale"])
        check("  the button names the two dollars it will take",
              live["button"] == "Open my full profile — $2", live["button"])
        check("  the badges are the ones that were always there",
              live["badges"] == ["One-time", "No subscription, ever"],
              str(live["badges"]))
        check("  the anchor still names the session it undercuts",
              live["anchor"] == "instead of a $75 private session",
              live["anchor"])
        check("  the purpose line is untouched",
              live["sub"] == "Your compatibility read is inside.", live["sub"])
        check("  and the note beside the price is unchanged",
              live["note"] == "one-time", live["note"])
        check("  nothing on the card counts down or runs out",
              not re.search(r"hurry|spots|seats|in stock|selling fast|"
                            r"almost gone|act now|countdown|expires in|"
                            r"\d+\s*(?:left|remaining)",
                            live["residue"]), live["residue"][:120])

    over = offer_at("zodiac30", AFTER)
    check("the card is reached once the sale is over", over is not None)
    if over:
        check("  three dollars is the hero again", over["now"] == "$3",
              over["now"])
        check("  with nothing struck through beside it",
              over["was"] is None, over["was"])
        check("  and no line about an offer", over["sale"] is None,
              over["sale"])
        check("  the button names three", over["button"]
              == "Open my full profile — $3", over["button"])
        check("  not a word of the sale is left on the card",
              "summer sale" not in over["residue"]
              and "$2" not in over["residue"], over["residue"][:120])
        check("  and everything else is exactly what it was",
              [over["badges"], over["anchor"], over["sub"], over["note"]]
              == [["One-time", "No subscription, ever"],
                  "instead of a $75 private session",
                  "Your compatibility read is inside.", "one-time"],
              str([over["badges"], over["anchor"], over["sub"],
                   over["note"]]))
    # The funnels that are not on offer, on the same build and the same clock.
    for slug, want in (("zodiac", "$3"), ("kitchen", "$3")):
        other = offer_at(slug, DURING)
        if slug == "kitchen":
            # kitchen draws no module; its price lives on its own paywall.
            check("  kitchen is priced by its own config, sale or no sale",
                  other is None or other.get("was") is None)
            continue
        check("  %s is reached" % slug, other is not None)
        if other:
            check("    priced at %s while the other funnel is on offer" % want,
                  other["now"] == want, other["now"])
            check("    with nothing struck through",
                  other["was"] is None and other["sale"] is None,
                  "%s / %s" % (other["was"], other["sale"]))
            check("    and its button naming the same number",
                  other["button"] == "Open my full profile — %s" % want,
                  other["button"])

    print("\n--- kitchen is untouched ---")
    start(page, "kitchen")
    check("an interstitial is reached", to_interstitial(page, limit=8))
    check("  it draws the Continue button",
          page.locator("#mid-cta").is_visible())
    check("  with no mode class and no accent",
          "is-auto" not in klass(page, "#screen-interstitial")
          and page.locator("#mid-accent").count() == 0)
    kcfg = json.load(open(os.path.join(ROOT, "funnels/kitchen.json"),
                          encoding="utf-8"))
    # Matched as a shape, not as a string: kitchen's lines are templates and
    # what reaches the screen has had its tokens filled by the same machinery
    # it always used. The claim is that the sentence is still one of its own,
    # word for word around the numbers.
    shown = page.text_content("#mid-line") or ""
    shapes = [re.escape(e["line"]).replace(r"\{", "{").replace(r"\}", "}")
              for e in kcfg["interstitials"]]
    shapes = [re.sub(r"\{\w+\}", ".+", shape) for shape in shapes]
    check("  its line is one of its own, filled the way it always was",
          any(re.fullmatch(shape, shown) for shape in shapes),
          "%r matches none of %s" % (shown, [e["line"]
                                             for e in kcfg["interstitials"]]))
    check("  and it hands back no frames either",
          page.locator("#mid-echo").count() == 0
          or not page.locator("#mid-echo").is_visible())
    page.wait_for_timeout(2500)
    check("  and it is still there without a press", mid_visible(page))
    # The analysing grid is this funnel's too. Neither of the others asks for
    # one, and the node is built only where a config does.
    check("  and its analysing screen draws no grid",
          page.locator("#analyzing-grid").count() == 0)


def main():
    socketserver.TCPServer.allow_reuse_address = True
    httpd = socketserver.TCPServer(("127.0.0.1", PORT), Handler)
    threading.Thread(target=httpd.serve_forever, daemon=True).start()
    try:
        with sync_playwright() as pw:
            browser = pw.chromium.launch(executable_path=CHROME)
            BROWSER[0] = browser
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
