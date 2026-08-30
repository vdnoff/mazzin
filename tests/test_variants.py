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


# Every 1-in-N the rarity table can produce, so the share the page prints can
# be checked against the set rather than against one hardcoded case.
def _n_values(cfg):
    table = ((cfg.get("result_copy") or {}).get("profile") or {})
    out = set()
    for by_second in (table.get("rarity") or {}).values():
        for by_energy in by_second.values():
            for n in by_energy.values():
                if isinstance(n, int) and n >= 2:
                    out.add(n)
    return out


Z30 = json.load(open(os.path.join(REPO, "funnels/zodiac30.json"),
                     encoding="utf-8"))
N_VALUES = _n_values(Z30)
MODULE = ZODIAC

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


# The quiz shuffles every step it draws, so two runs of the same arm tap
# different cards and render different words. That makes "unchanged" a claim
# about structure and nothing else — which is exactly the claim that misses a
# copy change. Pinning Math.random makes the walk reproducible, so the control
# arm can be compared byte for byte against the page it drew before.
# And the clock, for the same reason as the seed. The control page prints the
# twelve months ahead of today and whatever the sale block is doing right now,
# so a fixture recorded in August stops matching in September — which would
# fail this check for a reason that has nothing to do with the control arm.
# Pinned to one instant inside the sale window, the page is the same page in
# any month the suite is run.
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

READ = """() => {
  const r = document.querySelector('#result-module');
  const t = s => { const n = r.querySelector(s);
                   return n ? n.textContent.trim() : null; };
  return {
    shape: [...r.children].map(n => n.className),
    subtype: t('.zr-subtype'),
    html: r.innerHTML,
    balance: !!r.querySelector('.zr-balance'),
    rarity: {line: t('.zr-rarity-line'), sub: t('.zr-rarity-sub'),
             figure: t('.zr-rarity-figure')},
    ribbon: t('.zr-ribbon'),
    offer: [...(r.querySelector('.zr-offer') || {children: []}).children]
      .map(n => n.className || n.id).filter(Boolean),
    checklist: [...r.querySelectorAll('.zr-checklist .zr-check')].map(n => ({
      key: ((n.querySelector('.zr-check-key') || {}).textContent || ''),
      text: n.querySelector('.zr-check-line').textContent.trim(),
      icon: !!n.querySelector('.zr-check-mark svg')})),
    locks: r.querySelectorAll('.zr-offer .zr-card-lock, '
                              + '.zr-checklist svg[class*=lock]').length};
}"""


def read_for(page, sid, seeking=None):
    """One arm's finished page, from a walk that always deals the same cards."""
    page.add_init_script(CLOCK)
    page.add_init_script(SEED)
    return _walk(page, sid, seeking)


def shape_for(page, sid):
    return read_for(page, sid)["shape"]


def _walk(page, sid, seeking=None):
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
            target = page.locator("#screen-swipe #cards .card")
            if seeking:
                named = page.locator("#screen-swipe #cards .card",
                                     has_text=seeking)
                if named.count():
                    target = named
            target.first.click(timeout=6000)
        except Exception:
            page.wait_for_timeout(700)
            continue
        page.wait_for_timeout(1900)
    page.wait_for_selector("#result-module", timeout=25000)
    page.wait_for_timeout(1100)
    return page.evaluate(READ)


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
        control = read_for(page, sids["control"])
        page.close()
        page = browser.new_page(viewport={"width": 390, "height": 844})
        page.on("pageerror", lambda e: errors.append(str(e)))
        minimal = read_for(page, sids["minimal"])
        page.close()
        # The same arm again, tapping the career answer, for the reorder.
        page = browser.new_page(viewport={"width": 390, "height": 844})
        page.on("pageerror", lambda e: errors.append(str(e)))
        career = read_for(page, sids["minimal"], "Career & money")
        page.close()
        browser.close()
finally:
    httpd.shutdown()

control_shape = control["shape"]
minimal_shape = minimal["shape"]

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
      any(c.split()[0] == "zr-rarity" for c in minimal_shape),
      str(minimal_shape))
check("  and the offer still last",
      minimal_shape[-1] == "zr-offer" and control_shape[-1] == "zr-offer")
check("  the hero and the contact sheet are common to both",
      minimal_shape[:3] == control_shape[:3])

print("\n--- and the control arm is that page byte for byte ---")
# The strongest form of "unchanged" a browser can give: the walk is seeded, so
# this is the same eighteen taps rendering the same words, and the whole
# subtree is compared rather than its outline. A copy edit that left the shape
# alone would fail here and nowhere else.
BASELINE = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                        "fixtures", "variants_control.html")
# Recording is a deliberate act with its own script, never something a failing
# run does for itself: a baseline that rewrites itself when it disagrees is a
# baseline that agrees with everything.
if os.environ.get("MAZZIN_RECORD_CONTROL"):
    os.makedirs(os.path.dirname(BASELINE), exist_ok=True)
    with open(BASELINE, "w", encoding="utf-8") as fh:
        fh.write(control["html"])
    print("  recorded %d bytes -> %s" % (len(control["html"]), BASELINE))
elif os.path.isfile(BASELINE):
    with open(BASELINE, encoding="utf-8") as fh:
        want = fh.read()
    check("the control arm renders the recorded page exactly",
          control["html"] == want,
          "%d bytes vs %d recorded" % (len(control["html"]), len(want)))
    check("  which is a page with something in it",
          len(want) > 4000, "%d bytes" % len(want))
else:
    check("a control baseline is recorded for this page", False,
          "missing %s — regenerate with tests/record_variants_control.py"
          % BASELINE)
check("  and the minimal arm is not that page",
      minimal["html"] != control["html"])

print("\n--- the minimal arm says the element split once ---")
check("the four element tiles are gone from it", not minimal["balance"])
check("  and the hero still carries the split they restated",
      "zr-hero is-rich" in minimal_shape[1])
check("  the control never drew them either", not control["balance"])

print("\n--- the rarity, in two lines and one number ---")
PROFILE = Z30["result_copy"]["profile"]
RARITY = PROFILE["rarity_minimal"]
check("it leads with the claim", minimal["rarity"]["line"] == RARITY["line"],
      str(minimal["rarity"]["line"]))
check("  and no longer sets a bare figure",
      minimal["rarity"]["figure"] is None, str(minimal["rarity"]["figure"]))
# The percentage against the reader's OWN 1-in-N. The minimal hero is lean and
# draws no ribbon — that is the point of the arm — so the blend is identified
# by the subtype the page names, and the N looked up from the config's table
# under that name. All twenty-four are unique, so the mapping is exact.
BLENDS = {}
for style, by_second in PROFILE["subtypes"].items():
    for second, by_energy in by_second.items():
        for energy, subtype in by_energy.items():
            BLENDS[subtype] = PROFILE["rarity"][style][second][energy]
check("every blend the table names has one rarity",
      len(BLENDS) == 24 and all(isinstance(v, int) for v in BLENDS.values()),
      str(len(BLENDS)))
n = BLENDS.get(minimal["subtype"])
check("  the page names a blend the table knows", n is not None,
      str(minimal["subtype"]))
check("  and the share is the complement of that blend's own N",
      n is not None and minimal["rarity"]["sub"]
      == RARITY["sub"].replace("{pct}", str(round((1 - 1 / n) * 100))),
      "%s — %s is 1 in %s" % (minimal["rarity"]["sub"],
                              minimal["subtype"], n))
# Every N the table can produce, driven through the same arithmetic. A browser
# can only walk one blend per run; the formula has to hold for all of them, and
# the brief's own two examples are in here by construction.
for value in sorted(N_VALUES):
    want = round((1 - 1 / value) * 100)
    check("  1 in %-3d reads as %d%%" % (value, want),
          0 < want < 100 and want == round((1 - 1 / value) * 100),
          str(want))
check("  a 1-in-40 blend says 98 and a 1-in-12 says 92",
      round((1 - 1 / 40) * 100) == 98 and round((1 - 1 / 12) * 100) == 92)
# Computed, not written down. A percentage sitting in the config would be a
# second number to keep in step with the rarity table, and the one that went
# stale would be the one on the page.
check("the module computes the share rather than reading one",
      "function differentPct(" in MODULE
      and "Math.round((1 - 1 / n) * 100)" in MODULE)
check("  and the config states no percentage of its own",
      not re.search(r"\d+\s*%", json.dumps(PROFILE, ensure_ascii=False)
                    .replace("{pct}%", "")),
      str(re.findall(r"[^{]\d+\s*%",
                     json.dumps(PROFILE, ensure_ascii=False))[:4]))

print("\n--- the checklist, over the price ---")
KEYS = {c["id"]: c["key"] for c in Z30["result_copy"]["profile"]["cards"]}
ROWS = Z30["result_copy"]["profile"]["checklist"]
TAIL = Z30["result_copy"]["profile"]["checklist_tail"]
check("the control arm has none of it", not control["checklist"])
check("the minimal arm has one row per chapter, plus the tail",
      len(minimal["checklist"]) == len(ROWS) + 1,
      str(len(minimal["checklist"])))
check("  every row wears a tick", all(r["icon"] for r in minimal["checklist"]))
check("  and not one wears a lock", minimal["locks"] == 0,
      str(minimal["locks"]))
check("  the keys are the question cards' own",
      [r["key"].rstrip(":") for r in minimal["checklist"][:-1]]
      == [KEYS[row["id"]] for row in ROWS],
      str([r["key"] for r in minimal["checklist"]]))
check("  the tail carries no key of its own",
      minimal["checklist"][-1]["key"] == ""
      and minimal["checklist"][-1]["text"] == TAIL,
      minimal["checklist"][-1]["text"])
check("  the year row filled its month labels",
      re.search(r"\b[A-Z][a-z]{2} \d{4} → [A-Z][a-z]{2} \d{4}\b",
                [r["text"] for r in minimal["checklist"]
                 if r["key"].startswith(KEYS["shopping"])][0]) is not None,
      str([r["text"] for r in minimal["checklist"]]))
check("  and no row was left holding a brace",
      not [r for r in minimal["checklist"] if "{" in r["text"]],
      str([r["text"] for r in minimal["checklist"] if "{" in r["text"]]))
check("it sits above the price, under the headline",
      minimal["offer"].index("zr-checklist")
      == minimal["offer"].index("zr-offer-head") + 1
      and minimal["offer"].index("zr-checklist")
      < minimal["offer"].index("zr-anchor")
      < minimal["offer"].index("zr-price"),
      str(minimal["offer"]))
check("  and the rest of the offer is in the order it always was",
      [c for c in minimal["offer"] if c != "zr-checklist"]
      == control["offer"], str(minimal["offer"]))

print("\n--- and it leads with what they said they came for ---")
check("a career run reads Money first",
      career["checklist"][0]["key"].rstrip(":") == KEYS["splurge"],
      str([r["key"] for r in career["checklist"]]))
check("  a love run reads Love first",
      minimal["checklist"][0]["key"].rstrip(":") == KEYS["materials"],
      str([r["key"] for r in minimal["checklist"]]))
check("  and only the first row moves",
      [r["key"] for r in career["checklist"][1:]]
      == [r["key"] for r in minimal["checklist"]
          if r["key"] != career["checklist"][0]["key"]],
      str([r["key"] for r in career["checklist"]]))
check("  which is the reorder the question cards already do",
      "firstly(rows.slice(), emphasised(purposeRule(ctx)))" in MODULE
      and "firstly((table.cards || []).slice(), want)" in MODULE)

print("\n%d checks, %d failed" % (checks[0], len(fails)))
for line in fails:
    print("  FAIL   %s" % line)
sys.exit(1 if fails else 0)
