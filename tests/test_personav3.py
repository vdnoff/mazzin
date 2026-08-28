#!/usr/bin/env python3
"""Checks over scripts/gen_persona_v3_samples.py — the v3 style sampler.

Three candidate styles now: the flat-vector set the owner reviewed first, the
soft-3D clay direction picked out of that review, and the abstract sculptural
forms locked after both were rejected. They share the geometry, the crop, the
safe-area rule and the id set, and differ in their prefix, their negatives,
their id prefix and — for sculpt — their scenes. So most of what is asserted
below is asserted three times, and the interesting checks are the seams:

  - the vector and clay prompts are each frozen against a digest, because
    those sixteen frames are on disk and were reviewed as they stand. sculpt
    is deliberately NOT pinned: it has not been reviewed yet, and freezing a
    set before anybody has looked at it only makes the next revision noisy;
  - clay does not inherit the vector ban on "3D render", which is the exact
    thing it is asking for;
  - sculpt inverts what the other two are careful to allow. vector and clay
    go out of their way to permit a face at two dots and a line; sculpt bans
    figures, faces and scenes outright;
  - and since v3 it does not share their ids either. Its eight are
    idiom-states — wound up, drained, scattered — physical metaphors that
    ordinary language already uses for psychological ones, so the word IS
    the shape. They are not answers to the shared eight questions, so they
    get their own sample list and their own ids. The two-way principle is
    pinned structurally: the id carries the idiom, the idiom word must
    appear in the frame's own text, and the text must then say what that
    word looks like as a form;
  - the figure ban is checked on the positive half of a prompt only. The
    negatives necessarily say "no faces", and a whole-prompt search would
    flag the refusal as if it were a request. Craft vocabulary — finger
    impressions, hand-sculpted — is subtracted before the ban runs, since
    those name a surface and a process rather than a thing to draw, and the
    subtraction is itself checked so it cannot quietly become a hole;
  - the v2 prefix rules are all still pinned: a gesture per composition
    (eight, no two alike, none a restatement of the form language), the
    handmade marks named as visible rather than subtle, and the contrast
    rule stated once. The tension vocabulary now gates on whether a form is
    physically discontinuous — broken, on a point, cracked open — rather
    than on whether a scene is strained, because v3's idioms are mostly
    expressive and a tense/calm split would have permitted it everywhere;
  - each style's ids carry a prefix so all three sets share one directory
    without collision — except vector, which carries none, because renaming
    the first reviewed set would orphan it;
  - clay and sculpt each get their own lower colour floor, not the vector
    floor moved.

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
check("  and every style gets that same constant, verbatim",
      all(v3.SAFE_AREA in f["prompt"]
          for st in v3.STYLES for f in v3.samples(st)))
for st in sorted(v3.STYLES):
    check("  exactly once in every %s prompt" % st,
          all(f["prompt"].count(v3.SAFE_AREA) == 1 for f in v3.samples(st)))


print("\n--- and none of the dark gallery's vocabulary ---")
# The v2 identity, in the words it is actually written in. A v3 prompt that
# contains any of these is a prompt that has drifted back toward the look the
# owner rejected.
# Bare "silhouette" used to be on this list and is not any more. In the dark
# gallery it means a person drawn as a black shape — but as a composition
# term it just means the outline, which is precisely how sculpt has to talk
# about a gesture being readable at tile size. The dark reading is still
# banned as "flat silhouette", the phrase the ink prompts actually use, and
# the figure ban below is the stronger guard anyway: a sculpt prompt cannot
# ask for a person in the first place, in any rendering.
DARK = ["ink-navy", "ink navy", "#101820", "#d9b98c", "muted sand",
        "dark ground", "deep ink", "calm-minimal", "flat silhouette",
        "moody", "mysterious", "sombre", "somber",
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


print("\n--- the reviewed sets are frozen ---")
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

# Clay is frozen on the same terms and for the same reason: it was reviewed as
# it stands, and a third style is not licence to move it.
CLAY_DIGEST = ("8ec87ff3216e5dfd12a4306a05485e6f93f"
               "00abf5c95b0c28d800f422e90fb61")
clay_frozen = {f["id"]: f["prompt"] for f in v3.samples("clay")}
clay_joined = "\n\x00\n".join(clay_frozen[k] for k in sorted(clay_frozen))
clay_actual = hashlib.sha256(clay_joined.encode("utf-8")).hexdigest()
check("all eight clay prompts are byte-for-byte what was reviewed",
      clay_actual == CLAY_DIGEST, clay_actual)
check("  and the default style is still vector",
      v3.DEFAULT_STYLE == "vector"
      and [f["id"] for f in v3.samples()] == WANT)
check("  so the vector ids carry no prefix",
      v3.STYLES["vector"]["prefix"] == "")


print("\n--- the clay batch ---")
check("all three styles exist and no more",
      sorted(v3.STYLES) == ["clay", "sculpt", "vector"],
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


print("\n--- the sculpt batch: eight idiom-states ---")
# v3 changes what a sculpt frame IS, so it changes the ids too. The eight are
# no longer answers to the shared eight questions — they are physical-metaphor
# states, and filing them as sculpt_s_morning_run would claim a
# correspondence that is not there.
SCULPT_WANT = ["i_wound_up", "i_drained", "i_scattered", "i_grounded",
               "i_on_edge", "i_carrying", "i_walled_off", "i_lit_up"]

# v3-A adds three production slots the funnel rewrite needs now — the clay
# head, one totem, one card face. They are not idioms and are filed apart
# under p_ so the concept set stays exactly eight.
SCULPT_PREVIEW_WANT = ["p_head_base", "p_totem_open_flame",
                       "p_chapter_climbing"]

sculpt_plan = v3.samples("sculpt")
sculpt_ids = [f["id"] for f in sculpt_plan]
idiom_plan = [f for f in sculpt_plan if f["base_id"].startswith("i_")]
preview_plan = [f for f in sculpt_plan if f["base_id"].startswith("p_")]
check("eleven sculpt samples: eight idioms and three preview slots",
      len(sculpt_plan) == 11, str(len(sculpt_plan)))
check("the eight idioms, in order",
      [f["base_id"] for f in idiom_plan] == SCULPT_WANT,
      str([f["base_id"] for f in idiom_plan]))
check("  and the concept set is still exactly eight", len(idiom_plan) == 8)
check("the three preview slots, in order",
      [f["base_id"] for f in preview_plan] == SCULPT_PREVIEW_WANT,
      str([f["base_id"] for f in preview_plan]))
check("every sculpt id carries the sculpt_ prefix",
      sculpt_ids == ["sculpt_" + f["base_id"] for f in sculpt_plan],
      str(sculpt_ids))
check("  idioms are marked i_, preview slots p_",
      all(i.startswith("sculpt_i_") for i in
          [f["id"] for f in idiom_plan])
      and all(i.startswith("sculpt_p_") for i in
              [f["id"] for f in preview_plan]))
check("  so nothing collides with the two sets already on disk",
      not (set(sculpt_ids) & set(vector))
      and not (set(sculpt_ids) & set(clay_by_id)))
# The v1/v2 sculpt frames are on disk under sculpt_s_*. These are new files
# beside them, not overwrites, so both can be compared on the phone.
check("  nor with the sculpt frames v1 and v2 already wrote",
      not any(i.startswith("sculpt_s_") for i in sculpt_ids))
check("  and sculpt no longer answers the shared questions",
      not (set(f["base_id"] for f in sculpt_plan) & set(WANT)))
check("  and all three sets still share one directory and one geometry",
      all(f["size"] == v3.FRAME and f["api_size"] == v3.API_PORTRAIT
          for f in sculpt_plan))

sculpt_by_id = {f["id"]: f["prompt"] for f in sculpt_plan}


print("\n--- the two-way test, made structural ---")
# The principle the set is built on: word alone must be sculptable without
# ambiguity, and image alone must return the word. A prompt can only be
# checked on the first half of that — the second is what the owner review is
# for — but the first half has a structural shape. The id IS the idiom, the
# idiom word must appear in the frame's own text, and the text must then say
# what that word looks like as a form. A frame missing the word is a shape
# with a caption; a frame missing the form language is a caption with no
# shape.
IDIOM_FORM = {
    "i_wound_up": ["coil", "compressed", "about to release"],
    "i_drained": ["collapsed", "sagging", "draped"],
    "i_scattered": ["fragments", "drifting apart", "gaps"],
    "i_grounded": ["monolith", "wide rooted base", "immovable"],
    "i_on_edge": ["balanced", "point of contact", "about to go over"],
    "i_carrying": ["bowed", "sphere", "weight pressing down"],
    "i_walled_off": ["wall", "enclosed", "opening"],
    "i_lit_up": ["glowing", "core", "cracks and seams"],
}
check("every idiom has its form language pinned",
      sorted(IDIOM_FORM) == sorted(SCULPT_WANT))

scene_of = dict(v3.SCULPT_SAMPLES)
for base_id in SCULPT_WANT:
    # The id is the label word: i_wound_up -> "wound up". Derived rather than
    # written out again, so an id and its idiom cannot drift apart.
    word = base_id[len("i_"):].replace("_", " ")
    scene = scene_of[base_id].lower()
    check("  sculpt_%s says '%s' in its own text" % (base_id, word),
          word in scene)
    missing = [w for w in IDIOM_FORM[base_id] if w not in scene]
    check("  sculpt_%s says what '%s' looks like" % (base_id, word),
          not missing, str(missing))

check("no two idioms are the same word", len(set(SCULPT_WANT)) == 8)
# Every one of these is a physical state before it is a psychological one,
# which is the whole reason a sculpture can carry it. None of them names a
# situation, which is what v2 got wrong.
for base_id in SCULPT_WANT:
    word = base_id[len("i_"):].replace("_", " ")
    check("  '%s' is a state, not a scene" % word,
          not re.search(r"\b(meeting|morning|run|commute|party|office)\b",
                        word))



print("\n--- the sculpt prompts carry the sculpt identity ---")
for sample_id, text in sculpt_by_id.items():
    check("  %s opens on the sculpt prefix" % sample_id,
          text.startswith(v3.SCULPT_STYLE))
    check("  %s carries the safe-area rule, once" % sample_id,
          text.count(v3.SAFE_AREA) == 1)
    if sample_id != "sculpt_p_head_base":
        check("  %s ends on the sculpt negatives" % sample_id,
              text.endswith(v3.SCULPT_NEGATIVE))
    check("  %s asks for the teal accent thread" % sample_id,
          "#4EDDC4" in text)
    check("  %s wears no other style's prefix" % sample_id,
          v3.VECTOR_STYLE not in text and v3.CLAY_STYLE not in text)

sculpt_low = v3.SCULPT_STYLE.lower()
for word in ["clay sculpture", "still-life", "matte clay", "plasticine",
             "studio product lighting", "from one direction",
             "warm monochrome", "terracotta", "ochre", "sand",
             "warm grey", "negative space", "phone-tile"]:
    check("  sculpt style says '%s'" % word, word in sculpt_low)
check("  it refuses a clinical white ground", "pure white" in sculpt_low)
check("  it asks for one to three warm tones per composition",
      "one to three warm sculpture tones" in sculpt_low)
check("  it puts the teal on exactly one element",
      "on exactly one element" in sculpt_low)
check("  it makes the colour carry the state",
      "state-bearing colour" in sculpt_low
      and "never a pleasant palette laid over an unrelated form" in sculpt_low)
check("  and puts the teal only where the state is happening",
      "teal at the meaning point" in sculpt_low
      and "never sits anywhere as decoration" in sculpt_low)
check("  and it says the meaning is carried by form, not by depiction",
      "the meaning is carried by shape" in sculpt_low
      and "never by depicting anything" in sculpt_low)


print("\n--- v2 rule 1: every form is DOING something ---")
# The v1 review's verdict was that all eight frames read the same: static,
# symmetric, rounded, calm. The fix is a verb per scene, and a named failure
# mode in the prefix — "abstract sculptural form" on its own reliably returns
# a symmetrical object sitting still.
check("the prefix demands a gesture", "doing something" in sculpt_low)
check("  names the gestures it means",
      all(v in sculpt_low for v in ["launching", "slumping", "leaning",
                                    "huddling", "wilting", "reaching"]))
check("  requires asymmetry and implied motion",
      "asymmetry and implied motion are required" in sculpt_low)
check("  and calls a static balanced still-life a failure",
      "is a failure of this brief" in sculpt_low)
check("  with the one exemption that is not a loophole",
      "unless the composition's meaning is itself stillness" in sculpt_low)

# The rule survives v3 and gets easier to satisfy, because an idiom-state is
# already a thing a form is doing rather than a thing it is. What still has to
# be checked is that each scene SAYS the doing — a state named and then
# described statically is the v2 failure in new clothes.
#
# Pinned separately from IDIOM_FORM above and deliberately not overlapping it:
# that table checks the form is described, this one checks it is in motion or
# under load.
GESTURE = {
    "i_wound_up": "leaning",
    "i_drained": "nothing left holding it up",
    "i_scattered": "came apart",
    "i_grounded": "flaring where it meets",
    "i_on_edge": "tipped past",
    "i_carrying": "bulging where the load",
    "i_walled_off": "raised around itself",
    "i_lit_up": "spilling from inside",
}
check("every idiom has a gesture pinned",
      sorted(GESTURE) == sorted(SCULPT_WANT))
for base_id, phrase in GESTURE.items():
    check("  sculpt_%s is doing something: '%s'" % (base_id, phrase),
          phrase in scene_of[base_id].lower())
# Eight different gestures, or the set repeats itself in a new vocabulary.
check("  and no two idioms share a gesture",
      len(set(GESTURE.values())) == 8)
check("  none of them is a restatement of the form language",
      not any(GESTURE[b] in " ".join(IDIOM_FORM[b]) for b in SCULPT_WANT))


print("\n--- v2 rule 2: the handmade marks, unmissable ---")
# v1 came back machine-smooth. A perfectly even volume reads as a 3D asset,
# not as clay, so the marks are named as things pushed into a surface rather
# than as an adjective like "organic" that a renderer can satisfy invisibly.
for word in ["hand-sculpted", "finger impressions", "press marks",
             "pinch ridges", "uneven planes", "imperfect edges"]:
    check("  prefix pins '%s'" % word, word in sculpt_low)
check("  it says the marks must be visible, not implied",
      "must visibly look it" in sculpt_low)
check("  it names the asymmetry as the tell no machine leaves",
      "no machine would leave" in sculpt_low)
for word in ["machine-smooth", "cad-perfect", "glossy"]:
    check("  and refuses '%s'" % word, "never " + word in sculpt_low)
check("  and refuses a polished product render",
      "never a polished product render" in sculpt_low)
check("  the surface reads as just-worked",
      "worked by touch moments ago" in sculpt_low)


# Material identity does not lapse just because a scene is describing a
# gesture: every scene names the clay it is made of, so the verb never
# arrives without the material attached.
for base_id in SCULPT_WANT:
    check("  sculpt_%s names its material" % base_id,
          "clay" in scene_of[base_id].lower())


print("\n--- v2 rule 3: tension vocabulary, only where meant ---")
# The rounded-only language becomes conditional: angular is tension, round is
# calm. The prefix says both registers exist; the scenes decide which is
# which, and exactly one scene is under pressure.
check("the prefix makes form language follow feeling",
      "form language follows feeling" in sculpt_low)
check("  rounded for warm or calm",
      "soft, rounded, swelling volumes where the composition" in sculpt_low)
check("  angular for strained",
      all(w in sculpt_low for w in ["angular", "pinched", "wedged",
                                    "cracked", "jagged"]))
check("  and matte clay either way", "matte clay throughout" in sculpt_low)

TENSION = re.compile(r"\b(angular|pinched|wedge|wedged|wedge-shaped|jagged|"
                     r"cracked|cracks|crack|hard-cornered|sharp|fractured)\b")

# v2 had one strained scene out of eight and gated on that. v3's idioms are
# mostly expressive, so a simple tense/calm split would let the vocabulary
# everywhere and check nothing. The gate is on the FORM instead: three idioms
# are physically discontinuous — a thing broken, a thing on a point, a thing
# cracked open — and the hard-edge words are how you say that. The other five
# are continuous volumes, where the same words would just add spikes to a
# shape that is meant to read as soft, which is what the vocabulary is for.
HARD_EDGED = {"i_scattered", "i_on_edge", "i_lit_up"}
for base_id in SCULPT_WANT:
    scene = scene_of[base_id].lower()
    hits = sorted(set(TENSION.findall(scene)))
    if base_id in HARD_EDGED:
        check("  sculpt_%s breaks, so it may say so" % base_id, hits, "none")
    else:
        check("  sculpt_%s is one continuous volume, and stays soft"
              % base_id, not hits, str(hits))
check("  three of the eight are discontinuous, five are not",
      len(HARD_EDGED) == 3
      and len(set(SCULPT_WANT) - HARD_EDGED) == 5)


print("\n--- v2 rule 4: contrast, and something worth stopping on ---")
check("the backdrop is pushed away from the sculpture tones",
      "two steps deeper and less saturated than the sculpture tones"
      in sculpt_low)
check("  there is a rim light on the contour",
      "rim light picking out the contour" in sculpt_low)
check("  and a contact shadow grounding the form",
      "contact shadow anchoring the form" in sculpt_low)
check("  stated as separation at thumbnail size",
      "separates cleanly from its background at thumbnail size"
      in sculpt_low)
# Deeper, but still not the thing the whole v3 direction exists to escape.
check("  and a deeper backdrop is still not a dark one",
      "never a shadowed or low-key ground" in sculpt_low
      and "warm monochrome" in sculpt_low)
check("the composition has to be worth reading into",
      "enigmatic object" in sculpt_low
      and "read themselves into it" in sculpt_low)
check("  and the set has to vary",
      "vary the silhouettes strongly" in sculpt_low
      and "so no two read alike" in sculpt_low)

# Said once each, in the prefix, not pasted per scene — same reason the
# safe-area rule is one constant.
for phrase in ["two steps deeper", "rim light", "contact shadow",
               "enigmatic object"]:
    check("  '%s' is stated once, in the prefix" % phrase,
          sculpt_low.count(phrase) == 1
          and all(phrase not in scene_of[b].lower()
                  for b in SCULPT_WANT))


print("\n--- the figure ban, which is the reversal this style is ---")
# vector and clay go out of their way to PERMIT a face at two dots and a line.
# sculpt bans it outright, and that inversion is the direction — so it is
# asserted rather than assumed.
#
# Checked on the positive half only. The negatives necessarily say the words
# ("no human figures", "no faces"), and a whole-prompt search would flag the
# refusal as if it were a request. What must be clean is the text that ASKS
# for something: the prefix, the safe-area rule and the scene.
FIGURE = re.compile(
    r"\b(humans?|figures?|persons?|people|faces?|facial|eyes?|characters?|"
    r"creatures?|animals?|scenes?|rooms?|interiors?|furniture|tables?|"
    r"chairs?|couch|friends?|runner|hands?|fingers?|body|bodies|"
    r"portraits?|buildings?|notebooks?|mugs?|lamps?|cats?|clocks?|"
    r"heads?|busts?|skulls?|necks?|brows?|jaws?|noses?|profiles?)\b")

# The handmade brief needs the vocabulary of hands without ever asking for a
# hand: finger impressions are a surface, hand-sculpted is a process. Those
# phrases are subtracted before the ban runs, so the check does not have to
# choose between reading "finger impressions" as a violation and dropping
# "finger" from the list. It is an allowlist of exact phrases, not a hole in
# the pattern — the words still trip the ban anywhere else.
CRAFT = ["hand-sculpted", "hand-shaped", "shaped by hand", "human-touch",
         "finger impressions", "fingertip", "fingerprint", "finger marks",
         "press marks", "handmade", "hand-cut"]


def without_craft(text):
    for phrase in CRAFT:
        text = text.replace(phrase, " ")
    return text


# The allowlist is only safe if it did not neuter what it is carving out of.
probe = without_craft("a small human figure raising one hand, fingers spread")
check("subtracting craft vocabulary still leaves the ban intact",
      sorted(set(FIGURE.findall(probe)))
      == ["figure", "fingers", "hand", "human"],
      str(sorted(set(FIGURE.findall(probe)))))
check("  and the craft phrases themselves come back clean",
      not FIGURE.search(without_craft(
          "hand-sculpted clay with soft finger impressions and press marks")))

# One frame is exempt, and the exemption is named rather than inferred: the
# result page inlays the reader's radar on a clay cranium, so that frame has
# to be a head. Every other frame in every style is held to the ban, and the
# head is held to a narrower one of its own instead — checked below.
HEAD_EXEMPT = "sculpt_p_head_base"
for sample_id, text in sculpt_by_id.items():
    if sample_id == HEAD_EXEMPT:
        continue
    positive = without_craft("\n".join(text.split("\n")[:3]).lower())
    hits = sorted(set(FIGURE.findall(positive)))
    check("  %s asks for no figure, no scene, no prop" % sample_id,
          not hits, str(hits))

# The ban has to be able to catch a head, or exempting one frame from it
# would mean nothing.
check("the ban would catch a head anywhere else",
      sorted(set(FIGURE.findall("a clay head in profile, brow and jaw")))
      == ["brow", "head", "jaw", "profile"])
check("  and exactly one frame is exempt from it",
      len([f for f in sculpt_plan
           if f["base_id"] in v3.SCULPT_NEGATIVE_OVERRIDES]) == 1)


print("\n--- the head, the one declared exception ---")
head_prompt = sculpt_by_id[HEAD_EXEMPT]
check("it is drawn on the sculpt prefix like everything else",
      head_prompt.startswith(v3.SCULPT_STYLE)
      and head_prompt.count(v3.SAFE_AREA) == 1)
check("but on its own negatives",
      head_prompt.endswith(v3.SCULPT_HEAD_NEGATIVE)
      and v3.SCULPT_NEGATIVE not in head_prompt)
head_neg = v3.SCULPT_HEAD_NEGATIVE.lower()
for word in ["no eyes", "no mouth", "no lips", "no ear", "no nostril",
             "no eyebrow", "no hair of any kind", "no expression",
             "no realistic or detailed face", "no photographic likeness",
             "no recognisable person"]:
    check("  the head still refuses '%s'" % word, word in head_neg)
check("  and everything below the neck",
      "nothing below the neck" in head_neg
      and "no shoulders" in head_neg and "no second form" in head_neg)
check("  the profile is an edge, not a face",
      "a plain sculptural edge and nothing more" in head_neg)
# The whole point of the frame: a blank cranium for the radar to sit on.
head_scene = dict(v3.SCULPT_PREVIEW)["p_head_base"].lower()
check("the cranium is empty, which is what the overlay needs",
      "smooth, even, unbroken clay surface" in head_scene
      and "no features, no texture and no detail" in head_scene)
check("  and held clear of the frame edges",
      "held clear of every edge" in head_scene)
check("  no other frame claims the head negative",
      list(v3.SCULPT_NEGATIVE_OVERRIDES) == ["p_head_base"])


print("\n--- the totem block: a culmination frame, not a quiz card ---")
# The first totem came back reading as a vase, and the diagnosis was
# structural: the sculpt prefix is written for quiz cards — legible at tile
# size on a light ground, and quiet — which is the opposite of what the last
# frame in the product has to be. So the block stacks on top rather than
# replacing, and it applies to totems and nothing else.
totem_low = v3.TOTEM_STYLE.lower()
check("inner light is mandatory and named as such",
      "inner light, mandatory" in totem_low)
check("  the glow is emitted from inside the volume",
      "lit from within" in totem_low
      and "emitted from inside the volume" in totem_low)
check("  escaping through cracks, seams or an opening",
      all(w in totem_low for w in ["cracks", "seams", "opening",
                                   "molten core"]))
check("  with a bloom on the surrounding clay",
      "soft glow bloom" in totem_low)
# The failure it is written against: teal as paint rather than as light.
check("  and a painted teal surface is refused by name",
      "never a teal-painted surface" in totem_low)

check("the presentation is dramatic and dark",
      "dramatic presentation" in totem_low
      and "dimmed to a deep warm dusk" in totem_low)
check("  visibly darker than the quiz cards' own backdrop",
      "markedly darker than the light backdrop" in totem_low)
# The correction the first three draws forced. "Deep umbra ... alone in the
# dark" read as night and returned a glow floating in blackness with no clay
# in it, at luma 20-25 — darker than the backdrop's own colour. The block now
# says room, and the two phrases that produced night are gone.
check("  but a dimmed sweep, not night and not a place",
      "gallery at closing time, not night" in totem_low
      and "the same plain seamless sweep" in totem_low
      and "never black: the sweep keeps its own warm colour" in totem_low)
check("  and the phrasing that over-darkened it is gone",
      "alone in the dark" not in totem_low
      and "deep umbra" not in totem_low)
check("  the clay stays lit and readable as clay",
      "stays clearly lit and clearly readable as clay" in totem_low
      and "handmade marks" in totem_low)
check("  the glow adds to that light rather than replacing it",
      "adds to that light instead of replacing it" in totem_low)
check("  and the failure is named outright",
      "never a glowing shape floating in blackness" in totem_low)
# It asks for a dimmed backdrop, never for a place. The figure ban forbids
# environments in every sculpt frame and the totem block is held to it too.
check("  without asking for an environment to put it in",
      not re.search(r"\b(rooms?|interiors?|walls?|floors?)\b", totem_low))
check("  one spotlight, a rim light, a deep shadow",
      "single dramatic spotlight" in totem_low
      and "pronounced bright rim light" in totem_low
      and "deep soft shadow" in totem_low)
check("  museum-piece lighting, said plainly",
      "museum-piece lighting" in totem_low)
check("exclusivity is asked for, not implied",
      "exclusivity" in totem_low
      and "rare collectible artifact" in totem_low
      and "poster composition" in totem_low)
check("  and the pose-verb rule is restated at the top of its range",
      "pose-verb rule applies doubly" in totem_low
      and "static symmetrical object is the failure" in totem_low)

# The coupling, both ways. A totem that lost the block would come back plain;
# a quiz card that gained it would come back dark and unreadable at tile size.
check("the block is applied to the totem",
      v3.TOTEM_STYLE in sculpt_by_id["sculpt_p_totem_open_flame"])
check("  and to no other frame in the style",
      [f["base_id"] for f in sculpt_plan if v3.TOTEM_STYLE in f["prompt"]]
      == sorted(v3.TOTEM_IDS),
      str([f["base_id"] for f in sculpt_plan
           if v3.TOTEM_STYLE in f["prompt"]]))
check("  the quiz cards keep the light warm backdrop",
      all("warm monochrome" in sculpt_by_id["sculpt_" + b].lower()
          and v3.TOTEM_STYLE not in sculpt_by_id["sculpt_" + b]
          for b in SCULPT_WANT))
# Stacked, not swapped: a totem is a sculpt frame first.
check("a totem still carries the whole sculpt prefix",
      sculpt_by_id["sculpt_p_totem_open_flame"].startswith(v3.SCULPT_STYLE))
check("  and still carries the safe-area rule once",
      sculpt_by_id["sculpt_p_totem_open_flame"].count(v3.SAFE_AREA) == 1)
check("  and the handmade marks it inherits",
      "finger impressions" in
      sculpt_by_id["sculpt_p_totem_open_flame"].lower())
check("style_for stacks only for totems",
      v3.style_for("p_totem_open_flame", "sculpt") != v3.SCULPT_STYLE
      and v3.style_for("i_wound_up", "sculpt") == v3.SCULPT_STYLE
      and v3.style_for("s_morning_run", "vector") == v3.VECTOR_STYLE)


print("\n--- the totem is measured on its own band ---")
# The quiz floor and the totem block cannot both be right about the same
# frame: the block asks for a dark room and the floor exists to catch a frame
# that came back dark by accident. Three draws proved it — luma 20-25 against
# a floor of 90, all rejected. So the band is per frame class, and the totem's
# numbers are reasoned from what a correct totem is made of.
#
# Against PIL's own measures, umbra #241A10 is luma 27.8 / sat 141.7, lit
# terracotta #B4643C is luma 119.4 / sat 170.0, and a teal core #4EDDC4 is
# luma 175.4 / sat 165.0. A backdrop, a lit form and a core in the proportions
# the safe area allows land between luma 50 and 95 at sat 140-150.
check("the totem luma floor sits between bare umbra and a lit form",
      27.8 < v3.TOTEM_MIN_MEAN_LUMA < 49.7,
      "%.1f" % v3.TOTEM_MIN_MEAN_LUMA)
check("  and is pinned where it was reasoned to",
      v3.TOTEM_MIN_MEAN_LUMA == 38.0, "%.1f" % v3.TOTEM_MIN_MEAN_LUMA)
check("the totem saturation ceiling is pinned below the neon reading",
      v3.TOTEM_MAX_SATURATION == 235.0, "%.1f" % v3.TOTEM_MAX_SATURATION)
check("  with the correct range well under it",
      v3.TOTEM_MAX_SATURATION > 200)

quiz_band = v3.floor_for("sculpt", "i_wound_up")
totem_band = v3.floor_for("sculpt", "p_totem_open_flame")
check("the quiz-card band is untouched",
      quiz_band["min_luma"] == 90.0 and quiz_band["max_luma"] == 245.0
      and quiz_band["min_sd"] == 10.0 and quiz_band["max_sat"] is None,
      str(quiz_band))
check("  in every style", all(
    v3.floor_for(st)["min_luma"] == 90.0
    and v3.floor_for(st)["max_sat"] is None for st in v3.STYLES))
check("the totem band is dark-tolerant and colour-capped",
      totem_band["min_luma"] == v3.TOTEM_MIN_MEAN_LUMA
      and totem_band["max_sat"] == v3.TOTEM_MAX_SATURATION,
      str(totem_band))
check("  and only the totem gets it",
      [b for b in SCULPT_WANT + SCULPT_PREVIEW_WANT
       if v3.floor_for("sculpt", b)["max_sat"] is not None]
      == sorted(v3.TOTEM_IDS),
      str([b for b in SCULPT_WANT + SCULPT_PREVIEW_WANT
           if v3.floor_for("sculpt", b)["max_sat"] is not None]))
check("  the same ids the style block applies to",
      sorted(v3.TOTEM_IDS) == sorted(
          f["base_id"] for f in sculpt_plan
          if v3.TOTEM_STYLE in f["prompt"]))

# Both bounds, proved against the numbers a real render produces.
TOTEM = "p_totem_open_flame"
DUSK = (73.9, 46.0, 147.8)        # the mid-dusk composite: backdrop/form/core
check("a correct dusk totem passes", v3.sanity(DUSK, "sculpt", TOTEM)[0],
      v3.sanity(DUSK, "sculpt", TOTEM)[1])
check("  the darkest composition that still reads as a lit object passes",
      v3.sanity((49.7, 40.0, 150.7), "sculpt", TOTEM)[0])
check("  the brightest one does too",
      v3.sanity((94.3, 52.0, 137.7), "sculpt", TOTEM)[0])
# The lower bound: what the three rejected draws actually measured.
check("a near-black totem is rejected",
      not v3.sanity((22.0, 44.0, 210.0), "sculpt", TOTEM)[0])
check("  and so is a frame of bare backdrop with no lit form",
      not v3.sanity((27.8, 30.0, 141.7), "sculpt", TOTEM)[0])
# The upper bound: teal gone neon, which the quiz floor has no opinion on.
check("a neon-saturated totem is rejected",
      not v3.sanity((70.0, 45.0, 243.0), "sculpt", TOTEM)[0])
check("  even at a perfectly good exposure",
      not v3.sanity((80.0, 50.0, 240.0), "sculpt", TOTEM)[0])
check("  while the same saturation on a quiz card is nobody's business",
      v3.sanity((150.0, 40.0, 243.0), "sculpt", "i_wound_up")[0])
# And the quiz cards are judged exactly as before.
check("a dusk exposure on a quiz card is still rejected",
      not v3.sanity(DUSK, "sculpt", "i_wound_up")[0])
check("  and on a vector card", not v3.sanity(DUSK, "vector")[0])
check("sanity still defaults to the quiz band",
      v3.sanity(DUSK) == v3.sanity(DUSK, "vector", None))
check("an unmeasurable totem is still kept",
      v3.sanity(None, "sculpt", TOTEM)[0])


print("\n--- the three preview slots the funnel rewrite needs ---")
preview_by_id = {f["base_id"]: f["prompt"].lower() for f in preview_plan}
check("the totem is matter, a visible event and inner light",
      all(w in preview_by_id["p_totem_open_flame"]
          for w in ["upward-twisting", "teal glow at the very tip",
                    "colour climbs with the form"]))
check("  and reads as an emblem, like the cartographer totem did",
      "composed as an emblem" in preview_by_id["p_totem_open_flame"])
check("the climbing card is climbing",
      all(w in preview_by_id["p_chapter_climbing"]
          for w in ["climbing a slope", "tilted forward into the climb",
                    "clearly going up"]))
check("  with the teal at the point of contact, not as decoration",
      "teal mark sits where the form meets the slope"
      in preview_by_id["p_chapter_climbing"])
for base_id in SCULPT_PREVIEW_WANT:
    check("  sculpt_%s names its material" % base_id,
          "clay" in preview_by_id[base_id])

check("the safe-area rule itself is figure-free, so it is safe to share",
      not FIGURE.search(v3.SAFE_AREA.lower()))

neg_low = v3.SCULPT_NEGATIVE.lower()
for word in ["no human figures", "no people", "no busts", "no mannequins",
             "no hands", "no faces of any kind", "no eyes", "no characters",
             "no scenes", "no environments", "no rooms", "no furniture",
             "no buildings", "no text", "no letters", "no logos"]:
    check("  sculpt negatives refuse '%s'" % word, word in neg_low)
check("  and the ban is stated positively in the prefix too",
      "pure form only" in sculpt_low)

# The other two say the opposite, and still do.
check("vector still permits a character", "welcome" in v3.VECTOR_STYLE.lower())
check("clay still permits a character",
      "moulded in clay" in v3.CLAY_STYLE.lower())
check("  so the three negative lists are three different texts",
      len({v3.VECTOR_NEGATIVE, v3.CLAY_NEGATIVE, v3.SCULPT_NEGATIVE}) == 3)


print("\n--- and no dark-identity vocabulary in the sculpt set ---")
for sample_id, text in sculpt_by_id.items():
    hit = [w for w in DARK if w in text.lower()]
    check("  %s carries none of it" % sample_id, not hit, str(hit))
# v1 avoided the word "silhouette" to stay clear of the banned list. v2 needs
# it twice — the pose has to read in the silhouette, and the silhouettes have
# to vary across the set — so the list gave way instead, narrowed to the dark
# gallery's actual phrase. What must never appear is that phrase.
check("the prefix uses silhouette as a composition word",
      "readable in the silhouette alone" in sculpt_low
      and "vary the silhouettes" in sculpt_low)
check("  and never as the dark gallery's way of drawing a person",
      "flat silhouette" not in sculpt_low)


print("\n--- sculpt brings its own list, it does not borrow one ---")
# v2 kept the shared eight ids and swapped the scene text under them. v3 drops
# that: the idioms are not answers to the shared questions, so they get their
# own list and their own ids, and the per-id scene-replacement mechanism is
# gone with them — one override mechanism (clay's notes) rather than two.
check("sculpt is the only style with its own sample list",
      [st for st in sorted(v3.STYLES) if "samples" in v3.STYLES[st]]
      == ["sculpt"])
check("  and it is the eight idioms",
      [b for b, _ in v3.SCULPT_SAMPLES] == SCULPT_WANT,
      str([b for b, _ in v3.SCULPT_SAMPLES]))
check("  vector and clay still draw the shared list",
      all([f["base_id"] for f in v3.samples(st)] == WANT
          for st in ("vector", "clay")))
check("  the per-id scene-replacement mechanism is gone",
      not hasattr(v3, "SCULPT_SCENES")
      and all("scenes" not in spec for spec in v3.STYLES.values()))
check("  clay's notes still work, which is the one override left",
      v3.scene_for("s_morning_run", "SHARED", "clay").startswith("SHARED ")
      and v3.scene_for("s_morning_run", "SHARED", "vector") == "SHARED")
# A style with no list of its own falls back to the shared eight rather than
# drawing nothing, so a fourth style is one entry away from working.
check("  and a style without its own list falls back to the shared one",
      [f["base_id"] for f in v3.samples("vector")] == WANT)


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


print("\n--- sculpt's floor, pinned ---")
# v2 pushes the backdrop two steps deeper and less saturated, which lowers
# both mean luma and mean saturation. Neither floor moved, so the darkest and
# least colourful frame the brief asks for is checked against them here: the
# drain composition, muted grey-brown on a deeper sweep.
MUTED_DRAIN = (132.0, 33.0, 22.0)
check("the muted drain frame clears both floors",
      v3.sanity(MUTED_DRAIN, "sculpt")[0])
check("  with room to spare on luma", MUTED_DRAIN[0] > v3.MIN_MEAN_LUMA + 30)
check("  because a deeper backdrop is still not a dark one",
      "never a shadowed or low-key ground" in v3.SCULPT_STYLE.lower())
check("sculpt's colour floor is pinned at 10.0",
      v3.SCULPT_MIN_SATURATION == 10.0, "%.1f" % v3.SCULPT_MIN_SATURATION)
check("  below vector's, because a warm monochrome sweep is not flat art",
      v3.SCULPT_MIN_SATURATION < v3.MIN_SATURATION)
check("  and routed by the table, not by a branch",
      v3.min_saturation("sculpt") == v3.SCULPT_MIN_SATURATION
      and v3.MIN_SATURATION_BY_STYLE["sculpt"] == v3.SCULPT_MIN_SATURATION)
check("  every style is in the table",
      sorted(v3.MIN_SATURATION_BY_STYLE) == sorted(v3.STYLES),
      str(sorted(v3.MIN_SATURATION_BY_STYLE)))
# A style that forgets to add itself gets the strict floor, so the failure is
# a rejected frame and a look at the table, not a silently unchecked batch.
check("  and an unlisted style falls back to the strict one",
      v3.min_saturation("marble") == v3.MIN_SATURATION)

# The pale end of the sculpt set is the fog drift: cream clay over ochre
# mounds, mostly backdrop. It has to clear the floor.
PALE_SCULPT = (206.0, 24.0, 13.0)
check("a pale warm-monochrome render passes as sculpt",
      v3.sanity(PALE_SCULPT, "sculpt")[0])
check("  and would have been rejected as vector",
      not v3.sanity(PALE_SCULPT, "vector")[0])
# Terracotta and ochre read muted to the eye but are not low numbers, since
# saturation here is (max-min)/max and a warm tone spreads the channels wide.
check("a terracotta-on-peach render passes comfortably",
      v3.sanity((188.0, 42.0, 68.0), "sculpt")[0])

check("sculpt still rejects near-black",
      not v3.sanity((28.0, 30.0, 40.0), "sculpt")[0])
check("sculpt still rejects blank white",
      not v3.sanity((252.0, 2.0, 1.0), "sculpt")[0])
check("sculpt still rejects a flat wash",
      not v3.sanity((225.0, 3.0, 20.0), "sculpt")[0])
check("sculpt still rejects a colourless render",
      not v3.sanity((180.0, 50.0, 4.0), "sculpt")[0])
check("sculpt keeps an unmeasurable frame", v3.sanity(None, "sculpt")[0])


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

    # The totem band, on rendered frames rather than on tuples. The bands
    # above are equal-area, which overweights whatever is brightest; a totem
    # is mostly backdrop with a form in it, so these are built to the
    # proportions the safe-area rule actually leaves.
    def composite(parts):
        """parts = [(area share, (r, g, b))], top to bottom."""
        w, h = 1024, 1536
        img = Image.new("RGB", (w, h), parts[0][1])
        y = 0
        for share, colour in parts:
            band = max(1, int(h * share))
            img.paste(Image.new("RGB", (w, band), colour), (0, y))
            y += band
        out = _io.BytesIO()
        img.save(out, "PNG")
        return out.getvalue()

    TOTEM_ID = "p_totem_open_flame"

    def judged(parts, base_id=TOTEM_ID):
        _, frame = v3.to_webp(composite(parts), v3.FRAME)
        return v3.sanity(v3.measure(frame), "sculpt", base_id)

    DUSK_PARTS = [(.60, (90, 66, 48)), (.35, (180, 100, 60)),
                  (.05, (242, 192, 112))]
    DARKEST_OK = [(.72, (36, 26, 16)), (.23, (142, 74, 44)),
                  (.05, (78, 221, 196))]
    ok, note = judged(DUSK_PARTS)
    check("  a rendered dusk totem passes its own band", ok, note)
    ok, note = judged(DARKEST_OK)
    check("  and so does the darkest one that still reads as lit", ok, note)
    # The lower bound, against what the rejected draws actually looked like.
    ok, note = judged([(.80, (10, 8, 6)), (.16, (18, 16, 12)),
                       (.04, (78, 221, 196))])
    check("  a glow floating in blackness is rejected", not ok, note)
    ok, note = judged([(1.0, (36, 26, 16))])
    check("  and a frame of bare backdrop with no form is too", not ok, note)
    # The upper bound, isolated: well exposed and still wrong, which the luma
    # bound on its own would have waved through.
    ok, note = judged([(.40, (0, 200, 172)), (.35, (122, 46, 0)),
                       (.25, (46, 20, 0))])
    check("  a well-exposed neon frame is rejected on colour alone",
          not ok, note)
    check("    and it really was well exposed",
          v3.measure(v3.to_webp(composite(
              [(.40, (0, 200, 172)), (.35, (122, 46, 0)),
               (.25, (46, 20, 0))]), v3.FRAME)[1])[0]
          > v3.TOTEM_MIN_MEAN_LUMA)
    # And the quiz band is untouched by any of it.
    ok, note = judged(DUSK_PARTS, "i_wound_up")
    check("  the same dusk frame is still rejected as a quiz card",
          not ok, note)

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

code, out = run(["--style", "sculpt", "--dry-run"])
check("--style sculpt exits 0", code == 0, str(code))
check("  draws all eleven sculpt ids",
      all(("sculpt_" + i) in out
          for i in SCULPT_WANT + SCULPT_PREVIEW_WANT)
      and out.count("via 1024x1536") == 11)
check("  says which style it is running", "sculpt style" in out)
check("  prints the sculpt prefix and no other",
      v3.SCULPT_STYLE in out
      and v3.VECTOR_STYLE not in out and v3.CLAY_STYLE not in out)
check("  and wrote nothing", not os.path.exists(v3.OUT))

code, bare = run(["--style", "sculpt", "--only", "i_lit_up", "--dry-run"])
check("--only takes the bare idiom id under --style sculpt",
      code == 0 and bare.count("via 1024x1536") == 1
      and "sculpt_i_lit_up" in bare)
code, pref = run(["--style", "sculpt", "--only", "sculpt_i_lit_up",
                  "--dry-run"])
check("  and the prefixed id names the same frame",
      code == 0 and pref == bare)

code, out = run(["--style", "sculpt", "--only", "clay_s_weather_fog",
                 "--dry-run"])
check("another style's id is refused by a sculpt run", code == 2, str(code))
check("  and the message names the style it was refused for",
      "sculpt" in out and "clay_s_weather_fog" in out)

# The shared ids are the sharpest case: they are real ids in two other styles
# and mean nothing here, so a sculpt run must refuse them rather than draw
# something adjacent.
code, out = run(["--style", "sculpt", "--only", "s_weather_fog", "--dry-run"])
check("  and a shared id means nothing to sculpt now", code == 2, str(code))

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
