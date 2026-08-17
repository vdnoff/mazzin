#!/usr/bin/env python3
"""The working row must not change how long the interstitial holds.

Taps to the first anchor, then leaves the screen alone and times how long it
takes to dismiss itself. INTERSTITIAL_MS is 4000 and was not touched.
"""
import json, os, sys, time
import test_walk as walk
from playwright.sync_api import sync_playwright

# This was written as a script that printed its verdict and exited 0 whatever
# it found, which under an exit-code runner is a suite that can only ever say
# "ok". The three conditions below and the 3.9-4.3s window are unchanged; all
# that is added is that a FAIL now reaches the exit status.
fails = []


def verdict(label, ok):
    if not ok:
        fails.append(label)
    print("%s: %s" % (label, "ok" if ok else "FAIL"))

STEPS = walk.STEPS
ANCHOR = min(walk.ANCHORS)
GRID = walk.GRID

httpd = walk.serve()
try:
    with sync_playwright() as pw:
        b = pw.chromium.launch(
            executable_path="/opt/pw-browsers/chromium-1194/chrome-linux/chrome")
        pg = b.new_page(viewport={"width": 390, "height": 844})
        errs = []
        pg.on("pageerror", lambda e: errs.append(str(e)))
        pg.goto("http://127.0.0.1:%d/kitchen" % walk.PORT)
        pg.wait_for_selector("#cards .card", timeout=10000)

        for i in range(ANCHOR - 1):
            pg.query_selector_all("#cards .card")[0].click()
            pg.wait_for_function(
                "q => document.getElementById('swipe-caption').textContent === q",
                arg=STEPS[i + 1]["question"], timeout=12000)

        # Timed inside the page: a MutationObserver stamps the moment the
        # screen goes active and the moment it goes inactive, so the number is
        # the engine's own hold rather than however long the test took to
        # notice it. Installed before the tap that opens it.
        pg.evaluate("""() => {
          window.__held = null;
          const node = document.getElementById('screen-interstitial');
          let opened = null;
          new MutationObserver(() => {
            const on = node.classList.contains('is-active');
            if (on && opened === null) opened = performance.now();
            if (!on && opened !== null && window.__held === null) {
              window.__held = performance.now() - opened;
            }
          }).observe(node, {attributes: true, attributeFilter: ['class']});
        }""")

        pg.query_selector_all("#cards .card")[0].click()
        # No tap on the interstitial. It has to let itself go.
        pg.wait_for_function("() => window.__held !== null", timeout=20000)
        held = pg.evaluate("() => window.__held") / 1000.0
        print("auto-dismissed after %.2fs (INTERSTITIAL_MS = 4.0s)" % held)
        verdict("timing unchanged", 3.9 <= held <= 4.3)
        verdict("advanced to the next step", pg.eval_on_selector(
            "#screen-swipe", "n => n.classList.contains('is-active')"))
        verdict("spinner stopped with the screen", pg.eval_on_selector_all(
            ".mid-working", "ns => ns.length") <= 1)
        verdict("no page errors", not errs)
        if errs:
            print("  ", errs[:3])
        b.close()
finally:
    httpd.shutdown()

print("\n4 checks, %d failed" % len(fails))
raise SystemExit(1 if fails else 0)
