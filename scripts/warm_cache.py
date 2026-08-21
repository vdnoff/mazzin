#!/usr/bin/env python3
"""Fill the per-style section cache for every funnel and style.

Console use only — nothing imports this and no route reaches it. Run it after
a deploy that moves the report schema, so the first buyer of each style is not
the one who pays for those three sections in latency:

    cd ~/mazzin && python3 scripts/warm_cache.py

    python3 scripts/warm_cache.py kitchen            # one funnel
    python3 scripts/warm_cache.py kitchen minimalist # one style
    python3 scripts/warm_cache.py --dry-run          # report, generate nothing

A funnel cloned from another starts cold even though its styles are the same
objects — the cache is keyed on the funnel too. Copy rather than regenerate:

    python3 scripts/warm_cache.py kitchen-visualizer --copy-from kitchen

which needs no model at all, and falls back to nothing: a section the source
does not have is reported missing rather than quietly generated.

It is idempotent: a second run over a warm cache reports "cached" for every
style and makes no model calls at all. Exit status is 0 when nothing failed,
1 when any style could not be filled, so it can gate a deploy step.
"""
import argparse
import glob
import logging
import os
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import config          # noqa: E402
import reports         # noqa: E402

# The interesting lines are reports' own — the summary below is this script's.
logging.basicConfig(level=logging.INFO,
                    format="%(levelname)s %(name)s: %(message)s")

MARK = {"cached": "=", "warmed": "+", "partial": "~", "failed": "!",
        "skipped": "-"}


def funnels(names):
    if names:
        return list(names)
    found = glob.glob(os.path.join(config.FUNNELS_DIR, "*.json"))
    return sorted(os.path.splitext(os.path.basename(p))[0] for p in found)


def styles(slug, wanted):
    cfg = config.load_funnel(slug)
    ids = [s.get("id") for s in cfg.get("styles", []) if s.get("id")]
    if wanted:
        return [i for i in ids if i in wanted]
    return ids


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("funnel", nargs="?", help="only this funnel")
    ap.add_argument("style", nargs="*", help="only these styles")
    ap.add_argument("--dry-run", action="store_true",
                    help="report what is missing without calling the model")
    ap.add_argument("--copy-from", metavar="FUNNEL",
                    help="fill from another funnel's cache instead of "
                         "generating (for a cloned funnel)")
    args = ap.parse_args(argv)

    slugs = funnels([args.funnel] if args.funnel else None)
    if not slugs:
        print("no funnels found in %s" % config.FUNNELS_DIR)
        return 1

    if args.copy_from and not config.funnel_exists(args.copy_from):
        print("no such funnel to copy from: %s" % args.copy_from)
        return 1

    if not config.ANTHROPIC_API_KEY and not (args.dry_run or args.copy_from):
        print("ANTHROPIC_API_KEY is not set — nothing can be generated.")
        print("Run with --dry-run to see what is missing.")
        return 1

    rows = []
    started = time.monotonic()
    for slug in slugs:
        try:
            style_ids = styles(slug, set(args.style))
        except KeyError:
            print("%-10s  no such funnel" % slug)
            rows.append({"funnel": slug, "style": "-", "status": "skipped",
                         "detail": "no such funnel"})
            continue

        for style_id in style_ids:
            if args.dry_run:
                have, stale = reports._cache_state(slug, style_id)
                have = have or {}
                # Which sections are cached is the funnel's business, not
                # this script's: /zodiac holds a different three from /kitchen.
                wanted = reports.cached_sections(slug)
                missing = [s for s in wanted if s not in have]
                row = {"funnel": slug, "style": style_id,
                       "status": "cached" if not missing else "failed",
                       "cached": [s for s in wanted if s in have], "warmed": [],
                       "failed": missing, "stale": stale,
                       "detail": "dry run"}
            elif args.copy_from:
                row = reports.copy_style_cache(args.copy_from, slug, style_id)
            else:
                row = reports.warm_style_cache(slug, style_id)

            rows.append(row)
            detail = row.get("detail") or ""
            parts = []
            if row.get("warmed"):
                parts.append("warmed " + ",".join(row["warmed"]))
            if row.get("cached"):
                parts.append("had " + ",".join(row["cached"]))
            if row.get("failed"):
                parts.append("MISSING " + ",".join(row["failed"]))
            if row.get("stale"):
                parts.append("%d stale rows replaced" % row["stale"])
            if detail:
                parts.append(detail)
            print("%s %-10s %-16s %-8s %s"
                  % (MARK.get(row["status"], "?"), slug, style_id,
                     row["status"], "; ".join(parts)))
            sys.stdout.flush()

    counts = {}
    for row in rows:
        counts[row["status"]] = counts.get(row["status"], 0) + 1
    print("\n%d styles in %.1fs — %s"
          % (len(rows), time.monotonic() - started,
             ", ".join("%s %d" % (k, counts[k]) for k in sorted(counts))))

    bad = [r for r in rows if r["status"] in ("failed", "partial")]
    if bad:
        print("\nstill incomplete:")
        for r in bad:
            print("  %s/%s: %s" % (r["funnel"], r["style"],
                                   ",".join(r.get("failed") or []) or "?"))
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
