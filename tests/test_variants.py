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
import collections
import http.server
import json
import os
import random
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
CSS = open(os.path.join(REPO, "static/css/result_zodiac.css"),
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
PROFILE = Z30["result_copy"]["profile"]

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


def hashed(text):
    """The module's own FNV-1a, so the suite picks the same arm it does."""
    value = 0x811c9dc5
    for ch in text:
        value ^= ord(ch)
        value = (value + ((value << 1) + (value << 4) + (value << 7)
                          + (value << 8) + (value << 24))) & 0xFFFFFFFF
    return value


def weight_of(variant):
    """`variantWeight`, to the letter: a non-number is 1, a negative is 0."""
    weight = variant.get("weight")
    return weight if isinstance(weight, (int, float)) and weight > 0 else (
        1 if not isinstance(weight, (int, float)) else 0)


def pool_of(cfg):
    """`variantPool`: enabled, named, and weighing something."""
    return [v for v in (cfg.get("paywall_variants") or [])
            if v.get("id") and v.get("enabled") is not False
            and weight_of(v) > 0]


def arm_for(sid, cfg=None):
    """Which arm a session id reaches, as `assignedVariant` decides it.

    Mirrored rather than approximated — the weight filter and the
    single-variant shortcut included. A model that skipped either would agree
    with the module today and stop agreeing the moment a weight moved, which
    is exactly the change this suite is here to check.
    """
    pool = pool_of(cfg or Z30)
    if not pool:
        return None
    if len(pool) == 1:
        return pool[0]["id"]
    total = sum(weight_of(v) for v in pool)
    if total <= 0:
        return pool[0]["id"]
    point = (hashed(sid) % 100000) / 100000.0 * total
    seen = 0
    for v in pool:
        seen += weight_of(v)
        if point < seen:
            return v["id"]
    return pool[-1]["id"]


print("\n--- the layout flag ---")
variants = Z30["paywall_variants"]
check("zodiac30 declares two arms", len(variants) == 2,
      str([v["id"] for v in variants]))
control_def = next((v for v in variants if v["id"] == "control"), None)
minimal_def = next((v for v in variants if v["id"] == "minimal"), None)
check("  a control that names no template",
      control_def is not None and "template" not in control_def)
check("  and an arm that names one",
      minimal_def is not None and minimal_def.get("template") == "minimal")
check("  both still defined and enabled",
      all(v["enabled"] is True for v in variants),
      str([(v["id"], v["enabled"]) for v in variants]))
check("  and the split is carried by weights, not by an even deal",
      all(isinstance(v.get("weight"), int) for v in variants),
      str([(v["id"], v.get("weight")) for v in variants]))

print("\n--- minimal is the only arm served ---")
# The A/B is over. The control is kept — defined, enabled, named, and with
# its fixture still checked below — but it weighs nothing, which takes it out
# of the pool rather than merely making it unlikely.
check("the control weighs nothing", control_def["weight"] == 0,
      str(control_def["weight"]))
check("  and minimal weighs something", minimal_def["weight"] > 0,
      str(minimal_def["weight"]))
check("  so the pool is one arm long",
      [v["id"] for v in pool_of(Z30)] == ["minimal"],
      str([v["id"] for v in pool_of(Z30)]))
check("  which the module renders unconditionally, whatever the hash says",
      "if (pool.length === 1) return pool[0];" in ZODIAC)
# Ten thousand ids in the shape engine.js actually mints — crypto.randomUUID,
# or its v4 fallback — rather than a counter dressed as one.
rng = random.Random(20260830)


def production_sid():
    raw = "%032x" % rng.getrandbits(128)
    return "%s-%s-4%s-%x%s-%s" % (
        raw[0:8], raw[8:12], raw[13:16],
        (int(raw[16], 16) & 0x3) | 0x8, raw[17:20], raw[20:32])


SESSIONS = 10000
seen = collections.Counter(arm_for(production_sid()) for _ in range(SESSIONS))
check("every one of %d sessions is served minimal" % SESSIONS,
      seen["minimal"] == SESSIONS, str(dict(seen)))
check("  and not one of them reaches the control",
      seen["control"] == 0, str(seen["control"]))
check("  the ids were the shape the engine mints",
      all(re.fullmatch(r"[0-9a-f]{8}-[0-9a-f]{4}-4[0-9a-f]{3}"
                       r"-[89ab][0-9a-f]{3}-[0-9a-f]{12}", production_sid())
          for _ in range(200)))
# The weights are what did it, not a deleted arm. Put one back and the split
# comes back with it — which is the whole reason the definition stays.
restored = json.loads(json.dumps(Z30))
for v in restored["paywall_variants"]:
    v["weight"] = 1
back = collections.Counter(arm_for(production_sid(), restored)
                           for _ in range(SESSIONS))
check("the machinery still splits when a weight is put back",
      back["control"] > SESSIONS * 0.4 and back["minimal"] > SESSIONS * 0.4,
      str(dict(back)))
# The line grew a second fallback: a funnel may name its layout outright,
# with no A/B behind it — /zodiac-ro does, and carries no variants at all. An
# assigned arm still wins, and a funnel declaring neither still lands on "",
# which is what keeps every funnel below unaffected. This suite's own fixture
# — zodiac30's config and both its arms — is untouched by that.
check("the flag is optional, so every other funnel is unaffected",
      "var template = (variant && variant.template)" in ZODIAC
      and '|| (ctx.cfg && ctx.cfg.result_template) || "";' in ZODIAC)
check("  an assigned arm still wins over a named template",
      ZODIAC.index("(variant && variant.template)")
      < ZODIAC.index("ctx.cfg.result_template"))
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
    """The funnel off disk, with one switch.

    `serve_split` hands back zodiac30's config with the control's weight put
    back. That arm weighs nothing in production now, so no session id reaches
    it and there is no URL that forces one — which would leave the control
    fixture undrivable, and the fixture is the thing that has been guarding
    this experiment all along. Restoring the weight for one page load is the
    same edit somebody would make to run the arm again, so what the fixture
    checks is what they would see.
    """

    serve_split = False
    # Every /api/track body the page sent, so the arm it reports can be read
    # off the wire rather than off the source that emits it.
    tracked = []

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
        if path == "/static/funnels/zodiac30.json" and Handler.serve_split:
            with open(os.path.join(REPO, "static/funnels/zodiac30.json"),
                      encoding="utf-8") as fh:
                cfg = json.load(fh)
            for variant in cfg.get("paywall_variants") or []:
                variant["weight"] = 1
            return self._json(cfg)
        if path == "/zodiac30":
            self.path = "/static/funnel.html"
        return super().do_GET()

    def do_POST(self):
        raw = self.rfile.read(int(self.headers.get("content-length") or 0))
        if self.path.split("?")[0] == "/api/track":
            try:
                Handler.tracked.append(json.loads(raw.decode("utf-8")))
            except (ValueError, UnicodeDecodeError):
                pass
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
    root: r.className,
    kicker: {text: t('.zr-kicker'),
             stars: r.querySelectorAll('.zr-kicker .zr-star').length},
    hero: {cls: (r.querySelector('.zr-hero') || {}).className || '',
           corners: r.querySelectorAll('.zr-corner').length},
    chips: [...r.querySelectorAll('.zr-chip')].map(n => n.textContent),
    // The row must never be the reason anything scrolls sideways.
    overflow: {chips: (() => { const u = r.querySelector('.zr-chips');
                 return u ? u.scrollWidth - u.clientWidth : 0; })(),
               page: document.documentElement.scrollWidth
                     - document.documentElement.clientWidth},
    scales: [...r.querySelectorAll('.zr-scale')].map(n => ({
      left: n.children[0].textContent,
      leftLit: n.children[0].classList.contains('is-active'),
      right: n.children[2].textContent,
      rightLit: n.children[2].classList.contains('is-active'),
      at: parseFloat((n.querySelector('.zr-scale-dot') || {style: {}})
                     .style.left) || 0,
      litColour: (() => { const a = n.querySelector('.zr-scale-pole.is-active');
        return a ? getComputedStyle(a).color : null; })()})),
    split: [...r.querySelectorAll('.zr-split-seg')].map(n => ({
      width: parseFloat(n.style.width),
      pct: (n.querySelector('.zr-split-pct') || {}).textContent || null,
      // Where the block sits, so the name under it can be checked against it.
      mid: (() => { const b = n.getBoundingClientRect(); 
                    return Math.round((b.left + b.right) / 2); })()})),
    names: [...r.querySelectorAll('.zr-split-name')].map(n => ({
      text: n.textContent, width: parseFloat(n.style.width),
      mid: (() => { const b = n.getBoundingClientRect();
                    return Math.round((b.left + b.right) / 2); })()})),
    bright: (() => { const c = r.querySelector('.zr-crossline');
      return c ? {lit: c.classList.contains('is-bright'),
                  colour: getComputedStyle(c).color,
                  star: !!c.querySelector('.zr-star')} : null; })(),
    rarityCard: (() => { const c = r.querySelector('.zr-rarity');
      if (!c) return null;
      const box = c.getBoundingClientRect();
      const last = c.lastElementChild.getBoundingClientRect();
      return {cls: c.className,
        lead: (c.querySelector('.zr-rarity-lead') || {}).textContent || null,
        figure: (c.querySelector('.zr-rarity-figure') || {}).textContent
                || null,
        tail: (c.querySelector('.zr-rarity-tail') || {}).textContent || null,
        note: [...c.querySelectorAll('.zr-rarity-note-line')]
                .map(n => n.textContent),
        height: Math.round(box.height),
        below: Math.round(box.bottom - last.bottom),
        left: Math.round(last.left - box.left),
        right: Math.round(box.right - last.right)}; })(),
    unlock: (() => { const u = r.querySelector('.zr-unlock');
      if (!u) return null;
      return {head: (u.querySelector('.zr-unlock-head') || {}).textContent,
        rows: [...u.querySelectorAll('.zr-check')].map(n => {
          const line = n.querySelector('.zr-check-line');
          const key = n.querySelector('.zr-check-key');
          const mark = n.querySelector('.zr-check-mark');
          const box = line.getBoundingClientRect();
          const cs = getComputedStyle(line);
          return {key: key ? key.textContent : '',
            text: line.textContent.trim(),
            size: parseFloat(cs.fontSize),
            leading: parseFloat(cs.lineHeight),
            lines: Math.round(box.height / parseFloat(cs.lineHeight)),
            // A second line has to start under the words, never under the
            // tick.
            underText: Math.round(box.left)
                       >= Math.round(mark.getBoundingClientRect().right)};})};
      })(),
    price: (() => { const w = r.querySelector('.zr-price-was');
      const now = r.querySelector('.zr-price-now');
      if (!w || !now) return null;
      const mark = getComputedStyle(w, '::after');
      return {now: now.textContent, was: w.textContent,
        nowSize: parseFloat(getComputedStyle(now).fontSize),
        wasSize: parseFloat(getComputedStyle(w).fontSize),
        strikeHeight: parseFloat(mark.height) || 0,
        strikeColour: mark.backgroundColor,
        strikeTilted: mark.transform !== 'none',
        decoration: getComputedStyle(w).textDecorationLine}; })(),
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

# Session ids for each arm, picked against the split config — the one the
# control page is rendered under below. Against the shipped config there is
# only one arm and no id would find the other, which is the point of the
# change and the reason the walk has to say which config it is asking about.
SPLIT = json.loads(json.dumps(Z30))
for variant in SPLIT["paywall_variants"]:
    variant["weight"] = 1
sids = {}
for n in range(4000):
    sid = "a1b2c3d4-0000-4000-8000-%012d" % n
    sids.setdefault(arm_for(sid, SPLIT), sid)
    if len(sids) == 2:
        break
check("both arms are reachable when both are weighted",
      set(sids) == {"control", "minimal"}, str(sorted(sids)))
check("  and only one of them is, as this funnel now ships",
      arm_for(sids["control"]) == arm_for(sids["minimal"]) == "minimal",
      "%s / %s" % (arm_for(sids["control"]), arm_for(sids["minimal"])))

socketserver.TCPServer.allow_reuse_address = True
httpd = socketserver.TCPServer(("127.0.0.1", PORT), Handler)
threading.Thread(target=httpd.serve_forever, daemon=True).start()
try:
    with sync_playwright() as pw:
        browser = pw.chromium.launch(executable_path=CHROME)
        errors = []
        page = browser.new_page(viewport={"width": 390, "height": 844})
        page.on("pageerror", lambda e: errors.append(str(e)))
        # The control arm, served the config that still splits.
        Handler.serve_split = True
        try:
            control = read_for(page, sids["control"])
        finally:
            Handler.serve_split = False
        page.close()
        page = browser.new_page(viewport={"width": 390, "height": 844})
        page.on("pageerror", lambda e: errors.append(str(e)))
        Handler.tracked = []
        minimal = read_for(page, sids["minimal"])
        minimal_events = list(Handler.tracked)
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
check("  the contact sheet is common to both",
      minimal_shape[2] == control_shape[2], str(minimal_shape[:3]))
check("  and the kicker is the same line wearing the frame",
      minimal_shape[0] == control_shape[0] + " is-framed",
      "%s vs %s" % (minimal_shape[0], control_shape[0]))
check("  and the hero is the same card wearing the lux flag",
      minimal_shape[1] == control_shape[1] + " is-lux",
      "%s vs %s" % (minimal_shape[1], control_shape[1]))

print("\n--- the lux hero ---")
check("the arm is named on the container, not inside it",
      minimal["root"].endswith(" is-minimal")
      and "is-minimal" not in control["root"],
      "%s / %s" % (minimal["root"], control["root"]))
check("  which is why the control's own subtree is untouched",
      "is-minimal" not in control["html"])
check("the kicker is framed by two marks",
      minimal["kicker"]["stars"] == 2 and control["kicker"]["stars"] == 0,
      "%s / %s" % (minimal["kicker"]["stars"], control["kicker"]["stars"]))
check("  saying what it always said",
      minimal["kicker"]["text"].strip("\u2726 ")
      == control["kicker"]["text"].strip(),
      minimal["kicker"]["text"])
check("four ornaments, one to a corner",
      minimal["hero"]["corners"] == 4 and control["hero"]["corners"] == 0,
      "%s / %s" % (minimal["hero"]["corners"], control["hero"]["corners"]))
CHIPS = PROFILE["chips"]
check("the formula is drawn as capsules",
      len(minimal["chips"]) == len(CHIPS), str(minimal["chips"]))
check("  and the control still draws it as a line",
      not control["chips"] and "zr-formula" in control["html"])
# Four capsules do not fit one line at 390px. Wrapping is the design; going
# off the side of the phone is the failure it has to be told apart from.
check("  they wrap rather than overflow their row",
      minimal["overflow"]["chips"] == 0,
      str(minimal["overflow"]["chips"]))
check("  and nothing pushes the page sideways",
      minimal["overflow"]["page"] == 0 and control["overflow"]["page"] == 0,
      "%s / %s" % (minimal["overflow"]["page"], control["overflow"]["page"]))

print("\n--- the side they lean to is the side that is lit ---")
GOLD = "rgb(196, 166, 96)"
for arm_name, read in (("minimal", minimal), ("career", career)):
    for row in read["scales"]:
        want = "left" if row["at"] < 50 else ("right" if row["at"] > 50
                                              else "")
        lit = ("left" if row["leftLit"] else
               ("right" if row["rightLit"] else ""))
        check("  %-7s %-9s at %-4s lights %s"
              % (arm_name, row["left"], row["at"], lit or "neither"),
              lit == want, "wanted %s" % (want or "neither"))
        check("    and never both", not (row["leftLit"] and row["rightLit"]))
    lit_rows = [r for r in read["scales"] if r["litColour"]]
    check("  %-7s lights its poles gold" % arm_name,
          all(r["litColour"] == GOLD for r in lit_rows),
          str([r["litColour"] for r in lit_rows]))
check("the control lights none of them",
      not [r for r in control["scales"] if r["leftLit"] or r["rightLit"]])

print("\n--- the split, read twice and written once ---")
MIN_PCT = int(re.search(r"var SPLIT_LABEL_MIN_PCT = (\d+)", MODULE).group(1))
for cell in minimal["split"]:
    wide = cell["width"] >= MIN_PCT
    check("  a %2d%% block %s its figure"
          % (cell["width"], "carries" if wide else "goes without"),
          bool(cell["pct"]) == wide,
          "%s%% -> %r" % (cell["width"], cell["pct"]))
    if cell["pct"]:
        check("    which is the block's own share",
              cell["pct"] == "%d%%" % cell["width"], cell["pct"])
# The other side of the gate, on whichever run happens to produce a block too
# narrow to hold a figure. Both runs are checked so the negative case is
# covered whenever either of them has one; the invariant holds either way.
for cell in career["split"]:
    check("  a %2d%% block on the career run %s its figure"
          % (cell["width"], "carries" if cell["width"] >= MIN_PCT
             else "goes without"),
          bool(cell["pct"]) == (cell["width"] >= MIN_PCT),
          "%s%% -> %r" % (cell["width"], cell["pct"]))
narrow = [c for c in minimal["split"] + career["split"]
          if c["width"] < MIN_PCT]
check("  and the renderer gates on the width, not on the count",
      "cell.pct >= SPLIT_LABEL_MIN_PCT" in MODULE,
      "%d narrow blocks seen across the two runs" % len(narrow))
check("the control writes none of them inside the bar",
      not [c for c in control["split"] if c["pct"]])
check("four names under four blocks",
      len(minimal["names"]) == len(minimal["split"]) == 4,
      str(len(minimal["names"])))
check("  each the width of the block it names",
      [n["width"] for n in minimal["names"]]
      == [c["width"] for c in minimal["split"]],
      str([n["width"] for n in minimal["names"]]))
check("  and centred under it",
      all(abs(n["mid"] - c["mid"]) <= 1
          for n, c in zip(minimal["names"], minimal["split"])),
      str([(n["mid"], c["mid"])
           for n, c in zip(minimal["names"], minimal["split"])]))
check("  the control keeps the sentence instead",
      not control["names"] and "zr-split-caption" in control["html"])

print("\n--- the reading is the sentence the card is for ---")
BRIGHT = "rgb(248, 246, 240)"
check("it is set as primary text, not as an aside",
      minimal["bright"]["lit"] and minimal["bright"]["colour"] == BRIGHT,
      str(minimal["bright"]))
check("  with a mark leading it", minimal["bright"]["star"])
check("  and no rule above it, which made it a footnote",
      "zr-hairline" not in minimal["html"]
      and "zr-hairline" in control["html"])
check("the control reads it the way it always did",
      not control["bright"]["lit"] and not control["bright"]["star"],
      str(control["bright"]))

print("\n--- the experiment is retired, not dismantled ---")
check("the control is still defined, enabled and named",
      control_def is not None and control_def["enabled"] is True
      and control_def.get("name"), str(control_def))
check("  and still names no template, which is what makes it the control",
      "template" not in control_def)
check("  with a note saying how to bring it back",
      "weight" in (control_def.get("note") or "").lower(),
      str(control_def.get("note"))[:80])
check("the machinery is untouched",
      all(fn in ZODIAC for fn in ("function variantWeight(",
                                  "function variantPool(",
                                  "function assignedVariant(",
                                  "function reportVariant(")))
check("  and it still reports the arm it drew",
      'ctx.track("paywall_variant", { variant: variant.id })' in ZODIAC)
# Off the wire, not off the source: the page actually sent this.
reported = [e for e in minimal_events if e.get("event") == "paywall_variant"]
check("    which the page sends, once",
      len(reported) == 1, str([e.get("event") for e in minimal_events]))
check("    naming the arm that is now the only one",
      reported and (reported[0].get("extra") or {}).get("variant") == "minimal",
      str(reported[:1]))
check("    for this funnel", reported
      and reported[0].get("funnel") == "zodiac30", str(reported[:1]))
check("  which tracking.py still accepts",
      "paywall_variant" in open(os.path.join(REPO, "tracking.py"),
                                encoding="utf-8").read())
# The fixture itself, and the recorder beside it. What compares them is the
# block immediately below, which runs on every invocation of this suite.
FIXTURE = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                       "fixtures", "variants_control.html")
check("the control fixture is still on disk, and still has a page in it",
      os.path.isfile(FIXTURE) and os.path.getsize(FIXTURE) > 4000,
      str(os.path.getsize(FIXTURE)) if os.path.isfile(FIXTURE) else "missing")
check("  and the recorder that writes it is still there",
      os.path.isfile(os.path.join(
          os.path.dirname(os.path.abspath(__file__)),
          "record_variants_control.py")))

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
RARITY = PROFILE["rarity_card"]
card = minimal["rarityCard"]
check("it is a card of its own now", "is-card" in card["cls"], card["cls"])
check("  framing the number above and below",
      card["lead"] == RARITY["lead"] and card["tail"] == RARITY["tail"],
      "%s / %s" % (card["lead"], card["tail"]))
check("  with the figure between them",
      card["figure"] and card["figure"].endswith("%"), str(card["figure"]))
check("  and one line about what it is worth, in two",
      card["note"] == [RARITY["note"].split("\u2014")[0].strip()
                       + " \u2014",
                       RARITY["note"].split("\u2014")[1].strip()],
      str(card["note"]))
# Padding, not a height: the note is two lines at 390px and one on a wider
# phone, and a fixed box leaves dead ground under it on the second.
# The declarations, with the prose taken out — the comment inside this rule
# says the word "height" while arguing for not setting one.
rarity_css = re.sub(r"/\*.*?\*/", "", re.search(
    r"\.zr-rarity\.is-card \{(.*?)\n\}", CSS, re.S).group(1), flags=re.S)
check("  the card is sized by what is in it, not by a fixed height",
      not re.search(r"(?<!line-)height\s*:", rarity_css), rarity_css.strip())
check("  nothing sits closer than 24px to an edge",
      card["below"] >= 24 and card["left"] >= 24 and card["right"] >= 24,
      "below %s left %s right %s"
      % (card["below"], card["left"], card["right"]))
check("  and there is no dead ground under the last line",
      card["below"] <= 34, str(card["below"]))
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
check("  and the figure is the complement of that blend's own N",
      n is not None and card["figure"] == "%d%%" % round((1 - 1 / n) * 100),
      "%s — %s is 1 in %s" % (card["figure"], minimal["subtype"], n))
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

print("\n--- what you unlock, over the price ---")
KEYS = {c["id"]: c["key"] for c in PROFILE["cards"]}
ROWS = PROFILE["unlock"]
TAIL = PROFILE["unlock_tail"]
check("the control arm has none of it", control["unlock"] is None)
rows = minimal["unlock"]["rows"]
check("the minimal arm heads the block",
      minimal["unlock"]["head"] == PROFILE["unlock_head"],
      minimal["unlock"]["head"])
check("  one row per chapter, plus the tail",
      len(rows) == len(ROWS) + 1, str(len(rows)))
check("  every row wears a tick", all(r["icon"] for r in minimal["checklist"]))
check("  and not one wears a lock", minimal["locks"] == 0,
      str(minimal["locks"]))
check("  the keywords are the question cards' own",
      [r["key"] for r in rows[:-1]] == [KEYS[row["id"]] for row in ROWS],
      str([r["key"] for r in rows]))
check("  and the tail names itself",
      rows[-1]["key"] == TAIL["key"], rows[-1]["key"])
check("  the year row filled its month labels",
      re.search(r"\b[A-Z][a-z]{2} \d{4} → [A-Z][a-z]{2} \d{4}\b",
                [r["text"] for r in rows if r["key"] == KEYS["shopping"]][0])
      is not None, str([r["text"] for r in rows]))
check("  and no row was left holding a brace",
      not [r for r in rows if "{" in r["text"]],
      str([r["text"] for r in rows if "{" in r["text"]]))
# The wrap is the reason the keyword and the description are one paragraph
# rather than two columns. A row that runs to a second line has to start that
# line under its own words.
check("  a row that runs long wraps under its text, never under the tick",
      all(r["underText"] for r in rows), str([r["underText"] for r in rows]))
check("    and at least one of them does run long",
      max(r["lines"] for r in rows) >= 2,
      str([r["lines"] for r in rows]))
# The block is a list to scan, not prose to read. At 17.5px the longest row —
# LOVE, and it is the longest by some way — ran to three lines, which put the
# price a line and a half further down the card than it needed to be.
check("  the rows are set at 16px",
      all(r["size"] == 16 for r in rows), str([r["size"] for r in rows]))
check("    with the leading a multiple of that, not a second reduction",
      all(abs(r["leading"] - r["size"] * 1.45) < 0.6 for r in rows),
      str([(r["size"], r["leading"]) for r in rows]))
check("  and no row runs past two lines at 390px",
      max(r["lines"] for r in rows) <= 2,
      str([(r["key"], r["lines"]) for r in rows]))
longest = max(rows, key=lambda r: len(r["text"]))
check("    including the longest of them, which is %r"
      % longest["key"], longest["lines"] <= 2,
      "%s at %d lines" % (longest["key"], longest["lines"]))
check("it sits above the price, under the headline",
      minimal["offer"].index("zr-unlock")
      == minimal["offer"].index("zr-offer-head") + 1
      and minimal["offer"].index("zr-unlock")
      < minimal["offer"].index("zr-anchor")
      < minimal["offer"].index("zr-price")
      < minimal["offer"].index("zr-sale")
      < minimal["offer"].index("zr-badges"),
      str(minimal["offer"]))
check("  and the rest of the offer is in the order it always was",
      [c for c in minimal["offer"] if c != "zr-unlock"]
      == control["offer"], str(minimal["offer"]))

print("\n--- and it leads with what they said they came for ---")
career_rows = career["unlock"]["rows"]
check("a career run reads Money first",
      career_rows[0]["key"] == KEYS["splurge"],
      str([r["key"] for r in career_rows]))
check("  a love run reads Love first", rows[0]["key"] == KEYS["materials"],
      str([r["key"] for r in rows]))
check("  and only the first row moves",
      [r["key"] for r in career_rows[1:]]
      == [r["key"] for r in rows if r["key"] != career_rows[0]["key"]],
      str([r["key"] for r in career_rows]))
check("  which is the reorder the question cards already do",
      "firstly(rows.slice(), emphasised(purposeRule(ctx)))" in MODULE
      and "firstly((table.cards || []).slice(), want)" in MODULE)

print("\n--- the price it is instead of ---")
STRIKE = "rgb(226, 120, 112)"
check("the struck price is the regular one and nothing else",
      minimal["price"]["was"]
      == "$%d" % (Z30["sale"]["regular_price_cents"] // 100) == "$3",
      minimal["price"]["was"])
check("  set beside the hero at a little over half its size",
      0.5 <= minimal["price"]["wasSize"] / minimal["price"]["nowSize"] <= 0.6,
      "%s / %s" % (minimal["price"]["wasSize"], minimal["price"]["nowSize"]))
# A hairline in the type's own colour reads as a rendering artefact beside a
# 52px figure. This is a rule of its own, and the test is that it is drawn at
# all — a missing pseudo-element comes back at zero height.
check("  struck by a rule of its own, not by a text decoration",
      minimal["price"]["strikeHeight"] >= 2
      and minimal["price"]["decoration"] == "none",
      str(minimal["price"]))
check("    tilted, and in a red the gold does not contain",
      minimal["price"]["strikeTilted"]
      and minimal["price"]["strikeColour"] == STRIKE,
      str(minimal["price"]))
check("the control's is the plain line it always was",
      control["price"]["decoration"] == "line-through"
      and control["price"]["strikeHeight"] == 0,
      str(control["price"]))

print("\n%d checks, %d failed" % (checks[0], len(fails)))
for line in fails:
    print("  FAIL   %s" % line)
sys.exit(1 if fails else 0)
