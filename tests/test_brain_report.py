#!/usr/bin/env python3
"""The brain product: the number a purchase stores, and the plan it buys.

/brain is the first product on the platform that MEASURES rather than reads.
A kitchen, a sign and a temperament are all readings — interesting is enough.
This one puts a number on somebody's head and calls it an age, and that
changes what has to be true of the document.

Two things, mostly.

The number. The browser worked it out while the run existed and put it on the
screen before any money changed hands; the report has to arrive at exactly the
same figure from exactly the same table. So the check below is not "the server
computes something sensible" — it is the client's own formula, restated here,
walked over every brain type and both ends of the range, and compared. The one
place the two languages disagree is a half: Python rounds it to even and
JavaScript rounds it up, and three misses at 3.5 apiece is 32.5.

And the line. This product's drift is not a horoscope or a personality
framework — it is a diagnosis. Every word that turns a game into an assessment
is refused in the prompt and again in the answer, and the round trip below
proves the second one. The report may never tell the reader something is wrong
with them: the round they scored lowest on is the round with the most room in
it, and that phrasing is in the system prompt, in the shapes, and in every
stub that ships when there is no key.

    python3 tests/test_brain_report.py
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

import reports                                             # noqa: E402
import tracking                                            # noqa: E402

CFG = json.load(open(os.path.join(REPO, "funnels/brain.json"),
                     encoding="utf-8"))
MODULE = open(os.path.join(REPO, "static/js/result_brain.js"),
              encoding="utf-8").read()
STEPS = CFG["swipe"]["steps"]

fails = []
checks = [0]


def check(label, ok, detail=""):
    checks[0] += 1
    if not ok:
        fails.append("%s %s" % (label, detail))
    print("  %-62s %s%s" % (label, "ok" if ok else "FAIL",
                            ("  " + str(detail)) if detail and not ok else ""))


DOMAINS = ("mem", "spa", "chg", "foc")


def run_of(per_round, age_tag="age_40"):
    """(choices, tag_scores) for a walk that hits `per_round` of each round.

    Built by walking the config the way a reader does — every step answered,
    every tag counted — so what goes in is what a real purchase would carry.
    """
    choices = []
    scores = {}
    got = dict((key, 0) for key in DOMAINS)
    for step in STEPS:
        images = step["pairs"][0]["images"]
        domain = images[0]["tags"][0].split("_")[0]
        if domain in got:
            want_hit = got[domain] < per_round
            pick = next(i for i in images
                        if i["tags"][0].endswith("_hit") == want_hit)
            if want_hit:
                got[domain] += 1
        elif step["id"] == "age":
            pick = next(i for i in images if age_tag in i["tags"])
        else:
            pick = images[0]
        choices.append(pick["id"])
        for tag in pick["tags"]:
            scores[tag] = scores.get(tag, 0) + 1
    return choices, scores


print("--- the profile is registered, and it is its own ---")
profile = reports._profile("brain")
check("brain resolves to a profile of its own",
      profile is reports.BRAIN_PROFILE)
check("  and a -test twin would fall through to it",
      reports._profile("brain-test") is reports.BRAIN_PROFILE)
check("  rather than to kitchen, which is what it used to get",
      profile is not reports.KITCHEN_PROFILE)
check("it writes in a voice nobody else writes in",
      profile["system"] is reports.BRAIN_SYSTEM
      and profile["system"] not in (reports.KITCHEN_PROFILE["system"],
                                    reports.ZODIAC_PROFILE["system"],
                                    reports.PERSONA_PROFILE["system"]))
check("  and refuses a list of its own",
      profile["banned"] is reports.BRAIN_BANNED
      and profile["banned"] is not reports.PERSONA_PROFILE["banned"])
check("the document is named as a plan",
      profile["pdf_lead"] == "Your Brain Refresh report")
check("  and the mail is this product's own, not kitchen's fallback",
      profile["mail"] is reports.COPY_BRAIN)

print("\n--- four chapters, and which of them the run writes ---")
SECTIONS = ("dna", "materials", "mistakes", "shopping")
check("the spec is exactly the four the funnel sells",
      tuple(sorted(profile["spec"])) == tuple(sorted(SECTIONS)),
      str(sorted(profile["spec"])))
check("  which are the four ids the funnel's own config declares",
      [s["id"] for s in CFG["report"]["sections"]] == list(SECTIONS),
      str([s["id"] for s in CFG["report"]["sections"]]))
check("the strengths are cached, because they belong to the type",
      profile["cached"] == ("mistakes",), str(profile["cached"]))
check("  and the other three are written for the run",
      profile["personal"] == ("dna", "materials", "shopping"),
      str(profile["personal"]))
check("the two sets are disjoint",
      not set(profile["cached"]) & set(profile["personal"]))
check("  and between them they cover every chapter",
      set(profile["cached"]) | set(profile["personal"]) == set(SECTIONS))
check("every chapter ships a stub, for the path with no key",
      sorted(profile["stubs"]) == sorted(SECTIONS),
      str(sorted(profile["stubs"])))
check("nothing here has a palette or a year map to police",
      profile.get("verify") is None
      and reports._months_for(profile) is None)

print("\n--- the number, against the formula the browser ran ---")
BLOCK = CFG["brain_age"]


def client_age(misses):
    """engine.js's own arithmetic, restated. `Math.round`, not Python's."""
    raw = BLOCK["base"] + BLOCK["per_miss"] * misses
    age = int(math.floor(raw + 0.5))
    return max(BLOCK["min"], min(BLOCK["max"], age))


# The table's per-miss lands on whole numbers today, so nothing in this
# funnel's own range exercises the difference. It is still the difference,
# and a per-miss that goes back to a half — this one has already been 3.5
# once — would land straight on it, so the conversion is checked on the value
# rather than through the config.
check("Python's own round disagrees with the browser on a half",
      round(32.5) == 32 and reports._js_round(32.5) == 33,
      "round() says %s" % round(32.5))
check("  and agrees with it everywhere else",
      all(reports._js_round(v) == round(v)
          for v in (22.0, 26.4, 33.6, 78.0, 80.2)))

for style in CFG["styles"]:
    for per_round, label in ((4, "a perfect run"), (0, "an all-miss run"),
                             (2, "half of every round"), (3, "one miss each")):
        choices, scores = run_of(per_round)
        numbers = reports._brain_numbers(CFG, style, scores)
        misses = BLOCK["scored"] - per_round * len(DOMAINS)
        check("  %-14s %-18s scores %d" % (style["id"], label,
                                           client_age(misses)),
              numbers and numbers["age"] == client_age(misses),
              str(numbers and numbers["age"]))
choices, scores = run_of(4)
numbers = reports._brain_numbers(CFG, CFG["styles"][0], scores)
check("a perfect run lands on the base",
      numbers["age"] == BLOCK["base"] and numbers["misses"] == 0)
choices, scores = run_of(0)
numbers = reports._brain_numbers(CFG, CFG["styles"][0], scores)
# The formula's own ceiling is above the clamp now — sixteen misses at four
# years apiece is 86 against a maximum of 80 — so the clamp is what the reader
# actually sees at that end, and it is checked as the thing it now is.
RAW_CEILING = BLOCK["base"] + BLOCK["per_miss"] * BLOCK["scored"]
check("  and an all-miss run on the clamp rather than past it",
      numbers["age"] == BLOCK["max"] and numbers["misses"] == BLOCK["scored"],
      str(numbers["age"]))
check("  which is where the formula would have gone over it",
      RAW_CEILING > BLOCK["max"], "%s vs %s" % (RAW_CEILING, BLOCK["max"]))
check("  and the browser clamps at the same number",
      client_age(BLOCK["scored"]) == BLOCK["max"])
check("a funnel with no table stores nothing",
      reports._brain_numbers({}, CFG["styles"][0], scores) is None)
check("  and neither does a run with no tallies",
      reports._brain_numbers(CFG, CFG["styles"][0], {}) is None)

print("\n--- and it is the same block the page draws ---")
choices, scores = run_of(3, age_tag="age_50")
content = reports.start_report(1, "brain", CFG["styles"][0]["id"], scores,
                               choices=choices)
brain = (content.get("visuals") or {}).get("brain") or {}
check("a purchase stores the number", brain.get("age") == client_age(4),
      str(brain.get("age")))
check("  with all four rounds beside it",
      sorted(brain.get("counts") or {}) == sorted(DOMAINS)
      and all(brain["counts"][key] == 3 for key in DOMAINS),
      str(brain.get("counts")))
check("  their own age group, and the distance from it",
      brain.get("age_mid") == BLOCK["age_mid"]["age_50"]
      and brain.get("delta") == brain["age"] - brain["age_mid"],
      str((brain.get("age_mid"), brain.get("delta"))))
check("  the round with the most room in it",
      brain.get("weakest") in DOMAINS, str(brain.get("weakest")))
check("  and the type the run resolved to",
      brain.get("type") == CFG["styles"][0]["id"], str(brain.get("type")))
check("every key the delivered page reads is on it",
      all(key in brain for key in ("age", "hits", "misses", "scored",
                                   "counts", "age_mid", "delta")),
      str(sorted(brain)))
check("  which is the same list the module reads back",
      all(('stored.%s' % key) in MODULE or ('stored.counts' in MODULE)
          for key in ("age", "hits", "misses", "scored"))
      and "ctx.visuals && ctx.visuals.brain" in MODULE)
check("no other product grew a brain block",
      not (reports.start_report(
          2, "persona", json.load(open(os.path.join(
              REPO, "funnels/persona.json"), encoding="utf-8"))["styles"][0]
          ["id"], {"drive": 4}).get("visuals") or {}).get("brain"))

print("\n--- the line this product must not cross ---")
BANNED_WORDS = ("memory loss", "cognitive", "decline", "dementia", "health",
                "diagnosis", "treatment", "symptom", "disorder", "patient",
                "clinical", "brain training", "IQ")
for word in BANNED_WORDS:
    check("  %r is refused in the answer" % word,
          any(p.search("A sentence with %s in it." % word)
              for p in reports.BRAIN_BANNED))
# The system prompt is the one text that has to SAY the words it forbids, so
# it is checked the other way round: every pattern on the list is a word the
# prompt names as one never to use.
system = reports.BRAIN_SYSTEM
for word in BANNED_WORDS:
    check("  and named in the system prompt as forbidden" if word == "IQ"
          else "    %r is named there as forbidden" % word,
          word.lower() in system.lower(), word)
check("the system prompt says what this document is instead",
      "MOST ROOM" in system and "plan" in system.lower())
check("  and refuses the vocabulary of failure outright",
      all(('"%s"' % word) in system
          for word in ("weak", "poor", "failing", "struggle")))
check("  never sending anybody to see anybody",
      "Never suggest anybody see anyone about anything." in system)
every_prompt = "\n".join(
    reports._section_prompt(CFG["styles"][0], "The Recorder", scores,
                            section_id, cfg=CFG, choices=choices,
                            funnel_slug="brain")
    for section_id in profile["personal"])
every_prompt += reports._cached_prompt(CFG["styles"][0], "The Recorder",
                                       funnel_slug="brain")
hit = reports._banned_hit(every_prompt, reports.BRAIN_BANNED)
check("no prompt this profile builds carries a banned word", hit is None,
      str(hit))
every_stub = json.dumps([reports._stub_for(section_id, CFG["styles"][0],
                                           stubs=reports.BRAIN_STUBS)
                         for section_id in SECTIONS], ensure_ascii=False)
check("  and neither does a single stub it ships",
      reports._banned_hit(json.loads(every_stub), reports.BRAIN_BANNED)
      is None,
      str(reports._banned_hit(json.loads(every_stub), reports.BRAIN_BANNED)))
check("  nor the word 'weakness' anywhere in them",
      "weakness" not in every_stub.lower())

print("\n--- a dirty answer is redrawn, then stubbed ---")
LONG = ("You hold what you were shown for a beat longer than most people do, "
        "and it turns up in every part of an ordinary week where somebody "
        "only tells you a thing once.")
SECOND = ("That pairs with how fast you spot a difference, which together "
          "make you the one who notices a change before anybody else has "
          "looked up from what they were doing.")
THIRD = ("Point the same attention at the round with the most room in it and "
         "the number comes down faster than anything else in this plan will "
         "move it for you this week.")


def answer(word):
    return json.dumps({"dna": {
        "narrative": [LONG.replace("You hold", "Your %s holds" % word),
                      SECOND, THIRD],
        "implications": ["Say a new name out loud once, the first time.",
                         "Take one look back before you leave a room.",
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
            object(), "prompt", ("dna",), system=reports.BRAIN_SYSTEM,
            banned=reports.BRAIN_BANNED, detail=True)
    finally:
        reports._attempt = real
    return out, len(seen)


clean_out, clean_tries = replay(answer("recall"))
check("the same answer, clean, is accepted", clean_out is not None,
      str(clean_out)[:60])
check("  on the first attempt", clean_tries == 1, str(clean_tries))
dirty_out, dirty_tries = replay(answer("cognitive"))
check("one banned word in it and it is refused", dirty_out is None,
      str(dirty_out)[:60])
check("  after exactly one redraw", dirty_tries == 2, str(dirty_tries))
check("  and the word is what did it, not the shape",
      reports._banned_hit(json.loads(answer("cognitive")),
                          reports.BRAIN_BANNED) is not None
      and reports._banned_hit(json.loads(answer("recall")),
                              reports.BRAIN_BANNED) is None)

print("\n--- the four rounds come off the run, not the model ---")
choices, scores = run_of(4)
scores["chg_hit"] = 1
scores["chg_miss"] = 3
numbers = reports._brain_numbers(CFG, CFG["styles"][0], scores)
pairs = reports._brain_pairs_block(numbers)
check("the weakest round is the one with the fewest hits",
      numbers["weakest"] == "chg", str(numbers["weakest"]))
check("the pairs block names all four, in the config's own words",
      all(("- %s — " % name) in pairs
          for name in CFG["brain_age"]["domains"].values()), pairs)
check("  three of four or better is a strength",
      "- Memory — works" in pairs and "- Focus — works" in pairs, pairs)
check("  and the round with room in it carries the other verdict",
      "- Change — avoid" in pairs, pairs)
check("  which the profile prints as something a reader can act on",
      profile["words"]["verdicts"] == {"works": "STRENGTH",
                                       "avoid": "ROOM TO GROW"},
      str(profile["words"]["verdicts"]))
check("  while every other product keeps the badge it had",
      reports.RENDER_WORDS["verdicts"] == {"works": "WORKS",
                                           "avoid": "AVOID"})
plan = reports._brain_plan_block(numbers)
check("the plan's first day belongs to that same round",
      "drills for Change" in plan and "day one and day four" in plan.lower(),
      plan[:90])
rounds = reports._brain_rounds_block(numbers)
check("the model is told the scores and told not to print them",
      "- Change: 1 of 4" in rounds
      and "never print a score" in rounds.lower(), rounds[:80])
check("  and told outright that the round with room is not a weakness",
      "most room in it" in rounds
      and "rather than as a weakness" in rounds, rounds[:80])

print("\n--- the document it all arrives in ---")
choices, scores = run_of(2, age_tag="age_60")
content = reports.start_report(3, "brain", CFG["styles"][1]["id"], scores,
                               choices=choices)
content["version"] = "llm-2"
check("four sections, titled the way the funnel sells them",
      [s["title"] for s in content["sections"]]
      == [s["title"] for s in CFG["report"]["sections"]],
      str([s["title"] for s in content["sections"]]))
html = reports._pdf_html(content)
check("the PDF names the product as a plan",
      "Brain Refresh" in html, "pdf_lead")
check("  and badges the rounds as strengths and room to grow",
      "ROOM TO GROW" in html or "STRENGTH" in html)
pdf = reports.build_pdf(content)
check("it renders", pdf[:4] == b"%PDF")
check("  and fits in a mailbox: under 3 MB",
      len(pdf) < 3 * 1024 * 1024, "%.2f MB" % (len(pdf) / 1048576.0))
check("nothing banned reaches the finished document",
      reports._banned_hit(content, reports.BRAIN_BANNED) is None,
      str(reports._banned_hit(content, reports.BRAIN_BANNED)))

copy = reports._email_copy(content)
check("the mail is this funnel's own", copy is reports.COPY_BRAIN)
opening = reports._email_opening(content)
check("  and never gets kitchen's line about renovators",
      "renovator" not in opening.lower() and "$4,000" not in opening,
      opening)
check("  it names what was actually bought",
      "number you were shown" in opening, opening)
check("  and the body names the four promises",
      all(word in copy["body"].lower()
          for word in ("most room", "drill", "strengths", "seven days")),
      copy["body"])

print("\n--- the timing keys the client has been holding back ---")
step = STEPS[2]
images = [i["id"] for i in step["pairs"][0]["images"]]
# v11: a scored step names its pairs after the versions of itself it can
# play, so the pair this event reports is the one the cards came from rather
# than a fixed "p1".
BASE = {"pair": step["id"] + ":" + step["pairs"][0]["id"],
        "shown": images, "chosen": images[0]}


def clean(extra):
    try:
        return tracking._clean_extra("brain", "swipe", dict(extra))
    except ValueError:
        return None


check("the three that were always required still are",
      tracking.SWIPE_EXTRA_KEYS == frozenset(("pair", "shown", "chosen")),
      str(sorted(tracking.SWIPE_EXTRA_KEYS)))
check("  and a swipe carrying only those three is still valid",
      clean(BASE) == BASE)
check("the two the timing funnels add are optional, not required",
      tracking.SWIPE_EXTRA_OPTIONAL == frozenset(("elapsed_ms", "timed_out")),
      str(sorted(tracking.SWIPE_EXTRA_OPTIONAL)))
check("  a reaction time is stored", (clean(dict(BASE, elapsed_ms=1234))
                                      or {}).get("elapsed_ms") == 1234)
check("  a clock-answered step is stored",
      (clean(dict(BASE, timed_out=True)) or {}).get("timed_out") is True)
check("  both together are stored",
      clean(dict(BASE, elapsed_ms=0, timed_out=True))
      == dict(BASE, elapsed_ms=0, timed_out=True))
check("  and a false one is accepted without being written",
      clean(dict(BASE, timed_out=False)) == BASE)
for label, extra in (
        ("a reaction that is a string", dict(BASE, elapsed_ms="12")),
        ("a reaction that is a float", dict(BASE, elapsed_ms=1.5)),
        ("a reaction that is a bool", dict(BASE, elapsed_ms=True)),
        ("a negative reaction", dict(BASE, elapsed_ms=-1)),
        ("a reaction past the minute", dict(BASE, elapsed_ms=60001)),
        ("a timed_out that is an int", dict(BASE, timed_out=1)),
        ("a key nobody declared", dict(BASE, whatever=1)),
        ("a swipe missing one of the three", {"pair": BASE["pair"],
                                              "shown": BASE["shown"]})):
    check("  %s is refused" % label, clean(extra) is None)
check("a reaction of exactly a minute is the last one accepted",
      (clean(dict(BASE, elapsed_ms=tracking.ELAPSED_MAX_MS))
       or {}).get("elapsed_ms") == tracking.ELAPSED_MAX_MS)
check("no other event shape moved",
      tracking.SHARE_EXTRA_KEYS == frozenset(("persona",)))
check("and the funnel now asks for the two",
      CFG.get("track_timing") is True
      and json.load(open(os.path.join(REPO, "static/funnels/brain.json"),
                         encoding="utf-8")).get("track_timing") is True)

print("\n--- v5: one of the seven days is food ---")
shopping = reports._BRAIN_SHAPES["shopping"]
check("the plan gives a day to what goes on the plate",
      "ONE OF THE REMAINING DAYS IS FUEL" in shopping
      and "a day about food" in shopping)
check("  three or four ordinary things, and where they go",
      "three or\nfour ordinary things to put on a plate" in shopping
      or "ordinary things to put on a plate" in shopping, shopping[:40])
check("  buyable anywhere, and said in the same register as every other day",
      "buyable in any supermarket" in shopping)
check("  with nothing out of a bottle and nothing measured",
      "Nothing out of a bottle and nothing measured" in shopping)
check("  and no claim that eating something does anything",
      "Never\nclaim that eating something has been shown to do anything."
      in shopping or "has been shown to do anything" in shopping)
check("it shows the register rather than describing it",
      shopping.count("BAD ") >= 2 and shopping.count("GOOD ") >= 2)
FOOD_WORDS = ("supplement", "supplements", "vitamin", "dosage", "dose")
for word in FOOD_WORDS:
    check("  %r is refused in the answer" % word,
          any(p.search("Take a %s each morning." % word)
              for p in reports.BRAIN_BANNED))
    check("    and named in the system prompt as forbidden",
          word.lower() in reports.BRAIN_SYSTEM.lower(), word)
check("the shape itself carries none of them",
      reports._banned_hit(shopping, reports.BRAIN_BANNED) is None,
      str(reports._banned_hit(shopping, reports.BRAIN_BANNED)))
check("  and neither does the stub that ships without a key",
      reports._banned_hit(reports.BRAIN_STUBS["shopping"],
                          reports.BRAIN_BANNED) is None)
check("  which has a fuel day of its own",
      any("Fuel" in row["name"]
          for row in reports.BRAIN_STUBS["shopping"]["items"]),
      str([row["name"] for row in reports.BRAIN_STUBS["shopping"]["items"]]))
check("    naming food anybody can buy",
      any("walnuts" in row["priority_note"]
          for row in reports.BRAIN_STUBS["shopping"]["items"]))
check("no other profile grew the food ban",
      not any(p.pattern == r"\bsupplements?\b"
              for p in reports.PERSONA_PROFILE["banned"])
      and not any(p.pattern == r"\bsupplements?\b"
                  for p in reports.ZODIAC_PROFILE["banned"]))
check("  and kitchen still refuses nothing of its own",
      reports.KITCHEN_PROFILE["banned"] == ())

print("\n--- v6: the week ends on a second run ---")
shopping = reports._BRAIN_SHAPES["shopping"]
# Matched against the prompt with its wrapping collapsed: these are sentences
# in a paragraph that is hard-wrapped to fit the file, and a check bound to
# where the wrap happens to fall breaks on a reflow that changed nothing.
FLAT = " ".join(shopping.split())
check("the plan asks for eight days, not seven",
      "EIGHT items under `items`" in FLAT
      and '"Day 8 - Play again"' in shopping)
check("  and the eighth is the challenge again",
      "DAY EIGHT IS THE POINT OF THE OTHER SEVEN" in FLAT
      and "the eighth day is the second run" in FLAT)
check("  with nothing said about how far the number will move",
      "say nothing about how far the number will move" in FLAT
      and "promises is the measurement, not the result" in FLAT)
check("  and the food day is still in there",
      "ONE OF THE REMAINING DAYS IS FUEL" in FLAT)
days = reports.BRAIN_STUBS["shopping"]["items"]
check("the stub carries eight days too", len(days) == 8, str(len(days)))
check("  named in order, day one to day eight",
      [row["name"].split(" - ")[0] for row in days]
      == ["Day %d" % n for n in range(1, 9)],
      str([row["name"] for row in days]))
check("  the last of them the second run",
      days[-1]["name"] == "Day 8 - Play again"
      and "play the rounds from the top" in days[-1]["priority_note"].lower(),
      days[-1]["name"])
check("  which promises a measurement rather than a result",
      not re.search(r"\d+\s*(?:%|percent|years)",
                    days[-1]["priority_note"]),
      days[-1]["priority_note"])
check("  and the fuel day survived beside it",
      any("Fuel" in row["name"] for row in days),
      str([row["name"] for row in days]))
check("eight fits inside the schema's own ceiling",
      reports.SHAPE["shopping"]["items"][1] <= 8
      <= reports.SHAPE["shopping"]["items"][2],
      str(reports.SHAPE["shopping"]["items"][1:3]))
check("nothing banned reached either the shape or the stub",
      reports._banned_hit(shopping, reports.BRAIN_BANNED) is None
      and reports._banned_hit(reports.BRAIN_STUBS["shopping"],
                              reports.BRAIN_BANNED) is None)

print("\n--- v6: the rounds a clock answered, on the stored report ---")
# The ids cannot be derived from the run: a reader may genuinely tap the card
# the clock would have pressed, so a report that guessed would draw a cross
# over a round somebody played. They travel explicitly or not at all — which
# is why a purchase that names none still writes no key rather than an empty
# one.
choices, scores = run_of(3, age_tag="age_40")
plain = reports.start_report(11, "brain", CFG["styles"][0]["id"], scores,
                             choices=choices)
check("a purchase that names none carries no crossed rounds",
      "timed_out" not in (plain.get("visuals") or {}),
      str(sorted(plain.get("visuals") or {})))
# v7. They reach the purchase now: the checkout body carries them, payments.py
# validates them against the funnel and hands them to this same parameter.
ENGINE = open(os.path.join(REPO, "static/js/engine.js"),
              encoding="utf-8").read()
PAY = open(os.path.join(REPO, "payments.py"), encoding="utf-8").read()
check("  the free page still holds them",
      "timed_out: timedOutSteps.slice()," in ENGINE)
check("  the checkout body carries them from that same state",
      "if (timedOutSteps.length) payload.timed_out = timedOutSteps.slice();"
      in ENGINE)
check("  payments.py checks them against the funnel before believing them",
      "def _clean_timed_out(cfg, raw):" in PAY)
check("  and hands them to this parameter",
      "timed_out=timed_out," in PAY)
given = reports.start_report(12, "brain", CFG["styles"][0]["id"], scores,
                             choices=choices, timed_out=["ink", "count"])
check("handed them, the report stores them",
      (given.get("visuals") or {}).get("timed_out") == ["ink", "count"],
      str((given.get("visuals") or {}).get("timed_out")))
check("  under the key the delivered page already reads",
      "(ctx.visuals && ctx.visuals.timed_out) || []" in MODULE)
messy = reports.start_report(13, "brain", CFG["styles"][0]["id"], scores,
                             choices=choices, timed_out=["ink", "", None, 7])
check("  keeping only what is an id",
      (messy.get("visuals") or {}).get("timed_out") == ["ink"],
      str((messy.get("visuals") or {}).get("timed_out")))
other = reports.start_report(
    14, "persona",
    json.load(open(os.path.join(REPO, "funnels/persona.json"),
                   encoding="utf-8"))["styles"][0]["id"],
    {"drive": 4}, timed_out=["ink"])
check("no other product stores them, handed them or not",
      "timed_out" not in (other.get("visuals") or {}))
check("and the number is still beside them",
      (given.get("visuals") or {}).get("brain", {}).get("age")
      == client_age(4))

print("\n--- v6: the stub the memory game ships is its own ---")
# `_stub_for` prepends the free strength and cuts the list to five, which is
# right for the three products whose chapter is five hidden strengths. This
# one gives no strength away for free and its chapter is five strengths AND
# two habits, so the prepend would inject a promise it never made and the cut
# would drop the two the title sells.
brain_stub = reports._stub_for("mistakes", CFG["styles"][0],
                               stubs=reports.BRAIN_STUBS)
check("the memory game's fallback keeps all seven",
      len(brain_stub["items"]) == 7, str(len(brain_stub["items"])))
check("  five strengths and then two habits, in that order",
      brain_stub["items"][5]["title"] == "You re-read what you already know"
      and brain_stub["items"][6]["title"]
      == "You decide nothing moved too quickly",
      str([r["title"] for r in brain_stub["items"][5:]]))
check("  and none of them is a strength this funnel gave away",
      reports._mistake_one(CFG["styles"][0])["title"]
      not in [row["title"] for row in brain_stub["items"]])
check("kitchen's fallback still opens on the one it promised, five long",
      len(reports._stub_for(
          "mistakes", "Modern Rustic",
          json.load(open(os.path.join(REPO, "funnels/kitchen.json"),
                         encoding="utf-8"))["styles"][0])["items"]) == 5)
check("  and persona's still does too",
      len(reports._stub_for(
          "mistakes",
          json.load(open(os.path.join(REPO, "funnels/persona.json"),
                         encoding="utf-8"))["styles"][0],
          stubs=reports.PERSONA_STUBS)["items"]) == 5)

print("\n--- the neighbours ---")
check("kitchen still resolves to kitchen",
      reports._profile("kitchen") is reports.KITCHEN_PROFILE
      and reports._profile("kitchen-visualizer") is reports.KITCHEN_PROFILE)
check("  zodiac to zodiac, and its two translations to theirs",
      reports._profile("zodiac") is reports.ZODIAC_PROFILE
      and reports._profile("zodiac30") is reports.ZODIAC_PROFILE
      and reports._profile("zodiac-ro") is reports.ZODIAC_RO_PROFILE
      and reports._profile("zodiac-bg") is reports.ZODIAC_BG_PROFILE)
check("  and persona to persona",
      reports._profile("persona") is reports.PERSONA_PROFILE)
for name in ("KITCHEN_PROFILE", "ZODIAC_PROFILE", "PERSONA_PROFILE"):
    other = getattr(reports, name)
    check("  %s shares nothing of this one's" % name,
          other["system"] is not reports.BRAIN_SYSTEM
          and other["spec"] is not reports.BRAIN_SPEC
          and other["stubs"] is not reports.BRAIN_STUBS
          and other.get("banned") is not reports.BRAIN_BANNED)
# `_lst(low, high, fields)`, so the two numbers are the second and third.
# Seven, because /brain's chapter sells five strengths and two habits and all
# seven belong in the section its own title names. A maximum that moves up
# cannot reject an answer that was accepted before it moved.
check("the mistakes ceiling moved up rather than down",
      reports.SHAPE["mistakes"]["items"][1:3] == (4, 7),
      str(reports.SHAPE["mistakes"]["items"][1:3]))
check("  so every answer that parsed before still parses",
      len(reports._stub_for("mistakes", "X")["items"]) <= 7)

print("\n--- v10: the score the free page showed, stored beside the age ---")


def module_body(name):
    """One top-level function's body out of the result module."""
    hit = re.search(r"function %s\([^)]*\)\s*\{(.*?)\n  \}" % name,
                    MODULE, re.S)
    return hit.group(1) if hit else ""


RULE = BLOCK["score"]


def client_score(misses):
    """The module's own arithmetic, restated."""
    raw = RULE["base"] + RULE["per_miss"] * misses
    return max(RULE["floor"], min(RULE["base"], reports._js_round(raw)))


check("the report carries the constants rather than a copy of them",
      "rule = block.get(\"score\")" in open(
          os.path.join(REPO, "reports.py"), encoding="utf-8").read())
for per_round, label, want_room in ((4, "a perfect run", 0),
                                    (0, "an all-miss run", 4),
                                    (2, "half of every round", 4),
                                    (3, "one miss each", 0)):
    choices, scores = run_of(per_round)
    got = reports._brain_numbers(CFG, CFG["styles"][0], scores)
    misses = BLOCK["scored"] - per_round * len(DOMAINS)
    check("  %-18s scores %3d/100" % (label, client_score(misses)),
          got["score"] == client_score(misses), str(got["score"]))
    check("    with room in %d of the four" % want_room,
          got["room_rounds"] == want_room, str(got["room_rounds"]))
    check("    and elite is %s" % (client_score(misses) >= RULE["elite_min"]),
          got["elite"] == (client_score(misses) >= RULE["elite_min"]),
          str(got["elite"]))
choices, scores = run_of(4)
perfect = reports._brain_numbers(CFG, CFG["styles"][0], scores)
check("a perfect run is a hundred, elite, with room in none of the four",
      perfect["score"] == 100 and perfect["elite"] is True
      and perfect["room_rounds"] == 0, str(perfect["score"]))
choices, scores = run_of(0)
bottom = reports._brain_numbers(CFG, CFG["styles"][0], scores)
check("  and an all-miss run stops at the floor rather than below it",
      bottom["score"] == RULE["floor"]
      and RULE["base"] + RULE["per_miss"] * BLOCK["scored"] < RULE["floor"],
      "%s from a raw %s" % (bottom["score"],
                            RULE["base"] + RULE["per_miss"] * BLOCK["scored"]))
check("the three travel on the stored report, next to the age",
      all(key in perfect for key in ("score", "room_rounds", "elite", "age")))
choices, scores = run_of(3, age_tag="age_40")
row = reports.start_report(21, "brain", CFG["styles"][0]["id"], scores,
                           choices=choices)
stored = (row.get("visuals") or {}).get("brain") or {}
check("  and the stored row is the single record of them",
      stored.get("score") == 76 and stored.get("room_rounds") == 0
      and stored.get("elite") is False and stored.get("age") == 38,
      str({k: stored.get(k) for k in ("score", "room_rounds", "elite",
                                      "age")}))
check("    which the module reads rather than working out again",
      'typeof stored.score === "number" ? stored.score : null' in MODULE
      and "scoreOf(" not in module_body("storedProfile"))

print("\n--- v10: the age is the report's to reveal ---")
check("the chapter the report opens on opens on the number",
      "THE NUMBER, AND WHAT THEY RUN ON" in reports._BRAIN_SHAPES["dna"]
      and "first time they meet the age" in reports._BRAIN_SHAPES["dna"])
check("  and is told not to reach for a population that does not exist",
      "no average, no percentile, no share of people"
      in reports._BRAIN_SHAPES["dna"])
check("  while the shape it must return is the one it always was",
      reports.SHAPE["dna"]["narrative"][1:3] == (1, 3))
check("the page's kicker names the first card on it, which is the score",
      "kicker(copy, lean, copy.score_kicker)" in module_body("delivered")
      and MODULE.count("kicker(copy, lean, copy.score_kicker)") == 2)
check("  and the age card carries its own lead, one card down",
      'elm("p", "br-score-lead", lead)' in module_body("score")
      and "var lead = copy.kicker" in module_body("score")
      and CFG["result_copy"]["kicker"] == "Your brain age")
check("the age-delta lines are the delivered page's alone",
      "ageLine(copy, data)" in module_body("score")
      and "ageLine(" not in module_body("scoreCard")
      and "ageLine(" not in module_body("render"))
check("  and they are still the same three, chosen the same way",
      all(("copy." + key) in MODULE for key in
          ("younger_line", "level_line", "older_line", "age_line_bare")))
check("the other profiles are untouched by any of it",
      "score" not in reports.KITCHEN_PROFILE
      and "score" not in reports.ZODIAC_PROFILE
      and "score" not in reports.PERSONA_PROFILE
      and reports._BRAIN_SHAPES["dna"] is not reports.SHAPE["dna"])
check("  and nothing but /brain reaches the score at all",
      reports._brain_numbers({"brain_age": {"scored": 16}},
                             CFG["styles"][0], {"mem_hit": 4}) is not None
      and "score" not in reports._brain_numbers(
          {"brain_age": {"scored": 16}}, CFG["styles"][0], {"mem_hit": 4}))

print("\n--- v12: every promise the offer makes, and what delivers it ---")
#
# The offer card names five things. A promise on a sales card that no chapter
# of the document keeps is the one kind of copy this funnel cannot afford, so
# each of the five is tied here to the section that answers it — in the prompt
# the model is given AND in the stub that ships when there is no key, because
# the reader who gets the stub paid the same money.
SHAPES = reports._BRAIN_SHAPES
STUBS = reports.BRAIN_STUBS
OFFER = CFG["result_copy"]["profile"]
CARDS = {row["title"]: row for row in OFFER["offer_cards"]}

print("  (a) the brain age, revealed on the first page")
check("    the offer sells the reveal as the first thing in the report",
      OFFER["offer_hero_kicker"] == "Your brain age"
      and "first page" in OFFER["offer_hero_line"],
      OFFER["offer_hero_line"])
check("    the chapter the report opens on opens on the number",
      "THE NUMBER, AND WHAT THEY RUN ON" in SHAPES["dna"]
      and "first time they meet the age" in SHAPES["dna"])
check("    and so does the one written when there is no key",
      "your brain age" in STUBS["dna"]["narrative"][0].lower()
      and STUBS["dna"]["narrative"][0].lower().index("brain age") < 80,
      STUBS["dna"]["narrative"][0][:60])
check("    with no figure invented in a stub every reader shares",
      not re.search(r"\d", STUBS["dna"]["narrative"][0]),
      STUBS["dna"]["narrative"][0][:80])
check("    and the page puts the age above the chapters, not inside one",
      "root.appendChild(score(ctx, copy, data, lean));"
      in module_body("delivered")
      and module_body("delivered").index("score(ctx, copy, data, lean)")
      < module_body("delivered").index("firstly(ctx.sections"))

print("  (b) the weakest round's drill: two minutes a day, from tomorrow")
check("    the offer says a day, and says it starts tomorrow",
      CARDS["Weakest-round drill"]["sub"]
      == "2 minutes a day, starts tomorrow")
check("    the chapter is asked for the round with the most room",
      "THE ROUND WITH THE MOST ROOM" in SHAPES["materials"]
      and "scored lowest" in SHAPES["materials"])
check("    and for a drill that is two minutes, every day, from tomorrow",
      "two-minute drill" in SHAPES["materials"]
      and "two minutes every day" in SHAPES["materials"]
      and "starts tomorrow" in SHAPES["materials"],
      SHAPES["materials"][SHAPES["materials"].index("THE DRILL"):][:180])
check("    the stub delivers the same thing without a key",
      "Two minutes, every morning" in STUBS["materials"]["rule"],
      STUBS["materials"]["rule"][-80:])

print("  (c) seven days, one small thing on each")
check("    the offer says one small thing a day",
      CARDS["7-day plan"]["sub"] == "One small thing each day — the score "
      "climbs")
check("    the chapter is asked for seven days and an eighth that replays",
      SHAPES["shopping"].count('"Day') >= 8
      and '"Day 8 - Play again"' in SHAPES["shopping"]
      and "DAY EIGHT IS THE POINT OF THE OTHER SEVEN" in SHAPES["shopping"])
check("    each day small enough to do",
      "Under five minutes, start to finish" in SHAPES["shopping"])
check("    and the stub ships eight days, the last of them the replay",
      len(STUBS["shopping"]["items"]) == 8
      and STUBS["shopping"]["items"][-1]["name"] == "Day 8 - Play again",
      str([i["name"] for i in STUBS["shopping"]["items"]]))

print("  (d) five strengths and two habits")
check("    the offer counts them",
      "5 strengths · 2 habits" in CARDS
      and CARDS["5 strengths · 2 habits"]["sub"]
      == "What to lean on, what to swap")
check("    the chapter is asked for five and then two, in that order",
      "SEVEN items under the single key `items`" in SHAPES["mistakes"]
      and "five strengths, then" in SHAPES["mistakes"]
      and "two habits." in SHAPES["mistakes"]
      and "the first HABIT holding them back" in SHAPES["mistakes"])
check("    and the stub ships seven, the last two of them habits",
      len(STUBS["mistakes"]["items"]) == 7
      and all("habit" in i["title"].lower() or "fix" in i
              for i in STUBS["mistakes"]["items"][5:]),
      str([i["title"] for i in STUBS["mistakes"]["items"]]))
check("    which the schema allows through",
      reports.SHAPE["mistakes"]["items"][1] <= 7
      <= reports.SHAPE["mistakes"]["items"][2],
      str(reports.SHAPE["mistakes"]["items"][1:3]))

print("  (e) fuel: a plate, on one of the days")
check("    the offer sells a plate",
      CARDS["Fuel"]["sub"] == "The plate that feeds a sharp brain")
check("    one of the seven days is asked to be food on a plate",
      "ONE OF THE REMAINING DAYS IS FUEL" in SHAPES["shopping"]
      and "a day about food" in SHAPES["shopping"]
      and "on a plate" in SHAPES["shopping"])
check("    and it is food, never a supplement",
      "Nothing out of a bottle and nothing measured" in SHAPES["shopping"])
check("    the stub gives that day a name and a plate",
      [i for i in STUBS["shopping"]["items"] if i["name"].endswith("Fuel")]
      and "plate" in [i for i in STUBS["shopping"]["items"]
                      if i["name"].endswith("Fuel")][0]["priority_note"],
      str([i["name"] for i in STUBS["shopping"]["items"]]))

check("no other profile was touched by any of it",
      reports.KITCHEN_PROFILE["stubs"] is not STUBS
      and reports.ZODIAC_PROFILE["stubs"] is not STUBS
      and reports.PERSONA_PROFILE["stubs"] is not STUBS
      and reports._BRAIN_SHAPES is not reports.SHAPE)
check("  and the four prompts are this profile's alone",
      all(SHAPES[key] not in json.dumps(
          {k: str(v) for k, v in reports.KITCHEN_PROFILE.items()})
          for key in SHAPES))

print("\n%d checks, %d failed" % (checks[0], len(fails)))
for line in fails:
    print("  FAIL " + line)
sys.exit(1 if fails else 0)
