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
        # What the upload request carried besides the photograph. The whole
        # pre-purchase render turns on the browser naming the style it
        # computed, and until this was recorded nothing here could see whether
        # it did.
        self.upload_fields = []

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


def multipart_fields(raw, content_type):
    """The non-file parts of a multipart body, as {name: value}.

    Written out rather than pulled in, for the same reason `_multipart` in
    visualizer.py is: one body, four headers, and a dependency that has to be
    installed before the suite runs is a worse trade.
    """
    marker = "boundary="
    if marker not in content_type:
        return {}
    boundary = content_type.split(marker, 1)[1].strip().strip('"')
    out = {}
    for part in raw.split(("--" + boundary).encode()):
        if b"\r\n\r\n" not in part:
            continue
        head, body = part.split(b"\r\n\r\n", 1)
        head = head.decode("utf-8", "replace")
        if 'filename="' in head:
            continue                      # the photograph itself
        if 'name="' not in head:
            continue
        name = head.split('name="', 1)[1].split('"', 1)[0]
        out[name] = body.rstrip(b"\r\n-").decode("utf-8", "replace")
    return out


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
            S.upload_fields.append(
                multipart_fields(raw, self.headers.get("content-type") or ""))
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
            # This asserted a `.viz-price` line inside the card, which was the
            # contract before `checkout.price_after_upload` shipped. It is the
            # opposite now, deliberately: nothing on this page names a price
            # until there is a photograph to price, and the foot of the offer
            # asks for the photograph instead. The property is still worth a
            # check — it is just the other way round.
            check("no price is named before a photo is asked for",
                  page.query_selector(".viz-price") is None
                  and not page.evaluate(
                      """() => Array.from(document.querySelectorAll(
                           '#result-body *')).some(function (n) {
                           return n.children.length === 0
                             && n.offsetParent !== null
                             && /\$\d/.test(n.textContent)
                             && !n.closest('.offer-value'); })"""))
            check("  and the offer asks for the kitchen instead",
                  page.is_visible(".offer-gate__cta"))
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

            print("\n--- what the upload told the server ---")
            # The server cannot know which of the four styles thirteen taps
            # produced: a session has no row and no report, and the winner is
            # computed in the browser. So the upload has to name it, and if it
            # does not, `_pre_purchase_content` finds no style, `build_prompt`
            # returns None, and every pre-purchase render fails `no_prompt`
            # before an image is ever asked for.
            #
            # This is the link nothing was testing. `run_pre_render` was called
            # directly with the style as a Python argument, so the wire — the
            # one part that was broken — was the only part with no test on it.
            fields = S.upload_fields[-1] if S.upload_fields else {}
            style_ids = [st["id"] for st in CFG["kitchen-visualizer"]["styles"]]
            check("the upload named a style", bool(fields.get("style")),
                  fields)
            check("  and it is one this funnel can actually produce",
                  fields.get("style") in style_ids,
                  (fields.get("style"), style_ids))
            names = [st["name"] for st in CFG["kitchen-visualizer"]["styles"]]
            check("  it is the id, not the display name",
                  fields.get("style") not in names, fields.get("style"))
            check("  and it is the style this run was actually given",
                  fields.get("style") == page.eval_on_selector(
                      "#result-name",
                      "n => (%s)[n.textContent] || null"
                      % json.dumps(dict(zip(names, style_ids)))),
                  (fields.get("style"), page.inner_text("#result-name")))
            element_ids = [i["id"] for i
                           in CFG["kitchen-visualizer"]["style_elements"]["items"]]
            sent = [e for e in (fields.get("elements") or "").split(",") if e]
            check("  and the elements it showed came too",
                  len(sent) == 4 and all(e in element_ids for e in sent),
                  sent)

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

            print("\n--- what the offer says once the photo is in ---")
            # The six-row manifest this used to read is off this funnel's page:
            # the result-page rebuild replaced it with three value cards, and
            # this funnel carries no `checkout.manifest` at all any more. What
            # the block has to say at this point is that the gate is down, the
            # price is finally named, and the reader is told what paying sends.
            check("the manifest is gone from this funnel",
                  page.eval_on_selector_all(".commerce .manifest-row",
                                            "n => n.length") == 0
                  and "manifest" not in CFG["kitchen-visualizer"]["checkout"])
            check("the gate is down now that a photo exists",
                  not page.is_visible(".offer-gate__cta"))
            check("  so the price is named, once",
                  page.eval_on_selector_all(
                      "#commerce .price-now",
                      "ns => ns.filter(n => n.offsetParent !== null).length")
                  == 1)
            # The rows are built and reserved from the first render, so on
            # this suite — whose stub never reports a teaser — they are in the
            # document and deliberately not shown: "this image, unblurred"
            # would be pointing at a blur of the reader's own kitchen.
            check("  what unlocking sends is spelled out, in two rows",
                  page.eval_on_selector_all(".viz-deliver__row",
                                            "n => n.length") == 2)
            check("  they sit above the pay control, not below it",
                  page.evaluate("""() => {
                    var d = document.querySelector('.viz-deliver'),
                        b = document.querySelector('.viz-go--teaser');
                    return !!d && !!b && d.getBoundingClientRect().bottom
                           <= b.getBoundingClientRect().top + 1; }"""))
            check("  and hidden while there is no render to point at",
                  page.eval_on_selector(
                      ".viz-deliver",
                      "n => getComputedStyle(n).visibility") == "hidden")
            check("  in a tinted panel rather than loose on the page",
                  page.eval_on_selector(".viz-deliver", """n => {
                      var s = getComputedStyle(n);
                      return s.backgroundColor === 'rgb(253, 241, 231)'
                             && s.borderTopWidth === '1px'
                             && s.borderTopLeftRadius === '11px'
                             && s.paddingTop === '14px'; }"""),
                  page.eval_on_selector(".viz-deliver", """n => {
                      var s = getComputedStyle(n);
                      return [s.backgroundColor, s.borderTopWidth,
                              s.borderTopLeftRadius, s.paddingTop]; }"""))
            # The line naming what this is NOT, deleted from this funnel. It
            # was placed above the value cards, where it framed them; three
            # cards with icons say the same thing by showing what IS included,
            # and a sentence about what a reader is not getting is a doubt
            # planted in front of the offer.
            check("  the expectation line is off this funnel",
                  page.eval_on_selector_all(".offer-expectation",
                                            "n => n.length") == 0
                  and "expectation"
                  not in CFG["kitchen-visualizer"]["checkout"])
            # Three cards, each with a circular badge, and the hero's mark
            # filled where the other two are stroked.
            cards = page.eval_on_selector_all(".offer-value__row", """ns =>
                ns.map(n => {
                  var s = getComputedStyle(n);
                  var b = n.querySelector('.offer-value__badge');
                  var i = n.querySelector('.offer-value__icon');
                  return {hero: n.classList.contains('is-hero'),
                          badge: b ? Math.round(
                            b.getBoundingClientRect().width) : 0,
                          radius: b ? getComputedStyle(b).borderTopLeftRadius
                                    : null,
                          fill: i ? getComputedStyle(i).fill : null,
                          border: s.borderTopWidth,
                          bg: s.backgroundColor}; })""")
            check("  three value cards, each badged",
                  len(cards) == 3 and all(c["badge"] >= 20 for c in cards),
                  [c["badge"] for c in cards])
            check("  the badges are circles",
                  all(c["radius"] == "50%" for c in cards),
                  [c["radius"] for c in cards])
            check("  the hero is filled, tinted and bordered 3px",
                  cards[0]["hero"] and cards[0]["fill"] == "rgb(192, 86, 33)"
                  and cards[0]["border"] == "3px"
                  and cards[0]["bg"] == "rgb(253, 241, 231)",
                  cards[0])
            check("  and the other two are stroked, white and 2px",
                  all(c["fill"] == "none" and c["border"] == "2px"
                      and c["bg"] == "rgb(255, 255, 255)" for c in cards[1:]),
                  cards[1:])
            check("  the replace link is gone from the teaser",
                  page.query_selector(".viz-pair-teaser ~ .viz-replace") is None
                  and page.eval_on_selector_all(
                      "#visualizer .viz-replace", "n => n.length") == 0)

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
            # Waited for rather than asked about. An <img> that has not decoded
            # yet has no box, so "is it visible" answers no for a picture that
            # is on its way — a flake that says the photo was lost when it was
            # merely late.
            page.wait_for_function(
                """() => { const i = document.querySelector(
                     '.viz-shot .viz-img');
                   return i && i.complete && i.naturalWidth > 0; }""",
                timeout=15000)
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

            print("\n--- somebody who never uploaded cannot pay yet ---")
            # This walked to the offer and paid without a photograph, then
            # uploaded on the paid page. That route is closed on purpose: the
            # upload gate refuses to show any pay control until a kitchen
            # exists, because a wallet purchase with no photograph attached is
            # a buyer who has paid for a transformation of nothing. What the
            # section checks now is that the gate really is what stops them,
            # and that it says so rather than simply showing a dead button.
            S.reset()
            page = browser.new_page(viewport={"width": 390, "height": 844})
            no_stripe(page)
            errors = []
            page.on("pageerror", lambda e: errors.append(str(e)))
            page.goto("http://127.0.0.1:%d/kitchen-visualizer" % PORT)
            walk(page, "kitchen-visualizer")
            page.wait_for_selector("#commerce:not([hidden])", timeout=15000)
            page.wait_for_timeout(700)
            check("no pay control is on the page at all",
                  page.eval_on_selector_all(
                      "#commerce button",
                      """ns => ns.filter(n => n.offsetParent !== null)
                           .map(n => n.className)""") == ["offer-gate__cta"],
                  page.eval_on_selector_all(
                      "#commerce button",
                      """ns => ns.filter(n => n.offsetParent !== null)
                           .map(n => n.className)"""))
            check("  and the reader is told what is missing",
                  page.inner_text(".offer-gate__cta").strip().endswith(
                      CFG["kitchen-visualizer"]["checkout"]["gate_cta"]),
                  page.inner_text(".offer-gate__cta"))
            check("  nothing was checked out", not S.checkouts, S.checkouts)
            # Tapping it sends them back to the picker rather than to Stripe.
            page.click(".offer-gate__cta")
            page.wait_for_timeout(900)
            check("  tapping it goes to the picker, not to a payment",
                  page.is_visible(".viz-drop") and not S.checkouts)
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
