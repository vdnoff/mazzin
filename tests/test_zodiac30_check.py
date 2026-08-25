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
        "pricing", "meta"]
for key in SAME:
    check("  %-14s is the twin's" % key, cfg[key] == twin[key],
          json.dumps(cfg[key])[:90])
# result_copy is the twin's line for line, plus one block the twin has no
# question to fill: what pulled the reader here.
#
# The one exception inside `profile` is the rarity, which is measured per
# funnel — an eighteen-step walk lands on a different distribution than a
# twelve-step one, and a shared number would be a lie printed in gold on
# whichever funnel it did not belong to. Everything else in that block, all
# twenty-four names and forty-eight lines and six cards of it, is pinned.
def _no_rarity(copy):
    out = {k: v for k, v in copy.items() if k != "profile"}
    if "profile" in copy:
        out["profile"] = {k: v for k, v in copy["profile"].items()
                          if k != "rarity"}
    return out


mine_copy = {k: v for k, v in cfg["result_copy"].items() if k != "purpose_map"}
check("  result_copy    is the twin's, but for the purpose block",
      _no_rarity(mine_copy) == _no_rarity(twin["result_copy"]),
      str(sorted(set(mine_copy) ^ set(twin["result_copy"]))))
check("    and the rarity is measured on this funnel's own walk",
      cfg["result_copy"]["profile"]["rarity"]
      != twin["result_copy"]["profile"]["rarity"])
check("  and the twin carries no purpose block at all",
      "purpose_map" not in twin["result_copy"],
      str(sorted(twin["result_copy"])))
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

print("\n--- the seeking step opens on Love ---")
# The order the cards are authored in was decorative until the step pinned
# its first slot: engine.js shuffled all four, so whichever id came first in
# the config reached the reader's top-left about one run in four. It is the
# product now, so it is pinned here in the order the reader sees.
SEEKING = [("sk3a", "Love"), ("sk3b", "Career & money"),
           ("sk3c", "Inner peace"), ("sk3d", "The road ahead")]
seeking = by_step["seeking"]["pairs"][0]["images"]
check("four cards, in the authored order",
      [(i["id"], i["label"]) for i in seeking] == SEEKING,
      str([(i["id"], i["label"]) for i in seeking]))
check("  Love is the first of them",
      seeking[0]["id"] == "sk3a" and seeking[0]["label"] == "Love",
      "%s / %s" % (seeking[0]["id"], seeking[0]["label"]))
check("the step asks for its first slot to be kept",
      by_step["seeking"].get("pin_first") is True,
      str(by_step["seeking"].get("pin_first")))
check("  and it is the only step on this funnel that does",
      [s["id"] for s in steps if s.get("pin_first")] == ["seeking"],
      str([s["id"] for s in steps if "pin_first" in s]))
check("  it does not also opt out of the shuffle, which would pin all four",
      "shuffle" not in by_step["seeking"],
      str(by_step["seeking"].get("shuffle")))
check("  so the other three still carry no order of their own",
      len(seeking) == 4)
# The tags did not move with the slot. A reorder that also retagged would be
# a scoring change wearing a layout change's clothes.
check("Love is still the water card it always was",
      seeking[0]["tags"] == ["water", "mystic", "purpose_love"],
      str(seeking[0]["tags"]))
check("  and every card keeps the tags it was authored with",
      [i["tags"] for i in seeking] == [
          ["water", "mystic", "purpose_love"],
          ["fire", "bold", "purpose_career"],
          ["earth", "calm", "purpose_peace"],
          ["air", "sun", "purpose_path"]],
      str([i["tags"] for i in seeking]))
for slug in ("zodiac", "kitchen", "kitchen-visualizer"):
    other = json.load(open(os.path.join(ROOT, "funnels/%s.json" % slug)))
    check("  %-18s pins nothing, so it deals as it always did" % slug,
          not [st["id"] for st in other["swipe"]["steps"]
               if "pin_first" in st],
          str([st["id"] for st in other["swipe"]["steps"]
               if "pin_first" in st]))

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

print("\n--- what pulled them here ---")
# The seeking step has recorded this since the funnel shipped. This is the
# block that finally reads it: a rule per service tag, naming the section to
# lead with and the line under the anchor.
PURPOSE = {
    "purpose_love": ("materials", "Your compatibility read is inside."),
    "purpose_career": ("splurge", "Your money months are inside."),
    "purpose_peace": ("mistakes", "Your calm has a pattern. It's inside."),
    "purpose_path": ("shopping",
                     "Your year, mapped window by window — inside."),
}
pmap = cfg["result_copy"].get("purpose_map") or {}
check("a rule for every purpose tag the quiz can produce",
      sorted(pmap) == sorted(PURPOSE), str(sorted(pmap)))
check("  which is exactly the set the seeking step carries",
      sorted(pmap) == sorted(PURPOSE_SET := {
          t for i in by_step["seeking"]["pairs"][0]["images"]
          for t in i["tags"] if t in SERVICE}),
      str(sorted(PURPOSE_SET)))
check("  and none of the bond tags, which steer nothing",
      not set(pmap) & BOND, str(sorted(set(pmap) & BOND)))
for tag, (section_id, sub) in sorted(PURPOSE.items()):
    rule = pmap.get(tag) or {}
    check("  %-16s leads with %-10s" % (tag, section_id),
          rule.get("emphasized_section") == section_id,
          str(rule.get("emphasized_section")))
    check("    and says %s" % ('"%s"' % sub),
          rule.get("offer_sub") == sub, repr(rule.get("offer_sub")))
sections_by_id = {s["id"]: s for s in cfg["report"]["sections"]}
for tag, rule in sorted(pmap.items()):
    want = rule.get("emphasized_section")
    check("  %-16s names a real section of this report" % tag,
          want in sections_by_id, str(want))
    # Only a locked one can be led with: the free section is already open
    # above the reorder, and leading with it would be promising them
    # something they have already been given.
    check("    and one that is still behind the paywall",
          (sections_by_id.get(want, {}).get("reveal") or {}).get("mode")
          != "visible", str(want))
check("no two purposes lead with the same section",
      len({r.get("emphasized_section") for r in pmap.values()}) == len(pmap),
      str(sorted(r.get("emphasized_section") for r in pmap.values())))
check("every rule carries both halves and nothing else",
      all(sorted(r) == ["emphasized_section", "offer_sub"]
          for r in pmap.values()),
      str([sorted(r) for r in pmap.values()]))
check("the subs are one short line each",
      all(len(r["offer_sub"]) <= 60 and "\n" not in r["offer_sub"]
          for r in pmap.values()),
      str([len(r["offer_sub"]) for r in pmap.values()]))
check("  and none of them states the price or leans on a token",
      not [r for r in pmap.values()
           if "$" in r["offer_sub"] or "{" in r["offer_sub"]],
      str([r["offer_sub"] for r in pmap.values()
           if "$" in r["offer_sub"] or "{" in r["offer_sub"]]))

print("\n--- interstitials ---")
mids = cfg["interstitials"]
anchors = [i["after_step"] for i in mids]
# Down from eight. A beat every two steps is a rhythm the reader stops
# reading; four of them close acts instead of punctuating pairs.
check("four of them, down from eight", len(mids) == 4, str(len(mids)))
check("anchors are 4/9/14/18", anchors == [4, 9, 14, 18], str(anchors))
check("  in order, and none repeated",
      anchors == sorted(set(anchors)), str(anchors))
check("  every one of them lands after a step that exists",
      all(1 <= a <= len(steps) for a in anchors), str(anchors))
names = [steps[a - 1]["id"] for a in anchors]
check("they land after bond/symbol/decision/seal",
      names == ["bond", "symbol", "decision", "seal"], str(names))
check("  the first after the two steps that ask about the reader",
      [s["id"] for s in steps][2:4] == ["seeking", "bond"])
check("the last one closes the run rather than sitting inside it",
      anchors[-1] == len(steps))
check("  so the walk hands off to the analysing screen",
      "All 18 signals in." == mids[-1]["line"], mids[-1]["line"])
for entry in mids:
    check("  after %-2d has a kicker, a line and a cta" % entry["after_step"],
          all(entry.get(k) for k in ("kicker", "line", "cta")),
          json.dumps(entry))
check("every cta is the one this funnel uses",
      {e["cta"] for e in mids} == {"Continue analysis"},
      str(sorted({e["cta"] for e in mids})))
check("kickers stay in the diagnostic voice",
      {e["kicker"] for e in mids}
      <= {"Pattern detected", "Signal recorded", "Calibrating", "Deep layer"},
      str(sorted({e["kicker"] for e in mids})))
check("  four beats, four different ones",
      len({e["kicker"] for e in mids}) == 4,
      str(sorted({e["kicker"] for e in mids})))
check("templates are ones the engine knows how to draw",
      {e["template"] for e in mids} <= {"pattern", "confirm", "almost"},
      str(sorted({e["template"] for e in mids})))
# `almost` is the only one that draws the accent as a progress bar, so it
# belongs on the two beats whose copy is about how far along the reader is.
check("  the two progress beats are the ones drawn as a bar",
      [e["after_step"] for e in mids if e["template"] == "almost"] == [9, 18],
      str([(e["after_step"], e["template"]) for e in mids]))
check("the opening beat counts the two personal steps behind it",
      mids[0]["line"] == "Two personal signals in."
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
def sentences(entry):
    """Every sentence this entry can put on screen — its own, and the ones a
    run can substitute for them. A count in a line nobody thought of as a
    count is exactly the one that goes stale, and a personalised line is a
    line that is only read on some runs."""
    out = [entry["line"], entry.get("sub") or ""]
    for row in ((entry.get("personal") or {}).get("lines") or {}).values():
        out += [row.get("line") or "", row.get("sub") or ""]
    return out


for entry in mids:
    for text in sentences(entry):
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
check("one of them is templated on progress", len(pct) == 1, str(len(pct)))
check("  and the percentage it will show is honest",
      [round(e["after_step"] / len(steps) * 100) for e in pct] == [50],
      str([round(e["after_step"] / len(steps) * 100) for e in pct]))
check("working copy is the twin's",
      cfg["interstitial_working"] == twin["interstitial_working"])

print("\n--- and every one of them advances itself ---")
# The phone verdict on eight of these with a button each was that they read
# as barriers: a static screen and a mandatory tap, eight times. The mode is
# per entry rather than per funnel because that is what engine.js reads, and
# the twin must keep its button.
AUTO = {4: 2000, 9: 2000, 14: 2000, 18: 2400}
check("all four carry auto_advance_ms",
      all(isinstance(e.get("auto_advance_ms"), int) for e in mids),
      str([e["after_step"] for e in mids
           if not isinstance(e.get("auto_advance_ms"), int)]))
check("  two seconds each, and a beat longer on the last",
      {e["after_step"]: e["auto_advance_ms"] for e in mids} == AUTO,
      str({e["after_step"]: e["auto_advance_ms"] for e in mids}))
check("  the closing one is the longest of them",
      mids[-1]["auto_advance_ms"] == max(e["auto_advance_ms"] for e in mids)
      and mids[-1]["auto_advance_ms"] > mids[0]["auto_advance_ms"])
# Both ends of what engine.js will accept. Under the floor is a flash the
# entrance cannot finish inside; over the ceiling is a screen with no way out
# that outstays one that has a button.
check("  every timing is inside the bounds the engine clamps to",
      all(600 <= e["auto_advance_ms"] <= 4000 for e in mids),
      str(sorted(e["auto_advance_ms"] for e in mids)))
check("  and none of them is long enough to read as a wait",
      max(e["auto_advance_ms"] for e in mids) <= 2400)
check("the twin sets no timing on any of its three",
      not [e for e in twin["interstitials"] if "auto_advance_ms" in e],
      str([e["after_step"] for e in twin["interstitials"]
           if "auto_advance_ms" in e]))
for slug in ("kitchen", "kitchen-visualizer"):
    other = json.load(open(os.path.join(ROOT, "funnels/%s.json" % slug)))
    check("  nor does %-18s" % slug,
          not [e for e in (other.get("interstitials") or [])
               if "auto_advance_ms" in e])
# Trimmed for the format. Two seconds is a kicker and a line; a third line
# under them is one nobody finishes before the screen goes.
WITH_SUB = [4, 14, 18]
check("three of them keep a sub",
      [e["after_step"] for e in mids if e.get("sub")] == WITH_SUB,
      str([e["after_step"] for e in mids if e.get("sub")]))
check("  and the fourth carries no sub key at all",
      not [e["after_step"] for e in mids
           if "sub" in e and e["after_step"] not in WITH_SUB],
      str([e["after_step"] for e in mids
           if "sub" in e and e["after_step"] not in WITH_SUB]))
check("  the subs are one short line each",
      all(len(e["sub"]) <= 45 and "\n" not in e["sub"]
          for e in mids if e.get("sub")),
      str([(e["after_step"], len(e["sub"])) for e in mids if e.get("sub")]))
check("the four base lines are the ones written for them",
      [e["line"] for e in mids] == [
          "Two personal signals in.", "Profile {pct}% calibrated.",
          "Deep layer mapped.", "All 18 signals in."],
      str([e["line"] for e in mids]))
check("  and the closing one sets up the rarity the result page prints",
      mids[-1]["sub"] == "Most blends are common — let's see yours.",
      mids[-1].get("sub"))

# And nothing on a beat is a figure nobody measured. {pct} is arithmetic off
# the walk and is checked above; anything else numeric would not be.
STAT = re.compile(r"\b\d+\s*%")
check("no beat prints a percentage that is not {pct}",
      not [t for e in mids for t in sentences(e)
           if STAT.search(t.replace("{pct}%", ""))],
      str([t for e in mids for t in sentences(e)
           if STAT.search(t.replace("{pct}%", ""))]))

print("\n--- the echo: which frames each beat hands back ---")
# Each interstitial shows the images the reader tapped on the steps it
# closes. The lists are checked against the walk rather than against
# themselves: a beat that echoed a step from the wrong act would be handing
# somebody a frame they had not reached yet.
seen_steps = 0
for entry in mids:
    after = entry["after_step"]
    want = [s["id"] for s in steps][seen_steps:after]
    check("  after %-2d echoes the steps it closes" % after,
          entry.get("echo_steps") == want,
          "%s vs %s" % (entry.get("echo_steps"), want))
    seen_steps = after
echoed = [t for e in mids for t in e["echo_steps"]]
check("every step is handed back exactly once",
      sorted(echoed) == sorted(s["id"] for s in steps),
      str(sorted(set(echoed) ^ {s["id"] for s in steps})))
check("  and in the order they were walked",
      echoed == [s["id"] for s in steps], str(echoed))
check("the four beats hand back 4/5/5/4, which is every step once",
      [len(e["echo_steps"]) for e in mids] == [4, 5, 5, 4]
      and sum(len(e["echo_steps"]) for e in mids) == len(steps),
      str([len(e["echo_steps"]) for e in mids]))
check("the funnel asks for the analysing grid too",
      cfg.get("analyzing_echo") is True, str(cfg.get("analyzing_echo")))
# The dismiss has to outlast the row. Recomputed here off the engine's own
# numbers rather than trusting the config's base to be enough.
STAGGER = int(re.search(r"var ECHO_STAGGER_MS = (\d+)", engine).group(1))
CEILING = int(re.search(r"var ECHO_HOLD_MS = (\d+)", engine).group(1))
for entry in mids:
    want = entry["auto_advance_ms"] + len(entry["echo_steps"]) * STAGGER
    check("  after %-2d holds %dms, and its last frame lands at %dms"
          % (entry["after_step"], min(want, CEILING),
             (len(entry["echo_steps"]) - 1) * STAGGER),
          want <= CEILING
          and want > (len(entry["echo_steps"]) - 1) * STAGGER,
          "%d vs ceiling %d" % (want, CEILING))
check("no beat is cut off mid-row",
      all(e["auto_advance_ms"] + len(e["echo_steps"]) * STAGGER <= CEILING
          for e in mids))
for slug in ("zodiac", "kitchen", "kitchen-visualizer"):
    other = json.load(open(os.path.join(ROOT, "funnels/%s.json" % slug)))
    check("  %-18s echoes nothing" % slug,
          not [e for e in (other.get("interstitials") or [])
               if "echo_steps" in e]
          and "analyzing_echo" not in other,
          str([e.get("after_step") for e in (other.get("interstitials") or [])
               if "echo_steps" in e]))

print("\n--- the lines that say what the run said ---")
# Keyed by `axis` for the two accumulated readings and by `step` for the one
# that answers a single question back. The full sentence is written out here
# as the reader hears it — line then sub — because that is the thing being
# reviewed, not the two halves it is stored in.
PERSONAL = {
    4: ("axis", "purpose", {
        "purpose_love": "A {sign} looking for love. That narrows it fast.",
        "purpose_career":
            "A {sign} chasing momentum. That narrows it fast.",
        "purpose_peace":
            "A {sign} guarding their peace. That narrows it fast.",
        "purpose_path":
            "A {sign} mapping the road ahead. That narrows it fast."}),
    9: ("axis", "element", {
        "fire": "Fire keeps winning. If it holds, your reading changes.",
        "earth": "Earth keeps winning. If it holds, your reading changes.",
        "air": "Air keeps winning. If it holds, your reading changes.",
        "water": "Water keeps winning. If it holds, your reading changes."}),
    14: ("step", "decision", {
        "dc14a": "You choose with your heart first. Few admit that.",
        "dc14b": "You choose with your head first. The heart still votes.",
        "dc14c": "Gut first. Your fastest signal is usually your truest.",
        "dc14d":
            "You let time decide. Patience is a strategy, not a delay."}),
}
by_after = {e["after_step"]: e for e in mids}
check("three of the four carry a personal block",
      sorted(e["after_step"] for e in mids if "personal" in e)
      == sorted(PERSONAL), str(sorted(e["after_step"] for e in mids
                                      if "personal" in e)))
check("  and the closing one is static, because there is nothing left to read",
      by_after[18]["line"] == "All 18 signals in."
      and "personal" not in by_after[18])
for after, (kind, key, rows) in sorted(PERSONAL.items()):
    rule = by_after[after]["personal"]
    check("  after %-2d turns on %s %s" % (after, kind, key),
          rule.get(kind) == key, str(rule))
    check("    and on nothing else",
          sorted(rule) == sorted([kind, "lines"]), str(sorted(rule)))
    check("    with a line for every %s it can resolve to" % kind,
          sorted(rule.get("lines") or {}) == sorted(rows),
          str(sorted(rule.get("lines") or {})))
    for tag, said in sorted(rows.items()):
        got = (rule.get("lines") or {}).get(tag) or {}
        whole = " ".join(x for x in (got.get("line"), got.get("sub")) if x)
        check("    %-14s says %s" % (tag, '"%s"' % said[:40]),
              whole == said, repr(whole))
        check("      in two halves, so the block keeps its shape",
              bool(got.get("line")) and bool(got.get("sub")), repr(got))
# The step-keyed block names cards rather than tags, so every key has to be
# an image on that step — a key that is not is a line nobody can ever reach.
step_rules = [(a, r["personal"]) for a, r in by_after.items()
              if "step" in (r.get("personal") or {})]
for after, rule in step_rules:
    on = [i["id"] for st in steps if st["id"] == rule["step"]
          for p in st["pairs"] for i in p["images"]]
    check("  after %-2d names every card on the %s step and no others"
          % (after, rule["step"]),
          sorted(rule["lines"]) == sorted(on), str(sorted(on)))
# {sign} is the other new one. It resolves off the slot the funnel already
# declares for the result page, so a line that writes it and a config that
# does not declare it is a screen that silently falls back forever.
signed = [t for a, (_k, _v, rows) in PERSONAL.items() for t in rows.values()
          if "{sign}" in t]
check("the opening beat is the one that names their sign",
      len(signed) == 4 and all("{sign}" in t
                               for t in PERSONAL[4][2].values()),
      str(len(signed)))
check("  and the funnel declares where {sign} comes from",
      (cfg["report"]["hook_slots"].get("sign") or {}).get("step") == "sign",
      str(cfg["report"]["hook_slots"].get("sign")))
check("  which is a step this walk actually has",
      "sign" in [s["id"] for s in steps])
# The two kinds of axis the engine knows, named against what it actually
# declares — a config naming an axis this file has never heard of would
# resolve to nothing, silently, on every run.
declared = set(re.findall(r"(\w+):\s*\w+_AXIS",
                          re.search(r"var AXES = \{([^}]*)\}",
                                    engine, re.S).group(1)))
for after, (kind, key, _rows) in sorted(PERSONAL.items()):
    if kind == "step":
        check("  %-8s is a step, resolved to the card they tapped" % key,
              key in [s["id"] for s in steps], key)
        continue
    scoring = key in declared
    check("  %-8s is %s" % (key, "a scoring axis" if scoring
                            else "a service prefix"),
          scoring or key in {"purpose", "bond"}, key)
check("engine.js declares the two this funnel scores on",
      {"element", "energy"} <= declared, str(sorted(declared)))
check("  and still declares the three it always did",
      {"tone", "material", "season"} <= declared, str(sorted(declared)))
check("  element is the element vocabulary, in order",
      re.search(r"var ELEMENT_AXIS = \[([^\]]*)\]", engine).group(1)
      .replace('"', "").replace(" ", "").split(",")
      == ["fire", "earth", "air", "water"])
check("  energy is sun and moon",
      re.search(r"var ENERGY_AXIS = \[([^\]]*)\]", engine).group(1)
      .replace('"', "").replace(" ", "").split(",") == ["sun", "moon"])
# Every service prefix an axis names has to be a tag the quiz can produce.
for after, (kind, key, rows) in sorted(PERSONAL.items()):
    if kind != "axis" or key in declared:
        continue
    check("  every %s tag is one a card carries" % key,
          set(rows) <= {t for i in images for t in i["tags"]},
          str(sorted(set(rows) - {t for i in images for t in i["tags"]})))

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
      and "Math.round(progressRatio() * 100)" in engine)

print("\n--- the auto-advance mode, read out of the engine ---")
# Everything about this mode is gated on the entry carrying a number, so the
# proof that the twin and kitchen are untouched is that the gate is the
# config key and nothing else.
auto = re.search(r"function autoAdvanceMs\([^)]*\)\s*\{(.*?)\n  \}",
                 engine, re.S).group(1)
check("the mode is read off the entry, not off the funnel",
      "entry.auto_advance_ms" in auto and "slug" not in auto, auto[:160])
check("  a missing or unusable value is no timing at all",
      'typeof ms !== "number"' in auto and "return 0;" in auto)
check("  and a usable one is clamped at both ends",
      "Math.max(AUTO_MIN_MS, Math.min(want, ceiling))" in auto)
check("  the base beat is pushed back once per thumbnail",
      "var want = ms + (echoes || 0) * ECHO_STAGGER_MS;" in auto)
check("  a screen with a row on it gets the higher ceiling",
      "var ceiling = echoes ? ECHO_HOLD_MS : INTERSTITIAL_MS;" in auto)
check("  the floor and both ceilings are the ones the config sits inside",
      "var AUTO_MIN_MS = 600;" in engine
      and "var INTERSTITIAL_MS = 4000;" in engine
      and "var ECHO_HOLD_MS = 4500;" in engine)
opened = re.search(r"function openInterstitial\([^)]*\)\s*\{(.*?)\n  \}",
                   engine, re.S).group(1)
check("the button is hidden only when the entry asked for timing",
      "el.midCta.hidden = midAuto;" in opened)
check("  and the dismiss is the entry's beat or the old four seconds",
      "setTimeout(closeInterstitial, auto || INTERSTITIAL_MS)" in opened,
      opened[-200:])
check("  an open clears any timer left running before it sets its own",
      opened.index("clearTimeout(midTimer)")
      < opened.index("setTimeout(closeInterstitial"))
closed = re.search(r"function closeInterstitial\([^)]*\)\s*\{(.*?)\n  \}",
                   engine, re.S).group(1)
check("closing is idempotent, so a tap and the timer cannot both advance",
      "if (!midOpen) return;" in closed and "clearTimeout(midTimer)" in closed
      and "midAuto = false;" in closed)
check("a tap skips only in the mode that has nothing to tap",
      "function tapInterstitial()" in engine
      and "if (midAuto) closeInterstitial();" in engine)
check("  bound to the whole screen, because there is no control on it",
      'el.interstitial.addEventListener("click", tapInterstitial)' in engine)
check("  and the button keeps its own listener for the funnels that draw one",
      'el.midCta.addEventListener("click", closeInterstitial)' in engine)
check("the accent draws to the same ratio the sentence prints",
      'fill.style.transform = "scaleX(" + progressRatio() + \")\";' in engine)
check("  by transform, never by width",
      "function setAccent(" in engine
      and re.search(r"function setAccent\(.*?\n  \}", engine, re.S)
      .group(0).count("style.width") == 0)
check("  a bar on the almost beats, a spark on the rest",
      'var bar = entry.template === "almost";' in engine
      and 'classList.toggle("is-bar", bar)' in engine
      and 'classList.toggle("is-spark", !bar)' in engine)
check("the entrance is replayed rather than played once",
      "function playEntrance(" in engine
      and 'screen.classList.remove("is-enter")' in engine
      and "void screen.offsetWidth;" in engine
      and 'screen.classList.add("is-enter")' in engine)
check("  and the mode's class comes off for a funnel that does not ask",
      'screen.classList.toggle("is-auto", !!auto)' in engine)

print("\n--- the echo and the personal line, read out of the engine ---")
echo_fn = re.search(r"function setEcho\([^)]*\)\s*\{(.*?)\n  \}",
                    engine, re.S).group(1)
check("the row is drawn from the images this run actually tapped",
      "function echoPicks(" in engine
      and "imageById(chosenOnStep(want[i]))" in engine)
check("  a step with no answer is dropped, never drawn as a gap",
      "if (item && item.img) out.push(item);" in engine)
check("  and the row is only built for a screen that advances itself",
      "var picks = auto ? echoPicks(entry) : [];" in echo_fn)
check("the stagger is an animation delay, not eight live timers",
      "cell.style.animationDelay" in echo_fn
      and "setTimeout" not in echo_fn and "setInterval" not in echo_fn)
check("  and opting out of motion zeroes every one of them",
      "var slow = prefersReducedMotion();" in echo_fn
      and "(slow ? 0 : i * ECHO_STAGGER_MS)" in echo_fn)
accent_fn = re.search(r"function setAccent\([^)]*\)\s*\{(.*?)\n  \}",
                      engine, re.S).group(1)
check("the spark yields to the row, and the rule does not",
      "if (!auto || (echoes && !bar))" in accent_fn, accent_fn[:200])
grid_fn = re.search(r"function startGrid\([^)]*\)\s*\{(.*?)\n  \}",
                    engine, re.S).group(1)
check("the analysing grid is the whole run, in tap order",
      "function gridPicks(" in engine
      and "for (var i = 0; i < chosen.length; i++)" in engine)
check("  gated on the funnel asking for it",
      "if (!(cfg && cfg.analyzing_echo)) return [];" in engine)
check("  drawn above the copy, so the line has the signals over it",
      "el.analyzing.insertBefore(grid, el.analyzing.firstChild)" in grid_fn)
check("  and it starts once the ground behind it is dark",
      "* 0.45)" in grid_fn)
wait_fn = re.search(r"function analyzingMs\([^)]*\)\s*\{(.*?)\n  \}",
                    engine, re.S).group(1)
check("a funnel with no grid waits exactly what its config says",
      "if (!cells) return base;" in wait_fn)
check("  and one with a grid waits for the sequence plus a beat",
      "GRID_STAGGER_MS" in wait_fn and "GRID_HOLD_MS" in wait_fn
      and "Math.min(GRID_MAX_MS" in wait_fn)
check("  the message rotation spreads over the wait it was given",
      "(total || cfg.analyzing.duration_ms || 2500)" in engine)
check("  and the grid is cleared when the screen comes down",
      "el.analyzingGrid.innerHTML = \"\";" in re.search(
          r"function stopAnalyzing\([^)]*\)\s*\{(.*?)\n  \}",
          engine, re.S).group(1))
personal_fn = re.search(r"function personalised\([^)]*\)\s*\{(.*?)\n  \}",
                        engine, re.S).group(1)
check("a personalised entry replaces both halves or neither",
      "out.line = pick.line;" in personal_fn
      and 'out.sub = pick.sub || "";' in personal_fn)
check("  and a missing line leaves the entry exactly as written",
      "if (!pick || !pick.line) return entry;" in personal_fn)
check("  the kicker is never replaced",
      "out.kicker" not in personal_fn)
tag_fn = re.search(r"function personalTag\([^)]*\)\s*\{(.*?)\n  \}",
                   engine, re.S).group(1)
check("a scoring axis answers only when one tag leads outright",
      "soleLeaderOf(AXES[axis])" in tag_fn)
check("  and a service prefix is read off the run's own cards",
      'return prefixTag(axis + "_");' in tag_fn)
sole = re.search(r"function soleLeaderOf\([^)]*\)\s*\{(.*?)\n  \}",
                 engine, re.S).group(1)
check("a tie is not a leader",
      "level === 1" in sole and "bestScore > 0" in sole, sole[-120:])
check("  which is what separates it from the draw's own leaderOf",
      "function leaderOf(" in engine
      and "level" not in re.search(r"function leaderOf\([^)]*\)\s*\{"
                                   r"(.*?)\n  \}", engine, re.S).group(1))
check("the token check runs against the sentence that will be shown",
      "var shown = personalised(entry);" in engine
      and "return canFill(shown) ? shown : null;" in engine)
check("  which is the same check it always was",
      "function canFill(entry)" in engine)

print("\n--- and the stylesheet only paints it under that class ---")
css = open(os.path.join(ROOT, "static/css/mazzin.css"), encoding="utf-8").read()
check("the button is hidden by the mode's class",
      "#screen-interstitial.is-auto .mid-cta { display: none; }" in css)
check("every rule of the mode is scoped to it",
      all(rule.strip().startswith("#screen-interstitial.is-auto")
          or rule.strip().startswith(".mid-accent")
          or rule.strip().startswith("body.theme-zodiac .mid-accent")
          for rule in re.findall(r"^[^\s@}/][^{}]*(?=\{)", css, re.M)
          if "is-auto" in rule or "mid-accent" in rule),
      str([r.strip() for r in re.findall(r"^[^\s@}/][^{}]*(?=\{)", css, re.M)
           if ("is-auto" in r or "mid-accent" in r)
           and not r.strip().startswith(("#screen-interstitial.is-auto",
                                         ".mid-accent",
                                         "body.theme-zodiac .mid-accent"))]))
check("the three beats are staggered, kicker then line then sub",
      re.search(r"\.is-auto\.is-enter \.mid-line \{\s*animation:[^;]*?"
                r"(\d+)ms both", css).group(1) == "250")
FRAMES = r"@keyframes mid-(?:rise|spark|appear|breathe)\s*\{(.*?)\n\}"
check("only transform and opacity are animated",
      all(prop in ("opacity", "transform")
          for block in re.findall(FRAMES, css, re.S)
          for prop in re.findall(r"(\w[\w-]*)\s*:", block)),
      str(re.findall(FRAMES, css, re.S))[:200])
check("  and every keyframe block the mode uses is one of those four",
      sorted(re.findall(r"@keyframes (mid-[\w-]+)", css))
      == ["mid-appear", "mid-breathe", "mid-rise", "mid-spark", "mid-spin"],
      str(sorted(re.findall(r"@keyframes (mid-[\w-]+)", css))))
# The spark loops and the rule does not, declared in the sheet as well as
# asserted on the page: a progress line that breathed would be claiming to
# still be measuring something.
check("the spark breathes on a loop once its pulse has finished",
      "mid-breathe 1800ms ease-in-out 1240ms infinite alternate" in css)
check("  starting exactly where the pulse ends, so the seam does not jump",
      "mid-spark 820ms cubic-bezier(0.22, 0.61, 0.36, 1) 420ms both," in css
      and "100% { opacity: 1; transform: scale(1.08) rotate(0deg); }" in css
      and "from { opacity: 1; transform: scale(1.08); }" in css)
check("the rule holds instead, and glows rather than moving",
      "box-shadow: 0 0 7px 1px var(--mid-accent-glow);" in css
      and "mid-breathe" not in css.split(".mid-accent.is-bar")[1][:400])
check("  in this funnel's gold",
      "body.theme-zodiac .mid-accent { --mid-accent-glow: "
      "rgba(232, 200, 120, 0.38); }" in css)
check("the auto block is centred, and only the auto block",
      "#screen-interstitial.is-auto .mid-body { text-align: center; }" in css
      and "text-align: center" not in css.split(".mid-body {")[1][:200])
check("  the bar included — it scales, it does not resize",
      "transition: transform 740ms" in css
      and "transform-origin: left center;" in css)
check("reduced motion gets the same beats as fades",
      "@media (prefers-reduced-motion: reduce)" in css
      and "animation: mid-appear" in css
      and "#screen-interstitial.is-auto .mid-accent.is-bar .mid-accent-fill "
          "{\n    transition: none;\n  }" in css)
check("the accent is gold on this funnel's ground",
      "body.theme-zodiac .mid-accent .mid-accent-fill "
      "{ background: #E8C878; }" in css)
check("the echo row and the grid are painted, and only where they exist",
      ".mid-echo {" in css and ".mid-echo-cell {" in css
      and ".analyzing-grid {" in css and ".analyzing-cell {" in css)
check("  by transform and opacity, like everything else on this screen",
      all(prop in ("opacity", "transform")
          for block in re.findall(r"@keyframes echo-in\s*\{(.*?)\n\}",
                                  css, re.S)
          for prop in re.findall(r"(\w[\w-]*)\s*:", block)),
      str(re.findall(r"@keyframes echo-in\s*\{(.*?)\n\}", css, re.S)))
check("  and they fall back to a plain fade for anyone opted out",
      re.search(r"@media \(prefers-reduced-motion: reduce\) \{[^@]*?"
                r"\.mid-echo-cell,\s*\n\s*\.analyzing-cell \{\s*\n"
                r"\s*animation: mid-appear", css) is not None)
check("kitchen's interstitial styling is untouched",
      ".mid-cta {" in css and ".mid-cta:active { background: #f6f7f8; }" in css
      and ".mid-working {" in css and ".mid-next {" in css)

print("\n--- how engine.js deals a step it was told to pin ---")
deal = re.search(r"function pickPair\([^)]*\)\s*\{(.*?)\n  \}",
                 engine, re.S).group(1)
check("the flag is read off the step, not off the funnel",
      "st.pin_first" in deal and "slug" not in deal, deal[-400:])
check("  the first card keeps its slot and the rest are shuffled",
      "images: [images[0]].concat(shuffled(images.slice(1)))" in deal)
check("  a step that asks for neither still shuffles all of them",
      deal.rstrip().endswith("images: shuffled(images) };"), deal[-120:])
# `find` rather than `index`: a flag that is simply gone is a failing check
# here, not a traceback in place of the twenty that follow it.
check("  and shuffle:false still wins outright, because it pins every slot",
      -1 < deal.find("st.shuffle === false") < deal.find("st.pin_first"),
      "%d vs %d" % (deal.find("st.shuffle === false"),
                    deal.find("st.pin_first")))
check("the shuffle itself is untouched",
      "function shuffled(list)" in engine
      and "Math.floor(Math.random() * (i + 1))" in engine)
check("  and nothing else in the engine reads the flag",
      engine.count("pin_first") == 2, str(engine.count("pin_first")))

print("\n--- placeholders ---")
# `n` is the rarity; the four element names are the split caption's; the rest
# name the subtype and what it is made of. All of them are answered by
# result_zodiac.js's own `fill`, off the block it derives from the run's
# tallies, rather than by engine.js's hook machinery.
# `first` and `last` are the two ends of the reader's own twelve months, the
# same twelve reports.py builds server-side; the module fills them from the
# client date because nothing has been bought yet when the card is drawn.
PROFILE_TOKENS = {"element", "second", "energy", "subtype", "subtype_bare",
                  "subtype_article", "fire", "earth", "air", "water",
                  "first", "last"}
KNOWN = (set(cfg["report"]["hook_slots"])
         | {"style", "price", "n", "pct", "total"}
         | PROFILE_TOKENS)


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
            + [e["sub"] for e in mids if e.get("sub")]
            + [e["cta"] for e in mids]
            + [by_step[s]["question"] for s in NEW]
            + [by_step["essence"]["question"]]
            + [i["label"] for sid in NEW
               for i in by_step[sid]["pairs"][0]["images"]]
            + [c["name"] for sid in NEW
               for i in by_step[sid]["pairs"][0]["images"]
               for c in i["colors"]]
            + [t for _, t in COUNTED]
            + [r["offer_sub"] for r in pmap.values()]
            + [v for e in mids
               for r in (e.get("personal") or {}).get("lines", {}).values()
               for v in (r["line"], r.get("sub"))
               if v])
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


def dealt(step, rng=None):
    """The order engine.js would put a step's cards on screen in.

    Three cases, and pickPair reads them in this order: `shuffle: false`
    keeps every slot, `pin_first` keeps the first and shuffles the rest, and
    anything else shuffles all of them. With no rng the config order is
    returned as-is, which is what the persona walks want — they rank the
    cards rather than reading them off a screen.
    """
    images = [i for p in step["pairs"] for i in p["images"]]
    if rng is None or step.get("shuffle") is False:
        return images
    if step.get("pin_first"):
        rest = images[1:]
        rng.shuffle(rest)
        return images[:1] + rest
    order = list(images)
    rng.shuffle(order)
    return order


def play(pick, rng=None):
    """One run, as engine.js scores it: -0.5 a tag on the inverse step, 1 on
    every other. Nothing here is adaptive, so every step draws its one pair,
    dealt in the order the reader would have seen it."""
    scores = {}
    for step in steps:
        options = dealt(step, rng)
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
WALKS = 20000


def shares(excess):
    """What each archetype takes over WALKS runs, from a reader who over-taps
    the first slot by `excess` on top of the 1/n an indifferent one would.

    A shuffled step's first slot is a different card every run, so the excess
    lands nowhere in particular. On the two steps whose first slot is fixed it
    lands on the same card every time, which is the whole reason this is
    modelled rather than assumed: `sign` has always pinned Aries, and now
    `seeking` pins Love.
    """
    rng = random.Random(20260821)

    def reader(step, options):
        if excess and len(options) > 1 and rng.random() < excess:
            return options[0]
        return rng.choice(options)

    seen = collections.Counter(
        winner(play(reader, rng)) for _ in range(WALKS))
    return seen, {s["id"]: 100.0 * seen[s["id"]] / WALKS
                  for s in cfg["styles"]}


# Three readers: one indifferent to position, one who favours the first slot
# the way people do, and one who favours it harder than anybody plausibly
# does. Pinning Love moves deep_water and pinning Aries moves radiant_fire,
# in opposite directions, and the band has to hold under all three.
for excess, who in ((0.0, "an indifferent reader"),
                    (0.10, "a first-slot reader"),
                    (0.20, "a hard first-slot reader")):
    seen, got = shares(excess)
    for style in cfg["styles"]:
        share = got[style["id"]]
        check("  %-15s takes %4.1f%% from %-24s (%.0f-%.0f)"
              % (style["id"], share, who, FLOOR, CEILING),
              FLOOR <= share <= CEILING)
    check("  the four shares account for every walk",
          sum(seen.values()) == WALKS, str(sum(seen.values())))
# The claim the model rests on: pinning the seeking step is what puts the
# first-slot reader's thumb on a water card every run, so it has to be
# visible in the numbers rather than merely argued for.
pinned = shares(0.20)[1]
del by_step["seeking"]["pin_first"]
loose = shares(0.20)[1]
by_step["seeking"]["pin_first"] = True
check("pinning Love is what a first-slot reader feels, and it is deep water",
      pinned["deep_water"] > loose["deep_water"],
      "%.1f pinned vs %.1f loose" % (pinned["deep_water"],
                                     loose["deep_water"]))
check("  and it stays inside the band anyway, so nothing needed retagging",
      FLOOR <= pinned["deep_water"] <= CEILING,
      "%.1f%%" % pinned["deep_water"])
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
# Live. It was on the STRIPE_TEST_* key set while the rebuilt report was
# walked end to end with a 4242 card; it takes real money now, on the same key
# set kitchen-visualizer has always been on. The value is pinned rather than
# merely checked for presence because payments._stripe_mode reads exactly
# "test" and calls everything else live, so a typo in either direction is
# silent — one way the funnel charges a card nobody meant to charge, the other
# way it quietly stops charging anybody.
check("stripe_mode is the literal live", cfg.get("stripe_mode") == "live",
      repr(cfg.get("stripe_mode")))
check("payments reads it as a live-mode funnel",
      payments._stripe_mode(cfg) == payments.LIVE, payments._stripe_mode(cfg))
# Against stand-ins rather than against whatever this shell's .env holds, so
# the claim is about the wiring and not about one machine — and so it cannot
# pass vacuously with every key unset and equal to every other. No live key is
# read, printed or sent anywhere by any of it.
_env = (config.STRIPE_SECRET_KEY, config.STRIPE_PUBLISHABLE_KEY,
        config.STRIPE_TEST_SECRET_KEY, config.STRIPE_TEST_PUBLISHABLE_KEY)
try:
    config.STRIPE_SECRET_KEY = "sk_live_standin"
    config.STRIPE_PUBLISHABLE_KEY = "pk_live_standin"
    config.STRIPE_TEST_SECRET_KEY = "sk_test_standin"
    config.STRIPE_TEST_PUBLISHABLE_KEY = "pk_test_standin"
    _mode = payments._stripe_mode(cfg)
    check("  and resolves to STRIPE_SECRET_KEY / STRIPE_PUBLISHABLE_KEY",
          payments._stripe_secret(_mode) == "sk_live_standin"
          and payments._stripe_publishable(_mode) == "pk_live_standin",
          "%s / %s" % (payments._stripe_secret(_mode),
                       payments._stripe_publishable(_mode)))
    check("    which is the same pair the twin and kitchen resolve to",
          payments._stripe_secret(_mode)
          == payments._stripe_secret(payments._stripe_mode(twin))
          == payments._stripe_secret(
              payments._stripe_mode(config.load_funnel("kitchen"))))
finally:
    (config.STRIPE_SECRET_KEY, config.STRIPE_PUBLISHABLE_KEY,
     config.STRIPE_TEST_SECRET_KEY, config.STRIPE_TEST_PUBLISHABLE_KEY) = _env
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
# Why paywall_view does not carry the purpose. The payload is rebuilt from a
# closed key set rather than passed through, so an extra key is not ignored —
# it raises, /api/track answers a bare 400, and the event is lost entirely.
# Reading conversion per purpose would cost every paywall_view on the funnel,
# which is a worse trade than not having the breakdown. Asserted rather than
# argued, so the day the schema grows a slot this check is what says so.
check("paywall_view takes one key and rebuilds it",
      tracking._clean_paywall_view({"src": "scroll"}) == {"src": "scroll"})
try:
    tracking._clean_paywall_view({"src": "scroll", "purpose": "purpose_love"})
    check("  and refuses an extra one rather than dropping it", False)
except ValueError:
    check("  and refuses an extra one rather than dropping it", True)
# The prefix rather than the word: "purpose" appears twice in that file's
# prose, describing what `src` is for, and has since before any of this.
check("  so no purpose tag reaches tracking.py at all",
      "purpose_" not in open(os.path.join(ROOT, "tracking.py"),
                             encoding="utf-8").read())
check("  the key set it is checked against is the one key",
      sorted(tracking.PAYWALL_VIEW_KEYS) == ["src"],
      str(sorted(tracking.PAYWALL_VIEW_KEYS)))
check("  and pay_tap is unchanged in name and shape as well",
      tracking._clean_pay_tap({"method": "wallet"}) == {"method": "wallet"}
      and sorted(tracking.PAY_TAP_METHOD) == ["redirect", "wallet"],
      str(sorted(tracking.PAY_TAP_METHOD)))
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

print("\n--- the module reads it, and only when a funnel offers one ---")
module = open(os.path.join(ROOT, cfg["result_module"].lstrip("/")),
              encoding="utf-8").read()
check("the map is the gate, not the slug",
      "result_copy) || {}).purpose_map" in module
      and "zodiac30" not in module, "")
check("  a funnel without one gets null and no personalisation",
      "function purposeRule(" in module
      and "if (!map) return null;" in module)
# Read off the code rather than the file: the step is named in a comment
# above the function, saying why it is not named in the code.
module_code = re.sub(r"//[^\n]*", "", re.sub(r"/\*.*?\*/", "", module,
                                             flags=re.S))
check("the tag is found by tag, not by naming the seeking step",
      "function purposeTag(" in module_code
      and "seeking" not in module_code
      and "Object.keys(picks)" in module_code,
      str([ln for ln in module_code.split("\n") if "seeking" in ln]))
check("only the first match moves, and a name matching nothing moves nothing",
      "function firstly(" in module
      and "return hit ? [hit].concat(rest) : sections;" in module)
check("  the reorder is inside what is still locked",
      "var shut = ctx.sections.filter(" in module
      and "firstly(shut, want)" in module)
check("  and the free nodes above it keep their places",
      module.index("list.appendChild(balance(") < module.index("firstly(shut"))
check("the led teaser steps one tier, from the tokens the page already has",
      'teaser.style.color = "var(--zr-muted)"' in module
      and "--zr-muted" in open(
          os.path.join(ROOT, cfg["result_css"].lstrip("/")),
          encoding="utf-8").read())
check("  and no new rule was added to the module's stylesheet for it",
      ".zr-teaser.is-lead" not in open(
          os.path.join(ROOT, cfg["result_css"].lstrip("/")),
          encoding="utf-8").read())
check("the offer's sub-line is the only copy the rule replaces",
      "(rule && rule.offer_sub) || copy.offer_sub" in module)
check("  the price, the button and the trust row are untouched by it",
      not re.search(r"rule && rule\.(price|cta|trust|anchor)", module))
check("the delivered page reorders too, off the stored tag",
      "firstly(ctx.sections, emphasised(purposeRule(ctx)))" in module
      and "ctx.purpose" in module)
check("engine.js hands that tag over, empty when a report has none",
      'purpose: content.purpose || ""' in engine)

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

print("\n--- and it hears why they came ---")
seek_ids = [i["id"] for i in by_step["seeking"]["pairs"][0]["images"]]


def with_purpose(image_id):
    """A full run that tapped one of the seeking cards."""
    return [image_id if s["id"] == "seeking"
            else ("sign_leo" if s["id"] == "sign"
                  else s["pairs"][0]["images"][0]["id"])
            for s in steps]


for image_id in seek_ids:
    want = [t for t in by_id[image_id]["tags"] if t in PURPOSE][0]
    check("  %-5s reads back as %s" % (image_id, want),
          reports._purpose(cfg, with_purpose(image_id)) == want,
          str(reports._purpose(cfg, with_purpose(image_id))))
check("a run that never reached the step reads back as no purpose",
      reports._purpose(cfg, [c for c in with_purpose("sk3a")
                             if c not in seek_ids]) is None)
check("and a funnel that declares no map never has one",
      reports._purpose(twin, [s["pairs"][0]["images"][0]["id"]
                              for s in twin["swipe"]["steps"]]) is None)
love = with_purpose("sk3a")
style = cfg["styles"][0]
SAID = "The reader said what pulled them here"
for section_id in reports.personal_sections("zodiac30"):
    prompt = reports._section_prompt(style, "Radiant Fire", {"fire": 8},
                                     section_id, cfg, love, "zodiac30")
    check("  %-9s is told, in the reader's own terms" % section_id,
          SAID in prompt and "love and relationships" in prompt, section_id)
    check("    with the clause that keeps it honest",
          "without pretending the quiz measured more than it did" in prompt
          and "They tapped a picture" in prompt)
# The cache key is (funnel, style) and does not need the purpose. The cached
# trio is one answer per archetype shared by everybody who lands on it, and a
# purpose in that prompt would quadruple the rows while making each one a
# reading written for whoever warmed it first.
for section_id in reports.cached_sections("zodiac30"):
    prompt = reports._section_prompt(style, "Radiant Fire", {"fire": 8},
                                     section_id, cfg, love, "zodiac30")
    check("  %-9s is a cached id and is told nothing" % section_id,
          SAID not in prompt, section_id)
cached_prompt = reports._cached_prompt(style, "Radiant Fire",
                                       reports.cached_sections("zodiac30"),
                                       "zodiac30")
check("the cached prompt carries no purpose",
      SAID not in cached_prompt and "love and relationships"
      not in cached_prompt)
check("  and the cache key is still the funnel and the style, nothing more",
      "%s" % reports.SELECT_SECTIONS_SQL.lower().count("purpose") == "0",
      reports.SELECT_SECTIONS_SQL)
check("  which is what makes the same row serve all four purposes",
      reports._cached_prompt(style, "Radiant Fire",
                             reports.cached_sections("zodiac30"), "zodiac30")
      == cached_prompt)
check("  and the cache revision is unmoved by any of this",
      reports._cache_tag("zodiac30", "palette")
      == reports._cache_tag("zodiac", "palette"),
      "%s vs %s" % (reports._cache_tag("zodiac30", "palette"),
                    reports._cache_tag("zodiac", "palette")))
twin_run = [s["pairs"][0]["images"][0]["id"] for s in twin["swipe"]["steps"]]
for section_id in reports.personal_sections("zodiac"):
    prompt = reports._section_prompt(twin["styles"][0], "Radiant Fire",
                                     {"fire": 8}, section_id, twin,
                                     twin_run, "zodiac")
    check("  zodiac v1 %-9s is told nothing about a purpose" % section_id,
          SAID not in prompt, section_id)
check("the line itself says nothing this vertical may not say",
      not [t for t in seek_ids
           if reports._banned_hit(
               reports._purpose_block(cfg, with_purpose(t), "materials"),
               reports.ZODIAC_BANNED)],
      str([t for t in seek_ids
           if reports._banned_hit(
               reports._purpose_block(cfg, with_purpose(t), "materials"),
               reports.ZODIAC_BANNED)]))

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
# The tag travels on the report, because the page that reads it is opened
# from a link in an email in a tab that never ran the quiz.
check("it carries the purpose this run tapped",
      content.get("purpose") == "purpose_love", str(content.get("purpose")))
_saved = (database.execute, database.query_all, reports._api)
database.execute = lambda *a, **k: None
database.query_all = lambda *a, **k: []
reports._api = lambda: None
try:
    other = reports.start_report(1, "zodiac30", "deep_water", {"water": 8},
                                 choices=with_purpose("sk3d"))
    twin_content = reports.start_report(
        2, "zodiac", "deep_water", {"water": 8},
        choices=[st["pairs"][0]["images"][0]["id"]
                 for st in twin["swipe"]["steps"]])
    kitchen_content = reports.start_report(3, "kitchen", "modern_rustic",
                                           {"warm": 4})
finally:
    database.execute, database.query_all, reports._api = _saved
check("  a different tap stores a different purpose",
      other.get("purpose") == "purpose_path", str(other.get("purpose")))
check("  the twin stores no purpose key at all",
      "purpose" not in twin_content, str(twin_content.get("purpose")))
check("  and neither does kitchen",
      "purpose" not in kitchen_content, str(kitchen_content.get("purpose")))
# The reorder is the screen's. Print is a linear archive: a document that
# reshuffled itself per reader would not be the same document twice, and the
# PDF is built from this list.
check("the stored section list stays in the report's own order",
      [s["id"] for s in other["sections"]] == [i for i, _ in SHAPE_OF],
      str([s["id"] for s in other["sections"]]))
titles = reports._pdf_html(other)
order = [t for _, t in SHAPE_OF
         if t.replace("&", "&amp;") in titles]
check("  so the PDF prints them in that order whichever way they came in",
      order == [t for _, t in SHAPE_OF], str(order))
check("every photograph on it is a frame this run tapped",
      all(i in leo for i in content["visuals"]["sections"].values())
      and all(i in leo for i in content["visuals"]["hero"].values()),
      str(content["visuals"]))
# The same rules over every sentence a beat can put on screen, personalised
# ones included — those are the lines only some runs ever read, which is
# exactly where a word slips through unnoticed.
mid_dirty = [(t[:48], reports._banned_hit(t, reports.ZODIAC_BANNED))
             for e in mids for t in sentences(e)
             if t and reports._banned_hit(t, reports.ZODIAC_BANNED)]
check("no interstitial says a banned word, on any run", not mid_dirty,
      str(mid_dirty))
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
