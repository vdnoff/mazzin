#!/usr/bin/env python3
"""The RSOC quiz in a real browser: views, events and the identifiers.

/benefits is served from static/rsoc.html with the test config
(tests/fixtures/rsoc_test.json: the real config with a fake
https://example.test/<key> link on every article), so the passthrough can be
held to /loans's rules before the partner's links exist. One scenario uses
the real config, whose links are all empty, for the pre-feed page.

  1. Arrival with fbclid, ad_id and asid: they are held from the first view,
     through a reload, back and forward, and the result shows three anchors
     whose hrefs are the articles the answers pick plus the three ids, in
     that order and nothing else. A reload on the result and Edit answers
     and back keep them. A tap opens a new tab and posts one offer_tap.
  2. A second arrival on a bare /benefits in the same tab keeps all of it.
  3. No fbclid: no anchor at all, and the line that says so.
  4. An unresolved macro is dropped; an unresolved fbclid means no anchors.
  5. No identifier reaches any /api request, in any scenario.
  6. Every step posts its `step` event once, quiz_start and result_view
     once, whatever is reloaded, edited or walked again.
  7. The real, pre-feed config: muted rows that are not links, the "not
     available yet" line, and a tap still counted.
  8. At 390 and 360 wide: no horizontal scroll, every target 44px or more.

Nothing leaves the machine: every request off 127.0.0.1 is aborted.

    python3 tests/test_rsoc_walk.py
"""
import http.server
import json
import os
import socketserver
import sys
import threading

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, REPO)

from playwright.sync_api import sync_playwright            # noqa: E402

PORT = 8891
CHROME = "/opt/pw-browsers/chromium-1194/chrome-linux/chrome"
BASE = "http://127.0.0.1:%d" % PORT


def read(rel):
    with open(os.path.join(REPO, rel), encoding="utf-8") as fh:
        return fh.read()


SHELL = read("static/rsoc.html")
FIXTURE = read("tests/fixtures/rsoc_test.json")
REAL = read("funnels/rsoc/benefits.json")
CFG = json.loads(FIXTURE)
ARTICLES = CFG["articles"]
STEPS = CFG["steps"]

FBCLID = "AbC_123-x"
AD_ID = "120211111111"
ASID = "120222222222"
FULL = "?fbclid=%s&ad_id=%s&asid=%s" % (FBCLID, AD_ID, ASID)
HELD = {"fbclid": FBCLID, "ad_id": AD_ID, "asid": ASID}
TAIL = "?fbclid=%s&ad_id=%s&asid=%s" % (FBCLID, AD_ID, ASID)

posts = []
served = {"config": FIXTURE}
fails = []
checks = [0]


def check(label, ok, detail=""):
    checks[0] += 1
    if not ok:
        fails.append("%s %s" % (label, detail))
    print("  %-68s %s%s" % (label, "ok" if ok else "FAIL",
                            ("  " + str(detail)[:400]) if not ok else ""))


class Handler(http.server.SimpleHTTPRequestHandler):
    def __init__(self, *a, **kw):
        super().__init__(*a, directory=REPO, **kw)

    def log_message(self, *a):
        pass

    def _send(self, body, kind):
        raw = body.encode("utf-8")
        self.send_response(200)
        self.send_header("Content-Type", kind)
        self.send_header("Content-Length", str(len(raw)))
        self.end_headers()
        self.wfile.write(raw)

    def do_GET(self):
        path = self.path.split("?")[0]
        if path == "/benefits":
            return self._send(SHELL.replace("__RSOC_SLUG__", "benefits"),
                              "text/html")
        if path == "/static/funnels/rsoc/benefits.json":
            return self._send(served["config"], "application/json")
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
    ctx.route(lambda url: not url.startswith(BASE), lambda r: r.abort())
    page = ctx.new_page()
    errors = []
    page.on("pageerror", lambda e: errors.append(str(e)))
    page.goto(BASE + "/benefits" + query)
    page.wait_for_selector("#choices-need button")
    page.wait_for_timeout(200)
    return ctx, page, errors


def view(page):
    return page.evaluate(
        "() => [...document.querySelectorAll('.view')]"
        ".filter(s => !s.hidden).map(s => s.dataset.view).join(',')")


def held(page):
    return page.evaluate(
        "() => JSON.parse(sessionStorage.getItem('mazzin_pass_benefits')"
        " || 'null')")


def tap(page, selector):
    page.locator(selector).click()
    page.wait_for_timeout(200)


def choose(page, step, value):
    tap(page, '#choices-%s button[data-value="%s"]' % (step, value))


def to_result(page, need="medical", household="solo", income="i2",
              situation="employed", state="TX"):
    choose(page, "need", need)
    choose(page, "household", household)
    choose(page, "income", income)
    choose(page, "situation", situation)
    page.select_option("#state", state)
    tap(page, "#go-result")


def anchors(page):
    return page.evaluate(
        "() => [...document.querySelectorAll('#result-rows a')].map(a => ["
        "a.dataset.article, a.getAttribute('href'), a.target, a.rel, "
        "a.textContent])")


def events(since=0):
    out = []
    for path, raw in posts[since:]:
        if path == "/api/rsoc/benefits/event":
            out.append(json.loads(raw))
    return out


def leaks(since=0):
    """Any request to our server that carries an identifier or its value."""
    bad = []
    for path, raw in posts[since:]:
        text = path + raw
        if any(v in text for v in (FBCLID, AD_ID, ASID, "fbclid", "ad_id",
                                   "asid")):
            bad.append((path, raw[:120]))
    return bad


def want_hrefs(keys, tail=TAIL):
    return [[k, ARTICLES[k]["link"] + tail, "_blank", "noopener",
             ARTICLES[k]["label"]] for k in keys]


TILES = """() => Object.fromEntries([...document.querySelectorAll(
  '.view:not([hidden]) .tiles')]
  .map(list => [list.id.replace('choices-', ''),
    [...list.querySelectorAll('.tile')].map(t => {
      const b = t.getBoundingClientRect();
      const lb = t.querySelector('.tile-label').getBoundingClientRect();
      const wrap = t.querySelector('.ico-wrap');
      return { wrap: !!wrap, svg: !!t.querySelector('.ico-wrap svg.ico'),
               hidden: t.querySelector('svg') ? t.querySelector('svg')
                 .getAttribute('aria-hidden') : null,
               text: wrap ? wrap.textContent : '',
               span: getComputedStyle(t).gridColumnStart + '/'
                 + getComputedStyle(t).gridColumnEnd,
               w: Math.round(b.width), h: Math.round(b.height),
               inside: lb.left >= b.left - 0.5 && lb.right <= b.right + 0.5,
               cls: t.className }; })]))"""


def main():
    server = Server(("127.0.0.1", PORT), Handler)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    with sync_playwright() as pw:
        browser = pw.chromium.launch(executable_path=CHROME)

        print("\n--- 1. all three identifiers, a reload, back and forward ---")
        ctx, page, errors = arrive(browser, FULL + "&subid=s1")
        check("the first screen is step 1: the question as h1, four tiles",
              view(page) == "need"
              and page.locator("#view-need h1").text_content()
              == STEPS[0]["question"]
              and page.locator("#view-need .lede, #view-need h2").count() == 0
              and page.locator("#choices-need .tile").count() == 4)
        check("  the footnote under the tiles on step 1, and on no other step",
              page.locator(".footnote").count() == 1
              and page.locator("#view-need .tiles + .footnote").text_content()
              == STEPS[0]["footnote"])
        check("held on the first view, before any tap", held(page) == HELD,
              held(page))
        check("no event before the first tap", events() == [], events())
        choose(page, "need", "medical")
        check("a tile tap moves on at once", view(page) == "household")
        page.reload()
        page.wait_for_timeout(400)
        check("a reload in the middle keeps the view and the three",
              view(page) == "household" and held(page) == HELD,
              [view(page), held(page)])
        choose(page, "household", "solo")
        page.go_back()
        page.wait_for_timeout(300)
        back_view = view(page)
        page.go_forward()
        page.wait_for_timeout(300)
        check("back and forward walk the views and keep the three",
              back_view == "household" and view(page) == "income"
              and held(page) == HELD, [back_view, view(page)])
        check("  the income helper is under its tiles",
              page.locator("#view-income .helper").text_content()
              == STEPS[2]["helper"])
        choose(page, "income", "i2")
        choose(page, "situation", "employed")
        check("step 4 waits for the state: the button stays off",
              view(page) == "situation"
              and page.locator("#go-result").is_disabled())
        page.select_option("#state", "TX")
        check("  and comes on with both", not page.locator(
            "#go-result").is_disabled())
        tap(page, "#go-result")
        check("the result view, with three anchors in the answers' order",
              view(page) == "result"
              and anchors(page) == want_hrefs(
                  ["medicaid", "debt_relief", "car_insurance"]),
              anchors(page))
        chips = page.evaluate("() => [...document.querySelectorAll("
                              "'#result-chips li')].map(l => l.textContent)")
        check("  the chips: need, household, income, state",
              chips == ["Medical costs", "Just me or my partner",
                        "$1,000 – $2,000", "Texas"], chips)
        check("  the Sponsored pill and the disclaimer, no pre-feed line",
              page.locator("#result-rows .pill").text_content() == "Sponsored"
              and CFG["result"]["prefeed_line"] not in page.locator(
                  "#view-result").inner_text()
              and page.locator(".note.disclaimer").text_content()
              == CFG["result"]["disclaimer"])
        check("  and Edit answers in the header",
              page.locator("#top-link").is_visible()
              and page.locator("#top-link").text_content() == "Edit answers")
        page.reload()
        page.wait_for_timeout(400)
        check("a reload on the result keeps the three hrefs",
              view(page) == "result" and anchors(page) == want_hrefs(
                  ["medicaid", "debt_relief", "car_insurance"]))
        tap(page, "#top-link")
        check("Edit answers goes to step 4", view(page) == "situation",
              view(page))
        choose(page, "situation", "retired")
        tap(page, "#go-result")
        check("a changed answer is a changed row; the ids are still there",
              anchors(page) == want_hrefs(
                  ["medicaid", "medicare", "car_insurance"]), anchors(page))
        before = len(posts)
        with ctx.expect_page() as popup:
            page.locator('#result-rows a[data-article="medicare"]').click()
        opened = popup.value
        opened_url = opened.url
        opened.close()
        page.wait_for_timeout(400)
        taps = [e for e in events(before) if e["event"] == "offer_tap"]
        check("a tap opens a new tab and posts one offer_tap, slot the key",
              len(taps) == 1 and taps[0]["extra"] == {"slot": "medicare"}
              and opened_url in (ARTICLES["medicare"]["link"] + TAIL,
                                 "about:blank")
              or opened_url.startswith("chrome-error"),
              [taps, opened_url])
        check("  the page it left is still the result", view(page) == "result")

        print("\n--- 2. a second arrival on a bare URL, same tab ---")
        page.goto(BASE + "/benefits")
        page.wait_for_timeout(500)
        check("it resumes on the result, the three still held",
              view(page) == "result" and held(page) == HELD,
              [view(page), held(page)])
        check("  and the anchors still carry them",
              anchors(page) == want_hrefs(
                  ["medicaid", "medicare", "car_insurance"]))

        print("\n--- 6. events, for the whole of scenarios 1 and 2 ---")
        evs = events()
        names = [(e["event"], e.get("step"), json.dumps(e.get("extra")))
                 for e in evs]
        # quiz_start and step 1 leave on the same tap, as two beacons, and
        # either can land first: the pair is checked, not its order.
        check("quiz_start once, on the first tap, beside step 1",
              [n for n in names if n[0] == "quiz_start"]
              == [("quiz_start", None, "null")]
              and {names[0][0], names[1][0]} == {"quiz_start", "step"},
              names[:2])
        check("each step's event once, numbered, carrying its id only",
              [n for n in names if n[0] == "step"]
              == [("step", i + 1, json.dumps({"step": s["id"]}))
                  for i, s in enumerate(STEPS)], names)
        check("result_view once, through a reload and an edit",
              [n[0] for n in names].count("result_view") == 1)
        check("every event carries the subid and the session, no answer",
              all(e.get("subid") == "s1" and len(e["session_id"]) == 36
                  and set(e) <= {"event", "extra", "session_id", "step",
                                 "subid"} for e in evs)
              and not [e for e in evs if "medical" in json.dumps(e)
                       or "TX" in json.dumps(e)], evs[:2])
        check("no script error", not errors, errors)
        ctx.close()

        print("\n--- 3. no fbclid ---")
        mark = len(posts)
        ctx, page, errors = arrive(browser, "?ad_id=%s&asid=%s" % (AD_ID,
                                                                    ASID))
        to_result(page)
        check("the result, with no anchor at all",
              view(page) == "result" and anchors(page) == []
              and page.locator("#result-rows a, #result-rows .guide").count()
              == 0)
        check("  and the line that says so",
              page.locator("#result-rows .guides-none").text_content()
              == CFG["result"]["no_id_line"])
        check("  the other two are held all the same",
              held(page) == {"ad_id": AD_ID, "asid": ASID}, held(page))
        ctx.close()

        print("\n--- 4. unresolved macros ---")
        ctx, page, errors = arrive(
            browser, "?fbclid=%s&ad_id={{ad.id}}&asid=%s" % (FBCLID, ASID))
        to_result(page, need="food", household="kids")
        check("a macro ad_id is dropped; the link carries the other two",
              held(page) == {"fbclid": FBCLID, "asid": ASID}
              and anchors(page) == want_hrefs(
                  ["snap", "wic_chip", "car_insurance"],
                  "?fbclid=%s&asid=%s" % (FBCLID, ASID)), anchors(page))
        ctx.close()
        ctx, page, errors = arrive(browser, "?fbclid={{fbclid}}&ad_id=%s"
                                   % AD_ID)
        to_result(page)
        check("a macro fbclid is no fbclid: no anchors",
              anchors(page) == [] and held(page) == {"ad_id": AD_ID},
              [anchors(page), held(page)])
        ctx.close()

        print("\n--- 5. the identifiers never reach our server ---")
        check("no /api request carried an identifier, in any scenario",
              not leaks(), leaks()[:3])
        check("  and every request was an event post",
              {p for p, _ in posts} == {"/api/rsoc/benefits/event"},
              {p for p, _ in posts})

        print("\n--- 7. the real config: pre-feed ---")
        served["config"] = REAL
        mark = len(posts)
        ctx, page, errors = arrive(browser, FULL)
        to_result(page)
        offs = page.evaluate(
            "() => [...document.querySelectorAll('#result-rows .guide')]"
            ".map(g => [g.tagName, g.dataset.article, g.getAttribute("
            "'aria-disabled'), g.hasAttribute('href'), "
            "getComputedStyle(g).color])")
        check("three rows, none of them a link, each aria-disabled and muted",
              [o[:4] for o in offs] == [
                  ["SPAN", k, "true", False]
                  for k in ("medicaid", "debt_relief", "car_insurance")]
              and all(o[4] == "rgb(86, 96, 122)" for o in offs), offs)
        lines = page.evaluate(
            "() => [...document.querySelectorAll('#result-rows .guides-none')]"
            ".map(p => p.textContent)")
        check("  the 'not available yet' line, once, under the card",
              lines == [json.loads(REAL)["result"]["prefeed_line"]], lines)
        check("  and no anchor anywhere in the result",
              page.locator("#view-result a[href^='https']").count() == 0)
        page.locator('#result-rows .guide[data-article="debt_relief"]').click()
        page.wait_for_timeout(300)
        taps = [e for e in events(mark) if e["event"] == "offer_tap"]
        check("a tap on a muted row still posts offer_tap, slot the key",
              len(taps) == 1 and taps[0]["extra"] == {"slot": "debt_relief"}
              and len(ctx.pages) == 1, taps)
        check("  and opens nothing", view(page) == "result")
        ctx.close()
        served["config"] = FIXTURE

        print("\n--- 7b. step 1's tiles above the fold, on load ---")
        for width, height in ((390, 844), (360, 780)):
            ctx, page, errors = arrive(browser, FULL, width=width,
                                       height=height)
            got = page.evaluate(
                "() => ({ y: scrollY, h: innerHeight, bottom: Math.round("
                "[...document.querySelectorAll('#choices-need .tile')][3]"
                ".getBoundingClientRect().bottom), lines: Math.round("
                "document.querySelector('#view-need h1').getBoundingClientRect()"
                ".height / parseFloat(getComputedStyle(document.querySelector("
                "'#view-need h1')).lineHeight)) })")
            check("%dx%d: all four need tiles visible with no scroll, h1 in "
                  "2 lines or fewer" % (width, height),
                  got["y"] == 0 and got["bottom"] <= got["h"]
                  and got["lines"] <= 2, got)
            ctx.close()

        print("\n--- 8. 390 and 360 wide ---")
        for width in (390, 360):
            ctx, page, errors = arrive(browser, FULL, width=width)
            bad = []
            tiles = {}
            for step, value in (("need", "utilities"), ("household",
                                                        "senior"),
                                ("income", "i1"), ("situation", None)):
                bad += page.evaluate(
                    "() => [document.documentElement.scrollWidth > innerWidth"
                    " ? 'scroll' : ''].filter(Boolean).concat("
                    "[...document.querySelectorAll('.view:not([hidden]) "
                    "button, .view:not([hidden]) select, .view:not([hidden]) "
                    "a, header a, header button')].filter(n => "
                    "n.offsetParent !== null && !n.closest('.consent'))"
                    ".filter(n => n.getBoundingClientRect().height < 44)"
                    ".map(n => n.className || n.tagName))")
                tiles.update(page.evaluate(TILES))
                if value:
                    choose(page, step, value)
            choose(page, "situation", "unable")
            page.select_option("#state", "CA")
            tap(page, "#go-result")
            bad += page.evaluate(
                "() => [document.documentElement.scrollWidth > innerWidth"
                " ? 'scroll' : ''].filter(Boolean).concat("
                "[...document.querySelectorAll('#view-result a, "
                "#view-result button, header button')].filter(n => "
                "n.offsetParent !== null)"
                ".filter(n => n.getBoundingClientRect().height < 44)"
                ".map(n => n.className || n.tagName))")
            # The tiles, measured on each step while it was on screen.
            check("%dpx: badge on every need and household tile, none on "
                  "income or situation" % width,
                  all(t["wrap"] for t in tiles["need"] + tiles["household"])
                  and not any(t["wrap"] for t in tiles["income"]
                              + tiles["situation"])
                  and [t["text"] for t in tiles["household"]]
                  == ["", "", "60+", ""]
                  and all(t["svg"] and t["hidden"] == "true" for t in
                          tiles["need"] + tiles["household"]
                          if not t["text"]), tiles["household"])
            sit = tiles["situation"]
            check("  the fifth situation tile spans both columns",
                  [t["span"] for t in sit] == ["auto/auto"] * 4
                  + ["1/-1"] and sit[4]["w"] > sit[0]["w"] * 1.9, sit)
            check("  every tile is 44px or more and holds its label",
                  all(t["h"] >= 44 and t["inside"]
                      for ts in tiles.values() for t in ts),
                  [t for ts in tiles.values() for t in ts
                   if t["h"] < 44 or not t["inside"]][:2])
            check("  badge tiles 132px tall or more, plain tiles 76px or more",
                  all(t["h"] >= (132 if t["wrap"] else 76)
                      for ts in tiles.values() for t in ts))
            check("%dpx: no horizontal scroll, every target 44px or more"
                  % width, not bad and anchors(page) == want_hrefs(
                      ["liheap", "medicare", "car_insurance"]), bad)
            check("  no script error", not errors, errors)
            ctx.close()
        browser.close()
    server.shutdown()

    print("\n%d checks, %d failed" % (checks[0], len(fails)))
    for line in fails:
        print("  FAIL " + line[:420])
    return 1 if fails else 0


if __name__ == "__main__":
    sys.exit(main())
