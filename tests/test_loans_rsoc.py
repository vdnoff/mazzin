#!/usr/bin/env python3
"""The partner-article links on /loans, in a real browser.

The last view of the Loan Options funnel links out to four of a partner's
articles. The partner can only attribute a reader whose ad click travels with
them, so what is walked here is the whole trip an identifier makes: on the
landing URL, across six views, a reload, the browser's back and forward and a
second arrival on a bare URL, into the query of every link.

Four arrivals, 390x844:

  1. fbclid, ad_id and asid on the URL. Four anchors on the last view, each
     the link from loans.js plus exactly those three, in that order; the
     first two follow the purpose and the credit answer. A tap posts one
     `offer_tap` whose slot is the article's key.
  2. the same tab, loading a bare /loans: the hrefs are unchanged.
  3. no fbclid. No article anchor anywhere, the "not available" line where
     the card was, and the last view cannot be reached.
  4. ad_id left as the ad platform's unresolved macro. That key is dropped
     and the other two still travel.

Throughout, nothing posted to /api/loans/* carries an identifier, and nothing
leaves the machine: every request off 127.0.0.1 is aborted, the partner's
included. The last view is then measured at 390 and 360 pixels wide.

    python3 tests/test_loans_rsoc.py
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

PORT = 8863
CHROME = "/opt/pw-browsers/chromium-1194/chrome-linux/chrome"
BASE = "http://127.0.0.1:%d" % PORT

with open(os.path.join(REPO, "static", "js", "loans.js"),
          encoding="utf-8") as fh:
    JS = fh.read()
ARTICLES = {key: {"label": label, "link": link} for key, label, link in
            re.findall(r'    "(\w+)": \{\n      label: "([^"\n]+)",\n'
                       r'      link: "([^"\n]+)"\n    \}', JS)}

FBCLID = "AbC_123-x"
AD_ID = "120211111111"
ASID = "120222222222"
FULL = "?fbclid=%s&ad_id=%s&asid=%s" % (FBCLID, AD_ID, ASID)
HELD = {"fbclid": FBCLID, "ad_id": AD_ID, "asid": ASID}

fails = []
checks = [0]


def check(label, ok, detail=""):
    checks[0] += 1
    if not ok:
        fails.append("%s %s" % (label, detail))
    print("  %-62s %s%s" % (label, "ok" if ok else "FAIL",
                            ("  " + str(detail)[:300]) if not ok else ""))


posts = []          # (path with query, raw body) of every POST to our API


class Handler(http.server.SimpleHTTPRequestHandler):
    """The page off disk, with what it posts recorded."""

    def __init__(self, *a, **kw):
        super().__init__(*a, directory=REPO, **kw)

    def log_message(self, *a):
        pass

    def do_GET(self):
        if self.path.split("?")[0] == "/loans":
            self.path = "/static/loans.html"
        return super().do_GET()

    def do_POST(self):
        raw = self.rfile.read(int(self.headers.get("content-length") or 0))
        posts.append((self.path, raw.decode("utf-8", "replace")))
        self.send_response(204)
        self.send_header("Content-Length", "0")
        self.end_headers()


class Server(socketserver.ThreadingMixIn, http.server.HTTPServer):
    allow_reuse_address = True
    daemon_threads = True


def arrive(browser, query, width=390, height=844):
    ctx = browser.new_context(viewport={"width": width, "height": height},
                              is_mobile=True, has_touch=True)
    # Nothing leaves the machine, the partner's pages included.
    ctx.route(lambda url: not url.startswith(BASE), lambda r: r.abort())
    page = ctx.new_page()
    errors = []
    page.on("pageerror", lambda e: errors.append(str(e)))
    page.goto(BASE + "/loans" + query)
    page.wait_for_timeout(300)
    return ctx, page, errors


def view(page):
    return page.evaluate(
        "() => [...document.querySelectorAll('.view')]"
        ".filter(s => !s.hidden).map(s => s.dataset.view).join(',')")


def held(page):
    return page.evaluate(
        "() => JSON.parse(sessionStorage.getItem('mazzin_pass_loans')"
        " || 'null')")


def tap(page, selector):
    page.locator(selector).click()
    page.wait_for_timeout(250)


def to_income(page, purpose):
    tap(page, "#go-compare")
    tap(page, '#purpose-tiles button[data-value="%s"]' % purpose)


def to_credit(page):
    tap(page, '#employment-toggles button[data-value="employed"]')
    page.select_option("#income", "2000_3000")
    tap(page, "#go-credit")


def to_options(page, credit):
    tap(page, '#credit-rows button[data-value="%s"]' % credit)
    page.select_option("#state", "TX")
    tap(page, "#go-options")


GUIDES = """() => {
  const rect = n => { const b = n.getBoundingClientRect();
                      return [Math.round(b.left), Math.round(b.right),
                              Math.round(b.height)]; };
  const list = document.querySelector('#guides');
  return {
    links: [...document.querySelectorAll('#guides a')].map(a => ({
      href: a.getAttribute('href'), text: a.textContent, target: a.target,
      rel: a.rel, key: a.getAttribute('data-article'), rect: rect(a),
      label: rect(a.querySelector('span'))
    })),
    list: rect(list),
    articleAnchors: [...document.querySelectorAll('a[href^="http"]')]
      .filter(a => !a.getAttribute('href').startsWith(location.origin)).length,
    vw: innerWidth, sw: document.documentElement.scrollWidth
  };
}"""

OPTIONS = """() => {
  const v = document.querySelector('#view-options');
  const card = document.querySelector('#partner-card');
  const none = document.querySelector('#guides-none');
  const shown = n => !!(n && n.offsetParent !== null);
  const rest = v.cloneNode(true);
  rest.querySelector('#partner-card').remove();
  rest.querySelector('#guides-none').remove();
  return {
    card: shown(card), none: shown(none), noneText: none.textContent,
    cardText: card.textContent.replace(/\\s+/g, ' ').trim(),
    row: [...card.querySelectorAll('.partner-row span')]
      .map(s => s.textContent),
    button: document.querySelector('#go-guides').textContent,
    buttonHeight: Math.round(document.querySelector('#go-guides')
      .getBoundingClientRect().height),
    note: v.querySelector('.note').textContent,
    rest: rest.innerHTML,
    anchors: [...document.querySelectorAll('a')]
      .map(a => a.getAttribute('href') || '')
      .filter(h => /^https?:/.test(h)).length,
    vw: innerWidth, sw: document.documentElement.scrollWidth
  };
}"""


def leaks(since=0):
    """Every post since `since` that names or carries an identifier."""
    words = ("fbclid", "ad_id", "asid", FBCLID, AD_ID, ASID, "http")
    return [p for p in posts[since:] if any(w in p[0] + p[1] for w in words)]


def main():
    server = Server(("127.0.0.1", PORT), Handler)
    threading.Thread(target=server.serve_forever, daemon=True).start()

    check("the twelve articles are read out of loans.js",
          len(ARTICLES) == 12, len(ARTICLES))

    with sync_playwright() as pw:
        browser = pw.chromium.launch(executable_path=CHROME)

        print("\n--- 1. all three identifiers, a reload, back and forward ---")
        ctx, page, errors = arrive(browser, FULL + "&subid=s1")
        check("held on the landing view", held(page) == HELD, held(page))
        to_income(page, "medical")
        check("the walk reaches the income view", view(page) == "income",
              view(page))
        page.reload()
        page.wait_for_timeout(400)
        check("a reload in the middle keeps the view and the three",
              view(page) == "income" and held(page) == HELD,
              [view(page), held(page)])
        to_credit(page)
        page.go_back()
        page.wait_for_timeout(300)
        back_view = view(page)
        page.go_forward()
        page.wait_for_timeout(300)
        check("browser back and forward walk the views",
              back_view == "income" and view(page) == "credit",
              [back_view, view(page)])
        to_options(page, "building")
        got = page.evaluate(OPTIONS)
        check("the options view shows the partner card",
              view(page) == "options" and got["card"] and not got["none"])
        check("  labelled Partner site / Shows ads",
              got["row"] == ["Partner site", "Shows ads"], got["row"])
        check("  with its heading, three rows and button",
              "Free guides matched to your answers" in got["cardText"]
              and "Picked from your loan purpose and credit range"
              in got["cardText"]
              and "Explain costs and what to compare" in got["cardText"]
              and "Open on evoseekly.com, a partner site" in got["cardText"]
              and got["button"] == "See my guides", got["cardText"])
        check("  the note says the guides open a partner site with ads",
              got["note"].endswith("The guides open a partner site that "
                                   "shows ads, and we may earn money when "
                                   "you visit it."), got["note"])
        check("  no article link on this view", got["anchors"] == 0)
        with_card = got
        before = len(posts)
        tap(page, "#go-guides")
        page.wait_for_timeout(300)
        cta = [json.loads(p[1]) for p in posts[before:]
               if p[0] == "/api/loans/event"]
        check("the button posts one offer_tap, slot options_cta",
              [e.get("extra") for e in cta if e.get("event") == "offer_tap"]
              == [{"slot": "options_cta"}], cta)
        check("  and opens the guides view", view(page) == "guides",
              view(page))
        page.go_back()
        page.wait_for_timeout(300)
        back_view = view(page)
        page.go_forward()
        page.wait_for_timeout(300)
        check("  back to the options and forward again",
              back_view == "options" and view(page) == "guides",
              [back_view, view(page)])

        got = page.evaluate(GUIDES)
        want_keys = ["purpose_medical", "credit_building", "general_small",
                     "general_apr"]
        check("four anchors: the purpose, the credit, the two general",
              [l["key"] for l in got["links"]] == want_keys,
              [l["key"] for l in got["links"]])
        for link in got["links"]:
            key = link["key"]
            check("  %s: href is the link and the three, in order" % key,
                  link["href"] == ARTICLES[key]["link"] + FULL,
                  link["href"][-70:])
            check("  %s: its label, a new tab, noopener" % key,
                  link["text"] == ARTICLES[key]["label"]
                  and link["target"] == "_blank" and link["rel"] == "noopener",
                  [link["text"], link["target"], link["rel"]])
        check("no other link off the site on the page",
              got["articleAnchors"] == 4, got["articleAnchors"])
        first_hrefs = [l["href"] for l in got["links"]]

        before = len(posts)
        with ctx.expect_page() as popup:
            page.locator('#guides a[data-article="credit_building"]').click()
        popup.value.close()
        page.wait_for_timeout(500)
        taps = [json.loads(p[1]) for p in posts[before:]
                if p[0] == "/api/loans/event"]
        check("a tap opens a new tab and posts one offer_tap",
              len(taps) == 1 and taps[0].get("event") == "offer_tap", taps)
        check("  whose slot is the article's key, and nothing else",
              taps and taps[0].get("extra") == {"slot": "credit_building"}
              and set(taps[0]) <= {"session_id", "event", "extra", "subid"},
              taps)
        check("  the page it left is still the guides view",
              view(page) == "guides")
        check("no script errors", not errors, errors)

        print("\n--- 2. the same tab, a bare /loans ---")
        page.goto(BASE + "/loans")
        page.wait_for_timeout(400)
        check("the three are still held", held(page) == HELD, held(page))
        check("the session resumes on the guides view",
              view(page) == "guides", view(page))
        got = page.evaluate(GUIDES)
        check("the four hrefs are what they were",
              [l["href"] for l in got["links"]] == first_hrefs,
              [l["href"][-50:] for l in got["links"]])
        # A different purpose and credit, to see the first two rows follow.
        page.evaluate("() => { const s = JSON.parse(sessionStorage.getItem("
                      "'mazzin_loans')); s.answers.purpose = 'debt'; "
                      "s.answers.credit = 'excellent'; sessionStorage.setItem("
                      "'mazzin_loans', JSON.stringify(s)); }")
        page.goto(BASE + "/loans?utm_source=fb")
        page.wait_for_timeout(400)
        got = page.evaluate(GUIDES)
        check("other answers, other first two rows, the same identifiers",
              [l["href"] for l in got["links"]]
              == [ARTICLES[k]["link"] + FULL for k in
                  ("purpose_debt", "credit_excellent", "general_small",
                   "general_apr")], [l["key"] for l in got["links"]])
        check("no script errors", not errors, errors)
        ctx.close()

        print("\n--- 3. a fresh visit with no fbclid ---")
        ctx, page, errors = arrive(
            browser, "?ad_id=%s&asid=%s&subid=s1" % (AD_ID, ASID))
        to_income(page, "medical")
        to_credit(page)
        to_options(page, "building")
        got = page.evaluate(OPTIONS)
        check("the options view has no partner card",
              view(page) == "options" and not got["card"])
        check("  and says guides are not available for this visit",
              got["none"] and got["noneText"]
              == "Guides are not available for this visit.", got["noneText"])
        check("  nothing else on the view changed",
              got["rest"] == with_card["rest"] and got["note"]
              == with_card["note"])
        check("no article anchor anywhere in the DOM",
              got["anchors"] == 0
              and page.evaluate("() => document.querySelectorAll("
                                "'#guides a, a.guide').length") == 0)
        # The last view cannot be reached: not by the history, not by a
        # stored view, not by a reload on either.
        page.evaluate("() => { history.pushState({v: 'guides', i: 5}, ''); "
                      "const s = JSON.parse(sessionStorage.getItem("
                      "'mazzin_loans')); s.view = 'guides'; "
                      "sessionStorage.setItem('mazzin_loans', "
                      "JSON.stringify(s)); }")
        page.reload()
        page.wait_for_timeout(400)
        check("the guides view is unreachable",
              view(page) == "options"
              and page.evaluate("() => document.querySelectorAll("
                                "'#guides a').length") == 0, view(page))
        check("no script errors", not errors, errors)
        ctx.close()

        print("\n--- 4. ad_id left as an unresolved macro ---")
        ctx, page, errors = arrive(
            browser, "?fbclid=%s&ad_id={{ad.id}}&asid=%s" % (FBCLID, ASID))
        check("the macro is not held",
              held(page) == {"fbclid": FBCLID, "asid": ASID}, held(page))
        to_income(page, "car")
        to_credit(page)
        to_options(page, "fair")
        tap(page, "#go-guides")
        got = page.evaluate(GUIDES)
        check("four anchors, each carrying fbclid and asid only",
              [l["href"] for l in got["links"]]
              == [ARTICLES[k]["link"] + "?fbclid=%s&asid=%s" % (FBCLID, ASID)
                  for k in ("purpose_car", "credit_fair", "general_small",
                            "general_apr")],
              [l["href"][-50:] for l in got["links"]])
        check("no script errors", not errors, errors)
        ctx.close()

        print("\n--- 5. what reached /api/loans/* ---")
        paths = {p[0] for p in posts}
        check("the page posted leads and events, and nothing else",
              paths == {"/api/loans/lead", "/api/loans/event"}, paths)
        check("three leads, one per walk",
              len([p for p in posts if p[0] == "/api/loans/lead"]) == 3)
        check("no request carried fbclid, ad_id, asid or a link",
              not leaks(), leaks()[:2])
        check("  while the attribution it is meant to carry did travel",
              any('"subid":"s1"' in p[1] for p in posts))

        print("\n--- 6. 390 and 360 wide ---")
        for width in (390, 360):
            ctx, page, errors = arrive(browser, FULL, width=width)
            to_income(page, "home")
            to_credit(page)
            to_options(page, "good")
            opt = page.evaluate(OPTIONS)
            check("%d: options view, no horizontal scroll, 44px button"
                  % width, opt["sw"] <= opt["vw"]
                  and opt["buttonHeight"] >= 44,
                  [opt["sw"], opt["vw"], opt["buttonHeight"]])
            tap(page, "#go-guides")
            got = page.evaluate(GUIDES)
            check("%d: guides view, no horizontal scroll" % width,
                  got["sw"] <= got["vw"] == width, [got["sw"], got["vw"]])
            check("%d: every row is a touch target of 44px or more" % width,
                  len(got["links"]) == 4
                  and all(l["rect"][2] >= 44 for l in got["links"]),
                  [l["rect"] for l in got["links"]])
            check("%d: every label sits inside its row" % width,
                  all(l["rect"][0] >= got["list"][0]
                      and l["rect"][1] <= got["list"][1]
                      and l["label"][0] >= l["rect"][0]
                      and l["label"][1] <= l["rect"][1] - 20
                      for l in got["links"]),
                  [[l["rect"], l["label"]] for l in got["links"]])
            small = page.evaluate(
                "() => [...document.querySelectorAll('#view-guides a, "
                "#view-guides button, .top a, .top button')]"
                ".filter(n => n.offsetParent !== null)"
                ".map(n => [n.textContent.trim().slice(0, 20), Math.round("
                "n.getBoundingClientRect().height)]).filter(x => x[1] < 44)")
            check("%d: nothing tappable on the view is under 44px" % width,
                  not small, small)
            shot = os.environ.get("LOANS_SHOT")
            if shot:
                page.screenshot(path="%s-%d.png" % (shot, width),
                                full_page=True)
            check("%d: no script errors" % width, not errors, errors)
            ctx.close()

        browser.close()
    server.shutdown()

    print("\n%d checks, %d failed" % (checks[0], len(fails)))
    for line in fails:
        print("  FAIL " + line[:400])
    return 1 if fails else 0


if __name__ == "__main__":
    sys.exit(main())
