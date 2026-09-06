#!/usr/bin/env python3
"""Generate the love-zodiac-bg funnel's placeholder gallery.

Console use only, run by hand. Nothing imports this and no route reaches it.
Its outputs are committed, so a deploy never builds anything and the site
never depends on Pillow being present:

    pip install pillow
    cd ~/mazzin && python3 scripts/gen_love_placeholders.py

The same arrangement persona uses. /love-zodiac-bg owns every love frame it
shows and borrows exactly one set — the twelve sign glyphs, which point at
the zodiac gallery and are left alone here: an id whose path is not under
static/galleries/love-zodiac-bg/ belongs to another funnel, and this never
paints into somebody else's gallery.

An id whose file is already on disk is left alone too. scripts/
gen_love_gallery.py overwrites these stand-ins with the real art, and a rerun
of this script after that must not paint over it; deleting a frame is how you
ask for a stand-in again.

Every frame is a vertical gradient through the colours the funnel config
already carries for that image, so the placeholder and the config agree by
construction and there is no second table to keep in step. No text is drawn:
these are stand-ins for painted art, and a placeholder with a caption on it
is one somebody forgets to replace.

Written into static/galleries/love-zodiac-bg/:
    lv01a … lv18b .webp   800x800, one per love-owned image still missing
    int1, int2 .webp      800x1000, the two interstitial frames (4:5)
    og.webp               1200x630, the share card
"""
import json
import os

from PIL import Image

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
CONFIG = os.path.join(ROOT, "funnels", "love-zodiac-bg.json")
OUT = os.path.join(ROOT, "static", "galleries", "love-zodiac-bg")
OWNED = "/static/galleries/love-zodiac-bg/"

# Square, because the real art is drawn 1:1 and a stand-in has to be the
# same shape or replacing one with the other would change the layout rather
# than only the picture.
FRAME = (800, 800)
# The two interstitial frames are 4:5.
FRAME_TALL = (800, 1000)
QUALITY = 80

# The share card is the one frame with no image in the config behind it:
# night indigo up through the gold the whole funnel glows in.
OG = (1200, 630)
OG_COLORS = ["#F2C25A", "#8E4A7A", "#3E2E6E", "#141C3E"]

# The two interstitial frames have no config image behind them either — the
# config lists them in `preview_gallery` by id, with tags and a path but no
# colours — so their stops live here. A falling-star sky and a candle lit
# from another, in the same palette the cards are drawn in.
TALL_COLORS = {
    "int1": ["#D2D8E6", "#4A3A78", "#1A2246", "#0E1430"],
    "int2": ["#F0BE5C", "#9E6444", "#1A2246", "#0E1430"],
}


def rgb(value):
    """(r, g, b) for a `#rrggbb` string."""
    value = value.lstrip("#")
    return tuple(int(value[i:i + 2], 16) for i in (0, 2, 4))


def gradient(size, stops):
    """A vertical gradient through `stops`, drawn a row at a time.

    Built at full height rather than as a short strip that gets resized: at
    a thousand rows this is a few milliseconds, and a resize would band.
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
    """Every love-owned image the config references, with its colours.

    Ordered by first appearance so a rerun writes the files in a stable order
    and the log reads like the funnel. A frame belonging to another gallery —
    the sign glyphs — is dropped here rather than skipped later, so the count
    this prints is the count it owns.
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


def tall_in(cfg):
    """The preview-gallery frames no step carries: the interstitial two.

    Read off the config rather than off TALL_COLORS alone, so a frame the
    config stops naming stops being written, and one it names without a
    colour entry here is a loud failure rather than a missing file.
    """
    carried = {item["id"] for step in cfg["swipe"]["steps"]
               for pair in step["pairs"] for item in pair["images"]}
    out = []
    for item in cfg.get("preview_gallery") or []:
        if item["id"] in carried or not item["img"].startswith(OWNED):
            continue
        if item["id"] not in TALL_COLORS:
            raise SystemExit("preview_gallery names %s, which no step carries "
                             "and TALL_COLORS does not know" % item["id"])
        out.append((item["id"], TALL_COLORS[item["id"]]))
    return out


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

    tall = tall_in(cfg)
    made = 0
    for name, stops in tall:
        if not os.path.exists(os.path.join(OUT, name + ".webp")):
            total += write(name, gradient(FRAME_TALL, stops))
            made += 1

    card = 0
    if not os.path.exists(os.path.join(OUT, "og.webp")):
        card = write("og", gradient(OG, OG_COLORS))

    # A frame whose id the config no longer references is deleted rather than
    # left behind. The gallery is meant to be exactly what the funnel shows.
    # Only .webp files are touched, and only in this gallery.
    keep = ({i + ".webp" for i, _s in items} | {"og.webp"}
            | {name + ".webp" for name, _s in tall})
    orphans = sorted(f for f in os.listdir(OUT)
                     if f.endswith(".webp") and f not in keep)
    for name in orphans:
        os.remove(os.path.join(OUT, name))

    print("%d of %d frames written -> %s (%d KB), %d already on disk, "
          "%d of %d tall frame%s written, og.webp %s, %d orphan%s removed"
          % (len(missing), len(items), OUT, round((total + card) / 1024),
             len(items) - len(missing), made, len(tall),
             "" if len(tall) == 1 else "s",
             "written" if card else "already there",
             len(orphans), "" if len(orphans) == 1 else "s"))


if __name__ == "__main__":
    main()
