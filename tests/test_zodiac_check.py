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
    ("sign", "grid6", "Which sign speaks to you?"),
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
check("the sign step ids are sign_<name>",
      all(i["id"].startswith("sign_") for i in
          by_step["sign"]["pairs"][0]["images"]),
      str([i["id"] for i in by_step["sign"]["pairs"][0]["images"]]))
check("the six signs cover all four elements",
      {t for i in by_step["sign"]["pairs"][0]["images"] for t in i["tags"]}
      & ELEMENTS == ELEMENTS)
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
# `default`. So an adaptive step in this config is only meaningful if engine.js
# already carries its axis. It does not carry "season", which is why the sign
# step is a plain grid6 rather than four seasonal variants.
engine = open(os.path.join(ROOT, "static/js/engine.js")).read()
known = set(re.findall(r"(\w+):\s*\w+_AXIS",
                       re.search(r"var AXES = \{([^}]*)\}", engine).group(1)))
check("engine.js declares its axes", bool(known), str(known))
check("season is not one of them — the sign step cannot adapt on it",
      "season" not in known, str(sorted(known)))
declared = [(s["id"], (s.get("adaptive") or {}).get("axis"))
            for s in steps if s.get("adaptive")]
check("no step adapts on an axis engine.js cannot resolve",
      all(axis in known for _, axis in declared), str(declared))

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
check("every image id is unique", len(by_id) == len(images), str(len(images)))
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
    ("grounded_earth", "Grounded Earth", ["earth", "calm"]),
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
check("section ids and titles",
      [(s["id"], s["title"]) for s in sections]
      == [("palette", "Your Power Palette & Talismans"),
          ("strengths", "5 Hidden Strengths & Blind Spots"),
          ("profile", "Your Cosmic Blueprint"),
          ("love", "Love & Compatibility"),
          ("career", "Career & Money Path"),
          ("year", "Your 12-Month Energy Map")],
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
check("the hero is the strengths section",
      hero == "strengths" and hero in locked, hero)
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
# computeWinner sums the run's tag scores over each style's tags, so a style
# whose own persona does not win it is a style nobody can ever be given.


def winner(scores):
    best, best_score = None, float("-inf")
    for style in cfg["styles"]:
        total = sum(scores.get(t, 0) for t in style["tags"])
        if total > best_score:
            best, best_score = style["id"], total
    return best


def play(pick):
    """One run, as engine.js scores it: -0.5 a tag on the inverse step, 1 on
    every other."""
    scores = {}
    for step in steps:
        options = [i for p in step["pairs"] for i in p["images"]]
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

# Not a balance target — the archetypes are deliberately not equally weighted,
# because the tag vocabulary puts fire and water on more frames than earth and
# air. This is the floor under that: a style that a random walk can never
# reach is one the funnel cannot actually award, and it would be invisible
# from the checks above, which only ever play a style's own persona.
rng = random.Random(20260821)
seen = collections.Counter(
    winner(play(lambda s, o: rng.choice(o))) for _ in range(20000))
for style in cfg["styles"]:
    share = seen[style["id"]] / 200.0
    check("  %-15s is reachable at random (%.1f%% of runs)"
          % (style["id"], share), share >= 2.0)

print("\n--- server side ---")
import config  # noqa: E402
import payments  # noqa: E402
import tracking  # noqa: E402

check("the slug is routable", config.funnel_exists("zodiac"))
check("load_funnel returns this config", config.load_funnel("zodiac") == cfg)
choices = [s["pairs"][0]["images"][0]["id"] for s in steps]
check("checkout accepts a 13-long choice list",
      payments._clean_choices(cfg, choices) == choices)
check("checkout rejects a 14-long list",
      payments._clean_choices(cfg, choices + ["sy8a"]) is None)
check("tag scores validate against this vocabulary",
      payments._clean_tag_scores(cfg, {"fire": 6, "sun": 5, "bold": 4})
      == {"fire": 6, "sun": 5, "bold": 4})
for sid in ("hook", "sign", "palette"):
    shown = [i["id"] for i in by_step[sid]["pairs"][0]["images"]]
    got = tracking._clean_extra("zodiac", "swipe",
                                {"pair": sid + ":p1", "shown": shown,
                                 "chosen": shown[0]})
    check("tracking accepts the %s step" % sid, got["chosen"] == shown[0],
          str(got))
try:
    tracking._clean_extra("zodiac", "swipe",
                          {"pair": "hook:p1", "shown": ["hk1a", "zk1b"],
                           "chosen": "zk1b"})
    check("tracking rejects an image from another funnel", False)
except ValueError:
    check("tracking rejects an image from another funnel", True)
check("tracking allows step 13", tracking._clean_step(13) == 13)

print("\n%d checks, %d failed" % (checks[0], len(fails)))
for f in fails:
    print("  FAIL " + f)
sys.exit(1 if fails else 0)
