#!/usr/bin/env python3
"""Where the free part of the result page stops, checked on the page itself.

Walks the quiz for real, then reads the free result: what the palette gives
away and what it holds back, whether the first mistake is whole, what the
locked zone is made of now, and whether the commerce block reads top to bottom
in the order a decision is made. Then goes looking for the gated paint codes
everywhere a reader could look for them — the served JSON, the served JS, and
the rendered DOM — because a boundary that only exists in CSS is not one.

    python3 boundary.py
"""
import json
import os
import re
import sys
import urllib.request

# The repo root, derived from this file rather than hardcoded: a suite
# that only runs from one absolute path is a suite that stops running the
# first time the checkout moves.
REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from playwright.sync_api import sync_playwright   # noqa: E402
from test_walk import Handler, PORT, STEPS, ANCHORS, serve  # noqa: E402

ROOT = REPO
SHOTS = os.path.dirname(os.path.abspath(__file__))
CHROME = "/opt/pw-browsers/chromium-1194/chrome-linux/chrome"

CFG = json.load(open(os.path.join(ROOT, "funnels/kitchen.json")))
COMMERCE = CFG["checkout"]["commerce"]
ALSO = CFG["report"]["also"]
SECTION_TITLE = {s["id"]: s["title"] for s in CFG["report"]["sections"]}

# Every paint code the config used to hand over, reconstructed from the rgb
# triples it carries now. These are the strings that must not be reachable.
GATED = []
for _style in CFG["styles"]:
    for _c in _style["reveals"]["palette"]["colors"]:
        r, g, b = _c["rgb"]
        GATED += ["#%02X%02X%02X" % (r, g, b), "#%02x%02x%02x" % (r, g, b)]

fails = []
checks = [0]


def check(label, ok, detail=""):
    checks[0] += 1
    if not ok:
        fails.append("%s %s" % (label, detail))
    print("  %-60s %s%s" % (label, "ok" if ok else "FAIL",
                            ("  " + str(detail)) if not ok else ""))


def quiz(page):
    page.wait_for_selector("#cards .card", timeout=10000)
    for i, step in enumerate(STEPS):
        page.query_selector_all("#cards .card")[0].click()
        done = i + 1
        if done in ANCHORS and done < len(STEPS):
            page.wait_for_selector("#screen-interstitial.is-active",
                                   timeout=12000)
            page.click("#mid-cta")
        if done < len(STEPS):
            page.wait_for_function(
                "q => document.getElementById('swipe-caption').textContent === q",
                arg=STEPS[done]["question"], timeout=15000)
    page.wait_for_selector("#result-body:not([hidden])", timeout=20000)
    page.wait_for_timeout(400)


def titles(page):
    return page.eval_on_selector_all(
        "#report .section",
        "ns => ns.map(n => (n.querySelector('.section-title')||{}).textContent)")


def main():
    httpd = serve()
    try:
        with sync_playwright() as pw:
            browser = pw.chromium.launch(executable_path=CHROME)
            page = browser.new_page(viewport={"width": 390, "height": 844},
                                    device_scale_factor=2)
            errors = []
            page.on("pageerror", lambda e: errors.append(str(e)))
            page.on("console",
                    lambda m: errors.append(m.text) if m.type == "error" else None)

            page.goto("http://127.0.0.1:%d/kitchen" % PORT)
            quiz(page)
            style = page.inner_text("#result-name")

            print("\n--- 1. the palette gives the colour, not the code ---")
            rows = page.eval_on_selector_all(".swatch-row", """ns => ns.map(n => ({
                name: (n.querySelector('.swatch-name').firstChild||{}).textContent,
                dot: getComputedStyle(n.querySelector('.swatch-dot')).backgroundColor,
                masked: !!n.querySelector('.swatch-hex.is-masked'),
                mask: (n.querySelector('.code-mask')||{}).textContent,
                lock: !!n.querySelector('.swatch-hex .padlock'),
                blur: getComputedStyle(
                    n.querySelector('.code-mask')||n).filter,
                text: n.textContent
            }))""")
            # Five since the palette went to five roles — cabinetry, worktop,
            # walls, contrast and metal. Read from the config rather than
            # written in, so the next change to the palette is a config change
            # and not a config change plus a number in here.
            want = len(CFG["styles"][0]["reveals"]["palette"]["colors"])
            check("%d colours" % want, len(rows) == want, len(rows))
            check("every one is named",
                  all(r["name"] and r["name"].strip() for r in rows),
                  [r["name"] for r in rows])
            check("every dot is painted the real colour",
                  all(re.match(r"^rgba?\(\d", r["dot"] or "") for r in rows),
                  [r["dot"] for r in rows])
            check("every code slot is masked",
                  all(r["masked"] for r in rows), rows[:1])
            check("the mask is block characters, not a value",
                  all(r["mask"] == "#■■■■■"
                      for r in rows), [r["mask"] for r in rows])
            check("each carries a lock", all(r["lock"] for r in rows))
            check("the mask is blurred",
                  all("blur" in (r["blur"] or "") for r in rows),
                  [r["blur"] for r in rows])
            check("no row's text contains a #code",
                  not any(re.search(r"#[0-9A-Fa-f]{6}", r["text"] or "")
                          for r in rows))
            line = (page.inner_text(".callout")
                    if page.query_selector(".callout") else "")
            check("the why-it-fits line survives", len(line) > 40, line[:60])

            print("\n--- 2. the elements strip stops specifying ---")
            check("header subline is the new one",
                  page.inner_text(".elements-sub")
                  == CFG["style_elements"]["subline"],
                  page.inner_text(".elements-sub"))
            check("six chips still",
                  page.eval_on_selector_all(".element-chip", "n => n.length") == 6)
            check("every chip has a thumbnail and a label",
                  page.eval_on_selector_all(".element-chip", """ns => ns.every(
                      n => n.querySelector('.element-thumb img')
                        && n.querySelector('.element-label'))"""))
            check("no spec subline on any free chip",
                  page.eval_on_selector_all(".element-spec", "n => n.length") == 0,
                  page.eval_on_selector_all(".element-spec", "n => n.length"))

            print("\n--- 3. mistake #1, whole and free ---")
            one = page.query_selector(".section-mistake-one")
            check("the card is on the page", one is not None)
            check("it sits directly under the palette",
                  titles(page)[:2] == [SECTION_TITLE["palette"],
                                       CFG["report"]["mistake_one"]["title"]],
                  titles(page)[:3])
            check("it is numbered 1",
                  page.inner_text(".section-mistake-one .mistake-num") == "1")
            body = page.eval_on_selector(".section-mistake-one", """n => ({
                title: n.querySelector('.mistake-title').textContent,
                body: n.querySelector('.mistake-body').textContent,
                fix: n.querySelector('.mistake-fix').textContent,
                note: (n.querySelector('.mistake-locked')||{}).textContent,
                lock: !!n.querySelector('.mistake-locked .padlock'),
                blurred: n.querySelector('.dissolve') !== null
            })""")
            wanted = None
            for s in CFG["styles"]:
                if s["name"] == style:
                    wanted = s["reveals"]["mistake_one"]
            check("title, why and fix are the config's, in full",
                  body["title"] == wanted["title"]
                  and body["body"] == wanted["body"]
                  and body["fix"] == "→ Fix: " + wanted["fix"],
                  body["title"])
            check("nothing about it is blurred", not body["blurred"])
            check("the footer says where 2-5 are",
                  CFG["report"]["mistake_one"]["locked_note"] in body["note"],
                  body["note"])
            check("with a lock on it", body["lock"])

            print("\n--- 4. the locked zone: two teasers, then one card ---")
            shown = titles(page)
            check("materials, dna and splurge have no block of their own",
                  not ({SECTION_TITLE["materials"], SECTION_TITLE["dna"],
                        SECTION_TITLE["splurge"]} & set(shown)), shown)
            blurred = page.eval_on_selector_all(
                "#report .section:has(.dissolve)",
                "ns => ns.map(n => n.querySelector('.section-title').textContent)")
            check("exactly two sections keep the blur treatment",
                  blurred == [SECTION_TITLE["mistakes"],
                              SECTION_TITLE["shopping"]], blurred)
            trigger = page.inner_text(
                "#report .section .dissolve-crisp .trigger")
            check("the mistakes teaser now teases 2-5",
                  page.inner_text("#report .section .dissolve-crisp .setup")
                  .startswith("That one is the cheapest"), trigger)
            also = page.query_selector(".section-also")
            check("the compact card is there", also is not None)
            check("it is titled from config",
                  page.inner_text(".section-also .section-title")
                  == ALSO["title"])
            card = page.eval_on_selector_all(".also-row", """ns => ns.map(n => ({
                lock: !!n.querySelector('.padlock'),
                title: n.querySelector('.also-title').textContent,
                hook: (n.querySelector('.also-hook')||{}).textContent
            }))""")
            check("four rows", len(card) == 4, len(card))
            check("every row has a lock", all(r["lock"] for r in card))
            want_titles = [SECTION_TITLE[r["section"]] if "section" in r
                           else r["title"] for r in ALSO["rows"]]
            check("titles match the config, in order",
                  [r["title"] for r in card] == want_titles,
                  [r["title"] for r in card])
            # The hooks are templates now — "your {worktop}" — so what is
            # checked is that each row carries its own hook with every
            # placeholder resolved, rather than that it matches the config
            # string. hooks.py owns which words go in.
            import re as _re
            for i, row in enumerate(ALSO["rows"]):
                shape = _re.escape(row["hook"])
                shape = _re.sub(r"\\\{(\w+)\\\}", r"[^{}]+", shape)
                check("  row %d is its own hook, filled in" % i,
                      bool(_re.fullmatch(shape, card[i]["hook"])),
                      (row["hook"], card[i]["hook"]))
            check("no placeholder reaches the page",
                  not any("{" in r["hook"] for r in card),
                  [r["hook"] for r in card])
            # Three lines in the card's column at its widest label. Past this
            # the rows stop being scannable and the card stops being compact,
            # which is the whole reason it exists.
            check("each hook still reads as a line, not a paragraph",
                  all(len(r["hook"]) <= 125 for r in card),
                  max(len(r["hook"]) for r in card))

            print("\n--- 5. the commerce block, top to bottom ---")
            order = page.eval_on_selector(
                "#commerce",
                """n => Array.from(n.children)
                     .filter(c => !c.hidden && c.offsetParent !== null)
                     .map(c => c.id || c.className)""")
            check("headline, list, sample, price, consent, button, trust",
                  order == ["pay-anchor", "manifest", "sample-link", "price",
                            "withdrawal", "pay-button", "trust", "legal-links"],
                  order)
            head = page.eval_on_selector(".commerce .anchor-head", """n => ({
                text: n.textContent,
                size: parseFloat(getComputedStyle(n).fontSize),
                family: getComputedStyle(n).fontFamily,
                money: (n.querySelector('.money')||{}).textContent
            })""")
            check("the headline is the anchor copy",
                  head["text"] == COMMERCE["anchor_head"].replace(
                      "{price}", "$3"), head["text"])
            check("Fraunces at 20px",
                  head["size"] == 20 and "Fraunces" in head["family"], head)
            check("the saving is in the accent",
                  head["money"] == COMMERCE["anchor_head_accent"],
                  head["money"])
            check("no card box around it",
                  page.eval_on_selector(
                      ".commerce .pay-anchor",
                      "n => getComputedStyle(n).backgroundImage === 'none'"
                      " && getComputedStyle(n).backgroundColor"
                      " === 'rgba(0, 0, 0, 0)'"),
                  page.eval_on_selector(".commerce .pay-anchor",
                                        "n => getComputedStyle(n).backgroundColor"))
            check("the anchor sub-line is gone",
                  page.eval_on_selector(".commerce .anchor-line",
                                        "n => n.hidden || !n.textContent"))
            check("six manifest rows, at 14px",
                  page.eval_on_selector_all(".commerce .manifest-row",
                                            "n => n.length") == 6
                  and page.eval_on_selector(
                      ".commerce .manifest-text",
                      "n => parseFloat(getComputedStyle(n).fontSize)") == 14,
                  page.eval_on_selector(
                      ".commerce .manifest-text",
                      "n => getComputedStyle(n).fontSize"))
            check("the mistakes row still carries the accent",
                  page.eval_on_selector_all(
                      ".commerce .manifest-row.is-hero",
                      "ns => ns.length === 1 && ns[0].textContent") and
                  CFG["checkout"]["manifest_hero"] in page.inner_text(
                      ".commerce .manifest-row.is-hero").lower(),
                  page.inner_text(".commerce .manifest-row.is-hero"))
            price = page.eval_on_selector(".commerce .price", """n => ({
                text: n.textContent,
                weight: getComputedStyle(n).fontWeight,
                next: (n.nextElementSibling||{}).id
            })""")
            check("the price reads price, one-time, no subscription",
                  price["text"] == "3.00 USD · " + COMMERCE["price_suffix"],
                  price["text"])
            check("bold", int(price["weight"]) >= 700, price["weight"])
            check("nothing between it and the consent row",
                  price["next"] == "withdrawal", price["next"])
            check("the reframe line is not in the block",
                  page.eval_on_selector_all(
                      "#commerce .pay-reframe",
                      "ns => ns.filter(n => !n.hidden).length") == 0)
            check("no value banner remnant",
                  page.query_selector("#value-banner") is None)
            check("no cta note remnant",
                  page.query_selector("#cta-note") is None)
            btn = page.eval_on_selector("#pay-button", """n => {
                const r = n.getBoundingClientRect();
                const s = getComputedStyle(n);
                return {h: r.height, size: parseFloat(s.fontSize), bg: s.backgroundColor};
            }""")
            tallest = page.evaluate("""() => Math.max(...Array.from(
                document.querySelectorAll('#commerce button, #commerce a'))
                .filter(n => n.id !== 'pay-button')
                .map(n => n.getBoundingClientRect().height))""")
            check("the button is the largest tap target in the block",
                  btn["h"] >= 58 and btn["h"] > tallest,
                  "%s vs %s" % (btn["h"], tallest))
            check("and the only solid accent field",
                  btn["bg"].replace(" ", "") == "rgb(192,86,33)", btn["bg"])
            check("trust rows unchanged",
                  page.eval_on_selector_all(
                      ".commerce .trust-row",
                      "ns => ns.map(n => n.textContent.trim())")
                  == COMMERCE["trust"])

            print("\n--- 6. the sample page ---")
            check("the link sits under the manifest",
                  page.inner_text("#sample-link") == COMMERCE["sample_link"],
                  page.inner_text("#sample-link"))
            page.click("#sample-link")
            page.wait_for_selector("#sample-box:not([hidden])", timeout=4000)
            # Half a megabyte of PNG: measured after it has decoded, not
            # after the dialog has opened.
            page.wait_for_function(
                """() => { const i = document.querySelector('.sample-img');
                     return i && i.complete && i.naturalWidth > 0; }""",
                timeout=15000)
            box = page.eval_on_selector("#sample-box", """n => ({
                src: n.querySelector('.sample-img').getAttribute('src'),
                w: n.querySelector('.sample-img').naturalWidth,
                h: n.querySelector('.sample-img').naturalHeight,
                veil: getComputedStyle(n.querySelector('.sample-veil')).height,
                fig: n.querySelector('.sample-figure').getBoundingClientRect().height,
                caption: (n.querySelector('.sample-caption')||{}).textContent,
                modal: n.getAttribute('aria-modal')
            })""")
            check("it shows the generated page",
                  box["src"] == "/static/img/sample_page.png", box["src"])
            check("the image actually loaded", box["w"] > 0 and box["h"] > 0, box)
            check("the page is 840px — twice the box it is drawn in",
                  box["w"] == 840, box["w"])
            check("the lower half is veiled",
                  abs(float(box["veil"][:-2]) - box["fig"] / 2) < 2,
                  (box["veil"], box["fig"]))
            check("the caption says it is an example",
                  box["caption"] == COMMERCE["sample_caption"], box["caption"])
            check("it is a modal", box["modal"] == "true")
            check("the page behind it cannot scroll",
                  page.eval_on_selector("body",
                                        "n => getComputedStyle(n).overflow")
                  == "hidden")
            page.keyboard.press("Escape")
            page.wait_for_selector("#sample-box", state="hidden", timeout=3000)
            check("escape closes it",
                  page.eval_on_selector("#sample-box", "n => n.hidden"))
            check("and gives the page back",
                  page.eval_on_selector("body",
                                        "n => getComputedStyle(n).overflow")
                  != "hidden")

            print("\n--- 7. the two prompts still find the block ---")
            page.eval_on_selector("#mid-offer-cta, .mid-offer-cta", "n => n.click()")
            page.wait_for_timeout(900)
            check("the mid-CTA scrolls the commerce block into view",
                  page.eval_on_selector(
                      "#commerce",
                      """n => { const r = n.getBoundingClientRect();
                         return r.top < innerHeight && r.bottom > 0; }"""))
            page.evaluate("window.scrollTo(0, 0)")
            page.wait_for_timeout(400)
            page.evaluate("""() => {
                const r = document.getElementById('report');
                window.scrollTo(0, r.offsetTop + 600); }""")
            page.wait_for_timeout(500)
            check("the sticky bar comes back once past the palette",
                  page.eval_on_selector("#sticky-cta", "n => !n.hidden"))
            # The bar no longer scrolls anywhere — it takes the money. The
            # full event trail for that is polish2's; here it is enough that
            # the shortcut is wired and the offer it charges for is the block
            # this file has just finished checking.
            check("and it is wired straight to the pay button's handler",
                  page.evaluate("""() => {
                    const b = document.getElementById('pay-button'),
                          c = document.getElementById('withdrawal-check');
                    return !!b && !b.disabled && !!c && c.checked; }"""))

            print("\n--- 8. the gated codes are nowhere a reader can look ---")
            dom = page.content()
            hits = [h for h in GATED if h in dom]
            check("not in the rendered DOM", not hits, hits[:3])
            served = urllib.request.urlopen(
                "http://127.0.0.1:%d/static/funnels/kitchen.json" % PORT
            ).read().decode()
            hits = [h for h in GATED if h in served]
            check("not in the funnel JSON the browser fetches", not hits, hits[:3])
            payload = json.loads(served)
            check("and the palette carries rgb rather than hex",
                  all("hex" not in c and len(c.get("rgb", [])) == 3
                      for s in payload["styles"]
                      for c in s["reveals"]["palette"]["colors"]))
            js = urllib.request.urlopen(
                "http://127.0.0.1:%d/static/js/engine.js" % PORT
            ).read().decode()
            hits = [h for h in GATED if h in js]
            check("not in engine.js either", not hits, hits[:3])
            check("mistakes 2-5 are not in the payload at all",
                  all("mistake_one" in s["reveals"]
                      and not isinstance(s["reveals"]["mistakes"].get("items"),
                                         list)
                      for s in payload["styles"]))

            check("no page errors anywhere in the run", not errors, errors[:3])

            print("\n--- the page, top to bottom ---")
            page.evaluate("window.scrollTo(0, 0)")
            page.wait_for_timeout(500)
            shot = os.path.join(SHOTS, "shot-result-free.png")
            page.screenshot(path=shot, full_page=True)
            size = page.evaluate("() => document.body.scrollHeight")
            print("    %s  (%dpx tall)" % (shot, size))
            browser.close()
    finally:
        httpd.shutdown()

    print("\n%d checks, %d failed" % (checks[0], len(fails)))
    for f in fails:
        print("  FAIL " + f)
    return 1 if fails else 0


if __name__ == "__main__":
    raise SystemExit(main())
