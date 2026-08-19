#!/usr/bin/env python3
"""The visualizer section in a real browser, through its whole state machine.

Serves the two funnels and a stub of the four visualizer endpoints that behaves
like the real ones — a status the client polls, an upload that changes it, a
generation that takes a beat and then produces a picture. The engine is the
shipping engine, so what is checked is what a buyer would actually see.

Walks: none -> uploaded -> generating -> ready -> regenerate -> spent, the
failure path and its retry, the reload-mid-render path, the lightbox, and
/kitchen, which must show none of it.

    python3 vizui.py
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
CS = "cs_test_uiwalk"

CFG = {slug: json.load(open(os.path.join(ROOT, "funnels/%s.json" % slug)))
       for slug in ("kitchen", "kitchen-visualizer")}
VIZ = CFG["kitchen-visualizer"]["visualizer"]
VCO = CFG["kitchen-visualizer"]["checkout"]
VCOM = VCO["commerce"]

fails = []
checks = [0]


def check(label, ok, detail=""):
    checks[0] += 1
    if not ok:
        fails.append("%s %s" % (label, detail))
    print("  %-62s %s%s" % (label, "ok" if ok else "FAIL",
                            ("  " + str(detail)) if not ok else ""))


def jpeg(size=(900, 600), colour=(190, 120, 70)):
    out = io.BytesIO()
    Image.new("RGB", size, colour).save(out, "JPEG")
    return out.getvalue()


# --- a server that behaves like the real endpoints -------------------------

class State:
    def __init__(self):
        self.reset()

    def reset(self):
        # Every attempt to create a PaymentIntent, counted. The offer block is
        # not allowed to make one while the render is still running, and the
        # only way to prove that is to count them where they would land.
        self.intents = 0
        self.status = "none"
        self.generations = 0
        self.has_source = False
        self.fail_next = False
        self.take_s = 0.6
        self.due = None
        self.events = []
        self.uploads = 0
        self.generates = 0
        self.server_lacks_it = False
        # The pre-purchase render, as the status endpoint reports it: absent,
        # being made, finished, or given up on.
        self.teaser = None
        self.country = None

    def tick(self):
        """The render finishing, on its own clock, like a worker would."""
        if self.status == "generating" and self.due and time.time() > self.due:
            self.due = None
            if self.fail_next:
                self.fail_next = False
                self.generations -= 1          # the credit comes back
                self.status = "failed"
            else:
                self.status = "ready"

    def body(self):
        self.tick()
        out = {"status": self.status, "generations": self.generations,
               "max_generations": VIZ["max_generations"],
               "remaining": max(0, VIZ["max_generations"] - self.generations),
               "has_source": self.has_source}
        if self.status == "ready":
            out["url"] = ("/api/visualizer/image?which=result&cs=%s&v=%d"
                          % (CS, self.generations))
        if self.status == "failed":
            out["retriable"] = True
            out["message"] = VIZ["error_text"]
        if self.teaser:
            out["teaser"] = self.teaser
            if self.teaser == "ready":
                out["teaser_url"] = ("/api/visualizer/image?which=teaser&cs="
                                     + CS)
        if self.country:
            out["country"] = self.country
        return out


S = State()


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


class Handler(WalkHandler):

    def do_GET(self):
        path = self.path.split("?")[0]
        if path == "/api/pixel-config":
            return self._json({})
        if path == "/api/report":
            return self._json(report_body())
        if path == "/api/visualizer/status":
            if S.server_lacks_it:
                self.send_response(404)
                body = json.dumps({"error": "no_visualizer"}).encode()
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)
                return
            return self._json(S.body())
        if path == "/api/visualizer/image":
            if "which=teaser" in self.path:
                # Deliberately a different size as well as a different colour:
                # the real one is a downscale, and the panel must not care.
                return self._bytes(jpeg(size=(373, 560), colour=(40, 90, 60)),
                                   "image/jpeg")
            which = "result" if "which=result" in self.path else "source"
            colour = (30, 60, 120) if which == "result" else (190, 120, 70)
            return self._bytes(jpeg(colour=colour), "image/jpeg")
        if path in ("/kitchen", "/kitchen-visualizer"):
            self.path = "/static/funnel.html"
        return super().do_GET()

    def do_POST(self):
        path = self.path.split("?")[0]
        raw = self.rfile.read(int(self.headers.get("content-length") or 0))
        if path == "/api/track":
            try:
                S.events.append(json.loads(raw.decode("utf-8"))["event"])
            except Exception:
                pass
            self.send_response(204)
            self.end_headers()
            return
        if path == "/api/visualizer/upload":
            S.uploads += 1
            S.has_source = True
            S.status = "uploaded"
            return self._json(S.body())
        if path == "/api/payment-intent":
            S.intents += 1
            return self._json({"client_secret": "pi_test_secret",
                               "publishable_key": "pk_test_x"})
        if path == "/api/visualizer/generate":
            S.generates += 1
            S.generations += 1
            S.status = "generating"
            S.due = time.time() + S.take_s
            return self._json(S.body())
        self.send_response(204)
        self.end_headers()

    def _bytes(self, raw, mime):
        self.send_response(200)
        self.send_header("Content-Type", mime)
        self.send_header("Content-Length", str(len(raw)))
        self.end_headers()
        self.wfile.write(raw)

    def _json(self, body):
        self._bytes(json.dumps(body).encode(), "application/json")


# --- the walk --------------------------------------------------------------

def url(slug):
    return "http://127.0.0.1:%d/%s?cs=%s" % (PORT, slug, CS)


def open_report(browser, slug="kitchen-visualizer"):
    page = browser.new_page(viewport={"width": 390, "height": 844},
                            device_scale_factor=2)
    errors = []
    page.on("pageerror", lambda e: errors.append(str(e)))
    page.on("console",
            lambda m: errors.append(m.text) if m.type == "error" else None)
    page.on("response", lambda r: errors.append("%d %s" % (r.status, r.url))
            if r.status >= 400 else None)
    page.goto(url(slug))
    page.wait_for_selector("#result-body:not([hidden])", timeout=20000)
    page.wait_for_timeout(600)
    return page, errors


def photo_file(tmp, colour=(190, 120, 70), name="kitchen.jpg"):
    path = os.path.join(tmp, name)
    with open(path, "wb") as fh:
        fh.write(jpeg(colour=colour))
    return path


def heic_file(tmp, name="IMG_0001.HEIC"):
    """A real HEIC on disk, so the picker hands the browser one."""
    from pillow_heif import register_heif_opener
    register_heif_opener()
    path = os.path.join(tmp, name)
    out = io.BytesIO()
    Image.new("RGB", (900, 600), (190, 120, 70)).save(out, "HEIF")
    with open(path, "wb") as fh:
        fh.write(out.getvalue())
    return path


def main():
    socketserver.TCPServer.allow_reuse_address = True
    httpd = socketserver.TCPServer(("127.0.0.1", PORT), Handler)
    threading.Thread(target=httpd.serve_forever, daemon=True).start()

    try:
        with sync_playwright() as pw:
            browser = pw.chromium.launch(executable_path=CHROME)

            # --- the section, from nothing -----------------------------
            print("\n--- the section, before a photo ---")
            S.reset()
            page, errors = open_report(browser)

            check("it is in the report", page.is_visible("#visualizer"))
            check("  first, above the palette",
                  page.eval_on_selector(
                      "#report", "n => n.firstElementChild.id") == "visualizer",
                  page.eval_on_selector("#report",
                                        "n => n.firstElementChild.id"))
            check("  titled from the config",
                  page.inner_text("#visualizer .section-title") == VIZ["title"],
                  page.inner_text("#visualizer .section-title"))
            check("  with the picker showing", page.is_visible(".viz-drop"))
            check("  and the guidance line the render depends on",
                  page.inner_text(".viz-drop .viz-guide") == VIZ["guidance"],
                  page.inner_text(".viz-drop .viz-guide"))
            check("nothing offers to transform anything yet",
                  page.query_selector(".viz-go") is None)
            # Naming jpeg and png here greyed out most of an iPhone camera
            # roll: the camera writes HEIC and a burst shot is an MPO, and
            # neither matches either type.
            check("the picker offers everything the phone calls an image",
                  page.get_attribute(".viz-drop .viz-file", "accept")
                  == "image/*",
                  page.get_attribute(".viz-drop .viz-file", "accept"))
            page.screenshot(path=os.path.join(SHOTS, "shot-viz-empty.png"),
                            full_page=True)

            # --- upload ------------------------------------------------
            print("\n--- choosing a photo ---")
            tmp = os.path.join(SHOTS, "vizfiles")
            os.makedirs(tmp, exist_ok=True)
            page.set_input_files(".viz-drop .viz-file", photo_file(tmp))
            page.wait_for_selector(".viz-go", timeout=10000)
            check("the server was sent one", S.uploads == 1, S.uploads)
            check("it comes back as a preview",
                  page.is_visible(".viz-shot .viz-img"))
            check("  with the transform button under it",
                  page.inner_text(".viz-go") == VIZ["generate_cta"],
                  page.inner_text(".viz-go"))
            check("  the guidance line still in view",
                  page.is_visible(".viz-guide"))
            check("  and a way back to a different photo",
                  page.inner_text(".viz-replace").startswith(VIZ["replace_cta"]),
                  page.inner_text(".viz-replace"))
            check("viz_upload was counted once it landed",
                  S.events.count("viz_upload") == 1, S.events)

            # The whole point of the change: the file an iPhone camera
            # actually produces has to get through the picker and the input's
            # accept filter, not just through the server.
            page.set_input_files(".viz-replace .viz-file", heic_file(tmp))
            deadline = time.time() + 10
            while S.uploads < 2 and time.time() < deadline:
                page.wait_for_timeout(100)
            check("a HEIC straight off the camera goes through the picker too",
                  S.uploads == 2, S.uploads)
            # The server records the upload before the answer reaches the
            # browser, so waiting on the count and then reading the DOM in the
            # same breath catches the "Uploading…" frame about half the time.
            page.wait_for_selector(".viz-go", timeout=10000)
            check("  and the section lands back on the transform step",
                  page.is_visible(".viz-go"))
            page.screenshot(path=os.path.join(SHOTS, "shot-viz-ready.png"),
                            full_page=True)

            # --- generating --------------------------------------------
            print("\n--- transforming ---")
            page.click(".viz-go")
            check("the waiting state is up immediately, before any answer",
                  page.is_visible(".viz-working"))
            check("  titled from the config",
                  page.inner_text(".viz-working-title")
                  == VIZ["generating_title"],
                  page.inner_text(".viz-working-title"))
            check("  with a line from the rotation",
                  page.inner_text(".viz-working-text")
                  in VIZ["generating_messages"],
                  page.inner_text(".viz-working-text"))
            check("  and the note that says it is safe to leave",
                  "leave this page" in page.inner_text(".viz-note"),
                  page.inner_text(".viz-note"))
            check("viz_generate was counted", "viz_generate" in S.events,
                  S.events)
            page.screenshot(path=os.path.join(SHOTS, "shot-viz-working.png"),
                            full_page=True)

            # --- ready -------------------------------------------------
            print("\n--- the result ---")
            page.wait_for_selector(".viz-pair", timeout=20000)
            check("before and after are both on screen",
                  page.eval_on_selector_all(".viz-half", "n => n.length") == 2)
            check("  captioned from the config",
                  page.eval_on_selector_all(
                      ".viz-caption", "ns => ns.map(n => n.textContent)")
                  == [VIZ["before_label"], VIZ["after_label"]],
                  page.eval_on_selector_all(
                      ".viz-caption", "ns => ns.map(n => n.textContent)"))
            check("  the after one is the one marked out",
                  page.eval_on_selector_all(
                      ".viz-half",
                      "ns => ns.map(n => n.classList.contains('is-after'))")
                  == [False, True])
            check("  side by side, not stacked",
                  page.eval_on_selector(
                      ".viz-pair",
                      "n => getComputedStyle(n).gridTemplateColumns")
                  .count(" ") == 1,
                  page.eval_on_selector(
                      ".viz-pair",
                      "n => getComputedStyle(n).gridTemplateColumns"))
            check("  and both actually loaded",
                  page.eval_on_selector_all(
                      ".viz-half img",
                      "ns => ns.every(n => n.naturalWidth > 0)"))
            check("there is a download that saves rather than navigates",
                  page.get_attribute(".viz-download", "download") is not None
                  and "download=1" in page.get_attribute(".viz-download",
                                                         "href"),
                  page.get_attribute(".viz-download", "href"))
            check("  labelled from the config",
                  page.inner_text(".viz-download") == VIZ["download_cta"])
            check("the regenerate credit is offered",
                  page.inner_text(".viz-again") == VIZ["regenerate_cta"],
                  page.inner_text(".viz-again"))
            heights = page.eval_on_selector_all(
                ".viz-actions > *", "ns => ns.map(n => n.offsetHeight)")
            check("  and the two actions are the same one-line height",
                  len(set(heights)) == 1 and max(heights) < 48, heights)
            check("viz_ready was counted once", S.events.count("viz_ready") == 1,
                  S.events)
            page.screenshot(path=os.path.join(SHOTS, "shot-viz-result.png"),
                            full_page=True)

            print("\n--- tapping a photo enlarges it ---")
            page.click(".viz-half.is-after")
            page.wait_for_selector("#viz-box", timeout=5000)
            check("a lightbox opens", page.is_visible("#viz-box"))
            check("  with the page behind it locked",
                  page.eval_on_selector("body",
                                        "n => n.classList.contains('is-locked')"))
            check("  carrying that photo's caption",
                  page.inner_text("#viz-box .sample-caption")
                  == VIZ["after_label"],
                  page.inner_text("#viz-box .sample-caption"))
            page.keyboard.press("Escape")
            page.wait_for_timeout(200)
            check("escape closes it",
                  page.eval_on_selector("#viz-box", "n => n.hidden"))
            check("  and gives the page back",
                  not page.eval_on_selector(
                      "body", "n => n.classList.contains('is-locked')"))

            # --- regenerate --------------------------------------------
            print("\n--- the second credit ---")
            page.click(".viz-again")
            page.wait_for_selector(".viz-working", timeout=5000)
            page.wait_for_selector(".viz-pair", timeout=20000)
            check("it runs and lands", S.generates == 2 and S.status == "ready",
                  (S.generates, S.status))
            check("  and there is no third button",
                  page.query_selector(".viz-again") is None)
            check("  the reader is told why",
                  page.inner_text(".viz-spent") == VIZ["spent_note"],
                  page.inner_text(".viz-spent"))
            check("  but can still save what they got",
                  page.is_visible(".viz-download"))
            check("no page errors on the whole run", not errors, errors[:3])
            page.close()

            # --- failure -----------------------------------------------
            print("\n--- a render that fails ---")
            S.reset()
            S.fail_next = True
            page, errors = open_report(browser)
            page.set_input_files(".viz-drop .viz-file", photo_file(tmp))
            page.wait_for_selector(".viz-go", timeout=10000)
            page.click(".viz-go")
            page.wait_for_selector(".viz-error", timeout=20000)
            check("the reader is told, in the funnel's own words",
                  page.inner_text(".viz-error") == VIZ["error_text"],
                  page.inner_text(".viz-error"))
            check("  and the credit was not taken", S.generations == 0,
                  S.generations)
            check("  the button is back",
                  page.inner_text(".viz-go") == VIZ["generate_cta"])
            check("  their photo is still there, so it is one tap to retry",
                  page.is_visible(".viz-shot .viz-img"))
            check("viz_failed was counted", "viz_failed" in S.events, S.events)
            page.screenshot(path=os.path.join(SHOTS, "shot-viz-failed.png"),
                            full_page=True)

            page.click(".viz-go")
            page.wait_for_selector(".viz-pair", timeout=20000)
            check("and the retry goes through", S.status == "ready")
            check("  spending only the one credit", S.generations == 1,
                  S.generations)
            check("no page errors", not errors, errors[:3])
            page.close()

            # --- coming back to a render already running ----------------
            print("\n--- closing the tab mid-render and coming back ---")
            S.reset()
            S.has_source = True
            S.status = "generating"
            S.generations = 1
            S.take_s = 1.2
            S.due = time.time() + S.take_s
            page, errors = open_report(browser)
            check("the page opens straight into the waiting state",
                  page.is_visible(".viz-working"))
            check("  without being asked for a photo again",
                  page.query_selector(".viz-drop") is None)
            page.wait_for_selector(".viz-pair", timeout=25000)
            check("and it finds the render when it lands",
                  page.is_visible(".viz-pair"))
            check("no page errors", not errors, errors[:3])
            page.close()

            # --- a server that does not have the feature yet -------------
            # The window between pushing static/ to the CDN and the code
            # reaching the server. The config offers a section the endpoints
            # behind it do not exist for.
            print("\n--- config ahead of the server ---")
            S.reset()
            S.server_lacks_it = True
            page, errors = open_report(browser)
            page.wait_for_timeout(1200)
            check("the section takes itself out rather than 404 on a tap",
                  page.query_selector("#visualizer") is None)
            check("  and the report still opens on the palette",
                  page.eval_on_selector(
                      "#report",
                      "n => n.firstElementChild.querySelector('.section-title')"
                      ".textContent") == "Your Color Palette")
            check("  with no picker left promising anything",
                  page.query_selector(".viz-drop") is None)
            # The 404 is the point of this case, and it arrives twice — once as
            # the response event and once as the console line the browser
            # writes about it. Neither is a page error.
            expected = [e for e in errors
                        if "visualizer/status" in e
                        or "Failed to load resource" in e]
            check("it is the only failed request on the page",
                  len(expected) == len(errors) and len(expected) == 2,
                  errors[:4])
            page.close()

            # --- the other funnel ---------------------------------------
            print("\n--- /kitchen has none of this ---")
            S.reset()
            page, errors = open_report(browser, "kitchen")
            check("no visualizer section",
                  page.query_selector("#visualizer") is None)
            check("  nothing of it anywhere on the page",
                  page.eval_on_selector_all(
                      "[class*='viz-']", "n => n.length") == 0)
            check("the report still opens on its own first section",
                  page.eval_on_selector(
                      "#report",
                      "n => n.firstElementChild.querySelector('.section-title')"
                      ".textContent") == "Your Color Palette",
                  page.eval_on_selector(
                      "#report",
                      "n => n.firstElementChild.querySelector('.section-title')"
                      ".textContent"))
            check("and it asked for no visualizer status at all",
                  S.uploads == 0 and S.generates == 0)
            check("no page errors", not errors, errors[:3])
            page.close()

            # --- the locked panel, in its three states -----------------
            #
            # Before this, what an unpaid reader saw was their own photograph
            # behind a CSS blur — the room they already have, with an orange
            # wash on it. Thirteen of them read this page for minutes and
            # bought nothing. The panel now holds a real render with half of it
            # blurred into the file, a wait while that render is made, and the
            # old blur when there is no render to show.
            print("\n--- the locked panel: waiting, teaser, fallback ---")

            # The un-bought page, which means walking the quiz: there is no
            # `cs` to jump with, because the whole point is the reader who has
            # not paid.
            STEPS = CFG["kitchen-visualizer"]["swipe"]["steps"]


            def free_page(width=390):
                page = browser.new_page(viewport={"width": width,
                                                  "height": 844},
                                        device_scale_factor=2)
                errs = []
                page.on("pageerror", lambda e: errs.append(str(e)))
                # Every request at Stripe, whether it arrives or not. The
                # element must not even be reached for while the render runs,
                # and "no PaymentIntent" is only half of that — the script
                # itself is a third-party fetch on a page that has not asked
                # anybody for money yet.
                hits = []
                page.on("request", lambda r: "stripe.com" in r.url
                        and hits.append(r.url))
                page.goto("http://127.0.0.1:%d/kitchen-visualizer" % PORT)
                page.wait_for_selector("#cards .card", timeout=10000)
                for i, _step in enumerate(STEPS):
                    page.query_selector_all("#cards .card")[0].click()
                    done = i + 1
                    if done in ANCHORS and done < len(STEPS):
                        page.wait_for_selector("#screen-interstitial.is-active",
                                               timeout=12000)
                        page.click("#mid-cta")
                    if done < len(STEPS):
                        page.wait_for_function(
                            "q => document.getElementById('swipe-caption')"
                            ".textContent === q",
                            arg=STEPS[done]["question"], timeout=15000)
                page.wait_for_selector("#result-body:not([hidden])",
                                       timeout=20000)
                page.wait_for_selector("#commerce:not([hidden])", timeout=15000)
                page.wait_for_timeout(700)
                return page, errs, hits

            PANEL = """() => {
              var shade = document.querySelector('.viz-half.is-locked .viz-shade');
              var pair = document.querySelector('.viz-pair-teaser');
              var left = document.querySelector('.viz-pair-teaser .viz-half');
              var img = shade && shade.querySelector('img');
              var box = shade ? shade.getBoundingClientRect() : null;
              return {
                exists: !!shade,
                cls: shade ? shade.className : null,
                src: img ? img.getAttribute('src') : null,
                blurred: img ? img.className.indexOf('is-blurred') !== -1 : null,
                draggable: img ? img.draggable : null,
                waiting: !!(shade && shade.querySelector('.viz-wait')),
                waitTitle: (shade && shade.querySelector('.viz-wait__title')
                            || {}).textContent,
                w: box ? Math.round(box.width * 100) / 100 : null,
                h: box ? Math.round(box.height * 100) / 100 : null,
                leftH: left && left.querySelector('.viz-shade') ? Math.round(
                  left.querySelector('.viz-shade')
                      .getBoundingClientRect().height * 100) / 100 : null,
                caps: document.querySelectorAll(
                  '.viz-pair-teaser .viz-caption').length,
                capsSeen: Array.prototype.every.call(
                  document.querySelectorAll('.viz-pair-teaser .viz-caption'),
                  function (n) { return n.getBoundingClientRect().height > 0; }),
                deliverRows: document.querySelectorAll('.viz-deliver__row').length,
                deliverOn: (function () {
                  var d = document.querySelector('.viz-deliver');
                  return d ? getComputedStyle(d).visibility === 'visible' : null;
                })(),
                deliverText: Array.prototype.map.call(
                  document.querySelectorAll('.viz-deliver__text'),
                  function (n) { return n.textContent; }),
                deliverBold: Array.prototype.map.call(
                  document.querySelectorAll('.viz-deliver__text .money'),
                  function (n) { return n.textContent; }),
                payTop: (function () {
                  var b = document.querySelector('.viz-go--teaser');
                  return b ? Math.round(
                    (b.getBoundingClientRect().top + window.scrollY) * 100)
                    / 100 : null;
                })(),
                border: (function () {
                  var n = document.querySelector('.viz-half.is-locked');
                  if (!n) return null;
                  var s = getComputedStyle(n);
                  var r = n.getBoundingClientRect();
                  var rep = document.getElementById('report')
                              .getBoundingClientRect();
                  var fr = getComputedStyle(n, '::before');
                  return {frame: fr.borderTopWidth + ' ' + fr.borderTopStyle
                                 + ' ' + fr.borderTopColor,
                          framePos: fr.position,
                          frameZ: fr.zIndex,
                          frameTaps: fr.pointerEvents,
                          outline: s.outlineWidth + ' ' + s.outlineStyle,
                          shadow: s.boxShadow,
                          rightGap: Math.round((rep.right - r.right) * 100) / 100,
                          // All four, against the box that clips.
                          inset: {
                            left: Math.round((r.left - rep.left) * 100) / 100,
                            right: Math.round((rep.right - r.right) * 100) / 100,
                            top: Math.round((r.top - rep.top) * 100) / 100,
                            bottom: Math.round((rep.bottom - r.bottom) * 100) / 100
                          },
                          rect: {x: r.x + window.scrollX, y: r.y + window.scrollY,
                                 w: r.width, h: r.height}};
                })(),
                // --- the offer block below the panels ---
                held: (function () {
                  var h = document.querySelector('.offer-hold');
                  return h ? h.classList.contains('is-held') : null;
                })(),
                waitShown: (function () {
                  var w = document.querySelector('.offer-wait');
                  return w ? getComputedStyle(w).visibility === 'visible' : null;
                })(),
                waitText: (document.querySelector('.offer-wait')
                           || {}).textContent,
                priceShown: (function () {
                  var p = document.getElementById('price');
                  if (!p) return null;
                  return !p.hidden
                         && getComputedStyle(p).visibility === 'visible'
                         && p.getBoundingClientRect().height > 0;
                })(),
                // Anything in the block a thumb could press to pay. The pay
                // button, the wallet grid, the gate — all of them.
                // The wallet grid counts as one: while Stripe is still being
                // asked, what stands there is a shimmer in the shape of a
                // button, and the reader has no way to know it is not one yet.
                controls: Array.prototype.filter.call(
                  document.querySelectorAll('#commerce button, #commerce .xp'),
                  function (n) {
                    return n.offsetParent !== null
                      && getComputedStyle(n).visibility === 'visible';
                  }).map(function (n) { return n.id || n.className; }),
                // The first thing under the held block. If this moves, so did
                // everything below it.
                legalTop: (function () {
                  var n = document.getElementById('legal-links');
                  return n ? Math.round((n.getBoundingClientRect().top
                                         + window.scrollY) * 100) / 100 : null;
                })(),
                holdH: (function () {
                  var h = document.querySelector('.offer-hold');
                  return h ? Math.round(
                    h.getBoundingClientRect().height * 100) / 100 : null;
                })(),
                docH: Math.round(document.documentElement.scrollHeight),
                stripe: typeof window.Stripe,
                // --- the three offer cards ---
                cards: Array.prototype.map.call(
                  document.querySelectorAll('.offer-value__row'),
                  function (n) {
                    var s = getComputedStyle(n);
                    var badge = n.querySelector('.offer-value__badge');
                    var ic = n.querySelector('.offer-value__icon');
                    var r = n.getBoundingClientRect();
                    var body = n.querySelector('.offer-value__body');
                    return {
                      hero: n.classList.contains('is-hero'),
                      border: s.borderTopWidth,
                      bg: s.backgroundColor,
                      badge: badge ? Math.round(
                        badge.getBoundingClientRect().width) : 0,
                      badgeBg: badge
                        ? getComputedStyle(badge).backgroundColor : null,
                      fill: ic ? getComputedStyle(ic).fill : null,
                      stroke: ic ? getComputedStyle(ic).stroke : null,
                      // Text wider than the box it is in, at any width.
                      spill: Math.round(n.scrollWidth - n.clientWidth),
                      bodySpill: body
                        ? Math.round(body.scrollWidth - body.clientWidth) : null,
                      over: Math.round(
                        (r.right - document.getElementById('commerce')
                           .getBoundingClientRect().right) * 100) / 100
                    };
                  }),
                // --- the tinted panel the delivery rows sit in ---
                deliverBox: (function () {
                  var d = document.querySelector('.viz-deliver');
                  if (!d) return null;
                  var s = getComputedStyle(d);
                  var r = d.getBoundingClientRect();
                  var rep = document.getElementById('report')
                              .getBoundingClientRect();
                  return {pad: s.paddingTop, radius: s.borderTopLeftRadius,
                          bg: s.backgroundColor, border: s.borderTopWidth,
                          spill: Math.round(d.scrollWidth - d.clientWidth),
                          over: Math.round((r.right - rep.right) * 100) / 100};
                })(),
                bodyOver: Math.round(document.documentElement.scrollWidth
                                     - window.innerWidth)
              }; }"""

            ACCENT = (192, 86, 33)

            def frame_sides(page, _rect, dpr=2):
                """Which of the four edges of a box actually carry the accent.

                Computed styles say the outline is asked for; they do not say it
                survived an ancestor's overflow. This looks at the pixels — the
                only thing that settles whether a reader sees a border. Sampled
                a few pixels in from each corner so a rounded edge does not
                answer for a straight one.
                """
                # The element's own screenshot rather than a clip computed from
                # a rectangle: Playwright scrolls it into view and crops to its
                # box, which is the same crop at every scroll position. A clip
                # in page coordinates silently disagrees with one in viewport
                # coordinates, and the disagreement looks exactly like a
                # missing border.
                shot = page.locator(".viz-half.is-locked").screenshot()
                im = Image.open(io.BytesIO(shot)).convert("RGB")
                w, h = im.size
                band = max(3, int(round(3 * dpr)))
                inset = int(round(14 * dpr))

                def near(px):
                    return all(abs(px[i] - ACCENT[i]) <= 40 for i in range(3))

                def scan(points):
                    return any(near(im.getpixel(p)) for p in points)

                xs = range(inset, max(inset + 1, w - inset), 4)
                ys = range(inset, max(inset + 1, h - inset), 4)
                return {
                    "top": scan([(x, y) for x in xs for y in range(band)]),
                    "bottom": scan([(x, h - 1 - y) for x in xs
                                    for y in range(band)]),
                    "left": scan([(x, y) for y in ys for x in range(band)]),
                    "right": scan([(w - 1 - x, y) for y in ys
                                   for x in range(band)]),
                }

            boxes = {}
            for width in (320, 360, 390):
                S.reset(); S.has_source = True; S.teaser = "working"
                page, errs, hits = free_page(width)
                page.wait_for_selector(".viz-pair-teaser", timeout=20000)
                page.wait_for_timeout(900)
                waiting = page.evaluate(PANEL)
                check("%d: the panel is a wait, not an empty box" % width,
                      waiting["waiting"] and waiting["cls"].find("is-working")
                      != -1, waiting["cls"])
                check("  it says what is happening",
                      waiting["waitTitle"] == VIZ["preparing_title"],
                      waiting["waitTitle"])
                check("  the reader can still scroll",
                      page.evaluate("() => getComputedStyle(document.body)"
                                    ".overflow !== 'hidden'"))

                # The offer block, while the picture is still being made. No
                # number and nothing to press: what it costs is not a question
                # worth asking about a thing nobody has been shown yet.
                check("  the offer block is held",
                      waiting["held"] is True, waiting["held"])
                check("  no price is on it",
                      waiting["priceShown"] is False, waiting["priceShown"])
                check("  and no pay control either",
                      waiting["controls"] == [], waiting["controls"])
                check("  one muted line stands where they were",
                      waiting["waitShown"] is True
                      and waiting["waitText"] == VCO["wait_note"],
                      (waiting["waitShown"], waiting["waitText"]))
                # The discipline the upload gate already keeps, kept again.
                check("  NO PaymentIntent was created", S.intents == 0,
                      S.intents)
                check("  nothing was asked of Stripe at all", hits == [], hits[:2])
                check("  and window.Stripe is undefined",
                      waiting["stripe"] == "undefined", waiting["stripe"])
                check("  the bar at the foot names no price either",
                      page.evaluate(
                          "() => (document.getElementById('sticky-cta')"
                          "|| {}).textContent")
                      == VCOM["sticky_label_gated"],
                      page.evaluate("() => (document.getElementById("
                                    "'sticky-cta')||{}).textContent"))
                if width == 390:
                    page.screenshot(
                        path=os.path.join(SHOTS, "shot-pre-wait.png"),
                        full_page=True)

                # The render lands. Nothing may move.
                S.teaser = "ready"
                page.wait_for_selector(".viz-shade.is-real img", timeout=12000)
                page.wait_for_function(
                    """() => { const i = document.querySelector(
                         '.viz-shade.is-real img');
                       return i && i.complete && i.naturalWidth > 0; }""",
                    timeout=12000)
                page.wait_for_timeout(300)
                ready = page.evaluate(PANEL)
                boxes[width] = (waiting, ready)
                check("  and the finished picture is the very same box",
                      abs(waiting["w"] - ready["w"]) < 0.5
                      and abs(waiting["h"] - ready["h"]) < 0.5,
                      ((waiting["w"], waiting["h"]), (ready["w"], ready["h"])))
                check("  both pictures are the same box",
                      abs(ready["leftH"] - ready["h"]) < 0.5,
                      (ready["leftH"], ready["h"]))
                check("  and both captions survived the fixed ratio",
                      ready["caps"] == 2 and ready["capsSeen"],
                      (ready["caps"], ready["capsSeen"]))
                check("  it is the teaser file, not the source",
                      "which=teaser" in (ready["src"] or ""), ready["src"])
                check("  with no CSS blur over it", ready["blurred"] is False)
                check("  and no warm wash either",
                      page.eval_on_selector(
                          ".viz-shade.is-real",
                          "n => getComputedStyle(n, '::after').content")
                      == "none")
                check("  not draggable, as a courtesy", ready["draggable"]
                      is False)
                # The rows: hidden while the render runs, shown with it, and
                # the pay button in the same place either way.
                check("  the rows were reserved while it was still working",
                      waiting["deliverRows"] == 2
                      and waiting["deliverOn"] is False,
                      (waiting["deliverRows"], waiting["deliverOn"]))
                check("  and they appear WITH the picture",
                      ready["deliverRows"] == 2 and ready["deliverOn"] is True,
                      (ready["deliverRows"], ready["deliverOn"]))
                check("  saying what unlocking sends",
                      ready["deliverText"] == [r["text"] for r
                                               in VIZ["deliver_rows"]],
                      ready["deliverText"])
                check("  with only the promise half in bold",
                      ready["deliverBold"] == [r["accent"] for r
                                               in VIZ["deliver_rows"]],
                      ready["deliverBold"])
                check("  THE PAY BUTTON DOES NOT MOVE when they appear",
                      waiting["payTop"] is not None
                      and abs(waiting["payTop"] - ready["payTop"]) < 0.5,
                      (waiting["payTop"], ready["payTop"]))

                # The offer block, now that there is a picture to sell.
                check("  the offer block opens with the render",
                      ready["held"] is False and ready["waitShown"] is False,
                      (ready["held"], ready["waitShown"]))
                check("  the price is back",
                      ready["priceShown"] is True, ready["priceShown"])
                check("  and so is a pay control",
                      any(c in ("pay-button", "xp")
                          for c in ready["controls"]), ready["controls"])
                check("  the intent is created only now", S.intents == 1,
                      S.intents)
                # The whole point of the hold. The block gave four rows back
                # and the page under it did not move by a pixel.
                check("  NOTHING BELOW THE BLOCK MOVED",
                      waiting["legalTop"] is not None
                      and abs(waiting["legalTop"] - ready["legalTop"]) < 0.5,
                      (waiting["legalTop"], ready["legalTop"]))
                check("  because the held block is the same height",
                      abs(waiting["holdH"] - ready["holdH"]) < 0.5,
                      (waiting["holdH"], ready["holdH"]))
                check("  and the page is the same length",
                      abs(waiting["docH"] - ready["docH"]) <= 1,
                      (waiting["docH"], ready["docH"]))
                print("      %d: pay button %.1f -> %.1f | legal line %.1f -> "
                      "%.1f | held block %.1f -> %.1f | page %d -> %d"
                      % (width, waiting["payTop"], ready["payTop"],
                         waiting["legalTop"], ready["legalTop"],
                         waiting["holdH"], ready["holdH"],
                         waiting["docH"], ready["docH"]))

                # The three cards, at this width.
                cards = ready["cards"]
                check("  three offer cards, each with a badge",
                      len(cards) == 3
                      and all(c["badge"] >= 20 for c in cards),
                      [c["badge"] for c in cards])
                check("  the hero is filled and bordered heavier",
                      cards[0]["hero"] and cards[0]["border"] == "3px"
                      and cards[0]["bg"] == "rgb(253, 241, 231)"
                      and cards[0]["fill"] == "rgb(192, 86, 33)",
                      (cards[0]["border"], cards[0]["bg"], cards[0]["fill"]))
                check("  its badge is deeper than the card under it",
                      cards[0]["badgeBg"] != cards[0]["bg"],
                      (cards[0]["badgeBg"], cards[0]["bg"]))
                check("  the other two are white, hairlined, stroked not filled",
                      all(c["border"] == "2px"
                          and c["bg"] == "rgb(255, 255, 255)"
                          and c["fill"] == "none"
                          and c["stroke"] == "rgb(192, 86, 33)"
                          for c in cards[1:]),
                      [(c["border"], c["bg"], c["fill"], c["stroke"])
                       for c in cards[1:]])
                check("  no card's text overflows its own box",
                      all(c["spill"] <= 0 and c["bodySpill"] <= 0
                          for c in cards),
                      [(c["spill"], c["bodySpill"]) for c in cards])
                check("  and no card reaches past the block it is in",
                      all(c["over"] <= 0.5 for c in cards),
                      [c["over"] for c in cards])

                # The tinted panel the delivery rows moved into.
                box = ready["deliverBox"]
                check("  the delivery rows sit in a tinted panel",
                      box["bg"] == "rgb(253, 241, 231)" and box["pad"] == "14px"
                      and box["radius"] == "11px" and box["border"] == "1px",
                      (box["bg"], box["pad"], box["radius"], box["border"]))
                check("  which does not overflow",
                      box["spill"] <= 0 and box["over"] <= 0.5,
                      (box["spill"], box["over"]))
                check("  and neither does the page itself",
                      ready["bodyOver"] <= 0, ready["bodyOver"])
                # The accent frame. Inside the box because the panel's right
                # edge is flush with #report's, which clips; over the picture
                # because a positioned child paints above an ancestor's
                # outline, which is how the last version of this went missing
                # on three sides while every computed style said it was there.
                check("  the frame is an overlay inside the box, over the "
                      "picture",
                      ready["border"]["frame"]
                      == "2px solid rgb(192, 86, 33)"
                      and ready["border"]["framePos"] == "absolute"
                      and ready["border"]["frameZ"] == "2"
                      and ready["border"]["outline"] == "0px none"
                      and ready["border"]["shadow"] == "none",
                      ready["border"])
                check("  and a thumb goes straight through it",
                      ready["border"]["frameTaps"] == "none",
                      ready["border"]["frameTaps"])
                check("  so nothing of it falls outside the clipping ancestor",
                      ready["border"]["rightGap"] >= 0,
                      ready["border"]["rightGap"])
                inset = ready["border"]["inset"]
                check("  the panel is inside that ancestor on all four sides",
                      all(v >= 0 for v in inset.values()), inset)
                # And the pixels, which are the only thing that settles it. A
                # computed style says the outline was asked for; it does not
                # say an ancestor's overflow let it through.
                sides = frame_sides(page, ready["border"]["rect"])
                check("  THE ACCENT IS ON ALL FOUR EDGES, in pixels",
                      all(sides.values()), sides)
                check("  and the replace link is off the teaser",
                      page.eval_on_selector_all("#visualizer .viz-replace",
                                                "n => n.length") == 0)
                check("  no page errors", not errs, errs[:2])
                # The two middle states, at the width the report is read at.
                # Taken last, because a full-page shot puts the whole document
                # in front of every IntersectionObserver on it.
                if width == 390:
                    page.screenshot(
                        path=os.path.join(SHOTS, "shot-pre-ready.png"),
                        full_page=True)
                page.close()

            print("\n--- and when the render fails, the old blur is back ---")
            S.reset(); S.has_source = True; S.teaser = "failed"
            page, errs, hits = free_page()
            page.wait_for_selector(".viz-pair-teaser", timeout=20000)
            page.wait_for_timeout(900)
            failed = page.evaluate(PANEL)
            check("the rows stay hidden when the render failed",
                  failed["deliverRows"] == 2 and failed["deliverOn"] is False,
                  (failed["deliverRows"], failed["deliverOn"]))
            check("the panel falls back to the blurred photograph",
                  failed["blurred"] is True
                  and "which=source" in (failed["src"] or ""), failed["src"])
            check("  with the lock back on it",
                  page.eval_on_selector_all(".viz-lock", "n => n.length") == 1)
            check("  and the reader is not stopped from paying",
                  page.eval_on_selector("#commerce", "n => !n.hidden"))
            # A failed render is a finished one as far as the offer goes. The
            # reader still gets the report and the blurred panel is still
            # theirs; holding the block for a picture that is never coming
            # would be refusing money for a product we can still deliver.
            check("  the offer block is open, not held",
                  failed["held"] is False and failed["waitShown"] is False,
                  (failed["held"], failed["waitShown"]))
            check("  the price and a control are on it",
                  failed["priceShown"] is True
                  and any(c in ("pay-button", "xp")
                          for c in failed["controls"]),
                  (failed["priceShown"], failed["controls"]))
            check("  no page errors", not errs, errs[:2])
            page.screenshot(path=os.path.join(SHOTS, "shot-pre-failed.png"),
                            full_page=True)
            page.close()

            print("\n--- and with no photograph at all, the gate ---")
            S.reset()
            page, errs, hits = free_page()
            page.wait_for_selector(".viz-drop", timeout=20000)
            page.wait_for_timeout(900)
            gated = page.evaluate(PANEL)
            check("the offer is gated, not held",
                  gated["held"] is False and gated["waitShown"] is False,
                  (gated["held"], gated["waitShown"]))
            check("  the gate is the only control",
                  gated["controls"] == ["offer-gate__cta"], gated["controls"])
            check("  no price is named", gated["priceShown"] is False,
                  gated["priceShown"])
            check("  and still nothing was asked of Stripe",
                  S.intents == 0 and hits == [], (S.intents, hits[:2]))
            check("  no page errors", not errs, errs[:2])
            page.screenshot(path=os.path.join(SHOTS, "shot-pre-gate.png"),
                            full_page=True)
            page.close()

            print("\n--- the withdrawal waiver, where it is required ---")
            for country, want, why in (("GB", True, "the UK requires it"),
                                       ("CA", False, "Canada does not"),
                                       (None, True, "unknown means show it"),
                                       ("XX", True, "and so does XX")):
                S.reset(); S.has_source = True; S.country = country
                page, errs, hits = free_page()
                page.wait_for_selector(".viz-pair-teaser", timeout=20000)
                page.wait_for_timeout(900)
                shown = page.evaluate(
                    """() => { const n = document.getElementById('withdrawal');
                       if (!n) return null;
                       return !n.hidden && !n.classList.contains('is-off')
                              && getComputedStyle(n).display !== 'none'; }""")
                ticked = page.evaluate(
                    "() => document.getElementById('withdrawal-check').checked")
                check("%-4s -> %-5s  (%s)" % (country or "none", want, why),
                      shown is want, shown)
                check("  and the box never silently gates the button",
                      shown or ticked, (shown, ticked))
                check("  no page errors", not errs, errs[:2])
                page.close()

            browser.close()
    finally:
        httpd.shutdown()

    print("\n%d checks, %d failed" % (checks[0], len(fails)))
    for f in fails:
        print("  FAIL " + f)
    return 1 if fails else 0


if __name__ == "__main__":
    raise SystemExit(main())
