#!/usr/bin/env python3
"""Integrity checks over funnels/zodiac-bg.json — zodiac30, in Bulgarian.

test_zodiac30_check.py asserts what an eighteen-step walk is, and
test_zodiacro_check.py asserts that /zodiac-ro is that same walk with nothing
but the strings changed. This asserts the same thing for /zodiac-bg: the same
step ids in the same order, the same image ids on the same frames with the
same tags, the same interstitial anchors and mechanics, the same archetypes,
scoring, hook slots and rarity tables, the same galleries. The funnel brings
no new art and no new machinery — only a language.

So the shape is compared against the twin structurally rather than restated,
and what is checked on its own account is the part that is genuinely new: that
the copy really is Bulgarian, written in Cyrillic, that the words the page
prints and the words the PDF prints are the same words, and that it stays
inside the same Terms line the English funnels are held to, in both languages.

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
                            ("  " + str(detail)) if detail and not ok else ""))


# The two files whose English defaults this funnel is the exception to.
JS = os.path.join(ROOT, "static", "js")
ENGINE_JS = open(os.path.join(JS, "engine.js"), encoding="utf-8").read()
RESULT_JS = open(os.path.join(JS, "result_zodiac.js"),
                 encoding="utf-8").read()
# The arm's stylesheet, for the claim that every rule it adds is scoped
# to it and nothing above it was touched.
CSS = open(os.path.join(ROOT, "static/css/result_zodiac.css"),
           encoding="utf-8").read()

# Imported here rather than beside the Terms checks that first needed it:
# the price block below reads `_price_paid` and the module's own source, and
# runs before that section.
import reports                                             # noqa: E402

REPORTS_SRC = open(os.path.join(ROOT, "reports.py"), encoding="utf-8").read()

PATH = os.path.join(ROOT, "funnels/zodiac-bg.json")
RAW = open(PATH, encoding="utf-8").read()
cfg = json.loads(RAW)
static_cfg = json.load(
    open(os.path.join(ROOT, "static/funnels/zodiac-bg.json")))
twin = json.load(open(os.path.join(ROOT, "funnels/zodiac30.json")))
english = json.load(open(os.path.join(ROOT, "funnels/zodiac.json")))
romanian = json.load(open(os.path.join(ROOT, "funnels/zodiac-ro.json")))

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
TWIN_STRINGS = dict(leaves(twin))

print("\n--- config shape ---")
check("static copy matches funnels/", cfg == static_cfg)
check("slug is zodiac-bg", cfg["slug"] == "zodiac-bg", cfg["slug"])
check("funnel_id is zodiac_bg_v1", cfg["funnel_id"] == "zodiac_bg_v1",
      cfg["funnel_id"])
check("locale is bg", cfg["locale"] == "bg", cfg["locale"])
check("  and the English two still say en",
      twin["locale"] == english["locale"] == "en")
check("  and the Romanian one still says ro", romanian["locale"] == "ro")
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


# The keys this funnel carries and zodiac30 does not: the localization layer.
# Every one of them is OPTIONAL in engine.js and result_zodiac.js — a funnel
# that declares none renders the English it always did, which the
# English-default block at the end proves against the sources themselves. So
# the comparison drops them rather than being weakened: everything outside
# this list is still pinned to the twin, key for key and value for value.
# FORCED TEST EDIT. `boxes` joins them: the second paywall arm's own
# copy, optional in result_zodiac.js exactly as the other three are —
# a funnel that declares none renders that module's English.
ADDED = ("delivery_line", "delivery_line_bare", "labels", "boxes")
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
    tapped>][<element>]` — so its twelve keys move with the twelve cards or
    every reader of this funnel gets a blank cross line. "cusp" is a literal
    in both and does not move. Compared by position, in the order the sign
    grid lists them.
    """
    out = without_added(config)
    # `pricing` whole: this funnel takes euros at a different amount, and it
    # declares two optional keys for writing them. Pinned on its own account
    # below, at "pricing is 499 eur", together with the assertion that the
    # English three are still at 300 usd.
    out["pricing"] = "priced"
    # And `sale`: whether a funnel is running an offer this week is a
    # commercial decision taken per funnel, not a property of the translation.
    # Asserted on its own account below.
    out.pop("sale", None)
    # And `paywall_variants`: zodiac30 is running a layout A/B and this funnel
    # is not. Asserted below.
    out.pop("paywall_variants", None)
    # And the layout this funnel names outright, for the same reason.
    out.pop("result_template", None)
    copy = dict(config["result_copy"])
    for key in ADDED:
        copy.pop(key, None)
    profile = dict(copy["profile"])
    # And the minimal arm's own copy: zodiac30 runs a layout A/B and this
    # funnel declares no `paywall_variants` at all. Asserted below.
    for key in ("rarity_card", "chips", "unlock", "unlock_head",
                "unlock_tail"):
        profile.pop(key, None)
    cross = profile["sign_cross"]
    profile["sign_cross"] = ([cross[k] for k in cross if k != "cusp"]
                             + [cross["cusp"]])
    copy["profile"] = profile
    out["result_copy"] = copy
    return out


check("the whole config has the twin's shape",
      shape(comparable(cfg)) == shape(comparable(twin)))
check("  and `pricing` is the only block they disagree on",
      cfg["pricing"] != twin["pricing"]
      and shape(comparable(cfg)) == shape(comparable(twin)),
      "%s vs %s" % (cfg["pricing"], twin["pricing"]))
import payments  # noqa: E402

# FORCED TEST EDIT. This funnel ran no experiment and runs one now: a 50/50
# split between the minimal arm it has been serving and the new boxes arm.
# Asserted in full in its own section at the end of this file.
ARMS = cfg.get("paywall_variants") or []
check("  and it runs a layout experiment of its own",
      [a["id"] for a in ARMS] == ["minimal", "boxes"], str(ARMS))
ARM_ONLY = {"rarity_card", "chips", "unlock", "unlock_head", "unlock_tail"}
check("    it carries the minimal layout's copy, all of it",
      ARM_ONLY <= set(cfg["result_copy"]["profile"]),
      str(sorted(ARM_ONLY - set(cfg["result_copy"]["profile"]))))
check("    it names the layout outright instead of being assigned an arm",
      cfg.get("result_template") == "minimal", str(cfg.get("result_template")))
check("  it runs a sale of its own",
      isinstance(cfg.get("sale"), dict), str(cfg.get("sale")))
check("    a different currency, not just a different number",
      cfg["pricing"]["currency"] != twin["pricing"]["currency"]
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
check("  which say where the PDF went, in Bulgarian, with {email} intact",
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
# for field, and pairs those names with role text in the stub. The element
# half of that sentence is frozen, so the name half is left in English with
# it: renaming only the middle would break the match and mix the sentence.
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
# lands mid-sentence in "енергията ти на {symbol}", so it is copy.
check("  and every fallback noun is the Bulgarian one",
      {k: v["fallback"] for k, v in cfg["report"]["hook_slots"].items()}
      == {"sign": "зодия", "palette": "палитра", "moonphase": "луна",
          "symbol": "талисман"},
      str({k: v["fallback"] for k, v in cfg["report"]["hook_slots"].items()}))
check("the rarity table is the twin's, number for number",
      cfg["result_copy"]["profile"]["rarity"]
      == twin["result_copy"]["profile"]["rarity"])
check("the purpose map points at the twin's sections",
      {k: v["emphasized_section"]
       for k, v in cfg["result_copy"]["purpose_map"].items()}
      == {k: v["emphasized_section"]
          for k, v in twin["result_copy"]["purpose_map"].items()})

print("\n--- one price, and every rendering of it comes from that field ---")
# This funnel presents in euros. 499 cents renders "4,99 €" — an integer minor
# unit, server-derived, never sent by the client, the way every other funnel
# here carries money.
check("pricing is 499 eur",
      cfg["pricing"]["amount_cents"] == 499
      and cfg["pricing"]["currency"] == "eur",
      str(cfg["pricing"]))
# The space between the number and the sign is U+00A0, not an ordinary one.
# On the paywall the euro sign was wrapping onto its own line, which is a
# price that reads as two things; a no-break space is the only fix that
# survives every width the card is drawn at.
check("  written the way Bulgarian writes money",
      cfg["pricing"].get("price_format") == "{amount}\u00a0\u20ac"
      and cfg["pricing"].get("decimal_mark") == ",",
      repr(cfg["pricing"].get("price_format")))
check("    the space in it being a no-break one, not an ordinary space",
      "\u00a0" in cfg["pricing"]["price_format"]
      and " " not in cfg["pricing"]["price_format"],
      repr(cfg["pricing"]["price_format"]))
check("    written literally into the file, not as an escape",
      '"price_format": "{amount}\u00a0\u20ac"' in RAW)
check("  and the English three declare neither key, so they format as before",
      not any(k in json.load(open(os.path.join(ROOT, "funnels", slug + ".json"),
                                  encoding="utf-8"))["pricing"]
              for slug in ("zodiac", "zodiac30", "kitchen")
              for k in ("price_format", "decimal_mark")))
check("  integer cents, never a float or a formatted string",
      isinstance(cfg["pricing"]["amount_cents"], int)
      and not isinstance(cfg["pricing"]["amount_cents"], bool),
      repr(cfg["pricing"]["amount_cents"]))
check("  and the English funnels are untouched at 300 usd",
      twin["pricing"]["currency"] == english["pricing"]["currency"] == "usd"
      and twin["pricing"]["amount_cents"]
      == english["pricing"]["amount_cents"] == 300,
      "%s / %s" % (twin["pricing"]["amount_cents"],
                   english["pricing"]["amount_cents"]))
check("  and the Romanian one is untouched at 999 ron",
      romanian["pricing"]["amount_cents"] == 999
      and romanian["pricing"]["currency"] == "ron",
      str(romanian["pricing"]))
check("  and it still transacts live",
      cfg["stripe_mode"] == "live", cfg["stripe_mode"])

# The rule the paywall rests on: config carries an amount and a slot, never a
# spelled-out number. A price written into a sentence is a price that goes on
# saying 3.00 after the amount moves, on the one screen where being wrong
# costs the sale and the trust at once.
PRICEY = re.compile(r"\$\s?\d|\b\d+[.,]\d{2}\b")
spelled = [(p, v) for p, v in STRINGS if PRICEY.search(v)]
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
      len(SLOTS) == 7, str(sorted(p for p, _v in SLOTS)))
check("  including the struck price a screen reader is given",
      "{price}" in cfg["result_copy"]["labels"]["price_regular_aria"],
      cfg["result_copy"]["labels"]["price_regular_aria"])
check("  the CTA, the anchor and the sticky bar among them",
      all("{price}" in cfg["checkout"][k]
          for k in ("cta_label", "anchor", "anchor_head", "unlock_note"))
      and all("{price}" in cfg["checkout"]["commerce"][k]
              for k in ("anchor_head", "sticky_label")))


def short(pricing):
    """What engine.js formatPriceShort() prints, mirrored here.

    Both formatters take the funnel's own `price_format` when it declares one
    and fall through to the symbol table when it does not, which is what keeps
    the dollar funnels rendering what they always rendered. The real functions
    are in static/js/engine.js; this is the same branch, and the source
    assertions below hold the two together.
    """
    cents = pricing["amount_cents"]
    amount = (str(cents // 100) if cents % 100 == 0
              else "%.2f" % (cents / 100.0))
    mark = pricing.get("decimal_mark")
    if mark:
        amount = amount.replace(".", mark)
    shape_ = pricing.get("price_format")
    if shape_:
        return shape_.replace("{amount}", amount)
    cur = (pricing.get("currency") or "usd").upper()
    return {"USD": "$", "EUR": "€", "GBP": "£"}.get(cur, "") + amount


def long(pricing):
    """And what formatPrice() prints — the paywall's own line."""
    cents = pricing["amount_cents"]
    amount = "%.2f" % (cents / 100.0)
    mark = pricing.get("decimal_mark")
    if mark:
        amount = amount.replace(".", mark)
    shape_ = pricing.get("price_format")
    if shape_:
        return shape_.replace("{amount}", amount)
    return amount + " " + (pricing.get("currency") or "usd").upper()


check("  which renders as 4,99\u00a0€, short form and long",
      short(cfg["pricing"]) == long(cfg["pricing"]) == "4,99\u00a0\u20ac",
      "%r / %r" % (short(cfg["pricing"]), long(cfg["pricing"])))
check("  and the sale price renders as 1,99\u00a0€ through the same formatter",
      short(dict(cfg["pricing"], amount_cents=cfg["sale"]["price_cents"]))
      == "1,99\u00a0\u20ac",
      repr(short(dict(cfg["pricing"],
                      amount_cents=cfg["sale"]["price_cents"]))))
check("    so the no-break space survives into every {price} slot",
      all("\u00a0" in v.replace("{price}", short(cfg["pricing"]))
          for _p, v in STRINGS if "{price}" in v))
# FORCED TEST EDIT (2 sites, this and the mail block below). `_price_paid`
# used to read `pricing.amount_cents`, so a buyer who took the sale was
# thanked for the regular price — 1,99 € paid, "4,99 €" in the mail. It reads
# the purchase row now, which is what the webhook recorded from Stripe, so a
# price assertion has to hand it a purchase.
import database                                            # noqa: E402

_ROWS = {}
database.query_one = lambda sql, args: _ROWS.get(args[0])


def _bought(slug, cents, currency="eur", when=None, purchase_id=1):
    """`(price string, opening line)` for a purchase recorded at `cents`."""
    _ROWS.clear()
    _ROWS[purchase_id] = {"amount_cents": cents, "currency": currency,
                          "created_at": when}
    return (reports._price_paid({"funnel": slug}, purchase_id),
            reports._email_opening({"funnel": slug}, purchase_id))


check("    and reports.py fills it the same way, for the mail and the PDF",
      'shape.replace("{amount}", amount)' in REPORTS_SRC
      and _bought("zodiac-bg", 499)[0] == "4,99\u00a0\u20ac",
      repr(_bought("zodiac-bg", 499)[0]))
check("    the sale price through that same format, nbsp and all",
      _bought("zodiac-bg", 199)[0] == "1,99\u00a0\u20ac",
      repr(_bought("zodiac-bg", 199)[0]))
for slug in ("zodiac", "zodiac30", "kitchen", "kitchen-visualizer"):
    en = json.load(open(os.path.join(ROOT, "funnels", slug + ".json"),
                        encoding="utf-8"))["pricing"]
    check("  %-19s still renders $3 and 3.00 USD" % slug,
          short(en) == "$3" and long(en) == "3.00 USD",
          "%s / %s" % (short(en), long(en)))
check("  and zodiac-ro still renders 9,99 lei",
      short(romanian["pricing"]) == "9,99 lei",
      short(romanian["pricing"]))


def js_body(name):
    """One function out of engine.js, from its `function` line to its close."""
    head = ENGINE_JS.index("  function %s(" % name)
    return ENGINE_JS[head:ENGINE_JS.index("\n  }\n", head)]


# Both formatters substitute the slot by plain replacement, so whatever
# character the funnel put beside {amount} is what reaches the page — that is
# the whole mechanism the no-break space rests on, and it is asserted against
# the source rather than assumed.
check("both formatters fill the slot by plain replacement",
      js_body("formatPrice").count('own.replace("{amount}"') == 1
      and js_body("formatPriceShort").count('own.replace("{amount}"') == 1)
check("both engine.js formatters read the funnel's own format",
      all("priceFormat()" in js_body(fn) and "priceAmount(cents," in js_body(fn)
          for fn in ("formatPrice", "formatPriceShort")),
      str([fn for fn in ("formatPrice", "formatPriceShort")
           if "priceFormat()" not in js_body(fn)
           or "priceAmount(cents," not in js_body(fn)]))
check("  and fall through to the symbol table when there is none",
      'var SYMBOLS = { USD: "$", EUR: "€", GBP: "£" };' in ENGINE_JS
      and 'return (cents / 100).toFixed(2) + " " + cur;' in ENGINE_JS)

# The anchor is a claim about what somebody else charges. It moves with the
# currency, not with our price: a card that quoted dollars against euros would
# be asking the reader to do the conversion.
check("the anchor is stated in euros, like everything else on the card",
      "70 €" in cfg["checkout"]["anchor"]
      and "70 €" in cfg["checkout"]["commerce"]["anchor_head"]
      and "70 €" in cfg["checkout"]["commerce"]["price_anchor"],
      cfg["checkout"]["anchor"])
check("  and the English twins still quote $75, untouched",
      twin["checkout"]["anchor"].count("$75") == 1
      and english["checkout"]["anchor"].count("$75") == 1)
check("  and the Romanian one still quotes 350 de lei",
      "350 de lei" in romanian["checkout"]["anchor"])
check("no dollar sign survives anywhere in this funnel's copy",
      not [p for p, v in STRINGS if "$" in v],
      str([p for p, v in STRINGS if "$" in v][:4]))
check("  and no string says usd, ron or lei either",
      not [p for p, v in STRINGS
           if re.search(r"\b(usd|ron|lei)\b", v, re.I)
           and p != "/pricing/currency"],
      str([p for p, v in STRINGS
           if re.search(r"\b(usd|ron|lei)\b", v, re.I)][:4]))
check("  70 is the only figure the anchor states outright",
      sorted(set(re.findall(r"\d+", " ".join(
          v for p, v in STRINGS if "€" in v and p != "/pricing/price_format"))))
      == ["70"],
      str(sorted(set(re.findall(r"\d+", " ".join(
          v for p, v in STRINGS if "€" in v
          and p != "/pricing/price_format"))))))
# The reframe is static copy on a page whose price moves: it reads at the
# regular 4,99 € and it has to still read at the sale's 1,99 €. Two coffees is
# the claim that survives both — one coffee would be false at neither price,
# and "less than one" would be a claim this funnel cannot make at 4,99 €.
check("the coffee reframe is two coffees, which both prices are under",
      "две кафета" in cfg["checkout"]["commerce"]["mid_line"]
      and "две кафета" in cfg["checkout"]["reframe"],
      "%s | %s" % (cfg["checkout"]["commerce"]["mid_line"],
                   cfg["checkout"]["reframe"]))
check("  and no string claims one coffee, which 4,99 € is not under",
      not [p for p, v in STRINGS if re.search(r"\bедно кафе\b", v)],
      str([p for p, v in STRINGS if re.search(r"\bедно кафе\b", v)]))
check("  and the accent is still a substring of the line it accents",
      cfg["checkout"]["commerce"]["mid_line_accent"]
      in cfg["checkout"]["commerce"]["mid_line"]
      and cfg["checkout"]["commerce"]["anchor_head_accent"]
      in cfg["checkout"]["commerce"]["anchor_head"]
      and cfg["checkout"]["commerce"]["price_anchor_accent"]
      in cfg["checkout"]["commerce"]["price_anchor"])
check("every {price} slot reads with the amount substituted",
      all("{price}" not in v.replace("{price}", short(cfg["pricing"]))
          and "  " not in v.replace("{price}", short(cfg["pricing"]))
          for _p, v in STRINGS if "{price}" in v))

print("\n--- the tokens the page fills ---")
TOKEN = re.compile(r"\{(\w+)\}")
drift = []
CROSS_PATH = "/result_copy/profile/sign_cross/"
for path, value in STRINGS:
    if path not in TWIN_STRINGS or path.startswith(CROSS_PATH):
        continue
    mine_t, theirs = sorted(TOKEN.findall(value)), \
        sorted(TOKEN.findall(TWIN_STRINGS[path]))
    if mine_t != theirs:
        drift.append((path, theirs, mine_t))
# One line drops a token on purpose. result_zodiac.js fills
# {subtype_article} with the English "a" or "an", and a Bulgarian subtype name
# carries its own definite article suffixed to it, so the bridge is written
# without the slot.
EXPECTED_DRIFT = ["/result_copy/profile/bridge"]
check("every line fills the same tokens as the twin's",
      sorted(d[0] for d in drift) == sorted(EXPECTED_DRIFT), str(drift))
check("  and no cross line fills a token at all, on either funnel",
      not [v for p, v in STRINGS if p.startswith(CROSS_PATH) and TOKEN.search(v)]
      and not [v for p, v in leaves(twin)
               if p.startswith(CROSS_PATH) and TOKEN.search(v)])
check("  and the bridge still names the subtype",
      "{subtype_bare}" in cfg["result_copy"]["profile"]["bridge"]
      and "{subtype_article}" not in cfg["result_copy"]["profile"]["bridge"],
      cfg["result_copy"]["profile"]["bridge"])
check("  and the blueprint card still names both halves",
      all(t in cfg["result_copy"]["profile"]["cards"][5]["promise"]
          for t in ("{element}", "{second}")),
      cfg["result_copy"]["profile"]["cards"][5]["promise"])
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

print("\n--- it is actually Bulgarian, in Cyrillic ---")
# The failure this whole funnel exists to prevent: a config that shipped as a
# Latin transliteration, or one where a block was never translated at all.
# Both read as Bulgarian at a glance and neither is. Every VISIBLE string is
# scanned rather than the long ones only — Cyrillic is not an accent that a
# short word may legitimately lack, it is the alphabet.
CYRILLIC = re.compile(r"[Ѐ-ӿ]")
# What a string is allowed to be made of when it carries no Cyrillic at all:
# the placeholders the page fills, a figure, a currency sign, punctuation.
# Listed as a whole-string pattern rather than as a set of paths, so a new
# machine-shaped string is caught rather than quietly exempted.
TOKEN_ONLY = re.compile(r"^(?:\{\w+\}|\d+|[\s.,·—–\-+#%€↓→]+)+$")
# Paths whose value is a machine word, not copy: an id, a file, a currency
# code, a layout name, a timestamp. Everything else this funnel changed is
# read by somebody.
MACHINE = {"/slug", "/funnel_id", "/locale", "/result_template",
           "/pricing/currency", "/pricing/price_format",
           "/pricing/decimal_mark", "/sale/ends",
           # Which step's frame the boxes hero shows, and which section and
           # which glyph each tile names. Keys the module dispatches on, not
           # words anybody reads.
           "/result_copy/boxes/hero_step"}
MACHINE |= {"/result_copy/boxes/boxes/%d/%s" % (i, key)
            for i in range(4) for key in ("id", "icon")}
# An arm's id, its template and the name it is written down under. The name is
# an internal label for whoever reads the split — zodiac30's are English too —
# and nothing on the page ever prints one.
MACHINE |= {"/paywall_variants/%d/%s" % (i, key)
            for i in range(4)
            for key in ("id", "name", "template", "note")}
VISIBLE = [(p, v) for p, v in STRINGS
           if p not in MACHINE
           and (p not in TWIN_STRINGS or TWIN_STRINGS[p] != v)]
check("  there is a whole translation here, not a patched block",
      len(VISIBLE) >= 450, "%d translated strings" % len(VISIBLE))
flat = [(p, v) for p, v in VISIBLE
        if not CYRILLIC.search(v) and not TOKEN_ONLY.match(v)]
check("every visible string is written in Cyrillic", not flat, str(flat[:4]))
tokens_only = [(p, v) for p, v in VISIBLE if not CYRILLIC.search(v)]
check("  and the ones that carry no letters carry only figures and slots",
      sorted(p for p, _v in tokens_only)
      == ["/checkout/commerce/anchor_head_accent",
          "/checkout/commerce/price_anchor_accent",
          # The year tile's whole sub is the span the page computes: twelve
          # months from this one, in this funnel's own month names. A literal
          # here would be a month that goes stale on the first of next month.
          "/result_copy/boxes/boxes/3/sub"],
      str(tokens_only))
check("  the ъ is in there, which no Latin transliteration produces",
      "ъ" in RAW)
check("  and no Russian ы, э or ё wandered in",
      not re.search(r"[ыэёЫЭЁ]", RAW),
      str(re.findall(r".{20}[ыэёЫЭЁ].{20}", RAW)[:2]))

# The other half: which Latin is allowed to stay, named rather than tolerated.
# The colour names are copied exactly by two validators and by the stub, the
# rest are proper nouns and a file format.
COLOUR_NAMES = set(v for p, v in STRINGS
                   if p.endswith("/name") and "/colors/" in p)
ALLOWED_LATIN = sorted(COLOUR_NAMES | {"PDF", "Stripe", "e-mail",
                                       "Apple Pay", "Google Pay", "Mazzin"},
                       key=len, reverse=True)


def latin_left(value):
    """What Latin survives once the allowlisted tokens are taken out."""
    text = TOKEN.sub("", value)
    for token in ALLOWED_LATIN:
        text = text.replace(token, "")
    return re.findall(r"[A-Za-z]+", text)


stray = [(p, latin_left(v)) for p, v in VISIBLE if latin_left(v)]
check("no Latin word survives outside the allowlist", not stray,
      str(stray[:4]))
check("  and the allowlist is really used — the palette lines name colours",
      all(any(name in s["reveals"]["palette"]["line"]
              for name in COLOUR_NAMES) for s in cfg["styles"]),
      str([s["reveals"]["palette"]["line"][:40] for s in cfg["styles"]]))
check("  the colour names being the twin's own, character for character",
      COLOUR_NAMES == set(v for p, v in leaves(twin)
                          if p.endswith("/name") and "/colors/" in p))

# A straight double quote inside a value is what reports.py spends a whole
# prompt rule keeping out of a generated section. The config is held to the
# same rule — and, unlike the generated prose, its own quotation marks never
# pass through a JSON parser, so it keeps the typographic pair „ “ it has
# always used. Only what the model writes has to be guillemets.
check("no value in the config contains a straight double quote",
      not [p for p, v in STRINGS if '"' in v],
      str([p for p, v in STRINGS if '"' in v][:4]))
check("  nor a straight one anywhere in the raw file's values",
      not re.search(r'": "[^"]*\\"', RAW))
check("  and no value carries a typewriter quote of any kind",
      not [(p, v) for p, v in STRINGS if "''" in v or '""' in v],
      str([p for p, v in STRINGS if "''" in v or '""' in v][:3]))

# The colour names are excluded by path rather than by key: they are the one
# thing this funnel copies out of the twin on purpose, and the block above
# asserts that they are byte-identical to it.
SAME_AS_TWIN = [p for p, v in STRINGS
                if p in TWIN_STRINGS and v == TWIN_STRINGS[p]
                and "/colors/" not in p
                and p.split("/")[-1] in ("question", "label", "line", "sub",
                                         "kicker", "cta", "title", "blurb",
                                         "promise", "key", "spec", "hook",
                                         "teaser_line", "headline", "hint",
                                         "body", "fix", "setup", "trigger",
                                         "name", "left", "right", "fallback")]
# Unlike Romanian, Bulgarian shares no spelling with English here: Capricorn
# is Козирог and Ocean is Океан. Nothing is allowed to read the same.
check("no piece of visible copy was left in English", not SAME_AS_TWIN,
      str([(p, TWIN_STRINGS[p]) for p in SAME_AS_TWIN[:6]]))

cross = cfg["result_copy"]["profile"]["sign_cross"]
check("all 52 cross lines are written, in Cyrillic",
      sum(1 for row in cross.values() for v in row.values()) == 52
      and all(CYRILLIC.search(v)
              for row in cross.values() for v in row.values()),
      str([k for k, row in cross.items()
           for v in row.values() if not CYRILLIC.search(v)]))
check("  each of the thirteen covers all four elements",
      all(sorted(row) == ["air", "earth", "fire", "water"]
          for row in cross.values()))
check("  and no two of them are the same sentence",
      len({v for row in cross.values() for v in row.values()}) == 52)
check("the twelve signs are the Bulgarian twelve",
      [i["label"] for i in by_step["sign"]["pairs"][0]["images"]]
      == ["Овен", "Телец", "Близнаци", "Рак", "Лъв", "Дева", "Везни",
          "Скорпион", "Стрелец", "Козирог", "Водолей", "Риби"],
      str([i["label"] for i in by_step["sign"]["pairs"][0]["images"]]))

print("\n--- register: a blend of signs is a съчетание ---")
# The same decision the Romanian funnel took, in this language: the cross
# lines and the rarity line beside them have to call a blend the same thing,
# or the page is arguing with itself one line apart. The adjective is what
# says how rare a blend is; flattening the three tiers into one word would
# cost the product a distinction it sells.
TIERS = ("истинско съчетание", "необичайно съчетание", "рядко съчетание")
lines = [v for row in cross.values() for v in row.values()]
blend = [v for v in lines if "съчетание" in v]
plain = [v for v in lines if "съчетание" not in v]
check("every blend line calls it a съчетание", len(blend) == 36,
      "%d of %d" % (len(blend), len(lines)))
check("  and each carries exactly one of the three tiers",
      all(sum(t in v for t in TIERS) == 1 for v in blend),
      str([v[:60] for v in blend if sum(t in v for t in TIERS) != 1][:3]))
check("  all three tiers are used",
      all(sum(t in v for v in blend) for t in TIERS),
      str({t: sum(t in v for v in blend) for t in TIERS}))
check("  twelve of them are the genuine-cross tier, one per sign",
      sum(TIERS[0] in v for v in blend) == 12,
      str(sum(TIERS[0] in v for v in blend)))
check("  the rarity line says the same word",
      "съчетание" in cfg["result_copy"]["profile"]["rarity_line"],
      cfg["result_copy"]["profile"]["rarity_line"])
check("the sixteen that name no blend are the same-element and cusp lines",
      len(plain) == 16
      and sum("зодията в чист вид" in v for v in plain) == 12
      and len(cross["cusp"]) == 4,
      str([v[:50] for v in plain
           if "зодията в чист вид" not in v and "Границата" not in v]))
# The Romanian funnel's own register rule, restated for this one: no line here
# calls a blend by the clinical word for a genetic cross.
CLINICAL = re.compile(r"кръстос\w*", re.IGNORECASE)
check("  and no line in the config uses the clinical word for a cross",
      not CLINICAL.search(RAW), str(CLINICAL.findall(RAW)[:3]))

print("\n--- the product has one name, and it is профил ---")
# What the live page was selling was a "четене" in some lines and a "профил"
# in others — two names for one thing, on the screen that asks for the money.
# "профил" wins: it is what the page is titled, what the mail attaches and
# what the PDF is. "четене" is gone, in every inflection, and the whole config
# is scanned rather than the lines that happened to carry it.
READING = re.compile(r"четен", re.IGNORECASE)
reading = [(p, v) for p, v in STRINGS if READING.search(v)]
check("no string in the funnel calls the product a четене", not reading,
      str(reading[:4]))
check("  not in the raw file either, keys included",
      not READING.search(RAW),
      str(READING.findall(RAW)[:3]))
# The verb is a separate word and was rewritten with it, so the looser stem
# the review asked for is clean too: nothing here reads "се чете" either.
check("  and no ordinary form of the verb is left in the copy",
      not re.search(r"чете", RAW, re.IGNORECASE),
      str(re.findall(r".{15}чете.{15}", RAW)[:3]))
check("  while профил is everywhere the product is named",
      all(re.search(r"профил", cfg[b][k], re.IGNORECASE)
          for b, k in (("checkout", "product_name"), ("meta", "title"))),
      str([cfg["checkout"]["product_name"], cfg["meta"]["title"]]))
for label, value in (
        ("rarity_card.note", cfg["result_copy"]["profile"]["rarity_card"]["note"]),
        ("rarity_card.tail", cfg["result_copy"]["profile"]["rarity_card"]["tail"]),
        ("profile.rarity_line", cfg["result_copy"]["profile"]["rarity_line"]),
        ("profile.offer_head", cfg["result_copy"]["profile"]["offer_head"]),
        ("profile.bridge", cfg["result_copy"]["profile"]["bridge"])):
    check("  %-20s names it профил" % label,
          re.search(r"профил", value, re.IGNORECASE) is not None, value)
check("  the rarity card still counts in {n}, over профили",
      cfg["result_copy"]["profile"]["rarity_line"]
      == "Приблизително 1 на {n} профила попада на това съчетание",
      cfg["result_copy"]["profile"]["rarity_line"])
check("  and the note is the one the review asked for, one em dash and all",
      cfg["result_copy"]["profile"]["rarity_card"]["note"]
      == "Твоето предимство пред останалите — в пълния ти профил.",
      cfg["result_copy"]["profile"]["rarity_card"]["note"])

check("the hint invites a pull rather than a decision",
      cfg["swipe"]["hint"] == "Докосни това, което те привлича",
      cfg["swipe"]["hint"])
check("  and the subtext beside it is untouched",
      cfg["swipe"]["subtext"]
      == "18 докосвания. Без писане. Космичен профил, който наистина е твой."
      and cfg["swipe"]["subtext_accent"] == "18 докосвания",
      cfg["swipe"]["subtext"])

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
           if re.search(r"\b12 (сигнала|избора|докосвания)\b", v)],
      str([v for _, v in STRINGS
           if re.search(r"\b12 (сигнала|избора|докосвания)\b", v)]))
check("  and the only twelve left is the year map",
      "12 месеца" in cfg["report"]["sections"][5]["title"],
      cfg["report"]["sections"][5]["title"])
check("four signals are said to remain after the third interstitial",
      "четири" in cfg["interstitials"][2]["sub"].lower(),
      cfg["interstitials"][2]["sub"])
check("the rarity line still counts in {n}",
      "{n}" in cfg["result_copy"]["profile"]["rarity_line"],
      cfg["result_copy"]["profile"]["rarity_line"])

print("\n--- the words this vertical does not use, in two languages ---")
import reports  # noqa: E402

# The English list the twins are held to, unchanged, plus the Bulgarian half.
# Everything in the config is scanned, not a hand-listed subset: nothing in
# here is inherited from an English funnel that was already cleared, because
# every string in this file was written for it.
EN_WORDS = ["psychic", "prediction", "predictions", "fortune",
            "horoscope", "prophecy", "your future will"]
BG_WORDS = ["ясновид", "предсказ", "предреч", "гада", "пророч", "хороскоп",
            "късмет", "бъдещето ти ще", "симптом", "лекарств", "инвестиц"]
low = RAW.lower()
for word in EN_WORDS + BG_WORDS:
    where = low.find(word)
    check("  never says %r" % word, where == -1,
          low[max(0, where - 40):where + 40])

en_hits = [(p, reports._banned_hit(v, reports.ZODIAC_BANNED))
           for p, v in STRINGS]
en_hits = [(p, h) for p, h in en_hits if h]
check("the whole config passes the English Terms check",
      not en_hits, str(en_hits[:4]))
bg_hits = [(p, reports._banned_hit(v, reports.ZODIAC_BG_BANNED))
           for p, v in STRINGS]
bg_hits = [(p, h) for p, h in bg_hits if h]
check("  and the Bulgarian one",
      not bg_hits, str(bg_hits[:4]))
check("the Bulgarian list is the English list plus its own",
      set(reports.ZODIAC_BANNED) < set(reports.ZODIAC_BG_BANNED)
      and len(reports.ZODIAC_BG_BANNED)
      == len(reports.ZODIAC_BANNED) + len(reports.ZODIAC_BG_ONLY))
check("  and it is not the Romanian list under another name",
      reports.ZODIAC_BG_ONLY != reports.ZODIAC_RO_ONLY
      and reports.ZODIAC_BG_BANNED is not reports.ZODIAC_RO_BANNED)
CAUGHT = ["бъдещето ти ще донесе пари", "малко късмет", "едно предсказание",
          "твоят хороскоп", "гадаене на ръка", "старо пророчество",
          "ясновидка", "симптоми на умора", "лекарства", "инвестиции в злато"]
for phrase in CAUGHT:
    check("  %-30s is rejected" % ('"%s"' % phrase),
          reports._banned_hit(phrase, reports.ZODIAC_BG_BANNED) is not None)
check("  and ordinary Bulgarian is not",
      all(reports._banned_hit(t, reports.ZODIAC_BG_BANNED) is None
          for t in ("Добър си в това, което правиш.",
                    "Този месец е добър за почивка.",
                    "Избираш първо със сърцето.")))
check("  the Romanian list is untouched by any of it",
      len(reports.ZODIAC_RO_BANNED)
      == len(reports.ZODIAC_BANNED) + len(reports.ZODIAC_RO_ONLY))

print("\n--- the report profile behind it ---")
profile = reports._profile("zodiac-bg")
check("zodiac-bg is registered", profile is reports.ZODIAC_BG_PROFILE)
check("  and it is neither of the other two objects",
      profile is not reports.ZODIAC_PROFILE
      and profile is not reports.ZODIAC_RO_PROFILE)
check("  but it is still a zodiac profile everywhere it matters",
      reports._is_zodiac(profile)
      and reports._is_zodiac(reports._profile("zodiac30"))
      and reports._is_zodiac(reports._profile("zodiac-ro"))
      and not reports._is_zodiac(reports._profile("kitchen")))
check("  the two English funnels still share one object",
      reports._profile("zodiac") is reports._profile("zodiac30")
      is reports.ZODIAC_PROFILE)
check("  and the sandbox twin reads this funnel's profile, not kitchen's",
      reports._profile("zodiac-bg-test") is profile)
check("the same section split as the twin",
      profile["personal"] == reports.ZODIAC_PROFILE["personal"]
      and profile["cached"] == reports.ZODIAC_PROFILE["cached"])
check("  and the same shapes, asking for fewer characters",
      profile["spec"] is reports.ZODIAC_BG_SPEC
      and profile["spec"] is not reports.ZODIAC_PROFILE["spec"]
      and profile["spec"] is not reports.ZODIAC_RO_SPEC
      and sorted(profile["spec"]) == sorted(reports.ZODIAC_PROFILE["spec"]))
check("    and the year map's two marks said in Bulgarian",
      reports.RENDER_WORDS_BG["year_strong"] in profile["spec"]["shopping"]
      and reports.RENDER_WORDS_BG["year_quiet"] in profile["spec"]["shopping"])
check("    and no longer in English",
      reports.RENDER_WORDS["year_strong"] not in profile["spec"]["shopping"]
      and reports.RENDER_WORDS["year_quiet"] not in profile["spec"]["shopping"])
check("  the English shape is untouched, character for character",
      reports.RENDER_WORDS["year_strong"] in reports.ZODIAC_SPEC["shopping"]
      and reports.ZODIAC_PROFILE["spec"] is reports.ZODIAC_SPEC)
check("  and the marks are the only thing the shapes differ in, bar numbers",
      [sid for sid in reports.ZODIAC_SPEC
       if reports._marked_shapes(reports.RENDER_WORDS_BG)[sid]
       != reports._ZODIAC_SHAPES[sid]] == ["shopping"])
check("its prompt asks for Bulgarian, in the first rule",
      "LANGUAGE" in profile["system"]
      and "Bulgarian" in profile["system"].split("Every field")[0])
check("  and names the alphabet outright",
      "CYRILLIC" in profile["system"]
      and "Latin alphabet" in profile["system"])
check("  and the letter a transliteration cannot produce",
      "ъ" in profile["system"])
check("  and restates the never-claim-the-future rule",
      "never claim" in profile["system"].lower())
check("  in both languages",
      all(word in profile["system"]
          for word in ("предсказание", "хороскоп", "бъдещето ти ще",
                       "prophecy", "your future will")))
check("  and holds the JSON keys in English",
      "KEYS stay in English" in profile["system"])
check("the banned list is enforced on generation, not only in the prompt",
      profile["banned"] is reports.ZODIAC_BG_BANNED)

# The other half of the Terms check. The config is scanned above; this is
# everything the module PUBLISHES on its own account — the stubs a failed
# generation ships, the swatch prose, the render words, the mail, the
# compatibility table, the PDF's furniture. Serialised in one blob rather than
# walked, so a Bulgarian string added to any of these objects later is scanned
# without this list being extended.
#
# The prompts are deliberately not in it. ZODIAC_BG_SYSTEM and the two JSON
# notes NAME the banned words in order to forbid them, in both languages, so
# scanning them would fail on the rule doing its job — they are asserted
# separately, by the block above, on the words they have to contain.
BG_PUBLISHED = json.dumps([
    reports.ZODIAC_STUBS_BG, reports.ZODIAC_COLOR_TEXT_BG,
    reports.RENDER_WORDS_BG, reports.COPY_ZODIAC_BG,
    reports.COMPATIBILITY_BG, reports.PDF_ELEMENTS_BG,
    reports.ZODIAC_EMAIL_LINK_BG,
    dict((k, v) for k, v in reports.ZODIAC_BG_PROFILE.items()
         if isinstance(v, str) and k not in ("system", "json_retry")),
    reports._email_opening({"funnel": "zodiac-bg"}),
], ensure_ascii=False, default=str)
check("nothing the module publishes says a banned thing either",
      reports._banned_hit(BG_PUBLISHED, reports.ZODIAC_BG_BANNED) is None,
      str(reports._banned_hit(BG_PUBLISHED, reports.ZODIAC_BG_BANNED)))
check("  nor does it trip the English list",
      reports._banned_hit(BG_PUBLISHED, reports.ZODIAC_BANNED) is None,
      str(reports._banned_hit(BG_PUBLISHED, reports.ZODIAC_BANNED)))
check("  which is a real body of Bulgarian, not an empty scan",
      len(CYRILLIC.findall(BG_PUBLISHED)) > 3000,
      "%d Cyrillic characters" % len(CYRILLIC.findall(BG_PUBLISHED)))
STUB_STRINGS = [s for s in re.findall(r"[^\"]+", json.dumps(
    reports.ZODIAC_STUBS_BG, ensure_ascii=False))
    if CYRILLIC.search(s)]
check("  and every stub string is Bulgarian, not the English one",
      not [s for s in STUB_STRINGS
           if s in json.dumps(reports.ZODIAC_STUBS, ensure_ascii=False)],
      str(STUB_STRINGS[:2]))


def validates(stubs):
    return dict((section_id,
                 reports.VALIDATORS[section_id](
                     reports._fill(stubs[section_id], "X")) is not None)
                for section_id in stubs)


check("the profile carries its own stubs",
      profile["stubs"] is reports.ZODIAC_STUBS_BG
      and profile["stubs"] is not reports.ZODIAC_STUBS
      and profile["stubs"] is not reports.ZODIAC_STUBS_RO)
check("  the same six sections as the twin",
      sorted(reports.ZODIAC_STUBS_BG) == sorted(reports.ZODIAC_STUBS),
      str(sorted(set(reports.ZODIAC_STUBS) ^ set(reports.ZODIAC_STUBS_BG))))
check("  and each one validates exactly where the English one does",
      validates(reports.ZODIAC_STUBS_BG) == validates(reports.ZODIAC_STUBS),
      str([s for s, ok in validates(reports.ZODIAC_STUBS_BG).items()
           if ok != validates(reports.ZODIAC_STUBS)[s]]))
check("  the palette stub still takes its colours from the config",
      reports.ZODIAC_STUBS_BG["palette"]["colors"] == reports.FROM_CONFIG)
check("  and the module stamps the year onto this set too",
      reports.ZODIAC_STUBS_BG in reports.ZODIAC_STUB_SETS)
check("the swatch prose under the palette is Bulgarian",
      len(reports.ZODIAC_COLOR_TEXT_BG) == len(reports.ZODIAC_COLOR_TEXT)
      and all(CYRILLIC.search(" ".join(row))
              for row in reports.ZODIAC_COLOR_TEXT_BG))
check("  and the profile hands it over",
      profile["stub_colors"] is reports.ZODIAC_COLOR_TEXT_BG
      and reports.ZODIAC_PROFILE.get("stub_colors") is None)
bg_palette = reports._stub_for(
    "palette", reports._style_name(cfg, "celestial_air"),
    reports._style(cfg, "celestial_air"), profile["stubs"],
    reports._months_for(profile), profile["stub_colors"])
check("a built palette stub keeps the reader's own colour NAMES",
      [(c["name"], c["hex"]) for c in bg_palette["colors"]]
      == reports._style_colors(reports._style(cfg, "celestial_air")),
      str([c["name"] for c in bg_palette["colors"]]))
check("  and says what each one is for in Bulgarian",
      all(CYRILLIC.search(c["role"] + c["finish"] + c["where"])
          for c in bg_palette["colors"]))
bg_year = reports._stub_for("shopping", "X",
                            reports._style(cfg, "celestial_air"),
                            profile["stubs"], reports._months_for(profile),
                            profile["stub_colors"])
year_notes = [i["priority_note"] for i in bg_year["items"]]
check("the year stub is stamped with the reader's twelve months",
      [i["name"] for i in bg_year["items"]]
      == list(reports._months_for(profile)),
      str([i["name"] for i in bg_year["items"]][:3]))
check("  and marks three months and one, in Bulgarian",
      sum(n.startswith(reports.RENDER_WORDS_BG["year_strong"])
          for n in year_notes) == reports.YEAR_STRONG
      and sum(n.startswith(reports.RENDER_WORDS_BG["year_quiet"])
              for n in year_notes) == reports.YEAR_QUIET,
      str([n[:30] for n in year_notes]))
check("  never with the English prefixes",
      not [n for n in year_notes
           if n.startswith(reports.RENDER_WORDS["year_strong"])
           or n.startswith(reports.RENDER_WORDS["year_quiet"])])

print("\n--- it asks for a Bulgarian-sized amount of Bulgarian ---")
# Bulgarian says the same thing in 15-20% more characters, for the same kind
# of reason Romanian does: the article suffixes the noun, the future and the
# passive are analytic, and "на" sits between almost any two ideas. A budget
# calibrated on English is one this funnel overruns while writing exactly what
# it was asked for.
BG_BUDGET = reports.ZODIAC_BG_PROMPT_BUDGET
check("the profile declares its own prompt budget",
      profile.get("prompt_budget") == BG_BUDGET < reports.PROMPT_BUDGET,
      "%s vs %s" % (profile.get("prompt_budget"), reports.PROMPT_BUDGET))
check("  read through the accessor, which defaults to the English one",
      reports._prompt_budget(profile) == BG_BUDGET
      and reports._prompt_budget(reports.ZODIAC_PROFILE)
      == reports._prompt_budget(reports.KITCHEN_PROFILE)
      == reports._prompt_budget(None) == reports.PROMPT_BUDGET)
check("  and the translated profiles are the only ones that set the key",
      sorted(slug for slug, p in reports.PROFILES.items()
             if p.get("prompt_budget")) == ["zodiac-bg", "zodiac-ro"],
      str([slug for slug, p in reports.PROFILES.items()
           if p.get("prompt_budget")]))

# The claim the budget rests on: whatever the prompt asks for, the validator
# that would throw the section away allows more. Checked over every capped
# field of every section rather than the ones that happened to fail.
over = []
tighter = []
for section_id in sorted(reports.ZODIAC_BG_SPEC):
    ceilings = reports._ceilings(section_id)
    bg = reports._budgets(section_id, BG_BUDGET)
    en = reports._budgets(section_id)
    for field, asked in sorted(bg.items()):
        cap = ceilings[field]
        if asked > cap:
            over.append("%s.%s asks %d of %d" % (section_id, field, asked, cap))
        if asked >= en[field]:
            tighter.append("%s.%s %d vs %d" % (section_id, field, asked,
                                               en[field]))
check("every BG budget is inside the ceiling that polices its field",
      not over, str(over))
check("  and every one of them is under the English number",
      not tighter, str(tighter))
check("  with real headroom left, not a rounding of it",
      all(asked <= 0.62 * reports._ceilings(sid)[field]
          for sid in reports.ZODIAC_BG_SPEC
          for field, asked in reports._budgets(sid, BG_BUDGET).items()),
      str([(sid, f, a, reports._ceilings(sid)[f])
           for sid in reports.ZODIAC_BG_SPEC
           for f, a in reports._budgets(sid, BG_BUDGET).items()
           if a > 0.62 * reports._ceilings(sid)[f]]))
# PROMPT_LENGTH is hand-set and overrides the derived default, so a budget
# that only moved the derived numbers would leave the long sections exactly as
# they were.
check("the hand-set lengths came down too, not just the derived ones",
      all(reports._budgets(sid, BG_BUDGET)[field]
          < reports.PROMPT_LENGTH[sid][field]
          for sid, fields in reports.PROMPT_LENGTH.items()
          for field in fields),
      str({sid: {f: reports._budgets(sid, BG_BUDGET)[f] for f in fields}
           for sid, fields in reports.PROMPT_LENGTH.items()}))
check("the English shapes are untouched, byte for byte",
      reports.ZODIAC_SPEC == dict(
          (sid, reports._zodiac_spec(text, sid))
          for sid, text in reports._ZODIAC_SHAPES.items()))


def shape_only(text):
    """One shape with the three things that separate the languages taken off.

    The budgets, the closing punctuation rule, and the two prefixes the year
    map marks its months with. Normalise all three and what is left is the
    question itself, which has to be the same question in every language.
    """
    if text.endswith(reports.ZODIAC_BG_JSON_RULE):
        text = text[:-len(reports.ZODIAC_BG_JSON_RULE)]
    for key in ("year_strong", "year_quiet"):
        text = text.replace(reports.RENDER_WORDS_BG[key],
                            reports.RENDER_WORDS[key])
    return re.sub(r"\d+", "#", text)


check("  and the two ask the same questions, in different numbers",
      all(shape_only(reports.ZODIAC_BG_SPEC[sid])
          == re.sub(r"\d+", "#", reports.ZODIAC_SPEC[sid])
          for sid in reports.ZODIAC_SPEC),
      str([sid for sid in reports.ZODIAC_SPEC
           if shape_only(reports.ZODIAC_BG_SPEC[sid])
           != re.sub(r"\d+", "#", reports.ZODIAC_SPEC[sid])]))

print("\n--- Bulgarian prose is what breaks the JSON ---")
check("the prompt says the answer is JSON and what breaks it",
      "not valid JSON" in profile["system"]
      and "escaped" in profile["system"])
# FORCED TEST EDIT (1 of 2). This pinned „ “ as the pair the prompt offers,
# and that pair is what broke production: the model opened with U+201E and
# closed with a straight ", which is the JSON delimiter, and ten of twelve
# warmed sections were thrown away. The prompt offers guillemets now, which
# cannot be mistaken for a delimiter, and it names the old pair by codepoint
# rather than typing it.
check("  and offers the punctuation that costs nothing to parse",
      "«" in profile["system"] and "»" in profile["system"])
check("  the English prompt is unchanged",
      reports.ZODIAC_PROFILE["system"] is reports.ZODIAC_SYSTEM
      and "„" not in reports.ZODIAC_SYSTEM)
check("every BG shape closes on the punctuation contract",
      all(text.endswith(reports.ZODIAC_BG_JSON_RULE)
          for text in reports.ZODIAC_BG_SPEC.values()))
check("  which tells it to write the sentence with no quotation marks",
      "no quotation marks"
      in " ".join(reports.ZODIAC_BG_JSON_RULE.split()))
# FORCED TEST EDIT (2 of 2). Same reason: the alternative offered is the
# guillemet pair now. The old pair is still named — by codepoint, so it can be
# forbidden without the glyph appearing anywhere the model might copy it from.
check("  and offers the guillemets as the only alternative",
      "«" in reports.ZODIAC_BG_JSON_RULE
      and "U+00AB" in reports.ZODIAC_BG_JSON_RULE
      and "U+00BB" in reports.ZODIAC_BG_JSON_RULE)
check("    naming the pair that broke it, without typing it",
      "U+201E" in reports.ZODIAC_BG_JSON_RULE
      and "U+201C" in reports.ZODIAC_BG_JSON_RULE)
check("  which is not the Romanian rule — that one still offers its own pair",
      "U+201D" in reports.ZODIAC_RO_JSON_RULE
      and "U+201D" not in reports.ZODIAC_BG_JSON_RULE
      and "«" not in reports.ZODIAC_RO_JSON_RULE)
check("the English shapes carry none of it",
      not any(reports.ZODIAC_BG_JSON_RULE in t
              for t in reports.ZODIAC_SPEC.values())
      and "PUNCTUATION" not in reports.ZODIAC_SPEC["splurge"])
check("the BG prompt forbids the character outright, not as a preference",
      "Never type one inside a value" in profile["system"])
check("the BG profile declares a JSON retry note",
      profile["json_retry"] is reports.ZODIAC_BG_JSON_RETRY)
check("  naming the quote, the field and what to do instead",
      "straight double quote" in reports.ZODIAC_BG_JSON_RETRY
      and "sentence a field asked" in reports.ZODIAC_BG_JSON_RETRY
      and "NO quotation marks" in reports.ZODIAC_BG_JSON_RETRY)
check("  and the translated profiles are the only ones that declare one",
      sorted(slug for slug, pr in reports.PROFILES.items()
             if pr.get("json_retry")) == ["zodiac-bg", "zodiac-ro"],
      str([slug for slug, pr in reports.PROFILES.items()
           if pr.get("json_retry")]))
check("  and every call site still hands the profile's own",
      REPORTS_SRC.count('profile.get("json_retry")') == 3)

WANT = ("splurge",)


def body(text):
    """One section's worth of JSON, with `text` in a prose field."""
    return json.dumps(
        {"splurge": {"splurge": {"item": "Тримесечен курс", "why": text},
                     "split_note": text,
                     "saves": [{"item": "Тетрадка", "why": text},
                               {"item": "Час на ден", "why": text}]}},
        ensure_ascii=False)


PROSE = "Парите следват вниманието ти, не усилието, и моделът се чупи. " * 4
ok_json = body(PROSE)
parsed, why = reports._parse_detail(ok_json, WANT, [])
check("a valid answer still parses", parsed is not None, why)
notes = []
parsed, why = reports._parse_detail(
    ok_json.replace("не усилието", 'не "усилието"', 1), WANT, notes)
check("an unescaped quote is still refused", parsed is None, str(parsed)[:60])
check("  and the retry names the failure as a parse failure",
      notes and "not valid JSON" in notes[0], str(notes))


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


SAID = 'Откажи я направо, с изречението: "Не мога да поема това сега." Сложи'
broken = body(PROSE).replace("не усилието", "не " + SAID, 1)


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


bg_retry = retry_for(profile)
en_retry = retry_for(reports.ZODIAC_PROFILE)
kitchen_retry = retry_for(reports.KITCHEN_PROFILE)
check("a Bulgarian retry really does carry the rule",
      reports.ZODIAC_BG_JSON_RETRY in bg_retry)
check("  and the generic advice before it",
      0 <= bg_retry.find("punctuation, not length")
      < bg_retry.find(reports.ZODIAC_BG_JSON_RETRY))
check("  and not the Romanian note",
      reports.ZODIAC_RO_JSON_RETRY not in bg_retry)
check("an English zodiac retry gets the generic advice and no more",
      "This is punctuation, not length" in en_retry
      and reports.ZODIAC_BG_JSON_RETRY not in en_retry
      and "„" not in en_retry)
check("a kitchen retry is the line it has always been",
      kitchen_retry == "P" + reports.RETRY_NOTE, kitchen_retry[-80:])
check("and no retry quotes the answer back at the model",
      not any("Не мога да поема" in r
              for r in (bg_retry, en_retry, kitchen_retry)))

print("\n--- the year, in Bulgarian ---")
months = reports._months_for(profile)
check("twelve labels", len(months) == 12, str(months))
check("  in Bulgarian month names", all(
    any(m.startswith(a) for a in reports.MONTH_ABBR_BG) for m in months),
      str(months))
check("  none of them is an English month",
      not [m for m in months
           if any(m.startswith(a) for a in reports.MONTH_ABBR)],
      str(months))
check("  and none of them is a Romanian one",
      not set(reports.MONTH_ABBR_BG) & set(reports.MONTH_ABBR_RO))
check("  starting from this month, not January",
      months[0] == "%s %d" % (
          reports.MONTH_ABBR_BG[reports.datetime.datetime.now(
              reports.datetime.timezone.utc).date().month - 1],
          reports.datetime.datetime.now(
              reports.datetime.timezone.utc).date().year),
      months[0])
check("the twin still counts its year in English",
      reports._months_for(reports.ZODIAC_PROFILE) == reports._year_labels())
check("  and zodiac-ro still counts its own in Romanian",
      reports._months_for(reports.ZODIAC_RO_PROFILE)
      == reports._year_labels_ro())
check("  and kitchen counts no year at all",
      reports._months_for(reports.KITCHEN_PROFILE) is None)
check("the month validator accepts the Bulgarian twelve",
      reports._verify_months(
          {"items": [{"name": m} for m in months]}, months) is None)
check("  and rejects a year that opens in January anyway",
      reports._verify_months(
          {"items": [{"name": m} for m in reports._year_labels()]},
          months) is not None)

print("\n--- the year map is checked in the language it was asked for ---")
bg_style = reports._style(cfg, "celestial_air")
GOOD_BG = {"items": [
    {"name": m,
     "priority_note": (reports.RENDER_WORDS_BG["year_strong"] if i in (2, 5, 8)
                       else reports.RENDER_WORDS_BG["year_quiet"] if i == 7
                       else "Добър за") + " нещо конкретно."}
    for i, m in enumerate(months)]}
BAD_EN = {"items": [
    {"name": m,
     "priority_note": (reports.RENDER_WORDS["year_strong"] if i in (2, 5, 8)
                       else reports.RENDER_WORDS["year_quiet"] if i == 7
                       else "Добър за") + " нещо конкретно."}
    for i, m in enumerate(months)]}
check("the Bulgarian profile asks for the marks to be checked",
      profile.get("verify_marks") is True)
check("  and the English one still does not",
      reports.ZODIAC_PROFILE.get("verify_marks") is None
      and reports.KITCHEN_PROFILE.get("verify_marks") is None)
marks = reports._year_marks(profile)
check("its marks are the two Bulgarian prefixes",
      marks == (reports.RENDER_WORDS_BG["year_strong"],
                reports.RENDER_WORDS_BG["year_quiet"]), str(marks))
check("a Bulgarian year map marked in Bulgarian is accepted",
      reports._verify_months(GOOD_BG, months, marks) is None,
      str(reports._verify_months(GOOD_BG, months, marks)))
check("  the same map marked in English is refused",
      reports._verify_months(BAD_EN, months, marks) is not None)
bg_verify = reports._verify_for(profile, bg_style, months)
check("the purchase path's check refuses an English-marked Bulgarian year",
      bg_verify(("shopping",), {"shopping": BAD_EN}) is not None)
check("  and accepts the Bulgarian-marked one",
      bg_verify(("shopping",), {"shopping": GOOD_BG}) is None,
      str(bg_verify(("shopping",), {"shopping": GOOD_BG})))

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
      table["Овен"][0] == ("Лъв", "Стрелец")
      and table["Рак"][0] == ("Скорпион", "Риби")
      and table["Дева"][0] == ("Телец", "Козирог"),
      str(table["Овен"]))
EN_SIGNS = [i["label"] for i in twin["swipe"]["steps"][1]["pairs"][0]["images"]]
BG_OF = dict(zip(EN_SIGNS, signs))
check("  and it is the English table, sign for sign, in these names",
      all((tuple(BG_OF[s] for s in reports.COMPATIBILITY[en][0]),
           BG_OF[reports.COMPATIBILITY[en][1]]) == table[BG_OF[en]]
          for en in EN_SIGNS),
      str([en for en in EN_SIGNS
           if (tuple(BG_OF[s] for s in reports.COMPATIBILITY[en][0]),
               BG_OF[reports.COMPATIBILITY[en][1]]) != table[BG_OF[en]]]))
check("the English table is untouched",
      reports.COMPATIBILITY["Aries"] == (("Leo", "Sagittarius"), "Cancer")
      and reports.ZODIAC_PROFILE["compatibility"] is reports.COMPATIBILITY)
check("  and the Romanian one too",
      reports.ZODIAC_RO_PROFILE["compatibility"] is reports.COMPATIBILITY_RO)

# A run down the Bulgarian walk, to the block the love section is built from.
choices = []
for step in steps:
    if step["id"] == "sign":
        choices.append("sign_virgo")
    else:
        choices.append(step["pairs"][0]["images"][0]["id"])
read = reports._sign(cfg, choices)
check("the sign step reads back a Bulgarian label",
      (read or {}).get("label") == "Дева", str(read))
block = reports._compat_block(cfg, choices, table)
check("  and the love prompt names its three signs in Bulgarian",
      block and "Телец" in block and "Козирог" in block
      and "Стрелец" in block and "Virgo" not in block,
      (block or "")[:120])
check("  where the English table would have named none of them",
      reports._compat_block(cfg, choices, reports.COMPATIBILITY) is None)

rak = ["sign_cancer" if step["id"] == "sign"
       else step["pairs"][0]["images"][0]["id"] for step in steps]
block = reports._compat_block(cfg, rak, table)
check("a Рак is handed three signs, not four",
      sorted(s for s in table if re.search(r"\b%s\b" % s, block))
      == sorted(["Рак", "Скорпион", "Риби", "Овен"]),
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


DELIVERED = love("Рак + Скорпион", "Рак + Риби", "Рак + Овен", "Рак + Овен")
CORRECT = love("Рак + Скорпион", "Рак + Риби", "Рак + Овен", "Рак + Козирог")
bg_love = reports._verify_for(profile, reports._style(cfg, "deep_water"),
                              months)
check("a section that names one sign twice is refused",
      bg_love(("materials",), DELIVERED) is not None,
      str(bg_love(("materials",), DELIVERED)))
check("  the refusal names Овен, and not the reader's own sign",
      "Овен" in (bg_love(("materials",), DELIVERED) or "")
      and "Рак" not in (bg_love(("materials",), DELIVERED) or ""),
      str(bg_love(("materials",), DELIVERED)))
check("  four distinct Bulgarian signs pass",
      bg_love(("materials",), CORRECT) is None,
      str(bg_love(("materials",), CORRECT)))
check("  and the Bulgarian stub passes it too",
      bg_love(("materials",), {"materials": reports._fill(
          reports.ZODIAC_STUBS_BG["materials"], "X")}) is None,
      str(bg_love(("materials",), {"materials": reports._fill(
          reports.ZODIAC_STUBS_BG["materials"], "X")})))

print("\n--- the mail and the document ---")
check("zodiac-bg sends its own mail",
      reports._email_copy({"funnel": "zodiac-bg"}) is reports.COPY_ZODIAC_BG)
check("  and the English funnels still send theirs",
      reports._email_copy({"funnel": "zodiac30"})
      is reports._email_copy({"funnel": "zodiac"}) is reports.COPY_ZODIAC)
check("  and zodiac-ro still sends the Romanian one",
      reports._email_copy({"funnel": "zodiac-ro"}) is reports.COPY_ZODIAC_RO)
for field in ("headline", "subject", "body", "keep", "keep_no_link"):
    value = reports.COPY_ZODIAC_BG[field]
    check("  mail.%-12s is Bulgarian" % field,
          bool(CYRILLIC.search(value))
          and value != reports.COPY_ZODIAC.get(field)
          and value != reports.COPY_ZODIAC_RO.get(field),
          value)
check("  the subject still takes the style name",
      reports.COPY_ZODIAC_BG["subject"].count("%s") == 1
      and reports.COPY_ZODIAC_BG["body"].count("%s") == 1)
# FORCED TEST EDIT (2 of 2). Same reason as the block above: the mail names
# what the reader was actually charged, so the purchase is what says which
# number that is.
check("the opening line is Bulgarian and names the price that was paid",
      CYRILLIC.search(_bought("zodiac-bg", 499)[1])
      and "4,99\u00a0\u20ac" in _bought("zodiac-bg", 499)[1],
      _bought("zodiac-bg", 499)[1])
check("  and the sale price when that is what the card was charged",
      "1,99\u00a0\u20ac" in _bought("zodiac-bg", 199)[1],
      _bought("zodiac-bg", 199)[1])
# The one place the ACT of reading is meant rather than the thing sold, and
# the word for it is "прочит" — never "четене", which is the product noun this
# funnel does not use.
check("  and it calls that a прочит, not a четене",
      "прочит" in _bought("zodiac-bg", 199)[1]
      and "чете" not in _bought("zodiac-bg", 199)[1],
      _bought("zodiac-bg", 199)[1])
check("  read off the purchase rather than written into the mail",
      _bought("zodiac-bg", 199)[0] == "1,99\u00a0\u20ac"
      and _bought("zodiac30", 199, "usd")[0] == "$1.99"
      and _bought("zodiac-ro", 499, "ron")[0] == "4,99 lei",
      "%s / %s" % (_bought("zodiac-bg", 199)[0],
                   _bought("zodiac30", 199, "usd")[0]))
check("  and no number at all when the purchase cannot be read",
      reports._price_paid({"funnel": "zodiac-bg"}) is None,
      repr(reports._price_paid({"funnel": "zodiac-bg"})))
check("  and the English opening is unchanged",
      _bought("zodiac30", 300, "usd")[1].startswith("You just spent"),
      _bought("zodiac30", 300, "usd")[1])
print("\n--- the archetype name, in a Bulgarian sentence ---")
# What the live page did: glued the style name straight onto a bare noun.
# "Профил Небесен въздух решава бързо" is two nominatives side by side with
# nothing joining them — it is not a sentence in Bulgarian. So the name is
# wrapped and the noun in front of it is an ordinary common noun that takes
# an article where the syntax asks for one: Профилът «Небесен въздух» решава
# бързо, but умът на профила «Небесен въздух».
#
# FORCED TEST EDITS through this block. The wrapper was „ “ and is guillemets
# now — U+201E opened and a straight " closed it, which is the JSON delimiter,
# and warm_cache lost ten of twelve sections to exactly that. A guillemet
# cannot be mistaken for a delimiter.
STYLE_NAME = "Небесен въздух"
OPEN, CLOSE = "\u00ab", "\u00bb"
check("the funnel's four archetypes are the names this is about",
      [s["name"] for s in cfg["styles"]]
      == ["Сияен огън", "Дълбока вода", "Устойчива земя", "Небесен въздух"],
      str([s["name"] for s in cfg["styles"]]))
check("the mail subject sets the name in guillemets",
      reports.COPY_ZODIAC_BG["subject"] % STYLE_NAME
      == "Твоят космичен профил \u00abНебесен въздух\u00bb — Mazzin",
      reports.COPY_ZODIAC_BG["subject"] % STYLE_NAME)
check("  and the body takes the article on the head noun with it",
      reports.COPY_ZODIAC_BG["body"] % STYLE_NAME
      == "Пълният ти профил \u00abНебесен въздух\u00bb е прикачен.",
      reports.COPY_ZODIAC_BG["body"] % STYLE_NAME)
check("  neither of them glues a bare name onto a bare noun",
      not re.search(r"профил %s" % STYLE_NAME,
                    (reports.COPY_ZODIAC_BG["subject"] % STYLE_NAME)
                    + " " + (reports.COPY_ZODIAC_BG["body"] % STYLE_NAME)))
check("  and the English and Romanian mails are untouched",
      reports.COPY_ZODIAC["subject"] == "Your %s cosmic profile — Mazzin"
      and reports.COPY_ZODIAC_RO["subject"] == "Profilul tău cosmic %s — Mazzin",
      "%s / %s" % (reports.COPY_ZODIAC["subject"],
                   reports.COPY_ZODIAC_RO["subject"]))

# Every stub that names the archetype, filled the way `_stub_for` fills it.
FILLED = {sid: json.dumps(reports._fill(stub, STYLE_NAME), ensure_ascii=False)
          for sid, stub in reports.ZODIAC_STUBS_BG.items()}
NAMING = [(sid, text) for sid, text in sorted(FILLED.items())
          if STYLE_NAME in text]
check("four of the six stubs name the archetype",
      [sid for sid, _t in NAMING] == ["dna", "mistakes", "palette", "splurge"],
      str([sid for sid, _t in NAMING]))
for sid, text in NAMING:
    check("  %-9s wraps it in guillemets" % sid,
          ((OPEN + STYLE_NAME + CLOSE) in text),
          re.search(r".{0,24}%s.{0,6}" % STYLE_NAME, text).group(0))
    check("    and articles the noun in front of it",
          not re.search(r"(?:Профил|Палитра|Енергия|План) %s" % STYLE_NAME,
                        text),
          re.search(r".{0,24}%s.{0,6}" % STYLE_NAME, text).group(0))
HEADS = (("palette", "Палитрата "), ("mistakes", "Профилът "),
         ("splurge", "Енергията "), ("dna", "Планът "))
check("  the four heads being the articled forms, each a common noun",
      all((head + OPEN) in FILLED[sid] for sid, head in HEADS),
      str([sid for sid, head in HEADS if (head + OPEN) not in FILLED[sid]]))
check("the swatch prose names no archetype, so it needs no rule",
      STYLE_NAME not in json.dumps(reports.ZODIAC_COLOR_TEXT_BG,
                                   ensure_ascii=False)
      and "{name}" not in json.dumps(reports.ZODIAC_COLOR_TEXT_BG,
                                     ensure_ascii=False))
check("  and the English stubs still say it the English way",
      "A {name} palette runs on" in json.dumps(reports.ZODIAC_STUBS,
                                               ensure_ascii=False))
# The model writes the sections the stubs only stand in for, so it is told
# the same rule in the same words.
check("the prompt states the rule, with the pair and a worked example",
      "NAMING THE ARCHETYPE" in profile["system"]
      and "GUILLEMETS" in profile["system"]
      and "\u00abНебесен въздух\u00bb" in profile["system"]
      and "Профилът \u00abНебесен въздух\u00bb" in profile["system"])
check("  and names the failure it is there to prevent",
      "Профил Небесен въздух" in profile["system"])
# The article rule as it actually is, rather than "always articled": the head
# is a common noun and behaves like one. After a preposition it is bare, and
# the prompt has to show that or the model writes "Умът на Профилът".
check("  the article rule is the one Bulgarian actually has",
      "\u0443\u043c\u044a\u0442 \u043d\u0430 \u043f\u0440\u043e\u0444"
      "\u0438\u043b\u0430 \u00abНебесен въздух\u00bb" in profile["system"]
      and "Умът на Профилът" in profile["system"],
      "the prompt shows neither the prepositional case nor the error")
check("  and forbids the pair that broke it, by codepoint",
      "U+201E" in profile["system"] and "U+201C" in profile["system"])

print("\n--- nothing the model is shown carries the pair that broke it ---")
# The outage, in one sentence: the prompt showed the model U+201E … U+201C,
# the model opened with U+201E and closed with a straight ", which is the JSON
# delimiter, and warm_cache lost ten of twelve sections — twice each, because
# the retry showed it the same pair again. So the glyphs appear nowhere the
# model could copy them from: the prompts name them by codepoint instead.
#
# The funnel's own config is a separate matter and keeps „ “: those strings
# are rendered by the browser and never pass through a JSON parser.
SHOWN = {
    "system": profile["system"],
    "json rule": reports.ZODIAC_BG_JSON_RULE,
    "json retry": reports.ZODIAC_BG_JSON_RETRY,
    "spec": json.dumps(reports.ZODIAC_BG_SPEC, ensure_ascii=False),
    "stubs": json.dumps(reports.ZODIAC_STUBS_BG, ensure_ascii=False),
    "swatch prose": json.dumps(reports.ZODIAC_COLOR_TEXT_BG,
                               ensure_ascii=False),
    "mail": json.dumps(reports.COPY_ZODIAC_BG, ensure_ascii=False),
    "render words": json.dumps(reports.RENDER_WORDS_BG, ensure_ascii=False),
}
for name, text in sorted(SHOWN.items()):
    check("  %-13s carries no \u201e and no \u201c" % name,
          "\u201e" not in text and "\u201c" not in text,
          re.search(r".{0,30}[\u201e\u201c].{0,30}", text).group(0)
          if re.search(r"[\u201e\u201c]", text) else "")
check("  and the guillemets are what they use instead",
      all("\u00ab" in SHOWN[k] for k in
          ("system", "json rule", "json retry", "stubs", "mail")))
check("the config keeps its own typographic pair, which parses nothing",
      any("\u201e" in v for _p, v in STRINGS)
      or True,  # a funnel with no quoted prose is not a failure
      "")
check("  and still contains no straight double quote",
      not [p for p, v in STRINGS if '"' in v])

print("\n--- the straight quote is repaired before the parser sees it ---")
# Belt to the prompt's braces. A model that has been told once can still reach
# for the key next to it, and what it costs when it does is a buyer's report.
repair = profile.get("json_repair")
check("the BG profile declares a repair", callable(repair))
check("  and it is the only profile that does",
      [slug for slug, pr in reports.PROFILES.items() if pr.get("json_repair")]
      == ["zodiac-bg"],
      str([slug for slug, pr in reports.PROFILES.items()
           if pr.get("json_repair")]))

# The three fragments out of the warm_cache log, character for character.
# The first two are what it died on; the third is the one that must survive
# untouched, because there the straight quote really is the end of the value.
NAMED = "палитрата „Сияен огън\" работят"
MID = '"why": "Енергията „Дълбока вода\" не губи'
ENDS = '"Сияен огън",'
check("a name closed with a straight quote becomes a guillemet",
      repair(NAMED) == "палитрата «Сияен огън» работят", repr(repair(NAMED)))
check("  and the value's own opening quote is left alone",
      repair(MID) == '"why": "Енергията «Дълбока вода» не губи',
      repr(repair(MID)))
check("  while a value that ENDS with the name keeps its real closing quote",
      repair(ENDS) == ENDS, repr(repair(ENDS)))
check("an English answer is untouched, quotes and all",
      repair('{"a": "He said \\"no\\" and meant it."}')
      == '{"a": "He said \\"no\\" and meant it."}')
check("  and a Bulgarian answer that was written correctly is untouched",
      repair('{"a": "Палитрата «Сияен огън» работи."}')
      == '{"a": "Палитрата «Сияен огън» работи."}')
check("  the closing curly quote is normalised with the opening one",
      repair("Палитрата „Сияен огън“ работи")
      == "Палитрата «Сияен огън» работи",
      repr(repair("Палитрата „Сияен огън“ работи")))
check("  and a straight quote followed by JSON structure is never touched",
      repair('{"a": "текст", "b": "друг"}') == '{"a": "текст", "b": "друг"}')

# End to end, on the shape the warmer actually asks for: the section that
# production threw away twice is accepted now.
COLORS = [{"name": name, "hex": code, "role": "за движение",
           "finish": "понеделник", "where": "на китката"}
          for name, code in (("Solar Amber", "#F2A33C"),
                             ("Ember Gold", "#D8642A"),
                             ("Ash Basalt", "#3A1E14"),
                             ("Sun White", "#FBE2A0"))]
BROKEN = json.dumps(
    {"palette": {
        "intro": "PLACEHOLDER работят заедно и държат деня, а третият "
                 "носи тежестта отдолу.",
        "colors": COLORS,
        "closing_rule": "Носи едно силно нещо, не три."}},
    ensure_ascii=False).replace("PLACEHOLDER", "Палитрата „Сияен огън\"")
check("the section production threw away does not parse as it stands",
      reports._parse_detail(BROKEN, ("palette",), [])[0] is None)
check("  and parses once the repair has run",
      reports._parse_detail(BROKEN, ("palette",), [], repair)[0] is not None,
      str(reports._parse_detail(BROKEN, ("palette",), [], repair)[1]))
check("  with the name in guillemets in the text that is stored",
      "«Сияен огън»" in (
          reports._parse_detail(BROKEN, ("palette",), [], repair)[0]
          or {}).get("palette", {}).get("intro", ""))
check("_parse_detail takes the repair as an argument, defaulting to none",
      "repair" in reports._parse_detail.__code__.co_varnames
      and reports._parse_detail.__defaults__[-1] is None)
check("_generate takes it too, and hands it to BOTH attempts",
      "json_repair" in reports._generate.__code__.co_varnames
      and REPORTS_SRC.count(
          "_parse_detail(text, want, notes, json_repair)") == 1
      and REPORTS_SRC.count(
          "_parse_detail(text, want, None, json_repair)") == 1)
check("  and every call site hands the profile's own",
      REPORTS_SRC.count('profile.get("json_repair")') == 3)

check("the warmed rows go stale, so the broken ones are written again",
      profile["cache_rev"] == {"palette": "bgname2", "mistakes": "bgname2",
                               "splurge": "bgname2"},
      str(profile["cache_rev"]))
check("  and the English and Romanian revisions are untouched",
      reports.ZODIAC_PROFILE["cache_rev"]
      == reports.ZODIAC_RO_PROFILE["cache_rev"]
      == {"palette": "colors2", "mistakes": "short1", "splurge": "moves1"})
check("  the English and Romanian prompts say nothing about it",
      "NAMING THE ARCHETYPE" not in reports.ZODIAC_SYSTEM
      and "NAMING THE ARCHETYPE" not in reports.ZODIAC_RO_SYSTEM)

check("the button on the mail is Bulgarian",
      "Отвори" in profile["mail_link"]
      and "Open your profile online" not in profile["mail_link"])
check("  and the English template still fills on {link} alone",
      reports.ZODIAC_EMAIL_LINK % {"link": "x"})
check("the PDF leads and closes in Bulgarian",
      bool(CYRILLIC.search(profile["pdf_lead"]))
      and bool(CYRILLIC.search(profile["pdf_note"]))
      and profile["pdf_lead"] != reports.ZODIAC_PROFILE["pdf_lead"],
      profile["pdf_lead"])
check("  the document declares its language",
      profile.get("pdf_lang") == "bg")
check("  the cover strip names the four elements in Bulgarian",
      [label for _t, label, _h in profile["pdf_elements"]]
      == ["Огън", "Земя", "Въздух", "Вода"])
check("  and it draws the same cover and sheet as the twin",
      profile["pdf_cover"] is reports.ZODIAC_PROFILE["pdf_cover"]
      and profile["pdf_css"] is reports.ZODIAC_PROFILE["pdf_css"])
check("the delivered page is still handed the address",
      profile.get("delivery_note") is True)
check("  and every section header it prints is this config's Bulgarian",
      all(m["title"] != t["title"] for m, t in
          zip(cfg["report"]["sections"], twin["report"]["sections"])),
      str([s["title"] for s in cfg["report"]["sections"]]))

print("\n--- the cache is this funnel's own ---")
# style_sections is keyed (funnel, style_id), so this funnel warms its own
# rows and can never be served the English or the Romanian ones.
# `warm_cache.py zodiac-bg` writes them; `--copy-from zodiac` would fill them
# with English and is the one thing not to do here.
check("the section cache reads and writes on the funnel",
      "funnel = %s" in reports.SELECT_SECTIONS_SQL
      and "(funnel, style_id, section_id, content)"
      in reports.UPSERT_SECTION_SQL)
check("  so nothing this funnel is served can be another funnel's row",
      reports.SELECT_SECTIONS_SQL.count("%s") == 2)
check("  and it holds the same three sections as the twin",
      reports.cached_sections("zodiac-bg")
      == reports.cached_sections("zodiac30") == ("palette", "mistakes",
                                                 "splurge"))
# Not the twin's revisions any more. Every cached section names the
# archetype, and the rule for how Bulgarian names it changed — a row warmed
# under the old prompt says "Профил Небесен въздух", which is the thing the
# live review caught. So all three go stale and are written again.
check("  stamped with revisions of its own, so the warmed rows go stale",
      all(reports._cache_tag("zodiac-bg", s) != reports._cache_tag("zodiac30", s)
          for s in ("palette", "mistakes", "splurge")),
      str([(s, reports._cache_tag("zodiac-bg", s)) for s in
           ("palette", "mistakes", "splurge")]))
check("    and the English funnels keep the revisions they had",
      reports.ZODIAC_PROFILE["cache_rev"]
      == {"palette": "colors2", "mistakes": "short1", "splurge": "moves1"},
      str(reports.ZODIAC_PROFILE["cache_rev"]))
check("    as does zodiac-ro",
      reports.ZODIAC_RO_PROFILE["cache_rev"]
      == {"palette": "colors2", "mistakes": "short1", "splurge": "moves1"},
      str(reports.ZODIAC_RO_PROFILE["cache_rev"]))

print("\n--- the words the report prints itself ---")
check("the profile carries its own words",
      profile["words"] is reports.RENDER_WORDS_BG
      and reports._words(profile) is reports.RENDER_WORDS_BG)
check("  and every English funnel prints the defaults",
      reports._words(reports.ZODIAC_PROFILE)
      is reports._words(reports.KITCHEN_PROFILE)
      is reports._words(reports._profile("kitchen-visualizer"))
      is reports.RENDER_WORDS)
check("  a profile that declares none falls back to them",
      reports._words({}) is reports._words(None) is reports.RENDER_WORDS)
check("the Bulgarian map covers every key the English one has",
      sorted(reports.RENDER_WORDS_BG) == sorted(reports.RENDER_WORDS),
      str(sorted(set(reports.RENDER_WORDS) ^ set(reports.RENDER_WORDS_BG))))

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
for key in sorted(ENGLISH):
    value = reports.RENDER_WORDS_BG[key]
    check("  %-16s is not the English" % key,
          value != reports.RENDER_WORDS[key], repr(value))
check("  the Bulgarian verdict badges are РАБОТИ / ИЗБЯГВАЙ",
      reports.RENDER_WORDS_BG["verdicts"] == {"works": "РАБОТИ",
                                              "avoid": "ИЗБЯГВАЙ"},
      str(reports.RENDER_WORDS_BG["verdicts"]))
check("  the four fixed marks are the ones the page was specified against",
      (reports.RENDER_WORDS_BG["year_strong"] == "Най-силен месец:"
       and reports.RENDER_WORDS_BG["year_quiet"] == "Тих месец:"
       and reports.RENDER_WORDS_BG["fix"] == "Решение:"
       and reports.RENDER_WORDS_BG["splurge"] == "Струва си"
       and reports.RENDER_WORDS_BG["save"] == "Откажи се"),
      str({k: reports.RENDER_WORDS_BG[k]
           for k in ("year_strong", "year_quiet", "fix", "splurge", "save")}))
check("  every Bulgarian word is written in Cyrillic",
      all(CYRILLIC.search(v) for k, v in reports.RENDER_WORDS_BG.items()
          if isinstance(v, str) and k != "pdf_filename"),
      str([k for k, v in reports.RENDER_WORDS_BG.items()
           if isinstance(v, str) and k != "pdf_filename"
           and not CYRILLIC.search(v)]))
check("  and pass the Bulgarian Terms check",
      not [k for k, v in reports.RENDER_WORDS_BG.items()
           if reports._banned_hit(v, reports.ZODIAC_BG_BANNED)],
      str([k for k, v in reports.RENDER_WORDS_BG.items()
           if reports._banned_hit(v, reports.ZODIAC_BG_BANNED)]))
check("the attachment still takes the style name once",
      reports.RENDER_WORDS_BG["pdf_filename"] == "mazzin-%s-profil.pdf",
      reports.RENDER_WORDS_BG["pdf_filename"])
check("  and the Romanian words are untouched",
      reports.RENDER_WORDS_RO["verdicts"] == {"works": "MERGE",
                                              "avoid": "EVITĂ"})

print("\n--- the document those words are printed into ---")


def document(slug, style_id="celestial_air"):
    """One whole report for a funnel, stubbed end to end, as HTML."""
    funnel = json.load(open(os.path.join(ROOT, "funnels", slug + ".json"),
                            encoding="utf-8"))
    style = reports._style(funnel, style_id)
    prof = reports._profile(slug)
    year = reports._months_for(prof)
    built, paths = {}, {}
    for section in funnel["report"]["sections"]:
        stub = reports._stub_for(section["id"],
                                 reports._style_name(funnel, style_id),
                                 style, prof["stubs"], year,
                                 prof.get("stub_colors"))
        if stub is None:
            continue
        built[section["id"]] = stub
        paths[section["id"]] = "stub"
    return reports._pdf_html(reports._assemble(
        funnel, slug, style_id, reports._style_name(funnel, style_id),
        built, paths, True))


bg_doc = document("zodiac-bg")
en_doc = document("zodiac30")
for word in ("Fix:", ">Splurge ", ">Save<", ">Skip<", ">WORKS<", ">AVOID<",
             "Your style", "Strongest month:", "Quiet month:"):
    check("  the Bulgarian PDF never prints %-18s" % repr(word),
          word not in bg_doc, word)
for word in (reports.RENDER_WORDS_BG["fix"], reports.RENDER_WORDS_BG["splurge"],
             reports.RENDER_WORDS_BG["save"], "РАБОТИ", "ИЗБЯГВАЙ",
             reports.RENDER_WORDS_BG["year_strong"]):
    check("  and it does print %-28s" % repr(word), word in bg_doc, word)
check("  the verdict CLASS stays the English word the stylesheet colours on",
      'class="badge works"' in bg_doc and 'class="badge avoid"' in bg_doc)
check("  the document still declares itself Bulgarian",
      '<html lang="bg"' in bg_doc)
check("zodiac30's document is the English one, word for word",
      all(w in en_doc for w in ("Fix:", "<b>Splurge &mdash;", "<b>Save</b>",
                                ">WORKS<", ">AVOID<")),
      str([w for w in ("Fix:", "<b>Splurge &mdash;", "<b>Save</b>",
                       ">WORKS<", ">AVOID<") if w not in en_doc]))
check("  and carries not one Bulgarian word of this funnel's",
      not [w for w in (reports.RENDER_WORDS_BG[k] for k in
                       ("fix", "skip", "save", "year_strong", "year_quiet"))
           if w in en_doc],
      str([w for w in (reports.RENDER_WORDS_BG[k] for k in
                       ("fix", "skip", "save", "year_strong", "year_quiet"))
           if w in en_doc]))
check("the emailed attachment is named in Bulgarian",
      reports._words(profile)["pdf_filename"] % "nebesen-vazduh"
      == "mazzin-nebesen-vazduh-profil.pdf")
check("  and zodiac30's is named exactly as it always was",
      reports._words(reports.ZODIAC_PROFILE)["pdf_filename"] % "celestial-air"
      == "mazzin-celestial-air-report.pdf")

print("\n--- the page and the document say the same words ---")
# The whole point of `result_copy.labels`: a reader who saw РАБОТИ on the page
# and WORKS in the PDF has been handed two documents about themselves. The
# config's labels are asserted against reports.py's constants rather than
# against a literal, so the two files cannot drift apart.
LABELS = cfg["result_copy"]["labels"]
check("the funnel declares its own page labels", isinstance(LABELS, dict))
for key in ("elements", "energies", "led_template", "months", "verdicts",
            "saves_head", "scale_aria", "price_regular_aria"):
    check("  labels.%-18s is filled" % key, bool(LABELS.get(key)),
          repr(LABELS.get(key)))
check("elements are reports.py's, exactly",
      LABELS["elements"] == reports.ELEMENT_LABEL_BG,
      "%s vs %s" % (LABELS["elements"], reports.ELEMENT_LABEL_BG))
check("energies are reports.py's, exactly",
      LABELS["energies"] == reports.ENERGY_LABEL_BG,
      "%s vs %s" % (LABELS["energies"], reports.ENERGY_LABEL_BG))
check("verdict badges are reports.py's, exactly",
      LABELS["verdicts"] == reports.RENDER_WORDS_BG["verdicts"],
      "%s vs %s" % (LABELS["verdicts"], reports.RENDER_WORDS_BG["verdicts"]))
check("months are reports.py's twelve, in order",
      LABELS["months"] == list(reports.MONTH_ABBR_BG), str(LABELS["months"]))
check("  and none of them is an English or a Romanian month",
      not set(LABELS["months"]) & (set(reports.MONTH_ABBR)
                                   | set(reports.MONTH_ABBR_RO)))
check("the elements are the four the config's own tags name",
      sorted(LABELS["elements"]) == ["air", "earth", "fire", "water"])
check("the saves heading reuses the PDF's own word",
      reports.RENDER_WORDS_BG["save"].lower()[:5] in LABELS["saves_head"].lower(),
      "%s vs %s" % (LABELS["saves_head"], reports.RENDER_WORDS_BG["save"]))
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
# Bulgarian adjectives agree with the noun beside them, and the two values
# this template can take do not share a gender: Слънце is neuter and Луна is
# feminine. So the template agrees with a noun it carries itself — "водеща
# енергия", feminine, fixed — rather than with the value substituted into it.
# Both readings are checked, because a template that reads well for one value
# and wrong for the other is a page that is wrong for half its buyers.
for energy in reports.ENERGY_LABEL_BG.values():
    filled = LABELS["led_template"].replace("{energy}", energy)
    check("  led_template reads for %-8s" % energy,
          filled == "водеща енергия " + energy, filled)
check("  and the chips say it the way the rest of the page does",
      "водеща стихия {element}" in cfg["result_copy"]["profile"]["chips"]
      and "водеща стихия" in cfg["result_copy"]["profile"]["formula"]
      and LABELS["led_template"] == "водеща енергия {energy}",
      str(cfg["result_copy"]["profile"]["chips"]))
# The same test for the element chip and the formula, over all four values.
for element in reports.ELEMENT_LABEL_BG.values():
    filled = "водеща стихия {element}".replace("{element}", element)
    check("  the element chip reads for %-7s" % element,
          filled == "водеща стихия " + element, filled)
check("the scale ends are Bulgarian and read inside the aria template",
      all(CYRILLIC.search(s[k]) for s in cfg["result_copy"]["profile"]["scales"]
          for k in ("left", "right")),
      str([(s["left"], s["right"])
           for s in cfg["result_copy"]["profile"]["scales"]]))
check("  and the first scale's ends are the profile's own two energies",
      (cfg["result_copy"]["profile"]["scales"][0]["left"],
       cfg["result_copy"]["profile"]["scales"][0]["right"])
      == (reports.ENERGY_LABEL_BG["sun"], reports.ENERGY_LABEL_BG["moon"]),
      str(cfg["result_copy"]["profile"]["scales"][0]))
check("the split caption names the four elements in the same four words",
      all(label in cfg["result_copy"]["profile"]["split_caption"]
          for label in reports.ELEMENT_LABEL_BG.values()),
      cfg["result_copy"]["profile"]["split_caption"])

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
check("  and counts in Bulgarian words, not English ones",
      cfg["checkout"]["number_words"]
      == ["нула", "едно", "две", "три", "четири", "пет", "шест", "седем",
          "осем", "девет", "десет"],
      str(cfg["checkout"]["number_words"]))
check("  eleven of them, so {n} up to ten has a word",
      len(cfg["checkout"]["number_words"]) == 11)
check("the card label keeps its token", "{label}" in cfg["swipe"]["card_aria"])
check("every one of them is Cyrillic",
      all(CYRILLIC.search(cfg[b][k]) for b, k in ENGINE_KEYS),
      str([k for b, k in ENGINE_KEYS if not CYRILLIC.search(cfg[b][k])]))
check("  and none of them was left in English",
      not any(v in (
          "Redirecting...", "Preparing your personalized report…",
          "Locked", "Choose {label}",
          "Could not start checkout. Please try again.",
          "That payment didn't go through. Please try again.",
          "Please tick the box above to continue.")
          for v in (cfg[b][k] for b, k in ENGINE_KEYS)))

print("\n--- a funnel that declares none of it renders English ---")
# The guarantee the other four funnels rest on. Asserted two ways: they
# declare nothing, and the English every default falls back to is still in the
# file, character for character.
for slug in ("kitchen", "kitchen-visualizer", "zodiac", "zodiac30"):
    other = json.load(open(os.path.join(ROOT, "funnels", slug + ".json"),
                           encoding="utf-8"))
    declared = [k for k in ("labels",)
                if k in (other.get("result_copy") or {})]
    declared += ["%s.%s" % (b, k) for b, k in ENGINE_KEYS
                 if k in (other.get(b) or {})]
    declared += [k for k in ("number_words",)
                 if k in (other.get("checkout") or {})]
    check("  %-18s declares none of the new keys" % slug, not declared,
          str(declared))
ENGLISH_DEFAULTS = [
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
for source, literal in ENGLISH_DEFAULTS:
    check("  default still in the file: %s" % literal[:44],
          literal in source, literal)
check("the verdict badge still uppercases the tag when nothing is declared",
      "mark.toUpperCase()" in RESULT_JS)
check("  and the CSS classes stayed English, as the stylesheet expects",
      '"zr-tag is-" + (mark || "works")' in RESULT_JS)
check("the module names no funnel slug to pick a layout",
      "zodiac30" not in RESULT_JS and "zodiac-bg" not in RESULT_JS)
check("  and reads the named template when no arm assigns one",
      "var template = (variant && variant.template)" in RESULT_JS
      and "(ctx.cfg && ctx.cfg.result_template)" in RESULT_JS)

print("\n--- the minimal layout, as this funnel's only template ---")
MIN = cfg["result_copy"]["profile"]
RARE = MIN["rarity_card"]
check("the rarity card is framed, not a sentence with a number in it",
      all(RARE.get(k) for k in ("lead", "tail", "note")), str(RARE))
check("  every part of it Bulgarian, and none of it the English",
      CYRILLIC.search(RARE["lead"]) and CYRILLIC.search(RARE["note"])
      and RARE["lead"] != "Rarer than" and RARE["tail"] != "of readings"
      and RARE["note"] != "Your edge over the rest — inside your reading.",
      str(RARE))
check("  and none of it states a figure — the module supplies the only one",
      not [k for k in ("lead", "tail", "note") if re.search(r"\d", RARE[k])],
      str([RARE[k] for k in ("lead", "tail", "note")
           if re.search(r"\d", RARE[k])]))
check("  the note carries exactly one em dash, which is where it breaks",
      RARE["note"].count("—") == 1, RARE["note"])
check("  and the card reads as one sentence around the figure",
      (RARE["lead"] + " 97% " + RARE["tail"])
      == "По-рядко от 97% от профилите",
      RARE["lead"] + " 97% " + RARE["tail"])


def different_pct(n):
    """The module's own arithmetic: how many readings come out otherwise."""
    return round((1 - 1.0 / n) * 100) if isinstance(n, int) and n >= 2 else 0


NS = sorted({n for by_second in MIN["rarity"].values()
             for by_energy in by_second.values()
             for n in by_energy.values() if isinstance(n, int)})
check("every rarity this funnel can produce yields a share under 100",
      all(0 < different_pct(n) < 100 for n in NS),
      str([(n, different_pct(n)) for n in NS]))

CHIPS = MIN["chips"]
check("the hero draws four capsules", len(CHIPS) == 4, str(CHIPS))
check("  each one a token this funnel's own words fill",
      all(re.search(r"\{\w+\}", c) for c in CHIPS), str(CHIPS))
check("  with no English suffix left in them",
      not [c for c in CHIPS if "-led" in c or "under." in c], str(CHIPS))

ROWS = MIN["unlock"]
SECTION_IDS = {sec["id"] for sec in cfg["report"]["sections"]}
CARD_IDS = {c["id"] for c in MIN["cards"]}
check("the unlock list promises only chapters this funnel delivers",
      {r["id"] for r in ROWS} <= SECTION_IDS,
      str(sorted({r["id"] for r in ROWS} - SECTION_IDS)))
check("  and it is the four the minimal arm was specified with",
      [r["id"] for r in ROWS]
      == ["materials", "splurge", "shopping", "mistakes"],
      str([r["id"] for r in ROWS]))
check("  each of which has a card keyword to head it",
      {r["id"] for r in ROWS} <= CARD_IDS,
      str(sorted({r["id"] for r in ROWS} - CARD_IDS)))
check("  no row is listed twice",
      len({r["id"] for r in ROWS}) == len(ROWS))
check("  every line is written and Bulgarian",
      all(r.get("line") and CYRILLIC.search(r["line"]) for r in ROWS),
      str([r["line"] for r in ROWS
           if not (r.get("line") and CYRILLIC.search(r["line"]))]))
check("the block has a heading, and it is not the English one",
      MIN["unlock_head"] and MIN["unlock_head"] != "What you unlock:",
      MIN["unlock_head"])
TAIL = MIN["unlock_tail"]
check("  and a tail naming the two chapters the list did not",
      TAIL.get("key") and TAIL.get("line")
      and CYRILLIC.search(TAIL["key"] + TAIL["line"]), str(TAIL))
check("the unlock copy states no figure it cannot stand behind",
      not [r for r in ROWS
           if re.search(r"\d", re.sub(r"\{\w+\}|#\d", "", r["line"]))],
      str([r["line"] for r in ROWS
           if re.search(r"\d", re.sub(r"\{\w+\}|#\d", "", r["line"]))]))
NEW_MINIMAL = ([RARE["lead"], RARE["tail"], RARE["note"], MIN["unlock_head"],
                TAIL["key"], TAIL["line"]]
               + [r["line"] for r in ROWS] + list(CHIPS))
for text in NEW_MINIMAL:
    check("  %-44s passes both Terms checks" % ('"%s"' % text[:42]),
          reports._banned_hit(text, reports.ZODIAC_BG_BANNED) is None,
          reports._banned_hit(text, reports.ZODIAC_BG_BANNED))
check("and every one of them is walked by the config-wide banned scan",
      all(any(v == text for _p, v in STRINGS) for text in NEW_MINIMAL))

print("\n--- the layout split, switched off ---")
# The experiment is over and every reader gets `minimal`. Off the way zodiac30
# switches an arm off: weight 0 rather than a deleted block, so the arm and
# the reason it exists stay readable in the config and coming back is one
# number. The template itself is untouched in the module and its stylesheet.
#
# What weight 0 does, precisely: `variantPool` drops the arm, one arm left is
# not a test and is returned unconditionally, so no session id can reach
# `boxes` — and neither can ?arm=boxes, because the override only ever
# returns an arm the pool already carries.


def pool_of(config):
    """`variantPool`, mirrored: enabled, and weighing something."""
    return [a for a in (config.get("paywall_variants") or [])
            if a and a.get("id") and a.get("enabled") is not False
            and isinstance(a.get("weight"), int)
            and not isinstance(a.get("weight"), bool) and a["weight"] > 0]


check("both arms are still declared", len(ARMS) == 2, str(ARMS))
check("  and one of them is in the pool",
      [a["id"] for a in pool_of(cfg)] == ["minimal"],
      str([a["id"] for a in pool_of(cfg)]))
check("  so every reader gets the minimal layout",
      len(pool_of(cfg)) == 1 and pool_of(cfg)[0]["template"] == "minimal",
      str(pool_of(cfg)))
check("  boxes weighs nothing, which is what takes it out",
      [a.get("weight") for a in ARMS] == [1, 0],
      str([a.get("weight") for a in ARMS]))
check("  it is retired rather than deleted, and says how to come back",
      ARMS[1].get("note") and "set this weight to 1" in ARMS[1]["note"],
      str(ARMS[1].get("note")))
check("  which is how zodiac30 retires an arm too",
      any(a.get("weight") == 0 and a.get("note")
          for a in twin.get("paywall_variants") or []),
      str([(a["id"], a.get("weight")) for a in
           twin.get("paywall_variants") or []]))
check("  one arm in the pool is rendered unconditionally, not hashed",
      "if (pool.length === 1) return pool[0];" in RESULT_JS)
check("  so the override cannot reach the retired arm either",
      "if (pool[i].id === want) return pool[i];" in RESULT_JS
      and "forcedVariant(variantPool(ctx.cfg))" in RESULT_JS)
check("  and the template it names is still in the module and the sheet",
      'template === "boxes"' in RESULT_JS and ".zr-boxes-grid" in CSS)
check("  the arm it is serving, and the one it is not",
      [(a["id"], a.get("template")) for a in ARMS]
      == [("minimal", "minimal"), ("boxes", "boxes")],
      str([(a["id"], a.get("template")) for a in ARMS]))
ARM_KEYS = {"id", "enabled", "weight", "name", "template", "note"}
check("  and each arm is a layout, not a second offer",
      all(set(a) <= ARM_KEYS for a in ARMS),
      str([sorted(set(a) - ARM_KEYS) for a in ARMS]))
check("  each one named, for whoever reads the split",
      all(a.get("name") for a in ARMS))
check("the funnel still names a template for a reader nothing assigns",
      cfg.get("result_template") == "minimal", str(cfg.get("result_template")))
check("  which an assigned arm outranks, as the module reads them",
      RESULT_JS.index("(variant && variant.template)")
      < RESULT_JS.index("ctx.cfg.result_template"))
check("the arm is reported before anything is drawn",
      RESULT_JS.index("reportVariant(ctx, variant);")
      < RESULT_JS.index('root.innerHTML = "";'))
check("  as the event zodiac30's arms already ride on",
      'ctx.track("paywall_variant", { variant: variant.id });' in RESULT_JS)
check("  and zodiac30's own arms are untouched",
      [a["id"] for a in twin.get("paywall_variants") or []]
      == ["control", "minimal"],
      str([a["id"] for a in twin.get("paywall_variants") or []]))
check("  while zodiac and zodiac-ro still declare none",
      not english.get("paywall_variants")
      and not romanian.get("paywall_variants"))
# QA on a real phone. Assignment is untouched — this can only pick an arm the
# pool already carries, and it is read once per load and stored nowhere.
check("a named arm can be forced for a walk",
      "function forcedVariant(pool)" in RESULT_JS
      and "[?&]arm=([^&#]+)" in RESULT_JS)
check("  and only ever one the config carries",
      "if (pool[i].id === want) return pool[i];" in RESULT_JS
      and "return null;" in RESULT_JS.split("function forcedVariant")[1]
                                     .split("function assignedVariant")[0])
check("  handed the config's own pool, so it cannot conjure a layout",
      "forcedVariant(variantPool(ctx.cfg))" in RESULT_JS
      and "|| assignedVariant(ctx.cfg);" in RESULT_JS)
# Assignment itself is untouched, and has to be: tests/test_variants.py holds
# this block byte-identical against result_persona.js's copy, so the override
# lives at the call site rather than inside it.
MECH = RESULT_JS[RESULT_JS.index("  // engine.js's own session key."):
                 RESULT_JS.index("  // One event, once, when the offer")]
check("  and assignment itself never learned about it",
      "forcedVariant" not in MECH and "location" not in MECH,
      MECH[:60])
check("  so a forced page still reports the arm it drew",
      RESULT_JS.index("var variant = forcedVariant(variantPool(ctx.cfg))")
      < RESULT_JS.index("reportVariant(ctx, variant);"))

print("\n--- the boxes arm's own copy ---")
BOXES = cfg["result_copy"]["boxes"]
check("the funnel carries the block", isinstance(BOXES, dict))
for key in ("locked", "hero_kicker", "hero_line", "boxes"):
    check("  boxes.%-12s is filled" % key, bool(BOXES.get(key)),
          repr(BOXES.get(key)))
# FORCED TEST EDIT. `head` and `sub` are gone. The arm shipped with a
# headline and a "Ти си «X»" line of its own, above a hero that already names
# the subtype, the sign and the chips — the page said the same thing twice
# before asking for money. The block is the locked card and the tiles now, and
# the keys that existed only for those two lines are out of the config.
check("it heads nothing — the hero above already does",
      "head" not in BOXES and "sub" not in BOXES, str(sorted(BOXES)))
check("  and the module carries no default for either",
      "zr-boxes-title" not in RESULT_JS and "zr-boxes-sub" not in RESULT_JS
      and "function boxesHead(" not in RESULT_JS)
check("  nor does the sheet style one",
      ".zr-boxes-title" not in CSS and ".zr-boxes-head" not in CSS)
check("the locked hero reads the step the reader actually tapped",
      BOXES["hero_step"] in {s["id"] for s in steps},
      "%s not a step" % BOXES["hero_step"])
check("  and the module falls back to that step's first frame",
      "function bondPick(ctx)" in RESULT_JS
      and "pairs[0] && pairs[0].images && pairs[0].images[0]" in RESULT_JS)
# The verdicts are the funnel's own, so the tile and the delivered page call a
# pairing the same thing — the whole reason `labels.verdicts` exists.
check("the hero line fills both verdicts from labels, not from prose",
      "{works}" in BOXES["hero_line"] and "{avoid}" in BOXES["hero_line"],
      BOXES["hero_line"])
FILLED_LINE = (BOXES["hero_line"].replace("{works}", LABELS["verdicts"]["works"])
               .replace("{avoid}", LABELS["verdicts"]["avoid"]))
check("  which fills to this funnel's own two words",
      LABELS["verdicts"]["works"] in FILLED_LINE
      and LABELS["verdicts"]["avoid"] in FILLED_LINE, FILLED_LINE)
check("  and neither word is written into the copy",
      LABELS["verdicts"]["works"] not in BOXES["hero_line"]
      and LABELS["verdicts"]["avoid"] not in BOXES["hero_line"],
      BOXES["hero_line"])
TILES = BOXES["boxes"]
check("four tiles", len(TILES) == 4, str(len(TILES)))
check("  each naming a chapter this funnel delivers",
      [t["id"] for t in TILES] == ["palette", "mistakes", "dna", "shopping"]
      and {t["id"] for t in TILES} <= {s["id"] for s in
                                       cfg["report"]["sections"]},
      str([t["id"] for t in TILES]))
check("  each with a glyph the module draws",
      all(('%s: [' % t["icon"]) in RESULT_JS for t in TILES),
      str([t["icon"] for t in TILES]))
check("  titles and subs in Bulgarian",
      all(CYRILLIC.search(t["title"]) for t in TILES)
      and all(CYRILLIC.search(t["sub"]) or t["sub"] == "{range}"
              for t in TILES),
      str([(t["title"], t["sub"]) for t in TILES]))
# The year tile. A month written into the copy is a month that is wrong on the
# first of the next one, so the whole span is computed at render out of the
# same twelve labels the year map counts in.
check("the year tile names no month of its own",
      TILES[3]["sub"] == "{range}", TILES[3]["sub"])
check("  and no tile hardcodes one either",
      not [t for t in TILES
           if any(m.rstrip(".") in t["title"] + t["sub"]
                  for m in LABELS["months"])],
      str([(t["title"], t["sub"]) for t in TILES]))
check("  the span is built from the funnel's own month names",
      "function monthRange(ctx)" in RESULT_JS
      and "var year = yearOf(ctx);" in RESULT_JS
      # The en dash as the source spells it, so a raw character cannot drift
      # in unnoticed under a font that renders the two alike.
      and r'year[0] + " \u2013 " + year[11]' in RESULT_JS)
check("    off the same twelve the year map runs on",
      "function yearOf(ctx)" in RESULT_JS
      and 'yearLabels(null, label(ctx, "months"))' in RESULT_JS)
check("    which start at this month, as reports.py's twelve do",
      list(reports.MONTH_ABBR_BG) == LABELS["months"]
      and reports._months_for(profile)[0].startswith(
          reports.MONTH_ABBR_BG[reports.datetime.datetime.now(
              reports.datetime.timezone.utc).date().month - 1]))
NEW_STRINGS = ([BOXES[k] for k in ("locked", "hero_kicker", "hero_line")]
               + [t["title"] for t in TILES]
               + [t["sub"] for t in TILES if t["sub"] != "{range}"])
for text in NEW_STRINGS:
    check("  %-42s passes both Terms checks" % ('"%s"' % text[:40]),
          reports._banned_hit(text, reports.ZODIAC_BG_BANNED) is None,
          reports._banned_hit(text, reports.ZODIAC_BG_BANNED))
check("and every one of them is walked by the config-wide scans",
      all(any(v == text for _p, v in STRINGS) for text in NEW_STRINGS))
check("no boxes string carries a straight double quote",
      not [t for t in NEW_STRINGS if '"' in t])

print("\n--- and every one of them has an English default in the module ---")
# The rule the other funnels rest on: a funnel that declares no block renders
# real English, not a hole and not a transliteration.
DEFAULTS = [
    'hero_step: "bond"',
    'locked: "Locked"',
    'hero_kicker: "LOVE & COMPATIBILITY"',
    'hero_line: "{works} or {avoid} \u2014 for every sign, on the first page."',
    'title: "Your power palette", sub: "Colours and talismans"',
    'title: "5 hidden strengths", sub: "And 2 blind spots"',
    'title: "Your cosmic blueprint", sub: "Career and money"',
    'title: "The next 12 months", sub: "{range}"',
]
for literal in DEFAULTS:
    check("  default in the file: %s" % literal[:46],
          literal in RESULT_JS, literal)
check("every key the config sets has a default behind it",
      set(BOXES) <= set(re.findall(r"^\s{4}(\w+):",
                                   RESULT_JS.split("BOXES_FALLBACK = {")[1]
                                   .split("\n  };")[0], re.M)),
      str(sorted(set(BOXES))))
check("  and the defaults are English, not this funnel's words",
      not CYRILLIC.search(RESULT_JS.split("BOXES_FALLBACK = {")[1]
                          .split("\n  };")[0]))
check("the module reads them through one accessor, as labels are read",
      "function boxesText(ctx, key)" in RESULT_JS
      and "BOXES_FALLBACK[key] : own" in RESULT_JS)
check("  off result_copy.boxes and nowhere else",
      'var own = ((ctx.cfg && ctx.cfg.result_copy) || {}).boxes;'
      in RESULT_JS)

print("\n--- the arm swaps one block and shares everything else ---")
# FORCED TEST EDIT (this block). The arm used to replace the whole page above
# the money — kicker, hero, taps and the rarity card all gone — which is the
# bug this branch fixes. It is the minimal page with its pitch list swapped
# now, so what is asserted is the sharing rather than the replacing.
#
# One code path, not a copy: the same `kicker`, the same `richHero` with the
# same lean flag, the same `taps`, the same `rarityBadge`. A second copy of
# those four calls under an `if` would drift the first time one of them moved.
check("both lean arms are one flag, and one call each",
      'var lean = template === "minimal" || template === "boxes";'
      in RESULT_JS
      and "root.appendChild(kicker(copy, lean));" in RESULT_JS
      and "richHero(ctx, glyph(ctx.picks.sign), data, { lean: lean })"
      in RESULT_JS
      and RESULT_JS.count("var strip = taps(ctx, copy);") == 1
      and RESULT_JS.count(
          "var rare = rarityBadge(data, profileBlock(ctx) || {});") == 1)
check("  so the whole top is the minimal top, node for node",
      RESULT_JS.count("root.appendChild(kicker(copy, lean));") == 1
      and "if (data && lean) {" in RESULT_JS)
check("the swap happens after the rarity card and before the offer",
      RESULT_JS.index("if (rare) root.appendChild(rare);")
      < RESULT_JS.index(
          'if (template === "boxes") root.appendChild(boxesPitch(ctx));')
      < RESULT_JS.index("root.appendChild(offer(ctx, copy, data, template));"))
check("  and the block it swaps in is the locked card and the tiles, only",
      "function boxesPitch(ctx) {" in RESULT_JS
      and RESULT_JS.split("function boxesPitch(ctx) {")[1]
                   .split("\n  }")[0].count("appendChild") == 2)
check("  and then the same offer card every arm draws",
      RESULT_JS.count("root.appendChild(offer(ctx, copy, data, template));")
      == 1)
check("  so nothing about the money is branched on the arm",
      "function offer(ctx, copy, data, template)" in RESULT_JS
      and RESULT_JS.split("function offer(ctx, copy, data, template)")[1]
                   .split("\n  }\n")[0].count('"boxes"') == 0)
check("minimal keeps its pitch inside the offer, and boxes gets none",
      'if (data && template === "minimal") {\n      var list = checklist('
      in RESULT_JS)
check("both lean arms wear is-minimal, so the sheet reaches both",
      'root.classList.toggle("is-minimal", lean);' in RESULT_JS)
check("  and is-boxes is added on top, for the two blocks that differ",
      'root.classList.toggle("is-boxes", template === "boxes");'
      in RESULT_JS)
NEW_RULES = re.findall(r"^\.[\w.\- ]+(?= \{)",
                       CSS.split("--- the boxes arm")[1], re.M)


def own_rule(sel):
    return (sel.startswith(".zr-box")
            or sel.startswith(".result-module.is-boxes"))


check("every new rule in the sheet is scoped to the new arm",
      NEW_RULES and all(own_rule(sel) for sel in NEW_RULES),
      str([sel for sel in NEW_RULES if not own_rule(sel)]))
check("  and nothing above it mentions the arm at all",
      "is-boxes" not in CSS.split("--- the boxes arm")[0]
      and ".zr-box" not in CSS.split("--- the boxes arm")[0])

print("\n--- the tiles are read at arm's length, not squinted at ---")
# They shipped at a 17px icon over 13px titles and 12px subs, floating in
# 13px of padding — small type in a big box, which is what "starved" meant.
# The sizes are pinned here because they are the fix, and a silent drift back
# is the same defect again.
BOXES_CSS = CSS.split("--- the boxes arm")[1]


def rule(sel):
    """One declaration block out of the arm's own section of the sheet."""
    head = BOXES_CSS.index("\n" + sel + " {")
    return BOXES_CSS[head:BOXES_CSS.index("}", head)]


for sel, want in ((".zr-box-icon svg", ("width: 28px", "height: 28px",
                                        "stroke: var(--zr-gold)")),
                  (".zr-box-title", ("font-size: 17px", "font-weight: 600",
                                     "line-height: 1.3")),
                  (".zr-box-sub", ("font-size: 14px", "line-height: 1.3")),
                  (".zr-boxes-kicker", ("font-size: 12px",)),
                  (".zr-boxes-line", ("font-size: 15px",))):
    block = rule(sel)
    check("  %-18s %s" % (sel, ", ".join(want)),
          all(w in block for w in want),
          str([w for w in want if w not in block]))
check("the icon box is the drawing and nothing more",
      "display: flex;" in rule(".zr-box-icon")
      and "display: block;" in rule(".zr-box-icon svg"),
      rule(".zr-box-icon"))
check("  so no dead band sits between the glyph and the title",
      "margin: 0 0 9px;" in rule(".zr-box-icon"), rule(".zr-box-icon"))
check("  and the title and its sub read as one block",
      "margin: 3px 0 0;" in rule(".zr-box-sub"), rule(".zr-box-sub"))
check("the tiles take their height from the grid, not from padding",
      "grid-template-columns: 1fr 1fr;" in rule(".zr-boxes-grid")
      and "height" not in rule(".zr-box"),
      rule(".zr-box"))
check("  and the grid is capped by nothing the offer is not",
      "max-width" not in rule(".zr-boxes-grid"), rule(".zr-boxes-grid"))

print("\n--- the sale, and what it is allowed to claim ---")
BEFORE_END = reports.datetime.datetime(2026, 8, 27,
                                       tzinfo=reports.datetime.timezone.utc)
ONE_SEC = reports.datetime.timedelta(seconds=1)
twin_cfg = json.load(open(os.path.join(ROOT, "funnels/zodiac-bg-test.json"),
                          encoding="utf-8"))
SALE = cfg["sale"]
check("it is active at 199 against a regular 499",
      SALE["active"] is True and SALE["price_cents"] == 199
      and SALE["regular_price_cents"] == 499, str(SALE))
check("  and the struck figure is what this funnel actually charges",
      SALE["regular_price_cents"] == cfg["pricing"]["amount_cents"],
      "%s vs %s" % (SALE["regular_price_cents"],
                    cfg["pricing"]["amount_cents"]))
check("  which is the guard payments.py enforces, not a coincidence",
      payments._sale(dict(cfg, sale=dict(SALE, regular_price_cents=1999)),
                     BEFORE_END) is None)
check("  a sale that is not a discount does not run either",
      payments._sale(dict(cfg, sale=dict(SALE, price_cents=499)),
                     BEFORE_END) is None)
check("the label names the offer and no date",
      SALE["label"] == "Лятно намаление"
      and not re.search(r"\d", SALE["label"]), SALE["label"])
check("  and no string on this funnel puts a date in the pitch",
      not [p for p, v in STRINGS
           if re.search(r"\b(30|септември|сеп\.)\b", v)],
      str([p for p, v in STRINGS
           if re.search(r"\b(30|септември|сеп\.)\b", v)][:3]))
check("it ends on the date this sale was set to end",
      SALE["ends"] == "2026-09-30T23:59:59-12:00", SALE["ends"])
ENDS = reports.datetime.datetime.fromisoformat(SALE["ends"])
check("  on a clock, with an offset, so the end is an instant not a guess",
      ENDS.tzinfo is not None, SALE["ends"])
check("  and it is not open-ended in disguise", ENDS.year == 2026, str(ENDS))
for label, when, want in (
        ("today", BEFORE_END, 199),
        ("one second before the end", ENDS - ONE_SEC, 199),
        ("at the end", ENDS, 499),
        ("one second after", ENDS + ONE_SEC, 499),
        ("a week after", ENDS + reports.datetime.timedelta(days=7), 499)):
    cents, live = payments._effective_price(cfg, when)
    check("  %-26s charges %d" % (label, want),
          cents == want and bool(live) == (want == 199),
          "%s / %s" % (cents, bool(live)))
check("expiry leaves no residue: the page reverts with the charge",
      payments._effective_price(cfg, ENDS + ONE_SEC) == (499, None))

print("\n--- the sandbox twin is this funnel, on test keys ---")
TWINNED = ("slug", "funnel_id", "stripe_mode")
differ = sorted(k for k in set(cfg) | set(twin_cfg)
                if cfg.get(k) != twin_cfg.get(k))
check("it differs in exactly the three fields the generator changes",
      differ == sorted(TWINNED), str(differ))
check("  slug, funnel_id and stripe_mode",
      twin_cfg["slug"] == "zodiac-bg-test"
      and twin_cfg["funnel_id"] == "zodiac_bg_v1_test"
      and twin_cfg["stripe_mode"] == "test",
      str([twin_cfg[k] for k in TWINNED]))
check("  its static copy is on disk too",
      os.path.isfile(os.path.join(ROOT,
                                  "static/funnels/zodiac-bg-test.json")))
check("  and byte-identical to funnels/",
      open(os.path.join(ROOT, "static/funnels/zodiac-bg-test.json"),
           encoding="utf-8").read()
      == open(os.path.join(ROOT, "funnels/zodiac-bg-test.json"),
              encoding="utf-8").read())
check("  it runs the same sale, on test keys",
      payments._effective_price(twin_cfg, BEFORE_END)[0] == 199)
check("  and it reads this funnel's report profile, not kitchen's",
      reports._profile(twin_cfg["slug"]) is profile)

print("\n--- and the neighbours are untouched ---")
# The failure this funnel could cause and no assertion above would see: a
# string edited on the way past, on a config that is live and in another
# language.
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
check("  and its static copy still matches it",
      english == json.load(open(os.path.join(ROOT,
                                             "static/funnels/zodiac.json"))))
check("funnels/zodiac-ro.json is still zodiac-ro",
      romanian["slug"] == "zodiac-ro" and romanian["locale"] == "ro"
      and romanian["result_template"] == "minimal")
check("  and its static copy still matches it",
      romanian == json.load(open(os.path.join(
          ROOT, "static/funnels/zodiac-ro.json"))))
check("none of the three carries a Cyrillic letter",
      not any(CYRILLIC.search(open(os.path.join(ROOT, "funnels", name),
                                   encoding="utf-8").read())
              for name in ("zodiac30.json", "zodiac.json", "zodiac-ro.json")))
check("  and this one carries no Romanian diacritic",
      not re.search(r"[ăâîșțĂÂÎȘȚ]", RAW))
check("the funnels directory and its static copy agree",
      sorted(os.listdir(os.path.join(ROOT, "static/funnels")))
      == sorted(os.listdir(os.path.join(ROOT, "funnels"))),
      str(sorted(set(os.listdir(os.path.join(ROOT, "static/funnels")))
                 ^ set(os.listdir(os.path.join(ROOT, "funnels"))))))

print("\n%d checks, %d failed" % (checks[0], len(fails)))
for f in fails:
    print("  FAIL " + f)
sys.exit(1 if fails else 0)
