#!/usr/bin/env python3
"""Integrity checks over the funnel config and the server code that reads it."""
import json
import os
import sys

# The repo root, derived from this file rather than hardcoded: a suite
# that only runs from one absolute path is a suite that stops running the
# first time the checkout moves.
REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

sys.path.insert(0, REPO)
ROOT = REPO
GALLERY = os.path.join(ROOT, "static/galleries/kitchen")

fails = []
checks = [0]


def check(label, ok, detail=""):
    checks[0] += 1
    if not ok:
        fails.append("%s %s" % (label, detail))
    print("  %-58s %s%s" % (label, "ok" if ok else "FAIL",
                            ("  " + detail) if detail and not ok else ""))


cfg = json.load(open(os.path.join(ROOT, "funnels/kitchen.json")))
static_cfg = json.load(open(os.path.join(ROOT, "static/funnels/kitchen.json")))
steps = cfg["swipe"]["steps"]
GRID = {"grid4": 4, "grid6": 6}

print("\n--- config shape ---")
check("static copy matches funnels/", cfg == static_cfg)
check("pairs_count == number of steps",
      cfg["swipe"]["pairs_count"] == len(steps) == 13,
      "%s vs %s" % (cfg["swipe"]["pairs_count"], len(steps)))
check("money line leads with the saving",
      cfg["swipe"]["subtext"].startswith("$4,000+"), cfg["swipe"]["subtext"])
check("analyzing copy names 13", "13" in cfg["analyzing"]["messages"][0])
check("checkout proof line names 13", "13" in cfg["checkout"]["proof_line"])

print("\n--- step 1 is the static hook ---")
hook = steps[0]
check("step 1 id is hook", hook["id"] == "hook")
check("hook question",
      hook["question"] == "Which kitchen would you walk into?",
      hook["question"])
check("hook is a pair", hook["format"] == "pair")
check("hook is not adaptive", "adaptive" not in hook)
check("hook has exactly one pair (never drawn)", len(hook["pairs"]) == 1)
check("hook images are hk1a/hk1b",
      [i["id"] for i in hook["pairs"][0]["images"]] == ["hk1a", "hk1b"])
check("hook labels",
      [i["label"] for i in hook["pairs"][0]["images"]]
      == ["Evening drama", "Morning light"])
check("hook tags",
      [i["tags"] for i in hook["pairs"][0]["images"]]
      == [["dark", "warm", "wood"], ["bright", "warm", "wood"]])
check("no color_family on the hook",
      not any("color_family" in i for i in hook["pairs"][0]["images"]))

print("\n--- regen wiring ---")
by_step = {s["id"]: s for s in steps}
palette = by_step["color"]["pairs"][0]["images"]
check("palette is mp1-mp6",
      [i["id"] for i in palette] == ["mp1", "mp2", "mp3", "mp4", "mp5", "mp6"])
check("palette carries all six families",
      [i["color_family"] for i in palette]
      == ["deep-dramatic", "soft-neutral", "urban-grey", "crisp-white",
          "moss-earth", "dusty-blue"])
light = by_step["lighting"]["pairs"][0]["images"]
check("lighting is lt3a/lt3b", [i["id"] for i in light] == ["lt3a", "lt3b"])
check("lighting labels",
      [i["label"] for i in light] == ["Golden pools", "Crisp & bright"])
mat = by_step["materials"]["pairs"][0]["images"]
check("texture is mt1-mt4",
      [i["id"] for i in mat] == ["mt1", "mt2", "mt3", "mt4"])
check("materials labels",
      [i["label"] for i in mat]
      == ["Rich & bold", "Light & natural", "Soft & raw", "Sleek & polished"])

retired = {"g1a", "g1b", "g1c", "g1d", "g1e", "g1f", "c3a", "c3b",
           "m12a", "m12b", "m12c", "m12d", "m12e", "m12f",
           "p2a", "p2b", "p2c", "p2d", "p2e", "p2f",
           "t12a", "t12b", "t12c", "t12d"}
live = {i["id"] for s in steps for p in s["pairs"] for i in p["images"]}
check("retired ids are out of the quiz", not (retired & live),
      str(sorted(retired & live)))
check("retired files still on disk",
      all(os.path.exists(os.path.join(GALLERY, r + ".webp"))
          for r in retired - {"m12c", "m12d"}))

print("\n--- images, colours, tags ---")
HEX = set("0123456789ABCDEF")
for step in steps:
    for pair in step["pairs"]:
        want = GRID.get(step.get("format"), 2)
        check("step %-11s pair %-7s has %d images"
              % (step["id"], pair["id"], want), len(pair["images"]) == want,
              str(len(pair["images"])))
        for img in pair["images"]:
            ok = (os.path.exists(os.path.join(GALLERY,
                                              img["img"].rsplit("/", 1)[-1]))
                  and len(img["tags"]) == 3
                  and img.get("colors")
                  and all(c["hex"][0] == "#" and len(c["hex"]) == 7
                          and set(c["hex"][1:]) <= HEX
                          and c.get("name") and c.get("element")
                          for c in img["colors"]))
            if not ok:
                check("  image %s" % img["id"], False, json.dumps(img)[:120])
check("every image id is unique", len(live) == len(
    [i for s in steps for p in s["pairs"] for i in p["images"]]))

print("\n--- interstitials ---")
anchors = [i["after_step"] for i in cfg["interstitials"]]
check("anchors are 4/7/10", anchors == [4, 7, 10], str(anchors))
names = [steps[a - 1]["id"] for a in anchors]
check("anchors land after lighting/floor/hardware",
      names == ["lighting", "floor", "hardware"], str(names))
check("last anchor leaves three steps", len(steps) - anchors[-1] == 3)
check("'three more' copy matches",
      "Three more" in cfg["interstitials"][2]["sub"])

print("\n--- style elements ---")
block = cfg["style_elements"]
items = block["items"]
by_id = {i["id"]: i for s in steps for p in s["pairs"] for i in p["images"]}
check("title", block["title"] == "Your Style Elements")
# The strip stops claiming to specify anything: the specification is what
# the report is for, and the free chips are down to a thumbnail and a name.
check("subline", block["subline"]
      == "Recognized from your choices — specified in your full report.",
      block["subline"])
check("13 elements mapped", len(items) == 13, str(len(items)))
check("every element points at a live quiz image",
      all(e["image"] in by_id for e in items),
      str([e["image"] for e in items if e["image"] not in by_id]))
check("element thumbs match their image path",
      all(e["img"] == by_id[e["image"]]["img"] for e in items))
check("element tags match their image tags",
      all(e["tags"] == by_id[e["image"]]["tags"] for e in items))
check("element ids unique", len({e["id"] for e in items}) == len(items))
check("element labels unique", len({e["label"] for e in items}) == len(items))

print("\n--- styles ---")
vocab = {t for i in by_id.values() for t in i["tags"]}
for style in cfg["styles"]:
    check("style %-14s tags are real" % style["id"],
          set(style["tags"]) <= vocab,
          str(set(style["tags"]) - vocab))
check("every style keeps its own name tag",
      all(any(t in s["id"] or s["id"].endswith(t) for t in s["tags"])
          for s in cfg["styles"]))

print("\n--- server side ---")
import reports  # noqa: E402
import payments  # noqa: E402
import tracking  # noqa: E402

choices = [p["pairs"][0]["images"][0]["id"] for p in steps]
check("checkout accepts a 13-long choice list",
      payments._clean_choices(cfg, choices) == choices)
check("checkout rejects a 14-long list",
      payments._clean_choices(cfg, choices + ["h9b"]) is None)
scores = {"warm": 8, "wood": 6, "dark": 5}
check("tag scores still validate",
      payments._clean_tag_scores(cfg, scores) == scores)
labels = reports._shown_elements(cfg, choices, scores)
check("report context names six elements", len(labels) == 6, str(labels))
check("element labels are real labels",
      set(labels) <= {e["label"] for e in items})
block_text = reports._choice_block(cfg, choices, scores)
check("choice block carries the elements line",
      "already been shown these as their style elements" in block_text)
check("choice block counts 13 choices", "The 13 choices" in block_text)
prompt = reports._section_prompt(cfg["styles"][0], "Modern Rustic", scores,
                                 "materials", cfg=cfg, choices=choices)
check("materials prompt carries the elements line",
      "style elements" in prompt)
palette_prompt = reports._section_prompt(cfg["styles"][0], "Modern Rustic",
                                         scores, "palette", cfg=cfg,
                                         choices=choices)
check("palette prompt still anchored on the colour family",
      "chosen color family" in palette_prompt)

# tracking: a 2-image shown list on the new hook step
check("tracking accepts the hook pair's shown list",
      tracking._clean_extra("kitchen", "swipe",
                            {"pair": "hook:p1", "shown": ["hk1a", "hk1b"],
                             "chosen": "hk1a"})
      == {"pair": "hook:p1", "shown": ["hk1a", "hk1b"], "chosen": "hk1a"})
check("tracking accepts the six-up palette", tracking._clean_extra(
    "kitchen", "swipe",
    {"pair": "color:p1", "shown": [i["id"] for i in palette],
     "chosen": "mp3"})["chosen"] == "mp3")
check("tracking accepts the six-up floor", tracking._clean_extra(
    "kitchen", "swipe",
    {"pair": "floor:p1",
     "shown": [i["id"] for i in by_step["floor"]["pairs"][0]["images"]],
     "chosen": "f6e"})["chosen"] == "f6e")
check("tracking still allows step 13", tracking._clean_step(13) == 13)
try:
    tracking._clean_extra("kitchen", "swipe",
                          {"pair": "hook:p1", "shown": ["p2a", "hk1b"],
                           "chosen": "hk1b"})
    check("tracking rejects a retired image", False)
except ValueError:
    check("tracking rejects a retired image", True)

print("\n--- phase 6: header ---")
check("subtext_accent is present", bool(cfg["swipe"].get("subtext_accent")))
check("accent is a fragment of the line",
      cfg["swipe"]["subtext_accent"] in cfg["swipe"]["subtext"],
      "%r not in %r" % (cfg["swipe"].get("subtext_accent"),
                        cfg["swipe"]["subtext"]))
check("accent names the saving",
      cfg["swipe"]["subtext_accent"] == "$4,000+",
      cfg["swipe"].get("subtext_accent"))
# The kicker copy stays in the config on purpose: engine.js and this file are
# cached separately, and an engine from before this deploy still writes it.
check("headline retained for a stale engine", "headline" in cfg["swipe"])
funnel_html = open(os.path.join(ROOT, "static/funnel.html")).read()
check("kicker node is gone from the shell",
      "swipe-headline" not in funnel_html)
home_html = open(os.path.join(ROOT, "static/pages/home.html")).read()
check("home preview drops the kicker", "mini-kicker" not in home_html)
# The saving is a claim about a renovation. It left the hero when the hero
# stopped being the renovation, and it is on the card that sells one.
check("the saving is on the kitchen card, not over the hero question",
      "mini-money" not in home_html
      and "$4,000+</strong> saved on your\n          renovation" in home_html)

print("\n--- phase 6: floor grid6 ---")
floor = by_step["floor"]
check("floor is grid6", floor["format"] == "grid6", floor["format"])
check("floor is no longer adaptive", "adaptive" not in floor)
check("floor is one pair of six", len(floor["pairs"]) == 1
      and len(floor["pairs"][0]["images"]) == 6)
check("floor is f6a-f6f",
      [i["id"] for i in floor["pairs"][0]["images"]]
      == ["f6a", "f6b", "f6c", "f6d", "f6e", "f6f"])
check("floor labels",
      [i["label"] for i in floor["pairs"][0]["images"]]
      == ["Herringbone oak", "Smoked plank", "Raw concrete", "Gallery stone",
          "Terracotta warmth", "Slate drama"])
# Measured frame luminance, as a single grid rather than as three pairs.
FRAME_L = {"f6a": 118, "f6b": 90, "f6c": 140, "f6d": 190, "f6e": 83, "f6f": 83}
for item in floor["pairs"][0]["images"]:
    tags = item["tags"]
    lum = FRAME_L[item["id"]]
    bad = ("dark" in tags and lum > 130) or ("bright" in tags and lum < 100)
    check("  %-4s tone tag survives the six-up (L=%d)" % (item["id"], lum),
          not bad, str(tags))
check("no two floor options share a tag triple",
      len({tuple(sorted(i["tags"])) for i in floor["pairs"][0]["images"]}) == 6)

print("\n--- phase 6: interstitial working row ---")
working = cfg.get("interstitial_working") or []
check("working copy is configured", len(working) >= 2, str(len(working)))
check("working copy is all strings",
      all(isinstance(w, str) and w for w in working))

print("\n--- phase 6: mistakes emphasis ---")
teaser = (cfg.get("result") or {}).get("mistakes_teaser") or ""
check("teaser exists", bool(teaser))
check("teaser is templated on the style", "{style}" in teaser, teaser)
check("teaser now counts from the free one",
      "mistake #1" in teaser and "other four" in teaser, teaser)
check("teaser names the cost", "$4,000+" in teaser, teaser)
hero = (cfg.get("checkout") or {}).get("manifest_hero") or ""
check("manifest hero is configured", bool(hero))
hits = [r for r in cfg["checkout"]["manifest"] if hero.lower() in r.lower()]
check("manifest hero matches exactly one row", len(hits) == 1, str(hits))
check("the row it matches is the mistakes row",
      hits and "mistakes" in hits[0].lower(), str(hits))

print("\n--- phase 6: element specs ---")
check("every element carries a spec",
      all(e.get("spec") for e in items),
      str([e["id"] for e in items if not e.get("spec")]))
check("specs are one line each",
      all("\n" not in e["spec"] and len(e["spec"]) < 60 for e in items))
check("specs are unique", len({e["spec"] for e in items}) == len(items))

print("\n--- phase 6: report ordering + paid elements ---")
sections = [s for s in cfg["report"]["sections"] if s.get("enabled") is not False]
check("palette is the configured opening", sections[0]["id"] == "palette",
      sections[0]["id"])
check("palette is the only visible section",
      [s["id"] for s in sections
       if (s.get("reveal") or {}).get("mode") == "visible"] == ["palette"])
specs = reports._element_specs(cfg, choices, scores)
check("server can build element specs", len(specs) == 6, str(specs))
check("each spec line is label + spec",
      all(" — " in line for line in specs), str(specs))
mat_prompt = reports._section_prompt(cfg["styles"][0], "Modern Rustic", scores,
                                     "materials", cfg=cfg, choices=choices)
check("materials prompt REQUIRES every element",
      "REQUIRED" in mat_prompt and "must appear in this section by name"
      in mat_prompt)
for line in specs:
    check("  materials prompt carries %r" % line[:28],
          line in mat_prompt)
other = reports._section_prompt(cfg["styles"][0], "Modern Rustic", scores,
                                "mistakes", cfg=cfg, choices=choices)
check("mistakes carries a REQUIRED block of its own", "REQUIRED" in other)
check("  and it is the free mistake, verbatim",
      all(reports._mistake_one(cfg["styles"][0])[f] in other
          for f in ("title", "body", "fix")))
for sid in ("shopping", "dna", "splurge", "palette"):
    check("  nothing REQUIRED on %s" % sid,
          "REQUIRED" not in reports._section_prompt(
              cfg["styles"][0], "Modern Rustic", scores, sid,
              cfg=cfg, choices=choices))

picked = reports._pick_elements(cfg, choices, scores)
assembled = reports._assemble(cfg, "kitchen", "modern_rustic", "Modern Rustic",
                              {}, {}, False, [p["id"] for p in picked])
check("assembled content carries element ids",
      assembled.get("elements") == [p["id"] for p in picked],
      str(assembled.get("elements")))
check("assembled elements are real element ids",
      set(assembled["elements"]) <= {e["id"] for e in items})
bare = reports._assemble(cfg, "kitchen", "modern_rustic", "Modern Rustic",
                         {}, {}, False, [])
check("no elements key when there are none", "elements" not in bare)

print("\n--- phase 6: email + pdf ---")
check("price is read from the funnel's own pricing",
      reports._price_paid({"funnel": "kitchen"}) == "$3",
      str(reports._price_paid({"funnel": "kitchen"})))
check("unknown funnel yields no price",
      reports._price_paid({"funnel": "nope"}) is None)
check("opening drops the number when the price is unknown",
      "spent" not in reports._email_opening({"funnel": "nope"}),
      reports._email_opening({"funnel": "nope"}))
check("opening names the price when it is known",
      "$3" in reports._email_opening({"funnel": "kitchen"}))
check("email template has a logo slot", "%(logo)s" in reports.EMAIL_HTML)
check("email template has a mazzin.com footer",
      "mazzin.com" in reports.EMAIL_HTML)
check("pdf css footers every page",
      'content: "mazzin.com"' in reports.PDF_CSS)
check("pdf cover carries the wordmark",
      "brand/logo.svg" in reports._pdf_html({"style_name": "X",
                                             "sections": []}))

print("\n--- single-page checkout config ---")
co = cfg["checkout"]
check("single_page flag present", "single_page" in co)
check("single_page defaults on", co["single_page"] is True, co.get("single_page"))
com = co.get("commerce") or {}
check("commerce copy block present", bool(com))
for key in ("anchor_head", "anchor_head_accent", "price_suffix",
            "consent", "trust", "mid_line", "mid_line_accent", "mid_button",
            "sticky_label", "sample_link", "sample_caption"):
    check("  commerce.%s" % key, bool(com.get(key)), repr(com.get(key)))
check("anchor headline carries the saving",
      "$4,000+" in com["anchor_head"], com["anchor_head"])
check("its accent is a fragment of it",
      com["anchor_head_accent"] in com["anchor_head"],
      "%r not in %r" % (com["anchor_head_accent"], com["anchor_head"]))
check("anchor head is priced from config, not written in",
      "{price}" in com["anchor_head"], com["anchor_head"])
# The headline is the block's header now. A support line under it was a
# second claim competing with the one the reader is meant to act on, so the
# single-page block does without it — the two-screen paywall keeps its own.
check("the single-page block has no support line", "anchor" not in com, com.get("anchor"))
check("the two-screen paywall still has one",
      "$4,000+" in co["anchor"] and "undo" in co["anchor"], co["anchor"])
check("and its headline still carries the $20,000 framing",
      "$20,000" in co["anchor_head"], co["anchor_head"])
check("price row says one-time and no subscription",
      "one-time" in com["price_suffix"] and "no subscription" in com["price_suffix"],
      com["price_suffix"])
check("consent is priced from config",
      "{price}" in com["consent"], com["consent"])
check("consent promises no subscription and instant unlock",
      "no subscription" in com["consent"] and "instantly" in com["consent"],
      com["consent"])
check("three trust rows", len(com["trust"]) == 3, com["trust"])
check("trust names Stripe, no recurring, and the PDF",
      "Stripe" in com["trust"][0] and "recurring" in com["trust"][1]
      and "PDF" in com["trust"][2], com["trust"])
check("mid line carries the saving", "$4,000+" in com["mid_line"], com["mid_line"])
check("mid accent is a fragment of it",
      com["mid_line_accent"] in com["mid_line"], com["mid_line"])
check("sticky label is priced from config",
      "{price}" in com["sticky_label"], com["sticky_label"])
check("two-screen copy is still intact for the flag-off path",
      all(co.get(k) for k in ("kicker", "title", "anchor_head", "anchor",
                              "reframe", "price_suffix", "trust",
                              "eu_withdrawal_text", "cta_label")))
check("the old value banner still exists for the flag-off path",
      bool((cfg.get("result") or {}).get("value_banner")))

print("\n--- the value boundary ---")
import re as _re
raw = open(os.path.join(ROOT, "funnels/kitchen.json")).read()
gated = []
for st in cfg["styles"]:
    colours = st["reveals"]["palette"]["colors"]
    check("  %-14s palette carries rgb, never hex" % st["id"],
          all("hex" not in c and isinstance(c.get("rgb"), list)
              and len(c["rgb"]) == 3
              and all(isinstance(v, int) and 0 <= v <= 255 for v in c["rgb"])
              for c in colours), colours)
    check("  %-14s every colour is still named" % st["id"],
          all(c.get("name") for c in colours))
    for c in colours:
        r, g, b = c["rgb"]
        gated += ["#%02X%02X%02X" % (r, g, b), "#%02x%02x%02x" % (r, g, b)]
hits = [h for h in gated if h in raw]
check("no gated paint code survives anywhere in the config", not hits, hits[:3])
# Derived from the config rather than written in. The palette moved from
# three colours to five and this still expected the old first one, which is a
# test failing for the only reason a test should not: the thing it describes
# changed somewhere else and it was never told.
#
# Still real work, not a restatement of the function. The value has to be the
# uppercase form of that triple, and it has to be one of the codes collected
# above as gated — the server reading back exactly what the browser is denied
# is the whole point of the function existing.
_first = cfg["styles"][0]["reveals"]["palette"]["colors"][0]
_want = "#%02X%02X%02X" % tuple(_first["rgb"])
_got = reports._config_hex(_first)
check("the server can still read a code back", _got == _want, (_got, _want))
check("  and it is exactly a code the browser is denied",
      _got in gated, _got)
check("and it tells the model the reader has NOT been given them",
      "have NOT been given these codes"
      in reports._style_block(cfg["styles"][0], "Modern Rustic"))

print("\n--- mistake #1, free and whole ---")
for st in cfg["styles"]:
    one = reports._mistake_one(st)
    check("  %-14s has a first mistake" % st["id"], one is not None)
    check("  %-14s title, why and fix are all substantial" % st["id"],
          one and len(one["title"]) > 12 and len(one["body"]) > 150
          and len(one["fix"]) > 80,
          one and (len(one["title"]), len(one["body"]), len(one["fix"])))
    tease = st["reveals"]["mistakes"]
    check("  %-14s teaser opens on the other four" % st["id"],
          tease["setup"].startswith("That one is the cheapest"), tease["setup"])
    check("  %-14s teaser trigger is its own" % st["id"],
          bool(tease["trigger"]) and tease["trigger"].endswith(","),
          tease["trigger"])
    check("  %-14s no items list in the free payload" % st["id"],
          "items" not in tease, tease)
triggers = [st["reveals"]["mistakes"]["trigger"] for st in cfg["styles"]]
check("every style's trigger is different", len(set(triggers)) == len(triggers),
      triggers)
check("the stub fallback still honours the promise",
      [i["title"] for i in reports._stub_for(
          "mistakes", "Modern Rustic", cfg["styles"][0])["items"]][0]
      == reports._mistake_one(cfg["styles"][0])["title"])
check("  and stays inside the 4-6 the schema allows",
      4 <= len(reports._stub_for("mistakes", "Modern Rustic",
                                 cfg["styles"][0])["items"]) <= 6)
check("  a stub with no style is unchanged",
      reports._stub_for("mistakes", "X")["items"]
      == reports._fill(reports.STUBS["mistakes"], "X")["items"])
check("  and a section with no stub still has none",
      reports._stub_for("nope", "X") is None)
mo = cfg["report"]["mistake_one"]
check("the card is titled and numbered", mo["title"] == "Mistake #1 of 5", mo)
check("and says where 2-5 are",
      "2" in mo["locked_note"] and "5" in mo["locked_note"], mo)

print("\n--- the collapsed card ---")
also = cfg["report"]["also"]
ids = {s["id"] for s in cfg["report"]["sections"] if s.get("enabled") is not False}
check("titled", also["title"] == "Also in your report", also["title"])
check("four rows", len(also["rows"]) == 4, len(also["rows"]))
named = [r["section"] for r in also["rows"] if "section" in r]
check("it collapses materials, dna and splurge",
      named == ["materials", "dna", "splurge"], named)
check("every named section is a real one", all(n in ids for n in named), named)
check("mistakes and shopping keep their own blocks",
      "mistakes" not in named and "shopping" not in named, named)
own = [r["title"] for r in also["rows"] if "title" in r]
check("and one row is the paint codes", own == ["Your Exact Paint Codes"], own)
check("every row has a one-line hook",
      all(r.get("hook") and 40 < len(r["hook"]) <= 110 for r in also["rows"]),
      [len(r.get("hook") or "") for r in also["rows"]])
check("no hook invents a number",
      not any(_re.search(r"\d", r["hook"]) for r in also["rows"]),
      [r["hook"] for r in also["rows"] if _re.search(r"\d", r["hook"])])

print("\n--- the report's photographs ---")
vis = cfg["report"]["visuals"]
by_step = {st["id"]: [i["id"] for pr in st.get("pairs", []) for i in pr["images"]]
           for st in steps}
check("the moodboard step is a real step",
      vis["moodboard_step"] in by_step, vis["moodboard_step"])
check("it is the one that carries colour families",
      all(i.get("color_family")
          for pr in next(st for st in steps if st["id"] == vis["moodboard_step"])["pairs"]
          for i in pr["images"]))
check("two material steps, both real",
      len(vis["material_steps"]) == 2
      and all(m in by_step for m in vis["material_steps"]),
      vis["material_steps"])
check("every style has a default set",
      set(vis["defaults"]) == {st["id"] for st in cfg["styles"]},
      sorted(vis["defaults"]))
for sid, d in vis["defaults"].items():
    check("  %-14s board is on the colour step" % sid,
          d["moodboard"] in by_step[vis["moodboard_step"]], d["moodboard"])
    check("  %-14s surfaces are on their own steps" % sid,
          len(d["materials"]) == 2
          and all(d["materials"][i] in by_step[vis["material_steps"][i]]
                  for i in (0, 1)), d["materials"])
boards = [d["moodboard"] for d in vis["defaults"].values()]
check("no two styles open on the same board", len(set(boards)) == len(boards),
      boards)

check("the resolver prefers what they chose",
      reports._visuals(cfg, "industrial", ["mp1", "c4a", "b8b"])
      == {"moodboard": "mp1", "materials": ["c4a", "b8b"]})
check("  falls back to the style where they did not",
      reports._visuals(cfg, "classic", [])
      == {"moodboard": "mp2", "materials": ["c4a", "b8b"]})
check("  and returns nothing for a style it does not know",
      reports._visuals(cfg, "nope", []) is None)
check("visuals ride along in the stored content",
      reports._assemble(cfg, "kitchen", "classic", "Classic", {}, {}, False,
                        None, {"moodboard": "mp2"}).get("visuals")
      == {"moodboard": "mp2"})
check("  and are simply absent when there are none",
      "visuals" not in reports._assemble(cfg, "kitchen", "classic", "Classic",
                                         {}, {}, False))

print("\n--- print variants for the PDF ---")
need = set()
for sid, d in vis["defaults"].items():
    need.update([d["moodboard"]] + d["materials"])
need.update(by_step[vis["moodboard_step"]])
for m in vis["material_steps"]:
    need.update(by_step[m])
missing = [i for i in sorted(need)
           if not os.path.isfile(os.path.join(ROOT, "static/img/print",
                                              i + ".jpg"))]
check("every image the report can draw has a print copy", not missing, missing)
big = []
for i in sorted(need):
    path = os.path.join(ROOT, "static/img/print", i + ".jpg")
    if os.path.isfile(path) and os.path.getsize(path) > 60 * 1024:
        big.append((i, os.path.getsize(path) // 1024))
check("  and none of them is heavy enough to bloat a PDF", not big, big)
check("  the PDF points at them rather than the originals",
      reports._print_src("mp5", {"img": "/static/galleries/kitchen/mp5.webp"})
      == "img/print/mp5.jpg")
check("  falling back to the original when one is absent",
      reports._print_src("nope", {"img": "/static/galleries/kitchen/x.webp"})
      == "galleries/kitchen/x.webp")

print("\n--- the sample page ---")
sample = os.path.join(ROOT, "static/img/sample_page.png")
check("the asset exists", os.path.isfile(sample), sample)
from PIL import Image as _Image
with _Image.open(sample) as _im:
    check("it is a PNG", _im.format == "PNG", _im.format)
    # Twice the 420px box the lightbox draws it in — retina-exact, and no
    # wider, because a PNG of two photographs does not compress with width.
    check("840px, twice the width the lightbox draws it at",
          _im.size[0] == 840, str(_im.size))
check("under half a megabyte", os.path.getsize(sample) < 512 * 1024,
      "%d KB" % (os.path.getsize(sample) // 1024))
check("the link and caption are config copy",
      com["sample_link"] == "See a sample page"
      and "example" in com["sample_caption"].lower(),
      (com["sample_link"], com["sample_caption"]))

print("\n--- the visualizer prompt: mood is not exposure ---")
# Fourteen real renders came back a mean brightness of 86 against source
# photos at 121 — systematically a third darker than the kitchen the reader
# photographed, and the worst of them near-black and unviewable. The cause is
# that an image model reads a word describing a SURFACE as a word describing
# the LIGHT: "dark timber" is a plank, and it was being rendered as a dim room.
#
# The same mistake had already been made once in the gallery generation
# prompts, so this is a test and not a memory. Every string this funnel feeds
# into the edit instruction is checked for the vocabulary that turns a dark
# kitchen into a dark photograph.
EXPOSURE_WORDS = (
    "dark", "darkly", "dim", "dimly", "moody", "moodily", "shadow",
    "shadowed", "shadowy", "low-key", "lowkey", "dramatic", "dramatically",
    "intimate", "candlelit", "candlelight", "atmospheric", "gloomy", "murky",
    "sombre", "somber", "night", "nighttime", "dusk", "twilight", "unlit",
    "underexposed", "silhouette", "noir", "smoky", "hazy",
)

VIZCFG = json.load(open(os.path.join(ROOT, "funnels/kitchen-visualizer.json")))
VIZ = VIZCFG["visualizer"]
_slots = VIZ.get("prompt_slots") or {}


def _has_exposure_word(text):
    """The exposure words in one string, matched on word boundaries.

    Boundaries and not substrings: "dark" is the word, "Denmark" is not, and a
    check that fires on the second is a check somebody switches off.
    """
    low = str(text or "").lower()
    return [w for w in EXPOSURE_WORDS
            if _re.search(r"(?<![a-z])%s(?![a-z])" % _re.escape(w), low)]


# Everything that is interpolated into the template. The template's own text is
# not in this list on purpose: it is where the negatives live, and it says
# "NOT dim, dimly lit, moody" deliberately.
carried = []
for st in VIZCFG["styles"]:
    carried.append(("styles[%s].name" % st["id"], st["name"]))
for key, rule in sorted(_slots.items()):
    carried.append(("prompt_slots.%s.fallback" % key, rule.get("fallback")))
    tag = rule.get("tag")
    for item in VIZCFG["style_elements"]["items"]:
        if tag and tag in (item.get("tags") or []):
            # `_slot_words` puts the LABEL in the prompt, never the spec.
            carried.append(("style_elements[%s].label -> {%s}"
                            % (item["id"], key), item.get("label")))

for where, text in carried:
    hits = _has_exposure_word(text)
    check("  %-46s clean" % where, not hits, (text, hits))

tpl = VIZ.get("prompt_template") or ""
check("the template states the exposure requirement",
      "BRIGHTLY" in tpl and "EVENLY" in tpl, tpl[:60])
check("  unconditionally, for every style and palette",
      "without exception" in tpl and "whatever the style" in tpl)
check("  and separates surface from light in as many words",
      "describe the SURFACES" in tpl and "never the exposure" in tpl)
for neg in ("NOT low-key", "NOT dim", "NO crushed blacks",
            "NO heavy vignette"):
    check("  negative present: %-20s" % neg, neg in tpl, tpl[-400:])
check("the floor is named among the surfaces that change",
      "FLOOR" in tpl and "Replace the floor" in tpl)
check("  and the source floor is refused explicitly",
      "do not carry the original flooring through" in tpl.lower(), tpl[:200])
check("the geometry that must not change is still listed",
      all(w in tpl for w in ("KEEP unchanged", "camera angle", "perspective",
                             "window and door positions")))
# Every slot the template uses is one build_prompt can actually fill.
_used = set(_re.findall(r"\{([a-z_]+)\}", tpl))
_fillable = {"style", "dominant", "dominant_hex", "secondary", "accent",
             "secondary_hex", "accent_hex"} | set(_slots)
check("no placeholder in the template goes unanswered",
      _used <= _fillable, str(sorted(_used - _fillable)))

print("\n--- tracking: the interaction map ---")
for name in ("mid_cta", "sticky_cta", "paywall_view", "paywall_open",
             "pay_tap", "pay_ready", "checkout_error", "result_view"):
    check("  %-15s allowed" % name, name in tracking.ALLOWED_EVENTS)
check("purchase is still not client-assertable",
      "purchase" not in tracking.ALLOWED_EVENTS)
# Every member of the closed set, read from the set rather than typed out
# here. A value added to tracking.py and to nothing else would otherwise be a
# category that validates and is never sent.
for src_ in sorted(tracking.PAYWALL_VIEW_SRC):
    check("  paywall_view src=%-10s accepted" % src_,
          tracking._clean_extra("kitchen", "paywall_view", {"src": src_})
          == {"src": src_})
for bad in ({"src": "elsewhere"}, {"src": 1}, {}, {"src": "scroll", "x": 1}):
    try:
        tracking._clean_extra("kitchen", "paywall_view", bad)
        check("  paywall_view rejects %s" % json.dumps(bad), False)
    except ValueError:
        check("  paywall_view rejects %s" % json.dumps(bad), True)
try:
    tracking._clean_extra("kitchen", "mid_cta", {"src": "scroll"})
    check("a payload on mid_cta is refused", False)
except ValueError:
    check("a payload on mid_cta is refused", True)
check("swipe payloads still validate",
      tracking._clean_extra("kitchen", "swipe",
                            {"pair": "hook:p1", "shown": ["hk1a", "hk1b"],
                             "chosen": "hk1a"})["chosen"] == "hk1a")

print("\n--- what was shown, and what it was shown on ---")
# Twelve sessions uploaded a photo, reached the offer and produced one tap
# between them. `pay_tap` only ever answers for somebody who tapped, so the
# question that costs money — what were the other eleven looking at — had no
# field at all. These two give it one each: `pay_ready.control` is what was on
# screen, and the device on `funnel_start` is what it was on screen on.
for control in sorted(tracking.PAY_READY_CONTROL):
    check("  pay_ready control=%-8s accepted" % control,
          tracking._clean_extra("kitchen", "pay_ready", {"control": control})
          == {"control": control})
for bad in ({"control": "apple_pay"}, {"control": 1}, {}, {"method": "wallet"},
            {"control": "wallet", "x": 1}, None):
    try:
        got = tracking._clean_extra("kitchen", "pay_ready", bad)
        check("  pay_ready rejects %s" % json.dumps(bad), got is None and bad is None,
              got)
    except ValueError:
        check("  pay_ready rejects %s" % json.dumps(bad), True)
check("the two vocabularies match, so the rate is a plain division",
      tracking.PAY_READY_CONTROL == tracking.PAY_TAP_METHOD,
      (tracking.PAY_READY_CONTROL, tracking.PAY_TAP_METHOD))
for ev in ("result_view", "pay_tap", "funnel_start", "viz_upload"):
    try:
        tracking._clean_extra("kitchen", ev, {"control": "wallet"})
        check("  a control payload is refused on %-12s" % ev, False)
    except ValueError:
        check("  a control payload is refused on %-12s" % ev, True)
# The device is server-derived, so a client must not be able to plant it or
# overwrite it. `funnel_start` still takes no client payload at all.
for planted in ({"platform": "ios"}, {"platform": "ios", "browser": "safari"}):
    try:
        tracking._clean_extra("kitchen", "funnel_start", planted)
        check("  a client cannot send %s" % json.dumps(planted), False)
    except ValueError:
        check("  a client cannot send %s" % json.dumps(planted), True)

# Real strings, including the ones the whole exercise is about: the Facebook
# and Instagram in-app browsers claim to be Safari AND Chrome, so anything
# testing for those first files every in-app session as an ordinary browser.
UAS = [
    ("ios", "facebook",
     "Mozilla/5.0 (iPhone; CPU iPhone OS 17_5 like Mac OS X) AppleWebKit/"
     "605.1.15 (KHTML, like Gecko) Mobile/15E148 [FBAN/FBIOS;FBAV/468.0.0.36]"),
    ("android", "facebook",
     "Mozilla/5.0 (Linux; Android 13; SM-G991B) AppleWebKit/537.36 (KHTML, "
     "like Gecko) Chrome/120.0.0.0 Mobile Safari/537.36 [FB_IAB/FB4A;FBAV/452]"),
    ("ios", "instagram",
     "Mozilla/5.0 (iPhone; CPU iPhone OS 17_5 like Mac OS X) AppleWebKit/"
     "605.1.15 (KHTML, like Gecko) Mobile/15E148 Instagram 302.0.0.23.113"),
    ("android", "instagram",
     "Mozilla/5.0 (Linux; Android 13; SM-G991B) AppleWebKit/537.36 (KHTML, "
     "like Gecko) Chrome/120.0.0.0 Mobile Safari/537.36 Instagram 302.0 Android"),
    ("ios", "safari",
     "Mozilla/5.0 (iPhone; CPU iPhone OS 17_5 like Mac OS X) AppleWebKit/"
     "605.1.15 (KHTML, like Gecko) Version/17.5 Mobile/15E148 Safari/604.1"),
    ("ios", "chrome",
     "Mozilla/5.0 (iPhone; CPU iPhone OS 17_5 like Mac OS X) AppleWebKit/"
     "605.1.15 (KHTML, like Gecko) CriOS/126.0 Mobile/15E148 Safari/604.1"),
    ("android", "chrome",
     "Mozilla/5.0 (Linux; Android 14; Pixel 8) AppleWebKit/537.36 (KHTML, "
     "like Gecko) Chrome/126.0.0.0 Mobile Safari/537.36"),
    ("android", "webview",
     "Mozilla/5.0 (Linux; Android 13; SM-A536B Build/TP1A; wv) AppleWebKit/"
     "537.36 (KHTML, like Gecko) Version/4.0 Chrome/120.0 Mobile Safari/537.36"),
    ("android", "samsung",
     "Mozilla/5.0 (Linux; Android 13; SM-S918B) AppleWebKit/537.36 (KHTML, "
     "like Gecko) SamsungBrowser/23.0 Chrome/115.0 Mobile Safari/537.36"),
    ("desktop", "safari",
     "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/605.1.15 "
     "(KHTML, like Gecko) Version/17.5 Safari/605.1.15"),
    ("desktop", "edge",
     "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, "
     "like Gecko) Chrome/126.0.0.0 Safari/537.36 Edg/126.0.0.0"),
    ("desktop", "firefox",
     "Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:127.0) Gecko/20100101 "
     "Firefox/127.0"),
    ("other", "other", "curl/8.4.0"),
    ("other", "other", ""),
    ("other", "other", None),
]
for want_platform, want_browser, ua in UAS:
    got = tracking._device(ua)
    check("  %-9s %-9s from %s" % (want_platform, want_browser,
                                   (ua or "<none>")[:34]),
          got == {"platform": want_platform, "browser": want_browser}, got)
check("every value is inside its closed set",
      all(tracking._device(ua)["platform"] in tracking.UA_PLATFORM
          and tracking._device(ua)["browser"] in tracking.UA_BROWSER
          for _, _, ua in UAS))
check("only the head of the header is ever read",
      tracking._device("Mozilla/5.0 (Linux; Android 13) " + "x" * 40000)
      == {"platform": "android", "browser": "other"})
# What is deliberately not kept. The raw UA is the most fingerprintable string
# in the request and none of it is needed to answer the wallet question.
d = tracking._device(UAS[0][2])
check("the derived value is two keys and no more",
      set(d) == {"platform", "browser"}, sorted(d))
check("  and neither of them is the User-Agent itself",
      not any("Mozilla" in str(v) or "FBAV" in str(v) for v in d.values()), d)

print("\n--- client/allowlist agreement ---")
import re as _re
engine = open(os.path.join(ROOT, "static/js/engine.js")).read()
# Every file that can reach `/api/track`, not only engine.js.
#
# It was engine.js alone until a result module needed an event of its own —
# the persona share button, which fires where the reader actually is rather
# than through a hook back in the engine. The pair of checks below is about
# the allowlist and the client agreeing, and "the client" is now more than one
# file: scanning only the engine would read a module's event as a dead name in
# the allowlist and fail for it.
clients = [engine]
for _name in sorted(os.listdir(os.path.join(ROOT, "static/js"))):
    if _name.startswith("result_") and _name.endswith(".js"):
        clients.append(open(os.path.join(ROOT, "static/js", _name)).read())
emitted = set()
for _src in clients:
    emitted |= set(_re.findall(r'\btrack\("([a-z_]+)"', _src))
check("every emitted event is allowed",
      emitted <= tracking.ALLOWED_EVENTS,
      str(sorted(emitted - tracking.ALLOWED_EVENTS)))
check("every allowed event is emitted",
      tracking.ALLOWED_EVENTS <= emitted,
      str(sorted(tracking.ALLOWED_EVENTS - emitted)))
check("  and the scan read more than the engine",
      len(clients) > 1, str(len(clients)))
check("paywall_view is the only event sent with a payload",
      len(_re.findall(r'track\("paywall_view", null, \{ src:', engine)) == 1)
# The src field, both directions, the same way the event names are checked
# above. `paywall_view` is grouped by this value, so a word in one file and not
# the other is either a bucket nobody fills or a payload the server refuses.
sent = set(_re.findall(r'payIntent = "([a-z_]+)"', engine))
check("every src engine.js sends is in the closed set",
      sent <= tracking.PAYWALL_VIEW_SRC,
      str(sorted(sent - tracking.PAYWALL_VIEW_SRC)))
check("every src in the closed set is sent by engine.js",
      tracking.PAYWALL_VIEW_SRC <= sent,
      str(sorted(tracking.PAYWALL_VIEW_SRC - sent)))
shell = open(os.path.join(ROOT, "static/funnel.html")).read()
for node in ("commerce", "sticky-cta", "withdrawal", "legal-links"):
    check("  shell declares #%s" % node, 'id="%s"' % node in shell)
check("the paywall screen is still in the shell for the flag-off path",
      'id="screen-paywall"' in shell)

from app import app  # noqa: E402
rules = sorted(str(r) for r in app.url_map.iter_rules())
check("routes intact", "/api/track" in rules and "/api/checkout" in rules
      and "/<slug>" in rules, str(rules))

print("\n%d checks, %d failed" % (checks[0], len(fails)))
for f in fails:
    print("  FAIL " + f)
sys.exit(1 if fails else 0)
