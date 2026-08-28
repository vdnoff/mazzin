#!/usr/bin/env python3
"""Generate the persona funnel's placeholder gallery.

Console use only, run by hand. Nothing imports this and no route reaches it.
Its outputs are committed, so a deploy never builds anything and the site
never depends on Pillow being present:

    pip install pillow
    cd ~/mazzin && python3 scripts/gen_persona_placeholders.py

Unlike zodiac30, which is the A/B twin of another funnel and borrows most of
its artwork, persona owns every frame it shows. The set written here is still
the config's own images filtered on their path — an id pointing anywhere but
static/galleries/persona/ belongs to another funnel and is left alone, which
is what stops a stray edit painting into somebody else's gallery.

An id whose file is already on disk is left alone too. Phase 2 overwrites
these stand-ins with real artwork, and a rerun of this script after that must
not paint over it; deleting a frame is how you ask for it to be drawn again.

Every frame is a vertical gradient through the colours the funnel config
already carries for that image, so the placeholder and the config agree by
construction and there is no second table to keep in step. No text is drawn:
these are stand-ins for photography, and a placeholder with a caption on it
is one somebody forgets to replace.

Written into static/galleries/persona/:
    <image id>.webp   600x800, one per persona-owned image still missing
    og.webp           1200x630, the share card — this funnel has its own
    head_base.webp    800x800, the clay head the result page inlays on
    totem_<persona>.webp   600x800, one per persona, eight of them
    share_<persona>.webp   1200x630, the card a shared link previews as
"""
import json
import os

from PIL import Image

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
CONFIG = os.path.join(ROOT, "funnels", "persona.json")
OUT = os.path.join(ROOT, "static", "galleries", "persona")
OWNED = "/static/galleries/persona/"

FRAME = (600, 800)
QUALITY = 80

# The share card is the one frame with no image in the config behind it: ink
# base through the teal the whole funnel ends on. Left as it is by v3-A — the
# frame on disk is not redrawn, and v3-B replaces it with the rest of the art.
OG = (1200, 630)
OG_COLORS = ["#4EDDC4", "#2A7078", "#1C2833", "#101820"]

# Two more frames with no config image behind them, both slots the result page
# reads by path. They are stand-ins in the v3 palette until v3-B renders them:
# the clay head the radar is inlaid on, and one totem per persona.
#
# The head is square because it is displayed on a pedestal card rather than as
# a quiz tile, and the overlay is positioned against its own box.
HEAD = (800, 800)
HEAD_COLORS = ["#E8D5B5", "#C98A3E", "#B4643C", "#8E4A2C"]

TOTEM = (600, 800)

# The share card, at the aspect every social preview crops to.
SHARE = (1200, 630)
# Warmed toward what each persona is: flame amber, stone sand, tide teal,
# beacon ochre, each dropping into the umbra the result page sits on.
TOTEM_COLORS = {
    "igniter_outer": ["#F2C070", "#E0A24E", "#B4643C", "#241A10"],
    "igniter_inner": ["#E0A24E", "#B4643C", "#8E4A2C", "#241A10"],
    "keeper_outer": ["#E8D5B5", "#D9BE95", "#A89684", "#241A10"],
    "keeper_inner": ["#D9BE95", "#A89684", "#6E655C", "#241A10"],
    "feeler_outer": ["#7DF0DB", "#4EDDC4", "#0F6F62", "#241A10"],
    "feeler_inner": ["#4EDDC4", "#0F6F62", "#2A5048", "#241A10"],
    "thinker_outer": ["#F3E3CC", "#E0A24E", "#0F6F62", "#241A10"],
    "thinker_inner": ["#C98A3E", "#8E4A2C", "#0F6F62", "#241A10"],
}


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
    """Every persona-owned image the config references, with its colours.

    Ordered by first appearance so a rerun writes the files in a stable order
    and the log reads like the funnel. A frame belonging to another gallery is
    dropped here rather than skipped later, so the count this prints is the
    count it owns.
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

    card = 0
    if not os.path.exists(os.path.join(OUT, "og.webp")):
        card = write("og", gradient(OG, OG_COLORS))

    # The result page's own two slots. Same rule as every other frame: an id
    # already on disk is left alone, so v3-B's renders survive a rerun.
    extras = [("head_base", HEAD, HEAD_COLORS)]
    extras += [("totem_" + key, TOTEM, stops)
               for key, stops in sorted(TOTEM_COLORS.items())]
    # And the share cards, which are the one set drawn from the config rather
    # than from a table here: `share_cards` declares them, the share pages
    # point at them as og:image, and tracking.py checks a share tap against
    # the same list. Landscape, because that is the shape every social card
    # preview crops to.
    extras += [("share_" + card["id"], SHARE,
                [c["hex"] for c in card["colors"]])
               for card in (cfg.get("share_cards") or [])]
    made = 0
    for name, size, stops in extras:
        if not os.path.exists(os.path.join(OUT, name + ".webp")):
            card += write(name, gradient(size, stops))
            made += 1

    # A frame whose id the config no longer references is deleted rather than
    # left behind. The gallery is meant to be exactly what the funnel shows,
    # and a step redesign renames ids by the dozen — without this the
    # directory silently accumulates the art of every walk this funnel used to
    # be, and the one check that would notice is a test nobody runs on a
    # deploy. Only .webp files are touched, and only in this gallery.
    keep = ({i + ".webp" for i, _stops in items} | {"og.webp"}
            | {name + ".webp" for name, _s, _c in extras})
    orphans = sorted(f for f in os.listdir(OUT)
                     if f.endswith(".webp") and f not in keep)
    for name in orphans:
        os.remove(os.path.join(OUT, name))

    print("%d of %d frames written -> %s (%d KB), %d already on disk, "
          "og.webp %s, %d result slot%s written, %d orphan%s removed"
          % (len(missing), len(items), OUT, round((total + card) / 1024),
             len(items) - len(missing),
             "already there" if os.path.exists(os.path.join(OUT, "og.webp"))
             else "written",
             made, "" if made == 1 else "s",
             len(orphans), "" if len(orphans) == 1 else "s"))


if __name__ == "__main__":
    main()
