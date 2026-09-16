#!/usr/bin/env python3
"""Re-price a funnel that is already on disk: the price test's standing tool.

Console use only, run by hand on the server. No model call, no database, no
network — pure JSON: the funnel is read, its pricing block is set from the
locale row, every string that names the old price literally is rewritten to
name the new one, and both copies are written back byte-frozen otherwise.
A translation is not touched and the report cache does not move, which is
the whole point: a price test should cost a table edit, not a regeneration.

    cd ~/mazzin && python3 scripts/set_price.py blinds hu
    cd ~/mazzin && python3 scripts/set_price.py blinds en        # the master
    cd ~/mazzin && python3 scripts/set_price.py blinds de --dry-run

What it does, in order:

  1. loads funnels/<vertical>-<lang>.json (the master itself for `en`, or
     whatever language the master declares) and fails plainly when the
     funnel is not on disk — it patches, it does not generate;
  2. reads the language's row from scripts/locales.json and holds it to the
     same Stripe rules the generator does (minor-unit step, minimum charge);
  3. writes amount_cents, currency, price_format and decimal_mark to the
     pricing block, in place, key order kept;
  4. swaps the old written price ("790 Ft", "1,99 €", "$1.99") for the new
     one in every string of the funnel, so a line that named the price
     literally does not go on naming the old one — and refuses to write a
     funnel in which the old figure still survives anywhere;
  5. writes funnels/<slug>.json and the byte-identical static/funnels/
     copy, and does the same to the funnel's -test twin when it has one,
     so the twin stays the funnel it is named after.

Idempotent: rerun against an unchanged table and it rewrites the same bytes
and says the price already stood. Exit status 0 when the files are on disk
and correct, 1 otherwise.
"""
import argparse
import json
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(HERE))
sys.path.insert(0, HERE)

import reports                                  # noqa: E402
import make_funnel as mf                        # noqa: E402

ROOT = mf.ROOT


class PriceError(Exception):
    pass


def slug_for(vertical, lang, master_locale="en"):
    """Which file a language's price lives in: the master for its own
    language, <vertical>-<lang> for every other."""
    return vertical if lang == master_locale else "%s-%s" % (vertical, lang)


def _read(root, slug):
    path = os.path.join(root, "funnels", slug + ".json")
    if not os.path.isfile(path):
        return None
    with open(path, encoding="utf-8") as fh:
        return json.load(fh)


def written(cfg):
    """The price as this funnel writes it — the string a line would name."""
    return reports._written_price(cfg, (cfg.get("pricing") or {})
                                  .get("amount_cents")) or ""


def reprice(cfg, loc):
    """Set the price on `cfg` in place and swap the old written price for
    the new in every string. Returns (old written, new written, swapped)."""
    old = written(cfg)
    mf.apply_pricing(cfg, loc)
    new = written(cfg)
    swapped = 0
    if old and old != new:
        for path, text in mf._all_strings(cfg):
            if old in text:
                mf._set(cfg, path, text.replace(old, new))
                swapped += 1
    return old, new, swapped


def check_stale(cfg, old, new):
    """Refuse a funnel that still names the old price anywhere — the written
    form, or the bare amount with its decimal mark when it has one (a "1,99"
    that lost its sign is still the old price)."""
    if not old or old == new:
        return
    pricing = cfg.get("pricing") or {}
    bare = ""
    amount = old.replace(pricing.get("price_format", "{amount}")
                         .replace("{amount}", ""), "").strip()
    mark = pricing.get("decimal_mark") or "."
    if mark in amount:
        bare = amount
    hits = []
    for path, text in mf._all_strings(cfg):
        if old in text or (bare and bare in text):
            hits.append("%s: %r" % (path, text[:60]))
    if hits:
        raise PriceError("%d string(s) still name the old price %s — nothing "
                         "written:\n  %s" % (len(hits), old,
                                             "\n  ".join(hits[:12])))


def set_price(vertical, lang, root=ROOT, dry_run=False, locales=None):
    """The whole tool. Returns (config written, twin written or None)."""
    master = _read(root, vertical)
    if master is None:
        raise FileNotFoundError("no master funnel at funnels/%s.json"
                                % vertical)
    locales = locales or mf.load_locales()
    if lang not in locales:
        raise ValueError("no locale %r in scripts/locales.json (have: %s)"
                         % (lang, ", ".join(sorted(locales))))
    loc = locales[lang]
    mf.check_locale(lang, loc)
    slug = slug_for(vertical, lang, master.get("locale") or "en")
    cfg = _read(root, slug)
    if cfg is None:
        raise FileNotFoundError(
            "no funnel at funnels/%s.json — set_price patches a funnel that "
            "is on disk; generate it first with make_funnel.py" % slug)

    before = dict(cfg.get("pricing") or {})
    old, new, swapped = reprice(cfg, loc)
    check_stale(cfg, old, new)
    print("%s: %s %s -> %s %d  (%s -> %s)%s"
          % (slug, before.get("currency"), before.get("amount_cents"),
             loc["currency"], loc["amount_cents"], old or "?", new,
             "" if old != new else "  already there"))
    if swapped:
        print("  price swapped in %d string(s)" % swapped)

    twin_slug = slug + "-test"
    twin = _read(root, twin_slug)
    if twin is not None:
        t_old, t_new, t_swapped = reprice(twin, loc)
        check_stale(twin, t_old, t_new)
        print("%s: %s -> %s%s" % (twin_slug, t_old or "?", t_new,
                                  ("  (%d string(s))" % t_swapped)
                                  if t_swapped else ""))
    if dry_run:
        print("  dry run — nothing written")
        return None, None
    mf.write_both(root, slug, cfg)
    if twin is not None:
        mf.write_both(root, twin_slug, twin)
    return cfg, twin


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("vertical")
    ap.add_argument("lang")
    ap.add_argument("--dry-run", action="store_true",
                    help="print the change, write nothing")
    ap.add_argument("--root", default=ROOT,
                    help="repo root to read the funnel from and write into")
    args = ap.parse_args(argv)
    try:
        set_price(args.vertical, args.lang, args.root, args.dry_run)
    except (FileNotFoundError, ValueError, PriceError) as exc:
        print("error: %s" % exc)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
