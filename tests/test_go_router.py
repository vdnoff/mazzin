#!/usr/bin/env python3
"""GET /go — the ad link that resolves to whichever funnel exists.

Asserted here: the vertical + language mapping and its English special
case, both fallback tiers, that the whole query string but `v` and `l`
survives the redirect (subid and utm_* are what tracking counts), that bad
parameters are a bare 400, that the target is always a local path and never
somebody else's host, that a `-test` twin is never a destination, that a
miss is counted with one upsert and a failing count never touches the
redirect, and that nothing about the request reaches a log line.

No database: `database.execute` is replaced with a recorder, and once with
something that raises.
"""
import json
import logging
import os
import sys

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, REPO)
ROOT = REPO

import config                                   # noqa: E402
import database                                 # noqa: E402
import router                                   # noqa: E402
from app import app                             # noqa: E402

fails = []
checks = [0]


def check(label, ok, detail=""):
    checks[0] += 1
    if not ok:
        fails.append("%s %s" % (label, detail))
    print("  %-62s %s%s" % (label, "ok" if ok else "FAIL",
                            ("  " + str(detail)[:200]) if detail and not ok
                            else ""))


writes = []
database.execute = lambda q, p=None: writes.append((q, p)) or 1
client = app.test_client()


def go(query):
    writes.clear()
    r = client.get("/go" + query)
    return r.status_code, r.headers.get("Location"), r


print("\n--- the mapping ---")
check("blinds + en is the master", router.candidate_slug("blinds", "en") == "blinds")
check("blinds + hu is blinds-hu",
      router.candidate_slug("blinds", "hu") == "blinds-hu")
check("resolve: the language exists -> it, no miss",
      router.resolve("zodiac", "ro") == ("zodiac-ro", False))
check("resolve: only the master exists -> it, counted",
      router.resolve("blinds", "hu") == ("blinds", True))
check("resolve: nothing exists -> kitchen, counted",
      router.resolve("nothing", "hu") == ("kitchen", True))
check("resolve: a -test twin is never a destination",
      router.resolve("blinds", "test") == ("blinds", True)
      and router.resolve("zodiac-ro", "test") == ("zodiac-ro", True))
check("  and never as the master either",
      router.resolve("zodiac-ro-test", "en") == ("kitchen", True))
check("the default receiver is a funnel that exists",
      config.funnel_exists(router.DEFAULT_RECEIVER))

print("\n--- the redirect ---")
code, loc, r = go("?v=blinds&l=en")
check("/go?v=blinds&l=en -> 301 /blinds", code == 301 and loc == "/blinds",
      "%s %s" % (code, loc))
check("  no miss counted", writes == [])
check("  never cached: a 301 whose answer changes when a language goes live",
      r.headers.get("Cache-Control") == "no-store")
code, loc, r = go("?v=zodiac&l=ro")
check("a language that exists lands on it",
      code == 301 and loc == "/zodiac-ro" and writes == [], "%s %s" % (code, loc))
code, loc, r = go("?v=blinds&l=hu")
check("a language that does not exist yet falls back to the master",
      code == 301 and loc == "/blinds", "%s %s" % (code, loc))
check("  and is counted once", len(writes) == 1 and writes[0][1] == ("blinds", "hu"),
      str(writes))
code, loc, r = go("?v=nothere&l=de")
check("a vertical that does not exist falls back to kitchen",
      code == 301 and loc == "/kitchen", "%s %s" % (code, loc))
check("  and is counted", writes and writes[0][1] == ("nothere", "de"))
code, loc, r = go("?v=blinds")
check("no l means English", code == 301 and loc == "/blinds" and writes == [])
code, loc, r = go("?v=BLINDS&l=Hu")
check("parameters are lowercased", code == 301 and loc == "/blinds"
      and writes[0][1] == ("blinds", "hu"))
code, loc, r = go("?v=blinds&l=test")
check("a -test twin is not routed to, even when it exists on disk",
      code == 301 and loc == "/blinds" and writes[0][1] == ("blinds", "test"),
      "%s %s" % (code, loc))

print("\n--- the query string survives ---")
code, loc, r = go("?v=blinds&l=en&subid=abc123&utm_source=meta&utm_campaign=c1"
                  "&utm_content=x&utm_term=y")
check("subid and every utm ride through",
      loc == "/blinds?subid=abc123&utm_source=meta&utm_campaign=c1"
             "&utm_content=x&utm_term=y", loc)
code, loc, r = go("?subid=first&v=blinds&utm_source=s&l=hu&fbclid=z")
check("  in their original order, v and l removed wherever they sat",
      loc == "/blinds?subid=first&utm_source=s&fbclid=z", loc)
code, loc, r = go("?v=blinds&l=en&empty=&k=v")
check("  blank values are kept", loc == "/blinds?empty=&k=v", loc)
code, loc, r = go("?v=blinds&l=en&utm_campaign=summer%20sale&q=a%26b")
check("  encoded values are re-encoded, not lost",
      loc == "/blinds?utm_campaign=summer+sale&q=a%26b", loc)
check("carried_query drops only v and l",
      router.carried_query("v=x&a=1&l=y&b=2") == "a=1&b=2"
      and router.carried_query("v=x&l=y") == ""
      and router.carried_query("") == "")

print("\n--- invalid parameters are a bare 400 ---")
for q in ("", "?l=en", "?v=&l=en", "?v=../etc&l=en", "?v=blinds&l=h%C3%BC",
          "?v=" + "a" * 25 + "&l=en", "?v=blinds%2Fx&l=en", "?v=bl%20inds",
          "?v=blinds&l=en%0d%0aX", "?v=Blinds!&l=en"):
    code, loc, r = go(q)
    check("  %-32s -> 400, nothing counted" % (q or "(none)"),
          code == 400 and r.data == b"" and writes == [], "%s %s" % (code, loc))
check("the pattern is ^[a-z0-9_-]{1,24}$",
      router.PARAM_RE.pattern == "^[a-z0-9_-]{1,24}$")

print("\n--- no open redirect ---")
for q in ("?v=evil.com&l=en", "?v=%2F%2Fevil.com&l=en", "?v=blinds&l=en&next=//x",
          "?v=blinds&l=%2F%2Fevil.com", "?v=blinds&l=en&subid=//evil.com"):
    code, loc, r = go(q)
    ok = code == 400 or (loc and loc.startswith("/") and not loc.startswith("//")
                         and "://" not in loc.split("?")[0])
    check("  %-40s stays local" % q, ok, "%s %s" % (code, loc))
code, loc, r = go("?v=blinds&l=en&subid=http://x")
check("  a URL inside a carried value is still a local target",
      loc.startswith("/blinds?") and loc.split("?")[0] == "/blinds", loc)

print("\n--- the queue ---")
code, loc, r = go("?v=blinds&l=pl")
q, params = writes[0]
check("one upsert per miss", len(writes) == 1)
check("  INSERT ... ON DUPLICATE KEY UPDATE hits = hits + 1",
      q.startswith("INSERT INTO gen_queue")
      and "ON DUPLICATE KEY UPDATE hits = hits + 1" in q
      and "last_seen = NOW()" in q)
check("  parameters are the two tokens, nothing else",
      params == ("blinds", "pl"))
check("  a hit never writes", (go("?v=zodiac&l=ro"), writes == [])[1])


def boom(q, p=None):
    raise RuntimeError("no database")


database.execute = boom
log = logging.getLogger("router")
records = []
handler = logging.Handler()
handler.emit = lambda rec: records.append(rec)
log.addHandler(handler)
r = client.get("/go?v=blinds&l=da&subid=SECRET&utm_source=SRC")
log.removeHandler(handler)
check("a queue failure never breaks the redirect",
      r.status_code == 301
      and r.headers.get("Location") == "/blinds?subid=SECRET&utm_source=SRC",
      "%s %s" % (r.status_code, r.headers.get("Location")))
check("  it is logged as one warning naming the exception type",
      len(records) == 1 and records[0].levelno == logging.WARNING
      and "RuntimeError" in records[0].getMessage())
check("  with nothing from the query string in it",
      "SECRET" not in records[0].getMessage()
      and "SRC" not in records[0].getMessage()
      and "no database" not in records[0].getMessage())
database.execute = lambda q, p=None: writes.append((q, p)) or 1

print("\n--- where it lives ---")
APP = open(os.path.join(ROOT, "app.py"), encoding="utf-8").read()
ROUTER = open(os.path.join(ROOT, "router.py"), encoding="utf-8").read()
MIGRATIONS = open(os.path.join(ROOT, "schema_migrations.sql"),
                  encoding="utf-8").read()
check("app.py registers the blueprint and holds no SQL for it",
      "router_bp" in APP and "gen_queue" not in APP)
check("  the route is a static rule, so it wins over /<slug>",
      '@bp.get("/go")' in ROUTER
      and any(r.rule == "/go" for r in app.url_map.iter_rules()))
check("  /go is not a funnel slug anybody could shadow",
      not config.funnel_exists("go"))
check("the router never imports the model, Stripe or the report module",
      not any(w in ROUTER for w in ("anthropic", "stripe", "import reports",
                                    "openai")))
check("the migration creates gen_queue if it does not exist",
      "CREATE TABLE IF NOT EXISTS gen_queue" in MIGRATIONS)
check("  with the columns the upsert writes and the status enum",
      all(c in MIGRATIONS for c in ("vertical VARCHAR(24)", "lang VARCHAR(24)",
                                    "first_seen DATETIME", "last_seen DATETIME",
                                    "hits INT",
                                    "ENUM('new','generating','live','rejected')",
                                    "UNIQUE KEY uq_vertical_lang (vertical, lang)")))
check("  appended, never edited into schema.sql",
      "gen_queue" not in open(os.path.join(ROOT, "schema.sql"),
                              encoding="utf-8").read())
check("the funnel page still 404s an unknown slug and serves a known one",
      client.get("/no-such-funnel").status_code == 404
      and client.get("/kitchen").status_code == 200)

print("\n%d checks, %d failed" % (checks[0], len(fails)))
for f in fails:
    print("  FAIL " + f)
sys.exit(1 if fails else 0)
