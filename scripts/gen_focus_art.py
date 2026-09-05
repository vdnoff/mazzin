#!/usr/bin/env python3
"""Generate the focus funnel's whole gallery.

Console use only, run by hand. Nothing imports this and no route reaches it.
Its outputs are committed, so a deploy never builds anything and the site
never depends on Pillow being present:

    pip install pillow
    cd ~/mazzin && python3 scripts/gen_focus_art.py

/focus is an attention game, and like /brain its art is the question rather
than the decoration: a board the reader has a few seconds to scan for the one
arrow that is turned, a scatter of dots to count against three others, an
icon to hold in mind and pick out of a grid. So it is drawn, not shot, and
drawn to the rules gen_brain_art.py settled on:

  * Flat. One bold figure on a plain ground, no gradient, no shadow, no
    texture. Anything the eye has to look past is time off the clock.
  * Six colours, named, and nothing else. A round is only fair when the
    difference between two cards is one the reader could say out loud —
    "the red arrow", not "the slightly warmer one".
  * Reproducible. The dot scatters and the odd-arrow boards are randomised
    so a layout cannot be learned, but from ONE fixed seed, in ONE fixed
    order: a rerun writes the same bytes, and a diff on this directory means
    somebody changed a card on purpose. `manifest.json` states what the seed
    produced — which board is the odd one, how many dots each card carries —
    so the funnel config and its check read the answers off a file rather
    than off a picture.

The ground is warmer and a step darker than brain's. Brain's third phone
review found its cards vanishing into the page: an off-white picture on a
white page is a shape floating on nothing, not a card. This one is linen —
far enough off white to read as a surface at arm's length, still neutral
enough that six accents sit on it without arguing.

Everything is drawn at three times size and resized down, which is the whole
of the antialiasing — Pillow's own draw is hard-edged, and a hard edge on a
circle at 600px reads as a jagged circle rather than as a bold one.

Written into static/galleries/focus/ as WebP, quality 80:

    work_*.webp          6   where the reader works
    thief_*.webp         6   what steals their attention
    icon_*_color*.webp  20   ten objects in two inks: the working-memory
                             round's flash boards and answer grids
    foc_<set>_<n>.webp  16   four sets of four 3x3 arrow boards; one board
                             per set has one arrow turned 45 degrees
    swi_<dir>_<ink>     16   one bold arrow, direction x ink fully crossed,
                             for the switching round
    dec_<set>_<n>.webp  16   four sets of four dot scatters; one card per
                             set has the most dots
    focus_intro.webp     1   the dial the intro opens on
    og.webp              1   1200x630, for the link preview
    manifest.json        1   every id and file, plus the answers
"""
import json
import math
import os
import random

from PIL import Image, ImageDraw, ImageFont

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
OUT = os.path.join(ROOT, "static", "galleries", "focus")
MANIFEST = os.path.join(OUT, "manifest.json")

CARD = 600
OG = (1200, 630)
QUALITY = 80
# Everything is drawn at this multiple and resized down. Three rather than
# four: four doubles the memory for a difference nobody can see at 600px.
SS = 3

# The one seed. Every random choice below — which board is odd, where the
# dots fall — comes from one generator started here and consumed in one
# fixed order, so the gallery is a function of this number and nothing else.
SEED = 20260905

# Linen. A warm neutral a step off the page's white, so a card reads as a
# card (brain v3's lesson) without tinting the six inks that sit on it.
GROUND = (236, 230, 218)
INK = (44, 48, 56)
# The one muted tone, for the parts of a picture that are not the point of
# it: a battery's shell, a divider.
SHELL = (150, 152, 158)

# The whole palette. Six, named, the same six brain draws with, because a
# round is only fair when the difference between two cards is one a reader
# could say out loud.
RED = (226, 87, 76)
BLUE = (59, 125, 216)
AMBER = (242, 179, 61)
GREEN = (76, 175, 125)
VIOLET = (142, 111, 216)
TEAL = (47, 168, 160)
PALETTE = {"red": RED, "blue": BLUE, "amber": AMBER,
           "green": GREEN, "violet": VIOLET, "teal": TEAL}

# A fixed font, chosen once and named, because "whatever the system has"
# makes the output depend on the machine that ran it. Same list
# gen_brain_art.py uses, for the same reason and so the two scripts cannot
# disagree. Only the share image sets any type; every card is shapes.
FONTS = [
    ("/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
     "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf"),
    ("/usr/share/fonts/truetype/liberation/LiberationSans-Bold.ttf",
     "/usr/share/fonts/truetype/liberation/LiberationSans-Regular.ttf"),
]


def fonts():
    """`(bold path, regular path)`, or None when the machine has neither."""
    for bold, regular in FONTS:
        if os.path.exists(bold) and os.path.exists(regular):
            return bold, regular
    return None


BOLD, REGULAR = fonts() or (None, None)


# --- geometry ---------------------------------------------------------------

def spin(points, cx, cy, degrees):
    if not degrees:
        return points
    rad = math.radians(degrees)
    cos, sin = math.cos(rad), math.sin(rad)
    return [(cx + (x - cx) * cos - (y - cy) * sin,
             cy + (x - cx) * sin + (y - cy) * cos) for x, y in points]


def arrow_points(cx, cy, r, angle=0.0):
    """One bold arrow as a single polygon, tip to tail `2r` long.

    Drawn pointing up and turned by `angle`: 0 is up, 90 right, 180 down,
    270 left, and 45 is the turned one the focus round hides. One polygon
    rather than a line and a triangle, so the head and the shaft cannot
    disagree by a pixel after rotation.
    """
    hh, hw, sw = r * 0.85, r * 0.72, r * 0.27
    pts = [(cx, cy - r), (cx + hw, cy - r + hh), (cx + sw, cy - r + hh),
           (cx + sw, cy + r), (cx - sw, cy + r), (cx - sw, cy - r + hh),
           (cx - hw, cy - r + hh)]
    return spin(pts, cx, cy, angle)


# --- the canvas -------------------------------------------------------------

class Card(object):
    """One card, drawn oversize and resized down on `save`.

    Every measurement is a fraction of the card's width, so a picture is a
    table of numbers between 0 and 1 and the size of the file is one constant.
    """

    def __init__(self, width=CARD, height=None, ground=GROUND):
        self.w = width
        self.h = height or width
        self.img = Image.new("RGB", (self.w * SS, self.h * SS), ground)
        self.d = ImageDraw.Draw(self.img)

    def px(self, v):
        return v * self.w * SS

    def circle(self, cx, cy, r, colour, outline=None, width=0):
        x, y, radius = self.px(cx), self.px(cy), self.px(r)
        self.d.ellipse([x - radius, y - radius, x + radius, y + radius],
                       fill=colour, outline=outline,
                       width=int(self.px(width)))

    def ellipse(self, box, colour=None, outline=None, width=0):
        self.d.ellipse([self.px(v) for v in box], fill=colour,
                       outline=outline, width=int(self.px(width)))

    def rect(self, box, colour, radius=0.0, outline=None, width=0):
        x0, y0, x1, y1 = [self.px(v) for v in box]
        if radius:
            self.d.rounded_rectangle([x0, y0, x1, y1], self.px(radius),
                                     fill=colour, outline=outline,
                                     width=int(self.px(width)))
        else:
            self.d.rectangle([x0, y0, x1, y1], fill=colour, outline=outline,
                             width=int(self.px(width)))

    def poly(self, points, colour):
        self.d.polygon([(self.px(x), self.px(y)) for x, y in points],
                       fill=colour)

    def line(self, points, colour, width):
        self.d.line([(self.px(x), self.px(y)) for x, y in points],
                    fill=colour, width=int(self.px(width)), joint="curve")

    def arrow(self, cx, cy, r, angle, colour):
        self.d.polygon(arrow_points(self.px(cx), self.px(cy), self.px(r),
                                    angle), fill=colour)

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
        """Resized down to size and written. `quality` is a lever for the two
        pictures nobody has to answer a question about: the intro and the
        share image are the only ones that would otherwise go heavy."""
        out = self.img.resize((self.w, self.h), Image.LANCZOS)
        path = os.path.join(OUT, name + ".webp")
        out.save(path, "WEBP", quality=quality, method=6)
        return path


# --- warm-ups: where they work ---------------------------------------------
#
# Six icons, one colour each, sized to fill the card: on a phone these are
# tiles in a two-wide grid, and an icon that leaves air around itself is an
# icon that reads small.

def work_card(name):
    card = Card()
    if name == "work_office":
        # A desk with a monitor on it. The monitor is the tell; a table on
        # its own is a table.
        card.rect((0.33, 0.20, 0.67, 0.45), BLUE, radius=0.025)
        card.rect((0.365, 0.235, 0.635, 0.415), GROUND, radius=0.012)
        card.rect((0.48, 0.45, 0.52, 0.52), BLUE)
        card.rect((0.40, 0.52, 0.60, 0.555), BLUE, radius=0.015)
        card.rect((0.12, 0.58, 0.88, 0.645), BLUE, radius=0.02)
        card.rect((0.18, 0.645, 0.25, 0.86), BLUE, radius=0.015)
        card.rect((0.75, 0.645, 0.82, 0.86), BLUE, radius=0.015)
    elif name == "work_remote":
        # A house with a laptop cut out of its front wall.
        card.poly([(0.5, 0.13), (0.88, 0.46), (0.12, 0.46)], GREEN)
        card.rect((0.20, 0.44, 0.80, 0.84), GREEN, radius=0.02)
        card.rect((0.375, 0.53, 0.625, 0.68), GROUND, radius=0.015)
        card.rect((0.405, 0.555, 0.595, 0.655), GREEN, radius=0.008)
        card.rect((0.32, 0.69, 0.68, 0.73), GROUND, radius=0.015)
    elif name == "work_hybrid":
        # Half a house and half a desk with a rule down the middle: two
        # pictures the reader already knows from the cards either side.
        card.rect((0.492, 0.16, 0.508, 0.84), SHELL, radius=0.008)
        card.poly([(0.27, 0.27), (0.45, 0.43), (0.09, 0.43)], TEAL)
        card.rect((0.13, 0.42, 0.41, 0.68), TEAL, radius=0.015)
        card.rect((0.225, 0.52, 0.315, 0.68), GROUND, radius=0.01)
        card.rect((0.58, 0.30, 0.90, 0.52), VIOLET, radius=0.02)
        card.rect((0.61, 0.33, 0.87, 0.49), GROUND, radius=0.01)
        card.rect((0.725, 0.52, 0.755, 0.58), VIOLET)
        card.rect((0.66, 0.58, 0.82, 0.61), VIOLET, radius=0.012)
        card.rect((0.55, 0.65, 0.93, 0.68), VIOLET, radius=0.012)
    elif name == "work_feet":
        # A work boot, side on: a tall shaft, a foot, a dark sole.
        card.rect((0.28, 0.14, 0.52, 0.62), AMBER, radius=0.03)
        card.rect((0.28, 0.50, 0.78, 0.76), AMBER, radius=0.07)
        card.rect((0.28, 0.50, 0.52, 0.76), AMBER)
        card.rect((0.25, 0.72, 0.80, 0.82), INK, radius=0.03)
        for y in (0.24, 0.34, 0.44):
            card.circle(0.40, y, 0.025, GROUND)
    elif name == "work_student":
        # A backpack: a handle over a body with a pocket on the front.
        card.ellipse((0.36, 0.13, 0.64, 0.38), outline=RED, width=0.04)
        card.rect((0.22, 0.26, 0.78, 0.86), RED, radius=0.10)
        card.rect((0.30, 0.42, 0.70, 0.455), GROUND, radius=0.012)
        card.rect((0.33, 0.55, 0.67, 0.77), GROUND, radius=0.04)
        card.rect((0.36, 0.58, 0.64, 0.74), RED, radius=0.03)
    else:
        # Shuffle: two tracks that cross, one passing over the other.
        for y0, y1 in ((0.32, 0.68), (0.68, 0.32)):
            if y0 > y1:
                card.line([(0.34, y0), (0.62, y1)], GROUND, 0.13)
            card.line([(0.10, y0), (0.34, y0), (0.62, y1), (0.80, y1)],
                      TEAL, 0.06)
            card.poly([(0.78, y1 - 0.11), (0.92, y1), (0.78, y1 + 0.11)],
                      TEAL)
    return card


# --- warm-ups: what steals the attention -----------------------------------

def arrow_line(card, p0, p1, colour, width, head=0.10, gap=False):
    """A straight arrow from `p0` to `p1`, headed at `p1`.

    `gap` first paints the same line wider in the ground, so a later arrow
    crossing an earlier one passes over it rather than merging with it.
    """
    (x0, y0), (x1, y1) = p0, p1
    angle = math.degrees(math.atan2(y1 - y0, x1 - x0))
    tip = [(x1, y1), (x1 - head, y1 - head * 0.62), (x1 - head, y1 + head * 0.62)]
    tip = spin(tip, x1, y1, angle)
    if gap:
        card.line([p0, p1], GROUND, width * 2.2)
    card.line([p0, (x1 - head * 0.5 * math.cos(math.radians(angle)),
                    y1 - head * 0.5 * math.sin(math.radians(angle)))],
              colour, width)
    card.poly(tip, colour)


def thief_card(name):
    card = Card()
    if name == "thief_phone":
        card.rect((0.31, 0.10, 0.69, 0.90), RED, radius=0.07)
        card.rect((0.35, 0.19, 0.65, 0.77), GROUND, radius=0.02)
        card.circle(0.5, 0.835, 0.025, GROUND)
        card.rect((0.44, 0.135, 0.56, 0.155), GROUND, radius=0.01)
    elif name == "thief_meetings":
        # Two speech bubbles, the second laid over the first.
        card.rect((0.10, 0.16, 0.62, 0.50), BLUE, radius=0.09)
        card.poly([(0.20, 0.48), (0.20, 0.62), (0.34, 0.48)], BLUE)
        card.rect((0.35, 0.41, 0.93, 0.79), GROUND, radius=0.11)
        card.poly([(0.83, 0.77), (0.83, 0.92), (0.66, 0.77)], GROUND)
        card.rect((0.38, 0.44, 0.90, 0.76), VIOLET, radius=0.09)
        card.poly([(0.80, 0.74), (0.80, 0.88), (0.66, 0.74)], VIOLET)
    elif name == "thief_notifications":
        # A bell with a red badge on its shoulder.
        card.circle(0.5, 0.19, 0.035, AMBER)
        card.ellipse((0.27, 0.19, 0.73, 0.65), AMBER)
        card.rect((0.27, 0.42, 0.73, 0.66), AMBER)
        card.rect((0.18, 0.63, 0.82, 0.71), AMBER, radius=0.025)
        card.circle(0.5, 0.775, 0.055, AMBER)
        card.circle(0.745, 0.245, 0.125, GROUND)
        card.circle(0.745, 0.245, 0.10, RED)
    elif name == "thief_multitasking":
        # Three arrows going three ways through each other.
        arrow_line(card, (0.16, 0.30), (0.86, 0.60), VIOLET, 0.055)
        arrow_line(card, (0.18, 0.80), (0.82, 0.18), VIOLET, 0.055, gap=True)
        arrow_line(card, (0.56, 0.90), (0.40, 0.10), VIOLET, 0.055, gap=True)
    elif name == "thief_fatigue":
        # A battery with almost nothing in it. Brain's tired card, drawn
        # heavier: here it is a tile rather than a caption's illustration.
        card.rect((0.12, 0.33, 0.80, 0.67), SHELL, radius=0.04)
        card.rect((0.155, 0.365, 0.765, 0.635), GROUND, radius=0.025)
        card.rect((0.80, 0.43, 0.88, 0.57), SHELL, radius=0.02)
        card.rect((0.19, 0.40, 0.31, 0.60), RED, radius=0.015)
    else:
        # A clock asleep: the face, two hands, and a pair of Zs off its
        # shoulder, drawn as zigzags so no font is in the picture.
        card.circle(0.46, 0.56, 0.31, None, outline=TEAL, width=0.05)
        card.line([(0.46, 0.56), (0.46, 0.35)], TEAL, 0.045)
        card.line([(0.46, 0.56), (0.60, 0.66)], TEAL, 0.045)
        card.circle(0.46, 0.56, 0.035, TEAL)
        card.line([(0.68, 0.12), (0.84, 0.12), (0.68, 0.28), (0.84, 0.28)],
                  TEAL, 0.035)
        card.line([(0.86, 0.04), (0.95, 0.04), (0.86, 0.13), (0.95, 0.13)],
                  TEAL, 0.022)
    return card


# --- round MEM: ten objects in two inks -------------------------------------
#
# What the memory round flashes and what its answer grid is built from.
# Named by what they are, so one file serves both boards. Two inks, because
# "I saw a clock" is not enough when the grid holds a blue one and a red one.

ICONS = ("clock", "mug", "folder", "pencil", "phone",
         "calendar", "key", "bulb", "flag", "chart")
ICON_INKS = {"colorA": "blue", "colorB": "red"}


def icon_card(name, colour):
    card = Card()
    if name == "clock":
        card.circle(0.5, 0.5, 0.32, None, outline=colour, width=0.055)
        card.line([(0.5, 0.5), (0.5, 0.29)], colour, 0.05)
        card.line([(0.5, 0.5), (0.67, 0.5)], colour, 0.05)
        card.circle(0.5, 0.5, 0.04, colour)
    elif name == "mug":
        # A mug: straight sides, a heavy handle off the right.
        card.ellipse((0.52, 0.36, 0.82, 0.66), outline=colour, width=0.055)
        card.rect((0.20, 0.26, 0.62, 0.76), colour, radius=0.04)
    elif name == "folder":
        card.rect((0.14, 0.22, 0.44, 0.36), colour, radius=0.03)
        card.rect((0.14, 0.30, 0.86, 0.78), colour, radius=0.03)
        card.rect((0.14, 0.40, 0.86, 0.42), GROUND)
    elif name == "pencil":
        # A pencil on the diagonal, the point at the bottom left.
        cx, cy, w = 0.5, 0.5, 0.085
        body = [(cx - w, cy - 0.36), (cx + w, cy - 0.36),
                (cx + w, cy + 0.20), (cx - w, cy + 0.20)]
        tip = [(cx - w, cy + 0.20), (cx + w, cy + 0.20), (cx, cy + 0.36)]
        card.poly(spin(body, cx, cy, 45), colour)
        card.poly(spin(tip, cx, cy, 45), colour)
        for y in (-0.27, 0.20):
            card.line(spin([(cx - w, cy + y), (cx + w, cy + y)], cx, cy, 45),
                      GROUND, 0.018)
    elif name == "phone":
        card.rect((0.31, 0.10, 0.69, 0.90), colour, radius=0.07)
        card.rect((0.35, 0.19, 0.65, 0.77), GROUND, radius=0.02)
        card.circle(0.5, 0.835, 0.025, GROUND)
    elif name == "calendar":
        card.rect((0.16, 0.22, 0.84, 0.82), colour, radius=0.04)
        card.rect((0.16, 0.395, 0.84, 0.42), GROUND)
        for x in (0.32, 0.68):
            card.rect((x - 0.03, 0.13, x + 0.03, 0.31), colour, radius=0.02)
        for row in range(2):
            for col in range(3):
                x = 0.31 + col * 0.19
                y = 0.52 + row * 0.16
                card.rect((x - 0.045, y - 0.045, x + 0.045, y + 0.045),
                          GROUND, radius=0.012)
    elif name == "key":
        # A round bow with a hole through it, a shaft, two teeth.
        card.circle(0.29, 0.5, 0.15, colour)
        card.rect((0.29, 0.445, 0.84, 0.555), colour, radius=0.02)
        for at in (0.62, 0.74):
            card.rect((at, 0.555, at + 0.07, 0.71), colour, radius=0.015)
        card.circle(0.29, 0.5, 0.065, GROUND)
    elif name == "bulb":
        card.circle(0.5, 0.40, 0.25, colour)
        card.rect((0.39, 0.56, 0.61, 0.74), colour, radius=0.02)
        card.rect((0.43, 0.74, 0.57, 0.81), colour, radius=0.02)
        for y in (0.63, 0.69):
            card.rect((0.39, y - 0.01, 0.61, y + 0.01), GROUND)
    elif name == "flag":
        card.rect((0.24, 0.12, 0.31, 0.88), colour, radius=0.02)
        card.poly([(0.31, 0.16), (0.80, 0.16), (0.68, 0.32),
                   (0.80, 0.48), (0.31, 0.48)], colour)
    else:
        for i, top in enumerate((0.56, 0.38, 0.18)):
            x = 0.18 + i * 0.24
            card.rect((x, top, x + 0.16, 0.80), colour, radius=0.02)
        card.rect((0.14, 0.80, 0.86, 0.85), colour, radius=0.015)
    return card


# --- round FOC: find the turned arrow ---------------------------------------
#
# Four sets of four boards. Every board is nine small arrows all pointing the
# set's way, and one board per set has one of its nine turned 45 degrees.
# Which board, and which of its nine, comes from the seed; the set's own
# direction and ink are fixed so the four sets are four pictures rather than
# one picture four times.

FOC_SETS = {"a": ("up", "blue"), "b": ("right", "green"),
            "c": ("down", "violet"), "d": ("left", "teal")}
DIRECTIONS = {"up": 0, "right": 90, "down": 180, "left": 270}
FOC_GRID = (0.24, 0.50, 0.76)
FOC_R = 0.085
# Every arrow on every board is nudged by up to this much. It is invisible
# — a pixel and a half at card size — and it is on every board alike, so
# it is not a tell; what it does is make the four files of a set four
# different files, so the odd board cannot be picked out by its byte size.
FOC_JITTER = 0.0025


def foc_card(direction, colour, odd_cell, jitter):
    card = Card()
    angle = DIRECTIONS[direction]
    for i in range(9):
        cx = FOC_GRID[i % 3] + jitter[i][0]
        cy = FOC_GRID[i // 3] + jitter[i][1]
        turn = 45 if i == odd_cell else 0
        card.arrow(cx, cy, FOC_R, angle + turn, PALETTE[colour])
    return card


# --- round SWI: one arrow, direction by ink ---------------------------------

SWI_INKS = ("red", "blue", "green", "amber")


def swi_card(direction, colour):
    card = Card()
    card.arrow(0.5, 0.5, 0.36, DIRECTIONS[direction], PALETTE[colour])
    return card


# --- round DEC: which card has the most dots --------------------------------
#
# Four sets of four scatters. The counts per set are four different values
# between 7 and 13, so exactly one card has the most, and the scatter is
# drawn so no two dots touch: a dot half-hidden by another is a dot the
# reader can argue about.

DEC_SETS = {"a": "amber", "b": "red", "c": "teal", "d": "violet"}
DEC_COUNTS = range(7, 14)
DOT_R = 0.062
DOT_GAP = 2.5


def scatter(rng, n, r=DOT_R, lo=0.13, hi=0.87, gap=DOT_GAP):
    """`n` centres, no two closer than `gap` radii, inside the safe area."""
    pts = []
    tries = 0
    while len(pts) < n:
        x, y = rng.uniform(lo, hi), rng.uniform(lo, hi)
        if all((x - px) ** 2 + (y - py) ** 2 >= (gap * r) ** 2
               for px, py in pts):
            pts.append((round(x, 4), round(y, 4)))
        tries += 1
        if tries > 50000:
            raise RuntimeError("could not place %d dots" % n)
    return pts


def dec_card(spots, colour):
    card = Card()
    for x, y in spots:
        card.circle(x, y, DOT_R, PALETTE[colour])
    return card


# --- the plan: everything the seed decides, decided once --------------------

def make_plan(rng):
    """Every random choice in the gallery, drawn in one fixed order.

    Kept apart from the drawing so the manifest and the pictures come from
    one table rather than from two walks over the generator.
    """
    plan = {"foc": {}, "dec": {}}
    # One odd index per set, all four different, so a reader who has seen
    # one set has learned nothing about the next.
    odd_indexes = rng.sample([1, 2, 3, 4], 4)
    for (set_id, (direction, colour)), odd in zip(sorted(FOC_SETS.items()),
                                                  odd_indexes):
        plan["foc"][set_id] = {
            "direction": direction, "colour": colour,
            "odd": odd, "odd_cell": rng.randrange(9),
            "jitter": {n: [(round(rng.uniform(-FOC_JITTER, FOC_JITTER), 4),
                            round(rng.uniform(-FOC_JITTER, FOC_JITTER), 4))
                           for _ in range(9)] for n in range(1, 5)},
        }
    for set_id, colour in sorted(DEC_SETS.items()):
        counts = rng.sample(list(DEC_COUNTS), 4)
        plan["dec"][set_id] = {
            "colour": colour,
            "counts": {n: c for n, c in zip(range(1, 5), counts)},
            "most": counts.index(max(counts)) + 1,
            "spots": {n: scatter(rng, c) for n, c in zip(range(1, 5), counts)},
        }
    return plan


# --- extras: the intro dial and the share image -----------------------------

def dial(card, cx, cy, r, needle=-48.0):
    """A target with a needle on it: rings, a bullseye, one hand."""
    card.circle(cx, cy, r, BLUE)
    card.circle(cx, cy, r * 0.80, GROUND)
    card.circle(cx, cy, r * 0.60, BLUE)
    card.circle(cx, cy, r * 0.40, GROUND)
    card.circle(cx, cy, r * 0.20, RED)
    for i in range(12):
        a = math.radians(i * 30.0)
        card.line([(cx + math.cos(a) * r * 1.08, cy + math.sin(a) * r * 1.08),
                   (cx + math.cos(a) * r * 1.16, cy + math.sin(a) * r * 1.16)],
                  INK, r * 0.04)
    tip = (cx + math.cos(math.radians(needle)) * r * 1.02,
           cy + math.sin(math.radians(needle)) * r * 1.02)
    base = [(cx, cy - r * 0.07), (cx, cy + r * 0.07)]
    card.poly(spin([tip] + base, cx, cy, 0), INK)
    card.circle(cx, cy, r * 0.11, INK)


def intro_card():
    card = Card()
    dial(card, 0.5, 0.5, 0.36)
    return card


def og_card():
    card = Card(OG[0], OG[1])
    # Fractions here are of the WIDTH, so the dial is placed by its own
    # radius rather than by a height nobody else on the card uses.
    dial(card, 0.20, 0.2625, 0.16)
    card.text("FOCUS", 118, cx=0.64, cy=0.40)
    card.text("SCORE", 118, cx=0.64, cy=0.62)
    return card


# --- main -------------------------------------------------------------------

def main():
    if not BOLD:
        raise SystemExit("no usable font on this machine — see FONTS above")
    if not os.path.isdir(OUT):
        os.makedirs(OUT)
    plan = make_plan(random.Random(SEED))
    cards = []

    def put(card, name, group, quality=QUALITY, **meta):
        card.save(name, quality)
        entry = {"id": name, "file": name + ".webp", "group": group}
        entry.update(meta)
        cards.append(entry)

    for name in ("work_office", "work_remote", "work_hybrid",
                 "work_feet", "work_student", "work_mixed"):
        put(work_card(name), name, "warmup_work")
    for name in ("thief_phone", "thief_meetings", "thief_notifications",
                 "thief_multitasking", "thief_fatigue",
                 "thief_procrastination"):
        put(thief_card(name), name, "warmup_thief")

    for icon in ICONS:
        for variant, ink in sorted(ICON_INKS.items()):
            put(icon_card(icon, PALETTE[ink]), "icon_%s_%s" % (icon, variant),
                "mem_icon", icon=icon, ink=ink)

    for set_id, spec in sorted(plan["foc"].items()):
        for n in range(1, 5):
            odd = n == spec["odd"]
            put(foc_card(spec["direction"], spec["colour"],
                         spec["odd_cell"] if odd else None,
                         spec["jitter"][n]),
                "foc_%s_%d" % (set_id, n), "foc_board",
                set=set_id, variant=n, odd=odd,
                direction=spec["direction"], ink=spec["colour"])

    for direction in ("up", "down", "left", "right"):
        for ink in SWI_INKS:
            put(swi_card(direction, ink), "swi_%s_%s" % (direction, ink),
                "swi_arrow", direction=direction, ink=ink)

    for set_id, spec in sorted(plan["dec"].items()):
        for n in range(1, 5):
            put(dec_card(spec["spots"][n], spec["colour"]),
                "dec_%s_%d" % (set_id, n), "dec_dots",
                set=set_id, variant=n, count=spec["counts"][n],
                most=(n == spec["most"]), ink=spec["colour"])

    put(intro_card(), "focus_intro", "extra", quality=74)
    put(og_card(), "og", "extra", quality=70)

    manifest = {
        "funnel": "focus",
        "generator": "scripts/gen_focus_art.py",
        "seed": SEED,
        "card": CARD,
        "og": list(OG),
        "ground": list(GROUND),
        "palette": {k: list(v) for k, v in sorted(PALETTE.items())},
        "icon_inks": ICON_INKS,
        "foc": {s: {"direction": p["direction"], "ink": p["colour"],
                    "odd": p["odd"], "odd_cell": p["odd_cell"]}
                for s, p in sorted(plan["foc"].items())},
        "dec": {s: {"ink": p["colour"], "most": p["most"],
                    "counts": {str(n): c for n, c in sorted(p["counts"].items())}}
                for s, p in sorted(plan["dec"].items())},
        "cards": cards,
    }
    with open(MANIFEST, "w") as fh:
        json.dump(manifest, fh, indent=2, sort_keys=True)
        fh.write("\n")

    for entry in cards:
        path = os.path.join(OUT, entry["file"])
        if not os.path.isfile(path) or os.path.getsize(path) == 0:
            raise SystemExit("missing or empty: " + path)
    biggest = max(cards,
                  key=lambda e: os.path.getsize(os.path.join(OUT, e["file"])))
    print("%d files written to %s" % (len(cards), OUT))
    print("largest: %s at %d bytes"
          % (biggest["file"],
             os.path.getsize(os.path.join(OUT, biggest["file"]))))
    for s, p in sorted(plan["foc"].items()):
        print("foc %s: odd board %d (cell %d)" % (s, p["odd"], p["odd_cell"]))
    for s, p in sorted(plan["dec"].items()):
        print("dec %s: counts %s, most %d"
              % (s, [p["counts"][n] for n in range(1, 5)], p["most"]))


if __name__ == "__main__":
    main()
