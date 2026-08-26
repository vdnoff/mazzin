#!/usr/bin/env python3
"""The section cache a `-test` twin reads from.

A twin is a live funnel with its slug, its funnel_id and its Stripe mode
changed — the same steps, the same archetypes, the same report profile. The
cached trio (palette, mistakes, splurge) is one answer per archetype rather
than one per buyer, so the source funnel's rows ARE the twin's answers.

Until this they were not reachable. The cache is keyed (funnel, style), the
twin has never been warmed, and three sections do not generate inside the
webhook's budget — so a sandbox purchase on /zodiac-ro-test delivered the
stubs, which is how a Romanian report came back with three English blocks in
the middle of it.

What is asserted here is the loan and its edges: a twin with nothing of its
own reads its source's rows, a live slug never reads anybody's, and the write
side is untouched — nothing a sandbox generates can land on a row a paying
reader will be served.

No database, no network, no key. `database.query_all` is replaced with a dict
lookup and every row is built here.
"""
import json
import os
import sys

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

sys.path.insert(0, REPO)

import config                                    # noqa: E402
import reports                                   # noqa: E402

SOURCE = "zodiac-ro"
TWIN = SOURCE + config.TEST_SUFFIX
STYLE = "celestial_air"
TRIO = ("palette", "mistakes", "splurge")

fails = []
checks = [0]


def check(label, ok, detail=""):
    checks[0] += 1
    if not ok:
        fails.append("%s %s" % (label, detail))
    print("  %-62s %s%s" % (label, "ok" if ok else "FAIL",
                            ("  " + str(detail)) if detail and not ok else ""))


# --- the rows ---------------------------------------------------------------
# Real section data, not a hand-written blob: the stubs are the one thing in
# the module already shaped to pass the validators a cached row is read
# through, so a row built from them proves the read rather than the fixture.
cfg = config.load_funnel(SOURCE)
style = reports._style(cfg, STYLE)
name = reports._style_name(cfg, STYLE)
profile = reports._profile(SOURCE)

DATA = dict((section_id, reports._stub_for(section_id, name, style,
                                           profile["stubs"], None,
                                           profile.get("stub_colors")))
            for section_id in TRIO)


def rows_for(slug, tag=None):
    """The three cached rows one funnel would have, as the driver returns."""
    return [{"section_id": section_id,
             "content": json.dumps(
                 {"v": tag or reports._cache_tag(slug, section_id),
                  "data": DATA[section_id]})}
            for section_id in TRIO]


asked = []


def fake_query_all(sql, params):
    """Every read this suite serves, and a record of who asked for what."""
    slug, style_id = params
    asked.append((slug, style_id))
    if isinstance(TABLE, Exception):
        raise TABLE
    return TABLE.get((slug, style_id), [])


TABLE = {}
reports.database.query_all = fake_query_all


def state(slug, table, style_id=STYLE):
    """(_cache_state, the slugs it queried) for one arrangement of the table."""
    global TABLE
    TABLE = table
    del asked[:]
    got = reports._cache_state(slug, style_id)
    return got, [s for s, _ in asked]


print("\n--- what a twin is, spelled once ---")
check("the twin's source is the slug with the suffix taken off",
      reports._cache_source(TWIN) == SOURCE, reports._cache_source(TWIN))
check("  it is the same suffix config and _profile use",
      TWIN == SOURCE + config.TEST_SUFFIX
      and config.is_test_slug(TWIN) and not config.is_test_slug(SOURCE))
check("a live slug borrows from nobody",
      reports._cache_source(SOURCE) is None
      and reports._cache_source("zodiac30") is None
      and reports._cache_source("kitchen") is None)
check("  nor does an empty or missing slug",
      reports._cache_source("") is None and reports._cache_source(None) is None)
check("  and neither does the bare suffix on its own",
      reports._cache_source(config.TEST_SUFFIX) is None)
check("the twin reads the same profile, so the same cache tag",
      all(reports._cache_tag(TWIN, s) == reports._cache_tag(SOURCE, s)
          for s in TRIO))

print("\n--- the twin with nothing of its own ---")
(got, stale), queried = state(TWIN, {(SOURCE, STYLE): rows_for(SOURCE)})
check("reads its source's rows", sorted(got or {}) == sorted(TRIO),
      str(sorted(got or {})))
check("  no stale rows came with them", stale == 0, stale)
check("  it asked itself first, and the source second",
      queried == [TWIN, SOURCE], str(queried))
check("  and the sections are the source's own content",
      all((got or {}).get(s) == reports.VALIDATORS[s](DATA[s]) for s in TRIO))

TABLE = {(SOURCE, STYLE): rows_for(SOURCE)}
check("so _read_cache hands the purchase path a full set",
      sorted(reports._read_cache(TWIN, STYLE) or {}) == sorted(TRIO),
      str(sorted(reports._read_cache(TWIN, STYLE) or {})))
check("  which is what stops the purchase falling to stubs",
      reports._read_cache(TWIN, STYLE) is not None)

print("\n--- and never at the expense of its own ---")
(got, stale), queried = state(
    TWIN, {(TWIN, STYLE): rows_for(TWIN), (SOURCE, STYLE): []})
check("a twin with rows of its own reads only those",
      sorted(got or {}) == sorted(TRIO) and queried == [TWIN], str(queried))
(got, stale), queried = state(
    TWIN, {(TWIN, STYLE): rows_for(TWIN, tag="stale-schema"),
           (SOURCE, STYLE): rows_for(SOURCE)})
check("a twin whose own rows went stale regenerates rather than borrows",
      got == {} and stale == len(TRIO) and queried == [TWIN],
      "%s stale=%s queried=%s" % (sorted(got or {}), stale, queried))
TABLE = {(TWIN, STYLE): rows_for(TWIN, tag="stale-schema"),
         (SOURCE, STYLE): rows_for(SOURCE)}
check("  and _read_cache says miss, so the purchase writes them fresh",
      reports._read_cache(TWIN, STYLE) is None)

print("\n--- a read that failed is not an empty cache ---")
(got, stale), queried = state(TWIN, OSError("no database"))
check("a failed read is None, not a loan",
      got is None and stale == 0, "%s %s" % (got, stale))
check("  and it never went looking for the source",
      queried == [TWIN], str(queried))

print("\n--- a live funnel reads nobody's rows ---")
for slug in (SOURCE, "zodiac", "zodiac30", "kitchen"):
    (got, stale), queried = state(
        slug, {(SOURCE, STYLE): rows_for(SOURCE),
               ("zodiac", STYLE): rows_for("zodiac"),
               ("zodiac30", STYLE): rows_for("zodiac30")})
    check("  %-10s asks for its own rows and stops" % slug,
          queried == [slug], str(queried))
(got, stale), queried = state("nothing-at-all", {(SOURCE, STYLE):
                                                 rows_for(SOURCE)})
check("an unknown live slug gets an empty cache, not the twin's",
      got == {} and queried == ["nothing-at-all"], str(queried))
(got, stale), queried = state("nonsense-test", {(SOURCE, STYLE):
                                                rows_for(SOURCE)})
check("  and an unregistered twin asks for its own source, which has nothing",
      got == {} and queried == ["nonsense-test", "nonsense"], str(queried))

print("\n--- the write side did not move ---")
wrote = []
reports.database.execute = lambda sql, params: wrote.append(params)
reports._write_cache(TWIN, STYLE, {"palette": DATA["palette"]})
check("warming a twin writes on the twin, never on its source",
      [p[0] for p in wrote] == [TWIN], str([p[0] for p in wrote]))
check("  and the row it writes is stamped with the shared tag",
      json.loads(wrote[0][3])["v"] == reports._cache_tag(SOURCE, "palette"))
check("  so nothing a sandbox generates can reach a paying reader's row",
      reports.UPSERT_SECTION_SQL.count("%s") == 4
      and "(funnel, style_id, section_id, content)"
      in reports.UPSERT_SECTION_SQL)

print("\n--- the warmer sees the same thing the purchase does ---")
TABLE = {(SOURCE, STYLE): rows_for(SOURCE)}
have, _stale = reports._cache_state(TWIN, STYLE)
check("a twin whose source is warm has nothing left to warm",
      [s for s in reports.cached_sections(TWIN) if s not in have] == [],
      str([s for s in reports.cached_sections(TWIN) if s not in have]))
check("  which is the point: a twin never pays to regenerate its source's work",
      reports.cached_sections(TWIN) == reports.cached_sections(SOURCE)
      == ("palette", "mistakes", "splurge"))

print("\n%d checks, %d failed" % (checks[0], len(fails)))
for f in fails:
    print("  FAIL " + f)
sys.exit(1 if fails else 0)
