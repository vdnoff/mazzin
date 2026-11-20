#!/usr/bin/env python3
"""The /ai-navigator walk, in a real browser: four warm-ups, eight money traps.

What is walked, at 390x844 and again at 360x640:

  - the intro, then four warm-ups, one screen between, eight traps;
  - on every step the answers are all on screen without scrolling, nothing
    readable is under 15px but an uppercase kicker or the legal small print,
    neighbouring blocks are 12 to 28px apart, every card that names an icon
    draws it, and no card holds an image;
  - a trap is numbered, named and lettered A to D by where its answers
    landed; a tap marks the right answer and, where the tap was wrong, the
    tapped one, folds the question away and puts a panel under the answers
    that says which it was and why, all of it on screen without scrolling;
  - the score strip and its count follow the run, and the streak pill shows
    from the second dodge in a row and is gone after a miss;
  - the panel moves on by itself after the configured delay, and at once on
    a tap anywhere;
  - exactly one swipe event a step, fired at the tap, and one interstitial;
  - the free result is the blocks in order, with engine.js's pay button
    inside the offer card.

Nothing leaves the machine: every request off 127.0.0.1 is aborted.

    python3 tests/test_ainavigator_walk.py
"""
import os
import sys
import threading
import time

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, REPO)
sys.path.insert(0, os.path.join(REPO, "tests"))

import test_ainavigator_rsoc as walk                       # noqa: E402

from playwright.sync_api import sync_playwright            # noqa: E402

PORT = 8867
BASE = "http://127.0.0.1:%d" % PORT
CFG = walk.CFG
STEPS = CFG["swipe"]["steps"]
FEEDBACK = CFG["swipe"]["feedback"]
STRIP = CFG["swipe"]["score_strip"]
DELAY = CFG["swipe"]["feedback_ms"]
TRAPS = [s for s in STEPS if "why" in s]

# Which traps this walk dodges: three in a row, a miss, one, a miss, two.
DODGE = [True, True, True, False, True, False, True, True]

fails = []
checks = [0]


def check(label, ok, detail=""):
    checks[0] += 1
    if not ok:
        fails.append("%s %s" % (label, detail))
    print("  %-64s %s%s" % (label, "ok" if ok else "FAIL",
                            ("  " + str(detail)[:300]) if not ok else ""))


SCREEN = """() => {
  const box = n => { const b = n.getBoundingClientRect();
                     return [Math.round(b.top), Math.round(b.bottom),
                             Math.round(b.left), Math.round(b.right)]; };
  const shown = n => !!(n && n.offsetParent !== null);
  const text = s => { const n = document.querySelector(s);
                      return shown(n) ? n.textContent : ''; };
  const screen = document.querySelector('#screen-swipe');
  const cards = [...document.querySelectorAll('#cards .card')];
  const panel = document.querySelector('#step-feedback');
  const strip = document.querySelector('#step-strip');
  const head = document.querySelector('#step-head');
  // Readable text under 15px that is neither an uppercase kicker nor the
  // legal small print.
  const small = [];
  for (const n of screen.querySelectorAll('*')) {
    if (!shown(n)) continue;
    const own = [...n.childNodes].some(c => c.nodeType === 3
      && c.textContent.trim());
    if (!own) continue;
    const cs = getComputedStyle(n);
    const px = parseFloat(cs.fontSize);
    const kicker = cs.textTransform === 'uppercase' && px >= 13;
    const legal = n.classList.contains('intro-foot-note') && px >= 14;
    if (px < 15 && !kicker && !legal) small.push([n.className, px]);
  }
  // The blocks of the step, top to bottom, and the gap between each pair.
  const blocks = [document.querySelector('.swipe-top .pips'), strip, head,
    document.querySelector('#step-kicker'),
    document.querySelector('#swipe-caption'),
    document.querySelector('#step-sub'), document.querySelector('#cards'),
    panel].filter(shown).filter(n => n.getBoundingClientRect().height > 0)
    .sort((a, b) => a.getBoundingClientRect().top
                    - b.getBoundingClientRect().top);
  const gaps = [];
  for (let i = 0; i + 1 < blocks.length; i++) {
    gaps.push([blocks[i].id || blocks[i].className.split(' ')[0],
               blocks[i + 1].id || blocks[i + 1].className.split(' ')[0],
               Math.round(blocks[i + 1].getBoundingClientRect().top
                          - blocks[i].getBoundingClientRect().bottom)]);
  }
  for (let i = 0; i + 1 < cards.length; i++) {
    const a = cards[i].getBoundingClientRect();
    const b = cards[i + 1].getBoundingClientRect();
    if (b.top >= a.bottom - 0.5) {
      gaps.push(['card', 'card', Math.round(b.top - a.bottom)]);
    }
  }
  const pinned = [document.querySelector('#step-chip'),
                  document.querySelector('#step-foot'),
                  document.querySelector('#step-wait')].filter(shown);
  const above = panel && shown(panel) ? panel
    : document.querySelector('#cards');
  return {
    caption: text('#swipe-caption'), chip: text('#step-chip'),
    sub: text('#step-sub'), foot: text('#step-foot'),
    label: text('#progress-label'),
    captionSize: shown(document.querySelector('#swipe-caption'))
      ? getComputedStyle(document.querySelector('#swipe-caption')).fontSize
      : '',
    head: shown(head) ? {
      kicker: (head.querySelector('.step-head-kicker') || {}).textContent,
      title: head.querySelector('.step-head-title').textContent,
      icon: (head.querySelector('svg') || { getAttribute: () => '' })
        .getAttribute('data-icon'),
      square: Math.round(head.querySelector('.step-head-icon')
        .getBoundingClientRect().width) } : null,
    strip: shown(strip) ? {
      segs: [...strip.querySelectorAll('.step-strip-seg')].map(s =>
        s.classList.contains('is-hit') ? 'hit'
        : s.classList.contains('is-miss') ? 'miss'
        : s.classList.contains('is-current') ? 'current' : 'todo'),
      colors: [...strip.querySelectorAll('.step-strip-seg')].map(s =>
        getComputedStyle(s).backgroundColor),
      count: strip.querySelector('.step-strip-count').textContent,
      aria: strip.getAttribute('aria-label') } : null,
    pips: shown(document.querySelector('.swipe-top .pips')),
    cards: cards.map(c => ({
      text: (c.querySelector('.card-text') || {}).textContent || '',
      sub: (c.querySelector('.card-sub') || {}).textContent || '',
      badge: (c.querySelector('.card-badge') || {}).textContent || '',
      letter: (c.querySelector('.card-letter') || {}).textContent || '',
      mark: (c.querySelector('.card-letter svg') || { getAttribute: () => '' })
        .getAttribute('data-icon') || '',
      icon: (c.querySelector('.card-icon svg') || { getAttribute: () => '' })
        .getAttribute('data-icon') || '',
      aria: c.getAttribute('aria-label') || '',
      flags: c.querySelectorAll('.card-flag').length,
      box: box(c), cls: c.className,
      border: getComputedStyle(c).borderTopColor,
      fill: getComputedStyle(c).backgroundColor,
      ink: getComputedStyle(c.querySelector('.card-text')).color,
      size: getComputedStyle(c.querySelector('.card-text')).fontSize,
      imgs: c.querySelectorAll('img').length })),
    panel: shown(panel) ? {
      box: box(panel), cls: panel.className,
      head: panel.querySelector('.step-feedback-head').childNodes[0]
        .textContent,
      streak: (panel.querySelector('.step-feedback-streak') || {})
        .textContent || '',
      why: panel.querySelector('.step-feedback-why').textContent,
      buttons: panel.querySelectorAll('button').length,
      fill: getComputedStyle(panel).backgroundColor,
      ink: getComputedStyle(
        panel.querySelector('.step-feedback-why')).color } : null,
    wait: text('.step-wait-line'),
    waitBar: shown(document.querySelector('.step-wait-bar')),
    small: small, gaps: gaps,
    pinnedGap: pinned.map(n => Math.round(n.getBoundingClientRect().top
                                          - above.getBoundingClientRect()
                                            .bottom)),
    pinnedBottom: pinned.map(n => Math.round(
      n.getBoundingClientRect().bottom)),
    vh: innerHeight, vw: innerWidth,
    sh: document.documentElement.scrollHeight,
    sw: document.documentElement.scrollWidth, y: scrollY
  };
}"""

ACCENT = "rgb(200, 245, 59)"
MISS = "rgb(255, 154, 122)"
DARK = "rgb(11, 15, 20)"
MUTED = "rgb(154, 167, 180)"


def swipes():
    return [e for e in walk.events if e.get("event") == "swipe"]


def wait_step(page, question, timeout=6000):
    page.wait_for_function(
        """q => { const c = document.querySelector('#swipe-caption');
                  const b = document.querySelector('#cards');
                  const s = document.querySelector('#screen-swipe');
                  return s.classList.contains('is-active') && c
                    && c.textContent === q && b
                    && !b.classList.contains('is-leaving')
                    && b.querySelectorAll('.card').length
                    && !b.querySelector('.card.is-chosen'); }""",
        arg=question, timeout=timeout)
    page.wait_for_timeout(260)


def card(page, label):
    return page.locator("#cards .card").filter(
        has=page.locator(".card-text", has_text=label)).first


def run(browser, width, height, reduced=False):
    tag = "%dx%d%s" % (width, height, " reduced-motion" if reduced else "")
    print("\n--- %s ---" % tag)
    del walk.events[:]
    ctx = browser.new_context(
        viewport={"width": width, "height": height}, is_mobile=True,
        has_touch=True, reduced_motion="reduce" if reduced else "no-preference")
    ctx.route(lambda url: not url.startswith(BASE), lambda r: r.abort())
    page = ctx.new_page()
    errors = []
    page.on("pageerror", lambda e: errors.append(str(e)))
    page.goto(BASE + "/ai-navigator")
    page.wait_for_selector(".intro-cta")
    page.wait_for_timeout(500)
    small_screen = height < 700

    intro = page.evaluate("""() => {
      const q = s => (document.querySelector(s) || {}).textContent || '';
      const cta = document.querySelector('.intro-cta').getBoundingClientRect();
      const brand = document.querySelector('.swipe-brand');
      const tiles = [...document.querySelectorAll('.intro-tile')];
      const small = [];
      for (const n of document.querySelectorAll('#intro *')) {
        if (n.offsetParent === null) continue;
        const own = [...n.childNodes].some(c => c.nodeType === 3
          && c.textContent.trim());
        if (!own) continue;
        const cs = getComputedStyle(n); const px = parseFloat(cs.fontSize);
        if (px < 15 && !(n.classList.contains('intro-kicker') && px >= 13)
            && !(n.classList.contains('intro-foot-note') && px >= 14)) {
          small.push([n.className, px]);
        }
      }
      return { kicker: q('.intro-kicker'), head: q('.intro-head'),
               sub: q('.intro-sub'), cta: q('.intro-cta'),
               ctaIcon: (document.querySelector('.intro-cta svg')
                 || { getAttribute: () => '' }).getAttribute('data-icon'),
               ctaSize: getComputedStyle(document.querySelector('.intro-cta'))
                 .fontSize,
               tiles: tiles.map(t => [
                 t.querySelector('.intro-tile-label').textContent,
                 (t.querySelector('svg') || { getAttribute: () => null })
                   .getAttribute('data-icon'),
                 getComputedStyle(t).borderTopStyle]),
               cols: new Set(tiles.map(t => Math.round(
                 t.getBoundingClientRect().left))).size,
               chips: document.querySelectorAll('.intro-chip').length,
               foot: q('.intro-foot'), note: q('.intro-foot-note'),
               ctaBox: [Math.round(cta.top), Math.round(cta.bottom),
                        Math.round(cta.height)],
               ground: getComputedStyle(document.body).backgroundColor,
               font: getComputedStyle(document.querySelector('.intro-head'))
                 .fontFamily,
               brand: getComputedStyle(brand, '::before').content
                 + getComputedStyle(brand, '::after').content,
               brandFont: getComputedStyle(brand).fontFamily,
               pad: Math.round(document.querySelector('.intro')
                 .getBoundingClientRect().left),
               imgs: document.querySelectorAll('#screen-swipe img').length,
               small: small, vh: innerHeight,
               sh: document.documentElement.scrollHeight,
               sw: document.documentElement.scrollWidth,
               vw: innerWidth }; }""")
    I = CFG["intro"]
    check("the intro says what the config says",
          intro["kicker"].strip("◆ ") == I["kicker"]
          and intro["head"] == I["headline"] and intro["sub"] == I["sub"]
          and intro["cta"] == I["cta"] and intro["foot"] == I["foot"]
          and intro["note"] == I["foot_note"], intro)
    check("  six icon tiles in three columns, the last one dashed",
          [t[0] for t in intro["tiles"]] == [t["label"] for t in I["tiles"]]
          and [t[1] for t in intro["tiles"]]
          == [t.get("icon") for t in I["tiles"]]
          and intro["tiles"][-1][2] == "dashed" and intro["cols"] == 3
          and intro["chips"] == 0, intro["tiles"])
    check("  dark ground, Space Grotesk headline, Fraunces wordmark",
          intro["ground"] == DARK and "Space Grotesk" in intro["font"]
          and intro["brand"] == '"mazzin""."'
          and "Fraunces" in intro["brandFont"],
          [intro["ground"], intro["font"], intro["brand"]])
    check("  the button: an arrow, 20px, on screen, 24px page padding",
          intro["ctaIcon"] == "arrow" and intro["ctaSize"] == "20px"
          and intro["ctaBox"][1] <= intro["vh"] and intro["ctaBox"][2] >= 56
          and intro["pad"] == 24 and intro["sw"] <= intro["vw"],
          [intro["ctaIcon"], intro["ctaSize"], intro["ctaBox"]])
    check("  nothing readable under 15px", not intro["small"], intro["small"])
    page.locator(".intro-cta").click()

    mids = 0
    history = []
    for index, step in enumerate(STEPS):
        number = index + 1
        wait_step(page, step["question"])
        before = page.evaluate(SCREEN)
        cards = step["pairs"][0]["images"]
        trap = "why" in step
        by_label = dict((c["label"], c) for c in cards)
        ok_fit = (before["sh"] <= before["vh"] and before["sw"] <= before["vw"]
                  and len(before["cards"]) == len(cards)
                  and all(0 <= c["box"][0] and c["box"][1] <= before["vh"]
                          and c["box"][2] >= 0 and c["box"][3] <= before["vw"]
                          for c in before["cards"])
                  and all(b <= before["vh"] for b in before["pinnedBottom"]))
        check("%d %s: every answer on screen, no scrolling"
              % (number, step["id"]), ok_fit,
              [before["sh"], before["vh"],
               [c["box"] for c in before["cards"]][-1:],
               before["pinnedBottom"]])
        check("  label, chip, sub and foot are the config's",
              before["chip"] == step.get("chip", "")
              and before["label"] == step.get(
                  "progress_label", "%d of %d" % (number, len(STEPS)))
              and before["sub"] == step.get("sub", "")
              and before["foot"] == step.get("foot", ""),
              [before["chip"], before["label"], before["foot"]])
        check("  nothing readable under 15px", not before["small"],
              before["small"])
        tight = [g for g in before["gaps"] if not 12 <= g[2] <= 28]
        check("  neighbouring blocks are 12 to 28px apart",
              not tight and all(g >= 12 for g in before["pinnedGap"]),
              [tight, before["pinnedGap"]])
        check("  every card that names an icon draws it; none holds an image",
              [c["icon"] for c in before["cards"]]
              == [by_label[c["text"]].get("icon", "")
                  for c in before["cards"]]
              and not any(c["imgs"] for c in before["cards"]))
        if not trap:
            check("  title, line and badge on each card, as written",
                  [(c["text"], c["sub"], c["badge"]) for c in before["cards"]]
                  == [(c["label"], c.get("sub", ""), c.get("badge", ""))
                      for c in cards]
                  and before["head"] is None and before["strip"] is None
                  and before["pips"])
            check("  the question at headline size, answers 15px or more",
                  before["captionSize"] == ("28px" if small_screen
                                            else "33px")
                  and all(float(c["size"][:-2]) >= 15
                          for c in before["cards"]),
                  [before["captionSize"], before["cards"][0]["size"]])
        else:
            n = len(history) + 1
            check("  MONEY TRAP #%d, its title and icon in a square" % n,
                  before["head"] and before["head"]["kicker"]
                  == step["title_kicker"]
                  and before["head"]["title"] == step["title"]
                  and before["head"]["icon"] == step["icon"]
                  and before["head"]["square"] == (52 if small_screen else 68),
                  before["head"])
            check("  four stacked rows, lettered A to D as they landed",
                  sorted(c["text"] for c in before["cards"])
                  == sorted(c["label"] for c in cards)
                  and [c["letter"] for c in before["cards"]]
                  == ["A", "B", "C", "D"]
                  and [c["box"][0] for c in before["cards"]]
                  == sorted(c["box"][0] for c in before["cards"])
                  and all(float(c["size"][:-2]) >= (16 if small_screen
                                                    else 18)
                          for c in before["cards"]),
                  [c["letter"] for c in before["cards"]])
            want = (["hit" if h else "miss" for h in history] + ["current"]
                    + ["todo"] * (7 - len(history)))
            check("  the strip: eight segments, this one outlined, the count",
                  before["strip"] and before["strip"]["segs"] == want
                  and before["strip"]["count"]
                  == STRIP["label"].replace("{n}", str(sum(history)))
                  and not before["pips"], before["strip"])

        scenario = number - 4
        right = cards[0]["label"]
        if trap:
            good = DODGE[scenario - 1]
            pick = right if good else cards[2]["label"]
        else:
            pick = cards[1]["label"]
        count = len(swipes())
        tapped = time.time()
        card(page, pick).click()
        page.wait_for_timeout(260)
        check("  one swipe event, at the tap",
              len(swipes()) == count + 1
              and swipes()[-1].get("step") == number
              and swipes()[-1]["extra"]["chosen"]
              == next(c["id"] for c in cards if c["label"] == pick)
              and sorted(swipes()[-1]["extra"]) == ["chosen", "pair", "shown"],
              swipes()[-1:])

        if not trap:
            after = page.evaluate(SCREEN)
            chosen = [c for c in after["cards"] if "is-chosen" in c["cls"]]
            check("  the tapped card is selected; no feedback on a warm-up",
                  after["panel"] is None and len(chosen) == 1
                  and chosen[0]["text"] == pick
                  and chosen[0]["border"] == ACCENT
                  and not after["wait"], [after["panel"], chosen])
            if number == 4:
                page.wait_for_selector("#screen-interstitial.is-active",
                                       timeout=5000)
                page.wait_for_timeout(400)
                mid = page.evaluate("""() => {
                  const q = s => (document.querySelector(s) || {})
                    .textContent || '';
                  const cta = document.querySelector('#mid-cta')
                    .getBoundingClientRect();
                  const size = s => parseFloat(getComputedStyle(
                    document.querySelector(s)).fontSize);
                  return { kicker: q('#mid-kicker'), line: q('#mid-line'),
                           sub: q('#mid-sub'), cta: q('#mid-cta'),
                           from: q('.mid-cut-from'), to: q('.mid-cut-to'),
                           strike: getComputedStyle(document.querySelector(
                             '.mid-cut-from')).textDecorationLine,
                           toColor: getComputedStyle(document.querySelector(
                             '.mid-cut-to')).color,
                           rows: [...document.querySelectorAll('.mid-lock')]
                             .map(r => [r.querySelector('.mid-lock-name')
                                          .textContent,
                                        r.querySelectorAll('svg').length,
                                        r.querySelector('.mid-lock-bar')
                                          .textContent]),
                           sizes: [size('#mid-sub'), size('.mid-lock'),
                                   size('#mid-cta')],
                           ctaBottom: Math.round(cta.bottom),
                           vh: innerHeight,
                           sh: document.documentElement.scrollHeight }; }""")
                M = CFG["interstitials"][0]
                check("the one screen between: 11 struck, a huge 3",
                      mid["kicker"] == M["kicker"] and mid["from"] == "11"
                      and mid["to"] == "3" and mid["strike"] == "line-through"
                      and mid["toColor"] == ACCENT and mid["line"] == M["line"]
                      and mid["sub"] == M["sub"] and mid["cta"] == M["cta"],
                      mid)
                check("  three locked rows, each a lock, a name, an empty bar",
                      mid["rows"] == [[r, 1, ""] for r in M["cut"]["rows"]])
                check("  all of it on screen, nothing under 15px",
                      mid["ctaBottom"] <= mid["vh"] and mid["sh"] <= mid["vh"]
                      and min(mid["sizes"]) >= 15,
                      [mid["ctaBottom"], mid["vh"], mid["sizes"]])
                page.wait_for_timeout(4300)
                check("  it waits for its button",
                      page.evaluate("() => document.querySelector("
                                    "'#screen-interstitial').classList"
                                    ".contains('is-active')"))
                mids += 1
                page.locator("#mid-cta").click()
            continue

        history.append(good)
        streak = 0
        for h in reversed(history):
            if not h:
                break
            streak += 1
        after = page.evaluate(SCREEN)
        panel = after["panel"]
        by_text = dict((c["text"], c) for c in after["cards"])
        hit = by_text[right]
        check("  the right answer: accent border, a check for its letter",
              "is-right" in hit["cls"] and hit["border"] == ACCENT
              and hit["fill"] == "rgb(27, 36, 16)" and hit["mark"] == "check"
              and hit["letter"] == ""
              and hit["aria"].endswith(". " + FEEDBACK["right"])
              and hit["flags"] == 0, hit)
        others = [c for c in after["cards"] if c["text"] not in (right, pick)]
        if good:
            check("  and nothing else is marked; the other rows are dimmed",
                  not any("is-wrong" in c["cls"] or c["mark"]
                          for c in after["cards"] if c["text"] != right)
                  and all(c["ink"] == MUTED for c in others)
                  and len(others) == 3, [c["ink"] for c in others])
        else:
            bad = by_text[pick]
            check("  the wrong pick: miss border, an x for its letter",
                  "is-wrong" in bad["cls"] and bad["border"] == MISS
                  and bad["fill"] == "rgb(42, 23, 18)" and bad["mark"] == "x"
                  and bad["aria"].endswith(". " + FEEDBACK["yours"])
                  and bad["flags"] == 0
                  and all(c["ink"] == MUTED for c in others)
                  and len(others) == 2, bad)
        check("  the panel says which it was, and the trap's why",
              panel and panel["head"] == (FEEDBACK["good"] if good
                                          else FEEDBACK["bad"])
              and panel["why"] == step["why"] and panel["buttons"] == 0
              and panel["fill"] == (ACCENT if good else MISS)
              and panel["ink"] == DARK
              and ("is-good" if good else "is-bad") in panel["cls"], panel)
        check("  the streak pill: from the second dodge in a row, not before",
              panel and panel["streak"] == (
                  FEEDBACK["streak"].replace("{n}", str(streak))
                  if good and streak >= 2 else ""),
              [streak, panel and panel["streak"]])
        want = (["hit" if h else "miss" for h in history]
                + ["todo"] * (8 - len(history)))
        check("  the strip takes this trap's colour and the count moves",
              after["strip"]["segs"] == want
              and after["strip"]["colors"][len(history) - 1]
              == (ACCENT if good else MISS)
              and after["strip"]["count"]
              == STRIP["label"].replace("{n}", str(sum(history)))
              and after["strip"]["aria"]
              == "%d dodged, %d walked into, %d still to come" % (
                  sum(history), len(history) - sum(history),
                  8 - len(history)), after["strip"])
        check("  the question folds away; answers, panel and bar on screen",
              after["caption"] == "" and panel
              and panel["box"][1] <= after["vh"]
              and after["sh"] <= after["vh"] and after["y"] == 0
              and all(c["box"][1] <= panel["box"][0] for c in after["cards"])
              and all(b <= after["vh"] for b in after["pinnedBottom"])
              and after["waitBar"]
              and after["wait"] == (FEEDBACK["wait_last"] if scenario == 8
                                    else FEEDBACK["wait"]),
              [panel and panel["box"], after["vh"], after["sh"],
               after["pinnedBottom"], after["wait"]])
        tight = [g for g in after["gaps"] if not 12 <= g[2] <= 28]
        check("  12 to 28px between blocks, nothing readable under 15px",
              not tight and all(g >= 12 for g in after["pinnedGap"])
              and not after["small"],
              [tight, after["pinnedGap"], after["small"]])

        gone = ("() => !document.querySelector('#step-feedback')")
        if scenario == 1:
            # Left alone: it moves on by itself after the delay.
            page.wait_for_timeout(max(0, int(DELAY - 500
                                             - (time.time() - tapped) * 1000)))
            still = page.evaluate("() => !!document.querySelector("
                                  "'#step-feedback')")
            page.wait_for_function(gone, timeout=1500)
            took = (time.time() - tapped) * 1000
            check("  left alone, it moves on by itself after %dms" % DELAY,
                  still and DELAY - 150 <= took <= DELAY + 900, round(took))
        elif scenario == 2:
            page.wait_for_timeout(450)
            page.locator("#step-head").click()        # anywhere at all
            page.wait_for_function(gone, timeout=600)
            took = (time.time() - tapped) * 1000
            check("  a tap anywhere moves on at once", took < DELAY - 600,
                  round(took))
        else:
            page.wait_for_timeout(420)
            page.locator("#step-wait").click()
            page.wait_for_function(gone, timeout=600)
            took = (time.time() - tapped) * 1000
            check("  a tap on the bar moves on at once", took < DELAY - 600,
                  round(took))
        check("  and the step is still counted once",
              len(swipes()) == count + 1)

    page.wait_for_selector("#result-module .ai-offer", timeout=30000)
    page.wait_for_timeout(900)
    names = [e.get("event") for e in walk.events]
    check("twelve swipes, steps 1 to 12, one interstitial",
          [e.get("step") for e in swipes()] == list(range(1, 13))
          and names.count("interstitial") == 1 and mids == 1, names)
    result = page.evaluate("""() => {
      const root = document.querySelector('#result-module');
      const pay = document.querySelector('#pay-button');
      const offer = root.querySelector('.ai-offer');
      const cs = getComputedStyle(offer);
      const name = root.querySelector('.ai-type-name');
      const small = [];
      for (const n of root.querySelectorAll('*')) {
        if (n.offsetParent === null) continue;
        const own = [...n.childNodes].some(c => c.nodeType === 3
          && c.textContent.trim());
        if (!own) continue;
        const st = getComputedStyle(n); const px = parseFloat(st.fontSize);
        const kicker = st.textTransform === 'uppercase' && px >= 13;
        const legal = n.closest('.ai-foot, .ai-offer-under, .ai-rsoc-note, .legal-links')
          && px >= 14;
        if (px < 15 && !kicker && !legal) {
          small.push([n.tagName, n.className, n.textContent.slice(0, 30),
                      n.parentNode.className, px]);
        }
      }
      const size = s => getComputedStyle(root.querySelector(s)).fontSize;
      return { order: [...root.children].map(c => c.className.split(' ')[0]),
               payIn: offer.contains(pay), payText: pay.textContent,
               payH: Math.round(pay.getBoundingClientRect().height),
               paySize: getComputedStyle(pay).fontSize,
               border: cs.borderTopWidth + ' ' + cs.borderTopColor,
               fill: cs.backgroundColor,
               nameSize: getComputedStyle(name).fontSize,
               ring: root.querySelector('.ai-ring-n').textContent,
               predict: root.querySelector('.ai-predict').textContent,
               word: (root.querySelector('.ai-calibration') || {})
                 .textContent || '',
               type: name.textContent,
               body: [size('.ai-type-essence'), size('.ai-predict'),
                      size('.ai-offer-line'), size('.ai-check')],
               rows: [...root.querySelectorAll('.ai-check')]
                 .map(r => r.textContent),
               small: small,
               zones: root.querySelectorAll('.ai-zone, .ai-mark, .ai-level')
                 .length,
               sw: document.documentElement.scrollWidth, vw: innerWidth }; }""")
    check("the free result: hero, score card, offer card, footer",
          result["order"] == ["ai-profile", "ai-scorecard", "ai-offer",
                              "ai-foot"], result["order"])
    check("  six dodged of eight: the ring, the prediction line, the type",
          result["nameSize"] == "46px" and result["ring"] == "6/8"
          and result["predict"] == "You predicted 3–4. You scored 6."
          and result["word"] == CFG["result_copy"]["calibration"]["under"]
          and result["type"] == "The Mechanic",
          [result["ring"], result["predict"], result["type"]])
    check("  body and lists at 17px, nothing readable under 15px",
          result["body"] == ["17px"] * 4 and not result["small"],
          [result["body"], result["small"]])
    check("  it says traps, not scenarios",
          result["rows"][-1].endswith("your 8 traps explained"),
          result["rows"][-1:])
    check("  the offer card: 2px accent border, its own ground",
          result["border"] == "2px " + ACCENT
          and result["fill"] == "rgb(19, 26, 18)", result["border"])
    check("  engine.js's pay button inside it, 58px or more, 20px, priced",
          result["payIn"] and result["payH"] >= 58
          and result["paySize"] == "20px"
          and result["payText"] == "Unlock my strategy · $6",
          [result["payText"], result["payH"], result["paySize"]])
    check("  no zone bars, round strip or level chip; no horizontal scroll",
          result["zones"] == 0 and result["sw"] <= result["vw"])
    check("no script errors", not errors, errors)
    shot = os.environ.get("AI_SHOT")
    if shot:
        page.screenshot(path="%s-%d.png" % (shot, width), full_page=True)
    ctx.close()


def main():
    server = walk.Server(("127.0.0.1", PORT), walk.Handler)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    with sync_playwright() as pw:
        browser = pw.chromium.launch(executable_path=walk.CHROME)
        run(browser, 390, 844)
        run(browser, 360, 640)
        run(browser, 390, 844, reduced=True)
        browser.close()
    server.shutdown()

    print("\n%d checks, %d failed" % (checks[0], len(fails)))
    for line in fails:
        print("  FAIL " + line[:420])
    return 1 if fails else 0


if __name__ == "__main__":
    sys.exit(main())
