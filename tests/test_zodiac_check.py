#!/usr/bin/env python3
"""Integrity checks over funnels/zodiac.json and the gallery behind it.

The config-shape half of test_check.py, pointed at the zodiac funnel. Nothing
here touches kitchen: the two funnels share an engine and a server, not a
content contract, and a check that read both would fail for whichever one was
edited last.

No database, no network, no key. Everything is read off disk.
"""
import collections
import json
import os
import random
import re
import sys

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

sys.path.insert(0, REPO)
ROOT = REPO
GALLERY = os.path.join(ROOT, "static/galleries/zodiac")

fails = []
checks = [0]


def check(label, ok, detail=""):
    checks[0] += 1
    if not ok:
        fails.append("%s %s" % (label, detail))
    print("  %-58s %s%s" % (label, "ok" if ok else "FAIL",
                            ("  " + detail) if detail and not ok else ""))


cfg = json.load(open(os.path.join(ROOT, "funnels/zodiac.json")))
static_cfg = json.load(open(os.path.join(ROOT, "static/funnels/zodiac.json")))
steps = cfg["swipe"]["steps"]
by_step = {s["id"]: s for s in steps}
images = [i for s in steps for p in s["pairs"] for i in p["images"]]
by_id = {i["id"]: i for i in images}
GRID = {"grid4": 4, "grid6": 6}

# The service axis. These are the only tags allowed to stand alone, and they
# are the only ones no style scores against.
SEASONS = {"spring", "summer", "autumn", "winter"}
ELEMENTS = {"fire", "earth", "air", "water"}
ENERGY = {"sun", "moon"}
TONE = {"bold", "calm", "mystic"}
VOCAB = SEASONS | ELEMENTS | ENERGY | TONE

print("\n--- config shape ---")
check("static copy matches funnels/", cfg == static_cfg)
check("slug is zodiac", cfg["slug"] == "zodiac", cfg["slug"])
check("funnel_id is zodiac_v1", cfg["funnel_id"] == "zodiac_v1",
      cfg["funnel_id"])
check("locale is en", cfg["locale"] == "en", cfg["locale"])
check("pairs_count == number of steps",
      cfg["swipe"]["pairs_count"] == len(steps) == 13,
      "%s vs %s" % (cfg["swipe"]["pairs_count"], len(steps)))
check("analyzing copy names the 13 signals",
      "13 signals" in cfg["analyzing"]["messages"][0],
      cfg["analyzing"]["messages"][0])
check("checkout proof line names 13", "13" in cfg["checkout"]["proof_line"])
check("accent is a fragment of the subtext",
      cfg["swipe"]["subtext_accent"] in cfg["swipe"]["subtext"],
      "%r not in %r" % (cfg["swipe"]["subtext_accent"],
                        cfg["swipe"]["subtext"]))
check("subtext accent names the time",
      cfg["swipe"]["subtext_accent"] == "60 seconds",
      cfg["swipe"].get("subtext_accent"))
check("no stripe_mode — the default is what this funnel wants",
      "stripe_mode" not in cfg)

print("\n--- steps ---")
WANT = [
    ("hook", "pair", "Which sky calls to you?"),
    ("season", "grid4", "When do you celebrate your birthday?"),
    ("sign", "grid4", "Tap your zodiac sign:"),
    ("energy", "pair", "Choose your source of power"),
    ("landscape", "grid6", "Which world feels like home?"),
    ("palette", "grid6", "Which palette holds your energy?"),
    ("moment", "pair", "Your hour of power:"),
    ("symbol", "grid4", "Pick your talisman:"),
    ("moonphase", "grid4", "Which moon speaks to you?"),
    ("flow", "pair", "Your natural rhythm:"),
    ("drain", "grid4", "Which energy drains you most?"),
    ("sanctuary", "pair", "Where your soul recharges:"),
    ("essence", "grid4", "Your cosmic essence — final signal:"),
]
check("step ids and order", [s["id"] for s in steps] == [w[0] for w in WANT],
      str([s["id"] for s in steps]))
for step, (sid, fmt, question) in zip(steps, WANT):
    check("  %-10s is %-5s and asks its question" % (sid, fmt),
          step["id"] == sid and step["format"] == fmt
          and step["question"] == question,
          "%s / %s / %r" % (step["id"], step["format"], step["question"]))
check("only the drain step scores inverse",
      [s["id"] for s in steps if s.get("scoring") == "inverse"] == ["drain"],
      str([s["id"] for s in steps if s.get("scoring")]))
sign_images = [i for p in by_step["sign"]["pairs"] for i in p["images"]]
check("the sign step ids are sign_<name>",
      all(i["id"].startswith("sign_") for i in sign_images),
      str(sorted({i["id"] for i in sign_images})))
check("all twelve signs are reachable, plus the cusp",
      {i["id"] for i in sign_images} == {"sign_" + n for n in (
          "aries", "taurus", "gemini", "cancer", "leo", "virgo", "libra",
          "scorpio", "sagittarius", "capricorn", "aquarius", "pisces",
          "cusp")},
      str(sorted({i["id"] for i in sign_images})))
check("every variant covers three elements and the cusp",
      all({t for i in p["images"] for t in i["tags"]} & ELEMENTS
          == {i["tags"][0] for i in p["images"]} & ELEMENTS
          and len({i["tags"][0] for i in p["images"]} & ELEMENTS) == 3
          for p in by_step["sign"]["pairs"]),
      str([sorted({i["tags"][0] for i in p["images"]} & ELEMENTS)
           for p in by_step["sign"]["pairs"]]))
check("the four variants between them cover all four elements",
      {i["tags"][0] for i in sign_images} & ELEMENTS == ELEMENTS)
check("the cusp is the same card in every variant",
      len({json.dumps(i, sort_keys=True) for i in sign_images
           if i["id"] == "sign_cusp"}) == 1)
check("the cusp is labelled and tagged as one",
      all(i["label"] == "Born on a cusp" and i["tags"] == ["mystic", "moon"]
          for i in sign_images if i["id"] == "sign_cusp"))
check("the palette step is the moodboard step",
      cfg["report"]["visuals"]["moodboard_step"] == "palette")
check("every palette option carries a colour family",
      all(i.get("color_family") for i in
          by_step["palette"]["pairs"][0]["images"]))
check("colour families are unique",
      len({i["color_family"]
           for i in by_step["palette"]["pairs"][0]["images"]}) == 6)
check("no other step carries a colour family",
      not [i["id"] for s in steps if s["id"] != "palette"
           for p in s["pairs"] for i in p["images"] if "color_family" in i])

print("\n--- the adaptive axis engine.js actually knows ---")
# The engine holds the axis vocabulary, not the config: `AXES` there maps an
# axis name to the tags it is made of, and an axis it has never heard of
# resolves to no leader at all — which silently collapses every variant onto
# `default`. That is a wrong funnel rather than a broken one, and nothing
# else in this repo would catch it, so the whitelist is read out of engine.js
# rather than restated here.
engine = open(os.path.join(ROOT, "static/js/engine.js")).read()
known = set(re.findall(r"(\w+):\s*\w+_AXIS",
                       re.search(r"var AXES = \{([^}]*)\}",
                                 engine, re.S).group(1)))
check("engine.js declares its axes", bool(known), str(sorted(known)))
check("season is one of them", "season" in known, str(sorted(known)))
check("engine.js spells the season axis the way the season step tags do",
      set(re.search(r"var SEASON_AXIS = \[([^\]]*)\]", engine).group(1)
          .replace('"', "").replace(" ", "").split(",")) == SEASONS)
declared = [(s["id"], (s.get("adaptive") or {}).get("axis"))
            for s in steps if s.get("adaptive")]
check("the sign step is the only adaptive one, on season",
      declared == [("sign", "season")], str(declared))
check("no step adapts on an axis engine.js cannot resolve",
      all(axis in known for _, axis in declared), str(declared))

rule = by_step["sign"]["adaptive"]
pair_ids = {p["id"] for p in by_step["sign"]["pairs"]}
check("every variant resolves to a pair that exists",
      set(rule["variants"].values()) <= pair_ids,
      str(set(rule["variants"].values()) - pair_ids))
check("every pair of the step is reachable through some variant",
      pair_ids <= set(rule["variants"].values()),
      str(pair_ids - set(rule["variants"].values())))
# adaptivePairId falls back to variants.default when the axis has no leader,
# which on this funnel means somebody who somehow reached step 3 without
# answering step 2. Without the key the draw goes random.
check("there is a default", "default" in rule["variants"])
season_images = by_step["season"]["pairs"][0]["images"]
for key in rule["variants"]:
    if key == "default":
        continue
    carriers = [i["id"] for i in season_images if key in i["tags"]]
    check("  variant key %-7s is a tag exactly one season card carries" % key,
          len(carriers) == 1, str(carriers))
# Winter has no key of its own and rides `default`, which is the shape the
# engine wants — but it means a missing key looks like a working funnel. So
# resolve all four the way adaptivePairId does and require four distinct
# grids: a season quietly sharing another's signs is the exact failure this
# step was rebuilt to stop.
resolved = {}
for image in season_images:
    for tag in image["tags"]:
        resolved[tag] = (rule["variants"].get(tag)
                         or rule["variants"]["default"])
check("every season a card offers resolves to a grid",
      set(resolved) == SEASONS and all(resolved.values()), str(resolved))
check("and the four seasons resolve to four different grids",
      len(set(resolved.values())) == 4, str(resolved))
check("each grid holds the signs of its own season",
      resolved == {"spring": "p_spring", "summer": "p_summer",
                   "autumn": "p_autumn", "winter": "p_winter"}, str(resolved))

print("\n--- images, colours, tags ---")
HEX = set("0123456789ABCDEF")
for step in steps:
    for pair in step["pairs"]:
        want = GRID.get(step["format"], 2)
        check("step %-10s pair %-4s has %d images"
              % (step["id"], pair["id"], want), len(pair["images"]) == want,
              str(len(pair["images"])))
for img in images:
    name = img["img"].rsplit("/", 1)[-1]
    on_disk = os.path.exists(os.path.join(GALLERY, name))
    path_ok = img["img"] == "/static/galleries/zodiac/%s.webp" % img["id"]
    tags = img["tags"]
    # One tag is legal only on the season step, where the tag is the service
    # axis and carries no style weight. Everywhere else two or three.
    seasonal = set(tags) <= SEASONS
    tags_ok = (set(tags) <= VOCAB and len(set(tags)) == len(tags)
               and (len(tags) == 1 if seasonal else 2 <= len(tags) <= 3))
    colors_ok = (img.get("colors")
                 and all(c["hex"][0] == "#" and len(c["hex"]) == 7
                         and set(c["hex"][1:].upper()) <= HEX
                         and c.get("name") and c.get("element")
                         for c in img["colors"]))
    ok = on_disk and path_ok and img.get("label") and tags_ok and colors_ok
    if not ok:
        check("  image %s" % img["id"], False,
              "disk=%s path=%s tags=%s colors=%s"
              % (on_disk, path_ok, tags_ok, bool(colors_ok)))
check("every referenced frame is on disk and well formed",
      not [f for f in fails if f.startswith("  image")])
# One id is deliberately shared: the cusp card is the same picture, label and
# tags in all four seasonal grids, and every consumer of an image id either
# set-ifies it (tracking's funnel index, payments' known-id set), keys by
# step and pair rather than by image (pair_stats), or is indifferent to
# identical duplicates (reports' by-id map, the engine's imageById). Splitting
# it into four ids would buy nothing and put four identical frames on the CDN.
check("no pair shows the same image twice",
      all(len({i["id"] for i in p["images"]}) == len(p["images"])
          for s in steps for p in s["pairs"]))
where = collections.defaultdict(set)
for s in steps:
    for p in s["pairs"]:
        for i in p["images"]:
            where[i["id"]].add((s["id"], p["id"]))
repeated = {i: v for i, v in where.items() if len(v) > 1}
check("the only repeated id is the cusp", set(repeated) == {"sign_cusp"},
      str(sorted(repeated)))
check("and it is repeated only inside its own step",
      all(len({s for s, _ in v}) == 1 for v in repeated.values()))
check("every other image id is unique",
      len(by_id) == len(images) - (len(repeated.get("sign_cusp", ())) - 1),
      "%d ids, %d slots" % (len(by_id), len(images)))
check("the gallery has a frame for every image and an og card",
      set(os.listdir(GALLERY))
      == {i["id"] + ".webp" for i in images} | {"og.webp"},
      str(sorted(set(os.listdir(GALLERY))
                 ^ ({i["id"] + ".webp" for i in images} | {"og.webp"}))))
check("og_image points at that card",
      cfg["meta"]["og_image"] == "/static/galleries/zodiac/og.webp")
check("the season tags live only on the season step",
      {i["id"] for i in images if set(i["tags"]) & SEASONS}
      == {i["id"] for i in by_step["season"]["pairs"][0]["images"]})
check("the four seasons appear exactly once each",
      sorted(t for i in by_step["season"]["pairs"][0]["images"]
             for t in i["tags"]) == sorted(SEASONS))

print("\n--- interstitials ---")
anchors = [i["after_step"] for i in cfg["interstitials"]]
check("anchors are 4/7/10", anchors == [4, 7, 10], str(anchors))
names = [steps[a - 1]["id"] for a in anchors]
check("anchors land after energy/moment/flow",
      names == ["energy", "moment", "flow"], str(names))
check("last anchor leaves three steps", len(steps) - anchors[-1] == 3)
check("'Three more' copy matches",
      "Three more" in cfg["interstitials"][2]["sub"])
check("the last one is templated on progress",
      "{pct}" in cfg["interstitials"][2]["line"])
# `canFill` in engine.js suppresses an interstitial whose tokens it cannot
# resolve, and it resolves {leading_trait}/{opposite}/{leading_material} off
# the kitchen's tone and material axes. On this funnel's vocabulary they would
# never resolve, so a line using one would simply never be shown.
DEAD = re.compile(r"\{leading_trait\}|\{opposite\}|\{leading_material\}|\{n\}")
check("no interstitial leans on a token this vocabulary cannot fill",
      not [e for e in cfg["interstitials"]
           if DEAD.search((e.get("line") or "") + (e.get("sub") or ""))],
      str([e["kicker"] for e in cfg["interstitials"]
           if DEAD.search((e.get("line") or "") + (e.get("sub") or ""))]))
working = cfg.get("interstitial_working") or []
check("working copy is configured", len(working) >= 2, str(len(working)))
check("working copy is all strings",
      all(isinstance(w, str) and w for w in working))

print("\n--- styles ---")
WANT_STYLES = [
    ("radiant_fire", "Radiant Fire", ["fire", "sun", "bold"]),
    ("deep_water", "Deep Water", ["water", "moon", "mystic"]),
    ("grounded_earth", "Grounded Earth", ["earth", "calm", "moon"]),
    ("celestial_air", "Celestial Air", ["air", "sun", "bold"]),
]
check("four archetypes, named and tagged",
      [(s["id"], s["name"], s["tags"]) for s in cfg["styles"]] == WANT_STYLES,
      str([(s["id"], s["tags"]) for s in cfg["styles"]]))
vocab = {t for i in images for t in i["tags"]}
sections = [s for s in cfg["report"]["sections"]
            if s.get("enabled") is not False]
locked = [s["id"] for s in sections
          if (s.get("reveal") or {}).get("mode") != "visible"]
for style in cfg["styles"]:
    reveals = style["reveals"]
    palette = reveals.get("palette") or {}
    rgbs = palette.get("colors") or []
    ok_rgb = (len(rgbs) == 4
              and all(c.get("name") and isinstance(c.get("rgb"), list)
                      and len(c["rgb"]) == 3
                      and all(isinstance(v, int) and 0 <= v <= 255
                              for v in c["rgb"])
                      for c in rgbs))
    one = reveals.get("mistake_one") or {}
    check("style %-15s is complete" % style["id"],
          set(style["tags"]) <= vocab
          and style.get("blurb")
          # Four power colours, as rgb triples. A hex anywhere in here would
          # put a paint code in the free payload, which is the thing the
          # report is being paid for.
          and ok_rgb and palette.get("line")
          and len(palette.get("talismans") or []) == 3
          and palette.get("lucky_days")
          # One free strength, whole, and a setup/trigger for every section
          # that stays behind the paywall.
          and all(one.get(f) for f in ("title", "body", "fix"))
          and all((reveals.get(sec) or {}).get("setup")
                  and (reveals.get(sec) or {}).get("trigger")
                  for sec in locked),
          json.dumps(sorted(reveals))[:120])
    check("  %-15s hides its hex codes" % style["id"],
          not any("hex" in c for c in rgbs))
check("every style keeps its own name tag",
      all(any(t in s["id"] for t in s["tags"]) for s in cfg["styles"]))
check("style ids are unique", len({s["id"] for s in cfg["styles"]}) == 4)

print("\n--- report ---")
check("six sections", len(sections) == 6, str(len(sections)))
# The ids are kitchen's because both renderers dispatch on them —
# SECTION_BODY[sec.id] in engine.js, PDF_BODY[id] in reports.py — and an id
# neither table knows falls through to a bare paragraph. The titles are the
# product. Pinned as pairs so a rename on either side has to be deliberate.
SHAPE_OF = [
    ("palette", "Your Power Palette & Talismans"),
    ("mistakes", "5 Hidden Strengths & Blind Spots"),
    ("dna", "Your Cosmic Blueprint"),
    ("materials", "Love & Compatibility"),
    ("splurge", "Career & Money Path"),
    ("shopping", "Your 12-Month Energy Map"),
]
check("section ids and titles",
      [(s["id"], s["title"]) for s in sections] == SHAPE_OF,
      str([s["id"] for s in sections]))
# renderLockedReport draws the swatch grid for the first visible section that
# carries colours, and drops the free strength in directly behind it. A
# visible section without colours would be rendered blurred instead, and a
# visible section further down the list would put the free half of the report
# below the offer.
check("the palette section is the one given away",
      [s["id"] for s in sections
       if (s.get("reveal") or {}).get("mode") == "visible"] == ["palette"])
check("it is the opening section", sections[0]["id"] == "palette")
check("every section has two preview lines",
      all(len(s.get("preview") or []) == 2 for s in sections))
for key, rule in cfg["report"]["hook_slots"].items():
    check("hook slot %-10s names a real step" % key,
          rule["step"] in by_step and rule.get("fallback"),
          str(rule))
check("hook slots cover sign/palette/moonphase/symbol",
      sorted(cfg["report"]["hook_slots"]) == ["moonphase", "palette", "sign",
                                              "symbol"],
      str(sorted(cfg["report"]["hook_slots"])))
also_rows = cfg["report"]["also"]["rows"]
check("every also-row names a locked section or is a bonus row",
      all(r.get("section") in locked or r.get("title") for r in also_rows),
      str([r.get("section") for r in also_rows]))
check("the also-rows never collapse the hero section",
      cfg["checkout"]["manifest_hero"]
      not in [r.get("section") for r in also_rows])
visuals = cfg["report"]["visuals"]
check("visuals name real steps",
      visuals["moodboard_step"] in by_step
      and all(s in by_step for s in visuals["material_steps"]),
      str(visuals["material_steps"]))
check("every style has a visual default",
      sorted(visuals["defaults"]) == sorted(s["id"] for s in cfg["styles"]))
check("every visual default names a real image",
      all(d["moodboard"] in by_id and all(m in by_id for m in d["materials"])
          for d in visuals["defaults"].values()))
check("the free strength is numbered 1 of 5",
      "#1" in cfg["report"]["mistake_one"]["title"]
      and cfg["report"]["mistake_one"].get("locked_note"))

print("\n--- style elements ---")
block = cfg["style_elements"]
items = block["items"]
check("title and subline", bool(block["title"]) and bool(block["subline"]))
check("at least six elements to pick from", len(items) >= 6, str(len(items)))
check("every element points at a live quiz image",
      all(e["image"] in by_id for e in items),
      str([e["image"] for e in items if e["image"] not in by_id]))
check("element thumbs match their image path",
      all(e["img"] == by_id[e["image"]]["img"] for e in items))
check("element tags match their image tags",
      all(e["tags"] == by_id[e["image"]]["tags"] for e in items))
check("element ids unique", len({e["id"] for e in items}) == len(items))
check("element labels unique", len({e["label"] for e in items}) == len(items))
check("every element carries a one-line spec",
      all(e.get("spec") and "\n" not in e["spec"] and len(e["spec"]) < 60
          for e in items))
check("specs are unique", len({e["spec"] for e in items}) == len(items))

print("\n--- preview gallery ---")
gallery = cfg["preview_gallery"]
check("the gallery reuses quiz images",
      all(g["id"] in by_id for g in gallery),
      str([g["id"] for g in gallery if g["id"] not in by_id]))
check("with their own tags and paths",
      all(g["tags"] == by_id[g["id"]]["tags"]
          and g["img"] == by_id[g["id"]]["img"] for g in gallery))
check("it is the landscape, palette and essence sets",
      [g["id"] for g in gallery]
      == [i["id"] for sid in ("landscape", "palette", "essence")
          for i in by_step[sid]["pairs"][0]["images"]],
      str([g["id"] for g in gallery]))
# styleShots ranks the gallery by tag overlap and each locked block that gets
# drawn takes two frames off the top. previewStrip wraps rather than running
# dry, so a thin pool is a repeated thumbnail rather than an empty strip —
# but a style matching nothing at all would have no strip to draw and the
# withheld sections would be prose alone.
drawn = [s for s in locked
         if s not in [r.get("section") for r in also_rows]]
for style in cfg["styles"]:
    hits = [g for g in gallery if set(g["tags"]) & set(style["tags"])]
    check("  %-15s has %d frames for its %d locked blocks"
          % (style["id"], len(hits), len(drawn)),
          len(hits) >= 2 * len(drawn), str(len(hits)))

print("\n--- pricing and checkout ---")
check("price is 700 usd",
      cfg["pricing"]["amount_cents"] == 700
      and cfg["pricing"]["currency"] == "usd",
      str(cfg["pricing"]))
check("price is an integer number of cents",
      isinstance(cfg["pricing"]["amount_cents"], int))
check("cta names the profile",
      cfg["pricing"]["cta"] == "Unlock my full profile", cfg["pricing"]["cta"])
checkout = cfg["checkout"]
check("product name", checkout["product_name"] == "Your Cosmic Profile Report",
      checkout["product_name"])
check("single page", checkout["single_page"] is True)
check("proof line", checkout["proof_line"] == "Built from your 13 choices")
check("anchor names the session it undercuts",
      "$75" in checkout["anchor"] and "{price}" in checkout["anchor"],
      checkout["anchor"])
check("reframe",
      checkout["reframe"] == "Less than two coffees. Yours forever.")
check("manifest carries one row per section",
      len(checkout["manifest"]) == len(sections),
      str(len(checkout["manifest"])))
hero = checkout["manifest_hero"]
hits = [r for r in checkout["manifest"] if hero.lower() in r.lower()]
check("manifest hero matches exactly one row", len(hits) == 1, str(hits))
# The hero is a fragment of manifest copy rather than a section id — the
# engine uses it to bold one row — so it names the strengths in words while
# the section itself is `mistakes`.
strengths_id = [i for i, t in SHAPE_OF if "Strengths" in t][0]
check("the hero row names the strengths section",
      hero == "strengths" and hero.lower() in hits[0].lower()
      and strengths_id in locked, "%s / %s" % (hero, strengths_id))
check("trust lines are the ones kitchen ships",
      checkout["trust"] == ["Secure payment via Stripe", "Instant delivery",
                            "PDF copy to your email"], str(checkout["trust"]))
check("EU withdrawal text is the one kitchen ships",
      checkout["eu_withdrawal_text"]
      == "Instant delivery — I waive my 14-day withdrawal right.",
      checkout["eu_withdrawal_text"])
commerce = checkout["commerce"]
for key in ("anchor_head", "mid_line"):
    accent = commerce.get(key + "_accent")
    check("commerce %s accent is a fragment of its line" % key,
          accent and accent in commerce[key],
          "%r not in %r" % (accent, commerce.get(key)))
check("the sticky label is templated on the price",
      "{price}" in commerce["sticky_label"], commerce["sticky_label"])
teaser = cfg["result"]["mistakes_teaser"]
check("teaser counts from the free strength",
      "strength #1" in teaser and "other four" in teaser, teaser)
check("teaser is templated on a real hook slot",
      all(k in cfg["report"]["hook_slots"]
          for k in re.findall(r"\{(\w+)\}", teaser)), teaser)
check("value banner exists", bool(cfg["result"]["value_banner"]))

print("\n--- the words this vertical does not use ---")
BANNED = ["psychic", "prediction", "predictions", "fortune",
          "your future will"]
raw = open(os.path.join(ROOT, "funnels/zodiac.json"), encoding="utf-8").read()
low = raw.lower()
for word in BANNED:
    check("  never says %r" % word, word not in low,
          low[max(0, low.find(word) - 40):low.find(word) + 40])
print("\n--- placeholders ---")
# A token nothing answers is left on the page exactly as written — fillHook
# says so in as many words — so a brace in this config that no substitution
# knows about ships to the reader as a brace. The set: the hook slots, the
# style name, the price, the manifest count, and the progress percentage.
KNOWN = (set(cfg["report"]["hook_slots"])
         | {"style", "price", "n", "pct", "total"})


def tokens(node):
    if isinstance(node, str):
        return set(re.findall(r"\{(\w+)\}", node))
    if isinstance(node, dict):
        return set().union(set(), *(tokens(v) for v in node.values()))
    if isinstance(node, list):
        return set().union(set(), *(tokens(v) for v in node))
    return set()


used = tokens(cfg)
check("every placeholder in the copy is one something fills",
      used <= KNOWN, str(sorted(used - KNOWN)))
check("the hook slots are all actually used somewhere",
      set(cfg["report"]["hook_slots"]) <= used,
      str(sorted(set(cfg["report"]["hook_slots"]) - used)))

print("\n--- scoring ---")
# The axis vocabulary as engine.js holds it, so the walk below draws the
# adaptive step exactly as a phone would.
AXES = {name: [t.strip().strip('"') for t in body.split(",")]
        for name, body in re.findall(
            r"var (\w+)_AXIS = \[([^\]]*)\]", engine)}
AXES = {k.lower(): v for k, v in AXES.items()}
# computeWinner sums the run's tag scores over each style's tags, so a style
# whose own persona does not win it is a style nobody can ever be given.


def winner(scores):
    best, best_score = None, float("-inf")
    for style in cfg["styles"]:
        total = sum(scores.get(t, 0) for t in style["tags"])
        if total > best_score:
            best, best_score = style["id"], total
    return best


def _variant(step, scores):
    """The pair engine.js would draw, or None to leave it to the caller.

    adaptivePairId: the leading tag on the step's axis picks the variant,
    `default` covers the rest, and a rule naming a pair that is not there
    falls through to the random draw.
    """
    rule = step.get("adaptive")
    if not rule:
        return None
    leader, best = None, 0
    for tag in AXES.get(rule["axis"], ()):
        if scores.get(tag, 0) > best:
            best, leader = scores.get(tag, 0), tag
    wanted = (leader and rule["variants"].get(leader)) \
        or rule["variants"].get("default")
    return next((p for p in step["pairs"] if p["id"] == wanted), None)


def play(pick):
    """One run, as engine.js scores it: -0.5 a tag on the inverse step, 1 on
    every other, and the adaptive step drawn from what came before it."""
    scores = {}
    for step in steps:
        pair = _variant(step, scores)
        options = ([i for i in pair["images"]] if pair
                   else [i for p in step["pairs"] for i in p["images"]])
        weight = -0.5 if step.get("scoring") == "inverse" else 1
        for tag in pick(step, options)["tags"]:
            scores[tag] = scores.get(tag, 0) + weight
    return scores


for style in cfg["styles"]:
    want = set(style["tags"])
    element = (want & ELEMENTS).pop()

    def persona(step, options, want=want, element=element):
        # Element first, then the rest of the archetype's tags: somebody who
        # is air takes the air option when there is one, and falls back on
        # tone and energy when there is not. Ranking on the total alone would
        # have an air reader take a bold fire frame over a calm air one.
        def rank(item):
            return (element in item["tags"],
                    len(set(item["tags"]) & want))

        if step.get("scoring") == "inverse":
            # An inverse step asks what they would never have.
            return min(options, key=rank)
        return max(options, key=rank)

    got = winner(play(persona))
    check("a %-15s run is given %s" % (style["id"], style["name"]),
          got == style["id"], got)

check("the inverse step can push a total negative — the floor is -Infinity",
      any(s.get("scoring") == "inverse" for s in steps))

# The balance the tags were retuned for, held to a band rather than a point.
# A random walk is not a customer, but it is the one measure of this funnel
# that does not depend on guessing who its customers are, and a retag that
# quietly pushes an archetype out of reach shows up here and nowhere else —
# the persona checks above only ever play a style against itself.
#
# The band is wide on purpose: 15-35% leaves room to move copy and frames
# around without a failing suite, and still catches the 45/42/9/4 spread the
# funnel shipped with before the sign step was made adaptive.
FLOOR, CEILING = 15.0, 35.0
rng = random.Random(20260821)
seen = collections.Counter(
    winner(play(lambda s, o: rng.choice(o))) for _ in range(20000))
for style in cfg["styles"]:
    share = 100.0 * seen[style["id"]] / 20000
    check("  %-15s takes %4.1f%% of random walks (%.0f-%.0f)"
          % (style["id"], share, FLOOR, CEILING),
          FLOOR <= share <= CEILING)
check("the four shares account for every walk",
      sum(seen.values()) == 20000, str(sum(seen.values())))

print("\n--- server side ---")
import config  # noqa: E402
import database  # noqa: E402
import payments  # noqa: E402
import reports  # noqa: E402
import tracking  # noqa: E402

# Kitchen, for the checks that this funnel's arrival left it alone.
kitchen_cfg = json.load(open(os.path.join(ROOT, "funnels/kitchen.json")))
kitchen_choices = [s["pairs"][0]["images"][0]["id"]
                   for s in kitchen_cfg["swipe"]["steps"]]
MONTHS = ["January", "February", "March", "April", "May", "June", "July",
          "August", "September", "October", "November", "December"]

check("the slug is routable", config.funnel_exists("zodiac"))
check("load_funnel returns this config", config.load_funnel("zodiac") == cfg)


def _accepts(extra):
    try:
        tracking._clean_extra("zodiac", "swipe", extra)
        return True
    except ValueError:
        return False


choices = [s["pairs"][0]["images"][0]["id"] for s in steps]
check("checkout accepts a 13-long choice list",
      payments._clean_choices(cfg, choices) == choices)
check("checkout rejects a 14-long list",
      payments._clean_choices(cfg, choices + ["sy8a"]) is None)
check("tag scores validate against this vocabulary",
      payments._clean_tag_scores(cfg, {"fire": 6, "sun": 5, "bold": 4})
      == {"fire": 6, "sun": 5, "bold": 4})
for sid in ("hook", "season", "palette"):
    pair = by_step[sid]["pairs"][0]
    shown = [i["id"] for i in pair["images"]]
    got = tracking._clean_extra("zodiac", "swipe",
                                {"pair": "%s:%s" % (sid, pair["id"]),
                                 "shown": shown, "chosen": shown[0]})
    check("tracking accepts the %s step" % sid, got["chosen"] == shown[0],
          str(got))
# Every seasonal grid, by its own pair key. The cusp is in all four `shown`
# lists and tracking rejects a repeat inside one of them, so this is also
# where a shared id would show up if it were a problem.
for pair in by_step["sign"]["pairs"]:
    shown = [i["id"] for i in pair["images"]]
    got = tracking._clean_extra("zodiac", "swipe",
                                {"pair": "sign:" + pair["id"],
                                 "shown": shown, "chosen": "sign_cusp"})
    check("  tracking accepts sign:%-8s and the cusp in it" % pair["id"],
          got["chosen"] == "sign_cusp", str(got))
check("tracking still rejects a pair key the funnel has no variant for",
      not _accepts({"pair": "sign:p_autumn_2",
                    "shown": [i["id"] for i
                              in by_step["sign"]["pairs"][0]["images"]],
                    "chosen": "sign_cusp"}))
try:
    tracking._clean_extra("zodiac", "swipe",
                          {"pair": "hook:p1", "shown": ["hk1a", "zk1b"],
                           "chosen": "zk1b"})
    check("tracking rejects an image from another funnel", False)
except ValueError:
    check("tracking rejects an image from another funnel", True)
check("tracking allows step 13", tracking._clean_step(13) == 13)

print("\n--- the report is drawn by ids the renderers already know ---")
# The whole reason zodiac's sections are named after kitchen's: neither
# renderer sniffs the shape, both switch on the id, and an id they do not
# carry silently degrades a paid section to one paragraph of prose.
engine_body = set(re.findall(
    r"(\w+):\s*\w+Body", re.search(r"var SECTION_BODY = \{([^}]*)\}",
                                   engine, re.S).group(1)))
check("engine.js draws these six and no others",
      engine_body == {i for i, _ in SHAPE_OF}, str(sorted(engine_body)))
check("reports.py's PDF draws the same six",
      set(reports.PDF_BODY) == {i for i, _ in SHAPE_OF},
      str(sorted(reports.PDF_BODY)))
check("every zodiac section maps onto one of them",
      [i for i, _ in SHAPE_OF] == [s["id"] for s in sections])
check("and no two sections claim the same shape",
      len({i for i, _ in SHAPE_OF}) == len(SHAPE_OF))
check("every section has a validator, a spec and a stub",
      all(i in reports.VALIDATORS and i in reports.ZODIAC_SPEC
          and i in reports.ZODIAC_STUBS for i, _ in SHAPE_OF))
check("every stub survives the validator that will police the real thing",
      all(reports.VALIDATORS[i](reports._fill(reports.ZODIAC_STUBS[i],
                                              "Deep Water")) is not None
          for i, _ in SHAPE_OF),
      str([i for i, _ in SHAPE_OF
           if reports.VALIDATORS[i](
               reports._fill(reports.ZODIAC_STUBS[i], "Deep Water")) is None]))

print("\n--- what is cached, and what is written per purchase ---")
CACHED_TRIO = ("palette", "mistakes", "splurge")
PERSONAL_TRIO = ("dna", "materials", "shopping")
check("zodiac caches exactly the archetype trio",
      reports.cached_sections("zodiac") == CACHED_TRIO,
      str(reports.cached_sections("zodiac")))
check("and personalises exactly the sign-driven trio",
      reports.personal_sections("zodiac") == PERSONAL_TRIO,
      str(reports.personal_sections("zodiac")))
check("the two together are every section, once",
      sorted(CACHED_TRIO + PERSONAL_TRIO) == sorted(i for i, _ in SHAPE_OF))
# The split is the COGS decision: 4 cached calls a style against 3 fresh calls
# a purchase. Kitchen's split is the other overlap and must not have moved.
check("kitchen still caches shopping/dna/splurge",
      reports.cached_sections("kitchen") == ("shopping", "dna", "splurge"),
      str(reports.cached_sections("kitchen")))
check("kitchen still personalises palette/materials/mistakes",
      reports.personal_sections("kitchen")
      == ("palette", "materials", "mistakes"),
      str(reports.personal_sections("kitchen")))
check("a funnel nobody registered is kitchen",
      reports.cached_sections("kitchen-visualizer") == reports.CACHED
      and reports.cached_sections("") == reports.CACHED)
check("the warmer asks the funnel rather than the module",
      "reports.cached_sections(" in open(
          os.path.join(ROOT, "scripts/warm_cache.py")).read())

print("\n--- the words this vertical may not say, enforced twice ---")
# Once in the prompt, which is an instruction, and once on the way back,
# which is not. The second is the one that holds when a model ignores the
# first, and it is a Terms line rather than a matter of house style.
BAN_SAMPLES = [
    "your future will be brighter", "a psychic reading", "this prediction",
    "we predict a strong month", "your fortune changes", "a horoscope for you",
    "you are destined to lead", "a diagnosis of burnout",
    "the symptoms of overwork", "invest in property this spring",
    "financial advice for the year", "clairvoyant insight",
]
for phrase in BAN_SAMPLES:
    check("  refuses %-34s" % ('"%s"' % phrase),
          reports._banned_hit(phrase, reports.ZODIAC_BANNED) is not None)
KEEP = ["unpredictable weather", "a fortunate turn",
        "the treatment of a theme", "you are predisposed to act",
        "returns to the same question"]
for phrase in KEEP:
    check("  allows  %-34s" % ('"%s"' % phrase),
          reports._banned_hit(phrase, reports.ZODIAC_BANNED) is None)
check("the check reaches into nested section data",
      reports._banned_hit(
          {"items": [{"body": "ok"}, {"body": "our prediction"}]},
          reports.ZODIAC_BANNED) == "prediction")
check("kitchen's list is empty, so kitchen validates as it always did",
      reports._profile("kitchen")["banned"] == ()
      and reports._banned_hit("your future will", ()) is None)

templates = {"SPEC[%s]" % k: v for k, v in reports.ZODIAC_SPEC.items()}
templates.update({"STUB[%s]" % k: json.dumps(reports._fill(v, "Deep Water"))
                  for k, v in reports.ZODIAC_STUBS.items()})
dirty = {k: reports._banned_hit(v, reports.ZODIAC_BANNED)
         for k, v in templates.items()}
dirty = {k: v for k, v in dirty.items() if v}
check("no zodiac prompt template or stub says one itself", not dirty,
      str(dirty))
# The system prompt is the exception and has to be: it names them to ban them.
check("the system prompt does name them, in order to forbid them",
      reports._banned_hit(reports.ZODIAC_SYSTEM, reports.ZODIAC_BANNED)
      is not None)
for word in ("psychic", "prediction", "fortune", "your future will"):
    check("  system prompt forbids %-16s" % word,
          word in reports.ZODIAC_SYSTEM.lower())

print("\n--- the reader's own sign, out of the run ---")
run = {}
for step in steps:
    run[step["id"]] = step["pairs"][0]["images"][0]["id"]


def walk_with(season_id, sign_id):
    """A full 13-choice run that tapped one season and one sign."""
    out = []
    for step in steps:
        if step["id"] == "season":
            out.append(season_id)
        elif step["id"] == "sign":
            out.append(sign_id)
        else:
            out.append(run[step["id"]])
    return out


season_of = {}
for image in by_step["season"]["pairs"][0]["images"]:
    season_of[image["tags"][0]] = image["id"]
variant_of = by_step["sign"]["adaptive"]["variants"]
seen_signs = set()
for pair in by_step["sign"]["pairs"]:
    season = [t for t, v in variant_of.items() if v == pair["id"]]
    season = season[0] if season and season[0] != "default" else "winter"
    for image in pair["images"]:
        if image["id"] == "sign_cusp":
            continue
        seen_signs.add(image["id"])
        got = reports._sign(cfg, walk_with(season_of[season], image["id"]))
        check("  %-18s reads back as %-12s"
              % (image["id"], got and got.get("label")),
              got is not None and got["cusp"] is False
              and got["label"] == image["label"]
              and got["season"] == season,
              str(got))
check("all twelve signs resolve", len(seen_signs) == 12, str(len(seen_signs)))

for season, season_image in sorted(season_of.items()):
    got = reports._sign(cfg, walk_with(season_image, "sign_cusp"))
    block = reports._sign_block(cfg, walk_with(season_image, "sign_cusp"))
    grid = [i["label"] for i in
            by_step["sign"]["pairs"][
                [p["id"] for p in by_step["sign"]["pairs"]].index(
                    variant_of.get(season) or variant_of["default"])]["images"]
            if i["id"] != "sign_cusp"]
    check("  cusp in %-7s blends the season, names no single sign" % season,
          got["cusp"] is True and got["label"] is None
          and got["season"] == season and got["neighbours"] == grid
          and "born on a cusp" in block
          and "Never assert that they are any one" in block,
          str(got))
check("the thirteenth id is the cusp and it is the only one",
      len(seen_signs) + 1 == 13 and "sign_cusp" not in seen_signs)
check("a run with no sign step answered reads back as no sign",
      reports._sign(cfg, [run[s["id"]] for s in steps
                          if s["id"] != "sign"]) is None)

print("\n--- every per-purchase section is written from real taps ---")
leo = walk_with(season_of["summer"], "sign_leo")
style = cfg["styles"][0]
for section_id in PERSONAL_TRIO:
    prompt = reports._section_prompt(style, "Radiant Fire", {"fire": 8},
                                     section_id, cfg, leo, "zodiac")
    check("  %-10s names the sign and demands a tap by name" % section_id,
          "Leo" in prompt and "REQUIRED" in prompt
          and "the moon they chose" in prompt
          and reports.ZODIAC_SPEC[section_id] in prompt,
          section_id)
    check("  %-10s is not handed kitchen's voice or shapes" % section_id,
          "kitchen" not in prompt.lower()
          and reports.SPEC[section_id] not in prompt)
cusp_prompt = reports._section_prompt(
    style, "Radiant Fire", {"fire": 8}, "dna", cfg,
    walk_with(season_of["summer"], "sign_cusp"), "zodiac")
check("a cusp run never has a single sign put in its prompt",
      "born on a cusp" in cusp_prompt
      and not re.search(r"this reader's sign is", cusp_prompt), "")
cached_prompt = reports._cached_prompt(style, "Radiant Fire", CACHED_TRIO,
                                       "zodiac")
check("the cached prompt is style-only and names no tap",
      "Nothing here is specific to one person." in cached_prompt
      and "the moon they chose" not in cached_prompt)
check("and it still reproduces the free strength as item 1",
      style["reveals"]["mistake_one"]["title"] in cached_prompt)
check("kitchen's prompts are untouched by any of this",
      reports.SPEC["palette"] in reports._section_prompt(
          kitchen_cfg["styles"][0], "Modern Rustic", {"warm": 4}, "palette",
          kitchen_cfg, kitchen_choices))

print("\n--- print copies for the PDF ---")
vis = cfg["report"]["visuals"]
need = set()
for defaults in vis["defaults"].values():
    need.update([defaults["moodboard"]] + defaults["materials"])
for step_id in [vis["moodboard_step"]] + list(vis["material_steps"]):
    need.update(i["id"] for p in by_step[step_id]["pairs"]
                for i in p["images"])
missing = [i for i in sorted(need)
           if not os.path.isfile(os.path.join(ROOT, "static/img/print",
                                              i + ".jpg"))]
check("every image the zodiac report can draw has a print copy",
      not missing, str(missing))


def print_size(image_id):
    return os.path.getsize(
        os.path.join(ROOT, "static/img/print", image_id + ".jpg"))


heavy = [(i, print_size(i) // 1024) for i in sorted(need)
         if print_size(i) > 60 * 1024]
check("  and none is heavy enough to bloat a mailbox", not heavy, str(heavy))
check("  the PDF points at them rather than the gallery originals",
      reports._print_src("pl6a", {"img": "/static/galleries/zodiac/pl6a.webp"})
      == "img/print/pl6a.jpg")

print("\n--- a purchase, end to end, with nothing real behind it ---")
# No database, no key, no model: `_api` off is the documented stub path, and
# what it produces has to be a publishable report rather than six blank
# sections — which is exactly what /zodiac delivered before this.
_saved = (database.execute, database.query_all, reports._api)
database.execute = lambda *a, **k: None
database.query_all = lambda *a, **k: []
reports._api = lambda: None
try:
    content = reports.start_report(1, "zodiac", "deep_water",
                                   {"water": 8, "moon": 6, "mystic": 5},
                                   choices=leo)
finally:
    database.execute, database.query_all, reports._api = _saved

check("the report is stored complete rather than partial",
      content["version"] == "stub-2", content["version"])
check("it carries all six sections, in the config's order",
      [s["id"] for s in content["sections"]] == [i for i, _ in SHAPE_OF],
      str([s["id"] for s in content["sections"]]))
check("with the zodiac titles rather than kitchen's",
      [s["title"] for s in content["sections"]] == [t for _, t in SHAPE_OF])
check("every section arrives with data the renderer can draw",
      all(isinstance(s["data"], dict) and s["data"]
          for s in content["sections"]),
      str([s["id"] for s in content["sections"]
           if not isinstance(s["data"], dict)]))
check("the style name is the archetype", content["style_name"] == "Deep Water")
check("the free result's elements are carried into the paid view",
      len(content.get("elements") or []) == 6, str(content.get("elements")))
check("and the photographs it is illustrated with",
      set(content.get("visuals") or {}) == {"moodboard", "materials"},
      str(content.get("visuals")))

by_section = {s["id"]: s["data"] for s in content["sections"]}
check("the year map is twelve months, in calendar order",
      [i["name"] for i in by_section["shopping"]["items"]] == MONTHS,
      str([i["name"] for i in by_section["shopping"]["items"]]))
check("  nothing is struck out under a Skip heading",
      by_section["shopping"]["skip"] == [],
      str(by_section["shopping"]["skip"]))
notes = [i["priority_note"] for i in by_section["shopping"]["items"]]
check("  two months are marked strongest",
      sum(n.startswith("Strongest month:") for n in notes) == 2)
check("  one is marked quiet",
      sum(n.startswith("Quiet month:") for n in notes) == 1)
check("the strengths section is five of them",
      len(by_section["mistakes"]["items"]) == 5,
      str(len(by_section["mistakes"]["items"])))
check("the palette is four colours with real hex values",
      len(by_section["palette"]["colors"]) == 4
      and all(reports.HEX_RE.match(c["hex"])
              for c in by_section["palette"]["colors"]))
check("compatibility runs two that work and two that cost",
      sorted(p["verdict"] for p in by_section["materials"]["pairs"])
      == ["avoid", "avoid", "works", "works"])
check("nothing delivered says a banned word",
      reports._banned_hit(content["sections"], reports.ZODIAC_BANNED) is None,
      str(reports._banned_hit(content["sections"], reports.ZODIAC_BANNED)))

print("\n--- and the PDF a buyer is emailed ---")
html_out = reports._pdf_html(content)
check("the cover names this product",
      "Your cosmic profile report" in html_out
      and "Your kitchen style report" not in html_out)
for _, title in SHAPE_OF:
    check("  carries %-34s" % title,
          title.replace("&", "&amp;") in html_out)
check("it draws the print copies of this run's own images",
      'src="img/print/' in html_out
      and "galleries/zodiac" not in html_out,
      str(re.findall(r'<img src="([^"]+)"', html_out)))
check("the year map has no empty Skip block in print",
      "<b>Skip</b>" not in reports._pdf_section_body(
          {"id": "shopping", "data": by_section["shopping"]}, True))
pdf = reports.build_pdf(content)
check("weasyprint renders it", pdf is not None and pdf[:4] == b"%PDF")
check("  and it is small enough to email",
      pdf is not None and len(pdf) < 3 * 1024 * 1024,
      "%d KB" % (len(pdf) // 1024) if pdf else "none")
check("the mail is the zodiac mail, not the kitchen one",
      reports._email_copy(content) is reports.COPY_ZODIAC
      and "kitchen" not in reports.COPY_ZODIAC["subject"].lower())
check("  and its opening line does not promise a renovation saving",
      "$4,000" not in reports._email_opening(content),
      reports._email_opening(content))

print("\n%d checks, %d failed" % (checks[0], len(fails)))
for f in fails:
    print("  FAIL " + f)
sys.exit(1 if fails else 0)
