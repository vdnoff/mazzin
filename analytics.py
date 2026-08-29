"""Read-only aggregates over `events` and `purchases`.

Owns the SQL behind the admin dashboard and the console stats scripts, and
nothing else: every statement in this file is a SELECT. There is no write
path here, no route, no Stripe call and no model call — a caller that wants
to change something has to go somewhere else for it.

Two shapes of number come out of here and they are not interchangeable:

  sessions   COUNT(DISTINCT session_id). This is the funnel's unit. A reader
             who reloads the result page fires `result_view` twice and is one
             reader, so every step count is distinct sessions and every rate
             below is a ratio of them.
  cents      integer cents, exactly as the column stores them. Money leaves
             this module as an int and is turned into a `Decimal` at the edge
             that formats it — never a float, ever, and never a string in the
             database.

Every query is bounded by a half-open window, `start <= created_at < end`.
Half-open is what makes "today" and "the 7 days ending today" adjoin without
double-counting the midnight between them.
"""

import decimal
import os

import config
import database

# The events the dashboard reports on, in funnel order. `swipe` is deliberately
# not here: it is one event name with a `step` column behind it, so it is
# counted by `swipe_steps` rather than as a single column.
#
# `purchase` is not here either, and cannot be: tracking.py refuses it as a
# client-asserted event, and the only truthful count of a sale is the
# `purchases` table the Stripe webhook writes.
FUNNEL_EVENTS = (
    "funnel_start",
    "result_view",
    "paywall_view",
    "pay_tap",
    "share_tap",
)

# Only these two are read out of `purchases`. `pending` is a checkout that
# started and may never finish; counting it as revenue would be counting an
# intention. Refunds keep their row (purchases are never deleted) and are
# excluded here by the same rule.
PAID_STATUS = "paid"

# What a row with no `subid` is called on screen. A literal rather than NULL
# so it groups, sorts and reads like any other campaign.
NO_SUBID = "(none)"

# A purchase whose session has no `funnel_start` inside the window — the
# reader arrived yesterday and paid today, or the start row predates the
# window for any other reason. It is real revenue and it is shown, in its own
# row, rather than being silently dropped out of the per-subid split or
# quietly folded into `(none)`.
UNATTRIBUTED = "(unattributed)"


# --- funnels ---------------------------------------------------------------

def funnel_slugs():
    """Every funnel the config directory declares, in a stable order.

    From the configs rather than from the event table on purpose: a funnel
    that has not been started once today still has a row, showing zero, which
    is the number the owner actually wants to see. Reading the slugs out of
    `events` would make a dead funnel disappear exactly when it matters.

    `-test` twins follow the same rule as the route that serves them: they
    are a live funnel's shape on Stripe test keys, and they are listed only
    while the server admits they exist.
    """
    try:
        names = os.listdir(config.FUNNELS_DIR)
    except OSError:
        return []
    slugs = []
    for name in names:
        if not name.endswith(".json"):
            continue
        slug = name[:-len(".json")]
        if not config.valid_slug(slug):
            continue
        if config.is_test_slug(slug) and not config.TEST_FUNNELS:
            continue
        slugs.append(slug)
    return sorted(slugs)


def funnel_meta(slug):
    """Display facts about a funnel, read off its config. Never raises.

    A config that will not parse is not a reason for the dashboard to fall
    over — the row still appears, named by its slug, with whatever could not
    be read left empty.
    """
    meta = {
        "slug": slug,
        "title": slug,
        "funnel_id": None,
        "steps": 0,
        "currency": None,
        "amount_cents": None,
        "test_mode": False,
        "shares": False,
        "variants": [],
    }
    try:
        cfg = config.load_funnel(slug)
    except (KeyError, ValueError, OSError):
        return meta
    title = (cfg.get("meta") or {}).get("title")
    if isinstance(title, str) and title.strip():
        meta["title"] = title.strip()
    meta["funnel_id"] = cfg.get("funnel_id")
    steps = (cfg.get("swipe") or {}).get("steps") or []
    meta["steps"] = len(steps)
    pricing = cfg.get("pricing") or {}
    meta["currency"] = pricing.get("currency")
    meta["amount_cents"] = pricing.get("amount_cents")
    meta["test_mode"] = cfg.get("stripe_mode") == "test"
    meta["shares"] = bool(cfg.get("share_cards"))
    meta["variants"] = variant_config(cfg)
    return meta


def variant_config(cfg):
    """The paywall arms a config declares, with the share each one is live at.

    The pool rule is result_persona.js's, restated here rather than guessed:
    an arm is assignable when it is not `enabled: false` and its weight is
    above zero, and a pool of exactly one renders unconditionally whatever it
    weighs. Getting this wrong would put a number on the screen saying an arm
    takes half the traffic when the config has it switched off — which is the
    one thing this panel exists to make impossible to believe.
    """
    arms = []
    for variant in (cfg.get("paywall_variants") or []):
        if not isinstance(variant, dict) or not isinstance(variant.get("id"),
                                                           str):
            continue
        weight = variant.get("weight")
        weight = weight if isinstance(weight, (int, float)) else 1
        weight = weight if weight > 0 else 0
        enabled = variant.get("enabled") is not False and weight > 0
        arms.append({
            "id": variant["id"],
            "name": variant.get("name") or variant["id"],
            "enabled": enabled,
            "weight": weight,
            "share": 0.0,
        })
    live = [a for a in arms if a["enabled"]]
    if len(live) == 1:
        live[0]["share"] = 100.0
    else:
        total = sum(a["weight"] for a in live)
        for arm in live:
            arm["share"] = (100.0 * arm["weight"] / total) if total else 0.0
    return arms


# --- windows ---------------------------------------------------------------

def _window_clause(column, start, end):
    """`(sql fragment, params)` for a half-open window on `column`.

    Either bound may be absent, which is what lets the console script keep its
    open-ended "everything since N days ago" while the dashboard always asks
    for a closed range.
    """
    parts = []
    params = []
    if start is not None:
        parts.append("AND %s >= %%s" % column)
        params.append(start)
    if end is not None:
        parts.append("AND %s < %%s" % column)
        params.append(end)
    return " ".join(parts), params


# --- event counts ----------------------------------------------------------

EVENT_COUNT_SQL = """
SELECT e.event AS event, COUNT(DISTINCT e.session_id) AS sessions
FROM events e
WHERE e.funnel = %s
  AND e.event IN ({names})
  {window}
GROUP BY e.event
"""


def event_counts(funnel, start=None, end=None, events=FUNNEL_EVENTS):
    """`{event: sessions}` for one funnel, zero-filled for every event asked.

    One query per funnel rather than one query for all of them: the index is
    `(funnel, event, created_at)`, so a constant funnel and a short list of
    constant event names make this an index range scan, where a single
    `GROUP BY funnel, event` over a date range would read the table.
    """
    window, params = _window_clause("e.created_at", start, end)
    sql = EVENT_COUNT_SQL.format(
        names=", ".join(["%s"] * len(events)), window=window)
    rows = database.query_all(
        sql, tuple([funnel] + list(events) + params)) or []
    counts = {name: 0 for name in events}
    for row in rows:
        counts[row["event"]] = int(row["sessions"] or 0)
    return counts


SWIPE_STEPS_SQL = """
SELECT e.step AS step, COUNT(DISTINCT e.session_id) AS sessions
FROM events e
WHERE e.funnel = %s
  AND e.event = 'swipe'
  AND e.step IS NOT NULL
  {window}
GROUP BY e.step
ORDER BY e.step
"""


def swipe_steps(funnel, start=None, end=None):
    """`{step: sessions}` — how far into the quiz readers actually get."""
    window, params = _window_clause("e.created_at", start, end)
    rows = database.query_all(
        SWIPE_STEPS_SQL.format(window=window), tuple([funnel] + params)) or []
    return {int(row["step"]): int(row["sessions"] or 0) for row in rows
            if row["step"] is not None}


SUBID_EVENTS_SQL = """
SELECT COALESCE(e.subid, %s) AS subid,
       e.event                AS event,
       COUNT(DISTINCT e.session_id) AS sessions
FROM events e
WHERE e.funnel = %s
  AND e.event IN ({names})
  {window}
GROUP BY COALESCE(e.subid, %s), e.event
"""


def subid_events(funnel, start=None, end=None, events=FUNNEL_EVENTS):
    """`{subid: {event: sessions}}` — the same columns, split by campaign."""
    window, params = _window_clause("e.created_at", start, end)
    sql = SUBID_EVENTS_SQL.format(
        names=", ".join(["%s"] * len(events)), window=window)
    rows = database.query_all(
        sql,
        tuple([NO_SUBID, funnel] + list(events) + params + [NO_SUBID])) or []
    out = {}
    for row in rows:
        cell = out.setdefault(row["subid"], {name: 0 for name in events})
        cell[row["event"]] = int(row["sessions"] or 0)
    return out


# --- purchases -------------------------------------------------------------

PURCHASES_SQL = """
SELECT p.currency AS currency,
       COUNT(*)   AS purchases,
       COALESCE(SUM(p.amount_cents), 0) AS cents
FROM purchases p
WHERE p.funnel = %s
  AND p.status = %s
  {window}
GROUP BY p.currency
"""


def purchase_totals(funnel, start=None, end=None):
    """`[{currency, purchases, cents}]`, one row per currency.

    Per currency because the funnels are not all priced in one: zodiac-ro
    sells in RON and everything else in USD, and a single summed number over
    the two would be a number of nothing. Nothing here converts between them,
    which is deliberate — a rate would have to come from somewhere and be
    wrong by the time it was read.
    """
    window, params = _window_clause("p.created_at", start, end)
    rows = database.query_all(
        PURCHASES_SQL.format(window=window),
        tuple([funnel, PAID_STATUS] + params)) or []
    return [{"currency": (row["currency"] or "").lower(),
             "purchases": int(row["purchases"] or 0),
             "cents": int(row["cents"] or 0)} for row in rows]


SUBID_PURCHASES_SQL = """
SELECT COALESCE(a.subid, %s) AS subid,
       p.currency            AS currency,
       COUNT(*)              AS purchases,
       COALESCE(SUM(p.amount_cents), 0) AS cents
FROM purchases p
JOIN (
  SELECT e.session_id AS session_id, MIN(e.subid) AS subid
  FROM events e
  WHERE e.funnel = %s
    AND e.event = 'funnel_start'
    {window_events}
  GROUP BY e.session_id
) a ON a.session_id = p.session_id
WHERE p.funnel = %s
  AND p.status = %s
  {window_purchases}
GROUP BY COALESCE(a.subid, %s), p.currency
"""


def subid_purchases(funnel, start=None, end=None):
    """`{subid: [{currency, purchases, cents}]}`, attributed by session join.

    `purchases` carries no `subid` column and does not need one: the webhook
    writes the same `session_id` the browser reported its arrival on, and both
    tables index it. So attribution is a join against the `funnel_start` row
    — which is where the campaign the reader was actually acquired on lives —
    rather than a column copied onto every sale.

    A sale whose start row is outside the window drops out of this join. The
    caller reconciles it against `purchase_totals` and shows the difference as
    `(unattributed)`; it is not this function's job to invent a row for it.
    """
    ev_window, ev_params = _window_clause("e.created_at", start, end)
    pu_window, pu_params = _window_clause("p.created_at", start, end)
    sql = SUBID_PURCHASES_SQL.format(
        window_events=ev_window, window_purchases=pu_window)
    params = ([NO_SUBID, funnel] + ev_params
              + [funnel, PAID_STATUS] + pu_params + [NO_SUBID])
    rows = database.query_all(sql, tuple(params)) or []
    out = {}
    for row in rows:
        out.setdefault(row["subid"], []).append({
            "currency": (row["currency"] or "").lower(),
            "purchases": int(row["purchases"] or 0),
            "cents": int(row["cents"] or 0),
        })
    return out


# --- paywall variants ------------------------------------------------------

# One row per session: the arm it was assigned, and the subid it arrived on.
# `MIN(created_at)` collapses a session that somehow reported twice — a reload
# on a cached page, an engine a version apart — to the assignment it saw first,
# so a session counts once in exactly one arm.
#
# The subid comes off the assignment row rather than off the purchase, because
# it is the attribution the reader was actually acquired on; a purchase row
# carries its own copy and they are the same value.
#
# The window binds the assignment only. `reached` and `paid` are then asked
# about that cohort with no window of their own, on purpose: a reader assigned
# on Sunday who pays on Monday is a conversion of Sunday's arm, and clipping
# the purchase to the same range would quietly under-report whichever arm was
# shown last.
VARIANT_SQL = """
SELECT
  a.variant                                   AS variant,
  COALESCE(a.subid, '(none)')                 AS subid,
  COUNT(*)                                    AS shown,
  SUM(CASE WHEN v.session_id IS NOT NULL THEN 1 ELSE 0 END) AS reached,
  SUM(CASE WHEN p.session_id IS NOT NULL THEN 1 ELSE 0 END) AS paid
FROM (
  SELECT
    e.session_id,
    JSON_UNQUOTE(JSON_EXTRACT(e.extra, '$.variant')) AS variant,
    MIN(e.subid)                                     AS subid
  FROM events e
  WHERE e.funnel = %s
    AND e.event = 'paywall_variant'
    AND e.extra IS NOT NULL
    AND JSON_EXTRACT(e.extra, '$.variant') IS NOT NULL
    {window}
  GROUP BY e.session_id, variant
) a
LEFT JOIN (
  SELECT DISTINCT session_id FROM events
  WHERE funnel = %s AND event = 'paywall_view'
) v ON v.session_id = a.session_id
LEFT JOIN (
  SELECT DISTINCT session_id FROM purchases
  WHERE funnel = %s AND status = 'paid'
) p ON p.session_id = a.session_id
GROUP BY variant, subid
ORDER BY variant, shown DESC
"""


def variant_rows(funnel, start=None, end=None):
    """Per variant × subid: shown, reached, paid. The A/B readout's one query.

    Shared, not copied. `scripts/paywall_variant_stats.py` prints these rows
    on a console and `/admin/api/variants/<slug>` serves them as JSON, and the
    only way the two can ever disagree about what an arm converted at is if
    they stop running the same statement — so they run this one.
    """
    window, params = _window_clause("e.created_at", start, end)
    sql = VARIANT_SQL.format(window=window)
    return database.query_all(
        sql, tuple([funnel] + params + [funnel, funnel])) or []


def fold_variants(rows):
    """Collapse the subid dimension, for the headline number per arm."""
    out = {}
    for row in rows:
        cell = out.setdefault(row["variant"],
                              {"variant": row["variant"], "subid": "(all)",
                               "shown": 0, "reached": 0, "paid": 0})
        for key in ("shown", "reached", "paid"):
            cell[key] += int(row[key] or 0)
    return sorted(out.values(), key=lambda c: -c["shown"])


# --- arithmetic ------------------------------------------------------------

def rate(part, whole):
    """`part / whole` as a percentage, and 0.0 rather than an exception."""
    part = int(part or 0)
    whole = int(whole or 0)
    return (100.0 * part / whole) if whole else 0.0


# What a currency is written with. Anything not listed prints its code after
# the amount, which is the right answer for a currency nobody has decided a
# symbol for yet — and is never wrong, only plain.
CURRENCY_SYMBOLS = {"usd": "$", "eur": "€", "gbp": "£"}


def money(cents):
    """Integer cents as a `Decimal`. Never a float, at any point.

    The division is by a `Decimal`, so nothing here ever becomes binary
    floating point — which is the whole of the house rule about money, applied
    at the one place cents turn into an amount somebody reads.
    """
    return (decimal.Decimal(int(cents or 0))
            / decimal.Decimal(100)).quantize(decimal.Decimal("0.01"))


def format_money(cents, currency):
    """`$12.00`, or `120.00 RON` for a currency with no symbol here."""
    amount = money(cents)
    code = (currency or "").lower()
    symbol = CURRENCY_SYMBOLS.get(code)
    if symbol:
        return "%s%s" % (symbol, amount)
    return "%s %s" % (amount, code.upper() or "?")
