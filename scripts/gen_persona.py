#!/usr/bin/env python3
"""Draw the persona funnel's production gallery.

Console use only, run by hand against a key. Nothing imports this and no route
reaches it. Its outputs are committed, so a deploy never builds anything and
the site never depends on Pillow or on an API key being present:

    pip install pillow
    export OPENAI_API_KEY=sk-...
    cd ~/mazzin && python3 scripts/gen_persona.py

    python3 scripts/gen_persona.py --dry-run       # plan + prompts, no calls
    python3 scripts/gen_persona.py --only now_lit_up  # redraw named frames
    python3 scripts/gen_persona.py --force            # ignore the manifest
    python3 scripts/gen_persona.py --check-head    # measure the cranium

funnels/persona.json is the source of truth for what exists. Every id, label,
form description and colour comes off the config, so a walk redesign changes
the art by changing the config and rerunning — there is no second list of
frames to keep in step, which is the same rule the placeholder generator
follows.

The style is not here. It lives in scripts/persona_style.py, which the sampler
imports too, so the brief that took ten draws to settle cannot be half-updated.

--- four kinds of frame, and only two of them cost money -------------------

Quiz cards and totems are drawn. Everything else is either promoted from a
render the owner already approved, or composited here from frames that exist:

  44 quiz cards   drawn — the sculpt prefix plus the card's own form
                  description and colours, straight off the config
   7 totems       drawn — the totem block on top of the sculpt prefix, with
                  form language derived from each persona's essence
   1 totem        PROMOTED from the approved sample, not redrawn
   1 head base    PROMOTED from the approved sample, not redrawn
   8 share cards  composited, no API call: the persona's own totem on the
                  result page's dusk ground, with type
   1 og card      composited, no API call: a lineup of quiz shapes and the
                  funnel's own hook line

The no-text rule in the style binds what the MODEL draws, and it binds it
absolutely — a model asked for a word produces a smear that looks like one.
Type composited here is ours, is exact, and is the only way a share card can
carry a name at all.

--- what makes a rerun safe -------------------------------------------------

The record of what has really been drawn lives in a manifest beside this
script rather than being inferred from the directory, because every id has a
file from the moment the placeholders ran and "skip what exists" would draw
nothing, ever.

The manifest carries, per id, the sha256 of the bytes on disk, the prompt
digest, the size and what the frame cost. A rerun skips an id whose file still
hashes to what the manifest recorded — so a rerun after a crash resumes rather
than restarting, and a rerun after somebody edits a frame by hand leaves that
edit alone rather than painting over it. `--force` overrides. `--only` names
ids.

Deliberately not a size heuristic. "Regenerate anything under eight kilobytes"
would work today, on the placeholders this replaces, and would quietly start
redrawing real frames the day one of them compressed well.
"""
import argparse
import hashlib
import json
import os
import re
import shutil
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import persona_style                                          # noqa: E402
from persona_style import (                                   # noqa: E402
    API_PORTRAIT, FRAME, GenerationError, IMAGE_QUALITY, MODEL, PRICE,
    QUALITY, SCULPT_HEAD_NEGATIVE, SCULPT_NEGATIVE, SCULPT_STYLE, assemble,
    generate, measure, to_webp, totem_style, verdict,
)

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
CONFIG = os.path.join(ROOT, "funnels", "persona.json")
OUT = os.path.join(ROOT, "static", "galleries", "persona")
OWNED = "/static/galleries/persona/"
SAMPLES = os.path.join(ROOT, "static", "galleries", "persona_v3_samples")
MANIFEST = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                        "persona_art.json")

CARD = (1200, 630)

# --- the promoted pair -------------------------------------------------------
#
# Two renders the owner approved during the sampler rounds. They are copied
# rather than redrawn, for the obvious reason and for a less obvious one: the
# head is the only frame in the style permitted to be a head, and drawing it
# again is drawing a lottery ticket against a negative list written to make it
# hard. The approved bytes are the approved bytes.
PROMOTE = {
    "head_base": "sculpt_p_head_base",
    "totem_igniter_outer": "sculpt_p_totem_open_flame",
}

# --- the totems --------------------------------------------------------------
#
# Seven to draw; the eighth is the promoted open flame. The form language is
# derived from each persona's essence in the config rather than invented here,
# so a persona renamed or reworded upstream is a totem redrawn rather than a
# totem that quietly still means the old thing.
#
# Every one leads with a gesture, because the pose-verb rule governs totems
# doubly, and every one puts the light through the whole form rather than at a
# point — which is the note the seventh draw failed on.
TOTEM_FORMS = {
    "igniter_inner": (
        "A dense clay form coiled in on itself and holding, wound tight and "
        "leaning off vertical, its turns pressed close. Smouldering teal "
        "veins run deep between every turn and glow up out of the gaps, "
        "brightest where the coil is tightest. Burning slowly, and not going "
        "out."),
    "keeper_outer": (
        "A massive clay mass planted square on the ground, wide at the foot "
        "and rising heavy and unmoved, its flanks carved in long vertical "
        "folds. Bright teal seams open along the whole base where the weight "
        "meets the ground and glow outward through fine fissures climbing "
        "the flanks. Immovable, and lit from underneath."),
    "keeper_inner": (
        "A low settled clay form spread wide and sunk into the ground it "
        "rests on, its mass carried downward rather than up. Teal veins run "
        "down through the form and out of its underside, continuing into the "
        "ground as glowing roots that spread away beneath it. Holding from "
        "below."),
    "feeler_outer": (
        "A cresting clay wave caught at the moment it turns over, rising and "
        "curling forward with the whole face of it leaning into the break. A "
        "brilliant teal crest-line runs the entire length of the curl and "
        "spills down the face in luminous rivulets. Arriving, and about to "
        "land."),
    "feeler_inner": (
        "A long smooth clay form running low and level, unhurried, its "
        "surface calm and its ends tapering away. One bright teal vein runs "
        "the whole length of it deep inside the volume, showing through the "
        "clay as a steady band of light with a soft bloom around it. Moving "
        "underneath, where it does not show."),
    "thinker_outer": (
        "A tall upright clay column standing and reaching, narrowing as it "
        "rises and opening at the top into a radiant crown of teal veins "
        "that fan outward and throw their light wide across the sweep. Fine "
        "lit fissures climb the shaft to feed it. Seen from a long way off."),
    "thinker_inner": (
        "A clay arc bent attentively forward over a broad unrolled wave of "
        "clay spread open beneath it, studying it. A soft teal glow gathers "
        "in the fold where the arc leans closest, and fine veins run back up "
        "the arc from it. Quiet, patient, and already further on than it "
        "looks."),
}


# An element the config already wrote an article onto — "the gap", "the
# contact" — must not get a second one. Three cards carried one and the prompt
# read "in the the gap", which is a small thing that a model is entitled to
# read as emphasis or as a typo, and either way it is not what the frame meant
# to say.
#
# Fixed here rather than in the three config strings, because "the gap" is the
# natural English name for that element and the next person to write one will
# reach for the same wording. The generator is what should be robust to it.
ARTICLED = re.compile(r"^(the|a|an)\s", re.I)


def colour_phrase(colour):
    """One colour, as the prompt should say it."""
    element = colour["element"]
    lead = "in " if ARTICLED.match(element) else "in the "
    return "%s (%s) %s%s" % (colour["name"], colour["hex"], lead, element)


# --- the pair steps draw tall ------------------------------------------------
#
# A two-up tile is very tall and very narrow — about 174x604 at 390px, and
# 174x570 once the label bar is taken off the bottom, which is an aspect of
# 0.305. A 3:4 render shown whole inside that leaves three fifths of the tile
# empty, and shown by `cover` loses three fifths of its width. Neither is a
# picture worth looking at, so the pair art is drawn tall instead and the tile
# fills itself from it.
#
# 600x900 is a 2:3 output, which is exactly what the model returns at
# 1024x1536 — so unlike every other frame in this gallery, a pair render is
# not cropped by the generator at all.
FRAME_TALL = (600, 900)

PAIR_NOTE = (
    "Composed for a tall narrow frame — a vertical form with generous plain "
    "backdrop above and below; the backdrop is part of the composition."
    # The sentence above is the brief's. This one is added because the
    # geometry needs it and the brief's does not cover it: the tile is
    # narrower in aspect than even a 2:3 render, so what `cover` removes is
    # WIDTH, not height — 27% off each side at 390px. Backdrop above and
    # below does not protect against that; backdrop at the sides does, and
    # the sculpt prefix's own safe area only reserves 15%.
    " Leave the sides as generous as the top and bottom: the form occupies "
    "the central third of the width, with wide plain backdrop left and right "
    "of it, so the frame can be cropped hard to a narrower shape and lose "
    "nothing but backdrop."
)


def pair_ids(cfg):
    """Every card on a two-up step, from the config's own formats.

    Derived rather than listed: the brief named four steps and guessed ten
    cards, the config says four steps and eight, and the config is what the
    walk actually draws.
    """
    return {item["id"]
            for step in cfg["swipe"]["steps"] if step.get("format") == "pair"
            for pair in step["pairs"] for item in pair["images"]}


def rgb_words(colors):
    """The frame's own three colours, as the prompt should say them."""
    return ", ".join(colour_phrase(c) for c in colors)


def quiz_prompt(item, tall=False):
    """A quiz card: the sculpt prefix, the config's own words, its colours.

    A two-up card also carries the tall-composition note, which is what makes
    its prompt — and so its manifest recipe — differ from the frame already on
    disk, so exactly those eight replan and the other thirty-six do not.
    """
    scene = item["form"]
    if tall:
        scene += " " + PAIR_NOTE
    return assemble(
        SCULPT_STYLE,
        scene + " Within the palette, lean this frame's colour "
        "toward: %s." % rgb_words(item["colors"]),
        SCULPT_NEGATIVE)


def totem_prompt(persona_id, name, essence):
    """A totem: the totem block stacked on the prefix, plus its own form."""
    return assemble(
        totem_style(),
        "%s This is %s: %s" % (TOTEM_FORMS[persona_id], name, essence),
        SCULPT_NEGATIVE)


# --- the work list -----------------------------------------------------------


def personas(cfg):
    """`(id, name, essence)` for the eight, in config order."""
    prof = cfg["result_copy"]["profile"]
    return [("%s_%s" % (a, e), prof["subtypes"][a][e], prof["essence"][a][e])
            for a in ("igniter", "keeper", "feeler", "thinker")
            for e in ("outer", "inner")]


def frames(cfg):
    """Every frame this generator owns, in the order it draws them.

    A quiz card pointing anywhere but this gallery belongs to another funnel
    and is dropped here rather than skipped later, so the count this prints is
    the count it owns.
    """
    out, seen = [], set()
    tall = pair_ids(cfg)
    for step in cfg["swipe"]["steps"]:
        for pair in step["pairs"]:
            for item in pair["images"]:
                if item["id"] in seen or not item["img"].startswith(OWNED):
                    continue
                seen.add(item["id"])
                is_tall = item["id"] in tall
                out.append({"id": item["id"], "kind": "quiz",
                            "size": FRAME_TALL if is_tall else FRAME,
                            "api_size": API_PORTRAIT,
                            "band": persona_style.QUIZ_BAND,
                            "prompt": quiz_prompt(item, is_tall)})

    for persona_id, name, essence in personas(cfg):
        frame_id = "totem_" + persona_id
        if frame_id in PROMOTE:
            out.append({"id": frame_id, "kind": "promote",
                        "size": FRAME, "from": PROMOTE[frame_id]})
            continue
        out.append({"id": frame_id, "kind": "totem",
                    "size": FRAME, "api_size": API_PORTRAIT,
                    "band": persona_style.TOTEM_BAND,
                    "prompt": totem_prompt(persona_id, name, essence)})

    out.append({"id": "head_base", "kind": "promote", "size": (800, 800),
                "from": PROMOTE["head_base"]})

    for card in (cfg.get("share_cards") or []):
        out.append({"id": "share_" + card["id"], "kind": "share",
                    "size": CARD, "persona": card["id"],
                    "name": card.get("persona") or card["id"]})

    out.append({"id": "og", "kind": "og", "size": CARD})
    return out


# --- the compositor ----------------------------------------------------------
#
# Everything below is Pillow and costs nothing. It runs on frames that already
# exist, so a share card is a view of the totem the reader was given rather
# than a second drawing of it that might disagree.

UMBRA = (36, 26, 16)
SWEEP = (243, 227, 204)
CREAM = (243, 227, 204)
SAND = (194, 171, 144)
TEAL = (78, 221, 196)

# A fixed font, chosen once and named, because "whatever the system has"
# makes the output depend on the machine that ran it. Bold for the name, the
# regular cut for the small line under it.
FONTS = [
    ("/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
     "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf"),
    ("/usr/share/fonts/truetype/liberation/LiberationSans-Bold.ttf",
     "/usr/share/fonts/truetype/liberation/LiberationSans-Regular.ttf"),
]


def fonts():
    """`(bold path, regular path)`, or None when the machine has neither.

    Refused rather than fallen back on: Pillow's default is a bitmap face at
    one small size, and a share card set in it would ship looking broken
    rather than looking different.
    """
    for bold, regular in FONTS:
        if os.path.exists(bold) and os.path.exists(regular):
            return bold, regular
    return None


def spotlight(size, centre, radius, colour, strength):
    """A soft radial pool, built small and scaled up.

    Built at a sixteenth and resized rather than computed per pixel: the
    result is a gradient either way, this is two orders of magnitude faster,
    and LANCZOS on a smooth field is deterministic.
    """
    from PIL import Image

    w, h = size
    small = (max(1, w // 16), max(1, h // 16))
    mask = Image.new("L", small, 0)
    px = mask.load()
    cx, cy = centre[0] / 16.0, centre[1] / 16.0
    r = max(1.0, radius / 16.0)
    for y in range(small[1]):
        for x in range(small[0]):
            d = (((x - cx) ** 2 + (y - cy) ** 2) ** 0.5) / r
            px[x, y] = 0 if d >= 1 else int(round(strength * (1 - d) ** 2))
    mask = mask.resize(size, Image.LANCZOS)
    return Image.new("RGB", size, colour), mask


def fit(img, box):
    """`img` scaled to fit inside `box`, keeping its aspect."""
    from PIL import Image

    bw, bh = box
    scale = min(bw / img.width, bh / img.height)
    return img.resize((max(1, int(round(img.width * scale))),
                       max(1, int(round(img.height * scale)))), Image.LANCZOS)


def fit_text(draw, text, font_path, size, width, floor=34):
    """The largest size at or below `size` that fits `text` into `width`.

    Steps down two points at a time and stops at a floor: a name that will not
    fit even there is a naming problem rather than a layout one, and silently
    setting it in six-point type would hide that.
    """
    from PIL import ImageFont

    while size > floor:
        font = ImageFont.truetype(font_path, size)
        if draw.textbbox((0, 0), text, font=font)[2] <= width:
            return font
        size -= 2
    return ImageFont.truetype(font_path, floor)


def share_card(totem_path, name):
    """One share card: the persona's totem, lit, on the result page's ground.

    Deliberately the same presentation the result page gives it — dusk ground,
    a spotlight from above — because the card is the first thing a stranger
    sees of this product and it should be the page they are about to land on.
    """
    from PIL import Image, ImageDraw, ImageFont

    face = fonts()
    if not face:
        raise RuntimeError("no usable font on this machine")
    bold, regular = face

    card = Image.new("RGB", CARD, UMBRA)
    glow, mask = spotlight(CARD, (CARD[0] // 3, 40), CARD[1] * 1.15,
                           (92, 66, 42), 150)
    card.paste(glow, (0, 0), mask)

    art = Image.open(totem_path)
    art.load()
    art = fit(art.convert("RGB"), (330, 470))
    art_x, art_y = 118, (CARD[1] - art.height) // 2
    shadow, smask = spotlight(
        CARD, (art_x + art.width // 2, art_y + art.height + 6), 210,
        (12, 8, 4), 190)
    card.paste(shadow, (0, 0), smask)
    card.paste(art, (art_x, art_y))

    draw = ImageDraw.Draw(card)
    text_x = art_x + art.width + 76
    # Shrink to fit rather than trusting one size. Three of the eight names
    # overflow at 62px — "The Quiet Cartographer" by two hundred pixels — and
    # an overflowing name on a share card is the one place a defect is
    # guaranteed an audience.
    name_font = fit_text(draw, name, bold, 62, CARD[0] - text_x - 48)
    draw.text((text_x, 250), name, font=name_font, fill=CREAM)
    draw.text((text_x, 332), "Which shape are you?",
              font=ImageFont.truetype(regular, 30), fill=SAND)
    draw.line([(text_x, 392), (text_x + 64, 392)], fill=TEAL, width=3)
    draw.text((text_x, 414), "mazzin.com/persona",
              font=ImageFont.truetype(regular, 24), fill=SAND)
    return card


def og_card(shape_paths, headline):
    """The share card for the funnel itself: a lineup, on the quiz's own sweep.

    The quiz ground rather than the result ground, because this is the page it
    links to — somebody arriving here has not taken anything yet.
    """
    from PIL import Image, ImageDraw, ImageFont

    face = fonts()
    if not face:
        raise RuntimeError("no usable font on this machine")
    bold, regular = face

    card = Image.new("RGB", CARD, SWEEP)
    glow, mask = spotlight(CARD, (CARD[0] // 2, 0), CARD[1] * 1.3,
                           (247, 226, 204), 170)
    card.paste(glow, (0, 0), mask)

    shapes = []
    for path in shape_paths:
        img = Image.open(path)
        img.load()
        shapes.append(fit(img.convert("RGB"), (208, 278)))
    gap = 26
    total = sum(s.width for s in shapes) + gap * (len(shapes) - 1)
    x = (CARD[0] - total) // 2
    top = 96
    for shape in shapes:
        card.paste(shape, (x, top))
        x += shape.width + gap

    draw = ImageDraw.Draw(card)
    font = ImageFont.truetype(bold, 46)
    width = draw.textbbox((0, 0), headline, font=font)[2]
    draw.text(((CARD[0] - width) // 2, 452), headline, font=font,
              fill=(43, 30, 18))
    small = ImageFont.truetype(regular, 26)
    sub = "mazzin.com/persona"
    width = draw.textbbox((0, 0), sub, font=small)[2]
    draw.text(((CARD[0] - width) // 2, 520), sub, font=small,
              fill=(122, 101, 82))
    return card


def encode(img):
    """WebP bytes, at the quality every other frame in this gallery uses."""
    import io as _io

    buf = _io.BytesIO()
    img.save(buf, "WEBP", quality=QUALITY, method=6)
    return buf.getvalue()


# --- the head's cranial zone -------------------------------------------------


def head_extent(path):
    """The head's own bounding box in PLATE space, as percentages.

    `cranial_zone` above finds the smooth field on the crown, which is what
    the inlay used to sit in. It does not sit there any more: the radar is
    drawn across the whole head now, so the box that positions it is derived
    from the head itself rather than from the bald patch on top of it.

    Two things this has to get right, and an earlier draft got neither.

    The backdrop is a gradient. It is lighter on the left than on the right,
    so a reference sampled from one edge reads the far edge as an object and
    returns a head as wide as the frame. Both edges are sampled and the
    backdrop is interpolated across the row.

    The plinth is not the head. The widest row in this render is the teal
    base at the bottom, so a box fitted to "the widest part" fits the stand.
    The scan stops at the neck, found as the first row below the skull whose
    span has narrowed well inside the widest one.
    """
    from PIL import Image

    img = Image.open(path).convert("RGB")
    width, height = img.size
    px = img.load()
    side = width                        # the plate is square, cover-cropped
    top_crop = (height - side) // 2

    def span(y):
        left = [sum(px[x, y][c] for x in range(2, 10)) / 8.0 for c in range(3)]
        right = [sum(px[x, y][c] for x in range(width - 10, width - 2)) / 8.0
                 for c in range(3)]
        first = last = None
        run = 0
        for x in range(width):
            t = x / float(width - 1)
            ref = [left[c] + (right[c] - left[c]) * t for c in range(3)]
            gap = sum((px[x, y][c] - ref[c]) ** 2 for c in range(3)) ** 0.5
            if gap > 26:
                run += 1
                if run >= 6:
                    if first is None:
                        first = x - 5
                    last = x
            else:
                run = 0
        return (first, last) if first is not None else None

    rows = {}
    for y in range(top_crop, top_crop + side):
        found = span(y)
        if found:
            rows[y] = found
    if not rows:
        return None
    order = sorted(rows)
    crown = order[0]
    widest = max((rows[y][1] - rows[y][0], y) for y in order
                 if y < crown + side * 0.6)[1]
    limit = 0.62 * (rows[widest][1] - rows[widest][0])
    neck = next((y for y in order
                 if y > widest and (rows[y][1] - rows[y][0]) < limit),
                order[-1])
    band = [y for y in order if crown <= y <= neck]
    left = min(rows[y][0] for y in band)
    right = max(rows[y][1] for y in band)
    return {"left": 100.0 * left / side,
            "top": 100.0 * (crown - top_crop) / side,
            "width": 100.0 * (right - left) / side,
            "height": 100.0 * (neck - crown) / side}


def cranial_zone(path, cells=40):
    """Where the smooth empty field sits in the head render, in PLATE space.

    result_persona.css positions the radar inlay against this frame with four
    hardcoded numbers, and those numbers were written against a mockup rather
    than against the render. This measures the render instead.

    Two things make that less obvious than it sounds.

    The background is smooth too. A first version of this looked for the
    largest low-variance square anywhere and confidently returned the
    top-left corner of the sweep, which is not a cranium, and reported a
    26-point drift that did not exist. So background cells are excluded
    first, by colour: the sweep is whatever the frame's own border is made
    of, and a cell close to it is not part of the head.

    And the plate is square while the render is 3:4. `.pr-head-plate` sets
    `aspect-ratio: 1 / 1` and the image is `object-fit: cover`, so the
    browser scales to width and crops equally off the top and bottom — a
    quarter of the height on a 600x800 frame. The CSS percentages are
    percentages of what survives that crop, so this reports in the same space
    rather than in the render's, which are not the same numbers and would
    otherwise be compared as if they were.

    Reported, never applied. A generator that silently moved the stylesheet's
    numbers could reposition the reader's own diagram without anybody
    deciding to.
    """
    from PIL import Image, ImageStat

    img = Image.open(path)
    img.load()
    rgb = img.convert("RGB")
    w, h = rgb.size

    # `object-fit: cover` into a square: scale to the shorter side and crop
    # the longer one equally at both ends.
    side = min(w, h)
    off_x, off_y = (w - side) // 2, (h - side) // 2
    rgb = rgb.crop((off_x, off_y, off_x + side, off_y + side))
    grey = rgb.convert("L")

    step = side / float(cells)

    def box(gx, gy):
        return (int(gx * step), int(gy * step),
                int((gx + 1) * step), int((gy + 1) * step))

    # The sweep, taken from the border of what is actually displayed.
    border = []
    for i in range(cells):
        for gx, gy in ((i, 0), (i, cells - 1), (0, i), (cells - 1, i)):
            border.append(ImageStat.Stat(rgb.crop(box(gx, gy))).mean)
    sweep = [sum(c[i] for c in border) / len(border) for i in range(3)]

    good = [[False] * cells for _ in range(cells)]
    for gy in range(cells):
        for gx in range(cells):
            cell = box(gx, gy)
            if ImageStat.Stat(grey.crop(cell)).stddev[0] >= 6.0:
                continue
            mean = ImageStat.Stat(rgb.crop(cell)).mean
            far = sum((mean[i] - sweep[i]) ** 2 for i in range(3)) ** 0.5
            good[gy][gx] = far > 24.0

    # Largest all-good square, by the usual dynamic-programming scan, with the
    # search held to the upper part of the plate. Without that it finds the
    # cheek or the neck, which are just as smooth and just as much not the
    # cranium — a cranium is by definition the top of a head, and saying so is
    # cheaper and more honest than a shape model.
    ceiling = int(cells * 0.62)
    size = [[0] * cells for _ in range(cells)]
    best = None
    for gy in range(ceiling):
        for gx in range(cells):
            if not good[gy][gx]:
                continue
            size[gy][gx] = (1 if gy == 0 or gx == 0 else
                            1 + min(size[gy - 1][gx], size[gy][gx - 1],
                                    size[gy - 1][gx - 1]))
            if best is None or size[gy][gx] > best[2]:
                best = (gy, gx, size[gy][gx])
    if not best or best[2] < 4:
        return None
    bottom, right, n = best
    return {"top": 100.0 * (bottom - n + 1) / cells,
            "left": 100.0 * (right - n + 1) / cells,
            "width": 100.0 * n / cells, "height": 100.0 * n / cells}


# What result_persona.css claims, so --check-head can compare. These are the
# measurement this tool took, adopted after the first render made it checkable:
# the old top 13% / left 26% / 48% was written against a mockup and put the box
# over the ear with its left edge off the brow.
CSS_INLAY = {"top": 0.8, "left": 15.3, "width": 68.0,
             "height": 68.0}


# --- the manifest ------------------------------------------------------------


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
        "note": ("What gen_persona.py has really drawn, promoted or "
                 "composited. A rerun skips an id whose file still hashes to "
                 "what is recorded here, so a hand-edited frame is left "
                 "alone, not painted over."),
        "version": "v3",
        "model": MODEL,
        "quality": IMAGE_QUALITY,
        "frames": dict(sorted(entries.items())),
    }
    tmp = MANIFEST + ".tmp"
    with open(tmp, "w", encoding="utf-8") as fh:
        json.dump(payload, fh, indent=2, sort_keys=True)
        fh.write("\n")
    os.replace(tmp, MANIFEST)


def on_disk_sha(frame_id):
    path = os.path.join(OUT, frame_id + ".webp")
    if not os.path.exists(path):
        return None
    with open(path, "rb") as fh:
        return sha(fh.read())


def recipe(frame):
    """What this frame is made of, as one string, for the manifest digest.

    A prompt for a drawn frame; a source id for a promoted one; the inputs for
    a composited one. Changing any of them is what should make a rerun redraw.
    """
    if frame["kind"] in ("quiz", "totem"):
        return frame["prompt"]
    if frame["kind"] == "promote":
        return "promote:" + frame["from"]
    if frame["kind"] == "share":
        return "share:%s:%s" % (frame["persona"], frame["name"])
    return "og:" + OG_HEADLINE


def already_made(frame, entries):
    """True when this id's committed frame is the one the manifest recorded."""
    entry = entries.get(frame["id"])
    if not entry:
        return False
    if entry.get("sha256") != on_disk_sha(frame["id"]):
        return False
    return entry.get("recipe_sha") == sha(recipe(frame).encode("utf-8"))


OG_HEADLINE = "Shapes designed to read you."
OG_SHAPES = ["now_lit_up", "now_wound_up", "now_scattered", "chapter_climbing"]


# --- the run -----------------------------------------------------------------


def write(frame_id, data):
    path = os.path.join(OUT, frame_id + ".webp")
    with open(path, "wb") as fh:
        fh.write(data)
    return path


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--dry-run", action="store_true",
                    help="print the plan and every prompt, call nothing")
    ap.add_argument("--only", default="",
                    help="comma-separated frame ids to make")
    ap.add_argument("--force", action="store_true",
                    help="remake even frames the manifest already records")
    ap.add_argument("--price", type=float, default=None,
                    help="override the assumed per-image price in dollars")
    ap.add_argument("--retries", type=int, default=2,
                    help="redraws allowed when a frame fails its floor")
    ap.add_argument("--check-head", action="store_true",
                    help="measure the head render's cranial zone and stop")
    args = ap.parse_args(argv)

    with open(CONFIG, encoding="utf-8") as fh:
        cfg = json.load(fh)

    if args.check_head:
        path = os.path.join(OUT, "head_base.webp")
        if not os.path.exists(path):
            print("no head_base.webp on disk yet")
            return 1
        extent = head_extent(path)
        if extent:
            print("head : left %(left).1f%% top %(top).1f%% "
                  "%(width).1fx%(height).1f%% of the plate" % extent)
            # The box the stylesheet should carry: a square the width of the
            # head, centred on it and nudged to sit inside the plate.
            box = extent["width"]
            want_left = extent["left"] + (extent["width"] - box) / 2.0
            want_top = max(0.8, extent["top"] + extent["height"] / 2.0
                           - box / 2.0)
            print("want : left %.1f%% top %.1f%% %.1fx%.1f%%"
                  % (want_left, want_top, box, box))
        print("css  : left %(left).1f%% top %(top).1f%% "
              "%(width).1fx%(height).1f%%" % CSS_INLAY)
        if not extent:
            print("render: no head found — look at it by eye")
            return 1
        want = {"left": want_left, "top": want_top,
                "width": box, "height": box}
        drift = max(abs(want[k] - CSS_INLAY[k]) for k in CSS_INLAY)
        print("worst drift: %.1f percentage points" % drift)
        print("nothing was changed — .pr-head-inlay is edited by hand")
        # The cranium, still measured, because it is what the crown patch
        # used to sit in and a future change may want it again.
        crown = cranial_zone(path)
        if crown:
            print("(the old crown field: top %(top).1f%% left %(left).1f%% "
                  "%(width).1fx%(height).1f%%)" % crown)
        return 0 if drift <= 6 else 1

    plan = frames(cfg)
    known = set(f["id"] for f in plan)
    if args.only:
        names = [n.strip() for n in args.only.split(",") if n.strip()]
        unknown = [n for n in names if n not in known]
        if unknown:
            print("unknown frame id(s): %s" % ", ".join(unknown))
            return 2
        plan = [f for f in plan if f["id"] in set(names)]

    entries = load_manifest()
    if not args.force:
        plan = [f for f in plan if not already_made(f, entries)]

    price = args.price
    if price is None:
        price = PRICE.get((IMAGE_QUALITY, API_PORTRAIT), 0.0)
    drawn_plan = [f for f in plan if f["kind"] in ("quiz", "totem")]

    print("%s, quality %s — %d to draw (~$%.2f), %d to promote, "
          "%d to composite"
          % (MODEL, IMAGE_QUALITY, len(drawn_plan), len(drawn_plan) * price,
             len([f for f in plan if f["kind"] == "promote"]),
             len([f for f in plan if f["kind"] in ("share", "og")])))

    if args.dry_run:
        for frame in plan:
            print("\n--- %s (%s, %dx%d) ---"
                  % (frame["id"], frame["kind"], frame["size"][0],
                     frame["size"][1]))
            print(frame.get("prompt") or recipe(frame))
        print("\ndry run: nothing called, nothing written")
        return 0

    os.makedirs(OUT, exist_ok=True)
    spent, made, failed = 0.0, 0, []

    # Promotions first: the share cards are composited from totems, and one of
    # the totems is a promoted file.
    order = {"promote": 0, "quiz": 1, "totem": 1, "share": 2, "og": 3}
    plan.sort(key=lambda f: order[f["kind"]])

    key = os.getenv("OPENAI_API_KEY", "")
    if drawn_plan and not key:
        print("OPENAI_API_KEY is not set — nothing was called or written.")
        print("Run:  OPENAI_API_KEY=sk-... python3 scripts/gen_persona.py")
        return 1

    for frame in plan:
        frame_id, kind = frame["id"], frame["kind"]
        note = ""
        try:
            if kind == "promote":
                src = os.path.join(SAMPLES, frame["from"] + ".webp")
                if not os.path.exists(src):
                    failed.append((frame_id, "sample missing: %s" % src))
                    print("  %-26s MISSING %s" % (frame_id, src))
                    continue
                with open(src, "rb") as fh:
                    data = fh.read()
                write(frame_id, data)
                note = "promoted from %s" % frame["from"]
            elif kind in ("quiz", "totem"):
                data = None
                for attempt in range(args.retries + 1):
                    raw = generate(frame["prompt"], frame["api_size"], key)
                    spent += price
                    candidate, img = to_webp(raw, frame["size"])
                    ok, note = verdict(measure(img), frame["band"])
                    if ok:
                        data = candidate
                        break
                    print("  %-26s rejected (%s), redrawing"
                          % (frame_id, note))
                if data is None:
                    failed.append((frame_id, note))
                    print("  %-26s FAILED after %d draws (%s)"
                          % (frame_id, args.retries + 1, note))
                    continue
                write(frame_id, data)
            elif kind == "share":
                totem = os.path.join(
                    OUT, "totem_" + frame["persona"] + ".webp")
                if not os.path.exists(totem):
                    failed.append((frame_id, "totem missing"))
                    print("  %-26s needs %s first" % (frame_id, totem))
                    continue
                data = encode(share_card(totem, frame["name"]))
                write(frame_id, data)
                note = "composited from totem_%s" % frame["persona"]
            else:
                paths = [os.path.join(OUT, s + ".webp") for s in OG_SHAPES]
                gone = [p for p in paths if not os.path.exists(p)]
                if gone:
                    failed.append((frame_id, "shapes missing"))
                    print("  %-26s needs %s first" % (frame_id, gone[0]))
                    continue
                data = encode(og_card(paths, OG_HEADLINE))
                write(frame_id, data)
                note = "composited from %d shapes" % len(paths)
        except (GenerationError, RuntimeError, OSError) as err:
            failed.append((frame_id, "%s: %s" % (type(err).__name__, err)))
            print("  %-26s FAILED (%s)" % (frame_id, err))
            continue

        entries[frame_id] = {
            "sha256": sha(data),
            "recipe_sha": sha(recipe(frame).encode("utf-8")),
            "bytes": len(data),
            "size": "%dx%d" % frame["size"],
            "kind": kind,
            "cost_usd": round(price, 4) if kind in ("quiz", "totem") else 0.0,
            "note": note,
        }
        save_manifest(entries)
        made += 1
        flag = "  BIG" if len(data) > 120 * 1024 else ""
        print("  %-26s %7d B  %-11s %s%s"
              % (frame_id, len(data), kind, note, flag))

    print("\n%d frame(s) made, ~$%.2f spent, %d failed"
          % (made, spent, len(failed)))
    for frame_id, why in failed:
        print("  FAILED %s: %s" % (frame_id, why))
    print("manifest: %s" % MANIFEST)
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
