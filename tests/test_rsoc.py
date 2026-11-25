#!/usr/bin/env python3
"""The RSOC quiz engine: its config, its routes, its event endpoint, its copy.

No database, no network. The event route's one write is recorded instead of
made; the row resolver is the one in static/js/rsoc_quiz.js, run under Node;
the copy is scanned as written in the config and as a browser draws it.

    python3 tests/test_rsoc.py
"""
import hashlib
import http.server
import itertools
import json
import os
import re
import socketserver
import subprocess
import sys
import threading

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, REPO)

import database                                            # noqa: E402

writes = []
database.execute = lambda sql, params=None: writes.append((sql, params)) or 1
database.query_one = lambda *a, **kw: None
database.query_all = lambda *a, **kw: []

import config                                              # noqa: E402
import rsoc                                                # noqa: E402
import tracking                                            # noqa: E402
from app import app                                        # noqa: E402

fails = []
checks = [0]


def check(label, ok, detail=""):
    checks[0] += 1
    if not ok:
        fails.append("%s %s" % (label, detail))
    print("  %-68s %s%s" % (label, "ok" if ok else "FAIL",
                            ("  " + str(detail)[:400]) if not ok else ""))


def read(rel):
    with open(os.path.join(REPO, rel), encoding="utf-8") as fh:
        return fh.read()


SRC = read("funnels/rsoc/benefits.json")
MIRROR = read("static/funnels/rsoc/benefits.json")
CFG = json.loads(SRC)
JS = read("static/js/rsoc_quiz.js")
PAGE = read("static/rsoc.html")
CSS = read("static/css/rsoc.css")
LOANS_CSS = read("static/css/loans.css")

print("\n--- the config ---")
check("both copies are byte for byte the same", SRC == MIRROR)
check("the slug, title, headline and sub",
      CFG["slug"] == "benefits" and CFG["title"] == "Benefits Finder"
      and CFG["headline"] == "Which assistance programs fit your household?"
      and CFG["sub"] == "Answer 4 quick questions. No application, no "
      "sign-up, no SSN.")
check("the partner's pixel", CFG["pixel_id"] == "762004311984135")
STEPS = CFG["steps"]
WANT = [
    ("need", "What do you need help with most right now?",
     [("food", "Food & groceries"), ("utilities", "Energy & utility bills"),
      ("medical", "Medical costs"), ("debt", "Debt & overdue bills")]),
    ("household", "Who's in your household?",
     [("solo", "Just me or my partner"), ("kids", "Kids under 18"),
      ("senior", "Someone 60 or older"),
      ("disability", "Someone with a disability")]),
    ("income", "Household income per month, before tax",
     [("i1", "Under $1,000"), ("i2", "$1,000 – $2,000"),
      ("i3", "$2,000 – $3,000"), ("i4", "Over $3,000")]),
    ("situation", "Your situation",
     [("employed", "Employed"), ("gig", "Self-employed or gig work"),
      ("unemployed", "Unemployed"), ("retired", "Retired"),
      ("unable", "Unable to work")]),
]
check("four steps, their questions and answers, in order",
      [(s["id"], s["question"], [(o["id"], o["label"]) for o in s["options"]])
       for s in STEPS] == WANT)
check("  every step is tiles, with its own 'Step N of 4' eyebrow",
      all(s["type"] == "tiles" and s["eyebrow"] == "Step %d of 4" % (i + 1)
          for i, s in enumerate(STEPS)))
check("  the income helper",
      STEPS[2]["helper"] == "A range is enough. We never ask for exact "
      "figures.")
ICON_RE = r"[MmLlHhVvCcSsQqTtAaZz0-9 .,\-]{1,1200}"
check("  every need and household answer has an icon or a badge text",
      all(("icon" in o) != ("badge_text" in o)
          for s in STEPS[:2] for o in s["options"])
      and all(re.fullmatch(ICON_RE, o["icon"])
              for s in STEPS[:2] for o in s["options"] if "icon" in o)
      and not any("icon" in o or "badge_text" in o
                  for s in STEPS[2:] for o in s["options"]))
check("  the icons are single paths, each sub-path starting absolute",
      all(o["icon"].startswith("M") and not re.search(r"(?<![\d.])m", o["icon"])
          for s in STEPS[:2] for o in s["options"] if "icon" in o))
check("  60+ is the one badge text, on the senior answer",
      [(o["id"], o["badge_text"]) for s in STEPS[:2] for o in s["options"]
       if "badge_text" in o] == [("senior", "60+")])
check("  the script draws either, under a length limit that fits them",
      "var ICON_RE = /^[MmLlHhVvCcSsQqTtAaZz0-9 .,\\-]{1,1200}$/;" in JS
      and '"ico-wrap ico-text", o.badge_text' in JS)
SS = CFG["state_select"]
check("the state select: on step 4, 50 states and DC, two letters each",
      SS["step"] == "situation" and SS["label"] == "State"
      and SS["placeholder"] == "Select your state"
      and SS["button"] == "Show my programs"
      and len(SS["options"]) == 51
      and len({c for c, _ in SS["options"]}) == 51
      and all(re.fullmatch(r"[A-Z]{2}", c) for c, _ in SS["options"])
      and ["DC", "District of Columbia"] in SS["options"])
check("  and the consent line links Terms and Privacy",
      [p if isinstance(p, str) else p["href"] for p in SS["consent"]]
      == ["By continuing you agree to the ", "/terms", " and ", "/privacy",
          "."])
ART = CFG["articles"]
check("eight article keys, each labelled",
      list(ART) == ["snap", "liheap", "medicaid", "debt_relief", "wic_chip",
                    "medicare", "ssdi", "car_insurance"]
      and all(a["label"] for a in ART.values()))
check("  and every link is empty in this phase",
      all(a["link"] == "" for a in ART.values()))
R = CFG["result"]
check("the result copy",
      R["eyebrow"] == "Your results"
      and R["headline"] == "Programs worth checking for your household"
      and R["line"] == "Based on your answers. Availability and rules vary "
      "by state." and R["pill"] == "Sponsored"
      and R["prefeed_line"] == "Offers are not available yet."
      and R["no_id_line"] == "Offers are not available for this visit."
      and R["chips"] == ["need", "household", "income", "state"]
      and R["disclaimer"].startswith(
          "Mazzin is not a government agency and does not provide "
          "benefits. We show links to third-party content and may earn "
          "money when you click them. Program rules change"))
check("the footer: Privacy and Terms",
      CFG["footer"] == [{"label": "Privacy", "href": "/privacy"},
                        {"label": "Terms", "href": "/terms"}])
check("the banned list",
      CFG["banned"] == ["guarantee", "guaranteed", "you qualify",
                        "free money", "official", "approved by",
                        "government-approved", "$"])
PE = CFG["pixel_events"]
check("the two pixel events are custom, as /loans sends them",
      PE == {"result": {"name": "QuizComplete", "custom": True},
             "tap": {"name": "ArticleTap", "custom": True}})

print("\n--- the rules: every combination of answers ---")
answers = [dict(zip(("need", "household", "income", "situation"), combo))
           for combo in itertools.product(
               *[[o["id"] for o in s["options"]] for s in STEPS])]
run = subprocess.run(
    ["node", "-e",
     "const q = require(process.argv[1]); const cfg = require(process.argv[2]);"
     "const all = JSON.parse(require('fs').readFileSync(0, 'utf8'));"
     "process.stdout.write(JSON.stringify(all.map(a => q.resolveRows(cfg, a))));",
     os.path.join(REPO, "static/js/rsoc_quiz.js"),
     os.path.join(REPO, "funnels/rsoc/benefits.json")],
    input=json.dumps(answers), capture_output=True, text=True, timeout=60)
rows = json.loads(run.stdout) if run.returncode == 0 else []
check("the resolver in rsoc_quiz.js ran for all 4x4x4x5 answers",
      len(answers) == 320 and len(rows) == 320, run.stderr[:300])
check("  three rows every time, no duplicate, every key an article",
      all(len(r) == 3 and len(set(r)) == 3 and all(k in ART for k in r)
          for r in rows), [r for r in rows if len(set(r)) != 3][:3])


def expect(a):
    first = {"food": "snap", "utilities": "liheap", "medical": "medicaid",
             "debt": "debt_relief"}[a["need"]]
    second = {"kids": "wic_chip", "senior": "medicare",
              "disability": "ssdi"}.get(a["household"])
    if second is None:
        second = {"retired": "medicare", "unable": "ssdi"}.get(
            a["situation"], "medicaid")
        if second == first:
            second = [k for k in ("medicaid", "debt_relief", "liheap")
                      if k != first][0]
    return [first, second, "car_insurance"]


wrong = [(a, r) for a, r in zip(answers, rows) if r != expect(a)]
check("  each row is the one the brief names, in order", rows and not wrong,
      wrong[:2])
check("  income never changes the rows",
      all(rows[i] == rows[i - (i % 20) + (i % 5)] for i in range(len(rows))
          if answers[i]["income"] != "i1") if rows else False)
check("the rules are data: no article key and no answer id in the script",
      not [k for k in ART if '"%s"' % k in JS]
      and not [o["id"] for s in STEPS for o in s["options"]
               if '"%s"' % o["id"] in JS])
check("  and no word of the page's copy either",
      not [t for t in (CFG["headline"], R["headline"], R["line"],
                       R["disclaimer"], R["no_id_line"], R["prefeed_line"],
                       SS["button"], "Edit answers", "Sponsored",
                       "Show my programs", "Your answers", "Select your state")
           if t in JS])

print("\n--- the copy, as written ---")
INCOME = [o["label"] for o in STEPS[2]["options"]]


def scan(text):
    """Banned terms in `text`, the income tiles' dollar signs excepted."""
    for label in INCOME:
        text = text.replace(label, "")
    low = text.lower()
    hits = [b for b in CFG["banned"] if b.lower() in low]
    hits += [w for w in ("qualify", "qualifies", "eligible", "eligibility",
                         "approved", "free money")
             if re.search(r"\b%s\b" % w, low)]
    if re.search(r"\$\s?\d", text):
        hits.append("a dollar amount")
    return sorted(set(hits))


strings = []


def walk(node):
    if isinstance(node, dict):
        for k, v in node.items():
            if k not in ("banned", "icon", "link", "pixel_id"):
                walk(v)
    elif isinstance(node, list):
        for v in node:
            walk(v)
    elif isinstance(node, str):
        strings.append(node)


walk(CFG)
check("nothing banned in the config's copy", not scan("\n".join(strings)),
      scan("\n".join(strings)))
check("  the scan would catch each banned term, and a dollar amount",
      all(scan("x %s y" % b) for b in CFG["banned"])
      and scan("up to $500 a month") and scan("You are eligible")
      and not scan(" ".join(INCOME)))
check("  the page shell says nothing banned either", not scan(
    re.sub(r"<[^>]+>", " ", PAGE)))

print("\n--- the files ---")
for rel, name in (("css/rsoc.css", "rsoc.css"), ("js/rsoc_quiz.js",
                                                 "rsoc_quiz.js")):
    want = hashlib.sha256(read("static/" + rel).encode("utf-8")).hexdigest()[:10]
    got = re.findall(r"/static/%s\?v=([0-9a-f]+)" % re.escape(rel), PAGE)
    check("rsoc.html loads %s once, as ?v=%s" % (name, want), got == [want],
          "static/rsoc.html has %s — set it to ?v=%s" % (got, want))
for word in ("ViewContent", "Purchase"):
    check("%r is in neither rsoc.html nor rsoc_quiz.js" % word,
          word not in PAGE and word not in JS)
check("the shell carries the slug mark once, on the body",
      PAGE.count(rsoc.SLUG_MARK) == 1
      and '<body data-rsoc="%s">' % rsoc.SLUG_MARK in PAGE)
check("nothing loaded from off the site but Meta's script, added by the JS",
      not re.search(r"<(script|link|img|iframe)\b[^>]*https?:", PAGE)
      and sorted(set(re.findall(r"https?://[\w.-]+", JS)))
      == ["http://www.w3.org", "https://connect.facebook.net"]
      and "XMLHttpRequest" not in JS and "innerHTML" not in JS)
check("the identifiers' rules are /loans's, read for read",
      'fbclid: /^[A-Za-z0-9_-]{1,512}$/' in JS
      and 'ad_id: /^[0-9]{1,32}$/' in JS and 'asid: /^[0-9]{1,32}$/' in JS
      and 'var PASS_ORDER = ["fbclid", "ad_id", "asid"];' in JS
      and 'var PASS_KEY = "mazzin_pass_" + slug;' in JS)
check("  and the only reader of them is the link builder",
      # Its definition, the merge on load, hasClick() and the row's href.
      JS.count("heldPass()") == 4 and "passMemory" not in JS.split(
          "function track(", 1)[1].split("\n  }\n", 1)[0])
check("the stylesheet is /loans's: the same tokens, fonts and rows",
      LOANS_CSS[LOANS_CSS.index(":root {"):LOANS_CSS.index("*, *::before")]
      in CSS
      and LOANS_CSS[LOANS_CSS.index(".guides {"):LOANS_CSS.index(
          "/* --- footer")] in CSS
      and ".guide.is-off" in CSS and "@import" not in CSS)
check("no loans file is imported or edited: no shared name in the script",
      "loans" not in JS.lower().replace("/loans does", "").replace(
          "loans.js", "").replace("/loans", ""))

print("\n--- the routes ---")
client = app.test_client()
page = client.get("/benefits")
check("/benefits is 200, the shell with the slug written in",
      page.status_code == 200
      and b'<body data-rsoc="benefits">' in page.data
      and rsoc.SLUG_MARK.encode() not in page.data
      and page.headers.get("Cache-Control")
      == "public, max-age=%d" % config.FUNNEL_HTML_MAX_AGE)
check("/nope is 404", client.get("/nope").status_code == 404)
rules = {r.rule: r.endpoint for r in app.url_map.iter_rules()}
check("/loans and /kitchen still go to their own handlers",
      app.url_map.bind("localhost").match("/loans")[0] == "loans_page"
      and app.url_map.bind("localhost").match("/kitchen")
      == ("funnel_page", {"slug": "kitchen"})
      and app.url_map.bind("localhost").match("/benefits")[0]
      == "rsoc.page_benefits", rules.get("/benefits"))
loans_page = client.get("/loans")
kitchen = client.get("/kitchen")
check("  and answer what they always did",
      loans_page.status_code == 200 and b"Loan options" in loans_page.data
      and kitchen.status_code == 200 and b"engine.js" in kitchen.data
      and b"data-rsoc" not in loans_page.data + kitchen.data)
check("/ai-navigator, /go and the API are untouched",
      app.url_map.bind("localhost").match("/ai-navigator")[0] == "funnel_page"
      and app.url_map.bind("localhost").match("/go")[0] == "router.go"
      and app.url_map.bind("localhost", default_method="POST").match(
          "/api/track")[0] == "tracking.track")
saved = rsoc.RSOC_DIR
try:
    import tempfile
    with tempfile.TemporaryDirectory() as tmp:
        for name in ("kitchen", "loans", "terms", "fresh"):
            with open(os.path.join(tmp, name + ".json"), "w") as fh:
                json.dump({"slug": name}, fh)
        rsoc.RSOC_DIR = tmp
        check("a config named after a funnel, /loans or a page is not routed",
              rsoc.configured_slugs() == ["fresh"], rsoc.configured_slugs())
finally:
    rsoc.RSOC_DIR = saved

print("\n--- the event endpoint ---")
SID = "0f8fad5b-d9cb-469f-a165-70867728950e"


def post(slug, body, raw=None):
    del writes[:]
    data = raw if raw is not None else json.dumps(body)
    r = client.post("/api/rsoc/%s/event" % slug, data=data,
                    content_type="application/json")
    return r.status_code, list(writes)


ok = [
    ({"event": "quiz_start"}, None, None),
    ({"event": "step", "step": 1, "extra": {"step": "need"}}, 1,
     '{"step":"need"}'),
    ({"event": "step", "step": 4, "extra": {"step": "situation"}}, 4,
     '{"step":"situation"}'),
    ({"event": "result_view"}, None, None),
    ({"event": "offer_tap", "extra": {"slot": "snap"}}, None,
     '{"slot":"snap"}'),
]
for body, step, extra in ok:
    body = dict(body, session_id=SID, subid="sub-9", utm_source="fb")
    status, got = post("benefits", body)
    check("%s is one events row, funnel benefits" % (
        body["event"] + ("" if step is None else " %d" % step)),
          status == 204 and len(got) == 1 and got[0][0] == tracking.INSERT_SQL
          and got[0][1] == ("benefits", SID, body["event"], step, "sub-9",
                            "fb", None, None, None, extra), got)
bad = [
    ("an unknown slug", "nope", {"event": "quiz_start"}),
    ("an unknown event", "benefits", {"event": "purchase"}),
    ("an event loans uses but this does not", "benefits",
     {"event": "swipe", "step": 1}),
    ("a step with the wrong id", "benefits",
     {"event": "step", "step": 2, "extra": {"step": "need"}}),
    ("a step past the last", "benefits",
     {"event": "step", "step": 5, "extra": {"step": "result"}}),
    ("a step with an answer in it", "benefits",
     {"event": "step", "step": 1, "extra": {"step": "need",
                                            "answer": "food"}}),
    ("a tap on a key that is no article", "benefits",
     {"event": "offer_tap", "extra": {"slot": "lottery"}}),
    ("extra on result_view", "benefits",
     {"event": "result_view", "extra": {"slot": "snap"}}),
    ("fbclid in the body", "benefits", {"event": "quiz_start",
                                        "fbclid": "AbC"}),
    ("ad_id in the body", "benefits", {"event": "quiz_start", "ad_id": "1"}),
    ("asid in the body", "benefits", {"event": "quiz_start", "asid": "2"}),
    ("an answer in the body", "benefits", {"event": "quiz_start",
                                           "need": "food"}),
    ("a bad session id", "benefits", {"event": "quiz_start",
                                      "session_id": "x"}),
]
for label, slug, body in bad:
    body = dict({"session_id": SID}, **body)
    status, got = post(slug, body)
    check("refused, nothing written: %s" % label,
          status == 400 and got == [], [status, got])
status, got = post("benefits", None, raw=json.dumps(
    {"session_id": SID, "event": "quiz_start", "subid": "x" * 5000}))
check("refused, nothing written: a body over 4 KB",
      status == 400 and got == [], status)
status, got = post("benefits", None, raw="not json")
check("refused, nothing written: not JSON", status == 400 and got == [])
check("the route reads nothing and logs no body",
      "query_one" not in read("rsoc.py") and "query_all" not in read("rsoc.py")
      and not re.search(r"log\.\w+\([^)]*body", read("rsoc.py")))

print("\n--- the copy, as the browser draws it ---")
from playwright.sync_api import sync_playwright            # noqa: E402

PORT = 8889
BASE = "http://127.0.0.1:%d" % PORT


class Handler(http.server.SimpleHTTPRequestHandler):
    def __init__(self, *a, **kw):
        super().__init__(*a, directory=REPO, **kw)

    def log_message(self, *a):
        pass

    def do_GET(self):
        if self.path.split("?")[0] == "/benefits":
            body = PAGE.replace(rsoc.SLUG_MARK, "benefits").encode()
            self.send_response(200)
            self.send_header("Content-Type", "text/html")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)
            return
        return super().do_GET()

    def do_POST(self):
        self.rfile.read(int(self.headers.get("content-length") or 0))
        self.send_response(204)
        self.end_headers()


class Server(socketserver.ThreadingMixIn, http.server.HTTPServer):
    allow_reuse_address = True
    daemon_threads = True


server = Server(("127.0.0.1", PORT), Handler)
threading.Thread(target=server.serve_forever, daemon=True).start()
with sync_playwright() as pw:
    browser = pw.chromium.launch(
        executable_path="/opt/pw-browsers/chromium-1194/chrome-linux/chrome")
    ctx = browser.new_context(viewport={"width": 390, "height": 844},
                              is_mobile=True, has_touch=True)
    ctx.route(lambda url: not url.startswith(BASE), lambda r: r.abort())
    page = ctx.new_page()
    page.goto(BASE + "/benefits?fbclid=AbC")
    page.wait_for_selector("#choices-need .tile")
    texts = []
    for step in STEPS[:3]:
        texts.append(page.evaluate("() => document.body.innerText"))
        page.locator("#choices-%s button" % step["id"]).first.click()
        page.wait_for_timeout(200)
    page.locator("#choices-situation button").first.click()
    page.select_option("#state", "TX")
    texts.append(page.evaluate("() => document.body.innerText"))
    page.locator("#go-result").click()
    page.wait_for_timeout(300)
    texts.append(page.evaluate("() => document.body.innerText"))
    whole = page.evaluate("() => document.body.textContent")
    browser.close()
server.shutdown()
shown = "\n".join(texts)
check("every view was drawn: four questions and the result",
      all(s["question"] in whole for s in STEPS)
      and R["headline"] in shown and "Offers are not available yet." in shown)
check("nothing banned in the drawn page, every view and every option",
      not scan(shown) and not scan(whole), [scan(shown), scan(whole)])

print("\n%d checks, %d failed" % (checks[0], len(fails)))
for line in fails:
    print("  FAIL " + line[:420])
sys.exit(1 if fails else 0)
