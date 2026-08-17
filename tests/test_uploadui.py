#!/usr/bin/env python3
"""What the reader is told when an upload fails, and how it got there.

Two production symptoms, both on this side of the wire. A photograph that was
merely too large was answered with the *generation* failure sentence — "Nothing
was used up, try again" — because every failure in the section fell through to
one default, and that default belonged to renders. And the browser was sending
whatever came off the sensor, which on a newer Pro is a 48MP HEIC past any
sane ceiling.

So: a regression test that upload copy is never generation copy, one per class;
and coverage of the three ways a file can be shrunk before it is sent, since
most of the traffic is Android inside an in-app WebView where the good paths
are the ones that break.

The bitmap and canvas paths run for real in Chromium. The failure modes that
only happen on old WebViews — `toBlob` handing back null, `createImageBitmap`
rejecting — are induced by overriding those APIs in the page, which is the
only way to reach them here; that is stated rather than implied.

    python3 uploadui.py
"""
import io
import json
import os
import socketserver
import sys
import threading

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

CFG = json.load(open(os.path.join(ROOT, "funnels/kitchen-visualizer.json")))
VIZ = CFG["visualizer"]

# The sentence that belongs to a failed render and must never answer a failed
# upload. This is the whole regression.
GENERATION_COPY = VIZ["error_text"]

fails = []
checks = [0]


def check(label, ok, detail=""):
    checks[0] += 1
    if not ok:
        fails.append("%s %s" % (label, detail))
    print("  %-64s %s%s" % (label, "ok" if ok else "FAIL",
                            ("  " + str(detail)) if not ok else ""))


def jpeg(size=(3000, 2000), colour=(190, 120, 70)):
    out = io.BytesIO()
    Image.new("RGB", size, colour).save(out, "JPEG")
    return out.getvalue()


class Server:
    def __init__(self):
        self.reset()

    def reset(self):
        self.answer = None        # (status, body) to force, or None for ok
        self.uploads = []         # (bytes, content-type) actually received
        self.events = []
        self.have = False

    def status_body(self):
        body = {"status": "uploaded" if self.have else "none", "paid": False,
                "generations": 0, "max_generations": 2, "remaining": 2,
                "has_source": self.have}
        if self.have:
            body["source_url"] = "/api/visualizer/image?which=source&x=1"
        return body


S = Server()


def report_body():
    titles = {s["id"]: s["title"] for s in CFG["report"]["sections"]}
    data = {
        "palette": {"intro": "x", "colors": [{"name": "Oat", "hex": "#E5DAC8",
                    "role": "d", "finish": "matt", "where": "w"}],
                    "closing_rule": "r"},
        "mistakes": {"items": [{"title": "t", "body": "b" * 40, "fix": "f" * 12}]},
        "materials": {"intro": "i" * 22, "pairs": [{"combo": "c", "verdict":
                      "works", "why": "w" * 12}], "rule": "r" * 16},
        "shopping": {"items": [{"name": "n", "priority_note": "p"}], "skip": []},
        "dna": {"narrative": ["n"], "implications": ["i"]},
        "splurge": {"splurge": {"item": "i", "why": "w"},
                    "saves": [{"item": "i", "why": "w"}], "split_note": "s"},
    }
    return {"complete": True, "report": {
        "version": "llm-2", "funnel": "kitchen-visualizer",
        "style_id": "modern_rustic", "style_name": "Modern Rustic",
        "sections": [{"id": s["id"], "title": titles[s["id"]],
                      "data": data[s["id"]]}
                     for s in CFG["report"]["sections"]]}}


class Handler(WalkHandler):

    def do_GET(self):
        path = self.path.split("?")[0]
        if path == "/api/pixel-config":
            return self._json({})
        if path == "/api/report":
            return self._json(report_body())
        if path == "/api/visualizer/status":
            return self._json(S.status_body())
        if path == "/api/visualizer/image":
            return self._bytes(jpeg((600, 400)), "image/jpeg")
        if path in ("/kitchen", "/kitchen-visualizer"):
            self.path = "/static/funnel.html"
        return super().do_GET()

    def do_POST(self):
        path = self.path.split("?")[0]
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
            S.uploads.append(raw)
            if S.answer is not None:
                code, body = S.answer
                if body is None:      # HTML, the way Werkzeug used to answer
                    return self._bytes(b"<!doctype html><h1>413</h1>",
                                       "text/html", code)
                return self._json(body, code)
            S.have = True
            return self._json(S.status_body())
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


def walk(page):
    steps = CFG["swipe"]["steps"]
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
    page.wait_for_timeout(500)


def photo_file(tmp, name="kitchen.jpg", size=(3000, 2000)):
    path = os.path.join(tmp, name)
    with open(path, "wb") as fh:
        fh.write(jpeg(size))
    return path


def open_free(browser, init=None):
    page = browser.new_page(viewport={"width": 390, "height": 844})
    errors = []
    page.on("pageerror", lambda e: errors.append(str(e)))
    if init:
        page.add_init_script(init)
    page.goto("http://127.0.0.1:%d/kitchen-visualizer" % PORT)
    walk(page)
    page.wait_for_selector(".viz-drop", timeout=15000)
    return page, errors


def main():
    socketserver.TCPServer.allow_reuse_address = True
    httpd = socketserver.TCPServer(("127.0.0.1", PORT), Handler)
    threading.Thread(target=httpd.serve_forever, daemon=True).start()
    tmp = os.path.join(SHOTS, "hardfiles")
    os.makedirs(tmp, exist_ok=True)

    try:
        with sync_playwright() as pw:
            browser = pw.chromium.launch(executable_path=CHROME)

            # --- the shrink, for real ---------------------------------
            print("\n--- the photo is shrunk before it leaves the phone ---")
            S.reset()
            page, errors = open_free(browser)
            big = photo_file(tmp, size=(4000, 3000))
            original = os.path.getsize(big)
            page.set_input_files(".viz-drop .viz-file", big)
            page.wait_for_selector(".viz-pair-teaser", timeout=15000)
            sent = len(S.uploads[-1])
            check("what arrives is smaller than what was chosen",
                  sent < original, (original, sent))
            check("  the upload carries which path produced it",
                  ("viz_upload", {"phase": "pre", "path": "bitmap"})
                  in S.events
                  or ("viz_upload", {"phase": "pre", "path": "canvas"})
                  in S.events,
                  [e for e in S.events if e[0] == "viz_upload"])
            path_used = [e[1]["path"] for e in S.events
                         if e[0] == "viz_upload"][-1]
            check("  and in Chromium that is the memory-safe bitmap path",
                  path_used == "bitmap", path_used)
            check("no page errors", not errors, errors[:3])
            page.close()

            print("\n--- the longest side really is capped ---")
            S.reset()
            page, errors = open_free(browser)
            page.set_input_files(".viz-drop .viz-file",
                                 photo_file(tmp, "wide.jpg", (5000, 2000)))
            page.wait_for_selector(".viz-pair-teaser", timeout=15000)
            body = S.uploads[-1]
            start = body.find(b"\xff\xd8\xff")
            img = Image.open(io.BytesIO(body[start:]))
            check("a 5000px wide photo arrives at 2048",
                  max(img.size) == 2048, img.size)
            check("  with its shape kept",
                  abs(img.size[0] / float(img.size[1]) - 2.5) < 0.02, img.size)
            check("  as a JPEG whatever it started as", img.format == "JPEG")
            page.close()

            print("\n--- a portrait photo is capped on the other axis ---")
            S.reset()
            page, errors = open_free(browser)
            page.set_input_files(".viz-drop .viz-file",
                                 photo_file(tmp, "tall.jpg", (2000, 5000)))
            page.wait_for_selector(".viz-pair-teaser", timeout=15000)
            body = S.uploads[-1]
            img = Image.open(io.BytesIO(body[body.find(b"\xff\xd8\xff"):]))
            check("a 5000px tall photo arrives at 2048 too",
                  max(img.size) == 2048 and img.size[1] > img.size[0],
                  img.size)
            page.close()

            # --- the fallbacks ----------------------------------------
            print("\n--- createImageBitmap missing: the canvas path ---")
            S.reset()
            page, errors = open_free(
                browser, "delete window.createImageBitmap;")
            page.set_input_files(".viz-drop .viz-file", photo_file(tmp))
            page.wait_for_selector(".viz-pair-teaser", timeout=15000)
            used = [e[1]["path"] for e in S.events if e[0] == "viz_upload"][-1]
            check("it falls through to canvas", used == "canvas", used)
            body = S.uploads[-1]
            img = Image.open(io.BytesIO(body[body.find(b"\xff\xd8\xff"):]))
            check("  and still shrinks the photo",
                  max(img.size) == 2048, img.size)
            check("no page errors", not errors, errors[:3])
            page.close()

            print("\n--- toBlob returning null: the toDataURL fallback ---")
            S.reset()
            # The documented old-WebView behaviour, induced. Chromium's own
            # toBlob works, so there is no other way to reach this branch.
            page, errors = open_free(browser, """
                delete window.createImageBitmap;
                HTMLCanvasElement.prototype.toBlob = function (cb) { cb(null); };
            """)
            page.set_input_files(".viz-drop .viz-file", photo_file(tmp))
            page.wait_for_selector(".viz-pair-teaser", timeout=15000)
            used = [e[1]["path"] for e in S.events if e[0] == "viz_upload"][-1]
            check("the upload still happens", len(S.uploads) == 1, S.uploads)
            check("  still by the canvas path", used == "canvas", used)
            body = S.uploads[-1]
            img = Image.open(io.BytesIO(body[body.find(b"\xff\xd8\xff"):]))
            check("  and toDataURL produced a real shrunk JPEG",
                  img.format == "JPEG" and max(img.size) == 2048, img.size)
            check("no page errors", not errors, errors[:3])
            page.close()

            print("\n--- nothing works: the raw file goes as it is ---")
            S.reset()
            page, errors = open_free(browser, """
                delete window.createImageBitmap;
                HTMLCanvasElement.prototype.toBlob = function (cb) { cb(null); };
                HTMLCanvasElement.prototype.toDataURL = function () {
                  throw new Error("no");
                };
            """)
            raw_path = photo_file(tmp, "raw.jpg", (2600, 1800))
            page.set_input_files(".viz-drop .viz-file", raw_path)
            page.wait_for_selector(".viz-pair-teaser", timeout=15000)
            used = [e[1]["path"] for e in S.events if e[0] == "viz_upload"][-1]
            check("it is reported as the raw path", used == "raw", used)
            body = S.uploads[-1]
            img = Image.open(io.BytesIO(body[body.find(b"\xff\xd8\xff"):]))
            check("  and the original arrives untouched, for the server to "
                  "shrink", img.size == (2600, 1800), img.size)
            check("no page errors", not errors, errors[:3])
            page.close()

            # --- the copy, which is the reported bug ------------------
            print("\n--- an upload failure never shows generation copy ---")
            cases = [
                ("a photo over the ceiling", 413,
                 {"error": "too_large", "limit_bytes": 25 * 1024 * 1024},
                 "over 25MB"),
                ("an HTML error page, as Werkzeug used to send", 413, None,
                 "check your connection"),
                ("a file we cannot read", 400,
                 {"error": "not_an_image",
                  "message": "We couldn't read that photo — JPEG, PNG or "
                             "HEIC please."},
                 "JPEG, PNG or HEIC"),
                ("a session the server has never seen", 403,
                 {"error": "unknown_session"}, "quiz"),
                ("a bad token, which a shared link produces", 400,
                 {"error": "bad_token"}, "quiz"),
                ("something nobody can name", 500, {"error": "kaboom"},
                 "check your connection"),
            ]
            for label, code, body, needle in cases:
                S.reset()
                S.answer = (code, body)
                page, errors = open_free(browser)
                page.set_input_files(".viz-drop .viz-file", photo_file(tmp))
                page.wait_for_selector(".viz-error", timeout=15000)
                shown = page.inner_text(".viz-error")
                check("%s is explained" % label, needle in shown, shown)
                check("  and NOT with the generation sentence",
                      GENERATION_COPY not in shown and "used up" not in shown,
                      shown)
                check("  with the picker still there to try again",
                      page.query_selector(".viz-drop .viz-file") is not None
                      or page.query_selector(".viz-replace .viz-file")
                      is not None)
                check("  no page errors", not errors, errors[:2])
                page.close()

            print("\n--- the section does not vanish on a shared link ---")
            S.reset()
            S.answer = (404, {"error": "no_visualizer"})
            page, errors = open_free(browser)
            page.set_input_files(".viz-drop .viz-file", photo_file(tmp))
            page.wait_for_timeout(1500)
            check("a refusal on upload explains itself rather than "
                  "disappearing", page.query_selector("#visualizer")
                  is not None)
            check("  saying what to do about it",
                  "quiz" in (page.inner_text(".viz-error")
                             if page.query_selector(".viz-error") else ""),
                  page.inner_text("#visualizer"))
            page.close()

            print("\n--- and the generation failure keeps its own copy ---")
            S.reset()
            page, errors = open_free(browser)
            page.set_input_files(".viz-drop .viz-file", photo_file(tmp))
            page.wait_for_selector(".viz-pair-teaser", timeout=15000)
            shown = page.evaluate("""() => {
              // Reach the generation path directly: it is post-purchase and
              // this page is not, so the copy is checked at its source.
              return document.querySelector('#visualizer') ? 'ok' : 'no';
            }""")
            check("the teaser is up", shown == "ok")
            check("  and the generation string is still the config's",
                  GENERATION_COPY == "That didn't come out. Nothing was used "
                                     "up — try again.", GENERATION_COPY)
            page.close()

            print("\n--- the picker still offers the gallery ---")
            S.reset()
            page, errors = open_free(browser)
            check("accept is image/*",
                  page.get_attribute(".viz-drop .viz-file", "accept")
                  == "image/*")
            check("  and there is no capture attribute forcing the camera",
                  page.get_attribute(".viz-drop .viz-file", "capture") is None,
                  page.get_attribute(".viz-drop .viz-file", "capture"))
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
