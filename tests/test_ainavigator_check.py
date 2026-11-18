#!/usr/bin/env python3
"""Integrity checks over funnels/ai-navigator.json — the AI Navigator.

/ai-navigator is the platform's third game, cut from /focus the way /focus
was cut from /brain: warm-up steps that score nothing, scored rounds with
exactly one right answer, a result module. What differs is that the answers
are sentences. There is no gallery, no clock, no memorise screen and no
speed: eighteen steps of text rows, six that ask about the reader and twelve
that have a right answer, three for each of four zones.

The machinery is brain's and is named here by brain's names — the tag stems
`mem`, `foc`, `chg` and `spa`, because engine.js scores on those and nothing
else, and the number block `brain_age`. The reader sees How AI works,
Prompting, Judgment & risk and Business sense.

Checked here:

  * The file, its static copy, and that it transacts on Stripe's test keys —
    there is no report profile for this funnel yet, so it must not be able to
    take a live charge.
  * Eighteen steps: six warm-ups carrying service tags only, twelve scored,
    each with exactly one hit and the rest misses on one stem, three a stem.
  * Every format the funnel names is one engine.js declares, and the text
    formats draw no image.
  * The four types each win a run that hits only their own zone, and an
    all-hit run resolves to the first by the tie-break.
  * The prediction against the score: all three calibration labels reachable,
    off the config's own bands. The three levels cover 0–12 with no gap.
  * The price, through payments' own function. No sale. No literal price in
    any string.
  * A banned-phrase scan over every string, with two allowlisted exceptions
    that the spec itself requires: one decoy answer card, and the disclaimer.
  * The result module: on disk, registers both halves, holds no payment path
    and never says which answer was right.

No database, no network, no key. Everything is read off disk.

    python3 tests/test_ainavigator_check.py
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


def check(label, ok, detail=""):
    checks[0] += 1
    if not ok:
        fails.append("%s %s" % (label, detail))
    print("  %-64s %s%s" % (label, "ok" if ok else "FAIL",
                            ("  " + str(detail)[:240]) if detail and not ok
                            else ""))


def read(rel):
    with open(os.path.join(ROOT, rel), encoding="utf-8") as fh:
        return fh.read()


SLUG = "ai-navigator"
RAW = read("funnels/%s.json" % SLUG)
cfg = json.loads(RAW)
FOCUS = json.loads(read("funnels/focus.json"))
ENGINE = read("static/js/engine.js")
MODULE = read("static/js/result_ai.js")
RESULT_CSS = read("static/css/result_ai.css")
MAZZIN_CSS = read("static/css/mazzin.css")

import config                                                # noqa: E402
import payments                                              # noqa: E402

steps = cfg["swipe"]["steps"]
by_id = {s["id"]: s for s in steps}

GRID_SIZE = {name: int(size) for name, size in re.findall(
    r"(\w+): (\d+)",
    re.search(r"var GRID_SIZE = \{([^}]*)\}", ENGINE).group(1))}
TEXT_FORMATS = set(re.findall(
    r"(\w+): true",
    re.search(r"var TEXT_FORMATS = \{([^}]*)\}", ENGINE).group(1)))

DOMAINS = ("mem", "foc", "chg", "spa")
NAMES = {"mem": "How AI works", "foc": "Prompting",
         "chg": "Judgment & risk", "spa": "Business sense"}
WARMUPS = ("exp", "tool", "skill", "time", "goal", "predict")
DISCLAIMER = ("Educational content. No income is promised or guaranteed — "
              "results depend on your effort, skills and market.")


def images(step):
    return step["pairs"][0]["images"]


def strings(node, at=""):
    """Every string in the config, with the path it sits at."""
    if isinstance(node, str):
        yield at, node
    elif isinstance(node, dict):
        for key, value in node.items():
            yield from strings(value, at + "." + key)
    elif isinstance(node, list):
        for i, value in enumerate(node):
            yield from strings(value, "%s[%d]" % (at, i))


ALL = list(strings(cfg))

print("--- the file, and its copy on the CDN ---")
check("funnels/ai-navigator.json is /ai-navigator",
      cfg["slug"] == SLUG and cfg["funnel_id"] == "ai_navigator_v1"
      and cfg["locale"] == "en")
check("  the slug is one the router accepts",
      config.SLUG_RE.match(SLUG) is not None and config.valid_slug(SLUG)
      and config.funnel_exists(SLUG))
check("  its static copy is byte-identical",
      RAW == read("static/funnels/%s.json" % SLUG))
check("  written the way the others are: two-space JSON, one newline",
      RAW == json.dumps(cfg, indent=2, ensure_ascii=False) + "\n")
check("the funnels directory and its static copy agree",
      sorted(os.listdir(os.path.join(ROOT, "funnels")))
      == sorted(os.listdir(os.path.join(ROOT, "static/funnels"))))
check("the theme it names is one the stylesheet knows",
      ("body.theme-%s {" % cfg["theme"]) in MAZZIN_CSS, cfg["theme"])
check("it draws its result with its own module",
      cfg["result_module"] == "/static/js/result_ai.js"
      and cfg["result_css"] == "/static/css/result_ai.css")
check("  both on disk",
      os.path.isfile(os.path.join(ROOT, cfg["result_module"].lstrip("/")))
      and os.path.isfile(os.path.join(ROOT, cfg["result_css"].lstrip("/"))))
check("  and the analysing fade lands on the result page's own ground",
      cfg["swipe"]["analyzing_fade_to"] == "#ECE6DA"
      and "background-color: #ECE6DA;" in RESULT_CSS
      and "--ai-ground: #ECE6DA;" in RESULT_CSS)

print("\n--- it cannot take a live charge ---")
# There is no report profile for this funnel until its second phase, so a
# purchase today would be delivered somebody else's document. The mechanism
# is the one /focus ships on: the config asks for Stripe's test key set, and
# payments.py refuses checkout rather than fall back to the live keys when
# those are missing. An override row is the only thing that outranks it, and
# that is a deliberate act by a signed-in owner.
check("the config asks for the test key set", cfg.get("stripe_mode") == "test")
check("  which is what payments reads off it",
      payments._stripe_mode(cfg) == payments.TEST
      and payments._stripe_mode(config.load_funnel(SLUG)) == payments.TEST)
_real = payments._read_override
payments._read_override = lambda slug: None
try:
    check("  and, with no override row, what it transacts on",
          payments.effective_mode(SLUG) == payments.TEST
          and payments.effective_mode(SLUG, cfg) == payments.TEST)
finally:
    payments._read_override = _real
check("  the same flag focus ships on, read the same way",
      FOCUS.get("stripe_mode") == "test"
      and 'return TEST if (cfg or {}).get("stripe_mode") == TEST else LIVE'
      in read("payments.py"))
import reports                                               # noqa: E402
check("there is no report profile for it yet, which is why",
      SLUG not in reports.PROFILES)

print("\n--- cut from focus: what is kept and what is dropped ---")
DROPPED = ["track_timing", "result_template", "preview_gallery",
           "style_elements", "analyzing_echo", "sale", "pairings",
           "share_cards"]
# One key is this funnel's own: `rsoc`, the partner-article block, which has
# a section to itself further down. It is last, after everything focus has.
OWN = ["rsoc"]
check("every top-level key is one focus carries, bar the one of its own",
      [k for k in cfg if k not in FOCUS] == OWN,
      str([k for k in cfg if k not in FOCUS]))
check("  in focus's order, its own key last",
      list(cfg) == [k for k in FOCUS if k in cfg] + OWN)
check("  and the ones with no meaning here are gone, not emptied",
      sorted(k for k in FOCUS if k not in cfg) == sorted(DROPPED),
      str(sorted(k for k in FOCUS if k not in cfg)))
check("no clock, no memorise screen, no time-up line",
      not any("timer_ms" in s or "pool" in s for s in steps)
      and not any(m.get("template") == "flash" or "flash" in m
                  for m in cfg["interstitials"])
      and "timeup_line" not in cfg["swipe"])
check("no echo row of pictures between zones",
      not any("echo_steps" in m for m in cfg["interstitials"]))
check("the number block keeps brain's key, without brain's formula",
      set(cfg["brain_age"]) == {"scored", "per_domain", "domains", "levels",
                                "predict"})
check("no share line, no play-again line, no last-run comparison",
      not any(k in json.dumps(cfg["result_copy"]) for k in
              ("share_cta", "share_line", "retest_line", "younger_line",
               "older_line", "level_line", "improve_cta")))
check("no gallery: not one image path on a card, and no folder for it",
      not any("img" in card for s in steps for p in s["pairs"]
              for card in p["images"])
      and "/static/galleries/" not in RAW
      and not os.path.exists(os.path.join(ROOT, "static/galleries", SLUG)))
check("  the only image named anywhere is the brand icon Stripe shows",
      [v for _, v in ALL if re.search(r"\.(webp|png|jpe?g|svg)$", v)]
      == ["/static/brand/icon-512.png"])

print("\n--- eighteen steps ---")
check("eighteen, and the walk says so",
      len(steps) == 18 and cfg["swipe"]["pairs_count"] == 18)
check("  ids unique, one pair each",
      len(by_id) == 18 and all(len(s["pairs"]) == 1 for s in steps))
check("  six warm-ups first, in order",
      [s["id"] for s in steps[:6]] == list(WARMUPS))
check("  then three questions a zone, in zone order",
      [s["id"] for s in steps[6:]]
      == ["%s%d" % (d, n) for d in DOMAINS for n in (1, 2, 3)])
for step in steps:
    fmt = step.get("format")
    check("  %s: %s is a format engine.js declares, drawn as text"
          % (step["id"], fmt),
          fmt in GRID_SIZE and fmt in TEXT_FORMATS
          and len(images(step)) == GRID_SIZE.get(fmt), fmt)
check("every card is an id, a label and tags — nothing else",
      all(set(card) == {"id", "label", "tags"} and card["label"].strip()
          for s in steps for card in images(s)))
ids = [card["id"] for s in steps for card in images(s)]
check("  card ids unique across the walk", len(ids) == len(set(ids)))
# The longest is the spec's own sixty-five characters, which is two lines of a
# 390px row; the cap is here so a third line cannot arrive unnoticed.
check("  and no answer is longer than two lines of a row",
      max(len(card["label"]) for s in steps for card in images(s)) <= 70,
      str(max(len(card["label"]) for s in steps for card in images(s))))

print("\n--- the six warm-ups: service tags, scoring nothing ---")
WARM = {
    "exp": ("How often do you use AI today?",
            ["Never really", "A few times", "Weekly", "Daily"]),
    "tool": ("Which do you use most?",
             ["Chat assistants", "Image tools", "Automation tools",
              "Coding tools", "Built into my apps", "None yet"]),
    "skill": ("What are you best at?",
              ["Writing", "Design & visuals", "Tech & code",
               "Sales & people", "Organizing", "Teaching"]),
    "time": ("Hours a week you could put in?",
             ["Under 3", "3–7", "8–15", "15+"]),
    "goal": ("What are you after?",
             ["A side project", "A full business",
              "Level up my current work", "Not sure yet"]),
    "predict": ("12 questions on how AI really works. How many will you get "
                "right?", ["0–3", "4–6", "7–9", "10–12"]),
}
STYLE_TAGS = {t for st in cfg["styles"] for t in st["tags"]}
for sid, (question, labels) in WARM.items():
    step = by_id[sid]
    check("%s asks its question and lists its answers in order" % sid,
          step["question"] == question
          and [c["label"] for c in images(step)] == labels,
          str([c["label"] for c in images(step)]))
    check("  dealt as listed", step.get("shuffle") is False)
    check("  one service tag a card, on its own stem",
          all(len(c["tags"]) == 1 and c["tags"][0].startswith(sid + "_")
              and c["tags"][0] == c["id"] for c in images(step)),
          str([c["tags"] for c in images(step)]))
    check("  scoring nothing: no hit, no miss, no type counts it",
          not any(re.search(r"_(hit|miss)$", t) or t in STYLE_TAGS
                  for c in images(step) for t in c["tags"]))
check("the prediction's four tags are the four bands",
      [c["tags"][0] for c in images(by_id["predict"])]
      == ["predict_0_3", "predict_4_6", "predict_7_9", "predict_10_12"])

print("\n--- the twelve questions: one right answer each ---")
ZONE_KICKER = {"mem": "ZONE 1 · HOW AI WORKS", "foc": "ZONE 2 · PROMPTING",
               "chg": "ZONE 3 · JUDGMENT & RISK",
               "spa": "ZONE 4 · BUSINESS SENSE"}
HITS = {
    "mem1": "Nothing — it can sound sure and be wrong",
    "mem2": "How much text the model can consider at once",
    "mem3": "It picks among likely next words, with some randomness",
    "foc1": "Specific context, audience and format",
    "foc2": "Say exactly what to change and iterate",
    "foc3": "Give 2–3 real examples to imitate",
    "chg1": "Open the source and check it first",
    "chg2": "A draft of your own blog post",
    "chg3": "The tool's terms for commercial use",
    "spa1": "It fixes one specific, recurring problem for one kind of "
            "customer",
    "spa2": "Get a few people to pay or commit first",
    "spa3": "Your judgment, process and accountability",
}
per_stem = dict.fromkeys(DOMAINS, 0)
for step in steps[6:]:
    stem = step["id"][:3]
    tags = [t for c in images(step) for t in c["tags"]]
    check("%s: four answers, one tag each, all on %s" % (step["id"], stem),
          step["format"] == "text4" and len(images(step)) == 4
          and all(len(c["tags"]) == 1 for c in images(step))
          and {t.rsplit("_", 1)[0] for t in tags} == {stem}, str(tags))
    check("  exactly one hit and three misses",
          tags.count(stem + "_hit") == 1 and tags.count(stem + "_miss") == 3,
          str(tags))
    hit = [c for c in images(step) if c["tags"] == [stem + "_hit"]]
    check("  the hit is the first listed, and it is the right sentence",
          hit and hit[0] is images(step)[0]
          and hit[0]["label"] == HITS[step["id"]],
          hit[0]["label"] if hit else "")
    check("  the answers are shuffled when dealt",
          "shuffle" not in step and "pin_first" not in step)
    check("  the reader sees the zone's name, never the stem",
          step["kicker"] == "%s · %s/3" % (ZONE_KICKER[stem], step["id"][3])
          and not re.search(r"\b(mem|foc|chg|spa)\b",
                            step["kicker"] + step["question"]),
          step["kicker"])
    per_stem[stem] += 1
check("three questions a zone, twelve in all",
      per_stem == dict.fromkeys(DOMAINS, 3)
      and cfg["brain_age"]["scored"] == 12
      and cfg["brain_age"]["per_domain"] == 3, str(per_stem))
check("the zones are named once, in the number block",
      cfg["brain_age"]["domains"] == NAMES)
check("the engine scores on those four stems and no others here",
      all(("var %s_AXIS = [\"%s_hit\", \"%s_miss\"];"
           % (d.upper(), d, d)) in ENGINE for d in DOMAINS))

print("\n--- the beats between ---")
mids = cfg["interstitials"]
check("one after the warm-ups, one after each zone, one before the result",
      [m["after_step"] for m in mids] == [6, 9, 12, 15, 18])
check("  on the templates the engine already has",
      [m["template"] for m in mids]
      == ["confirm", "confirm", "confirm", "confirm", "almost"])
check("  the first says the test starts, and that there is no clock",
      mids[0]["line"] == "Now the test."
      and mids[0]["sub"] == "12 questions, no clock.")
for m, stem in zip(mids[:4], DOMAINS):
    check("  the one after step %d names the zone that follows"
          % m["after_step"], NAMES[stem] in m["kicker"], m["kicker"])
for m, stem in zip(mids[1:4], DOMAINS):
    lines = m["personal"]["lines"]
    check("  the one after step %d echoes %s, hit and miss"
          % (m["after_step"], stem),
          m["personal"]["axis"] == stem
          and set(lines) == {stem + "_hit", stem + "_miss"}
          and all(v.get("line") and v.get("sub") for v in lines.values()))
    check("    and a miss is room, never a verdict",
          "room" in lines[stem + "_miss"]["sub"]
          and not re.search(r"weak|worst|fail|wrong|bad at",
                            json.dumps(lines).lower()))
check("  all short enough to read before they move on",
      all(len(m["line"]) <= 40 and len(m.get("sub", "")) <= 110
          for m in mids)
      and all(len(v["line"]) <= 40 and len(v["sub"]) <= 110
              for m in mids for v in (m.get("personal") or
                                      {"lines": {}})["lines"].values()))

print("\n--- the four types, won the way engine.js wins them ---")


def winner(scores):
    best, best_score = cfg["styles"][0]["id"], float("-inf")
    for style in cfg["styles"]:
        total = sum(scores.get(t, 0) for t in style["tags"])
        if total > best_score:
            best, best_score = style["id"], total
    return best


check("engine.js still picks the winner that way: strictly more, first wins",
      "if (sc > bestScore) { bestScore = sc; best = s; }" in ENGINE
      and "var best = cfg.styles[0];" in ENGINE)
STYLES = [("mechanic", "The Mechanic", "mem_hit"),
          ("director", "The Director", "foc_hit"),
          ("editor", "The Editor", "chg_hit"),
          ("dealmaker", "The Dealmaker", "spa_hit")]
check("four types, on the four hit tags, in zone order",
      [(s["id"], s["name"], s["tags"]) for s in cfg["styles"]]
      == [(i, n, [t]) for i, n, t in STYLES])
for sid, _name, tag in STYLES:
    check("  a run that hits only its own zone wins %s" % sid,
          winner({tag: 3}) == sid, winner({tag: 3}))
check("  an all-hit run resolves to the first: A > B > C > D",
      winner({t: 3 for _, _, t in STYLES}) == "mechanic")
check("  and every two-way tie goes to the earlier zone",
      winner({"foc_hit": 2, "chg_hit": 2}) == "director"
      and winner({"chg_hit": 1, "spa_hit": 1}) == "editor"
      and winner({"mem_hit": 2, "spa_hit": 2}) == "mechanic")
check("  a run that hits nothing still resolves to a type",
      winner({}) == "mechanic")
check("each is named, blurbed, and carries strength #1 in full",
      all(s.get("blurb") and s.get("accent")
          and set(s["reveals"]) == {"dna", "materials", "mistakes",
                                    "shopping", "mistake_one"}
          and all(s["reveals"]["mistake_one"].get(k)
                  for k in ("title", "body", "fix"))
          for s in cfg["styles"]))
check("  and an essence line the result page prints under the name",
      set(cfg["result_copy"]["profile"]["essence"])
      == {s["id"] for s in cfg["styles"]}
      and all(cfg["result_copy"]["profile"]["essence"].values()))
for style in cfg["styles"]:
    text = json.dumps(style, ensure_ascii=False).lower()
    check("  %s: the low zone is room, never a weakness" % style["id"],
          "most room" in text
          and not re.search(r"weak|worst|deficien|poor|lacking", text))

print("\n--- the prediction, set against the score ---")
block = cfg["brain_age"]
bands = block["predict"]["bands"]
check("the bands are read off the step that asks",
      block["predict"]["step"] == "predict"
      and list(bands) == [c["tags"][0] for c in images(by_id["predict"])])
check("  each says what its card says",
      [b["label"] for b in bands.values()]
      == [c["label"] for c in images(by_id["predict"])])
check("  and together they cover 0 to 12 with no gap and no overlap",
      [(b["min"], b["max"]) for b in bands.values()]
      == [(0, 3), (4, 6), (7, 9), (10, 12)])


def calibration(band, hits):
    """result_ai.js's `calibrationOf`, restated."""
    if hits > band["max"]:
        return "under"
    if hits < band["min"]:
        return "over"
    return "on"


check("the module compares them exactly that way",
      'if (hits > band.max) return "under";' in MODULE
      and 'if (hits < band.min) return "over";' in MODULE
      and 'return "on";' in MODULE)
seen = {}
for tag, band in bands.items():
    for hits in range(13):
        seen.setdefault(calibration(band, hits), []).append((tag, hits))
LABELS = cfg["result_copy"]["calibration"]
check("all three labels are reachable", set(seen) == {"on", "under", "over"})
check("  inside the band is on target",
      LABELS["on"] == "On target"
      and calibration(bands["predict_7_9"], 8) == "on")
check("  above it is underrated",
      LABELS["under"] == "Underrated — better than you think"
      and calibration(bands["predict_4_6"], 9) == "under")
check("  below it is bold",
      LABELS["over"] == "Bold — confidence ahead of skill, the easiest gap "
                        "to close"
      and calibration(bands["predict_7_9"], 5) == "over")
check("  the lowest band cannot be bold and the highest cannot be underrated",
      not any(t == "predict_0_3" for t, _ in seen["over"])
      and not any(t == "predict_10_12" for t, _ in seen["under"]))
check("the line is the reader's two numbers and nobody else's",
      cfg["result_copy"]["calibration_line"]
      == "You predicted {band}. You scored {n}."
      and cfg["result_copy"]["score_of"] == "{n} / {total}")
check("a skipped prediction shows the score alone",
      "if (data.band) {" in MODULE
      and "return null;" in MODULE.split("function predictionOf", 1)[1]
      .split("function calibrationOf", 1)[0])


def level(hits):
    for row in block["levels"]:
        if "max" not in row or hits <= row["max"]:
            return row["label"]


check("three levels: Explorer 0–4, Builder 5–8, Operator 9–12",
      [level(n) for n in range(13)]
      == ["Explorer"] * 5 + ["Builder"] * 4 + ["Operator"] * 4)
check("  read off the config's table by the module, top to bottom",
      "typeof rows[i].max !== \"number\" || hits <= rows[i].max" in MODULE)

print("\n--- the report, as it is promised ---")
SECTIONS = [("dna", "Your AI Profile & Your Edge"),
            ("materials", "Your 3 Best-Fit Paths"),
            ("mistakes", "5 Strengths to Sell & 2 Traps to Avoid"),
            ("shopping", "Your First 7 Days")]
check("four sections, on the shared ids, under this funnel's titles",
      [(s["id"], s["title"]) for s in cfg["report"]["sections"]] == SECTIONS)
check("  ids focus's report uses too",
      [s["id"] for s in cfg["report"]["sections"]]
      == [s["id"] for s in FOCUS["report"]["sections"]])
check("  all locked, each with a teaser and two preview lines",
      all(s["enabled"] is True and s["reveal"] == {"mode": "locked"}
          and s["teaser_line"] and len(s["preview"]) == 2
          for s in cfg["report"]["sections"]))
key_rows = [r for r in cfg["report"]["also"]["rows"] if "title" in r]
check("plus the manifest line: Your Answer Key",
      key_rows == [{"title": "Your Answer Key",
                    "hook": "Every question, your answer, the right one, "
                            "and why."}])
check("  which the result page lists under the four, locked",
      cfg["result_copy"]["profile"]["answer_key"]["title"]
      == "Your Answer Key")
slots = cfg["report"]["hook_slots"]
check("the teaser words come off the reader's own warm-ups",
      {k: v["step"] for k, v in slots.items()}
      == {"skill": "skill", "hours": "time", "goal": "goal"}
      and all(v["step"] in by_id for v in slots.values()))
used = set(re.findall(r"\{(\w+)\}", json.dumps(cfg["report"]["sections"])))
check("  and every token a teaser uses is one of them",
      used <= set(slots) | {"style"}, str(used))
check("strength #1 is free, and says what stays locked",
      cfg["report"]["mistake_one"]["title"] == "Strength #1 of 5"
      and cfg["report"]["mistake_one"]["locked_note"])
check("the locked teaser is the line the page was asked to carry",
      cfg["result_copy"]["path_teaser"]
      == "Your best-fit path: ▒▒▒▒ — matched from your skill, your hours "
         "and your score")

print("\n--- the price ---")
check("six dollars", cfg["pricing"]["amount_cents"] == 600
      and cfg["pricing"]["currency"] == "usd")
check("  an integer number of cents, never a float or a string",
      type(cfg["pricing"]["amount_cents"]) is int)
check("  with no sale block at all", "sale" not in cfg)
check("  and that is what payments would charge, by its own function",
      payments._effective_price(cfg) == (600, None)
      and payments._effective_price(config.load_funnel(SLUG)) == (600, None),
      str(payments._effective_price(cfg)))
co = cfg["checkout"]
check("the product is Your AI Navigator Report",
      co["product_name"] == "Your AI Navigator Report")
check("the button says what it unlocks, and the price is a token",
      co["cta_label"] == "Unlock my AI Navigator — {price}"
      and co["commerce"]["sticky_label"] == co["cta_label"])
literal = [(at, v) for at, v in ALL
           if re.search(r"[$€£]\s?\d|\d\s?(usd|dollars?|bucks)\b|\b6\.00\b",
                        v, re.I)]
check("no literal price in any string", not literal, str(literal[:3]))
priced = [at for at, v in ALL if "{price}" in v]
check("  the strings that name one interpolate it",
      {"checkout.cta_label", "checkout.anchor", "checkout.anchor_head",
       "checkout.commerce.anchor_head", "checkout.commerce.sticky_label"}
      <= {at.lstrip(".") for at in priced}, str(priced))
money_anchor = [(at, v) for at, v in ALL if at.startswith(".checkout")
                and re.search(r"coffee|costs more|cheaper|less than|worth "
                              r"\S+ times|pays for itself|a book|a course",
                              v, re.I)]
check("the offer is anchored on what it is, never on money",
      not money_anchor
      and "12 answers and your own skill, hours and goal"
      in co["commerce"]["price_anchor"], str(money_anchor[:2]))
check("the EU withdrawal consent is exactly as focus has it",
      all(co[k] == FOCUS["checkout"][k] for k in
          ("withdrawal_consent", "consent_prechecked",
           "eu_withdrawal_text")))
check("  and so are the checkout switches",
      all(co[k] == FOCUS["checkout"][k] for k in
          ("single_page", "express", "product_image")))
check("every checkout key is one focus's checkout has, plus the disclaimer",
      set(co) - set(FOCUS["checkout"]) == {"disclaimer"}
      and set(FOCUS["checkout"]) - set(co) == set()
      and set(co["commerce"]) == set(FOCUS["checkout"]["commerce"]))

print("\n--- the disclaimer ---")
check("near the button", co["disclaimer"] == DISCLAIMER)
check("and in the footer of the result",
      cfg["result_copy"]["disclaimer"] == DISCLAIMER)
check("  the module prints one under the pay button",
      MODULE.index("nodes.payButton, nodes.payError]")
      < MODULE.index('elm("p", "ai-disclaimer", plain)')
      < MODULE.index("var chips = profileCopy(ctx).offer_chips"))
check("  and one as the last thing on both pages",
      MODULE.count("var foot = footer(copy);") == 2
      and MODULE.count("if (foot) root.appendChild(foot);") == 2)

print("\n--- nothing in it promises money ---")
BANNED = [
    r"guarante", r"passive income", r"get rich", r"financial freedom",
    r"quit your job", r"easy money", r"overnight", r"effortless", r"secret",
    r"loophole", r"six[- ]figure", r"\$\s?\d[\d,.]*\s*(a|per|/)\s*(day|week|"
    r"month)", r"earn \$", r"make \$", r"make money",
]
# Two strings the spec itself requires that trip the scan. The decoy answer
# on the last question is a wrong answer about secrecy; the disclaimer says
# that nothing is guaranteed. Allowlisted by exact path and exact text, so a
# third string cannot hide behind either.
ALLOW = {
    (".swipe.steps[17].pairs[0].images[1].label", "Secret prompts"),
    (".checkout.disclaimer", DISCLAIMER),
    (".result_copy.disclaimer", DISCLAIMER),
}
check("the two exceptions are where the allowlist says they are",
      all(pair in set(ALL) for pair in ALLOW))
check("  the decoy is a miss, on the question about what a client pays for",
      by_id["spa3"]["pairs"][0]["images"][1]["tags"] == ["spa_miss"])
hits = [(at, v) for at, v in ALL if (at, v) not in ALLOW
        and any(re.search(p, v, re.I) for p in BANNED)]
check("no banned phrase in any other string (%d scanned)" % len(ALL),
      not hits, str(hits[:3]))
for pattern in BANNED:
    probe = {"guarante": "Guaranteed results", "secret": "The secret",
             r"six[- ]figure": "a six-figure year"}.get(pattern)
    if probe:
        check("  the scan would catch %r" % probe,
              re.search(pattern, probe, re.I) is not None)
check("  and it would catch a figure a day, a week or a month",
      all(re.search(BANNED[11], s, re.I)
          for s in ("$500 a day", "$1,000/week", "$ 3000 per month")))
OTHERS = [r"most people", r"\d+\s?% of", r"\b\d[\d,]* (people|users|readers|"
          r"customers|students)\b", r"testimonial", r"\bhurry\b",
          r"limited time", r"last chance", r"only \d+ left", r"ends (today|"
          r"tonight|soon)", r"before it'?s gone", r"act now", r"\btoday only"]
hits = [(at, v) for at, v in ALL
        if any(re.search(p, v, re.I) for p in OTHERS)]
check("no statistic about other people, no testimonial, no urgency",
      not hits, str(hits[:3]))
income = [(at, v) for at, v in ALL if (at, v) not in ALLOW
          and re.search(r"\b(income|salary|revenue|profit|earn(ing)?s?|"
                        r"rich|wealth)\b", v, re.I)]
check("no string talks about income at all, bar the disclaimer",
      not income, str(income[:3]))

print("\n--- the text formats, in the engine ---")
check("text4 and text6 are sizes in the engine's own table",
      GRID_SIZE.get("text4") == 4 and GRID_SIZE.get("text6") == 6
      and TEXT_FORMATS == {"text4", "text6"})
check("  beside the picture formats, which are what they were",
      {k: GRID_SIZE[k] for k in ("grid3", "grid4", "grid6", "grid12")}
      == {"grid3": 3, "grid4": 4, "grid6": 6, "grid12": 12})
check("  and sizes tracking.py accepts on a swipe",
      {4, 6} <= set(__import__("tracking").SHOWN_SIZES))
node = ENGINE.split("function cardNode(item, index) {", 1)[1].split(
    "function enterStagger", 1)[0]
text_branch = node.split("if (isTextStep(stepAt(step))) {", 1)[1].split(
    "var img = document.createElement", 1)[0]
check("a text card is a button holding its label",
      'card.className = "card is-text";' in text_branch
      and 'words_.className = "card-text";' in text_branch
      and "words_.textContent = item.label" in text_branch)
check("  with no image node and no image request",
      "img" not in text_branch.replace("is-text", ""))
check("  the same tap as every other card",
      'card.addEventListener("click", function () { choose(item, card); });'
      in text_branch and "return card;" in text_branch)
check("  and the picture path below it is untouched",
      'img.className = "card-img";' in node and "img.src = item.img;" in node
      and node.count("choose(item, card)") == 2)
check("nothing waits on an image a text card does not have",
      ENGINE.count("items = items.filter(function (item) "
                   "{ return item && item.img; });") == 2)
check("the swipe event is the one every step sends",
      "shown: picked.images.map(function (g) { return g.id; })," in ENGINE
      and "chosen: item.id" in ENGINE)
check("the sheet stacks the rows: 56px at least, 16px type, wrapping",
      ".cards.is-text4,\n.cards.is-text6 {" in MAZZIN_CSS
      and "min-height: 56px;" in MAZZIN_CSS.split(".card.is-text {", 1)[1]
      .split("}", 1)[0]
      and "font-size: 16px;" in MAZZIN_CSS.split(
          ".card.is-text .card-text {", 1)[1].split("}", 1)[0]
      and "overflow-wrap: break-word;" in MAZZIN_CSS.split(
          ".card.is-text .card-text {", 1)[1].split("}", 1)[0])
sheet_tail = MAZZIN_CSS.split("/* --- text answers: `text4` and `text6`", 1)
selectors = re.findall(r"^([^\s/@}][^{]*)\{", sheet_tail[1], re.M)
check("  and every rule added for them is scoped to them",
      len(sheet_tail) == 2 and selectors
      and all(re.search(r"is-text", sel) for sel in selectors),
      str([s for s in selectors if "is-text" not in s]))
other = [name for name in sorted(os.listdir(os.path.join(ROOT, "funnels")))
         if name != SLUG + ".json"
         and re.search(r'"format": "text\d"', read("funnels/" + name))]
check("no other funnel names a text format", not other, str(other))

print("\n--- the result module ---")
check("it registers the two halves engine.js loads",
      "window.MazzinResult = { render: render, delivered: delivered };"
      in MODULE)
CODE = re.sub(r"//[^\n]*", "", re.sub(r"/\*.*?\*/", "", MODULE, flags=re.S))
check("it makes no payment path of its own",
      not re.search(r"fetch\(|XMLHttpRequest|/api/|stripe|checkout\(|"
                    r"location\.href|ctx\.checkout", CODE, re.I)
      and 'createElement("button")' not in CODE
      and 'elm("button"' not in CODE)
check("  the button and the consent are engine.js's own nodes, moved",
      "nodes.payButton, nodes.payError]" in CODE
      and "nodes.consent.hidden = true;" in CODE
      and "ctx.watchOffer(card)" in CODE)
check("  and it never writes the button's label",
      "cta_label =" not in CODE)
check("it holds no number of its own about the game",
      not re.search(r"\b(12|600)\b", CODE)
      and "block.scored" in CODE and "block.per_domain" in CODE
      and "block.levels" in CODE)
check("the free page is in the order it was specified",
      [m for m in re.findall(
          r"root\.appendChild\((\w+)\(", MODULE.split(
              "function render(root, ctx) {", 1)[1].split(
              "// --- the delivered report", 1)[0])]
      == ["kicker", "hero", "typeCard", "bars", "path", "offer"]
      and re.search(r"hero\(ctx, copy, data\)\);\s+var chip = levelChip",
                    MODULE)
      and MODULE.index("root.appendChild(typeCard(ctx));")
      < MODULE.index("var marks = strip(ctx, copy);")
      < MODULE.index("var one = strength(ctx, copy);")
      < MODULE.index("root.appendChild(path(ctx, copy));")
      < MODULE.index("root.appendChild(offer(ctx, copy, data));"))
strip_fn = MODULE.split("function strip(ctx, copy) {", 1)[1].split(
    "// --- 6)", 1)[0]
check("the strip marks right or missed and names no answer",
      "is-hit" in strip_fn and "is-miss" in strip_fn
      and ".label" not in strip_fn and "pick.id" not in strip_fn
      and "data-" not in strip_fn)
check("  twelve marks come off the config's own scored steps",
      "rounds(ctx.cfg)" in strip_fn)
check("the lowest zone is the one with the most room, and only that",
      cfg["result_copy"]["zone_room"] == "the zone with the most room"
      and not re.search(r"weak|worst|deficien|fail|poor",
                        json.dumps(cfg["result_copy"]).lower()))
check("every sentence it prints is the config's",
      not re.findall(r'elm\("\w+", "[\w -]+", "[A-Z][a-z]+ [a-z]', CODE))
check("the delivered page draws stub prose when a section has no data",
      'if (section.body) body.appendChild(elm("p", "ai-body", section.body))'
      in MODULE and "function delivered(root, ctx) {" in MODULE)
check("  and carries no offer",
      "offer(" not in MODULE.split("function delivered(root, ctx) {", 1)[1])
check("the stylesheet is scoped to this module",
      all(re.search(r"\.ai-|\.result-module\.is-ai|result-module\.is-ai",
                    sel)
          for sel in re.findall(r"^([^\s/@}][^{]*)\{", RESULT_CSS, re.M)),
      str([sel for sel in re.findall(r"^([^\s/@}][^{]*)\{", RESULT_CSS, re.M)
           if not re.search(r"\.ai-|result-module\.is-ai", sel)][:3]))
check("  with no image and no web font",
      "url(" not in RESULT_CSS and "@font-face" not in RESULT_CSS
      and "@import" not in RESULT_CSS)

print("\n--- the partner articles: the block ---")
RSOC = cfg.get("rsoc") or {}
ARTICLES = RSOC.get("articles") or {}
SKILL_TAGS = [t for card in next(s for s in steps if s["id"] == "skill")
              ["pairs"][0]["images"] for t in card["tags"]]
check("the block has exactly the keys it was specified with",
      list(RSOC) == ["enabled", "placement", "require_fbclid", "passthrough",
                     "head", "head_delivered", "note", "articles"],
      str(list(RSOC)))
check("  on, in both places, and only for a reader who came from a click",
      RSOC.get("enabled") is True
      and RSOC.get("placement") == ["below_paywall", "delivered"]
      and RSOC.get("require_fbclid") is True)
check("  passing on the three identifiers, in this order",
      RSOC.get("passthrough") == ["fbclid", "ad_id", "asid"])
check("  with the three lines around the buttons",
      RSOC.get("head") == "Not ready yet? Start with a free guide"
      and RSOC.get("head_delivered")
      == "Keep going: free guides for your profile"
      and RSOC.get("note")
      == "Opens evoseekly.com, a partner site that shows ads.")
check("ten articles", len(ARTICLES) == 10, str(len(ARTICLES)))
check("  keyed by the six skill tags the quiz uses, then its four zones",
      len(SKILL_TAGS) == 6
      and list(ARTICLES) == SKILL_TAGS + list(DOMAINS),
      str(list(ARTICLES)))
check("  each a label and a link and nothing else",
      all(isinstance(a, dict) and list(a) == ["label", "link"]
          and isinstance(a["label"], str) and a["label"]
          and isinstance(a["link"], str) for a in ARTICLES.values()))
LINKS = [a["link"] for a in ARTICLES.values()]
check("  every link https, with no query and no fragment",
      all(re.fullmatch(r"https://[a-z0-9.-]+/[A-Za-z0-9_-]+", link)
          for link in LINKS),
      str([link[:40] for link in LINKS
           if not re.fullmatch(r"https://[a-z0-9.-]+/[A-Za-z0-9_-]+", link)]))
check("  no link twice, no label twice",
      len(set(LINKS)) == 10
      and len({a["label"] for a in ARTICLES.values()}) == 10)
# The scan above walks every string in the file, so these are already inside
# it. This says so out loud, for the strings a reader actually sees.
SHOWN = ([RSOC.get("head", ""), RSOC.get("head_delivered", ""),
          RSOC.get("note", "")] + [a["label"] for a in ARTICLES.values()])
check("  and the lines a reader sees pass the banned scan",
      all(text in {v for _, v in ALL} for text in SHOWN)
      and not [text for text in SHOWN
               if any(re.search(p, text, re.I) for p in BANNED)])
check("no other funnel carries the block",
      not [n for n in os.listdir(os.path.join(ROOT, "funnels"))
           if n != SLUG + ".json"
           and "rsoc" in json.loads(read("funnels/" + n))])

print("\n--- the partner articles: the identifiers ---")
PASS = ENGINE.split("var PASS_RULES = {", 1)[1].split("};", 1)[0]
check("engine.js keeps three keys, each under its own rule",
      re.findall(r"(\w+): (/[^\n]+/),?\n", PASS)
      == [("fbclid", "/^[A-Za-z0-9_-]{1,512}$/"),
          ("ad_id", "/^[0-9]{1,32}$/"), ("asid", "/^[0-9]{1,32}$/")], PASS)
for value, key, ok in (("AbC_123-x", "fbclid", True),
                       ("{{ad.id}}", "ad_id", False), ("111", "ad_id", True),
                       ("12a", "asid", False), ("", "fbclid", False),
                       ("a b", "fbclid", False), ("x" * 513, "fbclid", False),
                       ("1" * 33, "asid", False)):
    rule = dict(re.findall(r"(\w+): /([^\n]+)/,?\n", PASS))[key]
    check("  %s=%r is %s" % (key, value[:12], "kept" if ok else "dropped"),
          bool(re.fullmatch(rule.strip("^$"), value)) is ok)
KEEP = ENGINE.split("function keepPassthrough(params) {", 1)[1].split(
    "\n  }\n", 1)[0]
HELD = ENGINE.split("function heldPassthrough() {", 1)[1].split(
    "\n  }\n", 1)[0]
check("only a funnel with the block reaches the store",
      KEEP.lstrip().startswith("if (!cfg || !cfg.rsoc) return;")
      and HELD.lstrip().startswith("if (!cfg || !cfg.rsoc) return {};"))
check("  which is sessionStorage, under the funnel's own name",
      'sessionStorage.setItem("mazzin_pass_" + slug' in KEEP
      and "localStorage" not in KEEP and "document.cookie" not in KEEP)
check("  and the contexts carry the key only on such a funnel",
      "if (cfg.rsoc) ctx.passthrough = heldPassthrough();" in ENGINE
      and ENGINE.count("heldPassthrough()") == 4)
check("the tracker does not send them",
      "passthrough" not in ENGINE.split("function track(event,", 1)[1]
      .split("\n  }\n", 1)[0]
      and "console." not in KEEP and "console." not in HELD)
RS = MODULE.split("// --- partner articles", 1)[1].split("// --- render", 1)[0]
check("the module builds real anchors, a new tab, noopener",
      'elm("a", "ai-rsoc-link", item.label)' in RS
      and 'link.target = "_blank";' in RS and 'link.rel = "noopener";' in RS)
check("  the query with URLSearchParams, from the held keys only",
      "new URLSearchParams()" in RS and "ctx.passthrough" in RS
      and "location" not in RS and "session" not in RS.replace(
          "sessionStorage", ""))
check("  refusing a link that is not https or already has a query",
      'link.indexOf("https://") !== 0' in RS
      and 'link.indexOf("?") !== -1 || link.indexOf("#") !== -1' in RS)
check("  with no markup written from a string",
      "innerHTML" not in RS)

print("\n--- the partner articles: the tap, server side ---")
import database                                           # noqa: E402
import tracking                                           # noqa: E402
from app import app                                       # noqa: E402

rows = []
database.execute = lambda sql, params=None: rows.append(params) or 1
tracking._mirror = lambda *a, **k: None
client = app.test_client()
SID = "3f1c2a54-9d6e-4b7a-8c21-0e5d4f6a7b8c"


def tap(funnel, extra):
    del rows[:]
    answer = client.post("/api/track", json={
        "funnel": funnel, "session_id": SID, "event": "article_tap",
        "extra": extra})
    return answer.status_code, (rows[0][-1] if rows else None)


check("the event is on the list, and its keys are a closed pair",
      "article_tap" in tracking.ALLOWED_EVENTS
      and tracking.ARTICLE_TAP_KEYS == frozenset(("article", "slot"))
      and tracking.ARTICLE_TAP_SLOT
      == frozenset(("below_paywall", "delivered")))
for key in ARTICLES:
    for slot in ("below_paywall", "delivered"):
        code, stored = tap(SLUG, {"slot": slot, "article": key})
        check("  %s in %s is accepted, and stored rebuilt" % (key, slot),
              code == 204
              and stored == '{"article":"%s","slot":"%s"}' % (key, slot),
              str((code, stored)))
REFUSED = [
    ("an article the config does not have", {"article": "skill_cooking",
                                             "slot": "delivered"}),
    ("a slot outside the set", {"article": "mem", "slot": "sticky"}),
    ("an extra key", {"article": "mem", "slot": "delivered",
                      "fbclid": "AbC_123-x"}),
    ("a link in place of the key", {"article": ARTICLES["mem"]["link"],
                                    "slot": "delivered"}),
    ("a missing slot", {"article": "mem"}),
    ("an article of the wrong type", {"article": 1, "slot": "delivered"}),
    ("an article as a list", {"article": ["mem"], "slot": "delivered"}),
    ("a slot of the wrong type", {"article": "mem", "slot": True}),
    ("a payload that is not an object", ["mem", "delivered"]),
]
for label, extra in REFUSED:
    code, stored = tap(SLUG, extra)
    check("  %s is refused, and nothing is written" % label,
          code == 400 and stored is None, str((code, stored)))
for other in ("focus", "kitchen"):
    code, stored = tap(other, {"article": "mem", "slot": "below_paywall"})
    check("  the same event on %s is refused" % other,
          code == 400 and stored is None, str((code, stored)))
check("no schema change: it is one more row in the column every event uses",
      "article" not in read("schema_migrations.sql")
      and "article" not in tracking.INSERT_SQL)

print("\n--- the neighbours ---")
check("focus is the file it was",
      FOCUS["slug"] == "focus" and len(FOCUS["swipe"]["steps"]) == 18
      and FOCUS["result_module"] == "/static/js/result_focus.js")
check("no other config names this funnel's module or its sheet",
      not [n for n in os.listdir(os.path.join(ROOT, "funnels"))
           if n != SLUG + ".json" and "result_ai" in read("funnels/" + n)])
check("result_focus.js and result_brain.js know nothing of it",
      "result_ai" not in read("static/js/result_focus.js")
      and "result_ai" not in read("static/js/result_brain.js")
      and "ai-navigator" not in read("static/js/result_focus.js"))
check("engine.js names no funnel to do any of this",
      "ai-navigator" not in ENGINE and "ai_navigator" not in ENGINE
      and "result_ai" not in ENGINE)

print("\n%d checks, %d failed" % (checks[0], len(fails)))
for f in fails:
    print("  FAIL " + f)
sys.exit(1 if fails else 0)
