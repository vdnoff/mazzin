#!/usr/bin/env python3
"""The /ai-navigator walk, in a real browser: twelve steps that answer back.

What is walked, at 390x844 and again at 360x640:

  - the intro, then four warm-ups, one screen between, eight scenarios;
  - on every step the answers are all on screen without scrolling, the
    counter chip and the progress label say what the config says, and no
    card holds an image;
  - on every scenario a tap marks the right answer and, where the tap was
    wrong, the tapped one; a panel under the cards says which it was and
    why, and it too is on screen without scrolling;
  - the panel moves on by itself after the configured delay, and at once on
    its Next button or on a tap anywhere;
  - exactly one swipe event a step, fired at the tap, and one interstitial;
  - the free result is three blocks in order, with engine.js's pay button
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
DELAY = CFG["swipe"]["feedback_ms"]

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
  const cards = [...document.querySelectorAll('#cards .card')];
  const panel = document.querySelector('#step-feedback');
  const ground = getComputedStyle(document.body).backgroundColor;
  return {
    caption: text('#swipe-caption'), chip: text('#step-chip'),
    kicker: text('#step-kicker'), sub: text('#step-sub'),
    label: text('#progress-label'),
    cards: cards.map(c => ({
      text: (c.querySelector('.card-text') || {}).textContent || '',
      box: box(c), cls: c.className,
      flag: (c.querySelector('.card-flag') || {}).textContent || '',
      border: getComputedStyle(c).borderTopColor,
      fill: getComputedStyle(c).backgroundColor,
      imgs: c.querySelectorAll('img').length })),
    panel: shown(panel) ? {
      box: box(panel), cls: panel.className,
      head: panel.querySelector('.step-feedback-head').textContent,
      why: panel.querySelector('.step-feedback-why').textContent,
      next: panel.querySelector('.step-feedback-next').textContent,
      headColor: getComputedStyle(
        panel.querySelector('.step-feedback-head')).color } : null,
    ground: ground, vh: innerHeight, vw: innerWidth,
    sh: document.documentElement.scrollHeight,
    sw: document.documentElement.scrollWidth,
    y: scrollY
  };
}"""

ACCENT = "rgb(200, 245, 59)"
MISS = "rgb(255, 154, 122)"


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

    intro = page.evaluate("""() => {
      const q = s => (document.querySelector(s) || {}).textContent || '';
      const cta = document.querySelector('.intro-cta').getBoundingClientRect();
      const last = document.querySelector('.intro-chip:last-child');
      const brand = document.querySelector('.swipe-brand');
      return { kicker: q('.intro-kicker'), head: q('.intro-head'),
               sub: q('.intro-sub'), cta: q('.intro-cta'),
               chips: [...document.querySelectorAll('.intro-chip')]
                 .map(c => c.textContent),
               foot: q('.intro-foot'), note: q('.intro-foot-note'),
               ctaBox: [Math.round(cta.top), Math.round(cta.bottom),
                        Math.round(cta.height)],
               dashed: getComputedStyle(last).borderTopStyle,
               ground: getComputedStyle(document.body).backgroundColor,
               font: getComputedStyle(document.querySelector('.intro-head'))
                 .fontFamily,
               brand: getComputedStyle(brand, '::before').content
                 + getComputedStyle(brand, '::after').content,
               brandFont: getComputedStyle(brand).fontFamily,
               pad: Math.round(document.querySelector('.intro')
                 .getBoundingClientRect().left),
               imgs: document.querySelectorAll('#screen-swipe img').length,
               vh: innerHeight, sw: document.documentElement.scrollWidth,
               vw: innerWidth }; }""")
    I = CFG["intro"]
    check("the intro says what the config says",
          intro["kicker"].strip("◆ ") == I["kicker"]
          and intro["head"] == I["headline"] and intro["sub"] == I["sub"]
          and intro["chips"] == I["chips"] and intro["cta"] == I["cta"]
          and intro["foot"] == I["foot"] and intro["note"] == I["foot_note"],
          intro)
    check("  dark ground, Space Grotesk headline, Fraunces wordmark",
          intro["ground"] == "rgb(11, 15, 20)"
          and "Space Grotesk" in intro["font"]
          and intro["brand"] == '"mazzin""."'
          and "Fraunces" in intro["brandFont"],
          [intro["ground"], intro["font"], intro["brand"]])
    check("  the button is on screen, 58px or more, 24px page padding",
          intro["ctaBox"][1] <= intro["vh"] and intro["ctaBox"][2] >= 58
          and intro["pad"] == 24 and intro["sw"] <= intro["vw"],
          [intro["ctaBox"], intro["pad"]])
    check("  the last chip is the dashed one", intro["dashed"] == "dashed")
    page.locator(".intro-cta").click()

    mids = 0
    for index, step in enumerate(STEPS):
        number = index + 1
        wait_step(page, step["question"])
        before = page.evaluate(SCREEN)
        cards = step["pairs"][0]["images"]
        scored = "why" in step
        ok_fit = (before["sh"] <= before["vh"] and before["sw"] <= before["vw"]
                  and len(before["cards"]) == len(cards)
                  and all(0 <= c["box"][0] and c["box"][1] <= before["vh"]
                          and c["box"][2] >= 0 and c["box"][3] <= before["vw"]
                          for c in before["cards"]))
        check("%d %s: every answer on screen, no scrolling"
              % (number, step["id"]), ok_fit,
              [before["sh"], before["vh"],
               [c["box"] for c in before["cards"]][-1:]])
        check("  chip, label, kicker and sub are the config's",
              before["chip"] == step.get("chip", "")
              and before["label"] == step.get(
                  "progress_label", "%d of %d" % (number, len(STEPS)))
              and before["kicker"] == step.get("kicker", "")
              and before["sub"] == step.get("sub", ""),
              [before["chip"], before["label"], before["kicker"]])
        check("  no image on any card",
              not any(c["imgs"] for c in before["cards"]))
        if scored:
            check("  dealt as four stacked rows, the same four answers",
                  sorted(c["text"] for c in before["cards"])
                  == sorted(c["label"] for c in cards)
                  and len({c["box"][0] for c in before["cards"]}) == 4)

        # Odd scenarios are answered right, even ones wrong.
        scenario = number - 4
        right = cards[0]["label"]
        pick = right if (not scored or scenario % 2) else cards[2]["label"]
        if not scored:
            pick = cards[1]["label"]
        count = len(swipes())
        tapped = time.time()
        card(page, pick).click()
        page.wait_for_timeout(260)
        check("  one swipe event, at the tap",
              len(swipes()) == count + 1
              and swipes()[-1].get("step") == number
              and swipes()[-1]["extra"]["chosen"]
              == next(c["id"] for c in cards if c["label"] == pick),
              swipes()[-1:] )

        if not scored:
            after = page.evaluate(SCREEN)
            check("  no feedback panel on a warm-up", after["panel"] is None
                  and not any(c["flag"] for c in after["cards"]))
            if number == 4:
                page.wait_for_selector("#screen-interstitial.is-active",
                                       timeout=5000)
                page.wait_for_timeout(400)
                mid = page.evaluate("""() => {
                  const q = s => (document.querySelector(s) || {})
                    .textContent || '';
                  const cta = document.querySelector('#mid-cta')
                    .getBoundingClientRect();
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
                check("  all of it on screen, button included",
                      mid["ctaBottom"] <= mid["vh"] and mid["sh"] <= mid["vh"],
                      [mid["ctaBottom"], mid["vh"], mid["sh"]])
                page.wait_for_timeout(4300)
                check("  it waits for its button",
                      page.evaluate("() => document.querySelector("
                                    "'#screen-interstitial').classList"
                                    ".contains('is-active')"))
                mids += 1
                page.locator("#mid-cta").click()
            continue

        after = page.evaluate(SCREEN)
        panel = after["panel"]
        good = pick == right
        by_text = dict((c["text"], c) for c in after["cards"])
        check("  the right answer is marked: accent border, the word Right",
              "is-right" in by_text[right]["cls"]
              and by_text[right]["flag"] == FEEDBACK["right"]
              and by_text[right]["border"] == ACCENT
              and by_text[right]["fill"] == "rgb(27, 36, 16)",
              by_text[right])
        if good:
            check("  and nothing else is flagged",
                  [c["flag"] for c in after["cards"]].count("") == 3
                  and not any("is-wrong" in c["cls"] for c in after["cards"]))
        else:
            check("  the wrong pick is marked: miss border, Your pick",
                  "is-wrong" in by_text[pick]["cls"]
                  and by_text[pick]["flag"] == FEEDBACK["yours"]
                  and by_text[pick]["border"] == MISS
                  and by_text[pick]["fill"] == "rgb(42, 23, 18)"
                  and [c["flag"] for c in after["cards"]].count("") == 2,
                  by_text[pick])
        check("  the panel says which it was, and the step's why",
              panel and panel["head"] == (FEEDBACK["good"] if good
                                          else FEEDBACK["bad"])
              and panel["why"] == step["why"]
              and panel["next"] == FEEDBACK["next"]
              and panel["headColor"] == (ACCENT if good else MISS)
              and ("is-good" if good else "is-bad") in panel["cls"], panel)
        check("  answers and panel all on screen, nothing scrolled",
              panel and panel["box"][1] <= after["vh"]
              and after["sh"] <= after["vh"] and after["y"] == 0
              and all(c["box"][1] <= panel["box"][0] + 1
                      for c in after["cards"]),
              [panel and panel["box"], after["vh"], after["sh"]])

        nxt = STEPS[index + 1]["question"] if index + 1 < len(STEPS) else None
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
            page.locator("#swipe-caption").click()    # anywhere at all
            page.wait_for_function(gone, timeout=600)
            took = (time.time() - tapped) * 1000
            check("  a tap anywhere moves on at once", took < DELAY - 600,
                  round(took))
        else:
            page.wait_for_timeout(420)
            page.locator(".step-feedback-next").click()
            page.wait_for_function(gone, timeout=600)
            took = (time.time() - tapped) * 1000
            check("  Next moves on at once", took < DELAY - 600, round(took))
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
      return { order: [...root.children].map(c => c.className.split(' ')[0]),
               payIn: offer.contains(pay), payText: pay.textContent,
               payH: Math.round(pay.getBoundingClientRect().height),
               border: cs.borderTopWidth + ' ' + cs.borderTopColor,
               fill: cs.backgroundColor,
               nameSize: getComputedStyle(name).fontSize,
               ring: root.querySelector('.ai-ring-n').textContent,
               predict: root.querySelector('.ai-predict').textContent,
               word: (root.querySelector('.ai-calibration') || {})
                 .textContent || '',
               zones: root.querySelectorAll('.ai-zone, .ai-mark, .ai-level')
                 .length,
               sw: document.documentElement.scrollWidth, vw: innerWidth }; }""")
    check("the free result: three blocks in order, then the rest",
          result["order"] == ["ai-profile", "ai-scorecard", "ai-offer",
                              "ai-foot"], result["order"])
    check("  the type name at 46px, the ring N/8, the prediction line",
          result["nameSize"] == "46px" and result["ring"] == "4/8"
          and result["predict"] == "You predicted 3–4. You scored 4."
          and result["word"] == CFG["result_copy"]["calibration"]["on"],
          [result["nameSize"], result["ring"], result["predict"]])
    check("  the offer card: 2px accent border, its own ground",
          result["border"] == "2px " + ACCENT
          and result["fill"] == "rgb(19, 26, 18)", result["border"])
    check("  engine.js's pay button inside it, 58px or more, priced",
          result["payIn"] and result["payH"] >= 58
          and result["payText"] == "Unlock my strategy · $6",
          [result["payText"], result["payH"]])
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
