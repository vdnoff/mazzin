#!/usr/bin/env python3
"""The three engine capabilities the memory funnel is going to need.

/brain is a memory game rather than a taste quiz: it shows a set of pictures,
takes them away, and asks what was there. None of the three things that needs
existed as anything a funnel could turn on, and all three had to be added to
files every live funnel already runs — so what this suite is actually about is
that none of them can reach a funnel that has not asked. /brain has since
landed and asks for the first two; every other funnel is where it was.

  1. The `flash` interstitial: the memorise screen. Gated on the entry naming
     the template, carrying frames, and saying how long it holds for.
  2. Four domain axes — mem, spa, chg, foc — so a personal line can key on how
     a round went. Gated on a card carrying one of the eight tags.
  3. `elapsed_ms` on the swipe event: how long the question was on screen.
     Gated on the funnel naming `track_timing`.

The third gate is not decoration. `/api/track` validates a swipe payload
against a closed set of keys and refuses the whole event on one it does not
know, so an engine that sent this from every funnel would drop every swipe row
the platform records. The gate is what keeps that from happening, and the
check below that no shipping funnel carries the key is what keeps it true.
/brain does not turn it on: it will need tracking.SWIPE_EXTRA_KEYS taught the
key on the same deploy that sets it, so until then nothing sends it.

Everything is read off disk. No database, no network, no key.

    python3 tests/test_brain_engine.py
"""
import json
import os
import re
import sys

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, REPO)
ROOT = REPO

fails = []
checks = [0]


def check(label, ok, detail=""):
    checks[0] += 1
    if not ok:
        fails.append("%s %s" % (label, detail))
    print("  %-62s %s%s" % (label, "ok" if ok else "FAIL",
                            ("  " + str(detail)) if detail and not ok else ""))


ENGINE = open(os.path.join(ROOT, "static/js/engine.js"),
              encoding="utf-8").read()
CSS = open(os.path.join(ROOT, "static/css/mazzin.css"), encoding="utf-8").read()
PAYMENTS = open(os.path.join(ROOT, "payments.py"), encoding="utf-8").read()

import tracking                                            # noqa: E402


def body(name):
    """One top-level function's body, the way the other suites read them."""
    hit = re.search(r"function %s\([^)]*\)\s*\{(.*?)\n  \}" % name,
                    ENGINE, re.S)
    return hit.group(1) if hit else ""


# Every selector in the stylesheet, ignoring at-rules and nested blocks.
RULES = [r.strip() for r in re.findall(r"^[^\s@}/][^{}]*(?=\{)", CSS, re.M)]

FUNNELS = os.path.join(ROOT, "funnels")
CONFIGS = {name: json.load(open(os.path.join(FUNNELS, name), encoding="utf-8"))
           for name in sorted(os.listdir(FUNNELS)) if name.endswith(".json")}


print("--- 1. the flash interstitial ---")
flash_fn = body("isFlash")
check("engine.js knows the template by name",
      'entry.template === "flash"' in flash_fn, flash_fn[:200])
check("  and an entry that does not name it is not one",
      "function isFlash(" in ENGINE and flash_fn.count("return") == 1)
check("  frames are required, so an empty set draws no screen",
      "flash.images && flash.images.length" in flash_fn)
check("  and a timing is too, because there is no button to leave by",
      "autoAdvanceMs(entry)" in flash_fn)

set_fn = body("setFlash")
check("the screen is built only for an entry that is one",
      "if (!isFlash(entry)) {" in set_fn
      and "host.hidden = true;" in set_fn, set_fn[:200])
check("  built on first use, like the echo row and the accent",
      "if (!host) {" in set_fn and 'elm("div", "mid is-flash")' in set_fn
      and "el.midFlash = host;" in set_fn)
check("  and refilled on every open rather than left as it was",
      'host.innerHTML = "";' in set_fn)
opened = body("openInterstitial")
check("the open builds it beside the echo row",
      "setFlash(entry);" in opened, opened[:200])
check("  the button is still hidden by the timing, not by the template",
      "el.midCta.hidden = midAuto;" in opened)
check("  the subline is cleared, so the frames stand alone",
      "el.midSub.hidden = true;" in opened and "var flash = isFlash(entry);"
      in opened)
check("  and the handoff line is suppressed with it",
      'setHandoff(flash ? "" : (entry.next || ""));' in opened)

echo_fn = body("setEcho")
check("a flash gets no echo row",
      "if (isFlash(entry)) {" in echo_fn and "return 0;" in echo_fn)
check("  and the row's own gate is untouched for every other screen",
      "var picks = auto ? echoPicks(entry) : [];" in echo_fn)
accent_fn = body("setAccent")
check("a flash gets no accent bar and no spark",
      "if (isFlash(entry)) {" in accent_fn
      and accent_fn.index("if (isFlash(entry))")
      < accent_fn.index("if (!auto || (echoes && !bar))"))
check("  and the accent's own rule is untouched for every other screen",
      "if (!auto || (echoes && !bar))" in accent_fn)
check("no CTA copy, no personal line: the entry is not personalised into one",
      "out.kicker" not in body("personalised"))

check("the dismiss is the entry's own beat, clamped where it always was",
      "Math.max(AUTO_MIN_MS, Math.min(want, ceiling))" in body("autoAdvanceMs")
      and "var ceiling = echoes ? ECHO_HOLD_MS : INTERSTITIAL_MS;"
      in body("autoAdvanceMs"))
check("  with no echo stagger, because a flash reports no thumbnails",
      "return 0;" in echo_fn)
check("a tap still skips it, through the screen's own listener",
      "if (midAuto) closeInterstitial();" in ENGINE
      and 'el.interstitial.addEventListener("click", tapInterstitial)'
      in ENGINE)

print("\n--- the grid comes off GRID_SIZE, not out of a second table ---")
fmt_fn = body("flashFormat")
check("the format is looked up in the step grid's own table",
      "GRID_SIZE[f]" in fmt_fn, fmt_fn)
check("  and a format the table has never heard of falls back to grid4",
      '? f : "grid4"' in fmt_fn)
check("  the table itself is the one the swipe steps read",
      "var GRID_SIZE = { grid4: 4, grid6: 6, grid12: 12 };" in ENGINE)
check("the row carries the swipe screen's own classes",
      '"mid-flash-grid cards is-" + flashFormat(entry)' in set_fn)
check("  which the stylesheet already lays out",
      ".cards.is-grid4 {" in CSS and ".cards.is-grid6 {" in CSS)
check("labels are drawn only when the frame carries one",
      "if (frame.label) {" in set_fn
      and 'elm("span", "mid-flash-label", frame.label)' in set_fn)

print("\n--- the countdown drains by transform, never by width ---")
check("engine.js writes the duration and nothing else",
      'fill.style.animationDuration = autoAdvanceMs(entry) + "ms";' in set_fn)
check("  it sets no width anywhere in the screen it builds",
      "style.width" not in set_fn and "offsetWidth" not in set_fn)
drain = re.search(r"@keyframes flash-drain\s*\{(.*?)\n\}", CSS, re.S)
check("the drain is a keyframe in the stylesheet", drain is not None)
check("  animating transform and nothing else",
      drain is not None
      and set(re.findall(r"(\w[\w-]*)\s*:", drain.group(1))) == {"transform"},
      str(drain and re.findall(r"(\w[\w-]*)\s*:", drain.group(1))))
check("  scaling from full to empty, anchored left",
      drain is not None and "scaleX(1)" in drain.group(1)
      and "scaleX(0)" in drain.group(1)
      and "transform-origin: left center;" in CSS)
fill_rule = re.search(r"\.mid\.is-flash \.mid-flash-fill \{(.*?)\n\}",
                      CSS, re.S)
check("  and the fill is a full-width bar that is scaled, not a sized one",
      fill_rule is not None and "width: 100%;" in fill_rule.group(1)
      and "animation: flash-drain" in fill_rule.group(1))

print("\n--- and the new paint cannot reach a screen that did not ask ---")
flash_rules = [r for r in RULES
               if "mid-flash" in r or "is-flash " in r or r == ".mid.is-flash"]
check("every new rule is scoped under .mid.is-flash",
      flash_rules and all(r.startswith(".mid.is-flash") for r in flash_rules),
      str([r for r in flash_rules if not r.startswith(".mid.is-flash")]))
check("  and no existing rule was widened to reach it",
      not [r for r in RULES
           if r.startswith(".mid.is-flash") and "," in r])
check("the auto-advance mode's keyframes are still exactly the five it had",
      sorted(re.findall(r"@keyframes (mid-[\w-]+)", CSS))
      == ["mid-appear", "mid-breathe", "mid-rise", "mid-spark", "mid-spin"],
      str(sorted(re.findall(r"@keyframes (mid-[\w-]+)", CSS))))
check("  and the new one is not named into that family",
      "@keyframes flash-drain" in CSS
      and "@keyframes mid-flash" not in CSS)

print("\n--- the frames are warm before the screen paints ---")
prep = body("prepareNext")
check("the step's own render warms the flash anchored on it",
      "var flash = flashAt(index);" in prep
      and "flash.flash.images.forEach(function (g) { preload(g.img); });"
      in prep, prep[:240])
check("  alongside the next pair, off the same index",
      prep.index("flashAt(index)") < prep.index("var st = stepAt(index);"))
check("  and renderStep is what calls it",
      "prepareNext();" in body("renderStep"))
at_fn = body("flashAt")
check("the lookup matches on after_step, like the open's own",
      "entry.after_step === completed" in at_fn and "isFlash(entry)" in at_fn)
check("  and it is a lookup only, with nothing of the open's bookkeeping",
      "midSeen" not in at_fn and "personalised" not in at_fn)

print("\n--- 2. the domain axes ---")
declared = re.search(r"var AXES = \{([^}]*)\}", ENGINE, re.S).group(1)
names = set(re.findall(r"(\w+):\s*\w+_AXIS", declared))
check("the AXES block still parses the way every suite reads it",
      len(names) == 10, str(sorted(names)))
for axis in ("mem", "spa", "chg", "foc"):
    check("  %s is declared" % axis, axis in names, str(sorted(names)))
check("  and the six that were there are still there",
      {"tone", "material", "season", "element", "energy", "axis"} <= names,
      str(sorted(names)))

VARS = {name.lower(): [t.strip().strip('"') for t in raw.split(",")]
        for name, raw in re.findall(r"var (\w+)_AXIS = \[([^\]]*)\]", ENGINE)}
check("every declared axis has a var of that shape",
      names <= set(VARS), str(sorted(names - set(VARS))))
for axis in ("mem", "spa", "chg", "foc"):
    check("  %s is a hit and a miss, in that order" % axis,
          VARS.get(axis) == ["%s_hit" % axis, "%s_miss" % axis],
          str(VARS.get(axis)))
check("ELEMENT is unchanged", VARS["element"] == ["fire", "earth", "air",
                                                  "water"],
      str(VARS["element"]))
check("ENERGY is unchanged", VARS["energy"] == ["sun", "moon"],
      str(VARS["energy"]))
check("TONE is unchanged", VARS["tone"] == ["warm", "cool", "dark", "bright"],
      str(VARS["tone"]))
check("MATERIAL is unchanged", VARS["material"] == ["wood", "stone", "metal"],
      str(VARS["material"]))
check("SEASON is unchanged",
      VARS["season"] == ["spring", "summer", "autumn", "winter"],
      str(VARS["season"]))
check("AXIS is unchanged",
      VARS["axis"] == ["drive", "anchor", "wave", "prism"], str(VARS["axis"]))
check("leader resolution is the one that was already there",
      "soleLeaderOf(AXES[axis])" in body("personalTag")
      and 'return prefixTag(axis + "_");' in body("personalTag")
      and 'rule.variants["default"]' in body("adaptivePairId"))

print("\n--- 3. elapsed_ms, on the swipe event and nowhere else ---")
extra_fn = body("swipeExtra")
check("the three fields that were always there are still the three",
      "pair: st.id" in extra_fn and "shown: picked.images.map" in extra_fn
      and "chosen: item.id" in extra_fn)
check("the reaction is written into the swipe event's extra",
      "extra.elapsed_ms = elapsedMs();" in extra_fn)
check("  behind the funnel's own key, so no shipping funnel sends it",
      "timingTracked()" in extra_fn
      and "cfg && cfg.track_timing" in body("timingTracked"))
check("  and behind a mark, so a step with no render sends nothing",
      "shownAtMs != null" in extra_fn)
check("the mark is taken when the cards are in the document",
      "shownAtMs = nowMs();" in body("renderStep"))
check("  from the monotonic clock where there is one",
      "window.performance && performance.now" in body("nowMs"))
elapsed_fn = body("elapsedMs")
check("it is a whole number of milliseconds",
      "Math.round(nowMs() - shownAtMs)" in elapsed_fn)
check("  clamped to 0..60000",
      "Math.max(0, Math.min(ms, ELAPSED_MAX_MS))" in elapsed_fn
      and "var ELAPSED_MAX_MS = 60000;" in ENGINE)

order_fn = body("orderPayload")
check("the checkout body does not carry it",
      "elapsed" not in order_fn, order_fn[:300])
check("  and still carries only what it always did",
      "tag_scores: scores" in order_fn and "choices: chosen.slice()"
      in order_fn)
check("it is not scored, so it cannot move a result",
      "elapsed" not in body("choose").split("track(")[0].replace(
          "swipeExtra", ""))
check("payments.py has never heard of it", "elapsed" not in PAYMENTS)
check("tracking.py has never heard of it either",
      "elapsed" not in open(os.path.join(ROOT, "tracking.py"),
                            encoding="utf-8").read())
check("  and a swipe payload is still the closed set of three",
      tracking.SWIPE_EXTRA_KEYS == frozenset(("pair", "shown", "chosen")),
      str(sorted(tracking.SWIPE_EXTRA_KEYS)))

print("\n--- and only the funnel that asked for them can reach them ---")
# /brain is that funnel and arrived a phase after this file did. What is
# checked here is unchanged in substance: these three are opt-in, and every
# funnel that did not opt in is untouched by their existing. The list is
# spelled out rather than left as "none", so a fourth funnel growing a flash
# by accident still fails.
OWNER = "brain.json"
for name, cfg in CONFIGS.items():
    if name == OWNER:
        continue
    entries = cfg.get("interstitials") or []
    check("  %-22s names no flash" % name,
          not [e for e in entries if e.get("template") == "flash"
               or e.get("flash")])
check("  and the funnel that does is the one built on it",
      bool([e for e in (CONFIGS[OWNER].get("interstitials") or [])
            if e.get("template") == "flash"]))
check("no shipping funnel asks for reaction times",
      not [n for n, c in CONFIGS.items() if c.get("track_timing")],
      str([n for n, c in CONFIGS.items() if c.get("track_timing")]))
DOMAIN = {"%s_%s" % (a, s) for a in ("mem", "spa", "chg", "foc")
          for s in ("hit", "miss")}
carried = set()
for name, cfg in CONFIGS.items():
    if name == OWNER:
        continue
    for st in (cfg.get("swipe") or {}).get("steps", []):
        for pairing in (st.get("pairs") or ([{"images": st["images"]}]
                                            if st.get("images") else [])):
            for img in pairing.get("images") or []:
                carried |= set(img.get("tags") or []) & DOMAIN
check("no other funnel's cards carry a domain tag", not carried,
      str(sorted(carried)))
check("no other funnel keys an interstitial or a step on a domain axis",
      not [n for n, c in CONFIGS.items() if n != OWNER
           and re.search(r'"axis":\s*"(?:mem|spa|chg|foc)"', json.dumps(c))],
      str([n for n, c in CONFIGS.items() if n != OWNER
           and re.search(r'"axis":\s*"(?:mem|spa|chg|foc)"',
                         json.dumps(c))]))
check("the funnels directory and its static copy still agree",
      sorted(os.listdir(FUNNELS))
      == sorted(os.listdir(os.path.join(ROOT, "static/funnels"))))

print("\n%d checks, %d failed" % (checks[0], len(fails)))
for f in fails:
    print("  FAIL " + f)
sys.exit(1 if fails else 0)
