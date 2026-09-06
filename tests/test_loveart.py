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
is skipped; delete the file or edit the prompt and it is drawn again. v2
bumps every recipe, so the whole v1 manifest is stale and nothing is skipped.

The floor rejects the old gloom. The whole v1 gallery measured luma 25 to
62; the default floor is above every one of those, and only the frames whose
subject is dark are judged under a floor of their own.

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
SUFFIX_TEXT = (", painterly dreamy style, soft luminous palette — dawn sky, "
               "golden hour or airy pastel light — with warm gold accents, "
               "gentle glow, {guidance}, no text, no watermark, no close-up "
               "faces")
check("the base suffix is the review's, with the crop guidance as its slot",
      gen.STYLE_SUFFIX == SUFFIX_TEXT, repr(gen.STYLE_SUFFIX))
check("  and it says nothing about a night or an indigo palette",
      "indigo" not in gen.STYLE_SUFFIX and "night" not in gen.STYLE_SUFFIX)
check("  every prompt ends on it", all(
    f["prompt"].endswith(", no text, no watermark, no close-up faces")
    and "soft luminous palette — dawn sky, golden hour or airy pastel light "
        "— with warm gold accents, gentle glow" in f["prompt"]
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
          for i, s in gen.CARD_PROMPTS + gen.TALL_PROMPTS))
SUBJECTS = {
    "lv01a": "spark of golden light leaping between two reaching hands, "
             "bright dawn sky behind",
    "lv05c": "two silhouettes laughing together at a sunlit kitchen table, "
             "light spilling in",
    "lv07d": "two silhouettes dancing in a bright kitchen in daylight, sun "
             "through the window",
    "lv10d": "hammock for two strung between trees in a leafy garden, "
             "dappled sunlight",
    "lv11b": "glowing embers in a hearth, warm amber light radiating onto "
             "stone, deep red and gold",
    "lv16d": "two figures in a parked car on a hill watching the sunset, "
             "warm glowing sky",
    "lv18a": "heart-shaped nebula glowing in deep space, warm gold and rose "
             "against the dark",
    "int1": "night sky with two falling stars over a faint horizon glow",
}
for frame_id, subject in sorted(SUBJECTS.items()):
    check("  %-6s is the review's subject" % frame_id,
          dict(gen.CARD_PROMPTS + gen.TALL_PROMPTS)[frame_id] == subject)
check("no prompt asks for a face, a word or a watermark",
      all("no close-up faces" in f["prompt"] and "no text" in f["prompt"]
          and "no watermark" in f["prompt"] for f in plan))
# The palette moved to light: every scene that is not deliberately dark says
# so in its own words, and the dark ones are exactly the frames with a floor
# of their own.
LIGHT = re.compile(r"dawn|sunrise|sunlit|sunlight|golden|morning|daylight|"
                   r"bright|pastel|afternoon|spring|sunset", re.I)
dark = set(gen.MIN_LUMA_BY_FRAME)
check("every frame not named dark is written in daylight words",
      all(LIGHT.search(s) for i, s in gen.CARD_PROMPTS + gen.TALL_PROMPTS
          if i not in dark),
      str([i for i, s in gen.CARD_PROMPTS + gen.TALL_PROMPTS
           if i not in dark and not LIGHT.search(s)]))
check("  and the dark ones are at most six of forty-six",
      0 < len(dark) <= 6 and dark <= set(by_id), str(sorted(dark)))


print("\n--- the manifest: recipes, idempotency, a full redraw ---")
recipes = [gen.recipe(f) for f in plan]
check("every frame's recipe is distinct", len(set(recipes)) == len(recipes))
check("  and carries the version, the prompt, the API size and the geometry",
      gen.RECIPE_VERSION == "v2"
      and all(r.startswith("v2|") for r in recipes)
      and all(f["prompt"] in gen.recipe(f) and f["api_size"] in gen.recipe(f)
              and "%dx%d" % f["size"] in gen.recipe(f) for f in plan))
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
    check("the v1 manifest is stale in full: nothing recorded is skipped",
          not [i for i in entries if i in by_id
               and gen.already_made(by_id[i], entries)],
          str([i for i in entries if i in by_id
               and gen.already_made(by_id[i], entries)][:3]))
    check("  so a plain run redraws all forty-six",
          len([f for f in plan if not gen.already_made(f, entries)]) == 46)
    old = [float(m.group(1)) for e in entries.values()
           for m in [re.search(r"luma ([\d.]+)", e.get("note", ""))] if m]
    check("  and every frame v1 recorded sits under the new floor",
          old and max(old) < gen.MIN_MEAN_LUMA,
          "max recorded luma %.1f vs floor %.1f"
          % (max(old) if old else -1, gen.MIN_MEAN_LUMA))
    print("    %d v1 frames recorded, all invalidated" % len(entries))
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


print("\n--- the floor, raised against the old gloom ---")
check("the default floor is 80, over every frame v1 drew",
      gen.MIN_MEAN_LUMA == 80.0 and gen.BAND["min_luma"] == 80.0)
check("  and the ceiling admits an airy pastel frame",
      gen.MAX_MEAN_LUMA == 235.0)
check("a dawn or golden-hour frame passes",
      gen.verdict((132.0, 44.0, 70.0))[0]
      and gen.verdict((96.0, 50.0, 90.0))[0])
check("  a pale pastel frame passes too", gen.verdict((205.0, 30.0, 30.0))[0])
check("a frame at v1's brightest, 62, is rejected now",
      not gen.verdict((62.0, 40.0, 120.0))[0])
check("  and v1's median, 41, is rejected", not gen.verdict((41.0, 40.0, 120.0))[0])
check("a near-black render fails", not gen.verdict((6.0, 30.0, 150.0))[0])
check("  a blown-out one fails", not gen.verdict((245.0, 30.0, 60.0))[0])
check("  a flat wash fails", not gen.verdict((150.0, 3.0, 100.0))[0])
check("  a greyscale one fails", not gen.verdict((150.0, 40.0, 5.0))[0])
check("  and an unmeasurable frame is kept and says so",
      gen.verdict(None) == (True, "unmeasured"))


print("\n--- four frames are deliberately dark, and judged on their own floor ---")
check("exactly four frames carry their own luma floor",
      gen.MIN_LUMA_BY_FRAME == {"lv11b": 20.0, "lv17a": 40.0,
                                "lv18a": 25.0, "int1": 25.0},
      str(gen.MIN_LUMA_BY_FRAME))
check("  each set above a black render and under the default",
      all(6.0 < v < gen.MIN_MEAN_LUMA for v in gen.MIN_LUMA_BY_FRAME.values()))
for frame_id, floor in sorted(gen.MIN_LUMA_BY_FRAME.items()):
    check("  %-6s band is the shared band with only the floor moved" % frame_id,
          by_id[frame_id]["band"] == dict(gen.BAND, min_luma=floor)
          and by_id[frame_id]["band"] is not gen.BAND)
check("  and every other frame is judged on the shared band, untouched",
      all(f["band"] == gen.BAND for f in plan
          if f["id"] not in gen.MIN_LUMA_BY_FRAME))
NEBULA = (30.0, 45.0, 140.0)
check("a nebula at 30 passes its own floor and fails the shared one",
      gen.verdict(NEBULA, by_id["lv18a"]["band"])[0]
      and not gen.verdict(NEBULA, gen.BAND)[0]
      and not gen.verdict(NEBULA, by_id["lv18b"]["band"])[0])
check("  embers at 22 pass lv11b's floor and fail lv17a's",
      gen.verdict((22.0, 38.0, 140.0), by_id["lv11b"]["band"])[0]
      and not gen.verdict((22.0, 38.0, 140.0), by_id["lv17a"]["band"])[0])
check("  while a near-black render fails every dark floor too",
      not any(gen.verdict((6.0, 30.0, 150.0), by_id[i]["band"])[0]
              for i in gen.MIN_LUMA_BY_FRAME))
check("the run judges each frame on its own band",
      'verdict(measure(img), frame["band"])' in gen_src
      and "verdict(measure(img))" not in gen_src)
check("the floor is in a dark frame's recipe, and in no other",
      all("|min_luma=%g" % v in gen.recipe(by_id[i])
          for i, v in gen.MIN_LUMA_BY_FRAME.items())
      and not [f["id"] for f in plan
               if f["id"] not in gen.MIN_LUMA_BY_FRAME
               and "min_luma" in gen.recipe(f)])
check("  so moving one floor invalidates one record",
      gen.recipe(dict(by_id["lv18a"], band=dict(gen.BAND, min_luma=12.0)))
      != gen.recipe(by_id["lv18a"])
      and gen.recipe(dict(plan[0], band=gen.BAND)) == gen.recipe(plan[0]))
check("  and the dry run says which floor a frame draws under",
      "luma floor %g" in gen_src)


print("\n--- the frame mechanics, run for real ---")
try:
    from PIL import Image, ImageDraw
except ImportError:
    Image = None
if Image is None:
    notes.append("Pillow is not installed here, so the crop, the encoder "
                 "and the measure were not exercised")
else:
    def synthetic(size, noisy=False):
        # A pale dawn sky with a gold sun: what a correct v2 frame is.
        img = Image.new("RGB", size, (232, 222, 206))
        draw = ImageDraw.Draw(img)
        w, h = size
        draw.ellipse((w * 0.3, h * 0.3, w * 0.7, h * 0.7), fill=(242, 194, 90))
        # Soft hills along the bottom, so the frame has the spread a
        # picture has and is not one flat wash with a disc on it.
        draw.rectangle((0, h * 0.78, w, h), fill=(146, 128, 98))
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
    check("  and the synthetic dawn frame passes the new floor",
          gen.verdict(stats)[0], str(stats))
    dusk = Image.new("RGB", (640, 960), (20, 28, 62))
    ImageDraw.Draw(dusk).ellipse((190, 290, 450, 670), fill=(242, 194, 90))
    check("  while v1's indigo night with a gold disc fails it",
          not gen.verdict(gen.measure(dusk))[0], str(gen.measure(dusk)))
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
check("only two functions open a file for writing",
      writers == {"write", "save_manifest"}, str(sorted(writers)))
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
