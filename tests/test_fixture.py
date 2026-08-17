#!/usr/bin/env python3
"""Render one email body and one PDF from a realistic finished report.

Nothing is sent: the Resend call is replaced with a recorder, so this exercises
the real subject line, the real template interpolation and the real PDF path
without touching the network.
"""
import json
import os
import sys

# The repo root, derived from this file rather than hardcoded: a suite
# that only runs from one absolute path is a suite that stops running the
# first time the checkout moves.
REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

sys.path.insert(0, REPO)
OUT = os.path.dirname(os.path.abspath(__file__))

import reports  # noqa: E402
import config  # noqa: E402

cfg = json.load(open(os.path.join(REPO, "funnels/kitchen.json")))

CONTENT = {
    "version": "llm-2",
    "funnel": "kitchen",
    "style_id": "modern_rustic",
    "style_name": "Modern Rustic",
    "elements": ["brass-hardware", "dark-timber", "stone-worktop",
                 "open-shelving", "statement-pendants", "oak-wood"],
    # The palette board and the two surfaces this run picked, as _visuals
    # stores them.
    "visuals": {"moodboard": "mp5", "materials": ["c4b", "b8a"]},
    "sections": [
        {"id": "palette", "title": "Your Color Palette", "data": {
            "intro": "Three colours carry this room, and the ratio between "
                     "them is what keeps it from reading as a showroom.",
            "colors": [
                {"name": "Oat Linen", "hex": "#E5DAC8", "role": "dominant",
                 "finish": "matt emulsion",
                 "where": "the cream you kept choosing, on the wall units"},
                {"name": "Weathered Oak", "hex": "#8B6F4E", "role": "secondary",
                 "finish": "hard-wax oil",
                 "where": "the smoked plank floor you picked over concrete"},
                {"name": "Burnt Clay", "hex": "#A45A34", "role": "accent",
                 "finish": "eggshell",
                 "where": "one wall behind the range, nowhere else"},
            ],
            "closing_rule": "Sixty oat, thirty oak, ten clay — and the clay "
                            "only where the light already falls.",
        }},
        {"id": "mistakes", "title": "The 5 Mistakes People With Your Style Make",
         "data": {"items": [
             {"title": "Matching every wood tone",
              "body": "Three identical oaks in one room read as laminate, "
                      "however good each one is on its own.",
              "fix": "Age one piece past the rest — the floor, usually."},
             {"title": "Buying the table last",
              "body": "The table sets the height everything else is judged "
                      "against, and it is the piece people leave to the end.",
              "fix": "Choose it before the cabinetry, not after."},
         ]}},
        {"id": "materials", "title": "Materials & Combinations", "data": {
            "intro": "Aged brass, unlacquered and satin, against smoked oak.",
            "pairs": [
                {"combo": "Smoked oak + honed dark marble", "verdict": "works",
                 "why": "The marble's cool grey is the one cold thing in the "
                        "room, which is exactly what the timber needs."},
                {"combo": "Brass + matte black together", "verdict": "avoid",
                 "why": "Two statement metals in one sightline and neither "
                        "reads as chosen."},
            ],
            "rule": "One warm metal, one cold stone, and the timber between "
                    "them.",
        }},
    ],
}


class FakePost:
    """Stands in for requests.post and keeps what would have been sent."""

    def __init__(self):
        self.payload = None

    def __call__(self, url, json=None, headers=None, timeout=None):
        self.payload = json

        class R:
            status_code = 200
        return R()


def main():
    # --- PDF ---------------------------------------------------------------
    pdf = reports.build_pdf(CONTENT)
    if not pdf:
        print("FAIL: no pdf produced")
        return 1
    path = os.path.join(OUT, "fixture-report.pdf")
    with open(path, "wb") as fh:
        fh.write(pdf)
    print("pdf: %s (%d KB)" % (path, len(pdf) // 1024))

    # --- email -------------------------------------------------------------
    import requests
    recorder = FakePost()
    real_post, requests.post = requests.post, recorder
    real_key = config.RESEND_API_KEY
    config.RESEND_API_KEY = "test-key-not-real"
    try:
        ok = reports.send_report_email("pur_fixture", "someone@example.com",
                                       CONTENT, checkout_session="cs_test_123")
    finally:
        requests.post = real_post
        config.RESEND_API_KEY = real_key

    if not ok or not recorder.payload:
        print("FAIL: email path did not complete")
        return 1

    body = recorder.payload
    print("subject: %r" % body["subject"])
    print("attachment: %s" % body["attachments"][0]["filename"])
    html_path = os.path.join(OUT, "fixture-email.html")
    with open(html_path, "w") as fh:
        fh.write(body["html"])
    print("email html: %s" % html_path)

    # --- assertions --------------------------------------------------------
    fails = []

    def check(label, ok_, detail=""):
        print("  %-52s %s%s" % (label, "ok" if ok_ else "FAIL",
                                ("  " + str(detail)) if not ok_ else ""))
        if not ok_:
            fails.append(label)

    check("subject names the style and Mazzin",
          body["subject"] == "Your Modern Rustic kitchen style report — Mazzin",
          body["subject"])
    check("logo header points at logo.svg",
          "/static/brand/logo.svg" in body["html"])
    check("congratulatory opening", "Smart move." in body["html"])
    check("names the real price from config",
          "You just spent $3 to dodge" in body["html"])
    check("says the report is attached",
          "report is attached" in body["html"])
    check("carries the result link",
          "?cs=cs_test_123" in body["html"])
    check("  and the funnel it belongs to",
          "/%s?cs=" % CONTENT["funnel"] in body["html"], body["html"][:0])
    check("footer says mazzin.com", "mazzin.com" in body["html"])
    check("no invented user counts or statistics",
          not any(w in body["html"].lower() for w in
                  ("join ", "renovators trust", "customers", "users",
                   "% of ", "rated", "reviews", "so far")),
          body["html"])
    check("pdf is a real pdf", pdf[:5] == b"%PDF-")

    # --- the link, for the two ways a purchase can be identified ----------
    #
    # The case above is the hosted one, which is the only case this suite used
    # to cover — and that gap is exactly how a broken link shipped. A wallet
    # purchase has no checkout session at all: the token is on the row, under
    # payment_intent, and the parameter is still called `cs`. Left untested,
    # three Apple Pay buyers were emailed a link back to the quiz they had
    # already finished.
    def email_with(row):
        """Send once against a purchases row, and hand back the html."""
        recorder = FakePost()
        real_post, requests.post = requests.post, recorder
        real_key = config.RESEND_API_KEY
        real_query = reports.database.query_one
        config.RESEND_API_KEY = "test-key-not-real"
        reports.database.query_one = lambda sql, params=None: row
        try:
            sent = reports.send_report_email("pur_link", "someone@example.com",
                                             CONTENT)
        finally:
            requests.post = real_post
            config.RESEND_API_KEY = real_key
            reports.database.query_one = real_query
        return sent, (recorder.payload or {}).get("html", "")

    sent, out = email_with({"checkout_session": None,
                            "payment_intent": "pi_3U5IT3P1W1DBbOcM14VE2MOU"})
    check("a wallet purchase still gets its mail", sent)
    check("  with a link built from the payment intent",
          "?cs=pi_3U5IT3P1W1DBbOcM14VE2MOU" in out,
          [l for l in out.split("\n") if "?cs=" in l][:1])
    check("  pointing at the funnel, not the site root",
          "/%s?cs=pi_" % CONTENT["funnel"] in out)
    check("  and it is offered as a link to open",
          "Open your report online" in out)

    sent, out = email_with({"checkout_session": "cs_live_row",
                            "payment_intent": "pi_ignored"})
    check("a session on the row wins over the intent",
          "?cs=cs_live_row" in out and "pi_ignored" not in out)

    sent, out = email_with({"checkout_session": None, "payment_intent": None})
    check("a purchase with neither still gets its mail", sent)
    check("  and is offered NO link rather than one to the quiz",
          "Open your report online" not in out and "?cs=" not in out,
          [l for l in out.split("\n") if "cs=" in l][:1])
    check("  with nothing left promising a link",
          "stays at that link" not in out
          and "stays available at that link" not in out)
    check("  the only anchor left is the footer",
          out.count("<a href=") == 1, out.count("<a href="))

    # Page text, not raw bytes: the content streams are compressed, so a
    # substring search over the file finds nothing whatever the page says.
    try:
        import pypdfium2 as pdfium
    except ImportError:
        print("  (pypdfium2 absent — page text not inspected)")
    else:
        doc = pdfium.PdfDocument(path)
        pages = [doc[i].get_textpage().get_text_range() for i in range(len(doc))]
        check("pdf has a cover plus body pages", len(pages) >= 2, len(pages))
        check("cover names the style", "Modern Rustic" in pages[0])
        check("cover carries no page furniture",
              "mazzin.com" not in pages[0], pages[0][:80])
        check("every body page footers mazzin.com",
              all("mazzin.com" in p for p in pages[1:]),
              [i + 2 for i, p in enumerate(pages[1:]) if "mazzin.com" not in p])

    # --- the two photographs, and what they cost --------------------------
    # A report that lands in a mailbox has a size budget as much as a look.
    # Two screen-resolution gallery webps took this from 28 KB to 1.9 MB.
    check("the pdf stays under 250 KB", len(pdf) < 250 * 1024,
          "%d KB" % (len(pdf) // 1024))
    check("and is not so small the images are missing", len(pdf) > 45 * 1024,
          "%d KB" % (len(pdf) // 1024))

    html_out = reports._pdf_html(CONTENT)
    check("the palette carries the chosen moodboard",
          'class="board"' in html_out and "img/print/mp5.jpg" in html_out,
          [l for l in html_out.split("<") if "board" in l][:1])
    check("the materials carry both chosen surfaces",
          html_out.count('class="shot"') == 2
          and "img/print/c4b.jpg" in html_out
          and "img/print/b8a.jpg" in html_out,
          html_out.count('class="shot"'))
    check("both are captioned with the label from the quiz",
          "Living wood" in html_out and "Warm texture" in html_out)
    check("every print variant it points at exists",
          all(os.path.isfile(os.path.join(config.STATIC_DIR, "img/print",
                                          i + ".jpg"))
              for i in ["mp5", "c4b", "b8a"]))

    # A report written before visuals shipped, or one whose choices never
    # reached the server, still renders — with no pictures and no holes.
    import copy as _copy
    bare = _copy.deepcopy(CONTENT)
    bare.pop("visuals", None)
    bare_pdf = reports.build_pdf(bare)
    check("a report with no visuals still renders", bool(bare_pdf))
    check("  and carries no figures", 'class="board"' not in
          reports._pdf_html(bare) and 'class="shot"' not in
          reports._pdf_html(bare))
    check("  and is smaller for it", len(bare_pdf) < len(pdf),
          (len(bare_pdf) // 1024, len(pdf) // 1024))

    # Reports generate on a thread each, and the PDF is built at the end of
    # that thread. Two purchases landing together must not be able to swap
    # photographs — a failure that would never show up in a single-file test.
    import threading
    other = _copy.deepcopy(CONTENT)
    other["style_id"] = "industrial"
    other["visuals"] = {"moodboard": "mp3", "materials": ["c4d", "b8d"]}
    out = {}

    def render(key, content):
        for _ in range(8):
            out[key] = reports._pdf_html(content)

    ts = [threading.Thread(target=render, args=k)
          for k in (("mine", CONTENT), ("theirs", other))]
    for t in ts:
        t.start()
    for t in ts:
        t.join()
    check("concurrent reports keep their own photographs",
          "print/mp5.jpg" in out["mine"] and "print/mp3.jpg" not in out["mine"]
          and "print/mp3.jpg" in out["theirs"]
          and "print/mp5.jpg" not in out["theirs"])

    print("\n%d failed" % len(fails))
    return 1 if fails else 0


if __name__ == "__main__":
    raise SystemExit(main())
