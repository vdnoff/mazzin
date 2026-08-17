#!/usr/bin/env python3
"""A photograph that arrives before the money, and what becomes of it.

Three things are worth proving here and none of them is the happy path alone.

The **COGS line**: a session id gets a reader as far as putting a photo up and
looking at it. The endpoint that bills an account must be unreachable with one,
however it is dressed up.

The **migration**: a photo uploaded by a session has to end up under the
purchase when Stripe confirms it, exactly once, and the paid flow afterwards
must be the flow that already shipped.

The **collection**: almost nobody buys, so most of these files exist only to be
deleted. If that does not work, the disk fills with pictures of strangers'
kitchens.

    python3 pending.py
"""
import io
import json
import os
import shutil
import sys
import tempfile
import time

# The repo root, derived from this file rather than hardcoded: a suite
# that only runs from one absolute path is a suite that stops running the
# first time the checkout moves.
REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

sys.path.insert(0, REPO)

import config                # noqa: E402
import database              # noqa: E402
import payments              # noqa: E402
import visualizer            # noqa: E402
from PIL import Image        # noqa: E402
from app import app          # noqa: E402

SESSION = "aaaaaaaa-bbbb-4ccc-8ddd-eeeeeeeeeeee"
OTHER = "11111111-2222-4333-8444-555555555555"
UNSEEN = "99999999-8888-4777-8666-555555555555"
CS = "cs_test_prepurchase"
SLUG = "kitchen-visualizer"

fails = []
checks = [0]


def check(label, ok, detail=""):
    checks[0] += 1
    if not ok:
        fails.append("%s %s" % (label, detail))
    print("  %-64s %s%s" % (label, "ok" if ok else "FAIL",
                            ("  " + str(detail)) if not ok else ""))


def photo(size=(900, 600), colour=(190, 120, 70)):
    out = io.BytesIO()
    Image.new("RGB", size, colour).save(out, "JPEG")
    return out.getvalue()


# --- a database ------------------------------------------------------------

PURCHASES = {CS: {"id": 900, "funnel": SLUG, "status": "paid"}}

# Which sessions have actually run the funnel. The gate on pre-purchase upload
# is an events row, so this is what stands in for one.
SEEN = {(SESSION, SLUG), (OTHER, SLUG)}


class Fake:
    def __init__(self):
        self.rows = {}
        self.reset()

    def reset(self):
        self.rows = {}

    def query_one(self, sql, params=None):
        params = params or ()
        if "FROM events" in sql:
            return {"seen": 1} if (params[0], params[1]) in SEEN else None
        if "FROM purchases" in sql:
            return dict(PURCHASES[params[0]]) if params[0] in PURCHASES else None
        if "FROM visualizations" in sql:
            row = self.rows.get(params[0])
            return dict(row) if row else None
        if "FROM reports" in sql:
            return None
        raise AssertionError("unexpected query_one: " + sql[:60])

    def execute(self, sql, params=None):
        params = params or ()
        if "INSERT INTO visualizations" in sql:
            self.rows.setdefault(
                params[0], {"status": "uploaded", "generations": 0,
                            "attempts": 0, "result_n": None, "error": None,
                            "started": None})
            self.rows[params[0]].update(status="uploaded", result_n=None,
                                        error=None)
            return 1
        return 1

    def execute_rowcount(self, sql, params=None):
        return 0


DB = Fake()


def install(tmp):
    config.VISUALIZER_DIR = tmp
    for module in (visualizer,):
        module.database.query_one = DB.query_one
        module.database.execute = DB.execute
        module.database.execute_rowcount = DB.execute_rowcount
    database.query_one, database.execute = DB.query_one, DB.execute


def session_q(session=SESSION, slug=SLUG):
    return "session_id=%s&funnel=%s" % (session, slug)


def upload(client, query, raw=None, name="kitchen.jpg"):
    return client.post(
        "/api/visualizer/upload?" + query,
        data={"photo": (io.BytesIO(raw if raw is not None else photo()), name)},
        content_type="multipart/form-data")


def main():
    tmp = tempfile.mkdtemp(prefix="pending-")
    install(tmp)

    with app.test_client() as client:
        print("\n--- who may upload before paying ---")
        res = client.get("/api/visualizer/status?" + session_q())
        check("a session that ran the funnel is known", res.status_code == 200,
              res.status_code)
        check("  and has nothing yet",
              res.get_json()["status"] == "none", res.get_json())
        check("  and is told it has not paid",
              res.get_json()["paid"] is False, res.get_json())

        res = client.get("/api/visualizer/status?" + session_q(UNSEEN))
        check("a session that never ran the funnel is refused",
              res.status_code == 403, res.status_code)
        check("  which is what stops this being free disk for anyone with a "
              "UUID generator",
              res.get_json()["error"] == "unknown_session", res.get_json())

        res = client.get("/api/visualizer/status?session_id=not-a-uuid&funnel="
                         + SLUG)
        check("a session id that is not a UUID is a bad token",
              res.status_code == 400, res.status_code)
        res = client.get("/api/visualizer/status?"
                         + session_q(SESSION, "kitchen"))
        check("a funnel with no visualizer is a 404", res.status_code == 404,
              res.status_code)
        res = client.get("/api/visualizer/status?"
                         + session_q(SESSION, "../../etc/passwd"))
        check("a funnel name that is a path is a 404", res.status_code == 404,
              res.status_code)

        print("\n--- the photo goes in under the session ---")
        res = upload(client, session_q())
        check("the upload is accepted", res.status_code == 200,
              res.get_json())
        body = res.get_json()
        check("  and comes back as uploaded", body["status"] == "uploaded",
              body)
        check("  still unpaid", body["paid"] is False, body)
        stored = visualizer.pending_source(SESSION)
        check("  filed under the session, not under a purchase",
              os.path.isfile(stored) and "pending" in stored, stored)
        check("  outside static/", config.STATIC_DIR not in stored)
        check("  and normalised to a JPEG like any other",
              Image.open(stored).format == "JPEG")
        check("no visualizations row was written for somebody who has not "
              "bought anything", not DB.rows, DB.rows)

        res = client.get("/api/visualizer/image?which=source&" + session_q())
        check("they can see their own photo back", res.status_code == 200,
              res.status_code)
        check("  privately and uncached",
              "no-store" in res.headers.get("Cache-Control", ""),
              res.headers.get("Cache-Control"))
        res = client.get("/api/visualizer/image?which=source&"
                         + session_q(OTHER))
        check("another session sees nothing of theirs",
              res.status_code == 404, res.status_code)

        first = open(stored, "rb").read()
        upload(client, session_q(), photo(colour=(20, 40, 90)))
        check("re-uploading replaces rather than stacks",
              open(stored, "rb").read() != first
              and len(os.listdir(visualizer.pending_dir(SESSION))) == 1,
              os.listdir(visualizer.pending_dir(SESSION)))

        print("\n--- and the thing that costs money is not reachable ---")
        for label, query in (("a session id", session_q()),
                             ("a session id and a funnel", session_q()),
                             ("no credential at all", "")):
            res = client.post("/api/visualizer/generate?" + query)
            check("generate refuses %s" % label, res.status_code == 400,
                  (res.status_code, res.get_json()))
        check("  every refusal is the same shape, so the modes cannot be "
              "told apart by probing",
              client.post("/api/visualizer/generate?" + session_q())
              .get_json()["error"] == "bad_token")

        print("\n--- the purchase claims it ---")
        cfg = config.load_funnel(SLUG)
        moved = visualizer.claim_pending(900, SESSION, cfg)
        check("the photo moves onto the purchase", moved is True)
        check("  and is where the paid flow looks for it",
              os.path.isfile(visualizer.source_path(900)))
        check("  with nothing left behind under the session",
              not os.path.exists(visualizer.pending_dir(SESSION)))
        check("  and a row saying a photo is waiting",
              DB.rows.get(900, {}).get("status") == "uploaded", DB.rows)

        res = client.get("/api/visualizer/status?cs=" + CS)
        check("the paid page opens straight onto it",
              res.get_json()["status"] == "uploaded", res.get_json())
        check("  which is the flow that already shipped",
              res.get_json()["paid"] is True and res.get_json()["remaining"]
              == 2, res.get_json())

        print("\n--- a webhook that arrives twice ---")
        again = visualizer.claim_pending(900, SESSION, cfg)
        check("the replay moves nothing", again is False)
        check("  and the photo is still there",
              os.path.isfile(visualizer.source_path(900)))

        print("\n--- and one that has nothing to claim ---")
        check("a session that never uploaded is not an error",
              visualizer.claim_pending(901, OTHER, cfg) is False)
        check("a funnel without the feature is skipped",
              visualizer.claim_pending(902, SESSION,
                                       config.load_funnel("kitchen")) is False)
        check("a session id that is not a UUID cannot address anything",
              visualizer.claim_pending(903, "../../etc", cfg) is False)

        print("\n--- payments calls it on the way past ---")
        seen = []
        real = visualizer.claim_pending
        visualizer.claim_pending = lambda *a: seen.append(a) or True
        real_start = payments.reports.start_report
        payments.reports.start_report = lambda *a, **k: {}
        try:
            payments._record_side_effects(910, SLUG, SESSION, "modern_rustic",
                                          {})
        finally:
            visualizer.claim_pending = real
            payments.reports.start_report = real_start
        check("the webhook's side effects include claiming the photo",
              len(seen) == 1 and seen[0][0] == 910 and seen[0][1] == SESSION,
              seen)

        print("\n--- collecting what nobody bought ---")
        DB.reset()
        for name in os.listdir(os.path.join(tmp, "pending")):
            shutil.rmtree(os.path.join(tmp, "pending", name),
                          ignore_errors=True)
        upload(client, session_q())
        upload(client, session_q(OTHER))
        check("two photos are waiting",
              len(os.listdir(os.path.join(tmp, "pending"))) == 2)

        # Age one of them past the window by moving its mtime, which is what
        # the sweep reads.
        old = visualizer.pending_source(OTHER)
        stale = time.time() - config.VISUALIZER_PENDING_MAX_AGE_S - 60
        os.utime(old, (stale, stale))

        removed = visualizer.purge_pending()
        check("the old one goes", removed == 1, removed)
        check("  and the recent one stays",
              os.path.isfile(visualizer.pending_source(SESSION)))
        check("  with its directory gone too, not just the file",
              not os.path.exists(visualizer.pending_dir(OTHER)))

        check("a second sweep finds nothing to do",
              visualizer.purge_pending() == 0)
        check("re-uploading restarts the clock rather than inheriting it",
              upload(client, session_q(OTHER)).status_code == 200
              and visualizer.purge_pending() == 0)

        empty = os.path.join(tmp, "pending", "leftover-dir")
        os.makedirs(empty, exist_ok=True)
        os.utime(empty, (stale, stale))
        check("an empty directory left by a claim is aged out on its own",
              visualizer.purge_pending() == 1
              and not os.path.exists(empty))

        missing = os.path.join(tmp, "nowhere")
        config.VISUALIZER_DIR = missing
        check("a sweep with no directory at all is not an error",
              visualizer.purge_pending() == 0)
        config.VISUALIZER_DIR = tmp

        print("\n--- the sweep does not run on every upload ---")
        visualizer._last_purge[0] = 0
        calls = [0]
        real_purge = visualizer.purge_pending
        visualizer.purge_pending = lambda *a, **k: calls.append(1) or 0
        try:
            for _ in range(5):
                upload(client, session_q())
        finally:
            visualizer.purge_pending = real_purge
        check("five uploads in a row cost one sweep", len(calls) - 1 == 1,
              len(calls) - 1)

        print("\n--- the funnel decides whether any of this is on offer ---")
        block = config.load_funnel(SLUG)["visualizer"]
        check("kitchen-visualizer takes photos before the money",
              block.get("pre_purchase") is True)
        check("  and says what it costs before asking for one",
              "{price}" in block.get("price_note", ""), block.get("price_note"))
        check("  and what happens to the photo",
              "deleted if you don't continue" in block.get("privacy_note", ""))
        check("funnels/ and static/funnels/ agree",
              open(os.path.join(REPO, "funnels/kitchen-visualizer.json"),
                   "rb").read()
              == open(os.path.join(REPO, "static/funnels",
                                   "kitchen-visualizer.json"), "rb").read())

        # A funnel that offers the visualizer but has not opted into taking the
        # photo early must refuse a session upload — the key is a switch, not
        # decoration.
        real_load = config.load_funnel

        def without_pre(slug):
            data = json.loads(json.dumps(real_load(slug)))
            if "visualizer" in data:
                data["visualizer"].pop("pre_purchase", None)
            return data

        config.load_funnel = without_pre
        visualizer.config.load_funnel = without_pre
        try:
            res = client.get("/api/visualizer/status?" + session_q())
            check("without pre_purchase a session is refused",
                  res.status_code == 404, res.status_code)
            check("  and the paid path is untouched",
                  client.get("/api/visualizer/status?cs=" + CS).status_code
                  == 200)
        finally:
            config.load_funnel = real_load
            visualizer.config.load_funnel = real_load

    shutil.rmtree(tmp, ignore_errors=True)
    print("\n%d checks, %d failed" % (checks[0], len(fails)))
    for f in fails:
        print("  FAIL " + f)
    return 1 if fails else 0


if __name__ == "__main__":
    raise SystemExit(main())
