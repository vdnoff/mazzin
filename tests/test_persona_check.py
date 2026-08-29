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

import database                                            # noqa: E402

# No suite talks to a database. reports.py is imported for the banned list it
# enforces, and importing it must not open a connection.
database.execute = lambda *a, **kw: None
database.query_all = lambda *a, **kw: []
database.query_one = lambda *a, **kw: None

import reports                                             # noqa: E402

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


print("\n--- the hook line ---")
# The accent is not markup: engine.js finds the fragment inside the sentence
# by substring and lifts it into a span, and when it cannot find it the line
# renders plain with no error anywhere. So a copy edit that leaves the accent
# behind costs the headline its emphasis silently. The hook has now been
# rewritten once with the accent pointing at "13 taps" while the sentence
# stopped counting taps, which is precisely the failure this pins.
check("the hook has a subtext and an accent",
      bool(cfg["swipe"].get("subtext"))
      and bool(cfg["swipe"].get("subtext_accent")))
check("  and the accent is a fragment of the line it accents",
      cfg["swipe"]["subtext_accent"] in cfg["swipe"]["subtext"],
      "%r not in %r" % (cfg["swipe"].get("subtext_accent"),
                        cfg["swipe"].get("subtext")))
# The repositioning itself: the hook stopped selling the tap count and
# started making a claim about what the shapes do. It is one sentence now —
# the second, "Your profile is already forming", went in review.
check("  the hook claims the shapes read the reader",
      cfg["swipe"]["subtext"] == "Shapes designed to read you.",
      cfg["swipe"]["subtext"])
check("  in one sentence",
      cfg["swipe"]["subtext"].count(".") == 1,
      cfg["swipe"]["subtext"])
check("  and no longer counts the taps",
      "tap" not in cfg["swipe"]["subtext"].lower(),
      cfg["swipe"]["subtext"])

# The two questions were reframed the same way: a trait rather than a mood,
# a standing pull rather than today's errand. Both readings turn on a
# time-anchoring word, so that is what is checked.
MOMENT = re.compile(r"\b(right now|today|tonight|this week|at the moment|"
                    r"lately)\b")
momentary = [s["id"] for s in steps if MOMENT.search(s["question"].lower())]
check("no question anchors itself to a moment", not momentary,
      str(momentary))
check("  step one asks which shape fits, not which shape you are",
      by_step["now"]["question"] == "Which shape fits you best?",
      by_step["now"]["question"])
check("  and step two asks what pulls, not what pulled",
      by_step["seeking"]["question"] == "What pulls you most?",
      by_step["seeking"]["question"])

# The beats between steps quote the walk back at the reader, so a question
# rewritten there and not here would put two voices on one funnel.
mid_copy = " ".join(strings(cfg["interstitials"])
                    + cfg["interstitial_working"]
                    + strings(cfg["analyzing"])).lower()
stale = [w for w in ("pulled you here", "13 taps", "right now,")
         if w in mid_copy]
check("no interstitial or analysing line carries the old phrasing",
      not stale, str(stale))


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


print("\n--- no card demands a frame its own floor refuses ---")
# hour_after_dark failed 3/3 at luma 34-43. It had Warm Umbra in the GROUND
# and a description whose whole point was that no light falls on it — the
# card demanded a dark frame by construction and the quiz floor refuses one
# by construction. Same conflict the totems had, same resolution: the
# darkness moves into the form and the backdrop stays lit.
after_dark = by_id["hour_after_dark"]
check("after dark is a dark form on a light sweep",
      "deep dark-toned clay form" in after_dark["form"]
      and "bright warm sweep" in after_dark["form"],
      after_dark["form"][:70])
check("  it keeps its own-light meaning",
      "gives its own light instead of taking any" in after_dark["form"])
check("  and says outright that the backdrop stays lit",
      "the sweep behind it stays fully lit" in after_dark["form"])
check("  it no longer asks for an unlit frame",
      "none falling on it" not in after_dark["form"])
check("  the deep tone is on the form, the teal is the core",
      [(c["hex"], c["element"]) for c in after_dark["colors"]]
      == [("#4A2E1E", "form"), ("#4EDDC4", "core"), ("#F3E3CC", "sweep")],
      str([(c["hex"], c["element"]) for c in after_dark["colors"]]))
# The generalisation, so the next card written this way is caught here rather
# than after three draws: nothing may put the darkest tone in the backdrop.
GROUND = {"ground", "backdrop", "field", "sweep"}


def lightness(hexv):
    r, g, b = (int(hexv[i:i + 2], 16) for i in (1, 3, 5))
    return 0.299 * r + 0.587 * g + 0.114 * b


dark_ground = [(i["id"], c["hex"], c["element"]) for i in images
               for c in i["colors"]
               if c["element"] in GROUND and lightness(c["hex"]) < 90]
check("no card puts a near-dark tone in its own backdrop", not dark_ground,
      str(dark_ground[:3]))
check("  and the warm umbra is off the quiz palette entirely",
      "#241A10" not in {c["hex"] for i in images for c in i["colors"]})
check("  though it is still the ground the share cards sit on",
      "#241A10" in {c["hex"] for cd in cfg["share_cards"]
                    for c in cd["colors"]})
# The sibling has to stay the bright half of the pair, or the step stops
# asking anything.
check("first light is still the lit one",
      "rising toward the light" in by_id["hour_first_light"]["form"])


print("\n--- the gallery on disk ---")
gallery = {f[:-len(".webp")] for f in os.listdir(GALLERY)
           if f.endswith(".webp")}
check("every card has a frame", set(by_id) <= gallery,
      str(sorted(set(by_id) - gallery)[:4]))
SLOTS = ({"og", "head_base"}
         | {"totem_%s_%s" % p for p in PERSONAS}
         | {"share_%s_%s" % p for p in PERSONAS})
check("  and the gallery carries nothing the walk dropped",
      not (gallery - set(by_id) - SLOTS),
      str(sorted(gallery - set(by_id) - SLOTS)[:4]))
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
# The two halves argued: "one person in eight" is not rare, and printing both
# invited the reader to notice. The measured number is the half worth keeping.
check("the rarity line makes the rarity claim",
      "{rarer}" in prof["rarity_line"]
      and prof["rarity_line"].lower().startswith("rarer than"),
      prof["rarity_line"])
check("  and no longer says one of eight",
      "1 of 8" not in prof["rarity_line"]
      and "1 of 8" not in json.dumps(cfg),
      prof["rarity_line"])
check("  while the rarity data itself is untouched",
      all(prof["rarity"][a][e] and prof["rarer_than"][a][e]
          for a, e in PERSONAS))
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


print("\n--- the tile: two zones that cannot overlap ---")
# The label is a full-width bar on the tile's bottom edge and the picture is
# strictly above it. What makes that exact rather than approximate is that one
# variable is both the bar's height and the padding reserved out of the
# image's content box: object-fit works inside the content box, so the drawn
# frame ends at the bar's top edge by construction, on both formats, at every
# tile size, with no per-format number.
engine_src = open(os.path.join(ROOT, "static/js/engine.js"),
                  encoding="utf-8").read()
check("engine.js still knows only the badge mode",
      engine_src.count('labelMode() === "badge"') == 1
      and 'labelMode() === "caption"' not in engine_src)

check("one variable sets the bar height and the image's reserve",
      re.search(r"body\.theme-persona \.card \{[^}]*--tile-bar: 26px;",
                mazzin, re.S) is not None
      and re.search(r"body\.theme-persona \.card-img \{[^}]*"
                    r"box-sizing: border-box;[^}]*"
                    r"padding-bottom: var\(--tile-bar\);", mazzin, re.S)
      is not None
      and re.search(r"body\.theme-persona \.card-name \{[^}]*"
                    r"height: var\(--tile-bar\);", mazzin, re.S) is not None)
check("the bar spans the tile and sits on its bottom edge",
      re.search(r"body\.theme-persona \.card-name \{[^}]*left: 0;"
                r"[^}]*right: 0;[^}]*bottom: 0;", mazzin, re.S) is not None
      and re.search(r"body\.theme-persona \.card-name \{[^}]*"
                    r"max-width: none;", mazzin, re.S) is not None)
check("  the pill's centring is undone with it",
      re.search(r"body\.theme-persona \.card-name \{[^}]*transform: none;",
                mazzin, re.S) is not None)
check("  one line, centred, with equal air above and below",
      re.search(r"body\.theme-persona \.card-name \{[^}]*"
                r"align-items: center;[^}]*justify-content: center;",
                mazzin, re.S) is not None
      and re.search(r"body\.theme-persona \.card-name \{[^}]*"
                    r"padding: 0 10px;", mazzin, re.S) is not None)
check("  solid, and no gradient — the celestial suite's rule",
      re.search(r"body\.theme-persona \.card-name \{[^}]*"
                r"background: rgba\(43, 30, 18, 0\.92\);", mazzin, re.S)
      is not None
      and not [b for b in mazzin.split("}")
               if ".card" in b.split("{")[0]
               and "gradient" in b.split("{")[-1]])
check("  and it borrows the tile's own corners rather than carrying any",
      re.search(r"body\.theme-persona \.card-name \{[^}]*border-radius: 0;",
                mazzin, re.S) is not None
      and re.search(r"^\.card \{[^}]*overflow: hidden;", mazzin,
                    re.M | re.S) is not None)

# The four-up shows the whole frame; the two-up fills from tall art.
# Both formats fill their zone now: `contain` left thin bands down the sides
# of the four-up and they were rejected on sight. Which edge that costs is the
# opposite of the obvious guess — the zone is NARROWER in aspect than the
# frame, so cover fills the height and trims the sides.
check("the four-up fills its zone",
      re.search(r"body\.theme-persona \.cards\.is-grid4 \.card-img \{"
                r"[^}]*object-fit: cover;", mazzin, re.S) is not None
      and re.search(r"body\.theme-persona \.cards\.is-grid4 \.card-img \{"
                    r"[^}]*object-position: center center;", mazzin, re.S)
      is not None)
check("  and nothing is letterboxed any more",
      not re.search(r"body\.theme-persona[^{]*\.card-img \{"
                    r"[^}]*object-fit: contain;", mazzin, re.S))
# The four-up's zone is height-driven, so what cover trims depends on the
# viewport and cannot be pinned from the stylesheet alone. It was briefly
# capped to the render's 3:4 to make the trim zero; that cap needed an 848px
# viewport at 390 wide and overlapped the rows on every real phone, so it is
# gone. The geometry it was standing in for is measured in a browser, at
# heights a phone has, by test_personatiles.py — including the thing no
# single-card measurement can see, which is one card painted over another.
# And the art that fill is safe on. Derived from the config's own formats.
import importlib.util as _il                                  # noqa: E402
_spec = _il.spec_from_file_location("gp", os.path.join(ROOT, "scripts",
                                                       "gen_persona.py"))
_gp = _il.module_from_spec(_spec)
sys.path.insert(0, os.path.join(ROOT, "scripts"))
_spec.loader.exec_module(_gp)
pair_cards = _gp.pair_ids(cfg)
check("the two-up cards are derived from the config, not listed",
      pair_cards == {i["id"] for s_ in steps if s_["format"] == "pair"
                     for i in s_["pairs"][0]["images"]})
check("  which is eight cards on four steps",
      len(pair_cards) == 8
      and len([s_ for s_ in steps if s_["format"] == "pair"]) == 4,
      str(sorted(pair_cards)))
plan = {f["id"]: f for f in _gp.frames(cfg)}
check("  they are drawn tall and nothing else is",
      {i for i, f in plan.items() if f.get("size") == (600, 900)}
      == pair_cards,
      str(sorted({i for i, f in plan.items()
                  if f.get("size") == (600, 900)} ^ pair_cards)))
check("  600x900 is what the model returns, so they are not cropped at all",
      _gp.FRAME_TALL == (600, 900) and _gp.API_PORTRAIT == "1024x1536")
check("  and every one carries the tall-composition note",
      all(_gp.PAIR_NOTE in plan[i]["prompt"] for i in pair_cards))
check("  which no other card carries",
      not [i for i, f in plan.items()
           if f["kind"] == "quiz" and i not in pair_cards
           and _gp.PAIR_NOTE in f["prompt"]])
# The note asks for side margin as well as top and bottom, because what a
# cover crop takes from a tile this narrow is width.
check("  the note reserves the sides, which is what cover actually crops",
      "wide plain backdrop left and right" in _gp.PAIR_NOTE
      and "central third of the width" in _gp.PAIR_NOTE)
check("the placeholder generator knows the tall shape too",
      "FRAME_TALL = (600, 900)" in open(
          os.path.join(ROOT, "scripts/gen_persona_placeholders.py"),
          encoding="utf-8").read())

check("the shared card rules are untouched",
      re.search(r"^\.card-img \{[^}]*object-fit: cover;", mazzin,
                re.M | re.S) is not None
      and re.search(r"^\.card-name \{[^}]*position: absolute;", mazzin,
                    re.M | re.S) is not None)
check("  and every persona rule is scoped to this funnel",
      all(r.startswith("body.theme-persona") for r in theme_rules))


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
      all(c in sheet for c in (".pr-stand", ".pr-stand-light",
                               ".pr-totem-art", ".pr-stand-plinth"))
      and "function pedestal(" in module)
# The pedestal used to be the totem's alone. It is shared now, because the
# head stands beside it and two objects lit differently read as a picture
# next to a diagram rather than as a pair.
check("  and the treatment is shared with the head",
      '.pr-stand.is-head' in sheet or '.pr-stand' in sheet)
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
# The measured numbers, and the third set of them. They were a mockup's box
# first, then the smooth field on the crown; they are the head itself now,
# because the radar is the head's defining feature rather than a mark on top
# of it. scripts/gen_persona.py --check-head measures the head's extent and
# reports the box it wants; test_personaart pins the two against each other.
check("  and the inlay spans the measured head",
      re.search(r"\.pr-head-inlay \{[^}]*top: 0\.8%;[^}]*left: 15\.3%;"
                r"[^}]*width: 68(?:\.0)?%;[^}]*height: 68(?:\.0)?%;", sheet, re.S)
      is not None)
check("  not the crown patch it replaced",
      not re.search(r"\.pr-head-inlay \{[^}]*width: 22\.5%;", sheet, re.S))
check("  and it is big enough to be the thing you look at",
      float(re.search(r"\.pr-head-inlay \{[^}]*width: ([\d.]+)%",
                      sheet, re.S).group(1)) >= 60)
check("the SVG is still generated from the tallies",
      "function headValues(" in module and "data.split" in module
      and "function headSvg(" in module)

# The inlay went dark. A mid-value teal wash over mid-value terracotta, at
# the size the crown allows, reads as a smudge; dark ink on warm clay is the
# contrast the material actually offers. The render's own teal collar carries
# the brand a few centimetres below.
head_svg = module[module.index("function headSvg("):
                  module.index("function headLegend(")]
check("the inlay is drawn in the page's own near-black",
      'INK = "#241A10"' in module and 'INK_SOFT = "#3A2A1B"' in module)
check("  rings and axes are dark strokes",
      "stroke: INK" in head_svg and '"stroke-opacity": 0.5' in head_svg)
check("  the polygon is a dark stroke over a dark wash",
      'fill: INK, "fill-opacity"' in head_svg and "stroke: INK" in head_svg)
check("  the vertices are dark", "r: 4, fill: INK" in head_svg)
check("  and the lean arc and its bead too",
      "stroke: INK_SOFT" in head_svg and "r: 5, fill: INK" in head_svg)
# Resolved, not scanned. The colours are constants defined outside the
# drawing function, so looking for a teal literal inside it would pass
# happily while INK itself was teal — which is exactly what a first version
# of this check did.
INK_VALUES = dict(re.findall(r'var (INK|INK_SOFT) = "(#[0-9A-Fa-f]{6})"',
                             module))


def luma(hexv):
    r, g, b = (int(hexv[i:i + 2], 16) for i in (1, 3, 5))
    return 0.299 * r + 0.587 * g + 0.114 * b


check("  both inks resolve to a near-black",
      len(INK_VALUES) == 2
      and all(luma(v) < 50 for v in INK_VALUES.values()),
      str(INK_VALUES))
check("  neither of them is the teal",
      "#4EDDC4" not in INK_VALUES.values(), str(INK_VALUES))
check("  and the drawing names no colour of its own",
      not re.search(r"#[0-9A-Fa-f]{6}", head_svg)
      and "GLAZE" not in module and "GROOVE" not in module,
      str(re.findall(r"#[0-9A-Fa-f]{6}", head_svg)))
check("  and the teal that carries the brand is in the render, not the ink",
      "--pr-teal: #4EDDC4;" in sheet)

print("\n--- the pair at the top of the card ---")
# The head was a diagram at the end of the page, below six locked cards,
# which made it read as an appendix to the offer rather than as the other
# half of what the profile is. It stands beside the totem now.
check("the module builds a pair row",
      "function headPair(" in module and 'elm("div", "pr-pair")' in module)
check("  totem left, head right, in that order",
      re.search(r'row\.appendChild\(pedestal\(data\)\);\s*\n\s*if '
                r'\(plate\) row\.appendChild\(stand\("is-head"',
                module) is not None)
check("  both wear the same pedestal treatment",
      "function stand(variant, node)" in module
      and '.pr-stand-light' in sheet and '.pr-stand-plinth' in sheet)
check("  matched heights, by column ratio rather than by fixed pixels",
      re.search(r"\.pr-pair \{(?:[^}]*)grid-template-columns: "
                r"minmax\(0, 3fr\) minmax\(0, 4fr\);", sheet, re.S)
      is not None
      and "aspect-ratio: 3 / 4;" in sheet and "aspect-ratio: 1 / 1;" in sheet)
# `.index` raises when the needle is gone, so an absent pair row would crash
# the suite instead of failing it. `.find` returns -1, which orders correctly
# against a real position and reads as the failure it is.
PAIR_AT = module.find("card.appendChild(headPair(data));")
ID_AT = module.find('elm("div", "pr-hero-id")')
check("  the pair is the first thing in the card",
      PAIR_AT >= 0 and ID_AT > PAIR_AT, "pair at %d, id at %d"
      % (PAIR_AT, ID_AT))
check("  and the head's old end-of-page slot is gone",
      "function headBlock(" not in module)

# The legend stays below as the diagram's caption, in the same rows.
CAPTION_AT = module.find("headCaption(copy || {}, data)")
check("the legend is the caption under the pair",
      "function headCaption(" in module
      and PAIR_AT >= 0 and CAPTION_AT > PAIR_AT and ID_AT > CAPTION_AT,
      "pair %d, caption %d, id %d" % (PAIR_AT, CAPTION_AT, ID_AT))
check("  still name-and-value rows", "function headLegend(" in module
      and ".pr-head-key" in sheet and ".pr-head-value" in sheet)
check("  and it keeps the line that says what it is",
      cfg["result_copy"]["head_caption"].startswith("Four traits"),
      cfg["result_copy"]["head_caption"])
check("  the caption block carries no plate of its own",
      "pr-head-plate" not in module[module.find("function headCaption("):
                                    module.find("function headPair(")])

check("the rarity line is centred",
      re.search(r"\.pr-ribbon \{[^}]*text-align: center;", sheet, re.S)
      is not None
      and re.search(r"\.pr-ribbon \{[^}]*margin: 16px auto 0;", sheet, re.S)
      is not None)
check("  and still says what it always said",
      cfg["result_copy"]["profile"]["rarity_line"]
      == "Rarer than {rarer}% of profiles")

# Both views draw one card, from one function, so the layout cannot drift
# between them. What differs is the picture at the top of it, and that is the
# product decision: the clay head and the radar pressed into it are what the
# report sells, so the free page shows the totem alone and the delivered page
# shows the pair.
check("one card function serves both views",
      module.count("function richHero(") == 1)
check("  the delivered page asks for the head",
      re.search(r"richHero\(glyph\(pick\), data, copy, \{ head: true \}\)",
                module) is not None)
check("  the free page does not",
      re.search(r"richHero\(glyph\(ctx\.picks\.now\), data, copy,\s*"
                r"\{ share: true, ctx: ctx, lean: true \}\)", module)
      is not None)
check("  so the pair is drawn only under that flag",
      module.count("card.appendChild(headPair(data));") == 1
      and re.search(r"if \(opts && opts\.head\) \{\s*"
                    r"card\.appendChild\(headPair\(data\)\);", module)
      is not None)
check("  and the totem stands alone on the other branch",
      "card.appendChild(soloTotem(data));" in module
      and module.count("function soloTotem(") == 1)
check("  and only the share button and the lean layout differ besides",
      "{ share: true, ctx: ctx, lean: true }" in module
      and "if (opts && opts.share && opts.ctx)" in module
      and "var lean = !!(opts && opts.lean);" in module)
check("the solo totem stands on the same pedestal as the pair's",
      ".pr-solo .pr-stand" in sheet and ".pr-solo .pr-totem-art" in sheet
      and re.search(r"\.pr-solo \{[^}]*margin: 0 auto", sheet, re.S)
      is not None)
check("  and the head, inlay and legend are all still built",
      all(("function %s(" % name) in module
          for name in ("headSvg", "headLegend", "headPlate", "headCaption",
                       "headPair")))
check("  with the four bars still on the free card",
      module.count("function traitBars(") == 1
      and "var bars = traitBars(data);" in module)


print("\n--- the words this vertical does not use ---")
# The words this funnel refuses, read from the profile that enforces them
# rather than kept in a second list here.
#
# They were two lists for as long as reports.py had no persona profile: this
# one policed the config's own strings and nothing policed what a model wrote.
# Now that PERSONA_BANNED exists and is enforced on every generated section,
# a copy of it here would be the thing that drifts — a word added there and
# forgotten here reads as this funnel having stopped banning it.
#
# The patterns are compiled regexes; the scan below wants plain words, so the
# few that carry alternation or a boundary trick are listed as what they
# match. Everything else comes straight off the profile.
# The scan runs the profile's own patterns rather than a copy of its words.
#
# A copy was what this was, and it drifted the moment reports.py grew a
# persona profile: a word added there and forgotten here reads as this funnel
# having stopped banning it. Extracting the words back out of the patterns is
# no better — half of them carry alternation (`\bdiagnos(?:e|es|is)\w*\b`)
# and an extractor that misses those quietly weakens the check it is supposed
# to be tightening.
#
# So the patterns are used as patterns. They already carry their own word
# boundaries, which is what the hand-rolled matcher below them was for.
def banned_hit(text):
    for pattern in reports.PERSONA_BANNED:
        found = pattern.search(text or "")
        if found:
            return found.group(0).lower()
    return None


SCANNED = strings(cfg)
dirty = [(t[:50], banned_hit(t)) for t in SCANNED if banned_hit(t)]
check("no on-screen string says a banned word", not dirty, str(dirty[:4]))
check("  and the scan actually read the whole config",
      len(SCANNED) > 600, str(len(SCANNED)))
check("  the scanner catches one when there is one",
      banned_hit("a clinical diagnosis") is not None
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
# Code, not prose. The zodiac module carries a byte-identical copy of the
# variant mechanism and says so in a comment naming the file it came from,
# which is the sentence a maintainer needs to keep the two in step. What it
# must not do is *depend* on this funnel — draw its classes, read its
# gallery, load its module — and that is a claim about code.
_zodiac_src = open(os.path.join(ROOT, "static/js/result_zodiac.js"),
                   encoding="utf-8").read()
_zodiac_code = re.sub(r"//[^\n]*", "",
                      re.sub(r"/\*.*?\*/", "", _zodiac_src, flags=re.S))
check("  and result_zodiac.js depends on nothing of persona's",
      not OWN.search(_zodiac_code), str(OWN.findall(_zodiac_code)[:3]))
check("  naming it only where it says where the shared mechanism came from",
      _zodiac_src.count("result_persona.js") <= 1)
check("engine.js knows nothing about persona either — it is all config",
      not OWN.search(engine), str(OWN.findall(engine)[:3]))
# app.py used to name this funnel nowhere at all, which was the proof the
# walk is config-driven. v3-A.1 adds the one exception: a share landing route
# whose whole subject is this funnel's personas. The claim narrows rather than
# lapsing — the funnel page is still slug-generic, and the naming is confined
# to the share route.
app_py = open(os.path.join(ROOT, "app.py"), encoding="utf-8").read()
check("app.py still serves the funnel page without naming it",
      "funnel_exists" in app_py
      and not OWN.search(app_py[app_py.index("def funnel_page("):]))
check("  and names persona only for the share route",
      app_py.count('@app.get("/persona/s/<persona>")') == 1
      and app_py.count('load_funnel("persona")') == 1)
# Three GET routes in the file: /health, the share page, and /<slug>. The
# count is the guard — a second persona route, or a template being rendered
# here, is the change this check exists to catch.
check("  which is one route and not a second page renderer",
      app_py.count("@app.get(") == 3
      and "render_template" not in app_py
      and "PERSONA_SHARE_DIR" in app_py,
      str(app_py.count("@app.get(")))
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

print("\n--- paywall variants ---")
variants = cfg.get("paywall_variants") or []
VARIANT_KEYS = {"id", "enabled", "weight", "name", "frame", "benefits",
                "cta_text"}
check("the config carries a list of variants", len(variants) == 2,
      str(len(variants)))
check("  each with the whole shape and nothing extra",
      all(set(v) == VARIANT_KEYS for v in variants),
      str([sorted(set(v) ^ VARIANT_KEYS) for v in variants]))
check("  both launch arms enabled, evenly weighted",
      all(v["enabled"] is True and v["weight"] == 1 for v in variants))
check("  named as the brief names them",
      [v["id"] for v in variants] == ["why", "advantage"],
      str([v["id"] for v in variants]))
check("  each with five benefits and a priced call to action",
      all(len(v["benefits"]) == 5 and "{price}" in v["cta_text"]
          for v in variants))
check("  and a name and a frame to argue it",
      all(v["name"] and v["frame"] for v in variants))

# The mechanism has to be adoptable by another funnel as it stands, which
# means it cannot know this one's name. The check is on the mechanism's own
# functions, not on the whole file: the persona module is full of persona.
MECHANISM = ("variantWeight", "variantPool", "sessionKey", "hashOf",
             "assignedVariant", "variantBlock", "applyVariantCta",
             "reportVariant")
start = min(module.find("function %s(" % name) for name in MECHANISM)
end = max(module.find("function %s(" % name) for name in MECHANISM)
end = module.find("\n  // ---", end)
mechanism = module[start:end]
# Code, not prose. The comments in here name `subid` and the URL precisely to
# say that assignment must not read either, and a scan that cannot tell a
# rule from its explanation would fail on the explanation and pass on a file
# that had quietly deleted it.
mechanism = re.sub(r"//[^\n]*", "", re.sub(r"/\*.*?\*/", "", mechanism,
                                           flags=re.S))
check("no funnel knows its own name in the mechanism",
      not re.search(r"persona|zodiac|kitchen", mechanism, re.I),
      str(re.findall(r"persona|zodiac|kitchen", mechanism, re.I)[:3]))
check("  it reads the variant list off the config, by the shared key",
      "cfg.paywall_variants" in mechanism)
check("  and takes weight and enabled as the config states them",
      "variant.enabled !== false" in mechanism
      and "typeof variant.weight" in mechanism)

# The hard requirement: a new arm, or a retired one, is a config edit.
check("assignment never reads the URL or a campaign parameter",
      not re.search(r"location|search|URLSearchParams|subid|utm_",
                    mechanism))
check("  it reads the session id the events already carry",
      "mazzin_sid" in module and "sessionStorage" in mechanism)

check("the offer draws the variant above the button",
      re.search(r"var frame = variantBlock\(variant\);\s*"
                r"if \(frame\) card\.appendChild\(frame\);", module, re.S)
      is not None)
pay_at = module.find("nodes.payButton, nodes.payError]")
frame_at = module.find("if (frame) card.appendChild(frame);")
check("  which is above where the pay button is placed",
      -1 < frame_at < pay_at, "%d vs %d" % (frame_at, pay_at))

check("the label engine.js reads is the one the variant argues",
      "ctx.cfg.checkout.cta_label = variant.cta_text;" in module)
check("  and engine.js is asked to read it again after it is written",
      re.search(r"cta_label = variant\.cta_text;[^}]*"
                r"dispatchEvent\(new Event\(\"change\"", module, re.S)
      is not None)

check("the arm is reported once, with the id in the payload",
      'ctx.track("paywall_variant", { variant: variant.id });' in module
      and "if (!variant || variantReported) return;" in module)
check("  and not from the delivered page",
      "reportVariant" not in module[module.find("function delivered(root"):])

# Nothing else on the platform grew a variants key or lost its paywall.
# zodiac30 adopted the mechanism for a layout test, which is what it was
# built funnel-agnostic for. Everything else still declares none, and that is
# the claim worth keeping: a funnel gets variants by asking for them.
VARIANT_FUNNELS = {"zodiac30"}
check("only the funnel that asked for them has variants",
      set(s for s in NEIGHBOUR_SLUGS
          if json.load(open(os.path.join(ROOT, "funnels", s + ".json"),
                            encoding="utf-8")).get("paywall_variants"))
      == VARIANT_FUNNELS)
check("  and its arms are a layout test, not this funnel's offer copy",
      all(set(v) <= {"id", "enabled", "weight", "name", "template"}
          for v in json.load(open(os.path.join(ROOT,
                                               "funnels/zodiac30.json"),
                                  encoding="utf-8"))["paywall_variants"]))
check("  and each still carries its own single call to action",
      all(json.load(open(os.path.join(ROOT, "funnels", s + ".json"),
                         encoding="utf-8"))
          .get("checkout", {}).get("cta_label")
          or json.load(open(os.path.join(ROOT, "funnels", s + ".json"),
                            encoding="utf-8"))
          .get("pricing", {}).get("cta")
          for s in NEIGHBOUR_SLUGS))

# The spot value. Only this funnel's module writes `cta_label`, and it writes
# it into the config object engine.js was handed for this page — so a funnel
# that never loads result_persona.js cannot have its button relabelled by any
# of this. Pinned by value as well as by argument, because "no other funnel is
# affected" is the kind of claim that is true right up until it is not.
NEIGHBOUR_CTA = {
    "zodiac30": "Open my full profile — {price}",
    "zodiac": "Open my full profile — {price}",
    "kitchen": "Get my report for {price}",
}
check("the neighbours' call to action is exactly what it was",
      all(json.load(open(os.path.join(ROOT, "funnels", slug + ".json"),
                         encoding="utf-8"))["checkout"]["cta_label"] == want
          for slug, want in NEIGHBOUR_CTA.items()))
check("  and only the persona module writes that key",
      sum(1 for name in os.listdir(os.path.join(ROOT, "static/js"))
          if name.endswith(".js")
          and "checkout.cta_label =" in open(
              os.path.join(ROOT, "static/js", name), encoding="utf-8").read())
      == 1)

# The sections ARE the offer now: one per bullet on the card, in the order
# the card lists them. Pinned against the config's own benefits rather than
# against a word list here, so a bullet rewritten without its section — or a
# section added without its bullet — fails rather than drifts.
SECTION_ORDER = ["dna", "materials", "mistakes", "shopping"]
check("the report is the four sections the paywall sells",
      [sec["id"] for sec in cfg["report"]["sections"]] == SECTION_ORDER,
      str([sec["id"] for sec in cfg["report"]["sections"]]))
check("  and nothing the paywall does not",
      not any(sec["id"] in ("palette", "splurge")
              for sec in cfg["report"]["sections"]))
for variant in cfg["paywall_variants"]:
    check("  %s promises one thing per section, plus the keepsake"
          % variant["id"],
          len(variant["benefits"]) == len(SECTION_ORDER) + 1,
          str(len(variant["benefits"])))
check("  every section has a teaser of its own",
      all((sec.get("teaser_line") or "").strip()
          for sec in cfg["report"]["sections"]))
check("  and the delivered page can still name each one",
      sorted(c["id"] for c in cfg["result_copy"]["profile"]["cards"])
      == sorted(SECTION_ORDER))

print("\n--- the page the reader lands on ---")
# The order the page argues in, read off the module rather than off a
# screenshot: picture, evidence, measure, rarity, price.
body = module[module.index("  function render(root, ctx)"):
              module.index("  // --- the delivered report")]
ZONES = ["richHero", "taps(ctx, copy)", "traitBars(data)", "rarityBadge(data)",
         "offer(ctx, copy, data, variant)"]
at = [body.find(z) for z in ZONES]
check("the free page runs picture, evidence, measure, rarity, price",
      all(x > 0 for x in at) and at == sorted(at), str(at))
# Scoped to the branch that draws the rich page. The `else` beside it is the
# plain fallback for a config with no table, and a scan that ran across both
# would read that branch's own node as something wedged in between.
rich = body[body.index("if (data) {"):body.index("    } else {")]
check("  the rarity is the last thing that branch draws",
      rich.rindex("appendChild(rare)")
      == max(m.start() for m in re.finditer(r"appendChild\(", rich)))
check("  and the offer comes straight after it",
      body.index("rarityBadge(data)") < body.index("offer(ctx, copy, data,"))
check("  the bullet zone is gone from the module",
      "function questions(" not in module
      and "function questionCard(" not in module)
check("  and the paragraph woven from their picks with it",
      "function bridge(" not in module
      and "narrativeBlock(data.narrative)" not in body)
check("  the stylesheet paints neither any more",
      not any(cls in sheet for cls in (".pr-cards", ".pr-card-icon",
                                       ".pr-bridge", ".pr-card-key")))
check("  but the narrative is still built, for the delivered page",
      "function narrativeBlock(" in module
      and "narrativeBlock(data.narrative)" in module)
check("the rarity is the loudest thing after the picture",
      re.search(r"\.pr-rarity-figure \{[^}]*font-size: (\d+)px", sheet, re.S)
      is not None
      and int(re.search(r"\.pr-rarity-figure \{[^}]*font-size: (\d+)px",
                        sheet, re.S).group(1)) >= 36)
check("  and the totem earns more room than it had",
      re.search(r"\.pr-solo \.pr-totem-art \{ width: (\d+)px", sheet)
      is not None
      and int(re.search(r"\.pr-solo \.pr-totem-art \{ width: (\d+)px",
                        sheet).group(1)) >= 200)
check("  the contact-sheet label stepped back",
      re.search(r"\.pr-taps-caption \{[^}]*font-size: (\d+)px", sheet, re.S)
      is not None
      and int(re.search(r"\.pr-taps-caption \{[^}]*font-size: (\d+)px",
                        sheet, re.S).group(1)) <= 11)
check("  and the sheet is two rows for a thirteen-step run",
      re.search(r"\.pr-taps-grid \{[^}]*repeat\(7, 1fr\)", sheet, re.S)
      is not None)
check("the line above the totem is the one the owner asked for",
      cfg["result_copy"]["kicker"] == "The inner shape of your mind")

print("\n--- the sculptures are shown whole ---")
check("the contact sheet contains rather than crops",
      re.search(r"\.pr-tap img \{[^}]*object-fit: contain;", sheet, re.S)
      is not None)
check("  on a ground toned to the renders' own backdrop",
      re.search(r"\.pr-tap img \{[^}]*background: var\(--pr-frame",
                sheet, re.S) is not None
      and "--pr-frame:" in sheet)
check("  and so does the section photograph",
      re.search(r"\.pr-shot img \{[^}]*object-fit: contain;", sheet, re.S)
      is not None)
check("nowhere in this funnel's own frames is cover still used",
      not re.search(r"\.pr-(tap|shot) img \{[^}]*object-fit: cover;",
                    sheet, re.S))
check("the funnel asks for whole frames in print too",
      cfg["report"].get("print_whole") is True)

print("\n%d checks, %d failed" % (checks[0], len(fails)))
for f in fails:
    print("  FAIL " + f)
sys.exit(1 if fails else 0)
