#!/usr/bin/env python3
"""Check every LCSC code in a KiCad netlist against the JLCPCB parts catalogue.

usage: python3 hardware/tools/lcsc_check.py <netlist> [<netlist> ...] [--csv out.csv]

For each part with an LCSC field it reports the catalogue's model name, the
library type (basic/extended), the stock, and the unit price at qty 1. It flags
parts whose MPN does not appear in the catalogue model name, codes with no
stock, and parts with no LCSC code.
"""

from __future__ import annotations

import csv
import json
import os
import re
import sys
import time
import urllib.request

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import pcbgen  # noqa: E402

API = "https://jlcpcb.com/api/overseas-pcb-order/v1/shoppingCart/smtGood/selectSmtComponentList"


def lookup(code, cache={}):
    if code in cache:
        return cache[code]
    body = json.dumps({"keyword": code, "currentPage": 1, "pageSize": 5}).encode()
    req = urllib.request.Request(API, data=body, headers={"Content-Type": "application/json"})
    for attempt in range(3):
        try:
            with urllib.request.urlopen(req, timeout=30) as r:
                d = json.load(r)
            break
        except Exception:  # noqa: BLE001 — network hiccups: retry
            time.sleep(2 * (attempt + 1))
    else:
        cache[code] = None
        return None
    items = (d.get("data") or {}).get("componentPageInfo", {}).get("list") or []
    hit = next((i for i in items if i.get("componentCode") == code), None)
    cache[code] = hit
    return hit


def norm(s):
    return re.sub(r"[^A-Z0-9]", "", (s or "").upper())


def main():
    args = [a for a in sys.argv[1:] if not a.startswith("--")]
    out_csv = sys.argv[sys.argv.index("--csv") + 1] if "--csv" in sys.argv else None
    if out_csv in args:
        args.remove(out_csv)
    rows, problems = [], 0
    for net in args:
        comps, _ = pcbgen.load_netlist(net)
        groups = {}
        for ref, c in comps.items():
            if "exclude_from_bom" in c["props"] or not c["footprint"]:
                continue
            if "dnp" in c["props"] or c["fields"].get("DNP"):
                continue
            key = (c["fields"].get("LCSC", ""), c["fields"].get("MPN", ""), c["value"])
            groups.setdefault(key, []).append(ref)
        for (code, mpn, value), refs in sorted(groups.items()):
            status, model, lib, stock, price = "OK", "", "", "", ""
            if not code:
                status = "NO-LCSC"
            else:
                hit = lookup(code)
                if hit is None:
                    status = "NOT-FOUND"
                else:
                    model = hit.get("componentModelEn", "")
                    lib = hit.get("componentLibraryType", "")
                    stock = hit.get("stockCount", 0)
                    prices = hit.get("componentPrices") or []
                    price = prices[0]["productPrice"] if prices else ""
                    if mpn and norm(mpn)[:8] not in norm(model) and norm(model)[:8] not in norm(mpn):
                        status = "MPN-MISMATCH"
                    elif not stock:
                        status = "NO-STOCK"
            if status != "OK":
                problems += 1
            rows.append([os.path.basename(net), status, ",".join(sorted(refs)), len(refs), value, mpn, code, model, lib, stock, price])
    w = csv.writer(open(out_csv, "w", newline="") if out_csv else sys.stdout)
    w.writerow(["board", "status", "refs", "qty", "value", "MPN", "LCSC", "catalogue model", "type", "stock", "unit $ (qty1)"])
    w.writerows(rows)
    if out_csv:
        for r in rows:
            if r[1] != "OK":
                print(r[1], r[2], r[5], r[6], r[7], r[9])
    kinds = {}
    for r in rows:
        kinds[r[8] or "?"] = kinds.get(r[8] or "?", 0) + 1
    print(f"{len(rows)} BOM lines, {problems} flagged; library types: {kinds}", file=sys.stderr)


if __name__ == "__main__":
    main()
