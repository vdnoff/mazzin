#!/usr/bin/env python3
"""The love funnel's three-up gender step, in a browser, at 390x844.

Whether three cells fit one row on a phone with the question above them,
whether the longest of the three names — "Предпочитам да не казвам" — is
read whole in a 112px cell, and whether the tap on the middle card is the
one the run records are facts about a layout engine and a running page, not
about JSON. Every one of them was a guess until this rendered.

The format is `grid3`, added to engine.js's GRID_SIZE for this step and
laid out by one block in mazzin.css. Nothing else names it, which the
config suite holds; what this holds is that the page draws what the format
promises.

    python3 tests/test_lovegrid3.py
"""
import http.server
import json
import os
import socketserver
import sys
import threading

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, REPO)

from playwright.sync_api import sync_playwright           # noqa: E402

ROOT = REPO
PORT = 8811
CHROME = "/opt/pw-browsers/chromium-1194/chrome-linux/chrome"
SLUG = "love-zodiac-bg"
ORDER = ["За жена", "За мъж", "Предпочитам да не казвам"]
IDS = ["g01", "g02", "g03"]

fails = []
checks = [0]
posted = []


def check(label, ok, detail=""):
    checks[0] += 1
    if not ok:
        fails.append("%s %s" % (label, detail))
    print("  %-58s %s%s" % (label, "ok" if ok else "FAIL",
                            ("  " + str(detail)) if not ok else ""))


class Handler(http.server.SimpleHTTPRequestHandler):
    """static/ off disk, /<slug> is the shell, APIs stubbed, POSTs kept."""

    def __init__(self, *a, **kw):
        super().__init__(*a, directory=ROOT, **kw)

    def log_message(self, *a):
        pass

    def do_GET(self):
        path = self.path.split("?")[0]
        if path.startswith("/api/"):
            return self._json({})
        if not path.startswith("/static/"):
            self.path = "/static/funnel.html"
        return super().do_GET()

    def do_POST(self):
        raw = self.rfile.read(int(self.headers.get("content-length") or 0))
        posted.append((self.path, raw.decode("utf-8", "replace")))
        self._json({"ok": True})

    def _json(self, body):
        raw = json.dumps(body).encode()
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(raw)))
        self.end_headers()
        self.wfile.write(raw)


# engine.js holds a chosen card on screen before the set leaves; nothing may
# be asserted about the next step until that has run.
HOLD_MS = 1650

CELLS = """() => {
  const wrap = document.querySelector('#cards');
  const cards = Array.from(document.querySelectorAll('#cards .card'));
  return {
    cls: wrap ? wrap.className : '',
    scrollW: document.documentElement.scrollWidth,
    innerW: window.innerWidth,
    cells: cards.map(c => {
      const b = c.getBoundingClientRect();
      const name = c.querySelector('.card-name');
      const img = c.querySelector('img');
      let label = null;
      if (name) {
        const cs = getComputedStyle(name);
        const nb = name.getBoundingClientRect();
        label = {text: name.textContent, fs: parseFloat(cs.fontSize),
                 lines: Math.round((nb.height - parseFloat(cs.paddingTop)
                        - parseFloat(cs.paddingBottom)) / parseFloat(cs.lineHeight)),
                 fits: name.scrollWidth <= name.clientWidth
                       && name.scrollHeight <= name.clientHeight,
                 inside: nb.left >= b.left - 0.5 && nb.right <= b.right + 0.5
                         && nb.bottom <= b.bottom + 0.5 && nb.top >= b.top,
                 w: nb.width, h: nb.height};
      }
      return {x: b.left, y: b.top, w: b.width, h: b.height,
              src: img ? img.getAttribute('src').split('/').pop() : '',
              loaded: img ? (img.complete && img.naturalWidth > 0) : false,
              chosen: c.classList.contains('is-chosen'), label: label};
    }),
    question: (document.querySelector('#question, .question, h2') || {}).textContent || ''
  };
}"""


def advance(page, index=0):
    """Tap one card and clear whatever stands between steps."""
    page.locator("#cards .card").nth(index).click()
    page.wait_for_timeout(HOLD_MS + 350)
    for _ in range(3):
        mid = page.locator("#screen-interstitial")
        if mid.count() and mid.is_visible():
            page.click("#mid-cta")
            page.wait_for_timeout(600)
        else:
            break


def run(page):
    print("\n--- the way there ---")
    page.goto("http://127.0.0.1:%d/%s" % (PORT, SLUG))
    page.wait_for_selector("#cards .card", timeout=20000)
    page.wait_for_timeout(500)
    info = page.evaluate(CELLS)
    check("the hook comes first, as a pair", len(info["cells"]) == 2
          and "is-grid" not in info["cls"], info["cls"])
    advance(page)
    info = page.evaluate(CELLS)
    check("then the sign grid, twelve up", len(info["cells"]) == 12
          and "is-grid12" in info["cls"], info["cls"])
    advance(page)
    page.wait_for_timeout(300)

    print("\n--- the three-up ---")
    info = page.evaluate(CELLS)
    cells = info["cells"]
    check("the third step draws three cells", len(cells) == 3, len(cells))
    check("  under the grid3 class and no other grid class",
          "is-grid3" in info["cls"]
          and not any("is-grid%d" % n in info["cls"] for n in (4, 6, 12)),
          info["cls"])
    check("  asking for whom the profile is",
          "За кого е този профил" in page.content())
    check("  the three frames are g01, g02, g03, in the approved order",
          [c["src"] for c in cells] == [i + ".webp" for i in IDS],
          str([c["src"] for c in cells]))
    check("  and all three decoded", all(c["loaded"] for c in cells))
    tops = {round(c["y"]) for c in cells}
    check("  in one row", len(tops) == 1, str(tops))
    widths = [round(c["w"]) for c in cells]
    heights = [round(c["h"]) for c in cells]
    check("  each cell about 112px across at 390 (%s)" % widths,
          all(100 <= w <= 125 for w in widths) and max(widths) - min(widths) <= 1)
    check("  and about 3:5 tall, the shape the frames are drawn for (%s)"
          % heights,
          all(1.55 <= h / w <= 1.8 for w, h in zip(widths, heights)))
    check("  every tap target clears 44px",
          all(min(c["w"], c["h"]) >= 44 for c in cells))
    check("  the third cell is on screen, not below the fold",
          all(c["y"] + c["h"] <= 844 for c in cells))
    check("  and the page does not scroll sideways",
          info["scrollW"] <= info["innerW"], info["scrollW"])
    names = [c["label"]["text"] if c["label"] else None for c in cells]
    check("  every cell is named, in the approved order", names == ORDER,
          str(names))
    check("  the badge type stepped down for the narrow cells",
          all(c["label"]["fs"] == 11 for c in cells),
          str([c["label"]["fs"] for c in cells]))
    check("  every name whole: nothing clipped, nothing outside its cell",
          all(c["label"]["fits"] and c["label"]["inside"] for c in cells),
          str([(c["label"]["text"], c["label"]["fits"], c["label"]["inside"])
               for c in cells]))
    lines = [c["label"]["lines"] for c in cells]
    check("  the two short names on one line, the long one on two, never "
          "three", lines == [1, 1, 2], str(lines))

    print("\n--- the tap ---")
    page.locator("#cards .card").nth(1).click()
    page.wait_for_timeout(400)
    info = page.evaluate(CELLS)
    check("the tapped card is marked chosen, and only it",
          [c["chosen"] for c in info["cells"]] == [False, True, False],
          str([c["chosen"] for c in info["cells"]]))
    tick = page.evaluate("""() => {
        const n = document.querySelectorAll('#cards .card')[1]
                    .querySelector('.card-name');
        return n ? getComputedStyle(n, '::after').content : '';
    }""")
    check("  with the tick inside its label, as on the sign grid",
          "2713" in tick or "✓" in tick, tick)
    page.wait_for_timeout(HOLD_MS + 350)
    for _ in range(3):
        mid = page.locator("#screen-interstitial")
        if mid.count() and mid.is_visible():
            page.click("#mid-cta")
            page.wait_for_timeout(600)
        else:
            break
    info = page.evaluate(CELLS)
    check("tapping advances the run to the evening pair",
          len(info["cells"]) == 2 and "is-grid" not in info["cls"],
          info["cls"])
    page.wait_for_timeout(800)
    tracked = [json.loads(body) for path, body in posted
               if path.startswith("/api/track")]
    swipes = [e for e in tracked if e.get("event") == "swipe"]
    gender = [e for e in swipes if e.get("step") == 3]
    check("  and the choice rides to /api/track as the third swipe",
          len(gender) == 1 and gender[0]["extra"]["chosen"] == "g02",
          str(gender))
    check("    like every other tap: pair named, the three shown, one chosen",
          gender and gender[0]["extra"]["pair"] == "gender:p1"
          and gender[0]["extra"]["shown"] == IDS
          and [e["step"] for e in swipes] == [1, 2, 3]
          and swipes[1]["extra"]["chosen"].startswith("sign_"))


socketserver.TCPServer.allow_reuse_address = True
httpd = socketserver.TCPServer(("127.0.0.1", PORT), Handler)
threading.Thread(target=httpd.serve_forever, daemon=True).start()
try:
    with sync_playwright() as pw:
        browser = pw.chromium.launch(executable_path=CHROME)
        page = browser.new_page(viewport={"width": 390, "height": 844},
                                device_scale_factor=2)
        run(page)
        browser.close()
finally:
    httpd.shutdown()

print("\n%d checks, %d failed" % (checks[0], len(fails)))
for f in fails:
    print("  FAIL " + f)
sys.exit(1 if fails else 0)
