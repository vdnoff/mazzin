#!/usr/bin/env python3
"""The article partner's Meta pixel on an RSOC quiz, in a real browser.

Meta's script is replaced by a local recorder, so every fbq call the page
makes can be read back; every other request off the machine is aborted.

The quiz sends what /loans sends, under the names its config gives:

  1. a load: init with the config's pixel id, then one PageView (standard);
  2. the result: one result event (custom, QuizComplete), once a session —
     not again on a reload, on Edit answers and back, on back and forward,
     or on a second arrival — and sent with or without an fbclid;
  3. a row tap: one tap event (custom, ArticleTap) on every tap, with the
     article's key and the quiz's slug and nothing else; the new tab opens;
     a muted pre-feed row counts the same way;
  4. nothing else, ever: no standard Lead or AddToCart, no ViewContent, no
     Purchase, and no answer, session id, subid or click id in any call;
  5. Meta's script blocked: nothing throws and the quiz works unchanged;
  6. the first view is painted while Meta's script is still on its way.

    python3 tests/test_rsoc_pixel.py
"""
import json
import os
import sys
import threading

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, REPO)
sys.path.insert(0, os.path.join(REPO, "tests"))

import test_rsoc_walk as walk                              # noqa: E402

from playwright.sync_api import sync_playwright            # noqa: E402

PORT = 8893
BASE = "http://127.0.0.1:%d" % PORT
walk.BASE = BASE
CFG = walk.CFG
PIXEL = CFG["pixel_id"]
RESULT = CFG["pixel_events"]["result"]["name"]
TAP = CFG["pixel_events"]["tap"]["name"]
META = "https://connect.facebook.net/en_US/fbevents.js"
FULL = walk.FULL + "&subid=sub-77"
METHOD = {"PageView": "trackSingle", RESULT: "trackSingleCustom",
          TAP: "trackSingleCustom"}
TRACKS = ("track", "trackCustom", "trackSingle", "trackSingleCustom")
NEVER = ("Lead", "AddToCart", "ViewContent", "Purchase")

fails = []
checks = [0]


def check(label, ok, detail=""):
    checks[0] += 1
    if not ok:
        fails.append("%s %s" % (label, detail))
    print("  %-68s %s%s" % (label, "ok" if ok else "FAIL",
                            ("  " + str(detail)[:400]) if not ok else ""))


FBEVENTS = """
(function () {
  var f = window.fbq;
  if (!f) return;
  function keep(args) {
    var all = [];
    try { all = JSON.parse(sessionStorage.getItem('__fbq') || '[]'); }
    catch (e) {}
    all.push(args);
    sessionStorage.setItem('__fbq', JSON.stringify(all));
  }
  f.callMethod = function () { keep([].slice.call(arguments)); };
  var q = f.queue || [];
  while (q.length) f.callMethod.apply(f, q.shift());
})();
"""


def arrive(browser, query, meta="stub"):
    ctx = browser.new_context(viewport={"width": 390, "height": 844},
                              is_mobile=True, has_touch=True)
    seen = {"off": [], "held": [], "errors": [], "console": []}

    def off_machine(route):
        url = route.request.url
        seen["off"].append(url)
        if url == META and meta == "stub":
            return route.fulfill(status=200, content_type="text/javascript",
                                 body=FBEVENTS)
        if url == META and meta == "hold":
            seen["held"].append(route)
            return None
        return route.abort()

    ctx.route(lambda url: not url.startswith(BASE), off_machine)
    page = ctx.new_page()
    page.on("pageerror", lambda e: seen["errors"].append(str(e)))
    page.on("console", lambda m: seen["console"].append(
        (m.type, m.text, (m.location or {}).get("url", ""))))
    page.goto(BASE + "/benefits" + query,
              wait_until="domcontentloaded" if meta == "hold" else "load")
    page.wait_for_selector("#choices-need button")
    page.wait_for_timeout(300)
    return ctx, page, seen


def fbq(page):
    return page.evaluate(
        "() => JSON.parse(sessionStorage.getItem('__fbq') || '[]')")


def names(calls):
    return [c[2] for c in calls if c[0] in TRACKS]


def methods_right(calls):
    return all(c[0] == METHOD.get(c[2]) for c in calls if c[0] in TRACKS)


def main():
    server = walk.Server(("127.0.0.1", PORT), walk.Handler)
    threading.Thread(target=server.serve_forever, daemon=True).start()

    with sync_playwright() as pw:
        browser = pw.chromium.launch(executable_path=walk.CHROME)

        print("\n--- 1. a load ---")
        ctx, page, seen = arrive(browser, FULL)
        calls = fbq(page)
        check("init with the config's pixel id, and nothing beside it",
              calls[:1] == [["init", PIXEL]], calls[:1])
        check("then one PageView, as a standard event to that pixel",
              calls == [["init", PIXEL], ["trackSingle", PIXEL, "PageView"]],
              calls)
        check("the only request off the machine is Meta's script",
              seen["off"] == [META], seen["off"])
        check("the landing URL still carries its fbclid",
              "fbclid=" + walk.FBCLID in page.url, page.url)

        print("\n--- 2. the result: one result event a session ---")
        walk.to_result(page)
        calls = fbq(page)
        check("exactly one %s, custom, with no parameters" % RESULT,
              names(calls) == ["PageView", RESULT]
              and calls[-1] == ["trackSingleCustom", PIXEL, RESULT], calls)
        page.reload()
        page.wait_for_timeout(500)
        check("a reload on the result: a PageView, no second %s" % RESULT,
              walk.view(page) == "result"
              and names(fbq(page)) == ["PageView", RESULT, "PageView"],
              names(fbq(page)))
        walk.tap(page, "#top-link")
        at = walk.view(page)
        walk.choose(page, "situation", "unable")
        walk.tap(page, "#go-result")
        check("Edit answers, a changed answer and back: still one",
              at == "situation" and walk.view(page) == "result"
              and names(fbq(page)).count(RESULT) == 1,
              [at, names(fbq(page))])
        page.go_back()
        page.wait_for_timeout(300)
        mid = walk.view(page)
        page.go_forward()
        page.wait_for_timeout(300)
        check("back and forward: still one",
              mid == "situation" and walk.view(page) == "result"
              and names(fbq(page)).count(RESULT) == 1, [mid, names(fbq(page))])
        page.goto(BASE + "/benefits")
        page.wait_for_timeout(500)
        check("a second arrival in the tab: a PageView, still one",
              walk.view(page) == "result"
              and names(fbq(page)) == ["PageView", RESULT, "PageView",
                                       "PageView"], names(fbq(page)))

        print("\n--- 3. a tap on a row ---")
        rows = walk.anchors(page)
        key, href = rows[1][0], rows[1][1]
        before = len(fbq(page))
        with ctx.expect_page() as popup:
            page.locator('#result-rows a[data-article="%s"]' % key).click()
        opened = popup.value.url
        popup.value.close()
        page.wait_for_timeout(400)
        added = fbq(page)[before:]
        check("one %s, custom, to the pixel" % TAP,
              len(added) == 1 and added[0][:3] == ["trackSingleCustom", PIXEL,
                                                   TAP], added)
        check("  content_name the key, content_category the slug, only",
              added and added[0][3:] == [{"content_name": key,
                                          "content_category": "benefits"}],
              added)
        check("  and the new tab opens on the row's href",
              href == walk.ARTICLES[key]["link"] + walk.TAIL
              and (opened == href or opened in ("about:blank", "")
                   or opened.startswith("chrome-error")), [opened, href])
        first = rows[0][0]
        with ctx.expect_page() as popup:
            page.locator('#result-rows a[data-article="%s"]' % first).click()
        popup.value.close()
        with ctx.expect_page() as popup:
            page.locator('#result-rows a[data-article="%s"]' % key).click()
        popup.value.close()
        page.wait_for_timeout(400)
        added = fbq(page)[before:]
        check("every tap is one more, the same row again included",
              [c[3]["content_name"] for c in added] == [key, first, key],
              added)

        print("\n--- 4. what is never sent ---")
        calls = fbq(page)
        check("three event names and no others",
              sorted(set(names(calls))) == sorted({"PageView", RESULT, TAP}),
              sorted(set(names(calls))))
        check("no Lead, AddToCart, ViewContent or Purchase, by any method",
              not [c for c in calls if c[0] in TRACKS and c[2] in NEVER],
              [c[:3] for c in calls])
        check("PageView standard, the other two custom; one init a load",
              methods_right(calls)
              and [c for c in calls if c[0] == "init"] == [["init", PIXEL]] * 3,
              [c[:3] for c in calls])
        check("only the tap event has parameters, and only its two",
              all(len(c) == 3 for c in calls if c[0] in TRACKS
                  and c[2] != TAP)
              and all(len(c) == 4 and sorted(c[3]) == ["content_category",
                                                       "content_name"]
                      for c in calls if c[0] in TRACKS and c[2] == TAP))
        sid = page.evaluate("() => JSON.parse(sessionStorage.getItem("
                            "'mazzin_rsoc_benefits')).sid")
        flat = json.dumps(calls)
        check("no session id, subid or click identifier in any call",
              len(sid) == 36 and not [v for v in (
                  sid, "sub-77", walk.FBCLID, walk.AD_ID, walk.ASID)
                  if v in flat], flat[:200])
        params = json.dumps([c[3] for c in calls if len(c) > 3])
        check("no answer in any parameter",
              not [v for v in ("medical", "solo", "i2", "employed", "unable",
                               "TX", "Texas") if v in params], params)
        check("no script error", not seen["errors"], seen["errors"])
        ctx.close()

        print("\n--- 2b. no fbclid ---")
        ctx, page, seen = arrive(browser, "?ad_id=%s" % walk.AD_ID)
        walk.to_result(page)
        check("no rows, and the result event is sent anyway",
              walk.anchors(page) == []
              and names(fbq(page)) == ["PageView", RESULT], names(fbq(page)))
        ctx.close()

        print("\n--- 3b. a muted pre-feed row ---")
        walk.served["config"] = walk.PREFEED
        ctx, page, seen = arrive(browser, FULL)
        walk.to_result(page)
        page.locator('#result-rows .guide[data-article="car_insurance"]'
                     ).click()
        page.wait_for_timeout(300)
        last = fbq(page)[-1]
        check("a tap on it is a %s like any other" % TAP,
              last == ["trackSingleCustom", PIXEL, TAP,
                       {"content_name": "car_insurance",
                        "content_category": "benefits"}], last)
        ctx.close()
        walk.served["config"] = walk.REAL

        print("\n--- 5. Meta's script blocked ---")
        ctx, page, seen = arrive(browser, FULL, meta="block")
        walk.to_result(page)
        rows = walk.anchors(page)
        check("the quiz completes, with three anchors carrying the ids",
              walk.view(page) == "result" and len(rows) == 3
              and all(r[1].endswith(walk.TAIL) for r in rows), rows)
        with ctx.expect_page() as popup:
            page.locator("#result-rows a").first.click()
        popup.value.close()
        page.wait_for_timeout(300)
        queued = page.evaluate("() => [...window.fbq.queue].map(a => [...a]"
                               ".slice(0, 3))")
        check("the calls wait in a queue nobody reads, under the right names",
              ["trackSingleCustom", PIXEL, RESULT] in queued
              and ["trackSingleCustom", PIXEL, TAP] in queued
              and methods_right(queued)
              and not page.evaluate("() => !!window.fbq.callMethod"), queued)
        page.reload()
        page.wait_for_timeout(400)
        walk.tap(page, "#top-link")
        own = [c for c in seen["console"] if c[0] == "error"
               and "connect.facebook.net" not in c[1] + c[2]
               and c[2].startswith(BASE)]
        check("nothing throws, and the page logs no error of its own",
              not seen["errors"] and not own and walk.view(page)
              == "situation", [seen["errors"], own])
        ctx.close()

        print("\n--- 6. the first paint does not wait for Meta ---")
        ctx, page, seen = arrive(browser, FULL, meta="hold")
        paint = page.evaluate(
            "() => ({ fcp: (performance.getEntriesByName("
            "'first-contentful-paint')[0] || {}).startTime || null,"
            " h1: !!document.querySelector('#view-need h1').offsetParent,"
            " async: [...document.scripts].filter(s => s.src.includes("
            "'facebook')).map(s => [s.async, s.parentNode.tagName]) })")
        check("Meta's script is still on its way, and the page is painted",
              len(seen["held"]) == 1 and fbq(page) == []
              and paint["fcp"] is not None and paint["h1"], paint)
        check("  the tag is async, in the head, added by the script",
              paint["async"] == [[True, "HEAD"]], paint)
        walk.choose(page, "need", "food")
        check("  a tap moves on while it hangs",
              walk.view(page) == "household")
        seen["held"][0].fulfill(status=200, content_type="text/javascript",
                                body=FBEVENTS)
        page.wait_for_timeout(500)
        check("  when it lands, the queued init and PageView are delivered",
              fbq(page) == [["init", PIXEL],
                            ["trackSingle", PIXEL, "PageView"]], fbq(page))
        ctx.close()
        browser.close()
    server.shutdown()

    print("\n--- the files ---")
    for rel in ("static/rsoc.html", "static/js/rsoc_quiz.js"):
        text = walk.read(rel)
        check("%s names neither ViewContent nor Purchase" % rel,
              "ViewContent" not in text and "Purchase" not in text)
    js = walk.read("static/js/rsoc_quiz.js")
    check("the script sends only trackSingle and trackSingleCustom",
          '"trackSingleCustom" : "trackSingle"' in js
          and "fbq(" not in js.replace("window.fbq.apply(", "")
          and '"track"' not in js and '"trackCustom"' not in js)
    check("  and init carries no second argument",
          'pixel("init", pixelId);' in js and "external_id" not in js)

    print("\n%d checks, %d failed" % (checks[0], len(fails)))
    for line in fails:
        print("  FAIL " + line[:420])
    return 1 if fails else 0


if __name__ == "__main__":
    sys.exit(main())
