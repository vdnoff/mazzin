# Funnel factory

How a vertical becomes a swipe funnel in nine languages without a code
change per language. v1 ships the `blinds` vertical.

## The flow

```
scripts/galleries/<vertical>.json      the 36 images: id, tags, alt, prompt
        │
        ├── scripts/simulate_<vertical>.py   proves every style is reachable
        │
        ▼
funnels/<vertical>.json                the English master, hand-built
        │                              (carries its own report_profile block)
        ├── scripts/make_test_twin.py  → funnels/<vertical>-test.json (committed)
        │
        └── scripts/make_funnel.py <vertical> <lang>
                 │   translates every human-visible string (Anthropic API),
                 │   applies scripts/locales.json, names the funnel
                 ▼
            funnels/<vertical>-<lang>.json  +  static/funnels/<vertical>-<lang>.json
                 (server-side data: gitignored, mirrored by deploy.sh)

scripts/make_gallery.py <vertical>     draws static/galleries/<vertical>/
                                       (placeholders now, real images later)

GET /go?v=<vertical>&l=<lang>          routes an ad click to whichever of the
                                       above exists and queues the misses
```

Reports need no code per language because `reports.build_guide_profile()`
builds the profile from the config's `report_profile` block, and
`reports._profile()` falls back to it for any slug the registry does not
name. The registry (`PROFILES`) is untouched; every existing funnel reads
exactly the profile it always did.

## Add a language — one command

```bash
cd ~/mazzin && python3 scripts/make_funnel.py blinds hu --dry-run   # plan + token estimate
cd ~/mazzin && python3 scripts/make_funnel.py blinds hu             # the run
```

That writes `funnels/blinds-hu.json` and its `static/funnels/` mirror,
priced from `scripts/locales.json` (HUF, whole forints), with the report
profile's language set to Hungarian. Nothing else changes: `/blinds-hu`
serves, `/go?v=blinds&l=hu` lands on it, and a purchase gets a Hungarian
guide, PDF and mail. `--no-llm` pseudo-translates for a free dry walk.

To add a *new* language, add its row to `scripts/locales.json`: language
name, currency, `amount_cents` in that currency's minor units, and the
`price_format` / `decimal_mark` engine.js reads. Stripe's rules are encoded
per row — `amount_multiple` (100 for HUF, which is charged in whole
forints) and `stripe_min_cents` — and the generator refuses an amount that
breaks them.

Every string the model touches is checked before it is accepted: same keys,
every `{token}` intact, no line breaks, no banned word. A chunk that stays
wrong after three tries fails the run; nothing half-translated is written.

## Add a vertical

1. **Gallery spec** — `scripts/galleries/<vertical>.json`: 36 images with
   `id`, `filename` (`<id>.webp`), `tags` from the ten-tag system (five
   identity tags + warm/cool, dark/bright, wood/stone/metal, exactly as
   kitchen), `alt`, and a photorealistic generation prompt (no people, no
   text, no logos). `size` is the swipe frame (640x982) and `og` names the
   share card.
2. **Balance** — copy `scripts/simulate_blinds.py`, put the vertical's step
   plan in `PLAN`, run `--search`, and bake the winning identity tags into
   the spec. Every style must win at least 15% under both tapper models.
3. **Master config** — `funnels/<vertical>.json`, built on the kitchen
   shape: nine pair steps whose variant pairs share tags, five styles with
   full `reveals`, `style_elements`, the six report sections under the
   engine's ids (`palette` visible; `mistakes`, `materials`, `shopping`,
   `dna`, `splurge` locked), every engine chrome key (`checkout.unlock_note`,
   `number_words`, `redirecting`, `error_*`, `report.preparing`,
   `report.locked_aria`, `swipe.card_aria`), the delivery lines, integer
   USD pricing, the EU withdrawal line, `stripe_mode`, and a full
   `report_profile` block (see `funnels/blinds.json`). Mirror it to
   `static/funnels/` byte for byte.
4. **Twin** — `python3 scripts/make_test_twin.py <vertical>`; commit both
   copies. It is the one `<vertical>-*.json` that is committed.
5. **Gallery** — `python3 scripts/make_gallery.py <vertical> --placeholders`
   locally to walk it; the real draw runs on the server. Add
   `static/galleries/<vertical>/` to `.gitignore`.
6. **Check** — a `tests/test_<vertical>_check.py` in the shape of
   `tests/test_blinds_check.py`, including the simulation and the browser
   walk.

### The `report_profile` block

| key | what it is |
|---|---|
| `vertical_noun`, `language_name`, `pdf_lang` | fill the parametric system prompt; the generator sets the last two per language |
| `sections.<id>.brief` | one English line per section appended to its shape — model-facing, frozen by the generator |
| `stubs` | the six fallbacks in the model's own shape; `"colors": "from-config"` takes the style's four colours |
| `stub_colors` | the four (role, finish, where) sentences for a palette stub |
| `words` | what the PDF prints between the model's sentences (`fix`, `skip`, `splurge`, `save`, `verdicts`, …) |
| `mail` | `headline`, `subject`, `body` (one `{style}` each), `keep`, `keep_no_link`, `opening` (`{price}`), `opening_bare` |
| `pdf_lead`, `pdf_note` | the PDF's kicker and keep line |
| `banned` | extra regexes for the language, on top of the English list |
| `json_retry`, `prompt_budget` | optional, as the Romanian and Bulgarian profiles use them |

## The `/go` contract

`GET /go?v=<vertical>&l=<lang>&subid=…&utm_*=…`

- `v` and `l` are lowercased and must match `^[a-z0-9_-]{1,24}$`; a
  missing or bad `v`, or a bad `l`, is a bare 400. A missing `l` means `en`.
- Candidate slug is `<v>-<l>`, or `<v>` when `l` is `en`.
- If the candidate exists: `301 /<candidate>`.
- Else if `<v>` exists: `301 /<v>` and the miss is recorded.
- Else: `301 /kitchen` and the miss is recorded.
- The whole query string but `v` and `l` is carried onto the target, in
  order, so `subid` and every `utm_*` reach tracking.
- A `-test` twin is never a destination.
- The answer carries `Cache-Control: no-store`: the fallback tiers change
  the moment a language goes live, and a cached 301 would not.
- Recording is one upsert into `gen_queue` (`hits + 1`, `last_seen`),
  inside a try/except; a failed write logs the exception type only and
  never touches the redirect. No LLM call, no heavy work, ever.

`gen_queue` (see `schema_migrations.sql`): `vertical`, `lang`, `first_seen`,
`last_seen`, `hits`, `status` in `new / generating / live / rejected`,
unique on `(vertical, lang)`. Read it to see which languages are actually
being asked for; set `status` by hand as the batch works through them.

## Server runbook

In order, on the server, in the `mazzin` virtualenv:

```bash
# 1. schema (once, before the deploy that ships /go)
mysql -h "$DB_HOST" -u "$DB_USER" -p "$DB_NAME" -e "$(sed -n '/CREATE TABLE IF NOT EXISTS gen_queue/,/);/p' ~/mazzin/schema_migrations.sql)"

# 2. deploy
~/mazzin/deploy.sh claude/blinds-factory "funnel factory v1: blinds master + generator + /go router"

# 3. gallery — placeholders first so the funnel renders, then the real draw
cd ~/mazzin && python3 scripts/make_gallery.py blinds --placeholders
cd ~/mazzin && python3 scripts/make_gallery.py blinds --dry-run        # count + estimate
cd ~/mazzin && python3 scripts/make_gallery.py blinds                  # OPENAI_API_KEY from .env; resumable

# 4. batch translation — one command per language, ANTHROPIC_API_KEY from .env
cd ~/mazzin && for l in nl de hu cs pl da sk el; do python3 scripts/make_funnel.py blinds $l || break; done

# 5. warm the per-style report cache for each new funnel (optional, cuts first-purchase latency)
cd ~/mazzin && python3 scripts/warm_cache.py blinds
cd ~/mazzin && for l in nl de hu cs pl da sk el; do python3 scripts/warm_cache.py blinds-$l; done

# 6. re-mirror the generated configs to the CDN copy (deploy.sh does this on every deploy;
#    between deploys, after a batch:)
cp ~/mazzin/funnels/*.json ~/mazzin/static/funnels/

# 7. check
curl -sI "https://mazzin.com/go?v=blinds&l=hu&subid=check" | grep -i location
```

Generated funnels and gallery images are server-side data: they are
gitignored, survive a deploy (deploy merges and copies, it never cleans),
and are regenerated with the same commands if the disk is lost.
