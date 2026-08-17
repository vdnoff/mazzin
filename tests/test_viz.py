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
from PIL import Image      # noqa: E402
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

    def __call__(self, prompt, jpeg):
        self.calls.append({"prompt": prompt, "bytes": len(jpeg)})
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

    shutil.rmtree(tmp, ignore_errors=True)
    print("\n%d checks, %d failed" % (checks[0], len(fails)))
    for f in fails:
        print("  FAIL " + f)
    return 1 if fails else 0


if __name__ == "__main__":
    raise SystemExit(main())
