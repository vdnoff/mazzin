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

print("\n--- the countdown: one component, drained by transform ---")
timer_fn = body("makeTimer")
check("there is one timer, and both screens draw it",
      "function makeTimer(" in ENGINE
      and 'elm("div", "mz-timer")' in timer_fn
      and ENGINE.count("var timer = makeTimer();") == 2,
      str(ENGINE.count("var timer = makeTimer();")))
check("  a rail and a numeral, and nothing else",
      'elm("span", "mz-timer-track")' in timer_fn
      and 'elm("i", "mz-timer-fill")' in timer_fn
      and 'elm("span", "mz-timer-count")' in timer_fn)
check("the rail is driven by a transition on transform",
      'fill.style.transition = "transform " + ms + "ms linear";' in timer_fn
      and 'fill.style.transform = "scaleX(0)";' in timer_fn)
check("  primed at full, with a reflow between the two writes",
      'fill.style.transform = "scaleX(1)";' in timer_fn
      and timer_fn.index('scaleX(1)') < timer_fn.index("void fill.offsetWidth")
      < timer_fn.index('scaleX(0)'))
check("  and it never touches width",
      "style.width" not in timer_fn)
check("the numeral is whole seconds, read off a deadline",
      "Math.ceil(left / 1000)" in timer_fn
      and "ends - nowMs()" in timer_fn)
check("  repainted on its own tick rather than counted down",
      "setInterval(paint, TIMER_TICK_MS)" in timer_fn)
check("the last stretch is a class, so the colour stays in the stylesheet",
      'node.classList.toggle("is-warn", left <= TIMER_WARN_MS)' in timer_fn
      and "var TIMER_WARN_MS = 1500;" in ENGINE)
check("the timer can be stopped, and the tap is what stops it",
      "function stop()" in timer_fn and "clearInterval(tick)" in timer_fn)

fill_rule = re.search(r"\.mz-timer-fill \{(.*?)\n\}", CSS, re.S)
check("the fill is a full-width rail that is scaled, not a sized one",
      fill_rule is not None and "width: 100%;" in fill_rule.group(1)
      and "transform: scaleX(1);" in fill_rule.group(1)
      and "transform-origin: left center;" in fill_rule.group(1))
check("  painted as a gradient with a glow under it",
      fill_rule is not None and "linear-gradient(" in fill_rule.group(1)
      and "box-shadow:" in fill_rule.group(1))
check("  and nothing in the stylesheet animates its width",
      not re.search(r"\.mz-timer[^{]*\{[^}]*(?:animation|transition)"
                    r"[^;}]*width", CSS))
check("the warn state repaints the rail and the numeral together",
      ".mz-timer.is-warn .mz-timer-fill {" in CSS
      and ".mz-timer.is-warn .mz-timer-count" in CSS)
check("the rail is a rounded track, and the numeral sits beside it",
      re.search(r"\.mz-timer-track \{[^}]*border-radius: 999px;", CSS, re.S)
      is not None
      and re.search(r"\.mz-timer-count \{[^}]*text-align: right;", CSS, re.S)
      is not None)
check("it is drawn above the frames on a flash",
      re.search(r"\.mid\.is-flash \.mz-timer \{(.*?)\n\}", CSS, re.S)
      is not None
      and set_fn.index("makeTimer()") < set_fn.index("mid-flash-grid cards"))
check("  and above the cards on a step",
      ".step.is-timed .mz-timer {" in CSS
      and "el.stage.insertBefore(timer.node, el.cards);" in body("startStepTimer"))

print("\n--- 2. the count-in, and the flash's own ceiling ---")
prep_fn = body("preparePlan")
check("the phase is gated on the entry naming a count",
      "entry && entry.prepare" in prep_fn
      and 'typeof count !== "number"' in prep_fn
      and "return null;" in prep_fn)
run_fn = body("runPrepare")
check("it puts its own line up and takes the entry's down",
      "el.midLine.textContent = plan.line;" in run_fn
      and 'el.midLine.textContent = fillTokens(entry.line || "");' in run_fn)
check("  marking the screen, so the stylesheet holds the frames back",
      'parts.host.classList.add("is-prepare")' in run_fn
      and ".mid.is-flash.is-prepare .mid-flash-grid { display: none; }"
      in CSS.replace("\n", " ").replace("  ", " ")
      or ".mid.is-flash.is-prepare .mz-timer,\n"
      ".mid.is-flash.is-prepare .mid-flash-grid { display: none; }" in CSS)
check("  one numeral per beat, each restarted with a reflow",
      "PREPARE_TICK_MS" in run_fn
      and "void node.offsetWidth;" in body("countIn")
      and 'node.classList.add("is-in")' in body("countIn"))
check("  and the numeral's arrival is a keyframe of its own family",
      "@keyframes mz-count-in" in CSS)
check("its time is spent on top of the entry's beat, not out of it",
      "showFlashFrames(entry, parts, auto)" in body("startFlash")
      and "parts.timer.start(hold)" in body("showFlashFrames"))
check("a tap during the count goes to the frames, not past them",
      "midPrepareSkip = finish;" in run_fn
      and "if (midPrepareSkip) midPrepareSkip();" in body("tapInterstitial"))
auto_fn = body("autoAdvanceMs")
check("a flash gets its own ceiling",
      'if (entry.template === "flash") ceiling = FLASH_MAX_MS;' in auto_fn
      and "var FLASH_MAX_MS = 8000;" in ENGINE)
check("  and every other template keeps the one it always had",
      "var ceiling = echoes ? ECHO_HOLD_MS : INTERSTITIAL_MS;" in auto_fn
      and "var INTERSTITIAL_MS = 4000;" in ENGINE
      and "var ECHO_HOLD_MS = 4500;" in ENGINE
      and "var AUTO_MIN_MS = 600;" in ENGINE)
check("  the floor is still the floor, at both ends",
      "Math.max(AUTO_MIN_MS, Math.min(want, ceiling))" in auto_fn)

print("\n--- 3. the reveal: declared, never rolled ---")
rev_fn = body("revealPlan")
check("the phase is gated on the entry naming a reveal",
      "entry && entry.reveal" in rev_fn
      and 'typeof slot !== "number"' in rev_fn
      and "if (!rule.closed_img) return null;" in rev_fn)
check("  and on the slot being one the grid actually has",
      "slot >= frames.length" in rev_fn)
check("the swaps come out of the config, in the order it wrote them",
      "(rule.swaps || []).forEach" in rev_fn and "swaps.push(" in rev_fn)
check("  and nothing on this path rolls a die",
      "Math.random" not in rev_fn
      and "Math.random" not in body("runSwaps")
      and "Math.random" not in body("swapCells")
      and "Math.random" not in body("runReveal"))
check("  a pair naming a slot that is not there is dropped, not clamped",
      "a >= frames.length || b >= frames.length) return;" in rev_fn)
show_fn = body("showFlashFrames")
check("the timer runs the open beat, and the reveal is what follows it",
      "var hold = plan ? plan.open_ms : auto;" in show_fn
      and "midReveal = true;" in show_fn)
lid_fn = body("closeLid")
check("the lid is a crossfade over the open card",
      'lid.className = "mid-flash-lid";' in lid_fn
      and "lid.src = plan.closed_img;" in lid_fn
      and 'lid.style.opacity = "1";' in lid_fn)
check("  with the squash driven from the same close_ms",
      'cell.style.animationDuration = plan.close_ms + "ms";' in lid_fn
      and 'cell.classList.add("is-closing")' in lid_fn
      and "@keyframes mz-lid" in CSS)
swap_fn = body("swapCells")
check("cards trade places by transform, both of them",
      'one.style.transform = "translate(' in swap_fn
      and 'two.style.transform = "translate(' in swap_fn
      and "style.width" not in swap_fn)
check("  measured off where they actually are",
      "two.offsetLeft - one.offsetLeft" in swap_fn
      and "two.offsetTop - one.offsetTop" in swap_fn)
check("  and the list is reordered once the move is over",
      "grid.insertBefore(one, two);" in swap_fn
      and "grid.insertBefore(two, mark);" in swap_fn
      and 'cell.style.transform = "none";' in swap_fn)
check("they run one at a time, in the order declared",
      "runSwaps(grid, plan, i + 1, done)" in body("runSwaps"))
check("a tap during the reveal is ignored",
      "if (midReveal) return;" in body("tapInterstitial"))
check("  and the ordinary skip is still there for every other screen",
      "if (midAuto) closeInterstitial();" in ENGINE)
check("closing takes the whole sequence down with it",
      "clearFlashSteps();" in body("closeInterstitial")
      and "midReveal = false;" in body("closeInterstitial")
      and "if (flashParts) flashParts.timer.stop();"
      in body("closeInterstitial"))
check("the lid the reveal closes with is warmed a step early",
      "if (flash.reveal) preload(flash.reveal.closed_img);" in prep)

print("\n--- 4. a step with a clock on it ---")
ms_fn = body("stepTimerMs")
check("the clock is gated on the step naming how long",
      "st && st.timer_ms" in ms_fn and 'typeof ms !== "number"' in ms_fn
      and "return 0;" in ms_fn)
check("  and on it naming what to press when nobody does",
      "if (!timeoutPick(st)) return 0;" in ms_fn)
check("  clamped to one second and fifteen",
      "Math.max(STEP_TIMER_MIN_MS, Math.min(ms, STEP_TIMER_MAX_MS))" in ms_fn
      and "var STEP_TIMER_MIN_MS = 1000;" in ENGINE
      and "var STEP_TIMER_MAX_MS = 15000;" in ENGINE)
pick_fn = body("timeoutPick")
check("the card it presses is one actually on screen",
      "st && st.timeout_pick" in pick_fn
      and "pair[i].id === want" in pick_fn)
check("it starts with the cards in the document",
      "startStepTimer(st);" in body("renderStep")
      and body("renderStep").index("shownAtMs = nowMs();")
      < body("renderStep").index("startStepTimer(st);"))
check("  and a tap clears it",
      "stopStepTimer();" in body("choose"))
out_fn = body("timeOut")
check("running out is a tap on the card the config named",
      "choose(item, card);" in out_fn and "timedOut = true;" in out_fn)
check("  and never a second one on a step already answered",
      "stepTimer.step !== step || picking" in out_fn)
check("the screen is marked while the clock is on it, and unmarked after",
      'classList.add("step", "is-timed")' in body("startStepTimer")
      and 'classList.remove("step", "is-timed")' in body("stopStepTimer"))

print("\n--- timed_out, on the swipe event and nowhere else ---")
extra_fn = body("swipeExtra")
check("it is written into the swipe event's extra",
      "extra.timed_out = true;" in extra_fn)
check("  beside the three that were always there, and the reaction",
      "pair: st.id" in extra_fn and "chosen: item.id" in extra_fn
      and "extra.elapsed_ms = elapsedMs();" in extra_fn)
check("  behind the same key the reaction is, because /api/track is closed",
      "if (timingTracked() && timedOut) extra.timed_out = true;" in extra_fn
      and "cfg && cfg.track_timing" in body("timingTracked"))
check("  and reset on every step, so it cannot carry over",
      "timedOut = false;" in body("renderStep"))
check("the checkout body does not carry it",
      "timed_out" not in body("orderPayload")
      and "timedOut" not in body("orderPayload"))
check("payments.py and tracking.py have never heard of it",
      "timed_out" not in PAYMENTS
      and "timed_out" not in open(os.path.join(ROOT, "tracking.py"),
                                  encoding="utf-8").read())
check("  and a swipe payload is still the closed set of three",
      tracking.SWIPE_EXTRA_KEYS == frozenset(("pair", "shown", "chosen")),
      str(sorted(tracking.SWIPE_EXTRA_KEYS)))

print("\n--- 5. a step that names its own cards ---")
label_fn = body("labelMode")
check("the step is asked before the funnel",
      "(stepAt(step) || {}).label_mode" in label_fn
      and label_fn.index("label_mode")
      < label_fn.index("cfg.swipe.label_mode"))
check("  and a step that names nothing takes the funnel's own setting",
      "cfg && cfg.swipe && cfg.swipe.label_mode" in label_fn)
check("badge is still read the one way it always was",
      ENGINE.count('labelMode() === "badge"') == 1)
check("on_tap draws the badge after the tap, on the card that was chosen",
      'labels === "on_tap"' in body("choose")
      and "revealLabel(item, card);" in body("choose")
      and 'elm("span", "card-name is-late", item.label)' in body("revealLabel"))
check("  and the chip that would say the same word stands down",
      re.search(r'if \(labels === "on_tap"\) \{\s*revealLabel\(item, card\);'
                r'\s*\} else \{', body("choose"), re.S) is not None)
check("  the mode is read before the counter moves",
      body("choose").index("var labels = labelMode();")
      < body("choose").index("step += 1;"))
check("only that mode delays the advance, and only by the badge's own beat",
      'var late = labels === "on_tap" ? LABEL_FLASH_MS : 0;' in body("choose")
      and "(reduced ? HOLD_REDUCED_MS : HOLD_MS) + late" in body("choose")
      and "var LABEL_FLASH_MS = 500;" in ENGINE)
check("  the badge is the badge mode's own node, arriving late",
      ".cards .card-name.is-late {" in CSS
      and "@keyframes mz-label-in" in CSS)
check("  and it restates the pill's own centring, which the animation replaces",
      re.search(r"@keyframes mz-label-in\s*\{(.*?)\n\}", CSS, re.S)
      is not None
      and re.search(r"@keyframes mz-label-in\s*\{(.*?)\n\}",
                    CSS, re.S).group(1).count("translateX(-50%)") == 2)

print("\n--- and the new paint cannot reach a screen that did not ask ---")
NEW_SCOPES = (".mz-timer", ".mid.is-flash", ".step.is-timed",
              ".cards .card-name.is-late")
new_rules = [r for r in RULES
             if "mz-" in r or "mid-flash" in r or ".mid.is-flash" in r
             or "is-timed" in r or "is-late" in r]
check("every new rule is scoped to a class only a new config can produce",
      new_rules and all(r.startswith(NEW_SCOPES) for r in new_rules),
      str([r for r in new_rules if not r.startswith(NEW_SCOPES)]))
check("  and none of them was widened with a second selector",
      not [r for r in new_rules if "," in r and not r.startswith(NEW_SCOPES)])
check("the auto-advance mode's keyframes are still exactly the five it had",
      sorted(re.findall(r"@keyframes (mid-[\w-]+)", CSS))
      == ["mid-appear", "mid-breathe", "mid-rise", "mid-spark", "mid-spin"],
      str(sorted(re.findall(r"@keyframes (mid-[\w-]+)", CSS))))
check("  and every keyframe this branch added is in its own family",
      sorted(re.findall(r"@keyframes (mz-[\w-]+)", CSS))
      == ["mz-count-in", "mz-label-in", "mz-lid"],
      str(sorted(re.findall(r"@keyframes (mz-[\w-]+)", CSS))))

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
# Read structurally rather than off the JSON text: `reveal` is also what a
# report section calls its lock state, and a substring scan would report every
# funnel on the platform for a key none of them carries here.
loud = []
for name, cfg in CONFIGS.items():
    for entry in cfg.get("interstitials") or []:
        for key in ("prepare", "reveal"):
            if entry.get(key):
                loud.append("%s:interstitial.%s" % (name, key))
    for st in (cfg.get("swipe") or {}).get("steps", []):
        for key in ("timer_ms", "timeout_pick", "label_mode"):
            if st.get(key):
                loud.append("%s:%s.%s" % (name, st.get("id"), key))
check("no funnel names a count-in, a reveal, a clock or its own labels yet",
      not loud, str(loud))
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
