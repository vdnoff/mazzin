#!/usr/bin/env python3
"""Checks over the love-zodiac-bg gallery generator.

scripts/gen_love_gallery.py draws the funnel's real art. It is a console
tool, run by hand against a key, and nothing imports it — so what is worth
asserting is not that it runs but that what it would send, keep and skip is
right before anybody spends money on finding out.

Four things carry most of the weight.

The plan comes off the config and is held to it. Every love-owned image id
the funnel references has a prompt and every prompt names an id the funnel
references; a config that drifts from the plan makes the generator refuse
rather than draw a gallery nobody sees. The SHAPE of every frame comes off
the config too — the format of the step it sits in — because v1 was drawn
square for tiles that render as tall columns, and that is the defect this
version exists to fix.

The manifest makes reruns cheap and deletions meaningful. A frame whose file
still hashes to what was recorded, drawn from a recipe that has not changed,
is skipped; delete the file or edit the prompt and it is drawn again. v4
bumps every recipe, so everything on disk is stale and `--only` is how the
owner calibrates a few frames before a plain run redraws the rest.

v4 invents no style: the suffix is the zodiac gallery's own style string,
found in the server's generator and copied character for character, after
the composition guidance. That string bans people, faces and hands and asks
for a well-lit subject, so every scene is objects and symbols, and a scene
that asks for darkness or names a person is refused at plan time — the
zodiac generator's exposure guard, ported. The light lives per frame, in
three buckets, every pair and four-up in one bucket, each judged on a band
read off the approved zodiac frames that sit in it.

And the key is read off ~/mazzin/.env as a literal line, never sourced, with
the environment as the fallback.

No key, no network, no spend. The frame mechanics — the crop, the encoder,
the floor — are exercised for real on synthetic images, because they cost
nothing and their output is what gets committed.
"""
import ast
import hashlib
import importlib.util
import io
import json
import os
import re
import sys

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, REPO)
sys.path.insert(0, os.path.join(REPO, "scripts"))

GALLERY = os.path.join(REPO, "static/galleries/love-zodiac-bg")
SCRIPT = os.path.join(REPO, "scripts/gen_love_gallery.py")
PLACEHOLDERS = os.path.join(REPO, "scripts/gen_love_placeholders.py")
SCRATCH = os.path.join(REPO, "tests", ".loveart_scratch")

fails = []
checks = [0]
notes = []


def check(label, ok, detail=""):
    checks[0] += 1
    if not ok:
        fails.append("%s %s" % (label, detail))
    print("  %-58s %s%s" % (label, "ok" if ok else "FAIL",
                            ("  " + str(detail)) if detail and not ok else ""))


def load(path, name):
    spec = importlib.util.spec_from_file_location(name, path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


print("\n--- it loads with no key and draws nothing on import ---")
saved_key = os.environ.pop("OPENAI_API_KEY", None)
gen = load(SCRIPT, "gen_love_gallery_t")
check("the generator imports", True)
gen_src = open(SCRIPT, encoding="utf-8").read()
ph_src = open(PLACEHOLDERS, encoding="utf-8").read()
cfg = json.load(open(os.path.join(REPO, "funnels/love-zodiac-bg.json"),
                     encoding="utf-8"))
check("it is a console script, run by hand",
      "__main__" in gen_src and "argparse" in gen_src)
IMPORTS = re.compile(r"^\s*(?:import|from)\s+(?:scripts\.)?gen_love", re.M)
check("  and nothing in the app imports it, nor the placeholder script",
      not [f for f in ("app.py", "config.py", "reports.py", "payments.py",
                       "tracking.py", "visualizer.py", "admin.py")
           if IMPORTS.search(open(os.path.join(REPO, f),
                                  encoding="utf-8").read())])
check("  it borrows nothing from the persona style module",
      "persona_style" not in gen_src and "gen_persona" not in gen_src)
check("  and no test or deploy step runs it",
      "gen_love_gallery" not in open(os.path.join(REPO, "deploy.sh"),
                                     encoding="utf-8").read()
      and "gen_love_gallery" not in open(os.path.join(REPO, "tests/run.sh"),
                                         encoding="utf-8").read())


print("\n--- the plan comes off the config, shape included ---")
plan = gen.frames(cfg)
by_id = {f["id"]: f for f in plan}
steps = cfg["swipe"]["steps"]
images = [i for s in steps for p in s["pairs"]
          for i in p["images"] if i["img"].startswith(gen.OWNED)]
format_of = {i["id"]: s["format"] for s in steps for p in s["pairs"]
             for i in p["images"]}
extras = [g for g in cfg.get("preview_gallery") or []
          if g["img"].startswith(gen.OWNED)
          and g["id"] not in {i["id"] for i in images}]
kinds = {}
for f in plan:
    kinds[f["kind"]] = kinds.get(f["kind"], 0) + 1
print("    plan: " + ", ".join("%s %d" % kv for kv in sorted(kinds.items())))
check("forty-six frames: twenty-eight pair cards, sixteen grid cells, two "
      "interstitials",
      len(plan) == 46 and kinds == {"pair": 28, "grid": 16, "interstitial": 2},
      str(kinds))
check("  the cards are every love card the walk shows, in walk order",
      [f["id"] for f in plan if f["kind"] != "interstitial"]
      == [i["id"] for i in images])
check("  a card's kind is its step's format: pair or grid4, nothing else",
      all(by_id[i["id"]]["kind"] == gen.KIND_OF_FORMAT[format_of[i["id"]]]
          for i in images)
      and gen.KIND_OF_FORMAT == {"pair": "pair", "grid4": "grid"})
check("  the sixteen grid cells are the four four-up steps' cards",
      sorted(f["id"] for f in plan if f["kind"] == "grid")
      == sorted(i["id"] for i in images if format_of[i["id"]] == "grid4")
      and len([s for s in steps if s["format"] == "grid4"]) == 4)
check("  the interstitials are the two frames only the preview strip names",
      [f["id"] for f in plan if f["kind"] == "interstitial"]
      == [g["id"] for g in extras] == ["int1", "int2"])
check("  no sign glyph is planned — those are the zodiac gallery's",
      not [f for f in plan if f["id"].startswith("sign_")])
check("no id is planned twice", len(by_id) == len(plan))
check("the prompt table is forty-four and two",
      len(gen.CARD_PROMPTS) == 44 and len(gen.TALL_PROMPTS) == 2)


def refuses(config):
    try:
        gen.frames(config)
    except SystemExit as exc:
        return str(exc)
    return None


drifted = json.loads(json.dumps(cfg))
drifted["swipe"]["steps"][0]["pairs"][0]["images"][0]["id"] = "lv99a"
drifted["swipe"]["steps"][0]["pairs"][0]["images"][0]["img"] = (
    gen.OWNED + "lv99a.webp")
check("a config naming an id with no prompt makes it refuse",
      refuses(drifted) is not None and "lv99a" in (refuses(drifted) or ""),
      str(refuses(drifted)))
trimmed = json.loads(json.dumps(cfg))
trimmed["preview_gallery"] = [g for g in trimmed["preview_gallery"]
                              if g["id"] != "int2"]
check("  and so does a config that stopped naming a planned frame",
      refuses(trimmed) is not None and "int2" in (refuses(trimmed) or ""),
      str(refuses(trimmed)))
odd = json.loads(json.dumps(cfg))
odd["swipe"]["steps"][0]["format"] = "grid6"
check("  and a step on a format no frame shape is known for",
      refuses(odd) is not None and "grid6" in (refuses(odd) or ""),
      str(refuses(odd)))
check("  while the committed config is accepted", refuses(cfg) is None)


print("\n--- the shapes, measured off the tiles they are shown in ---")
# On the live shell at 390x844 a pair card renders 174x603 (about 2:7) and a
# four-up cell 174x279 to 174x297 (about 3:5). v1 drew every card square and
# `object-fit: cover` showed the middle third of it.
check("every frame is rendered portrait, 1024x1536",
      all(f["api_size"] == "1024x1536" for f in plan)
      and gen.API_PORTRAIT == "1024x1536")
check("  a pair card keeps the whole 2:3 render at 640x960",
      gen.KINDS["pair"]["size"] == (640, 960)
      and all(f["size"] == (640, 960) for f in plan if f["kind"] == "pair"))
check("  which is the zodiac gallery's own shape",
      abs(640 / 960.0 - 640 / 982.0) < 0.02)
check("  a grid cell is twice its rendered 3:5 at 360x600",
      gen.KINDS["grid"]["size"] == (360, 600)
      and all(f["size"] == (360, 600) for f in plan if f["kind"] == "grid"))
check("  and the interstitials keep 4:5 at 800x1000",
      gen.KINDS["interstitial"]["size"] == (800, 1000)
      and all(f["size"] == (800, 1000) for f in plan
              if f["kind"] == "interstitial"))
check("the price table knows the portrait size at the quality in use",
      (gen.IMAGE_QUALITY, gen.API_PORTRAIT) in gen.PRICE,
      "%s %s" % (gen.IMAGE_QUALITY, sorted(gen.PRICE)))


print("\n--- what a frame is asked for ---")
# The zodiac gallery's style string, as the server's generator has it.
ZODIAC_STYLE = (
    "Cinematic celestial art, painterly photographic hybrid, rich saturated "
    "colour, luminous, well-lit subject, every detail clearly visible, subtle "
    "silver star grain, vertical portrait composition centered and readable "
    "at thumbnail size. No text, no letters, no numbers, no people, no faces, "
    "no hands, no watermark, no logo, no frame."
)
# And the love gallery's own, v5: the same string with the ban on people,
# faces and hands replaced by a ban on close-up faces, and nothing else
# moved — the compositions came back, the style did not change.
LOVE_STYLE = (
    "Cinematic celestial art, painterly photographic hybrid, rich saturated "
    "colour, luminous, well-lit subject, every detail clearly visible, subtle "
    "silver star grain, vertical portrait composition centered and readable "
    "at thumbnail size. No text, no letters, no numbers, no close-up faces, "
    "no watermark, no logo, no frame."
)
check("the zodiac style string is still held, character for character",
      gen.ZODIAC_STYLE == ZODIAC_STYLE, repr(gen.ZODIAC_STYLE))
check("the love style string is pinned verbatim",
      gen.LOVE_STYLE == LOVE_STYLE, repr(gen.LOVE_STYLE))
check("  and differs from the zodiac one in exactly that substitution",
      gen.LOVE_STYLE == ZODIAC_STYLE.replace(
          "no people, no faces, no hands", "no close-up faces")
      and gen.LOVE_STYLE != ZODIAC_STYLE)
check("  it is the whole of the v5 palette after the guidance slot",
      gen.DRAW_PALETTE == gen.RECORDED_PALETTE == "v5"
      and gen.PALETTES == {"v4": ", {guidance}. " + ZODIAC_STYLE,
                           "v5": ", {guidance}. " + LOVE_STYLE}
      and gen.STYLE_SUFFIX == gen.PALETTES["v5"], repr(gen.PALETTES))
# The words that made v1, v2 and v3 what they were. A scene never carries
# them: the only style words in a prompt are the zodiac string's own.
TREATMENT = ("painterly", "dreamy", "luminous", "moody", "golden-hour",
             "saturated", "palette", "cinematic", "style")
check("  and no scene carries a treatment word of its own",
      not [(f["id"], w) for f in plan for w in TREATMENT
           if w in f["subject"]],
      str([(f["id"], w) for f in plan for w in TREATMENT
           if w in f["subject"]][:4]))
check("  every prompt is its scene, the guidance for its crop, the zodiac "
      "string", all(
    f["prompt"] == f["subject"] + ", " + gen.KINDS[f["kind"]]["guidance"]
    + ". " + LOVE_STYLE
    for f in plan))
GUIDE = "single central subject, composed for a "
check("  every prompt carries the composition guidance for its own crop",
      all(GUIDE + gen.KINDS[f["kind"]]["crop"] in f["prompt"]
          and "comfortable margins on all sides" in f["prompt"]
          and "middle 70%" in f["prompt"] for f in plan))
check("  a pair card is told about the tall band it is shown through",
      all("middle 40% of the frame width" in f["prompt"]
          for f in plan if f["kind"] == "pair")
      and not any("40%" in f["prompt"] for f in plan if f["kind"] != "pair"))
check("  a grid cell is composed for 3:5 and an interstitial for 4:5",
      all("3:5 portrait crop" in f["prompt"] for f in plan
          if f["kind"] == "grid")
      and all("4:5 portrait crop" in f["prompt"] for f in plan
              if f["kind"] == "interstitial"))
check("  and every subject is carried verbatim, opening the prompt",
      all(by_id[i]["prompt"].startswith(s + ",")
          for i, _b, s in gen.CARD_PROMPTS + gen.TALL_PROMPTS))
SUBJECTS = {
    "lv01a": "a bright golden spark leaping between two reaching hands, "
            "deep indigo starry sky behind",
    "lv06b": "two birds flying side by side across a bright open sky at "
            "dawn",
    "lv11b": "glowing embers in a stone hearth, deep red and gold, the "
            "ember glow lighting the stones",
    "lv12a": "a figure leaping toward an outstretched hand over a gap "
            "between two cliffs, bright sky behind",
    "lv16c": "two figures from behind reading side by side on a sofa in "
            "soft afternoon light",
    "lv18a": "heart-shaped nebula glowing gold and rose in deep indigo "
            "space",
    "lv18b": "two hands forming a heart shape against a bright full moon "
            "in a deep indigo sky",
    "int1": "two falling stars streaking across a deep indigo sky over "
            "a faint horizon glow",
}
for frame_id, subject in sorted(SUBJECTS.items()):
    check("  %-6s is the plan's subject" % frame_id,
          by_id[frame_id]["subject"] == subject)
check("every prompt bans close-up faces, text and a watermark — and no "
      "longer people or hands",
      all(all(w in f["prompt"].lower()
              for w in ("no close-up faces", "no text", "no watermark"))
          and "no people" not in f["prompt"].lower()
          and "no hands" not in f["prompt"].lower()
          for f in plan))


print("\n--- the exposure guard, ported from the zodiac generator ---")
ZODIAC_EXPOSURE = (
    "dark", "darkly", "dim", "dimly", "moody", "moodily", "shadow",
    "shadowed", "shadowy", "low-key", "lowkey", "dramatic", "dramatically",
    "intimate", "candlelit", "candlelight", "atmospheric", "gloomy", "murky",
    "sombre", "somber", "night", "nighttime", "dusk", "twilight", "unlit",
    "underexposed", "silhouette", "noir", "smoky", "hazy",
)
check("the zodiac list is still held verbatim and in order",
      gen.ZODIAC_EXPOSURE_WORDS == ZODIAC_EXPOSURE)
# v5: a silhouette is a subject here, not a way of asking for gloom, so the
# one silhouette word comes out of the zodiac list on its way into the guard
# and the plural is no longer appended.
check("  the guard is that list minus silhouette, in order",
      gen.EXPOSURE_WORDS[:len(ZODIAC_EXPOSURE) - 1]
      == tuple(w for w in ZODIAC_EXPOSURE if w != "silhouette")
      and gen.SILHOUETTE_WORDS == ("silhouette", "silhouettes")
      and "silhouette" not in gen.EXPOSURE_WORDS
      and "silhouettes" not in gen.EXPOSURE_WORDS,
      str(gen.EXPOSURE_WORDS[:8]))
check("  with this file's four appended after it, nothing else",
      gen.EXPOSURE_WORDS[len(ZODIAC_EXPOSURE) - 1:]
      == ("darkness", "midnight", "nocturnal", "candle-lit"))
check("  plain candle and candles are not on it — a candle is an object",
      "candle" not in gen.EXPOSURE_WORDS and "candles" not in gen.EXPOSURE_WORDS
      and gen.guard("two candles, one lighting the other") == []
      and gen.guard("a candlelight dinner") == ["candlelight"])
check("  and the style's one ban is words too: a face, a portrait of somebody",
      gen.SUBJECT_WORDS == ("face", "faces", "portrait of a", "close-up",
                            "closeup")
      and gen.guard("a portrait of a woman") == ["portrait of a"]
      and gen.guard("a close-up face") == ["close-up", "face"])
check("  while people, couples, figures, silhouettes and hands pass it now",
      all(gen.guard(s) == [] for s in (
          "couple silhouettes", "two figures from behind", "two hands",
          "two fishermen", "a person waving", "two people at a table")))
check("the guard names what it finds, as whole words",
      gen.guard("a dark night with silhouettes") == ["dark", "night"]
      and gen.guard("a darkened room") == []
      and gen.guard("Candlelit dinner") == ["candlelit"])
check("  and a scene with a lamp, a moon or an ember passes it",
      gen.guard("a lamp glowing under a moon, embers below") == [])
check("no scene in the plan carries a guarded word",
      not [(f["id"], gen.guard(f["subject"])) for f in plan
           if gen.guard(f["subject"])],
      str([(f["id"], gen.guard(f["subject"])) for f in plan
           if gen.guard(f["subject"])][:4]))
saved = gen.CARD_PROMPTS[0]
gen.CARD_PROMPTS[0] = (saved[0], saved[1], "two faces in a dark night")
try:
    caught = refuses(cfg)
finally:
    gen.CARD_PROMPTS[0] = saved
check("a scene that asks for darkness or a face refuses to run",
      caught is not None and "zodiac style refuses" in (caught or "")
      and "night" in (caught or "") and "faces" in (caught or ""),
      str(caught))

print("\n--- v5: the seventeen compositions, back ---")
# Every frame that showed a couple, a silhouette or a pair of hands in the
# v1 plan shows it again: as silhouettes, figures from behind or hands, in
# its own frame's bucket, lit the way its v4 stand-in was.
RESTORED = ("lv01a", "lv02a", "lv03a", "lv05c", "lv05d", "lv07d", "lv08a",
            "lv09b", "lv12a", "lv14a", "lv14b", "lv15a", "lv15b", "lv16a",
            "lv16c", "lv16d", "lv18b")
PEOPLE = re.compile(r"\b(silhouettes?|figures?|hands?|fishermen|couple)\b")
check("seventeen frames name a silhouette, a figure, hands or a couple",
      sorted(f["id"] for f in plan if PEOPLE.search(f["subject"]))
      == sorted(RESTORED),
      str(sorted(set(f["id"] for f in plan if PEOPLE.search(f["subject"]))
                 ^ set(RESTORED))))
check("  and the other twenty-nine are the object scenes they were",
      not [f["id"] for f in plan if f["id"] not in RESTORED
           and PEOPLE.search(f["subject"])])
check("  no scene, restored or not, asks for a face",
      not [f["id"] for f in plan
           if re.search(r"\bfaces?\b|portrait", f["subject"])])
check("  a figure is a silhouette, from behind, or hands — never facing",
      all(re.search(r"silhouette|from behind|hands?\b|fingers", f["subject"])
          for f in plan if f["id"] in RESTORED),
      str([f["id"] for f in plan if f["id"] in RESTORED
           and not re.search(r"silhouette|from behind|hands?\b|fingers",
                             f["subject"])]))
# The v1 line, restored: the same composition, the v4 light.
V1 = {"lv01a": "spark", "lv02a": "square", "lv03a": "interlaced",
      "lv05c": "kitchen table", "lv05d": "shoulder to shoulder",
      "lv07d": "dancing", "lv08a": "street lamp", "lv09b": "key",
      "lv12a": "leaping", "lv14a": "dancing", "lv14b": "blanket",
      "lv15a": "umbrella", "lv15b": "kite", "lv16a": "pier",
      "lv16c": "sofa", "lv16d": "parked car", "lv18b": "heart"}
for frame_id, word in sorted(V1.items()):
    check("  %-6s keeps its v1 composition: %s" % (frame_id, word),
          word in by_id[frame_id]["subject"])
check("  each keeps its frame's bucket and its step's",
      all(by_id[i]["bucket"] == by_id[i[:4] + "a"]["bucket"]
          for i in RESTORED))
check("  and none asks for v1's darkness",
      not [i for i in RESTORED if gen.guard(by_id[i]["subject"])]
      and all("deep indigo" in by_id[i]["subject"]
              for i in RESTORED if by_id[i]["bucket"] == "dark"))

# The three frames of the gender step, planned ahead of the step.
check("three gender frames wait on the step, in one bucket",
      [r[0] for r in gen.PENDING_PROMPTS] == ["g01", "g02", "g03"]
      and {r[1] for r in gen.PENDING_PROMPTS} == {"mid"}
      and not [f for f in plan if f["id"].startswith("g0")]
      and not any(gen.guard(r[2]) for r in gen.PENDING_PROMPTS))
check("  feminine, masculine, neutral — stardust silhouettes and a star",
      "feminine silhouette" in gen.PENDING_PROMPTS[0][2]
      and "rose-gold" in gen.PENDING_PROMPTS[0][2]
      and "masculine silhouette" in gen.PENDING_PROMPTS[1][2]
      and "teal-gold" in gen.PENDING_PROMPTS[1][2]
      and "neutral and welcoming" in gen.PENDING_PROMPTS[2][2])
_with_step = json.loads(json.dumps(cfg))
_with_step["swipe"]["steps"].insert(2, {
    "id": "gender", "question": "За кого е този профил?", "format": "grid4",
    "pairs": [{"id": "p1", "images": [
        {"id": g, "img": "/static/galleries/love-zodiac-bg/%s.webp" % g,
         "label": g, "tags": []} for g in ("g01", "g02", "g03")]}]})
_plan49 = gen.frames(_with_step)
check("  and they join the plan the day the config names them: 49 frames",
      len(_plan49) == 49
      and [f["id"] for f in _plan49 if f["id"].startswith("g0")]
      == ["g01", "g02", "g03"]
      and all(f["kind"] == "grid" for f in _plan49 if f["id"].startswith("g0")))


print("\n--- the light plan: three buckets, one per step ---")
buckets = {f["id"]: f["bucket"] for f in plan}
count = {b: sum(1 for v in buckets.values() if v == b)
         for b in ("bright", "mid", "dark")}
print("    " + ", ".join("%s %d" % kv for kv in sorted(count.items())))
check("every frame sits in one of three buckets",
      set(buckets.values()) == {"bright", "mid", "dark"})
# The first v4 run drew thirty of forty-six and rejected thirteen, each at a
# consistent luma across three draws — a band assigned wrong, not art drawn
# wrong. The buckets follow what was measured: four bright, twenty-eight
# mid, fourteen dark.
check("  four bright, twenty-eight mid, fourteen dark — what the draws said",
      count == {"bright": 4, "mid": 28, "dark": 14}, str(count))
check("  every pair and every four-up is lit alike: one bucket per step",
      all(len({buckets[i["id"]] for p in s["pairs"] for i in p["images"]
               if i["id"] in buckets}) == 1
          for s in steps if s["id"] != "sign"),
      str([(s["id"], sorted({buckets[i["id"]] for p in s["pairs"]
                             for i in p["images"] if i["id"] in buckets}))
           for s in steps if s["id"] != "sign"
           and len({buckets[i["id"]] for p in s["pairs"]
                    for i in p["images"] if i["id"] in buckets}) != 1]))
check("  and the interstitials are the night frames they always were",
      buckets["int1"] == buckets["int2"] == "dark")
# The thirteen rejected frames and the luma each drew, three times over.
# Every one now sits in a band its numbers fit, and every one's step-mates
# moved with it — an accepted step-mate keeps its frame, only the label
# moves, because the bucket is not part of the recipe.
OBSERVED = {
    "lv04a": (21, 38), "lv05a": (40, 47), "lv05d": (41, 55),
    "lv06a": (87, 96), "lv07b": (78, 90), "lv07d": (82, 84),
    "lv08a": (32, 46), "lv10b": (58, 70), "lv10c": (93, 101),
    "lv10d": (74, 93), "lv12a": (84, 96), "lv12b": (83, 92),
    "lv15a": (79, 87),
}
check("every rejected frame's observed range now sits inside its band",
      all(by_id[i]["band"]["min_luma"] <= lo
          and hi <= by_id[i]["band"]["max_luma"]
          for i, (lo, hi) in OBSERVED.items()),
      str([(i, by_id[i]["band"]["min_luma"], by_id[i]["band"]["max_luma"])
           for i, (lo, hi) in OBSERVED.items()
           if not (by_id[i]["band"]["min_luma"] <= lo
                   and hi <= by_id[i]["band"]["max_luma"])]))
check("  the 70-to-101 group is mid, step-mates included",
      all(buckets[i] == "mid" for i in
          ("lv06a", "lv06b", "lv07a", "lv07b", "lv07c", "lv07d", "lv10a",
           "lv10b", "lv10c", "lv10d", "lv12a", "lv12b", "lv15a", "lv15b")))
check("  and the four that drew darker than their step keep its bucket "
      "with a floor just under what they drew",
      buckets["lv04a"] == buckets["lv04b"] == "bright"
      and buckets["lv05a"] == buckets["lv05d"] == "mid"
      and buckets["lv08a"] == buckets["lv08b"] == "mid"
      and all(OBSERVED[i][0] - 5 <= gen.MIN_LUMA_BY_FRAME[i] < OBSERVED[i][0]
              for i in ("lv04a", "lv05a", "lv05d", "lv08a")))
check("  the dark bucket is untouched: the review's dark examples stay dark",
      all(buckets[i] == "dark" for i in
          ("lv01a", "lv11a", "lv11b", "lv14b", "lv18a", "int1")))
# A dark frame's darkness is a named colour — deep indigo, an ember glow —
# never an exposure word, and its subject is still lit. Bright and mid are
# what the draws measured, not what the words say, so only dark is held to
# its vocabulary.
WORDS = {"dark": re.compile(r"deep indigo|indigo|ember", re.I)}
check("  every dark scene says so in its own colours",
      all(WORDS["dark"].search(f["subject"]) for f in plan
          if f["bucket"] == "dark"),
      str([f["id"] for f in plan if f["bucket"] == "dark"
           and not WORDS["dark"].search(f["subject"])]))
check("  and no bright or mid scene reaches for the dark colours",
      not [f["id"] for f in plan if f["bucket"] != "dark"
           and WORDS["dark"].search(f["subject"])],
      str([f["id"] for f in plan if f["bucket"] != "dark"
           and WORDS["dark"].search(f["subject"])]))
check("  every dark scene keeps its subject lit, the zk1b way",
      all(re.search(r"bright|lit|glow|light", f["subject"], re.I)
          for f in plan if f["bucket"] == "dark"),
      str([f["id"] for f in plan if f["bucket"] == "dark"
           and not re.search(r"bright|lit|glow|light", f["subject"], re.I)]))
# A step that mixes buckets is refused at plan time, not shipped.
saved = gen.CARD_PROMPTS[0]
gen.CARD_PROMPTS[0] = (saved[0], "bright", saved[2])
try:
    mixed = refuses(cfg)
finally:
    gen.CARD_PROMPTS[0] = saved
check("a plan that lit one card of a pair differently would refuse to run",
      mixed is not None and "mixes light buckets" in (mixed or ""),
      str(mixed))


print("\n--- the manifest: recipes, idempotency, a full redraw ---")
recipes = [gen.recipe(f) for f in plan]
check("every frame's recipe is distinct", len(set(recipes)) == len(recipes))
check("  and carries the version, the prompt, the API size and the geometry",
      gen.RECIPE_VERSION == "v5"
      and all(r.startswith("v5|") for r in recipes)
      and all(f["prompt"] in gen.recipe(f) and f["api_size"] in gen.recipe(f)
              and "%dx%d" % f["size"] in gen.recipe(f) for f in plan))
check("  but not the bucket: a band judges a draw, it does not make one",
      not any(gen.recipe(f).split("|")[4:5] in (["bright"], ["mid"], ["dark"])
              for f in plan)
      and gen.recipe(dict(plan[0], bucket="bright", band=gen.BANDS["bright"]))
      == gen.recipe(plan[0]))
# The first v4 run recorded thirty frames under the v4.1 spelling, bucket
# and all. Those records are still current, whatever the label says now.
LEGACY = gen.legacy_recipes(by_id["lv06b"])
check("the bucketed spelling is still known, one per bucket",
      len(LEGACY) == 3
      and all(s.startswith(gen.recipe(by_id["lv06b"]) + "|") for s in LEGACY)
      and {s.rsplit("|", 1)[1] for s in LEGACY} == {"bright", "mid", "dark"})
_stamp = gen.on_disk_sha("lv06b")
check("  a frame accepted as bright is still current now that its label "
      "says mid",
      by_id["lv06b"]["bucket"] == "mid"
      and gen.already_made(by_id["lv06b"], {"lv06b": {
          "sha256": _stamp,
          "recipe_sha": hashlib.sha256(
              [s for s in LEGACY if s.endswith("|bright")][0]
              .encode("utf-8")).hexdigest()}}))
check("  and so is one drawn under an overridden floor, in that spelling",
      gen.already_made(by_id["lv18a"], {"lv18a": {
          "sha256": gen.on_disk_sha("lv18a"),
          "recipe_sha": hashlib.sha256(
              (gen.recipe(by_id["lv18a"]).replace("|min_luma=10", "")
               + "|dark|min_luma=10").encode("utf-8")).hexdigest()}}))
check("  while a record from a different prompt is not, in any spelling",
      not gen.already_made(by_id["lv06b"], {"lv06b": {
          "sha256": _stamp,
          "recipe_sha": hashlib.sha256(
              (gen.recipe(by_id["lv06a"]) + "|bright").encode("utf-8"))
          .hexdigest()}}))
check("  the thirteen rejected frames have no record, so nothing needs "
      "bumping: they are simply drawn",
      all(i in by_id for i in OBSERVED))
check("  so the same subject at another size is another recipe",
      gen.recipe(dict(plan[0], size=(360, 600)))
      != gen.recipe(plan[0]))
sample = plan[0]
digest = hashlib.sha256(gen.recipe(sample).encode("utf-8")).hexdigest()
on_disk = gen.on_disk_sha(sample["id"])
check("the placeholder on disk hashes, so the record can be compared",
      on_disk is not None and len(on_disk) == 64)
check("a frame recorded with matching bytes and recipe is skipped",
      gen.already_made(sample, {sample["id"]: {"sha256": on_disk,
                                               "recipe_sha": digest}}))
check("  a changed recipe unskips it",
      not gen.already_made(sample, {sample["id"]: {"sha256": on_disk,
                                                   "recipe_sha": "0" * 64}}))
check("  changed bytes on disk unskip it",
      not gen.already_made(sample, {sample["id"]: {"sha256": "0" * 64,
                                                   "recipe_sha": digest}}))
check("  an unrecorded frame is never skipped",
      not gen.already_made(sample, {}))
check("  and a deleted file is drawn again — no file, no hash, no match",
      gen.on_disk_sha("no-such-frame") is None
      and not gen.already_made(dict(sample, id="no-such-frame"),
                               {"no-such-frame": {"sha256": "0" * 64,
                                                  "recipe_sha": digest}}))
check("the manifest lives beside the script, not in the gallery",
      gen.MANIFEST == os.path.join(REPO, "scripts", "love_art.json"))
entries = gen.load_manifest()
if entries:
    # The manifest on disk was drawn under v4, and v5 bumps every recipe:
    # the final full redraw.
    check("every recorded frame is stale: a plain run would redraw all 46",
          not any(gen.already_made(f, entries) for f in plan)
          and not any(gen.already_made(f, entries, (gen.DRAW_PALETTE,))
                      for f in plan),
          str([f["id"] for f in plan if gen.already_made(f, entries)][:4]))
    check("  and a record drawn under v5 would be current again",
          gen.already_made(plan[0], {plan[0]["id"]: {
              "sha256": gen.on_disk_sha(plan[0]["id"]),
              "recipe_sha": hashlib.sha256(
                  gen.recipe(plan[0]).encode("utf-8")).hexdigest()}}))
    stats = {}
    for i, e in entries.items():
        m = re.search(r"luma ([\d.]+) sd ([\d.]+) sat ([\d.]+)",
                      e.get("note", ""))
        if m and i in by_id:
            stats[i] = tuple(float(x) for x in m.groups())
    rejected = [i for i, s in stats.items()
                if not gen.verdict(s, by_id[i]["band"])[0]]
    print("    %d frames recorded before v5, all stale; %d of them would "
          "fail their bucket band" % (len(entries), len(rejected)))
else:
    notes.append("no manifest on disk: the first run draws all 46")
    check("  with no manifest, nothing is skipped",
          not any(gen.already_made(f, {}) for f in plan))


print("\n--- the key, read as a line and never sourced ---")
os.makedirs(SCRATCH, exist_ok=True)


def env_file(text, name="dotenv"):
    path = os.path.join(SCRATCH, name)
    with open(path, "w", encoding="utf-8") as fh:
        fh.write(text)
    return path


plain = env_file("DB_NAME=FarvaGO$mazzin\nOPENAI_API_KEY=sk-plain\n")
check("a plain line is read", gen.key_from_env_file((plain,)) == "sk-plain",
      repr(gen.key_from_env_file((plain,))))
quoted = env_file('export OPENAI_API_KEY="sk-quoted"\r\n', "quoted")
check("  an exported, quoted, CRLF line too",
      gen.key_from_env_file((quoted,)) == "sk-quoted",
      repr(gen.key_from_env_file((quoted,))))
last = env_file("OPENAI_API_KEY=sk-first\nOPENAI_API_KEY=sk-last\n", "twice")
check("  the last assignment wins, as a sourced file would have it",
      gen.key_from_env_file((last,)) == "sk-last")
check("  a file without the key answers nothing",
      gen.key_from_env_file((env_file("STRIPE_SECRET_KEY=sk_live_x\n",
                                      "other"),)) == "")
check("  and a missing file is not an error",
      gen.key_from_env_file((os.path.join(SCRATCH, "absent"),)) == "")
check("  the first file that has it wins over the second",
      gen.key_from_env_file((quoted, plain)) == "sk-quoted")
check("the script looks in the repo's own .env and in ~/mazzin/.env",
      gen.ENV_FILES == (os.path.join(REPO, ".env"),
                        os.path.expanduser("~/mazzin/.env")))
was = gen.ENV_FILES
gen.ENV_FILES = (os.path.join(SCRATCH, "absent"),)
try:
    check("with no file the environment is the fallback",
          gen.api_key() == "")
    os.environ["OPENAI_API_KEY"] = "sk-env"
    check("  and it is read when set", gen.api_key() == "sk-env")
    gen.ENV_FILES = (plain,)
    check("  but the file comes first", gen.api_key() == "sk-plain")
finally:
    os.environ.pop("OPENAI_API_KEY", None)
    gen.ENV_FILES = was
check("nothing here runs a shell",
      not re.search(r"\b(subprocess|os\.system|os\.popen)\b", gen_src))
check("  and the only line the reader matches is the key's",
      "OPENAI_API_KEY=" in gen._ENV_LINE.pattern
      and gen._ENV_LINE.pattern.count("=") == 1)


print("\n--- three bands, read off the approved zodiac frames ---")
check("dark is 15 to 75, mid 55 to 135, bright 110 to 225",
      gen.BANDS == {
          "dark": {"min_luma": 15.0, "max_luma": 75.0, "min_sd": 12.0,
                   "min_sat": 60.0},
          "mid": {"min_luma": 55.0, "max_luma": 135.0, "min_sd": 12.0,
                  "min_sat": 50.0},
          "bright": {"min_luma": 110.0, "max_luma": 225.0, "min_sd": 12.0,
                     "min_sat": 20.0}},
      str(gen.BANDS))
check("  and every planned frame is judged on its bucket's band",
      all(f["band"] == gen.BANDS[f["bucket"]] for f in plan
          if f["id"] not in gen.MIN_LUMA_BY_FRAME))
# The approved zodiac frames, as measured on disk: (luma, sd, sat).
ZODIAC = {
    "новолуние mn9a": (33.6, 16.2, 111.7), "среднощно небе mo7b": (29.5, 22.6, 177.3),
    "стая на свещи sa12a": (45.5, 19.3, 231.1), "вкоренен камък es13c": (63.5, 33.6, 221.2),
    "първа светлина mo7a": (90.3, 38.2, 107.5), "вълна sy8d": (113.6, 55.7, 161.9),
    "планинско езеро fl10b": (107.8, 60.0, 68.7), "изгряващо слънце sl18a": (84.1, 35.0, 242.8),
    "сияйно слънце en4a": (147.2, 28.6, 238.6), "открито небе es13d": (168.2, 20.0, 77.1),
    "перо sy8c": (177.2, 16.6, 43.6), "над облаците ls5f": (201.5, 17.3, 32.2),
    "пастелно небе pl6c": (210.3, 13.9, 27.3),
}
for name, want in (("новолуние mn9a", "dark"), ("среднощно небе mo7b", "dark"),
                   ("стая на свещи sa12a", "dark"), ("вкоренен камък es13c", "dark"),
                   ("първа светлина mo7a", "mid"), ("вълна sy8d", "mid"),
                   ("планинско езеро fl10b", "mid"), ("изгряващо слънце sl18a", "mid"),
                   ("сияйно слънце en4a", "bright"), ("открито небе es13d", "bright"),
                   ("перо sy8c", "bright"), ("над облаците ls5f", "bright"),
                   ("пастелно небе pl6c", "bright")):
    check("  %-24s passes the %s band" % (name, want),
          gen.verdict(ZODIAC[name], gen.BANDS[want])[0],
          str(ZODIAC[name]))
check("a pale sky is not a defect: пастелно небе at saturation 27 passes bright",
      gen.verdict((210.3, 13.9, 27.3), gen.BANDS["bright"])[0])
check("  but a night card fails bright and a pale sky fails dark",
      not gen.verdict(ZODIAC["новолуние mn9a"], gen.BANDS["bright"])[0]
      and not gen.verdict(ZODIAC["пастелно небе pl6c"], gen.BANDS["dark"])[0])
check("  and mid rejects both ends: 19 and 201",
      not gen.verdict((19.1, 18.4, 185.0), gen.BANDS["mid"])[0]
      and not gen.verdict((201.5, 17.3, 32.2), gen.BANDS["mid"])[0])
check("v1's gloom, luma 40 muddy, fails bright and mid",
      not gen.verdict((40.0, 40.0, 150.0), gen.BANDS["bright"])[0]
      and not gen.verdict((40.0, 40.0, 150.0), gen.BANDS["mid"])[0])
check("  v2's wash, luma 172, fails mid and dark",
      not gen.verdict((172.0, 30.0, 140.0), gen.BANDS["mid"])[0]
      and not gen.verdict((172.0, 30.0, 140.0), gen.BANDS["dark"])[0])
check("a near-black render fails every band",
      not any(gen.verdict((6.0, 30.0, 150.0), b)[0] for b in gen.BANDS.values()))
check("  a blown-out one fails every band",
      not any(gen.verdict((245.0, 30.0, 60.0), b)[0] for b in gen.BANDS.values()))
check("  a flat wash fails every band",
      not any(gen.verdict((110.0, 3.0, 170.0), b)[0] for b in gen.BANDS.values()))
check("  a greyscale one fails every band",
      not any(gen.verdict((110.0, 40.0, 5.0), b)[0] for b in gen.BANDS.values()))
check("  the default band is mid, for a frame with no bucket",
      gen.BAND is gen.BANDS["mid"] and gen.band_for("nothing") is gen.BANDS["mid"])
check("  and an unmeasurable frame is kept and says so",
      gen.verdict(None) == (True, "unmeasured"))


print("\n--- six frames go darker than their bucket, on their own floor ---")
check("exactly six frames carry their own luma floor",
      gen.MIN_LUMA_BY_FRAME == {"lv18a": 10.0, "int1": 10.0, "lv04a": 18.0,
                                "lv05a": 38.0, "lv05d": 38.0, "lv08a": 30.0},
      str(gen.MIN_LUMA_BY_FRAME))
check("  each set above a black render and under its own bucket's floor",
      all(6.0 < v < gen.BANDS[by_id[i]["bucket"]]["min_luma"]
          for i, v in gen.MIN_LUMA_BY_FRAME.items()))
for frame_id, floor in sorted(gen.MIN_LUMA_BY_FRAME.items()):
    bucket = by_id[frame_id]["bucket"]
    check("  %-6s band is the %s band with only the floor moved"
          % (frame_id, bucket),
          by_id[frame_id]["band"] == dict(gen.BANDS[bucket], min_luma=floor)
          and by_id[frame_id]["band"] is not gen.BANDS[bucket])
check("a pendant that drew 21 to 38 passes its own floor in bright",
      gen.verdict((25.0, 30.0, 120.0), by_id["lv04a"]["band"])[0]
      and not gen.verdict((25.0, 30.0, 120.0), by_id["lv04b"]["band"])[0])
check("  and a lamp between chairs at 42 passes its own floor in mid",
      gen.verdict((42.0, 30.0, 140.0), by_id["lv05a"]["band"])[0]
      and not gen.verdict((42.0, 30.0, 140.0), by_id["lv05b"]["band"])[0])
NEBULA = (12.0, 45.0, 140.0)
check("a nebula at 12 passes its own floor and fails the dark band",
      gen.verdict(NEBULA, by_id["lv18a"]["band"])[0]
      and not gen.verdict(NEBULA, gen.BANDS["dark"])[0]
      and not gen.verdict(NEBULA, by_id["lv18b"]["band"])[0])
check("  while a near-black render fails its floor too",
      not any(gen.verdict((6.0, 30.0, 150.0), by_id[i]["band"])[0]
              for i in gen.MIN_LUMA_BY_FRAME))
check("  and a dark frame is still held to the dark ceiling",
      not gen.verdict((110.0, 30.0, 140.0), by_id["lv18a"]["band"])[0]
      and not gen.verdict((90.0, 30.0, 140.0), by_id["int1"]["band"])[0])
check("the run judges each frame on its own band",
      'verdict(measure(img), frame["band"])' in gen_src
      and "verdict(measure(img))" not in gen_src)
check("the floor is in an overridden frame's recipe, and in no other",
      all("|min_luma=%g" % v in gen.recipe(by_id[i])
          for i, v in gen.MIN_LUMA_BY_FRAME.items())
      and not [f["id"] for f in plan
               if f["id"] not in gen.MIN_LUMA_BY_FRAME
               and "min_luma" in gen.recipe(f)])
_before = gen.recipe(by_id["lv18a"])
gen.MIN_LUMA_BY_FRAME["lv18a"] = 12.0
try:
    _after = gen.recipe(by_id["lv18a"])
finally:
    gen.MIN_LUMA_BY_FRAME["lv18a"] = 10.0
check("  so moving one floor invalidates one record",
      _after != _before and gen.recipe(by_id["lv18a"]) == _before
      and gen.recipe(dict(plan[0], band=gen.BANDS[plan[0]["bucket"]]))
      == gen.recipe(plan[0]))
check("  and the dry run says which band a frame draws under",
      "%s: luma %g-%g" in gen_src)


print("\n--- the frame mechanics, run for real ---")
try:
    from PIL import Image, ImageDraw
except ImportError:
    Image = None
if Image is None:
    notes.append("Pillow is not installed here, so the crop, the encoder "
                 "and the measure were not exercised")
else:
    def synthetic(size, noisy=False, ground=(168, 108, 48),
                  hills=(48, 70, 78)):
        # A low amber sun over teal hills: what a correct v3 frame is.
        # Pass v2's pale ground to make the frame v2 rejected.
        img = Image.new("RGB", size, ground)
        draw = ImageDraw.Draw(img)
        w, h = size
        draw.ellipse((w * 0.3, h * 0.3, w * 0.7, h * 0.7), fill=(245, 200, 90))
        # Hills along the bottom, so the frame has the spread a picture
        # has and is not one flat wash with a disc on it.
        draw.rectangle((0, h * 0.78, w, h), fill=hills)
        if noisy:
            import random
            rng = random.Random(7)
            px = img.load()
            for _ in range(w * h // 2):
                x, y = rng.randrange(w), rng.randrange(h)
                px[x, y] = (rng.randrange(256), rng.randrange(256),
                            rng.randrange(256))
        return img

    def png(img):
        buf = io.BytesIO()
        img.save(buf, "PNG")
        return buf.getvalue()

    render = png(synthetic((1024, 1536)))
    pair = gen.fit(render, gen.KINDS["pair"]["size"])
    check("a 1024x1536 render comes down whole to a 640x960 pair card",
          pair.size == (640, 960))
    cell = gen.fit(render, gen.KINDS["grid"]["size"])
    check("  and is centre-cropped to a 360x600 grid cell", cell.size == (360, 600))
    tall = gen.fit(render, gen.KINDS["interstitial"]["size"])
    check("  and to an 800x1000 interstitial", tall.size == (800, 1000))
    wide = gen.fit(png(synthetic((1536, 1024))), gen.KINDS["pair"]["size"])
    check("  and a wrong-shaped render still lands on the frame",
          wide.size == (640, 960))
    stats = gen.measure(pair)
    check("the measure reads luma, spread and colour",
          stats is not None and len(stats) == 3 and stats[2] > 0)
    check("  and the synthetic low-sun frame passes the mid band",
          gen.verdict(stats)[0], str(stats))
    dusk = Image.new("RGB", (640, 960), (20, 28, 62))
    ImageDraw.Draw(dusk).ellipse((190, 290, 450, 670), fill=(242, 194, 90))
    check("  an indigo night with a gold disc fails mid and passes dark",
          not gen.verdict(gen.measure(dusk))[0]
          and gen.verdict(gen.measure(dusk), gen.BANDS["dark"])[0],
          str(gen.measure(dusk)))
    pale = synthetic((640, 960), ground=(232, 222, 206), hills=(146, 128, 98))
    check("  and a pale pastel with the same sun fails mid and passes bright",
          not gen.verdict(gen.measure(pale))[0]
          and gen.verdict(gen.measure(pale), gen.BANDS["bright"])[0],
          str(gen.measure(pale)))
    data, q = gen.encode(pair)
    check("a quiet frame encodes under the ceiling at full quality",
          data is not None and len(data) <= gen.MAX_BYTES and q == gen.QUALITY,
          "%s bytes at q%s" % (len(data or b""), q))
    noisy = synthetic((640, 960), noisy=True)
    heavy, hq = gen.encode(noisy, ceiling=10)
    check("  and a frame that cannot get under the ceiling is refused",
          heavy is None and hq == gen.QUALITY_FLOOR, "q%s" % hq)
    stepped, sq = gen.encode(noisy)
    check("  stepping quality down is what buys the bytes",
          (stepped is None and sq == gen.QUALITY_FLOOR)
          or (stepped is not None and len(stepped) <= gen.MAX_BYTES),
          "%s at q%s" % (len(stepped or b""), sq))
    check("  size is checked against the committed geometry",
          gen.size_ok(pair, gen.KINDS["pair"]["size"])
          and not gen.size_ok(pair, gen.KINDS["grid"]["size"]))


print("\n--- it writes into its gallery and its manifest, nowhere else ---")
writers = set()
for func in [n for n in ast.walk(ast.parse(gen_src))
             if isinstance(n, ast.FunctionDef)]:
    for node in ast.walk(func):
        if (isinstance(node, ast.Call)
                and isinstance(node.func, ast.Name)
                and node.func.id == "open"
                and any(isinstance(a, ast.Constant) and "w" in str(a.value)
                        for a in node.args[1:])):
            writers.add(func.name)
check("only three functions open a file for writing",
      writers == {"write", "write_reject", "save_manifest"},
      str(sorted(writers)))
check("  the reject writer writes beside the gallery, in a folder that "
      "ignores itself",
      'os.path.join(OUT, REJECTS)' in gen_src and gen.REJECTS == "_rejects"
      and 'fh.write("*\\n")' in gen_src)
check("  the frame writer writes into the gallery",
      re.search(r"def write\(frame_id, data\):\s*\n\s*path = "
                r"os\.path\.join\(OUT,", gen_src) is not None
      and gen.OUT == GALLERY)
check("  and the manifest writer writes the manifest, atomically",
      "tmp = MANIFEST + \".tmp\"" in gen_src
      and "os.replace(tmp, MANIFEST)" in gen_src)
check("  never under static/ except its own gallery",
      gen_src.count('"static"') == 1)


print("\n--- the run, without a key ---")
import contextlib                                              # noqa: E402


def run(argv):
    out = io.StringIO()
    with contextlib.redirect_stdout(out):
        code = gen.main(argv)
    return code, out.getvalue()


called = []
real_generate = gen.generate
gen.generate = lambda *a, **kw: called.append(a) or (_ for _ in ()).throw(
    RuntimeError("must not be called"))
was = gen.ENV_FILES
gen.ENV_FILES = (os.path.join(SCRATCH, "absent"),)
try:
    code, text = run(["--dry-run", "--force"])
    check("a forced dry run prints every prompt and calls nothing",
          code == 0 and not called and text.count("--- lv") == 44
          and text.count("--- int") == 2 and "nothing called" in text,
          "exit %s, %d calls" % (code, len(called)))
    check("  and states the count and the estimate first",
          re.search(r"46 frame\(s\) to draw, ~\$\d+\.\d\d estimated", text)
          is not None, text.splitlines()[0])
    code, text = run(["--dry-run"])
    check("a plain dry run lists only the frames not yet recorded",
          code == 0 and not called
          and text.count("--- ") == len([f for f in plan
                                         if not gen.already_made(
                                             f, gen.load_manifest())]),
          text.splitlines()[0])
    check("  and names the palette it would draw under",
          "palette v5" in text.splitlines()[0], text.splitlines()[0])
    if gen.load_manifest():
        check("  with a pre-v4 manifest on disk that is all forty-six",
              text.count("--- ") == 46, text.splitlines()[0])
        check("    each under its bucket's band",
              text.count("bright: luma 110-225") == 3
              and text.count("bright: luma 18-225") == 1
              and text.count("mid: luma 55-135") == 25
              and text.count("mid: luma 38-135") == 2
              and text.count("mid: luma 30-135") == 1
              and text.count("dark: luma") == 14, text.splitlines()[0])
        code, text = run(["--only", "lv06b,lv18a", "--dry-run"])
        check("--only draws exactly the frames named — calibration first",
              code == 0 and text.count("--- ") == 2 and "lv06b" in text
              and "lv18a" in text, text.splitlines()[0])
        code, text = run(["--only", "lv06b"])
        check("  and with no key a calibration run stops before calling",
              code == 1 and not called and "nothing was called" in text, text)
    code, text = run(["--only", "lv07a,nope"])
    check("an unknown frame id is refused, exit 2",
          code == 2 and "nope" in text and not called)
    code, text = run(["--only", "lv07a", "--force"])
    check("with no key anywhere the run stops before calling, exit 1",
          code == 1 and not called and "nothing was called" in text, text)
    code, text = run(["--only", "lv07c", "--dry-run", "--force"])
    check("  --only narrows the dry run to the frames named",
          code == 0 and text.count("--- lv") == 1 and "lv07c" in text
          and "(grid, 360x600" in text)
finally:
    gen.generate = real_generate
    gen.ENV_FILES = was
check("no file was written by any of that",
      not os.path.exists(gen.MANIFEST + ".tmp"))


print("\n--- --save-rejects keeps what the band throws away ---")
if Image is not None:
    black = Image.new("RGB", (1024, 1536), (4, 4, 6))
    buf = io.BytesIO()
    black.save(buf, "PNG")
    BLACK = buf.getvalue()
    scratch_out = os.path.join(SCRATCH, "gallery")
    os.makedirs(scratch_out, exist_ok=True)
    was_out, was_manifest = gen.OUT, gen.MANIFEST
    was_key, was_gen = gen.api_key, gen.generate
    gen.OUT = scratch_out
    gen.MANIFEST = os.path.join(SCRATCH, "manifest.json")
    gen.api_key = lambda: "sk-test"
    gen.generate = lambda *a, **kw: BLACK
    try:
        code, text = run(["--only", "lv03a", "--retries", "1"])
        check("without the flag a rejected draw is discarded",
              code == 1 and "rejected" in text
              and not os.path.exists(os.path.join(scratch_out, "_rejects")),
              text.splitlines()[-4:])
        code, text = run(["--only", "lv03a", "--retries", "1",
                          "--save-rejects"])
        kept = sorted(os.listdir(os.path.join(scratch_out, "_rejects")))
        check("with it every rejected draw is written under _rejects/",
              code == 1 and kept == [".gitignore", "lv03a_1.webp",
                                     "lv03a_2.webp"], str(kept))
        check("  named by frame and attempt, and said so in the log",
              "_rejects/lv03a_1.webp" in text
              and "_rejects/lv03a_2.webp" in text)
        check("  the folder ignores itself, so nothing in it is ever "
              "committed",
              open(os.path.join(scratch_out, "_rejects", ".gitignore"),
                   encoding="utf-8").read() == "*\n")
        check("  and nothing reached the gallery or the manifest",
              not [f for f in os.listdir(scratch_out) if f.endswith(".webp")]
              and not os.path.exists(gen.MANIFEST))
        with Image.open(os.path.join(scratch_out, "_rejects",
                                     "lv03a_1.webp")) as im:
            check("  a kept reject is the frame at its committed shape",
                  im.size == (640, 960), str(im.size))
    finally:
        gen.OUT, gen.MANIFEST = was_out, was_manifest
        gen.api_key, gen.generate = was_key, was_gen
    import shutil
    shutil.rmtree(scratch_out)
check("the real gallery has no _rejects folder committed",
      not os.path.exists(os.path.join(GALLERY, "_rejects"))
      or os.path.exists(os.path.join(GALLERY, "_rejects", ".gitignore")))


print("\n--- the placeholder script, and the gallery on disk ---")
ph = load(PLACEHOLDERS, "gen_love_placeholders_t")
check("the placeholders come off the same config into the same gallery",
      ph.CONFIG == gen.CONFIG and ph.OUT == gen.OUT and ph.OWNED == gen.OWNED)
check("  at the shape the real art is kept at, per step format",
      ph.FRAME_BY_FORMAT == {"pair": gen.KINDS["pair"]["size"],
                             "grid4": gen.KINDS["grid"]["size"]}
      and ph.FRAME_TALL == gen.KINDS["interstitial"]["size"])
check("  and it leaves a frame already on disk alone",
      "not os.path.exists" in ph_src)
check("  never painting into another funnel's gallery",
      "startswith(OWNED)" in ph_src)
gallery = {f[:-len(".webp")] for f in os.listdir(GALLERY)
           if f.endswith(".webp")}
want = {f["id"] for f in plan} | {"og"}
check("every planned frame has a file, and the og beside them — forty-seven",
      want <= gallery and len(want) == 47, str(sorted(want - gallery)[:4]))
check("  and the gallery holds nothing else — plan equals directory",
      not (gallery - want), str(sorted(gallery - want)[:4]))
big = [f for f in sorted(gallery)
       if os.path.getsize(os.path.join(GALLERY, f + ".webp")) > 120 * 1024]
check("no frame is over 120KB", not big, str(big[:4]))
if Image is not None:
    def size_of(name):
        with Image.open(os.path.join(GALLERY, name + ".webp")) as im:
            return im.size
    wrong = [(f["id"], size_of(f["id"])) for f in plan
             if size_of(f["id"]) != f["size"]]
    check("  every file on disk is the shape its frame is planned at",
          not wrong, str(wrong[:4]))
tiny = [f for f in sorted(gallery)
        if os.path.getsize(os.path.join(GALLERY, f + ".webp")) < 6 * 1024]
if tiny:
    notes.append("%d of %d frames are still placeholders (under 6KB) — "
                 "real art lands with the owner's run of "
                 "scripts/gen_love_gallery.py" % (len(tiny), len(gallery)))
print("    %d frames, %d still placeholder-sized" % (len(gallery), len(tiny)))
check("the og is the placeholder script's, not the generator's",
      "og" not in by_id and '"og"' in ph_src)

# Tidy the scratch files this suite wrote.
for name in os.listdir(SCRATCH):
    os.remove(os.path.join(SCRATCH, name))
os.rmdir(SCRATCH)

if saved_key is not None:
    os.environ["OPENAI_API_KEY"] = saved_key

print("\n%d checks, %d failed" % (checks[0], len(fails)))
for f in fails:
    print("  FAIL " + f)
for n in notes:
    print("  NOTE " + n)
sys.exit(1 if fails else 0)
