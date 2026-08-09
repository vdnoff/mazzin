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
| `database.py` | MySQL connections, `execute` / `query_all` / `query_one` | Query construction for callers, ORM anything |
| `tracking.py` | `POST /api/track` — validate + one INSERT | Reads, joins, anything slow |
| `schema.sql` | Table definitions | — |
| `funnels/*.json` | Funnel content, styles, pricing, copy | — |
| `static/js/engine.js` | Swipe UX, scoring, screens, tracking calls | Payment logic (Phase 1b) |
| `static/css/mazzin.css` | Mobile portrait styling | Desktop layout |
| `deploy.sh` / `rollback.sh` | Server deploy + recovery | Being run from anywhere but the server |

Phase 1b adds `payments.py` and `reports.py`. They do not exist yet.

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

## Local check

```bash
python3 -c "from app import app; print(app.url_map)"
```

`/health` needs a real database; the funnel page does not.
