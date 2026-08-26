#!/usr/bin/env python3
"""The sandbox twin, and the switch that decides whether it exists.

Two things are asserted here and they fail for different reasons.

The first is drift. funnels/zodiac-ro-test.json is generated from
funnels/zodiac-ro.json by scripts/make_test_twin.py and is committed rather
than built at deploy time, so the moment somebody edits a line of Romanian
copy and does not rerun the script, the twin is testing last week's funnel.
Nothing about that is visible on the page — the twin still loads, still
walks, still takes a test card — so it is asserted here instead: everything
but the three fields the script changes must be equal, and equal is checked
over the whole config rather than a sampled list of keys.

The second is the gate. A `-test` slug is a public URL one guessable suffix
away from a live one, and what keeps it closed is an environment variable
read per request. So: off means the same empty 404 an unknown slug gets, on
means a page nobody caches and no crawler indexes, and neither state may
change anything about the live funnel, the legal pages or /health.

No database, no network, no key. Everything is read off disk or through the
Flask test client.
"""
import json
import os
import sys

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

sys.path.insert(0, REPO)
ROOT = REPO

import config                                   # noqa: E402
import database                                 # noqa: E402
from app import app                             # noqa: E402

SOURCE = "zodiac-ro"
TWIN = SOURCE + "-test"

fails = []
checks = [0]


def check(label, ok, detail=""):
    checks[0] += 1
    if not ok:
        fails.append("%s %s" % (label, detail))
    print("  %-62s %s%s" % (label, "ok" if ok else "FAIL",
                            ("  " + str(detail)) if detail and not ok else ""))


def read(directory, slug):
    with open(os.path.join(ROOT, directory, slug + ".json"),
              encoding="utf-8") as fh:
        return fh.read()


src_raw = read("funnels", SOURCE)
twin_raw = read("funnels", TWIN)
src = json.loads(src_raw)
twin = json.loads(twin_raw)

print("\n--- the twin is on disk, in both places ---")
for directory in ("funnels", os.path.join("static", "funnels")):
    path = os.path.join(ROOT, directory, TWIN + ".json")
    check("  %s exists" % os.path.join(directory, TWIN + ".json"),
          os.path.isfile(path))
check("the static copy is byte-identical to funnels/",
      read(os.path.join("static", "funnels"), TWIN) == twin_raw)
check("  and the source's two copies still are too",
      read(os.path.join("static", "funnels"), SOURCE) == src_raw)
check("the config loader can reach the twin",
      config.funnel_exists(TWIN) and config.load_funnel(TWIN) == twin)

print("\n--- it differs from its source in exactly three fields ---")
# The alarm. Not a list of keys somebody has to remember to extend when the
# funnel grows one: everything is compared, and the three the generator
# changes are the only permitted difference.
TWINNED = ("slug", "funnel_id", "stripe_mode")
differ = sorted(k for k in set(src) | set(twin) if src.get(k) != twin.get(k))
check("only slug, funnel_id and stripe_mode differ",
      differ == sorted(TWINNED), str(differ))
check("  every other key is the source's, value for value",
      all(twin[k] == src[k] for k in src if k not in TWINNED),
      str([k for k in src if k not in TWINNED and twin.get(k) != src[k]]))
check("  no key was added or dropped",
      set(src) == set(twin), str(sorted(set(src) ^ set(twin))))
check("  and the key order is the source's, so the two files diff cleanly",
      list(src) == list(twin))
# Belt and braces on the same claim, at the byte level: three lines of a
# 3000-line file, and they are the three above.
src_lines = src_raw.splitlines()
twin_lines = twin_raw.splitlines()
moved = [n for n, (a, b) in enumerate(zip(src_lines, twin_lines), 1) if a != b]
check("three lines of the file differ and no more",
      len(src_lines) == len(twin_lines) and len(moved) == 3,
      "%d lines vs %d, %d differ" % (len(src_lines), len(twin_lines),
                                     len(moved)))

print("\n--- the three fields say what they should ---")
check("twin slug is %s" % TWIN, twin["slug"] == TWIN, twin["slug"])
check("  and the source still calls itself %s" % SOURCE,
      src["slug"] == SOURCE, src["slug"])
check("twin funnel_id is the source's plus _test",
      twin["funnel_id"] == src["funnel_id"] + "_test", twin["funnel_id"])
check("  so a tracked event can never be counted as the live funnel's",
      twin["funnel_id"] != src["funnel_id"])
check("the twin transacts on test keys",
      twin["stripe_mode"] == "test", twin["stripe_mode"])
check("  and the source is still live",
      src["stripe_mode"] == "live", src["stripe_mode"])
check("  which is the field payments.py reads",
      __import__("payments")._stripe_mode(twin) == "test"
      and __import__("payments")._stripe_mode(src) == "live")
check("the price is untouched — a sandbox that charges differently "
      "tests nothing",
      twin["pricing"] == src["pricing"], str(twin["pricing"]))

print("\n--- the generator is idempotent ---")
import importlib.util                            # noqa: E402

spec = importlib.util.spec_from_file_location(
    "make_test_twin", os.path.join(ROOT, "scripts", "make_test_twin.py"))
maker = importlib.util.module_from_spec(spec)
spec.loader.exec_module(maker)
rebuilt = maker.twin_of(src, SOURCE)
check("regenerating from the current source reproduces the committed twin",
      rebuilt == twin,
      str(sorted(k for k in set(rebuilt) | set(twin)
                 if rebuilt.get(k) != twin.get(k))))
check("  byte for byte, not just field for field",
      json.dumps(rebuilt, indent=2, ensure_ascii=False) + "\n" == twin_raw)


def _twin_error(cfg, slug):
    try:
        maker.twin_of(cfg, slug)
    except ValueError as exc:
        return str(exc)
    return None


check("  it refuses to twin a twin", _twin_error(twin, TWIN) is not None,
      _twin_error(twin, TWIN))
check("  and refuses a config with no funnel_id to twin",
      _twin_error({k: v for k, v in src.items() if k != "funnel_id"},
                  SOURCE) is not None)

print("\n--- the report the twin delivers is the one it is a twin of ---")
# Not cosmetic. `_profile` falls back to kitchen for an unregistered slug, so
# without the twin resolving to its source a sandbox purchase would succeed,
# take the test card, and return an English kitchen PDF — a failure a test
# card does not show you.
import reports                                   # noqa: E402

check("the twin reads its source's report profile",
      reports._profile(TWIN) is reports._profile(SOURCE)
      is reports.ZODIAC_RO_PROFILE)
check("  so its PDF and mail are the Romanian ones",
      reports._profile(TWIN)["pdf_lead"] != reports.KITCHEN_PROFILE["pdf_lead"]
      and reports._email_copy({"funnel": TWIN}) is reports.COPY_ZODIAC_RO)
check("  and it is still a zodiac profile everywhere that branches on one",
      reports._is_zodiac(reports._profile(TWIN)))
check("kitchen and its clone are unmoved",
      reports._profile("kitchen") is reports._profile("kitchen-visualizer")
      is reports.KITCHEN_PROFILE)
check("  and a -test slug with no source still falls through to kitchen",
      reports._profile("nonsense-test") is reports.KITCHEN_PROFILE)
check("the twin's section cache is its own, not the source's",
      TWIN != SOURCE and "funnel = %s" in reports.SELECT_SECTIONS_SQL)

print("\n--- the gate, off ---")
# The switch is read through the module on every request, which is what makes
# flipping it in .env and restarting the whole of turning the twin off. That
# is also what lets this suite flip it without a second app.
LIVE_CACHE = "public, max-age=%d" % config.FUNNEL_HTML_MAX_AGE
NOSTORE = "no-store"
ROBOTS = "noindex, nofollow"

# /health talks to the database. Stubbed, because this suite has none and the
# point of asking is the status code and the headers, not the query.
database.query_one = lambda *a, **kw: {"ok": 1}

client = app.test_client()


def get(path):
    resp = client.get(path)
    return (resp.status_code,
            resp.headers.get("Cache-Control"),
            resp.headers.get("X-Robots-Tag"),
            resp.get_data())


def brief(got):
    """One response, short enough to read when it is the reason for a fail.

    The body of a served funnel is the whole HTML shell, and a check that
    prints it has told you nothing you can see.
    """
    status, cache, robots, body = got
    return "%s cache=%r robots=%r body=%dB" % (status, cache, robots,
                                               len(body))


def with_flag(value, fn):
    was = config.TEST_FUNNELS
    config.TEST_FUNNELS = value
    try:
        return fn()
    finally:
        config.TEST_FUNNELS = was


check("the flag defaults to off",
      config.TEST_FUNNELS is False, config.TEST_FUNNELS)

off = with_flag(False, lambda: get("/" + TWIN))
check("/%s is 404 with the flag off" % TWIN, off[0] == 404, off[0])
unknown = with_flag(False, lambda: get("/no-such-funnel"))
check("  the same 404 an unknown slug gets — status, body and headers",
      off[0] == unknown[0] and off[3] == unknown[3]
      and off[1] == unknown[1] and off[2] == unknown[2],
      "%s vs %s" % (brief(off), brief(unknown)))
check("  so the refusal never admits the twin exists",
      off[3] == b"" and off[2] is None, brief(off))
check("  and it is not a 403, which would be an answer",
      off[0] != 403)

print("\n--- the gate, on ---")
on = with_flag(True, lambda: get("/" + TWIN))
check("/%s is 200 with the flag on" % TWIN, on[0] == 200, on[0])
check("  Cache-Control is no-store", on[1] == NOSTORE, on[1])
check("    so turning the flag off takes effect without a CDN purge",
      "no-store" in (on[1] or ""))
check("  X-Robots-Tag is noindex, nofollow", on[2] == ROBOTS, on[2])
check("  and it serves the same shell every funnel does",
      b"<html" in on[3].lower() or b"<!doctype" in on[3].lower(),
      brief(on))
check("an unknown -test slug is still 404 with the flag on",
      with_flag(True, lambda: get("/nothing-test"))[0] == 404)

print("\n--- the live funnel is the same page in both states ---")
for state, flag in (("off", False), ("on", True)):
    live = with_flag(flag, lambda: get("/" + SOURCE))
    check("  /%s is 200 with the flag %s" % (SOURCE, state),
          live[0] == 200, live[0])
    check("    keeps its public Cache-Control", live[1] == LIVE_CACHE, live[1])
    check("    and grows no X-Robots-Tag", live[2] is None, live[2])
both = [with_flag(f, lambda: get("/" + SOURCE)) for f in (False, True)]
check("the flag changes nothing at all about it", both[0] == both[1])

print("\n--- and no other route moved ---")
OTHERS = ["/health", "/kitchen", "/zodiac30", "/terms", "/privacy", "/",
          "/no-such-funnel"]
for path in OTHERS:
    a = with_flag(False, lambda p=path: get(p))
    b = with_flag(True, lambda p=path: get(p))
    check("  %-16s identical with the flag on and off" % path,
          a == b, "%s vs %s" % (brief(a), brief(b)))
check("/health still answers ok",
      with_flag(True, lambda: client.get("/health").get_json())
      == {"status": "ok"})
check("the legal pages still cache for an hour",
      with_flag(True, lambda: get("/terms"))[1]
      == "public, max-age=%d" % config.PAGE_HTML_MAX_AGE)
check("no route was added for the twin",
      not [r for r in app.url_map.iter_rules() if "test" in str(r.rule)],
      str([str(r.rule) for r in app.url_map.iter_rules()
           if "test" in str(r.rule)]))
check("  it is served by the one funnel route",
      len([r for r in app.url_map.iter_rules()
           if str(r.rule) == "/<slug>"]) == 1)

print("\n--- the source funnel is untouched ---")
check("funnels/%s.json is still the live Romanian funnel" % SOURCE,
      src["locale"] == "ro" and src["stripe_mode"] == "live"
      and src["funnel_id"] == "zodiac_ro_v1")
check("  and the other four funnels still mirror cleanly",
      all(read("funnels", s) == read(os.path.join("static", "funnels"), s)
          for s in ("kitchen", "kitchen-visualizer", "zodiac", "zodiac30")))

print("\n%d checks, %d failed" % (checks[0], len(fails)))
for f in fails:
    print("  FAIL " + f)
sys.exit(1 if fails else 0)
