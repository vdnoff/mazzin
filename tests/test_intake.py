#!/usr/bin/env python3
"""What reaches disk when somebody uploads a photograph of their kitchen.

The privacy claim is the one worth testing properly. "We strip EXIF" has to
mean the bytes on disk contain none of it — not that PIL was asked nicely — so
the fixtures here carry real GPS coordinates and a real device serial, and the
output is both re-opened and searched as raw bytes.

The orientation half matters just as much and fails silently: a phone stores
the photo unrotated with a tag saying which way is up, so dropping the tag
without acting on it first turns every portrait kitchen sideways.

    python3 intake.py
"""
import io
import os
import sys

# The repo root, derived from this file rather than hardcoded: a suite
# that only runs from one absolute path is a suite that stops running the
# first time the checkout moves.
REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

sys.path.insert(0, REPO)

import config                      # noqa: E402
import visualizer                  # noqa: E402
from PIL import Image              # noqa: E402
from PIL.ExifTags import IFD       # noqa: E402

SERIAL = b"SERIAL-12345"
MAKE = b"FakePhone"

fails = []
checks = [0]


def check(label, ok, detail=""):
    checks[0] += 1
    if not ok:
        fails.append("%s %s" % (label, detail))
    print("  %-62s %s%s" % (label, "ok" if ok else "FAIL",
                            ("  " + str(detail)) if not ok else ""))


def phone_exif(orientation=1):
    """The metadata a phone actually attaches — GPS, serial, orientation."""
    tags = Image.Exif()
    tags[271] = MAKE.decode()
    tags[272] = "Model X"
    tags[274] = orientation
    tags[306] = "2026:08:14 10:00:00"
    tags.get_ifd(IFD.Exif)[42033] = SERIAL.decode()
    gps = tags.get_ifd(IFD.GPSInfo)
    gps[1], gps[2] = "N", (51.0, 30.0, 0.0)
    gps[3], gps[4] = "W", (0.0, 7.0, 0.0)
    return tags


def canvas(size=(1200, 800), colour=(200, 120, 60)):
    img = Image.new("RGB", size, colour)
    # A recognisable corner, so a rotation is something we can actually see
    # rather than something we take the size's word for.
    for x in range(size[0] // 6):
        for y in range(size[1] // 6):
            img.putpixel((x, y), (0, 0, 255))
    return img


def photo(size=(1200, 800), fmt="JPEG", exif=True, orientation=1):
    """A picture that looks like it came off a phone."""
    img = canvas(size)
    out = io.BytesIO()
    if exif and fmt in ("JPEG", "HEIF", "MPO"):
        img.save(out, fmt, exif=phone_exif(orientation).tobytes())
    else:
        img.save(out, fmt)
    return out.getvalue()


def heic(size=(1200, 800), orientation=1):
    """What an iPhone camera writes. Needs the plugin to be registered."""
    visualizer.register_image_formats()
    out = io.BytesIO()
    canvas(size).save(out, "HEIF", exif=phone_exif(orientation).tobytes())
    return out.getvalue()


def mpo(size=(1200, 800), orientation=1):
    """What a portrait or burst shot arrives as: several JPEGs in one file.

    Frame 0 is the photograph. The second frame is a different colour on
    purpose, so "we took frame 0" is something the pixels can prove rather
    than something the frame count implies.
    """
    out = io.BytesIO()
    canvas(size).save(out, "MPO",
                      append_images=[canvas(size, (60, 90, 200))],
                      exif=phone_exif(orientation).tobytes())
    return out.getvalue()


def refused(raw):
    """(code, message) for a photo we will not take, or None if accepted."""
    try:
        visualizer.normalise(raw)
    except visualizer.IntakeError as exc:
        return exc.code, exc.message
    return None


def main():
    print("\n--- the fixture really does carry what we claim to strip ---")
    raw = photo()
    check("it has GPS, a serial and a make in it",
          SERIAL in raw and MAKE in raw)
    check("  and an orientation tag PIL can read",
          Image.open(io.BytesIO(raw)).getexif().get(274) == 1)

    print("\n--- and none of it survives ---")
    out = visualizer.normalise(raw)
    check("the device serial is gone from the bytes", SERIAL not in out)
    check("the make is gone from the bytes", MAKE not in out)
    kept = Image.open(io.BytesIO(out))
    check("there is no EXIF block left at all", not dict(kept.getexif()),
          dict(kept.getexif()))
    check("  no GPS sub-IFD either",
          not dict(kept.getexif().get_ifd(IFD.GPSInfo)))
    check("what comes out is a JPEG", kept.format == "JPEG", kept.format)

    print("\n--- a sideways photo is stood up, not just untagged ---")
    # Orientation 6 means "rotate 90° clockwise to view". A 1200x800 stored
    # image is therefore an 800x1200 photograph, and the blue corner moves.
    turned = visualizer.normalise(photo(orientation=6))
    img = Image.open(io.BytesIO(turned))
    check("the tall photo comes out tall", img.size[0] < img.size[1], img.size)
    check("  with nothing left to rotate it a second time",
          not dict(img.getexif()))
    straight = Image.open(io.BytesIO(visualizer.normalise(photo())))
    check("an upright photo is left alone", straight.size[0] > straight.size[1],
          straight.size)

    print("\n--- downscaling ---")
    big = Image.open(io.BytesIO(visualizer.normalise(photo((4032, 3024)))))
    check("a 12MP phone photo is brought down to the long edge",
          max(big.size) == config.VISUALIZER_MAX_EDGE, big.size)
    check("  keeping its aspect ratio",
          abs(big.size[0] / float(big.size[1]) - 4032 / 3024.0) < 0.01,
          big.size)
    small = Image.open(io.BytesIO(visualizer.normalise(photo((400, 300)))))
    check("a small photo is not upscaled", small.size == (400, 300), small.size)

    print("\n--- HEIC, which is what an iPhone camera actually writes ---")
    raw = heic()
    check("the plugin is registered and the fixture is really HEIF",
          Image.open(io.BytesIO(raw)).format == "HEIF",
          Image.open(io.BytesIO(raw)).format)
    check("  carrying the metadata a phone attaches", SERIAL in raw)
    out = visualizer.normalise(raw)
    kept = Image.open(io.BytesIO(out))
    check("it is accepted", kept.format == "JPEG", kept.format)
    check("  and comes out as a plain JPEG with no EXIF",
          not dict(kept.getexif()), dict(kept.getexif()))
    check("  the serial does not survive", SERIAL not in out)

    # Who rotates is different for HEIC than for everything else, and getting
    # it wrong turns every iPhone photo on its side without changing a single
    # test that only looks at sizes. The invariant is not "normalise rotates"
    # — it is "the photo ends upright, exactly once".
    #
    # HEIC: libheif applies the container's rotation while decoding and
    # pillow-heif resets the EXIF tag to 1, so the picture is already upright
    # when we get it and normalise must add nothing.
    for turn in (1, 6):
        raw = heic(orientation=turn)
        decoded = Image.open(io.BytesIO(raw))
        out = Image.open(io.BytesIO(visualizer.normalise(raw)))
        check("HEIC at orientation %d arrives already upright" % turn,
              decoded.getexif().get(274) in (None, 1),
              decoded.getexif().get(274))
        check("  so normalise rotates it no further",
              out.size == decoded.size, (decoded.size, out.size))

    # JPEG and MPO: the decoder hands back unrotated pixels and a live tag, so
    # here normalise is the thing that stands the photo up.
    for build, name in ((photo, "JPEG"), (mpo, "MPO")):
        raw = build(orientation=6)
        decoded = Image.open(io.BytesIO(raw))
        out = Image.open(io.BytesIO(visualizer.normalise(raw)))
        check("a sideways %s still carries a live tag" % name,
              decoded.getexif().get(274) == 6, decoded.getexif().get(274))
        check("  and normalise is what stands it up",
              out.size == (decoded.size[1], decoded.size[0]),
              (decoded.size, out.size))

    print("\n--- MPO, which is what a portrait or burst shot arrives as ---")
    raw = mpo()
    probe = Image.open(io.BytesIO(raw))
    check("the fixture is a real multi-frame MPO",
          probe.format == "MPO" and probe.n_frames == 2,
          (probe.format, getattr(probe, "n_frames", 1)))
    check("  and it still carries an unapplied orientation tag, unlike HEIC",
          probe.getexif().get(274) == 1, probe.getexif().get(274))
    out = visualizer.normalise(raw)
    kept = Image.open(io.BytesIO(out))
    check("it is accepted as a single-frame JPEG",
          kept.format == "JPEG" and getattr(kept, "n_frames", 1) == 1,
          (kept.format, getattr(kept, "n_frames", 1)))
    # Frame 0 is orange and frame 1 is blue, so which one we kept is a fact
    # about the pixels rather than about the frame count.
    check("  and it is frame 0 — the photograph, not the depth frame",
          kept.getpixel((kept.size[0] - 5, kept.size[1] - 5))[0] > 150,
          kept.getpixel((kept.size[0] - 5, kept.size[1] - 5)))
    check("  keeping every frame but the first out of the result",
          getattr(Image.open(io.BytesIO(out)), "n_frames", 1) == 1)

    print("\n--- the bytes decide, not the name or the type ---")
    check("a WEBP with a .bin name and no type at all is still a photo",
          refused(photo(fmt="WEBP", exif=False)) is None,
          refused(photo(fmt="WEBP", exif=False)))
    check("  and comes out as JPEG like everything else",
          Image.open(io.BytesIO(visualizer.normalise(
              photo(fmt="WEBP", exif=False)))).format == "JPEG")
    check("a HEIC calling itself IMG_0001.JPG is opened as HEIC",
          refused(heic()) is None)
    check("a GIF is no longer refused for not being on a list",
          refused(photo(fmt="GIF", exif=False)) is None,
          refused(photo(fmt="GIF", exif=False)))
    check("a TIFF either", refused(photo(fmt="TIFF", exif=False)) is None,
          refused(photo(fmt="TIFF", exif=False)))
    check("a BMP either", refused(photo(fmt="BMP", exif=False)) is None,
          refused(photo(fmt="BMP", exif=False)))

    print("\n--- what we will still not take ---")
    check("an empty body", (refused(b"") or ("",))[0] == "empty", refused(b""))
    check("a text file pretending to be a photo",
          (refused(b"this is not an image at all") or ("",))[0]
          == "not_an_image", refused(b"x" * 40))
    check("a truncated JPEG",
          (refused(photo()[:200]) or ("",))[0] == "not_an_image",
          refused(photo()[:200]))
    check("a PDF, which Pillow will not open",
          (refused(b"%PDF-1.7\n1 0 obj\n<<>>\nendobj\n") or ("",))[0]
          == "not_an_image")

    # EPS is the one thing Pillow *can* open that we refuse anyway: it does not
    # decode PostScript itself, it runs Ghostscript on the file. That is a much
    # bigger thing to point at a stranger's upload than an image decoder, and
    # no camera produces EPS.
    eps = (b"%!PS-Adobe-3.0 EPSF-3.0\n%%BoundingBox: 0 0 10 10\n"
           b"%%EndComments\nshowpage\n%%EOF\n")
    check("an EPS is refused rather than handed to Ghostscript",
          (refused(eps) or ("",))[0] in ("wrong_format", "not_an_image"),
          refused(eps))

    over = b"\xff\xd8" + b"\x00" * (config.VISUALIZER_MAX_BYTES + 1)
    code, message = refused(over)
    check("anything past the size ceiling", code == "too_large", code)
    # The ceiling moved from 8MB to 25 when a 48MP Pro sensor turned out to
    # write past it routinely, so the sentence is checked against the config
    # rather than against a number written here.
    limit = "%dMB" % (config.VISUALIZER_MAX_BYTES // (1024 * 1024))
    check("  and it says so in a sentence with the real limit in it",
          limit in message, (limit, message))

    print("\n--- and one sentence covers all of them ---")
    for label, raw in (("junk", b"nope"), ("a truncated file", photo()[:200]),
                       ("an EPS", eps)):
        check("%s is answered with the same readable line" % label,
              (refused(raw) or ("", ""))[1]
              == "We couldn't read that photo — JPEG, PNG or HEIC please.",
              (refused(raw) or ("", ""))[1])

    print("\n--- what we will take ---")
    check("a PNG, re-encoded to JPEG",
          Image.open(io.BytesIO(
              visualizer.normalise(photo(fmt="PNG", exif=False)))).format
          == "JPEG")
    check("a JPEG with no EXIF at all", refused(photo(exif=False)) is None)
    check("a photo exactly at the ceiling is not refused for size",
          (refused(b"not a jpeg" * 10) or ("",))[0] != "too_large")

    print("\n--- a decompression bomb is a memory allocation, not a kitchen ---")
    # A real one: a PNG of a flat colour compresses to almost nothing and
    # decodes to gigabytes. The header says how big it is, which is the whole
    # point — the refusal happens before a pixel is decoded.
    # Over our ceiling and deliberately under Pillow's own warning threshold,
    # so what refuses it is demonstrably our check and not a library default
    # that might move. The ceiling rose to 80MP to admit a 48MP phone, so the
    # fixture rose with it — the gap it has to land in is 80.0M to 89.5M.
    side = 9200
    bomb = io.BytesIO()
    Image.new("RGB", (side, side), (0, 0, 0)).save(bomb, "PNG")
    raw = bomb.getvalue()
    check("an %.0fMP fixture is small on disk and huge decoded"
          % (side * side / 1e6),
          len(raw) < 2_000_000 and side * side > config.VISUALIZER_MAX_PIXELS,
          (len(raw), side * side, config.VISUALIZER_MAX_PIXELS))
    check("  and under Pillow's own alarm, so our check is what catches it",
          side * side < 89_478_485, side * side)
    code, message = refused(raw) or ("", "")
    check("it is refused on its declared size", code == "too_large", code)
    check("  with something a reader can act on", "camera roll" in message,
          message)

    was = Image.MAX_IMAGE_PIXELS
    visualizer.normalise(photo())
    check("and Pillow's own global is never moved — two uploads at once "
          "would race on it", Image.MAX_IMAGE_PIXELS == was,
          Image.MAX_IMAGE_PIXELS)
    check("  not on the refused path either", refused(raw)
          and Image.MAX_IMAGE_PIXELS == was, Image.MAX_IMAGE_PIXELS)
    check("  and the ceiling is still well under Pillow's default of ~179MP",
          config.VISUALIZER_MAX_PIXELS < 178_956_970,
          config.VISUALIZER_MAX_PIXELS)
    check("  while admitting the 48MP sensor that started all this",
          8064 * 6048 < config.VISUALIZER_MAX_PIXELS,
          (8064 * 6048, config.VISUALIZER_MAX_PIXELS))

    print("\n%d checks, %d failed" % (checks[0], len(fails)))
    for f in fails:
        print("  FAIL " + f)
    return 1 if fails else 0


if __name__ == "__main__":
    raise SystemExit(main())
