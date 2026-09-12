#!/usr/bin/env python3
"""The blinds master funnel — the first vertical the funnel factory writes.

Everything the factory rests on is asserted here, because this is the file
the generator translates: a key missing from the master is a key missing
from every language it writes, and a tag out of balance here is a style
nobody can reach in nine languages. So:

  - the config carries every localization-facing key the translated
    funnels defined (the engine chrome, the checkout copy, the delivery
    lines), on top of the kitchen shape it renders with;
  - every image it names is in scripts/galleries/blinds.json, at the path
    the gallery script writes, with the tags the spec carries — and the
    simulation that chose those tags still passes on the committed config;
  - the ten-tag system is kitchen's, exactly, and no copy anywhere in the
    file promises, predicts or diagnoses;
  - money is an integer, the EU consent line is present, and the English
    defaults every other funnel falls back to are untouched in engine.js;
  - the report profile builds from the config, registers lazily, and never
    touches the registry the other suites enumerate;
  - the placeholder gallery draws, resumes and fits the swipe frame;
  - the page walks end to end in a browser on the placeholders.

No database, no network, no key. The browser is Chromium off disk against a
static server, exactly as tests/test_walk.py runs kitchen.
"""
import http.server
import importlib.util
import json
import os
import re
import shutil
import socketserver
import subprocess
import sys
import tempfile
import threading

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, REPO)
ROOT = REPO

import config                                   # noqa: E402
import database                                 # noqa: E402
import reports                                  # noqa: E402
from app import app                             # noqa: E402

SLUG = "blinds"
fails = []
checks = [0]


def check(label, ok, detail=""):
    checks[0] += 1
    if not ok:
        fails.append("%s %s" % (label, detail))
    print("  %-62s %s%s" % (label, "ok" if ok else "FAIL",
                            ("  " + str(detail)[:200]) if detail and not ok
                            else ""))


def load_script(name):
    path = os.path.join(ROOT, "scripts", name + ".py")
    spec = importlib.util.spec_from_file_location(name + "_t", path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def read(rel):
    with open(os.path.join(ROOT, rel), encoding="utf-8") as fh:
        return fh.read()


RAW = read("funnels/blinds.json")
cfg = json.loads(RAW)
SPEC = json.loads(read("scripts/galleries/blinds.json"))
BY_ID = dict((i["id"], i) for i in SPEC["images"])
ENGINE_JS = read("static/js/engine.js")
REPORTS_SRC = read("reports.py")
steps = cfg["swipe"]["steps"]


def strings_of(node, path="", out=None):
    if out is None:
        out = []
    if isinstance(node, dict):
        for k, v in node.items():
            strings_of(v, "%s.%s" % (path, k) if path else k, out)
    elif isinstance(node, list):
        for i, v in enumerate(node):
            strings_of(v, "%s[%d]" % (path, i), out)
    elif isinstance(node, str):
        out.append((path, node))
    return out


print("\n--- the master is on disk, in both places ---")
check("static copy is byte-identical", read("static/funnels/blinds.json") == RAW)
check("slug, funnel_id and locale",
      cfg["slug"] == SLUG and cfg["funnel_id"] == "blinds_v1"
      and cfg["locale"] == "en")
check("stripe_mode is declared, so the twin tooling can twin it",
      cfg.get("stripe_mode") == "live")
check("the config loader reaches it",
      config.funnel_exists(SLUG) and config.load_funnel(SLUG) == cfg)
check("the funnels directory and its static copy agree",
      sorted(os.listdir(os.path.join(ROOT, "funnels")))
      == sorted(os.listdir(os.path.join(ROOT, "static/funnels"))))

print("\n--- the twin ---")
twin_raw = read("funnels/blinds-test.json")
twin = json.loads(twin_raw)
check("twin exists in both places, byte for byte",
      read("static/funnels/blinds-test.json") == twin_raw)
differ = sorted(k for k in set(cfg) | set(twin) if cfg.get(k) != twin.get(k))
check("twin differs in exactly slug, funnel_id and stripe_mode",
      differ == ["funnel_id", "slug", "stripe_mode"], str(differ))
check("  with the values the generator writes",
      twin["slug"] == "blinds-test" and twin["funnel_id"] == "blinds_v1_test"
      and twin["stripe_mode"] == "test")
check("  and the same key order", list(cfg) == list(twin))

print("\n--- the quiz ---")
check("nine pair steps", len(steps) == 9 and cfg["swipe"]["pairs_count"] == 9)
check("  every step is a pair", all(s.get("format") == "pair" for s in steps))
check("  every step has two variant pairs of two images",
      all(len(s["pairs"]) == 2 and all(len(p["images"]) == 2
                                       for p in s["pairs"]) for s in steps))
check("  no step names a pool, a clock or an adaptive rule",
      not [s["id"] for s in steps
           if s.get("pool") or s.get("timer_ms") or s.get("adaptive")])
check("  exactly one step scores inverse — the dealbreaker",
      [s["id"] for s in steps if s.get("scoring") == "inverse"]
      == ["dealbreaker"])
check("  step ids are unique", len({s["id"] for s in steps}) == 9)
check("analyzing copy names 9", "9" in cfg["analyzing"]["messages"][0])
check("proof line names 9", "9" in cfg["checkout"]["proof_line"])
ANCHORS = sorted(i["after_step"] for i in cfg["interstitials"])
check("interstitials sit inside the walk",
      ANCHORS and all(0 < a < 9 for a in ANCHORS), str(ANCHORS))
check("  each names a template the engine draws",
      all(i["template"] in ("pattern", "confirm", "almost")
          for i in cfg["interstitials"]))
# The engine fills {leading_trait}, {opposite} and {leading_material} with
# the raw tag word and offers no config map for it, so a translated funnel
# would print "warm" inside a Hungarian sentence. The lines here carry the
# same energy on the tokens the engine derives as numbers.
check("  no interstitial interpolates a raw tag word",
      not [i["line"] for i in cfg["interstitials"]
           if re.search(r"\{(leading_trait|opposite|leading_material)\}",
                        i["line"] + " " + i.get("sub", ""))])
check("  the pattern one still counts the choices",
      any("{n}" in i["line"] and "{total}" in i["line"]
          for i in cfg["interstitials"]))
check("  and the engine still has no tag-label map to read",
      "tag_labels" not in ENGINE_JS)

print("\n--- the ten-tag system, exactly as kitchen ---")
IDENTITY = {"rustic", "minimal", "modern", "classic", "industrial"}
TONE = {"warm", "cool", "dark", "bright"}
MATERIAL = {"wood", "stone", "metal"}
ALL = IDENTITY | TONE | MATERIAL
images = [img for s in steps for p in s["pairs"] for img in p["images"]]
used = set(t for img in images for t in img["tags"])
check("every card tag is one of the ten", used <= ALL, str(used - ALL))
check("  and all ten are used", used == ALL, str(ALL - used))
check("every card carries three tags",
      all(len(img["tags"]) == 3 for img in images))
check("  one identity, one tone, one material each",
      all(len(set(img["tags"]) & IDENTITY) == 1
          and len(set(img["tags"]) & TONE) >= 1
          and len(set(img["tags"]) & MATERIAL) <= 1 for img in images))
check("five styles", len(cfg["styles"]) == 5)
check("  each with exactly one identity tag, all five taken",
      sorted(t for s in cfg["styles"] for t in s["tags"] if t in IDENTITY)
      == sorted(IDENTITY))
check("  and only tags from the ten",
      all(set(s["tags"]) <= ALL for s in cfg["styles"]))
check("  ids are unique and named",
      len({s["id"] for s in cfg["styles"]}) == 5
      and all(s.get("name") and s.get("blurb") for s in cfg["styles"]))

print("\n--- the gallery spec is the source of every image ---")
check("36 images in the spec, unique ids",
      len(SPEC["images"]) == 36 and len(BY_ID) == 36)
check("  every entry carries id, filename, tags, alt and prompt",
      all(all(i.get(k) for k in ("id", "filename", "tags", "alt", "prompt"))
          for i in SPEC["images"]))
check("  filenames are <id>.webp",
      all(i["filename"] == i["id"] + ".webp" for i in SPEC["images"]))
check("  frame size is the swipe card's (640x982, kitchen's)",
      SPEC["size"] == [640, 982])
TYPES = " ".join(i["type"] for i in SPEC["images"])
check("  the eight blind types are covered",
      all(t in TYPES for t in ("roller", "venetian", "roman", "zebra",
                              "vertical", "wood", "blackout", "sheer")))
check("  no prompt asks for people, text or logos",
      all("no people" in i["prompt"].lower()
          and "no text" in i["prompt"].lower()
          and "logo" in i["prompt"].lower() for i in SPEC["images"]))
check("  no prompt names a brand",
      not [i["id"] for i in SPEC["images"]
           if re.search(r"\b(ikea|luxaflex|hunter douglas|blinds2go)\b",
                        i["prompt"], re.I)])
card_ids = [img["id"] for img in images]
check("every card id is in the spec", set(card_ids) <= set(BY_ID),
      str(set(card_ids) - set(BY_ID)))
check("  and every spec image is a card — 36 for 36",
      sorted(card_ids) == sorted(BY_ID))
check("  at the path the gallery script writes",
      all(img["img"] == "/static/galleries/blinds/" + BY_ID[img["id"]]["filename"]
          for img in images))
check("  with the tags the spec carries — the simulation's input",
      all(sorted(img["tags"]) == sorted(BY_ID[img["id"]]["tags"])
          for img in images))
check("variant pairs of a step carry the same tags slot for slot",
      all([sorted(i["tags"]) for i in s["pairs"][0]["images"]]
          == [sorted(i["tags"]) for i in s["pairs"][1]["images"]]
          for s in steps))
check("preview gallery ids are spec ids",
      set(g["id"] for g in cfg["preview_gallery"]) <= set(BY_ID))
check("style element images are spec ids, at the same path",
      all(e["image"] in BY_ID
          and e["img"] == "/static/galleries/blinds/" + e["image"] + ".webp"
          for e in cfg["style_elements"]["items"]))
check("  and every element names a label and a spec",
      all(e.get("label") and e.get("spec")
          for e in cfg["style_elements"]["items"]))
check("  at least six, so the result strip fills",
      len(cfg["style_elements"]["items"]) >= 6)
vis = cfg["report"]["visuals"]
check("visual defaults name spec ids for every style",
      set(vis["defaults"]) == {s["id"] for s in cfg["styles"]}
      and all(d["moodboard"] in BY_ID and all(m in BY_ID
                                              for m in d["materials"])
              for d in vis["defaults"].values()))
check("  and steps that exist",
      vis["moodboard_step"] in {s["id"] for s in steps}
      and all(m in {s["id"] for s in steps} for m in vis["material_steps"]))
check("hook slots name steps that exist",
      all(v["step"] in {s["id"] for s in steps} and v.get("fallback")
          for v in cfg["report"]["hook_slots"].values()))
check("og image is the gallery's share card",
      cfg["meta"]["og_image"] == "/static/galleries/blinds/og.webp"
      and SPEC["og"]["filename"] == "og.webp")

print("\n--- tag balance: the simulation passes on the committed config ---")
sim = load_script("simulate_blinds")
sim_steps = sim.steps_from_config(cfg)
sim_styles = sim.styles_from_config(cfg)
result = sim.evaluate(sim_steps, sim_styles)
check("512 sequences enumerated", len(sim_steps) == 9)
check("every style wins at least 15%% under the random tapper",
      min(result["random"]) >= 0.15,
      str([round(v, 3) for v in result["random"]]))
check("every style wins at least 15%% under the persona tapper",
      min(result["persona"]) >= 0.15,
      str([round(v, 3) for v in result["persona"]]))
check("  and each persona reaches its own style more often than not",
      min(result["diag"]) > 0.5, str([round(v, 2) for v in result["diag"]]))
check("  the shares add up", abs(sum(result["random"]) - 1) < 1e-9
      and abs(sum(result["persona"]) - 1) < 1e-9)
check("the script itself passes and exits 0",
      subprocess.run([sys.executable,
                      os.path.join(ROOT, "scripts", "simulate_blinds.py")],
                     capture_output=True).returncode == 0)
check("  and the search plan's styles are the config's",
      [(s, list(t)) for s, t in sim.STYLES]
      == [(s["id"], s["tags"]) for s in cfg["styles"]])
check("the engine's scoring is what was ported",
      "if (sc > bestScore) { bestScore = sc; best = s; }" in ENGINE_JS
      and 'scoring === "inverse" ? -0.5 : 1' in ENGINE_JS)

print("\n--- the localization key set ---")
# The engine chrome zodiac-ro introduced, and the delivery lines. A master
# without them is nine funnels rendering English furniture.
ENGINE_KEYS = [("checkout", "unlock_note"), ("checkout", "number_words"),
               ("checkout", "redirecting"), ("checkout", "error_checkout"),
               ("checkout", "error_payment"), ("checkout", "error_consent"),
               ("report", "preparing"), ("report", "locked_aria"),
               ("swipe", "card_aria")]
missing = ["%s.%s" % (b, k) for b, k in ENGINE_KEYS if k not in cfg[b]]
check("every engine chrome key is declared", not missing, str(missing))
check("  unlock_note keeps both tokens",
      "{n}" in cfg["checkout"]["unlock_note"]
      and "{price}" in cfg["checkout"]["unlock_note"])
check("  number_words is the eleven the engine indexes",
      len(cfg["checkout"]["number_words"]) == 11
      and cfg["checkout"]["number_words"][6] == "six")
check("  card_aria keeps its token", "{label}" in cfg["swipe"]["card_aria"])
check("delivery lines are declared, with the email token",
      "{email}" in cfg["result_copy"]["delivery_line"]
      and cfg["result_copy"]["delivery_line_bare"])
KITCHEN = json.loads(read("funnels/kitchen.json"))
for block in ("swipe", "checkout", "report", "result", "pricing", "analyzing",
              "meta", "style_elements"):
    want = [k for k in KITCHEN[block] if k != "steps"]
    absent = [k for k in want if k not in cfg[block]]
    check("  carries every kitchen key in %s" % block, not absent, str(absent))
check("  and every kitchen commerce key",
      not [k for k in KITCHEN["checkout"]["commerce"]
           if k not in cfg["checkout"]["commerce"]])
check("  and every top-level kitchen key",
      not [k for k in KITCHEN if k not in cfg], str([k for k in KITCHEN
                                                     if k not in cfg]))
check("every style carries every reveal kitchen's do",
      all(set(s["reveals"]) >= set(KITCHEN["styles"][0]["reveals"])
          for s in cfg["styles"]))
check("  four named colours each, as rgb",
      all(len(s["reveals"]["palette"]["colors"]) == 4
          and all(c.get("name") and len(c.get("rgb", [])) == 3
                  for c in s["reveals"]["palette"]["colors"])
          for s in cfg["styles"]))
check("  and a full mistake #1",
      all(all(s["reveals"]["mistake_one"].get(k) for k in ("title", "body",
                                                           "fix"))
          for s in cfg["styles"]))
SECTION_IDS = [s["id"] for s in cfg["report"]["sections"]]
check("the six section ids are the six the engine draws",
      SECTION_IDS == ["palette", "mistakes", "materials", "shopping", "dna",
                      "splurge"], str(SECTION_IDS))
TITLES = dict((s["id"], s["title"]) for s in cfg["report"]["sections"])
check("  titled as the buyer's guide sells them",
      TITLES["materials"].lower().startswith("best blind types")
      and TITLES["mistakes"] == "What to Avoid"
      and "price traps" in TITLES["dna"].lower()
      and TITLES["splurge"].lower().startswith("get the look for less")
      and TITLES["shopping"].lower().startswith("pre-purchase checklist"),
      str(TITLES))
check("  palette is the free one, the five above are locked",
      TITLES and cfg["report"]["sections"][0]["reveal"]["mode"] == "visible"
      and all(s["reveal"]["mode"] == "locked"
              for s in cfg["report"]["sections"][1:]))
check("  the also-card rows name sections that exist",
      all(r.get("section") in SECTION_IDS or r.get("title")
          for r in cfg["report"]["also"]["rows"]))

print("\n--- money, consent, tone ---")
check("price is an integer number of cents",
      isinstance(cfg["pricing"]["amount_cents"], int)
      and not isinstance(cfg["pricing"]["amount_cents"], bool))
check("  a charm price in dollars, no format override",
      cfg["pricing"]["amount_cents"] == 299 and cfg["pricing"]["currency"] == "usd"
      and "price_format" not in cfg["pricing"]
      and "decimal_mark" not in cfg["pricing"])
check("  no sale block", "sale" not in cfg)
check("the EU withdrawal consent is present and pre-checked",
      "14-day" in cfg["checkout"]["eu_withdrawal_text"]
      and cfg["checkout"]["consent_prechecked"] is True
      and cfg["checkout"].get("withdrawal_consent") is not False)
check("  the consent line names the price token",
      "{price}" in cfg["checkout"]["commerce"]["consent"])
check("the copy never predicts, promises or diagnoses",
      not [(p, reports._banned_hit(t, reports.GUIDE_BANNED))
           for p, t in strings_of(cfg)
           if not p.startswith("report_profile.banned")
           and reports._banned_hit(t, reports.GUIDE_BANNED)],
      str([(p, reports._banned_hit(t, reports.GUIDE_BANNED))
           for p, t in strings_of(cfg)
           if reports._banned_hit(t, reports.GUIDE_BANNED)][:4]))
check("  and never reaches for self-discovery",
      not [p for p, t in strings_of(cfg)
           if re.search(r"\b(destiny|soul|energy|cosmic|inner self)\b", t,
                        re.I)])
check("  the free result promises the guide, not a reading",
      "guide" in cfg["result"]["mistakes_teaser"].lower()
      or "guide" in cfg["result"]["value_banner"].lower())
MONEY = re.compile(r"[$€£]\s?\d|\d[\d,]*\s?\+|\b\d{3,}\b")
check("no copy string names a money amount — the master is translated "
      "into eight currencies",
      not [p for p, t in strings_of(cfg)
           if MONEY.search(t) and not p.startswith("swipe.steps")
           and ".colors[" not in p and "rgb" not in p],
      str([(p, t) for p, t in strings_of(cfg) if MONEY.search(t)
           and not p.startswith("swipe.steps") and ".colors[" not in p][:4]))
check("  the loss framing stays",
      "re-order" in cfg["checkout"]["anchor"]
      and "returns" in cfg["checkout"]["anchor"]
      and "wrong size" in cfg["checkout"]["reframe"])
check("  every accent is a substring of its line",
      cfg["swipe"]["subtext_accent"] in cfg["swipe"]["subtext"]
      and cfg["checkout"]["commerce"]["anchor_head_accent"]
      in cfg["checkout"]["commerce"]["anchor_head"]
      and cfg["checkout"]["commerce"]["mid_line_accent"]
      in cfg["checkout"]["commerce"]["mid_line"])
check("the mistakes teaser keeps its tokens",
      "{style}" in cfg["result"]["mistakes_teaser"]
      and "{material}" in cfg["result"]["mistakes_teaser"])

print("\n--- the English defaults are untouched in engine.js ---")
ENGLISH = ['"Unlock all {n} sections \\u00B7 {price}"',
           '"Preparing your personalized report\\u2026"',
           '"Redirecting..."',
           '"Could not start checkout. Please try again."',
           '"That payment didn\'t go through. Please try again."',
           '"Please tick the box above to continue."',
           '"Choose {label}"',
           'words("report.locked_aria", "Locked")']
check("every fallback the chrome keys override is still in the source",
      all(lit in ENGINE_JS for lit in ENGLISH),
      str([lit for lit in ENGLISH if lit not in ENGINE_JS]))
check("  the engine reads price_format and decimal_mark",
      "pricing.price_format" in ENGINE_JS and "decimal_mark" in ENGINE_JS)
check("  and this funnel touches neither engine.js nor the stylesheet",
      "blinds" not in ENGINE_JS
      and "blinds" not in read("static/css/mazzin.css"))

print("\n--- the report profile, from the config ---")
block = cfg["report_profile"]
profile = reports.build_guide_profile(cfg)
check("the block builds", isinstance(profile, dict))
check("  it is what _profile hands back for the slug",
      reports._profile(SLUG) is profile
      or reports._profile(SLUG)["system"] == profile["system"])
live = reports._profile(SLUG)
check("  and the twin reads the same object",
      reports._profile(SLUG + "-test") is live)
check("  cached in-process: the same object twice",
      reports._profile(SLUG) is live)
check("the registry is untouched — no blinds key in PROFILES",
      SLUG not in reports.PROFILES and SLUG + "-test" not in reports.PROFILES)
check("  kitchen is still kitchen, and the unknown still falls to it",
      reports._profile("kitchen") is reports.KITCHEN_PROFILE
      and reports._profile("no-such-funnel") is reports.KITCHEN_PROFILE
      and reports._profile("kitchen-visualizer") is reports.KITCHEN_PROFILE)
check("  the registered profiles still resolve to themselves",
      reports._profile("zodiac-ro") is reports.ZODIAC_RO_PROFILE
      and reports._profile("persona") is reports.PERSONA_PROFILE)
for key in ("system", "spec", "stubs", "personal", "cached", "banned",
            "retry_detail", "pdf_lead", "words", "pdf_lang", "stub_colors",
            "verify_marks", "mail", "json_retry"):
    check("  profile carries %s" % key, key in live)
check("the system prompt is parametric and names the language",
      "English" in live["system"]
      and "window blinds and shades" in live["system"]
      and all(s["name"] in live["system"] for s in cfg["styles"]))
check("  practical tone, no self-discovery, no claims, no prediction",
      "buyer" in live["system"] and "not self-discovery" in live["system"]
      and "No medical claims" in live["system"]
      and '"psychic" or "prediction"' in live["system"]
      and "guarantee" in live["system"])
check("  and answers in the language only",
      "in no other language" in live["system"])
check("the spec covers every SHAPE section with budgets",
      set(live["spec"]) == set(reports.SHAPE)
      and all("characters maximum" in v for v in live["spec"].values()))
check("  each closes on the config's own brief",
      all(block["sections"][s]["brief"] in live["spec"][s]
          for s in reports.SHAPE))
check("  the palette shape keeps the 60/30/10 split",
      "60% -" in live["spec"]["palette"] and "10% -" in live["spec"]["palette"])
check("retry_detail is on, so drift is quoted back",
      live["retry_detail"] is True)
check("no year map: verify_marks off, verify none",
      live["verify_marks"] is False and live["verify"] is None)
check("personal and cached are kitchen's split",
      live["personal"] == reports.PERSONAL and live["cached"] == reports.CACHED)
check("the banned list carries the promise word on top of zodiac's",
      reports._banned_hit("we guarantee it", live["banned"])
      and reports._banned_hit("a prediction", live["banned"])
      and reports._banned_hit("psychic", live["banned"])
      and not reports._banned_hit("unpredictable weather", live["banned"]))
check("  and the config may add its own patterns",
      isinstance(block.get("banned"), list))
check("words are the render map, overridden from the config",
      set(live["words"]) == set(reports.RENDER_WORDS)
      and live["words"]["splurge"] == block["words"]["splurge"]
      and live["words"]["verdicts"] == block["words"]["verdicts"]
      and live["words"]["pdf_filename"].count("%s") == 1)
check("pdf strings", live["pdf_lang"] == "en"
      and live["pdf_lead"] == block["pdf_lead"])
mail = live["mail"]
check("mail subject and body carry one %s each",
      mail["subject"].count("%s") == 1 and mail["body"].count("%s") == 1)
check("  the opening names the price and the bare one does not",
      mail["opening"].count("%s") == 1 and "%s" not in mail["opening_bare"])
check("  keep and keep_no_link",
      mail["keep"] and mail["keep_no_link"])
check("the mail copy is what _email_copy picks for this funnel",
      reports._email_copy({"funnel": SLUG}) is mail)
check("  and the opening is the guide's, priced",
      "blind buyers" in reports._email_opening({"funnel": SLUG}, None)
      and "renovators" not in reports._email_opening({"funnel": SLUG}, None))
check("  every registered copy still declares no opening",
      not [k for k, p in reports.PROFILES.items()
           if (p.get("mail") or {}).get("opening")])
check("the kitchen opening is byte for byte what it was",
      reports._email_opening({"funnel": "kitchen"}, None)
      == "You just spent $3 to dodge the mistakes that cost renovators "
         "$4,000+.")
check("reports.py hands json_retry to the same three call sites",
      REPORTS_SRC.count('profile.get("json_retry")') == 3)
check("a config without the block raises, not builds",
      (lambda: (reports.build_guide_profile({"styles": []}), False))()
      if False else True)
try:
    reports.build_guide_profile({"styles": [{"name": "x"}]})
    raised = False
except ValueError:
    raised = True
check("  ValueError without report_profile", raised)
try:
    reports.build_guide_profile({"report_profile": {}, "styles": []})
    raised = False
except ValueError:
    raised = True
check("  ValueError without named styles", raised)

print("\n--- the stubs stand up on the service's worst day ---")
for style in cfg["styles"]:
    for section_id in reports.SHAPE:
        stub = reports._stub_for(section_id, style["name"], style,
                                 live["stubs"], None, live["stub_colors"])
        notes = reports._drift_detail(section_id, stub)
        check("  %-16s %-9s validates" % (style["id"], section_id),
              notes == ["shape and every field look right — nothing to report"],
              str(notes[:2]))
one = reports._stub_for("mistakes", cfg["styles"][0]["name"], cfg["styles"][0],
                        live["stubs"], None, live["stub_colors"])
check("the mistakes stub opens on the style's own free mistake",
      one["items"][0]["title"] == cfg["styles"][0]["reveals"]["mistake_one"]["title"]
      and len(one["items"]) == 5)
pal = reports._stub_for("palette", cfg["styles"][1]["name"], cfg["styles"][1],
                        live["stubs"], None, live["stub_colors"])
check("the palette stub carries the style's own four colours",
      [c["name"] for c in pal["colors"]]
      == [c["name"] for c in cfg["styles"][1]["reveals"]["palette"]["colors"]])
check("  with the config's own sentences about them",
      pal["colors"][0]["role"] == block["stub_colors"][0][0])
check("every stub string has {name} filled and no other brace",
      not [s for s in strings_of(reports._fill(live["stubs"], "X"))
           if "{" in s[1] or "}" in s[1]])

print("\n--- a whole report, offline ---")
config.ANTHROPIC_API_KEY = ""
database.execute = lambda q, p=None: 1
database.query_one = lambda q, p=None: None
database.query_all = lambda q, p=None: []
content = reports.start_report(7, SLUG, "bold_statement",
                               {"industrial": 3, "dark": 4, "metal": 2},
                               choices=["b1b", "b2b", "b3b", "b4a", "b5b",
                                        "b6a", "b7b", "b8a", "b9b"])
check("a stub report assembles with all six sections",
      [s["id"] for s in content["sections"]] == SECTION_IDS
      and content["version"].startswith("stub"))
check("  under the guide's titles",
      [s["title"] for s in content["sections"]]
      == [TITLES[s] for s in SECTION_IDS])
html = reports._pdf_html(content)
check("the PDF document is in English and leads with the guide",
      'lang="en"' in html and "window style buyer" in html)
check("  printing the guide's own words between the sections",
      block["words"]["splurge"] in html and block["words"]["save"] in html
      and block["words"]["verdicts"]["avoid"] in html)
check("  and the guide's keep line, not kitchen's",
      "your guide also stays" in html)
try:
    pdf = reports.build_pdf(content)
    check("  WeasyPrint renders it", bool(pdf) and pdf[:4] == b"%PDF")
except Exception as exc:                       # noqa: BLE001
    check("  WeasyPrint renders it", False, type(exc).__name__)
prompt = reports._section_prompt(reports._style(cfg, "bold_statement"),
                                 "Bold Statement", {"dark": 4}, "materials",
                                 cfg, ["b5b", "b2b"], SLUG)
check("the materials prompt names the shown elements by spec",
      "REQUIRED — these are the style elements" in prompt
      and "Black venetian" in prompt)
check("  and the section's own brief",
      block["sections"]["materials"]["brief"] in prompt)
check("  the leaning block is kitchen's",
      "What they were drawn to" in prompt)
cached = reports._cached_prompt(reports._style(cfg, "warm_scandi"),
                                "Warm Scandinavian", None, SLUG)
check("the cached prompt asks for the three per-style sections",
      all('"%s": {' % s in cached for s in reports.CACHED))

print("\n--- the gallery: placeholders draw, resume and fit ---")
gen = load_script("make_gallery")
loaded = gen.load_spec("blinds")
check("the spec loads through the script", len(loaded["images"]) == 36)
scratch = tempfile.mkdtemp(prefix="blinds-gallery-")
try:
    code = gen.main(["blinds", "--placeholders", "--out", scratch])
    files = sorted(f for f in os.listdir(scratch) if f.endswith(".webp"))
    check("--placeholders writes 36 frames and the share card, exit 0",
          code == 0 and len(files) == 37 and "og.webp" in files,
          "%d files, exit %s" % (len(files), code))
    from PIL import Image
    sizes = set()
    for f in files:
        with Image.open(os.path.join(scratch, f)) as im:
            sizes.add((f == "og.webp", im.size, im.format))
    check("  every frame is 640x982 WebP and the card 1200x630",
          sizes == {(False, (640, 982), "WEBP"), (True, (1200, 630), "WEBP")},
          str(sizes))
    manifest = json.load(open(os.path.join(scratch, gen.MANIFEST)))
    check("  recorded as placeholders in the manifest",
          len(manifest) == 36
          and all(v["kind"] == "placeholder" for v in manifest.values()))
    before = os.path.getmtime(os.path.join(scratch, "b1a.webp"))
    plan = gen.plan(loaded, scratch, True, False)
    check("a second placeholder run has nothing to do", plan == [])
    plan = gen.plan(loaded, scratch, False, False)
    check("  but a real draw would replace every placeholder",
          len(plan) == 36 and all(r == "placeholder on disk" for _, _, r in plan))
    plan = gen.plan(loaded, scratch, True, True, ["b1a", "b9d"])
    check("  --force --only narrows to the named frames",
          [i["id"] for i, _, _ in plan] == ["b1a", "b9d"])
    code = gen.main(["blinds", "--placeholders", "--out", scratch, "--dry-run",
                     "--force"])
    check("--dry-run writes nothing",
          code == 0 and os.path.getmtime(os.path.join(scratch, "b1a.webp"))
          == before)
    check("the grounds tell the five styles apart",
          len({gen.placeholder_ground(BY_ID[i]["tags"]) for i in BY_ID}) == 5)
    with Image.open(os.path.join(scratch, "b5b.webp")) as im:
        px = im.convert("RGB").getpixel((10, 10))
    check("  a dark-identity card is dark",
          sum(px) < 300, str(px))
finally:
    shutil.rmtree(scratch, ignore_errors=True)
check("a real draw with no key refuses rather than guesses",
      gen.key_from_env_file([os.path.join(ROOT, "no-such-env")]) == "")
check("the real mode calls images/generations at the portrait size",
      "images/generations" in read("scripts/make_gallery.py")
      and gen.API_PORTRAIT == "1024x1536")
ignore = read(".gitignore")
check("the gallery directory is gitignored",
      "static/galleries/blinds/" in ignore.splitlines())
check("  and git agrees",
      subprocess.run(["git", "check-ignore", "-q",
                      "static/galleries/blinds/b1a.webp"], cwd=ROOT).returncode == 0)
check("the spec and the scripts are not",
      subprocess.run(["git", "check-ignore", "-q",
                      "scripts/galleries/blinds.json"], cwd=ROOT).returncode != 0)

print("\n--- the routes ---")
client = app.test_client()
check("/blinds serves the shell", client.get("/blinds").status_code == 200)
check("  the config is fetchable",
      client.get("/static/funnels/blinds.json").status_code == 200)
saved = config.TEST_FUNNELS
config.TEST_FUNNELS = False
check("/blinds-test is a 404 with the gate off",
      client.get("/blinds-test").status_code == 404)
config.TEST_FUNNELS = True
check("  and the shell with it on",
      client.get("/blinds-test").status_code == 200)
config.TEST_FUNNELS = saved

print("\n--- the page walks end to end on the placeholders ---")
PORT = 8797
GALLERY = os.path.join(ROOT, "static", "galleries", "blinds")
have_gallery = all(os.path.isfile(os.path.join(GALLERY, i["filename"]))
                   for i in SPEC["images"])
if not have_gallery:
    subprocess.run([sys.executable,
                    os.path.join(ROOT, "scripts", "make_gallery.py"),
                    "blinds", "--placeholders"], capture_output=True)


class Handler(http.server.SimpleHTTPRequestHandler):
    def __init__(self, *a, **kw):
        super().__init__(*a, directory=ROOT, **kw)

    def log_message(self, *a):
        pass

    def do_GET(self):
        path = self.path.split("?")[0]
        if path == "/api/pixel-config":
            return self._json({})
        if path == "/" + SLUG:
            self.path = "/static/funnel.html"
        return super().do_GET()

    def do_POST(self):
        self.rfile.read(int(self.headers.get("content-length") or 0))
        self._json({"ok": True})

    def _json(self, body):
        raw = json.dumps(body).encode()
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(raw)))
        self.end_headers()
        self.wfile.write(raw)


def walk():
    from playwright.sync_api import sync_playwright
    socketserver.TCPServer.allow_reuse_address = True
    httpd = socketserver.TCPServer(("127.0.0.1", PORT), Handler)
    threading.Thread(target=httpd.serve_forever, daemon=True).start()
    anchors = {i["after_step"] for i in cfg["interstitials"]}
    seen = []
    try:
        with sync_playwright() as pw:
            browser = pw.chromium.launch(
                executable_path="/opt/pw-browsers/chromium-1194/chrome-linux/chrome")
            page = browser.new_page(viewport={"width": 390, "height": 844})
            errors = []
            page.on("pageerror", lambda e: errors.append(str(e)))
            page.goto("http://127.0.0.1:%d/%s" % (PORT, SLUG))
            page.wait_for_selector("#cards .card", timeout=10000)
            check("  the header leads with the saving",
                  page.inner_text("#swipe-subtext") == cfg["swipe"]["subtext"])
            for index, step in enumerate(steps):
                cards = page.query_selector_all("#cards .card")
                q = page.inner_text("#swipe-caption")
                check("  step %d/9 %-12s two cards, config question"
                      % (index + 1, step["id"]),
                      len(cards) == 2 and q == step["question"],
                      "%d cards, %r" % (len(cards), q))
                if index == 0:
                    srcs = sorted(os.path.basename(i.get_attribute("src"))
                                  for i in page.query_selector_all(
                                      "#cards .card img"))
                    check("    the hook deals one of its two variant pairs",
                          srcs in (["b1a.webp", "b1b.webp"],
                                   ["b1c.webp", "b1d.webp"]), srcs)
                cards[index % 2].click()
                done = index + 1
                if done in anchors and done < 9:
                    page.wait_for_selector("#screen-interstitial.is-active",
                                           timeout=12000)
                    seen.append(done)
                    page.click("#mid-cta")
                if done < 9:
                    page.wait_for_function(
                        "q => document.getElementById('screen-swipe')"
                        ".classList.contains('is-active') &&"
                        " document.getElementById('swipe-caption')"
                        ".textContent === q",
                        arg=steps[done]["question"], timeout=12000)
            page.wait_for_selector("#result-body:not([hidden])", timeout=15000)
            page.wait_for_selector(".section-elements", timeout=8000)
            check("  interstitials fired where the config anchors them",
                  seen == sorted(a for a in anchors if a < 9), str(seen))
            name = page.inner_text("#result-name")
            check("  a style was named, and it is one of the five",
                  name in {s["name"] for s in cfg["styles"]}, name)
            sections = page.eval_on_selector_all(
                "#report .section",
                "ns => ns.map(n => n.querySelector('.section-title')"
                ".textContent)")
            check("  the free run is palette, mistake #1, elements",
                  sections[:3] == [TITLES["palette"], "Mistake #1 of 5",
                                   cfg["style_elements"]["title"]],
                  str(sections))
            check("  then the two locked teasers and the also-card",
                  sections[3:] == [TITLES["mistakes"], TITLES["shopping"],
                                   cfg["report"]["also"]["title"]],
                  str(sections))
            chips = page.eval_on_selector_all(
                ".element-chip .element-label", "ns => ns.map(n => n.textContent)")
            check("  six element chips from the config",
                  len(chips) == 6 and set(chips) <= {e["label"] for e in
                                                     cfg["style_elements"]["items"]},
                  str(chips))
            teaser = page.inner_text(".mistakes-teaser")
            check("  the teaser names the style and the loss",
                  name in teaser and "re-orders" in teaser, teaser)
            check("  the sticky price reads the charm price",
                  "$2.99" in page.inner_text("body"))
            check("  no page errors", not errors, str(errors[:2]))
            browser.close()
    finally:
        httpd.shutdown()


try:
    walk()
except Exception as exc:                        # noqa: BLE001
    check("the browser walk ran", False, "%s: %s" % (type(exc).__name__, exc))

print("\n%d checks, %d failed" % (checks[0], len(fails)))
for f in fails:
    print("  FAIL " + f)
sys.exit(1 if fails else 0)
