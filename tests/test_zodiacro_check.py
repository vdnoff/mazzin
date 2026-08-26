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
# FORCED TEST EDIT (1 of 1). The parity check below compares this funnel's
# whole shape against zodiac30's, and this funnel now legitimately carries
# keys zodiac30 does not: the localization layer. Every one of them is
# OPTIONAL in the two JS files — a funnel that declares none renders the
# English it always did, which the English-default block further down proves
# against the sources themselves. So the comparison drops them rather than
# being weakened: everything outside this list is still pinned to the twin,
# key for key and value for value.
ADDED = ("delivery_line", "delivery_line_bare", "labels")
ADDED_BLOCKS = {
    "checkout": ("unlock_note", "number_words", "redirecting",
                 "error_checkout", "error_payment", "error_consent"),
    "report": ("preparing", "locked_aria"),
    "swipe": ("card_aria",),
}


def without_added(config):
    """The config with the optional localization keys taken back off."""
    out = dict(config)
    for block, keys in ADDED_BLOCKS.items():
        if block in out:
            out[block] = {k: v for k, v in out[block].items() if k not in keys}
    return out


def comparable(config):
    """The config with the known differences normalised away.

    `sign_cross` is a lookup keyed on the sign LABEL — both readers of it,
    result_zodiac.js and reports.py, ask for `sign_cross[<the label they
    tapped>][<element>] — so its twelve keys move with the twelve cards or
    every reader of this funnel gets a blank cross line. "cusp" is a literal
    in both and does not move. Compared by position, in the order the sign
    grid lists them.
    """
    out = without_added(config)
    # The price is this funnel's own now — 199 against the English 300 — and
    # `shape` keeps numbers, so it would read as drift. Normalised away here
    # and pinned on its own account below, at "pricing is 199 usd", together
    # with the assertion that the English twins are still at 300. This is the
    # one number the two funnels are allowed to disagree on; everything else
    # numeric stays compared.
    out["pricing"] = dict(out["pricing"], amount_cents="priced")
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
# `cta` is copy and is translated like every other string; `currency` is not
# copy and has to match, or two funnels selling the same thing would be
# charging in different money. So the amount is the ONE thing left that the
# two are allowed to differ on numerically.
check("  and the price is the only number the two disagree on",
      shape(cfg["pricing"]) != shape(twin["pricing"])
      and shape(dict(cfg["pricing"], amount_cents=0))
      == shape(dict(twin["pricing"], amount_cents=0)),
      "%s vs %s" % (cfg["pricing"], twin["pricing"]))
check("    same keys, same currency, different amount",
      sorted(cfg["pricing"]) == sorted(twin["pricing"])
      and cfg["pricing"]["currency"] == twin["pricing"]["currency"] == "usd"
      and cfg["pricing"]["amount_cents"] != twin["pricing"]["amount_cents"],
      "%s vs %s" % (cfg["pricing"], twin["pricing"]))
check("  and sign_cross is keyed on this funnel's own twelve labels",
      [k for k in cfg["result_copy"]["profile"]["sign_cross"] if k != "cusp"]
      == [i["label"] for i in by_step["sign"]["pairs"][0]["images"]],
      str(list(cfg["result_copy"]["profile"]["sign_cross"])))
check("  with the cusp key untouched, because both readers spell it in code",
      "cusp" in cfg["result_copy"]["profile"]["sign_cross"]
      and len(cfg["result_copy"]["profile"]["sign_cross"]) == 13)
check("  and those three are the only keys result_copy adds",
      set(cfg["result_copy"]) - set(twin["result_copy"]) == set(ADDED),
      str(sorted(set(cfg["result_copy"]) ^ set(twin["result_copy"]))))
for block, keys in sorted(ADDED_BLOCKS.items()):
    check("  and %-8s adds only its optional strings" % block,
          set(cfg[block]) - set(twin[block]) == set(keys),
          str(sorted(set(cfg[block]) ^ set(twin[block]))))
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
# This funnel prices on its own now — 199 where the English three still
# charge 300 — so the shape comparison above stops at the shape and the
# amount is asserted here, on its own account.
check("pricing is 199 usd",
      cfg["pricing"]["amount_cents"] == 199
      and cfg["pricing"]["currency"] == "usd",
      str(cfg["pricing"]))
check("  integer cents, never a float or a formatted string",
      isinstance(cfg["pricing"]["amount_cents"], int)
      and not isinstance(cfg["pricing"]["amount_cents"], bool),
      repr(cfg["pricing"]["amount_cents"]))
check("  and the English funnels are untouched at 300",
      twin["pricing"]["amount_cents"] == english["pricing"]["amount_cents"]
      == 300,
      "%s / %s" % (twin["pricing"]["amount_cents"],
                   english["pricing"]["amount_cents"]))
check("  and it still transacts live",
      cfg["stripe_mode"] == "live", cfg["stripe_mode"])

print("\n--- one price, and every rendering of it comes from that field ---")
# The rule the paywall rests on: config carries an amount and a slot, never a
# spelled-out number. A price written into a sentence is a price that goes on
# saying 3.00 after the amount moves, on the one screen where being wrong
# costs the sale and the trust at once.
PRICEY = re.compile(r"\$\s?\d|\b\d+[.,]\d{2}\b|\b3[.,]00\b")
spelled = [(p, v) for p, v in STRINGS
           if PRICEY.search(v) and "75 $" not in v]
check("no string in the config spells a price out", not spelled,
      str(spelled[:4]))
check("  not the old one, in any spelling",
      not [(p, v) for p, v in STRINGS
           if re.search(r"\$\s?3\b|\b3[.,]00\b|\b300\b", v)],
      str([(p, v[:50]) for p, v in STRINGS
           if re.search(r"\$\s?3\b|\b3[.,]00\b|\b300\b", v)][:4]))
check("  and the raw file names 300 nowhere either",
      "300" not in RAW, RAW[max(0, RAW.find("300") - 40):RAW.find("300") + 20])
SLOTS = [(p, v) for p, v in STRINGS if "{price}" in v]
check("every line that names a price interpolates {price}",
      len(SLOTS) == 6, str(sorted(p for p, _v in SLOTS)))
check("  the CTA, the anchor and the sticky bar among them",
      all("{price}" in cfg["checkout"][k]
          for k in ("cta_label", "anchor", "anchor_head", "unlock_note"))
      and all("{price}" in cfg["checkout"]["commerce"][k]
              for k in ("anchor_head", "sticky_label")))


def short(cents, cur="USD"):
    """What engine.js formatPriceShort() prints for an amount."""
    amount = str(cents // 100) if cents % 100 == 0 else "%.2f" % (cents / 100.0)
    return {"USD": "$", "EUR": "€", "GBP": "£"}.get(cur, "") + amount


check("  which renders this amount as $1.99, cents and all",
      short(cfg["pricing"]["amount_cents"]) == "$1.99",
      short(cfg["pricing"]["amount_cents"]))
check("  where the English three still render as $3",
      short(twin["pricing"]["amount_cents"]) == "$3",
      short(twin["pricing"]["amount_cents"]))
# The anchor is a claim about what somebody else charges, not a multiple of
# what we charge, so it does not move with our price — and the English twins
# make the same claim, in the same figure.
check("the 75 $ anchor is left alone, and says the same as the twin's",
      cfg["checkout"]["anchor"].count("75 $") == 1
      and twin["checkout"]["anchor"].count("$75") == 1,
      cfg["checkout"]["anchor"])
check("  and it is the only figure the copy states outright",
      sorted(set(re.findall(r"\d+", " ".join(
          v for _p, v in STRINGS if "$" in v)))) == ["75"],
      str(sorted(set(re.findall(r"\d+", " ".join(
          v for _p, v in STRINGS if "$" in v))))))

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

print("\n--- register: a blend of signs is a combinație ---")
# "încrucișare" is what a geneticist calls a cross. Romanian astrology writing
# calls a blend of signs or energies a "combinație", which is also what this
# config's own rarity line has always called it — so thirteen lines saying
# otherwise were both off-register and arguing with the line beside them.
#
# The stem rather than one inflection: încrucișare, încrucișări, Încrucișăm
# and the diacritic-stripped spellings all have to stay out, or the clinical
# word comes back in a form this check cannot see.
CLINICAL = re.compile(r"[îiÎI]ncruci[sș]", re.IGNORECASE)
clinical = [(p, v) for p, v in STRINGS if CLINICAL.search(v)]
check("no line in the config says it", not clinical,
      str([(p, v[:60]) for p, v in clinical[:4]]))
check("  not in the raw file either, keys included", not CLINICAL.search(RAW))
check("  nor in the twin, which is generated from it",
      not CLINICAL.search(open(
          os.path.join(ROOT, "funnels/zodiac-ro-test.json"),
          encoding="utf-8").read()))
# The positive half. A sign_cross line describes a blend only where the
# element differs from the sign's own: the twelve same-element lines say
# "zodia în stare pură" and the four cusp lines have their own opening, and
# neither is a blend to name. Every line that IS one now names it with the
# same noun the rarity line beside it has always used.
CROSS = cfg["result_copy"]["profile"]["sign_cross"]
lines = [v for row in CROSS.values() for v in row.values()]
# Three tiers, and the change touched only the noun in front of them. The
# adjective is what says how rare a blend is; flattening neobișnuită / rară /
# autentică into one word would have cost the product a distinction it sells.
TIERS = ("combinație autentică", "combinație neobișnuită", "combinație rară")
blend = [v for v in lines if "combinație" in v]
plain = [v for v in lines if "combinație" not in v]
check("every blend line calls it a combinație", len(blend) == 36,
      "%d of %d" % (len(blend), len(lines)))
check("  and each carries exactly one of the three tiers",
      all(sum(t in v for t in TIERS) == 1 for v in blend),
      str([v[:60] for v in blend if sum(t in v for t in TIERS) != 1][:3]))
check("  all three tiers survived the swap",
      all(sum(t in v for v in blend) for t in TIERS),
      str({t: sum(t in v for v in blend) for t in TIERS}))
check("  twelve of them are the tier that was reworded",
      sum(TIERS[0] in v for v in blend) == 12,
      str(sum(TIERS[0] in v for v in blend)))
check("  the rarity line says the same word",
      "combinație" in cfg["result_copy"]["profile"]["rarity_line"],
      cfg["result_copy"]["profile"]["rarity_line"])
check("the sixteen that name no blend are the same-element and cusp lines",
      len(plain) == 16
      and sum("zodia în stare pură" in v for v in plain) == 12
      and len(CROSS["cusp"]) == 4,
      str([v[:50] for v in plain
           if "zodia în stare pură" not in v and "Cumpăna" not in v]))
check("  and none of them ever said it either",
      not [v for v in plain if CLINICAL.search(v)])
check("the loading line is reworded rather than swapped",
      "Împletim" in cfg["report"]["generating_messages"][2]
      and not CLINICAL.search(cfg["report"]["generating_messages"][2]),
      cfg["report"]["generating_messages"][2])
check("  because the message before it already opens on that root",
      "combinațiile" in cfg["report"]["generating_messages"][1]
      and "Combinăm" not in cfg["report"]["generating_messages"][2],
      cfg["report"]["generating_messages"][1])
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
# The other half of the register check. The config is scanned above; this is
# everything Romanian the module writes on its own account — the prompts, the
# shapes, the stubs, the mail, the PDF's furniture and the swatch prose.
# Serialised in one blob rather than walked, so a Romanian string added to any
# of these objects later is scanned without this list being extended.
RO_WRITTEN = json.dumps([
    reports.ZODIAC_RO_SYSTEM, reports.ZODIAC_RO_SPEC,
    reports.ZODIAC_RO_JSON_RULE, reports.ZODIAC_RO_JSON_RETRY,
    reports.ZODIAC_STUBS_RO, reports.ZODIAC_COLOR_TEXT_RO,
    reports.RENDER_WORDS_RO, reports.COPY_ZODIAC_RO,
    reports.COMPATIBILITY_RO, reports.PDF_ELEMENTS_RO,
    reports.ZODIAC_EMAIL_LINK_RO,
    dict((k, v) for k, v in reports.ZODIAC_RO_PROFILE.items()
         if isinstance(v, str)),
    reports._email_opening({"funnel": "zodiac-ro"}),
], ensure_ascii=False, default=str)
check("and no Romanian string it writes itself says it either",
      not CLINICAL.search(RO_WRITTEN),
      str(CLINICAL.findall(RO_WRITTEN)[:4]))
check("  which is a real body of Romanian, not an empty scan",
      len(DIACRITIC.findall(RO_WRITTEN)) > 500,
      "%d accented characters" % len(DIACRITIC.findall(RO_WRITTEN)))

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

# The bug a sandbox purchase on sign Rac delivered: four pairings, and the
# one draining sign named twice under two different paragraphs. The table
# names three signs — two magnetic and one draining — the shape asks for
# four rows, and the fourth was the model's own choice with nothing saying it
# had to be a sign it had not used. The verdict count was satisfied: two
# `works` and two `avoid` is exactly what came back.
rac = ["sign_cancer" if step["id"] == "sign"
       else step["pairs"][0]["images"][0]["id"] for step in steps]
block = reports._compat_block(cfg, rac, table)
check("a Rac is handed three signs, not four",
      sorted(s for s in table if re.search(r"\b%s\b" % s, block))
      == sorted(["Rac", "Scorpion", "Pești", "Berbec"]),
      str(sorted(s for s in table if re.search(r"\b%s\b" % s, block))))
check("  so the prompt says the fourth is a second drain and a new sign",
      "SECOND draining" in block and "four DIFFERENT signs" in block,
      block[-220:])


def love(*combos):
    """One materials section, its four pairings named as given."""
    verdicts = ["works", "works", "avoid", "avoid"]
    return {"materials": {
        "intro": "x" * 40, "rule": "r" * 40,
        "pairs": [{"combo": c, "verdict": v, "why": "y" * 40}
                  for c, v in zip(combos, verdicts)]}}


DELIVERED = love("Rac + Scorpion", "Rac + Pești",
                 "Rac + Berbec", "Rac + Berbec")
CORRECT = love("Rac + Scorpion", "Rac + Pești",
               "Rac + Berbec", "Rac + Capricorn")
ro_verify = reports._verify_for(profile, reports._style(cfg, "deep_water"),
                                reports._months_for(profile))
check("the section that shipped is refused now",
      ro_verify(("materials",), DELIVERED) is not None,
      str(ro_verify(("materials",), DELIVERED)))
check("  the refusal names Berbec, and not the reader's own sign",
      "Berbec" in (ro_verify(("materials",), DELIVERED) or "")
      and "Rac" not in (ro_verify(("materials",), DELIVERED) or ""),
      str(ro_verify(("materials",), DELIVERED)))
check("  four distinct Romanian signs pass",
      ro_verify(("materials",), CORRECT) is None,
      str(ro_verify(("materials",), CORRECT)))
check("  the old verdict count alone would have waved it through",
      sorted(p["verdict"] for p in DELIVERED["materials"]["pairs"])
      == ["avoid", "avoid", "works", "works"]
      and reports._v_materials(DELIVERED["materials"]) is not None)
check("  the check reads the twelve names off this funnel's own table",
      sorted(table) == sorted(signs))
check("  and a diacritic sign name is matched whole, not by substring",
      reports._verify_pairs(
          {"pairs": [{"combo": "Rac + Pești"},
                     {"combo": "Rac + Săgetător"}]}, tuple(table)) is None)
check("the Romanian stub still passes it",
      ro_verify(("materials",), {"materials": reports._fill(
          reports.ZODIAC_STUBS_RO["materials"], "X")}) is None)

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
      and "$1.99" in reports._email_opening({"funnel": "zodiac-ro"}),
      reports._email_opening({"funnel": "zodiac-ro"}))
check("  read off the funnel rather than written into the mail",
      reports._price_paid({"funnel": "zodiac-ro"}) == "$1.99"
      and reports._price_paid({"funnel": "zodiac30"}) == "$3",
      "%s / %s" % (reports._price_paid({"funnel": "zodiac-ro"}),
                   reports._price_paid({"funnel": "zodiac30"})))
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

print("\n--- the words the page prints, and the words the PDF prints ---")
# The free and delivered pages carried element names, energy names, month
# abbreviations, the verdict badges and two headings in English no matter what
# the funnel sold in — they were literals in static/js/result_zodiac.js. They
# are `result_copy.labels` now, and the whole point is that the page and the
# document agree: a reader who saw MERGE on the page and WORKS in the PDF has
# been handed two documents about themselves.
LABELS = cfg["result_copy"]["labels"]
check("the funnel declares its own page labels", isinstance(LABELS, dict))
for key in ("elements", "energies", "led_template", "months", "verdicts",
            "saves_head", "scale_aria"):
    check("  labels.%-13s is filled" % key, bool(LABELS.get(key)),
          repr(LABELS.get(key)))

check("elements are reports.py's, exactly",
      LABELS["elements"] == reports.ELEMENT_LABEL_RO,
      "%s vs %s" % (LABELS["elements"], reports.ELEMENT_LABEL_RO))
check("energies are reports.py's, exactly",
      LABELS["energies"] == reports.ENERGY_LABEL_RO,
      "%s vs %s" % (LABELS["energies"], reports.ENERGY_LABEL_RO))
check("verdict badges are reports.py's, exactly",
      LABELS["verdicts"] == reports.RENDER_WORDS_RO["verdicts"],
      "%s vs %s" % (LABELS["verdicts"], reports.RENDER_WORDS_RO["verdicts"]))
check("months are reports.py's twelve, in order",
      LABELS["months"] == list(reports.MONTH_ABBR_RO), str(LABELS["months"]))
check("  and none of them is an English month",
      not set(LABELS["months"]) & set(reports.MONTH_ABBR))
check("the saves heading reuses the PDF's own word",
      reports.RENDER_WORDS_RO["save"].lower()[:5] in LABELS["saves_head"].lower(),
      "%s vs %s" % (LABELS["saves_head"], reports.RENDER_WORDS_RO["save"]))
check("  and it is not the English heading",
      LABELS["saves_head"] != "Where to stop spending it")
check("the two templates keep their tokens",
      "{energy}" in LABELS["led_template"]
      and all(t in LABELS["scale_aria"]
              for t in ("{left}", "{right}", "{at}")),
      "%s | %s" % (LABELS["led_template"], LABELS["scale_aria"]))
check("  and neither is still the English one",
      LABELS["led_template"] != "{energy}-led"
      and "out of 100 toward" not in LABELS["scale_aria"])

print("\n--- engine.js's own furniture ---")
ENGINE_KEYS = [("checkout", "unlock_note"), ("checkout", "redirecting"),
               ("checkout", "error_checkout"), ("checkout", "error_payment"),
               ("checkout", "error_consent"), ("report", "preparing"),
               ("report", "locked_aria"), ("swipe", "card_aria")]
for block, key in ENGINE_KEYS:
    value = cfg[block].get(key)
    check("  %s.%-15s is filled" % (block, key), bool(value), repr(value))
check("the unlock note keeps both its tokens",
      "{n}" in cfg["checkout"]["unlock_note"]
      and "{price}" in cfg["checkout"]["unlock_note"],
      cfg["checkout"]["unlock_note"])
check("  and counts in Romanian words, not English ones",
      cfg["checkout"]["number_words"][6] == "șase"
      and len(cfg["checkout"]["number_words"]) == 11,
      str(cfg["checkout"]["number_words"]))
check("the card label keeps its token", "{label}" in cfg["swipe"]["card_aria"])
# "Blocat" and "Alege" are Romanian words that happen to carry no diacritic;
# requiring one on every string would be requiring a spelling mistake.
NO_DIACRITIC = ("locked_aria", "card_aria")
check("every new string carries its diacritics where Romanian has them",
      all(DIACRITIC.search(cfg[b][k]) for b, k in ENGINE_KEYS
          if k not in NO_DIACRITIC),
      str([k for b, k in ENGINE_KEYS
           if k not in NO_DIACRITIC and not DIACRITIC.search(cfg[b][k])]))
check("  and the two that do not are Romanian all the same",
      cfg["report"]["locked_aria"] != "Locked"
      and cfg["swipe"]["card_aria"] != "Choose {label}",
      "%s | %s" % (cfg["report"]["locked_aria"], cfg["swipe"]["card_aria"]))
check("  and none of them was left in English",
      not any(v in (
          "Redirecting...", "Preparing your personalized report\u2026",
          "Locked", "Choose {label}",
          "Could not start checkout. Please try again.",
          "That payment didn't go through. Please try again.",
          "Please tick the box above to continue.")
          for v in (cfg[b][k] for b, k in ENGINE_KEYS)))

print("\n--- a funnel that declares none of it renders English ---")
# The guarantee the other three funnels rest on. Asserted two ways: they
# declare nothing, and the English every default falls back to is still in
# the file, character for character.
JS = os.path.join(ROOT, "static", "js")
ENGINE_JS = open(os.path.join(JS, "engine.js"), encoding="utf-8").read()
RESULT_JS = open(os.path.join(JS, "result_zodiac.js"), encoding="utf-8").read()
for slug in ("kitchen", "kitchen-visualizer", "zodiac", "zodiac30"):
    other = json.load(open(os.path.join(ROOT, "funnels", slug + ".json"),
                           encoding="utf-8"))
    declared = [k for k in ("labels",)
                if k in (other.get("result_copy") or {})]
    declared += ["%s.%s" % (b, k) for b, k in ENGINE_KEYS
                 if k in (other.get(b) or {})]
    declared += [k for k in ("number_words",) if k in (other.get("checkout") or {})]
    check("  %-18s declares none of the new keys" % slug, not declared,
          str(declared))
ENGLISH = [
    (ENGINE_JS, r'"Unlock all {n} sections \u00B7 {price}"'),
    (ENGINE_JS, r'"Preparing your personalized report\u2026"'),
    (ENGINE_JS, '"Redirecting..."'),
    (ENGINE_JS, '"Could not start checkout. Please try again."'),
    (ENGINE_JS, '"That payment didn\'t go through. Please try again."'),
    (ENGINE_JS, '"Please tick the box above to continue."'),
    (ENGINE_JS, '"Choose {label}"'),
    (ENGINE_JS, 'words("report.locked_aria", "Locked")'),
    (RESULT_JS, '"Where to stop spending it"'),
    (RESULT_JS, '"{energy}-led"'),
    (RESULT_JS, '"{left} to {right} — {at} out of 100 toward {right}"'),
    (RESULT_JS, 'fire: "Fire"'),
    (RESULT_JS, '{ sun: "Sun", moon: "Moon" }'),
    (RESULT_JS, '"Jan", "Feb", "Mar"'),
]
for source, literal in ENGLISH:
    check("  default still in the file: %s" % literal[:44],
          literal in source, literal)
check("the verdict badge still uppercases the tag when nothing is declared",
      'mark.toUpperCase()' in RESULT_JS)
check("every delivered body builder is handed the run it renders for",
      "build(section.data, ctx)" in RESULT_JS
      and "function compatibility(data, ctx)" in RESULT_JS
      and "function career(data, ctx)" in RESULT_JS)
check("  and the CSS classes stayed English, as the stylesheet expects",
      '"zr-tag is-" + (mark || "works")' in RESULT_JS)

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
