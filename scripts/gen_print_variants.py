#!/usr/bin/env python3
"""Write the PDF's print copies of a funnel's gallery images.

Console use only, run by hand when a funnel's gallery changes. Nothing
imports this and no route reaches it. Its outputs are committed, so a deploy
never builds anything and the server never needs Pillow for a report:

    pip install pillow
    cd ~/mazzin && python3 scripts/gen_print_variants.py zodiac

WeasyPrint embeds whatever it is handed at full resolution, and the gallery
originals are tall screen images: two of them took a report from 28 KB to
1.9 MB, which is a mailbox problem rather than a quality one. So each image
is pre-cropped to the box the stylesheet actually draws it in and saved as a
JPEG, and `reports._print_src` prefers it over the original.

The boxes, all out of PDF_CSS:

    .board        the moodboard, full column width x 42mm
    .shots        the two surface shots, half width x 32mm
    .tap          a section's own photograph, full width x 34mm
    .cover-band   the horizon on the cover, full width x 26mm
    .cover-glyph  the sign's frame, a 30mm disc
    .tapcell      one square of the contact sheet, a sixth of the width

A funnel that names a photograph per section draws one on every page, so
those boxes carry a tighter ceiling than the single board a kitchen report
has: eight frames at the board's 60 KB would be half a megabyte of mail.

Which images a funnel can draw is its own config's business — the moodboard
step, the material steps, and every per-style default — so the set is read
from the config rather than listed here. Idempotent: a second run rewrites
the same files.
"""
import argparse
import json
import os
import sys

from PIL import Image

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

import config          # noqa: E402

OUT = os.path.join(config.STATIC_DIR, "img", "print")

# (width, height) in pixels, at roughly 150dpi for the mm the CSS asks for,
# and the ceiling each is written under.
BOARD = (1000, 241)
SHOT = (620, 232)
TAP = (760, 200)
BAND = (900, 154)
GLYPH = (280, 280)
# The contact sheet is every frame of the run — eighteen of them on zodiac30
# — so its square is the smallest box here and carries the tightest ceiling
# by a distance. Eighteen at the tap's 30 KB would be half a megabyte of mail
# for a block the reader reads as one object.
GRID = (200, 200)

# A funnel whose frames are shown whole wants portrait slots to show them in.
# Letterboxing a 3:4 sculpture into the 760x200 banner above leaves it a fifth
# of the width with backdrop either side, which is the crop problem wearing a
# different shape. These are the same slots at the frames' own aspect, and
# they are only ever used by a funnel that asks for whole frames — every other
# funnel's boxes, bytes and ceilings are exactly what they were.
TAP_WHOLE = (420, 560)
GRID_WHOLE = (200, 267)
WHOLE_BOX = {TAP: TAP_WHOLE, GRID: GRID_WHOLE}

# A report that draws one picture per section carries eight of them.
CEILING = {TAP: 30 * 1024, BAND: 34 * 1024, GLYPH: 22 * 1024,
           GRID: 12 * 1024}

# The ceiling tests/test_check.py holds these to. Quality steps down until a
# frame fits rather than being fixed and hoped for: a busy photograph and a
# flat gradient do not compress alike.
MAX_BYTES = 60 * 1024
QUALITY = (86, 80, 74, 68, 62, 55)


def wanted(cfg):
    """{image id: box} for every image this funnel's report can draw."""
    visuals = (cfg.get("report") or {}).get("visuals") or {}
    steps = {s.get("id"): s for s in (cfg.get("swipe") or {}).get("steps") or []}

    def ids_on(step_id):
        step = steps.get(step_id) or {}
        return [i.get("id") for p in step.get("pairs") or []
                for i in p.get("images") or [] if i.get("id")]

    out = {}
    for image_id in ids_on(visuals.get("moodboard_step")):
        out[image_id] = BOARD
    for step_id in visuals.get("material_steps") or []:
        for image_id in ids_on(step_id):
            out[image_id] = SHOT
    # The per-style fallbacks, for a run whose own taps did not reach a step.
    for default in (visuals.get("defaults") or {}).values():
        if default.get("moodboard"):
            out.setdefault(default["moodboard"], BOARD)
        for image_id in default.get("materials") or []:
            out.setdefault(image_id, SHOT)
    # A funnel that illustrates each section from the reader's own taps: every
    # frame on those steps can end up in a PDF, so every one of them needs a
    # print copy.
    for step_id in (visuals.get("section_steps") or {}).values():
        for image_id in ids_on(step_id):
            out[image_id] = TAP
    hero = visuals.get("hero") or {}
    for image_id in ids_on(hero.get("band_step")):
        out[image_id] = BAND
    for image_id in ids_on(hero.get("glyph_step")):
        out[image_id] = GLYPH
    # The contact sheet is the reader's whole run, so on a funnel that draws
    # one every frame on every step can end up in a PDF and every one of them
    # needs a print copy. `setdefault`, never over: a frame the document also
    # draws full width somewhere else must not be shrunk to a thumbnail for
    # this. A funnel that declares no sheet is untouched.
    if visuals.get("taps"):
        for step in (cfg.get("swipe") or {}).get("steps") or []:
            for image_id in ids_on(step.get("id")):
                out.setdefault(image_id, GRID)
    return out


def source(cfg, image_id):
    """The gallery file behind an image id, or None."""
    for step in (cfg.get("swipe") or {}).get("steps") or []:
        for pair in step.get("pairs") or []:
            for item in pair.get("images") or []:
                if item.get("id") != image_id:
                    continue
                src = item.get("img") or ""
                if not src.startswith("/static/"):
                    return None
                return os.path.join(config.STATIC_DIR, src[len("/static/"):])
    return None


# The renders' own backdrop, so a letterboxed frame sits on the colour its
# sweep is made of rather than on white. The same value the result page uses
# for `--pr-frame`, and the same reason.
FRAME_GROUND = (206, 163, 113)


def crop_to(image, box, whole=False):
    """Fit the image onto the box: cropped to fill, or whole with a ground.

    `whole` is what the report asks for now. The sculptures are the asset the
    funnel is built on, and a print copy pre-cropped to a square threw away a
    third of every 3:4 frame before the PDF ever saw it — so on that path the
    image is scaled to fit inside the box and the remainder is filled with the
    renders' own backdrop. `object-fit: contain` in the stylesheet cannot
    recover pixels this file already discarded, which is why the change has to
    be here as well as there.

    Without it this is the old behaviour exactly: centre-crop to the box's
    aspect, then resize onto it, which is what `object-fit: cover` would do at
    render time.
    """
    want = box[0] / float(box[1])
    have = image.width / float(image.height)
    if whole:
        scale = min(box[0] / float(image.width), box[1] / float(image.height))
        size = (max(1, int(round(image.width * scale))),
                max(1, int(round(image.height * scale))))
        fitted = image.resize(size, Image.LANCZOS)
        ground = Image.new("RGB", box, FRAME_GROUND)
        ground.paste(fitted, ((box[0] - size[0]) // 2,
                              (box[1] - size[1]) // 2))
        return ground
    if have > want:                                  # too wide, trim the sides
        width = int(round(image.height * want))
        left = (image.width - width) // 2
        image = image.crop((left, 0, left + width, image.height))
    else:                                            # too tall, trim top/bottom
        height = int(round(image.width / want))
        top = (image.height - height) // 2
        image = image.crop((0, top, image.width, top + height))
    return image.resize(box, Image.LANCZOS)


def write(path, image, ceiling=MAX_BYTES):
    """Save at the best quality that stays under the ceiling."""
    for quality in QUALITY:
        image.save(path, "JPEG", quality=quality, optimize=True,
                   progressive=True)
        if os.path.getsize(path) <= ceiling:
            return quality, os.path.getsize(path)
    return QUALITY[-1], os.path.getsize(path)


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("funnel", help="the funnel whose gallery to convert")
    args = ap.parse_args(argv)

    try:
        cfg = config.load_funnel(args.funnel)
    except KeyError:
        print("no such funnel: %s" % args.funnel)
        return 1

    os.makedirs(OUT, exist_ok=True)
    todo = wanted(cfg)
    if not todo:
        print("%s draws no images in its report" % args.funnel)
        return 1

    # Whether this funnel's frames are shown whole or cropped to fill, read
    # from the funnel rather than passed on the command line: a flag somebody
    # has to remember is a flag that silently re-crops a gallery the next time
    # the script is run without it.
    whole = bool((cfg.get("report") or {}).get("print_whole"))
    if whole:
        print("  (whole frames: scaled to fit, backdrop where they do not)")

    missing = 0
    for image_id in sorted(todo):
        src = source(cfg, image_id)
        if not src or not os.path.isfile(src):
            print("  %-14s MISSING source" % image_id)
            missing += 1
            continue
        box = todo[image_id]
        if whole:
            box = WHOLE_BOX.get(box, box)
        with Image.open(src) as image:
            out = crop_to(image.convert("RGB"), box, whole=whole)
        path = os.path.join(OUT, image_id + ".jpg")
        quality, size = write(path, out, CEILING.get(todo[image_id],
                                                     MAX_BYTES))
        print("  %-14s %-9s q%-3d %5.1f KB"
              % (image_id, "%dx%d" % box, quality, size / 1024.0))

    print("\n%d images -> %s" % (len(todo) - missing, OUT))
    return 1 if missing else 0


if __name__ == "__main__":
    sys.exit(main())
