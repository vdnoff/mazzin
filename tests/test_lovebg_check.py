#!/usr/bin/env python3
"""Integrity checks over funnels/love-zodiac-bg.json — the Bulgarian love vertical.

test_zodiacbg_check.py asserts that /zodiac-bg is zodiac30's walk with the
strings translated. This asserts a different thing about /love-zodiac-bg: it
is zodiac-bg's MACHINERY — the same archetype ids, the same tag axes, the same
result module and stylesheet, the same key set in every block, the same
rarity table, the same sign grid card for card — carrying an all-new walk and
all-new copy. So the shape is compared against zodiac-bg key for key, and the
content is checked on its own account: the tag map really is balanced and
every archetype is reachable, the copy really is Bulgarian in Cyrillic, the
cross lines really are the love angle, and it stays inside the same Terms line
zodiac-bg is held to.

The report phase has landed: reports.LOVE_BG_PROFILE is registered under the
slug and its twin, the funnel transacts live, and the checks that waited for
the profile run here — the page's labels are the profile's constants, the
compatibility table is keyed on the grid's twelve labels, the mail and the
PDF are this product's Bulgarian, the profile's own strings pass its own
banned list, and every string on the model's path keeps the guillemet rule.

No database, no network, no key. Everything is read off disk.
"""
import json
import os
import re
import sys

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

sys.path.insert(0, REPO)
ROOT = REPO

fails = []
checks = [0]
notes = []


def check(label, ok, detail=""):
    checks[0] += 1
    if not ok:
        fails.append("%s %s" % (label, detail))
    print("  %-58s %s%s" % (label, "ok" if ok else "FAIL",
                            ("  " + str(detail)) if detail and not ok else ""))


JS = os.path.join(ROOT, "static", "js")
ENGINE_JS = open(os.path.join(JS, "engine.js"), encoding="utf-8").read()
RESULT_JS = open(os.path.join(JS, "result_zodiac.js"),
                 encoding="utf-8").read()

import reports                                             # noqa: E402
import payments                                            # noqa: E402
import config                                              # noqa: E402

SLUG = "love-zodiac-bg"
PATH = os.path.join(ROOT, "funnels", SLUG + ".json")
RAW = open(PATH, encoding="utf-8").read()
cfg = json.loads(RAW)
static_cfg = json.load(open(os.path.join(ROOT, "static/funnels",
                                         SLUG + ".json"), encoding="utf-8"))
zbg = json.load(open(os.path.join(ROOT, "funnels/zodiac-bg.json"),
                     encoding="utf-8"))
ZBG_RAW = open(os.path.join(ROOT, "funnels/zodiac-bg.json"),
               encoding="utf-8").read()

steps = cfg["swipe"]["steps"]
by_step = {s["id"]: s for s in steps}
images = [i for s in steps for p in s["pairs"] for i in p["images"]]
by_id = {i["id"]: i for i in images}
GALLERY = "/static/galleries/love-zodiac-bg/"
love_images = [i for i in images if i["img"].startswith(GALLERY)]
sign_images = by_step["sign"]["pairs"][0]["images"]

profile = reports.LOVE_BG_PROFILE


def leaves(node, path=""):
    """Every string in the config, with the path it sits at."""
    if isinstance(node, dict):
        for key, value in node.items():
            for item in leaves(value, path + "/" + key):
                yield item
    elif isinstance(node, list):
        for index, value in enumerate(node):
            for item in leaves(value, "%s/%d" % (path, index)):
                yield item
    elif isinstance(node, str):
        yield path, node


STRINGS = list(leaves(cfg))
ZBG_STRINGS = dict(leaves(zbg))

print("\n--- config shape ---")
check("static copy matches funnels/", cfg == static_cfg)
check("slug is love-zodiac-bg", cfg["slug"] == SLUG, cfg["slug"])
check("funnel_id is love_zodiac_bg_v1",
      cfg["funnel_id"] == "love_zodiac_bg_v1", cfg["funnel_id"])
check("locale is bg", cfg["locale"] == "bg", cfg["locale"])
check("pairs_count == number of steps == 20",
      cfg["swipe"]["pairs_count"] == len(steps) == 20,
      "%s vs %s" % (cfg["swipe"]["pairs_count"], len(steps)))
check("the theme, the module and the sheet are zodiac-bg's",
      all(cfg[k] == zbg[k] for k in ("theme", "result_module", "result_css")),
      str([k for k in ("theme", "result_module", "result_css")
           if cfg[k] != zbg[k]]))
check("it names the minimal layout outright",
      cfg.get("result_template") == "minimal", str(cfg.get("result_template")))
check("  and runs no layout experiment",
      "paywall_variants" not in cfg, str(cfg.get("paywall_variants")))

print("\n--- live: complete, reachable, sold ---")
# The report phase is what flipped this. While the slug fell through to the
# kitchen profile a real purchase would have delivered the wrong document,
# and the Stripe mode was what kept a real card out; now a purchase delivers
# this product's own report, and the funnel transacts on the live keys.
check("it transacts on live keys", cfg["stripe_mode"] == "live",
      cfg["stripe_mode"])
check("  which is the field payments.py reads, per request",
      payments._stripe_mode(cfg) == payments.LIVE
      and payments.effective_mode.__code__.co_argcount == 2)
check("  and zodiac-bg is still live", zbg["stripe_mode"] == "live")
home = open(os.path.join(ROOT, "static/pages/home.html"),
            encoding="utf-8").read()
check("the homepage does not link it yet",
      'href="/%s"' % SLUG not in home and SLUG not in home)
check("the report profile is registered under the slug and its twin",
      reports.PROFILES.get(SLUG) is profile
      and reports.PROFILES.get(SLUG + "-test") is profile
      and reports._profile(SLUG) is profile
      and reports._profile(SLUG + "-test") is profile)
check("  it is a zodiac profile, so every zodiac branch takes it",
      reports._is_zodiac(profile))
check("  and a distinct object, not a share of zodiac-bg's",
      profile is not reports.ZODIAC_BG_PROFILE
      and reports._profile("zodiac-bg") is reports.ZODIAC_BG_PROFILE)

print("\n--- it is zodiac-bg's machinery, key for key ---")


def shape(node):
    """The config with every string replaced by its type."""
    if isinstance(node, dict):
        return dict((k, shape(v)) for k, v in node.items())
    if isinstance(node, list):
        return [shape(v) for v in node]
    if isinstance(node, str):
        return "str"
    if isinstance(node, bool) or node is None:
        return node
    return "num" if isinstance(node, (int, float)) else node


check("the top-level keys are zodiac-bg's, less the layout split",
      set(cfg) == set(zbg) - {"paywall_variants"},
      str(sorted(set(cfg) ^ (set(zbg) - {"paywall_variants"}))))
for block in ("meta", "checkout", "report", "result", "result_copy",
              "pricing", "sale", "analyzing", "style_elements"):
    check("  %-14s carries the same keys" % block,
          set(cfg[block]) == set(zbg[block]),
          str(sorted(set(cfg[block]) ^ set(zbg[block]))))
check("  swipe carries the same keys",
      set(cfg["swipe"]) == set(zbg["swipe"]),
      str(sorted(set(cfg["swipe"]) ^ set(zbg["swipe"]))))
check("  checkout.commerce too",
      set(cfg["checkout"]["commerce"]) == set(zbg["checkout"]["commerce"]))
check("  and result_copy.profile, labels and boxes",
      all(set(cfg["result_copy"][k]) == set(zbg["result_copy"][k])
          for k in ("profile", "labels", "boxes", "purpose_map")),
      str([k for k in ("profile", "labels", "boxes", "purpose_map")
           if set(cfg["result_copy"][k]) != set(zbg["result_copy"][k])]))
check("checkout and report have zodiac-bg's shape exactly",
      shape(cfg["checkout"]) == shape(zbg["checkout"])
      and shape(cfg["report"]["sections"]) == shape(zbg["report"]["sections"])
      and shape(cfg["report"]["also"]) == shape(zbg["report"]["also"]))
check("the same four archetype ids and tags, in order",
      [(s["id"], s["tags"]) for s in cfg["styles"]]
      == [(s["id"], s["tags"]) for s in zbg["styles"]])
check("  each with the same reveals shape",
      all(shape(m["reveals"]) == shape(t["reveals"])
          for m, t in zip(cfg["styles"], zbg["styles"])))
check("  and named for love, not the zodiac names",
      [s["name"] for s in cfg["styles"]]
      == ["Открит пламък", "Дълбоко течение", "Тихо пристанище",
          "Танцуващ въздух"],
      str([s["name"] for s in cfg["styles"]]))
check("the report sections keep zodiac-bg's ids, order and reveal modes",
      [(s["id"], s.get("enabled"), s["reveal"]["mode"])
       for s in cfg["report"]["sections"]]
      == [(s["id"], s.get("enabled"), s["reveal"]["mode"])
          for s in zbg["report"]["sections"]])
check("the rarity table is zodiac-bg's, number for number",
      cfg["result_copy"]["profile"]["rarity"]
      == zbg["result_copy"]["profile"]["rarity"])
check("the purpose map keys the same tags at the same sections",
      {k: v["emphasized_section"]
       for k, v in cfg["result_copy"]["purpose_map"].items()}
      == {k: v["emphasized_section"]
          for k, v in zbg["result_copy"]["purpose_map"].items()})
check("the cards, the unlock rows and the scales keep their ids",
      [c["id"] for c in cfg["result_copy"]["profile"]["cards"]]
      == [c["id"] for c in zbg["result_copy"]["profile"]["cards"]]
      and [r["id"] for r in cfg["result_copy"]["profile"]["unlock"]]
      == [r["id"] for r in zbg["result_copy"]["profile"]["unlock"]]
      and [s["id"] for s in cfg["result_copy"]["profile"]["scales"]]
      == [s["id"] for s in zbg["result_copy"]["profile"]["scales"]])
check("  and the same glyphs, which the module draws",
      [c["icon"] for c in cfg["result_copy"]["profile"]["cards"]]
      == [c["icon"] for c in zbg["result_copy"]["profile"]["cards"]]
      and all(('%s: [' % t["icon"]) in RESULT_JS
              for t in cfg["result_copy"]["boxes"]["boxes"]))
check("the subtype table has the same 4x3x2 shape",
      shape(cfg["result_copy"]["profile"]["subtypes"])
      == shape(zbg["result_copy"]["profile"]["subtypes"]))
check("hook slots and visuals name steps this walk has",
      all(v["step"] in by_step for v in cfg["report"]["hook_slots"].values())
      and all(v in by_step for v in
              cfg["report"]["visuals"]["section_steps"].values())
      and all(v in by_step for v in cfg["report"]["visuals"]["hero"].values())
      and cfg["result_copy"]["boxes"]["hero_step"] in by_step,
      str(cfg["report"]["hook_slots"]))
check("  the sign slot still reads the sign step, as engine.js's signWord does",
      cfg["report"]["hook_slots"]["sign"]["step"] == "sign"
      and "hook_slots) || {}).sign" in ENGINE_JS)
check("  and the hero glyph is the sign, as the module draws it",
      cfg["report"]["visuals"]["hero"]["glyph_step"] == "sign"
      and "glyph(ctx.picks.sign)" in RESULT_JS)

print("\n--- the walk: the sign grid, fourteen pairs and four four-ups ---")
LOVE_STEPS = ["spark", "evening", "gesture", "gift", "conflict", "closeness",
              "romance", "rhythm", "distance", "home", "passion", "trust",
              "past", "public", "care", "silence", "future", "symbol"]
check("nineteen steps: the hook pair, the sign, then seventeen pairs",
      [s["id"] for s in steps] == LOVE_STEPS[:1] + ["sign", "gender"] + LOVE_STEPS[1:],
      str([s["id"] for s in steps]))
check("the sign step is zodiac-bg's, card for card",
      by_step["sign"] == next(s for s in zbg["swipe"]["steps"]
                              if s["id"] == "sign"))
check("  twelve signs, in the Bulgarian twelve",
      [i["label"] for i in sign_images]
      == ["Овен", "Телец", "Близнаци", "Рак", "Лъв", "Дева", "Везни",
          "Скорпион", "Стрелец", "Козирог", "Водолей", "Риби"])
check("  pointing at the zodiac gallery, which has them",
      all(i["img"].startswith("/static/galleries/zodiac/")
          and os.path.isfile(os.path.join(ROOT, i["img"].lstrip("/")))
          for i in sign_images))
# The four-choice steps use the grid the engine already draws for four
# cards — `grid4`, the format zodiac-bg's seeking and bond steps sit on and
# engine.js sizes in its GRID_SIZE table. No engine change was needed.
FOURS = ["conflict", "romance", "home", "silence"]
check("four steps are four-ups, on the engine's own grid4",
      [s["id"] for s in steps if s["format"] == "grid4"] == FOURS
      and "grid4: 4" in ENGINE_JS and ".cards.is-grid4" in open(
          os.path.join(ROOT, "static/css/mazzin.css"), encoding="utf-8").read(),
      str([(s["id"], s["format"]) for s in steps if s["format"] != "pair"]))
check("  each with exactly four cards", all(
    len(s["pairs"]) == 1 and len(s["pairs"][0]["images"]) == 4
    for s in steps if s["id"] in FOURS))
check("  and every other step is a pair of two", all(
    s["format"] == "pair" and len(s["pairs"]) == 1
    and len(s["pairs"][0]["images"]) == 2
    for s in steps if s["id"] not in ("sign", "gender") and s["id"] not in FOURS))
WANT_IDS = []
for n, sid in enumerate(LOVE_STEPS, 1):
    for side in ("abcd" if sid in FOURS else "ab"):
        WANT_IDS.append("lv%02d%s" % (n, side))
# The gender step's three sit after the hook pair, where the step does.
WANT_IDS[2:2] = ["g01", "g02", "g03"]
check("the love images are lv01a..lv18d, in walk order, c and d on the fours, "
      "g01..g03 third",
      [i["id"] for i in love_images] == WANT_IDS,
      str([i["id"] for i in love_images][:6]))
check("  forty-seven of them, and nothing else is this funnel's",
      len(love_images) == 47 and len(images) == 59)
NEW_LABELS = {"lv05c": "Споделен смях", "lv05d": "Разходка рамо до рамо",
              "lv07c": "Писмо на възглавницата", "lv07d": "Танц в кухнята",
              "lv10c": "Маса за гости", "lv10d": "Хамак за двама",
              "lv16c": "Книги на дивана", "lv16d": "Залез от колата"}
check("  the eight new cards carry the reviewed labels",
      all(by_id[i]["label"] == v for i, v in NEW_LABELS.items()),
      str({i: by_id[i]["label"] for i in NEW_LABELS
           if by_id[i]["label"] != NEW_LABELS[i]}))
check("  every one under this funnel's own gallery",
      all(i["img"] == GALLERY + i["id"] + ".webp" for i in love_images))
check("  with a label, three colours and a file each",
      all(i.get("label") and len(i.get("colors") or []) == 3
          and os.path.isfile(os.path.join(ROOT, i["img"].lstrip("/")))
          for i in love_images),
      str([i["id"] for i in love_images
           if not os.path.isfile(os.path.join(ROOT, i["img"].lstrip("/")))]))
check("no step shuffles off, pins or inverts except the sign grid",
      all(s.get("shuffle") is None and s.get("pin_first") is None
          and s.get("scoring") is None
          for s in steps if s["id"] not in ("sign", "gender"))
      and by_step["sign"].get("shuffle") is False
      and by_step["gender"].get("shuffle") is False)
check("the og image is this funnel's own, on disk",
      cfg["meta"]["og_image"] == GALLERY + "og.webp"
      and os.path.isfile(os.path.join(ROOT, "static/galleries/love-zodiac-bg",
                                      "og.webp")))
PREVIEW = cfg["preview_gallery"]
check("the preview strip is sixteen frames of this gallery",
      len(PREVIEW) == 16 and all(g["img"].startswith(GALLERY) for g in PREVIEW)
      and all(os.path.isfile(os.path.join(ROOT, g["img"].lstrip("/")))
              for g in PREVIEW),
      str([g["id"] for g in PREVIEW]))
check("  fourteen off the walk, carrying the walk's tags",
      all(g["tags"] == [t for t in by_id[g["id"]]["tags"]
                        if t != "purpose_love"]
          for g in PREVIEW if g["id"] in by_id)
      and sum(g["id"] in by_id for g in PREVIEW) == 14)
# The engine's `confirm` and `almost` screens carry no image slot, so the
# two interstitial frames the brief asked for are shipped in the gallery and
# shown where the engine does show a strip of this funnel's frames.
check("  and the two interstitial frames, which no step carries",
      [g["id"] for g in PREVIEW if g["id"] not in by_id] == ["int1", "int2"])
check("the style-elements strip names frames off the walk",
      all(it["image"] in by_id and it["img"] == by_id[it["image"]]["img"]
          and it["tags"] == [t for t in by_id[it["image"]]["tags"]
                             if t != "purpose_love"]
          for it in cfg["style_elements"]["items"])
      and len(cfg["style_elements"]["items"]) == 11)

print("\n--- the tag map: balanced, and every archetype reachable ---")
ELEMENTS = ("fire", "earth", "air", "water")
ENERGIES = ("sun", "moon")
TONES = ("bold", "calm", "mystic")
# The gender step's three cards score nothing: they carry one gender tag
# each and no axis tag, and are held to that in their own block below.
GENDER_IDS = ("g01", "g02", "g03")
scored = [i for i in love_images if i["id"] not in GENDER_IDS]
check("every scored love image carries one element, one energy and one tone",
      all(sum(t in ELEMENTS for t in i["tags"]) == 1
          and sum(t in ENERGIES for t in i["tags"]) == 1
          and sum(t in TONES for t in i["tags"]) == 1
          for i in scored) and len(scored) == 44,
      str([i["id"] for i in scored
           if sum(t in ELEMENTS for t in i["tags"]) != 1]))
check("  and nothing outside that vocabulary but the one service tag",
      all(set(i["tags"]) <= set(ELEMENTS + ENERGIES + TONES
                                + ("purpose_love",)) for i in scored))
tally = {}
for i in scored:
    for t in i["tags"]:
        tally[t] = tally.get(t, 0) + 1
check("eleven images per element", all(tally[e] == 11 for e in ELEMENTS),
      str({e: tally.get(e) for e in ELEMENTS}))
check("  twenty-two sun, twenty-two moon",
      tally["sun"] == tally["moon"] == 22,
      str({e: tally.get(e) for e in ENERGIES}))
check("  and the three tones within one of each other",
      all(14 <= tally[t] <= 15 for t in TONES) and sum(tally[t] for t in TONES) == 44,
      str({t: tally.get(t) for t in TONES}))
check("every pair contrasts two different elements",
      all(len({t for i in s["pairs"][0]["images"] for t in i["tags"]
               if t in ELEMENTS}) == 2
          for s in steps if s["id"] not in ("sign", "gender") and s["id"] not in FOURS),
      str([s["id"] for s in steps if s["id"] not in ("sign", "gender") and s["id"] not in FOURS
           and len({t for i in s["pairs"][0]["images"] for t in i["tags"]
                    if t in ELEMENTS}) != 2]))
check("  and every four-up offers all four elements",
      all(sorted(t for i in s["pairs"][0]["images"] for t in i["tags"]
                 if t in ELEMENTS) == sorted(ELEMENTS)
          for s in steps if s["id"] in FOURS),
      str([(s["id"], [t for i in s["pairs"][0]["images"] for t in i["tags"]
                      if t in ELEMENTS]) for s in steps if s["id"] in FOURS]))
check("the service tag rides on the hook pair only, and on both cards",
      [i["id"] for i in images if "purpose_love" in i["tags"]]
      == ["lv01a", "lv01b"])
check("  which is a tag the purpose map declares",
      "purpose_love" in cfg["result_copy"]["purpose_map"]
      and "prefixTag(axis" in ENGINE_JS)

# engine.js's own arithmetic: a style's score is the sum of its tags' scores
# over the run, and the highest wins. A reader who taps every card of one
# element, plus that element's own sign, has to land on that archetype and on
# no other — the walk has to be able to say each of its four answers.
SIGN_OF = {"fire": "sign_aries", "earth": "sign_taurus",
           "air": "sign_gemini", "water": "sign_cancer"}
ARCHETYPE_OF = {"fire": "radiant_fire", "water": "deep_water",
                "earth": "grounded_earth", "air": "celestial_air"}


def walk(element):
    picks = []
    for s in steps:
        if s["id"] == "sign":
            picks.append(SIGN_OF[element])
            continue
        cards = s["pairs"][0]["images"]
        picks.append(next((c["id"] for c in cards if element in c["tags"]),
                          cards[0]["id"]))
    scores = {}
    for pid in picks:
        for t in by_id[pid]["tags"]:
            scores[t] = scores.get(t, 0) + 1
    return {st["id"]: sum(scores.get(t, 0) for t in st["tags"])
            for st in cfg["styles"]}


for element in ELEMENTS:
    won = walk(element)
    best = max(won.values())
    check("  an all-%s walk lands on %s, outright" % (element,
                                                     ARCHETYPE_OF[element]),
          won[ARCHETYPE_OF[element]] == best
          and sum(v == best for v in won.values()) == 1, str(won))

# And a reader tapping at random, many times over, with ties broken the way
# engine.js breaks them (first listed). No archetype may be a foregone
# conclusion and none may be out of reach — "roughly equally likely" is a
# band, and the band is wide enough that a tag moved on one card does not
# fail it while a walk tilted toward one element does.
import random                                                  # noqa: E402

rng = random.Random(7)
RUNS = 20000
wins = {st["id"]: 0 for st in cfg["styles"]}
for _ in range(RUNS):
    scores = {}
    for s in steps:
        for t in rng.choice(s["pairs"][0]["images"])["tags"]:
            scores[t] = scores.get(t, 0) + 1
    totals = [(sum(scores.get(t, 0) for t in st["tags"]), st["id"])
              for st in cfg["styles"]]
    best = max(v for v, _i in totals)
    wins[next(i for v, i in totals if v == best)] += 1
share = {k: v / float(RUNS) for k, v in wins.items()}
check("under random taps every archetype wins between 15%% and 35%%",
      all(0.15 <= v <= 0.35 for v in share.values()),
      str({k: round(v, 3) for k, v in share.items()}))
print("    random-walk shares: %s"
      % ", ".join("%s %.1f%%" % (k, v * 100) for k, v in sorted(share.items())))

print("\n--- the interstitials keep zodiac-bg's mechanics ---")
mids = cfg["interstitials"]
check("four beats, at the same four points, one step later each for the "
      "gender step",
      [e["after_step"] for e in mids] == [5, 10, 15, 20],
      str([e["after_step"] for e in mids]))
check("  same templates and dwell times as zodiac-bg",
      [(e["template"], e["auto_advance_ms"]) for e in mids]
      == [(e["template"], e["auto_advance_ms"])
          for e in zbg["interstitials"]])
echoed = [sid for e in mids for sid in e["echo_steps"]]
# The gender step is not a signal about the heart, so no beat echoes it.
check("  every scored step is echoed exactly once, in walk order",
      echoed == [s["id"] for s in steps if s["id"] != "gender"], str(echoed))
check("  the first beat answers the hook pair back, card for card",
      mids[0]["personal"]["step"] == "spark"
      and sorted(mids[0]["personal"]["lines"]) == ["lv01a", "lv01b"])
check("    with the {sign} token in every variant",
      all("{sign}" in r["line"]
          for r in mids[0]["personal"]["lines"].values()))
check("  the second reads the element axis, all four",
      mids[1]["personal"]["axis"] == "element"
      and sorted(mids[1]["personal"]["lines"]) == sorted(ELEMENTS)
      and "{pct}" in mids[1]["line"])
check("  the third answers the trust pair back",
      mids[2]["personal"]["step"] == "trust"
      and sorted(mids[2]["personal"]["lines"]) == ["lv12a", "lv12b"])
check("    and says five taps remain, which after fourteen of nineteen they do",
      "пет" in mids[2]["sub"].lower(), mids[2]["sub"])
check("  every personal variant is written, line and sub",
      all(r.get("line") and r.get("sub")
          for e in mids
          for r in ((e.get("personal") or {}).get("lines") or {}).values()))
check("  and each beat still has its fallback line and CTA",
      all(e.get("kicker") and e.get("line") and e.get("cta") for e in mids))

print("\n--- one price, and every rendering of it comes from that field ---")
check("pricing is 499 eur",
      cfg["pricing"]["amount_cents"] == 499
      and cfg["pricing"]["currency"] == "eur", str(cfg["pricing"]))
check("  written the way Bulgarian writes money",
      cfg["pricing"].get("price_format") == "{amount} €"
      and cfg["pricing"].get("decimal_mark") == ",",
      repr(cfg["pricing"].get("price_format")))
check("    the space in it being a no-break one",
      " " in cfg["pricing"]["price_format"]
      and " " not in cfg["pricing"]["price_format"])
check("    written literally into the file, not as an escape",
      '"price_format": "{amount} €"' in RAW)
check("  integer cents, never a float or a formatted string",
      isinstance(cfg["pricing"]["amount_cents"], int)
      and not isinstance(cfg["pricing"]["amount_cents"], bool))
check("  and zodiac-bg is untouched at 499 eur",
      zbg["pricing"]["amount_cents"] == 499
      and zbg["pricing"]["currency"] == "eur")

PRICEY = re.compile(r"\$\s?\d|\b\d+[.,]\d{2}\b")
spelled = [(p, v) for p, v in STRINGS if PRICEY.search(v)]
check("no string in the config spells a price out", not spelled,
      str(spelled[:4]))
check("  and the raw file names 300 nowhere", "300" not in RAW)
SLOTS = [(p, v) for p, v in STRINGS if "{price}" in v]
check("every line that names a price interpolates {price}, seven of them",
      len(SLOTS) == 7, str(sorted(p for p, _v in SLOTS)))
check("  the same seven slots zodiac-bg fills",
      sorted(p for p, _v in SLOTS)
      == sorted(p for p, v in ZBG_STRINGS.items() if "{price}" in v))


def short(pricing):
    """What engine.js formatPriceShort() prints, mirrored here."""
    cents = pricing["amount_cents"]
    amount = (str(cents // 100) if cents % 100 == 0
              else "%.2f" % (cents / 100.0))
    mark = pricing.get("decimal_mark")
    if mark:
        amount = amount.replace(".", mark)
    shape_ = pricing.get("price_format")
    if shape_:
        return shape_.replace("{amount}", amount)
    cur = (pricing.get("currency") or "usd").upper()
    return {"USD": "$", "EUR": "€", "GBP": "£"}.get(cur, "") + amount


check("  which renders as 4,99 €",
      short(cfg["pricing"]) == "4,99 €", repr(short(cfg["pricing"])))
check("  and the sale price as 1,99 € through the same formatter",
      short(dict(cfg["pricing"], amount_cents=cfg["sale"]["price_cents"]))
      == "1,99 €")
check("    so the no-break space survives into every {price} slot",
      all(" " in v.replace("{price}", short(cfg["pricing"]))
          for _p, v in STRINGS if "{price}" in v))
check("every {price} slot reads with the amount substituted",
      all("{price}" not in v.replace("{price}", short(cfg["pricing"]))
          and "  " not in v.replace("{price}", short(cfg["pricing"]))
          for _p, v in STRINGS if "{price}" in v))
check("the anchor is stated in euros, like everything else on the card",
      "70 €" in cfg["checkout"]["anchor"]
      and "70 €" in cfg["checkout"]["commerce"]["anchor_head"]
      and "70 €" in cfg["checkout"]["commerce"]["price_anchor"])
check("  70 is the only figure the euro lines state outright",
      sorted(set(re.findall(r"\d+", " ".join(
          v for p, v in STRINGS if "€" in v and p != "/pricing/price_format"))))
      == ["70"])
check("no dollar sign survives anywhere in this funnel's copy",
      not [p for p, v in STRINGS if "$" in v])
check("  and no string says usd, ron or lei either",
      not [p for p, v in STRINGS
           if re.search(r"\b(usd|ron|lei)\b", v, re.I)
           and p != "/pricing/currency"])
check("the coffee reframe is two coffees, which both prices are under",
      "две кафета" in cfg["checkout"]["commerce"]["mid_line"]
      and "две кафета" in cfg["checkout"]["reframe"])
check("  and no string claims one coffee",
      not [p for p, v in STRINGS if re.search(r"\bедно кафе\b", v)])
ACCENTS = [("swipe.subtext", cfg["swipe"]["subtext"],
            cfg["swipe"]["subtext_accent"]),
           ("commerce.anchor_head", cfg["checkout"]["commerce"]["anchor_head"],
            cfg["checkout"]["commerce"]["anchor_head_accent"]),
           ("commerce.price_anchor",
            cfg["checkout"]["commerce"]["price_anchor"],
            cfg["checkout"]["commerce"]["price_anchor_accent"]),
           ("commerce.mid_line", cfg["checkout"]["commerce"]["mid_line"],
            cfg["checkout"]["commerce"]["mid_line_accent"])]
for name, full, accent in ACCENTS:
    check("  %-22s contains its accent" % name, accent in full,
          "%r not in %r" % (accent, full))

print("\n--- the tokens the page fills ---")
TOKEN = re.compile(r"\{(\w+)\}")
HOOKS = set(cfg["report"]["hook_slots"])
# What engine.js and result_zodiac.js fill on their own account, whichever
# funnel they serve.
ENGINE_TOKENS = {"price", "style", "n", "label", "pct", "email", "left",
                 "right", "at", "first", "last", "element", "second", "energy",
                 "subtype_bare", "fire", "earth", "air", "water", "works",
                 "avoid", "range", "amount"}
invented = [(p, sorted(set(TOKEN.findall(v)) - HOOKS - ENGINE_TOKENS))
            for p, v in STRINGS]
invented = [(p, t) for p, t in invented if t]
check("no line invents a token nothing fills", not invented,
      str(invented[:4]))
check("  the hook slots are love-native, four of them, and one is the sign",
      sorted(HOOKS) == ["gesture", "gift", "sign", "symbol"], str(sorted(HOOKS)))
check("  every fallback noun is Bulgarian and bare",
      {k: v["fallback"] for k, v in cfg["report"]["hook_slots"].items()}
      == {"sign": "зодия", "gift": "подарък", "gesture": "жест",
          "symbol": "символ"})
check("  and every slot is actually used by a line",
      all(any("{%s}" % k in v for _p, v in STRINGS) for k in HOOKS),
      str([k for k in HOOKS if not any("{%s}" % k in v for _p, v in STRINGS)]))
check("the report block fills hook slots only",
      all(set(TOKEN.findall(v)) <= HOOKS
          for p, v in STRINGS if p.startswith("/report/")),
      str([(p, TOKEN.findall(v)) for p, v in STRINGS
           if p.startswith("/report/") and set(TOKEN.findall(v)) - HOOKS]))
CROSS_PATH = "/result_copy/profile/sign_cross/"
check("  and no cross line fills a token at all",
      not [v for p, v in STRINGS if p.startswith(CROSS_PATH) and TOKEN.search(v)])
check("  the bridge names the subtype and carries no English article slot",
      "{subtype_bare}" in cfg["result_copy"]["profile"]["bridge"]
      and "{subtype_article}" not in cfg["result_copy"]["profile"]["bridge"])
check("  the blueprint card names both halves",
      all(t in cfg["result_copy"]["profile"]["cards"][5]["promise"]
          for t in ("{element}", "{second}")))
check("  and the year card and row span the year",
      "{first}" in cfg["result_copy"]["profile"]["cards"][2]["promise"]
      and "{last}" in cfg["result_copy"]["profile"]["unlock"][2]["line"])
check("the strength lead reads two slots of this walk",
      set(TOKEN.findall(cfg["result_copy"]["strength_lead"]))
      == {"gesture", "symbol"}, cfg["result_copy"]["strength_lead"])

print("\n--- it is actually Bulgarian, in Cyrillic ---")
CYRILLIC = re.compile(r"[Ѐ-ӿ]")
TOKEN_ONLY = re.compile(r"^(?:\{\w+\}|\d+|[\s.,·—–\-+#%€↓→]+)+$")
# Paths whose value is a machine word, not copy.
MACHINE_KEYS = {"id", "img", "image", "icon", "format", "template", "step",
                "label_mode",
                "hex", "section", "emphasized_section", "axis", "mode",
                "manifest_hero", "product_image", "og_image",
                "analyzing_fade_to", "theme", "result_module", "result_css",
                "stripe_mode", "hero_step", "glyph_step", "band_step",
                "scoring", "ends", "price_format", "decimal_mark", "currency",
                "slug", "funnel_id", "locale", "result_template"}


def machine(path):
    parts = path.split("/")
    if parts[-1] in MACHINE_KEYS:
        return True
    if "/colors/" in path or "/tags/" in path or "/echo_steps/" in path:
        return True
    if "/section_steps/" in path:
        return True
    return False


VISIBLE = [(p, v) for p, v in STRINGS if not machine(p)]
check("there is a whole funnel's worth of copy here",
      len(VISIBLE) >= 420, "%d visible strings" % len(VISIBLE))
flat = [(p, v) for p, v in VISIBLE
        if not CYRILLIC.search(v) and not TOKEN_ONLY.match(v)]
check("every visible string is written in Cyrillic", not flat, str(flat[:4]))
tokens_only = [(p, v) for p, v in VISIBLE if not CYRILLIC.search(v)]
check("  and the ones that carry no letters carry only figures and slots",
      sorted(p for p, _v in tokens_only)
      == ["/checkout/commerce/anchor_head_accent",
          "/checkout/commerce/price_anchor_accent",
          "/result_copy/boxes/boxes/3/sub",
          "/result_copy/profile/chips/0", "/result_copy/profile/chips/3"],
      str(tokens_only))
check("  the ъ is in there", "ъ" in RAW)
check("  and no Russian ы, э or ё wandered in",
      not re.search(r"[ыэёЫЭЁ]", RAW),
      str(re.findall(r".{20}[ыэёЫЭЁ].{20}", RAW)[:2]))
check("  and no Romanian diacritic", not re.search(r"[ăâîșțĂÂÎȘȚ]", RAW))

COLOUR_NAMES = set(v for p, v in STRINGS
                   if p.endswith("/name") and "/colors/" in p)
ALLOWED_LATIN = sorted(COLOUR_NAMES | {"PDF", "Stripe", "e-mail",
                                       "Apple Pay", "Google Pay", "Mazzin"},
                       key=len, reverse=True)


def latin_left(value):
    text = TOKEN.sub("", value)
    for token in ALLOWED_LATIN:
        text = text.replace(token, "")
    return re.findall(r"[A-Za-z]+", text)


stray = [(p, latin_left(v)) for p, v in VISIBLE if latin_left(v)]
check("no Latin word survives outside the allowlist", not stray,
      str(stray[:4]))
check("  and the allowlist is really used — the palette lines name colours",
      all(any(name in s["reveals"]["palette"]["line"]
              for name in COLOUR_NAMES) for s in cfg["styles"]))
check("  the colour names being this funnel's own, not zodiac-bg's swatches",
      COLOUR_NAMES != set(v for p, v in ZBG_STRINGS.items()
                          if p.endswith("/name") and "/colors/" in p))

print("\n--- the quotes: „ “ for the page, «» kept for the model ---")
check("no value in the config contains a straight double quote",
      not [p for p, v in STRINGS if '"' in v])
check("  nor a straight one anywhere in the raw file's values",
      not re.search(r'": "[^"]*\\"', RAW))
check("  and no value carries a typewriter quote of any kind",
      not [(p, v) for p, v in STRINGS if "''" in v or '""' in v])
check("static copy quotes with the typographic pair, balanced",
      RAW.count("„") == RAW.count("“") >= 1,
      "%d „ vs %d “" % (RAW.count("„"), RAW.count("“")))
check("  and never with guillemets, which are the model's wrapper",
      "«" not in RAW and "»" not in RAW)
check("  so the archetype names are bare in the config",
      not any(ch in s["name"] for s in cfg["styles"]
              for ch in "«»„“"))

print("\n--- the product has one name, and it is профил ---")
READING = re.compile(r"чете", re.IGNORECASE)
check("no string in the funnel calls the product a четене, in any form",
      not READING.search(RAW), str(READING.findall(RAW)[:3]))
check("  while профил is everywhere the product is named",
      all(re.search(r"профил", cfg[b][k], re.IGNORECASE)
          for b, k in (("checkout", "product_name"), ("meta", "title"))))
for label, value in (
        ("rarity_card.note", cfg["result_copy"]["profile"]["rarity_card"]["note"]),
        ("rarity_card.tail", cfg["result_copy"]["profile"]["rarity_card"]["tail"]),
        ("profile.rarity_line", cfg["result_copy"]["profile"]["rarity_line"]),
        ("profile.offer_head", cfg["result_copy"]["profile"]["offer_head"]),
        ("profile.bridge", cfg["result_copy"]["profile"]["bridge"])):
    check("  %-20s names it профил" % label,
          re.search(r"профил", value, re.IGNORECASE) is not None, value)
check("  and the product is a love profile, everywhere it is titled",
      all("любов" in cfg[b][k].lower()
          for b, k in (("checkout", "product_name"), ("meta", "title")))
      and "ЛЮБОВЕН" in cfg["result_copy"]["kicker"])
CLINICAL = re.compile(r"кръстос\w*", re.IGNORECASE)
check("no line uses the clinical word for a cross", not CLINICAL.search(RAW))

print("\n--- the count claims say twenty taps ---")
# The walk takes twenty taps: the sign, the gender three-up, fourteen pairs
# and four four-ups.
# "18 двойки" stopped being true the day four of the pairs became grids, so
# the copy counts what the reader actually does — докосвания — and every
# claim says the same number.
TAPS = len(steps)
check("twenty taps, counted off the config",
      TAPS == 20 == cfg["swipe"]["pairs_count"])
COUNTED = [("swipe.subtext", cfg["swipe"]["subtext"]),
           ("analyzing.messages[0]", cfg["analyzing"]["messages"][0]),
           ("report.generating_messages[0]",
            cfg["report"]["generating_messages"][0]),
           ("checkout.proof_line", cfg["checkout"]["proof_line"]),
           ("interstitials[3].line", cfg["interstitials"][3]["line"]),
           ("result.value_banner", cfg["result"]["value_banner"])]
for name, text in COUNTED:
    check("  %-30s says 20 докосвания" % name, "20 докосвания" in text, text)
check("nothing claims eighteen pairs any more, or twelve of anything",
      not [v for _, v in STRINGS
           if re.search(r"\b(18|12) (сигнала|избора|докосвания|двойки)\b", v)
           or "двойки" in v],
      str([v for _, v in STRINGS if "двойки" in v][:3]))
check("  and the one number claimed is the walk's own",
      not [v for _, v in STRINGS
           if re.search(r"\b(\d+) докосвания\b", v)
           and int(re.search(r"\b(\d+) докосвания\b", v).group(1)) != TAPS])
check("  and the only twelve left are the signs and the year",
      all(re.search(r"12 (зодии|месеца)|12-те", v)
          for _p, v in VISIBLE if re.search(r"\b12\b", v)),
      str([v for _p, v in VISIBLE if re.search(r"\b12\b", v)
           and not re.search(r"12 (зодии|месеца)|12-те", v)]))

print("\n--- the words this vertical does not use ---")
EN_WORDS = ["psychic", "prediction", "predictions", "fortune",
            "horoscope", "prophecy", "your future will"]
BG_WORDS = ["ясновид", "предсказ", "предреч", "гада", "пророч", "хороскоп",
            "късмет", "бъдещето ти ще", "симптом", "лекарств", "инвестиц"]
low = RAW.lower()
for word in EN_WORDS + BG_WORDS:
    where = low.find(word)
    check("  never says %r" % word, where == -1,
          low[max(0, where - 40):where + 40])
en_hits = [(p, reports._banned_hit(v, reports.ZODIAC_BANNED))
           for p, v in STRINGS]
en_hits = [(p, h) for p, h in en_hits if h]
check("the whole config passes the English Terms check", not en_hits,
      str(en_hits[:4]))
bg_hits = [(p, reports._banned_hit(v, reports.ZODIAC_BG_BANNED))
           for p, v in STRINGS]
bg_hits = [(p, h) for p, h in bg_hits if h]
check("  and the Bulgarian one, ZODIAC_BG_ONLY included", not bg_hits,
      str(bg_hits[:4]))
check("  which really is the zodiac-bg list, not a copy of it",
      len(reports.ZODIAC_BG_BANNED)
      == len(reports.ZODIAC_BANNED) + len(reports.ZODIAC_BG_ONLY))
# Entertainment framing: the copy describes a profile read off taps and
# never promises an event. No future-tense claim about the reader's life.
future = [(p, v) for p, v in STRINGS if re.search(r"\bще\b", v)]
check("no line promises a future event — no ще anywhere", not future,
      str(future[:3]))
check("  and the offer sells a profile, not a forecast",
      "профил" in cfg["result_copy"]["offer_sub"]
      and "профил" in cfg["checkout"]["anchor"])

print("\n--- the cross lines: fifty-two, love-angle, keyed on the grid ---")
cross = cfg["result_copy"]["profile"]["sign_cross"]
check("sign_cross is keyed on the twelve labels the grid carries",
      [k for k in cross if k != "cusp"] == [i["label"] for i in sign_images],
      str(list(cross)))
check("  with the cusp key, which both readers spell in code",
      "cusp" in cross and len(cross) == 13
      and reports.CUSP_ID == "sign_cusp"
      and 'pick.id === "sign_cusp"' in RESULT_JS)
lines = [v for row in cross.values() for v in row.values()]
check("all 52 cross lines are written, in Cyrillic",
      len(lines) == 52 and all(CYRILLIC.search(v) for v in lines))
check("  each of the thirteen covers all four elements",
      all(sorted(row) == ["air", "earth", "fire", "water"]
          for row in cross.values()))
check("  and no two of them are the same sentence", len(set(lines)) == 52)
check("  none of them is a zodiac-bg line",
      not set(lines) & set(v for p, v in ZBG_STRINGS.items()
                           if p.startswith(CROSS_PATH)))
check("  every one is about love, in the word",
      all(re.search(r"обич|любов", v) for v in lines),
      str([v[:50] for v in lines if not re.search(r"обич|любов", v)][:3]))
TIERS = ("истинско съчетание", "необичайно съчетание", "рядко съчетание")
blend = [v for v in lines if "съчетание" in v]
plain = [v for v in lines if "съчетание" not in v]
check("thirty-six blend lines call it a съчетание", len(blend) == 36,
      "%d of %d" % (len(blend), len(lines)))
check("  each carrying exactly one of the three tiers",
      all(sum(t in v for t in TIERS) == 1 for v in blend))
check("  twelve of them the genuine-cross tier, one per sign",
      sum(TIERS[0] in v for v in blend) == 12)
check("  and the tier of every sign-and-element is zodiac-bg's",
      all(next((t for t in TIERS if t in cross[s][e]), "pure")
          == next((t for t in TIERS
                   if t in zbg["result_copy"]["profile"]["sign_cross"][s][e]),
                  "pure")
          for s in cross for e in cross[s]))
check("the sixteen that name no blend are the same-element and cusp lines",
      len(plain) == 16
      and sum("зодията в чист вид" in v for v in plain) == 12
      and len(cross["cusp"]) == 4
      and all(v.startswith("Границата") for v in cross["cusp"].values()))
check("  the rarity line says the same word",
      "съчетание" in cfg["result_copy"]["profile"]["rarity_line"])

print("\n--- the twenty-four subtypes ---")
SUBS = cfg["result_copy"]["profile"]["subtypes"]
names = [n for a in SUBS.values() for b in a.values() for n in b.values()]
check("twenty-four names, all distinct",
      len(names) == 24 and len(set(names)) == 24)
check("  each a two-word noun phrase, capitalised, in Cyrillic",
      all(len(n.split()) == 2 and n[0].isupper() and CYRILLIC.search(n)
          and not re.search(r"[A-Za-z]", n) for n in names),
      str([n for n in names if len(n.split()) != 2]))
# Agent-noun suffixes. Not -ец, which is also how a well (кладенец) ends.
AGENT = re.compile(r"(тел|ач|ник|джия|киня|ица)$")
check("  and no gendered agent noun among them",
      not [n for n in names if AGENT.search(n.split()[-1])],
      str([n for n in names if AGENT.search(n.split()[-1])]))
check("  none of them a zodiac-bg subtype",
      not set(names) & set(n for a in zbg["result_copy"]["profile"]["subtypes"]
                           .values() for b in a.values()
                           for n in b.values()))
check("  keyed on the other three elements, both energies, per archetype",
      all(sorted(SUBS[st["id"]]) == sorted(set(ELEMENTS) - {st["tags"][0]})
          and all(sorted(SUBS[st["id"]][e]) == ["moon", "sun"]
                  for e in SUBS[st["id"]])
          for st in cfg["styles"]))

print("\n--- the scales, and the labels the page prints ---")
SCALES = cfg["result_copy"]["profile"]["scales"]
LABELS = cfg["result_copy"]["labels"]
check("the module reads three scales: energy, tone, depth",
      [s["id"] for s in SCALES] == ["energy", "tone", "depth"]
      and 'var TONE = ["bold", "calm", "mystic"];' in RESULT_JS
      and "depth: between(tone.mystic, tone.bold + tone.calm)" in RESULT_JS)
check("  tone is relabelled Пламък to Жарава",
      (SCALES[1]["left"], SCALES[1]["right"]) == ("Пламък", "Жарава"))
check("  depth is relabelled Романтик to Реалист",
      (SCALES[2]["left"], SCALES[2]["right"]) == ("Романтик", "Реалист"))
# Energy is relabelled for love. The page reads `labels.energies` and the
# energy scale; the PDF, the mail header and the delivered page print the
# profile's `energy_labels`; and the three are pinned to one constant here —
# a page saying На глас over a PDF saying Слънце is the drift this exists to
# catch. Sun and moon stay the tag names underneath; only the words move.
check("  energy is relabelled На глас to В дълбочина, page and PDF alike",
      (SCALES[0]["left"], SCALES[0]["right"]) == ("На глас", "В дълбочина")
      == (profile["energy_labels"]["sun"], profile["energy_labels"]["moon"])
      and LABELS["energies"] == profile["energy_labels"]
      == reports.LOVE_BG_ENERGY_LABEL
      and sorted(LABELS["energies"]) == ["moon", "sun"])
check("  and zodiac-bg keeps Слънце and Луна, untouched",
      reports.ZODIAC_BG_PROFILE["energy_labels"] is reports.ENERGY_LABEL_BG
      and reports.ENERGY_LABEL_BG == {"sun": "Слънце", "moon": "Луна"}
      and zbg["result_copy"]["labels"]["energies"] == reports.ENERGY_LABEL_BG)
check("elements are reports.py's Bulgarian four, shared with zodiac-bg",
      LABELS["elements"] == reports.ELEMENT_LABEL_BG
      and profile["element_labels"] is reports.ELEMENT_LABEL_BG)
check("verdict badges are the profile's, exactly",
      LABELS["verdicts"] == profile["words"]["verdicts"]
      == reports.RENDER_WORDS_BG["verdicts"])
check("months are reports.py's twelve, in order",
      LABELS["months"] == list(reports.MONTH_ABBR_BG))
check("the two templates keep their tokens",
      "{energy}" in LABELS["led_template"]
      and all(t in LABELS["scale_aria"] for t in ("{left}", "{right}", "{at}"))
      and "{price}" in LABELS["price_regular_aria"])
for energy in profile["energy_labels"].values():
    check("  led_template reads for %-11s" % energy,
          LABELS["led_template"].replace("{energy}", energy)
          == "водеща енергия " + energy)
check("the chips say it the way the formula does",
      "водеща стихия {element}" in cfg["result_copy"]["profile"]["chips"]
      and "водеща стихия" in cfg["result_copy"]["profile"]["formula"])
check("the split caption names the four elements in the same four words",
      all(label in cfg["result_copy"]["profile"]["split_caption"]
          for label in reports.ELEMENT_LABEL_BG.values()))
check("the saves heading is the PDF's own heading for that list",
      LABELS["saves_head"] == profile["words"]["save"] == "Пази сърцето си")

print("\n--- every card label is read whole: two lines, never an ellipsis ---")
# The badge pill is one line with an ellipsis in shared CSS, and four of this
# funnel's labels are longer than a 390px tile's 167px pill — "Писмо на
# възглавницата" came back as "Писмо на възглавн…". The fix wraps to a
# second line and lives in mazzin.css, scoped to the cards whose picture
# comes out of this funnel's own gallery, since the shell puts no funnel
# class on the page: every other funnel's pill is byte for byte what it was,
# and the sign grid these cards share with zodiac-bg included.
CSS = open(os.path.join(ROOT, "static/css/mazzin.css"), encoding="utf-8").read()
LOVE_RULE = '.card:has(> .card-img[src*="/galleries/love-zodiac-bg/"]) .card-name'
check("the sheet carries one rule for this funnel's card names",
      CSS.count(LOVE_RULE + " {") == 1 and CSS.count("love-zodiac-bg") == 1)
_rule = CSS.split(LOVE_RULE + " {", 1)[1].split("}", 1)[0]
check("  it wraps, keeps the pill at its own width, and stops at two lines",
      "white-space: normal;" in _rule and "width: max-content;" in _rule
      and "max-height: calc(2.4em + 10px);" in _rule
      and "ellipsis" not in _rule and "line-clamp" not in _rule)
_base = CSS.split("\n.card-name {", 1)[1].split("}", 1)[0]
check("  and the shared pill is untouched: one line, ellipsis, for everyone "
      "else",
      "white-space: nowrap;" in _base and "text-overflow: ellipsis;" in _base
      and "max-width: 96%;" in _base and "font-size: 14px;" in _base
      and "padding: 5px 10px;" in _base)
# The budget, measured on the live shell at 390px: a pair card and a four-up
# cell are both 174px wide, the pill is 96% of that less 10px of padding a
# side — 147px a line — and the widest glyph run in these labels measured
# 9.2px a character at 14px bold. So a word longer than fifteen characters
# can spill past the pill, and a label longer than thirty cannot be held in
# two lines. The four that wrap today are 19 to 22 characters; every label
# is held under both numbers before it can be committed, so an ellipsis
# never comes back and a third line never appears.
WORD, LABEL = 15, 30
long_words = [(i["id"], w) for i in love_images
              for w in re.split(r"[\s-]+", i["label"]) if len(w) > WORD]
long_labels = [(i["id"], i["label"]) for i in love_images
               if len(i["label"]) > LABEL]
check("no word is longer than a pill line holds (%d)" % WORD, not long_words,
      str(long_words[:4]))
check("  and no label is longer than two lines hold (%d)" % LABEL,
      not long_labels, str(long_labels[:4]))
print("    longest label %d chars, longest word %d chars"
      % (max(len(i["label"]) for i in love_images),
         max(len(w) for i in love_images
             for w in re.split(r"[\s-]+", i["label"]))))

print("\n--- the gender step: three named options, scoring nothing ---")
# "За кого е този профил?" sits right after the sign, on the three-up format
# the engine gained for it: one row of three, pinned in the approved order,
# each card carrying one gender tag and no axis tag, so the answer changes
# the report's grammar and never its archetype.
GENDER = by_step["gender"]
check("the gender step is third, after the sign",
      [s["id"] for s in steps][:3] == ["spark", "sign", "gender"])
check("  asking for whom the profile is",
      GENDER["question"] == "За кого е този профил?", GENDER["question"])
check("  on the three-up, pinned in the approved order",
      GENDER["format"] == "grid3" and GENDER.get("shuffle") is False
      and [i["id"] for i in GENDER["pairs"][0]["images"]] == list(GENDER_IDS)
      and [i["label"] for i in GENDER["pairs"][0]["images"]]
      == ["За жена", "За мъж", "Предпочитам да не казвам"])
check("  each card carries its one gender tag and nothing that scores",
      [i["tags"] for i in GENDER["pairs"][0]["images"]]
      == [["gender_female"], ["gender_male"], ["gender_unsaid"]]
      and all(not set(i["tags"]) & set(ELEMENTS + ENERGIES + TONES)
              for i in GENDER["pairs"][0]["images"]))
check("  so no archetype counts it",
      not any(t.startswith("gender_") for st in cfg["styles"]
              for t in st["tags"])
      and all(t in reports.GENDER_TAGS for i in GENDER["pairs"][0]["images"]
              for t in i["tags"]))
check("  three frames with three colours each, on disk",
      all(len(i["colors"]) == 3
          and os.path.isfile(os.path.join(ROOT, i["img"].lstrip("/")))
          for i in GENDER["pairs"][0]["images"]))
check("the engine knows the format, by that name and no other new one",
      "var GRID_SIZE = { grid3: 3, grid4: 4, grid6: 6, grid12: 12 };"
      in ENGINE_JS)
check("  and the sheet lays it out: one row of three, the badge stepped down",
      ".cards.is-grid3 {" in CSS
      and "grid-template-columns: repeat(3, minmax(0, 1fr));"
      in CSS.split(".cards.is-grid3 {", 1)[1].split("}", 1)[0]
      and ".cards.is-grid3 .card-name {" in CSS
      and ".cards.is-grid3 .reaction { display: none !important; }" in CSS)
# And the server accepts what the client sends: /api/track gates a swipe's
# shown list on a closed set of sizes, and three had to be admitted to it or
# this step's every tap was a valid event thrown away on arrival.
import tracking                                                # noqa: E402
check("  and /api/track accepts a three-image shown list",
      3 in tracking.SHOWN_SIZES
      and tracking._clean_extra(SLUG, "swipe", {
          "pair": "gender:p1", "shown": list(GENDER_IDS),
          "chosen": "g02"})["chosen"] == "g02"
      and tracking.SHOWN_SIZES == frozenset((2, 3, 4, 6, 12)))
check("  no other funnel names the format",
      not [f for f in os.listdir(os.path.join(ROOT, "funnels"))
           if not f.startswith("love-zodiac-bg")
           and '"grid3"' in open(os.path.join(ROOT, "funnels", f),
                                encoding="utf-8").read()])
# The three-up's cells are the sign grid's width — about 112px at 390px —
# and its badge is the sign grid's 11px, so a line holds about thirteen
# characters and two lines about twenty-six. "Предпочитам да не казвам"
# measured two whole lines on the live shell; the budget is held here.
G_WORD, G_LABEL = 13, 26
check("  every label fits the narrow cell in two lines",
      all(len(i["label"]) <= G_LABEL
          and all(len(w) <= G_WORD for w in i["label"].split())
          for i in GENDER["pairs"][0]["images"]))

print("\n--- compatibility is the locked core ---")
MIN = cfg["result_copy"]["profile"]
ROWS = MIN["unlock"]
check("the unlock list leads with compatibility",
      ROWS[0]["id"] == "materials", str([r["id"] for r in ROWS]))
check("  and sells the whole twelve-sign table in the badge words",
      "12" in ROWS[0]["line"]
      and LABELS["verdicts"]["works"] in ROWS[0]["line"]
      and LABELS["verdicts"]["avoid"] in ROWS[0]["line"], ROWS[0]["line"])
check("  plus how to keep the relationship, in the reviewed words",
      "как да пазите връзката" in ROWS[0]["line"]
      and "задърж" not in ROWS[0]["line"], ROWS[0]["line"])
check("    said the same way everywhere the chapter is sold",
      not [p for p, v in STRINGS if "да го задържиш" in v],
      str([p for p, v in STRINGS if "да го задържиш" in v]))
check("the evening question is the reviewed one",
      by_step["evening"]["question"] == "Идеалната вечер за двама:",
      by_step["evening"]["question"])
check("the compatibility card is the first card, and it is love-headed",
      MIN["cards"][0]["id"] == "materials"
      and MIN["cards"][0]["key"] == "Съвместимост"
      and "12" in MIN["cards"][0]["promise"])
check("  with the purpose upgrade for readers who came for love",
      "purpose_love" in (MIN["cards"][0].get("upgrade") or {}))
check("the purpose map emphasises compatibility for that tag",
      cfg["result_copy"]["purpose_map"]["purpose_love"]["emphasized_section"]
      == "materials")
check("  which every reader carries, off the hook pair",
      all("purpose_love" in c["tags"]
          for c in by_step["spark"]["pairs"][0]["images"]))
check("the compatibility chapter's title and manifest line say twelve",
      "12" in cfg["report"]["sections"][3]["title"]
      and "12" in cfg["checkout"]["manifest"][3])
check("the boxes hero fills both verdicts from labels, not prose",
      "{works}" in cfg["result_copy"]["boxes"]["hero_line"]
      and "{avoid}" in cfg["result_copy"]["boxes"]["hero_line"]
      and LABELS["verdicts"]["works"]
      not in cfg["result_copy"]["boxes"]["hero_line"])
RARE = MIN["rarity_card"]
check("the rarity card is framed, with no figure of its own",
      all(RARE.get(k) for k in ("lead", "tail", "note"))
      and not [k for k in ("lead", "tail", "note") if re.search(r"\d", RARE[k])]
      and RARE["note"].count("—") == 1)
check("  and reads as one sentence around the figure",
      (RARE["lead"] + " 97% " + RARE["tail"]) == "По-рядко от 97% от профилите")
check("the hero draws four capsules, each a token",
      len(MIN["chips"]) == 4 and all(TOKEN.search(c) for c in MIN["chips"]))
check("the unlock copy states no figure it cannot stand behind",
      not [r for r in ROWS
           if re.search(r"\d", re.sub(r"\{\w+\}|#\d|\b12(-те)?\b", "",
                                      r["line"]))],
      str([r["line"] for r in ROWS]))

print("\n--- engine.js's own furniture ---")
ENGINE_KEYS = [("checkout", "unlock_note"), ("checkout", "redirecting"),
               ("checkout", "error_checkout"), ("checkout", "error_payment"),
               ("checkout", "error_consent"), ("report", "preparing"),
               ("report", "locked_aria"), ("swipe", "card_aria")]
for block, key in ENGINE_KEYS:
    value = cfg[block].get(key)
    check("  %s.%-15s is filled, in Cyrillic" % (block, key),
          bool(value) and CYRILLIC.search(value), repr(value))
check("the unlock note keeps both its tokens",
      "{n}" in cfg["checkout"]["unlock_note"]
      and "{price}" in cfg["checkout"]["unlock_note"])
check("  and counts in Bulgarian words, eleven of them",
      cfg["checkout"]["number_words"] == zbg["checkout"]["number_words"]
      and len(cfg["checkout"]["number_words"]) == 11)
check("the card label keeps its token", "{label}" in cfg["swipe"]["card_aria"])
check("the delivery lines say where the PDF went, with {email} intact",
      "{email}" in cfg["result_copy"]["delivery_line"]
      and cfg["result_copy"]["delivery_line_bare"])
ENGLISH_DEFAULTS = [
    (ENGINE_JS, r'"Unlock all {n} sections \u00B7 {price}"'),
    (ENGINE_JS, '"Redirecting..."'),
    (ENGINE_JS, '"Choose {label}"'),
    (RESULT_JS, '"{energy}-led"'),
    (RESULT_JS, 'fire: "Fire"'),
    (RESULT_JS, '{ sun: "Sun", moon: "Moon" }'),
]
for source, literal in ENGLISH_DEFAULTS:
    check("  default still in the file: %s" % literal[:44],
          literal in source, literal)
check("the module names no funnel slug to pick a layout",
      SLUG not in RESULT_JS and SLUG not in ENGINE_JS)

print("\n--- the sale, and what it is allowed to claim ---")
BEFORE_END = reports.datetime.datetime(2026, 9, 6,
                                       tzinfo=reports.datetime.timezone.utc)
ONE_SEC = reports.datetime.timedelta(seconds=1)
SALE = cfg["sale"]
check("it is active at 199 against a regular 499",
      SALE["active"] is True and SALE["price_cents"] == 199
      and SALE["regular_price_cents"] == 499, str(SALE))
check("  and the struck figure is what this funnel actually charges",
      SALE["regular_price_cents"] == cfg["pricing"]["amount_cents"])
check("  which is the guard payments.py enforces",
      payments._sale(dict(cfg, sale=dict(SALE, regular_price_cents=1999)),
                     BEFORE_END) is None)
check("  and a sale that is not a discount does not run either",
      payments._sale(dict(cfg, sale=dict(SALE, price_cents=499)),
                     BEFORE_END) is None)
check("  the amount handed to Stripe clears its 0,50 € floor",
      payments._effective_price(cfg, BEFORE_END)[0] >= 50)
check("the label names the offer and no date",
      SALE["label"] == "Лятно намаление"
      and not re.search(r"\d", SALE["label"]), SALE["label"])
check("  and no string on this funnel puts a date in the pitch",
      not [p for p, v in STRINGS
           if re.search(r"\b(30|септември|сеп\.)\b", v)])
check("it ends on the pinned instant",
      SALE["ends"] == "2026-09-30T23:59:59-12:00", SALE["ends"])
ENDS = reports.datetime.datetime.fromisoformat(SALE["ends"])
check("  on a clock, with an offset", ENDS.tzinfo is not None)
for label, when, want in (
        ("today", BEFORE_END, 199),
        ("one second before the end", ENDS - ONE_SEC, 199),
        ("at the end", ENDS, 499),
        ("a week after", ENDS + reports.datetime.timedelta(days=7), 499)):
    cents, live = payments._effective_price(cfg, when)
    check("  %-26s charges %d" % (label, want),
          cents == want and bool(live) == (want == 199),
          "%s / %s" % (cents, bool(live)))

print("\n--- the sandbox twin is this funnel, on test keys ---")
twin_cfg = json.load(open(os.path.join(ROOT, "funnels",
                                       SLUG + "-test.json"), encoding="utf-8"))
TWINNED = ("slug", "funnel_id", "stripe_mode")
differ = sorted(k for k in set(cfg) | set(twin_cfg)
                if cfg.get(k) != twin_cfg.get(k))
check("it differs in exactly the three twinned fields",
      differ == sorted(TWINNED), str(differ))
check("  slug, funnel_id and stripe_mode",
      twin_cfg["slug"] == SLUG + "-test"
      and twin_cfg["funnel_id"] == "love_zodiac_bg_v1_test"
      and twin_cfg["stripe_mode"] == "test")
check("  its static copy is byte-identical to funnels/",
      open(os.path.join(ROOT, "static/funnels", SLUG + "-test.json"),
           encoding="utf-8").read()
      == open(os.path.join(ROOT, "funnels", SLUG + "-test.json"),
              encoding="utf-8").read())
check("  it runs the same sale",
      payments._effective_price(twin_cfg, BEFORE_END)[0] == 199)
check("  and is gated by the same switch every twin is",
      config.is_test_slug(twin_cfg["slug"]) and not config.is_test_slug(SLUG))
check("  and reads the same report profile, so a sandbox purchase delivers "
      "the same document",
      reports._profile(twin_cfg["slug"]) is profile
      and reports._email_copy({"funnel": twin_cfg["slug"]})
      is reports.COPY_LOVE_BG)

print("\n--- the gallery on disk ---")
GDIR = os.path.join(ROOT, "static/galleries/love-zodiac-bg")
on_disk = {f[:-len(".webp")] for f in os.listdir(GDIR) if f.endswith(".webp")}
referenced = ({i["id"] for i in love_images} | {g["id"] for g in PREVIEW}
              | {"og"})
check("every referenced id has a file", referenced <= on_disk,
      str(sorted(referenced - on_disk)[:4]))
check("  and the gallery holds nothing else", not (on_disk - referenced),
      str(sorted(on_disk - referenced)[:4]))
big = [f for f in sorted(on_disk)
       if os.path.getsize(os.path.join(GDIR, f + ".webp")) > 120 * 1024]
check("no frame is over 120KB", not big, str(big[:4]))
tiny = [f for f in sorted(on_disk)
        if os.path.getsize(os.path.join(GDIR, f + ".webp")) < 6 * 1024]
if tiny:
    notes.append("%d of %d frames are still gradient placeholders (under "
                 "6KB) — real art lands with scripts/gen_love_gallery.py"
                 % (len(tiny), len(on_disk)))
print("    %d frames, %d still placeholder-sized" % (len(on_disk), len(tiny)))
try:
    from PIL import Image
except ImportError:
    Image = None
    notes.append("Pillow is not installed here, so the frame geometry was "
                 "not measured")
if Image is not None:
    def size_of(name):
        with Image.open(os.path.join(GDIR, name + ".webp")) as im:
            return im.size
    # The shape of the tile each step renders, measured on the live shell
    # at 390x844: a pair card is 174x603, a four-up cell about 174x297.
    SHAPE = {"pair": (640, 960), "grid3": (360, 600), "grid4": (360, 600)}
    wrong = [(i["id"], size_of(i["id"])) for s in steps
             if s["id"] != "sign" for i in s["pairs"][0]["images"]
             if size_of(i["id"]) != SHAPE[s["format"]]]
    check("  pair cards are 640x960, three-up and four-up cells 360x600",
          not wrong,
          str(wrong[:3]))
    check("  the two interstitial frames are 4:5, 800x1000",
          size_of("int1") == size_of("int2") == (800, 1000))
    check("  and the share card is 1200x630", size_of("og") == (1200, 630))

print("\n--- the report profile: mirrored from zodiac-bg, object for object ---")
ZBG = reports.ZODIAC_BG_PROFILE
check("it declares every key zodiac-bg's profile declares, plus the "
      "gender line",
      sorted(set(profile) - {"personal_note"}) == sorted(ZBG),
      str(sorted(set(profile) ^ set(ZBG))))
check("  nothing is left unfilled", not [k for k, v in profile.items()
                                         if v is None],
      str([k for k, v in profile.items() if v is None]))
OWN = ("system", "spec", "stubs", "stub_colors", "words", "banned",
       "cache_rev", "pdf_lead", "energy_labels", "mail", "mail_kicker",
       "mail_cross_fallback", "json_retry")
check("  what love differs in is its own object",
      all(profile[k] is not ZBG[k] for k in OWN),
      str([k for k in OWN if profile[k] is ZBG[k]]))
SHARED = ("prompt_budget", "verify", "pdf_css", "pdf_logo", "pdf_lang",
          "pdf_note", "pdf_cover", "pdf_elements", "element_labels",
          "compatibility", "mail_link", "json_repair", "cached", "personal",
          "verify_marks", "retry_detail", "pdf_node", "delivery_note")
check("  and what it shares, it shares by reference or by value",
      all(profile[k] is ZBG[k] or profile[k] == ZBG[k] for k in SHARED),
      str([k for k in SHARED if not (profile[k] is ZBG[k]
                                     or profile[k] == ZBG[k])]))
check("the prompt budget is zodiac-bg's, because the language is",
      profile["prompt_budget"] == reports.ZODIAC_BG_PROMPT_BUDGET
      and reports._prompt_budget(profile) == reports.ZODIAC_BG_PROMPT_BUDGET)
check("the cached trio and the personal trio are zodiac-bg's",
      profile["cached"] == ("palette", "mistakes", "splurge")
      and profile["personal"] == ("dna", "materials", "shopping")
      and reports.cached_sections(SLUG) == profile["cached"]
      and reports.personal_sections(SLUG + "-test") == profile["personal"])
check("  every cached section opens on its own first revision",
      profile["cache_rev"] == {"palette": "lovebg1", "mistakes": "lovebg1",
                               "splurge": "lovebg1"}, str(profile["cache_rev"]))
REPORTS_SRC = open(os.path.join(ROOT, "reports.py"), encoding="utf-8").read()
check("the quote repair is the one zodiac-bg uses, not a fork of it",
      profile["json_repair"] is reports._bg_quote_repair
      and ZBG["json_repair"] is reports._bg_quote_repair
      and REPORTS_SRC.count("def _bg_quote_repair") == 1
      and REPORTS_SRC.count("_CLOSER_RE = re.compile") == 1)
check("  and the retry note names this product's archetype in guillemets",
      profile["json_retry"] is reports.LOVE_BG_JSON_RETRY
      and "«Открит пламък»" in profile["json_retry"]
      and "straight double quote" in profile["json_retry"]
      and "NO quotation marks" in profile["json_retry"])
check("the year runs on zodiac-bg's months",
      reports._months_for(profile) == reports._year_labels_bg()
      and reports._year_marks(profile)
      == (reports.RENDER_WORDS_BG["year_strong"],
          reports.RENDER_WORDS_BG["year_quiet"]))
check("  and the love stubs are a zodiac stub set, so the year gets stamped",
      profile["stubs"] in reports.ZODIAC_STUB_SETS
      and reports.ZODIAC_STUBS_BG in reports.ZODIAC_STUB_SETS)

print("\n--- the voice ---")
SYSTEM = profile["system"]
check("it is its own system prompt, about love, in English instructions",
      SYSTEM is reports.LOVE_BG_SYSTEM and SYSTEM != reports.ZODIAC_BG_SYSTEM
      and SYSTEM.startswith("You write love and relationship profile reports"))
check("  demanding Bulgarian in Cyrillic, ти not Вие, and the ъ",
      "CYRILLIC" in SYSTEM and '"ти"' in SYSTEM and '"Вие"' in SYSTEM
      and "ъ, which Bulgarian uses" in SYSTEM)
check("  the archetype always in guillemets, on a lowercase common noun",
      "GUILLEMETS" in SYSTEM and "U+00AB" in SYSTEM
      and "lowercase common noun" in SYSTEM
      and "definite article only" in SYSTEM)
for example in ("Профилът «Открит пламък» се влюбва бързо",
                "Палитрата «Открит пламък» се държи на един цвят",
                "Енергията «Открит пламък»",
                "сърцето на профила «Открит пламък»",
                "в палитрата «Открит пламък»",
                '"Сърцето на Профилът" is'):
    check("  worked example: %s" % example[:44], example in SYSTEM)
check("  the never-claim-the-future rule, in English and in Bulgarian",
      all(w in SYSTEM for w in ('"psychic"', '"horoscope"', '"prophecy"',
                                '"ясновидец"', '"предсказание"', '"гадая"',
                                '"хороскоп"', '"късмет"', '"бъдещето ти')))
check("  and the love-specific nevers: meeting, wedding, pregnancy, "
      "the ex, destiny, magic",
      all(w in SYSTEM for w in ('"ще срещнеш"', '"сватба"', '"бременност"',
                                '"той ще се върне"', '"тя ще се върне"',
                                '"съдба"', '"писано ти е"', '"сродна душа"',
                                '"половинка"', '"любовна магия"',
                                '"омагьосвам"', '"ритуал за привличане"')),
      str([w for w in ('"ще срещнеш"', '"сватба"', '"бременност"',
                       '"той ще се върне"', '"съдба"', '"половинка"',
                       '"любовна магия"') if w not in SYSTEM]))
check("  no manipulation or control of a partner",
      "manipulating or controlling a partner" in SYSTEM
      and "reader's own side" in SYSTEM)
check("  no therapeutic or diagnostic frame — entertainment and "
      "self-discovery",
      "No therapeutic or diagnostic frame" in SYSTEM
      and "entertainment" in SYSTEM and "самопознание" in SYSTEM
      and "not couples counselling" in SYSTEM)
check("  the medical and financial line, as zodiac-bg states it",
      '"диагноза", "симптоми", "лекарства" and "инвестиции"' in SYSTEM)
check("  keys stay English, values Bulgarian, one line each",
      "KEYS stay in English" in SYSTEM and "Every value is one line" in SYSTEM)
check("  and nothing in it is U+201E or U+201C",
      "„" not in SYSTEM and "“" not in SYSTEM)

print("\n--- the shapes ---")
SPEC = profile["spec"]
check("six shapes, the six ids every funnel uses",
      sorted(SPEC) == ["dna", "materials", "mistakes", "palette", "shopping",
                       "splurge"]
      and sorted(SPEC) == sorted(reports.ZODIAC_BG_SPEC))
check("  none of them is zodiac-bg's",
      all(SPEC[s] != reports.ZODIAC_BG_SPEC[s] for s in SPEC))
check("  each closes on the love JSON rule, with this product's example",
      all(SPEC[s].endswith(reports.LOVE_BG_JSON_RULE) for s in SPEC)
      and "«Открит пламък»" in reports.LOVE_BG_JSON_RULE
      and "с no quotation marks" not in reports.LOVE_BG_JSON_RULE
      and "no quotation marks" in reports.LOVE_BG_JSON_RULE
      and "Кажи направо, че тази седмица" in reports.LOVE_BG_JSON_RULE)
check("  each states its budgets at the Bulgarian number",
      all(reports._budget_lines(s, reports.ZODIAC_BG_PROMPT_BUDGET) in SPEC[s]
          and "LENGTHS ARE HARD LIMITS" in SPEC[s] for s in SPEC))
check("  and every field name the validator wants is in the shape it wants",
      all(("\"%s\"" % field) in SPEC[section]
          for section, fields in reports.SHAPE.items()
          for field in fields),
      str([(section, field) for section, fields in reports.SHAPE.items()
           for field in fields if ("\"%s\"" % field) not in SPEC[section]]))
SAYS = {
    "palette": ("the way this person loves", "talismans", "closeness",
                "it does nothing to the other"),
    "mistakes": ("hidden strength in love", "works against this reader in "
                 "love", "never a tactic aimed at the partner",
                 "EXACTLY TWO SENTENCES"),
    "materials": ("THEIR PATTERN IN LOVE", "HOW TO KEEP IT ALIVE",
                  "HOW TO PROTECT THE RELATIONSHIP", "Лъв + Овен",
                  "never that two people cannot be together",
                  "change the other person"),
    "splurge": ("where to invest\nthe heart and where not to", "never money",
                "THREE CONCRETE MOVES", "THE LEAK, AND HOW TO PLUG IT",
                "never something the reader gets the other person"),
    "dna": ("combine in love", "once it gets serious",
            "how they choose somebody", "how a partner reads them"),
    "shopping": ("good for in love", "nobody arrives, nobody returns",
                 reports.RENDER_WORDS_BG["year_strong"],
                 reports.RENDER_WORDS_BG["year_quiet"]),
}
for section, phrases in sorted(SAYS.items()):
    check("  %-9s says what it is about" % section,
          all(p in SPEC[section] for p in phrases),
          str([p for p in phrases if p not in SPEC[section]]))
check("  the year map asks for the Bulgarian marks and never the English",
      "Strongest month:" not in SPEC["shopping"]
      and "Quiet month:" not in SPEC["shopping"]
      and "exactly three months" in SPEC["shopping"]
      and profile.get("verify_marks") is True)
check("  the sign combo example carries no quotation marks",
      "Лъв + Овен, with no quotation marks" in SPEC["materials"]
      and '\\"' not in SPEC["materials"])
check("  and no shape uses U+201E or U+201C",
      all("„" not in SPEC[s] and "“" not in SPEC[s] for s in SPEC))

print("\n--- the banned list: zodiac-bg's, plus what a love reading promises ---")
BANNED = profile["banned"]
check("it starts with the whole zodiac-bg list",
      BANNED[:len(reports.ZODIAC_BG_BANNED)] == reports.ZODIAC_BG_BANNED
      and BANNED is reports.LOVE_BG_BANNED)
check("  and adds the love list", BANNED[len(reports.ZODIAC_BG_BANNED):]
      == reports.LOVE_BG_ONLY and len(reports.LOVE_BG_ONLY) == 11)
CAUGHT = ("тя е твоята половинка", "сродна душа", "сродни души",
          "това е съдба", "съдбата ви е обща", "съдбовна среща",
          "писано ти е", "той ще се върне", "тя ще се върне при теб",
          "върни се при него", "омагьосан от теб", "любовна магия",
          "любовни магии", "ритуал за привличане", "привличащ ритуал",
          "ще срещнеш човека", "ПОЛОВИНКАТА ти", "хороскоп", "инвестиции")
for phrase in CAUGHT:
    check("  catches %-26s" % phrase,
          reports._banned_hit(phrase, BANNED) is not None)
FREE = ("половин час преди срещата", "написано е на лицето ти",
        "връщаш се към стария навик", "се връща към теб всяка вечер",
        "магията на една обикновена вечер", "ритуалът на неделната закуска",
        "ще срещнете гостите заедно", "привлича те тишината",
        "непредвидим", "лекар по професия")
for phrase in FREE:
    check("  and lets %-32s through" % phrase,
          reports._banned_hit(phrase, BANNED) is None,
          str(reports._banned_hit(phrase, BANNED)))


def profile_strings():
    """Every string the profile itself can put in front of a reader."""
    def walk(node):
        if isinstance(node, dict):
            for value in node.values():
                for item in walk(value):
                    yield item
        elif isinstance(node, (list, tuple)):
            for value in node:
                for item in walk(value):
                    yield item
        elif isinstance(node, str):
            yield node
    for key in ("stubs", "stub_colors", "words", "mail", "pdf_lead",
                "pdf_note", "mail_kicker", "mail_cross_fallback"):
        for item in walk(profile[key]):
            yield key, item


hit = [(k, reports._banned_hit(s, BANNED), s[:50]) for k, s in profile_strings()
       if reports._banned_hit(s, BANNED)]
check("nothing the profile prints itself trips its own list", not hit,
      str(hit[:4]))
hit = [(p, reports._banned_hit(v, BANNED)) for p, v in STRINGS
       if reports._banned_hit(v, BANNED)]
check("  and nothing in the funnel's own copy does either", not hit,
      str(hit[:4]))
hit = [(p, reports._banned_hit(v, BANNED)) for p, v in leaves(twin_cfg)
       if reports._banned_hit(v, BANNED)]
check("  nor in the twin's", not hit, str(hit[:4]))

print("\n--- the guillemet rule, on every string the model sees or writes ---")
LLM_PATH = [("system", SYSTEM), ("json_rule", reports.LOVE_BG_JSON_RULE),
            ("json_retry", reports.LOVE_BG_JSON_RETRY)]
LLM_PATH += [("spec:" + s, SPEC[s]) for s in sorted(SPEC)]
check("no low-9 or turned-comma mark anywhere on the model's path",
      not [k for k, text in LLM_PATH if "„" in text or "“" in text])
NAME = "Открит пламък"
bare = [(k, m.start()) for k, text in LLM_PATH
        for m in re.finditer(NAME, text)
        if not (text[m.start() - 1:m.start()] == "«"
                and text[m.end():m.end() + 1] == "»")]
check("  every archetype name on it is wrapped in «»",
      bare == [("system", SYSTEM.index('"Профил Открит пламък се')
                          + len('"Профил '))], str(bare[:4]))
check("    the one exception being the broken example the prompt shows",
      SYSTEM.count('"Профил Открит пламък се влюбва бързо"') == 1
      and "reads as broken" in SYSTEM)
STUB_STRINGS = [s for k, s in profile_strings() if k == "stubs"]
check("the stubs name the archetype in «{name}» and never bare",
      all("{name}" not in s or s.count("«{name}»") == s.count("{name}")
          for s in STUB_STRINGS)
      and sum(s.count("«{name}»") for s in STUB_STRINGS) >= 4)
check("  and carry no quotation mark of any kind",
      not [s[:40] for s in STUB_STRINGS
           if '"' in s or "„" in s or "“" in s or "'" in s])
check("  the mail names it in guillemets too",
      profile["mail"]["subject"].count("«%s»") == 1
      and profile["mail"]["body"].count("«%s»") == 1)
check("  and every one of them is Cyrillic prose",
      not [s[:40] for s in STUB_STRINGS
           if s not in (reports.FROM_CONFIG, "works", "avoid")
           and re.findall(r"[A-Za-z]+", s.replace("{name}", ""))],
      str([s[:40] for s in STUB_STRINGS
           if s not in (reports.FROM_CONFIG, "works", "avoid")
           and re.findall(r"[A-Za-z]+", s.replace("{name}", ""))][:3]))

print("\n--- the fallbacks stand on their own ---")
months = reports._months_for(profile)
STYLE = reports._style(cfg, "radiant_fire")
check("a style resolves off this config", STYLE and STYLE["name"] == NAME)
for section in sorted(SPEC):
    stub = reports._stub_for(section, NAME, STYLE, profile["stubs"], months)
    try:
        reports.VALIDATORS[section](stub)
        ok, why = True, ""
    except Exception as exc:                      # noqa: BLE001
        ok, why = False, "%s: %s" % (type(exc).__name__, exc)
    check("  %-9s stub passes the validator" % section, ok, why)
mistakes = reports._stub_for("mistakes", NAME, STYLE, profile["stubs"], months)
check("the mistakes stub opens on the strength the free page gave away",
      mistakes["items"][0] == STYLE["reveals"]["mistake_one"]
      and len(mistakes["items"]) == 5
      and mistakes["items"][0]["title"] != profile["stubs"]["mistakes"]
      ["items"][0]["title"])
year = reports._stub_for("shopping", NAME, STYLE, profile["stubs"], months)
check("the year stub is stamped with this reader's twelve months",
      [row["name"] for row in year["items"]] == months)
notes_ = [row["priority_note"] for row in year["items"]]
check("  three strong months and one quiet, in the profile's own marks",
      sum(n.startswith(reports.RENDER_WORDS_BG["year_strong"])
          for n in notes_) == 3
      and sum(n.startswith(reports.RENDER_WORDS_BG["year_quiet"])
              for n in notes_) == 1)
check("  and the purchase path's check accepts it",
      reports._verify_for(profile, STYLE, months)(("shopping",),
                                                  {"shopping": year}) is None)
palette = reports._stub_for("palette", NAME, STYLE, profile["stubs"], months,
                            colors=profile["stub_colors"])
check("the palette stub carries this style's own four colours",
      [c["name"] for c in palette["colors"]]
      == [c["name"] for c in STYLE["reveals"]["palette"]["colors"]]
      and [c["role"] for c in palette["colors"]]
      == [t[0] for t in reports.LOVE_BG_COLOR_TEXT])
check("  under love sentences, not zodiac-bg's",
      reports.LOVE_BG_COLOR_TEXT != reports.ZODIAC_COLOR_TEXT_BG
      and len(reports.LOVE_BG_COLOR_TEXT) == 4
      and reports._verify_for(profile, STYLE, months)(
          ("palette",), {"palette": palette}) is None)
check("  and the fallback name is Bulgarian",
      profile["words"]["style_fallback"] == "Твоят стил")

print("\n--- the year map is policed in Bulgarian ---")


def year_map(strong, quiet):
    rows = []
    for index, label in enumerate(months):
        note = "Добър за разговор." * 3
        if index in (0, 3, 6):
            note = strong + " " + note
        if index == 9:
            note = quiet + " " + note
        rows.append({"name": label, "priority_note": note})
    return {"items": rows, "skip": []}


GOOD_BG = year_map(reports.RENDER_WORDS_BG["year_strong"],
                   reports.RENDER_WORDS_BG["year_quiet"])
BAD_EN = year_map("Strongest month:", "Quiet month:")
verify = reports._verify_for(profile, STYLE, months)
check("a year map marked in Bulgarian is accepted",
      verify(("shopping",), {"shopping": GOOD_BG}) is None,
      str(verify(("shopping",), {"shopping": GOOD_BG})))
check("  and the same map marked in English is refused",
      verify(("shopping",), {"shopping": BAD_EN}) is not None)

print("\n--- compatibility: the same twelve labels, the same classical table ---")
table = profile["compatibility"]
check("the table is zodiac-bg's, keyed on this grid's twelve labels",
      table is reports.COMPATIBILITY_BG
      and sorted(table) == sorted(i["label"] for i in sign_images))
check("  and every answer in it is one of the twelve",
      all(a in table and b in table and c in table
          for (a, b), c in table.values()))
choices = []
for step in steps:
    if step["id"] == "sign":
        choices.append("sign_virgo")
    else:
        choices.append(step["pairs"][0]["images"][0]["id"])
read = reports._sign(cfg, choices)
check("the sign step reads back a Bulgarian label",
      (read or {}).get("label") == "Дева", str(read))
block = reports._compat_block(cfg, choices, table)
check("  and the compatibility block names its three signs in Bulgarian",
      block and "Телец" in block and "Козирог" in block
      and "Стрелец" in block and "Virgo" not in block,
      (block or "")[:120])
scores = {"fire": 6, "sun": 5, "bold": 4, "earth": 2}
prompt = reports._section_prompt(STYLE, NAME, scores, "materials", cfg=cfg,
                                 choices=choices, funnel_slug=SLUG,
                                 months=months)
check("a materials prompt for this funnel is built on the love shape",
      "HOW TO KEEP IT ALIVE" in prompt and "Телец" in prompt
      and reports.LOVE_BG_JSON_RULE in prompt
      and prompt.endswith('{"materials": {...}}.')
      and "THEIR PATTERN IN RELATIONSHIPS" not in prompt)
check("  it hands over the reader's sign, the love purpose and the subtype",
      "this reader's sign is Дева" in prompt
      and "love and relationships" in prompt
      and "name this report is written to" in prompt)
year_prompt = reports._section_prompt(STYLE, NAME, scores, "shopping",
                                      cfg=cfg, choices=choices,
                                      funnel_slug=SLUG, months=months)
check("  the year prompt lists these twelve months and the Bulgarian marks",
      all(label in year_prompt for label in months)
      and reports.RENDER_WORDS_BG["year_strong"] in year_prompt
      and "Strongest month:" not in year_prompt)
cached = reports._cached_prompt(STYLE, NAME, ("palette",), SLUG)
check("  and the cached palette prompt is the love one, with the four "
      "colours named",
      "the way this person loves" in cached
      and all(c["name"] in cached
              for c in STYLE["reveals"]["palette"]["colors"]))


def love(*combos):
    verdicts = ["works", "works", "avoid", "avoid"]
    return {"materials": {
        "intro": "x" * 40, "rule": "r" * 40,
        "pairs": [{"combo": c, "verdict": v, "why": "y" * 40}
                  for c, v in zip(combos, verdicts)]}}


check("a section naming one sign twice is refused, in Bulgarian names",
      verify(("materials",),
             love("Дева + Телец", "Дева + Козирог", "Дева + Стрелец",
                  "Дева + Стрелец")) is not None
      and verify(("materials",),
                 love("Дева + Телец", "Дева + Козирог", "Дева + Стрелец",
                      "Дева + Овен")) is None)
check("  and the love stub passes it",
      verify(("materials",), {"materials": reports._fill(
          profile["stubs"]["materials"], NAME)}) is None)

print("\n--- the mail and the PDF are this product's Bulgarian ---")
MAIL = profile["mail"]
check("the mail is its own copy, chosen by the profile",
      MAIL is reports.COPY_LOVE_BG
      and reports._email_copy({"funnel": SLUG}) is MAIL
      and MAIL is not reports.COPY_ZODIAC_BG)
check("  with the same keys as zodiac-bg's, all Bulgarian",
      sorted(MAIL) == sorted(reports.COPY_ZODIAC_BG)
      and all(re.search(r"[Ѐ-ӿ]", v) for v in MAIL.values()))
check("  the subject and the body say love, and take the archetype",
      "любовен" in MAIL["subject"] and "любовен" in MAIL["body"]
      and MAIL["subject"].count("%s") == 1 and MAIL["body"].count("%s") == 1
      and MAIL["subject"].endswith("— Mazzin"))
check("  the body names what the paywall sold",
      "дванадесетте зодии" in MAIL["body"] and "петте сили" in MAIL["body"]
      and "картата на сърцето" in MAIL["body"])
check("  the kicker over it is the page's own",
      profile["mail_kicker"] == cfg["result_copy"]["kicker"]
      == "ТВОЯТ ЛЮБОВЕН ПРОФИЛ"
      and profile["mail_cross_fallback"] == "Пълният ти любовен профил")
check("  and the button is the Bulgarian one",
      profile["mail_link"] is reports.ZODIAC_EMAIL_LINK_BG
      and "Отвори профила си онлайн" in profile["mail_link"])
WORDS = profile["words"]
check("the PDF is filed as a love document",
      WORDS["pdf_filename"] == "mazzin-%s-lyubov.pdf"
      and (WORDS["pdf_filename"] % reports._slug(NAME)).endswith("-lyubov.pdf")
      and profile["pdf_lang"] == "bg")
check("  its words are zodiac-bg's, with the two headings said for the heart",
      {k: v for k, v in WORDS.items()
       if k not in ("splurge", "save", "pdf_filename")}
      == {k: v for k, v in reports.RENDER_WORDS_BG.items()
          if k not in ("splurge", "save", "pdf_filename")}
      and WORDS["splurge"] == "Вложи сърце тук"
      and WORDS["save"] == "Пази сърцето си"
      and reports._words(profile) is WORDS)
check("  the cover, the strip, the sheet and the note are zodiac-bg's",
      profile["pdf_cover"] is reports._zodiac_cover
      and profile["pdf_elements"] is reports.PDF_ELEMENTS_BG
      and profile["pdf_css"] is ZBG["pdf_css"]
      and profile["pdf_note"] == ZBG["pdf_note"]
      and profile["pdf_logo"] == "brand/logo-dark.svg")
check("  and the lead says love", profile["pdf_lead"] == "Твоят личен любовен "
      "профил" and profile["pdf_lead"] != ZBG["pdf_lead"])
check("the verify hooks are the zodiac palette checks",
      profile["verify"] is reports.ZODIAC_VERIFY)

print("\n--- the reader's grammatical gender, on two sections ---")
# The step that asks is the three-up after the sign: three cards, one tag
# each, no scoring weight. The tag rides in `choices` like every other tap
# and reaches the two personal sections as one instruction line.
check("the tags and the two sections are declared on the profile alone",
      reports.GENDER_TAGS == {"gender_female": "feminine",
                              "gender_male": "masculine",
                              "gender_unsaid": None}
      and reports.GENDER_SECTIONS == ("dna", "materials")
      and profile["personal_note"] is reports._love_bg_gender_note
      and sorted(s for s, pr in reports.PROFILES.items()
                 if pr.get("personal_note"))
      == ["love-zodiac-bg", "love-zodiac-bg-test"])
check("  and _section_prompt asks the profile for it, once, on the personal "
      "sections",
      REPORTS_SRC.count('profile.get("personal_note")') == 1)
_gendered = cfg
_gstyle = reports._style(_gendered, "radiant_fire")


def gendered_choices(pick):
    return ["sign_virgo" if s["id"] == "sign"
            else pick if s["id"] == "gender"
            else s["pairs"][0]["images"][0]["id"]
            for s in _gendered["swipe"]["steps"]]


def gender_prompt(pick, section):
    return reports._section_prompt(
        _gstyle, NAME, scores, section, cfg=_gendered,
        choices=gendered_choices(pick), funnel_slug=SLUG, months=months)


FEM, MASC = "FEMININE grammatical gender", "MASCULINE grammatical gender"
for section in ("dna", "materials"):
    check("  %-9s for a woman is addressed in the feminine" % section,
          FEM in gender_prompt("g01", section)
          and "уморена, готова, сама, влюбена" in gender_prompt("g01", section)
          and MASC not in gender_prompt("g01", section))
    check("  %-9s for a man in the masculine" % section,
          MASC in gender_prompt("g02", section)
          and "уморен, готов, сам, влюбен" in gender_prompt("g02", section)
          and FEM not in gender_prompt("g02", section))
    check("  %-9s unsaid stays the neutral default" % section,
          FEM not in gender_prompt("g03", section)
          and MASC not in gender_prompt("g03", section)
          and "gender" not in gender_prompt("g03", section).lower())
check("  the year map never carries it",
      all(FEM not in gender_prompt(g, "shopping")
          and MASC not in gender_prompt(g, "shopping")
          for g in ("g01", "g02", "g03")))
_no_answer = [c for c in gendered_choices("g03") if c not in GENDER_IDS]
check("  and a walk that never answered is the prompt it was",
      not any(w in reports._section_prompt(
                  _gstyle, NAME, scores, section, cfg=cfg,
                  choices=_no_answer, funnel_slug=SLUG, months=months)
              for section in ("dna", "materials") for w in (FEM, MASC)))
check("  the line keeps the other person unnamed either way",
      all("партньорът, човекът до теб, другият" in line
          and "уморен(а)" in line
          for line in reports.LOVE_BG_GENDER_LINE.values()))
GENDER_WORDS = re.compile(r"feminine|masculine|gender|женски|мъжки|уморена|"
                          r"\bwoman\b|\bman\b", re.I)
check("no cached-section prompt mentions gender",
      not [s for s in profile["cached"]
           if GENDER_WORDS.search(reports._cached_prompt(STYLE, NAME, (s,),
                                                          SLUG))])
check("  nor any cached shape, nor any stub",
      not [s for s in profile["cached"] if GENDER_WORDS.search(SPEC[s])]
      and not [s[:30] for k, s in profile_strings()
               if k == "stubs" and GENDER_WORDS.search(s)])
check("  and the twin reads the same line",
      reports._profile(SLUG + "-test")["personal_note"]
      is profile["personal_note"])

print("\n--- and the neighbours are untouched ---")
check("funnels/zodiac-bg.json is still zodiac-bg, byte for byte with static/",
      zbg["slug"] == "zodiac-bg" and zbg["funnel_id"] == "zodiac_bg_v1"
      and ZBG_RAW == open(os.path.join(ROOT, "static/funnels/zodiac-bg.json"),
                          encoding="utf-8").read())
check("  still eighteen steps", len(zbg["swipe"]["steps"]) == 18)
check("  and its walk is not this walk",
      [s["id"] for s in zbg["swipe"]["steps"]] != [s["id"] for s in steps])
check("no piece of zodiac-bg copy was carried over unchanged",
      not [p for p, v in STRINGS
           if p in ZBG_STRINGS and v == ZBG_STRINGS[p]
           and not machine(p)
           and p.split("/")[-1] in ("question", "label", "line", "blurb",
                                    "promise", "spec", "hook", "teaser_line",
                                    "headline", "body", "fix", "setup",
                                    "trigger", "name", "title", "preview")
           and not p.startswith("/swipe/steps/1/")
           # The sale label is pinned by the brief and asserted verbatim above.
           and p != "/sale/label"],
      str([p for p, v in STRINGS
           if p in ZBG_STRINGS and v == ZBG_STRINGS[p] and not machine(p)
           and p.split("/")[-1] in ("question", "label", "line", "blurb",
                                    "promise", "spec", "hook", "teaser_line",
                                    "headline", "body", "fix", "setup",
                                    "trigger", "name", "title", "preview")
           and not p.startswith("/swipe/steps/1/")
           and p != "/sale/label"][:5]))
check("the funnels directory and its static copy agree",
      sorted(os.listdir(os.path.join(ROOT, "static/funnels")))
      == sorted(os.listdir(os.path.join(ROOT, "funnels"))))

print("\n%d checks, %d failed" % (checks[0], len(fails)))
for f in fails:
    print("  FAIL " + f)
for n in notes:
    print("  NOTE " + n)
sys.exit(1 if fails else 0)
