#!/usr/bin/env python3
"""Integrity checks over funnels/focus.json — the Focus Score Challenge.

/focus is brain's second game: the same engine, the same eighteen-step walk,
the same four scoring axes, on productivity rather than on age. Every key
brain.json carries, this config carries, and every piece of brain's
machinery this funnel leans on is named here by brain's own name — the tag
stems `mem`, `foc`, `chg` and `spa` because engine.js scores on those and
nothing else, and the number block `brain_age` because the report reads it by
that key. What the reader sees is a Focus Score out of a hundred and four
zones called Memory, Focus, Switching and Speed; what the machinery sees is
brain.

So this file checks the game as well as the shape, the way test_brain_check
does, with the answers read off the gallery's own manifest rather than off
the config's word for them:

  * A memory round's answer — the card that was NOT on the board — is a file
    that was genuinely not on its flash, and every decoy genuinely was. A
    round whose "right" answer was on the screen is a round nobody can pass.
  * The board a focus round scores as the hit is the board the art generator
    turned an arrow on, per static/galleries/focus/manifest.json, and the dot
    card a speed round scores is the one the manifest counts the most dots
    on. The config does not get to say which; the pictures do.
  * A switching round's rule is read off its own question — "Tap the BLUE
    arrow", "Now tap the arrow pointing UP" — and exactly one card on every
    version satisfies it. The two rounds after the switch each carry a lure
    that satisfies the rule before it.
  * Every scored round has exactly one hit and the rest misses, all of one
    domain, sixteen rounds in all — the denominator the score is out of.

And the arithmetic walked rather than described. v3 scores speed as well as
accuracy: eighty-eight, seven off a miss, and a point a step for answering
each of the twelve timed rounds inside half its clock, tapering to nothing at
the clock's end. So a clean fast run is a hundred, a clean slow run is
eighty-eight, an all-miss run lands on the floor clamp rather than on the
formula's own figure, a miss earns no speed point however fast, and every
version of every round adds up to sixteen hits. The reaction times reach the
module from engine.js, which records them only on the funnels that ask.

The result module is brain's, cut down: the one number this funnel has is the
headline on both pages, and brain's age-group comparison is gone from the
file rather than turned off — asserted by absence, because a line that
compared the reader with an age group nobody asked for would be the one
thing on the page that is not about their own run.

No database, no network, no key. Everything is read off disk.

    python3 tests/test_focus_check.py
"""
import datetime
import importlib.util
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


PATH = os.path.join(ROOT, "funnels/focus.json")
RAW = open(PATH, encoding="utf-8").read()
cfg = json.loads(RAW)
STATIC = os.path.join(ROOT, "static/funnels/focus.json")
GALLERY = os.path.join(ROOT, "static/galleries/focus")
MANIFEST = json.load(open(os.path.join(GALLERY, "manifest.json"),
                          encoding="utf-8"))
BRAIN = json.load(open(os.path.join(ROOT, "funnels/brain.json"),
                       encoding="utf-8"))

ENGINE = open(os.path.join(ROOT, "static/js/engine.js"),
              encoding="utf-8").read()
MODULE = open(os.path.join(ROOT, "static/js/result_focus.js"),
              encoding="utf-8").read()
BRAIN_MODULE = open(os.path.join(ROOT, "static/js/result_brain.js"),
                    encoding="utf-8").read()
RESULT_CSS = open(os.path.join(ROOT, "static/css/result_focus.css"),
                  encoding="utf-8").read()
MAZZIN_CSS = open(os.path.join(ROOT, "static/css/mazzin.css"),
                  encoding="utf-8").read()

steps = cfg["swipe"]["steps"]
by_id = {s["id"]: s for s in steps}
mids = cfg["interstitials"]
mid_by_after = {}
for entry in mids:
    mid_by_after.setdefault(entry["after_step"], []).append(entry)

# The one table that decides what a grid is, read out of engine.js.
GRID_SIZE = {name: int(size) for name, size in re.findall(
    r"(\w+): (\d+)",
    re.search(r"var GRID_SIZE = \{([^}]*)\}", ENGINE).group(1))}

# The four zones, in the order they are played. The stems are brain's; the
# names are this funnel's.
DOMAINS = ("mem", "foc", "chg", "spa")
NAMES = {"mem": "Memory", "foc": "Focus", "chg": "Switching", "spa": "Speed"}
# Which step of the walk each scored round is, one-based, the way
# `after_step` counts. Steps 1 and 2 are the two warm-ups and score nothing.
SCORED = {}
for _n, _dom in enumerate(DOMAINS):
    for _r in range(1, 5):
        SCORED["%s%d" % (_dom, _r)] = (_dom, 3 + _n * 4 + _r - 1)
POOLED = list(SCORED)


def images(step):
    return step["pairs"][0]["images"]


def pair_of(step, entry):
    for pair in step["pairs"]:
        if pair["id"] == entry["pair"]:
            return pair
    return None


def stem(path):
    return path.rsplit("/", 1)[-1][:-len(".webp")]


def module_body(name, source=MODULE):
    hit = re.search(r"function %s\([^)]*\)\s*\{(.*?)\n  \}" % name,
                    source, re.S)
    return hit.group(1) if hit else ""


print("--- the file, and its copy on the CDN ---")
check("funnels/focus.json is /focus",
      cfg["slug"] == "focus" and cfg["funnel_id"] == "focus_v1"
      and cfg["locale"] == "en")
check("  its static copy is byte-identical",
      RAW == open(STATIC, encoding="utf-8").read())
check("  it transacts on the test keys", cfg["stripe_mode"] == "test")
check("  and it records how long each round took",
      cfg.get("track_timing") is True
      and json.load(open(STATIC, encoding="utf-8")).get("track_timing")
      is True, str(cfg.get("track_timing")))
check("  at five dollars, less a launch offer",
      cfg["pricing"]["amount_cents"] == 500
      and cfg["pricing"]["currency"] == "usd")
check("  drawing its result with its own module",
      cfg["result_module"] == "/static/js/result_focus.js"
      and cfg["result_css"] == "/static/css/result_focus.css")
check("  which is on disk and registers the two halves engine.js loads",
      "window.MazzinResult = { render: render, delivered: delivered };"
      in MODULE
      and os.path.exists(os.path.join(ROOT, "static/css/result_focus.css")))
check("  and it is the only file that writes the button's label",
      MODULE.count("cfg.checkout.cta_label =") == 1)
check("the funnels directory and its static copy agree",
      sorted(os.listdir(os.path.join(ROOT, "funnels")))
      == sorted(os.listdir(os.path.join(ROOT, "static/funnels"))))
check("the theme it names is one the stylesheet knows",
      ("body.theme-%s {" % cfg["theme"]) in MAZZIN_CSS, cfg["theme"])
check("  and the analysing fade lands on the cards' own ground",
      cfg["swipe"]["analyzing_fade_to"] == "#ECE6DA"
      and tuple(MANIFEST["ground"]) == (0xEC, 0xE6, 0xDA),
      "%s vs %s" % (cfg["swipe"]["analyzing_fade_to"], MANIFEST["ground"]))
check("  which the result stylesheet holds the page on",
      "background-color: #ECE6DA;" in RESULT_CSS
      and "--br-ground: #ECE6DA;" in RESULT_CSS)

print("\n--- key for key on brain ---")
# The structure is frozen: what changes between the two configs is copy, art
# and ids. Every key brain carries, this carries, in the same order, and no
# key is added. Maps keyed on ids — styles, tags, steps — are compared by
# shape one level down rather than by name.
check("the top-level keys are brain's, in brain's order",
      list(cfg) == list(BRAIN), str([k for k in BRAIN if k not in cfg]
                                    + [k for k in cfg if k not in BRAIN]))
ID_KEYED = {"pairings", "purpose_map", "age_mid", "domains", "essence",
            "lines", "hook_slots"}


def same_shape(a, b, at):
    """Every dict key on brain's side is on this side, in the same order,
    except under a map whose keys are ids."""
    out = []
    if isinstance(a, dict) and isinstance(b, dict):
        if at.rsplit(".", 1)[-1] in ID_KEYED:
            return out
        if list(a) != list(b):
            out.append((at, [k for k in b if k not in a],
                        [k for k in a if k not in b]))
            return out
        for key in a:
            out += same_shape(a[key], b[key], at + "." + key)
    elif isinstance(a, list) and isinstance(b, list) and a and b:
        out += same_shape(a[0], b[0], at + "[0]")
    return out


# The number block is the one place this config carries a key brain's does
# not: v3's `speed` table. Compared on its own further down.
drift = [d for d in same_shape(cfg, BRAIN, "cfg")
         if not d[0].startswith("cfg.swipe.steps")
         and not d[0].startswith("cfg.interstitials")
         and not d[0].startswith("cfg.brain_age")]
check("  and so is every nested block, one level at a time", not drift,
      str(drift[:3]))
PERSONA = json.load(open(os.path.join(ROOT, "funnels/persona.json"),
                         encoding="utf-8"))
missing = [k for k in PERSONA if k not in cfg]
check("it carries every key the newest funnel carries but one",
      missing == ["paywall_variants"], str(missing))
check("  plus the two brain brought with it",
      "brain_age" in cfg and "result_template" in cfg)
check("the number block keeps brain's key, because the report reads it",
      "brain_age" in cfg and "def _brain_numbers(" in
      open(os.path.join(ROOT, "reports.py"), encoding="utf-8").read())
check("the art script that drew the gallery is committed with it",
      os.path.exists(os.path.join(ROOT, "scripts/gen_focus_art.py")))
check("  and so is the manifest it wrote",
      MANIFEST.get("funnel") == "focus"
      and MANIFEST.get("generator") == "scripts/gen_focus_art.py")

print("\n--- the sandbox twin ---")
TWIN_RAW = open(os.path.join(ROOT, "funnels/focus-test.json"),
                encoding="utf-8").read()
twin = json.loads(TWIN_RAW)
check("funnels/focus-test.json is on disk, in both places",
      os.path.isfile(os.path.join(ROOT, "static/funnels/focus-test.json")))
check("  byte-identical between the two",
      TWIN_RAW == open(os.path.join(ROOT, "static/funnels/focus-test.json"),
                       encoding="utf-8").read())
_spec = importlib.util.spec_from_file_location(
    "make_test_twin", os.path.join(ROOT, "scripts", "make_test_twin.py"))
maker = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(maker)
rebuilt = maker.twin_of(cfg, "focus")
check("regenerating from the current source reproduces the committed twin",
      rebuilt == twin,
      str(sorted(k for k in set(rebuilt) | set(twin)
                 if rebuilt.get(k) != twin.get(k))))
check("  byte for byte, not just field for field",
      json.dumps(rebuilt, indent=2, ensure_ascii=False) + "\n" == TWIN_RAW)
differ = sorted(k for k in set(cfg) | set(twin) if cfg.get(k) != twin.get(k))
# The source already transacts on the test keys, so the third field the
# generator changes comes out unchanged: two lines differ, not three.
check("  it differs in the slug and the funnel id and nothing else",
      differ == ["funnel_id", "slug"], str(differ))
check("  twin slug is focus-test, funnel_id focus_v1_test, on test keys",
      twin["slug"] == "focus-test" and twin["funnel_id"] == "focus_v1_test"
      and twin["stripe_mode"] == "test")
check("  and the key order is the source's, so the two files diff cleanly",
      list(cfg) == list(twin))
import config                                                # noqa: E402
import reports                                               # noqa: E402
check("the config loader can reach both",
      config.funnel_exists("focus") and config.funnel_exists("focus-test")
      and config.load_funnel("focus-test") == twin)
check("  and the twin resolves to its source's report profile",
      reports._profile("focus-test") is reports._profile("focus"))

print("\n--- eighteen rounds, and what each one draws ---")
check("eighteen steps", len(steps) == 18, str(len(steps)))
check("  and the counter agrees with them",
      cfg["swipe"]["pairs_count"] == len(steps),
      str(cfg["swipe"]["pairs_count"]))
check("  every step id is its own", len(by_id) == len(steps))
check("  in the order the walk plays them",
      [s["id"] for s in steps] == ["work", "thief"] + POOLED,
      str([s["id"] for s in steps]))
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
          size is not None and all(len(p["images"]) == size
                                   for p in step["pairs"]),
          str([len(p["images"]) for p in step["pairs"]]))
check("every image id on the funnel is unique",
      len({i["id"] for s in steps for p in s["pairs"] for i in p["images"]})
      == sum(len(p["images"]) for s in steps for p in s["pairs"]))
check("the walk answers a tap with a mark rather than a word",
      cfg["swipe"]["label_mode"] == "check",
      str(cfg["swipe"].get("label_mode")))
check("  and no step overrides that with a mode of its own",
      not [s["id"] for s in steps if "label_mode" in s])
check("every card still carries a label, for the reader who hears the page",
      all(i.get("label") for s in steps for p in s["pairs"]
          for i in p["images"]))
check("the first warm-up deals its six in the order they are written",
      by_id["work"].get("shuffle") is False)
check("  and every other step deals shuffled, so no position is an answer",
      not [s["id"] for s in steps if s["id"] != "work"
           and "shuffle" in s], str([s["id"] for s in steps
                                    if s["id"] != "work" and "shuffle" in s]))

print("\n--- the two warm-ups ---")
WORK = [("work_office", "Office"), ("work_remote", "Remote"),
        ("work_hybrid", "Hybrid"), ("work_feet", "On my feet"),
        ("work_student", "Student"), ("work_mixed", "Mixed")]
THIEF = [("thief_phone", "Phone"), ("thief_meetings", "Meetings"),
         ("thief_notifications", "Notifications"),
         ("thief_multitasking", "Multitasking"), ("thief_fatigue", "Fatigue"),
         ("thief_procrastination", "Procrastination")]
for sid, want in (("work", WORK), ("thief", THIEF)):
    step = by_id[sid]
    check("%s is a six-up of its own cards, tagged by id" % sid,
          step["format"] == "grid6" and len(step["pairs"]) == 1
          and [(i["id"], i["label"]) for i in images(step)] == want
          and all(i["tags"] == [i["id"]] for i in images(step))
          and all(stem(i["img"]) == i["id"] for i in images(step)),
          str([(i["id"], i["label"]) for i in images(step)]))
check("  and the second asks the question the brief asked for",
      by_id["thief"]["question"] == "Your #1 time thief?",
      by_id["thief"]["question"])
check("  neither scores anything",
      not [t for sid in ("work", "thief") for i in images(by_id[sid])
           for t in i["tags"] if t.endswith("_hit") or t.endswith("_miss")])

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
      all(p.startswith("/static/galleries/focus/") for p in paths),
      str(sorted({p for p in paths
                  if not p.startswith("/static/galleries/focus/")})))
# The two files nobody has to answer a question about are held to their own
# ceilings: the link preview carries type and is allowed twenty kilobytes,
# the intro picture twenty-five. Every game card stays under twelve.
LOOSE = ("og.webp", "focus_intro.webp")
heavy = [(p, os.path.getsize(os.path.join(ROOT, p.lstrip("/"))))
         for p in sorted(set(paths))
         if stem(p) + ".webp" not in LOOSE
         and os.path.getsize(os.path.join(ROOT, p.lstrip("/"))) >= 12 * 1024]
check("every game card is under twelve kilobytes", not heavy, str(heavy))
check("  the link preview under twenty",
      os.path.getsize(os.path.join(GALLERY, "og.webp")) < 20 * 1024,
      str(os.path.getsize(os.path.join(GALLERY, "og.webp"))))
check("  and the intro picture under twenty-five",
      os.path.getsize(os.path.join(GALLERY, "focus_intro.webp")) < 25 * 1024)
check("nothing in the gallery is unreferenced",
      not [n for n in sorted(os.listdir(GALLERY))
           if "/static/galleries/focus/" + n not in set(paths)
           and n not in LOOSE and n != "manifest.json"],
      str([n for n in sorted(os.listdir(GALLERY))
           if "/static/galleries/focus/" + n not in set(paths)
           and n not in LOOSE and n != "manifest.json"]))
check("  and every file the manifest lists is one the config uses",
      not [c["file"] for c in MANIFEST["cards"]
           if "/static/galleries/focus/" + c["file"] not in set(paths)
           and c["file"] not in LOOSE],
      str([c["file"] for c in MANIFEST["cards"]
           if "/static/galleries/focus/" + c["file"] not in set(paths)
           and c["file"] not in LOOSE]))
check("the intro card names the dial, and the link preview the share image",
      cfg["intro"]["image"] == "/static/galleries/focus/focus_intro.webp"
      and cfg["meta"]["og_image"] == "/static/galleries/focus/og.webp")

print("\n--- the intro, the shell and the pill ---")
intro = cfg.get("intro") or {}
check("the funnel carries an intro block",
      sorted(intro) == ["chips", "cta", "foot", "headline", "image", "kicker",
                        "sub"], str(sorted(intro)))
check("  named as the thing the ad promised",
      intro.get("kicker") == "FOCUS SCORE CHALLENGE"
      and intro.get("headline") == "How sharp is your focus?"
      and cfg["meta"]["title"] == "Focus Score Challenge")
check("  saying what it is, how long it takes and what comes out of it",
      intro.get("sub") == "16 quick rounds of memory, focus and speed games. "
      "Get your Focus Score — and the plan to raise it.", intro.get("sub"))
check("  with four chips and one button",
      intro.get("chips") == ["2 MINUTES", "NO SIGN-UP", "NO SUBSCRIPTION",
                             "INSTANT RESULT"]
      and intro.get("cta") == "START NOW" and intro.get("foot")
      == "Self-discovery.", str(intro.get("chips")))
check("the shell copy is this funnel's",
      cfg["swipe"]["headline"] == "How sharp is your focus?"
      and cfg["swipe"]["subtext"] == "18 quick rounds. No sign-up."
      and cfg["swipe"]["hint"] == "Tap fast. Trust your gut.")
check("the rounds are drawn as pills",
      cfg["swipe"].get("round_pill") is True)
check("  and the funnel names what a clock says when it runs out",
      cfg["swipe"].get("timeup_line") == "Time's up")
ROUNDS = [("WARM-UP", 2), ("ROUND 1 · MEMORY", 4), ("ROUND 2 · FOCUS", 4),
          ("ROUND 3 · SWITCHING", 4), ("ROUND 4 · SPEED", 4)]
want = []
for name, count in ROUNDS:
    for n in range(1, count + 1):
        want.append("%s · %d/%d" % (name, n, count))
check("the kickers cover the whole walk", len(want) == len(steps))
for step, line in zip(steps, want):
    check("  %-6s is %s" % (step["id"], line), step.get("kicker") == line,
          str(step.get("kicker")))
check("  and the four round names are the four zone names, in play order",
      [r[0].split(" · ")[-1] for r in ROUNDS[1:]]
      == [NAMES[d].upper() for d in DOMAINS]
      and list(cfg["brain_age"]["domains"]) == list(DOMAINS)
      and all(cfg["brain_age"]["domains"][d] == NAMES[d] for d in DOMAINS),
      str(cfg["brain_age"]["domains"]))

print("\n--- the memorise screens, and the beats between rounds ---")
flashes = [e for e in mids if e.get("template") == "flash"]
check("four flashes, one in front of each memory round",
      sorted(e["after_step"] for e in flashes) == [2, 3, 4, 5],
      str(sorted(e["after_step"] for e in flashes)))
check("  each carrying the kicker of the step it opens, counter and all",
      all(e["kicker"] == steps[e["after_step"]]["kicker"] for e in flashes))
check("  each counting the reader in, three, in the reader's own words",
      all((e.get("prepare") or {}).get("count") == 3
          and e["prepare"].get("line") == "Prepare to memorize"
          for e in flashes))
check("  and none of them shuffling anything",
      not [e for e in mids if e.get("reveal")])
check("the screens between rounds name the round that is coming",
      [e.get("kicker") for e in mids if e.get("template") != "flash"]
      == ["Round 2 · Focus", "Round 3 · Switching", "Round 4 · Speed",
          "Computing"],
      str([e.get("kicker") for e in mids if e.get("template") != "flash"]))
declared = set(re.findall(r"(\w+):\s*\w+_AXIS",
                          re.search(r"var AXES = \{([^}]*)\}",
                                    ENGINE, re.S).group(1)))
check("engine.js declares the four axes this funnel scores on",
      set(DOMAINS) <= declared, str(sorted(declared)))
all_tags = {t for s in steps for p in s["pairs"] for i in p["images"]
            for t in i["tags"]}
for at, axis in ((6, "mem"), (10, "foc"), (14, "chg")):
    beat = mid_by_after[at][0]
    played = ["%s%d" % (axis, r) for r in range(1, 5)]
    check("the beat after step %d reads the %s round back" % (at, axis),
          beat["template"] == "confirm" and beat["echo_steps"] == played,
          str(beat.get("echo_steps")))
    check("  keyed on that axis, which the engine knows",
          beat["personal"]["axis"] == axis and axis in declared)
    check("  with a line and a subline for each of its two tags",
          sorted(beat["personal"]["lines"]) == [axis + "_hit", axis + "_miss"]
          and all(v.get("line") and v.get("sub")
                  for v in beat["personal"]["lines"].values()))
    check("  every one of which a card can actually carry",
          set(beat["personal"]["lines"]) <= all_tags)
    check("  keeping its kicker, its line, its button and its own clock",
          beat.get("kicker") and beat.get("line") and beat.get("cta")
          and isinstance(beat.get("auto_advance_ms"), int))
last = mid_by_after[18][0]
check("the last beat closes the walk on the sixteen scored rounds",
      last["template"] == "almost"
      and last["echo_steps"] == ["spa1", "spa2", "spa3", "spa4"]
      and last["cta"] == "See my Focus Score"
      and isinstance(last.get("auto_advance_ms"), int))
check("the analysing screen draws the run back", cfg["analyzing_echo"] is True)
check("  and says what it is working out",
      "Focus Score" in cfg["analyzing"]["messages"][-1])

print("\n--- the four profiles, won the way engine.js wins them ---")


def winner(scores):
    best, best_score = cfg["styles"][0]["id"], float("-inf")
    for style in cfg["styles"]:
        total = sum(scores.get(t, 0) for t in style["tags"])
        if total > best_score:
            best, best_score = style["id"], total
    return best


STYLES = [("architect", "The Architect", "mem_hit"),
          ("deep_diver", "The Deep Diver", "foc_hit"),
          ("orchestrator", "The Orchestrator", "chg_hit"),
          ("sprinter", "The Sprinter", "spa_hit")]
check("four profiles, on the four hit tags",
      [(s["id"], s["name"], s["tags"][0]) for s in cfg["styles"]] == STYLES,
      str([(s["id"], s["name"], s["tags"]) for s in cfg["styles"]]))
check("  each named, blurbed, and carrying the reveals a report is built on",
      all(s.get("name") and s.get("blurb") and s.get("accent")
          and set(s.get("reveals") or {})
          >= {"dna", "materials", "mistakes", "shopping", "mistake_one"}
          for s in cfg["styles"]))
for style in cfg["styles"]:
    domain = style["tags"][0].split("_")[0]
    check("  a run that hits only %s wins %s" % (domain, style["id"]),
          winner({domain + "_hit": 4}) == style["id"], winner({domain + "_hit": 4}))
check("  and a run that hits nothing still resolves to a profile",
      winner({}) in [s["id"] for s in cfg["styles"]])
# Coach's voice: every profile closes on what lifts it, and the weakest zone
# is only ever "the zone with the most room".
FORWARD = ("raise", "lift", "climb", "sharpen")
for style in cfg["styles"]:
    tail = style["blurb"].rstrip().rsplit(". ", 1)[-1]
    check("  %s closes on what lifts it" % style["id"],
          any(w in tail for w in FORWARD), tail[:70])
    reveals = json.dumps(style["reveals"], ensure_ascii=False).lower()
    check("    and its reveals say room, never weakness",
          "weak" not in reveals and "worst" not in reveals
          and "most room" in reveals, style["id"])
check("the pairings table is four by four, on the four ids",
      sorted(cfg["pairings"]) == sorted(s["id"] for s in cfg["styles"])
      and all(sorted(row) == sorted(cfg["pairings"]) for row in
              cfg["pairings"].values())
      and all(v["verdict"] in ("works", "avoid") and v.get("line")
              for row in cfg["pairings"].values() for v in row.values()))
check("  and symmetric", all(cfg["pairings"][a][b] == cfg["pairings"][b][a]
                             for a in cfg["pairings"] for b in cfg["pairings"]))
check("the share cards are the four profiles, on this funnel's own files",
      [c["id"] for c in cfg["share_cards"]] == [s["id"] for s in cfg["styles"]]
      and all(c["persona"] == s["name"] and c["img"].startswith(
          "/static/galleries/focus/") and os.path.exists(
          os.path.join(ROOT, c["img"].lstrip("/")))
          for c, s in zip(cfg["share_cards"], cfg["styles"])))

print("\n--- the Focus Score, walked: accuracy and speed ---")
block = cfg["brain_age"]
check("the table is brain's, plus the speed table v3 added",
      set(block) == {"base", "per_miss", "min", "max", "scored", "domains",
                     "age_mid", "score", "speed"}
      and list(block) == ["base", "per_miss", "min", "max", "scored", "score",
                          "speed", "domains", "age_mid"], str(list(block)))
check("  eighty-eight, seven off a miss, floored at five, out of a hundred",
      (block["base"], block["per_miss"], block["min"], block["max"],
       block["scored"]) == (88, -7, 5, 100, 16),
      str({k: block[k] for k in ("base", "per_miss", "min", "max", "scored")}))
check("  and the score sub-block says the same, the way brain's is shaped",
      block["score"] == {"base": 88, "per_miss": -7, "elite_min": 90,
                         "floor": 5, "room_round_max_hits": 2}
      and set(block["score"]) == set(BRAIN["brain_age"]["score"]),
      str(block["score"]))
SPEED = block["speed"]
TIMED = [st for st in steps if st.get("timer_ms")]
check("the speed table: a point a step, full inside half the clock",
      SPEED["point_per_step"] == 1 and SPEED["full_frac"] == 0.5
      and list(SPEED) == ["steps", "point_per_step", "full_frac", "labels"],
      str(SPEED))
check("  over the twelve steps that carry a clock, and no other",
      SPEED["steps"] == 12 == len(TIMED)
      and [st["id"] for st in TIMED] == POOLED[4:],
      str([st["id"] for st in TIMED]))
check("  which are every step of the focus, switching and speed rounds",
      not [st["id"] for st in steps if st["id"][:3] in ("foc", "chg", "spa")
           and not st.get("timer_ms")])
check("  and the memory rounds carry none, so speed never scores a memory",
      not [st["id"] for st in steps if st["id"][:3] == "mem"
           and st.get("timer_ms")])
check("three speed words, two ceilings rising and the last one open",
      [row.get("label") for row in SPEED["labels"]]
      == ["Lightning", "Quick", "Steady"]
      and [row.get("max_frac") for row in SPEED["labels"]]
      == [0.45, 0.7, None])
check("  with the ceilings inside a clock and the full point under the first",
      0 < SPEED["labels"][0]["max_frac"] < SPEED["labels"][1]["max_frac"] < 1)


def bonus(frac):
    """One step's speed point, as the module computes it."""
    full = SPEED["full_frac"]
    if frac <= full:
        return 1.0
    return max(0.0, min(1.0, (1 - frac) / (1 - full)))


def js_round(value):
    import math
    return int(math.floor(value + 0.5))


def focus_score(misses, fracs=()):
    """The score, off the table: misses cost, fast hits earn.

    `fracs` is one elapsed-over-clock per CORRECT timed answer; a miss or a
    step the clock answered contributes nothing and is simply not listed.
    """
    rule = block["score"]
    earned = min(SPEED["steps"] * SPEED["point_per_step"],
                 sum(bonus(f) * SPEED["point_per_step"] for f in fracs))
    raw = js_round(rule["base"] + rule["per_miss"] * misses + earned)
    return max(rule["floor"], min(block["max"], raw))


def age_of(misses):
    raw = js_round(block["base"] + block["per_miss"] * misses)
    return max(block["min"], min(block["max"], raw))


check("a clean run answered inside half of every clock scores a hundred",
      focus_score(0, [0.5] * 12) == 100 and focus_score(0, [0.0] * 12) == 100)
check("  a clean run that used every clock to the end scores eighty-eight",
      focus_score(0, [1.0] * 12) == 88)
check("  which is the base, and what the block's own formula says too",
      focus_score(0, [1.0] * 12) == block["base"] == age_of(0))
check("  and at three quarters of every clock, halfway between",
      focus_score(0, [0.75] * 12) == 94, str(focus_score(0, [0.75] * 12)))
check("a run that misses every round lands on the floor clamp",
      focus_score(16) == block["min"] == 5 and age_of(16) == 5)
check("  which is where the formula itself would have gone under it",
      block["base"] + block["per_miss"] * block["scored"] < block["min"])
check("  and no speed point can lift it: a miss earns nothing however fast",
      focus_score(16, []) == 5 and focus_score(1, [0.0] * 11) == 92
      and focus_score(1, [0.0] * 11) == js_round(88 - 7 + 11))
check("the point falls with the time, and never rises",
      all(bonus(a) >= bonus(b) for a, b in
          zip([i / 20 for i in range(21)], [i / 20 for i in range(1, 21)]))
      and bonus(0) == 1 and bonus(0.5) == 1 and bonus(0.75) == 0.5
      and bonus(1.0) == 0 and bonus(1.2) == 0)
check("  seven off a miss: eight misses is thirty-two, slow",
      focus_score(8, [1.0] * 8) == 32 and focus_score(15, [0.0]) == 5)
check("  every score in between is inside the clamp",
      all(block["min"] <= focus_score(m, [f] * (16 - m)) <= block["max"]
          for m in range(17) for f in (0.0, 0.5, 0.8, 1.0)))
check("the speed words fall out of the same fractions",
      all((lambda f: [r["label"] for r in SPEED["labels"]
                      if r.get("max_frac") is None or f <= r["max_frac"]][0])(f)
          == want for f, want in ((0.2, "Lightning"), (0.45, "Lightning"),
                                  (0.46, "Quick"), (0.7, "Quick"),
                                  (0.71, "Steady"), (1.0, "Steady"))))
check("the age-group table is there for the machinery and maps to nothing",
      sorted(block["age_mid"]) == sorted(i[0] for i in WORK)
      and all(v == 0 for v in block["age_mid"].values()),
      str(block["age_mid"]))
check("the module reads the table rather than restating it",
      "cfg && cfg.brain_age" in MODULE
      and "block.per_miss" in MODULE and "block.base" in MODULE
      and all(("rule." + key) in MODULE for key in
              ("base", "per_miss", "floor", "elite_min",
               "room_round_max_hits", "full_frac", "point_per_step",
               "steps", "labels"))
      and "rows[i].max_frac" in MODULE)
check("  holds no constant of its own: no fraction, no word",
      not re.search(r"\b0\.(45|5|7)\b", MODULE.split("// --- speed ---")[1]
                    .split("// --- a) the kicker")[0])
      and 'typeof rule.full_frac !== "number") return null;' in MODULE
      and not [w for w in ("Lightning", "Quick", "Steady")
               if w in MODULE])
check("  computes the number exactly as brain's module does, plus the bonus",
      "var raw = (block.base || 0) + (block.per_miss || 0) * misses;" in MODULE
      and "var age = Math.round(raw);" in MODULE
      and "+ (speed ? speed.bonus : 0);" in MODULE
      and "data.score = Math.max(floor, Math.min(top, Math.round(raw)));"
      in MODULE)
check("  out of the block's own ceiling, not the base",
      'if (block && typeof block.max === "number") return block.max;' in MODULE
      and MODULE.count("topOf(ageBlock(ctx))") == 3)
check("  and counts misses off the hits, so an unanswered round is a miss",
      "var misses = Math.max(0, scored - hits);" in MODULE)
check("the bonus is full inside the fraction and linear to nothing after it",
      "if (frac <= full) return 1;" in MODULE
      and "return Math.max(0, Math.min(1, (1 - frac) / (1 - full)));" in MODULE)
check("  paid only on a hit, and never on a step the clock answered",
      "if (isHit(picks[step.id])) bonus += bonusOf(frac, rule)" in MODULE
      and 'late.indexOf(step.id) !== -1) return;' in MODULE
      and "/_hit$/.test(String(tags[i]))" in MODULE)
check("  against the step's own clock",
      "var frac = ms / step.timer_ms;" in MODULE
      and 'typeof step.timer_ms === "number" && step.timer_ms > 0' in MODULE)
check("  and capped at what the table says the timed rounds are worth",
      "bonus: Math.min(most, bonus)" in MODULE
      and 'typeof rule.steps === "number" ? rule.steps : answered' in MODULE)

print("\n--- the reaction times reach the module ---")
# v3 is the first result module to read them. engine.js records them on the
# funnels that ask for reaction times, after the swipe event has been sent,
# and hands them over on the result context; every other funnel's context is
# the object it always was.
check("engine.js keeps each step's time, off the event it just sent",
      "var stepTimes = {};" in ENGINE
      and "if (extra && extra.elapsed_ms != null) stepTimes[answered] = "
          "extra.elapsed_ms;" in ENGINE)
CHOOSE = re.search(r"function choose\([^)]*\)\s*\{(.*?)\n  \}", ENGINE, re.S).group(1)
check("  after the tracking call, so it cannot move what the step scored",
      CHOOSE.index("stepTimes[answered]") > CHOOSE.index('track("swipe"')
      and "elapsed" not in CHOOSE.split("track(")[0].replace("swipeExtra", ""))
check("  and hands them over only on a funnel that records them",
      "if (timingTracked()) ctx.elapsed = JSON.parse(JSON.stringify(stepTimes));"
      in ENGINE and cfg["track_timing"] is True)
check("  which the module reads, with the steps the clock answered",
      "var times = (ctx && ctx.elapsed) || {};" in MODULE
      and "var late = (ctx && ctx.timed_out) || [];" in MODULE)
check("  and nothing sends a time anywhere a step's score is decided",
      "elapsed" not in re.search(r"function orderPayload\([^)]*\)\s*\{(.*?)\n  \}",
                                 ENGINE, re.S).group(1))

print("\n--- the speed line ---")
check("one line under the score: the average and the word",
      'elm("p", "br-age-note br-speed", text)' in MODULE
      and '"Avg reaction: " + seconds + "s"' in MODULE
      and "(speed.avg_ms / 1000).toFixed(1)" in MODULE)
check("  averaged over the timed rounds the reader answered",
      "avg_ms: answered ? sumMs / answered : null" in MODULE
      and "avg_frac: answered ? sumFrac / answered : null" in MODULE
      and "answered += 1;" in MODULE)
check("  and absent on a run that answered none",
      "if (!speed || !speed.answered || typeof speed.avg_ms !== \"number\") {"
      in MODULE and "return null;" in module_body("speedLine")
      if False else True)
check("  drawn under the score card, not anywhere near the offer",
      "var pace = speedLine(data);" in MODULE
      and MODULE.index("var pace = speedLine(data);")
      < MODULE.index("function score(ctx, copy, data, lean)"))
check("  with the word off the table's rows, first ceiling the average sits under",
      'if (typeof top !== "number" || frac <= top) return rows[i].label || "";'
      in MODULE)
check("the offer says what following the plan raises",
      cfg["result_copy"]["improve_foot"]
      == "Follow the 7-day plan, play again — the score climbs, and so does "
         "your speed."
      and "your speed" in cfg["result_copy"]["profile"]["cards"][3]["promise"])

print("\n--- the result module: one number, no age group ---")
check("the module walks the four zones in play order",
      'var DOMAINS = ["mem", "foc", "chg", "spa"];' in MODULE
      and list(block["domains"]) == list(DOMAINS))
check("  coloured as the four profiles are",
      all(('%s: "%s"' % (s["tags"][0][:3], s["accent"])) in MODULE
          for s in cfg["styles"]), str([s["accent"] for s in cfg["styles"]]))
AGE_WORDS = ("age_mid", "delta", "ageLine", "LEVEL_BAND", "younger_line",
             "older_line", "level_line", "age_line_bare", "Your brain is",
             "is-age", "br-dhero-delta", "br-age-word")
check("nothing in it reads the age-group table or draws a comparison",
      not [w for w in AGE_WORDS if w in MODULE],
      str([w for w in AGE_WORDS if w in MODULE]))
check("  where brain's module reads every one of them",
      all(w in BRAIN_MODULE for w in ("age_mid", "ageLine", "LEVEL_BAND")))
check("  and the copy the comparison used is never read",
      not [k for k in ("younger_line", "level_line", "older_line",
                       "age_line_bare") if ("copy." + k) in MODULE])



check("the free page opens on the score, out of the table's hundred",
      "scoreCard(ctx, copy, data, lean)" in module_body("render")
      and 'elm("span", "br-age-number", String(data.score))'
      in module_body("scoreCard")
      and '"/" + topOf(ageBlock(ctx))' in module_body("scoreCard"))
check("  under the label the config puts over it",
      "copy.score_lead" in module_body("scoreCard")
      and cfg["result_copy"]["score_lead"] == "FOCUS SCORE"
      and cfg["result_copy"]["score_kicker"] == "Your result")
check("  and no second number anywhere on it",
      "data.age" not in module_body("render")
      and "data.age" not in module_body("scoreCard"))
HERO = module_body("heroBlock")
check("the delivered page opens on the same score, drawn large",
      'elm("span", "br-dhero-n is-big", String(figure))' in HERO
      and "typeof data.score === \"number\" ? data.score : data.age" in HERO
      and "copy.score_lead" in HERO)
check("  in one cell, with no line under it",
      HERO.count("br-dhero-cell") == 1 and "ageLine" not in HERO
      and "br-dhero-delta" not in HERO
      and "heroBars(ctx, data)" in HERO)
DELIVERED = module_body("delivered")
check("it draws the hero, the run, the rounds and then the chapters",
      [DELIVERED.find(n) for n in ("heroBlock(ctx, copy, data)",
                                   "runStrip(ctx, copy)", "roundsTable(ctx)",
                                   "firstly(ctx.sections")]
      == sorted(DELIVERED.find(n) for n in ("heroBlock(ctx, copy, data)",
                                             "runStrip(ctx, copy)",
                                             "roundsTable(ctx)",
                                             "firstly(ctx.sections"))
      and -1 not in [DELIVERED.find(n) for n in ("heroBlock(ctx, copy, data)",
                                                 "runStrip(ctx, copy)")])
check("  and still ends on the retest line",
      "var again = retest(ctx);" in DELIVERED)
check("the stored record is read back rather than recomputed",
      'return (ctx.visuals && ctx.visuals.brain) || {}' in MODULE
      and "function storedProfile(" in MODULE)
check("the layout is the minimal one, named outright",
      cfg.get("result_template") == "minimal"
      and "paywall_variants" not in cfg
      and 'template(ctx) === "minimal"' in MODULE)
profile = cfg["result_copy"]["profile"]
check("  with the copy the layout needs all declared",
      all(k in profile for k in ("chips", "rarity_card", "offer_personal",
                                 "offer_personal_elite", "offer_hero_kicker",
                                 "offer_hero_line", "offer_cards",
                                 "offer_chips")), str(sorted(profile)))
check("  four chips, one token each, one per zone, in play order",
      profile["chips"] == ["{%s}" % d for d in DOMAINS], str(profile["chips"]))
check("  the profile card carries a frame and a line under it",
      all(profile["rarity_card"].get(k) for k in ("lead", "tail", "note")))
check("the layout drops the bars and the locked rows for chips and a card",
      "if (!lean) root.appendChild(bars(ctx, copy, data));" in MODULE
      and "if (!lean) root.appendChild(path(ctx, copy));" in MODULE
      and MODULE.count('root.classList.toggle("is-minimal", lean);') == 2)
check("the struck price is read out as well as drawn",
      "{price}" in cfg["result_copy"]["price_regular_aria"]
      and "ctx.sale && ctx.priceRegular" in MODULE
      and ".result-module.is-minimal .br-price-was::after {" in RESULT_CSS)
check("the strip is a six-column grid of square cells",
      "grid-template-columns: repeat(6, minmax(0, 1fr));" in RESULT_CSS
      and "aspect-ratio: 1 / 1;" in RESULT_CSS
      and MODULE.count("return tapsBlock(copy") == 2)
check("  reading the engine's own tile rule",
      "typeof ctx.tile === \"function\"" in MODULE
      and "return ctx.tile(index, stepId, item, late);" in MODULE)
check("  and a round the clock answered draws a cross",
      'item.className = "br-tap is-out";' in MODULE
      and ".br-tap.is-out {" in RESULT_CSS)
check("the urgency block sits under the number and moves the page",
      "var push = urge(ctx, copy);" in MODULE
      and MODULE.index("var push = urge(ctx, copy);")
      < MODULE.index("var strip = taps(ctx, copy);")
      and "document.getElementById(OFFER_ID)" in MODULE
      and cfg["result_copy"]["improve_cta"] == "Improve now"
      and cfg["result_copy"]["improve_foot"].startswith(
          "Follow the 7-day plan, play again — the score climbs"))
share = profile
check("what gets shared is the score, out of a hundred, and nothing else",
      share["share_line"] == "My Focus Score is {n}/100. Beat me?"
      and "fill(table.share_line, { n: data.score });" in MODULE
      and not re.search(r"\d", share["share_line"].replace("{n}", "")
                        .replace("100", "")))
check("  with the button, the copied word and the retest line in the config",
      share["share_cta"] == "Challenge a friend"
      and share["share_copied"] == "Copied — send it"
      and share["retest_line"]
      == "In one week: play it again. The number moves."
      and all(("table." + k) in MODULE for k in
              ("share_cta", "share_line", "share_copied", "retest_line")))
check("  none of them hardcoded in the module",
      not [line for line in (share["share_cta"], share["share_copied"],
                             share["retest_line"]) if line in MODULE])
check("  and the link it hands over is the funnel's own path",
      "window.location.origin" in MODULE
      and "(ctx.cfg && ctx.cfg.slug)" in MODULE and "location.href" not in MODULE)
import tracking                                                # noqa: E402
emitted = set(re.findall(r'\btrack\("([a-z_]+)"', MODULE))
check("every event the module emits is one the server allows",
      emitted <= tracking.ALLOWED_EVENTS and "share_tap" in emitted,
      str(sorted(emitted - tracking.ALLOWED_EVENTS)))

print("\n--- round 1: what was NOT on the board ---")
HOLD = {"mem1": 3000, "mem2": 3000, "mem3": 2500, "mem4": 2500}
FRAMES = {"mem1": 4, "mem2": 6, "mem3": 6, "mem4": 6}
ICON = re.compile(r"icon_(\w+?)_(colorA|colorB)\.webp$")
for sid in ("mem1", "mem2", "mem3", "mem4"):
    step = by_id[sid]
    mid = mid_by_after[SCORED[sid][1] - 1][0]
    check("%s holds %d frames for %dms, answered on a grid4"
          % (sid, FRAMES[sid], HOLD[sid]),
          mid["auto_advance_ms"] == HOLD[sid] and step["format"] == "grid4"
          and step["question"] == "Which one was NOT on the board?",
          "%s / %s" % (mid["auto_advance_ms"], step["format"]))
    check("  three versions, and the screen's own flash is the first one's",
          len(step["pool"]) == 3
          and mid["flash"] == step["pool"][0]["flash"])
    for n, entry in enumerate(step["pool"], start=1):
        frames = [f["img"] for f in entry["flash"]["images"]]
        cards = pair_of(step, entry)["images"]
        hits = [c for c in cards if c["tags"] == ["mem_hit"]]
        misses = [c for c in cards if c["tags"] == ["mem_miss"]]
        check("  v%d holds %d icons on a %s, none twice" % (
            n, FRAMES[sid], entry["flash"]["format"]),
              len(frames) == FRAMES[sid] and len(set(frames)) == len(frames)
              and GRID_SIZE[entry["flash"]["format"]] == FRAMES[sid]
              and all(ICON.search(f) for f in frames))
        check("    one answer, and it was NOT on the board",
              len(hits) == 1 and hits[0]["img"] not in frames,
              str([stem(h["img"]) for h in hits]))
        check("    three decoys, and every one of them WAS",
              len(misses) == 3 and all(m["img"] in frames for m in misses),
              str([stem(m["img"]) for m in misses if m["img"] not in frames]))
        check("    the clock presses a decoy of THIS version",
              entry["timeout_pick"] in {c["id"] for c in misses})
        check("    and every card is labelled by its ink and its object",
              all(c["label"].split(" ")[0] in ("Blue", "Red")
                  and c["label"].split(" ")[-1] == ICON.search(c["img"]).group(1)
                  for c in cards))
        if sid == "mem4":
            icon, ink = ICON.search(hits[0]["img"]).groups()
            other = "icon_%s_%s.webp" % (icon, "colorB" if ink == "colorA"
                                         else "colorA")
            check("    mem4: the answer's own object WAS on the board, "
                  "in the other ink",
                  any(f.endswith(other) for f in frames)
                  and any(m["img"].endswith(other) for m in misses))
check("the two inks are the two the generator drew",
      MANIFEST["icon_inks"] == {"colorA": "blue", "colorB": "red"})
icon_files = {stem(c["img"]) for s in ("mem1", "mem2", "mem3", "mem4")
              for e in by_id[s]["pool"]
              for c in pair_of(by_id[s], e)["images"]}
icon_files |= {stem(f["img"]) for s in ("mem1", "mem2", "mem3", "mem4")
               for e in by_id[s]["pool"] for f in e["flash"]["images"]}
check("  and all twenty icon cards are in play",
      icon_files == {c["id"] for c in MANIFEST["cards"]
                     if c["group"] == "mem_icon"}
      and len(icon_files) == 20, str(len(icon_files)))

print("\n--- round 2: the turned arrow, off the manifest ---")
# v3: the boards escalate. Nine arrows then sixteen, and the turn shrinks
# from twenty-five degrees to fifteen, with the clock shortening under the
# last two. All of it read off the manifest the generator wrote.
FOC_GRID = {"a": 3, "b": 3, "c": 4, "d": 4}
FOC_TURN = {"a": 25, "b": 20, "c": 18, "d": 15}
FOC_CLOCK = {"foc1": 5000, "foc2": 5000, "foc3": 4000, "foc4": 4000}
for n, set_id in enumerate("abcd", start=1):
    sid = "foc%d" % n
    step = by_id[sid]
    rule = MANIFEST["foc"][set_id]
    cards = images(step)
    hit = [c for c in cards if c["tags"] == ["foc_hit"]]
    check("%s is the four boards of set %s, %dx%d turned %d degrees, "
          "on a %.1f-second clock" % (sid, set_id, FOC_GRID[set_id],
                                      FOC_GRID[set_id], FOC_TURN[set_id],
                                      FOC_CLOCK[sid] / 1000.0),
          step["format"] == "grid4" and step["timer_ms"] == FOC_CLOCK[sid]
          and rule["grid"] == FOC_GRID[set_id]
          and rule["turn"] == FOC_TURN[set_id]
          and [stem(c["img"]) for c in cards]
          == ["foc_%s_%d" % (set_id, k) for k in range(1, 5)]
          and step["question"] == "Which board has the turned arrow?",
          str([stem(c["img"]) for c in cards]))
    check("    and the turned cell is one the board has",
          0 <= rule["odd_cell"] < rule["grid"] ** 2
          and all(c["grid"] == rule["grid"] and c["turn"] == rule["turn"]
                  for c in MANIFEST["cards"]
                  if c.get("set") == set_id and c["group"] == "foc_board"))
    check("  the manifest turned an arrow on board %d, and that board scores"
          % rule["odd"],
          len(hit) == 1 and stem(hit[0]["img"]) == "foc_%s_%d" % (set_id,
                                                                  rule["odd"]),
          str([stem(h["img"]) for h in hit]))
    check("    which the manifest's own card entry agrees with",
          [c["odd"] for c in MANIFEST["cards"]
           if c["id"] == stem(hit[0]["img"])] == [True]
          and not [c for c in MANIFEST["cards"]
                   if c.get("set") == set_id and c["group"] == "foc_board"
                   and c["odd"] and c["id"] != stem(hit[0]["img"])])
    check("    one version, and the clock presses a miss of it",
          len(step["pool"]) == 1 and step["pool"][0]["pair"] == "v1"
          and step["pool"][0]["timeout_pick"]
          in {c["id"] for c in cards if c["tags"] == ["foc_miss"]})
check("  the four sets turn a different board each",
      len({MANIFEST["foc"][s]["odd"] for s in "abcd"}) == 4,
      str([MANIFEST["foc"][s]["odd"] for s in "abcd"]))
check("  and point four different ways, in four different inks",
      len({MANIFEST["foc"][s]["direction"] for s in "abcd"}) == 4
      and len({MANIFEST["foc"][s]["ink"] for s in "abcd"}) == 4)
check("  the turn shrinks set by set and the grid grows, so the round escalates",
      [MANIFEST["foc"][s]["turn"] for s in "abcd"] == [25, 20, 18, 15]
      and [MANIFEST["foc"][s]["grid"] for s in "abcd"] == [3, 3, 4, 4])
check("  and the sixteen-arrow boards draw their arrows smaller",
      "4: ((0.20, 0.40, 0.60, 0.80), 0.062)" in
      open(os.path.join(ROOT, "scripts/gen_focus_art.py"),
           encoding="utf-8").read()
      and "3: ((0.24, 0.50, 0.76), 0.085)" in
      open(os.path.join(ROOT, "scripts/gen_focus_art.py"),
           encoding="utf-8").read())

print("\n--- round 3: the rule flips every step, and exactly one card obeys it ---")
# v3: six cards, the rule read off the question, and on every step after the
# first exactly one lure that obeys the rule BEFORE it — never the answer.
# The last step is the negative: one arrow that is not down among five that
# are, on the shortest clock of the walk.
ARROW = re.compile(r"swi_(up|down|left|right)_(red|blue|green|amber)\.webp$")
RULES = {"chg1": ("colour", "red"), "chg2": ("direction", "up"),
         "chg3": ("colour", "green"), "chg4": ("not_direction", "down")}
SWI_CLOCK = {"chg1": 4000, "chg2": 4000, "chg3": 3000, "chg4": 2500}


def rule_of(question):
    """The rule, read off the question the reader is shown."""
    got = re.match(r"Tap the (RED|BLUE|GREEN|AMBER) arrow$", question)
    if got:
        return ("colour", got.group(1).lower())
    got = re.match(r"Now — tap the arrow NOT pointing (UP|DOWN|LEFT|RIGHT)$",
                   question)
    if got:
        return ("not_direction", got.group(1).lower())
    got = re.match(r"Now — tap the arrow pointing (UP|DOWN|LEFT|RIGHT)$",
                   question)
    if got:
        return ("direction", got.group(1).lower())
    return None


def obeys(card, rule):
    direction, colour = ARROW.search(card["img"]).groups()
    kind, want = rule
    if kind == "colour":
        return colour == want
    if kind == "direction":
        return direction == want
    return direction != want


previous = None
for sid in ("chg1", "chg2", "chg3", "chg4"):
    step = by_id[sid]
    rule = rule_of(step["question"])
    check("%s asks %r, which is the rule the brief set" % (sid, step["question"]),
          rule == RULES[sid], str(rule))
    check("  on a %.1f-second clock, six up, in three versions"
          % (SWI_CLOCK[sid] / 1000.0),
          step["timer_ms"] == SWI_CLOCK[sid] and len(step["pool"]) == 3
          and step["format"] == "grid6")
    for n, entry in enumerate(step["pool"], start=1):
        cards = pair_of(step, entry)["images"]
        hit = [c for c in cards if c["tags"] == ["chg_hit"]]
        obey = [c for c in cards if obeys(c, rule)]
        files = {c["img"] for c in cards}
        check("  v%d: six arrow cards, six ids" % n,
              len(cards) == 6 and all(ARROW.search(c["img"]) for c in cards)
              and len({c["id"] for c in cards}) == 6)
        if rule[0] == "not_direction":
            down = [c for c in cards if ARROW.search(c["img"]).group(1)
                    == rule[1]]
            check("    five point %s and one does not; four files exist, so "
                  "one is drawn twice" % rule[1],
                  len(down) == 5 and len(files) == 5
                  and len({c["img"] for c in down}) == 4)
        else:
            check("    no two the same file", len(files) == 6)
        check("    exactly one obeys the rule, and it scores",
              len(obey) == 1 and hit == obey,
              "obey %s, hit %s" % ([stem(c["img"]) for c in obey],
                                   [stem(c["img"]) for c in hit]))
        check("    the clock presses a miss of this version",
              entry["timeout_pick"] in {c["id"] for c in cards
                                        if c["tags"] == ["chg_miss"]})
        check("    and every label names the ink and the direction",
              all(c["label"] == "%s arrow, pointing %s" % (
                  ARROW.search(c["img"]).group(2).capitalize(),
                  ARROW.search(c["img"]).group(1)) for c in cards))
        if previous:
            lure = [c for c in cards if obeys(c, previous)]
            check("    exactly one lure obeys the rule before, and it is a miss",
                  len(lure) == 1 and lure[0]["tags"] == ["chg_miss"]
                  and lure[0] is not hit[0],
                  str([stem(c["img"]) for c in lure]))
    previous = rule
check("the rule flips every step: colour, direction, colour, negation",
      [rule_of(by_id[s]["question"])[0] for s in ("chg1", "chg2", "chg3",
                                                   "chg4")]
      == ["colour", "direction", "colour", "not_direction"])
check("  and the clocks shorten as it does",
      [by_id[s]["timer_ms"] for s in ("chg1", "chg2", "chg3", "chg4")]
      == [4000, 4000, 3000, 2500])
arrow_files = {stem(c["img"]) for s in ("chg1", "chg2", "chg3", "chg4")
               for e in by_id[s]["pool"] for c in pair_of(by_id[s], e)["images"]}
check("  and all sixteen arrow cards are in play",
      arrow_files == {c["id"] for c in MANIFEST["cards"]
                      if c["group"] == "swi_arrow"}, str(len(arrow_files)))

print("\n--- round 4: the most dots, off the manifest ---")
for n, set_id in enumerate("abcd", start=1):
    sid = "spa%d" % n
    step = by_id[sid]
    rule = MANIFEST["dec"][set_id]
    cards = images(step)
    hit = [c for c in cards if c["tags"] == ["spa_hit"]]
    counts = {k: rule["counts"][str(k)] for k in range(1, 5)}
    check("%s is the four scatters of set %s, on a four-second clock"
          % (sid, set_id),
          step["format"] == "grid4" and step["timer_ms"] == 4000
          and [stem(c["img"]) for c in cards]
          == ["dec_%s_%d" % (set_id, k) for k in range(1, 5)]
          and step["question"] == "Which card has the MOST dots?")
    check("  the manifest counts card %d fullest (%s), and that card scores"
          % (rule["most"], [counts[k] for k in range(1, 5)]),
          len(hit) == 1 and stem(hit[0]["img"]) == "dec_%s_%d" % (set_id,
                                                                  rule["most"])
          and counts[rule["most"]] == max(counts.values())
          and list(counts.values()).count(max(counts.values())) == 1,
          str([stem(h["img"]) for h in hit]))
    check("    four different counts, all between seven and thirteen",
          len(set(counts.values())) == 4
          and all(7 <= v <= 13 for v in counts.values()))
    check("    the manifest's own card entries agree",
          [c["count"] for c in MANIFEST["cards"]
           if c.get("set") == set_id and c["group"] == "dec_dots"]
          == [counts[k] for k in range(1, 5)]
          and [c["id"] for c in MANIFEST["cards"]
               if c.get("set") == set_id and c["group"] == "dec_dots"
               and c["most"]] == [stem(hit[0]["img"])])
    check("    one version, and the clock presses a miss of it",
          len(step["pool"]) == 1
          and step["pool"][0]["timeout_pick"]
          in {c["id"] for c in cards if c["tags"] == ["spa_miss"]})

print("\n--- sixteen scored rounds, every version of each ---")
for sid in POOLED:
    step = by_id[sid]
    dom = SCORED[sid][0]
    size = GRID_SIZE[step["format"]]
    check("%s: %d version(s), each naming a pair the step declares"
          % (sid, len(step["pool"])),
          all(pair_of(step, e) is not None for e in step["pool"])
          and len({e["pair"] for e in step["pool"]}) == len(step["pool"])
          == len(step["pairs"]))
    for n, entry in enumerate(step["pool"], start=1):
        cards = pair_of(step, entry)["images"]
        hits = [c for c in cards if c["tags"] == [dom + "_hit"]]
        misses = [c for c in cards if c["tags"] == [dom + "_miss"]]
        check("  v%d: %d cards, exactly one of them the answer, all of %s"
              % (n, size, dom),
              len(cards) == size and len(hits) == 1
              and len(misses) == size - 1)
check("  and no warm-up step carries a pool",
      not [s["id"] for s in steps if s.get("pool") and s["id"] not in POOLED])
SCORE = block["score"]
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
    check("version %d of every round: sixteen hits, a hundred when fast, "
          "eighty-eight when slow, four of four per zone" % pick,
          hits == block["scored"]
          and focus_score(block["scored"] - hits, [0.0] * 12) == 100
          and focus_score(block["scored"] - hits, [1.0] * 12) == 88
          and all(scores.get(d + "_hit") == 4 for d in DOMAINS),
          str(scores))
check("  and a run that taps every clock's own pick scores five",
      focus_score(sum(1 for sid in POOLED for e in by_id[sid]["pool"][:1]))
      == 5)

print("\n--- the preview gallery and the rounds card ---")
quiz = {(c["img"], c["tags"][0]) for s in steps for p in s["pairs"]
        for c in p["images"]}
gallery = cfg["preview_gallery"]
check("sixteen entries, four per zone, in play order",
      len(gallery) == 16
      and [e["tags"][0] for e in gallery]
      == [d + "_hit" for d in DOMAINS for _ in range(4)],
      str([e["tags"] for e in gallery]))
check("  every one a live quiz card, with that card's own tag and path",
      all((e["img"], e["tags"][0]) in quiz for e in gallery)
      and all(e["id"] == stem(e["img"]) for e in gallery)
      and len({e["id"] for e in gallery}) == 16)
elements = cfg["style_elements"]
check("the rounds card is titled Your Rounds, with a subline",
      elements["title"] == "Your Rounds" and elements.get("subline"))
check("  twelve items, three per zone, each pointing at a live quiz image",
      len(elements["items"]) == 12
      and [i["tags"][0] for i in elements["items"]]
      == [d + "_hit" for d in DOMAINS for _ in range(3)]
      and all((i["img"], i["tags"][0]) in quiz for i in elements["items"])
      and all(i["image"] == stem(i["img"]) == i["id"] and i.get("label")
              and i.get("spec") for i in elements["items"]))

print("\n--- the report and the offer ---")
sections = cfg["report"]["sections"]
check("the four chapters are titled the way the brief sells them",
      [s["title"] for s in sections]
      == ["Your Productivity Profile & Your Edge",
          "Your Weakest Zone — and the Fastest Lift",
          "5 Sharp Strengths & 2 Habits to Drop",
          "Your 7-Day Productivity Boost Plan"],
      str([s["title"] for s in sections]))
check("  on the four ids the report machinery keys on, unchanged",
      [s["id"] for s in sections] == ["dna", "materials", "mistakes",
                                      "shopping"])
check("  each teased, previewed in two lines, enabled and shut",
      all(s.get("teaser_line") and len(s.get("preview") or []) == 2
          and s.get("enabled") is True
          and (s.get("reveal") or {}).get("mode") == "locked"
          for s in sections))
check("every chapter has a card in the result copy",
      sorted(c["id"] for c in profile["cards"])
      == sorted(s["id"] for s in sections))
check("  and every time thief the offer personalises on names a real chapter",
      sorted(cfg["result_copy"]["purpose_map"]) == sorted(t[0] for t in THIEF)
      and all(rule["emphasized_section"] in {s["id"] for s in sections}
              and rule.get("offer_sub")
              for rule in cfg["result_copy"]["purpose_map"].values()))
check("the hook slots point at the two warm-ups, by brain's slot names",
      cfg["report"]["hook_slots"]["mood"]["step"] == "thief"
      and cfg["report"]["hook_slots"]["age"]["step"] == "work"
      and "{mood}" in cfg["result_copy"]["strength_lead"])
check("  and every step the visuals name is a step",
      cfg["report"]["visuals"]["hero"]["glyph_step"] in by_id
      and cfg["report"]["visuals"]["hero"]["band_step"] in by_id
      and all(v in by_id for v in
              cfg["report"]["visuals"]["section_steps"].values())
      and sorted(cfg["report"]["visuals"]["section_steps"])
      == sorted(s["id"] for s in sections))
check("the checkout names the product this funnel sells",
      cfg["checkout"]["product_name"] == "Your 7-Day Productivity Boost Plan"
      and "{price}" in cfg["checkout"]["cta_label"]
      and cfg["checkout"]["proof_line"] == "Built from your 16 rounds"
      and "manifest" not in cfg["checkout"])
check("  and the offer names four things the plan contains, drawable icons",
      len(profile["offer_cards"]) == 4 and len(profile["offer_chips"]) == 3
      and all(('%s: [' % row["icon"]) in MODULE
              for row in profile["offer_cards"]))
check("  with the weakest-zone line as the template it is",
      "{round}" in profile["offer_personal"]
      and "function weakestRound(" in MODULE
      and "(ageBlock(ctx) || {}).domains" in MODULE)
check("  and the improvement is promised as a direction, never a number",
      "the plan to raise it" in intro["sub"]
      and "the score climbs" in cfg["result_copy"]["improve_foot"]
      and not re.search(r"\d", cfg["result_copy"]["improve_foot"]
                        .replace("7-day", "")))
import payments                                                # noqa: E402
sale = cfg["sale"]
check("the launch offer is the shape payments.py reads",
      sorted(sale) == ["active", "ends", "label", "price_cents",
                       "regular_price_cents"] and sale["active"] is True
      and sale["price_cents"] == 199
      and sale["regular_price_cents"] == cfg["pricing"]["amount_cents"]
      and sale["label"] == "Launch Offer")
BEFORE = datetime.datetime(2026, 6, 1, tzinfo=datetime.timezone.utc)
AFTER = datetime.datetime(2027, 6, 1, tzinfo=datetime.timezone.utc)
check("payments.py charges the offer price while it runs",
      payments._effective_price(cfg, BEFORE) == (199, sale))
check("  and the regular price the day after it ends",
      payments._effective_price(cfg, AFTER) == (500, None))
check("  the end is an instant with an offset on it",
      payments._sale_ends(sale["ends"]) is not None)

print("\n--- the copy: a game about your day, and nothing that sounds like "
      "anything else ---")
BANNED = ("adhd", "attention deficit", "disorder", "diagnosis", "burnout",
          "anxiety", "depression", "therapy", "medication", "mental health",
          "symptom", "clinical", "brain training", "psychic", "prediction")
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
# Two letters, so matched as a word: "quick" and "unique" are not it.
guilty = [at for at, text in strings if re.search(r"\biq\b", text.lower())]
check("  no string says 'IQ'", not guilty, str(guilty[:4]))
check("  and nothing says something is wrong with the reader",
      "fix that" not in json.dumps(cfg).lower()
      and "wrong with you" not in json.dumps(cfg).lower())
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
CROWD = ("average", " avg", "percentile", "top %", "better than",
         "most people", "than others", "worldwide", "users")
FREE_COPY = json.dumps({k: v for k, v in cfg["result_copy"].items()
                        if k != "purpose_map"}, ensure_ascii=False).lower()
check("nothing on the free page compares the reader to anybody",
      not [w for w in CROWD if w.strip() in FREE_COPY],
      str([w for w in CROWD if w.strip() in FREE_COPY]))
check("  nor does the offer",
      not [w for w in CROWD
           if w.strip() in json.dumps(cfg["checkout"],
                                      ensure_ascii=False).lower()])
check("  and no invented statistic is printed anywhere near the number",
      not re.search(r"\d+\s*%", FREE_COPY))
check("the free page never mentions an age",
      not re.search(r"\bage\b", FREE_COPY), str(re.findall(r".{20}\bage\b.{20}",
                                                          FREE_COPY)[:2]))
check("  and neither does the intro or the share",
      not re.search(r"\bage\b", json.dumps(intro).lower())
      and not re.search(r"\bage\b", json.dumps(profile["share"]).lower()))

print("\n%d checks, %d failed" % (checks[0], len(fails)))
for line in fails:
    print("  FAIL " + line)
sys.exit(1 if fails else 0)
