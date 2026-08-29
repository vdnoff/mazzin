#!/usr/bin/env python3
"""The persona offer: which arm a session gets, and what the button says.

Two things here cannot be checked from the config, and one of them is the
whole reason this file exists.

The assignment. It is real shipped code, sliced out of result_persona.js by
name and run as itself — not a copy of the algorithm rewritten in Python,
which would pass while the module did something else. What it has to do:
give one session the same arm every time, honour the weights, never assign a
disabled arm, redistribute a disabled arm's share without anybody restating
the remaining weights, and render unconditionally when only one arm is left.

The button. Its label belongs to engine.js — `updatePayButton` writes
`payButton.textContent` from `cfg.checkout.cta_label`, and `renderCommerce`
runs before any module renders. So result_persona.js writes what engine.js
reads and then asks it to read again. If that ordering ever changes, the card
argues one offer and the button offers another, and nothing about the written
config would look wrong. That is why the check below reads the button's
VISIBLE TEXT off the rendered page rather than the value that was written.

    python3 tests/test_personaoffer.py
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

import database                                           # noqa: E402

# No suite talks to a database. `start_report` builds the delivered content
# and writes a row; the content is what this file wants and the row is not.
database.execute = lambda *a, **kw: None
database.query_all = lambda *a, **kw: []
database.query_one = lambda *a, **kw: None

import reports                                            # noqa: E402
from playwright.sync_api import sync_playwright           # noqa: E402

PORT = 8759
CHROME = "/opt/pw-browsers/chromium-1194/chrome-linux/chrome"
HOLD_MS = 1650

CFG = json.load(open(os.path.join(REPO, "funnels/persona.json"),
                     encoding="utf-8"))
VARIANTS = CFG["paywall_variants"]
MODULE = open(os.path.join(REPO, "static/js/result_persona.js"),
              encoding="utf-8").read()

fails = []
checks = [0]
POSTED = []


def check(label, ok, detail=""):
    checks[0] += 1
    if not ok:
        fails.append("%s %s" % (label, detail))
    print("  %-62s %s%s" % (label, "ok" if ok else "FAIL",
                            ("  " + str(detail)) if not ok else ""))


# The mechanism, as it ships. Sliced from the session key it reads to the
# event it does not — everything the assignment needs and nothing that touches
# the DOM. Taken by name so that renaming a function here breaks this suite
# rather than silently testing an empty string.
def mechanism_source():
    start = MODULE.index("  var SESSION_KEY =")
    end = MODULE.index("  // One event, once, when the offer is drawn")
    slice_ = MODULE[start:end]
    for name in ("variantWeight", "variantPool", "sessionKey", "hashOf",
                 "assignedVariant"):
        if ("function %s(" % name) not in slice_:
            raise SystemExit("mechanism slice lost %s" % name)
    return slice_


HARNESS = """(source) => {
  const make = new Function(source + `
    return { assignedVariant: assignedVariant, variantPool: variantPool };
  `);
  const api = make();
  window.__vary = (cfg, sid) => {
    try { window.sessionStorage.setItem('mazzin_sid', sid); } catch (e) {}
    const picked = api.assignedVariant(cfg);
    return picked ? picked.id : null;
  };
  window.__pool = cfg => api.variantPool(cfg).map(v => v.id);
  return true;
}"""


def arm(page, cfg, sid):
    return page.evaluate("([c, s]) => window.__vary(c, s)", [cfg, sid])


def variants(**over):
    """The shipped list, with one field overridden per id."""
    out = json.loads(json.dumps(VARIANTS))
    for row in out:
        for key, value in (over.get(row["id"]) or {}).items():
            row[key] = value
    return {"paywall_variants": out}


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
            # Only once the suite says a purchase exists. Answering this on
            # the free page would hand engine.js a finished report before the
            # quiz had been walked, and the page under test would never be
            # drawn at all.
            if not DELIVER[0]:
                return self._json({"complete": False, "report": None})
            return self._json({
                "complete": True, "email_masked": "s***@x.com",
                "report": reports.delivered_content(REPORT[0],
                                                    "buyer@example.com")})
        if path in ("/persona", "/zodiac30"):
            self.path = "/static/funnel.html"
        return super().do_GET()

    def do_POST(self):
        raw = self.rfile.read(int(self.headers.get("content-length") or 0))
        try:
            POSTED.append((self.path.split("?")[0], json.loads(raw or b"{}")))
        except ValueError:
            POSTED.append((self.path.split("?")[0], {}))
        if self.path.split("?")[0] == "/api/checkout":
            return self._json({"url": "http://127.0.0.1:%d/stubbed" % PORT})
        self._json({"ok": True})

    def _json(self, body):
        raw = json.dumps(body).encode()
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(raw)))
        self.end_headers()
        self.wfile.write(raw)


def stub_report():
    choices = []
    for step in CFG["swipe"]["steps"]:
        pair = step["pairs"][0]
        choices.append(pair["images"][0]["id"])
    style_id = CFG["styles"][0]["id"]
    # The same scores a real run produces, so `_persona_profile` resolves a
    # persona rather than returning None and sending the page to the plain
    # card. A stub that skipped this would be testing the fallback.
    scores = dict((tag, 9) for tag in (CFG["styles"][0].get("tags") or []))
    scores.update({"outer": 8, "inner": 3, "bold": 5, "calm": 3, "deep": 4,
                   "drive": 7, "anchor": 4, "wave": 5, "prism": 2})
    content = reports.start_report(1, "persona", style_id, scores,
                                   choices=choices)
    content["version"] = "llm-2"
    return content


REPORT = [None]
DELIVER = [False]


# A card is clickable when it has real geometry and has stopped moving. The
# chosen card of the previous step is still in the document, scaled and on its
# way out, and a walk that reaches for `.first` without these two waits keeps
# resolving to it and then failing because it is no longer visible.
LAID_OUT = ("() => { const c = document.querySelector('#screen-swipe #cards .card');"
            " return !!c && c.getBoundingClientRect().width > 1; }")
SETTLED = ("() => [...document.querySelectorAll('#screen-swipe #cards .card')]"
           ".every(c => { const t = getComputedStyle(c).transform;"
           " return t === 'none' || /matrix\\(1, 0, 0, 1/.test(t); })")


def walk(page):
    """Tap the first card through to the result.

    Persona's beat between steps carries no visible continue button — the one
    in the shell stays hidden on this funnel — so the walk waits for a card
    that is laid out and settled rather than for a screen to be named.
    """
    for _ in range(len(CFG["swipe"]["steps"]) + 6):
        if page.locator("#screen-result.is-active").count():
            return
        try:
            page.wait_for_function(LAID_OUT, timeout=6000)
            page.wait_for_function(SETTLED, timeout=4000)
        except Exception:
            mid = page.locator("#mid-cta:visible")
            if mid.count():
                mid.click()
                page.wait_for_timeout(650)
            else:
                page.wait_for_timeout(900)
            continue
        try:
            page.locator("#screen-swipe #cards .card").first.click(timeout=6000)
        except Exception:
            page.wait_for_timeout(700)
            continue
        page.wait_for_timeout(HOLD_MS + 250)


def price_of(page):
    return page.evaluate(
        "() => (document.querySelector('.pr-price-now') || {}).textContent")


def run_mechanism(page):
    print("\n--- the assignment ---")
    page.goto("http://127.0.0.1:%d/static/funnel.html" % PORT)
    page.evaluate(HARNESS, mechanism_source())
    both = variants()

    ids = ["a1b2c3d4-0000-4000-8000-00000000%04d" % n for n in range(400)]
    picks = [arm(page, both, sid) for sid in ids]
    check("every session gets one of the enabled arms",
          set(picks) <= {v["id"] for v in VARIANTS} and None not in picks,
          str(sorted(set(picks))))
    again = [arm(page, both, sid) for sid in ids]
    check("  and the same one when asked again",
          again == picks, "%d of %d differed"
          % (sum(1 for a, b in zip(again, picks) if a != b), len(picks)))

    share = picks.count("why") / float(len(picks))
    check("  two equal weights split about evenly",
          0.4 <= share <= 0.6, "%.2f to 'why'" % share)

    heavy = variants(why={"weight": 3})
    heavy_share = ([arm(page, heavy, sid) for sid in ids].count("why")
                   / float(len(ids)))
    check("  and an arm weighted 3:1 takes about three quarters",
          0.65 <= heavy_share <= 0.85, "%.2f" % heavy_share)

    print("\n--- turning an arm off is a config edit ---")
    off = variants(why={"enabled": False})
    check("a disabled arm is never assigned",
          set(arm(page, off, sid) for sid in ids) == {"advantage"},
          str(sorted(set(arm(page, off, sid) for sid in ids))))
    check("  and is not in the pool at all",
          page.evaluate("c => window.__pool(c)", off) == ["advantage"])
    check("  the one left renders unconditionally, whatever it weighs",
          set(arm(page, variants(why={"enabled": False},
                                 advantage={"weight": 0.001}), sid)
              for sid in ids) == {"advantage"})
    zeroed = variants(why={"weight": 0})
    check("  a zero weight is the same intent, written differently",
          set(arm(page, zeroed, sid) for sid in ids) == {"advantage"})

    # Renormalisation: a third arm, then that third arm turned off. The two
    # survivors must come back to their own ratio without anybody restating
    # their weights.
    three = json.loads(json.dumps(VARIANTS))
    three.append({"id": "third", "enabled": True, "weight": 2,
                  "name": "n", "frame": "f", "benefits": ["b"],
                  "cta_text": "c {price}"})
    with_third = {"paywall_variants": three}
    third_share = ([arm(page, with_third, sid) for sid in ids].count("third")
                   / float(len(ids)))
    check("a third arm added in config alone takes its share",
          0.4 <= third_share <= 0.6, "%.2f" % third_share)
    dropped = json.loads(json.dumps(three))
    dropped[2]["enabled"] = False
    back = [arm(page, {"paywall_variants": dropped}, sid) for sid in ids]
    check("  and turning it off hands that share back, renormalised",
          back == picks,
          "%d of %d differ from the two-arm assignment"
          % (sum(1 for a, b in zip(back, picks) if a != b), len(picks)))

    check("a funnel with no variants gets none",
          arm(page, {}, ids[0]) is None)
    return picks[0], ids[0]


def run_free(page, sid):
    print("\n--- the offer the reader sees ---")
    errors = []
    page.on("pageerror", lambda e: errors.append(str(e)))
    # Seeded before anything runs, so engine.js reads the id this suite chose
    # rather than minting its own. A goto-then-reload would work too, and did,
    # right up until the reload landed on a page mid-transition.
    page.add_init_script(
        "try { sessionStorage.setItem('mazzin_sid', %s); } catch (e) {}"
        % json.dumps(sid))
    page.goto("http://127.0.0.1:%d/persona" % PORT)
    page.wait_for_selector("#screen-swipe #cards .card", timeout=20000)
    walk(page)
    page.wait_for_selector("#result-module", timeout=25000)
    page.wait_for_timeout(1200)
    check("the result renders without a script error", not errors, str(errors))

    shown = page.get_attribute(".pr-variant", "data-variant")
    # The page's own choice, against the mechanism's, for the same session id.
    # Two routes to the same answer: if they part, one of them is lying.
    page.evaluate(HARNESS, mechanism_source())
    predicted = page.evaluate("([c, s]) => window.__vary(c, s)",
                              [variants(), sid])
    check("the rendered arm is the one the mechanism assigns",
          shown == predicted, "%s vs %s" % (shown, predicted))
    picked = [v for v in VARIANTS if v["id"] == shown]
    check("an arm was drawn, and it is one of the config's",
          len(picked) == 1, str(shown))
    if not picked:
        return shown
    variant = picked[0]
    check("  its name and frame are on the card",
          page.inner_text(".pr-variant-name").strip() == variant["name"]
          and page.inner_text(".pr-variant-frame").strip() == variant["frame"])
    lines = page.eval_on_selector_all(
        ".pr-variant-benefit", "ns => ns.map(n => n.innerText.trim())")
    check("  all five benefits, in order",
          lines == variant["benefits"], str(lines[:2]))

    # The house rule, read off the page rather than off the source.
    order = page.evaluate("""() => {
      const b = document.querySelector('.pr-variant-benefits');
      const p = document.querySelector('.pr-offer .cta, .pr-offer button');
      if (!b || !p) return null;
      return b.compareDocumentPosition(p) & Node.DOCUMENT_POSITION_FOLLOWING
        ? 'benefits first' : 'button first';
    }""")
    check("  and they sit above the button", order == "benefits first",
          str(order))

    # The hard one: what the button actually says.
    price = price_of(page)
    want = variant["cta_text"].replace("{price}", price or "")
    label = page.inner_text(".pr-offer .cta").strip()
    check("the button's visible text is this arm's call to action",
          label == want, "%r, wanted %r" % (label, want))

    print("\n--- what the free page gives away ---")
    # The head and the radar pressed into it are the reveal the report sells,
    # so the free page must not carry them. Everything that teases stays.
    check("the totem stands alone", page.locator(".pr-solo").count() == 1)
    check("  no clay head", page.locator(".pr-head-plate").count() == 0)
    check("  no radar inlay", page.locator(".pr-head-inlay").count() == 0)
    check("  no trait legend", page.locator(".pr-head-legend").count() == 0)
    check("  but the four bars stay", page.locator(".pr-trait").count() >= 4,
          str(page.locator(".pr-trait").count()))
    check("  and the share button where it was",
          page.locator(".pr-share").count() >= 1)

    print("\n--- the arm is reported once ---")
    armed = [b for p, b in POSTED
             if p == "/api/track" and b.get("event") == "paywall_variant"]
    check("one paywall_variant event", len(armed) == 1, str(len(armed)))
    if armed:
        check("  naming the arm that was drawn",
              (armed[0].get("extra") or {}).get("variant") == shown,
              str(armed[0].get("extra")))
        check("  on the same session the rest of the events carry",
              armed[0].get("session_id") == sid, str(armed[0].get("session_id")))
    return shown


def run_delivered(page, shown, sid):
    print("\n--- the page the buyer opens ---")
    errors = []
    page.on("pageerror", lambda e: errors.append(str(e)))
    before = len([1 for p, b in POSTED
                  if p == "/api/track" and b.get("event") == "paywall_variant"])
    DELIVER[0] = True
    page.goto("http://127.0.0.1:%d/persona?cs=cs_test_1" % PORT)
    page.wait_for_selector("#result-module.is-delivered", timeout=25000)
    page.wait_for_timeout(900)
    check("it renders without a script error", not errors, str(errors))
    print("      delivered card drew: %s"
          % page.evaluate("""() => {
              const r = document.querySelector('#result-module');
              return r ? [...r.querySelectorAll('section, h1')]
                .slice(0, 4).map(n => n.className || n.tagName).join(' | ')
                : 'none'; }"""))
    # The reveal, on the page that paid for it. This is drawn from the block
    # reports.py stores at purchase — `_persona_profile` — so a delivered page
    # without a head means the block was not written, not that the module
    # forgot to draw it.
    check("the head is the first thing in it",
          page.locator(".pr-head-plate").count() == 1)
    check("  with its radar inlay",
          page.locator(".pr-head-inlay").count() == 1)
    check("  and the trait legend under it",
          page.locator(".pr-head-legend").count() == 1)
    check("  the totem beside it, not alone",
          page.locator(".pr-pair").count() == 1
          and page.locator(".pr-solo").count() == 0)
    check("  and it is the rich card, not the plain fallback",
          page.locator(".pr-hero.is-rich").count() == 1
          and page.locator(".pr-animal").count() == 0)
    order = page.evaluate("""() => {
      const h = document.querySelector('.pr-head-plate');
      const s = document.querySelector('.pr-path');
      if (!h || !s) return null;
      return h.compareDocumentPosition(s) & Node.DOCUMENT_POSITION_FOLLOWING
        ? 'head first' : 'sections first';
    }""")
    check("  above every section", order == "head first", str(order))

    check("there is no offer on it", page.locator(".pr-offer").count() == 0)
    check("  and so no second button to disagree with the first",
          page.locator(".pr-offer .cta").count() == 0)
    check("  and no variant block", page.locator(".pr-variant").count() == 0)
    after = len([1 for p, b in POSTED
                 if p == "/api/track" and b.get("event") == "paywall_variant"])
    check("  and the arm is not reported a second time", after == before,
          "%d -> %d" % (before, after))


def main():
    REPORT[0] = stub_report()
    socketserver.TCPServer.allow_reuse_address = True
    httpd = socketserver.TCPServer(("127.0.0.1", PORT), Handler)
    threading.Thread(target=httpd.serve_forever, daemon=True).start()
    try:
        with sync_playwright() as pw:
            browser = pw.chromium.launch(executable_path=CHROME)
            page = browser.new_page(viewport={"width": 390, "height": 844})
            _, sid = run_mechanism(page)
            page.close()
            page = browser.new_page(viewport={"width": 390, "height": 844})
            shown = run_free(page, sid)
            run_delivered(page, shown, sid)
            browser.close()
    finally:
        httpd.shutdown()

    print("\n%d checks, %d failed" % (checks[0], len(fails)))
    for line in fails:
        print("  FAIL   %s" % line)
    return 1 if fails else 0


if __name__ == "__main__":
    sys.exit(main())
