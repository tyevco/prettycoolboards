#!/usr/bin/env python3
"""Prove two KiCad netlists are electrically identical (the schgen equivalence gate).

usage: python3 tools/netlist_diff.py OLD.net NEW.net [--allow-rename] [--strict-fields]
                                     [--pin-rename REF:OLD=NEW ...]

Compares, from the `kicad-cli sch export netlist` (KiCad s-expression) format:
  * nets: the same set of nets, each with the same set of (ref, pin) members. A net is matched by its member
    set, so a renamed net is reported as a rename (an error unless --allow-rename, which only accepts renames of
    local nets, i.e. names that KiCad prefixed with a sheet path or auto-named "Net-(...)").
  * components: the same refs, each with the same value, footprint, DNP/BOM/board flags and BOM fields
    (MPN, Manufacturer, LCSC, ...). With --strict-fields every field and property must match too.
  * --pin-rename REF:OLD=NEW maps a pin of the old netlist to its new number before comparing (a library update that
    renumbered a pin, e.g. KiCad 10's USB-C shield S1 -> SH); each mapping used is reported as a NOTE.

A Datasheet of "~" (KiCad's "empty") equals an empty one: KiCad 9 exported "~", KiCad 10 exports "".

Exit 0 when identical, 1 with a list of differences otherwise. Positions, UUIDs, sheet paths and the like are
ignored: they change whenever the schematic is redrawn.
"""

from __future__ import annotations

import argparse
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import sexpr  # noqa: E402
from sexpr import find, find_all  # noqa: E402

# Properties that describe the drawing, not the circuit.
_LAYOUT_PROPS = {"Sheetname", "Sheetfile"}


def load(path: str):
    with open(path, encoding="utf-8") as f:
        root = sexpr.parse(f.read())
    nets: dict[str, frozenset] = {}
    for n in find_all(find(root, "nets"), "net"):
        name = str(find(n, "name")[1])
        members = frozenset((str(find(nd, "ref")[1]), str(find(nd, "pin")[1])) for nd in find_all(n, "node"))
        nets[name] = members
    comps: dict[str, dict] = {}
    for c in find_all(find(root, "components"), "comp"):
        ref = str(find(c, "ref")[1])
        info = {"value": str(find(c, "value")[1]) if find(c, "value") else "",
                "footprint": str(find(c, "footprint")[1]) if find(c, "footprint") else ""}
        flds = find(c, "fields")
        info["fields"] = {str(find(f, "name")[1]): str(f[2]) if len(f) > 2 else ""
                          for f in find_all(flds, "field")} if flds else {}
        if info["fields"].get("Datasheet") == "~":
            info["fields"]["Datasheet"] = ""
        info["props"] = {str(find(p, "name")[1]): str(find(p, "value")[1]) if find(p, "value") else ""
                         for p in find_all(c, "property") if str(find(p, "name")[1]) not in _LAYOUT_PROPS}
        comps[ref] = info
    return nets, comps


def is_local_name(name: str) -> bool:
    return name.startswith("/") or name.startswith("Net-(")


def diff(old_path: str, new_path: str, allow_rename: bool = False, strict_fields: bool = False,
         pin_rename: dict | None = None):
    on, oc = load(old_path)
    nn, nc = load(new_path)
    errs, notes = [], []
    if pin_rename:
        used = set()
        for name, mem in on.items():
            new_mem = frozenset(pin_rename.get(m, m) for m in mem)
            used |= {m for m in mem if m in pin_rename}
            on[name] = new_mem
        for (ref, old), (_, new) in sorted(pin_rename.items()):
            if (ref, old) in used:
                notes.append(f"pin renamed: {ref}.{old} -> {ref}.{new}")
            else:
                errs.append(f"--pin-rename {ref}:{old}={new}: no such pin in the old netlist")

    by_members_new = {}
    for name, mem in nn.items():
        by_members_new.setdefault(mem, []).append(name)
    matched_new = set()
    for name, mem in sorted(on.items()):
        if name in nn and nn[name] == mem:
            matched_new.add(name)
            continue
        cands = [c for c in by_members_new.get(mem, []) if c not in matched_new]
        if cands:
            new_name = cands[0]
            matched_new.add(new_name)
            msg = f"net renamed: {name!r} -> {new_name!r} ({len(mem)} pins)"
            if allow_rename and is_local_name(name) and is_local_name(new_name):
                notes.append(msg)
            else:
                errs.append(msg)
            continue
        if name in nn:
            matched_new.add(name)
            gone = sorted(mem - nn[name])
            added = sorted(nn[name] - mem)
            errs.append(f"net {name!r} members differ: missing {gone} extra {added}")
        else:
            errs.append(f"net {name!r} missing in new netlist: {sorted(mem)}")
    for name in sorted(set(nn) - matched_new):
        errs.append(f"net {name!r} only in new netlist: {sorted(nn[name])}")

    for ref in sorted(set(oc) | set(nc)):
        if ref not in nc:
            errs.append(f"component {ref} missing in new netlist")
            continue
        if ref not in oc:
            errs.append(f"component {ref} only in new netlist")
            continue
        a, b = oc[ref], nc[ref]
        for k in ("value", "footprint"):
            if a[k] != b[k]:
                errs.append(f"{ref}: {k} {a[k]!r} -> {b[k]!r}")
        keys = set(a["fields"]) | set(b["fields"])
        for k in sorted(keys):
            if a["fields"].get(k) != b["fields"].get(k):
                errs.append(f"{ref}: field {k} {a['fields'].get(k)!r} -> {b['fields'].get(k)!r}")
        pkeys = set(a["props"]) | set(b["props"])
        for k in sorted(pkeys):
            if a["props"].get(k) != b["props"].get(k):
                if strict_fields or k in ("dnp", "exclude_from_bom", "exclude_from_board"):
                    errs.append(f"{ref}: property {k} {a['props'].get(k)!r} -> {b['props'].get(k)!r}")
    stats = {"nets": (len(on), len(nn)), "components": (len(oc), len(nc)),
             "pins": (sum(len(m) for m in on.values()), sum(len(m) for m in nn.values()))}
    return errs, notes, stats


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("old")
    ap.add_argument("new")
    ap.add_argument("--allow-rename", action="store_true", help="accept renamed local nets (reported)")
    ap.add_argument("--strict-fields", action="store_true", help="every component property must match")
    ap.add_argument("--pin-rename", action="append", default=[], metavar="REF:OLD=NEW",
                    help="the old netlist's pin OLD of REF is NEW in the new one (a library renumbering)")
    a = ap.parse_args(argv)
    ren = {}
    for spec in a.pin_rename:
        ref, _, rest = spec.partition(":")
        old, _, new = rest.partition("=")
        if not (ref and old and new):
            ap.error(f"--pin-rename {spec!r}: expected REF:OLD=NEW")
        ren[(ref, old)] = (ref, new)
    errs, notes, stats = diff(a.old, a.new, a.allow_rename, a.strict_fields, ren)
    print(f"{a.old} -> {a.new}")
    print("  nets {0[0]} -> {0[1]}, components {1[0]} -> {1[1]}, net members {2[0]} -> {2[1]}".format(
        stats["nets"], stats["components"], stats["pins"]))
    for n in notes:
        print("  NOTE:", n)
    for e in errs:
        print("  DIFF:", e)
    print("  IDENTICAL" if not errs else f"  {len(errs)} difference(s)")
    return 1 if errs else 0


if __name__ == "__main__":
    sys.exit(main())
