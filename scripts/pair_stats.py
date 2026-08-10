#!/usr/bin/env python3
"""Which variant pair wins, per step.

Console use only — nothing imports this and no route reaches it. Every step
owns several pairs asking the same question with different photographs, and
one is drawn per run; this is the readout that says which one to keep:

    cd ~/mazzin && python3 scripts/pair_stats.py

    python3 scripts/pair_stats.py kitchen        # one funnel
    python3 scripts/pair_stats.py --days 14      # a window
    python3 scripts/pair_stats.py --min 50       # hide pairs still too thin

Three numbers per pair, and they answer different questions:

  impressions   how often the draw handed this pair to somebody. Pairs inside
                a step should converge on equal shares — a lopsided split
                means the randomisation is not doing what it claims.
  pick rate     the split between the two images. This is the pair's own
                content telling you whether the question is a real choice or
                a foregone one; 50/50 is a genuine dilemma, 95/5 is a photo
                nobody wants next to one they do.
  continued     of the sessions shown this pair, how many went on to answer a
                later step. This is the one that matters. A pair can look
                decisive and still be the thing that ends the session.

Read against a step's other pairs, never across steps: step 1 carries every
arrival and step 9 only the people who stayed, so their continuation rates
are not comparable and nothing here pretends otherwise.

Reads only. No writes, no model calls, nothing that touches a purchase.
"""
import argparse
import glob
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import config          # noqa: E402
import database        # noqa: E402

# One pass over the swipes. `m` is each session's furthest step, so a row can
# say whether the session that saw this pair went any further without a second
# query per pair. Rows with no payload predate 3d and are left out rather than
# counted as a pair nobody can name.
STATS_SQL = """
SELECT
  JSON_UNQUOTE(JSON_EXTRACT(e.extra, '$.pair'))   AS pair_key,
  JSON_UNQUOTE(JSON_EXTRACT(e.extra, '$.chosen')) AS chosen,
  e.step                                          AS step_no,
  COUNT(*)                                        AS shows,
  SUM(CASE WHEN m.max_step > e.step THEN 1 ELSE 0 END) AS continued
FROM events e
JOIN (
  SELECT session_id, MAX(step) AS max_step
  FROM events
  WHERE funnel = %s AND event = 'swipe'
  GROUP BY session_id
) m ON m.session_id = e.session_id
WHERE e.funnel = %s
  AND e.event = 'swipe'
  AND e.extra IS NOT NULL
  AND JSON_EXTRACT(e.extra, '$.pair') IS NOT NULL
  {window}
GROUP BY pair_key, chosen, step_no
"""

WINDOW = "AND e.created_at >= NOW() - INTERVAL %s DAY"


def funnels(name):
    if name:
        return [name]
    found = glob.glob(os.path.join(config.FUNNELS_DIR, "*.json"))
    return sorted(os.path.splitext(os.path.basename(p))[0] for p in found)


def declared(cfg):
    """Every pair the config declares, and the images in it.

    The events only know about images somebody picked. A variant that has
    never once been chosen is exactly what this readout exists to find, so the
    shape comes from the config and the counts are hung off it.
    """
    out = []
    for step in ((cfg.get("swipe") or {}).get("steps") or []):
        if not isinstance(step, dict):
            continue
        pairs = step.get("pairs")
        if not (isinstance(pairs, list) and pairs):
            pairs = [{"id": "p1", "images": step.get("images") or []}]
        for pair in pairs:
            if not isinstance(pair, dict):
                continue
            images = [i for i in (pair.get("images") or [])
                      if isinstance(i, dict) and i.get("id")]
            out.append({
                "step": step.get("id") or "?",
                "question": step.get("question") or "",
                "pair": pair.get("id") or "p1",
                "key": "%s:%s" % (step.get("id"), pair.get("id") or "p1"),
                "images": images,
            })
    return out


def collect(slug, days):
    sql = STATS_SQL.format(window=WINDOW if days else "")
    params = (slug, slug, days) if days else (slug, slug)
    rows = database.query_all(sql, params) or []

    by_pair = {}
    for row in rows:
        key = row["pair_key"]
        bucket = by_pair.setdefault(
            key, {"shows": 0, "continued": 0, "picks": {}, "steps": set()})
        shows = int(row["shows"] or 0)
        bucket["shows"] += shows
        bucket["continued"] += int(row["continued"] or 0)
        bucket["picks"][row["chosen"]] = \
            bucket["picks"].get(row["chosen"], 0) + shows
        if row["step_no"] is not None:
            bucket["steps"].add(int(row["step_no"]))
    return by_pair


def pct(part, whole):
    return "  -  " if not whole else "%4.1f%%" % (100.0 * part / whole)


def report(slug, days, floor):
    try:
        cfg = config.load_funnel(slug)
    except KeyError:
        print("%s: no such funnel" % slug)
        return 1

    pairs = declared(cfg)
    if not pairs:
        print("%s: no steps declared" % slug)
        return 1

    try:
        stats = collect(slug, days)
    except Exception as exc:
        print("%s: could not read events (%s)" % (slug, type(exc).__name__))
        return 1

    window = ("last %d days" % days) if days else "all time"
    print("\n%s — %s" % (slug, window))
    print("=" * 72)

    total = sum(p["shows"] for p in stats.values())
    if not total:
        print("no swipe events carrying a pair yet — nothing to compare.")
        print("(events written before 3d have no payload and are not counted.)")
        return 0

    step_totals = {}
    for pair in pairs:
        step_totals[pair["step"]] = (step_totals.get(pair["step"], 0)
                                     + stats.get(pair["key"], {}).get("shows", 0))

    current = None
    thin = 0
    for pair in pairs:
        if pair["step"] != current:
            current = pair["step"]
            print("\n%s — %s" % (current, pair["question"]))
            print("  %-6s %8s %6s   %-26s %8s %7s"
                  % ("pair", "shown", "share", "image", "picks", "rate"))

        seen = stats.get(pair["key"], {})
        shows = seen.get("shows", 0)
        if shows < floor:
            thin += 1
            if not shows:
                print("  %-6s %8d %6s   %s"
                      % (pair["pair"], 0, "  -  ", "never shown"))
                continue

        print("  %-6s %8d %6s   %-26s %8s %7s"
              % (pair["pair"], shows, pct(shows, step_totals[pair["step"]]),
                 "", "", ""))
        for image in pair["images"]:
            picks = seen.get("picks", {}).get(image["id"], 0)
            print("  %-6s %8s %6s   %-26s %8d %7s"
                  % ("", "", "", "%s (%s)" % (image["id"],
                                              (image.get("label") or "")[:16]),
                     picks, pct(picks, shows)))
        print("  %-6s %8s %6s   %-26s %8s %7s"
              % ("", "", "", "continued to a later step",
                 seen.get("continued", 0), pct(seen.get("continued", 0), shows)))

    print("\n%d swipes across %d declared pairs%s"
          % (total, len(pairs),
             ("; %d pair(s) under the %d-event floor — too thin to read"
              % (thin, floor)) if thin and floor else ""))
    return 0


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("funnel", nargs="?", help="only this funnel")
    ap.add_argument("--days", type=int, default=0,
                    help="only events from the last N days (default: all)")
    ap.add_argument("--min", type=int, default=30, dest="floor",
                    help="flag pairs with fewer than N impressions (default 30)")
    args = ap.parse_args(argv)

    slugs = funnels(args.funnel)
    if not slugs:
        print("no funnels found in %s" % config.FUNNELS_DIR)
        return 1

    worst = 0
    for slug in slugs:
        worst = max(worst, report(slug, args.days, args.floor))
    return worst


if __name__ == "__main__":
    sys.exit(main())
