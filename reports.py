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

MAX_TOKENS = 2000          # the cached group, which is three sections at once
SECTION_TOKENS = 700       # one personalised section on its own
TEMPERATURE = 0.7

# The offline warmer's own limits. Nothing is waiting on it, so it is patient
# where the request path is not: a long per-call timeout and real retries in
# place of the request path's one.
WARM_TIMEOUT_S = 180.0
WARM_RETRIES = 3

# A 90-word section is ~500 characters. This only has to separate a real
# section from an empty string or a one-line apology.
MIN_BODY_CHARS = 200

# Report content schema. "-2" carries typed section data; "-1" was flat prose
# and is still rendered by both the client and the PDF, because rows written
# before this shipped are still being served.
SCHEMA = "2"

# Cached per-style rows are tagged with the schema that produced them. A row
# from an older schema is a cache miss, not a broken render.
CACHE_SCHEMA = SCHEMA

# A report that exists but is still filling up. The client renders the sections
# it has and keeps polling; the suffix is what tells it to.
PARTIAL_SUFFIX = "-partial"

HEX_RE = re.compile(r"^#?([0-9a-fA-F]{3}|[0-9a-fA-F]{6})$")
VERDICTS = ("works", "avoid")


def _text(value, least=2, most=600):
    """A usable string, or None. Model output is never trusted by length alone."""
    if not isinstance(value, str):
        return None
    value = value.strip()
    return value if least <= len(value) <= most else None


def _hex(value):
    """`#rrggbb`, or None.

    This lands in a CSS background and in the PDF, so nothing but six hex
    digits ever gets through — a colour is the one field the model supplies
    that becomes markup rather than text.
    """
    if not isinstance(value, str):
        return None
    match = HEX_RE.match(value.strip())
    if not match:
        return None
    digits = match.group(1).lower()
    if len(digits) == 3:
        digits = "".join(c * 2 for c in digits)
    return "#" + digits


def _items(value, low, high):
    return value if isinstance(value, list) and low <= len(value) <= high else None


def _v_palette(d):
    colors = _items(d.get("colors"), 3, 4)
    intro = _text(d.get("intro"), 20)
    rule = _text(d.get("closing_rule"), 15)
    if not (colors and intro and rule):
        return None
    out = []
    for c in colors:
        if not isinstance(c, dict):
            return None
        row = {
            "name": _text(c.get("name"), 2, 60),
            "hex": _hex(c.get("hex")),
            "role": _text(c.get("role"), 2, 80),
            "finish": _text(c.get("finish"), 2, 80),
            "where": _text(c.get("where"), 2, 200),
        }
        if not all(row.values()):
            return None
        out.append(row)
    return {"intro": intro, "colors": out, "closing_rule": rule}


def _v_mistakes(d):
    items = _items(d.get("items"), 4, 6)
    if not items:
        return None
    out = []
    for m in items:
        if not isinstance(m, dict):
            return None
        row = {
            "title": _text(m.get("title"), 3, 90),
            "body": _text(m.get("body"), 30),
            "fix": _text(m.get("fix"), 10, 300),
        }
        if not all(row.values()):
            return None
        out.append(row)
    return {"items": out}


def _v_materials(d):
    pairs = _items(d.get("pairs"), 3, 4)
    intro = _text(d.get("intro"), 20)
    rule = _text(d.get("rule"), 15)
    if not (pairs and intro and rule):
        return None
    out = []
    for p in pairs:
        if not isinstance(p, dict):
            return None
        verdict = p.get("verdict")
        verdict = verdict.strip().lower() if isinstance(verdict, str) else None
        row = {
            "combo": _text(p.get("combo"), 3, 90),
            "verdict": verdict if verdict in VERDICTS else None,
            "why": _text(p.get("why"), 15),
        }
        if not all(row.values()):
            return None
        out.append(row)
    # A page of nothing but "works" is a list, not a judgement.
    if not any(p["verdict"] == "avoid" for p in out):
        return None
    return {"intro": intro, "pairs": out, "rule": rule}


def _v_shopping(d):
    items = _items(d.get("items"), 5, 7)
    skip = _items(d.get("skip"), 1, 2)
    if not (items and skip):
        return None
    out = []
    for i in items:
        if not isinstance(i, dict):
            return None
        row = {"name": _text(i.get("name"), 2, 90),
               "priority_note": _text(i.get("priority_note"), 10, 300)}
        if not all(row.values()):
            return None
        out.append(row)
    skips = []
    for s in skip:
        if not isinstance(s, dict):
            return None
        row = {"name": _text(s.get("name"), 2, 90), "why": _text(s.get("why"), 10, 300)}
        if not all(row.values()):
            return None
        skips.append(row)
    return {"items": out, "skip": skips}


def _v_dna(d):
    narrative = d.get("narrative")
    if isinstance(narrative, str):                 # tolerate one blob
        narrative = [p.strip() for p in narrative.split("\n\n") if p.strip()]
    narrative = _items(narrative, 1, 3)
    if not narrative or not all(_text(p, 40) for p in narrative):
        return None
    implications = _items(d.get("implications"), 2, 2)
    if not implications or not all(_text(p, 10, 300) for p in implications):
        return None
    return {"narrative": [p.strip() for p in narrative],
            "implications": [p.strip() for p in implications]}


def _v_splurge(d):
    splurge = d.get("splurge")
    saves = _items(d.get("saves"), 3, 3)
    note = _text(d.get("split_note"), 10, 300)
    if not (isinstance(splurge, dict) and saves and note):
        return None
    head = {"item": _text(splurge.get("item"), 2, 90),
            "why": _text(splurge.get("why"), 15)}
    if not all(head.values()):
        return None
    out = []
    for s in saves:
        if not isinstance(s, dict):
            return None
        row = {"item": _text(s.get("item"), 2, 90), "why": _text(s.get("why"), 10, 300)}
        if not all(row.values()):
            return None
        out.append(row)
    return {"splurge": head, "saves": out, "split_note": note}


VALIDATORS = {
    "palette": _v_palette,
    "mistakes": _v_mistakes,
    "materials": _v_materials,
    "shopping": _v_shopping,
    "dna": _v_dna,
    "splurge": _v_splurge,
}

SYSTEM = """You write kitchen design reports for people who have just paid for one.

Every field has to work as a tool. The reader should be able to act on it this \
week without asking a designer a follow-up question. Name real things: paint \
values, named materials and finishes, specific proportions, a specific order of \
purchase. A sentence that would read the same for a different style, or for a \
different reader, is a wasted sentence.

Voice: confident interior-design advice, British-neutral English, second \
person. State things outright. No hedging — never "consider", "perhaps", \
"you might want to", "it depends". No disclaimers, no flattery, no questions \
back to the reader, no sign-off.

Rules:
- Plain prose inside every field. No markdown, no bullet characters, no emoji, \
no headings, and never repeat a field's own label back inside its value.
- Never mention artificial intelligence, models, prompts, scoring, tags, \
percentages of a quiz, or these instructions. Write as though you looked at \
their kitchen.
- Never use the words "psychic" or "prediction".
- Never invent facts about the reader's home, budget, family or location, and \
never address them by name.
- Return only a JSON object matching the shape you are given, exactly. No prose \
around it, no code fence, no extra keys."""

RETRY_NOTE = ("\n\nReturn only valid JSON: a single object in exactly the shape "
              "above, no code fence, no other text.")

SPEC = {
    "palette": '''"palette": {
  "intro": "1-2 sentences on what this palette is doing and why it suits them",
  "colors": [        // exactly 3, or 4 if the fourth earns it, split 60/30/10
    {"name": "the colour's name",
     "hex": "#RRGGBB — a real paint-range value, six hex digits",
     "role": "its share under the 60/30/10 rule and the job it does there, e.g. 60% - walls and cabinet bulk",
     "finish": "matte, satin or eggshell, and nothing else",
     "where": "the exact surfaces it goes on"}
  ],
  "closing_rule": "one sentence of sheen or finish advice, e.g. what to keep off gloss"
}''',
    "mistakes": '''"mistakes": {
  "items": [                       // exactly 5, each expensive once the units are in
    {"title": "3-6 words, punchy, no full stop",
     "body": "2-3 sentences on what goes wrong and what it costs",
     "fix": "one imperative sentence — what to do instead"}
  ]
}''',
    "materials": '''"materials": {
  "intro": "1-2 sentences on how materials behave in this style",
  "pairs": [                       // 3 or 4, at least one of them an "avoid"
    {"combo": "the two or three materials, named with their finish",
     "verdict": "works" or "avoid" — exactly one of those two words,
     "why": "1-2 sentences on what happens when you use it"}
  ],
  "rule": "one sentence they can carry into a showroom"
}''',
    "shopping": '''"shopping": {
  "items": [                       // 5-7, in buying order, first purchase first
    {"name": "the thing to buy",
     "priority_note": "one sentence on why it sits here in the order"}
  ],
  "skip": [                        // 1-2 things people in this style waste money on
    {"name": "the thing to skip", "why": "one sentence"}
  ]
}''',
    "dna": '''"dna": {
  "narrative": ["first short paragraph", "second short paragraph"],
  "implications": ["one thing to do differently", "a second thing to do differently"]
}''',
    "splurge": '''"splurge": {
  "splurge": {"item": "the one thing to overspend on", "why": "1-2 sentences"},
  "saves": [                       // exactly 3
    {"item": "what to buy cheaply", "why": "one sentence on why nobody notices"}
  ],
  "split_note": "a rough budget split across the two, in a sentence"
}''',
}

# Hand-written fallbacks, in the same shape the model returns. These are what a
# paying customer reads on the service's worst day, so they carry real advice
# and never mention being a fallback.
STUBS = {
    "palette": {
        "intro": "A {name} palette works on three colours and a strict split: "
                 "one quiet colour doing the bulk, one carrying the joinery, "
                 "and one appearing rarely enough to still register.",
        "colors": [
            {"name": "Warm Chalk", "hex": "#EDE8E0",
             "role": "60% - walls and cabinet bulk",
             "finish": "matte",
             "where": "Walls, ceiling and the run of tall units."},
            {"name": "Deep Clay", "hex": "#8B6F4E",
             "role": "30% - island and lower joinery",
             "finish": "eggshell",
             "where": "The island, the lower doors and any open shelving."},
            {"name": "Burnt Ochre", "hex": "#A45A34",
             "role": "10% - hardware and one accent",
             "finish": "satin",
             "where": "Handles, a single stool, or the inside of one cabinet."},
        ],
        "closing_rule": "Keep the bulk matte and let the accent be the only "
                        "surface in the room with any sheen — gloss on the "
                        "large runs will show every fingerprint by month two.",
    },
    "mistakes": {
        "items": [
            {"title": "Choosing a finish under showroom light",
             "body": "Showroom lighting is colour-corrected and twice as "
                     "bright as a domestic kitchen. A finish chosen there "
                     "reads several shades cooler once it is on your wall, "
                     "and repainting fitted units is not a weekend job.",
             "fix": "Order samples and live with them for a full week before "
                    "committing."},
            {"title": "Matching everything",
             "body": "When every timber, metal and stone agrees, the room "
                     "flattens instead of calming. A {name} kitchen needs one "
                     "element that is visibly older, darker or rougher than "
                     "the rest to give the eye somewhere to land.",
             "fix": "Break the set with one deliberately mismatched piece."},
            {"title": "Buying the statement piece first",
             "body": "A light fitting or a range cooker bought early becomes a "
                     "constraint everything else has to work around, usually "
                     "at the cost of the layout.",
             "fix": "Buy the statement piece last, once the room can tell you "
                    "what it needs."},
            {"title": "Solving storage with more cabinetry",
             "body": "The instinct when counters fill up is to add units. That "
                     "buys a month and costs the proportions of the room "
                     "permanently, because the wall runs stop breathing.",
             "fix": "Empty one drawer and keep it empty rather than adding a "
                    "cupboard."},
            {"title": "Skimping on the worktop edge",
             "body": "The edge profile is the detail your hands and hips meet "
                     "every day, and a cheap one chips within two winters. "
                     "Replacing it means replacing the whole surface.",
             "fix": "Spend the upgrade on the edge detail, not the surface "
                    "area."},
        ],
    },
    "materials": {
        "intro": "A {name} room lives or dies on how its surfaces behave "
                 "together under warm evening light, not on how they "
                 "photograph individually.",
        "pairs": [
            {"combo": "Honed stone worktop with a matching honed splashback",
             "verdict": "works",
             "why": "Sharing the finish rather than the colour lets the two "
                    "read as one surface without looking like a slab kit."},
            {"combo": "Timber joinery with one cold element between it and stone",
             "verdict": "works",
             "why": "Without something cold in between, timber and stone turn "
                    "muddy where they meet."},
            {"combo": "Polished stone with high-gloss cabinetry",
             "verdict": "avoid",
             "why": "Two reflective surfaces facing each other double every "
                    "smear and leave nowhere for the eye to rest."},
        ],
        "rule": "Keep metals to two finishes across the whole room, and make "
                "the one you touch daily the better of the two.",
    },
    "shopping": {
        "items": [
            {"name": "Lighting",
             "priority_note": "It changes the room more than anything else and "
                              "costs the least to get right."},
            {"name": "Hardware",
             "priority_note": "Handles set the register of the whole kitchen "
                              "and are cheap to change your mind about."},
            {"name": "The tap",
             "priority_note": "It is the one moving object in the room, so it "
                              "carries more attention than its price suggests."},
            {"name": "Worktop",
             "priority_note": "Order it once the cabinetry is set, so the edge "
                              "detail can respond to the actual runs."},
            {"name": "Splashback",
             "priority_note": "It has to answer the worktop, so it follows it "
                              "rather than leading."},
            {"name": "Seating",
             "priority_note": "Leave it until the room is in — proportions "
                              "shift once the units land."},
        ],
        "skip": [
            {"name": "The matching accessory set",
             "why": "It is the fastest way to make a considered room look "
                    "bought all at once."},
        ],
    },
    "dna": {
        "narrative": [
            "Your answers read as {name}, but not purely — no one's ever do. "
            "There is a clear secondary influence sitting underneath your "
            "picks, showing up in the textures you kept choosing rather than "
            "in the shapes.",
            "The tension between the two is what will make the room look "
            "considered rather than copied. Rooms that commit entirely to one "
            "reference always read as a showroom; the ones that hold two in "
            "balance read as somebody's.",
        ],
        "implications": [
            "Let the dominant style set the layout and the secondary one set "
            "the materials.",
            "When a decision is close, take the option that belongs to the "
            "quieter of your two influences.",
        ],
    },
    "splurge": {
        "splurge": {
            "item": "The things your hands meet daily",
            "why": "Handles, the tap and the worktop edge are touched a dozen "
                   "times a day, and cheap versions announce themselves "
                   "through the hand long before the eye.",
        },
        "saves": [
            {"item": "Cabinet carcasses",
             "why": "Once the doors are on, nobody can tell what is behind "
                    "them."},
            {"item": "Interior fittings",
             "why": "Drawer organisers cost a fraction from a generic supplier "
                    "and perform identically."},
            {"item": "Decorative accessories",
             "why": "They are the easiest thing to upgrade later and the "
                    "easiest to overspend on now."},
        ],
        "split_note": "Roughly seventy per cent of the budget into what you "
                      "touch, thirty into what you only look at.",
    },
}


def _fill(value, name):
    """Template {name} through a nested stub structure."""
    if isinstance(value, str):
        return value.format(name=name)
    if isinstance(value, list):
        return [_fill(v, name) for v in value]
    if isinstance(value, dict):
        return dict((k, _fill(v, name)) for k, v in value.items())
    return value


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
    return "\n\n".join(
        ["Return exactly this JSON object. Every key is required."]
        + [SPEC[section_id] for section_id in ids]
        + ["Wrap those in one object: {%s}."
           % ", ".join('"%s": {...}' % s for s in ids)]
    )


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


def _leaning_block(tag_scores):
    if not tag_scores:
        return ("Write for someone typical of this style; you have nothing "
                "specific about this individual.")
    ranked = sorted(tag_scores.items(), key=lambda kv: (-kv[1], kv[0]))
    return (
        "What they were drawn to, strongest pull first: %s. Let this bend the "
        "advice — a strong pull toward dark or warm should change which colours "
        "and materials you name, not just how you describe them. Refer to what "
        "they kept choosing, never to the numbers."
        % ", ".join("%s %d" % (tag, n) for tag, n in ranked if n > 0)
    )


def _choice_lines(cfg, choices):
    """What they actually looked at, in the order they chose it.

    Tags say a choice was `warm`; this says it was a deep green cabinet next
    to aged brass. It is the difference between a palette assembled from
    categories and one assembled from things this person pointed at.
    """
    if not choices:
        return []
    by_id = {}
    for step in (cfg.get("swipe") or {}).get("steps") or []:
        for item in step.get("images") or []:
            by_id[item.get("id")] = (step, item)

    lines = []
    for n, image_id in enumerate(choices, 1):
        found = by_id.get(image_id)
        if not found:
            continue
        step, item = found
        colours = ", ".join(
            "%s %s on the %s" % (c.get("name"), c.get("hex"), c.get("element"))
            for c in (item.get("colors") or [])
            if c.get("name") and c.get("hex") and c.get("element")
        )
        lines.append("%d. %s — chose \"%s\"%s"
                     % (n, step.get("question") or step.get("id"),
                        item.get("label") or image_id,
                        (": " + colours) if colours else ""))
    return lines


def _choice_block(cfg, choices):
    """The choice sequence as context for a section that is not the palette."""
    lines = _choice_lines(cfg, choices)
    if not lines:
        return None
    return ("The nine choices they made, in order, with what was on screen:\n"
            + "\n".join(lines)
            + "\nYou may refer to any of these directly — \"the marble you "
              "picked\", \"the brass you kept coming back to\" — but only where "
              "it earns its place in the advice.")


def _palette_block(cfg, choices):
    """The palette instruction, when we know what they actually chose."""
    lines = _choice_lines(cfg, choices)
    if not lines:
        return None
    return (
        "This person's own choices, in order, with the colours that were in "
        "front of them:\n" + "\n".join(lines) + "\n\n"
        "Build the palette out of THESE colours. Rules:\n"
        "- A hue they chose more than once is what the 60% or the 30% should "
        "be. Recurring beats striking: if warm oak turned up in four of nine "
        "choices, oak carries the room whatever else appealed.\n"
        "- The 10% accent is the strongest colour they chose that did NOT "
        "recur — the one they picked once and decisively.\n"
        "- Use their hex values, or a shade within a few points of one, rather "
        "than inventing a colour they never saw. You may correct a value that "
        "was obviously lit rather than painted — a cream tile read under lamp "
        "light is not really orange.\n"
        "- Every colour's `where` must say which choice it came from, in those "
        "words: \"the deep green you chose for your cabinets\", \"the marble "
        "you picked over warm wood\". Name the choice, never the step number "
        "and never a tag.\n"
        "- If their choices genuinely conflict, say so in the closing rule and "
        "resolve it — do not average them into mud."
    )


def _section_prompt(style, name, tag_scores, section_id, cfg=None, choices=None):
    """One personalised section on its own.

    Each section is its own call now, so each carries the whole style and
    leaning context. That is a few hundred repeated tokens per report against
    three sections arriving in the time one used to take.

    When the choice sequence survived checkout it goes in too: the palette is
    built from the colours they actually tapped, and the other two sections get
    the sequence as something they may point at. Without it every section falls
    back to the tag-based behaviour unchanged.
    """
    parts = [_style_block(style, name)]
    parts.append(_leaning_block(tag_scores))

    extra = None
    if cfg is not None and choices:
        extra = (_palette_block(cfg, choices) if section_id == "palette"
                 else _choice_block(cfg, choices))
    if extra:
        parts.append(extra)

    parts.append(_sections_block((section_id,)))
    return "\n\n".join(parts)


def _cached_prompt(style, name, ids=CACHED):
    """The per-style sections. `ids` narrows it to a subset for the warmer."""
    return "\n\n".join(
        [
            _style_block(style, name),
            "Write for anyone with this style. Nothing here is specific to one "
            "person.",
            _sections_block(ids),
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


def _warm_api():
    """A client for offline warming, or None when generation is switched off.

    Separate from the request-path client because the trade-off inverts. A
    purchase cannot wait three minutes for a section, so `_api` gives up early
    and stubs; a warmer run has nothing else to do and would far rather wait
    than leave a style cold for the next buyer. Not cached — this is called
    once per console run.
    """
    if not config.ANTHROPIC_API_KEY:
        return None
    try:
        import anthropic
    except ImportError:
        log.error("anthropic SDK not installed — cannot warm the cache")
        return None
    return anthropic.Anthropic(
        api_key=config.ANTHROPIC_API_KEY,
        timeout=WARM_TIMEOUT_S,
        max_retries=WARM_RETRIES,
    )


# --- the in-flight limit ---------------------------------------------------

# The cap belongs here rather than on the thread pool alone, because a retry
# is a second call from a thread that already has a worker slot. Rebuilt only
# when the configured size changes, which outside tests is never.
_gate = None
_gate_size = 0
_gate_lock = threading.Lock()


def _limiter():
    global _gate, _gate_size
    size = max(1, int(config.LLM_MAX_CONCURRENCY or 1))
    with _gate_lock:
        if _gate is None or _gate_size != size:
            _gate = threading.BoundedSemaphore(size)
            _gate_size = size
        return _gate


def _timeout_class():
    """The SDK's timeout error, or None when the SDK is not installed.

    Resolved lazily for the same reason the client is: the package may be
    missing between a deploy and a human running pip.
    """
    try:
        import anthropic
    except ImportError:
        return None
    return getattr(anthropic, "APITimeoutError", None)


FENCE_RE = re.compile(r"^\s*```(?:json)?|```\s*$", re.IGNORECASE)


def _parse(text, want):
    """The model's JSON as {section_id: data}, or None if it is unusable.

    Every section is validated against its own shape rather than checked for
    length. A section that is the wrong shape fails the whole group, which
    sends it to the retry and then to the stub — a half-built swatch list on a
    paid report is worse than a hand-written one.
    """
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
        if not isinstance(value, dict):
            return None
        clean = VALIDATORS[key](value)
        if clean is None:
            return None
        out[key] = clean
    return out


def _ask(client, prompt, max_tokens):
    gate = _limiter()
    gate.acquire()
    try:
        message = client.messages.create(
            model=config.ANTHROPIC_MODEL,
            max_tokens=max_tokens,
            temperature=TEMPERATURE,
            system=SYSTEM,
            messages=[{"role": "user", "content": prompt}],
        )
    finally:
        gate.release()
    return "".join(
        block.text for block in message.content if block.type == "text"
    )


def _attempt(client, prompt, max_tokens, label):
    """One prompt, retried once if it times out.

    A timeout is the one failure worth repeating immediately: it means the
    connection never produced anything, so there is no half-answer to salvage
    and nothing was spent on output. Every other error goes straight up — a
    rejection or a bad request will fail the same way twice.
    """
    timeout = _timeout_class()
    try:
        return _ask(client, prompt, max_tokens)
    except Exception as exc:
        if timeout is None or not isinstance(exc, timeout):
            raise
        log.warning("section %s timed out — retrying once", label)
    return _ask(client, prompt, max_tokens)


def _generate(client, prompt, want, max_tokens=MAX_TOKENS):
    """One section group. Returns {section_id: body}, or None.

    A single personalised section needs a fraction of the room a six-section
    call did, so the caller sizes the budget to what it asked for.
    """
    label = "+".join(want)
    parsed = _parse(_attempt(client, prompt, max_tokens, label), want)
    if parsed is None:
        parsed = _parse(_attempt(client, prompt + RETRY_NOTE, max_tokens, label),
                        want)
    return parsed


# --- cache -----------------------------------------------------------------


def _cache_state(funnel_slug, result_style):
    """(usable sections, stale row count) for one style.

    Section-by-section rather than all-or-nothing, because the warmer needs to
    know which three are missing and the purchase path only needs to know
    whether all three are there.
    """
    try:
        rows = database.query_all(SELECT_SECTIONS_SQL, (funnel_slug, result_style))
    except Exception:
        log.exception("style section read failed for %s/%s", funnel_slug, result_style)
        return None, 0

    out = {}
    stale = 0
    for row in rows or []:
        content = row.get("content")
        if isinstance(content, (str, bytes)):
            try:
                content = json.loads(content)
            except ValueError:
                continue
        if not isinstance(content, dict):
            continue
        if content.get("v") != CACHE_SCHEMA:
            stale += 1
            continue
        section_id = row.get("section_id")
        data = content.get("data")
        if section_id in VALIDATORS and isinstance(data, dict):
            clean = VALIDATORS[section_id](data)
            if clean is not None:
                out[section_id] = clean
    return out, stale


def _read_cache(funnel_slug, result_style):
    """Cached per-style sections, or None unless the whole set is current.

    A row written under an older schema is a miss, not a broken render: it is
    regenerated and overwritten on the next purchase of that style.
    """
    out, stale = _cache_state(funnel_slug, result_style)
    if out is None:
        return None

    if stale:
        # Loud, because scripts/warm_cache.py is supposed to have left every
        # style current. A stale row reaching a paying customer means the
        # schema moved and nobody re-warmed it.
        log.warning("style sections for %s/%s are schema %s — %d stale rows "
                    "regenerating on the purchase path; run warm_cache.py",
                    funnel_slug, result_style, CACHE_SCHEMA, stale)

    if all(section_id in out for section_id in CACHED):
        return dict((section_id, out[section_id]) for section_id in CACHED)
    return None


def _write_cache(funnel_slug, result_style, sections):
    for section_id, data in sections.items():
        try:
            database.execute(
                UPSERT_SECTION_SQL,
                (
                    funnel_slug,
                    result_style,
                    section_id,
                    json.dumps({"v": CACHE_SCHEMA, "data": data},
                               separators=(",", ":")),
                ),
            )
        except Exception:
            # A cache miss next time is cheap; a failed purchase is not.
            log.exception("style section write failed for %s/%s/%s",
                          funnel_slug, result_style, section_id)


# --- entry point -----------------------------------------------------------


def _is_schema2(version):
    """True for `llm-2`, `stub-2` and the partial marker they grow out of."""
    version = version or ""
    return version.endswith("-" + SCHEMA) or version.endswith(PARTIAL_SUFFIX)


def _assemble(cfg, funnel_slug, result_style, name, built, paths, complete):
    """The stored content for whatever has resolved so far.

    A section that has not resolved is simply absent — the client renders what
    exists and keeps polling. Once `complete`, every section is present, either
    generated or stubbed, and the version says which.
    """
    sections = []
    for section in cfg.get("report", {}).get("sections", []):
        if section.get("enabled") is False:
            continue
        section_id = section.get("id")
        if section_id not in built:
            continue
        sections.append({
            "id": section_id,
            "title": section.get("title"),
            "data": built[section_id],
        })

    if not complete:
        version = "llm-" + SCHEMA + PARTIAL_SUFFIX
    else:
        # "llm" means every section is real copy; a report carrying any stub
        # stays "stub" so regeneration tooling can find it.
        clean = all(paths.get(s["id"]) != "stub" for s in sections)
        version = ("llm-" if clean else "stub-") + SCHEMA

    return {
        "version": version,
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


# --- the background runner -------------------------------------------------


def _publish(job, complete=False):
    """Write what has resolved so far over the row that already exists."""
    content = _assemble(job["cfg"], job["funnel"], job["style_id"], job["name"],
                        job["built"], job["paths"], complete)
    job["content"] = content
    try:
        database.execute(
            UPDATE_REPORT_SQL,
            (json.dumps(content, separators=(",", ":")), job["purchase_id"]),
        )
    except Exception:
        log.exception("report update failed for purchase %s", job["purchase_id"])
    return content


def _absorb(job, task, result):
    """Fold one finished task into the job, or stub the sections it owed."""
    ids = task["ids"]
    if result:
        job["built"].update(result)
        for section_id in ids:
            job["paths"][section_id] = "llm"
        if task["cache"]:
            _write_cache(job["funnel"], job["style_id"], result)
        return True

    for section_id in ids:
        if section_id in job["built"]:
            continue                      # already have it (a cache hit)
        stub = STUBS.get(section_id)
        job["built"][section_id] = _fill(stub, job["name"]) if stub else None
        job["paths"][section_id] = "stub"
    return False


def _collect(job, task, future):
    """Absorb one already-finished task. A failed call costs only its own ids."""
    try:
        result = future.result()
    except Exception as exc:
        log.warning("section %s failed for purchase %s: %s",
                    "+".join(task["ids"]), job["purchase_id"], type(exc).__name__)
        result = None
    return _absorb(job, task, result)


def _drain(job, pending, ceiling):
    """Absorb tasks as they finish until `pending` empties or time runs out.

    Yields once per batch that lands so the caller can publish. Waiting on
    whichever call finishes first — rather than in submission order — is what
    keeps a slow section from sitting on a finished one.
    """
    while pending:
        remaining = ceiling - time.monotonic()
        if remaining <= 0:
            break
        done, _ = concurrent.futures.wait(
            list(pending), timeout=remaining,
            return_when=concurrent.futures.FIRST_COMPLETED)
        if not done:
            break
        landed = False
        for future in done:
            if _collect(job, pending.pop(future), future):
                landed = True
        yield landed


def _run(job):
    """Generate every section, publishing each one the moment it lands.

    The webhook is already gone by the time this starts. Sections are written
    over the row as they resolve, so a client polling sees the palette while
    the rest is still being written, and one slow call no longer holds five
    finished sections hostage.
    """
    started = time.monotonic()
    pending = dict((task["future"], task) for task in job["tasks"])

    for _ in _drain(job, pending, started + config.REPORT_BUDGET_S):
        _publish(job)

    # Anything still running has missed its budget. Stub what it owed so the
    # buyer has a whole report now, and keep the call alive in case it lands.
    late = bool(pending)
    if late:
        log.warning("%s missed the budget for purchase %s",
                    " ".join(sorted("+".join(t["ids"]) for t in pending.values())),
                    job["purchase_id"])
        for task in list(pending.values()):
            _absorb(job, task, None)
    content = _publish(job, complete=True)
    log.info("report %s for purchase %s in %.1fs (%d sections, %s)",
             content["version"], job["purchase_id"], time.monotonic() - started,
             len(content["sections"]),
             " ".join("%s=%s" % kv for kv in sorted(job["paths"].items())))

    # Late arrivals still upgrade the row in place — they were paid for.
    if late:
        upgraded = any(list(_drain(
            job, pending, time.monotonic() + config.REPORT_UPGRADE_MAX_S)))
        if upgraded:
            content = _publish(job, complete=True)
            log.info("late llm upgrade for purchase %s (now %s)",
                     job["purchase_id"], content["version"])

    if job["pool"] is not None:
        job["pool"].shutdown(wait=False)
    _fire(job["on_final"], content, job["purchase_id"])


def _personal_order(cfg):
    """The personalised sections, in the order the report displays them."""
    ordered = [s.get("id") for s in cfg.get("report", {}).get("sections", [])
               if s.get("id") in PERSONAL]
    # A config that has dropped or renamed one still has to generate the rest.
    return ordered + [i for i in PERSONAL if i not in ordered]


def start_report(purchase_id, funnel_slug, result_style, tag_scores=None,
                 on_final=None, choices=None):
    """Persist an empty report and generate into it in the background.

    Returns as soon as the row exists. Nothing here waits on a model, so the
    webhook's response time no longer depends on generation at all — the row
    is the handshake, and /api/report serves it while it fills up.

    `on_final` is called exactly once with the finished content, which is
    where anything that must reflect the whole report — the emailed PDF —
    belongs.

    `choices` is the sequence of image ids they tapped, already validated
    against this funnel. It is what lets the palette be built from colours
    they actually chose; without it every section falls back to tags alone.

    Raises if the funnel config is missing or the INSERT fails; the webhook
    treats that as non-fatal.
    """
    cfg = config.load_funnel(funnel_slug)
    style = _style(cfg, result_style)
    name = _style_name(cfg, result_style)

    cached = _read_cache(funnel_slug, result_style)
    client = _api() if style else None

    built = {}
    paths = {}
    if cached:
        built.update(cached)
        for section_id in CACHED:
            paths[section_id] = "cache"

    job = {
        "purchase_id": purchase_id, "cfg": cfg, "funnel": funnel_slug,
        "style_id": result_style, "name": name, "built": built, "paths": paths,
        "on_final": on_final, "content": None,
    }

    tasks = []
    pool = None
    if client is not None:
        # Fewer workers than tasks, on purpose: the pool size is the priority
        # mechanism. Submission order decides what runs first, so generating in
        # the funnel's own section order fills the report from the top down —
        # the palette, which the opening is built around, is never waiting
        # behind a section the reader has not scrolled to yet. The cached group
        # goes last because it is the one nobody is looking at first.
        pool = concurrent.futures.ThreadPoolExecutor(
            max_workers=max(1, int(config.LLM_MAX_CONCURRENCY or 1)))
        for section_id in _personal_order(cfg):
            tasks.append({
                "ids": (section_id,), "cache": False,
                "future": pool.submit(
                    _generate, client,
                    _section_prompt(style, name, tag_scores, section_id,
                                    cfg, choices),
                    (section_id,), SECTION_TOKENS),
            })
        if cached is None:
            tasks.append({
                "ids": CACHED, "cache": True,
                "future": pool.submit(_generate, client,
                                      _cached_prompt(style, name), CACHED,
                                      MAX_TOKENS),
            })
    job["tasks"] = tasks
    job["pool"] = pool

    if not tasks:
        # No model, no style, no key: the whole thing is stubs, and there is
        # nothing to wait for.
        for section_id in [s.get("id") for s in cfg.get("report", {}).get("sections", [])]:
            if section_id not in built:
                stub = STUBS.get(section_id)
                built[section_id] = _fill(stub, name) if stub else None
                paths[section_id] = "stub"
        content = _assemble(cfg, funnel_slug, result_style, name, built, paths, True)
        database.execute(
            INSERT_SQL, (purchase_id, json.dumps(content, separators=(",", ":")))
        )
        log.info("report %s for purchase %s (no generation)",
                 content["version"], purchase_id)
        _fire(on_final, content, purchase_id)
        return content

    opening = _assemble(cfg, funnel_slug, result_style, name, built, paths, False)
    database.execute(
        INSERT_SQL, (purchase_id, json.dumps(opening, separators=(",", ":")))
    )
    job["content"] = opening
    # Counted before the thread starts: it writes into this same dict as
    # sections land, and this number is how you tell whether the warmer is
    # doing its job.
    from_cache = len(built)
    threading.Thread(target=_run, args=(job,), daemon=True,
                     name="report-%s" % purchase_id).start()
    log.info("report started for purchase %s (%d tasks, %d cached, %d choices)",
             purchase_id, len(tasks), from_cache, len(choices or []))
    return opening


# --- offline cache warmer --------------------------------------------------


def warm_style_cache(funnel_slug, style_id, client=None):
    """Fill the per-style section cache for one style. Console use only.

    The three cached sections are the same for everyone with a given style, so
    generating them during a purchase is work the buyer should never have paid
    for in latency. Run this after a deploy that moves CACHE_SCHEMA and the
    purchase path drops to the three personalised calls it actually needs.

    Nothing here touches REPORT_BUDGET_S, the thread pool or the report row: it
    is not on any request path, so it can take as long as it takes. Calls are
    made one at a time, per missing section, so one unusable answer costs its
    own section and not the other two — and a style that is half-cached is
    repaired rather than regenerated.

    Returns a dict: status is "cached" when there was nothing to do, "warmed"
    when every missing section landed, "partial" when some did, "failed" when
    none did, and "skipped" when there is no client or no such style.
    """
    def result(status, **extra):
        out = {"funnel": funnel_slug, "style": style_id, "status": status,
               "cached": [], "warmed": [], "failed": [], "stale": 0}
        out.update(extra)
        return out

    try:
        cfg = config.load_funnel(funnel_slug)
    except KeyError:
        return result("skipped", detail="no such funnel")

    style = _style(cfg, style_id)
    if not style:
        return result("skipped", detail="no such style")
    name = _style_name(cfg, style_id)

    have, stale = _cache_state(funnel_slug, style_id)
    if have is None:
        return result("failed", detail="cache read failed")

    present = [s for s in CACHED if s in have]
    missing = [s for s in CACHED if s not in have]
    if not missing:
        return result("cached", cached=present, stale=stale)

    if client is None:
        client = _warm_api()
    if client is None:
        return result("skipped", cached=present, stale=stale,
                      detail="no API key or SDK")

    warmed, failed = [], []
    for section_id in missing:
        try:
            got = _generate(client, _cached_prompt(style, name, (section_id,)),
                            (section_id,), SECTION_TOKENS)
        except Exception as exc:
            log.warning("warm %s/%s/%s failed: %s", funnel_slug, style_id,
                        section_id, type(exc).__name__)
            got = None
        if not got:
            failed.append(section_id)
            continue
        _write_cache(funnel_slug, style_id, got)
        warmed.append(section_id)

    if not warmed:
        status = "failed"
    elif failed:
        status = "partial"
    else:
        status = "warmed"
    log.info("warm %s/%s: %s (warmed %s, already had %s, failed %s)",
             funnel_slug, style_id, status, len(warmed), len(present),
             len(failed))
    return result(status, cached=present, warmed=warmed, failed=failed,
                  stale=stale)


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

/* Sections flow across pages; only the individual cards stay whole, so a
   swatch or a numbered mistake is never split down the middle. */
.section { margin: 0 0 11mm; }
.section-title { break-after: avoid-page; }
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
.section p { margin: 0 0 2mm; }
.section p:last-child { margin-bottom: 0; }

.intro { margin: 0 0 4mm; }
.callout {
  margin: 4mm 0 0;
  padding: 2.5mm 0 2.5mm 4mm;
  border-left: 0.9mm solid #C05621;
  color: #16181d;
}

/* palette */
.swatch { display: flex; margin: 0 0 3mm; break-inside: avoid-page; }
.dot {
  display: inline-block;
  width: 7mm; height: 7mm;
  margin-right: 4mm;
  border-radius: 50%%;
  border: 0.25mm solid rgba(22, 24, 29, 0.12);
}
.swatch-text b { color: #16181d; }
.swatch-text span { display: block; }
.hex { display: inline !important; margin-left: 1.5mm; font-size: 9pt; color: #9aa0a6; }
.meta { font-size: 9.5pt; color: #C05621; }
.where { font-size: 10pt; }

/* numbered: mistakes and the shopping order */
.numbered { display: flex; margin: 0 0 4mm; break-inside: avoid-page; }
.num {
  flex: none;
  width: 8mm;
  font-family: %(serif)s;
  font-size: 14pt;
  font-weight: 600;
  color: #C05621;
}
.numbered b { color: #16181d; }
.fix { color: #C05621; }

/* materials */
.verdict { margin: 0 0 3.5mm; break-inside: avoid-page; }
.verdict b { color: #16181d; }
.badge {
  display: inline-block;
  padding: 0.5mm 1.8mm;
  border-radius: 1mm;
  font-size: 7.5pt;
  font-weight: 600;
  letter-spacing: 0.08em;
  vertical-align: 0.4mm;
}
.badge.works { background: #FDF1E7; color: #C05621; }
.badge.avoid { background: #FBEAE9; color: #B3261E; }

/* shopping skip block */
.skip { margin: 4mm 0 0; padding-top: 3mm; border-top: 0.2mm solid #e5e7eb; }
.skip b { color: #16181d; }
.struck { text-decoration: line-through; color: #9aa0a6 !important; }

/* splurge */
.splurge {
  padding: 3mm 4mm;
  margin: 0 0 3mm;
  border: 0.3mm solid #C05621;
  border-radius: 1.5mm;
  break-inside: avoid-page;
}
.splurge b { color: #C05621; }
.saves b { color: #16181d; }
.implication { color: #16181d; }
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


def _e(value):
    return html.escape(value or "")


def _pdf_palette(d):
    rows = "".join(
        '<div class="swatch"><span class="dot" style="background:%s"></span>'
        '<div class="swatch-text"><b>%s</b> <span class="hex">%s</span>'
        '<span class="meta">%s &middot; %s</span><span class="where">%s</span>'
        "</div></div>"
        % (_e(c["hex"]), _e(c["name"]), _e(c["hex"]), _e(c["role"]),
           _e(c["finish"]), _e(c["where"]))
        for c in d["colors"]
    )
    return ('<p class="intro">%s</p>%s<p class="callout">%s</p>'
            % (_e(d["intro"]), rows, _e(d["closing_rule"])))


def _pdf_mistakes(d):
    return "".join(
        '<div class="numbered"><span class="num">%d</span>'
        '<div><b>%s</b><p>%s</p><p class="fix">Fix: %s</p></div></div>'
        % (i + 1, _e(m["title"]), _e(m["body"]), _e(m["fix"]))
        for i, m in enumerate(d["items"])
    )


def _pdf_materials(d):
    rows = "".join(
        '<div class="verdict"><b>%s</b> <span class="badge %s">%s</span>'
        "<p>%s</p></div>"
        % (_e(p["combo"]), p["verdict"], p["verdict"].upper(), _e(p["why"]))
        for p in d["pairs"]
    )
    return ('<p class="intro">%s</p>%s<p class="callout">%s</p>'
            % (_e(d["intro"]), rows, _e(d["rule"])))


def _pdf_shopping(d):
    items = "".join(
        '<div class="numbered"><span class="num">%d</span>'
        "<div><b>%s</b><p>%s</p></div></div>"
        % (i + 1, _e(it["name"]), _e(it["priority_note"]))
        for i, it in enumerate(d["items"])
    )
    skips = "".join(
        "<p><b class='struck'>%s</b> %s</p>" % (_e(s["name"]), _e(s["why"]))
        for s in d["skip"]
    )
    return '%s<div class="skip"><b>Skip</b>%s</div>' % (items, skips)


def _pdf_dna(d):
    paras = "".join("<p>%s</p>" % _e(p) for p in d["narrative"])
    lines = "".join('<p class="implication">&rarr; %s</p>' % _e(p)
                    for p in d["implications"])
    return paras + lines


def _pdf_splurge(d):
    saves = "".join("<p><b>%s</b> %s</p>" % (_e(s["item"]), _e(s["why"]))
                    for s in d["saves"])
    return ('<div class="splurge"><b>Splurge &mdash; %s</b><p>%s</p></div>'
            '<div class="saves"><b>Save</b>%s</div>'
            '<p class="callout">%s</p>'
            % (_e(d["splurge"]["item"]), _e(d["splurge"]["why"]), saves,
               _e(d["split_note"])))


PDF_BODY = {
    "palette": _pdf_palette,
    "mistakes": _pdf_mistakes,
    "materials": _pdf_materials,
    "shopping": _pdf_shopping,
    "dna": _pdf_dna,
    "splurge": _pdf_splurge,
}


def _pdf_section_body(section, structured):
    """The inner HTML for one section, whichever schema it came in on."""
    if structured:
        data = section.get("data")
        builder = PDF_BODY.get(section.get("id"))
        if builder and isinstance(data, dict):
            try:
                return builder(data)
            except Exception:
                log.exception("pdf section %s failed", section.get("id"))
    # Schema 1, or a section that arrived without usable data.
    return "<p>%s</p>" % _e(section.get("body"))


def _pdf_html(content):
    name = _e(content.get("style_name") or "Your style")
    structured = _is_schema2(content.get("version"))
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
            '<span class="bar"></span></h2>%s</div>'
            % (_e(section.get("title")), _pdf_section_body(section, structured))
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
