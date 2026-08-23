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

# A report that draws one picture per section carries eight of them.
CEILING = {TAP: 30 * 1024, BAND: 34 * 1024, GLYPH: 22 * 1024}

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


def crop_to(image, box):
    """Centre-crop to the box's aspect, then resize onto it.

    The same thing `object-fit: cover` would do at render time, done once here
    so the bytes never reach the PDF.
    """
    want = box[0] / float(box[1])
    have = image.width / float(image.height)
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

    missing = 0
    for image_id in sorted(todo):
        src = source(cfg, image_id)
        if not src or not os.path.isfile(src):
            print("  %-14s MISSING source" % image_id)
            missing += 1
            continue
        box = todo[image_id]
        with Image.open(src) as image:
            out = crop_to(image.convert("RGB"), box)
        path = os.path.join(OUT, image_id + ".jpg")
        quality, size = write(path, out, CEILING.get(box, MAX_BYTES))
        print("  %-14s %-9s q%-3d %5.1f KB"
              % (image_id, "%dx%d" % box, quality, size / 1024.0))

    print("\n%d images -> %s" % (len(todo) - missing, OUT))
    return 1 if missing else 0


if __name__ == "__main__":
    sys.exit(main())
