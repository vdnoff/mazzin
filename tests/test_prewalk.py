#!/usr/bin/env python3
"""The whole arc, in a browser: photo first, money second, render third.

Walks the quiz on /kitchen-visualizer, uploads a kitchen from the free result
page, checks the teaser that upload produces — their photograph beside the same
photograph behind a lock — then buys, comes back from Stripe, and finds the
photo already there and the transformation one tap away.

The server here is a stub, but the migration it models is the real one: the
pending photo is keyed by session and the "webhook" moves it to the purchase,
so what the paid page opens on is a file that arrived before the money.

    python3 prewalk.py
"""
import io
import json
import os
import socketserver
import sys
import threading
import time

# The repo root, derived from this file rather than hardcoded: a suite
# that only runs from one absolute path is a suite that stops running the
# first time the checkout moves.
REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from PIL import Image                                    # noqa: E402
from playwright.sync_api import sync_playwright          # noqa: E402
from test_walk import Handler as WalkHandler, PORT, ANCHORS   # noqa: E402

ROOT = REPO
SHOTS = os.path.dirname(os.path.abspath(__file__))
CHROME = "/opt/pw-browsers/chromium-1194/chrome-linux/chrome"

CFG = {slug: json.load(open(os.path.join(ROOT, "funnels/%s.json" % slug)))
       for slug in ("kitchen", "kitchen-visualizer")}
VIZ = CFG["kitchen-visualizer"]["visualizer"]

fails = []
checks = [0]


def check(label, ok, detail=""):
    checks[0] += 1
    if not ok:
        fails.append("%s %s" % (label, detail))
    print("  %-64s %s%s" % (label, "ok" if ok else "FAIL",
                            ("  " + str(detail)) if not ok else ""))


def jpeg(size=(900, 600), colour=(190, 120, 70)):
    out = io.BytesIO()
    Image.new("RGB", size, colour).save(out, "JPEG")
    return out.getvalue()


class Server:
    """Enough of the four endpoints to model the pre/post split honestly."""

    def __init__(self):
        self.reset()

    def reset(self):
        self.pending = {}         # session_id -> photo bytes
        self.purchases = {}       # cs -> {session, generations, status, ...}
        self.events = []          # (event, extra)
        self.checkouts = []
        self.generates = 0

    # -- the split the whole feature turns on --
    def who(self, query):
        cs = query.get("cs")
        if cs:
            return ("paid", cs)
        sid = query.get("session_id")
        if sid:
            return ("pre", sid)
        return (None, None)

    def status(self, kind, key):
        if kind == "pre":
            have = key in self.pending
            body = {"status": "uploaded" if have else "none", "paid": False,
                    "generations": 0,
                    "max_generations": VIZ["max_generations"],
                    "remaining": VIZ["max_generations"], "has_source": have}
            if have:
                body["source_url"] = ("/api/visualizer/image?which=source"
                                      "&session_id=%s&funnel=kitchen-visualizer"
                                      % key)
            return body

        row = self.purchases.get(key) or {}
        used = row.get("generations", 0)
        body = {"status": row.get("status", "none"), "paid": True,
                "generations": used,
                "max_generations": VIZ["max_generations"],
                "remaining": max(0, VIZ["max_generations"] - used),
                "has_source": bool(row.get("photo")),
                "source_url": "/api/visualizer/image?which=source&cs=" + key}
        if row.get("status") == "ready":
            body["url"] = ("/api/visualizer/image?which=result&cs=%s&v=%d"
                           % (key, used))
        return body

    def buy(self, cs, session_id):
        """The webhook. Moves the pending photo onto the purchase."""
        row = {"session": session_id, "generations": 0, "status": "none",
               "photo": None}
        photo = self.pending.pop(session_id, None)
        if photo is not None:
            row["photo"] = photo
            row["status"] = "uploaded"
        self.purchases[cs] = row
        return row


S = Server()


def report_body():
    cfg = CFG["kitchen-visualizer"]
    titles = {s["id"]: s["title"] for s in cfg["report"]["sections"]}
    data = {
        "palette": {"intro": "Three colours carry this room.",
                    "colors": [{"name": "Oat Linen", "hex": "#E5DAC8",
                                "role": "dominant", "finish": "matt",
                                "where": "the cream you kept choosing"}],
                    "closing_rule": "Sixty oat, thirty oak, ten clay."},
        "mistakes": {"items": [{"title": "Matching every wood tone",
                                "body": "Three identical oaks read as laminate.",
                                "fix": "Age one piece past the rest."}]},
        "materials": {"intro": "Aged brass against smoked oak.",
                      "pairs": [{"combo": "Oak + marble", "verdict": "works",
                                 "why": "One cold thing in a warm room."}],
                      "rule": "One warm metal, one cold stone."},
        "shopping": {"items": [{"name": "The table",
                                "priority_note": "Buy it first."}], "skip": []},
        "dna": {"narrative": ["Your picks lean warm."],
                "implications": ["Buy the timber first."]},
        "splurge": {"splurge": {"item": "The joinery",
                                "why": "It is the thing you touch."},
                    "saves": [{"item": "Appliances", "why": "They all cook."}],
                    "split_note": "Spend up, save down."},
    }
    return {
        "complete": True, "email_masked": "s***@example.com",
        "report": {
            "version": "llm-2", "funnel": "kitchen-visualizer",
            "style_id": "modern_rustic", "style_name": "Modern Rustic",
            "elements": ["brass-hardware", "stone-worktop", "oak-wood",
                         "open-shelving", "statement-pendants", "slate-floor"],
            "visuals": {"moodboard": "mp5", "materials": ["c4b", "b8a"]},
            "sections": [{"id": s["id"], "title": titles[s["id"]],
                          "data": data[s["id"]]}
                         for s in cfg["report"]["sections"]],
        },
    }


def parse_query(path):
    out = {}
    if "?" not in path:
        return out
    for bit in path.split("?", 1)[1].split("&"):
        if "=" in bit:
            k, v = bit.split("=", 1)
            out[k] = v.replace("%2F", "/")
    return out


class Handler(WalkHandler):

    def do_GET(self):
        path = self.path.split("?")[0]
        query = parse_query(self.path)
        if path == "/api/pixel-config":
            return self._json({})
        if path == "/api/report":
            return self._json(report_body())
        if path == "/api/visualizer/status":
            kind, key = S.who(query)
            if not kind:
                return self._json({"error": "bad_token"}, 400)
            return self._json(S.status(kind, key))
        if path == "/api/visualizer/image":
            kind, key = S.who(query)
            if kind == "pre":
                raw = S.pending.get(key)
            else:
                row = S.purchases.get(key) or {}
                raw = (row.get("photo") if query.get("which") == "source"
                       else row.get("render"))
            if not raw:
                return self._json({"error": "not_found"}, 404)
            return self._bytes(raw, "image/jpeg")
        if path in ("/kitchen", "/kitchen-visualizer"):
            self.path = "/static/funnel.html"
        return super().do_GET()

    def do_POST(self):
        path = self.path.split("?")[0]
        query = parse_query(self.path)
        raw = self.rfile.read(int(self.headers.get("content-length") or 0))

        if path == "/api/track":
            try:
                body = json.loads(raw.decode("utf-8"))
                S.events.append((body["event"], body.get("extra")))
            except Exception:
                pass
            self.send_response(204)
            self.end_headers()
            return

        if path == "/api/visualizer/upload":
            kind, key = S.who(query)
            if not kind:
                return self._json({"error": "bad_token"}, 400)
            photo = jpeg(colour=(30, 120, 60))
            if kind == "pre":
                S.pending[key] = photo
            else:
                S.purchases.setdefault(key, {"generations": 0})
                S.purchases[key].update(photo=photo, status="uploaded")
            return self._json(S.status(kind, key))

        if path == "/api/visualizer/generate":
            kind, key = S.who(query)
            if kind != "paid":
                return self._json({"error": "bad_token"}, 400)
            S.generates += 1
            row = S.purchases[key]
            row["generations"] += 1
            row["status"] = "ready"
            row["render"] = jpeg((1024, 1024), (30, 60, 130))
            return self._json(S.status(kind, key))

        if path == "/api/checkout":
            body = json.loads(raw.decode("utf-8"))
            S.checkouts.append(body)
            cs = "cs_test_prewalk"
            # The webhook, modelled: the purchase is created from the session
            # the checkout carried, and it takes the pending photo with it.
            S.buy(cs, body["session_id"])
            return self._json({"url": "http://127.0.0.1:%d/%s?cs=%s"
                                      % (PORT, body["funnel"], cs)})

        self.send_response(204)
        self.end_headers()

    def _bytes(self, raw, mime, code=200):
        self.send_response(code)
        self.send_header("Content-Type", mime)
        self.send_header("Content-Length", str(len(raw)))
        self.end_headers()
        self.wfile.write(raw)

    def _json(self, body, code=200):
        self._bytes(json.dumps(body).encode(), "application/json", code)


def walk(page, slug):
    steps = CFG[slug]["swipe"]["steps"]
    page.wait_for_selector("#cards .card", timeout=10000)
    for index, step in enumerate(steps):
        page.query_selector_all("#cards .card")[0].click()
        done = index + 1
        if done in ANCHORS and done < len(steps):
            page.wait_for_selector("#screen-interstitial.is-active",
                                   timeout=12000)
            page.click("#mid-cta")
        if done < len(steps):
            page.wait_for_function(
                "q => document.getElementById('swipe-caption').textContent === q",
                arg=steps[done]["question"], timeout=15000)
    page.wait_for_selector("#result-body:not([hidden])", timeout=20000)
    page.wait_for_timeout(600)


def photo_file(tmp, name="kitchen.jpg"):
    path = os.path.join(tmp, name)
    with open(path, "wb") as fh:
        fh.write(jpeg())
    return path


# This box has no route to js.stripe.com, and the kitchen-visualizer paywall now
# asks for one. Answered here with an empty script: window.Stripe stays
# undefined, engine.js takes its no-wallet fallback, and the run is not polluted
# by a tunnel error that says nothing about what is under test. express.py is
# where that path is actually exercised.
def no_stripe(page):
    page.route("https://js.stripe.com/**",
               lambda r: r.fulfill(status=200,
                                   content_type="application/javascript",
                                   body=""))
    return page


def main():
    socketserver.TCPServer.allow_reuse_address = True
    httpd = socketserver.TCPServer(("127.0.0.1", PORT), Handler)
    threading.Thread(target=httpd.serve_forever, daemon=True).start()
    tmp = os.path.join(SHOTS, "prefiles")
    os.makedirs(tmp, exist_ok=True)

    try:
        with sync_playwright() as pw:
            browser = pw.chromium.launch(executable_path=CHROME)

            print("\n--- the free result, before a photo ---")
            S.reset()
            page = browser.new_page(viewport={"width": 390, "height": 844},
                                    device_scale_factor=2)
            no_stripe(page)
            errors = []
            page.on("pageerror", lambda e: errors.append(str(e)))
            page.on("console",
                    lambda m: errors.append(m.text) if m.type == "error"
                    else None)
            page.on("response", lambda r: errors.append(
                "%d %s" % (r.status, r.url)) if r.status >= 400 else None)
            page.goto("http://127.0.0.1:%d/kitchen-visualizer" % PORT)
            walk(page, "kitchen-visualizer")

            check("the section is on the free page", page.is_visible("#visualizer"))
            check("  at the top of the report",
                  page.eval_on_selector(
                      "#report", "n => n.firstElementChild.id") == "visualizer",
                  page.eval_on_selector("#report",
                                        "n => n.firstElementChild.id"))
            check("  with the picker showing", page.is_visible(".viz-drop"))
            check("the price is on screen before a photo is asked for",
                  page.inner_text(".viz-price")
                  == "Your transformation + full report — $7, one-time",
                  page.inner_text(".viz-price"))
            check("  and what happens to the photo is answered unprompted",
                  page.inner_text(".viz-privacy") == VIZ["privacy_note"],
                  page.inner_text(".viz-privacy"))
            check("nothing is locked yet",
                  page.query_selector(".viz-half.is-locked") is None)
            page.screenshot(path=os.path.join(SHOTS, "shot-pre-empty.png"),
                            full_page=True)

            print("\n--- uploading before paying ---")
            page.set_input_files(".viz-drop .viz-file", photo_file(tmp))
            page.wait_for_selector(".viz-pair-teaser", timeout=10000)
            check("the photo reached the server under the session",
                  len(S.pending) == 1, list(S.pending))
            check("  and no purchase was involved", not S.purchases, S.purchases)
            # The payload gained `path` — which of the three ways the photo
            # was shrunk actually ran — so this asserts the fields it cares
            # about rather than the whole dict.
            ups = [e[1] for e in S.events if e[0] == "viz_upload"]
            check("viz_upload was counted as the pre phase",
                  ups and ups[-1].get("phase") == "pre", ups)
            check("  carrying which shrink path the browser took",
                  ups and ups[-1].get("path")
                  in ("bitmap", "canvas", "raw"), ups)

            print("\n--- the teaser ---")
            halves = page.eval_on_selector_all(
                ".viz-pair-teaser .viz-half",
                """ns => ns.map(n => ({locked: n.classList.contains('is-locked'),
                     caption: n.querySelector('.viz-caption').textContent,
                     src: n.querySelector('img').getAttribute('src')}))""")
            check("two panels", len(halves) == 2, len(halves))
            check("  the left one is their kitchen",
                  halves[0]["caption"] == VIZ["before_label_pre"]
                  and not halves[0]["locked"], halves[0])
            check("  the right one is locked",
                  halves[1]["locked"], halves[1])
            # Read off the page rather than hardcoded: which style this walk
            # lands on is a property of the scoring, and the point of the
            # check is that the label is *theirs*, whichever one it is.
            named = page.inner_text("#result-name")
            check("  and names the style they were actually given",
                  halves[1]["caption"] == "Your %s transformation" % named,
                  (halves[1]["caption"], named))
            check("  which is a real style from the config",
                  named in [s["name"] for s in
                            CFG["kitchen-visualizer"]["styles"]], named)
            check("the locked panel is THEIR photo, not a placeholder",
                  halves[0]["src"] == halves[1]["src"], halves)
            check("  blurred rather than hidden",
                  "blur" in page.eval_on_selector(
                      ".viz-half.is-locked .viz-img",
                      "n => getComputedStyle(n).filter"),
                  page.eval_on_selector(".viz-half.is-locked .viz-img",
                                        "n => getComputedStyle(n).filter"))
            check("  with a padlock over it",
                  page.is_visible(".viz-half.is-locked .viz-lock"))
            check("  and both images really loaded",
                  page.eval_on_selector_all(
                      ".viz-pair-teaser img",
                      "ns => ns.every(n => n.naturalWidth > 0)"))
            check("viz_teaser_view fired once",
                  [e[0] for e in S.events].count("viz_teaser_view") == 1,
                  [e[0] for e in S.events])
            page.screenshot(path=os.path.join(SHOTS, "shot-pre-teaser.png"),
                            full_page=True)

            print("\n--- the manifest notices ---")
            rows = page.eval_on_selector_all(
                ".commerce .manifest-row .manifest-text",
                "ns => ns.map(n => n.textContent)")
            check("the first row says the photo is already in",
                  rows[0] == VIZ["manifest_uploaded"], rows[0])
            check("  and the rest of the list is untouched",
                  rows[1:] == CFG["kitchen-visualizer"]["checkout"]["manifest"][1:],
                  rows[1:3])

            print("\n--- tapping the lock asks for the money ---")
            before = page.evaluate("window.scrollY")
            page.click(".viz-half.is-locked")
            page.wait_for_timeout(900)
            check("it scrolls to the offer rather than doing anything else",
                  page.evaluate("window.scrollY") > before,
                  (before, page.evaluate("window.scrollY")))
            check("  and nothing was generated",
                  S.generates == 0, S.generates)

            print("\n--- buying ---")
            page.click("#pay-button")
            page.wait_for_url("**/kitchen-visualizer?cs=*", timeout=10000)
            check("the checkout carried the session the photo is filed under",
                  S.checkouts[-1]["session_id"] in
                  (list(S.purchases.values())[0]["session"],), S.checkouts[-1]
                  ["session_id"])
            check("the webhook moved the photo onto the purchase",
                  bool(list(S.purchases.values())[0]["photo"])
                  and not S.pending, (S.purchases, S.pending))

            print("\n--- and the paid page opens on it ---")
            page.wait_for_selector("#result-body:not([hidden])", timeout=20000)
            page.wait_for_selector("#visualizer .viz-go", timeout=20000)
            check("no picker — the photo is already theirs",
                  page.query_selector(".viz-drop") is None)
            check("  their photo is on screen",
                  page.is_visible(".viz-shot .viz-img"))
            check("  and the transform button is one tap away",
                  page.inner_text(".viz-go") == VIZ["generate_cta"],
                  page.inner_text(".viz-go"))
            check("  with no price line on a page already paid for",
                  page.query_selector(".viz-price") is None)

            page.click(".viz-go")
            page.wait_for_selector(".viz-pair:not(.viz-pair-teaser)",
                                   timeout=20000)
            check("generation runs on the photo uploaded before the money",
                  S.generates == 1, S.generates)
            check("  and the before/after is on screen",
                  page.eval_on_selector_all(".viz-half", "n => n.length") == 2)
            check("  with nothing locked left",
                  page.query_selector(".viz-half.is-locked") is None)
            check("no page errors on the whole arc", not errors, errors[:3])
            page.screenshot(path=os.path.join(SHOTS, "shot-pre-paid.png"),
                            full_page=True)
            page.close()

            print("\n--- somebody who never uploaded still gets the old flow ---")
            S.reset()
            page = browser.new_page(viewport={"width": 390, "height": 844})
            no_stripe(page)
            errors = []
            page.on("pageerror", lambda e: errors.append(str(e)))
            page.goto("http://127.0.0.1:%d/kitchen-visualizer" % PORT)
            walk(page, "kitchen-visualizer")
            page.click("#pay-button")
            page.wait_for_url("**/kitchen-visualizer?cs=*", timeout=10000)
            page.wait_for_selector("#visualizer", timeout=20000)
            page.wait_for_selector(".viz-drop", timeout=20000)
            check("the paid page asks for a photo, as it did before any of this",
                  page.is_visible(".viz-drop"))
            page.set_input_files(".viz-drop .viz-file", photo_file(tmp))
            page.wait_for_selector(".viz-go", timeout=10000)
            check("  and uploading there still works",
                  bool(list(S.purchases.values())[0]["photo"]))
            ups = [e[1] for e in S.events if e[0] == "viz_upload"]
            check("  counted as the post phase",
                  ups and ups[-1].get("phase") == "post", ups)
            check("no page errors", not errors, errors[:3])
            page.close()

            print("\n--- /kitchen has none of it ---")
            S.reset()
            page = browser.new_page(viewport={"width": 390, "height": 844})
            no_stripe(page)
            errors = []
            page.on("pageerror", lambda e: errors.append(str(e)))
            page.on("response", lambda r: errors.append(
                "%d %s" % (r.status, r.url)) if r.status >= 400 else None)
            page.goto("http://127.0.0.1:%d/kitchen" % PORT)
            walk(page, "kitchen")
            check("no visualizer section",
                  page.query_selector("#visualizer") is None)
            check("  nothing of it anywhere",
                  page.eval_on_selector_all("[class*='viz-']",
                                            "n => n.length") == 0)
            check("  and it never asked the server about one",
                  not S.pending and not S.events
                  or all(e[0] != "viz_upload" for e in S.events))
            rows = page.eval_on_selector_all(
                ".commerce .manifest-row .manifest-text",
                "ns => ns.map(n => n.textContent)")
            check("the manifest is exactly the config's",
                  rows == CFG["kitchen"]["checkout"]["manifest"], rows[:2])
            check("no page errors", not errors, errors[:3])
            browser.close()
    finally:
        httpd.shutdown()

    print("\n%d checks, %d failed" % (checks[0], len(fails)))
    for f in fails:
        print("  FAIL " + f)
    return 1 if fails else 0


if __name__ == "__main__":
    raise SystemExit(main())
