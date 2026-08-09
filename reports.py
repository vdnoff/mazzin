"""Report generation.

Hybrid. Three sections depend on what the individual actually picked and are
generated per purchase from their tag scores; three are the same for everyone
who lands on a style and are generated once, then read from `style_sections`.

Every path here is best effort and every failure lands on the same floor: the
stub templates. A paying customer always gets a report, so a missing API key, a
slow model, a malformed answer and a dead network all degrade to placeholder
copy rather than to no delivery at all.

Model calls happen only on this path, which only the Stripe webhook reaches.
Nothing an unauthenticated request can touch spends money.

No report content and no tag scores are ever logged.
"""

import concurrent.futures
import json
import logging
import re
import time

import config
import database

log = logging.getLogger(__name__)

INSERT_SQL = "INSERT INTO reports (purchase_id, content) VALUES (%s, %s)"

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

# Body templates keyed by section id. Each renders 3-5 sentences and names the
# style so the stub reads as belonging to this specific result.
BODIES = {
    "palette": (
        "Your {name} palette leans on three colors that showed up again and "
        "again in the rooms you picked. The base carries the walls and the "
        "bulk of the cabinetry, so it stays quiet on purpose. The second "
        "color does the work on the island and the joinery. The accent is "
        "the one you use sparingly — hardware, a stool, a single wall. "
        "Placeholder copy: exact paint and finish codes arrive in Phase 2."
    ),
    "mistakes": (
        "Every {name} kitchen goes wrong in roughly the same five places. "
        "The expensive one is committing to a finish before seeing it under "
        "your own light. The common one is matching everything, which flattens "
        "the room instead of calming it. The third is buying the statement "
        "piece first and building around it. Placeholder copy: the full five, "
        "with fixes, arrive in Phase 2."
    ),
    "materials": (
        "{name} rooms live or die on the worktop, and yours has two sensible "
        "options and one that only looks right in photographs. Pair the "
        "counter with a splashback that shares its undertone rather than its "
        "color. Keep metals to two finishes at most across the whole room. "
        "Placeholder copy: the full material matrix arrives in Phase 2."
    ),
    "shopping": (
        "Three pieces carry a {name} kitchen, and the rest is supporting cast. "
        "Buy the lighting and the hardware first — they change the room "
        "immediately and cost the least to get right. Leave the seating until "
        "the cabinetry is in, because proportions shift once it lands. "
        "Placeholder copy: the itemized list arrives in Phase 2."
    ),
    "dna": (
        "Your answers read as {name}, but not purely — no one's ever do. "
        "There is a clear secondary influence sitting underneath your picks, "
        "showing up in the textures you kept choosing. The tension between "
        "the two is what will make the room look considered rather than "
        "copied. Placeholder copy: the full breakdown arrives in Phase 2."
    ),
    "splurge": (
        "In a {name} kitchen exactly one line item rewards overspending, and "
        "it is not the appliances. Everything touched daily deserves the "
        "budget; everything looked at deserves the cheaper version done well. "
        "The savings usually come from cabinetry carcasses, where nobody can "
        "tell the difference. Placeholder copy: the budget split arrives in "
        "Phase 2."
    ),
}

GENERIC_BODY = (
    "Placeholder copy for your {name} result. This section is generated as a "
    "stub in Phase 1b so the end-to-end purchase flow can be tested with real "
    "Stripe events. The structure, ordering and section titles are final. "
    "Only the body text is replaced in Phase 2."
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


def generate_report(purchase_id, funnel_slug, result_style, tag_scores=None):
    """Build and persist the report for a purchase. Returns the content dict.

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
    if pool is not None:
        # Never wait: an abandoned call is already past the budget, and its
        # thread dies on its own when the HTTP timeout fires.
        pool.shutdown(wait=False)

    bodies = {}
    personal_path = "stub"
    if results.get("personal"):
        bodies.update(results["personal"])
        personal_path = "llm"

    if cached is not None:
        bodies.update(cached)
        cached_path = "cache"
    elif results.get("cached"):
        bodies.update(results["cached"])
        cached_path = "llm"
        _write_cache(funnel_slug, result_style, results["cached"])
    else:
        cached_path = "stub"

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
    complete = personal_path != "stub" and cached_path != "stub"
    content = {
        "version": "llm-1" if complete else "stub-1",
        "funnel": funnel_slug,
        "style_id": result_style,
        "style_name": name,
        "sections": sections,
    }

    database.execute(
        INSERT_SQL, (purchase_id, json.dumps(content, separators=(",", ":")))
    )
    log.info(
        "report %s for purchase %s in %.1fs (%d sections, personal=%s cached=%s)",
        content["version"],
        purchase_id,
        time.monotonic() - started,
        len(sections),
        personal_path,
        cached_path,
    )
    return content
