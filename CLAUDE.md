# Mazzin — repo guide

Mobile-only swipe-quiz funnel platform. User taps through image pairs, gets a
free style result, sees a partially-locked report, hits a paywall.

## Architecture

**Static-first. Flask is an API, not a page renderer.**

- The funnel page (HTML, CSS, JS, funnel config JSON) is served straight from
  `/static/` by the web server / Cloudflare. No Flask worker is involved.
- Flask handles exactly three things: `/api/*`, `/health`, and the `/<slug>`
  route that hands back `static/funnel.html` with a cache header.
- `funnels/*.json` is the source of truth for funnel content. `deploy.sh`
  copies it to `static/funnels/` so the browser can fetch it from the CDN.
  Never edit `static/funnels/` by hand.
- No frontend framework, no build step. One IIFE in `engine.js`.

## Module ownership

| File | Owns | Never does |
|---|---|---|
| `app.py` | Routing, blueprint registration, `/health` | Business logic, DB queries beyond `SELECT 1` |
| `config.py` | Env vars, paths, `load_funnel()`, slug validation | DB, Stripe calls |
| `database.py` | MySQL (PyMySQL) connections, `execute` / `execute_rowcount` / `query_all` / `query_one` | Query construction for callers, ORM anything |
| `tracking.py` | `POST /api/track` — validate + one INSERT | Reads, joins, anything slow |
| `payments.py` | `POST /api/checkout`, `POST /api/stripe/webhook`, `GET /api/report` | Trusting a client-supplied amount, report copy |
| `reports.py` | `generate_report()` — builds and stores report content | HTTP routes, Stripe calls |
| `visualizer.py` | `/api/visualizer/*` — photo intake, EXIF stripping, the image-edit call, generation credits | Running on an unpaid purchase, writing under `static/`, putting a photo in a log line |
| `schema.sql` | Table definitions (from scratch) | Being edited after a migration ships |
| `schema_migrations.sql` | Append-only `ALTER`s applied on top of `schema.sql` | Being rewritten or reordered |
| `funnels/*.json` | Funnel content, styles, pricing, copy | — |
| `static/js/engine.js` | Swipe UX, scoring, screens, tracking calls, checkout redirect + report polling | Holding payment state it can't prove |
| `static/css/mazzin.css` | Mobile portrait styling | Desktop layout |
| `deploy.sh` / `rollback.sh` | Server deploy + recovery | Being run from anywhere but the server |

## Rules

1. **Never edit files on the server.** Change code here, push, run `deploy.sh`.
2. **Deploy via `deploy.sh` only.** No manual `git pull` on the server, no
   hand-editing `static/funnels/`.
3. **Money is `decimal.Decimal` in Python and integer cents in MySQL.**
   Never `float`, never store a formatted string.
4. **The Stripe webhook is the source of truth for purchases.** A client-side
   "payment succeeded" is a hint, not a fact. `purchase` is never an accepted
   value on `/api/track`.
5. **Purchase rows are never deleted.** Correct with a status change, not a
   `DELETE`.
6. **No PII in logs.** No emails, no session payloads, no raw request bodies.
   `/api/track` returns a bare 400 on bad input and logs nothing about it.
7. **Mobile portrait only.** Desktop layout is not a goal.
8. **`schema.sql` is history, not a worksheet.** Schema changes go into
   `schema_migrations.sql` as appended `ALTER` statements and are applied by
   hand on the server.
9. **Uploaded photographs never touch `static/`.** They are somebody's home.
   They live under `VISUALIZER_DIR`, are stripped of every EXIF tag on the way
   in, and are readable only through `/api/visualizer/image`, which checks the
   purchase token and answers `private, no-store`.
10. **A generation is only ever spent on a paid purchase.** The credit is
    claimed by a conditional `UPDATE`, not by reading a count and then writing
    one, and it is given back when no image was produced.

## Environment

- **Python 3.13.**
- **Server virtualenv is `mazzin`** at `/home/FarvaGO/.virtualenvs/mazzin`.
  Every `pip install` on the server happens inside it — never system-wide,
  never in another virtualenv.
- **DB driver is PyMySQL.** `mysql-connector-python` is gone; do not
  reintroduce it.
- Stripe runs in **test mode**. Keys live in `.env` and are never hardcoded
  or committed. A funnel carrying `"stripe_mode": "test"` transacts on the
  `STRIPE_TEST_*` key set instead; without those keys it refuses checkout
  rather than falling back to the live one.
- The visualizer needs `OPENAI_API_KEY`. Empty is a kill switch, not an error:
  generation reports itself unavailable and everything else still works.

## Local check

```bash
python3 -c "from app import app; print(app.url_map)"
```

`/health` needs a real database; the funnel page does not.
