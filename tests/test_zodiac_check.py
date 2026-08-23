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
      cfg["swipe"]["pairs_count"] == len(steps) == 12,
      "%s vs %s" % (cfg["swipe"]["pairs_count"], len(steps)))
check("analyzing copy names the 12 signals",
      "12 signals" in cfg["analyzing"]["messages"][0],
      cfg["analyzing"]["messages"][0])
check("checkout proof line names 12", "12" in cfg["checkout"]["proof_line"])
# The count is claimed in five places and the season step took one tap out of
# all of them. A stale thirteen is the kind of line nobody notices is wrong
# until a reader counts.
check("nothing anywhere still claims thirteen",
      not re.search(r"\b13\b", json.dumps(cfg, ensure_ascii=False)),
      str(re.findall(r'"[^"]*\b13\b[^"]*"',
                     json.dumps(cfg, ensure_ascii=False))[:3]))
check("every claim of twelve agrees with the step count",
      all(str(len(steps)) in text for text in
          (cfg["analyzing"]["messages"][0], cfg["checkout"]["proof_line"],
           cfg["result"]["value_banner"])))
# Cards name themselves on this funnel, permanently, rather than only in the
# chip after a tap.
check("label_mode is badge", cfg["swipe"].get("label_mode") == "badge",
      cfg["swipe"].get("label_mode"))
check("accent is a fragment of the subtext",
      cfg["swipe"]["subtext_accent"] in cfg["swipe"]["subtext"],
      "%r not in %r" % (cfg["swipe"]["subtext_accent"],
                        cfg["swipe"]["subtext"]))
check("subtext accent names the time",
      cfg["swipe"]["subtext_accent"] == "60 seconds",
      cfg["swipe"].get("subtext_accent"))
# Live, as of go-live. It was on the sandbox key set while the funnel was
# being walked end to end with a 4242 card; it now takes money on the same
# account kitchen-visualizer does. The value is pinned rather than merely
# checked for presence because payments._stripe_mode reads exactly "test" and
# calls everything else live — so a typo in the other direction is a funnel
# that silently stops charging anybody.
check("stripe_mode is the literal live", cfg.get("stripe_mode") == "live",
      repr(cfg.get("stripe_mode")))
check("  the same value kitchen-visualizer carries",
      cfg.get("stripe_mode") == json.load(
          open(os.path.join(ROOT, "funnels/kitchen-visualizer.json")))
      .get("stripe_mode"))

print("\n--- steps ---")
WANT = [
    ("hook", "pair", "Which sky calls to you?"),
    ("sign", "grid12", "Tap your zodiac sign:"),
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
    check("  %-10s is %-6s and asks its question" % (sid, fmt),
          step["id"] == sid and step["format"] == fmt
          and step["question"] == question,
          "%s / %s / %r" % (step["id"], step["format"], step["question"]))
check("only the drain step scores inverse",
      [s["id"] for s in steps if s.get("scoring") == "inverse"] == ["drain"],
      str([s["id"] for s in steps if s.get("scoring")]))
# The season step existed only to steer the adaptive draw. With twelve signs
# on one screen it asked for a birthday to save nobody anything.
check("there is no season step", "season" not in by_step, sorted(by_step))
check("and no season tag survives on any image",
      not [i["id"] for i in images if set(i["tags"]) & SEASONS],
      str([i["id"] for i in images if set(i["tags"]) & SEASONS]))
check("the sign step is second, right after the hook",
      [s["id"] for s in steps][:2] == ["hook", "sign"])

print("\n--- the twelve signs, on one screen ---")
ZODIAC = ["Aries", "Taurus", "Gemini", "Cancer", "Leo", "Virgo",
          "Libra", "Scorpio", "Sagittarius", "Capricorn", "Aquarius",
          "Pisces"]
sign = by_step["sign"]
check("one pair, not four seasonal ones", len(sign["pairs"]) == 1,
      str([p["id"] for p in sign["pairs"]]))
sign_images = sign["pairs"][0]["images"]
check("twelve cards on it", len(sign_images) == 12, str(len(sign_images)))
check("all twelve signs, in classical order",
      [i["label"] for i in sign_images] == ZODIAC,
      str([i["label"] for i in sign_images]))
check("ids are sign_<name>, lowercased",
      [i["id"] for i in sign_images]
      == ["sign_" + n.lower() for n in ZODIAC],
      str([i["id"] for i in sign_images]))
check("each sign carries exactly one element",
      all(len(set(i["tags"]) & ELEMENTS) == 1 for i in sign_images),
      str([i["id"] for i in sign_images
           if len(set(i["tags"]) & ELEMENTS) != 1]))
check("three of each element across the twelve",
      sorted(collections.Counter(
          (set(i["tags"]) & ELEMENTS).pop() for i in sign_images).values())
      == [3, 3, 3, 3])
# engine.js shuffles a pair so a habitual left-tapper cannot score the same
# way twice. That assumes the cards are alternatives being weighed; a reader
# hunting for their own sign wants the order they already know.
check("the step opts out of the shuffle", sign.get("shuffle") is False,
      str(sign.get("shuffle")))
check("nothing else opts out",
      [s["id"] for s in steps if s.get("shuffle") is False] == ["sign"],
      str([s["id"] for s in steps if "shuffle" in s]))
check("the cusp card is gone from the quiz",
      "sign_cusp" not in {i["id"] for i in images})
# Kept deliberately: the branch costs nothing and a funnel that cannot show
# twelve at once would want it back.
check("  but its art is still on disk",
      os.path.isfile(os.path.join(GALLERY, "sign_cusp.webp")))

print("\n--- the formats engine.js can actually draw ---")
# The config names a format; engine.js decides what a format is. A step
# asking for one that is not in GRID_SIZE falls back to a two-up pair, which
# is a wrong funnel rather than a broken one — twelve signs would arrive as
# two — so the table is read out of the engine rather than restated here.
engine = open(os.path.join(ROOT, "static/js/engine.js")).read()
sizes = dict((name, int(size)) for name, size in re.findall(
    r"(grid\d+):\s*(\d+)",
    re.search(r"var GRID_SIZE = \{([^}]*)\}", engine).group(1)))
check("engine.js declares its grids", bool(sizes), str(sizes))
check("grid12 is one of them and means twelve", sizes.get("grid12") == 12,
      str(sizes))
check("every format this funnel asks for is one the engine has",
      all(s["format"] == "pair" or s["format"] in sizes for s in steps),
      str(sorted({s["format"] for s in steps})))
for step in steps:
    want = sizes.get(step["format"], 2)
    for pair in step["pairs"]:
        check("  %-10s %-4s holds the %d its format draws"
              % (step["id"], pair["id"], want),
              len(pair["images"]) == want, str(len(pair["images"])))
# The class is what the stylesheet lays out on, and renderStep now derives it
# from the same table rather than naming formats one at a time.
check("engine.js derives the grid class from that table",
      'classList.toggle("is-" + name' in engine)
css = open(os.path.join(ROOT, "static/css/mazzin.css")).read()
for name in sorted(sizes):
    check("  mazzin.css lays out .cards.is-%s" % name,
          ".cards.is-%s {" % name in css)

print("\n--- the season axis outlives the step that used it ---")
# Nothing adapts any more. The axis stays declared because removing it would
# be a change to shared code for no gain, and a funnel that wants seasonal
# variants back should find it there.
check("no step adapts on anything",
      not [s["id"] for s in steps if s.get("adaptive")],
      str([s["id"] for s in steps if s.get("adaptive")]))
known = set(re.findall(r"(\w+):\s*\w+_AXIS",
                       re.search(r"var AXES = \{([^}]*)\}",
                                 engine, re.S).group(1)))
check("engine.js still carries the season axis", "season" in known,
      str(sorted(known)))
check("  spelled the way the season tags were",
      set(re.search(r"var SEASON_AXIS = \[([^\]]*)\]", engine).group(1)
          .replace('"', "").replace(" ", "").split(",")) == SEASONS)

print("\n--- images, colours, tags ---")
HEX = set("0123456789ABCDEF")
for img in images:
    name = img["img"].rsplit("/", 1)[-1]
    on_disk = os.path.exists(os.path.join(GALLERY, name))
    path_ok = img["img"] == "/static/galleries/zodiac/%s.webp" % img["id"]
    tags = img["tags"]
    # Two or three, everywhere. The one-tag exception belonged to the season
    # step, which was the only place a tag no style scores against was
    # allowed, and that step is gone.
    tags_ok = (set(tags) <= VOCAB and len(set(tags)) == len(tags)
               and 2 <= len(tags) <= 3)
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
# The cusp was the one id that appeared in more than one pair, because the
# same card sat in all four seasonal grids. With one grid there is nothing
# left to share and every id is its own card again.
check("no id appears in more than one pair", not repeated,
      str(sorted(repeated)))
check("every image id is unique", len(by_id) == len(images),
      "%d ids, %d slots" % (len(by_id), len(images)))
# Every image the quiz can draw has a frame. The reverse no longer holds:
# the four season frames and the cusp outlived the step and the card that
# used them, and deleting art is not something a config change should do.
RETIRED = {"se2a.webp", "se2b.webp", "se2c.webp", "se2d.webp",
           "sign_cusp.webp"}
on_disk = set(os.listdir(GALLERY))
wanted = {i["id"] + ".webp" for i in images} | {"og.webp"}
check("the gallery has a frame for every image the quiz draws",
      wanted <= on_disk, str(sorted(wanted - on_disk)))
check("  and carries nothing beyond those but the retired frames",
      on_disk - wanted == RETIRED, str(sorted((on_disk - wanted) ^ RETIRED)))
check("og_image points at that card",
      cfg["meta"]["og_image"] == "/static/galleries/zodiac/og.webp")
check("no season tag survives anywhere in the quiz",
      not {t for i in images for t in i["tags"]} & SEASONS)

print("\n--- interstitials ---")
anchors = [i["after_step"] for i in cfg["interstitials"]]
check("anchors are 4/7/10", anchors == [4, 7, 10], str(anchors))
names = [steps[a - 1]["id"] for a in anchors]
check("anchors land after landscape/symbol/drain",
      names == ["landscape", "symbol", "drain"], str(names))
# One step fewer, so the last anchor now has two behind it rather than
# three — and the line that counts them had to move with it.
check("last anchor leaves two steps", len(steps) - anchors[-1] == 2)
check("'Two more' copy matches",
      "Two more" in cfg["interstitials"][2]["sub"],
      cfg["interstitials"][2]["sub"])
# Written out, because that is how the line reads it.
COUNTED = {1: "One more", 2: "Two more", 3: "Three more"}
check("  and it counts the steps that are actually left",
      COUNTED[len(steps) - anchors[-1]] in cfg["interstitials"][2]["sub"],
      cfg["interstitials"][2]["sub"])
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
# One photograph per report section and two for the header, each named as the
# step it is read off. A step that does not exist is a section that silently
# never gets a picture, which looks like a styling bug and is a typo.
section_steps = visuals["section_steps"]
check("every illustrated section names a real step",
      all(s in by_step for s in section_steps.values()),
      str([s for s in section_steps.values() if s not in by_step]))
check("  and a real section of this report",
      all(sid in {s["id"] for s in sections} for sid in section_steps),
      str([sid for sid in section_steps
           if sid not in {s["id"] for s in sections}]))
check("  no two sections share a photograph",
      len(set(section_steps.values())) == len(section_steps),
      str(sorted(section_steps.values())))
check("the header names two steps of its own",
      all(step in by_step for step in visuals["hero"].values()),
      str(visuals["hero"]))
check("  the sign's own frame among them",
      visuals["hero"]["glyph_step"] == "sign")
# The whole point of the set: every frame in it is one this reader tapped.
# A per-style default would put a photograph nobody chose under a page whose
# claim is that it was read off their choices.
check("nothing falls back to a stock image",
      "defaults" not in visuals and "moodboard_step" not in visuals
      and "material_steps" not in visuals, str(sorted(visuals)))
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
check("price is 300 usd",
      cfg["pricing"]["amount_cents"] == 300
      and cfg["pricing"]["currency"] == "usd",
      str(cfg["pricing"]))
# The price is written once and rendered everywhere from that one number.
# A funnel that hardcodes it in a sentence is a funnel that goes stale in one
# place the next time it moves, so no string may carry our own figure.
shown = "$%d" % (cfg["pricing"]["amount_cents"] // 100)
priced = [t for t in re.findall(r'"([^"]*\$[^"]*)"',
                                json.dumps(cfg, ensure_ascii=False))
          if shown in t]
check("  and no copy states it — every mention is the {price} token",
      not priced, str(priced))
check("  which the engine fills from amount_cents",
      "cfg.pricing.amount_cents" in engine
      and "{price}" in cfg["checkout"]["cta_label"])
check("price is an integer number of cents",
      isinstance(cfg["pricing"]["amount_cents"], int))
check("cta names the profile",
      cfg["pricing"]["cta"] == "Unlock my full profile", cfg["pricing"]["cta"])
checkout = cfg["checkout"]
check("product name", checkout["product_name"] == "Your Cosmic Profile Report",
      checkout["product_name"])
check("single page", checkout["single_page"] is True)
check("proof line", checkout["proof_line"] == "Built from your 12 choices",
      checkout["proof_line"])
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
# The mode is pinned as a string above; this is the half that matters — that
# payments.py agrees the string means live, and so reaches for the live key
# set rather than the sandbox one.
check("payments reads this funnel as a live-mode funnel",
      payments._stripe_mode(cfg) == payments.LIVE,
      payments._stripe_mode(cfg))
check("  which is the key set kitchen has always been on",
      payments._stripe_mode(config.load_funnel("kitchen")) == payments.LIVE)
check("  a mode payments does not know would be live, not an error",
      payments._stripe_mode({"stripe_mode": "sandbox"}) == payments.LIVE)
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
for sid in ("hook", "sign", "palette"):
    pair = by_step[sid]["pairs"][0]
    shown = [i["id"] for i in pair["images"]]
    got = tracking._clean_extra("zodiac", "swipe",
                                {"pair": "%s:%s" % (sid, pair["id"]),
                                 "shown": shown, "chosen": shown[0]})
    check("tracking accepts the %s step" % sid, got["chosen"] == shown[0],
          str(got))
# Twelve on one grid. `_clean_extra` gates the shown list on a closed set of
# sizes, and a twelve-up step is a swipe nothing could record until that set
# grew — a whole step of the funnel silently dropping its events.
SIGN_SHOWN = [i["id"] for i in sign_images]
check("tracking accepts a twelve-image shown list",
      len(SIGN_SHOWN) == 12
      and tracking._clean_extra(
          "zodiac", "swipe",
          {"pair": "sign:p1", "shown": SIGN_SHOWN,
           "chosen": "sign_leo"})["chosen"] == "sign_leo")
check("  and the size set is the engine's grid table plus the pair",
      tracking.SHOWN_SIZES == frozenset([2] + sorted(sizes.values())),
      "%s vs %s" % (sorted(tracking.SHOWN_SIZES),
                    sorted(set([2] + list(sizes.values())))))
for bad in (11, 13):
    padded = (SIGN_SHOWN + ["sign_cusp"])[:bad]
    check("  a %d-image shown list is still refused" % bad,
          not _accepts({"pair": "sign:p1", "shown": padded,
                        "chosen": SIGN_SHOWN[0]}))
check("tracking still rejects a pair key this funnel has no variant for",
      not _accepts({"pair": "sign:p_autumn", "shown": SIGN_SHOWN,
                    "chosen": "sign_leo"}))
check("  and a card the step does not offer",
      not _accepts({"pair": "sign:p1",
                    "shown": SIGN_SHOWN[:11] + ["sign_cusp"],
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
# Built rather than read out of the table: the palette stub's colours are
# this archetype's own and are filled in at build time, so the raw entry is
# deliberately not a section yet.
def built_stub(section_id, style):
    return reports._stub_for(section_id, style["name"], style,
                             reports.ZODIAC_STUBS)


check("every stub survives the validator that will police the real thing",
      all(reports.VALIDATORS[i](built_stub(i, style)) is not None
          for i, _ in SHAPE_OF for style in cfg["styles"]),
      str([(i, style["id"]) for i, _ in SHAPE_OF for style in cfg["styles"]
           if reports.VALIDATORS[i](built_stub(i, style)) is None]))
check("  and every palette stub is the archetype's own four colours",
      all([(c["name"], c["hex"]) for c in built_stub("palette", s)["colors"]]
          == reports._style_colors(s) for s in cfg["styles"]))

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


# The unit above says the phrase is spotted. This says what happens next: a
# section that parsed but says one is thrown away and asked for again, and it
# stubs rather than ships if the second answer says it too.
class _Msg(object):
    stop_reason = "end_turn"

    def __init__(self, text):
        self.content = [type("B", (), {"type": "text", "text": text})()]


def _client(answers):
    it = iter(answers)
    return type("C", (), {"messages": type("M", (), {
        "create": staticmethod(lambda **kw: _Msg(next(it)))})})


_clean = json.dumps({"dna": reports._fill(reports.ZODIAC_STUBS["dna"], "X")})
_dirty = json.dumps({"dna": {
    "narrative": ["Our prediction is that your future will change. "
                  + "x" * 60,
                  "A second paragraph long enough to pass. " + "y" * 60],
    "implications": ["one line here that is long enough",
                     "another line here long enough"]}})
check("a banned answer is thrown away and asked for again",
      reports._generate(_client([_dirty, _clean]), "p", ("dna",), 700,
                        reports.ZODIAC_SYSTEM, reports.ZODIAC_BANNED)
      is not None)
check("  and banned twice means a stub rather than shipping it",
      reports._generate(_client([_dirty, _dirty]), "p", ("dna",), 700,
                        reports.ZODIAC_SYSTEM, reports.ZODIAC_BANNED) is None)
check("  kitchen keeps the same payload, because kitchen bans nothing",
      reports._generate(_client([_dirty, _dirty]), "p", ("dna",), 700,
                        reports.SYSTEM, ()) is not None)

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


def walk_with(sign_id):
    """A full 12-choice run that tapped one sign."""
    return [sign_id if s["id"] == "sign" else run[s["id"]] for s in steps]


for image in sign_images:
    got = reports._sign(cfg, walk_with(image["id"]))
    check("  %-18s reads back as %-12s"
          % (image["id"], got and got.get("label")),
          got is not None and got["cusp"] is False
          and got["label"] == image["label"]
          and set(got["tags"]) == set(image["tags"]),
          str(got))
check("all twelve signs resolve",
      len({i["id"] for i in sign_images}) == 12)
# The season step is gone, so there is no season to read. That has to degrade
# rather than throw: _sign still answers, and answers with a sign.
check("a run with no season in it still names the sign",
      reports._sign(cfg, walk_with("sign_leo"))["season"] is None
      and reports._sign(cfg, walk_with("sign_leo"))["label"] == "Leo")
check("  and the prompt block says the sign rather than a season",
      "this reader's sign is Leo"
      in reports._sign_block(cfg, walk_with("sign_leo")))
check("a run with no sign step answered reads back as no sign",
      reports._sign(cfg, [run[s["id"]] for s in steps
                          if s["id"] != "sign"]) is None)

# The cusp is unreachable: no card offers it. The branch that handled one is
# kept anyway — it costs nothing, and a funnel that cannot show twelve at
# once will want it back — so it has to stay sound rather than merely unused.
# Exercised against a config with the card put back, which is the only way to
# reach it and the reason this is not simply deleted.
check("no card can reach the cusp",
      "sign_cusp" not in {i["id"] for i in images}
      and reports._sign(cfg, walk_with("sign_cusp")) is None)
revived = json.loads(json.dumps(cfg))
for step in revived["swipe"]["steps"]:
    if step["id"] == "sign":
        step["pairs"][0]["images"].append({
            "id": "sign_cusp", "label": "Born on a cusp",
            "img": "/static/galleries/zodiac/sign_cusp.webp",
            "tags": ["mystic", "moon"],
            "colors": sign_images[0]["colors"]})
cusp_run = [reports.CUSP_ID if s["id"] == "sign" else run[s["id"]]
            for s in steps]
cusp = reports._sign(revived, cusp_run)
check("the cusp branch still answers when a config offers one",
      cusp is not None and cusp["cusp"] is True
      and cusp["label"] is None, str(cusp))
check("  and still refuses to name a single sign",
      "born on a cusp" in reports._sign_block(revived, cusp_run)
      and "Never assert that they are any one"
      in reports._sign_block(revived, cusp_run))
check("  its art is still on disk for the day it comes back",
      os.path.isfile(os.path.join(GALLERY, "sign_cusp.webp")))

print("\n--- every per-purchase section is written from real taps ---")
leo = walk_with("sign_leo")
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
# The prompt has to follow the tap rather than the archetype: a Pisces who
# scored as Radiant Fire is a real run, and the section is written for the
# Pisces. The cusp wording must not appear at all now that no card offers it.
other = reports._section_prompt(style, "Radiant Fire", {"fire": 8}, "dna",
                                cfg, walk_with("sign_pisces"), "zodiac")
check("the prompt names the sign that was tapped, not the style's",
      "this reader's sign is Pisces" in other
      and "Leo" not in other, "")
check("  and says nothing about a cusp when none was offered",
      "born on a cusp" not in other)
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
for step_id in (list(vis["section_steps"].values())
                + list(vis["hero"].values())):
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


# Tighter than kitchen's 60 KB ceiling, because this report draws eight of
# them rather than three: at 60 KB apiece the mail would be half a megabyte.
heavy = [(i, print_size(i) // 1024) for i in sorted(need)
         if print_size(i) > 34 * 1024]
check("  and none is heavy enough to bloat a mailbox", not heavy, str(heavy))
check("  eight of them together still fit in a mailbox",
      sum(sorted((print_size(i) for i in need), reverse=True)[:8])
      < 250 * 1024,
      "%d KB" % (sum(sorted((print_size(i) for i in need),
                            reverse=True)[:8]) // 1024))
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
stored_visuals = content.get("visuals") or {}
check("and the photographs it is illustrated with",
      set(stored_visuals) == {"sections", "hero"}, str(stored_visuals))
check("  one for every section of the report",
      sorted(stored_visuals.get("sections") or {})
      == sorted(i for i, _ in SHAPE_OF),
      str(sorted(stored_visuals.get("sections") or {})))
check("  every one of them a frame this run actually tapped",
      all(image_id in leo
          for image_id in (stored_visuals.get("sections") or {}).values()),
      str([i for i in (stored_visuals.get("sections") or {}).values()
           if i not in leo]))
check("  and the header's two as well",
      all(image_id in leo
          for image_id in (stored_visuals.get("hero") or {}).values()),
      str(stored_visuals.get("hero")))

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
cover_out = html_out.split('<section class="cover">')[1].split("</section>")[0]
check("the cover names this product",
      cfg["result_copy"]["kicker"] in cover_out
      and "Your kitchen style report" not in html_out, cover_out[:160])
check("  as the hero card off the result page",
      '<div class="cover-card">' in cover_out
      and 'class="cover-el' in cover_out)
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

print("\n--- every prompt states a length for every field that has one ---")
# A warm run of all four styles lost `splurge` on every one of them, twice
# each: `why` came back 663-770 characters against a ceiling of 600 because
# the shape asked for "3-5 sentences" and named no number, and the retry
# repeated the prompt so the model repeated the overrun.
#
# The caps are walked here off SHAPE directly rather than through the helper
# reports.py uses, so a bug in that helper cannot hide by agreeing with
# itself.
BUDGET_RE = re.compile(r"^  (\S+)\s+(\d+) characters maximum$", re.M)
HEADROOM = 0.75

# The palette's names and codes are the reader's own power colours, handed to
# the model in the prompt and reproduced exactly. They are the only fields in
# the six sections the model does not write.
COPIED = {("palette", "colors[].name"), ("palette", "colors[].hex")}


def declared_caps(section_id):
    """{path: (floor, ceiling)} for every capped text field of a section."""
    out = {}
    for key, spec in reports.SHAPE[section_id].items():
        if spec[0] == "text":
            out[key] = (spec[1], spec[2])
        elif spec[0] == "obj":
            for field, rule in spec[1].items():
                if rule[0] == "text":
                    out["%s.%s" % (key, field)] = (rule[1], rule[2])
        elif spec[0] == "list":
            fields = spec[3]
            if isinstance(fields, tuple):
                if fields[0] == "text":
                    out["%s[]" % key] = (fields[1], fields[2])
            else:
                for field, rule in fields.items():
                    if rule[0] == "text":
                        out["%s[].%s" % (key, field)] = (rule[1], rule[2])
    return out


for section_id, _ in SHAPE_OF:
    spec = reports.ZODIAC_SPEC[section_id]
    stated = dict((path, int(n)) for path, n in BUDGET_RE.findall(spec))
    caps = declared_caps(section_id)
    check("%-10s states a budget for every capped field" % section_id,
          set(stated) == set(caps),
          "missing %s, extra %s" % (sorted(set(caps) - set(stated)),
                                    sorted(set(stated) - set(caps))))
    for path in sorted(caps):
        if path not in stated:
            continue
        floor, ceiling = caps[path]
        asked = stated[path]
        check("  %-24s asks %4d of %4d (%.0f%%)"
              % ("%s.%s" % (section_id, path), asked, ceiling,
                 100.0 * asked / ceiling),
              floor < asked <= ceiling * HEADROOM,
              "floor %d, ceiling %d" % (floor, ceiling))
        # The number has to be beside the field in the shape too, not only in
        # the recap: the shape example is what a model copies from.
        # Except the two the model is told to copy character for character
        # out of the config: a length beside a field whose value is given is
        # an invitation to edit it.
        if (section_id, path) in COPIED:
            check("    is copied, so states no length beside it",
                  "max %d chars" % asked not in spec)
            continue
        check("    and says so beside the field itself",
              "max %d chars" % asked in spec)

print("\n--- and names its keys, because one style renamed them ---")
# One warm run answered `splurge` with `item` and `why` at the top level
# instead of splurge/saves/split_note, which is a whole section lost to a
# spelling.
for section_id, _ in SHAPE_OF:
    spec = reports.ZODIAC_SPEC[section_id]
    for key in reports.SHAPE[section_id]:
        check("  %-10s names `%s`" % (section_id, key),
              "`%s`" % key in spec or '"%s"' % key in spec)
check("splurge says which keys are NOT top level",
      "Do not send `item` or `why` at the top level"
      in reports.ZODIAC_SPEC["splurge"])

print("\n--- a refusal comes back as a correction, not a repetition ---")


def _answers(seq):
    """A stub client, and the list of prompts it was sent."""
    it = iter(seq)
    sent = []

    def create(**kw):
        sent.append(kw["messages"][0]["content"])
        return _Msg(next(it))

    return type("C", (), {"messages": type("M", (), {
        "create": staticmethod(create)})}), sent


GOOD = json.dumps({"splurge": reports._fill(reports.ZODIAC_STUBS["splurge"],
                                            "Deep Water")})
# The production shape of the failure: everything valid but one long `why`.
OVERRUN = json.dumps({"splurge": {
    "splurge": {"item": "Work with a visible edge", "why": "w" * 707},
    "saves": [{"item": "Work that needs performing", "why": "y" * 200},
              {"item": "Roles built on maintaining", "why": "y" * 200},
              {"item": "Anything measured in hours", "why": "y" * 200}],
    "split_note": "Give the deep half of the week to the work with an edge."}})

client, sent = _answers([OVERRUN, GOOD])
got = reports._generate(client, "SHAPE", ("splurge",), 900,
                        reports.ZODIAC_SYSTEM, reports.ZODIAC_BANNED, True)
check("a too-long answer is corrected on the retry", got is not None)
check("  and the retry was asked twice, not once", len(sent) == 2, len(sent))
retry = sent[1]
check("  the retry names the field that overran",
      "splurge.why" in retry, retry[-300:])
check("  with the count it sent and the bound it broke",
      "707 chars, want 15-600" in retry, retry[-300:])
check("  and tells it the counts are hard limits",
      "hard limits" in retry)
check("  the first ask carried no correction",
      "previous answer was refused" not in sent[0])

# Key drift, the other production failure, has no field-level forensics
# behind it — it fails before the validator — so the reason line is what has
# to reach the retry.
DRIFTED = json.dumps({"splurge": {"item": "x", "why": "y" * 40}})
client, sent = _answers([DRIFTED, GOOD])
check("key drift is corrected too",
      reports._generate(client, "SHAPE", ("splurge",), 900,
                        reports.ZODIAC_SYSTEM, reports.ZODIAC_BANNED, True)
      is not None)
check("  and the retry names the keys that went missing",
      "missing 'splurge'" in sent[1] and "missing 'saves'" in sent[1],
      sent[1][-300:])

# A truncated answer never reaches the validator either.
client, sent = _answers(['{"splurge": {"splurge": {"item": "x", "why', GOOD])
reports._generate(client, "SHAPE", ("splurge",), 900, reports.ZODIAC_SYSTEM,
                  reports.ZODIAC_BANNED, True)
check("a truncated answer is told it was truncated",
      "unterminated" in sent[1] or "truncated" in sent[1], sent[1][-200:])

client, sent = _answers([json.dumps({"splurge": {
    "splurge": {"item": "Work", "why": "Our prediction is " + "w" * 100},
    "saves": [{"item": "Performing work", "why": "y" * 40},
              {"item": "Maintaining work", "why": "y" * 40}],
    "split_note": "s" * 40}}), GOOD])
reports._generate(client, "SHAPE", ("splurge",), 900, reports.ZODIAC_SYSTEM,
                  reports.ZODIAC_BANNED, True)
check("a banned phrase is quoted back so it is not repeated",
      'the phrase "prediction" is not allowed' in sent[1], sent[1][-300:])

print("\n--- kitchen's retry is the one it has always been ---")
client, sent = _answers([OVERRUN, GOOD])
reports._generate(client, "SHAPE", ("splurge",), 900, reports.SYSTEM, (),
                  False)
check("byte for byte, prompt plus the bare note",
      sent[1] == "SHAPE" + reports.RETRY_NOTE, repr(sent[1][-120:]))
check("  with no drift block appended",
      "previous answer was refused" not in sent[1])
check("kitchen's profile does not ask for one",
      reports._profile("kitchen")["retry_detail"] is False
      and reports._profile("kitchen-visualizer")["retry_detail"] is False)
check("zodiac's does",
      reports._profile("zodiac")["retry_detail"] is True)
check("and _parse_detail still answers the old way when nothing is passed",
      reports._parse_detail(GOOD, ("splurge",))[0] is not None)

print("\n--- the caps themselves are kitchen's and did not move ---")
check("shopping still 4-12 items, 0-3 skips",
      reports.SHAPE["shopping"]["items"][1:3] == (4, 12)
      and reports.SHAPE["shopping"]["skip"][1:3] == (0, 3))
check("no text ceiling anywhere is above 600",
      max(c for sid in reports.SHAPE for _, c in declared_caps(sid).values())
      == 600)
check("every zodiac budget is derived from SHAPE, not written out again",
      all(reports._budget(cap) == asked
          for sid, _ in SHAPE_OF
          for path, (floor, cap) in declared_caps(sid).items()
          for asked in [dict((p, int(n)) for p, n in
                             BUDGET_RE.findall(reports.ZODIAC_SPEC[sid]))
                        [path]]))

print("\n--- what the kitchen funnels must not have picked up ---")
# engine.js, mazzin.css and tracking.py all moved for this funnel. Every one
# of those changes is reached through a config flag or a table entry, so the
# proof that kitchen is untouched is that its configs ask for none of them.
for slug in ("kitchen", "kitchen-visualizer"):
    other = json.load(open(os.path.join(ROOT, "funnels/%s.json" % slug)))
    other_steps = other["swipe"]["steps"]
    check("%-18s sets no label_mode" % slug,
          "label_mode" not in other["swipe"],
          str(other["swipe"].get("label_mode")))
    check("  so its cards name themselves only after a tap",
          not any("label_mode" in json.dumps(st)
                  for st in other_steps))
    check("  no step of it asks for grid12",
          not [st["id"] for st in other_steps if st["format"] == "grid12"],
          str(sorted({st["format"] for st in other_steps})))
    check("  and none opts out of the shuffle",
          not [st["id"] for st in other_steps if st.get("shuffle") is False],
          str([st["id"] for st in other_steps if "shuffle" in st]))
    check("  its shown sizes were all legal before this change",
          all(sizes.get(st["format"], 2) in (2, 4, 6) for st in other_steps))
# The label node itself is gated on the flag in engine.js, not on the format,
# so the gate is worth reading rather than trusting.
check("engine.js draws a permanent label only when a funnel asks for one",
      'labelMode() === "badge"' in engine
      and 'cfg.swipe.label_mode' in engine)
check("  and the flag is absent by default rather than off",
      'label_mode) || ""' in engine)
check("  badge is the only mode there is",
      "labelMode() ===" in engine
      and len(re.findall(r'labelMode\(\) === "(\w+)"', engine)) == 1
      and re.findall(r'labelMode\(\) === "(\w+)"', engine) == ["badge"],
      str(re.findall(r'labelMode\(\) === "(\w+)"', engine)))
check("mazzin.css styles that label under its own class",
      ".card-name {" in css and ".cards.is-grid12 .card-name {" in css)

# The label used to be a scrim across the whole card, and the scrim was the
# thing that had to go: it dimmed every frame it sat on and covered the sign
# glyph. The art is the product. A rule that paints over it is the regression
# this mode exists to prevent, so the stylesheet is read for one.
label_rule = css[css.index("\n.card-name {") + 1:]
label_rule = label_rule[:label_rule.index("}")]
check("the label paints no gradient over the picture",
      "gradient" not in label_rule, label_rule)
# Anywhere a card is painted, rather than anywhere at all: the interstitial
# between steps is allowed a gradient, and does have one. What may not have
# one is anything drawn over the artwork.
card_rules = [block for block in css.split("}")
              if ".card" in block.split("{")[0]]
check("  nowhere a card is painted, in fact",
      not [b for b in card_rules if "gradient" in b.split("{")[-1]],
      str([b.split("{")[0].strip() for b in card_rules
           if "gradient" in b.split("{")[-1]]))
check("  it is a pill, not a panel",
      "border-radius: 999px" in label_rule
      and "bottom:" in label_rule and "inset: 0" not in label_rule)
check("  carrying its own background rather than borrowing the art's",
      "rgba(16, 20, 40, 0.88)" in label_rule)
check("  with the blur as an enhancement over that, not instead of it",
      "backdrop-filter: blur(4px)" in css
      and css.index("rgba(16, 20, 40, 0.88)")
      < css.index("rgba(16, 20, 40, 0.75)"))
check("  and one line only, truncated rather than grown",
      "white-space: nowrap" in label_rule
      and "text-overflow: ellipsis" in label_rule)
check("the shuffle opt-out is per step and defaults to shuffling",
      "st.shuffle === false" in engine)


print("\n--- this funnel brings its own result page ---")
# engine.js loads whatever these name and falls back to its own result if the
# load fails, so a path that points at nothing is a funnel that silently
# reverts to a page this design replaced.
for key in ("result_module", "result_css"):
    path = cfg.get(key) or ""
    check("%s is declared" % key, path.startswith("/static/"), repr(path))
    check("  and the file is on disk",
          os.path.isfile(os.path.join(ROOT, path.lstrip("/"))), path)
module = open(os.path.join(ROOT, cfg["result_module"].lstrip("/")),
              encoding="utf-8").read()
module_css = open(os.path.join(ROOT, cfg["result_css"].lstrip("/")),
                  encoding="utf-8").read()
check("the module exports the entry engine.js calls",
      "window.MazzinResult" in module and "render:" in module)
check("engine.js calls exactly that",
      "window.MazzinResult" in engine and "mod.render(" in engine)
# The module must not grow its own payment. engine.js hands it the live
# consent box and pay button; a module that fetched a checkout itself would
# be a second, untested way to take money.
check("the module makes no payment of its own",
      "/api/checkout" not in module and "payment-intent" not in module
      and "fetch(" not in module)
check("  it places the nodes engine.js wired instead",
      "nodes.consent" in module and "nodes.payButton" in module)
# Every rule scoped, so kitchen's result cannot pick any of it up.
stray = [line for line in module_css.split("\n")
         if line and not line[0].isspace()
         and not line.startswith(("/*", "*", "}", "@", ".result-module",
                                  ".zr-", "body:has(.result-module)"))]
check("every rule in the stylesheet is scoped to this module",
      not stray, str(stray[:3]))
check("  and mazzin.css was not touched for it",
      ".zr-" not in css and "result-module" not in css)

print("\n--- the copy the module reads ---")
copy = cfg.get("result_copy") or {}
for key in ("kicker", "blend_note", "taps_caption", "balance_title",
            "strength_lead", "offer_sub"):
    check("  result_copy.%-14s is set" % key,
          isinstance(copy.get(key), str) and copy[key].strip(),
          repr(copy.get(key)))
# The lead line above the free strength is filled through the engine's hook
# slots, so every token in it has to be one of them or it reaches the reader
# with braces in it.
tokens = set(re.findall(r"\{(\w+)\}", copy.get("strength_lead", "")))
check("strength_lead names only real hook slots",
      tokens and tokens <= set(cfg["report"]["hook_slots"]),
      str(sorted(tokens)))
check("locked sections each carry a teaser line",
      all(s.get("teaser_line", "").strip() for s in sections
          if s["id"] in locked),
      str([s["id"] for s in sections
           if s["id"] in locked and not s.get("teaser_line", "").strip()]))
check("  and the visible one does not",
      not [s for s in sections
           if s["id"] not in locked and s.get("teaser_line")])
for section in sections:
    line = section.get("teaser_line") or ""
    if not line:
        continue
    seen = set(re.findall(r"\{(\w+)\}", line))
    check("  %-9s teaser fills from real hook slots" % section["id"],
          seen <= set(cfg["report"]["hook_slots"]), str(sorted(seen)))
    check("    and is one short line", len(line) <= 90 and "\n" not in line,
          "%d chars" % len(line))
# The Terms line covers everything the reader is shown, and these two blocks
# are new places to break it.
for label, text in ([("blend_note", copy.get("blend_note", "")),
                     ("strength_lead", copy.get("strength_lead", "")),
                     ("kicker", copy.get("kicker", "")),
                     ("offer_sub", copy.get("offer_sub", ""))]
                    + [("teaser %s" % s["id"], s.get("teaser_line", ""))
                       for s in sections]):
    hit = reports._banned_hit(text, reports.ZODIAC_BANNED)
    check("  %-20s says nothing banned" % label, hit is None, hit)

print("\n--- the bridges between a light quiz and a dark report ---")
# Three config keys, each of which changes something a kitchen funnel also
# draws. Every one of them is read behind a test for its own presence, so a
# funnel that does not set it renders exactly what it always did — which is
# what the second half of this block is for.
check("the funnel names a theme", cfg.get("theme") == "zodiac",
      cfg.get("theme"))
check("  engine.js puts it on the body as a class",
      "theme-" in engine and "cfg.theme" in engine)
check("  and only ever a name it can vouch for",
      "/^[a-z0-9-]{1,24}$/.test(theme)" in engine)
check("  mazzin.css paints the quiz furniture under it",
      all(("body.theme-zodiac %s" % sel) in css
          for sel in (".pip.is-done {",
                      ".cards.is-grid12 .card.is-chosen .card-name {",
                      "#screen-interstitial.is-active {")),
      "")
check("the analysing screen is told where to land",
      re.match(r"^#[0-9A-Fa-f]{6}$",
               cfg["swipe"].get("analyzing_fade_to") or ""),
      cfg["swipe"].get("analyzing_fade_to"))
check("  which is the ground the report opens on",
      cfg["swipe"]["analyzing_fade_to"].upper() == "#0E1430")
check("  engine.js reads it and validates it as a colour",
      "analyzing_fade_to" in engine
      and "/^#[0-9a-fA-F]{3,8}$/.test(to)" in engine)
check("  and the fade itself is one class on the body",
      "is-fading" in engine and "body.is-fading {" in css)
check("  taking as long as the screen it runs under",
      "cfg.analyzing && cfg.analyzing.duration_ms" in engine)
check("the delivered page has a line about where else it is",
      "PDF" in (cfg["result_copy"].get("delivered_note") or ""),
      cfg["result_copy"].get("delivered_note"))
check("  and the module draws it only once the report is whole",
      "ctx.complete && copy.delivered_note" in module)


print("\n--- and kitchen brings none ---")
for slug in ("kitchen", "kitchen-visualizer"):
    other = json.load(open(os.path.join(ROOT, "funnels/%s.json" % slug)))
    check("%-18s names no result module" % slug,
          "result_module" not in other and "result_css" not in other)
    check("  no theme, so no rule in the sheet can reach it",
          "theme" not in other)
    check("  and nothing telling its analysing screen to go dark",
          "analyzing_fade_to" not in other["swipe"])
    check("  and no section of it carries a teaser line",
          not [s for s in other["report"]["sections"] if s.get("teaser_line")])
check("engine.js only delegates when a funnel asks",
      "cfg.result_module" in engine
      and 'if (resultModule())' in engine)
check("  and the paid report is never delegated",
      "SECTION_BODY[sec.id]" in engine
      and "SECTION_BODY" not in module)
# renderModuleResult hides #report so the module's page can stand in front of
# it, and the paid view fills that same container. Unreachable while both
# ways of paying navigate; asserted so it stays fixed if one stops.
check("  and it takes its container back before drawing",
      "el.report.hidden = false;\n      if (el.moduleRoot)" in engine)


print("\n--- the offer takes a wallet, and asks for no consent ---")
check("express is on", cfg["checkout"].get("express") is True,
      cfg["checkout"].get("express"))
check("  the same key kitchen-visualizer turns on",
      "express" in json.load(open(os.path.join(
          ROOT, "funnels/kitchen-visualizer.json")))["checkout"])
# /api/payment-intent validates any funnel through the same order builder as
# /api/checkout. Worth asserting rather than assuming: a funnel allowlist
# appearing there later would break this one silently.
check("  and payments needs no registration for it",
      payments._validated_order.__doc__ is not None
      and "express" not in open(os.path.join(ROOT, "payments.py")).read())
# `xpStart` hangs off `showOffer`, which returns early when a funnel has no
# gate node. Both funnels here are gateless, so without this the flag would
# be a config key that did nothing.
check("engine.js starts express for a funnel with no gate",
      "if (!el.gate) xpStart();" in engine)
check("  and the wallet's own nodes travel with the pay button",
      "wallet: xpBlock" in engine and "walletSummary" in engine
      and "nodes.wallet" in module and "nodes.walletSummary" in module)

check("the consent box is off for everyone",
      cfg["checkout"].get("withdrawal_consent") is False,
      cfg["checkout"].get("withdrawal_consent"))
check("  which is not the country list",
      "consent_skip_countries" not in cfg["checkout"])
check("  and the line it stood next to is gone",
      "consent" not in cfg["checkout"]["commerce"])
check("the module places it only when a funnel wants one",
      "withdrawal_consent !== false" in module)
check("  and ticks it when it does not, so the button is not dead",
      "box.checked = true" in module)
for slug in ("kitchen", "kitchen-visualizer"):
    other = json.load(open(os.path.join(ROOT, "funnels/%s.json" % slug)))
    check("%-18s keeps its consent box" % slug,
          other["checkout"].get("withdrawal_consent") is not False)
    check("  and its consent line", "consent" in other["checkout"]["commerce"])

print("\n--- the header names the product ---")
check("subtext names it",
      cfg["swipe"]["subtext"] == "Your Cosmic Profile in 60 seconds of taps",
      cfg["swipe"]["subtext"])
check("  with the accent still on the time",
      cfg["swipe"]["subtext_accent"] == "60 seconds"
      and cfg["swipe"]["subtext_accent"] in cfg["swipe"]["subtext"])
check("  and the headline still pairs with it",
      cfg["swipe"]["headline"].lower().startswith("your cosmic profile"),
      cfg["swipe"]["headline"])

print("\n--- the mail and the report are this funnel's ---")
check("zodiac has a dark stylesheet for the PDF",
      bool(reports._profile("zodiac").get("pdf_css")))
check("  and kitchen has none, so it renders the sheet it always did",
      reports._profile("kitchen").get("pdf_css") is None
      and reports._profile("kitchen-visualizer").get("pdf_css") is None)
check("the dark sheet covers every ink the base sheet uses",
      all(sel in reports.ZODIAC_PDF_CSS for sel in
          (".cover-name", ".section-title", ".callout", ".swatch-text b",
           ".numbered b", ".verdict b", ".skip b", ".saves b",
           ".implication", ".hex", ".struck", ".cover-lead", ".cover-note",
           "figure figcaption")),
      "a selector the base sheet paints dark is unaccounted for")
check("  including the page ground itself",
      "@page { background: #0E1430; }" in reports.ZODIAC_PDF_CSS)
check("the mail is a table, not a div",
      "<table" in reports.ZODIAC_EMAIL_HTML
      and "<div" not in reports.ZODIAC_EMAIL_HTML)
check("  carrying bgcolor as well as CSS, for the light-mode clients",
      reports.ZODIAC_EMAIL_HTML.count('bgcolor="#0E1430"') >= 6)
check("  with no style block and no web font",
      "<style" not in reports.ZODIAC_EMAIL_HTML
      and "@font-face" not in reports.ZODIAC_EMAIL_HTML
      and "fonts.googleapis" not in reports.ZODIAC_EMAIL_HTML)
check("  and the gold the page ends on",
      "#E8C878" in reports.ZODIAC_EMAIL_HTML)
check("kitchen's mail template is untouched",
      reports.EMAIL_HTML.startswith('<div style="font-family:-apple-system'))


print("\n%d checks, %d failed" % (checks[0], len(fails)))
for f in fails:
    print("  FAIL " + f)
sys.exit(1 if fails else 0)
