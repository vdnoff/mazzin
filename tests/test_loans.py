#!/usr/bin/env python3
"""The Loan Options funnel: `POST /api/loans/lead`, `POST /api/loans/event`,
`GET /loans`, and the three static files behind it.

Asserted here: a valid lead is a 204 and exactly one upsert carrying the six
answers and the cleaned attribution; every field's bad value and any unknown
key is a bare 400 that writes nothing; a second POST on the same session is
the same single statement, whose ON DUPLICATE KEY clause is what overwrites
instead of adding a row. An event is one row in `events` with funnel 'loans':
a swipe needs a step in 1..4 and nothing else may carry one, `extra` exists
only on `offer_tap` and is rebuilt from a checked slot, an unknown event is a
400. A database failure is a 500 whose log line carries nothing of the
request. Neither route reads, and neither looks at an IP or a User-Agent.
`/loans` is the static page with the funnel cache header and `/kitchen` still
answers. The page collects no free text, labels its ads, ships no dead link
in pre-feed mode and makes no third-party request.

No database, no network, no key: every call is monkeypatched.
"""
import json
import logging
import os
import re
import sys

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, REPO)

import config                                   # noqa: E402
import database                                 # noqa: E402
import loans                                    # noqa: E402
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
    with open(os.path.join(REPO, rel), encoding="utf-8") as fh:
        return fh.read()


SESSION = "3f2c1a9e-7b4d-4c8e-9a1f-2b3c4d5e6f70"
SUBID = "fb-camp-loans-7"


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
fail_with = {"exc": None}


def fake_execute(query, params=None):
    writes.append((query, params))
    if fail_with["exc"] is not None:
        raise fail_with["exc"]
    return len(writes)


def no_reads(*_args, **_kwargs):
    raise AssertionError("a loans route read from the database")


database.execute = fake_execute
database.execute_rowcount = no_reads
database.query_all = no_reads
database.query_one = no_reads
client = app.test_client()


def lead_body(**over):
    out = {"session_id": SESSION, "amount": 500, "purpose": "car",
           "employment": "employed", "income": "2000_3000", "credit": "fair",
           "state": "TX", "subid": SUBID, "utm_source": "fb"}
    out.update(over)
    return out


def without(payload, key):
    return {k: v for k, v in payload.items() if k != key}


def post(path, payload=None, raw=None):
    writes.clear()
    catch.lines.clear()
    if raw is not None:
        return client.post(path, data=raw, content_type="application/json")
    return client.post(path, json=payload)


def lead(payload=None, raw=None):
    return post("/api/loans/lead", payload, raw)


def event(payload=None, raw=None):
    return post("/api/loans/event", payload, raw)


def refused(resp):
    return resp.status_code == 400 and resp.data == b"" and not writes


print("\n--- POST /api/loans/lead: a valid lead ---")
r = lead(lead_body())
check("a valid lead is a 204 with no body",
      r.status_code == 204 and r.data == b"", r.status_code)
check("  and exactly one statement", len(writes) == 1, len(writes))
sql, params = writes[0] if writes else ("", ())
check("  an upsert into loan_leads on the session key",
      sql.startswith("INSERT INTO loan_leads ")
      and "ON DUPLICATE KEY UPDATE" in sql and sql is loans.UPSERT_SQL)
check("  the six answers and the attribution, in column order",
      params == (SESSION, 500, "car", "employed", "2000_3000", "fair", "TX",
                 SUBID, "fb", None, None, None), params)
check("  one placeholder per parameter",
      sql.split("ON DUPLICATE")[0].count("%s") == len(params) == 12)
columns = re.search(r"\((session_id.*?)\)", sql, re.S).group(1)
columns = [c.strip() for c in columns.split(",")]
updated = re.findall(r"(\w+) = VALUES\((\w+)\)", sql)
check("  every column but the key is overwritten on a duplicate",
      [u[0] for u in updated] == columns[1:]
      and all(left == right for left, right in updated), updated)
check("  no contact, identity or network column is written",
      not re.search(r"email|phone|name|address|ssn|dob|birth|ip|agent|bank",
                    " ".join(columns)), columns)
r = lead(lead_body(amount=100, state="DC", purpose="other"))
check("the bounds are in: $100, DC",
      r.status_code == 204 and writes[0][1][1] == 100
      and writes[0][1][6] == "DC")
r = lead(lead_body(amount=5000))
check("  and $5,000", r.status_code == 204 and writes[0][1][1] == 5000)
r = lead({k: v for k, v in lead_body().items()
          if k not in ("subid", "utm_source")})
check("attribution is optional",
      r.status_code == 204 and writes[0][1][7:] == (None,) * 5)

print("\n--- a second POST on the same session overwrites ---")
lead(lead_body())
first = list(writes)
r = lead(lead_body(amount=1200, credit="good", state="CA"))
check("the edit is a 204 and one statement again",
      r.status_code == 204 and len(writes) == 1)
check("  the same upsert, never a second kind of write",
      writes[0][0] is first[0][0] and "ON DUPLICATE KEY UPDATE" in writes[0][0])
check("  on the same session key, with the new answers",
      writes[0][1][0] == first[0][1][0] == SESSION
      and writes[0][1][1] == 1200 and writes[0][1][5] == "good"
      and writes[0][1][6] == "CA")
MIGRATIONS = read("schema_migrations.sql")
TABLE = MIGRATIONS[MIGRATIONS.index("CREATE TABLE loan_leads"):]
check("  and the table's unique key is what makes that an overwrite",
      "UNIQUE KEY uq_loan_lead_session (session_id)" in TABLE)
r = lead(lead_body(session_id=SESSION.upper()))
check("a session id is one key whatever its case",
      r.status_code == 204 and writes[0][1][0] == SESSION)

print("\n--- every field's bad value is a bare 400 and no write ---")
BAD = {
    "session_id": [None, "", "abc", 7, SESSION + "0", SESSION[:-1],
                   SESSION + "\n", " " + SESSION,
                   "not-a-uuid-at-all-but-36-chars-long!"],
    "amount": [None, "500", 0, 50, 99, 150, 5100, 100000, -500, 500.0, 500.5,
               True, [500]],
    "purpose": [None, "", "vacation", "Car", 1, ["car"]],
    "employment": [None, "", "student", "self-employed", 2],
    "income": [None, "", "1000-2000", "lt500", 2000],
    "credit": [None, "", "poor", "Fair", 650],
    "state": [None, "", "tx", "Texas", "XX", "PR", "T", 48],
}
for field, values in BAD.items():
    bad = [v for v in values if not refused(lead(lead_body(**{field: v})))]
    check("%s: %d bad values refused" % (field, len(values)), not bad, bad)
    check("  and a lead without it", refused(lead(without(lead_body(), field))))
for key in ("email", "name", "phone", "ssn", "zip", "funnel", "step", "extra"):
    check("unknown key refused: %s" % key,
          refused(lead(lead_body(**{key: "x"}))))
check("a body that is not an object",
      refused(lead(raw="[]")) and refused(lead(raw='"x"'))
      and refused(lead(raw="{not json")) and refused(lead(raw="")))
check("nothing about a refused lead is logged", not catch.lines, catch.lines)

print("\n--- attribution is cleaned exactly as /api/track cleans it ---")
r = lead(lead_body(subid="  " + "s" * 300 + "  ", utm_source="u" * 300,
                   utm_campaign="   ", utm_content=17, utm_term="t" * 128))
p = writes[0][1]
check("trimmed and cut to the column, junk becomes NULL",
      r.status_code == 204 and p[7] == "s" * 128 and p[8] == "u" * 64
      and p[9] is None and p[10] is None and p[11] == "t" * 128)
check("  the lengths are tracking.py's own",
      loans.ATTRIBUTION == tuple(tracking.ATTRIBUTION_FIELDS)
      and "tracking._clean_optional" in read("loans.py"))
for name, size in tracking.ATTRIBUTION_FIELDS.items():
    check("  %s fits its column (%d)" % (name, size),
          re.search(r"%s VARCHAR\(%d\) NULL" % (name, size), TABLE))

print("\n--- POST /api/loans/event ---")


def ev(**over):
    out = {"session_id": SESSION, "event": "funnel_start", "subid": SUBID}
    out.update(over)
    return out


r = event(ev())
check("funnel_start is a 204 and one row",
      r.status_code == 204 and r.data == b"" and len(writes) == 1)
sql, params = writes[0] if writes else ("", ())
check("  the events INSERT, tracking.py's own statement",
      sql is tracking.INSERT_SQL and sql.startswith("INSERT INTO events"))
check("  funnel 'loans', no step, no extra, the attribution",
      params == ("loans", SESSION, "funnel_start", None, SUBID, None, None,
                 None, None, None), params)
for step in (1, 2, 3, 4):
    r = event(ev(event="swipe", step=step))
    check("swipe step %d" % step,
          r.status_code == 204 and writes[0][1][2:4] == ("swipe", step)
          and writes[0][1][9] is None)
bad = [s for s in (None, 0, 5, -1, "1", 1.0, 1.5, True, [1])
       if not refused(event(ev(event="swipe", step=s)))]
check("a swipe needs a step in 1..4", not bad, bad)
check("  and one with no step key at all",
      refused(event(ev(event="swipe"))))
for name in ("funnel_start", "result_view", "offer_tap"):
    payload = ev(event=name, step=1)
    if name == "offer_tap":
        payload["extra"] = {"slot": "options_cta"}
    check("%s may not carry a step" % name, refused(event(payload)))
r = event(ev(event="result_view", step=None, extra=None))
check("result_view, nulls spelled out",
      r.status_code == 204 and writes[0][1][3] is None
      and writes[0][1][9] is None)

r = event(ev(event="offer_tap", extra={"slot": "options_cta"}))
check("offer_tap with a slot",
      r.status_code == 204 and writes[0][1][9] == '{"slot":"options_cta"}',
      writes)
r = event(ev(event="offer_tap", extra={"slot": "1-year-personal-loan"}))
check("  an OFFERS id is a slot",
      r.status_code == 204
      and json.loads(writes[0][1][9]) == {"slot": "1-year-personal-loan"})
bad_extra = [None, "options_cta", [], {}, {"slot": ""}, {"slot": "A"},
             {"slot": "has space"}, {"slot": "x" * 41}, {"slot": 3},
             {"slot": "a.b"}, {"slot": "a\n"}, {"slot": None},
             {"slot": "ok", "url": "https://example.com"},
             {"url": "https://example.com"}]
bad = [x for x in bad_extra
       if not refused(event(ev(event="offer_tap", extra=x)))]
check("offer_tap: %d bad extras refused" % len(bad_extra), not bad, bad)
check("  and one with no extra key at all",
      refused(event(ev(event="offer_tap"))))
check("  a 40-character slot is the longest allowed",
      event(ev(event="offer_tap", extra={"slot": "x" * 40})).status_code == 204)
for name in ("funnel_start", "result_view"):
    check("%s may not carry an extra" % name,
          refused(event(ev(event=name, extra={"slot": "options_cta"}))))
check("a swipe may not carry an extra",
      refused(event(ev(event="swipe", step=1, extra={"slot": "x"}))))
for name in ("purchase", "lead_submit", "paywall_view", "pay_tap", "", None,
             7, "Swipe"):
    check("unknown event refused: %r" % (name,),
          refused(event(ev(event=name))))
bad = [s for s in (None, "", "abc", 7) if not refused(event(ev(session_id=s)))]
check("an event needs a session id", not bad, bad)
for key in ("funnel", "email", "amount", "state", "event_id"):
    check("unknown key refused: %s" % key, refused(event(ev(**{key: "x"}))))
check("a body that is not an object",
      refused(event(raw="[]")) and refused(event(raw="{")))
writes.clear()
r = client.post("/api/loans/event", data=json.dumps(ev()),
                content_type="text/plain;charset=UTF-8")
check("a sendBeacon body (text/plain) is read as JSON",
      r.status_code == 204 and len(writes) == 1)
check("the names are a subset of what /api/track knows",
      loans.EVENTS <= tracking.ALLOWED_EVENTS | {"offer_tap"}
      and loans.EVENTS == {"funnel_start", "swipe", "result_view",
                           "offer_tap"})

print("\n--- a database failure: 500, and nothing of the request logged ---")
SECRET_SUB = "subid-that-must-not-be-logged"
fail_with["exc"] = RuntimeError("(1146, \"Table 'mazzin.loan_leads' doesn't "
                                "exist\")")
r = lead(lead_body(subid=SECRET_SUB, state="WY", amount=4300))
log_text = "\n".join(catch.lines)
check("a missing loan_leads table is a 500, not a crash",
      r.status_code == 500 and r.data == b"", r.status_code)
check("  it is logged once, as an exception",
      len(catch.lines) == 1 and "loan lead write failed" in log_text
      and "Traceback" in log_text, catch.lines)
check("  with no payload: no session, attribution or answer",
      SESSION not in log_text and SECRET_SUB not in log_text
      and "4300" not in log_text and "WY" not in log_text
      and "2000_3000" not in log_text)
r = event(ev(subid=SECRET_SUB, event="offer_tap",
             extra={"slot": "slot-not-logged"}))
log_text = "\n".join(catch.lines)
check("the event route the same: 500",
      r.status_code == 500 and len(catch.lines) == 1
      and "loan event write failed" in log_text)
check("  with no payload",
      SESSION not in log_text and SECRET_SUB not in log_text
      and "slot-not-logged" not in log_text)
fail_with["exc"] = None
check("the page still answers while the table is missing",
      client.get("/loans").status_code == 200)

print("\n--- the module: one write each, no reads, no network identity ---")
SRC = read("loans.py")
CODE = SRC.split('"""', 2)[2]
check("no SELECT and no read helper",
      not re.search(r"\bSELECT\b", CODE) and "query_one" not in CODE
      and "query_all" not in CODE and "execute_rowcount" not in CODE)
check("database.execute and nothing else, twice",
      CODE.count("database.") == 2 and CODE.count("database.execute(") == 2)
check("no IP address and no User-Agent",
      not re.search(r"remote_addr|headers|user.agent|access_route|"
                    r"X-Forwarded|_client_ip|environ", CODE, re.I))
check("the log calls carry no arguments",
      re.findall(r"log\.\w+\((.*?)\)", CODE, re.S)
      == ['"loan lead write failed"', '"loan event write failed"'])
check("no payment, pixel or model call",
      not re.search(r"stripe|payments|pixel|anthropic|openai", CODE, re.I))
check("51 states, two capitals each",
      len(loans.STATES) == 51 and "DC" in loans.STATES
      and all(re.match(r"^[A-Z]{2}$", s) for s in loans.STATES))
check("the SQL lives in loans.py and nowhere else",
      all("loan_leads" not in read(f) for f in
          ("app.py", "tracking.py", "payments.py", "leads.py", "admin.py",
           "analytics.py", "schema.sql")))
check("the email gate still owns /api/lead, untouched",
      "/api/loans" not in read("leads.py")
      and '@bp.post("/api/lead")' in read("leads.py"))

print("\n--- the schema ---")
check("the migration is appended, dated and last",
      "-- 2026-11-10" in MIGRATIONS
      and MIGRATIONS.rstrip().endswith(");")
      and MIGRATIONS.count("CREATE TABLE loan_leads (") == 1
      and MIGRATIONS.index("CREATE TABLE loan_leads")
      > MIGRATIONS.index("idx_leads_funnel_lang_created"))
NOTE = MIGRATIONS[MIGRATIONS.index("-- 2026-11-10"):
                  MIGRATIONS.index("CREATE TABLE loan_leads")]
check("  its comment says by hand, before the deploy",
      "APPLIED BY HAND BEFORE THE DEPLOY" in NOTE)
check("  and that it holds no contact or identity data by design",
      "no contact or identity data, by design" in NOTE)
table_cols = re.findall(r"^\s+(\w+) [A-Z]+", TABLE.split("UNIQUE KEY")[0],
                        re.M) + re.findall(r", (utm_\w+) VARCHAR", TABLE)
check("  every column the upsert writes exists",
      set(columns) <= set(table_cols), sorted(set(columns) - set(table_cols)))
check("  amount is whole dollars, never a float",
      "amount_usd SMALLINT UNSIGNED NOT NULL" in TABLE)

print("\n--- GET /loans, and the funnels beside it ---")
r = client.get("/loans")
PAGE = read("static/loans.html")
check("/loans is a 200", r.status_code == 200, r.status_code)
check("  the static page itself", r.data.decode("utf-8") == PAGE)
check("  with the funnel cache header",
      r.headers.get("Cache-Control")
      == "public, max-age=%d" % config.FUNNEL_HTML_MAX_AGE,
      r.headers.get("Cache-Control"))
check("  it is not the swipe shell",
      "engine.js" not in PAGE and "mazzin.css" not in PAGE
      and not os.path.exists(os.path.join(REPO, "funnels", "loans.json")))
r = client.get("/kitchen")
check("/kitchen is still a 200, and still the swipe shell",
      r.status_code == 200 and b"engine.js" in r.data
      and r.headers.get("Cache-Control")
      == "public, max-age=%d" % config.FUNNEL_HTML_MAX_AGE)
check("an unknown slug is still a 404",
      client.get("/loanz").status_code == 404)
check("the API is POST only",
      client.get("/api/loans/lead").status_code == 405
      and client.get("/api/loans/event").status_code == 405)

print("\n--- the page: what it asks, what it says, what it loads ---")
CSS = read("static/css/loans.css")
JS = read("static/js/loans.js")
check("noindex, nofollow",
      '<meta name="robots" content="noindex, nofollow">' in PAGE)
inputs = re.findall(r"<input\b[^>]*>", PAGE)
check("the only input is the amount range",
      len(inputs) == 1 and 'type="range"' in inputs[0]
      and 'min="100"' in inputs[0] and 'max="5000"' in inputs[0]
      and 'step="100"' in inputs[0] and 'value="500"' in inputs[0], inputs)
check("no free text anywhere",
      "<textarea" not in PAGE and "contenteditable" not in PAGE
      and "<form" not in PAGE
      and not re.search(r"createElement\(\"(input|textarea)\"\)", JS))
check("two selects, both closed lists",
      re.findall(r'<select id="(\w+)"', PAGE) == ["income", "state"])
visible = re.sub(r"<[^>]+>", " ", PAGE)
banned = [w for w in ("congratulations", "pre-qualif", "prequalif",
                      "approved", "you qualify", "guarantee", "instant",
                      "hurry", "limited time", "act now", "lender search",
                      "find a lender", "apply now", "apply here", "expires",
                      "% of", "people have")
          if w in visible.lower() or w in JS.lower()]
check("no approval, urgency or statistic in the copy", not banned, banned)
check("it says what Mazzin is not, on the landing, options and offers views",
      visible.count("Mazzin is not a lender") == 3)
check("the options card is labelled Sponsored and Ad",
      '<div class="sponsor-row"><span>Sponsored</span><span>Ad</span></div>'
      in PAGE)
check("the related searches are labelled Sponsored",
      'Related searches <span class="pill">Sponsored</span>' in PAGE)
for needle in ("How much do you need?", "What is the loan for?",
               "How do you earn your income?",
               "How would you rate your credit?",
               "Compare personal loan providers",
               "Pick a search to see offers",
               "Offers are not available yet."):
    check("copy: %s" % needle, needle in PAGE)
check("six views", len(re.findall(r'<section class="view"', PAGE)) == 6)
check("six purposes, four employments, four credit bands, five incomes",
      set(re.findall(r'class="tile" type="button" data-value="(\w+)"', PAGE))
      == loans.PURPOSES
      and set(re.findall(r'class="toggle" type="button" data-value="(\w+)"',
                         PAGE)) == loans.EMPLOYMENTS
      and set(re.findall(r'class="row-toggle" type="button" '
                         r'data-value="(\w+)"', PAGE)) == loans.CREDITS
      and {v for v in re.findall(r'<option value="(\w*)"', PAGE) if v}
      == loans.INCOMES)
js_states = re.findall(r'\["([A-Z]{2})", "[^"]+"\]', JS)
check("the page's 51 states are the server's",
      len(js_states) == 51 and set(js_states) == loans.STATES)
check("no image and no emoji",
      "<img" not in PAGE and "url(data:" not in CSS
      and not re.search(r"\.(png|jpe?g|webp|gif)", PAGE + CSS + JS)
      and not re.search("[\U0001F000-\U0001FAFF☀-➿]",
                        PAGE + CSS + JS))
external = [u for u in re.findall(r"(?:https?:)?//[\w.-]+\.[a-z]{2,}[^\s\"')]*",
                                  PAGE + CSS + JS)
            if "www.w3.org/2000/svg" not in u]
check("no third-party request", not external, external)
check("the site's own two font files, and only those",
      set(re.findall(r'url\("([^"]+)"\)', CSS))
      == {"/static/fonts/inter-latin-var.woff2",
          "/static/fonts/fraunces-latin-var.woff2"}
      and "@import" not in CSS)
tokens = {"--ground": "#F5F7FB", "--card": "#FFFFFF", "--ink": "#131A2B",
          "--ink-2": "#3B4560", "--muted": "#56607A", "--line": "#DCE2EE",
          "--line-input": "#C3CCDD", "--accent": "#1F4FD8",
          "--accent-hover": "#173BA6", "--accent-ink": "#132F85",
          "--tint": "#E8EEFC", "--navy": "#0F1F4D", "--navy-soft": "#B9C8F5"}
wrong = [k for k, v in tokens.items() if "%s: %s;" % (k, v) not in CSS]
check("the thirteen colour tokens", not wrong, wrong)
check("a visible focus ring", ":focus-visible" in CSS)

print("\n--- loans.js: the offers, the events, the storage ---")
check("one IIFE, strict",
      JS.lstrip().startswith("/*") and "(function () {" in JS
      and JS.rstrip().endswith("})();") and '"use strict";' in JS)
offers = re.findall(r'\{ id: "([a-z0-9-]+)", label: "([^"]+)", url: "([^"]*)" '
                    r'\}', JS)
check("the six seeded offers, in order",
      [o[1] for o in offers]
      == ["Personal Loans Online", "Small Personal Loans",
          "Personal Loans Near Me", "Compare Personal Loan Rates",
          "Loans for Fair Credit", "1 Year Personal Loan"]
      and offers[0][0] == "personal-loans-online", offers)
check("  every id is a slot the server accepts",
      all(loans.SLOT_RE.fullmatch(o[0]) for o in offers)
      and loans.SLOT_RE.fullmatch("options_cta"))
check("  pre-feed: every url is empty", all(o[2] == "" for o in offers))
check("  an empty url is drawn disabled, never as a link",
      'row.setAttribute("aria-disabled", "true")' in JS
      and JS.index("if (offer.url) {") < JS.index("row.href = offer.url;")
      < JS.index("} else {", JS.index("row.href = offer.url;"))
      and JS.count(".href =") == 1)
check("  a live one is rel sponsored noopener, in a new tab",
      'row.rel = "sponsored noopener";' in JS
      and 'row.target = "_blank";' in JS)
check("session id from crypto.randomUUID, kept in sessionStorage",
      "crypto.randomUUID()" in JS and "sessionStorage.setItem" in JS
      and "localStorage" not in JS and "document.cookie" not in JS)
check("the five attribution names engine.js uses",
      '["subid", "utm_source", "utm_campaign", "utm_content", "utm_term"]'
      in JS and '["subid", "utm_source", "utm_campaign", "utm_content", '
      '"utm_term"]' in read("static/js/engine.js"))
check("events by sendBeacon, with a keepalive fetch behind it",
      'navigator.sendBeacon("/api/loans/event", body)' in JS
      and "keepalive: true" in JS)
sent = set(re.findall(r'track(?:Once)?\((?:"\w+", )?"(\w+)"', JS))
check("only events the server accepts", sent == loans.EVENTS, sent)
check("the back button: pushState forward, popstate back",
      "history.pushState(" in JS and '"popstate"' in JS)
check("the lead is posted and not waited for",
      JS.index("sendLead();") < JS.index('go("options");')
      and "await" not in JS and ".then(" not in JS)
check("a failed call shows nothing",
      "alert(" not in JS and "console." not in JS
      and ".catch(function () {})" in JS)

print("\n--- the guide ---")
GUIDE = read("CLAUDE.md")
check("CLAUDE.md names loans.py and what it never does",
      "| `loans.py` | `/api/loans/*`" in GUIDE
      and "validate + one write each" in GUIDE)
check("  and the three static files, off engine.js",
      "`static/loans.html` / `static/css/loans.css` / `static/js/loans.js`"
      in GUIDE and "`/loans` does not use `engine.js`" in GUIDE)

print("\n%d checks, %d failed" % (checks[0], len(fails)))
for f in fails:
    print("  FAIL " + f)
sys.exit(1 if fails else 0)
