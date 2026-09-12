#!/usr/bin/env python3
"""Draw a vertical's swipe gallery from its spec: stand-ins now, real art later.

Console use only, run by hand. Nothing imports this at request time and no
route reaches it. The images it writes are server-side data rather than
code — static/galleries/<vertical>/ is gitignored for every factory vertical
— so a deploy copies nothing and the funnel renders whatever is on disk:

    cd ~/mazzin && python3 scripts/make_gallery.py blinds --placeholders
    cd ~/mazzin && python3 scripts/make_gallery.py blinds --dry-run
    cd ~/mazzin && python3 scripts/make_gallery.py blinds            # the draw
    cd ~/mazzin && python3 scripts/make_gallery.py blinds --only b1a,b1b --force

The spec is scripts/galleries/<vertical>.json: one entry per image with its
id, filename, tags, alt text and the generation prompt, plus the frame size
the swipe UI wants (640x982, the kitchen gallery's) and the share card.

--placeholders paints every frame as a flat colour taken from the image's
identity tag with the id centred on it, so a funnel can be walked end to end
before a single real image exists. The default mode calls the OpenAI Images
API instead — the key is read from .env as a literal line, the way deploy.sh
and gen_love_gallery.py read it, never sourced — fits the render to the
frame, and writes the same filename, so the funnel config never changes
between the two. Both modes are resumable: a file already on disk is left
alone unless --force, and a real draw overwrites a placeholder because a
placeholder is recorded as one in the sidecar manifest.

Money: one image per frame at the published gpt-image-1 rate. --dry-run
prints the plan and the estimate and calls nothing.
"""
import argparse
import base64
import binascii
import io
import json
import os
import re
import sys
import time
import urllib.error
import urllib.request

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SPECS = os.path.join(ROOT, "scripts", "galleries")
ENV_FILES = (os.path.join(ROOT, ".env"), os.path.expanduser("~/mazzin/.env"))

MODEL = os.getenv("OPENAI_IMAGE_MODEL", "gpt-image-1")
IMAGE_QUALITY = os.getenv("GALLERY_IMAGE_QUALITY", "medium")
TIMEOUT_S = float(os.getenv("OPENAI_TIMEOUT_S", "180"))
API_BASE = os.getenv("OPENAI_API_BASE", "https://api.openai.com/v1")
# The model renders 2:3 portrait; the frame is 640x982, near enough that a
# resize and a slim centre crop is the whole fit.
API_PORTRAIT = "1024x1536"
API_LANDSCAPE = "1536x1024"
# Rough published rate per image, for the estimate only.
COST_PER_IMAGE = {"low": 0.01, "medium": 0.04, "high": 0.17}

QUALITY = 80
QUALITY_FLOOR = 50
MAX_BYTES = 150 * 1024

MANIFEST = "_manifest.json"

# Placeholder ground per identity tag, and a neutral for an image without
# one. Chosen so the five read apart at a glance on a phone.
PLACEHOLDER_GROUND = {
    "minimal": "#D9DCDF",
    "modern": "#E5D3B3",
    "classic": "#5A3A2E",
    "rustic": "#B8935A",
    "industrial": "#3A3C40",
}
NEUTRAL_GROUND = "#9A9A96"
IDENTITY_TAGS = tuple(PLACEHOLDER_GROUND)


def load_spec(vertical, path=None):
    path = path or os.path.join(SPECS, vertical + ".json")
    with open(path, encoding="utf-8") as fh:
        spec = json.load(fh)
    if not isinstance(spec.get("images"), list) or not spec["images"]:
        raise ValueError("%s: no images in spec" % path)
    seen = set()
    for item in spec["images"]:
        for key in ("id", "filename", "tags", "alt", "prompt"):
            if key not in item:
                raise ValueError("%s: image without %s" % (path, key))
        if item["id"] in seen:
            raise ValueError("%s: duplicate id %s" % (path, item["id"]))
        seen.add(item["id"])
    return spec


def out_dir(spec, override=None):
    if override:
        return override
    return os.path.join(ROOT, spec.get("dir") or
                        os.path.join("static", "galleries", spec["vertical"]))


def frame_size(spec):
    size = spec.get("size") or [640, 982]
    return (int(size[0]), int(size[1]))


# --- the key -------------------------------------------------------------------

_ENV_LINE = re.compile(r"^\s*(?:export\s+)?OPENAI_API_KEY=(.*?)\s*$")


def key_from_env_file(paths=None):
    """OPENAI_API_KEY as written in the first .env that carries it, or "".

    Read as a literal line, never sourced: sourcing runs the file as shell
    and puts every other secret in it into this process's environment.
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
    return key_from_env_file() or os.getenv("OPENAI_API_KEY", "")


# --- the call ------------------------------------------------------------------

class GenerationError(Exception):
    def __init__(self, code, retriable=True):
        Exception.__init__(self, code)
        self.code = code
        self.retriable = retriable


def _post_generation(prompt, api_size, key):
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


def generate(prompt, api_size, key, tries=3, post=None):
    """The draw, retried on the failures worth retrying."""
    post = post or _post_generation
    last = None
    for attempt in range(tries):
        try:
            return post(prompt, api_size, key)
        except GenerationError as err:
            last = err
            if not err.retriable:
                raise
            if attempt + 1 < tries:
                time.sleep(2 * (attempt + 1))
    raise last


# --- the frame -----------------------------------------------------------------

def fit(raw, size):
    """The model's image, resized and centre-cropped to the frame."""
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
    """WebP bytes under the ceiling, stepping quality down ten at a time."""
    quality = QUALITY
    while True:
        buf = io.BytesIO()
        img.save(buf, "WEBP", quality=quality, method=6)
        data = buf.getvalue()
        if len(data) <= ceiling or quality <= QUALITY_FLOOR:
            return data
        quality -= 10


def rgb(value):
    value = value.lstrip("#")
    return tuple(int(value[i:i + 2], 16) for i in (0, 2, 4))


def placeholder_ground(tags):
    for tag in tags or ():
        if tag in PLACEHOLDER_GROUND:
            return PLACEHOLDER_GROUND[tag]
    return NEUTRAL_GROUND


def _font(size):
    from PIL import ImageFont
    for path in ("/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
                 "/usr/share/fonts/dejavu/DejaVuSans-Bold.ttf"):
        if os.path.isfile(path):
            try:
                return ImageFont.truetype(path, size)
            except OSError:
                pass
    return ImageFont.load_default()


def placeholder(item, size):
    """A flat frame in the identity tag's colour with the id centred."""
    from PIL import Image, ImageDraw
    ground = rgb(placeholder_ground(item.get("tags")))
    img = Image.new("RGB", size, ground)
    draw = ImageDraw.Draw(img)
    # Ink chosen by the ground's luminance, so the id reads on dark and light.
    luma = 0.299 * ground[0] + 0.587 * ground[1] + 0.114 * ground[2]
    ink = (20, 20, 20) if luma > 128 else (240, 240, 236)
    font = _font(max(24, size[0] // 8))
    text = item["id"]
    box = draw.textbbox((0, 0), text, font=font)
    w, h = box[2] - box[0], box[3] - box[1]
    draw.text(((size[0] - w) / 2 - box[0], (size[1] - h) / 2 - box[1]),
              text, fill=ink, font=font)
    return img


def og_from(source_path, size):
    """The share card: the hero frame, centre-cropped landscape."""
    with open(source_path, "rb") as fh:
        return fit(fh.read(), size)


# --- the manifest --------------------------------------------------------------

def load_manifest(directory):
    try:
        with open(os.path.join(directory, MANIFEST), encoding="utf-8") as fh:
            data = json.load(fh)
        return data if isinstance(data, dict) else {}
    except (OSError, ValueError):
        return {}


def save_manifest(directory, entries):
    with open(os.path.join(directory, MANIFEST), "w", encoding="utf-8") as fh:
        json.dump(entries, fh, indent=2, sort_keys=True)
        fh.write("\n")


# --- the run -------------------------------------------------------------------

def plan(spec, directory, placeholders, force, only=None):
    """[(item, path, reason)] — what would be written and why."""
    manifest = load_manifest(directory)
    wanted = set(only) if only else None
    todo = []
    for item in spec["images"]:
        if wanted is not None and item["id"] not in wanted:
            continue
        path = os.path.join(directory, item["filename"])
        exists = os.path.isfile(path)
        recorded = (manifest.get(item["id"]) or {}).get("kind")
        if force:
            reason = "forced"
        elif not exists:
            reason = "missing"
        elif not placeholders and recorded == "placeholder":
            reason = "placeholder on disk"
        else:
            continue
        todo.append((item, path, reason))
    return todo


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("vertical")
    ap.add_argument("--placeholders", action="store_true",
                    help="paint flat stand-ins instead of calling the API")
    ap.add_argument("--force", action="store_true",
                    help="rewrite frames already on disk")
    ap.add_argument("--only", help="comma-separated image ids")
    ap.add_argument("--dry-run", action="store_true",
                    help="print the plan and write nothing")
    ap.add_argument("--out", help="write here instead of the spec's dir")
    ap.add_argument("--spec", help="read this spec file instead")
    args = ap.parse_args(argv)

    try:
        spec = load_spec(args.vertical, args.spec)
    except (OSError, ValueError) as exc:
        print("cannot read spec for %s: %s" % (args.vertical, exc))
        return 1
    directory = out_dir(spec, args.out)
    size = frame_size(spec)
    only = [s for s in (args.only or "").split(",") if s]
    todo = plan(spec, directory, args.placeholders, args.force, only)

    mode = "placeholders" if args.placeholders else "%s, quality %s" % (
        MODEL, IMAGE_QUALITY)
    cost = "" if args.placeholders else " — ~$%.2f estimated" % (
        len(todo) * COST_PER_IMAGE.get(IMAGE_QUALITY, 0.04))
    print("%s: %d of %d frame(s) to write into %s (%s)%s"
          % (args.vertical, len(todo), len(spec["images"]),
             os.path.relpath(directory, ROOT) if directory.startswith(ROOT)
             else directory, mode, cost))
    for item, path, reason in todo:
        print("  %-8s %-14s %s" % (item["id"], reason, " ".join(item["tags"])))
    if args.dry_run:
        return 0
    if not todo:
        print("nothing to do")
        return 0

    key = ""
    if not args.placeholders:
        key = api_key()
        if not key:
            print("no OPENAI_API_KEY in .env or the environment — nothing "
                  "drawn. Use --placeholders for stand-ins.")
            return 1

    os.makedirs(directory, exist_ok=True)
    manifest = load_manifest(directory)
    failed = 0
    for item, path, _ in todo:
        try:
            if args.placeholders:
                img = placeholder(item, size)
                kind = "placeholder"
            else:
                raw = generate(item["prompt"], API_PORTRAIT, key)
                img = fit(raw, size)
                kind = "generated"
            data = encode(img)
            with open(path, "wb") as fh:
                fh.write(data)
            manifest[item["id"]] = {"kind": kind, "filename": item["filename"],
                                    "bytes": len(data)}
            save_manifest(directory, manifest)
            print("  wrote %-8s %6d bytes  (%s)" % (item["id"], len(data), kind))
        except GenerationError as err:
            failed += 1
            print("  FAILED %-8s %s" % (item["id"], err.code))

    og = spec.get("og")
    if og and (args.force or not os.path.isfile(
            os.path.join(directory, og["filename"]))):
        source = os.path.join(directory, (
            [i for i in spec["images"] if i["id"] == og.get("from")]
            or spec["images"])[0]["filename"])
        if os.path.isfile(source):
            og_size = tuple(int(v) for v in (og.get("size") or [1200, 630]))
            card = og_from(source, og_size)
            data = encode(card, ceiling=MAX_BYTES * 2)
            with open(os.path.join(directory, og["filename"]), "wb") as fh:
                fh.write(data)
            print("  wrote %-8s %6d bytes  (share card)" % (og["filename"],
                                                          len(data)))
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
