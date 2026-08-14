"""Photo in, restyled kitchen out. Post-purchase, one funnel, two renders.

Owns four routes and everything behind them: taking a photograph off a phone,
turning it into something safe to keep, building the edit instruction out of
the report that was already written for this buyer, calling the image model,
and serving the two pictures back to the one person entitled to see them.

Three things shape most of the decisions here.

**It costs money per use.** Every other endpoint in this app is free to serve.
This one bills an external account each time it succeeds, so the credit count
lives in the database behind a conditional UPDATE rather than in a file or in
the client, generation is refused on anything but a paid purchase, and a
failure that produced no image gives the credit back rather than eating it.

**The input is a photograph of somebody's home.** It is stripped of every EXIF
tag on the way in — a phone photo carries GPS coordinates, a device serial and
a timestamp, and none of that is ours to keep. It is stored outside static/,
served only through a route that checks the purchase token, and never named in
a log line.

**The model is slow and the browser is a phone.** Generation runs on a
background thread and the page polls a status endpoint, exactly as the report
pipeline does, so a locked screen or a closed tab costs nothing.
"""

import base64
import binascii
import io
import json
import logging
import os
import re
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
import uuid

from flask import Blueprint, jsonify, request, send_file

import config
import database
import reports
from payments import CHECKOUT_SESSION_RE

log = logging.getLogger(__name__)

bp = Blueprint("visualizer", __name__)

# The state machine, as the status endpoint reports it. `none` is not stored —
# it is the absence of a row.
NONE, UPLOADED, GENERATING, READY, FAILED = (
    "none", "uploaded", "generating", "ready", "failed")

# What a browser is allowed to hand us. Checked against what PIL actually
# decodes, not against the Content-Type header, which is whatever the client
# felt like saying.
ALLOWED_FORMATS = frozenset(("JPEG", "PNG"))

PLACEHOLDER_RE = re.compile(r"\{(\w+)\}")

SELECT_PURCHASE_SQL = (
    "SELECT id, funnel, status FROM purchases "
    "WHERE checkout_session = %s LIMIT 1"
)

SELECT_STATE_SQL = (
    "SELECT status, generations, attempts, result_n, error, "
    "       UNIX_TIMESTAMP(started_at) AS started FROM visualizations "
    "WHERE purchase_id = %s LIMIT 1"
)

# The upload. A second photograph for the same purchase replaces the first
# rather than stacking, and resets the row to `uploaded` — but only from a
# state where nothing is in flight, which is the WHERE clause's job.
UPSERT_STATE_SQL = (
    "INSERT INTO visualizations (purchase_id, status) VALUES (%s, 'uploaded') "
    "ON DUPLICATE KEY UPDATE status = 'uploaded', result_n = NULL, error = NULL"
)

# The claim. Everything that decides whether this purchase may spend a credit
# is in the WHERE clause, so two taps arriving together resolve to one winner
# in the database rather than in two workers that both read "1 generation used"
# a microsecond apart. `started_at` older than the stale window releases a
# claim whose worker died without ever finishing.
CLAIM_SQL = (
    "UPDATE visualizations SET status = 'generating', "
    "  generations = generations + 1, attempts = attempts + 1, "
    "  started_at = NOW(), error = NULL "
    "WHERE purchase_id = %s AND generations < %s AND attempts < %s "
    "  AND (status <> 'generating' "
    "       OR started_at < NOW() - INTERVAL %s SECOND)"
)

FINISH_OK_SQL = (
    "UPDATE visualizations SET status = 'ready', result_n = %s, error = NULL "
    "WHERE purchase_id = %s"
)

# The refund. A credit is spent when an image comes back, and an attempt that
# never got one did not cost anything, so it is given back — `attempts` is what
# still rose, and it is what stops this looping forever.
FINISH_FAIL_SQL = (
    "UPDATE visualizations SET status = 'failed', "
    "  generations = GREATEST(generations - 1, 0), error = %s "
    "WHERE purchase_id = %s"
)

# A failure with the image already in hand. We were billed, so the credit is
# not returned — but the buyer still has nothing, which is why this is logged
# loudly enough to be found and fixed by hand.
FINISH_LOST_SQL = (
    "UPDATE visualizations SET status = 'failed', error = %s "
    "WHERE purchase_id = %s"
)


# --- config ----------------------------------------------------------------


def settings(cfg):
    """The funnel's visualizer block, or None when it does not offer one.

    A funnel says nothing and gets nothing. That is the whole gate: /kitchen
    has no block, so every route below refuses it before looking at anything
    else, and no code path anywhere names a slug.
    """
    block = (cfg or {}).get("visualizer")
    if not isinstance(block, dict) or block.get("enabled") is not True:
        return None
    return block


def max_generations(block):
    value = (block or {}).get("max_generations")
    if isinstance(value, bool) or not isinstance(value, int):
        return 0
    return max(0, min(value, 10))


# --- where the files live --------------------------------------------------


def _dir(purchase_id):
    """The directory for one purchase. Built from an integer, always.

    `purchase_id` reaches here from a database column by way of int(), never
    from a request, so there is nothing in it to traverse with — but it is
    coerced anyway, because the day someone passes this a string from a query
    parameter should be the day it raises rather than the day it writes
    somewhere else.
    """
    return os.path.join(config.VISUALIZER_DIR, str(int(purchase_id)))


def source_path(purchase_id):
    return os.path.join(_dir(purchase_id), "source.jpg")


def result_path(purchase_id, n):
    return os.path.join(_dir(purchase_id), "result_%d.jpg" % int(n))


def _write_atomic(path, data):
    """Write a file that is never half there.

    The status route decides "ready" from a database row and the image route
    then opens the file. Between those two a partially written JPEG would be
    served as a broken image, so the bytes land under a scratch name and are
    renamed into place, which on a POSIX filesystem is atomic.
    """
    os.makedirs(os.path.dirname(path), exist_ok=True)
    tmp = "%s.%s.part" % (path, uuid.uuid4().hex)
    try:
        with open(tmp, "wb") as fh:
            fh.write(data)
            fh.flush()
            os.fsync(fh.fileno())
        os.replace(tmp, path)
    except Exception:
        try:
            os.unlink(tmp)
        except OSError:
            pass
        raise


# --- taking a photograph in ------------------------------------------------


class IntakeError(Exception):
    """A photo we will not accept, carrying the reason the reader is told."""

    def __init__(self, code, message):
        Exception.__init__(self, code)
        self.code = code
        self.message = message


def normalise(raw):
    """Bytes off a phone -> a plain JPEG with nothing else in it.

    Four things happen here and each one is load-bearing:

    * It is decoded, so what is stored is an image rather than whatever the
      Content-Type claimed. A file that PIL will not open never reaches disk.
    * Orientation is applied and then discarded. A phone photograph is stored
      unrotated with an EXIF tag saying which way is up — dropping the tag
      without acting on it first is how you get a sideways kitchen.
    * Everything else in the metadata goes with it. GPS coordinates, the
      device serial, the timestamp: re-encoding from the pixel buffer means
      the output carries no tags at all rather than the ones we remembered to
      remove.
    * It is downscaled. The model reads about a megapixel; keeping a 12MP
      original of the inside of someone's house serves nobody.

    Raises IntakeError with copy the caller can show. Never raises anything
    else on a bad file — a malformed image is an ordinary event on this route,
    not an exception worth a stack trace.
    """
    if not raw:
        raise IntakeError("empty", "That file was empty.")
    if len(raw) > config.VISUALIZER_MAX_BYTES:
        raise IntakeError(
            "too_large", "That photo is over %dMB. Try one straight from your "
            "camera roll rather than an export."
            % (config.VISUALIZER_MAX_BYTES // (1024 * 1024)))

    try:
        from PIL import Image, ImageOps
    except ImportError:
        # Pillow arrives with weasyprint, so this means a half-installed
        # environment rather than a bad upload. Same shape of answer, very
        # different log line.
        log.error("Pillow is not installed — visualizer uploads are refused")
        raise IntakeError("unavailable", "Uploads are briefly unavailable.")

    try:
        # `open` reads the header and stops. The pixels are not decoded until
        # `load()`, which is what makes the size check below worth anything:
        # it happens before we have allocated for them.
        img = Image.open(io.BytesIO(raw))
        fmt = img.format
    except Exception:
        raise IntakeError(
            "not_an_image", "That doesn't look like a photo. JPEG or PNG, "
                            "please.")

    if fmt not in ALLOWED_FORMATS:
        raise IntakeError(
            "wrong_format", "That's a %s. JPEG or PNG, please." % (fmt or "file"))

    # Checked here rather than by moving Pillow's own `MAX_IMAGE_PIXELS`, which
    # is a module global: two uploads at once would race on it and leave it
    # wherever the loser put it back, for weasyprint and everything else to
    # inherit. Reading the header's own dimensions asks the same question of
    # this one file and of nothing else. Pillow's default guard still sits
    # underneath as a second wall.
    width, height = img.size
    if width * height > config.VISUALIZER_MAX_PIXELS:
        raise IntakeError(
            "too_large",
            "That photo is enormous. One straight from your camera roll will "
            "work better.")

    try:
        img.load()
        # Reads the orientation tag, rotates the pixels, returns an image with
        # no orientation tag left to disagree with them.
        img = ImageOps.exif_transpose(img) or img
        img = img.convert("RGB")

        longest = max(img.size)
        if longest > config.VISUALIZER_MAX_EDGE:
            scale = float(config.VISUALIZER_MAX_EDGE) / longest
            img = img.resize(
                (max(1, int(round(img.size[0] * scale))),
                 max(1, int(round(img.size[1] * scale)))),
                Image.LANCZOS)

        out = io.BytesIO()
        # No `exif=` and no `icc_profile=`: what is not passed is not written,
        # which is the point of re-encoding rather than editing.
        img.save(out, "JPEG", quality=config.VISUALIZER_JPEG_QUALITY,
                 optimize=True)
    except Exception:
        log.exception("visualizer: re-encode failed")
        raise IntakeError("unreadable", "We couldn't read that photo.")

    return out.getvalue()


# --- the instruction the model is given ------------------------------------


def _elements_by_id(cfg):
    items = ((cfg or {}).get("style_elements") or {}).get("items") or []
    return {item.get("id"): item for item in items if isinstance(item, dict)}


def _slot_words(cfg, block, content):
    """What answers {metal}, {worktop} and friends.

    Read out of the elements the free result already showed this person, which
    are stored on the report precisely because the run they came from is gone
    by the time anything here executes. A slot names a tag; the first shown
    element carrying it wins, in the order the strip showed them, so the words
    in the prompt are the words that were on their screen.
    """
    slots = (block or {}).get("prompt_slots") or {}
    by_id = _elements_by_id(cfg)
    shown = [by_id[eid] for eid in ((content or {}).get("elements") or [])
             if eid in by_id]

    words = {}
    for key, rule in slots.items():
        if not isinstance(rule, dict):
            continue
        tag = rule.get("tag")
        picked = None
        for item in shown:
            if tag and tag in (item.get("tags") or []):
                picked = item
                break
        label = (picked or {}).get("label")
        # The label lowercased, not the spec: the spec is a purchasing
        # instruction ("Aged brass — unlacquered, satin finish") and an em dash
        # mid-prompt reads as two separate demands.
        words[key] = (label[0].lower() + label[1:]) if label \
            else (rule.get("fallback") or key)
    return words


def _palette_words(content):
    """The three colours, by the role each one plays.

    Only ever read off a stored paid report, where the hex codes are real. The
    free payload has them stripped out — which is the whole boundary the result
    page sells — so a caller that reached here with one would be describing a
    kitchen in colours it does not have. `dominant_hex` missing is what tells
    `build_prompt` to refuse.
    """
    for section in ((content or {}).get("sections") or []):
        if not isinstance(section, dict) or section.get("id") != "palette":
            continue
        colors = [c for c in ((section.get("data") or {}).get("colors") or [])
                  if isinstance(c, dict)]
        names = ["dominant", "secondary", "accent"]
        words = {}
        for index, key in enumerate(names):
            colour = colors[index] if index < len(colors) else {}
            words[key] = colour.get("name") or ""
            words[key + "_hex"] = colour.get("hex") or ""
        return words
    return {}


def build_prompt(cfg, block, content):
    """The edit instruction for one buyer, or None when it cannot be built.

    None rather than a generic fallback on purpose. A prompt with an empty
    {dominant} in it produces a competent kitchen in nobody's colours, and a
    competent kitchen in nobody's colours is worse than an honest "not ready
    yet" — the palette is the thing being sold, and it lands on the report a
    few seconds after the purchase does.
    """
    template = (block or {}).get("prompt_template")
    if not isinstance(template, str) or not template.strip():
        return None

    words = {"style": (content or {}).get("style_name") or ""}
    words.update(_palette_words(content))
    words.update(_slot_words(cfg, block, content))

    if not words.get("dominant") or not words.get("dominant_hex"):
        return None
    if not words["style"]:
        return None

    # A placeholder nothing answers is dropped rather than left in braces. On
    # the result page a stray {splashback} is a visible typo; in a prompt it is
    # an instruction to draw the word.
    return PLACEHOLDER_RE.sub(
        lambda m: str(words.get(m.group(1), "")), template).strip()


# --- the image model -------------------------------------------------------


class GenerationError(Exception):
    """A generation that did not produce an image.

    `retriable` is what the page shows: something that will plainly never work
    for this purchase should stop asking, and everything else should offer the
    button again. `billed` says whether an image was actually produced before
    things went wrong, which is what decides if the credit comes back.
    """

    def __init__(self, code, retriable=True, billed=False):
        Exception.__init__(self, code)
        self.code = code
        self.retriable = retriable
        self.billed = billed


def _multipart(fields, files):
    """A multipart/form-data body, built by hand.

    urllib has no multipart encoder and this is the one endpoint in the app
    that needs one. Written out rather than pulling in a dependency for four
    headers, and kept in one place so the boundary can never appear twice.
    """
    boundary = "----mazzin" + uuid.uuid4().hex
    line = ("\r\n").encode()
    body = io.BytesIO()

    for name, value in fields:
        body.write(b"--" + boundary.encode() + line)
        body.write(('Content-Disposition: form-data; name="%s"' % name)
                   .encode() + line + line)
        body.write(str(value).encode("utf-8") + line)

    for name, filename, content_type, data in files:
        body.write(b"--" + boundary.encode() + line)
        body.write(('Content-Disposition: form-data; name="%s"; filename="%s"'
                    % (name, filename)).encode() + line)
        body.write(("Content-Type: %s" % content_type).encode() + line + line)
        body.write(data + line)

    body.write(b"--" + boundary.encode() + b"--" + line)
    return "multipart/form-data; boundary=" + boundary, body.getvalue()


def _post_edit(prompt, jpeg):
    """One call to the images/edits endpoint. Returns JPEG bytes.

    Raw urllib rather than a client library: this is a single multipart POST
    against a documented URL, and a dependency that has to be installed by hand
    on the server before the feature works is a worse trade than thirty lines.
    """
    content_type, body = _multipart(
        fields=[("model", config.OPENAI_IMAGE_MODEL),
                ("prompt", prompt),
                ("size", config.OPENAI_IMAGE_SIZE),
                ("quality", config.OPENAI_IMAGE_QUALITY),
                ("n", 1)],
        files=[("image", "source.jpg", "image/jpeg", jpeg)])

    req = urllib.request.Request(
        config.OPENAI_API_BASE.rstrip("/") + "/images/edits",
        data=body, method="POST",
        headers={"Authorization": "Bearer " + config.OPENAI_API_KEY,
                 "Content-Type": content_type})

    try:
        with urllib.request.urlopen(
                req, timeout=config.OPENAI_TIMEOUT_S) as res:
            payload = json.loads(res.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        # 429 and 5xx are worth another go; a 400 means the request itself is
        # wrong and will be exactly as wrong the second time.
        status = exc.code
        body_hint = ""
        try:
            detail = json.loads(exc.read().decode("utf-8"))
            body_hint = str((detail.get("error") or {}).get("code") or "")[:60]
        except Exception:
            pass
        # The prompt is built from this buyer's report, so it is never logged.
        # The status and the API's own error code are not about them.
        log.warning("visualizer: image edit HTTP %s %s", status, body_hint)
        raise GenerationError("http_%d" % status,
                              retriable=(status == 429 or status >= 500))
    except Exception as exc:
        log.warning("visualizer: image edit failed: %s", type(exc).__name__)
        raise GenerationError("transport")

    data = (payload or {}).get("data") or []
    encoded = (data[0] or {}).get("b64_json") if data else None
    if not encoded:
        log.warning("visualizer: image edit returned no image")
        raise GenerationError("empty_response")

    try:
        return base64.b64decode(encoded, validate=True)
    except (binascii.Error, ValueError):
        # An image was generated and billed for; we simply cannot read it.
        log.error("visualizer: image edit returned undecodable base64")
        raise GenerationError("bad_image", billed=True)


def generate_image(prompt, jpeg):
    """The edit, with one retry on the failures that are worth retrying."""
    if not config.OPENAI_API_KEY:
        log.error("OPENAI_API_KEY is not configured — generation unavailable")
        raise GenerationError("unconfigured", retriable=False)

    try:
        return _post_edit(prompt, jpeg)
    except GenerationError as first:
        if not first.retriable or first.billed:
            raise
        log.info("visualizer: retrying after %s", first.code)
        time.sleep(2)
        return _post_edit(prompt, jpeg)


# --- state -----------------------------------------------------------------


def read_state(purchase_id):
    """The row for a purchase as a plain dict, or None."""
    try:
        return database.query_one(SELECT_STATE_SQL, (purchase_id,))
    except Exception:
        log.exception("visualizer: state read failed for purchase %s",
                      purchase_id)
        return None


def claim(purchase_id, limit):
    """Take a generation slot, or return False because there was none.

    One statement. The alternative — read the count, decide, then write — is
    two round trips with a window between them, and the thing in that window
    is a second image nobody paid for.
    """
    try:
        changed = database.execute_rowcount(
            CLAIM_SQL, (purchase_id, limit, config.VISUALIZER_MAX_ATTEMPTS,
                        int(config.VISUALIZER_STALE_S)))
    except Exception:
        log.exception("visualizer: claim failed for purchase %s", purchase_id)
        return False
    return bool(changed)


def _release(purchase_id, code, billed):
    sql = FINISH_LOST_SQL if billed else FINISH_FAIL_SQL
    try:
        database.execute(sql, (code[:32], purchase_id))
    except Exception:
        log.exception("visualizer: release failed for purchase %s", purchase_id)


def run_generation(purchase_id, cfg, block, content):
    """The worker body. Runs on its own thread; never raises into the caller.

    The slot is already claimed by the time this starts — claiming is the
    route's job, because a request that is going to be refused should be
    refused while the reader is still looking at the response.
    """
    try:
        prompt = build_prompt(cfg, block, content)
        if not prompt:
            log.warning("visualizer: no prompt for purchase %s — report is "
                        "not far enough along", purchase_id)
            _release(purchase_id, "no_prompt", billed=False)
            return

        try:
            with open(source_path(purchase_id), "rb") as fh:
                jpeg = fh.read()
        except OSError:
            log.warning("visualizer: source photo missing for purchase %s",
                        purchase_id)
            _release(purchase_id, "no_source", billed=False)
            return

        try:
            image = generate_image(prompt, jpeg)
        except GenerationError as exc:
            _release(purchase_id, exc.code, billed=exc.billed)
            return

        state = read_state(purchase_id) or {}
        n = int(state.get("generations") or 1)
        try:
            _write_atomic(result_path(purchase_id, n), image)
        except Exception:
            # Billed, and the buyer has nothing. Loud on purpose.
            log.exception("visualizer: could not store the result for "
                          "purchase %s", purchase_id)
            _release(purchase_id, "store_failed", billed=True)
            return

        try:
            database.execute(FINISH_OK_SQL, (n, purchase_id))
        except Exception:
            log.exception("visualizer: could not mark purchase %s ready",
                          purchase_id)
            _release(purchase_id, "store_failed", billed=True)
            return

        log.info("visualizer: purchase %s render %d ready", purchase_id, n)
    except Exception:
        # A thread that dies silently leaves the row in `generating` until the
        # stale window expires, which is a five minute wait on a page that says
        # nothing. Catch everything and say so.
        log.exception("visualizer: generation crashed for purchase %s",
                      purchase_id)
        _release(purchase_id, "crashed", billed=False)


# --- auth ------------------------------------------------------------------


class Denied(Exception):
    """Refused before any work was done, with the status to answer."""

    def __init__(self, status, code):
        Exception.__init__(self, code)
        self.status = status
        self.code = code


def _authorise():
    """Resolve the result-link token into (token, purchase, cfg, block).

    The token is the `cs` the reader was redirected back with and the same one
    their emailed link carries — the credential that already unlocks the paid
    report. Here it also authorises spending money, so every condition is
    checked on every call rather than trusted from a previous one: the funnel
    still offers the feature, and the purchase is still paid.
    """
    cs = request.args.get("cs")
    if not cs and request.method == "POST":
        cs = request.form.get("cs")
    if not isinstance(cs, str) or not CHECKOUT_SESSION_RE.match(cs):
        raise Denied(400, "bad_token")

    try:
        purchase = database.query_one(SELECT_PURCHASE_SQL, (cs,))
    except Exception:
        log.exception("visualizer: purchase lookup failed")
        raise Denied(500, "lookup_failed")
    if not purchase:
        raise Denied(404, "no_purchase")

    # The COGS guard, and the one that matters most. A pending purchase is one
    # Stripe has not confirmed; a refunded one is not owed anything further.
    if purchase.get("status") != "paid":
        raise Denied(403, "not_paid")

    try:
        cfg = config.load_funnel(purchase.get("funnel"))
    except (KeyError, ValueError, OSError):
        raise Denied(404, "no_funnel")

    block = settings(cfg)
    if block is None:
        raise Denied(404, "no_visualizer")

    return cs, purchase, cfg, block


def _denied(exc):
    return jsonify({"error": exc.code}), exc.status


# --- routes ----------------------------------------------------------------


@bp.post("/api/visualizer/upload")
def upload():
    try:
        cs, purchase, cfg, block = _authorise()
    except Denied as exc:
        return _denied(exc)

    state = read_state(purchase["id"]) or {}
    if state.get("status") == GENERATING and not _stale(state):
        # Replacing the photograph under a render that is already running would
        # produce a before/after of two different rooms. Only while it really
        # is running, though: the same staleness rule the status endpoint uses,
        # so a worker that died does not lock the picker for five minutes on a
        # page that has already given up on it.
        return jsonify({"error": "generating",
                        "message": "Hold on — a transformation is running."}), 409

    upload_file = request.files.get("photo")
    if upload_file is None:
        return jsonify({"error": "no_file", "message": "No photo was sent."}), 400

    # One byte past the ceiling, so what is measured is what arrived rather
    # than what the headers claimed, and "exactly at the limit" is
    # distinguishable from "at the limit and still going". The app's own
    # MAX_CONTENT_LENGTH is the outer wall that stops a worker reading a
    # gigabyte at all; this is the inner one that can answer in a sentence.
    raw = upload_file.read(config.VISUALIZER_MAX_BYTES + 1)

    try:
        jpeg = normalise(raw)
    except IntakeError as exc:
        # No filename, no dimensions, no size: the reason is a fixed string
        # from a closed set and nothing about the file goes to the log.
        log.info("visualizer: upload refused (%s)", exc.code)
        return jsonify({"error": exc.code, "message": exc.message}), 400

    try:
        _write_atomic(source_path(purchase["id"]), jpeg)
    except Exception:
        log.exception("visualizer: could not store the source photo")
        return jsonify({"error": "store_failed",
                        "message": "We couldn't save that. Try again."}), 500

    try:
        database.execute(UPSERT_STATE_SQL, (purchase["id"],))
    except Exception:
        log.exception("visualizer: could not record the upload")
        return jsonify({"error": "store_failed",
                        "message": "We couldn't save that. Try again."}), 500

    return jsonify(_status_body(cs, purchase, block)), 200


@bp.post("/api/visualizer/generate")
def generate():
    try:
        cs, purchase, cfg, block = _authorise()
    except Denied as exc:
        return _denied(exc)

    state = read_state(purchase["id"])
    if not state:
        return jsonify({"error": "no_source",
                        "message": "Upload a photo first."}), 409
    if state.get("status") == GENERATING and not _stale(state):
        # Already running. Not an error — the page just polls.
        return jsonify(_status_body(cs, purchase, block)), 200

    limit = max_generations(block)
    if int(state.get("generations") or 0) >= limit:
        return jsonify({"error": "spent",
                        "message": block.get("spent_note")
                        or "You've used all your transformations."}), 409
    if int(state.get("attempts") or 0) >= config.VISUALIZER_MAX_ATTEMPTS:
        return jsonify({"error": "exhausted",
                        "message": block.get("error_final")
                        or "We couldn't complete a transformation."}), 409

    # The report has to be far enough along to describe a palette. It is by the
    # time this section is on screen — the reader cannot reach the button
    # before the report opens — but a direct call can arrive at any moment.
    content = reports.report_content(purchase["id"])
    if not build_prompt(cfg, block, content):
        return jsonify({"error": "report_pending",
                        "message": "Your report is still being written — give "
                                   "it a few seconds."}), 409

    if not claim(purchase["id"], limit):
        # Lost the race, or ran into a ceiling between the read above and here.
        return jsonify(_status_body(cs, purchase, block)), 200

    threading.Thread(
        target=run_generation,
        args=(purchase["id"], cfg, block, content),
        daemon=True,
    ).start()

    return jsonify(_status_body(cs, purchase, block)), 200


def _stale(state):
    started = state.get("started")
    if not started:
        return True
    return (time.time() - float(started)) > config.VISUALIZER_STALE_S


def _status_body(cs, purchase, block):
    """What the page polls for. Re-read every time; never cached."""
    state = read_state(purchase["id"])
    limit = max_generations(block)
    if not state:
        return {"status": NONE, "generations": 0, "max_generations": limit,
                "remaining": limit, "has_source": False}

    status = state.get("status") or UPLOADED
    if status == GENERATING and _stale(state):
        # The worker is gone. Say so rather than spinning forever.
        status = FAILED

    used = int(state.get("generations") or 0)
    attempts = int(state.get("attempts") or 0)
    body = {
        "status": status,
        "generations": used,
        "max_generations": limit,
        "remaining": max(0, limit - used),
        "has_source": os.path.isfile(source_path(purchase["id"])),
    }
    if status == READY and state.get("result_n"):
        # `v` is which render this is, so a regenerate changes the URL and the
        # browser fetches the new picture instead of showing the cached one.
        body["url"] = "/api/visualizer/image?which=result&cs=%s&v=%d" % (
            urllib.parse.quote(cs, safe=""), int(state["result_n"]))
        body["source_url"] = "/api/visualizer/image?which=source&cs=%s" % (
            urllib.parse.quote(cs, safe=""))
    if status == FAILED:
        # Whether the button comes back. A purchase that has run out of
        # attempts is told so once instead of being offered a retry that the
        # server will refuse.
        body["retriable"] = attempts < config.VISUALIZER_MAX_ATTEMPTS
        body["message"] = (block.get("error_text") if body["retriable"]
                           else block.get("error_final"))
    return body


@bp.get("/api/visualizer/status")
def status():
    try:
        cs, purchase, cfg, block = _authorise()
    except Denied as exc:
        return _denied(exc)
    resp = jsonify(_status_body(cs, purchase, block))
    resp.headers["Cache-Control"] = "no-store"
    return resp, 200


@bp.get("/api/visualizer/image")
def image():
    """The only way either picture is readable.

    These files are not in static/ and never will be: static/ is served by the
    web server straight off disk with no idea who is asking, and behind a CDN
    that would cache the inside of somebody's house at an edge node. Here the
    token is checked first and the response is marked private and
    uncacheable — the browser may keep it, nothing in between may.
    """
    try:
        _cs, purchase, cfg, block = _authorise()
    except Denied as exc:
        return _denied(exc)

    which = request.args.get("which") or "result"
    if which == "source":
        path = source_path(purchase["id"])
    elif which == "result":
        state = read_state(purchase["id"]) or {}
        if state.get("status") != READY or not state.get("result_n"):
            return jsonify({"error": "not_ready"}), 404
        path = result_path(purchase["id"], state["result_n"])
    else:
        return jsonify({"error": "bad_which"}), 400

    if not os.path.isfile(path):
        return jsonify({"error": "not_found"}), 404

    resp = send_file(path, mimetype="image/jpeg", conditional=False)
    resp.headers["Cache-Control"] = "private, no-store"
    if request.args.get("download"):
        resp.headers["Content-Disposition"] = (
            'attachment; filename="my-kitchen-transformed.jpg"')
    return resp
