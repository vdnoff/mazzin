#!/usr/bin/env python3
"""The partner-article buttons on /ai-navigator, in a real browser.

The result page of this funnel can carry up to two links out to a partner's
articles. The partner pays on what happens over there, and only when the click
that brought the reader here travels with them — so what is walked here is the
whole trip an identifier makes: on the landing URL, through twelve steps, a
reload and a second arrival on a bare URL, into the query of a link.

Three arrivals, 390x844:

  1. fbclid, ad_id and asid on the URL. Two anchors under the pay button,
     each the config's link plus exactly those three, in the config's order.
     A tap reports `article_tap` with the article and the slot.
  2. no fbclid. Nothing is drawn, and the offer card is the same markup the
     first arrival got — which is the page as it was before the buttons.
  3. ad_id left as the ad platform's unresolved macro. That key is dropped
     and the other two still travel.

Nothing leaves the machine: every request off 127.0.0.1 is aborted, the
partner's included.

    python3 tests/test_ainavigator_rsoc.py
"""
import http.server
import json
import os
import re
import socketserver
import sys
import threading

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, REPO)

from playwright.sync_api import sync_playwright          # noqa: E402

PORT = 8857
CHROME = "/opt/pw-browsers/chromium-1194/chrome-linux/chrome"
BASE = "http://127.0.0.1:%d" % PORT

with open(os.path.join(REPO, "funnels", "ai-navigator.json"),
          encoding="utf-8") as fh:
    CFG = json.load(fh)
STEPS = CFG["swipe"]["steps"]
RSOC = CFG["rsoc"]
ARTICLES = RSOC["articles"]

fails = []
checks = [0]


def check(label, ok, detail=""):
    checks[0] += 1
    if not ok:
        fails.append("%s %s" % (label, detail))
    print("  %-62s %s%s" % (label, "ok" if ok else "FAIL",
                            ("  " + str(detail)[:300]) if not ok else ""))


events = []


class Handler(http.server.SimpleHTTPRequestHandler):
    """The funnel off disk, with its tracking posts recorded."""

    def __init__(self, *a, **kw):
        super().__init__(*a, directory=REPO, **kw)

    def log_message(self, *a):
        pass

    def do_GET(self):
        path = self.path.split("?")[0]
        if path == "/api/pixel-config":
            return self._json({"pixel_id": ""})
        if path == "/ai-navigator":
            self.path = "/static/funnel.html"
        return super().do_GET()

    def do_POST(self):
        raw = self.rfile.read(int(self.headers.get("content-length") or 0))
        path = self.path.split("?")[0]
        if path == "/api/track":
            try:
                events.append(json.loads(raw))
            except ValueError:
                events.append({"event": "<unparsable>"})
            return self._json({"ok": True})
        if path == "/api/payment-intent":
            return self._json({}, 502)
        return self._json({"ok": True})

    def _json(self, body, status=200):
        raw = json.dumps(body).encode()
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(raw)))
        self.end_headers()
        self.wfile.write(raw)


class Server(socketserver.ThreadingMixIn, http.server.HTTPServer):
    allow_reuse_address = True
    daemon_threads = True


# Which card is tapped on each step. The skill is design; the four zones score
# 2, 2, 1 and 0, so the zone with the most room is the last one, `spa`. The
# first card listed on a scored step is the hit.
SKILL = "skill_design"
ZONE = "spa"
MISSES = {"chg2", "spa1", "spa2"}


def label_for(step):
    cards = step["pairs"][0]["images"]
    if step["id"] == "skill":
        return [c for c in cards if SKILL in c.get("tags", [])][0]["label"]
    return cards[1 if step["id"] in MISSES else 0]["label"]


BY_QUESTION = {s["question"]: s for s in STEPS}

STATE = """() => {
  const on = s => { const n = document.querySelector(s);
                    return !!(n && n.offsetParent !== null); };
  if (document.querySelector('#result-module .ai-offer')) return 'result';
  const mid = document.querySelector('#screen-interstitial');
  if (mid && mid.classList.contains('is-active')) return 'mid';
  const sw = document.querySelector('#screen-swipe');
  const box = document.querySelector('#cards');
  if (sw && sw.classList.contains('is-active') && box
      && !box.classList.contains('is-leaving')
      && box.querySelectorAll('.card').length
      && !box.querySelector('.card.is-chosen')) {
    return 'step:' + document.querySelector('#swipe-caption').textContent;
  }
  if (on('.intro-cta')) return 'intro';
  return '';
}"""


def advance(page, until=None):
    """Play from wherever the page is. Stops on the result, or once the step
    with id `until` has been answered. Returns the ids answered, in order."""
    done = []
    idle = 0
    while idle < 240:
        state = page.evaluate(STATE)
        if state == "result":
            return done
        if state == "intro":
            page.wait_for_timeout(300)
            page.locator(".intro-cta").first.click()
            page.wait_for_timeout(500)
        elif state == "mid":
            page.wait_for_timeout(400)
            try:
                page.locator("#mid-cta").click(timeout=1500)
            except Exception:
                pass                         # it advanced on its own
            page.wait_for_timeout(500)
        elif state.startswith("step:") and state[5:] in BY_QUESTION:
            step = BY_QUESTION[state[5:]]
            page.wait_for_timeout(350)
            page.locator("#cards .card").filter(
                has=page.locator(".card-text", has_text=re.compile(
                    "^" + re.escape(label_for(step)) + "$"))).first.click()
            done.append(step["id"])
            idle = 0
            # A scenario answers the tap with a panel that moves on by itself;
            # its Next button moves on at once, which is what a walk wants.
            if step.get("why"):
                page.wait_for_timeout(450)
                try:
                    page.locator(".step-feedback-next").click(timeout=1500)
                except Exception:
                    pass                     # it had already moved on
            page.wait_for_timeout(500)
            if until and step["id"] == until:
                return done
            continue
        else:
            page.wait_for_timeout(250)
        idle += 1
    return done


def held(page):
    return page.evaluate(
        "() => JSON.parse(sessionStorage.getItem('mazzin_pass_ai-navigator')"
        " || 'null')")


PAGE = """() => {
  const root = document.querySelector('#result-module');
  const box = root.querySelector('.ai-rsoc');
  const offer = root.querySelector('.ai-offer');
  const pay = root.querySelector('#pay-button');
  const consent = document.querySelector('#withdrawal');
  const tick = document.querySelector('#withdrawal-check');
  const after = (a, b) => !!(a && b
    && (a.compareDocumentPosition(b) & Node.DOCUMENT_POSITION_FOLLOWING));
  const links = box ? [...box.querySelectorAll('a')] : [];
  const rect = n => { const b = n.getBoundingClientRect();
                      return [Math.round(b.left), Math.round(b.right),
                              Math.round(b.height)]; };
  const offerHtml = offer.cloneNode(true);
  return {
    box: !!box,
    slot: box ? box.getAttribute('data-slot') : '',
    head: box ? (box.querySelector('.ai-rsoc-head') || {}).textContent : '',
    kicker: box ? (box.querySelector('.ai-rsoc-kicker') || {}).textContent
      : '',
    sub: box ? (box.querySelector('.ai-rsoc-sub') || {}).textContent : '',
    card: box ? (() => { const cs = getComputedStyle(box);
      return [cs.backgroundColor, cs.borderTopWidth, cs.borderTopColor,
              cs.borderTopLeftRadius, cs.paddingTop]; })() : null,
    headStyle: box ? (() => { const cs = getComputedStyle(
      box.querySelector('.ai-rsoc-head'));
      return [cs.fontSize, cs.fontWeight, cs.fontFamily.indexOf(
        'Space Grotesk') !== -1]; })() : null,
    gap: Math.round(root.querySelector('.ai-offer-under')
      .getBoundingClientRect().top - pay.getBoundingClientRect().bottom),
    holder: (() => { const x = offer.querySelector('.xp');
      return x ? Math.round(x.getBoundingClientRect().height) : 0; })(),
    overlaps: (() => { const out = [];
      const sets = [[...root.children],
                    box ? [...box.children] : [], [...offer.children]];
      for (const set of sets) {
        const shown = set.filter(n => n.offsetParent !== null
          && n.getBoundingClientRect().height > 0);
        for (let i = 0; i + 1 < shown.length; i++) {
          const a = shown[i].getBoundingClientRect();
          const b = shown[i + 1].getBoundingClientRect();
          if (b.top < a.bottom - 0.5) out.push(shown[i].className + ' / '
                                               + shown[i + 1].className);
        }
      }
      for (const n of root.querySelectorAll('*')) {
        const b = n.getBoundingClientRect();
        if (b.width && (b.left < -0.5 || b.right > innerWidth + 0.5)) {
          out.push('off screen: ' + n.className);
        }
      }
      return out; })(),
    score: (root.querySelector('.ai-ring-n') || {}).textContent || '',
    note: box ? (box.querySelector('.ai-rsoc-note') || {}).textContent : '',
    links: links.map(a => ({
      href: a.getAttribute('href'),
      text: a.querySelector('.ai-rsoc-text').textContent,
      tag: (a.querySelector('.ai-rsoc-tag') || {}).textContent || '',
      arrow: a.querySelectorAll('svg').length, target: a.target,
      rel: a.rel, key: a.getAttribute('data-article'), rect: rect(a),
      weight: getComputedStyle(a).backgroundColor,
      inOffer: offer.contains(a), afterPay: after(pay, a),
      afterConsent: consent.hidden || after(consent, a),
      afterOffer: after(offer, a)
    })),
    payIn: offer.contains(pay), offerRect: rect(offer),
    // The consent box exactly as the page has it: where it is, whether it
    // is shown, whether it is ticked, and which side of the button it is on.
    consent: [offer.contains(consent), consent.hidden, tick.checked,
              after(consent, pay), consent.className],
    payBg: getComputedStyle(pay).backgroundColor,
    payDisabled: pay.disabled, payText: pay.textContent,
    offer: offerHtml.outerHTML,
    order: [...root.children].map(c => c.className.split(' ')[0]),
    sticky: [...document.querySelectorAll(
      '.sticky-cta a, #sticky-cta a, .sticky a')].length,
    vw: innerWidth, sw: document.documentElement.scrollWidth,
    anchorsOutside: [...document.querySelectorAll('a.ai-rsoc-link')]
      .filter(a => !box || !box.contains(a)).length
  };
}"""


def arrive(browser, query, size=(390, 844)):
    ctx = browser.new_context(viewport={"width": size[0], "height": size[1]},
                              is_mobile=True, has_touch=True)
    # Nothing leaves the machine, the partner's pages included.
    ctx.route(lambda url: not url.startswith(BASE), lambda r: r.abort())
    page = ctx.new_page()
    errors = []
    page.on("pageerror", lambda e: errors.append(str(e)))
    page.goto(BASE + "/ai-navigator" + query)
    return ctx, page, errors


def wait_result(page):
    page.wait_for_selector("#result-module .ai-offer", timeout=30000)
    page.wait_for_timeout(900)


def main():
    server = Server(("127.0.0.1", PORT), Handler)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    want_tail = "?fbclid=AbC_123-x&ad_id=111&asid=222"

    with sync_playwright() as pw:
        browser = pw.chromium.launch(executable_path=CHROME)

        print("\n--- 1. all three identifiers, a reload, a bare URL ---")
        del events[:]
        ctx, page, errors = arrive(browser, want_tail)
        first = advance(page, until="time")
        check("the walk reaches the hours step", first[-1:] == ["time"],
              first)
        check("the three are held once the config is in",
              held(page) == {"fbclid": "AbC_123-x", "ad_id": "111",
                             "asid": "222"}, held(page))
        page.reload()
        page.wait_for_timeout(800)
        check("  and still held after a reload",
              held(page) == {"fbclid": "AbC_123-x", "ad_id": "111",
                             "asid": "222"}, held(page))
        # Harder than a reload, which keeps the query: the same tab arriving
        # again on a URL that carries none of them.
        page.goto(BASE + "/ai-navigator")
        page.wait_for_timeout(800)
        check("  and after arriving again on a bare URL",
              held(page) == {"fbclid": "AbC_123-x", "ad_id": "111",
                             "asid": "222"}, held(page))
        advance(page)
        wait_result(page)
        got = page.evaluate(PAGE)
        check("the result draws the block, in the below-paywall slot",
              got["box"] and got["slot"] == "below_paywall", got["slot"])
        check("two anchors: the skill's article, then the zone's",
              [l["key"] for l in got["links"]] == [SKILL, ZONE],
              [l["key"] for l in got["links"]])
        for link in got["links"]:
            key = link["key"]
            check("  %s: href is the config link and the three" % key,
                  link["href"] == ARTICLES[key]["link"] + want_tail,
                  link["href"][-60:])
            check("  %s: an arrow, and the tag that says why it was picked"
                  % key, link["arrow"] == 1 and link["tag"] == (
                      "PICKED FOR YOUR SKILL: Design" if key == SKILL else
                      "PICKED FOR WHERE YOU HAVE THE MOST ROOM: "
                      "Business sense"), link["tag"])
            check("  %s: the config's label, a new tab, noopener" % key,
                  link["text"] == ARTICLES[key]["label"]
                  and link["target"] == "_blank"
                  and link["rel"] == "noopener",
                  [link["text"], link["target"], link["rel"]])
            check("  %s: below the offer, the consent box and the button"
                  % key, link["afterOffer"] and link["afterPay"]
                  and link["afterConsent"] and not link["inOffer"])
            check("  %s: full width of its card, 68px or more, a light fill"
                  % key, link["rect"][2] >= 68
                  # The whole inner width of its card, which is the offer
                  # card's width less the padding every card here has.
                  and link["rect"][0] == got["vw"] - link["rect"][1]
                  and link["rect"][1] - link["rect"][0]
                  >= got["offerRect"][1] - got["offerRect"][0] - 48
                  and link["weight"] == "rgb(242, 245, 247)"
                  and got["payBg"] == "rgb(200, 245, 59)",
                  [link["rect"], link["weight"], got["payBg"]])
        check("the kicker, headline, line and note are the config's",
              got["kicker"] == RSOC["kicker"] and got["head"] == RSOC["head"]
              and got["sub"] == RSOC["sub"] and got["note"] == RSOC["note"],
              [got["kicker"], got["head"], got["sub"], got["note"]])
        check("  a card of its own: #151B23, 2px #F2F5F7, radius 18, pad 18",
              got["card"] == ["rgb(21, 27, 35)", "2px", "rgb(242, 245, 247)",
                              "18px", "18px"]
              and got["headStyle"] == ["26px", "700", True],
              [got["card"], got["headStyle"]])
        check("  nothing overlaps, nothing is off the screen",
              not got["overlaps"], got["overlaps"])
        check("  no empty holder in the offer card: under 16px below the "
              "button", 0 <= got["gap"] < 16 and got["holder"] == 0,
              [got["gap"], got["holder"]])
        check("no article link anywhere else on the page",
              got["anchorsOutside"] == 0 and got["sticky"] == 0)
        check("no horizontal scroll", got["sw"] <= got["vw"], got["sw"])
        check("the guides card is right under the offer, above what unlocks",
              got["order"] == ["ai-profile", "ai-scorecard", "ai-offer",
                               "ai-rsoc", "ai-unlock", "ai-divider",
                               "ai-foot"], got["order"])
        check("the pay button is in the offer card, above the block",
              got["payIn"] and all(l["afterPay"] for l in got["links"]))
        with_block = got

        before = len(events)
        named = [e.get("event") for e in events]
        check("no article_tap before a tap", "article_tap" not in named)
        check("the identifiers are on no tracking event",
              not [e for e in events
                   if "ad_id" in e or "asid" in e
                   or "111" in json.dumps(e.get("extra") or {})])
        with ctx.expect_page() as popup:
            page.locator(".ai-rsoc-link").nth(1).click()
        popup.value.close()
        page.wait_for_timeout(700)
        taps = [e for e in events[before:] if e.get("event") == "article_tap"]
        check("a tap posts one article_tap",
              len(taps) == 1, [e.get("event") for e in events[before:]])
        check("  with exactly the article and the slot",
              taps and taps[0].get("extra")
              == {"article": ZONE, "slot": "below_paywall"},
              taps and taps[0].get("extra"))
        check("  and neither the link nor an identifier",
              taps and "222" not in json.dumps(taps[0])
              and "http" not in json.dumps(taps[0]))
        check("the page it left is still the result page",
              page.evaluate("() => !!document.querySelector("
                            "'#result-module .ai-offer')"))
        check("no script errors", not errors, errors)
        ctx.close()

        print("\n--- 2. no fbclid ---")
        ctx, page, errors = arrive(browser, "?ad_id=111&asid=222&subid=s1")
        advance(page)
        wait_result(page)
        got = page.evaluate(PAGE)
        check("no block and no article link in the DOM",
              not got["box"] and got["anchorsOutside"] == 0
              and "ai-rsoc" not in got["order"], got["order"])
        check("the offer is followed by what it unlocks, with no card",
              got["order"] == ["ai-profile", "ai-scorecard", "ai-offer",
                               "ai-unlock", "ai-divider", "ai-foot"],
              got["order"])
        check("the offer card is the same markup with and without the block",
              got["offer"] == with_block["offer"])
        check("  and so are the consent box, its place and the pay button",
              got["consent"] == with_block["consent"]
              and got["payIn"] and with_block["payIn"]
              and got["payDisabled"] == with_block["payDisabled"]
              and got["payText"] == with_block["payText"],
              [got["consent"], with_block["consent"]])
        check("no script errors", not errors, errors)
        ctx.close()

        print("\n--- 3. ad_id left as an unresolved macro ---")
        ctx, page, errors = arrive(
            browser, "?fbclid=AbC_123-x&ad_id={{ad.id}}&asid=222")
        advance(page)
        wait_result(page)
        got = page.evaluate(PAGE)
        check("the macro is not held", held(page)
              == {"fbclid": "AbC_123-x", "asid": "222"}, held(page))
        check("two anchors, each carrying fbclid and asid only",
              len(got["links"]) == 2 and all(
                  l["href"] == ARTICLES[l["key"]]["link"]
                  + "?fbclid=AbC_123-x&asid=222" for l in got["links"]),
              [l["href"][-40:] for l in got["links"]])
        check("no script errors", not errors, errors)
        ctx.close()

        print("\n--- 4. always two guides: level runs, both screen sizes ---")
        global MISSES
        normal = MISSES
        ALL_SCORED = set(s["id"] for s in STEPS if "why" in s)
        for name, misses, score, size in (
                ("nothing right", ALL_SCORED, "0/8", (390, 844)),
                ("everything right", set(), "8/8", (360, 640))):
            MISSES = misses
            ctx, page, errors = arrive(browser, want_tail, size)
            advance(page)
            wait_result(page)
            got = page.evaluate(PAGE)
            check("%s (%s) at %dx%d: still two anchors" % (
                name, score, size[0], size[1]),
                got["score"] == score
                and [l["key"] for l in got["links"]] == [SKILL, "spa"],
                [got["score"], [l["key"] for l in got["links"]]])
            check("  the tie is broken to business sense, and says so",
                  got["links"][-1]["tag"] == "PICKED FOR WHERE YOU HAVE THE "
                  "MOST ROOM: Business sense"
                  and got["links"][-1]["href"]
                  == ARTICLES["spa"]["link"] + want_tail)
            check("  each 68px or more, inside the card, nothing overlapping",
                  all(l["rect"][2] >= 68 and l["rect"][0] >= 0
                      and l["rect"][1] <= got["vw"] for l in got["links"])
                  and not got["overlaps"] and got["sw"] <= got["vw"],
                  [got["overlaps"], [l["rect"] for l in got["links"]]])
            check("  the gap under the pay button is under 16px",
                  0 <= got["gap"] < 16 and got["holder"] == 0,
                  [got["gap"], got["holder"]])
            check("  the pay button and the consent state are what they were",
                  got["payIn"] and got["consent"] == with_block["consent"]
                  and got["payDisabled"] == with_block["payDisabled"]
                  and got["payText"] == with_block["payText"])
            # The other state engine.js can leave the holder in: a wallet
            # button is the live control and the pay button is kept, unseen.
            wallet = page.evaluate("""() => {
              const offer = document.querySelector('.ai-offer');
              const slot = offer.querySelector('.xp__slot');
              const pay = document.querySelector('#pay-button');
              if (!slot) return null;
              slot.classList.remove('xp__off');
              const mount = slot.querySelector('.xp__mount');
              mount.classList.remove('xp__off');
              mount.style.height = '55px';
              const ghost = slot.querySelector('.xp__ghost');
              if (ghost) ghost.remove();
              pay.classList.add('xp__off');
              const under = offer.querySelector('.ai-offer-under')
                .getBoundingClientRect();
              const b = mount.getBoundingClientRect();
              return { shown: mount.offsetParent !== null,
                       height: Math.round(b.height),
                       gap: Math.round(under.top - b.bottom) }; }""")
            check("  with a wallet button live: it shows, and no gap under it",
                  wallet and wallet["shown"] and wallet["height"] == 55
                  and 0 <= wallet["gap"] < 16, wallet)
            check("  no script errors", not errors, errors)
            ctx.close()
        MISSES = normal

        browser.close()
    server.shutdown()

    print("\n%d checks, %d failed" % (checks[0], len(fails)))
    for line in fails:
        print("  FAIL " + line[:400])
    return 1 if fails else 0


if __name__ == "__main__":
    sys.exit(main())
