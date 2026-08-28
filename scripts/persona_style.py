#!/usr/bin/env python3
"""The persona v3 art style, and the machinery that draws it.

Imported by both generators and run by neither:

    scripts/gen_persona_v3_samples.py   the sampler — candidate styles,
                                        review batches, one-off frames
    scripts/gen_persona.py              the production gallery

--- why this file exists ----------------------------------------------------

The style was settled over ten draws and three rejections, and every one of
those rounds changed a paragraph of prompt text. While the sampler was the
only thing that drew anything that was fine. The moment a second generator
needed the same paragraphs, copy-pasting them would have meant the next
round of that argument landing in one file and not the other — and the way
that failure shows up is a production gallery drawn to last month's brief,
which nothing would catch, because both files would still be internally
consistent and both suites would still pass.

So the text lives here once. The sampler and the production generator import
the same strings, and a change to the brief reaches both or neither.

What is NOT here is anything either script owns alone: the sampler's own
candidate styles (vector, clay) and its idiom set, and the production
generator's frame plan, which it reads off the funnel config. This module is
the style and the mechanics, and it has no opinion about what is being drawn.

--- the floors --------------------------------------------------------------

Two bands, keyed by what a frame is FOR rather than by which script drew it.

A quiz card is a subject on a light warm sweep, and the band catches the
render that came back dark, blank or colourless. A totem is the same subject
on the same sweep — that was settled the hard way, after six draws under two
different requests for a dark backdrop all came back as a glow floating in
blackness — so it shares the exposure band exactly. What it adds is a
ceiling on colour, because the way a totem fails is the teal drowning the
clay, and saturation runs high both when the teal goes neon and when a frame
goes near-black.

The ceiling holds at any amount of glow, which is the property that matters
and the one that is easy to talk yourself out of. More teal does raise a
frame's saturation — it displaces the pale sweep, the least saturated thing
in the picture — but only ever toward teal's own reading of 165. A frame
made entirely of glow measures 165 and the ceiling is 235, so no amount of
light can breach it. Both suites assert that on rendered frames, because
"more glow must mean more saturation, so raise the ceiling" is the plausible
wrong conclusion and acting on it would disarm the one bound still catching
neon.
"""
import base64
import binascii
import io
import json
import os
import time
import urllib.error
import urllib.request


# --- geometry and the call ---------------------------------------------------

FRAME = (600, 800)

QUALITY = 80

API_PORTRAIT = "1024x1536"

MODEL = os.getenv("OPENAI_IMAGE_MODEL", "gpt-image-1")

IMAGE_QUALITY = os.getenv("PERSONA_IMAGE_QUALITY", "medium")

TIMEOUT_S = float(os.getenv("OPENAI_TIMEOUT_S", "180"))

API_BASE = os.getenv("OPENAI_API_BASE", "https://api.openai.com/v1")

PRICE = {
    ("low", API_PORTRAIT): 0.016,
    ("medium", API_PORTRAIT): 0.063,
    ("high", API_PORTRAIT): 0.25,
}

# --- the style, in the words both generators send ----------------------------
#
# Everything below is prompt text and nothing below is code. It is the whole
# of what ten draws settled, and it is imported rather than copied so that the
# eleventh round changes it in one place.

SAFE_AREA = (
    "Composition for a vertical card, with a generous safe area. The image "
    "will be centre-cropped and then cropped again by the interface, so the "
    "entire subject must sit well inside the central safe area of the frame. "
    "Keep nothing important in the outer 15 percent on any side — not the "
    "top, not the bottom, not the left, not the right. The subject is whole "
    "and complete and is never touched, clipped or cut off by the frame "
    "edge, and a wide calm margin of plain background runs all the way "
    "around it."
)

SCULPT_STYLE = (
    "Premium 3D clay sculpture still-life render. A single abstract "
    "sculptural composition, photographed as a product still-life. "
    # 2 — handmade authenticity. First in the prefix because it is the note
    # the v1 renders missed hardest: they came back machine-smooth, and a
    # perfectly even volume reads as a 3D asset rather than as clay.
    "Freshly hand-sculpted matte clay and plasticine, and it must visibly "
    "look it: soft finger impressions and press marks pushed into the "
    "surface, gentle pinch ridges along the edges, slightly uneven planes "
    "and imperfect edges, and a faint asymmetry to every volume that no "
    "machine would leave. Unglazed, visibly a little rough. Never "
    "machine-smooth, never CAD-perfect, never glossy, never a polished "
    "product render — the surface should read as clay worked by touch "
    "moments ago. "
    # 1 — the pose verb. Stated as a requirement with a named failure mode,
    # because "abstract sculptural form" on its own reliably returns a
    # symmetrical object sitting still, which is what made all eight v1
    # frames read the same.
    "Every composition shows its form DOING something: one clear physical "
    "gesture — launching, slumping, leaning, huddling, wilting, reaching — "
    "readable in the silhouette alone at phone-tile size. Asymmetry and "
    "implied motion are required. A static, balanced, evenly rounded "
    "still-life is a failure of this brief, unless the composition's "
    "meaning is itself stillness. "
    # 3 — tension vocabulary, as a rule rather than a blanket. The scenes
    # decide; the prefix only says the two registers exist.
    "Form language follows feeling: soft, rounded, swelling volumes where "
    "the composition is warm or calm; angular, pinched, wedged, cracked or "
    "jagged elements where it is strained or under pressure. Matte clay "
    "throughout, either way. "
    # 4 — contrast, so the form separates at tile size, and intrigue, so it
    # is worth stopping on.
    "Studio product lighting from one direction: a subtle rim light picking "
    "out the contour, and a defined soft contact shadow anchoring the form "
    "to the ground beneath it, so the sculpture separates cleanly from its "
    "background at thumbnail size. The backdrop is a plain seamless warm "
    "monochrome studio sweep, two steps deeper and less saturated than the "
    "sculpture tones themselves — never a clinical pure white, never a "
    "shadowed or low-key ground — with generous negative space around the "
    "form. "
    "One to three warm sculpture tones per composition — terracotta, ochre, "
    "sand, warm grey — with electric teal (#4EDDC4) as an accent material "
    "on exactly one element of the form, the thread that runs through the "
    "set. "
    # The two rules the idiom review added. Both are about where meaning is
    # allowed to live: in the material, never in the decoration.
    "State-bearing colour: the tone itself carries the state — a drained "
    "form is drained in its colour as well as its shape, a charged one is "
    "warm and lit. Never a pleasant palette laid over an unrelated form. "
    "Teal at the meaning point: the electric teal marks the one place where "
    "the state is happening — the point of contact, the opening, the seam, "
    "the core — and never sits anywhere as decoration. "
    "Pure form only: the meaning is carried by shape, volume, weight and "
    "gesture, never by depicting anything. Each composition is an enigmatic "
    "object — evocative, open to interpretation, a shape that makes the "
    "viewer pause and read themselves into it. Vary the silhouettes "
    "strongly from one composition to the next, so no two read alike."
)

SCULPT_NEGATIVE = (
    "Absolutely no human figures, no people, no bodies, no busts, no "
    "mannequins, no hands, no faces of any kind, no eyes, no facial "
    "features, no characters, no creatures, no animals. "
    "No scenes, no environments, no landscapes with places in them, no "
    "rooms, no interiors, no furniture, no buildings, no vehicles, no "
    "recognisable everyday props. "
    "No text, no letters, no numbers, no words, no logos, no watermarks, no "
    "user-interface elements. "
    "No photorealism of real materials, no glass, no chrome, no polished "
    "metal, no wet or glossy surfaces, no busy texture, no clutter. "
    "Never a night setting, never a black or midnight-blue background, never "
    "a dim, murky, drab or low-key palette."
)

SCULPT_HEAD_NEGATIVE = (
    "Absolutely no eyes, no eyeball, no iris, no pupil, no mouth, no lips, "
    "no teeth, no ear, no nostril, no eyebrow, no hair of any kind, no "
    "expression, no realistic or detailed face, no photographic likeness, "
    "no recognisable person. The profile is a plain sculptural edge and "
    "nothing more. "
    "Nothing below the neck: no shoulders, no body, no arms, no hands, and "
    "no second form anywhere in the frame. "
    "No scenes, no environments, no rooms, no interiors, no furniture. "
    "No text, no letters, no numbers, no words, no logos, no watermarks. "
    "No photorealism of real materials, no glass, no chrome, no polished "
    "metal, no wet or glossy surfaces, no busy texture, no clutter. "
    "Never a night setting, never a black or midnight-blue background, "
    "never a dim, murky, drab or low-key palette."
)

# The one frame in this style allowed to be a head. The result page inlays the
# reader's radar on a clay cranium, so that frame has to be one — which the
# sculpt negatives otherwise refuse outright, correctly, because every other
# frame asking for one would be the failure this style exists to avoid.
# Keyed by the caller's own id for that frame.

TOTEM_STYLE = (
    "This frame is a totem: the culmination piece, not a quiz card. It is "
    "shot on exactly the same light warm backdrop as every other frame in "
    "this set — the same plain seamless warm monochrome studio sweep, the "
    "same bright even light. Nothing about this frame is dark. "
    # 1 — light. Draw seven passed the floors and the owner's verdict was
    # "not inspiring enough to share": the glow was a detail on a tidy
    # object. So the glow becomes the event. Whole form rather than the tip,
    # which is the specific thing that came back too small to carry a frame.
    # The base prefix restricts teal to "exactly one element of the form",
    # which is right for a quiz card and is very likely why draw seven's glow
    # came back as a lit tip: the block was asking for more light while the
    # prefix above it was asking for one spot of it. The override has to be
    # explicit, because the two are read in the same breath.
    "OVERRIDING THE ONE-ELEMENT TEAL RULE ABOVE: that rule is for quiz "
    "cards. On a totem the teal is not one accent on one element — it runs "
    "throughout the piece as light. "
    "INNER LIGHT IS THE EVENT, NOT A DETAIL: a molten electric teal core "
    "burns inside the form and its light is the subject of the picture. "
    "Luminous veins and fine fissures wind across the whole form from base "
    "to tip — not one lit point, not only the tip — and light spills out of "
    "every one of them. A strong soft bloom washes the clay around each "
    "vein, the glow gathers and brightens where veins run close together, "
    "and a subtle teal reflection lies on the sweep where the form meets "
    "it. The whole piece reads as a lantern lit from within. The light "
    "still comes from inside the volume rather than falling on it: emitted "
    "light, never a teal-painted surface and never a teal object sitting "
    "next to the form. Warm terracotta and ochre clay against that glow, "
    "still fully readable as clay. "
    # 2 — complexity. The totem has to look expensive beside a quiz card,
    # and the quiz cards are deliberately plain, so the difference is the
    # frame's whole argument for existing.
    "SCULPTURAL COMPLEXITY, FAR BEYOND A QUIZ CARD: layered twisting "
    "volumes that turn over and past one another, carved undercuts, flowing "
    "ridges and folds, and deliberate fine detail across the whole surface "
    "— a master sculptor's centrepiece beside the plain single forms of the "
    "quiz cards. That difference should be obvious at a glance and it is "
    "the point of the frame. Intricate but never busy: every ridge, fold "
    "and undercut is a deliberate carved decision, never noise, never "
    "scattered clutter, never surface fuzz. The silhouette stays governed "
    "by the pose-verb rule — dynamic, asymmetric, caught mid-gesture, and "
    "readable as one shape at phone-tile size — while the surface inside it "
    "is rich. "
    # 3 — magic. Granted to totems and to nothing else, and fenced, because
    # this is the direction that turns kitsch fastest.
    "A LITTLE MAGIC, FOR TOTEMS ONLY: a few tiny soft glowing teal "
    "particles drift upward from the fissures, and a faint luminous haze "
    "hangs close around the brightest part of the glow. Restrained and "
    "premium — a handful of embers rising off a lit object, nothing more. "
    "No lightning, no bolts, no sparkles scattered across the frame, no "
    "magic effects, no fantasy kitsch. The matte clay and its handmade "
    "finger marks still read clearly underneath all of it. "
    # 4 — presentation, unchanged and still working.
    "PRESENTATION: a pronounced bright rim light tracing the whole contour "
    "so the form separates crisply from the sweep, a defined soft contact "
    "shadow anchoring it, and a reverent centred poster composition with "
    "generous space around it. The object is presented, not photographed in "
    "passing. "
    # 5 — exclusivity, and the failure that keeps coming back.
    "EXCLUSIVITY THROUGH FORM, LIGHT AND DETAIL, NEVER THROUGH DARKNESS: a "
    "rare collectible artifact, worth stopping on and worth sending to "
    "somebody. A static symmetrical object is the failure this frame is "
    "most likely to come back as."
)

def assemble(style_text, scene, negative_text):
    """The four blocks every frame in this style is built from, in order.

    Style, then the safe-area rule, then what this frame shows, then the
    refusals. The order is load-bearing only in that it is the same order
    every time: a set drawn with the blocks shuffled is a set drawn to
    thirty-odd slightly different briefs.
    """
    return "\n".join([style_text, SAFE_AREA, scene, negative_text])


def totem_style():
    """The sculpt prefix with the totem block stacked on it.

    Stacked rather than swapped: a totem is a sculpt frame first — same
    material, same handmade marks, same safe area — and then a sculpt frame
    that has to look like the last thing in the product. Swapping the prefix
    would lose everything the first one says.
    """
    return SCULPT_STYLE + " " + TOTEM_STYLE


# --- the floors --------------------------------------------------------------

MIN_MEAN_LUMA = 90.0

MAX_MEAN_LUMA = 245.0

MIN_STDDEV = 10.0

MIN_SATURATION = 15.0

CLAY_MIN_SATURATION = 10.0

SCULPT_MIN_SATURATION = 10.0

TOTEM_MAX_SATURATION = 235.0

def band(min_sat=SCULPT_MIN_SATURATION, max_sat=None):
    """The bounds a frame is judged against, as a dict.

    `max_sat=TOTEM_MAX_SATURATION` is what makes it a totem band; everything
    else is shared, which is the point.
    """
    return {"min_luma": MIN_MEAN_LUMA, "max_luma": MAX_MEAN_LUMA,
            "min_sd": MIN_STDDEV, "min_sat": min_sat, "max_sat": max_sat}


QUIZ_BAND = band()
TOTEM_BAND = band(max_sat=TOTEM_MAX_SATURATION)

def measure(img):
    """`(mean_luma, stddev, mean_saturation)` for a frame, or None.

    Split from the verdict so the floor can be reasoned about — and tested —
    without an image or Pillow in the room.
    """
    try:
        from PIL import ImageStat
        grey = ImageStat.Stat(img.convert("L"))
        sat = ImageStat.Stat(img.convert("HSV").getchannel("S"))
        return grey.mean[0], grey.stddev[0], sat.mean[0]
    except Exception:
        return None

def verdict(stats, bounds):
    """`(ok, note)` for a measured frame, against a band. Never raises.

    Loose on purpose: it rejects near-black, blank and colourless renders and
    passes everything else, because the owner review is the real gate.
    """
    if stats is None:
        # A frame is never lost to the checker. If it cannot be measured it is
        # kept and the note says so — it is going in front of a human anyway.
        return True, "unmeasured"
    mean, sd, sat = stats
    ok = (bounds["min_luma"] <= mean <= bounds["max_luma"]
          and sd >= bounds["min_sd"] and sat >= bounds["min_sat"]
          and (bounds["max_sat"] is None or sat <= bounds["max_sat"]))
    return ok, "luma %.1f sd %.1f sat %.1f" % (mean, sd, sat)

def to_webp(raw, size):
    """The model's image, centre-cropped to the committed frame and encoded."""
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

# --- the call ----------------------------------------------------------------

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


