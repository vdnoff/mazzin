#!/usr/bin/env python3
"""The minimal result template, generalized — and the zodiac pages unmoved.

result_zodiac.js draws the "minimal" page for every funnel that names it.
It used to need a zodiac table (`result_copy.profile.subtypes`, read on
elements, signs and energies) to draw its rich card at all; a config with
none of that got the plain hero and the constellation path. Now a config may
declare a generic table instead — a split over its own tags, scales between
tag sets, a step for the badge — and gets the same card, the taps strip, the
locked chapters as teaser boxes fed from report.sections, and the offer with
its checklist. /blinds is the first funnel on it.

Two claims, and the second is the one that matters:

  1. the blinds page is the zodiac30 page, node for node in structure, with
     the buyer's-guide words in it — free and paid;
  2. every zodiac funnel renders EXACTLY what it rendered before this change.
     Free page and paid page, four funnels, compared byte for byte against
     fixtures recorded from main before the module was touched, with the
     same seeded random and pinned clock tests/test_variants.py uses.

Re-recording is a deliberate act, never a failing run's own doing:

    MAZZIN_RECORD_MINIMAL=1 python3 tests/test_minimal_generic.py

No database, no network, no key: reports are built on stubs.
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
ROOT = REPO
FIXTURES = os.path.join(REPO, "tests", "fixtures")

import config                                   # noqa: E402
import database                                 # noqa: E402
import reports                                  # noqa: E402

config.ANTHROPIC_API_KEY = ""
database.execute = lambda q, p=None: 1
database.query_one = lambda q, p=None: None
database.query_all = lambda q, p=None: []

from playwright.sync_api import sync_playwright  # noqa: E402

PORT = 8813
CHROME = "/opt/pw-browsers/chromium-1194/chrome-linux/chrome"
ZODIAC = ["zodiac30", "zodiac-ro", "zodiac-bg", "love-zodiac-bg"]
STYLE = {"zodiac30": "deep_water", "zodiac-ro": "deep_water",
         "zodiac-bg": "deep_water", "love-zodiac-bg": None,
         "blinds": "warm_scandi"}
PINNED = "2026-09-15T12:00:00Z"
CLOCK = """(() => { const AT = Date.parse(%s); const Real = Date;
  class Stub extends Real {
    constructor(...a) { super(...(a.length ? a : [AT])); }
    static now() { return AT; } }
  window.Date = Stub; })();""" % json.dumps(PINNED)
SEED = """(() => { let s = 0x2f6e2b1;
  Math.random = () => { s |= 0; s = (s + 0x6D2B79F5) | 0;
    let t = Math.imul(s ^ (s >>> 15), 1 | s);
    t = (t + Math.imul(t ^ (t >>> 7), 61 | t)) ^ t;
    return ((t ^ (t >>> 14)) >>> 0) / 4294967296; }; })();"""
LAID = ("() => { const c=document.querySelector('#screen-swipe #cards .card');"
        " return !!c && c.getBoundingClientRect().width>1; }")
SETTLED = ("() => [...document.querySelectorAll('#screen-swipe #cards .card')]"
           ".every(c=>{const t=getComputedStyle(c).transform;"
           " return t==='none'||/matrix\\(1, 0, 0, 1/.test(t);})")
DUMP = ("() => { const r = document.querySelector('#result-module');"
        " return r.className + '\\n' + r.innerHTML; }")

fails = []
checks = [0]


def check(label, ok, detail=""):
    checks[0] += 1
    if not ok:
        fails.append("%s %s" % (label, detail))
    print("  %-62s %s%s" % (label, "ok" if ok else "FAIL",
                            ("  " + str(detail)[:200]) if detail and not ok
                            else ""))


REPORTS = {}
for slug in ZODIAC + ["blinds"]:
    cfg = config.load_funnel(slug)
    style = STYLE[slug] or cfg["styles"][0]["id"]
    choices = [s["pairs"][0]["images"][0]["id"] for s in cfg["swipe"]["steps"]]
    content = reports.start_report(
        1, slug, style, {"water": 9, "moon": 6, "warm": 5, "wood": 4,
                         "modern": 3}, choices=choices)
    content["version"] = "llm-2"
    REPORTS[slug] = content


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
            ref = self.headers.get("referer") or ""
            slug = next((s for s in sorted(REPORTS, key=len, reverse=True)
                         if "/" + s + "?" in ref or ref.endswith("/" + s)),
                        "zodiac30")
            return self._json({
                "complete": True, "email_masked": "s***@x.com",
                "report": reports.delivered_content(
                    REPORTS[slug], "sarah.okonkwo@example.com")})
        if path.strip("/") in REPORTS:
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


def walk(page, slug, query=""):
    page.add_init_script(CLOCK)
    page.add_init_script(SEED)
    page.add_init_script("try{sessionStorage.setItem('mazzin_sid',"
                         "'a1b2c3d4-0000-4000-8000-000000000007');}catch(e){}")
    page.goto("http://127.0.0.1:%d/%s%s" % (PORT, slug, query))
    page.wait_for_selector("#screen-swipe #cards .card", timeout=20000)
    steps = len(config.load_funnel(slug)["swipe"]["steps"])
    for _ in range(steps + 10):
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
            page.locator("#screen-swipe #cards .card").first.click(
                timeout=6000)
        except Exception:
            page.wait_for_timeout(700)
            continue
        page.wait_for_timeout(1900)
    page.wait_for_selector("#result-module", timeout=25000)
    page.wait_for_timeout(1200)
    return page.evaluate(DUMP)


def paid(page, slug):
    page.add_init_script(CLOCK)
    page.goto("http://127.0.0.1:%d/%s?cs=cs_test_123" % (PORT, slug))
    page.wait_for_selector("#result-module.is-delivered", timeout=25000)
    page.wait_for_timeout(1200)
    return page.evaluate(DUMP)


READ = """() => {
  const r = document.querySelector('#result-module');
  const t = s => { const n = r.querySelector(s); return n ? n.textContent.trim() : null; };
  const all = s => [...r.querySelectorAll(s)].map(n => n.textContent.trim());
  return {
    cls: r.className,
    shape: [...r.children].map(n => n.className),
    kicker: t('.zr-kicker'), stars: r.querySelectorAll('.zr-kicker .zr-star').length,
    subtype: t('.zr-subtype'), chips: all('.zr-chip'),
    scales: [...r.querySelectorAll('.zr-scale:not(.is-cost)')].map(n => ({
      left: n.children[0].textContent, right: n.children[2].textContent,
      at: parseFloat(n.querySelector('.zr-scale-dot').style.left)})),
    split: [...r.querySelectorAll('.zr-split-seg')].map(n => parseFloat(n.style.width)),
    splitNames: all('.zr-split-name'),
    splitColors: [...r.querySelectorAll('.zr-split-seg')].map(n => n.style.background),
    cross: t('.zr-crossline'), crossBright: !!r.querySelector('.zr-crossline.is-bright'),
    glyph: (r.querySelector('.zr-glyph img') || {}).getAttribute ? r.querySelector('.zr-glyph img').getAttribute('src') : null,
    taps: r.querySelectorAll('.zr-tap img').length, tapsCaption: t('.zr-taps-caption'),
    rarity: r.querySelectorAll('.zr-rarity').length, cards: r.querySelectorAll('.zr-cards').length,
    teasers: [...r.querySelectorAll('.zr-boxes-grid.is-teasers .zr-box')].map(n => ({
      title: n.querySelector('.zr-box-title').textContent, sub: (n.querySelector('.zr-box-sub') || {}).textContent || '',
      icon: !!n.querySelector('.zr-box-icon svg')})),
    offerHead: t('.zr-offer-head'), unlockHead: t('.zr-unlock-head'),
    cost: (() => { const c = r.querySelector('.zr-cost'); if (!c) return null;
      return {kicker: t('.zr-cost-kicker'), lead: t('.zr-cost-lead'),
              figure: t('.zr-cost-figure'), note: t('.zr-cost-note'),
              aria: c.querySelector('.zr-cost-figure').getAttribute('aria-label')}; })(),
    costRow: (() => { const c = r.querySelector('.zr-scales .zr-scale.is-cost'); if (!c) return null;
      const run = c.querySelector('.zr-scale-run'); const v = c.querySelector('.zr-cost-value');
      const pole = r.querySelector('.zr-scale:not(.is-cost) .zr-scale-pole');
      return {label: t('.zr-cost-label'), value: v.textContent, note: t('.zr-cost-sub'),
              width: run.style.width, size: parseFloat(getComputedStyle(v).fontSize),
              poleSize: pole ? parseFloat(getComputedStyle(pole).fontSize) : 0,
              colour: getComputedStyle(v).color, last: c === c.parentNode.lastElementChild,
              rows: r.querySelectorAll('.zr-scales .zr-scale').length}; })(),
    wrap: {chips: [...r.querySelectorAll('.zr-chip')].map(n => ({text: n.textContent,
              clipped: n.scrollWidth > n.clientWidth + 1, ws: getComputedStyle(n).whiteSpace})),
           names: [...r.querySelectorAll('.zr-split-name')].map(n => ({text: n.textContent,
              ws: getComputedStyle(n).whiteSpace, overflow: getComputedStyle(n).overflow,
              ellipsis: getComputedStyle(n).textOverflow}))},
    offerHasList: !!r.querySelector('.zr-offer .zr-checklist'),
    headLock: !!r.querySelector('.zr-unlock-head .zr-unlock-lock svg'),
    money: (() => { const m = r.querySelector('.zr-check.is-money'); if (!m) return null;
      const line = m.querySelector('.zr-check-line'); const key = m.querySelector('.zr-check-key');
      const other = r.querySelector('.zr-check:not(.is-money) .zr-check-line');
      return {first: m === m.parentNode.firstElementChild,
              shield: !!m.querySelector('.zr-check-mark.is-shield svg'),
              line: line.textContent.split(' — ').slice(1).join(' — ').trim(),
              size: parseFloat(getComputedStyle(line).fontSize),
              otherSize: other ? parseFloat(getComputedStyle(other).fontSize) : 0,
              keyColour: getComputedStyle(key).color}; })(),
    rows: [...r.querySelectorAll('.zr-checklist .zr-check')].map(n => ({
      key: (n.querySelector('.zr-check-key') || {}).textContent || '', text: n.querySelector('.zr-check-line').textContent.trim()})),
    anchor: t('.zr-anchor'), gold: t('.zr-anchor .zr-gold'), price: t('.zr-price-now'), note: t('.zr-price-note'),
    badges: all('.zr-badge'), sub: t('.zr-offer-sub'), trust: t('.zr-trust'),
    consent: !!r.querySelector('#withdrawal') && !r.querySelector('#withdrawal').hidden,
    pay: !!r.querySelector('#pay-button'),
    engineReport: document.getElementById('report').hidden,
    body: getComputedStyle(document.body).backgroundColor,
    text: r.innerText
  }; }"""

READ_PAID = """() => {
  const r = document.querySelector('#result-module');
  const t = s => { const n = r.querySelector(s); return n ? n.textContent.trim() : null; };
  return {
    cls: r.className, sent: t('.zr-sent'), kicker: t('.zr-kicker'),
    heroCls: r.querySelector('.zr-hero').className, sign: t('.zr-sign'), sub: t('.zr-sub'),
    elements: r.querySelectorAll('.zr-elements').length, band: r.querySelectorAll('.zr-band').length,
    taps: r.querySelectorAll('.zr-tap img').length,
    nodes: [...r.querySelectorAll('.zr-path .zr-node')].map(n => ({
      title: (n.querySelector('.zr-node-title') || n.querySelector('h2, h3') || {}).textContent || '',
      key: (n.querySelector('.zr-node-key') || {}).textContent || '',
      shot: !!n.querySelector('.zr-shot img'),
      body: !!(n.querySelector('.zr-swatches, .zr-list, .zr-verdicts, .zr-implications, .zr-splurge, .zr-months'))})),
    verdicts: [...r.querySelectorAll('.zr-tag')].map(n => n.textContent),
    savesHead: t('.zr-sub-head'), foot: t('.zr-footnote'),
    text: r.innerText
  }; }"""

BLINDS = config.load_funnel("blinds")
SECTIONS = [s for s in BLINDS["report"]["sections"]]
PROFILE = BLINDS["result_copy"]["profile"]

socketserver.TCPServer.allow_reuse_address = True
httpd = socketserver.TCPServer(("127.0.0.1", PORT), Handler)
threading.Thread(target=httpd.serve_forever, daemon=True).start()
record = bool(os.environ.get("MAZZIN_RECORD_MINIMAL"))
try:
    with sync_playwright() as pw:
        browser = pw.chromium.launch(executable_path=CHROME)

        print("\n--- the zodiac funnels render exactly what they did ---")
        for slug in ZODIAC:
            for kind in ("free", "paid"):
                page = browser.new_page(viewport={"width": 390, "height": 844})
                errors = []
                page.on("pageerror", lambda e: errors.append(str(e)))
                html = (walk(page, slug, "?arm=minimal" if slug == "zodiac30"
                             else "") if kind == "free" else paid(page, slug))
                page.close()
                path = os.path.join(FIXTURES, "minimal_%s-%s.html"
                                    % (slug, kind))
                if record:
                    with open(path, "w", encoding="utf-8") as fh:
                        fh.write(html)
                    print("  recorded %s (%d bytes)" % (path, len(html)))
                    continue
                want = open(path, encoding="utf-8").read() \
                    if os.path.isfile(path) else None
                check("%-16s %-4s page is byte-identical to the fixture"
                      % (slug, kind), want is not None and html == want
                      and not errors,
                      "%d vs %s bytes, errors=%s"
                      % (len(html), len(want) if want else "no fixture",
                         errors))
                check("  and the fixture is a whole page",
                      want is not None and len(want) > 4000)

        print("\n--- the blinds free page is the zodiac30 minimal page ---")
        page = browser.new_page(viewport={"width": 390, "height": 844})
        errors = []
        page.on("pageerror", lambda e: errors.append(str(e)))
        walk(page, "blinds")
        free = page.evaluate(READ)
        page.close()
        check("no page errors", not errors, str(errors[:2]))
        check("the module drew the minimal arm",
              free["cls"].startswith("result-module is-minimal"), free["cls"])
        check("  on the dark ground",
              free["body"].replace(" ", "") in ("rgb(14,20,48)",
                                                "rgba(14,20,48,1)"),
              free["body"])
        check("  the engine's own report is hidden", free["engineReport"])
        check("the page is kicker, lux hero, taps, unlock list, offer",
              free["shape"] == ["zr-kicker is-framed", "zr-hero is-rich is-lux",
                                "zr-taps", "zr-unlock is-list", "zr-offer"],
              str(free["shape"]))
        check("  the kicker is the config's, framed in two stars",
              free["kicker"].strip("✦ ") == BLINDS["result_copy"]["kicker"]
              and free["stars"] == 2, free["kicker"])
        check("  the hero names the style, not a subtype",
              free["subtype"] in {s["name"] for s in BLINDS["styles"]},
              free["subtype"])
        check("  the badge is the frame tapped on the glyph step",
              free["glyph"] and free["glyph"].startswith(
                  "/static/galleries/blinds/b1"), free["glyph"])
        check("  chips: the lead axis and the three scale poles",
              len(free["chips"]) == 4 and free["chips"][0].endswith("-led")
              and all(c for c in free["chips"]), str(free["chips"]))
        check("  three scales with the config's poles",
              [(s["left"], s["right"]) for s in free["scales"]]
              == [(r["left"], r["right"]) for r in PROFILE["scales"]]
              and all(0 <= s["at"] <= 100 for s in free["scales"]),
              str(free["scales"]))
        check("  a five-way split over the identity tags summing to 100, a "
              "name under every segment that has a width",
              len(free["split"]) == 5 and round(sum(free["split"])) == 100
              and free["splitNames"] == [PROFILE["split"]["names"][t]
                                         for t, pct in zip(
                                             PROFILE["split"]["tags"],
                                             free["split"]) if pct],
              str(free["split"]) + str(free["splitNames"]))
        check("  the root wears is-generic, which no zodiac page does",
              free["cls"] == "result-module is-minimal is-generic")
        check("  coloured from the config", all(free["splitColors"]))
        check("  the bright line is the style's blurb",
              free["crossBright"] and free["cross"].strip("✦ ")
              in {s["blurb"] for s in BLINDS["styles"]}, free["cross"])
        check("nine taps in the strip, under the config caption",
              free["taps"] == 9
              and free["tapsCaption"] == BLINDS["result_copy"]["taps_caption"],
              "%s / %s" % (free["taps"], free["tapsCaption"]))
        check("no rarity card and no question cards — nothing zodiac",
              free["rarity"] == 0 and free["cards"] == 0)
        check("  and no teaser boxes, no counter card",
              free["teasers"] == [] and free["cost"] is None)
        VF = BLINDS["value_framing"]
        ANCHOR = "up to $250"
        check("the hero carries three scales and no cost row",
              free["costRow"] is None and len(free["scales"]) == 3)
        money = free["money"] or {}
        check("the money row leads the unlock list: gold key, a size up, "
              "a shield",
              free["rows"] and free["rows"][0]["key"]
              == "Save up to $250 on your blinds"
              and money.get("first") and money.get("shield")
              and money.get("line") == VF["unlock_row"]["line"].replace(
                  "{style}", free["subtype"])
              and money.get("size", 0) > money.get("otherSize", 0)
              and money.get("keyColour", "").replace(" ", "")
              == "rgb(232,200,120)", str(money))
        check("  the head is WHAT YOU UNLOCK behind an inline lock glyph",
              free["unlockHead"] == "WHAT YOU UNLOCK"
              and free["headLock"] is True)
        check("the chapter rows follow, keyed on the section titles",
              [r["key"] for r in free["rows"]][1:]
              == [next(s["title"] for s in SECTIONS if s["id"] == row["id"])
                  for row in PROFILE["unlock"]] + [PROFILE["unlock_tail"]["key"]],
              str([r["key"] for r in free["rows"]]))
        check("  worded from the config's unlock lines",
              all(row["line"] in text["text"] for row, text
                  in zip(PROFILE["unlock"], free["rows"][1:])))
        check("  and the offer card carries no list of its own",
              free["offerHasList"] is False)
        check("chips wrap rather than truncate",
              all(c["ws"] == "normal" and not c["clipped"]
                  for c in free["wrap"]["chips"]), str(free["wrap"]["chips"]))
        check("  and so do the split names — no ellipsis anywhere",
              all(n["ws"] == "normal" and n["ellipsis"] != "ellipsis"
                  for n in free["wrap"]["names"]), str(free["wrap"]["names"]))
        check("the offer head names the style and the promise",
              free["offerHead"] and "overpay" in free["offerHead"]
              and free["subtype"] in free["offerHead"], free["offerHead"])
        check("the anchor is the commerce price anchor with its accent",
              free["anchor"] == BLINDS["checkout"]["commerce"]["price_anchor"]
              .replace("{price}", "$1.99")
              and free["gold"] == BLINDS["checkout"]["commerce"]
              ["price_anchor_accent"], free["anchor"])
        check("  the price is the charm price with its note and badges",
              free["price"] == "$1.99" and free["note"] == "one-time"
              and free["badges"] == BLINDS["checkout"]["commerce"]["badges"])
        check("  the offer sub and trust row are the config's",
              free["sub"] == BLINDS["result_copy"]["offer_sub"]
              and free["trust"] == " · ".join(
                  BLINDS["checkout"]["commerce"]["trust"]))
        check("the EU consent stays on the page, gating the button",
              free["consent"] and free["pay"])
        check("no money amount anywhere on the page",
              "$400" not in free["text"] and "$1,500" not in free["text"])

        print("\n--- and the paid page is the delivered zodiac layout ---")
        page = browser.new_page(viewport={"width": 390, "height": 844})
        errors = []
        page.on("pageerror", lambda e: errors.append(str(e)))
        paid(page, "blinds")
        got = page.evaluate(READ_PAID)
        page.close()
        check("no page errors", not errors, str(errors[:2]))
        check("the delivered page, opened on the delivery line",
              got["cls"] == "result-module is-delivered"
              and got["sent"] and "sarah.okonkwo@example.com" in got["sent"],
              got["sent"])
        check("  the plain hero: style name and blurb, no element strip",
              got["sign"] == "Warm Scandinavian"
              and got["sub"] == [s for s in BLINDS["styles"]
                                 if s["id"] == "warm_scandi"][0]["blurb"]
              and got["elements"] == 0 and got["band"] == 1,
              "%s / elements=%s band=%s" % (got["sign"], got["elements"],
                                            got["band"]))
        check("  the nine taps again", got["taps"] == 9, got["taps"])
        check("six chapters, each keyed, pictured and typed",
              len(got["nodes"]) == 6
              and all(n["key"] and n["shot"] and n["body"]
                      for n in got["nodes"]), str(got["nodes"]))
        check("  the keys are the config's cards",
              set(n["key"].rstrip(":") for n in got["nodes"])
              == {c["key"] for c in PROFILE["cards"]},
              str([n["key"] for n in got["nodes"]]))
        check("  the verdict badges and the saves heading are the labels",
              set(got["verdicts"]) <= {"WORKS", "AVOID"}
              and got["savesHead"] == "Save here",
              "%s / %s" % (got["verdicts"], got["savesHead"]))
        check("  closing on the delivered note",
              got["foot"] == BLINDS["result_copy"]["delivered_note"])
        browser.close()
finally:
    httpd.shutdown()

print("\n--- the module ---")
JS = open(os.path.join(ROOT, "static/js/result_zodiac.js"),
          encoding="utf-8").read()
check("the generic reader exists and is only reached without subtypes",
      "function genericProfileOf(ctx, table)" in JS
      and "if (!table || !table.subtypes) return genericProfileOf(ctx, table);"
      in JS)
check("  the badge, the pitch and the checklist rows are its only hooks",
      "glyph(heroPick(ctx, data))" in JS
      and "if (data.generic) {" in JS
      and "root.appendChild(list || sectionTeasers(ctx) || elm(\"span\"));"
      in JS
      and "var money = moneyRow(ctx, data);" in JS
      and "rows = sectionRows(ctx);" in JS)
check("  the generic page draws its list above the offer, the zodiac page "
      "inside it",
      "var list = unlockList(ctx, data);" in JS
      and "if (list && !data.generic) card.appendChild(list);" in JS
      and "costScale" not in JS)
check("  the counter card is gone with its animation",
      "costCounter" not in JS and "countUp" not in JS
      and "requestAnimationFrame" not in JS)
check("  the element strip is gated on a style that has an element",
      "if (hasElement(ctx.style)) card.appendChild(deliveredElements(ctx));"
      in JS)
check("  the split arithmetic is one function for both readers",
      JS.count("splitPcts(") == 3)
PERSONA = open(os.path.join(ROOT, "static/js/result_persona.js"),
               encoding="utf-8").read()
def mechanism(src):
    start = src.index("  // engine.js's own session key.")
    end = src.index("  // One event, once, when the offer is drawn", start)
    return src[start:end]


check("the paywall-variants block is still the persona module's, byte for "
      "byte", mechanism(JS) == mechanism(PERSONA) and mechanism(JS).strip())

print("\n%d checks, %d failed" % (checks[0], len(fails)))
for f in fails:
    print("  FAIL " + f)
sys.exit(1 if fails else 0)
