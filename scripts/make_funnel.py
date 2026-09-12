#!/usr/bin/env python3
"""Write a localized funnel from a vertical's master config: one command per
language, no code.

Console use only, run by hand on the server. Nothing imports this at request
time and no route reaches it. It spends money — one Anthropic call per chunk
of strings — so it is never run by a deploy or a test; the test runs it with
--no-llm, which pseudo-translates and exercises everything else:

    cd ~/mazzin && python3 scripts/make_funnel.py blinds hu --dry-run
    cd ~/mazzin && python3 scripts/make_funnel.py blinds hu
    cd ~/mazzin && python3 scripts/make_funnel.py blinds de --no-llm

What it does, in order:

  1. loads funnels/<vertical>.json, the English master, and fails plainly
     when there is none;
  2. translates every human-visible string in it through the Anthropic API
     (ANTHROPIC_API_KEY read from .env as a literal line, never sourced) in
     chunks, asking for JSON and only JSON, retrying a chunk that comes back
     unparsable, incomplete, with a {token} changed or a banned word in it;
  3. applies scripts/locales.json: currency, charm price in local minor
     units, the price format and decimal mark engine.js reads;
  4. names it <vertical>-<lang> / <vertical>_<lang>_v1;
  5. writes funnels/<vertical>-<lang>.json and the byte-identical
     static/funnels/ copy the browser fetches;
  6. makes sure .gitignore carries the two <vertical>-*.json patterns and
     the two exceptions for the -test twin — a generated funnel is
     server-side data, not code, and the twin is the one that is committed.

FROZEN, never handed to the model: structure and key order, every id, slug
and funnel_id, tags, image paths and filenames, step and section ids, style
ids, URLs, hex and rgb colours and colour names, `{tokens}` inside a string
(checked after the fact), the sentinel values the report module reads, and
the model-facing English under report_profile.sections — the instructions
to the model stay English on every funnel, as reports.py's own do.

--no-llm wraps every translatable value as "[xx] <original>" so the whole
pipeline — freezing, locale, mirror, gitignore — runs offline and free.
--dry-run prints the plan and a token estimate and writes nothing.
"""
import argparse
import json
import os
import re
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import config          # noqa: E402
import reports         # noqa: E402

ROOT = config.BASE_DIR
LOCALES = os.path.join(ROOT, "scripts", "locales.json")
ENV_FILES = (os.path.join(ROOT, ".env"), os.path.expanduser("~/mazzin/.env"))
MODEL = "claude-sonnet-4-6"
CHUNK = 40
TRIES = 3
MAX_TOKENS = 8000

# Keys whose values are never copy, whatever they hold.
FROZEN_KEYS = frozenset((
    "id", "slug", "funnel_id", "locale", "img", "image", "hex", "rgb",
    "format", "template", "tags", "step", "section", "mode", "moodboard",
    "color_family", "axis", "variants", "currency", "price_format",
    "decimal_mark", "og_image", "product_image", "result_module",
    "result_css", "theme", "stripe_mode", "pdf_lang", "language_name",
    "vertical_noun", "icon", "from", "filename", "manifest_hero",
    "moodboard_step", "material_steps", "echo_steps", "emphasized_section",
    "pdf_filename", "verdict", "element", "result_template", "scoring",
    "after_step", "auto_advance_ms", "duration_ms", "ends",
))
# Dotted path prefixes that are frozen whole.
FROZEN_PATHS = (
    "report_profile.sections", "report_profile.banned",
    "report_profile.json_retry", "report_profile.prompt_budget",
    "report.visuals",
)
HEX_RE = re.compile(r"^#[0-9a-fA-F]{3,8}$")
TOKEN_RE = re.compile(r"\{[a-zA-Z_][a-zA-Z0-9_]*\}|%s|%%")
FROZEN_VALUES = frozenset((reports.FROM_CONFIG,))

SYSTEM = """You translate the copy of a mobile consumer quiz and its paid \
buyer's guide from English into %(language)s.

Rules:
- Natural, native %(language)s for a consumer product: informal register \
(address the reader as a friend would in %(language)s), short, confident. \
Buttons and labels stay short — charm phrasing, no literal word-for-word.
- Keep every {token} exactly as it is — same spelling, same braces. Keep %%s \
and any number, currency symbol or price exactly as written.
- Keep proper nouns and product names (Mazzin, Stripe, PDF) as they are.
- Never use the words for psychic, prediction, fortune-telling, horoscope, \
guarantee, or any medical or financial claim.
- Return ONLY a JSON object with the same keys as the input and the \
translated strings as values. No prose, no code fence, no extra keys, no \
missing keys. Every value on one line."""


# --- the walk ------------------------------------------------------------------

def _frozen_path(path):
    return any(path == p or path.startswith(p + ".") for p in FROZEN_PATHS)


def _frozen_value(value):
    return (not value.strip() or value in FROZEN_VALUES
            or value.startswith("/") or value.startswith("http")
            or HEX_RE.match(value) is not None)


def collect(node, path="", in_colour=False, out=None):
    """[(path, string)] for every translatable string, in document order."""
    if out is None:
        out = []
    if isinstance(node, dict):
        # A colour row — anything carrying a hex or rgb — keeps its name: the
        # free result showed the reader that name and the report holds the
        # model to it character for character.
        colour = in_colour or "hex" in node or "rgb" in node
        for key, value in node.items():
            sub = "%s.%s" % (path, key) if path else key
            if key in FROZEN_KEYS or _frozen_path(sub):
                continue
            if colour and key == "name":
                continue
            collect(value, sub, colour, out)
    elif isinstance(node, list):
        for index, value in enumerate(node):
            collect(value, "%s[%d]" % (path, index), in_colour, out)
    elif isinstance(node, str):
        if not _frozen_value(node):
            out.append((path, node))
    return out


def _set(node, path, value):
    """Write `value` at a dotted/indexed path inside `node`."""
    parts = re.findall(r"[^.\[\]]+|\[\d+\]", path)
    cur = node
    for part in parts[:-1]:
        cur = cur[int(part[1:-1])] if part.startswith("[") else cur[part]
    last = parts[-1]
    if last.startswith("["):
        cur[int(last[1:-1])] = value
    else:
        cur[last] = value


def tokens_of(text):
    return sorted(TOKEN_RE.findall(text))


# --- the key -------------------------------------------------------------------

_ENV_LINE = re.compile(r"^\s*(?:export\s+)?ANTHROPIC_API_KEY=(.*?)\s*$")


def key_from_env_file(paths=None):
    for path in (ENV_FILES if paths is None else paths):
        try:
            with open(path, encoding="utf-8") as fh:
                lines = fh.read().splitlines()
        except OSError:
            continue
        value = ""
        for line in lines:
            hit = _ENV_LINE.match(line.rstrip("\r"))
            if hit:
                value = hit.group(1)
        if len(value) >= 2 and value[0] == value[-1] and value[0] in "\"'":
            value = value[1:-1]
        if value:
            return value
    return ""


def api_key():
    return key_from_env_file() or os.getenv("ANTHROPIC_API_KEY", "")


# --- the translation -----------------------------------------------------------

class TranslationError(Exception):
    pass


def _strip_fence(text):
    text = text.strip()
    if text.startswith("```"):
        text = text.split("\n", 1)[1] if "\n" in text else ""
        if text.rstrip().endswith("```"):
            text = text.rstrip()[:-3]
    return text.strip()


def check_chunk(source, answer, banned):
    """Problems with one chunk's answer, or [] when it is usable."""
    notes = []
    if not isinstance(answer, dict):
        return ["not a JSON object"]
    for key, original in source.items():
        got = answer.get(key)
        if not isinstance(got, str) or not got.strip():
            notes.append("%s: missing or empty" % key)
            continue
        if tokens_of(got) != tokens_of(original):
            notes.append("%s: {tokens} changed — keep %s exactly"
                         % (key, " ".join(tokens_of(original)) or "none"))
        if "\n" in got:
            notes.append("%s: contains a line break" % key)
        hit = reports._banned_hit(got, banned)
        if hit:
            notes.append("%s: uses the banned word %r" % (key, hit))
    extra = [k for k in answer if k not in source]
    if extra:
        notes.append("extra keys: %s" % ", ".join(extra[:5]))
    return notes


def translate_chunk(client, model, language, source, banned):
    prompt = json.dumps(source, ensure_ascii=False, indent=1)
    note = ""
    last = None
    for attempt in range(TRIES):
        message = client.messages.create(
            model=model, max_tokens=MAX_TOKENS, temperature=0.2,
            system=SYSTEM % {"language": language},
            messages=[{"role": "user", "content": prompt + note}])
        text = "".join(b.text for b in message.content if b.type == "text")
        try:
            answer = json.loads(_strip_fence(text))
        except ValueError:
            problems = ["the answer was not valid JSON"]
        else:
            problems = check_chunk(source, answer, banned)
        if not problems:
            return {k: answer[k].strip() for k in source}
        last = problems
        note = ("\n\nYour previous answer was refused:\n"
                + "\n".join("  - " + p for p in problems[:12])
                + "\nSend the whole object again, corrected, as JSON only.")
    raise TranslationError("chunk refused %d times: %s"
                           % (TRIES, "; ".join(last[:3])))


def translate_all(items, language, banned, model=MODEL, client=None):
    """{path: translated} for every (path, string) in `items`."""
    if client is None:
        key = api_key()
        if not key:
            raise TranslationError("no ANTHROPIC_API_KEY in .env or the "
                                   "environment")
        import anthropic
        client = anthropic.Anthropic(api_key=key)
    out = {}
    for start in range(0, len(items), CHUNK):
        chunk = items[start:start + CHUNK]
        source = dict(("s%d" % (start + i), text)
                      for i, (_, text) in enumerate(chunk))
        answer = translate_chunk(client, model, language, source, banned)
        for i, (path, _) in enumerate(chunk):
            out[path] = answer["s%d" % (start + i)]
        print("  translated %d/%d" % (min(start + CHUNK, len(items)),
                                      len(items)))
    return out


def pseudo_translate(items, lang):
    return dict((path, "[%s] %s" % (lang, text)) for path, text in items)


# --- the locale ----------------------------------------------------------------

def load_locales(path=LOCALES):
    with open(path, encoding="utf-8") as fh:
        data = json.load(fh)
    return dict((k, v) for k, v in data.items() if not k.startswith("_"))


def check_locale(lang, loc):
    cents = loc.get("amount_cents")
    if not isinstance(cents, int) or cents <= 0:
        raise ValueError("%s: amount_cents must be a positive integer" % lang)
    multiple = int(loc.get("amount_multiple") or 1)
    if cents % multiple:
        raise ValueError("%s: %d is not a multiple of %d minor units, which "
                         "Stripe refuses for %s"
                         % (lang, cents, multiple, loc.get("currency")))
    if cents < int(loc.get("stripe_min_cents") or 0):
        raise ValueError("%s: %d is under Stripe's minimum charge for %s"
                         % (lang, cents, loc.get("currency")))
    if not isinstance(loc.get("currency"), str) or len(loc["currency"]) != 3:
        raise ValueError("%s: currency must be a three-letter code" % lang)


def apply_locale(cfg, vertical, lang, loc):
    cfg["slug"] = "%s-%s" % (vertical, lang)
    cfg["funnel_id"] = "%s_%s_v1" % (vertical, lang)
    cfg["locale"] = lang
    pricing = cfg.setdefault("pricing", {})
    pricing["amount_cents"] = loc["amount_cents"]
    pricing["currency"] = loc["currency"]
    for key in ("price_format", "decimal_mark"):
        if loc.get(key):
            pricing[key] = loc[key]
        else:
            pricing.pop(key, None)
    profile = cfg.get("report_profile")
    if isinstance(profile, dict):
        profile["language_name"] = loc["language_name"]
        profile["pdf_lang"] = lang
    return cfg


# --- the files -----------------------------------------------------------------

def gitignore_lines(vertical):
    return ["funnels/%s-*.json" % vertical,
            "!funnels/%s-test.json" % vertical,
            "static/funnels/%s-*.json" % vertical,
            "!static/funnels/%s-test.json" % vertical]


def ensure_gitignore(root, vertical):
    """Append the vertical's patterns to .gitignore if they are missing."""
    path = os.path.join(root, ".gitignore")
    try:
        with open(path, encoding="utf-8") as fh:
            text = fh.read()
    except OSError:
        text = ""
    have = set(line.strip() for line in text.splitlines())
    missing = [line for line in gitignore_lines(vertical) if line not in have]
    if not missing:
        return False
    block = ("\n# Generated %s funnels: server-side data written by "
             "scripts/make_funnel.py.\n# The -test twin is the one that "
             "is committed.\n" % vertical) + "\n".join(missing) + "\n"
    with open(path, "a", encoding="utf-8") as fh:
        if text and not text.endswith("\n"):
            fh.write("\n")
        fh.write(block)
    return True


def write_both(root, slug, cfg):
    text = json.dumps(cfg, indent=2, ensure_ascii=False) + "\n"
    for directory in ("funnels", os.path.join("static", "funnels")):
        path = os.path.join(root, directory, slug + ".json")
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "w", encoding="utf-8") as fh:
            fh.write(text)
        print("written   %s" % os.path.relpath(path, root))


def build(vertical, lang, root=ROOT, no_llm=False, dry_run=False,
          model=MODEL, client=None, locales=None):
    """The whole pipeline. Returns the config written (or planned)."""
    master_path = os.path.join(root, "funnels", vertical + ".json")
    if not os.path.isfile(master_path):
        raise FileNotFoundError("no master funnel at %s — write funnels/%s.json"
                                " first" % (master_path, vertical))
    with open(master_path, encoding="utf-8") as fh:
        master = json.load(fh)
    locales = locales or load_locales()
    if lang not in locales:
        raise ValueError("no locale %r in scripts/locales.json (have: %s)"
                         % (lang, ", ".join(sorted(locales))))
    if lang == "en" or (master.get("locale") or "en") == lang:
        raise ValueError("%s is the master's own language — nothing to "
                         "generate" % lang)
    loc = locales[lang]
    check_locale(lang, loc)

    profile = reports.build_guide_profile(master) \
        if isinstance(master.get("report_profile"), dict) else None
    banned = profile["banned"] if profile else reports.GUIDE_BANNED

    items = collect(master)
    chars = sum(len(t) for _, t in items)
    print("%s -> %s-%s: %d strings, %d characters, %d chunk(s)"
          % (vertical, vertical, lang, len(items), chars,
             (len(items) + CHUNK - 1) // CHUNK))
    print("  price %s %d (%s), %s"
          % (loc["currency"], loc["amount_cents"], loc["language_name"],
             "pseudo-translation" if no_llm else model))
    if dry_run:
        # Input is the strings plus the prompt around them, output is about
        # the same length again; four characters a token is the usual rule.
        est = int(chars / 4 * 2.4) + 400 * ((len(items) + CHUNK - 1) // CHUNK)
        print("  estimated tokens: ~%d (nothing written)" % est)
        return None

    if no_llm:
        translated = pseudo_translate(items, lang)
    else:
        translated = translate_all(items, loc["language_name"], banned,
                                   model, client)

    cfg = json.loads(json.dumps(master))     # a deep copy, key order kept
    for path, text in translated.items():
        _set(cfg, path, text)
    apply_locale(cfg, vertical, lang, loc)
    write_both(root, cfg["slug"], cfg)
    if ensure_gitignore(root, vertical):
        print("appended  .gitignore")
    return cfg


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("vertical")
    ap.add_argument("lang")
    ap.add_argument("--no-llm", action="store_true",
                    help="pseudo-translate offline: '[xx] <original>'")
    ap.add_argument("--dry-run", action="store_true",
                    help="print the plan and a token estimate, write nothing")
    ap.add_argument("--root", default=ROOT,
                    help="repo root to read the master from and write into")
    ap.add_argument("--model", default=MODEL)
    args = ap.parse_args(argv)
    try:
        build(args.vertical, args.lang, args.root, args.no_llm,
              args.dry_run, args.model)
    except (FileNotFoundError, ValueError, TranslationError) as exc:
        print("error: %s" % exc)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
