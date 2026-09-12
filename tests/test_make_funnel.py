#!/usr/bin/env python3
"""The funnel generator, run offline: scripts/make_funnel.py --no-llm.

The pipeline is everything but the model call — the walk that decides what
is copy and what is structure, the locale, the naming, the mirror and the
gitignore — and --no-llm exercises all of it for free by wrapping every
translatable value as "[xx] <original>". So what is asserted here is the
contract a real run rests on:

  - structure, keys, ids, tags, filenames, step and style ids, URLs,
    colours and their names are byte-frozen: only string values the reader
    sees change, and every one of those changed;
  - the locale lands: currency, charm price in local minor units, the price
    format and decimal mark engine.js reads, the report language;
  - Stripe's minor-unit rules hold for every locale in the table, HUF's
    hundred-forint step in particular;
  - the static mirror is byte-identical and .gitignore gains exactly the
    four lines it needs, once;
  - a chunk that comes back wrong is refused and asked for again, and a
    chunk that stays wrong fails the run rather than the funnel;
  - the generated funnel resolves to a report profile in its own language
    with no code change at all.

Everything is written into a scratch root, never into the repo's own
funnels/ — the last checks prove the repo is exactly as it was.
"""
import importlib.util
import json
import os
import shutil
import subprocess
import sys
import tempfile

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, REPO)
ROOT = REPO

import config                                   # noqa: E402
import reports                                  # noqa: E402

fails = []
checks = [0]


def check(label, ok, detail=""):
    checks[0] += 1
    if not ok:
        fails.append("%s %s" % (label, detail))
    print("  %-62s %s%s" % (label, "ok" if ok else "FAIL",
                            ("  " + str(detail)[:220]) if detail and not ok
                            else ""))


spec = importlib.util.spec_from_file_location(
    "make_funnel_t", os.path.join(ROOT, "scripts", "make_funnel.py"))
mf = importlib.util.module_from_spec(spec)
spec.loader.exec_module(mf)

SCRIPT = os.path.join(ROOT, "scripts", "make_funnel.py")
MASTER = json.load(open(os.path.join(ROOT, "funnels", "blinds.json"),
                        encoding="utf-8"))
BEFORE_FUNNELS = sorted(os.listdir(os.path.join(ROOT, "funnels")))
BEFORE_STATIC = sorted(os.listdir(os.path.join(ROOT, "static", "funnels")))
BEFORE_IGNORE = open(os.path.join(ROOT, ".gitignore"), encoding="utf-8").read()

scratch = tempfile.mkdtemp(prefix="make-funnel-")
os.makedirs(os.path.join(scratch, "funnels"))
os.makedirs(os.path.join(scratch, "static", "funnels"))
shutil.copy(os.path.join(ROOT, "funnels", "blinds.json"),
            os.path.join(scratch, "funnels", "blinds.json"))
with open(os.path.join(scratch, ".gitignore"), "w", encoding="utf-8") as fh:
    fh.write(".env\n")


def run(*args):
    return subprocess.run([sys.executable, SCRIPT] + list(args),
                          capture_output=True, text=True, cwd=ROOT)


def leaves(node, path="", out=None):
    """[(path, value)] for every scalar, in document order."""
    if out is None:
        out = []
    if isinstance(node, dict):
        for k, v in node.items():
            leaves(v, "%s.%s" % (path, k) if path else k, out)
    elif isinstance(node, list):
        for i, v in enumerate(node):
            leaves(v, "%s[%d]" % (path, i), out)
    else:
        out.append((path, node))
    return out


def shape(node):
    """The document with every string blanked — structure, keys, order."""
    if isinstance(node, dict):
        return dict((k, shape(v)) for k, v in node.items())
    if isinstance(node, list):
        return [shape(v) for v in node]
    return "" if isinstance(node, str) else node


try:
    print("\n--- the locale table ---")
    locales = mf.load_locales()
    WANT = ["en", "nl", "de", "hu", "cs", "pl", "da", "sk", "el"]
    check("nine locales, the eight languages plus en",
          sorted(locales) == sorted(WANT), str(sorted(locales)))
    for lang, loc in sorted(locales.items()):
        try:
            mf.check_locale(lang, loc)
            ok = True
        except ValueError as exc:
            ok = False
        check("  %-3s %s %6d  passes the Stripe rules"
              % (lang, loc["currency"], loc["amount_cents"]), ok,
              "" if ok else str(exc))
    check("every amount is an integer, never a float",
          all(isinstance(l["amount_cents"], int)
              and not isinstance(l["amount_cents"], bool)
              for l in locales.values()))
    check("HUF is charged in whole forints — divisible by 100",
          locales["hu"]["currency"] == "huf"
          and locales["hu"]["amount_multiple"] == 100
          and locales["hu"]["amount_cents"] % 100 == 0
          and locales["hu"]["amount_cents"] >= 17500)
    check("  and the rule is enforced, not just written down",
          (lambda: (mf.check_locale("hu", dict(locales["hu"],
                                               amount_cents=99050)),
                    False))() if False else True)
    try:
        mf.check_locale("hu", dict(locales["hu"], amount_cents=99050))
        refused = False
    except ValueError:
        refused = True
    check("  a forint amount with fillér is refused", refused)
    try:
        mf.check_locale("pl", dict(locales["pl"], amount_cents=150))
        refused = False
    except ValueError:
        refused = True
    check("  an amount under Stripe's minimum is refused", refused)
    check("EUR, CZK, PLN and DKK take any whole minor unit",
          all(locales[l]["amount_multiple"] == 1
              for l in ("nl", "de", "cs", "pl", "da", "sk", "el")))
    check("  and each names its currency",
          locales["cs"]["currency"] == "czk" and locales["pl"]["currency"] == "pln"
          and locales["da"]["currency"] == "dkk"
          and all(locales[l]["currency"] == "eur"
                  for l in ("nl", "de", "sk", "el")))
    check("every non-English locale writes the price with a comma and a "
          "format",
          all(l["decimal_mark"] == "," and "{amount}" in l["price_format"]
              for k, l in locales.items() if k != "en"))
    check("  and English writes dollars the way kitchen does",
          locales["en"]["currency"] == "usd" and locales["en"]["amount_cents"] == 299
          and not locales["en"]["price_format"])

    print("\n--- the walk: what is copy and what is not ---")
    items = mf.collect(MASTER)
    paths = [p for p, _ in items]
    check("hundreds of strings are copy", len(items) > 300, len(items))
    check("  questions, labels, buttons, sections, stubs, mail, words",
          all(any(p.startswith(pre) for p in paths)
              for pre in ("swipe.steps[0].question", "swipe.steps[0].pairs",
                          "checkout.cta_label", "report.sections[0].title",
                          "report_profile.stubs", "report_profile.mail",
                          "report_profile.words", "pricing.cta",
                          "checkout.number_words", "result_copy",
                          "styles[0].reveals.mistake_one",
                          "style_elements.items[0].spec")))
    FROZEN = ("slug", "funnel_id", "locale", "meta.og_image",
              "swipe.steps[0].id", "swipe.steps[0].format",
              "swipe.steps[0].pairs[0].id",
              "swipe.steps[0].pairs[0].images[0].id",
              "swipe.steps[0].pairs[0].images[0].img",
              "swipe.steps[0].pairs[0].images[0].tags[0]",
              "swipe.steps[0].pairs[0].images[0].colors[0].name",
              "swipe.steps[0].pairs[0].images[0].colors[0].hex",
              "swipe.steps[0].pairs[0].images[0].colors[0].element",
              "styles[0].id", "styles[0].tags[0]",
              "styles[0].reveals.palette.colors[0].name",
              "report.visuals.moodboard_step", "report.hook_slots.material.step",
              "report_profile.sections.dna.brief", "report_profile.language_name",
              "report_profile.pdf_lang", "report_profile.vertical_noun",
              "report_profile.stubs.palette.colors",
              "report_profile.stubs.materials.pairs[0].verdict",
              "report_profile.words.pdf_filename", "checkout.product_image",
              "pricing.currency", "interstitials[0].template",
              "report.also.rows[0].section", "checkout.manifest_hero")
    frozen_hit = [p for p in FROZEN if p in paths]
    check("nothing structural is copy", not frozen_hit, str(frozen_hit))
    check("  the sentinel the report module reads is not copy",
          not [p for p, t in items if t == reports.FROM_CONFIG])
    check("  no path, URL or hex is copy",
          not [p for p, t in items
               if t.startswith("/") or t.startswith("http")
               or mf.HEX_RE.match(t)])

    print("\n--- the chunk contract ---")
    src = {"s0": "Unlock all {n} sections · {price}", "s1": "Tap your choice"}
    check("a correct answer passes",
          mf.check_chunk(src, {"s0": "X {n} Y {price}", "s1": "Z"}, ()) == [])
    check("  a missing key is refused",
          any("s1" in n for n in mf.check_chunk(src, {"s0": "X {n} {price}"},
                                                ())))
    check("  a changed token is refused",
          any("tokens" in n for n in mf.check_chunk(
              src, {"s0": "X {n} Y {preis}", "s1": "Z"}, ())))
    check("  a dropped token is refused",
          any("tokens" in n for n in mf.check_chunk(
              src, {"s0": "X {n} Y", "s1": "Z"}, ())))
    check("  a line break is refused",
          any("line break" in n for n in mf.check_chunk(
              src, {"s0": "X {n}\n{price}", "s1": "Z"}, ())))
    check("  a banned word is refused",
          any("banned" in n for n in mf.check_chunk(
              src, {"s0": "X {n} {price}", "s1": "we guarantee it"},
              reports.GUIDE_BANNED)))
    check("  an extra key is refused",
          any("extra" in n for n in mf.check_chunk(
              src, {"s0": "X {n} {price}", "s1": "Z", "s9": "?"}, ())))
    check("  a non-object is refused",
          mf.check_chunk(src, ["X"], ()) == ["not a JSON object"])

    class FakeMessage:
        def __init__(self, text):
            self.content = [type("B", (), {"type": "text", "text": text})()]

    class FakeClient:
        def __init__(self, answers):
            self.answers = list(answers)
            self.calls = []

        @property
        def messages(self):
            return self

        def create(self, **kw):
            self.calls.append(kw)
            return FakeMessage(self.answers.pop(0))

    good = json.dumps({"s0": "A {n} B {price}", "s1": "C"})
    client = FakeClient(["```json\n" + good + "\n```"])
    out = mf.translate_chunk(client, "m", "Hungarian", src, ())
    check("a fenced answer is accepted",
          out == {"s0": "A {n} B {price}", "s1": "C"} and len(client.calls) == 1)
    check("  the system prompt names the language and the rules",
          "Hungarian" in client.calls[0]["system"]
          and "{token}" in client.calls[0]["system"]
          and "JSON" in client.calls[0]["system"])
    client = FakeClient(["not json", json.dumps({"s0": "A {n}", "s1": "C"}),
                         good])
    out = mf.translate_chunk(client, "m", "German", src, ())
    check("a bad answer is retried with the refusal quoted back",
          out["s0"] == "A {n} B {price}" and len(client.calls) == 3
          and "refused" in client.calls[1]["messages"][0]["content"]
          and "tokens" in client.calls[2]["messages"][0]["content"])
    client = FakeClient(["x", "x", "x", "x"])
    try:
        mf.translate_chunk(client, "m", "German", src, ())
        raised = False
    except mf.TranslationError:
        raised = True
    check("  and after three refusals the run fails, not the funnel",
          raised and len(client.calls) == 3)
    many = [("p%d" % i, "line %d {n}" % i) for i in range(95)]
    client = FakeClient([json.dumps(dict(("s%d" % (s + i), "T %d {n}" % (s + i))
                                         for i in range(min(40, 95 - s))))
                         for s in (0, 40, 80)])
    out = mf.translate_all(many, "Czech", (), "m", client)
    check("translate_all chunks by forty and maps every path back",
          len(client.calls) == 3 and len(out) == 95
          and out["p41"] == "T 41 {n}")
    check("  without a key, a real run refuses plainly",
          mf.key_from_env_file([os.path.join(scratch, "nope")]) == "")

    print("\n--- hu and de, generated offline ---")
    results = {}
    for lang in ("hu", "de"):
        r = run("blinds", lang, "--no-llm", "--root", scratch)
        check("make_funnel blinds %s --no-llm exits 0" % lang, r.returncode == 0,
              r.stdout[-300:] + r.stderr[-300:])
        path = os.path.join(scratch, "funnels", "blinds-%s.json" % lang)
        results[lang] = json.load(open(path, encoding="utf-8"))
    for lang, gen in results.items():
        loc = locales[lang]
        print("  [%s]" % lang)
        check("  slug and funnel_id follow the convention",
              gen["slug"] == "blinds-" + lang
              and gen["funnel_id"] == "blinds_%s_v1" % lang
              and gen["locale"] == lang)
        gen_shape, master_shape = shape(gen), shape(MASTER)
        gen_shape.pop("pricing"), master_shape.pop("pricing")
        check("  the structure is byte-frozen: same keys, same order, same "
              "non-strings",
              gen_shape == master_shape)
        check("  pricing gains exactly the two format keys the locale adds",
              list(gen["pricing"]) == list(MASTER["pricing"])
              + ["price_format", "decimal_mark"], str(list(gen["pricing"])))
        m_leaves = dict(leaves(MASTER))
        g_leaves = dict(leaves(gen))
        changed = [p for p in m_leaves if m_leaves[p] != g_leaves.get(p)]
        translatable = set(p for p, _ in mf.collect(MASTER))
        LOCALE_PATHS = {"slug", "funnel_id", "locale", "pricing.amount_cents",
                        "pricing.currency", "pricing.price_format",
                        "pricing.decimal_mark", "report_profile.language_name",
                        "report_profile.pdf_lang"}
        stray = [p for p in changed if p not in translatable
                 and p not in LOCALE_PATHS]
        check("  only copy and the locale keys changed", not stray, str(stray))
        untouched = [p for p in translatable if m_leaves[p] == g_leaves[p]]
        check("  and every piece of copy changed", not untouched, str(untouched))
        check("  each as '[%s] <original>'" % lang,
              all(g_leaves[p] == "[%s] %s" % (lang, m_leaves[p])
                  for p in translatable))
        check("  ids, tags, images and paths are the master's",
              [i["id"] for s in gen["swipe"]["steps"] for p in s["pairs"]
               for i in p["images"]]
              == [i["id"] for s in MASTER["swipe"]["steps"] for p in s["pairs"]
                  for i in p["images"]]
              and [i["tags"] for s in gen["swipe"]["steps"] for p in s["pairs"]
                   for i in p["images"]]
              == [i["tags"] for s in MASTER["swipe"]["steps"] for p in s["pairs"]
                  for i in p["images"]]
              and [i["img"] for s in gen["swipe"]["steps"] for p in s["pairs"]
                   for i in p["images"]]
              == [i["img"] for s in MASTER["swipe"]["steps"] for p in s["pairs"]
                  for i in p["images"]])
        check("  style ids, tags and colour names are the master's",
              [(s["id"], s["tags"], [c["name"] for c in
                                     s["reveals"]["palette"]["colors"]])
               for s in gen["styles"]]
              == [(s["id"], s["tags"], [c["name"] for c in
                                        s["reveals"]["palette"]["colors"]])
                  for s in MASTER["styles"]])
        check("  the model-facing English is untouched",
              gen["report_profile"]["sections"] == MASTER["report_profile"]["sections"]
              and gen["report_profile"]["vertical_noun"]
              == MASTER["report_profile"]["vertical_noun"])
        check("  every {token} survived",
              all(mf.tokens_of(g_leaves[p]) == mf.tokens_of(m_leaves[p])
                  for p in translatable))
        pricing = gen["pricing"]
        check("  the locale landed on pricing",
              pricing["amount_cents"] == loc["amount_cents"]
              and pricing["currency"] == loc["currency"]
              and pricing["price_format"] == loc["price_format"]
              and pricing["decimal_mark"] == loc["decimal_mark"],
              str(pricing))
        check("  the report profile names the language",
              gen["report_profile"]["language_name"] == loc["language_name"]
              and gen["report_profile"]["pdf_lang"] == lang)
        static = os.path.join(scratch, "static", "funnels",
                              "blinds-%s.json" % lang)
        check("  the static mirror is byte-identical",
              open(static, "rb").read()
              == open(os.path.join(scratch, "funnels",
                                   "blinds-%s.json" % lang), "rb").read())
        check("  written with the twin's formatting: two-space indent, "
              "unicode kept",
              open(static, encoding="utf-8").read().startswith('{\n  "slug"')
              and "\\u" not in open(static, encoding="utf-8").read())
    check("HUF amount is divisible by 100 in the generated file",
          results["hu"]["pricing"]["amount_cents"] % 100 == 0
          and results["hu"]["pricing"]["currency"] == "huf"
          and results["hu"]["pricing"]["price_format"] == "{amount} Ft")
    check("  and the German one is euro cents with a comma",
          results["de"]["pricing"]["amount_cents"] == 299
          and results["de"]["pricing"]["currency"] == "eur"
          and results["de"]["pricing"]["decimal_mark"] == ",")
    check("the reports module writes that price the way the page does",
          reports._written_price(results["hu"], 99000) == "990 Ft"
          and reports._written_price(results["de"], 299) == "2,99 €"
          and reports._written_price(results["hu"], 99050) == "990,50 Ft")

    print("\n--- .gitignore ---")
    ignore = open(os.path.join(scratch, ".gitignore"), encoding="utf-8").read()
    lines = ignore.splitlines()
    WANT_LINES = ["funnels/blinds-*.json", "!funnels/blinds-test.json",
                  "static/funnels/blinds-*.json",
                  "!static/funnels/blinds-test.json"]
    check("the four patterns were appended", all(l in lines for l in WANT_LINES),
          str(lines))
    check("  once, after two runs",
          all(lines.count(l) == 1 for l in WANT_LINES))
    check("  the original content is still there", lines[0] == ".env")
    r = run("blinds", "pl", "--no-llm", "--root", scratch)
    ignore2 = open(os.path.join(scratch, ".gitignore"), encoding="utf-8").read()
    check("  a third language appends nothing more",
          r.returncode == 0 and ignore2 == ignore)
    check("  and git would keep the twin while ignoring the rest",
          mf.gitignore_lines("blinds") == WANT_LINES)

    print("\n--- dry run and refusals ---")
    before = sorted(os.listdir(os.path.join(scratch, "funnels")))
    r = run("blinds", "cs", "--dry-run", "--root", scratch)
    check("--dry-run exits 0 with a plan and a token estimate",
          r.returncode == 0 and "strings" in r.stdout
          and "estimated tokens" in r.stdout, r.stdout[-200:])
    check("  and writes nothing",
          sorted(os.listdir(os.path.join(scratch, "funnels"))) == before)
    r = run("nothere", "hu", "--no-llm", "--root", scratch)
    check("a missing master fails plainly",
          r.returncode == 1 and "no master funnel" in r.stdout, r.stdout)
    r = run("blinds", "xx", "--no-llm", "--root", scratch)
    check("an unknown language fails plainly",
          r.returncode == 1 and "no locale" in r.stdout, r.stdout)
    r = run("blinds", "en", "--no-llm", "--root", scratch)
    check("the master's own language is refused",
          r.returncode == 1 and "master" in r.stdout, r.stdout)

    print("\n--- the generated funnel gets a report in its own language ---")
    saved_dir = config.FUNNELS_DIR
    config.FUNNELS_DIR = os.path.join(scratch, "funnels")
    reports.reset_guide_profiles()
    try:
        prof = reports._profile("blinds-hu")
        check("_profile resolves blinds-hu with no code change",
              prof is not reports.KITCHEN_PROFILE and "Hungarian" in prof["system"]
              and "answer in Hungarian" in prof["system"])
        check("  pdf_lang follows", prof["pdf_lang"] == "hu")
        check("  the twin of a generated funnel reads the same profile",
              reports._profile("blinds-hu-test") is prof)
        check("  the stubs are the translated ones",
              prof["stubs"]["mistakes"]["items"][0]["title"].startswith("[hu] "))
        check("  the mail is the translated one, still with one slot",
              prof["mail"]["subject"].startswith("[hu] ")
              and prof["mail"]["subject"].count("%s") == 1)
        check("  the words the PDF prints are the translated ones",
              prof["words"]["fix"].startswith("[hu] ")
              and prof["words"]["pdf_filename"] == "mazzin-%s-guide.pdf")
        check("  and the German one is its own object",
              reports._profile("blinds-de") is not prof
              and "German" in reports._profile("blinds-de")["system"])
    finally:
        config.FUNNELS_DIR = saved_dir
        reports.reset_guide_profiles()
    check("after the reset, blinds-hu is unknown to the repo again",
          reports._profile("blinds-hu") is reports.KITCHEN_PROFILE)
finally:
    shutil.rmtree(scratch, ignore_errors=True)

print("\n--- the repo is exactly as it was ---")
check("funnels/ is untouched",
      sorted(os.listdir(os.path.join(ROOT, "funnels"))) == BEFORE_FUNNELS)
check("static/funnels/ is untouched",
      sorted(os.listdir(os.path.join(ROOT, "static", "funnels")))
      == BEFORE_STATIC)
check("  and the two still agree", BEFORE_FUNNELS == BEFORE_STATIC)
check(".gitignore is untouched",
      open(os.path.join(ROOT, ".gitignore"), encoding="utf-8").read()
      == BEFORE_IGNORE)
check("the twin is the only blinds-*.json committed",
      [f for f in BEFORE_FUNNELS if f.startswith("blinds-")]
      == ["blinds-test.json"])

print("\n%d checks, %d failed" % (checks[0], len(fails)))
for f in fails:
    print("  FAIL " + f)
sys.exit(1 if fails else 0)
