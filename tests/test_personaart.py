#!/usr/bin/env python3
"""Checks over the persona production gallery generator.

scripts/gen_persona.py draws the funnel's real art. It is a console tool, run
by hand against a key, and nothing imports it — so what is worth asserting is
not that it runs but that what it would send, promote and composite is right
before anybody spends money on finding out.

Three things carry most of the weight.

The style is shared. The sampler and this generator import the same module, so
the brief that took ten draws and three rejections to settle cannot be
half-updated. Both files are checked for their own copies of it, because a
copy is exactly what this arrangement exists to prevent and exactly what a
hurried edit would reintroduce.

The frame plan comes off the config. Every id, every form description and
every colour is read from funnels/persona.json rather than restated here, so a
walk redesign is a config edit and a rerun. What is pinned is that the
assembly really does carry the config's own words.

And the two owner-approved renders are promoted rather than redrawn. Drawing
the head again is a lottery ticket against a negative list written to make
heads hard; drawing the approved totem again throws away the one frame that
survived seven attempts.

No key, no network, no spend. The compositors are exercised for real, because
they cost nothing and their output is committed.
"""
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

GALLERY = os.path.join(REPO, "static/galleries/persona")
SAMPLES = os.path.join(REPO, "static/galleries/persona_v3_samples")

fails = []
checks = [0]
notes = []


def check(label, ok, detail=""):
    checks[0] += 1
    if not ok:
        fails.append("%s %s" % (label, detail))
    print("  %-58s %s%s" % (label, "ok" if ok else "FAIL",
                            ("  " + detail) if detail and not ok else ""))


def load(path, name):
    spec = importlib.util.spec_from_file_location(name, path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


print("\n--- it loads with no key and draws nothing on import ---")
saved_key = os.environ.pop("OPENAI_API_KEY", None)
gen = load(os.path.join(REPO, "scripts/gen_persona.py"), "gen_persona_v3")
style = load(os.path.join(REPO, "scripts/persona_style.py"), "persona_style_t")
check("the generator imports", True)
gen_src = open(os.path.join(REPO, "scripts/gen_persona.py"),
               encoding="utf-8").read()
sampler_src = open(os.path.join(REPO, "scripts/gen_persona_v3_samples.py"),
                   encoding="utf-8").read()
style_src = open(os.path.join(REPO, "scripts/persona_style.py"),
                 encoding="utf-8").read()
cfg = json.load(open(os.path.join(REPO, "funnels/persona.json"),
                     encoding="utf-8"))

check("it is a console script, run by hand",
      "__main__" in gen_src and "argparse" in gen_src)
# Imports, not mentions: app.py names a sibling script in a comment, which is
# documentation and not a dependency.
IMPORTS = re.compile(r"^\s*(?:import|from)\s+(?:scripts\.)?gen_persona",
                     re.M)
check("  and nothing in the app imports it",
      not [f for f in ("app.py", "config.py", "reports.py", "payments.py",
                       "tracking.py", "visualizer.py")
           if IMPORTS.search(open(os.path.join(REPO, f),
                                  encoding="utf-8").read())])


print("\n--- one style, two generators ---")
# The whole point of the shared module. A copy in either script is the failure
# it exists to prevent.
check("the style module holds the prompt text",
      all(t in style_src for t in ("SCULPT_STYLE = (", "TOTEM_STYLE = (",
                                   "SAFE_AREA = (", "SCULPT_NEGATIVE = (",
                                   "SCULPT_HEAD_NEGATIVE = (")))
for name, src in (("the generator", gen_src), ("the sampler", sampler_src)):
    check("  %s keeps no copy of it" % name,
          not re.search(r"^(SCULPT_STYLE|TOTEM_STYLE|SAFE_AREA|"
                        r"SCULPT_NEGATIVE|SCULPT_HEAD_NEGATIVE)\s*=\s*\(",
                        src, re.M))
    check("  %s imports it instead" % name,
          "from persona_style import (" in src)
check("  and both get the same strings",
      gen.SCULPT_STYLE is style.SCULPT_STYLE
      or gen.SCULPT_STYLE == style.SCULPT_STYLE)
check("the drawing mechanics are shared too",
      all("def %s(" % f in style_src
          for f in ("generate", "_post_generation", "to_webp", "measure",
                    "verdict"))
      and "def generate(" not in gen_src and "def to_webp(" not in gen_src)
check("  and the safe-area rule is stated once in the whole codebase",
      (gen_src + sampler_src + style_src).count(
          "Composition for a vertical card") == 1)


print("\n--- the frame plan comes off the config ---")
plan = gen.frames(cfg)
by_id = {f["id"]: f for f in plan}
kinds = {}
for f in plan:
    kinds[f["kind"]] = kinds.get(f["kind"], 0) + 1
print("    plan: " + ", ".join("%s %d" % kv for kv in sorted(kinds.items())))

images = [i for s in cfg["swipe"]["steps"] for p in s["pairs"]
          for i in p["images"]]
check("every quiz card in the config is drawn",
      {f["id"] for f in plan if f["kind"] == "quiz"}
      == {i["id"] for i in images},
      str(sorted({i["id"] for i in images}
                 ^ {f["id"] for f in plan if f["kind"] == "quiz"})[:4]))
check("  forty-four of them", kinds.get("quiz") == 44, str(kinds.get("quiz")))
check("eight totems, one per persona",
      {f["id"] for f in plan if f["kind"] in ("totem", "promote")}
      >= {"totem_%s_%s" % (a, e)
          for a in ("igniter", "keeper", "feeler", "thinker")
          for e in ("outer", "inner")})
check("  seven of them drawn, one promoted",
      kinds.get("totem") == 7
      and by_id["totem_igniter_outer"]["kind"] == "promote")
check("eight share cards and one og, all composited",
      kinds.get("share") == 8 and kinds.get("og") == 1)
check("  the share cards are the ids the config declares",
      {f["id"] for f in plan if f["kind"] == "share"}
      == {"share_" + c["id"] for c in cfg["share_cards"]})
check("nothing is planned that the config does not name",
      not [f["id"] for f in plan if f["kind"] == "quiz"
           and f["id"] not in {i["id"] for i in images}])
check("no id is planned twice", len(by_id) == len(plan))


print("\n--- what a quiz card is asked for ---")
card = images[0]
prompt = by_id[card["id"]]["prompt"]
check("it opens on the sculpt prefix", prompt.startswith(style.SCULPT_STYLE))
check("  carries the safe-area rule once",
      prompt.count(style.SAFE_AREA) == 1)
check("  ends on the sculpt negatives", prompt.endswith(style.SCULPT_NEGATIVE))
check("  and carries no totem language",
      style.TOTEM_STYLE not in prompt)
# The config's own words, not a paraphrase of them.
missing = [i["id"] for i in images
           if i["form"] not in by_id[i["id"]]["prompt"]]
check("every card carries its config form description verbatim",
      not missing, str(missing[:3]))
colourless = [i["id"] for i in images
              if not all(c["hex"] in by_id[i["id"]]["prompt"]
                         for c in i["colors"])]
check("  and all three of its config colours", not colourless,
      str(colourless[:3]))
check("  named the way the prompt should say them",
      "in the %s" % card["colors"][0]["element"] in prompt)


print("\n--- what a totem is asked for ---")
totem = by_id["totem_thinker_inner"]["prompt"]
check("it stacks the totem block on the sculpt prefix",
      totem.startswith(style.SCULPT_STYLE) and style.TOTEM_STYLE in totem)
check("  the safe-area rule still once", totem.count(style.SAFE_AREA) == 1)
check("  and the sculpt negatives still last",
      totem.endswith(style.SCULPT_NEGATIVE))
prof = cfg["result_copy"]["profile"]
for persona_id, name, essence in gen.personas(cfg):
    frame = by_id["totem_" + persona_id]
    if frame["kind"] != "totem":
        continue
    text = frame["prompt"]
    check("  totem_%s names its persona and essence" % persona_id,
          name in text and essence in text)
    check("    and carries its own form language",
          gen.TOTEM_FORMS[persona_id] in text)
# The note the seventh draw failed on: light through the whole form.
for persona_id, form in gen.TOTEM_FORMS.items():
    check("  totem_%s puts the light in the form, not at a point" % persona_id,
          re.search(r"\b(veins?|seams?|glow|luminous|lit)\b", form.lower())
          is not None)
check("  and every totem form leads with a gesture",
      all(re.search(r"\b(coiled|planted|settled|cresting|running|standing|"
                    r"bent|rising|holding|spread)\b", f.lower())
          for f in gen.TOTEM_FORMS.values()))
check("the form language is derived per persona, not shared",
      len(set(gen.TOTEM_FORMS.values())) == len(gen.TOTEM_FORMS) == 7)
check("  and the promoted one has none, because it is not drawn",
      "igniter_outer" not in gen.TOTEM_FORMS)


print("\n--- floors, per class ---")
check("quiz cards are judged on the quiz band",
      by_id[images[0]["id"]]["band"] == style.QUIZ_BAND)
check("totems are judged on the totem band",
      by_id["totem_thinker_inner"]["band"] == style.TOTEM_BAND)
check("  which differs in exactly one number",
      {k for k in style.QUIZ_BAND
       if style.QUIZ_BAND[k] != style.TOTEM_BAND[k]} == {"max_sat"},
      str({k: (style.QUIZ_BAND[k], style.TOTEM_BAND[k])
           for k in style.QUIZ_BAND
           if style.QUIZ_BAND[k] != style.TOTEM_BAND[k]}))
check("  the colour ceiling", style.TOTEM_BAND["max_sat"] == 235.0)
check("  and the exposure band is the same for both",
      style.QUIZ_BAND["min_luma"] == style.TOTEM_BAND["min_luma"] == 90.0)
BRIGHT = (168.0, 46.0, 152.0)
check("a lit frame passes either band",
      style.verdict(BRIGHT, style.QUIZ_BAND)[0]
      and style.verdict(BRIGHT, style.TOTEM_BAND)[0])
check("a dark frame fails either band",
      not style.verdict((28.0, 40.0, 150.0), style.QUIZ_BAND)[0]
      and not style.verdict((28.0, 40.0, 150.0), style.TOTEM_BAND)[0])
check("a neon frame fails only the totem band",
      style.verdict((170.0, 45.0, 243.0), style.QUIZ_BAND)[0]
      and not style.verdict((170.0, 45.0, 243.0), style.TOTEM_BAND)[0])


print("\n--- the two promoted renders ---")
check("the head is promoted, never drawn",
      by_id["head_base"]["kind"] == "promote"
      and by_id["head_base"]["from"] == "sculpt_p_head_base")
check("  and so is the approved totem",
      by_id["totem_igniter_outer"]["from"] == "sculpt_p_totem_open_flame")
check("  neither has a prompt at all",
      "prompt" not in by_id["head_base"]
      and "prompt" not in by_id["totem_igniter_outer"])
check("  and exactly two frames are promoted", len(gen.PROMOTE) == 2)

have_samples = os.path.isdir(SAMPLES)
if not have_samples:
    notes.append(
        "the approved sample renders are not in the repo — "
        "static/galleries/persona_v3_samples/ has no git history at all, so "
        "the promotion cannot be verified here and the owner's run is what "
        "performs it")
    print("    samples absent: promotion is code-checked, not byte-checked")
    # What can still be asserted: the generator refuses rather than inventing.
    check("  a missing sample is a loud failure, not a silent skip",
          'failed.append((frame_id, "sample missing' in gen_src
          and "MISSING" in gen_src)
else:
    for frame_id, source in gen.PROMOTE.items():
        src = os.path.join(SAMPLES, source + ".webp")
        dst = os.path.join(GALLERY, frame_id + ".webp")
        if not (os.path.exists(src) and os.path.exists(dst)):
            check("  %s promoted from %s" % (frame_id, source), False,
                  "missing on disk")
            continue
        check("  %s is byte-identical to %s" % (frame_id, source),
              open(src, "rb").read() == open(dst, "rb").read())


print("\n--- the compositors, run for real ---")
check("a usable font is found", gen.fonts() is not None, str(gen.fonts()))
totem_path = os.path.join(GALLERY, "totem_thinker_outer.webp")
if os.path.exists(totem_path):
    first = gen.encode(gen.share_card(totem_path, "The Bright Beacon"))
    second = gen.encode(gen.share_card(totem_path, "The Bright Beacon"))
    check("the share card composites", len(first) > 2000, str(len(first)))
    check("  and is byte-deterministic", first == second,
          "%s vs %s" % (hashlib.sha256(first).hexdigest()[:12],
                        hashlib.sha256(second).hexdigest()[:12]))
    from PIL import Image
    card = Image.open(io.BytesIO(first))
    check("  at the aspect every social preview crops to",
          card.size == (1200, 630), str(card.size))
    # A different persona has to make a different card, or the compositor is
    # ignoring its inputs.
    other = gen.encode(gen.share_card(totem_path, "The Deep Root"))
    check("  and the name is actually drawn on it", other != first)

    # Every name has to fit. Three of the eight overflow at the base size, so
    # the fit is the thing worth pinning rather than the size.
    from PIL import ImageDraw, ImageFont
    draw = ImageDraw.Draw(Image.new("RGB", (10, 10)))
    bold = gen.fonts()[0]
    room = 1200 - (118 + 330 + 76) - 48
    over = []
    for _pid, name, _e in gen.personas(cfg):
        font = gen.fit_text(draw, name, bold, 62, room)
        if draw.textbbox((0, 0), name, font=font)[2] > room:
            over.append(name)
    check("  every persona name fits the card", not over, str(over))
    check("    including the longest one",
          gen.fit_text(draw, "The Quiet Cartographer", bold, 62, room).size
          < 62)
    check("    and fit_text refuses to go below its floor",
          gen.fit_text(draw, "x" * 400, bold, 62, room).size == 34)
else:
    check("a totem exists to composite from", False, totem_path)

shapes = [os.path.join(GALLERY, s + ".webp") for s in gen.OG_SHAPES]
if all(os.path.exists(p) for p in shapes):
    og_first = gen.encode(gen.og_card(shapes, gen.OG_HEADLINE))
    check("the og card composites and is deterministic",
          og_first == gen.encode(gen.og_card(shapes, gen.OG_HEADLINE)))
    check("  it carries the funnel's own hook line",
          gen.OG_HEADLINE == cfg["swipe"]["subtext"].split(".")[0] + ".",
          "%r vs %r" % (gen.OG_HEADLINE, cfg["swipe"]["subtext"]))
    check("  and is built from quiz shapes that exist",
          all(s in {i["id"] for i in images} for s in gen.OG_SHAPES),
          str([s for s in gen.OG_SHAPES
               if s not in {i["id"] for i in images}]))
else:
    check("the og shapes exist", False, str(shapes[:1]))


print("\n--- the manifest ---")
manifest = json.load(open(os.path.join(REPO, "scripts/persona_art.json"),
                          encoding="utf-8"))
check("it is reset for v3", manifest.get("version") == "v3",
      str(manifest.get("version")))
check("  and carries no v1 frames",
      not [k for k in manifest.get("frames", {})
           if k.startswith("animal_") or k in ("pk1a", "sq3a")],
      str(sorted(manifest.get("frames", {}))[:3]))
# The recipe is what a rerun compares against, so it has to change when the
# thing that makes the frame changes — and differ between frame classes.
quiz_recipe = gen.recipe(by_id[images[0]["id"]])
check("a drawn frame's recipe is its prompt",
      quiz_recipe == by_id[images[0]["id"]]["prompt"])
check("  a promoted frame's is its source",
      gen.recipe(by_id["head_base"]) == "promote:sculpt_p_head_base")
check("  a share card's is its persona and name",
      gen.recipe(by_id["share_keeper_inner"]).startswith("share:keeper_inner"))
check("  and the og's is its headline",
      gen.recipe(by_id["og"]) == "og:" + gen.OG_HEADLINE)
check("all four recipes are distinct",
      len({gen.recipe(by_id[images[0]["id"]]), gen.recipe(by_id["head_base"]),
           gen.recipe(by_id["share_keeper_inner"]),
           gen.recipe(by_id["og"])}) == 4)
# Idempotency: recorded and unchanged means skip; anything else means remake.
sample = by_id["og"]
digest = hashlib.sha256(gen.recipe(sample).encode("utf-8")).hexdigest()
on_disk = gen.on_disk_sha("og")
check("a frame recorded with matching bytes and recipe is skipped",
      gen.already_made(sample, {"og": {"sha256": on_disk,
                                       "recipe_sha": digest}}))
check("  a changed recipe unskips it",
      not gen.already_made(sample, {"og": {"sha256": on_disk,
                                           "recipe_sha": "0" * 64}}))
check("  changed bytes on disk unskip it",
      not gen.already_made(sample, {"og": {"sha256": "0" * 64,
                                           "recipe_sha": digest}}))
check("  and an unrecorded frame is never skipped",
      not gen.already_made(sample, {}))


print("\n--- the gallery on disk ---")
gallery = {f[:-len(".webp")] for f in os.listdir(GALLERY)
           if f.endswith(".webp")}
want = {f["id"] for f in plan}
check("every planned frame has a file", want <= gallery,
      str(sorted(want - gallery)[:4]))
check("  and the gallery holds nothing else",
      not (gallery - want), str(sorted(gallery - want)[:4]))
big = [f for f in sorted(gallery)
       if os.path.getsize(os.path.join(GALLERY, f + ".webp")) > 120 * 1024]
check("no frame is over 120KB", not big, str(big[:4]))
# How much of it is still stand-in. Reported rather than asserted: the
# placeholders are correct until the owner's run replaces them.
tiny = [f for f in sorted(gallery)
        if os.path.getsize(os.path.join(GALLERY, f + ".webp")) < 6 * 1024]
if tiny:
    notes.append("%d of %d frames are still v3-A placeholders (under 6KB) — "
                 "real art lands with the owner's run"
                 % (len(tiny), len(gallery)))
print("    %d frames, %d still placeholder-sized" % (len(gallery), len(tiny)))


print("\n--- the cranial zone, which is measured and never moved ---")
check("the generator can measure it", callable(gen.cranial_zone))
check("  and knows what the stylesheet claims",
      gen.CSS_INLAY == {"top": 13.0, "left": 26.0,
                        "width": 48.0, "height": 48.0})
sheet = open(os.path.join(REPO, "static/css/result_persona.css"),
             encoding="utf-8").read()
check("  which is what the stylesheet actually says",
      re.search(r"\.pr-head-inlay \{[^}]*top: 13%;[^}]*left: 26%;"
                r"[^}]*width: 48%;[^}]*height: 48%;", sheet, re.S) is not None)
# It names the stylesheet rule in a docstring, which is how it explains
# itself, and that is fine. What it must never do is write one: a generator
# that could silently move the reader's own diagram is what this guards
# against, so the check is on writes rather than on mentions.
check("  it reports rather than repositions",
      "nothing was changed" in gen_src
      and not re.search(r"\.css", re.sub(r'"""(?:.|\n)*?"""|#[^\n]*', "",
                                         gen_src)))
# And more broadly: the only two places this generator opens a file for
# writing are the function that writes a frame into its own gallery and the
# one that writes its own manifest. Found by walking the tree rather than by
# matching text, because the interesting part is which function the call sits
# in, not what the local variable happens to be called.
import ast                                                    # noqa: E402

writers = set()
gen_tree = ast.parse(gen_src)
for func in [n for n in ast.walk(gen_tree)
             if isinstance(n, ast.FunctionDef)]:
    for node in ast.walk(func):
        if (isinstance(node, ast.Call)
                and isinstance(node.func, ast.Name)
                and node.func.id == "open"
                and any(isinstance(a, ast.Constant) and "w" in str(a.value)
                        for a in node.args[1:])):
            writers.add(func.name)
check("  and only two functions open a file for writing",
      writers == {"write", "save_manifest"}, str(sorted(writers)))
check("    the frame writer writes into the gallery and nowhere else",
      re.search(r"def write\(frame_id, data\):\s*\n\s*path = "
                r"os\.path\.join\(OUT,", gen_src) is not None)
check("    and the manifest writer writes the manifest",
      re.search(r"tmp = MANIFEST \+ \".tmp\"", gen_src) is not None
      and "os.replace(tmp, MANIFEST)" in gen_src)
head_path = os.path.join(GALLERY, "head_base.webp")
if os.path.exists(head_path) and os.path.getsize(head_path) > 6 * 1024:
    found = gen.cranial_zone(head_path)
    if found:
        drift = max(abs(found[k] - gen.CSS_INLAY[k]) for k in gen.CSS_INLAY)
        print("    render: %s" % found)
        check("  the render's smooth field matches the stylesheet",
              drift <= 6, "worst drift %.1f points" % drift)
    else:
        check("  a smooth field was found in the render", False)
else:
    notes.append("head_base.webp is still the v3-A placeholder, so the "
                 ".pr-head-inlay percentages could not be checked against a "
                 "real render — run `gen_persona.py --check-head` after the "
                 "promotion")
    print("    head is still a placeholder: inlay unverified")

if saved_key is not None:
    os.environ["OPENAI_API_KEY"] = saved_key

print("\n%d checks, %d failed" % (checks[0], len(fails)))
for f in fails:
    print("  FAIL " + f)
for n in notes:
    print("  NOTE " + n)
sys.exit(1 if fails else 0)
