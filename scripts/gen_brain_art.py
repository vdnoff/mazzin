#!/usr/bin/env python3
"""Generate the brain funnel's whole gallery.

Console use only, run by hand. Nothing imports this and no route reaches it.
Its outputs are committed, so a deploy never builds anything and the site
never depends on Pillow being present:

    pip install pillow
    cd ~/mazzin && python3 scripts/gen_brain_art.py

/brain is a memory game, which makes its art a different kind of thing from
every other funnel's. Kitchen and zodiac sell photographs; here the picture
IS the question — a card the reader has three seconds to hold in their head
and then has to pick out of four. So it is drawn rather than shot, and drawn
to three rules:

  * Flat. One bold shape on an off-white ground, no gradient, no shadow, no
    texture. Anything a reader has to look past is time taken off the three
    seconds they were given to look at the thing itself.
  * Six colours and eight forms, and nothing else. A round is only fair if
    the difference between two cards is one the reader can name — "the red
    triangle", not "the slightly warmer one" — and a palette that grows past
    counting is a palette where a miss is the art's fault.
  * Deterministic. No randomness anywhere, seeded or otherwise: every card
    is stated by the table it comes from, so a rerun writes the same bytes
    and a diff on this directory means somebody changed a card on purpose.

Everything is drawn at three times size and resized down, which is the whole
of the antialiasing — Pillow's own draw is hard-edged, and a hard edge on a
circle at 600px reads as a jagged circle rather than as a bold one.

Written into static/galleries/brain/ as WebP, quality 80, all well under the
12 KB the check enforces:

    age_*.webp        6   the age-group cards
    mood_*.webp       4   how sharp they say they feel
    mem<r>_*.webp    32   four memory rounds: what was flashed, and the decoys
    box_closed.webp   1   the one closed box, reused in all 24 spatial slots
    box_open_*.webp   4   the same box open on a key, a cup, a star, a moon
    chg<r>_*.webp    20   four change rounds: the four frames, and the one
                          that came back different
    odd_*.webp        2   the five that match, and the one that does not
    ink_*.webp        4   colour words in coloured ink, one of them honest
    nxt_*.webp        8   the sequence, and the four things it could become
    cnt_*.webp        8   the circles to count, and the four numbers
    share_*.webp      4   one per brain type
    og.webp           1   1200x630, for the link preview
"""
import math
import os

from PIL import Image, ImageDraw, ImageFont

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
OUT = os.path.join(ROOT, "static", "galleries", "brain")

CARD = 600
OG = (1200, 630)
QUALITY = 80
# Everything is drawn at this multiple and resized down. Three rather than
# four: four doubles the memory for a difference nobody can see at 600px.
SS = 3

GROUND = (244, 241, 234)      # the off-white every card sits on
INK = (44, 48, 56)

# The whole palette. Six, named, because a round is only fair when the
# difference between two cards is one a reader could say out loud.
RED = (226, 87, 76)
BLUE = (59, 125, 216)
AMBER = (242, 179, 61)
GREEN = (76, 175, 125)
VIOLET = (142, 111, 216)
TEAL = (47, 168, 160)
PALETTE = {"red": RED, "blue": BLUE, "amber": AMBER,
           "green": GREEN, "violet": VIOLET, "teal": TEAL}

# A fixed font, chosen once and named, because "whatever the system has"
# makes the output depend on the machine that ran it. Same list gen_persona.py
# uses, for the same reason and so the two scripts cannot disagree.
FONTS = [
    ("/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
     "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf"),
    ("/usr/share/fonts/truetype/liberation/LiberationSans-Bold.ttf",
     "/usr/share/fonts/truetype/liberation/LiberationSans-Regular.ttf"),
]


def fonts():
    """`(bold path, regular path)`, or None when the machine has neither.

    Refused rather than fallen back on: Pillow's default is a bitmap face at
    one small size, and a Stroop card set in it would ship unreadable — which
    on this funnel is not a cosmetic problem but a round nobody can answer.
    """
    for bold, regular in FONTS:
        if os.path.exists(bold) and os.path.exists(regular):
            return bold, regular
    return None


BOLD, REGULAR = fonts() or (None, None)


# --- geometry ---------------------------------------------------------------

def ngon(cx, cy, r, sides, phase=0.0):
    """A regular polygon, `phase` degrees off the first vertex being east."""
    out = []
    for i in range(sides):
        angle = math.radians(phase + i * 360.0 / sides)
        out.append((cx + r * math.cos(angle), cy + r * math.sin(angle)))
    return out


def star(cx, cy, r, points=5, inner=0.45, phase=-90.0):
    out = []
    for i in range(points * 2):
        radius = r if i % 2 == 0 else r * inner
        angle = math.radians(phase + i * 180.0 / points)
        out.append((cx + radius * math.cos(angle), cy + radius * math.sin(angle)))
    return out


def cross(cx, cy, r, arm=0.36):
    """A plus sign, as one polygon, so it rotates like everything else."""
    a = r * arm
    return [(cx - a, cy - r), (cx + a, cy - r), (cx + a, cy - a),
            (cx + r, cy - a), (cx + r, cy + a), (cx + a, cy + a),
            (cx + a, cy + r), (cx - a, cy + r), (cx - a, cy + a),
            (cx - r, cy + a), (cx - r, cy - a), (cx - a, cy - a)]


def spin(points, cx, cy, degrees):
    if not degrees:
        return points
    rad = math.radians(degrees)
    cos, sin = math.cos(rad), math.sin(rad)
    return [(cx + (x - cx) * cos - (y - cy) * sin,
             cy + (x - cx) * sin + (y - cy) * cos) for x, y in points]


# The eight forms a card can carry. `circle` is the one that is not a polygon
# and is drawn as an ellipse; the rest are point lists so rotation is one
# function rather than a case per shape.
FORMS = ("circle", "square", "triangle", "hexagon",
         "star", "diamond", "cross", "pentagon")


def shape_points(form, cx, cy, r, rot=0.0):
    if form == "square":
        pts = ngon(cx, cy, r, 4, 45)
    elif form == "diamond":
        pts = ngon(cx, cy, r, 4, 0)
    elif form == "triangle":
        pts = ngon(cx, cy, r, 3, -90)
    elif form == "hexagon":
        pts = ngon(cx, cy, r, 6, 0)
    elif form == "pentagon":
        pts = ngon(cx, cy, r, 5, -90)
    elif form == "star":
        pts = star(cx, cy, r)
    elif form == "cross":
        pts = cross(cx, cy, r)
    else:
        return None
    return spin(pts, cx, cy, rot)


# --- the canvas -------------------------------------------------------------

class Card(object):
    """One card, drawn oversize and resized down on `save`."""

    def __init__(self, width=CARD, height=None, ground=GROUND):
        self.w = width
        self.h = height or width
        self.img = Image.new("RGB", (self.w * SS, self.h * SS), ground)
        self.d = ImageDraw.Draw(self.img)

    def shape(self, form, colour, cx=0.5, cy=0.5, r=0.30, rot=0.0):
        """One form, positioned and sized in fractions of the card."""
        x, y = cx * self.w * SS, cy * self.h * SS
        radius = r * self.w * SS
        pts = shape_points(form, x, y, radius, rot)
        if pts is None:
            self.d.ellipse([x - radius, y - radius, x + radius, y + radius],
                           fill=colour)
        else:
            self.d.polygon(pts, fill=colour)

    def rect(self, box, colour, radius=0.0, outline=None, width=0):
        x0, y0, x1, y1 = [v * self.w * SS for v in box]
        if radius:
            self.d.rounded_rectangle([x0, y0, x1, y1], radius * self.w * SS,
                                     fill=colour, outline=outline,
                                     width=int(width * self.w * SS))
        else:
            self.d.rectangle([x0, y0, x1, y1], fill=colour, outline=outline,
                             width=int(width * self.w * SS))

    def text(self, body, size, colour=INK, cx=0.5, cy=0.5, bold=True):
        """Centred on (cx, cy), in points of the finished card."""
        path = BOLD if bold else REGULAR
        if not path:
            raise RuntimeError("no usable font on this machine")
        font = ImageFont.truetype(path, int(size * SS))
        box = self.d.textbbox((0, 0), body, font=font)
        x = cx * self.w * SS - (box[2] - box[0]) / 2.0 - box[0]
        y = cy * self.h * SS - (box[3] - box[1]) / 2.0 - box[1]
        self.d.text((x, y), body, font=font, fill=colour)

    def save(self, name, quality=QUALITY):
        """Resized down to size and written. `quality` is a lever for one
        card: the share image is twice the width of a game card and would
        otherwise be the only file over the 12 KB ceiling the check enforces,
        and it is the one picture nobody has to answer a question about."""
        out = self.img.resize((self.w, self.h), Image.LANCZOS)
        path = os.path.join(OUT, name + ".webp")
        out.save(path, "WEBP", quality=quality, method=6)
        return path



# --- the cards --------------------------------------------------------------
#
# Every table below is the whole statement of what a round looks like. The
# funnel config names these files and tests/test_brain_check.py checks the two
# agree; nothing is derived from the config here, so the art can be redrawn
# without a config in the room.

def plain(colour, form, rot=0.0, r=0.30):
    """One bold shape on the ground. The whole vocabulary of this funnel."""
    card = Card()
    card.shape(form, PALETTE[colour], r=r, rot=rot)
    return card


# Four memory rounds. `flash` is what is held up; `decoys` are the three
# cards the reader has to tell it apart from afterwards. `seen` is the slot
# of the flash card that comes back — a different one every round, so nobody
# can learn a position instead of a picture.
MEMORY = [
    {"seen": 1,
     "flash": [("red", "circle"), ("blue", "triangle"),
               ("amber", "square"), ("green", "star")],
     "decoys": [("violet", "hexagon"), ("teal", "diamond"),
                ("amber", "cross")]},
    {"seen": 3,
     "flash": [("violet", "square"), ("green", "hexagon"),
               ("red", "star"), ("blue", "diamond")],
     "decoys": [("amber", "triangle"), ("teal", "circle"),
                ("red", "pentagon")]},
    {"seen": 4,
     "flash": [("amber", "circle"), ("violet", "triangle"),
               ("teal", "square"), ("red", "hexagon"),
               ("green", "diamond"), ("blue", "cross")],
     "decoys": [("blue", "star"), ("red", "circle"),
                ("violet", "pentagon")]},
    {"seen": 2,
     "flash": [("green", "square"), ("teal", "star"),
               ("blue", "pentagon"), ("amber", "diamond"),
               ("violet", "circle"), ("red", "triangle")],
     "decoys": [("teal", "hexagon"), ("amber", "cross"),
                ("green", "circle")]},
]

# Four change rounds. `flash` is the set as it was; `changed` is the slot that
# comes back different and `after` is what it comes back as. One kind of
# difference per round, in the order they get harder: a colour, then a form,
# then a size, then a rotation.
CHANGE = [
    {"changed": 1, "kind": "colour",
     "flash": [("red", "triangle"), ("blue", "square"),
               ("green", "circle"), ("amber", "star")],
     "after": {"colour": "violet", "form": "square"}},
    {"changed": 3, "kind": "form",
     "flash": [("teal", "hexagon"), ("violet", "circle"),
               ("amber", "diamond"), ("red", "star")],
     "after": {"colour": "red", "form": "pentagon"}},
    {"changed": 0, "kind": "size",
     "flash": [("green", "square"), ("red", "circle"),
               ("blue", "triangle"), ("violet", "hexagon")],
     "after": {"colour": "green", "form": "square", "r": 0.185}},
    {"changed": 2, "kind": "rotation",
     "flash": [("amber", "triangle"), ("teal", "diamond"),
               ("red", "cross"), ("blue", "star")],
     "after": {"colour": "red", "form": "cross", "rot": 45.0}},
]

# The age groups, and the six words that go on them.
AGES = [("age_21", "18–24"), ("age_30", "25–34"), ("age_40", "35–44"),
        ("age_50", "45–54"), ("age_60", "55–64"), ("age_70", "65+")]

# How full the bar is, and what colour it runs at. Four steps, top to bottom.
MOODS = [("mood_sharp", 1.00, GREEN), ("mood_ok", 0.66, TEAL),
         ("mood_foggy", 0.36, AMBER), ("mood_fumes", 0.13, RED)]

# The word, and the ink it is set in. Exactly one card tells the truth.
INKS = [("ink_1", "RED", BLUE), ("ink_2", "BLUE", BLUE),
        ("ink_3", "GREEN", AMBER), ("ink_4", "AMBER", RED)]

# The sequence turns a quarter each frame, so the answer is the next quarter.
NEXT_ROT = [0.0, 45.0, 90.0]
NEXT_ANSWERS = [("nxt_a1", "triangle", 135.0), ("nxt_a2", "triangle", 180.0),
                ("nxt_a3", "triangle", 90.0), ("nxt_a4", "square", 135.0)]

# Nine circles across four frames, which is the whole of the round.
COUNTS = [2, 3, 2, 2]
COUNT_ANSWERS = ["7", "8", "9", "10"]

# One card per brain type: the name, and the form the domain is drawn as
# everywhere else on the funnel.
TYPES = [("memory_mind", "The Recorder", "circle", BLUE),
         ("spatial_mind", "The Navigator", "diamond", GREEN),
         ("change_mind", "The Detector", "triangle", AMBER),
         ("focus_mind", "The Laser", "star", VIOLET)]


def box(open_on=None):
    """The closed box, or the same box open on one object.

    One drawing with a branch rather than two: the closed box in a spatial
    round is the control, and a lid that sat a pixel differently on the open
    one would be a tell the reader could use instead of remembering.
    """
    card = Card()
    body = (0.16, 0.34, 0.84, 0.84)
    lid = (0.12, 0.24, 0.88, 0.36)
    if open_on:
        # The lid comes off and tilts; the object sits in the open body.
        pts = [(0.12, 0.16), (0.88, 0.16), (0.88, 0.27), (0.12, 0.27)]
        pts = [(x * CARD * SS, y * CARD * SS) for x, y in pts]
        card.d.polygon(spin(pts, 0.5 * CARD * SS, 0.215 * CARD * SS, -9.0),
                       fill=INK)
        card.rect(body, (223, 218, 206), radius=0.05)
        object_glyph(card, open_on)
    else:
        card.rect(body, (223, 218, 206), radius=0.05)
        card.rect(lid, INK, radius=0.03)
    return card


def object_glyph(card, name):
    """The four things a box can be hiding, drawn at the same weight."""
    unit = CARD * SS
    cx, cy = 0.5 * unit, 0.60 * unit
    if name == "star":
        card.shape("star", AMBER, cx=0.5, cy=0.60, r=0.19)
    elif name == "moon":
        # A crescent: one disc, then the ground bitten out of it.
        r = 0.19 * unit
        card.d.ellipse([cx - r, cy - r, cx + r, cy + r], fill=VIOLET)
        card.d.ellipse([cx - r * 0.45, cy - r * 1.05,
                        cx + r * 1.55, cy + r * 1.05], fill=(223, 218, 206))
    elif name == "cup":
        card.d.polygon([(cx - 0.13 * unit, cy - 0.14 * unit),
                        (cx + 0.13 * unit, cy - 0.14 * unit),
                        (cx + 0.09 * unit, cy + 0.15 * unit),
                        (cx - 0.09 * unit, cy + 0.15 * unit)], fill=TEAL)
        card.d.ellipse([cx + 0.09 * unit, cy - 0.10 * unit,
                        cx + 0.24 * unit, cy + 0.05 * unit],
                       outline=TEAL, width=int(0.028 * unit))
    else:
        # The key: a ringed head, a stem, and two teeth.
        r = 0.10 * unit
        card.d.ellipse([cx - 0.20 * unit - r, cy - r,
                        cx - 0.20 * unit + r, cy + r], fill=RED)
        card.d.ellipse([cx - 0.20 * unit - r * 0.42, cy - r * 0.42,
                        cx - 0.20 * unit + r * 0.42, cy + r * 0.42],
                       fill=(223, 218, 206))
        card.d.rectangle([cx - 0.20 * unit, cy - 0.035 * unit,
                          cx + 0.22 * unit, cy + 0.035 * unit], fill=RED)
        for at in (0.10, 0.17):
            card.d.rectangle([cx + at * unit, cy + 0.035 * unit,
                              cx + (at + 0.045) * unit, cy + 0.13 * unit],
                             fill=RED)


def dot_grid(odd=False):
    """Nine circles in a three by three. On the odd card one of them shrank.

    Deliberately a size rather than a hue: a shade half a step off survives
    neither the resize nor WebP, and a round whose answer depends on the
    encoder is a round that is sometimes unanswerable.
    """
    card = Card()
    for row in range(3):
        for col in range(3):
            small = odd and row == 1 and col == 1
            card.shape("circle", GREEN,
                       cx=0.24 + col * 0.26, cy=0.24 + row * 0.26,
                       r=0.070 if small else 0.105)
    return card


def circles(count):
    """`count` circles, laid out so counting them is a glance, not a search."""
    card = Card()
    spots = [(0.30, 0.32), (0.70, 0.32), (0.30, 0.68), (0.70, 0.68),
             (0.50, 0.50)]
    for i in range(count):
        x, y = spots[i % len(spots)]
        card.shape("circle", AMBER, cx=x, cy=y, r=0.115)
    return card


def bar(level, colour):
    """The mood card: a bar, filled to how sharp they say they feel."""
    card = Card()
    card.rect((0.16, 0.42, 0.84, 0.58), (223, 218, 206), radius=0.08)
    end = 0.16 + (0.84 - 0.16) * level
    card.rect((0.16, 0.42, max(end, 0.22), 0.58), colour, radius=0.08)
    return card


def word(text, size, colour=INK):
    card = Card()
    card.text(text, size, colour=colour)
    return card


def share_card(name, form, colour):
    card = Card()
    card.shape(form, colour, cy=0.40, r=0.20)
    card.text(name, 46, cx=0.5, cy=0.74)
    return card


def og_card():
    card = Card(OG[0], OG[1])
    for i, (form, colour) in enumerate((("circle", BLUE), ("diamond", GREEN),
                                        ("triangle", AMBER), ("star", VIOLET))):
        card.shape(form, colour, cx=0.155 + i * 0.23, cy=0.34, r=0.052)
    card.text("Brain Age Challenge", 78, cx=0.5, cy=0.62)
    card.text("18 quick rounds. No sign-up.", 34, colour=(120, 122, 128),
              cx=0.5, cy=0.78, bold=False)
    return card


# --- main -------------------------------------------------------------------

def main():
    if not BOLD:
        raise SystemExit("no usable font on this machine — see FONTS above")
    if not os.path.isdir(OUT):
        os.makedirs(OUT)
    written = []

    def put(card, name, quality=QUALITY):
        card.save(name, quality)
        written.append(name)

    for card_id, text in AGES:
        put(word(text, 92), card_id)
    for card_id, level, colour in MOODS:
        put(bar(level, colour), card_id)

    for r, round_spec in enumerate(MEMORY, start=1):
        for i, (colour, form) in enumerate(round_spec["flash"], start=1):
            put(plain(colour, form), "mem%d_f%d" % (r, i))
        for i, (colour, form) in enumerate(round_spec["decoys"], start=1):
            put(plain(colour, form), "mem%d_m%d" % (r, i))

    put(box(), "box_closed")
    for name in ("key", "cup", "star", "moon"):
        put(box(name), "box_open_" + name)

    for r, round_spec in enumerate(CHANGE, start=1):
        for i, (colour, form) in enumerate(round_spec["flash"], start=1):
            put(plain(colour, form), "chg%d_f%d" % (r, i))
        after = round_spec["after"]
        put(plain(after["colour"], after["form"],
                  rot=after.get("rot", 0.0), r=after.get("r", 0.30)),
            "chg%d_x" % r)

    put(dot_grid(False), "odd_base")
    put(dot_grid(True), "odd_diff")

    for card_id, text, colour in INKS:
        put(word(text, 76, colour), card_id)

    for i, rot in enumerate(NEXT_ROT, start=1):
        put(plain("violet", "triangle", rot=rot), "nxt_q%d" % i)
    put(word("?", 150, (150, 152, 158)), "nxt_qm")
    for card_id, form, rot in NEXT_ANSWERS:
        put(plain("violet", form, rot=rot), card_id)

    for i, count in enumerate(COUNTS, start=1):
        put(circles(count), "cnt_f%d" % i)
    for text in COUNT_ANSWERS:
        put(word(text, 130), "cnt_" + text)

    for style_id, name, form, colour in TYPES:
        put(share_card(name, form, colour), "share_" + style_id)

    put(og_card(), "og", quality=70)

    biggest = max(written,
                  key=lambda n: os.path.getsize(os.path.join(OUT, n + ".webp")))
    print("%d files written to %s" % (len(written), OUT))
    print("largest: %s.webp at %d bytes"
          % (biggest, os.path.getsize(os.path.join(OUT, biggest + ".webp"))))


if __name__ == "__main__":
    main()
