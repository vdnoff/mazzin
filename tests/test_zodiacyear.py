#!/usr/bin/env python3
"""The year that starts now, the sheet that is a grid, and the two chapters
that answer their own question.

Four things that all happen server-side and none of which a browser can see:

  * the twelve months a purchase's year map runs over, counted from the month
    it happened in, and the check that holds the model to them;
  * the contact sheet's layout in print, asserted on the rendered box tree
    rather than on the markup — six equal squares to a row is a property of
    the boxes, and the markup that produced 5/5/5/3 looked correct;
  * the second half Love and Money grew — a how-to-play-it beside every sign,
    three concrete moves beside the work — in the stubs, in the prompts and
    inside the budgets;
  * that none of it costs a cache row.

No database, no network, no Stripe, no model. The one clock this reads is
stubbed to a fixed date, because a suite that passes in October and fails on
the first of November is not a suite.

    python3 tests/test_zodiacyear.py
"""
import datetime
import json
import os
import re
import sys

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, REPO)

import config                                              # noqa: E402
import reports                                             # noqa: E402
import weasyprint                                          # noqa: E402

FUNNELS = ("zodiac", "zodiac30")
CFG = {slug: config.load_funnel(slug) for slug in FUNNELS}

# A date with a rollover in the middle of it: three months in one year, nine
# in the next. Every label below is arithmetic off this and nothing else.
FIXED = datetime.date(2026, 11, 3)
WANT = ["Nov 2026", "Dec 2026", "Jan 2027", "Feb 2027", "Mar 2027",
        "Apr 2027", "May 2027", "Jun 2027", "Jul 2027", "Aug 2027",
        "Sep 2027", "Oct 2027"]

fails = []
checks = [0]


def check(label, ok, detail=""):
    checks[0] += 1
    if not ok:
        fails.append("%s %s" % (label, detail))
    print("  %-66s %s%s" % (label, "ok" if ok else "FAIL",
                            ("  " + str(detail)) if not ok else ""))


def offline():
    """No database and no model."""
    reports.database.execute = lambda *a, **kw: None
    reports.database.query_all = lambda *a, **kw: []
    reports._api = lambda: None


def run_of(slug, style_id, sign="sign_leo"):
    """One stored report row, from a full run, with the clock held still."""
    cfg = CFG[slug]
    choices = [(sign if step["id"] == "sign"
                else step["pairs"][0]["images"][0]["id"])
               for step in cfg["swipe"]["steps"]]
    real = reports._year_labels
    reports._year_labels = lambda today=None: real(FIXED)
    try:
        return reports.start_report(1, slug, style_id,
                                    {"water": 9, "moon": 6, "mystic": 4},
                                    choices=choices)
    finally:
        reports._year_labels = real


# --- a) the twelve months ---------------------------------------------------

print("\n--- the year starts in the month they bought it ---")
check("twelve labels, from this month", reports._year_labels(FIXED) == WANT,
      str(reports._year_labels(FIXED)))
check("  the first is the month they are living through", WANT[0] == "Nov 2026")
check("  and the year rolls over inside the list, not at its edge",
      [label.split()[1] for label in WANT].count("2026") == 2
      and [label.split()[1] for label in WANT].count("2027") == 10)
check("every label carries its year, because four of them are in the next",
      all(re.match(r"^[A-Z][a-z]{2} \d{4}$", label) for label in WANT))
# The three edges: a January start rolls nowhere, a December start rolls
# immediately, and every month of the year produces twelve distinct labels.
jan = reports._year_labels(datetime.date(2027, 1, 15))
check("a January purchase gets a calendar year",
      jan[0] == "Jan 2027" and jan[-1] == "Dec 2027", "%s..%s" % (jan[0],
                                                                  jan[-1]))
check("  a December one rolls on the second month",
      reports._year_labels(datetime.date(2026, 12, 31))[:2]
      == ["Dec 2026", "Jan 2027"])
ragged = [month for month in range(1, 13)
          if len(set(reports._year_labels(
              datetime.date(2026, month, 1)))) != 12]
check("  and no start month repeats a label", not ragged, str(ragged))
check("the abbreviations are the twelve English ones, in order",
      list(reports.MONTH_ABBR)
      == [datetime.date(2026, m, 1).strftime("%b") for m in range(1, 13)],
      str(reports.MONTH_ABBR))

print("\n--- and the model is handed them, not asked to guess ---")
block = reports._year_block(WANT)
check("the block names all twelve, in order",
      all(("%2d. %s" % (n, label)) in block
          for n, label in enumerate(WANT, 1)), block[:120])
check("  and says they are the only twelve",
      "no others and none missing" in block and "never reorder" in block)
check("  a funnel with no year gets no block", reports._year_block(None) is None
      and reports._year_block([]) is None)
style = reports._style(CFG["zodiac"], "deep_water")
name = reports._style_name(CFG["zodiac"], "deep_water")
steps = CFG["zodiac"]["swipe"]["steps"]
choices = [("sign_leo" if s["id"] == "sign"
            else s["pairs"][0]["images"][0]["id"]) for s in steps]
year_prompt = reports._section_prompt(style, name, {"water": 9}, "shopping",
                                      CFG["zodiac"], choices, "zodiac", WANT)
check("the year section's prompt carries the block",
      all(label in year_prompt for label in WANT), "Nov 2026" in year_prompt)
check("  and no other section does",
      not any("Nov 2026" in reports._section_prompt(
          style, name, {"water": 9}, sid, CFG["zodiac"], choices, "zodiac",
          WANT) for sid in ("materials", "dna")))
# The shape is written once at import and cannot carry a month that moves.
# It names January exactly once, to say the map does not start there.
check("  nor the shape itself, which is written once at import",
      reports.ZODIAC_SPEC["shopping"].count("January") == 1
      and "not\nfrom January" in reports.ZODIAC_SPEC["shopping"]
      and "Nov 2026" not in reports.ZODIAC_SPEC["shopping"],
      reports.ZODIAC_SPEC["shopping"].count("January"))

# --- b) the check that holds it there ---------------------------------------

print("\n--- a map that opens in January is refused ---")
# A note long enough to clear the shape's own floor: the point of the pair
# below is that both are shape-valid and only one is this reader's year.
good = {"items": [{"name": label,
                   "priority_note": "Good for the work already in front of "
                                    "you rather than for opening anything."}
                  for label in WANT],
        "skip": []}
check("the right twelve pass", reports._verify_months(good, WANT) is None)
wrong = json.loads(json.dumps(good))
wrong["items"][2]["name"] = "January"
detail = reports._verify_months(wrong, WANT)
check("a wrong month is refused", bool(detail))
check("  named by its position, with what it should have been",
      detail and "month 3" in detail and "'January'" in detail
      and "'Jan 2027'" in detail, detail)
check("  and the whole sequence repeated, so the retry can copy it",
      detail and all(label in detail for label in WANT))
short = {"items": good["items"][:10], "skip": []}
check("ten months are refused by count",
      "exactly 12 months and 10 arrived" in (
          reports._verify_months(short, WANT) or ""),
      reports._verify_months(short, WANT))
check("  and a section with no items at all is refused too",
      bool(reports._verify_months({"items": []}, WANT)))
check("no year means no opinion — which is every funnel but these two",
      reports._verify_months(wrong, None) is None
      and reports._verify_months(wrong, []) is None)
# Shape-valid either way: this is exactly the failure the shape validators
# cannot see, which is why it is a verify rule rather than one of them.
check("both maps are shape-valid, which is the point of checking separately",
      reports.VALIDATORS["shopping"](good) is not None
      and reports.VALIDATORS["shopping"](wrong) is not None)

hook = reports._verify_for(reports.ZODIAC_PROFILE, style, WANT)
check("the verify hook refuses it for the year section",
      bool(hook(("shopping",), {"shopping": wrong})))
check("  passes the right one", hook(("shopping",), {"shopping": good})
      is None)
check("  and says nothing about any other section",
      hook(("materials",), {"materials": wrong}) is None)
check("a hook built without a year is the hook it always was",
      reports._verify_for(reports.ZODIAC_PROFILE, style)(
          ("shopping",), {"shopping": wrong}) is None)
check("  and kitchen still has no hook at all",
      reports._verify_for(reports.KITCHEN_PROFILE, style) is None)

# --- c) end to end, with the clock held still -------------------------------

print("\n--- the whole thing, generated at a fixed date ---")
offline()
content = run_of("zodiac", "deep_water")
stored = (content.get("visuals") or {}).get("year")
check("the report stores the twelve it was written for", stored == WANT,
      str(stored))
by_section = {s["id"]: s["data"] for s in content["sections"]}
check("  and the year section carries exactly those names",
      [i["name"] for i in by_section["shopping"]["items"]] == WANT,
      str([i["name"] for i in by_section["shopping"]["items"]]))
notes = [i["priority_note"] for i in by_section["shopping"]["items"]]
check("  three strongest and one quiet, as the card promises",
      sum(n.startswith("Strongest month:") for n in notes) == 3
      and sum(n.startswith("Quiet month:") for n in notes) == 1,
      "%d strongest, %d quiet"
      % (sum(n.startswith("Strongest month:") for n in notes),
         sum(n.startswith("Quiet month:") for n in notes)))
check("  and none of its notes names a month, because the labels move",
      not [n for n in notes
           if re.search(r"\b(January|February|March|April|June|July|August|"
                        r"September|October|November|December)\b", n)],
      str([n for n in notes if re.search(r"\bJanuary\b", n)]))
check("the twin stores its own twelve the same way",
      run_of("zodiac30", "deep_water")["visuals"]["year"] == WANT)
kitchen_cfg = config.load_funnel("kitchen")
kitchen = reports.start_report(2, "kitchen", "modern_rustic", {"warm": 4},
                               choices=[s["pairs"][0]["images"][0]["id"]
                                        for s in kitchen_cfg["swipe"]["steps"]])
check("and kitchen stores no year and keeps its own list",
      "year" not in (kitchen.get("visuals") or {})
      and [i["name"] for i in
           {s["id"]: s["data"] for s in kitchen["sections"]}["shopping"]
           ["items"]][0] == "Lighting",
      str(sorted(kitchen.get("visuals") or {})))

print("\n--- and it costs no cache row ---")
check("the year section is written per purchase, not per archetype",
      "shopping" in reports.personal_sections("zodiac")
      and "shopping" not in reports.cached_sections("zodiac"),
      str(reports.cached_sections("zodiac")))
check("  on both funnels",
      "shopping" in reports.personal_sections("zodiac30")
      and "shopping" not in reports.cached_sections("zodiac30"))
check("  so the cache is still four rows a funnel, keyed on the style alone",
      reports.UPSERT_SECTION_SQL.count("%s") == 4
      and "month" not in reports.UPSERT_SECTION_SQL.lower()
      and "year" not in reports.UPSERT_SECTION_SQL.lower())
cached_prompt = reports._cached_prompt(style, name,
                                       reports.cached_sections("zodiac"),
                                       "zodiac")
check("  and no month reaches a cached prompt",
      not [label for label in WANT if label in cached_prompt]
      and "Nov" not in cached_prompt)

# --- d) the contact sheet, as boxes rather than as markup -------------------

print("\n--- the contact sheet is six equal squares to a row ---")


def sheet_boxes(report):
    """Every image box inside the printed contact sheet."""
    reports._pdf_visuals().clear()
    html = reports._pdf_html(report)
    doc = weasyprint.HTML(string=html,
                          base_url=config.STATIC_DIR).render()
    found = []

    def walk(box, inside=False):
        klass = (box.element.get("class")
                 if (box.element is not None
                     and hasattr(box.element, "get")) else None)
        here = inside or klass == "tapcell"
        if here and getattr(box.element, "tag", None) == "img":
            found.append((round(box.position_y, 1), round(box.width, 1),
                          round(box.height, 1)))
        for child in getattr(box, "children", []):
            walk(child, here)

    for page in doc.pages:
        walk(page._page_box)
    return html, found


for slug in FUNNELS:
    report = run_of(slug, "deep_water")
    taps = report["visuals"]["taps"]
    html, boxes = sheet_boxes(report)
    rows = {}
    for top, width, height in boxes:
        rows.setdefault(top, []).append((width, height))
    per_row = [len(v) for _, v in sorted(rows.items())]
    check("  %-9s draws one square per tap" % slug,
          len(boxes) == len(taps) == len(CFG[slug]["swipe"]["steps"]),
          "%d boxes, %d taps" % (len(boxes), len(taps)))
    check("    six to a row, and the last row is not ragged",
          per_row == [reports.TAP_COLUMNS] * (len(taps)
                                              // reports.TAP_COLUMNS),
          str(per_row))
    widths = {w for _, w, _ in boxes}
    heights = {h for _, _, h in boxes}
    check("    every cell the same width and the same height",
          len(widths) == 1 and len(heights) == 1,
          "widths %s heights %s" % (sorted(widths), sorted(heights)))
    check("    and square, whatever shape the source file was",
          abs(widths.pop() - heights.pop()) < 1.0)
    check("    the sheet stays on one page",
          len(rows) == -(-len(taps) // reports.TAP_COLUMNS)
          and html.count('<section class="taps">') == 1,
          str(len(rows)))

# A run whose count is not a multiple of six. Neither funnel is one today,
# and the padding is what stops the next one that is not coming out ragged.
padded = run_of("zodiac", "deep_water")
# Fourteen: two rows of six and a row of two, which is the shape neither
# funnel makes today and the one the padding exists for.
padded["visuals"] = dict(padded["visuals"],
                         taps=(padded["visuals"]["taps"]
                               + padded["visuals"]["taps"][:2]))
reports._pdf_visuals().clear()
markup = reports._pdf_html(padded)
sheet = markup.split('<section class="taps">')[1].split("</section>")[0]
check("a short last row is padded out to a full one",
      sheet.count("<tr>") == 3
      and all(row.count('class="tapcell"') == reports.TAP_COLUMNS
              for row in sheet.split("<tr>")[1:]),
      "%d rows, %s" % (sheet.count("<tr>"),
                       [row.count('class="tapcell"')
                        for row in sheet.split("<tr>")[1:]]))
check("  with the padding drawing nothing at all",
      sheet.count('<td class="tapcell"></td>')
      == 3 * reports.TAP_COLUMNS - sheet.count("<img"),
      "%d empty, %d images" % (sheet.count('<td class="tapcell"></td>'),
                               sheet.count("<img")))

# --- e) the half Love and Money grew ----------------------------------------

print("\n--- love and money answer their own question ---")
love = reports._stub_for("materials", "Deep Water", style,
                         reports.ZODIAC_STUBS)
money = reports._stub_for("splurge", "Deep Water", style,
                          reports.ZODIAC_STUBS)
check("every pairing says what it is like and then what to do",
      all("How to play it:" in pair["why"]
          or "How to protect your energy:" in pair["why"]
          for pair in love["pairs"]),
      str([pair["why"][-40:] for pair in love["pairs"]]))
check("  the magnetic ones get how to play it",
      [("How to play it:" in p["why"]) for p in love["pairs"]
       if p["verdict"] == "works"] == [True, True])
check("  and the draining ones how to protect their energy",
      [("How to protect your energy:" in p["why"]) for p in love["pairs"]
       if p["verdict"] == "avoid"] == [True, True])
check("the intro is their pattern rather than a preamble",
      len(love["intro"]) > 150 and "pattern" in love["intro"].lower(),
      len(love["intro"]))
check("money names three moves beside the work",
      "Three moves:" in money["splurge"]["why"]
      and money["splurge"]["why"].count(";") == 2,
      money["splurge"]["why"][-60:])
check("  every save says how to decline it",
      all(re.search(r"Decline it by|Put a deliverable", row["why"])
          for row in money["saves"]),
      str([row["why"][-40:] for row in money["saves"]]))
check("  and the closing note is the leak and the plug",
      money["split_note"].startswith("The leak")
      and "Plug it by" in money["split_note"], money["split_note"][:60])
check("both stubs still survive the validators that police the real thing",
      reports.VALIDATORS["materials"](love) is not None
      and reports.VALIDATORS["splurge"](money) is not None)
check("  and neither says a banned word",
      reports._banned_hit(love, reports.ZODIAC_BANNED) is None
      and reports._banned_hit(money, reports.ZODIAC_BANNED) is None,
      str(reports._banned_hit(money, reports.ZODIAC_BANNED)))
# Money is energy and behaviour. The line that keeps it there is the one a
# regulator would read first.
MONEY_ADVICE = re.compile(
    r"\b(invest|portfolio|returns on|stocks?|shares?|market|fund|"
    r"savings account|interest rate)\b", re.I)
check("  nor anything that reads as advice about money itself",
      not MONEY_ADVICE.search(json.dumps(money)),
      str(MONEY_ADVICE.findall(json.dumps(money))))
check("  which the prompt says outright",
      "never a thing to buy, hold or put" in reports.ZODIAC_SPEC["splurge"]
      and "no markets, no figures" in reports.ZODIAC_SPEC["splurge"])

print("\n--- and the budgets moved with the copy ---")
for section_id, fields in sorted(reports.PROMPT_LENGTH.items()):
    asked = reports._budgets(section_id)
    ceilings = {}
    for _, field, cap in reports._walk_caps(section_id):
        ceilings[field] = min(cap, ceilings.get(field, cap))
    for field, want in sorted(fields.items()):
        check("  %-9s %-11s asks %3d of %3d"
              % (section_id, field, asked[field], ceilings[field]),
              asked[field] == want <= ceilings[field],
              "%s vs %s" % (asked.get(field), want))
check("love and money ask for more than the default, mistakes for less",
      reports.PROMPT_LENGTH["materials"]["why"] > reports._budget(600)
      and reports.PROMPT_LENGTH["splurge"]["why"] > reports._budget(600)
      and reports.PROMPT_LENGTH["mistakes"]["body"] < reports._budget(600))
check("  and every stated number is inside the ceiling that polices it",
      reports._check_prompt_lengths() is None)
for section_id in ("materials", "splurge"):
    stated = [int(n) for n in re.findall(r"max (\d+) chars",
                                         reports.ZODIAC_SPEC[section_id])]
    check("  %-9s states every one of them in the shape itself" % section_id,
          set(reports.PROMPT_LENGTH[section_id].values()) <= set(stated),
          str(sorted(set(stated))))

print("\n%d checks, %d failed" % (checks[0], len(fails)))
for line in fails:
    print("  FAIL " + line)
sys.exit(1 if fails else 0)
