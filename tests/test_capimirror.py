#!/usr/bin/env python3
"""The pixel events' server-side twins: same id on both sides, nothing else.

PageView, Lead, InitiateCheckout and AddPaymentInfo fire in the browser with
an eventID engine.js made up, and the tracking POST of the same moment
carries that id as `pixel_event_id`. tracking.py hands a twin to Meta under
the same id, off the request. What this holds:

  - the browser side: every one of the four fbq calls passes an eventID, the
    same id rides on the matching tracking event, and one event never has
    two ids — PageView's is made once at boot and read by both sides;
  - the server side: the twin carries the standard name, the pixel's id, the
    dedup fields Meta needs, the session id hashed as fbevents.js hashes it,
    the address, the user agent and the click cookies — and no email, no
    value, nothing persisted;
  - the bot guard: PageView is mirrored only off a tracking POST carrying
    both the pixel id and a session id, never off anything else;
  - the discipline: one attempt, a two-second deadline, failures at debug,
    and a tracking response that comes back 204 while Meta is still hanging;
  - the modes: a test-mode funnel's twin goes to the Test Events tab or
    nowhere, and a live funnel's carries the test code only when the
    Purchase sender would too.

No database, no network, no key: the row is captured, Meta is a stub.

    python3 tests/test_capimirror.py
"""
import hashlib
import json
import os
import re
import sys
import threading
import time
import types
import uuid

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, REPO)

import config                                              # noqa: E402
import database                                            # noqa: E402
import payments                                            # noqa: E402
import tracking                                            # noqa: E402
from app import app                                        # noqa: E402

fails = []
checks = [0]


def check(label, ok, detail=""):
    checks[0] += 1
    if not ok:
        fails.append("%s %s" % (label, detail))
    print("  %-62s %s%s" % (label, "ok" if ok else "FAIL",
                            ("  " + str(detail)) if detail and not ok else ""))


ENGINE = open(os.path.join(REPO, "static/js/engine.js"),
              encoding="utf-8").read()
SESSION = "3f1c2a7e-9b4d-4c1e-8a2f-5d6e7f8a9b0c"
FBP = "fb.1.1700000000000.1234567890"
FBC = "fb.1.1700000000000.AbCdEfGh"
SLUG = "zodiac-bg"
TWIN = "zodiac-bg-test"
UA = "Mozilla/5.0 (iPhone; CPU iPhone OS 17_0 like Mac OS X) Safari/604.1"
IP = "203.0.113.9"
MIRRORED = [("funnel_start", "PageView"), ("result_view", "Lead"),
            ("paywall_view", "InitiateCheckout"),
            ("paywall_open", "InitiateCheckout"),
            ("pay_tap", "AddPaymentInfo")]
EXTRA = {"paywall_view": {"src": "scroll"}, "pay_tap": {"method": "redirect"}}


print("\n--- the browser side, read off engine.js ---")
check("every fbq track call passes an eventID",
      "fbq()(\"track\", name, {}, { eventID: id })" in ENGINE
      and not re.search(r'fbq\(\)\("track", name\);', ENGINE))
# AddToCart is the visualizer's upload event, outside the four: it gets an
# id the same way but no twin, so it may still be called by name alone.
bare = re.findall(r'pixelTrack\("(\w+)"\)', ENGINE)
check("  and none of the four is fired without an explicit id",
      bare == ["AddToCart"], str(bare))
for name in ("PageView", "Lead", "InitiateCheckout", "AddPaymentInfo"):
    check("  %-16s fires under pixelEventId" % name,
          re.search(r'pixelTrack\("%s", (?:pixelEventId\("%s"\)|\w+)\)'
                    % (name, name), ENGINE) is not None)
check("the tracking POST carries the id and the click cookies with it",
      "body.pixel_event_id = pixelId;" in ENGINE
      and "var ids = metaIds();\n      for (var m in ids) body[m] = ids[m];"
      in ENGINE)
check("  PageView's id is made once, at boot, and both sides read it",
      'track("funnel_start", null, null, pixelEventId("PageView"));' in ENGINE
      and 'pixelTrack("PageView", pixelEventId("PageView"));' in ENGINE
      and "if (pixelIds[name]) return pixelIds[name];" in ENGINE)
check("  Lead's id rides on result_view, the same variable on both calls",
      'var lead = pixelEventId("Lead");\n    track("result_view", null, null, '
      'lead);\n    pixelTrack("Lead", lead);' in ENGINE)
check("  InitiateCheckout fires once a load, from either path, and only the "
      "path that fired it carries the id",
      ENGINE.count("fireCheckoutPixel()") == 3
      and 'track("paywall_view", null, { src: payIntent }, fireCheckoutPixel());'
      in ENGINE
      and 'track("paywall_open", null, null, fireCheckoutPixel());' in ENGINE
      and "if (pixelCheckoutFired) return null;" in ENGINE
      and ENGINE.count('pixelTrack("InitiateCheckout"') == 1)
check("  AddPaymentInfo the same, on the redirect and the wallet tap",
      'track("pay_tap", null, { method: "redirect" }, payPixel);' in ENGINE
      and 'track("pay_tap", null, { method: "wallet" }, firePayPixel());'
      in ENGINE
      and "if (pixelPayFired) return null;" in ENGINE
      and ENGINE.count('pixelTrack("AddPaymentInfo"') == 1)
check("  the three conversion ids survive a reload; PageView's does not",
      'var EVENT_ID_KEY = "mazzin_evid";' in ENGINE
      and ENGINE.count('if (name !== "PageView")') == 2
      and "sessionStorage.setItem(EVENT_ID_KEY" in ENGINE)
check("  an id queued before the pixel loads keeps its id",
      "pixelQueue.push({ name: name, id: id })" in ENGINE
      and "queued.forEach(function (q) { pixelTrack(q.name, q.id); });"
      in ENGINE)
check("  and the fbq init still declares only the session id",
      re.search(r'window\.fbq\("init", id, sessionId \? \{ external_id: '
                r'sessionId \} : \{\}\);', ENGINE) is not None)


# --- the rig ---------------------------------------------------------------

class Rig:
    """Meta stubbed, the row captured, the thread optional."""

    def __init__(self, inline=True, hang=None, status=200, raise_exc=None):
        self.posts = []
        self.rows = []
        self.logs = []
        self.hang = hang
        self.status = status
        self.raise_exc = raise_exc
        self.inline = inline

    def __enter__(self):
        self.real = (database.execute, payments.mode_override,
                     config.META_PIXEL_ID, config.META_CAPI_TOKEN,
                     config.META_TEST_EVENT_CODE, tracking._spawn,
                     payments.log, sys.modules.get("requests"))
        rig = self

        def execute(sql, params=None):
            rig.rows.append((sql, params))
            return 1

        database.execute = execute
        tracking.database.execute = execute
        payments.mode_override = lambda slug: None
        config.META_PIXEL_ID = "111222333"
        config.META_CAPI_TOKEN = "tok_notreal"
        config.META_TEST_EVENT_CODE = ""
        if self.inline:
            tracking._spawn = lambda target, **kw: target(**kw)

        def post(url, json=None, params=None, timeout=None):
            rig.posts.append({"url": url, "json": json, "params": params,
                              "timeout": timeout})
            if rig.hang:
                rig.hang.wait(5)
            if rig.raise_exc:
                raise rig.raise_exc
            return types.SimpleNamespace(status_code=rig.status)

        stub = types.ModuleType("requests")
        stub.post = post
        sys.modules["requests"] = stub

        class Recorder:
            def _at(level):
                def keep(self, template, *args):
                    rig.logs.append((level, str(template)
                                     % args if args else str(template)))
                return keep
            debug = _at("debug")
            info = _at("info")
            warning = _at("warning")
            error = _at("error")
            exception = _at("exception")

        payments.log = Recorder()
        return self

    def __exit__(self, *a):
        (database.execute, payments.mode_override, config.META_PIXEL_ID,
         config.META_CAPI_TOKEN, config.META_TEST_EVENT_CODE, tracking._spawn,
         payments.log, real_requests) = self.real
        tracking.database.execute = database.execute
        if real_requests is None:
            sys.modules.pop("requests", None)
        else:
            sys.modules["requests"] = real_requests


def post_track(client, body, headers=None):
    head = {"User-Agent": UA, "CF-Connecting-IP": IP}
    head.update(headers or {})
    return client.post("/api/track", data=json.dumps(body),
                       content_type="application/json", headers=head)


def body_for(event, slug=SLUG, event_id=None, session=SESSION, ids=True):
    out = {"funnel": slug, "event": event}
    if session:
        out["session_id"] = session
    if event in EXTRA:
        out["extra"] = EXTRA[event]
    if event_id:
        out["pixel_event_id"] = event_id
    if ids:
        out["fbp"] = FBP
        out["fbc"] = FBC
    return out


print("\n--- each mirrored event: one twin, the pixel's id, the dedup fields ---")
with app.test_client() as client:
    for event, name in MIRRORED:
        eid = str(uuid.uuid4())
        with Rig() as rig:
            r = post_track(client, body_for(event, event_id=eid))
            check("%-13s -> %-16s answered 204 and sent one twin"
                  % (event, name), r.status_code == 204 and len(rig.posts) == 1,
                  "%s, %d posts" % (r.status_code, len(rig.posts)))
            if not rig.posts:
                continue
            sent = rig.posts[0]
            data = sent["json"]["data"][0]
            check("  event_name %s, event_id is the pixel's, action_source "
                  "website" % name,
                  data["event_name"] == name and data["event_id"] == eid
                  and data["action_source"] == "website"
                  and len(sent["json"]["data"]) == 1)
            check("  event_source_url is the funnel page, event_time now",
                  data["event_source_url"] == "%s/%s" % (config.BASE_URL, SLUG)
                  and abs(data["event_time"] - int(time.time())) < 5)
            ud = data["user_data"]
            check("  external_id is the session id, hashed as fbevents.js "
                  "hashes it",
                  ud["external_id"]
                  == hashlib.sha256(SESSION.encode()).hexdigest()
                  and ud["external_id"] == payments._sha256(SESSION))
            check("  the address and the user agent, in the clear, as the "
                  "spec takes them",
                  ud["client_ip_address"] == IP and ud["client_user_agent"] == UA)
            check("  fbp and fbc as the browser had them",
                  ud["fbp"] == FBP and ud["fbc"] == FBC)
            check("  and nothing else: no email, no value, no test code",
                  set(ud) == {"external_id", "client_ip_address",
                              "client_user_agent", "fbp", "fbc"}
                  and "custom_data" not in data
                  and "test_event_code" not in sent["json"])
            check("  to the same endpoint with the same token as Purchase",
                  sent["url"] == payments._capi_url()
                  and sent["params"] == {"access_token": "tok_notreal"})
            check("  one attempt, two seconds at most",
                  sent["timeout"] == payments.MIRROR_TIMEOUT_S
                  and payments.MIRROR_TIMEOUT_S <= 2.0)
            check("  the row is what it was: the pixel id is not persisted",
                  len(rig.rows) == 1
                  and not any(eid in str(p) for p in rig.rows[0][1])
                  and not any(FBP in str(p) for p in rig.rows[0][1]))
            check("  and the outcome is a debug line, not a warning",
                  rig.logs and all(level == "debug" for level, _ in rig.logs)
                  and not any(eid in line or SESSION in line
                              for _, line in rig.logs))

    print("\n--- the bot guard: PageView only off a JS-made POST ---")
    with Rig() as rig:
        r = post_track(client, body_for("funnel_start"))
        check("funnel_start without a pixel id records itself and mirrors "
              "nothing", r.status_code == 204 and not rig.posts
              and len(rig.rows) == 1)
    with Rig() as rig:
        r = post_track(client, body_for("funnel_start",
                                        event_id=str(uuid.uuid4()),
                                        session=None))
        check("  without a session id the POST is refused outright",
              r.status_code == 400 and not rig.posts and not rig.rows)
    with Rig() as rig:
        r = post_track(client, body_for("funnel_start", event_id="not-a-uuid"))
        check("  a malformed pixel id drops the twin and keeps the row",
              r.status_code == 204 and not rig.posts and len(rig.rows) == 1)
    with Rig() as rig:
        r2 = client.get("/%s" % SLUG, headers={"User-Agent": "curl/8.0"})
        r3 = client.post("/api/track", data="not json",
                         content_type="application/json",
                         headers={"User-Agent": "curl/8.0"})
        check("  a page hit and a raw POST send nothing",
              r2.status_code == 200 and not rig.posts and r3.status_code == 400)
    first = json.load(open(os.path.join(REPO, "funnels", SLUG + ".json"),
                           encoding="utf-8"))["swipe"]["steps"][0]
    shown = [i["id"] for i in first["pairs"][0]["images"]]
    with Rig() as rig:
        r = post_track(client, {"funnel": SLUG, "session_id": SESSION,
                                "event": "swipe", "step": 1,
                                "pixel_event_id": str(uuid.uuid4()),
                                "extra": {"pair": "%s:%s" % (
                                    first["id"], first["pairs"][0]["id"]),
                                          "shown": shown,
                                          "chosen": shown[0]}})
        check("  an event that has no pixel twin is never mirrored, id or not",
              r.status_code == 204 and not rig.posts)
    with Rig() as rig:
        r = post_track(client, body_for("result_view",
                                        event_id=str(uuid.uuid4()),
                                        ids=False))
        ud = rig.posts[0]["json"]["data"][0]["user_data"] if rig.posts else {}
        check("a twin without click cookies still goes, on the session id",
              r.status_code == 204 and len(rig.posts) == 1
              and "fbp" not in ud and "fbc" not in ud
              and ud.get("external_id") == payments._sha256(SESSION))
    with Rig() as rig:
        bad = body_for("result_view", event_id=str(uuid.uuid4()))
        bad["fbp"] = "not a cookie; drop table"
        r = post_track(client, bad)
        ud = rig.posts[0]["json"]["data"][0]["user_data"] if rig.posts else {}
        check("  and a click id that is not one is dropped, as at checkout",
              r.status_code == 204 and "fbp" not in ud and ud.get("fbc") == FBC)

    print("\n--- a Meta outage costs the tracking response nothing ---")
    gate = threading.Event()
    with Rig(inline=False, hang=gate) as rig:
        started = time.monotonic()
        r = post_track(client, body_for("result_view",
                                        event_id=str(uuid.uuid4())))
        elapsed = time.monotonic() - started
        time.sleep(0.2)
        check("the response is 204 and back in well under a second while "
              "Meta hangs (%.0f ms)" % (elapsed * 1000),
              r.status_code == 204 and elapsed < 0.75
              and len(rig.posts) == 1 and len(rig.rows) == 1)
        gate.set()
        time.sleep(0.2)
    with Rig(raise_exc=TimeoutError("read timed out")) as rig:
        r = post_track(client, body_for("result_view",
                                        event_id=str(uuid.uuid4())))
        check("a timeout is swallowed: 204, one attempt, a debug line naming "
              "the class only",
              r.status_code == 204 and len(rig.posts) == 1
              and [lvl for lvl, _ in rig.logs] == ["debug"]
              and "TimeoutError" in rig.logs[0][1])
    with Rig(status=400) as rig:
        r = post_track(client, body_for("result_view",
                                        event_id=str(uuid.uuid4())))
        check("  and a rejection too: 204, one attempt, debug",
              r.status_code == 204 and len(rig.posts) == 1
              and [lvl for lvl, _ in rig.logs] == ["debug"]
              and "HTTP 400" in rig.logs[0][1])
    check("  the sender is handed to a daemon thread, like the visualizer's "
          "work",
          "threading.Thread(target=target, kwargs=kwargs, daemon=True)"
          in open(os.path.join(REPO, "tracking.py"), encoding="utf-8").read())
    with Rig() as rig:
        config.META_PIXEL_ID = ""
        r = post_track(client, body_for("result_view",
                                        event_id=str(uuid.uuid4())))
        check("no pixel configured, no twin, and the row still written",
              r.status_code == 204 and not rig.posts and len(rig.rows) == 1)

    print("\n--- live and test, the way Purchase tells them apart ---")
    with Rig() as rig:
        r = post_track(client, body_for("result_view", slug=TWIN,
                                        event_id=str(uuid.uuid4())))
        check("a test-mode twin funnel with no test event code sends nothing",
              r.status_code == 204 and not rig.posts and len(rig.rows) == 1
              and any("test-mode funnel" in line for _, line in rig.logs))
    with Rig() as rig:
        config.META_TEST_EVENT_CODE = "TEST4242"
        r = post_track(client, body_for("result_view", slug=TWIN,
                                        event_id=str(uuid.uuid4())))
        check("  with one, its twin goes to the Test Events tab",
              r.status_code == 204 and len(rig.posts) == 1
              and rig.posts[0]["json"]["test_event_code"] == "TEST4242"
              and rig.posts[0]["json"]["data"][0]["event_source_url"]
              .endswith("/" + TWIN))
    with Rig() as rig:
        payments.mode_override = lambda slug: "test" if slug == SLUG else None
        r = post_track(client, body_for("result_view",
                                        event_id=str(uuid.uuid4())))
        check("  an override pinning a live funnel to test is honoured too",
              r.status_code == 204 and not rig.posts)
    with Rig() as rig:
        config.META_TEST_EVENT_CODE = "TEST4242"
        r = post_track(client, body_for("result_view",
                                        event_id=str(uuid.uuid4())))
        check("a live funnel passes the test code through only when it is "
              "set — exactly as Purchase does",
              rig.posts and rig.posts[0]["json"]["test_event_code"] == "TEST4242")
    with Rig() as rig:
        r = post_track(client, body_for("result_view",
                                        event_id=str(uuid.uuid4())))
        check("  and carries none when it is not",
              rig.posts and "test_event_code" not in rig.posts[0]["json"])
    check("  the Purchase sender's own code is untouched",
          'payload["test_event_code"] = config.META_TEST_EVENT_CODE'
          in open(os.path.join(REPO, "payments.py"), encoding="utf-8").read()
          and "def send_purchase_event(purchase_id, slug, amount_cents, "
          "currency," in open(os.path.join(REPO, "payments.py"),
                              encoding="utf-8").read())

print("\n%d checks, %d failed" % (checks[0], len(fails)))
for f in fails:
    print("  FAIL " + f)
sys.exit(1 if fails else 0)
