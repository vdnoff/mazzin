#!/usr/bin/env python3
"""The post-Stripe view, driven through a real progressive delivery.

/api/report is served here as a scripted sequence of polls, deliberately out of
order: a later section resolves before an earlier one, which is exactly what
the model calls do in practice. What is checked is that the reader never sees
it — nothing until the palette is in, then the document strictly in config
order, with the elements strip delivered under the palette.
"""
import http.server
import json
import os
import socketserver
import threading
# The repo root, derived from this file rather than hardcoded: a suite
# that only runs from one absolute path is a suite that stops running the
# first time the checkout moves.
REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


from playwright.sync_api import sync_playwright

ROOT = REPO
SHOTS = os.path.dirname(os.path.abspath(__file__))
PORT = 8733
CS = "cs_test_paidview123"

cfg = json.load(open(os.path.join(ROOT, "funnels/kitchen.json")))
ORDER = [s["id"] for s in cfg["report"]["sections"]
         if s.get("enabled") is not False]
TITLES = {s["id"]: s["title"] for s in cfg["report"]["sections"]}
ELEMENTS = ["brass-hardware", "dark-timber", "stone-worktop",
            "open-shelving", "statement-pendants", "oak-wood"]
BY_ID = {e["id"]: e for e in cfg["style_elements"]["items"]}

fails = []


def check(label, ok, detail=""):
    if not ok:
        fails.append("%s %s" % (label, detail))
    print("  %-58s %s%s" % (label, "ok" if ok else "FAIL",
                            ("  " + str(detail)) if not ok else ""))


def section(sid):
    """A minimal but structurally valid schema-2 body per section."""
    data = {
        "palette": {
            "intro": "Three colours carry this room.",
            "colors": [{"name": "Oat Linen", "hex": "#E5DAC8",
                        "role": "dominant", "finish": "matt",
                        "where": "the cream you kept choosing"}],
            "closing_rule": "Sixty oat, thirty oak, ten clay.",
        },
        "mistakes": {"items": [{"title": "Matching every wood tone",
                                "body": "Three identical oaks read as laminate.",
                                "fix": "Age one piece past the rest."}]},
        "materials": {"intro": "Aged brass against smoked oak.",
                      "pairs": [{"combo": "Oak + marble", "verdict": "works",
                                 "why": "One cold thing in a warm room."}],
                      "rule": "One warm metal, one cold stone."},
        "shopping": {"items": [{"name": "The table",
                                "priority_note": "Buy it first."}],
                     "skip": []},
        "dna": {"narrative": ["Your picks lean warm."],
                "implications": ["Buy the timber first."]},
        "splurge": {"splurge": {"item": "The joinery",
                                "why": "It is the thing you touch."},
                    "saves": [{"item": "Appliances", "why": "They all cook."}],
                    "split_note": "Spend up, save down."},
    }[sid]
    return {"id": sid, "title": TITLES[sid], "data": data}


# Poll 1 delivers a LATER section on its own. Poll 2 adds the palette but
# still skips `mistakes`. Poll 3 fills the gap. Poll 4 completes.
# The first state is held for several polls on purpose: the gate has to be
# observable, and one 1200ms poll is a window a test can lose a race to.
SCRIPT = [
    (["materials"], False),
    (["materials"], False),
    (["materials"], False),
    (["palette", "materials"], False),
    (["palette", "materials"], False),
    (["palette", "mistakes", "materials"], False),
    (ORDER, True),
]
polls = [0]


class Handler(http.server.SimpleHTTPRequestHandler):
    def __init__(self, *a, **kw):
        super().__init__(*a, directory=ROOT, **kw)

    def log_message(self, *a):
        pass

    def do_GET(self):
        path = self.path.split("?")[0]
        if path == "/api/pixel-config":
            return self._json({})
        if path == "/api/report":
            i = min(polls[0], len(SCRIPT) - 1)
            ids, complete = SCRIPT[i]
            polls[0] += 1
            return self._json({
                "complete": complete,
                "email_masked": "s***@example.com",
                "report": {
                    "version": "llm-2" if complete else "llm-2-partial",
                    "funnel": "kitchen",
                    "style_id": "modern_rustic",
                    "style_name": "Modern Rustic",
                    "elements": ELEMENTS,
                    "visuals": {"moodboard": "mp5",
                                "materials": ["c4b", "b8a"]},
                    "sections": [section(s) for s in ids],
                },
            })
        if path == "/kitchen":
            self.path = "/static/funnel.html"
        return super().do_GET()

    def _json(self, body):
        raw = json.dumps(body).encode()
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(raw)))
        self.end_headers()
        self.wfile.write(raw)


def titles(page):
    return page.eval_on_selector_all(
        "#report .section",
        "ns => ns.map(n => n.querySelector('.section-title').textContent)")


def main():
    socketserver.TCPServer.allow_reuse_address = True
    httpd = socketserver.TCPServer(("127.0.0.1", PORT), Handler)
    threading.Thread(target=httpd.serve_forever, daemon=True).start()
    try:
        with sync_playwright() as pw:
            browser = pw.chromium.launch(
                executable_path="/opt/pw-browsers/chromium-1194/chrome-linux/chrome")
            page = browser.new_page(viewport={"width": 390, "height": 844},
                                    device_scale_factor=2)
            errors = []
            page.on("pageerror", lambda e: errors.append(str(e)))
            # `commit` rather than `load`: the engine starts polling at script parse,
            # and waiting for the load event can hand back a page that has
            # already moved on.
            page.goto("http://127.0.0.1:%d/kitchen?cs=%s" % (PORT, CS),
                      wait_until="commit")

            # --- poll 1: a later section alone must not open the document ---
            page.wait_for_selector("#analyzing:not([hidden])", timeout=8000)
            page.wait_for_timeout(900)
            check("out-of-order section alone shows no report",
                  page.eval_on_selector("#result-body", "n => n.hidden") is True)
            check("the status card covers the wait",
                  page.eval_on_selector("#analyzing", "n => !n.hidden")
                  and bool(page.inner_text("#analyzing-text")),
                  page.inner_text("#analyzing-text"))
            check("no section is in the document yet", titles(page) == [],
                  titles(page))

            # --- poll 2: palette arrives; materials must still wait ----------
            page.wait_for_selector("#result-body:not([hidden])", timeout=10000)
            page.wait_for_timeout(300)
            shown = titles(page)
            check("the document opens on the palette",
                  shown and shown[0] == TITLES["palette"], shown)
            check("materials does not jump the gap",
                  TITLES["materials"] not in shown, shown)
            check("elements land under the palette",
                  len(shown) > 1 and shown[1] == "Your Style Elements", shown)

            # --- poll 3+: the gap fills and order holds ---------------------
            page.wait_for_function(
                "n => document.querySelectorAll('#report .section').length >= n",
                arg=len(ORDER) + 1, timeout=20000)
            page.wait_for_timeout(400)
            shown = titles(page)
            expected = ([TITLES["palette"], "Your Style Elements"]
                        + [TITLES[s] for s in ORDER[1:]])
            check("final order is exactly the config order",
                  shown == expected, "%s\n        want %s" % (shown, expected))
            check("the elements strip is placed once",
                  shown.count("Your Style Elements") == 1, shown)

            # --- the delivered elements -------------------------------------
            chips = page.eval_on_selector_all(
                ".section-elements .element-chip",
                "ns => ns.map(n => ({"
                " label: n.querySelector('.element-label').textContent,"
                " spec: n.querySelector('.element-spec')"
                "        ? n.querySelector('.element-spec').textContent : null,"
                " img: n.querySelector('img').getAttribute('src'),"
                " top: Math.round(n.getBoundingClientRect().top)}))")
            check("six chips in the paid view", len(chips) == 6, len(chips))
            check("they are the six the server stored",
                  [c["label"] for c in chips]
                  == [BY_ID[e]["label"] for e in ELEMENTS],
                  [c["label"] for c in chips])
            check("every chip carries its spec",
                  all(c["spec"] for c in chips),
                  [c["label"] for c in chips if not c["spec"]])
            check("specs are the config's own wording",
                  [c["spec"] for c in chips]
                  == [BY_ID[e]["spec"] for e in ELEMENTS],
                  [c["spec"] for c in chips])
            check("paid chips are one to a row",
                  len({c["top"] for c in chips}) == 6,
                  sorted({c["top"] for c in chips}))
            check("the paid strip drops the free subline",
                  page.query_selector(".section-elements .elements-sub") is None)
            check("no paywall furniture in the paid view",
                  page.eval_on_selector("#cta", "n => n.hidden") is True)
            check("the commerce block stays out of the paid view",
                  page.eval_on_selector("#commerce", "n => n.hidden")
                  and page.eval_on_selector("#commerce",
                                            "n => n.children.length === 0"))
            check("the sticky bar never shows to somebody who has paid",
                  page.eval_on_selector("#sticky-cta", "n => n.hidden"))
            check("no mid-CTA in the paid view",
                  page.query_selector("#mid-offer") is None)
            check("no horizontal overflow",
                  page.evaluate("document.documentElement.scrollWidth <= 390"),
                  page.evaluate("document.documentElement.scrollWidth"))

            # --- the document's own photographs --------------------------
            board = page.eval_on_selector_all(".palette-board", """(ns, want) =>
                ns.map(n => ({
                    src: n.querySelector('img').getAttribute('src'),
                    ready: n.querySelector('img').naturalWidth > 0,
                    cap: (n.querySelector('figcaption')||{}).textContent,
                    inPalette: !!n.closest('.section')
                      && n.closest('.section').querySelector('.section-title')
                         .textContent === want}))""",
                TITLES["palette"])
            check("the palette opens on the board they chose",
                  len(board) == 1 and board[0]["src"].endswith("mp5.webp")
                  and board[0]["inPalette"], board)
            check("  the image actually loads", board and board[0]["ready"])
            check("  captioned with the label from the quiz",
                  board and board[0]["cap"] == "Moss & earth", board)
            shots = page.eval_on_selector_all(".material-shot", """ns => ns.map(
                n => ({src: n.querySelector('img').getAttribute('src'),
                       ready: n.querySelector('img').naturalWidth > 0,
                       cap: (n.querySelector('figcaption')||{}).textContent}))""")
            check("materials opens on the two surfaces they picked",
                  [s["src"].rsplit("/", 1)[-1] for s in shots]
                  == ["c4b.webp", "b8a.webp"], shots)
            check("  both load", all(s["ready"] for s in shots))
            check("  both captioned",
                  [s["cap"] for s in shots] == ["Living wood", "Warm texture"],
                  shots)
            check("the strip sits above the verdicts",
                  page.evaluate("""() => {
                    const s = document.querySelector('.material-strip'),
                          v = document.querySelector('.verdict-list');
                    return !!s && !!v && (s.compareDocumentPosition(v)
                      & Node.DOCUMENT_POSITION_FOLLOWING) > 0; }"""))
            check("the swatches are bigger in the paid view",
                  page.eval_on_selector(
                      ".swatch-dot",
                      "n => Math.round(n.getBoundingClientRect().width)") == 56,
                  page.eval_on_selector(
                      ".swatch-dot",
                      "n => n.getBoundingClientRect().width"))
            check("elements still sit between the palette and materials",
                  titles(page).index("Your Style Elements")
                  == titles(page).index(TITLES["palette"]) + 1
                  and titles(page).index("Your Style Elements")
                  < titles(page).index(TITLES["materials"]), titles(page))
            check("sections breathe wider than the preview does",
                  page.eval_on_selector(
                      "#report .section + .section",
                      """n => { const s = getComputedStyle(n);
                         return parseFloat(s.marginTop) + parseFloat(s.paddingTop); }""")
                  == 60,
                  page.eval_on_selector(
                      "#report .section + .section",
                      "n => getComputedStyle(n).marginTop + '/' + getComputedStyle(n).paddingTop"))
            check("no page errors", not errors, errors[:3])

            page.locator(".section-elements").scroll_into_view_if_needed()
            page.screenshot(path=os.path.join(SHOTS, "shot-paid-elements.png"))
            page.screenshot(path=os.path.join(SHOTS, "shot-paid-full.png"),
                            full_page=True)
            browser.close()
    finally:
        httpd.shutdown()

    print("\n%d failed" % len(fails))
    for f in fails:
        print("  FAIL " + f)
    return 1 if fails else 0


if __name__ == "__main__":
    raise SystemExit(main())
