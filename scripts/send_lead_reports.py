#!/usr/bin/env python3
"""Re-send the lead reports that did not go: the email gate's second try.

Console use only, run by hand. `/api/lead` renders and mails the report
inline, on the request, and stamps `report_sent_at`; a render or a send
that failed there leaves the stamp NULL and is logged by lead id. This is
how those rows are sent afterwards — the same routine the route ran,
`leads.send_report_for`, over every lead still NULL: the report from the
warmed style cache and the stubs (never a model call), the mail with the
article link, the stamp.

    python3 scripts/send_lead_reports.py               # the queue
    python3 scripts/send_lead_reports.py --dry-run     # list, send nothing
    python3 scripts/send_lead_reports.py --limit 20
    python3 scripts/send_lead_reports.py --id 42       # one, even if sent

A row is claimed before it is mailed — a conditional UPDATE that sets the
stamp only while it is NULL — so two overlapping runs cannot both send it;
a send that then fails puts the NULL back for the next run. A lock file
keeps the runs from overlapping in the first place.

No address is ever printed or logged: the id is what names a lead here.
Exit status 0 when every claimed lead was mailed (or there were none), 1
when any was put back.

Not scheduled: nothing runs this but a person, after a failure in the
log. It is safe to run any time — a queue with nothing in it is a line
saying so.
"""
import argparse
import fcntl
import logging
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import database                                 # noqa: E402
import leads                                    # noqa: E402

log = logging.getLogger("send_lead_reports")

SELECT_SQL = ("SELECT id, email, funnel, lang, style_key, scores_json "
              "FROM leads WHERE report_sent_at IS NULL ORDER BY id LIMIT %s")
SELECT_ONE_SQL = ("SELECT id, email, funnel, lang, style_key, scores_json "
                  "FROM leads WHERE id = %s")
CLAIM_SQL = ("UPDATE leads SET report_sent_at = NOW() "
             "WHERE id = %s AND report_sent_at IS NULL")
RECLAIM_SQL = "UPDATE leads SET report_sent_at = NOW() WHERE id = %s"
RELEASE_SQL = "UPDATE leads SET report_sent_at = NULL WHERE id = %s"
LOCK_PATH = os.path.join(leads.config.BASE_DIR, ".send_lead_reports.lock")


def deliver(row, send=None):
    """One lead's report, by the route's own routine. True when it went;
    a failure is logged by type and lead id, never by address."""
    try:
        return leads.send_report_for(row, send)
    except Exception as exc:                    # noqa: BLE001
        log.warning("lead %s: report not sent (%s)", row["id"],
                    type(exc).__name__)
        return False


def run(limit=50, dry_run=False, only_id=None, send=None):
    """Work the queue. Returns (sent, failed)."""
    if only_id is not None:
        row = database.query_one(SELECT_ONE_SQL, (only_id,))
        rows = [row] if row else []
    else:
        rows = database.query_all(SELECT_SQL, (limit,))
    print("%d lead(s) to mail" % len(rows))
    sent = failed = 0
    for row in rows:
        if dry_run:
            print("  lead %s  %s  %s  (dry run)" % (row["id"], row["funnel"],
                                                   row["style_key"]))
            continue
        if only_id is not None:
            database.execute_rowcount(RECLAIM_SQL, (row["id"],))
        elif database.execute_rowcount(CLAIM_SQL, (row["id"],)) != 1:
            continue                        # another run has it
        if deliver(row, send):
            sent += 1
            print("  lead %s  sent" % row["id"])
        else:
            failed += 1
            database.execute_rowcount(RELEASE_SQL, (row["id"],))
            print("  lead %s  not sent — released for the next run"
                  % row["id"])
    return sent, failed


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--limit", type=int, default=50)
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--id", type=int, help="one lead, even if already sent")
    args = ap.parse_args(argv)
    logging.basicConfig(level=logging.INFO,
                        format="%(levelname)s:%(name)s:%(message)s")
    with open(LOCK_PATH, "w") as lock:
        try:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except OSError:
            print("another run holds the lock — nothing done")
            return 0
        sent, failed = run(args.limit, args.dry_run, args.id)
    print("sent %d, released %d" % (sent, failed))
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
