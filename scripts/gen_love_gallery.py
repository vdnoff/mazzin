#!/usr/bin/env python3
"""Draw the love-zodiac-bg funnel's real gallery: 44 cards and 2 interstitials.

Console use only, run by hand against a key. Nothing imports this, no route
reaches it, and it spends money — one image per frame at the published
gpt-image-1 rate — so it is never run by a deploy or a test:

    pip install pillow
    cd ~/mazzin && python3 scripts/gen_love_gallery.py --dry-run   # prompts only
    cd ~/mazzin && python3 scripts/gen_love_gallery.py             # the draw
    python3 scripts/gen_love_gallery.py --only lv07a,int1 --force  # redraw two

The key is read from ~/mazzin/.env itself — the OPENAI_API_KEY line, read as
a literal the way deploy.sh reads .env, never sourced — and falls back to the
OPENAI_API_KEY environment variable when the file has none. Nothing else in
.env is read.

--- v2: portrait, lighter, four grids ------------------------------------------

The first gallery was drawn square and dark, and the owner's phone review
found both wrong. The engine renders a pair card as a tall column — at
390x844 it measures 174x603, about 2:7 — and a four-up cell at 174x297,
about 3:5. `object-fit: cover` then shows a square picture's middle third
and cuts the subject off both sides. Every frame also sat on a night sky.

So every frame is now rendered portrait (1024x1536, which is 2:3) and kept
at the shape its tile wants: a pair card at 640x960, the whole render, the
way the zodiac gallery's 640x982 frames are; a four-up cell at 360x600, twice
its rendered size, centre-cropped to 3:5; the two interstitial frames at
800x1000, 4:5. Which shape a card takes is read off the config — the step
format the card sits in — so the plan and the funnel cannot disagree.

Every prompt carries composition guidance for its own crop, and the pair
guidance is the honest one: the tile shows the middle 40 percent of the
width, so the subject is asked to sit in a central vertical band, not merely
inside the middle 70 percent of the frame. And the palette moved to light:
dawn, golden hour, airy pastel, with the warm gold accents kept. Four frames
stay dark because their subject is dark — a nebula, falling stars, embers, a
twilight road — and each carries its own luma floor. The recipes are bumped
with a version tag, so the whole manifest is stale and the next run redraws
everything.

--- the manifest, and what a rerun does ----------------------------------------

scripts/love_art.json records every frame this script has really drawn: the
hash of the bytes on disk, the hash of the recipe that made them, the cost.
A rerun skips a frame whose file still hashes to what is recorded AND whose
recipe is unchanged, and remakes everything else. So:

    delete the file        -> it is drawn again (the record no longer matches)
    edit its prompt        -> it is drawn again (the recipe no longer matches)
    `--force`              -> everything named is drawn again
    a placeholder on disk  -> drawn, because no record was ever written for it

The placeholders scripts/gen_love_placeholders.py writes are never recorded
here, which is what lets this script paint over them on its first run and
leave the real art alone on every run after.

--- the floor -------------------------------------------------------------------

The floor catches the render that came back as a non-picture, and now also
the render that came back as the old gloom: the whole first gallery measured
between luma 25 and 62, and the default floor is 80, above every one of
those and under what a dawn or golden-hour scene measures. A frame whose
subject is genuinely dark is judged under its own floor, named per frame
below. The band is printed per frame, so a rejection can be read against the
thresholds without rerunning anything.

A frame is also held under 120KB: the WebP is re-encoded a step at a time
down to a floor quality, and a frame that cannot get under is a failure
rather than a heavy file on a phone.
"""
import argparse
import base64
import binascii
import hashlib
import io
import json
import os
import re
import sys
import time
import urllib.error
import urllib.request

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
CONFIG = os.path.join(ROOT, "funnels", "love-zodiac-bg.json")
OUT = os.path.join(ROOT, "static", "galleries", "love-zodiac-bg")
OWNED = "/static/galleries/love-zodiac-bg/"
MANIFEST = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                        "love_art.json")

# Where the key lives. The repo root is ~/mazzin on the server, and the
# literal path is tried too so a checkout under another name still finds the
# server's own .env when it is run from there.
ENV_FILES = (os.path.join(ROOT, ".env"), os.path.expanduser("~/mazzin/.env"))

# Bumped when every frame has to be drawn again regardless of its prompt —
# a new palette, a new geometry. It is part of every recipe.
RECIPE_VERSION = "v2"

# --- geometry ------------------------------------------------------------------
#
# One render size, three frame shapes, keyed by the kind of tile a frame is
# shown in. Measured on the live shell at 390x844: a pair card is 174x603,
# a four-up cell 174x279 to 174x297, the interstitial strip is free.

API_PORTRAIT = "1024x1536"

# The kind of tile, the committed frame, and the crop guidance it is drawn
# against. A pair card keeps the whole 2:3 render, like the zodiac gallery's
# 640x982 frames; a grid cell is twice its rendered size at 3:5; an
# interstitial frame is 4:5.
KINDS = {
    "pair": {
        "size": (640, 960),
        "crop": "2:3",
        "guidance": ("single central subject, composed for a 2:3 portrait "
                     "frame that is shown as a tall central band, "
                     "comfortable margins on all sides, subject fully inside "
                     "the middle 70% of the frame height and the middle 40% "
                     "of the frame width"),
    },
    "grid": {
        "size": (360, 600),
        "crop": "3:5",
        "guidance": ("single central subject, composed for a 3:5 portrait "
                     "crop, comfortable margins on all sides, subject fully "
                     "inside the middle 70% of the frame"),
    },
    "interstitial": {
        "size": (800, 1000),
        "crop": "4:5",
        "guidance": ("single central subject, composed for a 4:5 portrait "
                     "crop, comfortable margins on all sides, subject fully "
                     "inside the middle 70% of the frame"),
    },
}
# Which step format draws which kind of tile. A format not named here is a
# loud failure at plan time, not a square frame in a portrait tile.
KIND_OF_FORMAT = {"pair": "pair", "grid4": "grid"}

MODEL = os.getenv("OPENAI_IMAGE_MODEL", "gpt-image-1")
IMAGE_QUALITY = os.getenv("LOVE_IMAGE_QUALITY", "medium")
TIMEOUT_S = float(os.getenv("OPENAI_TIMEOUT_S", "180"))
API_BASE = os.getenv("OPENAI_API_BASE", "https://api.openai.com/v1")

# Per-image list price in dollars, keyed (quality, api size). Not read from
# the API, stale the day the price list moves, `--price` overrides — the
# number printed is an estimate and the invoice is the truth.
PRICE = {
    ("low", API_PORTRAIT): 0.016,
    ("medium", API_PORTRAIT): 0.063,
    ("high", API_PORTRAIT): 0.25,
}

# WebP: the quality every frame is first encoded at, the floor it may be
# stepped down to when it is over the byte ceiling, and the ceiling.
QUALITY = 80
QUALITY_FLOOR = 50
MAX_BYTES = 120 * 1024

# --- the style ----------------------------------------------------------------

# The base suffix, on every prompt. One slot: the composition guidance for
# the frame's own crop, because a pair card, a grid cell and an interstitial
# frame are shown at three different shapes.
STYLE_SUFFIX = (", painterly dreamy style, soft luminous palette — dawn sky, "
                "golden hour or airy pastel light — with warm gold accents, "
                "gentle glow, {guidance}, no text, no watermark, no close-up "
                "faces")

# --- the plan ------------------------------------------------------------------
#
# The 44 cards, in walk order, and the two interstitial frames. Most scenes
# happen at dawn, golden hour or in bright soft daylight; the four that stay
# dark are the ones whose subject is dark, and they are named again in
# MIN_LUMA_BY_FRAME.

CARD_PROMPTS = [
    ("lv01a", "spark of golden light leaping between two reaching hands, "
              "bright dawn sky behind"),
    ("lv01b", "one candle lighting a second candle on a sunlit windowsill, "
              "soft morning light"),
    ("lv02a", "couple silhouettes strolling a city square strung with lights "
              "at golden hour"),
    ("lv02b", "two cups of tea by a rain-streaked window, folded blanket, "
              "pale morning light"),
    ("lv03a", "two hands with interlaced fingers in warm golden sunlight"),
    ("lv03b", "handwritten letter with a wax heart seal on a sunlit linen "
              "table"),
    ("lv04a", "small star pendant resting in an open palm, soft daylight"),
    ("lv04b", "brass key tied with red thread on a pale wooden table, morning "
              "light"),
    ("lv05a", "two chairs facing each other by a bright window, warm lamp "
              "between them"),
    ("lv05b", "empty park bench at dawn with room for two, pink and gold sky"),
    ("lv05c", "two silhouettes laughing together at a sunlit kitchen table, "
              "light spilling in"),
    ("lv05d", "two figures walking shoulder to shoulder down a tree-lined "
              "lane in golden hour light"),
    ("lv06a", "two trees with intertwined crowns in a sunlit meadow, airy "
              "pastel sky"),
    ("lv06b", "two birds flying side by side across a bright open sky at "
              "dawn"),
    ("lv07a", "candlelit table on a rooftop at golden hour, the sky glowing "
              "peach and gold"),
    ("lv07b", "sunrise from a mountain peak, two backpacks resting on the "
              "rocks, golden light"),
    ("lv07c", "a folded letter left on a pillow in soft morning light"),
    ("lv07d", "two silhouettes dancing in a bright kitchen in daylight, sun "
              "through the window"),
    ("lv08a", "two silhouettes dancing in a light rain under a street lamp "
              "at golden hour, wet pavement shining"),
    ("lv08b", "two coffee cups on the same table in morning light, a wall "
              "calendar behind"),
    ("lv09a", "paper plane gliding across a pastel dawn sky toward a lit "
              "window"),
    ("lv09b", "two shadows cast on a sunlit door, a key turning in the lock"),
    ("lv10a", "nest with two golden eggs among branches in soft spring "
              "light"),
    ("lv10b", "open door leading out to a bright sunlit garden"),
    ("lv10c", "long table laid for guests in a sunlit garden, golden "
              "afternoon light"),
    ("lv10d", "hammock for two strung between trees in a leafy garden, "
              "dappled sunlight"),
    ("lv11a", "lightning over a stormy sea under a bright dramatic sky, "
              "sunlight breaking through"),
    ("lv11b", "glowing embers in a hearth, warm amber light radiating onto "
              "stone, deep red and gold"),
    ("lv12a", "figure leaping toward an outstretched hand over a gap, bright "
              "sky behind"),
    ("lv12b", "stone bridge with a double railing over a calm river in "
              "morning mist and sunlight"),
    ("lv13a", "glass snow globe with a tiny winter scene inside, on a sunlit "
              "shelf"),
    ("lv13b", "blank white page and a quill on a desk at dawn, soft golden "
              "light"),
    ("lv14a", "couple silhouettes dancing in a sunlit square, bright festive "
              "bunting"),
    ("lv14b", "two under one blanket on a rooftop at golden hour, city far "
              "below in haze"),
    ("lv15a", "umbrella held over another silhouette in a bright spring "
              "rain, sun breaking through"),
    ("lv15b", "kite launched by two hands into a bright open sky"),
    ("lv16a", "two fishermen on a misty pier at sunrise, still water, pale "
              "gold light"),
    ("lv16b", "two glasses of wine and an unfinished conversation on a "
              "terrace at golden hour"),
    ("lv16c", "two figures reading side by side on a sofa in soft afternoon "
              "light"),
    ("lv16d", "two figures in a parked car on a hill watching the sunset, "
              "warm glowing sky"),
    ("lv17a", "road through soft hills toward a horizon with two pale moons "
              "in a twilight sky"),
    ("lv17b", "oak with initials carved into the bark, gold in the grooves, "
              "sunlight through leaves"),
    ("lv18a", "heart-shaped nebula glowing in deep space, warm gold and rose "
              "against the dark"),
    ("lv18b", "two hands forming a heart against a bright full moon in a "
              "pale evening sky"),
]

TALL_PROMPTS = [
    ("int1", "night sky with two falling stars over a faint horizon glow"),
    ("int2", "two candles, one lighting the other, on a table in soft dawn "
             "light"),
]


def prompt_for(subject, kind):
    """The subject, closed on the suffix, with this kind's crop guidance."""
    return subject + STYLE_SUFFIX.format(guidance=KINDS[kind]["guidance"])


def owned_ids(cfg):
    """Every image id the config references under this funnel's gallery,
    with the kind of tile each is shown in.

    The cards off the steps, keyed by the step's format, then the frames
    `preview_gallery` names on its own — which is where the two interstitial
    frames live, because the engine's interstitial screens carry no image
    slot and the strip under the locked report does.
    """
    out = []
    seen = set()
    for step in cfg["swipe"]["steps"]:
        fmt = step.get("format")
        for pair in step["pairs"]:
            for item in pair["images"]:
                if item["img"].startswith(OWNED) and item["id"] not in seen:
                    if fmt not in KIND_OF_FORMAT:
                        raise SystemExit("step %s has format %r, which no "
                                         "frame shape is known for"
                                         % (step.get("id"), fmt))
                    seen.add(item["id"])
                    out.append((item["id"], KIND_OF_FORMAT[fmt]))
    for item in cfg.get("preview_gallery") or []:
        if item["img"].startswith(OWNED) and item["id"] not in seen:
            seen.add(item["id"])
            out.append((item["id"], "interstitial"))
    return out


def frames(cfg):
    """The plan: one frame per prompt, shaped by the config, checked
    against it.

    A prompt for an id the funnel does not show, or an owned id with no
    prompt, is refused before anything is called. The gallery is the
    funnel's, not this file's.
    """
    owned = owned_ids(cfg)
    kind_of = dict(owned)
    subjects = dict(CARD_PROMPTS + TALL_PROMPTS)
    planned = [i for i, _s in CARD_PROMPTS + TALL_PROMPTS]
    if len(set(planned)) != len(planned):
        raise SystemExit("a frame id is planned twice")
    missing = sorted(set(kind_of) - set(planned))
    extra = sorted(set(planned) - set(kind_of))
    if missing or extra:
        raise SystemExit("plan and config disagree — no prompt for %s, "
                         "no config image for %s" % (missing, extra))
    tall = {i for i, _s in TALL_PROMPTS}
    wrong = [i for i, k in owned if (k == "interstitial") != (i in tall)]
    if wrong:
        raise SystemExit("interstitial frames and the preview-only ids "
                         "disagree: %s" % wrong)
    plan = []
    for frame_id, kind in owned:
        plan.append({"id": frame_id, "kind": kind,
                     "prompt": prompt_for(subjects[frame_id], kind),
                     "size": KINDS[kind]["size"], "api_size": API_PORTRAIT,
                     "band": band_for(frame_id)})
    return plan


# --- the key -------------------------------------------------------------------

_ENV_LINE = re.compile(r"^\s*(?:export\s+)?OPENAI_API_KEY=(.*?)\s*$")


def key_from_env_file(paths=None):
    """OPENAI_API_KEY as written in the first .env that carries it, or "".

    `paths` defaults to ENV_FILES at call time, not at definition time, so
    the list can be pointed elsewhere by a test without re-importing.

    Read as a literal line, never sourced: sourcing runs the file as shell,
    which mangles values with `$` in them and puts every other secret in the
    file into this process's environment. Quotes around the value are
    stripped, an inline comment is not — a key does not contain one and a
    password may.
    """
    for path in (ENV_FILES if paths is None else paths):
        try:
            with open(path, encoding="utf-8") as fh:
                lines = fh.read().splitlines()
        except OSError:
            continue
        value = ""
        for line in lines:
            hit = _ENV_LINE.match(line.rstrip("\r"))
            if hit:
                value = hit.group(1)
        if len(value) >= 2 and value[0] == value[-1] and value[0] in "\"'":
            value = value[1:-1]
        if value:
            return value
    return ""


def api_key():
    """The .env key first, the environment second, "" when neither."""
    return key_from_env_file() or os.getenv("OPENAI_API_KEY", "")


# --- the call ------------------------------------------------------------------


class GenerationError(Exception):
    def __init__(self, code, retriable=True):
        Exception.__init__(self, code)
        self.code = code
        self.retriable = retriable


def _post_generation(prompt, api_size, key):
    """One call to images/generations. Returns raw image bytes."""
    body = json.dumps({"model": MODEL, "prompt": prompt, "size": api_size,
                       "quality": IMAGE_QUALITY, "n": 1}).encode("utf-8")
    req = urllib.request.Request(
        API_BASE.rstrip("/") + "/images/generations",
        data=body, method="POST",
        headers={"Authorization": "Bearer " + key,
                 "Content-Type": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=TIMEOUT_S) as res:
            payload = json.loads(res.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        hint = ""
        try:
            detail = json.loads(exc.read().decode("utf-8"))
            hint = str((detail.get("error") or {}).get("code") or "")[:80]
        except Exception:
            pass
        # 429 and 5xx are worth another go; a 400 means the request itself
        # is wrong and will be exactly as wrong the second time.
        raise GenerationError("http_%d %s" % (exc.code, hint),
                              retriable=(exc.code == 429 or exc.code >= 500))
    except Exception as exc:
        raise GenerationError("transport %s" % type(exc).__name__)

    data = (payload or {}).get("data") or []
    encoded = (data[0] or {}).get("b64_json") if data else None
    if not encoded:
        raise GenerationError("empty_response")
    try:
        return base64.b64decode(encoded, validate=True)
    except (binascii.Error, ValueError):
        raise GenerationError("bad_image", retriable=False)


def generate(prompt, api_size, key, tries=3):
    """The draw, with retries on the failures that are worth retrying."""
    last = None
    for attempt in range(tries):
        try:
            return _post_generation(prompt, api_size, key)
        except GenerationError as err:
            last = err
            if not err.retriable:
                raise
            if attempt + 1 < tries:
                time.sleep(2 * (attempt + 1))
    raise last


# --- the frame -----------------------------------------------------------------


def fit(raw, size):
    """The model's image, centre-cropped to the committed frame, as a Pillow
    image. A 2:3 render into a 2:3 frame is a resize; into 3:5 or 4:5 it is
    a resize and a centre crop of the height."""
    from PIL import Image

    img = Image.open(io.BytesIO(raw))
    img.load()
    img = img.convert("RGB")
    want_w, want_h = size
    scale = max(want_w / img.width, want_h / img.height)
    img = img.resize((max(1, int(round(img.width * scale))),
                      max(1, int(round(img.height * scale)))),
                     Image.LANCZOS)
    left = (img.width - want_w) // 2
    top = (img.height - want_h) // 2
    return img.crop((left, top, left + want_w, top + want_h))


def encode(img, ceiling=MAX_BYTES):
    """`(bytes, quality)` for a frame under the ceiling, or `(None, q)`.

    Quality steps down from QUALITY to QUALITY_FLOOR, ten at a time, and the
    first encoding under the ceiling wins. None means the picture cannot be
    made small enough without being made bad, which is a failed frame.
    """
    quality = QUALITY
    while True:
        buf = io.BytesIO()
        img.save(buf, "WEBP", quality=quality, method=6)
        data = buf.getvalue()
        if len(data) <= ceiling:
            return data, quality
        if quality <= QUALITY_FLOOR:
            return None, quality
        quality -= 10


# --- the floor -----------------------------------------------------------------

# Mean luma below this is the old gloom, or a frame that came back black.
# The whole first gallery measured 25 to 62 and every one of those frames is
# what the review rejected; a dawn, golden-hour or pastel scene reads well
# above 100. Eighty is over every old frame and under a warm golden-hour
# render, which is the darkest thing the light palette should produce.
MIN_MEAN_LUMA = 80.0
# And above this it is a blown-out or blank page. Higher than before,
# because an airy pastel frame legitimately sits high.
MAX_MEAN_LUMA = 235.0
# One flat wash scores fine on luma and is still not a picture.
MIN_STDDEV = 12.0
# Gold on pastel is still colour. A greyscale render fails here and nowhere
# else; lower than the indigo floor because a pale palette is less saturated
# by construction.
MIN_SATURATION = 18.0

BAND = {"min_luma": MIN_MEAN_LUMA, "max_luma": MAX_MEAN_LUMA,
        "min_sd": MIN_STDDEV, "min_sat": MIN_SATURATION}

# Frames whose subject is deliberately dark, and the luma floor each is
# judged against instead of MIN_MEAN_LUMA. Everything else in the band is
# shared. Four of forty-six, under the review's cap of six: a nebula in deep
# space, falling stars at night, embers in a hearth, a twilight road under
# two moons. Each number is under what its scene measures and above a
# near-black render, which comes back in the single digits — so the frame
# the floor exists to catch is still caught. A frame named here draws under
# its own number and nothing else moves.
MIN_LUMA_BY_FRAME = {
    "lv11b": 20.0,   # embers: the first gallery measured 15 and 27
    "lv17a": 40.0,   # twilight, not night: the sky still holds light
    "lv18a": 25.0,   # a nebula on black, lit by its own gold and rose
    "int1": 25.0,    # falling stars over a horizon glow
}


def band_for(frame_id):
    """The bounds one frame is judged against: the shared band, or the
    shared band with this frame's own luma floor in it."""
    floor = MIN_LUMA_BY_FRAME.get(frame_id)
    return BAND if floor is None else dict(BAND, min_luma=floor)


def measure(img):
    """`(mean_luma, stddev, mean_saturation)` for a frame, or None."""
    try:
        from PIL import ImageStat
        grey = ImageStat.Stat(img.convert("L"))
        sat = ImageStat.Stat(img.convert("HSV").getchannel("S"))
        return grey.mean[0], grey.stddev[0], sat.mean[0]
    except Exception:
        return None


def verdict(stats, bounds=BAND):
    """`(ok, note)` for a measured frame. Never raises.

    Loose on purpose: it rejects the old gloom, near-black, blank, flat and
    colourless renders and passes everything else, because the owner review
    is the real gate. A frame that cannot be measured is kept and says so —
    it is going in front of a human anyway.
    """
    if stats is None:
        return True, "unmeasured"
    mean, sd, sat = stats
    ok = (bounds["min_luma"] <= mean <= bounds["max_luma"]
          and sd >= bounds["min_sd"] and sat >= bounds["min_sat"])
    return ok, "luma %.1f sd %.1f sat %.1f" % (mean, sd, sat)


def size_ok(img, size):
    """The frame is exactly the committed geometry."""
    return tuple(img.size) == tuple(size)


# --- the manifest --------------------------------------------------------------


def sha(data):
    return hashlib.sha256(data).hexdigest()


def load_manifest():
    if not os.path.exists(MANIFEST):
        return {}
    try:
        with open(MANIFEST, encoding="utf-8") as fh:
            return json.load(fh).get("frames") or {}
    except (ValueError, OSError):
        return {}


def save_manifest(entries):
    payload = {
        "note": ("What gen_love_gallery.py has really drawn. A rerun skips an "
                 "id whose file still hashes to what is recorded here and "
                 "whose recipe is unchanged; delete the file, or edit the "
                 "prompt, to have it drawn again. Placeholders are never "
                 "recorded, so the first run paints over them."),
        "funnel": "love-zodiac-bg",
        "model": MODEL,
        "quality": IMAGE_QUALITY,
        "frames": dict(sorted(entries.items())),
    }
    tmp = MANIFEST + ".tmp"
    with open(tmp, "w", encoding="utf-8") as fh:
        json.dump(payload, fh, indent=2, ensure_ascii=False, sort_keys=True)
        fh.write("\n")
    os.replace(tmp, MANIFEST)


def on_disk_sha(frame_id):
    path = os.path.join(OUT, frame_id + ".webp")
    if not os.path.exists(path):
        return None
    with open(path, "rb") as fh:
        return sha(fh.read())


def recipe(frame):
    """What this frame is made of, as one string, for the manifest digest.

    The version tag, the prompt, the geometry and the API size: changing any
    of them is what should make a rerun redraw. A frame judged under its own
    luma floor carries that number too, and only that frame does.
    """
    out = "%s|%s|%s|%dx%d" % (RECIPE_VERSION, frame["prompt"],
                              frame["api_size"], frame["size"][0],
                              frame["size"][1])
    floor = (frame.get("band") or BAND)["min_luma"]
    if floor != MIN_MEAN_LUMA:
        out += "|min_luma=%g" % floor
    return out


def already_made(frame, entries):
    """True when this id's committed frame is the one the manifest recorded."""
    entry = entries.get(frame["id"])
    if not entry:
        return False
    if entry.get("sha256") != on_disk_sha(frame["id"]):
        return False
    return entry.get("recipe_sha") == sha(recipe(frame).encode("utf-8"))


# --- the run -------------------------------------------------------------------


def write(frame_id, data):
    path = os.path.join(OUT, frame_id + ".webp")
    with open(path, "wb") as fh:
        fh.write(data)
    return path


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--dry-run", action="store_true",
                    help="print the plan and every prompt, call nothing")
    ap.add_argument("--only", default="",
                    help="comma-separated frame ids to draw")
    ap.add_argument("--force", action="store_true",
                    help="redraw even frames the manifest already records")
    ap.add_argument("--price", type=float, default=None,
                    help="override the assumed per-image price in dollars")
    ap.add_argument("--retries", type=int, default=2,
                    help="redraws allowed when a frame fails its floor")
    args = ap.parse_args(argv)

    with open(CONFIG, encoding="utf-8") as fh:
        cfg = json.load(fh)

    plan = frames(cfg)
    known = {f["id"] for f in plan}
    if args.only:
        names = [n.strip() for n in args.only.split(",") if n.strip()]
        unknown = [n for n in names if n not in known]
        if unknown:
            print("unknown frame id(s): %s" % ", ".join(unknown))
            return 2
        plan = [f for f in plan if f["id"] in set(names)]

    entries = load_manifest()
    if not args.force:
        plan = [f for f in plan if not already_made(f, entries)]

    def price_of(frame):
        if args.price is not None:
            return args.price
        return PRICE.get((IMAGE_QUALITY, frame["api_size"]), 0.0)

    estimate = sum(price_of(f) for f in plan)
    print("%s, quality %s — %d frame(s) to draw, ~$%.2f estimated"
          % (MODEL, IMAGE_QUALITY, len(plan), estimate))

    if args.dry_run:
        for frame in plan:
            print("\n--- %s (%s, %dx%d via %s, luma floor %g) ---"
                  % (frame["id"], frame["kind"], frame["size"][0],
                     frame["size"][1], frame["api_size"],
                     frame["band"]["min_luma"]))
            print(frame["prompt"])
        print("\ndry run: nothing called, nothing written")
        return 0

    if not plan:
        print("nothing to draw: every frame is recorded and unchanged")
        return 0

    key = api_key()
    if not key:
        print("no OPENAI_API_KEY in %s and none in the environment — "
              "nothing was called or written." % " or ".join(ENV_FILES))
        return 1

    os.makedirs(OUT, exist_ok=True)
    spent, made, failed = 0.0, 0, []
    for frame in plan:
        frame_id = frame["id"]
        price = price_of(frame)
        data, note, quality = None, "", QUALITY
        try:
            for attempt in range(args.retries + 1):
                raw = generate(frame["prompt"], frame["api_size"], key)
                spent += price
                img = fit(raw, frame["size"])
                if not size_ok(img, frame["size"]):
                    note = "size %dx%d" % img.size
                    print("  %-8s wrong size (%s), redrawing"
                          % (frame_id, note))
                    continue
                ok, note = verdict(measure(img), frame["band"])
                if not ok:
                    print("  %-8s rejected (%s), redrawing"
                          % (frame_id, note))
                    continue
                candidate, quality = encode(img)
                if candidate is None:
                    note += " over %dKB at q%d" % (MAX_BYTES // 1024, quality)
                    print("  %-8s too heavy (%s), redrawing"
                          % (frame_id, note))
                    continue
                data = candidate
                break
        except GenerationError as err:
            failed.append((frame_id, "api: %s" % err.code))
            print("  %-8s FAILED (api: %s)" % (frame_id, err.code))
            continue
        except (RuntimeError, OSError) as err:
            failed.append((frame_id, "%s: %s" % (type(err).__name__, err)))
            print("  %-8s FAILED (%s)" % (frame_id, err))
            continue
        if data is None:
            failed.append((frame_id, note))
            print("  %-8s FAILED after %d draws (%s)"
                  % (frame_id, args.retries + 1, note))
            continue

        write(frame_id, data)
        entries[frame_id] = {
            "sha256": sha(data),
            "recipe_sha": sha(recipe(frame).encode("utf-8")),
            "bytes": len(data),
            "size": "%dx%d" % frame["size"],
            "kind": frame["kind"],
            "webp_quality": quality,
            "cost_usd": round(price, 4),
            "note": note,
        }
        save_manifest(entries)
        made += 1
        print("  %-8s %7d B  q%-3d $%.3f  %s"
              % (frame_id, len(data), quality, price, note))

    print("\n%d frame(s) drawn, ~$%.2f spent, %d failed"
          % (made, spent, len(failed)))
    for frame_id, why in failed:
        print("  FAILED %s: %s" % (frame_id, why))
    print("manifest: %s" % MANIFEST)
    print("gallery : %s" % OUT)
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
