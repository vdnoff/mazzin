#!/usr/bin/env python3
"""The zodiac mail and the zodiac report, built from a stubbed purchase.

Both documents are assembled server-side from one report row, so neither can
be checked from the config and neither needs a browser. What is checked here
is that the dark templates are the ones a zodiac purchase reaches, that they
carry the markers a mail client needs to keep them dark, and — the half that
matters more — that kitchen's two come out byte for byte as the committed
file builds them.

No database, no Stripe, no model, no network.

    python3 tests/test_zodiacmail.py
"""
import os
import subprocess
import sys
import types

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, REPO)

import config                                              # noqa: E402
import reports                                             # noqa: E402

fails = []
checks = [0]


def check(label, ok, detail=""):
    checks[0] += 1
    if not ok:
        fails.append("%s %s" % (label, detail))
    print("  %-60s %s%s" % (label, "ok" if ok else "FAIL",
                            ("  " + str(detail)) if not ok else ""))


def offline(module):
    """No database and no model, whichever copy of reports this is."""
    module.database.execute = lambda *a, **kw: None
    module.database.query_all = lambda *a, **kw: []
    module._api = lambda: None


def run_of(module, slug, style, sign=None):
    """One stored report row, from a full run down a funnel."""
    cfg = config.load_funnel(slug)
    choices = []
    for step in cfg["swipe"]["steps"]:
        if sign and step["id"] == "sign":
            choices.append(sign)
        else:
            choices.append(step["pairs"][0]["images"][0]["id"])
    return module.start_report(1, slug, style, {"water": 9, "moon": 6},
                               choices=choices)


def mail_of(module, content, dark):
    copy = module._email_copy(content)
    name = content["style_name"]
    link = (module.ZODIAC_EMAIL_LINK if dark else module.EMAIL_LINK_BLOCK)
    fields = {
        "name": name,
        "headline": module.html.escape(copy["headline"]),
        "body": copy["body"] % module.html.escape(name),
        "link_block": link % {"link": "https://mazzin.com/x?cs=cs_1"},
        "keep": copy["keep"], "logo": "L", "home": "H",
        "opening": module._email_opening(content),
    }
    return module._email_html(dark, content, fields), fields


def main():
    offline(reports)

    print("\n--- the sign reaches the row both documents are built from ---")
    zodiac = run_of(reports, "zodiac", "deep_water", "sign_scorpio")
    check("a zodiac purchase stores the sign that was tapped",
          zodiac.get("sign") == "Scorpio", zodiac.get("sign"))
    kitchen = run_of(reports, "kitchen", "modern_rustic")
    check("  and a funnel without one stores no key",
          "sign" not in kitchen, kitchen.get("sign"))

    print("\n--- the mail a zodiac buyer opens ---")
    html, _ = mail_of(reports, zodiac, True)
    check("its ground is the result page's",
          html.count('bgcolor="#0E1430"') >= 6,
          html.count('bgcolor="#0E1430"'))
    check("  stated as an attribute, not only as CSS",
          'bgcolor="#0E1430"' in html and "background-color:#0E1430" in html)
    check("  so a light-mode client cannot lift it",
          html.count("bgcolor=") >= html.count("<td"))
    check("the gold accent is there", "#E8C878" in html)
    check("it is tables all the way down",
          html.count("<table") >= 4 and "<div" not in html)
    check("  with every style inline", "<style" not in html)
    check("  and no font anybody has to download",
          "@font-face" not in html and "fonts.googleapis" not in html
          and "Georgia" in html and "Helvetica" in html)
    check("the header is the one the page ended on",
          ">Scorpio<" in html and "× Deep Water" in html)
    # Escaped, because the titles carry ampersands and the template escapes
    # them — comparing the raw string here would be asking the mail to be
    # wrong.
    titles = [reports.html.escape(s["title"]) for s in zodiac["sections"]]
    check("every section is named on it",
          all(title in html for title in titles),
          str([t for t in titles if t not in html]))
    check("the subject names the product, not a kitchen",
          "cosmic profile" in reports._email_copy(zodiac)["subject"]
          and "kitchen" not in reports._email_copy(zodiac)["subject"])
    # An older row, or a run that somehow missed the step. The header must
    # degrade to the archetype rather than print a cross with a hole in it.
    no_sign = dict(zodiac)
    no_sign.pop("sign", None)
    bare, _ = mail_of(reports, no_sign, True)
    check("without a sign it falls back to the archetype alone",
          ">Deep Water<" in bare and "×" not in bare.split("</table>")[1],
          "")

    print("\n--- the report a zodiac buyer keeps ---")
    pdf_html = reports._pdf_html(zodiac)
    check("the page itself is dark",
          "@page { background: #0E1430; }" in pdf_html)
    check("  the cover carries the sign beside the archetype",
          "Scorpio" in pdf_html and "cover-cross" in pdf_html)
    check("  it says profile where the other says report",
          "your profile also stays available" in pdf_html)
    check("  and takes the light cut of the wordmark",
          "brand/logo-dark.svg" in pdf_html)
    # The failure this guards is invisible rather than loud: a selector the
    # base sheet paints in dark ink and the override misses renders near-black
    # on near-black and is simply gone from the page.
    INK = ("#16181d", "#3d424c", "#6b7280", "#9aa0a6")
    base = reports.PDF_CSS % reports.PDF_FONTS
    painted = []
    for block in base.split("}"):
        if "{" not in block:
            continue
        selector, body = block.rsplit("{", 1)
        if any(ink in body.lower() for ink in INK):
            painted.append(selector.strip().split("\n")[-1].strip())
    missing = [sel for sel in painted
               if sel and not sel.startswith("@")
               and sel not in reports.ZODIAC_PDF_CSS]
    check("every selector the base sheet inks dark is restated",
          not missing, str(missing))
    pdf = reports.build_pdf(zodiac)
    check("weasyprint renders it", pdf is not None and pdf[:4] == b"%PDF")
    check("  small enough to email",
          pdf is not None and len(pdf) < 3 * 1024 * 1024,
          "%d KB" % (len(pdf) // 1024) if pdf else "none")

    print("\n--- and kitchen's two are the ones it always sent ---")
    old_src = subprocess.run(["git", "show", "HEAD~4:reports.py"],
                             capture_output=True, text=True, cwd=REPO).stdout
    if not old_src:
        check("the committed file could be read", False, "git show failed")
    else:
        old = types.ModuleType("reports_before")
        old.__dict__["__name__"] = "reports_before"
        exec(compile(old_src, "reports_before", "exec"), old.__dict__)
        offline(old)
        was = run_of(old, "kitchen", "modern_rustic")
        check("its stored content is unchanged", was == kitchen)
        check("its PDF is unchanged",
              old._pdf_html(was) == reports._pdf_html(kitchen))
        now_mail, fields = mail_of(reports, kitchen, False)
        then_mail = old.EMAIL_HTML % {
            "headline": fields["headline"], "body": fields["body"],
            "link_block": fields["link_block"], "keep": fields["keep"],
            "logo": "L", "home": "H", "opening": fields["opening"]}
        check("its mail is unchanged", now_mail == then_mail)
        check("  and is still the light template",
              now_mail.startswith('<div style="font-family:-apple-system'))
        check("nothing dark leaked into it",
              "#0E1430" not in now_mail and "#E8C878" not in now_mail)

    print("\n%d checks, %d failed" % (checks[0], len(fails)))
    for line in fails:
        print("  FAIL " + line)
    return 1 if fails else 0


if __name__ == "__main__":
    sys.exit(main())
