"""Fabrication outputs: gerbers, drill, JLCPCB BOM, PDFs, renders (the CPL is jlc_cpl.py)."""

from __future__ import annotations

import csv
import os
import subprocess
import zipfile
from collections import OrderedDict

import pcbgen


def run(*args):
    r = subprocess.run(list(args), capture_output=True, text=True)
    if r.returncode != 0:
        raise RuntimeError(f"{' '.join(args)}\n{r.stdout}\n{r.stderr}")
    return r.stdout


def gerbers(pcb, outdir, layers=4):
    gdir = os.path.join(outdir, "gerbers")
    os.makedirs(gdir, exist_ok=True)
    cu = ["F.Cu", "In1.Cu", "In2.Cu", "B.Cu"] if layers == 4 else ["F.Cu", "B.Cu"]
    lay = cu + ["F.Paste", "B.Paste", "F.Silkscreen", "B.Silkscreen", "F.Mask", "B.Mask", "Edge.Cuts"]
    run("kicad-cli", "pcb", "export", "gerbers", "--layers", ",".join(lay), "--subtract-soldermask",
        "--use-drill-file-origin", "-o", gdir + "/", pcb)
    run("kicad-cli", "pcb", "export", "drill", "--format", "excellon", "--drill-origin", "plot",
        "--excellon-separate-th", "--generate-map", "--map-format", "gerberx2", "-o", gdir + "/", pcb)
    zpath = os.path.join(outdir, "gerbers.zip")
    with zipfile.ZipFile(zpath, "w", zipfile.ZIP_DEFLATED) as z:
        for f in sorted(os.listdir(gdir)):
            z.write(os.path.join(gdir, f), f)
    return zpath


def jlc_bom(netlist_path, out_csv):
    comps, _ = pcbgen.load_netlist(netlist_path)
    groups: "OrderedDict[tuple, list]" = OrderedDict()
    for ref, c in sorted(comps.items(), key=lambda kv: _refkey(kv[0])):
        if not c["footprint"] or c["fields"].get("DNP") or "dnp" in c["props"]:
            continue
        if "exclude_from_bom" in c["props"]:
            continue
        key = (c["value"], c["footprint"].split(":")[-1], c["fields"].get("LCSC", ""), c["fields"].get("MPN", ""))
        groups.setdefault(key, []).append(ref)
    with open(out_csv, "w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(["Comment", "Designator", "Footprint", "LCSC Part #", "MPN", "Qty"])
        for (val, fp, lcsc, mpn), refs in groups.items():
            w.writerow([val, ",".join(refs), fp, lcsc, mpn, len(refs)])
    return out_csv


def _refkey(ref):
    import re
    m = re.match(r"([A-Za-z#]+)(\d+)", ref)
    return (m.group(1), int(m.group(2))) if m else (ref, 0)
