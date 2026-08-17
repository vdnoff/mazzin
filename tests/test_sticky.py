#!/usr/bin/env python3
"""Is the sticky bar actually on the screen, or only un-`hidden`?

The rest of the suite asserts the `hidden` property and the class. That is the
engine's intent; this measures the pixels, because `[hidden]` competing with an
author `display` is exactly the kind of thing that reads as working in a
property check and ships a bar nobody can dismiss.
"""
import socketserver, threading
import test_single as single
from playwright.sync_api import sync_playwright

single.single[0] = True
single.checkout_ok[0] = True
fails = []


def check(label, ok, detail=""):
    if not ok:
        fails.append(label)
    print("  %-52s %s%s" % (label, "ok" if ok else "FAIL",
                            ("  " + str(detail)) if not ok else ""))


def bar(page):
    """Where the bar really is, in viewport terms."""
    return page.evaluate("""() => {
      const b = document.getElementById('sticky-cta');
      const r = b.getBoundingClientRect();
      const s = getComputedStyle(b);
      return {
        hiddenAttr: b.hidden,
        display: s.display,
        top: Math.round(r.top), bottom: Math.round(r.bottom),
        h: Math.round(r.height),
        onScreen: s.display !== 'none' && r.height > 0
                  && r.bottom > 0 && r.top < window.innerHeight,
        vh: window.innerHeight,
      };
    }""")


socketserver.TCPServer.allow_reuse_address = True
httpd = socketserver.TCPServer(("127.0.0.1", single.PORT), single.Handler)
threading.Thread(target=httpd.serve_forever, daemon=True).start()
try:
    with sync_playwright() as pw:
        b = pw.chromium.launch(
            executable_path="/opt/pw-browsers/chromium-1194/chrome-linux/chrome")
        pg = b.new_page(viewport={"width": 390, "height": 844})
        pg.goto("http://127.0.0.1:%d/kitchen" % single.PORT)
        single.quiz(pg)

        top = bar(pg)
        check("at the top of the result it is display:none",
              top["display"] == "none" and not top["onScreen"], top)

        pg.evaluate("""() => { const p = document.querySelector('#report .section');
             window.scrollTo(0, p.getBoundingClientRect().bottom
                                + window.scrollY + 60); }""")
        pg.wait_for_timeout(700)
        shown = bar(pg)
        check("past the palette it is really on screen",
              shown["onScreen"] and shown["h"] > 30, shown)
        check("it sits at the bottom, above the safe area",
              shown["bottom"] <= shown["vh"] and shown["bottom"] > shown["vh"] - 60,
              shown)

        pg.evaluate("() => document.getElementById('commerce').scrollIntoView()")
        pg.wait_for_timeout(900)
        gone = bar(pg)
        check("at the offer it is off the screen again",
              not gone["onScreen"], gone)

        # Back up: it must come back rather than being a one-shot. Measured off
        # the palette rather than scrolled to a fixed 400px — the bar's rule is
        # "past the free section", and the page's height is not a constant.
        pg.evaluate("""() => { const p = document.querySelector('#report .section');
             window.scrollTo(0, p.getBoundingClientRect().bottom
                                + window.scrollY + 60); }""")
        pg.wait_for_timeout(900)
        again = bar(pg)
        check("scrolling back up brings it back", again["onScreen"], again)
        b.close()
finally:
    httpd.shutdown()

print("\n%d failed" % len(fails))
raise SystemExit(1 if fails else 0)
