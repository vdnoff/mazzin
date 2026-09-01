#!/usr/bin/env python3
"""The power colours are the config's, and the PDF is the result page.

Two claims are checked here, both about the document somebody paid for.

The first is that the four colours in a zodiac palette section are this
reader's own — the four the free result drew as swatches and named — and not
four the model liked the sound of. That is enforced in three places and all
three are tested: the prompt states them, a validator rejects a section that
came back with any other, and the stub — what ships when there is no model at
all — is built from the same four rather than from a fifth set nobody chose.

The second is that the zodiac PDF is the delivered page on paper: a cover that
is the hero card, and sections that hang off numbered nodes. The check that
matters most in this file is the last one, which is that none of it reached
kitchen.

No database, no network, no model. WeasyPrint is used if it is installed and
the render check is skipped if it is not.

    python3 tests/test_zodiaccolors.py
"""
import copy
import json
import os
import re
import subprocess
import sys
import types

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, REPO)

import config                                              # noqa: E402
import reports                                             # noqa: E402

fails = []
checks = [0]


def check(label, ok, detail=""):
    checks[0] += 1
    if not ok:
        fails.append("%s %s" % (label, detail))
    print("  %-62s %s%s" % (label, "ok" if ok else "FAIL",
                            ("  " + str(detail)) if not ok else ""))


def offline(module):
    module.database.execute = lambda *a, **kw: None
    module.database.query_all = lambda *a, **kw: []
    module._api = lambda: None


def choices_for(slug, sign=None):
    """One tap on every step, which is what a finished run is."""
    cfg = config.load_funnel(slug)
    out = []
    for step in cfg["swipe"]["steps"]:
        if sign and step["id"] == "sign":
            out.append(sign)
        else:
            out.append(step["pairs"][0]["images"][0]["id"])
    return out


def stub_report(module, slug, style_id, sign=None):
    """A finished report row with every section stubbed, and no model.

    `sign` is the image id they tapped, not the label: the label is what the
    row stores and the run is what everything else is resolved from, so
    handing this the stored form would build a run nobody could have had.
    """
    cfg = config.load_funnel(slug)
    style = module._style(cfg, style_id)
    name = module._style_name(cfg, style_id)
    profile = module._profile(slug)
    built = {}
    for section in cfg["report"]["sections"]:
        if section.get("enabled") is False:
            continue
        built[section["id"]] = module._stub_for(section["id"], name, style,
                                                profile["stubs"])
    choices = choices_for(slug, sign)
    read = module._sign(cfg, choices)
    return module._assemble(cfg, slug, style_id, name, built,
                            {k: "stub" for k in built}, True,
                            None, module._visuals(cfg, style_id, choices),
                            read.get("label") if read else None)


def palette_of(style):
    """A section that would pass every shape check, with the real colours."""
    return {"palette": {
        "intro": "What the four are for, in a week rather than a room.",
        "colors": [
            {"name": name, "hex": code, "role": "for momentum",
             "finish": "Mondays", "where": "worn at the wrist"}
            for name, code in reports._style_colors(style)],
        "closing_rule": "One stone, one day of the week, and not three."}}


def main():
    offline(reports)
    cfg = config.load_funnel("zodiac")
    styles = cfg["styles"]

    print("\n--- every archetype has four colours to be held to ---")
    for style in styles:
        colours = reports._style_colors(style)
        check("%s carries four, with codes" % style["id"],
              len(colours) == 4 and all(
                  reports.HEX_RE.match(code) for _n, code in colours),
              str(colours))

    print("\n--- the prompt states them, and forbids the alternative ---")
    style = reports._style(cfg, "deep_water")
    required = reports._palette_required(style)
    check("the four are named in the prompt, with their codes",
          all(name in required and code in required
              for name, code in reports._style_colors(style)))
    # The palette is one of this funnel's cached sections — the colours belong
    # to the archetype, not to the reader — so the prompt that carries them is
    # the cached one, and it is the only prompt they appear in.
    prompt = reports._cached_prompt(style, "Deep Water", ("palette",), "zodiac")
    check("  and the block is in the palette prompt itself",
          required in prompt)
    check("  which tells the model to copy rather than choose",
          "NOT YOURS TO CHOOSE" in prompt and "Invent no colour" in prompt)
    check("  and bans the vocabulary of the other product",
          all(word in prompt for word in ('"matte"', '"satin"', '"gloss"')))
    other = reports._cached_prompt(style, "Deep Water", ("mistakes",), "zodiac")
    check("  no other section is handed a colour list",
          required not in other)
    personal = reports._section_prompt(style, "Deep Water", {"water": 9},
                                       "dna", cfg, [], "zodiac")
    check("  nor is the personal path", required not in personal)
    kcfg = config.load_funnel("kitchen")
    kstyle = reports._style(kcfg, "modern_rustic")
    kprompt = reports._section_prompt(kstyle, "Modern Rustic", {"warm": 4},
                                      "palette", kcfg, [], "kitchen")
    check("  and kitchen's palette prompt is not given one",
          "NOT YOURS TO CHOOSE" not in kprompt)

    print("\n--- the validator, on a section that came back wrong ---")
    verify = reports._verify_for(reports.ZODIAC_PROFILE, style)
    good = palette_of(style)
    check("the config's own four are accepted",
          verify(("palette",), good) is None,
          verify(("palette",), good))

    bad = copy.deepcopy(good)
    bad["palette"]["colors"][1]["hex"] = "#123456"
    check("a code that is not theirs is rejected",
          verify(("palette",), bad) is not None,
          "accepted #123456")

    bad = copy.deepcopy(good)
    bad["palette"]["colors"][0]["name"] = "Twilight Rose"
    check("  so is a colour renamed", verify(("palette",), bad) is not None)

    bad = copy.deepcopy(good)
    bad["palette"]["colors"].append(dict(good["palette"]["colors"][0]))
    check("  so is a fifth one", verify(("palette",), bad) is not None)

    bad = copy.deepcopy(good)
    bad["palette"]["colors"].pop()
    check("  so is three where there were four",
          verify(("palette",), bad) is not None)

    bad = copy.deepcopy(good)
    bad["palette"]["colors"][2]["finish"] = "matte, and only on a Tuesday"
    check("a paint word anywhere in the section is rejected",
          verify(("palette",), bad) is not None)

    bad = copy.deepcopy(good)
    bad["palette"]["intro"] = "A satin sheen suits this reader."
    check("  including in the copy around the swatches",
          verify(("palette",), bad) is not None)

    swapped = copy.deepcopy(good)
    swapped["palette"]["colors"][0], swapped["palette"]["colors"][3] = (
        swapped["palette"]["colors"][3], swapped["palette"]["colors"][0])
    check("  and the order the free page showed them in is held to",
          verify(("palette",), swapped) is not None)

    check("nothing but the palette is verified",
          verify(("mistakes",), {"mistakes": {"items": []}}) is None)
    check("and kitchen has no verifier at all",
          reports._verify_for(reports.KITCHEN_PROFILE, kstyle) is None)

    print("\n--- the stub, which is what ships when there is no model ---")
    for style in styles:
        stub = reports._stub_for("palette", style["name"], style,
                                 reports.ZODIAC_STUBS)
        want = reports._style_colors(style)
        got = [(c["name"], c["hex"]) for c in stub["colors"]]
        check("%s stubs its own four" % style["id"], got == want, str(got))
        bound = reports._verify_for(reports.ZODIAC_PROFILE, style)
        check("  and would pass the validator it is not run through",
              bound(("palette",), {"palette": stub}) is None,
              bound(("palette",), {"palette": stub}))
    check("a style with no palette in config still stubs four",
          len(reports._stub_colors({})) == 4)

    print("\n--- the cached rows that are now stale, and only those ---")
    tag = reports._cache_tag
    check("the zodiac palette cache is on a new revision",
          tag("zodiac", "palette") != reports.CACHE_SCHEMA,
          tag("zodiac", "palette"))
    check("  and the mistakes cache is on one of its own",
          tag("zodiac", "mistakes") != reports.CACHE_SCHEMA
          and tag("zodiac", "mistakes") != tag("zodiac", "palette"),
          tag("zodiac", "mistakes"))
    # All three cached sections have been rewritten now, each for its own
    # reason and each on its own revision — so a row warmed under any of the
    # old prompts is dropped rather than served as the old product.
    check("  and so is the money section, which grew a second half",
          tag("zodiac", "splurge") != reports.CACHE_SCHEMA,
          tag("zodiac", "splurge"))
    check("  three cached sections, three different revisions",
          len({tag("zodiac", sid)
               for sid in reports.cached_sections("zodiac")}) == 3,
          str({sid: tag("zodiac", sid)
               for sid in reports.cached_sections("zodiac")}))
    check("  and the twin's rows moved with the twin's",
          all(tag("zodiac30", sid) == tag("zodiac", sid)
              for sid in reports.cached_sections("zodiac")),
          str({sid: (tag("zodiac", sid), tag("zodiac30", sid))
               for sid in reports.cached_sections("zodiac")}))
    check("  and no kitchen row moved",
          all(tag("kitchen", sid) == reports.CACHE_SCHEMA
              for sid in ("palette", "mistakes", "shopping")))
    # One warmed row, exactly as _write_cache stamped it before this change,
    # read back by the path a purchase takes. The database is a lambda; what
    # is under test is which tag that row is compared against.
    def warmed(slug, style_id, section_id):
        stub = reports._stub_for(section_id, "X",
                                 reports._style(config.load_funnel(slug),
                                                style_id),
                                 reports._profile(slug)["stubs"])
        row = {"section_id": section_id,
               "content": json.dumps({"v": reports.CACHE_SCHEMA,
                                      "data": stub})}
        reports.database.query_all = lambda *a, **kw: [row]
        try:
            return reports._cache_state(slug, style_id)
        finally:
            reports.database.query_all = lambda *a, **kw: []

    have, dropped = warmed("zodiac", "deep_water", "palette")
    check("a zodiac palette row on the old revision is dropped",
          not have and dropped == 1, "%r, %d stale" % (have, dropped))
    # `mistakes` earned a revision of its own when the five strengths were
    # cut to two sentences and one: a row warmed under the old prompt is not
    # wrong, it is the old length, and the length is the product.
    have, dropped = warmed("zodiac", "deep_water", "mistakes")
    check("  and a mistakes row on the old revision is dropped with it",
          not have and dropped == 1, "%r, %d stale" % (have, dropped))
    have, dropped = warmed("zodiac", "deep_water", "splurge")
    check("  and a money row on the old revision goes with them",
          not have and dropped == 1, "%r, %d stale" % (have, dropped))
    check("  which is every cached section this funnel has",
          sorted(reports._profile("zodiac")["cache_rev"])
          == sorted(reports.cached_sections("zodiac")),
          str(sorted(reports._profile("zodiac")["cache_rev"])))
    have, dropped = warmed("kitchen", "modern_rustic", "palette")
    check("  and kitchen's palette row is kept",
          "palette" in (have or {}) and dropped == 0,
          "%r, %d stale" % (have, dropped))

    print("\n--- the PDF is the delivered page, on A4 ---")
    zodiac = stub_report(reports, "zodiac", "deep_water", "sign_pisces")
    html = reports._pdf_html(zodiac)
    cover = html.split('<section class="cover">')[1].split("</section>")[0]
    check("the cover leads with the page's own kicker",
          '<p class="cover-kicker">%s</p>'
          % cfg["result_copy"]["kicker"] in cover, cover[:160])
    check("  the sign is the headline",
          '<h1 class="cover-name">Pisces</h1>' in cover)
    check("  the archetype is under it, crossed",
          'class="cover-x">&#215; Deep Water<' in cover)
    check("  it is a card, not a title page",
          '<div class="cover-card">' in cover)
    check("  the style's own line is on it",
          reports._style(cfg, "deep_water")["blurb"][:40] in cover)
    check("the element bar draws all four",
          all(">%s</span>" % name in cover
              for _t, name, _h in reports.PDF_ELEMENTS),
          cover)
    check("  with this archetype's lit and no other",
          cover.count('class="cover-el own"') == 1)
    check("  and it is the element the archetype is scored on",
          cover.split('class="cover-el own"')[1].split("</span>")[0]
          .endswith("Water"))
    nodes = html.count('<span class="node">')
    check("every section hangs off a numbered node",
          nodes == len(zodiac["sections"]), "%d nodes" % nodes)
    check("  numbered in the order they read",
          all('<span class="node">%d</span>' % (i + 1) in html
              for i in range(len(zodiac["sections"]))))
    check("  on a rail down the margin",
          ".section {\n  padding-left: 11mm;\n  border-left:"
          in reports.ZODIAC_PDF_CSS)
    check("the palette printed is the palette they were shown",
          all(code in html for _n, code in
              reports._style_colors(reports._style(cfg, "deep_water"))))
    check("  and says nothing about a finish",
          not reports.PAINT_WORDS.search(
              "".join(s["data"].get("intro", "")
                      + json.dumps(s["data"].get("colors") or "")
                      for s in zodiac["sections"] if s["id"] == "palette")))

    print("\n--- and it is illustrated with their own frames ---")
    tapped = choices_for("zodiac", "sign_pisces")
    shots = zodiac.get("visuals") or {}
    check("the row carries one photograph per section",
          sorted(shots.get("sections") or {})
          == sorted(s["id"] for s in zodiac["sections"]),
          str(sorted(shots.get("sections") or {})))
    check("  and two for the cover", sorted(shots.get("hero") or {})
          == ["band", "glyph"], str(shots.get("hero")))
    every = list((shots.get("sections") or {}).values()) \
        + list((shots.get("hero") or {}).values())
    check("  every one of them tapped in this run",
          all(image_id in tapped for image_id in every),
          str([i for i in every if i not in tapped]))
    check("each section prints the one it was given",
          all('src="img/print/%s.jpg"' % shots["sections"][s["id"]] in html
              for s in zodiac["sections"]),
          str([s["id"] for s in zodiac["sections"]
               if 'src="img/print/%s.jpg"' % shots["sections"][s["id"]]
               not in html]))
    check("  the cover prints its two",
          'class="cover-glyph"' in cover and 'class="cover-band"' in cover,
          cover[:200])
    check("  all of them as print copies, never the gallery original",
          "galleries/zodiac" not in html,
          str(re.findall(r'<img src="([^"]+)"', html)))
    check("nothing is drawn that they did not tap",
          all(found.split("/")[-1][:-4] in tapped
              for found in re.findall(r'src="img/print/([^"]+)"', html)),
          str(re.findall(r'src="img/print/([^"]+)"', html)))
    # A step nobody reached leaves its section without a picture rather than
    # borrowing one: the page above this claims these are their own choices.
    bare = reports._visuals(config.load_funnel("zodiac"), "deep_water", [])
    check("a run with no taps at all is illustrated with nothing", not bare,
          str(bare))

    print("\n--- the cover mirrors whichever layout the page draws ---")
    # The page renders the minimal template, and this cover did not: the
    # reader was shown four capsules and a rarity card and was sent a formula
    # line and a "1 in N readings" pill. Which layout the cover draws is
    # decided the way result_zodiac.js decides it — by what the funnel's own
    # `result_copy.profile` carries — so the funnel that has no minimal copy
    # keeps the cover it has always had, which is the block above.

    def rich(slug, style_id, sign_id):
        """A report carrying the hero card the reader was shown."""
        cfg2 = config.load_funnel(slug)
        style = reports._style(cfg2, style_id)
        choices = choices_for(slug, sign_id)
        scores = {}
        for step in cfg2["swipe"]["steps"]:
            for image in step["pairs"][0]["images"]:
                if image["id"] in choices:
                    for tag in image.get("tags") or []:
                        scores[tag] = scores.get(tag, 0) + 2
        row = stub_report(reports, slug, style_id, sign_id)
        card = reports._profile_for(cfg2, slug, style, scores, choices)
        row["visuals"]["profile"] = card
        return row, card, cfg2

    row, card, cfg30 = rich("zodiac30", "celestial_air", "sign_virgo")
    lux = (reports._pdf_html(row).split('<section class="cover">')[1]
           .split("</section>")[0])
    table = cfg30["result_copy"]["profile"]
    check("the minimal cover is the one drawn for a funnel that has the copy",
          '<div class="cover-card rich lux">' in lux, lux[:200])
    check("  the legacy rarity pill is gone from it",
          "cover-ribbon" not in lux
          and card["rarity_line"] not in lux, card["rarity_line"])
    check("  and so is the formula line the capsules replace",
          'class="cover-formula"' not in lux)
    check("the capsules are the funnel's own chips, filled from this run",
          all(('<li class="cover-chip">%s</li>'
               % reports._TOKEN_RE.sub("", reports._fill_tokens(
                   shape, card["words"])).strip()) in lux
              for shape in table["chips"]),
          lux.split('class="cover-chips"')[1][:180])
    check("the rarity is its own card, in this funnel's own words",
          all(t in lux for t in ('<div class="cover-rare">',
                                 table["rarity_card"]["lead"],
                                 table["rarity_card"]["tail"])),
          lux.split("cover-rare")[1][:160] if "cover-rare" in lux else lux[:160])
    check("  carrying the share the page computes, not the 1-in-N",
          '<p class="cover-rare-figure">%d%%</p>'
          % reports._different_pct(card["rarity"]) in lux,
          "1 in %s" % card["rarity"])
    check("  and the note broken at the em dash, as rarityNote breaks it",
          lux.count('class="cover-rare-noteline"') == 2,
          table["rarity_card"]["note"])
    check("the three scales are still drawn, with the leading pole lit",
          lux.count('class="cover-scale"') == len(card["scales"])
          and "cover-pole is-active" in lux,
          "%d scales" % lux.count('class="cover-scale"'))
    check("  and the split names the four elements under the bar",
          all('>%s</span>' % cell["name"] in lux for cell in card["split"])
          and 'class="cover-splitnames"' in lux)
    check("the reading leads with the mark and drops the rule above it",
          'class="cover-crossline is-bright"' in lux
          and "cover-hair" not in lux)
    # And the funnel with no minimal copy is untouched, which the whole block
    # above already read — restated here against the same builder.
    plain = (reports._pdf_html(rich("zodiac", "deep_water", "sign_pisces")[0])
             .split('<section class="cover">')[1].split("</section>")[0])
    check("a funnel without the minimal copy keeps the legacy card",
          "cover-card rich lux" not in plain and "cover-rare" not in plain
          and 'class="cover-ribbon"' in plain,
          plain[:200])

    print("\n--- a section picture never leaves its heading ---")
    # The heading ended a page and its picture opened the next one, alone.
    # `break-after: avoid-page` on the heading could not hold it: what follows
    # the heading is a table WeasyPrint may break between its own rows.
    shots = reports._pdf_html(row)
    check("heading, picture and opening text are one block",
          shots.count('<div class="section-open">')
          == shots.count('<table class="media">'),
          "%d boxes, %d media tables"
          % (shots.count('<div class="section-open">'),
             shots.count('<table class="media">')))
    check("  the heading is inside the box, not above it",
          '<div class="section-open"><h2 class="section-title">' in shots)
    check("  and the box is what carries the picture",
          '</h2><table class="media">' in shots)
    check("the sheet forbids a break inside it",
          ".section-open { break-inside: avoid-page; }" in shots
          and ".media { break-inside: avoid-page; }" in shots)
    check("  and kitchen's sheet never grew the rule it cannot use",
          ".section-open" not in reports._pdf_html(
              stub_report(reports, "kitchen", "modern_rustic")))

    print("\n--- the whole document renders ---")
    try:
        import weasyprint                                  # noqa: F401
    except ImportError:
        print("  weasyprint absent — render check skipped")
    else:
        pdf = reports.build_pdf(zodiac)
        check("weasyprint builds it", pdf is not None and pdf[:4] == b"%PDF")
        # Page objects are inside compressed streams, so the document is
        # measured against the same document with its sections removed rather
        # than by counting a marker that is not in the bytes.
        bare = dict(zodiac, sections=[])
        thin = reports.build_pdf(bare)
        check("  and it is more than the cover",
              pdf is not None and thin is not None and len(pdf) > len(thin),
              "%d vs %d bytes" % (len(pdf or b""), len(thin or b"")))
        # Eight photographs and six sections of prose, in something a mail
        # server will still deliver.
        check("  and still small enough to email",
              pdf is not None and len(pdf) < 300 * 1024,
              "%d KB" % (len(pdf or b"") // 1024))

    print("\n--- and kitchen's document is the one it always built ---")
    kitchen = stub_report(reports, "kitchen", "modern_rustic")
    khtml = reports._pdf_html(kitchen)
    check("no node markers reached it", '<span class="node">' not in khtml)
    check("  it still leads with the plain cover line",
          '<p class="cover-lead">' in khtml and "cover-kicker" not in khtml)
    check("  and no element bar", "cover-el" not in khtml)

    old_src = ""
    for ref in ("origin/main:reports.py", "main:reports.py"):
        old_src = subprocess.run(["git", "show", ref], capture_output=True,
                                 text=True, cwd=REPO).stdout
        if old_src:
            break
    if not old_src:
        check("the committed file could be read", False, "git show failed")
    else:
        old = types.ModuleType("reports_before")
        old.__dict__["__name__"] = "reports_before"
        exec(compile(old_src, "reports_before", "exec"), old.__dict__)
        offline(old)
        for slug, style_id in (("kitchen", "modern_rustic"),
                               ("kitchen-visualizer", "modern_rustic")):
            was = stub_report(old, slug, style_id)
            now = stub_report(reports, slug, style_id)
            check("%s stubs the same report" % slug, was == now)
            check("  and prints the same PDF, character for character",
                  old._pdf_html(was) == reports._pdf_html(now))

    print("\n%d checks, %d failed" % (checks[0], len(fails)))
    for line in fails:
        print("  FAIL " + line)
    return 1 if fails else 0


if __name__ == "__main__":
    sys.exit(main())
