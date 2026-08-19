#!/usr/bin/env python3
"""The visualizer's four routes, driven for real against a fake database.

There is no OPENAI_API_KEY in this environment, so the model call is the one
thing replaced — `visualizer._post_edit` is swapped for a recorder that hands
back real JPEG bytes. Everything on either side of it is the shipping code:
the Flask routes, the token check, the paid guard, the conditional UPDATE that
rations generations, the background thread, and the file writes.

The database is a dict standing in for MySQL, and it implements the claim
statement's semantics by hand — including the part that matters, which is that
two callers racing for the last generation cannot both win.

    python3 viz.py
"""
import io
import json
import os
import shutil
import sys
import tempfile
import threading
import time

# The repo root, derived from this file rather than hardcoded: a suite
# that only runs from one absolute path is a suite that stops running the
# first time the checkout moves.
REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

sys.path.insert(0, REPO)

import config              # noqa: E402
import database            # noqa: E402
import reports             # noqa: E402
import visualizer          # noqa: E402
from PIL import Image, ImageStat   # noqa: E402
from app import app        # noqa: E402

CS = "cs_test_visualizer_token"
CS_OTHER = "cs_test_someone_else"
CS_UNPAID = "cs_test_not_paid_yet"
CS_KITCHEN = "cs_test_plain_kitchen"

fails = []
checks = [0]


def check(label, ok, detail=""):
    checks[0] += 1
    if not ok:
        fails.append("%s %s" % (label, detail))
    print("  %-62s %s%s" % (label, "ok" if ok else "FAIL",
                            ("  " + str(detail)) if not ok else ""))


def photo(size=(900, 600), colour=(190, 120, 70)):
    out = io.BytesIO()
    Image.new("RGB", size, colour).save(out, "JPEG")
    return out.getvalue()


def luma(raw):
    """The mean luma of some encoded image bytes."""
    return ImageStat.Stat(
        Image.open(io.BytesIO(raw)).convert("L")).mean[0]


def kitchen_like(size=(768, 768)):
    """Something with the tonal shape of the renders this is about.

    A flat grey rectangle would be lifted perfectly by any curve. What breaks a
    correction is range: a bright window, mid walls, saturated cabinets and a
    floor that has gone to almost nothing — which is exactly the render that
    came back at 40 with seventy per cent of its pixels near black.
    """
    im = Image.new("RGB", size)
    px = im.load()
    w, h = size
    for y in range(h):
        for x in range(w):
            if y < h * 0.30 and x > w * 0.60:
                px[x, y] = (235, 238, 240)      # window
            elif y < h * 0.55:
                px[x, y] = (150, 146, 138)      # walls
            elif y < h * 0.72:
                px[x, y] = (60, 92, 70)         # green cabinets
            else:
                px[x, y] = (26, 28, 27)         # floor
    return im


def at_mean(target, size=(768, 768), quality=92):
    """`kitchen_like`, exposed to land on a chosen mean luma, as JPEG bytes."""
    base = kitchen_like(size)
    lo, hi = 0.20, 4.0
    for _ in range(30):
        mid = (lo + hi) / 2.0
        shifted = base.point(visualizer._gamma_lut(mid) * 3)
        if ImageStat.Stat(shifted.convert("L")).mean[0] < target:
            hi = mid
        else:
            lo = mid
    out = io.BytesIO()
    base.point(visualizer._gamma_lut((lo + hi) / 2.0) * 3).save(
        out, "JPEG", quality=quality)
    return out.getvalue()


def textured(w, h, seed=7):
    """An image with real high-frequency detail in every part of the frame.

    A flat synthetic cannot test a blur: blurring a solid band leaves a solid
    band, and the sharp half and the soft half measure identical. Detail is
    what a downscale destroys and what a blur destroys, so detail is what the
    teaser assertions have to be made of.
    """
    im = Image.new("RGB", (w, h))
    px = im.load()
    state = seed
    for y in range(h):
        for x in range(w):
            state = (1103515245 * state + 12345) & 0x7FFFFFFF
            n = state % 96
            base = (150, 146, 138) if y < h * 0.55 else (58, 94, 70)
            px[x, y] = (min(255, base[0] + n), min(255, base[1] + n),
                        min(255, base[2] + n))
    return im


def detail(raw, region=None):
    """Mean edge energy — how much high-frequency detail an image carries."""
    from PIL import ImageFilter
    with Image.open(io.BytesIO(raw)) as im:
        grey = im.convert("L")
    if region:
        grey = grey.crop(region)
    return ImageStat.Stat(grey.filter(ImageFilter.FIND_EDGES)).mean[0]


def halves(raw):
    """(top-left detail, bottom-right detail), sampled well clear of the seam.

    The anti-diagonal is `x/W + y/H = 1`, so the two triangles are equal by
    construction whatever the aspect. Sampled at 0.72 and 1.28 rather than at
    the line itself, because the feather is deliberately a few pixels wide and
    measuring inside it would measure the feather.
    """
    with Image.open(io.BytesIO(raw)) as im:
        grey = im.convert("L")
    from PIL import ImageFilter
    edge = grey.filter(ImageFilter.FIND_EDGES)
    w, h = edge.size
    sharp, soft, n_sharp, n_soft = 0.0, 0.0, 0, 0
    for y in range(2, h - 2, 2):
        for x in range(2, w - 2, 2):
            g = x / float(w - 1) + y / float(h - 1)
            if g < 0.72:
                sharp += edge.getpixel((x, y)); n_sharp += 1
            elif g > 1.28:
                soft += edge.getpixel((x, y)); n_soft += 1
    return (sharp / max(1, n_sharp), soft / max(1, n_soft),
            n_sharp, n_soft)


def to_jpeg(im, quality=92):
    out = io.BytesIO()
    im.save(out, "JPEG", quality=quality)
    return out.getvalue()


def _teaser_url(auth):
    """What the status endpoint says the browser may fetch, if anything."""
    with app.test_client() as client:
        body = client.get("/api/visualizer/status?" + auth).get_json() or {}
    return body.get("teaser_url")


def _write_source(session_id, raw):
    visualizer._write_atomic(visualizer.pending_source(session_id), raw)


def near_black(raw, threshold=32):
    """The share of pixels below `threshold` — what "unviewable" means here."""
    hist = Image.open(io.BytesIO(raw)).convert("L").histogram()
    return sum(hist[:threshold]) / float(sum(hist))


# --- a database ------------------------------------------------------------

PURCHASES = {
    CS: {"id": 501, "funnel": "kitchen-visualizer", "status": "paid"},
    CS_OTHER: {"id": 502, "funnel": "kitchen-visualizer", "status": "paid"},
    CS_UNPAID: {"id": 503, "funnel": "kitchen-visualizer", "status": "pending"},
    CS_KITCHEN: {"id": 504, "funnel": "kitchen", "status": "paid"},
}


def report_content(style_name="Modern Rustic", hexes=True):
    """A stored paid report — the shape the prompt is built from."""
    colors = [
        {"name": "Oat Linen", "hex": "#E5DAC8" if hexes else "",
         "role": "60% - walls", "finish": "matt", "where": "the bulk"},
        {"name": "Weathered Oak", "hex": "#8A6A4A", "role": "30% - joinery",
         "finish": "eggshell", "where": "the cabinets"},
        {"name": "Burnt Clay", "hex": "#B4552D", "role": "10% - accent",
         "finish": "satin", "where": "one wall"},
    ]
    return {
        "version": "llm-2", "funnel": "kitchen-visualizer",
        "style_id": "modern_rustic", "style_name": style_name,
        "elements": ["brass-hardware", "stone-worktop", "oak-wood",
                     "open-shelving", "statement-pendants", "slate-floor"],
        "sections": [{"id": "palette", "title": "Your Color Palette",
                      "data": {"intro": "x", "colors": colors,
                               "closing_rule": "y"}}],
    }


class Fake:
    """MySQL, in a dict, with the claim statement's semantics kept honest."""

    def __init__(self):
        self.rows = {}            # purchase_id -> visualization row
        self.reports = {}         # purchase_id -> content dict
        self.lock = threading.Lock()
        self.claims = 0
        self.sessions = set()     # (session_id, funnel) pairs that ran the quiz

    # -- the three database entry points --
    def query_one(self, sql, params=None):
        params = params or ()
        if "FROM purchases" in sql:
            return dict(PURCHASES[params[0]]) if params[0] in PURCHASES else None
        if "FROM visualizations" in sql:
            row = self.rows.get(params[0])
            return dict(row) if row else None
        if "FROM reports" in sql:
            content = self.reports.get(params[0])
            return {"content": json.dumps(content)} if content else None
        if "FROM events" in sql:
            # What proves a session actually ran this funnel. The real one is
            # an events row; here it is a set the test fills in.
            return {"seen": 1} if params in self.sessions else None
        raise AssertionError("unexpected query_one: " + sql[:60])

    def execute(self, sql, params=None):
        params = params or ()
        with self.lock:
            if "INSERT INTO visualizations" in sql:
                row = self.rows.setdefault(
                    params[0], {"status": "uploaded", "generations": 0,
                                "attempts": 0, "result_n": None,
                                "error": None, "started": None})
                row.update(status="uploaded", result_n=None, error=None)
                return 1
            if "status = 'ready'" in sql:
                self.rows[params[1]].update(status="ready", result_n=params[0],
                                            error=None)
                return 1
            if "status = 'failed'" in sql:
                row = self.rows[params[1]]
                row.update(status="failed", error=params[0])
                if "GREATEST" in sql:
                    row["generations"] = max(0, row["generations"] - 1)
                return 1
        raise AssertionError("unexpected execute: " + sql[:60])

    def execute_rowcount(self, sql, params=None):
        """The claim. Its whole job is to be atomic, so it is."""
        assert "SET status = 'generating'" in sql, sql[:60]
        purchase_id, limit, max_attempts, stale = params
        with self.lock:
            row = self.rows.get(purchase_id)
            if not row:
                return 0
            if row["generations"] >= limit or row["attempts"] >= max_attempts:
                return 0
            running = (row["status"] == "generating"
                       and row.get("started")
                       and (time.time() - row["started"]) < stale)
            if running:
                return 0
            row.update(status="generating", generations=row["generations"] + 1,
                       attempts=row["attempts"] + 1, started=time.time(),
                       error=None)
            self.claims += 1
            return 1


DB = Fake()


class Edits:
    """Stands in for the one call that would cost money."""

    def __init__(self):
        self.calls = []
        self.fail_with = None
        self.delay = 0

    def __call__(self, prompt, jpeg, size=None):
        # `size` is new: the render is asked for in the shape of the source
        # photograph rather than always square, so the recorder keeps it and
        # the sizing can be asserted through the real route.
        self.calls.append({"prompt": prompt, "bytes": len(jpeg), "size": size})
        if self.delay:
            time.sleep(self.delay)
        if self.fail_with is not None:
            raise self.fail_with
        # A different colour each time, so a regenerate is visibly a new image.
        return photo((1024, 1024), (40 * len(self.calls) % 255, 90, 120))


EDITS = Edits()


def install(tmp):
    config.VISUALIZER_DIR = tmp
    config.OPENAI_API_KEY = "sk-not-real"
    for module in (visualizer, reports):
        module.database.query_one = DB.query_one
        module.database.execute = DB.execute
    visualizer.database.execute_rowcount = DB.execute_rowcount
    database.query_one, database.execute = DB.query_one, DB.execute
    database.execute_rowcount = DB.execute_rowcount
    visualizer._post_edit = EDITS


def post_upload(client, cs, raw, field="photo", name="kitchen.jpg",
                mime=None):
    part = ((io.BytesIO(raw), name, mime) if mime
            else (io.BytesIO(raw), name))
    return client.post(
        "/api/visualizer/upload?cs=" + cs,
        data={field: part},
        content_type="multipart/form-data")


def png(size=(900, 600)):
    out = io.BytesIO()
    Image.new("RGB", size, (120, 160, 200)).save(out, "PNG")
    return out.getvalue()


def refused_by(module, raw):
    try:
        module.normalise(raw)
    except module.IntakeError as exc:
        return exc.code
    return None


def heic(size=(900, 600)):
    """What an iPhone camera writes."""
    visualizer.register_image_formats()
    out = io.BytesIO()
    Image.new("RGB", size, (190, 120, 70)).save(out, "HEIF")
    return out.getvalue()


def mpo(size=(900, 600)):
    """What a portrait or burst shot arrives as."""
    out = io.BytesIO()
    Image.new("RGB", size, (190, 120, 70)).save(
        out, "MPO", append_images=[Image.new("RGB", size, (20, 40, 90))])
    return out.getvalue()


def wait_for(client, cs, want, limit=10.0):
    """Poll the real status endpoint until it settles."""
    deadline = time.time() + limit
    body = {}
    while time.time() < deadline:
        body = client.get("/api/visualizer/status?cs=" + cs).get_json()
        if body.get("status") in want:
            return body
        time.sleep(0.05)
    return body


def main():
    tmp = tempfile.mkdtemp(prefix="viz-")
    install(tmp)
    DB.reports[501] = report_content()
    DB.reports[502] = report_content()

    with app.test_client() as client:
        print("\n--- who is allowed in ---")
        check("no token is a 400",
              client.get("/api/visualizer/status").status_code == 400)
        check("a token that is not a checkout session is a 400",
              client.get("/api/visualizer/status?cs=../../etc/passwd")
              .status_code == 400)
        check("a token no purchase matches is a 404",
              client.get("/api/visualizer/status?cs=cs_test_nobody")
              .status_code == 404)
        res = client.get("/api/visualizer/status?cs=" + CS_UNPAID)
        check("an unpaid purchase is refused", res.status_code == 403,
              res.status_code)
        check("  and told exactly why", res.get_json().get("error")
              == "not_paid", res.get_json())
        res = client.get("/api/visualizer/status?cs=" + CS_KITCHEN)
        check("a funnel with no visualizer block is a 404",
              res.status_code == 404, res.status_code)
        check("  and the reason names the missing feature, not the funnel",
              res.get_json().get("error") == "no_visualizer", res.get_json())

        print("\n--- before anything has been uploaded ---")
        body = client.get("/api/visualizer/status?cs=" + CS).get_json()
        check("the status is `none`", body["status"] == "none", body)
        check("  with both generations still to spend",
              body["remaining"] == 2 and body["max_generations"] == 2, body)
        check("generating without a photo is refused",
              client.post("/api/visualizer/generate?cs=" + CS).status_code
              == 409)
        check("  and nothing was claimed", DB.claims == 0, DB.claims)
        check("the image route has nothing to serve",
              client.get("/api/visualizer/image?cs=" + CS).status_code == 404)

        print("\n--- uploading ---")
        res = post_upload(client, CS, photo())
        check("a real photo is accepted", res.status_code == 200,
              res.status_code)
        check("  and the status moves to `uploaded`",
              res.get_json()["status"] == "uploaded", res.get_json())
        check("  the file is on disk, outside static/",
              os.path.isfile(visualizer.source_path(501))
              and config.STATIC_DIR not in visualizer.source_path(501))
        check("  and it is a JPEG whatever came in",
              Image.open(visualizer.source_path(501)).format == "JPEG")

        print("\n--- the formats a phone really sends ---")
        # A share sheet routinely lies about all three: an iPhone hands over a
        # HEIC named IMG_0001.JPG marked image/jpeg. The bytes are the only
        # honest answer, so every one of these is uploaded under the wrong name
        # and the wrong type on purpose.
        res = post_upload(client, CS, heic(), name="IMG_0001.JPG",
                          mime="image/jpeg")
        check("a HEIC lying about its name and type is accepted",
              res.status_code == 200, res.get_json())
        check("  and what lands on disk is a JPEG",
              Image.open(visualizer.source_path(501)).format == "JPEG")

        res = post_upload(client, CS, mpo(), name="IMG_0002.JPG",
                          mime="image/jpeg")
        check("an MPO burst shot is accepted", res.status_code == 200,
              res.get_json())
        stored = Image.open(visualizer.source_path(501))
        check("  flattened to one frame",
              getattr(stored, "n_frames", 1) == 1,
              getattr(stored, "n_frames", 1))

        res = post_upload(client, CS, photo(), name="photo.bin",
                          mime="application/octet-stream")
        check("a photo with no usable type at all is still opened",
              res.status_code == 200, res.get_json())

        out = io.BytesIO()
        Image.new("RGB", (700, 500), (10, 180, 90)).save(out, "WEBP")
        res = post_upload(client, CS, out.getvalue(), name="whatever.bin",
                          mime="application/octet-stream")
        check("a WEBP masquerading as .bin is opened on its bytes",
              res.status_code == 200, res.get_json())

        res = post_upload(client, CS, b"this is not a photograph")
        check("junk is refused with a sentence", res.status_code == 400
              and res.get_json().get("message"), res.get_json())
        check("  the one naming the formats a reader recognises",
              res.get_json()["message"]
              == "We couldn't read that photo — JPEG, PNG or HEIC please.",
              res.get_json().get("message"))
        res = post_upload(client, CS, b"%PDF-1.7\n1 0 obj\n<<>>\nendobj\n",
                          name="kitchen.jpg", mime="image/jpeg")
        check("a PDF calling itself a JPEG is refused on its bytes",
              res.status_code == 400, res.status_code)

        # Put a real photo back, so the states below start from one.
        post_upload(client, CS, photo())
        res = client.post("/api/visualizer/upload?cs=" + CS, data={},
                          content_type="multipart/form-data")
        check("no file at all is a 400", res.status_code == 400,
              res.status_code)
        over = b"\xff\xd8" + b"\x00" * (config.VISUALIZER_MAX_BYTES + 1)
        res = post_upload(client, CS, over)
        check("an oversize body is refused by the server's own ceiling",
              res.status_code in (400, 413), res.status_code)

        print("\n--- serving the photo back ---")
        res = client.get("/api/visualizer/image?which=source&cs=" + CS)
        check("the owner can fetch their source", res.status_code == 200,
              res.status_code)
        check("  as an image", res.headers["Content-Type"] == "image/jpeg",
              res.headers.get("Content-Type"))
        check("  that nothing in between may cache",
              "no-store" in res.headers.get("Cache-Control", "")
              and "private" in res.headers.get("Cache-Control", ""),
              res.headers.get("Cache-Control"))
        check("somebody else's token gets their own empty result, not this one",
              client.get("/api/visualizer/image?which=source&cs=" + CS_OTHER)
              .status_code == 404)
        check("an unknown `which` is a 400",
              client.get("/api/visualizer/image?which=../source&cs=" + CS)
              .status_code == 400)

        print("\n--- generating ---")
        # The reader's own photograph, as it sits on disk before any of this.
        # The exposure lift must not go anywhere near it: what they uploaded is
        # the "before" panel and the blurred teaser, and both are that file.
        source_before = open(visualizer.source_path(501), "rb").read()
        res = client.post("/api/visualizer/generate?cs=" + CS)
        check("the call is accepted", res.status_code == 200, res.status_code)
        body = wait_for(client, CS, {"ready", "failed"})
        check("  and it lands ready", body["status"] == "ready", body)
        check("  one credit spent, one left",
              body["generations"] == 1 and body["remaining"] == 1, body)
        check("  the result is on disk as render 1",
              os.path.isfile(visualizer.result_path(501, 1)))
        check("  and the status carries a url for it",
              "which=result" in body.get("url", ""), body.get("url"))
        res = client.get(body["url"])
        check("  which serves the image", res.status_code == 200
              and res.headers["Content-Type"] == "image/jpeg", res.status_code)
        check("  the reader's own photo was not touched on the way past",
              open(visualizer.source_path(501), "rb").read() == source_before,
              len(source_before))
        stored = open(visualizer.result_path(501, 1), "rb").read()
        returned = photo((1024, 1024), (40, 90, 120))
        check("  and what was stored is the corrected render, not the raw one",
              stored != returned and luma(stored) > luma(returned),
              (luma(returned), luma(stored)))

        print("\n--- what the model was actually asked for ---")
        prompt = EDITS.calls[0]["prompt"]
        check("the style is named", "Modern Rustic" in prompt, prompt[:80])
        check("the dominant colour and its hex are both in it",
              "Oat Linen" in prompt and "#E5DAC8" in prompt, prompt[:120])
        check("the secondary colour is too", "Weathered Oak" in prompt)
        check("the metal slot resolved off their own elements",
              "brass hardware" in prompt, prompt)
        check("the worktop slot did too", "stone worktop" in prompt, prompt)
        check("nothing was left as an unfilled placeholder",
              "{" not in prompt and "}" not in prompt, prompt)
        check("the layout instruction survived",
              "KEEP" in prompt and "camera angle" in prompt)
        check("and it was asked for in the source photograph's shape",
              EDITS.calls[0]["size"] == visualizer.edit_size(photo((900, 600))),
              EDITS.calls[0]["size"])

        print("\n--- the second generation is the regenerate credit ---")
        res = client.post("/api/visualizer/generate?cs=" + CS)
        body = wait_for(client, CS, {"ready"})
        check("it runs", res.status_code == 200 and body["status"] == "ready",
              body)
        check("  and is render 2", body["generations"] == 2
              and os.path.isfile(visualizer.result_path(501, 2)), body)
        check("  with nothing left", body["remaining"] == 0, body)
        check("  and a url pointing at the new one",
              "v=2" in body.get("url", ""), body.get("url"))

        res = client.post("/api/visualizer/generate?cs=" + CS)
        check("a third is refused", res.status_code == 409, res.status_code)
        check("  politely, in the funnel's own words",
              "used both" in (res.get_json().get("message") or ""),
              res.get_json())
        check("  and the model was never called a third time",
              len(EDITS.calls) == 2, len(EDITS.calls))

        print("\n--- a failure gives the credit back ---")
        DB.rows[502] = {"status": "uploaded", "generations": 0, "attempts": 0,
                        "result_n": None, "error": None, "started": None}
        post_upload(client, CS_OTHER, photo())
        EDITS.fail_with = visualizer.GenerationError("http_500")
        client.post("/api/visualizer/generate?cs=" + CS_OTHER)
        body = wait_for(client, CS_OTHER, {"failed"})
        check("the render fails", body["status"] == "failed", body)
        check("  nothing was charged for it", body["generations"] == 0, body)
        check("  both transformations are still there",
              body["remaining"] == 2, body)
        check("  and the page is told it may try again",
              body.get("retriable") is True, body)
        check("  with copy from the config",
              "Nothing was used up" in (body.get("message") or ""), body)

        EDITS.fail_with = None
        client.post("/api/visualizer/generate?cs=" + CS_OTHER)
        body = wait_for(client, CS_OTHER, {"ready"})
        check("and the retry succeeds on the same credit",
              body["status"] == "ready" and body["generations"] == 1, body)

        print("\n--- a failure we were billed for keeps the credit ---")
        DB.rows[502] = {"status": "uploaded", "generations": 0, "attempts": 0,
                        "result_n": None, "error": None, "started": None}
        EDITS.fail_with = visualizer.GenerationError("bad_image", billed=True)
        client.post("/api/visualizer/generate?cs=" + CS_OTHER)
        body = wait_for(client, CS_OTHER, {"failed"})
        check("an image we paid for and could not read is still spent",
              body["generations"] == 1, body)
        EDITS.fail_with = None

        print("\n--- the attempt ceiling stops an endless retry ---")
        DB.rows[502] = {"status": "uploaded", "generations": 0,
                        "attempts": config.VISUALIZER_MAX_ATTEMPTS,
                        "result_n": None, "error": None, "started": None}
        res = client.post("/api/visualizer/generate?cs=" + CS_OTHER)
        check("a purchase out of attempts is refused", res.status_code == 409,
              res.status_code)
        check("  and told it is over, not to try again",
              "sort it out" in (res.get_json().get("message") or ""),
              res.get_json())

        print("\n--- two taps at once claim one credit between them ---")
        DB.rows[502] = {"status": "uploaded", "generations": 0, "attempts": 0,
                        "result_n": None, "error": None, "started": None}
        EDITS.delay = 0.3
        before = len(EDITS.calls)
        results = []

        def tap():
            with app.test_client() as c:
                results.append(c.post("/api/visualizer/generate?cs=" + CS_OTHER)
                               .status_code)

        threads = [threading.Thread(target=tap) for _ in range(6)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()
        wait_for(client, CS_OTHER, {"ready", "failed"})
        EDITS.delay = 0
        check("every tap is answered", len(results) == 6, results)
        check("  but only one reached the model",
              len(EDITS.calls) - before == 1, len(EDITS.calls) - before)
        check("  and only one credit was spent",
              DB.rows[502]["generations"] == 1, DB.rows[502])

        print("\n--- a report that is not written yet cannot be drawn ---")
        DB.rows[502] = {"status": "uploaded", "generations": 0, "attempts": 0,
                        "result_n": None, "error": None, "started": None}
        held = DB.reports.pop(502, None)
        res = client.post("/api/visualizer/generate?cs=" + CS_OTHER)
        check("generation is refused with no report at all",
              res.status_code == 409 and res.get_json()["error"]
              == "report_pending", res.get_json())
        DB.reports[502] = report_content(hexes=False)
        res = client.post("/api/visualizer/generate?cs=" + CS_OTHER)
        check("  and with a palette carrying no hex codes",
              res.status_code == 409, res.status_code)
        check("  neither of which spent anything",
              DB.rows[502]["generations"] == 0, DB.rows[502])
        DB.reports[502] = held or report_content()

        print("\n--- re-uploading ---")
        DB.rows[502] = {"status": "generating", "generations": 1,
                        "attempts": 1, "result_n": None, "error": None,
                        "started": time.time()}
        check("a new photo is refused while a render is running",
              post_upload(client, CS_OTHER, photo()).status_code == 409)
        DB.rows[502]["started"] = time.time() - config.VISUALIZER_STALE_S - 1
        check("  but not by a render that stopped running long ago",
              post_upload(client, CS_OTHER, photo()).status_code == 200)
        DB.rows[502] = {"status": "ready", "generations": 1, "attempts": 1,
                        "result_n": 1, "error": None, "started": time.time()}
        res = post_upload(client, CS_OTHER, photo(colour=(20, 40, 90)))
        check("but accepted once it is not", res.status_code == 200,
              res.status_code)
        check("  and the old render is dropped with it, so before and after "
              "always show the same room",
              res.get_json()["status"] == "uploaded"
              and DB.rows[502]["result_n"] is None, res.get_json())
        check("  while the credit already spent stays spent",
              DB.rows[502]["generations"] == 1, DB.rows[502])

        print("\n--- a worker that died does not spin forever ---")
        DB.rows[502] = {"status": "generating", "generations": 1,
                        "attempts": 1, "result_n": None, "error": None,
                        "started": time.time() - config.VISUALIZER_STALE_S - 1}
        body = client.get("/api/visualizer/status?cs=" + CS_OTHER).get_json()
        check("a stale claim reports as failed, not as generating",
              body["status"] == "failed", body)
        check("  and can be claimed again",
              client.post("/api/visualizer/generate?cs=" + CS_OTHER)
              .status_code == 200)
        wait_for(client, CS_OTHER, {"ready", "failed"})

        print("\n--- the download link ---")
        res = client.get("/api/visualizer/image?which=result&download=1&cs="
                         + CS)
        check("asks the browser to save it", "attachment"
              in res.headers.get("Content-Disposition", ""),
              res.headers.get("Content-Disposition"))

    print("\n--- the window between a deploy and a pip install ---")
    # deploy.sh deliberately does not install dependencies, so there is a real
    # window where the code is live and pillow-heif is not. Everything that is
    # not HEIC has to keep working through it, and the boot must not fall over.
    import builtins
    real_import = builtins.__import__

    def no_heif(name, *a, **kw):
        if name.startswith("pillow_heif"):
            raise ImportError("no module named pillow_heif")
        return real_import(name, *a, **kw)

    was = visualizer._formats_registered
    visualizer._formats_registered = False
    builtins.__import__ = no_heif
    try:
        visualizer.register_image_formats()
        check("registering without the package does not raise", True)
        check("  and JPEG still goes through",
              refused_by(visualizer, photo()) is None)
        check("  as does PNG",
              refused_by(visualizer, png()) is None)
        check("  and it does not try again on every upload",
              visualizer._formats_registered is True)
    except Exception as exc:
        check("registering without the package does not raise", False,
              "%s: %s" % (type(exc).__name__, exc))
    finally:
        builtins.__import__ = real_import
        visualizer._formats_registered = was

    print("\n--- and the funnel config is the only gate ---")
    check("kitchen-visualizer offers it",
          visualizer.settings(config.load_funnel("kitchen-visualizer"))
          is not None)
    check("kitchen does not",
          visualizer.settings(config.load_funnel("kitchen")) is None)
    check("a block with enabled:false does not either",
          visualizer.settings({"visualizer": {"enabled": False}}) is None)
    check("and neither does a truthy value that is not True",
          visualizer.settings({"visualizer": {"enabled": 1}}) is None)
    check("funnels/ and static/funnels/ still agree",
          open(os.path.join(REPO, "funnels/kitchen-visualizer.json"), "rb").read()
          == open(os.path.join(REPO, "static/funnels/kitchen-visualizer.json"),
                  "rb").read())

    print("\n--- the render is lifted to the exposure of the photograph ---")
    # Fourteen real renders came back at a mean of 86 against source photos at
    # 121, and the worst at 40-48 with most of their pixels near black. Three
    # prompt wordings on one photo produced 40.8, 62.4 and 47.9 — noise — so
    # the correction is after the render, not in front of it.
    #
    # No API call anywhere in here: `lift_exposure` takes bytes and returns
    # bytes, and the images are built in this file.
    check("the target is the source photos' own mean, near enough",
          115 <= visualizer.EXPOSURE_TARGET <= 121,
          visualizer.EXPOSURE_TARGET)
    check("  and the gamma floor is where the wash-out was measured",
          visualizer.EXPOSURE_GAMMA_FLOOR == 0.42,
          visualizer.EXPOSURE_GAMMA_FLOOR)

    dark = at_mean(45)
    out, note = visualizer.lift_exposure(dark)
    print("    dark   %5.1f -> %5.1f   near-black %.0f%% -> %.0f%%   %s"
          % (luma(dark), luma(out), near_black(dark) * 100,
             near_black(out) * 100, note))
    check("a render at ~45 is lifted a long way",
          luma(out) > luma(dark) + 30, (luma(dark), luma(out)))
    check("  but stops at the floor rather than washing out",
          "gamma 0.420" in note and "floored" in note, note)
    check("  so it lands short of the target, deliberately",
          luma(out) < visualizer.EXPOSURE_TARGET, luma(out))
    check("  and much less of it is near black",
          near_black(out) < near_black(dark) * 0.7,
          (near_black(dark), near_black(out)))
    # It stays higher than the other cases, and that is the floor doing its
    # job rather than a shortfall: a render this dark would need gamma 0.30 to
    # reach the target, and 0.30 was measured taking the greens to grey.

    mid = at_mean(85)
    out, note = visualizer.lift_exposure(mid)
    print("    mid    %5.1f -> %5.1f   %s" % (luma(mid), luma(out), note))
    check("a render at ~85 lands on the target",
          abs(luma(out) - visualizer.EXPOSURE_TARGET) < 2.0, luma(out))
    check("  with a gamma the search chose, not the floor",
          "floored" not in note
          and visualizer.EXPOSURE_GAMMA_FLOOR < float(
              note.split("gamma ")[1]) < 1.0, note)

    # The verified real case: a render measured at 62.4 went to 117.5.
    close = at_mean(62)
    out, note = visualizer.lift_exposure(close)
    print("    62-ish %5.1f -> %5.1f   %s" % (luma(close), luma(out), note))
    check("the 62-mean case reaches the target too",
          luma(out) > 110, luma(out))
    # The shape of the one real render this was verified against: 62.4 -> 117.5
    # with near-black falling from 57% to 5%.
    print("           near-black %.0f%% -> %.1f%%"
          % (near_black(close) * 100, near_black(out) * 100))
    check("  and its near-black all but disappears",
          near_black(close) > 0.35 and near_black(out) < 0.05,
          (near_black(close), near_black(out)))

    bright = at_mean(140)
    out, note = visualizer.lift_exposure(bright)
    print("    bright %5.1f -> %5.1f   %s" % (luma(bright), luma(out), note))
    check("an already-bright render is never darkened",
          luma(out) >= luma(bright), (luma(bright), luma(out)))
    check("  and comes back byte-identical, not re-encoded",
          out == bright and out is bright, len(out) - len(bright))
    check("  the note says so", "already at target" in note, note)

    # Monotone in the right direction, over the whole range, so no input can
    # come out darker than it went in.
    worse = [m for m in (30, 45, 60, 75, 90, 105, 118, 130, 160, 200)
             if luma(visualizer.lift_exposure(at_mean(m))[0])
             < luma(at_mean(m)) - 0.5]
    check("no exposure anywhere in the range comes out darker", not worse,
          worse)

    print("\n--- and a correction that fails costs nobody their render ---")
    real_gamma = visualizer._gamma_lut

    def explode(_g):
        raise RuntimeError("synthetic")

    visualizer._gamma_lut = explode
    try:
        out, note = visualizer.lift_exposure(dark)
        check("the original render is what comes back",
              out is dark, len(out))
        check("  and the note says it was stored uncorrected",
              "failed" in note, note)
    finally:
        visualizer._gamma_lut = real_gamma
    check("undamaged afterwards",
          visualizer.lift_exposure(at_mean(85))[0] != dark)
    check("unreadable bytes are the same story, not a crash",
          visualizer.lift_exposure(b"not an image")[0] == b"not an image")

    print("\n--- the render is shaped like the photograph it came from ---")
    for sw, sh, want in ((1000, 1500, visualizer.EDIT_PORTRAIT),
                         (1500, 1000, visualizer.EDIT_LANDSCAPE),
                         (1000, 1000, visualizer.EDIT_SQUARE),
                         (1000, 1100, visualizer.EDIT_SQUARE),
                         (1000, 1200, visualizer.EDIT_PORTRAIT)):
        got = visualizer.edit_size(to_jpeg(kitchen_like((sw, sh))))
        check("  %4dx%-4d (h/w %.2f) asks for %s"
              % (sw, sh, sh / float(sw), want), got == want, got)

    def ratio_of(raw):
        with Image.open(io.BytesIO(raw)) as im:
            return im.size[1] / float(im.size[0])

    print("  both panels end up the same shape:")
    for sw, sh, rw, rh in ((1000, 1500, 1024, 1536), (1000, 1500, 1024, 1024),
                           (1500, 1000, 1024, 1024)):
        src = to_jpeg(kitchen_like((sw, sh)))
        out, note = visualizer.match_ratio(to_jpeg(kitchen_like((rw, rh))), src)
        check("    source %.2f, render %.2f -> %.2f"
              % (sh / float(sw), rh / float(rw), ratio_of(out)),
              abs(ratio_of(out) - ratio_of(src)) < 0.02, note)

    # The cap. A panoramic source and a square render are three times apart;
    # matching them exactly would cut two thirds of the render away.
    src = to_jpeg(kitchen_like((1000, 3000)))
    out, note = visualizer.match_ratio(to_jpeg(kitchen_like((1024, 1024))), src)
    check("  a 3.00 source does not drag the render past the cap",
          abs(ratio_of(out) - visualizer.RATIO_CAP) < 0.02, (ratio_of(out), note))
    check("  and the log line says the cap is why", "capped" in note, note)
    check("  an unreadable render is returned rather than lost",
          visualizer.match_ratio(b"not an image", src)[0] == b"not an image")

    print("\n--- the teaser is a different file from the render ---")
    render = to_jpeg(textured(1024, 1536), quality=94)
    teaser = visualizer.build_teaser(render)
    with Image.open(io.BytesIO(teaser)) as im:
        tw, th = im.size
    sharp, soft, n_sharp, n_soft = halves(teaser)
    print("    render 1024x1536 %d bytes  ->  teaser %dx%d %d bytes"
          % (len(render), tw, th, len(teaser)))
    print("    detail: sharp half %.1f, blurred half %.1f" % (sharp, soft))
    check("it is not the render", teaser != render)
    check("  nor a re-encode of it at the same size",
          (tw, th) != (1024, 1536), (tw, th))
    check("  its long side is the configured small one",
          max(tw, th) == visualizer.TEASER_LONG_SIDE, max(tw, th))
    check("  so it carries a fraction of the render's pixels",
          tw * th < 1024 * 1536 * 0.2,
          "%.1f%%" % (100.0 * tw * th / (1024 * 1536)))
    check("  and it keeps the render's shape", abs(th / float(tw) - 1.5) < 0.02,
          th / float(tw))

    check("the split is 50/50 by area",
          abs(n_sharp - n_soft) / float(n_sharp) < 0.02, (n_sharp, n_soft))
    check("  the top-left half is sharp and the bottom-right is not",
          sharp > soft * 2.0, (sharp, soft))
    check("  no full-resolution detail survives anywhere in the file",
          detail(teaser) < detail(render) * 0.75,
          (detail(teaser), detail(render)))
    check("  including in the sharp half",
          sharp < detail(render), (sharp, detail(render)))

    print("\n--- the band across its foot, on two lines ---")
    # Measured against the picture the reader is actually shown: the panel is
    # about 37% of the viewport, so a 373-wide teaser is drawn around 138 CSS
    # pixels on a 320px phone. One line long enough to carry the sentence has
    # to shrink to fit and arrives at seven or eight of those; two lines carry
    # it at twelve. That is the whole reason this is two strings.
    from PIL import ImageDraw

    VBLK = visualizer.settings(config.load_funnel("kitchen-visualizer"))
    lines = visualizer._teaser_lines(VBLK)
    check("the config carries two lines",
          len(lines) == 2 and all(lines), lines)
    check("  and the default is two as well, if it does not",
          visualizer._teaser_lines({}) == list(visualizer.TEASER_BAND_DEFAULT),
          visualizer._teaser_lines({}))
    check("  a funnel JSON from before the split still says something",
          visualizer._teaser_lines({"teaser_band": "Unlocks in full"})
          == ["Unlocks in full"])
    check("  and one blank line is dropped rather than drawn",
          visualizer._teaser_lines({"teaser_band_1": "Only this",
                                    "teaser_band_2": "  "}) == ["Only this"])

    def band_fit(block, width=tw):
        """Type size, band height and the widest line, as the drawer sees it."""
        d = ImageDraw.Draw(Image.new("RGB", (10, 10)))
        rows = visualizer._teaser_lines(block)
        size = int(round(width * visualizer.TEASER_LABEL_SIZE))
        floor = int(round(width * visualizer.TEASER_LABEL_MIN))
        room = width * (1.0 - 2 * visualizer.TEASER_BAND_PAD)
        while size > floor:
            f = visualizer._brand_font(size)
            if max(d.textlength(r, font=f) for r in rows) <= room:
                break
            size -= 1
        f = visualizer._brand_font(size)
        return (size, int(round(size * visualizer.TEASER_BAND_RATIO)),
                max(d.textlength(r, font=f) for r in rows), room, floor)

    size, band_h, widest, room, floor = band_fit(VBLK)
    print("    teaser %dx%d: type %dpx, band %dpx (%.1fx), widest line %.0f "
          "of %.0f available" % (tw, th, size, band_h, band_h / float(size),
                                 widest, room))
    for vw, panel in ((320, tw * 0.37), (360, tw * 0.42), (390, tw * 0.464)):
        print("      at %d: panel ~%.0f CSS px -> type %.1f, band %.1f"
              % (vw, panel, size * panel / tw, band_h * panel / tw))
    check("both lines fit inside the picture with room to spare",
          widest <= room, (widest, room))
    check("  at the full size, with no shrinking needed",
          size == int(round(tw * visualizer.TEASER_LABEL_SIZE)), size)
    check("  the band is 2.9x the type", band_h == int(round(size * 2.9)),
          (band_h, size))
    check("  and the type is 8.8% of the picture's width",
          abs(size / float(tw) - 0.088) < 0.002, size / float(tw))
    # The smallest width the reader ever sees it at. Twelve CSS pixels of bold
    # cream on an 80% scrim is small; eight, which is where the one-line copy
    # landed, is a smudge.
    check("  which is still readable on the smallest phone",
          size * 0.37 >= 11.0, size * 0.37)

    # Copy nobody can fit. It must stop at the floor and say so, never run off
    # the edge of the picture in silence.
    long_size, _, long_w, long_room, long_floor = band_fit(
        {"teaser_band_1": "An extraordinarily long first line of copy",
         "teaser_band_2": "and a second one just as unreasonable"})
    check("over-long copy shrinks to the floor and stops",
          long_size == long_floor, (long_size, long_floor))
    check("  and is still too wide there, which is the case being tested",
          long_w > long_room, (long_w, long_room))

    import logging
    said = []

    class Ear(logging.Handler):
        def emit(self, record):
            said.append(record.getMessage())

    ear = Ear()
    visualizer.log.addHandler(ear)
    try:
        wide = visualizer.build_teaser(render, {
            "teaser_band_1": "An extraordinarily long first line of copy",
            "teaser_band_2": "and a second one just as unreasonable"})
    finally:
        visualizer.log.removeHandler(ear)
    check("  it says so in the log rather than clipping quietly",
          any("too long" in line for line in said), said[:2])
    check("  and still returns a picture", len(wide) > 0 and wide != render)

    print("\n--- one render per session, and the re-run survives it ---")
    sess = "aaaaaaaa-bbbb-4ccc-8ddd-eeeeeeeeeeee"
    shutil.rmtree(visualizer.pending_dir(sess), ignore_errors=True)
    check("the first upload claims the render", visualizer.pending_spend(sess))
    check("  a second does not", not visualizer.pending_spend(sess))
    check("  and neither does a third, after a replaced photo",
          not visualizer.pending_spend(sess))
    check("the flag is what turns it on at all",
          visualizer.pre_render_on({"pre_purchase_render": True})
          and not visualizer.pre_render_on({"pre_purchase_render": 1})
          and not visualizer.pre_render_on({})
          and not visualizer.pre_render_on(None))
    check("kitchen-visualizer has it on",
          visualizer.pre_render_on(visualizer.settings(
              config.load_funnel("kitchen-visualizer"))))
    check("  and kitchen has no visualizer at all",
          visualizer.settings(config.load_funnel("kitchen")) is None)
    # The claim is a real file, so it survives a process restart the way the
    # database row would.
    check("the claim is on disk, not in memory",
          os.path.isfile(os.path.join(visualizer.pending_dir(sess),
                                      "render.claimed")))
    check("the credit is what CLAIM_RENDER_SQL writes: one used, one left",
          "generations = 1" in visualizer.CLAIM_RENDER_SQL
          and "'ready', 1, 1" in visualizer.CLAIM_RENDER_SQL,
          visualizer.CLAIM_RENDER_SQL)
    check("  against a limit of two, so the re-run is intact",
          visualizer.max_generations(visualizer.settings(
              config.load_funnel("kitchen-visualizer"))) == 2)
    check("  and attempts is untouched, because nothing was retried",
          "attempts" not in visualizer.CLAIM_RENDER_SQL)

    print("\n--- a failed render costs the reader nothing ---")
    real_gen = visualizer.generate_image
    visualizer.generate_image = lambda *a, **k: (_ for _ in ()).throw(
        visualizer.GenerationError("http_500"))
    try:
        cfgv = config.load_funnel("kitchen-visualizer")
        blockv = visualizer.settings(cfgv)
        _write_source(sess, to_jpeg(kitchen_like((1000, 1400))))
        visualizer.run_pre_render(sess, cfgv, blockv, "modern_rustic", [])
        state = visualizer.read_pending(sess)
        check("it does not raise, and says so in the state file",
              state.get("status") == visualizer.PRE_FAILED, state)
        check("  no teaser file was written",
              not os.path.isfile(visualizer.pending_teaser(sess)))
        check("  and no render either",
              not os.path.isfile(visualizer.pending_result(sess)))
    finally:
        visualizer.generate_image = real_gen

    visualizer.generate_image = lambda *a, **k: to_jpeg(textured(1024, 1536))
    try:
        visualizer.run_pre_render(sess, cfgv, blockv, "modern_rustic",
                                  ["brass-hardware", "stone-worktop"])
        state = visualizer.read_pending(sess)
        check("a working render writes both files and says ready",
              state.get("status") == visualizer.PRE_READY
              and os.path.isfile(visualizer.pending_result(sess))
              and os.path.isfile(visualizer.pending_teaser(sess)), state)
        big = os.path.getsize(visualizer.pending_result(sess))
        small = os.path.getsize(visualizer.pending_teaser(sess))
        print("    render %d bytes on disk, teaser %d bytes served"
              % (big, small))
        check("  and the served file is the small one",
              small < big / 2.0, (small, big))
        check("an unknown style produces no prompt and no call",
              visualizer._pre_purchase_content(cfgv, "not_a_style", []) is None)
        content = visualizer._pre_purchase_content(
            cfgv, "modern_rustic", ["brass-hardware", "nope"])
        check("  and element ids are filtered against the config",
              content["elements"] == ["brass-hardware"], content["elements"])
        check("  the palette comes from the style the reader was shown",
              content["sections"][0]["data"]["colors"][0]["name"]
              == cfgv["styles"][0]["reveals"]["palette"]["colors"][0]["name"],
              content["sections"][0]["data"]["colors"][0])
        check("  with a real hex, so build_prompt does not refuse",
              bool(visualizer.build_prompt(cfgv, blockv, content)))
    finally:
        visualizer.generate_image = real_gen
        shutil.rmtree(visualizer.pending_dir(sess), ignore_errors=True)

    print("\n--- the wire: an upload that really starts a render ---")
    # `run_pre_render` was only ever called directly, with the style handed to
    # it as a Python argument, so the one link that was broken — the browser
    # naming the style on the request — was the only one with no test on it.
    # This goes through the route.
    SESS = "cccccccc-dddd-4eee-8fff-000000000000"
    DB.sessions.add((SESS, "kitchen-visualizer"))
    auth = "session_id=%s&funnel=kitchen-visualizer" % SESS

    def pre_upload(**fields):
        shutil.rmtree(visualizer.pending_dir(SESS), ignore_errors=True)
        data = {"photo": (io.BytesIO(photo((1000, 1400))), "kitchen.jpg")}
        data.update(fields)
        with app.test_client() as client:
            res = client.post("/api/visualizer/upload?" + auth, data=data,
                              content_type="multipart/form-data")
        for _ in range(80):                      # the worker is a thread
            state = visualizer.read_pending(SESS)
            if state.get("status") in (visualizer.PRE_READY,
                                       visualizer.PRE_FAILED):
                break
            time.sleep(0.05)
        return res, visualizer.read_pending(SESS)

    visualizer.generate_image = lambda *a, **k: to_jpeg(textured(1024, 1536))
    calls = []
    real_gen = visualizer.generate_image
    visualizer.generate_image = lambda *a, **k: (
        calls.append(1) or to_jpeg(textured(1024, 1536)))
    try:
        style_id = json.load(open(os.path.join(
            REPO, "funnels/kitchen-visualizer.json")))["styles"][0]["id"]
        res, state = pre_upload(style=style_id,
                                elements="brass-hardware,stone-worktop")
        check("the upload is accepted", res.status_code == 200, res.status_code)
        check("  and a render ran off the back of it",
              state.get("status") == visualizer.PRE_READY, state)
        check("  the image model was actually asked", len(calls) == 1, calls)
        check("  both files are on disk",
              os.path.isfile(visualizer.pending_result(SESS))
              and os.path.isfile(visualizer.pending_teaser(SESS)))
        check("  and the status endpoint offers the teaser, not the render",
              _teaser_url(auth) is not None)

        del calls[:]
        res, state = pre_upload(style="not_a_style")
        check("a style this funnel cannot produce is refused",
              state.get("status") == visualizer.PRE_FAILED
              and state.get("error") == "no_prompt", state)
        check("  and nothing was sent to the image model", not calls, calls)
        check("  the upload itself still succeeded, so the reader carries on",
              res.status_code == 200, res.status_code)

        del calls[:]
        res, state = pre_upload()
        check("no style at all is the same answer",
              state.get("status") == visualizer.PRE_FAILED
              and state.get("error") == "no_prompt", state)
        check("  and again nothing was charged", not calls, calls)
    finally:
        visualizer.generate_image = real_gen
        shutil.rmtree(visualizer.pending_dir(SESS), ignore_errors=True)

    shutil.rmtree(tmp, ignore_errors=True)
    print("\n%d checks, %d failed" % (checks[0], len(fails)))
    for f in fails:
        print("  FAIL " + f)
    return 1 if fails else 0


if __name__ == "__main__":
    raise SystemExit(main())
