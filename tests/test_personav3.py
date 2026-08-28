#!/usr/bin/env python3
"""Checks over scripts/gen_persona_v3_samples.py — the v3 style sampler.

Two candidate styles now: the flat-vector set the owner first reviewed, and
the soft-3D clay direction they picked out of that review. They share the
eight scenes, the geometry, the crop and the safe-area rule, and differ in
their prefix, their negatives and their id prefix — so most of what is
asserted below is asserted twice, once per style, and the interesting checks
are the ones about the seam between them:

  - the vector prompts are frozen against a digest, because those eight frames
    are on disk and were reviewed as they stand;
  - clay does not inherit the vector ban on "3D render", which is the exact
    thing it is asking for;
  - clay ids carry a prefix so both sets share one directory without
    collision, and vector ids carry none, because renaming the reviewed set
    would orphan it;
  - clay's colour floor is its own lower number, not the vector floor moved.

The sampler is a proposal, not a surface. It draws eight frames in the bright
quiz style the owner asked to see before any config rewrite, writes them to a
directory nothing points at, and is judged by a human looking at a phone. So
what is asserted here is not "the art is good" — no suite can say that — but
the two things that have to be true for the owner's look to be a fair test of
the direction, plus the one thing that has to be true for the batch to be
free:

  1. every assembled prompt really carries the v3 identity and the safe-area
     composition rule, and carries none of the dark gallery's vocabulary;
  2. the batch is the eight scenes that were asked for, in that order;
  3. nothing live moved — the deployed persona funnel still names the gallery
     it named this morning, and no config, stylesheet or script has learned
     about the sample directory.

No database, no network, no key, no Pillow. The sampler is imported and its
prompt assembly and sanity floor are exercised directly; the draw itself is
never reached, and a check that would have reached it fails instead.
"""
import hashlib
import importlib.util
import io
import os
import re
import sys
import contextlib

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, REPO)

SCRIPT = os.path.join(REPO, "scripts", "gen_persona_v3_samples.py")

fails = []
checks = [0]


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


print("\n--- the sampler loads with nothing available ---")
# No key in the environment, no Pillow installed, no config on the path it
# reads: importing must still work, because everything it needs at import time
# is its own text.
saved_key = os.environ.pop("OPENAI_API_KEY", None)
v3 = load(SCRIPT, "gen_persona_v3_samples")
check("imports with no key and no Pillow", True)

source = open(SCRIPT, encoding="utf-8").read()
check("it is a console script, run by hand",
      "__main__" in source and "argparse" in source)
check("  and it does not import gen_persona",
      "import gen_persona" not in source
      and "from gen_persona" not in source)


print("\n--- the vector batch ---")
WANT = ["s_morning_run", "s_morning_slow", "s_battery_home",
        "s_battery_people", "s_drain_meeting", "s_bag_notebook",
        "s_weather_fog", "s_character_cartographer"]

plan = v3.samples("vector")
ids = [f["id"] for f in plan]
check("eight samples", len(plan) == 8, str(len(plan)))
check("the eight ids that were asked for, in order", ids == WANT, str(ids))
check("no id drawn twice", len(set(ids)) == len(ids))

# The scene list is hardcoded in the sampler, which means a typo silently
# changes what the owner is shown. Each frame is pinned to the thing it is
# supposed to be a picture of.
SUBJECT = {
    "s_morning_run": ["runner", "dawn", "sun"],
    "s_morning_slow": ["mug", "notebook", "steam"],
    "s_battery_home": ["couch", "cat", "lamp", "phone"],
    "s_battery_people": ["friends", "kitchen table", "laugh"],
    "s_drain_meeting": ["meeting", "clock", "wilted"],
    "s_bag_notebook": ["notebook", "pen", "hero-object"],
    "s_weather_fog": ["fog", "hills"],
    "s_character_cartographer": ["cartographer", "map", "lamp"],
}
by_id = {f["id"]: f["prompt"] for f in plan}
for sample_id, words in SUBJECT.items():
    text = by_id.get(sample_id, "").lower()
    missing = [w for w in words if w not in text]
    check("  %s is a picture of what it says" % sample_id, not missing,
          str(missing))


print("\n--- every vector prompt carries the flat-vector identity ---")
for sample_id, text in by_id.items():
    check("  %s opens on the shared style prefix" % sample_id,
          text.startswith(v3.VECTOR_STYLE))
    check("  %s carries the safe-area rule" % sample_id,
          v3.SAFE_AREA in text)
    check("  %s ends on the shared negatives" % sample_id,
          text.endswith(v3.VECTOR_NEGATIVE))
    check("  %s asks for the teal accent thread" % sample_id,
          "#4EDDC4" in text)

low = v3.VECTOR_STYLE.lower()
for word in ["flat", "vector", "warm", "cream", "coral", "amber",
             "leaf green", "phone-tile"]:
    check("  style says '%s'" % word, word in low)
check("  style refuses a clinical white ground", "pure white" in low)
check("  style allows stylized characters",
      "stylized human characters are welcome" in low)
check("  and holds their faces to dots and a line",
      "dot eyes" in low and "never a realistic" in low)


print("\n--- the composition rule, which is the whole point ---")
rule = v3.SAFE_AREA.lower()
check("names the safe area", "safe area" in rule)
check("names the outer 15 percent", "outer 15 percent" in rule)
check("names all four sides",
      all(w in rule for w in ["top", "bottom", "left", "right"]))
check("demands a whole, unclipped subject",
      "whole" in rule and ("clipped" in rule or "cut off" in rule))
check("says the crop happens twice",
      "centre-cropped" in rule and "again" in rule)
check("composes for a vertical card", "vertical card" in rule)
# Stated once and shared, not pasted per scene and not once per style: a
# seventy-frame redraw is where a copy of this rule drifts, and the crop it is
# written against belongs to the pipeline, not to the material.
check("it lives in one shared constant",
      source.count("Composition for a vertical card") == 1)
check("  and both styles get that same constant, verbatim",
      all(v3.SAFE_AREA in f["prompt"]
          for st in v3.STYLES for f in v3.samples(st)))
for st in sorted(v3.STYLES):
    check("  exactly once in every %s prompt" % st,
          all(f["prompt"].count(v3.SAFE_AREA) == 1 for f in v3.samples(st)))


print("\n--- and none of the dark gallery's vocabulary ---")
# The v2 identity, in the words it is actually written in. A v3 prompt that
# contains any of these is a prompt that has drifted back toward the look the
# owner rejected.
DARK = ["ink-navy", "ink navy", "#101820", "#d9b98c", "muted sand",
        "dark ground", "deep ink", "calm-minimal", "flat silhouette",
        "silhouette", "moody", "mysterious", "sombre", "somber",
        "dramatic lighting", "chiaroscuro", "night sky", "starry"]
for sample_id, text in by_id.items():
    low_text = text.lower()
    hit = [w for w in DARK if w in low_text]
    check("  %s carries no dark-identity vocabulary" % sample_id, not hit,
          str(hit))

# The reversal that matters most, asserted straight: the live gallery bans
# every human face and draws people as silhouettes. v3 must not have carried
# that ban across, or there are no characters and no character system.
joined = " ".join(by_id.values()).lower()
check("faces are not banned outright",
      "no human faces" not in joined and "no faces" not in joined)


print("\n--- the flat-vector set is frozen ---")
# The eight vector frames were reviewed as they stand and are on disk. A
# change to their prompt text would make the committed set and the script
# disagree about what the set is, silently — the files would still be there
# and would no longer be what the script draws. So all eight are pinned to a
# digest, and adding a style is not allowed to move one byte of them.
#
# If a vector prompt is ever genuinely meant to change, this digest is the
# thing to update, deliberately, in the same commit as the redraw.
VECTOR_DIGEST = ("bde9d1bd1610f68ba21922107ee4f8f7715"
                 "d0b0f4143c3e46fe8b1d26baa6870")
vector = {f["id"]: f["prompt"] for f in v3.samples("vector")}
joined = "\n\x00\n".join(vector[k] for k in sorted(vector))
actual = hashlib.sha256(joined.encode("utf-8")).hexdigest()
check("all eight vector prompts are byte-for-byte what was reviewed",
      actual == VECTOR_DIGEST, actual)
check("  and the default style is still vector",
      v3.DEFAULT_STYLE == "vector"
      and [f["id"] for f in v3.samples()] == WANT)
check("  so the vector ids carry no prefix",
      v3.STYLES["vector"]["prefix"] == "")


print("\n--- the clay batch ---")
check("both styles exist and no more", sorted(v3.STYLES) == ["clay", "vector"],
      str(sorted(v3.STYLES)))

clay_plan = v3.samples("clay")
clay_ids = [f["id"] for f in clay_plan]
check("eight clay samples", len(clay_plan) == 8, str(len(clay_plan)))
check("the same eight scenes, in the same order",
      [f["base_id"] for f in clay_plan] == WANT, str(clay_ids))
check("every clay id carries the clay_ prefix",
      clay_ids == ["clay_" + i for i in WANT], str(clay_ids))
check("  so nothing collides with the vector set on disk",
      not (set(clay_ids) & set(vector)))
check("  and both sets share one directory",
      all(f["size"] == v3.FRAME and f["api_size"] == v3.API_PORTRAIT
          for f in clay_plan))

clay_by_id = {f["id"]: f["prompt"] for f in clay_plan}
for base_id, words in SUBJECT.items():
    text = clay_by_id["clay_" + base_id].lower()
    missing = [w for w in words if w not in text]
    check("  clay_%s is the same picture as its twin" % base_id, not missing,
          str(missing))


print("\n--- the clay prompts carry the clay identity ---")
for sample_id, text in clay_by_id.items():
    check("  %s opens on the clay prefix" % sample_id,
          text.startswith(v3.CLAY_STYLE))
    check("  %s carries the safe-area rule" % sample_id,
          v3.SAFE_AREA in text)
    check("  %s ends on the clay negatives" % sample_id,
          text.endswith(v3.CLAY_NEGATIVE))
    check("  %s asks for the teal accent thread" % sample_id,
          "#4EDDC4" in text)
    check("  %s is not wearing the vector prefix" % sample_id,
          v3.VECTOR_STYLE not in text and v3.VECTOR_NEGATIVE not in text)

clay_low = v3.CLAY_STYLE.lower()
for word in ["soft 3d", "clay", "matte", "rounded", "studio lighting",
             "soft diffused shadows", "depth-of-field", "cream",
             "peach", "phone-tile"]:
    check("  clay style says '%s'" % word, word in clay_low)
check("  it asks for a premium app aesthetic",
      "premium modern app aesthetic" in clay_low)
check("  it says rendered, not sculpted by hand",
      "rendered, not sculpted by hand" in clay_low)
check("  it refuses a clinical white ground", "pure white" in clay_low)
check("  it allows moulded characters with minimal faces",
      "moulded in clay" in clay_low and "dot eyes" in clay_low)
check("  and refuses realistic and childish in the same breath",
      "never realistic and never childish" in clay_low)


print("\n--- the guardrails that keep clay off claymation ---")
# The failure mode this brief is defined against. Ask a model for clay with no
# guardrail and it draws Aardman: stop-motion, thumbprints, a nursery. That
# reads cheaper than the flat set, not more premium, so each refusal is named
# rather than left to the positive prompt to imply.
clay_neg = v3.CLAY_NEGATIVE.lower()
for word in ["claymation", "stop-motion", "plasticine", "aardman",
             "fingerprints", "thumbprints", "childish", "toy-like",
             "nursery"]:
    check("  clay negatives refuse '%s'" % word, word in clay_neg)
check("  and refuse photorealism and real faces",
      "no photorealism" in clay_neg
      and "no realistic detailed faces" in clay_neg)

# The one line clay must NOT inherit. The vector set bans "no 3D render",
# which is the exact thing clay is asking for; carried across it would fight
# the prefix in the same prompt.
check("clay does not ban the 3D render it is asking for",
      "3d render" not in clay_neg)
check("  while the vector set still bans it",
      "no 3D render" in v3.VECTOR_NEGATIVE)
check("  and the two negative lists are genuinely different text",
      v3.CLAY_NEGATIVE != v3.VECTOR_NEGATIVE)


print("\n--- and no dark-identity vocabulary in the clay set either ---")
for sample_id, text in clay_by_id.items():
    low_text = text.lower()
    hit = [w for w in DARK if w in low_text]
    check("  %s carries none of it" % sample_id, not hit, str(hit))
clay_joined = " ".join(clay_by_id.values()).lower()
check("faces are not banned outright in clay",
      "no human faces" not in clay_joined and "no faces" not in clay_joined)


print("\n--- what clay says that vector does not ---")
# The character portrait is the frame that decides the eight-personas asset,
# and "collectible figure" is a clay idea: it is what makes a moulded figure
# read as one of a set. Said to a flat render it would just ask for a sticker,
# so it is a note on one scene in one style, not a sentence on all sixteen.
portrait = clay_by_id["clay_s_character_cartographer"]
check("the clay portrait asks for a collectible-figure feel",
      "collectible" in portrait.lower())
check("  and for a set of eight that belong together",
      "eight of these" in portrait.lower())
check("  and is still centred and poster-like",
      "poster-like" in portrait.lower() and "centred" in portrait.lower())
check("  while the vector portrait is left as reviewed",
      "collectible" not in by_id["s_character_cartographer"].lower())

# Two scenes describe their subjects as "flat" — written when flat was the
# material. The scene text is shared and the vector prompts are frozen, so
# clay cannot reword them; it overrules them in the same slot instead.
for base_id in ("s_morning_run", "s_drain_meeting"):
    text = clay_by_id["clay_" + base_id].lower()
    check("  clay_%s names the material as moulded clay" % base_id,
          "moulded clay" in text)
    check("  clay_%s refuses the flat reading outright" % base_id,
          "never a flat graphic" in text or "never flat graphic" in text)
    check("  clay_%s still carries the scene's own 'flat' wording" % base_id,
          "flat buildings" in text or "flat figures" in text)
check("  and the vector twins are untouched by that",
      all("moulded" not in by_id[b].lower()
          for b in ("s_morning_run", "s_drain_meeting")))
check("no clay note leaks into a scene that did not ask for one",
      sum(1 for t in clay_by_id.values()
          if "moulded clay" in t or "collectible" in t) == 3)


print("\n--- --style routes, and routes nothing else ---")
check("prompt_for defaults to vector",
      v3.prompt_for(v3.SAMPLES[0][1]) == v3.prompt_for(v3.SAMPLES[0][1],
                                                       "vector"))
check("sample_id_for prefixes clay and only clay",
      v3.sample_id_for("s_x", "clay") == "clay_s_x"
      and v3.sample_id_for("s_x", "vector") == "s_x")
# A typo'd style must not quietly draw the wrong set into the wrong ids.
try:
    v3.samples("marble")
    raised = False
except KeyError:
    raised = True
check("an unknown style raises, it does not silently fall back to vector",
      raised)


print("\n--- the sanity floor is v3's, not the ink gallery's ---")
gen = load(os.path.join(REPO, "scripts", "gen_persona.py"), "gen_persona")

BRIGHT = (195.0, 55.0, 70.0)          # what a correct v3 frame looks like
check("the ink gate would reject a correct v3 frame",
      BRIGHT[0] > gen.MAX_MEAN_LUMA,
      "%.1f vs %.1f" % (BRIGHT[0], gen.MAX_MEAN_LUMA))
# Not reused, and the docstring says why at length — so this looks at the
# code rather than at the prose: no ink gate on the module, and a ceiling of
# its own that sits well above the one that would have rejected the batch.
check("  so the sampler does not carry it",
      not hasattr(v3, "legibility") and not hasattr(v3, "MIN_LIT"))
check("  and its own ceiling clears the whole bright range",
      v3.MAX_MEAN_LUMA > gen.MAX_MEAN_LUMA and v3.MAX_MEAN_LUMA >= 240.0,
      "%.1f" % v3.MAX_MEAN_LUMA)
check("  with a floor the ink gallery would fail",
      v3.MIN_MEAN_LUMA >= 90.0, "%.1f" % v3.MIN_MEAN_LUMA)

ok, note = v3.sanity(BRIGHT)
check("bright warm art passes", ok, note)
check("  and the note carries the numbers a reviewer would want",
      "luma" in note and "sd" in note and "sat" in note, note)

check("near-black is rejected", not v3.sanity((28.0, 30.0, 40.0))[0])
check("blank white is rejected", not v3.sanity((252.0, 2.0, 1.0))[0])
check("a flat cream wash is rejected", not v3.sanity((225.0, 3.0, 20.0))[0])
check("a colourless render is rejected", not v3.sanity((180.0, 50.0, 4.0))[0])
check("the palest frame in the batch still clears it",
      v3.sanity((215.0, 22.0, 18.0))[0])
# A frame is never lost to the checker — it is going in front of a human.
unmeasured_ok, unmeasured_note = v3.sanity(None)
check("an unmeasurable frame is kept, not dropped",
      unmeasured_ok and "unmeasured" in unmeasured_note)


print("\n--- clay gets its own colour floor, and only that ---")
# Matte clay lit in a studio is a less saturated picture than flat vector art
# on the same ground: a highlight washes toward white and a shade toward grey,
# where a vector fill holds one saturation edge to edge. So clay's colour
# floor is lower — and lower on its own number, rather than by dragging the
# vector floor down to meet it.
check("clay's colour floor is lower than vector's",
      v3.CLAY_MIN_SATURATION < v3.MIN_SATURATION,
      "%.1f vs %.1f" % (v3.CLAY_MIN_SATURATION, v3.MIN_SATURATION))
check("  and vector's is untouched at what it was", v3.MIN_SATURATION == 15.0,
      "%.1f" % v3.MIN_SATURATION)
check("  min_saturation routes by style",
      v3.min_saturation("clay") == v3.CLAY_MIN_SATURATION
      and v3.min_saturation("vector") == v3.MIN_SATURATION
      and v3.min_saturation() == v3.MIN_SATURATION)

# The band between the two floors is the whole point of the second number: a
# pale clay render lands there, and vector would have thrown it away.
PALE_CLAY = (198.0, 26.0, 12.0)
check("a pale clay render passes as clay", v3.sanity(PALE_CLAY, "clay")[0])
check("  and would have been rejected as vector",
      not v3.sanity(PALE_CLAY, "vector")[0])

# Everything else about the floor is shared, and still catches what it caught.
check("clay still rejects near-black", not v3.sanity((28.0, 30.0, 40.0),
                                                     "clay")[0])
check("clay still rejects blank white", not v3.sanity((252.0, 2.0, 1.0),
                                                      "clay")[0])
check("clay still rejects a flat wash", not v3.sanity((225.0, 3.0, 20.0),
                                                      "clay")[0])
check("clay still rejects a colourless render",
      not v3.sanity((180.0, 50.0, 4.0), "clay")[0])
check("  because a greyscale frame is nowhere near the clay floor",
      4.0 < v3.CLAY_MIN_SATURATION)
check("clay keeps an unmeasurable frame", v3.sanity(None, "clay")[0])
check("sanity still defaults to the vector floor",
      v3.sanity(PALE_CLAY) == v3.sanity(PALE_CLAY, "vector"))


print("\n--- the crop and the measurement, when Pillow is here ---")
# Optional by design: the suite must pass on a machine with no Pillow, because
# nothing it guards needs an image. When Pillow IS present the pixel path is
# worth exercising, because the crop is the mechanism the safe-area rule is
# written against — a sampler that cropped differently from what the prompt
# promises would be lying to the model.
try:
    from PIL import Image
except Exception:
    print("  Pillow absent, pixel path skipped")
else:
    import io as _io

    def render(w, h, bands):
        """A crude flat-colour stand-in for a rendered frame."""
        img = Image.new("RGB", (w, h), bands[0])
        for i, colour in enumerate(bands[1:], start=1):
            top = int(h * i / float(len(bands)))
            img.paste(Image.new("RGB", (w, h // len(bands) or 1), colour),
                      (0, top))
        buf = _io.BytesIO()
        img.save(buf, "PNG")
        return buf.getvalue()

    warm = render(1024, 1536, [(250, 240, 226), (240, 110, 90),
                               (78, 221, 196), (247, 190, 70)])
    data, img = v3.to_webp(warm, v3.FRAME)
    check("  a 2:3 render is centre-cropped to the 600x800 tile",
          img.size == v3.FRAME, str(img.size))
    check("  and encodes to WebP bytes", data[:4] == b"RIFF" and len(data) > 0)

    stats = v3.measure(img)
    check("  measure returns luma, spread and saturation",
          stats is not None and len(stats) == 3, str(stats))
    ok, note = v3.sanity(stats)
    check("  warm saturated art clears the floor", ok, note)

    dark = render(1024, 1536, [(12, 16, 22), (16, 24, 32),
                               (10, 14, 20), (14, 20, 28)])
    ok, note = v3.sanity(v3.measure(v3.to_webp(dark, v3.FRAME)[1]))
    check("  an ink render is rejected as off-brief for v3", not ok, note)

    blank = render(1024, 1536, [(255, 255, 255)] * 4)
    ok, note = v3.sanity(v3.measure(v3.to_webp(blank, v3.FRAME)[1]))
    check("  a blank white page is rejected", not ok, note)


print("\n--- geometry, model and cost ---")
check("frame is the live tile geometry", v3.FRAME == (600, 800),
      str(v3.FRAME))
check("rendered portrait 2:3", v3.API_PORTRAIT == "1024x1536",
      v3.API_PORTRAIT)
check("gpt-image-1 at medium", v3.MODEL == "gpt-image-1"
      and v3.IMAGE_QUALITY == "medium",
      "%s / %s" % (v3.MODEL, v3.IMAGE_QUALITY))
check("every sample renders portrait",
      all(f["api_size"] == v3.API_PORTRAIT and f["size"] == v3.FRAME
          for f in plan))
check("a medium portrait draw has a price to log",
      v3.PRICE[("medium", v3.API_PORTRAIT)] > 0)
check("the call retries, like the live generator",
      "def generate(" in source and "retriable" in source)


print("\n--- the run calls nothing it should not ---")


def refuse(*a, **kw):
    raise AssertionError("the sampler called the API")


v3.generate = refuse
v3._post_generation = refuse

buf = io.StringIO()
with contextlib.redirect_stdout(buf):
    code = v3.main(["--dry-run"])
dry = buf.getvalue()
check("--dry-run exits 0", code == 0, str(code))
check("  prints all eight prompts",
      all(i in dry for i in WANT) and dry.count("via 1024x1536") == 8)
check("  and totals the cost it would have spent", "estimated" in dry)
check("  and says it wrote nothing", "nothing written" in dry)
check("  and wrote nothing", not os.path.exists(v3.OUT))

buf = io.StringIO()
with contextlib.redirect_stdout(buf):
    code = v3.main([])
check("no key: exits 1 without drawing", code == 1, str(code))
check("  and says so", "OPENAI_API_KEY is not set" in buf.getvalue())
check("  and still wrote nothing", not os.path.exists(v3.OUT))

buf = io.StringIO()
with contextlib.redirect_stdout(buf):
    code = v3.main(["--only", "s_nope", "--dry-run"])
check("an unknown id is refused, not silently skipped", code == 2, str(code))

buf = io.StringIO()
with contextlib.redirect_stdout(buf):
    code = v3.main(["--only", "s_weather_fog", "--dry-run"])
one = buf.getvalue()
check("--only draws the named sample alone",
      code == 0 and one.count("via 1024x1536") == 1
      and "s_weather_fog" in one)


print("\n--- --style routes the run ---")


def run(argv):
    out = io.StringIO()
    with contextlib.redirect_stdout(out):
        rc = v3.main(argv)
    return rc, out.getvalue()

code, out = run(["--style", "clay", "--dry-run"])
check("--style clay exits 0", code == 0, str(code))
check("  draws all eight clay ids",
      all(("clay_" + i) in out for i in WANT)
      and out.count("via 1024x1536") == 8)
check("  says which style it is running", "clay style" in out)
check("  prints the clay prefix, not the vector one",
      v3.CLAY_STYLE in out and v3.VECTOR_STYLE not in out)
check("  and wrote nothing", not os.path.exists(v3.OUT))

code, out = run(["--dry-run"])
check("no --style is still the vector set",
      code == 0 and "vector style" in out
      and v3.VECTOR_STYLE in out and v3.CLAY_STYLE not in out)

# The prefix is bookkeeping for a shared directory; nobody reviewing clay
# thinks of the fog card as anything but the fog card, so both spellings work.
code, bare = run(["--style", "clay", "--only", "s_weather_fog", "--dry-run"])
check("--only takes the bare scene id under --style clay",
      code == 0 and bare.count("via 1024x1536") == 1
      and "clay_s_weather_fog" in bare)
code, pref = run(["--style", "clay", "--only", "clay_s_weather_fog",
                  "--dry-run"])
check("  and the prefixed id names the same frame",
      code == 0 and pref == bare)

code, out = run(["--style", "clay", "--only", "s_nope", "--dry-run"])
check("an unknown id under clay is refused", code == 2, str(code))
check("  and the message names the style it was refused for",
      "clay" in out and "s_nope" in out)

# A vector-only id must not resolve under clay, or a typo would draw the wrong
# set. The vector ids have no prefix, so `clay_s_morning_run` is the one that
# cannot exist in the vector plan.
code, out = run(["--only", "clay_s_morning_run", "--dry-run"])
check("a clay id is not accepted by the vector run", code == 2, str(code))

# argparse rejects a style that does not exist, before any planning happens.
try:
    with contextlib.redirect_stdout(io.StringIO()), \
            contextlib.redirect_stderr(io.StringIO()):
        v3.main(["--style", "marble", "--dry-run"])
    refused = False
except SystemExit as exc:
    refused = exc.code != 0
check("--style marble is refused at the command line", refused)

if saved_key is not None:
    os.environ["OPENAI_API_KEY"] = saved_key


print("\n--- nothing live moved ---")
check("output is a new directory of its own",
      v3.OUT.endswith(os.path.join("galleries", "persona_v3_samples")),
      v3.OUT)
check("  which is not the deployed gallery",
      os.path.abspath(v3.OUT) != os.path.abspath(gen.OUT))
check("the deployed generator still writes the persona gallery",
      gen.OUT.endswith(os.path.join("galleries", "persona")), gen.OUT)
check("  and still owns /static/galleries/persona/",
      gen.OWNED == "/static/galleries/persona/", gen.OWNED)

# The sample directory is reviewed by opening it, never by the funnel. If any
# config, stylesheet or engine file learns its name, the proposal has become a
# surface and this branch has done more than it said it would.
SAMPLE_DIR = "persona_v3_samples"
LIVE = []
for sub in ("funnels", "static/funnels", "static/js", "static/css"):
    base = os.path.join(REPO, sub)
    for name in sorted(os.listdir(base)):
        path = os.path.join(base, name)
        if os.path.isfile(path):
            LIVE.append(path)
LIVE += [os.path.join(REPO, n) for n in
         ("app.py", "config.py", "reports.py", "payments.py", "deploy.sh")]

named = []
for path in LIVE:
    try:
        with open(path, encoding="utf-8", errors="replace") as fh:
            if SAMPLE_DIR in fh.read():
                named.append(os.path.relpath(path, REPO))
    except OSError:
        pass
check("no config, stylesheet, script or route names the sample dir",
      not named, str(named))

persona_cfg = open(os.path.join(REPO, "funnels/persona.json"),
                   encoding="utf-8").read()
check("the persona funnel still points every frame at its own gallery",
      "/static/galleries/persona/" in persona_cfg
      and not re.search(r"galleries/persona[_-]v3", persona_cfg))
check("  and its static copy says the same",
      open(os.path.join(REPO, "static/funnels/persona.json"),
           encoding="utf-8").read() == persona_cfg)

print("\n%d checks, %d failed" % (checks[0], len(fails)))
for f in fails:
    print("  FAIL " + f)
sys.exit(1 if fails else 0)
