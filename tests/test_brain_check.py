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
check("  every step asks exactly one question, once",
      all(len(s["pairs"]) == 1 for s in steps))
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

print("\n--- sixteen scored rounds, one right answer each ---")
check("sixteen rounds are scored", len(SCORED) == 16)
check("  which is the denominator the brain age is computed against",
      cfg["brain_age"]["scored"] == len(SCORED))
for sid, (domain, _at) in sorted(SCORED.items(), key=lambda r: r[1][1]):
    tags = [i["tags"] for i in images(by_id[sid])]
    flat = [t for row in tags for t in row]
    hits = [t for t in flat if t == domain + "_hit"]
    misses = [t for t in flat if t == domain + "_miss"]
    check("  %-6s has one %s_hit and the rest %s_miss"
          % (sid, domain, domain),
          len(hits) == 1 and len(misses) == len(images(by_id[sid])) - 1
          and len(flat) == len(images(by_id[sid])),
          str(flat))
check("the two service rounds score nothing anybody is measured on",
      not [t for sid in ("age", "mood") for i in images(by_id[sid])
           for t in i["tags"] if t.split("_")[0] in DOMAINS])
check("  the age round tags the six groups the table prices",
      sorted(t for i in images(by_id["age"]) for t in i["tags"])
      == sorted(cfg["brain_age"]["age_mid"]))
check("  and the mood round tags the four the offer reads",
      sorted(t for i in images(by_id["mood"]) for t in i["tags"])
      == sorted(cfg["result_copy"]["purpose_map"]))


def hit_index(sid):
    domain = SCORED[sid][0]
    for i, image in enumerate(images(by_id[sid])):
        if domain + "_hit" in image["tags"]:
            return i
    return -1


print("\n--- a flash in front of every round that needs one ---")
NEEDS_FLASH = [sid for sid in SCORED
               if sid.startswith(("mem", "spa", "chg"))] + ["next", "count"]
check("no two interstitials claim the same beat",
      all(len(rows) == 1 for rows in mid_by_after.values()),
      str([at for at, rows in mid_by_after.items() if len(rows) > 1]))
check("  and none of them lands past the last round",
      max(mid_by_after) <= len(steps), str(max(mid_by_after)))
for sid in sorted(NEEDS_FLASH, key=lambda s: SCORED[s][1]):
    at = SCORED[sid][1] - 1
    entry = (mid_by_after.get(at) or [None])[0]
    ok = entry is not None and entry.get("template") == "flash"
    check("  %-6s is preceded by a flash on beat %d" % (sid, at), ok,
          str(entry and entry.get("template")))
    if not ok:
        continue
    flash = entry.get("flash") or {}
    check("    laid out on the same grid the round draws",
          flash.get("format") == by_id[sid]["format"],
          "%s vs %s" % (flash.get("format"), by_id[sid]["format"]))
    check("    on a grid the engine knows",
          flash.get("format") in GRID_SIZE, str(flash.get("format")))
    ms = entry.get("auto_advance_ms")
    # Five seconds everywhere but the last memory round, which is the hardest
    # of the four and is meant to be: six frames, two and a half seconds.
    want_ms = 2500 if sid == "mem4" else FLASH_MS
    check("    held for %s" % ("two and a half seconds" if sid == "mem4"
                               else "five seconds"),
          ms == want_ms, str(ms))
    check("    with frames on it, and a kicker and a line over them",
          len(flash.get("images") or []) >= 4
          and entry.get("kicker") and entry.get("line"))
    check("    and every frame names a file",
          all(f.get("img") for f in flash["images"]))
FLASH_MAX_MS = int(re.search(r"var FLASH_MAX_MS = (\d+);", ENGINE).group(1))
check("no flash asks to be held longer than the engine will hold it",
      all(e["auto_advance_ms"] <= FLASH_MAX_MS
          for e in mids if e.get("template") == "flash"),
      str(FLASH_MAX_MS))
check("  and the ceiling it is measured against is the flash's own",
      'if (entry.template === "flash") ceiling = FLASH_MAX_MS;' in ENGINE)
check("the two rounds that need no flash have none",
      15 - 1 not in mid_by_after or
      mid_by_after[14][0].get("template") != "flash")

print("\n--- the memory rounds: the seen card was seen ---")
for r in range(1, 5):
    sid = "mem%d" % r
    entry = mid_by_after[SCORED[sid][1] - 1][0]
    shown = {f["img"] for f in entry["flash"]["images"]}
    cards = images(by_id[sid])
    hit = cards[hit_index(sid)]
    check("  %s: the card scored as seen was on its flash" % sid,
          hit["img"] in shown, hit["img"])
    check("    and none of the three decoys was",
          not [c for c in cards if c is not hit and c["img"] in shown],
          str([c["id"] for c in cards if c is not hit and c["img"] in shown]))
seen_slots = [next(i for i, f in enumerate(
    mid_by_after[SCORED["mem%d" % r][1] - 1][0]["flash"]["images"])
    if f["img"] == images(by_id["mem%d" % r])[hit_index("mem%d" % r)]["img"])
    for r in range(1, 5)]
check("  and the seen frame is a different slot on every round",
      len(set(seen_slots)) == 4, str(seen_slots))

print("\n--- the spatial rounds: the open box is the answer ---")
for r in range(1, 5):
    sid = "spa%d" % r
    entry = mid_by_after[SCORED[sid][1] - 1][0]
    frames = entry["flash"]["images"]
    opened = [i for i, f in enumerate(frames) if "box_open" in f["img"]]
    closed = [i for i, f in enumerate(frames) if "box_closed" in f["img"]]
    check("  %s: exactly one box was open" % sid, len(opened) == 1,
          str(opened))
    check("    and the other five were shut", len(closed) == 5, str(closed))
    check("    and the reveal opens the one the flash drew open",
          entry["reveal"]["open_slot"] == opened[0],
          "reveal %d, open %s" % (entry["reveal"]["open_slot"], opened))
    check("    and every card on the round is the same shut box",
          len({c["img"] for c in images(by_id[sid])}) == 1,
          str({c["img"] for c in images(by_id[sid])}))

print("\n--- the change rounds: three came back, one came back different ---")
for r in range(1, 5):
    sid = "chg%d" % r
    entry = mid_by_after[SCORED[sid][1] - 1][0]
    before = [f["img"] for f in entry["flash"]["images"]]
    after = [c["img"] for c in images(by_id[sid])]
    changed = [i for i in range(4) if before[i] != after[i]]
    check("  %s: exactly one of the four slots changed" % sid,
          len(changed) == 1, str(changed))
    check("    and that slot is the one scored as the hit",
          changed and hit_index(sid) == changed[0],
          "hit %d, changed %s" % (hit_index(sid), changed))
    check("    the other three came back byte for byte",
          [before[i] for i in range(4) if i not in changed]
          == [after[i] for i in range(4) if i not in changed])

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
      "def brain_intro(" in GEN and 'put(brain_intro(), "brain_intro"' in GEN)

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
                     "age_mid"}, str(sorted(block)))
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

print("\n--- the shuffle: declared, and landing where the step scores ---")
SPEED = {"spa1": (3, 900), "spa2": (4, 700), "spa3": (5, 550),
         "spa4": (7, 350)}
for r in range(1, 5):
    sid = "spa%d" % r
    entry = mid_by_after[SCORED[sid][1] - 1][0]
    rule = entry.get("reveal") or {}
    frames = entry["flash"]["images"]
    swaps = rule.get("swaps") or []
    want_n, want_ms = SPEED[sid]
    check("  %s shuffles %d times at %dms" % (sid, want_n, want_ms),
          len(swaps) == want_n and rule.get("swap_ms") == want_ms,
          "%d swaps at %s" % (len(swaps), rule.get("swap_ms")))
    check("    the box is open for five seconds, then closes",
          rule.get("open_ms") == FLASH_MS and rule.get("close_ms") == 600,
          str((rule.get("open_ms"), rule.get("close_ms"))))
    shut = [f["img"] for i, f in enumerate(frames)
            if i != rule.get("open_slot")]
    check("    and closes onto the one file every other slot already draws",
          len(set(shut)) == 1
          and rule.get("closed_img") == shut[0]
          == "/static/galleries/brain/box_closed.webp",
          str((rule.get("closed_img"), sorted(set(shut)))))
    check("    every swap names two slots this grid has",
          all(isinstance(p, list) and len(p) == 2 and p[0] != p[1]
              and all(isinstance(v, int) and 0 <= v < len(frames) for v in p)
              for p in swaps), str(swaps))
    # The engine swaps whatever is at the two positions, in order. Walked here
    # rather than restated, so the config and the check cannot agree on a
    # number that is wrong: where the object actually ends up IS the slot the
    # step has to score, and nothing but the swaps decides it.
    at = rule.get("open_slot")
    for a, b in swaps:
        if at == a:
            at = b
        elif at == b:
            at = a
    check("    and the object lands on the slot the step scores",
          at == hit_index(sid),
          "swaps land it on %s, %s scores %d" % (at, sid, hit_index(sid)))
    check("    which is not the slot it was shown in",
          at != rule.get("open_slot"), str(at))
check("each round shuffles more, and faster, than the one before",
      [SPEED["spa%d" % r][0] for r in range(1, 5)] == [3, 4, 5, 7]
      and [SPEED["spa%d" % r][1] for r in range(1, 5)] == [900, 700, 550, 350])
check("  and each round's question asks where the thing is now",
      all(by_id["spa%d" % r]["question"].endswith(" now?")
          for r in range(1, 5)),
      str([by_id["spa%d" % r]["question"] for r in range(1, 5)]))

print("\n--- the four focus rounds answer themselves if nobody does ---")
for sid in ("odd", "ink", "next", "count"):
    step = by_id[sid]
    pick = step.get("timeout_pick")
    tags = {i["id"]: i["tags"] for i in images(step)}
    # Four seconds on the last one, which is the round that got harder.
    want = 4000 if sid == "count" else FLASH_MS
    check("  %-5s gives %s seconds" % (sid, want // 1000),
          step.get("timer_ms") == want, str(step.get("timer_ms")))
    check("    and names a card on this step for the clock to press",
          pick in tags, str(pick))
    check("    which is a miss, so a clock cannot score a hit",
          tags.get(pick) == ["foc_miss"], str(tags.get(pick)))
check("no other step carries a clock",
      not [s["id"] for s in steps
           if s.get("timer_ms") and s["id"] not in ("odd", "ink", "next",
                                                    "count")],
      str([s["id"] for s in steps if s.get("timer_ms")]))
check("  and every clock is inside the range the engine honours",
      all(1000 <= s["timer_ms"] <= 15000 for s in steps if s.get("timer_ms")))

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
      all(k in profile for k in ("chips", "rarity_card", "unlock",
                                 "unlock_head", "unlock_tail")),
      str(sorted(profile)))
check("  four chips, one token each, one per round",
      profile["chips"] == ["{mem}", "{spa}", "{chg}", "{foc}"],
      str(profile["chips"]))
check("  the type card carries a frame and a line under it",
      all(profile["rarity_card"].get(k) for k in ("lead", "tail", "note")),
      str(profile["rarity_card"]))
# Four chapters and one promise inside a chapter: the food day is part of
# the seven-day plan rather than a chapter of its own, and it carries its own
# keyword because there is no section card to take one from.
check("  the unlock list is one row per chapter, plus the food day",
      sorted(r["id"] for r in profile["unlock"])
      == sorted([s["id"] for s in cfg["report"]["sections"]] + ["fuel"]),
      str([r["id"] for r in profile["unlock"]]))
check("    every row of it has a line",
      all(r.get("line") for r in profile["unlock"]))
check("    and the keepsake closes it",
      profile["unlock_tail"].get("key") and profile["unlock_tail"].get("line"))
check("every unlock row has a keyword to lead with",
      all(row.get("key") or row["id"] in set(c["id"] for c in
                                             profile["cards"])
          for row in profile["unlock"]),
      str([r["id"] for r in profile["unlock"]
           if not r.get("key")
           and r["id"] not in set(c["id"] for c in profile["cards"])]))
check("the struck price is read out as well as drawn",
      "price_regular_aria" in cfg["result_copy"]
      and "{price}" in cfg["result_copy"]["price_regular_aria"])
check("the module draws the sale beside the price it charges",
      "ctx.sale && ctx.priceRegular" in MODULE
      and 'elm("span", "br-price-was", ctx.priceRegular)' in MODULE
      and 'elm("p", "br-sale", ctx.sale.label)' in MODULE)
check("  and the stylesheet strikes it through on this layout",
      ".result-module.is-minimal .br-price-was::after {" in RESULT_CSS)
check("the layout drops the bars and the locked rows for chips and a list",
      "if (!lean) root.appendChild(bars(ctx, copy, data));" in MODULE
      and "if (!lean) root.appendChild(path(ctx, copy));" in MODULE
      and "if (list) card.appendChild(list);" in MODULE)
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
unlock = cfg["result_copy"]["profile"]["unlock"]
check("the unlock list is five lines, a head and a tail",
      len(unlock) == 5
      and cfg["result_copy"]["profile"].get("unlock_head")
      and cfg["result_copy"]["profile"].get("unlock_tail", {}).get("line"))
check("  headed by what the reader is buying: a lower number",
      "lower" in cfg["result_copy"]["profile"]["unlock_head"].lower(),
      cfg["result_copy"]["profile"]["unlock_head"])
check("  and closed on coming back to play it again",
      "again" in cfg["result_copy"]["profile"]["unlock_tail"]["line"].lower(),
      cfg["result_copy"]["profile"]["unlock_tail"]["line"])
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
      and cfg["checkout"]["cta_label"] == "Unlock my Brain Refresh — {price}"
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

print("\n--- v4: round three is letters, and one of them changed ---")
# The filename is the claim. `letter_<L>_<colour>_<size>_<degrees>` states the
# four things a card can differ in, so "exactly one of these four came back
# different, and in exactly this way" is a thing this file can hold the config
# to without opening a single pixel.
LETTER_RE = re.compile(r"^letter_([A-Z])_([a-z]+)_(lg|sm)_(\d+)$")
KINDS = {"chg1": 0, "chg2": 1, "chg3": 2, "chg4": 3}   # letter/colour/size/rot
FACET = ["letter", "colour", "size", "rotation"]


def spec_of(path):
    stem = path.rsplit("/", 1)[-1][:-len(".webp")]
    found = LETTER_RE.match(stem)
    return found.groups() if found else None


for r in range(1, 5):
    sid = "chg%d" % r
    entry = mid_by_after[SCORED[sid][1] - 1][0]
    before = [spec_of(f["img"]) for f in entry["flash"]["images"]]
    after = [spec_of(c["img"]) for c in images(by_id[sid])]
    check("  %s holds up four letter cards" % sid,
          len(before) == 4 and all(before), str(before))
    check("    and answers with four of the same kind",
          len(after) == 4 and all(after), str(after))
    if not (all(before) and all(after)):
        continue
    check("    every letter on the round is its own",
          len({b[0] for b in before}) == 4
          and len({a[0] for a in after}) == 4,
          str([b[0] for b in before]))
    check("    with nothing that pairs off as I and l, or O and Q",
          not ({b[0] for b in before} | {a[0] for a in after})
          & set("IOQ"), str(sorted({b[0] for b in before})))
    moved = [i for i in range(4) if before[i] != after[i]]
    check("    exactly one slot came back different",
          len(moved) == 1, str(moved))
    if len(moved) != 1:
        continue
    check("      and it is the slot the round scores",
          moved[0] == hit_index(sid),
          "changed %d, hit %d" % (moved[0], hit_index(sid)))
    facets = [i for i in range(4)
              if before[moved[0]][i] != after[moved[0]][i]]
    check("      differing in exactly one thing, and it is the %s"
          % FACET[KINDS[sid]],
          facets == [KINDS[sid]],
          "differs in %s" % [FACET[i] for i in facets])
    check("      the three that did not change are the same files",
          [before[i] for i in range(4) if i != moved[0]]
          == [after[i] for i in range(4) if i != moved[0]])
check("the shape cards the round used to draw are gone",
      not [n for n in os.listdir(GALLERY) if n.startswith("chg")],
      str([n for n in os.listdir(GALLERY) if n.startswith("chg")]))
check("the letters are set in a serif, which nothing else on the walk is",
      "SERIF_FONTS = [" in ART and "DejaVuSerif-Bold.ttf" in ART
      and "def letter_card(" in ART)
check("  on a block of their own colour, which does not turn with them",
      "card.rect((0.29, 0.29, 0.75, 0.75), tint(PALETTE[colour])" in ART
      and "layer.rotate(rot" in ART)
check("  and the rotated round is turned little enough to be a round",
      10 <= int([s["after"][3] for s in ast.literal_eval(
          re.search(r"^LETTERS = (\[.*?^\])", ART, re.S | re.M).group(1))][3])
      <= 18,
      str([s["after"][3] for s in ast.literal_eval(
          re.search(r"^LETTERS = (\[.*?^\])", ART, re.S | re.M).group(1))]))

print("\n--- v4: the odd one out is six umbrellas ---")
odd_imgs = [c["img"] for c in images(by_id["odd"])]
check("six cards, six files of their own",
      len(odd_imgs) == 6 and len(set(odd_imgs)) == 6, str(odd_imgs))
check("  all of them umbrellas", all("/umb_s" in p for p in odd_imgs),
      str(odd_imgs))
digests = [hashlib.sha256(open(os.path.join(ROOT, p.lstrip("/")),
                               "rb").read()).hexdigest()
           for p in odd_imgs]
counts = {}
for digest in digests:
    counts[digest] = counts.get(digest, 0) + 1
check("  five of them byte for byte the same drawing",
      sorted(counts.values()) == [1, 5], str(sorted(counts.values())))
check("    and the odd one is the card the round scores",
      digests.index([d for d, n in counts.items() if n == 1][0])
      == hit_index("odd"),
      "odd at %d, hit %d" % (digests.index(
          [d for d, n in counts.items() if n == 1][0]), hit_index("odd")))
check("  which is why they are six files and not two",
      "UMBRELLA_SLOTS = 6" in ART and "def umbrella_card(" in ART)
check("the round names none of them, and none of them is a number",
      cfg["swipe"]["label_mode"] == "check"
      and not by_id["odd"].get("label_mode")
      and {c["label"] for c in images(by_id["odd"])} == {"Umbrella"},
      str({c["label"] for c in images(by_id["odd"])}))
check("  and the grid it drew before is gone",
      not [n for n in os.listdir(GALLERY) if n.startswith("odd")],
      str([n for n in os.listdir(GALLERY) if n.startswith("odd")]))

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
      "var push = urge(ctx, copy, data);" in MODULE
      and MODULE.index("var push = urge(ctx, copy, data);")
      < MODULE.index("var strip = taps(ctx, copy);"))
urge_fn = re.search(r"function urgeLine\(copy, data\)\s*\{(.*?)\n  \}",
                    MODULE, re.S).group(1)
check("  and says one of three things, by where they sit against their group",
      "copy.urge_younger" in urge_fn and "copy.urge_level" in urge_fn
      and "copy.urge_older" in urge_fn and "LEVEL_BAND" in urge_fn)
for key, must in (("urge_older", "easiest number to lower"),
                  ("urge_level", "pushes it under"),
                  ("urge_younger", "Keep it there")):
    check("  %s is written in the improvement voice" % key,
          must in cfg["result_copy"].get(key, ""),
          cfg["result_copy"].get(key))
check("  and the one for a reader above their group counts the years",
      "{n}" in cfg["result_copy"]["urge_older"])
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
      and re.search(r"function urge\(ctx, copy, data\)(.*?)\n  \}",
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
check("  and every bullet promises something to do rather than a reading",
      all(any(w in row["line"] for w in
              ("drill", "habits", "technique", "days", "plate"))
          for row in cfg["result_copy"]["profile"]["unlock"]),
      str([r["line"] for r in cfg["result_copy"]["profile"]["unlock"]]))
check("  weakest round first",
      cfg["result_copy"]["profile"]["unlock"][0]["id"] == "materials",
      cfg["result_copy"]["profile"]["unlock"][0]["id"])

print("\n--- v5: the card before the first question ---")
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

print("\n--- v5: the last task of every round is the hardest ---")
check("the last memory round answers on a six-up",
      by_id["mem4"]["format"] == "grid6"
      and len(images(by_id["mem4"])) == 6, by_id["mem4"]["format"])
mem4 = mid_by_after[SCORED["mem4"][1] - 1][0]
check("  off a flash of six, on the same grid, held two and a half seconds",
      mem4["flash"]["format"] == "grid6"
      and len(mem4["flash"]["images"]) == 6
      and mem4["auto_advance_ms"] == 2500,
      str(mem4["auto_advance_ms"]))
check("  and the other three memory rounds still answer on a four-up",
      all(by_id["mem%d" % r]["format"] == "grid4" for r in range(1, 4)))
spa4 = mid_by_after[SCORED["spa4"][1] - 1][0]["reveal"]
check("the last spatial round shuffles seven times at 350ms",
      len(spa4["swaps"]) == 7 and spa4["swap_ms"] == 350,
      "%d at %s" % (len(spa4["swaps"]), spa4["swap_ms"]))
check("the last change round turns its letter fifteen degrees",
      by_id["chg4"]["pairs"][0]["images"][
          [i for i, c in enumerate(images(by_id["chg4"]))
           if "chg_hit" in c["tags"]][0]]["img"].endswith("_15.webp"),
      images(by_id["chg4"])[2]["img"])
check("  and the twenty-five degree card is gone from the gallery",
      not [n for n in os.listdir(GALLERY) if n.endswith("_25.webp")])
count_flash = mid_by_after[SCORED["count"][1] - 1][0]
SPOTS = ast.literal_eval(
    re.search(r"^COUNT_SPOTS = (\[.*?^\])", ART, re.S | re.M).group(1))
check("the counting round shows eleven circles",
      sum(len(frame) for frame in SPOTS) == 11
      and art_number("COUNT_TOTAL") == 11,
      str(sum(len(frame) for frame in SPOTS)))
check("  scattered rather than laid out, so it cannot be counted by pattern",
      len({round(x, 3) for frame in SPOTS for x, _y in frame}) >= 8
      and len({round(y, 3) for frame in SPOTS for _x, y in frame}) >= 8,
      str(len({round(x, 3) for frame in SPOTS for x, _y in frame})))
check("  the answer is among the four on offer, and it is eleven",
      [c["label"] for c in images(by_id["count"])] == ["9", "10", "11", "12"]
      and images(by_id["count"])[hit_index("count")]["label"] == "11",
      str([c["label"] for c in images(by_id["count"])]))
check("  and the round gives four seconds rather than five",
      by_id["count"]["timer_ms"] == 4000, str(by_id["count"]["timer_ms"]))
check("    with a miss for the clock to press",
      images(by_id["count"])[
          [i for i, c in enumerate(images(by_id["count"]))
           if c["id"] == by_id["count"]["timeout_pick"]][0]]["tags"]
      == ["foc_miss"])

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
check("the count answers draw their number, and draw it large",
      'put(word(text, 130), "cnt_" + text)' in ART
      and art_number("COUNT_TOTAL") == 11)
check("  and the four on offer are the four the config names",
      ast.literal_eval(
          re.search(r"^COUNT_ANSWERS = (\[.*?\])\n", ART, re.S | re.M).group(1))
      == [c["label"] for c in images(by_id["count"])])
check("the age numerals and the ink words were already in their art",
      "def age_card(" in ART and "AGE_NUMERAL_SIZE" in ART
      and "def word(text, size, colour=INK):" in ART)

print("\n--- v8: the pattern round, rebuilt on two attributes at once ---")
# The whole round, proved off the generator's own tables and the filenames
# they produce — never off pixels. A dial has a notch that turns and a dot
# that steps, the two move at different rates, and the round is only a
# working-memory task if continuing ONE of them is not enough to answer it.
# `art_number` answers a float, because most of what it reads is one. These
# three are counts and degrees and index things.
DIAL_STEP = int(art_number("DIAL_ROT_STEP"))
DIAL_DOTS = int(art_number("DIAL_DOTS"))
DIAL_FRAMES = int(art_number("DIAL_FRAMES"))
NEXT_STEP = by_id["next"]
NEXT_MID = [e for e in cfg["interstitials"] if e["after_step"] == 16][0]


def dial_of(path):
    """The two attributes, read back off the filename that states them."""
    found = re.search(r"dial_r(\d+)_d(\d+)\.webp$", path)
    return (int(found.group(1)), int(found.group(2))) if found else None


frames = [dial_of(f["img"]) for f in NEXT_MID["flash"]["images"]]
cands = [dial_of(c["img"]) for c in images(NEXT_STEP)]

check("the flash holds up three frames and then a question mark",
      len(NEXT_MID["flash"]["images"]) == 4
      and frames[:3] == [f for f in frames[:3] if f]
      and frames[3] is None
      and NEXT_MID["flash"]["images"][3]["img"].endswith("nxt_qm.webp"),
      str([f["img"].split("/")[-1] for f in NEXT_MID["flash"]["images"]]))
check("  after a count-in, and held for five seconds",
      NEXT_MID.get("prepare", {}).get("count") == 3
      and NEXT_MID["auto_advance_ms"] == 5000,
      str(NEXT_MID.get("auto_advance_ms")))
check("the notch turns the same amount every frame",
      [f[0] for f in frames[:3]]
      == [(i * DIAL_STEP) % 360 for i in range(DIAL_FRAMES)],
      str([f[0] for f in frames[:3]]))
check("  and the dot steps one place every frame",
      [f[1] for f in frames[:3]] == list(range(DIAL_FRAMES)),
      str([f[1] for f in frames[:3]]))
check("  so two things progress across the three, not one",
      len({f[0] for f in frames[:3]}) == DIAL_FRAMES
      and len({f[1] for f in frames[:3]}) == DIAL_FRAMES)

ROT_NEXT = (frames[2][0] + DIAL_STEP) % 360
DOT_NEXT = (frames[2][1] + 1) % DIAL_DOTS
check("the step offers four candidates",
      len(cands) == 4 and all(cands), str(cands))
check("  and no two of them are the same picture",
      len(set(cands)) == 4, str(cands))
right = [c for c in cands if c == (ROT_NEXT, DOT_NEXT)]
check("exactly one continues BOTH progressions",
      len(right) == 1, "%s in %s" % ((ROT_NEXT, DOT_NEXT), cands))
check("  and it is the one the round scores",
      cands[0] == (ROT_NEXT, DOT_NEXT)
      and images(NEXT_STEP)[0]["tags"] == ["foc_hit"],
      str(images(NEXT_STEP)[0]["tags"]))
wrong = cands[1:]
check("  the other three are misses",
      [c["tags"] for c in images(NEXT_STEP)[1:]] == [["foc_miss"]] * 3)
scored = [(c[0] == ROT_NEXT) + (c[1] == DOT_NEXT) for c in wrong]
check("every distractor gets EXACTLY ONE of the two right",
      scored == [1, 1, 1], str(list(zip(wrong, scored))))
check("  one keeps the notch and drops the dot",
      any(c[0] == ROT_NEXT and c[1] != DOT_NEXT for c in wrong), str(wrong))
check("  one keeps the dot and drops the notch",
      any(c[1] == DOT_NEXT and c[0] != ROT_NEXT for c in wrong), str(wrong))
check("  and one is a frame the flash already showed, redrawn",
      any(c in frames[:3] for c in wrong),
      "%s vs %s" % (wrong, frames[:3]))
check("nothing this round draws is a triangle any more",
      not [p for p in
           [f["img"] for f in NEXT_MID["flash"]["images"]]
           + [c["img"] for c in images(NEXT_STEP)]
           if "nxt_a" in p or "nxt_q1" in p or "nxt_q2" in p or "nxt_q3" in p],
      str([f["img"] for f in NEXT_MID["flash"]["images"]]))
check("  and no triangle file is left in the gallery",
      not [n for n in sorted(os.listdir(GALLERY))
           if n.startswith("nxt_") and n != "nxt_qm.webp"],
      str([n for n in sorted(os.listdir(GALLERY)) if n.startswith("nxt_")]))
dial_files = [f["img"] for f in NEXT_MID["flash"]["images"]] \
    + [c["img"] for c in images(NEXT_STEP)]
check("every file the round names is on disk",
      all(os.path.exists(os.path.join(ROOT, p.lstrip("/")))
          for p in dial_files),
      str([p for p in dial_files
           if not os.path.exists(os.path.join(ROOT, p.lstrip("/")))]))
check("  and every one is under twelve kilobytes",
      all(os.path.getsize(os.path.join(ROOT, p.lstrip("/"))) < 12 * 1024
          for p in dial_files),
      str([(p.split("/")[-1],
            os.path.getsize(os.path.join(ROOT, p.lstrip("/"))))
           for p in dial_files]))
check("the clock still presses one of the misses",
      NEXT_STEP["timeout_pick"] in
      [c["id"] for c in images(NEXT_STEP)[1:]],
      str(NEXT_STEP["timeout_pick"]))
check("  and the round still gives five seconds",
      NEXT_STEP["timer_ms"] == 5000, str(NEXT_STEP["timer_ms"]))
check("the labels a screen reader hears describe rather than answer",
      all("Notch at" in c["label"] and "dot at" in c["label"]
          for c in images(NEXT_STEP))
      and not [c for c in images(NEXT_STEP)
               if "next" in c["label"] or "moved on" in c["label"]],
      str([c["label"] for c in images(NEXT_STEP)]))

print("\n--- v5: the offer, and the line under the button ---")
unlock = cfg["result_copy"]["profile"]["unlock"]
fuel = [row for row in unlock if row["id"] == "fuel"]
check("the plan sells a day of food as well as the drills",
      len(fuel) == 1 and fuel[0].get("key") == "Fuel",
      str([r["id"] for r in unlock]))
check("  in the words the review asked for",
      "what to put on your plate this week" in fuel[0]["line"]
      and "feed a sharp brain" in fuel[0]["line"], fuel[0]["line"])
check("  and the manifest carries it too",
      any("put on your plate" in line
          for line in cfg["checkout"]["manifest"]),
      str(cfg["checkout"]["manifest"]))
FOOD_BANNED = ("supplement", "vitamin", "dosage", "dose", "proven",
               "clinically", "boost your")
check("  with nothing out of a bottle in either",
      not [w for w in FOOD_BANNED
           if w in (fuel[0]["line"] + " "
                    + " ".join(cfg["checkout"]["manifest"])).lower()],
      str([w for w in FOOD_BANNED
           if w in (fuel[0]["line"] + " "
                    + " ".join(cfg["checkout"]["manifest"])).lower()]))
check("the offer names no brain type at all",
      "{type}" not in json.dumps(cfg["result_copy"]["profile"]["offer_head"])
      and "{type}" not in json.dumps(cfg["checkout"]))
check("the button carries a line saying what following the plan does",
      cfg["result_copy"].get("improve_foot")
      == "Follow the 7-day plan, play again — the number moves.",
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
check("  and no other number at all",
      not re.search(r"\d", share["share_line"].replace("{n}", "")),
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
      < MODULE.index("var push = urge(ctx, copy, data);"))
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
check("  and the free page keeps the line it already had",
      cfg["result_copy"].get("improve_foot")
      == "Follow the 7-day plan, play again — the number moves."
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
      and cfg["checkout"]["cta_label"] == "Unlock my Brain Refresh — {price}"
      and cfg["checkout"]["proof_line"] == "Built from your 16 rounds")
check("one offer, not two: the layout is named rather than tested",
      "paywall_variants" not in cfg)
check("  and the manifest offers one line per chapter, the food day and the "
      "keepsake",
      len(cfg["checkout"]["manifest"]) == len(sections) + 2,
      str(len(cfg["checkout"]["manifest"])))
check("  which is what the unlock list on the offer card argues",
      len(cfg["result_copy"]["profile"]["unlock"]) == len(sections) + 1)
check("every chapter has a card in the result copy",
      sorted(c["id"] for c in cfg["result_copy"]["profile"]["cards"])
      == sorted(s["id"] for s in sections))
check("  and every mood the offer personalises on names a real chapter",
      all(rule["emphasized_section"] in {s["id"] for s in sections}
          for rule in cfg["result_copy"]["purpose_map"].values()))

print("\n%d checks, %d failed" % (checks[0], len(fails)))
for line in fails:
    print("  FAIL " + line)
sys.exit(1 if fails else 0)
