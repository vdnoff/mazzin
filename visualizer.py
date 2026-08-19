"""Photo in, restyled kitchen out. One funnel, two renders.

Owns four routes and everything behind them: taking a photograph off a phone,
turning it into something safe to keep, building the edit instruction out of
the report that was already written for this buyer, calling the image model,
and serving the two pictures back to the one person entitled to see them.

**The upload happens before the money and the generation happens after it.**
That split is the shape of the whole module. Somebody can put a photo of their
kitchen up while they are still deciding, and see it sitting next to a locked
panel where the transformation will be — but the thing that bills an account
is reachable only with a token Stripe's webhook produced. So a photograph has
two possible owners: a quiz session, which owns a file and nothing else, and a
purchase, which owns everything. `Subject` is where the two meet, and
`_resolve(allow_pending=...)` is the one line that separates them.

Three things shape most of the remaining decisions.

**It costs money per use.** Every other endpoint in this app is free to serve.
This one bills an external account each time it succeeds, so the credit count
lives in the database behind a conditional UPDATE rather than in a file or in
the client, generation is refused on anything but a paid purchase, and a
failure that produced no image gives the credit back rather than eating it.

**The input is a photograph of somebody's home.** It is stripped of every EXIF
tag on the way in — a phone photo carries GPS coordinates, a device serial and
a timestamp, and none of that is ours to keep. It is stored outside static/,
served only through a route that checks a credential, and never named in a log
line. Most uploads are from people who never buy, so most of them are deleted
unread within two days rather than kept against a purchase that never came.

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
import shutil
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
from payments import RESULT_TOKEN_RE, find_purchase

log = logging.getLogger(__name__)

bp = Blueprint("visualizer", __name__)

# The state machine, as the status endpoint reports it. `none` is not stored —
# it is the absence of a row.
NONE, UPLOADED, GENERATING, READY, FAILED = (
    "none", "uploaded", "generating", "ready", "failed")

# What we will not take, which is a far shorter list than what we will.
#
# The rule is "anything Pillow can decode", because the alternative — an
# allowlist of formats — is what broke this in production: it said JPEG and
# PNG, and an iPhone camera sends HEIC while portrait and burst shots arrive
# as MPO. A phone will keep inventing containers and none of them are worth a
# deploy.
#
# EPS is the exception, and it is a security carve-out rather than a taste
# one. Pillow does not decode PostScript itself: it writes the upload to a
# temporary file and runs Ghostscript on it. Ghostscript parsing a stranger's
# file is a much larger thing to be responsible for than an image decoder, and
# no camera on earth produces EPS, so the trade is all cost and no benefit.
REFUSED_FORMATS = frozenset(("EPS",))

# One sentence for every way a file can fail to be a photograph, because from
# the reader's side they are the same event and naming three formats is more
# use to them than naming the seventeen we would actually take.
UNREADABLE = "We couldn't read that photo — JPEG, PNG or HEIC please."

# Set once `register_image_formats` has run, so it can be called from anywhere
# as many times as anyone likes.
_formats_registered = False
_formats_lock = threading.Lock()

PLACEHOLDER_RE = re.compile(r"\{(\w+)\}")

# The quiz session, which is what a photograph is filed under before there is
# a purchase to file it under. Same shape tracking.py and payments.py validate.
UUID_RE = re.compile(
    r"^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$",
    re.IGNORECASE,
)

# A session may upload once it has actually run the funnel. Pre-purchase upload
# is by nature an endpoint nobody has authenticated against — that is the whole
# point of it — so this is what stops it being a free eight megabytes of disk
# to anyone who can spell a UUID. Every real reader has fired `funnel_start`
# and `result_view` long before the section is on their screen.
SELECT_SESSION_SEEN_SQL = (
    "SELECT 1 AS seen FROM events "
    "WHERE session_id = %s AND funnel = %s LIMIT 1"
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

# The pre-purchase render arriving with the photograph. One generation used
# out of the funnel's limit, which on kitchen-visualizer leaves exactly the one
# re-run the offer promises. `attempts` is not touched: nothing was retried.
CLAIM_RENDER_SQL = (
    "INSERT INTO visualizations "
    "  (purchase_id, status, generations, result_n) "
    "VALUES (%s, 'ready', 1, 1) "
    "ON DUPLICATE KEY UPDATE status = 'ready', generations = 1, "
    "  result_n = 1, error = NULL"
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


# A photograph uploaded before there is a purchase to hang it on, kept under
# the session that took the quiz. It becomes a real one at the webhook, or it
# is deleted unread.
PENDING = "pending"


def pending_dir(session_id):
    """The directory for one un-bought session.

    The name is a UUID and it is re-checked here rather than trusted from the
    caller, because this is the one path component in the whole module that
    originates in a request body. A session id that is not a UUID cannot
    address a directory at all, so there is nothing to traverse with.
    """
    if not isinstance(session_id, str) or not UUID_RE.match(session_id):
        raise ValueError("session_id")
    return os.path.join(config.VISUALIZER_DIR, PENDING, session_id)


def pending_source(session_id):
    return os.path.join(pending_dir(session_id), "source.jpg")


# The pre-purchase render and the picture of it the reader is allowed to see.
# `result.jpg` is the real thing at full size and is never served to anybody;
# `teaser.jpg` is the only one the image route will hand over before a purchase
# exists. Same directory as the source, so one `rmtree` still takes all of it.
def pending_result(session_id):
    return os.path.join(pending_dir(session_id), "result.jpg")


def pending_teaser(session_id):
    return os.path.join(pending_dir(session_id), "teaser.jpg")


def pending_state_path(session_id):
    return os.path.join(pending_dir(session_id), "state.json")


# The one-render-per-session claim, in the filesystem rather than the database.
#
# A session has no row and is not going to get one — a table of people who did
# not buy anything is a table we have decided not to keep. So the claim is a
# file that either exists or does not, created with O_EXCL, which on a POSIX
# filesystem is exactly as atomic as the conditional UPDATE the paid path uses
# and answers the same question: two tabs racing produce one winner.
#
# It is never removed. Replacing the photograph does not buy another render,
# and neither does a failure — the marker outlives both and is only ever
# cleared by the whole pending directory going away, at purge or at purchase.
def pending_spend(session_id):
    marker = os.path.join(pending_dir(session_id), "render.claimed")
    try:
        os.makedirs(os.path.dirname(marker), exist_ok=True)
        fd = os.open(marker, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
    except FileExistsError:
        return False
    except OSError:
        log.exception("visualizer: could not claim a pre-purchase render")
        return False
    os.close(fd)
    return True


def read_pending(session_id):
    """The pre-purchase render's state, as a dict. `{}` when there is none."""
    try:
        with open(pending_state_path(session_id), "r") as fh:
            body = json.load(fh)
        return body if isinstance(body, dict) else {}
    except (OSError, ValueError):
        return {}


def write_pending(session_id, body):
    try:
        _write_atomic(pending_state_path(session_id),
                      json.dumps(body, separators=(",", ":")).encode("utf-8"))
    except Exception:
        log.exception("visualizer: could not record the pre-purchase state")


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


# --- pending photographs come and go ---------------------------------------


def purge_pending(max_age_s=None):
    """Delete un-bought photographs older than the window. Returns how many.

    Almost everybody who uploads one does not buy, so this is the path most
    photographs take: they are read by nobody, they become a purchase's or
    they are removed. Forty-eight hours is long enough for somebody to come
    back to a tab the next evening and short enough that a picture of a
    stranger's kitchen is not sitting on a disk a week later.

    Age is the file's own mtime rather than the directory's, so re-uploading
    restarts the clock the way somebody still deciding would expect.

    Never raises. It runs on the upload path and from cron, and neither of
    those should fail because a directory was removed underneath it.
    """
    if max_age_s is None:
        max_age_s = config.VISUALIZER_PENDING_MAX_AGE_S
    root = os.path.join(config.VISUALIZER_DIR, PENDING)
    cutoff = time.time() - max_age_s
    removed = 0
    try:
        names = os.listdir(root)
    except OSError:
        return 0

    for name in names:
        path = os.path.join(root, name)
        try:
            source = os.path.join(path, "source.jpg")
            if os.path.isfile(source):
                if os.path.getmtime(source) > cutoff:
                    continue
            elif os.path.getmtime(path) > cutoff:
                # An empty directory, left by a claim or a half-finished write.
                # Aged out on its own mtime rather than kept forever.
                continue
            shutil.rmtree(path, ignore_errors=True)
            removed += 1
        except OSError:
            continue
    if removed:
        log.info("visualizer: purged %d pending photo(s)", removed)
    return removed


# The sweep walks every pending directory, which is fine once in a while and
# silly on every upload. This is the last time it ran, so a busy hour costs one
# sweep rather than one per photograph.
_last_purge = [0.0]


def maybe_purge_pending():
    """Sweep at most once per interval, from whichever request gets there."""
    now = time.time()
    if now - _last_purge[0] < config.VISUALIZER_PURGE_EVERY_S:
        return
    _last_purge[0] = now
    try:
        purge_pending()
    except Exception:
        log.exception("visualizer: pending purge failed")


def claim_pending(purchase_id, session_id, cfg):
    """Move a session's photograph onto a purchase. Returns True if one moved.

    Called from the webhook, once, after the purchase row exists. Everything
    after this point is the flow that already existed: there is a photo under
    the purchase and a row saying so, exactly as if it had been uploaded from
    the paid page.

    Idempotent by construction rather than by checking: a replayed webhook
    finds nothing left to move, because the first one moved it.
    """
    if settings(cfg) is None:
        return False
    try:
        source = pending_source(session_id)
    except ValueError:
        return False
    if not os.path.isfile(source):
        return False

    target = source_path(purchase_id)
    try:
        os.makedirs(os.path.dirname(target), exist_ok=True)
        # A rename, not a copy: it is atomic, it cannot half-succeed, and it
        # leaves no second copy of somebody's kitchen behind to be collected
        # later. Both paths are under VISUALIZER_DIR, so it never crosses a
        # filesystem.
        os.replace(source, target)
    except OSError:
        log.exception("visualizer: could not move the pending photo onto "
                      "purchase %s", purchase_id)
        return False

    try:
        shutil.rmtree(pending_dir(session_id), ignore_errors=True)
    except (OSError, ValueError):
        pass

    # The render this session already paid us for, moved with the photograph.
    #
    # This is the whole point of rendering early: the buyer lands on the paid
    # page and their kitchen is already there. Nothing regenerates, no second
    # call is made, and `generations` is set to 1 so the paid page reports one
    # render used out of two — which leaves the re-run they were promised
    # intact. What the pre-purchase render spent was our money, not theirs.
    rendered = False
    try:
        pre = pending_result(session_id)
        if os.path.isfile(pre):
            os.replace(pre, result_path(purchase_id, 1))
            rendered = True
    except (OSError, ValueError):
        # The photograph is already across, so this degrades to the flow that
        # shipped before: the paid page finds a source and offers the button.
        log.exception("visualizer: could not claim the pre-purchase render "
                      "for purchase %s", purchase_id)
        rendered = False

    try:
        database.execute(CLAIM_RENDER_SQL if rendered else UPSERT_STATE_SQL,
                         (purchase_id,))
    except Exception:
        # The photo is in place and the row is not. The paid page's status
        # endpoint reports `none` while the file sits there, and re-uploading
        # from the paid page recovers it — which is the existing flow, so this
        # degrades to what shipped before rather than to nothing.
        log.exception("visualizer: photo moved but the row failed for "
                      "purchase %s", purchase_id)
        return False

    log.info("visualizer: pending photo claimed by purchase %s%s",
             purchase_id, " with its render" if rendered else "")
    return True


# --- taking a photograph in ------------------------------------------------


class IntakeError(Exception):
    """A photo we will not accept, carrying the reason the reader is told."""

    def __init__(self, code, message):
        Exception.__init__(self, code)
        self.code = code
        self.message = message


def register_image_formats():
    """Teach Pillow the formats a phone sends. Idempotent, never raises.

    Only HEIC needs teaching. MPO — what a portrait or burst shot arrives as —
    Pillow already reads, and WEBP and the rest have always been built in.

    Called at boot from app.py and again from the intake path, because the
    intake path is also reached by scripts and tests that never import app.
    Registering twice is free; registering not at all is a funnel that refuses
    every photograph taken on an iPhone.
    """
    global _formats_registered
    if _formats_registered:
        return
    with _formats_lock:
        if _formats_registered:
            return
        try:
            from pillow_heif import register_heif_opener
            register_heif_opener()
            log.info("visualizer: HEIC/HEIF support registered")
        except Exception as exc:
            # Not fatal, and deliberately so. Everything that is not HEIC still
            # works; an iPhone photographing straight from the camera does not.
            # Loud enough to find in a log, quiet enough not to stop a boot.
            log.error("pillow-heif is not available (%s) — HEIC uploads will "
                      "be refused. Run: pip install -r requirements.txt",
                      type(exc).__name__)
        # Set either way: a second attempt would fail identically, and the
        # error belongs in the log once rather than on every upload.
        _formats_registered = True


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

    register_image_formats()

    try:
        # `open` reads the header and stops. The pixels are not decoded until
        # `load()`, which is what makes the size check below worth anything:
        # it happens before we have allocated for them.
        #
        # What decides the format is this call and nothing else. The filename,
        # the extension and the Content-Type are all the client's word for it,
        # and on a phone all three are routinely wrong — a share sheet will
        # hand over a HEIC called IMG_0001.JPG marked image/jpeg. The bytes
        # are the only honest answer.
        img = Image.open(io.BytesIO(raw))
        fmt = img.format
    except Exception:
        raise IntakeError("not_an_image", UNREADABLE)

    if fmt in REFUSED_FORMATS:
        log.info("visualizer: refused a %s upload", fmt)
        raise IntakeError("wrong_format", UNREADABLE)

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
        # A portrait or burst shot arrives as MPO, which is several JPEGs in
        # one file — the photograph, then a depth map or the frames either side
        # of it. Frame 0 is the picture that was taken, and it is what Pillow
        # lands on already; seeking to it says so out loud and costs nothing.
        if getattr(img, "n_frames", 1) > 1:
            img.seek(0)

        img.load()

        # Reads the orientation tag, rotates the pixels, returns an image with
        # no orientation tag left to disagree with them.
        #
        # Right for every format here, including the two that disagree about
        # who does the rotating. A JPEG or an MPO arrives unrotated with a tag
        # saying which way is up, and this is what stands it up. A HEIC does
        # not: libheif applies the container's rotation while decoding, and
        # pillow-heif rewrites the EXIF tag to 1 on the way out precisely so
        # that a caller doing this does not rotate it a second time. Both
        # paths end with upright pixels and no tag.
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
        raise IntakeError("unreadable", UNREADABLE)

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


def _post_edit(prompt, jpeg, size=None):
    """One call to the images/edits endpoint. Returns JPEG bytes.

    Raw urllib rather than a client library: this is a single multipart POST
    against a documented URL, and a dependency that has to be installed by hand
    on the server before the feature works is a worse trade than thirty lines.
    """
    content_type, body = _multipart(
        fields=[("model", config.OPENAI_IMAGE_MODEL),
                ("prompt", prompt),
                # Chosen from the source photograph's own shape rather than
                # fixed, so the render comes back closer to the box it has to
                # sit in and less of it is cropped away afterwards.
                ("size", size or config.OPENAI_IMAGE_SIZE),
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


def generate_image(prompt, jpeg, size=None):
    """The edit, with one retry on the failures that are worth retrying."""
    if not config.OPENAI_API_KEY:
        log.error("OPENAI_API_KEY is not configured — generation unavailable")
        raise GenerationError("unconfigured", retriable=False)

    try:
        return _post_edit(prompt, jpeg, size)
    except GenerationError as first:
        if not first.retriable or first.billed:
            raise
        log.info("visualizer: retrying after %s", first.code)
        time.sleep(2)
        return _post_edit(prompt, jpeg, size)


# --- exposure ---------------------------------------------------------------

# The model hands back a room a third darker than the one that was
# photographed. Measured over fourteen real renders on this server: the source
# photos average a mean luma of 121 and the renders 86, and the worst of them
# land at 40-48 with seventy per cent of their pixels near black. Somebody paid
# to look at their own kitchen and cannot see the bottom half of it.
#
# This is not a prompt problem, and that was established by trying. Three
# wordings on one source photo: the original at 40.8, explicit not-dim
# negatives at 62.4, purely positive "midday, blinds open" at 47.9. The spread
# between them is noise. images/edits reproduces the exposure of the photograph
# it is given, whatever it is told, so the correction belongs after the render
# and not in front of it. The prompt is right and stays as it is.
#
# A gamma lift and not a brightness add: adding a constant lifts the black
# point and everything goes milky, where a gamma curve opens the shadows and
# leaves the highlights where they are. The exponent is searched per image
# rather than fixed, because the renders that need it vary by a factor of three
# and one constant would either under-serve the dark ones or blow out the rest.

# Where a corrected render should land. Chosen against the source photos this
# is trying to match — they average 121 — rather than against a notion of
# correct exposure.
EXPOSURE_TARGET = 118.0

# The strongest lift that is allowed, and it is a real limit rather than a
# safety margin: verified on a render at 47.9, a gamma of 0.39 took the greens
# to grey and blew out the foreground. A slightly dark kitchen is a photograph
# of their kitchen; a washed-out one is not. Anything needing more than this
# gets this and stops.
EXPOSURE_GAMMA_FLOOR = 0.42

# The search runs below the floor so the log can say the floor was reached.
EXPOSURE_GAMMA_MIN = 0.30
EXPOSURE_STEPS = 24

# Opening the shadows costs a little saturation. This puts it back and no more.
EXPOSURE_SATURATION = 1.05


def _gamma_lut(gamma):
    """A 256-entry curve for one gamma, for `Image.point`."""
    return [min(255, int((i / 255.0) ** gamma * 255 + 0.5)) for i in range(256)]


def _mean_luma(img, ImageStat):
    return ImageStat.Stat(img.convert("L")).mean[0]


def _apply_gamma(img, gamma, ImageEnhance):
    out = img.point(_gamma_lut(gamma) * 3)
    return ImageEnhance.Color(out).enhance(EXPOSURE_SATURATION)


def lift_exposure(raw):
    """One render, brought up to the exposure of the photograph it came from.

    Returns `(bytes, note)`. The note is one short line for the log, because
    the effect of this has to be readable off the server without going and
    measuring files.

    Never raises. A reader who has paid, waited and been billed for a
    generation must not lose the image to a post-processing step, so anything
    that goes wrong here hands back exactly what the model returned and says
    so. Same discipline as the billing degrade path.

    Never darkens. `gamma` is capped at 1.0, so a render that already arrives
    at or above the target is returned untouched — the same object, not a
    re-encode of it, so a bright render is bit-for-bit what the model sent.
    """
    try:
        from PIL import Image, ImageEnhance, ImageStat

        img = Image.open(io.BytesIO(raw))
        img.load()
        img = img.convert("RGB")

        before = _mean_luma(img, ImageStat)
        if before >= EXPOSURE_TARGET:
            return raw, "%.1f, already at target, untouched" % before

        # Mean luma falls as gamma rises, so the search is a plain bisection on
        # a monotone function: `lo` is the brightest exponent allowed and `hi`
        # is no change at all. Measured on the converted image rather than
        # predicted from the histogram — the saturation step moves it too.
        lo, hi = EXPOSURE_GAMMA_MIN, 1.0
        for _ in range(EXPOSURE_STEPS):
            mid = (lo + hi) / 2.0
            if _mean_luma(_apply_gamma(img, mid, ImageEnhance),
                          ImageStat) < EXPOSURE_TARGET:
                hi = mid
            else:
                lo = mid
        wanted = (lo + hi) / 2.0

        gamma = max(EXPOSURE_GAMMA_FLOOR, min(1.0, wanted))
        floored = gamma > wanted + 1e-6

        out = _apply_gamma(img, gamma, ImageEnhance)
        after = _mean_luma(out, ImageStat)

        buf = io.BytesIO()
        # No `exif=`, no `icc_profile=`: nothing is carried across that was not
        # asked for, the same way the intake re-encode works.
        out.save(buf, "JPEG", quality=config.VISUALIZER_JPEG_QUALITY,
                 optimize=True)
        return buf.getvalue(), "%.1f -> %.1f, gamma %.3f%s" % (
            before, after, gamma,
            " (floored, wanted %.3f)" % wanted if floored else "")
    except Exception as exc:
        # Loud, and then out of the way. The render is what was paid for.
        log.warning("visualizer: exposure correction failed (%s) — storing "
                    "the render as it came back", type(exc).__name__)
        return raw, "correction failed, stored uncorrected"


# --- shaping the render ----------------------------------------------------

# The three sizes gpt-image-1 will produce, and nothing else. Asking for the
# source photograph's own dimensions is not an option, so the closest of these
# is chosen and the difference is taken out afterwards by cropping.
EDIT_SQUARE = "1024x1024"
EDIT_PORTRAIT = "1024x1536"
EDIT_LANDSCAPE = "1536x1024"

# Where a photograph stops being square enough to render square. Generous on
# purpose: a 4:3 phone photo (1.33) is portrait, a 5:4 (1.25) is portrait, and
# anything inside these bounds is close enough that cropping a square render to
# it costs almost nothing.
RATIO_PORTRAIT = 1.15
RATIO_LANDSCAPE = 0.87

# How far the render may be cropped to agree with the source. Past this, the
# two panels stay slightly different shapes and the reader keeps their kitchen:
# cutting away a third of a room so that two boxes line up is paying for
# symmetry with the thing being sold.
RATIO_CAP = 1.7


def _ratio_of(raw):
    """height / width for some encoded image, or None if unreadable."""
    try:
        from PIL import Image
        with Image.open(io.BytesIO(raw)) as img:
            width, height = img.size
        if not width or not height:
            return None
        return float(height) / float(width)
    except Exception:
        return None


def edit_size(raw):
    """Which of the model's three sizes suits this source photograph."""
    ratio = _ratio_of(raw)
    if ratio is None:
        return EDIT_SQUARE
    if ratio > RATIO_PORTRAIT:
        return EDIT_PORTRAIT
    if ratio < RATIO_LANDSCAPE:
        return EDIT_LANDSCAPE
    return EDIT_SQUARE


def match_ratio(render, source):
    """Crop `render` to the shape of `source`. Returns `(bytes, note)`.

    Both panels on the page are the same box, so two pictures of different
    shapes inside them either letterbox or crop in CSS — and CSS cropping is
    done by the browser at display time, on the full image, differently at
    every width. Doing it here means the file itself is the right shape and
    every viewport agrees.

    Never raises, for the same reason `lift_exposure` never does: the render is
    what was paid for and a framing step must not be able to lose it.
    """
    try:
        from PIL import Image

        want = _ratio_of(source)
        have = _ratio_of(render)
        if not want or not have:
            return render, "no ratio, uncropped"

        # Clamped rather than refused. A source and a render this far apart
        # still get most of the way to agreeing; they simply stop before the
        # crop starts costing real kitchen.
        capped = min(max(want, have / RATIO_CAP), have * RATIO_CAP)
        note = ""
        if abs(capped - want) > 1e-6:
            note = " (capped at %.2f, wanted %.2f)" % (RATIO_CAP, want / have)
        want = capped

        if abs(want - have) < 0.01:
            return render, "%.2f already, uncropped" % have

        with Image.open(io.BytesIO(render)) as img:
            img.load()
            img = img.convert("RGB")
            width, height = img.size
            if want > have:                 # taller wanted: take width off
                new_w = int(round(height / want))
                new_h = height
            else:                           # wider wanted: take height off
                new_w = width
                new_h = int(round(width * want))
            new_w = max(1, min(width, new_w))
            new_h = max(1, min(height, new_h))
            left = (width - new_w) // 2
            top = (height - new_h) // 2
            out = img.crop((left, top, left + new_w, top + new_h))

        buf = io.BytesIO()
        out.save(buf, "JPEG", quality=config.VISUALIZER_JPEG_QUALITY,
                 optimize=True)
        return buf.getvalue(), "%.2f -> %.2f%s" % (have, want, note)
    except Exception as exc:
        log.warning("visualizer: ratio match failed (%s) — storing the render "
                    "as it came back", type(exc).__name__)
        return render, "crop failed, uncropped"


# --- the locked teaser ------------------------------------------------------

# A separate, deliberately small file.
#
# What the reader was shown before this was their own photograph behind a CSS
# blur — a picture of the room they already have, with an orange wash over it.
# They were being asked to pay for something they had to imagine. This is the
# real transformation, half of it sharp.
#
# It is built here rather than by the browser because a CSS filter is a
# decoration over a file the browser already has: anybody who opens the network
# tab has the unblurred image. The blur has to be in the pixels, and the pixels
# have to be a downscale, so that possessing this file is not possessing the
# product.
TEASER_LONG_SIDE = 560          # against a render of 1024-1536
TEASER_QUALITY = 82
TEASER_BLUR_DIVISOR = 26        # radius as a fraction of the shorter side
TEASER_FEATHER = 0.018          # of the shorter side, per the brief
TEASER_GRADIENT = 64            # the ramp is linear, so it resizes exactly

BRAND_CREAM = (247, 242, 234)
BRAND_ACCENT = (192, 86, 33)

# The server may not carry any particular font. Probed in order, and if none of
# them loads the wordmark falls back to Pillow's own bitmap face — smaller and
# plainer, and still a wordmark, which is better than a teaser that fails to
# build because a font moved.
_FONT_CANDIDATES = (
    "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
    "/usr/share/fonts/truetype/freefont/FreeSansBold.ttf",
    "/usr/share/fonts/truetype/liberation/LiberationSans-Bold.ttf",
    "/usr/share/fonts/TTF/DejaVuSans-Bold.ttf",
    "/System/Library/Fonts/Supplemental/Arial Bold.ttf",
)


def _brand_font(size):
    from PIL import ImageFont
    for path in _FONT_CANDIDATES:
        try:
            return ImageFont.truetype(path, size)
        except Exception:
            continue
    try:
        return ImageFont.load_default(size)
    except Exception:
        return ImageFont.load_default()


def _diagonal_mask(size, feather_px, Image):
    """255 on the bottom-right of the anti-diagonal, 0 on the top-left.

    The anti-diagonal runs corner to corner, from top-right to bottom-left, so
    the two halves are triangles of equal area whatever the aspect ratio.

    Built small and resized rather than looped per pixel. `x/W + y/H` is linear,
    and bilinear interpolation of a linear function is exact, so a 64x64 ramp
    stretched to full size is the same surface — at a thousandth of the cost on
    a page somebody is waiting in front of. The feather is then a curve applied
    to the ramp's values, which is why it can be specified in pixels.
    """
    width, height = size
    n = TEASER_GRADIENT
    ramp = Image.new("L", (n, n))
    ramp.putdata([int(round((x + y) * 255.0 / (2 * (n - 1))))
                  for y in range(n) for x in range(n)])
    ramp = ramp.resize((width, height), Image.BILINEAR)

    # How much of the ramp's 0-255 range one pixel of travel across the
    # diagonal is worth, so `feather_px` means pixels on the finished image.
    per_px = 255.0 * 0.5 * ((1.0 / width) ** 2 + (1.0 / height) ** 2) ** 0.5
    half = max(1.0, feather_px * per_px)

    lut = []
    for value in range(256):
        t = (value - 127.5) / (2.0 * half) + 0.5
        t = 0.0 if t < 0 else (1.0 if t > 1 else t)
        lut.append(int(round(t * t * (3 - 2 * t) * 255)))   # smoothstep
    return ramp.point(lut)


def _padlock(draw, cx, cy, unit):
    """A shackle and a body, drawn rather than fetched."""
    body_w = unit * 1.5
    body_h = unit * 1.25
    left = cx - body_w / 2.0
    top = cy - body_h / 2.0 + unit * 0.28
    draw.rounded_rectangle([left, top, left + body_w, top + body_h],
                           radius=unit * 0.28, fill=BRAND_CREAM)
    draw.arc([cx - unit * 0.62, cy - unit * 1.25,
              cx + unit * 0.62, cy + unit * 0.15],
             start=180, end=360, fill=BRAND_CREAM, width=max(2, int(unit * 0.3)))


def build_teaser(render):
    """The locked half of a render, as its own small file. Returns bytes.

    Raises rather than degrading: the caller decides what a missing teaser
    means, and on the pre-purchase path it means falling back to the blur the
    page already had.
    """
    from PIL import Image, ImageDraw, ImageFilter

    with Image.open(io.BytesIO(render)) as src:
        src.load()
        img = src.convert("RGB")

    # Downscaled FIRST, and everything after this works on the small copy, so
    # no operation in this function has full-resolution pixels to lose.
    width, height = img.size
    scale = float(TEASER_LONG_SIDE) / max(width, height)
    if scale < 1.0:
        img = img.resize((max(1, int(round(width * scale))),
                          max(1, int(round(height * scale)))), Image.LANCZOS)
    width, height = img.size
    short = min(width, height)

    blurred = img.filter(ImageFilter.GaussianBlur(short / TEASER_BLUR_DIVISOR))
    mask = _diagonal_mask((width, height), short * TEASER_FEATHER, Image)
    out = Image.composite(blurred, img, mask)

    # Everything drawn on top goes through one RGBA layer, so the scrims are
    # translucent against the picture rather than flat rectangles over it.
    layer = Image.new("RGBA", (width, height), (0, 0, 0, 0))
    draw = ImageDraw.Draw(layer)

    unit = short * 0.115
    cx, cy = width / 2.0, height / 2.0
    draw.ellipse([cx - unit * 1.7, cy - unit * 1.7,
                  cx + unit * 1.7, cy + unit * 1.7], fill=(24, 18, 14, 150))
    _padlock(draw, cx, cy, unit)

    # The wordmark, bottom right, on a pill dark enough to read over anything.
    font = _brand_font(max(11, int(short * 0.062)))
    word, dot = "mazzin", "."
    try:
        w_word = draw.textlength(word, font=font)
        w_dot = draw.textlength(dot, font=font)
        ascent = font.getbbox("M")[3] - font.getbbox("M")[1]
    except Exception:
        w_word, w_dot, ascent = short * 0.22, short * 0.03, short * 0.06
    pad_x, pad_y = short * 0.045, short * 0.028
    pill_w = w_word + w_dot + pad_x * 2
    pill_h = ascent + pad_y * 2
    x1 = width - short * 0.045
    y1 = height - short * 0.045
    x0, y0 = x1 - pill_w, y1 - pill_h
    draw.rounded_rectangle([x0, y0, x1, y1], radius=pill_h / 2.0,
                           fill=(24, 18, 14, 165))
    tx = x0 + pad_x
    ty = y0 + pad_y - (font.getbbox("M")[1] if hasattr(font, "getbbox") else 0)
    draw.text((tx, ty), word, font=font, fill=BRAND_CREAM + (255,))
    draw.text((tx + w_word, ty), dot, font=font, fill=BRAND_ACCENT + (255,))

    out = Image.alpha_composite(out.convert("RGBA"), layer).convert("RGB")

    buf = io.BytesIO()
    out.save(buf, "JPEG", quality=TEASER_QUALITY, optimize=True)
    return buf.getvalue()


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
            image = generate_image(prompt, jpeg, edit_size(jpeg))
        except GenerationError as exc:
            _release(purchase_id, exc.code, billed=exc.billed)
            return

        state = read_state(purchase_id) or {}
        n = int(state.get("generations") or 1)

        # Between the model and the disk, and nowhere else. The reader's own
        # photograph is never touched by this — it is stored by the intake
        # path, long before any of this runs, and the blurred teaser is that
        # same file behind a CSS filter. Only what the model produced is
        # corrected, and only on its way to being stored.
        image, exposure = lift_exposure(image)
        image, framing = match_ratio(image, jpeg)
        log.info("visualizer: purchase %s render %d exposure %s, ratio %s",
                 purchase_id, n, exposure, framing)

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


# --- the render before the money -------------------------------------------

# What the reader was being asked to buy, before this, was a blur over their
# own photograph — the room they already have, behind an orange wash, with a
# padlock on it. Thirteen of them uploaded a photo, reached the offer, spent
# two to eight minutes reading, and bought nothing. They were being asked to
# imagine the product.
#
# So the render happens on upload, at our cost, and half of it is shown. The
# file the browser can reach is a downscale with the other half blurred into
# the pixels; the real one sits on disk under the session and is served to
# nobody until a purchase claims it.

PRE_STARTED, PRE_READY, PRE_FAILED = "generating", "ready", "failed"

# How long the page will wait before deciding a pre-purchase render is not
# coming. The model takes twenty to thirty seconds; this is generous enough to
# cover a slow one and short enough that nobody watches a spinner for a minute.
PRE_RENDER_STALE_S = 90


def pre_render_on(block):
    """Whether this funnel renders before the money. Config, never inference.

    Both flags: `pre_purchase` is what lets a session hold a photograph at all,
    and this is what makes one cost money. Off, and everything else here
    behaves exactly as it did — the teaser falls back to the blur.
    """
    return (block or {}).get("pre_purchase_render") is True


def _style_by_id(cfg, style_id):
    for style in (cfg or {}).get("styles") or []:
        if isinstance(style, dict) and style.get("id") == style_id:
            return style
    return None


def _pre_purchase_content(cfg, style_id, element_ids):
    """A stand-in for the stored report, built from the funnel's own config.

    `build_prompt` reads a paid report — the style's name, the palette with its
    codes, and which elements this reader was shown. Before the money none of
    that exists: the report is written after the webhook. What does exist is
    the config the free page was drawn from, and the reader has already seen it
    — the five blocks under YOUR PALETTE and the four pictures under YOUR
    MATERIALS are these exact values.

    So the pre-purchase render is built from the style's palette rather than
    from the personalised one the report will later write. That is a real
    difference and it is the right way round: what the teaser shows is what the
    reader was shown, and the paid re-run — which happens after the report
    exists — uses the personalised palette.

    Everything here is validated against the config. `style_id` and the element
    ids arrive in the upload request, so they are treated as what they are: a
    claim by the browser about which result it computed, checked against the
    list of results this funnel can produce.
    """
    style = _style_by_id(cfg, style_id)
    if style is None:
        return None

    colours = (((style.get("reveals") or {}).get("palette") or {})
               .get("colors") or [])
    if not colours:
        return None

    names = ["dominant", "secondary", "accent"]
    data = {"colors": []}
    for index, key in enumerate(names):
        colour = colours[index] if index < len(colours) else {}
        data["colors"].append({"name": colour.get("name") or "",
                               "hex": reports._config_hex(colour) or ""})

    known = {item.get("id") for item
             in ((cfg.get("style_elements") or {}).get("items") or [])
             if isinstance(item, dict)}
    elements = [eid for eid in (element_ids or [])
                if isinstance(eid, str) and eid in known]

    return {"style_name": style.get("name") or "",
            "elements": elements,
            "sections": [{"id": "palette", "data": data}]}


def run_pre_render(session_id, cfg, block, style_id, element_ids):
    """The worker for one un-bought session. Never raises into the caller.

    A failure here costs nothing that matters: the state file says so, the page
    falls back to the blur it has always shown, and the reader walks on to the
    offer. A teaser that did not build must never be the reason a sale did not
    happen.
    """
    try:
        content = _pre_purchase_content(cfg, style_id, element_ids)
        prompt = build_prompt(cfg, block, content) if content else None
        if not prompt:
            log.warning("visualizer: no pre-purchase prompt for this session "
                        "— falling back to the blur")
            write_pending(session_id, {"status": PRE_FAILED,
                                       "error": "no_prompt"})
            return

        try:
            with open(pending_source(session_id), "rb") as fh:
                jpeg = fh.read()
        except OSError:
            write_pending(session_id, {"status": PRE_FAILED,
                                       "error": "no_source"})
            return

        try:
            image = generate_image(prompt, jpeg, edit_size(jpeg))
        except GenerationError as exc:
            log.warning("visualizer: pre-purchase render failed (%s) — the "
                        "page falls back to the blur", exc.code)
            write_pending(session_id, {"status": PRE_FAILED,
                                       "error": exc.code[:32]})
            return

        image, exposure = lift_exposure(image)
        image, framing = match_ratio(image, jpeg)

        try:
            teaser = build_teaser(image)
        except Exception:
            # The render is fine and only the half-blurred copy of it is not.
            # Kept on disk anyway: a purchase still claims it, so the buyer
            # gets their image even though the teaser fell back to the blur.
            log.exception("visualizer: could not build the teaser")
            _write_atomic(pending_result(session_id), image)
            write_pending(session_id, {"status": PRE_FAILED,
                                       "error": "teaser_failed"})
            return

        # The full render first, then the teaser, then the state that admits
        # either exists. Written in that order so the page can never be told
        # there is a teaser a moment before there is one.
        _write_atomic(pending_result(session_id), image)
        _write_atomic(pending_teaser(session_id), teaser)
        write_pending(session_id, {"status": PRE_READY})
        log.info("visualizer: pre-purchase render ready — exposure %s, "
                 "ratio %s, teaser %d bytes", exposure, framing, len(teaser))
    except Exception:
        log.exception("visualizer: pre-purchase render crashed")
        try:
            write_pending(session_id, {"status": PRE_FAILED,
                                       "error": "crashed"})
        except Exception:
            pass


def start_pre_render(who, style_id, element_ids):
    """Spend this session's one render, if it has one left. Returns True.

    Called from the upload route, on the un-bought path only. Everything that
    decides whether an API call happens is in here, so the route stays a route.
    """
    if not pre_render_on(who.block) or who.paid or not who.session_id:
        return False
    if not config.OPENAI_API_KEY:
        # Same kill switch as everywhere else: an empty key is a feature that
        # is off, not an error.
        return False
    if not pending_spend(who.session_id):
        return False

    write_pending(who.session_id, {"status": PRE_STARTED,
                                   "started": time.time()})
    thread = threading.Thread(
        target=run_pre_render,
        args=(who.session_id, who.cfg, who.block, style_id, element_ids),
        daemon=True)
    thread.start()
    return True


# --- auth ------------------------------------------------------------------


class Denied(Exception):
    """Refused before any work was done, with the status to answer."""

    def __init__(self, status, code):
        Exception.__init__(self, code)
        self.status = status
        self.code = code


class Subject:
    """Whose photograph this is, and which of the two ways we know that.

    Two things can own a photo here and they are not the same kind of thing.

    A **purchase** is identified by the result-link token, has been confirmed
    paid by Stripe, and is the only thing that may ever spend a generation.

    A **session** is identified by the quiz session id and is nobody in
    particular — the reader has not paid and may never. It can put a photo up
    and look at it, and that is the whole list. Keeping the two as one object
    with a `paid` flag rather than as two code paths is deliberate: the intake
    pipeline, the storage rules and the image route are genuinely identical
    for both, and the one place they differ is the one place that matters, so
    it is written out on its own rather than spread across four routes.
    """

    def __init__(self, cfg, block, token, purchase=None, session_id=None):
        self.cfg = cfg
        self.block = block
        self.token = token          # what the browser calls back with
        self.purchase = purchase
        self.session_id = session_id

    @property
    def paid(self):
        return self.purchase is not None

    @property
    def purchase_id(self):
        return self.purchase["id"] if self.purchase else None

    def source(self):
        return (source_path(self.purchase["id"]) if self.paid
                else pending_source(self.session_id))

    def query(self):
        """The credential, as the browser must send it back."""
        if self.paid:
            return "cs=" + urllib.parse.quote(self.token, safe="")
        return "session_id=%s&funnel=%s" % (
            urllib.parse.quote(self.session_id, safe=""),
            urllib.parse.quote(self.cfg.get("slug") or "", safe=""))


def _param(name):
    value = request.args.get(name)
    if not value and request.method == "POST":
        value = request.form.get(name)
    return value


def _pending_subject():
    """A reader who has run the quiz and not bought anything, or None.

    Deliberately weaker than a purchase and deliberately not nothing. What it
    proves is that this session actually ran this funnel — there is an event
    row for it — which is not identity, and is not meant to be. It is the
    difference between an endpoint anyone can write eight megabytes to and one
    that costs a full quiz run per photograph.
    """
    session_id = _param("session_id")
    if not isinstance(session_id, str) or not UUID_RE.match(session_id):
        return None

    slug = _param("funnel")
    if not config.funnel_exists(slug):
        raise Denied(404, "no_funnel")

    try:
        cfg = config.load_funnel(slug)
    except (KeyError, ValueError, OSError):
        raise Denied(404, "no_funnel")

    block = settings(cfg)
    if block is None:
        raise Denied(404, "no_visualizer")
    if block.get("pre_purchase") is not True:
        # The funnel offers the feature but not before the money. Same answer
        # as a funnel that does not offer it at all, because from the browser's
        # side it is the same fact: there is nothing for you here yet.
        raise Denied(404, "no_visualizer")

    try:
        seen = database.query_one(SELECT_SESSION_SEEN_SQL, (session_id, slug))
    except Exception:
        log.exception("visualizer: session lookup failed")
        raise Denied(500, "lookup_failed")
    if not seen:
        raise Denied(403, "unknown_session")

    return Subject(cfg, block, session_id, session_id=session_id)


def _resolve(allow_pending):
    """The subject for this request, or a refusal.

    `allow_pending` is the COGS line, written once. Everything that only
    handles a photograph the reader already owns takes either credential;
    generation takes the paid one and nothing else, because a generation is
    the one operation here that bills an account.
    """
    if _param("cs"):
        return _authorise()
    if allow_pending:
        pending = _pending_subject()
        if pending is not None:
            return pending
    # No usable credential of either kind. Answered as a bad token rather than
    # as a missing session so the two modes cannot be told apart by probing.
    raise Denied(400, "bad_token")


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
    if not isinstance(cs, str) or not RESULT_TOKEN_RE.match(cs):
        raise Denied(400, "bad_token")

    try:
        # payments.py owns what a result token resolves to. Two copies of that
        # SELECT is how the visualizer ends up unable to find a purchase the
        # report can — which is precisely what would have happened the day an
        # in-page payment produced a `pi_` token and only one of them knew.
        purchase = find_purchase(cs)
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

    return Subject(cfg, block, cs, purchase=purchase)


def _denied(exc):
    return jsonify({"error": exc.code}), exc.status


# --- saying why, every time -------------------------------------------------


def _signature(raw, count=8):
    """The first few bytes as hex. What the file claims to be, structurally.

    Eight bytes is enough to name a container and nowhere near enough to be
    content: `ffd8ffe0` is a JPEG, `0000001c66747970` is the front of an ISO
    box and says HEIC, `89504e47` is a PNG. When somebody's phone sends
    something we cannot read, this is the difference between "an upload
    failed" and "that model writes a variant we do not decode".
    """
    return (raw or b"")[:count].hex()


def refused(reason, raw=None, extra=None):
    """One line per rejected upload. No exceptions.

    An upload that fails and leaves nothing in the log is a bug report with no
    evidence in it, and that is precisely what happened: a photograph over the
    ceiling was refused by Werkzeug before this module ran at all, so the
    server had nothing to say and the page showed the wrong sentence. Every
    path that turns an upload away now comes through here.

    What is logged is a reason from a closed set, the declared length, the
    declared type and eight bytes of signature. What is not logged is the
    filename, the rest of the bytes, and anything else about the picture —
    those belong to whoever took it.
    """
    parts = ["visualizer: upload refused (%s)" % reason]
    length = request.headers.get("Content-Length")
    parts.append("len=%s" % (length if length else "?"))

    upload_file = None
    try:
        upload_file = request.files.get("photo")
    except Exception:
        # Reading `files` re-parses the body, which is exactly what failed on
        # the path this function exists for. Never let logging raise.
        pass
    claimed = getattr(upload_file, "mimetype", None) or request.content_type
    parts.append("type=%s" % (str(claimed)[:60] if claimed else "?"))

    if raw is not None:
        parts.append("sig=%s" % _signature(raw))
    if extra:
        parts.append(str(extra)[:80])
    log.info(" ".join(parts))


# --- routes ----------------------------------------------------------------


@bp.post("/api/visualizer/upload")
def upload():
    try:
        who = _resolve(allow_pending=True)
    except Denied as exc:
        # An upload turned away at the door used to be as silent as one turned
        # away for its size — and this is the one somebody hits by opening a
        # friend's result link, where the fix is a sentence rather than a
        # smaller photograph.
        refused(exc.code)
        return _denied(exc)

    if who.paid:
        state = read_state(who.purchase_id) or {}
        if state.get("status") == GENERATING and not _stale(state):
            # Replacing the photograph under a render that is already running
            # would produce a before/after of two different rooms. Only while
            # it really is running, though: the same staleness rule the status
            # endpoint uses, so a worker that died does not lock the picker for
            # five minutes on a page that has already given up on it.
            return jsonify(
                {"error": "generating",
                 "message": "Hold on — a transformation is running."}), 409
    else:
        # Cheap, and on the one path that creates pending photographs, so the
        # sweep runs about as often as they arrive. Before the write rather
        # than after, so a burst cannot outpace it.
        maybe_purge_pending()

    upload_file = request.files.get("photo")
    if upload_file is None:
        refused("no_file")
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
        # The signature is the whole point of logging this one: a phone that
        # writes a container we cannot read is indistinguishable from a broken
        # upload until you can see the first eight bytes of it.
        refused(exc.code, raw)
        return jsonify({"error": exc.code, "message": exc.message}), 400

    try:
        _write_atomic(who.source(), jpeg)
    except Exception:
        log.exception("visualizer: could not store the source photo")
        refused("store_failed", raw)
        return jsonify({"error": "store_failed",
                        "message": "We couldn't save that. Try again."}), 500

    # Only a purchase has a row. A session's photograph is a file and nothing
    # else — there is no state to keep about somebody who has not bought
    # anything, and a table of them would be a list of people who did not.
    if who.paid:
        try:
            database.execute(UPSERT_STATE_SQL, (who.purchase_id,))
        except Exception:
            log.exception("visualizer: could not record the upload")
            return jsonify({"error": "store_failed",
                            "message": "We couldn't save that. Try again."}), 500
    else:
        # The one render this session gets, spent here or never. `style` and
        # `elements` are the browser's account of the result it computed and
        # are checked against the funnel's own config before a word of either
        # reaches a prompt. Replacing the photograph runs this again and it
        # returns False, because the claim is a file that already exists.
        start_pre_render(who, _param("style"),
                         (_param("elements") or "").split(","))

    return jsonify(_status_body(who)), 200


@bp.post("/api/visualizer/generate")
def generate():
    try:
        # The COGS line. A session id gets a reader as far as putting a photo
        # up and looking at it; the thing that costs money is reachable only
        # with a token Stripe's webhook produced.
        who = _resolve(allow_pending=False)
    except Denied as exc:
        return _denied(exc)
    cs, purchase, cfg, block = who.token, who.purchase, who.cfg, who.block

    state = read_state(purchase["id"])
    if not state:
        return jsonify({"error": "no_source",
                        "message": "Upload a photo first."}), 409
    if state.get("status") == GENERATING and not _stale(state):
        # Already running. Not an error — the page just polls.
        return jsonify(_status_body(who)), 200

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
        return jsonify(_status_body(who)), 200

    threading.Thread(
        target=run_generation,
        args=(purchase["id"], cfg, block, content),
        daemon=True,
    ).start()

    return jsonify(_status_body(who)), 200


def _stale(state):
    started = state.get("started")
    if not started:
        return True
    return (time.time() - float(started)) > config.VISUALIZER_STALE_S


def _pre_stale(pre):
    """Whether a pre-purchase render has been "working" for too long.

    Shorter than the paid window on purpose. Nobody is watching a paid render
    with their thumb over a pay button; here somebody is, and a spinner that
    never resolves is worse than the blur it replaced.
    """
    try:
        started = float(pre.get("started") or 0)
    except (TypeError, ValueError):
        return True
    if not started:
        return True
    return (time.time() - started) > PRE_RENDER_STALE_S


# Which header names the reader's country, in the order they are trusted.
# Cloudflare sits in front of this app and sets the first; the others are here
# so a move off it does not silently turn a legal control off.
COUNTRY_HEADERS = ("CF-IPCountry", "X-Country-Code", "X-AppEngine-Country")
COUNTRY_RE = re.compile(r"^[A-Z]{2}$")


def reader_country():
    """A two-letter country for this request, or None when it is not known.

    None is a real answer and the callers treat it as one: the consent control
    it feeds defaults to being SHOWN when this returns nothing. A legal control
    that disappears because a header was missing is the failure mode worth
    designing against, so absence never means "not required".

    `XX` and `T1` are what Cloudflare sends for unknown and for Tor, and both
    are exactly the case where nothing should be assumed.
    """
    for name in COUNTRY_HEADERS:
        raw = (request.headers.get(name) or "").strip().upper()
        if COUNTRY_RE.match(raw) and raw not in ("XX", "T1"):
            return raw
    return None


def _status_body(who):
    """What the page polls for. Re-read every time; never cached."""
    limit = max_generations(who.block)
    has_source = os.path.isfile(who.source())
    source_url = "/api/visualizer/image?which=source&" + who.query()

    # A session has no row and needs none. There are exactly two things to
    # know about it — is there a photo, and where can the page draw it — and
    # `paid: false` is what tells the browser to render the teaser rather than
    # the machinery.
    if not who.paid:
        body = {"status": UPLOADED if has_source else NONE,
                "paid": False,
                "generations": 0, "max_generations": limit,
                "remaining": limit, "has_source": has_source}
        if has_source:
            body["source_url"] = source_url

        # Which of the three things the locked panel is: a render being made,
        # a real half-blurred render, or the blur the page has always had.
        # `teaser` is the only key the browser acts on, so a funnel with the
        # flag off, or an engine.js cached from before this, sees exactly what
        # it saw before.
        pre = read_pending(who.session_id) if who.session_id else {}
        state = pre.get("status")
        if state == PRE_READY and os.path.isfile(
                pending_teaser(who.session_id)):
            body["teaser"] = "ready"
            body["teaser_url"] = ("/api/visualizer/image?which=teaser&"
                                  + who.query())
        elif state == PRE_STARTED and not _pre_stale(pre):
            body["teaser"] = "working"
        elif state:
            body["teaser"] = "failed"

        # What the reader's country is, for the one control that depends on it.
        # Read off the edge rather than guessed, and absent rather than wrong
        # when there is no header to read.
        country = reader_country()
        if country:
            body["country"] = country
        return body

    state = read_state(who.purchase_id)
    if not state:
        # A purchase with a photo already on disk and no row is what a webhook
        # that moved the file and then failed to write leaves behind. Reported
        # as `none` so the paid page offers the picker, which rebuilds both.
        return {"status": NONE, "paid": True, "generations": 0,
                "max_generations": limit, "remaining": limit,
                "has_source": has_source}

    status = state.get("status") or UPLOADED
    if status == GENERATING and _stale(state):
        # The worker is gone. Say so rather than spinning forever.
        status = FAILED

    used = int(state.get("generations") or 0)
    attempts = int(state.get("attempts") or 0)
    body = {
        "status": status,
        "paid": True,
        "generations": used,
        "max_generations": limit,
        "remaining": max(0, limit - used),
        "has_source": has_source,
        "source_url": source_url,
    }
    if status == READY and state.get("result_n"):
        # `v` is which render this is, so a regenerate changes the URL and the
        # browser fetches the new picture instead of showing the cached one.
        body["url"] = "/api/visualizer/image?which=result&%s&v=%d" % (
            who.query(), int(state["result_n"]))
    if status == FAILED:
        # Whether the button comes back. A purchase that has run out of
        # attempts is told so once instead of being offered a retry that the
        # server will refuse.
        body["retriable"] = attempts < config.VISUALIZER_MAX_ATTEMPTS
        body["message"] = (who.block.get("error_text") if body["retriable"]
                           else who.block.get("error_final"))
    country = reader_country()
    if country:
        body["country"] = country
    return body


@bp.get("/api/visualizer/status")
def status():
    try:
        who = _resolve(allow_pending=True)
    except Denied as exc:
        return _denied(exc)
    resp = jsonify(_status_body(who))
    resp.headers["Cache-Control"] = "no-store"
    return resp, 200


@bp.get("/api/visualizer/image")
def image():
    """The only way either picture is readable.

    These files are not in static/ and never will be: static/ is served by the
    web server straight off disk with no idea who is asking, and behind a CDN
    that would cache the inside of somebody's house at an edge node. Here the
    credential is checked first and the response is marked private and
    uncacheable — the browser may keep it, nothing in between may.

    Both credentials reach it, because the teaser has to draw the reader their
    own photograph before they have paid for anything. Only a purchase has a
    render to ask for; a session asking for one is asking for a file that does
    not exist, and is told so.
    """
    try:
        who = _resolve(allow_pending=True)
    except Denied as exc:
        return _denied(exc)

    which = request.args.get("which") or "result"
    if which == "source":
        path = who.source()
    elif which == "teaser":
        # The only picture of a render an unpaid reader can reach, and it is a
        # different file from the render: a downscale with half of it blurred
        # into the pixels and a lock drawn on top. There is no parameter here
        # that reaches `pending_result` — the full render has no route at all
        # until a purchase claims it and it becomes `result_1.jpg`.
        if who.paid or not who.session_id:
            return jsonify({"error": "not_ready"}), 404
        path = pending_teaser(who.session_id)
    elif which == "result":
        if not who.paid:
            return jsonify({"error": "not_ready"}), 404
        state = read_state(who.purchase_id) or {}
        if state.get("status") != READY or not state.get("result_n"):
            return jsonify({"error": "not_ready"}), 404
        path = result_path(who.purchase_id, state["result_n"])
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
