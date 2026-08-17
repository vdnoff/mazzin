#!/usr/bin/env python3
"""What `_post_edit` actually puts on the wire.

There is no OPENAI_API_KEY in this environment, so the one thing that cannot
be checked is whether OpenAI accepts the request. Everything else can be, and
is: the request is sent for real, over HTTP, to a local server that parses it
the way the API would and hands back what the API hands back.

That covers the parts most likely to be wrong and least likely to be noticed
until the first live purchase — the multipart encoding written by hand, the
field names, the auth header, which form fields carry the model and the size,
that the image arrives byte-identical, and that the retry fires on a 429 and a
500 but not on a 400.

    python3 wire.py
"""
import base64
import cgi
import io
import json
import socketserver
import os
import sys
import threading
import time

# The repo root, derived from this file rather than hardcoded: a suite
# that only runs from one absolute path is a suite that stops running the
# first time the checkout moves.
REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

sys.path.insert(0, REPO)

import http.server                                  # noqa: E402
import config                                       # noqa: E402
import visualizer                                   # noqa: E402
from PIL import Image                               # noqa: E402

PORT = 8744

fails = []
checks = [0]


def check(label, ok, detail=""):
    checks[0] += 1
    if not ok:
        fails.append("%s %s" % (label, detail))
    print("  %-62s %s%s" % (label, "ok" if ok else "FAIL",
                            ("  " + str(detail)) if not ok else ""))


def jpeg(size=(640, 480), colour=(190, 120, 70)):
    out = io.BytesIO()
    Image.new("RGB", size, colour).save(out, "JPEG")
    return out.getvalue()


SEEN = []
PLAN = []          # status codes to answer with, one per call


class API(http.server.BaseHTTPRequestHandler):
    """Enough of images/edits to tell us whether we spoke it correctly."""

    protocol_version = "HTTP/1.1"

    def log_message(self, *a):
        pass

    def do_POST(self):
        ctype = self.headers.get("Content-Type", "")
        length = int(self.headers.get("Content-Length") or 0)
        raw = self.rfile.read(length)

        record = {"path": self.path,
                  "auth": self.headers.get("Authorization", ""),
                  "ctype": ctype, "fields": {}, "files": {}}

        # Parsed by the standard library's own multipart reader rather than by
        # anything we wrote, so agreeing with it means agreeing with a parser
        # we did not author.
        env = {"REQUEST_METHOD": "POST", "CONTENT_TYPE": ctype,
               "CONTENT_LENGTH": str(length)}
        form = cgi.FieldStorage(fp=io.BytesIO(raw), environ=env,
                                keep_blank_values=True)
        for key in (form.keys() or []):
            item = form[key]
            if getattr(item, "filename", None):
                record["files"][key] = {"filename": item.filename,
                                        "bytes": item.file.read(),
                                        "type": item.type}
            else:
                record["fields"][key] = item.value
        SEEN.append(record)

        status = PLAN.pop(0) if PLAN else 200
        if status == 200:
            body = json.dumps({"data": [{"b64_json": base64.b64encode(
                jpeg((256, 256), (20, 60, 120))).decode()}]}).encode()
        else:
            body = json.dumps({"error": {"code": "rate_limit_exceeded"}}).encode()
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)


def main():
    socketserver.TCPServer.allow_reuse_address = True
    httpd = socketserver.TCPServer(("127.0.0.1", PORT), API)
    threading.Thread(target=httpd.serve_forever, daemon=True).start()

    config.OPENAI_API_BASE = "http://127.0.0.1:%d/v1" % PORT
    config.OPENAI_API_KEY = "sk-test-notreal"
    config.OPENAI_TIMEOUT_S = 20

    source = jpeg()
    prompt = ("Redecorate this exact kitchen in Modern Rustic style: cabinets "
              "in Oat Linen (#E5DAC8) — with an em dash, a \"quote\" and a "
              "newline\nin it.")

    try:
        print("\n--- one edit, sent for real ---")
        out = visualizer.generate_image(prompt, source)
        check("an image comes back", bool(out) and out[:2] == b"\xff\xd8",
              len(out or b""))
        check("  and it is a real JPEG we can open",
              Image.open(io.BytesIO(out)).format == "JPEG")

        sent = SEEN[-1]
        check("it went to /v1/images/edits", sent["path"] == "/v1/images/edits",
              sent["path"])
        check("with a bearer token", sent["auth"] == "Bearer sk-test-notreal",
              sent["auth"])
        check("as multipart/form-data",
              sent["ctype"].startswith("multipart/form-data"), sent["ctype"])
        check("  with a boundary the parser could find",
              "boundary=" in sent["ctype"])

        print("\n--- the fields ---")
        check("the model is named", sent["fields"].get("model")
              == config.OPENAI_IMAGE_MODEL, sent["fields"].get("model"))
        check("the size is named", sent["fields"].get("size")
              == config.OPENAI_IMAGE_SIZE, sent["fields"].get("size"))
        check("the quality is named", sent["fields"].get("quality")
              == config.OPENAI_IMAGE_QUALITY, sent["fields"].get("quality"))
        check("exactly one image is asked for",
              sent["fields"].get("n") == "1", sent["fields"].get("n"))
        check("the prompt arrives whole, punctuation and all",
              sent["fields"].get("prompt") == prompt,
              repr(sent["fields"].get("prompt"))[:100])
        check("  and the key is not among the form fields",
              "api_key" not in sent["fields"] and "key" not in sent["fields"],
              list(sent["fields"]))

        print("\n--- the photo ---")
        check("it is sent under `image`", "image" in sent["files"],
              list(sent["files"]))
        check("  byte for byte what we stored",
              sent["files"]["image"]["bytes"] == source,
              len(sent["files"]["image"]["bytes"]))
        check("  with a filename and a jpeg type",
              sent["files"]["image"]["filename"] == "source.jpg"
              and sent["files"]["image"]["type"] == "image/jpeg",
              sent["files"]["image"])

        print("\n--- retrying ---")
        before = len(SEEN)
        PLAN[:] = [429]
        started = time.time()
        out = visualizer.generate_image(prompt, source)
        check("a 429 is retried and the retry is used",
              bool(out) and len(SEEN) - before == 2, len(SEEN) - before)
        check("  after a pause rather than immediately",
              time.time() - started >= 1.5, round(time.time() - started, 2))

        before = len(SEEN)
        PLAN[:] = [500]
        out = visualizer.generate_image(prompt, source)
        check("a 500 is retried too", bool(out) and len(SEEN) - before == 2,
              len(SEEN) - before)

        before = len(SEEN)
        PLAN[:] = [400, 400]
        try:
            visualizer.generate_image(prompt, source)
            raised = None
        except visualizer.GenerationError as exc:
            raised = exc
        check("a 400 is not retried — it would be just as wrong twice",
              len(SEEN) - before == 1, len(SEEN) - before)
        check("  and it raises with the status in the code",
              raised is not None and raised.code == "http_400",
              raised and raised.code)
        check("  marked as not worth retrying",
              raised is not None and raised.retriable is False)

        before = len(SEEN)
        PLAN[:] = [429, 429]
        try:
            visualizer.generate_image(prompt, source)
            raised = None
        except visualizer.GenerationError as exc:
            raised = exc
        check("one retry, not a loop", len(SEEN) - before == 2,
              len(SEEN) - before)
        check("  and the second failure is raised",
              raised is not None and raised.code == "http_429",
              raised and raised.code)

        print("\n--- the kill switch ---")
        config.OPENAI_API_KEY = ""
        before = len(SEEN)
        try:
            visualizer.generate_image(prompt, source)
            raised = None
        except visualizer.GenerationError as exc:
            raised = exc
        check("no key means nothing is sent at all", len(SEEN) == before,
              len(SEEN) - before)
        check("  and it says so without pretending it might work later",
              raised is not None and raised.code == "unconfigured"
              and raised.retriable is False, raised and raised.code)
    finally:
        httpd.shutdown()

    print("\n%d checks, %d failed" % (checks[0], len(fails)))
    for f in fails:
        print("  FAIL " + f)
    return 1 if fails else 0


if __name__ == "__main__":
    raise SystemExit(main())
