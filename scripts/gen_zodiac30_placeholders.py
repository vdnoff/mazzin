#!/usr/bin/env python3
"""Generate the zodiac30 funnel's placeholder gallery.

Console use only, run by hand. Nothing imports this and no route reaches it.
Its outputs are committed, so a deploy never builds anything and the site
never depends on Pillow being present:

    pip install pillow
    cd ~/mazzin && python3 scripts/gen_zodiac30_placeholders.py

zodiac30 is the A/B twin of zodiac and most of its quiz is the other funnel's
artwork, referenced where it already lives. Only the frames this funnel
brought with it live under static/galleries/zodiac30/, so the set written
here is the config's own images filtered on their path — an id pointing at
/static/galleries/zodiac/ is somebody else's frame and is left alone.

An id whose file is already on disk is left alone too. Phase 2 overwrites
these stand-ins with real artwork, and a rerun of this script after that must
not paint over it; deleting a frame is how you ask for it to be drawn again.

Every frame is a vertical gradient through the colours the funnel config
already carries for that image, so the placeholder and the config agree by
construction and there is no second table to keep in step. No text is drawn:
these are stand-ins for photography, and a placeholder with a caption on it
is one somebody forgets to replace.

The share card is not written here. zodiac30 points meta.og_image at the
zodiac card, which is the same product photographed the same way.

Written into static/galleries/zodiac30/:
    <image id>.webp   600x800, one per zodiac30-owned image still missing
"""
import json
import os

from PIL import Image

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
CONFIG = os.path.join(ROOT, "funnels", "zodiac30.json")
OUT = os.path.join(ROOT, "static", "galleries", "zodiac30")
OWNED = "/static/galleries/zodiac30/"

FRAME = (600, 800)
QUALITY = 80


def rgb(value):
    """(r, g, b) for a `#rrggbb` string."""
    value = value.lstrip("#")
    return tuple(int(value[i:i + 2], 16) for i in (0, 2, 4))


def gradient(size, stops):
    """A vertical gradient through `stops`, drawn a row at a time.

    Built at full height rather than as a short strip that gets resized: at
    800 rows this is a few milliseconds, and a resize would band.
    """
    width, height = size
    stops = [rgb(s) for s in stops]
    if len(stops) == 1:
        stops = stops * 2

    image = Image.new("RGB", (1, height))
    pixels = image.load()
    spans = len(stops) - 1
    for y in range(height):
        # Where this row falls between two stops.
        pos = y / max(1, height - 1) * spans
        low = min(int(pos), spans - 1)
        t = pos - low
        a, b = stops[low], stops[low + 1]
        pixels[0, y] = tuple(round(a[i] + (b[i] - a[i]) * t) for i in range(3))
    return image.resize((width, height), Image.NEAREST)


def images_in(cfg):
    """Every zodiac30-owned image the config references, with its colours.

    Ordered by first appearance so a rerun writes the files in a stable order
    and the log reads like the funnel. Borrowed frames are dropped here rather
    than skipped later, so the count this prints is the count it owns.
    """
    found = {}
    order = []
    for step in cfg["swipe"]["steps"]:
        for pair in step["pairs"]:
            for item in pair["images"]:
                if item["id"] in found or not item["img"].startswith(OWNED):
                    continue
                found[item["id"]] = [c["hex"] for c in item["colors"]]
                order.append(item["id"])
    return [(i, found[i]) for i in order]


def write(name, image):
    path = os.path.join(OUT, name + ".webp")
    image.save(path, "WEBP", quality=QUALITY, method=6)
    return os.path.getsize(path)


def main():
    with open(CONFIG, encoding="utf-8") as fh:
        cfg = json.load(fh)

    os.makedirs(OUT, exist_ok=True)
    items = images_in(cfg)
    missing = [(i, stops) for i, stops in items
               if not os.path.exists(os.path.join(OUT, i + ".webp"))]
    total = 0
    for image_id, stops in missing:
        total += write(image_id, gradient(FRAME, stops))

    print("%d of %d frames written -> %s (%d KB), %d already on disk"
          % (len(missing), len(items), OUT, round(total / 1024),
             len(items) - len(missing)))


if __name__ == "__main__":
    main()
