#!/usr/bin/env python3
"""The rich profile: the tables, the numbers on them, and the card they draw.

The result page names the reader — "The Wildlight", not "Leo × Celestial Air"
— and sells six chapters as six questions. Three separate things have to agree
for that to be true, and they live in three languages:

  * the tables, in funnels/*.json, written from one source by
    scripts/gen_profile_rarity.py;
  * `profileOf` in static/js/result_zodiac.js, which resolves a run to a name
    in the browser;
  * `_reader_profile` in reports.py, which resolves the same run to the same
    name on the server, because the delivered page, the PDF and the mail are
    all built by something that never had the run.

So the suite runs the module in a real browser against a synthetic run and
holds it to what the Python says about the same tallies, all twenty-four
combinations of it. It also re-derives a sample of the committed rarity from
the same walk model the generator used and holds the printed numbers to it,
so a retag that moves the distribution fails here instead of shipping a stale
ribbon in gold.

No database, no network, no Stripe, no model. The browser loads the module
file directly; nothing is served.

    python3 tests/test_zodiacprofile.py
"""
import json
import os
import random
import re
import sys

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, REPO)
sys.path.insert(0, os.path.join(REPO, "scripts"))

import config                                              # noqa: E402
import reports                                             # noqa: E402
import gen_profile_rarity as gen                           # noqa: E402
from playwright.sync_api import sync_playwright            # noqa: E402

CHROME = "/opt/pw-browsers/chromium-1194/chrome-linux/chrome"

FUNNELS = ("zodiac", "zodiac30")
ELEMENTS = ("fire", "earth", "air", "water")
ENERGIES = ("sun", "moon")

# The archetype that owns each element, read off the configs rather than
# stated, so a retag of a style's tags cannot leave this file quietly wrong.
CFG = {slug: config.load_funnel(slug) for slug in FUNNELS}
TABLE = {slug: CFG[slug]["result_copy"]["profile"] for slug in FUNNELS}
STYLES = {style["id"]: style for style in CFG["zodiac"]["styles"]}
OWN_ELEMENT = {
    style["id"]: next(t for t in style["tags"] if t in ELEMENTS)
    for style in CFG["zodiac"]["styles"]
}

fails = []
checks = [0]


def check(label, ok, detail=""):
    checks[0] += 1
    if not ok:
        fails.append("%s %s" % (label, detail))
    print("  %-64s %s%s" % (label, "ok" if ok else "FAIL",
                            ("  " + str(detail)) if not ok else ""))


def banned(text):
    """The first banned phrase in a string, or None."""
    return reports._banned_hit(text, reports.ZODIAC_BANNED)


def combos():
    """Every (archetype, second element, energy) a reader can land on."""
    for style_id in sorted(OWN_ELEMENT):
        for second in ELEMENTS:
            if second == OWN_ELEMENT[style_id]:
                continue
            for energy in ENERGIES:
                yield style_id, second, energy


def scores_for(style_id, second, energy, extra=None):
    """Tallies that resolve to exactly one combination.

    The runner-up is given a clear lead over the other two so nothing here
    depends on a tiebreak; the ties get their own checks below.
    """
    primary = OWN_ELEMENT[style_id]
    others = [tag for tag in ELEMENTS if tag not in (primary, second)]
    out = {primary: 12, second: 7, others[0]: 3, others[1]: 1}
    out[energy] = 8
    out["sun" if energy == "moon" else "moon"] = 2
    out.update({"bold": 4, "calm": 5, "mystic": 3})
    out.update(extra or {})
    return out


# --- a) one source, two funnels --------------------------------------------

print("\n--- the tables are the generator's, on both funnels ---")
want = gen.block(None)
for slug in FUNNELS:
    have = TABLE[slug]
    for key in sorted(k for k in want if k != "rarity"):
        check("  %-10s %-14s is the script's" % (slug, key),
              have.get(key) == want[key],
              json.dumps(have.get(key), ensure_ascii=False)[:80])
check("the two funnels carry identical copy",
      gen.shared(TABLE["zodiac"]) == gen.shared(TABLE["zodiac30"]),
      str(sorted(set(TABLE["zodiac"]) ^ set(TABLE["zodiac30"]))))
check("  and their own measured rarity",
      TABLE["zodiac"]["rarity"] != TABLE["zodiac30"]["rarity"])

# --- b) the twenty-four names ----------------------------------------------

print("\n--- the twenty-four subtype names ---")
names = []
for style_id, second, energy in combos():
    name = ((TABLE["zodiac"]["subtypes"].get(style_id) or {}).get(second)
            or {}).get(energy)
    check("  %-15s %-6s %-4s is named" % (style_id, second, energy),
          bool(name), name)
    names.append(name)
check("there are twenty-four of them", len(names) == 24, len(names))
check("  and no two readers share a name",
      len(set(names)) == 24,
      str([n for n in set(names) if names.count(n) > 1]))
check("  every one of them is in the register",
      all(n and n.startswith("The ") and 1 <= len(n.split()) - 1 <= 2
          for n in names),
      str([n for n in names if not (n or "").startswith("The ")]))
check("  and none of them says a banned word",
      not [n for n in names if banned(n)],
      str([(n, banned(n)) for n in names if banned(n)]))

# --- c) the forty-eight sign lines -----------------------------------------

print("\n--- the sign crossed with the element they led with ---")
SIGNS = [i["label"] for step in CFG["zodiac"]["swipe"]["steps"]
         if step["id"] == "sign"
         for pair in step["pairs"] for i in pair["images"]
         if i["id"] != reports.CUSP_ID]
cross = TABLE["zodiac"]["sign_cross"]
check("all twelve signs have a line for all four leads",
      len(SIGNS) == 12
      and all(set(cross.get(sign) or {}) == set(ELEMENTS) for sign in SIGNS),
      str([s for s in SIGNS if set(cross.get(s) or {}) != set(ELEMENTS)]))
lines = [cross[sign][element] for sign in SIGNS for element in ELEMENTS]
check("  which is forty-eight lines", len(lines) == 48, len(lines))
check("  none of them repeated", len(set(lines)) == 48)
bad = [(sign, element) for sign in SIGNS for element in ELEMENTS
       if sign not in cross[sign][element]
       or reports.ELEMENT_LABEL[element] not in cross[sign][element]]
check("  each naming its own sign and its own lead", not bad, str(bad[:4]))
check("  and none of them saying a banned word",
      not [line for line in lines if banned(line)],
      str([(line[:40], banned(line)) for line in lines if banned(line)][:3]))
check("a cusp gets four lines that name no sign at all",
      set(cross.get("cusp") or {}) == set(ELEMENTS)
      and not [sign for sign in SIGNS
               for element in ELEMENTS if sign in cross["cusp"][element]],
      str(cross.get("cusp")))

# --- d) the six cards -------------------------------------------------------

print("\n--- the six question cards ---")
CARDS = TABLE["zodiac"]["cards"]
# Every chapter, not only the ones the constellation used to draw. `palette`
# carries `reveal: visible`, so the old locked list left it off the page
# entirely — a paywall selling six chapters that listed five.
chapters = [s["id"] for s in CFG["zodiac"]["report"]["sections"]
            if s.get("enabled") is not False]
check("one card per chapter, and no others",
      sorted(c["id"] for c in CARDS) == sorted(chapters),
      str(sorted(c["id"] for c in CARDS)))
check("  which is the six the offer headline claims",
      len(chapters) == 6 and "6 chapters" in TABLE["zodiac"]["offer_head"],
      len(chapters))
check("  every one of them keyword-first",
      all(c.get("key") and c.get("promise")
          and not c["promise"].startswith(c["key"]) for c in CARDS),
      str([c["id"] for c in CARDS if not c.get("key")]))
check("  with an icon named for it",
      all(c.get("icon") for c in CARDS),
      str([c["id"] for c in CARDS if not c.get("icon")]))
# `first` and `last` are the two ends of the reader's own twelve months —
# the same twelve reports.py builds server-side and stores on the report.
KNOWN_TOKENS = {"element", "second", "energy", "subtype", "subtype_bare",
                "subtype_article", "n", "fire", "earth", "air", "water",
                "first", "last"} \
    | set(CFG["zodiac"]["report"]["hook_slots"])
tokens = set()
for card in CARDS:
    tokens |= set(re.findall(r"\{(\w+)\}", card["promise"]))
    for text in (card.get("upgrade") or {}).values():
        tokens |= set(re.findall(r"\{(\w+)\}", text))
check("  and every token on them is one something answers",
      tokens <= KNOWN_TOKENS, str(sorted(tokens - KNOWN_TOKENS)))
love = [c for c in CARDS if c["id"] == "materials"][0]
check("the reader who came for love gets the card that says so",
      "purpose_love" in (love.get("upgrade") or {})
      and "came for" in love["upgrade"]["purpose_love"],
      str(love.get("upgrade")))
copy = [c["key"] + ": " + c["promise"] for c in CARDS]
copy += [c["key"] + ": " + t for c in CARDS
         for t in (c.get("upgrade") or {}).values()]
copy += [TABLE["zodiac"]["bridge"], TABLE["zodiac"]["offer_head"],
         TABLE["zodiac"]["formula"], TABLE["zodiac"]["split_caption"],
         TABLE["zodiac"]["rarity_line"].replace("{n}", "12")]
check("nothing on the paywall says a banned word",
      not [t for t in copy if banned(t)],
      str([(t[:40], banned(t)) for t in copy if banned(t)]))

# --- e) resolution, in Python ----------------------------------------------

print("\n--- every one of the twenty-four resolves, on the server ---")
for style_id, second, energy in combos():
    card = reports._reader_profile(CFG["zodiac"], STYLES[style_id],
                                   scores_for(style_id, second, energy), "Leo")
    want_name = TABLE["zodiac"]["subtypes"][style_id][second][energy]
    check("  %-15s %-6s %-4s -> %s" % (style_id, second, energy, want_name),
          card and card["subtype"] == want_name
          and card["second"] == second and card["energy"] == energy,
          str(card and card["subtype"]))

print("\n--- and the ties resolve the way both languages break them ---")
# Two runners-up dead level. The declared element order carries it, which is
# the only rule that gives the same answer in JavaScript and in Python.
tie = reports._reader_profile(
    CFG["zodiac"], STYLES["deep_water"],
    {"water": 9, "fire": 4, "earth": 4, "air": 1, "sun": 3, "moon": 1}, "Leo")
check("a tie between two runners-up falls to the declared order",
      tie["second"] == "fire", tie["second"])
tie = reports._reader_profile(
    CFG["zodiac"], STYLES["deep_water"],
    {"water": 9, "earth": 4, "air": 4, "fire": 1, "sun": 3, "moon": 1}, "Leo")
check("  whichever two they are", tie["second"] == "earth", tie["second"])
# Sun and moon dead level. The archetype's own energy carries it: the name
# beside the number says both, and a tie broken by list order can print an
# energy the archetype does not hold.
for style_id in sorted(OWN_ELEMENT):
    own = next(t for t in STYLES[style_id]["tags"] if t in ENERGIES)
    level = reports._reader_profile(
        CFG["zodiac"], STYLES[style_id],
        {OWN_ELEMENT[style_id]: 9, "fire": 2, "earth": 2, "air": 2, "water": 2,
         "sun": 3, "moon": 3}, "Leo")
    check("  %-15s at dead level keeps its own %s" % (style_id, own),
          level["energy"] == own, level["energy"])
none = reports._reader_profile(CFG["zodiac"], STYLES["deep_water"],
                               {"water": 4}, "Leo")
check("a run with nothing on three elements still splits to a hundred",
      sum(c["pct"] for c in none["split"]) == 100,
      str([c["pct"] for c in none["split"]]))
check("  and a run with nothing at all is not a profile",
      reports._reader_profile(CFG["zodiac"], STYLES["deep_water"], {}, "Leo")
      is None)
check("a funnel with no tables gets no profile either",
      reports._reader_profile({"result_copy": {}}, STYLES["deep_water"],
                              {"water": 4}, "Leo") is None)

print("\n--- the generator counts what the report names ---")
# The rarity is bucketed by the generator's own resolution of the same three
# things. If the two ever disagree, the ribbon is a number about a different
# blend than the name above it.
rng = random.Random(4242)
drift = []
for _ in range(400):
    scores = dict((tag, rng.randint(-2, 9))
                  for tag in ELEMENTS + ENERGIES + ("bold", "calm", "mystic"))
    style_id = gen.winner(CFG["zodiac"], scores)
    got = gen.bucket(CFG["zodiac"], scores)
    card = reports._reader_profile(CFG["zodiac"], STYLES[style_id], scores,
                                   "Leo")
    if not card:
        continue
    if (card["archetype"], card["second"], card["energy"]) != got:
        drift.append((scores, got,
                      (card["archetype"], card["second"], card["energy"])))
check("four hundred random runs bucket where they are named", not drift,
      str(drift[:2]))

# --- f) the rarity is fresh -------------------------------------------------

print("\n--- the rarity, re-derived ---")
# A smaller sample on a different seed than the committed numbers were taken
# on, held to one rung of the ladder. Wide enough that sampling noise cannot
# fail it and narrow enough that a retag which genuinely moves a blend's share
# does — which is the whole point: a committed number that has quietly gone
# stale is a claim in gold that is no longer true.
SAMPLE, SEED, SLACK = 30000, 88041, 1
for slug in FUNNELS:
    fresh = gen.rarity_table(CFG[slug], SAMPLE, SEED)
    committed = TABLE[slug]["rarity"]
    off = []
    for style_id, second, energy in combos():
        mine = committed[style_id][second][energy]
        theirs = fresh[style_id][second][energy]
        gap = abs(gen.LADDER.index(mine) - gen.LADDER.index(theirs))
        if gap > SLACK:
            off.append((style_id, second, energy, mine, theirs))
    check("  %-9s every committed number is still what the walk says" % slug,
          not off, str(off))
    check("    all twenty-four of them are on the ladder",
          all(committed[a][b][c] in gen.LADDER for a, b, c in combos()),
          str(sorted({committed[a][b][c] for a, b, c in combos()})))
    check("    and inside the floor and the ceiling",
          all(gen.FLOOR <= committed[a][b][c] <= gen.CEILING
              for a, b, c in combos()))

# --- g) the prompts ---------------------------------------------------------

print("\n--- what the model is told, and what it is not ---")
zcfg = CFG["zodiac"]
style = reports._style(zcfg, "celestial_air")
name = reports._style_name(zcfg, "celestial_air")
step_ids = [s["id"] for s in zcfg["swipe"]["steps"]]
choices = [s["pairs"][0]["images"][0]["id"] for s in zcfg["swipe"]["steps"]]
choices[step_ids.index("sign")] = "sign_leo"
tallies = scores_for("celestial_air", "fire", "sun")
subtype = TABLE["zodiac"]["subtypes"]["celestial_air"]["fire"]["sun"]
for section_id in reports.personal_sections("zodiac"):
    prompt = reports._section_prompt(style, name, tallies, section_id, zcfg,
                                     choices, "zodiac")
    check("  %-9s is written to a %s" % (section_id, subtype),
          subtype in prompt, section_id)
love_prompt = reports._section_prompt(style, name, tallies, "materials", zcfg,
                                      choices, "zodiac")
magnetic, drains = reports.COMPATIBILITY["Leo"]
check("the love section is handed the three signs it promised",
      all(sign in love_prompt for sign in magnetic + (drains,)),
      love_prompt[-400:])
check("  and told to use no others as the answer",
      "Use no other signs" in love_prompt)
check("every sign has two magnetic and one draining",
      sorted(reports.COMPATIBILITY) == sorted(SIGNS)
      and all(len(m) == 2 and d and d not in m
              for m, d in reports.COMPATIBILITY.values()),
      str(sorted(set(SIGNS) ^ set(reports.COMPATIBILITY))))
check("  and nobody is their own magnet or their own drain",
      not [s for s, (m, d) in reports.COMPATIBILITY.items()
           if s in m or s == d],
      str([s for s, (m, d) in reports.COMPATIBILITY.items()
           if s in m or s == d]))

print("\n--- and the cache stays four rows a funnel, not twenty-four ---")
cached = reports.cached_sections("zodiac")
prompts = {}
for style_id in OWN_ELEMENT:
    prompts[style_id] = reports._cached_prompt(
        reports._style(zcfg, style_id),
        reports._style_name(zcfg, style_id), cached, "zodiac")
check("one cached prompt per archetype, and four archetypes",
      len(set(prompts.values())) == 4 == len(OWN_ELEMENT), len(prompts))
leaked = [(style_id, subtype_name)
          for style_id, text in prompts.items()
          for subtype_name in names if subtype_name in text]
check("  and not one of them carries a subtype", not leaked, str(leaked))
check("  nor a sign, nor a scale",
      not [s for s in SIGNS
           for text in prompts.values() if s in text]
      and not [t for t in prompts.values() if "out of 100" in t])
# The row itself: the key is the funnel and the style and nothing else, so
# twenty-four subtypes cannot become twenty-four rows to pay for.
check("the cache row is keyed on the funnel and the style alone",
      reports.UPSERT_SECTION_SQL.count("%s") == 4
      and "subtype" not in reports.UPSERT_SECTION_SQL.lower())

# --- h) the stored block, the PDF and the mail ------------------------------

print("\n--- the block reaches the report, the PDF and the mail ---")
saved = (reports.database.execute, reports.database.query_all, reports._api)
try:
    reports.database.execute = lambda *a, **kw: None
    reports.database.query_all = lambda *a, **kw: []
    reports._api = lambda: None
    content = reports.start_report(1, "zodiac", "celestial_air", tallies,
                                   choices=choices)
    kitchen_cfg = config.load_funnel("kitchen")
    kitchen = reports.start_report(2, "kitchen", "modern_rustic", {"warm": 4},
                                   choices=[s["pairs"][0]["images"][0]["id"]
                                            for s in
                                            kitchen_cfg["swipe"]["steps"]])
finally:
    (reports.database.execute, reports.database.query_all,
     reports._api) = saved

stored = (content.get("visuals") or {}).get("profile") or {}
check("the report stores the card the reader was shown",
      stored.get("subtype") == subtype, str(stored.get("subtype")))
check("  beside the photographs rather than among them",
      all(isinstance(v, str)
          for v in (content["visuals"].get("hero") or {}).values()),
      str(content["visuals"].get("hero")))
check("  with the split, the scales and the sign line on it",
      sum(c["pct"] for c in stored["split"]) == 100
      and len(stored["scales"]) == 3
      and stored["cross_line"].startswith("A Leo"),
      str(stored.get("cross_line"))[:60])
check("and kitchen stores nothing of the kind",
      "profile" not in (kitchen.get("visuals") or {}),
      str(sorted(kitchen.get("visuals") or {})))

reports._pdf_visuals().clear()
cover = (reports._pdf_html(content).split('<section class="cover">')[1]
         .split("</section>")[0])
check("the PDF cover is the same card on paper",
      reports._e(stored["subtype"]) in cover
      and reports._e(stored["formula"]) in cover
      and reports._e(stored["rarity_line"]) in cover
      and reports._e(stored["cross_line"]) in cover,
      cover[:140])
check("  scales included, and the split with them",
      cover.count('class="cover-scale"') == 3
      and cover.count('class="cover-seg"') == 4,
      "%d / %d" % (cover.count('class="cover-scale"'),
                   cover.count('class="cover-seg"')))
dots = re.findall(r'class="cover-run" style="width: (\d+)%"', cover)
check("  every dot somewhere on its own track",
      len(dots) == 3 and all(0 <= int(d) <= 100 for d in dots), str(dots))
pdf = reports.build_pdf(content)
check("  and weasyprint still renders the document",
      pdf is not None and pdf[:4] == b"%PDF")
mail = reports._email_html(True, content, {
    "name": "Celestial Air", "headline": "h", "body": "b", "link_block": "",
    "keep": "k", "logo": "L", "home": "H",
    "opening": reports._email_opening(content)})
check("the mail header is the name over the formula",
      (">%s<" % stored["subtype"]) in mail and stored["formula"] in mail,
      stored["formula"])

# --- i) the module, in a browser --------------------------------------------
#
# A synthetic run rather than a walk: the module is handed the context
# engine.js would hand it, so all twenty-four combinations can be drawn in the
# time one walk down zodiac30 takes. What is being checked is the module's own
# arithmetic and its own markup, and neither needs a quiz in front of it.

HARNESS = """(args) => {
  const {cfg, styleId, scores, signId, first} = args;
  const style = cfg.styles.find(s => s.id === styleId);
  const images = {};
  cfg.swipe.steps.forEach(st => (st.pairs || []).forEach(
    p => (p.images || []).forEach(i => { images[i.id] = i; })));
  const picks = {};
  cfg.swipe.steps.forEach(st => {
    const all = (st.pairs || []).reduce((a, p) => a.concat(p.images || []), []);
    let pick = all[0];
    if (st.id === 'sign' && signId) pick = images[signId] || pick;
    if (first && all.some(i => (i.tags || []).indexOf(first) !== -1)) {
      pick = all.find(i => (i.tags || []).indexOf(first) !== -1);
    }
    if (pick) picks[st.id] = pick;
  });
  const words = { style: style.name };
  const slots = (cfg.report || {}).hook_slots || {};
  Object.keys(slots).forEach(key => {
    const label = (picks[slots[key].step] || {}).label;
    words[key] = label
      ? label.charAt(0).toLowerCase() + label.slice(1)
      : (slots[key].fallback || key);
  });
  const ctx = {
    cfg: cfg,
    style: {id: style.id, name: style.name, blurb: style.blurb || "",
            tags: style.tags.slice(), reveals: style.reveals || {}},
    tally: names => names.map(t => ({tag: t, score: scores[t] || 0})),
    picks: picks,
    chosen: Object.keys(picks).map(k => picks[k].id),
    scores: scores,
    hookWords: words,
    fillHook: text => String(text || "").replace(
      /\\{(\\w+)\\}/g, (whole, key) => (key in words) ? words[key] : whole),
    strength: (style.reveals || {}).mistake_one || null,
    strengthCopy: (cfg.report || {}).mistake_one || {},
    sections: (cfg.report.sections || []).map(s => ({
      id: s.id, title: s.title, teaser_line: s.teaser_line || "",
      locked: ((s.reveal || {}).mode || 'locked') !== 'visible'})),
    price: "$3",
    withPrice: t => String(t || "").replace(/\\{price\\}/g, "$3"),
    commerce: (cfg.checkout || {}).commerce || {},
    nodes: {}
  };
  document.body.innerHTML = "";
  const root = document.createElement("div");
  root.className = "result-module";
  document.body.appendChild(root);
  window.MazzinResult.render(root, ctx);
  const text = sel => {
    const n = root.querySelector(sel);
    return n ? n.textContent.trim() : null;
  };
  return {
    subtype: text('.zr-subtype'),
    formula: text('.zr-formula'),
    ribbon: text('.zr-ribbon'),
    caption: text('.zr-split-caption'),
    cross: text('.zr-crossline'),
    bridge: text('.zr-bridge'),
    offerHead: text('.zr-offer-head'),
    scales: [...root.querySelectorAll('.zr-scale')].map(n => [
      n.querySelector('.zr-scale-pole').textContent,
      n.querySelector('.zr-scale-pole.is-right').textContent,
      parseFloat(n.querySelector('.zr-scale-dot').style.left)]),
    split: [...root.querySelectorAll('.zr-split-seg')].map(
      n => parseFloat(n.style.width)),
    cards: [...root.querySelectorAll('.zr-card')].map(n => ({
      key: n.querySelector('.zr-card-key').textContent,
      line: n.querySelector('.zr-card-line').textContent.trim(),
      icon: !!n.querySelector('.zr-card-icon svg path'),
      lock: !!n.querySelector('.zr-card-lock svg path'),
      lead: n.classList.contains('is-lead')})),
    free: root.querySelectorAll('.zr-free .zr-strength-title').length,
    lockedNodes: root.querySelectorAll('.zr-node.is-locked').length,
    balance: root.querySelectorAll('.zr-bal').length
  };
}"""

DELIVERED = """(args) => {
  const {cfg, content} = args;
  const images = {};
  cfg.swipe.steps.forEach(st => (st.pairs || []).forEach(
    p => (p.images || []).forEach(i => { images[i.id] = i; })));
  const ctx = {
    cfg: cfg, delivered: true, complete: true,
    style: {id: content.style_id, name: content.style_name, blurb: "",
            tags: [], reveals: {}},
    sign: content.sign || "", purpose: content.purpose || "",
    elements: [], visuals: content.visuals || {}, images: images,
    sections: (content.sections || []).map(s => ({
      id: s.id, title: s.title, data: s.data, locked: false})),
    version: content.version || ""
  };
  document.body.innerHTML = "";
  const root = document.createElement("div");
  root.className = "result-module";
  document.body.appendChild(root);
  window.MazzinResult.delivered(root, ctx);
  const text = sel => {
    const n = root.querySelector(sel);
    return n ? n.textContent.trim() : null;
  };
  return {
    subtype: text('.zr-subtype'),
    formula: text('.zr-formula'),
    cross: text('.zr-crossline'),
    scales: root.querySelectorAll('.zr-scale').length,
    split: root.querySelectorAll('.zr-split-seg').length,
    band: root.querySelectorAll('.zr-hero .zr-band img').length,
    keys: [...root.querySelectorAll('.zr-node-key')].map(
      n => n.textContent.trim()),
    offers: root.querySelectorAll('.zr-offer').length
  };
}"""


def browser_checks(page):
    print("\n--- the module draws it, in a browser, on both funnels ---")
    for slug in FUNNELS:
        cfg = CFG[slug]
        for style_id, second, energy in combos():
            scores = scores_for(style_id, second, energy)
            got = page.evaluate(HARNESS, {
                "cfg": cfg, "styleId": style_id, "scores": scores,
                "signId": "sign_leo", "first": None})
            mine = reports._reader_profile(cfg, STYLES[style_id], scores,
                                           "Leo")
            check("  %-9s %-15s %-6s %-4s draws %s"
                  % (slug, style_id, second, energy, mine["subtype"]),
                  got["subtype"] == mine["subtype"]
                  and got["formula"] == mine["formula"]
                  and got["ribbon"] == mine["rarity_line"]
                  and got["cross"] == mine["cross_line"]
                  and got["caption"] == mine["split_caption"]
                  and got["split"] == [c["pct"] for c in mine["split"]]
                  and got["scales"] == [[r["left"], r["right"], r["at"]]
                                        for r in mine["scales"]],
                  "%s vs %s" % (got["subtype"], mine["subtype"]))

    print("\n--- and the page under the card is the new one ---")
    cfg = CFG["zodiac"]
    got = page.evaluate(HARNESS, {
        "cfg": cfg, "styleId": "celestial_air",
        "scores": scores_for("celestial_air", "fire", "sun"),
        "signId": "sign_leo", "first": None})
    check("the element balance chart is gone", got["balance"] == 0)
    check("  and so is every locked constellation node",
          got["lockedNodes"] == 0)
    check("the free strength is still there, on its own",
          got["free"] == 1)
    check("six cards, in the order the config lists them",
          [c["key"] for c in got["cards"]]
          == ["%s:" % row["key"] for row in CARDS],
          str([c["key"] for c in got["cards"]]))
    check("  every one keyword-first, with an icon and a lock",
          all(c["line"].startswith(c["key"] + " ") and c["icon"] and c["lock"]
              for c in got["cards"]),
          str([c["line"][:30] for c in got["cards"]]))
    check("  and no brace left showing on any of them",
          not [c for c in got["cards"] if "{" in c["line"]],
          str([c["line"] for c in got["cards"] if "{" in c["line"]]))
    blind = [c for c in got["cards"] if c["key"] == "Blind spots:"][0]["line"]
    check("  the moon token answered from what they tapped",
          "{" not in blind and "pick revealed" in blind, blind)
    plan = [c for c in got["cards"] if c["key"] == "Blueprint:"][0]["line"]
    check("  and the blueprint names the lead and the undercurrent",
          "Air" in plan and "Fire" in plan, plan)
    check("the bridge and the offer both name the subtype",
          "Solar Spark" in got["bridge"] and "Solar Spark" in got["offerHead"]
          and "6 chapters" in got["offerHead"],
          "%s / %s" % (got["bridge"], got["offerHead"]))
    check("  and the bridge's article agrees with the name after it",
          " a Solar Spark" in got["bridge"], got["bridge"])
    vowel = page.evaluate(HARNESS, {
        "cfg": cfg, "styleId": "deep_water",
        "scores": scores_for("deep_water", "fire", "moon"),
        "signId": "sign_leo", "first": None})
    check("    which for The Underglow means an, not a",
          " an Underglow" in vowel["bridge"], vowel["bridge"])

    print("\n--- what the reader said they came for still moves first ---")
    love = page.evaluate(HARNESS, {
        "cfg": CFG["zodiac30"], "styleId": "celestial_air",
        "scores": scores_for("celestial_air", "fire", "sun"),
        "signId": "sign_leo", "first": "purpose_love"})
    check("the Love card is first, and it is the one wearing the border",
          love["cards"][0]["key"] == "Love:" and love["cards"][0]["lead"]
          and sum(1 for c in love["cards"] if c["lead"]) == 1,
          str([(c["key"], c["lead"]) for c in love["cards"]]))
    check("  and it says the thing they came for",
          "came for" in love["cards"][0]["line"], love["cards"][0]["line"])
    plain = page.evaluate(HARNESS, {
        "cfg": CFG["zodiac"], "styleId": "celestial_air",
        "scores": scores_for("celestial_air", "fire", "sun"),
        "signId": "sign_leo", "first": None})
    check("the twin, which asks no such question, promotes nothing",
          not [c for c in plain["cards"] if c["lead"]]
          and plain["cards"][0]["key"] == "Love:",
          str([(c["key"], c["lead"]) for c in plain["cards"]]))

    print("\n--- and the delivered page opens on the same card ---")
    got = page.evaluate(DELIVERED, {"cfg": CFG["zodiac"], "content": content})
    check("the hero is the stored subtype and formula",
          got["subtype"] == stored["subtype"]
          and got["formula"] == stored["formula"],
          "%s / %s" % (got["subtype"], got["formula"]))
    check("  with its scales, its split and its sign line",
          got["scales"] == 3 and got["split"] == 4
          and got["cross"] == stored["cross_line"], str(got["scales"]))
    check("  and the horizon they chose still under it", got["band"] == 1)
    keys = {c["id"]: c["key"] for c in CARDS}
    check("every section is headed by its card's keyword",
          got["keys"] == ["%s:" % keys[s["id"]] for s in content["sections"]],
          str(got["keys"]))
    check("  and no offer card is on a page already paid for",
          got["offers"] == 0)
    old = json.loads(json.dumps(content))
    old["visuals"].pop("profile", None)
    was = page.evaluate(DELIVERED, {"cfg": CFG["zodiac"], "content": old})
    check("a report written before any of this gets the card it always got",
          was["subtype"] is None and was["scales"] == 0, str(was["subtype"]))


def main():
    with sync_playwright() as pw:
        browser = pw.chromium.launch(executable_path=CHROME)
        page = browser.new_page(viewport={"width": 390, "height": 844})
        errors = []
        page.on("pageerror", lambda e: errors.append(str(e)))
        page.goto("about:blank")
        page.add_script_tag(
            content=open(os.path.join(REPO, "static/js/result_zodiac.js"),
                         encoding="utf-8").read())
        page.add_style_tag(
            content=open(os.path.join(REPO, "static/css/result_zodiac.css"),
                         encoding="utf-8").read())
        check("the module loads and exports both halves",
              page.evaluate("!!(window.MazzinResult && MazzinResult.render"
                            " && MazzinResult.delivered)"))
        browser_checks(page)
        check("nothing threw on the way through", not errors, str(errors))
        browser.close()

    print("\n%d checks, %d failed" % (checks[0], len(fails)))
    for line in fails:
        print("  FAIL " + line)
    return 1 if fails else 0


if __name__ == "__main__":
    sys.exit(main())
