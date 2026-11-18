#!/usr/bin/env python3
"""A stubbed purchase on /ai-navigator, walked to the real delivered page.

Eighteen steps at 390x844, the pay button, and the page that comes back from
it. Stripe is the one thing stubbed: the checkout call is answered here with
a return link, and the report behind that link is the real one —
`reports.start_report` run on the choices the browser sent, with no key, so
what is drawn is exactly what a purchase stores when nothing is generating.

What is held to it:

  * the delivered page draws the stored numbers, the paths card — three
    paths with their facts, two to skip — the four chapters and the answer
    key, all from the report and none of it from the run;
  * the "delivered" article slot still renders at the end of the paid page,
    with the click identifiers on both links;
  * that slot reads the skill and the zone off the report, so it survives a
    tab that kept the identifiers and nothing of the run;
  * a tab with no identifiers draws no article block at all;
  * the free page, before the money, shows no right answer and no reason.

Nothing leaves the machine. The walker is the one the article suite uses.

    python3 tests/test_ainavigator_delivered.py
"""
import http.server
import json
import os
import socketserver
import sys
import threading

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, REPO)
sys.path.insert(0, os.path.join(REPO, "tests"))

import database                                            # noqa: E402

# No suite talks to a database.
database.execute = lambda *a, **kw: None
database.query_all = lambda *a, **kw: []
database.query_one = lambda *a, **kw: None

import reports                                             # noqa: E402
import test_ainavigator_rsoc as walk                       # noqa: E402

from playwright.sync_api import sync_playwright            # noqa: E402

PORT = 8861
CHROME = walk.CHROME
BASE = "http://127.0.0.1:%d" % PORT
CS = "cs_test_ainavigator1"
TAIL = "?fbclid=AbC_123-x&ad_id=111&asid=222"

CFG = walk.CFG
ARTICLES = CFG["rsoc"]["articles"]
CATALOG = dict((row["id"], row) for row in CFG["paths"]["catalog"])
KEY = dict((s["id"], s["why"]) for s in CFG["swipe"]["steps"] if "why" in s)
COPY = CFG["result_copy"]
IMAGES = set(c["id"] for s in CFG["swipe"]["steps"]
             for c in s["pairs"][0]["images"])

fails = []
checks = [0]


def check(label, ok, detail=""):
    checks[0] += 1
    if not ok:
        fails.append("%s %s" % (label, detail))
    print("  %-62s %s%s" % (label, "ok" if ok else "FAIL",
                            ("  " + str(detail)[:400]) if not ok else ""))


state = {"order": None, "report": None}


class Handler(http.server.SimpleHTTPRequestHandler):
    """The funnel off disk; checkout answered with a report of its own."""

    def __init__(self, *a, **kw):
        super().__init__(*a, directory=REPO, **kw)

    def log_message(self, *a):
        pass

    def do_GET(self):
        path = self.path.split("?")[0]
        if path == "/api/pixel-config":
            return self._json({"pixel_id": ""})
        if path == "/api/report":
            if state["report"] is None:
                return self._json({}, 404)
            return self._json({
                "complete": True, "email_masked": "r***@example.com",
                "report": reports.delivered_content(state["report"],
                                                    "reader@example.com")})
        if path == "/ai-navigator":
            self.path = "/static/funnel.html"
        return super().do_GET()

    def do_POST(self):
        raw = self.rfile.read(int(self.headers.get("content-length") or 0))
        path = self.path.split("?")[0]
        if path == "/api/checkout":
            order = json.loads(raw)
            # What the webhook would hand over: the ids, known to this
            # funnel, and the style the page landed on.
            choices = [c for c in order.get("choices") or [] if c in IMAGES]
            state["order"] = order
            state["report"] = reports.start_report(
                77, "ai-navigator", order.get("result_style"),
                order.get("tag_scores"), choices=choices)
            return self._json({"url": "%s/ai-navigator?cs=%s" % (BASE, CS)})
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


FREE = """() => {
  const root = document.querySelector('#result-module');
  const pay = document.querySelector('#pay-button');
  const offer = root.querySelector('.ai-offer');
  // The markup, not the rendered text: nothing of the report may be in the
  // DOM at all, shown or hidden.
  return { text: root.innerHTML,
           order: [...root.children].map(c => c.className.split(' ')[0]),
           key: !!root.querySelector('.ai-key'),
           paths: !!root.querySelector('.ai-paths'),
           score: (root.querySelector('.ai-ring-n') || {}).innerText || '',
           payIn: offer.contains(pay), payText: pay.textContent,
           bars: offer.querySelectorAll('.ai-bar').length,
           barText: [...offer.querySelectorAll('.ai-bar')]
             .map(b => b.textContent).join(''),
           rows: [...offer.querySelectorAll('.ai-locked-label')]
             .map(n => n.textContent),
           pay: !pay.disabled };
}"""

PAID = """() => {
  const root = document.querySelector('#result-module');
  const q = s => (root.querySelector(s) || {}).innerText || '';
  const all = s => [...root.querySelectorAll(s)];
  const box = root.querySelector('.ai-rsoc');
  const cards = all('.ai-paths .ai-pathcard').map(c => ({
    name: c.querySelector('.ai-pathcard-name').textContent,
    first: c.classList.contains('is-first'),
    facts: [...c.querySelectorAll('dd')].map(d => d.textContent),
    labels: [...c.querySelectorAll('dt')].map(d => d.textContent) }));
  const over = [];
  for (const el of root.querySelectorAll('*')) {
    const b = el.getBoundingClientRect();
    if (b.width && (b.right > innerWidth + 0.5 || b.left < -0.5)) {
      over.push(el.className);
    }
  }
  return {
    delivered: root.classList.contains('is-delivered'),
    order: [...root.children].map(c => c.className.split(' ')[0]),
    score: q('.ai-ring-n'), predict: q('.ai-predict'),
    calibration: q('.ai-calibration'), type: q('.ai-type-name'),
    kicker: q('.ai-kicker'),
    zones: all('.ai-zone').map(z => z.querySelector('.ai-zone-name')
      .textContent + ' ' + z.querySelector('.ai-zone-count').textContent),
    room: q('.ai-zone.is-room .ai-zone-name'),
    sent: q('.ai-sent'),
    pathsTitle: q('.ai-paths .ai-h2'), format: q('.ai-paths-format'),
    skipTitle: q('.ai-paths-sub'), cards: cards,
    chapters: all('.ai-path.is-open .ai-node-title').map(n => n.textContent),
    pairs: all('.ai-pair .ai-item-title').map(n => n.textContent),
    keyTitle: q('.ai-key .ai-h2'),
    rows: all('.ai-key-row').map(r => ({
      q: r.querySelector('.ai-key-q').childNodes[0].textContent,
      badge: r.querySelector('.ai-badge').textContent,
      hit: r.classList.contains('is-hit'),
      lines: [...r.querySelectorAll('.ai-key-line')].map(l => l.textContent),
      why: (r.querySelector('.ai-key-why') || {}).textContent })),
    rsoc: box ? {
      slot: box.getAttribute('data-slot'),
      head: box.querySelector('.ai-rsoc-head').textContent,
      kicker: box.querySelector('.ai-rsoc-kicker').textContent,
      tags: [...box.querySelectorAll('.ai-rsoc-tag')].map(t => t.textContent),
      links: [...box.querySelectorAll('a')].map(a => [
        a.getAttribute('data-article'), a.getAttribute('href'),
        a.target, a.rel]) } : null,
    offer: !!root.querySelector('.ai-offer'),
    buttons: root.querySelectorAll('button').length,
    foot: q('.ai-foot'),
    sw: document.documentElement.scrollWidth, vw: innerWidth, over: over
  };
}"""


def context(browser, seed=None):
    ctx = browser.new_context(viewport={"width": 390, "height": 844},
                              is_mobile=True, has_touch=True)
    ctx.route(lambda url: not url.startswith(BASE), lambda r: r.abort())
    if seed:
        ctx.add_init_script(
            "(function (s) { try { for (var k in s) "
            "sessionStorage.setItem(k, JSON.stringify(s[k])); } catch (e) {} "
            "})(%s)" % json.dumps(seed))
    page = ctx.new_page()
    errors = []
    page.on("pageerror", lambda e: errors.append(str(e)))
    return ctx, page, errors


def delivered(page):
    page.wait_for_selector("#result-module.is-delivered .ai-node",
                           timeout=30000)
    page.wait_for_timeout(800)
    return page.evaluate(PAID)


def main():
    server = Server(("127.0.0.1", PORT), Handler)
    threading.Thread(target=server.serve_forever, daemon=True).start()

    with sync_playwright() as pw:
        browser = pw.chromium.launch(executable_path=CHROME)

        print("\n--- the walk, and the free page ---")
        ctx, page, errors = context(browser)
        page.goto(BASE + "/ai-navigator" + TAIL)
        answered = walk.advance(page)
        page.wait_for_selector("#result-module .ai-offer", timeout=30000)
        page.wait_for_timeout(900)
        free = page.evaluate(FREE)
        check("twelve steps, to the result", len(answered) == 12,
              len(answered))
        check("the free page is the three blocks, in order, then the rest",
              free["order"] == ["ai-profile", "ai-scorecard", "ai-offer",
                                "ai-rsoc", "ai-unlock", "ai-divider",
                                "ai-foot"], free["order"])
        check("  the pay button is engine.js's own, inside the offer card",
              free["payIn"] and free["payText"].startswith(
                  "Unlock my strategy"), free["payText"])
        check("  no strategy's name and no right answer anywhere in it",
              not [row["name"] for row in CATALOG.values()
                   if row["name"] in free["text"]]
              and not [c["label"] for s in CFG["swipe"]["steps"]
                       if "why" in s for c in s["pairs"][0]["images"]
                       if c["label"] in free["text"]])
        check("  the locked rows are labels and empty bars",
              free["bars"] == 4 and free["barText"] == ""
              and free["rows"] == COPY["offer"]["rows"], free["rows"])
        check("the free page draws no answer key and no paths card",
              not free["key"] and not free["paths"])
        check("  and no reason from the key, and no path's facts",
              not [k for k, why in KEY.items() if why in free["text"]]
              and not [row["id"] for row in CATALOG.values()
                       if row["sells"] in free["text"]
                       or row["risk"] in free["text"]])
        check("the pay button is live", free["pay"])

        print("\n--- the purchase ---")
        page.locator("#pay-button").click()
        paid = delivered(page)
        order = state["order"] or {}
        report = state["report"] or {}
        visuals = report.get("visuals") or {}
        check("checkout carried the choices, all twelve, known ids",
              len(order.get("choices") or []) == 12
              and all(c in IMAGES for c in order["choices"])
              and order.get("funnel") == "ai-navigator")
        check("the report behind the link is whole, with its three blocks",
              report.get("version", "").startswith("stub-")
              and len(report.get("sections") or []) == 4
              and all(k in visuals for k in ("brain", "paths",
                                             "answer_key")))
        check("it came back to the delivered page, not the quiz",
              paid["delivered"] and not paid["offer"]
              and paid["buttons"] == 0)

        print("\n--- the delivered page: the numbers ---")
        brain = visuals["brain"]
        check("the score the free page showed, out of eight",
              paid["score"].replace("\n", "").replace(" ", "") == "5/8"
              and brain["hits"] == 5 and free["score"] == paid["score"],
              paid["score"])
        check("  against the prediction, in the config's words",
              paid["predict"] == "You predicted 0–2. You scored 5."
              and paid["calibration"] == COPY["calibration"]["under"]
              and brain["calibration"] == "underrated",
              [paid["predict"], paid["calibration"]])
        check("  the type, and the four zones in play order, x of 2",
              paid["type"] == "The Mechanic" and brain["level"] == "Builder"
              and paid["kicker"] == COPY["kicker"]
              and paid["zones"] == ["How AI works 2 of 2",
                                    "Prompting 2 of 2",
                                    "Judgment & risk 1 of 2",
                                    "Business sense 0 of 2"],
              [paid["type"], paid["zones"]])
        check("  the zone with the most room, and where the PDF went",
              paid["room"] == "Business sense"
              and "reader@example.com" in paid["sent"])

        print("\n--- the delivered page: the paths card ---")
        want_works = ["P3", "P4", "P1"]
        want_skip = ["P6", "P7"]
        check("the server matched design, under three hours, a side project",
              [c["id"] for c in visuals["paths"]["works"]] == want_works
              and [c["id"] for c in visuals["paths"]["avoid"]] == want_skip)
        check("five cards: the three that fit, then the two to skip",
              [c["name"] for c in paid["cards"]]
              == [CATALOG[p]["name"] for p in want_works + want_skip],
              [c["name"] for c in paid["cards"]])
        check("  the first is marked as the one to start with, alone",
              [c["first"] for c in paid["cards"]]
              == [True, False, False, False, False])
        check("  each of the three carries all five facts, as the catalog's",
              all(card["facts"] == [CATALOG[p][f] for f in
                                    ("sells", "buyer", "first_client",
                                     "startup", "risk")]
                  for card, p in zip(paid["cards"][:3], want_works))
              and paid["cards"][0]["labels"]
              == [COPY["paths_card"]["facts"][f] for f in
                  ("sells", "buyer", "first_client", "startup", "risk")])
        check("  each of the two to skip says what it is and where it goes "
              "wrong",
              all(card["facts"] == [CATALOG[p]["sells"], CATALOG[p]["risk"]]
                  for card, p in zip(paid["cards"][3:], want_skip)))
        check("  under the config's headings, with the format for the level",
              # Compared without case: the sheet sets both in capitals.
              paid["pathsTitle"].lower()
              == COPY["paths_card"]["title"].lower()
              and paid["skipTitle"].lower()
              == COPY["paths_card"]["skip_title"].lower()
              and paid["format"].endswith(
                  "a productized service with fixed scope"))

        print("\n--- the delivered page: the chapters ---")
        check("four chapters, titled as sold",
              sorted(paid["chapters"]) == sorted(
                  s["title"] for s in CFG["report"]["sections"]),
              paid["chapters"])
        check("the paths chapter names the same five, badged",
              paid["pairs"] == [
                  "%s %s" % (CATALOG[p]["name"], badge) for p, badge in
                  [(p, COPY["paths_card"]["badge_works"]) for p in want_works]
                  + [(p, COPY["paths_card"]["badge_avoid"])
                     for p in want_skip]], paid["pairs"])

        print("\n--- the delivered page: the answer key ---")
        rows = visuals["answer_key"]
        check("eight rows, in the order the scenarios were asked",
              [r["q"].strip() for r in paid["rows"]]
              == [r["question"] for r in rows] and len(rows) == 8
              and paid["keyTitle"] == COPY["key_card"]["title"])
        check("  theirs and the right one on every row",
              all(shown["lines"] == [
                  "%s %s" % (COPY["key_card"]["yours"], r["yours"]),
                  "%s %s" % (COPY["key_card"]["right"], r["right"])]
                  for shown, r in zip(paid["rows"], rows)),
              paid["rows"][0]["lines"])
        check("  the reason on every row, as the config wrote it",
              [r["why"] for r in paid["rows"]] == [KEY[r["id"]] for r in rows])
        check("  five right and three missed, marked as the report says",
              [r["hit"] for r in paid["rows"]] == [r["hit"] for r in rows]
              and [r["hit"] for r in rows].count(True) == 5
              and all(shown["badge"] == (COPY["key_card"]["hit"] if r["hit"]
                                         else COPY["key_card"]["miss"])
                      for shown, r in zip(paid["rows"], rows)))

        print("\n--- the delivered page: the article slot ---")
        check("the block is drawn, in the delivered slot, with its own head",
              paid["rsoc"] is not None
              and paid["rsoc"]["slot"] == "delivered"
              and paid["rsoc"]["head"] == CFG["rsoc"]["head_delivered"]
              and paid["rsoc"]["kicker"] == "KEEP GOING"
              and paid["rsoc"]["tags"]
              == ["PICKED FOR YOUR SKILL: Design",
                  "PICKED FOR WHERE YOU HAVE THE MOST ROOM: Business sense"],
              paid["rsoc"])
        links = (paid["rsoc"] or {}).get("links") or []
        check("two anchors: the skill's article, then the zone's",
              [l[0] for l in links] == ["skill_design", "spa"],
              [l[0] for l in links])
        check("  each the config link and the three identifiers",
              all(l[1] == ARTICLES[l[0]]["link"] + TAIL
                  and l[2] == "_blank" and l[3] == "noopener"
                  for l in links), [l[1][-44:] for l in links])
        check("the page runs numbers, paths, chapters, key, articles, footer",
              [c for c in paid["order"] if c in (
                  "ai-zones", "ai-paths", "ai-path", "ai-key", "ai-rsoc",
                  "ai-foot")]
              == ["ai-zones", "ai-paths", "ai-path", "ai-key", "ai-rsoc",
                  "ai-foot"], paid["order"])
        check("the disclaimer is the last line",
              paid["foot"] == COPY["disclaimer"]
              and paid["order"][-1] == "ai-foot")
        check("no horizontal scroll, nothing off the screen",
              paid["sw"] <= paid["vw"] and not paid["over"],
              paid["over"][:4])
        check("no script errors", not errors, errors)
        if os.environ.get("AI_SHOT"):
            page.screenshot(path=os.environ["AI_SHOT"], full_page=True)
        ctx.close()

        print("\n--- the same link, in a tab that kept only the click ---")
        # The identifiers and nothing of the run: no stored skill, no stored
        # zone. Both articles can only have come off the report.
        ctx, page, errors = context(browser, {
            "mazzin_pass_ai-navigator": {"fbclid": "AbC_123-x"}})
        page.goto("%s/ai-navigator?cs=%s" % (BASE, CS))
        paid = delivered(page)
        links = (paid["rsoc"] or {}).get("links") or []
        check("both articles are drawn from the report alone",
              [l[0] for l in links] == ["skill_design", "spa"],
              [l[0] for l in links])
        check("  carrying the one identifier that is held",
              all(l[1] == ARTICLES[l[0]]["link"] + "?fbclid=AbC_123-x"
                  for l in links))
        check("no script errors", not errors, errors)
        ctx.close()

        print("\n--- the same link, from the mail, in a fresh tab ---")
        ctx, page, errors = context(browser)
        page.goto("%s/ai-navigator?cs=%s" % (BASE, CS))
        paid = delivered(page)
        check("the report is all there: numbers, paths, chapters, key",
              paid["type"] == "The Mechanic" and len(paid["cards"]) == 5
              and len(paid["chapters"]) == 4 and len(paid["rows"]) == 8)
        check("  and with no click held there is no article block",
              paid["rsoc"] is None and "ai-rsoc" not in paid["order"])
        check("no script errors", not errors, errors)
        ctx.close()

        browser.close()
    server.shutdown()

    print("\n%d checks, %d failed" % (checks[0], len(fails)))
    for line in fails:
        print("  FAIL " + line[:500])
    return 1 if fails else 0


if __name__ == "__main__":
    sys.exit(main())
