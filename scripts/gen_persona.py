#!/usr/bin/env python3
"""Generate the persona funnel's real gallery art.

Console use only, run by hand against a key. Nothing imports this and no route
reaches it. Its outputs are committed, so a deploy never builds anything and
the site never depends on Pillow or on an API key being present:

    pip install pillow
    cd ~/mazzin && OPENAI_API_KEY=sk-... python3 scripts/gen_persona.py

    python3 scripts/gen_persona.py --dry-run        # prompts + plan, no calls
    python3 scripts/gen_persona.py --only pk1a,og   # redraw named frames
    python3 scripts/gen_persona.py --force          # ignore the manifest

funnels/persona.json is the source of truth for what exists. Every id, label,
step question and colour comes off the config, so a step redesign changes the
art by changing the config and rerunning — there is no second list of frames
to keep in step, which is the whole reason the placeholder generator is built
the same way.

--- what makes a rerun safe -------------------------------------------------

The placeholder generator skips an id whose file is on disk. That rule cannot
work here: every id already has a file, because every id has a placeholder, and
"skip what exists" would generate nothing on the first run and nothing ever
after. So the record of what has really been drawn lives in a manifest beside
this script rather than being inferred from the directory.

The manifest is committed with the art. It carries, per id, the sha256 of the
bytes on disk, the prompt digest, the size and what the frame cost. A rerun
skips an id whose file still hashes to what the manifest recorded — so a rerun
after a crash resumes rather than restarting, and a rerun after somebody edits
a frame by hand leaves that edit alone rather than silently painting over it.
`--force` overrides. `--only` names ids.

Deliberately not a size heuristic. "Regenerate anything under eight kilobytes"
would work today, on the placeholders this replaces, and would quietly start
redrawing real frames the day one of them compressed well.

--- the exposure floor, carried over ----------------------------------------

The zodiac rule was: a render that comes back too dark to read is not a frame
you can ship, and the check belongs after the render rather than in front of
it, because asking a model for "bright" does not reliably produce it.

That rule carries. What does NOT carry is visualizer.py's correction, and the
difference matters enough to write down. That code lifts a render's mean luma
to 118 because it is matching photographs of somebody's kitchen. Persona's
identity is a deep ink-navy ground on every single frame: lifting these to 118
would wash the ink to slate and throw the identity away on all seventy-odd.

So the floor here measures legibility instead of brightness. An ink frame is
correct; an ink frame with nothing readable in it is not. `legibility` asks
whether enough of the frame carries the teal-and-sand light that is supposed
to be doing the work, and whether the frame has real dynamic range rather than
being one flat wash. A frame that fails is regenerated, not corrected — these
are illustrations drawn to a brief, and the honest fix for a bad one is
another draw.
"""
import argparse
import base64
import binascii
import hashlib
import io
import json
import os
import sys
import time
import urllib.error
import urllib.request

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
CONFIG = os.path.join(ROOT, "funnels", "persona.json")
OUT = os.path.join(ROOT, "static", "galleries", "persona")
OWNED = "/static/galleries/persona/"
MANIFEST = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                        "persona_art.json")

# The committed frame geometry, unchanged from the placeholders these replace:
# the config, the CSS and the contact sheet on the result page all assume it.
FRAME = (600, 800)
OG = (1200, 630)
QUALITY = 80

# What the model is asked for, and what it costs. Portrait 2:3 is the closest
# shape the model offers to the 3:4 the funnel wants, so a little is cropped
# off the top and bottom rather than the sides — these are centre-weighted
# compositions and the sides are where the negative space lives.
API_PORTRAIT = "1024x1536"
API_LANDSCAPE = "1536x1024"
MODEL = os.getenv("OPENAI_IMAGE_MODEL", "gpt-image-1")
IMAGE_QUALITY = os.getenv("PERSONA_IMAGE_QUALITY", "medium")
TIMEOUT_S = float(os.getenv("OPENAI_TIMEOUT_S", "180"))
API_BASE = os.getenv("OPENAI_API_BASE", "https://api.openai.com/v1")

# Per-image list price, keyed (quality, api size). These are the published
# rates this script assumes so the log can total a run; they are not read from
# the API and they go stale the day the price list moves. `--price` overrides,
# and the number printed is an estimate either way — the invoice is the truth.
PRICE = {
    ("low", API_PORTRAIT): 0.016, ("low", API_LANDSCAPE): 0.016,
    ("medium", API_PORTRAIT): 0.063, ("medium", API_LANDSCAPE): 0.063,
    ("high", API_PORTRAIT): 0.25, ("high", API_LANDSCAPE): 0.25,
}

# --- the identity -----------------------------------------------------------
#
# One prefix on every frame, so seventy-four pictures drawn one at a time read
# as one set. The palette is stated in words and in hex: the words are what the
# model actually steers on, the hex is what keeps a human reviewer honest about
# whether it landed.
#
# The negatives are the half that matters. Faces make a quiz about the reader
# into a quiz about a stranger; text and UI make a photograph of a screen; and
# the mystical iconography is the other funnel's entire visual language, which
# is exactly what a model reaches for when asked for "a symbolic illustration
# about identity" and exactly what this funnel must not look like.

STYLE = (
    "Calm-minimal symbolic illustration. Flat and semi-flat geometry with "
    "soft gradients, generous negative space, one dominant subject centred in "
    "frame. "
    "Locked palette: a deep ink-navy ground (#101820 family) fills the whole "
    "frame; electric teal (#4EDDC4 family) is the light — glows, thin light "
    "threads, edge accents; warm muted sand (#D9B98C family) is the single "
    "secondary warm accent, used sparingly so the frame is never clinical. "
    "Consistent soft even lighting across the whole set. "
    "The subject reads clearly against the dark ground: strong figure-ground "
    "contrast carried by the teal and the sand, no fine detail carrying the "
    "meaning, legible at thumbnail size on a phone."
)

NEGATIVE = (
    "Absolutely no human faces and no facial features of any kind; human "
    "figures only ever as clean flat silhouettes. "
    "No text, no letters, no numbers, no words, no logos, no watermarks, no "
    "user-interface elements, no buttons, no charts. "
    "No mystical or astrological iconography whatsoever: no stars, no "
    "constellations, no zodiac signs, no tarot, no crystals, no moons, no "
    "planets, no runes, no eyes-in-triangles. "
    "No photorealism, no 3D render, no busy texture, no clutter."
)


def rgb_words(colors):
    """The frame's own three colours, as the prompt should say them."""
    return ", ".join("%s (%s) in the %s" % (c["name"], c["hex"], c["element"])
                     for c in colors)


# --- what each kind of frame is a picture of ---------------------------------
#
# Four families, because four things are being drawn. The animals are a matched
# set and have to be built the same way twelve times over or the grid reads as
# twelve borrowed pictures. The moodboards are the one family with no subject
# at all. The share card is its own thing. Everything else is a moment.

ANIMAL_SET = (
    "A stylised geometric animal mark of %s %s, seen in full profile, "
    "centred, "
    "filling the same share of the frame as every other animal in this set. "
    "Built from clean geometric planes and a few long confident curves — the "
    "same construction language and the same stroke weight throughout, so "
    "twelve of these side by side read as one designed system rather than as "
    "twelve illustrations. A single teal light thread traces one defining "
    "line of the animal. Not naturalistic wildlife art, not a mascot, not a "
    "logo lockup."
)

MOODBOARD = (
    "A pure abstract colour-field composition — no objects, no subject, no "
    "horizon. Three or four soft bands and blocks of colour meeting with soft "
    "gradient edges, in the exact proportions of a designer's moodboard "
    "swatch. The mood of the composition is '%s'."
)

OG_SCENE = (
    "A centred human head shown in clean profile as a single continuous thin "
    "teal outline against the deep ink-navy ground — the head empty inside, "
    "no face, no features, no eye, no mouth. Inside the skull a small sparse "
    "arrangement of four teal points joined by thin straight lines, evenly "
    "spaced like the corners of a simple technical diagram. "
    "Wide empty margins on both sides. A single soft warm sand glow low "
    "behind the head."
)


def article(word):
    """"a" or "an" for a word the config supplies. Owl and Otter are why."""
    return "an" if word[:1].lower() in "aeiou" else "a"


def scene_for(step_id, question, label, colors):
    """The one sentence that says what this particular frame shows."""
    if step_id == "animal":
        return ANIMAL_SET % (article(label), label.lower())
    if step_id == "palette":
        return MOODBOARD % label
    # Everything else is a behavioural moment. The step's own question is what
    # makes the picture specific — "Road trip" alone is a postcard, "Road trip"
    # as an answer to what a free Saturday is for is a moment — so the question
    # goes in beside the label rather than the label going in alone.
    return (
        "A symbolic, quiet illustration of this moment: \"%s\" — the answer "
        "being '%s'. Show the moment itself through its objects, its light "
        "and its space. Where a person is implied, show them only as a clean "
        "flat "
        "silhouette, small in the frame and never facing the viewer."
        % (question.rstrip(":?… "), label)
    )


def prompt_for(step_id, question, label, colors):
    return "\n".join([
        STYLE,
        scene_for(step_id, question, label, colors),
        "Within the locked palette, lean this frame's colour toward: %s."
        % rgb_words(colors),
        NEGATIVE,
    ])


OG_COLORS = [
    {"name": "Bright Teal", "hex": "#4EDDC4", "element": "outline"},
    {"name": "Warm Sand", "hex": "#D9B98C", "element": "low glow"},
    {"name": "Ink Navy", "hex": "#101820", "element": "ground"},
]


def og_prompt():
    return "\n".join([
        STYLE, OG_SCENE,
        "Within the locked palette, lean this frame's colour toward: %s."
        % rgb_words(OG_COLORS),
        NEGATIVE,
    ])


# --- the work list ----------------------------------------------------------


def frames(cfg):
    """Every persona-owned frame the config references, in walk order.

    A frame pointing anywhere but this gallery belongs to another funnel and
    is dropped here rather than skipped later, so the count this prints is the
    count it owns — the same rule the placeholder generator applies.
    """
    seen, out = set(), []
    for step in cfg["swipe"]["steps"]:
        for pair in step["pairs"]:
            for item in pair["images"]:
                if item["id"] in seen or not item["img"].startswith(OWNED):
                    continue
                seen.add(item["id"])
                out.append({
                    "id": item["id"],
                    "size": FRAME,
                    "api_size": API_PORTRAIT,
                    "prompt": prompt_for(step["id"], step.get("question", ""),
                                         item["label"], item["colors"]),
                })
    out.append({"id": "og", "size": OG, "api_size": API_LANDSCAPE,
                "prompt": og_prompt()})
    return out


# --- the call ---------------------------------------------------------------


class GenerationError(Exception):
    def __init__(self, code, retriable=True):
        Exception.__init__(self, code)
        self.code = code
        self.retriable = retriable


def _post_generation(prompt, api_size, key):
    """One call to images/generations. Returns raw image bytes.

    Raw urllib rather than a client library, for the same reason visualizer.py
    gives: this is a single documented POST, and a dependency somebody has to
    install by hand before the script runs is a worse trade than thirty lines.
    """
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
        # 429 and 5xx are worth another go; a 400 means the request itself is
        # wrong and will be exactly as wrong the second time.
        raise GenerationError(
            "http_%d %s" % (exc.code, hint),
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


# --- the exposure floor, as legibility --------------------------------------

# Below this share of lit pixels the frame has come back as an ink rectangle
# with something almost invisible in it. Measured against what the identity
# asks for: a dominant subject picked out in teal and sand on a dark ground
# puts a few per cent of the frame well above the ground.
MIN_LIT = 0.02

# And above this it is not an ink frame at all — the model has drawn a bright
# picture and dropped the identity. Both ends are failures and both are
# regenerated rather than corrected.
MAX_MEAN_LUMA = 150.0

# One flat wash scores fine on both of the above and is still not a picture.
MIN_STDDEV = 12.0


def legibility(img):
    """`(ok, note)` for a finished frame. Never raises.

    A frame is legible when it is grounded in ink, carries enough lit pixels
    for the subject to read, and has real dynamic range rather than being one
    even wash.
    """
    try:
        from PIL import ImageStat
        grey = img.convert("L")
        stat = ImageStat.Stat(grey)
        mean, sd = stat.mean[0], stat.stddev[0]
        hist = grey.histogram()
        total = float(sum(hist)) or 1.0
        lit = sum(hist[140:]) / total
        ok = (lit >= MIN_LIT and mean <= MAX_MEAN_LUMA and sd >= MIN_STDDEV)
        return ok, "luma %.1f sd %.1f lit %.1f%%" % (mean, sd, lit * 100)
    except Exception as exc:
        # A frame is never lost to the checker. If it cannot be measured it is
        # accepted and the note says so, and a human reviews the sheet anyway.
        return True, "unmeasured (%s)" % type(exc).__name__


def to_webp(raw, size):
    """The model's image, cropped to the committed frame and encoded."""
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
    img = img.crop((left, top, left + want_w, top + want_h))

    buf = io.BytesIO()
    img.save(buf, "WEBP", quality=QUALITY, method=6)
    return buf.getvalue(), img


# --- the manifest -----------------------------------------------------------


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
        "note": ("What gen_persona.py has really drawn. A rerun skips an "
                 "id whose file still hashes to what is recorded here, so a "
                 "hand-edited frame is left alone, not painted over."),
        "model": MODEL,
        "quality": IMAGE_QUALITY,
        "frames": dict(sorted(entries.items())),
    }
    tmp = MANIFEST + ".tmp"
    with open(tmp, "w", encoding="utf-8") as fh:
        json.dump(payload, fh, indent=2, sort_keys=True)
        fh.write("\n")
    os.replace(tmp, MANIFEST)


def on_disk_sha(image_id):
    path = os.path.join(OUT, image_id + ".webp")
    if not os.path.exists(path):
        return None
    with open(path, "rb") as fh:
        return sha(fh.read())


def already_drawn(image_id, prompt, entries):
    """True when this id's committed frame is the one the manifest recorded."""
    entry = entries.get(image_id)
    if not entry:
        return False
    if entry.get("sha256") != on_disk_sha(image_id):
        return False
    return entry.get("prompt_sha") == sha(prompt.encode("utf-8"))


# --- the run ----------------------------------------------------------------


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--dry-run", action="store_true",
                    help="print the plan and every prompt, call nothing")
    ap.add_argument("--only", default="",
                    help="comma-separated frame ids to draw (og included)")
    ap.add_argument("--force", action="store_true",
                    help="redraw even frames the manifest already records")
    ap.add_argument("--price", type=float, default=None,
                    help="override the assumed per-image price in dollars")
    ap.add_argument("--retries", type=int, default=2,
                    help="redraws allowed when a frame fails the floor")
    args = ap.parse_args(argv)

    with open(CONFIG, encoding="utf-8") as fh:
        cfg = json.load(fh)

    plan = frames(cfg)
    wanted = set(f["id"] for f in plan)
    if args.only:
        names = [n.strip() for n in args.only.split(",") if n.strip()]
        unknown = [n for n in names if n not in wanted]
        if unknown:
            print("unknown frame id(s): %s" % ", ".join(unknown))
            return 2
        plan = [f for f in plan if f["id"] in set(names)]

    entries = load_manifest()
    if not args.force:
        plan = [f for f in plan
                if not already_drawn(f["id"], f["prompt"], entries)]

    price = args.price
    if price is None:
        price = PRICE.get((IMAGE_QUALITY, API_PORTRAIT), 0.0)

    print("%s, quality %s, %d frame(s) to draw, ~$%.2f estimated"
          % (MODEL, IMAGE_QUALITY, len(plan), len(plan) * price))

    if args.dry_run:
        for frame in plan:
            print("\n--- %s (%dx%d via %s) ---"
                  % (frame["id"], frame["size"][0], frame["size"][1],
                     frame["api_size"]))
            print(frame["prompt"])
        print("\ndry run: nothing called, nothing written")
        return 0

    key = os.getenv("OPENAI_API_KEY", "")
    if not key:
        print("OPENAI_API_KEY is not set — nothing was called or written.")
        print("Run:  OPENAI_API_KEY=sk-... python3 scripts/gen_persona.py")
        return 1

    os.makedirs(OUT, exist_ok=True)
    spent, drawn, failed = 0.0, 0, []
    for frame in plan:
        image_id = frame["id"]
        note = ""
        for attempt in range(args.retries + 1):
            try:
                raw = generate(frame["prompt"], frame["api_size"], key)
            except GenerationError as err:
                note = "api: %s" % err.code
                break
            spent += price
            data, img = to_webp(raw, frame["size"])
            ok, note = legibility(img)
            if ok:
                path = os.path.join(OUT, image_id + ".webp")
                with open(path, "wb") as fh:
                    fh.write(data)
                entries[image_id] = {
                    "sha256": sha(data),
                    "prompt_sha": sha(frame["prompt"].encode("utf-8")),
                    "bytes": len(data),
                    "size": "%dx%d" % frame["size"],
                    "cost_usd": round(price, 4),
                    "attempts": attempt + 1,
                    "note": note,
                }
                save_manifest(entries)
                drawn += 1
                print("  %-16s %6d B  $%.3f  %s" % (image_id, len(data),
                                                    price, note))
                break
            print("  %-16s rejected (%s), redrawing" % (image_id, note))
        else:
            failed.append((image_id, note))
            print("  %-16s FAILED after %d draws (%s)"
                  % (image_id, args.retries + 1, note))
            continue
        if note.startswith("api: "):
            failed.append((image_id, note))
            print("  %-16s FAILED (%s)" % (image_id, note))

    print("\n%d frame(s) drawn, ~$%.2f spent, %d failed"
          % (drawn, spent, len(failed)))
    for image_id, why in failed:
        print("  FAILED %s: %s" % (image_id, why))
    print("manifest: %s" % MANIFEST)
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
