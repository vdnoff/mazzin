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
import datetime
import decimal
import html
import json
import logging
import math
import os
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

SELECT_REPORT_SQL = (
    "SELECT content FROM reports WHERE purchase_id = %s ORDER BY id DESC LIMIT 1"
)

# Both ways a purchase can be identified in a link. Exactly one of them is
# filled for any given row: a hosted checkout has the session and no intent in
# the link, a payment confirmed in the page has the intent and no session.
# What the buyer was actually charged, as the webhook recorded it from
# Stripe. Read for the receipt line in the mail — see `_price_paid`, which
# will not name a number it cannot source.
SELECT_PURCHASE_PRICE_SQL = (
    "SELECT amount_cents, currency, created_at FROM purchases WHERE id = %s")

SELECT_PURCHASE_TOKENS_SQL = (
    "SELECT checkout_session, payment_intent FROM purchases WHERE id = %s"
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
        # Seven rather than six, because /brain's chapter sells five sharp
        # strengths and two habits and all seven belong in the one section
        # its title names. A ceiling is the outer wall rather than the
        # target: kitchen, zodiac and persona all still ask for five, and
        # widening a maximum cannot reject an answer that was accepted
        # before it moved.
        "items": _lst(4, 7, {"title": _t(3, 90), "body": _t(30),
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
        # 4-12 rather than the 5-7 kitchen's prompt asks for: a list one
        # short is still a shopping list, and the stub replacing it is worse
        # than an off-by-one. The twelve is the zodiac funnel, whose year map
        # is this shape with a month on every row — the ceiling has always
        # been the outer wall rather than the target, and kitchen's prompt
        # still asks for five to seven.
        "items": _lst(4, 12, {"name": _t(2, 140),
                              "priority_note": _t(10)}, bare=True),
        "skip": _lst(0, 3, {"name": _t(2, 140), "why": _t(10)}, bare=True),
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
    raw = _pick(container, key)
    # A field that may legitimately be empty is also allowed to be absent:
    # "send me none of these" and "do not send me these" are the same answer.
    if raw is None and low == 0:
        raw = []
    got = _items(raw, low, high)
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

# The second ask, for a funnel that wants to be told what it got wrong. The
# forensics behind `_drift_detail` have always known which field ran over and
# by how much — they were written to a log line and thrown away, so the retry
# repeated the prompt and the model repeated the overrun. This is that
# knowledge reaching the one party who can act on it.
#
# Names, counts and declared bounds only. Nothing the model wrote comes back
# to it through here except a banned phrase, which is the one case where the
# word itself is the correction.
RETRY_DRIFT = (
    "\n\nYour previous answer was refused. What was wrong with it, field by "
    "field:\n%s\n"
    "Send the whole section again with those corrected. The character counts "
    "are hard limits — count them before you answer. Everything not listed "
    "above was fine and should come back as it was.")


def _retry_prompt(prompt, notes):
    """The second ask, with what the first one got wrong when we know it.

    Without notes this is the line the file has always appended, byte for
    byte, which is what kitchen still gets.
    """
    if not notes:
        return prompt + RETRY_NOTE
    return (prompt + RETRY_NOTE
            + RETRY_DRIFT % "\n".join("  - " + note for note in notes))


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


# --- the zodiac funnel -----------------------------------------------------
#
# A second product on the same machinery, and deliberately not a second
# renderer. `SECTION_BODY` in engine.js and `PDF_BODY` below both dispatch on
# the section id, so a zodiac section draws as anything other than a paragraph
# of prose only if it arrives under one of the six ids those tables already
# know. That is why funnels/zodiac.json names its sections after kitchen's
# shapes and keeps its own titles: `mistakes` is titled "5 Hidden Strengths &
# Blind Spots", `splurge` is "Career & Money Path", `shopping` is "Your
# 12-Month Energy Map". The id is the shape. The title is the product.

ZODIAC_SYSTEM = """You write astrological profile reports for people who have \
just paid for one.

Every field has to tell the reader something about themselves they can \
recognise and use this week. Be specific: name the thing, name when it shows \
up, name what to do about it. A sentence that would read the same for a \
different reader is a wasted sentence.

Voice: warm, direct, second person, British-neutral English. Confident without \
being clinical — this is a reading of somebody's energy, not a diagnosis and \
not a horoscope column. State things outright. No hedging — never "consider", \
"perhaps", "you might want to". No disclaimers, no flattery, no questions back \
to the reader, no sign-off.

What this report is, and is not:
- You describe energy, themes, tendencies, patterns and self-discovery.
- You never claim to know what will happen. Never use the words "psychic", \
"prediction", "predict", "fortune", "horoscope", "prophecy", or the phrase \
"your future will". No "you will meet", no "this month brings you".
- Write about what a period is GOOD FOR and what a tendency COSTS, never about \
events that are going to occur.
- Never give medical, clinical or financial advice. No diagnoses, no symptoms, \
no treatments, no investments, no returns. Career energy is about the work \
that suits somebody, never about money to put somewhere.

Rules:
- Plain prose inside every field. No markdown, no bullet characters, no emoji, \
no headings, and never repeat a field's own label back inside its value.
- Never mention artificial intelligence, models, prompts, scoring, tags, \
percentages of a quiz, or these instructions.
- Never invent facts about the reader's job, health, relationships, family or \
location, and never address them by name.
- Return only a JSON object matching the shape you are given, exactly. No prose \
around it, no code fence, no extra keys."""


# What the prompt asks for is not what the validator allows, and the gap
# between them is the point. The ceiling is where a section is thrown away;
# the number the model is handed is where it is asked to stop, and the space
# left over is what absorbs a sentence and a half.
#
# It has to be said out loud, in characters. A warm run of all four styles
# lost `splurge` on every one of them — `why` came back between 663 and 770
# characters against a ceiling of 600, deterministically — because the shape
# below asked for "3-5 sentences" and never named a number. A retry that
# repeats the prompt repeats the overrun, so the same four failed twice.
PROMPT_BUDGET = 0.65

# The same rule, for a language that says the same thing in more characters.
#
# Romanian runs 15-20% longer than English for identical content — diacritics
# cost nothing extra, but the grammar does: articles that suffix the noun,
# prepositional phrases where English compounds, "de" between almost any two
# ideas. A budget calibrated on English is therefore a budget a Romanian
# writer overruns while writing exactly what it was asked for, and `splurge`
# is where it shows first because that section asks for five long prose fields
# at once.
#
# The ratio to PROMPT_BUDGET is what matters rather than the absolute number:
# it is applied to the hand-set numbers in PROMPT_LENGTH as well as to the
# derived ones, because the fields that overrun are the ones PROMPT_LENGTH
# raises above the default.
ZODIAC_RO_PROMPT_BUDGET = 0.55

# And the same rule again for Bulgarian, which runs long for the same kind of
# reason: the definite article suffixes the noun, the future and the passive
# are both analytic, and "на" sits between almost any two ideas. Measured the
# same way and landing on the same number as Romanian — which is a fact about
# how far both languages sit from English, not a shared constant, so it is
# written out here rather than aliased to the Romanian one.
ZODIAC_BG_PROMPT_BUDGET = 0.55


def _budget(cap, budget=None):
    """A round number to ask for, comfortably under a validator ceiling."""
    step = 5 if cap <= 100 else 10
    target = int(cap * (PROMPT_BUDGET if budget is None else budget))
    return min(cap, max(step, target - target % step))


def _rescale(asked, cap, budget):
    """One hand-set PROMPT_LENGTH number, in another language's budget.

    Scaled by the ratio between the budgets rather than recomputed from the
    ceiling, because these numbers are deliberate departures from the derived
    default — `mistakes` asks for less than the rule would give it and
    `splurge` asks for more, and both of those judgements survive the
    translation. Rounded to the same step, and clamped to the ceiling that
    polices the field so a ratio above 1 could never push one over.
    """
    if budget is None or budget == PROMPT_BUDGET:
        return asked
    step = 5 if cap <= 100 else 10
    target = int(asked * (budget / PROMPT_BUDGET))
    return min(cap, max(step, target - target % step))


def _walk_caps(section_id):
    """(path, field name, ceiling) for every capped text field in a section.

    Read off SHAPE rather than written out again here, so a ceiling that moves
    takes the prompts with it and no number in a prompt can quietly go stale.
    """
    out = []
    for key, spec in (SHAPE.get(section_id) or {}).items():
        if spec[0] == "text":
            out.append((key, key, spec[2]))
        elif spec[0] == "obj":
            for field, rule in spec[1].items():
                if rule[0] == "text":
                    out.append(("%s.%s" % (key, field), field, rule[2]))
        elif spec[0] == "list":
            fields = spec[3]
            if isinstance(fields, tuple):            # a list of plain strings
                if fields[0] == "text":
                    out.append(("%s[]" % key, key, fields[2]))
            else:
                for field, rule in fields.items():
                    if rule[0] == "text":
                        out.append(("%s[].%s" % (key, field), field, rule[2]))
    return out


# What a field is asked for, where the derived default is the wrong number.
#
# The default below takes what the model is told from the ceiling that would
# throw a section away, and leaves a deliberate gap: room for a sentence and
# a half. That is the right rule when the risk is losing a section, and the
# wrong one at both ends. The five hidden strengths ran a hundred and ten
# words each — an essay where the product is a hit — so they ask for less.
# Love and Money carry a second half each now, a how-to-play-it beside every
# sign and three concrete moves beside the work, so they ask for more.
#
# A number here can go either way and neither direction may pass the
# validator's own ceiling: _check_prompt_lengths below refuses at import
# rather than at generation, because a field asked for more than it is
# allowed is a section written to be thrown away. The ceilings themselves
# live in SHAPE and are not touched by any of this.
PROMPT_LENGTH = {
    "mistakes": {"body": 240, "fix": 140},
    "materials": {"intro": 440, "why": 440},
    "splurge": {"why": 440, "split_note": 440},
}


def _ceilings(section_id):
    """{bare field name: the tightest ceiling that field answers to}."""
    out = {}
    for _, field, cap in _walk_caps(section_id):
        out[field] = min(cap, out.get(field, cap))
    return out


def _budgets(section_id, budget=None):
    """{field name: the number to put in the prompt} for one section.

    Keyed by the bare field name, because that is what the shape example says.
    Where a name appears at two depths under different ceilings the tighter
    one wins — one number in the prompt has to satisfy both.

    `budget` is the profile's own, defaulting to the English one. Passing None
    reproduces this function's previous output exactly.
    """
    caps = _ceilings(section_id)
    out = {}
    for _, field, cap in _walk_caps(section_id):
        value = _budget(cap, budget)
        out[field] = min(value, out.get(field, value))
    for field, asked in (PROMPT_LENGTH.get(section_id) or {}).items():
        if field in out:
            out[field] = _rescale(asked, caps[field], budget)
    return out


def _check_prompt_lengths(budget=None):
    """Every stated budget is inside the ceiling that polices it."""
    for section_id, fields in PROMPT_LENGTH.items():
        ceilings = _ceilings(section_id)
        for field, asked in fields.items():
            cap = ceilings.get(field)
            if cap is None:
                raise ValueError("PROMPT_LENGTH names %s.%s, which is not a "
                                 "capped field" % (section_id, field))
            asked = _rescale(asked, cap, budget)
            if asked > cap:
                raise ValueError("PROMPT_LENGTH asks %d for %s.%s, over its "
                                 "%d ceiling" % (asked, section_id, field, cap))


_check_prompt_lengths()
_check_prompt_lengths(ZODIAC_RO_PROMPT_BUDGET)
_check_prompt_lengths(ZODIAC_BG_PROMPT_BUDGET)


def _budget_lines(section_id, budget=None):
    """The hard-limit recap that closes every zodiac shape.

    By path rather than by bare name — `saves[].why` — which is the same
    vocabulary the drift notes use when one of them comes back too long, so
    the correction and the original instruction read as the same thing.
    """
    budgets = _budgets(section_id, budget)
    return "\n".join(
        "  %-22s %d characters maximum" % (path, budgets[field])
        for path, field, _ in _walk_caps(section_id))


def _zodiac_spec(text, section_id, budget=None):
    """One shape, with its budgets substituted and its recap appended."""
    return (text % _budgets(section_id, budget)) + """

LENGTHS ARE HARD LIMITS. Count the characters and stay under every one of
them — a single field over its limit costs the entire section, so write to
the limit rather than to the sentence you had in mind:
%s""" % _budget_lines(section_id, budget)


# --- the words the module writes itself ------------------------------------
#
# Everything a finished report says that comes from neither the funnel config
# nor the model: the two prefixes the year map marks its months with, the
# labels the PDF prints around a section's own copy, the badges on the love
# verdicts, and the handful of fallbacks that stand in when a config or a run
# is missing a string.
#
# They were literals spread down the render path, which is how a Romanian
# report came back with English headings around Romanian sentences: every
# section was translated and none of the furniture between them was.
#
# The defaults are exactly what every report has printed since the first one,
# so a profile that declares no words of its own renders byte for byte what it
# always did. A profile that declares them replaces the whole map, built from
# this one, so a key added here is never missing from a translation.
RENDER_WORDS = {
    # The year map's two marks. Read three times over — the shape the model is
    # given, the stub that ships when generation fails, and the check that
    # polices the answer — and all three have to be the same two strings, or
    # the check refuses what the shape asked for.
    "year_strong": "Strongest month:",
    "year_quiet": "Quiet month:",
    # The PDF's own furniture, printed between the model's sentences.
    "fix": "Fix:",
    "skip": "Skip",
    "splurge": "Splurge",
    "save": "Save",
    "verdicts": {"works": "WORKS", "avoid": "AVOID"},
    # Fallbacks. Each stands in for something a config or a run should have
    # carried and did not, which is exactly when a reader is least able to
    # forgive a word in the wrong language.
    "style_fallback": "Your style",
    "taps_caption": "Read from your taps:",
    "pdf_note": ("Keep this — your report also stays available at the link "
                 "you were sent back to after checkout."),
    "mail_style": "style",
    "pdf_filename": "mazzin-%s-report.pdf",
}

# The same map, in the language /zodiac-ro sold in.
#
# "Merită" / "Renunță" rather than a literal Splurge / Save: that section is
# career energy and never money, and the Romanian words for spending and
# saving would put this funnel one noun away from the line its own banned list
# draws. "Merită" heads the work worth the effort, "Renunță" the list of
# things to decline — which is what those two headings actually mean here.
RENDER_WORDS_RO = dict(RENDER_WORDS, **{
    "year_strong": "Cea mai puternică lună:",
    "year_quiet": "Lună liniștită:",
    "fix": "Soluție:",
    "skip": "De evitat",
    "splurge": "Merită",
    "save": "Renunță",
    "verdicts": {"works": "MERGE", "avoid": "EVITĂ"},
    "style_fallback": "Stilul tău",
    "taps_caption": "Citit din alegerile tale:",
    "pdf_note": ("Păstrează-l — profilul tău rămâne disponibil și la linkul "
                 "primit după plată."),
    "mail_style": "personal",
    "pdf_filename": "mazzin-%s-profil.pdf",
})

# And the same map again for /zodiac-bg.
#
# "Струва си" / "Откажи се" rather than a literal Splurge / Save, for the same
# reason the Romanian pair is not literal: that section is career energy and
# never money, and the Bulgarian verbs for spending and putting money aside
# would put this funnel one noun away from the line its own banned list draws.
# "Струва си" heads the work worth the effort, "Откажи се" the list of things
# to decline — which is what the two headings actually mean here.
#
# The page says these same words. `funnels/zodiac-bg.json` carries the verdict
# badges and the month abbreviations in `result_copy.labels`, and
# tests/test_zodiacbg_check.py pins the two files to each other: a reader who
# saw РАБОТИ on the page and WORKS in the PDF has been handed two documents
# about themselves.
RENDER_WORDS_BG = dict(RENDER_WORDS, **{
    "year_strong": "Най-силен месец:",
    "year_quiet": "Тих месец:",
    "fix": "Решение:",
    "skip": "За избягване",
    "splurge": "Струва си",
    "save": "Откажи се",
    "verdicts": {"works": "РАБОТИ", "avoid": "ИЗБЯГВАЙ"},
    "style_fallback": "Твоят стил",
    "taps_caption": "Според докосванията ти:",
    "pdf_note": ("Запази го — профилът ти остава достъпен и на линка, към "
                 "който те върнахме след плащането."),
    "mail_style": "личен",
    "pdf_filename": "mazzin-%s-profil.pdf",
})


# The same six shapes, described for the other product. Keyed by the id the
# renderer dispatches on, written about what the reader was actually sold.
_ZODIAC_SHAPES = {
    "palette": '''"palette": {
  "intro": "1-2 sentences on what these four colours do for this person's energy (max %(intro)d chars)",
  "colors": [
    {"name": "COPY THE FIRST NAME FROM THE LIST ABOVE, EXACTLY",
     "hex": "COPY ITS CODE FROM THE LIST ABOVE, EXACTLY",
     "role": "what this colour is FOR - the kind of day or moment to reach for it (max %(role)d chars)",
     "finish": "when to use it: a day of the week, a time of day, or a kind of occasion (max %(finish)d chars)",
     "where": "how to carry it - worn, kept in a pocket, on a desk, in a room they spend time in (max %(where)d chars)"},
    {"name": "the second name from the list, exactly", "hex": "its code, exactly",
     "role": "...", "finish": "...", "where": "..."},
    {"name": "the third name from the list, exactly", "hex": "its code, exactly",
     "role": "...", "finish": "...", "where": "..."},
    {"name": "the fourth name from the list, exactly", "hex": "its code, exactly",
     "role": "...", "finish": "...", "where": "..."}
  ],
  "closing_rule": "one sentence naming their three talismans or stones and the day of the week each is worth carrying (max %(closing_rule)d chars)"
}

THE COLOURS ARE NOT YOURS TO CHOOSE. Four of them are given above, with their
codes. Reproduce all four, in that order, with the name and the code exactly
as written - character for character. Invent no colour, rename none, and write
no code that is not on that list. A section carrying a colour that is not
theirs is thrown away and asked for again.

What you write is what each one is FOR. This is not a paint chart and not a
clothing catalogue: never the words "matte", "satin", "eggshell", "gloss",
"sheen", "swatch" or "paint", no garment descriptions, no decorating. Write
about momentum, steadiness, being seen, being left alone - the days a colour
is worth reaching for and the days it is not.''',

    "mistakes": '''"mistakes": {
  "items": [
    {"title": "the hidden strength, as a short phrase (max %(title)d chars)",
     "body": "EXACTLY TWO SENTENCES and no more. The first says what the strength is and how it shows up in an ordinary week. The second says what it costs — the blind spot on its other side. No third sentence, and do not join two of them with a semicolon to get around that (max %(body)d chars)",
     "fix": "ONE imperative sentence starting with a verb — the thing to do differently this week. A second is allowed only if it is short (max %(fix)d chars)"},
    {"title": "the second one", "body": "two sentences", "fix": "one sentence"},
    {"title": "the third one", "body": "two sentences", "fix": "one sentence"},
    {"title": "the fourth one", "body": "two sentences", "fix": "one sentence"},
    {"title": "the fifth one", "body": "two sentences", "fix": "one sentence"}
  ]
}

Exactly five, under the single key `items`, each an object with `title`,
`body` and `fix` spelled exactly so. Every strength carries its own blind
spot inside the same body — a strength with no cost is flattery. `fix` is how
to spend the strength on purpose, never a warning.

All five are the same shape and the same length: two sentences and one. This
is read on a phone by somebody scrolling, and five paragraphs is an essay
where the product is five hits. Cut every clause that is scene-setting, every
"which is why", and every restatement of the title. If a sentence could be
deleted without losing a fact about this reader, delete it.''',

    "materials": '''"materials": {
  "intro": "THEIR PATTERN IN RELATIONSHIPS: 2-3 sentences on what this reader is repeatedly drawn to, what it costs them, and how it follows from the name they were given on the page they paid from. Use that name once, in the middle of a sentence rather than as a label (max %(intro)d chars)",
  "pairs": [
    {"combo": "their sign + another sign, e.g. \\"Leo + Aries\\" (max %(combo)d chars)",
     "verdict": "works",
     "why": "TWO PARTS IN ONE PARAGRAPH. First: what that pairing is like to be inside, and what it asks of them. Then, in the same paragraph: HOW TO PLAY IT — the one thing that actually works with this sign, written as something to do rather than something to know (max %(why)d chars)"},
    {"combo": "their sign + another sign", "verdict": "works", "why": "same two parts"},
    {"combo": "their sign + another sign", "verdict": "avoid", "why": "same shape, but the second part is HOW TO PROTECT THEIR ENERGY: the specific boundary that makes this one survivable, written as something to do"},
    {"combo": "their sign + another sign", "verdict": "avoid", "why": "same two parts"}
  ],
  "rule": "one sentence on what to say, or ask for, in the first month with somebody (max %(rule)d chars)"
}

Four pairings under `pairs`, two that work and two that cost, each an object
with `combo`, `verdict` and `why` spelled exactly so. `verdict` is the word
"works" or the word "avoid" and nothing else. `combo` always leads with this
reader's own sign. "avoid" means the pairing is expensive to be in, never
that a person is bad.

Every `why` carries both halves. The first half is what it is like; the
second is what to do about it, and it is the half the reader came for — a
pairing described and not answered is half a chapter. Name the thing to do
specifically enough to do it this month.''',

    "splurge": '''"splurge": {
  "splurge": {"item": "the kind of work or working environment this energy pays best in, as a short phrase (max %(item)d chars)",
              "why": "TWO PARTS IN ONE PARAGRAPH. First: why their energy earns here and what it looks like day to day. Then THREE CONCRETE MOVES, in the same paragraph — three things to actually do, each one naming a place to work, a time of day or week, or an action, in the language of their own element (max %(why)d chars)"},
  "saves": [
    {"item": "a kind of work to stop accepting, as a short phrase (max %(item)d chars)",
     "why": "what it costs them specifically, then one line on how to decline it — the sentence to say, or the condition to put on it (max %(why)d chars)"},
    {"item": "a second one", "why": "same two parts"},
    {"item": "a third one", "why": "same two parts"}
  ],
  "split_note": "THE LEAK, AND HOW TO PLUG IT: the single biggest drain on this reader's working energy, named outright, and then the one change that stops it. 2-3 sentences (max %(split_note)d chars)"
}

The three top-level keys are `splurge`, `saves` and `split_note`, spelled
exactly so and nothing else. `splurge` is a single object with `item` and
`why`; `saves` is a list of three objects with the same two keys;
`split_note` is one string. Do not send `item` or `why` at the top level, and
do not rename `split_note`.

`item` is a short phrase — a job shape, not a sentence. One place their
energy earns and three to stop spending it on. This is the shape of the work,
never money to put anywhere: no markets, no figures, and no advice about
where to place anything. The three moves are behaviour and energy — where to
be, when to work, what to say yes to — and never a thing to buy, hold or put
money into.

The second half of every field is the half the reader came for. A place named
and not acted on, a cost named and not declined, a leak named and not
plugged: each of those is a chapter that stops one sentence early.''',

    "dna": '''"dna": {
  "narrative": [
    "a paragraph on how this person's element, energy and tone actually combine — the blueprint, in their own nouns (max %(narrative)d chars)",
    "a second paragraph on the one place those three pull against each other, and what that tension produces (max %(narrative)d chars)"
  ],
  "implications": [
    "one sentence naming something concrete this means for how they decide (max %(implications)d chars)",
    "one sentence on what it means for how they rest (max %(implications)d chars)",
    "one sentence on what it means for how other people read them (max %(implications)d chars)"
  ]
}

Two keys only, `narrative` and `implications`, each a list of plain strings —
not objects. Two paragraphs and three implications. Each paragraph is its own
entry in the list and carries its own limit; do not run them together into
one long string. This is the section that has to sound like it was written
about this reader and nobody else.''',

    "shopping": '''"shopping": {
  "items": [
    {"name": "COPY THE 1st LABEL FROM THE LIST ABOVE, EXACTLY (max %(name)d chars)", "priority_note": "what this month's energy is good for (max %(priority_note)d chars — one or two sentences)"},
    {"name": "COPY THE 2nd, EXACTLY", "priority_note": "..."},
    {"name": "COPY THE 3rd, EXACTLY", "priority_note": "..."},
    {"name": "the 4th", "priority_note": "..."},
    {"name": "the 5th", "priority_note": "..."},
    {"name": "the 6th", "priority_note": "..."},
    {"name": "the 7th", "priority_note": "..."},
    {"name": "the 8th", "priority_note": "..."},
    {"name": "the 9th", "priority_note": "..."},
    {"name": "the 10th", "priority_note": "..."},
    {"name": "the 11th", "priority_note": "..."},
    {"name": "the 12th", "priority_note": "..."}
  ],
  "skip": []
}

Two keys, `items` and `skip`, spelled exactly so. Twelve items under `items`,
in the order the list above gives them, every one an object with `name` and
`priority_note`. `skip` is an empty list — send it, and put nothing in it.

`name` is the label from the list and nothing else — the month and the year,
exactly as written there. This map starts from the month they are in, not
from January, so the first item is the month they are living through right
now and four of the twelve are in next year.

Mark exactly three months by opening their note with "Strongest month:" and
exactly one by opening its note with "Quiet month:". The quiet one is for
recovery rather than for starting things, and its note says what it is good
for instead. Themes only — what a month is good for, never what is going to
happen in it.''',
}

ZODIAC_SPEC = dict((section_id, _zodiac_spec(text, section_id))
                   for section_id, text in _ZODIAC_SHAPES.items())

# The rule that goes under every Romanian shape, and the reason it has to.
#
# `splurge` asks, three times in one answer, for "the sentence to say" — the
# line to decline a piece of work with. A model asked for a sentence to say
# writes it the way anyone writes reported speech: inside quotation marks.
# Typed as ASCII `"` that is not punctuation, it is the end of the JSON string
# value, and the section is thrown away whole. Six consecutive failures on
# grounded_earth all broke on exactly that character, in exactly that field.
#
# So the fix is not another reminder to escape it. It is to stop asking for
# something that invites it: write the sentence plainly, without quotation
# marks around it, and where quoting really is unavoidable use the Romanian
# pair, which is not the JSON delimiter and needs no escaping.
#
# Romanian only. The English shapes ask the same question and are left
# exactly as they are.
ZODIAC_RO_JSON_RULE = """

PUNCTUATION, AND IT DECIDES WHETHER THIS SECTION SURVIVES. The straight
double-quote character (") is the JSON delimiter. Every one you type inside a
value ends that value early and costs the whole section, however good the
writing is.

So do not type it at all inside a value. Where a field asks you for a
sentence to say — the words to decline something with, the line to open a
conversation with — write that sentence plainly, with no quotation marks
around it at all: Spune-i simplu ca nu poti prelua asta acum. If you truly
must mark it as speech, use the Romanian pair „ and " (U+201E and U+201D),
never the straight one. The same goes for apostrophes: Romanian does not need
them, and a straight ' is safer than a straight " but still better avoided.

One more: every value is one line. No line breaks inside a value."""

def _marked_shapes(words):
    """The same shapes, with the year map's two marks said in one language.

    Only the shopping shape names them, and it names them as strings to copy
    rather than as an idea to express — so a Romanian report asked for the
    English prefix gets the English prefix, which is exactly what shipped.

    A replacement rather than a second shape written out: the two texts are
    the same instruction and a translation kept as its own copy is a paragraph
    that stops matching the English the first time either is edited.
    """
    shapes = dict(_ZODIAC_SHAPES)
    shapes["shopping"] = (
        shapes["shopping"]
        .replace(RENDER_WORDS["year_strong"], words["year_strong"])
        .replace(RENDER_WORDS["year_quiet"], words["year_quiet"]))
    return shapes


# The same six shapes, marked in Romanian, in Romanian numbers, each closing
# on that rule. Three separate things the Romanian shapes are and the English
# ones are not, and one object rather than three: a second RO spec beside this
# one would be a shape the profile does not use.
ZODIAC_RO_SPEC = dict(
    (section_id,
     _zodiac_spec(text, section_id, ZODIAC_RO_PROMPT_BUDGET)
     + ZODIAC_RO_JSON_RULE)
    for section_id, text in _marked_shapes(RENDER_WORDS_RO).items())


# The same contract for Bulgarian, and it is the same contract for the same
# reason: a model asked for "the sentence to say" types quotation marks around
# it, and one straight double quote inside a value costs the whole section.
# The pair offered instead is the Bulgarian one — „ and “ — which is not the
# same closing character Romanian uses, so this is written out rather than
# shared.
ZODIAC_BG_JSON_RULE = """

PUNCTUATION, AND IT DECIDES WHETHER THIS SECTION SURVIVES. The straight
double-quote character (") is the JSON delimiter. Every one you type inside a
value ends that value early and costs the whole section, however good the
writing is.

So do not type it at all inside a value. Where a field asks you for a
sentence to say — the words to decline something with, the line to open a
conversation with — write that sentence plainly, with no quotation marks
around it at all: Кажи му направо, че не можеш да поемеш това сега.

Where you truly must mark something as quoted — and the archetype name is the
one place you must — use the GUILLEMETS « and » (U+00AB and U+00BB):
«Небесен въздух». Never U+201E and never U+201C. Those two sit one keystroke
from the straight quote and are what this section keeps dying on: an opening
U+201E closed with a straight " ends the value there and throws the whole
section away. A guillemet cannot be mistaken for a delimiter and cannot end
anything. The same
goes for apostrophes: Bulgarian does not need them, and a straight ' is safer
than a straight " but still better avoided.

One more: every value is one line. No line breaks inside a value."""


# The same six shapes, marked in Bulgarian, in Bulgarian numbers, each closing
# on that rule.
ZODIAC_BG_SPEC = dict(
    (section_id,
     _zodiac_spec(text, section_id, ZODIAC_BG_PROMPT_BUDGET)
     + ZODIAC_BG_JSON_RULE)
    for section_id, text in _marked_shapes(RENDER_WORDS_BG).items())


# What a reader gets when generation fails outright, so it has to be
# publishable rather than apologetic — and true of the archetype, since the
# style name is the only thing it knows.
# The zodiac palette stub's colours are not written here; they are this
# reader's own, read off the config at build time.
FROM_CONFIG = "from-config"

# What each of the four is for, by position: the same order the config lists
# them in, which is the order the free result drew the swatches in. Written
# about days and momentum rather than finishes — this document is not a paint
# chart, and the stub is held to the rule the prompt states.
ZODIAC_COLOR_TEXT = [
    ("the one to live in",
     "ordinary days, and the ones you would like to stay ordinary",
     "The layer closest to you — what goes on without a decision."),
    ("for the day something has to move",
     "one day a week, picked in advance rather than in the moment",
     "One thing where the eye lands: a cuff, a strap, a scarf."),
    ("the weight underneath",
     "long days, and rooms you have to hold for other people",
     "Shoes, outer layers, and the corners of the room you work in."),
    ("used once and never twice",
     "the evening that matters, and none of the ones that do not",
     "A single piece at the collarbone or the wrist."),
]

ZODIAC_STUBS = {
    "palette": {
        "intro": "A {name} palette runs on one colour you live in, one you "
                 "reach for when a room needs to turn, and one carrying the "
                 "weight so the other two do not burn out.",
        # Filled from the style's own four power colours at build time. The
        # model is forbidden to invent a colour here, and the fallback the
        # reader gets when there is no model must not be allowed to either —
        # the page that took the money showed them four swatches by name.
        "colors": FROM_CONFIG,
        "closing_rule": "Carry one stone rather than three, and give it a day "
                        "of the week rather than a habit.",
    },
    # Two sentences and one, the same as the prompt asks for. A stub is what
    # a reader gets when there is no key, and it is not allowed to be a
    # different product from the one that arrives when there is.
    "mistakes": {
        "items": [
            {"title": "You read your own certainty as evidence",
             "body": "A {name} profile decides quickly and trusts the speed "
                     "of it. A decision made out of restlessness feels "
                     "identical, from the inside, to one made out of "
                     "conviction.",
             "fix": "Sleep one night on any decision you could explain in "
                    "ten seconds."},
            {"title": "You hold the useful thing until the moment is clean",
             "body": "You notice more than the people around you and you say "
                     "less of it. The read is usually right and it usually "
                     "arrives late, by which point the situation has resolved "
                     "without you in it.",
             "fix": "Set a ceiling of three days between noticing something "
                    "and naming it, clumsy wording included."},
            {"title": "You absorb the cost rather than name it",
             "body": "You take the extra hour and the awkward conversation, "
                     "and you take them quietly enough that nobody learns "
                     "they were extra. Over a few years the baseline "
                     "moves.",
             "fix": "Say what it took, once, at the moment it happens, "
                    "without asking for anything back."},
            {"title": "You leave at the point it stops being interesting",
             "body": "You see the shape of a thing early, which is the hard "
                     "part. Once the shape is clear the rest reads as admin, "
                     "and the value gets collected by whoever stayed.",
             "fix": "Pick one thing a quarter and stay past the boredom."},
            {"title": "You mistake being steady for being fine",
             "body": "Steadiness is what people rely on you for, and it makes "
                     "a poor instrument for measuring yourself. The weeks "
                     "that cost you most tend to look identical from "
                     "outside.",
             "fix": "Keep one measure of how a week went that is not how much "
                    "of it you got through."},
        ],
    },
    # Every `why` carries both halves, the same as the prompt asks for: what
    # it is like, then what to do about it. A stub is what a reader gets when
    # there is no key, and it must not be a different product from the one
    # that arrives when there is.
    "materials": {
        "intro": "The pattern underneath who you are drawn to is steadier "
                 "than the people themselves. You go towards the ones who "
                 "move at your speed and stay with the ones who slow you "
                 "down, which is a costly way round — and it is worth "
                 "knowing before the next one.",
        "pairs": [
            {"combo": "Your sign + a fire sign", "verdict": "works",
             "why": "Pace matches, and neither of you waits for the other "
                    "to finish deciding. How to play it: say the quiet part "
                    "in the first week rather than the fourth — this one "
                    "rewards being told, and reads a pause as a verdict."},
            {"combo": "Your sign + an earth sign", "verdict": "works",
             "why": "They hold the ground you move across, and the holding "
                    "is easy to stop seeing. How to play it: name one "
                    "specific thing they carried, out loud, every week — "
                    "steady people leave when the steadiness goes unread."},
            {"combo": "Your sign + a mirror of yourself", "verdict": "avoid",
             "why": "Two of the same energy make a fast start and a short "
                    "middle, and nothing in the pairing slows anything down. "
                    "How to protect your energy: keep one thing in your week "
                    "that is yours alone and do not move it for them."},
            {"combo": "Your sign + somebody who needs managing",
             "verdict": "avoid",
             "why": "You are good at carrying, which is exactly why this one "
                    "costs you more than it costs them. How to protect your "
                    "energy: stop offering before you are asked, once, and "
                    "watch what they do with the gap."},
        ],
        "rule": "In the first month ask the second question rather than the "
                "first — the answer to that one tells you something.",
    },
    "splurge": {
        "splurge": {
            "item": "Work with a visible edge and a short feedback loop",
            "why": "A {name} energy earns where the result comes back quickly "
                   "enough to steer by, and drifts on long horizons with no "
                   "signal. Three moves: put the hardest thing in the first "
                   "two hours of your day, before the room fills; ask for a "
                   "check-in at the halfway point of anything longer than a "
                   "month; and work the two days either side of a deadline "
                   "rather than the week before it.",
        },
        "saves": [
            {"item": "Work that needs performing",
             "why": "The energy it takes to be a version of yourself all day "
                    "is energy not spent on the work itself. Decline it by "
                    "asking what the output is — if the answer is a "
                    "presence, it is not work."},
            {"item": "Roles built entirely on maintaining",
             "why": "You will do it well, and it will cost you more than it "
                    "costs somebody suited to it. Decline it by naming the "
                    "part you will hold and the part you will hand back."},
            {"item": "Anything measured only in hours",
             "why": "It rewards presence over judgement, and judgement is the "
                    "thing you actually have. Put a deliverable on it before "
                    "you agree, or let it go to somebody who is paid to sit "
                    "there."},
        ],
        "split_note": "The leak is the second half of your afternoon, given "
                      "away in pieces to things that arrived rather than "
                      "things you chose. Plug it by booking the last ninety "
                      "minutes of the day to yourself before anyone else "
                      "books them, and treating that block as unmovable.",
    },
    "dna": {
        "narrative": [
            "A {name} blueprint runs on three things at once: the element you "
            "return to under pressure, the energy you keep time by, and the "
            "tone other people read first. Most of the time the three agree, "
            "and while they do you are easy to be around and easy to read "
            "for yourself.",
            "The interesting part is where they pull against each other. The "
            "tone arrives before the element does, so people meet the surface "
            "and adjust to it, and a certain amount of every week goes on "
            "correcting an impression you did not set out to make.",
        ],
        "implications": [
            "You decide faster than you can explain, which is worth trusting "
            "and worth writing down.",
            "Rest that looks like doing nothing does not restore you; rest "
            "with a shape does.",
            "People read your tone as your whole position, so the thing you "
            "say lightly is the thing they carry away.",
        ],
    },
    # Twelve months with no month names in the prose. The labels are stamped
    # on at build time from the reader's own year — this stub can be a March
    # or a September map depending on when generation failed — so a note that
    # said "since the autumn" would be a stub that contradicts its own
    # heading. Position in their year is the only thing these can be about.
    "shopping": {
        "items": [
            {"name": "1", "priority_note": "Good for deciding what this year "
             "is actually for, before anyone asks you to commit to it."},
            {"name": "2", "priority_note": "Good for clearing what the last "
             "one left open — the small unfinished things, not the big ones."},
            {"name": "3", "priority_note": "Strongest month: what you start "
             "here goes unnoticed long enough to get properly built."},
            {"name": "4", "priority_note": "Good for saying the thing you "
             "have been holding since before this map began."},
            {"name": "5", "priority_note": "Good for beginnings that need "
             "other people in them."},
            {"name": "6", "priority_note": "Strongest month: your judgement "
             "is at its sharpest — spend it on one thing rather than four."},
            {"name": "7", "priority_note": "Good for consolidating rather "
             "than adding — a month to finish, not to open."},
            {"name": "8", "priority_note": "Quiet month: low on output and "
             "high on recovery. Good for reading, repair and saying no."},
            {"name": "9", "priority_note": "Strongest month: momentum "
             "returns, and what you push now carries further than it should."},
            {"name": "10", "priority_note": "Good for repair work, in what "
             "you have built and in who you built it with."},
            {"name": "11", "priority_note": "Good for the conversations you "
             "have been scheduling around."},
            {"name": "12", "priority_note": "Good for looking back honestly "
             "at the eleven behind it, and deciding what repeats."},
        ],
        "skip": [],
    },
}


# --- the same fallbacks, in Romanian ---------------------------------------
#
# A stub is what a reader gets when generation fails outright, and until now
# the Romanian funnel's stubs were the English set: a reader who paid in
# Romanian and lost the model got an English report, which is the failure the
# fallback exists to prevent happening twice over. Short and generic like the
# English ones — a stub knows the archetype's name and nothing else about the
# person — with the full diacritics, and inside the same Terms line: nothing
# here foretells anything, and nothing here is medical or financial advice.
ZODIAC_COLOR_TEXT_RO = [
    ("cea în care trăiești",
     "zilele obișnuite, și pe cele pe care vrei să le păstrezi obișnuite",
     "Stratul cel mai apropiat de tine — ce se poartă fără o decizie."),
    ("pentru ziua în care ceva trebuie să se miște",
     "o zi pe săptămână, aleasă dinainte, nu pe moment",
     "Un singur loc unde cade privirea: o manșetă, o curea, o eșarfă."),
    ("greutatea de dedesubt",
     "zilele lungi, și încăperile pe care le ții pentru alții",
     "Încălțămintea, straturile de deasupra și colțurile camerei în care "
     "lucrezi."),
    ("folosită o dată și niciodată de două ori",
     "seara care contează, și niciuna dintre cele care nu contează",
     "O singură piesă, la claviculă sau la încheietură."),
]

ZODIAC_STUBS_RO = {
    "palette": {
        "intro": "O paletă {name} se ține pe o culoare în care trăiești, una "
                 "la care ajungi când o zi trebuie să se întoarcă și una care "
                 "duce greutatea, ca primele două să nu se ardă.",
        # The reader's own four, read off the config at build time, exactly as
        # the English stub does — the page that took the money named them.
        "colors": FROM_CONFIG,
        "closing_rule": "Poartă o singură piesă tare, nu trei, și dă-i o zi "
                        "din săptămână, nu un obicei.",
    },
    "mistakes": {
        "items": [
            {"title": "Îți citești propria certitudine ca pe o dovadă",
             "body": "Un profil {name} decide repede și are încredere în "
                     "viteza asta. O hotărâre luată din neliniște se simte "
                     "identic, pe dinăuntru, cu una luată din convingere.",
             "fix": "Dormi o noapte peste orice hotărâre pe care ai "
                    "putea-o explica în zece secunde."},
            {"title": "Ții lucrul folositor până când momentul e curat",
             "body": "Observi mai mult decât oamenii din jur și spui mai "
                     "puțin. Citirea ta e de obicei corectă și ajunge de "
                     "obicei târziu, când situația s-a rezolvat deja fără "
                     "tine.",
             "fix": "Pune-ți un plafon de trei zile între momentul în care "
                    "observi ceva și cel în care îl numești, cu tot cu "
                    "formularea stângace."},
            {"title": "Absorbi costul în loc să-l numești",
             "body": "Iei ora în plus și conversația incomodă, și le iei "
                     "destul de tăcut cât nimeni să nu afle că au fost în "
                     "plus. În câțiva ani, nivelul de la care se pleacă se "
                     "mută.",
             "fix": "Spune ce te-a costat, o dată, în momentul în care se "
                    "întâmplă, fără să ceri nimic în schimb."},
            {"title": "Pleci exact când încetează să fie interesant",
             "body": "Vezi devreme forma unui lucru, care e partea grea. "
                     "Odată ce forma e clară, restul se citește ca "
                     "administrație, iar valoarea o strânge cine a rămas.",
             "fix": "Alege un singur lucru pe trimestru și rămâi în el "
                    "dincolo de plictiseală."},
            {"title": "Confunzi faptul că ești constant cu faptul că ești "
                      "bine",
             "body": "Pe constanța ta se bazează ceilalți, și e un "
                     "instrument prost cu care să te măsori pe tine. "
                     "Săptămânile care te costă cel mai mult arată identic "
                     "din afară.",
             "fix": "Ține o măsură a felului în care a mers săptămâna care "
                    "să nu fie cât din ea ai apucat să treci."},
        ],
    },
    "materials": {
        "intro": "Tiparul de sub cine te atrage e mai constant decât oamenii "
                 "în sine. Mergi spre cei care se mișcă în ritmul tău și "
                 "rămâi cu cei care te încetinesc, ceea ce e un drum scump — "
                 "și merită știut înainte de următorul.",
        "pairs": [
            {"combo": "Semnul tău + un semn de foc", "verdict": "works",
             "why": "Ritmul se potrivește și niciunul nu așteaptă ca celălalt "
                    "să termine de decis. Cum îl joci: spune partea tăcută în "
                    "prima săptămână, nu într-a patra — acesta răspunde bine "
                    "când i se spune și citește o pauză ca pe o sentință."},
            {"combo": "Semnul tău + un semn de pământ", "verdict": "works",
             "why": "Ei țin pământul pe care te miști, iar ținerea asta e "
                    "ușor de încetat să o vezi. Cum îl joci: numește cu voce "
                    "tare, în fiecare săptămână, un lucru anume pe care l-au "
                    "dus — oamenii constanți pleacă atunci când constanța lor "
                    "nu e citită."},
            {"combo": "Semnul tău + o oglindă a ta", "verdict": "avoid",
             "why": "Două energii la fel fac un început rapid și un mijloc "
                    "scurt, și nimic din pereche nu încetinește nimic. Cum "
                    "îți protejezi energia: păstrează în săptămâna ta un "
                    "lucru care e numai al tău și nu-l muta pentru ei."},
            {"combo": "Semnul tău + cineva care are nevoie să fie dus",
             "verdict": "avoid",
             "why": "Ești bun la dus, exact de aceea acesta te costă pe tine "
                    "mai mult decât pe el. Cum îți protejezi energia: nu mai "
                    "oferi înainte să ți se ceară, o dată, și uită-te ce face "
                    "cu golul rămas."},
        ],
        "rule": "În prima lună pune a doua întrebare, nu pe prima — "
                "răspunsul la aceea îți spune ceva.",
    },
    "splurge": {
        "splurge": {
            "item": "Munca cu o margine vizibilă și un răspuns care vine "
                    "repede",
            "why": "O energie {name} dă cel mai mult acolo unde rezultatul se "
                   "întoarce destul de repede cât să poți corecta după el, și "
                   "se pierde pe orizonturi lungi, fără semnal. Trei mișcări: "
                   "pune lucrul cel mai greu în primele două ore ale zilei, "
                   "înainte să se umple camera; cere un punct de control la "
                   "jumătatea a orice ține mai mult de o lună; și lucrează "
                   "cele două zile din jurul unui termen, nu săptămâna "
                   "dinaintea lui.",
        },
        "saves": [
            {"item": "Munca ce cere să fie jucată",
             "why": "Energia cu care ești o versiune a ta toată ziua e "
                    "energie nepusă în munca propriu-zisă. Refuz-o "
                    "întrebând care e rezultatul — dacă răspunsul e o "
                    "prezență, nu e muncă."},
            {"item": "Rolurile construite numai pe întreținere",
             "why": "O vei face bine, și te va costa mai mult decât pe "
                    "cineva potrivit pentru ea. Refuz-o numind partea pe "
                    "care o ții și partea pe care o dai înapoi."},
            {"item": "Orice se măsoară doar în ore",
             "why": "Răsplătește prezența în locul judecății, iar judecata e "
                    "lucrul pe care îl ai cu adevărat. Pune un rezultat pe ea "
                    "înainte să accepți, sau las-o pe seama cuiva plătit să "
                    "stea acolo."},
        ],
        "split_note": "Pierderea e a doua jumătate a după-amiezii, dată "
                      "bucată cu bucată lucrurilor care au venit, nu celor pe "
                      "care le-ai ales. Astup-o rezervându-ți ultimele "
                      "nouăzeci de minute ale zilei înainte să ți le rezerve "
                      "altcineva, și tratând blocul acela ca pe ceva ce nu se "
                      "mută.",
    },
    "dna": {
        "narrative": [
            "Un plan {name} merge pe trei lucruri deodată: elementul la care "
            "te întorci sub presiune, energia după care ții timpul și tonul "
            "pe care ceilalți îl citesc primul. De cele mai multe ori cele "
            "trei sunt de acord, și cât sunt, ești ușor de suportat și ușor "
            "de citit pentru tine însuți.",
            "Partea interesantă e acolo unde se trag una de alta. Tonul "
            "ajunge înaintea elementului, așa că oamenii întâlnesc suprafața "
            "și se așază după ea, iar o parte din fiecare săptămână se duce "
            "pe corectarea unei impresii pe care nu ai vrut să o lași.",
        ],
        "implications": [
            "Decizi mai repede decât poți explica, ceea ce merită crezut și "
            "merită scris undeva.",
            "Odihna care arată ca a nu face nimic nu te reface; odihna cu o "
            "formă, da.",
            "Oamenii îți citesc tonul ca pe toată poziția ta, așa că lucrul "
            "spus în treacăt e lucrul pe care îl duc cu ei.",
        ],
    },
    # The same twelve positions as the English stub, with no month named in
    # the prose: the labels are stamped on at build time out of the reader's
    # own year. The three marks and the one are the profile's own words, and
    # they are the same two strings the shape asked the model for.
    "shopping": {
        "items": [
            {"name": "1", "priority_note": "Bună pentru a decide la ce e "
             "anul acesta, înainte să-ți ceară cineva să te ții de ceva."},
            {"name": "2", "priority_note": "Bună pentru a curăța ce a lăsat "
             "deschis anul dinainte — lucrurile mici neterminate, nu cele "
             "mari."},
            {"name": "3", "priority_note": "Cea mai puternică lună: ce începi "
             "aici trece neobservat destul cât să apuce să fie construit "
             "bine."},
            {"name": "4", "priority_note": "Bună pentru a spune lucrul pe "
             "care îl ții de dinainte să înceapă harta asta."},
            {"name": "5", "priority_note": "Bună pentru începuturile care au "
             "nevoie de alți oameni în ele."},
            {"name": "6", "priority_note": "Cea mai puternică lună: judecata "
             "ta e la cel mai ascuțit — dă-o pe un singur lucru, nu pe "
             "patru."},
            {"name": "7", "priority_note": "Bună pentru a strânge, nu pentru "
             "a adăuga — o lună de terminat, nu de deschis."},
            {"name": "8", "priority_note": "Lună liniștită: puțin randament "
             "și multă refacere. Bună pentru citit, pentru reparat și pentru "
             "a spune nu."},
            {"name": "9", "priority_note": "Cea mai puternică lună: elanul "
             "revine, și ce împingi acum ajunge mai departe decât ar "
             "trebui."},
            {"name": "10", "priority_note": "Bună pentru munca de reparație, "
             "în ce ai construit și în cine a construit cu tine."},
            {"name": "11", "priority_note": "Bună pentru conversațiile în "
             "jurul cărora tot faci programări."},
            {"name": "12", "priority_note": "Bună pentru a te uita cinstit "
             "înapoi la cele unsprezece dinainte și a decide ce se repetă."},
        ],
        "skip": [],
    },
}

# The same four swatch roles again, for the funnel that says them in
# Bulgarian. Same rule as the Romanian set: about days and momentum rather
# than finishes, because this document is not a paint chart.
ZODIAC_COLOR_TEXT_BG = [
    ("тази, в която живееш",
     "обикновените дни, и онези, които искаш да останат обикновени",
     "Слоят най-близо до теб — това, което се носи без решение."),
    ("за деня, в който нещо трябва да помръдне",
     "един ден в седмицата, избран предварително, а не в момента",
     "Едно място, където пада погледът: маншет, каишка, шал."),
    ("тежестта отдолу",
     "дългите дни, и стаите, които държиш заради другите",
     "Обувките, горните слоеве и ъглите на стаята, в която работиш."),
    ("използвана веднъж и никога два пъти",
     "вечерта, която има значение, и нито една от онези, които нямат",
     "Едно-единствено нещо на ключицата или на китката."),
]

# And the fallbacks, in Bulgarian. A reader who paid in Bulgarian and lost the
# model gets a Bulgarian report: publishable rather than apologetic, true of
# the archetype since the style name is the only thing it knows, and inside
# the same Terms line — nothing here foretells anything, and nothing here is
# medical or financial advice.
ZODIAC_STUBS_BG = {
    "palette": {
        "intro": "Палитрата \u00ab{name}\u00bb се държи на един цвят, в който живееш, "
                 "един, към който посягаш, когато денят трябва да се обърне, "
                 "и един, който носи тежестта, за да не изгорят първите два.",
        # The reader's own four, read off the config at build time, exactly as
        # the English and Romanian stubs do.
        "colors": FROM_CONFIG,
        "closing_rule": "Носи едно силно нещо, не три, и му дай един ден от "
                        "седмицата, а не навик.",
    },
    "mistakes": {
        "items": [
            {"title": "Четеш собствената си увереност като доказателство",
             "body": "Профилът \u00ab{name}\u00bb решава бързо и се доверява на тази "
                     "скорост. Решение, взето от безпокойство, се усеща "
                     "отвътре точно като решение, взето от убеденост.",
             "fix": "Преспи една нощ всяко решение, което може да се обясни "
                    "за десет секунди."},
            {"title": "Държиш полезното, докато моментът стане чист",
             "body": "Забелязваш повече от хората около теб и казваш "
                     "по-малко. Прочитът ти обикновено е верен и обикновено "
                     "идва късно, когато ситуацията вече се е решила без "
                     "теб.",
             "fix": "Сложи си таван от три дни между това да забележиш нещо "
                    "и това да го назовеш, с несръчните думи включително."},
            {"title": "Поемаш цената, вместо да я назовеш",
             "body": "Взимаш допълнителния час и неудобния разговор и ги "
                     "взимаш достатъчно тихо, че никой да не разбере, че са "
                     "били допълнителни. За няколко години нивото, от което "
                     "се тръгва, се измества.",
             "fix": "Кажи какво ти е струвало, веднъж, в момента, в който се "
                    "случва, без да искаш нищо в замяна."},
            {"title": "Тръгваш точно когато спре да е интересно",
             "body": "Виждаш формата на нещо рано, което е трудната част. "
                     "Щом формата е ясна, останалото прилича на "
                     "администрация, а стойността я прибира този, който е "
                     "останал.",
             "fix": "Избери едно нещо на тримесечие и остани в него отвъд "
                    "отегчението."},
            {"title": "Бъркаш постоянството с това, че си добре",
             "body": "На постоянството ти разчитат другите, а то е лош "
                     "инструмент, с който да мериш себе си. Седмиците, които "
                     "ти струват най-много, изглеждат отвън еднакво.",
             "fix": "Води си мярка за седмицата, която да не отчита само "
                    "това колко от нея е минало."},
        ],
    },
    "materials": {
        "intro": "Моделът под това кой те привлича е по-постоянен от самите "
                 "хора. Вървиш към тези, които се движат в твоя ритъм, и "
                 "оставаш с тези, които те забавят, а това е скъп път — и си "
                 "струва да се знае преди следващия.",
        "pairs": [
            {"combo": "Твоята зодия + огнена зодия", "verdict": "works",
             "why": "Ритъмът съвпада и никой не чака другия да свърши с "
                    "решаването. Как да го изиграеш: кажи тихата част през "
                    "първата седмица, не през четвъртата — отсрещният "
                    "реагира добре, когато му се казва, и приема паузата "
                    "като присъда."},
            {"combo": "Твоята зодия + земна зодия", "verdict": "works",
             "why": "Те държат почвата, по която се движиш, и тъкмо това "
                    "държане лесно спира да се вижда. Как да го изиграеш: "
                    "назовавай на глас всяка седмица по едно конкретно нещо, "
                    "което са свършили — постоянните хора си тръгват, когато "
                    "постоянството им остава незабелязано."},
            {"combo": "Твоята зодия + твое огледало", "verdict": "avoid",
             "why": "Две еднакви енергии правят бързо начало и кратка среда, "
                    "и нищо в двойката не забавя нищо. Как да пазиш "
                    "енергията си: остави в седмицата си едно нещо, което е "
                    "само твое, и не го мести заради тях."},
            {"combo": "Твоята зодия + някой, който има нужда да бъде носен",
             "verdict": "avoid",
             "why": "Носенето ти се отдава и точно затова този струва повече "
                    "на теб, отколкото на него. Как да пазиш енергията си: "
                    "спри да предлагаш, преди да са ти поискали, веднъж, и "
                    "виж какво прави с останалата празнина."},
        ],
        "rule": "През първия месец задай втория въпрос, не първия — "
                "отговорът на него ти казва нещо.",
    },
    "splurge": {
        "splurge": {
            "item": "Работа с видим ръб и с отговор, който идва бързо",
            "why": "Енергията \u00ab{name}\u00bb дава най-много там, където резултатът се "
                   "връща достатъчно бързо, за да можеш да коригираш по "
                   "него, и се губи по дълги хоризонти без сигнал. Три хода: "
                   "сложи най-тежкото нещо в първите два часа на деня, преди "
                   "стаята да се напълни; поискай контролна точка по средата "
                   "на всичко, което трае повече от месец; и работи двата "
                   "дни около срока, а не седмицата преди него.",
        },
        "saves": [
            {"item": "Работа, която иска да бъде изиграна",
             "why": "Енергията, с която си една своя версия по цял ден, е "
                    "енергия, невложена в самата работа. Откажи я, като "
                    "питаш какъв е резултатът — ако отговорът е присъствие, "
                    "това не е работа."},
            {"item": "Роли, построени само върху поддръжка",
             "why": "Ще я свършиш добре и ще ти струва повече, отколкото на "
                    "някой, на когото тя пасва. Откажи я, като назовеш "
                    "частта, която задържаш, и частта, която връщаш."},
            {"item": "Всичко, което се мери само в часове",
             "why": "Възнаграждава присъствието вместо преценката, а "
                    "преценката е това, което наистина имаш. Сложи резултат "
                    "върху нея, преди да приемеш, или я остави на някой, на "
                    "когото плащат да седи там."},
        ],
        "split_note": "Загубата е втората половина на следобеда, раздадена "
                      "парче по парче на неща, които са дошли, а не на "
                      "такива, които са избрани от теб. Запуши я, като "
                      "запазиш последните деветдесет минути от деня, преди "
                      "да ти ги запази някой друг, и като третираш този блок "
                      "като нещо, което не се мести.",
    },
    "dna": {
        "narrative": [
            "Планът \u00ab{name}\u00bb върви по три неща едновременно: стихията, към "
            "която се връщаш под напрежение, енергията, по която мериш "
            "времето, и тонът, който другите прочитат първи. През повечето "
            "време трите "
            "са съгласни, и докато са, с теб се живее лесно и сам се "
            "разчиташ лесно.",
            "Интересното е там, където се дърпат едно друго. Тонът стига "
            "преди стихията, така че хората срещат повърхността и се "
            "нареждат по нея, а част от всяка седмица отива в поправяне на "
            "впечатление, оставено без намерение.",
        ],
        "implications": [
            "Решаваш по-бързо, отколкото можеш да обясниш, и това заслужава "
            "доверие и заслужава да се запише някъде.",
            "Почивката, която изглежда като нищоправене, не те възстановява; "
            "почивката с форма — да.",
            "Хората четат тона ти като цялата ти позиция, така че казаното "
            "между другото е това, което отнасят със себе си.",
        ],
    },
    # The same twelve positions, with no month named in the prose: the labels
    # are stamped on at build time out of the reader's own year. The three
    # marks and the one are the profile's own words, and they are the same two
    # strings the shape asked the model for.
    "shopping": {
        "items": [
            {"name": "1", "priority_note": "Добър за решаване на какво е "
             "тази година, преди някой да те помоли да се хванеш за нещо."},
            {"name": "2", "priority_note": "Добър за разчистване на това, "
             "което миналата година е оставила отворено — малките "
             "недовършени неща, не големите."},
            {"name": "3", "priority_note": "Най-силен месец: това, което "
             "започваш тук, минава достатъчно незабелязано, за да успее да "
             "бъде построено добре."},
            {"name": "4", "priority_note": "Добър за изричане на това, което "
             "държиш отпреди тази карта да е започнала."},
            {"name": "5", "priority_note": "Добър за начала, които имат "
             "нужда от други хора в себе си."},
            {"name": "6", "priority_note": "Най-силен месец: преценката ти е "
             "най-остра — дай я на едно нещо, не на четири."},
            {"name": "7", "priority_note": "Добър за събиране, не за "
             "добавяне — месец за довършване, не за отваряне."},
            {"name": "8", "priority_note": "Тих месец: малко добив и много "
             "възстановяване. Добър за книги, за поправяне и за казване на "
             "не."},
            {"name": "9", "priority_note": "Най-силен месец: инерцията се "
             "връща, и това, което избуташ сега, стига по-далеч, отколкото "
             "би трябвало."},
            {"name": "10", "priority_note": "Добър за ремонтна работа — и в "
             "построеното, и в тези, които са строили с теб."},
            {"name": "11", "priority_note": "Добър за разговорите, около "
             "които все насрочваш срещи."},
            {"name": "12", "priority_note": "Добър за честен поглед назад "
             "към единадесетте преди него и за решаване какво се повтаря."},
        ],
        "skip": [],
    },
}

# Which stub sets are the zodiac product's. `_stub_for` stamps the year onto
# the shopping stub for these and only these, and it used to ask by identity
# against the one object there was.
ZODIAC_STUB_SETS = (ZODIAC_STUBS, ZODIAC_STUBS_RO, ZODIAC_STUBS_BG)


# The system prompt asks; this refuses. Two of these are a Terms line rather
# than a matter of taste, which is why the check runs on what the model wrote
# instead of trusting what it was told. Word-boundaried, so "unpredictable"
# and "fortunate" are not casualties.
ZODIAC_BANNED = tuple(re.compile(p, re.IGNORECASE) for p in (
    r"\bpsychic\w*\b",
    r"\bpredict(?:s|ed|ing|ion|ions|ive|ably)?\b",
    r"\bfortune(?:s|\s*-?\s*tell\w*)?\b",
    r"\byour future will\b",
    r"\bclairvoyan\w*\b",
    r"\bhoroscope\w*\b",
    r"\bprophec(?:y|ies)\b",
    r"\bdestined to\b",
    r"\bfated to\b",
    # the medical and financial half of the same line
    r"\bdiagnos(?:e|es|ed|is|tic)\w*\b",
    r"\bsymptoms?\b",
    # "treatment" on its own is ordinary English — the treatment of a theme —
    # and a false positive here costs a retry and then a stub, which a paying
    # reader pays for. Medical sense only.
    r"\bmedical treatment\b",
    r"\b(?:medication|prescri\w+|therapist)\b",
    r"\b(?:invest|invests|investing|investment|investments|portfolio)\b",
    r"\breturns on\b",
    r"\bfinancial advice\b",
))

# What a funnel needs that its JSON does not carry: the voice, the shapes
# described in that voice, the fallbacks, and which sections are worth holding
# per style. Anything not registered here is kitchen — /kitchen-visualizer
# included, which is kitchen's config with a photo step bolted on.
KITCHEN_PROFILE = {
    "system": SYSTEM,
    "spec": SPEC,
    "stubs": STUBS,
    "personal": PERSONAL,
    "cached": CACHED,
    "banned": (),
    # Kitchen's retry is the bare note it has always been. Its prompts carry
    # sentence counts rather than character budgets, so a drift list quoting
    # ceilings it was never given would be answering a question it was not
    # asked — that is a change to make deliberately, on its own evidence.
    "retry_detail": False,
    "pdf_lead": "Your kitchen style report",
}

ZODIAC_PROFILE = {
    "system": ZODIAC_SYSTEM,
    "spec": ZODIAC_SPEC,
    "stubs": ZODIAC_STUBS,
    # Archetype-driven, so identical for everyone who lands on a style and
    # work no buyer should pay for in latency. warm_cache.py fills these.
    "cached": ("palette", "mistakes", "splurge"),
    # Sign-driven: these three weave the reader's own sign and their own taps,
    # so they are written per purchase. Caching them per sign x style would be
    # fifty-two rows a funnel for nothing the reader could tell apart.
    "personal": ("dna", "materials", "shopping"),
    "banned": ZODIAC_BANNED,
    # Checks that run over a parsed section before it is accepted, bound to
    # the style — the colours a reader was promised are per archetype, and a
    # validator keyed on a section id alone cannot know them. Attached below,
    # where the rules exist.
    "verify": None,
    # A section whose prompt has changed enough that an answer cached under
    # the old one is the wrong answer. The tag travels with the row, so only
    # the sections named here go stale — kitchen declares no revisions and
    # every one of its rows stays valid.
    # `mistakes` is here because the prompt now asks for two sentences and one
    # where it asked for three and two. A row warmed under the old prompt is
    # not stale in the sense of being wrong — it is the old product, at the
    # old length, and the whole point of the change is the length.
    "cache_rev": {"palette": "colors2", "mistakes": "short1",
                  # The money section grew a second half — three concrete
                  # moves beside the work and a leak with a way to plug it —
                  # and it is cached per archetype, so every warmed row is
                  # the shorter product.
                  "splurge": "moves1"},
    "pdf_css": None,        # filled below, once ZODIAC_PDF_CSS is defined
    # The wordmark is dark ink, which on a dark page is a rectangle of
    # nothing. The light cut already exists and is what this document wants.
    "pdf_logo": "brand/logo-dark.svg",
    "pdf_note": ("Keep this — your profile also stays available at the link "
                 "you were sent back to after checkout."),
    # These shapes state a budget for every capped field, so a refusal can be
    # quoted back against a number the model was already given.
    "retry_detail": True,
    "pdf_lead": "Your cosmic profile report",
    # The cover this funnel draws instead of the plain one, and the node
    # markers down its sections. Both are the result page's own furniture,
    # brought to paper; a funnel that sets neither prints what it always did.
    "pdf_cover": None,      # filled below, once _zodiac_cover is defined
    "pdf_node": True,
    # The delivered page opens on a line confirming where the PDF went, so
    # this product's report response carries the address it went to. Declared
    # here rather than inferred, and only here: a funnel that does not ask for
    # the line is never handed the address at all.
    "delivery_note": True,
}

# --- the same product, in Romanian -----------------------------------------
#
# /zodiac-ro is zodiac30's walk with every string translated, and it needs a
# report to match: a reader who was sold in Romanian and handed an English PDF
# has been sold one thing and given another.
#
# The instructions below stay in English, deliberately. They are the same
# rules as ZODIAC_SYSTEM's, so the two can be read side by side and a change
# to one can be checked against the other; what is Romanian is the OUTPUT,
# which is what the reader sees. The keys of the JSON are English because the
# validators are.
ZODIAC_RO_SYSTEM = """You write astrological profile reports for people who \
have just paid for one. This funnel is Romanian, and every word you return is \
read by a Romanian speaker.

LANGUAGE — the first rule, and the one that voids the whole answer when it is \
broken. Write every field in natural, idiomatic Romanian: not translated \
English, but Romanian as a Romanian writer would put it, with Romanian rhythm \
and Romanian idiom. Use the full diacritics — a-breve, a-circumflex, \
i-circumflex, s-comma and t-comma (ă, â, î, ș, ț) — everywhere they belong, \
capitals included. A field written in English, or written in Romanian with the \
diacritics stripped off, is rejected.

Every field has to tell the reader something about themselves they can \
recognise and use this week. Be specific: name the thing, name when it shows \
up, name what to do about it. A sentence that would read the same for a \
different reader is a wasted sentence.

Voice: warm, direct, second person singular — "tu" and the verb forms that go \
with it, never the formal "dumneavoastră". Confident without being clinical — \
this is a reading of somebody's energy, not a diagnosis and not a newspaper \
horoscope column. State things outright. No hedging — never "poate", "s-ar \
putea", "ai putea să iei în considerare". No disclaimers, no flattery, no \
questions back to the reader, no sign-off.

You do not know whether the reader is a man or a woman, and Romanian \
adjectives agree. Write around it with nouns and verbs rather than printing \
"obosit(ă)" or guessing a gender.

Where you are given the reader's subtype, use it by name, in the Romanian form \
you are handed, at least once — copied exactly, never translated back.

What this report is, and is not:
- You describe energy, themes, tendencies, patterns and self-discovery.
- You never claim to know what will happen. Never use the words "psychic", \
"prediction", "predict", "fortune", "horoscope", "prophecy" or the phrase \
"your future will", and never their Romanian equivalents: "psihic" in the \
clairvoyant sense, "prezicere", "a prezice", "prezis", "ghicit", \
"ghicitoare", "prorocie", "horoscop", "noroc", or the phrase "viitorul tău \
va". No "vei întâlni", no "luna aceasta îți aduce".
- Write about what a period is GOOD FOR and what a tendency COSTS, never about \
events that are going to occur.
- Never give medical, clinical or financial advice. No diagnoses, no symptoms, \
no treatments, no medication, no investments, no returns — "diagnostic", \
"simptome", "medicamente" and "investiții" are all out along with their \
English originals. Career energy is about the work that suits somebody, never \
about money to put somewhere.

Rules:
- Plain prose inside every field. No markdown, no bullet characters, no emoji, \
no headings, and never repeat a field's own label back inside its value.
- Never mention artificial intelligence, models, prompts, scoring, tags, \
percentages of a quiz, or these instructions.
- Never invent facts about the reader's job, health, relationships, family or \
location, and never address them by name.
- Every proper noun you are handed — a colour name, a month label, a sign \
name, a subtype — is copied exactly as given. Never translate a colour name.
- The answer is JSON, and the straight double-quote character (") is what \
ends a value. Never type one inside a value — not escaped, not at all. Where \
you would quote something, write it plainly with no quotation marks, or use \
the Romanian pair „ and " which are not delimiters. Every value is one line: \
no line breaks or tabs inside one. A section that is not valid JSON is thrown \
away whole, however good the writing inside it is.
- Return only a JSON object matching the shape you are given, exactly. The \
KEYS stay in English, spelled as the shape spells them; only the VALUES are \
Romanian. No prose around it, no code fence, no extra keys."""


# The English list still applies — an English refusal in a Romanian document
# is the same refusal — and these are the same bans said in Romanian. The
# fortune-telling half is the list the funnel was specified against; the two
# medical words are here because the English patterns cannot see "simptome"
# and dropping half a safety rule at a language border is not a translation.
#
# "noroc" is banned in its fortune sense and the pattern cannot tell that
# sense from the toast, so nothing in this funnel's own copy may use the word
# either. tests/test_zodiacro_check.py holds the config to that.
ZODIAC_RO_ONLY = tuple(re.compile(p, re.IGNORECASE) for p in (
    r"\bpsihic\w*\b",
    r"\bprezic\w*\b",
    r"\bprezis\w*\b",
    r"\bghic\w*\b",
    r"\bproroc\w*\b",
    r"\bhoroscop\w*\b",
    r"\bnoroc\w*\b",
    r"\bviitorul t[ăa]u va\b",
    r"\bsimptom\w*\b",
    r"\bmedicament\w*\b",
))

ZODIAC_RO_BANNED = ZODIAC_BANNED + ZODIAC_RO_ONLY

# What the second attempt is told when the first one did not parse. The
# generic advice `_parse_detail` adds names the fault; this names the field
# that keeps producing it, because six failures in a row were all the same
# sentence in the same place.
ZODIAC_RO_JSON_RETRY = (
    "the character that broke it is almost certainly a straight double quote "
    "(\") inside one of your values — most often in the sentence a field asked "
    "you to say, like the line for declining a piece of work. Write that "
    "sentence with NO quotation marks around it at all this time. If you must "
    "mark it as speech use „ and \u201d. Do not type a straight double quote "
    "anywhere inside a value")

# A distinct object rather than a share of ZODIAC_PROFILE: the voice, the
# banned list, the year labels, the compatibility table and the mail are all
# different, and the checks that branch on a zodiac profile ask `_is_zodiac`
# rather than testing one identity.
ZODIAC_RO_PROFILE = {
    "system": ZODIAC_RO_SYSTEM,
    # The twin's shapes, asking for fewer characters and marking the year map
    # in this language. See ZODIAC_RO_PROMPT_BUDGET: the same content is
    # 15-20% longer in Romanian, and a budget calibrated on English is one
    # this funnel overruns while writing exactly what it was told to.
    "spec": ZODIAC_RO_SPEC,
    "prompt_budget": ZODIAC_RO_PROMPT_BUDGET,
    # Romanian, now. These were the English set on the reasoning that a
    # publishable English fallback beats an absent section — which was true of
    # an absent section and false of the page that actually shipped, where
    # three English blocks sat between six Romanian ones.
    "stubs": ZODIAC_STUBS_RO,
    "stub_colors": ZODIAC_COLOR_TEXT_RO,
    # What this report prints between the model's sentences: the PDF's
    # headings, the love verdicts' badges, and the fallbacks.
    "words": RENDER_WORDS_RO,
    # And the check that the year map came back marked in this language.
    # Declared here rather than on both zodiac profiles: the English funnels
    # have shipped without it since the first report and a new refusal on that
    # path would be a section a paying reader loses, whereas the mixed-language
    # answer this catches is the failure this funnel actually had.
    "verify_marks": True,
    "cached": ("palette", "mistakes", "splurge"),
    "personal": ("dna", "materials", "shopping"),
    "banned": ZODIAC_RO_BANNED,
    "verify": None,         # filled below, with the twin's
    "cache_rev": {"palette": "colors2", "mistakes": "short1",
                  "splurge": "moves1"},
    "pdf_css": None,        # filled below, once ZODIAC_PDF_CSS is defined
    "pdf_logo": "brand/logo-dark.svg",
    "pdf_lang": "ro",
    "pdf_note": ("Păstrează-l — profilul tău rămâne disponibil și la linkul "
                 "primit după plată."),
    "retry_detail": True,
    "pdf_lead": "Raportul profilului tău cosmic",
    "pdf_cover": None,      # filled below, once _zodiac_cover is defined
    "pdf_elements": None,   # filled below, with the Romanian element strip
    "pdf_node": True,
    "delivery_note": True,
    "compatibility": None,  # filled below, once COMPATIBILITY_RO exists
    "mail": None,           # filled below, once COPY_ZODIAC_RO exists
    "mail_kicker": "PROFILUL TĂU COSMIC",
    "mail_cross_fallback": "Profilul tău complet",
    "mail_link": None,      # filled below, once the RO button exists
    # Repeated to the model when its first answer did not parse. English
    # declares none and gets the generic advice alone, exactly as before.
    "json_retry": ZODIAC_RO_JSON_RETRY,
}

# --- the same product again, in Bulgarian ----------------------------------
#
# /zodiac-bg is zodiac30's walk with every string translated, and it needs a
# report to match, for the reason the Romanian one did: a reader sold in
# Bulgarian and handed an English PDF has been sold one thing and given
# another.
#
# The instructions below stay in English, deliberately, exactly as the
# Romanian ones do — they are the same rules as ZODIAC_SYSTEM's, so the three
# can be read side by side. What is Bulgarian is the OUTPUT, which is what the
# reader sees. The keys of the JSON are English because the validators are.
ZODIAC_BG_SYSTEM = """You write astrological profile reports for people who \
have just paid for one. This funnel is Bulgarian, and every word you return is \
read by a Bulgarian speaker.

LANGUAGE — the first rule, and the one that voids the whole answer when it is \
broken. Write every field in natural, idiomatic Bulgarian, in the CYRILLIC \
alphabet: not translated English, but Bulgarian as a Bulgarian writer would \
put it, with Bulgarian rhythm and Bulgarian idiom. Every letter of every \
sentence is Cyrillic — а, б, в, г, д, е, ж, з, и, й, к, л, м, н, о, п, р, с, \
т, у, ф, х, ц, ч, ш, щ, ъ, ь, ю, я — including the ъ, which Bulgarian uses \
inside ordinary words and which no other language spells this way. A field \
written in English, or transliterated into the Latin alphabet, is rejected.

Every field has to tell the reader something about themselves they can \
recognise and use this week. Be specific: name the thing, name when it shows \
up, name what to do about it. A sentence that would read the same for a \
different reader is a wasted sentence.

Voice: warm, direct, second person singular — "ти" and the verb forms that go \
with it, never the formal "Вие". Confident without being clinical — this is a \
reading of somebody's energy, not a diagnosis and not a newspaper horoscope \
column. State things outright. No hedging — never "може би", "евентуално", \
"би могъл да обмислиш". No disclaimers, no flattery, no questions back to the \
reader, no sign-off.

You do not know whether the reader is a man or a woman, and Bulgarian past \
participles and adjectives agree with gender. Write around it with nouns, \
present-tense verbs and impersonal constructions rather than printing \
"уморен(а)" or guessing.

Where you are given the reader's subtype, use it by name, in the Bulgarian \
form you are handed, at least once — copied exactly, never translated back.

NAMING THE ARCHETYPE. The style name you are given is a proper noun, and a \
Bulgarian sentence cannot glue it straight onto a bare noun: "Профил Небесен \
въздух решава бързо" is two nominatives side by side and reads as broken. \
Every time you name it, wrap the name in GUILLEMETS — « and » (U+00AB and \
U+00BB) — and never in any other mark: not the low-9 and turned-comma pair \
U+201E and U+201C, and above all not the straight double quote, which is the \
JSON delimiter and destroys the whole section. Write it «Небесен въздух», \
exactly as you were given it, never inflected.

In front of the name goes an ordinary lowercase common noun — профил, \
палитра, енергия, план, ум — and that noun takes the definite article only \
where the syntax of the sentence calls for one, exactly as any other noun \
would. As the subject it does: Профилът «Небесен въздух» решава бързо. \
Палитрата «Небесен въздух» се държи на един цвят. Енергията «Небесен \
въздух» дава най-много там, където. After a preposition it does not: умът на \
профила «Небесен въздух», в палитрата «Небесен въздух». Never capitalise \
that noun mid-sentence and never double the article — "Умът на Профилът" is \
not Bulgarian.

What this report is, and is not:
- You describe energy, themes, tendencies, patterns and self-discovery.
- You never claim to know what will happen. Never use the words "psychic", \
"prediction", "predict", "fortune", "horoscope", "prophecy" or the phrase \
"your future will", and never their Bulgarian equivalents: "ясновидец" and \
anything built on it, "предсказание", "предсказвам", "предричам", "гадая", \
"гадателка", "пророчество", "хороскоп", "късмет", or the phrase "бъдещето ти \
ще". No "ще срещнеш", no "този месец ти носи".
- Write about what a period is GOOD FOR and what a tendency COSTS, never about \
events that are going to occur.
- Never give medical, clinical or financial advice. No diagnoses, no symptoms, \
no treatments, no medication, no investments, no returns — "диагноза", \
"симптоми", "лекарства" and "инвестиции" are all out along with their English \
originals. Career energy is about the work that suits somebody, never about \
money to put somewhere.

Rules:
- Plain prose inside every field. No markdown, no bullet characters, no emoji, \
no headings, and never repeat a field's own label back inside its value.
- Never mention artificial intelligence, models, prompts, scoring, tags, \
percentages of a quiz, or these instructions.
- Never invent facts about the reader's job, health, relationships, family or \
location, and never address them by name.
- Every proper noun you are handed — a colour name, a month label, a sign \
name, a subtype — is copied exactly as given. Never translate a colour name.
- The answer is JSON, and the straight double-quote character (") is what \
ends a value. Never type one inside a value — not escaped, not at all. Where \
you would quote something, write it plainly with no quotation marks, or use \
the guillemets « and » which are not delimiters and cannot be confused with \
one. Do not use U+201E or U+201C either: they sit one keystroke from the \
straight quote and that is how sections get destroyed. Every value is one \
line: no line \
breaks or tabs inside one. A section that is not valid JSON is thrown away \
whole, however good the writing inside it is.
- Return only a JSON object matching the shape you are given, exactly. The \
KEYS stay in English, spelled as the shape spells them; only the VALUES are \
Bulgarian. No prose around it, no code fence, no extra keys."""


# The English list still applies — an English refusal in a Bulgarian document
# is the same refusal — and these are the same bans said in Bulgarian. The
# fortune-telling half is the list the funnel was specified against; the
# medical and financial words are here because the English patterns cannot see
# "симптоми" or "инвестиции", and dropping half a safety rule at a language
# border is not a translation.
#
# "късмет" is banned in its fortune sense and the pattern cannot tell that
# sense from the everyday one, so nothing in this funnel's own copy may use
# the word either — a lucky colour is a "цвят на силата" here.
# tests/test_zodiacbg_check.py holds the config to that.
ZODIAC_BG_ONLY = tuple(re.compile(p, re.IGNORECASE) for p in (
    r"\bясновид\w*\b",
    r"\bпредсказ\w*\b",
    r"\bпредреч\w*\b",
    r"\bгада\w*\b",
    r"\bпророч\w*\b",
    r"\bхороскоп\w*\b",
    r"\bкъсмет\w*\b",
    r"\bбъдещето ти ще\b",
    r"\bсимптом\w*\b",
    r"\bлекарств\w*\b",
    r"\bинвестиц\w*\b",
))

ZODIAC_BG_BANNED = ZODIAC_BANNED + ZODIAC_BG_ONLY

# What the second attempt is told when the first one did not parse. Same
# failure, same field, said for this language: the generic advice
# `_parse_detail` adds names the fault, and this names the field that keeps
# producing it.
ZODIAC_BG_JSON_RETRY = (
    "the character that broke it is almost certainly a straight double quote "
    "(\") inside one of your values, and the likeliest place is the archetype "
    "name: an opening U+201E closed with a straight \" ends the value there. "
    "Write the name in guillemets this time — \u00abНебесен въздух\u00bb, "
    "U+00AB and U+00BB, never U+201E and never U+201C — and write any "
    "sentence a field asked you to say with NO quotation marks around it at "
    "all. Do not type a straight double quote anywhere inside a value")

# A distinct object rather than a share of either zodiac profile: the voice,
# the banned list, the year labels, the compatibility table and the mail are
# all different, and the checks that branch on a zodiac profile ask
# `_is_zodiac` rather than testing one identity.
ZODIAC_BG_PROFILE = {
    "system": ZODIAC_BG_SYSTEM,
    # The twin's shapes, asking for fewer characters and marking the year map
    # in this language. See ZODIAC_BG_PROMPT_BUDGET.
    "spec": ZODIAC_BG_SPEC,
    "prompt_budget": ZODIAC_BG_PROMPT_BUDGET,
    "stubs": ZODIAC_STUBS_BG,
    "stub_colors": ZODIAC_COLOR_TEXT_BG,
    # What this report prints between the model's sentences: the PDF's
    # headings, the love verdicts' badges, and the fallbacks.
    "words": RENDER_WORDS_BG,
    # And the check that the year map came back marked in this language.
    "verify_marks": True,
    "cached": ("palette", "mistakes", "splurge"),
    "personal": ("dna", "materials", "shopping"),
    "banned": ZODIAC_BG_BANNED,
    "verify": None,         # filled below, with the twin's
    # Bumped past the English revisions rather than sharing them: every cached
    # section names the archetype, and the rule for how to name it in
    # Bulgarian changed. A row warmed under the old prompt says "Профил
    # Небесен въздух" — publishable English, broken Bulgarian — so all three
    # go stale and are written again.
    "cache_rev": {"palette": "bgname2", "mistakes": "bgname2",
                  "splurge": "bgname2"},
    "pdf_css": None,        # filled below, once ZODIAC_PDF_CSS is defined
    "pdf_logo": "brand/logo-dark.svg",
    "pdf_lang": "bg",
    "pdf_note": ("Запази го — профилът ти остава достъпен и на линка, към "
                 "който те върнахме след плащането."),
    "retry_detail": True,
    "pdf_lead": "Твоят личен космичен профил",
    "pdf_cover": None,      # filled below, once _zodiac_cover is defined
    "pdf_elements": None,   # filled below, with the Bulgarian element strip
    "pdf_node": True,
    "delivery_note": True,
    "compatibility": None,  # filled below, once COMPATIBILITY_BG exists
    "mail": None,           # filled below, once COPY_ZODIAC_BG exists
    "mail_kicker": "ТВОЯТ КОСМИЧЕН ПРОФИЛ",
    "mail_cross_fallback": "Пълният ти профил",
    "mail_link": None,      # filled below, once the BG button exists
    "json_retry": ZODIAC_BG_JSON_RETRY,
    # And the repair that runs before the parser, on this profile only.
    # Attached below, where the function exists.
    "json_repair": None,
}

# zodiac30 is the same product down a longer walk, so it is the same
# report: one voice, one set of shapes, one banned list, one PDF and
# one mail. The object is shared rather than copied because the checks
# that branch on this profile test it by identity.
#
# The section cache is keyed on the funnel as well as the style, so the
# two funnels warm their own rows off the same archetypes:
#
#     python3 scripts/warm_cache.py zodiac30 --copy-from zodiac
# --- the persona product ----------------------------------------------------
#
# Same machinery, a different reading. This funnel sells "shapes that unlock
# what's underneath": thirteen pairs of forms, an archetype won on tags, and a
# name on the other side of it. Nothing about it is astrological and nothing
# about it is clinical, and those are the two directions it can drift in — so
# the voice says so, the banned list enforces it, and the shapes below are
# written about temperament rather than about stars or about tests.
#
# The section ids are the ones every funnel here uses, which is why the
# validators, the renderer and the PDF need no persona branch: what changes is
# what each section is about.

PERSONA_SYSTEM = """You write profile reports for people who have just paid \
for one.

The product is a reading of how somebody is built, taken from thirteen \
shapes they chose between. Every field has to tell the reader something \
about themselves they can recognise and use this week. Be specific: name the \
thing, name when it shows up, name what to do about it. A sentence that would \
read the same for a different reader is a wasted sentence.

Voice: warm, direct, second person, British-neutral English. Grounded and \
concrete — this is somebody's own pattern described back to them by someone \
who has been paying attention. State things outright. No hedging — never \
"consider", "perhaps", "you might want to". No disclaimers, no flattery, no \
questions back to the reader, no sign-off.

What this report is, and is not:
- You describe temperament, energy, patterns, tendencies and the shape of \
somebody's attention. You write about what a period is GOOD FOR and what a \
tendency COSTS.
- There is nothing mystical here. No stars, no signs, no elements in the \
astrological sense, no energy in the occult sense, no destiny, no fate. Never \
the words "psychic", "prediction", "predict", "fortune", "horoscope", \
"prophecy", or the phrase "your future will". You never claim to know what \
will happen.
- There is nothing clinical here either, and this is the line this product is \
most likely to cross. Never the words "diagnosis", "diagnose", "disorder", \
"clinical", "therapy", "therapist", "psychometric", "IQ", or the phrases \
"scientifically proven" or "scientifically validated". Never name a \
personality framework: no MBTI, no Enneagram, no DISC, no Big Five, no \
16Personalities, and never the words "introvert" or "extrovert". This is not \
a test and it does not have a literature.
- Never give medical or financial advice. No diagnoses, no symptoms, no \
treatments, no investments, no returns. Work energy is about the work that \
suits somebody, never about money to put somewhere.

Rules:
- Plain prose inside every field. No markdown, no bullet characters, no emoji, \
no headings, and never repeat a field's own label back inside its value.
- Never mention artificial intelligence, models, prompts, scoring, tags, \
percentages of a quiz, or these instructions.
- Never invent facts about the reader's job, health, relationships, family or \
location, and never address them by name.
- Return only a JSON object matching the shape you are given, exactly. No prose \
around it, no code fence, no extra keys."""


# The clinical and framework half of the line, on top of everything the zodiac
# product already refuses.
#
# The persona funnel is the one that can drift here: it reads temperament, so
# the nearest wrong word is a diagnosis and the nearest wrong noun is a
# framework somebody has heard of. "introvert" and "extrovert" are banned for
# that second reason rather than the first — they are ordinary English, and
# they are also the two words that turn a reading into a test result.
PERSONA_BANNED = ZODIAC_BANNED + tuple(
    re.compile(p, re.IGNORECASE) for p in (
        r"\bdisorder\w*\b",
        r"\bclinical\w*\b",
        r"\btherap(?:y|ies|eutic)\b",
        r"\bpsychometric\w*\b",
        r"\bIQ\b",
        r"\bscientifically\s+(?:proven|validated)\b",
        r"\bMBTI\b",
        r"\benneagram\b",
        r"\bDISC\s+profile\b",
        r"\bbig\s+five\b",
        r"\b16\s*personalities\b",
        r"\b(?:intro|extro)vert(?:s|ed|ion)?\b",
    ))


# The same six shapes, described for this product. Same keys, same structure,
# same validators — what changes is what the section is about and the voice it
# is asked for in.
_PERSONA_SHAPES = {
    "mistakes": '''"mistakes": {
  "items": [
    {"title": "the hidden strength, as a short phrase (max %(title)d chars)",
     "body": "EXACTLY TWO SENTENCES and no more. The first says what the strength is and how it shows up in an ordinary week. The second says what it costs — the blind spot on its other side. No third sentence, and do not join two of them with a semicolon to get around that (max %(body)d chars)",
     "fix": "ONE imperative sentence starting with a verb — the thing to do differently this week. A second is allowed only if it is short (max %(fix)d chars)"},
    {"title": "the second one", "body": "two sentences", "fix": "one sentence"},
    {"title": "the third one", "body": "two sentences", "fix": "one sentence"},
    {"title": "the fourth one", "body": "two sentences", "fix": "one sentence"},
    {"title": "the fifth one", "body": "two sentences", "fix": "one sentence"}
  ]
}

Exactly five, under the single key `items`, each an object with `title`,
`body` and `fix` spelled exactly so. Every strength carries its own blind
spot inside the same body — a strength with no cost is flattery. `fix` is how
to spend the strength on purpose, never a warning.

All five are the same shape and the same length: two sentences and one. This
is read on a phone by somebody scrolling, and five paragraphs is an essay
where the product is five hits. Cut every clause that is scene-setting, every
"which is why", and every restatement of the title. If a sentence could be
deleted without losing a fact about this reader, delete it.''',

    "materials": '''"materials": {
  "intro": "THEIR PATTERN WITH OTHER PEOPLE: 2-3 sentences on who this reader is repeatedly drawn to, what it costs them, and how it follows from the name they were given on the page they paid from. Use that name once, in the middle of a sentence rather than as a label (max %(intro)d chars)",
  "pairs": [
    {"combo": "COPY THE FIRST PAIRING FROM THE LIST ABOVE, EXACTLY (max %(combo)d chars)",
     "verdict": "COPY ITS VERDICT FROM THE LIST ABOVE - the word works or the word avoid",
     "why": "ONE LINE. What this pairing is like and the one thing to do about it, in a single sentence a reader can act on. Not a paragraph, not two sentences joined by a semicolon (max %(why)d chars)"},
    {"combo": "the second pairing from the list, exactly", "verdict": "its verdict, exactly", "why": "one line"},
    {"combo": "the third pairing from the list, exactly", "verdict": "its verdict, exactly", "why": "one line"},
    {"combo": "the fourth pairing from the list, exactly", "verdict": "its verdict, exactly", "why": "one line"}
  ],
  "rule": "THE FIRST MONTH: 2-3 sentences on what to say, ask for, or watch for in the first month with somebody new — the paragraph this section closes on (max %(rule)d chars)"
}

THE PAIRINGS ARE NOT YOURS TO CHOOSE. Four of them are given above, each with
its verdict and a line saying what it is. Reproduce all four, in that order,
with the `combo` and the `verdict` exactly as written. Invent no pairing, and
never change a verdict.

`verdict` is the word "works" or the word "avoid" and nothing else. "avoid"
means the pairing is expensive to be in, never that a person is bad.

This section is read as a table: a name, a verdict, and one line. Four essays
is what it used to be and it is not what it is now — every `why` is a single
sentence carrying both halves, what it is like AND what to do, and the doing
is the half the reader came for. The paragraph at the end is `rule`, and it
is the only paragraph here.''',
    "dna": '''"dna": {
  "narrative": [
    "WHY THEY DRAIN WHERE OTHERS CHARGE: a paragraph naming the exact conditions that empty this person — the kind of room, the kind of demand, the hour of the day — built from the shapes they chose for pressure, drain and battery, and quoting at least one of them by the words on it (max %(narrative)d chars)",
    "a second paragraph on what fills them back up, in the same concrete terms: what recovery actually looks like for THEM rather than what rest looks like in general (max %(narrative)d chars)"
  ],
  "implications": [
    "one sentence naming the single situation to stop accepting (max %(implications)d chars)",
    "one sentence on the recovery that works for them and looks like laziness to somebody else (max %(implications)d chars)",
    "one sentence on the early sign they are running empty, before they notice it themselves (max %(implications)d chars)"
  ]
}

Two keys only, `narrative` and `implications`, each a list of plain strings —
not objects. Two paragraphs and three implications. Each paragraph is its own
entry in the list and carries its own limit; do not run them together into
one long string.

This is the section the reader bought first and its promise is exact: why
they drain where other people charge. Answer that question, in their own
conditions. Never a general theory of energy, never a kind of person, and
never a word that sorts people into types — the subject is what happens to
THIS reader in a Tuesday afternoon they would recognise.

The shapes they chose are how you make it theirs: quote one back by the words
on it. Not "you find noise difficult" but the thing they actually reached
for.''',
    "shopping": '''"shopping": {
  "items": [
    {"name": "COPY THE 1st LABEL FROM THE LIST ABOVE, EXACTLY (max %(name)d chars)", "priority_note": "what to DO in this month (max %(priority_note)d chars)"},
    {"name": "COPY THE 2nd, EXACTLY", "priority_note": "..."},
    {"name": "COPY THE 3rd, EXACTLY", "priority_note": "..."},
    {"name": "the 4th", "priority_note": "..."},
    {"name": "the 5th", "priority_note": "..."},
    {"name": "the 6th", "priority_note": "..."},
    {"name": "the 7th", "priority_note": "..."},
    {"name": "the 8th", "priority_note": "..."},
    {"name": "the 9th", "priority_note": "..."},
    {"name": "the 10th", "priority_note": "..."},
    {"name": "the 11th", "priority_note": "..."},
    {"name": "the 12th", "priority_note": "..."}
  ],
  "skip": []
}

Two keys, `items` and `skip`, spelled exactly so. Twelve items under `items`,
in the order the list above gives them, every one an object with `name` and
`priority_note`. `skip` is an empty list — send it, and put nothing in it.

`name` is the label from the list and nothing else — the month and the year,
exactly as written there. The map starts from the month they are in, not from
January, so four of the twelve are in next year.

WHAT EACH MONTH SAYS. Exactly three months open their note with
"Strongest month:" and exactly one opens with "Quiet month:".

- The three strongest: one CONCRETE ACTION each, in work or in how they
  spend their energy. A thing to start, ask for, ship, decline or book. Name
  it specifically enough to put in a calendar.
- The one quiet month: what to PROTECT — the thing to guard rather than the
  thing to start.
- The other eight: one or two lines each, and each one still says what the
  month is FOR. Shorter than the strong ones, never vaguer.

THIS IS MECHANICS, NOT MOOD. Every line is anchored to how this person is
built — their axis and their rhythm, the shapes they chose, the way they
drain and recover. Not to a season, not to a feeling, and not to what the
year "brings".

The register, exactly:

  BAD  "Warmth runs close to the surface this month."
  BAD  "The year closes on a warm current."
  BAD  "A month for reflection and gentle progress."
  GOOD "Strongest month: pitch the thing you have been drafting — you decide
        fastest in the first two hours and this is the month to spend them."
  GOOD "Quiet month: protect the standing block on your calendar. This is
        where the last three months get consolidated, not where you add."
  GOOD "Say no to the second project. Your drive runs ahead of your anchor
        here and the cost lands in the month after."

Never "energy" as a noun on its own, never "warmth", "current", "flow",
"season", "cycle", "the universe", "brings", "invites", "opens". If a
sentence would survive being moved to another reader, it is the wrong
sentence.''',
}

PERSONA_SPEC = dict((section_id, _zodiac_spec(text, section_id))
                    for section_id, text in _PERSONA_SHAPES.items())


# What a reader gets when there is no key, and it is not allowed to be a
# different product from the one that arrives when there is. Same lengths,
# same structure, same voice — and banned-clean, because the fallback is
# exactly the path where nothing is checking.
PERSONA_STUBS = {
    "mistakes": {
        "items": [
            {"title": "You read your own certainty as evidence",
             "body": "You decide quickly and you trust the speed of it. A "
                     "decision made out of restlessness feels identical, "
                     "from the inside, to one made out of conviction.",
             "fix": "Sleep one night on any decision you could explain in "
                    "ten seconds."},
            {"title": "You hold the useful thing until the moment is clean",
             "body": "You notice more than the people around you and you say "
                     "less of it. The read is usually right and it usually "
                     "arrives late, by which point the situation has "
                     "resolved without you in it.",
             "fix": "Set a ceiling of three days between noticing something "
                    "and naming it, clumsy wording included."},
            {"title": "You absorb the cost rather than name it",
             "body": "You take the extra hour and the awkward conversation, "
                     "and you take them quietly enough that nobody learns "
                     "they were extra. Over a few years the baseline moves.",
             "fix": "Say what it took, once, at the moment it happens, "
                    "without asking for anything back."},
            {"title": "You leave at the point it stops being interesting",
             "body": "You see the shape of a thing early, which is the hard "
                     "part. Once the shape is clear the rest reads as admin, "
                     "and the value gets collected by whoever stayed.",
             "fix": "Name the last ten percent before you start, and put a "
                    "date on it."},
            {"title": "You mistake being needed for being close",
             "body": "You are the one people bring the difficult thing to, "
                     "and you are good at it. Being useful to somebody is a "
                     "different arrangement from being known by them, and "
                     "the first can run for years without the second.",
             "fix": "Tell one person something you have not solved yet."},
        ],
    },
    "materials": {
        "intro": "A {name} is drawn to people who move at a different speed "
                 "— steadier or faster, rarely the same — and the pull is "
                 "real rather than a mistake. What it costs is that the "
                 "difference has to be talked about, and it usually is not "
                 "until it has already cost something.",
        "pairs": [
            {"combo": "{name} + a steadier profile",
             "verdict": "works",
             "why": "They hold the ground while you cover distance, and "
                    "neither of you has to argue for the arrangement. Say "
                    "out loud, early, which decisions you want them to slow "
                    "down and which you want left alone."},
            {"combo": "{name} + a profile that reads the room the way you do",
             "verdict": "works",
             "why": "You are understood without the preamble, which is rest "
                    "rather than romance. Give it something to do together "
                    "or the understanding turns into commentary."},
            {"combo": "{name} + a profile that needs constant motion",
             "verdict": "avoid",
             "why": "Two engines and no keel: it is exhilarating for a "
                    "season and expensive after it. Put one fixed thing in "
                    "the week that neither of you is allowed to move, and "
                    "protect it before anything else."},
            {"combo": "{name} + a profile that withholds to stay safe",
             "verdict": "avoid",
             "why": "You will read the silence as a puzzle and spend "
                    "yourself solving it. Ask once, plainly, and take the "
                    "answer you are given rather than the one you can "
                    "reconstruct."},
        ],
        "rule": "In the first month, ask what they do when they are tired — "
                "the answer tells you more than what they want.",
    },
    "dna": {
        "narrative": [
            "You drain in rooms that ask you to be available rather than "
            "useful — the long meeting with no decision in it, the afternoon "
            "of small interruptions, the conversation that circles. None of "
            "those look like work and all of them cost you the same as work "
            "does.",
            "What fills you back up is finishing something small enough to "
            "finish. Not rest in the sense of stopping: an hour with one "
            "task and a door shut, and the thing done at the end of it.",
        ],
        "implications": [
            "Stop accepting the meeting you are in to be reachable.",
            "Your recovery looks like tidying the edges of something already "
            "running, and it reads as procrastination to everyone watching.",
            "The early sign is that you start reading the same sentence "
            "twice — long before you feel tired.",
        ],
    },
    "shopping": {
        # The twelve carry positions rather than month names; the labels go on
        # at build time, from the same twelve the generated one is held to.
        "items": [
            {"name": "", "priority_note": "Strongest month: the one to start "
                                          "the thing you have been circling."},
            {"name": "", "priority_note": "Good for finishing what the last "
                                          "month started."},
            {"name": "", "priority_note": "Good for the conversation you have "
                                          "been drafting and not sending."},
            {"name": "", "priority_note": "Quiet month: recovery rather than "
                                          "starting. Good for tidying the "
                                          "edges of things already running."},
            {"name": "", "priority_note": "Good for saying yes to one thing "
                                          "outside your usual shape."},
            {"name": "", "priority_note": "Strongest month: the one to ask "
                                          "for something."},
            {"name": "", "priority_note": "Good for consolidating rather than "
                                          "adding."},
            {"name": "", "priority_note": "Good for the admin you have been "
                                          "treating as optional."},
            {"name": "", "priority_note": "Good for reconnecting with the "
                                          "person you meant to call."},
            {"name": "", "priority_note": "Strongest month: the one where "
                                          "effort compounds fastest."},
            {"name": "", "priority_note": "Good for deciding what next year "
                                          "does not include."},
            {"name": "", "priority_note": "Good for closing the year with one "
                                          "thing declared finished."},
        ],
        "skip": [],
    },
}


PERSONA_PROFILE = {
    "system": PERSONA_SYSTEM,
    "spec": PERSONA_SPEC,
    "stubs": PERSONA_STUBS,
    # Archetype-driven, so identical for everyone who lands on a persona and
    # work no buyer should pay for in latency. warm_cache.py fills these.
    # The same split zodiac uses, for the same reasons: these three are true
    # of the shape rather than of the run.
    # The one section that is true of the shape rather than of the run: the
    # hidden strengths belong to the archetype, so every buyer of a persona
    # gets the same five and none of them should pay for it in latency.
    #
    # It used to be three. The colours and the work section were the other
    # two, and both are gone — they were the zodiac product's vocabulary
    # wearing this one's name, and neither was on the card the reader buys
    # from. What is left is four sections, one per promise on that card.
    "cached": ("mistakes",),
    # Run-driven, all three. The drain section quotes the shapes they chose
    # for pressure and battery, the pairings are read off their own row, and
    # the year map starts in the month they bought in. Caching any of these
    # per persona would be eight rows of something meant to be about one
    # reader.
    "personal": ("dna", "materials", "shopping"),
    "banned": PERSONA_BANNED,
    "verify": None,         # filled below, once ZODIAC_VERIFY is defined
    "retry_detail": True,
    "pdf_lead": "Your mind profile report",
    "pdf_css": None,        # filled below, once PERSONA_PDF_CSS is defined
    "pdf_logo": "brand/logo-dark.svg",
    "pdf_note": ("Keep this — your profile also stays available at the link "
                 "you were sent back to after checkout."),
    "pdf_cover": None,      # filled below, once _persona_cover is defined
    "pdf_node": True,
    "delivery_note": True,
}


# --- /brain: the report a two-minute game buys ------------------------------
#
# The other three products read somebody: a kitchen from photographs, a sign
# from a date, a temperament from shapes. This one measures something instead
# — sixteen rounds, scored, with a number at the end — and that changes what
# the document has to be. A reading can afford to be interesting. A score has
# to be useful, or the reader has a number and nothing to do with it.
#
# So every section here ends on an action, and the whole report is written as
# a plan rather than as a verdict. The round somebody dropped is the round
# with the most room in it, and that is not a euphemism: it is the round where
# a week of two-minute drills moves the number most, which is the thing being
# sold.

# The line this product must not cross, and it is a different line from the
# others'. Zodiac drifts mystical and persona drifts toward a personality
# framework; this one drifts clinical, because it puts a number on somebody's
# head and calls it an age. Every word below is a word that turns a game into
# an assessment, and the reader did not buy an assessment.
#
# Written out rather than built on ZODIAC_BANNED: the mystical half is not a
# risk here — nothing in a memory game reaches for a horoscope — and every
# pattern a profile carries is a retry and then a stub when it fires, which a
# paying reader pays for in latency.
BRAIN_BANNED = tuple(re.compile(p, re.IGNORECASE) for p in (
    r"\bmemory\s+loss\b",
    r"\bcognitive\w*\b",
    r"\bdeclin(?:e|es|ed|ing)\b",
    r"\bdementia\b",
    r"\bhealth\w*\b",
    r"\bdiagnos(?:e|es|ed|is|tic)\w*\b",
    r"\btreatment\w*\b",
    r"\bsymptoms?\b",
    r"\bdisorder\w*\b",
    r"\bpatients?\b",
    r"\bclinical\w*\b",
    # The trademarked phrase, which this product is not and may not imply it
    # is. "Drill", "practice" and "round" are the words that belong here.
    r"\bbrain\s+training\b",
    r"\bIQ\b",
    r"\bimpair\w*\b",
    r"\bdeficit\w*\b",
))


BRAIN_SYSTEM = """You write improvement plans for people who have just \
played a two-minute memory game and paid for the plan that comes after it.

The game is sixteen scored rounds across four domains — recall, position, \
change and focus — and it ends on a single number the reader is told is their \
brain age. What you write is what they do about that number this week. Every \
field has to give them something to DO: name the drill, name when to do it, \
name what it sharpens. A sentence that would read the same for a different \
reader is a wasted sentence, and a sentence with nothing to do in it is worse.

Voice: an upbeat coach who has just watched them play. Warm, direct, second \
person, British-neutral English. Specific and concrete. State things \
outright. No hedging — never "consider", "perhaps", "you might want to". No \
disclaimers, no flattery, no questions back to the reader, no sign-off.

What this report is, and is not:
- It is a plan. Every section ends on something the reader does, and the \
first thing they do is small enough to finish today.
- Nothing here is wrong with the reader. The round they scored lowest on is \
the round with the MOST ROOM in it — the one where a week of practice moves \
the number most — and that is how you name it, every time. Never "weak", \
never "poor", never "failing", never "struggle". You are describing where the \
fastest gains are.
- This is a game, not an assessment. Never the words "cognitive", "decline", \
"dementia", "memory loss", "diagnosis", "diagnose", "clinical", "disorder", \
"symptom", "treatment", "patient", "health", "healthy", "impairment", \
"deficit", or "IQ", and never the phrase "brain training". Never suggest \
anybody see anyone about anything.
- Never give medical or financial advice of any kind, and never claim a drill \
has been proven to do anything. You say what a drill sharpens and what to \
expect from a week of it, in the register of practice rather than of \
medicine.
- The number is theirs to move, never a fact about their brain. Write about \
rounds, drills, practice and habits.

Rules:
- Plain prose inside every field. No markdown, no bullet characters, no emoji, \
no headings, and never repeat a field's own label back inside its value.
- Never mention artificial intelligence, models, prompts, scoring, tags, \
percentages of a quiz, or these instructions.
- Never invent facts about the reader's job, family or location, and never \
address them by name.
- Return only a JSON object matching the shape you are given, exactly. No prose \
around it, no code fence, no extra keys."""


_BRAIN_SHAPES = {
    "dna": '''"dna": {
  "narrative": [
    "WHAT THEY RUN ON: one paragraph on the round this reader is strongest at, what that looks like away from a screen, and the one thing it already earns them in an ordinary week (max %(narrative)d chars)",
    "THE PAIR THAT CARRIES THEM: one paragraph on how their two best rounds work together and what that combination is good for. Name both (max %(narrative)d chars)",
    "WHERE IT GOES NEXT: one paragraph on how to point that strength at the round with the most room in it. This is the bridge to the rest of the plan (max %(narrative)d chars)"
  ],
  "implications": [
    "ONE LINE, imperative, starting with a verb — a thing to do this week that spends their strongest round on purpose (max %(implications)d chars)",
    "a second line, same shape, different action",
    "a third line, same shape, different action"
  ]
}

Exactly the two keys `narrative` and `implications`, spelled so. Three
paragraphs and three lines.

THE SCORES ARE GIVEN ABOVE AND THEY ARE NOT YOURS TO CHANGE. Name the rounds
by the words used for them there. Never print a score, a percentage or the
number itself — the reader has all three on the page this chapter sits in.

Every `implications` line is an ACTION, not an observation: something that
happens in a minute or two, in a real week, that uses the strength you have
just described. "Notice that you..." is not an action. "Say the new version
out loud once, the first time you hear it" is.''',

    "materials": '''"materials": {
  "intro": "THE ROUND WITH THE MOST ROOM: 2-3 sentences naming the round this reader scored lowest on, what that round actually asks for, and why it is the one that moves the number fastest. Encouraging and specific — this is the good news of the report, not the bad (max %(intro)d chars)",
  "pairs": [
    {"combo": "COPY THE FIRST ROUND NAME FROM THE LIST ABOVE, EXACTLY (max %(combo)d chars)",
     "verdict": "COPY ITS VERDICT FROM THE LIST ABOVE - the word works or the word avoid",
     "why": "ONE LINE. What this round asks for, and the single thing to do about it — either how to spend it, or the drill that lifts it. Not a paragraph (max %(why)d chars)"},
    {"combo": "the second round from the list, exactly", "verdict": "its verdict, exactly", "why": "one line"},
    {"combo": "the third round from the list, exactly", "verdict": "its verdict, exactly", "why": "one line"},
    {"combo": "the fourth round from the list, exactly", "verdict": "its verdict, exactly", "why": "one line"}
  ],
  "rule": "THE DRILL: 2-3 sentences spelling out one two-minute drill for the round with the most room in it. What to do, with what, and how many times. Somebody has to be able to do it tomorrow morning from this paragraph alone (max %(rule)d chars)"
}

THE FOUR ROUNDS ARE NOT YOURS TO CHOOSE. All four are given above, each with
its verdict. Reproduce all four, in that order, with `combo` and `verdict`
exactly as written. Invent no round and never change a verdict.

`verdict` is the word "works" or the word "avoid" and nothing else. "avoid"
here does not mean anything is wrong — it marks the round with room in it,
and the line beside it says what lifts it.

This section is read as a table: a name, a badge, and one line. The paragraph
at the end is `rule`, and it is the only paragraph here. It is also the most
important thing in the report: it is the drill the whole plan is built on, so
it is specific enough to follow without thinking.''',

    "mistakes": '''"mistakes": {
  "items": [
    {"title": "the sharp strength, as a short phrase (max %(title)d chars)",
     "body": "EXACTLY TWO SENTENCES and no more. The first says what this brain type does better than most and where it shows up in an ordinary week. The second says what it makes easy that other people find hard. No third sentence, and do not join two of them with a semicolon to get around that (max %(body)d chars)",
     "fix": "ONE imperative sentence starting with a verb — how to spend this strength on purpose this week (max %(fix)d chars)"},
    {"title": "the second strength", "body": "two sentences", "fix": "one sentence"},
    {"title": "the third strength", "body": "two sentences", "fix": "one sentence"},
    {"title": "the fourth strength", "body": "two sentences", "fix": "one sentence"},
    {"title": "the fifth strength", "body": "two sentences", "fix": "one sentence"},
    {"title": "the first HABIT holding them back, as a short phrase", "body": "two sentences: what the habit is and when it happens", "fix": "one imperative sentence — the swap that replaces it"},
    {"title": "the second habit", "body": "two sentences", "fix": "one sentence"}
  ]
}

SEVEN items under the single key `items`, in this order: five strengths, then
two habits. Each is an object with `title`, `body` and `fix` spelled exactly
so.

The five strengths belong to this brain type and are genuinely good news —
five things this reader does better than most people, named specifically
enough to recognise. A strength nobody could fail to have is not a strength.

The two habits are habits, not faults: things this type does out of practice
that cost it speed, each with the swap that replaces it. Never say a habit
means something is wrong. `fix` on a habit is the replacement, in the
imperative, and it is small enough to start today.

All seven are the same shape and the same length: two sentences and one. This
is read on a phone by somebody scrolling. Cut every clause that is
scene-setting, every "which is why", and every restatement of the title.''',

    "shopping": '''"shopping": {
  "items": [
    {"name": "Day 1 - <the drill's name, two or three words> (max %(name)d chars)",
     "priority_note": "What to do, in enough detail to do it without thinking, and what it sharpens. Two to three sentences. Under five minutes, start to finish (max %(priority_note)d chars)"},
    {"name": "Day 2 - <its drill>", "priority_note": "what to do, and what it sharpens"},
    {"name": "Day 3 - <its drill>", "priority_note": "same"},
    {"name": "Day 4 - <its drill>", "priority_note": "same"},
    {"name": "Day 5 - <its drill>", "priority_note": "same"},
    {"name": "Day 6 - <its drill>", "priority_note": "same"},
    {"name": "Day 7 - <its drill>", "priority_note": "same"}
  ],
  "skip": []
}

Two keys, `items` and `skip`, spelled exactly so. SEVEN items under `items`,
one per day, in order. `skip` is an empty list — send it, and put nothing in
it.

`name` opens with the day, exactly as "Day 1 - ", "Day 2 - " and so on,
followed by a short name for that day's drill.

DAY ONE AND DAY FOUR BELONG TO THE ROUND WITH THE MOST ROOM. Day one is the
two-minute drill from the chapter before this one, said again in the doing
rather than in the explaining. Day four is a harder version of the same
thing. The other five days spread across the remaining three rounds, and at
least one of them spends the reader's strongest round rather than training it.

EVERY DAY IS A THING SOMEBODY DOES, ALONE, WITH WHAT THEY ALREADY HAVE. No
apps, no equipment, no other people required, nothing to buy. Under five
minutes each. If a day cannot be done at a bus stop or a kitchen table, it is
the wrong day.

The register, exactly:

  BAD  "Day 3 - Mindfulness: take some time to be present."
  BAD  "Day 5 - Focus work: try to concentrate for longer."
  GOOD "Day 1 - Shopping list recall: read a list of eight things once, put
        it face down, and write down as many as you can. Do it again in the
        evening with the same list and beat the morning score."
  GOOD "Day 6 - Room sweep: stand in a doorway, take one look, turn around,
        and name six things behind you and where each one was."

If a day would survive being moved to another reader with a different weakest
round, it is the wrong day.''',
}

BRAIN_SPEC = dict((section_id, _zodiac_spec(text, section_id))
                  for section_id, text in _BRAIN_SHAPES.items())


# The four rounds, and what each one is called in the document. The keys are
# the config's own domain prefixes, so a round renamed on the funnel is
# renamed here and in the prompt at the same time.
BRAIN_DOMAINS = ("mem", "spa", "chg", "foc")


# The badges the four rounds wear in the PDF. The class the stylesheet colours
# stays the English verdict; only the word inside it changes — and it changes
# because "AVOID" over the round somebody is being told to practise is the
# document contradicting its own advice.
BRAIN_WORDS = dict(
    RENDER_WORDS,
    verdicts={"works": "STRENGTH", "avoid": "ROOM TO GROW"},
    pdf_note=("Keep this — your plan also stays available at the link you "
              "were sent back to after checkout."),
)


# What a reader gets when there is no key, and it is not allowed to be a
# different product from the one that arrives when there is. Same lengths,
# same structure, same voice — and banned-clean, because the fallback is
# exactly the path where nothing is checking.
BRAIN_STUBS = {
    "dna": {
        "narrative": [
            "You hold what you have just been shown for a beat longer than "
            "most people do, and it turns up everywhere: the name you catch "
            "the first time, the aisle you walk back to without checking, "
            "the instruction you only need once.",
            "That holding pairs with how quickly you spot a difference. "
            "Together they make you the one who notices that something moved "
            "before anybody else has looked up, and the one who can say what "
            "it was.",
            "The round with the most room in it is the one that asks you to "
            "let go of what you were already holding. Point the same "
            "attention at starting fresh and the number comes down faster "
            "than anything else in this plan will move it.",
        ],
        "implications": [
            "Say a new name out loud once, the first time you hear it.",
            "Before you leave a room, take one look back and name three "
            "things and where they were.",
            "When a plan changes, say the new version aloud before you act "
            "on it.",
        ],
    },
    "materials": {
        "intro": "The round with the most room in it is the one that asks "
                 "you to drop what you were holding and take in something "
                 "new. That is good news: it is the round that responds "
                 "fastest to practice, and two minutes a day moves it inside "
                 "a week.",
        "pairs": [
            {"combo": "Memory", "verdict": "works",
             "why": "You keep what you were shown — spend it by taking one "
                    "deliberate look before you need to remember anything."},
            {"combo": "Spatial", "verdict": "works",
             "why": "You file where beside what — sketch a layout before you "
                    "start a task and the whole task gets shorter."},
            {"combo": "Change", "verdict": "avoid",
             "why": "Spotting an edit rewards a second look — count to two "
                    "before you decide nothing moved."},
            {"combo": "Focus", "verdict": "avoid",
             "why": "A narrow beam is fast and misses the edges — name the "
                    "target out loud before you aim it."},
        ],
        "rule": "Here is the drill. Open any page of text, read one "
                "paragraph once, close it, and say the paragraph back in a "
                "sentence. Do it three times, with three different "
                "paragraphs, and do it before you have looked at a screen "
                "for anything else. Two minutes, every morning, for a week.",
    },
    "mistakes": {
        "items": [
            {"title": "You only need telling once",
             "body": "An instruction lands with you first time and stays "
                     "there, which is why you are rarely the one asking for "
                     "it again. It makes you fast at anything with steps in "
                     "it.",
             "fix": "Take the instructions once, deliberately, and then put "
                    "them away rather than re-reading."},
            {"title": "You recognise before you can name",
             "body": "You know a face, a route or a difference before you "
                     "have found the word for it. That head start is worth "
                     "more than the word.",
             "fix": "Act on the recognition and let the name catch up."},
            {"title": "You keep the map",
             "body": "Where a thing was is filed with what it was, so you "
                     "walk back to things other people go looking for. It "
                     "saves you minutes every day you never notice.",
             "fix": "Put the things you reach for most in fixed places and "
                    "stop deciding."},
            {"title": "You notice the edit",
             "body": "Something moved and you knew before you could say "
                     "what. In a room full of people looking at the same "
                     "thing, you are the one who says so.",
             "fix": "Say what changed out loud, once, as soon as you spot "
                    "it."},
            {"title": "You finish what you start",
             "body": "Once your attention is on something it stays there "
                     "until the thing is done. Most people lose the thread "
                     "and you simply do not.",
             "fix": "Pick the one thing worth finishing before you start, "
                    "not after."},
            {"title": "You re-read what you already know",
             "body": "You go back over the instruction you took in first "
                     "time, because going back feels like being careful. It "
                     "costs a minute every time and buys nothing.",
             "fix": "Read it once, close it, and start."},
            {"title": "You decide nothing moved too quickly",
             "body": "When a difference is small you call it early and move "
                     "on. The one you miss is always the small one.",
             "fix": "Count to two before you decide two things are the "
                    "same."},
        ],
    },
    "shopping": {
        "items": [
            {"name": "Day 1 - Paragraph recall",
             "priority_note": "Read one paragraph of anything once, close "
                              "it, and say it back in a sentence. Three "
                              "paragraphs, two minutes. Sharpens the round "
                              "with the most room in it."},
            {"name": "Day 2 - Doorway sweep",
             "priority_note": "Stand in a doorway, take one look, turn "
                              "around, and name six things behind you and "
                              "where each one was. Sharpens position."},
            {"name": "Day 3 - List of eight",
             "priority_note": "Write eight things you need, read the list "
                              "once, put it face down, and shop from "
                              "memory. Check it at the till. Sharpens "
                              "recall."},
            {"name": "Day 4 - Paragraph recall, harder",
             "priority_note": "The same drill as day one, with two "
                              "paragraphs instead of one and a gap of an "
                              "hour before you say them back."},
            {"name": "Day 5 - Spot the change",
             "priority_note": "Look at a shelf or a desk for ten seconds, "
                              "turn away while somebody moves one thing, "
                              "and find it. On your own, move something "
                              "yourself and come back in an hour."},
            {"name": "Day 6 - One target",
             "priority_note": "Name out loud the one thing you are about to "
                              "do, then do only that until it is finished. "
                              "Once, on the hardest task of the day. "
                              "Sharpens focus."},
            {"name": "Day 7 - Play again",
             "priority_note": "Play the rounds again from the top and watch "
                              "the number. A week of two-minute drills "
                              "moves it, and this is the day you see by how "
                              "much."},
        ],
        "skip": [],
    },
}


BRAIN_PROFILE = {
    "system": BRAIN_SYSTEM,
    "spec": BRAIN_SPEC,
    "stubs": BRAIN_STUBS,
    # The five strengths and the two habits belong to the brain type rather
    # than to the run: everybody who plays as a Recorder gets the same seven,
    # which is what makes them worth warming once instead of writing eight
    # thousand times.
    "cached": ("mistakes",),
    # The other three are the run. The profile chapter names the rounds this
    # reader actually scored on, the weakest-round chapter is built around
    # which one that was, and the plan's first day is the drill for it —
    # caching any of them per type would be four answers where there are four
    # thousand readers.
    "personal": ("dna", "materials", "shopping"),
    "banned": BRAIN_BANNED,
    # No palette here and no year map, so there is nothing for the shared
    # verifier to hold this product to. What polices it is the banned list
    # above and the shapes themselves.
    "verify": None,
    "retry_detail": True,
    "words": BRAIN_WORDS,
    "mail": None,           # filled below, once COPY_BRAIN exists
    "mail_link": None,      # filled below, once the shared button exists
    "pdf_lead": "Your Brain Refresh report",
    "pdf_note": ("Keep this — your plan also stays available at the link you "
                 "were sent back to after checkout."),
    "delivery_note": True,
}


PROFILES = {"zodiac": ZODIAC_PROFILE, "zodiac30": ZODIAC_PROFILE,
            "zodiac-ro": ZODIAC_RO_PROFILE,
            "zodiac-bg": ZODIAC_BG_PROFILE,
            "persona": PERSONA_PROFILE,
            "brain": BRAIN_PROFILE}


def _prompt_budget(profile):
    """The share of a validator's ceiling this profile's prompts ask for.

    A profile that does not declare one gets PROMPT_BUDGET, which is every
    profile but the Romanian one — so this reads as the English number
    everywhere it always was.
    """
    return (profile or {}).get("prompt_budget") or PROMPT_BUDGET


def _is_zodiac(profile):
    """True for either zodiac voice.

    The branches below used to test `is ZODIAC_PROFILE`, which was exact while
    there was one object for the two English funnels. There are two objects
    now — the Romanian one differs in voice, bans, months, mail and cover —
    and every one of those branches means "this is the zodiac product", not
    "this is the English one".
    """
    return (profile is ZODIAC_PROFILE or profile is ZODIAC_RO_PROFILE
            or profile is ZODIAC_BG_PROFILE)


def _profile(funnel_slug):
    """The report profile for a funnel. Unregistered means kitchen.

    A `-test` twin reads the profile of the funnel it was cut from. The twin
    is that funnel — the same steps, the same copy, the same product — with
    its Stripe mode changed, so a sandbox purchase has to come back the same
    report a real one would. Falling through to kitchen instead would have
    made the twin a test of something nobody sells, and the failure is not
    one a test card would show you: the walk succeeds, the money moves, and
    the PDF is simply the wrong document.

    Only the fallback moves. A twin registered here in its own right keeps
    whatever it was registered with, and its section cache stays its own —
    that is keyed on the funnel, and the twin is a different funnel.
    """
    slug = funnel_slug or ""
    if slug not in PROFILES and config.is_test_slug(slug):
        slug = slug[:-len(config.TEST_SUFFIX)]
    return PROFILES.get(slug, KITCHEN_PROFILE)


def _words(profile):
    """The strings this profile prints itself.

    A profile that declares none prints the English, which is what every
    report printed before there was a second language.
    """
    return (profile or {}).get("words") or RENDER_WORDS


def _year_marks(profile):
    """(strongest, quiet) — the two prefixes this profile's year map uses."""
    words = _words(profile)
    return (words["year_strong"], words["year_quiet"])


def personal_sections(funnel_slug):
    """The sections written fresh for every purchase."""
    return _profile(funnel_slug)["personal"]


def cached_sections(funnel_slug):
    """The sections held per style — what warm_cache.py fills."""
    return _profile(funnel_slug)["cached"]



def _style_colors(style):
    """[(name, #RRGGBB)] for a style's power colours, in config order."""
    palette = ((style or {}).get("reveals") or {}).get("palette") or {}
    out = []
    for colour in (palette.get("colors") or []):
        code = _config_hex(colour)
        name = colour.get("name")
        if name and code:
            out.append((name.strip(), code.upper()))
    return out


def _palette_required(style):
    """The four colours, stated as the only ones this section may carry."""
    colours = _style_colors(style)
    if not colours:
        return None
    return (
        "REQUIRED — these are this reader's power colours. They are the only "
        "four the palette section may contain, in this order, with these "
        "names and these codes exactly:\n"
        + "\n".join("  %d. %s  %s" % (i + 1, name, code)
                    for i, (name, code) in enumerate(colours))
        + "\nCopy each name and each code character for character. Do not "
          "rename one, do not adjust a code, and do not add a fifth. What you "
          "write about them is what each is for.")


# Colours a reader was told are theirs are a promise the free page already
# made: the swatches were on screen before any money changed hands, with the
# codes withheld as the thing being sold. A generated section that renames one
# or prints a code we never chose is not a style note gone slightly wrong — it
# is the document contradicting the page that sold it.
def _verify_palette(data, style):
    want = _style_colors(style)
    if not want:
        return None
    got = data.get("colors") or []
    if len(got) != len(want):
        return ("palette carries %d colours, want the %d in the config"
                % (len(got), len(want)))
    for i, (name, code) in enumerate(want):
        mine = got[i] or {}
        if (mine.get("name") or "").strip().lower() != name.lower():
            return ("colors[%d].name is %r, want %r"
                    % (i, (mine.get("name") or "")[:40], name))
        clean = _hex(mine.get("hex") or "")
        if not clean or clean.upper() != code:
            return ("colors[%d].hex is %r, want %s"
                    % (i, (mine.get("hex") or "")[:12], code))
    return None


# The vocabulary this section is not written in. A palette that reaches for
# "matte" is describing paint, which is the other product.
PAINT_WORDS = re.compile(
    r"\b(matte|matt|satin|eggshell|gloss(y)?|sheen|swatch|undercoat|"
    r"emulsion|paint(ed|work)?)\b", re.IGNORECASE)


def _verify_no_paint(data, style):
    hit = PAINT_WORDS.search(json.dumps(data, ensure_ascii=False))
    return ("palette uses %r, which belongs to the other product"
            % hit.group(0)) if hit else None


ZODIAC_VERIFY = {
    "palette": (_verify_palette, _verify_no_paint),
}

ZODIAC_PROFILE["verify"] = ZODIAC_VERIFY
ZODIAC_RO_PROFILE["verify"] = ZODIAC_VERIFY
ZODIAC_BG_PROFILE["verify"] = ZODIAC_VERIFY
# The same two checks, and they are the same checks for the same reason: the
# persona palette is also four colours the reader was shown by name before
# they paid, and it is also not a paint chart.
PERSONA_PROFILE["verify"] = ZODIAC_VERIFY


def _verify_for(profile, style, months=None):
    """A check to run over a parsed section, or None.

    Bound to the style, because that is where the truth about the colours
    lives, and to the year, because that is where the truth about the months
    does. Both are facts this purchase already fixed; the section is checked
    against them rather than against itself.
    """
    rules = profile.get("verify")
    if not rules and not months:
        return None
    # Only where the profile asks. The English funnels have shipped without
    # this check since the first report, and a check they have never been held
    # to is a section they can now lose.
    marks = _year_marks(profile) if profile.get("verify_marks") else None
    # The twelve names this funnel's cards carry, which is exactly the keys of
    # the table the love prompt was built from. Read here rather than passed
    # in: the reader's own sign is in every combo and cancels out, so the
    # check needs the vocabulary and not the run.
    signs = tuple(profile.get("compatibility") or ())

    def verify(want, parsed):
        for section_id in want:
            for rule in (rules or {}).get(section_id) or ():
                problem = rule((parsed or {}).get(section_id) or {}, style)
                if problem:
                    return problem
            if section_id == "shopping" and months:
                problem = _verify_months(
                    (parsed or {}).get(section_id) or {}, months, marks)
                if problem:
                    return problem
            if section_id == "materials" and signs:
                problem = _verify_pairs(
                    (parsed or {}).get(section_id) or {}, signs)
                if problem:
                    return problem
        return None

    return verify

def _banned_hit(value, patterns):
    """The first banned phrase anywhere in a generated section, or None."""
    if not patterns:
        return None
    if isinstance(value, str):
        for rx in patterns:
            found = rx.search(value)
            if found:
                return found.group(0)
        return None
    if isinstance(value, dict):
        value = list(value.values())
    if isinstance(value, (list, tuple)):
        for item in value:
            hit = _banned_hit(item, patterns)
            if hit:
                return hit
    return None


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


def _sections_block(ids, spec=None):
    spec = SPEC if spec is None else spec
    return "\n\n".join(
        ["Return exactly this JSON object. Every key is required."]
        + [spec[section_id] for section_id in ids]
        + ["Wrap those in one object: {%s}."
           % ", ".join('"%s": {...}' % s for s in ids)]
    )


def _config_hex(colour):
    """`#rrggbb` for a config palette colour, or None.

    The free result draws the swatch and names the colour but does not print
    the code — that is the first thing the report is being paid for — so the
    config carries the value as an rgb triple and nothing the browser is sent
    is a paint code. This is the server side reading it back. `hex` is still
    accepted: config and engine sit behind a CDN and can be a version apart.
    """
    if not isinstance(colour, dict):
        return None
    triple = colour.get("rgb")
    if (isinstance(triple, (list, tuple)) and len(triple) == 3
            and all(isinstance(v, int) and 0 <= v <= 255 for v in triple)):
        return "#%02X%02X%02X" % tuple(triple)
    raw = colour.get("hex")
    return raw if isinstance(raw, str) and HEX_RE.match(raw) else None


def _stub_for(section_id, name, style=None, stubs=None, months=None,
              colors=None):
    """The placeholder for one section, or None if it has no placeholder.

    The mistakes stub is the one that cannot be purely generic any more. The
    free result hands over mistake #1 by name and says the other four are in
    here; if generation fails and this is what ships, a stub that opens on
    somebody else's first mistake breaks that promise on the one path where
    the reader is least inclined to be forgiving. So the promised one goes in
    front and the generic list fills in behind it.
    """
    stub = (STUBS if stubs is None else stubs).get(section_id)
    if stub is None:
        return None
    if isinstance(stub, dict) and stub.get("colors") == FROM_CONFIG:
        stub = dict(stub)
        stub["colors"] = _stub_colors(style, colors)
    if section_id == "mistakes":
        first = _mistake_one(style)
        if first:
            stub = dict(stub)
            # Four behind it: five items, inside the 4-6 the schema allows.
            stub["items"] = [first] + list(stub["items"])[:4]
    if section_id == "shopping" and (
            months or any(stubs is one for one in ZODIAC_STUB_SETS)):
        # The year stub carries positions rather than month names; the labels
        # go on here, from the same twelve the generated one is held to. A
        # stub that opened on January under a heading that says otherwise is
        # the failure being visible twice — and a stub that shipped the bare
        # positions would be the same failure with worse manners, so the clock
        # is read here rather than left unstamped when no year was passed in.
        stub = dict(stub)
        stub["items"] = [dict(row, name=label) for row, label
                         in zip(stub["items"], months or _year_labels())]
    return _fill(stub, name)


def _stub_colors(style, texts=None):
    """The four swatches for a palette stub, out of the style's own reveals.

    A config missing its palette — an older one, or one being written — falls
    back to four neutrals rather than to nothing: the section schema wants
    three to five colours, and a stub that fails validation is a section the
    reader simply does not get.

    The colour NAMES are the reader's own and are never translated — the free
    result showed them by name. What `texts` carries is the sentence about
    each one, which is prose and belongs to whatever language the report is
    written in.
    """
    texts = texts or ZODIAC_COLOR_TEXT
    colours = _style_colors(style)[:len(texts)]
    if not colours:
        colours = [("Everyday Ground", "#B9AE9C"), ("Signal", "#C0563A"),
                   ("Anchor", "#2E3440"), ("Rare Metal", "#C9A227")]
    out = []
    for index, (name, code) in enumerate(colours):
        role, when, where = texts[index]
        out.append({"name": name, "hex": code, "role": role,
                    "finish": when, "where": where})
    return out


def _mistake_one(style):
    """The mistake the free result gave away in full, or None.

    Same three fields as a row of the paid section, so it can be handed
    straight back to the model as item 1. A config without it — an older one,
    or another funnel — simply has no requirement to carry.
    """
    one = ((style or {}).get("reveals") or {}).get("mistake_one")
    if not isinstance(one, dict):
        return None
    out = {}
    for field in ("title", "body", "fix"):
        value = one.get(field)
        if not isinstance(value, str) or not value.strip():
            return None
        out[field] = value.strip()
    return out


def _style_block(style, name):
    lines = ["Style: %s" % name]
    blurb = (style or {}).get("blurb")
    if blurb:
        lines.append("What the style is: %s" % blurb)
    palette = ((style or {}).get("reveals") or {}).get("palette") or {}
    named = []
    for colour in (palette.get("colors") or []):
        code = _config_hex(colour)
        if colour.get("name") and code:
            named.append("%s %s" % (colour["name"], code))
    if named:
        # What they have and have not been given, stated separately, because
        # the palette section is sold on the difference: they have seen the
        # swatch and the name for nothing, and the code is the thing this
        # section is delivering. A model told they had already been shown the
        # codes writes around them.
        lines.append(
            "Palette already shown to them, as a swatch and a name only — "
            "they have NOT been given these codes: %s" % ", ".join(named))
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
        # A step owns several pairs from 3d on and the browser shows one of
        # them, so every variant has to be findable here — a chosen image this
        # could not name would drop out of the sequence silently and take its
        # colours with it. A bare `images` list is the pre-3d shape.
        pairs = step.get("pairs") or [{"images": step.get("images") or []}]
        for pair in pairs:
            for item in (pair.get("images") or []):
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
        # A step can ask what they would never have, and on that one the tap
        # means the opposite of every other tap in the list. Saying "chose"
        # for it would invite the model to build advice out of the one thing
        # they told us to keep away from.
        verb = ("explicitly rejected" if step.get("scoring") == "inverse"
                else "chose")
        lines.append("%d. %s — %s \"%s\"%s"
                     % (n, step.get("question") or step.get("id"), verb,
                        item.get("label") or image_id,
                        (": " + colours) if colours else ""))
    return lines


# How many style elements the free result screen shows. engine.js owns the
# grid; this owns knowing what was in it.
ELEMENTS_SHOWN = 6


def _pick_elements(cfg, choices, tag_scores):
    """The style elements the free result already put on screen.

    Recomputed here rather than taken from the browser, by the same rule
    engine.js picks with: an element whose image they tapped comes first, in
    config order, and the remaining slots go to whichever elements carry most
    of what they kept choosing. `choices` and `tag_scores` were both
    re-validated at checkout and the mapping is the config the server owns, so
    nothing in this is the client's word.

    The ids travel into the stored report, which is what lets the paid view
    show the same six. It cannot recompute them for itself: somebody returning
    from Stripe may land in a new tab with no quiz state at all.
    """
    items = [item for item in
             ((cfg.get("style_elements") or {}).get("items") or [])
             if isinstance(item, dict)]
    if not items or not choices:
        return []

    scores = tag_scores or {}
    picked, seen = [], set()
    for index, item in enumerate(items):
        if len(picked) >= ELEMENTS_SHOWN:
            break
        if item.get("image") in choices:
            seen.add(index)
            picked.append(item)

    if len(picked) < ELEMENTS_SHOWN:
        rest = [(index, item) for index, item in enumerate(items)
                if index not in seen]
        rest.sort(key=lambda row: (
            -sum(scores.get(tag, 0) for tag in (row[1].get("tags") or [])),
            row[0]))
        picked.extend(item for _, item in rest[:ELEMENTS_SHOWN - len(picked)])

    return picked


def _shown_elements(cfg, choices, tag_scores):
    """Just the labels, for the prompts."""
    return [item["label"] for item in _pick_elements(cfg, choices, tag_scores)
            if item.get("label")]


def _element_specs(cfg, choices, tag_scores):
    """`label — spec` for each shown element, for the section that has to
    deliver on them. The spec is the config's own wording, so the report and
    the chip under it cannot disagree about what was promised."""
    lines = []
    for item in _pick_elements(cfg, choices, tag_scores):
        label = item.get("label")
        if not label:
            continue
        spec = item.get("spec")
        lines.append("%s — %s" % (label, spec) if spec else label)
    return lines


def _choice_block(cfg, choices, tag_scores=None):
    """The choice sequence as context for a section that is not the palette."""
    lines = _choice_lines(cfg, choices)
    if not lines:
        return None
    elements = _shown_elements(cfg, choices, tag_scores)
    # They have already been told these are their elements, for free, before
    # being asked for anything. A section that then recommends around one of
    # them reads as the report going back on the free part of itself.
    shown = ("\nThey have already been shown these as their style elements: %s "
             "— specify these rather than contradict them.\n"
             % ", ".join(elements)) if elements else ""
    # Counted, not written out: the quiz was nine steps and is now thirteen,
    # and a number spelled into the prompt is a number that goes stale silently.
    return ("The %d choices they made, in order, with what was on screen:\n"
            % len(lines)
            + "\n".join(lines)
            + shown
            + "\nOne of these is a rejection rather than a preference, and it "
              "is marked as one — treat it as a thing to steer away from, "
              "never as a thing to recommend."
              "\nYou may refer to any of these directly — \"the marble you "
              "picked\", \"the brass you kept coming back to\" — but only where "
              "it earns its place in the advice.")


def _color_family(cfg, choices):
    """The palette family they picked at step 1, with its actual colours.

    Step 1 offers six boards and asks which palette pulls them in. That is a
    more specific answer than any tag can hold: `warm, wood, rustic` fits a
    moss-green board and a walnut board equally, and a report that averaged
    the two would hand a moss-green person a brown kitchen.

    Nothing is trusted from the client here. `choices` is a list of image ids
    the checkout already re-validated against this funnel, and the family is
    read back out of the config the server owns.
    """
    if not choices:
        return None
    by_id = {}
    for step in (cfg.get("swipe") or {}).get("steps") or []:
        pairs = step.get("pairs") or [{"images": step.get("images") or []}]
        for pair in pairs:
            for item in (pair.get("images") or []):
                if item.get("color_family"):
                    by_id[item.get("id")] = item
    for image_id in choices:
        item = by_id.get(image_id)
        if item:
            colours = ", ".join(
                "%s %s" % (c.get("name"), c.get("hex"))
                for c in (item.get("colors") or [])
                if c.get("name") and c.get("hex"))
            return item["color_family"], item.get("label") or "", colours
    return None


def _images_by_id(cfg):
    out = {}
    for step in (cfg.get("swipe") or {}).get("steps") or []:
        for pair in (step.get("pairs") or []):
            for item in (pair.get("images") or []):
                if isinstance(item, dict) and item.get("id"):
                    out[item["id"]] = item
    return out


def _chosen_on_step(cfg, choices, step_id):
    """The image id they tapped on one named step, or None."""
    if not choices or not step_id:
        return None
    for step in (cfg.get("swipe") or {}).get("steps") or []:
        if step.get("id") != step_id:
            continue
        here = set()
        for pair in (step.get("pairs") or []):
            for item in (pair.get("images") or []):
                if item.get("id"):
                    here.add(item["id"])
        for image_id in choices:
            if image_id in here:
                return image_id
    return None


# The service tags a funnel declares a purpose rule for. Empty for every
# funnel that declares none, which is how kitchen and zodiac v1 opt out of all
# of this without knowing it exists.
def _purpose_tags(cfg):
    block = ((cfg or {}).get("result_copy") or {}).get("purpose_map") or {}
    return block if isinstance(block, dict) else {}


def _purpose(cfg, choices):
    """What the reader said pulled them here, as a tag, or None.

    Read off the tags of the cards they tapped rather than off a named step:
    which question asks this belongs to the funnel, and the map is the list of
    answers this one knows what to do with.
    """
    known = _purpose_tags(cfg)
    if not known or not choices:
        return None
    images = _images_by_id(cfg)
    for image_id in choices:
        for tag in (images.get(image_id) or {}).get("tags") or ():
            if tag in known:
                return tag
    return None


# How the tag is said to a model. One line, in the reader's own terms, with
# the honesty clause attached: the quiz asked them to tap a picture, and a
# section that treated that as a diagnosis would be claiming a measurement
# nobody took.
PURPOSE_SAID = {
    "purpose_love": "love and relationships",
    "purpose_career": "career and money",
    "purpose_peace": "inner peace",
    "purpose_path": "the road ahead",
}


def _purpose_block(cfg, choices, section_id):
    """The purpose context line for one section, or None."""
    tag = _purpose(cfg, choices)
    said = PURPOSE_SAID.get(tag or "")
    if not said:
        return None
    return ("The reader said what pulled them here: %s — let the %s section "
            "lean into that where it is honest to, without pretending the "
            "quiz measured more than it did. They tapped a picture; they did "
            "not answer a questionnaire about it. Do not name the question or "
            "quote their answer back at them, and do not let this crowd out "
            "what the section is for." % (said, section_id))


def _visuals(cfg, result_style, choices):
    """The photographs this report is illustrated with, as image ids.

    The palette board they chose at the colour step, and the two surfaces —
    worktop and backsplash — they picked. Resolved here and stored with the
    report for the same reason the style elements are: nearly every reader
    arrives at the paid view through a Stripe redirect, in a page with no quiz
    state left to resolve them from, and the PDF is built on a server that
    never had any. Where a choice is missing the config's per-style default
    stands in, so the pictures always belong to the style even when they
    cannot belong to the person.

    Ids rather than paths: the caller that draws them owns how a path is
    built, and a stored URL is a stored deploy layout.
    """
    block = ((cfg.get("report") or {}).get("visuals")) or {}
    known = _images_by_id(cfg)
    fallback = (block.get("defaults") or {}).get(result_style) or {}

    def pick(value):
        return value if value in known else None

    out = {}
    board = (pick(_chosen_on_step(cfg, choices, block.get("moodboard_step")))
             or pick(fallback.get("moodboard")))
    if board:
        out["moodboard"] = board

    mats = []
    defaults = fallback.get("materials") or []
    for i, step_id in enumerate(block.get("material_steps") or []):
        one = (pick(_chosen_on_step(cfg, choices, step_id))
               or pick(defaults[i] if i < len(defaults) else None))
        if one:
            mats.append(one)
    if mats:
        out["materials"] = mats

    # A funnel may instead name one photograph per report section, and two for
    # the page's own header. Resolved from taps alone, with no per-style
    # fallback: this set is the report keeping the promise the free page makes
    # when it says it read them off their own choices, and a stock image under
    # that claim is the claim being false. A step they somehow never reached
    # simply leaves its section without a picture.
    sections = {}
    for section_id, step_id in (block.get("section_steps") or {}).items():
        one = pick(_chosen_on_step(cfg, choices, step_id))
        if one:
            sections[section_id] = one
    if sections:
        out["sections"] = sections

    hero = {}
    for slot, step_id in (block.get("hero") or {}).items():
        if not slot.endswith("_step"):
            continue
        one = pick(_chosen_on_step(cfg, choices, step_id))
        if one:
            hero[slot[:-len("_step")]] = one
    if hero:
        out["hero"] = hero

    # And the whole run, in the order they tapped it, on a funnel that asks
    # for the contact sheet. The free page shows the reader every frame they
    # chose under "read from your taps"; the page they paid for and the PDF
    # have to show the same grid, and neither has a run to read it off — one
    # is opened from a link in a mail and the other is built on a server. Ids
    # only, and only ids this config knows.
    if block.get("taps"):
        taps = [image_id for image_id in (choices or []) if image_id in known]
        if taps:
            out["taps"] = taps
    return out or None


def _palette_block(cfg, choices):
    """The palette instruction, when we know what they actually chose."""
    lines = _choice_lines(cfg, choices)
    if not lines:
        return None
    # The anchor goes first and is stated as a requirement rather than as
    # context. Everything after it is about which of their colours does what;
    # this is about which family the whole palette lives in, and it is not
    # one signal among twelve any more.
    family = _color_family(cfg, choices)
    anchor = ""
    if family:
        family_id, label, colours = family
        anchor = (
            "The user's chosen color family is %s (%s). The 60/30/10 palette "
            "MUST be built around this family — the dominant and secondary "
            "colors come from it; only the accent may depart.\n\n"
            % (family_id, colours or label))
    return (
        anchor +
        "This person's own choices, in order, with the colours that were in "
        "front of them:\n" + "\n".join(lines) + "\n\n"
        "Build the palette out of THESE colours. Rules:\n"
        "- The colour family above is the anchor. The 60% and the 30% come "
        "out of it. A rule below that would pull the dominant colour out of "
        "that family loses to this one.\n"
        "- Any line marked as rejected is the one thing they told us to keep "
        "out of the room. Its colours are not palette candidates; use it only "
        "to rule a direction out.\n"
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


# --- the twelve months, counted from this one ------------------------------
#
# The year map used to run January to December, which is a calendar rather
# than a reading: somebody who buys in September is handed eight months that
# have already been and four that have not. It runs from the month they
# bought in now, twelve of them, and the year is on every label because four
# of them are in the next one.
#
# Server date, UTC. A reader a timezone either side of the boundary can be a
# few hours out of step with their own phone on the last night of a month;
# what they must never see is a map that opens on a month that is over.

MONTH_ABBR = ("Jan", "Feb", "Mar", "Apr", "May", "Jun",
              "Jul", "Aug", "Sep", "Oct", "Nov", "Dec")

YEAR_MONTHS = 12


def _year_labels(today=None):
    """["Aug 2026", "Sep 2026", ... "Jul 2027"], starting from this month."""
    day = today or datetime.datetime.now(datetime.timezone.utc).date()
    year, month = day.year, day.month
    out = []
    for _ in range(YEAR_MONTHS):
        out.append("%s %d" % (MONTH_ABBR[month - 1], year))
        month += 1
        if month > 12:
            month, year = 1, year + 1
    return out


# The same twelve, said the way a Romanian calendar says them. Bound to the
# profile rather than to a locale lookup: the labels are handed to the model as
# the only twelve it may use and are then checked back against it by
# `_verify_months`, so the one thing that matters is that the writer and the
# checker read them from the same place.
MONTH_ABBR_RO = ("ian.", "feb.", "mar.", "apr.", "mai", "iun.",
                 "iul.", "aug.", "sept.", "oct.", "nov.", "dec.")


def _year_labels_ro(today=None):
    """["aug. 2026", "sept. 2026", ... "iul. 2027"], starting from this month."""
    day = today or datetime.datetime.now(datetime.timezone.utc).date()
    year, month = day.year, day.month
    out = []
    for _ in range(YEAR_MONTHS):
        out.append("%s %d" % (MONTH_ABBR_RO[month - 1], year))
        month += 1
        if month > 12:
            month, year = 1, year + 1
    return out


# And again for /zodiac-bg. Bulgarian abbreviates its months with a full
# stop, like Romanian and unlike English, and "май" is short enough that it
# takes none. Bound to the profile for the same reason: the writer and the
# checker have to read the twelve labels off the same place.
MONTH_ABBR_BG = ("яну.", "фев.", "мар.", "апр.", "май", "юни",
                 "юли", "авг.", "сеп.", "окт.", "ное.", "дек.")


def _year_labels_bg(today=None):
    """["авг. 2026", "сеп. 2026", ... "юли 2027"], starting from this month."""
    day = today or datetime.datetime.now(datetime.timezone.utc).date()
    year, month = day.year, day.month
    out = []
    for _ in range(YEAR_MONTHS):
        out.append("%s %d" % (MONTH_ABBR_BG[month - 1], year))
        month += 1
        if month > 12:
            month, year = 1, year + 1
    return out


def _months_for(profile, today=None):
    """The twelve labels this profile's year map runs on, or None.

    Resolved here rather than held on the profile as a value. The name is
    looked up when it is called, so a caller that holds the clock still by
    replacing this module's `_year_labels` is honoured — which is the only way
    a report generated at a fixed date can be asserted at all. A profile
    carrying the function object would have captured the real one at import
    and quietly ignored the substitution.
    """
    if profile is ZODIAC_RO_PROFILE:
        return _year_labels_ro(today)
    if profile is ZODIAC_BG_PROFILE:
        return _year_labels_bg(today)
    if _is_zodiac(profile) or profile is PERSONA_PROFILE:
        return _year_labels(today)
    return None


def _year_block(months):
    """The twelve labels, as the only twelve the year section may use."""
    if not months:
        return None
    return (
        "REQUIRED — this reader's year starts now, not in January. These are "
        "the twelve months, in this order, and they are the twelve `name` "
        "values you must send, copied exactly, including the year:\n"
        + "\n".join("  %2d. %s" % (n, label)
                     for n, label in enumerate(months, 1))
        + "\nTwelve items, in that order, no others and none missing. Write "
          "the year as it is written above. Never write a month that is not "
          "on this list, and never reorder them.")


# How many of the twelve carry each mark. The shape asks for exactly these
# two numbers, so a check that polices the marks has to police the same two.
YEAR_STRONG = 3
YEAR_QUIET = 1


# One compiled word-boundary pattern per sign name, built once per table.
# `combo` is prose — "Rac + Scorpion", "Leo + a fire sign" — so a plain `in`
# would find "Leu" inside a longer word and a sign named nowhere would look
# named. Keyed by the id of the table it came from, which is a module-level
# constant per language and never rebuilt.
_SIGN_RES = {}


def _sign_res(signs):
    key = id(signs)
    if key not in _SIGN_RES:
        _SIGN_RES[key] = [
            (name, re.compile(r"\b%s\b" % re.escape(name), re.IGNORECASE))
            for name in signs]
    return _SIGN_RES[key]


def _verify_pairs(data, signs):
    """The love section's four pairings against each other, or None.

    The shape asks for four pairings, two that work and two that cost, and
    the table behind the prompt names three signs: two magnetic and one
    draining. The fourth is the model's own choice — and nothing said it had
    to be a sign it had not used yet, so a Romanian report came back naming
    the one draining sign twice, under two different paragraphs.

    The existing checks could not see it. `_v_materials` counts verdicts and
    is satisfied by two of each; the character ceilings and the banned list
    are about words rather than about which sign is in them. A reader looking
    at the page sees the same name twice with two different readings under
    it, which is the section arguing with itself.

    Both languages, because the English path has the same gap and has only
    ever been saved by the model's own preference.

    A pairing that names no sign at all is not judged — a generic combo is a
    different fault and one this check has no business inventing a verdict on.
    """
    if not signs:
        return None
    rows = []
    for index, pair in enumerate(data.get("pairs") or [], 1):
        combo = str((pair or {}).get("combo") or "")
        named = frozenset(name for name, rx in _sign_res(signs)
                          if rx.search(combo))
        if named:
            rows.append((index, named))
    if not rows:
        return None
    # The reader's own sign leads every combo, so it is in every row and
    # cancels out. Inferred rather than passed in, and only used to keep the
    # refusal readable: naming it back at the model as half the duplicate
    # would point at the one sign that is supposed to repeat.
    own = frozenset.intersection(*[named for _i, named in rows])
    seen = {}
    for index, named in rows:
        if named in seen:
            partner = named - own or named
            return ("pairing %d names %s, which pairing %d already used — the "
                    "four pairings name four different signs beside this "
                    "reader's own, and the second draining one is yours to "
                    "choose from the signs not yet used"
                    % (index, " and ".join(sorted(partner)), seen[named]))
        seen[named] = index
    return None


def _verify_months(data, months, marks=None):
    """The year section's labels against the twelve it was handed, or None.

    A shape-valid year map that opens in January is the document contradicting
    the page that sold it, and the shape validators cannot see it — they
    police the form, and every month name is a well-formed string.

    `marks` is (strongest, quiet), and only a profile that asks for it passes
    a pair. Given one, the notes have to open with those exact two prefixes,
    three times and once — which is how a Romanian year map that came back
    marked "Strongest month:" is caught here rather than in the PDF.
    """
    if not months:
        return None
    got = [str((row or {}).get("name") or "").strip()
           for row in (data.get("items") or [])]
    if got != list(months):
        if len(got) != len(months):
            return ("the year needs exactly %d months and %d arrived — they "
                    "are %s, in that order" % (len(months), len(got),
                                               ", ".join(months)))
        wrong = next(n for n, (a, b) in enumerate(zip(got, months), 1)
                     if a != b)
        return ("month %d is %r and must be %r — the twelve `name` values are "
                "%s, in that order, copied exactly"
                % (wrong, got[wrong - 1], months[wrong - 1],
                   ", ".join(months)))
    if marks:
        strong, quiet = marks
        notes = [str((row or {}).get("priority_note") or "").lstrip()
                 for row in (data.get("items") or [])]
        counts = (sum(1 for note in notes if note.startswith(strong)),
                  sum(1 for note in notes if note.startswith(quiet)))
        if counts != (YEAR_STRONG, YEAR_QUIET):
            return ("%d notes open with %r and %d with %r — it must be "
                    "exactly %d and %d, each prefix copied exactly as written"
                    % (counts[0], strong, counts[1], quiet,
                       YEAR_STRONG, YEAR_QUIET))
    return None


# --- the reader's own sign -------------------------------------------------
#
# Recoverable from the run without storing anything new: the sign step's
# image ids are `sign_<name>`, and the season step's tag is what chose which
# three of them were on screen. Both are already in `choices`.

SIGN_PREFIX = "sign_"
CUSP_ID = "sign_cusp"

SEASON_TAGS = ("spring", "summer", "autumn", "winter")


def _season_of(cfg, choices):
    """(tag, label) for the season they tapped, or (None, None)."""
    chosen = _chosen_on_step(cfg, choices, "season")
    if not chosen:
        return None, None
    item = _images_by_id(cfg).get(chosen) or {}
    for tag in item.get("tags") or []:
        if tag in SEASON_TAGS:
            return tag, (item.get("label") or tag.title())
    return None, None


def _season_signs(cfg, season_tag):
    """The sign labels that season's grid offers, in the order it shows them.

    Read off the adaptive step rather than from a table here, so a config that
    moves a sign between seasons does not leave this file quietly wrong.
    """
    for step in (cfg.get("swipe") or {}).get("steps") or []:
        if step.get("id") != "sign":
            continue
        rule = step.get("adaptive") or {}
        variants = rule.get("variants") or {}
        wanted = variants.get(season_tag) or variants.get("default")
        for pair in step.get("pairs") or []:
            if pair.get("id") != wanted:
                continue
            return [i.get("label") for i in pair.get("images") or []
                    if i.get("id") != CUSP_ID and i.get("label")]
    return []


def _sign(cfg, choices):
    """What this run says about the reader's sign, or None.

    `cusp` is the honest case and the reason this returns a dict rather than a
    name: somebody who tapped "Born on a cusp" told us their season and
    nothing finer, so the report has to speak to the blend of that season's
    energies and must never settle on one sign for them.
    """
    chosen = _chosen_on_step(cfg, choices, "sign")
    if not chosen or not str(chosen).startswith(SIGN_PREFIX):
        return None
    season, season_label = _season_of(cfg, choices)
    item = _images_by_id(cfg).get(chosen) or {}
    out = {
        "id": chosen,
        "cusp": chosen == CUSP_ID,
        "season": season,
        "season_label": season_label,
        "neighbours": _season_signs(cfg, season) if season else [],
        "tags": list(item.get("tags") or []),
    }
    out["label"] = None if out["cusp"] else (
        item.get("label") or chosen[len(SIGN_PREFIX):].title())
    return out


def _sign_block(cfg, choices):
    """How the sign is handed to the model, or None when there is no sign."""
    sign = _sign(cfg, choices)
    if not sign:
        return None
    if not sign["cusp"]:
        line = ("REQUIRED — this reader's sign is %s. Name it, in that word, "
                "at least once in this section, and write the section as "
                "though you are writing about a %s rather than about people "
                "in general." % (sign["label"], sign["label"]))
        if sign["tags"]:
            line += (" Their sign carries these energies: %s."
                     % ", ".join(sign["tags"]))
        return line

    # The cusp. Everything below is deliberately what we do NOT know.
    where = sign["season_label"] or "their season"
    span = sign["neighbours"]
    span_text = (" — the signs that season covers are %s"
                 % ", ".join(span)) if span else ""
    return (
        "REQUIRED — this reader was born on a cusp and did not give a single "
        "sign. They told us their season: %s%s. Write to somebody carrying two "
        "adjacent energies at once rather than one: say \"born on a cusp\" in "
        "this section, describe the blend and what it costs to sit between "
        "two things, and name the season. Never assert that they are any one "
        "of those signs, never pick one for them, and never ask them for a "
        "birth date." % (where, span_text))


# --- the reader's own subtype ----------------------------------------------
#
# The other half of static/js/result_zodiac.js's `profileOf`, in Python.
#
# It exists twice because it is needed in two places that cannot reach each
# other: the free page computes it in the browser out of a live run, and the
# delivered page, the PDF and the mail are all built from a stored report by
# something that never had one. So the block is computed once here, while the
# run still exists, and carried on the report — and every tiebreak below is
# the module's, stated rather than left to array order, because a name
# resolved one way and a rarity counted another is a number about nothing.
#
# The tables themselves are in the funnel config, written into both funnels
# from one source by scripts/gen_profile_rarity.py.

ELEMENT_TAGS = ("fire", "earth", "air", "water")
ENERGY_TAGS = ("sun", "moon")
TONE_TAGS = ("bold", "calm", "mystic")

ELEMENT_LABEL = {"fire": "Fire", "earth": "Earth", "air": "Air",
                 "water": "Water"}
ENERGY_LABEL = {"sun": "Sun", "moon": "Moon"}

# The same words for the funnel that says them in Romanian. They reach the
# reader in three places built from the stored card — the delivered page, the
# PDF cover and the mail header — so they are read off the profile rather than
# hardcoded here. The free result page computes its own copy of this card in
# static/js/result_zodiac.js and still says "Water" there; that module serves
# every funnel and translating it is its own change.
ELEMENT_LABEL_RO = {"fire": "Foc", "earth": "Pământ", "air": "Aer",
                    "water": "Apă"}
ENERGY_LABEL_RO = {"sun": "Soare", "moon": "Lună"}

ZODIAC_PROFILE["element_labels"] = ELEMENT_LABEL
ZODIAC_PROFILE["energy_labels"] = ENERGY_LABEL
ZODIAC_RO_PROFILE["element_labels"] = ELEMENT_LABEL_RO
ZODIAC_RO_PROFILE["energy_labels"] = ENERGY_LABEL_RO

# The same words again for the funnel that says them in Bulgarian. These are
# the four and the two that funnels/zodiac-bg.json also carries in
# `result_copy.labels`, and the suite pins the two files to each other: the
# page and the document have to name a reader's element with the same word.
ELEMENT_LABEL_BG = {"fire": "Огън", "earth": "Земя", "air": "Въздух",
                    "water": "Вода"}
ENERGY_LABEL_BG = {"sun": "Слънце", "moon": "Луна"}

ZODIAC_BG_PROFILE["element_labels"] = ELEMENT_LABEL_BG
ZODIAC_BG_PROFILE["energy_labels"] = ENERGY_LABEL_BG

ELEMENT_INK = dict((tag, ink) for tag, _label, ink in [
    ("fire", "Fire", "#E08A3C"), ("earth", "Earth", "#7E9B5E"),
    ("air", "Air", "#9CC3DF"), ("water", "Water", "#4E8FA0")])


def _profile_table(cfg):
    """`result_copy.profile`, or None on a funnel that carries no tables."""
    table = ((cfg or {}).get("result_copy") or {}).get("profile")
    return table if isinstance(table, dict) else None


def _scored(tag_scores, tags):
    """Those tags as a dict, with anything below zero read as zero.

    A negative score is a tap the reader told us to keep away from on the
    inverse step. It is not a negative share of who they are.
    """
    scores = tag_scores or {}
    return dict((tag, max(0, scores.get(tag, 0) or 0)) for tag in tags)


def _between(left, right):
    """A dot's place between two poles: 0 hard left, 100 hard right.

    Nothing measured on either side is dead centre rather than zero — a run
    that scored neither has not leant left, it has not leant.
    """
    total = left + right
    if not total:
        return 50
    return int(round(100.0 * right / total))


def _split(tag_scores, labels=None):
    """The four elements as whole percents that add to a hundred.

    Rounding each share on its own gives 33/33/17/16 as readily as not, and a
    caption whose numbers sum to 99 is the one thing on that card a reader can
    check for themselves. Largest remainder, ties to the declared order.
    """
    scores = _scored(tag_scores, ELEMENT_TAGS)
    raw = [scores[tag] for tag in ELEMENT_TAGS]
    total = sum(raw)
    if not total:
        pcts = [int(round(100.0 / len(raw)))] * len(raw)
    else:
        exact = [100.0 * value / total for value in raw]
        pcts = [int(math.floor(value)) for value in exact]
        owed = 100 - sum(pcts)
        order = sorted(range(len(exact)),
                       key=lambda i: (-(exact[i] % 1), i))
        for i in order[:max(0, owed)]:
            pcts[i] += 1
    names = labels or ELEMENT_LABEL
    return [{"tag": tag, "name": names[tag], "pct": pcts[i],
             "color": ELEMENT_INK[tag]}
            for i, tag in enumerate(ELEMENT_TAGS)]


_TOKEN_RE = re.compile(r"\{(\w+)\}")


def _fill_tokens(text, words):
    if not text:
        return ""
    return _TOKEN_RE.sub(
        lambda m: words[m.group(1)] if m.group(1) in words else m.group(0),
        str(text))


def _reader_profile(cfg, style, tag_scores, sign, cusp=False,
                    elements=None, energies=None):
    """The whole hero card for one run, or None when it cannot be resolved.

    None on a funnel with no tables, on a run with no tallies, and on any
    combination the tables do not name — all of which leave the report exactly
    as it was, which is the page every reader before today was sent to.
    """
    table = _profile_table(cfg)
    if not table or not table.get("subtypes") or not tag_scores:
        return None
    element_name = elements or ELEMENT_LABEL
    energy_name = energies or ENERGY_LABEL
    tags = (style or {}).get("tags") or []
    style_id = (style or {}).get("id") or ""
    primary = next((tag for tag in tags if tag in ELEMENT_TAGS), None)
    if not primary:
        return None

    elements = _scored(tag_scores, ELEMENT_TAGS)
    rest = [tag for tag in ELEMENT_TAGS if tag != primary]
    second = max(rest, key=lambda tag: (elements[tag], -rest.index(tag)))

    energies = _scored(tag_scores, ENERGY_TAGS)
    if energies["sun"] > energies["moon"]:
        energy = "sun"
    elif energies["moon"] > energies["sun"]:
        energy = "moon"
    else:
        # Dead level: the archetype's own energy carries it, because the name
        # beside it says both and a tie broken by list order can print an
        # energy the archetype does not hold.
        energy = next((tag for tag in tags if tag in ENERGY_TAGS),
                      ENERGY_TAGS[0])

    name = (((table["subtypes"].get(style_id) or {}).get(second) or {})
            .get(energy))
    if not name:
        return None

    bare = re.sub(r"^The\s+", "", name)
    rarity = (((table.get("rarity") or {}).get(style_id) or {}).get(second)
              or {}).get(energy) or 0
    split = _split(tag_scores, element_name)
    tone = _scored(tag_scores, TONE_TAGS)
    at = {
        "energy": _between(energies["sun"], energies["moon"]),
        "tone": _between(tone["bold"], tone["calm"]),
        # There is no `grounded` tag and there never was one: `mystic` is the
        # single tag this vocabulary spends on the otherworldly, and bold and
        # calm are what it spends on everything else.
        "depth": _between(tone["mystic"], tone["bold"] + tone["calm"]),
    }

    words = {
        "sign": sign or "",
        "subtype": name,
        "subtype_bare": bare,
        "subtype_article": "an" if bare[:1].upper() in "AEIOU" else "a",
        "element": element_name[primary],
        "second": element_name[second],
        "energy": energy_name[energy],
        "n": str(rarity),
    }
    for cell in split:
        words[cell["tag"]] = str(cell["pct"])

    cross_key = sign if sign else ("cusp" if cusp else "")
    return {
        "archetype": style_id,
        "primary": primary,
        "second": second,
        "energy": energy,
        "sign": sign or "",
        "subtype": name,
        "subtype_bare": bare,
        "rarity": rarity,
        "words": words,
        # The formula loses its leading separator rather than printing one
        # when a run never reached the sign step.
        "formula": re.sub(r"^\s*·\s*", "",
                          _fill_tokens(table.get("formula"), words)),
        "rarity_line": (_fill_tokens(table.get("rarity_line"), words)
                        if rarity else ""),
        "cross_line": ((table.get("sign_cross") or {}).get(cross_key)
                       or {}).get(primary, ""),
        "split": split,
        "split_caption": _fill_tokens(table.get("split_caption"), words),
        "scales": [{"id": row.get("id"), "left": row.get("left"),
                    "right": row.get("right"),
                    "at": at.get(row.get("id"), 50)}
                   for row in (table.get("scales") or [])],
    }


# --- the persona reader's own card ------------------------------------------
#
# The same idea as `_reader_profile` above and none of the same words. That
# one is built on the zodiac vocabulary — fire/earth/air/water, sun/moon —
# and returns None the moment it is handed a run that has none of those tags,
# which is every persona run there has ever been. So the delivered persona
# page had nothing to draw and fell back to the plain card: the head, the
# inlay and the legend existed, on the free page, where they were being given
# away.
#
# What is built here is the block the free page already computes in the
# browser, computed again on the server where the browser cannot help — the
# delivered page is opened from a link in a mail, in a tab that never ran the
# quiz, and the PDF is drawn on a machine that never had one either.
#
# It has to agree with `profileOf` in static/js/result_persona.js field for
# field, because both of them feed the same `richHero`. Where that file makes
# a choice — the runner-up excluding the archetype's own axis, a dead-level
# energy falling to the archetype's own, largest-remainder percentages — this
# makes the same one, and the suite walks all eight personas to prove the two
# agree rather than trusting that they do.

PERSONA_AXES = ("drive", "anchor", "wave", "prism")
PERSONA_ENERGIES = ("outer", "inner")

# The tone axis as this funnel tags it. There is no `light` tag: `deep` is the
# one word the vocabulary spends on what sits under the surface and bold and
# calm are what it spends on everything above, so the light-to-deep scale
# reads deep against the sum of the other two.
PERSONA_TONES = ("bold", "calm", "deep")

PERSONA_AXIS_LABEL = {"drive": "Drive", "anchor": "Anchor",
                      "wave": "Wave", "prism": "Prism"}

# The gallery's own families, so a bar and its frames are the same colour.
PERSONA_AXIS_INK = {"drive": "#F0845A", "anchor": "#9BB08A",
                    "wave": "#4EDDC4", "prism": "#A98CE8"}

PERSONA_ENERGY_LABEL = {"outer": "Outer", "inner": "Inner"}

# The three steps the reading quotes back. The claim the funnel makes is that
# the shapes unlock something, so the paragraph has to name what they actually
# reached for — the shape they opened on, the chapter they said they are in,
# and the fork they follow.
PERSONA_NARRATIVE_STEPS = ("now", "chapter", "forks")

PERSONA_TOTEM_DIR = "/static/galleries/persona/totem_"


def _persona_split(tag_scores):
    """The four axes as whole percents that add to a hundred.

    `_split` above does this for the zodiac elements and is keyed on them; the
    arithmetic is the same and the tags are not. Largest remainder, ties to
    the declared order, so the caption a reader can add up themselves does.
    """
    scores = _scored(tag_scores, PERSONA_AXES)
    raw = [scores[tag] for tag in PERSONA_AXES]
    total = sum(raw)
    if not total:
        pcts = [int(round(100.0 / len(raw)))] * len(raw)
    else:
        exact = [100.0 * value / total for value in raw]
        pcts = [int(math.floor(value)) for value in exact]
        owed = 100 - sum(pcts)
        order = sorted(range(len(exact)), key=lambda i: (-(exact[i] % 1), i))
        for i in order[:max(0, owed)]:
            pcts[i] += 1
    return [{"tag": tag, "name": PERSONA_AXIS_LABEL[tag], "pct": pcts[i],
             "color": PERSONA_AXIS_INK[tag]}
            for i, tag in enumerate(PERSONA_AXES)]


def _persona_traits(table, split):
    """The four bars, named the way this funnel's own table names them."""
    names = {}
    for row in (table.get("traits") or []):
        if isinstance(row, dict) and row.get("tag"):
            names[row["tag"]] = row.get("name") or row["tag"]
    return [{"tag": cell["tag"],
             "name": names.get(cell["tag"])
             or PERSONA_AXIS_LABEL.get(cell["tag"], cell["tag"]),
             "pct": cell["pct"]}
            for cell in split]


def _persona_picks(cfg, choices):
    """The labels this run actually tapped, by step id.

    The server has image ids where the browser had the images, so the labels
    are looked back up through the config the same way `imageById` does.
    """
    if not choices:
        return {}
    taken = set(choices)
    out = {}
    for step in ((cfg.get("swipe") or {}).get("steps") or []):
        if not isinstance(step, dict):
            continue
        # The same fallback the rest of this module uses for a step that
        # carries its images directly rather than in pairs.
        pairs = step.get("pairs") or [{"images": step.get("images") or []}]
        for pair in pairs:
            for item in (pair.get("images") or []):
                if (isinstance(item, dict) and item.get("id") in taken
                        and item.get("label")):
                    out[step.get("id")] = item["label"]
    return out


def _persona_narrative(cfg, choices, name):
    """The paragraph, woven from what they actually picked.

    Parts rather than a string, because the labels are set in italics and a
    string would have to be parsed back apart to do it — the same list of
    `{"text": ...}` / `{"em": ...}` the browser builds, so one renderer draws
    either.
    """
    picks = _persona_picks(cfg, choices)
    got = [picks[step] for step in PERSONA_NARRATIVE_STEPS if picks.get(step)]
    if not got:
        return None
    parts = [{"text": "You opened on "}, {"em": got[0].lower()}]
    if len(got) > 1:
        parts.append({"text": ", said the chapter you are in is "})
        parts.append({"em": got[1].lower()})
    if len(got) > 2:
        parts.append({"text": ", and when it forks you follow "})
        parts.append({"em": got[2].lower()})
    parts.append({"text": ". That is %s, and the rest of this page is what "
                          "those three unlock." % name})
    return parts


def _persona_profile(cfg, style, tag_scores, choices, today=None):
    """The whole hero card for one persona run, or None.

    None on a funnel with no tables, a run with no tallies, and any
    combination the tables do not name — all of which leave the report exactly
    as it was.
    """
    table = _profile_table(cfg)
    if not table or not table.get("subtypes") or not tag_scores:
        return None

    style_id = (style or {}).get("id") or ""
    tags = (style or {}).get("tags") or []
    scores = _scored(tag_scores, PERSONA_AXES)

    # The axis the hero names is the archetype's own, not the highest scorer.
    # An archetype is won on its tags, so a reader can out-score their own
    # axis and still be what they are; the bars below still show all four.
    primary = next((tag for tag in PERSONA_AXES if tag in tags), None)
    if not primary:
        return None
    rest = [tag for tag in PERSONA_AXES if tag != primary]
    second = max(rest, key=lambda tag: (scores[tag], -rest.index(tag)))

    energies = _scored(tag_scores, PERSONA_ENERGIES)
    if energies["outer"] > energies["inner"]:
        energy = "outer"
    elif energies["inner"] > energies["outer"]:
        energy = "inner"
    else:
        # Dead level: the archetype's own energy carries it, because the name
        # beside it says both and a tie broken by list order can print an
        # energy the archetype does not hold.
        energy = next((tag for tag in PERSONA_ENERGIES if tag in tags),
                      PERSONA_ENERGIES[0])

    name = (table["subtypes"].get(style_id) or {}).get(energy)
    if not name:
        return None
    bare = re.sub(r"^The\s+", "", name)
    essence = ((table.get("essence") or {}).get(style_id) or {}).get(energy, "")
    rarity = ((table.get("rarity") or {}).get(style_id) or {}).get(energy) or 0
    rarer = (((table.get("rarer_than") or {}).get(style_id) or {})
             .get(energy) or 0)

    split = _persona_split(tag_scores)
    tone = _scored(tag_scores, PERSONA_TONES)
    at = {
        "energy": _between(energies["outer"], energies["inner"]),
        "tone": _between(tone["bold"], tone["calm"]),
        "depth": _between(tone["bold"] + tone["calm"], tone["deep"]),
    }

    year = _year_labels(today)
    words = {
        "first": year[0],
        "last": year[-1],
        "subtype": name,
        "subtype_bare": bare,
        "subtype_article": "an" if bare[:1].upper() in "AEIOU" else "a",
        "axis": PERSONA_AXIS_LABEL.get(primary, primary),
        "second": PERSONA_AXIS_LABEL.get(second, second),
        "energy": PERSONA_ENERGY_LABEL.get(energy, energy),
        "n": str(rarity),
        "rarer": str(rarer),
    }
    for cell in split:
        words[cell["tag"]] = str(cell["pct"])

    return {
        "archetype": style_id,
        "primary": primary,
        "second": second,
        "energy": energy,
        "subtype": name,
        "subtype_bare": bare,
        "essence": essence,
        "rarity": rarity,
        "rarer": rarer,
        "totem": "%s%s_%s.webp" % (PERSONA_TOTEM_DIR, style_id, energy),
        # The persona as one string, which is what the share card, the share
        # page and the share event are all keyed by.
        "persona_slug": "%s_%s" % (style_id, energy),
        "narrative": _persona_narrative(cfg, choices, name),
        "traits": _persona_traits(table, split),
        "words": words,
        # The formula loses its leading separator rather than printing one
        # when a run never reached the opening step.
        "formula": re.sub(r"^\s*\u00b7\s*", "",
                          _fill_tokens(table.get("formula"), words)),
        "rarity_line": (_fill_tokens(table.get("rarity_line"), words)
                        if rarer else ""),
        "split": split,
        "split_caption": _fill_tokens(table.get("split_caption"), words),
        "scales": [{"id": row.get("id"), "left": row.get("left"),
                    "right": row.get("right"),
                    "at": at.get(row.get("id"), 50)}
                   for row in (table.get("scales") or [])],
    }


def _persona_pairings(cfg, card):
    """The buyer's own row of the pairings table, or None.

    Read off the config rather than left to the model. The paywall promises
    which profiles fit and which one costs, by name, and a model asked for
    four pairings without being told which four will happily supply four —
    different ones for every buyer of the same persona.
    """
    table = (cfg or {}).get("pairings") or {}
    row = table.get((card or {}).get("persona_slug") or "")
    if not isinstance(row, dict):
        return None
    names = _profile_table(cfg) or {}
    subtypes = names.get("subtypes") or {}
    out = []
    for slug, verdict in row.items():
        if not isinstance(verdict, dict):
            continue
        archetype, _, energy = slug.rpartition("_")
        name = (subtypes.get(archetype) or {}).get(energy) or slug
        out.append({"slug": slug, "name": name,
                    "verdict": verdict.get("verdict") or "",
                    "line": verdict.get("line") or ""})
    return out or None


def _persona_pairs_block(cfg, card):
    """Four pairings, stated, with the reader's own name leading each.

    Two that work and two that cost, which is the shape the section is
    validated against and the promise the card on the paywall made. Chosen
    here rather than by the model: the table is the product's own judgement
    and the model's job is to say what being inside one is like.
    """
    rows = _persona_pairings(cfg, card)
    if not rows:
        return None
    mine = (card or {}).get("subtype") or ""
    works = [r for r in rows if r["verdict"] == "works" and r["slug"]
             != (card or {}).get("persona_slug")]
    avoid = [r for r in rows if r["verdict"] == "avoid" and r["slug"]
             != (card or {}).get("persona_slug")]
    picked = works[:2] + avoid[:2]
    if len(picked) < 4:
        return None
    return (
        "REQUIRED — these are this reader's four pairings, in this order, "
        "with the verdict each one carries. They are the only four this "
        "section may contain:\n"
        + "\n".join(
            '  %d. combo: "%s + %s"  verdict: %s  what it is: %s'
            % (i + 1, mine, row["name"], row["verdict"], row["line"])
            for i, row in enumerate(picked))
        + "\nCopy each `combo` and each `verdict` exactly. Write the `why` "
          "yourself: take the line above as true, say what that pairing is "
          "like to be inside, and then what to do about it.")


def _persona_picks_block(cfg, choices):
    """The shapes this reader actually chose, as the evidence to quote back.

    The claim the funnel makes is that the shapes unlock something, so a
    report that never names one has not paid the claim off. Given as labels
    rather than as ids: the label is the word that was on the card they
    tapped.
    """
    picks = _persona_picks(cfg, choices)
    if not picks:
        return None
    steps = ((cfg.get("swipe") or {}).get("steps") or [])
    lines = []
    for step in steps:
        label = picks.get(step.get("id"))
        if not label:
            continue
        question = step.get("caption") or step.get("question") or ""
        lines.append("- %s%s" % (label, "  (%s)" % question if question else ""))
    if not lines:
        return None
    return ("THE SHAPES THIS PERSON CHOSE. These are their own words back at "
            "them, and the reason they believe this report is about them:\n"
            + "\n".join(lines)
            + "\nQuote at least one of them, by the words on it, somewhere in "
              "this section. Not a paraphrase — the label itself.")


# --- /brain: the number the reader was already shown ------------------------
#
# The browser worked all of this out while the run existed and put it on the
# screen before any money changed hands. The report has to arrive at exactly
# the same figures, from exactly the same table, for two reasons: the
# delivered page draws them back off the stored block rather than recomputing
# them — the tab it opens in never ran the quiz — and a document that
# disagreed with the page that sold it is worse than one that said nothing.


def _js_round(value):
    """`Math.round`, which is not Python's `round`.

    Python rounds a half to even; JavaScript rounds it up. They disagree on
    exactly the scores this funnel produces: a base of 22 with 3.5 for each
    miss lands on a half for every odd number of misses, and three misses is
    32.5 — 33 in the browser and 32 here. Floor of the value plus a half is
    what the browser does, on every value, so this is the whole conversion.
    """
    return int(math.floor(value + 0.5))


def _brain_numbers(cfg, style, tag_scores):
    """The block the browser computed, rebuilt server-side, or None.

    None on a funnel with no `brain_age` table and on a run with no tallies —
    both of which leave the report exactly as it was.
    """
    block = (cfg or {}).get("brain_age") or {}
    scored = block.get("scored")
    if not block or not tag_scores or not isinstance(scored, int) \
            or scored <= 0:
        return None

    # Counted off the hits rather than off a miss tally, exactly as the module
    # does it: a round nobody answered is a miss, and counting `*_miss` tags
    # would quietly score it as neither. The number is always out of `scored`.
    counts = {}
    hits = 0
    for key in BRAIN_DOMAINS:
        got = max(0, int(tag_scores.get(key + "_hit") or 0))
        counts[key] = got
        hits += got
    misses = max(0, scored - hits)

    age = _js_round((block.get("base") or 0)
                    + (block.get("per_miss") or 0) * misses)
    floor = block.get("min")
    ceiling = block.get("max")
    if isinstance(floor, (int, float)):
        age = max(int(floor), age)
    if isinstance(ceiling, (int, float)):
        age = min(int(ceiling), age)

    # Their own age group, off the service tag the first round carries, and
    # in the table's own order — the module takes the first tag it finds with
    # a score on it and so does this.
    mid = None
    for tag, value in (block.get("age_mid") or {}).items():
        if (tag_scores.get(tag) or 0) > 0 and isinstance(value, (int, float)):
            mid = int(value)
            break

    # The round with the most room in it. Ties go to the earliest of the four,
    # so the same run always names the same round — in the prompt, in the
    # chapter and in the plan's first day.
    weakest = min(BRAIN_DOMAINS,
                  key=lambda key: (counts[key], BRAIN_DOMAINS.index(key)))

    return {
        "age": age,
        "hits": hits,
        "misses": misses,
        "scored": scored,
        "counts": counts,
        "age_mid": mid,
        "delta": None if mid is None else age - mid,
        "weakest": weakest,
        "domains": dict(block.get("domains") or {}),
        "type": (style or {}).get("id") or "",
        "type_name": (style or {}).get("name") or "",
    }


def _brain_round_name(numbers, key):
    """What this funnel calls one round, or the bare key."""
    return (numbers.get("domains") or {}).get(key) or key


def _brain_rounds_block(numbers):
    """How this reader actually played, for the sections written for them."""
    if not numbers:
        return None
    lines = ["- %s: %d of 4" % (_brain_round_name(numbers, key),
                                min(4, numbers["counts"][key]))
             for key in BRAIN_DOMAINS]
    room = _brain_round_name(numbers, numbers["weakest"])
    tail = [
        "THE ROUNDS THIS PERSON PLAYED, and how they scored:",
        "\n".join(lines),
        "The round with the most room in it is %s. It is the one this plan "
        "is built around, and it is named that way rather than as a weakness "
        "— it is where a week of practice moves the number most." % room,
    ]
    delta = numbers.get("delta")
    if delta is not None:
        if delta >= 3:
            tail.append(
                "Their number came out above the middle of their own age "
                "group, which is the best news in this report: it is the "
                "number with the most room to come down.")
        elif delta <= -3:
            tail.append(
                "Their number came out below the middle of their own age "
                "group. Write for somebody keeping an edge they already "
                "have, not for somebody catching up.")
        else:
            tail.append(
                "Their number came out level with the middle of their own "
                "age group. Write for somebody about to move it for the "
                "first time.")
    tail.append(
        "Name the rounds by the words above and never print a score, a "
        "percentage or the number itself — the reader has all three on the "
        "page this chapter sits in.")
    return "\n\n".join(tail)


def _brain_pairs_block(numbers):
    """The four rounds and the badge each wears, from the run, not the model.

    Three of four or better is a strength; anything under it is a round with
    room in it. The word is the schema's — `works` or `avoid` — and the badge
    the reader sees is the profile's, because "AVOID" printed over the round
    somebody is being told to practise is the document arguing with its own
    plan.
    """
    if not numbers:
        return None
    rows = []
    for key in BRAIN_DOMAINS:
        verdict = "works" if numbers["counts"][key] >= 3 else "avoid"
        rows.append("- %s — %s" % (_brain_round_name(numbers, key), verdict))
    return ("REQUIRED — these are this reader's four rounds and the verdict "
            "each one carries, in this order:\n"
            + "\n".join(rows)
            + "\nReproduce all four as `pairs`, in this order, with `combo` "
              "the round's name exactly as written here and `verdict` the "
              "word beside it. Invent no round and never change a verdict.")


def _brain_plan_block(numbers):
    """Which round the first day of the week belongs to."""
    if not numbers:
        return None
    room = _brain_round_name(numbers, numbers["weakest"])
    return ("REQUIRED — day one and day four of this plan are drills for %s, "
            "which is the round with the most room in it for this reader. "
            "Day one is the two-minute drill the chapter before this one "
            "spelled out, written as the doing rather than the explaining. "
            "The remaining five days spread across the other three rounds, "
            "and at least one of them spends the round this reader is "
            "already strongest at rather than training it." % room)


def _profile_for(cfg, funnel_slug, style, tag_scores, choices):
    """The stored block for a purchase, or None.

    Two vocabularies, one slot. Zodiac runs are read on elements and signs;
    persona runs are read on axes and energies and have no sign at all. Both
    end up in `visuals.profile` and both are drawn by the same card.
    """
    profile = _profile(funnel_slug)
    if profile is PERSONA_PROFILE:
        return _persona_profile(cfg, style, tag_scores, choices)
    if not _is_zodiac(profile):
        return None
    read = _sign(cfg, choices) if choices else None
    return _reader_profile(cfg, style, tag_scores,
                           (read or {}).get("label") or "",
                           bool((read or {}).get("cusp")),
                           profile.get("element_labels"),
                           profile.get("energy_labels"))


# --- what the reader is told about love ------------------------------------
#
# Classical compatibility, stated rather than left to the model. The Love card
# on the paywall promises two magnetic signs and one that drains, by name, so
# the section has to name three signs — and a model asked for three signs
# without being told which three will happily supply three.
#
# The rule is the ordinary one: the two other signs of the reader's own
# element are the trine, and one of the squares is the friction. Nothing here
# is a prediction about a person; it is the classical relationship between two
# signs, which is what the reader bought a reading of.
COMPATIBILITY = {
    "Aries": (("Leo", "Sagittarius"), "Cancer"),
    "Taurus": (("Virgo", "Capricorn"), "Leo"),
    "Gemini": (("Libra", "Aquarius"), "Pisces"),
    "Cancer": (("Scorpio", "Pisces"), "Aries"),
    "Leo": (("Aries", "Sagittarius"), "Taurus"),
    "Virgo": (("Taurus", "Capricorn"), "Sagittarius"),
    "Libra": (("Gemini", "Aquarius"), "Cancer"),
    "Scorpio": (("Cancer", "Pisces"), "Leo"),
    "Sagittarius": (("Aries", "Leo"), "Virgo"),
    "Capricorn": (("Taurus", "Virgo"), "Libra"),
    "Aquarius": (("Gemini", "Libra"), "Scorpio"),
    "Pisces": (("Cancer", "Scorpio"), "Gemini"),
}


# The same classical relationships, keyed and answered in the names the
# Romanian funnel actually puts on its cards. `_sign` reads the label off the
# config, so a table keyed in English would simply never match here.
COMPATIBILITY_RO = {
    "Berbec": (("Leu", "Săgetător"), "Rac"),
    "Taur": (("Fecioară", "Capricorn"), "Leu"),
    "Gemeni": (("Balanță", "Vărsător"), "Pești"),
    "Rac": (("Scorpion", "Pești"), "Berbec"),
    "Leu": (("Berbec", "Săgetător"), "Taur"),
    "Fecioară": (("Taur", "Capricorn"), "Săgetător"),
    "Balanță": (("Gemeni", "Vărsător"), "Rac"),
    "Scorpion": (("Rac", "Pești"), "Leu"),
    "Săgetător": (("Berbec", "Leu"), "Fecioară"),
    "Capricorn": (("Taur", "Fecioară"), "Balanță"),
    "Vărsător": (("Gemeni", "Balanță"), "Scorpion"),
    "Pești": (("Rac", "Scorpion"), "Gemeni"),
}

# And once more in the names the Bulgarian funnel puts on its cards. `_sign`
# reads the label off the config, so a table keyed in English or in Romanian
# would simply never match here.
COMPATIBILITY_BG = {
    "Овен": (("Лъв", "Стрелец"), "Рак"),
    "Телец": (("Дева", "Козирог"), "Лъв"),
    "Близнаци": (("Везни", "Водолей"), "Риби"),
    "Рак": (("Скорпион", "Риби"), "Овен"),
    "Лъв": (("Овен", "Стрелец"), "Телец"),
    "Дева": (("Телец", "Козирог"), "Стрелец"),
    "Везни": (("Близнаци", "Водолей"), "Рак"),
    "Скорпион": (("Рак", "Риби"), "Лъв"),
    "Стрелец": (("Овен", "Лъв"), "Дева"),
    "Козирог": (("Телец", "Дева"), "Везни"),
    "Водолей": (("Близнаци", "Везни"), "Скорпион"),
    "Риби": (("Рак", "Скорпион"), "Близнаци"),
}

ZODIAC_PROFILE["compatibility"] = COMPATIBILITY
ZODIAC_RO_PROFILE["compatibility"] = COMPATIBILITY_RO
ZODIAC_BG_PROFILE["compatibility"] = COMPATIBILITY_BG


def _compat_block(cfg, choices, table=None):
    """The three signs the love section has to name, or None.

    A cusp reader gets the sets for both energies their season sits between
    and an instruction not to settle on one of them, because that is what they
    told us and no more.
    """
    read = _sign(cfg, choices) if choices else None
    if not read:
        return None
    table = table or COMPATIBILITY
    label = read.get("label")
    if label and label in table:
        magnetic, drains = table[label]
        return (
            "REQUIRED — the free page promised this reader, in these words, "
            "the two signs that are magnetic for them and the one that drains "
            "their relationships. Classically, for a %s those are: magnetic — "
            "%s and %s; draining — %s. Name all three, in those words, and for "
            "each one say two things: what it is actually like — what the "
            "pull is built on for the two, what the cost is with the third — "
            "and then what to DO about it, which is the half they came for. "
            "For the two magnetic ones that is the thing that actually works "
            "with them; for the draining one it is the boundary that makes it "
            "survivable. Use no other signs as the answer to that promise. "
            "The shape asks for a fourth pairing and it is a SECOND draining "
            "sign, which is yours to choose: pick one that is none of the "
            "three above. All four pairings name four DIFFERENT signs beside "
            "this reader's own — never the same sign twice, however "
            "differently the second entry is written. And never write that a "
            "relationship will or will not work — describe the energy between "
            "them and what it takes from each side."
            % (label, magnetic[0], magnetic[1], drains))

    neighbours = [name for name in (read.get("neighbours") or [])
                  if name in table]
    if not neighbours:
        return None
    lines = []
    for name in neighbours:
        magnetic, drains = table[name]
        lines.append("- for a %s: magnetic %s and %s, draining %s"
                     % (name, magnetic[0], magnetic[1], drains))
    return (
        "REQUIRED — the free page promised this reader the two signs that are "
        "magnetic for them and the one that drains their relationships. They "
        "were born on a cusp and gave no single sign, so the honest answer is "
        "the blend. The classical sets for the signs their season covers "
        "are:\n" + "\n".join(lines)
        + "\nName the signs these sets have in common as the magnetic ones "
          "and the friction they share as the draining one, say plainly that "
          "sitting between two signs is why this reads as a blend, and never "
          "settle on one sign for them. The fourth pairing the shape asks for "
          "is a second draining sign and is yours to choose; all four name "
          "four DIFFERENT signs, never the same one twice.")


def _subtype_block(profile):
    """How the reader's own subtype is handed to a model, or None.

    Personal sections only. The cached trio is one answer per archetype shared
    by every buyer of it — see the note above `_cached_prompt` — and a subtype
    in that prompt would be twenty-four cache rows where there are four, each
    written for whoever happened to warm it first.
    """
    if not profile:
        return None
    scales = ", ".join(
        "%s to %s at %d out of 100"
        % (row.get("left"), row.get("right"), row.get("at", 50))
        for row in (profile.get("scales") or [])
        if row.get("left") and row.get("right"))
    split = ", ".join("%s %d%%" % (cell["name"], cell["pct"])
                      for cell in (profile.get("split") or []))
    # Two vocabularies reach this block. The zodiac card leads on an element
    # and the persona card leads on an axis; everything else about the
    # sentence is the same, so the noun follows the card rather than the
    # block having to be written twice.
    words = profile.get("words") or {}
    lead = words.get("element") or words.get("axis") or ""
    measured = "elements" if words.get("element") else "axes"
    lines = [
        "This reader has been given a name for what they are, on the page "
        "they paid from, and it is the name this report is written to: %s."
        % profile["subtype"],
        "What it is made of: %s-led with a %s undercurrent, %s energy."
        % (lead, words.get("second", ""), words.get("energy", "")),
    ]
    if split:
        lines.append("Their four %s measured: %s." % (measured, split))
    if scales:
        lines.append("Where they sit on the three scales the page showed "
                     "them: %s." % scales)
    lines.append(
        "Use the name. Address them as %s where it lands naturally — once or "
        "twice in a section, at a point where the sentence is about what that "
        "name means — and never as a label stapled to every paragraph. Let "
        "the undercurrent do real work: %s leading with %s underneath is a "
        "different person from %s leading alone, and the advice should show "
        "it. Never mention scales, percentages, positions or a quiz."
        % (words.get("subtype_article", "a") + " " +
           profile["subtype_bare"],
           lead, words.get("second", ""), lead))
    return "\n".join(lines)


def _zodiac_choice_block(cfg, choices, tag_scores=None):
    """The taps this section has to be visibly written from.

    The differentiator between a report and a horoscope column is that this
    one names things the reader did twenty seconds ago. Every per-purchase
    section carries this, and the requirement is not decorative: a section
    that mentions none of them reads as bought copy.
    """
    if not choices:
        return None
    images = _images_by_id(cfg)
    wanted = [("sign", "their sign"),
              ("moonphase", "the moon they chose"),
              ("symbol", "the talisman they chose"),
              ("palette", "the palette they chose"),
              ("landscape", "the landscape they chose"),
              ("sanctuary", "where they said they recharge")]
    lines = []
    for step_id, description in wanted:
        chosen = _chosen_on_step(cfg, choices, step_id)
        item = images.get(chosen) if chosen else None
        label = (item or {}).get("label")
        if not label or chosen == CUSP_ID:
            continue
        lines.append("- %s: %s" % (description, label))
    if not lines:
        return None
    return (
        "REQUIRED — what this person actually tapped, in their own run:\n"
        + "\n".join(lines)
        + "\nAt least one of these must appear in this section by name, used "
          "as evidence for something you are saying about them rather than "
          "listed back at them. More than one is better. Never say that they "
          "tapped or chose anything — write as though you already knew.")


def _section_prompt(style, name, tag_scores, section_id, cfg=None,
                    choices=None, funnel_slug=None, months=None):
    """One personalised section on its own.

    Each section is its own call now, so each carries the whole style and
    leaning context. That is a few hundred repeated tokens per report against
    three sections arriving in the time one used to take.

    When the choice sequence survived checkout it goes in too: the palette is
    built from the colours they actually tapped, and the other two sections get
    the sequence as something they may point at. Without it every section falls
    back to the tag-based behaviour unchanged.
    """
    profile = _profile(funnel_slug)
    zodiac = _is_zodiac(profile)
    persona = profile is PERSONA_PROFILE
    brain = profile is BRAIN_PROFILE

    parts = [_style_block(style, name)]
    # `_leaning_block` is kitchen's vocabulary — it asks the model to let the
    # pull change "which colours and materials you name" — and the memory
    # game has neither. Its rounds block below is this product's version of
    # the same idea, and it is stated in scores rather than in tag counts.
    if not brain:
        parts.append(_leaning_block(tag_scores))
    numbers = _brain_numbers(cfg, style, tag_scores) if brain else None
    if numbers:
        rounds = _brain_rounds_block(numbers)
        if rounds:
            parts.append(rounds)

    extra = None
    if cfg is not None and choices:
        if persona:
            # The shapes they chose, as labels. Kitchen's colour-family block
            # is about photographs of rooms and the zodiac one is about a
            # sign; this funnel's evidence is the words on the cards.
            extra = _persona_picks_block(cfg, choices)
        elif zodiac:
            # The zodiac palette is a wardrobe rather than a paint schedule,
            # so the colour-family block kitchen builds for it does not apply.
            extra = _zodiac_choice_block(cfg, choices, tag_scores)
        else:
            extra = (_palette_block(cfg, choices) if section_id == "palette"
                     else _choice_block(cfg, choices, tag_scores))
    if extra:
        parts.append(extra)

    # The year map is counted from the month this purchase happened in, so
    # the twelve labels are built here and handed over as the only twelve the
    # section may use. `months` is passed in rather than computed here so the
    # prompt and the check that polices it cannot read different clocks.
    if (zodiac or persona) and section_id == "shopping":
        year = _year_block(months)
        if year:
            parts.append(year)

    if zodiac and cfg is not None and choices:
        sign = _sign_block(cfg, choices)
        if sign:
            parts.append(sign)
        # Personal sections only, checked here rather than left to the call
        # site. The cached trio is one answer per archetype shared by every
        # buyer of it, so a purpose in that prompt would be a row written for
        # whoever happened to warm it first — see the note above
        # `_cached_prompt`.
        if section_id in (profile.get("personal") or ()):
            purpose = _purpose_block(cfg, choices, section_id)
            if purpose:
                parts.append(purpose)
            # The name the reader was sold under, for the sections written for
            # them. Same gate as the purpose above, and for the same reason:
            # the cached trio is one answer per archetype, and a subtype in
            # that prompt would be twenty-four cache rows where there are four.
            subtype = _subtype_block(
                _profile_for(cfg, funnel_slug, style, tag_scores, choices))
            if subtype:
                parts.append(subtype)

    # The love section names three signs because the paywall promised three
    # signs. Which three is classical rather than the model's to invent.
    if zodiac and section_id == "materials" and cfg is not None and choices:
        compat = _compat_block(cfg, choices,
                               profile.get("compatibility"))
        if compat:
            parts.append(compat)

    # The first mistake was given away in full, numbered, with the promise
    # that the other four are in here. So it has to BE the first item rather
    # than a similar one: a reader who bought on "mistakes 2-5" and found five
    # unfamiliar ones has been told the truth about the count and nothing else.
    if section_id == "mistakes" and not zodiac:
        first = _mistake_one(style)
        if first:
            parts.append(
                "REQUIRED — item 1 of this section was already given to this "
                "person in full, for free, as \"Mistake #1 of 5\". Reproduce "
                "it as item 1, in these words:\n"
                "  title: %s\n  body: %s\n  fix: %s\n"
                "Items 2 onward are yours to write and must all be different "
                "from it. Order them cheapest correction first, so the one "
                "that costs most to undo is last."
                % (first["title"], first["body"], first["fix"]))

    # The materials section is where the free preview gets paid off. Those six
    # elements were named on the result screen before any money changed hands,
    # with the promise that the report specifies each one — so this section is
    # required to, by name, rather than left to mention them if it happens to.
    # Not on the memory game: its `style_elements` block exists for the same
    # reason every funnel's does, but its result page draws no element strip
    # and nothing was promised. The block asks for "the finish, the material
    # or the fitting to ask a supplier for", which is a kitchen sentence in a
    # chapter about a round somebody played.
    if section_id == "materials" and not zodiac and not brain \
            and cfg is not None and choices:
        specs = _element_specs(cfg, choices, tag_scores)
        if specs:
            parts.append(
                "REQUIRED — these are the style elements this person was shown "
                "on the free result, with the specification each one was "
                "promised:\n"
                + "\n".join("- " + line for line in specs)
                + "\nEvery one of them must appear in this section by name, "
                  "and each must be specified rather than merely mentioned: "
                  "the finish, the material or the fitting to ask a supplier "
                  "for. Do not contradict a specification above. You may group "
                  "them where they belong together, and you may add to them, "
                  "but nothing on the list may be missing.")

    # The four rounds and their badges come off the run rather than out of
    # the model, exactly as the love pairings do on the zodiac product: the
    # chapter is read as a table and a table the model invented would not be
    # the reader's own.
    if numbers and section_id == "materials":
        pairs = _brain_pairs_block(numbers)
        if pairs:
            parts.append(pairs)
    if numbers and section_id == "shopping":
        plan = _brain_plan_block(numbers)
        if plan:
            parts.append(plan)

    if persona and cfg is not None:
        card = _profile_for(cfg, funnel_slug, style, tag_scores, choices)
        # The pairings the reader was promised, from the table rather than
        # from the model. Personal section, so this is where it belongs.
        if section_id == "materials":
            pairs = _persona_pairs_block(cfg, card)
            if pairs:
                parts.append(pairs)
        # The name they were sold under, on the sections written for them.
        if section_id in (profile.get("personal") or ()):
            subtype = _subtype_block(card)
            if subtype:
                parts.append(subtype)
            purpose = _purpose_block(cfg, choices, section_id) if choices \
                else None
            if purpose:
                parts.append(purpose)

    parts.append(_sections_block((section_id,), profile["spec"]))
    return "\n\n".join(parts)


# The cache key is (funnel, style) and stays that way.
#
# Nothing below this line ever sees a purpose. The cached trio is the same
# three sections for everybody who lands on an archetype — that is what makes
# them worth caching at all — and adding the purpose to this prompt would
# quadruple the rows while making each one a reading written for whichever
# buyer happened to warm it. The personalisation this funnel sells is the
# reader's own sign and their own taps, and all of that is in the personal
# trio, which is written fresh per purchase and cached nowhere.
def _cached_prompt(style, name, ids=None, funnel_slug=None):
    """The per-style sections. `ids` narrows it to a subset for the warmer."""
    profile = _profile(funnel_slug)
    if ids is None:
        ids = profile["cached"]
    parts = [
        _style_block(style, name),
        "Write for anyone with this style. Nothing here is specific to one "
        "person.",
    ]
    # The free result gave hidden strength #1 away in full, numbered, with the
    # promise that the other four are inside. On kitchen that section is
    # personalised and the requirement lives there; here it is cached, and it
    # can be, because the strength belongs to the archetype rather than to the
    # reader. Either way item 1 has to be the one already on screen.
    if (_is_zodiac(profile) or profile is PERSONA_PROFILE) and "palette" in ids:
        required = _palette_required(style)
        if required:
            parts.append(required)
    if (_is_zodiac(profile) or profile is PERSONA_PROFILE) \
            and "mistakes" in ids:
        first = _mistake_one(style)
        if first:
            parts.append(
                "REQUIRED — item 1 of the five was already given to this "
                "person in full, for free, as \"Hidden Strength #1 of 5\". "
                "Reproduce it as item 1, in these words:\n"
                "  title: %s\n  body: %s\n  fix: %s\n"
                "Items 2 onward are yours to write and must all be different "
                "from it." % (first["title"], first["body"], first["fix"]))
    parts.append(_sections_block(ids, profile["spec"]))
    return "\n\n".join(parts)


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

# What the retry is told when the first answer did not parse.
#
# It used to be told the diagnostic line instead — "invalid JSON
# (JSONDecodeError at char 812 of 1748)" — inside a correction block that
# closes with "the character counts are hard limits, count them before you
# answer". That is a length instruction for a syntax failure: the model was
# asked to shorten an answer whose only problem was a quotation mark, so the
# second attempt made the same mistake in fewer words. This names the actual
# fault and the actual fix.
#
# The repair we do NOT attempt is the matching one: rewriting a stray quote
# into an escaped quote. Deciding which `"` in a broken document is a
# delimiter and which is prose is a guess, and a wrong guess does not fail —
# it welds two fields into one and produces an object that is shape-valid,
# inside its character ceilings and clean of banned words, so every check
# below waves it through and a paying reader gets the mangled sentence. A
# retry that asks the model to escape its own quotes costs one call and
# cannot do that.
EXCERPT_EITHER_SIDE = 40


def _excerpt(chunk, at):
    """The characters around a decode failure, for the log line. Or "".

    Six identical failures in a row is what this exists for: the position and
    the exception class say a section broke, and never which character did it.
    Forty either side is enough to see the quotation mark sitting in the
    middle of a sentence and stop guessing.

    What this prints is the model's own writing, which the reason string has
    deliberately never carried before — so, against rule 6: a report section
    is written about an archetype, never about the person. It holds no
    address, no session, no identifier and nothing the reader typed, because
    this funnel has no field to type into. `repr` escapes it to one line, so
    a newline in the answer cannot forge a log record either.
    """
    if not isinstance(at, int) or not chunk:
        return ""
    lo = max(0, at - EXCERPT_EITHER_SIDE)
    hi = min(len(chunk), at + EXCERPT_EITHER_SIDE)
    return " near %s" % repr(chunk[lo:hi])


_JSON_ADVICE = (
    "the answer was not valid JSON and could not be read at all — it failed "
    "to parse at character %s of %s. This is punctuation, not length: the "
    "usual cause is an unescaped double quote inside a string value, or a "
    "line break in the middle of one. Escape every double quote inside a "
    "value as \\\" and keep each value on one line, or avoid straight double "
    "quotes in the prose altogether")


# A straight double quote that is doing the job of a closing guillemet.
#
# What went wrong in production: the prompt asked for the pair U+201E … U+201C
# and the model opened with U+201E and closed with a straight ", which is the
# JSON delimiter — so the value ended in the middle of the archetype name and
# ten of twelve warmed sections were thrown away, twice each. The prompt now
# asks for guillemets, which cannot be confused with a delimiter; this is the
# belt to that pair of braces, because a model that has been told once can
# still reach for the key next to it.
#
# The distinction that makes the repair safe is what sits on BOTH sides. A
# real JSON closing quote is followed by , } ] : or the end of the line, never
# by Cyrillic prose; and a real JSON opening quote is preceded by { [ , : or
# whitespace, never by a Cyrillic letter. So a " with a Cyrillic letter behind
# it and Cyrillic, an em-dash or a guillemet in front of it is not structure —
# it is punctuation inside a sentence, and the only thing it can be is the
# closing mark of a name the model opened with U+201E.
#
#   палитрата U+201E Сияен огън " работят   ->  ... «Сияен огън» работят
#   "why": "Енергията U+201E Дълбока вода " не  ->  value opens intact, name closed
#   "Сияен огън",                            ->  untouched: that " really is the end
_BG_CLOSER_RE = re.compile(
    r'(?<=[\u0400-\u04FF])"(?=\s*[\u0400-\u04FF\u2014\u00ab\u00bb])')


def _bg_quote_repair(text):
    """The model's raw answer with its quotation marks made parseable.

    Three substitutions and nothing else — no field is joined to its
    neighbour, no brace is invented, and every character that is not one of
    these marks comes through untouched:

      U+201E  ->  «     the opening mark it was told not to use
      U+201C  ->  »     its proper closing partner, normalised with it
      "       ->  »     only where it is closing a name mid-sentence

    The third is the one that matters and the one that is bounded: see
    `_BG_CLOSER_RE` for why a quote with Cyrillic on both sides cannot be
    JSON structure. Applied to the Bulgarian profile alone, because it is the
    only one whose prose is Cyrillic — the test that this is safe rests on
    that alphabet, and an English section would not be protected by it.
    """
    if not text:
        return text
    return _BG_CLOSER_RE.sub("\u00bb",
                             text.replace("\u201e", "\u00ab")
                                 .replace("\u201c", "\u00bb"))


ZODIAC_BG_PROFILE["json_repair"] = _bg_quote_repair


def _parse_detail(text, want, notes=None, repair=None):
    """(parsed, reason). `reason` is None on success, else why it was refused.

    `notes`, when a list is passed, collects the field-level drift the
    forensics produce — the same strings that go to the log. Callers that pass
    nothing are unaffected, which is every kitchen call site.

    The reason is diagnostic only and is built from field names, offsets and
    exception classes — never from the model's words. It exists because a
    section that fails here fails silently otherwise: the caller sees None and
    has no way to tell a truncated answer from a reshaped one.
    """
    if not text:
        return None, "empty response"
    if repair is not None:
        # Before anything reads it as JSON, and before the excerpt in a
        # refusal is cut from it, so the log shows what was actually parsed.
        text = repair(text)
    body = FENCE_RE.sub("", text.strip()).strip()
    start, end = body.find("{"), body.rfind("}")
    if start < 0 or end <= start:
        # A response cut off mid-object never gets its closing brace, so this
        # is what truncation looks like by the time it reaches us.
        return None, ("no closing brace — response ends unterminated"
                      if start >= 0 else "no JSON object in response")
    chunk = body[start:end + 1]
    try:
        data = json.loads(chunk)
    except ValueError as exc:
        # One salvage, and it is the standard library's rather than ours.
        # `strict=False` accepts literal control characters inside a string
        # value — a raw newline in the middle of a paragraph, which is one of
        # the two ways prose breaks JSON. It guesses at nothing: no quote is
        # reinterpreted, no field is joined to its neighbour, and the text
        # that comes back is character for character what the model wrote.
        # Anything it recovers still goes through the same shape validators,
        # the same character ceilings and the same banned list below.
        #
        # The other way prose breaks JSON — an unescaped double quote — is
        # deliberately NOT repaired here. See the note above `_JSON_ADVICE`.
        try:
            data = json.loads(chunk, strict=False)
        except ValueError:
            at = getattr(exc, "pos", None)
            # A response that ran out of room breaks at its own end, and the
            # last `}` we could find is from some earlier item — so the decode
            # fails near the tail rather than in the middle. Saying which it
            # is turns a log line into a diagnosis: run out of room, or came
            # back malformed.
            tail = isinstance(at, int) and (end + 1 - start) - at < 200
            if notes is not None:
                notes.append(_JSON_ADVICE % (at, len(body)))
            return None, ("invalid JSON (%s at char %s of %d)%s%s"
                          % (type(exc).__name__, at, len(body),
                             " — breaks at the end, looks truncated"
                             if tail else "", _excerpt(chunk, at)))
        log.warning("section %s recovered: a control character inside a "
                    "string value", "+".join(want))
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
            drift = _drift_detail(key, value)
            log.warning("section %s field drift: %s", key, "; ".join(drift))
            if notes is not None:
                notes.extend(drift)
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


def _ask(client, prompt, max_tokens, system=None):
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
            system=SYSTEM if system is None else system,
            messages=[{"role": "user", "content": prompt}],
        )
    finally:
        gate.release()
    text = "".join(
        block.text for block in message.content if block.type == "text"
    )
    return text, getattr(message, "stop_reason", None)


def _attempt(client, prompt, max_tokens, label, system=None):
    """One prompt, retried once if it times out.

    A timeout is the one failure worth repeating immediately: it means the
    connection never produced anything, so there is no half-answer to salvage
    and nothing was spent on output. Every other error goes straight up — a
    rejection or a bad request will fail the same way twice.
    """
    timeout = _timeout_class()
    try:
        return _ask(client, prompt, max_tokens, system)
    except Exception as exc:
        if timeout is None or not isinstance(exc, timeout):
            raise
        log.warning("section %s timed out — retrying once", label)
    return _ask(client, prompt, max_tokens, system)


def _generate(client, prompt, want, max_tokens=None, system=None,
              banned=(), detail=False, verify=None, json_retry=None,
              json_repair=None):
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

    # `detail` is what turns the second attempt into a correction rather than
    # a repetition. Off, this behaves exactly as it did.
    notes = [] if detail else None
    text, stop = _attempt(client, prompt, max_tokens, label, system)
    parsed, why = _parse_detail(text, want, notes, json_repair)
    hit = _banned_hit(parsed, banned) if parsed is not None else None
    if hit:
        # A section that says the banned thing is refused even though it
        # parsed. The words are a Terms line, and a retry is far cheaper than
        # the alternative — the stub, which never says them at all.
        why = "banned phrase %r" % hit
        parsed = None
        if notes is not None:
            notes.append('the phrase "%s" is not allowed anywhere in this '
                         "section — say it another way" % hit)
    wrong = verify(want, parsed) if (verify and parsed is not None) else None
    if wrong:
        # Shape-valid and still not this reader's. The validators police the
        # form; this polices the facts, and a colour the config never gave is
        # the document contradicting the page that sold it.
        why = wrong
        parsed = None
        if notes is not None:
            notes.append(wrong)
    if parsed is not None:
        return parsed
    # A profile that knows which of its own fields keeps breaking the JSON
    # says so, after the generic advice and only for a parse failure. Nothing
    # declares one but the Romanian profile, so every other funnel's retry is
    # the one it already had.
    if (json_retry and notes is not None and why
            and why.startswith("invalid JSON")):
        notes.append(json_retry)
    # Truncation, a missing key, a renamed key: those never reach the field
    # forensics, and they are exactly the failures worth naming on the retry.
    if notes is not None and not notes and why:
        notes.append(why)
    log.warning("section %s unusable: %s (%d chars, stop=%s, cap=%d) — retrying",
                label, why, len(text or ""), stop, max_tokens)

    text, stop = _attempt(client, _retry_prompt(prompt, notes), max_tokens,
                          label, system)
    # The second attempt gets the same repair as the first: a model that broke
    # the JSON this way once is the one most likely to do it again.
    parsed, why = _parse_detail(text, want, None, json_repair)
    hit = _banned_hit(parsed, banned) if parsed is not None else None
    if hit:
        why = "banned phrase %r" % hit
        parsed = None
    wrong = verify(want, parsed) if (verify and parsed is not None) else None
    if wrong:
        why = wrong
        parsed = None
    if parsed is None:
        log.warning("section %s given up: %s (%d chars, stop=%s, cap=%d)",
                    label, why, len(text or ""), stop, max_tokens)
    return parsed


# --- cache -----------------------------------------------------------------


def _cache_source(funnel_slug):
    """The funnel a `-test` twin borrows cached sections from, or None.

    The same suffix `_profile` strips, read through `config` for the same
    reason: the route guard, the profile and this all have to spell a twin the
    same way, and a second copy of the string is how they stop doing that.

    A live slug borrows from nobody, which is the whole of the rule — nothing
    here can make one funnel read another funnel's rows.
    """
    if not config.is_test_slug(funnel_slug or ""):
        return None
    return (funnel_slug or "")[:-len(config.TEST_SUFFIX)] or None


def _style_rows(funnel_slug, result_style):
    """(usable sections, stale row count) for one funnel's own rows.

    None for the sections when the read itself failed, which is a different
    thing from a funnel that has none: the first must not be allowed to look
    like an empty cache and send a twin off to borrow.
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
        section_id = row.get("section_id")
        if content.get("v") != _cache_tag(funnel_slug, section_id):
            stale += 1
            continue
        data = content.get("data")
        if section_id in VALIDATORS and isinstance(data, dict):
            clean = VALIDATORS[section_id](data)
            if clean is not None:
                out[section_id] = clean
    return out, stale


def _cache_state(funnel_slug, result_style):
    """(usable sections, stale row count) for one style.

    Section-by-section rather than all-or-nothing, because the warmer needs to
    know which three are missing and the purchase path only needs to know
    whether all three are there.

    A `-test` twin with nothing of its own reads its source funnel's rows. The
    twin IS that funnel — same styles, same archetypes, same profile, so the
    same cache tag — and the cached trio is one answer per archetype rather
    than one per buyer, so the source's answers are already the twin's. Without
    this a sandbox purchase finds an empty cache, cannot generate three
    sections inside the budget, and delivers the stubs: which is exactly how a
    Romanian test purchase came back with three English blocks in it.

    Reads only, and only when the twin has no row of its own — not even a
    stale one, because a stale row is a funnel that HAS been warmed and is
    owed a regeneration rather than a loan. The write side stays keyed to the
    funnel that asked, so nothing a sandbox generates can ever land on a row a
    paying reader will be served.
    """
    out, stale = _style_rows(funnel_slug, result_style)
    if out is None or out or stale:
        return out, stale
    source = _cache_source(funnel_slug)
    if not source:
        return out, stale
    borrowed, borrowed_stale = _style_rows(source, result_style)
    if not borrowed:
        return out, stale
    log.info("%s has no cached sections for %s — reading %s's",
             funnel_slug, result_style, source)
    return borrowed, borrowed_stale


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

    wanted = cached_sections(funnel_slug)
    if all(section_id in out for section_id in wanted):
        return dict((section_id, out[section_id]) for section_id in wanted)
    return None


def _cache_tag(funnel_slug, section_id):
    """What a cached row must be stamped with to still count.

    The schema, plus a per-section revision where a funnel has declared one.
    A section with no revision is tagged exactly as it always was, which is
    what keeps every existing kitchen row valid.
    """
    rev = (_profile(funnel_slug).get("cache_rev") or {}).get(section_id)
    return CACHE_SCHEMA + (":" + rev if rev else "")


def _write_cache(funnel_slug, result_style, sections):
    for section_id, data in sections.items():
        try:
            database.execute(
                UPSERT_SECTION_SQL,
                (
                    funnel_slug,
                    result_style,
                    section_id,
                    json.dumps({"v": _cache_tag(funnel_slug, section_id),
                                "data": data}, separators=(",", ":")),
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


def _assemble(cfg, funnel_slug, result_style, name, built, paths, complete,
              elements=None, visuals=None, sign=None, purpose=None):
    """The stored content for whatever has resolved so far.

    A section that has not resolved is simply absent — the client renders what
    exists and keeps polling. Once `complete`, every section is present, either
    generated or stubbed, and the version says which.

    `elements` is the ids of the style elements the free result showed, so the
    paid view can put the same six back on screen. It is stored rather than
    recomputed in the browser because someone returning from Stripe may have
    no quiz state left to recompute from.

    `visuals` is stored for exactly the same reason: the palette board and the
    two surfaces the report is illustrated with are ids out of this person's
    own run, and the page that draws them is reached through a redirect. The
    PDF is built server-side and never had the run at all.
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

    content = {
        "version": version,
        "funnel": funnel_slug,
        "style_id": result_style,
        "style_name": name,
        "sections": sections,
    }
    if elements:
        content["elements"] = list(elements)
    if visuals:
        content["visuals"] = dict(visuals)
    # The sign they tapped, for the funnels that have one. Stored for the same
    # reason the elements and the visuals are: the mail and the PDF are built
    # server-side from this row and never had the run, and by the time either
    # is written the choices are long gone. A funnel with no sign stores no
    # key and every reader of this content sees exactly what it saw before.
    if sign:
        content["sign"] = sign
    # And what they said pulled them here, for the same reason again: the paid
    # page is opened from a link in an email, in a tab that never ran the quiz,
    # and the order it puts the sections in is read off this. A funnel with no
    # purpose map stores no key, and every reader of this content sees exactly
    # what it saw before. The section list itself stays in the report's own
    # order — the PDF is built from it, and a printed archive that reshuffled
    # itself per reader would be a different document each time.
    if purpose:
        content["purpose"] = purpose
    return content


def delivered_content(content, email):
    """The stored report, plus what the delivered page says about delivery.

    One line on that page — "Your PDF was sent to ..." — needs the address the
    PDF actually went to, and the report row does not carry it: the address
    lives on the purchase and is deliberately not copied into the report JSON.
    So it is attached here, to the object being serialised for one
    authenticated response, and never to the row.

    That distinction is the whole safety of this. The stored row is what
    `build_pdf` and `send_report_email` are handed and what a later read of the
    reports table returns; nothing written here reaches any of them. The only
    place the address exists is the response to a request that already proved
    it holds this purchase's token.

    It rides inside `visuals` because that is the one key engine.js passes to
    a result module whole — the same channel the hero card, the tap order and
    the year already travel on. A funnel whose profile does not ask for the
    line, and a request with no address, both get the content exactly as it
    was stored — kitchen's response is the response it always was, to the
    byte.
    """
    if not content or not isinstance(content, dict) or not email:
        return content
    if not _profile(content.get("funnel")).get("delivery_note"):
        return content
    out = dict(content)
    visuals = dict(out.get("visuals") or {})
    visuals["delivery"] = {"email": email}
    out["visuals"] = visuals
    return out


def report_content(purchase_id):
    """The stored report for a purchase, parsed, or None.

    The row is written as a JSON column and read back as either a dict or a
    string depending on the driver's mood, which is a two-line dance that was
    already being done in one place and is now wanted in two. Here rather than
    at either call site because what a report row contains is this module's
    business, and a second hand-rolled decode is how the two drift apart.
    """
    try:
        row = database.query_one(SELECT_REPORT_SQL, (purchase_id,))
    except Exception:
        log.exception("report read failed for purchase %s", purchase_id)
        return None
    if not row:
        return None
    content = row.get("content")
    if isinstance(content, (str, bytes)):
        try:
            content = json.loads(content)
        except ValueError:
            log.error("report for purchase %s is not valid JSON", purchase_id)
            return None
    return content if isinstance(content, dict) else None


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
                        job["built"], job["paths"], complete, job["elements"],
                        job["visuals"], job.get("sign"), job.get("purpose"))
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
        stub_profile = _profile(job["funnel"])
        job["built"][section_id] = _stub_for(
            section_id, job["name"], _style(job["cfg"], job["style_id"]),
            stub_profile["stubs"], job.get("months"),
            stub_profile.get("stub_colors"))
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


def _personal_order(cfg, funnel_slug=None):
    """The personalised sections, in the order the report displays them."""
    personal = personal_sections(funnel_slug)
    ordered = [s.get("id") for s in cfg.get("report", {}).get("sections", [])
               if s.get("id") in personal]
    # A config that has dropped or renamed one still has to generate the rest.
    return ordered + [i for i in personal if i not in ordered]


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
    profile = _profile(funnel_slug)

    cached = _read_cache(funnel_slug, result_style)
    client = _api() if style else None

    built = {}
    paths = {}
    if cached:
        built.update(cached)
        for section_id in cached:
            paths[section_id] = "cache"

    # The six the free result named, resolved once here and carried on every
    # write: the paid view shows exactly what was promised, not a fresh guess.
    elements = [item["id"] for item in _pick_elements(cfg, choices, tag_scores)
                if item.get("id")]
    visuals = _visuals(cfg, result_style, choices)
    # Resolved here, while the run still exists, and carried on every write.
    # None on a funnel with no sign step, which is every funnel but one.
    read = _sign(cfg, choices) if choices else None
    sign = read.get("label") if read else None
    # The hero card, measured while the run still exists. It travels beside
    # the photographs rather than among them — `visuals.hero` is a map of slot
    # to image id and nothing else belongs in it — and it travels at all
    # because the browser is handed this dict whole: the delivered page is
    # opened from a link in a mail, in a tab that never ran the quiz, and the
    # PDF and the mail are built on a server that never had one either.
    #
    # A funnel with no tables, a run with no tallies and a combination the
    # tables do not name all store nothing and render exactly what they always
    # rendered.
    card = _profile_for(cfg, funnel_slug, style, tag_scores, choices)
    if card:
        visuals = dict(visuals or {})
        visuals["profile"] = card
    # The memory game's own figures, measured while the run still existed.
    # They travel for the same reason the hero card does and one more: the
    # delivered page prints the number the reader was shown before they paid,
    # and it opens in a tab that never played a round.
    if profile is BRAIN_PROFILE:
        numbers = _brain_numbers(cfg, style, tag_scores)
        if numbers:
            visuals = dict(visuals or {})
            visuals["brain"] = numbers
    # The twelve months this purchase's year map runs over, read off the clock
    # once and then treated as a fact about the purchase. The prompt is built
    # from it, the check that polices the answer is bound to it, and it is
    # stored — so a report generated in July still opens on July when it is
    # re-opened in September.
    months = _months_for(profile)
    if months:
        visuals = dict(visuals or {})
        visuals["year"] = list(months)
    # Same story: resolved once, while the run still exists. None on every
    # funnel that declares no purpose map.
    purpose = _purpose(cfg, choices)

    job = {
        "purchase_id": purchase_id, "cfg": cfg, "funnel": funnel_slug,
        "style_id": result_style, "name": name, "built": built, "paths": paths,
        "on_final": on_final, "content": None, "elements": elements,
        "visuals": visuals, "sign": sign, "purpose": purpose,
        "months": months,
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
        for section_id in _personal_order(cfg, funnel_slug):
            tasks.append({
                "ids": (section_id,), "cache": False,
                "future": pool.submit(
                    _generate, client,
                    _section_prompt(style, name, tag_scores, section_id,
                                    cfg, choices, funnel_slug, months),
                    (section_id,), _section_tokens(section_id),
                    profile["system"], profile["banned"],
                    profile["retry_detail"],
                    _verify_for(profile, style, months),
                    profile.get("json_retry"),
                    profile.get("json_repair")),
            })
        if cached is None:
            group = profile["cached"]
            tasks.append({
                "ids": group, "cache": True,
                "future": pool.submit(_generate, client,
                                      _cached_prompt(style, name, group,
                                                     funnel_slug),
                                      group, _group_tokens(group),
                                      profile["system"], profile["banned"],
                                      profile["retry_detail"],
                                      _verify_for(profile, style),
                                      profile.get("json_retry"),
                                      profile.get("json_repair")),
            })
    job["tasks"] = tasks
    job["pool"] = pool

    if not tasks:
        # No model, no style, no key: the whole thing is stubs, and there is
        # nothing to wait for.
        for section_id in [s.get("id") for s in cfg.get("report", {}).get("sections", [])]:
            if section_id not in built:
                built[section_id] = _stub_for(section_id, name, style,
                                              profile["stubs"], months,
                                              profile.get("stub_colors"))
                paths[section_id] = "stub"
        content = _assemble(cfg, funnel_slug, result_style, name, built, paths,
                            True, elements, visuals, sign, purpose)
        database.execute(
            INSERT_SQL, (purchase_id, json.dumps(content, separators=(",", ":")))
        )
        log.info("report %s for purchase %s (no generation)",
                 content["version"], purchase_id)
        _fire(on_final, content, purchase_id)
        return content

    opening = _assemble(cfg, funnel_slug, result_style, name, built, paths,
                        False, elements, visuals, sign, purpose)
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


def copy_style_cache(from_slug, to_slug, style_id):
    """Copy one style's cached sections between two funnels. Console use only.

    The cache is keyed on (funnel, style_id, section_id), so a funnel cloned
    from another starts cold even though its styles are the same objects with
    the same blurbs and the same reveals — the three cached sections it would
    generate are the ones already sitting under the funnel it was cloned from.
    Copying them is the difference between a clone costing nothing and a clone
    costing a model call per style per section.

    Only current-schema rows are copied, and only into sections the
    destination does not already have: this never overwrites something a real
    purchase generated, and it can never seed a stale row into a fresh funnel.

    Returns the same dict shape as warm_style_cache, with the copied sections
    under "warmed" so one summary can print both.
    """
    def result(status, **extra):
        out = {"funnel": to_slug, "style": style_id, "status": status,
               "cached": [], "warmed": [], "failed": [], "stale": 0}
        out.update(extra)
        return out

    for slug in (from_slug, to_slug):
        try:
            config.load_funnel(slug)
        except KeyError:
            return result("skipped", detail="no such funnel: %s" % slug)

    source, _ = _cache_state(from_slug, style_id)
    have, stale = _cache_state(to_slug, style_id)
    if source is None or have is None:
        return result("failed", detail="cache read failed")

    wanted = cached_sections(to_slug)
    present = [s for s in wanted if s in have]
    missing = [s for s in wanted if s not in have]
    if not missing:
        return result("cached", cached=present, stale=stale)

    copyable = {s: source[s] for s in missing if s in source}
    if not copyable:
        return result("failed", cached=present, failed=missing,
                      detail="%s has nothing to copy" % from_slug)

    _write_cache(to_slug, style_id, copyable)

    # Read back rather than assume: a write that did not land would otherwise
    # be reported as a warm cache and found by the first buyer.
    have, stale = _cache_state(to_slug, style_id)
    have = have or {}
    still = [s for s in wanted if s not in have]
    copied = sorted(copyable)
    if still:
        return result("partial" if len(still) < len(missing) else "failed",
                      cached=present, warmed=copied, failed=still, stale=stale,
                      detail="copied from %s" % from_slug)
    return result("warmed", cached=present, warmed=copied, stale=stale,
                  detail="copied from %s" % from_slug)


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

    wanted = cached_sections(funnel_slug)
    present = [s for s in wanted if s in have]
    missing = [s for s in wanted if s not in have]
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
            profile = _profile(funnel_slug)
            got = _generate(client,
                            _cached_prompt(style, name, (section_id,),
                                           funnel_slug),
                            (section_id,), _warm_tokens(section_id),
                            profile["system"], profile["banned"],
                            profile["retry_detail"],
                            _verify_for(profile, style),
                            profile.get("json_retry"),
                            profile.get("json_repair"))
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
  /* The page number moves right so the wordmark can have the left. Every page
     of a document somebody keeps should say where it came from — a printed
     page that has been separated from its first one is otherwise anonymous. */
  @bottom-left {
    content: "mazzin.com";
    font-family: %(sans)s;
    font-size: 9pt;
    color: #9aa0a6;
  }
  @bottom-right {
    content: counter(page);
    font-family: %(sans)s;
    font-size: 9pt;
    color: #9aa0a6;
  }
}
/* The cover carries the logo itself, so it needs neither. */
@page :first {
  margin-top: 48mm;
  @bottom-left { content: ""; }
  @bottom-right { content: ""; }
}

body { font-family: %(sans)s; font-size: 11pt; line-height: 1.65; color: #3d424c; }

/* The cover owns its page. Without this the sections start under the title
   and the two collide with no space between them. */
.cover { break-after: page; }

/* The wordmark, at the size it is drawn at rather than stretched to a box:
   the SVG carries its own aspect ratio and a height alone keeps it. */
.cover-logo {
  height: 9mm;
  margin: 0 0 12mm;
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

/* the two photographs the report carries. Fixed heights and object-fit, so a
   gallery image that is not the ratio this expects is cropped rather than
   allowed to push a section onto another page. */
figure { margin: 0 0 4mm; break-inside: avoid-page; }
figure img { display: block; width: 100%%; object-fit: cover; }
figure figcaption {
  padding: 1.6mm 2.5mm;
  font-size: 8pt;
  font-weight: 600;
  color: #6b7280;
  background: #f6f7f9;
}
.board img { height: 42mm; }
.shots { display: flex; gap: 3mm; margin: 0 0 4mm; }
.shots figure { flex: 1 1 0; min-width: 0; margin: 0; }
.shots img { height: 32mm; }

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

# The zodiac PDF. An override sheet rather than a second copy of the one
# above: the layout, the page furniture, the figure boxes and every break rule
# are shared and correct, and what differs between the two documents is the
# colour of the paper. Restating a hundred and sixty lines to change a dozen
# of them is how two stylesheets start disagreeing about margins.
#
# WeasyPrint honours `background` on `@page`, so the ground is real ink on
# every page rather than a box that stops where the content does.
ZODIAC_PDF_CSS = """
@page { background: #0E1430; }
@page :first { background: #0E1430; }

/* Every selector the sheet above paints in one of its four inks, restated in
   this document's. The list is not written from memory — the first pass
   guessed at class names, and `.swatch-name` and `.saves` do not exist, so
   four colour names and a whole Save block rendered near-black on near-black
   and were simply gone from the page. These are the selectors the base sheet
   actually uses, taken from it.
   #16181d -> #EDEFF6, #3d424c -> #C3C9E4, #6b7280 -> #868FB6,
   #9aa0a6 -> #6E77A0, and #C05621 -> the gold. */
body { color: #C3C9E4; }

.cover-name,
.section-title,
.callout,
.swatch-text b,
.numbered b,
.verdict b,
.skip b,
.saves b,
.implication { color: #EDEFF6; }

.cover-lead,
.cover-note,
figure figcaption { color: #868FB6; }

.hex { color: #A8AECC; }
.struck { color: #6E77A0 !important; }

/* The accent, everywhere the base sheet reaches for rust. */
.rule,
.section-title .bar { background: #E8C878; }
.meta,
.fix,
.num,
.splurge b { color: #E8C878; }
.where { color: #C3C9E4; }

/* Panels and rules: the same boxes, drawn on dark. */
.callout,
.splurge { background: #141B3C; border-color: #2C355F; }
.callout { border-left-color: #E8C878; }
.splurge { border-color: #E8C878; }
.skip,
.verdict,
.numbered { border-color: #2C355F; }
.dot { border-color: rgba(255, 255, 255, 0.28); }
figure figcaption { background: #141B3C; }
.badge.works { background: #22321F; color: #A8D8B0; }
.badge.avoid { background: #32222A; color: #E8A8A8; }

/* The cover is the hero card off the result page, on paper: the same kicker,
   the same sign over archetype, the same element bar. Somebody who paid on
   that page and then opens this file should recognise it as the same
   document, not as a printout of a different product. */
.cover { text-align: center; }
.cover-logo { margin-left: auto; margin-right: auto; }
.cover-kicker {
  margin: 0 0 7mm;
  font-size: 9pt;
  font-weight: 600;
  letter-spacing: 0.22em;
  text-transform: uppercase;
  color: #E8C878;
}
.cover-card {
  padding: 13mm 10mm 11mm;
  border: 0.3mm solid #2C355F;
  border-radius: 4mm;
  background: #141B3C;
}
.cover-card .cover-name { margin-bottom: 0; }
.cover-x {
  margin: 3mm 0 0;
  font-size: 15pt;
  font-weight: 600;
  color: #E8C878;
}
.cover-card .rule { margin: 7mm auto 6mm; }
.cover-blurb { margin: 0 0 9mm; font-size: 11pt; color: #C3C9E4; }

/* Four cells on one line, as inline-blocks rather than a flex row: the row is
   short, and flex containers and page breaks are a fight this document has no
   reason to pick. */
.cover-el {
  display: inline-block;
  margin: 0 1.1mm;
  padding: 1.7mm 4mm;
  border: 0.25mm solid #2C355F;
  border-radius: 8mm;
  font-size: 8.5pt;
  font-weight: 600;
  letter-spacing: 0.1em;
  text-transform: uppercase;
  color: #868FB6;
}
.cover-el-dot {
  display: inline-block;
  width: 2.2mm;
  height: 2.2mm;
  margin-right: 1.8mm;
  border-radius: 50%;
  opacity: 0.45;
}
.cover-el.own {
  color: #E8C878;
  border-color: rgba(232, 200, 120, 0.45);
  background: rgba(232, 200, 120, 0.10);
}
.cover-el.own .cover-el-dot { opacity: 1; }
.cover-note { text-align: center; }

/* --- the rich cover ------------------------------------------------------

   The hero card as the reader was shown it: left-aligned, because it is a
   document about them rather than a title page. Nothing in here is a flex
   container — this page is paginated, and inline-blocks and one two-cell
   table go where they are told. */
.cover-card.rich { padding: 10mm 9mm 9mm; text-align: left; }
.cover-top { width: 100%; border-collapse: collapse; }
.cover-top-glyph { width: 24mm; vertical-align: middle; }
.cover-top-id { vertical-align: middle; padding-left: 5mm; }
.cover-card.rich .cover-glyph {
  width: 20mm;
  height: 20mm;
  margin: 0;
}
.cover-card.rich .cover-glyph img { height: 20mm; }
.cover-subtype {
  margin: 0;
  font-family: "Mazzin Serif", Georgia, "Times New Roman", serif;
  font-size: 22pt;
  font-weight: 600;
  line-height: 1.12;
  letter-spacing: -0.01em;
  color: #EDEFF6;
}
.cover-formula {
  margin: 2mm 0 0;
  font-size: 9pt;
  font-weight: 600;
  letter-spacing: 0.03em;
  color: #E8C878;
}
.cover-ribbon {
  display: inline-block;
  margin: 7mm 0 0;
  padding: 1.8mm 4mm;
  border: 0.25mm solid rgba(232, 200, 120, 0.45);
  border-radius: 8mm;
  font-size: 8.5pt;
  font-weight: 700;
  letter-spacing: 0.04em;
  color: #221A05;
  background: #E8C878;
}
.cover-scales { margin: 7mm 0 0; }
/* Zero on the row and back up on its children: the gap between two
   inline-blocks is a space character, and three of them would push the right
   pole off the card. */
.cover-scale { margin: 0 0 3.5mm; font-size: 0; }
.cover-pole {
  display: inline-block;
  width: 22%;
  font-size: 7.5pt;
  font-weight: 700;
  letter-spacing: 0.08em;
  text-transform: uppercase;
  color: #868FB6;
}
.cover-pole.right { text-align: right; }
/* The track is as tall as the dot, and the rule is painted through the middle
   of it as a background band rather than drawn as a child. A child would be
   either a block in an inline row or a third inline-block to keep aligned;
   the band is neither and cannot be knocked out of place. */
.cover-track {
  display: inline-block;
  width: 56%;
  height: 3.4mm;
  vertical-align: middle;
  white-space: nowrap;
  background: linear-gradient(to bottom,
    transparent 0, transparent 1.3mm,
    rgba(255, 255, 255, 0.14) 1.3mm, rgba(255, 255, 255, 0.14) 2.1mm,
    transparent 2.1mm, transparent 3.4mm);
}
.cover-run { display: inline-block; height: 3.4mm; vertical-align: top; }
.cover-dot {
  display: inline-block;
  width: 3.4mm;
  height: 3.4mm;
  margin-left: -1.7mm;
  vertical-align: top;
  border-radius: 50%;
  background: #E8C878;
}
/* --- the minimal card ----------------------------------------------------

   result_zodiac.js's lux arm, in print units. Same blocks in the same order:
   the frame and its four marks, the capsules where the formula was, the lit
   pole on each scale, the figures inside the split and the names under it,
   the reading as the loudest sentence on the card, and the rarity on a card
   of its own below. Nothing here is invented — where the page uses a shadow
   or a radial gradient this uses the flat colour under it, because a print
   sheet has no screen to glow on. */
.cover-card.rich.lux {
  position: relative;
  border: 0.35mm solid #C4A660;
  border-radius: 5mm;
  padding: 8mm 8mm 6mm;
  break-inside: avoid-page;
}
.cover-card.lux .cover-scales { margin-top: 4mm; }
.cover-card.lux .cover-split { margin-top: 4mm; }
.cover-card.lux .cover-band { margin-top: 5mm; }
.cover-card.lux .cover-band img { height: 15mm; }
/* The closing note sits under the rarity card on this layout rather than
   under the hero, and the cover has to end on its own page. */
.cover-rare + .cover-note { margin-top: 4mm; }
.cover-corner {
  position: absolute;
  font-size: 7pt;
  line-height: 1;
  color: #C4A660;
}
.cover-corner.is-tl { top: 2.5mm; left: 3mm; }
.cover-corner.is-tr { top: 2.5mm; right: 3mm; }
.cover-corner.is-bl { bottom: 2.5mm; left: 3mm; }
.cover-corner.is-br { bottom: 2.5mm; right: 3mm; }
/* A short rule under the name, the width of a word rather than of the column:
   an accent, not a divider. */
.cover-card.lux .cover-subtype { font-size: 19pt; }
.cover-rule {
  width: 14mm;
  height: 0.6mm;
  margin: 2.6mm 0 0;
  border-radius: 0.6mm;
  background: #C4A660;
}
/* The formula, as capsules. */
.cover-chips { margin: 3mm 0 0; padding: 0; list-style: none; font-size: 0; }
.cover-chip {
  display: inline-block;
  margin: 0 1.6mm 1.6mm 0;
  padding: 0.9mm 2.6mm;
  border: 0.25mm solid rgba(196, 166, 96, 0.55);
  border-radius: 6mm;
  font-size: 7pt;
  font-weight: 700;
  letter-spacing: 0.08em;
  text-transform: uppercase;
  color: #C4A660;
}
/* The side a scale leans to is lit and the other is not, so the row reads
   before the dot is found. */
.cover-pole.is-active { color: #E8C878; }
.cover-run.is-lit { background: rgba(196, 166, 96, 0.42); }
/* Taller, with the figure inside its own block where the block is wide
   enough to hold it. Centred by line-height rather than by a flex rule: this
   page is paginated and inline-blocks go where they are told. */
.cover-card.lux .cover-splitbar { height: 6.5mm; border-radius: 2mm; }
.cover-card.lux .cover-seg {
  height: 6.5mm;
  line-height: 6.5mm;
  text-align: center;
}
.cover-seg-pct {
  font-size: 7.5pt;
  font-weight: 800;
  letter-spacing: 0.02em;
  /* Dark on the element's own colour, which is the only ink that holds on
     all four of them. */
  color: #0E1430;
}
/* The names under the bar, each the width of the block it names, so the word
   and the colour are the same measurement twice. */
.cover-splitnames { margin: 2.4mm 0 0; font-size: 0; }
.cover-splitname {
  display: inline-block;
  overflow: hidden;
  font-size: 6.5pt;
  font-weight: 700;
  letter-spacing: 0.06em;
  text-transform: uppercase;
  text-align: center;
  vertical-align: top;
  white-space: nowrap;
}
/* The reading is the sentence this card is for. It was set as an aside under
   a rule; it is the primary text here. */
.cover-crossline.is-bright {
  margin: 4mm 0 0;
  font-size: 11pt;
  line-height: 1.45;
  color: #EDEFF6;
}
.cover-star { margin-right: 2mm; font-size: 9pt; color: #C4A660; }
/* The rarity, as a card: the frame of the claim, the number at the size the
   claim deserves, and one line about what it is worth. */
.cover-rare {
  margin: 4mm auto 0;
  padding: 4mm 6mm 4mm;
  max-width: 82mm;
  border: 0.35mm solid #C4A660;
  border-radius: 5mm;
  background: rgba(196, 166, 96, 0.07);
  text-align: center;
  /* Whole or on the next page, never torn at the fold. */
  break-inside: avoid-page;
}
.cover-rare-lead,
.cover-rare-tail {
  margin: 0;
  font-size: 8pt;
  font-weight: 600;
  letter-spacing: 0.14em;
  text-transform: uppercase;
  color: #868FB6;
}
/* The number is the argument, so it is the size of one. */
.cover-rare-figure {
  margin: 0.5mm 0 0;
  font-family: "Mazzin Serif", Georgia, "Times New Roman", serif;
  font-size: 28pt;
  font-weight: 800;
  line-height: 1;
  letter-spacing: -0.03em;
  color: #C4A660;
}
.cover-rare-note {
  margin: 3mm 0 0;
  font-size: 9.5pt;
  font-weight: 700;
  line-height: 1.4;
  color: #C4A660;
}
/* Each half of the sentence on its own line, so the break is where the
   sentence turns rather than where the box happens to end. */
.cover-rare-noteline { display: block; }

.cover-split { margin: 8mm 0 0; }
.cover-splitbar {
  height: 2.4mm;
  font-size: 0;
  border-radius: 2mm;
  overflow: hidden;
  background: rgba(255, 255, 255, 0.10);
}
.cover-seg { display: inline-block; height: 2.4mm; vertical-align: top; }
.cover-splitcap {
  margin: 2.5mm 0 0;
  font-size: 8pt;
  letter-spacing: 0.04em;
  color: #A8AECC;
}
.cover-hair {
  height: 0;
  margin: 6mm 0 0;
  border-top: 0.25mm solid #2C355F;
}
.cover-crossline {
  margin: 4.5mm 0 0;
  font-size: 10pt;
  line-height: 1.5;
  color: #A8AECC;
}

/* The path. A hairline down the left of every section and a gold node on each
   title, which is the constellation on the web page redrawn in the one way
   print can hold it. The node hangs in the gutter on a negative margin: it is
   part of the title line, so it can never be orphaned from its heading, and a
   section that breaks across pages keeps the line running down both. */
.section {
  padding-left: 11mm;
  border-left: 0.3mm solid #2C355F;
}
/* --- the photographs, which are the reader's own ------------------------- */

/* One per section, framed the way the page frames them: rounded, on a
   hairline of the node gold. `break-inside: avoid` is inherited from the
   base sheet's `figure`, so a picture is never split across two pages. */
.tap {
  margin: 0 0 5mm;
  border: 0.25mm solid rgba(232, 200, 120, 0.30);
  border-radius: 2.5mm;
  overflow: hidden;
}
.tap img { height: 34mm; }
.tap figcaption {
  padding: 1.4mm 2.5mm;
  font-size: 7.5pt;
  letter-spacing: 0.08em;
  text-transform: uppercase;
  background: #141B3C;
  border-top: 0.2mm solid #2C355F;
}

/* The sign's own frame, on the cover, masked to a disc the way the card on
   the page masks it. */
.cover-glyph {
  width: 30mm;
  height: 30mm;
  margin: 0 auto 7mm;
  border: 0.4mm solid rgba(232, 200, 120, 0.55);
  border-radius: 50%;
  overflow: hidden;
}
.cover-glyph img { height: 30mm; }

/* And the horizon they chose, under the element bar. */
.cover-band {
  margin: 9mm 0 0;
  border: 0.25mm solid rgba(232, 200, 120, 0.30);
  border-radius: 2.5mm;
  overflow: hidden;
}
.cover-band img { height: 26mm; }
/* The heading, the picture that illustrates it and the paragraph that
   picture sits beside are one block that cannot be broken.

   `break-after: avoid-page` on the heading alone was not enough: it keeps the
   heading with whatever follows it, and what follows is a table WeasyPrint is
   free to break between its own rows. So the heading ended a page and its
   picture opened the next one, a screen away from the section it illustrates
   — "Rooftop under stars" alone at the top of page 5. One avoid-break box
   around all three is the fix, and it holds whichever way the text above it
   happens to fall.

   Only this sheet carries it: the section picture is a zodiac idea, and
   kitchen's document has no such picture to orphan. */
.section-open { break-inside: avoid-page; }
/* And the picture never leaves the paragraph it was set beside. */
.media { break-inside: avoid-page; }

.cover-band figcaption {
  padding: 1.4mm 2.5mm;
  font-size: 7.5pt;
  letter-spacing: 0.08em;
  text-transform: uppercase;
  background: #0E1430;
  border-top: 0.2mm solid #2C355F;
}

/* --- the contact sheet ---------------------------------------------------

   Every frame of the run, six to a row, the way the result page draws it.
   Inline-blocks on a zeroed line rather than a grid: this page is paginated,
   and the whole sheet has to stay together. */
.taps { margin: 0 0 9mm; break-inside: avoid-page; }
.taps-cap {
  margin: 0 0 3mm;
  font-size: 8pt;
  font-weight: 600;
  letter-spacing: 0.08em;
  text-transform: uppercase;
  color: #868FB6;
}
/* A fixed table, sized by its cells rather than by a percentage.
   Percentages were the whole problem: six sixths plus six gutters rounds past
   a hundred and wraps to five. A square stated in millimetres cannot round
   into a different number of columns, and 6 x 26.8 + 7 x 1.4 is 170.6mm
   inside a 174mm column.

   The square is stated on both axes for the same reason. `aspect-ratio` is
   honoured here but loses to a replaced element's own ratio, and the sheet
   draws frames from three different print boxes — a 900x154 horizon among
   the 200x200 squares came out a fifth of the height of its neighbours. Two
   explicit lengths and `object-fit: cover` is the only version of this that
   does not depend on what the source happens to be. */
.tapgrid {
  table-layout: fixed;
  border-collapse: separate;
  border-spacing: 1.4mm;
  margin: 0 -1.4mm;
}
.tapcell { padding: 0; vertical-align: top; }
/* The frame is on the image rather than on the cell: an empty cell — the
   padding at the end of a run whose count is not a multiple of six — should
   draw nothing at all. */
.tapcell img {
  display: block;
  width: 26.8mm;
  height: 26.8mm;
  object-fit: cover;
  border: 0.2mm solid rgba(232, 200, 120, 0.30);
  border-radius: 1.5mm;
}

.section-title .node {
  display: inline-block;
  width: 7mm;
  height: 7mm;
  margin-left: -14.5mm;
  margin-right: 1.5mm;
  border-radius: 50%;
  background: #E8C878;
  color: #0E1430;
  font-size: 10pt;
  font-weight: 700;
  line-height: 7mm;
  text-align: center;
  vertical-align: 0.8mm;
}
"""


# The profile is declared long before the PDF section, so its stylesheet is
# attached here, where the constant exists.
ZODIAC_PROFILE["pdf_css"] = ZODIAC_PDF_CSS
ZODIAC_RO_PROFILE["pdf_css"] = ZODIAC_PDF_CSS
ZODIAC_BG_PROFILE["pdf_css"] = ZODIAC_PDF_CSS

# The persona document is the same dark paper — it was sold on a dusk page and
# the file has to open as that document — with the cover's own furniture added
# on top: the totem and the head side by side, the legend under them, and the
# essence line the zodiac cover has no equivalent of.
PERSONA_PDF_CSS = ZODIAC_PDF_CSS + """
.cover-pair { width: 100%; border-collapse: collapse; margin: 0 0 10px; }
.cover-pair td { vertical-align: bottom; padding: 0 6px; }
.cover-totem { width: 43%; }
.cover-head { width: 57%; }
.cover-totem-art { display: block; width: 100%; border-radius: 10px; }

/* The plate is the photograph; the inlay is positioned on its crown by the
   same four numbers the page uses, as a share of the plate rather than in
   pixels, so the mark lands in the same place at any print size. */
.head-plate { position: relative; display: block; width: 100%; }
.head-base { display: block; width: 100%; border-radius: 10px; }
.head-inlay { position: absolute; }
.head-svg { display: block; width: 100%; height: 100%; }

.head-legend { margin: 2px 0 10px; text-align: center; }
.head-key { display: inline-block; margin: 0 7px; font-size: 8.5pt;
            color: #C9BBA8; }
.head-arrow { font-style: normal; margin-right: 3px; opacity: 0.75; }
.head-value { margin-left: 4px; color: #F2E6D4; }

.cover-essence { margin: 4px 0 0; font-size: 10pt; color: #C9BBA8; }

/* The frames, whole. The shared sheet draws a section's photograph as a
   full-width 34mm band and the contact sheet as a square, both filled with
   `object-fit: cover` — which is a third of a 3:4 sculpture thrown away on
   every page. These are the same slots at the frames' own shape, so the
   picture is scaled to fit rather than trimmed to fill.

   `contain` alone would not have been enough: the print copies under
   static/img/print were pre-cropped before the PDF ever saw them, so
   scripts/gen_print_variants.py writes this funnel's at 3:4 as well. */
/* A media object built from table cells rather than a float — see
   `_pdf_opening` in this file for why a float cannot be used here. */
.media {
  width: 100%;
  border-collapse: collapse;
  margin: 0 0 2mm;
}
.media-shot { width: 30mm; padding: 0 5mm 0 0; vertical-align: top; }
.media-text { vertical-align: top; }
.media-text > * { margin-top: 0; }

.tap {
  width: 30mm;
  margin: 0;
}
.tap img {
  width: 30mm;
  height: 40mm;
  object-fit: contain;
  background: #CEA371;
}
/* Normal case: the label is the reader's own words, not a code. */
.tap figcaption {
  font-size: 6.5pt;
  letter-spacing: 0;
  text-transform: none;
  line-height: 1.3;
}
/* Every section contains its own float.

   This was `.section-body::after`, a clearfix on a class this document does
   not have — the wrapper is `.section` — so the float was never contained at
   all. In print that is not a wrapping nicety: a floated figure taller than
   its section's text carries on into the next one, and page 4 had the image
   sitting on top of the first strength's heading while page 5 had it over
   the month rail. The reader loses lines.

   `flow-root` gives the section its own block formatting context, which is
   the containment this needs; the clearfix after it is the same rule stated
   the old way, for a renderer that does not know the keyword. Both are
   harmless where the other works. */
/* No float to contain any more: the picture and the opening text are table
   cells. Kept as a block context so a future float cannot escape either. */
.section { display: flow-root; }

/* The contact sheet is covered edge to edge. Bands inside a grid of thirteen
   squares read as a broken sheet; whole frames are what the section slot
   above is for. */
.tapcell img {
  width: 26.8mm;
  height: 26.8mm;
  object-fit: cover;
  background: #CEA371;
}
"""

PERSONA_PROFILE["pdf_css"] = PERSONA_PDF_CSS


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


# Set for the length of one _pdf_html call. The section builders take only
# their own data — the same shape the browser's do — so the two photographs
# that belong to the document rather than to a section reach them this way
# rather than by widening six signatures for the sake of two.
#
# Thread-local, because it is not one call at a time: a report generates on a
# thread of its own and the PDF is built at the end of it, so two purchases
# landing together would otherwise race here and one reader would be sent the
# other's photographs. Nothing about that failure is visible in testing.
_pdf_state = threading.local()


def _pdf_visuals():
    if not hasattr(_pdf_state, "visuals"):
        _pdf_state.visuals = {}
    return _pdf_state.visuals


def _pdf_words():
    """What this document prints itself. Set once, at the top of _pdf_html.

    Same channel as the photographs and for the same reason: the six section
    builders take only their own data, exactly as the browser's do, and the
    language of the headings between them is the document's business rather
    than any one section's.
    """
    return getattr(_pdf_state, "words", None) or RENDER_WORDS


PRINT_DIR = "img/print"


def _print_src(image_id, item):
    """Where the PDF should read this photograph from.

    The print copy first. WeasyPrint embeds whatever it is handed at full
    resolution, and the gallery originals are screen-sized: two of them took a
    report from 28 KB to 1.9 MB, which is a mailbox problem rather than a
    quality one. scripts-side, `printvariants` writes a pre-cropped JPEG per
    image at the size the stylesheet actually draws.

    Falls back to the original if the variant is not on disk, because a heavy
    PDF is still a PDF and a missing one is not.
    """
    rel = os.path.join(PRINT_DIR, image_id + ".jpg")
    if os.path.isfile(os.path.join(config.STATIC_DIR, rel)):
        return rel
    src = item.get("img") or ""
    return src[len("/static/"):] if src.startswith("/static/") else src


def _pdf_asset(rel):
    """A static file's path for the PDF, or "" when it is not on disk.

    Relative for the same reason `_print_src` is: build_pdf renders with
    base_url=STATIC_DIR, and an absolute URL would make the file depend on
    the site being up when it is opened. Checked rather than assumed — a
    missing image is a broken box on a paid document, and returning nothing
    prints the page without it instead.
    """
    rel = (rel or "").lstrip("/")
    if not rel:
        return ""
    return rel if os.path.isfile(os.path.join(config.STATIC_DIR, rel)) else ""


def _pdf_image(image_id, cls, caption=None):
    """One <figure>, or "" when the id resolves to nothing.

    The src is relative because build_pdf renders with base_url=STATIC_DIR;
    an absolute URL would make the PDF depend on the site being up.
    """
    item = (_pdf_visuals().get("images") or {}).get(image_id)
    if not item:
        return ""
    src = _print_src(image_id, item)
    if not src:
        return ""
    label = ('<figcaption>%s</figcaption>' % _e(item.get("label"))
             if caption and item.get("label") else "")
    return '<figure class="%s"><img src="%s" alt="">%s</figure>' % (
        cls, _e(src), label)


def _pdf_palette(d):
    board = _pdf_image(_pdf_visuals().get("moodboard"), "board", True)
    rows = "".join(
        '<div class="swatch"><span class="dot" style="background:%s"></span>'
        '<div class="swatch-text"><b>%s</b> <span class="hex">%s</span>'
        '<span class="meta">%s &middot; %s</span><span class="where">%s</span>'
        "</div></div>"
        % (_e(c["hex"]), _e(c["name"]), _e(c["hex"]), _e(c["role"]),
           _e(c["finish"]), _e(c["where"]))
        for c in d["colors"]
    )
    return ('%s<p class="intro">%s</p>%s<p class="callout">%s</p>'
            % (board, _e(d["intro"]), rows, _e(d["closing_rule"])))


def _pdf_mistakes(d):
    return "".join(
        '<div class="numbered"><span class="num">%d</span>'
        '<div><b>%s</b><p>%s</p><p class="fix">%s %s</p></div></div>'
        % (i + 1, _e(m["title"]), _e(m["body"]), _e(_pdf_words()["fix"]),
           _e(m["fix"]))
        for i, m in enumerate(d["items"])
    )


def _pdf_materials(d):
    shots = "".join(_pdf_image(one, "shot", True)
                    for one in (_pdf_visuals().get("materials") or []))
    strip = '<div class="shots">%s</div>' % shots if shots else ""
    # The class stays the English verdict — it is what the stylesheet colours
    # the badge on — and only the word inside it is translated.
    badges = _pdf_words()["verdicts"]
    rows = "".join(
        '<div class="verdict"><b>%s</b> <span class="badge %s">%s</span>'
        "<p>%s</p></div>"
        % (_e(p["combo"]), p["verdict"],
           _e(badges.get(p["verdict"]) or p["verdict"].upper()), _e(p["why"]))
        for p in d["pairs"]
    )
    return ('%s<p class="intro">%s</p>%s<p class="callout">%s</p>'
            % (strip, _e(d["intro"]), rows, _e(d["rule"])))


def _pdf_shopping(d):
    items = "".join(
        '<div class="numbered"><span class="num">%d</span>'
        "<div><b>%s</b><p>%s</p></div></div>"
        % (i + 1, _e(it["name"]), _e(it["priority_note"]))
        for i, it in enumerate(d["items"])
    )
    if not d.get("skip"):
        return items
    skips = "".join(
        "<p><b class='struck'>%s</b> %s</p>" % (_e(s["name"]), _e(s["why"]))
        for s in d["skip"]
    )
    return ('%s<div class="skip"><b>%s</b>%s</div>'
            % (items, _e(_pdf_words()["skip"]), skips))


def _pdf_dna(d):
    paras = "".join("<p>%s</p>" % _e(p) for p in d["narrative"])
    lines = "".join('<p class="implication">&rarr; %s</p>' % _e(p)
                    for p in d["implications"])
    return paras + lines


def _pdf_splurge(d):
    words = _pdf_words()
    saves = "".join("<p><b>%s</b> %s</p>" % (_e(s["item"]), _e(s["why"]))
                    for s in d["saves"])
    return ('<div class="splurge"><b>%s &mdash; %s</b><p>%s</p></div>'
            '<div class="saves"><b>%s</b>%s</div>'
            '<p class="callout">%s</p>'
            % (_e(words["splurge"]), _e(d["splurge"]["item"]),
               _e(d["splurge"]["why"]), _e(words["save"]), saves,
               _e(d["split_note"])))


PDF_BODY = {
    "palette": _pdf_palette,
    "mistakes": _pdf_mistakes,
    "materials": _pdf_materials,
    "shopping": _pdf_shopping,
    "dna": _pdf_dna,
    "splurge": _pdf_splurge,
}


def _split_first_block(html):
    """(first top-level element, everything after it).

    A tag-depth scan rather than a regex: the builders emit nested markup and
    "the first `</p>`" is the wrong answer the moment a paragraph contains a
    span. Returns ("", html) for anything this cannot read, which puts the
    whole body below the picture rather than guessing.
    """
    if not html.startswith("<"):
        return "", html
    depth = 0
    i = 0
    n = len(html)
    while i < n:
        if html[i] != "<":
            i += 1
            continue
        close = html.find(">", i)
        if close < 0:
            return "", html
        tag = html[i + 1:close]
        if tag.startswith("/"):
            depth -= 1
            if depth == 0:
                return html[:close + 1], html[close + 1:]
        elif not tag.endswith("/") and tag.split(" ")[0] not in _VOID_TAGS:
            depth += 1
        i = close + 1
    return "", html


_VOID_TAGS = frozenset(("img", "br", "hr", "input", "meta", "link"))


def _pdf_opening(head, shot, body):
    """One section's heading, its picture and its opening text, as one block.

    Two things are held together here and they were broken by different
    faults.

    The picture sits beside the opening paragraph in two table cells rather
    than as a float. A floated figure is what this was, and in print it does
    not stay in its own section: a float taller than the text beside it
    carries into the next one, and WeasyPrint re-places it after a page break
    at the same offset — so the image landed on top of the first strength's
    heading on page 4 and across the month rail on page 5. `flow-root` and a
    clearfix on the section did not fix it, because the escape happens at the
    page break rather than at the end of the block. Two table cells cannot do
    that, and it is also the shape the layout wanted: text beside the picture,
    not a column of text running the whole length of a 30mm image.

    And the heading goes in the box with them. The table alone could still be
    broken away from the heading above it at a page boundary, which is how a
    picture came to open a page on its own with the section it illustrates a
    screen behind it. The whole opening is one unbreakable unit now.

    A section with no picture is left exactly as it was — heading, then body,
    no box. There is nothing to orphan there, `break-after: avoid-page` on the
    heading is the rule that block has always been held to, and kitchen's
    document prints character for character what it printed before.
    """
    if not shot:
        return head + body
    first, rest = _split_first_block(body)
    if not first:
        # Nothing this can read a first block out of: the picture leads and
        # the body follows it, still inside the unbreakable box.
        return '<div class="section-open">%s%s</div>%s' % (head, shot, body)
    return ('<div class="section-open">%s'
            '<table class="media"><tr>'
            '<td class="media-shot">%s</td>'
            '<td class="media-text">%s</td>'
            "</tr></table></div>%s" % (head, shot, first, rest))


def _pdf_section_body(section, structured, head=""):
    """One whole section — its heading and its body, whichever schema it came
    in on.

    The heading is passed in rather than concatenated by the caller because
    it belongs inside the unbreakable opening box with the picture: see
    `_pdf_opening`.
    """
    # The photograph this section was given, if the funnel names one. Here
    # rather than in the six builders: which picture belongs to a section is
    # the config's business, and threading it through every builder would put
    # kitchen's board and this in the same place for no reason.
    shot = _pdf_image(
        (_pdf_visuals().get("sections") or {}).get(section.get("id")),
        "tap", True)
    if structured:
        data = section.get("data")
        builder = PDF_BODY.get(section.get("id"))
        if builder and isinstance(data, dict):
            try:
                return _pdf_opening(head, shot, builder(data))
            except Exception:
                log.exception("pdf section %s failed", section.get("id"))
    # Schema 1, or a section that arrived without usable data.
    return _pdf_opening(head, shot, "<p>%s</p>" % _e(section.get("body")))


# Six to a row, the same as the result page's grid. Stated once, because the
# markup and the column width in the stylesheet have to agree and a second
# copy of the number is how they stop agreeing.
TAP_COLUMNS = 6

# The gallery's four families, in the order the result page draws them and in
# the same four inks. One document, one vocabulary.
PDF_ELEMENTS = [
    ("fire", "Fire", "#E08A3C"),
    ("earth", "Earth", "#7E9B5E"),
    ("air", "Air", "#9CC3DF"),
    ("water", "Water", "#4E8FA0"),
]

# The same four, for the funnel that names them in Romanian. Only the plain
# cover draws this strip — the rich one takes its split caption off the card
# the reader was shown, which is already the funnel's own copy.
PDF_ELEMENTS_RO = [
    ("fire", "Foc", "#E08A3C"),
    ("earth", "Pământ", "#7E9B5E"),
    ("air", "Aer", "#9CC3DF"),
    ("water", "Apă", "#4E8FA0"),
]

ZODIAC_RO_PROFILE["pdf_elements"] = PDF_ELEMENTS_RO

# And the same four for the Bulgarian cover.
PDF_ELEMENTS_BG = [
    ("fire", "Огън", "#E08A3C"),
    ("earth", "Земя", "#7E9B5E"),
    ("air", "Въздух", "#9CC3DF"),
    ("water", "Вода", "#4E8FA0"),
]

ZODIAC_BG_PROFILE["pdf_elements"] = PDF_ELEMENTS_BG


def _cover_scales(card, lean=False):
    """The three spectrum rows, as inline blocks rather than a flex row.

    Same reason the element cells below are: this document is paginated by
    WeasyPrint, and inline-blocks with percentage widths break where they are
    told to. The whitespace between them is killed by `font-size: 0` on the
    row, which is why the markup can stay readable.

    The dot is pushed along by an empty run rather than positioned absolutely.
    An absolute `left: 82%` puts the dot's left edge at 82 and hangs its whole
    width off the end of the track at 100; a run of 82% followed by a dot with
    half its width pulled back puts the dot's centre there, which is what a
    dot on a scale means.
    """
    rows = []
    for row in (card.get("scales") or []):
        if not row.get("left") or not row.get("right"):
            continue
        at = max(0, min(100, int(row.get("at") or 0)))
        # Which pole this row leans to. Under half is the left and over half
        # the right; dead level is neither, and neither is lit rather than one
        # of them being lit by rounding. `scaleRow`, in the same words.
        active = "left" if at < 50 else ("right" if at > 50 else "")
        lit = " is-active" if lean and active else ""
        # The run reads as a distance travelled from the lit side rather than
        # as a slider with a value on it, so on the minimal card it starts at
        # the lit pole. The dot is pushed along by an empty run either way —
        # an absolutely positioned dot hangs its whole width off the end of
        # the track at 100.
        if lean and active == "right":
            track = ('<span class="cover-run" style="width: %d%%"></span>'
                     '<i class="cover-dot"></i>'
                     '<span class="cover-run is-lit" style="width: %d%%">'
                     "</span>" % (at, 100 - at))
        else:
            run = "cover-run is-lit" if (lean and active == "left") \
                else "cover-run"
            track = ('<span class="%s" style="width: %d%%"></span>'
                     '<i class="cover-dot"></i>' % (run, at))
        rows.append(
            '<div class="cover-scale">'
            '<span class="cover-pole%s">%s</span>'
            '<span class="cover-track">%s</span>'
            '<span class="cover-pole right%s">%s</span></div>'
            % (lit if active == "left" else "", _e(row["left"]), track,
               lit if active == "right" else "", _e(row["right"])))
    return "".join(rows)


def _cover_split(card, lean=False):
    """The four elements as one bar, and what is written under it.

    Legacy: the caption that adds to a hundred. Minimal: the figure inside
    each block wide enough to hold it and the element names beneath at the
    same widths — result_zodiac.js's `splitBar(data, lean)`, which is where
    the twelve-percent floor comes from too.
    """
    cells = (card.get("split") or [])
    if not cells:
        return ""
    segments = []
    for cell in cells:
        pct = max(0, int(cell.get("pct") or 0))
        figure = ('<b class="cover-seg-pct">%d%%</b>' % pct) if (
            lean and pct >= SPLIT_LABEL_MIN_PCT) else ""
        segments.append(
            '<span class="cover-seg" style="width: %d%%; background: %s">'
            "%s</span>" % (pct, cell.get("color") or "#E8C878", figure))
    bar = '<div class="cover-splitbar">%s</div>' % "".join(segments)
    if not lean:
        return bar + ('<p class="cover-splitcap">%s</p>'
                      % _e(card.get("split_caption")))
    names = "".join(
        '<span class="cover-splitname" style="width: %d%%; color: %s">%s</span>'
        % (max(0, int(cell.get("pct") or 0)),
           cell.get("color") or "#E8C878",
           _e(cell.get("name") or cell.get("tag")))
        for cell in cells)
    return bar + '<div class="cover-splitnames">%s</div>' % names


# The page's own floor for printing a figure inside a segment, from
# result_zodiac.js. Below it the block is narrower than the number.
SPLIT_LABEL_MIN_PCT = 12

# The mark the minimal card sets in its corners and in front of the reading.
STAR = "\u2726"


def _cover_chips(cfg, card):
    """The formula as capsules, the way `chipRow` draws it, or "".

    Same source and same filling: the funnel's own `result_copy.profile.chips`
    templated with this reader's words, with any token the run could not fill
    dropped rather than printed. A funnel that declares no chips gets nothing
    here and keeps the formula line it has always had.
    """
    shapes = (_profile_table(cfg) or {}).get("chips") or []
    words = card.get("words") or {}
    cells = []
    for shape in shapes:
        text = _TOKEN_RE.sub("", _fill_tokens(shape, words)).strip()
        if text:
            cells.append('<li class="cover-chip">%s</li>' % _e(text))
    return ('<ul class="cover-chips">%s</ul>' % "".join(cells)) if cells else ""


def _different_pct(n):
    """How many readings do NOT land this blend — `differentPct` in the page.

    One number from one source: the same 1-in-N the ribbon was built from, so
    the card and the sentence can never disagree about how rare a blend is.
    """
    n = _minor_units(n)
    return int(round((1 - 1.0 / n) * 100)) if n and n >= 2 else 0


def _cover_rarity(cfg, card):
    """The rarity as its own card, or "" — `rarityBadge`'s first branch.

    The frame of the claim, the number at the size the claim deserves, and one
    line about what it is worth, all four strings read off the funnel's own
    `rarity_card` so each language prints its own. A funnel that declares none
    gets nothing: the legacy pill it used to print is gone from both layouts.
    """
    own = (_profile_table(cfg) or {}).get("rarity_card") or {}
    pct = _different_pct(card.get("rarity"))
    if not own.get("lead") or not pct:
        return ""
    parts = ['<p class="cover-rare-lead">%s</p>' % _e(own["lead"]),
             '<p class="cover-rare-figure">%d%%</p>' % pct]
    if own.get("tail"):
        parts.append('<p class="cover-rare-tail">%s</p>' % _e(own["tail"]))
    note = own.get("note")
    if note:
        # Broken at the em-dash rather than at whatever width the box is —
        # the break is where the sentence turns, so it is the same break in
        # any column. A translation carrying no dash gets one line rather
        # than a guess at where to cut it. `rarityNote`, exactly.
        halves = str(note).split("\u2014")
        if len(halves) == 2:
            parts.append(
                '<p class="cover-rare-note">'
                '<span class="cover-rare-noteline">%s \u2014</span>'
                '<span class="cover-rare-noteline">%s</span></p>'
                % (_e(halves[0].strip()), _e(halves[1].strip())))
        else:
            parts.append('<p class="cover-rare-note">%s</p>' % _e(note))
    return '<div class="cover-rare">%s</div>' % "".join(parts)


def _zodiac_rich_cover(content, profile, cfg, card):
    """The cover, when the report carries the hero the reader was shown.

    Every part of the card on the page, in the order the page has them, in
    whichever of the two layouts that page draws. Somebody who paid on that
    page and then opens this file should recognise it as the same document —
    which is exactly what stopped being true when the page moved to the
    minimal template and this kept printing the old one: the reader was shown
    a rarity card and four capsules, and was sent a "1 in N readings" pill and
    a formula line.

    Which layout is decided the way the page decides it, by what the funnel's
    own `result_copy.profile` carries. A funnel that declares no `chips` and
    no `rarity_card` — zodiac v1, persona, every kitchen — has no minimal arm
    on the page either, and gets this document exactly as it has always got
    it. Nothing here is a third design: every block below is
    result_zodiac.js's, in the same order, in print units.
    """
    table = _profile_table(cfg) or {}
    lean = bool(table.get("chips") or table.get("rarity_card"))
    hero = _pdf_visuals().get("hero") or {}
    glyph = _pdf_image(hero.get("glyph"), "cover-glyph")
    chips = _cover_chips(cfg, card) if lean else ""
    # The four corner marks the lux card carries. Decoration, and named as
    # such — `aria-hidden` on the page, and a print document has no reader to
    # hide them from.
    corners = "".join(
        '<span class="cover-corner is-%s">%s</span>' % (corner, STAR)
        for corner in ("tl", "tr", "bl", "br")) if lean else ""
    return [
        '<section class="cover">',
        '<img class="cover-logo" src="%s" alt="Mazzin">'
        % _e(profile.get("pdf_logo") or "brand/logo.svg"),
        '<p class="cover-kicker">%s</p>'
        % _e(((cfg or {}).get("result_copy") or {}).get("kicker")
             or profile["pdf_lead"]),
        '<div class="cover-card rich%s">' % (" lux" if lean else ""),
        corners,
        '<table class="cover-top"><tr>',
        ('<td class="cover-top-glyph">%s</td>' % glyph) if glyph else "",
        '<td class="cover-top-id">',
        '<h1 class="cover-subtype">%s</h1>' % _e(card.get("subtype")),
        '<div class="cover-rule"></div>' if lean else "",
        # The capsules stand in for the formula on the minimal card, exactly
        # as `richHero` swaps them: chips when the funnel has them, the
        # formula line when it does not.
        chips or (('<p class="cover-formula">%s</p>' % _e(card["formula"]))
                  if card.get("formula") else ""),
        "</td></tr></table>",
        # The legacy pill, for the legacy layout only. The minimal one gives
        # the rarity its own card below the hero instead, which is the whole
        # of the change the page made.
        (('<p class="cover-ribbon">%s</p>' % _e(card["rarity_line"]))
         if card.get("rarity_line") else "") if not lean else "",
        '<div class="cover-scales">%s</div>' % _cover_scales(card, lean),
        '<div class="cover-split">%s</div>' % _cover_split(card, lean),
        # The rule goes on the lux card: the reading is the loudest sentence
        # on it now, and a line above it makes it a footnote to the chart.
        (('' if lean else '<div class="cover-hair"></div>')
         + '<p class="cover-crossline%s">%s%s</p>'
         % (" is-bright" if lean else "",
            ('<span class="cover-star">%s</span>' % STAR) if lean else "",
            _e(card["cross_line"])))
        if card.get("cross_line") else "",
        _pdf_image(hero.get("band"), "cover-band", True),
        "</div>",
        _cover_rarity(cfg, card) if lean else "",
        '<p class="cover-note">%s</p>' % _e(profile.get("pdf_note") or ""),
        "</section>",
    ]


def _zodiac_cover(content, profile, cfg):
    """The zodiac cover: the result page's hero card, on paper.

    The element it lights is the archetype's own, read off the style's tags,
    not a tally — by the time a PDF is built the run is long gone, and a bar
    that prints a percentage nobody measured is worse than one that prints
    none. A config that would not load costs the blurb and the lit cell; the
    cover still names the sign, the archetype and the four elements.
    """
    # The rich card, when the report was written after it existed. Everything
    # below this is the cover every report before it got, and still gets.
    card = _pdf_visuals().get("profile") or {}
    if card.get("subtype"):
        return _zodiac_rich_cover(content, profile, cfg, card)

    style = _style(cfg, content.get("style_id")) if cfg else None
    hero = _pdf_visuals().get("hero") or {}
    tags = (style or {}).get("tags") or []
    strip = profile.get("pdf_elements") or PDF_ELEMENTS
    own = next((tag for tag, _n, _h in strip if tag in tags), "")
    cells = "".join(
        '<span class="cover-el%s">'
        '<i class="cover-el-dot" style="background: %s"></i>%s</span>'
        % (" own" if tag == own else "", hexcode, _e(label))
        for tag, label, hexcode in strip
    )
    name = _e(content.get("style_name") or _pdf_words()["style_fallback"])
    sign = _e(content.get("sign"))
    blurb = _e((style or {}).get("blurb"))
    return [
        '<section class="cover">',
        '<img class="cover-logo" src="%s" alt="Mazzin">'
        % _e(profile.get("pdf_logo") or "brand/logo.svg"),
        '<p class="cover-kicker">%s</p>'
        % _e(((cfg or {}).get("result_copy") or {}).get("kicker")
             or profile["pdf_lead"]),
        '<div class="cover-card">',
        _pdf_image(hero.get("glyph"), "cover-glyph"),
        '<h1 class="cover-name">%s</h1>' % (sign or name),
        ('<p class="cover-x">&#215; %s</p>' % name) if sign else "",
        '<div class="rule"></div>',
        ('<p class="cover-blurb">%s</p>' % blurb) if blurb else "",
        '<div class="cover-elements">%s</div>' % cells,
        _pdf_image(hero.get("band"), "cover-band", True),
        "</div>",
        '<p class="cover-note">%s</p>' % _e(profile.get("pdf_note") or ""),
        "</section>",
    ]


ZODIAC_PROFILE["pdf_cover"] = _zodiac_cover
ZODIAC_RO_PROFILE["pdf_cover"] = _zodiac_cover
ZODIAC_BG_PROFILE["pdf_cover"] = _zodiac_cover

# --- the persona cover, and the head on it ----------------------------------
#
# The reveal the reader bought is a photographed clay head with a radar
# pressed into its crown, and it has to survive the trip to paper: a PDF that
# printed the name and dropped the drawing would be selling one thing on
# screen and delivering another in the file.
#
# The drawing is reproduced rather than screenshotted. `headSvg` in
# static/js/result_persona.js writes its paint as presentation attributes for
# exactly this reason — there is no stylesheet of that page's here — so the
# same geometry, the same inks and the same numbers come out as a string of
# SVG that any renderer can take.

PERSONA_INLAY_SIZE = 240
PERSONA_HEAD_CX = 120
PERSONA_HEAD_CY = 120
PERSONA_HEAD_R = 96
PERSONA_LEAN_ARC = "M 24 44 Q 120 -6 216 44"
PERSONA_INK = "#241A10"
PERSONA_INK_SOFT = "#3A2A1B"
PERSONA_HEAD_BASE = "galleries/persona/head_base.webp"

# Where the inlay sits on the head, as a share of the plate. Measured against
# the render rather than guessed, and the same four numbers the stylesheet
# carries — see CSS_INLAY in scripts/gen_persona.py, which checks them.
PERSONA_INLAY_BOX = {"top": 0.8, "left": 15.3, "width": 68.0,
                     "height": 68.0}

# North is drive, east is prism, south is anchor, west is wave — the same four
# points, in the same order, as the drawing on the page.
PERSONA_HEAD_AXES = (("drive", 0, -1), ("prism", 1, 0),
                     ("anchor", 0, 1), ("wave", -1, 0))


def _persona_head_values(card):
    """The four traits as 0-100, scaled so the strongest reaches the rim.

    Shares of a hundred would put every polygon inside the middle ring and
    every reader's shape would look like everybody else's. The shape is the
    subject; the numbers are printed underneath it either way.
    """
    by = {}
    for cell in (card.get("split") or []):
        by[cell.get("tag")] = max(0, cell.get("pct") or 0)
    top = max([by.get(tag, 0) for tag in PERSONA_AXES] or [0])
    return dict((tag, int(round(100.0 * by.get(tag, 0) / top)) if top else 0)
                for tag in PERSONA_AXES)


def _persona_lean_at(card):
    for row in (card.get("scales") or []):
        if row.get("id") == "energy":
            return max(0, min(100, row.get("at", 50)))
    return 50


def _persona_lean_point(t):
    """A point on the crown's arc, at t along it. The same quadratic."""
    u = 1.0 - t
    return (u * u * 24 + 2 * u * t * 120 + t * t * 216,
            u * u * 44 + 2 * u * t * -6 + t * t * 44)


def _persona_head_svg(card):
    """The inlay, as a standalone SVG string. Empty when there is nothing."""
    values = _persona_head_values(card)
    if not any(values.values()):
        return ""
    parts = ['<svg viewBox="0 0 %d %d" xmlns="http://www.w3.org/2000/svg" '
             'class="head-svg">' % (PERSONA_INLAY_SIZE, PERSONA_INLAY_SIZE)]
    # The grid, as grooves pressed into the clay: darker than the surface
    # rather than lighter, because a groove in clay reads as a shadow.
    for r in (PERSONA_HEAD_R / 3.0, PERSONA_HEAD_R * 2 / 3.0, PERSONA_HEAD_R):
        parts.append('<circle cx="%d" cy="%d" r="%.1f" fill="none" '
                     'stroke="%s" stroke-width="1.2" stroke-opacity="0.5"/>'
                     % (PERSONA_HEAD_CX, PERSONA_HEAD_CY, r, PERSONA_INK))
    for x1, y1, x2, y2 in (
            (PERSONA_HEAD_CX, PERSONA_HEAD_CY - PERSONA_HEAD_R,
             PERSONA_HEAD_CX, PERSONA_HEAD_CY + PERSONA_HEAD_R),
            (PERSONA_HEAD_CX - PERSONA_HEAD_R, PERSONA_HEAD_CY,
             PERSONA_HEAD_CX + PERSONA_HEAD_R, PERSONA_HEAD_CY)):
        parts.append('<line x1="%d" y1="%d" x2="%d" y2="%d" stroke="%s" '
                     'stroke-width="1.2" stroke-opacity="0.5"/>'
                     % (x1, y1, x2, y2, PERSONA_INK))

    # The reader's own shape, cut deeper than the grid it sits on.
    points = []
    for tag, dx, dy in PERSONA_HEAD_AXES:
        r = PERSONA_HEAD_R * (values.get(tag) or 0) / 100.0
        points.append((PERSONA_HEAD_CX + dx * r, PERSONA_HEAD_CY + dy * r))
    parts.append('<polygon points="%s" fill="%s" fill-opacity="0.28" '
                 'stroke="%s" stroke-width="2.2" stroke-linejoin="round"/>'
                 % (" ".join("%.1f,%.1f" % p for p in points),
                    PERSONA_INK, PERSONA_INK))
    for x, y in points:
        parts.append('<circle cx="%.1f" cy="%.1f" r="4" fill="%s"/>'
                     % (x, y, PERSONA_INK))

    # The lean, over the crown: one dashed groove with a bead on it. Which way
    # the charge runs is a single number and deserves a single mark.
    parts.append('<path d="%s" fill="none" stroke="%s" stroke-width="1.2" '
                 'stroke-dasharray="3 5"/>'
                 % (PERSONA_LEAN_ARC, PERSONA_INK_SOFT))
    bead = _persona_lean_point(_persona_lean_at(card) / 100.0)
    parts.append('<circle cx="%.1f" cy="%.1f" r="5" fill="%s"/>'
                 % (bead[0], bead[1], PERSONA_INK))
    parts.append("</svg>")
    return "".join(parts)


def _persona_head_plate(card):
    """The clay head with its inlay on the crown, or "" without a base."""
    inlay = _persona_head_svg(card)
    if not inlay:
        return ""
    base = _pdf_asset(PERSONA_HEAD_BASE)
    if not base:
        return ""
    return (
        '<div class="head-plate">'
        '<img class="head-base" src="%s" alt="">'
        '<div class="head-inlay" style="top:%.1f%%;left:%.1f%%;'
        'width:%.1f%%;height:%.1f%%">%s</div>'
        "</div>"
        % (base, PERSONA_INLAY_BOX["top"], PERSONA_INLAY_BOX["left"],
           PERSONA_INLAY_BOX["width"], PERSONA_INLAY_BOX["height"], inlay))


def _persona_legend(card):
    """The four traits read out under the head, in the drawing's own order."""
    names = dict((cell.get("tag"), cell.get("name"))
                 for cell in (card.get("traits") or []))
    values = _persona_head_values(card)
    arrows = {"drive": "&#8593;", "prism": "&#8594;",
              "anchor": "&#8595;", "wave": "&#8592;"}
    cells = "".join(
        '<span class="head-key"><i class="head-arrow">%s</i>%s'
        '<b class="head-value">%d</b></span>'
        % (arrows.get(tag, ""),
           _e(names.get(tag) or PERSONA_AXIS_LABEL.get(tag, tag)),
           values.get(tag, 0))
        for tag, _dx, _dy in PERSONA_HEAD_AXES)
    return '<div class="head-legend">%s</div>' % cells


def _persona_cover(content, profile, cfg):
    """The persona cover: the delivered page's hero card, on paper.

    The same order the page has it in — the totem and the head side by side,
    the legend under them, then the name, the formula, the rarity and the
    four traits. Somebody who paid on that page and then opens this file
    should recognise it as the same document.

    Without a stored card there is nothing to draw and the ordinary cover is
    used instead, which is the cover every report before this one got.
    """
    card = _pdf_visuals().get("profile") or {}
    if not card.get("subtype"):
        return None
    totem = _pdf_asset((card.get("totem") or "").lstrip("/")
                       .replace("static/", "", 1))
    plate = _persona_head_plate(card)
    return [
        '<section class="cover">',
        '<img class="cover-logo" src="%s" alt="Mazzin">'
        % _e(profile.get("pdf_logo") or "brand/logo.svg"),
        '<p class="cover-kicker">%s</p>'
        % _e(((cfg or {}).get("result_copy") or {}).get("kicker")
             or profile["pdf_lead"]),
        '<div class="cover-card rich">',
        '<table class="cover-pair"><tr>',
        ('<td class="cover-totem">'
         '<img class="cover-totem-art" src="%s" alt=""></td>' % totem)
        if totem else "",
        ('<td class="cover-head">%s</td>' % plate) if plate else "",
        "</tr></table>",
        _persona_legend(card) if plate else "",
        '<h1 class="cover-subtype">%s</h1>' % _e(card.get("subtype")),
        ('<p class="cover-essence">%s</p>' % _e(card["essence"]))
        if card.get("essence") else "",
        ('<p class="cover-formula">%s</p>' % _e(card["formula"]))
        if card.get("formula") else "",
        ('<p class="cover-ribbon">%s</p>' % _e(card["rarity_line"]))
        if card.get("rarity_line") else "",
        '<div class="cover-split">%s</div>' % _cover_split(card),
        "</div>",
        '<p class="cover-note">%s</p>' % _e(profile.get("pdf_note") or ""),
        "</section>",
    ]


PERSONA_PROFILE["pdf_cover"] = _persona_cover



def _pdf_taps(cfg):
    """The reader's whole run as a contact sheet, or "".

    The same grid the result page draws and for the same reason: the claim
    above it is that this reading was read off these frames, and five of
    eighteen is a sample rather than a record. Six to a row, unlabelled, in
    the order they were tapped.

    Its own block rather than another row on the cover — the cover is already
    a full page — so it opens the second one, over the first chapter.

    A table, and a fixed one. Inline-blocks at a sixth of the width each did
    not survive contact with a paginator: six of them plus their gutters
    rounded past a hundred percent and wrapped to five, so eighteen frames
    came out 5/5/5/3 in four rows instead of 3 x 6. A fixed-layout table
    takes its column widths from the row rather than from the sum of its
    children, which is the one thing that cannot round wrong. The last row is
    padded out to six so every row is the same row.
    """
    ids = _pdf_visuals().get("taps") or []
    caption = ((cfg or {}).get("result_copy") or {}).get("taps_caption") \
        or _pdf_words()["taps_caption"]
    cells = []
    for image_id in ids:
        item = (_pdf_visuals().get("images") or {}).get(image_id)
        src = _print_src(image_id, item) if item else ""
        if src:
            cells.append('<td class="tapcell"><img src="%s" alt=""></td>'
                         % _e(src))
    if len(cells) < 4:
        return ""
    while len(cells) % TAP_COLUMNS:
        cells.append('<td class="tapcell"></td>')
    rows = ["<tr>%s</tr>" % "".join(cells[n:n + TAP_COLUMNS])
            for n in range(0, len(cells), TAP_COLUMNS)]
    return ('<section class="taps"><p class="taps-cap">%s</p>'
            '<table class="tapgrid">%s</table></section>'
            % (_e(caption), "".join(rows)))


def _pdf_html(content):
    structured = _is_schema2(content.get("version"))
    profile = _profile(content.get("funnel"))
    # What this document prints itself, for the length of this call. Set
    # before anything is built, because the cover reads it too.
    words = _words(profile)
    _pdf_state.words = words
    name = _e(content.get("style_name") or words["style_fallback"])
    # Same sheet, then the funnel's own ink over it. A funnel with no override
    # renders the document it always did, character for character.
    sheet = PDF_CSS % PDF_FONTS + (profile.get("pdf_css") or "")

    # The two photographs the document carries, resolved once against the
    # funnel this report was written for. A config that cannot be loaded costs
    # the pictures and nothing else — a report without them is still a report.
    state = _pdf_visuals()
    state.clear()
    visuals = content.get("visuals") or {}
    cover = profile.get("pdf_cover")
    cfg = None
    if visuals or cover:
        try:
            cfg = config.load_funnel(content.get("funnel"))
        except (KeyError, ValueError, OSError):
            cfg = None
    if visuals and cfg is not None:
        state["images"] = _images_by_id(cfg)
        state["moodboard"] = visuals.get("moodboard")
        state["materials"] = list(visuals.get("materials") or [])
        state["sections"] = dict(visuals.get("sections") or {})
        state["hero"] = dict(visuals.get("hero") or {})
        state["profile"] = dict(visuals.get("profile") or {})
        state["taps"] = list(visuals.get("taps") or [])

    if cover:
        blocks = [block for block in cover(content, profile, cfg) if block]
    else:
        blocks = [
        '<section class="cover">',
            # Resolved against config.STATIC_DIR, which is the base_url
            # build_pdf renders with. A missing file loses the logo and
            # nothing else.
            '<img class="cover-logo" src="%s" alt="Mazzin">'
            % _e(profile.get("pdf_logo") or "brand/logo.svg"),
            '<p class="cover-lead">%s</p>'
            % _e(profile["pdf_lead"]),
            '<h1 class="cover-name">%s</h1>'
            % (("%s <span class=\"cover-cross\">&#215; %s</span>"
                % (_e(content.get("sign")), name)) if content.get("sign")
               else name),
            '<div class="rule"></div>',
            '<p class="cover-note">%s</p>' % _e(
                profile.get("pdf_note") or words["pdf_note"]),
            "</section>",
        ]
    # Only where the run stored one, which is only where the funnel asked for
    # it. Kitchen stores no tap order and prints the document it always did.
    grid = _pdf_taps(cfg)
    if grid:
        blocks.append(grid)
    node = profile.get("pdf_node")
    for index, section in enumerate(content.get("sections") or [], 1):
        mark = ('<span class="node">%d</span>' % index) if node else ""
        head = ('<h2 class="section-title">%s%s<span class="bar"></span></h2>'
                % (mark, _e(section.get("title"))))
        blocks.append(
            '<div class="section">%s</div>'
            % _pdf_section_body(section, structured, head)
        )
    # The document's own language, so WeasyPrint hyphenates and a reader
    # opens a file that says what it is. A profile that declares none is
    # English, exactly as every report before this one was.
    return (
        '<!doctype html><html lang="%s"><head><meta charset="utf-8">'
        "<title>%s — Mazzin</title><style>%s%s</style></head><body>%s</body></html>"
        % (_e(profile.get("pdf_lang") or "en"), name, PDF_FACES, sheet,
           "".join(blocks))
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

# The opening congratulates them on the decision they already made, names what
# it bought, and stops. There is no "join 12,000 renovators" line and there
# will not be one: we have no such number, and a receipt is the worst possible
# place to put a figure nobody can stand behind. The price is interpolated
# from the purchase rather than written in, so it cannot drift from what was
# actually charged.
#
# The wordmark is an <img> at a hosted URL. Several clients will not draw an
# SVG at all, which is why the alt text is the brand name and the block around
# it carries the brand colour: where it does not render, the header still
# reads as Mazzin rather than as a broken image.
EMAIL_HTML = """<div style="font-family:-apple-system,BlinkMacSystemFont,'Segoe UI',Roboto,Helvetica,Arial,sans-serif;font-size:16px;line-height:1.6;color:#3d424c;max-width:520px">
<p style="margin:0 0 22px"><img src="%(logo)s" width="114" height="26" alt="Mazzin" style="display:block;border:0;font-family:Georgia,'Times New Roman',serif;font-size:20px;font-weight:600;color:#16181d;text-decoration:none"></p>
<h1 style="font-family:Georgia,'Times New Roman',serif;font-size:26px;font-weight:600;line-height:1.25;color:#16181d;margin:0 0 16px">%(headline)s</h1>
<p style="margin:0 0 16px">%(opening)s</p>
<p style="margin:0 0 16px">%(body)s</p>
%(link_block)s<p style="margin:0 0 6px;padding-top:18px;border-top:1px solid #e5e7eb;font-size:13px;color:#6b7280">%(keep)s</p>
<p style="margin:0;font-size:13px;color:#6b7280"><a href="%(home)s" style="color:#6b7280;text-decoration:none">mazzin.com</a></p>
</div>"""

# The online copy, offered only when there is a token that will actually open
# it. Everything about the mail that mentions a link lives in here, so there is
# no arrangement of the template that can promise one it did not send.
EMAIL_LINK_BLOCK = (
    '<p style="margin:0 0 22px"><a href="%(link)s"'
    ' style="color:#C05621;font-weight:600">Open your report online</a></p>\n')


# The zodiac mail. A different document from kitchen's, not a reskin of it,
# because the two are selling different things and the reader has just spent
# four minutes on a dark celestial page — a white letter arriving afterwards
# reads as somebody else's.
#
# Everything here is written for mail clients rather than for browsers, which
# is a narrower medium than it looks:
#
# - Tables, not divs. Outlook on Windows renders through Word and does not do
#   flex, grid, or margins that can be relied on.
# - Every style inline. Gmail strips <style> blocks in several of its clients.
# - `bgcolor` on every cell that carries the dark ground, as well as the CSS.
#   A client that drops the inline background — or a light-mode client that
#   decides to help — still gets the attribute, which is what stops this
#   turning into dark text on a dark field.
# - No web fonts and no font-family that has to be downloaded. Georgia for the
#   display line, the system stack under it, both with real fallbacks.
# - No background images, no border-radius load-bearing, no @media required.
ZODIAC_EMAIL_HTML = """\
<table role="presentation" width="100%%" cellpadding="0" cellspacing="0" \
border="0" bgcolor="#0E1430" \
style="background-color:#0E1430;margin:0;padding:0;width:100%%">
<tr><td align="center" bgcolor="#0E1430" \
style="background-color:#0E1430;padding:28px 16px">
<table role="presentation" width="100%%" cellpadding="0" cellspacing="0" \
border="0" bgcolor="#0E1430" \
style="background-color:#0E1430;max-width:520px;width:100%%">

<tr><td align="center" bgcolor="#0E1430" \
style="background-color:#0E1430;padding:0 0 22px">
<img src="%(logo)s" width="114" height="26" alt="Mazzin" \
style="display:block;border:0;font-family:Georgia,'Times New Roman',serif;\
font-size:18px;font-weight:600;color:#E8C878;text-decoration:none">
</td></tr>

<tr><td align="center" bgcolor="#141B3C" \
style="background-color:#141B3C;border:1px solid #2C355F;border-radius:18px;\
padding:26px 20px">
<p style="margin:0 0 10px;font-family:Helvetica,Arial,sans-serif;font-size:11px;\
font-weight:bold;letter-spacing:2px;color:#E8C878">%(kicker)s</p>
<p style="margin:0;font-family:Georgia,'Times New Roman',serif;font-size:30px;\
font-weight:600;line-height:1.15;color:#EDEFF6">%(sign)s</p>
<p style="margin:6px 0 0;font-family:Georgia,'Times New Roman',serif;\
font-size:17px;font-weight:600;color:#E8C878">%(cross)s</p>
</td></tr>

<tr><td bgcolor="#0E1430" style="background-color:#0E1430;padding:24px 2px 0;\
font-family:Helvetica,Arial,sans-serif;font-size:16px;line-height:1.6;\
color:#C3C9E4">
<p style="margin:0 0 14px;color:#C3C9E4">%(opening)s</p>
<p style="margin:0 0 20px;color:#C3C9E4">%(body)s</p>
</td></tr>

%(link_block)s
<tr><td bgcolor="#0E1430" style="background-color:#0E1430;padding:6px 2px 0">
<table role="presentation" width="100%%" cellpadding="0" cellspacing="0" \
border="0">%(sections)s</table>
</td></tr>

<tr><td bgcolor="#0E1430" style="background-color:#0E1430;padding:22px 2px 0;\
border-top:1px solid #2C355F;font-family:Helvetica,Arial,sans-serif;\
font-size:13px;line-height:1.55;color:#868FB6">
<p style="margin:18px 0 6px;color:#868FB6">%(keep)s</p>
<p style="margin:0;color:#868FB6"><a href="%(home)s" \
style="color:#868FB6;text-decoration:none">mazzin.com</a></p>
</td></tr>

</table></td></tr></table>"""

# One row per section, the constellation path flattened into something a mail
# client can draw: a gold rule where the page had a node, the title, and
# nothing else. Tables all the way down, because a bordered div with a margin
# is the first thing Outlook loses.
ZODIAC_EMAIL_SECTION = """\
<tr><td bgcolor="#0E1430" style="background-color:#0E1430;padding:0 0 10px">\
<table role="presentation" cellpadding="0" cellspacing="0" border="0" \
width="100%%"><tr>\
<td width="18" valign="top" bgcolor="#0E1430" \
style="background-color:#0E1430;padding:5px 10px 0 0;\
font-family:Helvetica,Arial,sans-serif;font-size:13px;color:#E8C878">&#10022;\
</td>\
<td valign="top" bgcolor="#0E1430" style="background-color:#0E1430;\
font-family:Helvetica,Arial,sans-serif;font-size:15px;font-weight:bold;\
line-height:1.4;color:#EDEFF6">%(title)s</td>\
</tr></table></td></tr>"""

ZODIAC_EMAIL_LINK = """\
<tr><td align="center" bgcolor="#0E1430" \
style="background-color:#0E1430;padding:4px 2px 20px">
<table role="presentation" cellpadding="0" cellspacing="0" border="0">
<tr><td align="center" bgcolor="#E8C878" \
style="background-color:#E8C878;border-radius:999px">
<a href="%(link)s" style="display:block;padding:14px 30px;\
font-family:Helvetica,Arial,sans-serif;font-size:16px;font-weight:bold;\
color:#221A05;text-decoration:none">Open your profile online</a>
</td></tr></table>
</td></tr>"""

ZODIAC_EMAIL_LINK_RO = ZODIAC_EMAIL_LINK.replace(
    ">Open your profile online<", ">Deschide-ți profilul online<")

ZODIAC_EMAIL_LINK_BG = ZODIAC_EMAIL_LINK.replace(
    ">Open your profile online<", ">Отвори профила си онлайн<")

ZODIAC_PROFILE["mail_link"] = ZODIAC_EMAIL_LINK
ZODIAC_RO_PROFILE["mail_link"] = ZODIAC_EMAIL_LINK_RO
ZODIAC_BG_PROFILE["mail_link"] = ZODIAC_EMAIL_LINK_BG


def _zodiac_email_html(content, fields):
    """The dark mail, filled from one report row."""
    sign = content.get("sign")
    name = fields["name"]
    card = (content.get("visuals") or {}).get("profile") or {}
    rows = "".join(
        ZODIAC_EMAIL_SECTION % {"title": _e(section.get("title"))}
        for section in (content.get("sections") or [])
        if section.get("title"))
    profile = _profile(content.get("funnel"))
    return ZODIAC_EMAIL_HTML % {
        "kicker": profile.get("mail_kicker") or "YOUR COSMIC PROFILE",
        # The header the result page ends on, so the mail opens where the page
        # left off: the subtype they were named, over the formula that made
        # it. A report written before that block existed falls back to the two
        # lines this mail carried then — and without even a sign, the
        # archetype carries the line on its own rather than printing a cross
        # with nothing on one side of it.
        "sign": _e(card.get("subtype") or sign or name),
        "cross": _e(card.get("formula")
                    or (("× " + name) if sign
                        else (profile.get("mail_cross_fallback")
                              or "Your complete profile"))),
        "opening": fields["opening"],
        "body": fields["body"],
        "link_block": fields["link_block"],
        "sections": rows,
        "keep": fields["keep"],
        "logo": fields["logo"],
        "home": fields["home"],
    }


KEEP_NO_LINK = "The PDF is yours to keep."

# Two mails, because there are two products. A funnel that redraws the
# reader's own kitchen is selling a picture the report explains; a funnel
# without one is selling the report, and has been all along. The copy is
# chosen by what the funnel actually carries rather than by its slug, so a
# third funnel gets the right voice by having a `visualizer` block or not
# having one — and /kitchen's mail is exactly the mail it has always sent.
COPY_REPORT = {
    "headline": "Smart move.",
    "subject": "Your %s kitchen style report — Mazzin",
    "body": "Your personalized %s report is attached.",
    "keep": "It stays available at that link, and the PDF is yours to keep.",
}

COPY_VISUALIZER = {
    "headline": "Your kitchen, in your style.",
    "subject": "Your kitchen, in %s — Mazzin",
    "body": ("The %s report attached is the rest of it: which materials, "
             "colours and finishes make that kitchen real."),
    "keep": "Your kitchen stays at that link, and the PDF is yours to keep.",
}

COPY_ZODIAC = {
    "headline": "Your profile is ready.",
    "subject": "Your %s cosmic profile — Mazzin",
    "body": "Your complete %s profile is attached.",
    "keep": "It stays available at that link, and the PDF is yours to keep.",
}

# The fourth mail: the same product, to somebody who bought it in Romanian.
# `keep_no_link` is here rather than at KEEP_NO_LINK because the no-token case
# is the one place the module writes that sentence itself.
COPY_ZODIAC_RO = {
    "headline": "Profilul tău e gata.",
    "subject": "Profilul tău cosmic %s — Mazzin",
    "body": "Profilul tău complet %s este atașat.",
    "keep": "Rămâne disponibil la acel link, iar PDF-ul e al tău, pe termen "
            "nelimitat.",
    "keep_no_link": "PDF-ul e al tău, pe termen nelimitat.",
}

# The persona mail. One product with one name: the paywall's variants are
# wrappers on the offer and the thing that arrives is the same profile
# whichever wrapper sold it, so nothing here says "advantage" or "why you're
# like this". Neutral on purpose — a buyer who saw one frame and received a
# mail naming the other would notice, and would be right to.
COPY_PERSONA = {
    "headline": "What's underneath is ready.",
    "subject": "%s — what's underneath your shapes",
    "body": "Your full profile as %s is attached: why you drain where "
            "others charge, who steadies you, the strength nobody has named, "
            "and the next twelve months.",
    "keep": "It stays available at that link, and the PDF is yours to keep.",
}

# The memory game's own. Every registered product gets one, because the
# fallback is kitchen's — a brain buyer told they had dodged the mistakes
# that cost renovators four thousand pounds is the leak the persona mail was
# fixed for, and a new product falls into it by default.
COPY_BRAIN = {
    "headline": "Your refresh plan is ready.",
    "subject": "%s — your brain refresh plan",
    "body": "Your full plan as %s is attached: the round with the most room "
            "in it, the two-minute drill that lifts it, five sharp strengths "
            "to lean on, and seven days to move the number.",
    "keep": "It stays available at that link, and the PDF is yours to keep.",
}

# The fifth mail: the same product, to somebody who bought it in Bulgarian.
#
# The archetype name is a proper noun dropped into a Bulgarian sentence, and a
# bare noun followed by a bare name does not read as Bulgarian — "профил
# Небесен въздух" is two nominatives side by side with nothing joining them.
# The head noun takes its definite article and the name goes in guillemets:
# "Пълният ти профил «Небесен въздух»". Guillemets rather than „ “ because
# these same two strings are the pattern the model is shown, and „ closed with
# a straight " is what destroyed ten of twelve warmed sections.
COPY_ZODIAC_BG = {
    "headline": "Профилът ти е готов.",
    "subject": "Твоят космичен профил \u00ab%s\u00bb — Mazzin",
    "body": "Пълният ти профил \u00ab%s\u00bb е прикачен.",
    "keep": "Остава достъпен на онзи линк, а PDF-ът е твой, без срок.",
    "keep_no_link": "PDF-ът е твой, без срок.",
}

ZODIAC_PROFILE["mail"] = COPY_ZODIAC
ZODIAC_RO_PROFILE["mail"] = COPY_ZODIAC_RO
ZODIAC_BG_PROFILE["mail"] = COPY_ZODIAC_BG
PERSONA_PROFILE["mail"] = COPY_PERSONA
BRAIN_PROFILE["mail"] = COPY_BRAIN
PERSONA_PROFILE["mail_link"] = ZODIAC_EMAIL_LINK
# The same button, for the same reason: it is the one that says "open it in
# the browser", and there is nothing product-specific in it.
BRAIN_PROFILE["mail_link"] = ZODIAC_EMAIL_LINK


def _email_copy(content):
    """Which of the three mails this purchase gets.

    Kitchen's two are chosen by what the funnel carries rather than by its
    slug, so a clone gets the right voice by having a `visualizer` block or
    not having one. The third is a different product and is chosen by the
    profile, the same place the voice and the shapes come from.
    """
    funnel = content.get("funnel") or ""
    mail = _profile(funnel).get("mail")
    if mail:
        return mail
    try:
        cfg = config.load_funnel(funnel)
    except Exception:
        return COPY_REPORT
    block = (cfg or {}).get("visualizer") or {}
    return COPY_VISUALIZER if block.get("enabled") else COPY_REPORT


def _slug(text):
    return re.sub(r"[^a-z0-9]+", "-", (text or "report").lower()).strip("-") or "report"


SYMBOLS = {"USD": "$", "EUR": "€", "GBP": "£"}


def _minor_units(value):
    """`value` as integer minor units, or None. Never a float.

    Money is an integer count of the smallest unit here and in MySQL, and the
    one way to turn a correct price into a wrong one is to let a float into
    the middle of it. A Decimal that happens to be whole is accepted because
    a driver may hand one back; a float is refused whatever it holds.
    """
    if isinstance(value, bool):
        return None
    if isinstance(value, int):
        return value
    if (isinstance(value, decimal.Decimal)
            and value == value.to_integral_value()):
        return int(value)
    return None


def _written_price(cfg, cents, currency=None):
    """`cents` written the way this funnel writes money, or None.

    The funnel's own `price_format` and `decimal_mark` — the same two optional
    keys engine.js reads, so the page, the mail and the PDF name one price in
    one shape. Absent on every dollar funnel, which therefore renders exactly
    what it always did. Whatever character the format puts beside the amount
    is substituted in verbatim, no-break space included.
    """
    cents = _minor_units(cents)
    if cents is None or cents <= 0:
        return None
    pricing = (cfg or {}).get("pricing") or {}
    # Integers in, integers out; this is display, not arithmetic.
    whole, part = divmod(cents, 100)
    amount = str(whole) if part == 0 else "%d.%02d" % (whole, part)
    mark = pricing.get("decimal_mark")
    if isinstance(mark, str) and mark:
        amount = amount.replace(".", mark)
    shape = pricing.get("price_format")
    if isinstance(shape, str) and shape:
        return shape.replace("{amount}", amount)
    code = str(currency or pricing.get("currency") or "usd").upper()
    symbol = SYMBOLS.get(code)
    return (symbol + amount) if symbol else ("%s %s" % (amount, code))


def _aware(when):
    """A stored timestamp as an aware UTC datetime, or None.

    `purchases.created_at` is a naive MySQL DATETIME written by the server in
    UTC. It has to be made aware before it can be compared with a sale's own
    `ends`, which carries an offset — a naive/aware comparison raises, and the
    whole point of reaching for this value is to avoid guessing.
    """
    if not isinstance(when, datetime.datetime):
        return None
    return (when if when.tzinfo is not None
            else when.replace(tzinfo=datetime.timezone.utc))


def _price_paid(content, purchase_id=None):
    """What this reader actually paid, as a string for one sentence, or None.

    It used to read `pricing.amount_cents` off the funnel, which is the price
    the funnel charges when nothing is running — so every buyer who took a
    sale was thanked for a sum they did not pay. A receipt naming a number the
    reader can check against their own card statement is the one line in the
    mail nobody would forgive, so this reads what was charged, in this order:

    1. the purchase row, which is what the Stripe webhook recorded — the only
       record of the actual transaction, amount and currency both;
    2. failing a usable amount there, what the funnel was charging at the
       moment of the sale, which the same row still dates;
    3. failing that, no number at all. The sentence is written without one
       rather than with a guess — and the regular price is never that guess on
       a funnel that has ever carried a sale block, because a sale may have
       applied and nothing here can rule it out.

    A funnel with no sale block at all is the one case where the config price
    is provably what was charged, and it is named. That is every kitchen and
    persona report, and zodiac v1: all of them keep the line they always had.
    """
    try:
        cfg = config.load_funnel(content.get("funnel") or "")
    except (KeyError, ValueError, OSError):
        return None

    row = None
    if purchase_id is not None:
        try:
            row = database.query_one(SELECT_PURCHASE_PRICE_SQL, (purchase_id,))
        except Exception:
            # A receipt is not worth an exception on the mail path.
            log.exception("purchase price read failed for %s", purchase_id)
            row = None

    if row:
        written = _written_price(cfg, row.get("amount_cents"),
                                 row.get("currency"))
        if written:
            return written
        when = _aware(row.get("created_at"))
        if when is not None:
            # Imported here rather than at the top: payments imports this
            # module, and a module-level import back would be a cycle.
            import payments
            cents, _running = payments._effective_price(cfg, when)
            return _written_price(cfg, cents)
        return None

    if isinstance(cfg.get("sale"), dict):
        return None
    return _written_price(cfg, (cfg.get("pricing") or {}).get("amount_cents"))


def _email_opening(content, purchase_id=None):
    """The congratulation. Names the price when we know it, and does not
    reach for a substitute when we do not.

    `purchase_id` is what lets it name the price this reader was charged
    rather than the one the funnel lists; without it `_price_paid` will only
    answer for a funnel that has never run a sale.

    The saving is the same figure the funnel leads with everywhere else. It
    was "thousands" here, which is the one place the reader has already paid
    and can check the claim against what they are holding — a vaguer number
    there than on the way in reads as the number getting smaller.
    """
    price = _price_paid(content, purchase_id)
    copy = _email_copy(content)
    if copy is COPY_ZODIAC_BG:
        if price:
            return ("Току-що даде %s за прочит на енергията, с която "
                    "вървиш от самото начало." % html.escape(price))
        return "Прочит на енергията, с която вървиш от самото начало."
    if copy is COPY_ZODIAC_RO:
        if price:
            return ("Tocmai ai dat %s pe o citire a energiei cu care ai "
                    "mers până acum." % html.escape(price))
        return "O citire a energiei cu care ai mers până acum."
    if copy is COPY_ZODIAC:
        if price:
            return ("You just spent %s on a read of the energy you have been "
                    "running on all along." % html.escape(price))
        return ("A read of the energy you have been running on all along.")
    if copy is COPY_PERSONA:
        if price:
            return ("You just spent %s on the read underneath the shapes you "
                    "chose." % html.escape(price))
        return "The read underneath the shapes you chose."
    if copy is COPY_BRAIN:
        if price:
            return ("You just spent %s on the plan that moves the number you "
                    "were shown." % html.escape(price))
        return "The plan that moves the number you were shown."
    if copy is COPY_VISUALIZER:
        if price:
            return ("Your own kitchen, redrawn in the style your choices "
                    "pointed at — for %s." % html.escape(price))
        return "Your own kitchen, redrawn in the style your choices pointed at."
    # Kitchen's line, and the fall-through for anything that reads as kitchen.
    #
    # It is a fall-through rather than a fourth branch because kitchen is what
    # an unregistered funnel is — see `_profile`. That is fine for a kitchen
    # clone and wrong for a product with its own voice: persona reached here
    # for one release and told its buyers they had dodged the mistakes that
    # cost renovators $4,000, which is a sentence about a kitchen sent to
    # somebody who bought a reading of themselves. Every registered product
    # gets a branch above this line, and tests/test_personareport.py holds
    # each funnel to its own.
    if price:
        return ("You just spent %s to dodge the mistakes that cost renovators "
                "$4,000+." % html.escape(price))
    return ("You just dodged the mistakes that cost renovators $4,000+.")


def _result_token(purchase_id, checkout_session=None):
    """What `?cs=` has to carry for this purchase, or None.

    Two things can open a paid report and the parameter is called `cs` for
    both: `cs_…` from a hosted checkout, `pi_…` from a payment confirmed in the
    page. Widening the reading side was not enough — `find_purchase` matches on
    either column and the client regex accepts either shape, but the one place
    that *builds* a link still assumed a session. A wallet purchase has none,
    so every one of those emails carried a link to the funnel root and sent a
    buyer back to the quiz they had already finished.

    The caller's value wins when it has one, so the hosted path costs no query
    at all and behaves exactly as it did. Only a purchase without a session
    reaches the database, and it reads the row it is already named after.
    """
    if checkout_session:
        return checkout_session
    try:
        row = database.query_one(SELECT_PURCHASE_TOKENS_SQL, (purchase_id,))
    except Exception as exc:
        # A link is worth a query; it is not worth the email. Losing the row
        # here costs the online copy and nothing else — the PDF still goes.
        log.warning("could not read tokens for purchase %s: %s",
                    purchase_id, type(exc).__name__)
        return None
    if not row:
        return None
    return row.get("checkout_session") or row.get("payment_intent") or None


def _email_html(dark, content, fields):
    """The mail body. Kitchen's is assembled exactly as it always was."""
    if dark:
        return _zodiac_email_html(content, fields)
    return EMAIL_HTML % {
        "headline": fields["headline"],
        "body": fields["body"],
        "link_block": fields["link_block"],
        "keep": fields["keep"],
        "logo": fields["logo"],
        "home": fields["home"],
        "opening": fields["opening"],
    }


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

    funnel = content.get("funnel") or ""
    profile = _profile(funnel)
    words = _words(profile)
    name = content.get("style_name") or words["mail_style"]
    # The persona product names the reader by what they came out as rather
    # than by the archetype behind it — "Your Open Flame profile", which is
    # the name on the page they paid from. Bare, because the article is
    # already in the sentence: "Your The Open Flame profile" is what the
    # archetype name gives you.
    if profile is PERSONA_PROFILE:
        card = (content.get("visuals") or {}).get("profile") or {}
        name = card.get("subtype_bare") or re.sub(r"^The\s+", "", name)
    copy = _email_copy(content)
    token = _result_token(purchase_id, checkout_session)

    # No token, no link. The old line built the URL with the query string left
    # off, which is not a broken link — it is a working link to the quiz, and
    # it sent somebody who had just paid back to the start of the funnel they
    # had already finished. Sending nothing is the honest failure: the report
    # is attached either way, and the reader is not invited to click on their
    # own paywall.
    # Which mail this funnel sends. The link block is part of the template
    # rather than a string appended to it — a table row cannot be dropped into
    # a div — so it is chosen here alongside it.
    # The dark mail, for the products sold on a dark page. A buyer who paid on
    # a dusk result and opened a pale envelope has been handed a different
    # document from the one they bought.
    dark = _is_zodiac(profile) or profile is PERSONA_PROFILE
    link_template = (profile.get("mail_link") or ZODIAC_EMAIL_LINK) if dark \
        else EMAIL_LINK_BLOCK

    if token and funnel:
        link = "%s/%s?cs=%s" % (config.BASE_URL, funnel, token)
        link_block = link_template % {"link": html.escape(link)}
        keep = copy["keep"]
    else:
        log.warning("purchase %s has no result token — email sent with the "
                    "PDF and no link", purchase_id)
        link_block = ""
        keep = copy.get("keep_no_link") or KEEP_NO_LINK

    payload = {
        "from": config.EMAIL_FROM,
        "to": [email],
        "subject": copy["subject"] % name,
        "html": _email_html(dark, content, {
            "name": name,
            "headline": html.escape(copy["headline"]),
            "body": copy["body"] % html.escape(name),
            "link_block": link_block,
            "keep": keep,
            "logo": html.escape(config.BASE_URL + "/static/brand/logo.svg"),
            "home": html.escape(config.BASE_URL),
            "opening": _email_opening(content, purchase_id),
        }),
        "attachments": [
            {
                "filename": words["pdf_filename"] % _slug(name),
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
