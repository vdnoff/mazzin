#!/usr/bin/env python3
"""Generate the zodiac funnel's placeholder gallery.

Console use only, run by hand. Nothing imports this and no route reaches it.
Its outputs are committed, so a deploy never builds anything and the site
never depends on Pillow being present:

    pip install pillow
    cd ~/mazzin && python3 scripts/gen_zodiac_placeholders.py

Every frame is a vertical gradient through the colours the funnel config
already carries for that image, so the placeholder and the config agree by
construction and there is no second table to keep in step. No text is drawn:
these are stand-ins for photography, and a placeholder with a caption on it
is one somebody forgets to replace.

Phase 2 overwrites the .webp files with real artwork. Nothing here needs to
be rerun for that — the config, not this script, is the source of truth for
which ids exist.

Written into static/galleries/zodiac/:
    <image id>.webp   600x800, one per image referenced by the config
    og.webp           1200x630, the share card
"""
import json
import os

from PIL import Image

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
CONFIG = os.path.join(ROOT, "funnels", "zodiac.json")
OUT = os.path.join(ROOT, "static", "galleries", "zodiac")

FRAME = (600, 800)
QUALITY = 80

# The share card is the one frame with no image in the config behind it.
OG = (1200, 630)
OG_COLORS = ["#F2A33C", "#8E4A7A", "#3E2E6E", "#101A38"]


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
    """Every image id the config references, with its colours, deduplicated.

    Ordered by first appearance so a rerun writes the files in a stable order
    and the log reads like the funnel.
    """
    found = {}
    order = []
    for step in cfg["swipe"]["steps"]:
        for pair in step["pairs"]:
            for item in pair["images"]:
                if item["id"] in found:
                    continue
                found[item["id"]] = [c["hex"] for c in item["colors"]]
                order.append(item["id"])
    for item in cfg.get("preview_gallery") or []:
        if item["id"] not in found:
            raise SystemExit(
                "preview_gallery names %s, which no step carries" % item["id"])
    return [(i, found[i]) for i in order]


def write(name, image):
    path = os.path.join(OUT, name + ".webp")
    image.save(path, "WEBP", quality=QUALITY, method=6)
    return os.path.getsize(path)


def main():
    with open(CONFIG, encoding="utf-8") as fh:
        cfg = json.load(fh)

    os.makedirs(OUT, exist_ok=True)
    total = 0
    items = images_in(cfg)
    for image_id, stops in items:
        total += write(image_id, gradient(FRAME, stops))
    total += write("og", gradient(OG, OG_COLORS))

    print("%d frames + og.webp -> %s (%d KB)"
          % (len(items), OUT, round(total / 1024)))


if __name__ == "__main__":
    main()
