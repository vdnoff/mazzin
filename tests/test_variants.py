#!/usr/bin/env python3
"""The variant mechanism, and the live funnel it is now switched on for.

zodiac30 takes real money. It has an A/B arm now — a second way of laying the
result page out — and the property that matters more than the test itself is
that a reader who is not in that arm sees the page they have always seen.

Three things are checked here and none of them can be checked from one file.

The mechanism is duplicated, on purpose, and the duplication has to be exact.
engine.js loads one module per funnel (`loadAsset(cfg.result_module)`), so a
shared assignment file would have to be required from the shell every funnel
loads — including this one. Copying it into the zodiac module instead touches
nothing else; the cost is two copies, and this is what keeps them one.

The control arm renders the old page. Not "a page with the same parts" — the
same DOM, in the same order, which is what `--minimal` must not disturb.

And nothing in the mechanism knows what funnel it is in, because the next
funnel to adopt it should need a config edit and nothing else.

    python3 tests/test_variants.py
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

from playwright.sync_api import sync_playwright           # noqa: E402

PORT = 8785
CHROME = "/opt/pw-browsers/chromium-1194/chrome-linux/chrome"
PERSONA = open(os.path.join(REPO, "static/js/result_persona.js"),
               encoding="utf-8").read()
ZODIAC = open(os.path.join(REPO, "static/js/result_zodiac.js"),
              encoding="utf-8").read()
Z30 = json.load(open(os.path.join(REPO, "funnels/zodiac30.json"),
                     encoding="utf-8"))

fails = []
checks = [0]


def check(label, ok, detail=""):
    checks[0] += 1
    if not ok:
        fails.append("%s %s" % (label, detail))
    print("  %-62s %s%s" % (label, "ok" if ok else "FAIL",
                            ("  " + str(detail)) if not ok else ""))


def mechanism(src):
    """The assignment block, from the session key to the marker after it.

    The end marker is searched for AFTER the start rather than from the top of
    the file: the two modules carry these blocks in different orders, and a
    plain `index` found the zodiac module's reporter first and returned an
    empty slice — which compares equal to nothing and would have passed as
    "no mechanism" rather than failing as "not the same one".
    """
    start = src.index("  // engine.js's own session key.")
    end = src.index("  // One event, once, when the offer is drawn", start)
    block = src[start:end]
    assert block.strip(), "empty mechanism slice"
    return block


print("--- one mechanism, two copies ---")
mine, theirs = mechanism(PERSONA), mechanism(ZODIAC)
check("both modules carry it", bool(mine) and bool(theirs))
check("  character for character", mine == theirs,
      "%d vs %d chars" % (len(mine), len(theirs)))
for name in ("variantWeight", "variantPool", "sessionKey", "hashOf",
             "assignedVariant"):
    check("  including %s" % name,
          ("function %s(" % name) in mine
          and ("function %s(" % name) in theirs)
# Code, not prose: the comments explain why the URL must not be read, and a
# scan that cannot tell a rule from its explanation fails on the explanation.
code = re.sub(r"//[^\n]*", "", re.sub(r"/\*.*?\*/", "", mine, flags=re.S))
check("no funnel knows its own name in it",
      not re.search(r"persona|zodiac|kitchen", code, re.I),
      str(re.findall(r"persona|zodiac|kitchen", code, re.I)[:3]))
check("  and assignment reads the session, never the URL",
      "mazzin_sid" in mine
      and not re.search(r"location|URLSearchParams|subid|utm_", code))
report = PERSONA[PERSONA.index("  // One event, once"):
                 PERSONA.index("  // The offer's own copy")]
check("  the arm is reported the same way from both",
      report in ZODIAC)


print("\n--- the layout flag ---")
variants = Z30["paywall_variants"]
check("zodiac30 declares two arms", len(variants) == 2,
      str([v["id"] for v in variants]))
control = next((v for v in variants if v["id"] == "control"), None)
minimal = next((v for v in variants if v["id"] == "minimal"), None)
check("  a control that names no template",
      control is not None and "template" not in control)
check("  and an arm that names one",
      minimal is not None and minimal.get("template") == "minimal")
check("  both enabled and evenly weighted",
      all(v["enabled"] is True and v["weight"] == 1 for v in variants))
check("the flag is optional, so every other funnel is unaffected",
      'var template = (variant && variant.template) || "";' in ZODIAC)
check("  the old page is what a missing template renders",
      re.search(r'if \(data && template === "minimal"\) \{', ZODIAC)
      is not None
      and re.search(r'\} else if \(data\) \{', ZODIAC) is not None)
check("  and the flag is read before the hero that branches on it",
      ZODIAC.index("var template = (variant") <
      ZODIAC.index("{ lean: template ==="))
for slug in ("zodiac", "kitchen", "zodiac-ro"):
    other = json.load(open(os.path.join(REPO, "funnels", slug + ".json"),
                           encoding="utf-8"))
    check("  %s was given none" % slug, not other.get("paywall_variants"))


print("\n--- the control arm is the page it always was ---")


class Handler(http.server.SimpleHTTPRequestHandler):
    def __init__(self, *a, **kw):
        super().__init__(*a, directory=REPO, **kw)

    def log_message(self, *a):
        pass

    def do_GET(self):
        path = self.path.split("?")[0]
        if path == "/api/pixel-config":
            return self._json({})
        if path == "/api/report":
            return self._json({"complete": False, "report": None})
        if path == "/zodiac30":
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


LAID = ("() => { const c=document.querySelector('#screen-swipe #cards .card');"
        " return !!c && c.getBoundingClientRect().width>1; }")
SETTLED = ("() => [...document.querySelectorAll('#screen-swipe #cards .card')]"
           ".every(c=>{const t=getComputedStyle(c).transform;"
           " return t==='none'||/matrix\\(1, 0, 0, 1/.test(t);})")


def hashed(text):
    """The module's own FNV-1a, so the suite picks the same arm it does."""
    value = 0x811c9dc5
    for ch in text:
        value ^= ord(ch)
        value = (value + ((value << 1) + (value << 4) + (value << 7)
                          + (value << 8) + (value << 24))) & 0xFFFFFFFF
    return value


def arm_for(sid):
    pool = [v for v in Z30["paywall_variants"] if v.get("enabled") is not False]
    total = sum(v.get("weight", 1) for v in pool)
    point = (hashed(sid) % 100000) / 100000.0 * total
    seen = 0
    for v in pool:
        seen += v.get("weight", 1)
        if point < seen:
            return v["id"]
    return pool[-1]["id"]


def shape_for(page, sid):
    page.add_init_script(
        "try{sessionStorage.setItem('mazzin_sid',%s);}catch(e){}"
        % json.dumps(sid))
    page.goto("http://127.0.0.1:%d/zodiac30" % PORT)
    page.wait_for_selector("#screen-swipe #cards .card", timeout=20000)
    for _ in range(len(Z30["swipe"]["steps"]) + 8):
        if page.locator("#screen-result.is-active").count():
            break
        try:
            page.wait_for_function(LAID, timeout=6000)
            page.wait_for_function(SETTLED, timeout=3000)
        except Exception:
            mid = page.locator("#mid-cta:visible")
            if mid.count():
                mid.click()
                page.wait_for_timeout(600)
            else:
                page.wait_for_timeout(800)
            continue
        try:
            page.locator("#screen-swipe #cards .card").first.click(timeout=6000)
        except Exception:
            page.wait_for_timeout(700)
            continue
        page.wait_for_timeout(1900)
    page.wait_for_selector("#result-module", timeout=25000)
    page.wait_for_timeout(1100)
    return page.evaluate(
        "() => [...document.querySelector('#result-module').children]"
        ".map(n => n.className)")


# The page every reader outside the test sees. Pinned as a literal because
# "unchanged" is the requirement — a node added to it is a change to a live
# funnel whether or not anybody meant one.
CONTROL_SHAPE = ["zr-kicker", "zr-hero is-rich", "zr-taps", "zr-free",
                 "zr-bridge", "zr-cards", "zr-offer"]

sids = {}
for n in range(4000):
    sid = "a1b2c3d4-0000-4000-8000-%012d" % n
    sids.setdefault(arm_for(sid), sid)
    if len(sids) == 2:
        break
check("both arms are reachable", set(sids) == {"control", "minimal"},
      str(sorted(sids)))

socketserver.TCPServer.allow_reuse_address = True
httpd = socketserver.TCPServer(("127.0.0.1", PORT), Handler)
threading.Thread(target=httpd.serve_forever, daemon=True).start()
try:
    with sync_playwright() as pw:
        browser = pw.chromium.launch(executable_path=CHROME)
        errors = []
        page = browser.new_page(viewport={"width": 390, "height": 844})
        page.on("pageerror", lambda e: errors.append(str(e)))
        control_shape = shape_for(page, sids["control"])
        page.close()
        page = browser.new_page(viewport={"width": 390, "height": 844})
        page.on("pageerror", lambda e: errors.append(str(e)))
        minimal_shape = shape_for(page, sids["minimal"])
        page.close()
        browser.close()
finally:
    httpd.shutdown()

check("it renders without a script error", not errors, str(errors[:2]))
check("the control arm draws the page it always drew",
      control_shape == CONTROL_SHAPE, str(control_shape))
check("  which still carries the six locked cards above the offer",
      "zr-cards" in control_shape and "zr-bridge" in control_shape)
check("the minimal arm draws a different page",
      minimal_shape != control_shape)
check("  without the card list", "zr-cards" not in minimal_shape)
check("  or the bridge line", "zr-bridge" not in minimal_shape)
check("  with the rarity given its own weight",
      "zr-rarity" in minimal_shape, str(minimal_shape))
check("  and the offer still last",
      minimal_shape[-1] == "zr-offer" and control_shape[-1] == "zr-offer")
check("  the hero and the contact sheet are common to both",
      minimal_shape[:3] == control_shape[:3])

print("\n%d checks, %d failed" % (checks[0], len(fails)))
for line in fails:
    print("  FAIL   %s" % line)
sys.exit(1 if fails else 0)
