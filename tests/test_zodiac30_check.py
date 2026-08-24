#!/usr/bin/env python3
"""Integrity checks over funnels/zodiac30.json and the two galleries behind it.

test_zodiac_check.py, pointed at the A/B twin. The two funnels are the same
product down two different walks, so what is asserted here is the difference:
eighteen steps rather than twelve, eight interstitials rather than three, the
count claims that had to move with them, the service tags no style scores
against, and the split gallery — most of this funnel's frames are zodiac's,
referenced where they already live, and only the six steps it brought with it
have art of their own.

What the two share — the archetypes, the report shapes, the prompts, the PDF,
the mail — is asserted once, in test_zodiac_check.py, against the objects
both funnels reach through the same profile. Restating it here would be a
second copy to keep in step.

No database, no network, no key. Everything is read off disk.
"""
import collections
import json
import os
import random
import re
import sys

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

sys.path.insert(0, REPO)
ROOT = REPO
GALLERY = os.path.join(ROOT, "static/galleries/zodiac30")
BORROWED = os.path.join(ROOT, "static/galleries/zodiac")

fails = []
checks = [0]


def check(label, ok, detail=""):
    checks[0] += 1
    if not ok:
        fails.append("%s %s" % (label, detail))
    print("  %-58s %s%s" % (label, "ok" if ok else "FAIL",
                            ("  " + detail) if detail and not ok else ""))


cfg = json.load(open(os.path.join(ROOT, "funnels/zodiac30.json")))
static_cfg = json.load(
    open(os.path.join(ROOT, "static/funnels/zodiac30.json")))
twin = json.load(open(os.path.join(ROOT, "funnels/zodiac.json")))
steps = cfg["swipe"]["steps"]
by_step = {s["id"]: s for s in steps}
images = [i for s in steps for p in s["pairs"] for i in p["images"]]
by_id = {i["id"]: i for i in images}

# The scoring vocabulary, exactly as zodiac's. Everything outside it on an
# image is a service tag: carried so the run can be read back later, scored
# by nobody.
ELEMENTS = {"fire", "earth", "air", "water"}
ENERGY = {"sun", "moon"}
TONE = {"bold", "calm", "mystic"}
VOCAB = ELEMENTS | ENERGY | TONE
PURPOSE = {"purpose_love", "purpose_career", "purpose_peace", "purpose_path"}
BOND = {"bond_single", "bond_love", "bond_complicated", "bond_healing"}
SERVICE = PURPOSE | BOND

print("\n--- config shape ---")
check("static copy matches funnels/", cfg == static_cfg)
check("slug is zodiac30", cfg["slug"] == "zodiac30", cfg["slug"])
check("funnel_id is zodiac30_v1", cfg["funnel_id"] == "zodiac30_v1",
      cfg["funnel_id"])
check("locale is en", cfg["locale"] == "en", cfg["locale"])
check("pairs_count == number of steps",
      cfg["swipe"]["pairs_count"] == len(steps) == 18,
      "%s vs %s" % (cfg["swipe"]["pairs_count"], len(steps)))

print("\n--- it is the same funnel as zodiac, up to the walk ---")
# The point of the A/B: one product, two paths. Everything that is not the
# path is pinned against the twin, so a copy change on one funnel that was
# meant for both cannot land on only one of them unnoticed.
SAME = ["locale", "theme", "stripe_mode", "result_module", "result_css",
        "pricing", "result_copy", "meta"]
for key in SAME:
    check("  %-14s is the twin's" % key, cfg[key] == twin[key],
          json.dumps(cfg[key])[:90])
check("  the same four archetypes, byte for byte",
      cfg["styles"] == twin["styles"])
check("  the same report sections", cfg["report"]["sections"]
      == twin["report"]["sections"])
check("  the same illustrated steps and hook slots",
      cfg["report"]["visuals"] == twin["report"]["visuals"]
      and cfg["report"]["hook_slots"] == twin["report"]["hook_slots"])
check("  the same commerce block", cfg["checkout"]["commerce"]
      == twin["checkout"]["commerce"])
check("  the same style elements and preview gallery",
      cfg["style_elements"] == twin["style_elements"]
      and cfg["preview_gallery"] == twin["preview_gallery"])
check("  and the same badge labelling on the cards",
      cfg["swipe"].get("label_mode") == twin["swipe"].get("label_mode")
      == "badge")
# And the two things that must differ, or it is not an A/B at all.
check("the slug and the funnel_id are its own",
      cfg["slug"] != twin["slug"] and cfg["funnel_id"] != twin["funnel_id"])
check("  and it walks six steps further",
      len(steps) - len(twin["swipe"]["steps"]) == 6,
      "%d vs %d" % (len(steps), len(twin["swipe"]["steps"])))

print("\n--- every count claim says eighteen ---")
COUNTED = [("analyzing.messages[0]", cfg["analyzing"]["messages"][0]),
           ("analyzing.messages[1]", cfg["analyzing"]["messages"][1]),
           ("report.generating_messages[0]",
            cfg["report"]["generating_messages"][0]),
           ("checkout.proof_line", cfg["checkout"]["proof_line"]),
           ("result.value_banner", cfg["result"]["value_banner"])]
for label, text in COUNTED:
    check("  %-30s counts the steps" % label,
          str(len(steps)) in text and not re.search(r"\b12\b", text), text)
check("proof line is the eighteen-choice one",
      cfg["checkout"]["proof_line"] == "Built from your 18 choices",
      cfg["checkout"]["proof_line"])
check("the analysing screen names eighteen signals",
      "18 signals" in cfg["analyzing"]["messages"][0],
      cfg["analyzing"]["messages"][0])
# The one twelve that is not a tap count. The year map is months and was
# never the step count, so a blanket 12 -> 18 would have invented an
# eighteen-month year.


def strings(node):
    if isinstance(node, str):
        return [node]
    if isinstance(node, dict):
        return [s for v in node.values() for s in strings(v)]
    if isinstance(node, list):
        return [s for v in node for s in strings(v)]
    return []


TWELVES = [t for t in strings(cfg) if re.search(r"\b12\b", t)]
check("the only twelve left in the copy is the year map",
      all("12-month" in t.lower() for t in TWELVES), str(TWELVES))
check("  and the map itself still runs twelve months",
      cfg["report"]["sections"][5]["title"] == "Your 12-Month Energy Map",
      cfg["report"]["sections"][5]["title"])
check("nothing claims twelve choices or twelve signals",
      not re.search(r"12 (signals|choices|taps)",
                    json.dumps(cfg, ensure_ascii=False)))
check("and nothing anywhere still claims thirteen",
      not re.search(r"\b13\b", json.dumps(cfg, ensure_ascii=False)),
      str(re.findall(r'"[^"]*\b13\b[^"]*"',
                     json.dumps(cfg, ensure_ascii=False))[:3]))

print("\n--- steps ---")
WANT = [
    ("hook", "pair", "Which sky calls to you?"),
    ("sign", "grid12", "Tap your zodiac sign:"),
    ("seeking", "grid4", "What pulled you here tonight?"),
    ("bond", "grid4", "Your heart, right now:"),
    ("energy", "pair", "Choose your source of power"),
    ("landscape", "grid6", "Which world feels like home?"),
    ("palette", "grid6", "Which palette holds your energy?"),
    ("moment", "pair", "Your hour of power:"),
    ("symbol", "grid4", "Pick your talisman:"),
    ("moonphase", "grid4", "Which moon speaks to you?"),
    ("flow", "pair", "Your natural rhythm:"),
    ("drain", "grid4", "Which energy drains you most?"),
    ("sanctuary", "pair", "Where your soul recharges:"),
    ("decision", "grid4", "When life forks, you follow:"),
    ("tide", "pair", "Which truth feels more like you?"),
    ("door", "grid4", "Pick the door you'd walk through blind:"),
    ("essence", "grid4", "Your cosmic essence:"),
    ("seal", "pair", "Seal your reading:"),
]
check("step ids and order", [s["id"] for s in steps] == [w[0] for w in WANT],
      str([s["id"] for s in steps]))
for step, (sid, fmt, question) in zip(steps, WANT):
    check("  %-10s is %-6s and asks its question" % (sid, fmt),
          step["id"] == sid and step["format"] == fmt
          and step["question"] == question,
          "%s / %s / %r" % (step["id"], step["format"], step["question"]))
check("only the drain step scores inverse",
      [s["id"] for s in steps if s.get("scoring") == "inverse"] == ["drain"],
      str([s["id"] for s in steps if s.get("scoring")]))
check("the sign step is still second, right after the hook",
      [s["id"] for s in steps][:2] == ["hook", "sign"])
check("the two personal steps come straight after it",
      [s["id"] for s in steps][2:4] == ["seeking", "bond"])
check("the essence step is no longer billed as the final signal",
      "final signal" not in by_step["essence"]["question"],
      by_step["essence"]["question"])
check("  because the seal is",
      steps[-1]["id"] == "seal" and steps[-1]["format"] == "pair")
check("no step adapts on anything",
      not [s["id"] for s in steps if s.get("adaptive")],
      str([s["id"] for s in steps if s.get("adaptive")]))
check("only the sign step opts out of the shuffle",
      [s["id"] for s in steps if s.get("shuffle") is False] == ["sign"],
      str([s["id"] for s in steps if "shuffle" in s]))

print("\n--- the steps it shares with zodiac are that funnel's, unchanged ---")
REUSED = ["hook", "sign", "energy", "landscape", "palette", "moment",
          "symbol", "moonphase", "flow", "drain", "sanctuary", "essence"]
NEW = ["seeking", "bond", "decision", "tide", "door", "seal"]
check("twelve reused, six new",
      sorted(REUSED + NEW) == sorted(s["id"] for s in steps),
      str(sorted(set(s["id"] for s in steps) ^ set(REUSED + NEW))))
twin_steps = {s["id"]: s for s in twin["swipe"]["steps"]}
for sid in REUSED:
    mine = json.loads(json.dumps(by_step[sid]))
    theirs = json.loads(json.dumps(twin_steps[sid]))
    # The essence step's question moved, because it is no longer last. Its
    # cards did not.
    mine.pop("question"), theirs.pop("question")
    check("  %-10s is the twin's step" % sid, mine == theirs,
          json.dumps(mine)[:100])
check("  and the twin has no step this funnel invented",
      not [s for s in NEW if s in twin_steps], str([s for s in NEW
                                                    if s in twin_steps]))

print("\n--- the formats engine.js can actually draw ---")
engine = open(os.path.join(ROOT, "static/js/engine.js")).read()
sizes = dict((name, int(size)) for name, size in re.findall(
    r"(grid\d+):\s*(\d+)",
    re.search(r"var GRID_SIZE = \{([^}]*)\}", engine).group(1)))
check("engine.js declares its grids", bool(sizes), str(sizes))
check("every format this funnel asks for is one the engine has",
      all(s["format"] == "pair" or s["format"] in sizes for s in steps),
      str(sorted({s["format"] for s in steps})))
for step in steps:
    want = sizes.get(step["format"], 2)
    for pair in step["pairs"]:
        check("  %-10s %-4s holds the %d its format draws"
              % (step["id"], pair["id"], want),
              len(pair["images"]) == want, str(len(pair["images"])))
check("every step is one pair — nothing here is adaptive",
      all(len(s["pairs"]) == 1 for s in steps),
      str([s["id"] for s in steps if len(s["pairs"]) != 1]))

print("\n--- images, colours, tags ---")
HEX = set("0123456789ABCDEF")
for img in images:
    where = BORROWED if img["img"].startswith("/static/galleries/zodiac/") \
        else GALLERY
    name = img["img"].rsplit("/", 1)[-1]
    on_disk = os.path.exists(os.path.join(where, name))
    path_ok = img["img"].endswith("/%s.webp" % img["id"])
    tags = img["tags"]
    scoring = [t for t in tags if t not in SERVICE]
    # Two or three scoring tags, as on the twin, plus at most one service
    # tag. A card whose only tags were service tags would be a tap no
    # archetype could ever read.
    tags_ok = (set(scoring) <= VOCAB and len(set(tags)) == len(tags)
               and 2 <= len(scoring) <= 3
               and len(set(tags) & SERVICE) <= 1)
    colors_ok = (img.get("colors")
                 and len(img["colors"]) == 3
                 and all(c["hex"][0] == "#" and len(c["hex"]) == 7
                         and set(c["hex"][1:].upper()) <= HEX
                         and c.get("name") and c.get("element")
                         for c in img["colors"]))
    ok = on_disk and path_ok and img.get("label") and tags_ok and colors_ok
    if not ok:
        check("  image %s" % img["id"], False,
              "disk=%s path=%s tags=%s colors=%s"
              % (on_disk, path_ok, tags_ok, bool(colors_ok)))
check("every referenced frame is on disk and well formed",
      not [f for f in fails if f.startswith("  image")])
check("every image id is unique", len(by_id) == len(images),
      "%d ids, %d slots" % (len(by_id), len(images)))
check("no id appears in more than one pair",
      len({(i["id"]) for s in steps for p in s["pairs"]
           for i in p["images"]}) == len(images))
check("no season tag survives anywhere in the quiz",
      not {t for i in images for t in i["tags"]}
      & {"spring", "summer", "autumn", "winter"})
check("every card names itself", all(i.get("label") for i in images))
for step in steps:
    labels = [i["label"] for i in step["pairs"][0]["images"]]
    check("  %-10s labels are distinct" % step["id"],
          len(set(labels)) == len(labels), str(labels))

print("\n--- the gallery split ---")
# The twelve shared steps point into the zodiac gallery. Copying fifty
# frames to change nothing about them would be a second set to keep in step
# with the first, and the funnel already live is the one that would go stale.
mine = sorted(i["id"] for i in images
              if i["img"].startswith("/static/galleries/zodiac30/"))
borrowed = sorted(i["id"] for i in images
                  if i["img"].startswith("/static/galleries/zodiac/"))
check("every image resolves to one of the two galleries",
      len(mine) + len(borrowed) == len(images),
      str([i["img"] for i in images
           if i["id"] not in set(mine) | set(borrowed)]))
check("the reused steps' frames all point at zodiac's gallery",
      sorted(i["id"] for sid in REUSED
             for i in by_step[sid]["pairs"][0]["images"]) == borrowed,
      str(len(borrowed)))
check("  and the new steps' frames all point at this funnel's",
      sorted(i["id"] for sid in NEW
             for i in by_step[sid]["pairs"][0]["images"]) == mine,
      str(len(mine)))
NEW_IDS = ["sk3a", "sk3b", "sk3c", "sk3d",
           "bd4a", "bd4b", "bd4c", "bd4d",
           "dc14a", "dc14b", "dc14c", "dc14d",
           "td15a", "td15b",
           "dr16a", "dr16b", "dr16c", "dr16d",
           "sl18a", "sl18b"]
check("the new ids are the twenty this funnel brought",
      mine == sorted(NEW_IDS), str(sorted(set(mine) ^ set(NEW_IDS))))
on_disk = set(os.listdir(GALLERY))
wanted = {i + ".webp" for i in mine}
check("zodiac30's gallery has a frame for every one of them",
      wanted <= on_disk, str(sorted(wanted - on_disk)))
check("  and carries nothing else at all", on_disk == wanted,
      str(sorted(on_disk - wanted)))
check("  no share card of its own", "og.webp" not in on_disk)
check("og_image is the twin's card",
      cfg["meta"]["og_image"] == "/static/galleries/zodiac/og.webp"
      and os.path.isfile(os.path.join(BORROWED, "og.webp")),
      cfg["meta"]["og_image"])
check("every borrowed frame is on disk where it already lived",
      all(os.path.isfile(os.path.join(BORROWED, i + ".webp"))
          for i in borrowed),
      str([i for i in borrowed
           if not os.path.isfile(os.path.join(BORROWED, i + ".webp"))]))
check("  and none of them was copied into this gallery",
      not (on_disk & {i + ".webp" for i in borrowed}),
      str(sorted(on_disk & {i + ".webp" for i in borrowed})))
# The other direction, which is the one that would break the live funnel:
# test_zodiac_check pins zodiac's directory to an exact set, so a stray
# write into it fails there. This says the same thing from here, where the
# script that could do it lives.
check("nothing of this funnel's landed in zodiac's gallery",
      not (set(os.listdir(BORROWED)) & wanted),
      str(sorted(set(os.listdir(BORROWED)) & wanted)))

print("\n--- the placeholder script writes only what it owns ---")
gen = open(os.path.join(ROOT, "scripts/gen_zodiac30_placeholders.py"),
           encoding="utf-8").read()
check("it reads this funnel's config",
      'CONFIG = os.path.join(ROOT, "funnels", "zodiac30.json")' in gen)
check("  and writes into this funnel's gallery",
      '"static", "galleries", "zodiac30"' in gen)
check("  filtering on the path, so a borrowed frame is left alone",
      'OWNED = "/static/galleries/zodiac30/"' in gen
      and 'item["img"].startswith(OWNED)' in gen)
check("  and skipping any id already drawn",
      "if not os.path.exists(os.path.join(OUT, i" in gen)
check("it draws no share card, because it borrows one",
      'write("og"' not in gen)

print("\n--- service tags ---")
service_images = [i for i in images if set(i["tags"]) & SERVICE]
check("only the two personal steps carry them",
      sorted({sid for sid in by_step
              for i in by_step[sid]["pairs"][0]["images"]
              if set(i["tags"]) & SERVICE}) == ["bond", "seeking"],
      str(sorted({sid for sid in by_step
                  for i in by_step[sid]["pairs"][0]["images"]
                  if set(i["tags"]) & SERVICE})))
check("every card on them carries exactly one", len(service_images) == 8
      and all(len(set(i["tags"]) & SERVICE) == 1 for i in service_images),
      str(len(service_images)))
check("the purpose set is the seeking step's, whole",
      {t for i in by_step["seeking"]["pairs"][0]["images"]
       for t in i["tags"] if t in SERVICE} == PURPOSE)
check("the bond set is the bond step's, whole",
      {t for i in by_step["bond"]["pairs"][0]["images"]
       for t in i["tags"] if t in SERVICE} == BOND)
check("no service tag is shared by two cards",
      len([t for i in images for t in i["tags"] if t in SERVICE])
      == len(SERVICE))
# The whole contract: a service tag steers nothing. No style names one, so
# computeWinner never reads one, and a run that answered nothing but these
# two steps scores zero everywhere.
check("no archetype scores against one",
      not {t for s in cfg["styles"] for t in s["tags"]} & SERVICE,
      str({t for s in cfg["styles"] for t in s["tags"]} & SERVICE))
check("  and every card carrying one also carries tags that do score",
      all(set(i["tags"]) - SERVICE and set(i["tags"]) - SERVICE <= VOCAB
          for i in service_images),
      str([i["id"] for i in service_images
           if not set(i["tags"]) - SERVICE]))
check("the scoring vocabulary is exactly the twin's",
      {t for i in images for t in i["tags"]} - SERVICE
      == {t for s in twin["swipe"]["steps"]
          for p in s["pairs"] for i in p["images"] for t in i["tags"]},
      str(sorted({t for i in images for t in i["tags"]} - SERVICE)))

print("\n--- interstitials ---")
mids = cfg["interstitials"]
anchors = [i["after_step"] for i in mids]
check("eight of them, up from three", len(mids) == 8, str(len(mids)))
check("anchors are 2/4/6/8/10/12/15/18",
      anchors == [2, 4, 6, 8, 10, 12, 15, 18], str(anchors))
check("  in order, and none repeated",
      anchors == sorted(set(anchors)), str(anchors))
check("  every one of them lands after a step that exists",
      all(1 <= a <= len(steps) for a in anchors), str(anchors))
names = [steps[a - 1]["id"] for a in anchors]
check("they land after sign/bond/landscape/moment/moonphase/drain/tide/seal",
      names == ["sign", "bond", "landscape", "moment", "moonphase", "drain",
                "tide", "seal"], str(names))
check("  the first after the sign, the second after the personal pair",
      names[:2] == ["sign", "bond"])
check("the last one closes the run rather than sitting inside it",
      anchors[-1] == len(steps))
check("  so the walk hands off to the analysing screen",
      "All 18 signals in." == mids[-1]["line"], mids[-1]["line"])
for entry in mids:
    check("  after %-2d has a kicker, a line and a cta" % entry["after_step"],
          all(entry.get(k) for k in ("kicker", "line", "sub", "cta")),
          json.dumps(entry))
check("every cta is the one this funnel uses",
      {e["cta"] for e in mids} == {"Continue analysis"},
      str(sorted({e["cta"] for e in mids})))
check("kickers stay in the diagnostic voice",
      {e["kicker"] for e in mids}
      <= {"Pattern detected", "Signal recorded", "Calibrating"},
      str(sorted({e["kicker"] for e in mids})))
check("  and are the twin's own three words, not new ones",
      {e["kicker"] for e in mids}
      <= {e["kicker"] for e in twin["interstitials"]},
      str(sorted({e["kicker"] for e in mids}
                 - {e["kicker"] for e in twin["interstitials"]})))
check("templates are the three the twin ships",
      {e["template"] for e in mids} == {"pattern", "confirm", "almost"},
      str(sorted({e["template"] for e in mids})))
# The one line that counts what is left has to count what is actually left.
COUNTED_WORDS = {1: "One", 2: "Two", 3: "Three", 4: "Four", 5: "Five"}
left = len(steps) - 15
check("the deep-layer beat says how many signals are left",
      "Three signals left." == mids[6]["sub"], mids[6]["sub"])
check("  and three is what is actually left after fifteen",
      "%s signals left." % COUNTED_WORDS[left] == mids[6]["sub"],
      "%d left" % left)
check("the personal beat counts the two personal steps behind it",
      mids[1]["line"] == "Two personal signals in."
      and [s["id"] for s in steps][2:4] == ["seeking", "bond"])
check("the closing beat counts every step",
      str(len(steps)) in mids[-1]["line"], mids[-1]["line"])
# Every sentence that counts signals, wherever it is, against what the walk
# actually holds. A count in a line nobody thought of as a count is exactly
# the one that goes stale, so this scans all eight rather than the three
# above.
SAID = re.compile(r"\b(one|two|three|four|five|six|seven|eight|nine|ten|"
                  r"\d+)\s+(?:personal\s+)?signals?\b", re.I)
WORD = {"one": 1, "two": 2, "three": 3, "four": 4, "five": 5, "six": 6,
        "seven": 7, "eight": 8, "nine": 9, "ten": 10}
for entry in mids:
    for text in (entry["line"], entry["sub"]):
        hit = SAID.search(text)
        if not hit:
            continue
        said = WORD.get(hit.group(1).lower()) or int(hit.group(1))
        after = entry["after_step"]
        # "personal signals" counts the two steps that ask about the reader
        # rather than about pictures; everything else counts the walk. Either
        # way it is how many are behind them, how many are in front, or the
        # whole run. Anything else is a number nobody can check.
        personal = len([s for s in steps[:after]
                        if set(t for i in s["pairs"][0]["images"]
                               for t in i["tags"]) & SERVICE])
        want = ((personal,) if "personal" in hit.group(0).lower()
                else (after, len(steps) - after, len(steps)))
        check("  %-38s is true after %d" % ('"%s"' % text, after),
              said in want,
              "says %d, want one of %s" % (said, str(want)))
# {pct} is fillTokens' own, derived from step / pairs_count, so it is the
# one token here that always resolves. Every other one this vocabulary
# cannot fill, and canFill would drop the whole screen rather than show a
# hole.
DEAD = re.compile(r"\{leading_trait\}|\{opposite\}|\{leading_material\}"
                  r"|\{n\}|\{total\}")
check("no interstitial leans on a token this vocabulary cannot fill",
      not [e for e in mids
           if DEAD.search((e.get("line") or "") + (e.get("sub") or ""))],
      str([e["kicker"] for e in mids
           if DEAD.search((e.get("line") or "") + (e.get("sub") or ""))]))
pct = [e for e in mids if "{pct}" in e["line"]]
check("two of them are templated on progress", len(pct) == 2, str(len(pct)))
check("  and the percentages they will show are honest",
      [round(e["after_step"] / len(steps) * 100) for e in pct] == [44, 83],
      str([round(e["after_step"] / len(steps) * 100) for e in pct]))
check("working copy is the twin's",
      cfg["interstitial_working"] == twin["interstitial_working"])

print("\n--- engine.js walks the list rather than the first three ---")
# Eight is a config change and nothing else, but only because the lookup is
# a scan. A cap anywhere in here would make the last five screens dead copy.
lookup = re.search(r"function interstitialAfter\([^)]*\)\s*\{(.*?)\n  \}",
                   engine, re.S).group(1)
check("interstitialAfter scans the whole list",
      "for (var i = 0; i < list.length; i++)" in lookup, lookup[:120])
check("  matching on after_step rather than on position",
      "entry.after_step === completed" in lookup)
check("  with no ceiling on how many there may be",
      not re.search(r"i < (?!list\.length)\d+", lookup), lookup[:200])
check("engine.js counts steps completed, so after_step is one-based",
      "step += 1;" in engine and "interstitialAfter(step)" in engine)
check("  and an interstitial on the last step still reaches the result",
      "if (mid) { picking = false; openInterstitial(mid); return; }" in engine
      and "step >= cfg.swipe.pairs_count ? null" in engine)
check("{pct} is filled from the step count and pairs_count",
      "cfg.swipe.pairs_count || 1" in engine
      and "Math.round(step / total * 100)" in engine)

print("\n--- placeholders ---")
KNOWN = (set(cfg["report"]["hook_slots"])
         | {"style", "price", "n", "pct", "total"})


def tokens(node):
    if isinstance(node, str):
        return set(re.findall(r"\{(\w+)\}", node))
    if isinstance(node, dict):
        return set().union(set(), *(tokens(v) for v in node.values()))
    if isinstance(node, list):
        return set().union(set(), *(tokens(v) for v in node))
    return set()


used = tokens(cfg)
check("every placeholder in the copy is one something fills",
      used <= KNOWN, str(sorted(used - KNOWN)))
check("the hook slots are all actually used somewhere",
      set(cfg["report"]["hook_slots"]) <= used,
      str(sorted(set(cfg["report"]["hook_slots"]) - used)))
for key, rule in cfg["report"]["hook_slots"].items():
    check("hook slot %-10s names a step this funnel has" % key,
          rule["step"] in by_step and rule.get("fallback"), str(rule))
visuals = cfg["report"]["visuals"]
check("every illustrated section names a step this funnel has",
      all(s in by_step for s in visuals["section_steps"].values()),
      str([s for s in visuals["section_steps"].values() if s not in by_step]))
check("  and the header's two as well",
      all(s in by_step for s in visuals["hero"].values()),
      str(visuals["hero"]))
check("nothing the report draws comes off a step this funnel invented",
      not (set(visuals["section_steps"].values())
           | set(visuals["hero"].values())) & set(NEW),
      str(sorted((set(visuals["section_steps"].values())
                  | set(visuals["hero"].values())) & set(NEW))))
check("the preview gallery reuses quiz images",
      all(g["id"] in by_id for g in cfg["preview_gallery"]),
      str([g["id"] for g in cfg["preview_gallery"] if g["id"] not in by_id]))
check("  with their own tags and paths",
      all(g["tags"] == by_id[g["id"]]["tags"]
          and g["img"] == by_id[g["id"]]["img"]
          for g in cfg["preview_gallery"]))
check("every style element points at a live quiz image",
      all(e["image"] in by_id and e["img"] == by_id[e["image"]]["img"]
          and e["tags"] == by_id[e["image"]]["tags"]
          for e in cfg["style_elements"]["items"]),
      str([e["image"] for e in cfg["style_elements"]["items"]
           if e["image"] not in by_id]))

print("\n--- the words this vertical does not use ---")
# Over the whole config, which is where the new copy is: six steps of
# questions and labels, and eight interstitials.
BANNED = ["psychic", "prediction", "predictions", "fortune",
          "your future will"]
raw = open(os.path.join(ROOT, "funnels/zodiac30.json"),
           encoding="utf-8").read()
low = raw.lower()
for word in BANNED:
    check("  never says %r" % word, word not in low,
          low[max(0, low.find(word) - 40):low.find(word) + 40])
import reports  # noqa: E402
NEW_COPY = ([e["kicker"] for e in mids] + [e["line"] for e in mids]
            + [e["sub"] for e in mids] + [e["cta"] for e in mids]
            + [by_step[s]["question"] for s in NEW]
            + [by_step["essence"]["question"]]
            + [i["label"] for sid in NEW
               for i in by_step[sid]["pairs"][0]["images"]]
            + [c["name"] for sid in NEW
               for i in by_step[sid]["pairs"][0]["images"]
               for c in i["colors"]]
            + [t for _, t in COUNTED])
for text in NEW_COPY:
    hit = reports._banned_hit(text, reports.ZODIAC_BANNED)
    check("  %-44s passes the Terms check" % ('"%s"' % text[:42]),
          hit is None, hit)
# Not the whole config: `_banned_hit` reads the twin's own "returns on its
# own" as "returns on", and that string is zodiac's, unchanged, asserted
# identical to the twin's above. What is scanned here is what this funnel
# wrote, which is the list built above.
check("this funnel wrote none of them",
      not [t for t in NEW_COPY
           if reports._banned_hit(t, reports.ZODIAC_BANNED)],
      str([t for t in NEW_COPY
           if reports._banned_hit(t, reports.ZODIAC_BANNED)]))
check("  and what it did not write is the twin's, hit for hit",
      reports._banned_hit(cfg, reports.ZODIAC_BANNED)
      == reports._banned_hit(twin, reports.ZODIAC_BANNED) == "returns on",
      str(reports._banned_hit(cfg, reports.ZODIAC_BANNED)))

print("\n--- pricing ---")
check("price is the twin's 300 usd",
      cfg["pricing"] == twin["pricing"], str(cfg["pricing"]))
shown = "$%d" % (cfg["pricing"]["amount_cents"] // 100)
priced = [t for t in re.findall(r'"([^"]*\$[^"]*)"',
                                json.dumps(cfg, ensure_ascii=False))
          if shown in t]
check("  and no copy states it — every mention is the {price} token",
      not priced, str(priced))

print("\n--- scoring ---")


def winner(scores):
    best, best_score = None, float("-inf")
    for style in cfg["styles"]:
        total = sum(scores.get(t, 0) for t in style["tags"])
        if total > best_score:
            best, best_score = style["id"], total
    return best


def play(pick):
    """One run, as engine.js scores it: -0.5 a tag on the inverse step, 1 on
    every other. Nothing here is adaptive, so every step draws its one pair."""
    scores = {}
    for step in steps:
        options = [i for p in step["pairs"] for i in p["images"]]
        weight = -0.5 if step.get("scoring") == "inverse" else 1
        for tag in pick(step, options)["tags"]:
            scores[tag] = scores.get(tag, 0) + weight
    return scores


for style in cfg["styles"]:
    want = set(style["tags"])
    element = (want & ELEMENTS).pop()

    def persona(step, options, want=want, element=element):
        def rank(item):
            return (element in item["tags"],
                    len(set(item["tags"]) & want))

        if step.get("scoring") == "inverse":
            return min(options, key=rank)
        return max(options, key=rank)

    got = winner(play(persona))
    check("a %-15s run is given %s" % (style["id"], style["name"]),
          got == style["id"], got)

# A run that answers only the two service steps scores nothing any archetype
# reads. That is the whole claim about them, stated as a run rather than as
# a set operation.
service_only = {}
for sid in ("seeking", "bond"):
    for tag in by_step[sid]["pairs"][0]["images"][0]["tags"]:
        if tag in SERVICE:
            service_only[tag] = service_only.get(tag, 0) + 1
check("a score made only of service tags moves no archetype",
      all(sum(service_only.get(t, 0) for t in s["tags"]) == 0
          for s in cfg["styles"]), str(service_only))

FLOOR, CEILING = 15.0, 35.0
rng = random.Random(20260821)
seen = collections.Counter(
    winner(play(lambda s, o: rng.choice(o))) for _ in range(20000))
for style in cfg["styles"]:
    share = 100.0 * seen[style["id"]] / 20000
    check("  %-15s takes %4.1f%% of random walks (%.0f-%.0f)"
          % (style["id"], share, FLOOR, CEILING),
          FLOOR <= share <= CEILING)
check("the four shares account for every walk",
      sum(seen.values()) == 20000, str(sum(seen.values())))
check("the inverse step can push a total negative — the floor is -Infinity",
      any(s.get("scoring") == "inverse" for s in steps))

print("\n--- server side ---")
import config  # noqa: E402
import payments  # noqa: E402
import tracking  # noqa: E402

check("the slug is routable", config.funnel_exists("zodiac30"))
check("  and is a legal slug for the /<slug> route",
      config.valid_slug("zodiac30"))
check("load_funnel returns this config", config.load_funnel("zodiac30") == cfg)
check("payments reads it as a live-mode funnel",
      payments._stripe_mode(cfg) == payments.LIVE, payments._stripe_mode(cfg))
choices = [s["pairs"][0]["images"][0]["id"] for s in steps]
check("checkout accepts an 18-long choice list",
      payments._clean_choices(cfg, choices) == choices)
check("  and rejects a 19-long one",
      payments._clean_choices(cfg, choices + ["sy8a"]) is None)
check("  a short list is accepted, as it is on every funnel",
      payments._clean_choices(cfg, choices[:12]) == choices[:12])
check("  and a repeated tap is not",
      payments._clean_choices(cfg, choices[:-1] + [choices[0]]) is None)
check("tag scores validate against this vocabulary",
      payments._clean_tag_scores(cfg, {"fire": 6, "sun": 5, "bold": 4})
      == {"fire": 6, "sun": 5, "bold": 4})
check("  service tags among them too, since the engine sends every score",
      payments._clean_tag_scores(cfg, {"purpose_love": 1, "water": 3})
      == {"purpose_love": 1, "water": 3})
check("  and a tag this funnel does not carry is still refused",
      payments._clean_tag_scores(cfg, {"spring": 1}) is None)
for step in steps:
    shown = [i["id"] for i in step["pairs"][0]["images"]]
    got = tracking._clean_extra("zodiac30", "swipe",
                                {"pair": "%s:p1" % step["id"],
                                 "shown": shown, "chosen": shown[0]})
    check("tracking accepts the %-10s step" % step["id"],
          got["chosen"] == shown[0], str(got))
check("tracking allows step 18", tracking._clean_step(18) == 18)
try:
    tracking._clean_extra("zodiac30", "swipe",
                          {"pair": "seeking:p1",
                           "shown": ["sk3a", "sk3b", "sk3c", "hk1a"],
                           "chosen": "sk3a"})
    check("tracking rejects an image from another funnel", False)
except ValueError:
    check("tracking rejects an image from another funnel", True)
try:
    tracking._clean_extra("zodiac30", "swipe",
                          {"pair": "seeking:p1",
                           "shown": ["sk3a", "sk3b", "sk3c", "sk3d"],
                           "chosen": "zk1a"})
    check("  and a card the step does not offer", False)
except ValueError:
    check("  and a card the step does not offer", True)

print("\n--- the report this funnel is sold on ---")
check("zodiac30 resolves to the zodiac profile, by identity",
      reports._profile("zodiac30") is reports.ZODIAC_PROFILE)
check("  which is the object zodiac resolves to as well",
      reports._profile("zodiac30") is reports._profile("zodiac"))
check("so it caches the archetype trio",
      reports.cached_sections("zodiac30") == ("palette", "mistakes",
                                              "splurge"),
      str(reports.cached_sections("zodiac30")))
check("  and personalises the sign-driven one",
      reports.personal_sections("zodiac30") == ("dna", "materials",
                                                "shopping"),
      str(reports.personal_sections("zodiac30")))
check("  and bans what zodiac bans",
      reports._profile("zodiac30")["banned"] is reports.ZODIAC_BANNED)
check("  and prints on zodiac's dark sheet",
      bool(reports._profile("zodiac30").get("pdf_css")))
check("  and mails zodiac's mail",
      reports._email_copy({"funnel": "zodiac30"}) is reports.COPY_ZODIAC)
check("kitchen is still kitchen, and an unregistered funnel still is too",
      reports.cached_sections("kitchen") == ("shopping", "dna", "splurge")
      and reports.cached_sections("kitchen-visualizer") == reports.CACHED)
check("the two funnels are two rows in the section cache, not one",
      "%s" % reports.SELECT_SECTIONS_SQL.lower().count("funnel") >= "1"
      and "funnel" in reports.SELECT_SECTIONS_SQL.lower(),
      reports.SELECT_SECTIONS_SQL)
check("  which is why warm_cache.py takes a funnel name",
      "reports.cached_sections(" in open(
          os.path.join(ROOT, "scripts/warm_cache.py")).read())

print("\n--- the sign still reads back off an 18-choice run ---")
sign_images = by_step["sign"]["pairs"][0]["images"]
run = {s["id"]: s["pairs"][0]["images"][0]["id"] for s in steps}


def walk_with(sign_id):
    """A full 18-choice run that tapped one sign."""
    return [sign_id if s["id"] == "sign" else run[s["id"]] for s in steps]


for image in sign_images:
    got = reports._sign(cfg, walk_with(image["id"]))
    check("  %-18s reads back as %-12s"
          % (image["id"], got and got.get("label")),
          got is not None and got["cusp"] is False
          and got["label"] == image["label"]
          and set(got["tags"]) == set(image["tags"]), str(got))
check("all twelve signs resolve", len({i["id"] for i in sign_images}) == 12)
check("the prompt block says the sign",
      "this reader's sign is Leo"
      in reports._sign_block(cfg, walk_with("sign_leo")))
check("a run with no sign step answered reads back as no sign",
      reports._sign(cfg, [run[s["id"]] for s in steps
                          if s["id"] != "sign"]) is None)
check("no card can reach the cusp",
      "sign_cusp" not in {i["id"] for i in images}
      and reports._sign(cfg, walk_with("sign_cusp")) is None)

print("\n--- print copies for the PDF ---")
# Every frame the report can draw comes off a shared step, so the print
# copies zodiac already ships are the whole set. A new step appearing in
# visuals would need its own, and this is where that would surface.
need = set()
for step_id in (list(visuals["section_steps"].values())
                + list(visuals["hero"].values())):
    need.update(i["id"] for p in by_step[step_id]["pairs"]
                for i in p["images"])
missing = [i for i in sorted(need)
           if not os.path.isfile(os.path.join(ROOT, "static/img/print",
                                              i + ".jpg"))]
check("every image this report can draw has a print copy", not missing,
      str(missing))
check("  and every one of them is a frame zodiac already ships",
      all(by_id[i]["img"].startswith("/static/galleries/zodiac/")
          for i in need),
      str([i for i in sorted(need)
           if not by_id[i]["img"].startswith("/static/galleries/zodiac/")]))

print("\n--- a purchase, end to end, with nothing real behind it ---")
import database  # noqa: E402

leo = walk_with("sign_leo")
_saved = (database.execute, database.query_all, reports._api)
database.execute = lambda *a, **k: None
database.query_all = lambda *a, **k: []
reports._api = lambda: None
try:
    content = reports.start_report(1, "zodiac30", "deep_water",
                                   {"water": 8, "moon": 6, "mystic": 5},
                                   choices=leo)
finally:
    database.execute, database.query_all, reports._api = _saved

SHAPE_OF = [(s["id"], s["title"]) for s in cfg["report"]["sections"]]
check("the report is stored complete rather than partial",
      content["version"] == "stub-2", content["version"])
check("it carries all six sections, in the config's order",
      [s["id"] for s in content["sections"]] == [i for i, _ in SHAPE_OF],
      str([s["id"] for s in content["sections"]]))
check("with the zodiac titles rather than kitchen's",
      [s["title"] for s in content["sections"]] == [t for _, t in SHAPE_OF])
check("it names this funnel, not the twin", content["funnel"] == "zodiac30",
      content["funnel"])
check("every photograph on it is a frame this run tapped",
      all(i in leo for i in content["visuals"]["sections"].values())
      and all(i in leo for i in content["visuals"]["hero"].values()),
      str(content["visuals"]))
check("nothing delivered says a banned word",
      reports._banned_hit(content["sections"], reports.ZODIAC_BANNED) is None,
      str(reports._banned_hit(content["sections"], reports.ZODIAC_BANNED)))
html_out = reports._pdf_html(content)
check("the PDF draws print copies rather than gallery originals",
      'src="img/print/' in html_out and "galleries/zodiac" not in html_out)
pdf = reports.build_pdf(content)
check("weasyprint renders it", pdf is not None and pdf[:4] == b"%PDF")
check("  and it is small enough to email",
      pdf is not None and len(pdf) < 3 * 1024 * 1024,
      "%d KB" % (len(pdf) // 1024) if pdf else "none")
check("the mail is the zodiac mail",
      reports._email_copy(content) is reports.COPY_ZODIAC)

print("\n--- and the twin is untouched ---")
# The failure this funnel could cause and no zodiac30 assertion would see:
# a frame written into the other gallery, or a config edited on the way past.
check("funnels/zodiac.json is not this funnel",
      twin["slug"] == "zodiac" and twin["funnel_id"] == "zodiac_v1"
      and len(twin["swipe"]["steps"]) == twin["swipe"]["pairs_count"] == 12)
check("  still three interstitials, anchored 4/7/10",
      [i["after_step"] for i in twin["interstitials"]] == [4, 7, 10],
      str([i["after_step"] for i in twin["interstitials"]]))
check("  still counting twelve choices",
      twin["checkout"]["proof_line"] == "Built from your 12 choices",
      twin["checkout"]["proof_line"])
check("  and its static copy still matches it",
      twin == json.load(open(os.path.join(ROOT,
                                          "static/funnels/zodiac.json"))))

print("\n%d checks, %d failed" % (checks[0], len(fails)))
for f in fails:
    print("  FAIL " + f)
sys.exit(1 if fails else 0)
