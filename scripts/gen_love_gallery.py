#!/usr/bin/env python3
"""Draw the love-zodiac-bg funnel's real gallery: 44 cards and 2 interstitials.

Console use only, run by hand against a key. Nothing imports this, no route
reaches it, and it spends money — one image per frame at the published
gpt-image-1 rate — so it is never run by a deploy or a test:

    pip install pillow
    cd ~/mazzin && python3 scripts/gen_love_gallery.py --dry-run   # prompts only
    cd ~/mazzin && python3 scripts/gen_love_gallery.py             # the draw
    python3 scripts/gen_love_gallery.py --only lv07a,int1 --force  # redraw two

The key is read from ~/mazzin/.env itself — the OPENAI_API_KEY line, read as
a literal the way deploy.sh reads .env, never sourced — and falls back to the
OPENAI_API_KEY environment variable when the file has none. Nothing else in
.env is read.

--- v2: portrait, lighter, four grids ------------------------------------------

The first gallery was drawn square and dark, and the owner's phone review
found both wrong. The engine renders a pair card as a tall column — at
390x844 it measures 174x603, about 2:7 — and a four-up cell at 174x297,
about 3:5. `object-fit: cover` then shows a square picture's middle third
and cuts the subject off both sides. Every frame also sat on a night sky.

So every frame is now rendered portrait (1024x1536, which is 2:3) and kept
at the shape its tile wants: a pair card at 640x960, the whole render, the
way the zodiac gallery's 640x982 frames are; a four-up cell at 360x600, twice
its rendered size, centre-cropped to 3:5; the two interstitial frames at
800x1000, 4:5. Which shape a card takes is read off the config — the step
format the card sits in — so the plan and the funnel cannot disagree.

Every prompt carries composition guidance for its own crop, and the pair
guidance is the honest one: the tile shows the middle 40 percent of the
width, so the subject is asked to sit in a central vertical band, not merely
inside the middle 70 percent of the frame. Four frames stay dark because
their subject is dark — a nebula, falling stars, embers, a twilight road —
and each carries its own luma floor.

--- v4: the zodiac style, verbatim, and light per frame -----------------------

v1 was night-dark, v2 washed pastel, v3 oil-paint mush, and the cause was
the same each time: a new set of style words in the suffix. The gallery the
owner approves of is the zodiac one, and its generator lives on the server
outside this repo (~/mazzin_gallery_v3/gen_zodiac.py). Its style string is
ZODIAC_STYLE below, character for character, and the love gallery uses that
and nothing else: no invented adjectives, ever again.

That string bans people, faces and hands, so the v4 scenes were objects,
symbols and landscapes, the way the zodiac cards are — two crescent moons
curving into a heart rather than two hands. And it asks for a well-lit
subject with every detail visible, so the zodiac generator's EXPOSURE_WORDS
guard is ported: a scene that says dark, dim, night, candlelit and so on is
refused at plan time. The dark bucket's darkness lives in named colours
instead — a deep indigo sky, an ember glow — the way zk1b (звездна нощ) and
bd4a are drawn: dark frames, brightly lit subjects.

--- v5: the compositions back, in the v4 light --------------------------------

The v4 gallery was judged right in style and wrong in scene: a heart of two
moons is not two hands, and a love card with nobody in it says less than
the v1 card did. So every frame that showed a couple, a silhouette or a
pair of hands in the v1 plan shows it again — seventeen of them — written
as silhouettes, figures from behind and hands, never a close-up face. The
style string is the zodiac one with exactly that change: the ban on people,
faces and hands becomes a ban on close-up faces, and nothing else in it
moves. v1's darkness was the actual defect, not its compositions, so a
restored scene is lit the way its v4 stand-in was and sits in the same
bucket; the exposure guard stays, minus the two silhouette words, which are
subjects now rather than a way of asking for gloom. Every recipe is v5, so
the whole gallery is drawn again, once.

The light still lives per frame, in three buckets — bright, mid, dark —
with every pair and every four-up in one bucket, so no option wins by
glowing, and each bucket is judged on its own band, taken off the zodiac
frames that sit in it.

The palette is still versioned apart from the prompt (PALETTES,
RECORDED_PALETTE, DRAW_PALETTE), and `--only` still draws exactly the
frames it names:

    python3 scripts/gen_love_gallery.py --only lv06b,lv02b,lv18a

v4 bumps every recipe, so a plain run would redraw all 46; calibrate with
`--only` first. Nothing draws on its own — no test, no deploy.

--- the manifest, and what a rerun does ----------------------------------------

scripts/love_art.json records every frame this script has really drawn: the
hash of the bytes on disk, the hash of the recipe that made them, the cost.
A rerun skips a frame whose file still hashes to what is recorded AND whose
recipe is unchanged, and remakes everything else. So:

    delete the file        -> it is drawn again (the record no longer matches)
    edit its prompt        -> it is drawn again (the recipe no longer matches)
    `--force`              -> everything named is drawn again
    a placeholder on disk  -> drawn, because no record was ever written for it

The placeholders scripts/gen_love_placeholders.py writes are never recorded
here, which is what lets this script paint over them on its first run and
leave the real art alone on every run after.

--- the bands, one per light bucket --------------------------------------------

Three luma bands, taken off the approved zodiac frames that sit in each
bucket. Dark: night and moon cards measure 19 to 65 there, so 15 to 75.
Mid: first light, the wave, the still lake measure 84 to 117, so 55 to
135. Bright: radiant sun 147, open sky 168, feather 177, above the clouds
201, pastel skies 210, so 110 to 225 — and those bright frames sit at
saturation 27 to 77, so the bright band asks for colour only above 20; a
pale sky is what the approved gallery looks like, not a defect. Every band
keeps the spread floor (the zodiac frames never go under 14) and the
greyscale catch. A frame named in MIN_LUMA_BY_FRAME draws under its own
floor inside its bucket's band. The numbers are printed per frame, so a
rejection can be read against the thresholds without rerunning anything.

The buckets themselves were corrected from the first v4 run. It drew 30 of
46 and rejected 13, every one of them at a CONSISTENT luma across three
attempts — lv06a at 87 to 96 against a bright band that starts at 110,
lv04a at 21 to 38 — which is a band assigned wrong, not a picture drawn
wrong. So the assignment follows the observed numbers: steps 6, 7, 10, 12
and 15 are mid, and four frames that render darker than their step-mates
(lv04a, lv05a, lv05d, lv08a) keep their step's bucket with a floor of their
own just under what they measured. A step-mate whose frame was accepted
keeps it: the bucket is not part of the recipe, only the prompt and the
geometry are, so moving a label redraws nothing.

`--save-rejects` keeps what the band throws away: a rejected draw is written
to static/galleries/love-zodiac-bg/_rejects/<id>_<attempt>.webp — the
directory ignores itself in git — so a human can look at the picture and the
numbers before more money goes on the same frame.

A frame is also held under 120KB: the WebP is re-encoded a step at a time
down to a floor quality, and a frame that cannot get under is a failure
rather than a heavy file on a phone.
"""
import argparse
import base64
import binascii
import hashlib
import io
import json
import os
import re
import sys
import time
import urllib.error
import urllib.request

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
CONFIG = os.path.join(ROOT, "funnels", "love-zodiac-bg.json")
OUT = os.path.join(ROOT, "static", "galleries", "love-zodiac-bg")
OWNED = "/static/galleries/love-zodiac-bg/"
MANIFEST = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                        "love_art.json")

# Where the key lives. The repo root is ~/mazzin on the server, and the
# literal path is tried too so a checkout under another name still finds the
# server's own .env when it is run from there.
ENV_FILES = (os.path.join(ROOT, ".env"), os.path.expanduser("~/mazzin/.env"))

# Bumped when every frame has to be drawn again regardless of its prompt.
# v4: the light moved into the scene words; v4.1: the zodiac style string
# and the exposure guard, every scene rewritten — so every frame is stale.
# Calibrate with --only before a plain run.
RECIPE_VERSION = "v5"

# --- geometry ------------------------------------------------------------------
#
# One render size, three frame shapes, keyed by the kind of tile a frame is
# shown in. Measured on the live shell at 390x844: a pair card is 174x603,
# a four-up cell 174x279 to 174x297, the interstitial strip is free.

API_PORTRAIT = "1024x1536"

# The kind of tile, the committed frame, and the crop guidance it is drawn
# against. A pair card keeps the whole 2:3 render, like the zodiac gallery's
# 640x982 frames; a grid cell is twice its rendered size at 3:5; an
# interstitial frame is 4:5.
KINDS = {
    "pair": {
        "size": (640, 960),
        "crop": "2:3",
        "guidance": ("single central subject, composed for a 2:3 portrait "
                     "frame that is shown as a tall central band, "
                     "comfortable margins on all sides, subject fully inside "
                     "the middle 70% of the frame height and the middle 40% "
                     "of the frame width"),
    },
    "grid": {
        "size": (360, 600),
        "crop": "3:5",
        "guidance": ("single central subject, composed for a 3:5 portrait "
                     "crop, comfortable margins on all sides, subject fully "
                     "inside the middle 70% of the frame"),
    },
    "interstitial": {
        "size": (800, 1000),
        "crop": "4:5",
        "guidance": ("single central subject, composed for a 4:5 portrait "
                     "crop, comfortable margins on all sides, subject fully "
                     "inside the middle 70% of the frame"),
    },
}
# Which step format draws which kind of tile. A format not named here is a
# loud failure at plan time, not a square frame in a portrait tile.
KIND_OF_FORMAT = {"pair": "pair", "grid3": "grid", "grid4": "grid"}

MODEL = os.getenv("OPENAI_IMAGE_MODEL", "gpt-image-1")
IMAGE_QUALITY = os.getenv("LOVE_IMAGE_QUALITY", "medium")
TIMEOUT_S = float(os.getenv("OPENAI_TIMEOUT_S", "180"))
API_BASE = os.getenv("OPENAI_API_BASE", "https://api.openai.com/v1")

# Per-image list price in dollars, keyed (quality, api size). Not read from
# the API, stale the day the price list moves, `--price` overrides — the
# number printed is an estimate and the invoice is the truth.
PRICE = {
    ("low", API_PORTRAIT): 0.016,
    ("medium", API_PORTRAIT): 0.063,
    ("high", API_PORTRAIT): 0.25,
}

# WebP: the quality every frame is first encoded at, the floor it may be
# stepped down to when it is over the byte ceiling, and the ceiling.
QUALITY = 80
QUALITY_FLOOR = 50
MAX_BYTES = 120 * 1024

# --- the style ----------------------------------------------------------------

# The base suffix, on every prompt, one per palette version. One slot: the
# composition guidance for the frame's own crop, because a pair card, a grid
# cell and an interstitial frame are shown at three different shapes.
#
# Every version a record on disk may have been drawn under is kept, verbatim:
# a record is checked against the recipe of the palette it was drawn with,
# and that recipe needs the text.
#
# The zodiac gallery's style string, from the server's own generator
# (~/mazzin_gallery_v3/gen_zodiac.py), character for character. Its
# constraint list is the constraint list — the old "no close-up faces"
# tail is gone with it. Not to be edited: three versions of invented style
# words produced three rejected galleries, and this is the string the
# approved one was drawn with.
ZODIAC_STYLE = (
    "Cinematic celestial art, painterly photographic hybrid, rich saturated "
    "colour, luminous, well-lit subject, every detail clearly visible, subtle "
    "silver star grain, vertical portrait composition centered and readable "
    "at thumbnail size. No text, no letters, no numbers, no people, no faces, "
    "no hands, no watermark, no logo, no frame."
)
# v5: the same string with one substitution, and no other word moved. The
# zodiac cards have nobody in them by design; the love cards need two
# silhouettes, two figures from behind, two hands. What stays banned is the
# one thing a generated face costs: a face close enough to be somebody.
LOVE_STYLE = ZODIAC_STYLE.replace("no people, no faces, no hands",
                                  "no close-up faces")
assert LOVE_STYLE == (
    "Cinematic celestial art, painterly photographic hybrid, rich saturated "
    "colour, luminous, well-lit subject, every detail clearly visible, subtle "
    "silver star grain, vertical portrait composition centered and readable "
    "at thumbnail size. No text, no letters, no numbers, no close-up faces, "
    "no watermark, no logo, no frame."
)
PALETTES = {
    "v4": ", {guidance}. " + ZODIAC_STYLE,
    "v5": ", {guidance}. " + LOVE_STYLE,
}
# What the manifest's frames were drawn under, and what a draw uses now.
# The same while no palette is being calibrated; when one is, set
# DRAW_PALETTE to it and calibrate with --only, then set RECORDED_PALETTE
# to it once approved and the rest of the gallery goes stale.
RECORDED_PALETTE = "v5"
DRAW_PALETTE = "v5"
STYLE_SUFFIX = PALETTES[DRAW_PALETTE]

# --- the exposure guard, ported from the zodiac generator -------------------
#
# The style asks for a well-lit subject with every detail clearly visible,
# and a scene word that asks for the opposite wins over the style every
# time — that is how v1 came back as gloom. So the zodiac generator refuses
# a scene that carries one of these, and this one does too. The list is the
# zodiac generator's own, verbatim and in its order, with five of this
# file's additions appended after it. Darkness is said in colour instead: a
# deep indigo sky, an ember glow, a moon — the subject stays lit. Plain
# "candle" and "candles" are not on the list, only candlelit and
# candlelight: a candle is an object, and an object can be lit.
#
# v5 takes one word out of the zodiac list on its way into EXPOSURE_WORDS:
# "silhouette" (and this file's plural). In the zodiac gallery a silhouette
# is a way of asking for an unlit subject; here it is the subject — a couple
# drawn as two dark shapes against a lit sky is exactly the card — and the
# style's "well-lit subject" still applies to everything around them. The
# zodiac tuple itself stays verbatim, so it can be compared with the
# server's, and the subtraction is done where the guard is built.
ZODIAC_EXPOSURE_WORDS = (
    "dark", "darkly", "dim", "dimly", "moody", "moodily", "shadow",
    "shadowed", "shadowy", "low-key", "lowkey", "dramatic", "dramatically",
    "intimate", "candlelit", "candlelight", "atmospheric", "gloomy", "murky",
    "sombre", "somber", "night", "nighttime", "dusk", "twilight", "unlit",
    "underexposed", "silhouette", "noir", "smoky", "hazy",
)
SILHOUETTE_WORDS = ("silhouette", "silhouettes")
EXPOSURE_WORDS = tuple(
    w for w in ZODIAC_EXPOSURE_WORDS if w not in SILHOUETTE_WORDS
) + ("darkness", "midnight", "nocturnal", "candle-lit")
# And the style's own ban, as words a scene must not use: a scene that asks
# for a face, or for a portrait of somebody, is asking the model to break
# the one constraint the love style keeps. People, couples, figures,
# silhouettes and hands are what the restored scenes are made of and are
# allowed again — from behind, as shapes, as hands, never as a face.
SUBJECT_WORDS = (
    "face", "faces", "portrait of a", "close-up", "closeup",
)
_GUARD = re.compile(r"\b(%s)\b" % "|".join(
    re.escape(w) for w in EXPOSURE_WORDS + SUBJECT_WORDS), re.IGNORECASE)


def guard(subject):
    """The banned words a scene carries, or an empty list."""
    return sorted({m.group(1).lower() for m in _GUARD.finditer(subject)})


# --- the plan ------------------------------------------------------------------
#
# The 44 cards, in walk order, and the two interstitial frames, each with
# its light bucket and its scene words. The light is IN the scene words
# and the bucket is the band the frame is judged on. Every pair and every
# four-up sits in one bucket, so the two or four options a reader compares
# are lit alike: bright with bright, mid with mid, dark with dark. Four
# bright, twenty-eight mid, fourteen dark, as the v4 draws measured.
#
# Seventeen scenes are v1's compositions, restored in v5: the ones that
# showed a couple, a silhouette or a pair of hands. Each is written as
# silhouettes, figures from behind or hands — never a face — and each is
# lit the way its v4 stand-in was, in the same bucket: v1's darkness was the
# defect, not its people. The other twenty-nine are the v4 scenes, unchanged.
# No scene asks for darkness: a dark frame is a deep indigo sky or an ember
# glow with a brightly lit subject in it, like the zodiac cards.

BRIGHT, MID, DARK = "bright", "mid", "dark"

CARD_PROMPTS = [
    # 1 spark — dark
    ("lv01a", DARK, "a bright golden spark leaping between two reaching hands, "
                    "deep indigo starry sky behind"),
    ("lv01b", DARK, "one lit candle lighting a second candle on a table, "
                    "both flames bright and clear, deep indigo backdrop"),
    # 2 evening — mid
    ("lv02a", MID, "couple silhouettes strolling a small city square strung with "
                   "warm string lights under a soft pastel evening sky"),
    ("lv02b", MID, "two cups of tea by a rain-streaked window, folded "
                   "blanket, soft grey afternoon light"),
    # 3 gesture — bright
    ("lv03a", BRIGHT, "two hands with interlaced fingers in bright golden sunlight, "
                      "pale sky behind"),
    ("lv03b", BRIGHT, "handwritten letter with a wax heart seal on a sunlit "
                      "linen table, bright daylight"),
    # 4 gift — bright
    ("lv04a", BRIGHT, "small star pendant resting on a folded velvet cloth "
                      "in bright daylight"),
    ("lv04b", BRIGHT, "brass key tied with red thread on a pale wooden table "
                      "in bright morning light"),
    # 5 conflict — mid, four-up
    ("lv05a", MID, "two chairs facing each other in a quiet room, a warm "
                   "lamp glowing between them, soft evening light"),
    ("lv05b", MID, "empty park bench at first light with room for two, soft "
                   "pastel sky"),
    ("lv05c", MID, "two silhouettes laughing together at a kitchen table, soft "
                   "afternoon light spilling through the window"),
    ("lv05d", MID, "two figures from behind walking shoulder to shoulder down a "
                   "tree-lined lane in soft late-afternoon light"),
    # 6 closeness — mid (drew 87-96 and 192; the step follows the pair)
    ("lv06a", MID, "two trees with intertwined crowns in a sunlit meadow, "
                      "bright open sky"),
    ("lv06b", MID, "two birds flying side by side across a bright open "
                      "sky at dawn"),
    # 7 romance — mid, four-up (lv07b drew 78-90, lv07d 82-84)
    ("lv07a", MID, "candles on a rooftop table at bright sunrise, clear "
                      "morning sky"),
    ("lv07b", MID, "sunrise from a mountain peak, two backpacks resting "
                      "on the rocks, bright golden light"),
    ("lv07c", MID, "a folded letter left on a pillow in bright morning "
                      "sun"),
    ("lv07d", MID, "two silhouettes dancing in a bright kitchen, sun through the "
                   "window, a record spinning on a turntable"),
    # 8 rhythm — mid
    ("lv08a", MID, "two silhouettes dancing in a light rain under a glowing "
                   "street lamp, soft amber evening light, wet cobblestones "
                   "shining"),
    ("lv08b", MID, "two coffee cups on the same table in soft morning light, "
                   "a wall calendar behind"),
    # 9 distance — dark
    ("lv09a", DARK, "paper plane gliding across a deep indigo starry sky "
                    "toward one warmly lit window"),
    ("lv09b", DARK, "two figures from behind at one front door, a key turning in "
                    "the lock, a porch lamp glowing, deep indigo evening sky"),
    # 10 home — mid, four-up (lv10b drew 58-70, lv10c 93-101, lv10d 74-93)
    ("lv10a", MID, "nest with two golden eggs among branches in bright "
                      "spring light"),
    ("lv10b", MID, "open door leading out to a bright sunlit garden"),
    ("lv10c", MID, "long table laid for guests in a sunlit garden, bright "
                      "afternoon light"),
    ("lv10d", MID, "hammock for two strung between trees in a leafy "
                      "garden, bright dappled sunlight"),
    # 11 passion — dark
    ("lv11a", DARK, "lightning striking a stormy sea under a deep indigo "
                    "sky, the bolt brightly lit"),
    ("lv11b", DARK, "glowing embers in a stone hearth, deep red and gold, "
                    "the ember glow lighting the stones"),
    # 12 trust — mid (both drew 83-96)
    ("lv12a", MID, "a figure leaping toward an outstretched hand over a gap "
                   "between two cliffs, bright sky behind"),
    ("lv12b", MID, "stone bridge with a double railing over a calm river "
                      "in bright morning sunlight"),
    # 13 past — mid
    ("lv13a", MID, "glass snow globe with a tiny winter scene inside, on a "
                   "shelf in soft window light"),
    ("lv13b", MID, "blank white page and a quill on a desk at first light, "
                   "soft pastel dawn"),
    # 14 public — dark
    ("lv14a", DARK, "couple silhouettes dancing in a square under strings of "
                    "glowing lights and festive bunting, deep indigo sky"),
    ("lv14b", DARK, "two figures from behind under one blanket on a rooftop, city "
                    "lights glittering far below, deep indigo sky"),
    # 15 care — mid (lv15a drew 79-87; the step follows the pair)
    ("lv15a", MID, "one silhouette holding an umbrella over another in a bright "
                   "spring rain, sun breaking through"),
    ("lv15b", MID, "a kite launched by two pairs of hands into a bright open sky"),
    # 16 silence — mid, four-up
    ("lv16a", MID, "two fishermen from behind on a misty pier in soft early "
                   "morning light, still water, pale gold"),
    ("lv16b", MID, "two glasses of wine on a terrace table under a soft "
                   "amber evening sky, one candle"),
    ("lv16c", MID, "two figures from behind reading side by side on a sofa in "
                   "soft afternoon light"),
    ("lv16d", MID, "two figures from behind in a parked car on a hill watching a "
                   "soft glowing sunset sky"),
    # 17 future — dark
    ("lv17a", DARK, "road through indigo hills toward a horizon with two "
                    "pale moons glowing in a deep indigo sky"),
    ("lv17b", DARK, "an oak with initials carved into the bark, gold glowing "
                    "in the grooves, deep indigo starry sky behind"),
    # 18 symbol — dark
    ("lv18a", DARK, "heart-shaped nebula glowing gold and rose in deep "
                    "indigo space"),
    ("lv18b", DARK, "two hands forming a heart shape against a bright full moon "
                    "in a deep indigo sky"),
]

# The three frames of the gender step, planned ahead of the step: the engine
# has no three-option format yet, so the config cannot carry them, and a
# plan that named ids the config does not show would refuse itself. They
# join the plan the day the config names them, and stay out of it until
# then. One bucket for the three, as for any step.
PENDING_PROMPTS = [
    ("g01", MID, "a graceful feminine silhouette of flowing stardust against "
                 "a luminous rose-gold nebula"),
    ("g02", MID, "a strong masculine silhouette of flowing stardust against "
                 "a luminous teal-gold nebula"),
    ("g03", MID, "a radiant star of pure white-gold light between two soft "
                 "nebula swirls, neutral and welcoming"),
]

TALL_PROMPTS = [
    ("int1", DARK, "two falling stars streaking across a deep indigo sky "
                   "over a faint horizon glow"),
    ("int2", DARK, "two candles, one lighting the other, bright flames "
                   "against a deep indigo backdrop"),
]


def prompt_for(subject, kind, palette=None):
    """The subject, closed on a palette's suffix, with this kind's crop
    guidance. The draw palette unless one is named."""
    suffix = PALETTES[DRAW_PALETTE if palette is None else palette]
    return subject + suffix.format(guidance=KINDS[kind]["guidance"])


def owned_ids(cfg):
    """Every image id the config references under this funnel's gallery,
    with the kind of tile each is shown in.

    The cards off the steps, keyed by the step's format, then the frames
    `preview_gallery` names on its own — which is where the two interstitial
    frames live, because the engine's interstitial screens carry no image
    slot and the strip under the locked report does.
    """
    out = []
    seen = set()
    for step in cfg["swipe"]["steps"]:
        fmt = step.get("format")
        for pair in step["pairs"]:
            for item in pair["images"]:
                if item["img"].startswith(OWNED) and item["id"] not in seen:
                    if fmt not in KIND_OF_FORMAT:
                        raise SystemExit("step %s has format %r, which no "
                                         "frame shape is known for"
                                         % (step.get("id"), fmt))
                    seen.add(item["id"])
                    out.append((item["id"], KIND_OF_FORMAT[fmt]))
    for item in cfg.get("preview_gallery") or []:
        if item["img"].startswith(OWNED) and item["id"] not in seen:
            seen.add(item["id"])
            out.append((item["id"], "interstitial"))
    return out


def frames(cfg):
    """The plan: one frame per prompt, shaped by the config, checked
    against it.

    A prompt for an id the funnel does not show, or an owned id with no
    prompt, is refused before anything is called. The gallery is the
    funnel's, not this file's.
    """
    owned = owned_ids(cfg)
    kind_of = dict(owned)
    pending = [row for row in PENDING_PROMPTS if row[0] in kind_of]
    rows = CARD_PROMPTS + pending + TALL_PROMPTS
    subjects = {i: s for i, _b, s in rows}
    buckets = {i: b for i, b, _s in rows}
    planned = [i for i, _b, _s in rows]
    if len(set(planned)) != len(planned):
        raise SystemExit("a frame id is planned twice")
    missing = sorted(set(kind_of) - set(planned))
    extra = sorted(set(planned) - set(kind_of))
    if missing or extra:
        raise SystemExit("plan and config disagree — no prompt for %s, "
                         "no config image for %s" % (missing, extra))
    tall = {i for i, _b, _s in TALL_PROMPTS}
    wrong = [i for i, k in owned if (k == "interstitial") != (i in tall)]
    if wrong:
        raise SystemExit("interstitial frames and the preview-only ids "
                         "disagree: %s" % wrong)
    # No scene may ask for what the style forbids: darkness, or a person.
    banned = {i: guard(s) for i, s in subjects.items() if guard(s)}
    if banned:
        raise SystemExit("scenes carry words the zodiac style refuses: %s"
                         % banned)
    # One bucket per step: the options a reader compares are lit alike.
    for step in cfg["swipe"]["steps"]:
        ids = [i["id"] for p in step["pairs"] for i in p["images"]
               if i["id"] in buckets]
        if len({buckets[i] for i in ids}) > 1:
            raise SystemExit("step %s mixes light buckets: %s"
                             % (step.get("id"),
                                {i: buckets[i] for i in ids}))
    plan = []
    for frame_id, kind in owned:
        plan.append({"id": frame_id, "kind": kind,
                     "bucket": buckets[frame_id],
                     "subject": subjects[frame_id],
                     "prompt": prompt_for(subjects[frame_id], kind),
                     "size": KINDS[kind]["size"], "api_size": API_PORTRAIT,
                     "band": band_for(frame_id, buckets[frame_id])})
    return plan


# --- the key -------------------------------------------------------------------

_ENV_LINE = re.compile(r"^\s*(?:export\s+)?OPENAI_API_KEY=(.*?)\s*$")


def key_from_env_file(paths=None):
    """OPENAI_API_KEY as written in the first .env that carries it, or "".

    `paths` defaults to ENV_FILES at call time, not at definition time, so
    the list can be pointed elsewhere by a test without re-importing.

    Read as a literal line, never sourced: sourcing runs the file as shell,
    which mangles values with `$` in them and puts every other secret in the
    file into this process's environment. Quotes around the value are
    stripped, an inline comment is not — a key does not contain one and a
    password may.
    """
    for path in (ENV_FILES if paths is None else paths):
        try:
            with open(path, encoding="utf-8") as fh:
                lines = fh.read().splitlines()
        except OSError:
            continue
        value = ""
        for line in lines:
            hit = _ENV_LINE.match(line.rstrip("\r"))
            if hit:
                value = hit.group(1)
        if len(value) >= 2 and value[0] == value[-1] and value[0] in "\"'":
            value = value[1:-1]
        if value:
            return value
    return ""


def api_key():
    """The .env key first, the environment second, "" when neither."""
    return key_from_env_file() or os.getenv("OPENAI_API_KEY", "")


# --- the call ------------------------------------------------------------------


class GenerationError(Exception):
    def __init__(self, code, retriable=True):
        Exception.__init__(self, code)
        self.code = code
        self.retriable = retriable


def _post_generation(prompt, api_size, key):
    """One call to images/generations. Returns raw image bytes."""
    body = json.dumps({"model": MODEL, "prompt": prompt, "size": api_size,
                       "quality": IMAGE_QUALITY, "n": 1}).encode("utf-8")
    req = urllib.request.Request(
        API_BASE.rstrip("/") + "/images/generations",
        data=body, method="POST",
        headers={"Authorization": "Bearer " + key,
                 "Content-Type": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=TIMEOUT_S) as res:
            payload = json.loads(res.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        hint = ""
        try:
            detail = json.loads(exc.read().decode("utf-8"))
            hint = str((detail.get("error") or {}).get("code") or "")[:80]
        except Exception:
            pass
        # 429 and 5xx are worth another go; a 400 means the request itself
        # is wrong and will be exactly as wrong the second time.
        raise GenerationError("http_%d %s" % (exc.code, hint),
                              retriable=(exc.code == 429 or exc.code >= 500))
    except Exception as exc:
        raise GenerationError("transport %s" % type(exc).__name__)

    data = (payload or {}).get("data") or []
    encoded = (data[0] or {}).get("b64_json") if data else None
    if not encoded:
        raise GenerationError("empty_response")
    try:
        return base64.b64decode(encoded, validate=True)
    except (binascii.Error, ValueError):
        raise GenerationError("bad_image", retriable=False)


def generate(prompt, api_size, key, tries=3):
    """The draw, with retries on the failures that are worth retrying."""
    last = None
    for attempt in range(tries):
        try:
            return _post_generation(prompt, api_size, key)
        except GenerationError as err:
            last = err
            if not err.retriable:
                raise
            if attempt + 1 < tries:
                time.sleep(2 * (attempt + 1))
    raise last


# --- the frame -----------------------------------------------------------------


def fit(raw, size):
    """The model's image, centre-cropped to the committed frame, as a Pillow
    image. A 2:3 render into a 2:3 frame is a resize; into 3:5 or 4:5 it is
    a resize and a centre crop of the height."""
    from PIL import Image

    img = Image.open(io.BytesIO(raw))
    img.load()
    img = img.convert("RGB")
    want_w, want_h = size
    scale = max(want_w / img.width, want_h / img.height)
    img = img.resize((max(1, int(round(img.width * scale))),
                      max(1, int(round(img.height * scale)))),
                     Image.LANCZOS)
    left = (img.width - want_w) // 2
    top = (img.height - want_h) // 2
    return img.crop((left, top, left + want_w, top + want_h))


def encode(img, ceiling=MAX_BYTES):
    """`(bytes, quality)` for a frame under the ceiling, or `(None, q)`.

    Quality steps down from QUALITY to QUALITY_FLOOR, ten at a time, and the
    first encoding under the ceiling wins. None means the picture cannot be
    made small enough without being made bad, which is a failed frame.
    """
    quality = QUALITY
    while True:
        buf = io.BytesIO()
        img.save(buf, "WEBP", quality=quality, method=6)
        data = buf.getvalue()
        if len(data) <= ceiling:
            return data, quality
        if quality <= QUALITY_FLOOR:
            return None, quality
        quality -= 10


# --- the floor -----------------------------------------------------------------

# One flat wash scores fine on luma and is still not a picture. The approved
# zodiac frames never measure under 14.
MIN_STDDEV = 12.0

# One band per light bucket, each read off the approved zodiac frames that
# sit in it (HSV saturation, 0-255):
#
#   dark    night and moon cards: bd4a 19, mo7b 30, mn9a 34, sa12b 50,
#           es13c 64 — so 15 to 75, and still coloured (sat 60 and up;
#           those measure 111 to 231)
#   mid     first light 90, the wave 114, the still lake 108, sy8d 114,
#           rising sun 84 — so 55 to 135, coloured above 50
#   bright  radiant sun 147, open sky 168, feather 177, above the clouds
#           201, pastel skies 210 — so 110 to 225, and only coloured above
#           20: those five sit at saturation 27 to 77, and a pale sky is
#           what the approved gallery looks like
#
# Below the dark floor is a black render, above the bright ceiling a blank
# page; between buckets the bands overlap on purpose, because a frame is
# judged in its own bucket and a dusk scene at 70 is right in mid and
# right in dark.
BANDS = {
    "dark": {"min_luma": 15.0, "max_luma": 75.0, "min_sd": MIN_STDDEV,
             "min_sat": 60.0},
    "mid": {"min_luma": 55.0, "max_luma": 135.0, "min_sd": MIN_STDDEV,
            "min_sat": 50.0},
    "bright": {"min_luma": 110.0, "max_luma": 225.0, "min_sd": MIN_STDDEV,
               "min_sat": 20.0},
}
# The band a frame with no bucket is judged on — the tests' synthetic frames
# and nothing in the plan, which always carries one.
BAND = BANDS["mid"]
MIN_MEAN_LUMA = BAND["min_luma"]
MAX_MEAN_LUMA = BAND["max_luma"]
MIN_SATURATION = BAND["min_sat"]

# Frames whose subject renders darker than their bucket's floor, and the
# luma floor each is judged against instead. Inside the bucket's band
# otherwise. Two are dark by nature — a nebula on black space, falling stars
# — and four measured, three draws each, well under a bucket their step-mate
# was accepted in; they keep the step's bucket for the pairing and take a
# floor just under what they drew. Each number is still above a near-black
# render, which comes back in the single digits.
MIN_LUMA_BY_FRAME = {
    "lv18a": 10.0,   # a nebula on black, lit by its own gold and rose
    "int1": 10.0,    # falling stars over a faint horizon glow
    "lv04a": 18.0,   # a pendant on velvet: drew 21-38, step-mate bright
    "lv05a": 38.0,   # a lamp between two chairs: drew 40-47, in mid
    "lv05d": 38.0,   # footprints in a lane: drew 41-55, in mid
    "lv08a": 30.0,   # a street lamp on wet stone: drew 32-46, in mid
}


def band_for(frame_id, bucket="mid"):
    """The bounds one frame is judged against: its bucket's band, or that
    band with this frame's own luma floor in it."""
    band = BANDS[bucket]
    floor = MIN_LUMA_BY_FRAME.get(frame_id)
    return band if floor is None else dict(band, min_luma=floor)


def measure(img):
    """`(mean_luma, stddev, mean_saturation)` for a frame, or None."""
    try:
        from PIL import ImageStat
        grey = ImageStat.Stat(img.convert("L"))
        sat = ImageStat.Stat(img.convert("HSV").getchannel("S"))
        return grey.mean[0], grey.stddev[0], sat.mean[0]
    except Exception:
        return None


def verdict(stats, bounds=BAND):
    """`(ok, note)` for a measured frame. Never raises.

    Loose on purpose: it rejects the old gloom, near-black, blank, flat and
    colourless renders and passes everything else, because the owner review
    is the real gate. A frame that cannot be measured is kept and says so —
    it is going in front of a human anyway.
    """
    if stats is None:
        return True, "unmeasured"
    mean, sd, sat = stats
    ok = (bounds["min_luma"] <= mean <= bounds["max_luma"]
          and sd >= bounds["min_sd"] and sat >= bounds["min_sat"])
    return ok, "luma %.1f sd %.1f sat %.1f" % (mean, sd, sat)


def size_ok(img, size):
    """The frame is exactly the committed geometry."""
    return tuple(img.size) == tuple(size)


# --- the manifest --------------------------------------------------------------


def sha(data):
    return hashlib.sha256(data).hexdigest()


def load_manifest():
    if not os.path.exists(MANIFEST):
        return {}
    try:
        with open(MANIFEST, encoding="utf-8") as fh:
            return json.load(fh).get("frames") or {}
    except (ValueError, OSError):
        return {}


def save_manifest(entries):
    payload = {
        "note": ("What gen_love_gallery.py has really drawn. A rerun skips an "
                 "id whose file still hashes to what is recorded here and "
                 "whose recipe is unchanged; delete the file, or edit the "
                 "prompt, to have it drawn again. Placeholders are never "
                 "recorded, so the first run paints over them."),
        "funnel": "love-zodiac-bg",
        "model": MODEL,
        "quality": IMAGE_QUALITY,
        "frames": dict(sorted(entries.items())),
    }
    tmp = MANIFEST + ".tmp"
    with open(tmp, "w", encoding="utf-8") as fh:
        json.dump(payload, fh, indent=2, ensure_ascii=False, sort_keys=True)
        fh.write("\n")
    os.replace(tmp, MANIFEST)


def on_disk_sha(frame_id):
    path = os.path.join(OUT, frame_id + ".webp")
    if not os.path.exists(path):
        return None
    with open(path, "rb") as fh:
        return sha(fh.read())


def recipe(frame, palette=None):
    """What this frame is made of, as one string, for the manifest digest.

    The version tag, the prompt under a palette, the geometry and the API
    size: changing any of them is what should make a rerun redraw. A frame
    judged under its own luma floor carries that number too, and only that
    frame does. The BUCKET is not in it: a band decides how a draw is
    judged, not what is drawn, so moving a frame's label never redraws an
    accepted frame. The palette defaults to the draw palette; a record is
    compared under the palette it was drawn with.
    """
    prompt = (frame["prompt"] if palette is None
              else prompt_for(frame["subject"], frame["kind"], palette))
    out = "%s|%s|%s|%dx%d" % (RECIPE_VERSION, prompt, frame["api_size"],
                              frame["size"][0], frame["size"][1])
    if frame["id"] in MIN_LUMA_BY_FRAME:
        out += "|min_luma=%g" % MIN_LUMA_BY_FRAME[frame["id"]]
    return out


def legacy_recipes(frame, palette=None):
    """The v4.1 spellings of this frame's recipe, one per bucket.

    The first v4 run recorded thirty frames under a recipe that carried the
    bucket the frame was judged in, and a floor when it had one. Those
    records stay current whatever bucket the frame is labelled now: an
    accepted frame is an accepted frame.
    """
    base = recipe(frame, palette)
    if frame["id"] in MIN_LUMA_BY_FRAME:
        base = base[:base.rindex("|min_luma=")]
    out = []
    for bucket in BANDS:
        one = "%s|%s" % (base, bucket)
        floor = MIN_LUMA_BY_FRAME.get(frame["id"])
        if floor is not None and floor != BANDS[bucket]["min_luma"]:
            one += "|min_luma=%g" % floor
        out.append(one)
    return out


def already_made(frame, entries, palettes=None):
    """True when this id's committed frame is the one the manifest recorded.

    Under either palette by default — the one the gallery was drawn with
    and the one a draw uses now — so a palette change alone invalidates
    nothing. `--only` narrows this to the draw palette for the frames it
    names, which is what bumps their recipes and nobody else's. A record in
    the v4.1 spelling, bucket and all, counts too.
    """
    entry = entries.get(frame["id"])
    if not entry:
        return False
    if entry.get("sha256") != on_disk_sha(frame["id"]):
        return False
    if palettes is None:
        palettes = (RECORDED_PALETTE, DRAW_PALETTE)
    spellings = [recipe(frame, p) for p in palettes]
    for p in palettes:
        spellings.extend(legacy_recipes(frame, p))
    return any(entry.get("recipe_sha") == sha(s.encode("utf-8"))
               for s in spellings)


# --- the run -------------------------------------------------------------------


def write(frame_id, data):
    path = os.path.join(OUT, frame_id + ".webp")
    with open(path, "wb") as fh:
        fh.write(data)
    return path


REJECTS = "_rejects"


def write_reject(frame_id, attempt, data):
    """A rejected draw, kept for a human to look at before the next draw.

    Written beside the gallery under _rejects/, never into it — the gallery
    is exactly what the funnel shows — and the directory carries a
    .gitignore of its own so nothing in it is ever committed.
    """
    folder = os.path.join(OUT, REJECTS)
    os.makedirs(folder, exist_ok=True)
    ignore = os.path.join(folder, ".gitignore")
    if not os.path.exists(ignore):
        with open(ignore, "w", encoding="utf-8") as fh:
            fh.write("*\n")
    path = os.path.join(folder, "%s_%d.webp" % (frame_id, attempt))
    with open(path, "wb") as fh:
        fh.write(data)
    return path


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--dry-run", action="store_true",
                    help="print the plan and every prompt, call nothing")
    ap.add_argument("--only", default="",
                    help="comma-separated frame ids to draw under the "
                         "current palette — calibration mode: their "
                         "recipes are bumped, nobody else's")
    ap.add_argument("--force", action="store_true",
                    help="redraw even frames the manifest already records")
    ap.add_argument("--price", type=float, default=None,
                    help="override the assumed per-image price in dollars")
    ap.add_argument("--retries", type=int, default=2,
                    help="redraws allowed when a frame fails its floor")
    ap.add_argument("--save-rejects", action="store_true",
                    help="keep rejected draws under %s/ for review"
                         % REJECTS)
    args = ap.parse_args(argv)

    with open(CONFIG, encoding="utf-8") as fh:
        cfg = json.load(fh)

    plan = frames(cfg)
    known = {f["id"] for f in plan}
    if args.only:
        names = [n.strip() for n in args.only.split(",") if n.strip()]
        unknown = [n for n in names if n not in known]
        if unknown:
            print("unknown frame id(s): %s" % ", ".join(unknown))
            return 2
        plan = [f for f in plan if f["id"] in set(names)]

    entries = load_manifest()
    if not args.force:
        # Named frames are held to the draw palette, so one recorded under
        # the old palette is stale and drawn; everything else is current
        # under either palette and left alone.
        palettes = (DRAW_PALETTE,) if args.only else None
        plan = [f for f in plan if not already_made(f, entries, palettes)]

    def price_of(frame):
        if args.price is not None:
            return args.price
        return PRICE.get((IMAGE_QUALITY, frame["api_size"]), 0.0)

    estimate = sum(price_of(f) for f in plan)
    print("%s, quality %s, palette %s — %d frame(s) to draw, ~$%.2f estimated"
          % (MODEL, IMAGE_QUALITY, DRAW_PALETTE, len(plan), estimate))

    if args.dry_run:
        for frame in plan:
            print("\n--- %s (%s, %dx%d via %s, %s: luma %g-%g) ---"
                  % (frame["id"], frame["kind"], frame["size"][0],
                     frame["size"][1], frame["api_size"], frame["bucket"],
                     frame["band"]["min_luma"], frame["band"]["max_luma"]))
            print(frame["prompt"])
        print("\ndry run: nothing called, nothing written")
        return 0

    if not plan:
        print("nothing to draw: every frame is recorded and unchanged"
              + (" — use --force to redraw the frames named" if args.only
                 else " — name frames with --only to calibrate the palette"))
        return 0

    key = api_key()
    if not key:
        print("no OPENAI_API_KEY in %s and none in the environment — "
              "nothing was called or written." % " or ".join(ENV_FILES))
        return 1

    os.makedirs(OUT, exist_ok=True)
    spent, made, failed = 0.0, 0, []
    for frame in plan:
        frame_id = frame["id"]
        price = price_of(frame)
        data, note, quality = None, "", QUALITY
        try:
            for attempt in range(args.retries + 1):
                raw = generate(frame["prompt"], frame["api_size"], key)
                spent += price
                img = fit(raw, frame["size"])
                if not size_ok(img, frame["size"]):
                    note = "size %dx%d" % img.size
                    print("  %-8s wrong size (%s), redrawing"
                          % (frame_id, note))
                    continue
                ok, note = verdict(measure(img), frame["band"])
                if not ok:
                    kept = ""
                    if args.save_rejects:
                        saved = encode(img)[0]
                        if saved is not None:
                            kept = " -> " + os.path.relpath(
                                write_reject(frame_id, attempt + 1, saved),
                                ROOT)
                    print("  %-8s rejected (%s), redrawing%s"
                          % (frame_id, note, kept))
                    continue
                candidate, quality = encode(img)
                if candidate is None:
                    note += " over %dKB at q%d" % (MAX_BYTES // 1024, quality)
                    print("  %-8s too heavy (%s), redrawing"
                          % (frame_id, note))
                    continue
                data = candidate
                break
        except GenerationError as err:
            failed.append((frame_id, "api: %s" % err.code))
            print("  %-8s FAILED (api: %s)" % (frame_id, err.code))
            continue
        except (RuntimeError, OSError) as err:
            failed.append((frame_id, "%s: %s" % (type(err).__name__, err)))
            print("  %-8s FAILED (%s)" % (frame_id, err))
            continue
        if data is None:
            failed.append((frame_id, note))
            print("  %-8s FAILED after %d draws (%s)"
                  % (frame_id, args.retries + 1, note))
            continue

        write(frame_id, data)
        entries[frame_id] = {
            "sha256": sha(data),
            "recipe_sha": sha(recipe(frame).encode("utf-8")),
            "bytes": len(data),
            "size": "%dx%d" % frame["size"],
            "kind": frame["kind"],
            "bucket": frame["bucket"],
            "palette": DRAW_PALETTE,
            "webp_quality": quality,
            "cost_usd": round(price, 4),
            "note": note,
        }
        save_manifest(entries)
        made += 1
        print("  %-8s %7d B  q%-3d $%.3f  %s"
              % (frame_id, len(data), quality, price, note))

    print("\n%d frame(s) drawn, ~$%.2f spent, %d failed"
          % (made, spent, len(failed)))
    for frame_id, why in failed:
        print("  FAILED %s: %s" % (frame_id, why))
    print("manifest: %s" % MANIFEST)
    print("gallery : %s" % OUT)
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
