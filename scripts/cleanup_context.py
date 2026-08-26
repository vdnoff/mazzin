#!/usr/bin/env python3
"""Delete the checkout context of everybody who did not buy.

`checkout_context` holds one row per session that reached the pay button: the
buyer's IP address and User-Agent, captured because the Stripe webhook fires
from Stripe's request and so has neither, and Meta matches a conversion on
both. The row is useful for the minutes between the tap and the webhook, and
after that it is an address and a device fingerprint we have no reason to
hold.

Most of them never had a webhook at all — almost nobody buys — so most of
this table is the personal data of people who looked at a price and closed
the tab.

    python3 scripts/cleanup_context.py               # the default window
    python3 scripts/cleanup_context.py --hours 6     # a shorter one
    python3 scripts/cleanup_context.py --dry-run     # count, delete nothing

Exit status is 0 whether or not anything was removed; a cron job that mails on
failure should hear about a failure, not about a quiet Tuesday.

Cron, on the server:

    23 4 * * *  cd ~/mazzin && ~/.virtualenvs/mazzin/bin/python \\
                scripts/cleanup_context.py >> ~/mazzin_cleanup.log 2>&1
"""
import argparse
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import database    # noqa: E402

# A day, which is a long time for a row whose whole life is the gap between a
# tap and a webhook. Wide because the cost of being wrong in one direction is
# a conversion that matches worse and in the other is nothing at all.
DEFAULT_HOURS = 24

COUNT_SQL = (
    "SELECT COUNT(*) AS total, "
    "SUM(created_at <= NOW() - INTERVAL %s HOUR) AS stale "
    "FROM checkout_context"
)

DELETE_SQL = (
    "DELETE FROM checkout_context WHERE created_at <= NOW() - INTERVAL %s HOUR"
)


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--hours", type=float, default=DEFAULT_HOURS,
                    help="retention window (default: %d)" % DEFAULT_HOURS)
    ap.add_argument("--dry-run", action="store_true",
                    help="report what would go, delete nothing")
    args = ap.parse_args(argv)

    row = database.query_one(COUNT_SQL, (args.hours,)) or {}
    total = int(row.get("total") or 0)
    stale = int(row.get("stale") or 0)
    print("checkout context rows: %d, older than %.0fh: %d"
          % (total, args.hours, stale))

    if args.dry_run:
        print("dry run — nothing removed")
        return 0

    removed = database.execute_rowcount(DELETE_SQL, (args.hours,))
    print("removed: %d" % removed)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
