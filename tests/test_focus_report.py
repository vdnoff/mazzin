#!/usr/bin/env python3
"""The focus product: the number a purchase stores, and the plan it buys.

/focus is the second product on the platform that MEASURES rather than reads,
and the first whose number moves on how fast somebody answered. That changes
what has to be true of the document in two ways.

The number. The browser worked it out while the run existed — a base, a cost
per miss, and a point a step for answering each of the twelve timed rounds
inside half its clock — and put it on the screen before any money changed
hands. The order carried the reaction times through Stripe, and the report
has to arrive at exactly the same figure from exactly the same table. So the
check below is the client's own formula, restated here and walked: a clean
fast run is a hundred, a clean slow run is eighty-eight, an all-miss run is
the floor whatever the times were, a step the clock answered earns nothing,
and a purchase whose order carried no times scores its accuracy and never
crashes. The one place the two languages disagree is a half, and the speed
bonus lands on halves.

And the line. This product's drift is towards a condition with a name.
Every such word is refused in the prompt and again in the answer, and the
round trip below proves the second one. The report may never tell the reader
something is wrong with them: the zone they scored lowest on is the zone with
the most room in it, in the system prompt, in the shapes, and in every stub
that ships when there is no key.

    python3 tests/test_focus_report.py
"""
import json
import math
import os
import re
import sys

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, REPO)

import database                                            # noqa: E402

# No suite talks to a database.
database.execute = lambda *a, **kw: None
database.query_all = lambda *a, **kw: []
database.query_one = lambda *a, **kw: None

import payments                                            # noqa: E402
import reports                                             # noqa: E402

CFG = json.load(open(os.path.join(REPO, "funnels/focus.json"),
                     encoding="utf-8"))
BRAIN = json.load(open(os.path.join(REPO, "funnels/brain.json"),
                       encoding="utf-8"))
MODULE = open(os.path.join(REPO, "static/js/result_focus.js"),
              encoding="utf-8").read()
ENGINE = open(os.path.join(REPO, "static/js/engine.js"),
              encoding="utf-8").read()
PAY = open(os.path.join(REPO, "payments.py"), encoding="utf-8").read()
STEPS = CFG["swipe"]["steps"]
BLOCK = CFG["brain_age"]
SPEED = BLOCK["speed"]
TIMED = [step for step in STEPS if step.get("timer_ms")]

fails = []
checks = [0]


def check(label, ok, detail=""):
    checks[0] += 1
    if not ok:
        fails.append("%s %s" % (label, detail))
    print("  %-62s %s%s" % (label, "ok" if ok else "FAIL",
                            ("  " + str(detail)) if detail and not ok else ""))


DOMAINS = ("mem", "foc", "chg", "spa")


def run_of(per_round, thief="thief_notifications", work="work_remote"):
    """(choices, tag_scores) for a walk that hits `per_round` of each zone.

    `per_round` is one number or a map of zone to hits. Built by walking the
    config the way a reader does — every step answered on its first version,
    every tag counted — so what goes in is what a real purchase would carry.
    """
    want = dict((key, per_round) for key in DOMAINS) \
        if isinstance(per_round, int) else dict(per_round)
    choices = []
    scores = {}
    got = dict((key, 0) for key in DOMAINS)
    for step in STEPS:
        images = step["pairs"][0]["images"]
        domain = images[0]["tags"][0].split("_")[0]
        if domain in got:
            want_hit = got[domain] < want[domain]
            pick = next(i for i in images
                        if i["tags"][0].endswith("_hit") == want_hit)
            if want_hit:
                got[domain] += 1
        elif step["id"] == "thief" and thief:
            pick = next(i for i in images if thief in i["tags"])
        elif step["id"] == "work" and work:
            pick = next(i for i in images if work in i["tags"])
        else:
            pick = images[0]
        choices.append(pick["id"])
        for tag in pick["tags"]:
            scores[tag] = scores.get(tag, 0) + 1
    return choices, scores


def times_at(frac, only=None):
    """A reaction map: every timed step answered at `frac` of its clock."""
    return dict((step["id"], int(round(step["timer_ms"] * frac)))
                for step in TIMED if only is None or step["id"] in only)


def js_round(value):
    return int(math.floor(value + 0.5))


def bonus(frac):
    full = SPEED["full_frac"]
    if frac <= full:
        return 1.0
    return max(0.0, min(1.0, (1 - frac) / (1 - full)))


def client_score(misses, fracs=()):
    """result_focus.js's own arithmetic, restated: base, misses, speed."""
    rule = BLOCK["score"]
    earned = min(SPEED["steps"] * SPEED["point_per_step"],
                 sum(bonus(f) * SPEED["point_per_step"] for f in fracs))
    raw = js_round(rule["base"] + rule["per_miss"] * misses + earned)
    return max(rule["floor"], min(BLOCK["max"], raw))


STYLE = CFG["styles"][0]

print("--- the profile is registered, and it is its own ---")
profile = reports._profile("focus")
check("focus resolves to a profile of its own",
      profile is reports.FOCUS_PROFILE)
check("  and its -test twin falls through to it",
      reports._profile("focus-test") is reports.FOCUS_PROFILE)
check("  rather than to kitchen, which is what it used to get",
      profile is not reports.KITCHEN_PROFILE
      and profile is not reports.BRAIN_PROFILE)
check("it writes in a voice nobody else writes in",
      profile["system"] is reports.FOCUS_SYSTEM
      and profile["system"] not in (reports.KITCHEN_PROFILE["system"],
                                    reports.BRAIN_PROFILE["system"],
                                    reports.PERSONA_PROFILE["system"]))
check("  a productivity coach, with the tactics named outright",
      "productivity coach" in profile["system"]
      and all(w in profile["system"] for w in
              ("phone", "timer", "one tab", "first block", "night before")))
check("  and refuses a list of its own",
      profile["banned"] is reports.FOCUS_BANNED
      and profile["banned"] is not reports.BRAIN_BANNED)
check("the document is named as the plan the offer sells",
      profile["pdf_lead"] == "Your 7-Day Productivity Boost Plan"
      and CFG["checkout"]["product_name"] == profile["pdf_lead"])
check("  and the mail is this product's own, not kitchen's or brain's",
      profile["mail"] is reports.COPY_FOCUS
      and profile["mail_link"] is reports.ZODIAC_EMAIL_LINK)

print("\n--- four chapters, and which of them the run writes ---")
SECTIONS = ("dna", "materials", "mistakes", "shopping")
check("the spec is exactly the four the funnel sells",
      tuple(sorted(profile["spec"])) == tuple(sorted(SECTIONS)),
      str(sorted(profile["spec"])))
check("  which are the four ids the funnel's own config declares, titled "
      "as the brief set them",
      [s["id"] for s in CFG["report"]["sections"]] == list(SECTIONS)
      and [s["title"] for s in CFG["report"]["sections"]]
      == ["Your Productivity Profile & Your Edge",
          "Your Weakest Zone — and the Fastest Lift",
          "5 Sharp Strengths & 2 Habits to Drop",
          "Your 7-Day Productivity Boost Plan"])
check("the strengths are cached, because they belong to the profile",
      profile["cached"] == ("mistakes",), str(profile["cached"]))
check("  and the other three are written for the run",
      profile["personal"] == ("dna", "materials", "shopping"))
check("  disjoint, and between them every chapter",
      not set(profile["cached"]) & set(profile["personal"])
      and set(profile["cached"]) | set(profile["personal"]) == set(SECTIONS))
check("every chapter ships a stub, for the path with no key",
      sorted(profile["stubs"]) == sorted(SECTIONS))
check("  in the shapes the chapters are read in",
      len(profile["stubs"]["dna"]["narrative"]) == 3
      and len(profile["stubs"]["dna"]["implications"]) == 3
      and [p["combo"] for p in profile["stubs"]["materials"]["pairs"]]
      == [BLOCK["domains"][d] for d in DOMAINS]
      and len(profile["stubs"]["mistakes"]["items"]) == 7
      and len(profile["stubs"]["shopping"]["items"]) == 8
      and profile["stubs"]["shopping"]["items"][-1]["name"]
      == "Day 8 - Play again")
check("  and the stub helper leaves the seven alone",
      len(reports._stub_for("mistakes", STYLE["name"], STYLE,
                            stubs=reports.FOCUS_STUBS)["items"]) == 7)
check("nothing here has a palette or a year map to police",
      profile.get("verify") is None
      and reports._months_for(profile) is None)

print("\n--- the number, against the formula the browser ran ---")
check("Python's own round disagrees with the browser on a half",
      round(92.5) == 92 and reports._js_round(92.5) == 93)
for style in CFG["styles"]:
    for per_round, frac, label in ((4, 0.0, "a clean fast run"),
                                   (4, 1.0, "a clean slow run"),
                                   (0, 0.0, "an all-miss run, fast"),
                                   (2, 0.75, "half of every zone, mid"),
                                   (3, 0.6, "one miss each, quick")):
        choices, scores = run_of(per_round)
        numbers = reports._focus_numbers(CFG, style, scores, choices,
                                         times_at(frac))
        misses = BLOCK["scored"] - per_round * len(DOMAINS)
        # A miss earns nothing: only the hit timed steps carry a fraction.
        hit_timed = sum(1 for step in TIMED
                        if per_round > int(step["id"][-1]) - 1)
        want = client_score(misses, [frac] * hit_timed)
        check("  %-12s %-24s scores %3d" % (style["id"], label, want),
              numbers and numbers["score"] == want,
              str(numbers and numbers["score"]))
choices, scores = run_of(4)
fast = reports._focus_numbers(CFG, STYLE, scores, choices, times_at(0.0))
slow = reports._focus_numbers(CFG, STYLE, scores, choices, times_at(1.0))
check("a clean fast run is a hundred, and a clean slow run the base",
      fast["score"] == 100 and slow["score"] == 88 == BLOCK["base"]
      and slow["age"] == 88 and fast["misses"] == 0)
check("  with every zone four of four",
      all(fast["counts"][key] == 4 for key in DOMAINS))
choices, scores = run_of(0)
floor = reports._focus_numbers(CFG, STYLE, scores, choices, times_at(0.0))
check("an all-miss run lands on the floor clamp however fast it was",
      floor["score"] == BLOCK["min"] == 5 and floor["speed"]["bonus"] == 0
      and floor["misses"] == BLOCK["scored"])
check("  which is where the formula would have gone under it",
      BLOCK["base"] + BLOCK["per_miss"] * BLOCK["scored"] < BLOCK["min"])
choices, scores = run_of(4)
mid = reports._focus_numbers(CFG, STYLE, scores, choices, times_at(0.75))
check("three quarters of every clock pays half a point a step",
      mid["speed"]["bonus"] == 6.0 and mid["score"] == 94,
      str((mid["speed"]["bonus"], mid["score"])))
check("  and the bonus falls with the time, never rises",
      all(reports._focus_bonus(a, SPEED) >= reports._focus_bonus(b, SPEED)
          for a, b in zip([i / 20 for i in range(21)],
                          [i / 20 for i in range(1, 21)]))
      and reports._focus_bonus(0.5, SPEED) == 1
      and reports._focus_bonus(1.0, SPEED) == 0)
check("  capped at what the table says the timed rounds are worth",
      reports._focus_numbers(
          CFG, STYLE, scores, choices,
          dict((k, 0) for k in times_at(0.0)))["speed"]["bonus"]
      == SPEED["steps"] * SPEED["point_per_step"])

print("\n--- a purchase with no times, and a step the clock answered ---")
choices, scores = run_of(3)
plain = reports._focus_numbers(CFG, STYLE, scores, choices)
check("a purchase whose order carried no times scores its accuracy",
      plain["score"] == client_score(4) == 60
      and plain["speed"]["bonus"] == 0 and plain["speed"]["answered"] == 0
      and plain["speed"]["avg_ms"] is None and plain["speed"]["label"] == "")
check("  and never crashes on nonsense in the slot",
      reports._focus_numbers(CFG, STYLE, scores, choices, "no",
                             [7, None])["score"] == 60
      and reports._focus_numbers(CFG, STYLE, scores, choices,
                                 {"nope": 12, "foc1": "fast"})["score"] == 60)
choices, scores = run_of(4)
late = reports._focus_numbers(CFG, STYLE, scores, choices, times_at(0.0),
                              timed_out=["foc2", "spa4"])
check("a step the clock answered earns nothing and is not counted as "
      "answered",
      late["speed"]["answered"] == 10 and late["speed"]["bonus"] == 10
      and late["score"] == 98)
content = reports.start_report(1, "focus", STYLE["id"], scores,
                               choices=choices, reactions=times_at(0.0),
                               timed_out=["foc2", "spa4"])
brain = (content.get("visuals") or {}).get("brain") or {}
check("  and the stored record marks it as the clock's",
      [row["status"] for row in brain.get("rounds") or []
       if row["id"] in ("foc2", "spa4")] == ["out", "out"]
      and (content.get("visuals") or {}).get("timed_out") == ["foc2", "spa4"])
check("  with no picture of the card the clock happened to press",
      all(not row["img"] for row in brain.get("rounds") or []
          if row["status"] == "out")
      and sum(1 for cell in brain.get("strip") or []
              if cell["status"] == "out") == 2)

print("\n--- the tie is broken in play order, not brain's ---")
choices, scores = run_of({"mem": 4, "foc": 1, "chg": 4, "spa": 1})
tie = reports._focus_numbers(CFG, STYLE, scores, choices)
check("focus and speed level: focus has the most room, because it is played "
      "first",
      tie["weakest"] == "foc", tie["weakest"])
check("  where brain's order would have named speed",
      reports.BRAIN_DOMAINS.index("spa") < reports.BRAIN_DOMAINS.index("foc")
      and reports.FOCUS_DOMAINS == DOMAINS)
choices, scores = run_of(2)
check("  and a four-way tie names memory, the first zone played",
      reports._focus_numbers(CFG, STYLE, scores, choices)["weakest"] == "mem")
check("  which is the module's own tie-break",
      'var DOMAINS = ["mem", "foc", "chg", "spa"];' in MODULE
      and "if (worst === null || got < worst.got)" in MODULE)

print("\n--- and it is the same block the page draws ---")
choices, scores = run_of(3)
content = reports.start_report(2, "focus", STYLE["id"], scores,
                               choices=choices, reactions=times_at(0.3))
brain = (content.get("visuals") or {}).get("brain") or {}
hit_timed = sum(1 for step in TIMED if 3 > int(step["id"][-1]) - 1)
check("a purchase stores the number the free page showed",
      brain.get("score") == client_score(4, [0.3] * hit_timed),
      str(brain.get("score")))
check("  with all four zones beside it, and the type",
      sorted(brain.get("counts") or {}) == sorted(DOMAINS)
      and all(brain["counts"][key] == 3 for key in DOMAINS)
      and brain.get("type") == STYLE["id"]
      and brain.get("type_name") == STYLE["name"])
check("  the speed: the average, and the table's word for it",
      isinstance(brain.get("speed"), dict)
      and brain["speed"]["answered"] == 12
      and abs(brain["speed"]["avg_frac"] - 0.3) < 0.01
      and brain["speed"]["label"] == "Lightning"
      and isinstance(brain["speed"]["avg_ms"], float))
check("  every key the delivered page reads is on it",
      all(key in brain for key in ("age", "hits", "misses", "scored",
                                   "counts", "score", "room_rounds",
                                   "elite", "speed", "rounds", "strip")))
check("  and the module reads the speed back rather than recomputing it",
      "stored.speed" in MODULE
      and 'speedLine(data, "br-dhero-pace")' in MODULE
      and "typeof stored.speed.avg_ms === \"number\"" in MODULE)
check("the sixteen rounds are named in this funnel's own words",
      set(reports.FOCUS_TASKS) == {s["id"] for s in STEPS
                                   if s["id"] not in ("work", "thief")}
      and len(brain.get("rounds") or []) == 16
      and all(row["domain"] in DOMAINS for row in brain["rounds"]))
check("  and the strip is the whole walk, eighteen tiles",
      len(brain.get("strip") or []) == 18)
plain = reports.start_report(3, "focus", STYLE["id"], scores, choices=choices)
check("a purchase with no times stores the accuracy-only block, no crash",
      ((plain.get("visuals") or {}).get("brain") or {}).get("score")
      == client_score(4)
      and plain["visuals"]["brain"]["speed"]["answered"] == 0)
check("the age-group keys are carried empty, never invented",
      brain.get("age_mid") is None and brain.get("delta") is None)
check("no other product grew a brain block",
      not (reports.start_report(
          4, "persona", json.load(open(os.path.join(
              REPO, "funnels/persona.json"), encoding="utf-8"))["styles"][0]
          ["id"], {"drive": 4}).get("visuals") or {}).get("brain"))
check("  and brain's own is still brain's",
      "speed" not in ((reports.start_report(
          5, "brain", BRAIN["styles"][0]["id"], {"mem_hit": 4},
          choices=None).get("visuals") or {}).get("brain") or {}))

print("\n--- the order carries the times, and only on this funnel ---")
check("engine.js sends the map with the order",
      "payload.reactions = JSON.parse(JSON.stringify(stepTimes));" in ENGINE)
ORDER = re.search(r"function orderPayload\(\)\s*\{(.*?)\n  \}", ENGINE,
                  re.S).group(1)
check("  gated on the funnel SCORING speed, not merely tracking it",
      "if (speedScored() && Object.keys(stepTimes).length)" in ORDER
      and "cfg && cfg.brain_age && cfg.brain_age.speed" in ENGINE)
check("  so the memory game's order is the one it always was",
      "speed" not in BRAIN["brain_age"] and "speed" in BLOCK)
check("  and still carries only what it always did beside it",
      "tag_scores: scores" in ORDER and "choices: chosen.slice()" in ORDER)
check("payments.py validates every entry against the step's own clock",
      "def _clean_reactions(cfg, raw):" in PAY
      and "out[step_id] = max(0, min(clock, int(value)))" in PAY)
brain_cfg = BRAIN
clean = payments._clean_reactions
check("  unknown steps are dropped, and steps without a clock",
      clean(CFG, {"foc1": 1200, "mem1": 900, "nope": 3}) == {"foc1": 1200})
check("  a time is clamped to [0, clock]",
      clean(CFG, {"foc1": 99999, "chg4": -5}) == {"foc1": 5000, "chg4": 0})
check("  and anything that is not a number is dropped",
      clean(CFG, {"foc1": "1200", "foc2": True, "foc3": None, "foc4": 1.9})
      == {"foc4": 1})
check("  a map with nothing usable is None, and so is nonsense",
      clean(CFG, {"nope": 1}) is None and clean(CFG, []) is None
      and clean(CFG, None) is None and clean(CFG, {}) is None)
check("  and a map too big to be a walk is dropped whole",
      clean(CFG, dict(("s%d" % i, 1) for i in range(40))) is None
      and payments.REACTIONS_MAX >= len(TIMED))
packed = payments._reactions_metadata(times_at(0.4))
check("it packs under Stripe's value limit and reads back the same",
      packed and len(packed) < payments.METADATA_VALUE_MAX
      and payments._read_reactions(CFG, packed) == times_at(0.4),
      str(packed)[:60])
check("  refusing garbage on the way back",
      payments._read_reactions(CFG, "foc1:abc,zzz,foc2:12") == {"foc2": 12}
      and payments._read_reactions(CFG, "") is None
      and payments._read_reactions(CFG, None) is None)
check("the metadata carries it only when there is one",
      "reactions" in payments._metadata("focus", "s", "architect", None,
                                        reactions="foc1:12")
      and "reactions" not in payments._metadata("focus", "s", "architect",
                                                None))
check("  through the webhook, into the report, beside the timeouts",
      'reactions = _read_reactions(cfg, metadata.get("reactions"))' in PAY
      and "reactions=reactions," in PAY
      and "reactions=None, timed_out=None):" in PAY)
check("  and it logs nothing about what was sent", "log" not in
      re.search(r"def _clean_reactions\(cfg, raw\):(.*?)\ndef ", PAY,
                re.S).group(1))

print("\n--- the line this product must not cross ---")
BANNED_WORDS = ("ADHD", "attention deficit", "disorder", "diagnosis",
                "burnout", "anxiety", "depression", "therapy", "medication",
                "mental health", "symptom", "clinical", "IQ",
                "brain training", "psychic", "prediction")
for word in BANNED_WORDS:
    check("  %r is refused in the answer" % word,
          any(p.search("A sentence with %s in it." % word)
              for p in reports.FOCUS_BANNED))
system = reports.FOCUS_SYSTEM
for word in BANNED_WORDS:
    check("    %r is named in the system prompt as forbidden" % word,
          word.lower() in system.lower(), word)
check("the system prompt says what this document is instead",
      "MOST ROOM" in system and "plan" in system.lower())
check("  and refuses the vocabulary of failure outright",
      all(('"%s"' % word) in system
          for word in ("weak", "poor", "failing", "struggle")))
check("  never sending anybody to see anybody",
      "Never suggest anybody see anyone about anything." in system)
choices, scores = run_of(3)
numbers = reports._focus_numbers(CFG, STYLE, scores, choices, times_at(0.4))
every_prompt = "\n".join(
    reports._section_prompt(STYLE, STYLE["name"], scores, section_id,
                            cfg=CFG, choices=choices, funnel_slug="focus",
                            numbers=numbers)
    for section_id in profile["personal"])
every_prompt += reports._cached_prompt(STYLE, STYLE["name"],
                                       funnel_slug="focus")
hit = reports._banned_hit(every_prompt, reports.FOCUS_BANNED)
check("no prompt this profile builds carries a banned word", hit is None,
      str(hit))
check("  the prompt names the score and the reaction word, once",
      "Their Focus Score came to %d out of 100" % numbers["score"]
      in every_prompt and "Lightning" in every_prompt)
check("  and the time thief and the workplace, by the reader's own words",
      "Notifications" in every_prompt and "Remote" in every_prompt
      and "built around beating Notifications" in every_prompt)
check("  with the zones in play order and the one with the most room named",
      "- Memory: 3 of 4" in every_prompt
      and every_prompt.index("- Memory:") < every_prompt.index("- Focus:")
      < every_prompt.index("- Switching:") < every_prompt.index("- Speed:")
      and "zone with the most room in it is Memory" in every_prompt)
no_warmups = reports._section_prompt(
    STYLE, STYLE["name"], {"mem_hit": 4}, "shopping", cfg=CFG,
    choices=None, funnel_slug="focus")
check("a run with no warm-ups falls back cleanly",
      "named no time thief" in no_warmups
      and "phone and the inbox" in no_warmups
      and reports._banned_hit(no_warmups, reports.FOCUS_BANNED) is None)
check("  and a prompt built with no times says so rather than guessing",
      "No reaction times were recorded" in reports._section_prompt(
          STYLE, STYLE["name"], scores, "dna", cfg=CFG, choices=choices,
          funnel_slug="focus"))
every_stub = json.dumps([reports._stub_for(section_id, STYLE["name"], STYLE,
                                           stubs=reports.FOCUS_STUBS)
                         for section_id in SECTIONS], ensure_ascii=False)
check("  and neither does a single stub it ships",
      reports._banned_hit(json.loads(every_stub), reports.FOCUS_BANNED)
      is None,
      str(reports._banned_hit(json.loads(every_stub), reports.FOCUS_BANNED)))
check("  nor the word 'weakness' anywhere in them",
      "weakness" not in every_stub.lower()
      and "wrong with you" not in every_stub.lower())
check("  and every stub day is a thing somebody does",
      all(re.match(r"^Day \d - ", item["name"])
          for item in reports.FOCUS_STUBS["shopping"]["items"]))
config_text = json.dumps(CFG, ensure_ascii=False)
check("the config itself is clean on the same list",
      reports._banned_hit(json.loads(config_text), reports.FOCUS_BANNED)
      is None)

print("\n--- a dirty answer is redrawn, then stubbed ---")
LONG = ("You keep hold of what you were just shown for a beat longer than "
        "most people do, and it turns up all day in the brief you only read "
        "once and the list you only wrote once.")
SECOND = ("That pairs with how quickly you decide, which together make you "
          "the one who has already started while everybody else is still "
          "opening tabs at their desk.")
THIRD = ("Point the same attention at the zone with the most room in it and "
         "the score climbs faster than anything else in this plan will move "
         "it for you this week.")


def answer(word):
    return json.dumps({"dna": {
        "narrative": [LONG.replace("You keep hold", "Your %s keeps hold"
                                   % word), SECOND, THIRD],
        "implications": ["Write tomorrow's first task on a card tonight.",
                         "Put the phone in the hall for the first block.",
                         "Say a changed plan aloud before you act on it."]}})


def replay(text):
    seen = []

    def attempt(client, prompt, max_tokens, label, system):
        seen.append(label)
        return text, "stop"

    real = reports._attempt
    reports._attempt = attempt
    try:
        out = reports._generate(
            object(), "prompt", ("dna",), system=reports.FOCUS_SYSTEM,
            banned=reports.FOCUS_BANNED, detail=True)
    finally:
        reports._attempt = real
    return out, len(seen)


clean_out, clean_tries = replay(answer("attention"))
check("the same answer, clean, is accepted on the first attempt",
      clean_out is not None and clean_tries == 1)
dirty_out, dirty_tries = replay(answer("burnout"))
check("one banned word in it and it is refused after one redraw",
      dirty_out is None and dirty_tries == 2)

print("\n--- the document and the mail ---")
check("the cover is this product's, with one number on it",
      profile["pdf_cover"] is reports._focus_cover
      and profile["pdf_after_cover"] is reports._focus_table
      and profile["pdf_body"] is reports.BRAIN_PROFILE["pdf_body"]
      and profile["pdf_css"] == reports.BRAIN_PROFILE["pdf_css"]
      and profile["pdf_taps"] is False)
check("  and the reaction line under it is the page's own words",
      reports._focus_speed_line(brain) == "Avg reaction: %.1fs — Lightning"
      % (brain["speed"]["avg_ms"] / 1000.0)
      and reports._focus_speed_line({}) == "")
try:
    html_out = reports._pdf_html(content)
    built = True
except Exception as exc:                                # pragma: no cover
    html_out, built = str(exc), False
check("the PDF's HTML builds from a stored purchase",
      built and "hero-score" in html_out and "Avg reaction:" in html_out
      and 'class="hero-age"' not in html_out
      and profile["pdf_lead"] in html_out, html_out[:120])
check("  grouping the rounds in play order",
      built and html_out.index("Memory") < html_out.index("Switching")
      < html_out.index("Speed"))
check("the mail is chosen by the profile",
      reports._email_copy(content) is reports.COPY_FOCUS)
check("  and its first line is about the score, in the coach's voice",
      "raises the score" in reports._email_opening(content)
      and reports._banned_hit(json.dumps(reports.COPY_FOCUS),
                              reports.FOCUS_BANNED) is None)

print("\n%d checks, %d failed" % (checks[0], len(fails)))
for line in fails:
    print("  FAIL " + line)
sys.exit(1 if fails else 0)
