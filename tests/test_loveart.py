#!/usr/bin/env python3
"""Checks over the love-zodiac-bg gallery generator.

scripts/gen_love_gallery.py draws the funnel's real art. It is a console
tool, run by hand against a key, and nothing imports it — so what is worth
asserting is not that it runs but that what it would send, keep and skip is
right before anybody spends money on finding out.

Three things carry most of the weight.

The plan comes off the config and is held to it. Every love-owned image id
the funnel references has a prompt and every prompt names an id the funnel
references; a config that drifts from the plan makes the generator refuse
rather than draw a gallery nobody sees.

The manifest makes reruns cheap and deletions meaningful. A frame whose file
still hashes to what was recorded, drawn from a prompt that has not changed,
is skipped; delete the file or edit the prompt and it is drawn again. The
placeholders are never recorded, so the first real run paints over them.

And the key is read off ~/mazzin/.env as a literal line, never sourced, with
the environment as the fallback — so a run on the server needs no export and
never puts every secret in .env into the process.

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


print("\n--- the plan comes off the config ---")
plan = gen.frames(cfg)
by_id = {f["id"]: f for f in plan}
images = [i for s in cfg["swipe"]["steps"] for p in s["pairs"]
          for i in p["images"] if i["img"].startswith(gen.OWNED)]
extras = [g for g in cfg.get("preview_gallery") or []
          if g["img"].startswith(gen.OWNED)
          and g["id"] not in {i["id"] for i in images}]
check("thirty-eight frames: thirty-six cards and two interstitials",
      len(plan) == 38
      and sum(f["kind"] == "card" for f in plan) == 36
      and sum(f["kind"] == "interstitial" for f in plan) == 2,
      str({f["kind"] for f in plan}))
check("  the cards are every love card the walk shows, in walk order",
      [f["id"] for f in plan if f["kind"] == "card"]
      == [i["id"] for i in images])
check("  the interstitials are the two frames only the preview strip names",
      [f["id"] for f in plan if f["kind"] == "interstitial"]
      == [g["id"] for g in extras] == ["int1", "int2"])
check("  no sign glyph is planned — those are the zodiac gallery's",
      not [f for f in plan if f["id"].startswith("sign_")])
check("no id is planned twice", len(by_id) == len(plan))
check("the prompt table is the brief, thirty-six and two",
      len(gen.CARD_PROMPTS) == 36 and len(gen.TALL_PROMPTS) == 2)


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
check("  while the committed config is accepted", refuses(cfg) is None)


print("\n--- what a frame is asked for ---")
SUFFIX_TEXT = (", painterly dreamy style, deep indigo night palette with "
               "warm gold accents, soft glow, {aspect}, no text, no "
               "watermark, no close-up faces")
check("the base suffix is the brief's, with the aspect as its one slot",
      gen.STYLE_SUFFIX == SUFFIX_TEXT, repr(gen.STYLE_SUFFIX))
check("  every prompt ends on it", all(
    f["prompt"].endswith(", no text, no watermark, no close-up faces")
    and "painterly dreamy style, deep indigo night palette with warm gold "
        "accents, soft glow" in f["prompt"]
    for f in plan))
check("  cards say square 1:1, the interstitials portrait 4:5",
      all("square 1:1" in f["prompt"] and "4:5" not in f["prompt"]
          for f in plan if f["kind"] == "card")
      and all("portrait 4:5" in f["prompt"] and "1:1" not in f["prompt"]
              for f in plan if f["kind"] == "interstitial"))
check("  and every subject is carried verbatim, opening the prompt",
      all(by_id[i]["prompt"].startswith(s + ",")
          for i, s in gen.CARD_PROMPTS + gen.TALL_PROMPTS))
SUBJECTS = {
    "lv01a": "lightning spark between two reaching hands",
    "lv09a": "paper plane flying through night sky toward a lit window",
    "lv16b": "two glasses of wine and an unfinished conversation, dying candle",
    "lv18b": "two hands forming a heart against a full moon",
    "int1": "night sky with two falling stars",
    "int2": "two candles in darkness, one lighting the other",
}
for frame_id, subject in sorted(SUBJECTS.items()):
    check("  %-6s is the brief's subject" % frame_id,
          dict(gen.CARD_PROMPTS + gen.TALL_PROMPTS)[frame_id] == subject)
check("no prompt asks for a face, a word or a watermark",
      all("no close-up faces" in f["prompt"] and "no text" in f["prompt"]
          and "no watermark" in f["prompt"] for f in plan))
check("cards are drawn 1:1 at 1024 and kept at 800 square",
      all(f["api_size"] == "1024x1024" and f["size"] == (800, 800)
          for f in plan if f["kind"] == "card"))
check("  interstitials are drawn portrait and kept at 800x1000",
      all(f["api_size"] == "1024x1536" and f["size"] == (800, 1000)
          for f in plan if f["kind"] == "interstitial"))
check("the price table knows both sizes at the quality in use",
      all((gen.IMAGE_QUALITY, s) in gen.PRICE
          for s in ("1024x1024", "1024x1536")),
      "%s %s" % (gen.IMAGE_QUALITY, sorted(gen.PRICE)))


print("\n--- the manifest: recipes, idempotency, redraw by deletion ---")
recipes = [gen.recipe(f) for f in plan]
check("every frame's recipe is distinct", len(set(recipes)) == len(recipes))
check("  and carries the prompt, the API size and the geometry",
      all(f["prompt"] in gen.recipe(f) and f["api_size"] in gen.recipe(f)
          and "%dx%d" % f["size"] in gen.recipe(f) for f in plan))
check("  so the same subject at another size is another recipe",
      gen.recipe(dict(plan[0], size=(800, 1000), api_size="1024x1536"))
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
if os.path.exists(gen.MANIFEST):
    entries = gen.load_manifest()
    check("  the committed manifest names only planned frames",
          set(entries) <= set(by_id), str(sorted(set(entries) - set(by_id))))
    check("  and every recorded frame is on disk at the recorded hash",
          all(gen.on_disk_sha(i) == e.get("sha256")
              for i, e in entries.items()),
          str([i for i, e in entries.items()
               if gen.on_disk_sha(i) != e.get("sha256")][:3]))
    check("  every recorded frame is still skipped: the recipe change "
          "touched none of them",
          all(gen.already_made(by_id[i], entries) for i in entries
              if i in by_id and i != "lv11b"),
          str([i for i in entries if i in by_id and i != "lv11b"
               and not gen.already_made(by_id[i], entries)][:3]))
    check("  and lv11b, unrecorded, is what a plain run draws",
          "lv11b" not in entries
          or not gen.already_made(by_id["lv11b"], entries))
    print("    %d of %d frames recorded as drawn" % (len(entries), len(plan)))
else:
    notes.append("no manifest yet: every frame is a placeholder and the "
                 "owner's first run draws all %d" % len(plan))
    check("  with no manifest, nothing is skipped",
          not any(gen.already_made(f, gen.load_manifest()) for f in plan))


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


print("\n--- the floor, for a night palette ---")
check("the floor is its own, tuned below persona's exposure band",
      gen.MIN_MEAN_LUMA < 90.0 and gen.MIN_MEAN_LUMA > 0
      and gen.MAX_MEAN_LUMA < 255.0 and gen.MIN_SATURATION > 0)
check("a correct indigo-and-gold frame passes",
      gen.verdict((48.0, 40.0, 120.0))[0])
check("  a bright one passes too", gen.verdict((150.0, 50.0, 60.0))[0])
check("a near-black render fails", not gen.verdict((6.0, 30.0, 150.0))[0])
check("  a blown-out one fails", not gen.verdict((240.0, 30.0, 60.0))[0])
check("  a flat wash fails", not gen.verdict((60.0, 3.0, 100.0))[0])
check("  a greyscale one fails", not gen.verdict((60.0, 40.0, 5.0))[0])
check("  and an unmeasurable frame is kept and says so",
      gen.verdict(None) == (True, "unmeasured"))

print("\n--- one frame is deliberately dark, and judged on its own floor ---")
# lv11b is embers in a hearth: it came back at about 15 three times, correct
# and rejected against a floor written for an indigo night. It draws under
# its own number now, and nothing else does.
check("exactly one frame carries its own luma floor",
      gen.MIN_LUMA_BY_FRAME == {"lv11b": 10.0}, str(gen.MIN_LUMA_BY_FRAME))
check("  set under what an ember scene measures and above a black render",
      6.0 < gen.MIN_LUMA_BY_FRAME["lv11b"] < 15.0 < gen.MIN_MEAN_LUMA)
check("  and its prompt asks for the light the floor expects",
      dict(gen.CARD_PROMPTS)["lv11b"]
      == "glowing embers in a hearth, warm amber light radiating onto stone, "
         "deep red and gold")
check("its band is the shared band with only the luma floor moved",
      by_id["lv11b"]["band"] == dict(gen.BAND, min_luma=10.0)
      and by_id["lv11b"]["band"] is not gen.BAND, str(by_id["lv11b"]["band"]))
check("  and every other frame is judged on the shared band, untouched",
      all(f["band"] == gen.BAND for f in plan if f["id"] != "lv11b")
      and gen.BAND["min_luma"] == gen.MIN_MEAN_LUMA == 18.0)
EMBERS = (15.0, 38.0, 140.0)
check("an ember frame at 15 passes lv11b's floor",
      gen.verdict(EMBERS, by_id["lv11b"]["band"])[0])
check("  and still fails the shared one, which is the point",
      not gen.verdict(EMBERS, gen.BAND)[0]
      and not gen.verdict(EMBERS, by_id["lv11a"]["band"])[0])
check("  while a near-black render fails lv11b's floor too",
      not gen.verdict((6.0, 30.0, 150.0), by_id["lv11b"]["band"])[0])
check("  and its other three bounds still bite",
      not gen.verdict((60.0, 3.0, 100.0), by_id["lv11b"]["band"])[0]
      and not gen.verdict((60.0, 40.0, 5.0), by_id["lv11b"]["band"])[0]
      and not gen.verdict((240.0, 30.0, 60.0), by_id["lv11b"]["band"])[0])
check("the run judges each frame on its own band",
      'verdict(measure(img), frame["band"])' in gen_src
      and "verdict(measure(img))" not in gen_src)
check("the floor is in lv11b's recipe, and in no other",
      "|min_luma=10" in gen.recipe(by_id["lv11b"])
      and not [f["id"] for f in plan
               if f["id"] != "lv11b" and "min_luma" in gen.recipe(f)])
check("  so moving it invalidates lv11b's record alone",
      gen.recipe(dict(by_id["lv11b"], band=dict(gen.BAND, min_luma=12.0)))
      != gen.recipe(by_id["lv11b"])
      and gen.recipe(dict(plan[0], band=gen.BAND)) == gen.recipe(plan[0]))


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
        img = Image.new("RGB", size, (20, 28, 62))
        draw = ImageDraw.Draw(img)
        w, h = size
        draw.ellipse((w * 0.3, h * 0.3, w * 0.7, h * 0.7), fill=(242, 194, 90))
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

    square = gen.fit(png(synthetic((1024, 1024))), gen.FRAME)
    check("a 1024 square comes down to 800x800", square.size == (800, 800))
    tall = gen.fit(png(synthetic((1024, 1536))), gen.FRAME_TALL)
    check("  a 1024x1536 portrait is centre-cropped to 800x1000",
          tall.size == (800, 1000))
    wide = gen.fit(png(synthetic((1536, 1024))), gen.FRAME)
    check("  and a wrong-shaped render still lands on the frame",
          wide.size == (800, 800))
    stats = gen.measure(square)
    check("the measure reads luma, spread and colour",
          stats is not None and len(stats) == 3 and stats[2] > 0)
    check("  and the synthetic night frame passes the floor",
          gen.verdict(stats)[0], str(stats))
    data, q = gen.encode(square)
    check("a quiet frame encodes under the ceiling at full quality",
          data is not None and len(data) <= gen.MAX_BYTES and q == gen.QUALITY,
          "%s bytes at q%s" % (len(data or b""), q))
    noisy = synthetic((800, 800), noisy=True)
    heavy, hq = gen.encode(noisy, ceiling=10)
    check("  and a frame that cannot get under the ceiling is refused",
          heavy is None and hq == gen.QUALITY_FLOOR, "q%s" % hq)
    stepped, sq = gen.encode(noisy)
    check("  stepping quality down is what buys the bytes",
          (stepped is None and sq == gen.QUALITY_FLOOR)
          or (stepped is not None and len(stepped) <= gen.MAX_BYTES),
          "%s at q%s" % (len(stepped or b""), sq))
    check("  size is checked against the committed geometry",
          gen.size_ok(square, gen.FRAME) and not gen.size_ok(square,
                                                             gen.FRAME_TALL))


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
    # Forced, so the plan is the whole set whether or not a manifest on disk
    # has recorded most of it: the gallery is drawn now, and a plain dry run
    # lists only what is left to draw.
    code, text = run(["--dry-run", "--force"])
    check("a forced dry run prints every prompt and calls nothing",
          code == 0 and not called and text.count("--- lv") == 36
          and text.count("--- int") == 2 and "nothing called" in text,
          "exit %s, %d calls" % (code, len(called)))
    check("  and states the count and the estimate first",
          re.search(r"38 frame\(s\) to draw, ~\$\d+\.\d\d estimated", text)
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
    code, text = run(["--only", "lv07a", "--dry-run", "--force"])
    check("  --only narrows the dry run to the frames named",
          code == 0 and text.count("--- lv") == 1 and "lv07a" in text)
finally:
    gen.generate = real_generate
    gen.ENV_FILES = was
check("no file was written by any of that",
      not os.path.exists(gen.MANIFEST + ".tmp"))


print("\n--- the placeholder script, and the gallery on disk ---")
ph = load(PLACEHOLDERS, "gen_love_placeholders_t")
check("the placeholders come off the same config into the same gallery",
      ph.CONFIG == gen.CONFIG and ph.OUT == gen.OUT and ph.OWNED == gen.OWNED)
check("  at the geometry the real art is kept at",
      ph.FRAME == gen.FRAME and ph.FRAME_TALL == gen.FRAME_TALL)
check("  and it leaves a frame already on disk alone",
      "if not os.path.exists(os.path.join(OUT, i + \".webp\"))" in ph_src
      or "not os.path.exists" in ph_src)
check("  never painting into another funnel's gallery",
      "startswith(OWNED)" in ph_src)
gallery = {f[:-len(".webp")] for f in os.listdir(GALLERY)
           if f.endswith(".webp")}
want = {f["id"] for f in plan} | {"og"}
check("every planned frame has a file, and the og beside them",
      want <= gallery, str(sorted(want - gallery)[:4]))
check("  and the gallery holds nothing else — plan equals directory",
      not (gallery - want), str(sorted(gallery - want)[:4]))
big = [f for f in sorted(gallery)
       if os.path.getsize(os.path.join(GALLERY, f + ".webp")) > 120 * 1024]
check("no frame is over 120KB", not big, str(big[:4]))
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
