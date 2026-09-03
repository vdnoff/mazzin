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
    mem<r>_*.webp    34   four memory rounds: what was flashed, and the decoys
    box_closed.webp   1   the one closed box, reused in all 24 spatial slots
    box_open_*.webp   4   the same box open on a key, a cup, a star, a moon
    letter_*.webp    20   four change rounds of letters: the four that were
                          held up, and the one that came back different
    umb_s*.webp       6   the five umbrellas that match, and the one that does not
    ink_*.webp        4   colour words in coloured ink, one of them honest
    dial_r*_d*.webp   6   the pattern round: three frames, the one that
                          continues both of their progressions, and the two
                          that continue one — the third of those three is the
                          first frame, so six files carry seven cards
    nxt_qm.webp       1   the question mark the pattern round's flash ends on
    cnt_*.webp        8   the circles to count, and the four numbers
    share_*.webp      4   one per brain type
    og.webp           1   1200x630, for the link preview
"""
import math
import os

from PIL import Image, ImageChops, ImageDraw, ImageFont

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

    def text_above(self, body, size, bottom, colour=INK, cx=0.5, bold=True):
        """Centred across, with the glyphs' feet at `bottom`.

        Centring on a y is the wrong tool where the thing under the text moves
        between cards: the gap the eye reads is the one between the bottom of
        the number and the top of what is under it, and that is what this
        sets.
        """
        path = BOLD if bold else REGULAR
        if not path:
            raise RuntimeError("no usable font on this machine")
        font = ImageFont.truetype(path, int(size * SS))
        box = self.d.textbbox((0, 0), body, font=font)
        x = cx * self.w * SS - (box[2] - box[0]) / 2.0 - box[0]
        y = bottom * self.h * SS - box[3]
        self.d.text((x, y), body, font=font, fill=colour)

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
    if form == "crescent":
        crescent(card, PALETTE[colour], r=r)
        return card
    card.shape(form, PALETTE[colour], r=r, rot=rot)
    return card


def crescent(card, colour, r=0.30, cx=0.5, cy=0.5):
    """A disc with a bite taken out of it by the ground behind it.

    Not in FORMS, because it is not a polygon and it does not turn: it is one
    shape on one card, drawn where a rotating triangle used to be.
    """
    unit = card.w * SS
    radius = r * unit
    x, y = cx * unit, cy * unit
    card.d.ellipse([x - radius, y - radius, x + radius, y + radius],
                   fill=colour)
    bite = radius * 0.92
    card.d.ellipse([x - bite + radius * 0.52, y - bite,
                    x + bite + radius * 0.52, y + bite], fill=GROUND)


# Four memory rounds. `flash` is what is held up; `decoys` are the three
# cards the reader has to tell it apart from afterwards. `seen` is the slot
# of the flash card that comes back — a different one every round, so nobody
# can learn a position instead of a picture.
# --- v11: every scored round has three versions of itself -------------------
#
# A reader who plays this twice should not be answering the same sixteen
# questions. Every scored step carries three variants and the engine draws one
# per run, so what changes between two walks is the content and never the
# shape: a variant of a round keeps that round's own difficulty — how many
# frames, how long they are held, how big the change is — and differs only in
# which shapes, letters, colours or objects it uses.
#
# Files are named by WHAT THEY ARE rather than by which round uses them, so
# three variants of a memory round share one library of shape cards instead of
# writing three copies of the same picture. `plain_red_circle.webp` is a red
# circle wherever it turns up, which is also what lets a check read a round
# off its filenames.


def shape_name(colour, form):
    return "plain_%s_%s" % (colour, form)


# The memory rounds. `flash` is what is held up, `decoys` are the cards that
# come back with the answer, and `seen` is which of the flashed frames is the
# answer. The four rounds get harder in how the round is played rather than in
# what it is made of: four frames then six, three seconds then two and a half,
# and the last round's decoys are colour neighbours of the answer.
MEMORY_VARIANTS = {
    "mem1": [
        {"seen": 1, "hold": 3000,
         "flash": [("red", "circle"), ("blue", "triangle"),
                   ("amber", "square"), ("green", "star")],
         "decoys": [("violet", "hexagon"), ("teal", "diamond"),
                    ("amber", "cross")]},
        {"seen": 3, "hold": 3000,
         "flash": [("teal", "pentagon"), ("amber", "diamond"),
                   ("violet", "circle"), ("red", "square")],
         "decoys": [("blue", "star"), ("green", "cross"),
                    ("teal", "triangle")]},
        {"seen": 0, "hold": 3000,
         "flash": [("green", "hexagon"), ("red", "star"),
                   ("blue", "cross"), ("amber", "pentagon")],
         "decoys": [("violet", "square"), ("teal", "circle"),
                    ("red", "diamond")]},
    ],
    "mem2": [
        {"seen": 3, "hold": 3000,
         "flash": [("violet", "square"), ("green", "hexagon"),
                   ("red", "star"), ("blue", "diamond"),
                   ("amber", "circle"), ("teal", "cross")],
         "decoys": [("amber", "triangle"), ("teal", "circle"),
                    ("red", "pentagon"), ("green", "star"),
                    ("blue", "square")]},
        {"seen": 5, "hold": 3000,
         "flash": [("teal", "star"), ("red", "hexagon"),
                   ("amber", "cross"), ("violet", "triangle"),
                   ("green", "diamond"), ("blue", "pentagon")],
         "decoys": [("violet", "star"), ("green", "cross"),
                    ("red", "circle"), ("amber", "square"),
                    ("teal", "diamond")]},
        {"seen": 1, "hold": 3000,
         "flash": [("blue", "circle"), ("amber", "star"),
                   ("green", "square"), ("teal", "hexagon"),
                   ("red", "triangle"), ("violet", "cross")],
         "decoys": [("blue", "diamond"), ("red", "pentagon"),
                    ("teal", "square"), ("violet", "hexagon"),
                    ("green", "circle")]},
    ],
    "mem3": [
        {"seen": 4, "hold": 2500,
         "flash": [("amber", "circle"), ("violet", "triangle"),
                   ("teal", "square"), ("red", "hexagon"),
                   ("green", "diamond"), ("blue", "cross")],
         "decoys": [("blue", "star"), ("red", "circle"),
                    ("violet", "pentagon"), ("amber", "hexagon"),
                    ("teal", "star")]},
        {"seen": 2, "hold": 2500,
         "flash": [("red", "pentagon"), ("blue", "square"),
                   ("green", "star"), ("violet", "diamond"),
                   ("amber", "hexagon"), ("teal", "triangle")],
         "decoys": [("teal", "cross"), ("amber", "circle"),
                    ("blue", "hexagon"), ("red", "triangle"),
                    ("green", "pentagon")]},
        {"seen": 5, "hold": 2500,
         "flash": [("green", "cross"), ("teal", "diamond"),
                   ("violet", "star"), ("amber", "triangle"),
                   ("blue", "hexagon"), ("red", "square")],
         "decoys": [("violet", "cross"), ("green", "square"),
                    ("amber", "star"), ("blue", "circle"),
                    ("teal", "pentagon")]},
    ],
    # The hardest of the four: the decoys are the answer's own shape in the
    # colour next to it, so "I remember a green one" is not enough.
    "mem4": [
        {"seen": 2, "hold": 2500,
         "flash": [("green", "square"), ("teal", "star"),
                   ("blue", "pentagon"), ("amber", "diamond"),
                   ("violet", "circle"), ("red", "triangle")],
         "decoys": [("teal", "pentagon"), ("green", "pentagon"),
                    ("violet", "pentagon"), ("blue", "hexagon"),
                    ("blue", "diamond")]},
        {"seen": 0, "hold": 2500,
         "flash": [("red", "hexagon"), ("blue", "cross"),
                   ("amber", "star"), ("green", "circle"),
                   ("teal", "square"), ("violet", "diamond")],
         "decoys": [("amber", "hexagon"), ("violet", "hexagon"),
                    ("red", "pentagon"), ("red", "diamond"),
                    ("green", "hexagon")]},
        {"seen": 4, "hold": 2500,
         "flash": [("amber", "triangle"), ("violet", "square"),
                   ("green", "diamond"), ("red", "cross"),
                   ("teal", "hexagon"), ("blue", "star")],
         "decoys": [("green", "hexagon"), ("blue", "hexagon"),
                    ("teal", "pentagon"), ("teal", "circle"),
                    ("violet", "hexagon")]},
    ],
}

# The spatial rounds. Six identical closed boxes, one of which was open on the
# flash, and then a chain of swaps. Every variant of a round runs a chain of
# the SAME length at the SAME speed — that is the round's difficulty — and
# differs in which object was under the lid, which slot it started in and
# which way the chain runs. The landing slot is worked out by running the
# chain rather than written down, so a variant cannot claim a landing its own
# swaps do not produce.
SPATIAL_VARIANTS = {
    "spa1": [
        {"object": "key", "open_slot": 2, "swap_ms": 800,
         "swaps": [[2, 5], [0, 3], [5, 1], [3, 4]]},
        {"object": "leaf", "open_slot": 0, "swap_ms": 800,
         "swaps": [[0, 4], [1, 3], [4, 2], [5, 0]]},
        {"object": "bell", "open_slot": 5, "swap_ms": 800,
         "swaps": [[5, 1], [2, 4], [1, 0], [3, 5]]},
    ],
    "spa2": [
        {"object": "cup", "open_slot": 5, "swap_ms": 600,
         "swaps": [[5, 2], [0, 4], [2, 3], [1, 5], [4, 0]]},
        {"object": "star", "open_slot": 1, "swap_ms": 600,
         "swaps": [[1, 4], [3, 0], [4, 2], [5, 1], [0, 3]]},
        {"object": "key", "open_slot": 3, "swap_ms": 600,
         "swaps": [[3, 0], [2, 5], [0, 4], [1, 3], [5, 2]]},
    ],
    "spa3": [
        {"object": "star", "open_slot": 0, "swap_ms": 450,
         "swaps": [[0, 4], [1, 2], [4, 5], [0, 3], [5, 2], [3, 1]]},
        {"object": "bell", "open_slot": 4, "swap_ms": 450,
         "swaps": [[4, 1], [0, 5], [1, 3], [2, 4], [5, 0], [3, 2]]},
        {"object": "moon", "open_slot": 2, "swap_ms": 450,
         "swaps": [[2, 5], [3, 1], [5, 0], [4, 2], [1, 3], [0, 4]]},
    ],
    "spa4": [
        {"object": "moon", "open_slot": 3, "swap_ms": 350,
         "swaps": [[3, 1], [0, 5], [1, 4], [2, 3], [4, 0], [5, 1], [0, 2]]},
        {"object": "leaf", "open_slot": 1, "swap_ms": 350,
         "swaps": [[1, 5], [2, 0], [5, 3], [4, 1], [0, 2], [3, 4], [2, 5]]},
        {"object": "cup", "open_slot": 4, "swap_ms": 350,
         "swaps": [[4, 0], [3, 5], [0, 2], [1, 4], [5, 3], [2, 1], [4, 5]]},
    ],
}

SPATIAL_OPEN_MS = 3000
SPATIAL_CLOSE_MS = 600


def spatial_landing(open_slot, swaps):
    """Where the object ends up after a chain, by running the chain.

    The same walk the engine's own reveal does: each swap exchanges the
    contents of two slots, and the object goes wherever the slot it is in is
    sent. Written here so the config and the check can both be built from the
    chain rather than from somebody's arithmetic about it.
    """
    at = open_slot
    for a, b in swaps:
        if at == a:
            at = b
        elif at == b:
            at = a
    return at


# The change rounds. One of four letters comes back different, and what makes
# the four rounds four is the KIND of difference and how small it is: a letter
# that could be mistaken for the one it replaced, then a colour one shade
# over, then a fifth off the size, then ten degrees of tilt. Every variant of
# a round keeps its round's kind and magnitude.
#
# The letter pairs are chosen for silhouette — E and F, C and G, P and R — so
# a reader who held "there was a letter with a bar" is not helped by any of
# them.
CHANGE_VARIANTS = {
    "chg1": [
        {"changed": 1, "kind": "letter",
         "flash": [("A", "red", "lg", 0), ("E", "blue", "lg", 0),
                   ("R", "green", "lg", 0), ("M", "amber", "lg", 0)],
         "after": ("F", "blue", "lg", 0)},
        {"changed": 3, "kind": "letter",
         "flash": [("K", "violet", "lg", 0), ("S", "teal", "lg", 0),
                   ("T", "amber", "lg", 0), ("C", "red", "lg", 0)],
         "after": ("G", "red", "lg", 0)},
        {"changed": 0, "kind": "letter",
         "flash": [("P", "green", "lg", 0), ("W", "amber", "lg", 0),
                   ("B", "blue", "lg", 0), ("Z", "violet", "lg", 0)],
         "after": ("R", "green", "lg", 0)},
    ],
    # Neighbours on the palette: amber next to red, teal next to green,
    # violet next to blue. One shade over, never one colour over.
    "chg2": [
        {"changed": 3, "kind": "colour",
         "flash": [("S", "violet", "lg", 0), ("T", "teal", "lg", 0),
                   ("B", "blue", "lg", 0), ("G", "green", "lg", 0)],
         "after": ("G", "teal", "lg", 0)},
        {"changed": 1, "kind": "colour",
         "flash": [("D", "green", "lg", 0), ("K", "red", "lg", 0),
                   ("N", "blue", "lg", 0), ("V", "teal", "lg", 0)],
         "after": ("K", "amber", "lg", 0)},
        {"changed": 2, "kind": "colour",
         "flash": [("H", "amber", "lg", 0), ("F", "teal", "lg", 0),
                   ("L", "blue", "lg", 0), ("Y", "red", "lg", 0)],
         "after": ("L", "violet", "lg", 0)},
    ],
    # A fifth off, which at this size is about eleven pixels of cap height and
    # not a card anybody spots without having held the row.
    "chg3": [
        {"changed": 0, "kind": "size",
         "flash": [("W", "green", "lg", 0), ("F", "blue", "lg", 0),
                   ("N", "amber", "lg", 0), ("Z", "violet", "lg", 0)],
         "after": ("W", "green", "md", 0)},
        {"changed": 2, "kind": "size",
         "flash": [("Q", "red", "lg", 0), ("J", "teal", "lg", 0),
                   ("A", "violet", "lg", 0), ("E", "amber", "lg", 0)],
         "after": ("A", "violet", "md", 0)},
        {"changed": 3, "kind": "size",
         "flash": [("B", "blue", "lg", 0), ("X", "green", "lg", 0),
                   ("T", "red", "lg", 0), ("M", "teal", "lg", 0)],
         "after": ("M", "teal", "md", 0)},
    ],
    # Ten degrees. Fifteen was already the hardest of the four; this is the
    # round the plan is most often built around.
    "chg4": [
        {"changed": 2, "kind": "rotation",
         "flash": [("D", "amber", "lg", 0), ("P", "teal", "lg", 0),
                   ("Y", "red", "lg", 0), ("H", "blue", "lg", 0)],
         "after": ("Y", "red", "lg", 10)},
        {"changed": 0, "kind": "rotation",
         "flash": [("L", "violet", "lg", 0), ("C", "green", "lg", 0),
                   ("U", "blue", "lg", 0), ("K", "amber", "lg", 0)],
         "after": ("L", "violet", "lg", 10)},
        {"changed": 3, "kind": "rotation",
         "flash": [("R", "teal", "lg", 0), ("S", "red", "lg", 0),
                   ("E", "amber", "lg", 0), ("N", "green", "lg", 0)],
         "after": ("N", "green", "lg", 10)},
    ],
}

# The odd one out. Five umbrellas the same and one whose hook is SHORTER
# rather than mirrored: a hook that curls the other way is a card anybody
# finds in a second, and this round is meant to be the one that catches a
# reader who is skimming. Every variant hides it in a different slot and
# draws the six in a different colour.
ODD_SHORT = 0.62          # the odd hook's share of the others' curve
ODD_VARIANTS = [
    {"set": "a", "colour": "red", "odd": 4},
    {"set": "b", "colour": "teal", "odd": 2},
    {"set": "c", "colour": "violet", "odd": 6},
]

# The word, and the ink it is set in. v11 pairs near misses: a word in the
# colour NEXT to the one it names, so a reader has to read rather than
# glance. Exactly one card tells the truth, and it is the one whose word and
# ink are the same colour.
#
# The near misses are red/amber and blue/violet, and NOT teal/green. Teal is
# a shade of green in ordinary speech, so "GREEN" set in teal is not an
# attention test — it is a disagreement about what the colour is called, and
# a reader who taps it is right by their own naming. The change round pairs
# teal with green happily, because there the reader is comparing two cards
# rather than naming one.
INK_NEAR = {("red", "amber"), ("amber", "red"),
            ("blue", "violet"), ("violet", "blue")}
INK_VARIANTS = [
    {"set": "a", "cards": [("RED", "amber"), ("BLUE", "blue"),
                           ("VIOLET", "blue"), ("AMBER", "red")]},
    {"set": "b", "cards": [("AMBER", "red"), ("VIOLET", "blue"),
                           ("TEAL", "teal"), ("RED", "amber")]},
    {"set": "c", "cards": [("BLUE", "violet"), ("RED", "amber"),
                           ("GREEN", "green"), ("AMBER", "red")]},
]

# The counting round. Uneven scatters — a frame carrying two spots next to a
# frame carrying five — so the total cannot be reached by pattern, and a true
# count that changes between variants so the answer is never in the same place
# twice. The four numbers offered are the true count with two below and one
# above, which is the shape a reader who miscounts by one lands in.
COUNT_VARIANTS = [
    {"set": "a", "total": 11, "answers": ["9", "10", "11", "12"],
     "spots": [
         [(0.26, 0.30), (0.66, 0.22), (0.44, 0.63)],
         [(0.31, 0.24), (0.71, 0.44), (0.22, 0.66), (0.55, 0.75)],
         [(0.50, 0.28), (0.28, 0.62)],
         [(0.24, 0.35), (0.62, 0.28)],
     ]},
    {"set": "b", "total": 12, "answers": ["10", "11", "12", "13"],
     "spots": [
         [(0.30, 0.26), (0.62, 0.35), (0.45, 0.70), (0.74, 0.66),
          (0.22, 0.58)],
         [(0.52, 0.24), (0.26, 0.45)],
         [(0.35, 0.30), (0.70, 0.28), (0.28, 0.70)],
         [(0.60, 0.55), (0.30, 0.35)],
     ]},
    {"set": "c", "total": 13, "answers": ["11", "12", "13", "14"],
     "spots": [
         [(0.28, 0.32), (0.68, 0.26)],
         [(0.24, 0.28), (0.55, 0.40), (0.75, 0.62), (0.34, 0.68),
          (0.62, 0.22), (0.44, 0.55)],
         [(0.50, 0.30), (0.26, 0.60), (0.72, 0.48)],
         [(0.32, 0.38), (0.66, 0.62)],
     ]},
]

# The age groups: the bracket, and a tree at the stage that group is at. The
# card carries the words because this step draws no badge under it — the six
# cards have to be tellable apart from the art alone — and the tree is what
# makes six numbers a row somebody reads left to right rather than six numbers
# they have to compare. Nothing on this funnel is a claim about anybody: a
# sprout and an ancient tree are both trees.
AGES = [("age_21", "18–24", "sprout"), ("age_30", "25–34", "sapling"),
        ("age_40", "35–44", "young"), ("age_50", "45–54", "full"),
        ("age_60", "55–64", "broad"), ("age_70", "65+", "ancient")]

# How the reader says they feel, drawn rather than measured. Four bars at four
# heights were a chart of a thing nobody had measured yet; these are four
# pictures, and a reader picks one the way they would pick a weather symbol.
MOODS = ("mood_sharp", "mood_ok", "mood_foggy", "mood_fumes")

# The word each of those cards used to get from a label. This funnel puts no
# words on any card any more — the art has to be the whole question — so the
# four moods carry theirs. A battery near empty and the words "Running on
# fumes" are the same statement, and with the label gone only one of them is
# left to make it.
MOOD_WORDS = {"mood_sharp": "Sharp", "mood_ok": "Okay",
              "mood_foggy": "Foggy", "mood_fumes": "Running on fumes"}

# --- the pattern round: a dial with two hands -------------------------------
#
# A violet ring with one notch cut out of it, and an amber dot inside. TWO
# things move from frame to frame and the reader has to hold both: the notch
# turns a third of a turn clockwise, and the dot steps one quarter clockwise.
#
# That is the whole round. One attribute progressing is a sequence anybody
# spots at a glance and guesses right on; two is a working-memory task, which
# is what this funnel is measuring. The round this replaces was a triangle
# rotating by itself.
#
# The notch's turn is a third, so after three frames it is back where it
# started — which is what makes the last distractor work. The first frame
# redrawn has the right notch and the wrong dot, and cannot be dismissed by
# anybody who only held one of the two.
DIAL_FRAMES = 3            # frames shown before the question mark

# v11: three versions of the round, and the two hands turn at a different rate
# in each. The structure is the same every time — one card continues BOTH
# progressions, three continue exactly one, and one of those three is a frame
# the flash already showed — but which attribute the repeated frame shares
# changes with the numbers, which is what stops a second run being the same
# puzzle with new pictures.
#
# `rot` is degrees the notch turns per frame and `dots` how many places the
# dot steps through. For the repeat to share exactly one attribute, one of the
# two has to come back where it started after three frames and the other must
# not: (120, 4) brings the notch home, (90, 3) and (72, 3) bring the dot home.
DIAL_VARIANTS = [
    {"rot": 120, "dots": 4},
    {"rot": 90, "dots": 3},
    {"rot": 72, "dots": 3},
]


def dial_name(rot, dot, dots):
    """The file's name states both attributes, so the round can be checked
    off the manifest and the filenames without anybody opening a picture."""
    return "dial_r%d_d%d" % (rot % 360, dot % dots)


def dial_round(spec):
    """One version of the round: the frames, the answer, and the three wrong.

    Everything is derived from the two numbers rather than written out, so a
    variant cannot claim a distractor its own progressions do not produce.
    """
    rot, dots = spec["rot"], spec["dots"]
    seq = [((i * rot) % 360, i % dots) for i in range(DIAL_FRAMES)]
    right = ((DIAL_FRAMES * rot) % 360, DIAL_FRAMES % dots)
    wrong = [
        # the notch continued, the dot two places back
        (right[0], (right[1] - 2) % dots),
        # the dot continued, the notch left where the last frame had it
        ((right[0] - rot) % 360, right[1]),
        # a frame the flash showed, which shares exactly one of the two
        seq[0],
    ]
    return {"seq": seq, "right": right, "wrong": wrong,
            "answers": [right] + wrong, "dots": dots, "rot": rot}

# Eleven circles across four frames, and not in the same place twice. The
# grid of neat spots the round used to draw could be counted by pattern
# rather than by looking — two here, three there, add them up — which is a
# different round from the one this is. Every frame scatters its own, stated
# here rather than rolled, so the same card is drawn every time.
#
#   (x, y) in fractions of the card, per frame
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
    elif name == "leaf":
        # A leaf: two arcs meeting at a tip, one vein and a stem.
        card.d.pieslice([cx - 0.20 * unit, cy - 0.20 * unit,
                         cx + 0.14 * unit, cy + 0.14 * unit],
                        270, 90, fill=GREEN)
        card.d.pieslice([cx - 0.14 * unit, cy - 0.14 * unit,
                         cx + 0.20 * unit, cy + 0.20 * unit],
                        90, 270, fill=GREEN)
        card.d.line([(cx - 0.15 * unit, cy + 0.15 * unit),
                     (cx + 0.16 * unit, cy - 0.16 * unit)],
                    fill=(223, 218, 206), width=int(0.020 * unit))
        card.d.line([(cx - 0.15 * unit, cy + 0.15 * unit),
                     (cx - 0.24 * unit, cy + 0.24 * unit)],
                    fill=GREEN, width=int(0.026 * unit))
    elif name == "bell":
        # A bell: a dome on a lip, with the clapper under it.
        card.d.pieslice([cx - 0.17 * unit, cy - 0.22 * unit,
                         cx + 0.17 * unit, cy + 0.12 * unit],
                        180, 360, fill=AMBER)
        card.d.rectangle([cx - 0.17 * unit, cy - 0.05 * unit,
                          cx + 0.17 * unit, cy + 0.08 * unit], fill=AMBER)
        card.d.rounded_rectangle([cx - 0.22 * unit, cy + 0.08 * unit,
                                  cx + 0.22 * unit, cy + 0.15 * unit],
                                 int(0.035 * unit), fill=AMBER)
        card.d.ellipse([cx - 0.045 * unit, cy + 0.16 * unit,
                        cx + 0.045 * unit, cy + 0.25 * unit], fill=AMBER)
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


# --- round three: letters ---------------------------------------------------
#
# The change round used to be shapes, and on a phone it was the memory round
# again: four coloured forms, four coloured forms, spot the difference. Letters
# read as a different kind of thing at a glance, which is the whole point of
# having four rounds rather than one played four times.
#
# Every letter card names itself. The file is `letter_<L>_<colour>_<size>_
# <degrees>`, and that is not decoration: the round is "exactly one of these
# four came back different", and a filename that states the four things a card
# can differ in is a claim a check can hold the config to without opening a
# single pixel.
# `md` is v11's change-round size: a fifth off `lg` rather than the third
# `sm` took off, which is the difference between a card that is obviously
# smaller and one somebody has to have held the row to notice.
LETTER_SIZES = {"lg": 300, "md": 240, "sm": 190}

# A serif, and a bold one. The quiz's own face is a sans and every other card
# on the funnel is a flat shape; a heavy serif letter is the one thing on this
# walk that could not be mistaken for any of them.
SERIF_FONTS = [
    "/usr/share/fonts/truetype/dejavu/DejaVuSerif-Bold.ttf",
    "/usr/share/fonts/truetype/liberation/LiberationSerif-Bold.ttf",
]


def serif():
    for path in SERIF_FONTS:
        if os.path.exists(path):
            return path
    return None


SERIF = serif()


def tint(colour, amount=0.82):
    """The colour, most of the way to the ground. The block behind a letter."""
    return tuple(int(round(colour[i] + (GROUND[i] - colour[i]) * amount))
                 for i in range(3))


def letter_name(letter, colour, size, rot):
    return "letter_%s_%s_%s_%d" % (letter, colour, size, rot)


def letter_card(letter, colour, size="lg", rot=0):
    """One letter, on a block of its own colour, turned if it is turned.

    Drawn into a layer and pasted rather than drawn straight onto the card,
    because Pillow will not rotate text in place and the rotated round is the
    reason this exists. The block does not turn with it: it is the ground the
    letter sits on, and a ground that tilted would be a second difference on a
    round that is allowed exactly one.
    """
    if not SERIF:
        raise RuntimeError("no usable serif on this machine")
    card = Card()
    unit = card.w * SS
    card.rect((0.29, 0.29, 0.75, 0.75), tint(PALETTE[colour]), radius=0.055)
    layer = Image.new("RGBA", (int(unit), int(unit)), (0, 0, 0, 0))
    draw = ImageDraw.Draw(layer)
    font = ImageFont.truetype(SERIF, int(LETTER_SIZES[size] * SS))
    box = draw.textbbox((0, 0), letter, font=font)
    draw.text((unit / 2.0 - (box[2] - box[0]) / 2.0 - box[0],
               unit / 2.0 - (box[3] - box[1]) / 2.0 - box[1]),
              letter, font=font, fill=PALETTE[colour] + (255,))
    if rot:
        layer = layer.rotate(rot, resample=Image.BICUBIC,
                             center=(unit / 2.0, unit / 2.0))
    card.img.paste(layer, (0, 0), layer)
    return card


# Four rounds, and the one thing that changes in each. `flash` is the set as it
# was held up; `after` is what the changed slot comes back as. The letters
# inside a round are chosen to be unmistakable for each other at a glance —
# nothing that pairs off as I and l, or O and Q.
#
#   (letter, colour, size, degrees)
# --- the odd one out: umbrellas ---------------------------------------------
#
# Six of them, and one has its handle hooked the other way. Written as six
# files rather than as one file used five times and a second used once,
# because the answer to this round would otherwise be readable off the page
# source: five identical `src` attributes and one that is not is a round
# anybody can win with the inspector open. Five of the six are byte for byte
# the same drawing; only the sixth is a different picture.
UMBRELLA_SLOTS = 6
def umbrella_card(flipped=False, colour=None, short=False):
    """A canopy, a pole, and a hook that curves one way or the other."""
    card = Card()
    unit = card.w * SS
    cx = 0.5 * unit
    rim = 0.52 * unit
    span = 0.30 * unit
    # The canopy: a half disc, notched along its rim so it reads as panels
    # rather than as a semicircle.
    card.d.pieslice([cx - span, rim - span, cx + span, rim + span],
                    180, 360, fill=colour or RED)
    for offset in (-0.20, 0.0, 0.20):
        notch = 0.078 * unit
        card.d.ellipse([cx + offset * unit - notch, rim - notch,
                        cx + offset * unit + notch, rim + notch],
                       fill=GROUND)
    # The pole, from under the canopy to where the hook starts.
    pole = 0.017 * unit
    card.d.rectangle([cx - pole, rim - 0.02 * unit, cx + pole, 0.74 * unit],
                     fill=INK)
    # The hook. v11 makes the odd card's hook SHORTER rather than mirrored: a
    # hook that curls the other way is a card anybody finds at a glance, and
    # this is the round that is supposed to catch a reader who is skimming.
    # `flipped` is kept for the funnels drawn before that change.
    #
    # The arc runs clockwise from three o'clock and its box is placed so the
    # pole meets it at 180 degrees, so a shorter hook is trimmed from the
    # START — trimmed from the end it comes away from the pole and reads as a
    # comma rather than as a handle.
    hook = 0.075 * unit
    side = -1 if flipped else 1
    left = cx if side > 0 else cx - 2 * hook
    sweep = 180 * (ODD_SHORT if short else 1.0)
    card.d.arc([left, 0.74 * unit - hook, left + 2 * hook, 0.74 * unit + hook],
               180 - sweep if side > 0 else 0,
               180 if side > 0 else sweep,
               fill=INK, width=int(2 * pole))
    return card


def dial_card(rot, dot, dots=4):
    """One frame of the pattern round: a notched ring and an inner dot.

    Both angles are measured clockwise from twelve, which is how a reader
    reads a dial; Pillow measures from three, which is the -90 below and the
    only place that difference appears.
    """
    card = Card()
    unit = card.w * SS
    cx = cy = 0.5 * unit
    ring = 0.315 * unit
    stroke = int(0.042 * unit)
    # The ring, drawn as an arc with a piece missing rather than a full circle
    # with something painted over it: a notch is the absence, and an absence
    # drawn as a ground-coloured bar shows its own edges the moment the card
    # sits on anything but the ground.
    gap = 15.0                       # half the notch, in degrees of arc
    start = (rot - 90) + gap
    card.d.arc([cx - ring, cy - ring, cx + ring, cy + ring],
               start=start, end=start + (360 - 2 * gap),
               fill=VIOLET, width=stroke)
    # The dot, on its own smaller circle. Amber, because the two attributes
    # have to be told apart at a glance under a five-second clock, and two
    # violet marks on one card is one mark the eye has to resolve.
    step = 360.0 / dots
    angle = math.radians(dot * step)
    inner = 0.155
    card.shape("circle", AMBER,
               cx=0.5 + math.sin(angle) * inner,
               cy=0.5 - math.cos(angle) * inner,
               r=0.075)
    return card


def circles(spots):
    """The circles this frame carries, where the table puts them."""
    card = Card()
    for x, y in spots:
        card.shape("circle", AMBER, cx=x, cy=y, r=0.105)
    return card


# The six stages, each a trunk and a canopy. Stated as numbers rather than
# drawn per stage: a sprout and an ancient tree differ in how tall the trunk
# is, how thick it is, and how many rounds of canopy sit on it, and writing
# that as a table keeps the six a sequence instead of six drawings that happen
# to be in the same file.
#
#   trunk height, trunk width, canopy blobs as (dx, dy, r), roots
TREES = {
    "sprout":  (0.09, 0.016, [(0.0, -0.02, 0.045)], 0),
    "sapling": (0.15, 0.022, [(0.0, -0.03, 0.075)], 0),
    "young":   (0.19, 0.030, [(0.0, -0.04, 0.105)], 0),
    "full":    (0.21, 0.040, [(-0.075, 0.005, 0.090),
                              (0.075, 0.005, 0.090),
                              (0.0, -0.065, 0.105)], 0),
    "broad":   (0.20, 0.052, [(-0.125, 0.020, 0.090),
                              (0.125, 0.020, 0.090),
                              (-0.060, -0.045, 0.105),
                              (0.060, -0.045, 0.105),
                              (0.0, -0.100, 0.095)], 0),
    "ancient": (0.19, 0.068, [(-0.155, 0.030, 0.085),
                              (0.155, 0.030, 0.085),
                              (-0.080, -0.040, 0.110),
                              (0.080, -0.040, 0.110),
                              (0.0, -0.110, 0.105)], 2),
}


# The whole sequence, scaled once. The table above is written as proportions
# of each other so the six read as one plant growing; this is how much room
# that plant is given on the card, and it is a number here rather than six
# numbers there.
TREE_SCALE = 1.18

# Where the tree stands on the card.
AGE_BASE_Y = 0.84

# The age card is a tile, and the tile is drawn here rather than in the
# stylesheet. On a phone the six of them were six numbers floating on the page
# ground: the card's own background is behind the picture, the picture filled
# it edge to edge, and the picture was the same off-white as everything else.
# So the ground of THIS card is a shade of its own — sage over the cream, far
# enough off it to read as a surface at arm's length.
#
# The tint is now the whole of it. A keyline inside the edge and a line under
# the tree were both drawn here and both came off after the second phone
# review: on a 175px cell the keyline read as a second border a few pixels
# inside the card's own, and the floor read as an underline under nothing. The
# colour was doing the work; the two rules were arguing with it.
AGE_PANEL_FILL = (224, 229, 211)

# How much air sits between the bottom of the numeral and the top of the
# leaves. The number and the tree are one figure — the bracket labelled by the
# thing that grew that far — and the gap is what says so.
AGE_NUMERAL_GAP = 0.030
AGE_NUMERAL_SIZE = 100


def canopy_top(stage):
    """Where the leaves start on one stage, as a fraction of the card."""
    height, _width, canopy, _roots = TREES[stage]
    top = AGE_BASE_Y - height * TREE_SCALE
    return min(top + (dy - r) * TREE_SCALE for _dx, dy, r in canopy)


def numeral_bottom(stage):
    """Where the bracket's feet go on one stage. Follows the leaves."""
    return canopy_top(stage) - AGE_NUMERAL_GAP


def tree(card, stage, base_y=AGE_BASE_Y, colour=GREEN, bark=(122, 92, 62)):
    """One tree, grown from the table above, standing on `base_y`."""
    height, width, canopy, roots = TREES[stage]
    height *= TREE_SCALE
    width *= TREE_SCALE
    canopy = [(dx * TREE_SCALE, dy * TREE_SCALE, r * TREE_SCALE)
              for dx, dy, r in canopy]
    unit = card.w * SS
    cx = 0.5 * unit
    foot = base_y * unit
    top = foot - height * unit
    # The two exposed roots the oldest stage gets, drawn before the trunk so
    # the trunk closes over where they meet it.
    for side in range(roots):
        sign = -1 if side == 0 else 1
        card.d.polygon([(cx, foot - 0.02 * unit),
                        (cx + sign * 0.085 * unit, foot + 0.012 * unit),
                        (cx + sign * 0.085 * unit, foot + 0.030 * unit),
                        (cx, foot)], fill=bark)
    card.d.rounded_rectangle(
        [cx - width * unit, top, cx + width * unit, foot],
        width * unit, fill=bark)
    for dx, dy, r in canopy:
        card.shape("circle", colour,
                   cx=0.5 + dx, cy=(top / unit) + dy, r=r)


def age_card(text, stage):
    """The bracket over the stage it stands at, on a tile of its own."""
    card = Card(ground=AGE_PANEL_FILL)
    tree(card, stage)
    card.text_above(text, AGE_NUMERAL_SIZE, numeral_bottom(stage))
    return card


def mood_card(name):
    """One of four pictures of how sharp somebody says they feel.

    A picture rather than a quantity: a bar at four heights is a chart of
    something nobody has measured yet, and the reader is being asked how they
    feel rather than to read one.
    """
    card = Card()
    unit = card.w * SS
    # Every picture below sits a little higher than it used to: the bottom of
    # the card is the word's now.
    cx, cy = 0.5 * unit, 0.435 * unit
    if name == "mood_sharp":
        # A bolt inside a lit ring. Two rings rather than one, the outer
        # thinner and set off — the same "this one is switched on" the
        # timer's glow says elsewhere on the funnel.
        card.d.ellipse([cx - 0.30 * unit, cy - 0.30 * unit,
                        cx + 0.30 * unit, cy + 0.30 * unit],
                       outline=AMBER, width=int(0.010 * unit))
        card.d.ellipse([cx - 0.245 * unit, cy - 0.245 * unit,
                        cx + 0.245 * unit, cy + 0.245 * unit],
                       outline=AMBER, width=int(0.028 * unit))
        card.d.polygon([(cx + 0.045 * unit, cy - 0.165 * unit),
                        (cx - 0.105 * unit, cy + 0.020 * unit),
                        (cx - 0.010 * unit, cy + 0.020 * unit),
                        (cx - 0.045 * unit, cy + 0.165 * unit),
                        (cx + 0.105 * unit, cy - 0.020 * unit),
                        (cx + 0.010 * unit, cy - 0.020 * unit)], fill=AMBER)
    elif name == "mood_ok":
        # A sun most of the way out from behind one small cloud.
        card.shape("circle", AMBER, cx=0.44, cy=0.355, r=0.145)
        for i in range(8):
            angle = math.radians(i * 45.0)
            x0 = 0.44 * unit + math.cos(angle) * 0.185 * unit
            y0 = 0.355 * unit + math.sin(angle) * 0.185 * unit
            x1 = 0.44 * unit + math.cos(angle) * 0.245 * unit
            y1 = 0.355 * unit + math.sin(angle) * 0.245 * unit
            card.d.line([(x0, y0), (x1, y1)], fill=AMBER,
                        width=int(0.020 * unit))
        cloud = (196, 202, 212)
        for dx, dy, r in ((-0.085, 0.0, 0.085), (0.020, -0.030, 0.105),
                          (0.115, 0.010, 0.080)):
            card.shape("circle", cloud, cx=0.56 + dx, cy=0.565 + dy, r=r)
        card.rect((0.435, 0.565, 0.705, 0.647), cloud, radius=0.041)
    elif name == "mood_foggy":
        # Bands, lightest at the top, so the card reads as something settling
        # rather than as three grey rules.
        bands = ((0.20, 0.175, 0.80, (214, 218, 224)),
                 (0.14, 0.315, 0.86, (198, 203, 212)),
                 (0.24, 0.455, 0.76, (181, 187, 199)),
                 (0.16, 0.595, 0.84, (163, 170, 184)))
        for x0, y, x1, tone in bands:
            card.rect((x0, y, x1, y + 0.085), tone, radius=0.042)
    else:
        # A battery with almost nothing in it, and the terminal on the end so
        # it reads as a battery at a glance rather than as a bar.
        card.rect((0.185, 0.310, 0.760, 0.560), (206, 210, 218), radius=0.035)
        card.rect((0.215, 0.340, 0.730, 0.530), GROUND, radius=0.022)
        card.rect((0.235, 0.360, 0.290, 0.510), RED, radius=0.014)
        card.rect((0.775, 0.390, 0.830, 0.480), (206, 210, 218), radius=0.020)
    word_under(card, MOOD_WORDS[name])
    return card


def word_under(card, text, bottom=0.885, size=58, width=0.84):
    """`text` centred across the card with its feet at `bottom`.

    Sized by measurement rather than by a number per card: the four words this
    draws are "Sharp" and "Running on fumes", and one type size that suits
    both does not exist. It shrinks until the longest fits and stops there.
    """
    if not BOLD:
        raise RuntimeError("no usable font on this machine")
    limit = width * card.w * SS
    while size > 22:
        font = ImageFont.truetype(BOLD, int(size * SS))
        box = card.d.textbbox((0, 0), text, font=font)
        if box[2] - box[0] <= limit:
            break
        size -= 2
    card.text_above(text, size, bottom)


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



# --- the intro brain --------------------------------------------------------
#
# v11 draws the picture the funnel is actually about: a head in profile with
# the brain inside it, in line art. The versions before it were a brain on its
# own, and a brain on its own is a diagram — this is a person, which is what
# the reader is being asked about.
#
# Everything is one weight of line with round caps and round joins. There are
# no fills except the pale tint inside the skull, no facial detail beyond the
# profile itself, and nothing crosses anything: the folds are one family of
# ribbons running the way the lobe does, because two families is a net and a
# net is not a brain.
#
# Two of it, facing each way. `INTRO_FACING` says which ships.

# Drawn at 3x the ~200px the card shows it at, which covers the densest
# screen this funnel meets. It carries an alpha channel, which costs more per
# pixel than every other file here, so it is not drawn larger than that.
INTRO = (600, 465)
INTRO_FACING = "left"

# ~2% of the width. Thicker and the eight ribbons merge into a block at the
# two hundred pixels the intro card shows this at; thinner and the whole
# drawing disappears there.
INTRO_STROKE = 0.019
INTRO_FACE = (24, 95, 165)      # the head's own line
INTRO_FOLD = (55, 138, 221)     # the brain's
INTRO_TINT = (230, 241, 251)    # the only fill in the picture


def curve_bez(p0, p1, p2, p3, n=34):
    """A cubic through four control points, as a list of points."""
    out = []
    for i in range(n + 1):
        t = i / float(n)
        u = 1 - t
        out.append((u * u * u * p0[0] + 3 * u * u * t * p1[0]
                    + 3 * u * t * t * p2[0] + t * t * t * p3[0],
                    u * u * u * p0[1] + 3 * u * u * t * p1[1]
                    + 3 * u * t * t * p2[1] + t * t * t * p3[1]))
    return out


def curve_path(w, h, spec, close=False):
    """Several cubics, written in fractions, joined into one point list."""
    pts = []
    for i, seg in enumerate(spec):
        got = curve_bez(*[(p[0] * w, p[1] * h) for p in seg])
        pts += got if i == 0 else got[1:]
    if close:
        pts.append(pts[0])
    return pts


def stroke_path(d, line, colour, width):
    """One path at one weight, with round caps and round joins.

    Pillow draws a wide polyline as a rectangle per segment plus a join, and
    at this weight the seams show as fringe along the edge. A disc stamped at
    every vertex fills them — which is what a round join is.
    """
    d.line(line, fill=colour, width=width, joint="curve")
    r = width / 2.0
    for x, y in line:
        d.ellipse([x - r, y - r, x + r, y + r], fill=colour)


# The face, facing left: one line from the crown down the forehead, over the
# brow, out to the nose, in to the lip, out over the chin and down the jaw to
# the neck — and off the bottom of the picture rather than closing, because a
# closed outline draws a bar across the throat.
HEAD_FACE = [
    [(.500, .075), (.310, .075), (.215, .190), (.212, .300)],
    [(.212, .300), (.210, .355), (.196, .375), (.196, .400)],
    [(.196, .400), (.196, .430), (.128, .500), (.140, .530)],
    [(.140, .530), (.150, .552), (.205, .548), (.214, .566)],
    [(.214, .566), (.222, .582), (.196, .600), (.200, .620)],
    [(.200, .620), (.204, .642), (.244, .646), (.252, .668)],
    [(.252, .668), (.262, .700), (.236, .742), (.286, .790)],
    [(.286, .790), (.330, .832), (.404, .846), (.470, .848)],
    [(.470, .848), (.468, .900), (.466, .960), (.466, 1.04)],
]

# And the back of it, from the nape up over the skull to the crown.
HEAD_BACK = [
    [(.752, 1.04), (.752, .900), (.744, .845), (.740, .800)],
    [(.740, .800), (.736, .700), (.790, .620), (.800, .520)],
    [(.800, .520), (.812, .330), (.690, .075), (.500, .075)],
]

# The brain, inside the cranium with air between it and the skull.
HEAD_BRAIN = [
    [(.296, .192), (.404, .142), (.578, .144), (.680, .210)],
    [(.680, .210), (.764, .268), (.776, .398), (.718, .476)],
    [(.718, .476), (.664, .546), (.508, .570), (.398, .538)],
    [(.398, .538), (.308, .510), (.264, .408), (.270, .300)],
    [(.270, .300), (.272, .244), (.280, .210), (.296, .192)],
]

# Eight folds, and each one snakes: a fold under a dome does not run straight
# across, and eight straight ones inside a head is a ruled notepad. Two cubics
# per ribbon, bending one way and then the other, with the bend alternating
# from ribbon to ribbon so no two lie parallel.
RIBBON_N = 8
RIBBON_X0 = .262
RIBBON_X1 = .786
RIBBON_TOP_Y = .268
RIBBON_STEP = .0375
RIBBON_BEND = .0225
RIBBON_ARCH = .048          # how much the top ones follow the crown


def ribbons():
    """Every fold: two cubics that bend one way and then the other.

    The arch is the dome the fold is under and it eases off as the family
    steps down; the bend is the snake in the fold itself.
    """
    out = []
    for k in range(RIBBON_N):
        y = RIBBON_TOP_Y + RIBBON_STEP * k
        arch = RIBBON_ARCH * (1.0 - k / float(RIBBON_N))
        bend = RIBBON_BEND * (1 if k % 2 == 0 else -1)
        mid = (RIBBON_X0 + RIBBON_X1) / 2.0
        q = (mid - RIBBON_X0) / 3.0
        out.append([
            [(RIBBON_X0, y), (RIBBON_X0 + q, y - arch - bend),
             (mid - q, y - arch + bend), (mid, y - arch * 0.75)],
            [(mid, y - arch * 0.75), (mid + q, y - arch - bend),
             (RIBBON_X1 - q, y - arch * 0.4 + bend), (RIBBON_X1, y)],
        ])
    return out


def brain_intro(facing=None):
    facing = facing or INTRO_FACING
    card = Card(INTRO[0], INTRO[1])
    # The one card with no ground of its own. Every other file here is a
    # square the reader compares against another square, so it carries the
    # off-white they all sit on; this one sits on the intro screen and has to
    # take that screen's background, whatever a funnel sets it to.
    card.img = Image.new("RGBA", card.img.size, (0, 0, 0, 0))
    card.d = ImageDraw.Draw(card.img)
    w, h = card.w * SS, card.h * SS
    width = max(3, int(INTRO_STROKE * w))
    mirror = facing == "right"

    def pts(spec, close=False):
        got = curve_path(w, h, spec, close)
        return [((w - x) if mirror else x, y) for x, y in got]

    brain = pts(HEAD_BRAIN, True)
    card.d.polygon(brain, fill=INTRO_TINT)
    for spec in (HEAD_FACE, HEAD_BACK):
        stroke_path(card.d, pts(spec), INTRO_FACE, width)
    stroke_path(card.d, brain, INTRO_FOLD, width)

    # The folds go on their own layer and are stamped through the brain's own
    # shape, pulled in by the line's width: a ribbon running past the edge
    # would be a fold outside the skull.
    layer = Image.new("L", (w, h), 0)
    ld = ImageDraw.Draw(layer)
    for ribbon in ribbons():
        stroke_path(ld, pts(ribbon), 255, width)
    inside = Image.new("L", (w, h), 0)
    ImageDraw.Draw(inside).polygon(brain, fill=255)
    ImageDraw.Draw(inside).line(brain, fill=0, width=int(width * 2.4),
                                joint="curve")
    card.img.paste(Image.new("RGBA", (w, h), INTRO_FOLD + (255,)), (0, 0),
                   ImageChops.multiply(layer, inside))
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

    for card_id, text, stage in AGES:
        put(age_card(text, stage), card_id)
    for card_id in MOODS:
        put(mood_card(card_id), card_id)

    # v11: the shape library the memory rounds share. Named by what the card
    # is, so three versions of a round draw on one set of pictures instead of
    # writing three copies of a red circle.
    for variants in MEMORY_VARIANTS.values():
        for variant in variants:
            for colour, form in variant["flash"] + variant["decoys"]:
                name = shape_name(colour, form)
                if name not in written:
                    put(plain(colour, form), name)

    put(box(), "box_closed")
    for name in sorted({v["object"] for vs in SPATIAL_VARIANTS.values()
                        for v in vs}):
        put(box(name), "box_open_" + name)

    # Every letter a round draws, its own name on it. The unchanged three
    # slots of a step are the same files their flash held, so a round writes
    # five files rather than eight — and two versions that happen to share a
    # letter share its file too.
    for variants in CHANGE_VARIANTS.values():
        for variant in variants:
            for spec in variant["flash"] + [variant["after"]]:
                name = letter_name(*spec)
                if name not in written:
                    put(letter_card(*spec), name)

    # Six umbrellas per version, written as six files rather than as one used
    # five times and a second used once: five identical `src` attributes and
    # one that is not would be a round anybody wins with the inspector open.
    for variant in ODD_VARIANTS:
        for slot in range(1, UMBRELLA_SLOTS + 1):
            put(umbrella_card(colour=PALETTE[variant["colour"]],
                              short=(slot == variant["odd"])),
                "umb_%s_s%d" % (variant["set"], slot))

    for variant in INK_VARIANTS:
        for i, (text, ink) in enumerate(variant["cards"], start=1):
            put(word(text, 76, PALETTE[ink]),
                "ink_%s_%d" % (variant["set"], i))

    # The dials. Deduplicated by name, because the last of each version's
    # three wrong cards IS its first frame and the round works precisely
    # because it is the same picture.
    for spec in DIAL_VARIANTS:
        plan = dial_round(spec)
        for rot, dot in plan["seq"] + plan["answers"]:
            name = dial_name(rot, dot, plan["dots"])
            if name not in written:
                put(dial_card(rot, dot, plan["dots"]), name)
    put(word("?", 150, (150, 152, 158)), "nxt_qm")

    for variant in COUNT_VARIANTS:
        for i, spots in enumerate(variant["spots"], start=1):
            put(circles(spots), "cnt_%s_f%d" % (variant["set"], i))
    for text in sorted({n for v in COUNT_VARIANTS for n in v["answers"]},
                       key=int):
        put(word(text, 130), "cnt_" + text)

    for style_id, name, form, colour in TYPES:
        put(share_card(name, form, colour), "share_" + style_id)

    # Facing left, which is where the funnel's own picture has always faced
    # and where a reader's eye enters the card. `INTRO_FACING = "right"` draws
    # the mirror of it.
    put(brain_intro(), "brain_intro", quality=74)
    put(og_card(), "og", quality=70)

    biggest = max(written,
                  key=lambda n: os.path.getsize(os.path.join(OUT, n + ".webp")))
    print("%d files written to %s" % (len(written), OUT))
    print("largest: %s.webp at %d bytes"
          % (biggest, os.path.getsize(os.path.join(OUT, biggest + ".webp"))))


if __name__ == "__main__":
    main()
