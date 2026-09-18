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
name, currency, `amount_cents` in that currency's minor units (the EN master prices at 199), and the
`price_format` / `decimal_mark` engine.js reads. Stripe's rules are encoded
per row — `amount_multiple` (100 for HUF, which is charged in whole
forints) and `stripe_min_cents` — and the generator refuses an amount that
breaks them.

The row also carries the market's value-framing anchor — the one money
figure the copy names — as `anchor_amount`, `anchor_format` (written around
`{n}`: `€{n}`, `{n} Ft`, `{n} kr.`) and `anchor_group` (the thousands
separator: `" "` for `100 000 Ft`, `"."` for `1.800 kr.`, `""` for none).
After translation the generator writes the three to `value_framing`
(`amount`, `amount_format`, `amount_group`) and swaps the master's literal
(`$250`) for the market's in every string of the funnel; the model is held
to handing that literal back unchanged so the swap can find it. A
non-English funnel that still names the literal — or carries any `$` at
all — is refused and nothing is written.

**A price test costs a table edit, not a regeneration.** Change the
`amount_cents` column in `scripts/locales.json` (and the master's own
pricing block for `en`), then re-price each funnel that is on disk:

```bash
for l in nl de hu cs pl da sk el; do python3 scripts/set_price.py blinds $l; done
```

`set_price.py` patches the existing file in place — the pricing block from
the locale row, the old written price ("790 Ft", "1,99 €") swapped for the
new in any line that named it literally, everything else byte-frozen, the
static mirror and the `-test` twin rewritten to match. No model call, so the
translation stays and the report cache is untouched; it refuses to write a
funnel in which the old figure still survives. `blinds en` re-prices the
master itself.

## The email gate

A funnel that carries a `lead_gate` block asks for an address where the
others ask for a price. The result page is the same page down to the unlock
list; where the offer stood, the module draws a form — headline, subline,
email box, an unticked tips box, the button, the privacy line — and the
commerce nodes stay hidden. Payments are not removed: `payments.py`, the
webhook, the purchase tables and the price configs are exactly what they
were, and a funnel without the block is the funnel it was, to the byte.

The block, on the master (`funnels/blinds.json`):

| key | what it is |
|---|---|
| `article_url` | the article the reader is sent to, in this funnel's language — tigerjar.com's canonical `?p=` form, which 301s to the pretty URL and keeps the anchor |
| `utm_campaign` | the campaign on the UTM triplet the server appends (`utm_source=mazzin&utm_medium=redirect` on the redirect, `email` on the mail) |
| `gate_mode` | `gate_first` — the result screen is the gate alone: the kicker, a sealed card that shows nothing computed, the form; nothing of the run (no style name, no number, no strip, no chapter) until the address is given. `after_result` (or absent) is the free profile above the gate as it first shipped. A per-funnel switch, no deploy; `?gate_mode=` on the URL overrides it for a look, like `?arm=` |
| `anchors` | style id → the article's section anchor, the same in every language |
| `copy` | the gate's words: `headline` and `subline` (after the result), `gate_headline` and `gate_subline` (gate first — never filled with `{style}`), `placeholder`, `button`, `sending`, `error_email`, `error_send`, `notice` (the line under the button, the privacy policy linked from its [brackets]), `sticky` (empty hides the sticky bar) |
| `mail` | the report mail: `subject`, `headline`, `summary` (`{style}`, `{scales}`), `scale` (`{pct}`, `{label}`), `cta`, `keep` |

What happens on submit: the page validates the address, `POST /api/lead`
(`leads.py`) validates it again, writes one `leads` row with the run's
facts, writes `lead_submit` (or `lead_dup` when the address is already
there for this funnel — same redirect, nothing re-sent), and answers with
the article URL anchored to the style; the browser goes there. The gate
reaching the reader is `lead_view`, fired from the same observer, with the
same `src`, at the same moment `paywall_view` fires on a priced funnel.

The report is mailed off the request by `scripts/send_lead_reports.py`,
run by cron every minute: it takes the leads whose `report_sent_at` is
NULL, builds each report from the warmed style cache and the stubs
(`reports.lead_content` — never a model call), mails it through Resend
with the article button and the PDF attached, and stamps the row. Keep
`warm_cache.py` warm for every language, or a lead gets stub chapters.

The leads are read on the dashboard, at `/admin/leads`, behind the same
login as the rest of it: total, today, last 7 days and the gate's
conversion (submits over result views, 7 days) at the top, a per-market
table beside them, the rows fifty a page newest first with the report
column reading ✓ or —, filters by vertical, market and a subid
contains-match, and a CSV export of whatever the filter matches. It reads
through the `(funnel, lang, created_at)` index the migration adds.

The eight generated funnels take the gate without a regeneration:
`scripts/lead_gate.json` carries each language's article URL, gate copy
and mail copy, and `scripts/set_gate.py blinds <lang>` writes the block
into the funnel on disk, byte-frozen otherwise, mirror and twin included.
A new master string goes into the table in every language first.

```bash
# apply schema_migrations.sql's `leads` table by hand, then:
cd ~/mazzin && for l in nl de hu cs pl da sk el; do python3 scripts/set_gate.py blinds $l; done
# cron, every minute:
* * * * *  cd ~/mazzin && ~/.virtualenvs/mazzin/bin/python scripts/send_lead_reports.py >> ~/mazzin_leads.log 2>&1
```

Every string the model touches is checked before it is accepted: same keys,
every `{token}` intact, no line breaks, no banned word. The answer is asked
for as a structured output (a JSON schema of the chunk's keys), so it is
valid JSON by contract on the models that support it; fences and commentary
are stripped before parsing regardless. A chunk that stays wrong after three
tries is split in half and each half asked for on its own, down to single
strings. A single string that still fails is kept in English, the run goes
on, and a `WARNING` at the end lists the paths to translate by hand — the
exit code is 0 whenever the funnel was written. To look at one bad chunk:

```bash
cd ~/mazzin && python3 scripts/make_funnel.py blinds hu --only-chunk 4   # raw answers on stderr, nothing written
```

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

### The zodiac30 look

A factory funnel renders on the zodiac result module rather than the
kitchen template, so it looks and flows like zodiac30. The keys that
carry it, all of them in the master and translated by the generator
(structure and ids frozen, strings translated):

| key | what it is |
|---|---|
| `theme: "zodiac"`, `result_module`, `result_css`, `result_template: "minimal"` | the dark theme, the module and its stylesheet, the minimal page |
| `paywall_variants` | one arm, `template: "minimal"`, weight 1 (`name` is copy) |
| `swipe.label_mode: "badge"`, `swipe.analyzing_fade_to`, `analyzing_echo` | badge labels, the fade into the dark page, the echo of the taps |
| `interstitials[]` | `template` confirm/almost, `kicker`, `line`, `sub`, `cta`, `auto_advance_ms`, `echo_steps` (no `personal` block: those lines are keyed on signs) |
| `report.sections[].teaser_line` | one line under each locked title, in the teaser boxes and the checklist fallback |
| `report.visuals.taps`, `.hero.glyph_step`, `.hero.band_step`, `.section_steps` | what the paid page draws: the taps strip, the badge and band frames, one frame per chapter |
| `checkout.express`, `checkout.commerce.price_anchor`, `price_anchor_accent`, `price_note`, `badges` | the wallet path and the offer card's own lines |
| `result_copy.kicker`, `blend_note`, `taps_caption`, `offer_sub`, `locked_note`, `delivered_note`, `delivery_line`, `delivery_line_bare` | the page's own words |
| `result_copy.labels.verdicts`, `saves_head`, `price_regular_aria`, `scale_aria` | what the delivered chapters print between the model's sentences |
| `result_copy.profile.glyph_step` | the step whose tapped frame is the hero badge |
| `result_copy.profile.split` | `{tags, names, colors}`: the bar over the funnel's own style tags |
| `result_copy.profile.scales[]` | `{id, left, right, left_tags, right_tags}`: a dot between two tag sets |
| `result_copy.profile.chips`, `formula`, `split_caption`, `offer_head` | filled from `{style}`, `{style_bare}`, `{lead}`, `{second}`, `{sections}`, one `{<tag>}` per split tag, one `{<scale id>}` per scale |
| `result_copy.profile.unlock[]`, `unlock_head`, `unlock_tail`, `cards[]` | the checklist in the offer card and the keyword over each delivered chapter |

| `value_framing.amount`, `amount_format`, `amount_group` (the locale writes all three), `unlock_row.key`, `unlock_row.line`, `scale.label`, `scale.value`, `scale.note`, `scale.aria` | the one money figure: "up to {amount}". `unlock_row` is the gold first row of the unlock list (`{amount}`, `{style}`); `scale` feeds the PDF cover's cost line and the phrase the report's prompt is held to |

The module reads the generic table only when the profile declares no
`subtypes`; a zodiac config is drawn exactly as before, and
`tests/test_minimal_generic.py` holds the four zodiac funnels to recorded
fixtures byte for byte.

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
