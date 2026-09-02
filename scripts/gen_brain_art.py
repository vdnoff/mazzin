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
    # The last memory round answers on a six-up rather than a four, which is
    # the whole of what makes it the hardest one: six frames held for two and
    # a half seconds, and then one of six to find rather than one of four.
    {"seen": 2,
     "flash": [("green", "square"), ("teal", "star"),
               ("blue", "pentagon"), ("amber", "diamond"),
               ("violet", "circle"), ("red", "triangle")],
     "decoys": [("teal", "hexagon"), ("amber", "cross"),
                ("green", "circle"), ("violet", "diamond"),
                ("blue", "hexagon")]},
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

# The word, and the ink it is set in. Exactly one card tells the truth.
INKS = [("ink_1", "RED", BLUE), ("ink_2", "BLUE", BLUE),
        ("ink_3", "GREEN", AMBER), ("ink_4", "AMBER", RED)]

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
DIAL_ROT_STEP = 120        # degrees the notch turns per frame, clockwise
DIAL_DOTS = 4              # places the dot steps through, clockwise from 12
DIAL_FRAMES = 3            # frames shown before the question mark


def dial_name(rot, dot):
    """The file's name states both attributes, so the round can be checked
    off the manifest and the filenames without anybody opening a picture."""
    return "dial_r%d_d%d" % (rot % 360, dot % DIAL_DOTS)


# The three frames the flash shows.
DIAL_SEQUENCE = [(i * DIAL_ROT_STEP, i) for i in range(DIAL_FRAMES)]

# The one card that continues BOTH progressions — the notch turned once more,
# the dot stepped once more.
DIAL_NEXT = (DIAL_FRAMES * DIAL_ROT_STEP, DIAL_FRAMES)

# And the three that continue exactly one of them. Every one of these is a
# card somebody who held half the pattern would tap.
DIAL_WRONG = [
    # the notch continued, the dot left two places back
    (DIAL_NEXT[0], DIAL_NEXT[1] - 2),
    # the dot continued, the notch left where the last frame had it
    (DIAL_NEXT[0] - DIAL_ROT_STEP, DIAL_NEXT[1]),
    # the first frame, redrawn: right notch, wrong dot
    DIAL_SEQUENCE[0],
]

# Which candidate carries `foc_hit`, and which of the wrong three the clock
# presses when it runs out. Stated here so the config and the art cannot
# disagree about which picture is the right answer.
DIAL_ANSWERS = [DIAL_NEXT] + DIAL_WRONG

# Eleven circles across four frames, and not in the same place twice. The
# grid of neat spots the round used to draw could be counted by pattern
# rather than by looking — two here, three there, add them up — which is a
# different round from the one this is. Every frame scatters its own, stated
# here rather than rolled, so the same card is drawn every time.
#
#   (x, y) in fractions of the card, per frame
COUNT_SPOTS = [
    [(0.26, 0.30), (0.66, 0.22), (0.44, 0.63)],
    [(0.31, 0.24), (0.71, 0.44), (0.22, 0.66)],
    [(0.50, 0.28), (0.28, 0.62)],
    [(0.24, 0.35), (0.62, 0.28), (0.75, 0.65)],
]
COUNT_TOTAL = 11
COUNT_ANSWERS = ["9", "10", "11", "12"]

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
LETTER_SIZES = {"lg": 300, "sm": 190}

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
LETTERS = [
    {"changed": 1, "kind": "letter",
     "flash": [("A", "red", "lg", 0), ("K", "blue", "lg", 0),
               ("R", "green", "lg", 0), ("M", "amber", "lg", 0)],
     "after": ("E", "blue", "lg", 0)},
    {"changed": 3, "kind": "colour",
     "flash": [("S", "violet", "lg", 0), ("T", "teal", "lg", 0),
               ("B", "red", "lg", 0), ("G", "green", "lg", 0)],
     "after": ("G", "amber", "lg", 0)},
    {"changed": 0, "kind": "size",
     "flash": [("W", "green", "lg", 0), ("F", "blue", "lg", 0),
               ("N", "amber", "lg", 0), ("Z", "violet", "lg", 0)],
     "after": ("W", "green", "sm", 0)},
    # Fifteen degrees rather than twenty-five. At twenty-five the round was
    # the easiest of the four and it is meant to be the hardest: a letter
    # that has plainly fallen over is not a change anybody has to look for.
    {"changed": 2, "kind": "rotation",
     "flash": [("D", "amber", "lg", 0), ("P", "teal", "lg", 0),
               ("Y", "red", "lg", 0), ("H", "blue", "lg", 0)],
     "after": ("Y", "red", "lg", 15)},
]


# --- the odd one out: umbrellas ---------------------------------------------
#
# Six of them, and one has its handle hooked the other way. Written as six
# files rather than as one file used five times and a second used once,
# because the answer to this round would otherwise be readable off the page
# source: five identical `src` attributes and one that is not is a round
# anybody can win with the inspector open. Five of the six are byte for byte
# the same drawing; only the sixth is a different picture.
UMBRELLA_SLOTS = 6
UMBRELLA_ODD = 4          # one-based, the slot whose handle turns the other way


def umbrella_card(flipped=False):
    """A canopy, a pole, and a hook that curves one way or the other."""
    card = Card()
    unit = card.w * SS
    cx = 0.5 * unit
    rim = 0.52 * unit
    span = 0.30 * unit
    # The canopy: a half disc, notched along its rim so it reads as panels
    # rather than as a semicircle.
    card.d.pieslice([cx - span, rim - span, cx + span, rim + span],
                    180, 360, fill=RED)
    for offset in (-0.20, 0.0, 0.20):
        notch = 0.078 * unit
        card.d.ellipse([cx + offset * unit - notch, rim - notch,
                        cx + offset * unit + notch, rim + notch],
                       fill=GROUND)
    # The pole, from under the canopy to where the hook starts.
    pole = 0.017 * unit
    card.d.rectangle([cx - pole, rim - 0.02 * unit, cx + pole, 0.74 * unit],
                     fill=INK)
    # The hook. A half turn either to the left or to the right, which is the
    # only difference between the odd card and the other five.
    hook = 0.075 * unit
    side = -1 if flipped else 1
    left = cx if side > 0 else cx - 2 * hook
    card.d.arc([left, 0.74 * unit - hook, left + 2 * hook, 0.74 * unit + hook],
               0, 180, fill=INK, width=int(2 * pole))
    return card


def dial_card(rot, dot):
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
    step = 360.0 / DIAL_DOTS
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
# One illustration, drawn rather than traced: a flat side-profile brain in the
# funnel's blues, facing left. It is the only picture on the intro screen and
# it is displayed about 200px wide, so the silhouette does the work — the
# frontal bulge, the temporal lobe hanging forward under its notch, the
# cerebellum as a striated wedge inside the back-lower edge. The folds are
# texture, not anatomy, and the rule they follow is that they never cross:
# each family is one curve stepped along a direction, and the families are
# clipped to regions that do not overlap.

# Drawn well over the ~200px it is shown at, so a 3x screen still
# gets a clean edge, and no further: it carries an alpha channel,
# which costs more per pixel than every other file here.
INTRO = (680, 527)
BRAIN_FILL = (214, 232, 249)
BRAIN_FOLD = (55, 138, 221)     # #378ADD, the pill's border
BRAIN_EDGE = (26, 86, 155)


def curve_bez(p0, p1, p2, p3, n=44):
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


def curve_path(w, h, spec):
    """Several cubics, written in fractions, joined into one point list."""
    pts = []
    for i, seg in enumerate(spec):
        got = curve_bez(*[(p[0] * w, p[1] * h) for p in seg])
        pts += got if i == 0 else got[1:]
    return pts


CEREBRUM = [
    [(.08, .44), (.09, .19), (.28, .06), (.47, .06)],
    [(.47, .06), (.70, .06), (.90, .19), (.92, .42)],
    [(.92, .42), (.94, .60), (.86, .74), (.74, .79)],
    [(.74, .79), (.66, .82), (.58, .81), (.52, .76)],
    [(.52, .76), (.47, .72), (.45, .79), (.38, .81)],
    [(.38, .81), (.29, .83), (.21, .77), (.19, .69)],
    [(.19, .69), (.18, .63), (.20, .59), (.17, .555)],
    [(.17, .555), (.13, .53), (.085, .50), (.08, .44)],
]
CEREBELLUM = [
    [(.60, .58), (.72, .58), (.78, .65), (.72, .73)],
    [(.72, .73), (.64, .78), (.56, .75), (.55, .68)],
    [(.55, .68), (.55, .62), (.57, .58), (.60, .58)],
]
SYLVIAN = [[(.175, .555), (.26, .625), (.34, .625), (.41, .655)]]
TUCK = [[(.55, .62), (.60, .57), (.70, .57), (.78, .63)]]

# Each family: the first fold, the direction the rest of it steps in, how
# many, how much the ends pull in as it steps, and the region it is clipped
# to. The regions tile the silhouette, so no fold of one family can ever meet
# a fold of another.
FOLD_FAMILIES = [
    dict(pts=[(.20, .30), (.34, .16), (.55, .15), (.70, .24)],
         step=(.000, .060), count=6, squeeze=.03,
         region=[(.28, .00), (.70, .00), (.70, .58), (.28, .52)]),
    dict(pts=[(.13, .26), (.23, .32), (.28, .42), (.25, .49)],
         step=(.048, -.008), count=4, squeeze=.00,
         region=[(.05, .00), (.28, .00), (.28, .52), (.05, .48)]),
    dict(pts=[(.22, .66), (.32, .72), (.44, .69), (.54, .74)],
         step=(.000, .036), count=3, squeeze=.02,
         region=[(.10, .55), (.58, .60), (.58, .95), (.10, .95)]),
    dict(pts=[(.72, .18), (.85, .28), (.87, .44), (.80, .56)],
         step=(-.048, .004), count=5, squeeze=.00,
         region=[(.70, .00), (1.0, .00), (1.0, .58), (.70, .58)]),
]

# Where each fold breaks. A gyrus is not a contour line: it stops, and
# another one starts beside it. Read as (start, run) along the curve.
FOLD_CUTS = [((.00, .46), (.52, .48)),
             ((.00, .30), (.36, .28), (.70, .30)),
             ((.06, .40), (.52, .44)),
             ((.00, .34), (.40, .32), (.78, .22)),
             ((.10, .44), (.60, .38)),
             ((.00, .26), (.32, .34), (.72, .26))]


def fold_wander(curve, amp, period, phase):
    """A curve pushed off its own line by a slow sine along its normals, so
    that two folds of a family stay apart without staying parallel."""
    out = []
    n = len(curve)
    for i, (x, y) in enumerate(curve):
        px, py = curve[max(0, i - 1)]
        nx, ny = curve[min(n - 1, i + 1)]
        tx, ty = nx - px, ny - py
        length = math.hypot(tx, ty) or 1.0
        k = amp * math.sin(i / float(n) * period * math.tau + phase)
        out.append((x + (ty / length) * k, y - (tx / length) * k))
    return out


def fold_snip(curve, cuts):
    """One fold broken into the two or three `cuts` name, with gaps."""
    n = len(curve)
    out = []
    for start, run in cuts:
        a = int(start * n)
        b = min(n, a + int(run * n))
        if b - a > 3:
            out.append(curve[a:b])
    return out


def fold_family(w, h, pts, step, count, squeeze):
    """Every stroke one family contributes, already broken and wandering."""
    out = []
    for k in range(count):
        moved = []
        for i, (x, y) in enumerate(pts):
            f = i / 3.0
            sx = x + step[0] * k + squeeze * k * (0.5 - abs(f - 0.5)) * \
                (1 if x > 0.5 else -1)
            sy = y + step[1] * k
            moved.append((sx * w, sy * h))
        curve = fold_wander(curve_bez(*moved), 0.011 * h,
                            2.4 + (k % 3) * 0.7, k * 1.6)
        out += fold_snip(curve, FOLD_CUTS[k % len(FOLD_CUTS)])
    return out


def brain_intro():
    card = Card(INTRO[0], INTRO[1])
    # The one card with no ground of its own. Every other file here is a
    # square the reader compares against another square, so it carries the
    # off-white they all sit on; this one sits on the intro screen and has to
    # take that screen's background, whatever a funnel sets it to.
    card.img = Image.new("RGBA", card.img.size, (0, 0, 0, 0))
    card.d = ImageDraw.Draw(card.img)
    w, h = card.w * SS, card.h * SS
    poly = curve_path(w, h, CEREBRUM)
    mask = Image.new("L", (w, h), 0)
    ImageDraw.Draw(mask).polygon(poly, fill=255)

    body = Image.new("RGB", (w, h), BRAIN_FILL)
    cere = curve_path(w, h, CEREBELLUM)

    # The folds go on their own layer so they can be kept off the outline,
    # out of the cerebellum's wedge and off the fissure in one stamp.
    folds = Image.new("L", (w, h), 0)
    stroke = max(3, int(0.0105 * h))
    for spec in FOLD_FAMILIES:
        layer = Image.new("L", (w, h), 0)
        ld = ImageDraw.Draw(layer)
        for curve in fold_family(w, h, spec["pts"], spec["step"],
                                 spec["count"], spec["squeeze"]):
            ld.line(curve, fill=255, width=stroke, joint="curve")
        region = Image.new("L", (w, h), 0)
        ImageDraw.Draw(region).polygon(
            [(x * w, y * h) for x, y in spec["region"]], fill=255)
        folds = ImageChops.lighter(folds, ImageChops.multiply(layer, region))

    keep = Image.new("L", (w, h), 255)
    ImageDraw.Draw(keep).polygon(cere, fill=0)
    ImageDraw.Draw(keep).line(curve_path(w, h, SYLVIAN), fill=0,
                              width=int(0.030 * h), joint="curve")
    inner = mask.copy()
    ImageDraw.Draw(inner).line(poly + [poly[0]], fill=0,
                               width=int(0.026 * h), joint="curve")
    folds = ImageChops.multiply(ImageChops.multiply(folds, keep), inner)
    body.paste(Image.new("RGB", (w, h), BRAIN_FOLD), (0, 0), folds)

    # The cerebellum's own striations: tighter than a fold, and all one way.
    cmask = Image.new("L", (w, h), 0)
    ImageDraw.Draw(cmask).polygon(cere, fill=255)
    strip = body.copy()
    sd = ImageDraw.Draw(strip)
    for i in range(11):
        y = (0.576 + i * 0.0175) * h
        sd.line(curve_bez((0.50 * w, y + 0.015 * h),
                          (0.62 * w, y - 0.004 * h),
                          (0.74 * w, y - 0.004 * h),
                          (0.84 * w, y + 0.012 * h)),
                fill=BRAIN_FOLD, width=max(2, int(0.0046 * h)),
                joint="curve")
    body.paste(strip, (0, 0), cmask)

    card.img.paste(body, (0, 0), mask)
    card.d.line(poly + [poly[0]], fill=BRAIN_EDGE, width=int(0.013 * h),
                joint="curve")
    card.d.line(curve_path(w, h, SYLVIAN), fill=BRAIN_FOLD,
                width=int(0.009 * h), joint="curve")
    # The cerebellum is the same material as everything else: no second
    # colour and no border, only the line where it tucks under the occipital.
    card.d.line(curve_path(w, h, TUCK), fill=BRAIN_EDGE,
                width=int(0.008 * h), joint="curve")
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

    for r, round_spec in enumerate(MEMORY, start=1):
        for i, (colour, form) in enumerate(round_spec["flash"], start=1):
            put(plain(colour, form), "mem%d_f%d" % (r, i))
        for i, (colour, form) in enumerate(round_spec["decoys"], start=1):
            put(plain(colour, form), "mem%d_m%d" % (r, i))

    put(box(), "box_closed")
    for name in ("key", "cup", "star", "moon"):
        put(box(name), "box_open_" + name)

    # Every letter a round draws, its own name on it. The unchanged three
    # slots of a step are the same files their flash held, so a round writes
    # five files rather than eight.
    for round_spec in LETTERS:
        for spec in round_spec["flash"] + [round_spec["after"]]:
            name = letter_name(*spec)
            if name not in written:
                put(letter_card(*spec), name)

    for slot in range(1, UMBRELLA_SLOTS + 1):
        put(umbrella_card(slot == UMBRELLA_ODD), "umb_s%d" % slot)

    for card_id, text, colour in INKS:
        put(word(text, 76, colour), card_id)

    # The dials: the three the flash shows, the one that continues both of
    # their progressions, and the three that continue one. Deduplicated by
    # name, because the last of the three wrong ones IS the first frame and
    # the round works precisely because it is the same picture.
    for rot, dot in DIAL_SEQUENCE + DIAL_ANSWERS:
        name = dial_name(rot, dot)
        if name not in written:
            put(dial_card(rot, dot), name)
    put(word("?", 150, (150, 152, 158)), "nxt_qm")

    for i, spots in enumerate(COUNT_SPOTS, start=1):
        put(circles(spots), "cnt_f%d" % i)
    for text in COUNT_ANSWERS:
        put(word(text, 130), "cnt_" + text)

    for style_id, name, form, colour in TYPES:
        put(share_card(name, form, colour), "share_" + style_id)

    put(brain_intro(), "brain_intro", quality=72)
    put(og_card(), "og", quality=70)

    biggest = max(written,
                  key=lambda n: os.path.getsize(os.path.join(OUT, n + ".webp")))
    print("%d files written to %s" % (len(written), OUT))
    print("largest: %s.webp at %d bytes"
          % (biggest, os.path.getsize(os.path.join(OUT, biggest + ".webp"))))


if __name__ == "__main__":
    main()
