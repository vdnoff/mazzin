#!/usr/bin/env python3
"""The email gate: `POST /api/lead`, the lead's report and its mail, the
worker that sends it, the tool that writes the gate into every language.

Asserted here: the route validates the address and the style and refuses
the rest with a bare 400, writes one `leads` row with the run's facts, treats
a duplicate as the same success (`lead_dup`, nothing re-sent), counts
`lead_submit` server-side with the subid, builds the article URL with the
UTM triplet and the style's anchor, and never puts the address in a log
line. The client may send `lead_view` and may not send the other two.
`reports.lead_content` builds from the cache and the stubs and writes no
row; the mail is the funnel's own copy with the style and the scale
percentages filled in and the PDF attached. The worker claims, sends and
stamps, and releases what it could not send. `set_gate.py` writes each
language's block into a funnel on disk and moves nothing else.

No database, no network, no key: every call is monkeypatched.
"""
import contextlib
import importlib.util
import io
import json
import logging
import os
import shutil
import subprocess
import sys
import tempfile

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, REPO)
sys.path.insert(0, os.path.join(REPO, "scripts"))
ROOT = REPO

import config                                   # noqa: E402
import database                                 # noqa: E402
import leads                                    # noqa: E402
import reports                                  # noqa: E402
import tracking                                 # noqa: E402
from app import app                             # noqa: E402

fails = []
checks = [0]


def check(label, ok, detail=""):
    checks[0] += 1
    if not ok:
        fails.append("%s %s" % (label, detail))
    print("  %-66s %s%s" % (label, "ok" if ok else "FAIL",
                            ("  " + str(detail)[:220]) if detail and not ok
                            else ""))


def read(rel):
    with open(os.path.join(ROOT, rel), encoding="utf-8") as fh:
        return fh.read()


def load_script(name):
    spec = importlib.util.spec_from_file_location(
        name + "_t", os.path.join(ROOT, "scripts", name + ".py"))
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


MASTER = json.loads(read("funnels/blinds.json"))
GATE = MASTER["lead_gate"]
SESSION = "3f2c1a9e-7b4d-4c8e-9a1f-2b3c4d5e6f70"
EMAIL = "Reader@Example.com"


class LogCatch(logging.Handler):
    def __init__(self):
        logging.Handler.__init__(self)
        self.lines = []

    def emit(self, record):
        self.lines.append(self.format(record))


catch = LogCatch()
catch.setFormatter(logging.Formatter("%(name)s %(levelname)s %(message)s"))
logging.getLogger().addHandler(catch)
logging.getLogger().setLevel(logging.DEBUG)

writes = []
fail_with = {"exc": None, "on": None}


def fake_execute(query, params=None):
    writes.append((query, params))
    exc = fail_with["exc"]
    if exc is not None and (fail_with["on"] is None or fail_with["on"] in query):
        raise exc
    return len(writes)


database.execute = fake_execute
client = app.test_client()


def body(**over):
    out = {"email": EMAIL, "funnel": "blinds", "lang": "xx",
           "style_key": "modern_minimal",
           "scores": {"minimal": 4, "cool": 2, "bright": 3, "metal": 1,
                      "warm": -0.5},
           "subid": "fb-camp-7", "session_id": SESSION,
           "marketing_opt_in": False}
    out.update(over)
    return out


def post(payload, raw=None):
    writes.clear()
    catch.lines.clear()
    if raw is not None:
        return client.post("/api/lead", data=raw,
                           content_type="application/json")
    return client.post("/api/lead", json=payload)


ARTICLE = ("https://tigerjar.com/?p=3396&utm_source=mazzin"
           "&utm_medium=redirect&utm_campaign=blinds#modern-minimal")

print("\n--- the config: the gate block, every style anchored ---")
check("the master carries lead_gate after checkout",
      list(MASTER).index("lead_gate") == list(MASTER).index("checkout") + 1
      and GATE["article_url"] == "https://tigerjar.com/?p=3396"
      and GATE["utm_campaign"] == "blinds")
check("  the five styles map one to one onto the article's anchors",
      GATE["anchors"] == {"modern_minimal": "#modern-minimal",
                          "warm_scandi": "#warm-scandinavian",
                          "classic_elegant": "#classic-elegant",
                          "natural_organic": "#natural-organic",
                          "bold_statement": "#bold-statement"}
      and set(GATE["anchors"]) == {s["id"] for s in MASTER["styles"]})
check("  the copy is the brief's: no box, a notice under the button",
      GATE["copy"]["headline"] == "Get your full personal report — free"
      and GATE["copy"]["button"] == "Send my report"
      and "checkbox" not in GATE["copy"] and "privacy" not in GATE["copy"]
      and GATE["copy"]["notice"] == "You'll receive your free report at this "
      "email. No spam — one report. [Privacy policy]."
      and "prices and traps" in GATE["copy"]["subline"])
check("  the mail names the style and the scales",
      "{style}" in GATE["mail"]["subject"] and "{scales}" in GATE["mail"]["summary"]
      and "{pct}" in GATE["mail"]["scale"] and "{style}" in GATE["mail"]["cta"])
check("  pricing and the checkout block stand untouched for the era "
      "comparison",
      MASTER["pricing"]["amount_cents"] == 99
      and MASTER["checkout"]["commerce"]["price_anchor"])
check("the twin and the mirrors carry the same block",
      json.loads(read("funnels/blinds-test.json"))["lead_gate"] == GATE
      and read("funnels/blinds.json") == read("static/funnels/blinds.json"))
check("the migration adds leads with the unique (email, funnel) key",
      "CREATE TABLE IF NOT EXISTS leads (" in read("schema_migrations.sql")
      and "UNIQUE KEY uq_lead (email, funnel)" in read("schema_migrations.sql")
      and "report_sent_at DATETIME NULL" in read("schema_migrations.sql"))

print("\n--- the article link ---")
check("the canonical ?p= URL takes the UTM triplet with & and the anchor last",
      leads.article_link(GATE, "modern_minimal") == ARTICLE)
check("  a URL without a query takes it with ?",
      leads.article_link({"article_url": "https://x.test/a",
                          "utm_campaign": "blinds",
                          "anchors": {"s": "sec"}}, "s")
      == "https://x.test/a?utm_source=mazzin&utm_medium=redirect"
         "&utm_campaign=blinds#sec")
check("  the mail's link says it came by mail",
      leads.article_link(GATE, "bold_statement", leads.UTM_EMAIL)
      == "https://tigerjar.com/?p=3396&utm_source=mazzin&utm_medium=email"
         "&utm_campaign=blinds#bold-statement")
check("  an unmapped style gets the article with no anchor",
      leads.article_link(GATE, "nope").endswith("utm_campaign=blinds"))

print("\n--- POST /api/lead ---")
r = post(body())
data = r.get_json() or {}
check("a good submit is 200 with the redirect", r.status_code == 200
      and data == {"redirect_url": ARTICLE}, (r.status_code, data))
lead_rows = [w for w in writes if w[0].startswith("INSERT INTO leads")]
event_rows = [w for w in writes if w[0].startswith("INSERT INTO events")]
check("  one leads row: the address lower-cased, the funnel, its locale, "
      "the style, the scores, the subid, the session, the box",
      len(lead_rows) == 1 and lead_rows[0][1] == (
          "reader@example.com", "blinds", "en", "modern_minimal",
          json.dumps({"bright": 3, "cool": 2, "metal": 1, "minimal": 4,
                      "warm": -0.5}, separators=(",", ":")),
          "fb-camp-7", SESSION, 0),
      str(lead_rows))
check("  one lead_submit event, with the subid, no step, no extra",
      len(event_rows) == 1 and event_rows[0][1][:5]
      == ("blinds", SESSION, "lead_submit", None, "fb-camp-7")
      and event_rows[0][1][-1] is None, str(event_rows))
check("  and the address is in no log line",
      not any("example.com" in line.lower() for line in catch.lines))
check("  the language is the funnel's, not the client's",
      lead_rows[0][1][2] == "en")
without = body()
del without["marketing_opt_in"]
r = post(without)
check("a post with no consent field at all is the same 200, opt-in 0",
      r.status_code == 200 and [w for w in writes
                                if "INSERT INTO leads" in w[0]][0][1][-1] == 0)
r = post(body(marketing_opt_in="yes"))
check("  and anything but a literal true writes 0", [w for w in writes
                                                     if "INSERT INTO leads" in w[0]][0][1][-1] == 0)

import pymysql                                  # noqa: E402
fail_with.update(exc=pymysql.err.IntegrityError(1062, "Duplicate entry"),
                 on="INSERT INTO leads")
r = post(body())
data = r.get_json() or {}
events = [w for w in writes if w[0].startswith("INSERT INTO events")]
check("a duplicate address is the same 200 and the same redirect",
      r.status_code == 200 and data == {"redirect_url": ARTICLE})
check("  counted as lead_dup, no second row",
      len(events) == 1 and events[0][1][2] == "lead_dup"
      and len([w for w in writes if "INSERT INTO leads" in w[0]]) == 1)
fail_with.update(exc=pymysql.err.OperationalError(2003, "gone"), on=None)
r = post(body())
check("any other database failure is a 500", r.status_code == 500)
check("  logged by type, without the address",
      any("OperationalError" in line for line in catch.lines)
      and not any("example.com" in line.lower() for line in catch.lines),
      str(catch.lines[-2:]))
fail_with.update(exc=None, on=None)

for label, payload in (
        ("no address", body(email="")),
        ("not an address", body(email="reader.example.com")),
        ("an address with a space", body(email="rea der@example.com")),
        ("an address over 320 characters",
         body(email="a" * 310 + "@example.com")),
        ("a style the funnel does not have", body(style_key="cosy")),
        ("no style", body(style_key=None)),
        ("a funnel that does not exist", body(funnel="nope")),
        ("a funnel name that is not a slug", body(funnel="../etc")),
):
    r = post(payload)
    check("  %s is a bare 400" % label,
          r.status_code == 400 and r.get_data() == b"" and not writes,
          (r.status_code, len(writes)))
r = post(None, raw="not json")
check("  a body that is not JSON is a bare 400", r.status_code == 400)
r = post(body(funnel="zodiac30", style_key="fire"))
check("  a funnel that sells for money has no gate: 404, no row",
      r.status_code == 404 and not writes)
r = post(body(session_id="not-a-uuid", scores="nope", subid="x" * 200))
lead_rows = [w for w in writes if w[0].startswith("INSERT INTO leads")]
check("a bad session id, bad scores and a long subid are dropped, not "
      "refused: the row still lands",
      r.status_code == 200 and len(lead_rows) == 1
      and lead_rows[0][1][4] is None and lead_rows[0][1][6] is None
      and len(lead_rows[0][1][5]) == 128, str(lead_rows))
check("  but no event without a session to join on",
      not [w for w in writes if w[0].startswith("INSERT INTO events")])

print("\n--- the events ---")
check("lead_view is a client event with the paywall view's src",
      "lead_view" in tracking.ALLOWED_EVENTS
      and tracking._clean_extra("blinds", "lead_view", {"src": "sticky"})
      == {"src": "sticky"})
check("  lead_submit and lead_dup are server events, never posted",
      tracking.SERVER_EVENTS == frozenset(("lead_submit", "lead_dup"))
      and not (tracking.SERVER_EVENTS & tracking.ALLOWED_EVENTS))
writes.clear()
r = client.post("/api/track", json={"funnel": "blinds", "session_id": SESSION,
                                     "event": "lead_view",
                                     "extra": {"src": "scroll"},
                                     "subid": "fb-camp-7"})
check("  /api/track takes lead_view", r.status_code == 204
      and writes and writes[0][1][2] == "lead_view"
      and writes[0][1][4] == "fb-camp-7", (r.status_code, writes[:1]))
for name in ("lead_submit", "lead_dup"):
    r = client.post("/api/track", json={"funnel": "blinds",
                                         "session_id": SESSION, "event": name})
    check("  /api/track refuses %s" % name, r.status_code == 400)
writes.clear()
try:
    tracking.record_event("blinds", SESSION, "swipe", {})
    refused = False
except ValueError:
    refused = True
check("  record_event refuses an event the client may send", refused)
check("  and writes nothing without a session id",
      tracking.record_event("blinds", None, "lead_submit", {}) is False
      and not writes)
check("  paywall_view stays defined for the history",
      "paywall_view" in tracking.ALLOWED_EVENTS
      and tracking.MIRRORED_EVENTS["paywall_view"] == "InitiateCheckout")

print("\n--- the lead's report: cache and stubs, no row, no model ---")
saved_cache = reports._read_cache
reports._read_cache = lambda funnel, style: None
writes.clear()
content = reports.lead_content("blinds", "warm_scandi",
                               {"warm": 3, "wood": 2, "bright": 2, "cool": 1},
                               ["b1b", "b2a"])
reports._read_cache = saved_cache
check("every section is present, stubbed, and the report is complete",
      [s["id"] for s in content["sections"]]
      == [s["id"] for s in MASTER["report"]["sections"]]
      and content["version"].startswith("stub")
      and content["style_name"] == "Warm Scandinavian"
      and content["funnel"] == "blinds")
check("  nothing was written and no model was asked",
      not writes and reports._api() is None)
reports._read_cache = lambda funnel, style: {
    s: {"stub": False, "title": "cached " + s} for s in
    reports.cached_sections("blinds")}
content2 = reports.lead_content("blinds", "warm_scandi", {"warm": 3})
reports._read_cache = saved_cache
check("  a warm cache is read, the rest stubbed",
      "cached " in json.dumps(content2["sections"])
      and len(content2["sections"]) == len(MASTER["report"]["sections"]))
try:
    reports.lead_content("blinds", "cosy", {})
    refused = False
except ValueError:
    refused = True
check("  an unknown style is a ValueError", refused)

scales = reports.lead_scales(MASTER, {"warm": 3, "cool": 1, "dark": 0,
                                      "bright": 2, "wood": 1, "stone": 1,
                                      "metal": 2})
check("the scale percentages lean the way the tally does",
      scales == [("Warm", 75), ("Bright", 100), ("Natural", 50)], str(scales))
check("  no scores, no scales", reports.lead_scales(MASTER, None) == []
      and reports.lead_scales(MASTER, {"warm": -0.5}) == [])

saved_pdf = reports.build_pdf
reports.build_pdf = lambda content: b"%PDF-fake"
link = leads.article_link(GATE, "warm_scandi", leads.UTM_EMAIL)
payload = reports.lead_mail_payload(MASTER, "reader@example.com", content,
                                    {"warm": 3, "cool": 1, "bright": 2},
                                    link)
check("the mail: subject and body name the style, the scales, the link",
      payload["subject"] == "Your Warm Scandinavian report — Mazzin"
      and payload["to"] == ["reader@example.com"]
      and "Your Warm Scandinavian report is attached." in payload["html"]
      and "You came out Warm Scandinavian: 75% Warm, 100% Bright." in
      payload["html"]
      and 'href="%s"' % link.replace("&", "&amp;") in payload["html"]
      and ">Open the full Warm Scandinavian guide<" in payload["html"]
      and "The PDF is yours to keep." in payload["html"],
      payload["subject"] + " | " + payload["html"][:200])
check("  the PDF rides along under the guide's filename",
      payload["attachments"][0]["filename"] == "mazzin-warm-scandinavian-guide.pdf"
      and payload["attachments"][0]["content"] == "JVBERi1mYWtl")
check("  no price anywhere in it",
      "$" not in payload["html"] and "0.99" not in payload["html"])
hu_cfg = json.loads(json.dumps(MASTER))
table = load_script("set_gate").load_table()
hu_cfg["lead_gate"]["mail"] = table["hu"]["mail"]
hu_payload = reports.lead_mail_payload(hu_cfg, "reader@example.com", content,
                                       {"warm": 3}, link)
check("  a funnel's own language writes its own mail",
      hu_payload["subject"] == "A Warm Scandinavian jelentésed — Mazzin"
      and "A PDF a tiéd, örökre." in hu_payload["html"])
reports.build_pdf = lambda content: b""
check("  no PDF, no mail", reports.lead_mail_payload(
    MASTER, "r@x.test", content, {}, link) is None)
reports.build_pdf = lambda content: b"%PDF-fake"

sent = []


class FakeResponse:
    status_code = 200


fake_requests = type("R", (), {"post": staticmethod(
    lambda url, json=None, headers=None, timeout=None:
    sent.append((url, json, headers)) or FakeResponse())})()
saved_key = config.RESEND_API_KEY
sys.modules["requests"] = fake_requests
config.RESEND_API_KEY = "re_test"
catch.lines.clear()
ok = reports.send_lead_email(7, "reader@example.com", MASTER, content,
                             {"warm": 3}, link)
check("send_lead_email posts the payload to Resend with the key",
      ok is True and len(sent) == 1 and sent[0][0] == reports.RESEND_URL
      and sent[0][2]["Authorization"] == "Bearer re_test"
      and sent[0][1]["to"] == ["reader@example.com"])
check("  and logs the id, never the address",
      any("lead 7" in line for line in catch.lines)
      and not any("example.com" in line for line in catch.lines))
config.RESEND_API_KEY = ""
check("  no key, no send", reports.send_lead_email(
    8, "r@x.test", MASTER, content, {}, link) is False and len(sent) == 1)
config.RESEND_API_KEY = saved_key
del sys.modules["requests"]
reports.build_pdf = saved_pdf

print("\n--- the worker ---")
worker = load_script("send_lead_reports")
queue = [{"id": 1, "email": "a@x.test", "funnel": "blinds", "lang": "en",
          "style_key": "modern_minimal", "scores_json": '{"minimal": 3}'},
         {"id": 2, "email": "b@x.test", "funnel": "blinds", "lang": "en",
          "style_key": "bold_statement", "scores_json": None},
         {"id": 3, "email": "c@x.test", "funnel": "blinds", "lang": "en",
          "style_key": "cosy", "scores_json": "not json"}]
claims = []
database.query_all = lambda q, p=None: list(queue)
database.query_one = lambda q, p=None: next((r for r in queue if r["id"] == p[0]), None)
database.execute_rowcount = lambda q, p=None: claims.append((q, p)) or 1
saved_lead_content = reports.lead_content
reports.lead_content = lambda funnel, style, scores=None, choices=None: {
    "funnel": funnel, "style_id": style, "style_name": style,
    "sections": []} if style != "cosy" else (_ for _ in ()).throw(
        ValueError(style))
mailed = []


def fake_send(lead_id, email, cfg, content, scores, link):
    mailed.append((lead_id, email, content["style_id"], scores, link))
    return lead_id != 2


log = io.StringIO()
with contextlib.redirect_stdout(log):
    sent_n, failed_n = worker.run(limit=10, send=fake_send)
check("the queue is claimed row by row, mailed, and the stamp stands on "
      "success",
      sent_n == 1 and failed_n == 2
      and [c for c in claims if c[0] == worker.CLAIM_SQL] == [
          (worker.CLAIM_SQL, (1,)), (worker.CLAIM_SQL, (2,)),
          (worker.CLAIM_SQL, (3,))], str(claims))
check("  the mail carried the scores and the email-tagged article link",
      mailed[0][:4] == (1, "a@x.test", "modern_minimal", {"minimal": 3})
      and mailed[0][4].endswith("utm_medium=email&utm_campaign=blinds"
                                "#modern-minimal"))
check("  a send that failed, and a report that would not build, are "
      "released for the next run",
      [c for c in claims if c[0] == worker.RELEASE_SQL]
      == [(worker.RELEASE_SQL, (2,)), (worker.RELEASE_SQL, (3,))]
      and len(mailed) == 2)
check("  the log names ids and never an address",
      "lead 1  sent" in log.getvalue() and "released" in log.getvalue()
      and "x.test" not in log.getvalue())
claims.clear()
mailed.clear()
log = io.StringIO()
with contextlib.redirect_stdout(log):
    worker.run(limit=10, dry_run=True, send=fake_send)
check("--dry-run lists and claims nothing", not claims and not mailed
      and "dry run" in log.getvalue())
claims.clear()
mailed.clear()
database.execute_rowcount = lambda q, p=None: claims.append((q, p)) or 0
with contextlib.redirect_stdout(io.StringIO()):
    worker.run(limit=10, send=fake_send)
check("  a row another run claimed is skipped", not mailed)
database.execute_rowcount = lambda q, p=None: claims.append((q, p)) or 1
with contextlib.redirect_stdout(io.StringIO()):
    worker.run(only_id=2, send=fake_send)
check("  --id re-sends one lead whether or not it is stamped",
      mailed and mailed[0][0] == 2
      and claims[-2][0] == worker.RECLAIM_SQL)
reports.lead_content = saved_lead_content
check("the worker documents its cron line",
      "* * * * *" in worker.__doc__ and "send_lead_reports.py" in worker.__doc__)

print("\n--- set_gate: every language, nothing else moved ---")
sg = load_script("set_gate")
mf = load_script("make_funnel")
LANGS = ("nl", "de", "hu", "cs", "pl", "da", "sk", "el")
check("the table names en and the eight languages",
      set(table) == {"en"} | set(LANGS)
      and all(table[l]["article_url"] == url for l, url in (
          ("en", "https://tigerjar.com/?p=3396"),
          ("nl", "https://tigerjar.com/?p=3415"),
          ("de", "https://tigerjar.com/?p=3416"),
          ("hu", "https://tigerjar.com/?p=3419"),
          ("cs", "https://tigerjar.com/?p=3420"),
          ("pl", "https://tigerjar.com/?p=3421"),
          ("da", "https://tigerjar.com/?p=3422"),
          ("sk", "https://tigerjar.com/?p=3423"),
          ("el", "https://tigerjar.com/?p=3424"))))
check("  en mirrors the master",
      table["en"] == {"article_url": GATE["article_url"],
                      "copy": GATE["copy"], "mail": GATE["mail"]})
check("  every language carries every key of the master's copy and mail, "
      "translated, with the tokens kept",
      all(set(table[l]["copy"]) == set(GATE["copy"])
          and set(table[l]["mail"]) == set(GATE["mail"])
          and all(table[l]["copy"][k] and table[l]["copy"][k]
                  != GATE["copy"][k] for k in GATE["copy"]
                  if k != "placeholder")
          and all(mf.tokens_of(table[l]["mail"][k])
                  == mf.tokens_of(GATE["mail"][k]) for k in GATE["mail"])
          for l in LANGS))
check("  every notice says what the address is for and links the policy "
      "from its brackets, in its own words",
      all("[" in table[l]["copy"]["notice"] and "]." in table[l]["copy"]["notice"]
          and "spam" in table[l]["copy"]["notice"].lower()
          and "checkbox" not in table[l]["copy"]
          and "privacy" not in table[l]["copy"] for l in table)
      and len({table[l]["copy"]["notice"] for l in table}) == 9)
check("  and none of them prices anything",
      not any("$" in json.dumps(table[l]) or "0.99" in json.dumps(table[l])
              for l in table))
scratch = tempfile.mkdtemp(prefix="lead-gate-")
try:
    os.makedirs(os.path.join(scratch, "funnels"))
    shutil.copy(os.path.join(ROOT, "funnels", "blinds.json"),
                os.path.join(scratch, "funnels", "blinds.json"))
    stripped = json.loads(read("funnels/blinds.json"))
    with contextlib.redirect_stdout(io.StringIO()):
        for lang in LANGS:
            mf.build("blinds", lang, scratch, no_llm=True)
    # The eight on the server were generated before the block existed.
    for lang in LANGS:
        path = os.path.join(scratch, "funnels", "blinds-%s.json" % lang)
        gen = json.load(open(path, encoding="utf-8"))
        gen.pop("lead_gate")
        for directory in ("funnels", os.path.join("static", "funnels")):
            open(os.path.join(scratch, directory, "blinds-%s.json" % lang),
                 "w", encoding="utf-8").write(
                json.dumps(gen, indent=2, ensure_ascii=False) + "\n")
    before = {l: json.load(open(os.path.join(scratch, "funnels",
                                             "blinds-%s.json" % l),
                                encoding="utf-8")) for l in LANGS}
    log = io.StringIO()
    with contextlib.redirect_stdout(log):
        for lang in LANGS:
            sg.set_gate("blinds", lang, scratch)
    after = {l: json.load(open(os.path.join(scratch, "funnels",
                                            "blinds-%s.json" % l),
                               encoding="utf-8")) for l in LANGS}

    def leaves(node, path="", out=None):
        out = [] if out is None else out
        if isinstance(node, dict):
            for k, v in node.items():
                leaves(v, "%s.%s" % (path, k) if path else k, out)
        elif isinstance(node, list):
            for i, v in enumerate(node):
                leaves(v, "%s[%d]" % (path, i), out)
        else:
            out.append((path, node))
        return out

    check("each language gets the block where the master keeps it",
          all(list(after[l]).index("lead_gate")
              == list(after[l]).index("checkout") + 1 for l in LANGS))
    check("  with its own article, copy and mail, the master's anchors "
          "and campaign",
          all(after[l]["lead_gate"] == {
              "article_url": table[l]["article_url"],
              "utm_campaign": "blinds", "anchors": GATE["anchors"],
              "copy": dict((k, table[l]["copy"][k]) for k in GATE["copy"]),
              "mail": dict((k, table[l]["mail"][k]) for k in GATE["mail"])}
              for l in LANGS))
    moved = {l: sorted(p for p, v in leaves(after[l])
                       if not p.startswith("lead_gate.")
                       and (p, v) not in leaves(before[l])) for l in LANGS}
    check("  and nothing else moved, in any of the eight",
          all(not moved[l] for l in LANGS), str(moved))
    check("  the static mirror is byte-identical",
          all(open(os.path.join(scratch, "funnels", "blinds-%s.json" % l),
                   "rb").read()
              == open(os.path.join(scratch, "static", "funnels",
                                   "blinds-%s.json" % l), "rb").read()
              for l in LANGS))
    log = io.StringIO()
    with contextlib.redirect_stdout(log):
        sg.set_gate("blinds", "hu", scratch)
    check("  rerun, it says so and rewrites the same bytes",
          "already there" in log.getvalue()
          and json.load(open(os.path.join(scratch, "funnels",
                                          "blinds-hu.json"),
                             encoding="utf-8")) == after["hu"])
    r = subprocess.run([sys.executable,
                        os.path.join(ROOT, "scripts", "set_gate.py"),
                        "blinds", "ro", "--root", scratch],
                       capture_output=True, text=True, cwd=ROOT)
    check("a language the table lacks is a plain error", r.returncode == 1
          and "no language" in r.stdout, r.stdout[-200:])
    r = subprocess.run([sys.executable,
                        os.path.join(ROOT, "scripts", "set_gate.py"),
                        "blinds", "de", "--root", scratch, "--dry-run"],
                       capture_output=True, text=True, cwd=ROOT)
    check("  --dry-run writes nothing", r.returncode == 0
          and "nothing written" in r.stdout)
    try:
        sg.gate_block(GATE, {"article_url": "https://x", "copy": {},
                             "mail": table["hu"]["mail"]})
        refused = False
    except sg.GateError:
        refused = True
    check("  a row missing a copy key is refused", refused)
    check("  the make_funnel walk translates the gate's copy and freezes "
          "its anchors and campaign",
          "lead_gate.copy.headline" in [p for p, _ in mf.collect(MASTER)]
          and "lead_gate.mail.subject" in [p for p, _ in mf.collect(MASTER)]
          and not [p for p, _ in mf.collect(MASTER)
                   if p.startswith("lead_gate.anchors")
                   or p in ("lead_gate.article_url",
                            "lead_gate.utm_campaign")])
finally:
    shutil.rmtree(scratch, ignore_errors=True)

print("\n--- the gate at 390px, in all nine languages ---")
import http.server                              # noqa: E402
import socketserver                             # noqa: E402
import threading                                # noqa: E402
from playwright.sync_api import sync_playwright  # noqa: E402

PORT = 8814
CHROME = "/opt/pw-browsers/chromium-1194/chrome-linux/chrome"
PINNED = "2026-09-15T12:00:00Z"
CLOCK = """(() => { const AT = Date.parse(%s); const Real = Date;
  class Stub extends Real {
    constructor(...a) { super(...(a.length ? a : [AT])); }
    static now() { return AT; } }
  window.Date = Stub; })();""" % json.dumps(PINNED)
SEED = """(() => { let s = 0x2f6e2b1;
  Math.random = () => { s |= 0; s = (s + 0x6D2B79F5) | 0;
    let t = Math.imul(s ^ (s >>> 15), 1 | s);
    t = (t + Math.imul(t ^ (t >>> 7), 61 | t)) ^ t;
    return ((t ^ (t >>> 14)) >>> 0) / 4294967296; }; })();"""
LAID = ("() => { const c=document.querySelector('#screen-swipe #cards .card');"
        " return !!c && c.getBoundingClientRect().width>1; }")
SETTLED = ("() => [...document.querySelectorAll('#screen-swipe #cards .card')]"
           ".every(c=>{const t=getComputedStyle(c).transform;"
           " return t==='none'||/matrix\\(1, 0, 0, 1/.test(t);})")
READ_GATE = """() => { const g = document.querySelector('#result-module .zr-gate');
  if (!g) return null;
  const t = s => { const n = g.querySelector(s); return n ? n.textContent.trim() : null; };
  const a = g.querySelector('.zr-gate-notice a');
  return {notice: t('.zr-gate-notice'), link: a ? a.textContent : null,
          href: a ? a.getAttribute('href') : null,
          boxes: g.querySelectorAll('input[type=checkbox]').length,
          privacyLine: !!g.querySelector('.zr-gate-privacy'),
          button: t('.zr-gate-button'), width: g.getBoundingClientRect().width,
          overflow: document.documentElement.scrollWidth > window.innerWidth}; }"""

site = tempfile.mkdtemp(prefix="lead-gate-site-")
langs_ok = {}
try:
    os.makedirs(os.path.join(site, "static", "funnels"))
    os.makedirs(os.path.join(site, "funnels"))
    for name in os.listdir(os.path.join(ROOT, "static")):
        if name != "funnels":
            os.symlink(os.path.join(ROOT, "static", name),
                       os.path.join(site, "static", name))
    shutil.copy(os.path.join(ROOT, "funnels", "blinds.json"),
                os.path.join(site, "funnels", "blinds.json"))
    shutil.copy(os.path.join(ROOT, "funnels", "blinds.json"),
                os.path.join(site, "static", "funnels", "blinds.json"))
    with contextlib.redirect_stdout(io.StringIO()):
        for lang in LANGS:
            mf.build("blinds", lang, site, no_llm=True)
            sg.set_gate("blinds", lang, site)

    class Handler(http.server.SimpleHTTPRequestHandler):
        def __init__(self, *a, **kw):
            super().__init__(*a, directory=site, **kw)

        def log_message(self, *a):
            pass

        def do_GET(self):
            path = self.path.split("?")[0].strip("/")
            if path == "api/pixel-config":
                return self._json({})
            if path == "blinds" or path.startswith("blinds-"):
                self.path = "/static/funnel.html"
            return super().do_GET()

        def do_POST(self):
            self.rfile.read(int(self.headers.get("content-length") or 0))
            self._json({"ok": True})

        def _json(self, payload):
            raw = json.dumps(payload).encode()
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(raw)))
            self.end_headers()
            self.wfile.write(raw)

    socketserver.TCPServer.allow_reuse_address = True
    httpd = socketserver.TCPServer(("127.0.0.1", PORT), Handler)
    threading.Thread(target=httpd.serve_forever, daemon=True).start()

    def walk(page, slug, steps):
        page.add_init_script(CLOCK)
        page.add_init_script(SEED)
        page.add_init_script("try{sessionStorage.setItem('mazzin_sid',"
                             "'a1b2c3d4-0000-4000-8000-000000000007');}"
                             "catch(e){}")
        page.goto("http://127.0.0.1:%d/%s" % (PORT, slug))
        page.wait_for_selector("#screen-swipe #cards .card", timeout=20000)
        for _ in range(steps + 10):
            if page.locator("#screen-result.is-active").count():
                break
            try:
                page.wait_for_function(LAID, timeout=6000)
                page.wait_for_function(SETTLED, timeout=3000)
            except Exception:
                page.wait_for_timeout(800)
                continue
            try:
                page.locator("#screen-swipe #cards .card").first.click(
                    timeout=6000)
            except Exception:
                page.wait_for_timeout(700)
                continue
            page.wait_for_timeout(1900)
        page.wait_for_selector("#result-module .zr-gate", timeout=25000)
        page.wait_for_timeout(600)
        return page.evaluate(READ_GATE)

    try:
        with sync_playwright() as pw:
            browser = pw.chromium.launch(executable_path=CHROME)
            steps = len(MASTER["swipe"]["steps"])
            for lang in ("en",) + LANGS:
                slug = "blinds" if lang == "en" else "blinds-" + lang
                page = browser.new_page(viewport={"width": 390,
                                                  "height": 844})
                errors = []
                page.on("pageerror", lambda e: errors.append(str(e)))
                try:
                    got = walk(page, slug, steps) or {}
                except Exception as exc:          # noqa: BLE001
                    got = {"error": "%s: %s" % (type(exc).__name__, exc)}
                page.close()
                want = table[lang]["copy"]["notice"]
                plain = want.replace("[", "").replace("]", "")
                label = want[want.index("[") + 1:want.index("]")]
                langs_ok[lang] = (
                    got.get("notice") == plain and got.get("link") == label
                    and got.get("href") == "/privacy" and got.get("boxes") == 0
                    and not got.get("privacyLine")
                    and got.get("button") == table[lang]["copy"]["button"]
                    and got.get("width") and got.get("width") <= 390
                    and not got.get("overflow") and not errors)
                check("  %s: the notice in its words, the policy linked, no "
                      "box, fits 390" % lang, langs_ok[lang], str(got)[:220])
            browser.close()
    finally:
        httpd.shutdown()
finally:
    shutil.rmtree(site, ignore_errors=True)
check("all nine languages render the gate the same way",
      len(langs_ok) == 9 and all(langs_ok.values()))

print("\n--- the page's side, pinned in source ---")
ENGINE = read("static/js/engine.js")
MODULE = read("static/js/result_zodiac.js")
CSS = read("static/css/result_zodiac.css")
check("engine: the gate reaching the reader is lead_view with the src, "
      "no pixel",
      'track("lead_view", null, { src: payIntent });' in ENGINE
      and "if (leadGate()) {" in ENGINE
      and 'track("paywall_view", null, { src: payIntent }, fireCheckoutPixel());'
      in ENGINE)
check("  engine owns the POST and hands the module the block and the call",
      'fetch("/api/lead", {' in ENGINE and "leadGate: leadGate()," in ENGINE
      and "submitLead: submitLead," in ENGINE
      and "style_key: winnerStyleId," in ENGINE and "scores: scores," in ENGINE
      and "subid: attribution.subid || null," in ENGINE)
check("  the sticky bar carries the gate's line or stays away",
      "function stickyLabel()" in ENGINE
      and "&& !(leadGate() && !stickyLabel());" in ENGINE)
check("module: the gate stands where the offer stood, and only there",
      "if (ctx.leadGate) {\n      root.appendChild(gate(ctx, data));\n    } else {\n"
      "      root.appendChild(offer(ctx, copy, data, template));\n    }" in MODULE
      and "function gate(ctx, data) {" in MODULE
      and 'elm("section", "zr-offer zr-gate")' in MODULE
      and "window.location.href = res.redirect_url;" in MODULE)
GATE_SRC = MODULE.split("function gate(ctx, data) {")[1].split("\n  }\n")[0]
check("  the gate draws no box and reads none: the submit carries the "
      "address alone",
      "checkbox" not in GATE_SRC and "marketing_opt_in" not in GATE_SRC
      and "zr-gate-tick" not in MODULE
      and "ctx.submitLead({ email: email })" in GATE_SRC)
check("  and says in so many words that a marketing opt-in is a separate "
      "unchecked box",
      "delivery of the REQUESTED report" in GATE_SRC
      and "UNCHECKED box" in GATE_SRC)
check("  the notice links the policy from its brackets, to the page's own "
      "privacy link",
      "function gateNotice(text, legal) {" in MODULE
      and 'var href = "/privacy";' in MODULE
      and "/privacy/i.test(links[i].getAttribute(\"href\")" in MODULE
      and 'elm("a", "zr-gate-privacy-link", text.slice(open + 1, close))'
      in MODULE and ".zr-gate-notice a {" in CSS
      and ".zr-gate-tick" not in CSS)
check("  the paid offer's consent box is exactly where it was",
      "var wantsConsent = ctx.cfg.checkout.withdrawal_consent !== false;"
      in MODULE
      and "[wantsConsent ? nodes.consent : null, nodes.walletSummary, "
      "nodes.wallet," in MODULE)
check("  the styles are before the boxes arm's",
      CSS.index(".zr-gate-input {") < CSS.index("the boxes arm"))
check("payments.py is not touched by any of this",
      "/api/lead" not in read("payments.py")
      and "INSERT INTO leads" not in read("payments.py")
      and "lead_gate" not in read("payments.py")
      and "import payments" in read("leads.py"))

print("\n%d checks, %d failed" % (checks[0], len(fails)))
for f in fails:
    print("  FAIL " + f)
sys.exit(1 if fails else 0)
