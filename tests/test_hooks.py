#!/usr/bin/env python3
"""Whether the locked zone is asking about this reader's kitchen.

Two runs down the same funnel tapping different cards, and the hooks compared:
the words have to come out of the run rather than out of the style. Then a
third run against a config whose hook steps have been renamed, which is the one
way a live page can reach the fallback — the zone is only ever rendered off a
finished quiz, so there is no such thing as a run with no choices here.

    python3 hooks.py
"""
import copy
import http.server
import json
import os
import socketserver
import sys
import threading

# The repo root, derived from this file rather than hardcoded: a suite
# that only runs from one absolute path is a suite that stops running the
# first time the checkout moves.
REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from playwright.sync_api import sync_playwright   # noqa: E402
from test_walk import Handler as WalkHandler, PORT, STEPS, ANCHORS  # noqa: E402

ROOT = REPO
CHROME = "/opt/pw-browsers/chromium-1194/chrome-linux/chrome"
CFG = json.load(open(os.path.join(ROOT, "funnels/kitchen.json")))
SLOTS = CFG["report"]["hook_slots"]

LABELS = {i["id"]: i.get("label")
          for s in CFG["swipe"]["steps"]
          for p in s.get("pairs", []) for i in p["images"]}
STEP_IDS = {s["id"]: [i["id"] for p in s.get("pairs", []) for i in p["images"]]
            for s in CFG["swipe"]["steps"]}

break_slots = [False]
fails = []
checks = [0]


def check(label, ok, detail=""):
    checks[0] += 1
    if not ok:
        fails.append("%s %s" % (label, detail))
    print("  %-58s %s%s" % (label, "ok" if ok else "FAIL",
                            ("  " + str(detail)) if not ok else ""))


class Handler(WalkHandler):
    def do_GET(self):
        if (self.path.split("?")[0] == "/static/funnels/kitchen.json"
                and break_slots[0]):
            # Every slot points at a step that is not there any more — the
            # shape of a funnel edit that renames a step and forgets the map.
            cfg = copy.deepcopy(CFG)
            for rule in cfg["report"]["hook_slots"].values():
                rule["step"] = rule["step"] + "_gone"
            raw = json.dumps(cfg).encode()
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(raw)))
            self.end_headers()
            self.wfile.write(raw)
            return
        return super().do_GET()


def lower(text):
    return text[0].lower() + text[1:] if text else text


def walk(page, side):
    """One run. `side` picks the first or the last cell on every step."""
    picked = {}
    page.wait_for_selector("#cards .card", timeout=10000)
    for index, step in enumerate(STEPS):
        cards = page.query_selector_all("#cards .card")
        i = 0 if side == "first" else len(cards) - 1
        # The row is shuffled, so which id was tapped is read off the image.
        src = page.eval_on_selector_all(
            "#cards .card img", "ns => ns.map(n => n.getAttribute('src'))")[i]
        picked[step["id"]] = os.path.basename(src).split(".")[0]
        cards[i].click()
        done = index + 1
        if done in ANCHORS and done < len(STEPS):
            page.wait_for_selector("#screen-interstitial.is-active",
                                   timeout=12000)
            page.click("#mid-cta")
        if done < len(STEPS):
            page.wait_for_function(
                "q => document.getElementById('swipe-caption').textContent === q",
                arg=STEPS[done]["question"], timeout=15000)
    page.wait_for_selector("#result-body:not([hidden])", timeout=20000)
    page.wait_for_timeout(500)
    return picked


def hooks(page):
    return page.evaluate("""() => ({
        teaser: (document.querySelector('.mistakes-teaser')||{}).textContent,
        setups: Array.from(document.querySelectorAll(
            '#report .dissolve-crisp .setup')).map(n => n.textContent),
        triggers: Array.from(document.querySelectorAll(
            '#report .dissolve-crisp .trigger')).map(n => n.textContent),
        also: Array.from(document.querySelectorAll('.also-hook'))
            .map(n => n.textContent)
    })""")


def run(pw, side):
    browser = pw.chromium.launch(executable_path=CHROME)
    page = browser.new_page(viewport={"width": 390, "height": 844})
    errors = []
    page.on("pageerror", lambda e: errors.append(str(e)))
    page.on("console",
            lambda m: errors.append(m.text) if m.type == "error" else None)
    page.goto("http://127.0.0.1:%d/kitchen" % PORT)
    picked = walk(page, side)
    got = hooks(page)
    style = page.inner_text("#result-name")
    browser.close()
    return picked, got, style, errors


def main():
    socketserver.TCPServer.allow_reuse_address = True
    httpd = socketserver.TCPServer(("127.0.0.1", PORT), Handler)
    threading.Thread(target=httpd.serve_forever, daemon=True).start()
    try:
        with sync_playwright() as pw:
            runs = {}
            for side in ("first", "last"):
                print("\n--- tapping the %s cell on every step ---" % side)
                picked, got, style, errors = run(pw, side)
                runs[side] = (picked, got, style)
                want = {}
                for slot, rule in SLOTS.items():
                    want[slot] = lower(LABELS[picked[rule["step"]]])
                print("    style %s | %s" % (style, ", ".join(
                    "%s=%s" % (k, v) for k, v in want.items())))
                print("    teaser: %s" % got["teaser"])
                for line in got["also"]:
                    print("    also:   %s" % line)

                check("  no braces survive into the page",
                      not any("{" in t for t in
                              [got["teaser"]] + got["setups"] + got["triggers"]
                              + got["also"]),
                      [t for t in got["also"] if "{" in t])
                check("  the teaser names their style and their worktop",
                      style in got["teaser"]
                      and ("your %s." % want["worktop"]) in got["teaser"],
                      got["teaser"])
                check("  the materials row names worktop and metal",
                      got["also"][0].startswith("Your %s + %s pairing"
                                                % (want["worktop"],
                                                   want["metal"])),
                      got["also"][0])
                check("  the dna row names their palette",
                      "your %s choices" % want["palette"] in got["also"][1],
                      got["also"][1])
                check("  the splurge row names their floor",
                      "your %s budget" % want["floor"] in got["also"][2],
                      got["also"][2])
                check("  the paint-codes row is untouched",
                      got["also"][3] == CFG["report"]["also"]["rows"][3]["hook"],
                      got["also"][3])
                check("  the shopping setup names their metal",
                      any(want["metal"] in s for s in got["setups"]),
                      got["setups"])
                check("  the metal is in the legible half, not the blur",
                      not any(want["metal"] in t for t in got["triggers"]),
                      got["triggers"])
                check("  labels read lowercase mid-sentence",
                      all(w == lower(w) for w in want.values()), want)
                check("  no page errors", not errors, errors[:3])

            print("\n--- the two runs are not the same page ---")
            (p1, h1, s1), (p2, h2, s2) = runs["first"], runs["last"]
            check("they made different choices",
                  any(p1[r["step"]] != p2[r["step"]] for r in SLOTS.values()),
                  [(r["step"], p1[r["step"]], p2[r["step"]])
                   for r in SLOTS.values()])
            check("so the teaser differs", h1["teaser"] != h2["teaser"],
                  h1["teaser"])
            # Row by row, against the choices behind it. Two runs down a
            # shuffled funnel can land on the same floor by luck, and "every
            # row differs" would then fail on a page that is doing exactly
            # what it should — so what is checked is that a row differs when
            # and only when the choice it is written around did.
            row_slots = [("worktop", "metal"), ("palette",), ("floor",)]
            moved = 0
            for i, names in enumerate(row_slots):
                changed = any(p1[SLOTS[n]["step"]] != p2[SLOTS[n]["step"]]
                              for n in names)
                moved += 1 if changed else 0
                check("  row %d (%s) differs exactly when its choice did"
                      % (i, "+".join(names)),
                      (h1["also"][i] != h2["also"][i]) == changed,
                      (changed, h1["also"][i], h2["also"][i]))
            check("and at least one of them actually moved", moved > 0,
                  moved)
            check("while the unpersonalised one is identical",
                  h1["also"][3] == h2["also"][3])

            print("\n--- a config whose hook steps have been renamed ---")
            break_slots[0] = True
            picked, got, style, errors = run(pw, "first")
            print("    teaser: %s" % got["teaser"])
            for line in got["also"]:
                print("    also:   %s" % line)
            check("no braces are left on the page",
                  not any("{" in t for t in
                          [got["teaser"]] + got["setups"] + got["triggers"]
                          + got["also"]),
                  got["also"])
            check("each slot falls back to its bare noun",
                  "your worktop." in got["teaser"]
                  and got["also"][0].startswith("Your worktop + metal pairing")
                  and "your palette choices" in got["also"][1]
                  and "your floor budget" in got["also"][2],
                  [got["teaser"], got["also"][0]])
            check("every sentence still reads as English",
                  all("  " not in t and not t.strip().endswith("your")
                      for t in [got["teaser"]] + got["also"]),
                  got["also"])
            check("the style name still resolves", style in got["teaser"],
                  (style, got["teaser"]))
            check("no page errors", not errors, errors[:3])
    finally:
        httpd.shutdown()

    print("\n%d checks, %d failed" % (checks[0], len(fails)))
    for f in fails:
        print("  FAIL " + f)
    return 1 if fails else 0


if __name__ == "__main__":
    raise SystemExit(main())
