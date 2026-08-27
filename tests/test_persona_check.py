#!/usr/bin/env python3
"""Integrity checks over funnels/persona.json and the gallery behind it.

test_zodiac30_check.py, pointed at the personality funnel rather than the
celestial one. The two are the same product down two different vocabularies,
so what is asserted here is what makes persona itself: an eighteen-step walk
on drive/anchor/wave/prism rather than on the four elements, a grid of twelve
animals where the twin has twelve signs, a gallery it owns outright rather
than shares, a head diagram no other funnel draws, and — the check this file
exists for — not one celestial word anywhere in it.

Phase 1 is config, the result module, placeholder art and this suite. persona
is not registered in reports.py yet and nothing here imports it: the banned
word list below is local, so the copy rules this vertical needs can be
asserted before the server-side profile that will eventually enforce them.

No database, no network, no key. Everything is read off disk.
"""
import collections
import importlib.util
import json
import os
import random
import re
import sys

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

sys.path.insert(0, REPO)
ROOT = REPO
GALLERY = os.path.join(ROOT, "static/galleries/persona")

# Every funnel on disk that is not this one. Discovered rather than listed:
# a hardcoded roster stops looking at the next funnel somebody adds, which is
# exactly what happened when zodiac-ro landed mid-branch.
NEIGHBOUR_SLUGS = sorted(
    f[:-len(".json")] for f in os.listdir(os.path.join(REPO, "funnels"))
    if f.endswith(".json") and f != "persona.json")

fails = []
checks = [0]


def check(label, ok, detail=""):
    checks[0] += 1
    if not ok:
        fails.append("%s %s" % (label, detail))
    print("  %-58s %s%s" % (label, "ok" if ok else "FAIL",
                            ("  " + detail) if detail and not ok else ""))


cfg = json.load(open(os.path.join(ROOT, "funnels/persona.json"),
                     encoding="utf-8"))
static_cfg = json.load(open(os.path.join(ROOT, "static/funnels/persona.json"),
                            encoding="utf-8"))
steps = cfg["swipe"]["steps"]
by_step = {s["id"]: s for s in steps}
images = [i for s in steps for p in s["pairs"] for i in p["images"]]
by_id = {i["id"]: i for i in images}

# The scoring vocabulary, whole. Everything outside it on an image is a
# service tag: carried so the run can be read back later, scored by nobody.
AXIS = {"drive", "anchor", "wave", "prism"}
ENERGY = {"outer", "inner"}
TONE = {"bold", "calm", "deep"}
VOCAB = AXIS | ENERGY | TONE
PURPOSE = {"purpose_love", "purpose_career", "purpose_peace", "purpose_path"}
BOND = {"bond_single", "bond_love", "bond_complicated", "bond_healing"}
SERVICE = PURPOSE | BOND

# The other funnels' vocabulary, which must not have followed the structure
# across. A copy of zodiac30 that was retagged by hand rather than rewritten
# is exactly the failure this catches.
CELESTIAL = {"fire", "earth", "air", "water", "sun", "moon", "mystic",
             "spring", "summer", "autumn", "winter",
             "wood", "stone", "metal", "warm", "cool", "dark", "bright"}


def strings(node):
    if isinstance(node, str):
        return [node]
    if isinstance(node, dict):
        return [s for v in node.values() for s in strings(v)]
    if isinstance(node, list):
        return [s for v in node for s in strings(v)]
    return []


print("\n--- config shape ---")
check("static copy matches funnels/", cfg == static_cfg)
check("slug is persona", cfg["slug"] == "persona", cfg["slug"])
check("funnel_id is persona_v1", cfg["funnel_id"] == "persona_v1",
      cfg["funnel_id"])
check("locale is en", cfg["locale"] == "en", cfg["locale"])
check("theme is its own", cfg["theme"] == "persona", cfg["theme"])
check("pairs_count == number of steps",
      cfg["swipe"]["pairs_count"] == len(steps) == 18,
      "%s vs %s" % (cfg["swipe"]["pairs_count"], len(steps)))
check("it names its own result module and stylesheet",
      cfg["result_module"] == "/static/js/result_persona.js"
      and cfg["result_css"] == "/static/css/result_persona.css",
      "%s / %s" % (cfg["result_module"], cfg["result_css"]))
check("  and both of them exist",
      all(os.path.isfile(os.path.join(ROOT, cfg[k].lstrip("/")))
          for k in ("result_module", "result_css")))
check("the product is named", cfg["meta"]["title"] == "Your Mind Profile",
      cfg["meta"]["title"])
check("  and shares its own card",
      cfg["meta"]["og_image"] == "/static/galleries/persona/og.webp",
      cfg["meta"]["og_image"])
check("cards are labelled in badge mode, like the twin's",
      cfg["swipe"].get("label_mode") == "badge",
      str(cfg["swipe"].get("label_mode")))
check("the arrival fades to this funnel's ink",
      cfg["swipe"]["analyzing_fade_to"] == "#0E1A1E",
      cfg["swipe"]["analyzing_fade_to"])
# A new funnel takes money on the test key set until somebody decides it does
# not. payments._stripe_mode reads exactly "test" and calls everything else
# live, so the value is pinned rather than merely checked for presence.
check("stripe_mode is the literal test", cfg.get("stripe_mode") == "test",
      repr(cfg.get("stripe_mode")))
check("every count claim says eighteen",
      all(str(len(steps)) in text and not re.search(r"\b12\b", text)
          for text in (cfg["analyzing"]["messages"][0],
                       cfg["analyzing"]["messages"][1],
                       cfg["report"]["generating_messages"][0],
                       cfg["checkout"]["proof_line"],
                       cfg["result"]["value_banner"])),
      cfg["checkout"]["proof_line"])
TWELVES = [t for t in strings(cfg) if re.search(r"\b12\b", t)]
check("  and the only twelve in the copy is the year map",
      all("12-month" in t.lower() for t in TWELVES), str(TWELVES))

print("\n--- steps ---")
WANT = [
    ("hook", "pair", "Which morning is yours?"),
    ("animal", "grid12", "Which one is you?"),
    ("seeking", "grid4", "What pulled you here today?"),
    ("bond", "grid4", "Your heart, right now:"),
    ("energy", "pair", "Where does your battery fill?"),
    ("environment", "grid6", "Where does your mind work best?"),
    ("palette", "grid6", "Which moodboard is yours?"),
    ("moment", "pair", "When do you lose track of time?"),
    ("talisman", "grid4", "Which one lives in your bag?"),
    ("weather", "grid4", "Your inner weather lately?"),
    ("rhythm", "pair", "Your sharpest hour?"),
    ("drain", "grid4", "Which of these drains you most?"),
    ("sanctuary", "pair", "After a hard day, you reset by\u2026"),
    ("decision", "grid4", "When life forks, you follow:"),
    ("tide", "pair", "Deadline pressure hits. You\u2026"),
    ("door", "grid4", "A free Saturday appears. First instinct?"),
    ("essence", "grid4", "People come to you for\u2026"),
    ("seal", "pair", "Ten years from now, the win is\u2026"),
]
check("step ids and order", [s["id"] for s in steps] == [w[0] for w in WANT],
      str([s["id"] for s in steps]))
for step, (sid, fmt, question) in zip(steps, WANT):
    check("  %-12s is %-6s and asks its question" % (sid, fmt),
          step["id"] == sid and step["format"] == fmt
          and step["question"] == question,
          "%s / %s / %r" % (step["id"], step["format"], step["question"]))
# The shape zodiac30 walks, kept: the identity grid second, the two personal
# steps behind it, the inverse step in the same place, the seal last.
check("the identity grid is second, right after the hook",
      [s["id"] for s in steps][:2] == ["hook", "animal"])
check("  the two personal steps come straight after it",
      [s["id"] for s in steps][2:4] == ["seeking", "bond"])
check("  and the seal closes the walk",
      steps[-1]["id"] == "seal" and steps[-1]["format"] == "pair")
check("only the drain step scores inverse",
      [s["id"] for s in steps if s.get("scoring") == "inverse"] == ["drain"],
      str([s["id"] for s in steps if s.get("scoring")]))
check("only the animal grid opts out of the shuffle",
      [s["id"] for s in steps if s.get("shuffle") is False] == ["animal"],
      str([s["id"] for s in steps if "shuffle" in s]))
check("only the seeking step pins its first slot",
      [s["id"] for s in steps if s.get("pin_first")] == ["seeking"],
      str([s["id"] for s in steps if "pin_first" in s]))
check("  and it does not also opt out of the shuffle, which would pin four",
      "shuffle" not in by_step["seeking"],
      str(by_step["seeking"].get("shuffle")))
check("no step adapts on anything",
      not [s["id"] for s in steps if s.get("adaptive")],
      str([s["id"] for s in steps if s.get("adaptive")]))
check("every step is one pair — nothing here is adaptive",
      all(len(s["pairs"]) == 1 for s in steps),
      str([s["id"] for s in steps if len(s["pairs"]) != 1]))
# The format counts are the engine's, read out of the engine: a grid6 with
# five cards in it is a hole on the screen and nothing in the config says so.
engine = open(os.path.join(ROOT, "static/js/engine.js"),
              encoding="utf-8").read()
sizes = dict((name, int(size)) for name, size in re.findall(
    r"(grid\d+):\s*(\d+)",
    re.search(r"var GRID_SIZE = \{([^}]*)\}", engine).group(1)))
check("every format this funnel asks for is one the engine has",
      all(s["format"] == "pair" or s["format"] in sizes for s in steps),
      str(sorted({s["format"] for s in steps})))
for step in steps:
    want = sizes.get(step["format"], 2)
    check("  %-12s holds the %d its format draws" % (step["id"], want),
          len(step["pairs"][0]["images"]) == want,
          str(len(step["pairs"][0]["images"])))

print("\n--- the nine behavioural steps ---")
# Phase 1.6 replaced the scenery with scenarios. Each of these asks what the
# reader does rather than which picture they like, and the cards are the
# answers to that question — so the labels are pinned, not just the count.
SCENARIOS = {
    "hook": ["Running shoes at dawn", "Slow coffee, notebook open"],
    "environment": ["A busy creative studio", "A minimal, tidy desk",
                    "A cosy reading nook", "A grand library hall",
                    "A park bench with a laptop", "A night desk under a lamp"],
    "moment": ["Deep in conversation", "Deep in a solo project"],
    "talisman": ["A notebook and pen", "Headphones", "Running shoes",
                 "A camera"],
    "rhythm": ["First light, at the desk", "Midnight, under the lamp"],
    "sanctuary": ["Outside, moving, with people", "Blanket, book, quiet"],
    "tide": ["Speed up, go all in", "Slow down, make a list"],
    "door": ["Road trip", "Build or fix something", "Gather your people",
             "Museum, bookshop, deep dive"],
    "essence": ["A push", "Steadiness", "Comfort", "Answers"],
    "seal": ["A life full of stories", "A life that feels like peace"],
}
for sid, labels in sorted(SCENARIOS.items()):
    got = [i["label"] for i in by_step[sid]["pairs"][0]["images"]]
    check("  %-12s offers the answers it was redesigned around" % sid,
          got == labels, str(got))
check("ten steps were replaced, and the rest kept their ids",
      len(SCENARIOS) == 10 and set(SCENARIOS) <= {s["id"] for s in steps})
# The frames were renamed with the content. The generator skips an id already
# on disk, so a replaced picture that kept its id would keep the old
# gradient — the rename is what forces the art to be redrawn.
for sid in SCENARIOS:
    old_ids = {"hook": "ph1", "environment": "ev6", "moment": "mo8",
               "talisman": "tl9", "rhythm": "rh11", "sanctuary": "sn13",
               "tide": "tr15", "door": "dw16", "essence": "es17",
               "seal": "sg18"}[sid]
    check("  %-12s frames were renamed with the content" % sid,
          not [i["id"] for i in by_step[sid]["pairs"][0]["images"]
               if i["id"].startswith(old_ids)],
          str([i["id"] for i in by_step[sid]["pairs"][0]["images"]]))
# And the questions ask about behaviour rather than about scenery. A question
# with no verb in it is the old kind.
for sid in sorted(SCENARIOS):
    q = by_step[sid]["question"].lower()
    check("  %-12s asks what they do" % sid,
          any(w in q for w in ("you", "your", "does", "do ", "lives",
                               "come", "hits", "appears", "work", "lose",
                               "win", "from now")),
          by_step[sid]["question"])

# The weather step kept its four pictures and changed what it asks: the sky
# was a picture to like, the mood is a thing the reader reports about
# themselves. Same frames, same ids, so no art was redrawn for it — which is
# why the ids are asserted to have *stayed* here, the opposite of the nine.
WEATHER = ["Clear sky", "Gathering storm", "Low fog", "Steady rain"]
weather_cards = by_step["weather"]["pairs"][0]["images"]
check("the weather step keeps its four states",
      [i["label"] for i in weather_cards] == WEATHER,
      str([i["label"] for i in weather_cards]))
check("  and its frames, because the pictures did not change",
      all(i["id"].startswith("wt10") for i in weather_cards),
      str([i["id"] for i in weather_cards]))
check("  but asks for a self-report rather than a preference",
      by_step["weather"]["question"] == "Your inner weather lately?",
      by_step["weather"]["question"])
# And the sentences that print the tapped label had to move with it. "your low
# fog put this one first" reads as a possession; a mood is a spell you have
# been under.
check("  and the copy that prints the label reads it as a mood",
      "the {weather} you've been under" in cfg["result_copy"]["strength_lead"]
      and "the {weather} you named" in cfg["result"]["mistakes_teaser"],
      cfg["result_copy"]["strength_lead"])
check("  with no sentence still calling it a thing they own",
      not [t for t in strings(cfg) if "your {weather}" in t],
      str([t for t in strings(cfg) if "your {weather}" in t]))

# Two cards on one step with the same tags are one card asked twice: whichever
# the reader taps, the run learns the same thing. The tuner reaches for this
# constantly — identical tags are often locally optimal — so it is pinned.
for step in steps:
    tagsets = [tuple(sorted(i["tags"]))
               for i in step["pairs"][0]["images"]]
    check("  %-12s asks something different on every card" % step["id"],
          len(set(tagsets)) == len(tagsets),
          str([t for t in tagsets if tagsets.count(t) > 1]))

print("\n--- the twelve animals ---")
ANIMALS = ["Owl", "Fox", "Wolf", "Bear", "Stag", "Raven",
           "Lynx", "Otter", "Hawk", "Tortoise", "Horse", "Cat"]
animals = by_step["animal"]["pairs"][0]["images"]
check("twelve of them, in the authored order",
      [i["label"] for i in animals] == ANIMALS,
      str([i["label"] for i in animals]))
check("  and the grid does not shuffle, because the reader is looking for "
      "their own",
      by_step["animal"].get("shuffle") is False)
check("every id is the animal it names",
      all(i["id"] == "animal_" + i["label"].lower() for i in animals),
      str([i["id"] for i in animals]))
check("each carries exactly one axis and one tone, and nothing else",
      all(len(i["tags"]) == 2 and len(set(i["tags"]) & AXIS) == 1
          and len(set(i["tags"]) & TONE) == 1 for i in animals),
      str([(i["id"], i["tags"]) for i in animals
           if not (len(i["tags"]) == 2 and len(set(i["tags"]) & AXIS) == 1
                   and len(set(i["tags"]) & TONE) == 1)]))
# The whole point of a twelve-card identity grid: every combination the
# vocabulary can make, once. A duplicate would be two animals the scoring
# cannot tell apart, and a gap would be a reader with no card to tap.
combos = collections.Counter(
    (tuple(sorted(set(i["tags"]) & AXIS))[0],
     tuple(sorted(set(i["tags"]) & TONE))[0])
    for i in animals)
WANTED = {(a, t) for a in sorted(AXIS) for t in sorted(TONE)}
check("the twelve cover every axis x tone exactly once",
      set(combos) == WANTED and set(combos.values()) == {1},
      str(sorted(set(combos) ^ WANTED) or combos.most_common(3)))
check("  which is four axes by three tones",
      len(WANTED) == 12 and len(animals) == 12)
# The named tags, pinned. A retag here moves the archetype distribution and
# the subtype a reader is given, so it is the config's most load-bearing
# twelve lines.
TAGGED = {
    "Fox": ["drive", "bold"], "Horse": ["drive", "calm"],
    "Hawk": ["drive", "deep"], "Bear": ["anchor", "bold"],
    "Tortoise": ["anchor", "calm"], "Stag": ["anchor", "deep"],
    "Otter": ["wave", "bold"], "Wolf": ["wave", "calm"],
    "Raven": ["wave", "deep"], "Lynx": ["prism", "bold"],
    "Owl": ["prism", "calm"], "Cat": ["prism", "deep"],
}
for one in animals:
    check("  %-9s is %s" % (one["label"], "/".join(TAGGED[one["label"]])),
          one["tags"] == TAGGED[one["label"]], str(one["tags"]))

print("\n--- the vocabulary, and nothing from another funnel ---")
tags_used = {t for i in images for t in i["tags"]}
check("every tag is scoring vocabulary or a service tag",
      tags_used <= VOCAB | SERVICE, str(sorted(tags_used - VOCAB - SERVICE)))
check("  and the whole scoring vocabulary is actually used",
      VOCAB <= tags_used, str(sorted(VOCAB - tags_used)))
check("no celestial tag survives anywhere in the quiz",
      not tags_used & CELESTIAL, str(sorted(tags_used & CELESTIAL)))
check("no archetype scores against a word from another funnel",
      not {t for s in cfg["styles"] for t in s["tags"]} - VOCAB,
      str(sorted({t for s in cfg["styles"] for t in s["tags"]} - VOCAB)))
# Not only the tags. A funnel forked from zodiac30 and retagged would keep
# the sentences, and the sentences are what the reader is sold.
#
# Whole words, over every string value in the config — the labels, the
# questions, the beats, the archetypes, the forty-eight cross lines and the
# ids and paths as well. Word-bounded because half of them live inside
# ordinary English this funnel does need: "signal" is not a sign, "library"
# is not a Libra, and a substring scan would fail on both.
CELESTIAL_WORDS = [
    "zodiac", "zodiacs", "cosmic", "celestial", "astrology", "astrological",
    "astrologer", "horoscope", "horoscopes", "sign", "signs", "star sign",
    "aries", "taurus", "gemini", "cancer", "leo", "virgo", "libra",
    "scorpio", "sagittarius", "capricorn", "aquarius", "pisces",
    "moonphase", "moon", "moons", "sun", "cusp", "mystic", "mystical",
]
copy_text = " \u241f ".join(strings(cfg)).lower()
for word in CELESTIAL_WORDS:
    found = re.search(r"\b%s\b" % re.escape(word), copy_text)
    check("  the copy never says %r" % word, found is None,
          copy_text[max(0, (found.start() if found else 0) - 45):
                    (found.end() if found else 0) + 45])
check("  the scan read every string in the config",
      copy_text.count("\u241f") == len(strings(cfg)) - 1,
      str(len(strings(cfg))))
check("  and it would catch one: the twin fails the same scan",
      any(re.search(r"\b%s\b" % w, " ".join(strings(json.load(open(
          os.path.join(ROOT, "funnels/zodiac30.json"), encoding="utf-8")
      ))).lower()) for w in CELESTIAL_WORDS))
check("every gallery path is this funnel's own",
      all(i["img"].startswith("/static/galleries/persona/") for i in images),
      str(sorted({i["img"].rsplit("/", 1)[0] for i in images})))

print("\n--- images, colours, tags ---")
HEX = set("0123456789ABCDEF")
for img in images:
    name = img["img"].rsplit("/", 1)[-1]
    on_disk = os.path.exists(os.path.join(GALLERY, name))
    path_ok = img["img"].endswith("/%s.webp" % img["id"])
    tags = img["tags"]
    scoring = [t for t in tags if t not in SERVICE]
    # Two or three scoring tags plus at most one service tag. A card whose
    # only tags were service tags would be a tap no archetype could read.
    tags_ok = (set(scoring) <= VOCAB and len(set(tags)) == len(tags)
               and 2 <= len(scoring) <= 3
               and len(set(tags) & SERVICE) <= 1)
    # Three named colours per frame, which is what the placeholder generator
    # paints a gradient through and what a palette check would read.
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
check("every card names itself", all(i.get("label") for i in images))
for step in steps:
    labels = [i["label"] for i in step["pairs"][0]["images"]]
    check("  %-12s labels are distinct" % step["id"],
          len(set(labels)) == len(labels), str(labels))

print("\n--- the gallery, which this funnel owns outright ---")
# zodiac30 borrows most of its art from zodiac, because it is that funnel's
# A/B twin and copying fifty frames would be a second set to keep in step.
# persona is nobody's twin: every frame it shows is its own, and the check
# runs in both directions because the failure that matters is a write into
# somebody else's directory.
mine = sorted(i["id"] for i in images)
on_disk = set(os.listdir(GALLERY))
wanted = {i + ".webp" for i in mine}
check("the gallery has a frame for every image in the config",
      wanted <= on_disk, str(sorted(wanted - on_disk)))
check("  its own share card as well", "og.webp" in on_disk)
check("  and nothing else at all", on_disk == wanted | {"og.webp"},
      str(sorted(on_disk - wanted - {"og.webp"})))
check("no frame is borrowed from another gallery",
      not [i["id"] for i in images
           if not i["img"].startswith("/static/galleries/persona/")])
for other in sorted(os.listdir(os.path.join(ROOT, "static/galleries"))):
    if other == "persona":
        continue
    there = set(os.listdir(os.path.join(ROOT, "static/galleries", other)))
    check("  nothing of this funnel's landed in %-10s" % other,
          not (there & wanted), str(sorted(there & wanted)))

print("\n--- the placeholder script writes only what it owns ---")
gen = open(os.path.join(ROOT, "scripts/gen_persona_placeholders.py"),
           encoding="utf-8").read()
check("it reads this funnel's config",
      'CONFIG = os.path.join(ROOT, "funnels", "persona.json")' in gen)
check("  and writes into this funnel's gallery",
      '"static", "galleries", "persona"' in gen)
check("  filtering on the path, so another gallery's frame is left alone",
      'OWNED = "/static/galleries/persona/"' in gen
      and 'item["img"].startswith(OWNED)' in gen)
check("  and skipping any id already drawn",
      "if not os.path.exists(os.path.join(OUT, i" in gen)
check("it draws its own share card, because it borrows none",
      'write("og"' in gen and "OG_COLORS" in gen)
check("  and skips that too when it is already there",
      'os.path.exists(os.path.join(OUT, "og.webp"))' in gen)
check("the gradient runs through the colours the config carries",
      '[c["hex"] for c in item["colors"]]' in gen)
# Phase 1.6 renamed frames by the dozen, so the generator sweeps as well as
# writes: a .webp whose id the config no longer names is deleted, or the
# directory quietly keeps the art of every walk this funnel used to be.
check("it deletes a frame the config no longer references",
      "orphans = sorted(f for f in os.listdir(OUT)" in gen
      and "os.remove(os.path.join(OUT, name))" in gen)
check("  keeping the share card, which has no config entry behind it",
      'keep = {i + ".webp" for i, _stops in items} | {"og.webp"}' in gen)
check("  and touching nothing that is not a frame",
      'f.endswith(".webp") and f not in keep' in gen)
check("  in this gallery only", gen.count("os.remove(") == 1
      and "os.remove(os.path.join(OUT," in gen)
check("it draws no text onto a placeholder",
      "ImageDraw" not in gen and "ImageFont" not in gen)
check("nothing imports it — it is a console script",
      not [f for f in os.listdir(ROOT)
           if f.endswith(".py")
           and "gen_persona_placeholders" in open(
               os.path.join(ROOT, f), encoding="utf-8").read()])

print("\n--- the art generator ---")
# The script that replaces the placeholders with real frames. It is console
# work — nothing imports it and no route reaches it — so what is checked here
# is that it reads the same source of truth the funnel does, and that the
# rules the art has to obey are actually in the prompt rather than only in the
# brief that asked for them.
art = open(os.path.join(ROOT, "scripts/gen_persona.py"),
           encoding="utf-8").read()
OG_C = [{"name": "Ink", "hex": "#101820", "element": "ground"}]
check("it reads this funnel's config",
      'CONFIG = os.path.join(ROOT, "funnels", "persona.json")' in art)
check("  and writes into this funnel's gallery",
      '"static", "galleries", "persona"' in art)
check("  filtering on the path, so another gallery is never written",
      'OWNED = "/static/galleries/persona/"' in art
      and 'item["img"].startswith(OWNED)' in art)
check("  at the committed frame geometry",
      "FRAME = (600, 800)" in art and "OG = (1200, 630)" in art
      and "QUALITY = 80" in art)
check("every frame carries the locked identity",
      "STYLE = (" in art and "#101820" in art and "#4EDDC4" in art
      and "#D9B98C" in art)
# Asserted against the assembled prompt rather than the source text, which is
# the difference between checking what gets sent and checking how it was
# typed: the negatives are one string split over six source lines, so "no
# constellations" appears in what the model receives and nowhere in the file.
art_mod = importlib.util.module_from_spec(
    importlib.util.spec_from_file_location(
        "gen_persona", os.path.join(ROOT, "scripts/gen_persona.py")))
art_mod.__loader__.exec_module(art_mod)
sample = art_mod.frames(cfg)
built = " ".join(f["prompt"] for f in sample).lower()
check("  and it builds a prompt for every frame plus the share card",
      len(sample) == len(images) + 1
      and sample[-1]["id"] == "og", str(len(sample)))
# Each negative is here because the model reaches for exactly that thing
# unasked when told to illustrate identity.
for banned in ("no human faces", "no text", "no letters", "no logos",
               "no stars", "no constellations", "no zodiac signs",
               "no tarot", "no crystals", "no moons"):
    check("  every prompt forbids %s" % banned,
          all(banned in f["prompt"].lower() for f in sample), banned)
check("  and allows a person only as a silhouette", "silhouette" in built)
check("  every prompt names the ink, the teal and the sand",
      all(all(hexcode in f["prompt"].lower()
              for hexcode in ("#101820", "#4eddc4", "#d9b98c"))
          for f in sample))
check("  and carries that frame's own three colours",
      all(all(c["hex"] in art_mod.prompt_for(
          st["id"], st.get("question", ""), i["label"], i["colors"])
          for c in i["colors"])
          for st in steps for i in st["pairs"][0]["images"]))
check("  no prompt asks for something the negatives ban",
      not [f["id"] for f in sample
           if "constellation of" in f["prompt"].lower()
           or "a star" in f["prompt"].lower()],
      str([f["id"] for f in sample
           if "constellation of" in f["prompt"].lower()]))
check("  the animal prompts read as English",
      "of an owl" in art_mod.prompt_for("animal", "", "Owl", OG_C)
      and "of a fox" in art_mod.prompt_for("animal", "", "Fox", OG_C))
# A prompt that bans constellations and then asks for one is a prompt arguing
# with itself. The share card wants four joined points; it must not call them
# that.
og_block = art[art.index("OG_SCENE = ("):art.index("def scene_for")]
check("the share card does not ask for what the negatives ban",
      not [w for w in ("constellation", "star", "zodiac", "moon")
           if w in og_block.lower()],
      str([w for w in ("constellation", "star", "zodiac", "moon")
           if w in og_block.lower()]))
check("  and it draws the head the result page draws",
      "profile" in og_block and "no face" in og_block)
check("the twelve animals are asked for as one matched set",
      "ANIMAL_SET" in art and "same construction language" in art
      and "same share of the frame" in art)
check("  with an article that reads, because Owl and Otter exist",
      "def article(" in art and '"an" if' in art)
check("the moodboard step is asked for as colour fields, not objects",
      "MOODBOARD" in art and "no objects" in art)
# The zodiac rule carried over: the check is after the render, not in front of
# it. What did not carry is the kitchen exposure lift — these frames are meant
# to be dark, and lifting them to a photograph's mean luma would throw the
# identity away on every one of them.
check("a render is checked for legibility after it comes back",
      "def legibility(" in art and "MIN_LIT" in art
      and "MAX_MEAN_LUMA" in art and "MIN_STDDEV" in art)
check("  and a frame that fails it is redrawn, not corrected",
      "redrawing" in art and "lift_exposure" not in art)
check("  the checker never loses a frame to its own failure",
      "unmeasured" in art)
# Idempotency, and why it cannot be the placeholder script's rule.
check("a rerun skips what it has really drawn",
      "def already_drawn(" in art and "sha256" in art)
check("  recorded outside the gallery, which holds frames and nothing else",
      'MANIFEST = os.path.join(os.path.dirname(os.path.abspath(__file__))'
      in art)
check("  and keyed on the bytes, not on a file-size guess",
      "def sha(" in art and "hashlib.sha256" in art)
check("it can be run without spending anything",
      '"--dry-run"' in art and "dry run: nothing called" in art)
check("  and refuses to run at all with no key",
      'OPENAI_API_KEY is not set' in art)
check("it logs what each frame cost",
      "cost_usd" in art and "spent" in art)
check("nothing imports it — it is a console script",
      not [f for f in os.listdir(ROOT)
           if f.endswith(".py")
           and "gen_persona" in open(os.path.join(ROOT, f),
                                     encoding="utf-8").read()])

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
# computeWinner never reads one.
check("no archetype scores against one",
      not {t for s in cfg["styles"] for t in s["tags"]} & SERVICE,
      str({t for s in cfg["styles"] for t in s["tags"]} & SERVICE))
check("  and every card carrying one also carries tags that do score",
      all(set(i["tags"]) - SERVICE and set(i["tags"]) - SERVICE <= VOCAB
          for i in service_images),
      str([i["id"] for i in service_images
           if not set(i["tags"]) - SERVICE]))
check("the seeking step opens on Love, which is why it pins its first slot",
      by_step["seeking"]["pairs"][0]["images"][0]["label"] == "Love"
      and by_step["seeking"].get("pin_first") is True)

print("\n--- what pulled them here ---")
PURPOSE_RULES = {
    "purpose_love": ("materials", "How you connect is inside."),
    "purpose_career": ("splurge", "Your working months are inside."),
    "purpose_peace": ("mistakes", "Your calm has a pattern. It's inside."),
    "purpose_path": ("shopping",
                     "Your year, mapped window by window — inside."),
}
pmap = cfg["result_copy"].get("purpose_map") or {}
check("a rule for every purpose tag the quiz can produce",
      sorted(pmap) == sorted(PURPOSE_RULES), str(sorted(pmap)))
seek_tags = {t for i in by_step["seeking"]["pairs"][0]["images"]
             for t in i["tags"] if t in SERVICE}
check("  which is exactly the set the seeking step carries",
      sorted(pmap) == sorted(seek_tags), str(sorted(seek_tags)))
check("  and none of the bond tags, which steer nothing",
      not set(pmap) & BOND, str(sorted(set(pmap) & BOND)))
sections_by_id = {s["id"]: s for s in cfg["report"]["sections"]}
for tag, (section_id, sub) in sorted(PURPOSE_RULES.items()):
    rule = pmap.get(tag) or {}
    check("  %-16s leads with %-10s" % (tag, section_id),
          rule.get("emphasized_section") == section_id,
          str(rule.get("emphasized_section")))
    check("    and says %s" % ('"%s"' % sub),
          rule.get("offer_sub") == sub, repr(rule.get("offer_sub")))
    check("    naming a real section of this report",
          section_id in sections_by_id, section_id)
    # Only a locked one can be led with: the free section is already open
    # above the reorder, and leading with it would be promising them
    # something they have already been given.
    check("    and one that is still behind the paywall",
          (sections_by_id[section_id].get("reveal") or {}).get("mode")
          != "visible")
check("no two purposes lead with the same section",
      len({r.get("emphasized_section") for r in pmap.values()}) == len(pmap))
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
           if "$" in r["offer_sub"] or "{" in r["offer_sub"]])

print("\n--- interstitials ---")
mids = cfg["interstitials"]
anchors = [i["after_step"] for i in mids]
check("four of them, at the twin's anchors", anchors == [4, 9, 14, 18],
      str(anchors))
check("  every one lands after a step that exists",
      all(1 <= a <= len(steps) for a in anchors), str(anchors))
names = [steps[a - 1]["id"] for a in anchors]
check("they land after bond/talisman/decision/seal",
      names == ["bond", "talisman", "decision", "seal"], str(names))
check("the last one closes the run rather than sitting inside it",
      anchors[-1] == len(steps))
for entry in mids:
    check("  after %-2d has a kicker, a line and a cta" % entry["after_step"],
          all(entry.get(k) for k in ("kicker", "line", "cta")),
          json.dumps(entry)[:100])
check("every cta is the one this funnel uses",
      {e["cta"] for e in mids} == {"Continue analysis"},
      str(sorted({e["cta"] for e in mids})))
check("four beats, four different kickers",
      len({e["kicker"] for e in mids}) == 4,
      str(sorted({e["kicker"] for e in mids})))
check("templates are ones the engine knows how to draw",
      {e["template"] for e in mids} <= {"pattern", "confirm", "almost"},
      str(sorted({e["template"] for e in mids})))
check("  the two progress beats are the ones drawn as a bar",
      [e["after_step"] for e in mids if e["template"] == "almost"] == [9, 18],
      str([(e["after_step"], e["template"]) for e in mids]))
check("the closing beat counts every step",
      str(len(steps)) in mids[-1]["line"], mids[-1]["line"])
pct = [e for e in mids if "{pct}" in e["line"]]
check("one of them is templated on progress", len(pct) == 1)
check("  and the percentage it will show is honest",
      [round(e["after_step"] / len(steps) * 100) for e in pct] == [50],
      str([round(e["after_step"] / len(steps) * 100) for e in pct]))
# {pct} is fillTokens' own, derived from step / pairs_count. Every other one
# it knows belongs to another funnel's vocabulary, and canFill would drop the
# whole screen rather than show a hole.
DEAD = re.compile(r"\{leading_trait\}|\{opposite\}|\{leading_material\}"
                  r"|\{sign\}|\{n\}|\{total\}")
check("no beat leans on a token this vocabulary cannot fill",
      not [e for e in mids
           if DEAD.search((e.get("line") or "") + (e.get("sub") or ""))],
      str([e["kicker"] for e in mids
           if DEAD.search((e.get("line") or "") + (e.get("sub") or ""))]))


def sentences(entry):
    """Every sentence this entry can put on screen — its own and the ones a
    run can substitute for them. A personalised line is a line only some runs
    ever read, which is exactly where a bad number or word survives."""
    out = [entry["line"], entry.get("sub") or ""]
    for row in ((entry.get("personal") or {}).get("lines") or {}).values():
        out += [row.get("line") or "", row.get("sub") or ""]
    return out


STAT = re.compile(r"\b\d+\s*%")
check("no beat prints a percentage that is not {pct}",
      not [t for e in mids for t in sentences(e)
           if STAT.search(t.replace("{pct}%", ""))],
      str([t for e in mids for t in sentences(e)
           if STAT.search(t.replace("{pct}%", ""))]))
SAID = re.compile(r"\b(one|two|three|four|five|six|seven|eight|nine|ten|"
                  r"\d+)\s+(?:personal\s+)?signals?\b", re.I)
WORD = {"one": 1, "two": 2, "three": 3, "four": 4, "five": 5, "six": 6,
        "seven": 7, "eight": 8, "nine": 9, "ten": 10}
for entry in mids:
    for text in sentences(entry):
        hit = SAID.search(text)
        if not hit:
            continue
        said = WORD.get(hit.group(1).lower()) or int(hit.group(1))
        after = entry["after_step"]
        personal = len([s for s in steps[:after]
                        if set(t for i in s["pairs"][0]["images"]
                               for t in i["tags"]) & SERVICE])
        want = ((personal,) if "personal" in hit.group(0).lower()
                else (after, len(steps) - after, len(steps)))
        check("  %-38s is true after %d" % ('"%s"' % text, after),
              said in want,
              "says %d, want one of %s" % (said, str(want)))

print("\n--- and every one of them advances itself ---")
AUTO = {4: 2000, 9: 2000, 14: 2000, 18: 2400}
check("all four carry auto_advance_ms",
      all(isinstance(e.get("auto_advance_ms"), int) for e in mids))
check("  two seconds each, and a beat longer on the last",
      {e["after_step"]: e["auto_advance_ms"] for e in mids} == AUTO,
      str({e["after_step"]: e["auto_advance_ms"] for e in mids}))
check("  every timing is inside the bounds the engine clamps to",
      all(600 <= e["auto_advance_ms"] <= 4000 for e in mids))
check("  and none of them is long enough to read as a wait",
      max(e["auto_advance_ms"] for e in mids) <= 2400)
WITH_SUB = [4, 14, 18]
check("three of them keep a sub",
      [e["after_step"] for e in mids if e.get("sub")] == WITH_SUB,
      str([e["after_step"] for e in mids if e.get("sub")]))
check("  the subs are one short line each",
      all(len(e["sub"]) <= 45 and "\n" not in e["sub"]
          for e in mids if e.get("sub")),
      str([(e["after_step"], len(e["sub"])) for e in mids if e.get("sub")]))

print("\n--- the echo: which frames each beat hands back ---")
seen_steps = 0
for entry in mids:
    after = entry["after_step"]
    want = [s["id"] for s in steps][seen_steps:after]
    check("  after %-2d echoes the steps it closes" % after,
          entry.get("echo_steps") == want,
          "%s vs %s" % (entry.get("echo_steps"), want))
    seen_steps = after
echoed = [t for e in mids for t in e["echo_steps"]]
check("every step is handed back exactly once, in walk order",
      echoed == [s["id"] for s in steps], str(echoed))
check("the funnel asks for the analysing grid too",
      cfg.get("analyzing_echo") is True)
STAGGER = int(re.search(r"var ECHO_STAGGER_MS = (\d+)", engine).group(1))
CEILING_MS = int(re.search(r"var ECHO_HOLD_MS = (\d+)", engine).group(1))
check("no beat is cut off mid-row",
      all(e["auto_advance_ms"] + len(e["echo_steps"]) * STAGGER <= CEILING_MS
          for e in mids),
      str([(e["after_step"],
            e["auto_advance_ms"] + len(e["echo_steps"]) * STAGGER)
           for e in mids]))
check("  and each one outlasts its own last thumbnail",
      all(e["auto_advance_ms"] + len(e["echo_steps"]) * STAGGER
          > (len(e["echo_steps"]) - 1) * STAGGER for e in mids))

print("\n--- the lines that say what the run said ---")
by_after = {e["after_step"]: e for e in mids}
check("three of the four carry a personal block",
      sorted(e["after_step"] for e in mids if "personal" in e) == [4, 9, 14],
      str(sorted(e["after_step"] for e in mids if "personal" in e)))
check("  and the closing one is static, because nothing is left to read",
      "personal" not in by_after[18])
check("the opening beat answers the animal they tapped",
      by_after[4]["personal"].get("step") == "animal",
      str(by_after[4]["personal"].get("step")))
check("  naming every card on that step and no others",
      sorted(by_after[4]["personal"]["lines"])
      == sorted(i["id"] for i in animals),
      str(sorted(by_after[4]["personal"]["lines"])))
check("the deep beat answers the fork they took",
      by_after[14]["personal"].get("step") == "decision")
check("  naming every card on that step and no others",
      sorted(by_after[14]["personal"]["lines"])
      == sorted(i["id"] for i in by_step["decision"]["pairs"][0]["images"]),
      str(sorted(by_after[14]["personal"]["lines"])))
check("the middle beat answers the axis that is leading",
      by_after[9]["personal"].get("axis") == "axis",
      str(by_after[9]["personal"].get("axis")))
check("  with a line for every axis a run can lead on",
      sorted(by_after[9]["personal"]["lines"]) == sorted(AXIS),
      str(sorted(by_after[9]["personal"]["lines"])))
for after, rule in sorted((e["after_step"], e["personal"]) for e in mids
                          if "personal" in e):
    check("  after %-2d keys on one thing and carries lines" % after,
          sorted(rule) in (["lines", "step"], ["axis", "lines"]),
          str(sorted(rule)))
    check("    every line comes in two halves, so the block keeps its shape",
          all(row.get("line") and row.get("sub")
              for row in rule["lines"].values()),
          str([k for k, v in rule["lines"].items()
               if not (v.get("line") and v.get("sub"))]))
# The axis beat, which phase 1 shipped dormant. `personalTag` resolves an
# accumulated axis only when AXES declares it, and until this phase AXES was a
# table that had never heard of these four words — so the beat fell back to its
# own base line on every run. The check below was written to fail the day the
# engine learned them, and this is that day.
declared = set(re.findall(r"(\w+):\s*\w+_AXIS",
                          re.search(r"var AXES = \{([^}]*)\}",
                                    engine, re.S).group(1)))
check("engine.js declares this funnel's axis", "axis" in declared,
      str(sorted(declared)))
check("  as the four words this funnel scores on, in order",
      re.search(r"var AXIS_AXIS = \[([^\]]*)\]", engine).group(1)
      .replace('"', "").replace(" ", "").split(",")
      == ["drive", "anchor", "wave", "prism"],
      re.search(r"var AXIS_AXIS = \[([^\]]*)\]", engine).group(1))
check("  which is exactly the set the axis beat writes lines for",
      sorted(by_after[9]["personal"]["lines"]) == sorted(AXIS))
check("  so every one of those lines can now be reached",
      set(by_after[9]["personal"]["lines"]) <= set(declared and AXIS))
check("  and it still declares the words it always did, unmoved",
      {"tone", "material", "season", "element", "energy"} <= declared,
      str(sorted(declared)))
check("  the celestial axes byte for byte, so no zodiac funnel moved",
      re.search(r"var ELEMENT_AXIS = \[([^\]]*)\]", engine).group(1)
      .replace('"', "").replace(" ", "").split(",")
      == ["fire", "earth", "air", "water"]
      and re.search(r"var ENERGY_AXIS = \[([^\]]*)\]", engine).group(1)
      .replace('"', "").replace(" ", "").split(",") == ["sun", "moon"])
check("  and no other funnel scores against a word persona named",
      not [slug for slug in NEIGHBOUR_SLUGS
           for st in json.load(open(
               os.path.join(ROOT, "funnels/%s.json" % slug),
               encoding="utf-8"))["styles"]
           if set(st["tags"]) & AXIS],
      str(AXIS))
check("  the two step-keyed beats are unaffected, because a step is a step",
      all(rule.get("step") in by_step for rule in
          [by_after[4]["personal"], by_after[14]["personal"]]))

print("\n--- placeholders ---")
# Every token in the copy, against everything that can answer one. The hook
# slots are engine.js's; the profile words are result_persona.js's own, filled
# from the block it derives from the run's tallies.
PROFILE_TOKENS = {"axis", "second", "energy", "subtype", "subtype_bare",
                  "subtype_article", "drive", "anchor", "wave", "prism",
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
# `talisman` was the last mystical word in the on-screen copy: a slot key the
# reader met as "Your {talisman} and your {weather}". The step keeps its id —
# ids are stable across this phase — but the word the copy reads is the plain
# one now.
check("no on-screen token is the old mystical one",
      "carry" in cfg["report"]["hook_slots"]
      and "talisman" not in cfg["report"]["hook_slots"],
      str(sorted(cfg["report"]["hook_slots"])))
check("  and it still reads off the step that asks what they carry",
      cfg["report"]["hook_slots"]["carry"]["step"] == "talisman")
check("  with a fallback that is a phrase, not a hole",
      cfg["report"]["hook_slots"]["carry"]["fallback"] == "everyday carry")
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
check("the preview gallery reuses quiz images, with their tags and paths",
      all(g["id"] in by_id and g["tags"] == by_id[g["id"]]["tags"]
          and g["img"] == by_id[g["id"]]["img"]
          for g in cfg["preview_gallery"]),
      str([g["id"] for g in cfg["preview_gallery"] if g["id"] not in by_id]))
check("every style element points at a live quiz image",
      all(e["image"] in by_id and e["img"] == by_id[e["image"]]["img"]
          and e["tags"] == by_id[e["image"]]["tags"]
          for e in cfg["style_elements"]["items"]),
      str([e["image"] for e in cfg["style_elements"]["items"]
           if e["image"] not in by_id]))

print("\n--- the words this vertical does not use ---")
# Local, and deliberately not reports.py's. persona has no profile registered
# there yet — that is Phase 3 — and a copy rule this funnel has to keep from
# its first commit should not have to wait for one. The list is the celestial
# funnels' own, extended with the two families a personality quiz can slide
# into if nobody is watching: the clinical, and somebody else's framework.
BANNED = [
    # what the twin already refuses
    "psychic", "prediction", "predictions", "predict", "fortune",
    "your future will", "clairvoyant", "horoscope", "prophecy", "prophecies",
    "destined to", "fated to", "symptom", "symptoms",
    "medication", "prescription", "financial advice",
    # the clinical half, which is this vertical's own risk
    "diagnosis", "diagnose", "disorder", "iq", "therapy", "therapist",
    "clinical", "psychometric", "scientifically proven",
    "scientifically validated",
    # and somebody else's framework, which is the other one
    "mbti", "enneagram", "disc profile", "big five", "16personalities",
    "introvert", "extrovert",
]
WORDY = re.compile(r"[a-z0-9]")


def banned_hit(text):
    """The first banned phrase in a string, or None.

    Word-bounded on both ends so `iq` does not fire on "unique" and
    `predict` does not fire on a word that merely contains it.
    """
    low_text = (text or "").lower()
    for word in BANNED:
        for found in re.finditer(re.escape(word), low_text):
            before = low_text[found.start() - 1] if found.start() else " "
            after = low_text[found.end():found.end() + 1] or " "
            if not WORDY.match(before) and not WORDY.match(after):
                return word
    return None


# Every string in the config, which on this funnel is every word it wrote —
# unlike the twin, nothing here is inherited from another config.
SCANNED = strings(cfg)
dirty = [(t[:50], banned_hit(t)) for t in SCANNED if banned_hit(t)]
check("no on-screen string says a banned word", not dirty, str(dirty[:4]))
check("  and the scan actually read the whole config",
      len(SCANNED) > 800, str(len(SCANNED)))
# The check checking itself: a list that matches nothing is a list nobody
# would notice going stale.
check("  the scanner catches one when there is one",
      banned_hit("a clinical diagnosis") == "diagnosis"
      and banned_hit("your MBTI type") == "mbti"
      and banned_hit("scored as an introvert") == "introvert")
check("  and does not fire on ordinary English that contains a banned word",
      banned_hit("a unique and antique object") is None
      and banned_hit("predictable, disordered prose") is None,
      str(banned_hit("a unique and antique object")))
# Phrases rather than words. "Study ink" is a colour and "a compass that
# does not need to be accurate" is a joke; what this vertical may not do is
# borrow the authority of a measurement it did not make.
CLAIMS = re.compile(
    r"research shows|studies show|(?:is|are) proven|proven to|"
    r"clinically|test score|\d+\s*%\s*accurate|accuracy rate|"
    r"peer[- ]reviewed|validated by")
check("nothing here borrows the authority of a study or a test score",
      not CLAIMS.search(copy_text), str(CLAIMS.findall(copy_text)[:4]))
check("and nothing invents a statistic outside the measured rarity",
      not [t for t in SCANNED
           if re.search(r"\b\d+\s*%", t.replace("{pct}%", ""))],
      str([t for t in SCANNED
           if re.search(r"\b\d+\s*%", t.replace("{pct}%", ""))][:3]))

print("\n--- pricing ---")
check("price is 300 usd", cfg["pricing"] == {"amount_cents": 300,
                                             "currency": "usd",
                                             "cta": "Unlock my full profile"},
      str(cfg["pricing"]))
shown = "$%d" % (cfg["pricing"]["amount_cents"] // 100)
priced = [t for t in re.findall(r'"([^"]*\$[^"]*)"',
                                json.dumps(cfg, ensure_ascii=False))
          if shown in t]
check("  and no copy states it — every mention is the {price} token",
      not priced, str(priced))
check("  the price token is actually used where the reader decides",
      "{price}" in cfg["checkout"]["cta_label"]
      and "{price}" in cfg["checkout"]["commerce"]["sticky_label"])

print("\n--- the four archetypes ---")
STYLE_TAGS = {
    "igniter": ["drive", "outer", "bold"],
    "keeper": ["anchor", "inner", "calm"],
    "feeler": ["wave", "outer", "deep"],
    "thinker": ["prism", "inner", "deep"],
}
STYLE_NAME = {"igniter": "The Igniter", "keeper": "The Keeper",
              "feeler": "The Feeler", "thinker": "The Thinker"}
check("four of them, in the authored order",
      [s["id"] for s in cfg["styles"]] == ["igniter", "keeper", "feeler",
                                           "thinker"],
      str([s["id"] for s in cfg["styles"]]))
for style in cfg["styles"]:
    check("  %-8s is %-13s on %s" % (style["id"], style["name"],
                                     "/".join(STYLE_TAGS[style["id"]])),
          style["name"] == STYLE_NAME[style["id"]]
          and style["tags"] == STYLE_TAGS[style["id"]],
          "%s / %s" % (style["name"], style["tags"]))
    check("    one axis, one energy, one tone",
          len(set(style["tags"]) & AXIS) == 1
          and len(set(style["tags"]) & ENERGY) == 1
          and len(set(style["tags"]) & TONE) == 1)
    check("    with a blurb and the six reveals, mistake_one among them",
          style.get("blurb")
          and set(style["reveals"]) == {"palette", "mistakes", "dna",
                                        "materials", "splurge", "shopping",
                                        "mistake_one"},
          str(sorted(style["reveals"])))
    one = style["reveals"]["mistake_one"]
    check("    and the free strength is whole",
          all(one.get(k) for k in ("title", "body", "fix")), str(sorted(one)))
check("no two archetypes lead on the same axis",
      len({(set(s["tags"]) & AXIS).pop() for s in cfg["styles"]}) == 4)
check("all four axes are led by somebody",
      {(set(s["tags"]) & AXIS).pop() for s in cfg["styles"]} == AXIS)

print("\n--- the twenty-four subtypes ---")
profile = cfg["result_copy"]["profile"]
subs = profile["subtypes"]
check("a table for every archetype", sorted(subs) == sorted(STYLE_TAGS),
      str(sorted(subs)))
names = []
for style_id, tags in sorted(STYLE_TAGS.items()):
    primary = (set(tags) & AXIS).pop()
    want = sorted(AXIS - {primary})
    check("  %-8s crosses the three axes that are not its own" % style_id,
          sorted(subs[style_id]) == want, str(sorted(subs[style_id])))
    for second in want:
        check("    x %-7s names an outer and an inner" % second,
              sorted(subs[style_id][second]) == ["inner", "outer"],
              str(sorted(subs[style_id][second])))
        names += list(subs[style_id][second].values())
check("twenty-four names in all", len(names) == 24, str(len(names)))
check("  every one of them distinct", len(set(names)) == 24,
      str([n for n, c in collections.Counter(names).items() if c > 1]))
check("  and every one of them is a The", all(n.startswith("The ")
                                              for n in names),
      str([n for n in names if not n.startswith("The ")]))
KNOWN_NAMES = {
    "The Open Flame", "The Steady Spark", "The Signal Fire",
    "The Coiled Spring", "The Patient Ember", "The Slow Burn",
    "The Standing Stone", "The Harbor Wall", "The Old Oak",
    "The Quiet Fortress", "The Still Foundation", "The Deep Root",
    "The Rising Tide", "The Warm Shore", "The Open Sea",
    "The Hidden Spring", "The Gentle Stream", "The Deep Current",
    "The Bright Beacon", "The Clear Lens", "The Far Lighthouse",
    "The Sharp Compass", "The Quiet Cartographer", "The Night Astronomer",
}
check("the twenty-four are the ones the brief names",
      set(names) == KNOWN_NAMES, str(sorted(set(names) ^ KNOWN_NAMES)))

print("\n--- the hero card's own tables ---")
check("three scales: tone, energy, depth",
      [r["id"] for r in profile["scales"]] == ["tone", "energy", "depth"],
      str([r["id"] for r in profile["scales"]]))
check("  labelled bold-calm, outer-inner, light-deep",
      [(r["left"], r["right"]) for r in profile["scales"]]
      == [("Bold", "Calm"), ("Outer", "Inner"), ("Light", "Deep")],
      str([(r["left"], r["right"]) for r in profile["scales"]]))
check("the formula names the animal, the axis, the runner-up and the energy",
      profile["formula"]
      == "{animal} · {axis}-led, {second} undercurrent · {energy}",
      profile["formula"])
check("the split caption names all four axes",
      all("{%s}%%" % tag in profile["split_caption"] for tag in AXIS),
      profile["split_caption"])
cross = profile["animal_cross"]
check("a cross line for every animal on the grid",
      sorted(cross) == sorted(ANIMALS), str(sorted(cross)))
check("  and no key nothing can reach",
      set(cross) == {i["label"] for i in animals},
      str(sorted(set(cross) ^ {i["label"] for i in animals})))
for animal, rows in sorted(cross.items()):
    check("  %-9s reads against all four axes" % animal,
          sorted(rows) == sorted(AXIS) and all(rows.values()),
          str(sorted(rows)))
lines = [line for rows in cross.values() for line in rows.values()]
check("forty-eight lines, every one of them distinct",
      len(lines) == 48 and len(set(lines)) == 48,
      "%d lines, %d distinct" % (len(lines), len(set(lines))))
CARD_IDS = ["materials", "mistakes", "shopping", "splurge", "palette", "dna"]
check("six question cards, one per report section",
      [c["id"] for c in profile["cards"]] == CARD_IDS,
      str([c["id"] for c in profile["cards"]]))
check("  each with a keyword, an icon and a promise",
      all(c.get("key") and c.get("icon") and c.get("promise")
          for c in profile["cards"]))
check("  and every id is a section this report has",
      all(c["id"] in sections_by_id for c in profile["cards"]))

print("\n--- rarity ---")
rarity = profile["rarity"]
LADDER = {6, 8, 10, 12, 15, 20, 25, 30, 40}
flat = [(a, b, c, v) for a, m in rarity.items()
        for b, n in m.items() for c, v in n.items()]
check("a number for all twenty-four blends", len(flat) == 24, str(len(flat)))
check("  keyed the same way the subtype table is",
      sorted((a, b, c) for a, b, c, _v in flat)
      == sorted((sid, second, energy) for sid, m in subs.items()
                for second, n in m.items() for energy in n),
      "keys differ")
check("  every one of them on the round-number ladder",
      all(v in LADDER for _a, _b, _c, v in flat),
      str(sorted({v for _a, _b, _c, v in flat} - LADDER)))
check("  and none of them claiming rarer than 1 in 6",
      min(v for _a, _b, _c, v in flat) >= 6)
check("the line that prints it says what it is",
      profile["rarity_line"] == "About 1 in {n} profiles land this blend",
      profile["rarity_line"])

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

    Three cases, and pickPair reads them in this order: `shuffle: false` keeps
    every slot, `pin_first` keeps the first and shuffles the rest, and
    anything else shuffles all of them. With no rng the config order is
    returned as-is, which is what the archetype walks below want — they rank
    the cards rather than reading them off a screen.
    """
    cards = [i for p in step["pairs"] for i in p["images"]]
    if rng is None or step.get("shuffle") is False:
        return cards
    if step.get("pin_first"):
        rest = cards[1:]
        rng.shuffle(rest)
        return cards[:1] + rest
    order = list(cards)
    rng.shuffle(order)
    return order


def play(pick, rng=None):
    """One run, as engine.js scores it: -0.5 a tag on the inverse step, 1 on
    every other. Nothing here is adaptive, so every step draws its one pair."""
    scores = {}
    for step in steps:
        options = dealt(step, rng)
        weight = -0.5 if step.get("scoring") == "inverse" else 1
        for tag in pick(step, options)["tags"]:
            scores[tag] = scores.get(tag, 0) + weight
    return scores


for style in cfg["styles"]:
    want = set(style["tags"])
    axis = (want & AXIS).pop()

    def deliberate(step, options, want=want, axis=axis):
        def rank(item):
            return (axis in item["tags"], len(set(item["tags"]) & want))

        if step.get("scoring") == "inverse":
            return min(options, key=rank)
        return max(options, key=rank)

    got = winner(play(deliberate))
    check("a %-8s run is given %s" % (style["id"], style["name"]),
          got == style["id"], got)

# A run that answers only the two service steps scores nothing any archetype
# reads. That is the whole claim about them, stated as a run rather than as a
# set operation.
service_only = collections.Counter(
    t for sid in ("seeking", "bond")
    for t in by_step[sid]["pairs"][0]["images"][0]["tags"] if t in SERVICE)
check("a score made only of service tags moves no archetype",
      all(sum(service_only.get(t, 0) for t in s["tags"]) == 0
          for s in cfg["styles"]), str(dict(service_only)))

FLOOR, CEILING = 15.0, 35.0
WALKS = 20000


def bucket(scores):
    """(archetype, runner-up axis, energy) for one finished run.

    The three resolutions here are result_persona.js's, deliberately: a
    distribution measured on a different definition of "runner-up" than the
    one printed beside the rarity is a number about nothing.
    """
    style_id = winner(scores)
    tags = next(s["tags"] for s in cfg["styles"] if s["id"] == style_id)
    primary = next(t for t in tags if t in AXIS)
    rest = [t for t in sorted(AXIS, key=["drive", "anchor", "wave",
                                         "prism"].index) if t != primary]
    at = (lambda tag: max(0, scores.get(tag, 0)))
    second = max(rest, key=lambda t: (at(t), -rest.index(t)))
    outer, inner = at("outer"), at("inner")
    if outer > inner:
        energy = "outer"
    elif inner > outer:
        energy = "inner"
    else:
        energy = next((t for t in tags if t in ENERGY), "outer")
    return style_id, second, energy


def walk(excess, seed=20260826):
    """WALKS runs from a reader who over-taps the first slot by `excess` on
    top of the 1/n an indifferent one would.

    A shuffled step's first slot is a different card every run, so the excess
    lands nowhere in particular. On the two steps whose first slot is fixed it
    lands on the same card every time, which is the whole reason this is
    modelled rather than assumed: `animal` pins Owl, and `seeking` pins Love.
    """
    rng = random.Random(seed)

    def reader(step, options):
        if excess and len(options) > 1 and rng.random() < excess:
            return options[0]
        return rng.choice(options)

    seen = collections.Counter()
    blends = collections.Counter()
    for _ in range(WALKS):
        scores = play(reader, rng)
        seen[winner(scores)] += 1
        blends[bucket(scores)] += 1
    return seen, blends


for excess, who in ((0.0, "an indifferent reader"),
                    (0.10, "a first-slot reader"),
                    (0.20, "a hard first-slot reader")):
    seen, blends = walk(excess)
    for style in cfg["styles"]:
        got = 100.0 * seen[style["id"]] / WALKS
        check("  %-8s takes %4.1f%% from %-24s (%.0f-%.0f)"
              % (style["id"], got, who, FLOOR, CEILING),
              FLOOR <= got <= CEILING)
    check("  the four shares account for every walk",
          sum(seen.values()) == WALKS, str(sum(seen.values())))
    # Every name in the table has to be reachable, or it is copy nobody is
    # ever shown and a rarity measured against nothing.
    reach = {(sid, second, energy) for sid, m in subs.items()
             for second, n in m.items() for energy in n}
    check("  and all twenty-four subtypes are reachable",
          reach <= set(blends), str(sorted(reach - set(blends))))
check("the inverse step can push a total negative — the floor is -Infinity",
      any(s.get("scoring") == "inverse" for s in steps))

print("\n--- server side ---")
import app  # noqa: E402
import config  # noqa: E402
import payments  # noqa: E402
import tracking  # noqa: E402

check("the slug is routable", config.funnel_exists("persona"))
check("  and is a legal slug for the /<slug> route",
      config.valid_slug("persona"))
check("load_funnel returns this config", config.load_funnel("persona") == cfg)
check("payments reads it as a test-mode funnel",
      payments._stripe_mode(cfg) == payments.TEST, payments._stripe_mode(cfg))
# Two different things wearing the same word, and the funnel sits across both.
#
# `stripe_mode: test` is about which key set takes the money. The route guard
# main grew for the sandbox twins is about who may see the page at all, and it
# keys on a `-test` slug suffix rather than on the mode — so persona is served
# to everybody while still being unable to charge a real card. That is the
# posture a funnel whose art is still placeholders wants, and it is an
# accident of two independent switches lining up, so it is pinned here.
check("the slug is not a sandbox twin's, so the route guard leaves it alone",
      not config.is_test_slug("persona"), "persona")
check("  which is what keeps it served whatever TEST_FUNNELS says",
      config.is_test_slug("zodiac-ro-test")
      and not config.is_test_slug("zodiac-ro"))
# Both sides of the guard, driven rather than observed: the flag is set here
# so the answer is about the code and not about this shell's .env.
_flag = config.TEST_FUNNELS
try:
    for flag in (False, True):
        config.TEST_FUNNELS = flag
        with app.app.test_client() as client:
            check("  /persona is served with TEST_FUNNELS=%s" % flag,
                  client.get("/persona").status_code == 200)
            check("    while the twin answers %d"
                  % (200 if flag else 404),
                  client.get("/zodiac-ro-test").status_code
                  == (200 if flag else 404))
finally:
    config.TEST_FUNNELS = _flag
# And the half that keeps it harmless: a test-mode funnel with no test key
# refuses outright. `_stripe_secret` returns "" for an unconfigured mode, and
# payments treats that as no checkout rather than reaching for the live key.
_secret = config.STRIPE_TEST_SECRET_KEY
try:
    config.STRIPE_TEST_SECRET_KEY = ""
    check("but with no test key it has nothing to charge with",
          payments._stripe_secret(payments._stripe_mode(cfg)) == "",
          repr(payments._stripe_secret(payments._stripe_mode(cfg))))
    config.STRIPE_TEST_SECRET_KEY = "sk_test_standin"
    check("  and with one, it is the test key and never the live one",
          payments._stripe_secret(payments._stripe_mode(cfg))
          == "sk_test_standin")
finally:
    config.STRIPE_TEST_SECRET_KEY = _secret
# Against stand-ins rather than against whatever this shell's .env holds, so
# the claim is about the wiring and not about one machine. No live key is
# read, printed or sent anywhere by any of it.
_env = (config.STRIPE_SECRET_KEY, config.STRIPE_PUBLISHABLE_KEY,
        config.STRIPE_TEST_SECRET_KEY, config.STRIPE_TEST_PUBLISHABLE_KEY)
try:
    config.STRIPE_SECRET_KEY = "sk_live_standin"
    config.STRIPE_PUBLISHABLE_KEY = "pk_live_standin"
    config.STRIPE_TEST_SECRET_KEY = "sk_test_standin"
    config.STRIPE_TEST_PUBLISHABLE_KEY = "pk_test_standin"
    mode = payments._stripe_mode(cfg)
    check("  and resolves to the STRIPE_TEST_* pair, not the live one",
          payments._stripe_secret(mode) == "sk_test_standin"
          and payments._stripe_publishable(mode) == "pk_test_standin",
          "%s / %s" % (payments._stripe_secret(mode),
                       payments._stripe_publishable(mode)))
    live = payments._stripe_mode(config.load_funnel("zodiac30"))
    check("    which is not the pair the live funnels resolve to",
          payments._stripe_secret(live) == "sk_live_standin")
finally:
    (config.STRIPE_SECRET_KEY, config.STRIPE_PUBLISHABLE_KEY,
     config.STRIPE_TEST_SECRET_KEY, config.STRIPE_TEST_PUBLISHABLE_KEY) = _env
choices = [s["pairs"][0]["images"][0]["id"] for s in steps]
check("checkout accepts an 18-long choice list",
      payments._clean_choices(cfg, choices) == choices)
check("  and rejects a 19-long one",
      payments._clean_choices(cfg, choices + ["tl9a"]) is None)
check("  a short list is accepted, as it is on every funnel",
      payments._clean_choices(cfg, choices[:12]) == choices[:12])
check("  and a repeated tap is not",
      payments._clean_choices(cfg, choices[:-1] + [choices[0]]) is None)
check("tag scores validate against this vocabulary",
      payments._clean_tag_scores(cfg, {"drive": 6, "outer": 5, "bold": 4})
      == {"drive": 6, "outer": 5, "bold": 4})
check("  service tags among them too, since the engine sends every score",
      payments._clean_tag_scores(cfg, {"purpose_love": 1, "wave": 3})
      == {"purpose_love": 1, "wave": 3})
check("  and another funnel's tag is refused",
      payments._clean_tag_scores(cfg, {"fire": 1}) is None)
for step in steps:
    shown = [i["id"] for i in step["pairs"][0]["images"]]
    got = tracking._clean_extra("persona", "swipe",
                                {"pair": "%s:p1" % step["id"],
                                 "shown": shown, "chosen": shown[0]})
    check("tracking accepts the %-12s step" % step["id"],
          got["chosen"] == shown[0], str(got))
check("tracking allows step 18", tracking._clean_step(18) == 18)
try:
    tracking._clean_extra("persona", "swipe",
                          {"pair": "seeking:p1",
                           "shown": ["sk3a", "sk3b", "sk3c", "zk1a"],
                           "chosen": "sk3a"})
    check("tracking rejects an image from another funnel", False)
except ValueError:
    check("tracking rejects an image from another funnel", True)
try:
    tracking._clean_extra("persona", "swipe",
                          {"pair": "seeking:p1",
                           "shown": ["sk3a", "sk3b", "sk3c", "sk3d"],
                           "chosen": "ph1a"})
    check("  and a card the step does not offer", False)
except ValueError:
    check("  and a card the step does not offer", True)

print("\n--- the module this funnel names ---")
module = open(os.path.join(ROOT, "static/js/result_persona.js"),
              encoding="utf-8").read()
sheet = open(os.path.join(ROOT, "static/css/result_persona.css"),
             encoding="utf-8").read()
check("it is a module, not a script with side effects",
      "window.MazzinResult = { render: render, delivered: delivered };"
      in module)
check("  drawing both halves of the page",
      "function render(root, ctx)" in module
      and "function delivered(root, ctx)" in module)
check("it scores on this funnel's axes and nobody else's",
      'var AXES = ["drive", "anchor", "wave", "prism"];' in module
      and 'var ENERGY = ["outer", "inner"];' in module
      and 'var TONE = ["bold", "calm", "deep"];' in module)
module_code = re.sub(r"//[^\n]*", "",
                     re.sub(r"/\*.*?\*/", "", module, flags=re.S))
check("  and never names the slug, so the config is the gate",
      "persona" not in module_code,
      str([ln for ln in module_code.split("\n") if "persona" in ln][:2]))
check("every class it draws carries the pr- prefix",
      not re.findall(r'"(?:zr|km)-[\w -]*"', module),
      str(re.findall(r'"(?:zr|km)-[\w -]*"', module)[:5]))
check("  and the stylesheet paints only those",
      not re.search(r"\.zr-", sheet),
      str(re.findall(r"\.zr-[\w-]+", sheet)[:4]))
check("the stylesheet is scoped, so it cannot reach another funnel's page",
      ".result-module {" in sheet and "body:has(.result-module)" in sheet)
check("  in this funnel's ink and accent",
      "--pr-ink: #101820;" in sheet and "--pr-teal: #4EDDC4;" in sheet)
check("the purpose map is the gate, not the slug",
      "result_copy) || {}).purpose_map" in module
      and "function purposeRule(" in module
      and "if (!map) return null;" in module)
check("  the tag is found by tag, not by naming the seeking step",
      "function purposeTag(" in module_code
      and "seeking" not in module_code
      and "Object.keys(picks)" in module_code)
check("  only the first match moves, and a name matching nothing moves none",
      "function firstly(" in module
      and "return hit ? [hit].concat(rest) : sections;" in module)
check("  and the offer's sub-line is the only copy the rule replaces",
      "(rule && rule.offer_sub) || copy.offer_sub" in module
      and not re.search(r"rule && rule\.(price|cta|trust|anchor)", module))
check("the delivered page reorders too, off the stored tag",
      "firstly(ctx.sections, emphasised(purposeRule(ctx)))" in module
      and "ctx.purpose" in module)
check("the pay button and the consent box are engine.js's, only moved",
      "nodes.payButton" in module and "nodes.consent" in module
      and "fetch(" not in module and "XMLHttpRequest" not in module)
check("  and the offer card is what the paywall event watches",
      "ctx.watchOffer(card)" in module)

print("\n--- the head ---")
# The one drawing on this page, and the only part of the module whose exact
# numbers are the product. They are pinned here because the same geometry has
# to be reproducible server-side for the PDF in a later phase, and a drawing
# that drifted between the two would be two different heads sold as one.
check('the canvas is 420 x 410, shifted left by forty',
      'viewBox: "0 0 420 410"' in module
      and 'transform: "translate(-40,0)"' in module)
check("the silhouette is one path, stroked and never filled",
      'd: HEAD_PATH, fill: "none", stroke: "#7E8C96",'
      ' "stroke-width": 6' in module
      and '"stroke-linecap": "round", "stroke-linejoin": "round"' in module)
check("  starting where the mockup starts it",
      module.count("M 372 400 C 366 380 358 360 360 336") == 1)
check("  and ending where the mockup ends it",
      "C 191 375 191 380 190 385" in module)
check("the radar is centred in the skull, not on the canvas",
      "var HEAD_CX = 262;" in module and "var HEAD_CY = 204;" in module
      and "var HEAD_R = 120;" in module)
check("  three rings and two crosshairs, in the quietest ink",
      "[40, 80, 120].forEach" in module
      and 'stroke: "#26333D", "stroke-width": 1' in module)
check("  the grid under the outline and the reader's own shape over it",
      module.index("[40, 80, 120].forEach")
      < module.index("d: HEAD_PATH,")
      < module.index("g.appendChild(svgEl(\"polygon\""))
check("the four arms are drive up, prism right, anchor down, wave left",
      re.search(r'\{ tag: "drive", dx: 0, dy: -1, arrow: "↑" \}', module)
      and re.search(r'\{ tag: "prism", dx: 1, dy: 0, arrow: "→" \}',
                    module)
      and re.search(r'\{ tag: "anchor", dx: 0, dy: 1, arrow: "↓" \}',
                    module)
      and re.search(r'\{ tag: "wave", dx: -1, dy: 0, arrow: "←" \}',
                    module))
check("  the polygon is teal at a sixth, outlined and dotted at the vertices",
      'fill: "#4EDDC4", "fill-opacity": 0.16' in module
      and 'stroke: "#4EDDC4", "stroke-width": 2, "stroke-linejoin": "round"'
      in module
      and 'r: 3.5, fill: "#4EDDC4"' in module)
check("  and its reach is the axis score, scaled to the outer ring",
      "HEAD_R * (values[row.tag] || 0) / 100" in module)
check("the lean is a dashed arc with one lit bead on it",
      'var LEAN_ARC = "M 150 66 Q 262 6 374 66";' in module
      and '"stroke-dasharray": "3 5"' in module
      and 'stroke: "#3A4750"' in module
      and 'r: 4.5, fill: "#4EDDC4"' in module)
check("  placed by solving the curve rather than measuring the path",
      "function leanPoint(t)" in module
      and "u * u * 150 + 2 * u * t * 262 + t * t * 374" in module)
check("  read off the energy scale by id, so a reordered config still fits",
      'rows[i].id === "energy"' in module)
check("  and labelled at both ends, the reader's own end lit",
      'x: 136, y: 82, "text-anchor": "end", "font-size": 11, fill: "#8A97A0"'
      in module
      and 'x: 388, y: 82, "text-anchor": "start", "font-size": 11, '
          'fill: "#4EDDC4"' in module)
check("the legend is two by two, an arrow and a whole number per axis",
      "grid-template-columns: 1fr 1fr;" in sheet.split(".pr-head-legend")[1]
      and "function headLegend(" in module
      and 'elm("span", "pr-head-arrow", row.arrow)' in module)
check("every colour in the drawing is set on the element, not in the sheet",
      "#7E8C96" not in sheet and "#26333D" not in sheet
      and "#3A4750" not in sheet and "#8A97A0" not in sheet)
check("  which is the same path the PDF cover already takes",
      'style="width: %d%%; background: %s"' in open(
          os.path.join(ROOT, "reports.py"), encoding="utf-8").read())
check("the head is drawn from the block the hero card is built from",
      "function headValues(data)" in module
      and "(data.split || []).forEach" in module
      and "function headBlock(copy, data)" in module)
check("  and is skipped rather than drawn empty when there is no block",
      "if (!data || !(data.split || []).length) return null;" in module)
# Phase 1.6 moved it. It was the last block on the page, under six locked
# cards; it is the top of the profile card now, directly below the name and
# the rarity and above the three scales.
hero_src = module[module.index("function richHero("):
                  module.index("// --- b3) the head")]
check("the head is drawn inside the profile card",
      "var drawing = headBlock(copy || {}, data);" in hero_src
      and "card.appendChild(drawing)" in hero_src)
check("  below the subtype name and the rarity line",
      hero_src.index('elm("h1", "pr-subtype"')
      < hero_src.index('elm("p", "pr-ribbon"')
      < hero_src.index("var drawing = headBlock("))
check("  and above the three scales",
      hero_src.index("var drawing = headBlock(")
      < hero_src.index('elm("div", "pr-scales")'))
check("  and above the axis split, which is still under the scales",
      hero_src.index('elm("div", "pr-scales")')
      < hero_src.index("splitBar(data)"))
# One call site, not two. Both the free page and the delivered page draw this
# card, so a reposition made inside it cannot drift between them — which is
# the whole reason it moved in here rather than being appended twice.
check("both views get it from the one place, so they cannot disagree",
      module.count("headBlock(") == 2
      and "richHero(glyph(ctx.picks.animal), data, copy)" in module
      and "richHero(glyph(pick), data, copy)" in module)
check("  and neither view appends a head of its own any more",
      "root.appendChild(head)" not in module)
check("the stylesheet unwraps it inside the card, so it is a band not a box",
      ".pr-hero .pr-head {" in sheet
      and "border: 0;" in sheet.split(".pr-hero .pr-head {")[1][:220]
      and "background: none;" in sheet.split(".pr-hero .pr-head {")[1][:260])
check("  while the standalone panel rule stays, for a CDN version skew",
      re.search(r"^\.pr-head \{", sheet, re.M) is not None)
check("the config gives it a heading and a line saying what it is",
      cfg["result_copy"]["head_title"] == "Your shape"
      and cfg["result_copy"]["head_caption"].startswith("Four axes"),
      str(cfg["result_copy"].get("head_title")))

print("\n--- the quiz chrome wears the funnel's colours ---")
# Phase 1 declared `"theme": "persona"` and mazzin.css had never heard of it,
# so the class landed and nothing painted it: a dark result page at the end of
# a default-coloured quiz. This is the block that finishes it.
mazzin = open(os.path.join(ROOT, "static/css/mazzin.css"),
              encoding="utf-8").read()
theme_rules = [r.strip() for r in
               re.findall(r"^[^\s@}/][^{}]*(?=\{)", mazzin, re.M)
               if "theme-persona" in r]
check("mazzin.css paints this funnel's theme", len(theme_rules) >= 8,
      str(len(theme_rules)))
check("  every rule of it is scoped to the funnel's own body class",
      all(r.startswith("body.theme-persona") for r in theme_rules),
      str([r for r in theme_rules
           if not r.startswith("body.theme-persona")][:3]))
check("  in the same teal and ink the result page uses",
      "#4EDDC4" in mazzin and "#101820" in mazzin
      and "--pr-teal: #4EDDC4;" in sheet and "--pr-ink: #101820;" in sheet)
check("  covering the pips, the analysing bar and the beat between steps",
      all(sel in mazzin for sel in (
          "body.theme-persona .pip",
          "body.theme-persona .analyzing-bar",
          "body.theme-persona #screen-interstitial.is-active",
          "body.theme-persona .mid-kicker")))
# The progress rule is themed through the tokens the base rules already read,
# not by restating its background. test_zodiac30_check asserts that the
# auto-advance mode carries no styling outside a fixed list of selectors — a
# guard written when zodiac was the only theme — and a second `.mid-accent`
# rule trips it even when scoped to a body class no other funnel wears. The
# tokens do the same job and leave that guard true.
check("  and the progress rule is themed through the accent tokens",
      "body.theme-persona #screen-interstitial {" in mazzin
      and "--accent: #4EDDC4;" in mazzin
      and "--accent-soft: rgba(78, 221, 196, 0.16);" in mazzin)
check("  adding no rule of its own to the auto-advance mode",
      not [r for r in theme_rules
           if "mid-accent" in r or "is-auto" in r],
      str([r for r in theme_rules
           if "mid-accent" in r or "is-auto" in r]))
check("  and repainting the accent no wider than that one screen",
      not re.search(r"^body\.theme-persona \{", mazzin, re.M),
      "the accent must not reach the white quiz cards")
check("the config asks for that theme by name", cfg["theme"] == "persona")
# The neighbours' own theme block is what this must not have disturbed.
zodiac_rules = [r.strip() for r in
                re.findall(r"^[^\s@}/][^{}]*(?=\{)", mazzin, re.M)
                if "theme-zodiac" in r]
check("  and zodiac's block is still there, whole",
      len(zodiac_rules) >= 14
      and "body.theme-zodiac .pip.is-done { background: #E8C878; }" in mazzin,
      str(len(zodiac_rules)))
check("  with no rule serving both themes at once",
      not [r for r in theme_rules if "theme-zodiac" in r]
      and not [r for r in zodiac_rules if "theme-persona" in r])

print("\n--- the instrument actually moves ---")
# The band says the four names are shared out evenly. It says nothing about
# the three scales under them, and a vocabulary that spends one tone word
# everywhere gives every reader the same three dots. Three dots that never
# move are decoration, so they are measured here too.


def _between(a, b):
    return 50.0 if not (a + b) else 100.0 * b / (a + b)


def scale_at(scores):
    def g(t):
        return max(0, scores.get(t, 0))

    between = _between
    return {"tone": between(g("bold"), g("calm")),
            "energy": between(g("outer"), g("inner")),
            "depth": between(g("bold") + g("calm"), g("deep"))}


_rng = random.Random(31337)
_at = {"tone": [], "energy": [], "depth": []}
for _ in range(6000):
    sc = play(lambda st, opts: _rng.choice(opts), _rng)
    for k, v in scale_at(sc).items():
        _at[k].append(v)
for name, vals in sorted(_at.items()):
    mean = sum(vals) / len(vals)
    sd = (sum((v - mean) ** 2 for v in vals) / len(vals)) ** 0.5
    check("  %-6s sits off the rail (20-80) and spreads (sd>=8)" % name,
          20.0 <= mean <= 80.0 and sd >= 8.0,
          "mean %.1f sd %.1f" % (mean, sd))
    lo = sum(1 for v in vals if v < 45) / len(vals)
    check("    and lands on both sides of the middle",
          0.1 <= lo <= 0.9, "%.2f below 45" % lo)

print("\n--- and the neighbours are untouched ---")
# The failure this funnel could cause that no persona assertion would see: a
# frame written into another gallery, or a config edited on the way past.
#
# Discovered rather than listed. A hardcoded roster of neighbours is a check
# that passes for the wrong reason the day somebody adds a funnel — it stops
# looking at the new one and nobody notices — and this file has already been
# through that once, when zodiac-ro landed. Every config on disk that is not
# persona is a neighbour, whatever it is called.
NEIGHBOURS = NEIGHBOUR_SLUGS
check("there are neighbours to check at all", len(NEIGHBOURS) >= 4,
      str(NEIGHBOURS))
check("  and persona is one config among them, not a replacement for one",
      os.path.isfile(os.path.join(ROOT, "funnels/persona.json")))
for slug in NEIGHBOURS:
    other = json.load(open(os.path.join(ROOT, "funnels/%s.json" % slug),
                           encoding="utf-8"))
    check("  %-18s still matches its static copy" % slug,
          other == json.load(open(
              os.path.join(ROOT, "static/funnels/%s.json" % slug),
              encoding="utf-8")))
    check("    and is still its own funnel", other["slug"] == slug,
          other["slug"])
    # By path, not by word: "personal signals" is copy most of these funnels
    # have carried since before persona existed.
    check("    naming none of this funnel's files",
          not re.search(r"(?:galleries|funnels|js|css)/[\w-]*persona",
                        json.dumps(other)))
# `config` is imported by the server section above, which runs first.
check("  and every one of them is still routable, so nothing was displaced",
      all(config.funnel_exists(slug) for slug in NEIGHBOURS),
      str([s for s in NEIGHBOURS if not config.funnel_exists(s)]))
check("every config in funnels/ has a static copy, and no copy is orphaned",
      sorted(os.listdir(os.path.join(ROOT, "static/funnels")))
      == sorted(os.listdir(os.path.join(ROOT, "funnels"))),
      str(sorted(set(os.listdir(os.path.join(ROOT, "static/funnels")))
                 ^ set(os.listdir(os.path.join(ROOT, "funnels"))))))
check("the twins' own result module is not this one",
      json.load(open(os.path.join(ROOT, "funnels/zodiac30.json"),
                     encoding="utf-8"))["result_module"]
      == "/static/js/result_zodiac.js")
# Word-bounded, because `personalised` and `personal signals` are engine.js's
# own and predate this funnel by a year.
OWN = re.compile(r"\bpersona\b|result_persona|galleries/persona")
check("  and result_zodiac.js knows nothing about persona",
      not OWN.search(open(os.path.join(ROOT, "static/js/result_zodiac.js"),
                          encoding="utf-8").read()))
check("engine.js knows nothing about persona either — it is all config",
      not OWN.search(engine), str(OWN.findall(engine)[:3]))
check("  and app.py routes it without naming it",
      not OWN.search(open(os.path.join(ROOT, "app.py"),
                          encoding="utf-8").read())
      and "funnel_exists" in open(os.path.join(ROOT, "app.py"),
                                  encoding="utf-8").read())

print("\n%d checks, %d failed" % (checks[0], len(fails)))
for f in fails:
    print("  FAIL " + f)
sys.exit(1 if fails else 0)
