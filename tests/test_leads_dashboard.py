#!/usr/bin/env python3
"""The leads section of the admin dashboard.

Asserted here: the three filters build the right WHERE, alone and together,
with the wildcards in a subid escaped; the page is behind the same door as
the rest of the dashboard (a redirect to login, a 401 on the API, a 503
unconfigured); the summary counts, the gate conversion off the events
table, the per-market table; the page of fifty newest first and the count
line; the CSV honouring the same filters with the same seven columns; the
report column reading ✓ or —; and that every statement issued was a
SELECT. The migration adds the index the filters read through.

No database: a SQLite table stands in for `leads` and `events`, seeded here.
"""
import csv
import datetime
import io
import json
import os
import re
import sqlite3
import sys

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, REPO)
ROOT = REPO

import admin                                    # noqa: E402
import analytics                                # noqa: E402
import config                                   # noqa: E402
import database                                 # noqa: E402
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


def eq(label, got, want):
    check(label, got == want, "got %r want %r" % (got, want))


def read(rel):
    with open(os.path.join(ROOT, rel), encoding="utf-8") as fh:
        return fh.read()


sqlite3.register_adapter(
    datetime.datetime, lambda v: v.strftime("%Y-%m-%d %H:%M:%S"))

conn = sqlite3.connect(":memory:")
conn.row_factory = sqlite3.Row
conn.executescript("""
    CREATE TABLE leads (
      id INTEGER PRIMARY KEY AUTOINCREMENT,
      email TEXT NOT NULL, funnel TEXT NOT NULL, lang TEXT NOT NULL,
      style_key TEXT, scores_json TEXT, subid TEXT, session_id TEXT,
      marketing_opt_in INTEGER DEFAULT 0, report_sent_at TEXT,
      created_at TEXT NOT NULL);
    CREATE TABLE events (
      id INTEGER PRIMARY KEY AUTOINCREMENT, created_at TEXT NOT NULL,
      funnel TEXT NOT NULL, session_id TEXT NOT NULL, event TEXT NOT NULL,
      step INTEGER, subid TEXT, extra TEXT);
""")
statements = []


def query_all(sql, params=None):
    statements.append(sql)
    cur = conn.execute(sql.replace("%s", "?"), tuple(params or ()))
    return [dict(r) for r in cur.fetchall()]


def query_one(sql, params=None):
    rows = query_all(sql, params)
    return rows[0] if rows else None


def refuse(sql, params=None):
    raise AssertionError("the leads dashboard wrote: %s" % sql[:60])


database.query_all = query_all
database.query_one = query_one
database.execute = refuse
database.execute_rowcount = refuse

NOW = datetime.datetime.now().replace(microsecond=0)
MIDNIGHT = NOW.replace(hour=0, minute=0, second=0)
TODAY = MIDNIGHT + datetime.timedelta(hours=9)
DAYS_AGO_3 = MIDNIGHT - datetime.timedelta(days=3) + datetime.timedelta(hours=12)
DAYS_AGO_20 = MIDNIGHT - datetime.timedelta(days=20) + datetime.timedelta(hours=12)


def lead(email, funnel, lang, when, subid=None, style="modern_minimal",
         sent=None):
    conn.execute(
        "INSERT INTO leads (email, funnel, lang, style_key, subid, "
        "report_sent_at, created_at) VALUES (?, ?, ?, ?, ?, ?, ?)",
        (email, funnel, lang, style, subid,
         sent.strftime("%Y-%m-%d %H:%M:%S") if sent else None,
         when.strftime("%Y-%m-%d %H:%M:%S")))


def event(funnel, session, name, when, subid=None):
    conn.execute(
        "INSERT INTO events (created_at, funnel, session_id, event, subid) "
        "VALUES (?, ?, ?, ?, ?)",
        (when.strftime("%Y-%m-%d %H:%M:%S"), funnel, session, name, subid))


# The seed: two verticals, three markets, two kinds of subid, three ages.
lead("a@x.test", "blinds", "en", TODAY, "tigerjar_article_en", sent=TODAY)
lead("b@x.test", "blinds", "en", DAYS_AGO_3, "comment_17", sent=DAYS_AGO_3)
lead("c@x.test", "blinds-hu", "hu", TODAY, "tigerjar_article_hu")
lead("d@x.test", "blinds-hu", "hu", DAYS_AGO_20, "comment_9",
     style="bold_statement", sent=DAYS_AGO_20)
lead("e@x.test", "blinds-de", "de", DAYS_AGO_3, "tigerjar_article_de",
     sent=DAYS_AGO_3)
lead("f@x.test", "sofa-hu", "hu", TODAY, "tigerjar_article_hu")
lead("g@x.test", "sofa", "en", DAYS_AGO_20, None, sent=DAYS_AGO_20)
# The gate's conversion: on blinds (the one funnel on disk here), six result
# views and two submits in the window, one submit of each subid family, and
# one result view from before the window that must not count.
for n in range(6):
    event("blinds", "s%d" % n, "result_view", DAYS_AGO_3,
          "tigerjar_article_en" if n < 4 else "comment_17")
event("blinds", "s0", "result_view", DAYS_AGO_3, "tigerjar_article_en")  # twice
event("blinds", "s0", "lead_submit", DAYS_AGO_3, "tigerjar_article_en")
event("blinds", "s5", "lead_submit", TODAY, "comment_17")
event("blinds", "old", "result_view", DAYS_AGO_20, "tigerjar_article_en")
conn.commit()

print("\n--- the WHERE ---")
eq("no filter is 1=1", analytics.leads_where(), ("1=1", []))
eq("a vertical is the stem or the stem-dash-anything",
   analytics.leads_where(vertical="blinds"),
   ("1=1 AND (l.funnel = %s OR l.funnel LIKE %s)", ["blinds", "blinds-%"]))
eq("a market is its column", analytics.leads_where(lang="hu"),
   ("1=1 AND l.lang = %s", ["hu"]))
eq("a subid is a contains, wildcards escaped",
   analytics.leads_where(subid="tiger_a%b!"),
   ("1=1 AND l.subid LIKE %s ESCAPE '!'", ["%tiger!_a!%b!!%"]))
eq("all three, in index order",
   analytics.leads_where("blinds", "hu", "article"),
   ("1=1 AND (l.funnel = %s OR l.funnel LIKE %s) AND l.lang = %s "
    "AND l.subid LIKE %s ESCAPE '!'",
    ["blinds", "blinds-%", "hu", "%article%"]))
eq("vertical and lang off a slug", (analytics.vertical_of("blinds-hu"),
                                    analytics.lang_of("blinds-hu"),
                                    analytics.vertical_of("blinds"),
                                    analytics.lang_of("blinds")),
   ("blinds", "hu", "blinds", "en"))

print("\n--- the filters off the query string ---")
eq("nothing asked is nothing", admin.resolve_lead_filters({}),
   {"vertical": None, "lang": None, "subid": None})
eq("a slug-shaped vertical and a lang are taken, lower-cased",
   admin.resolve_lead_filters({"vertical": "Blinds", "lang": "HU",
                               "subid": " article "}),
   {"vertical": "blinds", "lang": "hu", "subid": "article"})
eq("anything not slug-shaped is all",
   admin.resolve_lead_filters({"vertical": "bl inds; DROP", "lang": "h",
                               "subid": "x" * 300})["vertical"], None)
eq("  and a subid is cut to the column's length",
   len(admin.resolve_lead_filters({"subid": "x" * 300})["subid"]), 128)

print("\n--- the door ---")
USERNAME, PASSWORD = "owner", "correct horse battery staple"
config.ADMIN_USER = ""
config.ADMIN_PASSWORD_HASH = ""
admin.configure(app)
with app.test_client() as client:
    for route in ("/admin/leads", "/admin/leads.csv", "/admin/api/leads"):
        eq("503 with no credentials: %s" % route,
           client.get(route).status_code, 503)
config.ADMIN_USER = USERNAME
config.ADMIN_PASSWORD_HASH = admin.hash_password(PASSWORD, iterations=2)
config.ADMIN_COOKIE_SECURE = False
admin.configure(app)
admin.reset_rate_limit()
CSRF_RE = re.compile(r'name="csrf" value="([^"]+)"')
with app.test_client() as client:
    r = client.get("/admin/leads")
    eq("the page redirects to login", r.status_code, 302)
    check("  to the login page", "/admin/login" in r.headers.get("Location", ""))
    r = client.get("/admin/leads.csv?vertical=blinds")
    eq("the export redirects to login too — it holds addresses",
       r.status_code, 302)
    r = client.get("/admin/api/leads")
    eq("the api answers 401", r.status_code, 401)
    check("  no statement was issued for any of them", not statements)

    token = CSRF_RE.search(client.get("/admin/login").get_data(as_text=True))
    r = client.post("/admin/login", data={"csrf": token.group(1),
                                          "username": USERNAME,
                                          "password": PASSWORD})
    eq("signed in", r.status_code, 302)

    print("\n--- the page ---")
    r = client.get("/admin/leads")
    body = r.get_data(as_text=True)
    eq("200 signed in", r.status_code, 200)
    check("  no-store, like every other page here",
          r.headers.get("Cache-Control") == "private, no-store")
    check("  the nav carries the section", 'href="/admin/leads"' in body
          and 'href="/admin/leads.csv"' in body)
    api = client.get("/admin/api/leads").get_json()
    eq("the summary: total, today, last 7 days, this filter",
       api["counts"], {"total": 7, "today": 3, "week": 5})
    eq("  the gate conversion: submits over result views, 7 days, distinct "
       "sessions, the old view left out",
       (api["conversion"]["result_view"], api["conversion"]["lead_submit"]),
       (6, 2))
    check("  as a rate", abs(api["conversion"]["rate"] - 100.0 * 2 / 6) < 0.01
          and "33.3%" in body)
    eq("7 leads match, newest first", api["matching"], 7)
    eq("  the rows are newest first, the later row first on a tie",
       [r["email"] for r in api["rows"]],
       ["f@x.test", "c@x.test", "a@x.test", "e@x.test", "b@x.test",
        "g@x.test", "d@x.test"])
    check("  the count line", "7 leads match" in body)
    check("  a sent report reads ✓ and a time, an unsent one —",
          "✓ %s" % TODAY.strftime("%Y-%m-%d %H:%M:%S") in body
          and body.count('<td class="unsent">—</td>') == 2)
    eq("the per-market table, most leads first, with the unsent count and "
       "the last lead",
       [(g["funnel"], g["lang"], g["leads"], g["unsent"]) for g in api["groups"]],
       [("blinds", "en", 2, 0), ("blinds-hu", "hu", 2, 1),
        ("blinds-de", "de", 1, 0), ("sofa", "en", 1, 0),
        ("sofa-hu", "hu", 1, 1)])
    check("  with the time of the last one",
          api["groups"][0]["last_at"] == TODAY.strftime("%Y-%m-%d %H:%M:%S"))
    eq("the dropdowns list what the table has seen",
       api["facets"], {"verticals": ["blinds", "sofa"],
                       "langs": ["de", "en", "hu"]})

    print("\n--- the filters, combined ---")
    api = client.get("/admin/api/leads?vertical=blinds").get_json()
    eq("vertical=blinds: the master and its markets, not sofa",
       sorted(r["funnel"] for r in api["rows"]),
       ["blinds", "blinds", "blinds-de", "blinds-hu", "blinds-hu"])
    eq("  the summary follows the filter", api["counts"],
       {"total": 5, "today": 2, "week": 4})
    api = client.get("/admin/api/leads?lang=hu").get_json()
    eq("lang=hu: every hu funnel, whatever the vertical",
       sorted(r["funnel"] for r in api["rows"]),
       ["blinds-hu", "blinds-hu", "sofa-hu"])
    eq("  and its conversion has no funnel on disk to count: zero, not a "
       "crash", api["conversion"], {"result_view": 0, "lead_submit": 0,
                                   "rate": 0.0})
    api = client.get("/admin/api/leads?vertical=blinds&lang=hu").get_json()
    eq("both: the one market of the one vertical",
       [r["email"] for r in api["rows"]], ["c@x.test", "d@x.test"])
    api = client.get("/admin/api/leads?subid=tigerjar_article").get_json()
    eq("subid contains: the article traffic across everything",
       sorted(r["email"] for r in api["rows"]),
       ["a@x.test", "c@x.test", "e@x.test", "f@x.test"])
    eq("  and the conversion is cut to that traffic too",
       (api["conversion"]["result_view"], api["conversion"]["lead_submit"]),
       (4, 1))
    api = client.get("/admin/api/leads?subid=comment").get_json()
    eq("  the comment traffic is the other family",
       sorted(r["email"] for r in api["rows"]), ["b@x.test", "d@x.test"])
    api = client.get("/admin/api/leads?vertical=blinds&lang=hu"
                     "&subid=article").get_json()
    eq("all three together", [r["email"] for r in api["rows"]], ["c@x.test"])
    api = client.get("/admin/api/leads?subid=%25").get_json()
    eq("a wildcard in the box is a character, not a wildcard",
       api["matching"], 0)
    api = client.get("/admin/api/leads?vertical=nope").get_json()
    eq("an unknown vertical matches nothing and renders", api["matching"], 0)
    r = client.get("/admin/leads?vertical=nope")
    check("  the page says so", r.status_code == 200
          and "No leads match" in r.get_data(as_text=True))
    body = client.get("/admin/leads?vertical=blinds&lang=hu&subid=article"
                      ).get_data(as_text=True)
    check("the form keeps its selections and the export link carries them",
          'value="blinds" selected' in body and 'value="hu" selected' in body
          and 'value="article"' in body
          and re.search(r'href="/admin/leads\.csv\?[^"]*vertical=blinds', body)
          and re.search(r'href="/admin/leads\.csv\?[^"]*lang=hu', body)
          and re.search(r'href="/admin/leads\.csv\?[^"]*subid=article', body))

    print("\n--- the export ---")
    r = client.get("/admin/leads.csv?vertical=blinds&lang=hu")
    eq("csv, as an attachment named for the filter",
       (r.status_code, r.mimetype,
        r.headers.get("Content-Disposition")),
       (200, "text/csv", 'attachment; filename="leads-blinds-hu.csv"'))
    rows = list(csv.reader(io.StringIO(r.get_data(as_text=True))))
    eq("  the seven columns", rows[0], list(analytics.LEAD_COLUMNS))
    eq("  the same rows the page shows, newest first, every one",
       [(row[1], row[2], row[3], row[4], row[5]) for row in rows[1:]],
       [("c@x.test", "blinds-hu", "hu", "modern_minimal", "tigerjar_article_hu"),
        ("d@x.test", "blinds-hu", "hu", "bold_statement", "comment_9")])
    check("  an unsent report is an empty cell, a sent one its time",
          rows[1][6] == "" and rows[2][6] == DAYS_AGO_20.strftime(
              "%Y-%m-%d %H:%M:%S"))
    r = client.get("/admin/leads.csv")
    eq("no filter exports everything", len(list(csv.reader(
        io.StringIO(r.get_data(as_text=True))))) - 1, 7)
    check("  named plainly", r.headers.get("Content-Disposition")
          == 'attachment; filename="leads.csv"')

    print("\n--- pagination ---")
    for n in range(120):
        lead("p%03d@x.test" % n, "sofa", "en",
             DAYS_AGO_20 - datetime.timedelta(minutes=n + 1), "comment_bulk",
             sent=DAYS_AGO_20)
    conn.commit()
    api = client.get("/admin/api/leads?vertical=sofa").get_json()
    eq("122 sofa leads, fifty a page, three pages",
       (api["matching"], len(api["rows"]), api["pages"], api["page"]),
       (122, 50, 3, 1))
    eq("  page one opens on the newest", api["rows"][0]["email"], "f@x.test")
    api3 = client.get("/admin/api/leads?vertical=sofa&page=3").get_json()
    eq("  page three holds the last 22, the oldest last",
       (len(api3["rows"]), api3["rows"][-1]["email"]), (22, "p119@x.test"))
    api2 = client.get("/admin/api/leads?vertical=sofa&page=2").get_json()
    check("  the pages do not overlap",
          not ({r["id"] for r in api["rows"]}
               & {r["id"] for r in api2["rows"]}
               & {r["id"] for r in api3["rows"]})
          and len({r["id"] for r in api["rows"] + api2["rows"] + api3["rows"]})
          == 122)
    eq("  a page past the end is the last page",
       client.get("/admin/api/leads?vertical=sofa&page=9").get_json()["page"], 3)
    eq("  a page that is not a number is the first",
       client.get("/admin/api/leads?page=x").get_json()["page"], 1)
    body = client.get("/admin/leads?vertical=sofa&page=2").get_data(as_text=True)
    check("  the page links carry the filter",
          "page 2 of 3" in body
          and re.search(r'href="/admin/leads\?[^"]*page=3[^"]*"', body)
          and re.search(r'href="/admin/leads\?[^"]*vertical=sofa', body))
    r = client.get("/admin/leads.csv?vertical=sofa")
    eq("the export is never paginated", len(list(csv.reader(
        io.StringIO(r.get_data(as_text=True))))) - 1, 122)

print("\n--- read-only, indexed ---")
offenders = [s.strip()[:60] for s in statements
             if not s.strip().lower().startswith("select")]
eq("every statement the section issued was a SELECT", offenders, [])
check("  and the filters lead with funnel and lang, the index's order",
      all(s.index("l.funnel") < s.index("l.lang") < s.index("l.subid")
          for s in statements if "l.funnel = " in s and "l.lang = " in s
          and "l.subid LIKE" in s))
check("the migration adds (funnel, lang, created_at) on leads",
      "ALTER TABLE leads ADD INDEX idx_leads_funnel_lang_created "
      "(funnel, lang, created_at);" in read("schema_migrations.sql"))
check("the export and the api are named in the admin suite's door checks",
      '"/admin/leads.csv"' in read("tests/test_admin.py")
      and '"/admin/api/leads"' in read("tests/test_admin.py"))
check("the write carve-out is still the one endpoint",
      sorted(admin.WRITE_ENDPOINTS) == ["admin.modes_post"])

print("\n%d checks, %d failed" % (checks[0], len(fails)))
for f in fails:
    print("  FAIL " + f)
sys.exit(1 if fails else 0)
