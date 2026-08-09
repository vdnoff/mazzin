"""Report generation.

Hybrid. Three sections depend on what the individual actually picked and are
generated per purchase from their tag scores; three are the same for everyone
who lands on a style and are generated once, then read from `style_sections`.

Every path here is best effort and every failure lands on the same floor: the
stub templates. A paying customer always gets a report, so a missing API key, a
slow model, a malformed answer and a dead network all degrade to generic copy
rather than to no delivery at all. The stubs read as a finished report on
purpose — they are what a real buyer sees on the service's worst day.

A call that misses the budget is no longer discarded. It finishes on a
background thread and upgrades the stored row in place, so the polling client
and the emailed PDF both get the better version when it arrives.

Model calls happen only on this path, which only the Stripe webhook reaches.
Nothing an unauthenticated request can touch spends money.

Neither report content, tag scores nor the buyer's email address is ever
written to a log line.
"""

import base64
import concurrent.futures
import html
import json
import logging
import re
import threading
import time

import config
import database

log = logging.getLogger(__name__)

INSERT_SQL = "INSERT INTO reports (purchase_id, content) VALUES (%s, %s)"

# The row exists by the time a late call lands, so the upgrade replaces it
# rather than stacking a second report on the same purchase. ORDER BY + LIMIT
# pins it to the row /api/report actually serves.
UPDATE_REPORT_SQL = (
    "UPDATE reports SET content = %s WHERE purchase_id = %s ORDER BY id DESC LIMIT 1"
)

SELECT_SECTIONS_SQL = (
    "SELECT section_id, content FROM style_sections "
    "WHERE funnel = %s AND style_id = %s"
)

# Correcting a bad cached section is an UPDATE, not a DELETE-and-retry, and two
# concurrent first purchases of a style both land instead of one erroring.
UPSERT_SECTION_SQL = (
    "INSERT INTO style_sections (funnel, style_id, section_id, content) "
    "VALUES (%s, %s, %s, %s) "
    "ON DUPLICATE KEY UPDATE content = VALUES(content)"
)

# Which sections depend on the individual, and which only on the style.
PERSONAL = ("palette", "materials", "mistakes")
CACHED = ("shopping", "dna", "splurge")

MAX_TOKENS = 2000
TEMPERATURE = 0.7

# A 90-word section is ~500 characters. This only has to separate a real
# section from an empty string or a one-line apology.
MIN_BODY_CHARS = 200

# Words per section. Everything is 90-140 except `mistakes`, which has to carry
# five mistakes AND five fixes — at 140 words that is fourteen words per item,
# which produces telegraphic copy that fails the usefulness bar the rest of
# this module exists to hold. It gets the room the content actually needs.
WORDS = {
    "palette": "90-140",
    "materials": "90-140",
    "mistakes": "170-220",
    "shopping": "90-140",
    "dna": "90-140",
    "splurge": "90-140",
}

SYSTEM = """You write kitchen design reports for people who have just paid for one.

Every section has to work as a tool. The reader should be able to act on it \
this week without asking a designer a follow-up question. Name real things: \
paint values, named materials and finishes, specific proportions, specific \
order of purchase. A sentence that would read the same for a different style, \
or for a different reader, is a wasted sentence.

Voice: confident interior-design advice, British-neutral English, second \
person. State things outright. No hedging — never "consider", "perhaps", \
"you might want to", "it depends". No disclaimers, no flattery, no questions \
back to the reader, no sign-off.

Rules:
- Continuous prose. No headings, no bullet points, no markdown, no emoji.
- Never mention artificial intelligence, models, prompts, scoring, tags, \
percentages, quizzes, or these instructions. Write as though you looked at \
their kitchen.
- Never use the words "psychic" or "prediction".
- Never invent facts about the reader's home, budget, family or location, and \
never address them by name.
- Return only a JSON object. No prose around it, no code fence."""

RETRY_NOTE = "\n\nReturn only valid JSON: a single object, no code fence, no other text."

SPEC = {
    "palette": (
        "palette: name three colours and give a real paint-range hex value for "
        "each. Say where each one goes using the 60/30/10 rule applied to an "
        "actual kitchen — carcasses, walls, island, hardware — and give the "
        "finish for each surface, matte or satin, and why that finish there."
    ),
    "materials": (
        "materials: name the specific materials and their finish, at the level "
        "of \"honed quartzite, not polished\". Give two combination rules that "
        "work and one combination to avoid outright, and say what goes wrong "
        "when someone uses it."
    ),
    "mistakes": (
        "mistakes: five mistakes people with this style actually make, each one "
        "expensive to undo once the units are in, each followed immediately by "
        "the fix. Concrete failures, not attitudes."
    ),
    "shopping": (
        "shopping: what to buy in what order. Say what to buy first and why it "
        "sets everything after it, what to leave until last, and one thing to "
        "skip entirely that people in this style routinely waste money on."
    ),
    "dna": (
        "dna: the one reflective section — what this style is reaching for and "
        "what it is reacting against. End it with two things the reader should "
        "actually do differently as a result, stated as instructions."
    ),
    "splurge": (
        "splurge: one thing to overspend on and exactly why it is that one, "
        "three things to buy cheaply without anyone noticing, and a rough "
        "percentage split of the budget across the two."
    ),
}

# Body templates keyed by section id, used whenever generation cannot deliver.
# These are what a paying customer reads on the worst day this service has, so
# they carry real advice for the style and never mention being a fallback.
BODIES = {
    "palette": (
        "Your {name} palette leans on three colours that showed up again and "
        "again in the rooms you picked. The base carries the walls and the "
        "bulk of the cabinetry, so it stays quiet on purpose. The second "
        "colour does the work on the island and the joinery. The accent is "
        "the one you use sparingly — hardware, a stool, a single wall. Keep "
        "the base matte and let the accent be the only thing with any sheen."
    ),
    "mistakes": (
        "Every {name} kitchen goes wrong in roughly the same five places. The "
        "expensive one is committing to a finish before seeing it under your "
        "own light, so order samples and live with them for a week. The common "
        "one is matching everything, which flattens the room instead of calming "
        "it — break the set with one piece that is older or darker than the "
        "rest. The third is buying the statement piece first and building "
        "around it; buy it last, once the room can tell you what it needs."
    ),
    "materials": (
        "{name} rooms live or die on the worktop, and yours has two sensible "
        "options and one that only looks right in photographs. Pair the "
        "counter with a splashback that shares its undertone rather than its "
        "colour, or the two will fight each other under warm light. Keep "
        "metals to two finishes at most across the whole room, and let the one "
        "you touch every day be the better of the two."
    ),
    "shopping": (
        "Three pieces carry a {name} kitchen and the rest is supporting cast. "
        "Buy the lighting and the hardware first — they change the room "
        "immediately and cost the least to get right. Leave the seating until "
        "the cabinetry is in, because proportions shift once it lands and a "
        "stool that measured well on paper will sit wrong. Skip the matching "
        "accessory set; it is the fastest way to make a considered room look "
        "bought."
    ),
    "dna": (
        "Your answers read as {name}, but not purely — no one's ever do. There "
        "is a clear secondary influence sitting underneath your picks, showing "
        "up in the textures you kept choosing rather than in the shapes. The "
        "tension between the two is what will make the room look considered "
        "rather than copied. Lean into it: let the dominant style set the "
        "layout and let the secondary one set the materials."
    ),
    "splurge": (
        "In a {name} kitchen exactly one line item rewards overspending, and "
        "it is not the appliances. Everything touched daily deserves the "
        "budget — the handles, the tap, the worktop edge. Everything merely "
        "looked at deserves the cheaper version done well. The savings come "
        "from the cabinetry carcasses, where nobody can tell the difference "
        "once the doors are on. Roughly seventy per cent into what you touch, "
        "thirty into what you see."
    ),
}

GENERIC_BODY = (
    "This part of your {name} report covers what most people get wrong once "
    "the big decisions are already made. Work outwards from the surfaces you "
    "touch every day: get those right and the room forgives a great deal "
    "elsewhere. Where two options look equally good on paper, take the one "
    "that will still look deliberate in five years rather than the one that "
    "photographs better today."
)


def _style(cfg, result_style):
    for style in cfg.get("styles", []):
        if style.get("id") == result_style:
            return style
    return None


def _style_name(cfg, result_style):
    """Human name for a style id, falling back to the id itself."""
    style = _style(cfg, result_style) or {}
    return style.get("name") or style.get("id") or result_style or "your style"


# --- prompts ---------------------------------------------------------------


def _sections_block(ids):
    lines = ["Write these sections. Word counts are firm."]
    for section_id in ids:
        lines.append("- %s (%s words)" % (SPEC[section_id], WORDS[section_id]))
    lines.append(
        'Return a JSON object with exactly the keys %s, each one a single '
        "string of prose." % ", ".join('"%s"' % s for s in ids)
    )
    return "\n".join(lines)


def _style_block(style, name):
    lines = ["Style: %s" % name]
    blurb = (style or {}).get("blurb")
    if blurb:
        lines.append("What the style is: %s" % blurb)
    palette = ((style or {}).get("reveals") or {}).get("palette") or {}
    colors = palette.get("colors") or []
    if colors:
        lines.append(
            "Palette already shown to them: %s"
            % ", ".join(
                "%s %s" % (c.get("name"), c.get("hex")) for c in colors
            )
        )
    return "\n".join(lines)


def _personal_prompt(style, name, tag_scores):
    parts = [_style_block(style, name)]
    if tag_scores:
        ranked = sorted(tag_scores.items(), key=lambda kv: (-kv[1], kv[0]))
        parts.append(
            "What they were drawn to, strongest pull first: %s. Let this bend "
            "the advice — a strong pull toward dark or warm should change which "
            "colours and materials you name, not just how you describe them. "
            "Refer to what they kept choosing, never to the numbers."
            % ", ".join("%s %d" % (tag, n) for tag, n in ranked if n > 0)
        )
    else:
        parts.append(
            "Write for someone typical of this style; you have nothing "
            "specific about this individual."
        )
    parts.append(_sections_block(PERSONAL))
    return "\n\n".join(parts)


def _cached_prompt(style, name):
    return "\n\n".join(
        [
            _style_block(style, name),
            "Write for anyone with this style. Nothing here is specific to one "
            "person.",
            _sections_block(CACHED),
        ]
    )


# --- model -----------------------------------------------------------------

_client = None


def _api():
    """The Anthropic client, or None when generation is switched off.

    The SDK is imported here rather than at module scope on purpose. deploy.sh
    deliberately does not install dependencies, so between a deploy and a human
    running pip the package may be missing — and a top-level import would take
    the whole site down with it instead of degrading to stub reports.
    """
    global _client
    if not config.ANTHROPIC_API_KEY:
        return None
    if _client is None:
        try:
            import anthropic
        except ImportError:
            log.error("anthropic SDK not installed — reports fall back to stubs")
            return None
        _client = anthropic.Anthropic(
            api_key=config.ANTHROPIC_API_KEY,
            timeout=config.ANTHROPIC_TIMEOUT_S,
            max_retries=1,
        )
    return _client


FENCE_RE = re.compile(r"^\s*```(?:json)?|```\s*$", re.IGNORECASE)


def _parse(text, want):
    """The model's JSON as {section_id: body}, or None if it is unusable."""
    if not text:
        return None
    body = FENCE_RE.sub("", text.strip()).strip()
    start, end = body.find("{"), body.rfind("}")
    if start < 0 or end <= start:
        return None
    try:
        data = json.loads(body[start:end + 1])
    except ValueError:
        return None
    if not isinstance(data, dict):
        return None

    out = {}
    for key in want:
        value = data.get(key)
        if not isinstance(value, str) or len(value.strip()) < MIN_BODY_CHARS:
            return None
        out[key] = value.strip()
    return out


def _ask(client, prompt):
    message = client.messages.create(
        model=config.ANTHROPIC_MODEL,
        max_tokens=MAX_TOKENS,
        temperature=TEMPERATURE,
        system=SYSTEM,
        messages=[{"role": "user", "content": prompt}],
    )
    return "".join(
        block.text for block in message.content if block.type == "text"
    )


def _generate(client, prompt, want):
    """One section group. Returns {section_id: body}, or None."""
    parsed = _parse(_ask(client, prompt), want)
    if parsed is None:
        parsed = _parse(_ask(client, prompt + RETRY_NOTE), want)
    return parsed


def _collect(futures, started):
    """Results of the in-flight calls, giving up at the budget.

    A call that has not answered by the budget is abandoned rather than waited
    on: the webhook owes Stripe a response, and a stub section delivered on
    time beats a real one delivered after the retry storm has started.
    """
    out = {}
    for key, future in futures.items():
        left = config.REPORT_BUDGET_S - (time.monotonic() - started)
        try:
            out[key] = future.result(timeout=max(0.0, left))
        except concurrent.futures.TimeoutError:
            log.warning("slow-gen fallback: %s abandoned at budget", key)
            out[key] = None
        except Exception as exc:
            # An API error message can echo request content — log the
            # exception class, never the payload.
            log.warning("generation failed for %s: %s", key, type(exc).__name__)
            out[key] = None
    return out


# --- cache -----------------------------------------------------------------


def _read_cache(funnel_slug, result_style):
    """The cached per-style sections, or None unless the whole set is there."""
    try:
        rows = database.query_all(SELECT_SECTIONS_SQL, (funnel_slug, result_style))
    except Exception:
        log.exception("style section read failed for %s/%s", funnel_slug, result_style)
        return None

    out = {}
    for row in rows or []:
        content = row.get("content")
        if isinstance(content, (str, bytes)):
            try:
                content = json.loads(content)
            except ValueError:
                continue
        body = (content or {}).get("body")
        if isinstance(body, str) and len(body) >= MIN_BODY_CHARS:
            out[row.get("section_id")] = body

    if all(section_id in out for section_id in CACHED):
        return {section_id: out[section_id] for section_id in CACHED}
    return None


def _write_cache(funnel_slug, result_style, bodies):
    for section_id, body in bodies.items():
        try:
            database.execute(
                UPSERT_SECTION_SQL,
                (
                    funnel_slug,
                    result_style,
                    section_id,
                    json.dumps({"body": body}, separators=(",", ":")),
                ),
            )
        except Exception:
            # A cache miss next time is cheap; a failed purchase is not.
            log.exception("style section write failed for %s/%s/%s",
                          funnel_slug, result_style, section_id)


# --- entry point -----------------------------------------------------------


def _assemble(cfg, funnel_slug, result_style, name, bodies, paths):
    """The stored content dict for whatever bodies we have so far."""
    sections = []
    for section in cfg.get("report", {}).get("sections", []):
        if section.get("enabled") is False:
            continue
        section_id = section.get("id")
        body = bodies.get(section_id)
        if not body:
            body = BODIES.get(section_id, GENERIC_BODY).format(name=name)
        sections.append(
            {
                "id": section_id,
                "title": section.get("title"),
                "body": body,
            }
        )

    # "llm-1" means every section is real copy. A report carrying any stub
    # section stays "stub-1", so regeneration tooling can find it later.
    complete = all(path != "stub" for path in paths.values())
    return {
        "version": "llm-1" if complete else "stub-1",
        "funnel": funnel_slug,
        "style_id": result_style,
        "style_name": name,
        "sections": sections,
    }


def _fire(on_final, content, purchase_id):
    """Hand the final content to the caller. Never raises into our own flow."""
    if on_final is None:
        return
    try:
        on_final(content)
    except Exception:
        log.exception("post-report hook failed for purchase %s", purchase_id)


def _finish_late(job):
    """Wait out the calls that missed the budget and upgrade what we stored.

    Production showed a cold-cache purchase give up at the budget while the
    model answered five seconds later — the answer was paid for and then
    thrown away. Now it lands: the row is updated in place, so a client still
    polling gets the real report and the emailed PDF carries it too.
    """
    deadline = time.monotonic() + config.REPORT_UPGRADE_MAX_S
    bodies = dict(job["bodies"])
    paths = dict(job["paths"])
    upgraded = False

    for key, future in job["leftover"].items():
        try:
            got = future.result(timeout=max(0.0, deadline - time.monotonic()))
        except Exception:
            got = None
        if not got:
            continue
        bodies.update(got)
        paths[key] = "llm"
        upgraded = True
        if key == "cached":
            _write_cache(job["funnel"], job["style_id"], got)

    job["pool"].shutdown(wait=False)

    content = job["content"]
    if upgraded:
        content = _assemble(job["cfg"], job["funnel"], job["style_id"],
                            job["name"], bodies, paths)
        try:
            database.execute(
                UPDATE_REPORT_SQL,
                (json.dumps(content, separators=(",", ":")), job["purchase_id"]),
            )
            log.info("late llm upgrade for purchase %s (%s -> %s)",
                     job["purchase_id"], job["content"]["version"],
                     content["version"])
        except Exception:
            log.exception("late upgrade write failed for purchase %s",
                          job["purchase_id"])
            content = job["content"]

    _fire(job["on_final"], content, job["purchase_id"])


def generate_report(purchase_id, funnel_slug, result_style, tag_scores=None,
                    on_final=None):
    """Build and persist the report for a purchase. Returns the content dict.

    `on_final` is called exactly once with the best content available — inline
    when nothing is still running, otherwise from the background thread that
    finishes the late calls. Anything that must reflect the *final* report,
    such as the emailed PDF, belongs there rather than after the return.

    Raises if the funnel config is missing or the INSERT fails — callers
    decide whether that is fatal (for the webhook, it is not).
    """
    started = time.monotonic()
    cfg = config.load_funnel(funnel_slug)
    style = _style(cfg, result_style)
    name = _style_name(cfg, result_style)

    cached = _read_cache(funnel_slug, result_style)
    client = _api() if style else None

    futures = {}
    pool = None
    if client is not None:
        pool = concurrent.futures.ThreadPoolExecutor(max_workers=2)
        futures["personal"] = pool.submit(
            _generate, client, _personal_prompt(style, name, tag_scores), PERSONAL
        )
        if cached is None:
            futures["cached"] = pool.submit(
                _generate, client, _cached_prompt(style, name), CACHED
            )

    results = _collect(futures, started) if futures else {}

    bodies = {}
    paths = {"personal": "stub", "cached": "stub"}
    if results.get("personal"):
        bodies.update(results["personal"])
        paths["personal"] = "llm"

    if cached is not None:
        bodies.update(cached)
        paths["cached"] = "cache"
    elif results.get("cached"):
        bodies.update(results["cached"])
        paths["cached"] = "llm"
        _write_cache(funnel_slug, result_style, results["cached"])

    content = _assemble(cfg, funnel_slug, result_style, name, bodies, paths)

    database.execute(
        INSERT_SQL, (purchase_id, json.dumps(content, separators=(",", ":")))
    )
    log.info(
        "report %s for purchase %s in %.1fs (%d sections, personal=%s cached=%s)",
        content["version"],
        purchase_id,
        time.monotonic() - started,
        len(content["sections"]),
        paths["personal"],
        paths["cached"],
    )

    leftover = {k: f for k, f in futures.items() if not f.done()}
    if leftover:
        job = {
            "purchase_id": purchase_id, "cfg": cfg, "funnel": funnel_slug,
            "style_id": result_style, "name": name, "bodies": bodies,
            "paths": paths, "content": content, "leftover": leftover,
            "pool": pool, "on_final": on_final,
        }
        threading.Thread(
            target=_finish_late, args=(job,),
            name="report-upgrade-%s" % purchase_id, daemon=True,
        ).start()
    else:
        if pool is not None:
            pool.shutdown(wait=False)
        _fire(on_final, content, purchase_id)

    return content


# --- PDF -------------------------------------------------------------------

PDF_CSS = """
@page {
  size: A4;
  margin: 22mm 18mm 20mm;
  @bottom-center {
    content: counter(page);
    font-family: %(sans)s;
    font-size: 9pt;
    color: #9aa0a6;
  }
}
@page :first { margin-top: 60mm; @bottom-center { content: ""; } }

body { font-family: %(sans)s; font-size: 11pt; line-height: 1.65; color: #3d424c; }

/* The cover owns its page. Without this the sections start under the title
   and the two collide with no space between them. */
.cover { break-after: page; }

.kicker {
  margin: 0 0 10mm;
  font-family: %(sans)s;
  font-size: 9pt;
  font-weight: 600;
  letter-spacing: 0.14em;
  text-transform: uppercase;
  color: #C05621;
}
.cover-lead { margin: 0 0 3mm; font-size: 11pt; color: #6b7280; }
.cover-name {
  margin: 0 0 6mm;
  font-family: %(serif)s;
  font-size: 34pt;
  font-weight: 600;
  line-height: 1.1;
  letter-spacing: -0.015em;
  color: #16181d;
}
.rule { width: 46mm; height: 1.2mm; background: #C05621; border-radius: 0.6mm; }
.cover-note { margin: 8mm 0 0; font-size: 10pt; color: #6b7280; }

.section { break-inside: avoid-page; margin: 0 0 11mm; }
.section-title {
  margin: 0 0 3mm;
  font-family: %(serif)s;
  font-size: 15pt;
  font-weight: 600;
  line-height: 1.25;
  letter-spacing: -0.01em;
  color: #16181d;
}
.section-title .bar {
  display: block;
  width: 12mm;
  height: 0.9mm;
  margin-top: 2.5mm;
  background: #C05621;
  border-radius: 0.5mm;
}
.section p { margin: 0; }
"""

# The webfonts ship with the site; if WeasyPrint cannot use the variable woff2
# on this host it falls through to the system serif and sans, which is a
# duller PDF but never a failed one.
PDF_FACES = """
@font-face { font-family: "Mazzin Sans"; src: url("fonts/inter-latin-var.woff2"); }
@font-face { font-family: "Mazzin Serif"; src: url("fonts/fraunces-latin-var.woff2"); }
"""

PDF_FONTS = {
    "sans": '"Mazzin Sans", "Helvetica Neue", Helvetica, Arial, sans-serif',
    "serif": '"Mazzin Serif", Georgia, "Times New Roman", serif',
}


def _pdf_html(content):
    name = html.escape(content.get("style_name") or "Your style")
    blocks = [
        '<section class="cover">',
        '<p class="kicker">Mazzin</p>',
        '<p class="cover-lead">Your kitchen style report</p>',
        '<h1 class="cover-name">%s</h1>' % name,
        '<div class="rule"></div>',
        '<p class="cover-note">Keep this — your report also stays available '
        "at the link you were sent back to after checkout.</p>",
        "</section>",
    ]
    for section in content.get("sections") or []:
        blocks.append(
            '<div class="section"><h2 class="section-title">%s'
            '<span class="bar"></span></h2><p>%s</p></div>'
            % (
                html.escape(section.get("title") or ""),
                html.escape(section.get("body") or ""),
            )
        )
    return (
        '<!doctype html><html lang="en"><head><meta charset="utf-8">'
        "<title>%s — Mazzin</title><style>%s%s</style></head><body>%s</body></html>"
        % (name, PDF_FACES, PDF_CSS % PDF_FONTS, "".join(blocks))
    )


def build_pdf(content):
    """Render the report to PDF bytes, or None if it cannot be rendered.

    WeasyPrint is imported here for the same reason the Anthropic SDK is: it
    must not be able to take the site down in the window between a deploy and
    a human running pip on the server.
    """
    try:
        from weasyprint import HTML
    except ImportError:
        log.error("weasyprint not installed — report PDFs are skipped")
        return None
    try:
        return HTML(
            string=_pdf_html(content), base_url=config.STATIC_DIR
        ).write_pdf()
    except Exception:
        log.exception("pdf render failed for %s", content.get("style_id"))
        return None


# --- email -----------------------------------------------------------------

RESEND_URL = "https://api.resend.com/emails"

EMAIL_HTML = """<div style="font-family:-apple-system,BlinkMacSystemFont,'Segoe UI',Roboto,Helvetica,Arial,sans-serif;font-size:16px;line-height:1.6;color:#3d424c;max-width:520px">
<p style="font-size:12px;font-weight:600;letter-spacing:.14em;text-transform:uppercase;color:#C05621;margin:0 0 18px">Mazzin</p>
<h1 style="font-family:Georgia,'Times New Roman',serif;font-size:26px;font-weight:600;line-height:1.2;color:#16181d;margin:0 0 14px">Your %(name)s report is ready</h1>
<p style="margin:0 0 14px">It is attached as a PDF, and it is always available at your result link.</p>
<p style="margin:0"><a href="%(link)s" style="color:#C05621">Open your report</a></p>
</div>"""


def _slug(text):
    return re.sub(r"[^a-z0-9]+", "-", (text or "report").lower()).strip("-") or "report"


def send_report_email(purchase_id, email, content, checkout_session=None):
    """Email the report as a PDF attachment. Returns True when Resend took it.

    Best effort by design and quiet about it: a purchase is not worth less
    because its receipt bounced. The address is never written to a log line —
    only the purchase id, which is enough to find it in the database.
    """
    if not email or not config.RESEND_API_KEY:
        return False

    pdf = build_pdf(content)
    if not pdf:
        # A mail promising an attachment it does not carry is worse than none.
        log.warning("no pdf for purchase %s — email skipped", purchase_id)
        return False

    try:
        import requests
    except ImportError:
        log.error("requests not installed — report emails are skipped")
        return False

    name = content.get("style_name") or "style"
    link = "%s/%s%s" % (
        config.BASE_URL,
        content.get("funnel") or "",
        ("?cs=" + checkout_session) if checkout_session else "",
    )
    payload = {
        "from": config.EMAIL_FROM,
        "to": [email],
        "subject": "Your %s style report" % name,
        "html": EMAIL_HTML % {"name": html.escape(name), "link": html.escape(link)},
        "attachments": [
            {
                "filename": "mazzin-%s-report.pdf" % _slug(name),
                "content": base64.b64encode(pdf).decode("ascii"),
            }
        ],
    }

    try:
        response = requests.post(
            RESEND_URL,
            json=payload,
            headers={
                "Authorization": "Bearer %s" % config.RESEND_API_KEY,
                "Content-Type": "application/json",
            },
            timeout=config.RESEND_TIMEOUT_S,
        )
    except Exception as exc:
        log.warning("report email failed for purchase %s: %s",
                    purchase_id, type(exc).__name__)
        return False

    if response.status_code >= 300:
        # Resend echoes the recipient in its error bodies — status only.
        log.warning("report email rejected for purchase %s: HTTP %s",
                    purchase_id, response.status_code)
        return False

    log.info("report emailed for purchase %s (%d KB pdf)",
             purchase_id, len(pdf) // 1024)
    return True
