#!/usr/bin/env python3
"""Style win-rate simulation for the blinds funnel — the tag balance check.

Console use only. Nothing imports this at request time and no route reaches
it. It is what decided the tag assignment in scripts/galleries/blinds.json,
and it is what tests/test_blinds_check.py reruns to prove the committed
config still passes:

    cd ~/mazzin && python3 scripts/simulate_blinds.py            # evaluate
    cd ~/mazzin && python3 scripts/simulate_blinds.py --search   # re-search

A faithful port of engine.js's scoring, and only its scoring: every tag on a
tapped image scores one point, an `"scoring": "inverse"` step scores minus a
half, a style's total is the sum over its own tags, and the winner is the
highest total with ties going to the first style listed in the config
(`computeWinner` compares with a strict greater-than). Which of a step's
variant pairs is drawn does not matter here because every variant of a step
carries the same tags as its sibling — the test asserts that — so the walk
is exactly nine binary choices and can be enumerated in full rather than
sampled: 2^9 = 512 sequences, weighted under two models of the person
tapping.

  random   every sequence equally likely. A funnel that fails this one hands
           a style to people who were not choosing it, and starves another.
  persona  five tappers, one per style, each picking the card whose tags
           overlap their own style's tags most, with a NOISE chance of
           tapping the other one instead. Averaged over the five, so a style
           whose own persona cannot reach it pulls the number down. The
           diagonal — how often persona s lands on style s — is printed too.

Both models must give EVERY style at least FLOOR of the wins. That is the
same bar the kitchen rebalance was held to (see the fix-style-balance
commit), and the search below is that method: the descriptive tags of a
photograph are what they are, the identity tag is the one degree of freedom,
and a hill-climb over the semantically valid identity tags finds the
assignment with the highest minimum share.
"""
import argparse
import itertools
import json
import os
import random
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
FUNNEL = os.path.join(ROOT, "funnels", "blinds.json")
GALLERY = os.path.join(ROOT, "scripts", "galleries", "blinds.json")

FLOOR = 0.15
NOISE = 0.2
INVERSE_WEIGHT = -0.5

# The search space: per step, the two card slots, each with its fixed
# descriptive tags and the identity tags a photograph of that scene could
# honestly carry. Variant pairs share a slot. Slot order is the pair order.
PLAN = [
    ("hook", None, [
        (("bright", "cool"), ("minimal", "modern")),
        (("dark", "warm"), ("classic",)),
    ]),
    ("material", None, [
        (("warm", "wood"), ("rustic", "modern")),
        (("cool", "metal"), ("industrial", "minimal")),
    ]),
    ("light", None, [
        (("bright", "warm"), ("modern", "rustic")),
        (("dark", "cool"), ("minimal", "industrial")),
    ]),
    ("pattern", None, [
        (("cool", "stone"), ("minimal", "modern")),
        (("warm", "wood"), ("classic", "rustic")),
    ]),
    ("slats", None, [
        (("warm", "wood"), ("modern", "classic")),
        (("dark", "metal"), ("industrial", "minimal")),
    ]),
    ("bedroom", None, [
        (("warm", "dark"), ("classic",)),
        (("cool", "bright"), ("minimal", "modern")),
    ]),
    ("living", None, [
        (("warm", "stone"), ("rustic", "classic")),
        (("dark", "metal"), ("industrial",)),
    ]),
    ("kitchen", None, [
        (("bright", "wood"), ("modern", "minimal")),
        (("bright", "stone"), ("classic", "rustic")),
    ]),
    ("dealbreaker", "inverse", [
        (("dark", "metal"), ("industrial",)),
        (("warm", "wood"), ("rustic",)),
    ]),
]

STYLES = [
    ("modern_minimal", ("minimal", "cool", "bright", "metal")),
    ("warm_scandi", ("modern", "warm", "bright", "wood")),
    ("classic_elegant", ("classic", "warm", "dark", "wood")),
    ("natural_organic", ("rustic", "warm", "wood", "stone")),
    ("bold_statement", ("industrial", "dark", "cool", "metal")),
]


def steps_from_config(cfg):
    """[(scoring, [tags of card A, tags of card B])] off a funnel config.

    Every pair of a step must carry the same tags slot for slot, or the walk
    is not nine binary choices and this enumeration is not the funnel.
    """
    out = []
    for step in cfg["swipe"]["steps"]:
        slots = None
        for pair in step["pairs"]:
            tags = [tuple(img["tags"]) for img in pair["images"]]
            if slots is None:
                slots = tags
            elif [sorted(t) for t in tags] != [sorted(t) for t in slots]:
                raise ValueError("step %s: variant pairs disagree on tags"
                                 % step["id"])
        if len(slots) != 2:
            raise ValueError("step %s is not a pair" % step["id"])
        out.append((step.get("scoring"), slots))
    return out


def styles_from_config(cfg):
    return [(s["id"], tuple(s["tags"])) for s in cfg["styles"]]


def winner(scores, styles):
    best, best_score = 0, float("-inf")
    for i, (_, tags) in enumerate(styles):
        total = sum(scores.get(t, 0) for t in tags)
        if total > best_score:
            best, best_score = i, total
    return best


def evaluate(steps, styles):
    """{'random': [share per style], 'persona': [...], 'diag': [...]}."""
    n = len(steps)
    random_wins = [0.0] * len(styles)
    persona_wins = [0.0] * len(styles)
    diag = [0.0] * len(styles)
    # Per persona and per step, the probability of tapping card 0.
    prefer = []
    for _, style_tags in styles:
        row = []
        for scoring, slots in steps:
            a = len(set(slots[0]) & set(style_tags))
            b = len(set(slots[1]) & set(style_tags))
            # A rejection step: the persona rejects the card that looks
            # LEAST like them.
            if scoring == "inverse":
                a, b = b, a
            if a == b:
                row.append(0.5)
            else:
                row.append(1 - NOISE if a > b else NOISE)
        prefer.append(row)

    for seq in itertools.product((0, 1), repeat=n):
        scores = {}
        for (scoring, slots), pick in zip(steps, seq):
            weight = INVERSE_WEIGHT if scoring == "inverse" else 1
            for t in slots[pick]:
                scores[t] = scores.get(t, 0) + weight
        won = winner(scores, styles)
        random_wins[won] += 1.0 / (2 ** n)
        for p, row in enumerate(prefer):
            prob = 1.0
            for step_i, pick in enumerate(seq):
                prob *= row[step_i] if pick == 0 else 1 - row[step_i]
            persona_wins[won] += prob / len(styles)
            if won == p:
                diag[p] += prob
    return {"random": random_wins, "persona": persona_wins, "diag": diag}


def passes(result, floor=FLOOR):
    return (min(result["random"]) >= floor
            and min(result["persona"]) >= floor)


def report(result, styles, out=print):
    out("  %-18s %8s %9s %9s" % ("style", "random", "persona", "self"))
    for i, (sid, _) in enumerate(styles):
        out("  %-18s %7.1f%% %8.1f%% %8.1f%%"
            % (sid, 100 * result["random"][i], 100 * result["persona"][i],
               100 * result["diag"][i]))
    out("  minimum share %.1f%% (floor %.0f%%) — %s"
        % (100 * min(min(result["random"]), min(result["persona"])),
           100 * FLOOR, "PASS" if passes(result) else "FAIL"))


# --- search ------------------------------------------------------------------

def assignment_steps(choice):
    """The steps for one identity-tag choice (one index per slot)."""
    steps = []
    k = 0
    for _, scoring, slots in PLAN:
        cards = []
        for fixed, options in slots:
            cards.append(tuple(fixed) + (options[choice[k]],))
            k += 1
        steps.append((scoring, cards))
    return steps


def objective(choice, styles):
    result = evaluate(assignment_steps(choice), styles)
    return min(min(result["random"]), min(result["persona"]))


def search(styles, restarts=40, seed=1):
    rng = random.Random(seed)
    sizes = [len(options) for _, _, slots in PLAN for _, options in slots]
    best_choice, best_score = None, -1
    for _ in range(restarts):
        choice = [rng.randrange(s) for s in sizes]
        score = objective(choice, styles)
        improved = True
        while improved:
            improved = False
            for k in range(len(choice)):
                for alt in range(sizes[k]):
                    if alt == choice[k]:
                        continue
                    trial = list(choice)
                    trial[k] = alt
                    trial_score = objective(trial, styles)
                    if trial_score > score:
                        choice, score, improved = trial, trial_score, True
        if score > best_score:
            best_choice, best_score = choice, score
    return best_choice, best_score


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("--search", action="store_true",
                    help="hill-climb the identity tags instead of evaluating "
                         "the committed config")
    ap.add_argument("--restarts", type=int, default=40)
    args = ap.parse_args(argv)

    if args.search:
        choice, score = search(STYLES, args.restarts)
        steps = assignment_steps(choice)
        print("best assignment (min share %.1f%%):" % (100 * score))
        for (step_id, _, _), (_, cards) in zip(PLAN, steps):
            print("  %-12s %s | %s" % (step_id, " ".join(cards[0]),
                                      " ".join(cards[1])))
        report(evaluate(steps, STYLES), STYLES)
        return 0

    with open(FUNNEL, encoding="utf-8") as fh:
        cfg = json.load(fh)
    steps = steps_from_config(cfg)
    styles = styles_from_config(cfg)
    print("blinds: %d steps, %d styles, %d sequences per model"
          % (len(steps), len(styles), 2 ** len(steps)))
    result = evaluate(steps, styles)
    report(result, styles)
    return 0 if passes(result) else 1


if __name__ == "__main__":
    sys.exit(main())
