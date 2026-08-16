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


@app.get("/<slug>")
def funnel_page(slug):
    if not config.funnel_exists(slug):
        return "", 404
    resp = send_from_directory(os.path.join(config.STATIC_DIR), "funnel.html")
    resp.headers["Cache-Control"] = "public, max-age=%d" % config.FUNNEL_HTML_MAX_AGE
    return resp


if __name__ == "__main__":
    app.run(debug=True, port=5000)
