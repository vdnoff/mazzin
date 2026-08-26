#!/usr/bin/env python3
"""Write a funnel's sandbox twin: the same funnel, on Stripe test keys.

Console use only, run by hand. Nothing imports this and no route reaches it.
Its outputs are committed, so a deploy copies files and builds nothing:

    cd ~/mazzin && python3 scripts/make_test_twin.py zodiac-ro

A twin is the source config with exactly three fields changed:

    slug         <slug>          ->  <slug>-test
    funnel_id    <funnel_id>     ->  <funnel_id>_test
    stripe_mode  live            ->  test

Everything else is the source's, byte for byte — the same steps, the same
images, the same copy, the same price. That is the point of it: a twin that
had drifted would be testing something other than the funnel it is named
after. Both copies are written, `funnels/` and `static/funnels/`, because the
browser fetches the second one and `deploy.sh` mirrors the first over it.

`stripe_mode: "test"` is what makes it safe to walk end to end: payments.py
transacts that funnel on the STRIPE_TEST_* key set, and refuses checkout
outright rather than falling back to the live keys when those are missing.
The twin still has to be *reachable*, which is a separate switch and off by
default — see `TEST_FUNNELS` in config.py.

Idempotent. Rerun it after the source config changes and the twin catches up;
rerunning against an unchanged source rewrites the same bytes and says so.
tests/test_testtwin_check.py is what fails if somebody edits the source and
forgets this step.

Exit status is 0 when both files are on disk and correct, 1 when the source
cannot be read or is not a funnel this can twin.
"""
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import config          # noqa: E402

# The three fields, and nothing else. Named here rather than spelled inline
# below so the list of what a twin changes is readable in one place — the
# test asserts the complement of it.
TWINNED = ("slug", "funnel_id", "stripe_mode")

MIRRORS = ("funnels", os.path.join("static", "funnels"))


def twin_of(cfg, slug):
    """The twin config for `cfg`, or raise ValueError.

    Key order is the source's: this is written back out as JSON that wants to
    diff cleanly against the original, and a reordered file is a diff nobody
    can read.
    """
    for field in TWINNED:
        if not isinstance(cfg.get(field), str) or not cfg[field]:
            raise ValueError("source funnel has no %s to twin" % field)
    if config.is_test_slug(slug):
        raise ValueError("%s is already a twin — twin the source instead"
                         % slug)

    out = dict(cfg)
    out["slug"] = slug + config.TEST_SUFFIX
    out["funnel_id"] = cfg["funnel_id"] + "_test"
    out["stripe_mode"] = "test"
    if not config.valid_slug(out["slug"]):
        raise ValueError("twin slug %r is not a valid slug" % out["slug"])
    return out


def main(argv=None):
    argv = list(sys.argv[1:] if argv is None else argv)
    if len(argv) != 1:
        print(__doc__.strip().split("\n\n")[0])
        print("\nusage: python3 scripts/make_test_twin.py <slug>")
        return 1
    slug = argv[0]

    try:
        cfg = config.load_funnel(slug)
    except KeyError:
        print("no such funnel: %s" % slug)
        return 1
    except (ValueError, OSError) as exc:
        print("could not read %s: %s" % (slug, exc))
        return 1

    try:
        out = twin_of(cfg, slug)
    except ValueError as exc:
        print("cannot twin %s: %s" % (slug, exc))
        return 1

    # The source's own formatting, so the two files diff line for line.
    text = json.dumps(out, indent=2, ensure_ascii=False) + "\n"
    for directory in MIRRORS:
        path = os.path.join(config.BASE_DIR, directory,
                            out["slug"] + ".json")
        before = None
        if os.path.isfile(path):
            with open(path, "r", encoding="utf-8") as fh:
                before = fh.read()
        with open(path, "w", encoding="utf-8") as fh:
            fh.write(text)
        state = "unchanged" if before == text else (
            "refreshed" if before is not None else "written")
        print("%-9s %s" % (state, os.path.relpath(path, config.BASE_DIR)))

    print("%s -> %s  (funnel_id %s, stripe_mode %s)"
          % (slug, out["slug"], out["funnel_id"], out["stripe_mode"]))
    return 0


if __name__ == "__main__":
    sys.exit(main())
