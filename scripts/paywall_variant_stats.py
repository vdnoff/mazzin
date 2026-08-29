#!/usr/bin/env python3
"""Which paywall variant converts, split by variant and subid.

Console use only — nothing imports this and no route reaches it:

    cd ~/mazzin && python3 scripts/paywall_variant_stats.py persona

    python3 scripts/paywall_variant_stats.py persona --days 14
    python3 scripts/paywall_variant_stats.py persona --min 50
    python3 scripts/paywall_variant_stats.py persona --by-variant

The whole test is readable without a schema change, and this file is why.
`paywall_variant` writes one row per session saying which arm it was shown;
every event after it, and the purchase the webhook writes, already carry the
same `session_id`, and both tables index it. So conversion is a join, not a
column — and adding a third arm stays an edit to `paywall_variants` in the
funnel config with nothing to migrate.

Four numbers per row, and they answer different questions:

  shown       sessions assigned this arm. Arms with equal weights should
              converge on equal shares; a lopsided split on equal weights
              means assignment is not doing what it claims.
  reached     of those, how many actually saw the offer (`paywall_view`).
              An arm can win on conversion and lose here, which is a
              different problem from the one this test is asking about.
  paid        of those shown, how many ended with a paid purchase.
  rate        paid ÷ shown, as a percentage.

Read `--min` as the honesty threshold: a 100% rate on three sessions is
noise, and the default hides rows too thin to mean anything.

Reads only. No writes, no model calls, nothing that touches a purchase.
"""
import argparse
import datetime
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import analytics      # noqa: E402

# The query itself moved to analytics.py when the admin dashboard grew an A/B
# panel over the same numbers. It is imported rather than copied for one
# reason: two readouts of the same test that can disagree are worse than one
# readout, and the only way they can disagree is by drifting apart on the SQL.
#
# Nothing about this script's output changed with the move. The one difference
# under it is where the window's clock comes from: the range used to be
# `NOW() - INTERVAL N DAY`, measured by the database, and is now measured here
# and passed as a timestamp. Same window on a server whose clock agrees with
# its database, which is every server this runs on.


def rows_for(funnel, days):
    """The stats rows for a funnel, optionally limited to the last N days."""
    start = None
    if days:
        start = datetime.datetime.now() - datetime.timedelta(days=days)
    return analytics.variant_rows(funnel, start=start)


def rate(paid, shown):
    return analytics.rate(paid, shown)


def fold(rows):
    """Collapse the subid dimension, for the headline number per arm."""
    return analytics.fold_variants(rows)


def show(rows, floor):
    thin = [r for r in rows if int(r["shown"] or 0) < floor]
    rows = [r for r in rows if int(r["shown"] or 0) >= floor]
    if not rows:
        print("  nothing over the --min floor yet"
              "%s" % (" (%d rows under it)" % len(thin) if thin else ""))
        return
    print("  %-14s %-22s %7s %8s %6s %7s"
          % ("variant", "subid", "shown", "reached", "paid", "rate"))
    for row in rows:
        shown = int(row["shown"] or 0)
        print("  %-14s %-22s %7d %8d %6d %6.1f%%"
              % (row["variant"], row["subid"][:22], shown,
                 int(row["reached"] or 0), int(row["paid"] or 0),
                 rate(int(row["paid"] or 0), shown)))
    if thin:
        print("  (%d row%s under the --min floor, hidden)"
              % (len(thin), "" if len(thin) == 1 else "s"))


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("funnel", help="funnel slug, e.g. persona")
    ap.add_argument("--days", type=int, default=0,
                    help="only the last N days (default: all time)")
    ap.add_argument("--min", type=int, default=20, dest="floor",
                    help="hide rows with fewer sessions than this")
    ap.add_argument("--by-variant", action="store_true",
                    help="collapse subid and show one row per arm")
    args = ap.parse_args(argv)

    rows = rows_for(args.funnel, args.days)
    if not rows:
        print("no paywall_variant events for %s%s"
              % (args.funnel,
                 " in the last %d days" % args.days if args.days else ""))
        return 0
    print("%s — paywall variants%s"
          % (args.funnel,
             " (last %d days)" % args.days if args.days else ""))
    show(fold(rows) if args.by_variant else rows, args.floor)
    return 0


if __name__ == "__main__":
    sys.exit(main())
