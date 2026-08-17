#!/usr/bin/env python3
"""The upload failures a real phone produces, and what the server says about them.

Written against a production report with three symptoms and one cause: uploads
from a newer iPhone Pro failed, the server logged nothing at all, and the page
showed the generation-failure sentence. The silence was the interesting part —
Werkzeug enforces MAX_CONTENT_LENGTH while parsing the body, before any route
runs, so the module never saw the request and had nothing to say. Its HTML
error page then broke the client's `response.json()`, which fell through to
whatever copy was the default.

So the things worth asserting are: nothing is ever refused silently, every
refusal is JSON with a code on it, and the log line carries enough to tell a
broken upload from a container we cannot decode.

    python3 hardening.py
"""
import io
import logging
import os
import re
import shutil
import sys
import tempfile

# The repo root, derived from this file rather than hardcoded: a suite
# that only runs from one absolute path is a suite that stops running the
# first time the checkout moves.
REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

sys.path.insert(0, REPO)

import config                # noqa: E402
import database              # noqa: E402
import visualizer            # noqa: E402
from PIL import Image        # noqa: E402
from app import app          # noqa: E402

SESSION = "aaaaaaaa-bbbb-4ccc-8ddd-eeeeeeeeeeee"
UNSEEN = "99999999-8888-4777-8666-555555555555"
SLUG = "kitchen-visualizer"

fails = []
checks = [0]


def check(label, ok, detail=""):
    checks[0] += 1
    if not ok:
        fails.append("%s %s" % (label, detail))
    print("  %-64s %s%s" % (label, "ok" if ok else "FAIL",
                            ("  " + str(detail)) if not ok else ""))


class Capture(logging.Handler):
    """Everything the visualizer logger says, so silence is testable."""

    def __init__(self):
        logging.Handler.__init__(self)
        self.lines = []

    def emit(self, record):
        self.lines.append(record.getMessage())

    def take(self):
        out = self.lines[:]
        self.lines = []
        return out


LOG = Capture()


def photo(size=(900, 600), fmt="JPEG"):
    out = io.BytesIO()
    Image.new("RGB", size, (190, 120, 70)).save(out, fmt)
    return out.getvalue()


class Fake:
    def __init__(self):
        self.rows = {}

    def query_one(self, sql, params=None):
        params = params or ()
        if "FROM events" in sql:
            return {"seen": 1} if params[0] == SESSION else None
        if "FROM purchases" in sql:
            return None
        if "FROM visualizations" in sql:
            return None
        return None

    def execute(self, sql, params=None):
        return 1

    def execute_rowcount(self, sql, params=None):
        return 0


DB = Fake()


def session_q(session=SESSION, slug=SLUG):
    return "session_id=%s&funnel=%s" % (session, slug)


def post(client, query, raw, name="IMG_0001.HEIC", mime="image/heic"):
    return client.post(
        "/api/visualizer/upload?" + query,
        data={"photo": (io.BytesIO(raw), name, mime)},
        content_type="multipart/form-data")


def refusal_line(lines):
    for line in lines:
        if "upload refused" in line:
            return line
    return ""


def main():
    tmp = tempfile.mkdtemp(prefix="harden-")
    config.VISUALIZER_DIR = tmp
    visualizer.database.query_one = DB.query_one
    visualizer.database.execute = DB.execute
    database.query_one, database.execute = DB.query_one, DB.execute

    logger = logging.getLogger("visualizer")
    logger.addHandler(LOG)
    logger.setLevel(logging.INFO)

    with app.test_client() as client:
        print("\n--- the ceiling ---")
        check("the server takes 25MB now, not 8",
              config.VISUALIZER_MAX_BYTES == 25 * 1024 * 1024,
              config.VISUALIZER_MAX_BYTES)
        check("  and the request wall sits just above it",
              app.config["MAX_CONTENT_LENGTH"] > config.VISUALIZER_MAX_BYTES,
              app.config["MAX_CONTENT_LENGTH"])
        check("a 48MP photo is inside the decode ceiling now",
              8064 * 6048 < config.VISUALIZER_MAX_PIXELS,
              (8064 * 6048, config.VISUALIZER_MAX_PIXELS))

        print("\n--- a body past the wall: the silent case ---")
        LOG.take()
        over = b"\x00\x00\x00\x1cftypheic" + b"\x00" * (
            app.config["MAX_CONTENT_LENGTH"] + 4096)
        res = post(client, session_q(), over)
        lines = LOG.take()
        check("it is refused", res.status_code == 413, res.status_code)
        check("  in JSON, not an HTML error page", res.is_json,
              res.get_data()[:60])
        check("  with a code the page can route on",
              res.get_json().get("error") == "too_large", res.get_json())
        check("  carrying the actual limit, so no copy hardcodes a number",
              res.get_json().get("limit_bytes")
              == config.VISUALIZER_MAX_BYTES, res.get_json())
        check("  AND IT SAYS SO IN THE LOG — this is the reported bug",
              bool(refusal_line(lines)), lines)
        check("  naming the length that did it",
              "len=" in refusal_line(lines), refusal_line(lines))

        print("\n--- a body under the wall but over the photo cap ---")
        LOG.take()
        big = photo() + b"\x00" * config.VISUALIZER_MAX_BYTES
        res = post(client, session_q(), big[:config.VISUALIZER_MAX_BYTES + 2048])
        lines = LOG.take()
        check("it is refused with a sentence", res.status_code == 400
              and res.get_json().get("message"), res.get_json())
        check("  coded as a size problem",
              res.get_json().get("error") == "too_large", res.get_json())
        check("  and logged", bool(refusal_line(lines)), lines)

        print("\n--- every rejection leaves a line ---")
        cases = [
            ("junk that is not an image", b"this is not a photograph", 400),
            ("an empty file", b"", 400),
            ("a truncated JPEG", photo()[:180], 400),
            ("a PDF calling itself a photo",
             b"%PDF-1.7\n1 0 obj\n<<>>\nendobj\n", 400),
        ]
        for label, raw, want in cases:
            LOG.take()
            res = post(client, session_q(), raw)
            line = refusal_line(LOG.take())
            check("%s is refused" % label, res.status_code == want,
                  res.status_code)
            check("  and logged", bool(line), line)
            check("  with a reason, a length, a type and a signature",
                  all(bit in line for bit in ("refused (", "len=", "type=",
                                              "sig=")), line)

        print("\n--- what the signature is for ---")
        LOG.take()
        # A container we cannot decode looks exactly like a broken upload until
        # you can see the front of the file.
        post(client, session_q(), b"\x00\x00\x00\x20ftypmif2" + b"\x11" * 400)
        line = refusal_line(LOG.take())
        sig = re.search(r"sig=([0-9a-f]+)", line)
        check("the first bytes are in the line", bool(sig), line)
        check("  eight of them, as hex",
              sig and len(sig.group(1)) == 16, sig and sig.group(1))
        check("  enough to name the container",
              sig and sig.group(1).startswith("00000020"), sig and sig.group(1))
        check("the claimed type is recorded, not trusted",
              "image/heic" in line, line)

        print("\n--- nothing about the photograph itself is logged ---")
        LOG.take()
        post(client, session_q(), b"nonsense-bytes", name="my-kitchen-2026.HEIC")
        line = refusal_line(LOG.take())
        check("the filename never appears", "my-kitchen" not in line, line)
        check("  nor the extension they used", ".HEIC" not in line, line)
        check("  nor any of the content",
              "nonsense" not in line and "6e6f6e73" in line, line)

        print("\n--- a session the server has never seen ---")
        LOG.take()
        res = post(client, session_q(UNSEEN), photo())
        line = refusal_line(LOG.take())
        check("it is refused", res.status_code == 403, res.status_code)
        check("  with a code the page turns into its own sentence",
              res.get_json().get("error") == "unknown_session",
              res.get_json())
        check("  and it is no longer silent either",
              "unknown_session" in line, line)

        print("\n--- and the photo that should work, works ---")
        LOG.take()
        res = post(client, session_q(), photo((4032, 3024)))
        check("a 12MP JPEG goes through", res.status_code == 200,
              res.get_json())
        check("  with nothing logged as refused", not refusal_line(LOG.take()))
        res = post(client, session_q(), photo((8064, 6048)))
        check("a 48MP one does too — the reported device",
              res.status_code == 200, res.get_json())
        stored = Image.open(visualizer.pending_source(SESSION))
        check("  stored at the size we keep",
              max(stored.size) == config.VISUALIZER_MAX_EDGE, stored.size)

        print("\n--- the raw safety net: the client fell back, so this is "
              "the whole camera file ---")
        LOG.take()
        # What an in-app WebView with no working canvas sends: the original,
        # uncompressed by us, straight off a 48MP sensor.
        # Noise, not a flat colour: a 48MP block of one colour compresses to
        # about a megabyte and would not exercise anything. Real sensor output
        # is closer to incompressible.
        import random
        random.seed(7)
        noise = Image.frombytes(
            "RGB", (3600, 2700),
            bytes(random.getrandbits(8) for _ in range(3600 * 2700 * 3)))
        raw_big = io.BytesIO()
        noise.save(raw_big, "JPEG", quality=92, subsampling=0)
        payload = raw_big.getvalue()
        check("the fixture really is a large raw camera file",
              8 * 1024 * 1024 < len(payload) < config.VISUALIZER_MAX_BYTES,
              "%.1f MB" % (len(payload) / 1048576.0))
        res = post(client, session_q(), payload, name="IMG_9999.JPG",
                   mime="image/jpeg")
        check("  the server takes it", res.status_code == 200, res.get_json())
        check("  and nothing was refused", not refusal_line(LOG.take()))
        stored = Image.open(visualizer.pending_source(SESSION))
        check("  downscaled server-side to what we keep",
              max(stored.size) == config.VISUALIZER_MAX_EDGE, stored.size)
        check("  and much smaller on disk than it arrived",
              os.path.getsize(visualizer.pending_source(SESSION))
              < len(payload) / 4,
              os.path.getsize(visualizer.pending_source(SESSION)))

    logger.removeHandler(LOG)
    shutil.rmtree(tmp, ignore_errors=True)
    print("\n%d checks, %d failed" % (checks[0], len(fails)))
    for f in fails:
        print("  FAIL " + f)
    return 1 if fails else 0


if __name__ == "__main__":
    raise SystemExit(main())
