#!/usr/bin/env python3
"""Integrity checks over funnels/brain.json — the Brain Age Challenge.

/brain is the first funnel that is a game rather than a quiz. Every other one
asks what somebody likes, where any answer is as good as any other; this one
asks what was on the screen three seconds ago, and there is a right answer.
That changes what a config check has to be, because most of what can go wrong
here is not a typo — it is a round that cannot be won.

So this file checks the game as well as the shape:

  * A flash screen stands in front of every round that needs one, laid out on
    the same grid the round itself will draw, and held for a beat inside the
    range the engine will actually honour.
  * The card a memory round calls the seen one is a file that was genuinely on
    its flash, and the three decoys were genuinely not. A round whose "right"
    answer was never shown is a round nobody can pass.
  * The slot a spatial round scores as the hit is the slot whose box was open
    on the flash. Those steps deal unshuffled precisely so that this can be
    true, so the shuffle flag is checked with it rather than apart from it.
  * Every scored round has exactly one hit and the rest misses, all of one
    domain, sixteen rounds in all — which is the denominator the brain age is
    computed against and the one number the reader is shown.

And the arithmetic itself, walked rather than described: the four brain types
each have to win a run that hits only their own domain, a run that hits
everything has to score the base, and a run that hits nothing has to land on
the formula's ceiling with the clamp still slack.

v2, after the live review, is mostly about time. Every flash now counts the
reader in and holds five seconds; the four spatial rounds close the lid and
shuffle the boxes, faster and more often each round; the four focus rounds
answer themselves if nobody answers them. So the checks below walk the shuffle
rather than reading the config's word for where it lands — the swaps are
applied here, in order, exactly as engine.js applies them, and the slot they
land the object on has to be the slot the step scores. A config that stated
both could state them differently; this one cannot.

The result page is the minimal layout, named outright the way zodiac-ro and
zodiac-bg name theirs, which is why this funnel is the one key short of
persona's set: there is no arm to assign, one price and one button. The price
is five dollars with a launch offer under it, and the offer is checked through
payments._effective_price rather than by reading the block — what the reader
is charged is decided there and nowhere else.

Two deviations from the brief this funnel was written to, both deliberate and
both checked here:

  * The first report section is titled "Your Brain Profile", not "Your
    Cognitive Profile". "Cognitive" is on the banned list two paragraphs above
    the title in the same brief, and the ban is the rule that matters: this is
    a game, and a game does not borrow a clinical word for its chapter
    headings.
  * "An all-miss run scores max" is not reachable from the stated table. Base
    22 plus 3.5 for each of 16 misses is 78, and the ceiling is 80, so the
    clamp never bites. Asserted as the formula's own ceiling instead, with the
    clamp checked for slack, because the alternative was to change one of the
    numbers the brief fixed.

No database, no network, no key. Everything is read off disk.

    python3 tests/test_brain_check.py
"""
import ast
import datetime
import hashlib
import json
import os
import re
import sys

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, REPO)
ROOT = REPO

fails = []
checks = [0]


def check(label, ok, detail=""):
    checks[0] += 1
    if not ok:
        fails.append("%s %s" % (label, detail))
    print("  %-64s %s%s" % (label, "ok" if ok else "FAIL",
                            ("  " + str(detail)) if detail and not ok else ""))


PATH = os.path.join(ROOT, "funnels/brain.json")
RAW = open(PATH, encoding="utf-8").read()
cfg = json.loads(RAW)
STATIC = os.path.join(ROOT, "static/funnels/brain.json")
GALLERY = os.path.join(ROOT, "static/galleries/brain")

ENGINE = open(os.path.join(ROOT, "static/js/engine.js"),
              encoding="utf-8").read()
MODULE = open(os.path.join(ROOT, "static/js/result_brain.js"),
              encoding="utf-8").read()
RESULT_CSS = open(os.path.join(ROOT, "static/css/result_brain.css"),
                  encoding="utf-8").read()
# Five seconds is the beat this funnel settled on after the live review:
# every flash holds it, and so does every clock on a step.
FLASH_MS = 5000

steps = cfg["swipe"]["steps"]
by_id = {s["id"]: s for s in steps}
mids = cfg["interstitials"]
mid_by_after = {}
for entry in mids:
    mid_by_after.setdefault(entry["after_step"], []).append(entry)

# The one table that decides what a grid is. Read out of engine.js rather than
# restated, so a format this config names and that file has never heard of is a
# failure here rather than a step that silently draws as a pair.
GRID_SIZE = {name: int(size) for name, size in re.findall(
    r"(\w+): (\d+)",
    re.search(r"var GRID_SIZE = \{([^}]*)\}", ENGINE).group(1))}

DOMAINS = ("mem", "spa", "chg", "foc")
# Which step of the walk each scored round is, one-based, the way `after_step`
# counts. Steps 1 and 2 are the two service questions and score nothing.
SCORED = {"mem1": ("mem", 3), "mem2": ("mem", 4), "mem3": ("mem", 5),
          "mem4": ("mem", 6),
          "spa1": ("spa", 7), "spa2": ("spa", 8), "spa3": ("spa", 9),
          "spa4": ("spa", 10),
          "chg1": ("chg", 11), "chg2": ("chg", 12), "chg3": ("chg", 13),
          "chg4": ("chg", 14),
          "odd": ("foc", 15), "ink": ("foc", 16), "next": ("foc", 17),
          "count": ("foc", 18)}


def images(step):
    return step["pairs"][0]["images"]


def only(step):
    """The step's single pair. Every round here is one question, once."""
    return step["pairs"][0]


print("--- the file, and its copy on the CDN ---")
check("funnels/brain.json is /brain",
      cfg["slug"] == "brain" and cfg["funnel_id"] == "brain_v1"
      and cfg["locale"] == "en")
check("  its static copy is byte-identical",
      RAW == open(STATIC, encoding="utf-8").read())
check("  it transacts on the test keys", cfg["stripe_mode"] == "test")
# Phase 3 turned this on, and it is what puts `elapsed_ms` and `timed_out` on
# a swipe. engine.js gates both on it and /api/track was taught the two keys
# on the same deploy, so the flag and the validator move together or the
# funnel drops every swipe row it records.
check("  and it records how long each round took",
      cfg.get("track_timing") is True
      and json.load(open(STATIC, encoding="utf-8")).get("track_timing")
      is True,
      str(cfg.get("track_timing")))
check("  at five dollars, less a launch offer",
      cfg["pricing"]["amount_cents"] == 500
      and cfg["pricing"]["currency"] == "usd")
check("  drawing its result with its own module",
      cfg["result_module"] == "/static/js/result_brain.js"
      and cfg["result_css"] == "/static/css/result_brain.css")
check("  which is on disk and registers the two halves engine.js loads",
      "window.MazzinResult = { render: render, delivered: delivered };"
      in MODULE
      and os.path.exists(os.path.join(ROOT, "static/css/result_brain.css")))
check("  and it is the only file that writes the button's label",
      MODULE.count("cfg.checkout.cta_label =") == 1)
check("the funnels directory and its static copy agree",
      sorted(os.listdir(os.path.join(ROOT, "funnels")))
      == sorted(os.listdir(os.path.join(ROOT, "static/funnels"))))
# `paywall_variants` is the one key of persona's this funnel deliberately does
# not carry. The minimal layout is named outright here, the way zodiac-ro and
# zodiac-bg name theirs, so there is no arm to assign and no second offer to
# write: one page, one price, one button. The mechanism is still in the module
# and a config edit turns it back on.
PERSONA = json.load(open(os.path.join(ROOT, "funnels/persona.json"),
                         encoding="utf-8"))
missing = [k for k in PERSONA if k not in cfg]
check("it carries every key the newest funnel carries but one",
      missing == ["paywall_variants"], str(missing))
check("  and no other funnel that names a layout carries that key either",
      not [n for n in ("zodiac-ro", "zodiac-bg")
           if json.load(open(os.path.join(ROOT, "funnels/%s.json" % n),
                             encoding="utf-8")).get("paywall_variants")])
check("  plus the two it brought with it",
      "brain_age" in cfg and "result_template" in cfg)
check("the art script that drew the gallery is committed with it",
      os.path.exists(os.path.join(ROOT, "scripts/gen_brain_art.py")))

print("\n--- eighteen rounds, and what each one draws ---")
check("eighteen steps", len(steps) == 18, str(len(steps)))
check("  and the counter agrees with them",
      cfg["swipe"]["pairs_count"] == len(steps),
      str(cfg["swipe"]["pairs_count"]))
check("  every step id is its own", len(by_id) == len(steps))
# v11: a scored step carries three versions of itself and one is drawn per
# run, so it lists three pairs and a pool that says which flash goes with
# which. The two warm-up steps are one pair as they always were.
check("  every step asks one question, in one version or three",
      all(len(s["pairs"]) in (1, 3) for s in steps),
      str([s["id"] for s in steps if len(s["pairs"]) not in (1, 3)]))
check("  and names it", all(s.get("question") for s in steps))
for step in steps:
    fmt = step.get("format")
    size = GRID_SIZE.get(fmt)
    check("  %-6s draws a %s the engine knows" % (step["id"], fmt),
          size is not None, str(fmt))
    check("    with the %s cards that grid lays out"
          % (size if size else "?"),
          size is not None and len(images(step)) == size,
          "%d cards" % len(images(step)))
check("every image id on the funnel is unique",
      len({i["id"] for s in steps for i in images(s)})
      == sum(len(images(s)) for s in steps))
# v8. Not one card on this funnel shows a word any more: the art carries the
# whole question, and the tap is answered with a mark rather than a name. The
# labels stay in the config all the same — they are what a screen reader hears
# ("Choose {label}"), and what this suite validates every card by. They are
# simply never drawn.
check("the walk answers a tap with a mark rather than a word",
      cfg["swipe"]["label_mode"] == "check",
      str(cfg["swipe"].get("label_mode")))
check("  and no step overrides that with a mode of its own",
      not [s["id"] for s in steps if "label_mode" in s],
      str([s["id"] for s in steps if "label_mode" in s]))
check("every card still carries a label, for the reader who hears the page",
      all(i.get("label") for s in steps for i in images(s)),
      str([i["id"] for s in steps for i in images(s) if not i.get("label")]))
check("  including the four the pattern round holds up, which are the only "
      "frames a reader is asked to hold in their head",
      all(f.get("label") for e in cfg["interstitials"]
          if e["after_step"] == 16
          for f in ((e.get("flash") or {}).get("images") or [])))
check("the four rounds that must not shuffle do not",
      all(by_id[sid].get("shuffle") is False
          for sid in ("spa1", "spa2", "spa3", "spa4",
                      "chg1", "chg2", "chg3", "chg4")),
      str([sid for sid in SCORED if by_id[sid].get("shuffle") is not False]))
check("  and neither do the two whose cards have an order of their own",
      by_id["age"].get("shuffle") is False
      and by_id["count"].get("shuffle") is False)

print("\n--- the gallery ---")
paths = []


def walk(node):
    if isinstance(node, dict):
        for key, value in node.items():
            if key == "img" and isinstance(value, str):
                paths.append(value)
            else:
                walk(value)
    elif isinstance(node, list):
        for value in node:
            walk(value)


walk(cfg)
missing = [p for p in sorted(set(paths))
           if not os.path.exists(os.path.join(ROOT, p.lstrip("/")))]
check("every image the config names is on disk", not missing, str(missing))
check("  and all of them are this funnel's own",
      all(p.startswith("/static/galleries/brain/") for p in paths),
      str(sorted({p for p in paths
                  if not p.startswith("/static/galleries/brain/")})))
heavy = [(p, os.path.getsize(os.path.join(ROOT, p.lstrip("/"))))
         for p in sorted(set(paths))
         if os.path.getsize(os.path.join(ROOT, p.lstrip("/"))) >= 12 * 1024]
check("every one of them is under twelve kilobytes", not heavy, str(heavy))
check("  including the card the link preview uses",
      os.path.getsize(os.path.join(GALLERY, "og.webp")) < 12 * 1024)
# The two files nobody has to answer a question about: the link preview, and
# the illustration on the intro card. Neither is a game card, so neither is
# held to the ceiling a game card is held to — a card is one of a pair the
# reader is comparing under a clock, and what that ceiling buys is both of
# them decoded before the clock starts.
LOOSE = ("og.webp", "brain_intro.webp")
check("nothing in the gallery is unreferenced",
      not [n for n in sorted(os.listdir(GALLERY))
           if "/static/galleries/brain/" + n not in set(paths)
           and n not in LOOSE],
      str([n for n in sorted(os.listdir(GALLERY))
           if "/static/galleries/brain/" + n not in set(paths)
           and n not in LOOSE]))

print("\n--- v7: the picture on the intro card ---")
INTRO_ART = "/static/galleries/brain/brain_intro.webp"
check("the intro card names a picture",
      (cfg.get("intro") or {}).get("image") == INTRO_ART,
      str((cfg.get("intro") or {}).get("image")))
check("  and it is on disk",
      os.path.exists(os.path.join(ROOT, INTRO_ART.lstrip("/"))))
check("  under twenty-five kilobytes",
      os.path.getsize(os.path.join(ROOT, INTRO_ART.lstrip("/"))) < 25 * 1024,
      str(os.path.getsize(os.path.join(ROOT, INTRO_ART.lstrip("/")))))
GEN = open(os.path.join(ROOT, "scripts/gen_brain_art.py"),
           encoding="utf-8").read()
check("  and the generator is what draws it",
      "def brain_intro(" in GEN
      and 'put(brain_intro(), "brain_intro"' in GEN)
# v11 draws the picture the funnel is actually about: a head in profile with
# the brain inside it, in line art. What is checked is the discipline of it —
# one weight of line, round caps and joins, one family of folds, no fills but
# the tint, and nothing crossing anything.
check("it is a head in profile with the brain inside it",
      "HEAD_FACE = [" in GEN and "HEAD_BACK = [" in GEN
      and "HEAD_BRAIN = [" in GEN)
check("  drawn in two strokes, so the neck runs off rather than closing",
      "for spec in (HEAD_FACE, HEAD_BACK):" in GEN
      and "(.466, 1.04)" in GEN and "(.752, 1.04)" in GEN)
check("  at one weight, with round caps and round joins",
      "INTRO_STROKE = 0.019" in GEN
      and "def stroke_path(" in GEN
      and "d.ellipse([x - r, y - r, x + r, y + r], fill=colour)" in GEN
      and GEN.count("width = max(3, int(INTRO_STROKE * w))") == 1)
check("  and the only fill in the picture is the tint inside the skull",
      "card.d.polygon(brain, fill=INTRO_TINT)" in GEN
      and "INTRO_TINT = (230, 241, 251)" in GEN
      and GEN.count("fill=INTRO_TINT") == 1)
check("the folds are one family of eight to twelve ribbons",
      "RIBBON_N = 8" in GEN and 8 <= 8 <= 12)
check("  every one of them unbroken, and none crossing another",
      "def ribbons(" in GEN
      and "bend = RIBBON_BEND * (1 if k % 2 == 0 else -1)" in GEN
      and "RIBBON_ARCH" in GEN)
check("  and clipped to the skull, so none dangles below it",
      "ImageChops.multiply(layer, inside)" in GEN
      and 'ImageDraw.Draw(inside).polygon(brain, fill=255)' in GEN)
check("the two colours are the ones the review named",
      "INTRO_FACE = (24, 95, 165)" in GEN
      and "INTRO_FOLD = (55, 138, 221)" in GEN)
check("it is drawn facing both ways, and one of them ships",
      'INTRO_FACING = "left"' in GEN
      and 'mirror = facing == "right"' in GEN)

print("\n--- v7: a memorise screen carries the round's own pill ---")
flashes = [e for e in cfg["interstitials"] if e.get("template") == "flash"]
check("every flash names a kicker",
      flashes and all(e.get("kicker") for e in flashes), str(len(flashes)))
check("  and it is the kicker of the step it opens, counter and all",
      all(e["kicker"] == steps[e["after_step"]]["kicker"] for e in flashes),
      str([(e["after_step"], e["kicker"]) for e in flashes
           if e["kicker"] != steps[e["after_step"]]["kicker"]]))
check("  so a flash before the third memory step still reads 1/4 of its round",
      [e["kicker"] for e in flashes if e["after_step"] == 4]
      == ["ROUND 1 · MEMORY · 3/4"],
      str([e["kicker"] for e in flashes if e["after_step"] == 4]))
check("the screens between rounds keep the line they had",
      [e.get("kicker") for e in cfg["interstitials"]
       if e.get("template") != "flash"] == ["Round 4 · Focus", "Computing"],
      str([e.get("kicker") for e in cfg["interstitials"]
           if e.get("template") != "flash"]))

print("\n--- the four types, won the way engine.js wins them ---")


def winner(scores):
    """computeWinner, exactly: the floor is -inf and ties go to the first."""
    best, best_score = cfg["styles"][0]["id"], float("-inf")
    for style in cfg["styles"]:
        total = sum(scores.get(t, 0) for t in style["tags"])
        if total > best_score:
            best, best_score = style["id"], total
    return best


check("four brain types", len(cfg["styles"]) == 4,
      str([s["id"] for s in cfg["styles"]]))
check("  each scored on one domain's hit tag, and no two on the same",
      sorted(s["tags"][0] for s in cfg["styles"])
      == sorted(d + "_hit" for d in DOMAINS),
      str([s["tags"] for s in cfg["styles"]]))
check("  each named, blurbed, and carrying the reveals a report is built on",
      all(s.get("name") and s.get("blurb")
          and set(s.get("reveals") or {})
          >= {"dna", "materials", "mistakes", "shopping", "mistake_one"}
          for s in cfg["styles"]))
for style in cfg["styles"]:
    domain = style["tags"][0].split("_")[0]
    check("  a run that hits only %s wins %s" % (domain, style["id"]),
          winner({domain + "_hit": 4}) == style["id"],
          winner({domain + "_hit": 4}))
check("  and a run that hits nothing still resolves to a type",
      winner({}) in [s["id"] for s in cfg["styles"]])

print("\n--- the brain age, walked ---")
block = cfg["brain_age"]
check("the table is the one the module and the report both read",
      set(block) == {"base", "per_miss", "min", "max", "scored", "domains",
                     "age_mid", "score"}, str(sorted(block)))
check("  naming all four rounds", sorted(block["domains"]) == sorted(DOMAINS),
      str(sorted(block["domains"])))


def brain_age(misses):
    raw = round(block["base"] + block["per_miss"] * misses)
    return max(block["min"], min(block["max"], raw))


check("a run that hits every round scores the base",
      brain_age(0) == block["base"], str(brain_age(0)))
check("  and the floor never bites at that end",
      block["base"] >= block["min"])
# A miss costs four years now rather than three and a half, which puts
# sixteen of them past the ceiling: the clamp is what a reader who answers
# nothing actually sees, and it is checked as the thing it now is.
ceiling = block["base"] + block["per_miss"] * block["scored"]
check("a run that misses every round scores the clamp, not past it",
      brain_age(block["scored"]) == block["max"], str(brain_age(16)))
check("  which is where the formula would have gone over it",
      ceiling > block["max"],
      "%s vs %s" % (ceiling, block["max"]))
check("  and a miss costs four years",
      block["per_miss"] == 4.0, str(block["per_miss"]))
check("  every score in between is inside the clamp",
      all(block["min"] <= brain_age(m) <= block["max"]
          for m in range(block["scored"] + 1)))
check("the module reads the table rather than restating it",
      "cfg && cfg.brain_age" in MODULE
      and "block.per_miss" in MODULE and "block.base" in MODULE)
check("  and counts misses off the hits, so an unanswered round is a miss",
      "var misses = Math.max(0, scored - hits);" in MODULE)

print("\n--- the personal beat, and the engine axes behind it ---")
declared = set(re.findall(r"(\w+):\s*\w+_AXIS",
                          re.search(r"var AXES = \{([^}]*)\}",
                                    ENGINE, re.S).group(1)))
check("engine.js declares the four domains this funnel scores on",
      set(DOMAINS) <= declared, str(sorted(declared)))
beat = mid_by_after[14][0]
check("the beat after the change rounds reads them back",
      beat["template"] == "confirm"
      and beat["echo_steps"] == ["chg1", "chg2", "chg3", "chg4"])
check("  keyed on an axis the engine knows",
      beat["personal"]["axis"] in declared, beat["personal"]["axis"])
check("  with a line for each of that axis's two tags",
      sorted(beat["personal"]["lines"]) == ["chg_hit", "chg_miss"])
check("  and every one of those tags is one a card can actually carry",
      set(beat["personal"]["lines"])
      <= {t for s in steps for i in images(s) for t in i["tags"]})
last = mid_by_after[18][0]
check("the last beat closes the walk", last["template"] == "almost")
for at in (14, 18):
    entry = mid_by_after[at][0]
    check("  the beat on %d keeps its kicker, its line and its button" % at,
          entry.get("kicker") and entry.get("line") and entry.get("cta"))
check("both of them advance on their own, like the flashes do",
      all(isinstance(mid_by_after[at][0].get("auto_advance_ms"), int)
          for at in (14, 18)))
check("the analysing screen draws the run back",
      cfg["analyzing_echo"] is True)

print("\n--- v2: every round is counted in, timed, or shuffled ---")
check("every flash counts the reader in, except the four that shuffle",
      sorted(e["after_step"] for e in mids if e.get("prepare"))
      == [2, 3, 4, 5, 10, 11, 12, 13, 16, 17],
      str(sorted(e["after_step"] for e in mids if e.get("prepare"))))
for entry in mids:
    if not entry.get("prepare"):
        continue
    rule = entry["prepare"]
    check("  beat %-2d counts three, in the reader's own words"
          % entry["after_step"],
          rule.get("count") == 3 and rule.get("line") == "Prepare to memorize",
          str(rule))
check("a reveal and a count-in are never on the same screen",
      not [e for e in mids if e.get("prepare") and e.get("reveal")])

print("\n--- which steps name their cards, and when ---")
# v8. None of them, ever. The eleven overrides this used to walk were eleven
# answers to "should this round say what its cards are", and the answer is now
# the same for all eighteen: the art says it, and the tap is answered with a
# mark. What is left to check is that nothing reintroduces a word.
check("no step names its cards",
      cfg["swipe"]["label_mode"] == "check"
      and not [s["id"] for s in steps if s.get("label_mode")],
      str([s["id"] for s in steps if s.get("label_mode")]))
check("  and the mode is one the engine knows",
      cfg["swipe"]["label_mode"] in ("none", "on_tap", "badge", "check"))
check("the mood round asks the question the review asked for",
      by_id["mood"]["question"] == "How would you rate your brain right now?")

print("\n--- the launch offer ---")
import payments                                             # noqa: E402
import tracking                                             # noqa: E402
sale = cfg["sale"]
check("the block is the shape payments.py reads",
      sorted(sale) == ["active", "ends", "label", "price_cents",
                       "regular_price_cents"], str(sorted(sale)))
check("  it is live, and cheaper than the price it strikes through",
      sale["active"] is True and sale["price_cents"] == 199
      and sale["price_cents"] < cfg["pricing"]["amount_cents"])
check("  and the struck figure is the price this funnel actually charges",
      sale["regular_price_cents"] == cfg["pricing"]["amount_cents"],
      "%s vs %s" % (sale["regular_price_cents"],
                    cfg["pricing"]["amount_cents"]))
BEFORE = datetime.datetime(2026, 6, 1, tzinfo=datetime.timezone.utc)
AFTER = datetime.datetime(2027, 6, 1, tzinfo=datetime.timezone.utc)
check("payments.py charges the offer price while it runs",
      payments._effective_price(cfg, BEFORE) == (199, sale),
      str(payments._effective_price(cfg, BEFORE)[0]))
check("  and the regular price the day after it ends, with nothing deployed",
      payments._effective_price(cfg, AFTER) == (500, None),
      str(payments._effective_price(cfg, AFTER)))
check("  the end is an instant with an offset on it, not a naive date",
      payments._sale_ends(sale["ends"]) is not None, sale["ends"])
check("the offer has a name and no countdown",
      sale["label"] == "Launch Offer")

print("\n--- the result page: the minimal layout, named outright ---")
check("the funnel names the layout rather than testing for it",
      cfg.get("result_template") == "minimal"
      and "paywall_variants" not in cfg,
      str(cfg.get("result_template")))
check("  and the module reads that name",
      '(ctx.cfg && ctx.cfg.result_template)' in MODULE
      and 'template(ctx) === "minimal"' in MODULE)
profile = cfg["result_copy"]["profile"]
check("the copy the layout needs is all declared",
      all(k in profile for k in ("chips", "rarity_card", "offer_personal",
                                 "offer_personal_elite", "offer_hero_kicker",
                                 "offer_hero_line", "offer_cards",
                                 "offer_chips")),
      str(sorted(profile)))
check("  four chips, one token each, one per round",
      profile["chips"] == ["{mem}", "{spa}", "{chg}", "{foc}"],
      str(profile["chips"]))
check("  the type card carries a frame and a line under it",
      all(profile["rarity_card"].get(k) for k in ("lead", "tail", "note")),
      str(profile["rarity_card"]))
check("the struck price is read out as well as drawn",
      "price_regular_aria" in cfg["result_copy"]
      and "{price}" in cfg["result_copy"]["price_regular_aria"])
check("the module draws the sale beside the price it charges",
      "ctx.sale && ctx.priceRegular" in MODULE
      and 'elm("span", "br-price-was", ctx.priceRegular)' in MODULE
      and 'elm("p", "br-sale", ctx.sale.label)' in MODULE)
check("  and the stylesheet strikes it through on this layout",
      ".result-module.is-minimal .br-price-was::after {" in RESULT_CSS)
# v11 replaced the ticked list on the offer with a hero tile and four
# benefit cards; the bars and the locked rows are still what the lean arm
# drops from the page above it.
check("the layout drops the bars and the locked rows for chips and a card",
      "if (!lean) root.appendChild(bars(ctx, copy, data));" in MODULE
      and "if (!lean) root.appendChild(path(ctx, copy));" in MODULE
      and "if (grid) card.appendChild(grid);" in MODULE)
check("  and the delivered page opens as the page they paid on",
      'root.classList.toggle("is-minimal", lean);' in MODULE
      and MODULE.count('root.classList.toggle("is-minimal", lean);') == 2)

print("\n--- v3: the age cards read as cards, and the number sits on the tree ---")
ART = open(os.path.join(ROOT, "scripts/gen_brain_art.py"),
           encoding="utf-8").read()


def art_number(name):
    """One of the generator's own constants, read off its source.

    A trailing comment is allowed for: `GROUND` carries one, and a check that
    broke when somebody explained a value would be a check on the comment.
    """
    return float(re.search(r"^%s = ([\d.]+)\s*(?:#.*)?$" % name,
                           ART, re.M).group(1))


def art_colour(name):
    body = re.search(r"^%s = \(([^)]*)\)\s*(?:#.*)?$" % name,
                     ART, re.M).group(1)
    return tuple(int(v) for v in body.split(","))


# The generator's own constants, read rather than eyeballed off a pixel. What
# a check can say about a drawing is that the numbers it was drawn from are
# the numbers that were asked for; anything measured off the WebP would be a
# check on the encoder.
GROUND = art_colour("GROUND")
PANEL = art_colour("AGE_PANEL_FILL")
check("the age card has a ground of its own",
      PANEL != GROUND, "%s vs %s" % (PANEL, GROUND))
check("  darker than the page it sits on, on every channel",
      all(PANEL[i] < GROUND[i] for i in range(3)), "%s" % (PANEL,))
check("  and far enough off it to read as a surface",
      min(GROUND[i] - PANEL[i] for i in range(3)) >= 8,
      str([GROUND[i] - PANEL[i] for i in range(3)]))
# The tint is the whole of the tile now. A keyline a few pixels inside the
# card's own border and a floor under a tree that is already standing on the
# card were both drawn and both came off after the second phone review: the
# colour was doing the work and the two rules were arguing with it.
check("the tile is the tint and nothing else",
      "AGE_PANEL_EDGE" not in ART and "AGE_GROUND_FILL" not in ART
      and "AGE_PANEL_INSET" not in ART and "AGE_PANEL_RADIUS" not in ART,
      str([n for n in ("AGE_PANEL_EDGE", "AGE_GROUND_FILL",
                       "AGE_PANEL_INSET", "AGE_PANEL_RADIUS") if n in ART]))
check("  so the card draws a ground, a tree and a number, in that order",
      re.search(r"def age_card\(text, stage\):(.*?)\n\n", ART, re.S)
      is not None
      and "rounded_rectangle" not in
      re.search(r"def age_card\(text, stage\):(.*?)\n\n",
                ART, re.S).group(1))
check("the card is drawn on that ground rather than on the page's",
      "Card(ground=AGE_PANEL_FILL)" in ART)

# Where the numeral's feet land, worked out here from the same table the
# generator draws from: the leaves' top on each stage, less the gap.
TREES = ast.literal_eval(
    re.search(r"^TREES = (\{.*?^\})", ART, re.S | re.M).group(1))
SCALE = art_number("TREE_SCALE")
BASE = art_number("AGE_BASE_Y")
GAP = art_number("AGE_NUMERAL_GAP")


def numeral_bottom(stage):
    height, _width, blobs, _roots = TREES[stage]
    top = BASE - height * SCALE
    return min(top + (dy - r) * SCALE for _dx, dy, r in blobs) - GAP


STAGES = ["sprout", "sapling", "young", "full", "broad", "ancient"]
check("the six stages are all in the table", sorted(TREES) == sorted(STAGES),
      str(sorted(TREES)))
check("the sprout's number sits in the lower half of the card",
      0.55 <= numeral_bottom("sprout") <= 0.70,
      "%.3f" % numeral_bottom("sprout"))
check("every other number follows its own canopy up the card",
      [round(numeral_bottom(s), 4) for s in STAGES]
      == sorted((round(numeral_bottom(s), 4) for s in STAGES), reverse=True),
      str([round(numeral_bottom(s), 3) for s in STAGES]))
check("  and none of them is left floating above the leaves",
      0 < GAP <= 0.05, str(GAP))
check("the numeral is bigger than the one that vanished",
      art_number("AGE_NUMERAL_SIZE") >= 90,
      str(art_number("AGE_NUMERAL_SIZE")))
check("  and set on its feet rather than centred on a guess",
      "card.text_above(text, AGE_NUMERAL_SIZE, numeral_bottom(stage))" in ART
      and "def text_above(" in ART)
check("the age step still names nothing — the art carries the bracket",
      not by_id["age"].get("label_mode")
      and cfg["swipe"]["label_mode"] == "check")

print("\n--- v3: nothing on a box but the box ---")
for r in range(1, 5):
    sid = "spa%d" % r
    entry = mid_by_after[SCORED[sid][1] - 1][0]
    check("  the %s flash draws no numbers" % sid,
          not [f for f in entry["flash"]["images"] if f.get("label")],
          str([f.get("label") for f in entry["flash"]["images"]]))
    check("    and the round itself draws none either",
          not by_id[sid].get("label_mode")
          and cfg["swipe"]["label_mode"] == "check",
          str(by_id[sid].get("label_mode")))
check("the open box still carries its object",
      all("box_open_" in
          mid_by_after[SCORED["spa%d" % r][1] - 1][0]["flash"]["images"][
              mid_by_after[SCORED["spa%d" % r][1] - 1][0]["reveal"]
              ["open_slot"]]["img"]
          for r in range(1, 5)))
# v8: it is all eighteen now, off the funnel's own mode, so there is no list
# of six to keep in step with the config any more.
check("the rounds that name nothing include the six that must not",
      cfg["swipe"]["label_mode"] == "check"
      and not [s["id"] for s in steps
               if s["id"] in ("age", "odd", "spa1", "spa2", "spa3", "spa4")
               and s.get("label_mode")])

print("\n--- v3: the strip fills the card it is in ---")
grid = re.search(r"\.br-taps-grid \{(.*?)\n\}", RESULT_CSS, re.S)
check("the strip is a grid, not a wrapping row of fixed cells",
      grid is not None and "display: grid;" in grid.group(1)
      and "display: flex" not in grid.group(1))
check("  six columns, each a share of whatever the card is",
      grid is not None
      and "grid-template-columns: repeat(6, minmax(0, 1fr));" in grid.group(1))
check("  which lays eighteen rounds out in three even rows",
      18 % 6 == 0)
cell = re.search(r"\.br-tap \{(.*?)\n\}", RESULT_CSS, re.S)
check("the cells are square, sized by the track rather than fixed",
      cell is not None and "aspect-ratio: 1 / 1;" in cell.group(1)
      and "width: 46px" not in cell.group(1)
      and "height: 46px" not in cell.group(1))
check("  and one rule covers both pages, so the paid strip matches",
      RESULT_CSS.count(".br-taps-grid {") == 1
      and ".is-delivered .br-taps-grid" not in RESULT_CSS
      and ".is-minimal .br-taps-grid" not in RESULT_CSS)
check("the module draws both strips through the same block",
      MODULE.count("return tapsBlock(copy") == 2
      and MODULE.count("function tapsBlock(") == 1)

print("\n--- v3: the report is a plan, not a reading ---")
FORWARD = ("sharpen", "refresh", "lower")
for style in cfg["styles"]:
    tail = style["blurb"].rstrip().rsplit(". ", 1)[-1]
    check("  %s closes on what lifts it" % style["id"],
          any(w in tail for w in FORWARD), tail[:70])
check("the four chapters are titled the way the offer sells them",
      [s["title"] for s in cfg["report"]["sections"]]
      == ["Your Brain Profile & Your Edge",
          "Your Weakest Round — and the Fastest Way to Lift It",
          "5 Sharp Strengths & 2 Habits Holding You Back",
          "Your 7-Day Brain Refresh Plan"],
      str([s["title"] for s in cfg["report"]["sections"]]))
check("  on the four ids the report machinery keys on, unchanged",
      [s["id"] for s in cfg["report"]["sections"]]
      == ["dna", "materials", "mistakes", "shopping"])
check("the type card ends on what sharpens it",
      any(w in cfg["result_copy"]["profile"]["rarity_card"]["note"].lower()
          for w in FORWARD),
      cfg["result_copy"]["profile"]["rarity_card"]["note"])
delta = cfg["result_copy"]
check("a reader under their age group is told to keep it there",
      "keep it there" in delta["younger_line"], delta["younger_line"])
check("  one on it is told a week of drills moves it",
      "moves it" in delta["level_line"], delta["level_line"])
check("  and one over it is told the number is the easiest to lower",
      "easiest number to lower" in delta["older_line"],
      delta["older_line"])
check("  with nothing anywhere that says something is wrong with them",
      not [t for _at, t in [] ] and "fix that" not in json.dumps(cfg).lower(),
      "fix that")
check("the offer is a refresh rather than a reading",
      cfg["checkout"]["product_name"] == "Your Brain Refresh Report"
      and cfg["checkout"]["cta_label"] == "Reveal my brain age — {price}"
      and cfg["checkout"]["proof_line"] == "Built from your 16 rounds")
check("  and the anchor that was working is still there",
      cfg["checkout"]["commerce"]["price_anchor"]
      == "A puzzle book about nobody in particular costs more"
      and "puzzle book about nobody in particular" in cfg["checkout"]["anchor"])

print("\n--- v4: every step says which round it is ---")
# Derived here rather than copied out of the config: the walk is two warm-up
# questions and then four rounds of four, and where a step sits in that is a
# fact about its position. A step moved without its kicker moving with it is
# what this catches.
ROUNDS = [("WARM-UP", 2), ("ROUND 1 · MEMORY", 4), ("ROUND 2 · SPATIAL", 4),
          ("ROUND 3 · CHANGE", 4), ("ROUND 4 · FOCUS", 4)]
want = []
for name, count in ROUNDS:
    for n in range(1, count + 1):
        want.append("%s · %d/%d" % (name, n, count))
check("the kickers cover the whole walk", len(want) == len(steps))
for step, line in zip(steps, want):
    check("  %-6s is %s" % (step["id"], line), step.get("kicker") == line,
          str(step.get("kicker")))
check("the flashes still name the round they set up",
      all(e.get("kicker") for e in mids if e.get("template") == "flash"))
check("  in the same four words the steps use",
      all(e["kicker"].split(" · ")[1].upper()
          in {r[0].split(" · ")[-1] for r in ROUNDS[1:]}
          for e in mids if e.get("template") == "flash"),
      str(sorted({e["kicker"] for e in mids
                  if e.get("template") == "flash"})))
check("the funnel names what a clock says when it runs out",
      cfg["swipe"].get("timeup_line") == "Time's up",
      str(cfg["swipe"].get("timeup_line")))

print("\n--- v4: the free page argues for lowering the number ---")
def module_body(name):
    """One top-level function's body, the way the engine suites read them."""
    hit = re.search(r"function %s\([^)]*\)\s*\{(.*?)\n  \}" % name,
                    MODULE, re.S)
    return hit.group(1) if hit else ""


check("the type card is not drawn before the money",
      "typeCard(" not in module_body("render")
      and "root.appendChild(typeCard(ctx, copy, lean));"
      in module_body("delivered"))
check("  though the type is still computed, and still on the paid page",
      "ctx.style.name" in MODULE and "function typeCard(" in MODULE)
check("the urgency block sits straight under the number",
      "var push = urge(ctx, copy);" in MODULE
      and MODULE.index("var push = urge(ctx, copy);")
      < MODULE.index("var strip = taps(ctx, copy);"))
# v10. The block used to open on a line that said the same thing three ways,
# by where the reader sat against their age group — which meant printing the
# age delta on the page whose whole job is now to make the age worth paying
# for. The line under the score has already said what the run left on the
# table; those three sentences are the report's.
check("  and no line above the button says anything about an age",
      "br-urge-line" not in MODULE
      and "urge_younger" not in MODULE and "urge_older" not in MODULE
      and "urge_level" not in MODULE)
check("  nor is one left in the config for it to read",
      not [k for k in cfg["result_copy"] if k.startswith("urge")],
      str([k for k in cfg["result_copy"] if k.startswith("urge")]))
check("the control under it moves the page, and takes no money",
      'elm("button", "br-urge-cta"' in MODULE
      and 'card.scrollIntoView({ behavior: "smooth", block: "start" });'
      in MODULE
      and 'var OFFER_ID = "br-offer";' in MODULE
      and "card.id = OFFER_ID;" in MODULE)
check("  it resolves the offer at the tap rather than holding a node",
      "document.getElementById(OFFER_ID)" in MODULE)
check("  it is not the pay button, and does not touch it",
      "ctx.checkout" not in MODULE
      and re.search(r"function urge\(ctx, copy\)(.*?)\n  \}",
                    MODULE, re.S).group(1).count("payButton") == 0)
check("  and it is named in the funnel's own words",
      cfg["result_copy"].get("improve_cta") == "Improve now")
check("  set as the loudest control on the page after the number",
      ".br-urge-cta {" in RESULT_CSS
      and re.search(r"\.br-urge-cta \{[^}]*text-transform: uppercase;",
                    RESULT_CSS, re.S) is not None)
check("the offer leads with the plan rather than with a label",
      cfg["result_copy"]["profile"]["offer_head"]
      == "Your improvement plan — built from your 18 rounds"
      and "{type}" not in cfg["result_copy"]["profile"]["offer_head"],
      cfg["result_copy"]["profile"]["offer_head"])
intro = cfg.get("intro") or {}
check("the funnel carries an intro block",
      sorted(intro) == ["chips", "cta", "foot", "headline", "image", "kicker",
                        "sub"],
      str(sorted(intro)))
check("  named as the thing the ad promised",
      intro.get("kicker") == "BRAIN AGE CHALLENGE"
      and intro.get("headline") == "How old is your brain?")
check("  saying what it is, how long it takes and what comes out of it",
      "18 quick rounds" in intro.get("sub", "")
      and "brain age" in intro.get("sub", "")
      and "lower it" in intro.get("sub", ""), intro.get("sub"))
check("  with its chips and one button",
      len(intro.get("chips") or []) >= 3
      and intro.get("cta") == "START NOW", str(intro.get("chips")))
check("  and the foot line the review asked for",
      intro.get("foot") == "Self-discovery.", str(intro.get("foot")))
check("the rounds are drawn as pills",
      cfg["swipe"].get("round_pill") is True)
check("  and every kicker still splits into a label and a counter",
      all("·" in s["kicker"] for s in steps), str(
          [s["kicker"] for s in steps if "·" not in s["kicker"]]))

print("\n--- v8: the art carries what the labels carried ---")
# Off the generator's own source, never off pixels: what is checked is that
# the words are drawn at all and that they are the four the config names, so
# a mood card cannot quietly lose the only thing that says which one it is.
check("the mood cards draw their word",
      "word_under(card, MOOD_WORDS[name])" in ART
      and "def word_under(" in ART)
MOOD_ART = ast.literal_eval(
    re.search(r"^MOOD_WORDS = (\{.*?\})\n", ART, re.S | re.M).group(1))
check("  and it is the label the config gives that card",
      MOOD_ART == {c["id"]: c["label"] for c in images(by_id["mood"])},
      str(MOOD_ART))
check("  set on its feet under the picture, shrunk until it fits",
      "card.text_above(text, size, bottom)" in ART
      and "box[2] - box[0] <= limit" in ART)
check("  which is why every picture on those cards sits higher than it did",
      "cx, cy = 0.5 * unit, 0.435 * unit" in ART)
# v11 draws one number card per answer any version of the round can offer,
# and the versions are checked against their own scatters further down.
check("the count answers draw their number, and draw it large",
      'put(word(text, 130), "cnt_" + text)' in ART
      and 'for text in sorted({n for v in COUNT_VARIANTS for n in v'
      in ART)
check("the age numerals and the ink words were already in their art",
      "def age_card(" in ART and "AGE_NUMERAL_SIZE" in ART
      and "def word(text, size, colour=INK):" in ART)


print("\n--- v11: sixteen scored rounds, three versions of each ---")
#
# Everything below walks EVERY version of every pooled step rather than the
# one the config happens to list first. A version a run can be given and a
# check never looks at is a version that ships unproved.
import importlib.util as _il                                  # noqa: E402
_spec = _il.spec_from_file_location(
    "gen_brain_art", os.path.join(ROOT, "scripts/gen_brain_art.py"))
GEN = _il.module_from_spec(_spec)
_spec.loader.exec_module(GEN)

POOLED = ["mem1", "mem2", "mem3", "mem4", "spa1", "spa2", "spa3", "spa4",
          "chg1", "chg2", "chg3", "chg4", "odd", "ink", "next", "count"]
DOMAIN_OF = {"mem": "mem", "spa": "spa", "chg": "chg",
             "odd": "foc", "ink": "foc", "next": "foc", "count": "foc"}


def domain_of(sid):
    return DOMAIN_OF.get(sid[:3], DOMAIN_OF.get(sid, "foc"))


def pair_of(step, entry):
    for pair in step["pairs"]:
        if pair["id"] == entry["pair"]:
            return pair
    return None


check("every scored step carries three versions of itself",
      all(len(by_id[sid].get("pool") or []) == 3 for sid in POOLED),
      str([sid for sid in POOLED if len(by_id[sid].get("pool") or []) != 3]))
check("  and no other step carries any",
      not [s["id"] for s in steps if s.get("pool") and s["id"] not in POOLED],
      str([s["id"] for s in steps if s.get("pool")]))
check("  the two warm-up steps are the one version they always were",
      all(len(by_id[sid]["pairs"]) == 1 and "pool" not in by_id[sid]
          for sid in ("age", "mood")))
check("every version names a pair the step actually declares",
      all(pair_of(by_id[sid], entry) is not None
          for sid in POOLED for entry in by_id[sid]["pool"]))
check("  and the three name three different ones",
      all(len({e["pair"] for e in by_id[sid]["pool"]}) == 3
          for sid in POOLED))
check("  so the server, which validates against every pair, accepts them all",
      all(len(by_id[sid]["pairs"]) == 3 for sid in POOLED))

seen_paths = set()
for sid in POOLED:
    step = by_id[sid]
    dom = domain_of(sid)
    size = GRID_SIZE[step["format"]]
    for n, entry in enumerate(step["pool"], start=1):
        pair = pair_of(step, entry)
        cards = pair["images"]
        hits = [c for c in cards if c["tags"] == [dom + "_hit"]]
        misses = [c for c in cards if c["tags"] == [dom + "_miss"]]
        check("  %s v%d: %d cards, exactly one of them the answer"
              % (sid, n, size),
              len(cards) == size and len(hits) == 1
              and len(misses) == size - 1,
              "%d cards, %d hits" % (len(cards), len(hits)))
        check("    every card its own id, every card labelled",
              len({c["id"] for c in cards}) == size
              and all(c.get("label") for c in cards))
        check("    and the clock presses a miss of THIS version",
              entry["timeout_pick"] in {c["id"] for c in misses},
              str(entry.get("timeout_pick")))
        for card in cards:
            seen_paths.add(card["img"])
        for frame in (entry.get("flash") or {}).get("images", []):
            seen_paths.add(frame["img"])

check("every file any version names is on disk",
      not [p for p in sorted(seen_paths)
           if not os.path.exists(os.path.join(ROOT, p.lstrip("/")))],
      str([p for p in sorted(seen_paths)
           if not os.path.exists(os.path.join(ROOT, p.lstrip("/")))])[:200])
check("  and every one of them is under twelve kilobytes",
      not [p for p in sorted(seen_paths)
           if os.path.getsize(os.path.join(ROOT, p.lstrip("/"))) >= 12 * 1024],
      str([p for p in sorted(seen_paths)
           if os.path.getsize(os.path.join(ROOT, p.lstrip("/")))
           >= 12 * 1024])[:200])

print("\n--- v11: the memory rounds keep their own difficulty ---")
HOLD = {"mem1": 3000, "mem2": 3000, "mem3": 2500, "mem4": 2500}
FRAMES = {"mem1": 4, "mem2": 6, "mem3": 6, "mem4": 6}
for sid in ("mem1", "mem2", "mem3", "mem4"):
    step = by_id[sid]
    mid = mid_by_after[SCORED[sid][1] - 1][0]
    check("%s holds %d frames for %dms, answered on a %s"
          % (sid, FRAMES[sid], HOLD[sid], step["format"]),
          mid["auto_advance_ms"] == HOLD[sid]
          and step["format"] == ("grid4" if FRAMES[sid] == 4 else "grid6"),
          "%s / %s" % (mid["auto_advance_ms"], step["format"]))
    for n, entry in enumerate(step["pool"], start=1):
        frames = [f["img"] for f in entry["flash"]["images"]]
        cards = pair_of(step, entry)["images"]
        answer = [c for c in cards if c["tags"][0].endswith("_hit")][0]
        check("  v%d holds %d, and the answer is one of them"
              % (n, FRAMES[sid]),
              len(frames) == FRAMES[sid] and answer["img"] in frames,
              "%d frames" % len(frames))
        check("    no decoy was ever on the screen",
              not [c for c in cards
                   if c["tags"][0].endswith("_miss") and c["img"] in frames],
              str([c["id"] for c in cards
                   if c["tags"][0].endswith("_miss") and c["img"] in frames]))
        check("    and no frame is shown twice",
              len(set(frames)) == len(frames))
# The last round's decoys are the answer's own shape in the colour beside it,
# which is what makes it the hardest of the four rather than the longest.
for n, variant in enumerate(GEN.MEMORY_VARIANTS["mem4"], start=1):
    answer = variant["flash"][variant["seen"]]
    kin = [d for d in variant["decoys"][:5]
           if d[1] == answer[1] or d[0] == answer[0]]
    check("  mem4 v%d hides the answer among its own neighbours" % n,
          len(kin) >= 2, str(variant["decoys"][:5]))

print("\n--- v11: the spatial rounds land where their own chain lands ---")
CHAIN = {"spa1": (4, 800), "spa2": (5, 600), "spa3": (6, 450),
         "spa4": (7, 350)}
for sid in ("spa1", "spa2", "spa3", "spa4"):
    step = by_id[sid]
    want_n, want_ms = CHAIN[sid]
    for n, entry in enumerate(step["pool"], start=1):
        rule = entry["reveal"]
        frames = entry["flash"]["images"]
        cards = pair_of(step, entry)["images"]
        landing = GEN.spatial_landing(rule["open_slot"],
                                      [tuple(p) for p in rule["swaps"]])
        hit = [i for i, c in enumerate(cards)
               if c["tags"][0].endswith("_hit")]
        check("  %s v%d: %d swaps at %dms, held %dms"
              % (sid, n, want_n, want_ms, GEN.SPATIAL_OPEN_MS),
              len(rule["swaps"]) == want_n and rule["swap_ms"] == want_ms
              and rule["open_ms"] == GEN.SPATIAL_OPEN_MS,
              "%d at %s, open %s" % (len(rule["swaps"]), rule["swap_ms"],
                                     rule["open_ms"]))
        check("    the object lands on slot %d, and that slot scores"
              % landing,
              hit == [landing], "hit %s, chain lands %d" % (hit, landing))
        check("    which is never the slot it was shown in",
              landing != rule["open_slot"],
              "%d == %d" % (landing, rule["open_slot"]))
        check("    one box open on the flash, five shut",
              sum(1 for f in frames if "box_open_" in f["img"]) == 1
              and frames[rule["open_slot"]]["img"].count("box_open_") == 1,
              str([f["img"].split("/")[-1] for f in frames]))
        check("    every swap names two slots this grid has",
              all(len(p) == 2 and p[0] != p[1]
                  and all(isinstance(v, int) and 0 <= v < 6 for v in p)
                  for p in rule["swaps"]))
    # v12: the SAME object in all three, because the step's question names it.
    # v11 varied it per version, so two runs in three asked "where is the key
    # now?" over a box that had a moon in it — the object is the thing the
    # question names, so it belongs to the step, and what a version varies is
    # the slot it started in and the way the chain runs.
    shown = {e["flash"]["images"][e["reveal"]["open_slot"]]["img"]
             for e in step["pool"]}
    want = "/static/galleries/brain/box_open_%s.webp" % GEN.SPATIAL_OBJECT[sid]
    check("  and all three versions hide the object the question names",
          shown == {want}, str(sorted(shown)))
    check("    which is the word the step's own question uses",
          GEN.SPATIAL_OBJECT[sid] in step["question"].lower(),
          "%s / %s" % (GEN.SPATIAL_OBJECT[sid], step["question"]))
    check("    and the memorise screen in front of it names the same thing",
          GEN.SPATIAL_OBJECT[sid]
          in mid_by_after[SCORED[sid][1] - 1][0]["line"].lower(),
          mid_by_after[SCORED[sid][1] - 1][0]["line"])
    check("    while the three still start it in three different slots",
          len({e["reveal"]["open_slot"] for e in step["pool"]}) == 3,
          str([e["reveal"]["open_slot"] for e in step["pool"]]))

print("\n--- v11: the change rounds change one thing, by their own amount ---")
KIND = {"chg1": "letter", "chg2": "colour", "chg3": "size",
        "chg4": "rotation"}
NEIGHBOUR = {("violet", "blue"), ("blue", "violet"), ("teal", "green"),
             ("green", "teal"), ("amber", "red"), ("red", "amber")}


def letter_bits(path):
    """(letter, colour, size, degrees) off the filename that states them."""
    got = re.search(r"letter_([A-Z])_(\w+?)_(\w+?)_(\d+)\.webp$", path)
    return (got.group(1), got.group(2), got.group(3),
            int(got.group(4))) if got else None


for sid in ("chg1", "chg2", "chg3", "chg4"):
    step = by_id[sid]
    for n, entry in enumerate(step["pool"], start=1):
        before = [letter_bits(f["img"]) for f in entry["flash"]["images"]]
        after = [letter_bits(c["img"]) for c in pair_of(step, entry)["images"]]
        cards = pair_of(step, entry)["images"]
        hit = [i for i, c in enumerate(cards)
               if c["tags"][0].endswith("_hit")]
        moved = [i for i in range(4) if before[i] != after[i]]
        check("  %s v%d: exactly one of the four came back different"
              % (sid, n), len(moved) == 1 and moved == hit,
              "changed %s, scored %s" % (moved, hit))
        i = moved[0]
        facets = [k for k in range(4) if before[i][k] != after[i][k]]
        check("    and it changed exactly one thing, which is %s"
              % KIND[sid],
              len(facets) == 1
              and facets[0] == ["letter", "colour", "size",
                                "rotation"].index(KIND[sid]),
              str((before[i], after[i])))
        if KIND[sid] == "colour":
            check("    one shade over, not one colour over",
                  (before[i][1], after[i][1]) in NEIGHBOUR,
                  "%s -> %s" % (before[i][1], after[i][1]))
        if KIND[sid] == "size":
            check("    a fifth off, not a third",
                  before[i][2] == "lg" and after[i][2] == "md"
                  and GEN.LETTER_SIZES["md"] == 240,
                  "%s -> %s" % (before[i][2], after[i][2]))
        if KIND[sid] == "rotation":
            check("    ten degrees, which is less than the fifteen it was",
                  after[i][3] == 10, str(after[i][3]))
        check("    the other three came back byte for byte",
              [before[k] for k in range(4) if k != i]
              == [after[k] for k in range(4) if k != i])

print("\n--- v11: the four focus rounds, and their four seconds ---")
for sid in ("odd", "ink", "next", "count"):
    check("%s gives four seconds" % sid,
          by_id[sid]["timer_ms"] == 4000, str(by_id[sid]["timer_ms"]))

for n, variant in enumerate(GEN.ODD_VARIANTS, start=1):
    step = by_id["odd"]
    cards = pair_of(step, step["pool"][n - 1])["images"]
    hit = [i for i, c in enumerate(cards)
           if c["tags"][0].endswith("_hit")][0]
    check("  odd v%d: the short hook is slot %d, and that slot scores"
          % (n, variant["odd"]),
          hit == variant["odd"] - 1, "hit %d, odd %d" % (hit, variant["odd"]))
    check("    six files, so the answer is not readable off the page source",
          len({c["img"] for c in cards}) == 6)
check("  the odd hook is shorter rather than mirrored",
      "ODD_SHORT = 0.62" in ART and "short=(slot == variant[" in ART)

for n, variant in enumerate(GEN.INK_VARIANTS, start=1):
    step = by_id["ink"]
    cards = pair_of(step, step["pool"][n - 1])["images"]
    honest = [i for i, (text, colour) in enumerate(variant["cards"])
              if text.lower() == colour]
    hit = [i for i, c in enumerate(cards)
           if c["tags"][0].endswith("_hit")]
    check("  ink v%d: exactly one card tells the truth, and it scores" % n,
          len(honest) == 1 and hit == honest,
          "honest %s, hit %s" % (honest, hit))
    liars = [(t, c) for t, c in variant["cards"] if t.lower() != c]
    # The near misses here are red/amber and blue/violet, and not teal/green:
    # teal is a shade of green in ordinary speech, so "GREEN" set in teal is
    # not an attention test but a disagreement about the name of a colour.
    check("    and every liar is a near miss a reader would still call wrong",
          all((t.lower(), c) in GEN.INK_NEAR for t, c in liars),
          str(liars))

for n, spec in enumerate(GEN.DIAL_VARIANTS, start=1):
    plan = GEN.dial_round(spec)
    step = by_id["next"]
    entry = step["pool"][n - 1]
    cards = pair_of(step, entry)["images"]
    frames = [f["img"] for f in entry["flash"]["images"]]
    check("  next v%d: the notch turns %d a frame, the dot steps one of %d"
          % (n, spec["rot"], spec["dots"]),
          [((i * spec["rot"]) % 360, i % spec["dots"])
           for i in range(3)] == plan["seq"])
    check("    three frames and a question mark",
          len(frames) == 4 and frames[3].endswith("nxt_qm.webp"))
    check("    exactly one candidate continues both progressions",
          cards[0]["img"].endswith(
              GEN.dial_name(plan["right"][0], plan["right"][1],
                            plan["dots"]) + ".webp")
          and cards[0]["tags"][0].endswith("_hit"),
          cards[0]["img"])
    for k, (rot, dot) in enumerate(plan["wrong"], start=1):
        matched = (rot == plan["right"][0]) + (dot == plan["right"][1])
        check("    distractor %d gets exactly one of the two right" % k,
              matched == 1 and cards[k]["tags"][0].endswith("_miss"),
              "%s vs %s" % ((rot, dot), plan["right"]))
    check("    one of the three is a frame the flash already showed",
          any(GEN.dial_name(r, d, plan["dots"]) + ".webp" in frames[3 - 3:3]
              or any(f.endswith(GEN.dial_name(r, d, plan["dots"]) + ".webp")
                     for f in frames[:3])
              for r, d in plan["wrong"]))
    check("    and no two candidates are the same picture",
          len({c["img"] for c in cards}) == 4)

for n, variant in enumerate(GEN.COUNT_VARIANTS, start=1):
    step = by_id["count"]
    entry = step["pool"][n - 1]
    cards = pair_of(step, entry)["images"]
    total = sum(len(frame) for frame in variant["spots"])
    hit = [c for c in cards if c["tags"][0].endswith("_hit")]
    check("  count v%d: %d circles across four frames" % (n, variant["total"]),
          total == variant["total"], "%d drawn" % total)
    check("    the four on offer are its own, and the true count scores",
          [c["label"] for c in cards] == variant["answers"]
          and len(hit) == 1 and hit[0]["label"] == str(variant["total"]),
          str([c["label"] for c in cards]))
    check("    the frames carry uneven numbers, so it cannot be counted "
          "by pattern",
          len({len(frame) for frame in variant["spots"]}) >= 3,
          str([len(f) for f in variant["spots"]]))
check("  the three versions count three different totals",
      len({v["total"] for v in GEN.COUNT_VARIANTS}) == 3,
      str([v["total"] for v in GEN.COUNT_VARIANTS]))

print("\n--- v11: a perfect run reaches a hundred whatever it is dealt ---")
SCORE = cfg["brain_age"]["score"]
for pick in (0, 1, 2):
    scores = {}
    for sid in POOLED:
        step = by_id[sid]
        entry = step["pool"][pick % len(step["pool"])]
        for card in pair_of(step, entry)["images"]:
            if card["tags"][0].endswith("_hit"):
                for tag in card["tags"]:
                    scores[tag] = scores.get(tag, 0) + 1
    hits = sum(scores.values())
    check("  version %d of every round: sixteen hits, a hundred out of a "
          "hundred" % pick,
          hits == cfg["brain_age"]["scored"]
          and SCORE["base"] + SCORE["per_miss"] * 0 == 100,
          "%d hits" % hits)

print("\n--- v5: the offer, and the line under the button ---")
# v11 replaced the ticked list and the manifest with the offer card's own
# four benefit cards. The food day is one of them.
cards = cfg["result_copy"]["profile"]["offer_cards"]
fuel = [row for row in cards if row["title"] == "Fuel"]
check("the plan sells a day of food as well as the drills",
      len(fuel) == 1, str([r["title"] for r in cards]))
check("  in the words the review asked for",
      fuel[0]["sub"] == "The plate that feeds a sharp brain",
      fuel[0]["sub"])
check("the offer names no brain type at all",
      "{type}" not in json.dumps(cfg["result_copy"]["profile"]["offer_head"])
      and "{type}" not in json.dumps(cfg["checkout"]))
check("the button carries a line saying what following the plan does",
      cfg["result_copy"].get("improve_foot")
      == "Follow the 7-day plan, play again — the score climbs.",
      str(cfg["result_copy"].get("improve_foot")))
check("  with no percentage and no number nobody has measured",
      not re.search(r"\d", cfg["result_copy"]["improve_foot"]
                    .replace("7-day", "")),
      cfg["result_copy"]["improve_foot"])
check("  and the module draws it under the control",
      "copy.improve_foot" in MODULE
      and MODULE.index("block.appendChild(button);")
      < MODULE.index("copy.improve_foot"))

print("\n--- v5: the strip shows what happened ---")
# v8. The substitution moved into engine.js, which draws the same tiles in
# two other places, and this module reads that rule off the context rather
# than keeping a second copy of it. What is checked here is that it reads it
# and does not restate it.
check("a spatial round draws the box that was open, not the shut one",
      "function standIn(" not in MODULE
      and "typeof ctx.tile === \"function\"" in MODULE
      and "return ctx.tile(index, stepId, item, late);" in MODULE)
for r in range(1, 5):
    sid = "spa%d" % r
    entry = mid_by_after[SCORED[sid][1] - 1][0]
    stand = entry["flash"]["images"][entry["reveal"]["open_slot"]]["img"]
    check("  %s stands in the %s" % (sid, stand.rsplit("_", 1)[-1][:-5]),
          "box_open_" in stand, stand)
check("  and every other round still draws the card that was tapped",
      "return { img: (item && item.img) || null };" in MODULE
      and MODULE.count("out.push(tileOf(ctx, index,") == 2)
check("a round the clock answered draws a cross instead of a card",
      'item.className = "br-tap is-out";' in MODULE
      and MODULE.count('mark.appendChild(elm("i"));') >= 2
      and ".br-tap.is-out {" in RESULT_CSS
      and ".br-tap-out i:first-child { transform: rotate(45deg); }"
      in RESULT_CSS)
check("  read off the run before the money",
      "var late = ctx.timed_out || [];" in MODULE)
check("  and off the report after it",
      "(ctx.visuals && ctx.visuals.timed_out) || []" in MODULE)

print("\n--- v6: what the intro promises, and what the page hands over ---")
check("four chips, and the fourth is the one about money",
      intro.get("chips") == ["2 MINUTES", "NO SIGN-UP", "NO SUBSCRIPTION",
                             "INSTANT RESULT"],
      str(intro.get("chips")))
check("  none of them long enough to break a line on its own",
      all(len(chip) <= 16 for chip in intro["chips"]),
      str([c for c in intro["chips"] if len(c) > 16]))
share = cfg["result_copy"]["profile"]
for key in ("share_cta", "share_line", "share_copied", "retest_line"):
    check("  %s is copy, in the config" % key, bool(share.get(key)),
          str(share.get(key)))
check("what gets shared carries the reader's own number",
      "{n}" in share["share_line"], share["share_line"])
# v10 shares a score out of a hundred, so the denominator is a number the
# line has to carry. It is the only one: no price, no percentage, and nothing
# about anybody else.
check("  out of a hundred, and no other number at all",
      "100" in share["share_line"]
      and not re.search(r"\d", share["share_line"]
                        .replace("{n}", "").replace("100", "")),
      share["share_line"])
check("  nor a price, a percentage or anything about anybody else",
      "{price}" not in share["share_line"]
      and "%" not in share["share_line"])
check("the button says what it does, and what it did",
      share["share_cta"] == "Challenge a friend"
      and share["share_copied"] == "Copied — send it")
check("the plan ends on coming back to play it again",
      share["retest_line"] == "In one week: play it again. The number moves.")
check("  with no promise about how far the number moves",
      not re.search(r"\d", share["retest_line"])
      and "%" not in share["retest_line"], share["retest_line"])

check("the module reads every word of it off the config",
      all(("table." + key) in MODULE
          for key in ("share_cta", "share_line", "share_copied",
                      "retest_line")))
check("  and hardcodes none of them",
      not [line for line in (share["share_cta"], share["share_copied"],
                             share["retest_line"]) if line in MODULE],
      str([line for line in (share["share_cta"], share["share_copied"],
                             share["retest_line"]) if line in MODULE]))
check("the share control sits under the number and above the offer",
      MODULE.index("var hand = share(ctx, data);")
      < MODULE.index("var push = urge(ctx, copy);"))
check("  it is the quieter of the two, outlined against a solid one",
      re.search(r"\.br-share-cta \{[^}]*background: transparent;",
                RESULT_CSS, re.S) is not None
      and re.search(r"\.br-urge-cta \{[^}]*background: var\(--br-lux\);",
                    RESULT_CSS, re.S) is not None)
check("it hands over the sheet where there is one",
      "if (navigator.share) {" in MODULE
      and "navigator.share(payload)" in MODULE)
check("  and the clipboard where there is not",
      "navigator.clipboard.writeText(full)" in MODULE
      and "said(table.share_copied" in MODULE)
check("  swapping the label back after a beat",
      "var COPIED_MS = 2000;" in MODULE
      and "timer = setTimeout(function () {" in MODULE)
check("the link it hands over is the funnel's own path, not this tab's",
      "window.location.origin" in MODULE
      and '(ctx.cfg && ctx.cfg.slug)' in MODULE
      and "location.href" not in MODULE)
check("one event on the tap, and nothing about the reader in it",
      'ctx.track("share_tap");' in MODULE
      and MODULE.count('ctx.track("share_tap")') == 1
      and not re.search(r'track\("share_tap",', MODULE))
check("  which the server already allows",
      "share_tap" in tracking.ALLOWED_EVENTS)
check("the delivered page ends on the retest line",
      "var again = retest(ctx);" in MODULE
      and MODULE.index("var again = retest(ctx);")
      > MODULE.index("copy.delivered_note"))
check("  as a link back to the funnel's own path",
      'link.href = "/" + slug;' in MODULE
      and 'elm("a", "br-retest-link"' in MODULE)
# v10: the same sentence about the number the page now shows.
check("  and the free page closes on the score it just gave",
      cfg["result_copy"].get("improve_foot")
      == "Follow the 7-day plan, play again — the score climbs."
      and "copy.improve_foot" in MODULE)

print("\n--- v6: the paid page draws every shape the report writes ---")
# Four shapes reach it, because BRAIN_PROFILE writes four. Two of them were
# not being drawn: the plan's `{name, priority_note}` days came out as empty
# numbers and the weakest-round table was not read at all — the paid half of
# the document, missing from the paid page.
check("the day rows render their own two fields",
      "item.title || item.name" in MODULE
      and "item.body || item.priority_note" in MODULE)
check("the four rounds render as a badged table",
      "(data.pairs || []).forEach" in MODULE
      and 'elm("span", "br-combo"' in MODULE
      and 'elm("span", "br-badge-verdict is-"' in MODULE)
check("  with the funnel's own words in the badge, not the schema's",
      'VERDICT_WORDS = { works: "STRENGTH", avoid: "ROOM TO GROW" };'
      in MODULE
      and cfg["result_copy"]["profile"] is not None)
check("  and the class the colour hangs off is still the schema's word",
      ".br-badge-verdict.is-works {" in RESULT_CSS
      and ".br-badge-verdict.is-avoid {" in RESULT_CSS)
check("the chapter closes on the drill, set apart from the prose",
      "if (data.rule) frag.appendChild(elm(\"p\", \"br-callout\", data.rule));"
      in MODULE and ".br-callout {" in RESULT_CSS)

print("\n--- the copy: a game, and nothing that sounds like anything else ---")
BANNED = ("memory loss", "cognitive", "decline", "dementia", "test yourself",
          "health", "diagnosis", "treatment", "symptom", "disorder")
strings = []


def gather(node, at=""):
    if isinstance(node, dict):
        for key, value in node.items():
            gather(value, at + "." + key)
    elif isinstance(node, list):
        for i, value in enumerate(node):
            gather(value, at + "[%d]" % i)
    elif isinstance(node, str):
        strings.append((at, node))


gather(cfg)
for word in BANNED:
    guilty = [at for at, text in strings if word in text.lower()]
    check("  no string says %r" % word, not guilty, str(guilty[:4]))
check("  and the first chapter is titled without the banned one",
      cfg["report"]["sections"][0]["title"]
      == "Your Brain Profile & Your Edge",
      cfg["report"]["sections"][0]["title"])
money = [(at, text) for at, text in strings
         if "$" in text or re.search(r"\d\s*%", text)]
check("no price is written out anywhere; it is always the token", not money,
      str(money[:3]))
check("  and the token is on the one label that charges",
      "{price}" in cfg["checkout"]["cta_label"])
percent = [(at, text) for at, text in strings
           if "%" in text.replace("{pct}", "")]
check("  the only percent sign anywhere is {pct}", not percent,
      str(percent[:3]))
check("the shell copy is this funnel's",
      cfg["meta"]["title"] == "Brain Age Challenge"
      and cfg["swipe"]["headline"] == "How old is your brain?"
      and cfg["swipe"]["subtext"] == "18 quick rounds. No sign-up."
      and cfg["swipe"]["hint"] == "Tap fast. Trust your gut.")

print("\n--- the offer ---")
sections = cfg["report"]["sections"]
check("four chapters", len(sections) == 4,
      str([s["id"] for s in sections]))
check("  on the ids the report machinery already knows",
      [s["id"] for s in sections] == ["dna", "materials", "mistakes",
                                      "shopping"])
check("  each titled, teased and shut",
      all(s.get("title") and s.get("teaser_line")
          and s.get("enabled") is True
          and (s.get("reveal") or {}).get("mode") == "locked"
          for s in sections))
check("the checkout names the product this funnel sells",
      cfg["checkout"]["product_name"] == "Your Brain Refresh Report"
      and cfg["checkout"]["cta_label"] == "Reveal my brain age — {price}"
      and cfg["checkout"]["proof_line"] == "Built from your 16 rounds")
check("one offer, not two: the layout is named rather than tested",
      "paywall_variants" not in cfg)
# v10: the reveal leads both lists. The free page no longer shows the age, so
# the first thing this offer names is the number it is holding.
# v11: the offer card is four benefit cards and a hero tile now, not a
# manifest of one line per chapter and a list saying the same thing again.
check("  and the offer names four things the plan contains",
      len(cfg["result_copy"]["profile"]["offer_cards"]) == 4
      and "manifest" not in cfg["checkout"],
      str(sorted(cfg["checkout"])))
check("every chapter has a card in the result copy",
      sorted(c["id"] for c in cfg["result_copy"]["profile"]["cards"])
      == sorted(s["id"] for s in sections))
check("  and every mood the offer personalises on names a real chapter",
      all(rule["emphasized_section"] in {s["id"] for s in sections}
          for rule in cfg["result_copy"]["purpose_map"].values()))

print("\n--- v10: the free page shows a score, and no age at all ---")
SCORE = block["score"]
check("the score block is exactly the five constants both readers need",
      set(SCORE) == {"base", "per_miss", "elite_min", "floor",
                     "room_round_max_hits"}, str(sorted(SCORE)))
check("  a hundred down six a miss, floored, and elite at ninety",
      SCORE == {"base": 100, "per_miss": -6, "elite_min": 90, "floor": 5,
                "room_round_max_hits": 2}, str(SCORE))
check("the module reads every one of them rather than holding its own",
      all(("rule." + key) in MODULE for key in
          ("base", "per_miss", "floor", "elite_min", "room_round_max_hits"))
      and "var rule = (block && block.score) || null;" in MODULE)
check("  and the free page draws the score where the age used to be",
      "scoreCard(ctx, copy, data, lean)" in module_body("render")
      and "br-age-word" not in MODULE.split("function scoreCard(")[1]
      .split("\n  }")[0])
check("  falling back to the page it had on a config with no score table",
      'if (typeof data.score !== "number") return null;'
      in module_body("scoreCard")
      and "|| score(ctx, copy, data, lean);" in module_body("render"))
check("  under the score's own kicker",
      "kicker(copy, lean, copy.score_kicker)" in module_body("render")
      and cfg["result_copy"]["score_kicker"] == "Your score")
check("  as a figure out of what the table says a clean run is worth",
      '"/" + (typeof top === "number" ? top : 100)' in MODULE
      and 'elm("span", "br-age-number", String(data.score))' in MODULE)
check("no brain age is drawn on the free page at all",
      "data.age" not in module_body("render")
      and "br-age-word" not in module_body("scoreCard")
      and "ageLine(" not in module_body("scoreCard"))
check("  and the age hero is the delivered page's",
      "root.appendChild(score(ctx, copy, data, lean));"
      in module_body("delivered")
      and module_body("delivered").index("scoreCard(ctx, copy, data, lean)")
      < module_body("delivered").index("score(ctx, copy, data, lean)"))
check("the line under the score counts rounds with room, or says it was close",
      cfg["result_copy"]["score_room"]
      == "Clear room in {k} of your 4 rounds."
      and cfg["result_copy"]["score_room_none"]
      == "Close run — the points you dropped are all in the details."
      and cfg["result_copy"]["score_elite"]
      == "Elite run. See what's behind it inside.")
check("  and the module chooses between them off the run alone",
      "if (data.elite) return copy.score_elite" in MODULE
      and "if (!data.room_rounds) return copy.score_room_none" in MODULE
      and "{ k: data.room_rounds }" in MODULE)

# Nobody else has taken this. Every word the free page says about the number
# is about this run, and a page that reached for a population would be
# reaching for one that does not exist.
CROWD = ("average", " avg", "percentile", "top %", "better than",
         "most people", "than others", "worldwide", "users")
FREE_COPY = json.dumps({k: v for k, v in cfg["result_copy"].items()
                        if k != "purpose_map"}, ensure_ascii=False).lower()
check("nothing on the free page compares the reader to anybody",
      not [w for w in CROWD if w.strip() in FREE_COPY],
      str([w for w in CROWD if w.strip() in FREE_COPY]))
check("  nor does the offer or the share line",
      not [w for w in CROWD
           if w.strip() in json.dumps(cfg["checkout"],
                                      ensure_ascii=False).lower()],
      str([w for w in CROWD
           if w.strip() in json.dumps(cfg["checkout"],
                                      ensure_ascii=False).lower()]))
check("  and no invented statistic is printed anywhere near the number",
      not re.search(r"\d+\s*%", FREE_COPY), FREE_COPY[:80])
check("what gets shared is the score, out of a hundred",
      cfg["result_copy"]["profile"]["share_line"]
      == "I scored {n}/100. Beat me?"
      and "fill(table.share_line, { n: data.score });" in MODULE)
check("  and the share is withheld from a run with no score to give",
      'if (typeof data.score !== "number") return null;' in MODULE)

print("\n--- v11: the offer card, rebuilt ---")
OFFER = cfg["result_copy"]["profile"]
STATIC = json.load(open(os.path.join(ROOT, "static/funnels/brain.json"),
                        encoding="utf-8"))
for name, table in (("funnels", cfg), ("static", STATIC)):
    prof = table["result_copy"]["profile"]
    check("%s: the card's copy is all in the config" % name,
          all(prof.get(k) for k in ("offer_personal", "offer_personal_elite",
                                    "offer_hero_kicker", "offer_hero_line",
                                    "offer_cards", "offer_chips")),
          str([k for k in ("offer_personal", "offer_personal_elite",
                           "offer_hero_kicker", "offer_hero_line",
                           "offer_cards", "offer_chips")
               if not prof.get(k)]))
    check("  four benefit cards and three chips",
          len(prof["offer_cards"]) == 4 and len(prof["offer_chips"]) == 3,
          "%d cards, %d chips" % (len(prof["offer_cards"]),
                                  len(prof["offer_chips"])))
    check("  and the list it replaces is gone from the config",
          not [k for k in prof if "unlock" in k]
          and "manifest" not in table["checkout"],
          str([k for k in prof if "unlock" in k]))
check("nothing in the module reads the list either",
      "unlock" not in MODULE and "checklist" not in MODULE
      and "br-checklist" not in RESULT_CSS)
check("every benefit card names an icon, a title and a line",
      all(row.get("icon") and row.get("title") and row.get("sub")
          for row in OFFER["offer_cards"]),
      str(OFFER["offer_cards"]))
check("  and the four are the four the review asked for",
      [row["title"] for row in OFFER["offer_cards"]]
      == ["Weakest-round drill", "7-day plan", "5 strengths · 2 habits",
          "Fuel"],
      str([row["title"] for row in OFFER["offer_cards"]]))
check("  every icon the config names is one the module can draw",
      all(row["icon"] in MODULE for row in OFFER["offer_cards"])
      and all(('%s: [' % row["icon"]) in MODULE
              for row in OFFER["offer_cards"]),
      str([row["icon"] for row in OFFER["offer_cards"]]))
check("the icons are inline paths, stroked in the card's own colour",
      "var OFFER_ICONS = {" in MODULE
      and 'svgEl("svg", { viewBox: "0 0 24 24" })' in MODULE
      and "stroke: currentColor;" in RESULT_CSS
      and re.search(r"\.br-benefit-icon svg \{[^}]*fill: none;",
                    RESULT_CSS, re.S) is not None)
check("  and not one of them is an emoji",
      not [ch for row in OFFER["offer_cards"] for ch in row["title"] + row["sub"]
           if ord(ch) > 0x2100],
      str([ch for row in OFFER["offer_cards"]
           for ch in row["title"] + row["sub"] if ord(ch) > 0x2100]))
check("  nor is anything else on the card",
      not [ch for text in ([OFFER["offer_personal"],
                            OFFER["offer_personal_elite"],
                            OFFER["offer_hero_kicker"],
                            OFFER["offer_hero_line"]] + OFFER["offer_chips"])
           for ch in text if ord(ch) > 0x2100])

# The personal line names the round with the fewest hits, ties going to the
# earliest of the four — and a run with nothing to name says so instead.
DOM_ORDER = ["mem", "spa", "chg", "foc"]


def weakest(counts):
    return min(DOM_ORDER, key=lambda k: (counts[k], DOM_ORDER.index(k)))


for counts, want in (({"mem": 4, "spa": 3, "chg": 1, "foc": 2}, "chg"),
                     ({"mem": 2, "spa": 2, "chg": 4, "foc": 3}, "mem"),
                     ({"mem": 0, "spa": 0, "chg": 0, "foc": 0}, "mem")):
    check("  %s is the round with the most room in %s"
          % (cfg["brain_age"]["domains"][want], counts),
          weakest(counts) == want, weakest(counts))
check("the module names it the same way, off the config's own labels",
      "function weakestRound(" in MODULE
      and "if (worst === null || got < worst.got)" in MODULE
      and "(ageBlock(ctx) || {}).domains" in MODULE)
check("  and a close run is told it was close instead",
      "if (data.elite || !data.room_rounds) {" in MODULE
      and "table.offer_personal_elite" in MODULE)
check("  both templates being the config's",
      OFFER["offer_personal"]
      == "Most of your dropped points are in {round}. The drill for it is "
         "inside."
      and OFFER["offer_personal_elite"]
      == "A close run. The plan is what keeps it that way.")

check("the locked tile shows two hashes and never a number",
      'elm("span", "br-hero-hash", "##")' in MODULE
      and "data.age" not in module_body("offerHero")
      and "String(" not in module_body("offerHero"))
check("  with a solid LOCKED pill over its bottom edge",
      'elm("span", "br-hero-lock", "LOCKED")' in MODULE
      and re.search(r"\.br-hero-lock \{[^}]*background: var\(--br-lux\);",
                    RESULT_CSS, re.S) is not None
      and re.search(r"\.br-hero-lock \{[^}]*bottom: -9px;", RESULT_CSS, re.S)
      is not None)
check("  and the tile is 74px, on an accent-bordered card",
      re.search(r"\.br-hero-tile \{[^}]*flex: 0 0 74px;", RESULT_CSS, re.S)
      is not None
      and re.search(r"\.br-hero \{[^}]*border: 1\.5px solid var\(--br-lux\);",
                    RESULT_CSS, re.S) is not None)
check("the price block is the config's, struck regular and all",
      'elm("span", "br-price-now", ctx.price)' in MODULE
      and 'elm("span", "br-price-was", ctx.priceRegular)' in MODULE
      and cfg["checkout"]["commerce"]["price_note"] == "one-time"
      and cfg["sale"]["label"] == "Launch Offer")
check("the button says what pressing it reveals",
      cfg["checkout"]["cta_label"] == "Reveal my brain age — {price}"
      and "{price}" in cfg["checkout"]["cta_label"])
check("the card ends on the anchor, and it is the last thing on it",
      "card.appendChild(anchor);" in module_body("offer")
      and module_body("offer").rindex("card.appendChild(anchor);")
      > module_body("offer").rindex("if (chips) card.appendChild(chips);"))
check("  and the card argues in the order the review set",
      [module_body("offer").index(x) for x in
       ("if (head) card.appendChild", "if (personal) card.appendChild",
        "if (hero) card.appendChild", "if (grid) card.appendChild",
        "card.appendChild(price);", "if (chips) card.appendChild",
        "card.appendChild(anchor);")]
      == sorted([module_body("offer").index(x) for x in
                 ("if (head) card.appendChild", "if (personal) card.appendChild",
                  "if (hero) card.appendChild", "if (grid) card.appendChild",
                  "card.appendChild(price);", "if (chips) card.appendChild",
                  "card.appendChild(anchor);")]))
CROWD_OFFER = ("average", "percentile", "most people", "top %", "better than")
OFFER_TEXT = json.dumps(
    [OFFER[k] for k in ("offer_personal", "offer_personal_elite",
                        "offer_hero_kicker", "offer_hero_line")]
    + OFFER["offer_chips"] + OFFER["offer_cards"], ensure_ascii=False).lower()
check("and nothing on the new card claims anything about anybody else",
      not [w for w in CROWD_OFFER if w in OFFER_TEXT]
      and not re.search(r"\d+\s*%", OFFER_TEXT),
      str([w for w in CROWD_OFFER if w in OFFER_TEXT]))

print("\n--- v12: the four things a box can be hiding ---")
OBJECTS = sorted(set(GEN.SPATIAL_OBJECT.values()))
check("there are four of them, one per spatial round",
      OBJECTS == ["cup", "key", "moon", "star"], str(OBJECTS))
check("  and each round owns exactly one, for the length of the funnel",
      len(GEN.SPATIAL_OBJECT) == 4
      and len(set(GEN.SPATIAL_OBJECT.values())) == 4,
      str(GEN.SPATIAL_OBJECT))
check("  which is on the STEP now, not on the version",
      "SPATIAL_OBJECT = {" in ART
      and not re.search(r'\{"object":', ART),
      str(re.findall(r'\{"object":[^,]*', ART)[:2]))
for name in OBJECTS:
    path = os.path.join(GALLERY, "box_open_%s.webp" % name)
    check("  box_open_%s is drawn and on disk" % name, os.path.exists(path))
    check("    under twelve kilobytes",
          os.path.exists(path) and os.path.getsize(path) < 12 * 1024,
          str(os.path.getsize(path)) if os.path.exists(path) else "-")
check("  and the two v11 drew for versions that no longer vary are gone",
      not [n for n in os.listdir(GALLERY)
           if n.startswith("box_open_")
           and n[len("box_open_"):-len(".webp")] not in OBJECTS],
      str(sorted(n for n in os.listdir(GALLERY)
                 if n.startswith("box_open_"))))
check("every reference to an object anywhere points at the four",
      not [p for p in sorted(set(paths))
           if "box_open_" in p
           and p.split("box_open_")[-1][:-5] not in OBJECTS],
      str(sorted({p for p in paths if "box_open_" in p})))
# v12 redrew all four: at the size a card is on a phone the key was a red bar
# with two bumps on it, and a reader who cannot name what they saw cannot hold
# it for the length of a shuffle.
check("the key is a bow with a hole in it, a shaft and two teeth",
      "The key: a round bow with a hole you can see through it" in ART
      and "bow = px(0.122)" in ART
      and ART.count("card.d.rounded_rectangle([cx + px(at)") == 1)
check("  and the hole is cut last, so the shaft cannot close it",
      ART.index("The hole last, so the shaft cannot close it")
      > ART.index("bow = px(0.122)"))
check("the cup is a mug with a handle and a base",
      "A mug: straight sides, a heavy handle off the right" in ART)
check("the star is five points and big",
      'card.shape("star", AMBER, cx=0.5, cy=0.585, r=0.215)' in ART)
check("the moon is a disc bitten by a disc set up and across",
      "A crescent with horns that come to a point" in ART)
check("and none of the four can paint over the box it is inside",
      "ImageChops.multiply(glyph.img.split()[3], inside)" in ART
      and "stamped through the box\u2019s" in ART.replace("'", "\u2019"))

print("\n%d checks, %d failed" % (checks[0], len(fails)))
for line in fails:
    print("  FAIL " + line)
sys.exit(1 if fails else 0)
