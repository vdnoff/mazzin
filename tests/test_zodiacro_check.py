#!/usr/bin/env python3
"""Integrity checks over funnels/zodiac-ro.json — zodiac30, in Romanian.

test_zodiac30_check.py asserts what an eighteen-step walk is. This asserts
that /zodiac-ro is that same walk with nothing but the strings changed: the
same step ids in the same order, the same image ids on the same frames with
the same tags, the same interstitial anchors and mechanics, the same
archetypes, scoring, hook slots and rarity tables, the same galleries. The
funnel brings no new art and no new machinery — only a language.

So the shape is compared against the twin structurally rather than restated,
and what is checked on its own account is the part that is genuinely new: that
the copy really is Romanian, with the diacritics on, and that it stays inside
the same Terms line the English funnels are held to, in both languages.

No database, no network, no key. Everything is read off disk.
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
    print("  %-58s %s%s" % (label, "ok" if ok else "FAIL",
                            ("  " + detail) if detail and not ok else ""))


PATH = os.path.join(ROOT, "funnels/zodiac-ro.json")
RAW = open(PATH, encoding="utf-8").read()
cfg = json.loads(RAW)
static_cfg = json.load(
    open(os.path.join(ROOT, "static/funnels/zodiac-ro.json")))
twin = json.load(open(os.path.join(ROOT, "funnels/zodiac30.json")))
english = json.load(open(os.path.join(ROOT, "funnels/zodiac.json")))

steps = cfg["swipe"]["steps"]
tsteps = twin["swipe"]["steps"]
by_step = {s["id"]: s for s in steps}
images = [i for s in steps for p in s["pairs"] for i in p["images"]]
by_id = {i["id"]: i for i in images}


def leaves(node, path=""):
    """Every string in the config, with the path it sits at."""
    if isinstance(node, dict):
        for key, value in node.items():
            for item in leaves(value, path + "/" + key):
                yield item
    elif isinstance(node, list):
        for index, value in enumerate(node):
            for item in leaves(value, "%s/%d" % (path, index)):
                yield item
    elif isinstance(node, str):
        yield path, node


STRINGS = list(leaves(cfg))

print("\n--- config shape ---")
check("static copy matches funnels/", cfg == static_cfg)
check("slug is zodiac-ro", cfg["slug"] == "zodiac-ro", cfg["slug"])
check("funnel_id is zodiac_ro_v1", cfg["funnel_id"] == "zodiac_ro_v1",
      cfg["funnel_id"])
check("locale is ro", cfg["locale"] == "ro", cfg["locale"])
check("  and it is the only one of the three that says so",
      twin["locale"] == english["locale"] == "en")
check("pairs_count == number of steps",
      cfg["swipe"]["pairs_count"] == len(steps) == 18,
      "%s vs %s" % (cfg["swipe"]["pairs_count"], len(steps)))
check("the theme, the module and the sheet are the twin's",
      all(cfg[k] == twin[k] for k in
          ("theme", "result_module", "result_css", "stripe_mode")),
      str([k for k in ("theme", "result_module", "result_css", "stripe_mode")
           if cfg[k] != twin[k]]))

print("\n--- it is zodiac30's walk, string for string ---")


def shape(node):
    """The config with every string replaced by its type.

    What a translation is allowed to change is exactly the leaves this
    flattens: two configs with the same shape have the same keys, the same
    lists at the same lengths and the same numbers, and differ only in what
    they say.
    """
    if isinstance(node, dict):
        return dict((k, shape(v)) for k, v in node.items())
    if isinstance(node, list):
        return [shape(v) for v in node]
    return "str" if isinstance(node, str) else node


# The delivered page's two lines are the one place this funnel carries a key
# the twin does not. result_zodiac.js renders them from `result_copy` and
# falls back to its own English when a funnel declares none — which is what
# zodiac30 does, and what a Romanian funnel cannot afford to.
ADDED = ("delivery_line", "delivery_line_bare")


def comparable(config):
    """The config with the two known differences normalised away.

    `sign_cross` is a lookup keyed on the sign LABEL — both readers of it,
    result_zodiac.js and reports.py, ask for `sign_cross[<the label they
    tapped>][<element>] — so its twelve keys move with the twelve cards or
    every reader of this funnel gets a blank cross line. "cusp" is a literal
    in both and does not move. Compared by position, in the order the sign
    grid lists them.
    """
    out = dict(config)
    copy = dict(config["result_copy"])
    for key in ADDED:
        copy.pop(key, None)
    profile = dict(copy["profile"])
    cross = profile["sign_cross"]
    profile["sign_cross"] = ([cross[k] for k in cross if k != "cusp"]
                             + [cross["cusp"]])
    copy["profile"] = profile
    out["result_copy"] = copy
    return out


check("the whole config has the twin's shape",
      shape(comparable(cfg)) == shape(comparable(twin)))
check("  and sign_cross is keyed on this funnel's own twelve labels",
      [k for k in cfg["result_copy"]["profile"]["sign_cross"] if k != "cusp"]
      == [i["label"] for i in by_step["sign"]["pairs"][0]["images"]],
      str(list(cfg["result_copy"]["profile"]["sign_cross"])))
check("  with the cusp key untouched, because both readers spell it in code",
      "cusp" in cfg["result_copy"]["profile"]["sign_cross"]
      and len(cfg["result_copy"]["profile"]["sign_cross"]) == 13)
check("  and those two are the only keys it adds",
      set(cfg["result_copy"]) - set(twin["result_copy"]) == set(ADDED),
      str(sorted(set(cfg["result_copy"]) ^ set(twin["result_copy"]))))
check("  which say where the PDF went, in Romanian, with {email} intact",
      "{email}" in cfg["result_copy"]["delivery_line"]
      and cfg["result_copy"]["delivery_line_bare"],
      cfg["result_copy"]["delivery_line"])

check("step ids, in the twin's order",
      [s["id"] for s in steps] == [s["id"] for s in tsteps],
      str([s["id"] for s in steps]))
check("  every step keeps the twin's format",
      [s["format"] for s in steps] == [s["format"] for s in tsteps])
check("  and the twin's shuffle, pin_first, scoring and adaptive flags",
      [{k: s.get(k) for k in ("shuffle", "pin_first", "scoring", "adaptive")}
       for s in steps]
      == [{k: s.get(k) for k in ("shuffle", "pin_first", "scoring", "adaptive")}
          for s in tsteps])
check("image ids, in the twin's order",
      [i["id"] for i in images]
      == [i["id"] for s in tsteps for p in s["pairs"] for i in p["images"]])
check("  every frame points at the twin's file",
      all(i["img"] == j["img"] for i, j in zip(
          images,
          [x for s in tsteps for p in s["pairs"] for x in p["images"]])))
check("  and carries the twin's tags, in order",
      all(i["tags"] == j["tags"] for i, j in zip(
          images,
          [x for s in tsteps for p in s["pairs"] for x in p["images"]])))
check("no new art: every path is a gallery this funnel did not create",
      all(i["img"].startswith("/static/galleries/zodiac")
          and os.path.isfile(os.path.join(ROOT, i["img"].lstrip("/")))
          for i in images),
      str([i["img"] for i in images
           if not os.path.isfile(os.path.join(ROOT, i["img"].lstrip("/")))]))
check("  and the og image is the twin's",
      cfg["meta"]["og_image"] == twin["meta"]["og_image"])

print("\n--- the colours are the machinery, not the copy ---")
# reports.py hands a tapped card to the model as "<name> <hex> on the
# <element>", checks a generated palette against the config's own names field
# for field, and pairs those names with English role text in the stub. The
# element half of that sentence is frozen, so the name half is left in
# English with it: renaming only the middle would break the match and mix the
# sentence.
tcolours = [c for s in tsteps for p in s["pairs"] for i in p["images"]
            for c in i["colors"]]
mcolours = [c for i in images for c in i["colors"]]
check("every swatch on every card is the twin's, name and hex",
      mcolours == tcolours)
check("  and the four archetype palettes are too",
      [s["reveals"]["palette"]["colors"] for s in cfg["styles"]]
      == [s["reveals"]["palette"]["colors"] for s in twin["styles"]])

print("\n--- the interstitials keep their mechanics ---")
mids, tids = cfg["interstitials"], twin["interstitials"]
check("same count, same anchors",
      [e["after_step"] for e in mids] == [e["after_step"] for e in tids]
      == [4, 9, 14, 18],
      str([e["after_step"] for e in mids]))
check("  same templates and dwell times",
      [(e["template"], e["auto_advance_ms"]) for e in mids]
      == [(e["template"], e["auto_advance_ms"]) for e in tids])
check("  same echoed steps",
      [e.get("echo_steps") for e in mids] == [e.get("echo_steps") for e in tids])
check("  same personal axes, steps and variant keys",
      [((e.get("personal") or {}).get("axis"),
        (e.get("personal") or {}).get("step"),
        sorted((e.get("personal") or {}).get("lines") or {}))
       for e in mids]
      == [((e.get("personal") or {}).get("axis"),
           (e.get("personal") or {}).get("step"),
           sorted((e.get("personal") or {}).get("lines") or {}))
          for e in tids])
check("  every personal variant is written, line and sub",
      all(r.get("line") and r.get("sub")
          for e in mids
          for r in ((e.get("personal") or {}).get("lines") or {}).values()))
check("  and each interstitial still has its fallback line and CTA",
      all(e.get("kicker") and e.get("line") and e.get("cta") for e in mids))
check("the {sign} token survives every purpose variant",
      all("{sign}" in r["line"]
          for r in mids[0]["personal"]["lines"].values()),
      str([r["line"] for r in mids[0]["personal"]["lines"].values()]))
check("  and {pct} survives the calibration line",
      "{pct}" in mids[1]["line"], mids[1]["line"])

print("\n--- archetypes, scoring, hooks and rarity ---")
check("the same four archetype ids and tags",
      [(s["id"], s["tags"]) for s in cfg["styles"]]
      == [(s["id"], s["tags"]) for s in twin["styles"]])
check("  each one is renamed, and none is left in English",
      all(m["name"] != t["name"] for m, t in zip(cfg["styles"], twin["styles"])),
      str([s["name"] for s in cfg["styles"]]))
check("the report sections keep their ids, order and reveal modes",
      [(s["id"], s.get("enabled"), s["reveal"]["mode"])
       for s in cfg["report"]["sections"]]
      == [(s["id"], s.get("enabled"), s["reveal"]["mode"])
          for s in twin["report"]["sections"]])
check("the illustrated steps are the twin's",
      cfg["report"]["visuals"] == twin["report"]["visuals"])
check("the hook slots read the twin's steps",
      {k: v["step"] for k, v in cfg["report"]["hook_slots"].items()}
      == {k: v["step"] for k, v in twin["report"]["hook_slots"].items()})
# The bare noun a slot falls back to when the reader skipped that step. It
# lands mid-sentence in "energia ta de {symbol}", so it is copy — and
# "talisman" is simply the same word in both languages.
check("  and every fallback noun is the Romanian one",
      {k: v["fallback"] for k, v in cfg["report"]["hook_slots"].items()}
      == {"sign": "zodie", "palette": "paletă", "moonphase": "lună",
          "symbol": "talisman"},
      str({k: v["fallback"] for k, v in cfg["report"]["hook_slots"].items()}))
check("the rarity table is the twin's, number for number",
      cfg["result_copy"]["profile"]["rarity"]
      == twin["result_copy"]["profile"]["rarity"])
check("the purpose map points at the twin's sections",
      {k: v["emphasized_section"]
       for k, v in cfg["result_copy"]["purpose_map"].items()}
      == {k: v["emphasized_section"]
          for k, v in twin["result_copy"]["purpose_map"].items()})
check("pricing is unchanged: 300 usd",
      cfg["pricing"]["amount_cents"] == 300
      and cfg["pricing"]["currency"] == "usd",
      str(cfg["pricing"]))
check("  and it still transacts live",
      cfg["stripe_mode"] == "live", cfg["stripe_mode"])

print("\n--- the tokens the page fills ---")
TOKEN = re.compile(r"\{(\w+)\}")
tstrings = dict(leaves(twin))
drift = []
CROSS = "/result_copy/profile/sign_cross/"
for path, value in STRINGS:
    if path not in tstrings or path.startswith(CROSS):
        continue
    mine_t, theirs = sorted(TOKEN.findall(value)), \
        sorted(TOKEN.findall(tstrings[path]))
    if mine_t != theirs:
        drift.append((path, theirs, mine_t))
# One line drops a token on purpose. result_zodiac.js fills
# {subtype_article} with the English "a" or "an"; the Romanian subtype names
# carry their own article, so the bridge is written without it.
check("every line fills the same tokens as the twin's",
      [d[0] for d in drift] == ["/result_copy/profile/bridge"], str(drift))
check("  and no cross line fills a token at all, on either funnel",
      not [v for p, v in STRINGS if p.startswith(CROSS) and TOKEN.search(v)]
      and not [v for p, v in leaves(twin)
               if p.startswith(CROSS) and TOKEN.search(v)])
check("  and the bridge still names the subtype",
      "{subtype_bare}" in cfg["result_copy"]["profile"]["bridge"]
      and "{subtype_article}" not in cfg["result_copy"]["profile"]["bridge"],
      cfg["result_copy"]["profile"]["bridge"])
DECLARED = set(cfg["report"]["hook_slots"])
check("no line invents a hook slot the config does not declare",
      all(set(TOKEN.findall(v)) - DECLARED == set()
          or not path.startswith("/report/")
          for path, v in STRINGS),
      str([(p, TOKEN.findall(v)) for p, v in STRINGS
           if p.startswith("/report/") and set(TOKEN.findall(v)) - DECLARED]))

print("\n--- the accented half of a line is still inside it ---")
ACCENTS = [("swipe.subtext", cfg["swipe"]["subtext"],
            cfg["swipe"]["subtext_accent"]),
           ("commerce.anchor_head", cfg["checkout"]["commerce"]["anchor_head"],
            cfg["checkout"]["commerce"]["anchor_head_accent"]),
           ("commerce.price_anchor",
            cfg["checkout"]["commerce"]["price_anchor"],
            cfg["checkout"]["commerce"]["price_anchor_accent"]),
           ("commerce.mid_line", cfg["checkout"]["commerce"]["mid_line"],
            cfg["checkout"]["commerce"]["mid_line_accent"])]
for name, full, accent in ACCENTS:
    check("  %-22s contains its accent" % name, accent in full,
          "%r not in %r" % (accent, full))

print("\n--- it is actually Romanian ---")
# The failure this whole funnel exists to prevent: a config that shipped as a
# flat ASCII transliteration, or one where a block was never translated at
# all. Both read as Romanian at a glance and neither is.
for letter in "ăâîșț":
    check("  the config uses %r" % letter, letter in RAW)
check("  the s and t are comma-below, not the Turkish cedillas",
      "ş" not in RAW and "ţ" not in RAW)
DIACRITIC = re.compile(r"[ăâîșțĂÂÎȘȚ]")
# Prose blocks: long enough that Romanian without a single diacritic in them
# is not a coincidence.
PROSE = [(p, v) for p, v in STRINGS
         if len(v) > 90 and not p.endswith(("/img", "/hex", "/id"))]
flat = [p for p, v in PROSE if not DIACRITIC.search(v)]
check("every long line carries diacritics", not flat, str(flat[:4]))
check("  and there are enough of them to be a whole translation",
      len(PROSE) >= 90, "%d prose lines" % len(PROSE))
accented = [p for p, v in STRINGS if DIACRITIC.search(v)]
check("  with the accents spread across the whole config",
      len(accented) > 300
      and len({p.split("/")[1] for p in accented}) >= 9,
      "%d lines over %d blocks"
      % (len(accented), len({p.split("/")[1] for p in accented})))

SAME_AS_TWIN = [p for p, v in STRINGS
                if p in tstrings and v == tstrings[p]
                and p.split("/")[-1] in ("question", "label", "line", "sub",
                                         "kicker", "cta", "title", "blurb",
                                         "promise", "key", "spec", "hook",
                                         "teaser_line", "headline", "hint",
                                         "body", "fix", "setup", "trigger")]
# Two labels are spelled the same in both languages and translating them
# would be wrong, not thorough.
SPELLED_ALIKE = {"Capricorn", "Ocean"}
left = [p for p in SAME_AS_TWIN if tstrings[p] not in SPELLED_ALIKE]
check("no piece of visible copy was left in English", not left, str(left[:6]))
check("  and the two that read the same in both are the two expected",
      {tstrings[p] for p in SAME_AS_TWIN} == SPELLED_ALIKE,
      str(sorted({tstrings[p] for p in SAME_AS_TWIN})))
cross = cfg["result_copy"]["profile"]["sign_cross"]
check("all 52 cross lines are written, in Romanian",
      sum(1 for row in cross.values() for v in row.values()) == 52
      and all(DIACRITIC.search(v)
              for row in cross.values() for v in row.values()),
      str([k for k, row in cross.items()
           for v in row.values() if not DIACRITIC.search(v)]))
check("  each of the thirteen covers all four elements",
      all(sorted(row) == ["air", "earth", "fire", "water"]
          for row in cross.values()))
check("  and no two of them are the same sentence",
      len({v for row in cross.values() for v in row.values()}) == 52)
check("the twelve signs are the Romanian twelve",
      [i["label"] for i in by_step["sign"]["pairs"][0]["images"]]
      == ["Berbec", "Taur", "Gemeni", "Rac", "Leu", "Fecioară", "Balanță",
          "Scorpion", "Săgetător", "Capricorn", "Vărsător", "Pești"],
      str([i["label"] for i in by_step["sign"]["pairs"][0]["images"]]))

print("\n--- the count claims still say eighteen ---")
COUNTED = [("swipe.subtext", cfg["swipe"]["subtext"]),
           ("analyzing.messages[0]", cfg["analyzing"]["messages"][0]),
           ("analyzing.messages[1]", cfg["analyzing"]["messages"][1]),
           ("report.generating_messages[0]",
            cfg["report"]["generating_messages"][0]),
           ("checkout.proof_line", cfg["checkout"]["proof_line"]),
           ("interstitials[3].line", cfg["interstitials"][3]["line"]),
           ("result.value_banner", cfg["result"]["value_banner"])]
for name, text in COUNTED:
    check("  %-30s says 18" % name, "18" in text, text)
check("nothing claims twelve signals or twelve choices",
      not [v for _, v in STRINGS
           if re.search(r"\b12 (semnale|alegeri|atingeri)\b", v)],
      str([v for _, v in STRINGS
           if re.search(r"\b12 (semnale|alegeri|atingeri)\b", v)]))
check("  and the only twelve left is the year map",
      all("12 luni" in v or "douăsprezece luni" in v.lower()
          for v in [cfg["report"]["sections"][5]["title"]]))
check("four signals are said to remain after the third interstitial",
      "patru" in cfg["interstitials"][2]["sub"].lower(),
      cfg["interstitials"][2]["sub"])
check("the rarity line still counts in {n}",
      "{n}" in cfg["result_copy"]["profile"]["rarity_line"],
      cfg["result_copy"]["profile"]["rarity_line"])

print("\n--- the words this vertical does not use, in two languages ---")
import reports  # noqa: E402

# The English list the twins are held to, unchanged, plus the Romanian half.
# Everything in the config is scanned, not a hand-listed subset: nothing in
# here is inherited from an English funnel that was already cleared, because
# every string in this file was written for it.
EN_WORDS = ["psychic", "prediction", "predictions", "fortune",
            "horoscope", "prophecy", "your future will"]
RO_WORDS = ["psihic", "prezicere", "prezice", "prezis", "ghicit",
            "ghicitoare", "prorocie", "horoscop", "noroc", "viitorul tău va"]
low = RAW.lower()
for word in EN_WORDS + RO_WORDS:
    where = low.find(word)
    check("  never says %r" % word, where == -1,
          low[max(0, where - 40):where + 40])

en_hits = [(p, reports._banned_hit(v, reports.ZODIAC_BANNED))
           for p, v in STRINGS]
en_hits = [(p, h) for p, h in en_hits if h]
check("the whole config passes the English Terms check",
      not en_hits, str(en_hits[:4]))
ro_hits = [(p, reports._banned_hit(v, reports.ZODIAC_RO_BANNED))
           for p, v in STRINGS]
ro_hits = [(p, h) for p, h in ro_hits if h]
check("  and the Romanian one",
      not ro_hits, str(ro_hits[:4]))
check("the Romanian list is the English list plus its own",
      set(reports.ZODIAC_BANNED) < set(reports.ZODIAC_RO_BANNED)
      and len(reports.ZODIAC_RO_BANNED)
      == len(reports.ZODIAC_BANNED) + len(reports.ZODIAC_RO_ONLY))
CAUGHT = ["viitorul tău va aduce bani", "un pic de noroc", "o prezicere",
          "horoscopul tău", "am ghicit", "o prorocie veche", "psihicul cosmic",
          "simptome de oboseală", "medicamente"]
for phrase in CAUGHT:
    check("  %-28s is rejected" % ('"%s"' % phrase),
          reports._banned_hit(phrase, reports.ZODIAC_RO_BANNED) is not None)
check("  and ordinary Romanian is not",
      all(reports._banned_hit(t, reports.ZODIAC_RO_BANNED) is None
          for t in ("Ești bun la ce faci.", "Luna aceasta e bună pentru odihnă.",
                    "Alegi întâi cu inima.")))

print("\n--- the report profile behind it ---")
profile = reports._profile("zodiac-ro")
check("zodiac-ro is registered", profile is reports.ZODIAC_RO_PROFILE)
check("  and it is not the English object",
      profile is not reports.ZODIAC_PROFILE)
check("  but it is still a zodiac profile everywhere it matters",
      reports._is_zodiac(profile)
      and reports._is_zodiac(reports._profile("zodiac30"))
      and not reports._is_zodiac(reports._profile("kitchen")))
check("  the two English funnels still share one object",
      reports._profile("zodiac") is reports._profile("zodiac30")
      is reports.ZODIAC_PROFILE)
check("the same section split as the twin",
      profile["personal"] == reports.ZODIAC_PROFILE["personal"]
      and profile["cached"] == reports.ZODIAC_PROFILE["cached"])
check("  and the same shapes, asking for fewer characters",
      profile["spec"] is reports.ZODIAC_RO_SPEC
      and profile["spec"] is not reports.ZODIAC_PROFILE["spec"]
      and sorted(profile["spec"]) == sorted(reports.ZODIAC_PROFILE["spec"]))
# And marked in this language. The shopping shape names the year map's two
# marks as strings to COPY rather than as an idea to express, so a Romanian
# report asked for "Strongest month:" opens three Romanian notes with an
# English heading — which is what shipped.
check("    and the year map's two marks said in Romanian",
      reports.RENDER_WORDS_RO["year_strong"] in profile["spec"]["shopping"]
      and reports.RENDER_WORDS_RO["year_quiet"] in profile["spec"]["shopping"])
check("    and no longer in English",
      reports.RENDER_WORDS["year_strong"] not in profile["spec"]["shopping"]
      and reports.RENDER_WORDS["year_quiet"] not in profile["spec"]["shopping"])
check("  the English shape is untouched, character for character",
      reports.RENDER_WORDS["year_strong"] in reports.ZODIAC_SPEC["shopping"]
      and reports.ZODIAC_PROFILE["spec"] is reports.ZODIAC_SPEC)
check("  and the marks are the only thing the shapes differ in, bar numbers",
      [sid for sid in reports.ZODIAC_SPEC
       if reports._marked_shapes(reports.RENDER_WORDS_RO)[sid]
       != reports._ZODIAC_SHAPES[sid]] == ["shopping"])
check("its prompt asks for Romanian, in the first rule",
      "LANGUAGE" in profile["system"]
      and "Romanian" in profile["system"].split("Every field")[0])
check("  and names the diacritics",
      all(letter in profile["system"] for letter in "ăâîșț"))
check("  and restates the never-claim-the-future rule",
      "never claim" in profile["system"].lower()
      or "You never claim to know what will happen" in profile["system"])
check("  in both languages",
      all(word in profile["system"]
          for word in ("prezicere", "horoscop", "viitorul tău va",
                       "prophecy", "your future will")))
check("  and holds the JSON keys in English",
      "KEYS stay in English" in profile["system"])
check("the banned list is enforced on generation, not only in the prompt",
      profile["banned"] is reports.ZODIAC_RO_BANNED)

print("\n--- it asks for a Romanian-sized amount of Romanian ---")
# Romanian says the same thing in 15-20% more characters, so a prompt budget
# calibrated on English is one this funnel overruns while writing exactly what
# it was asked for. `splurge` is where that showed: five long prose fields in
# one call, and four consecutive failures on grounded_earth.
RO_BUDGET = reports.ZODIAC_RO_PROMPT_BUDGET
check("the profile declares its own prompt budget",
      profile.get("prompt_budget") == RO_BUDGET < reports.PROMPT_BUDGET,
      "%s vs %s" % (profile.get("prompt_budget"), reports.PROMPT_BUDGET))
check("  read through the accessor, which defaults to the English one",
      reports._prompt_budget(profile) == RO_BUDGET
      and reports._prompt_budget(reports.ZODIAC_PROFILE)
      == reports._prompt_budget(reports.KITCHEN_PROFILE)
      == reports._prompt_budget(None) == reports.PROMPT_BUDGET)
check("  and it is the only profile that sets the key",
      [slug for slug, p in reports.PROFILES.items()
       if p.get("prompt_budget")] == ["zodiac-ro"],
      str([slug for slug, p in reports.PROFILES.items()
           if p.get("prompt_budget")]))

# The claim the whole change rests on: whatever the prompt asks for, the
# validator that would throw the section away allows more. Checked over every
# capped field of every section rather than the ones that happened to fail.
over = []
tighter = []
for section_id in sorted(reports.ZODIAC_RO_SPEC):
    ceilings = reports._ceilings(section_id)
    ro = reports._budgets(section_id, RO_BUDGET)
    en = reports._budgets(section_id)
    for field, asked in sorted(ro.items()):
        cap = ceilings[field]
        if asked > cap:
            over.append("%s.%s asks %d of %d" % (section_id, field, asked, cap))
        if asked >= en[field]:
            tighter.append("%s.%s %d vs %d" % (section_id, field, asked,
                                               en[field]))
check("every RO budget is inside the ceiling that polices its field",
      not over, str(over))
check("  and every one of them is under the English number",
      not tighter, str(tighter))
check("  with real headroom left, not a rounding of it",
      all(asked <= 0.62 * reports._ceilings(sid)[field]
          for sid in reports.ZODIAC_RO_SPEC
          for field, asked in reports._budgets(sid, RO_BUDGET).items()),
      str([(sid, f, a, reports._ceilings(sid)[f])
           for sid in reports.ZODIAC_RO_SPEC
           for f, a in reports._budgets(sid, RO_BUDGET).items()
           if a > 0.62 * reports._ceilings(sid)[f]]))

# PROMPT_LENGTH is hand-set and overrides the derived default, so a budget
# that only moved the derived numbers would have left the failing section
# exactly as it was.
check("the hand-set lengths came down too, not just the derived ones",
      all(reports._budgets(sid, RO_BUDGET)[field]
          < reports.PROMPT_LENGTH[sid][field]
          for sid, fields in reports.PROMPT_LENGTH.items()
          for field in fields),
      str({sid: {f: reports._budgets(sid, RO_BUDGET)[f]
                 for f in fields}
           for sid, fields in reports.PROMPT_LENGTH.items()}))
check("  splurge, the section that failed, asks for less in every field",
      all(reports._budgets("splurge", RO_BUDGET)[f] < v
          for f, v in reports._budgets("splurge").items()),
      "%s vs %s" % (reports._budgets("splurge", RO_BUDGET),
                    reports._budgets("splurge")))
check("  and the shape the model is handed states the smaller numbers",
      "370 characters maximum" in reports.ZODIAC_RO_SPEC["splurge"]
      and "440 characters maximum" not in reports.ZODIAC_RO_SPEC["splurge"])
check("the English shapes are untouched, byte for byte",
      reports.ZODIAC_SPEC == dict(
          (sid, reports._zodiac_spec(text, sid))
          for sid, text in reports._ZODIAC_SHAPES.items())
      and "440 characters maximum" in reports.ZODIAC_SPEC["splurge"])


def shape_only(text):
    """One shape with the three things that separate the languages taken off.

    The budgets, the closing punctuation rule, and the two prefixes the year
    map marks its months with. Normalise all three and what is left is the
    question itself, which has to be the same question in both.
    """
    if text.endswith(reports.ZODIAC_RO_JSON_RULE):
        text = text[:-len(reports.ZODIAC_RO_JSON_RULE)]
    for key in ("year_strong", "year_quiet"):
        text = text.replace(reports.RENDER_WORDS_RO[key],
                            reports.RENDER_WORDS[key])
    return re.sub(r"\d+", "#", text)


check("  and the two ask the same questions, in different numbers",
      all(shape_only(reports.ZODIAC_RO_SPEC[sid])
          == shape_only(reports.ZODIAC_SPEC[sid])
          for sid in reports.ZODIAC_SPEC),
      str([sid for sid in reports.ZODIAC_SPEC
           if shape_only(reports.ZODIAC_RO_SPEC[sid])
           != shape_only(reports.ZODIAC_SPEC[sid])]))

print("\n--- Romanian prose is what breaks the JSON ---")
# The other half of the failure, and the half that is not about length: a
# 1748-character answer that stopped on end_turn still failed to parse, which
# only unescaped punctuation explains.
check("the prompt says the answer is JSON and what breaks it",
      "not valid JSON" in profile["system"]
      and "escaped" in profile["system"])
check("  and offers the Romanian punctuation that costs nothing to parse",
      "„" in profile["system"])
check("  the English prompt is unchanged",
      reports.ZODIAC_PROFILE["system"] is reports.ZODIAC_SYSTEM
      and "„" not in reports.ZODIAC_SYSTEM)

WANT = ("splurge",)


def body(text):
    """One section's worth of JSON, with `text` in a prose field."""
    return json.dumps(
        {"splurge": {"splurge": {"item": "Un curs de trei luni",
                                 "why": text},
                     "split_note": text,
                     "saves": [{"item": "Un caiet", "why": text},
                               {"item": "O oră pe zi", "why": text}]}},
        ensure_ascii=False)


PROSE = "Banii îți urmează atenția, nu efortul, iar tiparul se rupe. " * 4
ok_json = body(PROSE)

parsed, why = reports._parse_detail(ok_json, WANT, [])
check("a valid answer still parses", parsed is not None, why)

# The retry. It used to be handed the diagnostic line inside a block that
# closes "the character counts are hard limits" — a length correction for a
# punctuation failure, so the second attempt repeated the first.
notes = []
parsed, why = reports._parse_detail(
    ok_json.replace("nu efortul", 'nu "efortul"', 1), WANT, notes)
check("an unescaped quote is still refused", parsed is None, str(parsed)[:60])
check("  and the retry names the failure as a parse failure",
      notes and "not valid JSON" in notes[0], str(notes))
retry = reports._retry_prompt("PROMPT", notes)
check("  telling the model to escape its quotes, not to count characters",
      "Escape every double quote" in retry
      and "punctuation, not length" in retry, retry[-200:])
check("  and it reaches the prompt through the existing retry block",
      retry.startswith("PROMPT") and reports.RETRY_NOTE in retry)
check("  where a section that parses adds no note at all",
      reports._parse_detail(ok_json, WANT, [])[0] is not None
      and reports._parse_detail(ok_json, WANT, [])[1] is None)
check("kitchen never sees it — it passes no notes list",
      reports.KITCHEN_PROFILE["retry_detail"] is False
      and reports._retry_prompt("PROMPT", None)
      == "PROMPT" + reports.RETRY_NOTE)

# The one salvage, and the one deliberately not attempted.
raw_nl = body(PROSE).replace("nu efortul", "nu\nefortul", 1)
parsed, why = reports._parse_detail(raw_nl, WANT, [])
check("a raw line break inside a value is recovered", parsed is not None, why)
check("  losslessly — the text is what the model wrote",
      parsed and "nu\nefortul" in parsed["splurge"]["splurge"]["why"])
check("  and still went through the shape and length validators",
      parsed and len(parsed["splurge"]["split_note"])
      <= reports._ceilings("splurge")["split_note"])
long_nl = body("x" * 700 + "\n" + "y" * 700)
check("  a salvaged answer over its ceiling is still thrown away",
      reports._parse_detail(long_nl, WANT, [])[0] is None)
banned_nl = body("Un simptom clar.\nApoi altceva. " * 3)
salvaged = reports._parse_detail(banned_nl, WANT, [])[0]
check("  and a salvaged answer still faces the banned list",
      salvaged is not None
      and reports._banned_hit(salvaged, reports.ZODIAC_RO_BANNED) is not None,
      str(reports._banned_hit(salvaged, reports.ZODIAC_RO_BANNED)))
check("truncation is not salvaged — it is still truncation",
      reports._parse_detail(ok_json[:400], WANT, [])[0] is None)

print("\n--- the give-up log names the character that did it ---")
# Six identical failures said only "JSONDecodeError at char 743" — a position
# and an exception class, never the character. Forty either side is the
# difference between a seventh guess and a diagnosis.
SAID = 'Refuz-o clar, cu propoziția: "Pot prelua asta acum." Pune'
broken = body(PROSE).replace("nu efortul", "nu " + SAID, 1)
parsed, why = reports._parse_detail(broken, WANT, [])
check("an invalid-JSON reason carries an excerpt", parsed is None
      and " near " in why, why)
check("  wide enough to show the quote in its sentence",
      "Pot prelua" in why, why)
multiline = body("Prima linie.\nA doua linie, cu \"ghilimele\" drepte.")
_, why_nl = reports._parse_detail(
    multiline.replace('\\"', '"').replace("\\n", "\n"), WANT, [])
check("  escaped to one line, so an answer cannot forge a log record",
      why_nl is None or "\n" not in why_nl, repr(why_nl))
check("  and sized as configured",
      reports.EXCERPT_EITHER_SIDE == 40
      and len(reports._excerpt("x" * 400, 200)) <= 2 * 40 + 12)
check("  a reason with no position gets no excerpt, not a crash",
      reports._excerpt("abc", None) == "" and reports._excerpt("", 1) == "")
check("no other failure grew one",
      " near " not in reports._parse_detail('{"nope": 1}', WANT, [])[1]
      and " near " not in reports._parse_detail("", WANT, [])[1])
# The reason string carries the model's own words now; the note sent back to
# it must not. That invariant is what keeps a bad answer from being quoted
# into the prompt that asks for a better one.
leak_notes = []
reports._parse_detail(broken, WANT, leak_notes)
leaked = reports._retry_prompt("P", leak_notes)
check("and the excerpt never reaches the model",
      "Pot prelua" not in leaked and "Refuz-o clar" not in leaked)
check("  and the one note it does send is the generic advice",
      len(leak_notes) == 1
      and leak_notes[0].startswith("the answer was not valid JSON"),
      str(leak_notes))

print("\n--- the field that kept breaking it ---")
# grounded_earth x splurge failed 6/6. `splurge` is the one cached section
# whose shape asks, three times per answer, for "the sentence to say" — and a
# model asked for a sentence to say types quotation marks around it.
check("splurge is the section that asks for a quotable sentence",
      "sentence to say" in reports._ZODIAC_SHAPES["splurge"]
      and "sentence to say" not in reports._ZODIAC_SHAPES["mistakes"],
      "the shape no longer asks for it — this diagnosis is stale")
check("every RO shape closes on the punctuation contract",
      all(sid_text.endswith(reports.ZODIAC_RO_JSON_RULE)
          for sid_text in reports.ZODIAC_RO_SPEC.values()))
check("  which tells it to write the sentence with no quotation marks",
      "no quotation marks"
      in " ".join(reports.ZODIAC_RO_JSON_RULE.split()))
check("  and offers the Romanian pair as the only alternative",
      "„" in reports.ZODIAC_RO_JSON_RULE
      and "U+201E" in reports.ZODIAC_RO_JSON_RULE)
check("the English shapes carry none of it",
      not any(reports.ZODIAC_RO_JSON_RULE in t
              for t in reports.ZODIAC_SPEC.values())
      and "PUNCTUATION" not in reports.ZODIAC_SPEC["splurge"])
check("the RO prompt forbids the character outright, not as a preference",
      "Never type one inside a value" in profile["system"])
check("  and the English prompt still says nothing about it",
      "Never type one inside a value" not in reports.ZODIAC_SYSTEM)

print("\n--- and the retry repeats that rule, for this funnel only ---")
check("the RO profile declares a JSON retry note",
      profile["json_retry"] is reports.ZODIAC_RO_JSON_RETRY)
check("  and it is the only profile that does",
      [slug for slug, pr in reports.PROFILES.items() if pr.get("json_retry")]
      == ["zodiac-ro"],
      str([slug for slug, pr in reports.PROFILES.items()
           if pr.get("json_retry")]))
check("  naming the quote, the field and what to do instead",
      "straight double quote" in reports.ZODIAC_RO_JSON_RETRY
      and "sentence a field asked" in reports.ZODIAC_RO_JSON_RETRY
      and "NO quotation marks" in reports.ZODIAC_RO_JSON_RETRY)
check("_generate takes it as an argument, defaulting to none",
      "json_retry" in reports._generate.__code__.co_varnames
      and reports._generate.__defaults__[-1] is None)
check("  and every call site hands the profile's own",
      open(os.path.join(ROOT, "reports.py"), encoding="utf-8").read().count(
          'profile.get("json_retry")') == 3)


# The wiring, exercised rather than inspected. No network: the client is a
# stub that returns the same unparseable answer twice, so both attempts and
# the give-up are driven without a key.
class _Stub:
    """A client that answers every call with `text`, recording the prompts."""

    def __init__(self, text):
        self.text = text
        self.sent = []
        self.messages = self

    def create(self, **kw):
        self.sent.append(kw["messages"][0]["content"])
        block = type("B", (), {"type": "text", "text": self.text})()
        return type("M", (), {"content": [block], "stop_reason": "end_turn"})()


def retry_for(pr):
    """The second prompt `_generate` sends for `pr`, on an unparseable answer."""
    limiter, timeout = reports._limiter, reports._timeout_class
    reports._limiter = lambda: type(
        "G", (), {"acquire": lambda s: None, "release": lambda s: None})()
    reports._timeout_class = lambda: None
    stub = _Stub(broken)
    try:
        reports._generate(stub, "P", WANT, 900, pr["system"], pr["banned"],
                          pr["retry_detail"], None, pr.get("json_retry"))
    finally:
        reports._limiter, reports._timeout_class = limiter, timeout
    return stub.sent[1]


ro_retry = retry_for(profile)
en_retry = retry_for(reports.ZODIAC_PROFILE)
kitchen_retry = retry_for(reports.KITCHEN_PROFILE)
check("a Romanian retry really does carry the rule",
      reports.ZODIAC_RO_JSON_RETRY in ro_retry)
check("  and the generic advice before it",
      0 <= ro_retry.find("punctuation, not length")
      < ro_retry.find(reports.ZODIAC_RO_JSON_RETRY))
check("an English zodiac retry gets the generic advice and no more",
      "This is punctuation, not length" in en_retry
      and reports.ZODIAC_RO_JSON_RETRY not in en_retry
      and "„" not in en_retry)
check("a kitchen retry is the line it has always been",
      kitchen_retry == "P" + reports.RETRY_NOTE, kitchen_retry[-80:])
check("and no retry quotes the answer back at the model",
      not any("Pot prelua" in r
              for r in (ro_retry, en_retry, kitchen_retry)))

check("  and neither is a stray quote, which no repair can guess at safely",
      reports._parse_detail(
          ok_json.replace("nu efortul", 'nu "efortul"', 1), WANT, [])[0]
      is None)

print("\n--- the year, in Romanian ---")
months = reports._months_for(profile)
check("twelve labels", len(months) == 12, str(months))
check("  in Romanian month names", all(
    any(m.startswith(a) for a in reports.MONTH_ABBR_RO) for m in months),
      str(months))
check("  none of them is an English month",
      not [m for m in months
           if any(m.startswith(a) for a in reports.MONTH_ABBR)],
      str(months))
check("  starting from this month, not January",
      months[0] == "%s %d" % (
          reports.MONTH_ABBR_RO[reports.datetime.datetime.now(
              reports.datetime.timezone.utc).date().month - 1],
          reports.datetime.datetime.now(
              reports.datetime.timezone.utc).date().year),
      months[0])
check("the twin still counts its year in English",
      reports._months_for(reports.ZODIAC_PROFILE) == reports._year_labels())
check("  and kitchen counts no year at all",
      reports._months_for(reports.KITCHEN_PROFILE) is None)
check("the month validator accepts the Romanian twelve",
      reports._verify_months(
          {"items": [{"name": m} for m in months]}, months) is None)
check("  and rejects a year that opens in January anyway",
      reports._verify_months(
          {"items": [{"name": m} for m in reports._year_labels()]},
          months) is not None)

print("\n--- compatibility, in the names the cards carry ---")
table = profile["compatibility"]
signs = [i["label"] for i in by_step["sign"]["pairs"][0]["images"]]
check("every sign on the grid has a row",
      sorted(table) == sorted(signs),
      str(sorted(set(table) ^ set(signs))))
check("  each row names two magnetic signs and one that drains",
      all(len(v[0]) == 2 and isinstance(v[1], str) for v in table.values()))
check("  and every name in it is one of the twelve",
      all(name in signs for magnetic, drains in table.values()
          for name in list(magnetic) + [drains]),
      str([name for magnetic, drains in table.values()
           for name in list(magnetic) + [drains] if name not in signs]))
check("  never itself",
      not [k for k, v in table.items() if k in list(v[0]) + [v[1]]])
check("the classical trines survived translation",
      table["Berbec"][0] == ("Leu", "Săgetător")
      and table["Rac"][0] == ("Scorpion", "Pești")
      and table["Fecioară"][0] == ("Taur", "Capricorn"),
      str(table["Berbec"]))
check("the English table is untouched",
      reports.COMPATIBILITY["Aries"] == (("Leo", "Sagittarius"), "Cancer")
      and reports.ZODIAC_PROFILE["compatibility"] is reports.COMPATIBILITY)

# A run down the Romanian walk, to the block the love section is built from.
choices = []
for step in steps:
    if step["id"] == "sign":
        choices.append("sign_virgo")
    else:
        choices.append(step["pairs"][0]["images"][0]["id"])
read = reports._sign(cfg, choices)
check("the sign step reads back a Romanian label",
      (read or {}).get("label") == "Fecioară", str(read))
block = reports._compat_block(cfg, choices, table)
check("  and the love prompt names its three signs in Romanian",
      block and "Taur" in block and "Capricorn" in block
      and "Săgetător" in block and "Virgo" not in block,
      (block or "")[:120])
check("  where the English table would have named none of them",
      reports._compat_block(cfg, choices, reports.COMPATIBILITY) is None)

print("\n--- the mail and the document ---")
check("zodiac-ro sends its own mail",
      reports._email_copy({"funnel": "zodiac-ro"}) is reports.COPY_ZODIAC_RO)
check("  and the English funnels still send theirs",
      reports._email_copy({"funnel": "zodiac30"})
      is reports._email_copy({"funnel": "zodiac"}) is reports.COPY_ZODIAC)
check("  and kitchen is untouched",
      reports._email_copy({"funnel": "kitchen"}) is not reports.COPY_ZODIAC_RO)
for field in ("headline", "subject", "body", "keep", "keep_no_link"):
    value = reports.COPY_ZODIAC_RO[field]
    check("  mail.%-10s is Romanian" % field,
          bool(DIACRITIC.search(value)) and value != reports.COPY_ZODIAC.get(field),
          value)
check("  the subject still takes the style name",
      reports.COPY_ZODIAC_RO["subject"].count("%s") == 1
      and reports.COPY_ZODIAC_RO["body"].count("%s") == 1)
check("  and it is not a kitchen mail by another name",
      "kitchen" not in reports.COPY_ZODIAC_RO["subject"].lower())
check("the opening line is Romanian and names the price",
      DIACRITIC.search(reports._email_opening({"funnel": "zodiac-ro"}))
      and "$3" in reports._email_opening({"funnel": "zodiac-ro"}),
      reports._email_opening({"funnel": "zodiac-ro"}))
check("  and the English opening is unchanged",
      reports._email_opening({"funnel": "zodiac30"}).startswith("You just spent"),
      reports._email_opening({"funnel": "zodiac30"}))
check("the button on the mail is Romanian",
      "Deschide" in profile["mail_link"]
      and "Open your profile online" not in profile["mail_link"])
check("  and the English template still fills on {link} alone",
      reports.ZODIAC_EMAIL_LINK % {"link": "x"})
check("the PDF leads and closes in Romanian",
      bool(DIACRITIC.search(profile["pdf_lead"]))
      and bool(DIACRITIC.search(profile["pdf_note"]))
      and profile["pdf_lead"] != reports.ZODIAC_PROFILE["pdf_lead"],
      profile["pdf_lead"])
check("  the document declares its language",
      profile.get("pdf_lang") == "ro")
check("  the cover strip names the four elements in Romanian",
      [label for _t, label, _h in profile["pdf_elements"]]
      == ["Foc", "Pământ", "Aer", "Apă"])
check("  and it draws the same cover and sheet as the twin",
      profile["pdf_cover"] is reports.ZODIAC_PROFILE["pdf_cover"]
      and profile["pdf_css"] is reports.ZODIAC_PROFILE["pdf_css"])
check("the delivered page is still handed the address",
      profile.get("delivery_note") is True)
check("  and every section header it prints is this config's Romanian",
      all(m["title"] != t["title"] for m, t in
          zip(cfg["report"]["sections"], twin["report"]["sections"])),
      str([s["title"] for s in cfg["report"]["sections"]]))

print("\n--- the cache is this funnel's own ---")
# style_sections is keyed (funnel, style_id), so this funnel warms its own
# rows and can never be served the English ones. `warm_cache.py zodiac-ro`
# writes them; `--copy-from zodiac` would fill them with English and is the
# one thing not to do here.
check("the section cache reads and writes on the funnel",
      "funnel = %s" in reports.SELECT_SECTIONS_SQL
      and "(funnel, style_id, section_id, content)"
      in reports.UPSERT_SECTION_SQL)
check("  so nothing this funnel is served can be the twin's row",
      reports.SELECT_SECTIONS_SQL.count("%s") == 2)
check("  and it holds the same three sections as the twin",
      reports.cached_sections("zodiac-ro")
      == reports.cached_sections("zodiac30") == ("palette", "mistakes",
                                                 "splurge"))
check("  stamped with the same revisions",
      all(reports._cache_tag("zodiac-ro", s) == reports._cache_tag("zodiac30", s)
          for s in ("palette", "mistakes", "splurge")))

print("\n--- the words the report prints itself ---")
# The furniture between the sections: the PDF's headings, the badges on the
# love verdicts, the year map's two marks, and the fallbacks that stand in
# when a config or a run is missing a string. Every one of them was a literal
# in the render path, which is how a Romanian report came back with English
# headings around Romanian sentences.
check("the profile carries its own words",
      profile["words"] is reports.RENDER_WORDS_RO
      and reports._words(profile) is reports.RENDER_WORDS_RO)
check("  and every English funnel prints the defaults",
      reports._words(reports.ZODIAC_PROFILE)
      is reports._words(reports.KITCHEN_PROFILE)
      is reports._words(reports._profile("kitchen-visualizer"))
      is reports.RENDER_WORDS)
check("  a profile that declares none falls back to them",
      reports._words({}) is reports._words(None) is reports.RENDER_WORDS)
check("the Romanian map covers every key the English one has",
      sorted(reports.RENDER_WORDS_RO) == sorted(reports.RENDER_WORDS),
      str(sorted(set(reports.RENDER_WORDS) ^ set(reports.RENDER_WORDS_RO))))

# The exact English, stated here rather than read off the module: this is the
# assertion that kitchen, zodiac and zodiac30 print what they always printed,
# so it has to fail if somebody edits the default rather than the override.
ENGLISH = {
    "year_strong": "Strongest month:",
    "year_quiet": "Quiet month:",
    "fix": "Fix:",
    "skip": "Skip",
    "splurge": "Splurge",
    "save": "Save",
    "style_fallback": "Your style",
    "taps_caption": "Read from your taps:",
    "mail_style": "style",
    "pdf_filename": "mazzin-%s-report.pdf",
}
for key, value in sorted(ENGLISH.items()):
    check("  %-16s defaults to the English it always was" % key,
          reports.RENDER_WORDS[key] == value, repr(reports.RENDER_WORDS[key]))
check("  verdicts        defaults to WORKS / AVOID",
      reports.RENDER_WORDS["verdicts"] == {"works": "WORKS",
                                           "avoid": "AVOID"},
      str(reports.RENDER_WORDS["verdicts"]))
check("  pdf_note        defaults to the note kitchen has always printed",
      reports.RENDER_WORDS["pdf_note"].startswith("Keep this — your report"))

for key in sorted(ENGLISH):
    value = reports.RENDER_WORDS_RO[key]
    check("  %-16s is not the English" % key,
          value != reports.RENDER_WORDS[key], repr(value))
check("  and the Romanian verdict badges are MERGE / EVITĂ",
      reports.RENDER_WORDS_RO["verdicts"] == {"works": "MERGE",
                                              "avoid": "EVITĂ"},
      str(reports.RENDER_WORDS_RO["verdicts"]))
check("  the Romanian words carry their diacritics",
      all(DIACRITIC.search(reports.RENDER_WORDS_RO[k]) for k in
          ("year_strong", "year_quiet", "fix", "save", "style_fallback",
           "pdf_note")),
      str([k for k in ("year_strong", "year_quiet", "fix", "save",
                       "style_fallback", "pdf_note")
           if not DIACRITIC.search(reports.RENDER_WORDS_RO[k])]))
check("  and pass the Romanian Terms check",
      not [(k, reports._banned_hit(v, reports.ZODIAC_RO_BANNED))
           for k, v in reports.RENDER_WORDS_RO.items()
           if reports._banned_hit(v, reports.ZODIAC_RO_BANNED)],
      str([k for k, v in reports.RENDER_WORDS_RO.items()
           if reports._banned_hit(v, reports.ZODIAC_RO_BANNED)]))
check("the attachment still takes the style name once",
      reports.RENDER_WORDS_RO["pdf_filename"].count("%s") == 1
      and reports.RENDER_WORDS_RO["pdf_filename"].endswith(".pdf"),
      reports.RENDER_WORDS_RO["pdf_filename"])

print("\n--- the document those words are printed into ---")


def document(slug, style_id="celestial_air"):
    """One whole report for a funnel, stubbed end to end, as HTML."""
    funnel = json.load(open(os.path.join(ROOT, "funnels", slug + ".json"),
                            encoding="utf-8"))
    style = reports._style(funnel, style_id)
    prof = reports._profile(slug)
    months = reports._months_for(prof)
    built, paths = {}, {}
    for section in funnel["report"]["sections"]:
        stub = reports._stub_for(section["id"],
                                 reports._style_name(funnel, style_id),
                                 style, prof["stubs"], months,
                                 prof.get("stub_colors"))
        if stub is None:
            continue
        built[section["id"]] = stub
        paths[section["id"]] = "stub"
    return reports._pdf_html(reports._assemble(
        funnel, slug, style_id, reports._style_name(funnel, style_id),
        built, paths, True))


ro_doc = document("zodiac-ro")
en_doc = document("zodiac30")
for word in ("Fix:", ">Splurge ", ">Save<", ">Skip<", ">WORKS<", ">AVOID<",
             "Your style", "Strongest month:", "Quiet month:"):
    check("  the Romanian PDF never prints %-18s" % repr(word),
          word not in ro_doc, word)
for word, present in ((reports.RENDER_WORDS_RO["fix"], True),
                      (reports.RENDER_WORDS_RO["splurge"], True),
                      (reports.RENDER_WORDS_RO["save"], True),
                      ("MERGE", True), ("EVITĂ", True),
                      (reports.RENDER_WORDS_RO["year_strong"], True)):
    check("  and it does print %-28s" % repr(word),
          (word in ro_doc) is present, word)
check("  the verdict CLASS stays the English word the stylesheet colours on",
      'class="badge works"' in ro_doc and 'class="badge avoid"' in ro_doc)
check("  the document still declares itself Romanian",
      '<html lang="ro"' in ro_doc)
check("zodiac30's document is the English one, word for word",
      all(w in en_doc for w in ("Fix:", "<b>Splurge &mdash;", "<b>Save</b>",
                                ">WORKS<", ">AVOID<")),
      str([w for w in ("Fix:", "<b>Splurge &mdash;", "<b>Save</b>",
                       ">WORKS<", ">AVOID<") if w not in en_doc]))
check("  and carries not one Romanian word of this funnel's",
      not [w for w in (reports.RENDER_WORDS_RO[k] for k in
                       ("fix", "skip", "save", "year_strong", "year_quiet"))
           if w in en_doc],
      str([w for w in (reports.RENDER_WORDS_RO[k] for k in
                       ("fix", "skip", "save", "year_strong", "year_quiet"))
           if w in en_doc]))
check("the emailed attachment is named in Romanian",
      reports._words(profile)["pdf_filename"] % "aer-celest"
      == "mazzin-aer-celest-profil.pdf")
check("  and zodiac30's is named exactly as it always was",
      reports._words(reports.ZODIAC_PROFILE)["pdf_filename"] % "celestial-air"
      == "mazzin-celestial-air-report.pdf")

print("\n--- the fallbacks, in Romanian ---")
# What a reader gets when generation fails outright. These were the English
# set, on the reasoning that a publishable English section beats an absent
# one — true of an absent section, and false of the page that shipped.
check("the profile carries its own stubs",
      profile["stubs"] is reports.ZODIAC_STUBS_RO
      and profile["stubs"] is not reports.ZODIAC_STUBS)
check("  and the English funnels still carry theirs",
      reports.ZODIAC_PROFILE["stubs"] is reports.ZODIAC_STUBS
      and reports.KITCHEN_PROFILE["stubs"] is reports.STUBS)
check("  the same six sections as the twin",
      sorted(reports.ZODIAC_STUBS_RO) == sorted(reports.ZODIAC_STUBS),
      str(sorted(set(reports.ZODIAC_STUBS) ^ set(reports.ZODIAC_STUBS_RO))))


def stub_strings(node):
    if isinstance(node, str):
        yield node
    elif isinstance(node, dict):
        for value in node.values():
            for item in stub_strings(value):
                yield item
    elif isinstance(node, list):
        for value in node:
            for item in stub_strings(value):
                yield item


# `verdict` is a machine value the renderer dispatches on and the stylesheet
# colours the badge with — "works" and "avoid" are English in every language,
# and the word the reader actually sees is the badge, which is translated.
# The year stub's twelve `name` values are positions, not prose: the labels
# are stamped on at build time out of the reader's own year, in whichever
# language the profile counts it in.
MACHINE = (set(reports.VERDICTS) | {reports.FROM_CONFIG}
           | set(str(n) for n in range(1, 13)))
RO_STUB_STRINGS = [s for s in stub_strings(reports.ZODIAC_STUBS_RO)
                   if s not in MACHINE]
check("  every stub string is Romanian, not the English one",
      not [s for s in RO_STUB_STRINGS
           if s in list(stub_strings(reports.ZODIAC_STUBS))],
      str([s[:40] for s in RO_STUB_STRINGS
           if s in list(stub_strings(reports.ZODIAC_STUBS))][:3]))
LONG = [s for s in RO_STUB_STRINGS if len(s) > 40]
check("  and every long one carries diacritics",
      not [s for s in LONG if not DIACRITIC.search(s)],
      str([s[:50] for s in LONG if not DIACRITIC.search(s)][:3]))
check("  none of them says a banned thing, in either language",
      not [(s[:40], reports._banned_hit(s, reports.ZODIAC_RO_BANNED))
           for s in RO_STUB_STRINGS
           if reports._banned_hit(s, reports.ZODIAC_RO_BANNED)],
      str([s[:40] for s in RO_STUB_STRINGS
           if reports._banned_hit(s, reports.ZODIAC_RO_BANNED)][:3]))
# Section for section against the English set rather than against a flat
# "must validate": two of the six are templates that only become a section at
# build time — the palette takes its colours off the config and the year map
# takes its labels off the clock — and both sets are equally unfinished until
# `_stub_for` runs.


def validates(stubs):
    return dict((section_id,
                 reports.VALIDATORS[section_id](
                     reports._fill(stubs[section_id], "X")) is not None)
                for section_id in stubs)


check("  and each one validates exactly where the English one does",
      validates(reports.ZODIAC_STUBS_RO) == validates(reports.ZODIAC_STUBS),
      str([s for s, ok in validates(reports.ZODIAC_STUBS_RO).items()
           if ok != validates(reports.ZODIAC_STUBS)[s]]))
check("  the palette stub still takes its colours from the config",
      reports.ZODIAC_STUBS_RO["palette"]["colors"] == reports.FROM_CONFIG)
check("  the swatch prose under them is Romanian too",
      len(reports.ZODIAC_COLOR_TEXT_RO) == len(reports.ZODIAC_COLOR_TEXT)
      and all(DIACRITIC.search(" ".join(row))
              for row in reports.ZODIAC_COLOR_TEXT_RO))
check("  and the profile hands it over",
      profile["stub_colors"] is reports.ZODIAC_COLOR_TEXT_RO
      and reports.ZODIAC_PROFILE.get("stub_colors") is None)

ro_style = reports._style(cfg, "celestial_air")
ro_months = reports._months_for(profile)
palette = reports._stub_for("palette", reports._style_name(cfg,
                                                           "celestial_air"),
                            ro_style, profile["stubs"], ro_months,
                            profile["stub_colors"])
check("a built palette stub keeps the reader's own colour NAMES",
      [(c["name"], c["hex"]) for c in palette["colors"]]
      == reports._style_colors(ro_style),
      str([c["name"] for c in palette["colors"]]))
check("  and says what each one is for in Romanian",
      all(DIACRITIC.search(c["role"] + c["finish"] + c["where"])
          for c in palette["colors"]))
en_palette = reports._stub_for("palette", "Celestial Air",
                               reports._style(twin, "celestial_air"),
                               reports.ZODIAC_STUBS)
check("  where the English stub still says it in English",
      not DIACRITIC.search("".join(c["role"] + c["finish"] + c["where"]
                                   for c in en_palette["colors"])))
check("    and is the swatch prose zodiac30 has always printed",
      [(c["role"], c["finish"], c["where"]) for c in en_palette["colors"]]
      == [tuple(row) for row in reports.ZODIAC_COLOR_TEXT])

year = reports._stub_for("shopping", "X", ro_style, profile["stubs"],
                         ro_months, profile["stub_colors"])
notes = [i["priority_note"] for i in year["items"]]
check("the year stub is still stamped with the reader's twelve months",
      [i["name"] for i in year["items"]] == list(ro_months),
      str([i["name"] for i in year["items"]][:3]))
check("  and marks three months and one, in Romanian",
      sum(n.startswith(reports.RENDER_WORDS_RO["year_strong"])
          for n in notes) == reports.YEAR_STRONG
      and sum(n.startswith(reports.RENDER_WORDS_RO["year_quiet"])
              for n in notes) == reports.YEAR_QUIET,
      str([n[:30] for n in notes]))
check("  never with the English prefixes",
      not [n for n in notes
           if n.startswith(reports.RENDER_WORDS["year_strong"])
           or n.startswith(reports.RENDER_WORDS["year_quiet"])])

print("\n--- the year map is checked in the language it was asked for ---")
GOOD_RO = {"items": [
    {"name": m,
     "priority_note": (reports.RENDER_WORDS_RO["year_strong"] if i in (2, 5, 8)
                       else reports.RENDER_WORDS_RO["year_quiet"] if i == 7
                       else "Bună pentru") + " ceva anume."}
    for i, m in enumerate(ro_months)]}
BAD_EN = {"items": [
    {"name": m,
     "priority_note": (reports.RENDER_WORDS["year_strong"] if i in (2, 5, 8)
                       else reports.RENDER_WORDS["year_quiet"] if i == 7
                       else "Bună pentru") + " ceva anume."}
    for i, m in enumerate(ro_months)]}
check("the Romanian profile asks for the marks to be checked",
      profile.get("verify_marks") is True)
check("  and the English one does not — a check they never had is a "
      "section they can now lose",
      reports.ZODIAC_PROFILE.get("verify_marks") is None
      and reports.KITCHEN_PROFILE.get("verify_marks") is None)
marks = reports._year_marks(profile)
check("its marks are the two Romanian prefixes",
      marks == (reports.RENDER_WORDS_RO["year_strong"],
                reports.RENDER_WORDS_RO["year_quiet"]), str(marks))
check("  and the twin's are the two English ones",
      reports._year_marks(reports.ZODIAC_PROFILE)
      == ("Strongest month:", "Quiet month:"),
      str(reports._year_marks(reports.ZODIAC_PROFILE)))
check("a Romanian year map marked in Romanian is accepted",
      reports._verify_months(GOOD_RO, ro_months, marks) is None,
      str(reports._verify_months(GOOD_RO, ro_months, marks)))
check("  the same map marked in English is refused",
      reports._verify_months(BAD_EN, ro_months, marks) is not None,
      str(reports._verify_months(BAD_EN, ro_months, marks)))
check("  and so is one that marks the wrong number of months",
      reports._verify_months(
          {"items": [{"name": m, "priority_note": "Bună."}
                     for m in ro_months]}, ro_months, marks) is not None)
check("without marks the check is exactly what it always was",
      reports._verify_months(BAD_EN, ro_months) is None
      and reports._verify_months(GOOD_RO, ro_months) is None)
check("  and the month names are still policed first",
      reports._verify_months(
          {"items": [{"name": m} for m in reports._year_labels()]},
          ro_months, marks) is not None)
ro_verify = reports._verify_for(profile, ro_style, ro_months)
en_verify = reports._verify_for(reports.ZODIAC_PROFILE,
                                reports._style(twin, "celestial_air"),
                                reports._year_labels())
check("the purchase path's check refuses an English-marked Romanian year",
      ro_verify(("shopping",), {"shopping": BAD_EN}) is not None)
check("  accepts the Romanian-marked one",
      ro_verify(("shopping",), {"shopping": GOOD_RO}) is None,
      str(ro_verify(("shopping",), {"shopping": GOOD_RO})))
check("  and zodiac30's check still asks nothing about marks",
      en_verify(("shopping",),
                {"shopping": {"items": [{"name": m, "priority_note": "x"}
                                        for m in reports._year_labels()]}})
      is None)

print("\n--- and the twins are untouched ---")
# The failure this funnel could cause and no assertion above would see: a
# string edited on the way past, on a config that is live and in English.
check("funnels/zodiac30.json is still zodiac30",
      twin["slug"] == "zodiac30" and twin["funnel_id"] == "zodiac30_v1"
      and twin["locale"] == "en"
      and len(twin["swipe"]["steps"]) == twin["swipe"]["pairs_count"] == 18)
check("  still counting eighteen choices",
      twin["checkout"]["proof_line"] == "Built from your 18 choices",
      twin["checkout"]["proof_line"])
check("  and its static copy still matches it",
      twin == json.load(open(os.path.join(ROOT,
                                          "static/funnels/zodiac30.json"))))
check("funnels/zodiac.json is still zodiac",
      english["slug"] == "zodiac" and english["funnel_id"] == "zodiac_v1"
      and english["locale"] == "en"
      and len(english["swipe"]["steps"])
      == english["swipe"]["pairs_count"] == 12)
check("  still three interstitials, anchored 4/7/10",
      [i["after_step"] for i in english["interstitials"]] == [4, 7, 10],
      str([i["after_step"] for i in english["interstitials"]]))
check("  and its static copy still matches it",
      english == json.load(open(os.path.join(ROOT,
                                             "static/funnels/zodiac.json"))))
check("neither of them carries a Romanian diacritic",
      not DIACRITIC.search(open(
          os.path.join(ROOT, "funnels/zodiac30.json"), encoding="utf-8").read())
      and not DIACRITIC.search(open(
          os.path.join(ROOT, "funnels/zodiac.json"), encoding="utf-8").read()))

print("\n%d checks, %d failed" % (checks[0], len(fails)))
for f in fails:
    print("  FAIL " + f)
sys.exit(1 if fails else 0)
