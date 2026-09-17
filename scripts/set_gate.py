#!/usr/bin/env python3
"""Write a language's email gate into a funnel that is already on disk.

Console use only, run by hand on the server. No model call, no database —
pure JSON, the way set_price.py is: the funnel is read, its `lead_gate`
block is set from the master's block with this language's article URL,
gate copy and mail copy from scripts/lead_gate.json, and both copies are
written back byte-frozen otherwise. A translation is not touched, so the
eight generated funnels take the gate without a regeneration.

    cd ~/mazzin && python3 scripts/set_gate.py blinds hu
    cd ~/mazzin && python3 scripts/set_gate.py blinds en        # checks the master
    cd ~/mazzin && python3 scripts/set_gate.py blinds de --dry-run

What it does, in order:

  1. loads funnels/<vertical>.json, the master, and reads its `lead_gate`
     block — the anchors and the UTM campaign every language shares;
  2. loads funnels/<vertical>-<lang>.json (the master itself for `en`) and
     fails plainly when the funnel is not on disk — it patches, never
     generates;
  3. builds the block: the master's, with `article_url`, `copy` and `mail`
     replaced by the language's row, every master copy key present;
  4. writes it where the master carries it, in place when the funnel has
     one already, and writes funnels/<slug>.json and the byte-identical
     static/funnels/ copy, plus the -test twin when there is one.

Idempotent. Exit status 0 when the files are on disk and correct, 1
otherwise.
"""
import argparse
import json
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(HERE))
sys.path.insert(0, HERE)

import make_funnel as mf                        # noqa: E402

ROOT = mf.ROOT
TABLE = os.path.join(ROOT, "scripts", "lead_gate.json")


class GateError(Exception):
    pass


def load_table(path=TABLE):
    with open(path, encoding="utf-8") as fh:
        data = json.load(fh)
    return dict((k, v) for k, v in data.items() if not k.startswith("_"))


def _read(root, slug):
    path = os.path.join(root, "funnels", slug + ".json")
    if not os.path.isfile(path):
        return None
    with open(path, encoding="utf-8") as fh:
        return json.load(fh)


def gate_block(master_block, row):
    """The language's block: the master's shape, this language's words."""
    if not isinstance(row.get("article_url"), str) \
            or not row["article_url"].startswith("http"):
        raise GateError("the row has no article_url")
    block = json.loads(json.dumps(master_block))
    block["article_url"] = row["article_url"]
    for part in ("copy", "mail"):
        own = row.get(part) or {}
        missing = [k for k in (master_block.get(part) or {}) if k not in own]
        if missing:
            raise GateError("the row's %s lacks %s" % (part, ", ".join(missing)))
        extra = [k for k in own if k not in (master_block.get(part) or {})]
        if extra:
            raise GateError("the row's %s names keys the master does not: %s"
                            % (part, ", ".join(extra)))
        block[part] = dict((k, own[k]) for k in master_block[part])
    return block


def place(cfg, master, block):
    """Write `block` at `lead_gate`, where the master keeps it."""
    if "lead_gate" in cfg:
        cfg["lead_gate"] = block
        return cfg
    keys = list(master)
    before = keys[:keys.index("lead_gate")]
    rows = list(cfg.items())
    at = 0
    for index, (key, _) in enumerate(rows):
        if key in before:
            at = index + 1
    rows.insert(at, ("lead_gate", block))
    cfg.clear()
    cfg.update(rows)
    return cfg


def set_gate(vertical, lang, root=ROOT, dry_run=False, table=None):
    master = _read(root, vertical)
    if master is None:
        raise FileNotFoundError("no master funnel at funnels/%s.json"
                                % vertical)
    master_block = master.get("lead_gate")
    if not isinstance(master_block, dict):
        raise GateError("funnels/%s.json carries no lead_gate block"
                        % vertical)
    table = table or load_table()
    if lang not in table:
        raise ValueError("no language %r in scripts/lead_gate.json (have: %s)"
                         % (lang, ", ".join(sorted(table))))
    block = gate_block(master_block, table[lang])
    slug = vertical if lang == (master.get("locale") or "en") \
        else "%s-%s" % (vertical, lang)
    cfg = _read(root, slug)
    if cfg is None:
        raise FileNotFoundError(
            "no funnel at funnels/%s.json — set_gate patches a funnel that "
            "is on disk; generate it first with make_funnel.py" % slug)
    same = cfg.get("lead_gate") == block
    place(cfg, master, block)
    print("%s: lead_gate -> %s%s" % (slug, block["article_url"],
                                     "  already there" if same else ""))
    twin_slug = slug + "-test"
    twin = _read(root, twin_slug)
    if twin is not None:
        place(twin, master, block)
        print("%s: lead_gate -> %s" % (twin_slug, block["article_url"]))
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
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--root", default=ROOT)
    args = ap.parse_args(argv)
    try:
        set_gate(args.vertical, args.lang, args.root, args.dry_run)
    except (FileNotFoundError, ValueError, GateError) as exc:
        print("error: %s" % exc)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
