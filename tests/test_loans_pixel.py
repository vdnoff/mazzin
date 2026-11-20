#!/usr/bin/env python3
"""The article partner's Meta pixel on /loans, in a real browser.

Meta's script is replaced by a local recorder, so every fbq call the page
makes can be read back; every request off the machine is recorded and then
aborted.

  1. A load initialises pixel 762004311984135 and sends one PageView.
  2. The summary sends one Lead, once a session: not again on a reload, on
     "Edit answers" and back, or on browser back and forward. It is sent with
     or without an fbclid.
  3. A tap on an article row sends one AddToCart with that article's key and
     the category "loans", and the new tab still opens. Every tap.
  4. Nothing else is ever sent: no article-view event, no purchase event.
  5. No event carries a session id, the subid, a click identifier or any
     answer as a parameter of its own.
  6. With Meta's script blocked the page throws nothing, the flow completes
     and the article links still carry the identifiers.
  7. The first view is painted while Meta's script is still on its way.

    python3 tests/test_loans_pixel.py
"""
import json
import os
import sys
import threading

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, REPO)
sys.path.insert(0, os.path.join(REPO, "tests"))

import test_loans_rsoc as rsoc                             # noqa: E402

from playwright.sync_api import sync_playwright            # noqa: E402

PORT = 8875
BASE = "http://127.0.0.1:%d" % PORT
PIXEL = "762004311984135"
META = "https://connect.facebook.net/en_US/fbevents.js"
FULL = rsoc.FULL + "&subid=sub-77"
ARTICLES = rsoc.ARTICLES

fails = []
checks = [0]


def check(label, ok, detail=""):
    checks[0] += 1
    if not ok:
        fails.append("%s %s" % (label, detail))
    print("  %-66s %s%s" % (label, "ok" if ok else "FAIL",
                            ("  " + str(detail)[:400]) if not ok else ""))


# Meta's script, replaced: it drains the page's queue into sessionStorage, so
# the record outlives a reload.
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
    """A context on /loans. `meta` is what becomes of Meta's script: "stub"
    (the recorder), "block" (aborted), or "hold" (left hanging)."""
    ctx = browser.new_context(viewport={"width": 390, "height": 844},
                              is_mobile=True, has_touch=True)
    seen = {"off": [], "held": [], "errors": [], "console": []}

    def off_machine(route):
        seen["off"].append(route.request.url)
        url = route.request.url
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
    if query is not None:
        # With the script held the window's load event is held with it, as it
        # is for any async script; the document itself is not.
        page.goto(BASE + "/loans" + query,
                  wait_until="domcontentloaded" if meta == "hold" else "load")
        page.wait_for_timeout(400)
    return ctx, page, seen


def fbq(page):
    return page.evaluate(
        "() => JSON.parse(sessionStorage.getItem('__fbq') || '[]')")


def names(calls):
    return [c[2] for c in calls if c[0] == "trackSingle"]


def walk(page, purpose="medical", credit="fair"):
    rsoc.to_income(page, purpose)
    rsoc.to_credit(page)
    rsoc.to_options(page, credit)


def hrefs(page):
    return page.evaluate("() => [...document.querySelectorAll('a.guide')]"
                         ".map(a => [a.dataset.article, a.href])")


def main():
    server = rsoc.Server(("127.0.0.1", PORT), rsoc.Handler)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    tail = "?fbclid=%s&ad_id=%s&asid=%s" % (rsoc.FBCLID, rsoc.AD_ID,
                                             rsoc.ASID)

    with sync_playwright() as pw:
        browser = pw.chromium.launch(executable_path=rsoc.CHROME)

        print("\n--- 1. a load ---")
        ctx, page, seen = arrive(browser, FULL)
        calls = fbq(page)
        check("init with the partner's pixel id, and nothing beside it",
              calls[:1] == [["init", PIXEL]], calls[:1])
        check("then one PageView, addressed to that pixel",
              calls == [["init", PIXEL], ["trackSingle", PIXEL, "PageView"]],
              calls)
        check("the only request off the machine is Meta's script, once",
              seen["off"] == [META], seen["off"])
        check("the landing URL still carries its fbclid",
              "fbclid=" + rsoc.FBCLID in page.url, page.url)
        check("the site's own pixel is not asked for",
              not [p for p in rsoc.posts if "pixel" in p[0]]
              and page.evaluate("() => performance.getEntriesByType("
                                "'resource').filter(r => r.name.includes("
                                "'pixel-config')).length") == 0)

        print("\n--- 2. the summary: one Lead a session ---")
        walk(page)
        check("the walk reaches the summary", rsoc.view(page) == "options",
              rsoc.view(page))
        calls = fbq(page)
        check("exactly one Lead, with no parameters",
              names(calls) == ["PageView", "Lead"]
              and calls[-1] == ["trackSingle", PIXEL, "Lead"], calls)
        page.reload()
        page.wait_for_timeout(500)
        check("a reload on the summary: a PageView, no second Lead",
              rsoc.view(page) == "options"
              and names(fbq(page)) == ["PageView", "Lead", "PageView"],
              names(fbq(page)))
        rsoc.tap(page, "#top-link")
        back_at = rsoc.view(page)
        rsoc.tap(page, '#credit-rows button[data-value="good"]')
        rsoc.tap(page, "#go-options")
        check("Edit answers, a changed answer, and back: still one Lead",
              back_at == "credit" and rsoc.view(page) == "options"
              and names(fbq(page)).count("Lead") == 1,
              [back_at, names(fbq(page))])
        page.go_back()
        page.wait_for_timeout(300)
        mid = rsoc.view(page)
        page.go_forward()
        page.wait_for_timeout(300)
        check("browser back and forward: still one Lead",
              mid == "credit" and rsoc.view(page) == "options"
              and names(fbq(page)).count("Lead") == 1,
              [mid, names(fbq(page))])
        page.goto(BASE + "/loans")
        page.wait_for_timeout(500)
        check("a second arrival in the same tab: a PageView, no second Lead",
              rsoc.view(page) == "options"
              and names(fbq(page)) == ["PageView", "Lead", "PageView",
                                       "PageView"], names(fbq(page)))

        print("\n--- 3. a tap on an article row ---")
        rows = hrefs(page)
        key, href = rows[1]
        before = len(fbq(page))
        posts_before = len(rsoc.posts)
        with ctx.expect_page() as popup:
            page.locator('a.guide[data-article="%s"]' % key).click()
        opened = popup.value.url
        popup.value.close()
        page.wait_for_timeout(400)
        added = fbq(page)[before:]
        check("one AddToCart, addressed to the pixel",
              len(added) == 1 and added[0][:3] == ["trackSingle", PIXEL,
                                                   "AddToCart"], added)
        check("  content_name the article's key, content_category loans, "
              "and nothing else",
              added and added[0][3:] == [{"content_name": key,
                                          "content_category": "loans"}],
              added)
        check("  the new tab still opens, on the article with the three ids",
              href == ARTICLES[key]["link"] + tail
              and (opened == href or opened in ("about:blank", "")
                   or opened.startswith("chrome-error")), [opened, href])
        taps = [json.loads(p[1]) for p in rsoc.posts[posts_before:]
                if p[0] == "/api/loans/event"]
        check("  and the page's own offer_tap is posted as before",
              [t.get("event") for t in taps] == ["offer_tap"]
              and taps[0].get("extra") == {"slot": key}, taps)
        other = rows[0][0]
        with ctx.expect_page() as popup:
            page.locator('a.guide[data-article="%s"]' % other).click()
        popup.value.close()
        page.wait_for_timeout(400)
        added = fbq(page)[before:]
        check("every tap: a second row is a second AddToCart, under its key",
              [c[2] for c in added] == ["AddToCart", "AddToCart"]
              and added[1][3] == {"content_name": other,
                                  "content_category": "loans"}, added)

        print("\n--- 4 and 5. what is never sent ---")
        calls = fbq(page)
        check("three event names and no others, anywhere in the session",
              sorted(set(names(calls))) == ["AddToCart", "Lead", "PageView"],
              sorted(set(names(calls))))
        check("every event is a trackSingle to this pixel; one init a load",
              all(c[0] in ("init", "trackSingle") and c[1] == PIXEL
                  for c in calls)
              and [c for c in calls if c[0] == "init"]
              == [["init", PIXEL]] * 3, [c[:2] for c in calls])
        check("only AddToCart has parameters, and only the two it may",
              all(len(c) == 3 for c in calls if c[0] == "trackSingle"
                  and c[2] != "AddToCart")
              and all(sorted(c[3]) == ["content_category", "content_name"]
                      and len(c) == 4 for c in calls
                      if c[0] == "trackSingle" and c[2] == "AddToCart"))
        sid = page.evaluate("() => JSON.parse(sessionStorage.getItem("
                            "'mazzin_loans')).sid")
        flat = json.dumps(calls)
        check("no session id, subid or click identifier in any call",
              len(sid) == 36 and not [v for v in (
                  sid, "sub-77", rsoc.FBCLID, rsoc.AD_ID, rsoc.ASID)
                  if v in flat], flat[:200])
        params = json.dumps([c[3] for c in calls if len(c) > 3])
        check("no amount, employment, income or state in any parameter",
              not [v for v in ("500", "employed", "2000_3000", "TX", "Texas")
                   if v in params], params)
        check("nothing of the article link beyond its key",
              "http" not in flat and "openresourcelist" not in flat)
        check("no script error, and nothing off the machine but Meta's "
              "script and the two article tabs",
              not seen["errors"]
              and sorted(set(u.split("?")[0] for u in seen["off"]))
              == sorted({META, ARTICLES[key]["link"],
                         ARTICLES[other]["link"]}),
              [seen["errors"], [u[:60] for u in seen["off"]]])
        ctx.close()

        print("\n--- 2b. a visit with no fbclid ---")
        ctx, page, seen = arrive(browser, "")
        walk(page)
        check("the summary has no article rows, and the Lead is sent anyway",
              rsoc.view(page) == "options" and hrefs(page) == []
              and names(fbq(page)) == ["PageView", "Lead"],
              [hrefs(page), names(fbq(page))])
        ctx.close()

        print("\n--- 6. Meta's script blocked ---")
        ctx, page, seen = arrive(browser, FULL, meta="block")
        walk(page)
        rows = hrefs(page)
        check("the flow completes to the summary", rsoc.view(page) == "options"
              and len(rows) == 4, [rsoc.view(page), len(rows)])
        check("the article links still carry the three identifiers",
              rows and all(href == ARTICLES[k]["link"] + tail
                           for k, href in rows), rows[:1])
        with ctx.expect_page() as popup:
            page.locator("a.guide").first.click()
        popup.value.close()
        page.wait_for_timeout(400)
        page.reload()
        page.wait_for_timeout(400)
        rsoc.tap(page, "#top-link")
        own = [c for c in seen["console"] if c[0] == "error"
               and "connect.facebook.net" not in c[2]
               and "connect.facebook.net" not in c[1]
               and c[2].startswith(BASE)]
        check("nothing throws, and the page logs no error of its own",
              not seen["errors"] and not own, [seen["errors"], own])
        check("the calls wait in a queue nobody reads",
              page.evaluate("() => typeof window.fbq === 'function' "
                            "&& !window.fbq.callMethod "
                            "&& window.fbq.queue.length >= 2"))
        events = [json.loads(p[1]).get("event") for p in rsoc.posts
                  if p[0] == "/api/loans/event"]
        check("the page's own events are still posted",
              "result_view" in events and "offer_tap" in events)
        ctx.close()

        print("\n--- 7. the first paint does not wait for Meta ---")
        ctx, page, seen = arrive(browser, FULL, meta="hold")
        page.wait_for_timeout(600)
        paint = page.evaluate(
            "() => ({ fcp: (performance.getEntriesByName("
            "'first-contentful-paint')[0] || {}).startTime || null,"
            " h1: !!document.querySelector('#view-landing h1').offsetParent,"
            " ready: document.readyState,"
            " async: [...document.scripts].filter(s => s.src.includes("
            "'facebook')).map(s => [s.async, s.parentNode.tagName]),"
            " inHtml: document.documentElement.outerHTML.split("
            "'connect.facebook.net').length - 1 })")
        check("Meta's script is still on its way",
              len(seen["held"]) == 1 and fbq(page) == [], seen["off"])
        check("and the page is painted, parsed and usable all the same",
              paint["fcp"] is not None and paint["h1"]
              and paint["ready"] in ("interactive", "complete"), paint)
        check("  the script tag is async, in the head, and added by loans.js",
              paint["async"] == [[True, "HEAD"]] and paint["inHtml"] == 1,
              paint)
        rsoc.tap(page, "#go-compare")
        check("  a tap moves on while it hangs", rsoc.view(page) == "purpose")
        seen["held"][0].fulfill(status=200, content_type="text/javascript",
                                body=FBEVENTS)
        page.wait_for_timeout(500)
        check("  when it lands, the queued init and PageView are delivered",
              fbq(page) == [["init", PIXEL],
                            ["trackSingle", PIXEL, "PageView"]], fbq(page))
        ctx.close()
        browser.close()
    server.shutdown()

    print("\n%d checks, %d failed" % (checks[0], len(fails)))
    for line in fails:
        print("  FAIL " + line[:420])
    return 1 if fails else 0


if __name__ == "__main__":
    sys.exit(main())
