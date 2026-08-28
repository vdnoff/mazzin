#!/usr/bin/env python3
"""Generate the persona share landing pages.

Console use only, run by hand. Nothing imports this and no route reaches it:

    cd ~/mazzin && python3 scripts/gen_persona_share_pages.py
    python3 scripts/gen_persona_share_pages.py --check   # CI: are they stale?

One page per persona, written to static/pages/persona_share/. They are what a
shared link resolves to — the thing a crawler unfurls into a card, and the
thing a human lands on before being sent into the funnel.

--- why these are files rather than a template app.py fills in -------------

Because of the rule at the top of this repo: Flask is an API, not a page
renderer. The funnel page is a file the web server hands over without a Python
worker waking up, and a share page has exactly the same properties — no
per-user state, no session, nothing to compute — so it should be the same kind
of thing. `app.py` gets one route that checks the slug against the config and
sends the file, which is routing and nothing else.

The cost of generating rather than rendering is that the files can go stale
against the config. `--check` is what pays it: it regenerates into memory and
compares, so the suite fails the moment a persona is renamed and these are not
rerun, which is the only way this drifts.

--- what the page has to do ------------------------------------------------

Two audiences, and they want opposite things. A crawler wants complete OG tags
and real markup in the first response, with no JavaScript. A human wants to be
in the funnel. So the page renders its content for the crawler, shows a real
visible link the moment it paints, and only then bounces — after a beat, in
script, with the link still sitting there for anybody the script does not run
for.

The redirect carries `subid=share-<id>` into the funnel, which is an existing
attribution column engine.js already reads off the query string and tracking.py
already stores. Share traffic is countable from the day this ships, and no
schema moved to make that true.
"""
import argparse
import html
import json
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
CONFIG = os.path.join(ROOT, "funnels", "persona.json")
OUT = os.path.join(ROOT, "static", "pages", "persona_share")

SITE = "https://mazzin.com"
FUNNEL = "/persona"

TEMPLATE = """<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>%(title)s</title>
<meta name="description" content="%(text)s">
<link rel="canonical" href="%(url)s">
<meta property="og:type" content="website">
<meta property="og:title" content="%(title)s">
<meta property="og:description" content="%(text)s">
<meta property="og:image" content="%(image)s">
<meta property="og:url" content="%(url)s">
<meta name="twitter:card" content="summary_large_image">
<meta name="twitter:title" content="%(title)s">
<meta name="twitter:description" content="%(text)s">
<meta name="twitter:image" content="%(image)s">
<style>
html,body{margin:0;padding:0;background:#241A10;color:#F3E3CC;
font-family:-apple-system,BlinkMacSystemFont,"Segoe UI",Roboto,sans-serif}
.wrap{max-width:560px;margin:0 auto;padding:48px 22px 60px;text-align:center}
img{display:block;width:100%%;height:auto;border-radius:16px;margin:0 0 26px}
h1{margin:0 0 10px;font-size:26px;line-height:1.2}
p{margin:0 0 26px;font-size:15px;line-height:1.55;color:#C2AB90}
a.cta{display:inline-block;padding:14px 26px;border-radius:999px;
font-size:15px;font-weight:700;text-decoration:none;color:#241A10;
background:linear-gradient(180deg,#7DF0DB 0%%,#4EDDC4 100%%)}
</style>
</head>
<body>
<div class="wrap">
<img src="%(image)s" alt="" width="1200" height="630">
<h1>%(title)s</h1>
<p>%(text)s</p>
<a class="cta" href="%(go)s">Find your shape</a>
</div>
<script>
/* The human's path. The link above is the crawler's and the fallback both:
   it is real markup, it works with this script blocked, and it is what the
   page is still showing while the beat runs. */
setTimeout(function () { location.replace("%(go)s"); }, 1200);
</script>
</body>
</html>
"""


def pages(cfg):
    """`{slug: html}` for every share card the config declares."""
    share = ((cfg.get("result_copy") or {}).get("profile") or {}).get("share")
    share = share or {}
    text = share.get("text") or ""
    out = {}
    for card in (cfg.get("share_cards") or []):
        slug = card["id"]
        name = card.get("persona") or slug
        out[slug] = TEMPLATE % {
            "title": html.escape("I'm %s. Which shape are you?" % name),
            "text": html.escape(text),
            "image": html.escape(SITE + card["img"]),
            "url": html.escape("%s%s%s" % (SITE, share.get("url_base") or
                                           "/persona/s/", slug)),
            "go": html.escape("%s?subid=share-%s" % (FUNNEL, slug)),
        }
    return out


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--check", action="store_true",
                    help="compare against what is on disk, write nothing")
    args = ap.parse_args(argv)

    with open(CONFIG, encoding="utf-8") as fh:
        cfg = json.load(fh)
    want = pages(cfg)

    if args.check:
        stale = []
        for slug, body in sorted(want.items()):
            path = os.path.join(OUT, slug + ".html")
            try:
                with open(path, encoding="utf-8") as fh:
                    if fh.read() != body:
                        stale.append(slug)
            except OSError:
                stale.append(slug)
        extra = []
        if os.path.isdir(OUT):
            extra = sorted(f for f in os.listdir(OUT)
                           if f.endswith(".html") and f[:-5] not in want)
        if stale or extra:
            print("stale: %s" % ", ".join(stale or ["none"]))
            print("orphaned: %s" % ", ".join(extra or ["none"]))
            return 1
        print("%d share page(s) match the config" % len(want))
        return 0

    os.makedirs(OUT, exist_ok=True)
    for slug, body in sorted(want.items()):
        with open(os.path.join(OUT, slug + ".html"), "w",
                  encoding="utf-8") as fh:
            fh.write(body)
    # A persona the config dropped leaves a page behind that still resolves
    # and still unfurls, which is a live URL for something the product no
    # longer has. Same rule as the gallery's orphan sweep.
    orphans = [f for f in os.listdir(OUT)
               if f.endswith(".html") and f[:-len(".html")] not in want]
    for name in orphans:
        os.remove(os.path.join(OUT, name))
    print("%d share page(s) written -> %s, %d orphan(s) removed"
          % (len(want), OUT, len(orphans)))
    return 0


if __name__ == "__main__":
    sys.exit(main())
