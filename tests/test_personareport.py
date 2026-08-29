#!/usr/bin/env python3
"""The persona product: the profile a purchase stores, and the report it buys.

Everything here is what the $3 actually delivers, and none of it is reachable
from the config alone.

The profile block. `_reader_profile` is built on the zodiac vocabulary and
returns None for a persona run, which is why the delivered page drew the
plain card for as long as it did. `_persona_profile` is the answer, and the
thing worth testing about it is that it agrees with the browser: both feed
the same `richHero`, so a field this builds and that one does not is a page
that renders half of itself.

The pairings. Four per reader, from an 8x8 table in the config rather than
from the model — the paywall promises which profiles fit and which one costs,
and a model asked for four without being told which four will happily supply
four different ones per buyer of the same persona.

The banned line. This product reads temperament, so the two directions it can
drift are a horoscope and a diagnosis. Both are refused in the prompt and
again in the response, and the round trip below proves the second one: a
dirty answer is redrawn, and a dirty redraw becomes a stub.

    python3 tests/test_personareport.py
"""
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

CFG = json.load(open(os.path.join(REPO, "funnels/persona.json"),
                     encoding="utf-8"))
MODULE = open(os.path.join(REPO, "static/js/result_persona.js"),
              encoding="utf-8").read()
CHOICES = [step["pairs"][0]["images"][0]["id"]
           for step in CFG["swipe"]["steps"]]

fails = []
checks = [0]


def check(label, ok, detail=""):
    checks[0] += 1
    if not ok:
        fails.append("%s %s" % (label, detail))
    print("  %-62s %s%s" % (label, "ok" if ok else "FAIL",
                            ("  " + str(detail)) if not ok else ""))


def scores_for(style, energy):
    """A run that lands on this style with this energy, as tallies."""
    out = dict((tag, 9) for tag in (style.get("tags") or []))
    out.update({"drive": 3, "anchor": 3, "wave": 3, "prism": 3,
                "bold": 5, "calm": 3, "deep": 4})
    for tag in (style.get("tags") or []):
        out[tag] = 9
    out[energy] = 8
    out["inner" if energy == "outer" else "outer"] = 2
    return out


def every_persona():
    for style in CFG["styles"]:
        for energy in ("outer", "inner"):
            yield style, energy, reports._profile_for(
                CFG, "persona", style, scores_for(style, energy), CHOICES)


print("--- the profile a purchase stores ---")
profile = reports._profile("persona")
check("persona is registered", profile is reports.PERSONA_PROFILE)
check("  with its own voice", profile["system"] is reports.PERSONA_SYSTEM)
# Four sections, one per promise on the card the reader buys from. The two
# that are gone were the zodiac product's — colours and the work section —
# and neither was ever on that card.
BENEFIT_SECTIONS = {"dna", "materials", "mistakes", "shopping"}
check("  and its own shapes", set(profile["spec"]) == BENEFIT_SECTIONS,
      str(sorted(profile["spec"])))
check("  which are a subset of the ids every funnel here uses",
      set(profile["spec"]) < set(reports.ZODIAC_PROFILE["spec"]))
check("  so the validators, the renderer and the PDF need no persona branch",
      all(sid in reports.SPEC or sid in reports.ZODIAC_PROFILE["spec"]
          for sid in profile["spec"]))
check("  the cached section is the archetype's, the rest are the run's",
      profile["cached"] == ("mistakes",)
      and profile["personal"] == ("dna", "materials", "shopping"))
check("  and no section is in both",
      not set(profile["cached"]) & set(profile["personal"]))
check("  every section is either cached or personal",
      set(profile["cached"]) | set(profile["personal"]) == BENEFIT_SECTIONS)
check("  and zodiac keeps all six of its own",
      len(reports.ZODIAC_PROFILE["spec"]) == 6
      and reports.ZODIAC_PROFILE["cached"] == ("palette", "mistakes",
                                               "splurge"))

cards = list(every_persona())
check("all eight personas resolve a card",
      len(cards) == 8 and all(card for _s, _e, card in cards),
      str([(s["id"], e) for s, e, c in cards if not c]))

REQUIRED = ("archetype", "primary", "second", "energy", "subtype",
            "subtype_bare", "essence", "rarity", "rarer", "totem",
            "persona_slug", "narrative", "traits", "words", "formula",
            "rarity_line", "split", "split_caption", "scales")
missing = [(s["id"], e, sorted(set(REQUIRED) - set(card)))
           for s, e, card in cards if card and set(REQUIRED) - set(card)]
check("  each carrying every field the card draws", not missing,
      str(missing[:2]))

# The browser builds the same block for the free page. A field one of them
# invents and the other does not is a delivered page rendering half of itself.
browser_fields = set(re.findall(
    r"^\s{6}(\w+):", MODULE[MODULE.index("  function profileOf("):
                            MODULE.index("  // --- a) the kicker")], re.M))
check("  and the browser's own block names the same fields",
      set(REQUIRED) <= browser_fields,
      str(sorted(set(REQUIRED) - browser_fields)))

slugs = sorted(card["persona_slug"] for _s, _e, card in cards)
check("  eight distinct personas, named by archetype and energy",
      len(set(slugs)) == 8 and all("_" in s for s in slugs))
check("  the totem points at a file that exists",
      all(os.path.isfile(os.path.join(REPO, "static",
                                      card["totem"].lstrip("/")[len("static/"):]))
          for _s, _e, card in cards),
      str([c["totem"] for _s, _e, c in cards][:1]))
check("  the four traits always add to a hundred",
      all(sum(cell["pct"] for cell in card["split"]) == 100
          for _s, _e, card in cards))
check("  and the archetype's own axis leads, whatever out-scored it",
      all(card["primary"] in (s.get("tags") or [])
          for s, _e, card in cards))

# The picks, by the words that were on the cards. This is the claim the whole
# funnel makes, so a report that never quotes one has not paid it off.
first = cards[0][2]
told = "".join(part.get("text") or part.get("em") or ""
               for part in (first["narrative"] or []))
labels = [item["label"]
          for step in CFG["swipe"]["steps"] if step["id"] in
          reports.PERSONA_NARRATIVE_STEPS
          for pair in step["pairs"] for item in pair["images"]
          if item["id"] in CHOICES]
check("the narrative quotes the shapes they actually chose",
      all(label.lower() in told.lower() for label in labels),
      str([l for l in labels if l.lower() not in told.lower()]))
check("  by name, not by id",
      not any(pick_id in told for pick_id in CHOICES))


print("\n--- the pairings, from the table rather than the model ---")
table = CFG["pairings"]
check("the table is eight by eight", len(table) == 8
      and all(len(row) == 8 for row in table.values()), str(len(table)))
check("  every persona has a row and a column",
      set(table) == set(slugs)
      and all(set(row) == set(slugs) for row in table.values()))
cells = [cell for row in table.values() for cell in row.values()]
check("  sixty-four cells, each a verdict and a line", len(cells) == 64
      and all(set(c) == {"verdict", "line"} for c in cells))
check("  every verdict is one the section allows",
      all(c["verdict"] in reports.VERDICTS for c in cells),
      str(sorted({c["verdict"] for c in cells})))
check("  every line is short enough to read at a glance",
      max(len(c["line"]) for c in cells) <= 90,
      str(max(len(c["line"]) for c in cells)))
check("  and none of them is empty",
      all(c["line"].strip() and c["line"].endswith(".") for c in cells))
dirty = [(c["line"][:40], p.pattern) for c in cells
         for p in reports.PERSONA_BANNED if p.search(c["line"])]
check("  no line says a banned word", not dirty, str(dirty[:3]))

# The section asks for two that work and two that cost, so every row has to
# be able to supply them.
for row_id, row in table.items():
    works = sum(1 for k, c in row.items()
                if c["verdict"] == "works" and k != row_id)
    avoid = sum(1 for k, c in row.items()
                if c["verdict"] == "avoid" and k != row_id)
    if works < 2 or avoid < 2:
        check("  %s can fill the section" % row_id, False,
              "%d works, %d avoid" % (works, avoid))
        break
else:
    check("  every row can fill the section: two that work, two that cost",
          True)
check("  and nobody is their own best match",
      all(table[slug][slug]["verdict"] == "avoid" for slug in table))

block = reports._persona_pairs_block(CFG, first)
check("the prompt hands the model four pairings, with verdicts",
      block is not None and block.count("combo:") == 4)
check("  two that work and two that cost",
      block.count("verdict: works") == 2 and block.count("verdict: avoid") == 2)
check("  each led by the reader's own name",
      block.count('"%s + ' % first["subtype"]) == 4)
check("  and never the reader paired with themselves",
      ('"%s + %s"' % (first["subtype"], first["subtype"])) not in block)


print("\n--- the line this product must not cross ---")
words = ["diagnosis", "diagnose", "disorder", "IQ", "therapy", "therapist",
         "clinical", "psychometric", "scientifically proven",
         "scientifically validated", "MBTI", "enneagram", "DISC profile",
         "big five", "16personalities", "introvert", "extrovert",
         "psychic", "horoscope", "prophecy", "fortune"]
caught = [w for w in words
          if not any(p.search("a sentence with %s in it" % w)
                     for p in reports.PERSONA_BANNED)]
check("every word the persona suite bans is banned in reports.py",
      not caught, str(caught))
check("  and the zodiac list is carried whole, not replaced",
      set(reports.ZODIAC_BANNED) <= set(reports.PERSONA_BANNED))
check("  the system prompt refuses them too",
      all(word.lower() in reports.PERSONA_SYSTEM.lower()
          for word in ("diagnosis", "clinical", "MBTI", "introvert",
                       "horoscope")))
check("  and says outright that there is nothing mystical here",
      "nothing mystical" in reports.PERSONA_SYSTEM.lower())

ordinary = ["a steady week", "the work that suits you", "your own pattern",
            "what a month is good for"]
false_hits = [t for t in ordinary
              if any(p.search(t) for p in reports.PERSONA_BANNED)]
check("  while ordinary sentences pass", not false_hits, str(false_hits))


print("\n--- a dirty answer is redrawn, then stubbed ---")
# Double enforcement, end to end. The pair below is the point: the same
# answer, one word apart, and only the banned one is refused. A fixture that
# also fails the validator would be refused either way and would prove
# nothing about the banned list — which is what the first draft of this check
# did, quietly, while passing.
LONG = ("Your profile is stable across an ordinary week and shows up most "
        "clearly when somebody asks you for a decision at short notice.")
SECOND = ("The second paragraph runs the same length and says where the "
          "tension between those two settings actually produces something.")


def answer(word):
    return json.dumps({"dna": {
        "narrative": [LONG.replace("profile", word + " profile"), SECOND],
        "implications": ["You decide faster than you explain it.",
                         "You rest by finishing something small.",
                         "People read you as more certain than you feel."]}})


def replay(text):
    seen = []

    def attempt(client, prompt, max_tokens, label, system):
        seen.append(label)
        return text, "stop"

    real = reports._attempt
    reports._attempt = attempt
    try:
        out = reports._generate(
            object(), "prompt", ("dna",), system=reports.PERSONA_SYSTEM,
            banned=reports.PERSONA_BANNED, detail=True)
    finally:
        reports._attempt = real
    return out, len(seen)

clean_out, clean_tries = replay(answer("mind"))
check("the same answer, clean, is accepted", clean_out is not None,
      str(clean_out)[:60])
check("  on the first attempt", clean_tries == 1, str(clean_tries))

dirty_out, dirty_tries = replay(answer("clinical"))
check("one banned word in it and it is refused", dirty_out is None,
      str(dirty_out)[:60])
check("  after exactly one redraw", dirty_tries == 2, str(dirty_tries))
check("  and the word is what did it, not the shape",
      reports._banned_hit(json.loads(answer("clinical")),
                          reports.PERSONA_BANNED) is not None
      and reports._banned_hit(json.loads(answer("mind")),
                              reports.PERSONA_BANNED) is None)

clean = reports._stub_for("dna", CFG["styles"][0],
                          stubs=reports.PERSONA_STUBS)
check("and the stub that replaces it is clean",
      clean is not None
      and not any(p.search(json.dumps(clean))
                  for p in reports.PERSONA_BANNED))
every_stub = json.dumps([reports._stub_for(sid, CFG["styles"][0],
                                           stubs=reports.PERSONA_STUBS)
                         for sid in profile["spec"]])
check("  as is every other stub this profile ships",
      not any(p.search(every_stub) for p in reports.PERSONA_BANNED),
      str([p.pattern for p in reports.PERSONA_BANNED
           if p.search(every_stub)][:2]))


print("\n--- the document it all arrives in ---")
content = reports.start_report(1, "persona", CFG["styles"][0]["id"],
                               scores_for(CFG["styles"][0], "outer"),
                               choices=CHOICES)
content["version"] = "llm-2"
check("a purchase stores the profile block",
      bool((content.get("visuals") or {}).get("profile")))
html = reports._pdf_html(content)
for probe, label in (("head-plate", "the clay head"),
                     ("head-inlay", "its radar inlay"),
                     ("<polygon", "the reader's own shape, drawn"),
                     ("head-legend", "the trait legend"),
                     ("cover-totem-art", "the totem beside it"),
                     ("cover-subtype", "and the name they were given")):
    check("  the PDF carries %s" % label, probe in html)
pdf = reports.build_pdf(content)
check("it renders", pdf[:4] == b"%PDF")
check("  and fits in a mailbox: under 3 MB",
      len(pdf) < 3 * 1024 * 1024, "%.2f MB" % (len(pdf) / 1048576.0))

copy = reports._email_copy(content)
check("the mail is persona's own", copy is reports.COPY_PERSONA)
card = (content["visuals"] or {}).get("profile") or {}
subject = copy["subject"] % (card.get("subtype_bare") or "")
check("  naming the profile without doubling its article",
      "The " not in subject and "  " not in subject, subject)
check("  and never naming a paywall variant",
      not any((v.get("name") or "").lower() in json.dumps(copy).lower()
              for v in CFG["paywall_variants"]))


print("\n--- the neighbours ---")
check("zodiac still reads its own vocabulary",
      reports._profile("zodiac") is reports.ZODIAC_PROFILE
      and reports._profile("zodiac30") is reports.ZODIAC_PROFILE)
check("  and kitchen is still the fallback",
      reports._profile("kitchen") is reports.KITCHEN_PROFILE
      and reports._profile("nonesuch") is reports.KITCHEN_PROFILE)
check("  no zodiac funnel was given persona's banned list",
      reports.ZODIAC_PROFILE["banned"] is reports.ZODIAC_BANNED)
check("  and a zodiac run still builds a zodiac card",
      bool(reports._profile_for(
          json.load(open(os.path.join(REPO, "funnels/zodiac30.json"),
                         encoding="utf-8")),
          "zodiac30",
          json.load(open(os.path.join(REPO, "funnels/zodiac30.json"),
                         encoding="utf-8"))["styles"][0],
          {"fire": 9, "air": 4, "sun": 7, "moon": 2, "bold": 5}, None)))

print("\n%d checks, %d failed" % (checks[0], len(fails)))
for line in fails:
    print("  FAIL   %s" % line)
sys.exit(1 if fails else 0)
