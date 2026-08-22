#!/usr/bin/env python3
"""The twelve-sign step and the always-on labels, in a browser.

Two things here cannot be checked from the config. Whether twelve cells fit a
phone with the question above them is a fact about a layout engine, not about
JSON; and whether a white word is readable is a fact about what is behind it.
Both were wrong at some point in writing this — the signs arrived shuffled,
and an earlier label sat at 2.6:1 on the lightest frame — and neither was
visible without rendering the page.

The label is a pill below the picture now, so the third thing checked here is
that it stays there: the middle of every cell, where a glyph or a horizon is,
has to come out exactly as painted.

Contrast is measured over the rectangle the word occupies, with the type made
transparent so nothing measured is its own antialiasing. Transparent rather
than blanked: the pill is sized to its content, so emptying the text shrinks
it out from under the crop and what gets measured is the artwork — which
reads as a comfortable pass on a dark frame and a wild failure on a pale one,
and is not a measurement of anything.

    python3 tests/test_zodiacgrid.py
"""
import http.server
import json
import os
import socketserver
import sys
import threading

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, REPO)

from PIL import Image                                     # noqa: E402
from playwright.sync_api import sync_playwright           # noqa: E402

ROOT = REPO
PORT = 8807
DSF = 2
CHROME = "/opt/pw-browsers/chromium-1194/chrome-linux/chrome"
SHOTS = os.path.dirname(os.path.abspath(__file__))

# WCAG AA for body text. The label is large and bold enough to qualify for
# the 3.0 threshold, and is held to the stricter one anyway — it sits on
# photographs, where a margin is the difference between a design that works
# on the frames we have and one that works on the next frame too.
MIN_CONTRAST = 4.5

ZODIAC = ["Aries", "Taurus", "Gemini", "Cancer", "Leo", "Virgo", "Libra",
          "Scorpio", "Sagittarius", "Capricorn", "Aquarius", "Pisces"]

# The lightest frame in the gallery, the busiest, and the one the funnel
# opens on. ls5f is a near-white sky and is the one that fails first.
PROBES = {"zk1a": "hook", "sign_aries": "sign", "ls5f": "landscape",
          "dr11a": "drain"}

fails = []
checks = [0]


def check(label, ok, detail=""):
    checks[0] += 1
    if not ok:
        fails.append("%s %s" % (label, detail))
    print("  %-58s %s%s" % (label, "ok" if ok else "FAIL",
                            ("  " + str(detail)) if not ok else ""))


class Handler(http.server.SimpleHTTPRequestHandler):
    """static/ off disk, /zodiac and /kitchen are the shell, APIs stubbed."""

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
        self.rfile.read(int(self.headers.get("content-length") or 0))
        self._json({"ok": True})

    def _json(self, body):
        raw = json.dumps(body).encode()
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(raw)))
        self.end_headers()
        self.wfile.write(raw)


def luminance(px):
    def channel(v):
        v /= 255.0
        return v / 12.92 if v <= 0.04045 else ((v + 0.055) / 1.055) ** 2.4
    return (0.2126 * channel(px[0]) + 0.7152 * channel(px[1])
            + 0.0722 * channel(px[2]))


def contrast(bg):
    """White type on a background of this luminance."""
    return 1.05 / (bg + 0.05)


def frames(page):
    return page.eval_on_selector_all(
        "#cards .card img",
        "ns => ns.map(n => n.getAttribute('src').split('/').pop()"
        ".replace('.webp', ''))")


# engine.js holds a chosen card on screen — ring, badge, then the reaction
# chip — before the set leaves. Nothing may be asserted about the next step
# until that has run, and guessing a number shorter than it is how a suite
# reports a working funnel as broken.
HOLD_MS = 1650


def advance(page):
    """Tap the first card and clear whatever stands between steps."""
    page.locator("#cards .card").first.click()
    page.wait_for_timeout(HOLD_MS + 350)
    for _ in range(3):
        mid = page.locator("#screen-interstitial")
        if mid.count() and mid.is_visible():
            page.click("#mid-cta")
            page.wait_for_timeout(600)
        else:
            break


def measure(page, index, image_id):
    """Worst-pixel contrast under one card's label, and where its pill sits."""
    box = page.evaluate("""(i) => {
        const card = document.querySelectorAll('#cards .card')[i];
        const name = card.querySelector('.card-name');
        if (!name) return null;
        const range = document.createRange();
        range.selectNodeContents(name);
        const t = range.getBoundingClientRect();
        const c = card.getBoundingClientRect();
        const p = name.getBoundingClientRect();
        const cs = getComputedStyle(name);
        // Transparent, not emptied: the pill is content-sized, so emptying it
        // moves the box out from under the crop below.
        name.style.color = 'transparent';
        return {text: [t.left - c.left, t.top - c.top, t.width, t.height],
                pill: [p.left - c.left, p.top - c.top, p.width, p.height],
                cell: [c.width, c.height],
                background: cs.backgroundImage,
                lines: Math.round(t.height / parseFloat(cs.lineHeight))};
    }""", index)
    if not box or box["text"][2] < 1:
        return None
    page.wait_for_timeout(150)
    path = os.path.join(SHOTS, "grid12_%s.png" % image_id)
    page.locator("#cards .card").nth(index).screenshot(path=path)
    page.evaluate("""(i) => {
        document.querySelectorAll('#cards .card')[i]
            .querySelector('.card-name').style.color = '';
    }""", index)
    t = box["text"]
    with Image.open(path) as shot:
        crop = shot.convert("RGB").crop(
            (int(t[0] * DSF), int(t[1] * DSF),
             int((t[0] + t[2]) * DSF), int((t[1] + t[3]) * DSF)))
        levels = [luminance(p) for p in crop.convert("RGB").getdata()]
    os.remove(path)
    box["worst"] = min(contrast(v) for v in levels)
    return box


def run(page):
    print("\n--- the sign step ---")
    page.goto("http://127.0.0.1:%d/zodiac" % PORT)
    page.wait_for_selector("#cards .card", timeout=20000)
    page.wait_for_timeout(400)
    check("the hook comes first, as a pair",
          page.locator("#cards .card").count() == 2)
    advance(page)
    page.wait_for_function(
        "() => document.querySelectorAll('#cards .card').length === 12",
        timeout=10000)
    page.wait_for_timeout(500)

    check("the sign step draws twelve cells",
          page.locator("#cards .card").count() == 12,
          page.locator("#cards .card").count())
    check("  under the grid12 class",
          "is-grid12" in (page.get_attribute("#cards", "class") or ""),
          page.get_attribute("#cards", "class"))
    check("  asking for the sign",
          page.inner_text("#swipe-caption") == "Tap your zodiac sign:",
          page.inner_text("#swipe-caption"))
    loaded = page.eval_on_selector_all(
        "#cards .card img", "ns => ns.filter(n => n.naturalWidth > 0).length")
    check("  all twelve glyph frames actually decoded", loaded == 12, loaded)
    names = page.eval_on_selector_all(
        "#cards .card-name", "ns => ns.map(n => n.innerText.trim())")
    check("  every cell is named", len(names) == 12, str(names))
    check("  by a pill, one per cell", len(names) == 12
          and page.locator("#cards .card-name").count()
          == page.locator("#cards .card").count())
    # engine.js shuffles a pair unless the step opts out, and a shuffled
    # zodiac makes the reader scan all twelve for one they could point at.
    check("  in classical order, Aries to Pisces", names == ZODIAC, str(names))
    # The badge is what makes a sign findable, so a truncated one defeats the
    # step. Sagittarius is the longest of the twelve and the one that broke.
    clipped = page.eval_on_selector_all(".card-name", """ns => ns
        .filter(n => n.scrollWidth > n.clientWidth + 1)
        .map(n => n.innerText.trim())""")
    check("  every name whole, none truncated", not clipped, str(clipped))
    widest = page.eval_on_selector_all(".card-name", """ns => {
        let out = ['', 0, 0];
        ns.forEach(n => {
            const w = n.getBoundingClientRect().width;
            if (w > out[1]) out = [n.innerText.trim(), Math.round(w),
                                   Math.round(n.parentNode
                                     .getBoundingClientRect().width)];
        });
        return out;
    }""")
    check("  the longest (%s) fits in its cell at %dpx of %dpx"
          % (widest[0], widest[1], widest[2]),
          widest[1] < widest[2] - 6, str(widest))

    boxes = page.eval_on_selector_all("#cards .card", """ns => ns.map(n => {
        const r = n.getBoundingClientRect();
        return [Math.round(r.width), Math.round(r.height)];
    })""")
    smallest = min(min(b) for b in boxes)
    check("  every tap target clears 44px (smallest %dpx)" % smallest,
          smallest >= 44, smallest)
    check("  the badge type stepped down for the narrow cells",
          page.eval_on_selector(
              ".cards.is-grid12 .card-name",
              "n => parseFloat(getComputedStyle(n).fontSize)") <= 12)
    bottom = page.evaluate(
        "document.querySelector('#cards').getBoundingClientRect().bottom")
    check("  and the twelfth cell is on screen, not below the fold",
          bottom <= 844, "%d of 844" % round(bottom))
    check("  and the page does not scroll sideways",
          page.evaluate("document.documentElement.scrollWidth") <= 380,
          page.evaluate("document.documentElement.scrollWidth"))

    print("\n--- a tap on it registers ---")
    leo = names.index("Leo")
    page.locator("#cards .card").nth(leo).click()
    page.wait_for_timeout(250)
    check("the tapped card is marked chosen",
          page.locator("#cards .card.is-chosen").count() == 1,
          page.locator("#cards .card.is-chosen").count())
    check("  and it is the one that was tapped",
          page.eval_on_selector(
              "#cards .card.is-chosen img",
              "n => n.getAttribute('src')").endswith("sign_leo.webp"))
    page.wait_for_function(
        "() => document.getElementById('swipe-caption').innerText.trim()"
        " !== 'Tap your zodiac sign:'", timeout=HOLD_MS + 4000)
    page.wait_for_timeout(300)
    check("tapping a sign advances the run",
          page.inner_text("#swipe-caption") != "Tap your zodiac sign:",
          page.inner_text("#swipe-caption"))
    check("  and the next step is not the twelve-up again",
          page.locator("#cards .card").count() != 12,
          page.locator("#cards .card").count())

    print("\n--- the label leaves the picture alone ---")
    page.goto("http://127.0.0.1:%d/zodiac" % PORT)
    page.wait_for_selector("#cards .card", timeout=20000)
    seen = {}
    for _ in range(20):
        page.wait_for_timeout(450)
        here = frames(page)
        for image_id in PROBES:
            if image_id in here and image_id not in seen:
                got = measure(page, here.index(image_id), image_id)
                if got is not None:
                    seen[image_id] = got
        if len(seen) == len(PROBES):
            break
        advance(page)
        if not page.locator("#cards .card").count():
            break
    for image_id, step in sorted(PROBES.items()):
        got = seen.get(image_id)
        if got is None:
            check("  %-11s (%-9s) reached" % (image_id, step), False,
                  "never drawn")
            continue
        cell_h = got["cell"][1]
        pill_top = got["pill"][1]
        covered = 100.0 * got["pill"][2] * got["pill"][3] / (
            got["cell"][0] * cell_h)
        # The whole point of this mode. A label over the middle of the cell is
        # a label over the glyph, the horizon or the face the frame is of.
        check("  %-11s (%-9s) leaves the middle of the cell clear"
              % (image_id, step), pill_top > cell_h / 2,
              "pill top %.0f, centre %.0f" % (pill_top, cell_h / 2))
        check("    covering %.0f%% of it, low and small" % covered,
              covered < 20, "%.0f%%" % covered)
        check("    and painting nothing over the art",
              got["background"] == "none", got["background"])
        check("    on one line, not three", got["lines"] == 1, got["lines"])
        check("    white on it reads at %.1f:1" % got["worst"],
              got["worst"] >= MIN_CONTRAST,
              "below %.1f:1" % MIN_CONTRAST)

    print("\n--- and kitchen is left alone ---")
    page.goto("http://127.0.0.1:%d/kitchen" % PORT)
    page.wait_for_selector("#cards .card", timeout=20000)
    labels, classes = 0, set()
    for _ in range(13):
        page.wait_for_timeout(400)
        labels += page.locator("#cards .card-name").count()
        classes.add(page.get_attribute("#cards", "class") or "")
        advance(page)
        if not page.locator("#cards .card").count():
            break
    check("no kitchen step draws a permanent label", labels == 0, labels)
    check("  and none of them is a twelve-up",
          not [c for c in classes if "is-grid12" in c], str(sorted(classes)))


def main():
    socketserver.TCPServer.allow_reuse_address = True
    httpd = socketserver.TCPServer(("127.0.0.1", PORT), Handler)
    threading.Thread(target=httpd.serve_forever, daemon=True).start()
    try:
        with sync_playwright() as pw:
            browser = pw.chromium.launch(executable_path=CHROME)
            # 380 rather than 390: it is the narrower of the two common
            # phone widths and the one "Sagittarius" has to fit at.
            page = browser.new_page(viewport={"width": 380, "height": 844},
                                    device_scale_factor=DSF)
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
