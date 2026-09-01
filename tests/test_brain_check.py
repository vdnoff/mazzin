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
import datetime
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
check("every card carries a label, because this funnel badges them all",
      cfg["swipe"]["label_mode"] == "badge"
      and all(i.get("label") for s in steps for i in images(s)))
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
    check("    held for five seconds",
          ms == FLASH_MS, str(ms))
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
check("nothing in the gallery is unreferenced",
      not [n for n in sorted(os.listdir(GALLERY))
           if "/static/galleries/brain/" + n not in set(paths)
           and n != "og.webp"],
      str([n for n in sorted(os.listdir(GALLERY))
           if "/static/galleries/brain/" + n not in set(paths)
           and n != "og.webp"]))

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
ceiling = block["base"] + block["per_miss"] * block["scored"]
check("a run that misses every round scores the formula's ceiling",
      brain_age(block["scored"]) == round(ceiling), str(brain_age(16)))
check("  which sits inside the clamp, so the clamp never bites either",
      block["min"] <= ceiling <= block["max"],
      "%s not in [%s, %s]" % (ceiling, block["min"], block["max"]))
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
         "spa4": (6, 400)}
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
      [SPEED["spa%d" % r][0] for r in range(1, 5)] == [3, 4, 5, 6]
      and [SPEED["spa%d" % r][1] for r in range(1, 5)] == [900, 700, 550, 400])
check("  and each round's question asks where the thing is now",
      all(by_id["spa%d" % r]["question"].endswith(" now?")
          for r in range(1, 5)),
      str([by_id["spa%d" % r]["question"] for r in range(1, 5)]))

print("\n--- the four focus rounds answer themselves if nobody does ---")
for sid in ("odd", "ink", "next", "count"):
    step = by_id[sid]
    pick = step.get("timeout_pick")
    tags = {i["id"]: i["tags"] for i in images(step)}
    check("  %-5s gives five seconds" % sid, step.get("timer_ms") == FLASH_MS,
          str(step.get("timer_ms")))
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
check("the age step names nothing — its art carries the bracket",
      by_id["age"].get("label_mode") == "none",
      str(by_id["age"].get("label_mode")))
check("the five rounds that must not name a card up front do not",
      sorted(s["id"] for s in steps if s.get("label_mode") == "on_tap")
      == ["count", "mem1", "mem2", "mem3", "mem4"],
      str(sorted(s["id"] for s in steps if s.get("label_mode") == "on_tap")))
check("  and every override is a mode the engine knows",
      all(s["label_mode"] in ("none", "on_tap", "badge")
          for s in steps if s.get("label_mode")))
check("every other step takes the funnel's own badge",
      cfg["swipe"]["label_mode"] == "badge")
check("the mood round asks the question the review asked for",
      by_id["mood"]["question"] == "How would you rate your brain right now?")

print("\n--- the launch offer ---")
import payments                                             # noqa: E402
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
check("  the unlock list is one row per chapter",
      sorted(r["id"] for r in profile["unlock"])
      == sorted(s["id"] for s in cfg["report"]["sections"]),
      str([r["id"] for r in profile["unlock"]]))
check("    every row of it has a line",
      all(r.get("line") for r in profile["unlock"]))
check("    and the keepsake closes it",
      profile["unlock_tail"].get("key") and profile["unlock_tail"].get("line"))
check("every unlock row has a keyword to lead with",
      set(r["id"] for r in profile["unlock"])
      <= set(c["id"] for c in profile["cards"]))
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

print("\n--- the copy: a game, and nothing that sounds like anything else ---")
BANNED = ("memory loss", "cognitive", "decline", "dementia", "test yourself",
          "health", "diagnosis")
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
      cfg["report"]["sections"][0]["title"] == "Your Brain Profile",
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
      cfg["checkout"]["product_name"] == "Your Brain Age Report"
      and cfg["checkout"]["cta_label"] == "Unlock my full report — {price}"
      and cfg["checkout"]["proof_line"] == "Built from your 16 rounds")
check("one offer, not two: the layout is named rather than tested",
      "paywall_variants" not in cfg)
check("  and the manifest still offers one line per chapter, plus the "
      "keepsake",
      len(cfg["checkout"]["manifest"]) == len(sections) + 1,
      str(len(cfg["checkout"]["manifest"])))
check("  which is what the unlock list on the offer card argues",
      len(cfg["result_copy"]["profile"]["unlock"]) == len(sections))
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
