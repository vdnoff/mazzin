#!/usr/bin/env python3
"""Draw the love-zodiac-bg funnel's real gallery: 36 cards and 2 interstitials.

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

--- what it draws --------------------------------------------------------------

The plan is the 38 prompts below, one per frame, each closed on the same base
suffix: painterly, dreamy, deep indigo night with warm gold accents, no text,
no watermark, no close-up faces. Thirty-six are the quiz cards, drawn 1:1 at
1024 and brought down to an 800x800 WebP; two are the interstitial frames,
drawn portrait and centre-cropped to 4:5 at 800x1000. The plan is checked
against the config before anything is called: every love-owned image id the
funnel references has a prompt here and every prompt here is an id the funnel
references, or the run refuses — a gallery drawn to last week's config is a
gallery nobody sees.

--- the manifest, and what a rerun does ----------------------------------------

scripts/love_art.json records every frame this script has really drawn: the
hash of the bytes on disk, the hash of the prompt that made them, the cost.
A rerun skips a frame whose file still hashes to what is recorded AND whose
prompt is unchanged, and remakes everything else. So:

    delete the file        -> it is drawn again (the record no longer matches)
    edit its prompt        -> it is drawn again (the recipe no longer matches)
    `--force`              -> everything named is drawn again
    a placeholder on disk  -> drawn, because no record was ever written for it

The placeholders scripts/gen_love_placeholders.py writes are never recorded
here, which is what lets this script paint over them on its first run and
leave the real art alone on every run after.

--- the floor -------------------------------------------------------------------

Not persona's. That floor is tuned for bright art on a warm sweep and would
reject every correct frame here for being what was asked for: a deep indigo
night sits at a mean luma persona calls "came back dark". What this floor
catches is the render that came back as a non-picture — near-black, blown
out, flat, or grey with no gold in it — and passes everything else. The
owner's phone is the real gate. The band is stated as numbers and printed
per frame, so a rejection can be read against the thresholds without
rerunning anything.

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

# --- geometry ------------------------------------------------------------------

FRAME = (800, 800)
FRAME_TALL = (800, 1000)
API_SQUARE = "1024x1024"
API_PORTRAIT = "1024x1536"

MODEL = os.getenv("OPENAI_IMAGE_MODEL", "gpt-image-1")
IMAGE_QUALITY = os.getenv("LOVE_IMAGE_QUALITY", "medium")
TIMEOUT_S = float(os.getenv("OPENAI_TIMEOUT_S", "180"))
API_BASE = os.getenv("OPENAI_API_BASE", "https://api.openai.com/v1")

# Per-image list price in dollars, keyed (quality, api size). Not read from
# the API, stale the day the price list moves, `--price` overrides — the
# number printed is an estimate and the invoice is the truth.
PRICE = {
    ("low", API_SQUARE): 0.011,
    ("medium", API_SQUARE): 0.042,
    ("high", API_SQUARE): 0.167,
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

# The base suffix, on every prompt. One slot: the aspect, because thirty-six
# frames are square and two are not, and telling a portrait render it is
# square is asking for a square picture with black bars.
STYLE_SUFFIX = (", painterly dreamy style, deep indigo night palette with "
                "warm gold accents, soft glow, {aspect}, no text, no "
                "watermark, no close-up faces")
ASPECT_SQUARE = "square 1:1"
ASPECT_TALL = "portrait 4:5"

# --- the plan ------------------------------------------------------------------
#
# The 36 cards, in walk order, and the two interstitial frames. The subject
# text is the brief, verbatim; the suffix above is what makes it one set.

CARD_PROMPTS = [
    ("lv01a", "lightning spark between two reaching hands"),
    ("lv01b", "candle lighting a second candle, slow flame"),
    ("lv02a", "couple silhouettes on a night city square with lights"),
    ("lv02b", "two cups of tea by a rainy window, blanket"),
    ("lv03a", "two hands interlaced fingers golden glow"),
    ("lv03b", "handwritten letter with wax heart seal"),
    ("lv04a", "small star pendant in an open palm"),
    ("lv04b", "key tied with red thread"),
    ("lv05a", "two chairs facing each other, warm lamp between"),
    ("lv05b", "lone bench under stars with room for two"),
    ("lv06a", "two trees with intertwined crowns"),
    ("lv06b", "two birds flying parallel in open sky"),
    ("lv07a", "candlelit table on a rooftop under stars"),
    ("lv07b", "sunrise from a mountain peak, two backpacks"),
    ("lv08a", "dancing silhouettes under a street lamp in rain"),
    ("lv08b", "two coffee cups on the same table every morning, calendar"),
    ("lv09a", "paper plane flying through night sky toward a lit window"),
    ("lv09b", "two shadows at one door, key in lock"),
    ("lv10a", "nest with two golden eggs in branches"),
    ("lv10b", "open door to a lit garden"),
    ("lv11a", "lightning over dark sea"),
    ("lv11b", "embers in a hearth, deep red glow"),
    ("lv12a", "figure leaping toward an outstretched hand over a gap"),
    ("lv12b", "stone bridge over calm river, double railing"),
    ("lv13a", "glass globe with a snowy memory inside"),
    ("lv13b", "blank white page and a quill at dawn"),
    ("lv14a", "couple silhouettes dancing in a lit square"),
    ("lv14b", "two under one blanket on a rooftop, city far below"),
    ("lv15a", "umbrella held over another silhouette in rain"),
    ("lv15b", "kite launched by two hands into the sky"),
    ("lv16a", "two fishermen on a misty pier, silence"),
    ("lv16b", "two glasses of wine and an unfinished conversation, dying candle"),
    ("lv17a", "road through hills toward a horizon with two moons"),
    ("lv17b", "oak with initials carved in bark, gold in the grooves"),
    ("lv18a", "heart-shaped nebula in deep space"),
    ("lv18b", "two hands forming a heart against a full moon"),
]

TALL_PROMPTS = [
    ("int1", "night sky with two falling stars"),
    ("int2", "two candles in darkness, one lighting the other"),
]


def prompt_for(subject, tall=False):
    """The subject, closed on the suffix, with the aspect said correctly."""
    return subject + STYLE_SUFFIX.format(
        aspect=ASPECT_TALL if tall else ASPECT_SQUARE)


def owned_ids(cfg):
    """Every image id the config references under this funnel's gallery.

    The cards off the steps, then the frames `preview_gallery` names on its
    own — which is where the two interstitial frames live, because the
    engine's interstitial screens carry no image slot and the strip under the
    locked report does.
    """
    out = []
    seen = set()
    for step in cfg["swipe"]["steps"]:
        for pair in step["pairs"]:
            for item in pair["images"]:
                if item["img"].startswith(OWNED) and item["id"] not in seen:
                    seen.add(item["id"])
                    out.append(item["id"])
    for item in cfg.get("preview_gallery") or []:
        if item["img"].startswith(OWNED) and item["id"] not in seen:
            seen.add(item["id"])
            out.append(item["id"])
    return out


def frames(cfg):
    """The plan: one frame per prompt, checked against the config.

    A prompt for an id the funnel does not show, or an owned id with no
    prompt, is refused before anything is called. The gallery is the
    funnel's, not this file's.
    """
    plan = [{"id": i, "kind": "card", "prompt": prompt_for(s),
             "size": FRAME, "api_size": API_SQUARE}
            for i, s in CARD_PROMPTS]
    plan += [{"id": i, "kind": "interstitial", "prompt": prompt_for(s, True),
              "size": FRAME_TALL, "api_size": API_PORTRAIT}
             for i, s in TALL_PROMPTS]
    planned = [f["id"] for f in plan]
    if len(set(planned)) != len(planned):
        raise SystemExit("a frame id is planned twice")
    owned = owned_ids(cfg)
    missing = sorted(set(owned) - set(planned))
    extra = sorted(set(planned) - set(owned))
    if missing or extra:
        raise SystemExit("plan and config disagree — no prompt for %s, "
                         "no config image for %s" % (missing, extra))
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
    image. Square in, square out; portrait in, 4:5 out."""
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

# Mean luma below this is a frame that came back black: an indigo night with
# a gold accent in it reads in the 30s to 90s, and a near-black render in the
# single digits.
MIN_MEAN_LUMA = 18.0
# And above this it is a blown-out or blank page, which the palette makes
# nearly impossible and the floor refuses anyway.
MAX_MEAN_LUMA = 200.0
# One flat wash scores fine on luma and is still not a picture.
MIN_STDDEV = 12.0
# Gold on indigo is colour. A greyscale render fails here and nowhere else.
MIN_SATURATION = 25.0

BAND = {"min_luma": MIN_MEAN_LUMA, "max_luma": MAX_MEAN_LUMA,
        "min_sd": MIN_STDDEV, "min_sat": MIN_SATURATION}


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

    Loose on purpose: it rejects near-black, blank, flat and colourless
    renders and passes everything else, because the owner review is the
    real gate. A frame that cannot be measured is kept and says so — it is
    going in front of a human anyway.
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
                 "whose prompt is unchanged; delete the file, or edit the "
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

    The prompt, the geometry and the API size: changing any of them is what
    should make a rerun redraw.
    """
    return "%s|%s|%dx%d" % (frame["prompt"], frame["api_size"],
                            frame["size"][0], frame["size"][1])


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
            print("\n--- %s (%s, %dx%d via %s) ---"
                  % (frame["id"], frame["kind"], frame["size"][0],
                     frame["size"][1], frame["api_size"]))
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
                ok, note = verdict(measure(img))
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
