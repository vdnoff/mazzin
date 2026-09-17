#!/usr/bin/env python3
"""Mail every lead their report: the email gate's delivery, off the request.

Console use only, run by cron. `/api/lead` writes the row and redirects the
reader in one round trip; this is the other half — the PDF render and the
mail call it deliberately did not do. Each run takes the leads whose
`report_sent_at` is NULL, builds each report from the warmed style cache
and the stubs (never a model call — see reports.lead_content), mails it
with the article link, and stamps the row.

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

Cron, on the server, every minute:

    * * * * *  cd ~/mazzin && ~/.virtualenvs/mazzin/bin/python \\
               scripts/send_lead_reports.py >> ~/mazzin_leads.log 2>&1
"""
import argparse
import fcntl
import json
import logging
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import config                                   # noqa: E402
import database                                 # noqa: E402
import leads                                    # noqa: E402
import reports                                  # noqa: E402

log = logging.getLogger("send_lead_reports")

SELECT_SQL = ("SELECT id, email, funnel, lang, style_key, scores_json "
              "FROM leads WHERE report_sent_at IS NULL ORDER BY id LIMIT %s")
SELECT_ONE_SQL = ("SELECT id, email, funnel, lang, style_key, scores_json "
                  "FROM leads WHERE id = %s")
CLAIM_SQL = ("UPDATE leads SET report_sent_at = NOW() "
             "WHERE id = %s AND report_sent_at IS NULL")
RECLAIM_SQL = "UPDATE leads SET report_sent_at = NOW() WHERE id = %s"
RELEASE_SQL = "UPDATE leads SET report_sent_at = NULL WHERE id = %s"
LOCK_PATH = os.path.join(config.BASE_DIR, ".send_lead_reports.lock")


def scores_of(row):
    raw = row.get("scores_json")
    if not raw:
        return None
    try:
        data = json.loads(raw)
    except ValueError:
        return None
    return data if isinstance(data, dict) else None


def deliver(row, send=reports.send_lead_email):
    """Build and mail one lead's report. True when it went."""
    try:
        cfg = config.load_funnel(row["funnel"])
    except Exception:
        log.warning("lead %s: funnel %s cannot be loaded", row["id"],
                    row["funnel"])
        return False
    gate = leads.gate_of(cfg)
    if gate is None:
        log.warning("lead %s: %s has no lead_gate", row["id"], row["funnel"])
        return False
    scores = scores_of(row)
    try:
        content = reports.lead_content(row["funnel"], row["style_key"], scores)
    except Exception as exc:
        log.warning("lead %s: report not built (%s)", row["id"],
                    type(exc).__name__)
        return False
    link = leads.article_link(gate, row["style_key"], leads.UTM_EMAIL)
    return bool(send(row["id"], row["email"], cfg, content, scores, link))


def run(limit=50, dry_run=False, only_id=None, send=reports.send_lead_email):
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
