#!/usr/bin/env python3
"""Nothing in the printed report sits on top of anything else.

The section picture used to be a floated figure. In print a float does not
stay in the section that owns it: one taller than the text beside it carries
into the next, and WeasyPrint re-places it after a page break at the same
offset. So page 4 had the image over the first strength's heading and page 5
had it across the month rail, eating lines the buyer paid for.

`display: flow-root` and a clearfix did not fix it — the escape happens at the
page break rather than at the end of the block — so the float is gone and the
picture and the opening paragraph are two table cells instead.

This reads WeasyPrint's own box tree rather than rasterising: it gives the
exact rectangle of every line of text and every image, which is what an
overlap is made of, and a pixel check would have to guess where the ink came
from.

    python3 tests/test_personapdf.py
"""
import json
import os
import sys

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, REPO)

import database                                            # noqa: E402

database.execute = lambda *a, **kw: None
database.query_all = lambda *a, **kw: []
database.query_one = lambda *a, **kw: None

import config                                              # noqa: E402
import reports                                             # noqa: E402
import weasyprint                                          # noqa: E402

CFG = json.load(open(os.path.join(REPO, "funnels/persona.json"),
                     encoding="utf-8"))

fails = []
checks = [0]


def check(label, ok, detail=""):
    checks[0] += 1
    if not ok:
        fails.append("%s %s" % (label, detail))
    print("  %-62s %s%s" % (label, "ok" if ok else "FAIL",
                            ("  " + str(detail)) if not ok else ""))


# The one stack this document draws on purpose: the radar is pressed into the
# crown of the head, so the inlay is meant to sit on the plate.
DELIBERATE = frozenset([("head-base", "head-svg")])


def classes_of(box):
    try:
        element = getattr(box, "element", None)
        return (element.get("class") or "").split() if element is not None else []
    except Exception:
        return []


def marks(page):
    """Every drawn rectangle, with the chain of boxes it hangs from."""
    out = []

    def text_in(box):
        got = ""
        if type(box).__name__ == "TextBox":
            got += box.text
        for child in getattr(box, "children", []) or []:
            got += text_in(child)
        return got

    def walk(box, chain):
        name = type(box).__name__
        here = chain + [id(box)]
        if name in ("LineBox", "InlineReplacedBox", "BlockReplacedBox"):
            width = getattr(box, "width", 0) or 0
            height = getattr(box, "height", 0) or 0
            if width > 0 and height > 0:
                out.append({
                    "kind": "image" if "Replaced" in name else "text",
                    "x": box.position_x, "y": box.position_y,
                    "w": width, "h": height,
                    "cls": classes_of(box),
                    "chain": set(here),
                    "id": id(box),
                    "text": text_in(box).strip()[:44],
                })
                if "Replaced" in name:
                    return
        for child in getattr(box, "children", []) or []:
            walk(child, here)

    walk(page._page_box, [])
    return out


def collisions(page, slack=1.0):
    items = marks(page)
    bad = []
    for i in range(len(items)):
        for j in range(i + 1, len(items)):
            a, b = items[i], items[j]
            # Text lines inside one block legitimately stack tight.
            if a["kind"] == "text" and b["kind"] == "text":
                continue
            # A box and something inside it is containment, not collision:
            # the line that holds an image overlaps the image every time.
            if a["id"] in b["chain"] or b["id"] in a["chain"]:
                continue
            pair = frozenset(a["cls"] + b["cls"])
            if any(set(one) <= pair for one in DELIBERATE):
                continue
            over_x = min(a["x"] + a["w"], b["x"] + b["w"]) - max(a["x"], b["x"])
            over_y = min(a["y"] + a["h"], b["y"] + b["h"]) - max(a["y"], b["y"])
            if over_x > slack and over_y > slack:
                bad.append((round(over_x), round(over_y), a, b))
    return bad


def document():
    style = CFG["styles"][0]
    choices = [s["pairs"][0]["images"][0]["id"] for s in CFG["swipe"]["steps"]]
    scores = dict((tag, 9) for tag in style["tags"])
    scores.update({"drive": 7, "anchor": 4, "wave": 5, "prism": 2,
                   "outer": 8, "inner": 3, "bold": 5})
    content = reports.start_report(1, "persona", style["id"], scores,
                                   choices=choices)
    content["version"] = "llm-2"
    return weasyprint.HTML(string=reports._pdf_html(content),
                           base_url=config.STATIC_DIR).render()


print("--- the printed report ---")
doc = document()
check("it runs to a handful of pages", 4 <= len(doc.pages) <= 12,
      str(len(doc.pages)))

worst = []
for number, page in enumerate(doc.pages, 1):
    bad = collisions(page)
    check("  page %d draws nothing on top of anything else" % number,
          not bad,
          "; ".join("%r over %r by %dx%d" % (a["text"] or a["cls"],
                                             b["text"] or b["cls"], ox, oy)
                    for ox, oy, a, b in bad[:2]))
    worst.extend(bad)
check("no page in the document has an overlap", not worst,
      "%d in total" % len(worst))

print("\n--- and it is built so it cannot come back ---")
sheet = reports.PERSONA_PDF_CSS
check("the section picture is not a float",
      not __import__("re").search(r"\\.tap \\{[^}]*float:", sheet,
                                  __import__("re").S))
check("  it is a table cell beside the opening text",
      ".media-shot" in sheet and ".media-text" in sheet)
# FORCED TEST EDIT. `_pdf_media` is `_pdf_opening` now: the same builder,
# renamed because the box it returns holds the section heading as well as the
# picture and its opening text — the heading was being left on the page above
# and the picture opened the next one alone.
check("  and the builder puts it there",
      "def _pdf_opening(" in open(os.path.join(REPO, "reports.py"),
                                  encoding="utf-8").read())
check("the section is still its own block context",
      ".section { display: flow-root; }" in sheet)

print("\n%d checks, %d failed" % (checks[0], len(fails)))
for line in fails:
    print("  FAIL   %s" % line)
sys.exit(1 if fails else 0)
