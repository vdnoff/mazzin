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

TEMPERATURE = 0.7

# Output room, per section, sized from each section's own shape rather than
# from the smallest one. A section written to the standard the system prompt
# demands is not short: seven shopping items with a sentence each, indented,
# is about 600 tokens before the model has written anything wasteful, and the
# validator will accept up to about 1030. A flat 700 put `shopping` at its
# ceiling on every single call, and a response that runs out of room is
# unterminated JSON — which failed parsing, failed the retry, and stubbed.
#
# Raising a cap costs nothing that is not used: output is billed by what the
# model writes, not by what it was allowed to write.
SECTION_TOKENS = 900       # default for one section on its own
SECTION_TOKEN_BUDGET = {
    "palette": 900,        # 3-4 colours x 5 fields, plus intro and rule
    "mistakes": 1200,      # 4-6 items x title, body and fix
    "materials": 900,      # 3-4 pairs, plus intro and rule
    "shopping": 1400,      # 5-7 items plus 1-2 skips — the largest shape
    "dna": 700,            # two short paragraphs and two implications
    "splurge": 900,        # one splurge, three saves, one note
}


def _section_tokens(section_id):
    return SECTION_TOKEN_BUDGET.get(section_id, SECTION_TOKENS)


def _group_tokens(ids):
    """Room for a call that asks for several sections at once."""
    return sum(_section_tokens(i) for i in ids) or SECTION_TOKENS


# Kept as the ceiling for anything that asks for the whole report in one call.
MAX_TOKENS = sum(SECTION_TOKEN_BUDGET.values())

# The offline warmer's own limits. Nothing is waiting on it, so it is patient
# where the request path is not: a long per-call timeout and real retries in
# place of the request path's one.
WARM_TIMEOUT_S = 180.0
WARM_RETRIES = 3
# Offline, so the room a section gets is not rationed against a buyer waiting
# on it. Doubling the request-path budget costs nothing unless it is used.
WARM_TOKEN_FACTOR = 2

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


def _kind(value):
    """A type name for a log line. Never the value itself."""
    if isinstance(value, bool):
        return "bool"
    return type(value).__name__


# --- the declared shape ----------------------------------------------------

# One table, read by the validators and by the failure forensics alike. They
# used to hold separate copies of the bounds, and that is the whole reason
# "shape drift" went three rounds without ever naming a field: the validator
# knew a note was forty characters too long, and the forensics only knew the
# shape looked fine.
#
# Field rules:     ("text", low, high) | ("hex",) | ("enum", values)
# Container rules: ("obj", fields)
#                  ("list", low, high, fields | item rule, bare)


def _t(low, high=600):
    return ("text", low, high)


def _lst(low, high, fields, bare=False):
    """`bare` allows a row that arrived as a plain string instead of an object.

    Only where the string on its own is worth having. "Worktop stone" is a
    real shopping line with the reason left off; a mistake with a title and no
    body is a heading over an empty box, and the stub beats it.
    """
    return ("list", low, high, fields, bare)


def _obj(fields):
    return ("obj", fields)


HEX_RULE = ("hex",)
VERDICT_RULE = ("enum", VERDICTS)

# Prose fields top out at 600 — the ceiling a paragraph has always had in this
# file. The one-sentence fields used to stop at 300, which sounds generous
# until you count. A shopping section written to the standard SYSTEM demands
# arrives at 2500-3100 characters spread over six to nine rows, which puts the
# average note somewhere between 250 and 420 depending on how many rows the
# model chose. An average that close to a hard ceiling is not a near miss:
# sentences vary, and one note over the line threw away the whole section.
#
# The prompts still ask for less than this. The gap between what the prompt
# asks for and what the validator accepts is what absorbs a model writing a
# sentence and a half, and it is meant to be wide.
SHAPE = {
    "palette": {
        "intro": _t(20),
        "closing_rule": _t(15),
        "colors": _lst(3, 5, {"name": _t(2, 60), "hex": HEX_RULE,
                              "role": _t(2, 80), "finish": _t(2, 80),
                              # names the choice the colour came from as well
                              # as the surfaces, so it is not a label
                              "where": _t(2, 400)}),
    },
    "mistakes": {
        "items": _lst(4, 6, {"title": _t(3, 90), "body": _t(30),
                             "fix": _t(10)}),
    },
    "materials": {
        "intro": _t(20),
        "rule": _t(15),
        # `combo` names two or three materials with their finishes — a phrase,
        # not a heading.
        "pairs": _lst(3, 5, {"combo": _t(3, 140), "verdict": VERDICT_RULE,
                             "why": _t(15)}),
    },
    "shopping": {
        # 4-8 rather than the 5-7 the prompt asks for: a list one short is
        # still a shopping list, and the stub replacing it is worse than an
        # off-by-one.
        "items": _lst(4, 8, {"name": _t(2, 140),
                             "priority_note": _t(10)}, bare=True),
        "skip": _lst(1, 3, {"name": _t(2, 140), "why": _t(10)}, bare=True),
    },
    "dna": {
        "narrative": _lst(1, 3, _t(40)),
        "implications": _lst(2, 3, _t(10)),
    },
    "splurge": {
        "splurge": _obj({"item": _t(2, 140), "why": _t(15)}),
        "split_note": _t(10),
        "saves": _lst(2, 4, {"item": _t(2, 140), "why": _t(10)}, bare=True),
    },
}

# Spellings a model reaches for instead of the one it was handed, per
# canonical field name. An alias is the model being terse or synonym-happy,
# not the model sending something else, so accepting one costs nothing.
ALIASES = {
    "colors": ("colours", "palette"),
    "pairs": ("combinations", "combos"),
    "items": ("list", "buy"),
    "skip": ("skips", "avoid"),
    "narrative": ("story", "summary"),
    "implications": ("implication", "actions"),
    "splurge": ("spend", "invest"),
    "saves": ("save", "economise"),
    "split_note": ("split", "budget_split"),
    "name": ("item", "thing"),
    "item": ("name", "thing"),
    "priority_note": ("priority", "note", "why", "reason"),
    "why": ("reason", "note"),
}


def _names(field):
    return (field,) + ALIASES.get(field, ())


def _pick(d, field):
    """The value for `field` under any spelling it might have arrived as."""
    if not isinstance(d, dict):
        return None
    for key in _names(field):
        if key in d:
            return d[key]
    return None


def _pick_text(d, field):
    """The same, for a field that has to be a string — a string wins.

    Ordering matters more than it looks here. A model that ranks its shopping
    list sends `{"priority": 2, "note": "..."}`, and taking the first alias
    present hands the integer to a text rule and refuses a section that is
    perfectly good. So a string beats anything else, and a non-string comes
    back only when there is nothing better — which keeps the forensics able to
    say what the wrong type was.
    """
    if not isinstance(d, dict):
        return None
    fallback = None
    for key in _names(field):
        if key not in d:
            continue
        if isinstance(d[key], str):
            return d[key]
        if fallback is None:
            fallback = d[key]
    return fallback


def _for(d, field, rule):
    return (_pick_text(d, field) if rule[0] in ("text", "hex", "enum")
            else _pick(d, field))


def _check(rule, value):
    """(clean value, problem). `problem` describes the fault, never the value.

    Every refusal this returns is built from a type name, a character count or
    a declared constant. Nothing the model wrote can reach a log line through
    here.
    """
    kind = rule[0]
    if kind == "text":
        low, high = rule[1], rule[2]
        if not isinstance(value, str):
            return None, "%s, want str" % _kind(value)
        text = value.strip()
        if not low <= len(text) <= high:
            return None, "%d chars, want %d-%d" % (len(text), low, high)
        return text, None
    if kind == "hex":
        if not isinstance(value, str):
            return None, "%s, want str" % _kind(value)
        out = _hex(value)
        return (out, None) if out else (None, "not #rrggbb")
    if kind == "enum":
        if not isinstance(value, str):
            return None, "%s, want str" % _kind(value)
        out = value.strip().lower()
        if out not in rule[1]:
            return None, "not one of %s" % "/".join(rule[1])
        return out, None
    return value, None


def _items(value, low, high):
    """A list of the right length, wrapping a lone entry that forgot its list.

    `"skip": {...}` for a one-entry skip list is a model rendering "one or two
    entries" literally. The list of one it meant is recoverable; refusing it
    costs the section.
    """
    if isinstance(value, (dict, str)):
        value = [value]
    return value if isinstance(value, list) and low <= len(value) <= high else None


def _as_row(value, fields, bare=False):
    """One list entry as a dict of the declared fields, or None.

    A model that answers with ["Worktop stone", "Brass tap"] has given a real
    shopping list with the reasons left off. That is worth keeping where the
    name alone says something — the alternative is a generic stub — so the
    string becomes the first field and the rest are left empty rather than
    invented. Lists that have not asked for it get nothing.
    """
    names = list(fields)
    if isinstance(value, str):
        if not bare:
            return None
        return dict([(names[0], value)] + [(f, "") for f in names[1:]])
    if not isinstance(value, dict):
        return None
    return dict((f, _for(value, f, fields[f])) for f in names)


def _list_field(section_id, key, container):
    """The validated rows of one declared list field, or None."""
    _, low, high, fields, bare = SHAPE[section_id][key]
    got = _items(_pick(container, key), low, high)
    if got is None:
        return None

    out = []
    for entry in got:
        if isinstance(fields, tuple):           # a list of plain strings
            clean, problem = _check(fields, entry)
            if problem:
                return None
            out.append(clean)
            continue
        row = _as_row(entry, fields, bare)
        if row is None:
            return None
        clean = {}
        for n, (field, rule) in enumerate(fields.items()):
            value = row.get(field)
            # A row that arrived as a bare string has no body that could fail,
            # and one that was coerced that way and stored reads back with the
            # same empty note. Both have to round-trip: `_cache_state`
            # re-validates what it reads, so a shape this accepts and then
            # refuses would regenerate on every purchase, forever. A row that
            # arrived as an object with an unusable body is still a refusal.
            if bare and n and (isinstance(entry, str) or value == ""):
                clean[field] = ""
                continue
            value, problem = _check(rule, value)
            if problem:
                return None
            clean[field] = value
        out.append(clean)
    return out


def _scalars(section_id, d, *keys):
    """The declared non-list fields, or None if any of them fails."""
    out = {}
    for key in keys:
        rule = SHAPE[section_id][key]
        value, problem = _check(rule, _for(d, key, rule))
        if problem:
            return None
        out[key] = value
    return out


def _looks_like(section_id, d):
    """True when a dict resolves at least one of a section's declared fields."""
    return isinstance(d, dict) and any(
        _pick(d, key) is not None for key in SHAPE.get(section_id) or ())


def _unwrap(section_id, value):
    """Strip a wrapper the model put round the object it was asked for.

    `{"shopping": {"shopping": {...}}}` and `{"shopping": {"shopping_list":
    {...}}}` are the same habit under two names, so both the spelling and the
    contents are grounds to strip a layer. No section is declared with a single
    key, so a one-key object is never a section in its own right and unwrapping
    one can never discard a good answer.
    """
    for _ in range(4):
        if not (isinstance(value, dict) and len(value) == 1):
            break
        key, inner = next(iter(value.items()))
        if not isinstance(inner, dict):
            break
        # Either the wrapper is spelled like the section, or what is inside it
        # resolves as one. The first catches a model repeating the key it was
        # handed; the second catches it inventing a container name.
        if not (key == section_id or _looks_like(section_id, inner)):
            break
        value = inner
    return value


def _v_palette(d):
    colors = _list_field("palette", "colors", d)
    rest = _scalars("palette", d, "intro", "closing_rule")
    if colors is None or rest is None:
        return None
    return {"intro": rest["intro"], "colors": colors,
            "closing_rule": rest["closing_rule"]}


def _v_mistakes(d):
    items = _list_field("mistakes", "items", d)
    return {"items": items} if items else None


def _v_materials(d):
    pairs = _list_field("materials", "pairs", d)
    rest = _scalars("materials", d, "intro", "rule")
    if pairs is None or rest is None:
        return None
    # A page of nothing but "works" is a list, not a judgement.
    if not any(p["verdict"] == "avoid" for p in pairs):
        return None
    return {"intro": rest["intro"], "pairs": pairs, "rule": rest["rule"]}


def _v_shopping(d):
    items = _list_field("shopping", "items", d)
    skip = _list_field("shopping", "skip", d)
    if items is None or skip is None:
        return None
    return {"items": items, "skip": skip}


def _v_dna(d):
    if isinstance(_pick(d, "narrative"), str):     # tolerate one blob
        blob = _pick(d, "narrative")
        d = dict(d)
        for key in _names("narrative"):
            d.pop(key, None)
        d["narrative"] = [p.strip() for p in blob.split("\n\n") if p.strip()]
    narrative = _list_field("dna", "narrative", d)
    implications = _list_field("dna", "implications", d)
    if narrative is None or implications is None:
        return None
    return {"narrative": narrative, "implications": implications}


def _v_splurge(d):
    saves = _list_field("splurge", "saves", d)
    rest = _scalars("splurge", d, "split_note")
    head = _as_row(_pick(d, "splurge"), SHAPE["splurge"]["splurge"][1])
    if saves is None or rest is None or head is None:
        return None
    clean = {}
    for field, rule in SHAPE["splurge"]["splurge"][1].items():
        value, problem = _check(rule, head.get(field))
        if problem:
            return None
        clean[field] = value
    return {"splurge": clean, "saves": saves, "split_note": rest["split_note"]}


VALIDATORS = {
    "palette": _v_palette,
    "mistakes": _v_mistakes,
    "materials": _v_materials,
    "shopping": _v_shopping,
    "dna": _v_dna,
    "splurge": _v_splurge,
}


# --- why a section was refused ---------------------------------------------


def _roll(notes):
    """Say a per-row fault once with a count, not ten times with indices.

    A fault that happened once keeps its index — knowing it was the fourth row
    is worth more than the tidier `items[]`, and it is only when the whole list
    drifted the same way that the indices stop carrying anything.
    """
    order, seen, first = [], {}, {}
    for note in notes:
        key = re.sub(r"\[\d+\]", "[]", note)
        if key in seen:
            seen[key] += 1
            continue
        seen[key] = 1
        first[key] = note
        order.append(key)
    return ["%s (x%d)" % (k, seen[k]) if seen[k] > 1 else first[k]
            for k in order]


def _unknown(fields, d):
    """Keys in `d` that no declared field, under any spelling, accounts for."""
    known = set()
    for field in fields:
        known.update(_names(field))
    return sorted(set(d) - known)


def _extras(section_id, value):
    """Unknown keys a section carried, as names and types. Never values.

    Extras are not fatal — a model that adds `est_cost` to every shopping row
    has still answered the question, and throwing the section away over a
    bonus key would be the validator being precious. But they are the first
    visible sign that the prompt and the model have drifted apart, which is
    exactly the thing that went unnoticed for weeks here, so they are said out
    loud.
    """
    shape = SHAPE.get(section_id) or {}
    if not isinstance(value, dict):
        return []
    notes = ["%s(%s)" % (k, _kind(value[k])) for k in _unknown(shape, value)]
    for key, spec in shape.items():
        rows = _pick(value, key)
        fields = spec[3] if spec[0] == "list" else (
            spec[1] if spec[0] == "obj" else None)
        if not isinstance(fields, dict):
            continue
        for row in (rows if isinstance(rows, list) else [rows]):
            if not isinstance(row, dict):
                continue
            notes.extend("%s[].%s(%s)" % (key, k, _kind(row[k]))
                         for k in _unknown(fields, row))
    return _roll(notes)


def _field_notes(where, fields, row):
    """Per-field faults for one object: missing, extra, and rule failures."""
    notes, missing = [], []
    for field, rule in fields.items():
        value = _for(row, field, rule)
        if value is None and _pick(row, field) is None:
            missing.append(field)
            continue
        _, problem = _check(rule, value)
        if problem:
            notes.append("%s.%s: %s" % (where, field, problem))
    extra = _unknown(fields, row)
    if extra:
        notes.insert(0, "%s: extra %s"
                     % (where, ", ".join("%s(%s)" % (k, _kind(row[k]))
                                         for k in extra)))
    if missing:
        notes.insert(0, "%s: missing %s" % (where, ", ".join(missing)))
    return notes


def _drift_detail(section_id, value):
    """Field-level reasons a section was refused, as names, types and counts.

    The validators answer yes or no, which is the right contract for them and
    useless for working out what the model actually sent. This walks the same
    table they do — so it cannot disagree with them about a bound — and reports
    what is missing, extra, mistyped, miscounted or the wrong length. Never a
    value, never a word the model wrote.
    """
    shape = SHAPE.get(section_id)
    if not shape:
        return ["no declared shape for %r" % section_id]
    if not isinstance(value, dict):
        return ["section is %s, not an object" % _kind(value)]

    notes = ["extra key %r (%s)" % (k, _kind(value[k]))
             for k in _unknown(shape, value)]

    for key in sorted(shape):
        spec = shape[key]
        got = _pick(value, key)
        if got is None:
            notes.append("missing %r" % key)
            continue

        if spec[0] == "obj":
            if not isinstance(got, dict):
                notes.append("%s: %s, want object" % (key, _kind(got)))
                continue
            notes.extend(_field_notes(key, spec[1], got))
            continue

        if spec[0] != "list":
            _, problem = _check(spec, got)
            if problem:
                notes.append("%s: %s" % (key, problem))
            continue

        _, low, high, fields, bare = spec
        rows = _items(got, low, high)
        if rows is None:
            if not isinstance(got, list):
                notes.append("%s: %s, want list" % (key, _kind(got)))
                continue
            notes.append("%s: %d entries, want %d-%d"
                         % (key, len(got), low, high))
            rows = got
        for n, row in enumerate(rows):
            if isinstance(fields, tuple):          # plain strings
                _, problem = _check(fields, row)
                if problem:
                    notes.append("%s[%d]: %s" % (key, n, problem))
                continue
            if isinstance(row, str):
                if bare:
                    continue                       # coerced, not a fault
                notes.append("%s[%d]: str, want object with %s"
                             % (key, n, "/".join(fields)))
                continue
            if not isinstance(row, dict):
                notes.append("%s[%d]: %s, want object with %s"
                             % (key, n, _kind(row), "/".join(fields)))
                continue
            notes.extend(_field_notes("%s[%d]" % (key, n), fields, row))

    # `verdict` is the one rule that is about the set of rows rather than any
    # single one, so it has nowhere else to be reported from.
    if section_id == "materials" and not notes:
        rows = _items(_pick(value, "pairs"), 3, 5) or []
        verdicts = [_check(VERDICT_RULE, _pick(r, "verdict"))[0]
                    for r in rows if isinstance(r, dict)]
        if "avoid" not in verdicts:
            notes.append("pairs: no entry with verdict 'avoid'")

    if not notes:
        return ["shape and every field look right — nothing to report"]
    return _roll(notes)


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
    # Every array shows the number of entries that is actually wanted. It used
    # to show one, with a `// 5-7` comment beside it — but JSON has no comments
    # and the system prompt says to match the shape exactly, so a one-entry
    # example is an instruction to send one entry. That is what shape drift
    # was: the model matching the example it was given.
    #
    # Where a field has a length that matters, these say so in characters.
    # SHAPE accepts three times what is asked for here, deliberately: the
    # prompt sets the target and the validator sets the outer wall, and a
    # sentence and a half should land between the two rather than on the
    # floor.
    "palette": '''"palette": {
  "intro": "1-2 sentences on what this palette is doing and why it suits them",
  "colors": [
    {"name": "the dominant colour's name",
     "hex": "#RRGGBB — a real paint-range value, six hex digits",
     "role": "60% - walls and cabinet bulk",
     "finish": "matte, satin or eggshell, and nothing else",
     "where": "the exact surfaces it goes on"},
    {"name": "the secondary colour's name",
     "hex": "#RRGGBB",
     "role": "30% - joinery",
     "finish": "eggshell",
     "where": "the exact surfaces it goes on"},
    {"name": "the accent colour's name",
     "hex": "#RRGGBB",
     "role": "10% - hardware and one accent",
     "finish": "satin",
     "where": "the exact surfaces it goes on"}
  ],
  "closing_rule": "one sentence of sheen or finish advice, e.g. what to keep off gloss"
}

Send three colours in that order, or four if the fourth genuinely earns its
place. Never fewer than three. The `role` values carry the 60/30/10 split and
must add up to it.''',
    "mistakes": '''"mistakes": {
  "items": [
    {"title": "3-6 words, punchy, no full stop",
     "body": "2-3 sentences on what goes wrong and what it costs",
     "fix": "one imperative sentence — what to do instead"},
    {"title": "the second mistake", "body": "...", "fix": "..."},
    {"title": "the third mistake", "body": "...", "fix": "..."},
    {"title": "the fourth mistake", "body": "...", "fix": "..."},
    {"title": "the fifth mistake", "body": "...", "fix": "..."}
  ]
}

Send five items, each written out in full — the shortened entries above are
only showing you the shape. Each one expensive to undo once the units are in.''',
    "materials": '''"materials": {
  "intro": "1-2 sentences on how materials behave in this style",
  "pairs": [
    {"combo": "the two or three materials, named with their finish",
     "verdict": "works",
     "why": "1-2 sentences on what happens when you use it"},
    {"combo": "a second pairing", "verdict": "works", "why": "..."},
    {"combo": "a third pairing", "verdict": "avoid", "why": "..."}
  ],
  "rule": "one sentence they can carry into a showroom"
}

Send three pairings written out in full, or four. `verdict` is
"works" or "avoid" — exactly one of those two words, lower case and nothing
else — and at least one must be "avoid": a page of things that work is a
list, not a judgement.''',
    "shopping": '''"shopping": {
  "items": [
    {"name": "the first thing to buy",
     "priority_note": "one sentence on why it sits first in the order"},
    {"name": "the second thing to buy", "priority_note": "..."},
    {"name": "the third thing to buy", "priority_note": "..."},
    {"name": "the fourth thing to buy", "priority_note": "..."},
    {"name": "the fifth thing to buy", "priority_note": "..."}
  ],
  "skip": [
    {"name": "the thing to skip", "why": "one sentence on why it is wasted money"},
    {"name": "a second thing to skip", "why": "..."}
  ]
}

Send five to seven items, in buying order, each an object with both keys
written out in full — never a bare string, and never fewer than five. Send
one or two entries under `skip`, in the same object shape. Keep every `name`
short enough to read as a heading, and every `priority_note` and `why` to one
sentence under 200 characters.''',
    "dna": '''"dna": {
  "narrative": ["first short paragraph", "second short paragraph"],
  "implications": ["one thing to do differently", "a second thing to do differently"]
}

Both arrays hold plain strings. Send exactly two implications, each one
sentence under 200 characters.''',
    "splurge": '''"splurge": {
  "splurge": {"item": "the one thing to overspend on", "why": "1-2 sentences"},
  "saves": [
    {"item": "the first thing to buy cheaply",
     "why": "one sentence on why nobody notices"},
    {"item": "the second thing to buy cheaply", "why": "..."},
    {"item": "the third thing to buy cheaply", "why": "..."}
  ],
  "split_note": "a rough budget split across the two, in a sentence"
}

Send exactly three entries under `saves`, each an object with both keys, and
keep every `why` and the `split_note` to one sentence under 200 characters.''',
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


def _warm_tokens(section_id):
    """What one section is allowed offline. Same shape, more room."""
    return _section_tokens(section_id) * WARM_TOKEN_FACTOR


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


def _parse_detail(text, want):
    """(parsed, reason). `reason` is None on success, else why it was refused.

    The reason is diagnostic only and is built from field names, offsets and
    exception classes — never from the model's words. It exists because a
    section that fails here fails silently otherwise: the caller sees None and
    has no way to tell a truncated answer from a reshaped one.
    """
    if not text:
        return None, "empty response"
    body = FENCE_RE.sub("", text.strip()).strip()
    start, end = body.find("{"), body.rfind("}")
    if start < 0 or end <= start:
        # A response cut off mid-object never gets its closing brace, so this
        # is what truncation looks like by the time it reaches us.
        return None, ("no closing brace — response ends unterminated"
                      if start >= 0 else "no JSON object in response")
    try:
        data = json.loads(body[start:end + 1])
    except ValueError as exc:
        at = getattr(exc, "pos", None)
        # A response that ran out of room breaks at its own end, and the last
        # `}` we could find is from some earlier item — so the decode fails
        # near the tail rather than in the middle. Saying which it is turns a
        # log line into a diagnosis: run out of room, or came back malformed.
        tail = isinstance(at, int) and (end + 1 - start) - at < 200
        return None, ("invalid JSON (%s at char %s of %d)%s"
                      % (type(exc).__name__, at, len(body),
                         " — breaks at the end, looks truncated" if tail else ""))
    if not isinstance(data, dict):
        return None, "top level is %s, not an object" % type(data).__name__

    out = {}
    for key in want:
        value = data.get(key)
        if value is None:
            # A model that answered without the wrapper it was asked for has
            # still answered. Take the whole object as the section when it is
            # the only one being asked for and it looks like the right shape.
            if len(want) == 1 and _looks_like(key, data):
                value = data
            else:
                return None, "key %r missing" % key
        value = _unwrap(key, value)
        if not isinstance(value, dict):
            return None, "key %r is %s, not an object" % (key, type(value).__name__)
        clean = VALIDATORS[key](value)
        if clean is None:
            # The forensic layer, at warning. It was debug, on the reasoning
            # that the refusal line above already said enough — and then a
            # section failed every attempt for a fortnight while the one line
            # that would have named the field sat below the console's level.
            # Detail nobody can see is not detail. Names, types and counts
            # only; no value the model wrote reaches this.
            log.warning("section %s field drift: %s", key,
                        "; ".join(_drift_detail(key, value)))
            return None, "key %r failed its validator (shape drift)" % key
        extras = _extras(key, value)
        if extras:
            log.warning("section %s accepted with unknown keys: %s",
                        key, ", ".join(extras))
        out[key] = clean
    return out, None


def _parse(text, want):
    """The model's JSON as {section_id: data}, or None if it is unusable.

    Every section is validated against its own shape rather than checked for
    length. A section that is the wrong shape fails the whole group, which
    sends it to the retry and then to the stub — a half-built swatch list on a
    paid report is worse than a hand-written one.
    """
    return _parse_detail(text, want)[0]


def _ask(client, prompt, max_tokens):
    """(text, stop_reason). The stop reason is how truncation announces itself.

    `max_tokens` there means the model was still writing when it ran out of
    room, which is the difference between "the answer was wrong" and "we did
    not let it finish" — and the two need opposite fixes.
    """
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
    text = "".join(
        block.text for block in message.content if block.type == "text"
    )
    return text, getattr(message, "stop_reason", None)


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


def _generate(client, prompt, want, max_tokens=None):
    """One section group. Returns {section_id: body}, or None.

    A single personalised section needs a fraction of the room a six-section
    call did, so the budget is sized to what was asked for.

    Both refusals are logged. Returning None quietly was how a section could
    fail on every attempt for weeks with nothing in the log to say whether it
    was being cut off or coming back reshaped.
    """
    label = "+".join(want)
    if max_tokens is None:
        max_tokens = _group_tokens(want)

    text, stop = _attempt(client, prompt, max_tokens, label)
    parsed, why = _parse_detail(text, want)
    if parsed is not None:
        return parsed
    log.warning("section %s unusable: %s (%d chars, stop=%s, cap=%d) — retrying",
                label, why, len(text or ""), stop, max_tokens)

    text, stop = _attempt(client, prompt + RETRY_NOTE, max_tokens, label)
    parsed, why = _parse_detail(text, want)
    if parsed is None:
        log.warning("section %s given up: %s (%d chars, stop=%s, cap=%d)",
                    label, why, len(text or ""), stop, max_tokens)
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
                    (section_id,), _section_tokens(section_id)),
            })
        if cached is None:
            tasks.append({
                "ids": CACHED, "cache": True,
                "future": pool.submit(_generate, client,
                                      _cached_prompt(style, name), CACHED,
                                      _group_tokens(CACHED)),
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
                            (section_id,), _warm_tokens(section_id))
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
