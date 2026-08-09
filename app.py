"""Mazzin Flask app.

Flask is the API layer only. Everything the funnel page needs — HTML, CSS,
JS, funnel config — is served straight from /static/ by the web server, so
worker time is spent on /api/* and nothing else.
"""

import logging
import os

from flask import Flask, send_from_directory

import config
import database
from tracking import bp as tracking_bp

logging.basicConfig(level=logging.INFO)

app = Flask(__name__, static_folder="static", static_url_path="/static")
app.register_blueprint(tracking_bp)


@app.get("/health")
def health():
    try:
        database.query_one("SELECT 1 AS ok")
    except Exception:
        logging.getLogger(__name__).exception("health db check failed")
        return {"status": "db_error"}, 503
    return {"status": "ok"}


@app.get("/")
def index():
    return (
        "<!doctype html><html lang=\"en\"><head><meta charset=\"utf-8\">"
        "<meta name=\"viewport\" content=\"width=device-width,initial-scale=1\">"
        "<title>Mazzin</title></head><body><h1>Mazzin</h1></body></html>"
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
