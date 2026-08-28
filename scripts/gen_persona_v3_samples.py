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
scroll rather than three runs of memory. Nothing overwrites anything.

The geometry, the retry, the crop, the cost log and the safe-area rule are
shared. What a style owns is its prefix, its negatives, its id prefix and,
optionally, its own sample list.

That last one is the real split, and it is sculpt's alone. vector and clay
differ in material and agree on everything else: both answer the same eight
questions under the same eight ids, so `s_morning_run` and `clay_s_morning_run`
are one question drawn two ways. sculpt does not answer those questions at
all. Its eight are idiom-states — a compressed coil, a collapsed volume —
which are not answers to anything, so it brings its own list and its own ids
(`sculpt_i_wound_up`) rather than claiming a correspondence that is not there.

The vector and clay prompts are frozen. Both sets were reviewed as they stand,
so a change to either would silently invalidate what is already on disk; the
suite pins each against a digest and fails if this file moves one byte of
them.

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

# --- sculpt v3: the eight idiom-states ---------------------------------------
#
# v2 fixed the surface and the set still said nothing, and the review found
# why: the scenes were asking abstract forms to depict situations. "A draining
# meeting" is a story. A form cannot narrate — it has no before and after, no
# cause, nobody it is happening to — so a sculpture of a meeting is either a
# meeting (figures, a table, the thing the style bans) or it is a shape that
# happens to be drooping, which is what came back.
#
# v3 drops situations for states. Every frame is a physical-metaphor state
# that ordinary language already uses for a psychological one: wound up,
# drained, scattered, grounded, on edge, carrying, walled off, lit up. These
# are not descriptions of a form, they ARE forms — "wound up" is a compressed
# coil, "drained" is a collapsed volume with the air gone. The metaphor was
# already physical before anybody applied it to a mood, which is why a
# sculpture can carry it and a sculpture of a meeting cannot.
#
# The test the set has to pass runs both ways. Word alone must be sculptable
# without ambiguity: hand "wound up" to a sculptor and one shape comes back.
# Image alone must return the word: show the render and "wound up" is what
# occurs to you. A frame that only works in one direction is decoration with
# a caption.
#
# Hence its own ids. sculpt no longer answers the same eight questions as
# vector and clay under shared ids — the idioms ARE the concept under test,
# and filing them as `sculpt_s_morning_run` would say the coil is one answer
# to the morning question when it is not an answer to a question at all. The
# sample list is the style's own, and the id carries the idiom, so the two-way
# test is checkable from the id alone.
SCULPT_SAMPLES = [
    ("i_wound_up",
     "A coil of terracotta clay wound up tight: its turns compressed hard "
     "against one another with almost no gap left between them, the whole "
     "spring shortened under its own load and leaning slightly off "
     "vertical, loaded and about to release. A restrained electric teal "
     "band marks the innermost turn. Stored energy, held."),

    ("i_drained",
     "A hollow clay form drained and slumped empty: its walls collapsed "
     "inward, the air gone out of it, the whole skin sagging and draped "
     "loosely over its own base with nothing left holding it up. Muted "
     "grey-brown, the flattest tone in the set, with one faint electric "
     "teal line along the fallen rim. Emptied, not resting."),

    ("i_scattered",
     "One clay form scattered: broken into five or six fragments drifting "
     "apart across the composition, each piece carrying the sharp fractured "
     "edge where it parted from its neighbour, clear gaps of empty backdrop "
     "opening between them. The pieces still read as one object that came "
     "apart. One fragment is electric teal. Dispersed, not arranged."),

    ("i_grounded",
     "A dense monolith of terracotta clay standing grounded: a wide rooted "
     "base flaring where it meets the ground and carrying the mass "
     "squarely, the whole volume low, settled, planted and immovable. Soft "
     "and rounded throughout, with one calm electric teal seam running down "
     "the base. Unhurried weight, going nowhere and untroubled by it."),

    ("i_on_edge",
     "A heavy rounded clay mass balanced on edge: resting on a single sharp "
     "point of contact, tipped past its own centre and visibly about to go "
     "over, held for one more moment by nothing much. A thin electric teal "
     "line marks the point it is balanced on. Tense stillness, not rest."),

    ("i_carrying",
     "A tall clay form carrying a heavy sphere: bowed and compressed under "
     "the weight pressing down on its upper surface, its sides bulging "
     "where the load pushes through it, still upright and still holding. "
     "The sphere is a dull dense ochre; a restrained electric teal band "
     "circles the bearing form. Bearing it, not buckling."),

    ("i_walled_off",
     "A soft rounded clay form walled off: enclosed inside a thick smooth "
     "curving wall it raised around itself, the wall unbroken but for one "
     "narrow opening, the inner form intact and quite separate. Warm sand "
     "wall, ochre form, a small electric teal mark at the opening. "
     "Sheltered and apart, both at once."),

    ("i_lit_up",
     "A clay form lit up from within: a bright electric teal core glowing "
     "out through a network of fine cracks and seams that run across its "
     "surface, the light spilling from inside the volume rather than "
     "falling on it, warm terracotta shell against the glow. The one frame "
     "in the set that gives light instead of holding it."),
]


# The head is the one frame in this style that is allowed to be a head, and
# it is an exception rather than an oversight, so it is written down as one.
#
# The result page draws a clay head with the reader's radar inlaid on the
# cranium. That is the product, and it needs a head — which the sculpt
# negatives otherwise refuse outright, correctly, because every other frame
# asking for one would be the failure this style exists to avoid. So this
# frame swaps the blanket ban for a narrower one: a featureless sculptural
# profile is allowed, and everything that would make it a person — eyes, a
# mouth, hair, expression, a likeness, anything below the neck — is refused
# by name. Nothing else may claim this negative; the suite pins it to this id.
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

# Keyed by base id and consulted only by sculpt. One entry, and the intent is
# that it stays one entry.
SCULPT_NEGATIVE_OVERRIDES = {"p_head_base": SCULPT_HEAD_NEGATIVE}


# --- the totem block: what a culmination frame has to be ---------------------
#
# The owner's verdict on the first totem was "too plain" — it read as a vase.
# That is the right verdict and the diagnosis is structural: the sculpt prefix
# is written for quiz cards, which have to be legible at tile size on a light
# ground and must not shout, and a totem is the opposite object. It is the
# last thing the product shows, it is what the reader is being told they are,
# and it has to look like something behind glass.
#
# So this is an additional block rather than an edit to the prefix. Quiz cards
# keep the light warm backdrop they were designed for; totems get the result
# page's world — dusk, one hard light, deep shadow — and three demands the
# cards do not carry.
#
# Applied to totem ids only. `TOTEM_IDS` is the whole coupling, and v3-B's
# eight inherit it by being named here.
TOTEM_STYLE = (
    "This frame is a totem: the culmination piece, not a quiz card. Three "
    "things are required of it and none of them is optional. "
    # 1 — inner light. The cracked-egg formula: matter, a visible event, and
    # light escaping from inside it. A teal-painted surface is the failure
    # this is written against, because painted teal reads as decoration and
    # the whole rule of the set is that teal marks where the meaning is.
    "INNER LIGHT, MANDATORY: the form is lit from within and the light gets "
    "out — a bright electric teal glow emitted from inside the volume, "
    "escaping through cracks, seams, a split or an opening, or showing as a "
    "molten core through a fissure in the clay. The light spills onto the "
    "surrounding clay as a soft glow bloom and throws its own colour into the "
    "shadow. This is emitted light, never a teal-painted surface and never a "
    "teal object sitting next to the form. "
    # 2 — presentation. The quiz's cream sweep is what makes a totem read as
    # a vase on a shelf; this is the museum case.
    #
    # Softened after the first three draws came back at luma 20-25 — darker
    # than the umbra backdrop's own colour, which means the model read "dark
    # dusk-warm backdrop in deep umbra" plus "alone in the dark" as night and
    # returned a glow floating in blackness with no clay left in it. The
    # intent was always a dimmed studio sweep rather than a dark place, so
    # that is what it now asks for: the same seamless sweep every other frame
    # is shot against, turned down, keeping its own warm colour with the
    # spotlight pooling on it — and the clay lit and readable as clay, with
    # the glow adding to that light rather than replacing it.
    "DRAMATIC PRESENTATION: the same plain seamless sweep the other frames "
    "are shot against, dimmed to a deep warm dusk — the light of a gallery "
    "at closing time, not night. Markedly darker than the light backdrop the "
    "quiz cards are shot against, the world of the result page rather than "
    "the quiz, but never black: the sweep keeps its own warm colour and "
    "stays visible behind the form. One single dramatic spotlight from above "
    "and to one side falls across the form and pools on the sweep behind it, "
    "a pronounced bright rim light traces the contour, and a deep soft "
    "shadow gathers beneath. The clay itself stays clearly lit and clearly "
    "readable as clay — warm terracotta and ochre, its surface and its "
    "handmade marks still visible in the light — and the inner glow adds to "
    "that light instead of replacing it. Museum-piece lighting: the object "
    "is spotlit against a dim warm sweep, never a glowing shape floating in "
    "blackness. "
    # 3 — exclusivity. Restating the pose-verb rule at the top of its range,
    # because a totem that stands still is a vase however it is lit.
    "EXCLUSIVITY: a rare collectible artifact, poster composition, centred "
    "and reverent. The form is dynamic and caught mid-gesture — the "
    "pose-verb rule applies doubly here, and a static symmetrical object is "
    "the failure this frame is most likely to come back as."
)

# Which frames the block is applied to. Exactly the totems: a quiz card handed
# this block would come back dark, off-brief and unreadable at tile size.
TOTEM_IDS = {"p_totem_open_flame"}


# --- the v3-A preview: three frames the funnel rewrite needs now -------------
#
# Not idioms, and filed apart from them under `p_` for that reason. These are
# production slots the v3-A config and result page reference by path, drawn
# early so the concept can be seen assembled rather than described: the clay
# head the result page overlays its radar onto, one persona totem, and one
# card face from the new walk. The full set is v3-B; these three are the ones
# that decide whether the rest is worth drawing.
SCULPT_PREVIEW = [
    ("p_head_base",
     "A clay head in clean profile, seen side-on: a simplified sculptural "
     "head form in matte terracotta, cut off cleanly at the neck and resting "
     "as a studio object. The whole upper cranial area is one smooth, even, "
     "unbroken clay surface — deliberately empty and unmarked, a blank field "
     "with no features, no texture and no detail anywhere on it — while the "
     "brow, nose and jaw of the profile are softly modelled. A restrained "
     "electric teal seam runs along the base of the neck. Centred, upright, "
     "evenly lit, with the empty cranial field held clear of every edge."),

    ("p_totem_open_flame",
     "An upward-twisting clay form: a single column of warm terracotta "
     "rising and turning as it climbs, widening as it goes, its whole "
     "mass leaning into the ascent, with a bright electric teal glow at the "
     "very tip where the twist opens out. The tone warms from deep ochre "
     "at the base to lit amber at the top, so the colour climbs with the "
     "form. "
     "Matter, a visible event, and light from inside — an open flame with no "
     "fire in it. Composed as an emblem: centred, poster-like, evenly lit."),

    ("p_chapter_climbing",
     "A rounded clay form climbing a slope: a compact ochre volume caught "
     "part-way up a rising sand-toned incline, tilted forward into the climb "
     "with its trailing edge still stretched down the slope behind it and "
     "clear ground above it yet to cover. A restrained electric teal mark "
     "sits where the form meets the slope, at the point it is pushing "
     "against. Effortful and unfinished, and clearly going up."),
]


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
               "prefix": "sculpt_",
               "samples": SCULPT_SAMPLES + SCULPT_PREVIEW},
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
    """The scene text, plus whatever this style adds to it.

    Only clay adds anything: two corrections and one note, on the shared
    scenes it inherits. A style that disagrees with the shared scenes more
    deeply than a note can fix brings its own sample list instead — that is
    what sculpt does — so there is no per-id replacement mechanism here.
    """
    note = STYLE_SCENE_NOTES.get(style, {}).get(base_id)
    return scene + " " + note if note else scene


def negative_for(base_id, style=DEFAULT_STYLE):
    """The refusals this frame is drawn against.

    A style's own negatives, unless one frame has been granted its own — which
    exactly one has, and for a reason recorded above it.
    """
    if style == "sculpt" and base_id in SCULPT_NEGATIVE_OVERRIDES:
        return SCULPT_NEGATIVE_OVERRIDES[base_id]
    return STYLES[style]["negative"]


def style_for(base_id, style=DEFAULT_STYLE):
    """The prefix this frame is drawn on.

    The style's own, plus the totem block where the frame is a totem. Stacked
    rather than swapped: a totem is a sculpt frame first — same material, same
    handmade marks, same safe area — and then a sculpt frame under museum
    lighting. Swapping the prefix would lose everything the first one says.
    """
    prefix = STYLES[style]["style"]
    if style == "sculpt" and base_id in TOTEM_IDS:
        return prefix + " " + TOTEM_STYLE
    return prefix


def prompt_for(scene, style=DEFAULT_STYLE, base_id=None):
    """The four blocks every sample is built from, in the same order.

    The safe-area rule sits in the same slot in every style and is the same
    text in all of them, because the crop it is written against is a property
    of the pipeline rather than of the material — the render is 2:3, this
    script centre-crops it to 3:4 and the tile crops again, whichever way the
    picture was drawn.
    """
    return "\n".join([style_for(base_id, style), SAFE_AREA, scene,
                      negative_for(base_id, style)])


def sample_id_for(base_id, style=DEFAULT_STYLE):
    """The id a scene is filed under in this style.

    The vector set carries no prefix: it is on disk under these names already
    and reviewed under them, and renaming it to `vector_s_morning_run` to make
    the scheme tidy would orphan eight files somebody has already looked at.
    """
    return STYLES[style]["prefix"] + base_id


def samples(style=DEFAULT_STYLE):
    """The batch, in the order it is drawn and reviewed.

    A style either answers the shared eight questions — vector and clay do,
    under the shared ids — or brings its own list entirely. sculpt brings its
    own, because its eight are idiom-states rather than answers to anything,
    and filing them under the shared ids would claim a correspondence that is
    not there.
    """
    listing = STYLES[style].get("samples") or SAMPLES
    return [{"id": sample_id_for(base_id, style), "base_id": base_id,
             "style": style, "size": FRAME, "api_size": API_PORTRAIT,
             "prompt": prompt_for(scene_for(base_id, scene, style), style,
                                  base_id)}
            for base_id, scene in listing]


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

# --- the totem band ----------------------------------------------------------
#
# A totem is not a quiz card and cannot be measured like one. Three draws under
# the totem block came back at luma 20-25 against a floor of 90 and were all
# rejected — which is the floor working exactly as designed and measuring the
# wrong thing, because the block deliberately asks for a dark room and the quiz
# floor exists to catch a frame that came back dark by accident.
#
# So the numbers below are reasoned from what a correct totem is made of
# rather than from the failures. PIL's "L" is 601-2 luma and its HSV "S" is
# (max-min)/max, and against those:
#
#   the umbra backdrop  #241A10  is luma  27.8, sat 141.7
#   lit terracotta      #B4643C  is luma 119.4, sat 170.0
#   a teal core         #4EDDC4  is luma 175.4, sat 165.0
#
# A frame that is backdrop, a lit clay form and a glowing core — in the
# proportions the safe-area rule allows, which is a form filling something
# like a quarter to a third of the frame — lands between luma 50 and 95, and
# sits around sat 140-150 whichever way the mix goes.
#
# Two things follow, and they are the two bounds.

# Below this the frame has gone blacker than its own backdrop colour, which
# means there is no lit form in it: a glow floating in the dark, which is the
# failure the block's own language is written against. Pure umbra with nothing
# on it measures 27.8, and the darkest composition that still reads as a lit
# object measures about 50, so the line goes between them with room on both
# sides. It is emphatically not the quiz floor lowered — a quiz card at 38
# would be a broken quiz card.
TOTEM_MIN_MEAN_LUMA = 38.0

# And an upper bound on colour, which no other frame class has. Saturation
# rises both when the teal goes neon and when the frame goes near-black — a
# dark warm pixel is nearly pure hue — so one number catches the two ways this
# block fails. Correct renders measure 140-150 and a teal-heavy one might
# reach 200; the owner's read on the rejected draws was that 240 and above is
# the teal drowning the clay. The line sits just under that, which leaves
# every correct render a wide margin and still catches the neon.
TOTEM_MAX_SATURATION = 235.0


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


def floor_for(style=DEFAULT_STYLE, base_id=None):
    """The band this frame is judged against, as a dict.

    Keyed by frame class rather than by style, because the thing that decides
    what a correct exposure looks like is what the frame is FOR. Every quiz
    card in every style is a subject on a light ground and shares one band.
    A totem is a lit object in a dark room and needs its own — and it is the
    only frame class that does, which is why this is a branch and not a table
    with one row per id.
    """
    band = {
        "min_luma": MIN_MEAN_LUMA,
        "max_luma": MAX_MEAN_LUMA,
        "min_sd": MIN_STDDEV,
        "min_sat": min_saturation(style),
        "max_sat": None,
    }
    if style == "sculpt" and base_id in TOTEM_IDS:
        band["min_luma"] = TOTEM_MIN_MEAN_LUMA
        band["max_sat"] = TOTEM_MAX_SATURATION
    return band


def sanity(stats, style=DEFAULT_STYLE, base_id=None):
    """`(ok, note)` for a measured frame. Never raises.

    Loose on purpose: it rejects near-black, blank and colourless renders and
    passes everything else, because the owner review is the real gate and this
    batch exists to be looked at. A totem is judged on its own band — see
    `floor_for` — and the note prints the numbers either way, so a rejection
    can be read against the thresholds without rerunning anything.
    """
    if stats is None:
        # A frame is never lost to the checker. If it cannot be measured it is
        # kept and the note says so — it is going in front of a human anyway.
        return True, "unmeasured"
    mean, sd, sat = stats
    band = floor_for(style, base_id)
    ok = (band["min_luma"] <= mean <= band["max_luma"]
          and sd >= band["min_sd"] and sat >= band["min_sat"]
          and (band["max_sat"] is None or sat <= band["max_sat"]))
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
            ok, note = sanity(measure(img), frame["style"],
                              frame["base_id"])
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
