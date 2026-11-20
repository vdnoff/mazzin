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
    going live is a later, separate step, so it must not be able to take a
    live charge.
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
# The funnel and its sandbox twin, which is the same config under a second
# slug: neither is "another funnel" to a scan of the rest.
OWN_FILES = (SLUG + ".json", SLUG + "-test.json")
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
WARMUPS = ("skill", "time", "goal", "predict")
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
check("the theme is its own, declared in its own stylesheet",
      cfg["theme"] == "ai" and "body.theme-ai {" in RESULT_CSS
      and "theme-ai" not in MAZZIN_CSS, cfg["theme"])
check("  which the engine loads before the first screen",
      cfg["theme_css"] == cfg["result_css"]
      and "if (themeCss()) {" in ENGINE)
check("it draws its result with its own module",
      cfg["result_module"] == "/static/js/result_ai.js"
      and cfg["result_css"] == "/static/css/result_ai.css")
check("  both on disk",
      os.path.isfile(os.path.join(ROOT, cfg["result_module"].lstrip("/")))
      and os.path.isfile(os.path.join(ROOT, cfg["result_css"].lstrip("/"))))
check("  and the analysing fade lands on the result page's own ground",
      cfg["swipe"]["analyzing_fade_to"] == "#0B0F14"
      and "--ai-ground: #0B0F14;" in RESULT_CSS)

print("\n--- it cannot take a live charge ---")
# There is no report profile for this funnel until its second phase, so a
# purchase today would be delivered somebody else's document. The mechanism
# is the one /focus ships on: the config asks for Stripe's test key set, and
# payments.py refuses checkout rather than fall back to the live keys when
# those are missing. An override row is the only thing that outranks it, and
# that is a deliberate act by a signed-in owner.
#
# That was the build. The funnel is live now: the config says so in as many
# words, the way /zodiac's does, and its sandbox twin keeps the test path.
check("the config asks for the live key set", cfg.get("stripe_mode") == "live")
check("  which is what payments reads off it",
      payments._stripe_mode(cfg) == payments.LIVE
      and payments._stripe_mode(config.load_funnel(SLUG)) == payments.LIVE)
_real = payments._read_override
payments._read_override = lambda slug: None
try:
    check("  and, with no override row, what it transacts on",
          payments.effective_mode(SLUG) == payments.LIVE
          and payments.effective_mode(SLUG, cfg) == payments.LIVE
          and payments.effective_mode(SLUG + "-test") == payments.TEST)
finally:
    payments._read_override = _real
check("  the flag is read the way every funnel's is",
      json.load(open(os.path.join(REPO, "funnels", "zodiac.json")))
      .get("stripe_mode") == "live"
      and 'return TEST if (cfg or {}).get("stripe_mode") == TEST else LIVE'
      in read("payments.py"))
import reports                                               # noqa: E402
check("its report profile is registered, and the twin falls through to it",
      reports.PROFILES.get(SLUG) is reports.AI_PROFILE
      and reports._profile(SLUG + "-test") is reports.AI_PROFILE)

print("\n--- what it says it is ---")
HEADLINE = "11 ways to make money with AI. One has your name on it."
check("the headline, on the intro card and over the walk",
      cfg["intro"]["headline"] == HEADLINE
      and cfg["swipe"]["headline"] == HEADLINE)
check("the intro: kicker, sub, six icon tiles, button with an arrow",
      cfg["intro"]["kicker"] == "AI NAVIGATOR"
      and cfg["intro"]["sub"] == "12 taps. 8 money traps. Find the move "
      "that fits your skill and your week."
      and cfg["intro"]["tiles"]
      == [{"icon": "pen", "label": "Content"},
          {"icon": "bolt", "label": "Automation"},
          {"icon": "shapes", "label": "Design"},
          {"icon": "book", "label": "Workshops"},
          {"icon": "chat", "label": "Outreach"}, {"label": "+6 more"}]
      and "chips" not in cfg["intro"]
      and cfg["intro"]["cta"] == "Find my money move"
      and cfg["intro"]["cta_icon"] == "arrow")
check("  under it: free, optional, and the disclaimer",
      cfg["intro"]["foot"] == "No sign-up. The test and your profile are "
      "free. Your full personal strategy is optional."
      and cfg["intro"]["foot_note"] == cfg["checkout"]["disclaimer"])
check("  eleven ways is the catalog's own count",
      len(cfg["paths"]["catalog"]) == 11)
check("  and the line over the walk keeps its accent",
      cfg["swipe"]["subtext_accent"] in cfg["swipe"]["subtext"])

print("\n--- cut from focus: what is kept and what is dropped ---")
DROPPED = ["track_timing", "result_template", "preview_gallery",
           "style_elements", "analyzing_echo", "sale", "pairings",
           "share_cards", "interstitial_working"]
# Six keys are this funnel's own: `theme_css` and `icons`, beside the theme
# they belong to; `pixel`, beside the Stripe mode that silences its Purchase,
# and `subid_fallback` after it; and, last, `rsoc`, the partner-article block, and `paths`, the table its
# report matches a reader's strategies from.
OWN = ["theme_css", "icons", "pixel", "subid_fallback", "rsoc", "paths"]
check("every top-level key is one focus carries, bar its own six",
      [k for k in cfg if k not in FOCUS] == OWN,
      str([k for k in cfg if k not in FOCUS]))
check("  in focus's order, the theme's stylesheet beside the theme",
      [k for k in cfg if k not in ("theme_css", "icons", "pixel",
                                   "subid_fallback")]
      == [k for k in FOCUS if k in cfg] + OWN[4:]
      and list(cfg)[list(cfg).index("theme"):][:3]
      == ["theme", "theme_css", "icons"]
      and list(cfg)[list(cfg).index("stripe_mode") + 1:][:2]
      == ["pixel", "subid_fallback"] and cfg["subid_fallback"] == "ad_id")
check("its own pixel: the id, the token's variable by name, four events",
      cfg["pixel"] == {"id": "762004311984135",
                       "capi_token_env": "META_CAPI_TOKEN_VISYMO",
                       "events": ["PageView", "Lead", "Purchase",
                                  "AddToCart"]}
      and re.match(r"^[0-9]{5,20}$", cfg["pixel"]["id"]) is not None)
check("  no ViewContent, no InitiateCheckout, and no token in the file",
      "ViewContent" not in cfg["pixel"]["events"]
      and "InitiateCheckout" not in cfg["pixel"]["events"]
      and "access_token" not in json.dumps(cfg)
      and sorted(cfg["pixel"]) == ["capi_token_env", "events", "id"])
check("  and no other funnel has a pixel block",
      not [n for n in os.listdir(os.path.join(REPO, "funnels"))
           if n.endswith(".json") and n not in OWN_FILES
           and "pixel" in json.load(open(os.path.join(REPO, "funnels", n)))])
check("  and the ones with no meaning here are gone, not emptied",
      sorted(k for k in FOCUS if k not in cfg) == sorted(DROPPED),
      str(sorted(k for k in FOCUS if k not in cfg)))
check("no clock, no memorise screen, no time-up line",
      not any("timer_ms" in s or "pool" in s for s in steps)
      and not any(m.get("template") == "flash" or "flash" in m
                  for m in cfg["interstitials"])
      and "timeup_line" not in cfg["swipe"])
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

print("\n--- twelve steps ---")
SCORED = ["%s%d" % (d, n) for d in DOMAINS for n in (1, 2)]
check("twelve, and the walk says so",
      len(steps) == 12 and cfg["swipe"]["pairs_count"] == 12)
check("  ids unique, one pair each",
      len(by_id) == 12 and all(len(s["pairs"]) == 1 for s in steps))
check("  four warm-ups first, in order",
      [s["id"] for s in steps[:4]] == list(WARMUPS))
check("  then two scenarios a zone, in zone order",
      [s["id"] for s in steps[4:]] == SCORED)
for step in steps:
    fmt = step.get("format")
    check("  %s: %s is a format engine.js declares, drawn as text"
          % (step["id"], fmt),
          fmt in GRID_SIZE and fmt in TEXT_FORMATS
          and len(images(step)) == GRID_SIZE.get(fmt), fmt)
CARD_KEYS = {
    "skill": {"id", "label", "sub", "icon", "tags"},
    "time": {"id", "label", "sub", "icon", "badge", "said", "tags"},
    "goal": {"id", "label", "sub", "icon", "said", "tags"},
    "predict": {"id", "label", "icon", "badge", "tags"},
}
check("every card is an id, a label and tags, plus what its step draws",
      all(set(card) == CARD_KEYS.get(s["id"], {"id", "label", "tags"})
          and card["label"].strip()
          for s in steps for card in images(s)))
ids = [card["id"] for s in steps for card in images(s)]
check("  card ids unique across the walk", len(ids) == len(set(ids)))
check("  and no answer is longer than two lines of a row",
      max(len(card["label"]) for s in steps for card in images(s)) <= 56,
      str(max(len(card["label"]) for s in steps for card in images(s))))
check("the counter chip is the warm-ups': eleven in play, then three left",
      [s.get("chip") for s in steps]
      == ["11 strategies still in play"] * 3 + ["3 strategies left"]
      + [None] * 8)
check("the traps count themselves, the warm-ups use the walk's count",
      [s.get("progress_label") for s in steps]
      == [None] * 4 + ["Trap %d of 8" % n for n in range(1, 9)])

print("\n--- the icons: the funnel's own table, drawn by key ---")
ICONS = cfg["icons"]
NEEDED = ["pen", "shapes", "code", "chat", "grid", "book", "cup", "moon",
          "calendar", "bolt", "coins", "storefront", "trending-up", "compass",
          "bars-1", "bars-2", "bars-3", "bars-4", "megaphone", "file-half",
          "clock", "voice", "chart", "image", "thumbs-up", "question", "lock",
          "check", "x", "arrow"]
check("thirty keys, the ones that were asked for", list(ICONS) == NEEDED,
      str(list(ICONS)))
check("  each one path on a 24 grid: commands and numbers, nothing else",
      all(isinstance(d, str) and re.fullmatch(r"[MmLlHhVvCcSsQqTtAaZz0-9 ,."
                                              r"\-]+", d)
          and d.startswith("M") and len(d) <= 220
          and all(-1 <= float(n) <= 25 for n in re.findall(
              r"(?<![\d.])\d+(?:\.\d+)?", d)) for d in ICONS.values()),
      str([k for k, d in ICONS.items()
           if not re.fullmatch(r"[MmLlHhVvCcSsQqTtAaZz0-9 ,.\-]+", d)]))
USED = ([c["icon"] for s in steps for c in images(s) if "icon" in c]
        + [s["icon"] for s in steps if "icon" in s]
        + [t["icon"] for t in cfg["intro"]["tiles"] if "icon" in t]
        + [cfg["intro"]["cta_icon"]])
check("  every icon a card, a trap or the intro names is in the table",
      USED and not [k for k in USED if k not in ICONS], str(USED))
check("  the engine draws from the table: stroked, never filled, no network",
      "var table = cfg && cfg.icons;" in ENGINE
      and 'svg.setAttribute("fill", "none");' in ENGINE
      and 'svg.setAttribute("stroke-width", "2");' in ENGINE
      and 'svg.setAttribute("stroke-linecap", "round");' in ENGINE
      and 'svg.setAttribute("viewBox", "0 0 24 24");' in ENGINE)
check("  and an unknown key draws nothing",
      "|| !Object.prototype.hasOwnProperty.call(table, key)) return null;"
      in ENGINE)
check("  no emoji and no icon font anywhere in the funnel",
      not re.search("[\U0001F000-\U0001FAFF☀-➿]", RAW + RESULT_CSS + MODULE)
      and RESULT_CSS.count("@font-face") == 1)

print("\n--- the four warm-ups: service tags, scoring nothing ---")
WARM = {
    "skill": ("Which one would a stranger pay you for?",
              "Be honest. AI multiplies what you are already good at.",
              [("Writing", "pen", "Words that get read", None),
               ("Design", "shapes", "Things that look right", None),
               ("Tech", "code", "Making tools talk", None),
               ("Sales", "chat", "Getting a yes", None),
               ("Organizing", "grid", "Order out of chaos", None),
               ("Teaching", "book", "Making it click", None)]),
    "time": ("How much of your week can AI money have?",
             "The real number, not the ambitious one.",
             [("Lunch breaks", "cup", "Small, steady moves", "under 3h"),
              ("A few evenings", "moon", "A side-project pace", "3–7h"),
              ("Every weekend", "calendar", "Room to build something",
               "8–15h"),
              ("I'm all in", "bolt", "This is the plan", "15h+")]),
    "goal": ("What's the dream?", None,
             [("Extra cash on the side", "coins", "Something small that pays",
               None),
              ("My own business", "storefront", "The long game", None),
              ("Getting paid more at my job", "trending-up",
               "Same job, better at it", None),
              ("Just curious, for now", "compass", "Show me what's possible",
               None)]),
    "predict": ("Gut check: how many of the 8 money traps will you dodge?",
                None,
                [("I'll walk into most", "bars-1", None, "0–2"),
                 ("About half", "bars-2", None, "3–4"),
                 ("Most of them", "bars-3", None, "5–6"),
                 ("Nearly all. Watch me.", "bars-4", None, "7–8")]),
}
STYLE_TAGS = {t for st in cfg["styles"] for t in st["tags"]}
for sid, (question, sub, cards) in WARM.items():
    step = by_id[sid]
    check("%s asks its question and lists its cards in order" % sid,
          step["question"] == question and step.get("sub") == sub
          and [(c["label"], c.get("icon"), c.get("sub"), c.get("badge"))
               for c in images(step)] == cards,
          str([c["label"] for c in images(step)]))
    check("  dealt as listed, with no feedback line and no letters",
          step.get("shuffle") is False and "why" not in step
          and "letters" not in step)
    check("  one service tag a card, on its own stem",
          all(len(c["tags"]) == 1 and c["tags"][0].startswith(sid + "_")
              and c["tags"][0] == c["id"] for c in images(step)),
          str([c["tags"] for c in images(step)]))
    check("  scoring nothing: no hit, no miss, no type counts it",
          not any(re.search(r"_(hit|miss)$", t) or t in STYLE_TAGS
                  for c in images(step) for t in c["tags"]))
check("the report still hears the plain answer behind a livelier label",
      [c["said"] for c in images(by_id["time"])]
      == ["Under 3", "3–7", "8–15", "15+"]
      and [c["said"] for c in images(by_id["goal"])]
      == ["A side income", "A full business", "More from my current job",
          "Not sure yet"]
      and 'item.get("said") or item.get("label")' in read("reports.py"))
check("the skill, time and goal tags are the ones the rules are keyed on",
      [c["id"] for c in images(by_id["skill"])]
      == ["skill_" + k for k in cfg["paths"]["rules"]["by_skill"]]
      and [c["id"] for c in images(by_id["time"])]
      == ["time_under3", "time_3_7", "time_8_15", "time_15plus"]
      and [c["id"] for c in images(by_id["goal"])]
      == ["goal_side", "goal_business", "goal_levelup", "goal_unsure"])
check("the prediction's four tags are the four bands, shown as its badges",
      [c["tags"][0] for c in images(by_id["predict"])]
      == ["predict_0_2", "predict_3_4", "predict_5_6", "predict_7_8"]
      and [c["badge"] for c in images(by_id["predict"])]
      == [b["label"] for b in cfg["brain_age"]["predict"]["bands"].values()])
check("no warm-up about usage or tools is left",
      "exp" not in by_id and "tool" not in by_id)

print("\n--- the eight money traps: one right answer each ---")
HITS = {
    "mem1": ("megaphone", "The Confident Liar",
             "Nothing. Sure isn't the same as right"),
    "mem2": ("file-half", "The 80-Page Blind Spot",
             "It ran out of room. It can only hold so much"),
    "foc1": ("clock", "The One-Hour Deadline", "Tell it exactly what to fix"),
    "foc2": ("voice", "The Borrowed Voice",
             "Two or three of their real posts"),
    "chg1": ("chart", "The Perfect Statistic", "Open the source. Check it"),
    "chg2": ("image", "The Images Nobody Checked",
             "The tool's rules on selling"),
    "spa1": ("thumbs-up", "The Idea Everyone Loves",
             "Ask a few people to pay up front"),
    "spa2": ("question", "“Why Should I Pay You?”",
             "You're paying for judgment and a result I stand behind"),
}
per_stem = dict.fromkeys(DOMAINS, 0)
for number, step in enumerate(steps[4:], 1):
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
          and hit[0]["label"] == HITS[step["id"]][2],
          hit[0]["label"] if hit else "")
    check("  shuffled when dealt, lettered by where each one lands",
          "shuffle" not in step and "pin_first" not in step
          and step.get("letters") is True)
    check("  named and numbered: MONEY TRAP #%d, its title, its icon" % number,
          step["title_kicker"] == "MONEY TRAP #%d" % number
          and (step["icon"], step["title"]) == HITS[step["id"]][:2]
          and "kicker" not in step and "chip" not in step
          and step["foot"] == "Tap the move you would actually make."
          and not re.search(r"\b(mem|foc|chg|spa)\b",
                            step["title"] + step["question"]),
          step["title"])
    check("  a feedback line of 140 characters or fewer, promising nothing",
          isinstance(step.get("why"), str) and 20 <= len(step["why"]) <= 140
          and not re.search(r"\$|guarant|you will earn", step["why"]),
          step.get("why"))
    per_stem[stem] += 1
check("two traps a zone, eight in all",
      per_stem == dict.fromkeys(DOMAINS, 2)
      and cfg["brain_age"]["scored"] == 8
      and cfg["brain_age"]["per_domain"] == 2, str(per_stem))
check("the zones are named once, in the number block",
      cfg["brain_age"]["domains"] == NAMES)
check("the engine scores on those four stems and no others here",
      all(("var %s_AXIS = [\"%s_hit\", \"%s_miss\"];"
           % (d.upper(), d, d)) in ENGINE for d in DOMAINS))
check("nothing the reader sees still says scenario",
      not [(at, v) for at, v in ALL if re.search(r"scenario", v, re.I)],
      str([(at, v) for at, v in ALL if re.search(r"scenario", v, re.I)][:2]))

print("\n--- instant feedback, switched on from the config ---")
check("the funnel carries the feedback block and its delay",
      cfg["swipe"]["feedback"]
      == {"good": "Trap dodged.", "bad": "You walked into it.",
          "right": "Right answer", "yours": "Your pick", "flags": False,
          "next": False, "streak": "{n} in a row",
          "wait": "Next trap in a moment. Tap to skip.",
          "wait_last": "Your result in a moment."}
      and cfg["swipe"]["feedback_ms"] == 2000)
check("  and a score strip that counts the dodges",
      cfg["swipe"]["score_strip"]
      == {"label": "{n} dodged",
          "aria": "{hit} dodged, {miss} walked into, {left} still to come"})
check("  and a shorter hold on the steps that have none",
      cfg["swipe"]["hold_ms"] == 450)
check("the engine answers back only where both are declared",
      "var block = cfg && cfg.swipe && cfg.swipe.feedback;" in ENGINE
      and 'if (!st || typeof st.why !== "string" || !st.why) return null;'
      in ENGINE)
FEEDBACK = ENGINE[ENGINE.index("function runFeedback("):
                  ENGINE.index("// --- interstitials")]
check("  it tracks nothing and scores nothing of its own",
      "track(" not in FEEDBACK and "scores[" not in FEEDBACK
      and "chosen.push" not in FEEDBACK)
check("  the swipe event still fires at the tap, before any of it",
      ENGINE.index('track("swipe", step, extra);')
      < ENGINE.index("if (fb) { runFeedback("))
STEP_KEYS = ("title", "title_kicker", "foot", "chip", "sub", "letters",
             "icon", "progress_label", "why")
no_feedback = []
for name in sorted(os.listdir(os.path.join(ROOT, "funnels"))):
    if name in OWN_FILES:
        continue
    other = json.loads(read("funnels/" + name))
    swipe = other.get("swipe") or {}
    intro = other.get("intro") or {}
    if ("icons" in other or "theme_css" in other
            or any(k in swipe for k in ("feedback", "score_strip", "hold_ms"))
            or any(k in intro for k in ("tiles", "cta_icon", "foot_note"))
            or any(k in st for st in swipe.get("steps") or []
                   for k in STEP_KEYS)
            or any("cut" in m for m in other.get("interstitials") or [])):
        no_feedback.append(name)
check("no other funnel declares any of the new switches", not no_feedback,
      no_feedback)

print("\n--- the one screen between ---")
mids = cfg["interstitials"]
check("one interstitial, after the fourth step, and no other",
      len(mids) == 1 and mids[0]["after_step"] == 4)
check("  eleven cut down to three, with three locked rows",
      mids[0]["kicker"] == "MATCH IN PROGRESS"
      and mids[0]["cut"] == {"from": "11", "to": "3",
                             "rows": ["Strategy 1", "Strategy 2",
                                      "Strategy 3"]}
      and mids[0]["line"] == "Your skill, hours and goal just cut 11 "
      "strategies down to 3.")
check("  what is next, and a button that waits to be tapped",
      mids[0]["sub"] == "Next: 8 money traps. How you handle them shapes "
      "your plan: where to start, what to offer and what to skip."
      and mids[0]["cta"] == "Show me trap #1" and mids[0]["hold"] is True
      and "auto_advance_ms" not in mids[0])
check("the analysing screen is kept",
      cfg["analyzing"]["duration_ms"] > 0 and cfg["analyzing"]["messages"])

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
          winner({tag: 2}) == sid, winner({tag: 2}))
check("  an all-hit run resolves to the first: A > B > C > D",
      winner({t: 2 for _, _, t in STYLES}) == "mechanic")
check("  and every two-way tie goes to the earlier zone",
      winner({"foc_hit": 2, "chg_hit": 2}) == "director"
      and winner({"chg_hit": 1, "spa_hit": 1}) == "editor"
      and winner({"mem_hit": 2, "spa_hit": 2}) == "mechanic")
check("  a run that hits nothing still resolves to a type",
      winner({}) == "mechanic")
ESSENCE = {
    "mechanic": "You know how the machine really works. That keeps your work "
                "from breaking.",
    "director": "You get results out of AI fast. Speed is what you sell.",
    "editor": "You catch what AI gets wrong. That is the part clients cannot "
              "get from the tool.",
    "dealmaker": "You see where the money is. The tool is just how you "
                 "deliver.",
}
check("each has the essence line the result page prints under the name",
      cfg["result_copy"]["profile"]["essence"] == ESSENCE)
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
check("  each says what its card's badge says",
      [b["label"] for b in bands.values()]
      == [c["badge"] for c in images(by_id["predict"])])
check("  and together they cover 0 to 8 with no gap and no overlap",
      [(b["min"], b["max"]) for b in bands.values()]
      == [(0, 2), (3, 4), (5, 6), (7, 8)])


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
    for hits in range(9):
        seen.setdefault(calibration(band, hits), []).append((tag, hits))
LABELS = cfg["result_copy"]["calibration"]
check("all three headlines are reachable", set(seen) == {"on", "under", "over"})
check("  inside the band", LABELS["on"] == "You know exactly where you stand."
      and calibration(bands["predict_5_6"], 6) == "on")
check("  above it", LABELS["under"] == "Better than you think."
      and calibration(bands["predict_3_4"], 6) == "under")
check("  below it",
      LABELS["over"] == "Confidence is ahead of skill. Easy to fix."
      and calibration(bands["predict_7_8"], 5) == "over")
check("  the lowest band cannot be bold and the highest cannot be underrated",
      not any(t == "predict_0_2" for t, _ in seen["over"])
      and not any(t == "predict_7_8" for t, _ in seen["under"]))
check("the line is the reader's two numbers and nobody else's",
      cfg["result_copy"]["calibration_line"]
      == "You predicted {band}. You scored {n}."
      and cfg["result_copy"]["score_of"] == "{n}/{total}")
check("a skipped prediction shows the score alone",
      "if (data.band) {" in MODULE and "copy.score_only" in MODULE
      and "return null;" in MODULE.split("function predictionOf", 1)[1]
      .split("function calibrationOf", 1)[0])


def level(hits):
    for row in block["levels"]:
        if "max" not in row or hits <= row["max"]:
            return row["label"]


check("three levels: Explorer 0–2, Builder 3–5, Operator 6–8",
      [level(n) for n in range(9)]
      == ["Explorer"] * 3 + ["Builder"] * 3 + ["Operator"] * 3)
check("  read off the config's table by the module, top to bottom",
      "typeof rows[i].max !== \"number\" || hits <= rows[i].max" in MODULE)

print("\n--- the report, as it is promised ---")
SECTIONS = [("dna", "Your AI Profile & Your Edge"),
            ("materials", "Your 3 Best-Fit Strategies"),
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
check("plus the manifest line: Your 8 Traps",
      key_rows == [{"title": "Your 8 Traps",
                    "hook": "Every trap, your move, the right move, and "
                            "what it means for your plan."}])
check("  and nothing the reader sees still says path or answer key",
      not [(at, v) for at, v in ALL
           if not at.startswith((".paths", ".rsoc"))
           and re.search(r"\bpaths?\b|answer key|twelve", v, re.I)],
      str([(at, v) for at, v in ALL
           if not at.startswith((".paths", ".rsoc"))
           and re.search(r"\bpaths?\b|answer key|twelve", v, re.I)][:3]))
check("  the catalog says plan on, never typically",
      all(row["first_client"].startswith("Plan on ")
          for row in cfg["paths"]["catalog"])
      and "Typically" not in RAW)
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
OFFER = cfg["result_copy"]["offer"]
check("the offer card says it is about making money with AI",
      OFFER["label"] == "YOUR WAY TO MAKE MONEY WITH AI"
      and OFFER["head"] == "Your answers point to one strategy for making "
      "money with AI."
      and OFFER["line"] == "Unlock your report to see which one it is, and "
      "exactly how to start.")
check("  what it unlocks is four lines, inside the card",
      OFFER["unlock_title"] == "WHAT YOU UNLOCK"
      and OFFER["unlock"]
      == ["The strategy for making money with AI that fits you, matched to "
          "your answers",
          "What to sell, and who pays for it",
          "Your first 7 days, sized to your {hours} a week",
          "2 backup strategies, 2 to skip, and your 8 traps explained"])
check("  the hours are the four the time step offers",
      set(OFFER["hours"]) == {c["id"] for c in images(by_id["time"])}
      and OFFER["hours_bare"] == "hours")
check("  one line under the button, and it is the only place that says so",
      OFFER["under"] == "{price} one-time. No subscription. PDF copy to "
      "your email."
      and cfg["checkout"]["price_suffix"] == ""
      and cfg["checkout"]["commerce"]["price_suffix"] == "")
check("  no locked rows and no second list",
      "rows" not in OFFER and "line_bare" not in OFFER)

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
      co["cta_label"] == "Unlock my strategy · {price}"
      and co["commerce"]["sticky_label"] == co["cta_label"])
literal = [(at, v) for at, v in ALL
           if re.search(r"[$€£]\s?\d|\d\s?(usd|dollars?|bucks)\b|\b6\.00\b",
                        v, re.I)]
check("no literal price in any string", not literal, str(literal[:3]))
priced = [at for at, v in ALL if "{price}" in v]
check("  the strings that name one interpolate it",
      {"checkout.cta_label", "checkout.anchor", "checkout.anchor_head",
       "checkout.commerce.anchor_head", "checkout.commerce.sticky_label",
       "result_copy.offer.under"}
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
check("in the checkout block", co["disclaimer"] == DISCLAIMER)
check("on the intro, and in the footer of the result",
      cfg["intro"]["foot_note"] == DISCLAIMER
      and cfg["result_copy"]["disclaimer"] == DISCLAIMER)
check("  the module prints it as the last thing on both pages",
      MODULE.count("var foot = footer(ctx, copy);") == 2
      and MODULE.count("if (foot) root.appendChild(foot);") == 2)

print("\n--- nothing in it promises money ---")
# Exactly this, and no more. The funnel may talk plainly about earning with
# AI and about business; what it may not do is promise it, or put a figure on
# a day, a week or a month of it. The same core list reports.py holds the
# model's own sentences to.
PERIODIC = (r"(?:[$€£]\s?\d[\d,.]*\s?(?:k|m|thousand|million)?"
            r"|\d[\d,.]*\s?(?:k\s)?(?:dollars|euros|pounds|usd|eur|gbp))"
            r"\s*(?:\+\s*)?(?:a|an|per|each|every|/)\s*"
            r"(?:hour|day|week|month|year|hr|wk|mo|yr)\b")
BANNED = [r"\bguarant\w+", PERIODIC, r"\bget\s+rich\b",
          r"\bpassive\s+income\b", r"\bquit\s+your\s+job\b"]
check("the list is the one reports.py holds the model to",
      [rx.pattern for rx in reports.AI_BANNED_CORE] == BANNED)
# The one string the spec itself requires that trips the scan: the disclaimer
# says that nothing is guaranteed. Allowlisted by exact path and exact text,
# in the three places it is printed, so no other string can hide behind it.
ALLOW = {
    (".checkout.disclaimer", DISCLAIMER),
    (".result_copy.disclaimer", DISCLAIMER),
    (".intro.foot_note", DISCLAIMER),
}
check("the three exceptions are where the allowlist says they are",
      all(pair in set(ALL) for pair in ALLOW))
hits = [(at, v) for at, v in ALL if (at, v) not in ALLOW
        and any(re.search(p, v, re.I) for p in BANNED)]
check("no banned phrase in any other string (%d scanned)" % len(ALL),
      not hits, str(hits[:3]))
for probe in ("Guaranteed results", "a guarantee", "get rich with AI",
              "Passive income", "quit your job", "$500 a day",
              "$1,000/week", "$ 3000 per month", "$3,000/month",
              "€2k per week",
              "500 dollars a day"):
    check("  the scan would catch %r" % probe,
          any(re.search(p, probe, re.I) for p in BANNED))
for fine in ("Secret prompts", "make money with AI", "an AI business",
             "overnight", "a paid plan", "$6", "2–6 weeks"):
    check("  and it lets %r through" % fine,
          not any(re.search(p, fine, re.I) for p in BANNED))
OTHERS = [r"most people", r"\d+\s?% of", r"\b\d[\d,]* (people|users|readers|"
          r"customers|students)\b", r"testimonial", r"\bhurry\b",
          r"limited time", r"last chance", r"only \d+ left", r"ends (today|"
          r"tonight|soon)", r"before it'?s gone", r"act now", r"\btoday only"]
hits = [(at, v) for at, v in ALL
        if any(re.search(p, v, re.I) for p in OTHERS)]
check("no statistic about other people, no testimonial, no urgency",
      not hits, str(hits[:3]))
check("no string puts a currency figure on what anybody earns",
      not [(at, v) for at, v in ALL
           if re.search(r"(earn|income|revenue|profit|make)\w*[^.]{0,40}"
                        r"[$€£]\s?\d", v, re.I)])

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
         if name not in OWN_FILES
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
FREE = MODULE.split("function render(root, ctx) {", 1)[1].split(
    "// --- the paid page", 1)[0]
check("the free page is hero, score card, offer card, guides card, footer",
      re.findall(r"root\.appendChild\((\w+)\(", FREE)
      == ["profileBlock", "scoreCard", "offer"]
      and FREE.index("root.appendChild(offer(ctx, copy));")
      < FREE.index('articles(ctx, data, "below_paywall")')
      < FREE.index("var foot = footer(ctx, copy);"))
check("  with no zone bars, round strip, level chip or free strength",
      not re.search(r"bars\(|strip\(|levelChip|strength\(|path\(", FREE)
      and "function strip(" not in MODULE
      and "function levelChip(" not in MODULE
      and "function strength(" not in MODULE)
check("  and no standalone unlock section, divider or locked rows",
      "function unlocks(" not in MODULE and "function divider(" not in MODULE
      and "ai-locked" not in MODULE and "ai-unlock" not in MODULE
      and ".ai-locked" not in RESULT_CSS and ".ai-unlock" not in RESULT_CSS
      and ".ai-divider" not in RESULT_CSS)
OFFER_FN = MODULE.split("function offer(ctx, copy) {", 1)[1].split(
    "var CHECK_PATH", 1)[0]
check("the strategy's name is an empty bar, never text",
      'top.appendChild(bar("is-name"));' in OFFER_FN
      and 'node.setAttribute("aria-hidden", "true");' in MODULE.split(
          "function bar(cls) {", 1)[1].split("}", 1)[0])
check("  the unlock list is built before the payment nodes are moved in",
      OFFER_FN.index('elm("ul", "ai-checks")')
      < OFFER_FN.index("nodes.payButton, nodes.payError]")
      < OFFER_FN.index('elm("p", "ai-offer-under"'))
check("  and it reads nothing of the strategies, sections or right answers",
      not re.search(r"visuals|paths|catalog|sections|_hit|\.why|reveals",
                    OFFER_FN))
check("the zone bars are on the paid page only",
      "root.appendChild(bars(ctx, copy, data));" in MODULE.split(
          "function delivered(root, ctx) {", 1)[1])
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
SELECTORS = [sel.strip() for block in re.findall(
    r"^([^\s/@}][^{]*)\{", re.sub(r"/\*.*?\*/", "", RESULT_CSS, flags=re.S),
    re.M) for sel in block.split(",")]
LOOSE = [sel for sel in SELECTORS
         if not re.match(r"(body\.theme-ai\b|\.is-ai\b|\.ai-)", sel)
         and sel not in ("from", "to")]
check("the stylesheet is scoped to this theme and this module (%d selectors)"
      % len(SELECTORS), len(SELECTORS) > 150 and not LOOSE, str(LOOSE[:4]))
check("  the tokens are the ones specified",
      all(("--ai-%s: %s;" % pair) in RESULT_CSS for pair in (
          ("ground", "#0B0F14"), ("card", "#151B23"), ("border", "#26303B"),
          ("track", "#1C242E"), ("text", "#F2F5F7"), ("soft", "#C3CCD6"),
          ("muted", "#9AA7B4"), ("accent", "#C8F53B"),
          ("on-accent", "#0B0F14"), ("tint", "#1B2410"), ("miss", "#FF9A7A"),
          ("miss-tint", "#2A1712"), ("offer", "#131A12"),
          ("locked", "#33402A"))))
check("  one web font, on this site, with display swap; no image, no gradient",
      re.findall(r'url\("([^"]+)"\)', RESULT_CSS)
      == ["/static/fonts/space-grotesk-latin-var.woff2"]
      and os.path.isfile(os.path.join(
          ROOT, "static/fonts/space-grotesk-latin-var.woff2"))
      and RESULT_CSS.count("@font-face") == 1
      and "font-display: swap;" in RESULT_CSS
      and "@import" not in RESULT_CSS and "gradient" not in RESULT_CSS)
check("  the wordmark stays Fraunces, with the dot in the accent",
      'font-family: "Fraunces var", Georgia, serif;' in RESULT_CSS
      and 'body.theme-ai .swipe-brand::after { content: "."; '
          'color: var(--ai-accent); }' in RESULT_CSS)

print("\n--- the partner articles: the block ---")
RSOC = cfg.get("rsoc") or {}
ARTICLES = RSOC.get("articles") or {}
SKILL_TAGS = [t for card in next(s for s in steps if s["id"] == "skill")
              ["pairs"][0]["images"] for t in card["tags"]]
check("the block has exactly the keys it was specified with",
      list(RSOC) == ["enabled", "placement", "require_fbclid", "passthrough",
                     "kicker", "kicker_delivered", "head", "head_delivered",
                     "sub", "tag_start", "tag_skill", "tag_zone", "note",
                     "articles"],
      str(list(RSOC)))
check("  on, in both places, and only for a reader who came from a click",
      RSOC.get("enabled") is True
      and RSOC.get("placement") == ["below_paywall", "delivered"]
      and RSOC.get("require_fbclid") is True)
check("  passing on the three identifiers, in this order",
      RSOC.get("passthrough") == ["fbclid", "ad_id", "asid"])
check("  the card's own words: kicker, headline, line, and the note",
      RSOC.get("kicker") == "NOT READY TO UNLOCK YET?"
      and RSOC.get("head") == "Get the basics first. Free."
      and RSOC.get("sub") == "{n} free guides on the tools and skills behind "
      "your profile. Your money strategy stays in your report."
      and RSOC.get("note")
      == "Opens evoseekly.com, a partner site that shows ads.")
check("  nothing in the guides card says \"make money\"",
      not re.search(r"make money", json.dumps(
          {k: v for k, v in RSOC.items()}), re.I))
check("  the same card after the money, under its own kicker and headline",
      RSOC.get("kicker_delivered") == "KEEP GOING"
      and RSOC.get("head_delivered")
      == "Keep going: free guides for your profile")
check("  and a tag over each button saying why it was picked",
      RSOC.get("tag_start") == "START HERE"
      and RSOC.get("tag_skill") == "PICKED FOR YOUR SKILL: {skill}"
      and RSOC.get("tag_zone") == "PICKED FOR WHERE YOU HAVE THE MOST ROOM")
check("  no featured article is shipped: its link does not exist yet",
      "start" not in ARTICLES)
check("  but the module draws one first when the config carries it",
      'var FEATURED = "start";' in MODULE
      and "[FEATURED, keys.skill, DOMAINS.indexOf(keys.zone) !== -1 ? "
          "keys.zone : \"\"]" in MODULE)
import tracking as _tracking                                 # noqa: E402
check("  and tracking takes its tap with no change: keys come off the config",
      "if isinstance(key, str) and isinstance(article, dict):" in
      read("tracking.py") and "articles.add(key)" in read("tracking.py"))
check("  no label repeats that it is a free guide",
      not [a["label"] for a in ARTICLES.values()
           if re.search(r"free guide", a["label"], re.I)
           or not a["label"][0].isupper()])
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
SHOWN = ([RSOC.get(k, "") for k in
          ("kicker", "kicker_delivered", "head", "head_delivered", "sub",
           "tag_start", "tag_skill", "tag_zone", "note")]
         + [a["label"] for a in ARTICLES.values()])
check("  and the lines a reader sees pass the banned scan",
      all(text in {v for _, v in ALL} for text in SHOWN)
      and not [text for text in SHOWN
               if any(re.search(p, text, re.I) for p in BANNED)])
check("no other funnel carries the block",
      not [n for n in os.listdir(os.path.join(ROOT, "funnels"))
           if n not in OWN_FILES
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
      # The fifth reader is the subid fallback, which takes the ad id and
      # nothing else, on a funnel that asks for it.
      and ENGINE.count("heldPassthrough()") == 5
      and 'var subid = own || heldPassthrough().ad_id || "";' in ENGINE
      and 'if (!cfg || cfg.subid_fallback !== "ad_id") return;' in ENGINE)
check("the tracker does not send them",
      "passthrough" not in ENGINE.split("function track(event,", 1)[1]
      .split("\n  }\n", 1)[0]
      and "console." not in KEEP and "console." not in HELD)
RS = MODULE.split("// --- partner articles", 1)[1].split(
    "// --- the free page", 1)[0]
check("always two guides: a level run breaks its tie spa, foc, chg, mem",
      'var GUIDE_TIE = ["spa", "foc", "chg", "mem"];' in RS
      and "if (data.room) return data.room;" in RS
      and "keys.zone = guideZone(data);" in RS)
check("  for the guides only: the score card's rule is where it was",
      'room: level ? "" : low,' in MODULE
      and "GUIDE_TIE" not in MODULE.split("// --- partner articles", 1)[0])
check("the offer card's wallet holder collapses in theme CSS only",
      "body.theme-ai .ai-offer .xp__slot.xp__off,\n"
      "body.theme-ai .ai-offer #pay-button.xp__off { display: none; }"
      in RESULT_CSS and "xp" not in MODULE)
check("the module builds real anchors, a new tab, noopener",
      'elm("a", "ai-rsoc-link" + (first ? " is-featured" : ""))' in RS
      and 'elm("span", "ai-rsoc-text", item.label)' in RS
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
           if n not in OWN_FILES and "result_ai" in read("funnels/" + n)])
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
