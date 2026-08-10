#!/usr/bin/env python3
"""Generate the raster app icons from the wordmark's first two glyphs.

Console use only, run by hand when the brand changes — nothing imports this
and no route reaches it. Its outputs are committed, so a deploy never builds
anything and the site never depends on Pillow or on a font being downloadable:

    pip install pillow
    curl -sL -o /tmp/Poppins-Medium.ttf \\
      https://raw.githubusercontent.com/google/fonts/main/ofl/poppins/Poppins-Medium.ttf
    cd ~/mazzin && python3 scripts/build_icons.py

Pillow is deliberately absent from requirements.txt: it is a build-time tool,
not a runtime dependency, and adding it would put a compiled imaging library
into the server's virtualenv for the sake of four files that already exist.

Written into static/img/:
    icon-512.png, icon-192.png   rounded, transparent outside the corners
    apple-touch-icon.png         180px, full bleed — iOS masks it itself, and
                                 a pre-rounded tile gets rounded twice
    favicon.ico                  16 and 32, from a 32px tile
"""
import os
import sys

from PIL import Image, ImageDraw, ImageFont

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
OUT = os.path.join(ROOT, "static", "img")

FONT_PATH = "/tmp/Poppins-Medium.ttf"
BG = (28, 27, 31, 255)          # #1C1B1F, the wordmark's ink
LETTER = (247, 245, 242, 255)   # #F7F5F2
DOT = (217, 143, 85, 255)       # #D98F55, the accent lifted for dark ground

# The glyphs are drawn at 4x and downsampled: PIL has no antialiased text at
# a target size this small, and the dot in particular turns to mush at 32px.
SUPERSAMPLE = 4
FONT_FRACTION = 0.58
CORNER_FRACTION = 0.22
FAVICON_CORNER_FRACTION = 0.19


def tile(size, corner_fraction):
    """One icon: rounded dark tile, "m" in bone, "." in terracotta.

    The two glyphs are drawn as separate calls so the dot can carry its own
    colour, and positioned from the bounding box of "m." as a whole so the
    pair sits optically centred rather than centred on the "m" alone.
    """
    big = size * SUPERSAMPLE
    img = Image.new("RGBA", (big, big), (0, 0, 0, 0))
    draw = ImageDraw.Draw(img)

    radius = int(big * corner_fraction)
    if radius > 0:
        draw.rounded_rectangle([0, 0, big - 1, big - 1], radius=radius, fill=BG)
    else:
        draw.rectangle([0, 0, big - 1, big - 1], fill=BG)

    font = ImageFont.truetype(FONT_PATH, int(big * FONT_FRACTION))

    # The lockup is drawn on its own layer first and then placed by the box
    # its pixels actually occupy. Centring on the font's reported extents
    # left it eight pixels off at 512: the metric box and the drawn ink are
    # not the same rectangle, and only one of them is the thing anyone sees.
    layer = Image.new("RGBA", (big, big), (0, 0, 0, 0))
    pen = ImageDraw.Draw(layer)
    pen.text((big * 0.1, big * 0.1), "m", font=font, fill=LETTER)
    pen.text((big * 0.1 + pen.textlength("m", font=font), big * 0.1), ".",
             font=font, fill=DOT)

    ink = layer.getbbox()
    glyphs = layer.crop(ink)
    img.alpha_composite(glyphs, (int(round((big - glyphs.width) / 2.0)),
                                 int(round((big - glyphs.height) / 2.0))))

    return img.resize((size, size), Image.LANCZOS)


def main():
    if not os.path.isfile(FONT_PATH):
        print("missing %s — see the docstring for the curl line" % FONT_PATH)
        return 1
    os.makedirs(OUT, exist_ok=True)

    for size in (512, 192):
        path = os.path.join(OUT, "icon-%d.png" % size)
        tile(size, CORNER_FRACTION).save(path, optimize=True)
        print("%-24s %6d bytes" % (os.path.basename(path),
                                   os.path.getsize(path)))

    # Full bleed: iOS applies its own mask, and rounding here would round it
    # twice and leave the corners light against a dark home screen.
    path = os.path.join(OUT, "apple-touch-icon.png")
    tile(180, 0.0).save(path, optimize=True)
    print("%-24s %6d bytes" % (os.path.basename(path), os.path.getsize(path)))

    path = os.path.join(OUT, "favicon.ico")
    base = tile(32, FAVICON_CORNER_FRACTION)
    base.save(path, format="ICO", sizes=[(16, 16), (32, 32)])
    print("%-24s %6d bytes" % (os.path.basename(path), os.path.getsize(path)))
    return 0


if __name__ == "__main__":
    sys.exit(main())
