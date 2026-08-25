#!/usr/bin/env python3
"""The rich profile block, written into both zodiac configs from one source.

The result page stopped saying "Leo × Air" and started saying "The Wildlight".
That name, the line under it, the six question cards and the rarity ribbon are
all content, so they belong in the funnel JSON where the rest of this funnel's
content lives — but they are the same content on both funnels, and two copies
of a 24-name table maintained by hand is two tables that disagree by Christmas.

So the tables live here, once, and this script writes them into
`funnels/zodiac.json` and `funnels/zodiac30.json` under `result_copy.profile`.
Everything except the rarity numbers is byte-identical between the two;
the rarity is measured per funnel, because a longer walk has a different
distribution and a number that claimed otherwise would be a lie printed in
gold.

    cd ~/mazzin && python3 scripts/gen_profile_rarity.py
    python3 scripts/gen_profile_rarity.py --check     # exit 1 if stale
    python3 scripts/gen_profile_rarity.py --runs 200000

Reads nothing but the two configs and engine.js. No database, no network, no
model. tests/test_zodiacprofile.py re-derives a sample of the rarity and holds
the committed numbers to it, so a retag that moves the distribution fails a
suite instead of shipping a stale ribbon.

--- how the rarity is measured -------------------------------------------

Honestly, and by simulation rather than by assertion. The same seeded random
walk tests/test_zodiac_check.py uses to check the archetype balance is run
here: engine.js's own scoring, the adaptive pair draw included, with every tap
chosen uniformly. Each finished run is bucketed by the three things the
subtype is made of — archetype, second element, energy lean — and the bucket's
share of all runs is inverted into "1 in N".

A random walk is not a customer. It is, though, the only measure available
before there are enough customers to measure, it is the same measure the
funnel's own balance check is held to, and it is reproducible from the config
by anybody who doubts the number. N is floored at 6 (below that "rare" is not
a word anyone should print) and capped at 40 (above it the claim stops being
checkable and starts being theatre), and snapped to a short ladder of round
numbers so the ribbon reads like a sentence rather than a measurement.
"""
import argparse
import collections
import json
import os
import random
import re
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

FUNNELS = ("zodiac", "zodiac30")

ELEMENTS = ("fire", "earth", "air", "water")
ENERGIES = ("sun", "moon")

ELEMENT_NAME = {"fire": "Fire", "earth": "Earth", "air": "Air",
                "water": "Water"}
ENERGY_NAME = {"sun": "Sun", "moon": "Moon"}

# --- the subtype table ------------------------------------------------------
#
# archetype x second element x energy. The second element is never the
# archetype's own — a Fire-led reader's runner-up is one of the other three —
# so it is 4 x 3 x 2 and every one of the twenty-four is reachable.
#
# The register is fixed: "The" and one or two words, evocative rather than
# descriptive, nothing a horoscope column would print. They are read aloud in
# the reader's head as the name of a thing they are, so no name here explains
# itself.

SUBTYPES = {
    "radiant_fire": {
        "earth": {"sun": "The Bright Forge", "moon": "The Banked Ember"},
        "air": {"sun": "The Wildlight", "moon": "The Night Flare"},
        "water": {"sun": "The Warm Current", "moon": "The Slow Burn"},
    },
    "deep_water": {
        "fire": {"sun": "The Sunlit Depth", "moon": "The Underglow"},
        "earth": {"sun": "The Stone Pool", "moon": "The Still Well"},
        "air": {"sun": "The Clear Tide", "moon": "The Drifting Deep"},
    },
    "grounded_earth": {
        "fire": {"sun": "The Sunstone Ridge", "moon": "The Low Hearth"},
        "air": {"sun": "The Open Field", "moon": "The Quiet Orchard"},
        "water": {"sun": "The River Stone", "moon": "The Deep Root"},
    },
    "celestial_air": {
        "fire": {"sun": "The Solar Spark", "moon": "The Lantern Wind"},
        "earth": {"sun": "The High Meadow", "moon": "The Standing Mist"},
        "water": {"sun": "The Sea Breath", "moon": "The Rain Weaver"},
    },
}

# --- the sign-cross line ----------------------------------------------------
#
# Twelve signs against the four elements a run can lead with: forty-eight
# lines, one of which the reader ever sees. Each one names the classical
# nature of their sign and then says what the measured lead does to it — the
# whole point of the line is that a Leo who came out Air-led is told why that
# is interesting rather than left to wonder whether the quiz misfired.
#
# Nothing here predicts anything, and nothing here is a compliment. A line
# that would read the same for two different signs has failed.

SIGN_CROSS = {
    "Aries": {
        "fire": "An Aries that leads with Fire runs true — the start is the "
                "whole of it, and you are already moving while the room is "
                "still deciding.",
        "earth": "An Aries that leads with Earth is a genuine cross — the "
                 "impulse arrives on time, but you build the thing before you "
                 "announce it.",
        "air": "An Aries that leads with Air is uncommon — your speed goes "
               "into the argument rather than the action, and you win rooms "
               "you never meant to enter.",
        "water": "An Aries that leads with Water is rare — the charge is all "
                 "still there, and it moves through what you feel rather than "
                 "what you start.",
    },
    "Taurus": {
        "fire": "A Taurus that leads with Fire is uncommon — the patience is "
                "real and it sits on top of a heat that only shows when "
                "something is being taken from you.",
        "earth": "A Taurus that leads with Earth runs true — you hold ground "
                 "by standing on it, and what you keep is the measure of you.",
        "air": "A Taurus that leads with Air is a genuine cross — you settle "
               "slowly and think fast, so the decision is made long before you "
               "admit to it.",
        "water": "A Taurus that leads with Water is uncommon — the steadiness "
                 "is emotional rather than material, and comfort for you means "
                 "being felt, not being furnished.",
    },
    "Gemini": {
        "fire": "A Gemini that leads with Fire is uncommon — the two minds "
                "stop arguing the moment something is worth doing, and then "
                "you are all one direction.",
        "earth": "A Gemini that leads with Earth is a genuine cross — you talk "
                 "in possibilities and commit in specifics, and the specifics "
                 "are what people remember.",
        "air": "A Gemini that leads with Air runs true — you think out loud, "
               "in company, and the thought is finished only once somebody has "
               "answered it.",
        "water": "A Gemini that leads with Water is rare — the quickness reads "
                 "a room's mood before its words, and that is the half of you "
                 "people call uncanny.",
    },
    "Cancer": {
        "fire": "A Cancer that leads with Fire is uncommon — the shell is "
                "still there and there is something behind it that comes out "
                "first rather than last.",
        "earth": "A Cancer that leads with Earth is a genuine cross — you look "
                 "after people with logistics rather than sentiment, and it "
                 "lands harder.",
        "air": "A Cancer that leads with Air is rare — you feel it all and "
               "file it, and the distance you keep is a working distance "
               "rather than a cold one.",
        "water": "A Cancer that leads with Water runs true — you take the "
                 "temperature of a room before you take your coat off, and you "
                 "are almost never wrong about it.",
    },
    "Leo": {
        "fire": "A Leo that leads with Fire runs true — you warm a room by "
                "being in it, and the performance and the person are the same "
                "thing.",
        "earth": "A Leo that leads with Earth is a genuine cross — the shine "
                 "is real and it is built, and you would rather be relied on "
                 "than looked at.",
        "air": "A Leo that leads with Air is uncommon — your fire shows in how "
               "you decide, not how you burn.",
        "water": "A Leo that leads with Water is rare — the warmth turns "
                 "inward first, and what the room sees is the second draft of "
                 "it.",
    },
    "Virgo": {
        "fire": "A Virgo that leads with Fire is uncommon — the standard comes "
                "with heat behind it, and you will burn a week to get one "
                "detail right.",
        "earth": "A Virgo that leads with Earth runs true — you improve what "
                 "is in front of you, and the improvement is specific enough "
                 "to point at.",
        "air": "A Virgo that leads with Air is a genuine cross — the precision "
               "goes into language, and you can take a muddled idea apart in "
               "one sentence.",
        "water": "A Virgo that leads with Water is uncommon — you notice what "
                 "is wrong with a person the way other people notice weather, "
                 "and you say almost none of it.",
    },
    "Libra": {
        "fire": "A Libra that leads with Fire is uncommon — the balance is a "
                "decision you keep making, and you make it fast and out loud.",
        "earth": "A Libra that leads with Earth is a genuine cross — you weigh "
                 "things by what they cost to keep, and your taste is a "
                 "working budget.",
        "air": "A Libra that leads with Air runs true — you hold both sides "
               "long enough to see the shape of the whole, and only then take "
               "one.",
        "water": "A Libra that leads with Water is rare — fairness for you is "
                 "a felt thing, and you will carry an imbalance for months "
                 "rather than name it.",
    },
    "Scorpio": {
        "fire": "A Scorpio that leads with Fire is uncommon — the depth is "
                "loud rather than quiet, and people know exactly where they "
                "stand with you.",
        "earth": "A Scorpio that leads with Earth is a genuine cross — the "
                 "intensity goes into what you build, and you are patient in a "
                 "way that unsettles people.",
        "air": "A Scorpio that leads with Air is rare — you take a thing apart "
               "to understand it, and the understanding is where the intensity "
               "lands.",
        "water": "A Scorpio that leads with Water runs true — you go to the "
                 "bottom of a thing on the first pass, and shallow company "
                 "tires you within the hour.",
    },
    "Sagittarius": {
        "fire": "A Sagittarius that leads with Fire runs true — the arrow "
                "leaves the bow, and the aiming happens on the way.",
        "earth": "A Sagittarius that leads with Earth is a genuine cross — the "
                 "horizon is still the point and you now carry provisions, "
                 "which is why you actually arrive.",
        "air": "A Sagittarius that leads with Air is uncommon — you travel "
               "through ideas as readily as places, and the argument is the "
               "journey.",
        "water": "A Sagittarius that leads with Water is rare — the search is "
                 "inward as often as outward, and you go furthest when nobody "
                 "is watching.",
    },
    "Capricorn": {
        "fire": "A Capricorn that leads with Fire is uncommon — the climb is "
                "driven rather than dutiful, and you are competing with a "
                "version of yourself.",
        "earth": "A Capricorn that leads with Earth runs true — you build in "
                 "stone, on purpose, and you would rather be early than "
                 "impressive.",
        "air": "A Capricorn that leads with Air is a genuine cross — the "
               "structure is in the thinking first, and you can see the whole "
               "ladder before you touch it.",
        "water": "A Capricorn that leads with Water is rare — the discipline "
                 "is protecting something soft, and the people who get past it "
                 "stay for good.",
    },
    "Aquarius": {
        "fire": "An Aquarius that leads with Fire is uncommon — the distance "
                "you keep is a position, and you will defend it warmly and at "
                "length.",
        "earth": "An Aquarius that leads with Earth is a genuine cross — the "
                 "odd idea comes with a plan attached, which is what makes "
                 "people follow it.",
        "air": "An Aquarius that leads with Air runs true — you think from "
               "outside the room on purpose, and the view from there is the "
               "contribution.",
        "water": "An Aquarius that leads with Water is rare — the detachment "
                 "is a way of caring at scale, and the individual case still "
                 "gets to you.",
    },
    "Pisces": {
        "fire": "A Pisces that leads with Fire is uncommon — the dreaming has "
                "an engine under it, and what you begin tends to get finished.",
        "earth": "A Pisces that leads with Earth is a genuine cross — you make "
                 "the imagined thing real, which is the rarest half of "
                 "imagination.",
        "air": "A Pisces that leads with Air is rare — the feeling arrives "
               "already translated, and you can explain a mood to the person "
               "having it.",
        "water": "A Pisces that leads with Water runs true — you take on the "
                 "room's weather without meaning to, and solitude is "
                 "maintenance rather than sulking.",
    },
    # Somebody who tapped "Born on a cusp" told us their season and nothing
    # finer. The line still has to say something true, so it says the one
    # thing a cusp guarantees — two energies, one of them in front — and never
    # names a sign. No config currently ships a cusp card; the lines are here
    # so that reinstating one does not print an empty hairline.
    "cusp": {
        "fire": "Born on a cusp and leading with Fire — you carry two seasons' "
                "energies and one of them moves first, every time.",
        "earth": "Born on a cusp and leading with Earth — two energies sit in "
                 "you, and the steadier one is the one people meet.",
        "air": "Born on a cusp and leading with Air — you hold two natures at "
               "once, which is why you can argue both sides and mean both.",
        "water": "Born on a cusp and leading with Water — the two energies you "
                 "sit between meet in what you feel rather than in what you "
                 "do.",
    },
}

# --- the six question cards -------------------------------------------------
#
# What replaced the constellation's locked nodes. A locked node said "Love &
# Compatibility" and left the reader to guess what that was worth; a card
# names the question the chapter answers, keyword first, and the keyword is
# what the delivered page puts back over the same section so the thing they
# bought is recognisably the thing they were sold.
#
# `key` is that keyword. `promise` is everything after the colon. Tokens in
# braces are filled by the result module: {element} and {second} from the
# run's own tallies, {moonphase} through engine.js's hook machinery, which
# already declares "moon" as its fallback.

CARDS = [
    {
        "id": "materials",
        "key": "Love",
        "icon": "heart",
        "promise": "which two signs are magnetic for you — and the one that "
                   "drains your relationships",
        # The reader who said love is why they came gets the same chapter
        # named as the thing they asked for.
        "upgrade": {
            "purpose_love": "the reading you came for — your two magnetic "
                            "signs, and the one that drains you",
        },
    },
    {
        "id": "mistakes",
        "key": "Blind spots",
        "icon": "eye",
        "promise": "what your {moonphase} pick revealed — strengths #2–5, "
                   "the costliest last",
    },
    {
        "id": "shopping",
        "key": "Your year",
        "icon": "calendar",
        # {first} and {last} are the ends of the reader's own twelve months,
        # counted from the one they are in. The map used to run January to
        # December, which handed a September buyer eight months already gone.
        "promise": "{first} → {last} — the 3 strongest months, and the 1 to "
                   "lay low in",
    },
    {
        "id": "splurge",
        "key": "Money",
        "icon": "coin",
        "promise": "where your energy earns — and where it quietly leaks",
    },
    {
        "id": "palette",
        "key": "Power colors",
        "icon": "palette",
        "promise": "your 4, with exact codes + talismans",
    },
    {
        "id": "dna",
        "key": "Blueprint",
        "icon": "map",
        "promise": "how {element} leads you and {second} fuels it",
    },
]

# The three spectrum scales the hero draws, left pole to right pole. The ids
# are what the module computes positions under and what the PDF reads back.
SCALES = [
    {"id": "energy", "left": "Sun", "right": "Moon"},
    {"id": "tone", "left": "Bold", "right": "Calm"},
    {"id": "depth", "left": "Mystic", "right": "Grounded"},
]

# The lines the hero and the offer are built out of. Two tokens for the
# subtype rather than one, and the reason is grammar: the names all begin with
# "The", so "specifically for a {subtype}" would read "for a The Solar Spark".
# {first} and {last} are the two ends of the reader's own year, filled by the
# result module from the same twelve reports.py builds server-side.
# {subtype} is the name as it is printed in the hero; {subtype_bare} is the
# same name with the article off, for the sentences that supply their own —
# and {subtype_article} is that article, because half these names begin with a
# vowel and "a Underglow" is the kind of thing a reader stops reading at.
LINES = {
    "formula": "{sign} · {element}-led, {second} undercurrent · {energy}",
    "rarity_line": "About 1 in {n} readings land this blend",
    "bridge": "Your reading answers, specifically for {subtype_article} "
              "{subtype_bare}:",
    "offer_head": "The full {subtype_bare} reading — 6 chapters",
    "split_caption": "{fire}% Fire · {earth}% Earth · {air}% Air · "
                     "{water}% Water",
}


# --- the walk ---------------------------------------------------------------
#
# engine.js's scoring, read out of engine.js rather than restated here: the
# axis lists drive the adaptive pair draw, and a copy of them in this file is
# a copy that goes stale the first time a step is retagged.

def axes(engine):
    found = re.findall(r"var (\w+)_AXIS = \[([^\]]*)\]", engine)
    return {name.lower(): [t.strip().strip('"') for t in body.split(",")]
            for name, body in found}


def load_engine():
    with open(os.path.join(ROOT, "static/js/engine.js")) as handle:
        return handle.read()


def load_funnel(slug):
    with open(os.path.join(ROOT, "funnels/%s.json" % slug)) as handle:
        return json.load(handle)


def _variant(step, scores, axis_map):
    """The pair engine.js would draw for this step, or None for a free draw."""
    rule = step.get("adaptive")
    if not rule:
        return None
    leader, best = None, 0
    for tag in axis_map.get(rule["axis"], ()):
        if scores.get(tag, 0) > best:
            best, leader = scores.get(tag, 0), tag
    wanted = ((leader and (rule.get("variants") or {}).get(leader))
              or (rule.get("variants") or {}).get("default"))
    return next((p for p in step.get("pairs") or [] if p.get("id") == wanted),
                None)


def play(cfg, axis_map, pick):
    """One run's tag scores: -0.5 a tag on the inverse step, 1 everywhere."""
    scores = {}
    for step in cfg["swipe"]["steps"]:
        pair = _variant(step, scores, axis_map)
        options = (list(pair["images"]) if pair
                   else [i for p in step.get("pairs") or []
                         for i in p.get("images") or []])
        if not options:
            continue
        weight = -0.5 if step.get("scoring") == "inverse" else 1
        for tag in pick(options).get("tags") or []:
            scores[tag] = scores.get(tag, 0) + weight
    return scores


def winner(cfg, scores):
    """computeWinner: the style whose own tags total highest."""
    best, best_score = None, float("-inf")
    for style in cfg["styles"]:
        total = sum(scores.get(tag, 0) for tag in style["tags"])
        if total > best_score:
            best, best_score = style["id"], total
    return best


def _style_by_id(cfg, style_id):
    return next((s for s in cfg["styles"] if s["id"] == style_id), None)


def bucket(cfg, scores):
    """(archetype, second element, energy) for one finished run.

    The three resolutions here are the module's, deliberately: a rarity
    measured on a different definition of "second element" than the one
    printed beside it is a number about nothing. result_zodiac.js's
    `profileOf` is the other copy, and tests/test_zodiacprofile.py holds them
    to each other on a shared sample.
    """
    style_id = winner(cfg, scores)
    style = _style_by_id(cfg, style_id) or {}
    tags = style.get("tags") or []
    primary = next((t for t in tags if t in ELEMENTS), ELEMENTS[0])
    rest = [t for t in ELEMENTS if t != primary]
    # Anything the inverse step pushed below zero reads as zero, which is what
    # both renderers do: a negative score is a tap they told us to keep away
    # from, not a negative share of who they are. Counting the raw number here
    # would bucket a run under a different runner-up than the one the page
    # prints beside the rarity.
    at = lambda tag: max(0, scores.get(tag, 0))          # noqa: E731
    # Ties fall to the fixed element order, which is what the module does and
    # is the only tiebreak that gives the same answer in both languages.
    second = max(rest, key=lambda t: (at(t), -rest.index(t)))
    sun, moon = at("sun"), at("moon")
    if sun > moon:
        energy = "sun"
    elif moon > sun:
        energy = "moon"
    else:
        # Dead level: the archetype's own energy carries it, because the name
        # beside the number says both and a tie broken by list order can print
        # an energy the archetype does not hold.
        energy = next((t for t in tags if t in ENERGIES), "sun")
    return style_id, second, energy


# --- rarity -----------------------------------------------------------------

FLOOR, CEILING = 6, 40

# The rungs a rarity is allowed to land on. Short on purpose: "1 in 15" is a
# sentence and "1 in 17" is a measurement, and the gaps are wide enough that a
# retag has to move the distribution meaningfully before the printed number
# changes at all.
LADDER = (6, 8, 10, 12, 15, 20, 25, 30, 40)


def snap(raw):
    """One bucket's 1-in-N, clamped and snapped to the ladder."""
    if raw is None:
        return CEILING
    value = min(CEILING, max(FLOOR, raw))
    return min(LADDER, key=lambda rung: (abs(rung - value), rung))


def measure(cfg, runs, seed):
    """{(archetype, second, energy): raw 1-in-N} over a seeded random walk."""
    axis_map = axes(load_engine())
    rng = random.Random(seed)
    seen = collections.Counter()
    for _ in range(runs):
        seen[bucket(cfg, play(cfg, axis_map, rng.choice))] += 1
    out = {}
    for style in cfg["styles"]:
        primary = next(t for t in style["tags"] if t in ELEMENTS)
        for second in ELEMENTS:
            if second == primary:
                continue
            for energy in ENERGIES:
                hits = seen[(style["id"], second, energy)]
                out[(style["id"], second, energy)] = (
                    (runs / hits) if hits else None)
    return out


def rarity_table(cfg, runs, seed):
    """The committed shape: {archetype: {second: {energy: N}}}."""
    raw = measure(cfg, runs, seed)
    table = {}
    for (style_id, second, energy), value in raw.items():
        table.setdefault(style_id, {}).setdefault(second, {})[energy] = \
            snap(value)
    return table


# --- writing the configs ----------------------------------------------------

RUNS = 200000
SEED = 20260824


def block(rarity):
    """`result_copy.profile` for one funnel."""
    return {
        "subtypes": SUBTYPES,
        "sign_cross": SIGN_CROSS,
        "cards": CARDS,
        "scales": SCALES,
        "rarity": rarity,
        "formula": LINES["formula"],
        "rarity_line": LINES["rarity_line"],
        "bridge": LINES["bridge"],
        "offer_head": LINES["offer_head"],
        "split_caption": LINES["split_caption"],
    }


def shared(profile):
    """Everything in a profile block that must be identical on both funnels."""
    return {k: v for k, v in (profile or {}).items() if k != "rarity"}


def _write(path, cfg):
    """The config back to disk in the shape the repo already keeps it in."""
    with open(path, "w") as handle:
        json.dump(cfg, handle, indent=2, ensure_ascii=False)
        handle.write("\n")


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--runs", type=int, default=RUNS,
                        help="walks per funnel (default %d)" % RUNS)
    parser.add_argument("--seed", type=int, default=SEED)
    parser.add_argument("--check", action="store_true",
                        help="report staleness, write nothing, exit 1 if any")
    args = parser.parse_args(argv)

    stale = []
    for slug in FUNNELS:
        path = os.path.join(ROOT, "funnels/%s.json" % slug)
        with open(path) as handle:
            cfg = json.load(handle)
        rarity = rarity_table(cfg, args.runs, args.seed)
        wanted = block(rarity)
        have = (cfg.get("result_copy") or {}).get("profile")
        same = have == wanted
        print("%-10s %d walks  %s"
              % (slug, args.runs, "unchanged" if same else "written"))
        if not same:
            stale.append(slug)
            for style_id in sorted(rarity):
                for second in sorted(rarity[style_id]):
                    for energy in sorted(rarity[style_id][second]):
                        print("    %-15s %-6s %-5s  1 in %d"
                              % (style_id, second, energy,
                                 rarity[style_id][second][energy]))
        if args.check or same:
            continue
        cfg.setdefault("result_copy", {})["profile"] = wanted
        _write(path, cfg)

    if args.check and stale:
        print("stale: %s — run without --check" % ", ".join(stale))
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
