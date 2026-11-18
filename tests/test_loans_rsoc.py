#!/usr/bin/env python3
"""The partner-article links on /loans, in a real browser.

The summary view of the Loan Options funnel — the fifth and last — links out
to four of a partner's articles. The partner can only attribute a reader whose
ad click travels with them, so what is walked here is the whole trip an
identifier makes: on the landing URL, across five views, a reload, the
browser's back and forward and a second arrival on a bare URL, into the query
of every link.

Four arrivals, 390x844:

  1. fbclid, ad_id and asid on the URL. Four anchors on the summary view,
     each the link from loans.js plus exactly those three, in that order; the
     first two follow the purpose and the credit answer. A tap posts one
     `offer_tap` whose slot is the article's key. Browser back from the
     summary is step 3.
  2. the same tab, loading a bare /loans: the hrefs are unchanged. A session
     saved on the view that used to follow the summary resumes on it.
  3. no fbclid. No article anchor anywhere, and the "not available" line
     where the block was.
  4. ad_id left as the ad platform's unresolved macro. That key is dropped
     and the other two still travel.

Throughout, nothing posted to /api/loans/* carries an identifier, and nothing
leaves the machine: every request off 127.0.0.1 is aborted, the partner's
included. The summary is then measured at 390 and 360 pixels wide.

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


SUMMARY = """() => {
  const rect = n => { const b = n.getBoundingClientRect();
                      return [Math.round(b.left), Math.round(b.right),
                              Math.round(b.height), Math.round(b.top)]; };
  const shown = n => !!(n && n.offsetParent !== null);
  const v = document.querySelector('#view-options');
  const block = document.querySelector('#guides-block');
  const none = document.querySelector('#guides-none');
  const list = document.querySelector('#guides');
  const h1 = v.querySelector('h1');
  const rest = v.cloneNode(true);
  rest.querySelector('#guides-block').remove();
  rest.querySelector('#guides-none').remove();
  const order = [...v.children].filter(shown)
    .map(n => n.id || n.className.split(' ')[0]);
  return {
    block: shown(block), none: shown(none), noneText: none.textContent,
    label: block.querySelector('h2').textContent,
    head: (() => { const h = block.querySelector('h2');
                   const cs = getComputedStyle(h);
                   const b = h.getBoundingClientRect();
                   const prev = v.querySelector('#options-chips')
                     .getBoundingClientRect();
                   const next = block.querySelector('.lede')
                     .getBoundingClientRect();
                   return { tag: h.tagName, family: cs.fontFamily,
                            size: cs.fontSize, weight: cs.fontWeight,
                            lines: Math.round(b.height
                                              / parseFloat(cs.lineHeight)),
                            lineHeight: parseFloat(cs.lineHeight),
                            spacing: cs.letterSpacing, color: cs.color,
                            ink: getComputedStyle(h1).color,
                            above: Math.round(b.top - prev.bottom),
                            below: Math.round(next.top - b.bottom),
                            kids: h.children.length }; })(),
    pill: block.querySelector('.pill').textContent,
    pillBox: (() => { const p = block.querySelector('.pill')
                        .getBoundingClientRect();
                      const c = list.getBoundingClientRect();
                      return { gap: Math.round(p.top - c.bottom),
                               left: Math.round(p.left - c.left),
                               last: block.lastElementChild
                                 .contains(block.querySelector('.pill')),
                               blockOrder: [...block.children]
                                 .map(n => n.tagName) }; })(),
    lede: block.querySelector('.lede').textContent,
    links: [...document.querySelectorAll('#guides a')].map(a => ({
      href: a.getAttribute('href'), text: a.textContent, target: a.target,
      rel: a.rel, key: a.getAttribute('data-article'), rect: rect(a),
      label: rect(a.querySelector('span'))
    })),
    list: rect(list),
    note: v.querySelector('.note').textContent,
    foot: [...v.querySelectorAll('.foot-links a')]
      .map(a => [a.textContent, a.getAttribute('href')]),
    order: order, rest: rest.innerHTML,
    h1Lines: Math.round(h1.getBoundingClientRect().height
                        / parseFloat(getComputedStyle(h1).lineHeight)),
    offSite: [...document.querySelectorAll('a')]
      .map(a => a.getAttribute('href') || '')
      .filter(h => /^https?:/.test(h)).length,
    buttons: [...v.querySelectorAll('button')].length,
    topLink: document.querySelector('#top-link').textContent,
    vw: innerWidth, vh: innerHeight,
    sw: document.documentElement.scrollWidth
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
        before = len(posts)
        to_options(page, "building")
        page.wait_for_timeout(300)
        sent = [json.loads(p[1]).get("event") for p in posts[before:]
                if p[0] == "/api/loans/event"]
        check("the summary is the last view, and reports result_view once",
              view(page) == "options" and sent.count("result_view") == 1
              and "offer_tap" not in sent, sent)
        got = page.evaluate(SUMMARY)
        check("it shows the guides block, not the unavailable line",
              got["block"] and not got["none"])
        check("  under an h2 that stands alone: Your next step",
              got["label"] == "Your next step" and got["head"]["tag"] == "H2"
              and got["head"]["kids"] == 0, [got["label"], got["head"]])
        hd = got["head"]
        check("  Fraunces 600, 26px, 1.15, -0.02em, ink, on one line",
              "Fraunces" in hd["family"] and hd["size"] == "26px"
              and hd["weight"] == "600"
              and abs(hd["lineHeight"] - 29.9) < 0.11
              and abs(float(hd["spacing"][:-2]) + 0.52) < 0.011
              and hd["color"] == hd["ink"] and hd["lines"] == 1, hd)
        check("  28px above it and 6px below", hd["above"] == 28
              and hd["below"] == 6, [hd["above"], hd["below"]])
        check("  saying how the rows were picked",
              got["lede"] == "Picked from your answers.", got["lede"])
        pb = got["pillBox"]
        check("  heading, subline, card, then the Partner site pill",
              pb["blockOrder"] == ["H2", "P", "UL", "P"] and pb["last"]
              and got["pill"] == "Partner site", pb)
        check("  the pill is left-aligned, 12px under the card",
              pb["gap"] == 12 and pb["left"] == 0, pb)
        check("  in order: eyebrow, h1, chips, guides, note, footer",
              got["order"] == ["eyebrow", "options-title", "options-chips",
                               "guides-block", "note", "foot"], got["order"])
        check("  the note is the not-a-lender box, unchanged",
              got["note"] == "Mazzin is not a lender. We don't approve loans "
              "or check your credit. The guides open a partner site that "
              "shows ads, and we may earn money when you visit it.",
              got["note"])
        check("  the footer is Contact, Privacy, Terms",
              got["foot"] == [["Contact", "mailto:support@mazzin.com"],
                              ["Privacy", "/privacy"], ["Terms", "/terms"]],
              got["foot"])
        check("  no button on the view, and Edit answers in the header",
              got["buttons"] == 0 and got["topLink"] == "Edit answers",
              [got["buttons"], got["topLink"]])
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
              got["offSite"] == 4, got["offSite"])
        with_block = got
        first_hrefs = [l["href"] for l in got["links"]]

        page.reload()
        page.wait_for_timeout(400)
        got = page.evaluate(SUMMARY)
        check("a reload on the summary keeps the four hrefs",
              view(page) == "options"
              and [l["href"] for l in got["links"]] == first_hrefs)
        page.go_back()
        page.wait_for_timeout(300)
        back_view = view(page)
        check("browser back from the summary goes to step 3",
              back_view == "credit"
              and page.evaluate("() => document.querySelector('#top-label')"
                                ".textContent") == "Step 3 of 3", back_view)
        page.go_forward()
        page.wait_for_timeout(300)
        got = page.evaluate(SUMMARY)
        check("  and forward again to the summary and its four hrefs",
              view(page) == "options"
              and [l["href"] for l in got["links"]] == first_hrefs,
              view(page))
        tap(page, "#top-link")
        check("Edit answers goes to step 3 as well", view(page) == "credit",
              view(page))
        page.go_forward()
        page.wait_for_timeout(300)

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
        check("  the page it left is still the summary",
              view(page) == "options")
        check("no script errors", not errors, errors)

        print("\n--- 2. the same tab, a bare /loans ---")
        before = len(posts)
        page.goto(BASE + "/loans")
        page.wait_for_timeout(400)
        check("the three are still held", held(page) == HELD, held(page))
        check("the session resumes on the summary",
              view(page) == "options", view(page))
        got = page.evaluate(SUMMARY)
        check("the four hrefs are what they were",
              [l["href"] for l in got["links"]] == first_hrefs,
              [l["href"][-50:] for l in got["links"]])
        check("  and result_view is not sent a second time",
              not [p for p in posts[before:] if "result_view" in p[1]])
        # A different purpose and credit, to see the first two rows follow.
        page.evaluate("() => { const s = JSON.parse(sessionStorage.getItem("
                      "'mazzin_loans')); s.answers.purpose = 'debt'; "
                      "s.answers.credit = 'excellent'; sessionStorage.setItem("
                      "'mazzin_loans', JSON.stringify(s)); }")
        page.goto(BASE + "/loans?utm_source=fb")
        page.wait_for_timeout(400)
        got = page.evaluate(SUMMARY)
        check("other answers, other first two rows, the same identifiers",
              [l["href"] for l in got["links"]]
              == [ARTICLES[k]["link"] + FULL for k in
                  ("purpose_debt", "credit_excellent", "general_small",
                   "general_apr")], [l["key"] for l in got["links"]])
        # A tab that was left on the view that used to come after the
        # summary: its stored view and its history entry both name it.
        for label, how in (("a reload", "reload"), ("a new arrival", "goto")):
            page.evaluate(
                "() => { const s = JSON.parse(sessionStorage.getItem("
                "'mazzin_loans')); s.view = 'guides'; sessionStorage.setItem("
                "'mazzin_loans', JSON.stringify(s)); "
                "history.replaceState({v: 'guides', i: 5}, ''); }")
            if how == "reload":
                page.reload()
            else:
                page.goto(BASE + "/loans")
            page.wait_for_timeout(400)
            got = page.evaluate(SUMMARY)
            check("a session saved on the old guides view, %s: the summary"
                  % label, view(page) == "options" and len(got["links"]) == 4
                  and page.evaluate("() => history.state && history.state.v")
                  == "options", view(page))
        check("no script errors", not errors, errors)
        ctx.close()

        print("\n--- 3. a fresh visit with no fbclid ---")
        ctx, page, errors = arrive(
            browser, "?ad_id=%s&asid=%s&subid=s1" % (AD_ID, ASID))
        to_income(page, "medical")
        to_credit(page)
        to_options(page, "building")
        got = page.evaluate(SUMMARY)
        check("the summary has no guides block",
              view(page) == "options" and not got["block"])
        check("  and says guides are not available for this visit",
              got["none"] and got["noneText"]
              == "Guides are not available for this visit.", got["noneText"])
        check("  in the block's place: chips, the line, note, footer",
              got["order"] == ["eyebrow", "options-title", "options-chips",
                               "guides-none", "note", "foot"], got["order"])
        check("  nothing else on the view changed",
              got["rest"] == with_block["rest"]
              and got["note"] == with_block["note"]
              and got["foot"] == with_block["foot"])
        check("no article anchor anywhere in the DOM",
              got["offSite"] == 0 and not got["links"]
              and page.evaluate("() => document.querySelectorAll("
                                "'a.guide, a[target=_blank]').length") == 0)
        page.reload()
        page.wait_for_timeout(400)
        got = page.evaluate(SUMMARY)
        check("  nor after a reload", view(page) == "options"
              and got["offSite"] == 0 and got["none"])
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
        got = page.evaluate(SUMMARY)
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
        slots = [json.loads(p[1])["extra"]["slot"] for p in posts
                 if '"offer_tap"' in p[1]]
        check("every offer_tap names an article, never a button",
              slots == ["credit_building"], slots)

        print("\n--- 6. 390 and 360 wide ---")
        for width in (390, 360):
            ctx, page, errors = arrive(browser, FULL, width=width)
            to_income(page, "home")
            to_credit(page)
            to_options(page, "good")
            got = page.evaluate(SUMMARY)
            check("%d: no horizontal scroll" % width,
                  got["sw"] <= got["vw"] == width, [got["sw"], got["vw"]])
            check("%d: the heading fits on one line" % width,
                  got["head"]["lines"] == 1, got["head"])
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
                "() => [...document.querySelectorAll('#view-options a, "
                "#view-options button, .top a, .top button')]"
                ".filter(n => n.offsetParent !== null)"
                ".map(n => [n.textContent.trim().slice(0, 20), Math.round("
                "n.getBoundingClientRect().height)]).filter(x => x[1] < 44)")
            check("%d: nothing tappable on the view is under 44px" % width,
                  not small, small)
            first = got["links"][0]["rect"]
            print("      %d: h1 on %d lines, first article row top %dpx, "
                  "bottom %dpx of %d" % (width, got["h1Lines"], first[3],
                                         first[3] + first[2], got["vh"]))
            if width == 390:
                check("390: the h1 fits on two lines",
                      got["h1Lines"] <= 2, got["h1Lines"])
                check("390: the first article row is whole above the fold",
                      first[3] + first[2] <= got["vh"],
                      [first, got["vh"]])
            shot = os.environ.get("LOANS_SHOT")
            if shot:
                page.screenshot(path="%s-%d.png" % (shot, width))
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
