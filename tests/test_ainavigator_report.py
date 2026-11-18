#!/usr/bin/env python3
"""The AI Navigator's paid report: what a purchase stores and what it buys.

/ai-navigator is the third product on the platform that MEASURES, and the
first where two of the things the document says are not the model's to say.

The numbers. The free page worked out a score, a level, a calibration word
and the zone with the most room, in the browser, before any money changed
hands. The report arrives at the same figures on the server from the
validated choices — never from what the browser computed — so the check
below is result_ai.js's own rules, restated here and walked over every
combination of hits a run can have and every prediction it can carry.

The paths. Which three ways of working with AI fit a reader, and which two
to skip for now, comes out of a table in the config: the skill they named
picks them, the goal and the hours adjust them, the level picks the offer
format. Every combination of answers is walked and held to the invariants.

The answer key. Twelve rows, from the config and the choices.

And the line. This product talks about earning, so the drift is towards a
promise. A model's sentence that guarantees anything, or puts a figure on a
month, is refused and redrawn; the stubs, the path table and the answer key
are held to the same scan, because those ship with nothing checking them.

    python3 tests/test_ainavigator_report.py
"""
import itertools
import json
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

SLUG = "ai-navigator"


def load(name):
    with open(os.path.join(REPO, "funnels", name + ".json"),
              encoding="utf-8") as fh:
        return json.load(fh)


def read(rel):
    with open(os.path.join(REPO, rel), encoding="utf-8") as fh:
        return fh.read()


CFG = load(SLUG)
MODULE = read("static/js/result_ai.js")
STEPS = CFG["swipe"]["steps"]
BLOCK = CFG["brain_age"]
PATHS = CFG["paths"]
RULES = PATHS["rules"]
CATALOG = dict((row["id"], row) for row in PATHS["catalog"])
DOMAINS = ("mem", "foc", "chg", "spa")
STYLES = dict((s["id"], s) for s in CFG["styles"])
STYLE = STYLES["mechanic"]
SECTIONS = ("dna", "materials", "mistakes", "shopping")
profile = reports._profile(SLUG)

fails = []
checks = [0]


def check(label, ok, detail=""):
    checks[0] += 1
    if not ok:
        fails.append("%s %s" % (label, detail))
    print("  %-62s %s%s" % (label, "ok" if ok else "FAIL",
                            ("  " + str(detail)[:400]) if detail and not ok
                            else ""))


def run_of(hits, skill="skill_design", time="time_3_7", goal="goal_side",
           predict="predict_7_9", tool="tool_chat", exp="exp_weekly"):
    """(choices, tag_scores) for a walk that hits `hits[zone]` of each zone.

    Built by walking the config the way a reader does, one card a step, so
    what goes in is what a real purchase would carry. A warm-up passed as
    None is a step nobody answered.
    """
    want = dict((key, hits) for key in DOMAINS) if isinstance(hits, int) \
        else dict(hits)
    warm = {"skill": skill, "time": time, "goal": goal, "predict": predict,
            "tool": tool, "exp": exp}
    got = dict((key, 0) for key in DOMAINS)
    choices, scores = [], {}
    for step in STEPS:
        cards = step["pairs"][0]["images"]
        zone = cards[0]["tags"][0].split("_")[0]
        if zone in got:
            want_hit = got[zone] < want[zone]
            got[zone] += 1 if want_hit else 0
            pick = next(c for c in cards
                        if c["tags"][0].endswith("_hit") == want_hit)
        else:
            tag = warm[step["id"]]
            if tag is None:
                continue
            pick = next(c for c in cards if tag in c["tags"])
        choices.append(pick["id"])
        for tag in pick["tags"]:
            scores[tag] = scores.get(tag, 0) + 1
    return choices, scores


print("\n--- the profile ---")
check("ai-navigator has a profile of its own, and it is registered",
      reports.PROFILES.get(SLUG) is reports.AI_PROFILE
      and profile is reports.AI_PROFILE)
check("  which its sandbox twin would read too",
      reports._profile(SLUG + "-test") is reports.AI_PROFILE)
check("  and it is none of the others'",
      all(profile is not other for name, other in reports.PROFILES.items()
          if name != SLUG))
check("its own voice: an advisor, second person, every section an action",
      profile["system"] is reports.AI_SYSTEM
      and "direct, practical advisor" in reports.AI_SYSTEM
      and "Second person" in reports.AI_SYSTEM
      and "Every section ends on an action" in reports.AI_SYSTEM)
check("the four shared ids, and the config titles them as sold",
      sorted(profile["spec"]) == sorted(SECTIONS)
      and [(s["id"], s["title"]) for s in CFG["report"]["sections"]]
      == [("dna", "Your AI Profile & Your Edge"),
          ("materials", "Your 3 Best-Fit Paths"),
          ("mistakes", "5 Strengths to Sell & 2 Traps to Avoid"),
          ("shopping", "Your First 7 Days")])
check("one cached per type, three written per purchase",
      profile["cached"] == ("mistakes",)
      and profile["personal"] == ("dna", "materials", "shopping")
      and reports.cached_sections(SLUG) == ("mistakes",)
      and reports.personal_sections(SLUG) == ("dna", "materials", "shopping"))
check("  a partition of the four",
      sorted(profile["cached"] + profile["personal"]) == sorted(SECTIONS))
check("the furniture is as specified",
      profile["pdf_lead"] == "Your AI Navigator Report"
      and profile["delivery_note"] is True
      and profile["retry_detail"] is True and profile["verify"] is None
      and isinstance(profile["pdf_note"], str) and profile["pdf_note"]
      and profile["words"] is reports.AI_WORDS
      and profile["mail"] is reports.COPY_AI)
check("the shapes ask for three paths that fit and two to skip",
      profile["spec"]["materials"].count('"combo"') == 5
      and "Invent no path" in profile["spec"]["materials"])
check("  seven items of strengths and traps, seven days",
      "SEVEN items" in profile["spec"]["mistakes"]
      and "SEVEN items" in profile["spec"]["shopping"]
      and '"Day 7 - Ask one person"' in profile["spec"]["shopping"])
check("the funnel still transacts on the test keys",
      CFG.get("stripe_mode") == "test")

print("\n--- the stubs ---")
for section_id in SECTIONS:
    stub = reports._stub_for(section_id, STYLE["name"], STYLE,
                             stubs=reports.AI_STUBS)
    check("the %s stub is in the shape its validator takes" % section_id,
          reports.VALIDATORS[section_id](stub) is not None)
stub = reports._stub_for("mistakes", STYLE["name"], STYLE,
                         stubs=reports.AI_STUBS)
check("the strengths stub is seven: five strengths, then two traps",
      len(stub["items"]) == 7)
check("  opening on the strength the free page gave away, for each type",
      all(reports._stub_for("mistakes", s["name"], s,
                            stubs=reports.AI_STUBS)["items"][0]
          == reports._mistake_one(s) for s in STYLES.values()))
check("  with the two traps still at the end",
      [i["title"] for i in stub["items"][5:]]
      == [i["title"] for i in reports.AI_STUBS["mistakes"]["items"][5:]])
check("the paths stub is three that fit and two to skip",
      [p["verdict"] for p in reports.AI_STUBS["materials"]["pairs"]]
      == ["works"] * 3 + ["avoid"] * 2)
check("the week stub is seven days and ends on the asking",
      len(reports.AI_STUBS["shopping"]["items"]) == 7
      and reports.AI_STUBS["shopping"]["items"][6]["name"]
      == "Day 7 - Ask one person"
      and reports.AI_STUBS["shopping"]["skip"] == [])
check("the other two games' stubs are the ones they were",
      reports.GAME_MISTAKE_STUBS[:2]
      == (reports.BRAIN_STUBS["mistakes"], reports.FOCUS_STUBS["mistakes"])
      and len(reports._stub_for(
          "mistakes", "x", None, stubs=reports.FOCUS_STUBS)["items"]) == 7)

print("\n--- the numbers: the server and the page agree ---")
# result_ai.js, restated. Counts are hits out of three; the zone with the
# most room is the lowest, the earliest on a tie, and NONE when all four are
# level; the strongest is the highest, the earliest on a tie, which is how
# engine.js picks the type. The level is the first whose ceiling the score
# is under. Inside the predicted band is on target, above it underrated,
# below it bold, and no prediction is no word at all.
check("the module's own rules are the ones restated here",
      'var DOMAINS = ["mem", "foc", "chg", "spa"];' in MODULE
      and "if (low === null || counts[key] < counts[low]) low = key;"
      in MODULE
      and 'room: level ? "" : low,' in MODULE
      and 'if (hits > band.max) return "under";' in MODULE
      and 'if (hits < band.min) return "over";' in MODULE
      and "hits <= rows[i].max" in MODULE)


def client(counts, predict):
    hits = sum(counts[k] for k in DOMAINS)
    low = None
    level = True
    for key in DOMAINS:
        if counts[key] != counts[DOMAINS[0]]:
            level = False
        if low is None or counts[key] < counts[low]:
            low = key
    top = None
    for key in DOMAINS:
        if top is None or counts[key] > counts[top]:
            top = key
    name = ""
    for row in BLOCK["levels"]:
        if not isinstance(row.get("max"), int) or hits <= row["max"]:
            name = row["label"]
            break
    band = BLOCK["predict"]["bands"].get(predict) if predict else None
    if not band:
        word = "none"
    elif hits > band["max"]:
        word = "underrated"
    elif hits < band["min"]:
        word = "bold"
    else:
        word = "on_target"
    return {"hits": hits, "weakest": None if level else low,
            "strongest": top, "level": name, "calibration": word}


BANDS = list(BLOCK["predict"]["bands"]) + [None]
wrong = []
walked = 0
for combo in itertools.product(range(4), repeat=4):
    counts = dict(zip(DOMAINS, combo))
    for predict in BANDS:
        choices, scores = run_of(counts, predict=predict)
        got = reports._ai_numbers(CFG, STYLE, scores, choices)
        want = client(counts, predict)
        walked += 1
        if got["counts"] != counts or any(got[k] != want[k] for k in want) \
                or got["predict"] != predict or got["scored"] != 12:
            wrong.append((combo, predict, got, want))
check("every hits-per-zone combination, on every prediction (%d runs)"
      % walked, walked == 256 * 5 and not wrong, str(wrong[:1]))
choices, scores = run_of({"mem": 3, "foc": 2, "chg": 1, "spa": 0})
numbers = reports._ai_numbers(CFG, STYLE, scores, choices)
check("the three levels sit where the page draws them",
      [reports._ai_numbers(CFG, STYLE, *reversed(run_of(n)))["level"]
       for n in (0, 1, 2, 3)]
      == ["Explorer", "Explorer", "Builder", "Operator"]
      and [row.get("max") for row in BLOCK["levels"]][:2] == [4, 8])
check("an even run has no zone with the most room",
      all(reports._ai_numbers(CFG, STYLE, *reversed(run_of(n)))["weakest"]
          is None for n in range(4)))
check("it is counted off the choices, not off what the browser added up",
      reports._ai_numbers(CFG, STYLE, {"mem_hit": 3, "foc_hit": 3,
                                       "chg_hit": 3, "spa_hit": 3},
                          choices)["hits"] == 6
      and reports._ai_numbers(CFG, STYLE, None, choices)["hits"] == 6)
check("  a tally is only the fallback, clamped to what a zone can hold",
      reports._ai_numbers(CFG, STYLE, {"mem_hit": 9, "foc_hit": 1},
                          None)["counts"]
      == {"mem": 3, "foc": 1, "chg": 0, "spa": 0})
check("  and a run with neither stores nothing",
      reports._ai_numbers(CFG, STYLE, None, None) is None
      and reports._ai_numbers({}, STYLE, scores, choices) is None)
check("the warm-ups travel as the tag and the words on the card",
      numbers["skill"] == "skill_design" and numbers["time"] == "time_3_7"
      and numbers["goal"] == "goal_side"
      and numbers["said"]["skill"] == "Design & visuals"
      and numbers["said"]["time"] == "3–7")
bare, bare_scores = run_of(1, skill=None, time=None, goal=None, predict=None)
check("  and one nobody answered is None, never a guess",
      [reports._ai_numbers(CFG, STYLE, bare_scores, bare)[k]
       for k in ("skill", "time", "goal", "predict", "band")] == [None] * 5)

print("\n--- the paths: the catalog ---")
FACTS = ("sells", "buyer", "first_client", "startup", "risk")
check("eleven paths, P1 to P11, each named",
      [row["id"] for row in PATHS["catalog"]]
      == ["P%d" % n for n in range(1, 12)]
      and len({row["name"] for row in PATHS["catalog"]}) == 11)
check("  each with exactly the five facts, one sentence each",
      all(list(row) == ["id", "name"] + list(FACTS)
          and all(isinstance(row[f], str) and 30 <= len(row[f]) <= 180
                  and row[f].rstrip().endswith(".")
                  and not re.search(r"[.!?]\s+[A-Z]", row[f])
                  for f in FACTS) for row in PATHS["catalog"]))
check("  a first client is a range in weeks",
      all(re.search(r"\b\d+–\d+ weeks\b", row["first_client"])
          for row in PATHS["catalog"]))
check("  what it takes to start is a free tier or a paid plan",
      all(re.search(r"free tier|paid plan", row["startup"])
          and not re.search(r"[$€£]|\d", row["startup"])
          for row in PATHS["catalog"]))
check("  the risk is how it most often fails",
      all(row["risk"].startswith("It most often fails")
          for row in PATHS["catalog"]))
check("  and no fact puts a figure on what anybody earns",
      not [row["id"] for row in PATHS["catalog"]
           if re.search(r"[$€£]|\bearn|\bincome\b|\bprofit",
                        " ".join(row[f] for f in FACTS), re.I)])
check("the rules are the table that was specified",
      RULES["by_skill"] == {
          "writing": ["P1", "P2", "P10"], "design": ["P3", "P4", "P1"],
          "tech": ["P5", "P6", "P8"], "sales": ["P7", "P8", "P10"],
          "organizing": ["P9", "P5", "P8"], "teaching": ["P10", "P2", "P8"]}
      and RULES["skip_by_skill"] == {
          "writing": ["P6", "P5"], "design": ["P6", "P7"],
          "tech": ["P2", "P3"], "sales": ["P6", "P4"],
          "organizing": ["P6", "P2"], "teaching": ["P6", "P7"]}
      and RULES["goal_levelup"] == {"when": "goal_levelup", "primary": "P11"}
      and RULES["time_under_3"] == {
          "when": "time_under3", "not_in_works": "P2",
          "replace_with": ["P8", "P10", "P1", "P9", "P5"]}
      and RULES["format_by_level"] == {
          "explorer": "one small done-for-you service, one niche",
          "builder": "a productized service with fixed scope",
          "operator": "a system or product: retainer, tool or library"}
      and RULES["default_skill_by_type"] == {
          "mechanic": "tech", "director": "writing",
          "editor": "organizing", "dealmaker": "sales"})
SKILLS = [c["tags"][0] for c in next(s for s in STEPS if s["id"] == "skill")
          ["pairs"][0]["images"]]
TIMES = [c["tags"][0] for c in next(s for s in STEPS if s["id"] == "time")
         ["pairs"][0]["images"]]
GOALS = [c["tags"][0] for c in next(s for s in STEPS if s["id"] == "goal")
         ["pairs"][0]["images"]]
check("  keyed on the skills, hours and goals the quiz really asks",
      sorted("skill_" + k for k in RULES["by_skill"]) == sorted(SKILLS)
      and sorted(RULES["skip_by_skill"]) == sorted(RULES["by_skill"])
      and RULES["time_under_3"]["when"] in TIMES
      and RULES["goal_levelup"]["when"] in GOALS
      and len(TIMES) == 4 and len(GOALS) == 4
      and sorted(RULES["default_skill_by_type"]) == sorted(STYLES))

print("\n--- the paths: every reader ---")
LEVELS = {"explorer": 1, "builder": 2, "operator": 3}      # hits per zone
bad = []
seen = 0
for skill, (level, per), time, goal in itertools.product(
        SKILLS + [None], LEVELS.items(), TIMES, GOALS):
    for style in STYLES.values() if skill is None else (STYLE,):
        choices, scores = run_of(per, skill=skill, time=time, goal=goal)
        numbers = reports._ai_numbers(CFG, style, scores, choices)
        got = reports._ai_paths(CFG, choices, numbers)
        seen += 1
        if not got:
            bad.append(("none", skill, level, time, goal))
            continue
        works = [c["id"] for c in got["works"]]
        avoid = [c["id"] for c in got["avoid"]]
        key = (skill or "skill_" + RULES["default_skill_by_type"][
            style["id"]])[len("skill_"):]
        problems = []
        if len(works) != 3 or len(set(works)) != 3:
            problems.append("works")
        if len(avoid) != 2 or len(set(avoid)) != 2:
            problems.append("avoid")
        if set(works) & set(avoid):
            problems.append("overlap")
        if any(pid not in CATALOG for pid in works + avoid):
            problems.append("catalog")
        if any(not card.get(f) or card[f] != CATALOG[card["id"]][f]
               for card in got["works"] + got["avoid"]
               for f in ("name",) + FACTS):
            problems.append("facts")
        if got["primary"] != works[0] or got["skill"] != key:
            problems.append("primary")
        if got["format"] != RULES["format_by_level"][level]:
            problems.append("format")
        base = RULES["by_skill"][key]
        if goal == "goal_levelup":
            if works[0] != "P11":
                problems.append("levelup")
            if time != "time_under3" and works != ["P11"] + base[:2]:
                problems.append("levelup-shift")
        elif time != "time_under3" and works != base:
            problems.append("base")
        if time == "time_under3" and "P2" in works:
            problems.append("under3")
        if time != "time_under3" and avoid != RULES["skip_by_skill"][key]:
            problems.append("skip")
        if problems:
            bad.append((problems, skill, level, time, goal, works, avoid))
check("six skills and none, three levels, four hours, four goals (%d)" % seen,
      seen == 6 * 3 * 4 * 4 + 4 * 3 * 4 * 4 and not bad, str(bad[:2]))


def paths_for(**kw):
    choices, scores = run_of(2, **kw)
    return reports._ai_paths(
        CFG, choices, reports._ai_numbers(CFG, STYLE, scores, choices))


def ids(got):
    return ([c["id"] for c in got["works"]], [c["id"] for c in got["avoid"]])


check("a writer with the hours gets the table's own three and two",
      ids(paths_for(skill="skill_writing")) == (["P1", "P2", "P10"],
                                                ["P6", "P5"]))
check("levelling up puts P11 first and drops the old third",
      ids(paths_for(skill="skill_writing", goal="goal_levelup"))
      == (["P11", "P1", "P2"], ["P6", "P5"]))
check("under three hours, the newsletter leaves the three and is skipped",
      ids(paths_for(skill="skill_writing", time="time_under3"))
      == (["P1", "P8", "P10"], ["P6", "P2"]))
check("  with the first replacement not already there",
      ids(paths_for(skill="skill_teaching", time="time_under3"))
      == (["P10", "P1", "P8"], ["P6", "P2"]))
check("  both rules together",
      ids(paths_for(skill="skill_teaching", time="time_under3",
                    goal="goal_levelup")) == (["P11", "P10", "P8"],
                                              ["P6", "P2"]))
check("  and it is left alone where the newsletter was already skipped",
      ids(paths_for(skill="skill_tech", time="time_under3"))
      == (["P5", "P6", "P8"], ["P2", "P3"]))
check("no skill named: the type's own default",
      ids(paths_for(skill=None)) == (RULES["by_skill"]["tech"],
                                     RULES["skip_by_skill"]["tech"]))
check("no table, or no numbers, is no paths rather than a guess",
      reports._ai_paths({}, [], numbers) is None
      and reports._ai_paths(CFG, [], None) is None)

print("\n--- the answer key ---")
KEY = CFG["answer_key"]
SCORED = [s for s in STEPS if s["pairs"][0]["images"][0]["tags"][0]
          .split("_")[0] in DOMAINS]
check("one line of why for each scored step, and for nothing else",
      list(KEY) == [s["id"] for s in SCORED] and len(KEY) == 12)
check("  each a plain sentence or two, 160 characters at most",
      all(isinstance(v, str) and 40 <= len(v) <= 160 and v.endswith(".")
          for v in KEY.values()),
      str({k: len(v) for k, v in KEY.items() if len(v) > 160}))
choices, scores = run_of({"mem": 3, "foc": 2, "chg": 1, "spa": 0})
rows = reports._ai_answer_key(CFG, choices)
check("twelve rows, in the order the questions were asked",
      [r["id"] for r in rows] == [s["id"] for s in SCORED])
check("  each with the question, theirs, the right one, hit or miss, why",
      all(list(r) == ["id", "zone", "question", "yours", "right", "hit",
                      "why"] for r in rows))
check("  the right answer is the card tagged a hit",
      all(r["right"] == next(c["label"] for c in s["pairs"][0]["images"]
                             if c["tags"] == [r["zone"] + "_hit"])
          for r, s in zip(rows, SCORED)))
check("  theirs is the card they tapped, and the mark is whether it was",
      all(r["yours"] == next(c["label"] for c in s["pairs"][0]["images"]
                             if c["id"] in choices)
          and r["hit"] == (r["yours"] == r["right"])
          for r, s in zip(rows, SCORED))
      and [r["hit"] for r in rows].count(True) == 6)
check("  why is the config's line, never anything else",
      all(r["why"] == KEY[r["id"]] and r["question"] == s["question"]
          for r, s in zip(rows, SCORED)))
check("a question nobody answered is a miss with no answer of theirs",
      [(r["yours"], r["hit"]) for r in reports._ai_answer_key(CFG, [])]
      == [("", False)] * 12)
check("the free page still has no way to reach a right answer",
      "answer_key" not in MODULE.split("function render(root, ctx) {", 1)[1]
      .split("function storedProfile", 1)[0]
      and "ctx.visuals.answer_key" in MODULE
      and "ctx.cfg.answer_key" not in MODULE and "cfg.answer_key" not in MODULE)

print("\n--- what a purchase stores ---")
content = reports.start_report(21, SLUG, "mechanic", scores, choices=choices)
visuals = content.get("visuals") or {}
brain = visuals.get("brain") or {}
check("with no key the report is whole, and says it is stubs",
      content["version"] == "stub-" + reports.SCHEMA
      and [s["id"] for s in content["sections"]] == list(SECTIONS))
check("the numbers, under the key the delivered page reads",
      brain.get("hits") == 6 and brain.get("scored") == 12
      and brain.get("counts") == {"mem": 3, "foc": 2, "chg": 1, "spa": 0}
      and brain.get("level") == "Builder"
      and brain.get("calibration") == "bold"
      and brain.get("weakest") == "spa" and brain.get("strongest") == "mem"
      and brain.get("predict") == "predict_7_9"
      and "stored.hits" in MODULE and "stored.counts" in MODULE
      and "stored.predict" in MODULE)
check("  with the reader's skill, time and goal tags beside them",
      (brain.get("skill"), brain.get("time"), brain.get("goal"))
      == ("skill_design", "time_3_7", "goal_side"))
check("the paths, three and two with their facts",
      [c["id"] for c in visuals["paths"]["works"]] == ["P3", "P4", "P1"]
      and [c["id"] for c in visuals["paths"]["avoid"]] == ["P6", "P7"]
      and visuals["paths"]["format"]
      == "a productized service with fixed scope")
check("the answer key, twelve rows",
      visuals.get("answer_key") == rows)
stored = dict((s["id"], s["data"]) for s in content["sections"])
check("the paths chapter names the reader's own five, in order",
      [(p["combo"], p["verdict"]) for p in stored["materials"]["pairs"]]
      == [(CATALOG[pid]["name"], verdict) for pid, verdict in
          (("P3", "works"), ("P4", "works"), ("P1", "works"),
           ("P6", "avoid"), ("P7", "avoid"))])
check("  and is still a section its validator takes",
      all(reports.VALIDATORS[k](stored[k]) is not None for k in SECTIONS))
check("the shipped stub itself is not written on",
      reports.AI_STUBS["materials"]["pairs"][0]["combo"]
      == "Your primary path")
model = {"intro": "x" * 40, "rule": "y" * 40, "pairs": [
    {"combo": "Something else", "verdict": "avoid", "why": "w" * 30}] * 5}
fixed = reports._ai_personal_fix("materials", model, visuals)
check("a written chapter keeps its lines and takes the stored names",
      [(p["combo"], p["verdict"]) for p in fixed["pairs"]]
      == [(p["combo"], p["verdict"]) for p in stored["materials"]["pairs"]]
      and all(p["why"] == "w" * 30 for p in fixed["pairs"])
      and fixed["intro"] == model["intro"])
check("  and nothing else is touched by it",
      reports._ai_personal_fix("dna", stored["dna"], visuals)
      is stored["dna"]
      and reports._section_fix("focus", stored, visuals) is stored
      and reports._section_fix("kitchen", stored, None) is stored)

print("\n--- the prompts ---")
prompts = dict(
    (section_id, reports._section_prompt(
        STYLE, STYLE["name"], scores, section_id, cfg=CFG, choices=choices,
        funnel_slug=SLUG)) for section_id in profile["personal"])
check("every personal prompt carries the zones, by name, x of 3",
      all("- How AI works: 3 of 3" in p and "- Business sense: 0 of 3" in p
          and "The zone with the most room is Business sense." in p
          for p in prompts.values()))
check("  the score, the level and the calibration word",
      all("They scored 6 out of 12, which this funnel calls Builder." in p
          and "They predicted 7–9" in p and "bold" in p
          for p in prompts.values()))
check("  and their own words for skill, hours, goal, tool and experience",
      all("- What they are best at: Design & visuals" in p
          and "- Hours a week they can put in: 3–7" in p
          and "- What they are after: A side project" in p
          and "- The kind of AI tool they use most: Chat assistants" in p
          and "- How often they use AI today: Weekly" in p
          for p in prompts.values()))
check("the paths prompt lists the five, with verdicts, as REQUIRED",
      "REQUIRED — these are this reader's five paths" in
      prompts["materials"]
      and [m for m in re.findall(r"^- (.+) — (works|avoid)$",
                                 prompts["materials"], re.M)]
      == [(CATALOG[pid]["name"], verdict) for pid, verdict in
          (("P3", "works"), ("P4", "works"), ("P1", "works"),
           ("P6", "avoid"), ("P7", "avoid"))])
check("  with the offer format for their level",
      "The offer format for this reader's level is: a productized service "
      "with fixed scope." in prompts["materials"])
check("the week is on the primary path, and day one on the zone with room",
      "the seven days are on this reader's primary path, Brand & social "
      "design service." in prompts["shopping"]
      and "Day one is a fifteen-minute action on Business sense" in
      prompts["shopping"]
      and "They said they have 3–7 hours a week" in prompts["shopping"]
      and "Day seven ends with one real person asked one real question"
      in prompts["shopping"])
even_choices, even_scores = run_of(2)
even = reports._section_prompt(STYLE, STYLE["name"], even_scores, "shopping",
                               cfg=CFG, choices=even_choices,
                               funnel_slug=SLUG)
check("  on an even run, day one is the path's first step instead",
      "This was an even run" in even
      and "day one is a fifteen-minute action on the first step of that "
      "path" in even and "The zone with the most room is " not in even)
check("the kitchen blocks are not in it",
      not any("The %d choices they made" % 18 in p or "Leaning" in p
              or "style elements" in p for p in prompts.values()))
cached = reports._cached_prompt(STYLE, STYLE["name"], funnel_slug=SLUG)
check("the cached chapter opens on the strength already given away",
      "Strength #1 of 5" in cached
      and reports._mistake_one(STYLE)["title"] in cached
      and "They scored" not in cached and "five paths" not in cached)
every_prompt = "\n".join(prompts.values()) + cached
check("no prompt this profile builds carries a banned phrase",
      reports._banned_hit(every_prompt.replace(reports.AI_SYSTEM, ""),
                          reports.AI_BANNED) is None,
      str(reports._banned_hit(every_prompt, reports.AI_BANNED)))

print("\n--- the line this product must not cross ---")
system = reports.AI_SYSTEM
for phrase in ("never promises an outcome", "No currency figure for earnings",
               '"free tier" or "paid plan"', "No invented statistics",
               '"most people"', '"the zone with the most room"',
               "never by brand or product name",
               "named once, in the first paragraph"):
    check("the system prompt says: %s" % phrase, phrase in system)
REFUSED = ("You will make $2,000 a month from this.",
           "That is 500 dollars a week.", "€3k per month is realistic.",
           "Results are guaranteed.", "We guarantee a client.",
           "It becomes passive income.", "Then quit your job.",
           "This is how you get rich.", "A good side hustle.",
           "A side-hustle for evenings.", "Expect $500 from the first one.",
           "The tool costs $20 and the rest is yours.")
for text in REFUSED:
    check("  refused: %r" % text,
          reports._banned_hit(text, reports.AI_BANNED) is not None)
ALLOWED = ("Start on the free tier; the paid plan is $20 if you outgrow it.",
           "A paid plan, about $20, is enough.",
           "You can earn from this by selling one clear service.",
           "A first client typically takes 2–6 weeks.",
           "Charge per project rather than per hour.",
           "Secret prompts are not what a client pays for.")
for text in ALLOWED:
    check("  allowed: %r" % text[:48],
          reports._banned_hit(text, reports.AI_BANNED) is None,
          str(reports._banned_hit(text, reports.AI_BANNED)))
check("the core of the list is the funnel's own, plus two for a model",
      len(reports.AI_BANNED_CORE) == 5
      and reports.AI_BANNED[:5] == reports.AI_BANNED_CORE
      and len(reports.AI_BANNED) == 7)
every_stub = [reports._stub_for(section_id, s["name"], s,
                                stubs=reports.AI_STUBS)
              for section_id in SECTIONS for s in STYLES.values()]
check("no stub it ships carries a banned phrase",
      reports._banned_hit(every_stub, reports.AI_BANNED) is None,
      str(reports._banned_hit(every_stub, reports.AI_BANNED)))
check("  nor the catalog, nor the answer key, nor the stored report",
      reports._banned_hit(PATHS, reports.AI_BANNED) is None
      and reports._banned_hit(KEY, reports.AI_BANNED) is None
      and reports._banned_hit(content["sections"], reports.AI_BANNED) is None
      and reports._banned_hit(visuals["paths"], reports.AI_BANNED) is None)
check("  nor the mail",
      reports._banned_hit(
          [v for k, v in reports.COPY_AI.items()
           if k not in ("keep", "keep_no_link")], reports.AI_BANNED) is None)
soft = json.dumps([every_stub, PATHS, KEY]).lower()
check("nothing it ships calls the lowest zone a weakness, or cites anybody",
      not re.search(r"\bweak|\bpoor\b|deficien|most people|\d+\s?% of|"
                    r"studies show|research shows", soft))
BRANDS = ("chatgpt", "openai", "claude", "gemini", "midjourney", "canva",
          "zapier", "notion", "copilot", "etsy", "gumroad", "substack")
check("  and names no tool by brand",
      not [b for b in BRANDS if b in soft])

print("\n--- a dirty answer is redrawn, then stubbed ---")
P1 = ("Your score and how it sat against your own prediction are a reading "
      "of twelve answers and of nothing else, and the zone you scored "
      "highest in is the one you can already work from this week.")
P2 = ("Knowing how the tools work makes your prompts better, and good "
      "prompts give you output that is worth the time it takes to check "
      "before anybody else sees it.")
P3 = ("Point your strongest zone at the zone with the most room, in short "
      "sessions on one real task, which is how the first seven days of "
      "this plan are built for you.")


def answer(extra=""):
    return json.dumps({"dna": {
        "narrative": [P1 + extra, P2, P3],
        "implications": ["Do one real task with a chat assistant today.",
                         "Write the kind of work you want in one line.",
                         "Explain one right answer to somebody else."]}})


def replay(text):
    seen = []

    def attempt(client, prompt, max_tokens, label, system):
        seen.append(label)
        return text, "stop"

    real = reports._attempt
    reports._attempt = attempt
    try:
        out = reports._generate(
            object(), "prompt", ("dna",), system=reports.AI_SYSTEM,
            banned=reports.AI_BANNED, detail=True)
    finally:
        reports._attempt = real
    return out, len(seen)


out, tries = replay(answer())
check("the clean answer is accepted on the first attempt",
      out is not None and tries == 1)
for planted in (" That is worth $2,000 a month.", " It is guaranteed.",
                " It turns into passive income."):
    out, tries = replay(answer(planted))
    check("planted %r: refused after one redraw" % planted.strip(),
          out is None and tries == 2)

print("\n--- the document and the mail ---")
check("the cover, the paths page, the chapters and the end are its own",
      profile["pdf_cover"] is reports._ai_cover
      and profile["pdf_after_cover"] is reports._ai_paths_page
      and profile["pdf_end"] is reports._ai_end
      and sorted(profile["pdf_body"]) == ["materials", "mistakes",
                                          "shopping"]
      and profile["pdf_taps"] is False
      and profile["pdf_section_shots"] is False)
html_doc = reports._pdf_html(content)
check("the cover carries the score, the prediction, the level, the zones",
      '<span class="n">6</span><span class="of">/12</span>' in html_doc
      and "You predicted 7–9. You scored 6." in html_doc
      and "<b>Builder</b>" in html_doc
      and html_doc.count('class="bar-name"') == 4
      and "The zone with the most room:" in html_doc)
check("the paths page: three with all five facts, two to skip",
      html_doc.count('<div class="ai-path') == 5
      and html_doc.count('<div class="ai-path is-first">') == 1
      and all(reports._e(CATALOG[pid][f]) in html_doc
              for pid in ("P3", "P4", "P1") for f in FACTS)
      and all(reports._e(CATALOG[pid]["risk"]) in html_doc
              for pid in ("P6", "P7"))
      and "Two to skip for now" in html_doc)
check("the answer key: twelve rows, theirs, the right one and why",
      html_doc.count('class="ai-key-row"') == 12
      and all(reports._e(r["why"]) in html_doc
              and reports._e(r["right"]) in html_doc for r in rows)
      and html_doc.count(">RIGHT<") == 6 and html_doc.count(">MISSED<") == 6)
check("the disclaimer closes the document, once, and is furniture",
      html_doc.count(reports._e(reports.AI_DISCLAIMER)) == 1
      and html_doc.rstrip().endswith(
          '<p class="ai-disclaimer">%s</p></body></html>'
          % reports._e(reports.AI_DISCLAIMER))
      and reports.AI_DISCLAIMER == CFG["result_copy"]["disclaimer"])
check("  the chapters are in it, badged in this product's words",
      ">BEST FIT<" in html_doc and ">SKIP FOR NOW<" in html_doc
      and "Two traps to step around" in html_doc
      and html_doc.count('class="day-n"') == 7)
pdf = reports.build_pdf(content)
check("it renders to a PDF", pdf is None or pdf[:4] == b"%PDF")
bare_content = dict(content, visuals={})
check("a report with nothing stored still renders, with no empty blocks",
      'class="ai-key-row"' not in reports._pdf_html(bare_content)
      and '<div class="ai-path' not in reports._pdf_html(bare_content)
      and 'class="hero"' not in reports._pdf_html(bare_content))
copy = reports._email_copy(content)
check("the mail is this product's",
      copy is reports.COPY_AI and "AI Navigator Report" in copy["subject"]
      and "three best-fit paths" in copy["body"])
real_price = reports._price_paid
try:
    reports._price_paid = lambda content, purchase_id=None: None
    bare_opening = reports._email_opening(content)
    reports._price_paid = lambda content, purchase_id=None: "$6"
    priced_opening = reports._email_opening(content)
finally:
    reports._price_paid = real_price
check("  its opening names the price when there is one, and not otherwise",
      bare_opening == copy["opening_bare"]
      and priced_opening == copy["opening"] % "$6"
      and "twelve answers" in bare_opening)
check("  and its footer carries the disclaimer, with and without a link",
      reports.html.escape(reports.AI_DISCLAIMER) in copy["keep"]
      and reports.html.escape(reports.AI_DISCLAIMER) in copy["keep_no_link"])
shown = reports.delivered_content(content, "reader@example.com")
check("the delivered page is told where the PDF went, the row is not",
      shown["visuals"]["delivery"] == {"email": "reader@example.com"}
      and "delivery" not in content["visuals"])

print("\n--- the delivered page reads the report ---")
DELIVERED = MODULE.split("function delivered(root, ctx) {", 1)[1]
check("it draws the paths card and the answer key from the stored report",
      "pathsCard(ctx, copy)" in DELIVERED and "answerKey(ctx, copy)" in
      DELIVERED and "ctx.visuals.paths" in MODULE
      and "ctx.visuals.answer_key" in MODULE)
check("  in order: numbers, paths, chapters, key, articles, footer",
      DELIVERED.index("bars(ctx, copy, data)")
      < DELIVERED.index("pathsCard(") < DELIVERED.index("deliveredNode(")
      < DELIVERED.index("answerKey(")
      < DELIVERED.index('articles(ctx, data, "delivered")')
      < DELIVERED.index("footer(copy)"))
check("  every word on both cards is the config's",
      sorted(CFG["result_copy"]["paths_card"]) == sorted(
          ["title", "lead", "format", "skip_title", "facts", "badge_works",
           "badge_avoid"])
      and sorted(CFG["result_copy"]["paths_card"]["facts"]) == sorted(FACTS)
      and sorted(CFG["result_copy"]["key_card"]) == sorted(
          ["title", "lead", "yours", "right", "none", "hit", "miss"]))
KEYS_FN = MODULE.split("function rsocKeys(ctx, block, data) {", 1)[1].split(
    "\n  }\n", 1)[0]
check("the article slot reads the report first, session storage second",
      KEYS_FN.index("ctx.visuals.brain") < KEYS_FN.index("sessionStorage"
                                                         ".getItem")
      and 'typeof run.skill === "string"' in KEYS_FN)

print("\n--- nobody else grew any of it ---")
OTHERS = (("brain", {"mem_hit": 4}), ("focus", {"mem_hit": 3}),
          ("persona", {"drive": 4}), ("zodiac", {"fire": 3}),
          ("kitchen", {"warm": 2}))
for slug, tally in OTHERS:
    cfg = load(slug)
    style = cfg["styles"][0]
    other = reports.start_report(30, slug, style["id"], tally)
    seen_visuals = other.get("visuals") or {}
    text = "\n".join(
        reports._section_prompt(style, style["name"], tally, section_id,
                                cfg=cfg, choices=None, funnel_slug=slug)
        for section_id in reports.personal_sections(slug))
    text += reports._cached_prompt(style, style["name"], funnel_slug=slug)
    check("%s: no paths, no answer key, no ai block in a prompt" % slug,
          "paths" not in seen_visuals and "answer_key" not in seen_visuals
          and "five paths" not in text and "FOUR ZONES THIS PERSON WAS "
          "SCORED ON" not in text and 'as "Strength #1 of 5"' not in text
          and reports._profile(slug) is not reports.AI_PROFILE
          and not reports._profile(slug).get("pdf_end")
          and not reports._profile(slug).get("section_fix"))
    check("  and its document ends where it always ended",
          "ai-disclaimer" not in reports._pdf_html(other))

print("\n%d checks, %d failed" % (checks[0], len(fails)))
for f in fails:
    print("  FAIL " + f[:500])
sys.exit(1 if fails else 0)
