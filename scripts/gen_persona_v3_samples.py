#!/usr/bin/env python3
"""Draw eight sample frames in a candidate persona v3 quiz style, to review.

Console use only, run by hand against a key. Nothing imports this, no route
reaches it, and no config references what it writes:

    pip install pillow
    export OPENAI_API_KEY=sk-...
    cd ~/mazzin && python3 scripts/gen_persona_v3_samples.py --style sculpt

    python3 scripts/gen_persona_v3_samples.py --dry-run          # prompts only
    python3 scripts/gen_persona_v3_samples.py --style sculpt --dry-run
    python3 scripts/gen_persona_v3_samples.py --only s_bag_notebook --force
    python3 scripts/gen_persona_v3_samples.py --style sculpt --force

--- three styles, one directory --------------------------------------------

`--style vector` is the flat-vector set the owner reviewed first; `--style
clay` is the soft-3D clay direction picked out of that review; `--style
sculpt` is the abstract sculptural-forms direction the owner then locked,
after rejecting both. All three write into the same directory under their own
id prefix, so the sets sit side by side on the phone and the comparison is one
scroll rather than three runs of memory. Nothing overwrites anything:
`s_morning_run`, `clay_s_morning_run` and `sculpt_s_morning_run` are the same
question answered three ways.

The geometry, the retry, the crop, the cost log and the safe-area rule are
shared. What a style owns is its prefix, its negatives, its id prefix and —
for sculpt only — its own scene table.

That last one is the real split. vector and clay differ in material and agree
on everything else: both draw the scene, both put people in it. sculpt throws
the scene out and carries meaning in form alone, so it cannot reuse a scene
list written as "four friends laughing around a kitchen table" and cannot be
talked into it with a note. It brings its own eight, under the same ids.

The vector and clay prompts are frozen. Both sets were reviewed as they stand,
so a change to either would silently invalidate what is already on disk; the
suite pins each against a digest and fails if this file moves one byte of
them.

--- why this is a separate script ------------------------------------------

gen_persona.py draws the funnel as deployed. This one draws a proposal. The
owner rejected the dark gallery for the QUIZ phase — depressing, over-cropped,
unreadable at tile size — and the v3 direction splits the identity in two:
BRIGHT catchy art for the quiz, the existing dark premium look kept for the
result page. Before any config rewrite or full regeneration, eight real frames
have to exist so the direction can be judged on a phone rather than argued
about in prose.

So this script shares gen_persona.py's mechanics — the same urllib call, the
same retry, the same gpt-image-1 medium draw at 1024x1536 centre-cropped to a
600x800 WebP, the same cost log — and shares nothing else. Its own STYLE, its
own eight hardcoded prompts, its own output directory. It imports gen_persona
not at all: a sampler that reached into the live generator would make the live
generator's constants answerable to a proposal, and the whole point is that
the deployed funnel does not move while this is being looked at.

Output lands in static/galleries/persona_v3_samples/, which is new and which
nothing points at. The static mapping serves it, so the owner opens the files
directly on their phone; no funnel config names the directory, so the quiz
keeps showing exactly the art it shows today.

--- the sanity floor, deliberately loose ------------------------------------

gen_persona.py's `legibility` gate is not reused, and reusing it would be a
bug rather than a shortcut. That gate was tuned for ink frames: it caps mean
luma at 150 so that a frame which "came back bright" is rejected as having
dropped the dark identity. Every correct frame here is bright. Pointed at v3
art it would reject the whole batch for succeeding.

What replaces it is a floor, not a gate. It catches the three ways a render
comes back as a non-picture — near-black, blown-out or blank white, and
greyscale with no colour in it — and passes everything else. The owner review
is the real gate, and a floor that second-guesses the thing being reviewed
would be filtering the evidence.

The floor is shared by every style but for one number, the colour floor: a
matte material on a warm ground is a softer, less saturated picture than flat
vector art, so clay and sculpt each get a lower one. See
MIN_SATURATION_BY_STYLE.
"""
import argparse
import base64
import binascii
import io
import json
import os
import sys
import time
import urllib.error
import urllib.request

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
OUT = os.path.join(ROOT, "static", "galleries", "persona_v3_samples")

# The committed frame geometry, matched to the live gallery on purpose: these
# samples are judged as quiz tiles, so they have to be exactly the shape and
# the weight a quiz tile is.
FRAME = (600, 800)
QUALITY = 80

API_PORTRAIT = "1024x1536"
MODEL = os.getenv("OPENAI_IMAGE_MODEL", "gpt-image-1")
IMAGE_QUALITY = os.getenv("PERSONA_IMAGE_QUALITY", "medium")
TIMEOUT_S = float(os.getenv("OPENAI_TIMEOUT_S", "180"))
API_BASE = os.getenv("OPENAI_API_BASE", "https://api.openai.com/v1")

# Per-image list price, keyed (quality, api size), same published rates
# gen_persona.py assumes. Not read from the API, stale the day the price list
# moves, `--price` overrides — the number printed is an estimate and the
# invoice is the truth.
PRICE = {
    ("low", API_PORTRAIT): 0.016,
    ("medium", API_PORTRAIT): 0.063,
    ("high", API_PORTRAIT): 0.25,
}

# --- the v3 quiz identity ----------------------------------------------------
#
# Bright, warm, friendly, in two candidate materials. The one thread both keep
# from the dark result page is the electric teal, which is what stops the two
# halves of the product from looking like two products: the quiz is cream and
# coral with teal running through it, the result page is teal light on ink,
# and the teal is the hinge.
#
# Faces are the deliberate reversal, in both styles. The live gallery bans
# them outright and draws people as flat silhouettes, which is correct for a
# symbolic ink frame and is half of why the quiz reads as sombre — a
# silhouette is a person with the warmth taken out. v3 lets characters have a
# face as long as it stays at two dots and a line, which is likeable at tile
# size and still nobody in particular.

# The flat-vector prefix, exactly as the owner reviewed it. Frozen: the eight
# frames on disk were drawn from this text, so editing it makes the committed
# set and the script disagree about what the set is. The suite pins it.
VECTOR_STYLE = (
    "Flat modern vector-style illustration, warm and optimistic. "
    "Light warm background: soft cream and pale warm tones fill the frame — "
    "never a clinical pure white, never a shadowed or low-key ground. "
    "Saturated friendly palette — coral, amber, sunny yellow, leaf green — "
    "with electric teal (#4EDDC4) appearing in every frame as a recurring "
    "accent thread: one object, one light or one confident stroke. "
    "One clear subject per frame, bold and simple enough to read in half a "
    "second at phone-tile size. "
    "Clean flat shapes with crisp edges and soft simple shadows: no gradient "
    "mush, no texture noise, no fussy detail carrying the meaning. "
    "Simplified stylized human characters are welcome and wanted, with "
    "minimal facial features — two small dot eyes and one simple line for a "
    "mouth — never a realistic or detailed face."
)

# The composition rule, and the reason it is here in the shared prefix rather
# than repeated per prompt. The cropping the owner flagged is systemic, not
# per-frame: the model renders 2:3, this script centre-crops that to 3:4, and
# the tile in the UI crops again. Three crops deep, a subject that merely fits
# the render is a subject with its head off. Asking every frame for the same
# generous safe area is the only fix that scales to a seventy-frame redraw,
# and stating it once is what keeps it identical across all of them.
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

# The negatives, written to stay clear of the dark gallery's own vocabulary.
# "No ink-navy ground" would steer as well as anything here and would also put
# the phrase the v3 prompts are defined by NOT containing into every one of
# them, which makes the direction unassertable. Frozen with the prefix above.
VECTOR_NEGATIVE = (
    "No text, no letters, no numbers, no words, no logos, no watermarks, no "
    "user-interface elements, no buttons. "
    "No photorealism, no 3D render, no realistic detailed faces, no "
    "portrait-photograph likeness. "
    "Never a night scene, never a black or midnight-blue background, never a "
    "dim, murky, drab or low-key palette, no heavy grain, no clutter, no "
    "busy background."
)

# The clay prefix — the direction the owner picked out of the vector review.
#
# The hard part of this brief is what "clay" summons if left alone. Ask a model
# for clay and it reaches for claymation: Aardman, stop-motion, thumbprints in
# plasticine, a nursery. That is a children's-television look and it would read
# as cheaper than the flat vector set, not more premium. So the material is
# named positively — matte, finely textured, studio-lit, rendered — and the
# claymation reading is refused explicitly in the negatives rather than left to
# chance.
CLAY_STYLE = (
    "Soft 3D clay-render illustration in a premium modern app aesthetic, warm "
    "and optimistic. Rendered, not sculpted by hand: the polished soft-3D "
    "look of contemporary product and app illustration. "
    "Matte clay-like materials with a subtle fine surface texture, rounded "
    "simplified forms with softly bevelled edges, warm studio lighting with "
    "soft diffused shadows and a gentle shallow depth-of-field feel. "
    "Clean light-warm background: soft cream and pale peach tones fill the "
    "frame — never a clinical pure white, never a shadowed or low-key ground. "
    "Warm friendly palette — soft coral, amber, sunny yellow, leaf green — "
    "with electric teal (#4EDDC4) appearing in every frame as a recurring "
    "accent material: one moulded object, one garment or one soft glow. "
    "One clear subject per frame, bold and simple enough to read in half a "
    "second at phone-tile size. "
    "Stylized human figures moulded in clay, with minimal faces — two small "
    "dot eyes and one simple understated feature — friendly but composed, "
    "never realistic and never childish."
)

# What clay must NOT inherit from the vector set is its "no 3D render" line:
# clay IS a 3D render, and banning one in the same prompt that asks for one is
# how a set comes back flat and confused. Everything else the vector negatives
# refuse — text, dark palettes, real faces — still holds, so the two lists are
# close but not the same, and neither is derived from the other.
CLAY_NEGATIVE = (
    "No text, no letters, no numbers, no words, no logos, no watermarks, no "
    "user-interface elements, no buttons. "
    "Not claymation, not stop-motion, not plasticine, not Aardman, not "
    "handmade-looking: no visible fingerprints, thumbprints, tool marks or "
    "seams in the clay, nothing lumpy, nothing childish, nothing toy-like or "
    "nursery-like. "
    "No photorealism, no realistic skin or hair, no realistic detailed faces, "
    "no portrait-photograph likeness, no uncanny human anatomy. "
    "Never a night scene, never a black or midnight-blue background, never a "
    "dim, murky, drab or low-key palette, no clutter, no busy background."
)

# --- what the v1 sculpt review changed --------------------------------------
#
# The owner reviewed eight sculpt frames, kept the direction and rejected the
# execution on three counts, all of them prompt problems rather than render
# problems:
#
#   Zero meaning. Every form came back static, symmetric and rounded, so all
#   eight read "calm" and the set said nothing. "Abstract sculptural form" on
#   its own reliably returns a symmetrical object sitting still, so v2 asks
#   for a gesture per composition and names a static balanced still-life as a
#   failure of the brief.
#
#   Machine-smooth. The handmade quality of the reference was gone. v1 asked
#   for "a subtle fingerprint-and-tool surface texture", and subtle is exactly
#   what it got — invisible at tile size. v2 names the marks as things pushed
#   into the surface and says outright that they must be visible.
#
#   Weak figure-ground. A pale form on a pale sweep does not separate in a
#   thumbnail. v2 pushes the backdrop two steps deeper and less saturated than
#   the sculpture tones, and adds a rim light and a contact shadow.
#
# A fourth change follows from the first. If every form is doing something,
# the rounded-only vocabulary has to give, because a form under pressure is
# not a round form. So angular, pinched, wedged and cracked become available
# to a strained composition and stay out of a calm one. The scenes decide, and
# exactly one of the eight is strained.
#
# The floors did not move. A deeper backdrop lowers mean luma and saturation,
# so both were re-checked against what v2 asks for: the muted drain frame is
# the darkest and least colourful of the eight and still sits far above the
# floor, because "two steps deeper" from a warm sweep is not a dark ground —
# the prefix still refuses one.

# The sculpt prefix — the direction the owner locked, and the one that breaks
# the pattern the other two share.
#
# vector and clay differ in material and agree on everything else: both draw
# the scene, both put people in it, both were judged on whether the people
# looked right. sculpt throws the scene out. Meaning is carried by form alone —
# a coil, a hollow, a cluster — on a warm monochrome backdrop, the way a
# product still-life carries it. So sculpt is the one style that cannot reuse
# the shared scene list: a scene written as "four friends laughing around a
# kitchen table" is not a thing this style can draw, and softening it with a
# note would produce exactly the half-and-half render the direction rejects.
# It brings its own eight, keyed by the same ids so the sets line up for
# review.
#
# The figure ban is the reversal, and it is absolute. vector and clay go out
# of their way to permit a face at two dots and a line; here a face of any
# kind is the failure. It is stated in the prefix and again in the negatives,
# because "abstract sculptural form" on its own is a brief a model will
# cheerfully answer with a little clay person.
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
    "Pure form only: the meaning is carried by shape, volume, weight and "
    "gesture, never by depicting anything. Each composition is an enigmatic "
    "object — evocative, open to interpretation, a shape that makes the "
    "viewer pause and read themselves into it. Vary the silhouettes "
    "strongly from one composition to the next, so no two read alike."
)


# The negatives carry the ban a second time, in the blunter register a
# negative list is read in. "No people" is not enough on its own — a model
# handed a sculptural brief will offer a bust, a mannequin or a pair of hands
# and consider the brief met — so the near misses are named.
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

# sculpt's own eight, in the order the shared list uses, keyed by the same
# ids. Same questions, answered in form: what the runner frame is *about* is
# stored energy, so the runner becomes a coil under tension. Nothing here
# names an object from the world except as pure geometry.
SCULPT_SCENES = {
    # Every one leads with its gesture, because the verb is the thing that
    # was missing: v1 described what each form WAS and got eight objects
    # sitting still. Each also owns a distinct silhouette class — vertical
    # spiral, low slab, nested curves, cluster, drooping-over-a-wedge, flat
    # spread, horizontal drift, tall arc — so the set varies at tile size.
    "s_morning_run": (
        "A tight coil of terracotta clay caught mid-launch: wound close at "
        "the base and released upward, tilted forward off the vertical and "
        "lifting clear of the ground with open air beneath its lowest turn, "
        "the whole form straining up and away. Its leading tip is electric "
        "teal. Off-balance, asymmetric, unmistakably going somewhere."
    ),
    "s_morning_slow": (
        "A soft ochre clay mass settled and gone slack: low and wide, spread "
        "by its own weight, its edges slumping gently outward where it has "
        "relaxed down onto the surface beneath it. One shallow electric "
        "teal seam runs through the spread. Heavy, restful, unhurried — at "
        "ease rather than rigid, and clearly not going to move."
    ),
    "s_battery_home": (
        "A small rounded form curled snugly into a sheltering hollow of "
        "terracotta clay, tucked in so close that the hollow's inner curve "
        "and the curled form's outer curve meet along their whole length. A "
        "soft electric teal glaze sits on the inner form. Held rather than "
        "enclosed: solitude as comfort, a perfect fit."
    ),
    "s_battery_people": (
        "Four rounded sand and ochre clay forms of different heights leaning "
        "hard into one another, pressing warm where their sides meet and "
        "flattening slightly at each contact, with one small electric teal "
        "form nestled low in the middle of the huddle. Weight shared, every "
        "gap closed, the whole cluster tipped together off any single axis."
    ),
    "s_drain_meeting": (
        "A soft muted grey-brown clay form wilting: half-deflated and "
        "sagging, drooping over the sharp edge of a dull, heavy, wedge-shaped "
        "slab, its lower end hanging limp toward the ground. The slab is "
        "angular and hard-cornered where the form is spent and soft; a "
        "hairline crack runs along its top. A thin electric teal line traces "
        "the drooping edge. Drained, sagging, going nowhere."
    ),
    "s_bag_notebook": (
        "An open wave-spread of sand-toned clay, creased once down its "
        "centre and opening upward, with a slim electric teal cylinder "
        "resting across it at an angle — tilted as though just set down a "
        "moment ago and not yet straightened. Hero-object scale, nothing "
        "else in the composition, the tilt breaking the symmetry."
    ),
    "s_weather_fog": (
        "A low soft mass of pale cream clay drifting sideways over a few "
        "small rounded ochre mounds, stretched thin in the direction it is "
        "travelling, one trailing edge pulling away behind it and thinning "
        "to nothing. A narrow electric teal band runs low through the "
        "drift. Quiet and moving, calm rather than gloomy."
    ),
    "s_character_cartographer": (
        "A tall poised arc of warm sand-toned clay rising and curving over "
        "at its top, raising a small glowing sphere aloft at the far end of "
        "its reach — the gesture of seeking, of lighting the way ahead. The "
        "sphere carries an electric teal inlay and throws a soft warm glow "
        "back down the arc. Upright, watchful, asymmetric, and composed as "
        "an emblem: centred, poster-like, evenly lit, with the quiet "
        "authority of a maker's mark, at the scale and consistency where "
        "eight of these side by side would obviously belong to one set."
    ),
}


# The registry, and the whole of what a style owns: a prefix, its negatives,
# and the prefix its ids carry so two sets share one directory without
# colliding. The scenes, the geometry, the crop, the retry and the safe-area
# rule are shared, because a second copy of any of those is a second thing to
# keep in step across a redraw.
STYLES = {
    "vector": {"style": VECTOR_STYLE, "negative": VECTOR_NEGATIVE,
               "prefix": ""},
    "clay": {"style": CLAY_STYLE, "negative": CLAY_NEGATIVE,
             "prefix": "clay_"},
    "sculpt": {"style": SCULPT_STYLE, "negative": SCULPT_NEGATIVE,
               "prefix": "sculpt_", "scenes": SCULPT_SCENES},
}
DEFAULT_STYLE = "vector"


# --- the eight samples -------------------------------------------------------
#
# One per question type the quiz actually asks, so the batch answers the whole
# direction rather than eight versions of one easy frame: two halves of a pair
# scene, two options off a four-up grid, the drain question that has to be
# funny instead of bleak, a hero object, an inner-weather card with no subject
# in it, and the character portrait.
#
# The last one carries the most weight. The eight-personas face asset is the
# piece with no precedent in the live funnel — the dark gallery has no people
# in it at all, only silhouettes — so s_character_cartographer is the frame
# that decides whether the character system is worth building.

SAMPLES = [
    ("s_morning_run",
     "A single stylized runner mid-stride on a quiet dawn street, warm early "
     "sun low and bright behind them, a few simple flat buildings and one "
     "round tree far back. Long optimistic morning light, coral and amber "
     "sky, leaf-green tree, an electric teal stripe on the runner's clothing "
     "and shoes. Energetic and glad to be out. The whole runner, head to "
     "shoes, sits centred and complete with clear sky above and clear street "
     "below."),

    ("s_morning_slow",
     "A cosy table seen from a gentle raised angle: a steaming mug with soft "
     "curls of steam, an open notebook lying flat with a slim pen beside it, "
     "and one small potted plant. Warm cream tabletop, amber and leaf-green "
     "accents, an electric teal band around the mug. Unhurried and inviting. "
     "The whole arrangement sits centred and complete with a generous margin "
     "of plain warm background on every side."),

    ("s_battery_home",
     "One stylized person sitting happily alone on a couch, knees up, shoes "
     "off on the floor, a warm amber lamp glowing beside them, a cat curled "
     "asleep on the far cushion and a soft electric teal glow from the phone "
     "in their hands. Modern, content, comfortably recharging — pleased with "
     "their own company, not lonely. Couch, person, lamp and cat are all "
     "whole and sit inside the centre of the frame."),

    ("s_battery_people",
     "A small circle of four stylized friends laughing around a kitchen "
     "table, mugs and a shared plate of food between them, open easy body "
     "language and hands mid-gesture. Coral, amber and sunny-yellow "
     "clothing, leaf-green plant on the windowsill, one electric teal chair. "
     "Faces are only dot eyes and simple curved smiles. The whole group and "
     "the whole table sit inside the centre of the frame with nobody clipped "
     "by an edge."),

    ("s_drain_meeting",
     "A comically endless meeting: a long table with several near-identical "
     "flat figures still talking, and one gently wilted character slumping "
     "sideways in their chair with a drooping posture, while an oversized "
     "round wall clock looms behind them. Played for warm comedy, bright and "
     "recognisable rather than bleak — sunny-yellow wall, coral chairs, "
     "amber tabletop, an electric teal rim on the clock. The table, the "
     "figures and the whole clock all sit inside the centre of the frame."),

    ("s_bag_notebook",
     "A hero-object composition: one closed notebook with a slim pen resting "
     "diagonally across its cover, presented straight on against a plain "
     "soft-cream ground with one simple soft shadow beneath it. The notebook "
     "is coral with an electric teal elastic band and an amber page edge. "
     "Confident, poster-like, nothing else in the picture. Large and "
     "perfectly centred, with a wide even margin of empty background on all "
     "four sides."),

    ("s_weather_fog",
     "Soft pale fog drifting in gentle horizontal bands across a few small "
     "rounded hills, one tiny tree on the nearest crest, a mild amber sun "
     "disc glowing through the haze. Calm, soft and quietly hopeful, not "
     "gloomy — pale cream sky, warm pale grey mist, leaf-green hills and one "
     "thin electric teal band low in the fog. The hills and the tree sit "
     "whole and centred, with clear sky margin above and clear open ground "
     "margin below."),

    ("s_character_cartographer",
     "A poster-like character portrait of one stylized human figure with "
     "quiet cartographer energy: standing behind a small table with a large "
     "map unrolled flat in front of them, one hand resting on the paper, a "
     "warm lamp at their side throwing a soft electric teal glow across the "
     "map. Curious, warm and immediately likeable. The face carries only two "
     "dot eyes and one simple line for a mouth. Coral and amber clothing, "
     "leaf-green details, electric teal accent light. The figure is centred "
     "and shown complete from mid-thigh upward, with the lamp and the whole "
     "map inside the frame and generous warm background all around."),
]


# One scene wants a sentence in clay that it does not want in vector.
#
# The character portrait is the frame that decides the eight-personas asset,
# and "collectible figure" is a clay idea specifically: it is what makes a
# moulded figure read as one of a set rather than as a person in a picture.
# Said to a flat-vector render it would just ask for a sticker. So it is a
# per-style note on the one scene that needs it, rather than a second copy of
# the scene or a sentence bolted onto all sixteen prompts.
# Two of them also want a correction rather than an addition. The scene text
# is shared and the vector prompts are frozen, so `a few simple flat
# buildings` and `several near-identical flat figures` — written when flat was
# the material — cannot be reworded without moving the set already on disk.
# Left alone in a clay prompt they contradict the prefix in the same breath it
# asks for moulded, rounded, dimensional forms, and a model handed both tends
# to split the difference into relief cut-outs. So clay overrules them where
# they appear, in the scene's own slot, close enough to the wording it is
# answering to actually win.
STYLE_SCENE_NOTES = {
    "clay": {
        "s_morning_run": (
            "The buildings and the tree are moulded clay forms — rounded, "
            "dimensional and softly lit, never flat graphic cut-outs."
        ),
        "s_drain_meeting": (
            "Every figure is a rounded moulded clay character with real "
            "volume and a soft shadow, never a flat graphic shape."
        ),
        "s_character_cartographer": (
            "Give the figure the feel of a premium collectible character "
            "figure: a single moulded character presented straight on, "
            "poster-like and evenly lit, at the scale and consistency where "
            "eight of these side by side would obviously belong to one set."
        ),
    },
}


def scene_for(base_id, scene, style=DEFAULT_STYLE):
    """What this style draws for a given sample id.

    Three cases, and they are a hierarchy rather than a menu. A style with its
    own scene table replaces the shared scene outright — sculpt carries no
    people and no places, so a scene about four friends at a kitchen table is
    not something it can soften into shape. A style with a note appends to the
    shared scene. A style with neither draws the shared scene as written.

    A replacement wins over a note, and never silently merges with one: a
    scene that has been thrown out has no wording left for a note to correct.
    """
    scenes = STYLES[style].get("scenes")
    if scenes is not None:
        return scenes[base_id]
    note = STYLE_SCENE_NOTES.get(style, {}).get(base_id)
    return scene + " " + note if note else scene


def prompt_for(scene, style=DEFAULT_STYLE):
    """The four blocks every sample is built from, in the same order.

    The safe-area rule sits in the same slot in every style and is the same
    text in all of them, because the crop it is written against is a property
    of the pipeline rather than of the material — the render is 2:3, this
    script centre-crops it to 3:4 and the tile crops again, whichever way the
    picture was drawn.
    """
    spec = STYLES[style]
    return "\n".join([spec["style"], SAFE_AREA, scene, spec["negative"]])


def sample_id_for(base_id, style=DEFAULT_STYLE):
    """The id a scene is filed under in this style.

    The vector set carries no prefix: it is on disk under these names already
    and reviewed under them, and renaming it to `vector_s_morning_run` to make
    the scheme tidy would orphan eight files somebody has already looked at.
    """
    return STYLES[style]["prefix"] + base_id


def samples(style=DEFAULT_STYLE):
    """The batch, in the order it is drawn and reviewed."""
    return [{"id": sample_id_for(base_id, style), "base_id": base_id,
             "style": style, "size": FRAME, "api_size": API_PORTRAIT,
             "prompt": prompt_for(scene_for(base_id, scene, style), style)}
            for base_id, scene in SAMPLES]


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


# --- the sanity floor --------------------------------------------------------

# Bright art on a warm ground sits high. Below this the render came back as a
# dark picture, which for v3 means the model ignored the brief rather than
# that the frame is merely moody.
MIN_MEAN_LUMA = 90.0

# And above this, with nothing else going on, it is a blown-out or empty page.
MAX_MEAN_LUMA = 245.0

# One flat wash — cream rectangle, white rectangle — scores fine on luma and
# is still not a picture.
MIN_STDDEV = 10.0

# Saturated friendly palette, or it is not the style. A greyscale or
# near-greyscale render fails here and nowhere else; the threshold is low
# enough that the palest frame in the batch (the fog card) clears it.
MIN_SATURATION = 15.0

# Clay sits lower, and gets its own number rather than dragging the vector
# floor down with it. Matte clay lit in a studio is a desaturated material by
# construction — the highlight on a coral form is a wash toward white and the
# shade is a wash toward grey, where flat vector art holds one saturated fill
# edge to edge. On the palest scene in the batch, the fog card, a clay render
# is mostly near-neutral mist over a cream ground and can plausibly land in
# the low teens, which the vector floor would reject for being exactly what
# was asked for.
#
# It is set by reasoning about the material rather than by measuring a batch,
# so it is a starting number: if a clay run rejects a frame that looks right
# in the log's `sat` reading, this is the line to move. What it must keep
# catching is a colourless render, and those come back near zero — a true
# greyscale frame is nowhere near 10, so the margin below is intact even
# though the margin above got thinner.
CLAY_MIN_SATURATION = 10.0

# sculpt sits in the same place as clay and for the same reason, but on its
# own knob rather than sharing clay's: it is the same matte material, and its
# backdrop is a warm monochrome sweep rather than the cream-plus-coral the
# other two put behind a subject, so a correct frame is a narrower band of
# warm hues than either.
#
# It is not obviously lower than clay in practice — terracotta and ochre read
# as muted to the eye but are not low-saturation numbers, since saturation
# here is (max-min)/max over the channels and a warm tone spreads them wide.
# What could sit low is the palest scene in the set, the fog drift, which is
# cream clay over ochre mounds and mostly backdrop. 10.0 clears that with room
# and still sits far above a colourless render, which comes back near zero.
# Pinned rather than derived: if a sculpt run rejects a frame that looks right
# in the log's `sat` reading, this is the line to move.
SCULPT_MIN_SATURATION = 10.0

# Keyed rather than branched, now that there are three: a fourth style that
# forgets to add itself here gets the vector floor, which is the strict one,
# so the failure is a rejected frame and a look at this table rather than a
# silently unchecked batch.
MIN_SATURATION_BY_STYLE = {
    "vector": MIN_SATURATION,
    "clay": CLAY_MIN_SATURATION,
    "sculpt": SCULPT_MIN_SATURATION,
}


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


def min_saturation(style=DEFAULT_STYLE):
    """The colour floor this style is judged against."""
    return MIN_SATURATION_BY_STYLE.get(style, MIN_SATURATION)


def sanity(stats, style=DEFAULT_STYLE):
    """`(ok, note)` for a measured frame. Never raises.

    Loose on purpose: it rejects near-black, blank and colourless renders and
    passes everything else, because the owner review is the real gate and this
    batch exists to be looked at.
    """
    if stats is None:
        # A frame is never lost to the checker. If it cannot be measured it is
        # kept and the note says so — it is going in front of a human anyway.
        return True, "unmeasured"
    mean, sd, sat = stats
    ok = (MIN_MEAN_LUMA <= mean <= MAX_MEAN_LUMA
          and sd >= MIN_STDDEV and sat >= min_saturation(style))
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


# --- the run -----------------------------------------------------------------
#
# No manifest, and the reason gen_persona.py needs one does not apply. There,
# every id already had a placeholder file, so "skip what exists" would have
# drawn nothing on the first run and nothing ever after. Here the directory is
# new and every file in it is a real draw, so the file on disk IS the record.
# `--force` redraws, `--only` names ids.


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--style", default=DEFAULT_STYLE,
                    choices=sorted(STYLES),
                    help="which candidate style to draw (default: %s)"
                         % DEFAULT_STYLE)
    ap.add_argument("--dry-run", action="store_true",
                    help="print the plan and every prompt, call nothing")
    ap.add_argument("--only", default="",
                    help="comma-separated sample ids to consider, with or "
                         "without this style's id prefix")
    ap.add_argument("--force", action="store_true",
                    help="redraw samples whose file is already on disk")
    ap.add_argument("--price", type=float, default=None,
                    help="override the assumed per-image price in dollars")
    ap.add_argument("--retries", type=int, default=2,
                    help="redraws allowed when a sample fails the floor")
    args = ap.parse_args(argv)

    plan = samples(args.style)
    if args.only:
        # Both spellings resolve, because the prefix is bookkeeping for the
        # shared directory and nobody reviewing clay thinks of the fog card as
        # anything but the fog card. `--style clay --only s_weather_fog` and
        # `--only clay_s_weather_fog` name the same frame; a name that is
        # neither is an error rather than an empty run.
        wanted, unknown = set(), []
        for raw in (n.strip() for n in args.only.split(",")):
            if not raw:
                continue
            for frame in plan:
                if raw in (frame["id"], frame["base_id"]):
                    wanted.add(frame["id"])
                    break
            else:
                unknown.append(raw)
        if unknown:
            print("unknown sample id(s) for style %s: %s"
                  % (args.style, ", ".join(unknown)))
            return 2
        plan = [f for f in plan if f["id"] in wanted]

    if not args.force:
        plan = [f for f in plan
                if not os.path.exists(os.path.join(OUT, f["id"] + ".webp"))]

    price = args.price
    if price is None:
        price = PRICE.get((IMAGE_QUALITY, API_PORTRAIT), 0.0)

    print("%s style, %s, quality %s, %d sample(s) to draw, ~$%.2f estimated"
          % (args.style, MODEL, IMAGE_QUALITY, len(plan), len(plan) * price))

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
        print("Run:  OPENAI_API_KEY=sk-... python3 "
              "scripts/gen_persona_v3_samples.py --style %s" % args.style)
        return 1

    os.makedirs(OUT, exist_ok=True)
    spent, drawn, failed = 0.0, 0, []
    for frame in plan:
        sample_id = frame["id"]
        note = ""
        for attempt in range(args.retries + 1):
            try:
                raw = generate(frame["prompt"], frame["api_size"], key)
            except GenerationError as err:
                note = "api: %s" % err.code
                break
            spent += price
            data, img = to_webp(raw, frame["size"])
            ok, note = sanity(measure(img), frame["style"])
            if ok:
                path = os.path.join(OUT, sample_id + ".webp")
                with open(path, "wb") as fh:
                    fh.write(data)
                drawn += 1
                print("  %-26s %6d B  $%.3f  %s"
                      % (sample_id, len(data), price, note))
                break
            print("  %-26s rejected (%s), redrawing" % (sample_id, note))
        else:
            failed.append((sample_id, note))
            print("  %-26s FAILED after %d draws (%s)"
                  % (sample_id, args.retries + 1, note))
            continue
        if note.startswith("api: "):
            failed.append((sample_id, note))
            print("  %-26s FAILED (%s)" % (sample_id, note))

    print("\n%d sample(s) drawn, ~$%.2f spent, %d failed"
          % (drawn, spent, len(failed)))
    for sample_id, why in failed:
        print("  FAILED %s: %s" % (sample_id, why))
    print("review: %s" % OUT)
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
