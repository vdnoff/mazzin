#!/usr/bin/env python3
"""The admin dashboard: who gets in, what the numbers say, and what it writes.

Three claims, and the third is the one worth the machinery:

  1. Nothing behind /admin answers without a session, the credentials are
     checked in constant time against a hash in .env, the door stops answering
     after a handful of wrong passwords, and a server with no credentials
     configured says 503 rather than opening.

  2. The numbers are right. Not "plausible" — right: a fixture of hand-written
     sessions with counts worked out on paper, asserted as literals. A funnel
     dashboard that is approximately correct is a dashboard that gets an ad
     account turned off.

  3. It never writes. Every statement the routes reach is captured and read;
     `database.execute` and `execute_rowcount` are replaced with functions that
     fail this suite if anything calls them.

No MySQL, no network, no Stripe. The seeded database is sqlite in memory,
standing in for MySQL so the real SQL in analytics.py is the thing under test
rather than a mock of it — the two JSON functions the variant query needs are
registered with MySQL's semantics, which is the only place the dialects touch.

    python3 tests/test_admin.py
"""
import datetime
import io
import json
import os
import re
import sqlite3
import sys
import contextlib

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, REPO)
sys.path.insert(0, os.path.join(REPO, "scripts"))

import admin           # noqa: E402
import analytics       # noqa: E402
import config          # noqa: E402
import database        # noqa: E402
import paywall_variant_stats as cli   # noqa: E402
from app import app    # noqa: E402

fails = []
checks = [0]


def check(label, ok, detail=""):
    checks[0] += 1
    if not ok:
        fails.append("%s %s" % (label, detail))
    print("  %-62s %s%s" % (label, "ok" if ok else "FAIL",
                            ("  " + str(detail)) if not ok else ""))


def eq(label, got, want):
    check(label, got == want, "got %r want %r" % (got, want))


# --- a database that is not a database --------------------------------------

sqlite3.register_adapter(
    datetime.datetime, lambda value: value.strftime("%Y-%m-%d %H:%M:%S"))

# Write verbs, looked for in every statement the dashboard issues. The list is
# the point of the read-only claim: it is not "we did not mean to write", it is
# "nothing that could write was sent".
WRITE_WORDS = ("insert", "update", "delete", "replace", "drop", "alter",
               "create", "truncate", "grant")


def _json_extract(doc, path):
    """MySQL's JSON_EXTRACT: returns a JSON *value*, quotes and all.

    sqlite's own `json_extract` unquotes a string on the way out, which would
    make the JSON_UNQUOTE around it in the real query a no-op — and a test that
    no-ops the one function the variant query depends on is not testing it.
    """
    if doc is None or not path.startswith("$."):
        return None
    try:
        node = json.loads(doc)
    except (ValueError, TypeError):
        return None
    if not isinstance(node, dict):
        return None
    if path[2:] not in node:
        return None
    return json.dumps(node[path[2:]])


def _json_unquote(value):
    """MySQL's JSON_UNQUOTE: a JSON string becomes a plain one."""
    if value is None:
        return None
    try:
        node = json.loads(value)
    except (ValueError, TypeError):
        return value
    return node if isinstance(node, str) else value


class Rig:
    """Seeded events and purchases, and a record of what was asked of them."""

    def __init__(self):
        self.conn = sqlite3.connect(":memory:")
        self.conn.row_factory = sqlite3.Row
        self.conn.create_function("JSON_EXTRACT", 2, _json_extract)
        self.conn.create_function("JSON_UNQUOTE", 1, _json_unquote)
        self.conn.executescript("""
            CREATE TABLE events (
              id INTEGER PRIMARY KEY AUTOINCREMENT,
              created_at TEXT NOT NULL,
              funnel TEXT NOT NULL,
              session_id TEXT NOT NULL,
              event TEXT NOT NULL,
              step INTEGER,
              subid TEXT,
              extra TEXT
            );
            CREATE TABLE purchases (
              id INTEGER PRIMARY KEY AUTOINCREMENT,
              created_at TEXT NOT NULL,
              funnel TEXT NOT NULL,
              session_id TEXT NOT NULL,
              amount_cents INTEGER NOT NULL,
              currency TEXT NOT NULL,
              status TEXT NOT NULL
            );
        """)
        self.statements = []
        self.writes = []
        # Flipped on only around the one route that is allowed to write. Off,
        # any write at all fails the suite where it happens rather than at the
        # end, so the traceback names the route that did it.
        self.writes_allowed = False
        self.overrides = {}

    # -- what analytics.py calls
    def query_all(self, sql, params=None):
        self.statements.append(sql)
        # The override table has no sqlite twin: it is a dict here, because
        # what this suite needs from it is a thing it can toggle mid-test.
        if "funnel_mode_overrides" in sql:
            return list(self.overrides.values())
        cur = self.conn.execute(sql.replace("%s", "?"), tuple(params or ()))
        return [dict(row) for row in cur.fetchall()]

    def query_one(self, sql, params=None):
        if "funnel_mode_overrides" in sql:
            self.statements.append(sql)
            return self.overrides.get(params[0])
        rows = self.query_all(sql, params)
        return rows[0] if rows else None

    def execute(self, sql, params=None):
        self.writes.append(sql)
        if not self.writes_allowed:
            raise AssertionError("a read-only admin route called "
                                 "database.execute")
        if "funnel_mode_overrides" in sql:
            self.apply_override(sql, params)
        return 1

    def execute_rowcount(self, sql, params=None):
        self.writes.append(sql)
        raise AssertionError(
            "the admin dashboard called database.execute_rowcount")

    def apply_override(self, sql, params):
        if sql.strip().upper().startswith("INSERT"):
            self.overrides[params[0]] = {
                "funnel": params[0], "mode": params[1],
                "changed_at": None, "changed_by": params[2]}
        else:
            self.overrides.pop(params[0], None)

    # -- seeding
    def event(self, funnel, session_id, event, when, subid=None, step=None,
              extra=None):
        self.conn.execute(
            "INSERT INTO events (created_at, funnel, session_id, event, step,"
            " subid, extra) VALUES (?, ?, ?, ?, ?, ?, ?)",
            (when.strftime("%Y-%m-%d %H:%M:%S"), funnel, session_id, event,
             step, subid, json.dumps(extra) if extra is not None else None))
        self.conn.commit()

    def purchase(self, funnel, session_id, when, cents=300, currency="usd",
                 status="paid"):
        self.conn.execute(
            "INSERT INTO purchases (created_at, funnel, session_id,"
            " amount_cents, currency, status) VALUES (?, ?, ?, ?, ?, ?)",
            (when.strftime("%Y-%m-%d %H:%M:%S"), funnel, session_id, cents,
             currency, status))
        self.conn.commit()

    def walk(self, funnel, session_id, when, subid=None, swipes=0,
             result=False, paywall=False, pay_tap=False, share=False,
             variant=None, purchase=None):
        """One reader's whole visit, in the order the client would send it."""
        self.event(funnel, session_id, "funnel_start", when, subid)
        for step in range(1, swipes + 1):
            self.event(funnel, session_id, "swipe", when, subid, step=step)
        if result:
            self.event(funnel, session_id, "result_view", when, subid)
        if variant:
            self.event(funnel, session_id, "paywall_variant", when, subid,
                       extra={"variant": variant})
        if paywall:
            self.event(funnel, session_id, "paywall_view", when, subid,
                       extra={"src": "scroll"})
        if share:
            self.event(funnel, session_id, "share_tap", when, subid,
                       extra={"persona": "x"})
        if pay_tap:
            self.event(funnel, session_id, "pay_tap", when, subid)
        if purchase:
            cents, currency, status, paid_at = purchase
            self.purchase(funnel, session_id, paid_at, cents, currency, status)


rig = Rig()
database.query_all = rig.query_all
database.query_one = rig.query_one
database.execute = rig.execute
database.execute_rowcount = rig.execute_rowcount


# --- the fixture ------------------------------------------------------------
# Four buckets, chosen so each range selector includes exactly one more of
# them. Midnight-anchored rather than now-anchored so the suite means the same
# thing at 00:01 as it does at 23:59.

NOW = datetime.datetime.now()
MIDNIGHT = NOW.replace(hour=0, minute=0, second=0, microsecond=0)
TODAY = MIDNIGHT + datetime.timedelta(seconds=1)
WEEK = MIDNIGHT - datetime.timedelta(days=3) + datetime.timedelta(hours=12)
MONTH = MIDNIGHT - datetime.timedelta(days=20) + datetime.timedelta(hours=12)
ANCIENT = MIDNIGHT - datetime.timedelta(days=45) + datetime.timedelta(hours=12)

PAID_TODAY = (300, "usd", "paid", TODAY)
PENDING_TODAY = (300, "usd", "pending", TODAY)
PAID_WEEK = (300, "usd", "paid", WEEK)

# kitchen — today
rig.walk("kitchen", "k1", TODAY, "fb-a", swipes=13, result=True,
         paywall=True, pay_tap=True, purchase=PAID_TODAY)
rig.walk("kitchen", "k2", TODAY, "fb-a", swipes=13, result=True,
         paywall=True, pay_tap=True, purchase=PAID_TODAY)
rig.walk("kitchen", "k3", TODAY, "fb-a", swipes=8, result=True, paywall=True)
rig.walk("kitchen", "k4", TODAY, "fb-a", swipes=5, result=True)
rig.walk("kitchen", "k5", TODAY, "fb-b", swipes=13, paywall=True,
         pay_tap=True, purchase=PENDING_TODAY)
rig.walk("kitchen", "k6", TODAY, "fb-b", swipes=3)
rig.walk("kitchen", "k7", TODAY, None, swipes=1)
# kitchen — inside 7 days, not today
rig.walk("kitchen", "kw1", WEEK, "fb-a", swipes=13, result=True, paywall=True,
         pay_tap=True, purchase=PAID_WEEK)
rig.walk("kitchen", "kw2", WEEK, "fb-b", swipes=2)
# kitchen — inside 30 days, and the sale it made today. Its start row is
# outside today's window, which is what `(unattributed)` is for.
rig.walk("kitchen", "k8", MONTH, "old", swipes=13, result=True, paywall=True,
         pay_tap=True, purchase=PAID_TODAY)
# kitchen — older than every range on the page
rig.walk("kitchen", "ko1", ANCIENT, "ancient", swipes=13, result=True)

# persona — today, with both paywall arms in play
rig.walk("persona", "p1", TODAY, "ig-1", swipes=13, result=True, share=True,
         variant="why", paywall=True, pay_tap=True, purchase=PAID_TODAY)
rig.walk("persona", "p2", TODAY, "ig-1", swipes=13, result=True, share=True,
         variant="why", paywall=True)
rig.walk("persona", "p3", TODAY, "ig-1", swipes=6, result=True, variant="why")
rig.walk("persona", "p4", TODAY, "ig-2", swipes=13, result=True,
         variant="advantage", paywall=True, pay_tap=True,
         purchase=PAID_TODAY)
rig.walk("persona", "p5", TODAY, "ig-2", swipes=4, result=True,
         variant="advantage")


# --- the app ----------------------------------------------------------------

USERNAME = "owner"
PASSWORD = "correct horse battery staple"
# Two iterations rather than 240,000: this is the same code path, and a suite
# that spends a second per login attempt is a suite nobody runs.
PASSWORD_HASH = admin.hash_password(PASSWORD, iterations=2)

config.ADMIN_USER = USERNAME
config.ADMIN_PASSWORD_HASH = PASSWORD_HASH
config.ADMIN_COOKIE_SECURE = False      # the test client speaks http
admin.configure(app)

# Both key trios, so the mode switch's safety rail is satisfied and the toggle
# under test is the toggle rather than the refusal. The refusal has its own
# check below, and test_stripemode.py owns the rest of that behaviour.
for _name in ("STRIPE_SECRET_KEY", "STRIPE_WEBHOOK_SECRET",
              "STRIPE_PUBLISHABLE_KEY", "STRIPE_TEST_SECRET_KEY",
              "STRIPE_TEST_WEBHOOK_SECRET", "STRIPE_TEST_PUBLISHABLE_KEY"):
    setattr(config, _name, "notreal_" + _name.lower())

PAGE_ROUTES = ["/admin", "/admin/", "/admin/funnel/kitchen"]
API_ROUTES = ["/admin/api/overview", "/admin/api/funnels",
              "/admin/api/funnel/kitchen", "/admin/api/variants/persona"]
ALL_ROUTES = PAGE_ROUTES + API_ROUTES

CSRF_RE = re.compile(r'name="csrf" value="([^"]+)"')


def csrf_from(client):
    """This client's current token, whether or not it is signed in.

    The login page carries one and so does the logout form on every page, and
    a signed-in client is bounced off the login page — so the second place has
    to be tried, or every post-login form in this suite would be submitting an
    empty token.
    """
    response = client.get("/admin/login")
    if response.status_code in (301, 302):
        response = client.get("/admin")
    found = CSRF_RE.search(response.get_data(as_text=True))
    return found.group(1) if found else ""


def sign_in(client, username=USERNAME, password=PASSWORD, token=None):
    token = csrf_from(client) if token is None else token
    return client.post("/admin/login", data={
        "csrf": token, "username": username, "password": password})


# --- 1. the door ------------------------------------------------------------

print("\n--- unconfigured ---")
config.ADMIN_USER = ""
config.ADMIN_PASSWORD_HASH = ""
admin.configure(app)
with app.test_client() as client:
    for route in ALL_ROUTES + ["/admin/login"]:
        eq("503 with no credentials: %s" % route,
           client.get(route).status_code, 503)
    body = client.get("/admin/api/overview").get_json()
    eq("503 names the missing setting", body.get("error"), "not_configured")
    check("503 page says what to set",
          "ADMIN_PASSWORD_HASH" in client.get("/admin").get_data(as_text=True))

config.ADMIN_USER = USERNAME
config.ADMIN_PASSWORD_HASH = PASSWORD_HASH
admin.configure(app)

print("\n--- unauthenticated ---")
admin.reset_rate_limit()
with app.test_client() as client:
    for route in PAGE_ROUTES:
        response = client.get(route)
        eq("page redirects to login: %s" % route, response.status_code, 302)
        check("redirect target is the login page: %s" % route,
              "/admin/login" in response.headers.get("Location", ""),
              response.headers.get("Location"))
    for route in API_ROUTES:
        response = client.get(route)
        eq("api answers 401: %s" % route, response.status_code, 401)
        eq("api 401 is json: %s" % route,
           (response.get_json() or {}).get("error"), "unauthenticated")
    eq("login page is reachable", client.get("/admin/login").status_code, 200)

print("\n--- passwords ---")
check("hash round trips", admin.verify_password(PASSWORD, PASSWORD_HASH))
check("a wrong password does not",
      not admin.verify_password("wrong", PASSWORD_HASH))
check("an empty hash accepts nothing",
      not admin.verify_password(PASSWORD, ""))
check("a corrupt hash accepts nothing",
      not admin.verify_password(PASSWORD, "pbkdf2_sha256$notanumber$a$b"))
check("two hashes of one password differ (salted)",
      admin.hash_password(PASSWORD, iterations=2)
      != admin.hash_password(PASSWORD, iterations=2))
check("the right password with the wrong user is refused",
      not admin.check_login("someone", PASSWORD))
check("the wrong password with the right user is refused",
      not admin.check_login(USERNAME, "nope"))
check("both right is accepted", admin.check_login(USERNAME, PASSWORD))

print("\n--- login ---")
admin.reset_rate_limit()
with app.test_client() as client:
    eq("wrong password is 401", sign_in(client, password="nope").status_code,
       401)
    eq("wrong username is 401",
       sign_in(client, username="nobody").status_code, 401)
    eq("a missing csrf token is 400",
       client.post("/admin/login",
                   data={"username": USERNAME,
                         "password": PASSWORD}).status_code, 400)
    eq("a wrong csrf token is 400",
       sign_in(client, token="not-the-token").status_code, 400)
    eq("still not signed in after a bad csrf",
       client.get("/admin/api/overview").status_code, 401)

    response = sign_in(client)
    eq("the right password redirects", response.status_code, 302)
    eq("...to the dashboard",
       response.headers.get("Location", "").endswith("/admin"), True)
    eq("the dashboard now answers", client.get("/admin").status_code, 200)
    eq("the api now answers",
       client.get("/admin/api/overview").status_code, 200)

    eq("a logout with a stale token is refused",
       client.post("/admin/logout",
                   data={"csrf": "not-the-token"}).status_code, 400)
    eq("and it really did not log out",
       client.get("/admin/api/overview").status_code, 200)
    eq("logout ends the session",
       client.post("/admin/logout",
                   data={"csrf": csrf_from(client)}).status_code, 302)
    eq("and the api stops answering",
       client.get("/admin/api/overview").status_code, 401)

print("\n--- the cookie ---")
admin.reset_rate_limit()
with app.test_client() as client:
    fresh = app.test_client()
    token = csrf_from(fresh)
    login = fresh.post("/admin/login", data={
        "csrf": token, "username": USERNAME, "password": PASSWORD})
    header = ""
    for line in login.headers.getlist("Set-Cookie"):
        if line.startswith("mazzin_admin="):
            header = line
    check("the session cookie is named for the dashboard", bool(header),
          header)
    check("httponly", "HttpOnly" in header, header)
    check("samesite", "SameSite=Lax" in header, header)
    check("scoped to /admin", "Path=/admin" in header, header)
    check("it expires", "Expires=" in header, header)

config.ADMIN_COOKIE_SECURE = True
admin.configure(app)
secure_client = app.test_client()
admin.reset_rate_limit()
login = secure_client.post("/admin/login", data={
    "csrf": csrf_from(secure_client), "username": USERNAME,
    "password": PASSWORD})
secure_header = ""
for line in login.headers.getlist("Set-Cookie"):
    if line.startswith("mazzin_admin="):
        secure_header = line
check("secure when configured secure", "Secure" in secure_header,
      secure_header)
config.ADMIN_COOKIE_SECURE = False
admin.configure(app)

print("\n--- a changed password ends open sessions ---")
admin.reset_rate_limit()
with app.test_client() as client:
    sign_in(client)
    eq("signed in", client.get("/admin/api/overview").status_code, 200)
    config.ADMIN_PASSWORD_HASH = admin.hash_password("something else",
                                                     iterations=2)
    eq("the old cookie is no longer good",
       client.get("/admin/api/overview").status_code, 401)
config.ADMIN_PASSWORD_HASH = PASSWORD_HASH
admin.configure(app)

print("\n--- rate limit ---")
ceiling = config.ADMIN_LOGIN_MAX_ATTEMPTS
config.ADMIN_LOGIN_MAX_ATTEMPTS = 3
admin.reset_rate_limit()
with app.test_client() as client:
    codes = [sign_in(client, password="nope").status_code for _ in range(3)]
    eq("three wrong passwords are all refused", codes, [401, 401, 401])
    eq("the fourth attempt is rate limited",
       sign_in(client, password="nope").status_code, 429)
    eq("and the right password is refused too while it holds",
       sign_in(client).status_code, 429)
    eq("still locked out", client.get("/admin/api/overview").status_code, 401)

admin.reset_rate_limit()
with app.test_client() as client:
    eq("a reset lets the right password back in",
       sign_in(client).status_code, 302)

# A successful login clears that client's failures, so a fat-fingered
# password earlier in the day does not count against them later.
admin.reset_rate_limit()
with app.test_client() as client:
    sign_in(client, password="nope")
    sign_in(client, password="nope")
    sign_in(client)
    codes = [sign_in(client, password="nope").status_code for _ in range(3)]
    eq("a success clears the count", codes, [401, 401, 401])
config.ADMIN_LOGIN_MAX_ATTEMPTS = ceiling

# The global bucket, which is the one a client rotating its address cannot
# step around.
global_ceiling = config.ADMIN_LOGIN_MAX_ATTEMPTS_GLOBAL
config.ADMIN_LOGIN_MAX_ATTEMPTS_GLOBAL = 2
admin.reset_rate_limit()
admin.record_failure("10.0.0.1")
admin.record_failure("10.0.0.2")
check("the global bucket trips for an address that never failed",
      admin.rate_limited("10.0.0.3"))
config.ADMIN_LOGIN_MAX_ATTEMPTS_GLOBAL = global_ceiling
admin.reset_rate_limit()

# The buckets are in memory in a worker that lives for weeks, so the table
# they live in has to empty itself. A spray of addresses that all aged out
# must not still be occupying keys.
admin.reset_rate_limit()
old_clock = 1000.0
for n in range(admin.ATTEMPT_KEYS_MAX + 50):
    admin.record_failure("10.1.%d.%d" % (n // 256, n % 256), now=old_clock)
check("a spray of addresses is tracked",
      len(admin._attempts) > admin.ATTEMPT_KEYS_MAX, len(admin._attempts))
admin.record_failure("10.9.9.9",
                     now=old_clock + config.ADMIN_LOGIN_WINDOW_S + 1)
check("...and swept once they age out",
      len(admin._attempts) < 10, len(admin._attempts))
check("a client whose attempts expired is not asked to pay for them",
      not admin.rate_limited("10.1.0.1",
                             now=old_clock + config.ADMIN_LOGIN_WINDOW_S + 1))
admin.reset_rate_limit()


# --- 2. the numbers ---------------------------------------------------------

client = app.test_client()
sign_in(client)


def api(path, **params):
    query = "&".join("%s=%s" % item for item in params.items())
    response = client.get(path + ("?" + query if query else ""))
    return response.status_code, response.get_json()


print("\n--- overview ---")
status, data = api("/admin/api/overview", range="today", audience="all")
eq("overview answers", status, 200)
rows = {row["slug"]: row for row in data["funnels"]}
eq("every configured funnel has a row, live or dead",
   sorted(rows), ["kitchen", "kitchen-visualizer", "persona", "zodiac",
                  "zodiac-ro", "zodiac30"])
eq("a funnel with no traffic still shows",
   rows["zodiac"]["funnel_start"], 0)

kitchen = rows["kitchen"]
eq("kitchen starts today", kitchen["funnel_start"], 7)
eq("kitchen result views", kitchen["result_view"], 4)
eq("kitchen paywall views", kitchen["paywall_view"], 4)
eq("kitchen pay taps", kitchen["pay_tap"], 3)
eq("kitchen sales exclude the pending row", kitchen["purchases"], 3)
eq("kitchen revenue in cents",
   [(cell["currency"], cell["cents"]) for cell in kitchen["revenue"]],
   [("usd", 900)])
eq("kitchen revenue reads as money", kitchen["revenue_display"], "$9.00")
check("conversion is sales over starts",
      abs(kitchen["conversion"] - 300.0 / 7) < 1e-9, kitchen["conversion"])
check("result rate is result views over starts",
      abs(kitchen["result_rate"] - 400.0 / 7) < 1e-9, kitchen["result_rate"])
eq("paywall to pay rate", kitchen["pay_rate"], 75.0)

persona = rows["persona"]
eq("persona starts today", persona["funnel_start"], 5)
eq("persona paywall views", persona["paywall_view"], 3)
eq("persona sales", persona["purchases"], 2)
check("persona is flagged as running a test", persona["has_variants"])

totals = data["totals"]
eq("totals add the funnels up", totals["funnel_start"], 12)
eq("totals count every sale", totals["purchases"], 5)
eq("totals sum revenue", totals["revenue_display"], "$15.00")

print("\n--- date ranges ---")
for window, expected in (("today", 7), ("7d", 9), ("30d", 10)):
    status, data = api("/admin/api/overview", range=window)
    rows = {row["slug"]: row for row in data["funnels"]}
    eq("kitchen starts over %s" % window, rows["kitchen"]["funnel_start"],
       expected)
eq("nothing older than 30 days leaks in",
   api("/admin/api/overview", range="30d")[1]["range"]["range"], "30d")

first = (MIDNIGHT - datetime.timedelta(days=3)).strftime("%Y-%m-%d")
status, data = api("/admin/api/overview", **{"range": "custom",
                                             "from": first, "to": first})
rows = {row["slug"]: row for row in data["funnels"]}
eq("a custom single day sees only that day",
   rows["kitchen"]["funnel_start"], 2)
eq("the custom range is echoed back", data["range"]["range"], "custom")
eq("a broken custom range falls back rather than erroring",
   api("/admin/api/overview", **{"range": "custom", "from": "banana"})[1]
   ["range"]["range"], "7d")
eq("an unknown range falls back too",
   api("/admin/api/overview", range="all-time")[1]["range"]["range"], "7d")

print("\n--- funnel detail ---")
# The dashboard defaults to paid traffic now, so the blocks below that count
# every session — the `(none)` row, the unattributed sale, the drop-off over
# all arrivals — ask for all traffic by name. What the default does is checked
# on its own further down; conflating the two would leave both untested.
status, detail = api("/admin/api/funnel/kitchen", range="today",
                     audience="all")
eq("detail answers", status, 200)
steps = {row["step"]: row["sessions"] for row in detail["steps"]}
eq("every step the config declares has a row", len(detail["steps"]), 13)
eq("step 1 drop-off", steps[1], 7)
eq("step 2 drop-off", steps[2], 6)
eq("step 4 drop-off", steps[4], 5)
eq("step 6 drop-off", steps[6], 4)
eq("step 9 drop-off", steps[9], 3)
eq("step 13 drop-off", steps[13], 3)
first_step = detail["steps"][0]
eq("the first bar is full", first_step["of_first"], 100.0)
last_step = detail["steps"][-1]
check("the last bar is three sevenths of it",
      abs(last_step["of_first"] - 300.0 / 7) < 1e-9, last_step["of_first"])
check("of-starts is measured against starts, not against step one",
      abs(last_step["of_start"] - 300.0 / 7) < 1e-9, last_step["of_start"])

subids = {row["subid"]: row for row in detail["subids"]}
eq("the campaigns that ran", sorted(subids),
   ["(none)", "(unattributed)", "fb-a", "fb-b"])
eq("fb-a starts", subids["fb-a"]["funnel_start"], 4)
eq("fb-a result views", subids["fb-a"]["result_view"], 4)
eq("fb-a paywall views", subids["fb-a"]["paywall_view"], 3)
eq("fb-a pay taps", subids["fb-a"]["pay_tap"], 2)
eq("fb-a sales", subids["fb-a"]["purchases"], 2)
eq("fb-a revenue", subids["fb-a"]["revenue_display"], "$6.00")
eq("fb-a conversion", subids["fb-a"]["conversion"], 50.0)
eq("fb-b starts", subids["fb-b"]["funnel_start"], 2)
eq("fb-b made no sale — its one purchase is still pending",
   subids["fb-b"]["purchases"], 0)
eq("a session with no subid gets its own row",
   subids["(none)"]["funnel_start"], 1)
eq("a sale whose session started earlier is not lost",
   subids["(unattributed)"]["purchases"], 1)
eq("and its revenue is shown", subids["(unattributed)"]["revenue_display"],
   "$3.00")
eq("the subid rows add up to the funnel's sales",
   sum(row["purchases"] for row in detail["subids"]), detail["purchases"])
eq("kitchen emits no share event, so the column is absent",
   detail["share_tap"], None)
eq("kitchen runs no test, so there is no panel", detail["variants"], None)

status, detail = api("/admin/api/funnel/persona", range="today",
                     audience="all")
eq("persona counts its shares", detail["share_tap"], 2)
eq("an unknown funnel is a 404",
   api("/admin/api/funnel/nonesuch")[0], 404)
eq("an unknown funnel is a 404 on the page too",
   client.get("/admin/funnel/nonesuch").status_code, 404)

print("\n--- a/b panel ---")
status, panel = api("/admin/api/variants/persona", range="today",
                    audience="all")
eq("the panel answers", status, 200)
arms = {row["variant"]: row for row in panel["overall"]}
eq("both arms are listed", sorted(arms), ["advantage", "why"])
eq("why: shown", arms["why"]["shown"], 3)
eq("why: reached the offer", arms["why"]["reached"], 2)
eq("why: paid", arms["why"]["paid"], 1)
check("why: rate is paid over shown",
      abs(arms["why"]["rate"] - 100.0 / 3) < 1e-9, arms["why"]["rate"])
eq("advantage: shown", arms["advantage"]["shown"], 2)
eq("advantage: reached", arms["advantage"]["reached"], 1)
eq("advantage: paid", arms["advantage"]["paid"], 1)
eq("advantage: rate", arms["advantage"]["rate"], 50.0)
check("the config's enabled flag is on the row", arms["why"]["enabled"])
eq("so is its weight", arms["why"]["weight"], 1)
eq("and the share it is live at", arms["why"]["share"], 50.0)
check("an arm the config declares is marked declared",
      arms["why"]["declared"])

by_subid = {(row["variant"], row["subid"]): row for row in panel["by_subid"]}
eq("why split by campaign", by_subid[("why", "ig-1")]["shown"], 3)
eq("advantage split by campaign",
   by_subid[("advantage", "ig-2")]["shown"], 2)

eq("the detail page carries the same panel",
   api("/admin/api/funnel/persona", range="today",
       audience="all")[1]["variants"]["overall"],
   panel["overall"])

print("\n--- the panel and the console script agree ---")
window = admin.resolve_range({"range": "today"})
shared = analytics.variant_rows("persona", window["start"], window["end"])
folded = {row["variant"]: row for row in analytics.fold_variants(shared)}
for name in ("why", "advantage"):
    eq("%s: shown matches the shared query" % name,
       arms[name]["shown"], int(folded[name]["shown"]))
    eq("%s: paid matches the shared query" % name,
       arms[name]["paid"], int(folded[name]["paid"]))

cli_rows = cli.rows_for("persona", 0)
cli_folded = {row["variant"]: row for row in cli.fold(cli_rows)}
eq("the script sees the same arms", sorted(cli_folded), ["advantage", "why"])
eq("the script's why: shown", int(cli_folded["why"]["shown"]), 3)
eq("the script's advantage: paid", int(cli_folded["advantage"]["paid"]), 1)
eq("the script's rate helper still agrees",
   cli.rate(1, 3), analytics.rate(1, 3))

captured = io.StringIO()
with contextlib.redirect_stdout(captured):
    code = cli.main(["persona", "--min", "1"])
printed = captured.getvalue()
eq("the script still exits clean", code, 0)
check("and still prints its table", "variant" in printed and "why" in printed,
      printed[:120])
captured = io.StringIO()
with contextlib.redirect_stdout(captured):
    code = cli.main(["persona", "--by-variant", "--min", "1"])
check("--by-variant still folds", "(all)" in captured.getvalue(),
      captured.getvalue()[:120])
captured = io.StringIO()
with contextlib.redirect_stdout(captured):
    code = cli.main(["kitchen"])
eq("a funnel with no arms is not an error", code, 0)
check("and says so", "no paywall_variant events" in captured.getvalue(),
      captured.getvalue()[:120])

print("\n--- money ---")
eq("cents become a decimal, never a float", str(analytics.money(1999)),
   "19.99")
check("and it is a Decimal",
      type(analytics.money(1999)).__name__ == "Decimal")
eq("a symbol currency", analytics.format_money(300, "usd"), "$3.00")
eq("a currency with no symbol prints its code",
   analytics.format_money(999, "ron"), "9.99 RON")
eq("zero is still money", analytics.format_money(0, "usd"), "$0.00")

print("\n--- pages render ---")
for route in PAGE_ROUTES + ["/admin/funnel/persona"]:
    response = client.get(route + "?range=today")
    eq("200: %s" % route, response.status_code, 200)
    body = response.get_data(as_text=True)
    check("no cache: %s" % route,
          response.headers.get("Cache-Control") == "private, no-store",
          response.headers.get("Cache-Control"))
    check("not indexable: %s" % route,
          "noindex" in response.headers.get("X-Robots-Tag", ""))
    check("not frameable: %s" % route,
          response.headers.get("X-Frame-Options") == "DENY")
    check("mobile viewport: %s" % route, "width=device-width" in body)
body = client.get("/admin?range=today").get_data(as_text=True)
check("the overview names every funnel",
      all(slug in body for slug in
          ("kitchen", "persona", "zodiac30", "zodiac-ro")))
check("and prints the revenue", "$9.00" in body, )
body = client.get("/admin/funnel/persona?range=today").get_data(as_text=True)
check("the detail page draws the a/b panel",
      "why" in body and "advantage" in body)
check("and the drop-off bars", "class=\"fill\"" in body)


# --- 3. it never writes -----------------------------------------------------

print("\n--- the mode switch is behind the same door ---")
admin.reset_rate_limit()
with app.test_client() as stranger:
    response = stranger.get("/admin/modes")
    eq("logged out, the page redirects to login", response.status_code, 302)
    check("...to the login page",
          "/admin/login" in response.headers.get("Location", ""))
    eq("logged out, the write is refused too",
       stranger.post("/admin/modes", data={"funnel": "kitchen",
                                           "action": "set",
                                           "mode": "test"}).status_code, 302)
eq("nothing was written by a logged-out caller", rig.overrides, {})

modes_body = client.get("/admin/modes").get_data(as_text=True)
eq("logged in, the page answers",
   client.get("/admin/modes").status_code, 200)
check("it lists every funnel",
      all(slug in modes_body for slug in
          ("kitchen", "persona", "zodiac30", "zodiac-ro")))
check("the dashboard links to it",
      "/admin/modes" in client.get("/admin").get_data(as_text=True))
modes_csrf = re.search(r'name="csrf" value="([^"]+)"', modes_body).group(1)
eq("a post with no csrf token is refused",
   client.post("/admin/modes", data={"funnel": "kitchen", "action": "set",
                                     "mode": "test"}).status_code, 400)
eq("and nothing was written", rig.overrides, {})


print("\n--- read-only, and the one route that is not ---")
# Everything above this line was a GET. Nothing in it may have written.
eq("nothing reached the write helpers", rig.writes, [])
check("something was actually asked", len(rig.statements) > 20,
      len(rig.statements))


def select_offenders(statements):
    """Statements that are not a plain SELECT."""
    out = []
    for statement in statements:
        head = statement.strip().lower()
        if not head.startswith("select"):
            out.append(statement.strip()[:60])
            continue
        words = re.findall(r"[a-z_]+", head)
        for word in WRITE_WORDS:
            if word in words:
                out.append(statement.strip()[:60])
                break
    return out


eq("every statement the dashboard issued was a SELECT",
   select_offenders(rig.statements), [])

# The carve-out, stated rather than assumed: exactly one endpoint may write,
# and this is the list the guarantee is written against.
eq("exactly one admin endpoint is allowed to write",
   sorted(admin.WRITE_ENDPOINTS), ["admin.modes_post"])
writers = sorted(rule.endpoint for rule in app.url_map.iter_rules()
                 if rule.endpoint.startswith("admin.")
                 and "POST" in (rule.methods or set()))
eq("and the only admin POSTs are login, logout and that one",
   writers, ["admin.login_post", "admin.logout", "admin.modes_post"])

# Now the exception itself. The spy stops being a landmine for exactly the
# span of one request, and what that request writes is read back out.
rig.statements = []
rig.writes = []
rig.writes_allowed = True
toggle = client.post("/admin/modes", data={
    "csrf": modes_csrf, "funnel": "kitchen", "action": "set", "mode": "test"})
rig.writes_allowed = False
eq("the toggle redirects", toggle.status_code, 302)
eq("it wrote exactly once", len(rig.writes), 1)
check("and what it wrote was an override row",
      "funnel_mode_overrides" in rig.writes[0], rig.writes[0][:60])
eq("the row names the funnel and the mode",
   (rig.overrides["kitchen"]["funnel"], rig.overrides["kitchen"]["mode"]),
   ("kitchen", "test"))
eq("changed_by is the admin who was logged in",
   rig.overrides["kitchen"]["changed_by"], USERNAME)
check("the page now shows the funnel in test",
      ">TEST<" in client.get("/admin/modes").get_data(as_text=True))

rig.writes = []
rig.writes_allowed = True
client.post("/admin/modes", data={"csrf": modes_csrf, "funnel": "kitchen",
                                  "action": "clear"})
rig.writes_allowed = False
eq("clearing writes once too", len(rig.writes), 1)
eq("and the override is gone", rig.overrides, {})

# A switch the keys cannot support must not write at all — not a row that
# claims a mode the funnel cannot transact in.
held = config.STRIPE_TEST_WEBHOOK_SECRET
config.STRIPE_TEST_WEBHOOK_SECRET = ""
rig.writes = []
refused = client.post("/admin/modes", data={
    "csrf": modes_csrf, "funnel": "kitchen", "action": "set", "mode": "test"})
eq("a switch into a mode with a missing key redirects",
   refused.status_code, 302)
eq("and writes nothing at all", rig.writes, [])
eq("and leaves no override behind", rig.overrides, {})
config.STRIPE_TEST_WEBHOOK_SECRET = held

# The guarantee is worth something only if the spy would have caught a write,
# so prove the spy works.
tripped = False
try:
    database.execute("INSERT INTO events (funnel) VALUES (\'x\')")
except AssertionError:
    tripped = True
check("the spy catches a write from anywhere else", tripped)


print("\n--- paid traffic only, which is what the dashboard is for ---")
# Four arrivals on one funnel, one of each kind the definition has to tell
# apart. Seeded here rather than reused from above so the counts are exact.
rig.walk("zodiac", "paid-1", TODAY, "fb-ad-42", swipes=13, result=True,
         paywall=True, pay_tap=True, purchase=(300, "usd", "paid", TODAY))
rig.walk("zodiac", "share-1", TODAY, "share-open_flame", swipes=13,
         result=True, paywall=True, pay_tap=True, purchase=(300, "usd", "paid", TODAY))
rig.walk("zodiac", "direct-1", TODAY, None, swipes=13, result=True,
         paywall=True, pay_tap=True, purchase=(300, "usd", "paid", TODAY))
rig.walk("zodiac", "empty-1", TODAY, "", swipes=13, result=True,
         paywall=True, pay_tap=True, purchase=(300, "usd", "paid", TODAY))

check("one definition, in one place",
      hasattr(analytics, "paid_sessions_clause")
      and analytics.SHARE_SUBID_PREFIX == "share-")
# The four cases, run as SQL rather than asserted about in prose.
for label, subid, want in (("a real ad click", "fb-ad-42", True),
                           ("a share arrival", "share-open_flame", False),
                           ("a direct visit", None, False),
                           ("an empty subid", "", False)):
    counts = analytics.event_counts("zodiac", events=("funnel_start",),
                                    paid_only=True)
    seen = rig.conn.execute(
        "SELECT COUNT(*) AS n FROM events WHERE funnel='zodiac'"
        " AND event='funnel_start' AND session_id=?"
        " AND subid IS NOT NULL AND subid <> ''"
        " AND subid NOT LIKE 'share-%'",
        ({"fb-ad-42": "paid-1", "share-open_flame": "share-1",
          None: "direct-1", "": "empty-1"}[subid],)).fetchone()["n"]
    check("  %s counts as paid: %s" % (label, want), bool(seen) is want)

all_counts = analytics.event_counts("zodiac", events=("funnel_start",))
paid_counts = analytics.event_counts("zodiac", events=("funnel_start",),
                                     paid_only=True)
check("the filter changes the number", paid_counts["funnel_start"]
      < all_counts["funnel_start"],
      "%d vs %d" % (paid_counts["funnel_start"], all_counts["funnel_start"]))
check("  and keeps exactly the ad clicks",
      all_counts["funnel_start"] - paid_counts["funnel_start"] == 3,
      "%d dropped" % (all_counts["funnel_start"]
                      - paid_counts["funnel_start"]))
paid_sales = analytics.purchase_totals("zodiac", paid_only=True)
all_sales = analytics.purchase_totals("zodiac")
check("  purchases follow the same rule",
      sum(t["purchases"] for t in paid_sales)
      < sum(t["purchases"] for t in all_sales))

print("\n--- the toggle ---")
status, paid_view = api("/admin/api/funnel/zodiac", range="today",
                        audience="paid")
eq("the API takes the filter", status, 200)
eq("  and says which one it answered", paid_view.get("audience"), "paid")
status, all_view = api("/admin/api/funnel/zodiac", range="today",
                       audience="all")
eq("  the other way too", all_view.get("audience"), "all")
def starts_of(payload):
    """Arrivals, off the detail payload's own `events` block."""
    return (payload.get("events") or {}).get("funnel_start")


check("  and the numbers differ between them",
      starts_of(paid_view) < starts_of(all_view),
      "%s vs %s" % (starts_of(paid_view), starts_of(all_view)))
check("  by exactly the three arrivals that were not ad clicks",
      starts_of(all_view) - starts_of(paid_view) == 3,
      "%s vs %s" % (starts_of(all_view), starts_of(paid_view)))

# Sticky: the last explicit choice is what an unqualified request gets.
status, sticky = api("/admin/api/funnel/zodiac", range="today")
eq("the choice sticks for the session", sticky.get("audience"), "all")
status, back = api("/admin/api/funnel/zodiac", range="today", audience="paid")
eq("  and can be set back", back.get("audience"), "paid")

# A fresh client has never chosen, so it gets the default.
fresh = app.test_client()
sign_in(fresh)
first = fresh.get("/admin/api/overview?range=today").get_json()
eq("a dashboard nobody has touched shows paid only",
   first.get("audience"), "paid")

print("\n--- the toggle is on the page, not just in the payload ---")
overview_html = client.get("/admin?range=today&audience=paid").get_data(
    as_text=True)
check("the overview draws it", 'class="ranges audience"' in overview_html)
check("  offering both ways", "audience=paid" in overview_html
      and "audience=all" in overview_html)
check("  with the live one lit",
      re.search(r'audience=paid[^>]*class="on"', overview_html) is not None)
check("  and a line saying what is being counted",
      "share arrivals and direct visits excluded" in overview_html)
funnel_html = client.get(
    "/admin/funnel/kitchen?range=today&audience=paid").get_data(as_text=True)
check("the funnel page draws it too",
      'class="ranges audience"' in funnel_html)
switched = client.get("/admin?range=today&audience=all").get_data(as_text=True)
check("switching lights the other one",
      re.search(r'audience=all[^>]*class="on"', switched) is not None)
check("  and says so in the note",
      "including share arrivals and direct visits" in switched)
stuck = client.get("/admin?range=today").get_data(as_text=True)
check("  and the page keeps it without being asked again",
      re.search(r'audience=all[^>]*class="on"', stuck) is not None)
client.get("/admin?range=today&audience=paid")   # leave it as it was


print("\n--- the console and the panel agree ---")
panel = analytics.variant_rows("persona", paid_only=True)
import importlib
stats = importlib.import_module("scripts.paywall_variant_stats") \
    if False else None
sys.path.insert(0, os.path.join(REPO, "scripts"))
import paywall_variant_stats as cli          # noqa: E402
cli_rows = cli.rows_for("persona", 0, paid_only=True)
check("the CLI runs the panel's own query",
      cli_rows == panel, "%d vs %d rows" % (len(cli_rows), len(panel)))
check("  and its unfiltered numbers match too",
      cli.rows_for("persona", 0) == analytics.variant_rows("persona"))
check("  through the shared function, not a copy of the predicate",
      "paid_only=paid_only" in open(
          os.path.join(REPO, "scripts/paywall_variant_stats.py"),
          encoding="utf-8").read()
      and "NOT LIKE" not in open(
          os.path.join(REPO, "scripts/paywall_variant_stats.py"),
          encoding="utf-8").read())

print()
print("%d checks, %d failed" % (checks[0], len(fails)))
for line in fails:
    print("  FAIL %s" % line)
sys.exit(1 if fails else 0)
