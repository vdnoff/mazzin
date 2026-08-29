#!/usr/bin/env python3
"""Persona tiles in a browser: no card may paint over another.

The four-up briefly carried an image zone pinned to the render's own 3:4.
Every measurement taken of it was taken at an 844px viewport and every one
of them was clean, because at 844 it fits. No phone is 844px tall in the
part you can see. At the 650-730 a browser actually leaves, the tiles came
out taller than the tracks the grid had stretched to a definite container
height, `align-items: start` parked each one at the top of its track, and
row two was painted over by row one — 47px of it at 390x664, with the hint
pushed underneath both rows.

What made that invisible was the shape of the measuring, not the shape of
the tile: every earlier check read one card at a time and asked whether it
was cropped. A card cannot overlap itself. So this suite reads the cards
together and compares them with each other, at the heights a phone has.

    python3 test_personatiles.py
"""
import http.server
import json
import os
import socketserver
import sys
import threading

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from playwright.sync_api import sync_playwright          # noqa: E402

ROOT = REPO
PORT = 8753
CHROME = "/opt/pw-browsers/chromium-1194/chrome-linux/chrome"

CFG = json.load(open(os.path.join(ROOT, "funnels/persona.json")))
STEPS = CFG["swipe"]["steps"]

# Width by the height the viewport actually has once the browser has taken
# its share. The last is the no-chrome ideal, kept because it is the one the
# capped build was measured at: it has to keep passing, but on its own it
# proves nothing about a phone.
VIEWPORTS = ((360, 640), (390, 664), (430, 715), (390, 844))

fails = []
checks = [0]


def check(label, ok, detail=""):
    checks[0] += 1
    if not ok:
        fails.append("%s %s" % (label, detail))
    print("  %-64s %s%s" % (label, "ok" if ok else "FAIL",
                            ("  " + str(detail)) if not ok else ""))


class Handler(http.server.SimpleHTTPRequestHandler):
    def __init__(self, *a, **kw):
        super().__init__(*a, directory=ROOT, **kw)

    def log_message(self, *a):
        pass

    def do_GET(self):
        path = self.path.split("?")[0]
        if path == "/api/pixel-config":
            return self._json({})
        if path == "/persona":
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


# Read the cards as a set, with the hint, in one go. A card mid-transition is
# scaled 1.05 and would report a size it is not going to keep, so the caller
# waits for the transforms to settle before asking.
PROBE = """() => {
  const row = document.querySelector('#screen-swipe .cards');
  const cards = [...document.querySelectorAll('#screen-swipe .card')];
  const box = e => { const b = e.getBoundingClientRect();
    return {l: b.left, t: b.top, r: b.right, b: b.bottom,
            w: b.width, h: b.height}; };
  const hint = document.querySelector(
    '#screen-swipe .hint, #screen-swipe .swipe-hint, #screen-swipe .tap-hint');
  return {
    fmt: row ? row.className : '',
    vh: innerHeight,
    cards: cards.map(box),
    hint: hint ? box(hint) : null,
  };
}"""

LAID_OUT = ("() => { const c = document.querySelector('#screen-swipe .card');"
            " return !!c && c.getBoundingClientRect().width > 1; }")

SETTLED = ("() => [...document.querySelectorAll('#screen-swipe .card')]"
           ".every(c => { const t = getComputedStyle(c).transform;"
           " return t === 'none' || /matrix\\(1, 0, 0, 1/.test(t); })")


def overlap(a, b):
    """Height of the intersection of two card boxes, 0 if they do not touch."""
    wide = min(a["r"], b["r"]) - max(a["l"], b["l"])
    tall = min(a["b"], b["b"]) - max(a["t"], b["t"])
    return round(tall) if wide > 0.5 and tall > 0.5 else 0


socketserver.TCPServer.allow_reuse_address = True
httpd = socketserver.TCPServer(("127.0.0.1", PORT), Handler)
threading.Thread(target=httpd.serve_forever, daemon=True).start()

worst_overlap = {}
worst_gap = {}
seen = {"grid4": 0, "pair": 0}

with sync_playwright() as pw:
    browser = pw.chromium.launch(executable_path=CHROME)
    for width, height in VIEWPORTS:
        page = browser.new_page(viewport={"width": width, "height": height},
                                device_scale_factor=2)
        page.goto("http://127.0.0.1:%d/persona" % PORT)
        measured = 0
        page.wait_for_selector("#screen-swipe .card", timeout=15000)
        page.wait_for_timeout(600)
        for _ in range(len(STEPS) * 3):
            # Between steps the row is briefly present but zero-sized, and a
            # walk that treats that as the end of the funnel measures three
            # steps and reports a clean sweep. Wait for real geometry, then
            # for the transforms to settle.
            try:
                page.wait_for_function(LAID_OUT, timeout=2500)
                page.wait_for_function(SETTLED, timeout=2500)
            except Exception:
                pass
            data = page.evaluate(PROBE)
            cards = data["cards"]
            if not cards:
                break
            if not cards[0]["w"]:
                page.wait_for_timeout(400)
                continue
            fmt = "grid4" if "is-grid4" in data["fmt"] else "pair"
            seen[fmt] += 1
            measured += 1
            print("    %dx%d step %d %s %dx%d"
                  % (width, height, measured, fmt, round(cards[0]["w"]),
                     round(cards[0]["h"])), flush=True)
            key = "%dx%d" % (width, height)
            for i in range(len(cards)):
                for j in range(i + 1, len(cards)):
                    hit = overlap(cards[i], cards[j])
                    if hit > worst_overlap.get(key, 0):
                        worst_overlap[key] = hit
            if data["hint"]:
                gap = round(data["hint"]["t"] - max(c["b"] for c in cards))
                if key not in worst_gap or gap < worst_gap[key]:
                    worst_gap[key] = gap
                if data["hint"]["b"] > data["vh"]:
                    worst_gap[key] = min(worst_gap[key], -9999)
            page.locator("#screen-swipe .card").first.click()
            page.wait_for_timeout(700)
            if not page.locator("#screen-swipe .card").count():
                page.wait_for_timeout(1500)
                if not page.locator("#screen-swipe .card").count():
                    break
            if measured >= len(STEPS):
                break
        page.close()
    browser.close()
httpd.shutdown()

print("\nno card paints over another")
for width, height in VIEWPORTS:
    key = "%dx%d" % (width, height)
    check("  %s: cards are disjoint" % key,
          worst_overlap.get(key, 0) == 0,
          "%dpx of overlap" % worst_overlap.get(key, 0))

print("\nthe hint sits below the last row, on screen")
for width, height in VIEWPORTS:
    key = "%dx%d" % (width, height)
    gap = worst_gap.get(key)
    check("  %s: clear of the cards" % key, gap is not None and gap >= 0,
          "hint runs off the bottom" if gap == -9999 else
          ("%spx" % gap if gap is not None else "no hint found"))

print("\nand it walked enough of the funnel to mean something")
check("  four-up steps measured", seen["grid4"] >= 6 * len(VIEWPORTS),
      str(seen["grid4"]))
check("  two-up steps measured", seen["pair"] >= 3 * len(VIEWPORTS),
      str(seen["pair"]))

print("\n%d checks, %d failed" % (checks[0], len(fails)))
for line in fails:
    print("  FAIL   %s" % line)
sys.exit(1 if fails else 0)
