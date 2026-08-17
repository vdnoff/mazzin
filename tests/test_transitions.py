#!/usr/bin/env python3
"""What one step change actually does, measured in a real browser.

Installs a MutationObserver before engine.js runs and records, for every step
of a full thirteen-step walk: when the selection dim lands, when the exit
starts, what animation each card is actually running at that moment, and — at
the first frame the new cards are painted — whether their images had already
decoded. Then re-runs the walk hammering the cards during the transition to
show the extra taps go nowhere, and once more under reduced motion to show
that path is still the instant swap.

    python3 transitions.py
"""
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from playwright.sync_api import sync_playwright   # noqa: E402
from test_walk import Handler, PORT, STEPS, ANCHORS, GRID, TOTAL, serve  # noqa: E402

CHROME = "/opt/pw-browsers/chromium-1194/chrome-linux/chrome"

fails = []
checks = [0]


def check(label, ok, detail=""):
    checks[0] += 1
    if not ok:
        fails.append("%s %s" % (label, detail))
    print("  %-62s %s%s" % (label, "ok" if ok else "FAIL",
                            ("  " + str(detail)) if not ok else ""))


# Installed before any of the page's own script. Everything it records is read
# off getComputedStyle at the instant the class actually changed, so these are
# the values the compositor used, not the ones the stylesheet says it should.
PROBE = r"""
window.__T = { steps: [], taps: 0 };
document.addEventListener('DOMContentLoaded', function () {
  var cards = document.getElementById('cards');
  var cap = document.getElementById('swipe-caption');
  var cur = null;

  function snap() {
    return Array.prototype.map.call(
      cards.querySelectorAll('.card'), function (c, i) {
        var s = getComputedStyle(c);
        var im = c.querySelector('img');
        return {
          i: i,
          chosen: c.classList.contains('is-chosen'),
          name: s.animationName,
          dur: s.animationDuration,
          delay: s.animationDelay,
          opacity: s.opacity,
          transform: s.transform,
          transition: s.transitionDuration,
          ready: im ? !!(im.complete && im.naturalWidth > 0) : null
        };
      });
  }

  function capSnap() {
    var s = getComputedStyle(cap);
    return { name: s.animationName, dur: s.animationDuration,
             opacity: s.opacity, text: cap.textContent };
  }

  function pipSnap() {
    var done = document.querySelectorAll('#pips .pip.is-done').length;
    var one = document.querySelector('#pips .pip');
    var s = one ? getComputedStyle(one) : {};
    return { done: done, transition: s.transitionDuration || '' };
  }

  new MutationObserver(function (recs) {
    recs.forEach(function (r) {
      if (r.type === 'attributes') {
        var has = cards.classList.contains('is-picking');
        var leaving = cards.classList.contains('is-leaving');
        if (has && (!cur || cur.closed)) {
          cur = { closed: false, t_pick: performance.now(),
                  pick: snap(), stagger:
                    cards.style.getPropertyValue('--stagger') };
          window.__T.steps.push(cur);
        } else if (leaving && cur && !cur.t_exit) {
          cur.t_exit = performance.now();
          cur.exit = snap();
          cur.capExit = capSnap();
          cur.pipExit = pipSnap();
        }
      } else if (r.type === 'childList' && r.addedNodes.length && cur
                 && cur.t_exit && !cur.t_enter) {
        // The whole set is appended in one synchronous pass, so the first
        // batch of records is the whole set; read it on the next frame, which
        // is the first frame it is painted on.
        cur.t_enter = performance.now();
        cur.closed = true;
        (function (c) {
          requestAnimationFrame(function () {
            c.enter = snap();
            c.capEnter = capSnap();
            c.enterStagger = cards.style.getPropertyValue('--stagger');
            c.t_painted = performance.now();
          });
        })(cur);
      }
    });
  }).observe(cards, { attributes: true, attributeFilter: ['class'],
                      childList: true });
});
"""


def ms(value):
    """'220ms' / '0.22s' -> 220.0"""
    value = (value or "").split(",")[0].strip()
    if value.endswith("ms"):
        return float(value[:-2])
    if value.endswith("s"):
        return float(value[:-1]) * 1000
    return 0.0


def scale_of(matrix):
    """The uniform scale out of a computed `matrix(a, b, c, d, e, f)`."""
    if not matrix.startswith("matrix("):
        return 1.0
    parts = [float(p) for p in matrix[7:-1].split(",")]
    return parts[0]


def tx_of(matrix):
    if not matrix.startswith("matrix("):
        return 0.0
    return float(matrix[7:-1].split(",")[4])


def split_swaps(swaps):
    """(step-to-step swaps, swaps with an interstitial in the middle)."""
    direct, bridged = [], []
    for i, s in enumerate(swaps):
        (bridged if (i + 1) in ANCHORS else direct).append(s)
    return direct, bridged


def open_page(pw, reduced=False):
    browser = pw.chromium.launch(executable_path=CHROME)
    page = browser.new_page(viewport={"width": 390, "height": 844},
                            reduced_motion="reduce" if reduced else "no-preference")
    page.add_init_script(PROBE)
    errors = []
    page.on("pageerror", lambda e: errors.append(str(e)))
    page.on("console",
            lambda m: errors.append(m.text) if m.type == "error" else None)
    return browser, page, errors


def tap_through(page, hammer=False):
    """One full walk. `hammer` clicks every card repeatedly mid-transition."""
    page.goto("http://127.0.0.1:%d/kitchen" % PORT)
    page.wait_for_selector("#cards .card", timeout=10000)
    for index, step in enumerate(STEPS):
        cards = page.query_selector_all("#cards .card")
        cards[index % len(cards)].click()
        if hammer:
            # Straight through the hold, the exit and the decode gate.
            for _ in range(6):
                for c in cards:
                    try:
                        c.click(timeout=400, force=True)
                    except Exception:
                        pass
                page.wait_for_timeout(120)
        completed = index + 1
        if completed in ANCHORS and completed < TOTAL:
            page.wait_for_selector("#screen-interstitial.is-active",
                                   timeout=12000)
            page.click("#mid-cta")
        if completed < TOTAL:
            page.wait_for_function(
                "q => document.getElementById('screen-swipe')"
                ".classList.contains('is-active') &&"
                " document.getElementById('swipe-caption').textContent === q",
                arg=STEPS[completed]["question"], timeout=15000)
    page.wait_for_selector("#result-body:not([hidden])", timeout=20000)
    return page.evaluate("window.__T")


def main():
    httpd = serve()
    try:
        with sync_playwright() as pw:
            print("\n=== full motion: thirteen step changes ===")
            browser, page, errors = open_page(pw)
            data = tap_through(page)
            steps = data["steps"]
            check("every step change was observed",
                  len(steps) == TOTAL, len(steps))
            check("no page errors", not errors, errors[:3])

            # The last step hands over to the result screen, so it has a
            # selection and an exit but no incoming pair of its own.
            swaps = [s for s in steps if s.get("enter")]
            check("twelve of them swapped in a new set",
                  len(swaps) == TOTAL - 1, len(swaps))

            print("\n--- 1. the selection moment ---")
            for s in steps:
                fmt = "pair"
                n = len(s["pick"])
                if n == 4:
                    fmt = "grid4"
                elif n == 6:
                    fmt = "grid6"
                others = [c for c in s["pick"] if not c["chosen"]]
                chosen = [c for c in s["pick"] if c["chosen"]]
                ok = (len(chosen) == 1 and len(others) == n - 1
                      and all(ms(c["transition"]) == 180 for c in others))
                check("  %-5s  %d non-chosen dim on a 180ms curve" % (fmt, n - 1),
                      ok, [c["transition"] for c in others][:1])

            # Read after the transition has run, at the exit snapshot.
            dimmed = []
            for s in steps:
                for c in s["exit"]:
                    if not c["chosen"]:
                        dimmed.append((float(c["opacity"]),
                                       round(scale_of(c["transform"]), 3)))
            check("  every non-chosen card reached 0.4 opacity",
                  all(abs(o - 0.4) < 0.02 for o, _ in dimmed),
                  sorted(set(o for o, _ in dimmed))[:4])
            check("  and 0.96 scale",
                  all(abs(sc - 0.96) < 0.005 for _, sc in dimmed),
                  sorted(set(sc for _, sc in dimmed))[:4])

            print("\n--- 2. the exit ---")
            bad = []
            for s in steps:
                for c in s["exit"]:
                    want_name = "card-out-chosen" if c["chosen"] else "card-out"
                    want_delay = 40 if c["chosen"] else 0
                    if (c["name"] != want_name or ms(c["dur"]) != 220
                            or ms(c["delay"]) != want_delay):
                        bad.append(c)
            check("  220ms card-out on every card, chosen last (+40ms)",
                  not bad, bad[:2])
            check("  the question fades out with them",
                  all(s["capExit"]["name"] == "caption-out"
                      and ms(s["capExit"]["dur"]) == 220 for s in steps),
                  [s["capExit"]["name"] for s in steps][:3])
            gaps = [round(s["t_exit"] - s["t_pick"]) for s in steps]
            check("  the exit starts after the hold, not before",
                  all(1500 <= g <= 1900 for g in gaps), gaps)

            print("\n--- 3. the enter ---")
            bad = []
            for s in swaps:
                per = ms(s["enterStagger"])
                for c in s["enter"]:
                    if (c["name"] != "card-in" or ms(c["dur"]) != 240
                            or abs(ms(c["delay"]) - c["i"] * per) > 0.5):
                        bad.append([s["enterStagger"], c])
            check("  240ms card-in on every card, left to right",
                  not bad, bad[:2])

            by_format = {}
            for s in swaps:
                n = len(s["enter"])
                by_format[n] = (ms(s["enterStagger"]),
                                max(ms(c["delay"]) for c in s["enter"]))
            for n in sorted(by_format):
                per, total = by_format[n]
                check("  %d cards: %gms apart, %gms of stagger in total"
                      % (n, per, total),
                      per <= 50 and total <= 150, by_format[n])
            check("  all three formats were exercised",
                  sorted(by_format) == [2, 4, 6], sorted(by_format))
            check("  the incoming cards start 24px to the right",
                  all(abs(tx_of(c["transform"]) - 24) < 0.6
                      for s in swaps for c in s["enter"]
                      if ms(c["delay"]) == 0),
                  [round(tx_of(c["transform"]), 1)
                   for c in swaps[0]["enter"]])
            check("  the question crossfades back in over 240ms",
                  all(s["capEnter"]["name"] == "caption-in"
                      and ms(s["capEnter"]["dur"]) == 240 for s in swaps),
                  [s["capEnter"]["name"] for s in swaps][:3])
            check("  and it is the next step's question",
                  [s["capEnter"]["text"] for s in swaps]
                  == [st["question"] for st in STEPS[1:]],
                  [s["capEnter"]["text"] for s in swaps][:2])

            print("\n--- 4. the pip fills with the exit ---")
            check("  a pip is filled at each exit, none before",
                  [s["pipExit"]["done"] for s in steps]
                  == list(range(1, TOTAL + 1)),
                  [s["pipExit"]["done"] for s in steps])
            check("  its colour eases over the same 220ms",
                  all(ms(s["pipExit"]["transition"]) == 220 for s in steps),
                  steps[0]["pipExit"]["transition"])

            print("\n--- 7. nothing enters before it has decoded ---")
            blank = [c for s in swaps for c in s["enter"] if not c["ready"]]
            check("  every incoming card had its image on the first frame",
                  not blank, blank[:2])

            print("\n--- 8. the latency budget ---")
            # Three of the twelve swaps have an interstitial between the exit
            # and the enter, so their gap is that screen plus this harness's own
            # click round-trip rather than anything the transition costs. The
            # interstitial is item 5's territory and is untouched; the budget is
            # measured on the nine step-to-step swaps.
            direct, bridged = split_swaps(swaps)
            swap_ms = [round(s["t_enter"] - s["t_exit"]) for s in direct]
            # Was 200ms before this change: 160ms of card-out plus a 40ms
            # stagger. The animation itself is now 260, so the budget is what
            # the decode gate is allowed to add on top.
            check("  exit to enter is at most 500ms over the old 200",
                  all(g <= 700 for g in swap_ms), swap_ms)
            check("  in practice the gate costs almost nothing",
                  all(g <= 320 for g in swap_ms), swap_ms)
            check("  and never less than the 260ms the animation needs",
                  all(g >= 255 for g in swap_ms), swap_ms)
            total_ms = [round(s["t_enter"] - s["t_pick"]) for s in direct]
            check("  tap to next set is the hold plus the swap and no more",
                  all(t <= 2150 for t in total_ms), max(total_ms))
            print("    (across an interstitial: %s — that screen, not this)"
                  % [round(s["t_enter"] - s["t_exit"]) for s in bridged])
            browser.close()

            print("\n=== taps during the transition go nowhere ===")
            browser, page, errors = open_page(pw)
            data = tap_through(page, hammer=True)
            check("still exactly thirteen step changes",
                  len(data["steps"]) == TOTAL, len(data["steps"]))
            check("no step was skipped by a double tap",
                  [s["pipExit"]["done"] for s in data["steps"]]
                  == list(range(1, TOTAL + 1)),
                  [s["pipExit"]["done"] for s in data["steps"]])
            check("every question was shown, in order",
                  [s["capEnter"]["text"] for s in data["steps"]
                   if s.get("capEnter")] == [st["question"] for st in STEPS[1:]],
                  [s["capEnter"]["text"] for s in data["steps"]
                   if s.get("capEnter")][:3])
            check("the run still reached the result", page.query_selector(
                "#result-body:not([hidden])") is not None)
            check("no page errors under hammering", not errors, errors[:3])
            browser.close()

            print("\n=== reduced motion: the instant swap, unchanged ===")
            browser, page, errors = open_page(pw, reduced=True)
            data = tap_through(page)
            steps = data["steps"]
            swaps = [s for s in steps if s.get("enter")]
            check("thirteen step changes", len(steps) == TOTAL, len(steps))
            check("cards cross-fade rather than travel",
                  all(c["name"] == "fade-out" and ms(c["dur"]) == 160
                      and ms(c["delay"]) == 0
                      for s in steps for c in s["exit"]),
                  [(c["name"], c["delay"]) for c in steps[0]["exit"]])
            check("incoming cards fade in with no travel",
                  all(c["name"] == "fade-in" and ms(c["delay"]) == 0
                      and tx_of(c["transform"]) == 0
                      for s in swaps for c in s["enter"]),
                  [(c["name"], c["delay"], c["transform"])
                   for c in swaps[0]["enter"]][:2])
            check("the question is replaced in place, not faded out",
                  all(s["capExit"]["name"] == "none" for s in steps),
                  [s["capExit"]["name"] for s in steps][:3])
            check("the pip does not pop",
                  all(ms(s["pipExit"]["transition"]) == 0 for s in steps),
                  steps[0]["pipExit"]["transition"])
            hold = [round(s["t_exit"] - s["t_pick"]) for s in steps]
            check("the hold is the short one", all(400 <= h <= 700 for h in hold),
                  hold)
            direct, bridged = split_swaps(swaps)
            swap_ms = [round(s["t_enter"] - s["t_exit"]) for s in direct]
            check("the swap is the old 200ms, plus the decode gate only",
                  all(195 <= g <= 260 for g in swap_ms), swap_ms)
            check("tap to next set is under a second",
                  all(round(s["t_enter"] - s["t_pick"]) <= 950 for s in direct),
                  max(round(s["t_enter"] - s["t_pick"]) for s in direct))
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
