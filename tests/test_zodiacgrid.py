#!/usr/bin/env python3
"""The twelve-sign step and the always-on labels, in a browser.

Two things here cannot be checked from the config. Whether twelve cells fit a
phone with the question above them is a fact about a layout engine, not about
JSON; and whether a white word is readable on a particular photograph is a
fact about that photograph. Both were wrong at some point in writing this —
the signs arrived shuffled, and the label sat at 2.6:1 on the lightest frame —
and neither was visible without rendering the page.

Contrast is measured over the rectangle the word actually occupies, with the
word blanked in place so nothing measured is its own antialiasing.

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
    """Worst-pixel contrast under the label of one card."""
    box = page.evaluate("""(i) => {
        const card = document.querySelectorAll('#cards .card')[i];
        const name = card.querySelector('.card-name');
        if (!name) return null;
        const range = document.createRange();
        range.selectNodeContents(name);
        const t = range.getBoundingClientRect();
        const c = card.getBoundingClientRect();
        name.dataset.keep = name.textContent;
        name.textContent = ' ';
        return [t.left - c.left, t.top - c.top, t.width, t.height];
    }""", index)
    if not box or box[2] < 1:
        return None
    page.wait_for_timeout(120)
    path = os.path.join(SHOTS, "grid12_%s.png" % image_id)
    page.locator("#cards .card").nth(index).screenshot(path=path)
    page.evaluate("""(i) => {
        const n = document.querySelectorAll('#cards .card')[i]
            .querySelector('.card-name');
        n.textContent = n.dataset.keep;
    }""", index)
    with Image.open(path) as shot:
        crop = shot.convert("RGB").crop(
            (int(box[0] * DSF), int(box[1] * DSF),
             int((box[0] + box[2]) * DSF), int((box[1] + box[3]) * DSF)))
        levels = [luminance(p) for p in crop.convert("RGB").getdata()]
    os.remove(path)
    return min(contrast(v) for v in levels)


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
    # engine.js shuffles a pair unless the step opts out, and a shuffled
    # zodiac makes the reader scan all twelve for one they could point at.
    check("  in classical order, Aries to Pisces", names == ZODIAC, str(names))

    boxes = page.eval_on_selector_all("#cards .card", """ns => ns.map(n => {
        const r = n.getBoundingClientRect();
        return [Math.round(r.width), Math.round(r.height)];
    })""")
    smallest = min(min(b) for b in boxes)
    check("  every tap target clears 44px (smallest %dpx)" % smallest,
          smallest >= 44, smallest)
    bottom = page.evaluate(
        "document.querySelector('#cards').getBoundingClientRect().bottom")
    check("  and the twelfth cell is on screen, not below the fold",
          bottom <= 844, "%d of 844" % round(bottom))

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

    print("\n--- the label is readable on the frames that test it ---")
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
        check("  %-11s (%-9s) worst pixel %s"
              % (image_id, step,
                 ("%.1f:1" % got) if got else "not reached"),
              got is not None and got >= MIN_CONTRAST,
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
            page = browser.new_page(viewport={"width": 390, "height": 844},
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
