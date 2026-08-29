"""Mazzin Flask app.

Flask is the API layer only. Everything the funnel page needs — HTML, CSS,
JS, funnel config — is served straight from /static/ by the web server, so
worker time is spent on /api/* and nothing else.
"""

import logging
import os

from flask import Flask, jsonify, request, send_from_directory

import config
import database
import visualizer
from admin import bp as admin_bp
from payments import bp as payments_bp
from tracking import bp as tracking_bp
from visualizer import bp as visualizer_bp

logging.basicConfig(level=logging.INFO)

# HEIC is what an iPhone camera produces, and Pillow cannot read it without a
# plugin. Registered once here, at boot, rather than on the first upload.
#
# It is a call and not an import because `deploy.sh` deliberately does not
# install dependencies: between a deploy and a human running pip, the package
# is missing, and a bare top-level import of it would take the whole site down
# rather than degrade to refusing HEIC uploads. Same reasoning the Anthropic
# SDK is imported inside a function in reports.py.
visualizer.register_image_formats()

app = Flask(__name__, static_folder="static", static_url_path="/static")

# The outer wall on any request body. Every endpoint here took kilobytes until
# the visualizer started accepting photographs, and a request larger than the
# largest photo we would ever keep should be refused by the server before a
# worker reads it into memory. The slack over VISUALIZER_MAX_BYTES is the
# multipart envelope around the file, not extra room for the file itself —
# the per-photo limit is enforced again inside the upload route, where the
# refusal can be a sentence rather than a bare 413.
app.config["MAX_CONTENT_LENGTH"] = config.VISUALIZER_MAX_BYTES + 512 * 1024

app.register_blueprint(tracking_bp)
app.register_blueprint(payments_bp)
app.register_blueprint(visualizer_bp)
app.register_blueprint(admin_bp)


@app.errorhandler(413)
def too_large(_exc):
    """A body over the ceiling, answered in the language the caller speaks.

    This one handler is the whole of a production bug that looked like three.
    Werkzeug enforces MAX_CONTENT_LENGTH while parsing the body, which happens
    *before* any route function runs — so an oversize photograph was refused
    by the framework, the visualizer never saw it, and the server said nothing
    at all. That was the silence.

    The default answer is an HTML error page. The upload page calls
    `response.json()` on it, which throws, which lands in the catch-all branch
    with no message — and the catch-all fell back to the *generation* failure
    copy. That was the wrong sentence: "Nothing was used up — try again" shown
    to somebody whose photograph was simply too big.

    So: JSON, with an error code the page can route on, and a log line naming
    the length that did it. Everything else on the site is unaffected — no
    other endpoint here takes a body big enough to reach this.
    """
    length = request.headers.get("Content-Length") or "?"
    logging.getLogger("visualizer").info(
        "visualizer: upload refused (too_large_body) len=%s type=%s "
        "limit=%d", length, str(request.content_type)[:60],
        app.config["MAX_CONTENT_LENGTH"])
    return jsonify({
        "error": "too_large",
        "limit_bytes": config.VISUALIZER_MAX_BYTES,
    }), 413


@app.get("/health")
def health():
    try:
        database.query_one("SELECT 1 AS ok")
    except Exception:
        logging.getLogger(__name__).exception("health db check failed")
        return {"status": "db_error"}, 503
    return {"status": "ok"}


# Facade + legal pages. Static files under static/pages/, routed here only so
# the URLs stay clean. Registered before /<slug> so they win the match.
PAGES = {
    "/": "home.html",
    "/about": "about.html",
    "/terms": "terms.html",
    "/privacy": "privacy.html",
    "/refund": "refund.html",
}

# The homepage is the one page here that actually changes: an analysis goes
# live and its card has to stop saying "coming soon". Five minutes, against
# the hour the legal pages get.
HOME_HTML_MAX_AGE = 300


def _page(filename, max_age):
    resp = send_from_directory(os.path.join(config.STATIC_DIR, "pages"), filename)
    resp.headers["Cache-Control"] = "public, max-age=%d" % max_age
    return resp


for _rule, _file in PAGES.items():
    _age = HOME_HTML_MAX_AGE if _rule == "/" else config.PAGE_HTML_MAX_AGE
    app.add_url_rule(
        _rule,
        endpoint="page_" + _file.split(".")[0],
        view_func=(lambda f=_file, a=_age: _page(f, a)),
        methods=["GET"],
    )


# The share loop's landing page. A reader hands somebody their persona, that
# link unfurls into a card, and whoever taps it arrives in the funnel carrying
# `subid=share-<id>` — an attribution column engine.js already reads and
# tracking.py already stores, so the round trip is countable with no schema
# change and nothing new on the write path.
#
# Routing and nothing else, which is what keeps this file's job intact. The
# pages are files under static/pages/persona_share/, written from the config
# by scripts/gen_persona_share_pages.py and served without anything being
# rendered here; the only work done per request is checking that the slug is
# one the config actually declares, so an unknown one is a 404 rather than a
# page about a persona that does not exist.
#
# Registered before /<slug> for readability rather than necessity: this rule
# has three segments and that one has one, so they cannot collide.
PERSONA_SHARE_DIR = os.path.join(config.STATIC_DIR, "pages", "persona_share")


@app.get("/persona/s/<persona>")
def persona_share(persona):
    try:
        cards = config.load_funnel("persona").get("share_cards") or []
    except (KeyError, ValueError, OSError):
        return "", 404
    if persona not in {c.get("id") for c in cards if isinstance(c, dict)}:
        return "", 404
    resp = send_from_directory(PERSONA_SHARE_DIR, persona + ".html")
    # Nothing on this page is per-reader, so the edge can hold it for as long
    # as the legal pages: the only thing that changes it is a redeploy.
    resp.headers["Cache-Control"] = (
        "public, max-age=%d" % config.PAGE_HTML_MAX_AGE)
    return resp


@app.get("/<slug>")
def funnel_page(slug):
    # A `-test` twin is a live funnel's shape on Stripe test keys, and it sits
    # one guessable suffix away from the real URL. Gated on the server rather
    # than on a secret in the path: the flag is read here, per request, so
    # flipping it in .env and restarting is the whole of turning it off.
    #
    # The refusal is the same empty 404 an unknown slug gets — same status,
    # same body, same headers — because a 403 on /zodiac-ro-test is an answer:
    # it says the twin exists and is merely closed. This says nothing.
    if config.is_test_slug(slug) and not config.TEST_FUNNELS:
        return "", 404
    if not config.funnel_exists(slug):
        return "", 404
    resp = send_from_directory(os.path.join(config.STATIC_DIR), "funnel.html")
    if config.is_test_slug(slug):
        # Never cached, anywhere. The edge holding this page is what would
        # keep a twin answering after the flag went off, and a cache purge is
        # not a thing anybody should have to remember in that moment.
        resp.headers["Cache-Control"] = "no-store"
        resp.headers["X-Robots-Tag"] = "noindex, nofollow"
    else:
        resp.headers["Cache-Control"] = (
            "public, max-age=%d" % config.FUNNEL_HTML_MAX_AGE)
    return resp


if __name__ == "__main__":
    app.run(debug=True, port=5000)
