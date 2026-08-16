#!/usr/bin/env python3
"""Delete photographs uploaded by people who never bought anything.

The visualizer takes the photo before the money, so most of the pictures it
receives belong to somebody who looked at the price and closed the tab. They
are pictures of the inside of a stranger's house and there is no reason to
keep them: after the window they are removed, read by nobody.

The app sweeps on its own every few minutes while uploads are arriving, so
this is a belt to that braces — it matters on a quiet week, when nothing has
hit the upload endpoint since the last photograph was left behind.

    python3 scripts/cleanup_pending.py              # the configured window
    python3 scripts/cleanup_pending.py --hours 6    # a shorter one
    python3 scripts/cleanup_pending.py --dry-run    # count, delete nothing

Exit status is 0 whether or not anything was removed; a cron job that mails on
failure should hear about a failure, not about a Tuesday with no uploads.

Cron, on the server:

    17 4 * * *  cd ~/mazzin && ~/.virtualenvs/mazzin/bin/python \\
                scripts/cleanup_pending.py >> ~/mazzin_cleanup.log 2>&1
"""
import argparse
import os
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import config       # noqa: E402
import visualizer   # noqa: E402


def survey(root, cutoff):
    """(total, stale, bytes_stale) without removing anything."""
    total = stale = size = 0
    try:
        names = os.listdir(root)
    except OSError:
        return 0, 0, 0
    for name in names:
        path = os.path.join(root, name)
        source = os.path.join(path, "source.jpg")
        try:
            stamp = (os.path.getmtime(source) if os.path.isfile(source)
                     else os.path.getmtime(path))
        except OSError:
            continue
        total += 1
        if stamp <= cutoff:
            stale += 1
            try:
                size += os.path.getsize(source)
            except OSError:
                pass
    return total, stale, size


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--hours", type=float,
                    help="override the retention window (default: %.0f)"
                         % (config.VISUALIZER_PENDING_MAX_AGE_S / 3600.0))
    ap.add_argument("--dry-run", action="store_true",
                    help="report what would go, delete nothing")
    args = ap.parse_args(argv)

    max_age = (args.hours * 3600.0 if args.hours is not None
               else config.VISUALIZER_PENDING_MAX_AGE_S)
    root = os.path.join(config.VISUALIZER_DIR, visualizer.PENDING)

    total, stale, size = survey(root, time.time() - max_age)
    print("pending photos: %d, older than %.0fh: %d (%.1f MB)"
          % (total, max_age / 3600.0, stale, size / 1048576.0))

    if args.dry_run:
        print("dry run — nothing removed")
        return 0

    removed = visualizer.purge_pending(max_age)
    print("removed: %d" % removed)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
