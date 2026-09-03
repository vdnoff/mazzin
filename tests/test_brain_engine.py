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
# v8 adds the second half of the condition: a walk that shows no words at all
# does not show one here either. See the check on it further down.
check("labels are drawn only when the frame carries one",
      'if (frame.label && labels !== "check") {' in set_fn
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
      "choose(item, null);" in out_fn and "timedOut = true;" in out_fn)
check("  and on no card at all, so nothing is shown as chosen",
      "cardFor" not in ENGINE
      and 'var late = (card && labels === "on_tap") ? LABEL_FLASH_MS : 0;'
      in body("choose"))
check("  the ring, the dim and the chip are all behind that card",
      re.search(r"if \(card\) \{(.*?)\n    \}", body("choose"), re.S)
      is not None
      and all(bit in re.search(r"if \(card\) \{(.*?)\n    \}",
                               body("choose"), re.S).group(1)
              for bit in ('card.classList.add("is-chosen")',
                          'el.cards.classList.add("is-picking")',
                          "revealLabel(item, card);",
                          "showReaction(item.label")))
check("  and the ids of the rounds it answered are kept beside the choices",
      "timedOutSteps.push((stepAt(step) || {}).id" in out_fn
      and "chosen: chosen.slice()," in ENGINE
      and "timed_out: timedOutSteps.slice()," in ENGINE)
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
# v7. It reaches the purchase now, from the same state the free page reads.
# The server cannot derive it: a step that ran out records the same answer as
# a step somebody tapped, because the card the clock picks is one they could
# have picked themselves.
order_fn = body("orderPayload")
check("the checkout body carries the ids, from that same state",
      "if (timedOutSteps.length) payload.timed_out = timedOutSteps.slice();"
      in order_fn)
check("  and only when there are some, so every other funnel is unchanged",
      "if (timedOutSteps.length)" in order_fn)
check("payments.py validates it rather than believing it",
      "def _clean_timed_out(cfg, raw):" in PAYMENTS)
check("  a list, of ids this funnel has, no two the same, no longer than the "
      "walk",
      "if not isinstance(raw, list):" in PAYMENTS
      and "if step_id not in known" in PAYMENTS.replace(
          "if not isinstance(step_id, str) or step_id not in known",
          "if step_id not in known")
      and "if len(set(raw)) != len(raw):" in PAYMENTS
      and "if limit and len(raw) > limit:" in PAYMENTS)
check("  and refuses rather than dropping, unlike the two beside it",
      PAYMENTS.count("raise OrderError(400)")
      >= 5 and "return None" in PAYMENTS)
check("it rides Stripe's metadata and is re-checked coming back",
      'data["timed_out"] = timed_out' in PAYMENTS
      and "def _read_timed_out(cfg, packed):" in PAYMENTS
      and "except OrderError:" in PAYMENTS)
check("  and lands on the parameter reports.py already had",
      "timed_out=timed_out," in PAYMENTS
      and "timed_out=None):" in PAYMENTS)
check("  and tracking.py knows it only as one a swipe MAY carry",
      "timed_out" in tracking.SWIPE_EXTRA_OPTIONAL,
      str(sorted(tracking.SWIPE_EXTRA_OPTIONAL)))
check("  so a swipe payload is still required to be the closed three",
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
                r'\s*\} else if', body("choose"), re.S) is not None)
check("  the mode is read before the counter moves",
      body("choose").index("var labels = labelMode();")
      < body("choose").index("step += 1;"))
check("only that mode delays the advance, and only by the badge's own beat",
      'var late = (card && labels === "on_tap") ? LABEL_FLASH_MS : 0;'
      in body("choose")
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
# v7 adds a fifth: the memory game's own blue, which repaints the clock and
# the count-in. It is scoped to the theme class engine.js sets from `theme`
# in the config, so it cannot reach a funnel that names another one.
NEW_SCOPES = (".mz-timer", ".mid.is-flash", ".step.is-timed",
              ".cards .card-name.is-late", "body.theme-brain ")
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
check("  and every keyframe these branches added is in their own family",
      sorted(re.findall(r"@keyframes (mz-[\w-]+)", CSS))
      == ["mz-check-pop", "mz-count-in", "mz-label-in", "mz-lid",
          "mz-pill-pulse", "mz-timeup-in"],
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
check("tracking.py knows it only as one a swipe MAY carry",
      "elapsed_ms" in tracking.SWIPE_EXTRA_OPTIONAL,
      str(sorted(tracking.SWIPE_EXTRA_OPTIONAL)))
check("  so a swipe payload is still required to be the closed three",
      tracking.SWIPE_EXTRA_KEYS == frozenset(("pair", "shown", "chosen")),
      str(sorted(tracking.SWIPE_EXTRA_KEYS)))

OWNER = "brain.json"

print("\n--- 6. a step that says which round it is ---")
kick_fn = body("setStepKicker")
check("the line is gated on the step naming one",
      'var text = (st && st.kicker) || "";' in kick_fn
      and "if (!text) {" in kick_fn and "node.hidden = true;" in kick_fn)
check("  and no node is built for a walk that names none",
      "if (!node) {" in kick_fn and 'elm("p", "step-kicker")' in kick_fn
      and "el.stepKicker = node;" in kick_fn)
check("it goes above the question, inside the stage",
      "el.stage.insertBefore(node, el.caption);" in kick_fn)
check("  and is refilled on every step rather than left standing",
      "node.textContent = text;" in kick_fn
      and "setStepKicker(st);" in body("renderStep"))
check("  before the caption, so the two are drawn in the order they read",
      body("renderStep").index("setStepKicker(st);")
      < body("renderStep").index("setCaption("))
check("the caption itself is untouched",
      "el.caption.textContent = text;" in body("setCaption")
      and 'el.caption.classList.add("is-enter")' in body("setCaption"))
kick_rule = re.search(r"\.step-kicker \{(.*?)\n\}", CSS, re.S)
check("the stylesheet sets it as the interstitial's kicker is set",
      kick_rule is not None
      and "text-transform: uppercase;" in kick_rule.group(1)
      and "letter-spacing: 0.08em;" in kick_rule.group(1)
      and "color: var(--accent);" in kick_rule.group(1))

print("\n--- 7. the clock running out, said out loud ---")
check("the beat has a length of its own",
      "var TIMEUP_MS = 900;" in ENGINE)
up_fn = body("showTimeUp")
check("the cover is built only where there are cards to cover",
      "if (!el.cards) return null;" in up_fn
      and 'elm("div", "step-timeup")' in up_fn)
check("  drawn inside the card row, which is the positioned box",
      "el.cards.appendChild(over);" in up_fn
      and re.search(r"\.step-timeup \{[^}]*position: absolute;", CSS, re.S)
      is not None
      and re.search(r"^\.cards \{[^}]*position: relative;", CSS, re.S | re.M)
      is not None)
check("  a cross of two bars rather than a glyph",
      up_fn.count('mark.appendChild(elm("i"));') == 2
      and ".step-timeup-mark i:first-child { transform: rotate(45deg); }"
      in CSS
      and ".step-timeup-mark i:last-child { transform: rotate(-45deg); }"
      in CSS)
check("  and one line, off the funnel's own copy",
      'words("swipe.timeup_line", "Time\\u2019s up")' in up_fn)
out_fn = body("timeOut")
check("it is reached only from a step that carried a clock",
      "if (!stepTimer || stepTimer.step !== step || picking) return;" in out_fn
      and "st && st.timer_ms" in body("stepTimerMs"))
check("  the clock is stopped before the cover goes up",
      out_fn.index("stopStepTimer();") < out_fn.index("showTimeUp()"))
check("a tap while the cover is up does nothing",
      "picking = true;" in out_fn
      and out_fn.index("picking = true;") < out_fn.index("showTimeUp()")
      and "if (picking || !pair.length) return;" in body("choose"))
check("  and the cover takes the pointer as well",
      re.search(r"\.step-timeup \{[^}]*z-index: 9;", CSS, re.S) is not None)
check("the beat lifts, and then the answer goes in unchanged",
      "over.parentNode.removeChild(over);" in out_fn
      and "picking = false;" in out_fn
      and out_fn.index("picking = false;")
      < out_fn.index("choose(item, null);")
      and "}, over ? TIMEUP_MS : 0);" in out_fn)
check("  with the same word recorded as before",
      "timedOut = true;" in out_fn
      and "if (timingTracked() && timedOut) extra.timed_out = true;"
      in body("swipeExtra"))
# The one selector on this list that is not a class of its own is the rule
# hiding the question behind an intro card, and it cannot be: what it hides
# is the shell's own caption and card row. It is gated instead — nothing in
# it matches unless engine.js has put `is-intro` on the screen, which it does
# only for a funnel carrying an `intro` block.
#
# v7 adds three more of the same kind: the layer the one pill travels in, the
# memorise screen's kicker while it is hosting that pill, and the memory
# game's own blue — the last of which is under the theme class and so cannot
# reach any other funnel.
SCOPES = (".step-timeup", ".step-kicker", ".intro", "#screen-swipe.is-intro",
          ".pill-layer", ".pill-float", ".mid-kicker.is-pill-host",
          "body.theme-brain ")
own_rules = [r for r in RULES
             if "step-timeup" in r or "step-kicker" in r
             or ".intro" in r or "is-intro" in r
             or "pill-layer" in r or "pill-float" in r or "is-pill-host" in r]
check("every rule these additions bring is scoped to its own class",
      own_rules and all(r.startswith(SCOPES) for r in own_rules),
      str([r for r in own_rules if not r.startswith(SCOPES)]))
check("  and the one that reaches the shell is gated on the intro's class",
      all("#screen-swipe.is-intro" in part
          for r in own_rules if r.startswith("#screen-swipe")
          for part in r.split(",")),
      str([r for r in own_rules if r.startswith("#screen-swipe")]))
check("no funnel but the memory game names either key",
      not [n for n, cfg in CONFIGS.items() if n != OWNER
           and ([s for s in (cfg.get("swipe") or {}).get("steps", [])
                 if s.get("kicker")]
                or (cfg.get("swipe") or {}).get("timeup_line"))],
      str([n for n, cfg in CONFIGS.items() if n != OWNER
           and ([s for s in (cfg.get("swipe") or {}).get("steps", [])
                 if s.get("kicker")]
                or (cfg.get("swipe") or {}).get("timeup_line"))]))
check("  and the one that does names both",
      all(s.get("kicker") for s in CONFIGS[OWNER]["swipe"]["steps"])
      and CONFIGS[OWNER]["swipe"].get("timeup_line"))

print("\n--- 8. the card before the first question ---")
intro_fn = body("hasIntro")
check("the screen is gated on the funnel naming a button",
      "cfg && cfg.intro" in intro_fn and "block.cta" in intro_fn,
      intro_fn.strip()[:90])
show_fn = body("showIntro")
check("  and no node is built for a funnel that names none",
      'elm("section", "intro")' in show_fn
      and "if (hasIntro()) {" in body("startQuiz"))
check("it is built into the stage rather than as a screen of its own",
      "el.stage.insertBefore(card, el.stage.firstChild);" in show_fn
      and 'el.swipe.classList.add("is-intro");' in show_fn)
check("  and the stylesheet holds the question back while it is up",
      "#screen-swipe.is-intro .caption," in CSS
      and "#screen-swipe.is-intro .cards," in CSS
      and "#screen-swipe.is-intro .tap-hint," in CSS)
check("  with the money line off for good on a funnel that has one",
      "if (!hasIntro()) {" in body("startQuiz")
      and body("startQuiz").index("if (!hasIntro()) {")
      < body("startQuiz").index("setMoneyLine("))
check("every part of the card is drawn from the block",
      all(("block." + key) in show_fn
          for key in ("kicker", "headline", "sub", "chips", "cta", "foot")))
check("  the kicker carries the same two marks the minimal page frames with",
      "kicker.appendChild(introMark());" in show_fn
      and 'elm("span", "intro-mark"' in body("introMark"))
check("arriving is still arriving, and starting is a second thing",
      'track("funnel_start")' in body("startQuiz")
      and 'track("intro_start")' in show_fn)
check("  fired by the button and by nothing else",
      ENGINE.count('track("intro_start")') == 1
      and show_fn.index('button.addEventListener("click"')
      < show_fn.index('track("intro_start")'))
check("  and once, whatever a phone does with a double tap",
      "if (fired) return;" in show_fn and "fired = true;" in show_fn)
check("the event is one the server will accept",
      "intro_start" in tracking.ALLOWED_EVENTS)
check("  and carries no payload, which is what the server allows it",
      not re.search(r'track\("intro_start",', ENGINE))
check("the first pair warms while the card is being read",
      "preloadPair(pair, function () {});" in body("startQuiz")
      and "showIntro(renderStep);" in body("startQuiz"))

print("\n--- 9. the round, as a pill ---")
pill_fn = body("setStepKicker")
check("the pill is gated on the funnel asking for one",
      "cfg.swipe.round_pill" in body("roundPill")
      and 'node.classList.toggle("is-pill", roundPill());' in pill_fn)
check("  and a funnel that does not keeps the line it had",
      "if (!roundPill()) {" in pill_fn
      and "node.textContent = text;" in pill_fn)
# v7. The split and the two spans moved out of `setStepKicker` and into a
# pair of their own, because the memorise screen draws the same pill from the
# same parse — one component, read the same way in both places.
parts_fn = body("pillParts")
fill_fn = body("fillPill")
check("it splits on the LAST separator, not the first",
      'var cut = text.lastIndexOf("·");' in parts_fn,
      parts_fn[:120])
check("  the label in one span and the counter in another",
      'elm("span", "step-kicker-text"' in fill_fn
      and 'elm("span", "step-kicker-count"' in fill_fn)
# v9. The counter is what follows the last separator AND looks like one. It
# used to be whatever followed the last separator, which was right for every
# kicker a step carries and wrong for every kicker a screen between rounds
# carries — it would have put the word FOCUS in the badge.
check("  and the badge is only ever a counter",
      'var PILL_COUNT_RE = /^\\d+\\/\\d+$/;' in ENGINE
      and "if (!PILL_COUNT_RE.test(tail)) {" in parts_fn
      and "return { label: text.trim(), count: \"\" };" in parts_fn)
check("  so a kicker naming a round and no more is all label",
      "if (parts.count) {" in fill_fn
      and 'return { label: text.slice(0, cut).trim(), count: tail };'
      in parts_fn)
check("  and the step screen still fills through it",
      "fillPill(node, text);" in pill_fn)
check("the counter is a solid badge inside the pill",
      ".step-kicker.is-pill {" in CSS
      and re.search(r"\.step-kicker-count \{[^}]*background: var\(--accent\);",
                    CSS, re.S) is not None)
check("  and the pill is the accent, on the accent's own pale ground",
      re.search(r"\.step-kicker\.is-pill \{[^}]*border: 1px solid "
                r"var\(--accent\);", CSS, re.S) is not None
      and re.search(r"\.step-kicker\.is-pill \{[^}]*background: "
                    r"var\(--accent-soft\);", CSS, re.S) is not None)
check("nothing takes it down between the tap and the next step",
      "step-kicker" not in body("choose")
      and "el.stepKicker" not in body("choose"))

print("\n--- and neither key reaches a funnel that did not ask ---")
check("no funnel but the memory game carries an intro card",
      [n for n, cfg in CONFIGS.items() if cfg.get("intro")] == [OWNER],
      str([n for n, cfg in CONFIGS.items() if cfg.get("intro")]))
check("  or asks for the round pill",
      [n for n, cfg in CONFIGS.items()
       if (cfg.get("swipe") or {}).get("round_pill")] == [OWNER],
      str([n for n, cfg in CONFIGS.items()
           if (cfg.get("swipe") or {}).get("round_pill")]))
check("  and the one that does carries both",
      CONFIGS[OWNER].get("intro")
      and CONFIGS[OWNER]["swipe"].get("round_pill") is True)

print("\n--- and only the funnel that asked for them can reach them ---")
# /brain is that funnel and arrived a phase after this file did. What is
# checked here is unchanged in substance: these three are opt-in, and every
# funnel that did not opt in is untouched by their existing. The list is
# spelled out rather than left as "none", so a fourth funnel growing a flash
# by accident still fails.
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
#
# /brain names all five now, which is what it was built for. The claim that
# still matters is the one either side of it: no other funnel does, so none of
# them draws a count-in, a clock or a card it did not draw before.
loud = []
for name, cfg in CONFIGS.items():
    if name == OWNER:
        continue
    for entry in cfg.get("interstitials") or []:
        for key in ("prepare", "reveal"):
            if entry.get(key):
                loud.append("%s:interstitial.%s" % (name, key))
    for st in (cfg.get("swipe") or {}).get("steps", []):
        for key in ("timer_ms", "timeout_pick", "label_mode"):
            if st.get(key):
                loud.append("%s:%s.%s" % (name, st.get("id"), key))
check("no other funnel names a count-in, a reveal, a clock or its own labels",
      not loud, str(loud))
own = CONFIGS[OWNER]
check("  and the funnel that does names every one of them",
      [e for e in own["interstitials"] if e.get("prepare")]
      and [e for e in own["interstitials"] if e.get("reveal")]
      and [s for s in own["swipe"]["steps"] if s.get("timer_ms")]
      # v8: the labels are one answer for the whole walk now — no words on any
      # card — so it is named once on the funnel rather than eleven times on
      # the steps.
      and own["swipe"].get("label_mode") == "check"
      and not [s for s in own["swipe"]["steps"] if s.get("label_mode")])
check("no funnel but the memory game asks for reaction times",
      [n for n, c in CONFIGS.items() if c.get("track_timing")] == [OWNER],
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

print("\n--- v7: one pill, and it follows the reader ---")
# The rule the whole thing turns on: the pill the reader sees is ONE node for
# the length of the walk. Every screen that names a round draws its own copy
# and hides it, and that copy is only ever a box to move to — which is why it
# is hidden with opacity and not with `display`, and why the travelling node
# lives outside both screens rather than being moved between them.
# v10. `movePill` is a request now, not the act: everything that wants the
# pill moved goes through one rAF-debounced aimer, and `placePill` is the one
# thing that ever measures or writes.
move_fn = body("placePill")
aim_fn = body("aimPill")
node_fn = body("pillNode")
check("the travelling pill is built once, outside every screen",
      "if (el.pill) return el.pill;" in node_fn
      and "document.body.appendChild(layer);" in node_fn)
check("  as two nodes, because a glide and a beat are two transforms",
      'elm("div", "pill-float")' in node_fn
      and 'elm("p", "step-kicker is-pill")' in node_fn
      and "carrier.appendChild(node);" in node_fn)
check("  and read out by nobody: the slot under it is the one in the order",
      'layer.setAttribute("aria-hidden", "true");' in node_fn)
check("nothing here can reach a funnel that did not ask for a pill",
      "if (!roundPill() || !pillText) return;" in move_fn
      and "if (!roundPill()) return;" in aim_fn)
check("every request for a move is one measurement on one frame",
      "if (pillAim || !window.requestAnimationFrame) {" in aim_fn
      and "pillAim = requestAnimationFrame(function () {" in aim_fn
      and "placePill();" in aim_fn
      and "aimPill(instant);" in body("movePill"))
check("  and nothing else in the file measures or writes the transform",
      ENGINE.count("el.pillFloat.style.transform =") == 1)
check("it moves to whichever screen is up, and only to a real box",
      '".screen.is-active .step-kicker.is-slot"' in body("pillSlot")
      and "node && node.offsetWidth ? node : null" in body("pillSlot"))
check("  by transform alone, so nothing on the page moves with it",
      'el.pillFloat.style.transform = "translate("' in move_fn
      and "style.width" not in move_fn and "style.left" not in move_fn)
check("  and it comes to rest on whole pixels",
      "var x = Math.round(box.left - base.left);" in move_fn
      and "var y = Math.round(box.top - base.top);" in move_fn)
check("  over 450ms, on a curve rather than a linear ramp",
      "var PILL_GLIDE_MS = 450;" in ENGINE
      and '"transform " + PILL_GLIDE_MS + "ms " + PILL_EASE' in move_fn
      and 'var PILL_EASE = "cubic-bezier(0.25, 0.1, 0.25, 1)";' in ENGINE)
check("  and it is promoted for the length of the move, not for the walk",
      "liftPill(moved ? PILL_GLIDE_MS : 0);" in move_fn
      and 'el.pillFloat.style.willChange = "transform";' in body("liftPill")
      and 'style.willChange = "auto";' in body("liftPill")
      and "will-change: transform;" not in
      re.search(r"\.pill-float \{(.*?)\n\}", CSS, re.S).group(1))

print("\n--- v10: it never glides in from nowhere ---")
ground_fn = body("pillGrounded")
far_fn = body("pillFar")
check("a glide needs somewhere honest to start from",
      "var moved = !snap && !fresh && pillGrounded() && !still "
      "&& !pillFar(x, y);" in move_fn)
check("  which means a position this run measured, on a layer that is up",
      "if (!pillPos || !el.pillLayer || el.pillLayer.hidden) return false;"
      in ground_fn)
check("  and a box the reader can actually see",
      "box.right > 0 && box.bottom > 0" in ground_fn
      and "box.left < (window.innerWidth || 0)" in ground_fn
      and "box.top < (window.innerHeight || 0)" in ground_fn)
check("  so a first appearance and a return are placed, never played",
      "var fresh = el.pillLayer.hidden;" in move_fn
      and "pillPos = null;" in body("hidePill"))
check("a travel longer than the screen could honestly need is placed",
      "var PILL_MAX_TRAVEL = 0.6;" in ENGINE
      and "Math.sqrt(w * w + h * h) * PILL_MAX_TRAVEL" in far_fn
      and "return Math.sqrt(dx * dx + dy * dy) > far;" in far_fn)
check("a placement is committed before anything can transition it",
      "void el.pillFloat.offsetWidth;" in move_fn
      and move_fn.index('style.transform = "translate("')
      < move_fn.index("void el.pillFloat.offsetWidth;"))
check("the target is read after the browser has laid the screen out",
      "requestAnimationFrame" in aim_fn
      and "getBoundingClientRect" not in aim_fn)

print("\n--- v10: one glide and at most one settle ---")
quiet_fn = body("quietPill")
check("a re-aim while the glide is in the air is refused",
      "if (pillFlight && !snap) return;" in move_fn
      and "pillFlight = moved;" in move_fn)
check("  and the end of the glide is what lets the next one through",
      'carrier.addEventListener("transitionend"' in node_fn
      and 'ev.propertyName !== "transform"' in node_fn
      and "pillFlight = false;" in node_fn
      and "aimPill();" in node_fn)
check("the screen settling under it is waited for, not polled",
      "function quietPill(" in ENGINE
      and "var PILL_QUIET_MS = 250;" in ENGINE
      and 'screen.addEventListener("animationend", done)' in quiet_fn
      and "pillQuiet = setTimeout(done, PILL_QUIET_MS);" in quiet_fn)
check("  and it settles through the same aimer as everything else",
      "aimPill();" in quiet_fn
      and "function settlePill(" not in ENGINE
      and "PILL_SETTLE_FRAMES" not in ENGINE)
# v10 watches the screen for CHANGES rather than one box for a resize: the
# block the kicker sits in is `display: contents` on this funnel and so has no
# box to observe, and what actually moves the slot is a class going on and a
# grid being appended.
check("the memorise screen's own phases go through it too",
      "new MutationObserver(function () { aimPill(); }).observe(mid, {"
      in node_fn
      and "childList: true, subtree: true," in node_fn
      and 'attributeFilter: ["class", "hidden"]' in node_fn)
check("  and a glide whose end is never reported does not lock it out",
      "pillLanded = setTimeout(function () {" in body("placePill")
      and "pillFlight = false;" in body("placePill"))
check("  and so does a rotation, which places rather than plays",
      "movePill(true);" in ENGINE and "if (instant) pillSnap = true;" in aim_fn)
check("two screens that put it in the same place swap the text and nothing else",
      "var still = !!pillPos && pillPos.x === x && pillPos.y === y;" in move_fn
      and "el.pillFloat.style.transition = moved" in move_fn
      and re.search(r"el\.pillFloat\.style\.transition = moved.*?: \"none\";",
                    move_fn, re.S) is not None)
check("the copy each screen draws holds the space and is never seen",
      ".step-kicker.is-slot { opacity: 0; }" in CSS
      and 'node.classList.add("is-slot");' in pill_fn)
check("  and it is measured with this screen's own text already in it",
      move_fn.index("fillPill(node, pillText);")
      < move_fn.index("getBoundingClientRect()"))
check("the move happens after the screen it belongs to is on",
      "movePill();" in body("advance")
      and body("advance").index('show("screen-swipe");')
      < body("advance").index("movePill();"))
check("  and a screen with no pill is left alone rather than emptied",
      "if (!slot) return;" in move_fn)
# v10 states the same three rules where they now live: see the "never glides
# in from nowhere" and "one glide and at most one settle" blocks below.
check("  and the second call a step change makes is a no-op",
      "if (still && pillText === pillShown) return;" in move_fn)
check("  and the correction the glide's end allows is a short one",
      "var PILL_SETTLE_MS = 140;" in ENGINE)

print("\n--- v7: the beat, once a round ---")
beat_fn = body("beatPill")
check("it fires when the round changes and never when the counter does",
      "if (key === pillRound) return;" in beat_fn
      and "pillParts(pillText).label" in move_fn)
check("  and a re-place mid-round leaves a pending beat alone",
      beat_fn.index("if (key === pillRound) return;")
      < beat_fn.index("clearTimeout(pillPulse);"))
# v9. The round a screen between rounds names is the round the step after it
# names, however the two are written: the stylesheet sets the pill in capitals,
# so "Round 4 · Focus" and "ROUND 4 · FOCUS" are one round on the page and have
# to be one round here, or it beats twice.
check("  and the same round written two ways is one round",
      "function roundKey(" in ENGINE
      and ".toUpperCase()" in body("roundKey")
      and "var key = roundKey(label);" in beat_fn)
check("a beat announces a round somebody is about to play",
      "if (!pillBeats()) return;" in beat_fn
      and "step < ((cfg && cfg.swipe && cfg.swipe.pairs_count) || 0)"
      in body("pillBeats"))
check("  the class comes off when the beat ends, so it means beating now",
      'node.addEventListener("animationend", function () {' in body("pillNode")
      and 'node.classList.remove("is-pulse");' in body("pillNode"))
check("  after the glide has landed, not with it",
      "moved ? PILL_GLIDE_MS : 0" in move_fn
      and "}, delay);" in beat_fn)
check("  and it is restarted rather than re-added, or it would play once",
      'el.pill.classList.remove("is-pulse");' in beat_fn
      and "void el.pill.offsetWidth;" in beat_fn
      and 'el.pill.classList.add("is-pulse");' in beat_fn)
pulse = re.search(r"@keyframes mz-pill-pulse \{(.*?)\n\}", CSS, re.S)
check("the beat is a scale to 1.08 and back",
      pulse is not None
      and "scale(1.08)" in pulse.group(1)
      and pulse.group(1).count("scale(1)") == 2)
check("  over 400ms",
      "animation: mz-pill-pulse 400ms" in CSS
      and "var PILL_PULSE_MS = 400;" in ENGINE)
check("  and the class comes off even where the beat never plays",
      "PILL_PULSE_MS + 60" in beat_fn)
check("  played on the inner node, so it cannot disturb the glide",
      ".pill-float .step-kicker.is-pill.is-pulse {" in CSS)
# WARM-UP, then four rounds. The pill arriving is the round it names changing
# from nothing to something, so the walk gets five beats and not four.
BRAIN = CONFIGS[OWNER]
labels = []
for st in BRAIN["swipe"]["steps"]:
    text = st.get("kicker") or ""
    cut = text.rfind("·")
    labels.append((text if cut < 0 else text[:cut]).strip())
changes = sum(1 for i, lab in enumerate(labels)
              if i == 0 or lab != labels[i - 1])
check("the walk changes round five times, so the pill beats five times",
      changes == 5, str(changes))
check("  and never between two steps of the same round",
      changes == len(set(labels)), str(sorted(set(labels))))

print("\n--- v7: the memorise screen draws the same pill ---")
mid_fn = body("setMidKicker")
# v9. Every interstitial takes it, not only the memorise screens: the pill is
# one piece of chrome that follows the reader through the whole walk, and a
# screen it left and came back to was a screen it jumped on and off.
check("every interstitial takes it, and only where a funnel asked",
      "if (!(roundPill() && text)) {" in mid_fn
      and "host.textContent = text;" in mid_fn)
check("  built from the same parse the step pill is built from",
      "fillPill(slot, text);" in mid_fn
      and 'elm("span", "step-kicker is-pill is-slot")' in mid_fn)
check("  and placed once the screen is on",
      "if (roundPill() && entry.kicker) {" in body("openInterstitial")
      and body("openInterstitial").index('show("screen-interstitial");')
      < body("openInterstitial").index("pillText = entry.kicker;"))
check("a screen that names no round still sends the pill away",
      "hidePill();" in body("openInterstitial"))
check("  and every screen this funnel draws names one",
      all(e.get("kicker") for e in CONFIGS[OWNER]["interstitials"]),
      str([e["after_step"] for e in CONFIGS[OWNER]["interstitials"]
           if not e.get("kicker")]))
check("  and so does the result, because the walk is over",
      "hidePill();" in body("startResult"))

print("\n--- v7: the picture on the intro card ---")
intro_fn = body("showIntro")
check("it is gated on the config naming one",
      "if (block.image) {" in intro_fn and 'art.src = block.image;' in intro_fn)
check("  drawn between the kicker and the headline",
      intro_fn.index("if (block.image)")
      < intro_fn.index("if (block.headline)"))
check("  decorative, so it is not announced",
      'art.alt = "";' in intro_fn
      and 'art.setAttribute("aria-hidden", "true");' in intro_fn)
check("  and sized in the stylesheet rather than in a script",
      re.search(r"\.intro-art \{[^}]*max-width: 200px;", CSS, re.S) is not None
      and re.search(r"\.intro-art \{[^}]*margin: 0 auto", CSS, re.S)
      is not None)

print("\n--- v7: the game's blue, and what it is not allowed to reach ---")
theme_rules = [r for r in RULES if r.startswith("body.theme-brain")]
check("every blue rule is under the funnel's own theme class",
      theme_rules and all(r.startswith("body.theme-brain ")
                          or r == "body.theme-brain" for r in theme_rules),
      str(theme_rules))
check("  and none of them repaints the accent the platform's furniture uses",
      not [r for r in theme_rules
           if re.search(re.escape(r) + r"\s*\{[^}]*--accent\s*:", CSS, re.S)],
      str(theme_rules))
check("the progress dots and the header are not in the list at all",
      not [r for r in theme_rules
           if "progress" in r or "brand" in r or "header" in r],
      str(theme_rules))
check("the pill is the game's blue on its own pale ground",
      re.search(r"body\.theme-brain \.step-kicker\.is-pill \{[^}]*"
                r"border: 1\.5px solid var\(--brain-line\);", CSS, re.S)
      is not None
      and re.search(r"body\.theme-brain \.step-kicker\.is-pill \{[^}]*"
                    r"background: var\(--brain-soft\);", CSS, re.S) is not None
      and re.search(r"body\.theme-brain \.step-kicker\.is-pill \{[^}]*"
                    r"color: var\(--brain-ink\);", CSS, re.S) is not None)
check("  and its counter is that blue solid, in white",
      re.search(r"body\.theme-brain \.step-kicker-count \{[^}]*"
                r"background: var\(--brain-line\);", CSS, re.S) is not None
      and re.search(r"body\.theme-brain \.step-kicker-count \{[^}]*"
                    r"color: #fff;", CSS, re.S) is not None)
check("the three tokens are the ones the review named",
      re.search(r"body\.theme-brain \{(.*?)\n\}", CSS, re.S) is not None
      and "#378ADD" in re.search(r"body\.theme-brain \{(.*?)\n\}",
                                 CSS, re.S).group(1)
      and "#E6F1FB" in re.search(r"body\.theme-brain \{(.*?)\n\}",
                                 CSS, re.S).group(1)
      and "#0C447C" in re.search(r"body\.theme-brain \{(.*?)\n\}",
                                 CSS, re.S).group(1))
check("the clock is in the same family",
      "body.theme-brain .mz-timer-fill {" in CSS
      and "body.theme-brain .mz-timer-track { background: var(--brain-soft); }"
      in CSS
      and "body.theme-brain .mid.is-flash .mz-prepare-count { "
          "color: var(--brain-line); }" in CSS)
check("  and the last two seconds keep their red, which is not decoration",
      not [r for r in theme_rules if "is-warn" in r], str(theme_rules))
# v10: the air over the question is the pill's own bottom margin now, so the
# question adds none of its own. What is left of the rhythm is unchanged.
check("the column has one rhythm rather than four spacings",
      "body.theme-brain .caption { margin: 0 0 18px; }" in CSS
      and "body.theme-brain .step.is-timed .mz-timer { margin: 0 0 16px; }"
      in CSS)
check("  and the memorise screens are spaced the same way",
      "body.theme-brain #screen-interstitial .mid-line { margin-top: 0; }"
      in CSS
      and "body.theme-brain .mid.is-flash .mz-timer { margin: 18px auto 16px; }"
      in CSS)
check("no other funnel names this theme",
      [n for n, c in CONFIGS.items() if c.get("theme") == "brain"] == [OWNER],
      str([n for n, c in CONFIGS.items() if c.get("theme") == "brain"]))

print("\n--- v8: a tap answered with a mark rather than a word ---")
choose_fn = body("choose")
mark_fn = body("markChosen")
check("the mode is one more branch on the same read, not a new read",
      'labels === "check"' in choose_fn
      and "markChosen(card);" in choose_fn
      and ENGINE.count('labelMode() === "check"') == 1)
check("  so a funnel on any other mode falls through exactly as it did",
      choose_fn.index('labels === "on_tap"')
      < choose_fn.index('labels === "check"')
      and "showReaction(item.label" in choose_fn)
check("the mark is drawn, not typed",
      mark_fn.count('mark.appendChild(elm("i"));') == 2
      and "\u2713" not in mark_fn and "&check" not in mark_fn)
check("  once per card, and announced to nobody",
      'card.querySelector(".card-check")' in mark_fn
      and 'mark.setAttribute("aria-hidden", "true");' in mark_fn)
check("a run the clock answered gets no mark at all",
      "if (!card || card.querySelector" in mark_fn
      and "choose(item, null);" in body("timeOut")
      and "if (card) {" in choose_fn
      and choose_fn.index("if (card) {")
      < choose_fn.index("markChosen(card);"))
check("  which is the same guard every other confirmation is behind",
      choose_fn.index("if (card) {") < choose_fn.index("revealLabel(item"))
check("it is a circle over the middle of the art",
      re.search(r"\.card-check \{[^}]*top: 50%;", CSS, re.S) is not None
      and re.search(r"\.card-check \{[^}]*left: 50%;", CSS, re.S) is not None
      and re.search(r"\.card-check \{[^}]*border-radius: 50%;", CSS, re.S)
      is not None)
check("  solid in the game's blue, 44px across",
      re.search(r"\.card-check \{[^}]*background: #378ADD;", CSS, re.S)
      is not None
      and re.search(r"\.card-check \{[^}]*width: 44px;", CSS, re.S)
      is not None
      and re.search(r"\.card-check \{[^}]*height: 44px;", CSS, re.S)
      is not None)
check("  with the tick's two strokes in white",
      re.search(r"\.card-check i \{[^}]*background: #fff;", CSS, re.S)
      is not None
      and ".card-check i:first-child {" in CSS
      and ".card-check i:last-child {" in CSS)
pop = re.search(r"@keyframes mz-check-pop \{(.*?)\n\}", CSS, re.S)
check("it pops in by scale, over 200ms",
      pop is not None and "transform: scale(0)" in pop.group(1)
      and "scale(1.12)" in pop.group(1)
      and "animation: mz-check-pop 200ms" in CSS)
check("  and opting out of motion places it rather than plays it",
      re.search(r"@media \(prefers-reduced-motion: reduce\) \{\s*"
                r"\.card-check \{ animation: none;", CSS, re.S) is not None)
check("one confirmation per tap: the corner badge stands down",
      ".cards.is-check .check { display: none; }" in CSS
      and 'el.cards.classList.toggle("is-check", labelMode() === "check");'
      in body("renderStep"))
check("a memorise screen draws no caption under its frames either",
      'if (frame.label && labels !== "check") {' in body("setFlash")
      and "var labels = labelMode();" in body("setFlash"))
check("  and the label is still there for the reader who cannot see them",
      all(f.get("label") for e in CONFIGS[OWNER]["interstitials"]
          if e["after_step"] == 16
          for f in e["flash"]["images"]))
check("no other funnel asks for the mode",
      [n for n, c in CONFIGS.items()
       if (c.get("swipe") or {}).get("label_mode") == "check"] == [OWNER],
      str([n for n, c in CONFIGS.items()
           if (c.get("swipe") or {}).get("label_mode") == "check"]))
check("  and none of them names it on a step either",
      not [n for n, c in CONFIGS.items()
           for st in (c.get("swipe") or {}).get("steps", [])
           if st.get("label_mode") == "check"])

print("\n--- v8: one tile rule, three places that draw tiles ---")
MODULE = open(os.path.join(ROOT, "static/js/result_brain.js"),
              encoding="utf-8").read()
tile_fn = body("stepTile")
open_fn = body("openFrame")
check("the rule is one function",
      "function stepTile(index, stepId, item, late)" in ENGINE)
check("  a round the clock answered has no picture",
      'if (late && stepId && late.indexOf(stepId) !== -1) return { img: null };'
      in tile_fn)
check("  a round played on identical frames shows the one that was open",
      "openFrame(index) || (item && item.img)" in tile_fn
      and "entry.reveal && entry.reveal.open_slot" in open_fn
      and "frames[open].img" in open_fn)
check("  and everything else is the card that was tapped",
      "(item && item.img) || null" in tile_fn)
check("both gates are config, so no other funnel's rows move",
      'entry.after_step !== index' in open_fn
      and "return timedOutSteps;" in body("lateSteps"))
check("the row between rounds reads it",
      "out.push(stepTile(index, id, item, late));" in body("echoPicks"))
check("  and so does the grid on the analysing screen",
      "out.push(stepTile(i, st && st.id, item, late));" in body("gridPicks"))
check("  and both draw a tile through one filler",
      "fillTile(cell, tile);" in body("setEcho")
      and "fillTile(cell, tile);" in body("startGrid"))
fill_fn = body("fillTile")
check("the cross is the same mark the strip and the cover draw",
      'cell.classList.add("is-out");' in fill_fn
      and fill_fn.count('mark.appendChild(elm("i"));') == 2
      and ".tile-out i:first-child { transform: rotate(45deg); }" in CSS
      and ".tile-out i:last-child { transform: rotate(-45deg); }" in CSS)
check("  and no cross node exists on a run with no clock in it",
      "if (!tile || !tile.img) {" in fill_fn)
check("the result module reads the same rule off the context",
      "tile: stepTile," in ENGINE
      and ENGINE.count("tile: stepTile,") == 2
      and 'typeof ctx.tile === "function"' in MODULE)
check("  rather than keeping a second copy of it",
      "function standIn(" not in MODULE
      and "after_step !== index" not in MODULE)
check("no other funnel names a slot to stand in for a round",
      [n for n, c in CONFIGS.items()
       for e in (c.get("interstitials") or [])
       if (e.get("reveal") or {}).get("open_slot") is not None] == [OWNER] * 4,
      str([n for n, c in CONFIGS.items()
           for e in (c.get("interstitials") or [])
           if (e.get("reveal") or {}).get("open_slot") is not None]))

print("\n--- v9: the pill sits in one place, on every screen ---")
# v10 replaces the one distance with one rule: the pill is centred in the band
# between the progress bar and the first thing under it, whatever that band
# turns out to be. Layout, not pixels — a single value states both halves on a
# step, and auto margins divide the leftover on a screen between rounds.
check("the pill is centred in its band, by layout rather than by pixels",
      "body.theme-brain #step-kicker.is-pill { margin: 25px auto; }" in CSS
      and re.search(r"body\.theme-brain #screen-interstitial "
                    r"\.mid-kicker\.is-pill-host \{[^}]*margin: auto 0;",
                    CSS, re.S) is not None)
check("  and the host is a flex row, so the halves are not thrown by a "
      "baseline",
      re.search(r"body\.theme-brain #screen-interstitial "
                r"\.mid-kicker\.is-pill-host \{[^}]*display: flex;",
                CSS, re.S) is not None
      and re.search(r"body\.theme-brain #screen-interstitial "
                    r"\.mid-kicker\.is-pill-host \{[^}]*"
                    r"justify-content: center;", CSS, re.S) is not None)
check("  which needs the block it is in to stop being a box",
      "body.theme-brain #screen-interstitial .mid-body { display: contents; }"
      in CSS)
check("  and the pill that travels is not spaced a second time",
      re.search(r"\.pill-float \.step-kicker\.is-pill \{ margin: 0; \}", CSS)
      is not None
      and not [r for r in RULES if r.startswith("body.theme-brain")
               and ".step-kicker.is-pill" in r and "#step-kicker" not in r
               and "margin" in re.search(re.escape(r) + r"\s*\{([^}]*)\}",
                                         CSS, re.S).group(1)])
check("  and the leftover is divided in three: over it, under it, and below",
      re.search(r"body\.theme-brain #screen-interstitial\.is-active::after"
                r" \{[^}]*margin-top: auto;", CSS, re.S) is not None
      and CSS.count("margin: auto 0;") >= 1)
# The two `.mid-body` rules that are not scoped are the ones that were here
# before: its own auto margin and the centring the auto-advance mode gives it.
# What v9 adds to that element is scoped, and it is the only thing that can
# turn the block into a non-box.
check("every rule v9 adds to that block is under the funnel's theme class",
      [r for r in RULES if "mid-body" in r and "display: contents"
       in re.search(re.escape(r) + r"\s*\{([^}]*)\}", CSS, re.S).group(1)]
      == ["body.theme-brain #screen-interstitial .mid-body"],
      str([r for r in RULES if "mid-body" in r]))

print("\n--- v9: the intro card, in the game's blue ---")
intro_rules = [r for r in RULES if ".intro-" in r]
check("the kicker, the chips and the button are blue",
      "body.theme-brain .intro-kicker { color: var(--brain-ink); }" in CSS
      and re.search(r"body\.theme-brain \.intro-chip \{[^}]*"
                    r"border-color: var\(--brain-line\);", CSS, re.S)
      is not None
      and re.search(r"body\.theme-brain \.intro-cta \{[^}]*"
                    r"background: var\(--brain-line\);", CSS, re.S)
      is not None)
check("  the chips read in the deep blue, the button in white",
      re.search(r"body\.theme-brain \.intro-chip \{[^}]*"
                r"color: var\(--brain-ink\);", CSS, re.S) is not None
      and re.search(r"body\.theme-brain \.intro-cta \{[^}]*color: #fff;",
                    CSS, re.S) is not None)
check("  and every blue intro rule is under the theme class",
      all(r.startswith("body.theme-brain ")
          for r in intro_rules if "theme-" in r)
      and [r for r in intro_rules if r.startswith("body.theme-brain ")],
      str([r for r in intro_rules if "theme-" in r
           and not r.startswith("body.theme-brain ")]))
check("the headline and the subline keep the funnel's own ink",
      not [r for r in intro_rules
           if r.startswith("body.theme-brain")
           and ("intro-head" in r or "intro-sub" in r or "intro-foot" in r)],
      str(intro_rules))
check("  and nothing in the block repaints the accent the header reads",
      not [r for r in RULES if r.startswith("body.theme-brain")
           and re.search(re.escape(r) + r"\s*\{[^}]*--accent\s*:", CSS,
                         re.S)])
check("no other funnel is on this theme",
      [n for n, c in CONFIGS.items() if c.get("theme") == "brain"] == [OWNER])

print("\n--- v9: the walk beats five times, and where ---")
# The screens between rounds carry the pill now, so a round can first appear
# on one of them. ROUND 4 does: the confirm sits after fourteen steps, which
# is before the first step of that round, so the beat belongs there and must
# not fire again on the step behind it.
BRAIN = CONFIGS[OWNER]
order = []
for i, st in enumerate(BRAIN["swipe"]["steps"]):
    for e in BRAIN["interstitials"]:
        if e["after_step"] == i and e.get("kicker"):
            order.append(("mid", e["kicker"]))
    order.append(("step", st["kicker"]))
for e in BRAIN["interstitials"]:
    if e["after_step"] >= len(BRAIN["swipe"]["steps"]) and e.get("kicker"):
        order.append(("after", e["kicker"]))


def label_of(text):
    """`pillParts` and `roundKey`, restated: the label, upper-cased."""
    cut = text.rfind("·")
    tail = text[cut + 1:].strip() if cut >= 0 else ""
    body_text = text[:cut] if re.match(r"^\d+/\d+$", tail) else text
    return re.sub(r"\s+", " ", body_text).strip().upper()


beats = []
last = None
for kind, text in order:
    lab = label_of(text)
    if lab != last:
        last = lab
        if kind != "after":
            beats.append((kind, lab))
check("the walk changes round five times before its last step",
      len(beats) == 5, str(beats))
check("  starting on the warm-up and ending on round four",
      beats[0][1] == "WARM-UP" and beats[-1][1] == "ROUND 4 · FOCUS",
      str(beats))
check("  and round four's is on the screen before its first step",
      beats[-1][0] == "mid", str(beats[-1]))
check("the screen after the last step changes the words and beats on none",
      [t for k, t in order if k == "after"] == ["Computing"],
      str([t for k, t in order if k == "after"]))
check("  which is what pillBeats is for",
      "function pillBeats(" in ENGINE)

print("\n%d checks, %d failed" % (checks[0], len(fails)))
for f in fails:
    print("  FAIL " + f)
sys.exit(1 if fails else 0)
