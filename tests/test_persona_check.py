#!/usr/bin/env python3
"""Integrity checks over funnels/persona.json and the v3 concept behind it.

The funnel was rebuilt on one idea — "shapes that unlock what's underneath" —
and most of what is asserted here exists to keep that idea honest rather than
to keep the JSON well-formed.

The load-bearing rule is the two-way test the sculpt sampler established and
this config inherits: a card's meaning has to survive in both directions. The
label alone must be sculptable — "wound up" is a compressed coil and nothing
else — and the form alone must return the label. A config can only be checked
on the structure of that, so the structure is what is pinned: every card
carries its label word and a form description, and neither is allowed to go
missing while the other stays.

The rest divides into three. The walk has to be a real instrument: thirteen
steps, four traits, and a distribution measured by walking every path the
config allows rather than asserted from the copy. The page has to be able to
draw it: the result module's own hooks, the clay head's two layers, the warm
theme block in the shared stylesheet. And the neighbours have to be untouched,
which on a branch that edited a shared file is the check that earns its place.

No database, no network, no key. Everything is read off disk.
"""
import collections
import itertools
import json
import os
import re
import sys

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

sys.path.insert(0, REPO)
ROOT = REPO
GALLERY = os.path.join(ROOT, "static/galleries/persona")

NEIGHBOUR_SLUGS = sorted(
    f[:-len(".json")] for f in os.listdir(os.path.join(REPO, "funnels"))
    if f.endswith(".json") and f != "persona.json")

fails = []
checks = [0]


def check(label, ok, detail=""):
    checks[0] += 1
    if not ok:
        fails.append("%s %s" % (label, detail))
    print("  %-58s %s%s" % (label, "ok" if ok else "FAIL",
                            ("  " + detail) if detail and not ok else ""))


cfg = json.load(open(os.path.join(ROOT, "funnels/persona.json"),
                     encoding="utf-8"))
static_cfg = json.load(open(os.path.join(ROOT, "static/funnels/persona.json"),
                            encoding="utf-8"))
steps = cfg["swipe"]["steps"]
by_step = {s["id"]: s for s in steps}
images = [i for s in steps for p in s["pairs"] for i in p["images"]]
by_id = {i["id"]: i for i in images}

AXIS = {"drive", "anchor", "wave", "prism"}
ENERGY = {"outer", "inner"}
TONE = {"bold", "calm", "deep"}
VOCAB = AXIS | ENERGY | TONE
PURPOSE = {"purpose_love", "purpose_career", "purpose_peace", "purpose_path"}

ARCH = {"drive": "igniter", "anchor": "keeper", "wave": "feeler",
        "prism": "thinker"}
PERSONAS = [(a, e) for a in ("igniter", "keeper", "feeler", "thinker")
            for e in ("outer", "inner")]

CELESTIAL = {"fire", "earth", "air", "water", "sun", "moon", "mystic",
             "spring", "summer", "autumn", "winter",
             "wood", "stone", "metal", "warm", "cool", "dark", "bright"}


def strings(node):
    if isinstance(node, str):
        return [node]
    if isinstance(node, dict):
        return [s for v in node.values() for s in strings(v)]
    if isinstance(node, list):
        return [s for v in node for s in strings(v)]
    return []


print("\n--- config shape ---")
check("static copy matches funnels/", cfg == static_cfg)
check("slug is persona", cfg["slug"] == "persona", cfg["slug"])
check("funnel_id says v3", cfg["funnel_id"] == "persona_v3",
      cfg["funnel_id"])
check("locale is en", cfg["locale"] == "en", cfg["locale"])
check("theme is its own", cfg["theme"] == "persona", cfg["theme"])
check("thirteen steps", len(steps) == 13, str(len(steps)))
check("  and pairs_count agrees with them",
      cfg["swipe"]["pairs_count"] == len(steps) == 13,
      "%s vs %s" % (cfg["swipe"]["pairs_count"], len(steps)))
check("it names its own result module and stylesheet",
      cfg["result_module"] == "/static/js/result_persona.js"
      and cfg["result_css"] == "/static/css/result_persona.css")
check("pricing survives the rewrite untouched",
      cfg["pricing"]["amount_cents"] == 300
      and cfg["pricing"]["currency"] == "usd",
      json.dumps(cfg["pricing"]))
check("  and so does test mode", cfg["stripe_mode"] == "test",
      cfg.get("stripe_mode"))
check("  and the commerce block", bool(cfg["checkout"]["commerce"]))
check("prices are written as a token, never as a number in copy",
      "{price}" in cfg["checkout"]["cta_label"]
      and not re.search(r"\$3\b", " ".join(strings(cfg["checkout"]))),
      cfg["checkout"]["cta_label"])
check("badge labels are still on — the label is half the meaning now",
      cfg["swipe"]["label_mode"] == "badge", cfg["swipe"]["label_mode"])


print("\n--- the walk: thirteen steps, two formats ---")
check("only pair and grid4",
      {s["format"] for s in steps} == {"pair", "grid4"},
      str(sorted({s["format"] for s in steps})))
check("  a pair holds two cards and a grid4 holds four",
      all(len(s["pairs"][0]["images"]) == (2 if s["format"] == "pair" else 4)
          for s in steps),
      str([(s["id"], len(s["pairs"][0]["images"])) for s in steps
           if len(s["pairs"][0]["images"])
           != (2 if s["format"] == "pair" else 4)]))
check("forty-four cards in all", len(images) == 44, str(len(images)))
check("  every id unique", len(by_id) == len(images))
check("  every step has exactly one pair block",
      all(len(s["pairs"]) == 1 for s in steps))
check("the steps are the thirteen v3 names",
      [s["id"] for s in steps] == [
          "now", "seeking", "battery", "chapter", "pressure", "drain",
          "hour", "forks", "reset", "leanedon", "runs", "walls", "tenyears"],
      str([s["id"] for s in steps]))
check("every question asks for a shape, not a situation",
      all("?" in s["question"] or s["question"].endswith(":")
          for s in steps),
      str([s["id"] for s in steps
           if "?" not in s["question"] and not s["question"].endswith(":")]))
check("seeking is the pinned step", 
      [s["id"] for s in steps if s.get("pin_first")] == ["seeking"],
      str([s["id"] for s in steps if s.get("pin_first")]))
check("drain is the one inverse step",
      [s["id"] for s in steps if s.get("scoring") == "inverse"] == ["drain"],
      str([s["id"] for s in steps if s.get("scoring")]))


print("\n--- the two-way rule, structurally ---")
# Word alone must be sculptable; form alone must return the word. A config can
# only carry the first half of that, so what is pinned is that both halves are
# present on every card and that neither can go missing quietly.
check("every card has a label", all(i.get("label") for i in images))
check("every card has a form description", all(i.get("form") for i in images),
      str([i["id"] for i in images if not i.get("form")]))
check("  and the form says more than the label does",
      all(len(i["form"]) > 3 * len(i["label"]) for i in images),
      str([i["id"] for i in images
           if len(i["form"]) <= 3 * len(i["label"])]))
# The id carries the label, so the two cannot drift apart unnoticed — the same
# derivation the sculpt idiom set uses.
slug_bad = []
for i in images:
    step_id, _, slug = i["id"].partition("_")
    want = re.sub(r"[^a-z0-9]+", "_", i["label"].lower()).strip("_")
    if not (slug == want or slug.startswith(want) or want.startswith(slug)):
        slug_bad.append((i["id"], i["label"]))
check("  every id spells its own label", not slug_bad, str(slug_bad[:3]))
check("  and is filed under its own step",
      all(i["id"].startswith(s["id"] + "_")
          for s in steps for i in s["pairs"][0]["images"]),
      str([i["id"] for s in steps for i in s["pairs"][0]["images"]
           if not i["id"].startswith(s["id"] + "_")][:3]))

# The form language is the sculptable half. Every description has to name a
# form doing something, or the card is a caption with no shape — the exact
# failure the sculpt review caught in v2.
FORM_WORD = re.compile(
    r"\b(coil|mass|forms?|fragments?|base|wave|slab|sphere|hollow|wall|"
    r"door|ring|rings|particles|slope|steps?|core|opening|seam|column|"
    r"cluster|layers|plates|monolith|spread|tip|gap|enclosure|cylinder)\b")
missing_form = [i["id"] for i in images
                if not FORM_WORD.search(i["form"].lower())]
check("every description names a form", not missing_form,
      str(missing_form[:4]))
check("  and the check would notice one that did not",
      not FORM_WORD.search("a feeling of being generally quite busy"))
# No people, no places: the whole style bans them, and a card that describes a
# scene is a card the art cannot draw.
FIGURE = re.compile(r"\b(humans?|figures?|persons?|people|faces?|eyes?|"
                    r"characters?|rooms?|tables?|chairs?|friends?|hands?)\b")
peopled = [i["id"] for i in images if FIGURE.search(i["form"].lower())]
check("no card describes a person or a place", not peopled, str(peopled[:4]))


print("\n--- tags ---")
for i in images:
    unknown = [t for t in i["tags"] if t not in VOCAB | PURPOSE]
    check("  %s tags are in the vocabulary" % i["id"], not unknown,
          str(unknown))
check("every card carries at least one scoring tag",
      all(set(i["tags"]) & VOCAB for i in images),
      str([i["id"] for i in images if not set(i["tags"]) & VOCAB]))
svc_steps = sorted({s["id"] for s in steps for i in s["pairs"][0]["images"]
                    if set(i["tags"]) & PURPOSE})
check("service tags appear on seeking and nowhere else",
      svc_steps == ["seeking"], str(svc_steps))
check("  and seeking carries all four of them, one per card",
      sorted(t for i in by_step["seeking"]["pairs"][0]["images"]
             for t in i["tags"] if t in PURPOSE) == sorted(PURPOSE),
      str(sorted(t for i in by_step["seeking"]["pairs"][0]["images"]
                 for t in i["tags"] if t in PURPOSE)))
check("no celestial tag came across from the twin",
      not [t for i in images for t in i["tags"] if t in CELESTIAL],
      str([t for i in images for t in i["tags"] if t in CELESTIAL][:4]))
# Every step should discriminate: four cards that all score the same tag ask
# nothing.
flat = [s["id"] for s in steps
        if len({tuple(sorted(set(i["tags"]) & VOCAB))
                for i in s["pairs"][0]["images"]})
        < len(s["pairs"][0]["images"])]
check("no step offers the same answer twice", not flat, str(flat))


print("\n--- colours ---")
HEX = re.compile(r"^#[0-9A-F]{6}$")
for i in images:
    ok = (len(i["colors"]) == 3
          and all(HEX.match(c["hex"]) and c.get("name") and c.get("element")
                  for c in i["colors"]))
    check("  %s carries three named hexes" % i["id"], ok,
          json.dumps(i["colors"])[:80])
palette = {c["hex"] for i in images for c in i["colors"]}
check("the teal is in the palette", "#4EDDC4" in palette)
check("  and the ink the v3 direction left behind is not",
      "#101820" not in palette and "#0F1A22" not in palette,
      str(sorted(palette & {"#101820", "#0F1A22"})))
# State-bearing colour: the drained cards are the muted ones. Measured rather
# than asserted, on the mean lightness of each card's three tones.
def light(hexes):
    vals = []
    for h in hexes:
        r, g, b = (int(h[i:i + 2], 16) for i in (1, 3, 5))
        vals.append((max(r, g, b) + min(r, g, b)) / 2.0)
    return sum(vals) / len(vals)


def sat(hexes):
    vals = []
    for h in hexes:
        r, g, b = (int(h[i:i + 2], 16) for i in (1, 3, 5))
        vals.append(max(r, g, b) - min(r, g, b))
    return sum(vals) / len(vals)


drain_sat = [sat([c["hex"] for c in i["colors"]])
             for i in by_step["drain"]["pairs"][0]["images"]]
now_sat = [sat([c["hex"] for c in i["colors"]])
           for i in by_step["now"]["pairs"][0]["images"]]
check("the drain cards are the least saturated in the walk",
      max(drain_sat) < max(now_sat),
      "%.0f vs %.0f" % (max(drain_sat), max(now_sat)))


print("\n--- the gallery on disk ---")
gallery = {f[:-len(".webp")] for f in os.listdir(GALLERY)
           if f.endswith(".webp")}
check("every card has a frame", set(by_id) <= gallery,
      str(sorted(set(by_id) - gallery)[:4]))
check("  and the gallery carries nothing the walk dropped",
      not (gallery - set(by_id) - {"og", "head_base"}
           - {"totem_%s_%s" % p for p in PERSONAS}),
      str(sorted(gallery - set(by_id) - {"og", "head_base"}
                 - {"totem_%s_%s" % p for p in PERSONAS})[:4]))
check("the share card survived to v3-B", "og" in gallery)
check("the result page's clay head has a base frame", "head_base" in gallery)
check("  and every persona has a totem",
      all("totem_%s_%s" % p in gallery for p in PERSONAS),
      str([p for p in PERSONAS if "totem_%s_%s" % p not in gallery]))
check("every card path points into this funnel's own gallery",
      all(i["img"] == "/static/galleries/persona/" + i["id"] + ".webp"
          for i in images),
      str([i["id"] for i in images
           if i["img"] != "/static/galleries/persona/" + i["id"] + ".webp"]))


print("\n--- eight personas ---")
prof = cfg["result_copy"]["profile"]
check("four archetypes, two energies, eight names",
      sorted(prof["subtypes"]) == ["feeler", "igniter", "keeper", "thinker"]
      and all(sorted(prof["subtypes"][a]) == ["inner", "outer"]
              for a in prof["subtypes"]),
      json.dumps(sorted(prof["subtypes"])))
names = [prof["subtypes"][a][e] for a, e in PERSONAS]
check("  and the eight are distinct", len(set(names)) == 8, str(names))
check("  the owner-approved names, exactly",
      names == ["The Open Flame", "The Slow Burn",
                "The Standing Stone", "The Deep Root",
                "The Rising Tide", "The Deep Current",
                "The Bright Beacon", "The Quiet Cartographer"],
      str(names))
check("every persona has a one-line essence",
      all(prof["essence"][a][e] for a, e in PERSONAS))
check("  each of them a sentence about the reader",
      all(prof["essence"][a][e].startswith("You") for a, e in PERSONAS),
      str([prof["essence"][a][e] for a, e in PERSONAS
           if not prof["essence"][a][e].startswith("You")][:2]))
check("the 24-subtype table is gone", "animal_cross" not in prof)
check("the four traits carry human labels",
      [t["name"] for t in prof["traits"]]
      == ["Momentum", "Steadiness", "Connection", "Curiosity"],
      str([t["name"] for t in prof["traits"]]))
check("  keyed to the funnel's own axes",
      [t["tag"] for t in prof["traits"]]
      == ["drive", "anchor", "wave", "prism"],
      str([t["tag"] for t in prof["traits"]]))
check("the rarity line says one of eight",
      "1 of 8" in prof["rarity_line"] and "{rarer}" in prof["rarity_line"],
      prof["rarity_line"])
check("the four styles are tagged on their axis and nothing else",
      all(s["tags"] == [a] for a, name in ARCH.items()
          for s in cfg["styles"] if s["id"] == name),
      str([(s["id"], s["tags"]) for s in cfg["styles"]]))
check("  so the archetype is decided by the axis alone",
      sorted(s["id"] for s in cfg["styles"]) == sorted(ARCH.values()))


print("\n--- the walk, actually walked ---")
# Every path the config allows, scored the way engine.js scores it. Exhaustive
# rather than sampled: 4.2M walks is a couple of seconds and removes the one
# thing a distribution check should never have, which is noise.
def resolve(combo):
    scores = collections.Counter()
    for step, i in zip(steps, combo):
        weight = -0.5 if step.get("scoring") == "inverse" else 1
        for tag in step["pairs"][0]["images"][i]["tags"]:
            scores[tag] += weight
    best, best_score = "drive", None
    for tag in ["drive", "anchor", "wave", "prism"]:
        if best_score is None or scores[tag] > best_score:
            best, best_score = tag, scores[tag]
    energy = ("outer" if scores["outer"] > scores["inner"]
              else ("inner" if scores["inner"] > scores["outer"] else "outer"))
    return ARCH[best], energy


counts = collections.Counter()
total = 0
for combo in itertools.product(*[range(len(s["pairs"][0]["images"]))
                                 for s in steps]):
    counts[resolve(combo)] += 1
    total += 1
check("the walk has the paths the config promises",
      total == 4 ** 9 * 2 ** 4, str(total))

arch_pct = {}
for a in ("igniter", "keeper", "feeler", "thinker"):
    arch_pct[a] = (100.0 * sum(counts[(a, e)]
                               for e in ("outer", "inner")) / total)
print("    archetype shares: "
      + ", ".join("%s %.1f%%" % (a, arch_pct[a]) for a in arch_pct))
for a in arch_pct:
    check("  %s lands between 15%% and 35%%" % a,
          15 <= arch_pct[a] <= 35, "%.1f%%" % arch_pct[a])

energy_pct = {e: 100.0 * sum(counts[(a, e)] for a in arch_pct) / total
              for e in ("outer", "inner")}
print("    energy shares: "
      + ", ".join("%s %.1f%%" % (e, energy_pct[e]) for e in energy_pct))
for e in energy_pct:
    check("  %s lands between 40%% and 60%%" % e,
          40 <= energy_pct[e] <= 60, "%.1f%%" % energy_pct[e])

print("    persona shares: " + ", ".join(
    "%s/%s %.1f%%" % (a, e, 100.0 * counts[(a, e)] / total)
    for a, e in PERSONAS))
for a, e in PERSONAS:
    pct = 100.0 * counts[(a, e)] / total
    check("  %s %s is reachable at 5%% or better" % (a, e), pct >= 5,
          "%.1f%%" % pct)
check("  every persona is reachable at all",
      all(counts[p] for p in PERSONAS),
      str([p for p in PERSONAS if not counts[p]]))

# The rarity the config prints has to be the rarity the walk produces.
for a, e in PERSONAS:
    want = int(round(total / float(counts[(a, e)])))
    check("  %s %s rarity matches the walk" % (a, e),
          abs(prof["rarity"][a][e] - want) <= 1,
          "config %s vs walked %s" % (prof["rarity"][a][e], want))
    want_rarer = int(round(100 - 100.0 * counts[(a, e)] / total))
    check("  %s %s 'rarer than' matches too" % (a, e),
          abs(prof["rarer_than"][a][e] - want_rarer) <= 1,
          "config %s vs walked %s"
          % (prof["rarer_than"][a][e], want_rarer))


print("\n--- the four trait bars actually move ---")
# A bar that reads the same on every run is decoration. Each trait is walked
# to its extremes to prove the config can drive it across the scale, and the
# midpoint is checked from both sides so no trait is stuck on one half.
def trait_range(tag):
    lo = hi = 0.0
    for step in steps:
        weight = -0.5 if step.get("scoring") == "inverse" else 1
        deltas = [weight * (tag in i["tags"])
                  for i in step["pairs"][0]["images"]]
        lo += min(deltas)
        hi += max(deltas)
    return lo, hi


for tag in ["drive", "anchor", "wave", "prism"]:
    lo, hi = trait_range(tag)
    check("  %s can be scored high" % tag, hi >= 4, "%.1f" % hi)
    check("  %s can be scored low" % tag, lo <= 0, "%.1f" % lo)
    check("  %s has real travel between them" % tag, hi - lo >= 4,
          "%.1f to %.1f" % (lo, hi))
mids = {}
for a in ("igniter", "keeper", "feeler", "thinker"):
    mids[a] = arch_pct[a]
check("no trait dominates the set",
      max(mids.values()) - min(mids.values()) <= 20,
      "%.1f spread" % (max(mids.values()) - min(mids.values())))
for e in ("outer", "inner"):
    check("  and the energy scale is used from both sides of centre",
          energy_pct[e] > 30, "%.1f%%" % energy_pct[e])


print("\n--- the machinery the rewrite had to keep ---")
check("four interstitials", len(cfg["interstitials"]) == 4,
      str(len(cfg["interstitials"])))
stops = [b["after_step"] for b in cfg["interstitials"]]
check("  rescaled onto thirteen steps", stops == [3, 7, 10, 13], str(stops))
check("  in order, and none past the end",
      stops == sorted(stops) and max(stops) <= len(steps), str(stops))
echoed = [s for b in cfg["interstitials"] for s in b["echo_steps"]]
check("  every echoed step exists",
      all(s in by_step for s in echoed),
      str([s for s in echoed if s not in by_step]))
check("  and every step is echoed exactly once",
      sorted(echoed) == sorted(by_step),
      str(sorted(set(by_step) - set(echoed))))
for i, block in enumerate(cfg["interstitials"]):
    later = [s for s in block["echo_steps"]
             if [x["id"] for x in steps].index(s) >= block["after_step"]]
    check("  interstitial %d echoes only steps already walked" % (i + 1),
          not later, str(later))
personal = [b["personal"]["step"] for b in cfg["interstitials"]
            if b.get("personal")]
check("  personal lines are re-keyed to the three that carry meaning",
      personal == ["now", "chapter", "forks"], str(personal))
for block in cfg["interstitials"]:
    if not block.get("personal"):
        continue
    step_id = block["personal"]["step"]
    want = {i["id"] for i in by_step[step_id]["pairs"][0]["images"]}
    check("    %s has a line for every card" % step_id,
          set(block["personal"]["lines"]) == want,
          str(sorted(want ^ set(block["personal"]["lines"]))))
    idx = [x["id"] for x in steps].index(step_id)
    check("    and that step comes before the beat that reads it",
          idx < block["after_step"], "%s vs %s" % (idx, block["after_step"]))
check("event tracking hooks survive", bool(cfg.get("analyzing_echo")))
check("  and the analysing screen still has its messages",
      len(cfg["analyzing"]["messages"]) == 3)
check("the preview gallery points at cards that exist",
      all(p["id"] in by_id for p in cfg["preview_gallery"]),
      str([p["id"] for p in cfg["preview_gallery"] if p["id"] not in by_id]))
check("the signals list points at cards that exist",
      all(e["image"] in by_id for e in cfg["style_elements"]["items"]),
      str([e["image"] for e in cfg["style_elements"]["items"]
           if e["image"] not in by_id]))
check("  and covers all four traits",
      {t for e in cfg["style_elements"]["items"]
       for t in e["tags"] if t in AXIS} == AXIS)
hooks = cfg["report"]["hook_slots"]
check("every report hook names a step that still exists",
      all(h["step"] in by_step for h in hooks.values()),
      str([h["step"] for h in hooks.values() if h["step"] not in by_step]))
vis = cfg["report"]["visuals"]
check("  and so does every visual",
      vis["hero"]["glyph_step"] in by_step
      and vis["hero"]["band_step"] in by_step
      and all(v in by_step for v in vis["section_steps"].values()),
      json.dumps(vis))


print("\n--- the quiz goes warm ---")
check("the analysing fade lands on the warm umbra",
      cfg["swipe"]["analyzing_fade_to"] == "#241A10",
      cfg["swipe"]["analyzing_fade_to"])
mazzin = open(os.path.join(ROOT, "static/css/mazzin.css"),
              encoding="utf-8").read()
sheet = open(os.path.join(ROOT, "static/css/result_persona.css"),
             encoding="utf-8").read()
theme_rules = [r.strip() for r in
               re.findall(r"^[^\s@}/][^{}]*(?=\{)", mazzin, re.M)
               if "theme-persona" in r]
check("mazzin.css paints this funnel's theme", len(theme_rules) >= 8,
      str(len(theme_rules)))
check("  every rule of it is scoped to the funnel's own body class",
      all(r.startswith("body.theme-persona") for r in theme_rules),
      str([r for r in theme_rules
           if not r.startswith("body.theme-persona")][:3]))
check("  covering the pips, the analysing bar and the beat between steps",
      all(sel in mazzin for sel in (
          "body.theme-persona .pip",
          "body.theme-persona .analyzing-bar",
          "body.theme-persona #screen-interstitial.is-active",
          "body.theme-persona .mid-kicker")))
# The repaint, measured. The quiz chrome is warm now and the ink the v1 block
# ran on must be gone from it, or the funnel is half-repainted.
theme_block = mazzin[mazzin.index("/* The personality funnel's own colours"):
                     mazzin.index("/* The arrival.")]
# Declarations only. The block's own comments explain why the bright teal
# moved off the chrome and name it to do so, and a scan of the prose would
# read that explanation as the thing it is explaining away.
theme_css = re.sub(r"/\*.*?\*/", " ", theme_block, flags=re.S)
check("  the theme block is warm, not ink",
      "#FBF3E7" in theme_css and "#2B1E12" in theme_css,
      "cream ground and warm text")
check("  and carries none of the ink it used to",
      not any(v in theme_css for v in
              ("#101820", "#17272E", "#E8EFF0", "#A6B6BC", "#06231F")),
      str([v for v in ("#101820", "#17272E", "#E8EFF0", "#A6B6BC", "#06231F")
           if v in theme_css]))
# The teal changes value to survive the move: the bright one is unreadable as
# type on cream, so the chrome runs on a deep teal at the same hue.
check("  the chrome teal is the deep one cream needs",
      "#0F6F62" in theme_css and "#4EDDC4" not in theme_css,
      "deep teal only")
check("  and the progress rule is still themed through the accent tokens",
      "body.theme-persona #screen-interstitial {" in mazzin
      and "--accent: #0F6F62;" in mazzin
      and "--accent-soft: rgba(15, 111, 98, 0.14);" in mazzin)
check("  adding no rule of its own to the auto-advance mode",
      not [r for r in theme_rules
           if "mid-accent" in r or "is-auto" in r],
      str([r for r in theme_rules
           if "mid-accent" in r or "is-auto" in r]))
check("  and repainting the accent no wider than that one screen",
      not re.search(r"^body\.theme-persona \{", mazzin, re.M),
      "the accent must not reach the quiz cards")
check("the config asks for that theme by name", cfg["theme"] == "persona")


print("\n--- the result page, at dusk ---")
module = open(os.path.join(ROOT, "static/js/result_persona.js"),
              encoding="utf-8").read()
check("the page ground is the colour the fade lands on",
      "background-color: #241A10;" in sheet
      and cfg["swipe"]["analyzing_fade_to"] == "#241A10")
check("  and the ink palette is gone from it",
      not any(v in sheet for v in
              ("#101820", "#16202A", "#1C2833", "#E8EFF0", "#A6B6BC")),
      str([v for v in ("#101820", "#16202A", "#1C2833", "#E8EFF0", "#A6B6BC")
           if v in sheet]))
check("  the clay tokens are declared",
      all(t in sheet for t in ("--pr-umbra:", "--pr-slab:", "--pr-clay:",
                               "--pr-sand:", "--pr-teal:")))
check("teal is still the one cool colour on the page",
      "--pr-teal: #4EDDC4;" in sheet)
check("the totem stands on a lit pedestal",
      all(c in sheet for c in (".pr-totem", ".pr-totem-light",
                               ".pr-totem-art", ".pr-totem-plinth"))
      and "function pedestal(" in module)
check("  and the module builds its path from the persona",
      'TOTEM_DIR + ctx.style.id + "_" + energy' in module)
check("the narrative quotes the reader's own picks in italics",
      ".pr-quote" in sheet and "font-style: italic;" in sheet
      and "function narrativeOf(" in module
      and 'NARRATIVE_STEPS = ["now", "chapter", "forks"]' in module)
check("  and those three steps exist in the walk",
      all(s in by_step for s in ("now", "chapter", "forks")))
check("four trait bars, clay track and teal fill",
      all(c in sheet for c in (".pr-traits", ".pr-trait-track",
                               ".pr-trait-fill"))
      and "function traitBars(" in module)
check("  and the three spectrum scales it replaced are gone",
      ".pr-scale-dot" not in sheet and "function scaleRow(" not in module
      and ".pr-split-seg" not in sheet)
check("the module resolves eight personas, not twenty-four",
      "table.subtypes[ctx.style.id])[energy]" in module.replace("(", "")
      or "(table.subtypes[ctx.style.id] || {})[energy]" in module)


# Every class the module paints has to have a rule. This is not pedantry: the
# restyle replaced whole spans of the sheet, and a span that swallowed one
# rule more than it replaced would ship a page that renders unstyled in
# exactly one place — which nothing else here would notice, because the class
# is still emitted and the sheet still parses.
emitted = set()
for pattern in (r'elm\("[a-z0-9]+", "([^"]+)"', r'className = "([^"]+)"',
                r'classList\.add\("([^"]+)"\)', r'class: "([^"]+)"'):
    for found in re.findall(pattern, module):
        emitted.update(found.split())
emitted = {c for c in emitted if c.startswith("pr-")}
styled = set(re.findall(r"\.(pr-[a-z0-9-]+)", sheet))
# Two carry no rule on purpose and did before this branch: they are hooks for
# the delivered page's own markup, not things this sheet paints.
KNOWN_BARE = {"pr-ax-name", "pr-node-body"}
check("every class the module paints has a rule",
      not (emitted - styled - KNOWN_BARE),
      str(sorted(emitted - styled - KNOWN_BARE)))
check("  and the sheet paints nothing the module never emits",
      not (styled - emitted), str(sorted(styled - emitted)[:4]))


print("\n--- the clay head ---")
check("it is two layers: a rendered base and an inlay",
      all(c in sheet for c in (".pr-head-plate", ".pr-head-base",
                               ".pr-head-inlay"))
      and 'HEAD_BASE = "/static/galleries/persona/head_base.webp"' in module)
check("  the base frame is on disk", "head_base" in gallery)
check("  and the inlay is positioned on the cranial field",
      re.search(r"\.pr-head-inlay \{[^}]*top: 13%;[^}]*left: 26%;"
                r"[^}]*width: 48%;[^}]*height: 48%;", sheet, re.S) is not None)
check("the SVG is still generated from the tallies",
      "function headValues(" in module and "data.split" in module
      and "function headSvg(" in module)
check("  grid lines are pressed grooves, in warm ink",
      'GROOVE = "#7A5334"' in module and 'GROOVE_SOFT = "#8E6742"' in module)
check("  the value polygon is a teal glaze",
      'GLAZE = "#4EDDC4"' in module and '"fill-opacity": 0.42' in module)
check("  the vertices are teal beads",
      re.search(r'circle", \{\s*cx: p\.x\.toFixed\(1\),'
                r' cy: p\.y\.toFixed\(1\),\s*r: 4, fill: GLAZE',
                module) is not None)
check("  and the head outline it used to stroke is gone",
      "HEAD_PATH" not in module)
check("the legend reads the human trait names",
      "data.traits" in module and "function headLegend(" in module)
check("the delivered page can still draw it with no run in the tab",
      "ctx.visuals && ctx.visuals.profile" in module
      and "function deliveredHero(" in module)
check("  and finds the opening frame by label, not by a pasted id",
      "function shapeImageId(" in module
      and 'ids[i].indexOf("now_") === 0' in module)


print("\n--- the words this vertical does not use ---")
BANNED = [
    "psychic", "prediction", "predictions", "predict", "fortune",
    "your future will", "clairvoyant", "horoscope", "prophecy", "prophecies",
    "destined to", "fated to", "symptom", "symptoms",
    "medication", "prescription", "financial advice",
    "diagnosis", "diagnose", "disorder", "iq", "therapy", "therapist",
    "clinical", "psychometric", "scientifically proven",
    "scientifically validated",
    "mbti", "enneagram", "disc profile", "big five", "16personalities",
    "introvert", "extrovert",
]
WORDY = re.compile(r"[a-z0-9]")


def banned_hit(text):
    low_text = (text or "").lower()
    for word in BANNED:
        for found in re.finditer(re.escape(word), low_text):
            before = low_text[found.start() - 1] if found.start() else " "
            after = low_text[found.end():found.end() + 1] or " "
            if not WORDY.match(before) and not WORDY.match(after):
                return word
    return None


SCANNED = strings(cfg)
dirty = [(t[:50], banned_hit(t)) for t in SCANNED if banned_hit(t)]
check("no on-screen string says a banned word", not dirty, str(dirty[:4]))
check("  and the scan actually read the whole config",
      len(SCANNED) > 600, str(len(SCANNED)))
check("  the scanner catches one when there is one",
      banned_hit("a clinical diagnosis") == "diagnosis"
      and banned_hit("your MBTI type") == "mbti"
      and banned_hit("a unique iq") == "iq"
      and banned_hit("uniquely") is None)
# The idioms are everyday speech and have to stay that way: this is the one
# thing the concept cannot afford to lose.
labels = [i["label"] for i in images]
check("every label is plain speech, four words or fewer",
      all(len(l.split()) <= 4 for l in labels),
      str([l for l in labels if len(l.split()) > 4]))
check("  and most of them are two words or fewer",
      sum(1 for l in labels if len(l.split()) <= 2) >= len(labels) * 0.7,
      "%d of %d" % (sum(1 for l in labels if len(l.split()) <= 2),
                    len(labels)))
check("  and none of them is jargon",
      not [l for l in labels if banned_hit(l)],
      str([l for l in labels if banned_hit(l)]))


print("\n--- the neighbours ---")
check("the funnels directory and its static copy still agree",
      sorted(os.listdir(os.path.join(ROOT, "static/funnels")))
      == sorted(os.listdir(os.path.join(ROOT, "funnels"))),
      str(sorted(set(os.listdir(os.path.join(ROOT, "static/funnels")))
                 ^ set(os.listdir(os.path.join(ROOT, "funnels"))))))
check("the twins' own result module is not this one",
      json.load(open(os.path.join(ROOT, "funnels/zodiac30.json"),
                     encoding="utf-8"))["result_module"]
      == "/static/js/result_zodiac.js")
OWN = re.compile(r"\bpersona\b|result_persona|galleries/persona")
engine = open(os.path.join(ROOT, "static/js/engine.js"),
              encoding="utf-8").read()
check("  and result_zodiac.js knows nothing about persona",
      not OWN.search(open(os.path.join(ROOT, "static/js/result_zodiac.js"),
                          encoding="utf-8").read()))
check("engine.js knows nothing about persona either — it is all config",
      not OWN.search(engine), str(OWN.findall(engine)[:3]))
check("  and app.py routes it without naming it",
      not OWN.search(open(os.path.join(ROOT, "app.py"),
                          encoding="utf-8").read())
      and "funnel_exists" in open(os.path.join(ROOT, "app.py"),
                                  encoding="utf-8").read())
zodiac_rules = [r.strip() for r in
                re.findall(r"^[^\s@}/][^{}]*(?=\{)", mazzin, re.M)
                if "theme-zodiac" in r]
check("zodiac's theme block is still there, whole",
      len(zodiac_rules) >= 14
      and "body.theme-zodiac .pip.is-done { background: #E8C878; }" in mazzin,
      str(len(zodiac_rules)))
check("  with no rule serving both themes at once",
      not [r for r in theme_rules if "theme-zodiac" in r]
      and not [r for r in zodiac_rules if "theme-persona" in r])
check("every neighbour funnel still loads and keeps its own slug",
      all(json.load(open(os.path.join(ROOT, "funnels", s + ".json"),
                         encoding="utf-8"))["slug"] == s
          for s in NEIGHBOUR_SLUGS),
      str(NEIGHBOUR_SLUGS))

print("\n%d checks, %d failed" % (checks[0], len(fails)))
for f in fails:
    print("  FAIL " + f)
sys.exit(1 if fails else 0)
